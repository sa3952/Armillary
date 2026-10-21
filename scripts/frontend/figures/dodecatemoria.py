"""〈十二分部是什麼〉: figure 1 (a point walking through one sign and its
twelfth-part sign under both rules), figure 2 (a point moved through Taurus a
degree at a time, both rules' twelfth-parts on the wheel), figure 3 (the
ascendant and its twelfth-part at 14:30 and 14:34), table 1 (the five examples
the books give), table 2 (one synthetic hour as the result page marks it) and
the numbers the prose quotes.

The twelfth-parts are the product's own: `twelfth_part_longitude` from
backend/app/core/dodecatemoria.py for figures 1 and 2 and table 1, and the real
application in process for the synthetic chart (1990-05-15, Taipei, the
home page's demonstration date) in figure 3 and table 2.  Two oracles stand
apart from the product: each book's answer in table 1 is written here from the
source, and every twelfth-part figures 1 and 2 draw, and the share of a sign on
which the two rules agree, are worked exactly with Fractions.
"""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from . import _fx
from ._common import PLANETS, SIGNS, TAIPEI, backend_on_path, product_charts


FRAGMENT = "blog-dodecatemoria"
TWELVE = "twelvefold_from_sign_start_v1"
THIRTEEN = "thirteenfold_from_sign_start_v1"
RULES = (TWELVE, THIRTEEN)
CATEGORY = {"classical_planet": "行星", "angle": "軸點", "lot": "阿拉伯點"}

# The books' examples: (who, where, the point, its longitude, the rule the book
# uses or None when it gives only the sign, and the book's answer).  The answer
# is the source's, not the product's; build() refuses a row the product's rule
# no longer reproduces.
EXAMPLES = (
    ("Firmicus", "《Mathesis》II.13", "太陽", Fraction(5) + Fraction(5, 60), TWELVE, (2, Fraction(1)),
     "雙子第 1 度"),
    ("Paulus", "《導論》第 22 章", "某點", Fraction(11), THIRTEEN, (4, Fraction(23)), "獅子 23°"),
    ("Olympiodorus", "註 Paulus 第 20 章", "上升點", 210 + Fraction(20), THIRTEEN, (3, Fraction(20)), "巨蟹 20°"),
    ("Valens", "《占星選集》I.4", "太陽", 300 + Fraction(22), None, (7, None), "天蠍"),
    ("Porphyry", "《占星四書導論》第 39 章", "月亮", Fraction(13), None, (5, None), "處女"),
)

DEMO_DAY = {"year": 1990, "month": 5, "day": 15}
LOCATION = {"latitude": TAIPEI[0], "longitude": TAIPEI[1]}
OPTIONS = {"house_system": "W", "include_houses": True, "include_lots": True, "include_dodecatemoria": True}
HOUR = 14


def _exact(longitude: Fraction, multiplier: int) -> Fraction:
    start = longitude // 30 * 30
    return (start + multiplier * (longitude - start)) % 360


def _minutes(longitude: float) -> str:
    """「天秤 24°00′」: whole arcminutes."""
    sign, rest = divmod(round((longitude % 360) * 60), 30 * 60)
    return f"{SIGNS[sign % 12]} {rest // 60}°{rest % 60:02d}′"


def _zodiac_order(indices: list[int]) -> list[int]:
    """The result page's order for a set of signs: from the sign that opens the run."""
    present = set(indices)
    start = next((index for index in indices if (index + 11) % 12 not in present), None)
    if start is None:
        return sorted(indices)
    return [(start + step) % 12 for step in range(12) if (start + step) % 12 in present]


def _agreement() -> tuple[Fraction, Fraction, Fraction]:
    """(degrees of a sign on which the two rules give the same sign, the first
    and the last 2°30′ part's agreeing length), summed exactly: on the part
    [5k/2, 5(k+1)/2) the times-12 sign is k, and times 13 is k until 13d
    reaches 30(k+1)."""
    lengths = []
    for k in range(12):
        low, high = Fraction(5 * k, 2), Fraction(5 * (k + 1), 2)
        lengths.append(max(Fraction(0), min(high, Fraction(30 * (k + 1), 13)) - low))
    return sum(lengths, Fraction(0)), lengths[0], lengths[-1]


# --- figures --------------------------------------------------------------------
#
# Figure 1 (the page's hero: a point walking through one sign) and figure 3
# (14:30 against 14:34) are static; figure 2 moves a point through Taurus one
# degree a step with a slider.  Every twelfth-part drawn or written is the
# product's twelfth_part_longitude, and each is checked against the rule worked
# exactly in Fractions (`_exact`) before it is drawn; the lords are the
# product's own table.

RULE_LABELS = ((TWELVE, 12, "乘以 12", "Firmicus"), (THIRTEEN, 13, "乘以 13", "Paulus"))
# Figure 2 walks a point through Taurus, the sign of the worked example's Sun,
# and without script shows it at 24°, next to that Sun's 24°10′30″.
WALK_SIGN = 1
WALK_STEPS = 30
WALK_DEFAULT = 24
# Figure 3's ruler: Libra 0° to Scorpio 10°.
RULER_START = 180.0
RULER_SPAN = 40.0


def _cite(bound: _fx.Bound, number: int) -> str:
    return f'<a class="ar-cite" href="#ref-{number}">{bound.label(f"[{number}]")}</a>'


def _arc_text(value: Fraction) -> str:
    """「2°30′」, or 「2°18′」 for a length that is not a whole minute (then 「約」 is the caller's)."""
    minutes = int(value * 60)
    return f"{minutes // 60}°{minutes % 60:02d}′"


def _checked(twelfth_part, longitude: Fraction, rule: str, multiplier: int) -> float:
    """The product's twelfth-part, refused unless it lands in the exact rule's sign
    within a hundredth of an arcsecond of the exact rule's longitude."""
    value = twelfth_part(float(longitude), rule)
    exact = _exact(longitude, multiplier)
    if int(value // 30) != int(exact // 30) or abs(value - float(exact)) * 3600 > 0.01:
        raise RuntimeError(f"{rule} at {float(longitude)}: product {value}, exact rule {float(exact)}")
    return value


def _walk_cells(twelfth_part) -> tuple[dict[str, list[tuple[Fraction, Fraction, int]]], list[tuple[Fraction, Fraction]]]:
    """Figure 1's cells: per rule, the stretches of Aries whose twelfth-part
    stays in one sign; and the stretches where the two rules' signs differ."""
    cells = {}
    for rule, multiplier, _, _ in RULE_LABELS:
        edges = sorted({Fraction(0), Fraction(30), *(Fraction(30 * k, multiplier) for k in range(1, multiplier))})
        cells[rule] = [(low, high, int(_checked(twelfth_part, (low + high) / 2, rule, multiplier) // 30))
                       for low, high in zip(edges, edges[1:])]
    edges = sorted({Fraction(0), Fraction(30), *(Fraction(5 * k, 2) for k in range(1, 12)),
                    *(Fraction(30 * k, 13) for k in range(1, 13))})
    differ: list[tuple[Fraction, Fraction]] = []
    for low, high in zip(edges, edges[1:]):
        middle = (low + high) / 2
        signs = {int(_checked(twelfth_part, middle, rule, m) // 30) for rule, m, _, _ in RULE_LABELS}
        if len(signs) == 2:
            if differ and differ[-1][1] == low:
                differ[-1] = (differ[-1][0], high)
            else:
                differ.append((low, high))
    agree, _, _ = _agreement()
    if 30 - sum((high - low for low, high in differ), Fraction(0)) != agree:
        raise RuntimeError("figure 1's drawn disagreement is not the exact sum")
    return cells, differ


def _walk(layout: str, fid: str, cells: dict, differ: list, bound: _fx.Bound) -> str:
    """Figure 1, one layout: wide, the degrees run across and the two rules are
    rows; narrow, the degrees run down and the rules are columns."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    H = 300 if wide else 552
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        x0, x1 = 184.0, 850.0
        k = (x1 - x0) / 30

        def at(d) -> float:
            return x0 + float(d) * k

        for (rule, _, label, author), top in zip(RULE_LABELS, (38.0, 108.0)):
            out.append(_fx.text(24, top + 24, bound.label(label), "fx-t"))
            out.append(_fx.text(24, top + 46, author, "fx-t fx-small fx-dim"))
            for low, high, sign in cells[rule]:
                out.append(_fx.rect(at(low), top, at(high) - at(low), 54, "fx-track"))
                out.append(_fx.text((at(low) + at(high)) / 2, top + 33, SIGNS[sign], "fx-t", "middle"))
        band = 184.0
        out.append(_fx.text(24, band + 17, "落在不同星座", "fx-t fx-small"))
        out.append(_fx.rect(x0, band, x1 - x0, 22, "fx-track"))
        for low, high in differ:
            out.append(_fx.rect(at(low), band, at(high) - at(low), 22, "fx-fill-cross"))
        axis = 222.0
        out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
        for d in range(0, 31, 5):
            anchor = "start" if d == 0 else "end" if d == 30 else "middle"
            out.append(_fx.line(at(d), axis, at(d), axis + 6, "fx-axis"))
            out.append(_fx.text(at(d), axis + 26, bound.scale(f"{d}°"), "fx-t fx-small fx-num", anchor))
        out.append(_fx.text((x0 + x1) / 2, axis + 58, "這個點在牡羊座裡走到第幾度", "fx-t fx-small", "middle"))
    else:
        y0, k = 62.0, 15.0

        def at(d) -> float:
            return y0 + float(d) * k

        columns = ((64.0, 174.0), (182.0, 292.0))
        for (rule, _, label, author), (left, right) in zip(RULE_LABELS, columns):
            middle = (left + right) / 2
            out.append(_fx.text(middle, 28, bound.label(label), "fx-t", "middle"))
            out.append(_fx.text(middle, 48, author, "fx-t fx-small fx-dim", "middle"))
            for low, high, sign in cells[rule]:
                out.append(_fx.rect(left, at(low), right - left, at(high) - at(low), "fx-track"))
                out.append(_fx.text(middle, (at(low) + at(high)) / 2 + 5, SIGNS[sign], "fx-t", "middle"))
        out.append(_fx.text(313, 28, "不同", "fx-t fx-small", "middle"))
        out.append(_fx.text(313, 48, "星座", "fx-t fx-small", "middle"))
        out.append(_fx.rect(300, at(0), 26, at(30) - at(0), "fx-track"))
        for low, high in differ:
            out.append(_fx.rect(300, at(low), 26, at(high) - at(low), "fx-fill-cross"))
        out.append(_fx.line(58, at(0), 58, at(30), "fx-axis"))
        for d in range(0, 31, 5):
            out.append(_fx.line(52, at(d), 58, at(d), "fx-axis"))
            out.append(_fx.text(48, at(d) + 5, bound.scale(f"{d}°"), "fx-t fx-small fx-num", "end"))
        out.append(_fx.text(14, at(30) + 32, "這個點在牡羊座裡走到第幾度（往下）", "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)


def _polar(cx: float, cy: float):
    """Screen position of an ecliptic longitude on a wheel with Aries 0° on the
    left and the signs following counterclockwise, as the result page's wheel."""
    return lambda longitude, r: _fx.wheel_point(cx, cy, r, 180 + longitude)


def _walk_steps(twelfth_part, lords: dict[str, str]) -> list[dict]:
    """Figure 2's precomputed steps: the point at Taurus d° for d = 0 … 29."""
    from app.core.dignity_tables import SIGNS as SIGN_KEYS

    steps = []
    for d in range(WALK_STEPS):
        point = Fraction(30 * WALK_SIGN + d)
        step: dict[str, Any] = {"d": d, "point": float(point)}
        for rule, multiplier, _, _ in RULE_LABELS:
            value = _checked(twelfth_part, point, rule, multiplier)
            step[rule] = {"longitude": value, "lord": PLANETS[lords[SIGN_KEYS[int(value // 30)]]]}
        step["same"] = int(step[TWELVE]["longitude"] // 30) == int(step[THIRTEEN]["longitude"] // 30)
        if (step[THIRTEEN]["longitude"] - step[TWELVE]["longitude"] - d) % 360 > 1e-9:
            raise RuntimeError(f"step {d}: times 13 is not times 12 plus the degree")
        steps.append(step)
    return steps


def _wheel(layout: str, fid: str, steps: list[dict], bound: _fx.Bound) -> str:
    """Figure 2, one layout: the zodiac wheel with the point and its two
    twelfth-parts, one step group per degree; the readings beside (wide) or
    below (narrow) the wheel."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        cx, cy, r_out, r_in, H = 240.0, 240.0, 196.0, 152.0, 480
        marks = ((TWELVE, r_in - 30, 15.0), (THIRTEEN, r_in - 66, 15.0))
    else:
        cx, cy, r_out, r_in, H = 170.0, 166.0, 150.0, 114.0, 500
        marks = ((TWELVE, r_in - 22, 11.0), (THIRTEEN, r_in - 50, 11.0))
    at = _polar(cx, cy)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    # The sign the point walks through, hatched; then the ring and the names.
    (ax, ay), (bx, by) = at(30.0 * WALK_SIGN, r_out), at(30.0 * WALK_SIGN + 30, r_out)
    (cx2, cy2), (dx, dy) = at(30.0 * WALK_SIGN + 30, r_in), at(30.0 * WALK_SIGN, r_in)
    f = _fx.f
    out.append(_fx.path(f"M{f(ax)} {f(ay)} A{f(r_out)} {f(r_out)} 0 0 0 {f(bx)} {f(by)} L{f(cx2)} {f(cy2)} "
                        f"A{f(r_in)} {f(r_in)} 0 0 1 {f(dx)} {f(dy)} Z", "fx-fill-hatch"))
    out.append(_fx.circle(cx, cy, r_out, "fx-lens") + _fx.circle(cx, cy, r_in, "fx-lens"))
    for sign in range(12):
        (sx, sy), (ex, ey) = at(30.0 * sign, r_in), at(30.0 * sign, r_out)
        out.append(_fx.line(sx, sy, ex, ey, "fx-axis"))
        nx, ny = at(30.0 * sign + 15, (r_in + r_out) / 2)
        out.append(_fx.text(nx, ny + (6 if wide else 5), SIGNS[sign], "fx-t fx-key" if sign == WALK_SIGN else "fx-t",
                            "middle"))
    out.append(_fx.circle(cx, cy, 2.5, "fx-fill-solid"))
    if wide:
        px, label_x = 478.0, 600.0
        rows = {"point": 92.0, TWELVE: 168.0, THIRTEEN: 268.0, "gap": 362.0}
    else:
        px, label_x = 14.0, 110.0
        rows = {"point": 352.0, TWELVE: 384.0, THIRTEEN: 432.0, "gap": 476.0}
    out.append(_fx.text(px, rows["point"], "點", "fx-t"))
    for rule, _, label, _ in RULE_LABELS:
        out.append(_fx.text(px, rows[rule], bound.label(label), "fx-t"))
    small = "fx-t fx-small"
    for step in steps:
        d = step["d"]
        body = []
        x, y = at(step["point"], r_in)
        body.append(_fx.circle(x, y, 6 if wide else 5, "fx-fill-solid"))
        for rule, radius, size in marks:
            lon = step[rule]["longitude"]
            mx, my = at(lon, radius)
            body.append(_fx.line(cx, cy, mx, my, "fx-hair"))
            body.append(_fx.circle(mx, my, size, "fx-mk"))
            body.append(_fx.text(mx, my + (5 if wide else 4), bound.label("12" if rule == TWELVE else "13"),
                                 "fx-t fx-small fx-num", "middle"))
        if d:
            # The arc from times 12 on to times 13: the point's own degree.
            arc_r = r_in - (98 if wide else 72)
            (ux, uy), (vx, vy) = at(step[TWELVE]["longitude"], arc_r), at(step[THIRTEEN]["longitude"], arc_r)
            body.append(_fx.path(f"M{f(ux)} {f(uy)} A{f(arc_r)} {f(arc_r)} 0 0 0 {f(vx)} {f(vy)}", "fx-axis"))
        values = {rule: bound.num(_minutes(step[rule]["longitude"])) for rule in RULES}
        body.append(_fx.text(label_x, rows["point"], bound.num(f"{SIGNS[WALK_SIGN]} {d}°"), "fx-t fx-num"))
        for rule in RULES:
            body.append(_fx.text(label_x, rows[rule], values[rule], "fx-t fx-num"))
            body.append(_fx.text(label_x, rows[rule] + (26 if wide else 20), f"守護行星：{step[rule]['lord']}", small))
        verdict = "同一個星座" if step["same"] else "不同星座"
        gap = bound.num(f"{d}°")
        if wide:
            body.append(_fx.text(px, rows["gap"], f"乘以 13 比乘以 12 多走 {gap}，", "fx-t"))
            body.append(_fx.text(px, rows["gap"] + 30, f"兩者落在{verdict}。", "fx-t"))
        else:
            body.append(_fx.text(px, rows["gap"], f"乘以 13 多走 {gap}，落在{verdict}。", "fx-t"))
        out.append(_fx.step_group(d, WALK_DEFAULT, "".join(body)))
    if wide:
        out.append(_fx.text(px, 444, "排線的一格：點所在的金牛座", small + " fx-dim"))
    out.append("</svg>")
    return "".join(out)


def _wheel_sentence(step: dict, bound: _fx.Bound) -> str:
    d = step["d"]
    verdict = "落在同一個星座" if step["same"] else "落在不同星座"
    return (f"點在{bound.num(f'{SIGNS[WALK_SIGN]} {d}°')}：乘以 12 落在{bound.num(_minutes(step[TWELVE]['longitude']))}"
            f"（守護行星{step[TWELVE]['lord']}），乘以 13 落在{bound.num(_minutes(step[THIRTEEN]['longitude']))}"
            f"（守護行星{step[THIRTEEN]['lord']}）；乘以 13 多走了 {bound.num(f'{d}°')}，{verdict}。")


def _wheel_table(steps: list[dict], bound: _fx.Bound) -> str:
    rows = []
    for step in steps:
        cells = "".join(f'<td class="n">{bound.num(_minutes(step[rule]["longitude"]))}（{step[rule]["lord"]}）</td>'
                        for rule in RULES)
        rows.append(f'<tr><th scope="row">{bound.num(f"{SIGNS[WALK_SIGN]} {step["d"]}°")}</th>{cells}'
                    f'<td>{"同一個" if step["same"] else "不同"}</td></tr>')
    return _fx.data_table(("點", f"{bound.label('乘以 12')}（守護行星）", f"{bound.label('乘以 13')}（守護行星）", "星座"), rows)


def _ruler(layout: str, fid: str, pair: dict, bound: _fx.Bound) -> str:
    """Figure 3, one layout: the ascendant at 14:30 and 14:34 and its twelfth-part,
    on one ruler from Libra 0° to Scorpio 10°."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (232.0, 850.0) if wide else (14.0, 326.0)
    k = (x1 - x0) / RULER_SPAN

    def at(longitude: float) -> float:
        offset = longitude - RULER_START
        if not 0 <= offset <= RULER_SPAN:
            raise RuntimeError(f"figure 3: {longitude} is off the ruler")
        return x0 + offset * k

    before, after = pair[30]["asc"], pair[34]["asc"]
    moved = bound.num(f"{round((after['point_longitude'] - before['point_longitude']) * 60)}′")
    jumped = bound.num(f"約 {round((after['longitude'] - before['longitude']) % 360)}°")
    times = (bound.num("14:30"), bound.num("14:34"))
    boundary = at(RULER_START + 30)
    lords = (PLANETS[before["domicile_lord"]], PLANETS[after["domicile_lord"]])
    if int(before["longitude"] // 30) != 6 or int(after["longitude"] // 30) != 7:
        raise RuntimeError("figure 3: the twelfth-part no longer crosses from Libra into Scorpio")
    if wide:
        H = 332
        tracks = ((96.0, "point_longitude"), (186.0, "longitude"))
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        out.append(_fx.text((x0 + boundary) / 2, 46, f"天秤　守護行星 {lords[0]}", "fx-t fx-small", "middle"))
        out.append(_fx.text((boundary + x1) / 2, 46, f"天蠍　守護行星 {lords[1]}", "fx-t fx-small", "middle"))
        out.append(_fx.text(24, tracks[0][0] + 17, "上升點", "fx-t"))
        out.append(_fx.text(24, tracks[1][0] + 10, "十二分部", "fx-t"))
        out.append(_fx.text(24, tracks[1][0] + 32, f"（{bound.label('乘以 12')}）", "fx-t fx-small fx-dim"))
        th, r = 24.0, 6.5
    else:
        H = 246
        tracks = ((90.0, "point_longitude"), (148.0, "longitude"))
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        out.append(_fx.circle(22, 24, 4.5, "fx-mk") + _fx.text(32, 29, times[0], "fx-t fx-small fx-num"))
        out.append(_fx.circle(98, 24, 4.5, "fx-fill-solid") + _fx.text(108, 29, times[1], "fx-t fx-small fx-num"))
        out.append(_fx.text((x0 + boundary) / 2, 56, f"天秤・{lords[0]}", "fx-t fx-small", "middle"))
        out.append(_fx.text((boundary + x1) / 2, 56, f"天蠍・{lords[1]}", "fx-t fx-small", "middle"))
        th, r = 16.0, 4.5
    for top, field in tracks:
        out.append(_fx.rect(x0, top, x1 - x0, th, "fx-track"))
    out.append(_fx.line(boundary, tracks[0][0] - (34 if wide else 26), boundary, tracks[1][0] + th + 8, "fx-axis"))
    (top_a, field_a), (top_b, field_b) = tracks
    for item in (before, after):
        out.append(_fx.line(at(item[field_a]), top_a + th, at(item[field_b]), top_b, "fx-sunline"))
    if not wide:
        # after the leaders, so the paper outline of the words masks them
        out.append(_fx.text(x0, tracks[0][0] - 8, f"上升點：走了 {moved}", "fx-t fx-key"))
        out.append(_fx.text(x0, tracks[1][0] - 8, f"十二分部（{bound.label('乘以 12')}）：走了{jumped}", "fx-t fx-key"))
    for top, field in tracks:
        cy = top + th / 2
        for item, cls, time, side in ((before, "fx-mk", times[0], "end"), (after, "fx-fill-solid", times[1], "start")):
            x = at(item[field])
            out.append(_fx.circle(x, cy, r, cls))
            if wide:
                out.append(_fx.text(x + (-7 if side == "end" else 7), top - 8, time, "fx-t fx-small fx-num fx-key", side))
        if wide:
            a, b = at(before[field]), at(after[field])
            y = top + th + 8
            out.append(_fx.path(f"M{_fx.f(a)} {_fx.f(y)} v6 H{_fx.f(b)} v-6", "fx-axis"))
            out.append(_fx.text((a + b) / 2, y + 26, f"走了 {moved}" if field == field_a else f"走了{jumped}",
                                "fx-t fx-small", "middle"))
    axis = (tracks[1][0] + th + (52 if wide else 18))
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    step = 5 if wide else 10
    for offset in range(0, int(RULER_SPAN) + 1, step):
        x = x0 + offset * k
        anchor = "start" if offset == 0 else "end" if offset == RULER_SPAN else "middle"
        out.append(_fx.line(x, axis, x, axis + 5, "fx-axis"))
        out.append(_fx.text(x, axis + 22, bound.scale(f"{offset % 30}°"), "fx-t fx-small fx-num", anchor))
    span = f"天秤 {bound.scale('0°')} 到天蠍 {bound.scale('10°')}，等比例"
    out.append(_fx.text((x0 + x1) / 2, axis + (48 if wide else 44), span, "fx-t fx-small", "middle"))
    out.append("</svg>")
    if axis + 48 > H:
        raise RuntimeError("figure 3 outgrew its drawing")
    return "".join(out)


def _ruler_table(pair: dict, bound: _fx.Bound) -> str:
    rows = []
    for minute in (30, 34):
        asc = pair[minute]["asc"]
        rows.append(f'<tr><th scope="row">{bound.num(f"14:{minute}")}</th>'
                    f'<td class="n">{bound.num(_minutes(asc["point_longitude"]))}</td>'
                    f'<td class="n">{bound.num(_minutes(asc["longitude"]))}</td><td>{PLANETS[asc["domicile_lord"]]}</td></tr>')
    return _fx.data_table(("出生時間", "上升點", f"十二分部（{bound.label('乘以 12')}）", "守護行星"), rows)


def _figures(twelfth_part, lords: dict[str, str], pair: dict) -> dict[str, str]:
    """The page's sprite and its three figures, each checked by `_fx.problems`."""
    cells, differ = _walk_cells(twelfth_part)
    walk_bound = _fx.Bound()
    agree, _, _ = _agreement()
    twelve_part = walk_bound.num(_arc_text(Fraction(30, 12)))
    thirteen_part = walk_bound.num(_arc_text(Fraction(30, 13)))
    walk = _fx.figure(
        fid="fig-sign-walk",
        hero=True,
        title="一個點從牡羊座 0° 走到 30° 時，兩種算法的十二分部各落在哪個星座",
        caption=(f"<b>{walk_bound.label('圖 1')}</b>一個點從牡羊座 {walk_bound.scale('0°')} 走到 {walk_bound.scale('30°')} 時，"
                 f"它的十二分部落在哪個星座。上排乘以 {walk_bound.label('12')}，點每走 {twelve_part} 換一個星座，"
                 f"從牡羊一路數到雙魚；下排乘以 {walk_bound.label('13')}，每約 {thirteen_part} 換一個，數完雙魚，"
                 f"最後一小段又回到牡羊。最下面一條的交叉排線標出兩種算法落在不同星座的度數，合計 "
                 f"{walk_bound.num(f'{30 - int(agree)}°')}，一半{_cite(walk_bound, 9)}。"),
        art=_fx.FigureArt.drawn(_walk, "fig-sign-walk", cells, differ, walk_bound),
        bound=walk_bound,
    )

    steps = _walk_steps(twelfth_part, lords)
    wheel_bound = _fx.Bound()
    sun = pair[30]["sun"]
    wheel = _fx.figure(
        fid="fig-two-rules",
        title="一個點在金牛座裡逐度移動時，乘以 12 與乘以 13 的落點",
        caption=(f"<b>{wheel_bound.label('圖 2')}</b>拖拉滑桿，讓一個點在金牛座裡從 {wheel_bound.scale('0°')} 走到 "
                 f"{wheel_bound.scale('29°')}，一次 {wheel_bound.scale('1°')}。圓上是十二個星座，排線那一格是金牛；"
                 f"標「{wheel_bound.label('12')}」的是乘以 12 的落點，標「{wheel_bound.label('13')}」的是乘以 13 的落點，"
                 f"兩者都從金牛的起點往後數。圓心旁的弧是乘以 13 比乘以 12 多走的那一段，正好等於點在星座內的度數，"
                 f"所以點越往後，兩者分得越開。預設停在 {wheel_bound.scale(f'{WALK_DEFAULT}°')}，接近上面例子裡太陽的 "
                 f"{wheel_bound.num(sun['point_sign_position'][1].split('.')[0] + '″')}{_cite(wheel_bound, 9)}。"),
        art=_fx.FigureArt.drawn(
            _wheel, "fig-two-rules", steps, wheel_bound,
            notes=[_fx.Note(None, None, _wheel_sentence(step, wheel_bound), step=step["d"]) for step in steps],
            idle="拖拉滑桿，選這個點在金牛座裡的度數。",
        ),
        controls=_fx.FigureControls(
            steps=WALK_STEPS,
            default_step=WALK_DEFAULT,
            scrub_label="點在金牛座裡的度數",
        ),
        table=_wheel_table(steps, wheel_bound),
        bound=wheel_bound,
    )

    ruler_bound = _fx.Bound()
    before, after = pair[30]["asc"], pair[34]["asc"]
    ruler = _fx.figure(
        fid="fig-four-minutes",
        title="出生時間從 14:30 改成 14:34，上升點與它的十二分部各走了多遠",
        caption=(f"<b>{ruler_bound.label('圖 3')}</b>同一張合成範例，出生時間從 {ruler_bound.num('14:30')} 改成 "
                 f"{ruler_bound.num('14:34')}。上排是上升點，從{ruler_bound.num(_minutes(before['point_longitude']))} "
                 f"走到{ruler_bound.num(_minutes(after['point_longitude']))}；下排是它的十二分部（乘以 "
                 f"{ruler_bound.label('12')}），從{ruler_bound.num(_minutes(before['longitude']))} 跨進"
                 f"{ruler_bound.num(_minutes(after['longitude']))}。兩排用同一把尺，空心圓是 14:30，實心圓是 14:34，"
                 f"虛線連起同一個時刻的上升點與它的十二分部{_cite(ruler_bound, 9)}。"),
        art=_fx.FigureArt.drawn(_ruler, "fig-four-minutes", pair, ruler_bound),
        table=_ruler_table(pair, ruler_bound),
        bound=ruler_bound,
    )
    return {"fx-defs": _fx.defs(()), "sign-walk": walk, "two-rules": wheel, "four-minutes": ruler}


def _example_rows(twelfth_part) -> str:
    rows = []
    for who, where, point, longitude, rule, (sign, degree), answer in EXAMPLES:
        results = {name: twelfth_part(float(longitude), name) for name in RULES}
        exact = {name: _exact(longitude, 12 if name == TWELVE else 13) for name in RULES}
        for name in RULES:
            if int(results[name] // 30) != int(exact[name] // 30):
                raise RuntimeError(f"{who}: the product's {name} sign is not the rule's")
        fits = [name for name in RULES if int(exact[name] // 30) == sign]
        if rule is not None and (rule not in fits or exact[rule] - 30 * sign != degree):
            raise RuntimeError(f"{who}: the book's answer {answer} is not the named rule's")
        if rule is None and not fits:
            raise RuntimeError(f"{who}: neither rule gives the book's sign {answer}")
        differ = int(exact[TWELVE] // 30) != int(exact[THIRTEEN] // 30)
        verdict = ("兩種都合" if len(fits) == 2 and rule is None
                   else "只合乘以 13" if fits == [THIRTEEN] and rule is None
                   else "乘以 12" if rule == TWELVE else "乘以 13")
        cells = [f'{who}<br><small>{where}</small>', f"{point}　{_minutes(float(longitude))}"]
        for name in RULES:
            mark = ' class="n diff"' if differ else ' class="n"'
            cells.append(f"<td{mark}>{_minutes(float(exact[name]))}</td>")
        rows.append(
            f'          <tr><th scope="row">{cells[0]}</th><td class="n">{cells[1]}</td>{cells[2]}{cells[3]}'
            f"<td>{answer}（{verdict}）</td></tr>"
        )
    return "\n".join(rows)


def _hour(post) -> tuple[str, dict]:
    request = {"birth_time_precision": "approximate_hour",
               "datetime": {**DEMO_DAY, "hour": HOUR, "minute": 0, "second": 0},
               "location": LOCATION, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"}, "options": OPTIONS}
    answer = post(request)
    module = answer["derived_methods"]["dodecatemoria"]
    sensitivity = answer["birth_time_sensitivity"]
    if module["profile"] != TWELVE or sensitivity["precision"] != "approximate_hour":
        raise RuntimeError("the synthetic hour was not computed with the default rule")
    sampled = {item["key"]: item["sampled_sign_indices"] for item in sensitivity["dodecatemoria_signs"]}
    rows, many = [], []
    for point in module["points"]:
        signs = sampled[point["key"]]
        position = f"{SIGNS[point['sign_position'][0]]} {point['sign_position'][1]}"
        name = point["name"]
        if len(signs) >= 2:
            many.append(point["key"])
            name += " ※"
            position += "（這段時間內會換星座，取樣到：" + "、".join(SIGNS[i] for i in _zodiac_order(signs)) + "）"
        original = f"{SIGNS[point['point_sign_position'][0]]} {point['point_sign_position'][1]}"
        rows.append(f'          <tr><th scope="row">{name}</th><td>{CATEGORY[point["category"]]}</td>'
                    f"<td>{original}</td><td>{position}</td><td>{PLANETS[point['domicile_lord']]}</td></tr>")
    return "\n".join(rows), {"many": many, "samples": sampled}


def _day(post) -> dict:
    """Date only, both rules: the signs each planet's twelfth-part was sampled in."""
    out = {}
    for rule in RULES:
        answer = post({"birth_time_precision": "date_only",
                       "datetime": {**DEMO_DAY, "hour": 0, "minute": 0, "second": 0},
                       "location": LOCATION, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
                       "options": {**OPTIONS, "dodecatemoria_profile": rule}})
        out[rule] = {item["key"]: len(item["sampled_sign_indices"])
                     for item in answer["birth_time_sensitivity"]["dodecatemoria_signs"]}
    return out


def _exact_pair(post) -> dict:
    """14:30 and 14:34 on the demonstration day: the ascendant and its twelfth-part."""
    found = {}
    for minute in (30, 34):
        answer = post({"birth_time_precision": "exact",
                       "datetime": {**DEMO_DAY, "hour": HOUR, "minute": minute, "second": 0},
                       "location": LOCATION, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
                       "options": OPTIONS})
        points = {point["key"]: point for point in answer["derived_methods"]["dodecatemoria"]["points"]}
        found[minute] = points
    return found


def build() -> tuple[dict[str, str], list[str]]:
    with backend_on_path():
        from app.core.dodecatemoria import twelfth_part_longitude

        examples = _example_rows(twelfth_part_longitude)
        # Times 12 skips a sign when the point enters the next one; times 13 runs on.
        just_before = 30 - 1e-9
        skip = (int(twelfth_part_longitude(just_before, TWELVE) // 30), int(twelfth_part_longitude(30.0, TWELVE) // 30))
        runs_on = (int(twelfth_part_longitude(just_before, THIRTEEN) // 30),
                   int(twelfth_part_longitude(30.0, THIRTEEN) // 30))
        if skip != (11, 1) or runs_on != (0, 1):
            raise RuntimeError(f"the sign-entry behaviour changed: {skip}, {runs_on}")
    with product_charts() as post:
        hour_rows, hour = _hour(post)
        day = _day(post)
        pair = _exact_pair(post)

    agree, first, last = _agreement()
    if agree != 15:
        raise RuntimeError(f"the two rules agree on {agree} degrees of a sign, not 15")

    def arc(value: Fraction) -> str:
        seconds = round(value * 3600)
        return f"{seconds // 3600}°{seconds % 3600 // 60:02d}′{seconds % 60:02d}″"

    sun = pair[30]["sun"]
    asc_before, asc_after = pair[30]["asc"], pair[34]["asc"]
    moved = asc_after["point_longitude"] - asc_before["point_longitude"]
    twelfth_moved = (asc_after["longitude"] - asc_before["longitude"]) % 360
    with backend_on_path():
        from app.core.dodecatemoria import twelfth_part_longitude

        sun_13 = twelfth_part_longitude(sun["point_longitude"], THIRTEEN)
        from app.core.dodecatemoria import DOMICILE_LORD_BY_SIGN

        figures = _figures(twelfth_part_longitude, DOMICILE_LORD_BY_SIGN, pair)
    many_names = {"asc": "上升點", "fortune": "命運點", "spirit": "精神點"}
    if hour["many"] != list(many_names):
        raise RuntimeError(f"the synthetic hour marks {hour['many']}, not the ascendant and the two Lots")
    each = {len(hour["samples"][key]) for key in many_names}
    if len(each) != 1:
        raise RuntimeError(f"the ascendant and the Lots were sampled in different numbers of signs: {each}")
    sampled_each = each.pop()
    moon_day = day[TWELVE]["moon"]
    venus = (day[TWELVE]["venus"], day[THIRTEEN]["venus"])
    if venus != (2, 1):
        raise RuntimeError(f"Venus's sampled signs on the day are {venus}, not (2, 1)")
    zh_counts = "一二三四五六七八九十"
    quoted = [
        f"合計正好 {int(agree)}°，一半",
        f"第一段 2°30′ 裡有 {arc(first)} 相同，最後一段只有 {arc(last)}",
        f"太陽在金牛 {sun['point_sign_position'][1].split('.')[0]}″",
        f"得{_minutes(sun['longitude'])}，水瓶的守護行星是土星",
        f"得{_minutes(sun_13)}，雙魚的守護行星是木星",
        f"上升點從{_minutes(asc_before['point_longitude'])} 走到{_minutes(asc_after['point_longitude'])}，"
        f"只動了 {round(moved * 60)}′",
        f"十二分部卻從{_minutes(asc_before['longitude'])} 跳到{_minutes(asc_after['longitude'])}，"
        f"走了約 {round(twelfth_moved)}°",
        f"月亮的十二分部在取樣的時刻裡出現過{zh_counts[moon_day - 1]}個星座",
        "金星用乘以 12 時取樣到兩個星座，改用乘以 13 只有一個",
        f"上升點、命運點、精神點各取樣到{zh_counts[sampled_each - 1]}個",
    ]
    return {**figures, "examples": examples, "hour": hour_rows}, quoted
