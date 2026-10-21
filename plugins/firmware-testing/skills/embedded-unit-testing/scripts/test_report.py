#!/usr/bin/env python3
"""Turn test runner output into one HTML page laid out like gcovr's "GCC Code Coverage Report".

usage: test_report.py OUT.html INPUT [INPUT ...]
INPUT is one of:
  - a Unity runner log (one per test binary);
  - a ztest handler.log from twister (suite = its parent directory);
  - a JUnit XML file (*.xml: gtest --gtest_output=xml, ctest --output-junit, Ceedling junit).
A test skipped/ignored with a message starting "BUG:" is listed as a known bug (ztest: a
"BUG: ..." line printed before ztest_test_skip()). Output without the runner's final summary,
or a missing input, means the binary crashed. Always exits 0: the runner's exit code is the
verdict.
"""
import html
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

SKILL = "firmware-testing:embedded-unit-testing"
SKILL_URL = ("https://github.com/PedroGilo12/claude-skills/tree/main/"
             "plugins/firmware-testing/skills/embedded-unit-testing")

LINE = re.compile(r"^(?P<file>[^:\s]+):(?P<line>\d+):(?P<name>\w+):(?P<status>PASS|FAIL|IGNORE)"
                  r"(?::\s*(?P<msg>.*?))?(?:\s*\(\d+ ms\))?\s*$")
SUMMARY = re.compile(r"^\d+ Tests \d+ Failures \d+ Ignored")
ORDER = ["FAIL", "CRASH", "BUG", "IGNORE", "PASS"]
LABEL = {"FAIL": "Failed", "CRASH": "Crashed", "BUG": "Known bug", "IGNORE": "Ignored", "PASS": "Passed"}
# gcovr's colour classes: red for what breaks the run, yellow for what is parked, green for passed.
CLASS = {"FAIL": "coverage-low", "CRASH": "coverage-low", "BUG": "coverage-medium",
         "IGNORE": "coverage-medium", "PASS": "coverage-high"}

esc = html.escape


ANSI = re.compile(r"\x1b\[[0-9;]*m")
Z_START = re.compile(r"^\s*START - (\w+)")
Z_END = re.compile(r"^\s*(PASS|FAIL|SKIP) - (\w+) in ")
Z_ASSERT = re.compile(r"(?:Assertion failed at )?(\S+\.c):(\d+)")
Z_DONE = re.compile(r"TESTSUITE SUMMARY END|PROJECT EXECUTION (SUCCESSFUL|FAILED)")


def parse(log):
    if not log.exists():
        return [("CRASH", "(binary)", log.name, "no output file")]
    if log.suffix == ".xml":
        return parse_junit(log)
    text = ANSI.sub("", log.read_text(errors="replace"))
    if log.name == "handler.log" or re.search(r"^\s*START - test_", text, re.M):
        return parse_ztest(log, text)
    return parse_unity(log, text)


def parse_ztest(log, text):
    rows, finished, body, last = [], False, [], ""
    for line in text.splitlines():
        if Z_START.match(line):
            body = []
        elif m := Z_END.match(line):
            status, name = {"SKIP": "IGNORE"}.get(m[1], m[1]), m[2]
            bug = next((b.strip() for b in body if b.strip().startswith("BUG:")), None)
            if status == "IGNORE" and bug:
                status = "BUG"
            where = next((f"{Path(a[1]).name}:{a[2]}" for b in body if (a := Z_ASSERT.search(b))), log.name)
            msg = bug or (" ".join(b.strip() for b in body if b.strip()) if status == "FAIL" else "")
            rows.append((status, name, where, msg))
            body = []
        elif Z_DONE.search(line):
            finished = True
        else:
            body.append(line)
            if line.strip():
                last = line.strip()
    if not finished:
        rows.append(("CRASH", "(binary)", log.name, f"no ztest summary; last output: {last}"))
    return rows


def parse_junit(log):
    try:
        cases = ET.parse(log).getroot().iter("testcase")
    except ET.ParseError as e:
        return [("CRASH", "(binary)", log.name, f"unreadable JUnit XML: {e}")]
    rows = []
    for tc in cases:
        where = f"{Path(tc.get('file')).name}:{tc.get('line')}" if tc.get("file") else tc.get("classname", "")
        bad = tc.find("failure")
        if bad is None:
            bad = tc.find("error")
        skip = tc.find("skipped")
        if bad is not None:
            status, msg = "FAIL", bad.get("message") or (bad.text or "").strip()
        elif skip is not None:
            msg = skip.get("message") or (skip.text or "").strip()
            status = "BUG" if msg.startswith("BUG:") else "IGNORE"
        else:
            status, msg = "PASS", ""
        rows.append((status, tc.get("name", "?"), where, msg))
    return rows


def parse_unity(log, content):
    rows, finished, last = [], False, ""
    for text in content.splitlines():
        m = LINE.match(text)
        if m:
            status, msg = m["status"], m["msg"] or ""
            if status == "IGNORE" and msg.startswith("BUG:"):
                status = "BUG"
            rows.append((status, m["name"], f"{Path(m['file']).name}:{m['line']}", msg))
        elif SUMMARY.match(text):
            finished = True
        elif text.strip():
            last = text.strip()
    if not finished:
        rows.append(("CRASH", "(binary)", log.name, f"no Unity summary; last output: {last}"))
    return rows


def tally(rows):
    c = {k: sum(1 for r in rows if r[0] == k) for k in ORDER}
    run = c["PASS"] + c["FAIL"] + c["CRASH"]
    rate = 100.0 * c["PASS"] / run if run else 100.0
    cls = "coverage-low" if c["FAIL"] or c["CRASH"] else "coverage-high"
    return c, rate, cls


def test_table(rows, suite_col):
    head = "<th scope='col'>Suite</th>" if suite_col else ""
    body = "".join(
        f"<tr>{f'<td>{esc(s)}</td>' if suite_col else ''}"
        f"<th scope='row'>{esc(name)}</th>"
        f"<td class='CoverValue {CLASS[st]}'>{LABEL[st]}</td>"
        f"<td>{esc(loc)}</td><td class='message'>{esc(msg)}</td></tr>"
        for s, st, name, loc, msg in sorted(rows, key=lambda r: (ORDER.index(r[1]), r[0]))
    )
    return (f"<table class='file-list'><tr>{head}<th scope='col'>Test</th><th scope='col'>Status</th>"
            f"<th scope='col'>Where</th><th scope='col'>Message</th></tr>{body}</table>")


def main(out, logs):
    suites = {(Path(p).parent.name if Path(p).name == "handler.log" else Path(p).stem): parse(Path(p))
              for p in logs}
    every = [(s, *r) for s, rows in suites.items() for r in rows]
    total, rate, cls = tally([r[1:] for r in every])
    ok_suites = sum(1 for rows in suites.values() if tally(rows)[2] == "coverage-high")

    suite_rows = ""
    for s, rows in suites.items():
        c, r, k = tally(rows)
        cells = "".join(
            f"<td class='CoverValue {CLASS[x] if c[x] else ''}'>{c[x]}</td>" for x in ORDER if x != "PASS")
        suite_rows += (
            f"<tr><th scope='row'><a href='#{esc(s)}'>{esc(s)}</a></th>"
            f"<td><meter class='{k}' min='0' max='100' value='{r:.1f}' title='{r:.1f}%'>{r:.1f}</meter></td>"
            f"<td class='CoverValue {k}'>{r:.1f}%</td>"
            f"<td class='CoverValue {k}'>{c['PASS']} / {len(rows)}</td>{cells}</tr>")

    attention = [r for r in every if r[1] != "PASS"]
    details = "".join(
        f"<h2 id='{esc(s)}'>{esc(s)}</h2>{test_table([(s, *r) for r in rows], False)}"
        for s, rows in suites.items())

    Path(out).write_text(f"""<!DOCTYPE html>
<html class="theme-green">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Unit Test Report</title>
<style>
.theme-green {{ --low_color:#FF6666; --medium_color:#F9FD63; --high_color:#85E485; }}
body {{ color:#000; background-color:#FFF; font-family:sans-serif; }}
h1 {{ text-align:center; margin:0; padding-bottom:10px; font-size:20pt; font-weight:bold; }}
h2 {{ font-size:13pt; margin:24px 0 6px; }}
hr {{ background-color:navy; height:2px; border:0; }}
a:link {{ color:navy; text-decoration:underline; }}
a:visited {{ color:maroon; text-decoration:underline; }}
.summary {{ display:flex; flex-flow:row wrap; max-width:100%; justify-content:flex-start; }}
.summary > :last-child {{ margin-left:auto; }}
table.legend {{ color:black; }}
table.legend th[scope=row] {{ font-weight:normal; text-align:right; white-space:nowrap; }}
table.legend td {{ color:blue; text-align:left; white-space:nowrap; padding-left:5px; }}
table.legend td.legend {{ color:black; font-size:80%; }}
table.legend span {{ margin-right:4px; padding:2px 3px; }}
table.coverage td, table.coverage th {{ text-align:right; color:black; font-weight:normal;
  white-space:nowrap; padding-left:5px; padding-right:4px; }}
table.coverage td {{ background-color:LightSteelBlue; }}
table.coverage th[scope=col] {{ color:blue; }}
.coverage-low {{ background-color:var(--low_color) !important; }}
.coverage-medium {{ background-color:var(--medium_color) !important; }}
.coverage-high {{ background-color:var(--high_color) !important; }}
meter {{ -moz-appearance:none; width:30vw; min-width:4em; max-width:15em; height:0.75em; padding:0;
  vertical-align:baseline; margin-top:3px; background:none; background-color:whitesmoke; }}
meter::-webkit-meter-bar {{ background:none; background-color:whitesmoke; height:0.75em; border-radius:0; }}
meter::-webkit-meter-optimum-value {{ border:solid 1px black; }}
meter.coverage-low::-webkit-meter-optimum-value {{ background:var(--low_color); }}
meter.coverage-high::-webkit-meter-optimum-value {{ background:var(--high_color); }}
meter:-moz-meter-optimum::-moz-meter-bar {{ border:solid 1px black; }}
meter.coverage-low:-moz-meter-optimum::-moz-meter-bar {{ background:var(--low_color); }}
meter.coverage-high:-moz-meter-optimum::-moz-meter-bar {{ background:var(--high_color); }}
.wrap {{ overflow-x:auto; }}
.file-list {{ border-collapse:separate; border-spacing:2px; }}
.file-list td, .file-list th {{ padding:0 10px; font-weight:bold; }}
.file-list th[scope^=col] {{ text-align:center; color:white; background-color:SteelBlue; font-size:120%; }}
.file-list th[scope=row] {{ text-align:left; color:black; font-family:monospace; font-weight:bold; font-size:110%; }}
.file-list td.CoverValue {{ text-align:right; white-space:nowrap; }}
.file-list td.message {{ font-weight:normal; }}
footer {{ font-size:80%; }}
</style>
</head>
<body>
<header>
<h1>Unit Test Report</h1>
<hr/>
<div class="summary">
<div>
<table class="legend">
<tr><th scope="row">Generated with skill:</th>
<td><a href="{SKILL_URL}">{SKILL}</a></td></tr>
<tr><th scope="row">Date:</th><td>{datetime.now():%Y-%m-%d %H:%M:%S}</td></tr>
<tr><th scope="row">Status:</th><td class="legend">
<span class="coverage-low">failed / crashed</span>
<span class="coverage-medium">known bug / ignored</span>
<span class="coverage-high">passed</span></td></tr>
</table>
</div>
<div>
<table class="coverage">
<tr><th></th><th scope="col">Pass rate</th><th scope="col">Passed</th><th scope="col">Failed</th>
<th scope="col">Known bugs</th><th scope="col">Ignored</th><th scope="col">Total</th></tr>
<tr><th scope="row">Tests:</th><td class="{cls}">{rate:.1f}%</td><td class="{cls}">{total['PASS']}</td>
<td class="{cls}">{total['FAIL'] + total['CRASH']}</td><td class="{cls}">{total['BUG']}</td>
<td class="{cls}">{total['IGNORE']}</td><td class="{cls}">{len(every)}</td></tr>
<tr><th scope="row">Suites:</th><td class="{cls}">{100.0 * ok_suites / len(suites):.1f}%</td>
<td class="{cls}">{ok_suites}</td><td class="{cls}">{len(suites) - ok_suites}</td>
<td class="{cls}"></td><td class="{cls}"></td><td class="{cls}">{len(suites)}</td></tr>
</table>
</div>
</div>
<hr/>
</header>
<main>
<div class="wrap">
<table class="file-list">
<tr><th scope="col">Suite</th><th scope="colgroup" colspan="3">Tests</th>
<th scope="col">Failed</th><th scope="col">Crashed</th><th scope="col">Known bugs</th><th scope="col">Ignored</th></tr>
{suite_rows}
</table>
</div>
<h2>Needs attention</h2>
<div class="wrap">{test_table(attention, True) if attention else "<p>Nothing: every test passed.</p>"}</div>
{details}
<hr/>
</main>
<footer>
Generated by: test_report.py &middot; skill <a href="{SKILL_URL}">{SKILL}</a>
</footer>
</body>
</html>
""")
    print(f"report: {out}  ({' · '.join(f'{total[k]} {LABEL[k].lower()}' for k in ORDER)})")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
