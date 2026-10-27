"""〈站心月亮與地心月亮差多少〉: figures 1-2, table 1 and the numbers the prose quotes (figure 1: one day in Taipei,
2026-12-24, the Moon near perigee; figure 2: a schematic of the diurnal parallax; table 1: the product's two Moons at
four instants of that day against JPL Horizons).

The curve, the hourly steps and the 2026 statistics are Swiss Ephemeris with the repository's ephemeris files and the
product's flags (apparent, tropical, of date; FLG_TOPOCTR with the observer at the synthetic Taipei point, sea level).
The four instants of table 1 are the product's own answers with the Moon-only topocentric profile, and the hourly steps
are checked against them.  The Horizons values are pinned in `horizons_moon_taipei_2026.json` with the queries that
produced them; the generator does not go online.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path
import statistics

from . import _fx
from ._common import TAIPEI, calc_ut, product_charts, swiss
from ._demo import zodiacal_minutes

FRAGMENT = "blog-geocentric-vs-topocentric-moon"
PIN = Path(__file__).with_name("horizons_moon_taipei_2026.json")
DAY = (2026, 12, 24)
UTC_OFFSET = 8
DEFAULT_STEP = 18
STEP_MINUTES = 10

def _wrap(value: float) -> float:
    return ((value + 180) % 360) - 180

def _request(hour: int) -> dict:
    return {"datetime": {"year": DAY[0], "month": DAY[1], "day": DAY[2], "hour": hour, "minute": 0, "second": 0},
        "location": {"latitude": TAIPEI[0], "longitude": TAIPEI[1]},
        "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
        "options": {"house_system": "W", "include_houses": True, "moon_position_profile": "moon_only_topocentric_v1"}}

def _moon(swe, jd: float) -> tuple[float, float, float]:
    flags = swe.FLG_SWIEPH
    geo = calc_ut(swe, jd, swe.MOON, flags)
    topo = calc_ut(swe, jd, swe.MOON, flags | swe.FLG_TOPOCTR)
    altitude = swe.azalt(jd, swe.ECL2HOR, (TAIPEI[1], TAIPEI[0], 0.0), 0.0, 0.0, topo[:3])[1]
    return geo[0], topo[0], altitude

@functools.lru_cache(maxsize=1)
def answers() -> dict:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    with product_charts() as post:
        product = []
        for epoch in pin["epochs"]:
            parallax = post(_request(epoch["local_hour"]))["astronomical_data"]
            moon = parallax["parallax_moon"]
            product.append({"hour": epoch["local_hour"], "jd_et": parallax["time"]["jd_et"], "jd_ut": parallax["time"]["jd_ut"],
                "geo": moon["geocentric_reference"]["longitude"], "topo": moon["topocentric_effective"]["longitude"],
                "altitude": moon["topocentric_effective"]["altitude_true"], "delta": moon["longitude_delta_degrees"],
                "claim": moon["claim"], "paths": moon["effective_downstream_paths"]})
    with swiss() as swe:
        swe.set_topo(TAIPEI[1], TAIPEI[0], 0.0)
        start = swe.julday(DAY[0], DAY[1], DAY[2], 0) - UTC_OFFSET / 24
        curve = []
        for i in range(24 * 60 // STEP_MINUTES + 1):
            geo, topo, alt = _moon(swe, start + i * STEP_MINUTES / 1440)
            curve.append((i * STEP_MINUTES / 60, _wrap(topo - geo) * 60, alt))
        j0 = swe.julday(2026, 1, 1, 0)
        shifts, other = [], 0
        for i in range(365 * 24):
            geo, topo, _ = _moon(swe, j0 + i / 24)
            shifts.append(abs(_wrap(topo - geo)))
            other += int(geo // 30) != int(topo // 30)
        speed = calc_ut(swe, start + 0.5, swe.MOON, swe.FLG_SWIEPH | swe.FLG_SPEED)[3]
        check = [_moon(swe, p["jd_ut"]) for p in product]
    return {"pin": pin, "product": product, "curve": curve, "check": check, "speed": speed,
        "year": {"hours": len(shifts), "max": max(shifts), "median": statistics.median(shifts), "other": other}}

def _check(data: dict) -> None:
    for epoch, answer, (geo, topo, alt) in zip(data["pin"]["epochs"], data["product"], data["check"], strict=True):
        if abs(answer["jd_et"] - epoch["tt_jd"]) > 1e-8:
            raise RuntimeError(f"{answer['hour']} h: the product's TT is no longer the instant Horizons was asked for")
        if abs(_wrap(answer["geo"] - geo)) > 1e-9 or abs(_wrap(answer["topo"] - topo)) > 1e-9:
            raise RuntimeError(f"{answer['hour']} h: the generator's Swiss Moon is not the product's")
        if abs(answer["altitude"] - alt) > 1e-6:
            raise RuntimeError(f"{answer['hour']} h: the generator's altitude is not the product's")
        if answer["claim"] != "different_observer_origin_not_more_accurate":
            raise RuntimeError("the product's topocentric Moon now claims more than a different origin")
    peak = max(abs(d) for _, d, _ in data["curve"])
    if not 50 < peak < 64:
        raise RuntimeError(f"the day's largest shift {peak:.1f}′ no longer fits figure 1's scale")

def _arcsec(value_degrees: float) -> str:
    return f"{abs(value_degrees) * 3600:.2f}″"

# --- figure 1: one day --------------------------------------------------------------

def _hour(h: float) -> str:
    return f"{int(h):02d}:00"

def _day_art(layout: str, fid: str, data: dict, steps: list, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    if wide:
        W, H, L, R = _fx.WIDE, 470, 92.0, 852.0
        top_box, low_box = (64.0, 184.0), (250.0, 400.0)
    else:
        W, H, L, R = _fx.NARROW, 520, 50.0, 326.0
        top_box, low_box = (78.0, 194.0), (268.0, 432.0)
    X = lambda h: L + (R - L) * h / 24  # noqa: E731
    Ya = lambda a: top_box[0] + (top_box[1] - top_box[0]) * (90 - a) / 180  # noqa: E731
    Yd = lambda d: low_box[0] + (low_box[1] - low_box[0]) * (64 - d) / 128  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    small = "fx-t fx-small"
    out.append(_fx.text(L if wide else 14, 36 if wide else 28, "月亮在臺北的地平高度", "fx-t"))
    if not wide:
        out.append(_fx.text(14, 48, bound.label("2026 年 12 月 24 日，臺北時間"), "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(R, 36, bound.label("2026 年 12 月 24 日，臺北時間"), "fx-t fx-small fx-dim", "end"))
    for a in (-90, 0, 90):
        out.append(_fx.line(L, Ya(a), R, Ya(a), "fx-axis" if a == 0 else "fx-hair"))
        out.append(_fx.text(L - 8, Ya(a) + 5, bound.scale(f"{a}°".replace("-", "−")), "fx-t fx-small fx-num", "end"))
    out.append(_fx.text(R - 6, Ya(0) - 8, "地平線", "fx-t fx-small fx-dim", "end"))
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(h))} {_fx.f(Ya(a))}" for h, _, a in data["curve"]), "fx-curve"))
    title_y = low_box[0] - (26 if wide else 30)
    out.append(_fx.text(L if wide else 14, title_y, "站心月亮減地心月亮的黃經（角分）", "fx-t" if wide else "fx-t fx-small"))
    for d in (-60, -30, 0, 30, 60):
        if not wide and d in (-30, 30):
            out.append(_fx.line(L, Yd(d), R, Yd(d), "fx-hair"))
            continue
        out.append(_fx.line(L, Yd(d), R, Yd(d), "fx-axis" if d == 0 else "fx-hair"))
        label = "0′" if d == 0 else f"{'+' if d > 0 else '−'}{abs(d)}′"
        out.append(_fx.text(L - 8, Yd(d) + 5, bound.scale(label), "fx-t fx-small fx-num", "end"))
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(h))} {_fx.f(Yd(d))}" for h, d, _ in data["curve"]), "fx-curve"))
    for h in ((0, 6, 12, 18, 24) if wide else (0, 6, 12, 18, 24)):
        out.append(_fx.line(X(h), low_box[1], X(h), low_box[1] + 6, "fx-axis"))
        anchor = "start" if h == 0 and not wide else "end" if h == 24 and not wide else "middle"
        out.append(_fx.text(X(h), low_box[1] + 24, bound.scale(f"{h:02d}:00"), "fx-t fx-small fx-num", anchor))
    for i, step in enumerate(steps):
        x = X(step["hour"])
        body = (_fx.line(x, top_box[0] - 4, x, low_box[1], "fx-cursor") + _fx.circle(x, Ya(step["altitude"]), 6 if wide else 5,
            "fx-cursor") + _fx.circle(x, Yd(step["shift"]), 6 if wide else 5, "fx-cursor"))
        out.append(_fx.step_group(i, DEFAULT_STEP, body))
    out.append(_fx.text(L if wide else 14, H - 18, "直線：拖拉條選的整點" if wide else "直線：拖拉條選的整點", small + " fx-dim"))
    out.append("</svg>")
    return "".join(out)

def _step_sentence(step: dict, bound: _fx.Bound) -> str:
    where = "地平線上" if step["altitude"] >= 0 else "地平線下"
    shift = step["shift"]
    if abs(shift) < 0.5:
        change = "兩者幾乎相同"
    else:
        change = f"站心月亮比地心月亮{'多' if shift > 0 else '少'} {bound.num(f'{abs(shift):.0f}')} 角分"
    return (f"{bound.num(_hour(step['hour']))}：月亮在{where} {bound.num(f'{abs(step['altitude']):.0f}')}°，" f"{change}。")

def _figure_day(data: dict) -> str:
    bound = _fx.Bound()
    steps = [{"hour": h, "shift": d, "altitude": a} for h, d, a in data["curve"] if h == int(h)]
    notes = [_fx.Note(None, None, _step_sentence(step, bound), step=i) for i, step in enumerate(steps)]
    peak = max(data["curve"], key=lambda item: abs(item[1]))
    rows = [f'<tr><th scope="row">{bound.num(_hour(s["hour"]))}</th><td class="n">{bound.num(f"{s['altitude']:.1f}°")}</td>'
            f'<td class="n">{bound.num(f"{s['shift']:+.1f}′".replace("-", "−"))}</td></tr>' for s in steps]
    table = _fx.data_table(("臺北時間", "月亮高度", "站心減地心（角分）"), rows)
    caption = (f"<b>{bound.label('圖 1')}</b>合成範例：{bound.label('2026 年 12 月 24 日')}，臺北，月亮接近近地點的一天。"
               f"上：月亮的地平高度；下：從臺北看（站心）的月亮黃經減去從地心看的，每 {bound.label('10')} 分鐘一點。"
               "月亮貼近地平線時差最大，在頭頂附近時最小；"
               f"這一天最大差 {bound.num(f'{abs(peak[1]):.0f}')} 角分。拖拉條每次移動一個整點，說明列寫出那一刻的高度與差"
               f"<a class=\"ar-cite\" href=\"#ref-4\">{bound.label('[4]')}</a>。")
    return _fx.figure(
        fid="fig-moon-day",
        hero=True,
        title="臺北一天裡，月亮的高度與站心、地心黃經的差",
        caption=caption,
        art=_fx.FigureArt.drawn(_day_art, "fig-moon-day", data, steps, bound, notes=notes,
                                idle="拖拉選一個整點，這裡會寫出那一刻月亮的高度與兩種月亮的差。"),
        controls=_fx.FigureControls(steps=len(steps), default_step=DEFAULT_STEP, scrub_label="臺北時間"),
        table=table,
        bound=bound,
    )

# --- figure 2: the schematic ---------------------------------------------------------

def _parallax_art(layout: str, fid: str) -> str:
    wide = layout == "fx-wide"
    W, H = (_fx.WIDE, 340) if wide else (_fx.NARROW, 400)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    small = "fx-t fx-small"
    if wide:
        ex, ey, er = 170.0, 200.0, 86.0
        mx, my = 560.0, 112.0
        far = 852.0
    else:
        ex, ey, er = 82.0, 250.0, 54.0
        mx, my = 230.0, 150.0
        far = 326.0
    ox, oy = ex + er * 0.5, ey - er * 0.866
    out.append(_fx.text(24 if wide else 14, 36 if wide else 28, "示意圖，不按比例", "fx-t fx-small fx-dim"))
    out.append(_fx.circle(ex, ey, er, "fx-plane"))
    out.append(_fx.circle(ex, ey, 4, "fx-disc"))
    out.append(_fx.text(ex, ey + 22, "地心", small, "middle"))
    out.append(_fx.circle(ox, oy, 5, "fx-disc"))
    out.append(_fx.text(ox - 10, oy - 12, "出生地", small, "end"))
    def extend(x0, y0):
        t = (far - x0) / (mx - x0)
        return x0 + (mx - x0) * t, y0 + (my - y0) * t
    gx, gy = extend(ex, ey)
    tx, ty = extend(ox, oy)
    out.append(_fx.line(ex, ey, gx, gy, "fx-dash"))
    out.append(_fx.line(ox, oy, tx, ty, "fx-axis"))
    out.append(_fx.circle(mx, my, 12 if wide else 9, "fx-mk"))
    out.append(_fx.text(mx, my - (20 if wide else 16), "月亮", small, "middle"))
    out.append(_fx.line(far - 2, gy, far - 2, ty, "fx-axis"))
    if wide:
        out.append(_fx.text(far - 10, min(gy, ty) - 10, "背景上的兩個方向", small, "end"))
        out.append(_fx.text(far - 10, max(gy, ty) + 24, "這段夾角就是視差", small, "end"))
        out.append(_fx.text(320, H - 46, "虛線：從地球中心看月亮（地心）", small))
        out.append(_fx.text(320, H - 22, "實線：從地表的出生地看月亮（站心）", small))
    else:
        out.append(_fx.text(far - 6, min(gy, ty) - 10, "夾角就是視差", small, "end"))
        out.append(_fx.text(14, H - 46, "虛線：從地球中心看（地心）", small))
        out.append(_fx.text(14, H - 24, "實線：從出生地看（站心）", small))
    out.append("</svg>")
    return "".join(out)

def _figure_parallax() -> str:
    bound = _fx.Bound()
    return _fx.figure(
        fid="fig-moon-parallax",
        title="示意圖：從地心與從地表看同一個月亮，方向不同",
        caption=(f"<b>{bound.label('圖 2')}</b>示意圖，不按比例。站在地表的出生地與地球中心相距一個地球半徑；"
                 "從兩處看同一個月亮，視線指向背景上的兩個不同位置，夾角就是周日視差。"
                 "月亮離地球近，這個角比行星大得多。月亮在頭頂時兩條視線幾乎重合，"
                 "貼近地平線時夾角最大。"),
        art=_fx.FigureArt.drawn(_parallax_art, "fig-moon-parallax"),
        bound=bound,
    )

# --- table 1: the product against JPL Horizons ---------------------------------------

def _horizons_rows(data: dict) -> str:
    out = []
    for epoch, p in zip(data["pin"]["epochs"], data["product"], strict=True):
        shift = p["delta"] * 60
        altitude = f"{p['altitude']:.1f}°".replace("-", "−")
        out.append(
            f'          <tr><th scope="row">{_hour(p["hour"])}</th><td class="n">{altitude}</td>'
            f'<td class="n">{zodiacal_minutes(p["geo"])}</td><td class="n">{zodiacal_minutes(p["topo"])}</td>'
            f'<td class="n">{"+" if shift > 0 else "−"}{abs(shift):.1f}′</td>'
            f'<td class="n">{_arcsec(_wrap(p["geo"] - epoch["geocentric_longitude"]))}</td>'
            f'<td class="n">{_arcsec(_wrap(p["topo"] - epoch["topocentric_longitude"]))}</td></tr>')
    return "\n".join(out)

def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    _check(data)
    year = data["year"]
    worst = max(max(abs(_wrap(p["geo"] - e["geocentric_longitude"])), abs(_wrap(p["topo"] - e["topocentric_longitude"])))
                for e, p in zip(data["pin"]["epochs"], data["product"], strict=True))
    biggest = max(data["product"], key=lambda p: abs(p["delta"]))
    quoted = [f"<b>{year['max']:.2f}°</b><span>2026 年在臺北，站心與地心月亮黃經的最大差",
        f"<b>{year['median'] * 60:.0f}′</b><span>差的中位數",
        f"<b>{year['other'] / year['hours'] * 100:.1f}%</b><span>的時間",
        f"<b>{worst * 3600:.1f}″</b><span>本站兩種月亮與 JPL Horizons 的最大差",
        f"約 {year['other'] / year['hours'] * 365:.1f} 天", f"月亮一小時約走 {data['speed'] / 24 * 60:.0f} 角分",
        f"最大差 {year['max']:.2f} 度", f"中位數約 {year['median'] * 60:.0f} 角分",
        f"站心月亮比地心月亮{'多' if biggest['delta'] > 0 else '少'} {abs(biggest['delta']) * 60:.0f} 角分",
        f"{len(data['product'][0]['paths'])} 個地方"]
    return {"fx-defs": _fx.defs(()), "moon-day": _figure_day(data), "moon-parallax": _figure_parallax(),
            "horizons": _horizons_rows(data)}, quoted
