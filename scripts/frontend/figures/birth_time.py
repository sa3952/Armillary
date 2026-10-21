"""〈出生時間差五分鐘〉: figure 1 (the ascendant across one hour, a slider over
the product's answers every five minutes), figure 2 (five minutes of motion of
the Sun, the Moon and the ascendant on one scale) and figure 3 (how long each
sign takes to rise at Taipei's and London's latitude), with the numbers the
prose quotes.

Synthetic instant only: 1990-05-15, Taipei 25.05306N 121.52639E, UTC+8 (no
daylight saving that year), the same instant as the home page demonstration.
The slider's instants, the five sampled instants and the crossing window are
the product's own answers; the curve, the five-minute motion and the rising
times are Swiss Ephemeris read directly, and the product's ascendant at every
slider instant must lie on that curve.
"""
from __future__ import annotations

import math
from typing import Any

from . import _fx
from ._common import SIGNS, TAIPEI, calc_ut, hms as _hms, product_charts, sign_degree_minute, swiss


FRAGMENT = "blog-birth-time-sensitivity"
LAT, LON = TAIPEI
# The article's second latitude (London); a sign's rising time depends on the
# latitude and the obliquity, not on the longitude.
LONDON = (51.5, -0.1275)
DEMO: dict[str, Any] = {
    "datetime": {"year": 1990, "month": 5, "day": 15, "hour": 14, "minute": 0, "second": 0},
    "location": {"latitude": LAT, "longitude": LON},
    "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
    "options": {"house_system": "W", "include_houses": True},
}
# The slider: every five minutes from 14:00, and the hour's last second, the
# product's own last sample.
STEPS = [(14, m, 0) for m in range(0, 60, 5)] + [(14, 59, 59)]
DEFAULT_STEP = 6  # 14:30
# This module reads the clock as UT1 = UTC, while the product converts UTC
# with swe_utc_to_jd (UT1 = TT − Swiss ΔT, 0.079 s later here), so the
# product's ascendant is about 1.1″ ahead of the curve: invisible, and checked.
ON_CURVE_ARCSEC = 3.0
CLASSICAL = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
GLYPHS = ("sun", "moon", "aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio",
          "sagittarius", "capricorn", "aquarius", "pisces")
SIGN_KEYS = GLYPHS[2:]


def _clock(local: str) -> tuple[int, int, int]:
    """'1990-05-15T14:22:58' or '1990-05-15 14:22:58.000' -> (14, 22, 58)."""
    date, _, time = local.replace("T", " ").partition(" ")
    if date != "1990-05-15":
        raise RuntimeError(f"a sample left the day: {local}")
    h, m, s = time.split(".")[0].split(":")
    return int(h), int(m), int(s)


def _hm(clock: tuple[int, int, int]) -> str:
    return _hms(clock) if clock[2] else f"{clock[0]:02d}:{clock[1]:02d}"


def _minutes(clock: tuple[int, int, int]) -> float:
    return (clock[0] - 14) * 60 + clock[1] + clock[2] / 60


def _dm(longitude: float) -> tuple[str, str]:
    """(sign, 「0°49′」) rounded to the whole arcminute."""
    sign, degree, minute = sign_degree_minute(longitude)
    return sign, f"{degree}°{minute:02d}′"


def _product() -> dict:
    """The product's sampling of the hour, and its chart at every slider instant."""
    with product_charts() as post:
        hour = post({**DEMO, "birth_time_precision": "approximate_hour"})["birth_time_sensitivity"]
        (transition,) = hour["transitions"]
        probes = [_clock(p["input_local_time"]) for p in hour["probes"]]
        steps = []
        for h, m, s in STEPS:
            chart = post({**DEMO, "birth_time_precision": "exact",
                          "datetime": {**DEMO["datetime"], "hour": h, "minute": m, "second": s}})
            houses = {p["key"]: p["house"] for p in chart["derived_methods"]["planet_in_house"]["placements"]}
            steps.append({"clock": (h, m, s), "asc": chart["astronomical_data"]["angles"]["asc"],
                          "houses": {key: houses[key] for key in CLASSICAL}})
    if not set(probes) <= set(STEPS):
        raise RuntimeError(f"the product's samples {probes} are not all slider instants")
    return {"probes": probes, "steps": steps,
            "crossing": (_clock(transition["lower_bound_local"]), _clock(transition["upper_bound_local"])),
            "width": transition["resolution_seconds"]}


def _rising(swe, lat: float, lon: float) -> dict[int, float]:
    """Minutes each sign takes to rise: scan 24 h from local 0:00 in 10 s steps."""
    def asc(j):
        return swe.houses_ex(j, lat, lon, b"W")[1][0]

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
    return rising


def _data(swe) -> dict:
    def jd(h, m, s=0):  # local clock, UTC+8
        return swe.julday(1990, 5, 15, (h - 8) + m / 60 + s / 3600)

    def asc(j):
        return swe.houses_ex(j, LAT, LON, b"W")[1][0]

    out: dict = {"asc_at": lambda clock: asc(jd(*clock))}
    out["asc_per_minute"] = [[m, asc(jd(14, 0) + m / 1440)] for m in range(0, 61)]
    out["rising_minutes"] = _rising(swe, LAT, LON)
    out["london_minutes"] = _rising(swe, *LONDON)
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
    return out


def _check(d: dict, p: dict) -> None:
    """The product's slider instants lie on the curve, and its crossing window
    holds the ephemeris' crossing of Libra 0°."""
    for step in p["steps"]:
        own = d["asc_at"](step["clock"])
        gap = ((step["asc"] - own + 180) % 360 - 180) * 3600
        if abs(gap) > ON_CURVE_ARCSEC:
            raise RuntimeError(f"product ascendant at {_hms(step['clock'])} is {gap:.1f}″ off the curve")
    (lower, upper) = p["crossing"]
    before, after = d["asc_at"](lower), d["asc_at"](upper)
    if not before < 180 <= after:
        raise RuntimeError(f"the ascendant does not cross 180° between {p['crossing']}: {before}, {after}")


# --- figure 1: the hour, with a slider -----------------------------------------

YMIN, YMAX = 174.0, 189.0


def _step_sentence(step: dict, probe: bool, bound: _fx.Bound) -> str:
    sign, dm = _dm(step["asc"])
    clock = bound.num(_hm(step["clock"]))
    sun = bound.num(str(step["houses"]["sun"]))
    moon = bound.num(str(step["houses"]["moon"]))
    text = (f"{clock}：上升點在{sign}座 {bound.num(dm)}。整宮制下{sign}座是第一宮，"
            f"太陽在第 {sun} 宮、月亮在第 {moon} 宮。")
    return text + ("這是本站實際取樣的五個時刻之一。" if probe else "")


def _hour(layout: str, fid: str, d: dict, p: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        L, R, T, B = 84.0, 840.0, 78.0, 330.0
    else:
        L, R, T, B = 46.0, 326.0, 74.0, 290.0
    H = B + (78 if wide else 70)
    X = lambda m: L + (R - L) * m / 60  # noqa: E731
    Y = lambda v: B - (B - T) * (v - YMIN) / (YMAX - YMIN)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(L if wide else 14, 34 if wide else 28, "上升點在星座內的度數", "fx-t fx-small fx-dim"))
    out.append(_fx.rect(L, T, R - L, Y(180) - T, "fx-fill-dot"))
    out.append(_fx.rect(L, T, R - L, B - T, "fx-inset-frame"))
    for m in (15, 30, 45):
        out.append(_fx.line(X(m), T, X(m), B, "fx-hair"))
    labels = (0, 15, 30, 45, 60) if wide else (0, 30, 60)
    for m in labels:
        text = bound.scale(f"14:{m:02d}" if m < 60 else "15:00")
        anchor = "start" if m == 0 and not wide else "end" if m == 60 and not wide else "middle"
        out.append(_fx.text(X(m), B + 24, text, "fx-t fx-small fx-num", anchor))
    for v in (175, 180, 185):
        deg = v - 150 if v < 180 else v - 180
        out.append(_fx.text(L - 8, Y(v) + 5, bound.scale(f"{deg}°"), "fx-t fx-small fx-num", "end"))
    out.append(_fx.line(L, Y(180), R, Y(180), "fx-axis"))
    out.append(_fx.text(L + 10, T + 24, "天秤座", "fx-t fx-key"))
    out.append(_fx.text(R - 10, B - 12, "處女座", "fx-t fx-key", "end"))
    (lower, upper) = p["crossing"]
    xc = X((_minutes(lower) + _minutes(upper)) / 2)
    out.append(_fx.line(xc, T, xc, B, "fx-sunline"))
    lo_t, hi_t = bound.num(_hms(lower)), bound.num(_hms(upper))
    out.append(_fx.text(xc - 8, T + 24, "跨界區間", "fx-t fx-small fx-key", "end"))
    out.append(_fx.text(xc - 8, T + 44, f"{lo_t}–", "fx-t fx-small fx-num fx-key", "end"))
    out.append(_fx.text(xc - 8, T + 64, hi_t, "fx-t fx-small fx-num fx-key", "end"))
    pts = d["asc_per_minute"]
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(m))} {_fx.f(Y(v))}" for m, v in pts), "fx-curve"))
    for probe in p["probes"]:
        step = next(s for s in p["steps"] if s["clock"] == probe)
        out.append(_fx.circle(X(_minutes(probe)), Y(step["asc"]), 5 if wide else 4.5, "fx-mk"))
    for i, step in enumerate(p["steps"]):
        x, y = X(_minutes(step["clock"])), Y(step["asc"])
        label = bound.num(_hm(step["clock"]))
        anchor = "start" if x - L < 30 else "end" if R - x < 30 else "middle"
        body = (_fx.line(x, T - 6, x, B, "fx-cursor") + _fx.circle(x, y, 8 if wide else 7, "fx-cursor")
                + _fx.text(x, T - 12, label, "fx-t fx-small fx-num fx-cursor-t", anchor))
        out.append(_fx.step_group(i, DEFAULT_STEP, body))
    legend_y = B + (56 if wide else 50)
    out.append(_fx.circle(L + 5, legend_y - 5, 5 if wide else 4.5, "fx-mk"))
    sample = "本站實際取樣的時刻（每 15 分鐘）" if wide else "本站實際取樣的時刻"
    out.append(_fx.text(L + 18, legend_y, sample.replace("15", bound.scale("15")), "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)


def _hour_table(p: dict, bound: _fx.Bound) -> str:
    rows = []
    for step in p["steps"]:
        sign, dm = _dm(step["asc"])
        mark = "（本站取樣）" if step["clock"] in p["probes"] else ""
        houses = "".join(f'<td class="n">{bound.num(str(step["houses"][key]))}</td>' for key in ("sun", "moon"))
        rows.append(f'<tr><th scope="row">{bound.num(_hm(step["clock"]))}{mark}</th>'
                    f'<td>{sign}座 {bound.num(dm)}</td>{houses}</tr>')
    return _fx.data_table(("時刻", "上升點", "太陽落宮", "月亮落宮"), rows)


def _hour_figure(d: dict, p: dict) -> str:
    bound = _fx.Bound()
    first, last = d["asc_per_minute"][0][1], d["asc_per_minute"][-1][1]
    (lower, upper) = p["crossing"]
    notes = [_fx.Note(None, None, _step_sentence(step, step["clock"] in p["probes"], bound), step=i)
             for i, step in enumerate(p["steps"])]
    caption = (
        f"<b>{bound.label('圖 1')}</b>合成範例（不是任何人的出生資料）：{bound.num('1990')} 年 {bound.num('5')} 月 "
        f"{bound.num('15')} 日下午兩點到三點，臺北。上升點在這一小時裡走了約 "
        f"{bound.num(f'{(last - first) % 360:.1f}')} 度，並在 {bound.num(_hms(lower))} 到 {bound.num(_hms(upper))} "
        "之間跨過處女座與天秤座的界線（虛線）。圓圈是本站實際取樣的五個時刻；直線標出的時刻可以用拖拉條每五分鐘移動一次，"
        "說明列寫出本站在那一刻算出的上升點與落宮。點狀底是天秤座。"
    )
    return _fx.figure(
        fid="fig-asc-hour",
        hero=True,
        title="一小時裡的上升點：從處女座走進天秤座",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _hour, "fig-asc-hour", d, p, bound,
            notes=notes,
            idle="拖拉選一個時刻，這裡會寫出那一刻的上升點與落宮。",
        ),
        controls=_fx.FigureControls(
            steps=len(p["steps"]),
            default_step=DEFAULT_STEP,
            scrub_label="時刻",
        ),
        table=_hour_table(p, bound),
        bound=bound,
    )


# --- figure 2: five minutes on one scale ---------------------------------------

RULER = 75.0  # arcminutes
LENS = 3.0    # arcminutes shown in the enlargement


def _arcmin_label(t: int) -> str:
    return f"{t // 60}°" + (f"{t % 60}′" if t % 60 else "") if t >= 60 else f"{t}′"


def _five(layout: str, fid: str, rows: list[tuple[str, str, float, str]], bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (260.0, 840.0) if wide else (14.0, 326.0)
    k = (x1 - x0) / RULER
    m = (x1 - x0) / LENS
    out = [_fx.svg_open(layout, W, 0, fid)]  # height patched below
    out.append(_fx.text(24 if wide else 14, 36 if wide else 28, "從 14:30 起的五分鐘，同一把尺".replace(
        "14:30", bound.num("14:30")), "fx-t fx-small fx-dim"))
    top = 64 if wide else 52
    rh = 48 if wide else 52
    th = 16 if wide else 14
    for i, (key, name, arcmin, value) in enumerate(rows):
        y = top + i * rh
        track = y + (rh - th) / 2 if wide else y + 26
        if wide:
            if key != "asc":
                out.append(_fx.glyph(key, 36, track + th / 2, 18, "fx-mk-gl"))
            out.append(_fx.text(56, track + th / 2 + 6, name, "fx-t"))
            out.append(_fx.text(x0 - 16, track + th / 2 + 6, bound.num(value), "fx-t fx-num", "end"))
        else:
            gx = 14
            if key != "asc":
                out.append(_fx.glyph(key, gx + 7, y + 11, 14, "fx-mk-gl"))
                gx += 20
            out.append(_fx.text(gx, y + 16, name, "fx-t"))
            out.append(_fx.text(x1, y + 16, bound.num(value), "fx-t fx-num", "end"))
        out.append(_fx.rect(x0, track, x1 - x0, th, "fx-track"))
        out.append(_fx.rect(x0, track, max(arcmin * k, 1.0), th, "fx-fill-solid"))
    bottom = top + len(rows) * rh
    axis = bottom + 6
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    for t in range(0, int(RULER) + 1, 15):
        out.append(_fx.line(x0 + t * k, axis, x0 + t * k, axis + 5, "fx-axis"))
        anchor = "start" if t == 0 else "end" if t == RULER else "middle"
        out.append(_fx.text(x0 + t * k, axis + 22, bound.scale(_arcmin_label(t)), "fx-t fx-small fx-num", anchor))
    # The enlargement: the first 3′ of the same scale, the Sun and the Moon.
    lens_top = top + 4 if wide else top + 26 - 4
    out.append(_fx.rect(x0 - 3, lens_top, LENS * k + 6, bottom - lens_top - 8, "fx-lens"))
    iy = axis + (64 if wide else 72)
    gap = 22 if wide else 34
    ih = 2 * (th + gap) + (8 if wide else 0)
    out.append(_fx.line(x0 - 3, bottom - 4, x0, iy, "fx-leader"))
    out.append(_fx.line(x0 + LENS * k + 3, bottom - 4, x1, iy, "fx-leader"))
    out.append(_fx.rect(x0, iy, x1 - x0, ih, "fx-fill-dot"))
    out.append(_fx.rect(x0, iy, x1 - x0, ih, "fx-inset-frame"))
    times = bound.scale(f"{round(m / k)}")
    out.append(_fx.text(x0 + 6 if not wide else 24, iy - 10 if not wide else iy + ih / 2 + 6,
                        f"放大 {times} 倍：前 {bound.scale(f'{LENS:g}′')}", "fx-t fx-small"))
    for j, (key, name, arcmin, value) in enumerate(rows[:2]):
        if wide:
            y = iy + 10 + j * (th + gap)
            out.append(_fx.text(x0 - 16, y + th - 2, f"{name} {value}", "fx-t fx-small fx-num", "end"))
        else:
            y = iy + 24 + j * (th + gap)
            out.append(_fx.text(x0 + 6, y - 6, f"{name} {value}", "fx-t fx-small fx-num fx-key"))
        out.append(_fx.rect(x0, y, x1 - x0, th, "fx-track"))
        out.append(_fx.rect(x0, y, arcmin * m, th, "fx-fill-solid"))
    for t in range(0, int(LENS) + 1):
        out.append(_fx.line(x0 + t * m, iy + ih, x0 + t * m, iy + ih + 5, "fx-axis"))
        anchor = "start" if t == 0 else "end" if t == LENS else "middle"
        out.append(_fx.text(x0 + t * m, iy + ih + 22, bound.scale(f"{t}′"), "fx-t fx-small fx-num", anchor))
    H = iy + ih + 40
    out[0] = _fx.svg_open(layout, W, H, fid)
    out.insert(1, _fx.plate(W, H))
    out.append("</svg>")
    return "".join(out)


def _five_figure(d: dict) -> str:
    bound = _fx.Bound()
    sun, moon, asc = d["move5_sun_arcmin"], d["move5_moon_arcmin"], d["move5_asc_deg"]
    rows = [("sun", "太陽", sun, f"{sun:.1f}′"), ("moon", "月亮", moon, f"{moon:.1f}′"),
            ("asc", "上升點", asc * 60, f"{asc:.2f}°")]
    for *_, value in rows:
        bound.num(value)
    caption = (
        f"<b>{bound.label('圖 2')}</b>{bound.label('圖 1')} 那張合成盤從 {bound.num('14:30')} 起的五分鐘裡，太陽、月亮與上升點各走了多遠，"
        f"畫在同一把尺上（單位是角分，{bound.scale('60 角分是 1 度')}）。太陽那一段短到幾乎看不見，下方把前 "
        f"{bound.scale(f'{LENS:g}')} 角分放大，才看得出太陽與月亮。由本站以 Swiss Ephemeris 自算。"
    )
    return _fx.figure(
        fid="fig-five-minutes",
        title="五分鐘裡太陽、月亮與上升點各走了多遠",
        caption=caption,
        art=_fx.FigureArt.drawn(_five, "fig-five-minutes", rows, bound),
        bound=bound,
    )


# --- figure 3: rising times, Taipei or London -----------------------------------

PAIRS = tuple((k, 11 - k) for k in range(6))  # Aries–Pisces … Virgo–Libra
EMPHASIS = (5, 6)  # the signs figure 1's hour passes through
VARIANTS = (("taipei", "臺北　北緯 25.05°"), ("london", "倫敦　北緯 51.5°"))
SCALE_MAX = 180


def _pair_key(pair: tuple[int, int]) -> str:
    return f"{SIGN_KEYS[pair[0]]}-{SIGN_KEYS[pair[1]]}"


def _rise(layout: str, fid: str, minutes: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (150.0, 740.0) if wide else (78.0, 272.0)
    k = (x1 - x0) / SCALE_MAX
    top, rh = (56.0, 30.0) if wide else (50.0, 27.0)
    bh = 16 if wide else 14
    bottom = top + 12 * rh
    H = bottom + (70 if wide else 66)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(x0, 36 if wide else 30, "每個星座從開始升起到整個升完的時間", "fx-t fx-small fx-dim"))
    for t in range(30, SCALE_MAX + 1, 30):
        out.append(_fx.line(x0 + t * k, top - 6, x0 + t * k, bottom, "fx-hair"))
    for pair in PAIRS:
        key = _pair_key(pair)
        names = "與".join(f"{SIGNS[s]}座" for s in pair)
        values = "，".join(f"{city}約 {bound.num(f'{minutes[v][pair[0]]:.0f}')} 分鐘"
                          for v, city in (("taipei", "臺北"), ("london", "倫敦")))
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{names}：{values}">')
        for s in pair:
            y = top + s * rh
            cy = y + rh / 2
            out.append(_fx.rect(8, y + 1, W - 16, rh - 2, "fx-hit"))
            out.append(_fx.glyph(SIGN_KEYS[s], (30 if wide else 22), cy, 15 if wide else 13, "fx-mk-gl"))
            out.append(_fx.text(48 if wide else 36, cy + 6 if wide else cy + 5, SIGNS[s], "fx-t"))
            fill = "fx-fill-solid" if s in EMPHASIS else "fx-fill-hatch"
            for variant, _ in VARIANTS:
                value = minutes[variant][s]
                text = bound.num(f"{value:.0f}") + " 分"
                body = _fx.rect(x0, cy - bh / 2, value * k, bh, "fx-track") + _fx.rect(x0, cy - bh / 2, value * k, bh, fill)
                if wide:
                    body += _fx.text(x0 + value * k + 10, cy + 6, text, "fx-t fx-small fx-num fx-key")
                else:
                    body += _fx.text(W - 14, cy + 5, text, "fx-t fx-small fx-num", "end")
                out.append(_fx.variant_group(variant, VARIANTS[0][0], body))
        out.append("</g>")
    axis = bottom + 6
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    step = 30 if wide else 60
    for t in range(0, SCALE_MAX + 1, step):
        out.append(_fx.line(x0 + t * k, axis, x0 + t * k, axis + 5, "fx-axis"))
        out.append(_fx.text(x0 + t * k, axis + 22, bound.scale(str(t)), "fx-t fx-small fx-num", "middle"))
    out.append(_fx.text((x0 + x1) / 2, axis + (46 if wide else 44), "分鐘", "fx-t fx-small", "middle"))
    out.append("</svg>")
    return "".join(out)


def _rise_table(minutes: dict, bound: _fx.Bound) -> str:
    rows = []
    for s in range(12):
        key = _pair_key(next(pair for pair in PAIRS if s in pair))
        cells = "".join(f'<td class="n">{bound.num(f"{minutes[v][s]:.0f}")}</td>' for v, _ in VARIANTS)
        rows.append(f'<tr data-fx-key="{key}"><th scope="row">{SIGNS[s]}</th>{cells}</tr>')
    return _fx.data_table(("星座", f"臺北（北緯 {bound.label('25.05')}°）", f"倫敦（北緯 {bound.label('51.5')}°）"),
                          rows, summary="圖中的數字（表格，單位：分鐘）")


def _rise_figure(d: dict) -> str:
    bound = _fx.Bound()
    for _, label in VARIANTS:
        bound.label(label)
    minutes = {"taipei": d["rising_minutes"], "london": d["london_minutes"]}
    for variant, table in minutes.items():
        if max(table.values()) > SCALE_MAX:
            raise RuntimeError(f"{variant}: a sign takes longer than the scale")
        for a, b in PAIRS:
            if round(table[a]) != round(table[b]):
                raise RuntimeError(f"{variant}: {SIGNS[a]} and {SIGNS[b]} do not rise in the same time")
    notes = []
    cities = {"taipei": "在臺北（北緯 25.05 度）", "london": "在倫敦（北緯 51.5 度）"}
    for pair in PAIRS:
        for variant, _ in VARIANTS:
            value = minutes[variant][pair[0]]
            notes.append(_fx.Note(_pair_key(pair), variant, (
                f"{SIGNS[pair[0]]}座與{SIGNS[pair[1]]}座：{cities[variant]}各約 {bound.num(f'{value:.0f}')} 分鐘升起，"
                f"上升點平均約 {bound.num(f'{value / 30:.1f}')} 分鐘走一度。")))
    bound.label("25.05")
    bound.label("51.5")
    caption = (
        f"<b>{bound.label('圖 3')}</b>每個星座整個升過東方地平所需的時間，單位是分鐘，以 {bound.num('1990')} 年 "
        f"{bound.num('5')} 月 {bound.num('15')} 日的天空計算。按鈕切換北緯 25.05 度（臺北）與北緯 51.5 度（倫敦），"
        f"兩地用同一把尺。在臺北，牡羊與雙魚最快，約 {bound.num(f'{d['rising_minutes'][0]:.0f}')} 分鐘；"
        f"巨蟹到射手六個星座最慢，約 {bound.num(f'{min(d['rising_minutes'][k] for k in range(3, 9)):.0f}')} 到 "
        f"{bound.num(f'{max(d['rising_minutes'][k] for k in range(3, 9)):.0f}')} 分鐘。十二段加起來是一個恆星日。"
        f"實心的兩段（處女、天秤）是{bound.label('圖 1')} 那一小時經過的星座。"
    )
    return _fx.figure(
        fid="fig-rising-times",
        title="每個星座升起所需的時間：臺北與倫敦",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _rise, "fig-rising-times", minutes, bound,
            notes=notes,
            idle="用 Tab 鍵移到一組星座上，或用滑鼠指著它，這裡會寫出它升起所需的時間。",
        ),
        controls=_fx.FigureControls(
            variants=VARIANTS,
            switch_label="切換緯度",
        ),
        table=_rise_table(minutes, bound),
        bound=bound,
    )


def build() -> tuple[dict[str, str], list[str]]:
    p = _product()
    with swiss() as swe:
        d = _data(swe)
        _check(d, p)
    rising, london = d["rising_minutes"], d["london_minutes"]
    slow = [rising[k] for k in range(3, 9)]
    if not math.isclose(sum(rising.values()) * 60, d["sidereal_day_seconds"], abs_tol=1.0):
        raise RuntimeError("the twelve rising times do not add up to a sidereal day")
    (lower, upper) = p["crossing"]
    quoted = [
        f"<b>{d['move5_sun_arcmin']:.1f}′</b><span>太陽",
        f"<b>{d['move5_moon_arcmin']:.1f}′</b><span>月亮",
        f"<b>{d['move5_asc_deg']:.2f}°</b><span>上升點",
        f"介於 {d['moon_speed_range'][0]:.1f} 與 {d['moon_speed_range'][1]:.1f} 度之間",
        f"恆星日長度（{d['sidereal_day_seconds']:.2f} 秒）",
        f"本站以二分法夾在 {_hms(lower)} 與 {_hms(upper)} 之間，寬 {p['width']} 秒",
        f"約 {rising[0]:.0f} 分鐘升起，巨蟹到射手約 {min(slow):.0f} 到 {max(slow):.0f} 分鐘",
        f"約 {rising[0] / 30:.0f} 分鐘一度，走過處女、天秤座時約 {rising[5] / 30:.1f} 分鐘一度",
        f"牡羊約 {london[0]:.0f} 分鐘、處女約 {london[5]:.0f} 分鐘",
    ]
    return {
        "fx-defs": _fx.defs(GLYPHS),
        "ascendant-hour": _hour_figure(d, p),
        "five-minutes": _five_figure(d),
        "rising-times": _rise_figure(d),
    }, quoted
