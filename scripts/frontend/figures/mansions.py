"""〈月宿是什麼〉: figure 1 (the zodiac cut into 28 equal mansions under the
twelve signs; pointing at a mansion names it), figure 2 (the same Moon counted
from the vernal point and from sidereal 0° Aries, a switch between the two),
figure 3 (the stretch the Moon covers in the minute, the hour and the civil day
of table 2), table 2 (one Moon under three birth-time precisions) and the
numbers the prose quotes.

The mansion table, width and boundaries are the product's own
(backend/app/core/lunar_mansions.py); the example answers come from the real
application in process.  Synthetic instant only: 1990-11-03 Taipei, 14:00 for
the exact time, the 14:00 hour, and the civil day.  The sidereal row of
figure 2 is not a product output (the product refuses mansions in a sidereal
zodiac): it is the product's own sidereal Moon for the same instant, divided
the same way, so the article can show how far the starting point moves the
count.  The figures are the article figure component (`_fx`), direction 甲.
"""
from __future__ import annotations

from html import escape
import math

from . import _fx
from ._common import SIGNS, backend_on_path, calc_ut, indent, product_charts, swiss


FRAGMENT = "blog-lunar-mansions"
DAY = (1990, 11, 3)
HOUR = 14
LAT, LON = 25.05306, 121.52639
SIDEREAL = {"zodiac": "sidereal", "ayanamsa": "fagan_bradley"}


def _table() -> dict:
    with backend_on_path():
        from app.core import lunar_mansions
        from app.core.formatting import dms_text, sign_position

        return {
            "names": [transliteration for _, transliteration in lunar_mansions.MANSIONS],
            "starts": [lunar_mansions.mansion_start_degrees(i) for i in range(lunar_mansions.MANSION_COUNT)],
            "width": lunar_mansions.MANSION_WIDTH_DEGREES,
            "width_text": dms_text(lunar_mansions.MANSION_WIDTH_DEGREES),
            "positions": [sign_position(lunar_mansions.mansion_start_degrees(i))
                          for i in range(lunar_mansions.MANSION_COUNT)],
        }


def _request(precision: str, *, sidereal: bool = False) -> dict:
    hour = HOUR if precision != "date_only" else 0
    payload = {"birth_time_precision": precision,
               "datetime": {"year": DAY[0], "month": DAY[1], "day": DAY[2], "hour": hour, "minute": 0, "second": 0},
               "location": {"latitude": LAT, "longitude": LON},
               "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
               "options": {"include_lunar_mansions": True}}
    if sidereal:
        payload["computation_mode"] = dict(SIDEREAL)
    return payload


def _data() -> dict:
    d: dict = {}
    with product_charts() as post:
        for precision in ("exact", "approximate_hour", "date_only"):
            body = post(_request(precision))
            module = body["derived_methods"]["lunar_mansions"]
            if module["executed"] is not True:
                raise RuntimeError(f"{precision}: the mansion module did not run: {module.get('reason_code')}")
            moon = next(b for b in body["astronomical_data"]["bodies"] if b["key"] == "moon")
            d[precision] = {"module": module, "moon": moon}
        sidereal = post(_request("exact", sidereal=True))
        refusal = sidereal["derived_methods"]["lunar_mansions"]
        if (refusal["executed"], refusal["reason_code"]) != (False, "sidereal_lunar_mansion_basis_not_authorized"):
            raise RuntimeError(f"the product no longer refuses mansions in a sidereal zodiac: {refusal}")
        d["sidereal_moon"] = next(b for b in sidereal["astronomical_data"]["bodies"] if b["key"] == "moon")
        d["ayanamsa"] = sidereal["astronomical_data"]["time"]["ayanamsa"]
    return d


def civil_day_counts(width: float) -> dict[int, int]:
    """1950–2049, Taipei civil days (local midnight to the next, the end
    excluded): how many days the Moon is in 1, 2 or 3 mansions.  Local
    midnights come from the host's Asia/Taipei rules, daylight-saving years
    included; the Moon is Swiss Ephemeris's apparent geocentric Moon, as the
    product's date-only interval uses by default."""
    from datetime import date, datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    zone = ZoneInfo("Asia/Taipei")
    counts: dict[int, int] = {}
    with swiss() as swe:
        def moon_at(day: date) -> float:
            utc = datetime(day.year, day.month, day.day, tzinfo=zone).astimezone(timezone.utc)
            hours = utc.hour + utc.minute / 60 + utc.second / 3600
            return calc_ut(swe, swe.julday(utc.year, utc.month, utc.day, hours), swe.MOON)[0]

        day, end = date(1950, 1, 1), date(2050, 1, 1)
        start = moon_at(day)
        while day < end:
            day += timedelta(days=1)
            stop = moon_at(day)
            first = int(start // width)
            reach = start + (stop - start) % 360.0
            n = 1
            while width * (first + n) < reach:
                n += 1
            counts[n] = counts.get(n, 0) + 1
            start = stop
    return counts


def _mansion_of(longitude: float, width: float) -> int:
    return int((longitude % 360.0) // width) + 1


def _sign_text(position: list) -> str:
    """[1, '15°23′17.41″', …] -> 「金牛 15°23′」."""
    dms = position[1]
    return f"{SIGNS[position[0]]} {dms[:dms.index('′') + 1]}"


# --- the figures -------------------------------------------------------------
# Direction 甲 (_fx): two drawings per figure, a hatch for the Moon's mansion,
# red only for the mansion pointed at.  Every verdict drawn (which mansion holds
# the Moon) is read back from the drawn boundaries and must equal the product's.

WHEEL_IDLE = "用 Tab 鍵移到一宿上，或用滑鼠指著它，這裡會寫出它的宿名與起點。"
COUNT_IDLE = "用 Tab 鍵移到月亮上，或用滑鼠指著它，這裡會寫出它在這一種起點下落在第幾宿。"
COUNTS = (("tropical", "從春分點起（本站）"), ("sidereal", "從恆星牡羊 0° 起（示意）"))
COUNT_SWITCH = "切換兩種起點"
# The strip of figure 2: the vernal point, sidereal 0° Aries and the Moon.
COUNT_RANGE = (0.0, 72.0)
# A drawn boundary this close to the Moon (degrees, one arcsecond) would leave
# the verdict to whether the boundary belongs to the mansion.
EDGE = 1 / 3600


def _position(p: list) -> str:
    """[1, '8°34′17.14″', …] -> 「金牛 8°34′17.14″」, as the result page prints a boundary."""
    return f"{SIGNS[p[0]]} {p[1]}"


def _polar(cx: float, cy: float):
    """Longitude 0 (the vernal point) at the left, counting counter-clockwise, as a chart wheel."""
    def pt(lon: float, r: float) -> tuple[float, float]:
        a = math.radians(180 + lon)
        return cx + r * math.cos(a), cy - r * math.sin(a)
    return pt


def _ring(pt, lon0: float, lon1: float, outer: float, inner: float) -> str:
    """The path of one ring segment from lon0 to lon1."""
    f = _fx.f
    (ax, ay), (bx, by) = pt(lon0, outer), pt(lon1, outer)
    (cx, cy), (dx, dy) = pt(lon1, inner), pt(lon0, inner)
    return (f"M{f(ax)} {f(ay)} A{f(outer)} {f(outer)} 0 0 0 {f(bx)} {f(by)} "
            f"L{f(cx)} {f(cy)} A{f(inner)} {f(inner)} 0 0 1 {f(dx)} {f(dy)} Z")


def _cardinal(start: float) -> bool:
    return abs(start - round(start / 90) * 90) < 1e-9


def _wheel(layout: str, fid: str, t: dict, bound: _fx.Bound) -> str:
    """Figure 1, one layout: the twelve signs outside, the 28 mansions inside."""
    wide = layout == "fx-wide"
    if wide:
        W, H, cx, cy = _fx.WIDE, 600.0, 300.0, 300.0
        r_sign, r_ring, r_inner, r_card, lift = 276.0, 222.0, 172.0, 146.0, 6.0
        sign_cls = "fx-t fx-key"
    else:
        W, H, cx, cy = _fx.NARROW, 430.0, 170.0, 170.0
        r_sign, r_ring, r_inner, r_card, lift = 156.0, 124.0, 96.0, 78.0, 4.0
        sign_cls = "fx-t fx-small fx-key"
    pt = _polar(cx, cy)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for k in range(12):
        out.append(_fx.path(_ring(pt, 30 * k, 30 * (k + 1), r_sign, r_ring), "fx-fill-dot" if k % 2 else "fx-track"))
    for i, start in enumerate(t["starts"]):
        end = start + t["width"]
        key, number = f"m{i + 1}", bound.scale(str(i + 1))
        name = t["names"][i]
        x, y = pt(start + t["width"] / 2, (r_ring + r_inner) / 2)
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" '
                   f'aria-label="第 {number} 宿 {name}，從{bound.num(_position(t["positions"][i]))} 起">'
                   + _fx.path(_ring(pt, start, end, r_ring, r_inner), "fx-hit")
                   + _fx.text(x, y + lift - 1, number, "fx-t fx-small fx-num", "middle") + "</g>")
    for r in (r_sign, r_ring, r_inner):
        out.append(_fx.circle(cx, cy, r, "fx-axis"))
    for k in range(12):
        if k % 3:
            (x0, y0), (x1, y1) = pt(30 * k, r_sign), pt(30 * k, r_ring)
            out.append(_fx.line(x0, y0, x1, y1, "fx-axis"))
        x, y = pt(30 * k + 15, (r_sign + r_ring) / 2)
        out.append(_fx.text(x, y + lift, SIGNS[k], sign_cls, "middle"))
    quarters = []
    for i, start in enumerate(t["starts"]):
        if _cardinal(start):
            quarters.append(i + 1)
            (x0, y0), (x1, y1) = pt(start, r_sign), pt(start, r_card)
            out.append(_fx.line(x0, y0, x1, y1, "fx-frame"))
        else:
            (x0, y0), (x1, y1) = pt(start, r_ring), pt(start, r_inner)
            out.append(_fx.line(x0, y0, x1, y1, "fx-axis"))
    if quarters != [1, 8, 15, 22]:
        raise RuntimeError(f"the mansions starting at a cardinal point are {quarters}")
    width = bound.num(t["width_text"])
    if wide:
        out.append(_fx.text(cx, cy - 28, f"{bound.scale('28')} 等分", "fx-t", "middle"))
        out.append(_fx.text(cx, cy + 4, f"每宿 {width}", "fx-t fx-num", "middle"))
        out.append(_fx.text(cx, cy + 34, "內圈數字是第幾宿", "fx-t fx-small", "middle"))
        out.append(_fx.text(cx - r_card + 8, cy - 10, "春分點", "fx-t fx-small"))
        lx, ly = 604.0, 236.0
        cards = "、".join(bound.scale(str(n)) for n in quarters)
        legend = (
            (lambda y: _fx.rect(lx, y - 14, 34, 18, "fx-track"), f"外圈：十二星座，各 {bound.scale('30')}°"),
            (lambda y: _fx.rect(lx, y - 14, 34, 18, "fx-fill-dot") + _fx.rect(lx, y - 14, 34, 18, "fx-inset-frame"),
             "（兩種底紋交替）"),
            (lambda y: _fx.line(lx, y - 5, lx + 34, y - 5, "fx-frame"), "粗線：宿界正落在星座起點"),
            (lambda y: "", f"（第 {cards} 宿）"),
            (lambda y: _fx.line(lx, y - 5, lx + 34, y - 5, "fx-axis"), "細線：其他宿界，在星座中間"),
        )
        for i, (sample, label) in enumerate(legend):
            y = ly + 34 * i
            out.append(sample(y) + _fx.text(lx + 46, y, label, "fx-t fx-small"))
    else:
        out.append(_fx.text(cx, cy - 20, f"{bound.scale('28')} 等分", "fx-t fx-small", "middle"))
        out.append(_fx.text(cx, cy, "每宿", "fx-t fx-small", "middle"))
        out.append(_fx.text(cx, cy + 18, width, "fx-t fx-small fx-num", "middle"))
        out.append(_fx.text(cx - r_card + 4, cy + 36, "春分點", "fx-t fx-small"))
        ly = cy + r_sign + 40
        out.append(_fx.line(14, ly - 5, 44, ly - 5, "fx-frame"))
        out.append(_fx.text(54, ly, "粗線：宿界正落在星座起點", "fx-t fx-small"))
        out.append(_fx.text(54, ly + 20, f"（第 {'、'.join(bound.scale(str(n)) for n in quarters)} 宿）",
                            "fx-t fx-small"))
        out.append(_fx.line(14, ly + 39, 44, ly + 39, "fx-axis"))
        out.append(_fx.text(54, ly + 44, "細線：其他宿界，在星座中間", "fx-t fx-small"))
        if ly + 60 > H:
            raise RuntimeError("figure 1 outgrew its drawing")
    out.append("</svg>")
    return "".join(out)


def _wheel_table(t: dict, bound: _fx.Bound) -> str:
    rows = "".join(
        f'<tr data-fx-key="m{i + 1}"><td class="n">{bound.scale(str(i + 1))}</td><td>{escape(name)}</td>'
        f'<td class="n">{bound.num(_position(t["positions"][i]))}</td></tr>'
        for i, name in enumerate(t["names"]))
    return ('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
            '<table class="ar-table fx-table"><thead><tr><th scope="col">宿</th><th scope="col">宿名（轉寫）</th>'
            f'<th scope="col">起點</th></tr></thead><tbody>{rows}</tbody></table></div></details>')


def _drawn_mansion(shift: float, width: float, longitude: float) -> int:
    """The mansion a reader sees the Moon in: the drawn strip from `shift + k·width`
    that holds it, numbered from the strip that starts at `shift`."""
    k = math.floor((longitude - shift) / width)
    start = shift + k * width
    if min(longitude - start, start + width - longitude) < EDGE:
        raise RuntimeError("the Moon sits on a drawn boundary: inclusiveness would decide")
    return k % 28 + 1


def _count_row(x, y: float, h: float, shift: float, hit: int, active: bool, xm: float, width: float,
               lo: float, hi: float, bound: _fx.Bound, wide: bool) -> str:
    """One count drawn along the strip: its boundaries, its numbers, the Moon's mansion hatched."""
    out = [_fx.rect(x(lo), y, x(hi) - x(lo), h, "fx-track")]
    lines = []
    for k in range(math.floor((lo - shift) / width), math.ceil((hi - shift) / width) + 1):
        start = shift + k * width
        a, b = max(start, lo), min(start + width, hi)
        n = k % 28 + 1
        if b > a:
            if n == hit:
                out.append(_fx.rect(x(a), y, x(b) - x(a), h, "fx-fill-hatch" if active else "fx-fill-dot"))
            if x(b) - x(a) > (24 if wide else 20):
                tx = (x(a) + x(b)) / 2
                if abs(tx - xm) < (20 if wide else 14):  # keep the number clear of the Moon's line
                    tx = (x(a) + xm) / 2 if xm - x(a) > x(b) - xm else (xm + x(b)) / 2
                cls = "fx-t fx-num fx-key" if active else "fx-t fx-small fx-num fx-dim fx-key"
                if not wide:
                    cls = cls.replace("fx-t fx-num", "fx-t fx-small fx-num")
                out.append(_fx.text(tx, y + h / 2 + (6 if wide else 4), bound.scale(str(n)), cls, "middle"))
        if lo <= start <= hi:
            cls = "fx-frame" if k % 28 == 0 else "fx-axis" if active else "fx-hair"
            lines.append(_fx.line(x(start), y, x(start), y + h, cls))
    return "".join(out + lines)


def _counts(layout: str, fid: str, t: dict, d: dict, bound: _fx.Bound) -> str:
    """Figure 2, one layout: the same stretch of tropical longitude cut from the
    vernal point (the product) and from sidereal 0° Aries (an illustration)."""
    wide = layout == "fx-wide"
    lo, hi = COUNT_RANGE
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (34.0, 846.0) if wide else (14.0, 326.0)
    x = lambda lon: x0 + (x1 - x0) * (lon - lo) / (hi - lo)  # noqa: E731
    moon = d["exact"]["moon"]["longitude"]
    ayan = d["ayanamsa"]
    hits = {"tropical": _drawn_mansion(0.0, t["width"], moon), "sidereal": _drawn_mansion(ayan, t["width"], moon)}
    xm = x(moon)
    if wide:
        H, h, rows, moon_y = 384.0, 44.0, {"tropical": 124.0, "sidereal": 228.0}, 62.0
    else:
        H, h, rows, moon_y = 382.0, 38.0, {"tropical": 120.0, "sidereal": 216.0}, 58.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    bottom = rows["sidereal"] + h
    for sign in range(3):
        out.append(_fx.line(x(30 * sign), rows["tropical"] - 6, x(30 * sign), bottom + 6, "fx-hair"))
    labels = {"tropical": "從春分點起數（本站）",
              "sidereal": f"從恆星牡羊 {bound.scale('0')}° 起數（示意，本站不輸出）"}
    for variant, _ in COUNTS:
        body = []
        for row, shift in (("tropical", 0.0), ("sidereal", ayan)):
            active = row == variant
            y = rows[row]
            body.append(_fx.text(x0, y - 10, labels[row], "fx-t fx-key" if active else "fx-t fx-dim fx-key"))
            body.append(_count_row(x, y, h, shift, hits[row], active, xm, t["width"], lo, hi, bound, wide))
        out.append(_fx.variant_group(variant, COUNTS[0][0], "".join(body)))
    # the two starting points and the arc between them
    by = bottom + (26 if wide else 22)
    out.append(_fx.line(x(0), by, x(ayan), by, "fx-axis"))
    for edge in (0.0, ayan):
        out.append(_fx.line(x(edge), by - 6, x(edge), by + 6, "fx-axis"))
    gap = bound.num(f"{ayan:.1f}")
    if wide:
        out.append(_fx.text(x(ayan) + 10, by + 6, f"兩個起點相差約 {gap}°（Fagan–Bradley）", "fx-t fx-small"))
    else:
        out.append(_fx.text(x(ayan) + 8, by + 5, f"相差約 {gap}°", "fx-t fx-small"))
    sy = by + (40 if wide else 36)
    names = ("牡羊", "金牛", "雙子")
    for sign in range(3):
        anchor = "start" if sign == 0 else "middle"
        out.append(_fx.text(x(30 * sign), sy, f"{names[sign]} {bound.scale('0')}°", "fx-t fx-small fx-num", anchor))
    out.append(_fx.text(x1, sy + (24 if wide else 20), "回歸黃道的黃經", "fx-t fx-small fx-dim", "end"))
    # the Moon: one line through both counts, its mark on top
    position = bound.num(_sign_text(d["exact"]["moon"]["sign_position"]))
    out.append(_fx.line(xm, moon_y + 12, xm, bottom + 4, "fx-axis"))
    out.append(f'<g class="fx-row" data-fx-key="moon" tabindex="0" aria-label="月亮，{position}">'
               + _fx.circle(xm, moon_y, 20, "fx-hit") + _fx.circle(xm, moon_y, 11 if wide else 10, "fx-mk")
               + _fx.glyph("moon", xm, moon_y, 14 if wide else 12, "fx-mk-gl")
               + _fx.text(xm + 20, moon_y + 6, f"月亮 {position}", "fx-t" if wide else "fx-t fx-small") + "</g>")
    out.append("</svg>")
    if sy + 24 > H:
        raise RuntimeError("figure 2 outgrew its drawing")
    return "".join(out)


def _count_notes(t: dict, d: dict, bound: _fx.Bound) -> list:
    moon = d["exact"]["moon"]
    product = d["exact"]["module"]["placements"][0]
    tropical, sidereal = product["mansion"]["number"], _mansion_of(d["sidereal_moon"]["longitude"], t["width"])
    return [
        _fx.Note("moon", "tropical",
                 f"月亮在{bound.num(_sign_text(moon['sign_position']))}。從春分點起數，落在第 {bound.num(str(tropical))} 宿 "
                 f"{t['names'][tropical - 1]}，這是本站的算法。"),
        _fx.Note("moon", "sidereal",
                 f"同一個月亮，改從恆星黃道的牡羊 {bound.scale('0')}° 起數（Fagan–Bradley 歲差值，兩個起點相差約 "
                 f"{bound.num(f'{d['ayanamsa']:.1f}')}°），落在第 {bound.num(str(sidereal))} 宿 {t['names'][sidereal - 1]}。"
                 "本站不輸出這一種，只是示意。"),
    ]


def _count_table(t: dict, d: dict, bound: _fx.Bound) -> str:
    tropical = d["exact"]["module"]["placements"][0]["mansion"]["number"]
    sidereal = _mansion_of(d["sidereal_moon"]["longitude"], t["width"])
    rows = (
        ("tropical", "春分點（本站）", d["exact"]["moon"], tropical),
        ("sidereal", f"恆星牡羊 {bound.scale('0')}°（示意）", d["sidereal_moon"], sidereal),
    )
    body = "".join(
        f'<tr><th scope="row">{label}</th><td class="n">{bound.num(_sign_text(moon["sign_position"]))}</td>'
        f'<td>第 {bound.num(str(n))} 宿 {escape(t["names"][n - 1])}</td></tr>'
        for _, label, moon, n in rows)
    return ('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
            '<table class="ar-table fx-table"><thead><tr><th scope="col">從哪裡起數</th>'
            '<th scope="col">月亮的黃經（各自的黃道）</th><th scope="col">落在</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div></details>')


def _span_mansions(start: float, end: float, width: float) -> list[int]:
    """The mansions a drawn bar from `start` to `end` (the Moon only moves forward) touches."""
    first = math.floor(start / width)
    reach = start + (end - start) % 360.0
    out = [first % 28 + 1]
    k = first + 1
    while k * width < reach:
        out.append(k % 28 + 1)
        k += 1
    return out


DAY_IDLE = "用 Tab 鍵移到一列上，或用滑鼠指著它，這裡會寫出月亮在那段時間從哪裡走到哪裡。"
# Table 2's three precisions, in the order the figure draws them.
PRECISIONS = (("day", "date_only"), ("hour", "approximate_hour"), ("exact", "exact"))


def _day_rows(t: dict, d: dict, bound: _fx.Bound) -> list[dict]:
    """What figure 3 draws per precision: the stretch, its label, the mansions
    it touches, its short note and its sentence."""
    with backend_on_path():
        from app.core.formatting import sign_position

    def where(lon: float) -> str:
        position = sign_position(lon)
        if position is None:
            raise RuntimeError("no sign position for a Moon longitude")
        return bound.num(_sign_text(position))

    hour = bound.num(str(HOUR))
    rows = []
    for key, precision in PRECISIONS:
        module = d[precision]["module"]
        if key == "exact":
            moon = d["exact"]["moon"]["longitude"]
            n = module["placements"][0]["mansion"]["number"]
            numbers = [n]
            a = b = moon
            label = f"精確到分鐘（{bound.num(f'{HOUR}:00')}）"
            note = f"{where(moon)}：第 {bound.num(str(n))} 宿"
            sentence = (f"精確到分鐘：{bound.num(f'{HOUR}:00')} 月亮在{where(moon)}，只列一宿："
                        f"第 {bound.num(str(n))} 宿 {t['names'][n - 1]}。")
        else:
            interval = module["birth_time_interval"]
            (a, b), = interval["moon_longitudes"]
            numbers = [item["number"] for item in interval["mansions"]]
            listed = "、".join(bound.num(str(n)) for n in numbers)
            arc = bound.num(f"{(b - a) % 360:.1f}")
            if key == "day":
                label, span = "只知道日期（民用日）", "那一個民用日裡"
                note = f"一天走了約 {arc}°：第 {listed} 宿"
            else:
                label, span = f"只知道約略小時（{hour} 點）", f" {hour} 點那一個鐘點裡"
                note = f"一小時走了約 {arc}°：只在第 {listed} 宿"
            sentence = (f"{label[:label.index('（')]}：列出{span}月亮待過的每一宿。這段時間月亮從{where(a)}"
                        f"走到{where(b)}，約 {arc}°，經過第 {listed} 宿。")
        rows.append({"key": key, "start": a, "end": b, "numbers": numbers, "label": label, "note": note,
                     "sentence": sentence})
    return rows


def _day(layout: str, fid: str, t: dict, rows: list[dict], bound: _fx.Bound) -> str:
    """Figure 3, one layout: the stretch the Moon covers in the minute, the hour
    and the civil day of table 2, on the mansions the day crosses."""
    wide = layout == "fx-wide"
    shown = rows[0]["numbers"]
    lo, hi = t["starts"][shown[0] - 1], t["starts"][shown[-1] - 1] + t["width"]
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (40.0, 840.0) if wide else (14.0, 326.0)
    x = lambda lon: x0 + (x1 - x0) * (lon - lo) / (hi - lo)  # noqa: E731
    small = "fx-t fx-small"
    if wide:
        top, strip, ys, H, bar = 34.0, 52.0, (162.0, 236.0, 310.0), 356.0, 18.0
    else:
        top, strip, ys, H, bar = 22.0, 50.0, (150.0, 238.0, 324.0), 388.0, 16.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    bottom = ys[2] + bar
    for n in shown:
        a, b = t["starts"][n - 1], t["starts"][n - 1] + t["width"]
        out.append(_fx.rect(x(a), top, x(b) - x(a), strip, "fx-track"))
        label = f"第 {bound.scale(str(n))} 宿"
        if wide:
            out.append(_fx.text((x(a) + x(b)) / 2, top + strip / 2 + 6, f"{label} {t['names'][n - 1]}", "fx-t", "middle"))
        else:
            out.append(_fx.text((x(a) + x(b)) / 2, top + 21, label, small, "middle"))
            out.append(_fx.text((x(a) + x(b)) / 2, top + 39, t["names"][n - 1], small, "middle"))
    for i, n in enumerate(shown + [shown[-1] + 1]):
        start = t["starts"][(n - 1) % 28]
        edge = lo if i == 0 else hi if i == len(shown) else start
        out.append(_fx.line(x(edge), top + strip, x(edge), bottom, "fx-sunline"))
        anchor = "start" if i == 0 else "end" if i == len(shown) else "middle"
        out.append(_fx.text(x(edge), top + strip + 20, bound.num(_sign_text(t["positions"][(n - 1) % 28])),
                            "fx-t fx-small fx-num fx-key", anchor))
    fills = {"day": "fx-fill-hatch", "hour": "fx-fill-solid", "exact": ""}
    for y, row in zip(ys, rows):
        a, b, cls = row["start"], row["end"], fills[row["key"]]
        if _span_mansions(a, b, t["width"]) != row["numbers"]:
            raise RuntimeError(f"figure 3 draws the {row['key']} Moon across {_span_mansions(a, b, t['width'])}, "
                               f"the product lists {row['numbers']}")
        parts = [_fx.rect(x0 - (26 if wide else 8), y - (32 if wide else 28), (x1 - x0) + (52 if wide else 16),
                          bar + (56 if wide else 72), "fx-hit"),
                 _fx.text(x0, y - (12 if wide else 10), row["label"], "fx-t fx-key" if wide else small + " fx-key")]
        if cls:
            parts.append(_fx.rect(x(a), y, max(x(b) - x(a), 3.0), bar, cls))
            parts.append(_fx.line(x(a), y - 4, x(a), y + bar + 4, "fx-edge")
                         + _fx.line(x(b), y - 4, x(b), y + bar + 4, "fx-edge"))
            end = x(b)
        else:
            parts.append(_fx.circle(x(a), y + bar / 2, 10 if wide else 9, "fx-mk")
                         + _fx.glyph("moon", x(a), y + bar / 2, 13 if wide else 11, "fx-mk-gl"))
            end = x(a) + 10
        if wide:
            parts.append(_fx.text(end + 14, y + bar / 2 + 5, row["note"], small + " fx-key"))
        else:
            parts.append(_fx.text(x0, y + bar + 20, row["note"], small + " fx-key"))
        out.append(f'<g class="fx-row" data-fx-key="{row["key"]}" tabindex="0" '
                   f'aria-label="{row["label"]}，{row["note"]}">' + "".join(parts) + "</g>")
    out.append("</svg>")
    if not wide and ys[2] + bar + 30 > H:
        raise RuntimeError("figure 3 outgrew its drawing")
    return "".join(out)


def _figures(t: dict, d: dict) -> dict[str, str]:
    """The page's sprite and its three figures, each checked by `_fx.problems`."""
    exact = d["exact"]["module"]["placements"][0]["mansion"]["number"]
    sidereal = _mansion_of(d["sidereal_moon"]["longitude"], t["width"])
    moon = d["exact"]["moon"]["longitude"]
    if _drawn_mansion(0.0, t["width"], moon) != exact:
        raise RuntimeError(f"figure 2 draws the Moon in mansion {_drawn_mansion(0.0, t['width'], moon)}, "
                           f"the product says {exact}")
    if _drawn_mansion(d["ayanamsa"], t["width"], moon) != sidereal:
        raise RuntimeError(f"figure 2 draws the sidereal Moon in mansion {_drawn_mansion(d['ayanamsa'], t['width'], moon)}, "
                           f"the sidereal Moon divided the same way is in {sidereal}")

    wheel_bound, count_bound, day_bound = _fx.Bound(), _fx.Bound(), _fx.Bound()
    for bound, labels in ((wheel_bound, ("圖 1", "[6]")), (count_bound, ("圖 2", "[6]", "[7]")),
                          (day_bound, ("圖 3", "表 2"))):
        for label in labels:
            bound.label(label)
    for _, label in COUNTS:
        count_bound.label(label)
    wheel_notes = [
        _fx.Note(f"m{i + 1}", None,
                 f"第 {wheel_bound.scale(str(i + 1))} 宿 {name}：從{wheel_bound.num(_position(t['positions'][i]))} 起，"
                 f"到{wheel_bound.num(_position(t['positions'][(i + 1) % 28]))}為止（不含終點）。")
        for i, name in enumerate(t["names"])]
    wheel = _fx.figure(
        fid="fig-wheel", hero=True,
        title=(f"黃道一圈的兩種切法疊在一起：外圈是十二星座，每個 30 度；內圈是 28 個月宿，每宿 {t['width_text']}，"
               "從牡羊 0 度（春分點）起依序編號。第 1、8、15、22 宿的起點正好落在牡羊、巨蟹、天秤、摩羯的 0 度，以粗線標出；"
               "其餘的宿界大多落在星座中間。"),
        caption=(f"<b>{wheel_bound.label('圖 1')}</b>外圈是十二星座，內圈是本站的 {wheel_bound.scale('28')} 個月宿。"
                 f"每一宿一樣寬，從春分點（牡羊 {wheel_bound.scale('0')}°）起依序編號；只有第 "
                 f"{'、'.join(wheel_bound.scale(str(n)) for n in (1, 8, 15, 22))} 宿的起點正好落在星座的起點（粗線），"
                 '其餘的宿界都落在星座中間<a class="ar-cite" href="#ref-6">[6]</a>。'),
        wide=_wheel("fx-wide", "fig-wheel", t, wheel_bound),
        narrow=_wheel("fx-narrow", "fig-wheel", t, wheel_bound),
        notes=wheel_notes, idle=WHEEL_IDLE, table=_wheel_table(t, wheel_bound),
    )
    count_notes = _count_notes(t, d, count_bound)
    counts = _fx.figure(
        fid="fig-counts",
        title=(f"同一個月亮，兩種起點：從春分點起算是本站的做法，月亮落在第 {exact} 宿；從恆星黃道的牡羊 0 度起算"
               f"（以 Fagan–Bradley 的歲差值，1990 年時兩個起點相差約 {d['ayanamsa']:.1f} 度），所有宿界都挪了將近兩宿的寬度，"
               f"同一個月亮落在第 {sidereal} 宿。後者本站不輸出，只是示意。"),
        caption=(f"<b>{count_bound.label('圖 2')}</b>同一個月亮，兩種起點。上面一列是本站的算法，從春分點起；"
                 f"下面一列改從恆星黃道的牡羊 {count_bound.scale('0')}° 起，宿界整排挪了約 "
                 f"{count_bound.num(f'{d['ayanamsa']:.1f}')}°。單線排線是月亮落入的那一宿；按鈕切換以哪一列為主。"
                 "古書也有以星群為準、寬窄不一的劃法，以及從其他位置起算的刻度，這張圖沒有畫"
                 '<a class="ar-cite" href="#ref-6">[6]</a><a class="ar-cite" href="#ref-7">[7]</a>。'),
        wide=_counts("fx-wide", "fig-counts", t, d, count_bound),
        narrow=_counts("fx-narrow", "fig-counts", t, d, count_bound),
        notes=count_notes, idle=COUNT_IDLE, variants=COUNTS, switch_label=COUNT_SWITCH,
        table=_count_table(t, d, count_bound),
    )
    day_rows = _day_rows(t, d, day_bound)
    hour, day = (d[p]["module"]["birth_time_interval"]["moon_longitudes"][0] for p in ("approximate_hour", "date_only"))
    days = _fx.figure(
        fid="fig-day",
        title="同一個合成日子，三種出生時間精確程度下月亮走過的黃道：精確時刻是一點，一小時是一小段，一個民用日跨過兩條宿界。",
        caption=(f"<b>{day_bound.label('圖 3')}</b>{day_bound.label('表 2')} 的三種精確程度，畫在同一段黃道上。"
                 f"那一小時月亮走了約 {day_bound.num(f'{(hour[1] - hour[0]) % 360:.1f}')}°，沒有跨過宿界；"
                 f"那一天走了約 {day_bound.num(f'{(day[1] - day[0]) % 360:.1f}')}°，跨過兩條宿界，"
                 "所以只知道日期時列出三宿。點線是宿界。"),
        wide=_day("fx-wide", "fig-day", t, day_rows, day_bound),
        narrow=_day("fx-narrow", "fig-day", t, day_rows, day_bound),
        notes=[_fx.Note(row["key"], None, row["sentence"]) for row in day_rows], idle=DAY_IDLE,
    )
    for markup, bound in ((wheel, wheel_bound), (counts, count_bound), (days, day_bound)):
        found = _fx.problems(markup, bound)
        if found:
            raise RuntimeError("figure check: " + "; ".join(found))
    return {"fx-defs": _fx.defs(("moon",)), "wheel": wheel, "counts": counts, "day": days}


def _row(label: str, module: dict) -> str:
    interval = module["birth_time_interval"]
    names = interval["mansions"] if interval else [module["placements"][0]["mansion"]]
    cell = "<br>".join(f"第 {item['number']} 宿 {item['transliteration']}" for item in names)
    return f"          <tr><td>{label}</td><td>{cell}</td></tr>"


def _times(d: dict) -> str:
    return "\n".join((
        _row(f"精確到分鐘（{HOUR}:00）", d["exact"]["module"]),
        _row(f"只知道約略小時（{HOUR} 點）", d["approximate_hour"]["module"]),
        _row("只知道日期（民用日）", d["date_only"]["module"]),
    ))


def build() -> tuple[dict[str, str], list[str]]:
    t = _table()
    d = _data()
    exact = d["exact"]["module"]["placements"][0]
    hour = d["approximate_hour"]["module"]["birth_time_interval"]
    day = d["date_only"]["module"]["birth_time_interval"]
    if exact["mansion"]["number"] != _mansion_of(d["exact"]["moon"]["longitude"], t["width"]):
        raise RuntimeError("the product's mansion and the article's division disagree")
    if hour["crosses_mansion_boundary"] or not day["crosses_mansion_boundary"]:
        raise RuntimeError("the example no longer stays in one mansion for the hour and crosses for the day")
    (day_start, day_end), = day["moon_longitudes"]
    day_numbers = "、".join(str(item["number"]) for item in day["mansions"])
    sidereal_n = _mansion_of(d["sidereal_moon"]["longitude"], t["width"])
    counts = civil_day_counts(t["width"])
    if set(counts) != {1, 2, 3} or max(counts, key=lambda n: counts[n]) != 2:
        raise RuntimeError(f"a civil day no longer holds mostly two mansions: {counts}")
    share = {n: round(100 * counts[n] / sum(counts.values())) for n in counts}
    quoted = [
        f"每宿 360°÷28＝{t['width_text']}",
        f"月亮在{_sign_text(d['exact']['moon']['sign_position'])}，落在第 {exact['mansion']['number']} 宿 "
        f"{exact['mansion']['transliteration']}",
        f"已經走了 {exact['degrees_into_mansion_text'][:exact['degrees_into_mansion_text'].index('′') + 1]}",
        f"這一天月亮走了約 {(day_end - day_start) % 360:.1f}°",
        f"第 {day_numbers} 宿",
        f"兩個起點相差約 {d['ayanamsa']:.1f}°",
        f"落在第 {sidereal_n} 宿",
        f"約 {share[2]}% 是兩宿、約 {share[3]}% 是三宿、約 {share[1]}% 只有一宿",
    ]
    return {**_figures(t, d), "times": _times(d)}, quoted
