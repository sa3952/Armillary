"""〈命運點怎麼算〉: figure 1 (one night chart: the arc between the Sun and the
Moon laid off from the Ascendant on both sides, the two points named by the
night formula or the day formula, a switch between the two), table 1 (a day
chart and a night chart, each point as the product answers it) and the numbers
the prose quotes.

Synthetic instants only, 1990-05-15 Taipei: 14:30 (the demonstration chart, a
day chart) and 22:30 (a night chart), whole signs, tropical.  Every position is
the product's answer in process (`derived_methods.lots.by_sect`); the figure
draws the two points where the product puts them and stops if the product's
values stop being the mirror pair the drawing shows.
"""
from __future__ import annotations

from html import escape
import functools

from . import _fx
from ._common import SIGNS, degree_minute, product_charts
from ._demo import DEMO, zodiacal_minutes


FRAGMENT = "blog-lot-of-fortune-formula"
DAY_TIME = (14, 30)
NIGHT_TIME = (22, 30)
OPTIONS = {"house_system": "W", "include_houses": True, "include_lots": True}
# One second of arc: the product's two formulas are exact mirror images, so
# their sums and differences agree to rounding.
TOLERANCE = 1 / 3600


def _request(hour: int, minute: int) -> dict:
    return {**DEMO, "datetime": {**DEMO["datetime"], "hour": hour, "minute": minute}, "options": OPTIONS}


def _read(answer: dict) -> dict:
    bodies = {item["key"]: item["longitude"] for item in answer["astronomical_data"]["bodies"]}
    sect = answer["derived_methods"]["sect"]
    lots = answer["derived_methods"]["lots"]
    return {
        "asc": answer["astronomical_data"]["angles"]["asc"],
        "sun": bodies["sun"],
        "moon": bodies["moon"],
        "sect": sect["sect_status"],
        "altitude": sect["sun_altitude_used"],
        "basis": lots["formula_basis"],
        "fortune": lots["fortune"],
        "spirit": lots["spirit"],
        "houses": lots["house_placement"],
        "by_sect": lots["by_sect"],
    }


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    with product_charts() as post:
        return {"day": _read(post(_request(*DAY_TIME))), "night": _read(post(_request(*NIGHT_TIME)))}


def _close(a: float, b: float) -> bool:
    return abs((a - b + 180) % 360 - 180) < TOLERANCE


def _check(chart: dict, sect: str) -> None:
    """The product's answer is the case the article describes: the sect it
    names, outside the near-horizon band, and the two formulas giving the same
    two points with their names swapped, mirrored about the Ascendant."""
    if chart["sect"] != sect or chart["basis"] != f"{sect}_formula":
        raise RuntimeError(f"the {sect} example is now {chart['sect']} / {chart['basis']}")
    day, night = chart["by_sect"]["day"], chart["by_sect"]["night"]
    if not (_close(day["fortune"], night["spirit"]) and _close(day["spirit"], night["fortune"])):
        raise RuntimeError(f"the {sect} example: the night formula no longer swaps the day formula's points")
    if not _close(day["fortune"] + day["spirit"], 2 * chart["asc"]):
        raise RuntimeError(f"the {sect} example: the two points are no longer mirrored about the Ascendant")
    if not _close(chart["fortune"], chart["by_sect"][sect]["fortune"]):
        raise RuntimeError(f"the {sect} example: the primary Fortune is not the {sect} formula's")


def _arc(chart: dict) -> float:
    """The arc from the Moon forward to the Sun, in zodiacal order."""
    return (chart["sun"] - chart["moon"]) % 360


# --- figure 1 --------------------------------------------------------------------

VARIANTS = (("night", "夜盤公式（本站用在夜盤）"), ("day", "日盤公式（Ptolemy 日夜都用）"))
SWITCH = "切換用哪一套公式替兩個點命名"
IDLE = "用 Tab 鍵移到上升點、太陽、月亮或兩個點上，或用滑鼠指著它，這裡會寫出它的位置與它在這套公式裡的名字。"
# The two points: "fwd" lies the Moon-to-Sun arc after the Ascendant in
# zodiacal order, "back" the same arc before it.
NAMES = {"night": {"fwd": "命運點", "back": "精神點"}, "day": {"fwd": "精神點", "back": "命運點"}}
FORMULAS = {
    "night": ("命運點＝上升點＋太陽−月亮", "精神點＝上升點＋月亮−太陽"),
    "day": ("命運點＝上升點＋月亮−太陽", "精神點＝上升點＋太陽−月亮"),
}


def _wedge(cx: float, cy: float, r0: float, r1: float, a0: float, a1: float) -> str:
    """An annular sector from screen angle a0 to a1 (counter-clockwise)."""
    def at(r: float, a: float) -> str:
        return " ".join(map(_fx.f, _fx.wheel_point(cx, cy, r, a)))
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return (f"M{at(r1, a0)} A{_fx.f(r1)} {_fx.f(r1)} 0 {large} 0 {at(r1, a1)} L{at(r0, a1)} "
            f"A{_fx.f(r0)} {_fx.f(r0)} 0 {large} 1 {at(r0, a0)} Z")


def _arc_path(cx: float, cy: float, r: float, a0: float, a1: float) -> str:
    """An arc of radius r from screen angle a0 counter-clockwise to a1."""
    (x0, y0), (x1, y1) = _fx.wheel_point(cx, cy, r, a0), _fx.wheel_point(cx, cy, r, a1)
    large = 1 if (a1 - a0) % 360 > 180 else 0
    return f"M{_fx.f(x0)} {_fx.f(y0)} A{_fx.f(r)} {_fx.f(r)} 0 {large} 0 {_fx.f(x1)} {_fx.f(y1)}"


def _points(chart: dict) -> dict[str, float]:
    arc = _arc(chart)
    return {"fwd": (chart["asc"] + arc) % 360, "back": (chart["asc"] - arc) % 360}


def _wheel(layout: str, fid: str, chart: dict, text: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    if wide:
        W, H, cx, cy = _fx.WIDE, 540.0, 278.0, 270.0
        r_out, r_ring, r_body, r_arc, r_lot, r_copy, mark = 246.0, 208.0, 176.0, 146.0, 112.0, 84.0, 15.0
        sign_cls, lot_cls = "fx-t fx-small", "fx-t fx-key"
    else:
        W, H, cx, cy = _fx.NARROW, 560.0, 170.0, 168.0
        r_out, r_ring, r_body, r_arc, r_lot, r_copy, mark = 158.0, 134.0, 112.0, 92.0, 70.0, 50.0, 11.0
        sign_cls, lot_cls = "fx-t fx-small", "fx-t fx-small fx-key"
    asc = chart["asc"]
    screen = lambda lon: 180.0 + (lon - asc)  # noqa: E731  the Ascendant at 9 o'clock, zodiacal order counter-clockwise
    pt = lambda lon, r: _fx.wheel_point(cx, cy, r, screen(lon))  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for k in range(12):
        out.append(_fx.path(_wedge(cx, cy, r_ring, r_out, screen(30 * k), screen(30 * k + 30)),
                            "fx-fill-dot" if k % 2 else "fx-track"))
    for r in (r_out, r_ring):
        out.append(_fx.circle(cx, cy, r, "fx-axis"))
    for k in range(12):
        x, y = pt(30 * k + 15, (r_out + r_ring) / 2)
        out.append(_fx.text(x, y + (5 if wide else 4), SIGNS[k], sign_cls + " fx-key", "middle"))
    # The Moon-to-Sun arc, and the same arc laid off from the Ascendant both ways.
    arc = _arc(chart)
    out.append(_fx.path(_arc_path(cx, cy, r_arc, screen(chart["moon"]), screen(chart["sun"])), "fx-curve"))
    out.append(_fx.path(_arc_path(cx, cy, r_copy, 180.0, 180.0 + arc), "fx-dash"))
    out.append(_fx.path(_arc_path(cx, cy, r_copy, 180.0 - arc, 180.0), "fx-dash"))
    # The Ascendant: a rule from the centre out past the wheel at 9 o'clock.
    label = f"上升點，{bound.num(zodiacal_minutes(asc))}"
    out.append(f'<g class="fx-row" data-fx-key="asc" tabindex="0" aria-label="{label}">'
               + _fx.rect(cx - r_out - (34 if wide else 12), cy - 10, r_out + (34 if wide else 12), 20, "fx-hit")
               + _fx.line(cx - r_out - (30 if wide else 10), cy, cx, cy, "fx-wh-axis")
               + _fx.text(cx - r_ring + 6, cy - 9, "上升點", "fx-t fx-small fx-key")
               + "</g>")
    for key in ("sun", "moon"):
        x, y = pt(chart[key], r_body)
        name = "太陽" if key == "sun" else "月亮"
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" '
                   f'aria-label="{name}，{bound.num(zodiacal_minutes(chart[key]))}">'
                   + _fx.circle(x, y, mark + 7, "fx-hit") + _fx.circle(x, y, mark, "fx-mk")
                   + _fx.glyph(key, x, y, mark * 1.25, "fx-mk-gl") + "</g>")
    points = _points(chart)
    for key, lon in points.items():
        x, y = pt(lon, r_lot)
        side = "沿黃道順序" if key == "fwd" else "逆黃道順序"
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" '
                   f'aria-label="從上升點{side}量出的點，{bound.num(zodiacal_minutes(lon))}">'
                   + _fx.circle(x, y, mark + 7, "fx-hit") + _fx.circle(x, y, mark * 0.55, "fx-mk-on") + "</g>")
    # The names change with the formula: one group per variant.
    for variant, _ in VARIANTS:
        body = []
        for key, lon in points.items():
            x, y = pt(lon, r_lot - (24 if wide else 18))
            body.append(_fx.text(x, y + 5, NAMES[variant][key], lot_cls, "middle"))
        if wide:
            lx, ly = 566.0, 70.0
            body.append(_fx.text(lx, ly, text["heading"][variant], "fx-t"))
            for i, line in enumerate(FORMULAS[variant]):
                body.append(_fx.text(lx, ly + 34 + 26 * i, line, "fx-t fx-small"))
        else:
            lx, ly = 18.0, 2 * cy + 26
            body.append(_fx.text(lx, ly, text["heading"][variant], "fx-t"))
            for i, line in enumerate(FORMULAS[variant]):
                body.append(_fx.text(lx, ly + 24 + 20 * i, line, "fx-t fx-small"))
        out.append(_fx.variant_group(variant, VARIANTS[0][0], "".join(body)))
    # The static key.
    rows = (
        ("fx-curve", "實線：月亮到太陽的弧", f"（{text['arc']}）"),
        ("fx-dash", "虛線：同一段弧，", "從上升點往兩邊各量一次"),
    )
    if wide:
        lx, ly = 566.0, 216.0
        for i, (cls, first, second) in enumerate(rows):
            y = ly + 66 * i
            out.append(_fx.line(lx, y - 5, lx + 34, y - 5, cls))
            out.append(_fx.text(lx + 46, y, first, "fx-t fx-small"))
            out.append(_fx.text(lx + 46, y + 24, second, "fx-t fx-small"))
        out.append(_fx.text(lx, ly + 150, "兩套公式算出的是同兩個點，", "fx-t fx-small"))
        out.append(_fx.text(lx, ly + 174, "只是名字對調。", "fx-t fx-small"))
    else:
        ly = 2 * cy + 104
        for i, (cls, first, second) in enumerate(rows):
            y = ly + 50 * i
            out.append(_fx.line(18, y - 5, 48, y - 5, cls))
            out.append(_fx.text(58, y, first, "fx-t fx-small"))
            out.append(_fx.text(58, y + 20, second, "fx-t fx-small"))
        out.append(_fx.text(18, ly + 106, "兩套公式算出的是同兩個點，只是名字對調。", "fx-t fx-small"))
        if ly + 120 > H:
            raise RuntimeError("figure 1 outgrew its phone drawing")
    out.append("</svg>")
    return "".join(out)


def _notes(chart: dict, bound: _fx.Bound) -> list[_fx.Note]:
    points = _points(chart)
    arc = bound.num(degree_minute(_arc(chart)))
    notes = []
    for variant, _ in VARIANTS:
        notes.append(_fx.Note("asc", variant, f"上升點在{bound.num(zodiacal_minutes(chart['asc']))}。兩個點都從這裡量起。"))
        notes.append(_fx.Note("sun", variant, f"太陽在{bound.num(zodiacal_minutes(chart['sun']))}。出生時太陽在地平線下，這是一張夜盤。"))
        notes.append(_fx.Note("moon", variant, f"月亮在{bound.num(zodiacal_minutes(chart['moon']))}。從月亮沿黃道順序量到太陽是 {arc}。"))
        for key, lon in points.items():
            side = "沿黃道順序" if key == "fwd" else "逆黃道順序"
            name = NAMES[variant][key]
            if variant == "night":
                whose = "本站對這張夜盤輸出的" + name
            elif name == "命運點":
                whose = "Ptolemy 的命運點（他日夜都用日盤公式）"
            else:
                whose = "日盤公式的精神點；Ptolemy 沒有給精神點的公式"
            notes.append(_fx.Note(key, variant, f"從上升點{side}量 {arc}，落在{bound.num(zodiacal_minutes(lon))}：{whose}。"))
    return notes


def _table(chart: dict, bound: _fx.Bound) -> str:
    points = _points(chart)
    rows = [
        ("asc", "上升點", zodiacal_minutes(chart["asc"]), "兩個點的起量點", "同左"),
        ("sun", "太陽", zodiacal_minutes(chart["sun"]), "", ""),
        ("moon", "月亮", zodiacal_minutes(chart["moon"]), "", ""),
        ("fwd", "沿黃道順序量出的點", zodiacal_minutes(points["fwd"]), NAMES["night"]["fwd"], NAMES["day"]["fwd"]),
        ("back", "逆黃道順序量出的點", zodiacal_minutes(points["back"]), NAMES["night"]["back"], NAMES["day"]["back"]),
    ]
    body = "".join(
        f'<tr data-fx-key="{key}"><th scope="row">{escape(name)}</th><td class="n">{bound.num(position)}</td>'
        f"<td>{escape(night)}</td><td>{escape(day)}</td></tr>"
        for key, name, position, night, day in rows)
    return _fx.data_table(("點", "位置", "夜盤公式下", "日盤公式下"), body)


def _figure(chart: dict) -> str:
    bound = _fx.Bound()
    for label in ("圖 1", "[1]", "[10]"):
        bound.label(label)
    for _, label in VARIANTS:
        bound.label(label)
    when = bound.num("1990 年 5 月 15 日 22:30")
    arc = bound.num(degree_minute(_arc(chart)))
    text = {
        "heading": {"night": "夜盤公式（Valens、Paulus）", "day": "日盤公式"},
        "arc": f"這張盤是 {arc}",
    }
    points = _points(chart)
    return _fx.figure(
        fid="fig-lot-wheel",
        hero=True,
        title=(f"一張合成的夜盤（{when}，臺北）：上升點在左，黃道依逆時針排列。月亮到太陽的弧是 {arc}，"
               f"從上升點沿黃道順序量一次落在{bound.num(zodiacal_minutes(points['fwd']))}，逆著量一次落在"
               f"{bound.num(zodiacal_minutes(points['back']))}。夜盤公式把前者叫命運點（Lot of Fortune）、後者叫精神點（Lot of Spirit）；"
               "日盤公式把兩個名字對調。"),
        caption=(f"<b>{bound.label('圖 1')}</b>一張合成的夜盤（{when}，臺北，整宮制）。"
                 f"月亮到太陽的弧（實線）從上升點往兩邊各量一次，得到兩個點（虛線的終點）。"
                 "按鈕切換用哪一套公式替它們命名：夜盤公式是本站對夜盤的做法，日盤公式是 Ptolemy 日夜都用的命運點。"
                 "兩套公式算出的位置相同，只有名字對調"
                 '<a class="ar-cite" href="#ref-1">[1]</a><a class="ar-cite" href="#ref-10">[10]</a>。'),
        art=_fx.FigureArt.drawn(
            _wheel, "fig-lot-wheel", chart, text, bound,
            notes=_notes(chart, bound),
            idle=IDLE,
        ),
        controls=_fx.FigureControls(
            variants=VARIANTS,
            switch_label=SWITCH,
        ),
        table=_table(chart, bound),
        bound=bound,
    )


def _house(chart: dict, key: str) -> str:
    return f"第 {chart['houses'][key]} 宮"


def _charts_rows(data: dict) -> str:
    rows = []
    for name, hour, chart in (("日盤例", DAY_TIME, data["day"]), ("夜盤例", NIGHT_TIME, data["night"])):
        ptolemy = chart["by_sect"]["day"]["fortune"]
        rows.append(
            f'          <tr><th scope="row">{name}<br>{hour[0]:02d}:{hour[1]:02d}</th>'
            f'<td>{"日盤" if chart["sect"] == "day" else "夜盤"}</td>'
            f'<td class="n">{zodiacal_minutes(chart["asc"])}</td>'
            f'<td class="n">{zodiacal_minutes(chart["sun"])}</td>'
            f'<td class="n">{zodiacal_minutes(chart["moon"])}</td>'
            f'<td class="n">{zodiacal_minutes(chart["fortune"])}<br>{_house(chart, "fortune")}</td>'
            f'<td class="n">{zodiacal_minutes(chart["spirit"])}<br>{_house(chart, "spirit")}</td>'
            f'<td class="n">{zodiacal_minutes(ptolemy)}</td></tr>')
    return "\n".join(rows)


def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    day, night = data["day"], data["night"]
    _check(day, "day")
    _check(night, "night")
    points = _points(night)
    if not (_close(points["fwd"], night["fortune"]) and _close(points["back"], night["spirit"])):
        raise RuntimeError("figure 1 no longer draws the product's night Fortune and Spirit")
    if not _close(day["by_sect"]["day"]["fortune"], day["fortune"]):
        raise RuntimeError("the day example's Fortune is not Ptolemy's")
    quoted = [
        f"上升點在{zodiacal_minutes(night['asc'])}",
        f"太陽在{zodiacal_minutes(night['sun'])}",
        f"月亮在{zodiacal_minutes(night['moon'])}",
        f"從月亮沿黃道順序量到太陽是 {degree_minute(_arc(night))}",
        f"命運點落在{zodiacal_minutes(night['fortune'])}",
        f"精神點落在{zodiacal_minutes(night['spirit'])}",
        f"Ptolemy 的命運點落在{zodiacal_minutes(night['by_sect']['day']['fortune'])}",
        f"日盤例的命運點在{zodiacal_minutes(day['fortune'])}",
    ]
    return {"fx-defs": _fx.defs(("sun", "moon")), "wheel": _figure(night), "charts": _charts_rows(data)}, quoted
