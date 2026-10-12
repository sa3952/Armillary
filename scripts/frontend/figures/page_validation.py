"""The validation page's run size: the hourly time points and body-hour rows
follow from the comparison run's configuration.

The run itself (JPL DE442＋Astropy／ERFA against the product, 2026-07-28) and
its findings report are kept outside this repository; the configuration below
is the one that report records (§3.1).  The run's results (the share within
the thresholds, the largest differences) are its observations and are not
recomputed here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from ._common import zh


FRAGMENT = "validation"
START = datetime(1990, 1, 1, 0, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)  # exclusive
STEP = timedelta(hours=1)
BODIES = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")


def size() -> tuple[int, int]:
    points = math.ceil((END - START) / STEP)
    return points, points * len(BODIES)


def build() -> tuple[dict[str, str], list[str]]:
    points, rows = size()
    quoted = [
        f"<b>{rows:,}</b><span>天體—小時比對列</span><small>{START.year}–{END.year}，{zh(len(BODIES))}個天體",
        f"{START:%Y-%m-%d}至{END:%Y-%m-%d}，逐小時，共{points:,}個時點",
    ]
    return {}, quoted
