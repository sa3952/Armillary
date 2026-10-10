"""〈出生時間差五分鐘〉: figure 1 (the ascendant across one hour) and figure 2
(how long each sign takes to rise at Taipei's latitude).

Synthetic instant only: 1990-05-15, Taipei 25.05306N 121.52639E, UTC+8 (no
daylight saving that year), the same instant as the home page demonstration.
"""
from __future__ import annotations

from ._common import SIGNS, calc_ut, indent, swiss


FRAGMENT = "blog-birth-time-sensitivity"
LAT, LON = 25.05306, 121.52639
# §03 quotes the product's ascendant at 14:00 and 14:59:59 (the home page
# demonstration); tests/publication/test_page_copy_facts.py binds them to the
# product's answer.  This module reads the clock as UT1 = UTC, while the product
# converts UTC with swe_utc_to_jd (UT1 = TT − Swiss ΔT, 0.079 s later here), so
# its ascendant is about 1.1″ ahead of this curve: invisible in the figure, and
# the reason the strings are not recomputed here.
# The crossing window the product's own sampling reports for this hour (the
# home page demonstration); the generator checks the ephemeris agrees.
CROSSING = ("14:22:58", "14:23:12")


def _data(swe) -> dict:
    def jd(h, m, s=0):  # local clock, UTC+8
        return swe.julday(1990, 5, 15, (h - 8) + m / 60 + s / 3600)

    def asc(j):
        return swe.houses_ex(j, LAT, LON, b"W")[1][0]

    out: dict = {}
    out["asc_per_minute"] = [[m, asc(jd(14, 0) + m / 1440)] for m in range(0, 61)]
    # Rising time per sign: scan 24 h from local 0:00 in 10 s steps.
    start = swe.julday(1990, 5, 14, 16.0)
    cross = {}
    prev = asc(start)
    for i in range(1, 8640 + 1):
        j = start + i * 10 / 86400
        a = asc(j)
        if int(a // 30) != int(prev // 30) and (a - prev) % 360 < 5:
            lo, hi = j - 10 / 86400, j
            for _ in range(40):
                mid = (lo + hi) / 2
                if int(asc(mid) // 30) == int(prev // 30):
                    lo = mid
                else:
                    hi = mid
            cross[int(a // 30)] = hi
        prev = a
    rising = {}
    for k in range(12):
        if k in cross and (k + 1) % 12 in cross:
            d = (cross[(k + 1) % 12] - cross[k]) * 1440
            if d < 0:
                d += 1440 * 0.99727
            rising[k] = d
    if sorted(rising) != list(range(12)):
        raise RuntimeError(f"rising times found for signs {sorted(rising)}, not all twelve")
    out["rising_minutes"] = rising
    # Sidereal day: the time for sidereal time to come round again.
    j0 = jd(14, 0)
    st0 = swe.sidtime(j0)
    lo, hi = j0 + 0.99, j0 + 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if (swe.sidtime(mid) - st0) % 24 > 12:
            lo = mid
        else:
            hi = mid
    out["sidereal_day_seconds"] = (hi - j0) * 86400
    # Motion in five minutes from 14:30.
    j = jd(14, 30)
    j5 = j + 5 / 1440
    for name, body in (("sun", swe.SUN), ("moon", swe.MOON)):
        a = calc_ut(swe, j, body)[0]
        b = calc_ut(swe, j5, body)[0]
        out[f"move5_{name}_arcmin"] = ((b - a) % 360) * 60
    out["move5_asc_deg"] = (asc(j5) - asc(j)) % 360
    # The Moon's daily speed over 1990.
    speeds = [calc_ut(swe, swe.julday(1990, 1, 1, 0) + d, swe.MOON, swe.FLG_SPEED)[3] for d in range(0, 365)]
    out["moon_speed_range"] = [min(speeds), max(speeds)]
    # The sign boundary falls inside the product's crossing window.
    (h0, m0, s0), (h1, m1, s1) = ([int(part) for part in t.split(":")] for t in CROSSING)
    before, after = asc(jd(h0, m0, s0)), asc(jd(h1, m1, s1))
    if not before < 180 <= after:
        raise RuntimeError(f"the ascendant does not cross 180° between {CROSSING}: {before}, {after}")
    return out


def _spoken(lon: float) -> str:
    """「處女座 24 度 47 分」: whole minutes, rounded."""
    total = round(lon * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]}座 {rest // 60} 度 {rest % 60} 分"


def _hero(d: dict) -> str:
    W, H = 640, 360
    L, R, T, B = 70, 610, 40, 290
    ymin, ymax = 174.0, 189.0
    X = lambda m: L + (R - L) * m / 60  # noqa: E731
    Y = lambda v: B - (B - T) * (v - ymin) / (ymax - ymin)  # noqa: E731
    pts = d["asc_per_minute"]
    path = "M" + " L".join(f"{X(m):.1f},{Y(v):.1f}" for m, v in pts)
    lo, hi = (22 * 60 + 58) / 60, (23 * 60 + 12) / 60
    probes = (0, 15, 30, 45, 59.983)
    first, last = pts[0][1], pts[-1][1]
    s = []
    s.append(
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="一小時裡的上升點。合成範例：1990 年 5 月 15 日'
        f"下午兩點到三點的臺北。上升點從{_spoken(first)}走到{_spoken(last)}，約 {(last - first) % 360:.1f} 度；"
        f"在 {CROSSING[0]} 到 {CROSSING[1]} 之間跨過處女與天秤的界線。五個圓點是本站實際取樣的時刻。\">"
    )
    s.append(f'<rect class="f-ring2-soft" x="{L}" y="{T}" width="{R-L}" height="{Y(180)-T:.1f}"/>')
    s.append(f'<rect class="f-ring3-soft" x="{L}" y="{Y(180):.1f}" width="{R-L}" height="{B-Y(180):.1f}"/>')
    s.append(f'<text class="t-dim" x="{R-12}" y="{T+28}" text-anchor="end">天秤座</text>')
    s.append(f'<text class="t-dim" x="{R-12}" y="{B-14}" text-anchor="end">處女座</text>')
    for m in (0, 15, 30, 45, 60):
        s.append(f'<line class="g-hair" x1="{X(m):.1f}" y1="{T}" x2="{X(m):.1f}" y2="{B}"/>')
        lab = f"14:{m:02d}" if m < 60 else "15:00"
        s.append(f'<text class="t-faint" x="{X(m):.1f}" y="{B+28}" text-anchor="middle">{lab}</text>')
    for v in (175, 180, 185):
        deg = v - 150 if v < 180 else v - 180
        s.append(f'<text class="t-faint" x="{L-10}" y="{Y(v)+6:.1f}" text-anchor="end">{deg}°</text>')
    s.append(f'<line class="g-ink" x1="{L}" y1="{Y(180):.1f}" x2="{R}" y2="{Y(180):.1f}"/>')
    s.append(f'<rect class="f-accent" x="{X(lo):.2f}" y="{T}" width="{max(X(hi)-X(lo),3):.2f}" height="{B-T}"/>')
    s.append(f'<text class="t-accent" x="{X(lo)-10:.1f}" y="{T+34}" text-anchor="end">{CROSSING[0]}–</text>')
    s.append(f'<text class="t-accent" x="{X(lo)-10:.1f}" y="{T+60}" text-anchor="end">{CROSSING[1]}</text>')
    s.append(f'<text class="t-dim" x="{X(lo)-10:.1f}" y="{T+90}" text-anchor="end">跨界區間</text>')
    s.append(f'<path class="g-ink" d="{path}"/>')
    by_minute = dict((int(a), b) for a, b in pts)
    for probe in probes:
        v = by_minute[int(round(probe)) if probe < 59.9 else 60]
        s.append(f'<circle class="f-paper" cx="{X(probe):.1f}" cy="{Y(v):.1f}" r="7"/>')
        s.append(f'<circle class="g-accent-thin" cx="{X(probe):.1f}" cy="{Y(v):.1f}" r="7"/>')
    s.append(f'<text class="t-faint" x="{L}" y="{H-8}">○ 本站取樣時刻　縱軸：上升點在星座內的度數</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def _bars(d: dict) -> str:
    rows = []
    for k in range(12):
        m = d["rising_minutes"][k]
        cls = "f-accent" if k in (5, 6) else "f-ring2"
        rows.append(
            f'        <div class="bar-row"><span>{SIGNS[k]}</span><span class="bar-track">'
            f'<svg viewBox="0 0 150 10" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
            f'<rect class="{cls}" width="{m:.1f}" height="10"/></svg></span><span>{m:.0f} 分</span></div>'
        )
    return "\n".join(rows)


def build() -> tuple[dict[str, str], list[str]]:
    with swiss() as swe:
        d = _data(swe)
    rising = d["rising_minutes"]
    slow = [rising[k] for k in range(3, 9)]
    first, last = d["asc_per_minute"][0][1], d["asc_per_minute"][-1][1]
    quoted = [
        f"<b>{d['move5_sun_arcmin']:.1f}′</b><span>太陽",
        f"<b>{d['move5_moon_arcmin']:.1f}′</b><span>月亮",
        f"<b>{d['move5_asc_deg']:.2f}°</b><span>上升點",
        f"介於 {d['moon_speed_range'][0]:.1f} 與 {d['moon_speed_range'][1]:.1f} 度之間",
        f"恆星日長度（{d['sidereal_day_seconds']:.2f} 秒）",
        f"上升點在這一小時裡走了約 {(last - first) % 360:.1f} 度，並在 {CROSSING[0]} 到 {CROSSING[1]} 之間",
        f"牡羊與雙魚最快，約 {rising[0]:.0f} 分鐘；巨蟹到射手六個星座最慢，約 {min(slow):.0f} 到 {max(slow):.0f} 分鐘",
    ]
    return {"ascendant-hour": _hero(d), "rising-times": _bars(d)}, quoted
