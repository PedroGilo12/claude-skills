# Path B — ESP-IDF (native Unity, host build)

You are here because Phase 0 detected ESP-IDF (`idf_component_register(`, `sdkconfig`,
`$ENV{IDF_PATH}`, a `main/` component). ESP-IDF **already ships Unity** as a first-class
component (`$IDF_PATH/components/unity`), so the default is Unity — **without stopping to
ask**. One caveat only: if the project **already consistently uses another unit test
framework** (Ceedling, GoogleTest…), follow that one and treat it as Path C
(`non-zephyr-path.md`). And if you really cannot set up a host build with Unity (no `gcc`,
no Unity source), then stop and ask.

## Strategy: unit tests on the HOST, not on the board

Unit tests run on the PC, fast and deterministic — they do not bring up the board. Compile
the unit under test (`.c`) on the host with `gcc`, linking Unity, and **replace the firmware
dependencies with thin stubs**. This matches the `gcov`/`gcovr` that ESP-IDF projects usually
already use.

Two ways, in order of preference:
1. **Self-contained host build** (Makefile/CMake + `gcc` + Unity) — runs without the ESP-IDF
   toolchain or a board. The most portable option and the recommended default.
2. **ESP-IDF `linux` target** (`idf.py --preview set-target linux`) — if the project already
   has this flow set up, use it.

If the target has no host harness yet, **scaffold it**: a test directory with
`test_<module>.c`, the stubs, Unity (vendored or pointing to `$IDF_PATH/components/unity`)
and a `Makefile`/`CMakeLists.txt` with coverage.

> Scope: this skill does the full generation (methodology + catalog) and, if the harness
> does not exist, creates it. Just filling in a `test_<module>.c` that another tool already
> scaffolded is out of scope.

## Isolation with thin stubs

The `.c` under test pulls HAL/RTOS/log headers that do not exist (nor make sense) on the
host. Replace them with minimal stubs:

- `stubs/esp_log.h` — `ESP_LOGE/W/I/D(...)` become no-ops (`#define ESP_LOGE(...) ((void)0)`).
- Header of a dependency driver — declare **only** what the unit uses (e.g.
  `uart_write(...)`), avoiding dragging in GPIO/RMT/FreeRTOS. The implementation
  becomes a **spy** in the test file (records args for assertions) or a stub returning a
  programmable value.
- `static` functions of the unit are reached through the **real API** (handle/vtable, e.g.
  `motor_ctrl_get_api()->transform(...)`), never by the static name. Do not invent a
  signature. The only exception is assigning a `static` *variable* through the state seam,
  when the slow-test rule (SKILL.md, Phase 7) allows it.

## Unity suite — canonical form + traceability

Reset the module state in `setUp()` (independence between tests). The Phase 3/6 catalog
scheme applies the same way, with the comment above each test:

```c
#include "unity.h"
#include "motor_ctrl.h"   /* real API of the module under test */

void setUp(void)    { /* reinitialize the module's global state to the default */ }
void tearDown(void) { }

/*
 * Catalog — motor_ctrl_transform  (Phase 3 · spec-based testing)
 * Partitions:
 *   P1  p_axis_values == NULL     -> rejected, output not written
 *   P2  valid count, value > 0    -> positive steps
 *   P3  value < 0                 -> sign preserved
 * Boundaries:
 *   B1  rounding at the half step (10.01 -> 400 ; 10.02 -> 401)
 */

/* Covers: P2 */
void test_motor_ctrl_transform_positive_gives_positive_steps(void) { /* ... */ }

/* Covers: P1 */
void test_motor_ctrl_transform_null_input_is_rejected(void) { /* ... */ }

int main(void) {
    UNITY_BEGIN();
    RUN_TEST(test_motor_ctrl_transform_positive_gives_positive_steps);
    RUN_TEST(test_motor_ctrl_transform_null_input_is_rejected);
    return UNITY_END();
}
```

Macros by type: `TEST_ASSERT_EQUAL_INT/_UINT/_HEX`, `TEST_ASSERT_EQUAL_FLOAT`,
`TEST_ASSERT_FLOAT_WITHIN` (tolerance), `TEST_ASSERT_EQUAL_PTR`, `TEST_ASSERT_NULL`,
`TEST_ASSERT_EQUAL_MEMORY`. For "output not written", put a sentinel in the buffer and check
it stayed unchanged after the rejected call.

Keep the **IDs stable and grep-able** (header == annotations), as in SKILL.md.

### Defect found (code diverges from docs) — Unity syntax

Documented behavior ignored with the reason, plus a characterization test pinning the
current behavior. The run ends green and Unity lists the ignored test with its message:

```c
/* Covers: P5 — BUG: header says speed 0 is rejected with ESP_ERR_INVALID_ARG; code returns ESP_OK */
void test_motor_ctrl_set_speed_zero_is_rejected(void)
{
    TEST_IGNORE_MESSAGE("BUG: documented ESP_ERR_INVALID_ARG, current ESP_OK");
    TEST_ASSERT_EQUAL(ESP_ERR_INVALID_ARG, motor_ctrl_set_speed(0));
}

/* Covers: P5 — characterization of the BUG above */
void test_motor_ctrl_set_speed_zero_current_behavior(void)
{
    TEST_ASSERT_EQUAL(ESP_OK, motor_ctrl_set_speed(0));
}
```

## Execution + coverage (Phase 7)

Activate the environment first (the repo venv if any; `. $IDF_PATH/export.sh` for the IDF
flow). For the self-contained host build:

```sh
gcc -std=c11 --coverage -DUNITY_INCLUDE_DOUBLE \
    -I<module inc> -Istubs -Ivendor/unity \
    <module>.c test_<module>.c vendor/unity/unity.c -o test_<module> && ./test_<module>
# raw branch number, then the one compared against the target (log/assert branches out):
gcovr -r . --filter '<module>.c' --txt-metric branch --txt
gcovr -r . --filter '<module>.c' --exclude-branches-by-pattern '(^\s*ESP_LOG[EWIDV]\(.*)|(^\s*assert\(.*)' \
      --txt-metric branch --txt --html-details -o coverage.html    # or --xml for CI
```

Report both numbers. The second one is what counts against the target.

Point to the artifacts the tool generates (`coverage.html`/`.xml`, the Unity runner output)
— do not write a report of your own.

**Known gotchas:**
- Unity's `double` assertions are off by default → compile with `-DUNITY_INCLUDE_DOUBLE`
  (and `-DUNITY_INCLUDE_FLOAT` if you need float).
- A file-scope singleton **without a reset hook**: the "clean boot" states (e.g. before
  init) cannot be retested in the same binary. Isolate them in a second scenario/binary
  instead of relying on test order — and record it as a testability limitation of the module
  (feeds Phase 8, it is not a test gap).
- Unity: prefer `$IDF_PATH/components/unity/{unity.c,unity.h,unity_internals.h}`; vendor it
  only if the IDF is not available in the environment.
