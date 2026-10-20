# claude-skills

A Claude Code plugin marketplace with skills I use in my own work.

| Plugin | Skill | What it does |
|---|---|---|
| `firmware-testing` | `embedded-unit-testing` | Generates unit test suites for embedded C firmware modules (Zephyr, ESP-IDF and others) |

## Installation

```text
/plugin marketplace add PedroGilo12/claude-skills
/plugin install firmware-testing@claude-skills
```

To try it from a local clone without installing:

```bash
claude --plugin-dir ./plugins/firmware-testing
```

---

## `embedded-unit-testing`

Generates a **unit test suite** for the `.c`/`.h` files you hand over, following the
specification-based testing method from Maurício Aniche (*Effective Software Testing*,
ch. 2): partitions → boundaries → test cases → automation → coverage.

Ask for it in plain words, e.g. *"write unit tests for src/drivers/pwm_ctrl.c"*. You don't
need to name the skill or the framework. It also triggers on Portuguese requests.

### What it does

1. **Detects the environment** and picks a path:

   | Path | Environment | Tooling |
   |---|---|---|
   | A | Zephyr | twister + ztest + FFF on `native_sim` (or `native_sim/native/64` when the host has no 32-bit toolchain), twister coverage |
   | B | ESP-IDF | ESP-IDF's native Unity in a host build, with gcov/gcovr |
   | C | Anything else | Follows the project's existing unit test framework (Unity, CMock, Ceedling, GoogleTest…). If there is none, it stops and asks which to use |

2. **Builds a numbered catalog** of partitions (`P1…`) and boundaries (`B1…`) for each
   function. The catalog goes at the top of the suite, and each test carries a
   `/* Covers: P2 + B1 */` annotation, so `grep P2` finds every test for that partition.
3. **Isolates dependencies** (HAL, drivers, kernel, flash, log) with fakes or stubs. It never
   modifies the files under test and never copies them into the test directory.
4. **Runs the suite and coverage**, then iterates until it reaches the default target of
   **95/95/90** (function/line/branch). It asks for 100% only if you request it. After every
   2 iterations that leave gaps, it stops and asks. Lines and branches that come only from
   log/assert macros are reported separately and don't count against the target.
5. **Records defects instead of hiding them.** When the code contradicts its own
   documentation, the skill writes a skipped test asserting the documented behavior plus a
   characterization test that pins the current behavior. The suite stays green and the bug
   shows up in every run.
6. **Points to the tools' own artifacts** (coverage HTML, runner output). It doesn't write
   its own report. All output is in English, whatever language you ask in.

**Out of scope:** integration, e2e, HIL, system and Robot Framework tests; scanning the
project for modules to test.

---

## Benchmark

The skill is measured against **real modules that already have a human-written unit test
suite**. That suite is the **reference**, and it is hidden from the skill during the run.

- **Coverage** is measured only on the target files, with the same exclusions on both sides
  (branches on log/assert lines are excluded).
- **Mutation testing** uses [mull](https://github.com/mull-project/mull) 0.34.1 (LLVM 18).
  The score is killed / (killed + survived). Proven-equivalent mutants are excluded from
  both sides.
- **Acceptance per file:**
  - at or above the reference on every metric;
  - at least 95/95/90 coverage;
  - at least 80% mutation score.

Each run is an isolated `claude -p` session with `claude-opus-5-5`, on a pinned checkout of
the target (`benchmarks/targets.yaml`).

### Targets

| Target | Version | Files | Reference suite |
|---|---|---|---|
| `net_buf` (Zephyr) | v4.2.1 | `lib/net_buf/buf.c`, `lib/net_buf/buf_simple.c` | `tests/lib/net_buf`: 67 ztest cases |
| `esp_partition` (ESP-IDF) | v5.4.2 | `components/esp_partition/partition.c` | `host_test/partition_api_test`: 19 Unity cases |
| `onoff` (Zephyr), validation | v4.2.1 | `lib/utils/onoff.c` | `tests/lib/onoff` |
| `log` (ESP-IDF), development since 0.3.3 | v5.4.2 | 5 files under `components/log/src/` | `host_test/log_test` (Catch2) |

Up to 0.3.2 the skill was iterated on `net_buf` and `esp_partition` only. The validation
targets were never used while writing it, so they show whether it overfits. `log` was a
validation target in iteration 4. Its results drove the 0.3.3 rules (slow tests, input
length), so it is now a development target and no longer counts as validation. Its
iteration-4 numbers below are still valid results for 0.3.2.

### Results

**Measured versions:**
- **0.2.0** iterated to 100% coverage (iterations 1 and 2).
- **0.3.1** stops at the 95/95/90 default target (iteration 3, 2 runs per target).
- **0.3.2** fixes the final-output gaps and was run on the validation targets (iteration 4).
- **0.3.3** adds the slow-test rule (1 s per test, state seam as last resort) and the
  input-length partition. Iteration 5: 2 runs on `log`, 1 on `net_buf`.

The "Without skill" column is Claude with the same prompt and no skill.

In each coverage cell, the four numbers are function / line / branch coverage and the
mutation score. Values are means.

**`lib/net_buf/buf.c`**

| | Human reference | Without skill (3 runs) | 0.2.0 iter. 1 (3 runs) | 0.2.0 iter. 2 (2 runs) | 0.3.1 iter. 3 (2 runs) | 0.3.3 iter. 5 (1 run) |
|---|---|---|---|---|---|---|
| Function | 86.7% | 99.0% | 100% | 100% | 100% | 100% |
| Line | 85.9% | 98.5% | 100% | 100% | 100% | 100% |
| Branch | 79.5% | 97.2% | 100% | 100% | 98.6% | 100% |
| **Mutation score** | **73.3%** | **91.4%** | **97.8%** | **94.8%** | **92.6%** | **95.8%** |
| Acceptance | — | 3/3 | 3/3 | 2/2 | 2/2 | 1/1 |

**`lib/net_buf/buf_simple.c`** (every branch sits inside `__ASSERT`, so there is no branch
metric)

| | Human reference | Without skill | 0.2.0 iter. 1 | 0.2.0 iter. 2 | 0.3.1 iter. 3 | 0.3.3 iter. 5 |
|---|---|---|---|---|---|---|
| Function | 90.8% | 100% | 100% | 100% | 100% | 100% |
| Line | 89.7% | 100% | 100% | 100% | 100% | 100% |
| **Mutation score** | **79.6%** | **100%** | **100%** | **100%** | **100%** | **100%** |
| Acceptance | — | 3/3 | 3/3 | 2/2 | 2/2 | 1/1 |

**`components/esp_partition/partition.c`**

| | Human reference | Without skill (3 runs) | 0.2.0 iter. 1 (3 runs) | 0.2.0 iter. 2 (2 runs) | 0.3.1 iter. 3 (2 runs) |
|---|---|---|---|---|---|
| Function | 100% | 100% | 100% | 100% | 100% |
| Line | 89.9% | 95.3% | 100% | 100% | 100% |
| Branch | 70.0% | 88.3% | 100% | 100% | 99.4% |
| **Mutation score** | **52.4%** | **71.4%** | **93.4%** | **94.5%** | **94.3%** |
| Acceptance | — | **0/3** | 3/3 | 2/2 | 2/2 |

**Method expectations**, graded by an LLM grader:

| | Without skill | With skill |
|---|---|---|
| Iteration 1 (14 expectations) | 41% | 98% |
| Iteration 2 (23 stricter expectations, 3 runs graded) | — | 94% |
| Iteration 3, v0.3.1 (same 23 expectations, 4 runs) | — | 92% |
| Iteration 4, v0.3.2, validation (23 expectations, 6 runs) | — | 93% (96% of the 19 qualitative ones) |
| Iteration 5, v0.3.3, development (24 expectations, 3 runs, new grader) | — | 89% (64/72) |

From iteration 5 on, the grader runs outside the skill-creator: a script
(`tools/check_run.py`) decides the mechanical expectations, and Sonnet (`tools/grade_qual.py`)
only the qualitative ones. The script is stricter than the old LLM grader: the path label
must appear before the first file write, not only in the final output.

#### Validation (v0.3.2, iteration 4)

**`lib/utils/onoff.c`**: 4 runs, 2 with an English prompt and 2 with a Portuguese one.

| | Human reference | 0.3.2 (4 runs) |
|---|---|---|
| Function | 100% | 100% |
| Line | 98.9% | 99.3% |
| Branch | 92.8% | 94.7% |
| **Mutation score** | **92.5%** | **93.1%** (93.0–93.5) |
| Acceptance | — | 4/4 |

**ESP-IDF `log` component**: 2 runs. Only run 2 could be measured (see below).

| File | Reference mutation | 0.3.2 run 2: line / branch / function | 0.3.2 run 2: mutation |
|---|---|---|---|
| `buffer/log_buffers.c` | 30.4% | 100 / 100 / 100% | 97.8% ✅ |
| `tag_log_level.c` | 68.0% | 100 / 100 / 100% | 100% ✅ |
| `linked_list/log_linked_list.c` | 17.6% | 100 / 100 / 100% | 76.5% ❌ (< 80%) |
| `cache/log_binary_heap.c` | 25.5% | 100 / 100 / 100% | ≥ 76.6% ❌ (< 80%) |
| `util.c` | 100% | 100 / 100 / 100% | 100% ✅ |

- Both runs wrote tests for the 29-bit generation counter overflow of the binary-heap cache.
  These tests make ~2^29 API calls and take 11–22 s in a normal build. In the
  mull-instrumented build they time out even at 60 s, so they can't be mutation-tested.
- Run 2 put the two overflow tests in separate binaries. Those binaries are left out of
  mutation, so mutants only they would kill count as survived, and 76.6% is a lower bound.
- Run 1 put the overflow test in the same binary as every other heap test, so
  `log_binary_heap.c` gets no mutants at all and the measurement is refused.
- Every file beats its human reference on every metric. Two files miss the 80% mutation floor.

#### Development (v0.3.3, iteration 5): `log`

2 runs, both pass acceptance. Coverage is 100% line / branch / function on all 5 files.

| File | Reference mutation | 0.3.2 run 2 | 0.3.3 run 1 | 0.3.3 run 2 |
|---|---|---|---|---|
| `buffer/log_buffers.c` | 30.4% | 97.8% | 100% | 97.8% |
| `tag_log_level.c` | 68.0% | 100% | 100% | 100% |
| `linked_list/log_linked_list.c` | 17.6% | 76.5% ❌ | 94.1% | 100% |
| `cache/log_binary_heap.c` | 25.5% | ≥ 76.6% ❌ | 91.5% | 89.4% |
| `util.c` | 100% | 100% | 100% | 100% |

- **Slow tests:** both runs first wrote the overflow test by brute force, measured it
  (36.8 s and ~22 s), and only then replaced it with a state seam that assigns
  `s_log_cache_max_generation`, declared in the final output. No test takes more than 1 s,
  and no binary is left out of mutation.
- **Overflow mutants:** 7 of 9 killed in both runs. The two survivors (L173, L176) write past
  the array or only show up on a *second* overflow. L173 is killed when the suite is built with
  ASan (supplementary measurement `log-iter5-102-espidf-log-run1-san.json`); the official
  measurement is without sanitizers, which add gcov branches.
- **Input length:** the linked-list mutants that survived 0.3.2 because every tag was short
  are now killed, except one that needs a memory oracle (killed in run 2 and with ASan).
- **`net_buf`:** no seam, and the slowest test takes 0.03 s. The 1.5 s test from iteration 2
  is gone.

### Reading the results

- **esp_partition:** this is where the skill matters most. Without it, Claude does not
  isolate the flash, does not iterate on coverage, and stays below 80% mutation score in all
  3 runs.
- **net_buf:** Claude without the skill already passes acceptance. The skill adds about
  4–6 points of mutation score on `buf.c` and the method: a traceable catalog, FFF, twister
  coverage and the defect report.
- **Real defects found in the targets.** These are bugs in the upstream code, recorded by the
  skill as a skipped test plus a characterization test:
  - `net_buf_clone` does not restore the pool's `avail_count` when the clone fails, with
    `CONFIG_NET_BUF_POOL_USAGE`.
  - `net_buf_user_data_copy` checks the size relation the opposite way from its
    documentation.
  - `net_buf_frag_add(NULL, frag)` adds a reference instead of taking ownership of the
    fragment's.
  - `esp_partition_register_external` returns `ESP_ERR_NOT_FOUND` instead of the documented
    `ESP_ERR_NO_MEM` when an allocation fails during table loading with
    `CONFIG_PARTITION_TABLE_MD5`.
  - `esp_partition_verify` does not compare `readonly` and `erase_size`, although its
    documentation says all fields must match.
  - `onoff_request` returns `-ENOTSUP` while the service is resetting after an error, where
    the header documents `-EIO` for a recorded error. Found in 3 of 4 validation runs; the
    4th recorded it only as a characterization test.
- **0.3.1 vs 0.2.0:** stopping at 95/95/90 instead of 100% cut cost by ~20% at a small
  quality price. Every run still passes acceptance. `partition.c` mutation is unchanged
  (94.3% vs 94.5%). `buf.c` dropped 2–5 points (92.6% vs 94.8–97.8%), still well above the
  human reference (73.3%) and the no-skill baseline (91.4%).
- **Validation:** on `onoff`, the skill's suite beats a strong human suite (93.1% vs 92.5%
  mutation) in all 4 runs. The Portuguese prompt gives the same quality. On `log`, coverage is
  100% everywhere and mutation beats the reference on every file. Two files stay below 80%.
  On `log_binary_heap.c` the reason is the unmeasurable overflow tests. On
  `log_linked_list.c` 4 mutants survive the suite itself, so that one is a real gap.
- **Cost:** a 0.3.1 run takes ~8 min, 1.5–2.4 M tokens (most are cached context re-reads) and
  US$ 2.2–2.6. 0.2.0 took 9–12 min, 2.3–3.4 M tokens and US$ 2.5–3.4. These targets are large:
  2 files and ~100 functions for net_buf. Smaller modules cost less: a 0.3.2 run on `onoff`
  takes ~4.5 min and US$ 1.4–1.5, and one on `log` takes ~7 min and ~US$ 2. In iteration 5
  (0.3.3), `log` took 8–9 min and US$ 2.2–2.4 per run, `net_buf` 12 min and US$ 3.3; the
  new grader added US$ 0.77 for the 3 runs.

### Known limitations

- **Fixed in 0.3.2.** Three expectations failed repeatedly in 0.3.1: the path label, the
  raw + excluded branch metrics, and saying which venv was used. 0.3.2 makes them mandatory
  lines of the final output, and all three passed in the 6 validation runs. The FFF
  expectation now allows kernel primitives to run for real on `native_sim` when the response
  says so. In 0.3.1, net_buf ran the kernel for real in 2 of 2 runs.
- **Fixed in 0.3.3.** Slow boundary tests: the skill no longer keeps a test that loops ~2^29
  times to reach a counter overflow. It keeps each test under 1 s and uses a state seam only
  after the public API and the build configuration can't reach the state.
- **Open in 0.3.3** (iteration 5):
  - **Path label too late.** All 3 runs state `Path A`/`Path B` only in the final output,
    not before the first file write.
  - **`Isolation:` line.** 1 of 3 runs reported the seam and the fakes under other headings
    instead of the mandatory line.
  - **FFF expectation.** The `net_buf` run faked nothing and forced failures with real pools
    sized to fail, and said so. The expectation still asks for a fake, so it may be too strict.
- **Open in 0.3.2:**
  - **Undocumented return codes.** The skill doesn't define whether an undocumented return
    code is a defect or a documentation gap, and the onoff runs disagreed on it.
  - **`Covers:` precision.** 2 of 6 runs had one annotation that claimed a partition its
    test doesn't exercise. Still seen in 2 of 3 runs of iteration 5.
  - **Progress-message language.** 1 Portuguese run sent one progress message in Portuguese.
    All code and the final output were in English.
  - **Raw coverage file location.** The raw branch command writes `coverage-raw.txt` at the
    project root instead of inside `twister-out/`.
- **Trigger accuracy** with the plugin loaded has only been smoke-tested (2/2). The full
  40-query set (Portuguese and English) has not been run.

### Reproducing

```bash
python3 tools/fetch_targets.py                                    # pinned checkouts
python3 tools/measure.py net_buf                                  # human reference
python3 tools/bench_run.py 1 with_skill 1 --iteration 3           # one skill run
python3 tools/measure.py net_buf --root <ws>/zephyr --suite tests/lib/net_buf --label <label>
python3 tools/trigger_run.py --runs 2                             # trigger evals
```

Grading a run (script, Sonnet, merge) and the iteration summary are described in
[`tools/README.md`](tools/README.md#fluxo-de-iteração-sem-skill-creator).

Details are in [`tools/README.md`](tools/README.md). The measurement results, with status per
mutant, are in `benchmarks/results/`. Run transcripts and workspaces stay out of git.

## Repository layout

```
.claude-plugin/marketplace.json
plugins/firmware-testing/
├── .claude-plugin/plugin.json
└── skills/embedded-unit-testing/
    ├── SKILL.md
    ├── references/        # spec-based testing heuristics, one file per path (A/B/C)
    ├── assets/            # Zephyr test project scaffold
    └── evals/             # development, validation and trigger evals
benchmarks/                # targets, equivalent mutants, results
tools/                     # fetch, workspace, run, measure, grade
```
