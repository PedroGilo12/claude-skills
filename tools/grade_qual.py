#!/usr/bin/env python3
"""Avalia com um LLM (Sonnet, `claude -p`) só as expectations que o script não decidiu.

    python3 tools/grade_qual.py <run_dir>

Rode depois do tools/check_run.py. Entram no grader as expectations que:
- não são "[measured by tools/measure.py]" (essas o bench_grade.py tira do measure.json);
- não têm nota true/false em grading-auto.json (as null vão com a evidence do script).

Material do grader: mensagem final completa, arquivos-fonte da suíte e transcript.md
(tools/condense_transcript.py, gerado se faltar). Sem ferramentas: tudo vai no prompt.
Grava grading-qual.json (formato que o bench_grade.py lê) e grading-cost.json.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = "claude-sonnet-5-5"
SRC_EXT = (".c", ".h", ".cpp", ".txt", ".yaml", ".conf", ".cmake", ".mk")
MAX_FILE_CHARS = 60_000

SYSTEM = """You grade one run of an AI agent that generated a unit-test suite for embedded C code.
For each expectation, decide PASS or FAIL strictly from the material given (final message,
suite source files, condensed transcript). Rules:
- PASS only with concrete evidence; cite it (file:line, test name, quoted text, transcript step).
- If the material does not show it, FAIL and say what is missing.
- "Hint from script" lines are facts a deterministic checker measured; trust them as facts, but
  the verdict is yours.
- Evidence: one or two sentences, in Portuguese.
Also give eval_feedback: one short paragraph on expectations that look ambiguous or too
lenient/strict for this run (or "" if none)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "expectations": {"type": "array", "items": {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "passed": {"type": "boolean"},
                           "evidence": {"type": "string"}},
            "required": ["n", "passed", "evidence"]}},
        "eval_feedback": {"type": "string"},
    },
    "required": ["expectations", "eval_feedback"],
}


def pending(run):
    meta = json.loads((run.parent.parent / "eval_metadata.json").read_text())
    auto_file = run / "grading-auto.json"
    auto = {e["text"]: e for e in json.loads(auto_file.read_text())["expectations"]} if auto_file.exists() else {}
    todo = []
    for text in meta["assertions"]:
        if text.startswith("[measured by tools/measure.py]"):
            continue
        a = auto.get(text)
        if a and a["passed"] is not None:
            continue
        todo.append((text, a["evidence"] if a else None))
    return todo


def suite_sources(run):
    auto_file = run / "grading-auto.json"
    info = json.loads((run / "run.json").read_text())
    ws = Path(info["workspace"])
    suite = json.loads(auto_file.read_text()).get("suite_dir") if auto_file.exists() else None
    if not suite:
        return []
    created = json.loads((run / "changed.json").read_text())["created"]
    sys.path.insert(0, str(ROOT / "tools"))
    from check_run import ARTIFACT_RE
    files = [p for p in created if p.startswith(suite + "/") and not ARTIFACT_RE.search(p[len(suite) + 1:])
             and (p.endswith(SRC_EXT) or Path(p).name in ("Makefile", "CMakeLists.txt"))]
    out = []
    for p in sorted(files):
        text = (ws / p).read_text(errors="replace")
        if len(text) > MAX_FILE_CHARS:
            text = text[:MAX_FILE_CHARS] + f"\n…[truncado: +{len(text) - MAX_FILE_CHARS} chars]"
        out.append((p, text))
    return out


def final_message(run):
    for line in reversed((run / "transcript.jsonl").read_text().splitlines()):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "result":
            return ev.get("result") or ""
    return json.loads((run / "run.json").read_text()).get("final_message", "")


def main():
    run = Path(sys.argv[1])
    todo = pending(run)
    if not todo:
        (run / "grading-qual.json").write_text(json.dumps({"expectations": [], "eval_feedback": ""}, indent=2))
        print(f"{run}: nada para o LLM")
        return
    if not (run / "transcript.md").exists():
        subprocess.run([sys.executable, str(ROOT / "tools/condense_transcript.py"), str(run)], check=True,
                       capture_output=True)
    parts = ["# Expectations to grade\n"]
    for i, (text, hint) in enumerate(todo, 1):
        parts.append(f"{i}. {text}" + (f"\n   Hint from script: {hint}" if hint else ""))
    parts.append("\n# Final message of the run\n" + final_message(run))
    for p, text in suite_sources(run):
        parts.append(f"\n# Suite file: {p}\n```\n{text}\n```")
    parts.append("\n# Condensed transcript\n" + (run / "transcript.md").read_text())
    parts.append("\nReturn one entry per expectation above; `n` is its number in the list.")
    prompt = "\n".join(parts)

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}   # permite claude -p aninhado
    cmd = ["claude", "-p", "--model", MODEL, "--output-format", "json", "--tools", "",
           "--no-session-persistence", "--system-prompt", SYSTEM, "--json-schema", json.dumps(SCHEMA)]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=env, cwd=run, timeout=1800)
    try:
        res = json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"saída inválida do claude -p (rc={r.returncode}): {r.stdout[-500:]}{r.stderr[-500:]}")
    if res.get("is_error") or not res.get("structured_output"):
        sys.exit(f"grader falhou: {res.get('result', '')[:500]}")
    out = res["structured_output"]
    # O LLM devolve o número da expectation; o texto vem da lista, sem depender de cópia literal.
    by_n = {e["n"]: e for e in out["expectations"] if 1 <= e["n"] <= len(todo)}
    missing = [todo[i - 1][0] for i in range(1, len(todo) + 1) if i not in by_n]
    if missing:
        sys.exit(f"grader não respondeu: {missing}")
    out["expectations"] = [{"text": todo[i - 1][0], "passed": by_n[i]["passed"], "evidence": by_n[i]["evidence"]}
                           for i in range(1, len(todo) + 1)]
    (run / "grading-qual.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
    u = res.get("usage") or {}
    cost = {"model": MODEL, "cost_usd": round(res.get("total_cost_usd") or 0, 4), "prompt_chars": len(prompt),
            "tokens": sum(u.get(k, 0) for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                                 "cache_read_input_tokens"))}
    (run / "grading-cost.json").write_text(json.dumps(cost, indent=2))
    passed = sum(e["passed"] for e in out["expectations"])
    print(f"{run}: LLM {passed}/{len(out['expectations'])}, {cost['tokens']} tokens, US$ {cost['cost_usd']}")


if __name__ == "__main__":
    main()
