"""〈平均交點與密切交點〉: figure 1 (osculating minus mean node over 2026, every
6 hours, with the osculating node's direct-motion spells) and the numbers the
article quotes.

The 1800–2400 and 1950–2050 statistics take about ten seconds (2.5 million
Swiss calls); `long_range_statistics` computes them and only the weekly slow
test recomputes them against the article's stat block.  The 2026 figure, the
mean node's speed, and the article's 重點 list and the methods page repeating
the stat block are checked daily.
"""
from __future__ import annotations

import re
import statistics

from ._common import calc_ut, indent, swiss


FRAGMENT = "blog-mean-vs-osculating-node"


def _flags(swe) -> int:
    return swe.FLG_SWIEPH | swe.FLG_SPEED


def _difference(swe, jd: float) -> float:
    true = calc_ut(swe, jd, swe.TRUE_NODE, _flags(swe))[0]
    mean = calc_ut(swe, jd, swe.MEAN_NODE, _flags(swe))[0]
    return ((true - mean + 180) % 360) - 180


def _year_2026(swe) -> dict:
    j0 = swe.julday(2026, 1, 1, 0)
    n = 365 * 4
    series = [(i / 4, _difference(swe, j0 + i / 4)) for i in range(n + 1)]
    changes = []
    previous = None
    for i in range(n + 1):
        direct = calc_ut(swe, j0 + i / 4, swe.TRUE_NODE, _flags(swe))[3] > 0
        if previous is not None and direct != previous:
            changes.append((i / 4, direct))
        previous = direct
    return {
        # Rounded as the figure has always been drawn from them.
        "series": [[round(day, 3), round(value, 4)] for day, value in series],
        "changes": changes,
        "mean_speed": calc_ut(swe, j0, swe.MEAN_NODE, _flags(swe))[3],
    }


def _figure(d: dict) -> str:
    L, R, T, B = 60, 620, 30, 250
    X = lambda day: L + (R - L) * day / 365  # noqa: E731
    Y = lambda v: T + (B - T) * (2.2 - v) / 4.4  # noqa: E731
    s = ['<svg viewBox="0 0 640 340" role="img" aria-label="2026 年全年，密切交點減平均交點的差，每 6 小時一點。'
         "差值在正負約 1.8 度之間來回擺動；下方紅色短條標出密切交點往前走（順行）的時段，一年約二十多次。"
         '平均交點全年等速後退，不會順行。">']
    for v in (-2, -1, 0, 1, 2):
        cls = "g-ink" if v == 0 else "g-hair"
        s.append(f'<line class="{cls}" x1="{L}" y1="{Y(v):.1f}" x2="{R}" y2="{Y(v):.1f}"/>')
        label = f"{v:+d}°" if v else "0°"
        s.append(f'<text class="t-faint" x="{L-10}" y="{Y(v)+6:.1f}" text-anchor="end">{label}</text>')
    months = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365]
    for i, m in enumerate(months[:-1]):
        s.append(f'<line class="g-hair" x1="{X(m):.1f}" y1="{B}" x2="{X(m):.1f}" y2="{B+8}"/>')
        s.append(f'<text class="t-faint" x="{X((m+months[i+1])/2):.1f}" y="{B+30}" text-anchor="middle">{i+1}</text>')
    starts = [day for day, direct in d["changes"] if direct]
    ends = [day for day, direct in d["changes"] if not direct]
    for a in starts:
        b = next((e for e in ends if e > a), 365)
        s.append(f'<rect class="f-accent" x="{X(a):.1f}" y="{B+42}" width="{max(X(b)-X(a),2):.1f}" height="14"/>')
    s.append(f'<text class="t-dim" x="{L}" y="{B+84}">紅條：密切交點此時往前走（順行）</text>')
    path = "M" + " L".join(f"{X(t):.1f},{Y(v):.1f}" for t, v in d["series"])
    s.append(f'<path class="g-accent-thin" d="{path}"/>')
    s.append(f'<text class="t-dim" x="{R}" y="{T-8}" text-anchor="end">密切交點 − 平均交點</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def build() -> tuple[dict[str, str], list[str]]:
    with swiss() as swe:
        d = _year_2026(swe)
    speed = -d["mean_speed"]
    quoted = [f"平均每天後退約 {speed:.3f} 度，一年約 {speed * 365.25:.1f} 度"]
    return {"difference-2026": _figure(d)}, quoted


def long_range_statistics() -> dict[str, str]:
    """The 1800–2400 and 1950–2050 statistics, formatted as the pages print them."""
    with swiss() as swe:
        values = []
        j, end = swe.julday(1800, 1, 1, 0), swe.julday(2400, 1, 1, 0)
        while j < end:
            values.append(abs(_difference(swe, j)))
            j += 0.25
        episodes, days, previous = 0, 0.0, None
        j, end = swe.julday(1950, 1, 1, 0), swe.julday(2050, 1, 1, 0)
        while j < end:
            direct = calc_ut(swe, j, swe.TRUE_NODE, _flags(swe))[3] > 0
            if direct:
                days += 0.25
            if direct and previous is False:
                episodes += 1
            previous = direct
            j += 0.25
    return {
        "max": f"{max(values):.2f}",
        "median": f"{statistics.median(values):.2f}",
        "episodes": f"{episodes / 100:.1f}",
        "days": f"{days / 100:.0f}",
    }


def long_range_quoted(stats: dict[str, str]) -> list[str]:
    """The article's stat block."""
    return [
        f"<b>{stats['max']}°</b><span>1800–2400 年間的最大差",
        f"<b>{stats['median']}°</b><span>差的中位數",
        f"<b>{stats['episodes']}</b><span>1950–2050 年間，密切交點平均每年「順行」的次數",
        f"<b>{stats['days']}</b><span>天：每年順行時段的合計",
    ]


def stats_in_article(fragment: str) -> dict[str, str]:
    """The statistics the article's stat block prints (the weekly test binds
    that block to `long_range_statistics`)."""
    found = {}
    for key, text in zip(("max", "median", "episodes", "days"), long_range_quoted(
        {"max": "X", "median": "X", "episodes": "X", "days": "X"}
    )):
        pattern = re.escape(text).replace("X", r"([0-9.]+)", 1)
        match = re.search(pattern, fragment)
        if match is None:
            raise RuntimeError(f"{FRAGMENT}: the stat block no longer prints {key!r}")
        found[key] = match.group(1)
    return found


def quoted_elsewhere(stats: dict[str, str]) -> dict[str, list[str]]:
    """Other prose that repeats the statistics, by fragment."""
    return {
        FRAGMENT: [
            f"兩者最大差 {stats['max']} 度，中位數 {stats['median']} 度",
            f"平均每年有 {stats['episodes']} 次短暫順行，合計約 {stats['days']} 天",
        ],
        "methods": [f"最大 {stats['max']} 度，一半的時間在 {stats['median']} 度以內"],
    }


def elsewhere(fragment: str) -> dict[str, list[str]]:
    """What `figures --check` requires daily: the repeats equal the stat block."""
    return quoted_elsewhere(stats_in_article(fragment))
