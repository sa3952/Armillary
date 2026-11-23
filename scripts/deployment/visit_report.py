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
carries no time of its own) and the per-second admission refusal totals (busy
refusals are written only there).  A line it cannot read stops it: a smaller
number would look like a quieter day.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import TextIO
from zoneinfo import ZoneInfo

COUNT_ZONE = ZoneInfo("Asia/Taipei")
# A worker writes each finished hour within one minute (FLUSH_INTERVAL_SECONDS in backend/app/visit_counts.py,
# not imported: this script runs on the host).  A day is sealed only after this much longer than that.
SEAL_AFTER_DAY_END = timedelta(minutes=10)
VISIT_MARKER = "VISIT_COUNTS "
EVENT_MARKER = "PRIVACY_EVENT "
REFUSALS_MARKER = "PRIVACY_REFUSALS "
HOUR = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}")
SECOND = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
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


def daily_visits(stream: TextIO, earliest: list[int] | None = None) -> dict[str, tuple[int, int]]:
    """{Taiwan date: (page views, daily visitors)}; `earliest`, when given, receives the oldest receive time seen."""
    days: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    lines = 0
    for message, stamp in _entries(stream):
        if earliest is not None and stamp is not None and (not earliest or stamp < earliest[0]):
            earliest[:] = [stamp]
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


def complete_days(days: dict[str, tuple[int, int]], earliest_us: int, now: datetime) -> dict[str, tuple[int, int]]:
    """The days the journal holds whole: begun after its oldest entry and ended (Taiwan) at least
    SEAL_AFTER_DAY_END ago, so every worker has written its last hour of the day."""
    kept = {}
    for day, counts in days.items():
        start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=COUNT_ZONE)
        if start + timedelta(days=1) + SEAL_AFTER_DAY_END <= now and start.timestamp() * 1_000_000 >= earliest_us:
            kept[day] = counts
    return kept


def read_archive(path: Path) -> dict[str, tuple[int, int]]:
    if not path.exists(): return {}
    rows = path.read_text(encoding="utf-8").splitlines()
    if not rows or rows[0] != "日期\t瀏覽數\t今日訪客數": raise ReportError(f"{path} is not a visit archive")
    days = {}
    for row in rows[1:]:
        fields = row.split("\t")
        if len(fields) != 3 or not all(field.isdigit() for field in fields[1:]):
            raise ReportError(f"{path}: unreadable row {row[:60]!r}")
        days[fields[0]] = (int(fields[1]), int(fields[2]))
    return days


def archive(stream: TextIO, path: Path, now: datetime) -> list[str]:
    """Add each whole day the journal holds and the archive lacks; a day already archived is never rewritten
    (the journal may since have dropped its first hours).  Returns the days added."""
    earliest: list[int] = []
    days = daily_visits(stream, earliest)
    if not earliest: raise ReportError("--archive needs `journalctl -o json`: plain lines carry no receive time")
    kept = read_archive(path)
    added = sorted(day for day in complete_days(days, earliest[0], now) if day not in kept)
    if not added: return []
    kept.update({day: days[day] for day in added})
    partial = path.with_name(path.name + ".partial")
    with partial.open("w", encoding="utf-8") as out:
        print_daily(dict(sorted(kept.items())), out)
    os.chmod(partial, 0o640)
    os.replace(partial, path)
    return added


def chart_load(stream: TextIO) -> dict[str, dict[str, int]]:
    """{UTC hour: charts, refused_503, slow_1s_or_more} from the request events."""
    hours: dict[str, dict[str, int]] = {}
    for message, stamp in _entries(stream):
        totals = _payload(message, REFUSALS_MARKER)
        if totals is not None:
            # Busy refusals arrive only as per-second totals, never as request events.
            second, rows = totals.get("second_utc"), totals.get("totals")
            if (totals.get("event") != "admission_refusals" or not isinstance(second, str)
                    or not SECOND.fullmatch(second) or not isinstance(rows, list)):
                raise ReportError(f"PRIVACY_REFUSALS line is not the totals' shape: {message[:120]!r}")
            for row in rows:
                count = row.get("count") if isinstance(row, dict) else None
                if (not isinstance(row, dict) or not isinstance(row.get("route"), str)
                        or not isinstance(count, int) or isinstance(count, bool) or count < 0):
                    raise ReportError(f"PRIVACY_REFUSALS line is not the totals' shape: {message[:120]!r}")
                if row["route"] not in CHART_ROUTES: continue
                counts = hours.setdefault(second[:13], {"charts": 0, "refused_503": 0, "slow_1s_or_more": 0})
                counts["charts"] += count
                counts["refused_503"] += count
            continue
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
    parser.add_argument("--archive", type=Path, metavar="FILE",
                        help="add each whole Taiwan day the journal holds to FILE (journal JSON only); never rewrites a day")
    arguments = parser.parse_args(argv)
    try:
        if arguments.archive is not None:
            added = archive(sys.stdin, arguments.archive, datetime.now(timezone.utc))
            print(f"[visit archive] added {', '.join(added) if added else 'nothing'}")
        elif arguments.chart_load:
            print_load(chart_load(sys.stdin), sys.stdout)
        else:
            print_daily(daily_visits(sys.stdin), sys.stdout)
    except ReportError as error:
        print(f"VISIT REPORT REFUSED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__": raise SystemExit(main())
