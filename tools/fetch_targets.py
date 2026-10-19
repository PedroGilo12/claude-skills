#!/usr/bin/env python3
"""Baixa os checkouts de benchmarks/targets.yaml em benchmarks/.targets/<nome>/, no SHA fixado.

Idempotente: um checkout já existente no SHA certo é mantido; em outro SHA, é abortado.
Usa `git clone --reference-if-able` com o clone local indicado no manifesto (se existir),
para não baixar de novo o histórico do Zephyr/ESP-IDF.
"""
import subprocess
import sys
from pathlib import Path

import yaml  # PyYAML (já vem com o ambiente do west/ESP-IDF)

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "benchmarks" / "targets.yaml"
DEST = ROOT / "benchmarks" / ".targets"


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()


def fetch(name, co):
    dest = DEST / name
    if dest.exists():
        head = git("rev-parse", "HEAD", cwd=dest)
        if head != co["sha"]:
            sys.exit(f"{dest}: HEAD {head} != {co['sha']} fixado; remova a pasta e rode de novo")
        print(f"{name}: ok ({co['ref']})")
    else:
        ref = Path(co.get("reference", "")).expanduser()
        print(f"{name}: clonando {co['repo']} @ {co['ref']}"
              + (f" (reference {ref})" if ref.is_dir() else ""))
        git("clone", "--no-checkout", "--reference-if-able", str(ref), co["repo"], str(dest))
        git("checkout", "--detach", co["sha"], cwd=dest)
    subs = co.get("submodules") or []
    if subs:
        git("submodule", "update", "--init", *([] if subs == "all" else ["--", *subs]), cwd=dest)


def main():
    manifest = yaml.safe_load(MANIFEST.read_text())
    DEST.mkdir(parents=True, exist_ok=True)
    for name, co in manifest["checkouts"].items():
        fetch(name, co)
    for name, t in manifest["targets"].items():
        base = DEST / t["checkout"]
        missing = [p for p in t["sources"] + t["baseline_suite"] if not (base / p).exists()]
        if missing:
            sys.exit(f"{name}: caminhos ausentes no checkout: {missing}")
        print(f"{name}: alvo e suíte de referência presentes")


if __name__ == "__main__":
    main()
