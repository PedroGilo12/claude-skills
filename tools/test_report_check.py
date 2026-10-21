#!/usr/bin/env python3
"""Self-check do test_report.py da skill: uma fixture por formato (Unity, ztest, JUnit).

uso: python3 tools/test_report_check.py
"""
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent / "plugins/firmware-testing/skills/"
          "embedded-unit-testing/scripts/test_report.py")

UNITY = """\
test_a.c:10:test_ok:PASS
test_a.c:20:test_bad:FAIL: Expected 1 Was 2
test_a.c:30:test_doc:IGNORE: BUG: returns 0, docs say -1
test_a.c:40:test_later:IGNORE: not on host
-----------------------
4 Tests 1 Failures 2 Ignored
"""
UNITY_CRASH = "test_b.c:10:test_ok:PASS\nSegmentation fault\n"

ZTEST = """\
\x1b[0mRunning TESTSUITE mod_suite
START - test_ok
 PASS - test_ok in 0.001 seconds
START - test_bad
    Assertion failed at WEST_TOPDIR/tests/mod/src/test_mod.c:42: mod_suite_test_bad: (1 not equal to 2)
 FAIL - test_bad in 0.001 seconds
START - test_doc
BUG: documented -EINVAL, current 0
 SKIP - test_doc in 0.000 seconds
------ TESTSUITE SUMMARY START ------
 - PASS - [mod_suite.test_ok] duration = 0.001 seconds
------ TESTSUITE SUMMARY END ------
"""

JUNIT = """\
<testsuites><testsuite name="Mod">
<testcase name="Ok" classname="Mod" file="test_mod.cc" line="5"/>
<testcase name="Bad" classname="Mod"><failure message="expected 1"/></testcase>
<testcase name="Doc" classname="Mod"><skipped message="BUG: returns 0"/></testcase>
<testcase name="Later" classname="Mod"><skipped/></testcase>
</testsuite></testsuites>
"""


def report(d, *files):
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), str(d / "tests.html"), *map(str, files)],
                         capture_output=True, text=True, check=True).stdout
    return out.split("(", 1)[1]


with tempfile.TemporaryDirectory() as t:
    d = Path(t)
    (d / "test_a.log").write_text(UNITY)
    (d / "test_b.log").write_text(UNITY_CRASH)
    (d / "unit.mod").mkdir()
    (d / "unit.mod/handler.log").write_text(ZTEST)
    (d / "ztest_crash").mkdir()
    (d / "ztest_crash/handler.log").write_text("START - test_ok\n PASS - test_ok in 0.001 seconds\n")
    (d / "gtest.xml").write_text(JUNIT)

    r = report(d, d / "test_a.log", d / "test_b.log")
    assert "1 failed · 1 crashed · 1 known bug · 1 ignored · 2 passed" in r, r
    r = report(d, d / "unit.mod/handler.log", d / "ztest_crash/handler.log")
    assert "1 failed · 1 crashed · 1 known bug · 0 ignored · 2 passed" in r, r
    html = (d / "tests.html").read_text()
    assert "test_mod.c:42" in html and "unit.mod" in html, "ztest: where/suite"
    r = report(d, d / "gtest.xml", d / "missing.xml")
    assert "1 failed · 1 crashed · 1 known bug · 1 ignored · 1 passed" in r, r

print("test_report_check: ok")
