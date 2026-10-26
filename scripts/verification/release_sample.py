#!/usr/bin/env python3
"""The pre-release fuzz and astronomy sample, with a receipt.

Two runs, on a clean checkout, each a pytest run whose outcome is read back
from its JUnit report:

  * fuzz: tests/backend/test_fuzz_corpus.py with the generated example counts
    raised (the corpus replay and both Hypothesis tests, derandomized, so the
    same revision and counts replay the same examples);
  * astronomy: the tests that compare the product with authorities outside it
    (JPL Horizons, the NASA eclipse canons, USNO, ERFA), slow-marked ones
    included.

It fails, and the receipt says so, when a run exits non-zero, collects no
test, has a failure, error or skip, or ran fewer generated examples than it
asked for; or when HEAD moved during the run.  The receipt (JSON, a new path
outside the repository) records the revision, every command, the counts, the
result and the durations.

    python -m scripts.verification.release_sample --receipt <new path outside the repository> \
        [--http-examples N] [--parser-examples N]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from scripts.tools.child_environment import allowed_environment
from scripts.tools.git import require_clean_head
from scripts.tools.output_confinement import external_output_path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECEIPT_SCHEMA = "armillary-release-sample-receipt-v1"

FUZZ_TESTS = ("tests/backend/test_fuzz_corpus.py",)
# Only files whose expected values come from an authority outside the product.
ASTRONOMY_TESTS = (
    "tests/backend/test_external_astronomy_baselines.py",
    "tests/backend/test_sidereal_time_continuation.py",
    "tests/backend/test_solar_return_oracle.py",
    "tests/backend/test_eclipses_and_lunar_phases.py",
    "tests/backend/test_reference_frames.py",
)
# test_fuzz_corpus.py reads its example counts and tally path from these.
HTTP_EXAMPLES_ENV = "ARMILLARY_FUZZ_HTTP_EXAMPLES"
PARSER_EXAMPLES_ENV = "ARMILLARY_FUZZ_PARSER_EXAMPLES"
TALLY_ENV = "ARMILLARY_FUZZ_TALLY"
DEFAULT_HTTP_EXAMPLES = 10_000
DEFAULT_PARSER_EXAMPLES = 300_000


def junit_totals(report: Path) -> dict[str, int]:
    """Tests, failures, errors and skips summed over every suite in a JUnit report."""

    root = ElementTree.parse(report).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if not suites:
        raise ValueError(f"no test suite in {report}")
    return {key: sum(int(suite.get(key, "0")) for suite in suites)
            for key in ("tests", "failures", "errors", "skipped")}


def step_problems(step: dict) -> list[str]:
    """Why a recorded step does not count as passed; empty when it does."""

    problems = []
    if step["returncode"] != 0:
        problems.append(f"exit status {step['returncode']}")
    totals = step.get("totals")
    if totals is None:
        problems.append("no JUnit report")
    else:
        if totals["tests"] == 0:
            problems.append("no test ran")
        for key in ("failures", "errors", "skipped"):
            if totals[key]:
                problems.append(f"{totals[key]} {key}")
    for name, requested in step.get("requested_examples", {}).items():
        ran = step.get("examples_run", {}).get(name, 0)
        if ran < requested:
            problems.append(f"{name}: {ran} generated examples ran, {requested} requested")
    return problems


def run_step(name: str, tests: tuple[str, ...], workspace: Path, *, marker: str,
             requested_examples: dict[str, int] | None = None) -> dict:
    report = workspace / f"{name}.junit.xml"
    tally = workspace / f"{name}.tally.json"
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-m", marker,
               f"--junitxml={report}", *tests]
    extra = {"ARMILLARY_REQUIRE_ALL": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    requested_examples = requested_examples or {}
    if requested_examples:
        extra.update({HTTP_EXAMPLES_ENV: str(requested_examples["http"]),
                      PARSER_EXAMPLES_ENV: str(requested_examples["parser"]),
                      TALLY_ENV: str(tally)})
    started = time.monotonic()
    completed = subprocess.run(command, cwd=PROJECT_ROOT, env=allowed_environment(**extra), check=False)
    step = {
        "name": name,
        "command": command[1:],
        "environment": {key: value for key, value in extra.items() if key != TALLY_ENV},
        "returncode": completed.returncode,
        "duration_seconds": round(time.monotonic() - started, 1),
        "totals": junit_totals(report) if report.is_file() else None,
    }
    if requested_examples:
        step["requested_examples"] = requested_examples
        step["examples_run"] = json.loads(tally.read_text(encoding="utf-8")) if tally.is_file() else {}
    step["problems"] = step_problems(step)
    return step


def receipt_payload(revision: str, steps: list[dict], *, started: str, moved: bool) -> dict:
    problems = [f"{step['name']}: {problem}" for step in steps for problem in step["problems"]]
    if moved:
        problems.append("HEAD or the working tree changed during the run")
    return {
        "schema_version": RECEIPT_SCHEMA,
        "revision": revision,
        "started_utc": started,
        "python": sys.version.split()[0],
        "steps": steps,
        "result": "fail" if problems or not steps else "pass",
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--receipt", type=Path, required=True,
                        help="a new path outside the repository for the JSON receipt")
    parser.add_argument("--http-examples", type=int, default=DEFAULT_HTTP_EXAMPLES)
    parser.add_argument("--parser-examples", type=int, default=DEFAULT_PARSER_EXAMPLES)
    args = parser.parse_args(argv)
    if args.http_examples < 1 or args.parser_examples < 1:
        parser.error("example counts must be positive")
    try:
        receipt = external_output_path(args.receipt, source_root=PROJECT_ROOT, role="release sample receipt")
        if receipt.exists() or receipt.is_symlink():
            raise ValueError(f"release sample receipt already exists: {receipt}")
        revision = require_clean_head(PROJECT_ROOT, untracked_all=True,
                                      dirty="the release sample needs a clean checkout; its receipt names one revision")
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory(prefix="armillary-release-sample-") as directory:
        workspace = Path(directory)
        steps = [
            run_step("fuzz", FUZZ_TESTS, workspace, marker="not slow",
                     requested_examples={"http": args.http_examples, "parser": args.parser_examples}),
            run_step("astronomy", ASTRONOMY_TESTS, workspace, marker=""),
        ]
    try:
        require_clean_head(PROJECT_ROOT, revision, untracked_all=True)
        moved = False
    except RuntimeError:
        moved = True
    payload = receipt_payload(revision, steps, started=started, moved=moved)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if payload["result"] != "pass":
        print("RELEASE SAMPLE FAILED: " + "; ".join(payload["problems"]), file=sys.stderr)
        print(f"[release-sample] failing receipt: {receipt}", file=sys.stderr)
        return 1
    print(f"[release-sample] pass for {revision}: " + ", ".join(
        f"{step['name']} {step['totals']['tests']} tests in {step['duration_seconds']} s" for step in steps))
    print(f"[release-sample] receipt: {receipt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
