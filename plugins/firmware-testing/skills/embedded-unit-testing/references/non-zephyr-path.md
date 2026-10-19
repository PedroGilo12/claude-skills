# Path C — other (neither Zephyr nor ESP-IDF)

You are here because Phase 0 found **no** Zephyr **nor ESP-IDF** signals (ESP-IDF is Path B
→ `espidf-path.md`). The golden rule of this path: **do not impose a framework — discover and
faithfully follow what the project already uses.** The value here is the methodology
(partitions/boundaries/traceability), not swapping the team's tooling.

## Step 1 — Detect the existing UNIT test framework

Look at the project root and in `test/`, `tests/`, `unit_test/`, `spec/` directories:

| Framework | Signals |
|---|---|
| **Unity** (ThrowTheSwitch) | `unity.h`, `TEST_ASSERT_*`, `RUN_TEST`, `test_<x>.c`, `unity_config.h` |
| **Ceedling** | `project.yml`, a `test/` folder with `test_*.c`, ceedling's `build/`, `rakefile` |
| **CMock** | `cmock.h`, generated `mock_<module>.c/.h`, the `mock_` prefix |
| **GoogleTest** | `gtest/gtest.h`, `TEST(`, `TEST_F(`, `EXPECT_*`, `ASSERT_*`, CMake `gtest_main` |
| **Custom/home-grown** | its own `test_runner`, its own assert macros — read and imitate |

**Not unit test frameworks** (do not trigger this path with them): Robot Framework,
integration pytest, HIL over serial/JTAG, on-target tests. Those are integration — out of
this skill's scope.

## Step 2 — If there is NO unit framework: STOP and ask

If no unit test structure is found, **do not pick a default on your own.** Stop and ask the
user which framework to adopt, offering common options (e.g. for generic CMake, Unity or
GoogleTest + CTest). Only proceed after the answer. This is one of the only two mandatory
stopping points of the skill (the other is the Phase 8 coverage iteration).

## Step 3 — Follow the pattern faithfully

Once detected (or chosen by the user), imitate the project in everything:
- **Location and naming** of the files (`test_<module>.c`, `<Module>Test.cpp`, etc.).
- The framework's **assert macros** — use the project's, do not invent. Unity:
  `TEST_ASSERT_EQUAL_INT`, `_UINT`, `_FLOAT_WITHIN`, `_EQUAL_PTR`, `_NULL`, `_EQUAL_MEMORY`.
  GoogleTest: `EXPECT_EQ`, `EXPECT_NEAR`, `EXPECT_STREQ`. Ceedling generates runners
  automatically — do not hand-write `main`/`RUN_TEST` if Ceedling does it.
- **Runner:** respect who owns `main`/`UNITY_BEGIN/END`. If there is a shared runner, do not
  duplicate it; if the framework generates the runner (Ceedling, gtest_main), do not write
  one.
- **Mocks/fakes:** follow the project's mechanism (generated CMock, hand-written fakes,
  gmock). Only introduce FFF if the project **already** uses it; otherwise, use what exists.
- **Build:** follow how the project compiles its tests (`ceedling test:all`, a CMake/CTest
  target, `idf.py` on the host target). Do not reinvent the build.
- **Defect found (code diverges from docs):** use the framework's own skip/ignore
  (`TEST_IGNORE_MESSAGE` in Unity/Ceedling, `GTEST_SKIP() << "BUG: ..."` in GoogleTest) for
  the documented behavior, plus a characterization test, as described in SKILL.md.

## Step 4 — Traceability (same scheme, framework syntax)

The Phase 3/6 catalog scheme applies the same way, adapted:

```c
/*
 * Catalog — parse_gcode  (Phase 3 · spec-based testing)
 * Partitions:
 *   P1  empty line             -> no command
 *   P2  valid G command        -> parse ok
 *   P3  invalid checksum       -> rejected
 * Boundaries:
 *   B1  number at the field limit
 */

/* Covers: P2 */
void test_parse_gcode_valid_g1(void) { /* ... */ }

/* Covers: P3 */
void test_parse_gcode_bad_checksum_is_rejected(void) { /* ... */ }
```

GoogleTest uses the comment above `TEST(Suite, Case)`/`TEST_F`. Keep the **IDs stable and
identical** between header and annotations (`grep "P3"` must find everything).

## Step 5 — Execution + coverage (Phase 7)

Use the project's own runner + coverage and **point to the artifacts it generates**:
- **Ceedling:** `ceedling gcov:all` → report in `build/artifacts/gcov/`
  (HTML/`GcovCoverageCobertura.xml`).
- **Unity + manual CMake/gcov:** compile with `--coverage` (`-fprofile-arcs -ftest-coverage`),
  run the tests, then `gcovr -r . --html-details -o coverage.html` (or `--xml`). Point to
  `coverage.html`/`.xml`.
- **GoogleTest + gcov/llvm-cov:** run via CTest, generate coverage with `gcovr`/`llvm-cov`
  and point to the report.

Compare function/line/branch of the unit under test against the 95/95/90 target to feed Phase 8. Do not write a report of your own — the tool's artifact is
the output.
