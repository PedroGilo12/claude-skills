#!/usr/bin/env python3
"""Condensa o transcript.jsonl de uma execução em transcript.md para o grader.

    python3 tools/condense_transcript.py <run_dir>

Mantém o prompt, todo o texto visível do assistente e cada chamada de ferramenta (entrada
truncada); resultados de ferramenta são truncados. O pensamento interno fica de fora: as
expectations avaliam o que o usuário vê e o que foi executado.
"""
import json
import sys
from pathlib import Path

IN_MAX, OUT_MAX = 600, 400


def cut(s, n):
    s = s if isinstance(s, str) else json.dumps(s, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f" …[+{len(s) - n} chars]"


def main():
    run = Path(sys.argv[1])
    md, n = [], 0
    for line in (run / "transcript.jsonl").read_text().splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        for c in content or []:
            if not isinstance(c, dict):
                continue
            n += 1
            if ev.get("type") == "user" and c.get("type") == "text":
                md.append(f"### [{n}] USER\n{c['text']}\n")
            elif c.get("type") == "text":
                md.append(f"### [{n}] ASSISTANT (visible text)\n{c['text']}\n")
            elif c.get("type") == "tool_use":
                inp = c.get("input") or {}
                if c["name"] in ("Write",):
                    inp = {"file_path": inp.get("file_path"), "content": cut(inp.get("content", ""), IN_MAX)}
                md.append(f"### [{n}] TOOL CALL {c['name']}\n{cut(inp, IN_MAX)}\n")
            elif c.get("type") == "tool_result":
                body = c.get("content")
                if isinstance(body, list):
                    body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                md.append(f"### [{n}] TOOL RESULT\n{cut(body or '', OUT_MAX)}\n")
        if ev.get("type") == "result":
            md.append(f"### FINAL RESULT\n{ev.get('result', '')}\n")
    (run / "transcript.md").write_text("\n".join(md))
    print(run / "transcript.md", sum(len(x) for x in md), "chars")


if __name__ == "__main__":
    main()
