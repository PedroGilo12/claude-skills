---
name: embedded-unit-testing
description: >-
  Generates a UNIT TEST suite for embedded firmware .c/.h files, following Maurício Aniche's
  specification-based testing (partitions → boundaries → cases → coverage). Detects the
  environment: Zephyr uses twister + ztest + FFF on native_sim; ESP-IDF uses native Unity in a
  host build + gcovr; anything else follows the project's existing test framework (Unity,
  CMock, Ceedling, GoogleTest…) or stops and asks if there is none. ALWAYS use it when the user
  asks to generate/write/create unit tests for .c/.h modules — e.g. "write unit tests for
  motor_ctrl.c", "create unit tests for the uart_driver", "cover these .c/.h files with
  tests", "test this function with partitions/boundaries", "95% coverage on this module", or
  in Portuguese "gera os testes unitários de motor_ctrl.c", "cria unit test pro uart_driver",
  "cobre esses .c/.h com testes". Triggers without the word "skill" and without naming the
  framework. Do NOT use for integration, e2e, HIL, system or Robot Framework tests; nor to
  scan the project for targets (only the files given); nor to just fill in a test file that
  another tool already scaffolded.
---

# Embedded unit testing (specification-based)

Generates a **unit test suite** for a set of `.c`/`.h` files the user hands over, using the 7
steps of specification-based testing from Maurício Aniche (*Effective Software Testing*,
ch. 2). The judgment that makes this a skill: **partitioning each function's domain well**
(the most valuable step), deriving boundaries, designing the smallest suite that still
catches bugs, automating it in the project's right framework and iterating until coverage
hits the target.

Read `references/specification-based-testing.md` **before Phase 3** — it is the calibration
for how to think about partitions and boundaries, and the pragmatics that avoid a bloated or
brittle suite.

## Scope invariants (read first)

- **English output.** Everything this skill produces is in **English**, even when the user
  writes in another language: test code, test names, comments, catalog, `Covers:`
  annotations, skip/ignore messages, the path declaration and the final summary.
- **Unit tests only.** Never generate integration, e2e, system, HIL or Robot Framework
  tests. The granularity is the isolated function/module, with dependencies faked/mocked.
- **Only the files given.** The suite is for the `.c`/`.h` set the user passed. **Do not
  scan the project** for other targets nor test neighboring modules on your own.
- **Never modify the target files** — not temporarily, not "to test and revert". The suite
  compiles the original `.c` files, with no copy in the test directory. To reach something
  hard, use the public API, fakes of the dependencies or a separate test binary. Setting a
  module's internal state from the test (state seam) is a **last resort**, allowed only under
  the slow-test rule in Phase 7.
- **Autonomous.** Generate, run and report without asking for confirmation to execute. There
  are **two** exceptions where you **stop and ask**: (a) Path C (neither Zephyr nor ESP-IDF)
  where you cannot identify any unit test framework (Phase 0); (b) every 2 coverage
  iterations without hitting the target (Phase 8).
- **No report written by you.** You do **not** write a results report. Run the tools and
  **point to the artifacts they generate** (coverage HTML, runner output, `tests.html`). The
  "result" is what the tool emits, not your prose. `tests.html` comes from the bundled
  `scripts/test_report.py`, a tool like gcovr. Copying it into the suite directory is part
  of the scaffold, not a change to the target files.
- **Coverage target:** function ≥ 95%, line ≥ 95%, branch ≥ 90% (**95/95/90**) by default.
  Once the target is met, stop iterating and list the remaining uncovered lines/branches.
  Go for 100/100/100 only if the user asks for it. Below the target only when what is
  missing is provably unreachable (log/assert noise, testability limitation of the module),
  with each remaining line/branch justified.

## The flow (Aniche's 7 steps → 9 phases)

The 7 steps are not a rigid pipeline — they are iterative (Phase 3 often reveals something
that sends you back to Phase 1). The phases below are the backbone.

| Phase | Aniche step | What you do |
|---|---|---|
| 0 | — | Detect environment → Path A (Zephyr), B (ESP-IDF) or C (other) |
| 1 | 1 Understand | Requirement, inputs, outputs of each given function |
| 2 | 2 Explore code | Map dependencies to isolate with fakes/mocks |
| 3 | 3 Partitions | **Numbered catalog of partitions** (the most important step) |
| 4 | 4 Boundaries | Numbered catalog of boundaries (on/off point) |
| 5 | 5 Design cases | Combine partitions/boundaries, reduce combinations |
| 6 | 6 Automate | Write the suite in the path's framework, with traceability |
| 7 | — | Run the tools: execution + coverage |
| 8 | 7 Augment | Iterate over gaps (coverage + catalog items without a test) |

---

## Phase 0 — Environment detection

Identify the environment of the project containing the given files, in this order, and pick
the path. **Robot Framework, HIL, integration pytest are NOT unit test frameworks** — they
never count in any path.

1. **Zephyr? → Path A.** Signals: `west.yml`/`west.yaml`; `CMakeLists.txt` with
   `find_package(Zephyr ...)`; `prj.conf`; `testcase.yaml`/`sample.yaml`; `tests/`;
   `ztest`/`ZTEST_SUITE`. Tooling: twister + ztest + FFF + coverage. Read
   `references/zephyr-path.md`.

2. **ESP-IDF? → Path B.** Signals: `CMakeLists.txt` with `idf_component_register(`;
   `sdkconfig`/`sdkconfig.defaults`; use of `$ENV{IDF_PATH}`/`idf.py`; a `main/` component.
   Tooling: **ESP-IDF's native Unity** (host build, `linux` target) + gcov/gcovr. Use Unity
   directly — **do not stop to ask**. Exception: if the project **already consistently uses
   another unit test framework** (Ceedling, GoogleTest…), follow that one. Read
   `references/espidf-path.md`.

3. **Other (neither Zephyr nor ESP-IDF) → Path C.** Inspect the existing **unit** test
   structure (Unity, CMock, Ceedling, GoogleTest, custom) and **follow** the project's
   pattern faithfully. If **no unit test framework** is found, **STOP and ask** the user
   which one to use — never assume a silent default in Path C. Read
   `references/non-zephyr-path.md`.

**State in the response text** (not only in your reasoning), before moving on, the chosen
path **with its literal label** (`Path A`, `Path B` or `Path C` — not just "this is Zephyr")
and the **concrete signals** that justify it, with file and what you found — e.g.
"Path A (Zephyr): `zephyr/west.yml`, `find_package(Zephyr)` in `tests/.../CMakeLists.txt`,
`ZTEST_SUITE` suites in `tests/lib/`." Repeat the same line in the final output.

---

## Phase 1 — Understand requirement, inputs and outputs

For **each function** the suite will cover, extract from reading the `.c`/`.h`:
- the **business rule**: what it does and what it must **not** do (corners included);
- the **inputs**: types, range/domain, constraints between variables;
- the **outputs**: how inputs become the result (and observable side effects: output
  written, error returned, motion emitted/not emitted).

Part of this is explicit; part is implicit domain rules (saturation, wrap, units, sign,
backlash) that you infer. Those implicit rules are where bugs hide.

## Phase 2 — Explore the code

Read the whole `.c`/`.h` and build the map of **dependencies to isolate**: HAL, drivers,
kernel/RTOS, I/O, time, calls into other modules. Each dependency becomes a fake/mock in
Phase 6, except kernel primitives that run deterministically on the host (see the path
file). Fake those too when a test needs to control them (failure, timeout, time). Also identify how the real logic is reached (direct public API, or `static`
functions via handle/vtable — call them through the real API, never invent a signature).

## Phase 3 — Identify the partitions (the most important step)

Apply the 3 lenses from `references/specification-based-testing.md` to each function: each
input in isolation, inputs in combination, and output classes. Consider NULL/empty and the
implicit domain rules. If the function has state, also partition by the **state** of the
module/context.

**Size is a category of its own.** For every variable-size input (string, buffer, array,
list), partition its length: NULL / empty / 1 / typical / **long**. Long means well past any
size the API or module states (buffer sizes, `*_MAX`, header fields), and at least 64 when
none is stated. When a module copies or allocates from the input's length, short values run
every branch, so coverage never shows the long case is missing. When the module **keeps** the
input (stores a copy, not the pointer), add a case that overwrites the caller's buffer after
the call and then queries with an equal but distinct value. That proves the module owns a
complete copy.

Produce, per function, a **named, numbered catalog** with stable IDs within the suite:
- Partitions: `<func>/P1, P2, …`
- Boundaries (filled in Phase 4): `<func>/B1, B2, …`

Each item gets a short description. This catalog is the suite's **traceability contract**
(materialized in Phase 6) and the source of truth for gaps (Phase 8). A well-done Phase 3
should cover almost everything on the first coverage pass.

## Phase 4 — Analyze the boundaries

For each boundary between neighboring partitions, add to the catalog the **on point** (the
value in the condition) and the **off point** (the nearest neighbor in the opposite
partition); equalities give one on and **two** off points. Drop a boundary already covered
by another case — do not duplicate. "Partition or boundary? It doesn't matter": what counts
is that the case exists.

## Phase 5 — Design the test cases

Combine the partitions across input categories, but **reduce the combinatorial explosion**:
test the exceptional (NULL/empty) **once** and do not combine it with everything; use the
domain to cut. Use a **single seed** input, varying only the minimum per case (eases
debugging). When in doubt, the simplest input. For inputs that do not take part in the
behavior, reasonable/realistic values. If a case has the same skeleton as several others,
plan it as **parameterized**. List the cases and, for each, the catalog IDs it exercises.

## Phase 6 — Automate (with mandatory traceability)

Write the suite in the detected path's framework (syntax, isolation and scaffold details in
`references/zephyr-path.md`, `references/espidf-path.md` or `references/non-zephyr-path.md`).

The Phase 3/4 catalog becomes **comments in the suite, at two levels**:

1. **Per-function header** — a block at the top of that function's test section, listing
   the full catalog (each partition/boundary with its ID and short description).
2. **Per-test annotation** — each test references which item(s) it exercises, e.g.
   `/* Covers: P3 + B1 */`.

Mandatory rules (this is what makes the traceability valuable):
- **No orphan test:** every test references ≥ 1 catalog item.
- **No orphan item:** every partition/boundary is exercised by ≥ 1 test. An item without a
  test is flagged as a **gap** (feeds Phase 8).
- **Stable, identical IDs** between header and annotations — so that a `grep "P4"` lists the
  header and every test touching that partition.
- A test covering a combination **lists all IDs** (`/* Covers: P2 + P5 */`).
- **`Covers:` tells the truth:** each annotated ID matches what the case actually exercises
  (input, state and assert), not just an item that exists in the catalog. Before Phase 7,
  reread the annotations against each test body and fix the ones that do not match.
- In Paths B and C, the same scheme, adapted to the framework's syntax (comment above each
  `TEST(...)`/`TEST_CASE(...)`/`TEST_F(...)`).

Canonical form (Path A, ztest):

```c
/*
 * Catalog — motor_ctrl_transform  (Phase 3 · spec-based testing)
 * Partitions:
 *   P1  p_axis_values == NULL        -> rejected, output not written
 *   P2  valid axis_count (1..N)      -> transforms
 *   P3  positive value               -> positive steps
 *   P4  negative value               -> sign preserved
 *   P5  zero value                   -> zero steps
 * Boundaries:
 *   B1  axis_count == N (max)        -> accepted
 *   B2  axis_count == N+1            -> rejected
 */

/* Covers: P2 + P3 */
ZTEST(motor_ctrl_suite, test_transform_positive_gives_positive_steps) { /* ... */ }

/* Covers: P1 */
ZTEST(motor_ctrl_suite, test_transform_null_input_is_rejected) { /* ... */ }
```

> Note: in recent Zephyr the runner **requires test names to start with `test_`**
> (`ZTEST(suite, test_...)`) — without that prefix twister does not collect the case.

### Defect found: code diverges from documentation

When the code contradicts what the header, the function comment or the API contract
document (e.g. returns a different error code than documented, does not restore state on
failure), **do not leave the suite red** and do not use `ZTEST_EXPECT_FAIL`. Write **two**
tests:

1. **Documented behavior, ignored with a reason** — the assert of what the docs promise,
   skipped with the reason: `TC_PRINT("BUG: ...\n"); ztest_test_skip();` (Path A) or
   `TEST_IGNORE_MESSAGE("BUG: ...")` (Path B). The `BUG:` prefix is what makes the test
   report list it as a known bug. Comment above: `/* Covers: Pn — BUG: <docs say X; code does Y> */`.
2. **Characterization** — pins the **current** behavior, so that any change (including the
   fix) shows up. Comment: `/* Covers: Pn — characterization of the BUG above */`.

The suite ends green, the bug shows up in every run (as skip/ignore) and the binary enters
the measurements. Syntax in the path files. List the defects in the final summary.

## Phase 7 — Execution + coverage

**Before running, activate the project environment.** The test tool is rarely on the global
`PATH` — it usually lives in a repo virtualenv. Do not conclude "cannot run" before looking
for and activating the environment (this applies to every path):

- Look for a venv at the firmware root (`.venv/`, `venv/`, `env/`) and use its binary
  (`.venv/bin/west`, `.venv/bin/python`) or `source .venv/bin/activate`. The venv is often a
  **symlink**: check with `test -e .venv/bin/activate` or `ls -laL` (which follow the link),
  never only with `ls -d`/`find -type d`. **Say what you found**: the venv path used, or "no
  venv in `<dirs checked>`".
- **Zephyr:** set `ZEPHYR_BASE` (e.g. `deps/zephyr`, or `west topdir`/`.west/config`) and,
  for the host, `ZEPHYR_TOOLCHAIN_VARIANT=host`. If `west` is not on the `PATH` but the
  Zephyr tree exists, run twister directly: `python3 $ZEPHYR_BASE/scripts/twister ...`.
- **ESP-IDF:** make sure the IDF environment is set (`. $IDF_PATH/export.sh` when it exists)
  for the host build; otherwise compile with `gcc` directly (see `espidf-path.md`).

Only after exhausting this search is it honest to report that execution could not run here.

**Context economy** (firmware builds are verbose and every turn rereads everything):
- Redirect build, twister and gcovr to a file (`> build.log 2>&1`) and show only the summary
  (`tail -n 30 build.log`, `grep -E 'error|FAIL|PASS|lines|branches' build.log`). Open the
  whole log only when the summary does not explain the failure.
- Write each test file whole in one go; fix with targeted edits.
- Group independent reads and checks in the same turn; do not reread files you already read.

Run the path's tool and **point to the artifacts it generates** (do not write a report):

- **Path A (Zephyr):** `west twister --coverage -p native_sim -T <suite_path>`, or
  `-p native_sim/native/64` when the host has no `gcc-multilib` (see `zephyr-path.md`).
  Artifacts: `twister-out/coverage/index.html`, `twister-out/coverage.json`,
  `twister-out/twister.xml`, `twister-out/twister.json`.
- **Path B (ESP-IDF):** host build with Unity + `gcov`/`gcovr` (see `espidf-path.md`);
  point to the coverage report (`coverage.html`/`.xml`) and the test output.
- **Path C (other):** the project's own runner + coverage (e.g. `ceedling gcov`, or
  `gcov`/`gcovr` over the test build). Keep and point to the emitted artifacts.

Details and troubleshooting in each path's file.

**Test report: `tests.html`, every path.** Copy `scripts/test_report.py` (from this skill)
into the suite directory and wire it so that **the command that runs the suite also writes
`tests.html`**. It lists every test as passed, failed, crashed, ignored or known bug. Write
it even when tests fail: run every binary, write the report, then return the runner's exit
code. The script reads Unity logs, ztest `handler.log` files and JUnit XML. The wiring for
each path is in its path file. Path B: the Makefile's `run` target, so `make` and
`make coverage` both produce it. Path A: the command after twister. Path C: the project's
test target.

**Slow tests: 1 s per test, in the normal host build.** After each run, read the per-test
durations from the runner (ztest/twister print them; Catch2 `--durations yes`; Unity
`UNITY_INCLUDE_EXEC_TIME`, or `time` per binary). A unit test that takes longer usually
brute-forces a state, e.g. ~2^29 calls to reach a counter wrap. It slows every CI run and
makes mutation testing impractical. Rework each such test with the **first** option that
works:
1. the public API reaches the state faster (a setter, a config call, a smaller instance);
2. a build-time setting the module already offers (`#ifndef` constant, Kconfig/`sdkconfig`);
3. **state seam, only when 1 and 2 are impossible:** the test file `#include`s the module's
   `.c` (and that binary does not link it separately) and **only assigns** the internal
   variable(s) needed to stand just before the state, e.g. `counter = MAX - 2`. The assigned
   state must satisfy the module's invariants (here: the counter above every stored value).
   Never call `static` functions this way, and never read internal variables in asserts:
   assertions still go through the public API;
4. otherwise keep the brute-force test, in its own binary, and name it in the final output.

Never use a seam for convenience or to save a few calls. It couples the test to internal
names, so it is justified only by a test that exceeded the limit.

## Phase 8 — Coverage iteration

Compare the coverage **reported by the tools** with the **95/95/90** target (or the one the
user asked for). Below the target, every reachable line/branch without a test is a gap; once
the target is met, stop and list what remains uncovered. For each gap, add cases using
**both sources**: the
numeric coverage (red lines/branches) and the catalog (items without a matching test). This
is Aniche's Step 7 — augment with judgment; also add variations your instinct points to.

Before "hunting" branch coverage: log/assert macros (`LOG_ERR`, etc.) inject runtime branches
that **are not decision points of the module**. If the branch target only fails to close because
of them (every real logic branch covered), document it as infrastructure noise — do not
invent a test to close a branch no input reaches. The same goes for testability limitations
of the module itself (e.g. a singleton with no reset hook): record it, do not force it. Only
these justifications allow stopping below the target.

**Which branch metric counts for the target:** the metric **without** the branches on
log/assert lines (`LOG_*`/`__ASSERT*` in Zephyr, which twister already excludes;
`ESP_LOG*`/`assert` in ESP-IDF, via `gcovr --exclude-branches-by-pattern`). **Measure and
report both numbers** — raw and without log/assert — saying which one you compared against
the target. Twister only prints the excluded one; the path files show the extra `gcovr` call
that gives the raw one. "Twister already excludes them" is not a raw number.

**Pace:** iterate in **blocks of 2 iterations**. After every 2 iterations, if reachable gaps
remain (coverage below the target without justification), **report the current state** (tool numbers +
remaining gaps) and **ask** the user whether to keep iterating or stop. Do not iterate
indefinitely on your own.

## Final output

Point to the artifacts generated by the tools: the **coverage HTML** (twister/gcovr) and the
**results output** of twister/the runner, with their paths. One closing sentence may say
whether the target was met according to the tool numbers (and which lines/branches were
left out and why) and which
catalog gaps (if any) remain — but **without** rewriting the results into a report of your
own.

Also state, in one line each — **every line is mandatory**, even when it repeats what you
said earlier:
- **Path:** the literal label and its signals (`Path A (Zephyr): <file> — <what was found>`);
- **Environment:** the venv path used, or "no venv in `<dirs checked>`", plus the toolchain
  setup (`ZEPHYR_BASE`/platform, or `export.sh`/plain `gcc`);
- **Branch coverage:** `raw X/Y (Z%) · without log/assert X/Y (Z%) — compared: without
  log/assert` (per target file);
- **Isolation:** what was faked/stubbed (FFF fakes, stub headers) and what ran for real, and
  why; any state seam (variable, value, and the test that exceeded 1 s without it) and any
  brute-force test kept over 1 s; or "no seam, no test over 1 s";
- **Test report:** the `tests.html` path and the counts from the `report: …` line the script
  printed (e.g. `build/tests.html` (0 failed · 0 crashed · 2 known bug · 0 ignored · 41 passed));
- the **defects** found (ignored test + characterization), or that you found none;
- if only **one configuration** was tested (Kconfig/`sdkconfig`/`#ifdef`), which one, and
  that branches of other configurations were not exercised.

## References of this skill

- `references/specification-based-testing.md` — partition/boundary heuristics and the
  pragmatics of §2.4. **Read before Phase 3.**
- `references/zephyr-path.md` — Path A: FFF, ZTEST/fixtures, scaffold for `native_sim`,
  environment activation and twister/coverage. Read when entering Path A.
- `references/espidf-path.md` — Path B: ESP-IDF's native Unity in a host build, isolation
  stubs, gcov/gcovr and gotchas. Read when entering Path B.
- `references/non-zephyr-path.md` — Path C: detect and follow the existing framework (or
  stop and ask if there is none), its runner and coverage. Read when entering Path C.
- `scripts/test_report.py` — writes `tests.html` from Unity logs, ztest `handler.log` or
  JUnit XML. Copy it into every suite (Phase 7).
- `assets/zephyr-scaffold/` — templates for `CMakeLists.txt`, `prj.conf` and `testcase.yaml`
  for a new `native_sim` suite with the fakes linked in.
