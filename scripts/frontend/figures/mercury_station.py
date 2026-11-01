"""〈行星停滯〉: figure 1 (Mercury's daily motion, October-November 2026, against Lilly's mean motion), figure 2 (a
slider over Mercury's place at Taipei midnight around its second station), tables 1-2 and the numbers the prose quotes.

Stations are where the geocentric speed in longitude changes sign, found with Swiss Ephemeris as in the retrograde
article; Lilly's station days and mean motion are the product's own settings (the motion-state module).  Every instant
is printed as the whole minute it lies in.
"""
from __future__ import annotations

import datetime as dt

from . import _fx
from ._common import PLANETS, backend_on_path, calc_ut, swiss
from .mercury_retrograde import Sky, _date, _dm, _roots, _sign_dm, _slash, _when

FRAGMENT = "blog-mercury-station-direct-2026"
START = (2026, 10, 14)
DAYS = 47
PER_DAY = 4
RULER_DAYS = tuple(range(9, 20))  # figure 2: Mercury at Taipei midnight on these November days
DEFAULT_STEP = RULER_DAYS.index(14)
NOVEMBER = ((2026, 11, 1), (2026, 11, 30))
TABLE_BODIES = ("saturn", "jupiter", "mars", "venus", "mercury")

def _settings() -> tuple[float, str, dict[str, dict[str, int]]]:
    with backend_on_path():
        from app.core import motion_states as ms
    arcsec, per, text = ms.MEAN_MOTIONS[ms.DEFAULT_MEAN_MOTION_PROFILE]["mercury"]
    return float(arcsec / per) / 3600, text, {k: dict(ms.STATION_DAYS[k]) for k in TABLE_BODIES}

def _midnight(swe, y: int, m: int, d: int) -> float:
    """Taipei midnight as a UT1 Julian day (the clock is UTC, so through utc_to_jd)."""
    utc = dt.datetime(y, m, d) - dt.timedelta(hours=8)
    return swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour, 0, 0.0, swe.GREG_CAL)[1]

def compute() -> dict:
    mean, mean_text, days = _settings()
    with swiss() as swe:
        sky = Sky(swe)
        t0 = _midnight(swe, *START)
        curve = [(t, sky.speed(t)) for t in (t0 + i / PER_DAY for i in range(DAYS * PER_DAY + 1))]
        (k1, retro), (k2, direct) = sky.stations(t0, t0 + DAYS)
        if (k1, k2) != ("R", "D"):
            raise RuntimeError("the window does not hold one retrograde and one direct station")
        ruler = [(t, sky.mercury(t)[0], sky.speed(t)) for t in (_midnight(swe, 2026, 11, d) for d in RULER_DAYS)]
        venus_speed = lambda t: calc_ut(swe, t, swe.VENUS)[3]  # noqa: E731
        venus = _roots(venus_speed, _midnight(swe, *NOVEMBER[0]), _midnight(swe, *NOVEMBER[1]), 0.5)
        if len(venus) != 1 or venus_speed(venus[0] - 1e-3) > 0:
            raise RuntimeError("Venus's November station is not one turn to direct")
        swift = _roots(lambda t: abs(sky.speed(t)) - mean, t0, t0 + DAYS, 0.25)
        moments = {"retro": retro, "direct": direct, "venus": venus[0],
                   "m_start": direct - days["mercury"]["second_station_to_direct"],
                   "v_start": venus[0] - days["venus"]["second_station_to_direct"]}
        lons = {"retro": sky.mercury(retro)[0], "direct": sky.mercury(direct)[0],
                "venus": calc_ut(swe, venus[0], swe.VENUS)[0]}
        stamps = [*moments.values(), *swift, *(t for t, _ in curve[::PER_DAY]), *(t for t, _, _ in ruler)]
        labels = {t: {"when": _when(swe, t), "date": _date(swe, t), "slash": _slash(swe, t)} for t in stamps}
    return {"curve": curve, "ruler": ruler, "moments": moments, "lons": lons, "swift": swift, "mean": mean,
            "mean_text": mean_text, "days": days, "labels": labels}

# --- figure 1: daily motion ------------------------------------------------------------

Y_TOP = 100.0  # arcminutes a day
IDLE1 = "用 Tab 鍵移到圖上的圓點，或用滑鼠指著它，這裡會寫出那一刻的時間與行速。"

def _keys(data: dict) -> list[tuple[str, str, float]]:
    m, sw = data["moments"], data["swift"]
    return [("retro", "第一次停滯", m["retro"]), ("swift-in", "逆行而行速快", sw[0]), ("swift-out", "回到行速慢", sw[1]),
            ("direct", "第二次停滯", m["direct"]), ("swift-direct", "順行而行速快", sw[2])]

def _plot1(layout: str, fid: str, data: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (96.0, 860.0) if wide else (48.0, 330.0)
    top, bottom = 56.0, (392.0 if wide else 352.0)
    curve, L = data["curve"], data["labels"]
    t0, t1 = curve[0][0], curve[-1][0]
    x = lambda t: x0 + (t - t0) / (t1 - t0) * (x1 - x0)  # noqa: E731
    y = lambda v: top + (Y_TOP - v) / (2 * Y_TOP) * (bottom - top)  # noqa: E731
    H = bottom + 64
    mean = data["mean"] * 60
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H), _fx.rect(x0, top, x1 - x0, bottom - top, "fx-track")]
    out.append(_fx.rect(x0, y(mean), x1 - x0, y(-mean) - y(mean), "fx-fill-hatch"))
    out.append(_fx.text(x0 + 8, y(mean) + 18, f"比平均 {bound.num(data['mean_text'])} 慢（單線底）", "fx-t fx-small fx-key"))
    m = data["moments"]
    for key in ("retro", "direct"):
        start = m[key] - (1 if key == "retro" else data["days"]["mercury"]["second_station_to_direct"])
        out.append(_fx.rect(x(start), top, x(m[key]) - x(start), bottom - top, "fx-fill-solid"))
    out.append(_fx.line(x0, y(0), x1, y(0), "fx-sunline"))
    pts = " ".join(f"{_fx.f(x(t))},{_fx.f(y(v * 60))}" for t, v in curve)
    out.append(f'<polyline points="{pts}" class="fx-curve"/>')
    out.append(_fx.rect(x0, top, x1 - x0, bottom - top, "fx-inset-frame"))
    out.append(_fx.text(x0 + 8, top + 20, "↑ 順行", "fx-t fx-small fx-rub"))
    out.append(_fx.text(x0 + 8, bottom - 10, "↓ 逆行", "fx-t fx-small fx-rub"))
    for tick in (-90, -60, -30, 0, 30, 60, 90):
        out.append(_fx.line(x0 - 5, y(tick), x0, y(tick), "fx-axis"))
        out.append(_fx.text(x0 - 8, y(tick) + 5, bound.scale(f"{'−' if tick < 0 else ''}{abs(tick)}′"), "fx-t fx-small fx-num", "end"))
    axis = bottom + 10
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    every = 7 if wide else 14
    for i in range(0, DAYS + 1, every):
        t = curve[PER_DAY * i][0]
        out.append(_fx.line(x(t), axis, x(t), axis + 5, "fx-axis"))
        out.append(_fx.text(x(t), axis + 22, bound.scale(L[t]["slash"]), "fx-t fx-small fx-num", "start" if i == 0 else "middle"))
    for key, name, t in _keys(data):
        v = 0.0 if key in ("retro", "direct") else (mean if key == "swift-direct" else -mean)
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{name}，{L[t]["when"]}">')
        out.append(_fx.circle(x(t), y(v), 18, "fx-hit"))
        out.append(_fx.circle(x(t), y(v), 7 if wide else 6, "fx-mk"))
        if key in ("retro", "direct"):
            out.append(_fx.text(x(t), top - 12, name if wide else name[-2:], "fx-t fx-small", "middle"))
        out.append("</g>")
    out.append("</svg>")
    if axis + 22 > H:
        raise RuntimeError("figure 1 outgrew its drawing")
    return "".join(out)

def _note1(data: dict, key: str, name: str, t: float, bound: _fx.Bound) -> str:
    L, lons = data["labels"], data["lons"]
    when = bound.num(L[t]["when"])
    if key == "retro":
        return f"{when}，水星在{bound.num(_sign_dm(lons['retro']))}停住、轉為逆行；行速是零。"
    if key == "direct":
        return f"{when}，水星在{bound.num(_sign_dm(lons['direct']))}停住、轉回順行；行速是零。"
    if key == "swift-in":
        return f"{when}起，水星一天退得比 {bound.num(data['mean_text'])} 多：照 Lilly，逆行也算行速快。"
    if key == "swift-out":
        return f"{when}起，水星一天退得比 {bound.num(data['mean_text'])} 少，又慢下來，接著停住。"
    return f"{when}起，轉回順行的水星一天走得比 {bound.num(data['mean_text'])} 多，回到行速快。"

def _figure1(data: dict) -> str:
    bound = _fx.Bound()
    L = data["labels"]
    notes = [_fx.Note(key, None, _note1(data, key, name, t, bound)) for key, name, t in _keys(data)]
    rows = [f'<tr><th scope="row">{bound.num(L[t]["date"])}</th><td class="n">{bound.num(_rate(v))}</td></tr>'
            for t, v in data["curve"][::PER_DAY * 3]]
    table = _fx.data_table(("日期（臺北 0 時）", "一天走多少（負數是往回退）"), rows)
    first, last = data["curve"][0][0], data["curve"][-1][0]
    caption = (f"<b>{bound.label('圖 1')}</b>從 {bound.num(L[first]['date'])}到 {bound.num(L[last]['date'])}，"
               "水星在黃道上一天走多少（曲線；上方是順行，下方是逆行）。單線底是 Lilly 給水星的平均行度以內，"
               "曲線在這裡面就是「行速慢」；實心直條是 Lilly 說水星停的那一天，接在兩次轉向之前。"
               "曲線兩次穿過零：第一次轉為逆行，第二次轉回順行。")
    return _fx.figure(fid="fig-ms-speed", hero=True, title="2026 年 10 月到 11 月，水星一天走多少", caption=caption,
        art=_fx.FigureArt.drawn(_plot1, "fig-ms-speed", data, bound, notes=notes, idle=IDLE1), table=table, bound=bound)

def _rate(degrees_per_day: float) -> str:
    minutes = round(degrees_per_day * 60)
    return ("−" if minutes < 0 else "") + f"{abs(minutes)}′"

# --- figure 2: the slider over the station ------------------------------------------------

LO, HI = 4.5, 8.5  # degrees of Scorpio drawn
SCRUB = "拖動看每天臺北 0 時的位置"
IDLE2 = "拖動滑桿，這裡會寫出那一天臺北 0 時水星的位置與行速。"

def _plot2(layout: str, fid: str, data: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (60.0, 820.0) if wide else (24.0, 316.0)
    base = 120.0
    H = 230.0
    x = lambda lon: x0 + (lon % 30 - LO) / (HI - LO) * (x1 - x0)  # noqa: E731
    ruler, L = data["ruler"], data["labels"]
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.line(x0, base, x1, base, "fx-axis"))
    for deg in range(5, 9):
        out.append(_fx.line(x(210 + deg), base, x(210 + deg), base + 8, "fx-axis"))
        out.append(_fx.text(x(210 + deg), base + 30, bound.scale(f"天蠍 {deg}°"), "fx-t fx-small fx-num", "middle"))
    out.append(_fx.line(x(data["lons"]["direct"]), 40, x(data["lons"]["direct"]), base, "fx-dash"))
    out.append(_fx.text(x(data["lons"]["direct"]), 32, "轉順的位置", "fx-t fx-small fx-key", "middle"))
    for step, (t, lon, v) in enumerate(ruler):
        body = []
        for earlier, (_, lon_e, _v) in enumerate(ruler[:step]):
            body.append(_fx.circle(x(lon_e), base - 14 - 4 * (earlier % 2), 3, "fx-mk"))
        body.append(_fx.circle(x(lon), base - 30, 9 if wide else 7, "fx-mk"))
        body.append(_fx.text(x0, H - 30, bound.num(f"{L[t]['date']}：{_sign_dm(lon)}，一天{'退' if v < 0 else '走'} {_rate(abs(v))}"),
                             "fx-t fx-small", "start"))
        out.append(_fx.step_group(step, DEFAULT_STEP, "".join(body)))
    out.append("</svg>")
    return "".join(out)

def _figure2(data: dict) -> str:
    bound = _fx.Bound()
    L = data["labels"]
    notes = []
    for step, (t, lon, v) in enumerate(data["ruler"]):
        prev = data["ruler"][step - 1][1] if step else None
        moved = "" if prev is None else f"比前一天{'往回' if lon < prev else '往前'} {bound.num(_dm(abs(lon - prev)))}；"
        notes.append(_fx.Note(None, None, f"{bound.num(L[t]['date'])} 0 時，水星在{bound.num(_sign_dm(lon))}，{moved}"
                              f"這一刻一天{'退' if v < 0 else '走'} {bound.num(_rate(abs(v)))}。", step=step))
    rows = [f'<tr><th scope="row">{bound.num(L[t]["date"])}</th><td>{bound.num(_sign_dm(lon))}</td>'
            f'<td class="n">{bound.num(_rate(v))}</td></tr>' for t, lon, v in data["ruler"]]
    table = _fx.data_table(("日期（臺北 0 時）", "水星位置", "一天走多少"), rows)
    first, last = data["ruler"][0][0], data["ruler"][-1][0]
    caption = (f"<b>{bound.label('圖 2')}</b>從 {bound.num(L[first]['date'])}到 {bound.num(L[last]['date'])}，"
               "每天臺北 0 時水星在天蠍座的位置（大圓點；小點是前幾天的位置）。拖動滑桿逐日看：轉向前後幾天，"
               "它幾乎停在原地。沒有腳本時顯示轉向後的第一個 0 時。")
    return _fx.figure(fid="fig-ms-ruler", title="水星轉回順行前後，每天停在哪裡", caption=caption,
        art=_fx.FigureArt.drawn(_plot2, "fig-ms-ruler", data, bound, notes=notes, idle=IDLE2),
        controls=_fx.FigureControls(steps=len(data["ruler"]), default_step=DEFAULT_STEP, scrub_label=SCRUB),
        table=table, bound=bound)

# --- tables and build ---------------------------------------------------------------

def _station_rows(data: dict) -> str:
    pages = {"saturn": "p.58", "jupiter": "p.62", "mars": "p.65", "venus": "p.73", "mercury": "p.76"}
    rows = []
    for key in TABLE_BODIES:
        d = data["days"][key]
        rows.append(f'          <tr><th scope="row">{PLANETS[key]}</th><td class="n">{d["first_station_to_retrograde"]} 天</td>'
                    f'<td class="n">{d["second_station_to_direct"]} 天</td><td>{pages[key]}</td></tr>')
    return "\n".join(rows)

def _three_days(data: dict) -> tuple[str, str, str]:
    """The span of Mercury's midnight places from the midnight before the second station's eve to the one after it."""
    ruler = data["ruler"]
    i = next(n for n, (t, _, _) in enumerate(ruler) if t > data["moments"]["direct"])
    span = ruler[i - 2:i + 2]
    lons = [lon for _, lon, _ in span]
    L = data["labels"]
    return L[span[0][0]]["date"], L[span[-1][0]]["date"], _dm(max(lons) - min(lons))

def build() -> tuple[dict[str, str], list[str]]:
    data = compute()
    L, m, lons = data["labels"], data["moments"], data["lons"]
    first, last, arc = _three_days(data)
    quoted = [L[m["retro"]]["when"], L[m["direct"]]["when"], L[m["venus"]]["when"], L[m["m_start"]]["when"],
              L[m["v_start"]]["when"], _sign_dm(lons["retro"]), _sign_dm(lons["direct"]), _sign_dm(lons["venus"]),
              f"{(m['direct'] - m['retro']):.1f} 天", data["mean_text"], first, last, arc,
              *(L[t]["when"] for t in data["swift"])]
    return {"fx-defs": _fx.defs(()), "speed": _figure1(data), "ruler": _figure2(data),
            "stations": _station_rows(data)}, list(dict.fromkeys(quoted))
