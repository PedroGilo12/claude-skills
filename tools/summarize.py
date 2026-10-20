#!/usr/bin/env python3
"""Resumo compacto de uma iteração de benchmark: o único arquivo que a sessão precisa ler.

    python3 tools/summarize.py <iteração | pasta da iteração>

Lê cada run_dir de plugins/.../embedded-unit-testing-workspace/iteration-<N>/ e grava
summary.md na pasta da iteração: versão da skill, tempo, custo, aprovação, expectations
reprovadas, mutação por arquivo, duração máxima de teste e seam.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL_WS = ROOT / "plugins/firmware-testing/skills/embedded-unit-testing-workspace"


def load(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def main():
    arg = Path(sys.argv[1])
    it = arg if arg.is_dir() else SKILL_WS / f"iteration-{sys.argv[1]}"
    rows, details, total = [], [], 0.0
    for run in sorted(it.glob("eval-*/*/run-*")):
        name = f"{run.parent.parent.name.removeprefix('eval-')} · {run.parent.name} · {run.name}"
        skill = load(run / "skill.json", {})
        timing = load(run / "timing.json", {})
        gcost = load(run / "grading-cost.json", {})
        grading = load(run / "grading.json")
        measure = load(run / "measure.json")
        info = load(run / "run.json", {})
        auto = load(run / "grading-auto.json", {})
        cost = (timing.get("cost_usd") or 0) + (gcost.get("cost_usd") or 0)
        total += cost
        if grading:
            s = grading["summary"]
            score = f"{s['passed']}/{s['total']}"
        else:
            score = "sem grading"
        facts = auto.get("facts") or {}
        slow = facts.get("max_test_seconds")
        rows.append(f"| {name} | {skill.get('version', '?')} ({skill.get('sha256', '')[:8]}) | "
                    f"{timing.get('total_duration_seconds', 0) / 60:.1f} | {cost:.2f} | "
                    f"{(timing.get('total_tokens') or 0) / 1e6:.2f} M | {score} | "
                    f"{'—' if slow is None else f'{slow:.2f}'} | {', '.join(facts.get('seam') or []) or '—'} |")
        d = [f"### {name}"]
        if info.get("error"):
            d.append(f"- **Erro da execução:** {info['error']}")
        if measure is None:
            d.append("- Sem measure.json")
        elif "error" in measure:
            d.append(f"- **Medição recusada:** {measure['error']}")
        else:
            for src, m in measure["mutation"].items():
                ok = measure["vs_ref"]["per_file"][src]["pass"]
                d.append(f"- `{src.split('/')[-1]}`: mutação {m['score']}% "
                         f"({m['killed']}/{m['killed'] + m['survived']}, eq {m['equivalent']}) {'✅' if ok else '❌'}")
            if measure.get("notes", {}).get("excluded_binaries"):
                d.append(f"- Binários fora da mutação: {measure['notes']['excluded_binaries']}")
        for e in (grading or {}).get("expectations", []):
            if not e["passed"]:
                d.append(f"- ❌ [{e.get('source', '?')}] {e['text'][:90]} — {e['evidence'][:160]}")
        details.append("\n".join(d))
    out = [f"# {it.name}: resumo", "",
           "| Execução | Skill | min | US$ (exec + grader) | tokens | expectations | maior teste (s) | seam |",
           "|---|---|---|---|---|---|---|---|", *rows, "", f"**Custo total:** US$ {total:.2f}", "", *details, ""]
    (it / "summary.md").write_text("\n".join(out))
    print(it / "summary.md")


if __name__ == "__main__":
    main()
