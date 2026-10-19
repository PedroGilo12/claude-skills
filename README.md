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
   | A | Zephyr | twister + ztest + FFF on `native_sim`, twister coverage |
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

### Results

**Measured version: 0.2.0**, which iterated to 100% coverage. The "With skill" columns
combine iterations 1 and 2 of the skill, 5 runs in total. The "Without skill" column is
Claude with the same prompt and no skill.

In each coverage cell, the four numbers are function / line / branch coverage and the
mutation score. Values are means.

**`lib/net_buf/buf.c`**

| | Human reference | Without skill (3 runs) | With skill, iter. 1 (3 runs) | With skill, iter. 2 (2 runs) |
|---|---|---|---|---|
| Function | 86.7% | 99.0% | 100% | 100% |
| Line | 85.9% | 98.5% | 100% | 100% |
| Branch | 79.5% | 97.2% | 100% | 100% |
| **Mutation score** | **73.3%** | **91.4%** | **97.8%** | **94.8%** |
| Acceptance | — | 3/3 | 3/3 | 2/2 |

**`lib/net_buf/buf_simple.c`** (every branch sits inside `__ASSERT`, so there is no branch
metric)

| | Human reference | Without skill | With skill, iter. 1 | With skill, iter. 2 |
|---|---|---|---|---|
| Function | 90.8% | 100% | 100% | 100% |
| Line | 89.7% | 100% | 100% | 100% |
| **Mutation score** | **79.6%** | **100%** | **100%** | **100%** |
| Acceptance | — | 3/3 | 3/3 | 2/2 |

**`components/esp_partition/partition.c`**

| | Human reference | Without skill (3 runs) | With skill, iter. 1 (3 runs) | With skill, iter. 2 (2 runs) |
|---|---|---|---|---|
| Function | 100% | 100% | 100% | 100% |
| Line | 89.9% | 95.3% | 100% | 100% |
| Branch | 70.0% | 88.3% | 100% | 100% |
| **Mutation score** | **52.4%** | **71.4%** | **93.4%** | **94.5%** |
| Acceptance | — | **0/3** | 3/3 | 2/2 |

**Method expectations**, graded by an LLM grader:

| | Without skill | With skill |
|---|---|---|
| Iteration 1 (14 expectations) | 41% | 98% |
| Iteration 2 (23 stricter expectations, 3 runs graded) | — | 94% |

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
- **Cost:** one run takes 9–12 min and 2.3–3.4 M tokens (most are cached context re-reads),
  about US$ 2.5–3.4 each. These targets are large: 2 files and ~100 functions for net_buf.
  Smaller modules cost less.

### Known limitations

- **Version 0.3.0 is not benchmarked yet.** It lowered the default target from 100/100/100 to
  95/95/90 to save tokens on everyday use. Suites will be cheaper and a little smaller, and
  the mutation score may drop.
- **Validation is pending.** The skill was iterated on `net_buf` and `esp_partition` only.
  The validation targets are ready but have not run yet:
  - `onoff` (Zephyr state machine): reference 92.5% mutation score;
  - the ESP-IDF `log` component (5 files): reference 17.6–100%.
- **Path declaration:** in ESP-IDF runs, the environment/path declaration only appeared in
  the final message (2 of 2 runs), not at the start.
- **Trigger accuracy** with the plugin loaded has only been smoke-tested (2/2). The full
  40-query set (Portuguese and English) has not been run.

### Reproducing

```bash
python3 tools/fetch_targets.py                                    # pinned checkouts
python3 tools/measure.py net_buf                                  # human reference
python3 tools/bench_run.py 1 with_skill 1 --iteration 2           # one skill run
python3 tools/measure.py net_buf --root <ws>/zephyr --suite tests/lib/net_buf --label <label>
python3 tools/trigger_run.py --runs 2                             # trigger evals
```

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
