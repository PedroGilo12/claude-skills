#!/usr/bin/env python3
"""Roda UMA execução de eval da embedded-unit-testing com `claude -p` isolado.

    python3 tools/bench_run.py <eval_id> <with_skill|without_skill> <run> [--iteration 1]

- Workspace (fora do git): ~/.cache/claude-skills-bench/iteration-<N>/<eval>/<config>/run-<n>/ws/
  montado por tools/prepare_workspace.py, sem a suíte humana.
- with_skill carrega o plugin com --plugin-dir; without_skill não carrega nada.
- Se a execução termina perguntando algo ao usuário, retoma UMA vez com "continue".
- Saída no workspace do skill-creator (ignorado pelo git):
  plugins/firmware-testing/skills/embedded-unit-testing-workspace/iteration-<N>/<eval>/<config>/run-<n>/
  transcript.jsonl, timing.json, skill.json, changed.json, run.json.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins" / "firmware-testing"
SKILL = PLUGIN / "skills" / "embedded-unit-testing"
SKILL_WS = PLUGIN / "skills" / "embedded-unit-testing-workspace"
BENCH = Path.home() / ".cache" / "claude-skills-bench"
MODEL = "claude-opus-5-5"
TIMEOUT = 3 * 3600


def load_eval(eval_id):
    for f in ("evals.json", "validation-evals.json"):
        for e in json.loads((SKILL / "evals" / f).read_text())["evals"]:
            if e["id"] == eval_id:
                return e
    sys.exit(f"eval {eval_id} não encontrado")


def tree_state(base):
    state = {}
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != ".venv"]
        for f in files:
            p = Path(dirpath) / f
            try:
                st = p.lstat()
            except OSError:
                continue
            state[str(p.relative_to(base))] = [st.st_size, st.st_mtime_ns]
    return state


def skill_hash():
    h = hashlib.sha256()
    for p in sorted(SKILL.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(SKILL)).encode() + b"\0" + p.read_bytes())
    version = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())["version"]
    return {"version": version, "sha256": h.hexdigest()}


def claude(args, cwd, transcript, with_skill, max_turns):
    cmd = ["claude", "-p", *args, "--model", MODEL, "--output-format", "stream-json", "--verbose",
           "--dangerously-skip-permissions"]
    if with_skill:
        cmd += ["--plugin-dir", str(PLUGIN)]
    if max_turns:
        cmd += ["--max-turns", str(max_turns)]
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}   # permite claude -p aninhado
    with open(transcript, "a") as fh:
        try:
            subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            fh.write(json.dumps({"type": "bench_timeout", "seconds": TIMEOUT}) + "\n")
    events = []
    for line in Path(transcript).read_text().splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    results = [e for e in events if e.get("type") == "result"]
    return events, (results[-1] if results else None)


def run_error(result):
    """Execução inválida: sem resultado, erro do CLI ou corte por limite de uso."""
    if not result:
        return "sem evento result (timeout ou falha)"
    text = result.get("result") or ""
    if "hit your session limit" in text or "usage limit" in text.lower():
        return "cortada pelo limite de uso da conta"
    if result.get("is_error"):
        return f"erro do claude -p: {text[-200:]}"
    return None


def asks_user(result):
    text = (result or {}).get("result") or ""
    tail = [l.strip() for l in text.strip().splitlines() if l.strip()][-3:]
    return any(l.endswith("?") for l in tail)


def skills_invoked(events):
    names = []
    for e in events:
        for c in (e.get("message") or {}).get("content") or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                names.append((c.get("input") or {}).get("skill"))
    return names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("eval_id", type=int)
    ap.add_argument("config", choices=["with_skill", "without_skill"])
    ap.add_argument("run", type=int)
    ap.add_argument("--iteration", type=int, default=1)
    ap.add_argument("--prompt", help="teste do pipeline: substitui o prompt do eval")
    ap.add_argument("--max-turns", type=int)
    args = ap.parse_args()

    ev = load_eval(args.eval_id)
    eval_dir = f"eval-{ev['id']}-{ev['name']}"
    base = BENCH / f"iteration-{args.iteration}" / eval_dir / args.config / f"run-{args.run}"
    out = SKILL_WS / f"iteration-{args.iteration}" / eval_dir / args.config / f"run-{args.run}"
    if base.exists() or out.exists():
        sys.exit(f"execução já existe: {base} / {out}")
    out.mkdir(parents=True)
    meta = out.parent.parent / "eval_metadata.json"
    if not meta.exists():
        meta.write_text(json.dumps({"eval_id": ev["id"], "eval_name": ev["name"], "prompt": ev["prompt"],
                                    "assertions": ev["expectations"]}, ensure_ascii=False, indent=2))

    ws = base / "ws"
    target = ev["target"]
    co_dir = Path(subprocess.run([sys.executable, str(ROOT / "tools/prepare_workspace.py"), target, str(ws)],
                                 capture_output=True, text=True, check=True).stdout.strip())
    before = tree_state(ws)

    prompt = (args.prompt or ev["prompt"]).replace("{ws}", str(ws))
    transcript = out / "transcript.jsonl"
    t0 = time.time()
    events, result = claude([prompt], co_dir, transcript, args.config == "with_skill", args.max_turns)
    results, pauses = [result], 0
    if not run_error(result) and asks_user(result) and result.get("session_id"):
        pauses = 1
        events, result = claude(["--resume", result["session_id"], "continue"], co_dir, transcript,
                                args.config == "with_skill", args.max_turns)
        results.append(result)
    wall = time.time() - t0

    results = [r for r in results if r]
    usage = {}
    for r in results:
        for k, v in (r.get("usage") or {}).items():
            if isinstance(v, (int, float)):
                usage[k] = usage.get(k, 0) + v
    total_tokens = sum(usage.get(k, 0) for k in ("input_tokens", "output_tokens",
                                                  "cache_creation_input_tokens", "cache_read_input_tokens"))
    timing = {"total_tokens": total_tokens, "duration_ms": int(wall * 1000),
              "total_duration_seconds": round(wall, 1),
              "cost_usd": round(sum(r.get("total_cost_usd") or 0 for r in results), 2),
              "num_turns": sum(r.get("num_turns") or 0 for r in results), "usage": usage}
    (out / "timing.json").write_text(json.dumps(timing, indent=2))
    (out / "skill.json").write_text(json.dumps(skill_hash(), indent=2))

    after = tree_state(ws)
    changed = {"created": sorted(set(after) - set(before)),
               "modified": sorted(p for p in set(after) & set(before) if after[p] != before[p]),
               "deleted": sorted(set(before) - set(after))}
    (out / "changed.json").write_text(json.dumps(changed, indent=2))
    run_info = {"eval_id": ev["id"], "config": args.config, "run": args.run, "workspace": str(ws),
                "checkout_root": str(co_dir), "pauses_resumed": pauses,
                "ended_asking": asks_user(result), "skills_invoked": skills_invoked(events),
                "error": run_error(result),
                "final_message": (result or {}).get("result", "")[-3000:]}
    (out / "run.json").write_text(json.dumps(run_info, ensure_ascii=False, indent=2))
    print(json.dumps({k: run_info[k] for k in ("eval_id", "config", "run", "pauses_resumed",
                                                "skills_invoked", "error")} | {"timing": timing["total_duration_seconds"],
                                                                                "cost": timing["cost_usd"],
                                                                                "created": len(changed["created"]),
                                                                                "modified": len(changed["modified"])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
