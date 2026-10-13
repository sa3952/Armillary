"""〈產前朔望與產前日月食〉: figure 1 (the timeline of the readings birth),
figure 2 (the luminaries' altitudes at the full Moon and at the birth),
figure 3 (the Earth's shadow, a schematic), the readings table and the eclipse
table, and the numbers the prose quotes, as the product answers three Taipei
births in process, plus the share of births whose last lunar eclipse is only
penumbral, counted with Swiss Ephemeris over the product's year range (the same
search the product runs, about half a second).
"""
from __future__ import annotations

import bisect
from datetime import datetime
import functools

from . import _fx
from ._common import product_charts, swiss
from ._demo import DEMO, zodiacal


FRAGMENT = "blog-prenatal-syzygy"
# The three births the article works through: the full Moon whose degree the
# readings disagree on, a birth during the 1999-08-11 solar eclipse, and one
# whose last lunar eclipse is only penumbral.
READINGS = {"year": 2000, "month": 1, "day": 1, "hour": 12, "minute": 0, "second": 0}
UNDER_WAY = {"year": 1999, "month": 8, "day": 11, "hour": 18, "minute": 30, "second": 0}
PENUMBRAL = {"year": 1999, "month": 3, "day": 1, "hour": 12, "minute": 0, "second": 0}
OPTIONS = {"house_system": "W", "include_houses": True,
           "include_lunar_phases": True, "include_eclipses": True}
ECLIPSE_TYPE_ZH = {"total": "全食", "partial": "偏食", "annular": "環食", "hybrid": "複合日食",
                   "penumbral": "半影食"}


def _request(moment: dict) -> dict:
    return {"datetime": moment, "location": DEMO["location"], "timezone": DEMO["timezone"],
            "options": OPTIONS}


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    with product_charts() as post:
        return {name: post(_request(moment))["astronomical_data"]["lunar_events"]
                for name, moment in (("readings", READINGS), ("under_way", UNDER_WAY),
                                     ("penumbral", PENUMBRAL))}


def _minute(local_time: str) -> str:
    """「1999-12-23 01:31」: the product's birthplace clock, cut to the minute."""
    return local_time[:16]


def _altitude(reading: dict) -> str:
    value = reading["altitude_true_degrees"]
    return ("+" if value >= 0 else "−") + f"{abs(value):.1f}°"


def _readings(events: dict) -> dict:
    syzygy = events["prenatal_syzygy"]
    at_birth = events["prenatal_syzygy_at_birth"]
    profile = at_birth["sect_profile"]
    other = profile["other_previous_syzygy"]
    selection = syzygy["degree_selection"]
    horizon = selection["horizon_at_syzygy"]
    luminaries = at_birth["luminaries_above_horizon_at_birth"]
    if (syzygy["phase"], selection["state"], selection["selected_luminary"]) != ("full_moon", "selected", "moon"):
        raise RuntimeError("the readings birth no longer has a full Moon whose Moon is chosen")
    if (profile["sect_status"], profile["state"], profile["selected"], other["phase"]) != (
            "day", "selected", "other_previous_syzygy", "new_moon"):
        raise RuntimeError("the readings birth no longer picks the earlier new Moon by day")
    if not (luminaries["sun"]["above_horizon"] and luminaries["moon"]["above_horizon"]):
        raise RuntimeError("the readings birth no longer has both luminaries above the horizon at birth")
    new = other["event"]
    return {
        "full_local": _minute(syzygy["local_time"]),
        "full_days": at_birth["hours_before_birth"] / 24,
        "full_sun": zodiacal(syzygy["sun_longitude"]),
        "full_moon": zodiacal(syzygy["moon_longitude"]),
        "moon_alt": _altitude(horizon["moon"]),
        "sun_alt": _altitude(horizon["sun"]),
        "new_local": _minute(new["local_time"]),
        "new_days": other["hours_before_birth"] / 24,
        "new_degree": zodiacal(new["sun_longitude"]),
        "birth_sun_alt": _altitude(luminaries["sun"]),
        "birth_moon_alt": _altitude(luminaries["moon"]),
    }


# --- figures --------------------------------------------------------------------
#
# Figure 1 (the page's hero: the readings birth's new Moon, full Moon and birth
# on one line of days) and figure 3 (the shadow, a schematic) are static;
# figure 2 draws the luminaries' altitudes at the full Moon and at the birth,
# switched by two buttons.  Every date, altitude and degree is the product's
# answer; the verdict printed is re-read from the drawn altitudes (`_drawn_pick`)
# and must agree with the product's.

TIMELINE_START = datetime(1999, 12, 4)
TIMELINE_DAYS = 31
TIMELINE_TICKS = ("1999-12-05", "1999-12-15", "1999-12-25", "2000-01-04")
BIRTH_LOCAL = "2000-01-01 12:00"
LUMINARY_ZH = {"sun": "太陽", "moon": "月亮"}
HORIZON_VARIANTS = (("syzygy", "朔望那一刻（本站預設）"), ("birth", "出生那一刻（另一個手抄本）"))
HORIZON_SWITCH = "切換看哪一刻的地平線"
HORIZON_IDLE = "用 Tab 鍵移到太陽或月亮上，或用滑鼠指著它，這裡會寫出它的高度與這個讀法取不取它。"


def _day(local: str) -> float:
    """Days from the timeline's start to a birthplace clock reading."""
    moment = datetime.strptime(local[:16], "%Y-%m-%d %H:%M")
    days = (moment - TIMELINE_START).total_seconds() / 86400
    if not 0 <= days <= TIMELINE_DAYS:
        raise RuntimeError(f"figure 1: {local} is off the timeline")
    return days


def _timeline(layout: str, fid: str, r: dict, bound: _fx.Bound) -> str:
    """Figure 1, one layout: wide, the days run across; narrow, they run down."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    events = (("new", r["new_local"], "新月（朔）", "fx-b-caz"), ("full", r["full_local"], "滿月（望）", "fx-mk"))
    when = {key: bound.num(local[5:16]) for key, local, _, _ in events}
    birth = bound.num(BIRTH_LOCAL[5:])
    near = f"最近一次：滿月（出生前 {bound.num(f'{r['full_days']:.1f}')} 天）"
    sect_line = ("日生盤看前一次新月，", f"越過較近的滿月（出生前 {bound.num(f'{r['new_days']:.1f}')} 天）")
    rows = ((f"最近一次朔望（{bound.label('卷三第 2 章')}）", f"滿月，取在地平線上方的月亮：{bound.num(r['full_moon'])}"),
            (f"日生看朔（{bound.label('卷三第 10 章')}、Lilly）", f"新月：{bound.num(r['new_degree'])}"))
    if wide:
        H = 356
        x0, x1, y = 56.0, 824.0, 150.0
        k = (x1 - x0) / TIMELINE_DAYS
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        at = {key: x0 + _day(local) * k for key, local, _, _ in events}
        xb = x0 + _day(BIRTH_LOCAL) * k
        out.append(_fx.line(x0, y, x1, y, "fx-axis"))
        for tick in TIMELINE_TICKS:
            x = x0 + _day(tick + " 00:00") * k
            out.append(_fx.line(x, y, x, y + 6, "fx-axis"))
            out.append(_fx.text(x, y + 62, bound.scale(tick[5:]), "fx-t fx-small fx-num fx-dim", "middle"))
        # The nearest syzygy above the line, the day chart's pick below, as brackets back from the birth.
        out.append(_fx.path(f"M{_fx.f(at['full'])} {y - 46} V{y - 56} H{_fx.f(xb)} V{y - 46}", "fx-axis"))
        out.append(_fx.text((at["full"] + xb) / 2, y - 66, near, "fx-t fx-small", "middle"))
        out.append(_fx.path(f"M{_fx.f(at['new'])} {y + 74} V{y + 84} H{_fx.f(xb)} V{y + 74}", "fx-hair"))
        out.append(_fx.text((at["new"] + xb) / 2, y + 106, sect_line[0] + sect_line[1], "fx-t fx-small", "middle"))
        for key, _, name, cls in events:
            out.append(_fx.circle(at[key], y, 12, cls))
            out.append(_fx.text(at[key], y - 22, name, "fx-t", "middle"))
            out.append(_fx.text(at[key], y + 36, when[key], "fx-t fx-small fx-num", "middle"))
        out.append(_fx.line(xb, y - 20, xb, y + 20, "fx-frame"))
        out.append(_fx.text(xb, y - 26, "出生", "fx-t", "middle"))
        out.append(_fx.text(xb, y + 36, birth, "fx-t fx-small fx-num", "middle"))
        for i, (name, value) in enumerate(rows):
            yy = 296 + i * 34
            out.append(_fx.text(x0, yy, name, "fx-t fx-small fx-dim"))
            out.append(_fx.text(392, yy, value, "fx-t fx-num"))
        if xb + 30 > x1 + 30 or at["new"] < x0:
            raise RuntimeError("figure 1 outgrew its drawing")
    else:
        H = 590
        x, y0, k = 74.0, 64.0, 13.0
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        at = {key: y0 + _day(local) * k for key, local, _, _ in events}
        yb = y0 + _day(BIRTH_LOCAL) * k
        out.append(_fx.line(x, y0, x, y0 + TIMELINE_DAYS * k, "fx-axis"))
        for tick in TIMELINE_TICKS:
            ty = y0 + _day(tick + " 00:00") * k
            out.append(_fx.line(x - 6, ty, x, ty, "fx-axis"))
            out.append(_fx.text(x - 10, ty + 4, bound.scale(tick[5:]), "fx-t fx-small fx-num fx-dim", "end"))
        out.append(_fx.text(14, 32, "日期往下增加", "fx-t fx-small fx-dim"))
        for key, _, name, cls in events:
            out.append(_fx.circle(x, at[key], 10, cls))
            out.append(_fx.text(x + 20, at[key] - 2, name, "fx-t"))
            out.append(_fx.text(x + 20, at[key] + 16, when[key], "fx-t fx-small fx-num"))
        out.append(_fx.line(x - 16, yb, x + 16, yb, "fx-frame"))
        out.append(_fx.text(x + 20, yb - 2, "出生", "fx-t"))
        out.append(_fx.text(x + 20, yb + 16, birth, "fx-t fx-small fx-num"))
        # Brackets back from the birth: the nearest syzygy, then the day chart's pick.
        bx1, bx2 = 252.0, 226.0
        out.append(_fx.path(f"M{bx1 - 8} {_fx.f(at['full'])} H{bx1} V{_fx.f(yb)} H{bx1 - 8}", "fx-axis"))
        out.append(_fx.text(bx1 + 8, (at["full"] + yb) / 2 - 8, "最近一次：", "fx-t fx-small"))
        out.append(_fx.text(bx1 + 8, (at["full"] + yb) / 2 + 10, "滿月", "fx-t fx-small"))
        out.append(_fx.path(f"M{bx2 - 8} {_fx.f(at['new'])} H{bx2} V{_fx.f(yb)} H{bx2 - 8}", "fx-hair"))
        for i, part in enumerate(("日生盤看", "前一次新月", "（越過較近", "的滿月）")):
            out.append(_fx.text(bx2 + 8, at["new"] + 70 + i * 18, part, "fx-t fx-small"))
        for i, (name, value) in enumerate(rows):
            ry = y0 + TIMELINE_DAYS * k + 36 + i * 50
            out.append(_fx.text(14, ry, name, "fx-t fx-small fx-dim"))
            out.append(_fx.text(14, ry + 22, value, "fx-t fx-num"))
    out.append("</svg>")
    return "".join(out)


def _pick(horizon: dict) -> str | None:
    """The luminary a reading takes from the altitudes: the one above when the
    other is below, else none (both above, both below)."""
    above = [key for key in ("sun", "moon") if horizon[key]["above_horizon"]]
    return above[0] if len(above) == 1 else None


def _drawn_pick(ys: dict[str, float], horizon_y: float) -> str | None:
    """The same read from the drawing: a mark above the horizon line is up."""
    above = [key for key in ("sun", "moon") if ys[key] < horizon_y]
    return above[0] if len(above) == 1 else None


def _horizon_data(events: dict) -> dict:
    syzygy = events["prenatal_syzygy"]
    selection = syzygy["degree_selection"]
    at_syzygy = selection["horizon_at_syzygy"]
    at_birth = events["prenatal_syzygy_at_birth"]["luminaries_above_horizon_at_birth"]
    if any(item[key]["in_near_horizon_band"] for item in (at_syzygy, at_birth) for key in ("sun", "moon")):
        raise RuntimeError("figure 2: a luminary is in the near-horizon band, which the drawing does not show")
    if _pick(at_syzygy) != selection["selected_luminary"]:
        raise RuntimeError("figure 2: the altitudes do not give the product's pick")
    degrees = {"sun": zodiacal(syzygy["sun_longitude"]), "moon": zodiacal(syzygy["moon_longitude"])}
    return {
        "syzygy": {"horizon": at_syzygy, "pick": selection["selected_luminary"],
                   "when": _minute(syzygy["local_time"]), "moment": "滿月那一刻"},
        "birth": {"horizon": at_birth, "pick": _pick(at_birth), "when": BIRTH_LOCAL, "moment": "出生那一刻"},
        "degrees": degrees,
    }


def _horizon_sentence(key: str, variant: str, data: dict, bound: _fx.Bound) -> str:
    item = data[variant]
    alt = bound.num(_altitude(item["horizon"][key]))
    other = "moon" if key == "sun" else "sun"
    up = item["horizon"][key]["above_horizon"]
    text = f"{LUMINARY_ZH[key]}：{item['moment']}（{bound.num(item['when'])}，臺北）高度 {alt}，在地平線{'上' if up else '下'}方。"
    reading = "照 Robbins 採用的讀法" if variant == "syzygy" else "照出生那一刻的讀法"
    if item["pick"] == key:
        text += f"{reading}，取{LUMINARY_ZH[key]}的度數：{bound.num(data['degrees'][key])}。"
    elif item["pick"] == other:
        text += f"{reading}，不取它的度數（{bound.num(data['degrees'][key])}）。"
    else:
        both = "上" if up else "下"
        text += f"{LUMINARY_ZH[other]}也在{both}方，{reading}選不出來。"
    return text


def _horizon_mark(key: str, cx: float, cy: float, r: float, label: str) -> str:
    return (f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{label}">'
            + _fx.circle(cx, cy, r + 8, "fx-hit") + _fx.circle(cx, cy, r, "fx-mk")
            + _fx.glyph(key, cx, cy, r * 1.25, "fx-mk-gl"))


def _horizon(layout: str, fid: str, data: dict, bound: _fx.Bound) -> str:
    """Figure 2, one layout: an altitude scale, the horizon, the region below it
    hatched; the Sun and the Moon at their altitudes; and the reading's verdict,
    one group per moment."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, ax, top, per, right = 450, 108.0, 64.0, 2.0, 520.0
        xs = {"sun": 250.0, "moon": 400.0}
        r = 12.0
    else:
        H, ax, top, per, right = 420, 60.0, 50.0, 1.3, 326.0
        xs = {"sun": 128.0, "moon": 236.0}
        r = 10.0
    horizon_y = top + 90 * per
    y = lambda alt: horizon_y - alt * per  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.rect(ax + 6, horizon_y, right - ax - 6, 90 * per, "fx-b-beam"))
    out.append(_fx.line(ax + 6, horizon_y, right, horizon_y, "fx-axis"))
    out.append(_fx.text(right - 6, horizon_y - 8, "地平線", "fx-t fx-small fx-key", "end"))
    out.append(_fx.text(right - 6, y(-90) - 10, "地平線下", "fx-t fx-small fx-key", "end"))
    out.append(_fx.line(ax, y(90), ax, y(-90), "fx-axis"))
    for alt in (90, 45, 0, -45, -90):
        out.append(_fx.line(ax - 5, y(alt), ax, y(alt), "fx-axis"))
        sign = "+" if alt > 0 else "−" if alt < 0 else ""
        out.append(_fx.text(ax - 9, y(alt) + 5, bound.scale(f"{sign}{abs(alt)}°"), "fx-t fx-small fx-num", "end"))
    out.append(_fx.text(ax - 9 if wide else 14, top - 22 if wide else top - 22, "高度", "fx-t fx-small fx-dim",
                        "end" if wide else None))
    for variant, _ in HORIZON_VARIANTS:
        item = data[variant]
        ys = {key: y(item["horizon"][key]["altitude_true_degrees"]) for key in ("sun", "moon")}
        if _drawn_pick(ys, horizon_y) != item["pick"]:
            raise RuntimeError(f"figure 2 {variant}: drawn {_drawn_pick(ys, horizon_y)}, the product says {item['pick']}")
        body = []
        for key in ("sun", "moon"):
            height = bound.num(_altitude(item["horizon"][key]))
            body.append(_horizon_mark(key, xs[key], ys[key], r, f"{LUMINARY_ZH[key]}，{item['moment']}高度 {height}"))
            body.append(_fx.text(xs[key] + r + 8, ys[key] - 2, LUMINARY_ZH[key], "fx-t fx-small fx-key"))
            body.append(_fx.text(xs[key] + r + 8, ys[key] + 16, height, "fx-t fx-small fx-num fx-key"))
            body.append("</g>")
        pick = item["pick"]
        when = bound.num(item["when"])
        if pick is None:
            verdict = ("太陽、月亮都在", "地平線上方：", "這個讀法選不出來") if item["horizon"]["sun"]["above_horizon"] else (
                "太陽、月亮都在", "地平線下方：", "這個讀法選不出來")
            degree = ""
        else:
            other = "moon" if pick == "sun" else "sun"
            verdict = (f"{LUMINARY_ZH[pick]}在地平線上方，", f"{LUMINARY_ZH[other]}在下方：", f"取{LUMINARY_ZH[pick]}的度數")
            degree = bound.num(data["degrees"][pick])
        source = ((f"《占星四書》{bound.label('卷三第 2 章')}，", "Robbins 採用的讀法") if variant == "syzygy"
                  else (f"Robbins 註 {bound.label('9')} 記下的", "另一個手抄本讀法（只當資訊）"))
        if wide:
            px = 560.0
            lines = [(84, item["moment"], "fx-t"), (110, f"{when}，臺北", "fx-t fx-small fx-num")]
            lines += [(160 + i * 28, line, "fx-t") for i, line in enumerate(verdict)]
            if degree:
                lines.append((250, degree, "fx-t fx-num"))
            lines += [(330 + i * 24, line, "fx-t fx-small fx-dim") for i, line in enumerate(source)]
        else:
            px = 14.0
            base = y(-90) + 34
            lines = [(base, f"{item['moment']}（{when}）", "fx-t fx-small fx-num")]
            lines.append((base + 24, verdict[0] + verdict[1], "fx-t"))
            lines.append((base + 48, verdict[2] + ("：" + degree if degree else ""), "fx-t fx-num"))
            lines.append((base + 74, source[0] + source[1], "fx-t fx-small fx-dim"))
        body += [_fx.text(px, ly, text_, cls) for ly, text_, cls in lines]
        out.append(_fx.variant_group(variant, HORIZON_VARIANTS[0][0], "".join(body)))
    out.append("</svg>")
    return "".join(out)


def _shadow(layout: str, fid: str, bound: _fx.Bound) -> str:
    """Figure 3, a schematic, one layout: the Sun, the Earth and its two shadows
    from the side; and the shadow's cross-section where the Moon passes, with
    three paths of the Moon.  Not to scale: the shadow is drawn with the umbra
    half the penumbra's width and the Moon a little under half the umbra's, near
    their apparent sizes at the Moon's distance."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, cy, xs, s, xe, e, xm, end = 340, 190.0, 60.0, 40.0, 300.0, 24.0, 360.0, 400.0
        sx, sy, umb, pen, moon = 600.0, 190.0, 50.0, 100.0, 20.0
        tracks = (("penumbral", -76.0), ("total", 0.0), ("partial", 48.0))
    else:
        H, cy, xs, s, xe, e, xm, end = 392, 76.0, 40.0, 24.0, 240.0, 14.4, 290.0, 326.0
        sx, sy, umb, pen, moon = 222.0, 272.0, 45.0, 90.0, 18.0
        tracks = (("penumbral", -72.0), ("total", 0.0), ("partial", 47.0))
    names = {"penumbral": ("只經過半影：", "半影月食"), "total": ("整個進入本影：", "全食"),
             "partial": ("一部分進入本影：", "偏食")}
    # The drawn paths must be what their labels say.
    for kind, offset in tracks:
        near, far = abs(offset) - moon, abs(offset) + moon
        drawn = ("total" if far <= umb else "partial" if near < umb else "penumbral" if near < pen else "none")
        if drawn != kind:
            raise RuntimeError(f"figure 3: the {kind} path is drawn as {drawn}")
    d = xe - xs
    umbra = lambda x: e - (s - e) / d * (x - xe)  # noqa: E731
    penumbra = lambda x: e + (s + e) / d * (x - xe)  # noqa: E731
    f = _fx.f
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    # The side view: rays grazing the Sun and the Earth, then the shadows behind the Earth.
    for a, b in ((-s, -e), (s, e), (-s, e), (s, -e)):
        out.append(_fx.line(xs, cy + a, xe, cy + b, "fx-hair"))
    out.append(_fx.path(f"M{f(xe)} {f(cy - e)} L{f(end)} {f(cy - penumbra(end))} L{f(end)} {f(cy + penumbra(end))} "
                        f"L{f(xe)} {f(cy + e)} Z", "fx-b-beam"))
    out.append(_fx.path(f"M{f(xe)} {f(cy - e)} L{f(end)} {f(cy - umbra(end))} L{f(end)} {f(cy + umbra(end))} "
                        f"L{f(xe)} {f(cy + e)} Z", "fx-track"))
    out.append(_fx.path(f"M{f(xe)} {f(cy - e)} L{f(end)} {f(cy - umbra(end))} L{f(end)} {f(cy + umbra(end))} "
                        f"L{f(xe)} {f(cy + e)} Z", "fx-b-com"))
    out.append(_fx.circle(xs, cy, s, "fx-disc") + _fx.glyph("sun", xs, cy, s * 0.9, "fx-sun-gl"))
    out.append(_fx.circle(xe, cy, e, "fx-disc"))
    out.append(_fx.line(xm, cy - penumbra(xm) - 18, xm, cy + penumbra(xm) + 18, "fx-sunline"))
    if wide:
        out.append(_fx.text(xs, cy + s + 26, "太陽", "fx-t", "middle"))
        out.append(_fx.text(xe, cy + e + 26, "地球", "fx-t", "middle"))
        out.append(_fx.text(xm, cy - penumbra(xm) - 26, "月亮經過這裡", "fx-t fx-small", "middle"))
        out.append(_fx.text(390, cy - umbra(390) - 8, "半影", "fx-t fx-small fx-key", "end"))
        out.append(_fx.text(xe + e + 4, cy + 5, "本影", "fx-t fx-small fx-key"))
        out.append(_fx.text(sx, 56, "截面：月亮那一處的影子（從地球看過去）", "fx-t fx-small", "middle"))
        out.append(_fx.text(24, H - 20, "示意，不按比例", "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, 56, "側面", "fx-t fx-small"))
    else:
        out.append(_fx.text(xs, cy + s + 22, "太陽", "fx-t", "middle"))
        out.append(_fx.text(xe, cy + e + 22, "地球", "fx-t", "middle"))
        out.append(_fx.text(xm + 32, 26, "月亮經過這裡", "fx-t fx-small", "end"))
        out.append(_fx.text(14, 160, "截面：月亮那一處的影子（從地球看過去）", "fx-t fx-small"))
        out.append(_fx.text(14, H - 16, "示意，不按比例", "fx-t fx-small fx-dim"))
        out.append(_fx.text(14, 26, "側面", "fx-t fx-small"))
    # The cross-section: the penumbra, the umbra inside it, and three paths of the Moon.
    out.append(_fx.circle(sx, sy, pen, "fx-track") + _fx.circle(sx, sy, pen, "fx-b-beam"))
    out.append(_fx.circle(sx, sy, umb, "fx-track") + _fx.circle(sx, sy, umb, "fx-b-com"))
    out.append(_fx.text(sx, sy - umb + 18, "本影", "fx-t fx-small fx-key", "middle"))
    ring = (umb + pen) / 2
    out.append(_fx.text(sx + ring * 0.6, sy + ring * 0.8 + 5, "半影", "fx-t fx-small fx-key", "middle"))
    left, right = (sx - pen - 36, sx + pen + 36) if wide else (126.0, 326.0)
    for kind, offset in tracks:
        ty = sy + offset
        out.append(_fx.line(left, ty, right, ty, "fx-sunline"))
        out.append(_fx.path(f"M{f(right - 8)} {f(ty - 5)} L{f(right)} {f(ty)} L{f(right - 8)} {f(ty + 5)}", "fx-out-arrow"))
        out.append(_fx.circle(sx, ty, moon, "fx-lens"))
        first, second = names[kind]
        if wide:
            out.append(_fx.text(right + 12, ty - 4, first, "fx-t fx-small"))
            out.append(_fx.text(right + 12, ty + 16, second, "fx-t fx-small"))
        else:
            out.append(_fx.text(14, ty - 4, first.rstrip("："), "fx-t fx-small"))
            out.append(_fx.text(14, ty + 14, second, "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)


def _figures(events: dict) -> dict[str, str]:
    """The page's sprite and its three figures, each checked by `_fx.problems`."""
    r = _readings(events)
    timeline_bound = _fx.Bound()
    timeline = _fx.figure(
        fid="fig-timeline", hero=True,
        title="出生前的新月、滿月與出生，排在同一條日期線上",
        caption=(f"<b>{timeline_bound.label('圖 1')}</b>同一張盤，兩種挑法挑到不同的朔望。"
                 f"{timeline_bound.num('2000 年 1 月 1 日')}中午在臺北出生的合成例子：出生前最近的一次是滿月，"
                 "可是這是日生盤，「日生盤看前一次新月」的挑法會越過它，回頭取更早的新月。"
                 "實心圓是新月，空心圓是滿月；日期與時刻是臺北的鐘面時間。"),
        wide=_timeline("fx-wide", "fig-timeline", r, timeline_bound),
        narrow=_timeline("fx-narrow", "fig-timeline", r, timeline_bound),
        notes=[], idle="",
    )
    data = _horizon_data(events)
    horizon_bound = _fx.Bound()
    for _, label in HORIZON_VARIANTS:
        horizon_bound.label(label)
    horizon = _fx.figure(
        fid="fig-horizon",
        title="滿月那一刻與出生那一刻，太陽和月亮在臺北地平線上的高度",
        caption=(f"<b>{horizon_bound.label('圖 2')}</b>{horizon_bound.label('表 1')} 前兩種讀法看的地平線。縱軸是從臺北看出去的高度"
                 "（天體中心的地心真高度，不計大氣折射），地平線以下畫排線。"
                 f"按鈕切換兩個時刻：滿月那一刻（{horizon_bound.num(data['syzygy']['when'])}），月亮在上方、太陽在下方，"
                 f"所以取月亮的度數；出生那一刻（{horizon_bound.num(data['birth']['when'])}），兩個都在上方，"
                 "這個讀法選不出來。"),
        wide=_horizon("fx-wide", "fig-horizon", data, horizon_bound),
        narrow=_horizon("fx-narrow", "fig-horizon", data, horizon_bound),
        notes=[_fx.Note(key, variant, _horizon_sentence(key, variant, data, horizon_bound))
               for variant, _ in HORIZON_VARIANTS for key in ("sun", "moon")],
        idle=HORIZON_IDLE, variants=HORIZON_VARIANTS, switch_label=HORIZON_SWITCH,
    )
    shadow_bound = _fx.Bound()
    shadow = _fx.figure(
        fid="fig-shadow",
        title="地球的本影與半影，以及月亮經過時的三種月食（示意）",
        caption=(f"<b>{shadow_bound.label('圖 3')}</b>本影與半影的示意圖，不按比例。側面：太陽的光被地球擋住，"
                 "地球後方最暗的一塊是本影（交叉排線），外圍較淡的一圈是半影（單線排線）。截面：在月亮經過的那一處，"
                 "從地球看過去的影子截面，虛線是月亮可能走的三條路：只經過半影是半影月食，一部分進入本影是偏食，"
                 f"整個進入本影是全食。{shadow_bound.label('表 2')} 的「前一次月食（含半影月食）」三種都算，"
                 "「前一次本影月食」只算後兩種。"),
        wide=_shadow("fx-wide", "fig-shadow", shadow_bound),
        narrow=_shadow("fx-narrow", "fig-shadow", shadow_bound),
        notes=[], idle="",
    )
    for markup, bound in ((timeline, timeline_bound), (horizon, horizon_bound), (shadow, shadow_bound)):
        found = _fx.problems(markup, bound)
        if found:
            raise RuntimeError("figure check: " + "; ".join(found))
    return {"fx-defs": _fx.defs(("sun", "moon")), "timeline": timeline, "horizon": horizon, "shadow": shadow}


def _readings_table(r: dict) -> str:
    rows = (
        ("最近一次朔望，朔望那一刻在地平線上方的發光體", "《占星四書》卷三第 2 章，Robbins 採用的讀法（本站的預設）",
         f"滿月（出生前 {r['full_days']:.1f} 天）。那一刻從臺北看，月亮高度 {r['moon_alt']}、太陽 {r['sun_alt']}，"
         f"取月亮：{r['full_moon']}"),
        ("最近一次朔望，出生那一刻在地平線上方的發光體", "Robbins 註 9 記下的另一個手抄本讀法（只當資訊列出）",
         f"出生時太陽高度 {r['birth_sun_alt']}、月亮 {r['birth_moon_alt']}，兩個都在上方，這個讀法選不出來"),
        ("日生盤看前一次朔，夜生盤看前一次望", "《占星四書》卷三第 10 章；Lilly 明說越過較近的另一種（具名挑法，不是預設）",
         f"日生盤，取新月（出生前 {r['new_days']:.1f} 天）：{r['new_degree']}"),
    )
    lines = ['      <table class="ar-table">',
             '        <caption id="tab1-cap">表 1　同一張盤，三種讀法。2000 年 1 月 1 日 12:00 臺北出生的合成例子，'
             '數字是本站計算服務實際回答的值。</caption>',
             "        <thead><tr><th>挑法</th><th>出處</th><th>這張盤的結果</th></tr></thead>",
             "        <tbody>"]
    for name, source, result in rows:
        lines.append(f"          <tr><td>{name}</td><td>{source}</td><td>{result}</td></tr>")
    lines += ["        </tbody>", "      </table>"]
    return "\n".join(lines)


def _eclipse_table(events: dict) -> str:
    eclipses, days = events["eclipses"], events["eclipses_at_birth"]["days_before_birth"]
    umbral = eclipses["previous_umbral_lunar"]
    if eclipses["previous_lunar"]["type"] != "penumbral" or umbral["relation_to_previous_lunar"] != (
            "earlier_than_previous_lunar"):
        raise RuntimeError("the penumbral birth's last lunar eclipse is no longer only penumbral")
    rows = []
    for label, key in (("前一次日食", "previous_solar"), ("前一次月食（含半影月食）", "previous_lunar"),
                       ("前一次本影月食（偏食或全食）", "previous_umbral_lunar")):
        entry = eclipses[key]
        who = {"sun": "太陽", "moon": "月亮"}[entry["eclipsed_luminary"]]
        rows.append(f"          <tr><td>{label}</td><td>{ECLIPSE_TYPE_ZH[entry['type']]}</td>"
                    f"<td>{_minute(entry['maximum_local_time'])}</td><td class=\"n\">{days[key]:.0f} 天</td>"
                    f"<td>{who}：{zodiacal(entry['eclipse_longitude'])}</td></tr>")
    return "\n".join([
        '      <table class="ar-table">',
        '        <caption id="tab2-cap">表 2　1999 年 3 月 1 日 12:00 臺北出生的合成例子：出生前最近一次日食與月食。'
        "時間是臺北的鐘面時間（食甚，也就是食最深的那一刻），度數是食甚時受食的那一個發光體的度數。</caption>",
        "        <thead><tr><th>列名</th><th>類型</th><th>臺北時間（食甚）</th><th>出生前</th><th>日月食的度數</th></tr></thead>",
        "        <tbody>", *rows, "        </tbody>", "      </table>",
    ])


@functools.lru_cache(maxsize=1)
def penumbral_share() -> dict:
    """Births every 7 days from 1900-01-01 to 2399-11-30 (0h UT), as the
    product's year range allows: how many have a last lunar eclipse that is
    only penumbral, so that the umbral row names an earlier eclipse; and the
    longest wait between two umbral lunar eclipses."""
    with swiss() as swe:
        start, end = swe.julday(1899, 1, 1, 0.0), swe.julday(2399, 11, 30, 0.0)
        found, jd = [], start
        while jd < end:
            flags, times = swe.lun_eclipse_when(jd, swe.FLG_SWIEPH, 0, False)
            only_penumbral = not flags & (swe.ECL_PARTIAL | swe.ECL_TOTAL)
            found.append((times[0], only_penumbral))
            jd = times[0] + 1
        maxima = [when for when, _ in found]
        births = differ = 0
        birth = swe.julday(1900, 1, 1, 0.0)
        while birth < end:
            births += 1
            differ += found[bisect.bisect_right(maxima, birth) - 1][1]
            birth += 7.0
        umbral = [when for when, only_penumbral in found if not only_penumbral]
        gap, first, last = max((b - a, a, b) for a, b in zip(umbral, umbral[1:]))
        first_ymd, last_ymd = swe.revjul(first)[:2], swe.revjul(last)[:2]
    return {"births": births, "differ": differ, "gap_days": gap, "gap_from": first_ymd, "gap_to": last_ymd}


def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    r = _readings(data["readings"])
    under_way = data["under_way"]
    solar = under_way["eclipses_at_birth"]["in_progress"]["solar"]
    if solar is None or solar["relation"] != "maximum_after_birth":
        raise RuntimeError("the 1999-08-11 birth no longer has a solar eclipse under way")
    previous_solar = under_way["eclipses"]["previous_solar"]
    sect = under_way["prenatal_syzygy_at_birth"]["sect_profile"]
    if sect["state"] != "sect_near_horizon_not_selected":
        raise RuntimeError("the 1999-08-11 birth no longer has the Sun in the near-horizon band")
    sun_at_birth = under_way["prenatal_syzygy_at_birth"]["luminaries_above_horizon_at_birth"]["sun"]
    penumbral = data["penumbral"]
    share = penumbral_share()
    quoted = [
        # The readings birth.
        f"月亮高度 {r['moon_alt']}、太陽 {r['sun_alt']}",
        f"取月亮的度數：{r['full_moon']}",
        f"太陽在對面的{r['full_sun']}",
        f"新月，度數是{r['new_degree']}",
        f"出生那一刻，太陽高度 {r['birth_sun_alt']}、月亮 {r['birth_moon_alt']}",
        f"出生前 {r['full_days']:.1f} 天",
        # The birth during the solar eclipse.
        f"食甚在出生之後 {solar['maximum_minus_birth_minutes']:.0f} 分鐘",
        f"臺北時間 {_minute(solar['eclipse']['maximum_local_time'])}",
        f"{previous_solar['maximum_local_time'][:10]} 那一次{ECLIPSE_TYPE_ZH[previous_solar['type']]}",
        f"出生時太陽的高度是 {_altitude(sun_at_birth)}",
        # The penumbral birth.
        f"出生前 {penumbral['eclipses_at_birth']['days_before_birth']['previous_umbral_lunar']:.0f} 天",
        # The share over the product's years.
        f"{share['births']:,} 個出生時刻裡有 {share['differ']:,} 個",
        f"（{100 * share['differ'] / share['births']:.1f}%）",
        f"{share['gap_from'][0]} 年 {share['gap_from'][1]} 月到 {share['gap_to'][0]} 年 {share['gap_to'][1]} 月"
        f"之間隔了 {share['gap_days']:.0f} 天",
    ]
    blocks = {
        **_figures(data["readings"]),
        "readings": _readings_table(r),
        "eclipses": _eclipse_table(penumbral),
    }
    return blocks, quoted


def elsewhere(fragment: str) -> dict[str, list[str]]:
    """The methods page rounds the same share."""
    share = penumbral_share()
    return {"methods": [f"約 {round(100 * share['differ'] / share['births'])}% 的出生兩種算法得到的「前一次月食」不同"]}
