"""〈焦傷、在光束下、日輪內：離太陽多近才算〉: figure 1 and tables 1-4 of the article, with the numbers the prose quotes.

The limits are the backend's profile table (app.core.solar_phase).  The instant is synthetic, 2017-03-25 18:00 Taipei
(10:00 UT, Venus at inferior conjunction far north of the ecliptic, Mercury just past superior conjunction), and the
bands and crossings are the product's own answer to it.  Its longitude differences, Venus's latitude and the Mercury
crossing instants are checked against Swiss Ephemeris read directly, without the product's code.
"""
from __future__ import annotations

from html import escape

from . import _fx
from ._common import PLANETS, TAIPEI, calc_ut, degree_minute, product_charts, swiss
from .page_methods import solar_limit_text, solar_phase_limit_rows

FRAGMENT = "blog-combustion-under-beams-cazimi"
MOMENT = {"year": 2017, "month": 3, "day": 25, "hour": 18, "minute": 0, "second": 0}
REQUEST = {"datetime": MOMENT, "location": {"latitude": TAIPEI[0], "longitude": TAIPEI[1]},
    "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"}, "options": {"include_solar_phase": True}}
# (figure variant, the product's solar-phase profile, label)
VARIANTS = (("lilly", "lilly_1647_p113_v1", "Lilly 1647 p.113"), ("hellenistic", "hellenistic_15_v1", "希臘化"),
    ("biruni", "biruni_wright_v1", "al-Bīrūnī"))
NAMES = {key: name for key, name in PLANETS.items() if key != "sun"}
BAND_NAMES = {"cazimi": "日輪內", "combust": "焦傷", "under_beams": "在光束下", "clear": "離開光束",
    "accompanying_high_latitude": "伴隨太陽"}
DIRECTIONS = {"emerging": "升出光束", "sinking": "隱入光束"}
LIMITED = (("cazimi", "日輪內"), ("combust", "焦傷"), ("under_beams", "在光束下"))
# The original each band name carries where it first appears (「焦傷（combust）」); figure 1 sits above the lead, so its
# labels, first sentences and caption carry them.
ORIGINAL = {"cazimi": "cazimi", "combust": "combust", "under_beams": "under the beams"}
# Direct Swiss and the product agree to about a thousandth of an arcsecond; a crossing instant is a root found to 1e-6
# day, a few hundredths of an arcsecond of Mercury's motion against the Sun.
SAME_ARCSEC = 0.05
CROSSING_ARCSEC = 0.5

def _dm(degrees: float, signed: bool = False) -> str:
    """「8°18′」, rounded to the whole arcminute; signed: 「+16°34′」「−35°00′」."""
    text = degree_minute(abs(degrees))
    return (("−" if degrees < 0 else "+") + text) if signed else text

def _offset(days: float) -> str:
    side = "之前" if days < 0 else "之後"
    span = f"{abs(days) * 24:.1f} 小時" if abs(days) < 1 else f"{abs(days):.1f} 天"
    return f"{side} {span}"

def _summary_cell(table: dict, band: str) -> str:
    """One tradition's limit for one band over every body and side: the limit, or the range it spans."""
    leaves = []
    for sides in table.values():
        for per_band in sides.values():
            limit = per_band[band]
            if limit is None:
                continue
            leaves += [limit[m] for m in ("direct", "retrograde")] if "direct" in limit else [limit]
    if not leaves:
        return "（沒有這一帶）"
    texts = {solar_limit_text(limit) for limit in leaves}
    if len(texts) == 1:
        return texts.pop()
    low, high = min(limit["degrees"] for limit in leaves), max(limit["degrees"] for limit in leaves)
    return f"{low:g}°–{high:g}°（依天體而不同）"

def _summary_rows(tables: dict) -> str:
    rows = []
    for _, profile, name in VARIANTS:
        cells = "".join(f"<td>{escape(_summary_cell(tables[profile], band))}</td>" for band, _ in LIMITED)
        rows.append(f'          <tr><th scope="row">{escape(name)}</th>{cells}</tr>')
    return "\n".join(rows)

# The two figures draw the instant of tables 3 and 4 under the three traditions; the buttons switch the tradition.
# Every edge and printed verdict is the backend's; `_drawn_band` re-reads the verdict from the drawn edges and must
# agree.
VARIANT_LABELS = tuple((variant, label) for variant, _, label in VARIANTS)
SIDE_SHORT = {"morning": "西側（晨星）", "evening": "東側（昏星）"}
# The result page's wording (view-model.js SOLAR_PHASE_SIDE_ZH and SOLAR_PHASE_MOTION_ZH).
SIDE_LONG = {"morning": "西側，比太陽早升起（晨星）", "evening": "東側，比太陽晚落下（昏星）"}
MOTION_ZH = {"approaching_sun": "正在靠近太陽", "separating_from_sun": "正在離開太陽", "no_relative_motion": "與太陽沒有相對移動"}
BAND_CLASS = {"cazimi": "fx-b-caz", "combust": "fx-b-com", "under_beams": "fx-b-beam"}
RULER_RANGE = 24.0
RAY_RANGE = 30.0
RAY_LATITUDE = 10.0
# asinh scale of the ray figure: degrees near the Sun are drawn wider.
RAY_SOFTNESS = 1.0
SWITCH_LABEL = "切換三套界線"
IDLE = "用 Tab 鍵移到一顆星上，或用滑鼠指著它，這裡會寫出它的黃經差與判定。"

def _tick_anchor(t: float, end: float) -> str:
    return "start" if t == -end else "end" if t == end else "middle"

def _resolved(limit: dict | None, motion: str) -> float | None:
    if limit is None:
        return None
    return (limit[motion] if "direct" in limit else limit)["degrees"]

def _edges(tables: dict, profile: str, key: str, side: str, motion: str) -> dict[str, float | None]:
    per_band = tables[profile][key][side]
    return {band: _resolved(per_band[band], motion) for band, _ in LIMITED}

def _drawn_band(edges: dict[str, float | None], difference: float, latitude: float,
                exception: float | None, key: str) -> str:
    """The band a reader sees: the innermost drawn strip the mark sits in.  Whether an edge belongs to the band never
    decides at this instant (checked: no mark within 1″ of an edge)."""
    distance = abs(difference)
    band = "clear"
    for name in ("under_beams", "combust", "cazimi"):
        edge = edges[name]
        if edge is not None and distance <= edge:
            band = name
    if exception is not None and key == "venus" and latitude > exception and band in ("cazimi", "combust"):
        band = "accompanying_high_latitude"
    return band

def _strips(edges_by_side: dict[str, dict], x, top: float, height: float, xmin: float, xmax: float) -> str:
    out = []
    for band in ("under_beams", "combust", "cazimi"):
        for side, sign in (("morning", -1), ("evening", 1)):
            edge = edges_by_side[side][band]
            if edge is None:
                continue
            a, b = sorted((x(0.0), x(sign * edge)))
            a, b = max(a, xmin), min(b, xmax)
            out.append(_fx.rect(a, top, b - a, height, BAND_CLASS[band]))
            if xmin <= x(sign * edge) <= xmax and band != "cazimi":
                out.append(_fx.line(x(sign * edge), top, x(sign * edge), top + height, "fx-b-edge"))
    return "".join(out)

def _mark(key: str, cx: float, cy: float, r: float, off_scale: int = 0) -> str:
    """A planet: a paper disc with its glyph; off the scale, dashed, with a chevron pointing out of the figure."""
    out = _fx.circle(cx, cy, r, "fx-mk") + _fx.glyph(key, cx, cy, r * 1.25, "fx-mk-gl")
    if off_scale:
        edge = cx + off_scale * (r + 9)
        out = (f'<g class="fx-off-scale">{out}'
               + _fx.path(f"M{_fx.f(edge - off_scale * 6)} {_fx.f(cy - 6)} L{_fx.f(edge)} {_fx.f(cy)} "
                          f"L{_fx.f(edge - off_scale * 6)} {_fx.f(cy + 6)}", "fx-out-arrow") + "</g>")
    return out

def _sentence(row: dict, profile_label: str, band: str, bound: _fx.Bound, latitude: bool = False) -> str:
    text = (f"{row['name']}：{SIDE_LONG[row['side']]}，黃經差 {bound.num(_dm(row['longitude_difference_degrees']))}，"
            f"{MOTION_ZH[row['relative_motion']]}。")
    if latitude:
        lat = row["ecliptic_latitude_degrees"]
        text += (f"黃緯{'北' if lat >= 0 else '南'} {bound.num(_dm(lat))}（只顯示，不判定），"
                 f"天空中離太陽 {bound.num(_dm(row['angular_separation_degrees']))}。")
    # 「照 Lilly 1647 p.113」but 「照希臘化」: a space only before a Latin name.
    text += f"照{' ' if profile_label[0].isascii() else ''}{profile_label}：{BAND_NAMES[band]}。"
    if band == "accompanying_high_latitude":
        text += (f"al-Bīrūnī §{bound.num('483')} 說金星在會合時北黃緯超過 {bound.num('7')}°，" "不稱日輪內，也不稱焦傷，只稱「伴隨太陽」（muqārina）。")
    return text

def _band_labels(evening: dict[str, float | None], x, cx: float, limit: float, top: float, wide: bool) -> str:
    """The band names over figure 1, each with its original on the line below: 日輪內 left of the Sun's line (its strip
    is a hairline), the others from their band's inner edge, pushed right so none overlap."""
    size, pad = (15.0, 6.0) if wide else (12.0, 3.0)
    zh_y, en_y = top - (34 if wide else 28), top - (12 if wide else 10)
    cls = "fx-t fx-small fx-key"
    out = []
    if evening["cazimi"]:
        out.append(_fx.text(cx - 2 * pad, zh_y, "日輪內 ›", cls, "end")
                   + _fx.text(cx - 2 * pad, en_y, ORIGINAL["cazimi"], cls, "end"))
    end = cx
    inner = evening["cazimi"] or 0.0
    for band, name in LIMITED[1:]:
        edge = evening[band]
        if edge is None:
            continue
        start = max(x(inner) + pad, end + 2 * pad)
        end = start + max(_fx.text_width(name, size), _fx.text_width(ORIGINAL[band], size))
        if end > limit:
            raise RuntimeError(f"figure 1: the {band} label runs past the plate")
        out.append(_fx.text(start, zh_y, name, cls) + _fx.text(start, en_y, ORIGINAL[band], cls))
        inner = edge
    return "".join(out)

def _ruler(layout: str, fid: str, rows: list[dict], verdicts: dict, edges: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (200.0, 740.0) if wide else (14.0, 326.0)
    top, rh, th = (122.0, 46.0, 22.0) if wide else (98.0, 58.0, 20.0)
    cx = (x0 + x1) / 2
    k = (x1 - x0) / 2 / RULER_RANGE
    x = lambda d: cx + d * k  # noqa: E731
    bottom = top + len(rows) * rh
    H = bottom + (70 if wide else 64)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    head = 34 if wide else 26
    out.append(_fx.text(x0, head, "← " + SIDE_SHORT["morning"], "fx-t fx-rub"))
    out.append(_fx.text(x1, head, SIDE_SHORT["evening"] + " →", "fx-t fx-rub", "end"))
    out.append(_fx.glyph("sun", cx, head + (22 if wide else 18), 18 if wide else 15, "fx-sun-gl"))
    out += [_fx.variant_group(variant, VARIANTS[0][0], _band_labels(edges[variant][rows[0]["key"]]["evening"],
                                                                     x, cx, W - 12, top, wide))
            for variant, *_ in VARIANTS]
    out.append(_fx.line(cx, top - 4, cx, bottom + 4, "fx-sunline"))
    for i, row in enumerate(rows):
        y = top + i * rh
        key, diff = row["key"], row["longitude_difference_degrees"]
        track = y + (rh - th) / 2 if wide else y + 26
        my = track + th / 2
        value = bound.num(_dm(diff))
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" '
                   f'aria-label="{row["name"]}，{SIDE_SHORT[row["side"]]}，黃經差 {value}">')
        out.append(_fx.rect(8 if wide else 8, y + 1, W - 16, rh - 2, "fx-hit"))
        out.append(_fx.rect(x0, track, x1 - x0, th, "fx-track"))
        for variant, *_ in VARIANTS:
            strips = _strips(edges[variant][key], x, track, th, x0, x1)
            verdict = BAND_NAMES[verdicts[variant][key]]
            label = (_fx.text(x1 + 14, my + 6, verdict, "fx-t fx-small fx-verdict") if wide
                     else _fx.text(x1, y + 16, verdict, "fx-t fx-small fx-verdict", "end"))
            out.append(_fx.variant_group(variant, VARIANTS[0][0], strips + label))
        out.append(_fx.line(cx, track - 3, cx, track + th + 3, "fx-sunline"))
        r = 10 if wide else 9
        if abs(diff) <= RULER_RANGE:
            out.append(_mark(key, x(diff), my, r))
        else:
            sign = 1 if diff > 0 else -1
            out.append(_mark(key, (x1 if sign > 0 else x0) - sign * (r + 9), my, r, sign))
        if wide:
            out.append(_fx.text(24, my + 6, row["name"], "fx-t fx-name"))
            out.append(_fx.text(x0 - 14, my + 6, value, "fx-t fx-num", "end"))
        else:
            out.append(_fx.text(x0, y + 16, row["name"], "fx-t fx-name"))
            out.append(_fx.text(x0 + 40, y + 16, value + ("（圖外）" if abs(diff) > RULER_RANGE else ""), "fx-t fx-num"))
        out.append("</g>")
    axis = bottom + 6
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    step = 4 if wide else 8
    for t in range(-int(RULER_RANGE), int(RULER_RANGE) + 1, step):
        out.append(_fx.line(x(t), axis, x(t), axis + 5, "fx-axis"))
        out.append(_fx.text(x(t), axis + 22, bound.scale(f"{abs(t)}°"), "fx-t fx-small fx-num", _tick_anchor(t, RULER_RANGE)))
    out.append(_fx.text(cx, axis + (46 if wide else 44), "與太陽的黃經差（度，等比例）", "fx-t fx-small", "middle"))
    out.append("</svg>")
    if axis + 46 > H:
        raise RuntimeError("figure 1 outgrew its drawing")
    return "".join(out)

def _ray_x(cx: float, half: float):
    import math
    full = math.asinh(RAY_RANGE / RAY_SOFTNESS)
    return lambda d: cx + math.copysign(math.asinh(abs(d) / RAY_SOFTNESS) / full * half, d)

def _rays(layout: str, fid: str, rows: list[dict], verdicts: dict, edges: dict, exceptions: dict,
          semidiameter: float, bound: _fx.Bound) -> str:
    """Figure 2, one layout: the Sun at the centre, ecliptic longitude difference across (asinh), latitude up, the
    bands as upright strips; and the Sun ±1° at true scale, the disc and the cazimi strip."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        x0, x1, top, per_lat = 84.0, 600.0, 92.0, 15.0
    else:
        x0, x1, top, per_lat = 48.0, 326.0, 84.0, 10.0
    cx = (x0 + x1) / 2
    half = (x1 - x0) / 2
    x = _ray_x(cx, half)
    cy = top + RAY_LATITUDE * per_lat
    bottom = top + 2 * RAY_LATITUDE * per_lat
    y = lambda lat: cy - lat * per_lat  # noqa: E731
    venus = next(row for row in rows if row["key"] == "venus")
    if wide:
        ix, iy, iw, ih = 640.0, top, 216.0, 216.0
        H = bottom + 72
    else:
        ix, iw, ih = 14.0, 312.0, 156.0
        iy = bottom + 112
        H = iy + ih + 34
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    head = 32 if wide else 26
    out.append(_fx.text(x0, head, "← " + SIDE_SHORT["morning"], "fx-t fx-rub"))
    out.append(_fx.text(x1, head, SIDE_SHORT["evening"] + " →", "fx-t fx-rub", "end"))
    out.append(_fx.text(x0 - 8, top - 10, "黃緯（只顯示，不判定）", "fx-t fx-small fx-dim"))
    out.append(f'<clipPath id="{fid}-{layout}-plot">{_fx.rect(x0, top, x1 - x0, bottom - top, "")}</clipPath>')
    plot = [f'<g clip-path="url(#{fid}-{layout}-plot)">', _fx.rect(x0, top, x1 - x0, bottom - top, "fx-track")]
    for variant, *_ in VARIANTS:
        e = edges[variant]["venus"]
        body = _strips(e, x, top, bottom - top, x0, x1)
        limit = exceptions[variant]
        if limit is not None:
            com = max(e[side]["combust"] or 0.0 for side in ("morning", "evening"))
            body += _fx.rect(x(-com), top, x(com) - x(-com), y(limit) - top, "fx-exc")
            body += _fx.line(x(-com), y(limit), x(com), y(limit), "fx-exc-edge")
        plot.append(_fx.variant_group(variant, VARIANTS[0][0], body))
    plot.append(_fx.line(x0, cy, x1, cy, "fx-hair"))
    plot.append("</g>")
    out += plot
    out.append(_fx.rect(x0, top, x1 - x0, bottom - top, "fx-inset-frame"))
    for variant, *_ in VARIANTS:
        limit = exceptions[variant]
        if limit is not None:
            # inside the band above the line, either side of the mark at the centre
            ly = y(limit) - (10 if wide else 6)
            gap = 26 if wide else 20
            out.append(_fx.variant_group(variant, VARIANTS[0][0], (
                _fx.text(cx - gap, ly, f"北黃緯 {bound.num(f'{limit:g}')}° 以上", "fx-t fx-small fx-key", "end")
                + _fx.text(cx + gap, ly, "伴隨太陽", "fx-t fx-small fx-key"))))
    for lat in (-9, -6, -3, 3, 6, 9):
        out.append(_fx.line(x0 - 5, y(lat), x0, y(lat), "fx-axis"))
        out.append(_fx.text(x0 - 8, y(lat) + 5, bound.scale(f"{'北' if lat > 0 else '南'}{abs(lat)}°"),
                            "fx-t fx-small fx-num", "end"))
    out.append(_fx.text(x0 - 8, cy + 5, "黃道", "fx-t fx-small", "end"))
    out.append(_fx.glyph("sun", cx, cy, 16 if wide else 13, "fx-sun-gl"))
    ticks = (1, 3, 6, 15, 30) if wide else (1, 3, 6, 30)
    out.append(_fx.line(x0, bottom, x1, bottom, "fx-axis"))
    for t in (0,) + ticks + tuple(-t for t in ticks):
        out.append(_fx.line(x(t), bottom, x(t), bottom + 5, "fx-axis"))
        out.append(_fx.text(x(t), bottom + 22, bound.scale(f"{abs(t)}°"), "fx-t fx-small fx-num", _tick_anchor(t, RAY_RANGE)))
    out.append(_fx.text(cx, bottom + (46 if wide else 44), "與太陽的黃經差（越靠近太陽，刻度放得越大）", "fx-t fx-small", "middle"))
    for row in rows:
        diff, lat = row["longitude_difference_degrees"], row["ecliptic_latitude_degrees"]
        if abs(diff) > RAY_RANGE or abs(lat) > RAY_LATITUDE:
            continue
        out.append(f'<g class="fx-row" data-fx-key="{row["key"]}" tabindex="0" '
                   f'aria-label="{row["name"]}，黃經差 {bound.num(_dm(diff))}，黃緯{"北" if lat >= 0 else "南"} '
                   f'{bound.num(_dm(lat))}">')
        out.append(_fx.circle(x(diff), y(lat), 18, "fx-hit"))
        out.append(_mark(row["key"], x(diff), y(lat), 10 if wide else 9))
        out.append("</g>")
    # the enlargement: the Sun ±1° in longitude, the same scale up and down
    scale = iw / 2.0
    icx, icy = ix + iw / 2, iy + ih / 2
    lens = 1.0
    out.append(_fx.rect(x(-lens), y(lens), x(lens) - x(-lens), y(-lens) - y(lens), "fx-lens"))
    if wide:
        out.append(_fx.line(x(lens), y(lens), ix, iy, "fx-leader") + _fx.line(x(lens), y(-lens), ix, iy + ih, "fx-leader"))
    out.append(f'<clipPath id="{fid}-{layout}-inset">{_fx.rect(ix, iy, iw, ih, "")}</clipPath>')
    inset = [f'<g clip-path="url(#{fid}-{layout}-inset)">', _fx.rect(ix, iy, iw, ih, "fx-inset-bg")]
    for variant, *_ in VARIANTS:
        e = edges[variant]["venus"]
        body = ""
        caz = {side: e[side]["cazimi"] for side in ("morning", "evening")}
        if caz["morning"] is None:
            body += _fx.text(icx, iy + ih - 10, "這一套沒有日輪內", "fx-t fx-small fx-inset-t", "middle")
        else:
            body += _fx.rect(icx - caz["morning"] * scale, iy, (caz["morning"] + caz["evening"]) * scale, ih,
                             "fx-b-caz-in")
        inset.append(_fx.variant_group(variant, VARIANTS[0][0], body))
    inset.append(_fx.line(ix, icy, ix + iw, icy, "fx-hair"))
    inset.append(_fx.circle(icx, icy, semidiameter * scale, "fx-disc"))
    vx = icx + venus["longitude_difference_degrees"] * scale
    inset.append(f'<g class="fx-row-echo" data-fx-key="venus">' + _fx.path(f"M{_fx.f(vx)} {_fx.f(iy + 6)} l-6 10 h12 z",
        "fx-arrow") + _fx.text(vx, iy + 34, f"金星在北 {bound.num(_dm(venus['ecliptic_latitude_degrees']))}",
        "fx-t fx-small fx-inset-t", "middle") + "</g>")
    inset.append("</g>")
    out += inset
    out.append(_fx.rect(ix, iy, iw, ih, "fx-inset-frame"))
    note_y = iy + ih + (24 if wide else 22)
    disc = bound.num(f"{semidiameter * 60:.0f}′")
    if wide:
        out.append(_fx.text(icx, note_y, "放大：太陽前後 1°", "fx-t fx-small", "middle"))
        out.append(_fx.text(icx, note_y + 22, f"橫直同比例；圓是日面，半徑約 {disc}", "fx-t fx-small", "middle"))
    else:
        out.append(_fx.text(ix, iy - 28, "放大：太陽前後 1°，橫直同比例", "fx-t fx-small"))
        out.append(_fx.text(ix, iy - 10, f"圓是日面，半徑約 {disc}", "fx-t fx-small"))
        for t in (-1, 0, 1):
            out.append(_fx.text(icx + t * scale - (8 if t > 0 else -8 if t < 0 else 0), iy + ih + 18,
                                bound.scale(f"{abs(t)}°"), "fx-t fx-small fx-num", "middle"))
    out.append("</svg>")
    if (note_y + 22 if wide else iy + ih + 18) > H:
        raise RuntimeError("figure 2 outgrew its drawing")
    return "".join(out)

def _first_glossed(notes: list[_fx.Note]) -> list[_fx.Note]:
    out = list(notes)
    for band, name in LIMITED:
        for i, note in enumerate(out):
            if name in note.text:
                glossed = note.text.replace(name, f"{name}（{ORIGINAL[band]}）", 1)
                out[i] = _fx.Note(note.key, note.variant, glossed, note.step)
                break
    return out

def _ruler_table(rows: list[dict], verdicts: dict, bound: _fx.Bound) -> str:
    body = []
    for row in rows:
        cells = "".join(f"<td>{BAND_NAMES[verdicts[v][row['key']]]}</td>" for v, *_ in VARIANTS)
        body.append(f'<tr data-fx-key="{row["key"]}"><th scope="row">{row["name"]}</th>'
                    f'<td class="n">{bound.num(_dm(row["longitude_difference_degrees"], True))}</td>'
                    f'<td>{SIDE_SHORT[row["side"]]}</td>{cells}</tr>')
    return _fx.data_table(("天體", "黃經差", "太陽哪一側", *(label for *_, label in VARIANTS)), body)

def _figures(answer: dict) -> tuple[dict[str, str], list[str]]:
    module = answer["derived_methods"]["solar_phase"]
    results = module["profile_results"]
    rows = module["rows"]
    speeds = {body["key"]: body["speed_longitude"] for body in answer["astronomical_data"]["bodies"]}
    tables = {profile: results[profile]["limits"] for _, profile, _ in VARIANTS}
    edges = {
        variant: {row["key"]: {side: _edges(tables, profile, row["key"], side,
                                            "retrograde" if speeds[row["key"]] < 0 else "direct")
                               for side in ("morning", "evening")} for row in rows}
        for variant, profile, _ in VARIANTS
    }
    verdicts = {variant: results[profile]["bands"] for variant, profile, _ in VARIANTS}
    exceptions = {variant: results[profile]["venus_latitude_exception_degrees"] for variant, profile, _ in VARIANTS}
    for variant, *_ in VARIANTS:
        for row in rows:
            seen = _drawn_band(edges[variant][row["key"]][row["side"]], row["longitude_difference_degrees"],
                               row["ecliptic_latitude_degrees"], exceptions[variant], row["key"])
            if seen != verdicts[variant][row["key"]]:
                raise RuntimeError(f"{variant} {row['key']}: drawn {seen}, the product says {verdicts[variant][row['key']]}")
            for edge in edges[variant][row["key"]][row["side"]].values():
                if edge is not None and abs(abs(row["longitude_difference_degrees"]) - edge) * 3600 < 1:
                    raise RuntimeError(f"{row['key']} sits on a {variant} edge: inclusiveness would decide")
    labels = dict(VARIANT_LABELS)
    semidiameter = module["sun"]["semidiameter_degrees"]
    venus = next(row for row in rows if row["key"] == "venus")
    ruler_bound, ray_bound = _fx.Bound(), _fx.Bound()
    for bound in (ruler_bound, ray_bound):
        for _, label in VARIANT_LABELS:
            bound.label(label)
    ruler_notes = _first_glossed([_fx.Note(row["key"], v, _sentence(row, labels[v], verdicts[v][row["key"]], ruler_bound))
                                  for v, *_ in VARIANTS for row in rows])
    moment = MOMENT
    when = ruler_bound.num(f"{moment['year']} 年 {moment['month']} 月 {moment['day']} 日 "
                           f"{moment['hour']:02d}:{moment['minute']:02d}")
    ruler = _fx.figure(
        fid="fig-beams",
        hero=True,
        title="各星與太陽的黃經差，以及三套界線的距離帶",
        caption=(f"<b>{ruler_bound.label('圖 1')}</b>每一列是一顆星，橫軸是它與太陽的黃經差（等比例），中間的虛線是太陽；左邊是西側（晨星），"
                 f"右邊是東側（昏星）。距離帶由內到外是日輪內（cazimi，實心）、焦傷（combust，交叉線）、"
                 f"在光束下（under the beams，單線），"
                 f"界線依那顆星、那一側與它順行或逆行而定；按鈕切換三套界線。時刻是{ruler_bound.label('表 3')} 的合成時刻：{when}，臺北。"
                 f"相差超過 {ruler_bound.scale(f'{RULER_RANGE:g}')}° 的星畫在邊上的虛線圈裡。"),
        art=_fx.FigureArt.drawn(
            _ruler, "fig-beams", rows, verdicts, edges, ruler_bound,
            notes=ruler_notes,
            idle=IDLE,
        ),
        controls=_fx.FigureControls(
            variants=VARIANT_LABELS,
            switch_label=SWITCH_LABEL,
        ),
        table=_ruler_table(rows, verdicts, ruler_bound),
        bound=ruler_bound,
    )
    plotted = [row for row in rows if abs(row["longitude_difference_degrees"]) <= RAY_RANGE
               and abs(row["ecliptic_latitude_degrees"]) <= RAY_LATITUDE]
    ray_notes = [_fx.Note(row["key"], v, _sentence(row, labels[v], verdicts[v][row["key"]], ray_bound, True))
                 for v, *_ in VARIANTS for row in plotted]
    away = "、".join(row["name"] for row in rows if row not in plotted)
    rays = _fx.figure(
        fid="fig-rays",
        title="以太陽為中心的光芒圖：黃經差與黃緯，以及太陽前後 1° 的放大",
        caption=(f"<b>{ray_bound.label('圖 2')}</b>同一個時刻，以太陽為中心：橫軸是黃經差（越靠近太陽，刻度放得越大），縱軸是黃緯"
                 f"（只顯示，不判定）。距離帶畫成直條，所以金星在太陽北方 {ray_bound.num(_dm(venus['ecliptic_latitude_degrees']))}，"
                 f"仍落在黃經只差 {ray_bound.num(f"{round(abs(venus['longitude_difference_degrees']) * 60)}′")} 的那一條；"
                 f"按鈕切換三套界線，看同一顆金星的三個答案。直條是金星這一刻適用的界線。放大框是太陽前後 {ray_bound.scale('1°')}，"
                 f"橫直同比例，圓是日面。{away}離太陽 {ray_bound.scale(f'{RAY_RANGE:g}')}° 以上，不在圖內。"),
        art=_fx.FigureArt.drawn(
            _rays, "fig-rays", rows, verdicts, edges, exceptions, semidiameter, ray_bound,
            notes=ray_notes,
            idle=IDLE,
        ),
        controls=_fx.FigureControls(
            variants=VARIANT_LABELS,
            switch_label=SWITCH_LABEL,
        ),
        bound=ray_bound,
    )
    sprite = _fx.defs(("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"))
    return {"fx-defs": sprite, "beams": ruler, "rays": rays}, []

def _check_against_swiss(answer: dict) -> None:
    """The product's longitude differences, Venus's latitude and Mercury crossings against Swiss read directly."""
    module = answer["derived_methods"]["solar_phase"]
    jd = answer["astronomical_data"]["time"]["jd_ut"]
    with swiss() as swe:
        ids = {"moon": swe.MOON, "mercury": swe.MERCURY, "venus": swe.VENUS, "mars": swe.MARS,
               "jupiter": swe.JUPITER, "saturn": swe.SATURN}
        def difference(body: int, at: float) -> tuple[float, float]:
            planet, sun = calc_ut(swe, at, body), calc_ut(swe, at, swe.SUN)
            return (planet[0] - sun[0] + 180.0) % 360.0 - 180.0, planet[1]
        for row in module["rows"]:
            delta, latitude = difference(ids[row["key"]], jd)
            if abs(delta - row["longitude_difference_degrees"]) * 3600 > SAME_ARCSEC:
                raise RuntimeError(f"{row['key']}: product {row['longitude_difference_degrees']} != Swiss {delta}")
            if abs(latitude - row["ecliptic_latitude_degrees"]) * 3600 > SAME_ARCSEC:
                raise RuntimeError(f"{row['key']}: latitude {row['ecliptic_latitude_degrees']} != Swiss {latitude}")
        for _, profile, _ in VARIANTS:
            for crossing in module["profile_results"][profile]["beam_crossings_within_7_days"]["mercury"]:
                delta, _ = difference(swe.MERCURY, crossing["instant"]["jd_ut"])
                if abs(abs(delta) - crossing["threshold_degrees"]) * 3600 > CROSSING_ARCSEC:
                    raise RuntimeError(f"{profile}: Mercury at its crossing is {delta}°, not the limit")

def build() -> tuple[dict[str, str], list[str]]:
    with product_charts() as post:
        answer = post(REQUEST)
    _check_against_swiss(answer)
    module = answer["derived_methods"]["solar_phase"]
    results = module["profile_results"]
    rows = {row["key"]: row for row in module["rows"]}
    venus, mercury = rows["venus"], rows["mercury"]
    expected = {"lilly_1647_p113_v1": "cazimi", "hellenistic_15_v1": "under_beams",
                "biruni_wright_v1": "accompanying_high_latitude"}
    if any(results[profile]["bands"]["venus"] != band for profile, band in expected.items()):
        raise RuntimeError("the instant no longer gives Venus three answers")
    tables = {profile: results[profile]["limits"] for _, profile, _ in VARIANTS}
    example = []
    for key, name in NAMES.items():
        row = rows[key]
        bands = "".join(f"<td>{BAND_NAMES[results[profile]['bands'][key]]}</td>" for _, profile, _ in VARIANTS)
        example.append(f'          <tr><th scope="row">{name}</th><td class="n">{_dm(row["longitude_difference_degrees"],
            True)}</td>' f'<td class="n">{_dm(row["ecliptic_latitude_degrees"],
            True)}</td>' f'<td class="n">{_dm(row["angular_separation_degrees"])}</td>{bands}</tr>')
    crossings, quoted_offsets = [], []
    for _, profile, name in VARIANTS:
        found = results[profile]["beam_crossings_within_7_days"]["mercury"]
        if len(found) != 1:
            raise RuntimeError(f"{profile}: Mercury crosses {len(found)} times, the table expects one")
        item = found[0]
        when = _offset(item["day_offset"])
        quoted_offsets.append(when)
        crossings.append(
            f'          <tr><th scope="row">{escape(name)}</th><td class="n">{item["threshold_degrees"]:g}°</td>'
            f'<td>{DIRECTIONS[item["direction"]]}</td><td>{when}</td>'
            f'<td>{BAND_NAMES[results[profile]["bands"]["mercury"]]}</td></tr>'
        )
    semidiameter = module["sun"]["semidiameter_degrees"] * 60
    quoted = [f"黃經只差 {round(abs(venus['longitude_difference_degrees']) * 60)}′",
        f"北黃緯 {_dm(venus['ecliptic_latitude_degrees'])}",
        f"天空中離太陽 {_dm(venus['angular_separation_degrees'])}",
        f"水星在太陽東邊 {_dm(mercury['longitude_difference_degrees'])}", f"約 {semidiameter:.0f}′", *quoted_offsets]
    figures, _ = _figures(answer)
    return {**figures, "summary": _summary_rows(tables), "limits": solar_phase_limit_rows(), "example": "\n".join(example),
        "crossings": "\n".join(crossings)}, quoted
