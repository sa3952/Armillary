#!/usr/bin/env python3
"""Lab Core Web Vitals of the live site, measured in headless Chromium.

web_vitals_collect.cjs loads one page (cold cache) and prints the raw
performance entries; this module turns them into LCP, CLS, TBT (the lab proxy
for INP), INP of the measured interaction, FCP, TTFB, transfer size and
request count, takes the median of the runs of each case and compares it with
Google's "good" thresholds.  Runs are strictly sequential: the target is
production.  Usage:

    python -m scripts.verification.web_vitals --out <report.json> [--runs 3]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import median
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = Path(__file__).with_name("web_vitals_collect.cjs")
SITE = "https://projectarmillary.com"
PAGES = (
    ("home", "/zh-TW/", "load"),
    ("calculate", "/zh-TW/calculate", "load"),
    ("calculate-after-example", "/zh-TW/calculate", "compute"),
    ("firdaria", "/zh-TW/calculate/firdaria", "load"),
    ("profections", "/zh-TW/calculate/profections", "load"),
    ("decennials", "/zh-TW/calculate/decennials", "load"),
    ("zodiacal-releasing", "/zh-TW/calculate/zodiacal-releasing", "load"),
    ("blog-hong-kong-birth-time", "/zh-TW/blog/hong-kong-birth-time", "load"),
    ("blog-taiwan-time-zone-history", "/zh-TW/blog/taiwan-time-zone-history", "load"),
)
PROFILES = ("desktop", "mobile")
GOOD = {"lcp_ms": 2500.0, "cls": 0.1, "inp_ms": 200.0, "tbt_ms": 200.0}
LONG_TASK_BUDGET_MS = 50.0


def largest_contentful_paint(entries: dict) -> float | None:
    lcp = entries.get("lcp") or []
    return lcp[-1]["startTime"] if lcp else None


def cumulative_layout_shift(shifts: list[dict]) -> float:
    """Largest session window: gaps under 1 s, windows at most 5 s long."""
    best = current = 0.0
    window_start = previous = None
    for shift in sorted(shifts, key=lambda s: s["startTime"]):
        if shift.get("hadRecentInput"):
            continue
        t = shift["startTime"]
        if window_start is None or t - previous >= 1000 or t - window_start >= 5000:
            window_start, current = t, 0.0
        current += shift["value"]
        previous = t
        best = max(best, current)
    return best


def first_contentful_paint(entries: dict) -> float | None:
    return next((p["startTime"] for p in entries.get("paint") or [] if p["name"] == "first-contentful-paint"), None)


def total_blocking_time(longtasks: list[dict], after: float) -> float:
    return sum(max(0.0, t["duration"] - LONG_TASK_BUDGET_MS) for t in longtasks if t["startTime"] >= after)


def interaction_to_next_paint(events: list[dict]) -> float | None:
    """The slowest interaction; with fewer than 50 interactions that is the INP."""
    by_id: dict[int, float] = {}
    for event in events:
        if event.get("interactionId"):
            by_id[event["interactionId"]] = max(by_id.get(event["interactionId"], 0.0), event["duration"])
    return max(by_id.values()) if by_id else None


def run_metrics(run: dict) -> dict:
    entries = run["entries"]
    navigation = entries.get("navigation") or {}
    resources = entries.get("resources") or []
    fcp = first_contentful_paint(entries)
    return {
        "lcp_ms": largest_contentful_paint(entries),
        "cls": cumulative_layout_shift(entries.get("shifts") or []),
        "fcp_ms": fcp,
        "ttfb_ms": navigation.get("responseStart"),
        "tbt_ms": total_blocking_time(entries.get("longtasks") or [], fcp or 0.0),
        "inp_ms": interaction_to_next_paint(entries.get("events") or []),
        "transfer_bytes": run["wire"]["bytes"],
        "requests": run["wire"]["requests"],
        "render_blocking": [r["name"] for r in resources if r.get("renderBlockingStatus") == "blocking"],
        "lcp_element": (entries.get("lcp") or [{}])[-1].get("element"),
        "shift_sources": sorted({s for shift in entries.get("shifts") or [] for s in shift["sources"] if s}),
    }


def summarize(runs: list[dict]) -> dict:
    metrics = [run_metrics(run) for run in runs]
    summary: dict = {}
    for key in ("lcp_ms", "cls", "fcp_ms", "ttfb_ms", "tbt_ms", "inp_ms", "transfer_bytes", "requests"):
        values = [m[key] for m in metrics if m[key] is not None]
        summary[key] = median(values) if values else None
    for key in ("render_blocking", "lcp_element", "shift_sources"):
        summary[key] = metrics[-1][key]
    summary["fails"] = [key for key, limit in GOOD.items() if summary[key] is not None and summary[key] > limit]
    summary["runs"] = metrics
    return summary


def collect(url: str, profile: str, mode: str) -> dict:
    done = subprocess.run(["node", str(COLLECTOR), url, profile, mode], cwd=ROOT / "frontend",
                          capture_output=True, text=True, timeout=600, check=False)
    if done.returncode:
        raise RuntimeError(f"{url} {profile} {mode}: {done.stderr.strip()}")
    return json.loads(done.stdout)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--site", default=SITE)
    args = parser.parse_args(argv)
    if args.out.resolve().is_relative_to(ROOT):
        parser.error("--out must be outside the repository")
    cases = []
    for name, path, mode in PAGES:
        for profile in PROFILES:
            runs = [collect(args.site + path, profile, mode) for _ in range(args.runs)]
            cases.append({"page": name, "url": args.site + path, "mode": mode, "profile": profile, **summarize(runs)})
            print(name, profile, {k: cases[-1][k] for k in ("lcp_ms", "cls", "tbt_ms", "inp_ms", "fails")}, file=sys.stderr)
    report = {"measured_at": datetime.now(timezone.utc).isoformat(), "site": args.site, "runs_per_case": args.runs,
              "good_thresholds": GOOD, "cases": cases}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
