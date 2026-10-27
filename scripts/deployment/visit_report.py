#!/usr/bin/env python3
"""Daily page views and visitors from the application's VISIT_COUNTS lines.

Each worker writes one line per clock hour that had any count
(backend/app/visit_counts.py): the UTC hour, page views and daily visitors.
A day's figures are the sum of its hours over every worker; the day is
Taiwan's, the same day a browser's daily answer is cached until.  The input is
the journal on standard input, read-only, as `journalctl -o json` (each entry
counted once by its cursor) or as plain message lines:

    journalctl -o json --since -8d CONTAINER_NAME=armillary-armillary-app-1 \\
        | python3 -m scripts.deployment.visit_report

or from the Mac, `ssh USER@HOST "sudo journalctl -o json ..." | python -m
scripts.deployment.visit_report`.  `--chart-load` instead prints, per UTC
hour, the chart requests, how many the service refused with 503 and how many
took a second or more, from the request events (journal JSON only: the event
carries no time of its own).  A line it cannot read stops it: a smaller
number would look like a quieter day.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timezone
import json
import re
import sys
from typing import TextIO
from zoneinfo import ZoneInfo

COUNT_ZONE = ZoneInfo("Asia/Taipei")
VISIT_MARKER = "VISIT_COUNTS "
EVENT_MARKER = "PRIVACY_EVENT "
HOUR = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}")
CHART_ROUTES = frozenset({"/api/chart", "/api/chart/annual"})
SLOW_BUCKETS = frozenset({"1_to_9s", "gte_10s"})


class ReportError(ValueError):
    pass


def _entries(stream: TextIO) -> Iterable[tuple[str, int | None]]:
    """(message, receive time in microseconds or None), each journal cursor once."""
    seen: set[str] = set()
    for raw in stream:
        line = raw.rstrip("\n")
        if not line.strip(): continue
        entry = None
        if line.lstrip().startswith("{"):
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
        if not isinstance(entry, dict) or "MESSAGE" not in entry:
            yield line, None
            continue
        cursor = entry.get("__CURSOR")
        if cursor is not None:
            if cursor in seen: continue
            seen.add(cursor)
        message = entry["MESSAGE"]
        if isinstance(message, list):   # journald writes a non-UTF-8 message as a byte array
            message = bytes(message).decode("utf-8", "replace")
        stamp = entry.get("__REALTIME_TIMESTAMP")
        yield str(message), int(stamp) if isinstance(stamp, str) and stamp.isdigit() else None


def _payload(message: str, marker: str) -> dict | None:
    index = message.find(marker)
    if index < 0: return None
    try:
        payload = json.loads(message[index + len(marker):])
    except ValueError:
        raise ReportError(f"unreadable {marker.strip()} line: {message[:120]!r}") from None
    if not isinstance(payload, dict): raise ReportError(f"unreadable {marker.strip()} line: {message[:120]!r}")
    return payload


def daily_visits(stream: TextIO) -> dict[str, tuple[int, int]]:
    """{Taiwan date: (page views, daily visitors)}."""
    days: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    lines = 0
    for message, _stamp in _entries(stream):
        line = _payload(message, VISIT_MARKER)
        if line is None: continue
        hour, views, visitors = line.get("hour_utc"), line.get("page_views"), line.get("daily_visitors")
        if (line.get("event") != "visit_counts" or not isinstance(hour, str) or not HOUR.fullmatch(hour)
                or not isinstance(views, int) or not isinstance(visitors, int)
                or isinstance(views, bool) or isinstance(visitors, bool) or views < 0 or visitors < 0):
            raise ReportError(f"VISIT_COUNTS line is not the counter's shape: {message[:120]!r}")
        start = datetime.strptime(hour, "%Y-%m-%dT%H").replace(tzinfo=timezone.utc)
        day = days[start.astimezone(COUNT_ZONE).strftime("%Y-%m-%d")]
        day[0] += views
        day[1] += visitors
        lines += 1
    if not lines: raise ReportError("no VISIT_COUNTS line in the input (wrong container, or --since too short)")
    return {day: (counts[0], counts[1]) for day, counts in sorted(days.items())}


def chart_load(stream: TextIO) -> dict[str, dict[str, int]]:
    """{UTC hour: charts, refused_503, slow_1s_or_more} from the request events."""
    hours: dict[str, dict[str, int]] = {}
    for message, stamp in _entries(stream):
        event = _payload(message, EVENT_MARKER)
        if event is None or event.get("route") not in CHART_ROUTES: continue
        if stamp is None: raise ReportError("--chart-load needs `journalctl -o json`: a request event carries no time")
        hour = datetime.fromtimestamp(stamp / 1_000_000, timezone.utc).strftime("%Y-%m-%dT%H")
        counts = hours.setdefault(hour, {"charts": 0, "refused_503": 0, "slow_1s_or_more": 0})
        counts["charts"] += 1
        counts["refused_503"] += event.get("status_code") == 503
        counts["slow_1s_or_more"] += event.get("duration_bucket") in SLOW_BUCKETS
    if not hours: raise ReportError("no chart request event in the input")
    return dict(sorted(hours.items()))


def print_daily(days: dict[str, tuple[int, int]], out: TextIO) -> None:
    out.write("日期\t瀏覽數\t今日訪客數\n")
    for day, (views, visitors) in days.items():
        out.write(f"{day}\t{views}\t{visitors}\n")


def print_load(hours: dict[str, dict[str, int]], out: TextIO) -> None:
    out.write("UTC 小時\t排盤請求\t503 拒絕\t1 秒以上\t503 比例\n")
    for hour, counts in hours.items():
        share = counts["refused_503"] / counts["charts"]
        out.write(f"{hour}\t{counts['charts']}\t{counts['refused_503']}\t{counts['slow_1s_or_more']}\t{share:.1%}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--chart-load", action="store_true",
                        help="per UTC hour: chart requests, 503 refusals and answers of a second or more")
    arguments = parser.parse_args(argv)
    try:
        if arguments.chart_load:
            print_load(chart_load(sys.stdin), sys.stdout)
        else:
            print_daily(daily_visits(sys.stdin), sys.stdout)
    except ReportError as error:
        print(f"VISIT REPORT REFUSED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
