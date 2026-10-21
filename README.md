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

Generates a **unit test suite** for the `.c`/`.h` files you hand over, using the
specification-based testing method from Maurício Aniche (*Effective Software Testing*,
ch. 2).

Ask for it in plain words. You don't need to name the skill or the framework:

- *"write unit tests for src/drivers/pwm_ctrl.c"*
- *"gera os testes unitários de motor_ctrl.c"*

### How it works

The skill follows the seven steps of specification-based testing. The steps are iterative,
not a rigid pipeline: identifying partitions often sends it back to reread the code.

| # | Aniche's step | What the skill does |
|---|---|---|
| 0 | — | Detects the environment and picks a path (Zephyr, ESP-IDF or other) |
| 1 | Understand the requirement | Extracts each function's rule, inputs and outputs, including implicit domain rules (saturation, wrap, units, sign) |
| 2 | Explore the program | Maps the dependencies to isolate: HAL, drivers, kernel, I/O, time |
| 3 | Identify the partitions | Builds a numbered catalog (`P1…`) per function: each input alone, inputs combined, output classes, module state, input length. This is the most valuable step |
| 4 | Analyze the boundaries | Adds on and off points for each boundary (`B1…`) |
| 5 | Devise the test cases | Combines partitions while cutting the combinatorial explosion: exceptional inputs once, one seed input, parameterized cases |
| 6 | Automate | Writes the suite in the project's framework. Each test is annotated with what it covers (`/* Covers: P2 + B1 */`) |
| 7 | Augment | Runs the suite with coverage and adds cases for the gaps, from both the coverage report and the catalog items without a test |

The heuristics behind steps 3–5 are in
[`references/specification-based-testing.md`](plugins/firmware-testing/skills/embedded-unit-testing/references/specification-based-testing.md).

### Supported environments

| Path | Environment | Tooling |
|---|---|---|
| A | Zephyr | twister + ztest + FFF on `native_sim`, twister coverage |
| B | ESP-IDF | ESP-IDF's Unity in a host build, gcov/gcovr |
| C | Anything else | The project's existing unit test framework (Unity, CMock, Ceedling, GoogleTest…). If there is none, the skill asks which to use |

### What you get

- **A traceable suite.** The partition and boundary catalog sits at the top of the suite,
  and `grep P2` finds every test for that partition.
- **Isolated dependencies.** Fakes and stubs replace the HAL, drivers and kernel. The files
  under test are never modified or copied.
- **Coverage target of 95/95/90** (function/line/branch), or 100% if you ask. Lines and
  branches that come only from log/assert macros don't count against it. The skill stops
  and asks after every 2 iterations that leave gaps.
- **Defects recorded, not hidden.** When the code contradicts its documentation, the skill
  writes a skipped `BUG:` test with the documented behavior plus a characterization test of
  the current one. The suite stays green and the bug shows up in every run.
- **Fast tests.** Every test runs in under 1 s. A brute-force test is reworked through the
  public API or the build configuration first.
- **The tools' own reports.** Coverage HTML from twister or gcovr, and a `tests.html`
  listing every test as passed, failed, crashed, ignored or known bug. The skill doesn't
  write a report of its own.
- **English output**, whatever language you ask in.

**Out of scope:** integration, e2e, HIL, system and Robot Framework tests, and scanning the
project for modules to test.

---

## Performance

The skill is measured on real open-source modules that already have a human-written unit
test suite. That suite is the reference and is hidden from the skill. Each suite is scored
by coverage and by [mull](https://github.com/mull-project/mull) mutation score (the share of
injected bugs the tests catch). A run passes when every file is at or above the reference,
at 95/95/90 coverage or better, and at 80% mutation score or better.

Development targets were used to write the skill. Validation targets were never seen while
writing it, so they show whether it generalizes.

**Mutation score** (latest measured version, mean or range across runs):

| File | Target | Human reference | Claude without skill | With skill | Runs passing |
|---|---|---|---|---|---|
| `net_buf/buf.c` (Zephyr) | development | 73.3% | 91.4% | 95.8% | 1/1 |
| `net_buf/buf_simple.c` (Zephyr) | development | 79.6% | 100% | 100% | 1/1 |
| `esp_partition/partition.c` (ESP-IDF) | development | 52.4% | 71.4% (0/3 pass) | 94.3% | 2/2 |
| `log`, 5 files (ESP-IDF) | development | 17.6–100% | — | 89.4–100% | 2/2 |
| `utils/onoff.c` (Zephyr) | validation | 92.5% | — | 93.1% | 4/4 |
| `zbus/zbus.c` (Zephyr) | validation | 78.0% | — | 84.7–91.5% | 1/3 |
| `zbus/zbus_runtime_observers.c` (Zephyr) | validation | 91.2% | — | 89.2–91.9% | 1/3 |

**Coverage**, line / branch / function (same runs as above):

| File | Human reference | Claude without skill | With skill |
|---|---|---|---|
| `net_buf/buf.c` | 85.9 / 79.5 / 86.7% | 98.5 / 97.2 / 99.0% | 100 / 100 / 100% |
| `net_buf/buf_simple.c`¹ | 89.7 / — / 90.8% | 100 / — / 100% | 100 / — / 100% |
| `esp_partition/partition.c` | 89.9 / 70.0 / 100% | 95.3 / 88.3 / 100% | 100 / 99.4 / 100% |
| `log`, 5 files | 52.8–100 / 41.7–100 / 57.1–100% | — | 100 / 100 / 100% |
| `utils/onoff.c` | 98.9 / 92.8 / 100% | — | 99.3 / 94.7 / 100% |
| `zbus/zbus.c` | 99.6 / 95.1 / 100% | — | 99.2–100 / 96.2–98.6 / 100% |
| `zbus/zbus_runtime_observers.c` | 98.6 / 95.2 / 100% | — | 98.7–100 / 96.8–98.4 / 100% |

¹ Every branch in `buf_simple.c` sits inside `__ASSERT`, so it has no branch metric.

The skill reaches the 95/95/90 target on every file, and 100% on most.

- **Where the skill matters most:** on `esp_partition`, Claude without the skill doesn't
  isolate the flash or iterate on coverage, and no run passes.
- **Generalization:** on the validation targets the skill matches or beats strong human
  suites. On `zbus`, 2 of 3 runs fall just short of the reference.
- **Same quality in Portuguese:** prompts in Portuguese and English give equivalent suites.

### Version history

| Version | Main change |
|---|---|
| 0.2.0 | First benchmarked version. Iterates to 100% coverage |
| 0.3.1 | Stops at the 95/95/90 default target, about 20% cheaper at a small cost in mutation score |
| 0.3.2 | Mandatory final-output lines: path, environment, raw and filtered branch coverage |
| 0.3.3 | 1 s limit per test, input-length partitions |
| 0.3.4 | `tests.html` test report on every path |

### Real defects found

Bugs in the upstream code, recorded by the skill as a skipped test plus a characterization
test:

- `net_buf_clone` doesn't restore the pool's `avail_count` when the clone fails.
- `net_buf_user_data_copy` checks the size relation the opposite way from its documentation.
- `net_buf_frag_add(NULL, frag)` adds a reference instead of taking ownership of the fragment's.
- `esp_partition_register_external` returns `ESP_ERR_NOT_FOUND` instead of the documented
  `ESP_ERR_NO_MEM` on an allocation failure.
- `esp_partition_verify` doesn't compare `readonly` and `erase_size`, although its
  documentation says all fields must match.
- `onoff_request` returns `-ENOTSUP` where the header documents `-EIO`.
- zbus: a thread publishing at `ZBUS_MIN_THREAD_PRIORITY` keeps its boosted priority.

### Known limitations

- **Memory leaks go unnoticed.** Tests don't check that a removed object is freed.
- **Unreachable code.** The skill can declare code unreachable without proving it.
- **Caller-side boundaries.** It partitions a function's inputs but can miss the caller's
  own state, such as the publishing thread's priority.
- **`Covers:` precision.** An annotation occasionally claims a partition its test doesn't
  exercise.
- **Triggering** has only been smoke-tested with the plugin loaded.

The full results per iteration and run are in [`benchmarks/README.md`](benchmarks/README.md).
How to reproduce them is in [`tools/README.md`](tools/README.md).

## Repository layout

```
.claude-plugin/marketplace.json
plugins/firmware-testing/
├── .claude-plugin/plugin.json
└── skills/embedded-unit-testing/
    ├── SKILL.md
    ├── references/        # spec-based testing heuristics, one file per path (A/B/C)
    ├── scripts/           # test_report.py (tests.html)
    ├── assets/            # Zephyr test project scaffold
    └── evals/             # development, validation and trigger evals
benchmarks/                # targets, equivalent mutants, results, detailed history
examples/                  # Path C project with no test framework (eval fixture)
tools/                     # fetch, workspace, run, measure, grade
```
