#!/usr/bin/env python3
"""Avalia por script as expectations mecânicas de uma execução de benchmark (sem LLM).

    python3 tools/check_run.py <run_dir>

Grava <run_dir>/grading-auto.json: {expectations: [{text, passed, evidence}], facts: {...}}.
- passed true/false: decidido aqui; o grader LLM (tools/grade_qual.py) não reavalia;
- passed null: precisa de julgamento; vai para o grader LLM com a evidence como pista.
Expectations sem verificação aqui não aparecem no arquivo (ficam todas com o LLM).

Rode depois do tools/measure.py: na Path B os binários de teste são executados de novo para
medir o tempo de parede.
"""
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"\b[A-Za-z_]\w*/[A-Z][A-Z0-9]*\b")   # P1, B2, R1, D4, PT…
TEST_SRC_RE = re.compile(r"\bZTEST(?:_F)?\s*\(|\bRUN_TEST\s*\(|\bTEST_CASE\s*\(")
# Artefatos de build/ferramenta que podem surgir fora da suíte sem ser "harness extra".
ARTIFACT_RE = re.compile(r"(^|/)(twister-out[^/]*|__pycache__|build[^/]*|\.cache)(/|$)|"
                         r"\.(pyc|gcda|gcno|o|d)$|(^|/)parsetab\.py$|(^|/)coverage[^/]*$")
PT_RE = re.compile(r"[ãõçâêôáéíóúà]|\b(não|teste|testes|função|cobertura|arquivo|então)\b", re.I)
SLOW_S = 1.0


# ---------------------------------------------------------------- leitura da execução

def load_run(run):
    meta = json.loads((run.parent.parent / "eval_metadata.json").read_text())
    info = json.loads((run / "run.json").read_text())
    changed = json.loads((run / "changed.json").read_text())
    events = []
    for line in (run / "transcript.jsonl").read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return meta, info, changed, events


def final_message(events, info):
    # run.json guarda só o fim da mensagem; o transcript tem o texto inteiro.
    results = [e for e in events if e.get("type") == "result"]
    return (results[-1].get("result") if results else None) or info.get("final_message") or ""


def blocks(events):
    """(tipo, conteúdo) na ordem: ('text', str), ('tool', (nome, input)), ('result', str)."""
    out = []
    for ev in events:
        content = (ev.get("message") or {}).get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for c in content or []:
            if not isinstance(c, dict):
                continue
            if c.get("type") == "text" and ev.get("type") == "assistant":
                out.append(("text", c["text"]))
            elif c.get("type") == "tool_use":
                out.append(("tool", (c["name"], c.get("input") or {})))
            elif c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                out.append(("result", body or ""))
    return out


def bash_runs(bl):
    """[(comando, resultado)] das chamadas Bash."""
    runs = []
    for i, (kind, val) in enumerate(bl):
        if kind == "tool" and val[0] == "Bash":
            res = next((v for k, v in bl[i + 1:] if k == "result"), "")
            runs.append((val[1].get("command", ""), res))
    return runs


# ---------------------------------------------------------------- contexto do alvo

class Ctx:
    def __init__(self, run):
        self.meta, self.info, self.changed, self.events = load_run(run)
        self.ws = Path(self.info["workspace"])
        self.co = Path(self.info["checkout_root"])
        ev = next(e for f in ("evals.json", "validation-evals.json")
                  for e in json.loads((ROOT / "plugins/firmware-testing/skills/embedded-unit-testing/evals" / f)
                                      .read_text())["evals"] if e["id"] == self.meta["eval_id"])
        target = yaml.safe_load((ROOT / "benchmarks/targets.yaml").read_text())["targets"][ev["target"]]
        self.path = target["path"]
        co_rel = os.path.relpath(self.co, self.ws)
        self.sources = [f"{co_rel}/{s}" for s in target["sources"]]
        self.final = final_message(self.events, self.info)
        self.bl = blocks(self.events)
        self.bash = bash_runs(self.bl)
        self.created = self.changed["created"]
        self.test_files = [p for p in self.created if p.endswith((".c", ".cpp")) and not ARTIFACT_RE.search(p)
                           and TEST_SRC_RE.search(self.read(p))]
        self.suite = self.suite_dir()
        self.suite_files = [p for p in self.created if self.suite and p.startswith(self.suite + "/")
                            and not ARTIFACT_RE.search(p[len(self.suite) + 1:])]

    def read(self, rel):
        try:
            return (self.ws / rel).read_text(errors="replace")
        except OSError:
            return ""

    def suite_dir(self):
        if not self.test_files:
            return None
        d = os.path.commonpath([os.path.dirname(p) for p in self.test_files])
        markers = ("testcase.yaml",) if self.path == "A" else ("Makefile", "CMakeLists.txt")
        cur = d
        while cur and cur != ".":
            if any((self.ws / cur / m).exists() for m in markers):
                return cur
            cur = os.path.dirname(cur)
        return d


# ---------------------------------------------------------------- verificações

def chk_path_label(c):
    label = f"Path {c.path}"
    first_edit = next((i for i, (k, v) in enumerate(c.bl) if k == "tool" and v[0] in ("Write", "Edit")), len(c.bl))
    early = [v for k, v in c.bl[:first_edit] if k == "text" and label in v]
    final_lines = [l for l in c.final.splitlines() if label in l]
    if not early:
        return False, f"'{label}' não aparece no texto visível antes da primeira escrita de arquivo"
    if not final_lines:
        return False, f"'{label}' não aparece na mensagem final"
    if not any("`" in l for l in final_lines):
        return False, f"linha final sem sinal concreto entre crases: {final_lines[0][:150]}"
    return True, f"início: {early[0][:120]!r}; final: {final_lines[0][:150]!r}"


def test_defs(src):
    """Índices de linha das definições de teste."""
    lines = src.splitlines()
    run_names = set(re.findall(r"\bRUN_TEST\s*\(\s*(\w+)", src))
    defs = []
    for i, l in enumerate(lines):
        if l.rstrip().endswith("\\"):
            continue                      # dentro de #define (teste gerado por macro): sem Covers próprio
        if re.match(r"\s*(ZTEST(?:_F|_USER)?|TEST_CASE)\s*\(", l):
            defs.append(i)
        else:
            m = re.match(r"\s*(?:static\s+)?void\s+(\w+)\s*\(\s*void\s*\)\s*\{?\s*$", l)
            if m and m.group(1) in run_names:
                defs.append(i)
    return lines, defs


def covers_before(lines, i):
    """IDs do comentário `Covers:` logo acima da linha i (None se não houver)."""
    j = i - 1
    while j >= 0 and not lines[j].strip():
        j -= 1
    if j < 0 or not lines[j].rstrip().endswith("*/"):
        return None
    k = j
    while k >= 0 and "/*" not in lines[k]:
        k -= 1
    block = "\n".join(lines[max(k, 0):j + 1])
    if "Covers:" not in block:
        return None
    body = block.split("Covers:", 1)[1]
    full = set(ID_RE.findall(body))
    rest = ID_RE.sub(" ", body)                       # IDs curtos (P1, B2), escopados pelo catálogo acima
    return full | {"*/" + k for k in re.findall(r"\b[A-Z]{1,3}\d+\b", rest)}


def catalog_entries(lines):
    """[(escopo, chave, linha)] do catálogo. Aceita `pfx/P1` em qualquer comentário e `P1`
    curto dentro de um bloco "Catalog — <função>" (o escopo vira o nome da função)."""
    entries, header = [], None
    for l in lines:
        if "Covers:" in l:
            continue
        if re.search(r"\bcatalog\b", l, re.I):
            header = l.lower()
        body = re.sub(r"^\s*(?:/\*+|\*|//)?", "", l)
        full = re.match(r"\s*(\w+)/([A-Z][A-Z0-9]*)\b", body)
        if full:
            entries.append((full.group(1).lower(), full.group(2), l))
        elif header is not None:
            first = re.match(r"\s*([A-Z]{1,3}\d+(?=\s)|[A-Z]{1,3}(?=\s{2,}))", body)   # "P10 ...", "PT  ..."
            more = re.findall(r"\s{2,}([A-Z]{1,2}\d+)\s{2,}", body[first.end():] if first else "")
            for k in ([first.group(1)] if first else []) + more:          # 2ª coluna: "...   B2  ..."
                entries.append((header, k, l))
        if header is not None and "*/" in l:
            header = None
    return entries


def chk_covers(c):
    if not c.test_files:
        return False, "nenhum arquivo de teste encontrado entre os criados"
    entries, covered, missing = [], set(), []
    for rel in c.test_files:
        lines, defs = test_defs(c.read(rel))
        for i in defs:
            ids = covers_before(lines, i)
            if not ids:
                missing.append(f"{Path(rel).name}:{i + 1}")
            else:
                covered |= ids
        entries += catalog_entries(lines)

    def matches(cid, e):
        pfx, key = cid.split("/", 1)
        return key == e[1] and (pfx == "*" or pfx.lower() == e[0] or pfx.lower() in e[0])

    orphan = sorted(cid for cid in covered if not any(matches(cid, e) for e in entries))
    gaps = [e for e in entries if re.search(r"\bgap\b", e[2], re.I)
            or re.search(r"\b" + re.escape(e[1]) + r"\b.{0,80}\bgap\b", c.final, re.I | re.S)]
    untested = sorted({f"{e[0][:20]}:{e[1]}" for e in entries
                       if e not in gaps and not any(matches(cid, e) for cid in covered)})
    catalog = entries
    if missing:
        return False, f"{len(missing)} teste(s) sem Covers: {', '.join(missing[:5])}"
    # Apelidos de escopo (`copy/P1` para "Catalog — esp_partition_copy") nem sempre dão para
    # mapear por script: divergência de mapeamento fica para o LLM, não reprova aqui.
    if orphan or untested:
        return None, (f"todos os testes têm Covers:; mapeamento a conferir. Fora do catálogo: "
                      f"{', '.join(orphan[:8]) or 'nenhum'}; catálogo sem teste/gap: {', '.join(untested[:8]) or 'nenhum'}")
    return True, f"{len(catalog)} itens no catálogo, todos cobertos ou declarados como gap ({len(gaps)} gaps)"


def chk_extra_harness(c):
    outside = [p for p in c.created + c.changed["modified"] + c.changed["deleted"]
               if not (c.suite and p.startswith(c.suite + "/")) and not ARTIFACT_RE.search(p)]
    if outside:
        return False, f"alterado fora da suíte ({c.suite}): {', '.join(outside[:6])}"
    return True, f"nada fora de {c.suite} além de artefatos de build"


def chk_targets(c):
    mod = [p for p in c.changed["modified"] + c.changed["deleted"] if p in c.sources]
    names = {Path(s).name for s in c.sources}
    copies = [p for p in c.created if Path(p).name in names]
    if mod:
        return False, f"arquivo-alvo modificado: {', '.join(mod)}"
    if copies:
        return False, f"cópia de arquivo-alvo criada: {', '.join(copies)}"
    return True, "nenhum arquivo-alvo modificado ou copiado"


def chk_env_line(c):
    line = next((l for l in c.final.splitlines() if re.search(r"\bEnvironment:", l)), None)
    return (True, line.strip()[:200]) if line else (False, "mensagem final sem a linha 'Environment:'")


RUNNER_RE = re.compile(r"\btwister\b|\bctest\b|\bmake\b[^|;&]*\b(run|test|coverage)\b|\./\S*test\S*|"
                       r"\S*/test_\w+(\.elf)?\b|idf\.py\b[^|;&]*\b(build|run)\b")
PASS_RE = re.compile(r"\b\d+ Tests \d+ Failures \d+ Ignored\b|SUITE PASS|PROJECT EXECUTION SUCCESSFUL|"
                     r"\bpassed\b.*\b\d+\b|\bPASS\b", re.I)


def chk_executed(c):
    runs = [(cmd, res) for cmd, res in c.bash if RUNNER_RE.search(cmd)]
    if not runs:
        return False, "nenhuma chamada Bash de runner (twister/ctest/make run/binário de teste)"
    ok = [(cmd, res) for cmd, res in runs if PASS_RE.search(res)]
    if ok:
        return True, f"{len(runs)} execução(ões) de runner; ex.: {ok[-1][0][:120]!r}"
    return None, f"{len(runs)} chamada(s) de runner, mas nenhuma saída com resumo de testes reconhecido"


def mentioned_artifacts(c):
    toks = re.findall(r"`([^`\s]+\.(?:html|xml|json|txt))`", c.final)
    return [t for t in toks if re.search(r"cov|twister", t, re.I)]


def artifact_exists(c, tok):
    tok = tok.lstrip("./")
    bases = [c.ws, c.co] + ([c.ws / c.suite] if c.suite else [])
    if any((b / tok).exists() for b in bases) or Path(tok).is_absolute() and Path(tok).exists():
        return True
    return any(p.endswith("/" + tok) or p == tok for p in c.created)


def chk_artifacts(c):
    toks = mentioned_artifacts(c)
    if not toks:
        return False, "a mensagem final não cita nenhum artefato de cobertura entre crases"
    gone = [t for t in toks if not artifact_exists(c, t)]
    if gone:
        return False, f"artefatos citados que não existem: {', '.join(gone[:5])}"
    return True, f"artefatos citados e existentes: {', '.join(toks[:5])}"


def chk_branch_line(c):
    pat = re.compile(r"raw\W*\s*\d+\s*/\s*\d+.*without log/assert\W*\s*\d+\s*/\s*\d+", re.I)
    lines = [l for l in c.final.splitlines() if pat.search(l)]
    if not lines:
        if re.search(r"\braw\b", c.final, re.I) and re.search(r"without log/assert", c.final, re.I):
            return None, "as duas métricas aparecem, mas fora do formato 'raw X/Y · without log/assert X/Y'"
        return False, "nenhuma linha 'raw X/Y · without log/assert X/Y' na mensagem final"
    if not re.search(r"compared", c.final, re.I):
        return False, "duas métricas presentes, mas sem dizer qual foi comparada ('compared')"
    return True, lines[0].strip()[:200]


def chk_english(c):
    hits = []
    for rel in c.test_files + [p for p in c.suite_files if p.endswith(".h")]:
        for n, l in enumerate(c.read(rel).splitlines(), 1):
            m = PT_RE.search(l)
            if m:
                hits.append(f"{Path(rel).name}:{n} {m.group(0)!r}")
    m = PT_RE.search(c.final)
    if m:
        hits.append(f"mensagem final: {c.final[max(m.start() - 30, 0):m.end() + 30]!r}")
    return (False, "; ".join(hits[:5])) if hits else (True, "sem marcas de português nos testes e na mensagem final")


def chk_ztest_api(c):
    srcs = {rel: c.read(rel) for rel in c.test_files}
    legacy = [Path(r).name for r, s in srcs.items() if re.search(r"\bztest_test_suite\s*\(|\bztest_unit_test\s*\(", s)]
    nosuite = [Path(r).name for r, s in srcs.items() if "ZTEST_SUITE" not in s]
    badname = [n for s in srcs.values() for n in re.findall(r"\bZTEST(?:_F|_USER)?\s*\(\s*\w+\s*,\s*(\w+)", s)
               if not n.startswith("test_")]
    proj = [m for m in ("CMakeLists.txt", "prj.conf", "testcase.yaml") if not (c.ws / (c.suite or "") / m).exists()]
    probs = ([f"API legada em {legacy}"] if legacy else []) + ([f"sem ZTEST_SUITE em {nosuite}"] if nosuite else []) + \
            ([f"nomes sem test_: {badname[:5]}"] if badname else []) + ([f"faltam no projeto: {proj}"] if proj else [])
    return (False, "; ".join(probs)) if probs else (True, f"ZTEST_SUITE/ZTEST, projeto twister completo em {c.suite}")


def chk_unity_host(c):
    no_unity = [Path(r).name for r in c.test_files if not re.search(r'#include\s*[<"]unity\.h[>"]', c.read(r))]
    asked = c.info.get("pauses_resumed") or c.info.get("ended_asking") or \
        any(k == "tool" and v[0] == "AskUserQuestion" for k, v in c.bl)
    if no_unity:
        return False, f"testes sem unity.h: {no_unity}"
    if asked:
        return False, "a execução parou para perguntar ao usuário"
    return True, "Unity (unity.h) em build de host, sem pausa para perguntar"


def chk_twister_cov(c):
    cmds = [cmd for cmd, _ in c.bash if "twister" in cmd and "--coverage" in cmd]
    html = [p for p in c.created if p.endswith("coverage/index.html")]
    js = [p for p in c.created if p.endswith("coverage.json")]
    cited = re.search(r"index\.html", c.final) and re.search(r"coverage\.json", c.final)
    if not cmds:
        return False, "nenhuma chamada de twister com --coverage"
    if not (html and js):
        return False, "coverage/index.html ou coverage.json não foram gerados"
    if not cited:
        return False, "a mensagem final não aponta index.html e coverage.json"
    return True, f"{cmds[-1][:120]!r}; {html[-1]}"


def chk_gcovr(c):
    cmds = [cmd for cmd, _ in c.bash if "gcovr" in cmd]
    reps = [p for p in c.created if re.search(r"\.(html|xml)$", p) and re.search(r"cov", p, re.I)]
    if not cmds:
        return False, "nenhuma chamada de gcovr"
    if not reps:
        return False, "nenhum relatório html/xml de cobertura gerado"
    if not any(Path(r).name in c.final for r in reps):
        return False, "a mensagem final não aponta o relatório"
    return True, f"{cmds[-1][:120]!r}; {reps[0]}"


def static_vars(src):
    names = set()
    for l in src.splitlines():
        m = re.match(r"\s*static\s+(?!inline\b)([^;(){}]*?)\b(\w+)\s*(\[[^\]]*\])?\s*(=[^;]*)?;", l)
        if m and "(" not in l.split("=")[0]:
            names.add(m.group(2))
    return names


def durations(c):
    """(maior duração em s, [descrições]) ou (None, motivo)."""
    if c.path == "A":
        tj = sorted((c.ws / p for p in c.created if p.endswith("twister.json")), key=lambda p: p.stat().st_mtime)
        if not tj:
            return None, ["nenhum twister.json"]
        data = json.loads(tj[-1].read_text())
        cases = [(float(tc.get("execution_time") or 0), tc["identifier"])
                 for s in data.get("testsuites", []) for tc in s.get("testcases", [])]
        if not cases:
            return None, ["twister.json sem testcases"]
        worst = max(cases)
        return worst[0], [f"{t:.2f}s {i}" for t, i in sorted(cases, reverse=True)[:3]]
    bins = []
    for p in c.created:
        f = c.ws / p
        try:
            if f.is_file() and os.access(f, os.X_OK) and f.read_bytes()[:4] == b"\x7fELF":
                bins.append(f)
        except OSError:
            pass
    if not bins:
        return None, ["nenhum binário de teste entre os criados"]
    times = []
    for b in bins:
        t0 = time.time()
        try:
            subprocess.run([str(b)], cwd=c.ws / (c.suite or ""), capture_output=True, timeout=120)
            times.append((time.time() - t0, b.name))
        except subprocess.TimeoutExpired:
            times.append((120.0, b.name + " (timeout)"))
    worst = max(times)
    return worst[0], [f"{t:.2f}s {n}" for t, n in sorted(times, reverse=True)]


def chk_slow_seam(c):
    worst, desc = durations(c)
    included, seam = [], []
    for s in c.sources:
        name = Path(s).name
        vars_ = static_vars(c.read(s))
        for rel in c.test_files:
            src = c.read(rel)
            if re.search(r'#include\s*"[^"]*' + re.escape(name) + '"', src):
                included.append(f"{Path(rel).name} inclui {name}")
                for v in vars_:
                    if re.search(r"\b" + re.escape(v) + r"\b\s*(\[[^\]]*\])?\s*(\.\w+)?\s*[-+*/|&^]?=(?!=)", src):
                        seam.append(f"{Path(rel).name}: {v}")
    iso = next((l.strip() for l in c.final.splitlines() if re.search(r"\bIsolation:", l)), "")
    c.facts = {"max_test_seconds": worst, "durations": desc, "target_c_included": included, "seam": seam,
               "isolation_line": iso}
    if worst is None:
        return None, f"duração não medida ({desc[0]}); seam: {seam or 'nenhum'}"
    slow = worst > SLOW_S
    if not slow and not seam:
        return True, f"maior duração {worst:.2f}s, sem seam ({'; '.join(desc[:2])})"
    return None, (f"maior duração {worst:.2f}s ({'; '.join(desc[:3])}); seam: {seam or 'nenhum'}; "
                  f"linha Isolation: {iso[:200]!r}")


CHECKS = [  # trecho da expectation -> verificação
    ("states the chosen path", chk_path_label),
    ("annotation with IDs identical", chk_covers),
    ("extra harness outside the suite", chk_extra_harness),
    ("Does not modify the target files", chk_targets),
    ("says which venv", chk_env_line),
    ("Actually EXECUTES the suite", chk_executed),
    ("Actually runs coverage and points", chk_artifacts),
    ("Reports both branch metrics", chk_branch_line),
    ("is in English", chk_english),
    ("new ztest API", chk_ztest_api),
    ("native Unity in a host build", chk_unity_host),
    ("Runs twister with --coverage", chk_twister_cov),
    ("Generates coverage with gcov/gcovr", chk_gcovr),
    ("No test exceeds 1 s", chk_slow_seam),
]


def main():
    run = Path(sys.argv[1])
    c = Ctx(run)
    c.facts = {}
    out = []
    for text in c.meta["assertions"]:
        fn = next((f for k, f in CHECKS if k in text), None)
        if fn:
            passed, evidence = fn(c)
            out.append({"text": text, "passed": passed, "evidence": evidence})
    if not c.facts:
        chk_slow_seam(c)                  # duração e seam entram no summary.md mesmo sem a expectation
    result ={"suite_dir": c.suite, "test_files": c.test_files, "expectations": out, "facts": c.facts}
    (run / "grading-auto.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    n = {v: sum(e["passed"] is v for e in out) for v in (True, False, None)}
    print(f"{run}: auto {len(out)}/{len(c.meta['assertions'])} "
          f"(passou {n[True]}, falhou {n[False]}, para o LLM {n[None]})")


if __name__ == "__main__":
    main()
