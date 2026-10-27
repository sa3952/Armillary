"""〈三分性是什麼〉: figure 1 (the zodiac wheel grouped by element, with each element's rulers under a switch between
the three schemes) and figure 2 (four elements against the three schemes, the water row marked where they disagree).

Every ruler drawn is read from backend/app/core/dignity_tables.py; the build refuses tables whose shape it does not know.
"""
from __future__ import annotations

from . import _fx
from ._common import PLANETS, SIGNS, backend_on_path

FRAGMENT = "blog-triplicity-rulers"
SIGN_KEYS = ("aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius",
             "capricorn", "aquarius", "pisces")
ELEMENT_NAMES = {"fire": "火象", "earth": "土象", "air": "風象", "water": "水象"}
ELEMENT_SHORT = {"fire": "火", "earth": "土", "air": "風", "water": "水"}
# The element's triangle: fire solid, earth dashed, air hairline, water heavy.
TRIANGLE = {"fire": "fx-wh-line", "earth": "fx-dash", "air": "fx-hair", "water": "fx-axis"}
SCHEMES = (("dorotheus", "Dorotheus"), ("ptolemy", "Ptolemy"), ("lilly", "Lilly 1647"))
SECTS = (("day", "日盤"), ("night", "夜盤"))
VARIANTS = tuple((f"{scheme}-{sect}", f"{label}・{sect_label}") for scheme, label in SCHEMES for sect, sect_label in SECTS)
PLANET_KEYS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")

def _tables():
    with backend_on_path():
        from app.core.dignity_tables import DOROTHEAN, ELEMENTS, LILLY_COMPACT, PTOLEMY_TEXTUAL
    if tuple(ELEMENTS) != tuple(ELEMENT_NAMES):
        raise RuntimeError(f"the elements are no longer {tuple(ELEMENT_NAMES)}: {ELEMENTS}")
    return DOROTHEAN, PTOLEMY_TEXTUAL, LILLY_COMPACT

def rulers(scheme: str, sect: str, element: str) -> list[tuple[str, str, bool]]:
    dorothean, ptolemy, lilly = _tables()
    if scheme == "dorotheus":
        first, second, third = dorothean[element]
        lead, other = (first, second) if sect == "day" else (second, first)
        return [(lead, "當令", True), (other, "另一位", False), (third, "參與", False)]
    if scheme == "ptolemy":
        rule = ptolemy[element]
        if rule["principal"] is not None:
            co = rule[f"secondary_{sect}"]
            if tuple(rule[sect]) != (rule["principal"], co):
                raise RuntimeError(f"Ptolemy {element} {sect}: {rule[sect]} is not principal and co-ruler")
            return [(rule["principal"], "主", True), (co, "共主", True)]
        (lead,) = rule[sect]
        return [(lead, "居首", True), (rule[f"secondary_{sect}"], "次要共主", False)]
    (lead,) = lilly[element][sect]
    return [(lead, "當令", True)]

def _signs(element_index: int) -> list[int]:
    return [element_index + 4 * k for k in range(3)]

def _polar(cx: float, cy: float):
    return lambda longitude, r: _fx.wheel_point(cx, cy, r, 180 + longitude)

def _wheel(out: list[str], cx: float, cy: float, r_out: float, r_in: float, wide: bool) -> None:
    at = _polar(cx, cy)
    f = _fx.f
    out.append(_fx.circle(cx, cy, r_out, "fx-wh-ring") + _fx.circle(cx, cy, r_in, "fx-lens"))
    for sign in range(12):
        (sx, sy), (ex, ey) = at(30.0 * sign, r_in), at(30.0 * sign, r_out)
        out.append(_fx.line(sx, sy, ex, ey, "fx-axis"))
        gx, gy = at(30.0 * sign + 15, (r_in + r_out) / 2 + (8 if wide else 6))
        out.append(_fx.glyph(SIGN_KEYS[sign], gx, gy, 20 if wide else 15, "fx-mk-gl"))
        tx, ty = at(30.0 * sign + 15, (r_in + r_out) / 2 - (13 if wide else 10))
        out.append(_fx.text(tx, ty + 5, ELEMENT_SHORT[tuple(ELEMENT_NAMES)[sign % 4]], "fx-t fx-small fx-dim", "middle"))
    for index, element in enumerate(ELEMENT_NAMES):
        points = [at(30.0 * s + 15, r_in - 6) for s in _signs(index)]
        d = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in points) + " Z"
        out.append(_fx.path(d, TRIANGLE[element]))

def _ruler_row(out: list[str], items, x: float, y: float, step: float, r: float, wide: bool) -> None:
    for i, (planet, role, on) in enumerate(items):
        mx = x + i * step
        out.append(_fx.circle(mx, y, r, "fx-mk-on" if on else "fx-mk")
                   + _fx.glyph(planet, mx, y, r * 1.25, "fx-mk-gl-on" if on else "fx-mk-gl"))
        out.append(_fx.text(mx, y + r + (20 if wide else 16), PLANETS[planet], "fx-t fx-small", "middle"))
        out.append(_fx.text(mx, y + r + (38 if wide else 31), role, "fx-t fx-small fx-dim", "middle"))

def _drawing(layout: str, fid: str) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, cx, cy, r_out, r_in = 470, 236.0, 236.0, 206.0, 160.0
        x_label, x_mark, row0, row_h, step, r = 486.0, 650.0, 82.0, 96.0, 74.0, 17.0
    else:
        H, cx, cy, r_out, r_in = 646, 170.0, 158.0, 146.0, 112.0
        x_label, x_mark, row0, row_h, step, r = 16.0, 160.0, 368.0, 80.0, 62.0, 14.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    _wheel(out, cx, cy, r_out, r_in, wide)
    for index, element in enumerate(ELEMENT_NAMES):
        y = row0 + index * row_h
        out.append(_fx.text(x_label, y - 2, ELEMENT_NAMES[element], "fx-t"))
        out.append(_fx.text(x_label, y + 20, "、".join(SIGNS[s] for s in _signs(index)), "fx-t fx-small fx-dim"))
        out.append(_fx.path(f"M{_fx.f(x_label)} {_fx.f(y + 34)} L{_fx.f(x_label + 60)} {_fx.f(y + 34)}",
                            TRIANGLE[element]))
    for key, label in VARIANTS:
        scheme, sect = key.split("-")
        body = [_fx.text(x_label, row0 - (46 if wide else 40), label, "fx-t fx-key")]
        for index, element in enumerate(ELEMENT_NAMES):
            _ruler_row(body, rulers(scheme, sect, element), x_mark, row0 + index * row_h - 6, step, r, wide)
        out.append(_fx.variant_group(key, VARIANTS[0][0], "".join(body)))
    out.append("</svg>")
    return "".join(out)

def _grid(layout: str, fid: str) -> str:
    """Figure 2: four elements down, three schemes across; the water row on a dotted ground."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, x0, col_w, top, row_h = 330, 150.0, 230.0, 70.0, 62.0
    else:
        H, x0, col_w, top, row_h = 330, 60.0, 92.0, 70.0, 62.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for c, (_, label) in enumerate(SCHEMES):
        out.append(_fx.text(x0 + c * col_w + col_w / 2, top - 22, label, "fx-t" if wide else "fx-t fx-small", "middle"))
    for index, element in enumerate(ELEMENT_NAMES):
        y = top + index * row_h
        if element == "water":
            out.append(_fx.rect(x0, y, col_w * 3, row_h, "fx-fill-dot"))
        out.append(_fx.text(18 if wide else 14, y + row_h / 2 + 6, ELEMENT_NAMES[element] if wide else ELEMENT_SHORT[element],
                            "fx-t"))
        for c, (scheme, _) in enumerate(SCHEMES):
            x = x0 + c * col_w
            out.append(_fx.rect(x, y, col_w, row_h, "fx-lens"))
            for s, (sect, sect_label) in enumerate(SECTS):
                on = [p for p, _, lit in rulers(scheme, sect, element) if lit]
                names = "＋".join(PLANETS[p] for p in on)
                line = f"{sect_label[0]}　{names}" if wide else f"{sect_label[0]} {names}"
                out.append(_fx.text(x + 12 if wide else x + 6, y + 26 + s * 24, line, "fx-t fx-small"))
    note_y = top + 4 * row_h + 30
    out.append(_fx.text(18 if wide else 14, note_y, "點狀底：三套給的當令主星不同的一組" if wide else "點狀底：三套不同的一組",
                        "fx-t fx-small fx-dim"))
    out.append("</svg>")
    return "".join(out)

def _figure_table(bound: _fx.Bound) -> str:
    rows = []
    for index, element in enumerate(ELEMENT_NAMES):
        signs = "、".join(f"{SIGNS[s]} {bound.num(f'{30 * s}°')}" for s in _signs(index))
        rows.append(f'<tr><th scope="row">{ELEMENT_NAMES[element]}</th><td>{signs}</td></tr>')
    return _fx.data_table(("元素", "三個星座與各自的起點黃經（相隔 120°）"), rows)

def build() -> tuple[dict[str, str], list[str]]:
    bound = _fx.Bound()
    bound.scale("120°")
    bound.label("Lilly 1647")
    wheel = _fx.figure(
        fid="fig-triplicity-wheel",
        hero=True,
        title="十二星座依元素分成四組，各組的三分性主星依三套說法與日夜盤",
        caption=(f"<b>{bound.label('圖 1')}</b>十二星座依火、土、風、水分成四組，同一組的三個星座相隔 120 度，"
                 "連起來是一個三角形。輪盤旁是每一組的三分性主星：塗黑的圓是當下當令的主星，空心的圓是同一套裡的其他主星。"
                 "按鈕切換三套說法與日盤、夜盤；沒有開啟指令碼時顯示 Dorotheus 的日盤。"),
        art=_fx.FigureArt.drawn(_drawing, "fig-triplicity-wheel"),
        controls=_fx.FigureControls(variants=VARIANTS, switch_label="三套說法與日夜盤"),
        table=_figure_table(bound),
        bound=bound,
    )
    grid = _fx.figure(
        fid="fig-triplicity-grid",
        title="四個元素、三套說法：日盤與夜盤當令的主星",
        caption=(f"<b>{bound.label('圖 2')}</b>四個元素、三套說法，每格寫日盤（日）與夜盤（夜）當令的主星；"
                 "Ptolemy 水象的「＋」是主星與共主。火、土、風三組三套相同，只有水象三套各不相同（點狀底）。"),
        art=_fx.FigureArt.drawn(_grid, "fig-triplicity-grid"),
        bound=bound,
    )
    _check_water()
    return {"fx-defs": _fx.defs(PLANET_KEYS + SIGN_KEYS), "triplicity-wheel": wheel, "triplicity-grid": grid}, ["相隔 120 度"]

def _check_water() -> None:
    differ = []
    for element in ELEMENT_NAMES:
        seen = {tuple(tuple(p for p, _, on in rulers(s, sect, element) if on) for sect, _ in SECTS) for s, _ in SCHEMES}
        if len(seen) > 1:
            differ.append(element)
    if differ != ["water"]:
        raise RuntimeError(f"the schemes now differ in {differ}, not only in water")
