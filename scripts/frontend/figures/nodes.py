"""〈平均交點與密切交點〉: figures 1-3 of the article and the numbers it quotes (figure 1: osculating minus mean node over
2026; figure 2: a schematic; figure 3: how the difference is distributed 1800–2400).

The 1800–2400 and 1950–2050 statistics every 6 hours take about ten seconds (2.5 million Swiss calls);
`long_range_statistics` computes them and only the weekly slow test recomputes them against the article's stat block.
Figure 3 samples the same span once a day (about two seconds) and is checked daily; its maximum and median, rounded as
the stat block prints them, must equal the block's, so the block is held to a second sampling every day.  The 2026
figure, the mean node's speed, and the 重點 list and methods page repeating the stat block are checked daily.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
import re
import statistics

from . import _fx
from ._common import calc_ut, swiss

FRAGMENT = "blog-mean-vs-osculating-node"
MONTH_STARTS = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365)
SPAN = 2.2          # figure 1's vertical range, degrees either side of zero
BIN = 0.1           # figure 3's bin width, degrees
BINS = 20
# The page's first visible 密切交點 is in figure 1, so it carries the original there.
OSCULATING = "密切交點（osculating node）"

def _flags(swe) -> int:
    return swe.FLG_SWIEPH | swe.FLG_SPEED

def _difference(swe, jd: float, flags: int) -> float:
    true = calc_ut(swe, jd, swe.TRUE_NODE, flags)[0]
    mean = calc_ut(swe, jd, swe.MEAN_NODE, flags)[0]
    return ((true - mean + 180) % 360) - 180

def _year_2026(swe) -> dict:
    j0 = swe.julday(2026, 1, 1, 0)
    n = 365 * 4
    series = [(i / 4, _difference(swe, j0 + i / 4, _flags(swe))) for i in range(n + 1)]
    changes = []
    previous = None
    for i in range(n + 1):
        direct = calc_ut(swe, j0 + i / 4, swe.TRUE_NODE, _flags(swe))[3] > 0
        if previous is not None and direct != previous:
            changes.append((i / 4, direct))
        previous = direct
    return {
        "series": [[round(day, 3), round(value, 4)] for day, value in series],
        "changes": changes,
        "mean_speed": calc_ut(swe, j0, swe.MEAN_NODE, _flags(swe))[3],
    }

def _spells(changes: list[tuple[float, bool]], end: float = 365.0) -> list[tuple[float, float]]:
    if not changes:
        return []
    start: float | None = 0.0 if not changes[0][1] else None
    out = []
    for day, direct in changes:
        if direct:
            start = day
        elif start is not None:
            out.append((start, day))
            start = None
    if start is not None:
        out.append((start, end))
    return out

def _distribution(swe) -> dict:
    """|osculating − mean| at 0h UT of every day 1800-01-01 … 2399-12-31."""
    j0, end = swe.julday(1800, 1, 1, 0), swe.julday(2400, 1, 1, 0)
    values = [abs(_difference(swe, j0 + i, swe.FLG_SWIEPH)) for i in range(int(round(end - j0)))]
    if max(values) >= BIN * BINS:
        raise RuntimeError(f"a difference of {max(values):.3f}° falls outside figure 3's bins")
    counts = [0] * BINS
    for value in values:
        counts[int(value / BIN)] += 1
    return {"count": len(values), "shares": [c / len(values) for c in counts],
            "max": max(values), "median": statistics.median(values)}

# --- figure 1: the 2026 difference ----------------------------------------------

def _sign(v: float) -> str:
    return "0°" if v == 0 else f"{'+' if v > 0 else '−'}{abs(v):g}°"

def _curve_panel(d: dict, spells: list, d0: float, d1: float, box: tuple, wide: bool, bound: _fx.Bound) -> list[str]:
    L, R, T, B = box
    X = lambda day: L + (R - L) * (day - d0) / (d1 - d0)  # noqa: E731
    Y = lambda v: T + (B - T) * (SPAN - v) / (2 * SPAN)  # noqa: E731
    out = []
    for v in (-2, -1, 0, 1, 2):
        out.append(_fx.line(L, Y(v), R, Y(v), "fx-axis" if v == 0 else "fx-hair"))
        out.append(_fx.text(L - (10 if wide else 6), Y(v) + 5, bound.scale(_sign(v)), "fx-t fx-small fx-num", "end"))
    for i, start in enumerate(MONTH_STARTS[:-1]):
        stop = MONTH_STARTS[i + 1]
        if start < d0 or stop > d1:
            continue
        out.append(_fx.line(X(start), B, X(start), B + 6, "fx-axis"))
        out.append(_fx.text(X((start + stop) / 2), B + (24 if wide else 20), bound.scale(f"{i + 1} 月"),
                            "fx-t fx-small", "middle"))
    out.append(_fx.line(X(d1), B, X(d1), B + 6, "fx-axis"))
    points = [(t, v) for t, v in d["series"] if d0 <= t <= d1]
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(t))} {_fx.f(Y(v))}" for t, v in points), "fx-curve"))
    bar = B + (38 if wide else 30)
    for a, b in spells:
        a, b = max(a, d0), min(b, d1)
        if a < b:
            out.append(_fx.rect(X(a), bar, max(X(b) - X(a), 2), 12 if wide else 10, "fx-fill-solid"))
    return out

def _curve(layout: str, fid: str, d: dict, spells: list, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    if wide:
        W, H = _fx.WIDE, 392
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        out.append(_fx.text(92, 36, f"{OSCULATING} − 平均交點（度）", "fx-t"))
        out.append(_fx.text(852, 36, f"2026 年，每 {bound.label('6')} 小時一點", "fx-t fx-small fx-dim", "end"))
        out += _curve_panel(d, spells, 0, 365, (92, 852, 64, 292), True, bound)
        legend = 292 + 82
    else:
        W, H = _fx.NARROW, 480
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        out.append(_fx.text(14, 28, OSCULATING, "fx-t"))
        out.append(_fx.text(14, 48, "減平均交點（度）", "fx-t"))
        for d0, d1, top, name in ((0, 181, 84, "1–6 月"), (181, 365, 278, "7–12 月")):
            out.append(_fx.text(46, top - 12, bound.scale(f"2026 年 {name}"), "fx-t fx-small fx-dim"))
            out += _curve_panel(d, spells, d0, d1, (46, 326, top, top + 118), False, bound)
        legend = 278 + 118 + 64
    x0 = 92 if wide else 14
    out.append(_fx.rect(x0, legend - 11, 18, 12 if wide else 10, "fx-fill-solid"))
    out.append(_fx.text(x0 + 26, legend, "實心短條：密切交點往前走（順行）的時段" if wide else "實心短條：密切交點順行的時段", "fx-t fx-small"))
    if wide:
        out.append(_fx.text(852, legend, "平均交點全年等速後退，不會順行", "fx-t fx-small", "end"))
    out.append("</svg>")
    return "".join(out)

def _date(day: float) -> str:
    when = datetime(2026, 1, 1) + timedelta(days=day)
    return f"{when.month} 月 {when.day} 日"

def _spell_table(spells: list, bound: _fx.Bound) -> str:
    rows = []
    for a, b in spells:
        end = "年底仍在順行" if b >= 365 else bound.num(_date(b))
        days = f"{b - a:.2f}".rstrip("0").rstrip(".")
        rows.append(f'<tr><td>{bound.num(_date(a))}</td><td>{end}</td><td class="n">{bound.num(days)}</td></tr>')
    return _fx.data_table(("順行開始（約）", "順行結束（約）", "天數"), rows, summary="圖中的順行時段（表格）")

def _figure_2026(d: dict) -> str:
    bound = _fx.Bound()
    spells = _spells(d["changes"])
    values = [v for _, v in d["series"]]
    low, high = min(values), max(values)
    if not (SPAN > high > 1 and -SPAN < low < -1):
        raise RuntimeError(f"2026 differences {low:.2f}…{high:.2f} no longer fit figure 1's scale")
    caption = (f"<b>{bound.label('圖 1')}</b>{OSCULATING}減去平均交點的差，{bound.label('2026')} 年全年，"
               f"每 {bound.label('6')} 小時算一點。主要是一條約半年一個來回的大波，上面疊著兩週左右的小波；"
               "下方的實心短條是密切交點往前走（順行）的時段，"
               f"這一年共 {bound.num(str(len(spells)))} 段，日期列在表格裡（每 {bound.label('6')} 小時取樣，"
               f"起訖以世界時計）。平均交點全年都以固定速度後退<a class=\"ar-cite\" href=\"#ref-4\">{bound.label('[4]')}</a>。")
    return _fx.figure(fid="fig-node-2026", hero=True,
        title=f"2026 年全年，{OSCULATING}減平均交點的差，以及密切交點順行的時段", caption=caption,
        art=_fx.FigureArt.drawn(_curve, "fig-node-2026", d, spells, bound), table=_spell_table(spells, bound),
        bound=bound)

# --- figure 2: the schematic ----------------------------------------------------

# The orbit is drawn tilted far more than the real inclination and seen from just above the ecliptic, so its northern
# half rises clear of the plane in front and its southern half drops below it behind (TILT well over 2 × VIEW).
TILT = math.radians(30)
VIEW = math.radians(12)      # the eye's elevation above the ecliptic plane
ASCENDING_DEGREES = 180      # the ascending node at the left end of the drawing
ASCENDING = math.radians(ASCENDING_DEGREES)

def _projector(cx: float, cy: float, r: float):
    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return cx + r * x, cy - r * (y * math.sin(VIEW) + z * math.cos(VIEW))
    return project

def _orbit(u: float) -> tuple[float, float, float]:
    x = math.cos(ASCENDING) * math.cos(u) - math.sin(ASCENDING) * math.sin(u) * math.cos(TILT)
    y = math.sin(ASCENDING) * math.cos(u) + math.cos(ASCENDING) * math.sin(u) * math.cos(TILT)
    return x, y, math.sin(u) * math.sin(TILT)

def _poly(points: list[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{_fx.f(x)} {_fx.f(y)}" for x, y in points)

def _arrowhead(tip: tuple[float, float], back: tuple[float, float], size: float = 9) -> str:
    (x1, y1), (x0, y0) = tip, back
    length = math.hypot(x1 - x0, y1 - y0) or 1
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    bx, by = x1 - ux * size, y1 - uy * size
    return _fx.path(f"M{_fx.f(x1)} {_fx.f(y1)} L{_fx.f(bx - uy * size / 2)} {_fx.f(by + ux * size / 2)} "
                    f"L{_fx.f(bx + uy * size / 2)} {_fx.f(by - ux * size / 2)} Z", "fx-arrow")

def _node_mark(key: str, x: float, y: float, r: float) -> str:
    return _fx.circle(x, y, r, "fx-mk") + _fx.glyph(key, x, y, r * 1.2, "fx-mk-gl")

def _planes_art(cx: float, cy: float, r: float, wide: bool) -> list[str]:
    """The perspective: ecliptic plane, orbit (north half solid, south dashed), Earth, node line, nodes, regression arrow."""
    p = _projector(cx, cy, r)
    label = "fx-t fx-key" if wide else "fx-t fx-small fx-key"
    small = "fx-t fx-small fx-key"
    out = []
    ecliptic = [p(math.cos(math.radians(a)), math.sin(math.radians(a)), 0) for a in range(0, 361, 3)]
    out.append(_fx.path(_poly(ecliptic) + " Z", "fx-plane"))
    north = [p(*_orbit(math.radians(u))) for u in range(0, 181, 3)]
    south = [p(*_orbit(math.radians(u))) for u in range(180, 361, 3)]
    out.append(_fx.path(_poly(south), "fx-curve-dim"))
    asc, desc = p(*_orbit(0)), p(*_orbit(math.pi))
    out.append(_fx.line(asc[0], asc[1], desc[0], desc[1], "fx-sunline"))
    out.append(_fx.circle(cx, cy, 6 if wide else 5, "fx-disc"))
    out.append(_fx.text(cx + 12, cy + 6, "地球", small))
    out.append(_fx.path(_poly(north), "fx-curve"))
    # the Moon moving north, and its direction of motion
    moon = p(*_orbit(math.radians(58)))
    out.append(_arrowhead(p(*_orbit(math.radians(122))), p(*_orbit(math.radians(116)))))
    out.append(_fx.circle(moon[0], moon[1], 11 if wide else 9, "fx-mk")
               + _fx.glyph("moon", moon[0], moon[1], 12 if wide else 10, "fx-mk-gl"))
    out.append(_fx.text(moon[0] + 4, moon[1] - 18, "月亮", small, "middle"))
    crest = p(*_orbit(math.radians(96)))
    out.append(_fx.text(crest[0], crest[1] - 14, "月亮軌道", label, "middle"))
    out.append(_fx.text(cx - r * 0.5, cy + r * 0.12, "黃道面", label, "middle"))
    # the regression of the node line: an arc just outside the ecliptic, to lower longitude
    reach = 1.1 if wide else 1.2
    arc = [p(reach * math.cos(math.radians(a)), reach * math.sin(math.radians(a)), 0)
           for a in range(ASCENDING_DEGREES + 14, ASCENDING_DEGREES - 31, -3)]
    out.append(_fx.path(_poly(arc), "fx-curve"))
    out.append(_arrowhead(arc[-1], arc[-3]))
    r_mark = 12 if wide else 10
    out.append(_node_mark("north_node", asc[0], asc[1], r_mark))
    out.append(_node_mark("south_node", desc[0], desc[1], r_mark))
    reach_y = r * max(math.sin(VIEW), math.sin(TILT - VIEW))
    top, bottom = cy - reach_y, cy + reach_y
    if wide:
        out.append(_fx.text(asc[0] - 30, top - 26, "交點沿黃道後退", small))
        out.append(_fx.text(asc[0] - 30, bottom + 30, "北交點（升交點）", label))
        out.append(_fx.text(asc[0] - 30, bottom + 52, "月亮由南往北穿過黃道", "fx-t fx-small fx-dim fx-key"))
        out.append(_fx.text(desc[0] + 14, bottom + 30, "南交點（降交點）", label, "end"))
    else:
        out.append(_fx.text(14, top - 30, "交點沿黃道後退", small))
        out.append(_fx.text(14, bottom + 46, "北交點（升交點）", label))
        out.append(_fx.text(14, bottom + 64, "月亮由南往北穿過黃道", "fx-t fx-small fx-dim fx-key"))
        out.append(_fx.text(326, bottom + 46, "南交點（降交點）", label, "end"))
    return out

def _two_nodes(x0: float, x1: float, top: float, wide: bool) -> list[str]:
    """The two nodes along the ecliptic, unrolled into a line: the mean node moving back at an even pace, the
    osculating node swinging around it."""
    out = []
    small = "fx-t fx-small"
    out.append(_fx.text(x0, top, "沿著黃道看", "fx-t"))
    ly = top + (70 if wide else 60)
    out.append(_fx.line(x0, ly, x1, ly, "fx-axis"))
    out.append(_fx.text(x1, ly - 10, "黃道", "fx-t fx-small fx-dim", "end"))
    mx = x0 + (x1 - x0) * 0.58
    diamond = lambda x, y, s: _fx.path(  # noqa: E731
        f"M{_fx.f(x)} {_fx.f(y - s)} L{_fx.f(x + s)} {_fx.f(y)} L{_fx.f(x)} {_fx.f(y + s)} L{_fx.f(x - s)} {_fx.f(y)} Z", "fx-arrow")
    # mean node: the regression arrow above the line
    ay = ly - 26
    out.append(_fx.line(mx, ay, x0 + (x1 - x0) * 0.2, ay, "fx-axis"))
    out.append(_arrowhead((x0 + (x1 - x0) * 0.2 - 2, ay), (mx, ay)))
    out.append(_fx.text(x0 + (x1 - x0) * 0.38, ay - 10, "等速後退", "fx-t fx-small", "middle"))
    # osculating node: a swing on either side, below the line
    sx0, sx1 = mx - (x1 - x0) * 0.22, mx + (x1 - x0) * 0.22
    sy = ly + 24
    out.append(_fx.line(sx0 + 4, sy, sx1 - 4, sy, "fx-axis"))
    out.append(_arrowhead((sx0, sy), (mx, sy), 8) + _arrowhead((sx1, sy), (mx, sy), 8))
    out.append(_fx.text(mx, sy + 22, "前後擺動", "fx-t fx-small", "middle"))
    out.append(_fx.circle(mx - (x1 - x0) * 0.12, ly, 6, "fx-mk"))
    out.append(diamond(mx, ly, 7))
    ky = sy + (66 if wide else 58)
    out.append(diamond(x0 + 7, ky - 6, 7))
    out.append(_fx.text(x0 + 22, ky, "平均交點", "fx-t"))
    out.append(_fx.text(x0 + 22, ky + 22, "把擺動平滑掉，只留等速後退", small))
    ky += 60
    out.append(_fx.circle(x0 + 7, ky - 6, 6, "fx-mk"))
    out.append(_fx.text(x0 + 22, ky, "密切交點", "fx-t"))
    out.append(_fx.text(x0 + 22, ky + 22, "軟體裡的「真交點」：", small))
    out.append(_fx.text(x0 + 22, ky + 42, "此刻瞬時軌道與黃道的交點，", small))
    out.append(_fx.text(x0 + 22, ky + 62, "每個月在平均交點前後擺動", small))
    return out

def _planes(layout: str, fid: str) -> str:
    wide = layout == "fx-wide"
    if wide:
        W, H = _fx.WIDE, 420
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        out.append(_fx.text(24, 36, "示意圖，不按比例：兩個面的夾角畫得比實際大", "fx-t fx-small fx-dim"))
        out += _planes_art(306, 214, 236, True)
        out.append(_fx.line(584, 30, 584, H - 30, "fx-hair"))
        out += _two_nodes(606, 856, 64, True)
    else:
        W, H = _fx.NARROW, 616
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        out.append(_fx.text(14, 28, "示意圖，不按比例", "fx-t fx-small fx-dim"))
        out.append(_fx.text(14, 46, "兩個面的夾角畫得比實際大", "fx-t fx-small fx-dim"))
        out += _planes_art(178, 160, 132, False)
        out.append(_fx.line(14, 296, 326, 296, "fx-hair"))
        out += _two_nodes(14, 326, 330, False)
    out.append("</svg>")
    return "".join(out)

def _figure_planes() -> str:
    bound = _fx.Bound()
    return _fx.figure(
        fid="fig-node-planes",
        title="示意圖：月亮軌道面、黃道面與交點線，以及平均交點與密切交點沿黃道的走法",
        caption=(f"<b>{bound.label('圖 2')}</b>示意圖，不按比例。左：月亮軌道面與黃道面相交成一條交點線；"
                 "月亮由南往北穿過黃道的一點是北交點（升交點），另一端是南交點（降交點）；軌道在黃道北方的半圈畫實線，"
                 "南方的半圈畫虛線。交點線沿黃道往後退。右：把黃道拉直來看，平均交點只是等速後退；"
                 "密切交點是此刻瞬時軌道與黃道的交點，每個月在平均交點前後擺動。"),
        art=_fx.FigureArt.drawn(_planes, "fig-node-planes"),
        bound=bound,
    )

# --- figure 3: the distribution 1800–2400 ---------------------------------------

def _pct(share: float) -> str:
    return f"{share * 100:.1f}%"

def _histogram(layout: str, fid: str, dist: dict, texts: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    if wide:
        W, H = _fx.WIDE, 372
        L, R, T, B = 92.0, 852.0, 76.0, 300.0
    else:
        W, H = _fx.NARROW, 352
        L, R, T, B = 46.0, 326.0, 92.0, 280.0
    top_share = 10.0
    X = lambda v: L + (R - L) * v / (BIN * BINS)  # noqa: E731
    Y = lambda pct: B - (B - T) * pct / top_share  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    median, peak = dist["median"], dist["max"]
    for pct in ((0, 2, 4, 6, 8, 10) if wide else (0, 4, 8)):
        out.append(_fx.line(L, Y(pct), R, Y(pct), "fx-axis" if pct == 0 else "fx-hair"))
        out.append(_fx.text(L - (10 if wide else 6), Y(pct) + 5, bound.scale(f"{pct}%"), "fx-t fx-small fx-num", "end"))
    for i, share in enumerate(dist["shares"]):
        a, b = X(i * BIN) + 1, X((i + 1) * BIN) - 1
        y = Y(share * 100)
        out.append(_fx.rect(a, y, b - a, B - y, "fx-track"))
        hatch_end = min(b, X(median))
        if hatch_end > a:
            out.append(_fx.rect(a, y, hatch_end - a, B - y, "fx-fill-hatch"))
    mx = X(median)
    out.append(_fx.line(mx, T - (14 if wide else 8), mx, B, "fx-dash"))
    for t in (0, 0.5, 1, 1.5, 2):
        out.append(_fx.line(X(t), B, X(t), B + 6, "fx-axis"))
        out.append(_fx.text(X(t), B + 24 if wide else B + 20, bound.scale(f"{t:g}°"), "fx-t fx-small fx-num",
                            "start" if t == 0 else "end" if t == 2 else "middle"))
    px = X(peak)
    out.append(_fx.path(f"M{_fx.f(px)} {_fx.f(B - 1)} l-6 -11 h12 z", "fx-arrow"))
    if wide:
        out.append(_fx.text(L, 36, "佔全部時間的百分比", "fx-t fx-small fx-dim"))
        out.append(_fx.text(mx - 10, T - 2, texts["median"], "fx-t fx-key", "end"))
        out.append(_fx.text(mx - 10, T + 20, "一半的時間差在這以內（排線部分）", "fx-t fx-small fx-key", "end"))
        out.append(_fx.text(px - 4, Y(3.4), texts["max"], "fx-t fx-key", "end"))
        out.append(_fx.text((L + R) / 2, B + 52, "密切交點與平均交點相差幾度（每格 0.1 度）", "fx-t fx-small", "middle"))
    else:
        out.append(_fx.text(14, 28, f"虛線：{texts['median']}", "fx-t fx-small"))
        out.append(_fx.text(14, 46, "一半的時間差在這以內（排線部分）", "fx-t fx-small"))
        out.append(_fx.text(14, 64, f"三角形：{texts['max']}", "fx-t fx-small"))
        out.append(_fx.text((L + R) / 2, B + 46, "相差幾度（每格 0.1 度）", "fx-t fx-small", "middle"))
    bound.scale("0.1")
    out.append("</svg>")
    return "".join(out)

def _most_common(dist: dict) -> str:
    """The prose's 「最常見的是 a 到 b 度」: the three fullest bins, which must be adjacent."""
    top = sorted(sorted(range(BINS), key=lambda i: dist["shares"][i])[-3:])
    if top[-1] - top[0] != 2:
        raise RuntimeError(f"the three fullest bins {top} are not adjacent")
    return f"最常見的是 {top[0] * BIN:.1f} 到 {(top[-1] + 1) * BIN:.1f} 度"

def _figure_distribution(dist: dict) -> str:
    bound = _fx.Bound()
    median, peak = bound.num(f"{dist['median']:.2f}"), bound.num(f"{dist['max']:.2f}")
    texts = {"median": f"中位數 {median}°", "max": f"最大 {peak}°"}
    rows = "".join(
        f'<tr><td class="n">{bound.scale(f"{i * BIN:.1f}°–{(i + 1) * BIN:.1f}°")}</td>'
        f'<td class="n">{bound.num(_pct(share))}</td></tr>' for i, share in enumerate(dist["shares"]))
    table = _fx.data_table(("相差", "佔全部時間"), rows)
    count = bound.num(f"{dist['count']:,}")
    caption = (f"<b>{bound.label('圖 3')}</b>密切交點與平均交點相差幾度的分布：{bound.label('1800–2400')} 年，每天世界時 {bound.label('0')} 時取一點"
               f"（共 {count} 點）；每一條是 {bound.scale('0.1')} 度一格，"
               "高度是差落在這一格的時間佔全部的百分比。虛線是中位數 "
               f"{median} 度，左邊的排線部分是一半的時間；三角形是最大差 {peak} 度。這兩個數和 "
               f"{bound.label('§03')} 每 {bound.label('6')} 小時取樣的結果相同"
               f"<a class=\"ar-cite\" href=\"#ref-4\">{bound.label('[4]')}</a>。")
    return _fx.figure(fid="fig-node-spread", title="1800–2400 年，密切交點與平均交點相差幾度的分布", caption=caption,
        art=_fx.FigureArt.drawn(_histogram, "fig-node-spread", dist, texts, bound), table=table, bound=bound)

def build() -> tuple[dict[str, str], list[str]]:
    with swiss() as swe:
        d = _year_2026(swe)
        dist = _distribution(swe)
    speed = -d["mean_speed"]
    figures = {"difference-2026": _figure_2026(d), "planes": _figure_planes(), "spread": _figure_distribution(dist)}
    daily = {"max": f"{dist['max']:.2f}", "median": f"{dist['median']:.2f}"}
    quoted = [
        _most_common(dist),
        f"平均每天後退約 {speed:.3f} 度，一年約 {speed * 365.25:.1f} 度",
        # The stat block (every 6 hours, checked weekly) equals the daily sampling of figure 3.
        *long_range_quoted({**daily, "episodes": "", "days": ""})[:2],
    ]
    return {"fx-defs": _fx.defs(("moon", "north_node", "south_node")), **figures}, quoted

def long_range_statistics() -> dict[str, str]:
    with swiss() as swe:
        values = []
        j, end = swe.julday(1800, 1, 1, 0), swe.julday(2400, 1, 1, 0)
        while j < end:
            values.append(abs(_difference(swe, j, _flags(swe))))
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
    return {"max": f"{max(values):.2f}", "median": f"{statistics.median(values):.2f}", "episodes": f"{episodes / 100:.1f}",
        "days": f"{days / 100:.0f}"}

def long_range_quoted(stats: dict[str, str]) -> list[str]:
    return [f"<b>{stats['max']}°</b><span>1800–2400 年間的最大差", f"<b>{stats['median']}°</b><span>差的中位數",
        f"<b>{stats['episodes']}</b><span>1950–2050 年間，密切交點平均每年「順行」的次數",
        f"<b>{stats['days']}</b><span>天：每年順行時段的合計"]

def stats_in_article(fragment: str) -> dict[str, str]:
    """The statistics the article's stat block prints (the weekly test binds that block to `long_range_statistics`)."""
    found = {}
    for key, text in zip(("max", "median", "episodes", "days"),
        long_range_quoted({"max": "X", "median": "X", "episodes": "X", "days": "X"})):
        pattern = re.escape(text).replace("X", r"([0-9.]+)", 1)
        match = re.search(pattern, fragment)
        if match is None:
            raise RuntimeError(f"{FRAGMENT}: the stat block no longer prints {key!r}")
        found[key] = match.group(1)
    return found

def quoted_elsewhere(stats: dict[str, str]) -> dict[str, list[str]]:
    return {
        FRAGMENT: [
            f"兩者最大差 {stats['max']} 度，中位數 {stats['median']} 度",
            f"平均每年有 {stats['episodes']} 次短暫順行，合計約 {stats['days']} 天",
        ],
        "methods": [f"最大 {stats['max']} 度，一半的時間在 {stats['median']} 度以內"],
    }

def elsewhere(fragment: str) -> dict[str, list[str]]:
    return quoted_elsewhere(stats_in_article(fragment))
