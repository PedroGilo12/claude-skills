#!/usr/bin/env python3
"""Monta o workspace que a skill recebe num eval: o checkout fixado, SEM a suíte humana e sem .git.

    python3 tools/prepare_workspace.py <alvo> <dest>      # cria <dest>/<checkout>/

<dest> precisa ficar FORA de qualquer repositório git (sugestão: ~/.cache/claude-skills-bench/...):
o CMake do ESP-IDF sobe os diretórios procurando .git e quebra se achar o repositório errado.

- Extrai a árvore do SHA com `git archive` (sem .git, para a suíte humana não ser recuperável
  pelo histórico), excluindo os caminhos `hidden` do alvo.
- Copia os submodules do checkout (o git archive não os inclui).
- Zephyr: cria `.venv` apontando para o venv do west (a skill deve achá-lo sozinha na raiz).
"""
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ROOT / "benchmarks" / ".targets"


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    name, dest = sys.argv[1], Path(sys.argv[2]).resolve()
    manifest = yaml.safe_load((ROOT / "benchmarks/targets.yaml").read_text())
    target = manifest["targets"][name]
    co = manifest["checkouts"][target["checkout"]]
    src = TARGETS / target["checkout"]
    for parent in [dest, *dest.parents]:
        if (parent / ".git").exists():
            sys.exit(f"{dest} está dentro do repositório git {parent}; use um destino fora (ex.: ~/.cache/claude-skills-bench/)")
    ws = dest / target["checkout"]
    if ws.exists():
        sys.exit(f"{ws} já existe")
    ws.mkdir(parents=True)

    excludes = [f":(exclude){h}" for h in target["hidden"]]
    archive = subprocess.Popen(["git", "archive", "--format=tar", co["sha"], "--", ".", *excludes],
                               cwd=src, stdout=subprocess.PIPE)
    subprocess.run(["tar", "-x", "-C", str(ws)], stdin=archive.stdout, check=True)
    if archive.wait():
        sys.exit("git archive falhou")

    subs = co.get("submodules") or []
    if subs == "all":
        subs = subprocess.run(["git", "config", "--file", ".gitmodules", "--get-regexp", r"\.path$"],
                              cwd=src, capture_output=True, text=True, check=True).stdout.split()[1::2]
    for sub in subs:
        shutil.rmtree(ws / sub, ignore_errors=True)
        shutil.copytree(src / sub, ws / sub, ignore=shutil.ignore_patterns(".git"))
    if co.get("venv"):
        (ws / ".venv").symlink_to(Path(co["venv"]).expanduser())

    for h in target["hidden"]:
        assert not (ws / h).exists(), h
    for s in target["sources"]:
        assert (ws / s).exists(), s
    print(ws)


if __name__ == "__main__":
    main()
