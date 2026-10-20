# Path A — Zephyr (twister + ztest + FFF + coverage)

You are here because Phase 0 found Zephyr signals (`west.yml`, `find_package(Zephyr ...)`,
`prj.conf`, `testcase.yaml`, `tests/`, `ztest`). This file covers dependency isolation,
writing the ztest suite, scaffolding a new test project and running with coverage.

## Dependency isolation — FFF by default

Use **FFF (Fake Functions Framework)** as the default to isolate HAL, drivers, other
modules and kernel services. FFF generates fakes of C functions with call history and
programmable return values.

- **Kernel primitives may run for real** on `native_sim` when they are deterministic there
  and no test needs to control them (`k_spinlock`, `k_lifo`/`k_fifo`, `k_heap`, `sys_*`
  lists). A suite with zero fakes is fine for such a module, but **say so** in the final
  output ("no fakes: only kernel primitives, run for real").
- **Fake them anyway** when a partition needs their failure or timing: allocation failure
  (`k_heap_alloc`/`k_malloc` returning NULL), `K_NO_WAIT` timeouts, `k_uptime_get`. Use FFF
  with `-Wl,--wrap=<sym>` or a fake defined in the suite, not a hand-rolled global flag.

- **Exception:** if the project already consistently uses another mocking mechanism (its
  own wrapper, CMock etc.), follow the project's.
- **Do not use the native/legacy ztest mock** (`ztest_returns_value`, `ztest_expect_*`): it
  is among Zephyr's deprecated APIs.

FFF pattern in a suite:

```c
#include <zephyr/ztest.h>
#include <zephyr/fff.h>

DEFINE_FFF_GLOBALS;

/* Declare one fake per dependency function to isolate. */
FAKE_VALUE_FUNC(int, spi_transceive, const struct device *,
                const struct spi_config *, const struct spi_buf_set *,
                const struct spi_buf_set *);
FAKE_VOID_FUNC(k_msleep, int32_t);

/* Reset every fake before each test (in the fixture setup). */
#define FFF_FAKES_LIST(FAKE) FAKE(spi_transceive) FAKE(k_msleep)
```

Program returns and inspect history:

```c
spi_transceive_fake.return_val = 0;                 /* next return */
int seq[] = {0, -EIO};                               /* or a sequence */
SET_RETURN_SEQ(spi_transceive, seq, ARRAY_SIZE(seq));

zassert_equal(spi_transceive_fake.call_count, 1);    /* called once */
zassert_equal_ptr(spi_transceive_fake.arg0_val, dev);/* with this arg */
```

## ztest suite — modern structure

Use `ZTEST_SUITE`/`ZTEST` (the new runner-based API). An optional fixture carries shared
state; **`RESET_FAKE()` of each fake in the setup** keeps tests independent.

```c
struct motor_ctrl_fixture {
    /* shared state, if any */
};

static void *mc_setup(void)
{
    static struct motor_ctrl_fixture f;
    return &f;
}

static void mc_before(void *arg)
{
    ARG_UNUSED(arg);
    /* independence: reset every fake before each test */
    RESET_FAKE(spi_transceive);
    RESET_FAKE(k_msleep);
    FFF_RESET_HISTORY();
}

ZTEST_SUITE(motor_ctrl_suite, NULL, mc_setup, mc_before, NULL, NULL);

/* Covers: P2 + P3 */
ZTEST_F(motor_ctrl_suite, test_transform_positive_gives_positive_steps)
{
    /* arrange / act / assert */
}
```

**Mandatory prefix:** in recent Zephyr the runner only collects cases whose name starts with
`test_` (`ZTEST(suite, test_...)` / `ZTEST_F(suite, test_...)`). Without that prefix twister
silently runs 0 tests.

Most used assertion macros: `zassert_true/false`, `zassert_equal`, `zassert_equal_ptr`,
`zassert_not_null`, `zassert_within` (float with tolerance), `zassert_mem_equal`. For
"output not written", initialize the buffer with a sentinel and check it is unchanged after
the rejected call.

### Defect found (code diverges from docs) — ztest syntax

Documented behavior skipped with the reason, plus a characterization test pinning the
current behavior. The suite stays green and the skip shows up in every twister run:

```c
/* Covers: P5 — BUG: header says speed 0 is rejected with -EINVAL; code returns 0 */
ZTEST(motor_ctrl_suite, test_set_speed_zero_is_rejected)
{
    ztest_test_skip(); /* BUG: documented -EINVAL, current 0 (see characterization) */
    zassert_equal(motor_ctrl_set_speed(0), -EINVAL);
}

/* Covers: P5 — characterization of the BUG above */
ZTEST(motor_ctrl_suite, test_set_speed_zero_current_behavior)
{
    zassert_equal(motor_ctrl_set_speed(0), 0);
}
```

Do not use `ZTEST_EXPECT_FAIL`, and do not leave a failing assert.

## Reaching `static` functions

If the logic under test is `static` (not exposed in the `.h`), the idiomatic pattern is for
the suite to `#include "<module>.c"` directly (compiles the unit inside the test), or the
module exposes the functions via handle/vtable. Prefer what the module already offers; do
not change production code just to test it. Assigning a `static` *variable* this way (state
seam) is a separate case. It is a last resort, only under the slow-test rule (SKILL.md,
Phase 7).

## Scaffolding a new test project

If the target does **not** yet have a test project, generate the minimal structure below
(use the templates in `assets/zephyr-scaffold/`). Usual convention: `tests/<module-path>/`.

```
tests/<module>/
├── CMakeLists.txt        # links the suite + the .c under test + the fakes
├── prj.conf              # CONFIG_ZTEST=y, CONFIG_ASSERT=y (coverage: let twister inject it)
├── testcase.yaml         # platform_allow: native_sim, native_sim/native/64; tags
└── src/
    └── test_<module>.c   # the suite
```

Points to watch when filling in the templates:
- **native_sim** is the target board (runs on the host, fast, and is where coverage makes
  sense). Plain `native_sim` is 32-bit and needs `gcc-multilib`; `native_sim/native/64` is
  the same board in 64 bits. Allow both in `testcase.yaml` and pick at run time (step 3
  below). Do not hard-code 32-bit sizes (`sizeof(void *) == 4`) in assertions.
- In `CMakeLists.txt`, add **the `.c` under test** to `target_sources` (so gcov measures the
  real unit) together with the suite; make sure the module's includes are there
  (`target_include_directories`).
- The fakes are defined in the suite itself via FFF (no separate fake `.c` is needed, unless
  fakes are shared between suites).
- If the `.c` under test pulls HAL/kernel headers that do not exist on `native_sim`, isolate
  them by faking the functions and, if needed, providing minimal type stubs — flag it to the
  user if this grows too big for an honest unit test.

## Execution + coverage (Phase 7)

**Activate the environment first — do not give up if `west` is not on the `PATH`.** Almost
every Zephyr project keeps `west` and its dependencies in a repo virtualenv, not on the
global `PATH`. Find and use it before concluding it cannot run:

```sh
# 1) repo venv (the most common case):
[ -f .venv/bin/activate ] && source .venv/bin/activate    # or venv/ , env/
#    (or call the binary directly: .venv/bin/west , .venv/bin/python)

# 2) ZEPHYR_BASE + host toolchain:
export ZEPHYR_BASE="$(west topdir 2>/dev/null)/zephyr"    # or the repo's deps/zephyr
[ -d "$ZEPHYR_BASE" ] || export ZEPHYR_BASE="$(pwd)/deps/zephyr"
export ZEPHYR_TOOLCHAIN_VARIANT=host

# 3) pick the platform: 32-bit native_sim only if the host can link -m32 (gcc-multilib),
#    otherwise the 64-bit variant. Do not ask the user to install anything for this.
echo 'int main(void){return 0;}' | gcc -m32 -x c - -o /dev/null 2>/dev/null \
  && PLAT=native_sim || PLAT=native_sim/native/64

# 4) run twister (--coverage-basedir points at the root of the unit under test, which lives
#    OUTSIDE ZEPHYR_BASE; without it gcov does not match the files and coverage is empty):
west twister --coverage -p $PLAT -T <suite_path> \
     --coverage-basedir <root_of_module_under_test>
# fallback if `west` still does not resolve, but the Zephyr tree exists:
python3 "$ZEPHYR_BASE/scripts/twister" --coverage -p $PLAT -T <suite_path> \
     --coverage-basedir <root_of_module_under_test>

# 5) raw branch number (twister only reports it WITHOUT LOG_*/__ASSERT* branches). Same
#    .gcda files, no exclusion. The output dir goes BEFORE the options (`--txt` would take it
#    as its file name):
gcovr -r <root_of_module_under_test> twister-out --filter '<path/to/module.c>' \
      --txt-metric branch --txt > coverage-raw.txt 2>&1; tail -n 5 coverage-raw.txt
```

Only report "execution could not run here" after exhausting this search (venv + ZEPHYR_BASE +
script fallback). If it ran, point to the artifacts below; if not, say exactly what was
missing (e.g. no venv, `ZEPHYR_BASE` does not exist) — without fabricating coverage.

Artifacts generated by the tool (point to these paths; do not write a report). `twister-out`
is the default output directory; if you passed `-O <dir>`, they are under `<dir>`:
- `twister-out/coverage/index.html` — browsable HTML coverage report
- `twister-out/coverage.json` — coverage in JSON
- `twister-out/twister.xml` and `twister-out/twister.json` — test results

Reading the numbers for Phase 8: open `coverage.json` (or `index.html`) and compare
function/line/branch of the **unit under test** against the 95/95/90 target. Uncovered lines/branches point to the gaps to attack, together with the
catalog items without a test.

Reading branch coverage: log macros (`LOG_ERR`/`LOG_WRN`…) inject runtime filtering branches
that **are not decision points of the module**. If branch coverage stays below the target only
because of them (every real logic branch covered), that is infrastructure noise — document
it in Phase 8 instead of "hunting" the number (turning logging off usually makes the metric
worse, creating dead `if(0)`s).

Common troubleshooting (real gotchas already observed):
- **Test name without `test_`** → twister collects 0 cases. Prefix every `ZTEST`/`ZTEST_F`.
- **`CONFIG_ZTEST_NEW_API=y`** was removed in recent Zephyr → the Kconfig warning aborts
  twister. Do not use it (the ZTEST_SUITE/ZTEST API is already the default).
- **`CONFIG_COVERAGE_GCOV=y` in prj.conf** conflicts with native_sim's
  `COVERAGE_NATIVE_GCOV` → let twister's `--coverage` inject the config.
- **`cannot find crti.o` / `Scrt1.o`** at link time → no `gcc-multilib`; use
  `-p native_sim/native/64` (step 3 above).
- **A custom devicetree binding** requires a **known vendor prefix** (`vnd,` or `zephyr,`),
  not an invented one (`test,`) → the build fails DT validation.
- **`ZEPHYR_TOOLCHAIN_VARIANT` not set** breaks twister's coverage tool → export `=host`
  (step 2 above).
- Suite not found → check that `platform_allow` in `testcase.yaml` lists the `-p` platform and that `-T`
  points at the folder containing `testcase.yaml`.
- Duplicate symbol at link time → the `.c` under test and a fake define the same function;
  keep fakes only for external dependencies, never for the unit under test.
