"""Page views and daily visitors, counted and nothing else.

Every page loads visit-count.js, which sends two requests without a body or a
cookie.  POST /api/visit arrives once per page load.  GET /api/visit/daily is
answered with a cache lifetime that ends at the next midnight in Taiwan, so a
browser asks it at most once a day and the number of those requests is the
number of browsers that day; the browser's own cache does the deduplication and
the service never tells two visitors apart.

Neither request is logged on its own.  Each worker keeps two integers and
writes one aggregate line for each clock hour that had any count, when the
next hour's first request arrives or the worker stops: the hour and the two
counts.  No address, user agent, referrer, page or request time is kept.  A day's
figures are the sum of its hours over every worker.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
import json
import logging
import threading
from typing import Final
from zoneinfo import ZoneInfo

EVENT_NAME: Final = "visit_counts"
EVENT_FIELDS: Final = ("event", "hour_utc", "page_views", "daily_visitors")
# The day a "daily visitor" belongs to: the operator's and most visitors' day.
COUNT_ZONE: Final = ZoneInfo("Asia/Taipei")
PAGE_VIEW: Final = "page_view"
DAILY_VISITOR: Final = "daily_visitor"

_LOGGER = logging.getLogger("classical_astrology.visits")
_LOGGER.setLevel(logging.INFO)
_LOGGER.propagate = False
if not any(getattr(handler, "_classical_astrology_visit_handler", False) for handler in _LOGGER.handlers):
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _handler._classical_astrology_visit_handler = True  # type: ignore[attr-defined]
    _LOGGER.addHandler(_handler)


def log_counts(line: dict) -> None:
    if tuple(line) != EVENT_FIELDS:
        return
    _LOGGER.info("VISIT_COUNTS %s", json.dumps(line, ensure_ascii=True, separators=(",", ":")))


def seconds_until_next_count_day(now: datetime) -> int:
    """How long a browser may keep the daily answer: until the next midnight in COUNT_ZONE."""

    local = now.astimezone(COUNT_ZONE)
    midnight = datetime(local.year, local.month, local.day, tzinfo=COUNT_ZONE) + timedelta(days=1)
    return max(1, int((midnight - local).total_seconds()))


class VisitCounter:
    """Two integers per worker, written out per clock hour."""

    def __init__(self, emit: Callable[[dict], None] = log_counts,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._lock = threading.Lock()
        self._emit = emit
        self._clock = clock
        self._hour = self._hour_of(clock())
        self._counts = {PAGE_VIEW: 0, DAILY_VISITOR: 0}

    @staticmethod
    def _hour_of(now: datetime) -> datetime:
        return now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)

    def _take(self) -> dict | None:
        counts, self._counts = self._counts, {PAGE_VIEW: 0, DAILY_VISITOR: 0}
        if not any(counts.values()):
            return None
        return {
            "event": EVENT_NAME,
            "hour_utc": self._hour.strftime("%Y-%m-%dT%H"),
            "page_views": counts[PAGE_VIEW],
            "daily_visitors": counts[DAILY_VISITOR],
        }

    def count(self, kind: str) -> None:
        if kind not in (PAGE_VIEW, DAILY_VISITOR):
            raise ValueError(kind)
        with self._lock:
            hour = self._hour_of(self._clock())
            finished = None
            if hour != self._hour:
                finished = self._take()
                self._hour = hour
            self._counts[kind] += 1
        if finished is not None:
            self._emit(finished)

    def flush(self) -> None:
        """Write the current hour's counts now (the worker is stopping)."""

        with self._lock:
            line = self._take()
        if line is not None:
            self._emit(line)
