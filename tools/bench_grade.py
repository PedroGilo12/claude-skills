#!/usr/bin/env python3
"""Monta o grading.json de uma execução de benchmark (formato do viewer do skill-creator).

    python3 tools/bench_grade.py <run_dir>

Junta:
- grading-qual.json: expectations qualitativas avaliadas pelo grader (text/passed/evidence);
- measure.json: saída do tools/measure.py (ou {"error": "..."} se a medição foi recusada),
  que responde às expectations marcadas "[measured by tools/measure.py]";
- transcript.jsonl: métricas de execução (tempo e tokens o agregador lê do timing.json).
"""
import json
import sys
from collections import Counter
from pathlib import Path

QUANT = {  # trecho da expectation -> checks do vs_ref
    ">= the human reference, in each": ("line>=ref", "branch>=ref", "function>=ref"),
    ">= 95/95/90": ("line>=min", "branch>=min", "function>=min"),
    "Mutation score >= the human reference": ("mutation>=ref",),
    "Mutation score >= 80%": ("mutation>=min",),
}


def quant(text, measure):
    keys = next(v for k, v in QUANT.items() if k in text)
    if "error" in measure:
        return False, f"Medição recusada: {measure['error']}"
    bad, ok = [], []
    for src, v in measure["vs_ref"]["per_file"].items():
        for k in keys:
            res = v["checks"].get(k)
            metric = k.split(">=")[0]
            if metric == "mutation":
                got = f"{measure['mutation'][src]['score']}%"
            else:
                c, t = measure["coverage"][src][metric]
                got = f"{c}/{t}"
            (bad if res is False else ok).append(f"{src.split('/')[-1]} {metric} {got}")
    return not bad, ("Falhou: " + "; ".join(bad)) if bad else ("Ok: " + "; ".join(ok))


def main():
    run = Path(sys.argv[1])
    meta = json.loads((run.parent.parent / "eval_metadata.json").read_text())
    qual = {e["text"]: e for e in json.loads((run / "grading-qual.json").read_text())["expectations"]}
    measure = json.loads((run / "measure.json").read_text())

    exps = []
    for text in meta["assertions"]:
        if text.startswith("[measured by tools/measure.py]"):
            passed, evidence = quant(text, measure)
            exps.append({"text": text, "passed": passed, "evidence": evidence})
        elif text in qual:
            exps.append({"text": text, "passed": bool(qual[text]["passed"]), "evidence": qual[text]["evidence"]})
        else:
            sys.exit(f"expectation sem nota do grader: {text}")

    tools, chars = Counter(), 0
    for line in (run / "transcript.jsonl").read_text().splitlines():
        chars += len(line)
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        for c in (ev.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                tools[c["name"]] += 1
    passed = sum(e["passed"] for e in exps)
    grading = {
        "expectations": exps,
        "summary": {"passed": passed, "failed": len(exps) - passed, "total": len(exps),
                    "pass_rate": round(passed / len(exps), 2)},
        "execution_metrics": {"tool_calls": dict(tools), "total_tool_calls": sum(tools.values()),
                              "transcript_chars": chars},
        "eval_feedback": json.loads((run / "grading-qual.json").read_text()).get("eval_feedback"),
    }
    (run / "grading.json").write_text(json.dumps(grading, ensure_ascii=False, indent=2))
    print(f"{run}: {passed}/{len(exps)}")


if __name__ == "__main__":
    main()
