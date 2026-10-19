#!/usr/bin/env python3
"""Acionamento da embedded-unit-testing com o plugin carregado de verdade (`--plugin-dir`).

    python3 tools/trigger_run.py [--iteration 2] [--runs 2] [--workers 3] [--only 0 20]

Diferenças em relação ao `scripts.run_eval` do skill-creator (que deu 1/10 de positivos na
iteração 1, número não confiável):
- a skill é carregada como skill de plugin, não como comando de projeto;
- cada query roda num mini-projeto que contém os arquivos que ela cita, com os marcadores do
  ambiente (Zephyr, ESP-IDF ou CMake genérico), então o Claude não precisa sair procurando;
- conta acionamento se o `Skill` da embedded-unit-testing aparece em QUALQUER ponto do
  transcript, não só como primeira ferramenta.

Execuções curtas (`--max-turns 4`). Cada execução fica em
iteration-<N>/trigger/runs/q<i>-r<n>/ (transcript.jsonl, run.json); uma execução já feita
não é refeita, então dá para retomar depois de trocar de conta. Corte por limite de uso
interrompe tudo e apaga a execução cortada.
"""
import argparse
import json
import re
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench_run import BENCH, SKILL, SKILL_WS, claude, run_error, skills_invoked  # noqa: E402

SKILL_ID = "firmware-testing:embedded-unit-testing"
MAX_TURNS = 4
FILE_RE = re.compile(r"[\w./-]*\w\.(?:c|h|py)\b")

STUB_C = """#include <stdint.h>
#include <stddef.h>
#include "{h}"

/* Returns the clamped value; out must not be NULL. */
int {fn}(int32_t in, int32_t lo, int32_t hi, int32_t *out)
{{
    if (out == NULL || lo > hi) {{
        return -1;
    }}
    *out = in < lo ? lo : (in > hi ? hi : in);
    return 0;
}}
"""
STUB_H = """#pragma once
#include <stdint.h>

/** Clamps in to [lo, hi]. Returns 0, or -1 if out is NULL or lo > hi. */
int {fn}(int32_t in, int32_t lo, int32_t hi, int32_t *out);
"""


def environment(query):
    q = query.lower()
    if any(k in q for k in ("esp-idf", "esp_http", "main/", "components/")):
        return "espidf"
    if any(k in q for k in ("zephyr", "ztest", "twister", "subsys/", "nrf52", "net_buf", "app/src/")):
        return "zephyr"
    return "cmake"


def build_project(query, dest):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    env = environment(query)
    if env == "zephyr":
        (dest / "west.yml").write_text("manifest:\n  projects: []\n  self:\n    path: app\n")
        (dest / "prj.conf").write_text("CONFIG_LOG=y\n")
        (dest / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.20.0)\nfind_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})\n"
            "project(app)\n")
    elif env == "espidf":
        (dest / "CMakeLists.txt").write_text(
            "cmake_minimum_required(VERSION 3.16)\ninclude($ENV{IDF_PATH}/tools/cmake/project.cmake)\n"
            "project(app)\n")
        (dest / "sdkconfig.defaults").write_text("CONFIG_LOG_DEFAULT_LEVEL_INFO=y\n")
        (dest / "main").mkdir()
        (dest / "main" / "CMakeLists.txt").write_text('idf_component_register(SRCS "main.c")\n')
        (dest / "main" / "main.c").write_text("void app_main(void) {}\n")
    else:
        (dest / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(fw C)\n")
        if "unity" in query.lower():
            (dest / "test").mkdir()
            (dest / "test" / "unity.h").write_text("/* Unity (ThrowTheSwitch) */\n")
    cited = FILE_RE.findall(query)
    dirs = {Path(f).stem: Path(f).parent for f in cited if "/" in f}
    for f in cited:
        p = Path(f)
        if "/" not in f and p.stem in dirs:   # "battery_monitor.h" ao lado do .c citado
            p = dirs[p.stem] / p.name
        target = dest / p
        target.parent.mkdir(parents=True, exist_ok=True)
        fn = re.sub(r"\W", "_", p.stem)
        if p.suffix == ".c":
            target.write_text(STUB_C.format(h=p.stem + ".h", fn=fn))
            hdr = target.with_suffix(".h")
            if not hdr.exists():
                hdr.write_text(STUB_H.format(fn=fn))
        elif p.suffix == ".h":
            target.write_text(STUB_H.format(fn=fn))
        else:
            target.write_text("def main():\n    pass\n")
    return env


def one(i, n, query, it_dir):
    out = it_dir / "runs" / f"q{i:02d}-r{n}"
    if (out / "run.json").exists():
        return json.loads((out / "run.json").read_text())
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    ws = BENCH / it_dir.parent.name / "trigger" / f"q{i:02d}-r{n}"
    env = build_project(query, ws)
    events, result = claude([query], ws, out / "transcript.jsonl", True, MAX_TURNS)
    err = run_error(result)
    if err and "max_turns" in (result or {}).get("subtype", ""):
        err = None   # bater o --max-turns é o esperado aqui
    if err and "limite" in err:
        shutil.rmtree(out)
        return {"limit": True}
    skills = skills_invoked(events)
    info = {"query_index": i, "run": n, "env": env, "skills_invoked": skills,
            "triggered": SKILL_ID in skills or "embedded-unit-testing" in skills,
            "error": err}
    (out / "run.json").write_text(json.dumps(info, ensure_ascii=False, indent=2))
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iteration", type=int, default=2)
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--only", type=int, nargs=2, metavar=("INI", "FIM"), help="faixa de queries [INI, FIM)")
    args = ap.parse_args()

    queries = json.loads((SKILL / "evals" / "trigger-evals.json").read_text())
    it_dir = SKILL_WS / f"iteration-{args.iteration}" / "trigger"
    idx = range(*args.only) if args.only else range(len(queries))
    jobs = [(i, n) for i in idx for n in range(1, args.runs + 1)]

    limit = False
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(one, i, n, queries[i]["query"], it_dir): (i, n) for i, n in jobs}
        for f in futs:
            r = f.result()
            if r.get("limit"):
                limit = True
            else:
                print(f"q{futs[f][0]:02d} r{futs[f][1]}: triggered={r['triggered']} {r['skills_invoked']}"
                      + (f" ERRO {r['error']}" if r.get("error") else ""), flush=True)
    if limit:
        sys.exit("cortada pelo limite de uso da conta: troque de conta e rode de novo (retoma)")

    results = []
    for i, q in enumerate(queries):
        runs = [json.loads(p.read_text()) for p in sorted((it_dir / "runs").glob(f"q{i:02d}-r*/run.json"))]
        if not runs:
            continue
        trig = sum(r["triggered"] for r in runs)
        rate = trig / len(runs)
        results.append({"query": q["query"], "lang": q.get("lang"), "should_trigger": q["should_trigger"],
                        "trigger_rate": rate, "triggers": trig, "runs": len(runs),
                        "pass": (rate >= 0.5) == q["should_trigger"]})
    summary = {"total": len(results), "passed": sum(r["pass"] for r in results)}
    summary["failed"] = summary["total"] - summary["passed"]
    for kind, want in (("positives", True), ("negatives", False)):
        sel = [r for r in results if r["should_trigger"] is want]
        summary[kind] = f"{sum(r['pass'] for r in sel)}/{len(sel)}"
    (it_dir / "trigger-results.json").write_text(json.dumps(
        {"skill_name": "embedded-unit-testing", "method": "trigger_run.py (--plugin-dir, any position)",
         "results": results, "summary": summary}, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
