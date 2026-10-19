#!/usr/bin/env python3
"""Mede uma suíte de testes contra um alvo de benchmarks/targets.yaml: cobertura + mutação (mull).

    python3 tools/measure.py <alvo>                                   # suíte de referência
    python3 tools/measure.py <alvo> --root WS/esp-idf --suite DIR --cmd "make -C {suite} test" --label skill-v0.1.0

--root   raiz do checkout medido (padrão: benchmarks/.targets/<checkout>); pode ser um workspace
         criado por tools/prepare_workspace.py.
--suite  diretório(s) da suíte. Zephyr: projetos twister. Host: um diretório com build próprio.
--cmd    (só host) comando que compila E roda a suíte, com cwd = --root; {suite} é substituído.
         Os compiladores (gcc/cc/g++/c++/clang/clang++) são interceptados por um shim que
         acrescenta --coverage (cobertura) ou o plugin do mull (mutação).

Guardas: os `sources` precisam ser byte a byte os do SHA fixado; cada source precisa aparecer na
cobertura e ter mutantes (senão a suíte compilou uma cópia do módulo, e a medição é recusada).
Grava benchmarks/results/<alvo>-<label>.json. Zephyr: rode com o venv do west ativo, ou com
.venv na raiz do checkout.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ROOT / "benchmarks" / ".targets"
MULL_DIR = ROOT / "tools" / "mutation" / ".mull"
DEAD = {"Killed", "Timeout"}


class MeasureError(Exception):
    pass


NOTES = {"cmd_rc": [], "excluded_binaries": []}   # anomalias registradas no resultado


def run(cmd, log, **kw):
    with open(log, "a") as fh:
        fh.write(f"\n$ {cmd if isinstance(cmd, str) else shlex.join(cmd)}\n")
        fh.flush()
        return subprocess.run(cmd, stdout=fh, stderr=fh, **kw).returncode


def ensure_mull(cfg):
    stamp = MULL_DIR / "VERSION"
    if stamp.exists() and stamp.read_text() == cfg["version"]:
        return MULL_DIR / "usr"
    print(f"baixando mull {cfg['version']}...")
    with tempfile.TemporaryDirectory() as tmp:
        deb = Path(tmp) / "mull.deb"
        urllib.request.urlretrieve(cfg["url"], deb)
        if hashlib.sha256(deb.read_bytes()).hexdigest() != cfg["sha256"]:
            raise MeasureError("sha256 do pacote do mull não confere")
        shutil.rmtree(MULL_DIR, ignore_errors=True)
        subprocess.run(["dpkg-deb", "-x", str(deb), str(MULL_DIR)], check=True)
    stamp.write_text(cfg["version"])
    return MULL_DIR / "usr"


def check_integrity(target, co, root):
    """Os sources medidos precisam ser idênticos aos do SHA fixado."""
    pinned = TARGETS / target["checkout"]
    for src in target["sources"]:
        want = subprocess.run(["git", "rev-parse", f"{co['sha']}:{src}"], cwd=pinned,
                              capture_output=True, text=True, check=True).stdout.strip()
        got = subprocess.run(["git", "hash-object", str(root / src)],
                             capture_output=True, text=True, check=True).stdout.strip()
        if want != got:
            raise MeasureError(f"{src} foi alterado no checkout medido (integridade)")


SHIM = r"""
import os, subprocess, sys
SRC = (".c", ".cc", ".cpp", ".cxx")
real = os.environ["MEASURE_" + sys.argv[1]]
flags = os.environ.get("MEASURE_FLAGS", "").split()
# Fontes viram caminho absoluto: o filtro do mull (includePaths) compara o caminho gravado no
# debug info, que seria relativo num Makefile como `gcc ../src/x.c`.
args = [os.path.realpath(a) if a.endswith(SRC) and os.path.isfile(a) else a for a in sys.argv[2:]]
if os.environ.get("MEASURE_SPLIT") == "1":
    # Mutação: a cobertura da própria suíte (gcov) não serve e exigiria a runtime de profile do clang.
    args = [a for a in args if a not in ("--coverage", "-fprofile-arcs", "-ftest-coverage", "-lgcov")]
sources = [a for a in args if a.endswith(SRC) and os.path.isfile(a)]
single = {"-c", "-S", "-E", "-M", "-MM"} & set(args) or len(sources) < 2
if single or os.environ.get("MEASURE_SPLIT") != "1":
    os.execv(real, [real, *flags, *args])
# Mutação: o mull reprocessa o comando gravado e exige um arquivo por compilação.
# `cc a.c b.c -o x` vira uma compilação por fonte + link, como num build CMake.
rest, out, i = [], "a.out", 0
while i < len(args):
    if args[i] == "-o":
        out = args[i + 1]; i += 2; continue
    if args[i] not in sources:
        rest.append(args[i])
    i += 1
objs = []
for n, src in enumerate(sources):
    obj = f"{out}.measure{n}.o"
    rc = subprocess.call([real, *flags, *rest, "-c", src, "-o", obj])
    if rc:
        sys.exit(rc)
    objs.append(obj)
os.execv(real, [real, *flags, *objs, *rest, "-o", out])
"""


def write_shim(shim_dir):
    shim_dir.mkdir(parents=True, exist_ok=True)
    (shim_dir / "shim.py").write_text(SHIM)
    for name, var in [("gcc", "C"), ("cc", "C"), ("clang", "C"),
                      ("g++", "CXX"), ("c++", "CXX"), ("clang++", "CXX")]:
        p = shim_dir / name
        p.write_text(f'#!/bin/sh\nexec python3 "{shim_dir}/shim.py" {var} "$@"\n')
        p.chmod(0o755)


def shim_env(shim_dir, c, cxx, flags):
    env = dict(os.environ, MEASURE_C=c, MEASURE_CXX=cxx, MEASURE_FLAGS=flags,
               CC=str(shim_dir / "cc"), CXX=str(shim_dir / "c++"))
    env["PATH"] = f"{shim_dir}:{env['PATH']}"
    return env


class SuiteSnapshot:
    """Restaura o diretório da suíte (apaga artefatos de build) entre cobertura e mutação."""

    def __init__(self, suite, store):
        self.suite, self.store = Path(suite), Path(store)
        shutil.copytree(self.suite, self.store, symlinks=True)

    def restore(self):
        shutil.rmtree(self.suite)
        shutil.copytree(self.store, self.suite, symlinks=True)


def new_elfs(base, since):
    found = []
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d != "CMakeFiles"]   # executáveis de sondagem do CMake
        for f in files:
            p = Path(dirpath) / f
            try:
                if p.is_symlink() or not os.access(p, os.X_OK) or p.stat().st_mtime < since:
                    continue
                with open(p, "rb") as fh:
                    if fh.read(4) == b"\x7fELF" and not f.endswith((".so", ".o", ".a")):
                        found.append(str(p))
            except OSError:
                pass
    return found


VENV = None   # venv do checkout (targets.yaml), usado quando a raiz não tem .venv


def python_for(root):
    for venv in (root / ".venv", VENV):
        if venv and (venv / "bin" / "python").exists():
            return str(venv / "bin" / "python")
    return sys.executable


# ---------------------------------------------------------------- cobertura

def source_filters(sources):
    out = []
    for s in sources:
        out += ["--filter", "(.*/)?" + re.escape(s) + "$"]
    return out


def branch_exclude(target, co):
    """Padrão de branches ignorados: log/assert do checkout + wrappers de log do alvo."""
    pats = [co["branch_exclude"]] + ([target["branch_exclude_extra"]] if target.get("branch_exclude_extra") else [])
    return "|".join(f"(?:{p})" for p in pats)


def coverage_zephyr(root, target, co, sources, suites, out, log):
    dirs = []
    for i, suite in enumerate(suites):
        o = out / f"cov{i}"
        env = dict(os.environ, ZEPHYR_BASE=str(root), ZEPHYR_TOOLCHAIN_VARIANT="host")
        run([python_for(root), "scripts/twister", "--coverage", "--coverage-tool", "gcovr",
             "-p", "native_sim", "-p", "unit_testing", "-T", suite, "-O", str(o)], log, cwd=root, env=env)
        if list(o.rglob("*.gcda")):
            dirs.append(str(o))
    if not dirs:
        raise MeasureError(f"twister não gerou dados de cobertura; veja {log}")
    # Lê os .gcda/.gcno direto (como o twister faz), para aplicar a mesma exclusão de branch.
    summary = out / "coverage-summary.json"
    run(["gcovr", "-r", str(root), "--gcov-ignore-parse-errors=negative_hits.warn_once_per_file",
         "--merge-mode-functions=separate", *source_filters(sources),
         "--exclude-branches-by-pattern", branch_exclude(target, co),
         "--json-summary-pretty", "-o", str(summary), *dirs], log, cwd=root)
    return summary


def clean_suites(suites, clean, root, log):
    """Remove artefatos de build que a execução da skill deixou (senão nada recompila)."""
    for suite in suites:
        if clean:
            run(clean.format(suite=suite), log, shell=True, cwd=root, executable="/bin/bash")
        for g in Path(suite).rglob("*.gcda"):
            g.unlink()


def coverage_host(root, target, co, suites, cmd, out, log, clean):
    shim = out / "shim"
    write_shim(shim)
    env = shim_env(shim, "/usr/bin/gcc", "/usr/bin/g++", "--coverage")
    summary = out / "coverage-summary.json"
    clean_suites(suites, clean, root, log)
    for suite in suites:
        rc = run(cmd.format(suite=suite), log, shell=True, cwd=root, env=env, executable="/bin/bash")
        if rc:   # teste falhando não impede medir; registra (as guardas pegam suíte que nem compilou)
            NOTES["cmd_rc"].append({"phase": "coverage", "rc": rc})
    run(["gcovr", "-r", str(root), "--exclude-branches-by-pattern", branch_exclude(target, co),
         "--merge-mode-functions=separate", *source_filters(target["sources"]),
         "--gcov-ignore-errors=no_working_dir_found", "--gcov-ignore-parse-errors=all",
         "--json-summary-pretty", "-o", str(summary), *suites], log, cwd=root)
    return summary


def read_coverage(summary, sources):
    if not summary.exists():
        raise MeasureError("resumo de cobertura não foi gerado")
    files = {f["filename"]: f for f in json.loads(summary.read_text())["files"]}
    cov = {}
    for src in sources:
        f = files.get(src)
        if not f or not f["line_total"] or not f["line_covered"]:
            raise MeasureError(f"{src} sem cobertura: a suíte não compilou/executou o arquivo original "
                               "(cópia do módulo?)")
        cov[src] = {"line": [f["line_covered"], f["line_total"]],
                    "branch": [f["branch_covered"], f["branch_total"]],
                    "function": [f["function_covered"], f["function_total"]]}
    return cov


# ---------------------------------------------------------------- mutação

def mull_flags(mull):
    return f"-fpass-plugin={mull}/lib/mull-ir-frontend-18 -g -grecord-command-line"


def build_mutants_zephyr(root, suites, out, mull, log, env):
    bins = []
    flags = mull_flags(mull)
    for i, suite in enumerate(suites):
        o = out / f"mut{i}"
        z = dict(env, ZEPHYR_BASE=str(root), ZEPHYR_TOOLCHAIN_VARIANT="llvm")
        twister = [python_for(root), "scripts/twister", "--build-only", "-T", suite]
        # 64 bits é obrigatório: o runtime do mull falha em -m32.
        # --force-platform: suítes com `platform_allow: native_sim` (32 bits) também viram 64 bits.
        run(twister + ["-p", "native_sim/native/64", "--force-platform", "-O", str(o / "native_sim"),
                       f"-x=EXTRA_CFLAGS={flags}"], log, cwd=root, env=z)
        # unit_testing: o triple padrão do llvm é bare-metal (i686-pc-none-elf).
        run(twister + ["-p", "unit_testing", "-O", str(o / "unit_testing"), "-x=M64_MODE=1",
                       f"-x=EXTRA_CFLAGS=--target=x86_64-linux-gnu {flags}",
                       "-x=EXTRA_LDFLAGS=--target=x86_64-linux-gnu"], log, cwd=root, env=z)
        bins += glob.glob(str(o / "native_sim/**/zephyr/zephyr.exe"), recursive=True)
        bins += glob.glob(str(o / "unit_testing/**/testbinary"), recursive=True)
    return bins


def build_mutants_host(root, suites, cmd, out, mull, mcfg, log, env, clean):
    shim = out / "shim"
    write_shim(shim)
    env = dict(env, **{k: v for k, v in shim_env(
        shim, mcfg["cc"], mcfg["cxx"], mull_flags(mull) + " -Qunused-arguments").items()},
               MEASURE_SPLIT="1")
    clean_suites(suites, clean, root, log)
    start = time.time()
    for suite in suites:
        rc = run(cmd.format(suite=suite), log, shell=True, cwd=root, env=env, executable="/bin/bash")
        if rc:
            NOTES["cmd_rc"].append({"phase": "mutation", "rc": rc})
    return [b for s in suites for b in new_elfs(s, start)]


def run_mull(target, root, bins, out, mull, mcfg, env, log, runner_args):
    merged = {}
    for n, binary in enumerate(sorted(set(bins))):
        name = f"bin{n}"
        r = subprocess.run([str(mull / "bin/mull-runner-18"), "--workers", str(mcfg["workers"]),
                            "--reporters", "Elements", "--report-dir", str(out), "--report-name", name,
                            "--allow-surviving", binary, *runner_args],
                           cwd=out, env=env, capture_output=True, text=True)
        with open(log, "a") as fh:
            fh.write(f"\n$ mull-runner {binary}\n{r.stdout}{r.stderr}")
        report = out / f"{name}.json"
        if r.returncode and "Original test failed" in r.stdout + r.stderr:
            # O mull exige binário verde sem mutação; um binário com teste falhando fica fora
            # da mutação (seus mutantes contam pelos outros binários, ou como vivos).
            NOTES["excluded_binaries"].append(os.path.relpath(binary, out) if not binary.startswith(str(root))
                                              else os.path.relpath(binary, root))
            continue
        if r.returncode:
            raise MeasureError(f"mull-runner falhou em {binary}; veja {log}")
        if not report.exists():
            continue                          # binário sem mutantes dos sources (ex.: helper)
        for path, data in json.loads(report.read_text())["files"].items():
            rel = os.path.relpath(path, root)
            for m in data["mutants"]:
                s = m["location"]["start"]
                key = (rel, s["line"], s["column"], m["mutatorName"])
                merged[key] = m["status"] in DEAD or merged.get(key, False)
    return merged


def mutant_id(file, line, col, op):
    return hashlib.sha1(f"{file}:{line}:{col}:{op}".encode()).hexdigest()[:10]


def summarize_mutants(target_name, sources, merged):
    eq_file = ROOT / "benchmarks/equivalent-mutants.yaml"
    equivalent = (yaml.safe_load(eq_file.read_text()) or {}).get(target_name) or {}
    equivalent = {str(k) for k in equivalent}   # IDs só com dígitos chegam como int
    mutants, per_file = [], {s: {"killed": 0, "survived": 0, "equivalent": 0} for s in sources}
    for (file, line, col, op), dead in sorted(merged.items()):
        if file not in per_file:
            continue
        mid = mutant_id(file, line, col, op)
        status = "equivalent" if mid in equivalent else ("killed" if dead else "survived")
        mutants.append({"id": mid, "file": file, "line": line, "column": col, "operator": op, "status": status})
        per_file[file][status] += 1
    for src, f in per_file.items():
        counted = f["killed"] + f["survived"]
        if counted + f["equivalent"] == 0:
            raise MeasureError(f"{src} sem mutantes: a suíte não compilou o arquivo original (cópia do módulo?)")
        f["score"] = round(100 * f["killed"] / counted, 1) if counted else None
    return mutants, per_file


# ---------------------------------------------------------------- veredito

def pct(c, t):
    return None if not t else 100.0 * c / t


def parse_ratio(s):
    c, t = (int(x) for x in str(s).split("/"))
    return c, t


def verdict(target, acc, cov, mut):
    out, ok_all = {}, True
    ref_cov = target.get("baseline_coverage") or {}
    ref_mut = target.get("baseline_mutation") or {}
    for src in target["sources"]:
        checks = {}
        for metric in ("line", "branch", "function"):
            p = pct(*cov[src][metric])
            ref = pct(*parse_ratio(ref_cov[src][metric])) if src in ref_cov else None
            checks[f"{metric}>=ref"] = None if ref is None or p is None else p >= ref - 1e-9
            checks[f"{metric}>=min"] = None if p is None else p >= acc["coverage_min"][metric]
            checks[f"{metric}=target"] = None if p is None else p >= acc["coverage_target"][metric]
        if mut is not None:
            s = mut[src]["score"]
            ref = ref_mut.get(src, {}).get("score")
            checks["mutation>=ref"] = None if ref is None or s is None else s >= ref
            checks["mutation>=min"] = None if s is None else s >= acc["mutation_min"]
        passed = all(v is not False for k, v in checks.items() if not k.endswith("=target"))
        ok_all &= passed
        out[src] = {"checks": checks, "pass": passed}
    return {"per_file": out, "pass": ok_all}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target")
    ap.add_argument("--root")
    ap.add_argument("--suite", nargs="+")
    ap.add_argument("--cmd")
    ap.add_argument("--label", default="ref")
    ap.add_argument("--clean", help="(host) comando que apaga os artefatos de build da suíte; {suite} substituído")
    ap.add_argument("--runner-args", help="argumentos para o binário de teste (ex.: '--rng-seed 1')")
    ap.add_argument("--no-mutation", action="store_true")
    ap.add_argument("--sources", nargs="+", help="diagnóstico: mede só estes sources (o resultado não vale como aceite)")
    args = ap.parse_args()

    manifest = yaml.safe_load((ROOT / "benchmarks/targets.yaml").read_text())
    target = manifest["targets"][args.target]
    if args.sources:
        unknown = set(args.sources) - set(target["sources"])
        if unknown:
            raise MeasureError(f"sources fora do alvo: {sorted(unknown)}")
        target = dict(target, sources=args.sources)
    co = manifest["checkouts"][target["checkout"]]
    mcfg, acc = manifest["mull"], manifest["acceptance"]
    global VENV
    VENV = Path(co["venv"]).expanduser() if co.get("venv") else None
    root = Path(args.root).resolve() if args.root else TARGETS / target["checkout"]
    suites = [str((root / s).resolve()) if not Path(s).is_absolute() else s
              for s in (args.suite or target["baseline_suite"])]
    cmd = args.cmd or target.get("baseline_cmd")
    if target["kind"] == "host" and not cmd:
        raise MeasureError("alvo host precisa de --cmd")

    out = ROOT / "tools/mutation/out" / f"{args.target}-{args.label}"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    log = out / "measure.log"

    check_integrity(target, co, root)
    snaps = [SuiteSnapshot(s, out / f"snapshot{i}") for i, s in enumerate(suites)] \
        if target["kind"] == "host" else []
    try:
        print("cobertura...")
        if target["kind"] == "zephyr":
            summary = coverage_zephyr(root, target, co, target["sources"], suites, out, log)
        else:
            summary = coverage_host(root, target, co, suites, cmd, out, log, args.clean)
        cov = read_coverage(summary, target["sources"])
        for s in snaps:
            s.restore()

        mutants, mut = [], None
        if not args.no_mutation:
            print("mutação...")
            mull = ensure_mull(mcfg)
            include = "|".join(re.escape(str(root / s)) + "$" for s in target["sources"])
            (out / "mull.yml").write_text(yaml.safe_dump({"mutators": mcfg["mutators"], "includePaths": [include]}))
            env = dict(os.environ, MULL_CONFIG=str(out / "mull.yml"))
            if target["kind"] == "zephyr":
                bins = build_mutants_zephyr(root, suites, out, mull, log, env)
            else:
                bins = build_mutants_host(root, suites, cmd, out, mull, mcfg, log, env, args.clean)
            if not bins:
                raise MeasureError(f"nenhum binário de teste gerado para mutação; veja {log}")
            runner_args = shlex.split(args.runner_args) if args.runner_args is not None \
                else (target.get("baseline_runner_args") or []) if not args.suite else []
            merged = run_mull(target, root, bins, out, mull, mcfg, env, log, runner_args)
            mutants, mut = summarize_mutants(args.target, target["sources"], merged)
    finally:
        for s in snaps:
            s.restore()
    check_integrity(target, co, root)

    repo_commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True).stdout.strip() or None
    result = {
        "target": args.target, "label": args.label, "kind": target["kind"],
        "partial_sources": bool(args.sources),
        "suites": [os.path.relpath(s, root) for s in suites], "cmd": cmd if target["kind"] == "host" else None,
        "clean": args.clean,
        "target_ref": co["ref"], "target_sha": co["sha"], "repo_commit": repo_commit,
        "mull": mcfg["version"], "mutators": mcfg["mutators"], "date": datetime.date.today().isoformat(),
        "coverage": cov, "mutation": mut, "notes": NOTES,
        "vs_ref": None if args.label == "ref" else verdict(target, acc, cov, mut),
        "mutants": mutants,
    }
    dest = ROOT / "benchmarks/results" / f"{args.target}-{args.label}.json"
    dest.parent.mkdir(exist_ok=True)
    dest.write_text(json.dumps(result, indent=1) + "\n")

    print(f"\n{'arquivo':58} {'linha':>11} {'branch':>11} {'função':>9} {'mutação':>8}")
    for src in target["sources"]:
        c = cov[src]
        fmt = lambda m: f"{c[m][0]}/{c[m][1]}"
        score = f"{mut[src]['score']}%" if mut else "-"
        print(f"{src:58} {fmt('line'):>11} {fmt('branch'):>11} {fmt('function'):>9} {score:>8}")
    if result["vs_ref"]:
        print(f"\ncritério de aceite: {'PASSOU' if result['vs_ref']['pass'] else 'REPROVOU'}")
        for src, v in result["vs_ref"]["per_file"].items():
            bad = [k for k, ok in v["checks"].items() if ok is False and not k.endswith("=target")]
            print(f"  {src}: {'ok' if v['pass'] else 'falhou ' + ', '.join(bad)}")
    if NOTES["cmd_rc"] or NOTES["excluded_binaries"]:
        print(f"\natenção: {json.dumps(NOTES)}")
    print(f"\nresultado: {dest.relative_to(ROOT)}   log: {log.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        main()
    except MeasureError as e:
        sys.exit(f"ERRO: {e}")
