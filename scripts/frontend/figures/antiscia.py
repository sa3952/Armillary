"""〈反照點是什麼〉: figure 1 (the demonstration chart's seven planets on the
zodiac wheel and their mirror points, under a switch between antiscia — the
mirror in the solstitial axis — and contra-antiscia — the mirror in the
equinoctial axis; each planet can be pointed at), figure 2 (the length of
daylight in Taipei against the Sun's longitude through 2026, with Lilly's
pair 10° Taurus and 20° Leo) and the numbers the prose quotes.

Every mirror point is the product's answer in process
(`derived_geometry.antiscia` of the demonstration chart, 1990-05-15 14:30
Taipei, with antiscia requested; the same chart in the sidereal zodiac with
the Fagan–Bradley ayanamsa), and the build stops unless each is the planet's
longitude mirrored as the article states.  Lilly's worked example is the
product's own function applied to his Saturn.  Each day length is the
product's sunrise and sunset for that Taipei date (the planetary-hours
module's), the dates those on which Swiss Ephemeris puts the Sun at each
longitude.
"""
from __future__ import annotations

import datetime as dt
import functools

from . import _fx
from ._common import PLANETS, backend_on_path, product_charts, swiss
from ._demo import DEMO, zodiacal_minutes


FRAGMENT = "blog-antiscia"
PLANET_KEYS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
SIGN_KEYS = ("aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius",
             "capricorn", "aquarius", "pisces")
OPTIONS = {**DEMO["options"], "include_antiscia": True}
SIDEREAL = {"zodiac": "sidereal", "ayanamsa": "fagan_bradley"}
# Lilly 1647 p.90: Saturn in 20°35' of Leo.
LILLY_SATURN = 120 + 20 + 35 / 60
# Lilly's sun pair, p.90: 10° Taurus and 20° Leo.
LILLY_PAIR = (40.0, 140.0)
YEAR = 2026
TAIPEI_OFFSET_HOURS = 8
# One second of arc.
TOLERANCE = 1 / 3600
VARIANTS = (("antiscia", "反照點 antiscia（至點軸）"), ("contra", "反向反照點 contra-antiscia（分點軸）"))


def _close(a: float, b: float) -> bool:
    return abs((a - b + 180) % 360 - 180) < TOLERANCE


def _read(answer: dict) -> dict:
    bodies = {item["key"]: item["longitude"] for item in answer["astronomical_data"]["bodies"]}
    geometry = answer["derived_geometry"]["antiscia"]
    if geometry["scope"]["included_keys"] != list(PLANET_KEYS):
        raise RuntimeError(f"the antiscia now cover {geometry['scope']['included_keys']}")
    return {
        "bodies": {key: bodies[key] for key in PLANET_KEYS},
        "antiscia": {item["key"]: item["longitude"] for item in geometry["antiscia"]},
        "contra": {item["key"]: item["longitude"] for item in geometry["contra_antiscia"]},
    }


def _taipei_date(jd: float, swe) -> dt.date:
    year, month, day, _hour = swe.revjul(jd + TAIPEI_OFFSET_HOURS / 24)
    return dt.date(year, month, day)


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    with swiss() as swe:
        start = swe.julday(YEAR, 1, 1, 0.0)
        dates = {lon: _taipei_date(swe.solcross_ut(float(lon), start, swe.FLG_SWIEPH), swe)
                 for lon in [*range(0, 360, 10), *LILLY_PAIR]}
    with product_charts() as post:
        tropical = _read(post({**DEMO, "options": OPTIONS}))
        sidereal = _read(post({**DEMO, "options": OPTIONS, "computation_mode": SIDEREAL}))
        daylight = {}
        for lon, date in dates.items():
            day = post({**DEMO, "datetime": {"year": date.year, "month": date.month, "day": date.day, "hour": 12,
                                             "minute": 0, "second": 0},
                        "options": {"house_system": "W", "include_houses": False}})
            planetary = day["derived_methods"]["planetary_hours"]["chart_instant"]["planetary_day"]
            sun = next(b["longitude"] for b in day["astronomical_data"]["bodies"] if b["key"] == "sun")
            daylight[lon] = {"date": date, "minutes": planetary["day_hour_minutes"] * 12, "sun": sun,
                             "sunrise": planetary["sunrise"]["local_time"], "sunset": planetary["sunset"]["local_time"]}
    with backend_on_path():
        from app.core.antiscia import compute_antiscia
        from app.core.trace import Trace
        lilly = compute_antiscia([{"key": "saturn", "name": "土星", "longitude": LILLY_SATURN}], Trace())
    return {"tropical": tropical, "sidereal": sidereal, "daylight": daylight,
            "lilly": (lilly["antiscia"][0]["longitude"], lilly["contra_antiscia"][0]["longitude"])}


def _check(data: dict) -> float:
    """The product's points are the mirrors the article states; returns the ayanamsa they imply."""
    for name in ("tropical", "sidereal"):
        chart = data[name]
        for key in PLANET_KEYS:
            if not _close(chart["antiscia"][key] + chart["contra"][key], 180 + 360):
                if not _close(chart["contra"][key], chart["antiscia"][key] + 180):
                    raise RuntimeError(f"{name} {key}: the contra-antiscion is not opposite the antiscion")
    tropical, sidereal = data["tropical"], data["sidereal"]
    for key in PLANET_KEYS:
        if not _close(tropical["antiscia"][key], 180 - tropical["bodies"][key]):
            raise RuntimeError(f"{key}: the tropical antiscion is not 180° minus the longitude")
        if not _close(tropical["contra"][key], 360 - tropical["bodies"][key]):
            raise RuntimeError(f"{key}: the tropical contra-antiscion is not 360° minus the longitude")
    ayanamsa = (tropical["bodies"]["sun"] - sidereal["bodies"]["sun"]) % 360
    for key in PLANET_KEYS:
        if not _close(sidereal["antiscia"][key], tropical["antiscia"][key] - ayanamsa):
            raise RuntimeError(f"{key}: the sidereal antiscion is not the tropical one less the ayanamsa")
    antiscion, contra = data["lilly"]
    if zodiacal_minutes(antiscion) != "金牛 9°25′" or zodiacal_minutes(contra) != "天蠍 9°25′":
        raise RuntimeError(f"Lilly's Saturn now mirrors to {zodiacal_minutes(antiscion)} / {zodiacal_minutes(contra)}")
    return ayanamsa


# --- figure 1: the wheel -------------------------------------------------------------

def _polar(cx: float, cy: float):
    """Aries 0° on the left, the signs counterclockwise, as the result page's wheel."""
    return lambda longitude, r: _fx.wheel_point(cx, cy, r, 180 + longitude)


def _spread(longitudes: dict[str, float], gap: float) -> dict[str, float]:
    """Display angles for marks so that none sits closer than `gap` degrees to another."""
    order = sorted(longitudes, key=lambda key: longitudes[key] % 360)
    shown = {key: longitudes[key] % 360 for key in order}
    for _ in range(40):
        moved = False
        for a, b in zip(order, order[1:] + order[:1]):
            d = (shown[b] - shown[a]) % 360
            if d < gap:
                push = (gap - d) / 2
                shown[a] -= push
                shown[b] += push
                moved = True
        if not moved:
            break
    return shown


def _wheel(layout: str, fid: str, chart: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, cx, cy, r_sign, r_in, r_planet, r_mirror, mark = 600, 300.0, 300.0, 250.0, 212.0, 184.0, 146.0, 15.0
    else:
        H, cx, cy, r_sign, r_in, r_planet, r_mirror, mark = 440, 170.0, 198.0, 152.0, 126.0, 108.0, 82.0, 11.0
    at = _polar(cx, cy)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.circle(cx, cy, r_sign, "fx-wh-ring") + _fx.circle(cx, cy, r_in, "fx-lens"))
    out.append(_fx.circle(cx, cy, r_mirror, "fx-hair"))
    for sign in range(12):
        (sx, sy), (ex, ey) = at(30.0 * sign, r_in), at(30.0 * sign, r_sign)
        out.append(_fx.line(sx, sy, ex, ey, "fx-hair"))
        gx, gy = at(30.0 * sign + 15, (r_in + r_sign) / 2)
        out.append(_fx.glyph(SIGN_KEYS[sign], gx, gy, 20 if wide else 14, "fx-mk-gl"))
    planets = _spread(chart["bodies"], 11 if wide else 13)
    for key, label in VARIANTS:
        body = []
        mirrors = chart["antiscia"] if key == "antiscia" else chart["contra"]
        axis = (90.0, 270.0) if key == "antiscia" else (0.0, 180.0)
        (ax, ay), (bx, by) = at(axis[0], r_sign + 8), at(axis[1], r_sign + 8)
        body.append(_fx.line(ax, ay, bx, by, "fx-axis"))
        names = ("0° 巨蟹", "0° 摩羯") if key == "antiscia" else ("0° 牡羊", "0° 天秤")
        for lon, name in zip(axis, names):
            if lon == 0.0:  # Aries, on the left: the label sits above the axis, inside the plate
                tx, ty, anchor = 14.0, cy - 14, "start"
            elif lon == 180.0:
                tx, ty, anchor = (cx + r_sign + 14, cy + 5, "start") if wide else (W - 14.0, cy - 14, "end")
            else:
                tx, ty = at(lon, r_sign + (22 if wide else 16))
                ty, anchor = ty + 5, "middle"
            body.append(_fx.text(tx, ty, bound.num(name), "fx-t fx-small fx-key", anchor))
        shown = _spread(mirrors, 11 if wide else 13)
        for planet in PLANET_KEYS:
            (px, py), (qx, qy) = at(planets[planet], r_planet), at(shown[planet], r_mirror)
            body.append(f'<g class="fx-row" data-fx-key="{planet}">' + _fx.line(px, py, qx, qy, "fx-leader")
                        + _fx.circle(qx, qy, mark * 0.8, "fx-mk") + _fx.glyph(planet, qx, qy, mark, "fx-mk-gl")
                        + "</g>")
        if wide:
            body.append(_fx.text(570, 64, label, "fx-t fx-key"))
        out.append(_fx.variant_group(key, VARIANTS[0][0], "".join(body)))
    for planet in PLANET_KEYS:
        x, y = at(planets[planet], r_planet)
        sentence = f"{PLANETS[planet]}，{zodiacal_minutes(chart['bodies'][planet])}"
        out.append(f'<g class="fx-row" data-fx-key="{planet}" tabindex="0" aria-label="{bound.num(sentence)}">'
                   + _fx.circle(x, y, mark + 7, "fx-hit") + _fx.circle(x, y, mark, "fx-mk-on")
                   + _fx.glyph(planet, x, y, mark * 1.25, "fx-mk-gl-on") + "</g>")
    if wide:
        lines = (("實心圓：出生時的行星", "fx-t fx-small"), ("內圈空心圓：它的鏡射點", "fx-t fx-small"),
                 ("粗線：鏡射軸", "fx-t fx-small"), ("點一顆行星，看它和鏡射點", "fx-t fx-small fx-dim"))
        for i, (text, cls) in enumerate(lines):
            out.append(_fx.text(570, 110 + i * 28, text, cls))
    else:
        out.append(_fx.text(16, H - 40, "實心：行星　空心：鏡射點", "fx-t fx-small"))
        out.append(_fx.text(16, H - 18, "粗線：鏡射軸", "fx-t fx-small fx-dim"))
    out.append("</svg>")
    return "".join(out)


def _wheel_notes(chart: dict, bound: _fx.Bound) -> list[_fx.Note]:
    notes = []
    for planet in PLANET_KEYS:
        lon = bound.num(zodiacal_minutes(chart["bodies"][planet]))
        anti = bound.num(zodiacal_minutes(chart["antiscia"][planet]))
        contra = bound.num(zodiacal_minutes(chart["contra"][planet]))
        notes.append(_fx.Note(planet, "antiscia",
                              f"{PLANETS[planet]}在{lon}，對 0° 巨蟹—0° 摩羯這條軸鏡射，反照點在{anti}。"))
        notes.append(_fx.Note(planet, "contra",
                              f"{PLANETS[planet]}在{lon}，對 0° 牡羊—0° 天秤這條軸鏡射，反向反照點在{contra}，"
                              f"正好是反照點{anti}的對面。"))
    return notes


def _wheel_table(chart: dict, bound: _fx.Bound) -> str:
    rows = [f'<tr data-fx-key="{p}"><th scope="row">{PLANETS[p]}</th>'
            f'<td class="n">{bound.num(zodiacal_minutes(chart["bodies"][p]))}</td>'
            f'<td class="n">{bound.num(zodiacal_minutes(chart["antiscia"][p]))}</td>'
            f'<td class="n">{bound.num(zodiacal_minutes(chart["contra"][p]))}</td></tr>' for p in PLANET_KEYS]
    return _fx.data_table(("行星", "出生時的位置", "反照點", "反向反照點"), rows)


# --- figure 2: daylight ---------------------------------------------------------------

def _hours_minutes(minutes: float) -> str:
    total = round(minutes)
    return f"{total // 60} 小時 {total % 60:02d} 分"


def _daylight(layout: str, fid: str, daylight: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, x0, x1, y0, y1 = 400, 90.0, 850.0, 60.0, 300.0
    else:
        H, x0, x1, y0, y1 = 400, 46.0, 326.0, 60.0, 290.0
    points = sorted((lon, value) for lon, value in daylight.items() if lon not in LILLY_PAIR or lon % 10 == 0)
    low = min(value["minutes"] for _, value in points)
    high = max(value["minutes"] for _, value in points)
    floor, ceiling = 60 * int(low // 60), 60 * (int(high // 60) + 1)
    x = lambda lon: x0 + lon / 360 * (x1 - x0)  # noqa: E731
    y = lambda minutes: y1 - (minutes - floor) / (ceiling - floor) * (y1 - y0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.line(x0, y1, x1, y1, "fx-axis") + _fx.line(x0, y0, x0, y1, "fx-axis"))
    for hour in range(floor // 60, ceiling // 60 + 1):
        yy = y(hour * 60)
        out.append(_fx.line(x0 - 4, yy, x1, yy, "fx-hair"))
        out.append(_fx.text(x0 - 8, yy + 5, bound.scale(f"{hour}") + ("小時" if wide else ""), "fx-t fx-small", "end"))
    for sign in range(12):
        gx = x(30 * sign + 15)
        out.append(_fx.line(x(30 * sign), y1, x(30 * sign), y1 + 6, "fx-axis"))
        if wide or sign % 1 == 0:
            out.append(_fx.glyph(SIGN_KEYS[sign], gx, y1 + 22, 16 if wide else 12, "fx-mk-gl"))
    # the mirror axis: 0° Cancer
    out.append(_fx.line(x(90), y0 - 10, x(90), y1, "fx-dash"))
    out.append(_fx.text(x(90), y0 - 16, bound.num("0° 巨蟹（鏡射軸）") if wide else bound.num("0° 巨蟹"),
                        "fx-t fx-small", "middle"))
    out.append(_fx.line(x(270), y0 - 10, x(270), y1, "fx-dash"))
    d = "M" + " L".join(f"{_fx.f(x(lon))} {_fx.f(y(value['minutes']))}" for lon, value in points)
    out.append(_fx.path(d, "fx-curve"))
    (a, b) = (daylight[LILLY_PAIR[0]], daylight[LILLY_PAIR[1]])
    ya = y(a["minutes"])
    out.append(_fx.line(x(LILLY_PAIR[0]), ya, x(LILLY_PAIR[1]), ya, "fx-leader"))
    for lon, value in ((LILLY_PAIR[0], a), (LILLY_PAIR[1], b)):
        out.append(_fx.circle(x(lon), y(value["minutes"]), 6 if wide else 5, "fx-mk-on"))
    label_a = f"金牛 10°：{_hours_minutes(a['minutes'])}"
    label_b = f"獅子 20°：{_hours_minutes(b['minutes'])}"
    if wide:
        out.append(_fx.text(x(LILLY_PAIR[0]) + 4, ya + 28, bound.num(label_a), "fx-t fx-small fx-key", "start"))
        out.append(_fx.text(x(LILLY_PAIR[1]) - 4, ya + 52, bound.num(label_b), "fx-t fx-small fx-key", "end"))
        out.append(_fx.text(x0, H - 22, "橫軸：太陽所在的黃經（星座）　縱軸：臺北從日出到日落的時數", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(16, H - 46, bound.num(label_a), "fx-t fx-small"))
        out.append(_fx.text(16, H - 24, bound.num(label_b), "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)


def _daylight_table(daylight: dict, bound: _fx.Bound) -> str:
    rows = []
    for lon in sorted(lon for lon in daylight if lon % 30 == 10 or lon in LILLY_PAIR):
        value = daylight[lon]
        date = value["date"]
        rows.append(f'<tr><th scope="row">{bound.num(zodiacal_minutes(lon))}</th>'
                    f'<td class="n">{bound.num(f"{date.month}/{date.day}")}</td>'
                    f'<td class="n">{bound.num(value["sunrise"].split(" ")[1][:5])}</td>'
                    f'<td class="n">{bound.num(value["sunset"].split(" ")[1][:5])}</td>'
                    f'<td class="n">{bound.num(_hours_minutes(value["minutes"]))}</td></tr>')
    return _fx.data_table((f"太陽位置", f"{bound.num(str(YEAR))} 年臺北日期", "日出", "日落", "白天長度"), rows)


def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    ayanamsa = _check(data)
    chart, sidereal = data["tropical"], data["sidereal"]
    bound = _fx.Bound()
    wheel = _fx.figure(
        fid="fig-antiscia-wheel",
        hero=True,
        title="示範盤七顆行星與它們的反照點、反向反照點",
        caption=(f"<b>{bound.label('圖 1')}</b>示範盤（{bound.num('1990')} 年 {bound.num('5')} 月 {bound.num('15')} 日 "
                 f"{bound.num('14:30')} 臺北，合成資料）的七顆行星（實心圓）與它們的鏡射點（內圈空心圓）。"
                 "反照點對 0° 巨蟹—0° 摩羯這條至點軸鏡射，反向反照點對 0° 牡羊—0° 天秤這條分點軸鏡射。"
                 "按鈕切換兩種；點一顆行星或用鍵盤移到它，下方寫出它的位置與鏡射點。"
                 "沒有開啟指令碼時顯示反照點。圓點擠在一起時稍微錯開畫，確切位置見表格。"),
        art=_fx.FigureArt.drawn(_wheel, "fig-antiscia-wheel", chart, bound,
                                notes=_wheel_notes(chart, bound),
                                idle="點一顆行星（或用 Tab 鍵移到它），這裡會寫出它的位置與鏡射點。"),
        controls=_fx.FigureControls(variants=VARIANTS, switch_label="反照點或反向反照點"),
        table=_wheel_table(chart, bound),
        bound=bound,
    )
    daylight = data["daylight"]
    a, b = daylight[LILLY_PAIR[0]], daylight[LILLY_PAIR[1]]
    curve = _fx.figure(
        fid="fig-antiscia-daylight",
        title="臺北的白天長度隨太陽黃經變化，對 0° 巨蟹左右對稱",
        caption=(f"<b>{bound.label('圖 2')}</b>臺北在 {bound.num(str(YEAR))} 年，太陽每走到一個整十度那天，從日出到日落的長度"
                 "（本站計算服務的日出日落）。曲線對 0° 巨蟹（虛線）左右對稱：互為反照點的兩個位置，"
                 f"白天一樣長。實心圓是 Lilly 舉的例子，{bound.num('金牛 10°')}與{bound.num('獅子 20°')}。"),
        art=_fx.FigureArt.drawn(_daylight, "fig-antiscia-daylight", daylight, bound),
        table=_daylight_table(daylight, bound),
        bound=bound,
    )
    sun = chart["bodies"]["sun"]
    naive = (180 - sidereal["bodies"]["sun"]) % 360
    difference = abs(round(a["minutes"]) - round(b["minutes"]))
    quoted = [
        f"太陽在{zodiacal_minutes(sun)}",
        f"反照點在{zodiacal_minutes(chart['antiscia']['sun'])}",
        f"反向反照點在{zodiacal_minutes(chart['contra']['sun'])}",
        f"金牛 10° 那天（{a['date'].month} 月 {a['date'].day} 日）白天 {_hours_minutes(a['minutes'])}",
        f"獅子 20° 那天（{b['date'].month} 月 {b['date'].day} 日）白天 {_hours_minutes(b['minutes'])}",
        f"相差 {difference} 分鐘" if difference else "到分鐘都相同",
        f"約 {ayanamsa:.1f}°",
        f"恆星黃道下太陽在{zodiacal_minutes(sidereal['bodies']['sun'])}",
        f"反照點是{zodiacal_minutes(sidereal['antiscia']['sun'])}",
        f"直接拿 180° 去減，會得到{zodiacal_minutes(naive)}",
        f"差了約 {2 * ayanamsa:.0f}°",
    ]
    return {"fx-defs": _fx.defs(PLANET_KEYS + SIGN_KEYS), "antiscia-wheel": wheel, "antiscia-daylight": curve}, quoted
