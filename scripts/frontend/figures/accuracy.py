"""〈線上排盤準不準〉: figure 1 (an error budget: how far each kind of error moves a position in the chart, on one
logarithmic scale) and figure 2 (a slider over a birth time given late by one second to one hour), with the numbers the
prose quotes.

Synthetic instant only: 1990-05-15 14:00, Taipei 25.05306N 121.52639E, the same instant as the birth-time article and
the home page demonstration.  Every ascendant and midheaven is the product's own answer, checked against the closed
form (ARMC from Swiss sidereal time at the product's JD(UT), true obliquity of date).  The ΔT values and uncertainty
are the product's receipt; the Moon "with ΔT ignored" is Swiss Ephemeris at the product's JD(UT) read as TT.  The
ephemeris row is the product against the JPL Horizons fixture the standing test uses, measured here; tolerances, the
eclipse comparison and the house closed-form bounds are read from the test fixtures and module, never typed.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import math
import re
from typing import Any

from . import _fx, page_validation
from ._common import ROOT, SIGNS, TAIPEI, backend_on_path, product_charts, sign_degree_minute, swiss
from . import _site

FRAGMENT = "blog-chart-calculation-accuracy"
LAT, LON = TAIPEI
BASE: dict[str, Any] = {"datetime": {"year": 1990, "month": 5, "day": 15, "hour": 14, "minute": 0, "second": 0},
    "location": {"latitude": LAT, "longitude": LON}, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
    "birth_time_precision": "exact", "options": {"house_system": "W", "include_houses": True}}
ROUNDED = (25.0, 122.0)
LATE = (1, 5, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)
DEFAULT_STEP = LATE.index(60)
FIXTURES = ROOT / "tests" / "backend" / "fixtures"
HOUSE_TEST = ROOT / "tests" / "backend" / "test_house_product_path.py"
CLASSICAL = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
CLOSED_FORM_ARCSEC = 0.05

def _wrap(delta: float) -> float:
    return (delta + 180.0) % 360.0 - 180.0

def _payload(**changes) -> dict:
    payload = json.loads(json.dumps(BASE))
    for key, value in changes.items():
        if key in ("year", "hour", "minute", "second"):
            payload["datetime"][key] = value
        elif key == "location":
            payload["location"] = {"latitude": value[0], "longitude": value[1]}
        elif key == "timezone":
            payload["timezone"] = value
        else:
            raise KeyError(key)
    return payload

def _late(seconds: int) -> dict:
    total = 14 * 3600 + seconds
    return _payload(hour=total // 3600, minute=total % 3600 // 60, second=total % 60)

def _angles(chart: dict) -> dict:
    data = chart["astronomical_data"]
    moon = next(b for b in data["bodies"] if b["key"] == "moon")
    return {"asc": data["angles"]["asc"], "mc": data["angles"]["mc"], "jd_ut": data["time"]["jd_ut"],
            "jd_et": data["time"]["jd_et"], "delta_t": data["time"]["delta_t_seconds"],
            "delta_t_model": data["time"]["delta_t_model"], "moon": moon["longitude"]}

def _horizons_residuals(post) -> list[dict]:
    fixture = json.loads((FIXTURES / "jpl_horizons_positions.json").read_text(encoding="utf-8"))
    out = []
    for epoch in fixture["epochs"]:
        t = dt.datetime.fromisoformat(epoch["utc"].replace("Z", "+00:00"))
        chart = post({
            "datetime": {"year": t.year, "month": t.month, "day": t.day, "hour": t.hour, "minute": t.minute, "second": 0},
            "location": {"latitude": 0.0, "longitude": 0.0, "altitude_m": 0},
            "timezone": {"mode": "fixed_offset", "utc_offset_hours": 0},
            "birth_time_precision": "exact", "options": {"house_system": "W", "include_houses": False},
        })
        shift = epoch["comparison_tt_jd"] - chart["astronomical_data"]["time"]["jd_et"]
        found = {b["key"]: b for b in chart["astronomical_data"]["bodies"]}
        lon = {key: _wrap(found[key]["longitude"] + found[key]["speed_longitude"] * shift
                          - epoch["geocentric_apparent_ecliptic_of_date"][key][0]) * 3600 for key in CLASSICAL}
        out.append({"year": t.year, "absolute": max(abs(v) for v in lon.values()),
                    "relative": max(abs(v - lon["sun"]) for v in lon.values())})
    return out

def _product() -> dict:
    with product_charts() as post:
        base = post(BASE)
        late = [_angles(post(_late(s))) for s in LATE]
        p = {"base": _angles(base), "engine": base["calculation_dossier"]["engine"], "late": late,
            "dst": _angles(post(_payload(timezone={"mode": "fixed_offset", "utc_offset_hours": 9.0}))),
            "rounded": _angles(post(_payload(location=ROUNDED))), "y1900": _angles(post(_payload(year=1900))),
            "y2399": _angles(post(_payload(year=2399))), "horizons": _horizons_residuals(post)}
    return p

def _closed_form(swe, jd_ut: float, lat: float, lon: float) -> tuple[float, float]:
    eps = swe.calc_ut(jd_ut, swe.ECL_NUT)[0][0]
    armc = (swe.sidtime(jd_ut) * 15.0 + lon) % 360.0
    r, e, p = math.radians(armc), math.radians(eps), math.radians(lat)
    mc = math.degrees(math.atan2(math.sin(r), math.cos(r) * math.cos(e))) % 360.0
    asc = math.degrees(math.atan2(math.cos(r), -(math.sin(r) * math.cos(e) + math.tan(p) * math.sin(e)))) % 360.0
    return asc, mc

def _swiss(swe, p: dict) -> dict:
    cases = [(p["base"], (LAT, LON)), (p["dst"], (LAT, LON)), (p["rounded"], ROUNDED)] + [(a, (LAT, LON)) for a in p["late"]]
    for angles, (lat, lon) in cases:
        asc, mc = _closed_form(swe, angles["jd_ut"], lat, lon)
        for name, own in (("asc", asc), ("mc", mc)):
            gap = abs(_wrap(angles[name] - own)) * 3600
            if gap > CLOSED_FORM_ARCSEC:
                raise RuntimeError(f"product {name} at JD {angles['jd_ut']} is {gap:.3f}″ off the closed form")
    out = {}
    for key in ("base", "y1900"):
        angles = p[key]
        own = swe.calc(angles["jd_et"], swe.MOON)[0][0]
        if abs(_wrap(own - angles["moon"])) * 3600 > 0.01:
            raise RuntimeError(f"{key}: Swiss's Moon at the product's TT is not the product's Moon")
        ignored = swe.calc(angles["jd_ut"], swe.MOON)[0][0]
        out[key] = abs(_wrap(ignored - angles["moon"])) * 3600
    return out

def _test_constants() -> dict:
    tree = ast.parse(HOUSE_TEST.read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in ("TOLERANCE_ARCSEC", "USNO_TOLERANCE_ARCSEC", "SYSTEM_CODES", "CASES"):
                found[name] = ast.literal_eval(node.value)
    if len(found) != 4:
        raise RuntimeError(f"house test constants not found: {sorted(found)}")
    return found

def _eclipses() -> dict:
    fixture = json.loads((FIXTURES / "nasa_eclipse_canon_selection.json").read_text(encoding="utf-8"))
    full = re.search(r"full comparison of (\d+) eclipses", fixture["provenance"]["selection"])
    differ = re.search(r"all (\d+) eclipses in 1900-2399 whose Swiss Ephemeris 2.10.03 type or centrality differs",
                       fixture["provenance"]["selection"])
    measured = re.search(r"measured \|difference\| <= ([0-9.]+) s over (\d+) eclipses", fixture["tolerance_td_seconds_why"])
    if full is None or measured is None or differ is None or full[1] != measured[2]:
        raise RuntimeError("the eclipse fixture no longer states its full comparison")
    return {"count": int(full[1]), "measured": measured[1], "tolerance": fixture["tolerance_td_seconds"],
            "differ": int(differ[1])}

# --- formatting ------------------------------------------------------------------

def _arc(arcsec: float) -> str:
    if arcsec < 1:
        return f"{arcsec:.2f}″"
    if arcsec < 60:
        return f"{arcsec:.0f}″"
    if arcsec < 3600:
        whole = round(arcsec)
        return f"{whole // 60}′{whole % 60:02d}″"
    return f"{arcsec / 3600:.1f}°"

def _dms(arcsec: float) -> str:
    whole = round(arcsec)
    return f"{whole // 3600}°{whole % 3600 // 60:02d}′{whole % 60:02d}″"

def _place(longitude: float) -> tuple[str, str]:
    sign, degree, minute = sign_degree_minute(longitude)
    return sign + "座", f"{degree}°{minute:02d}′"

def _late_label(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分鐘"
    return f"{seconds // 3600} 小時"

# --- figure 1: the error budget -----------------------------------------------------

LOG_LO, LOG_HI = -1.0, math.log10(30 * 3600)  # 0.1″ … 30°
TICKS: tuple[tuple[float, str], ...] = ((0.1, "0.1″"), (1, "1″"), (10, "10″"), (60, "1′"), (600, "10′"), (3600, "1°"), (36000, "10°"))
DISPLAY_ROUNDING = 30.0  # arcseconds: half of the arcminute a chart prints

def _rows(p: dict, moon: dict) -> list[dict]:
    base = p["base"]
    per_second = abs(_wrap(p["late"][0]["asc"] - base["asc"])) * 3600
    sigma = base["delta_t_model"]["uncertainty_order_seconds"]
    eph = max(r["absolute"] for r in p["horizons"] if r["year"] <= 2100)
    asc_shift = lambda other: abs(_wrap(other["asc"] - base["asc"])) * 3600  # noqa: E731
    return [
        {"key": "eph", "label": "星曆：與 JPL 星曆的差", "moves": "天體位置", "kind": "body", "value": eph,
         "how": "本站 7 個天體對 JPL Horizons，1900 到 2100 年 6 個時刻的最大差"},
        {"key": "dt-sigma", "label": "ΔT 本身的不確定（1990 年）", "moves": "上升點", "kind": "angle",
         "value": sigma * per_second, "sigma": sigma,
         "how": f"收據寫的 ΔT 不確定度約 {sigma:g} 秒，乘上上升點每秒走的角度"},
        {"key": "dt-1900", "label": "忽略 ΔT（1900 年）", "moves": "月亮", "kind": "body", "value": moon["y1900"],
         "how": f"ΔT 約 {p['y1900']['delta_t']:.1f} 秒；把世界時當成地球時算出的月亮差多少".replace("-", "−")},
        {"key": "dt-1990", "label": "忽略 ΔT（1990 年）", "moves": "月亮", "kind": "body", "value": moon["base"],
         "how": f"ΔT 約 {base['delta_t']:.1f} 秒；同上"},
        {"key": "minute", "label": "出生時間差 1 分鐘", "moves": "上升點", "kind": "angle",
         "value": asc_shift(p["late"][LATE.index(60)]), "how": "本站對 14:01 的回應減 14:00 的回應"},
        {"key": "coords", "label": "座標取到整數度", "moves": "上升點", "kind": "angle", "value": asc_shift(p["rounded"]),
         "how": "北緯 25°、東經 122° 對 北緯 25.05306°、東經 121.52639°"},
        {"key": "hour", "label": "時區或夏令時間錯 1 小時", "moves": "上升點", "kind": "angle", "value": asc_shift(p["dst"]),
         "how": "把鐘面當成 UTC+9（世界時早了 1 小時）"},
    ]

def _bind_how(row: dict, bound: _fx.Bound) -> str:
    for token in re.findall(r"\d+(?:\.\d+)?", row["how"]):
        bound.num(token)
    return row["how"]

def _budget(layout: str, fid: str, rows: list[dict], bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (400.0, 850.0) if wide else (14.0, 326.0)
    X = lambda v: x0 + (x1 - x0) * (math.log10(v) - LOG_LO) / (LOG_HI - LOG_LO)  # noqa: E731
    top, rh = (78.0, 50.0) if wide else (78.0, 72.0)
    bottom = top + len(rows) * rh
    axis = bottom + 6
    H = axis + (72 if wide else 70)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        out.append(_fx.text(24, 36, "每一種誤差讓星盤上的位置移動多少（對數刻度）", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(14, 28, "每一種誤差讓位置移動多少", "fx-t fx-small fx-dim"))
        out.append(_fx.text(14, 46, "（對數刻度，每格十倍）", "fx-t fx-small fx-dim"))
    xr = X(DISPLAY_ROUNDING)
    out.append(_fx.line(xr, top - 10, xr, bottom, "fx-dash"))
    note = f"顯示到角分的捨入：最多 {bound.scale(_arc(DISPLAY_ROUNDING))}"
    out.append(_fx.text(xr + 6, top - 14 if wide else top - 12, note, "fx-t fx-small fx-key"))
    for t, _ in TICKS[1:]:
        out.append(_fx.line(X(t), top - 4, X(t), bottom, "fx-hair"))
    for row in rows:
        i = rows.index(row)
        y = top + i * rh
        label = row["label"]
        for token in re.findall(r"\d+", label):
            bound.label(token)
        value = bound.num(_arc(row["value"]))
        fill = "fx-fill-solid" if row["kind"] == "angle" else "fx-fill-hatch"
        aria = f"{label}：{row['moves']}移動約 {value}"
        out.append(f'<g class="fx-row" data-fx-key="{row["key"]}" tabindex="0" aria-label="{aria}">')
        out.append(_fx.rect(8, y + 1, W - 16, rh - 2, "fx-hit"))
        xv = X(row["value"])
        if wide:
            cy = y + rh / 2
            out.append(_fx.text(24, cy - 2, label, "fx-t"))
            out.append(_fx.text(24, cy + 17, f"移動的是：{row['moves']}", "fx-t fx-small fx-dim"))
            out.append(_fx.rect(x0, cy - 9, xv - x0, 18, "fx-track"))
            out.append(_fx.rect(x0, cy - 9, xv - x0, 18, fill))
            if xv + 62 < W - 10:
                out.append(_fx.text(xv + 8, cy + 6, value, "fx-t fx-small fx-num fx-key"))
            else:
                out.append(_fx.text(xv - 8, cy + 6, value, "fx-t fx-small fx-num fx-key", "end"))
        else:
            out.append(_fx.text(14, y + 18, label, "fx-t fx-key"))
            out.append(_fx.text(W - 14, y + 18, value, "fx-t fx-num fx-key", "end"))
            out.append(_fx.rect(x0, y + 27, xv - x0, 15, "fx-track"))
            out.append(_fx.rect(x0, y + 27, xv - x0, 15, fill))
            out.append(_fx.text(14, y + 60, f"移動的是：{row['moves']}", "fx-t fx-small fx-dim fx-key"))
        out.append("</g>")
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    for t, name in TICKS:
        out.append(_fx.line(X(t), axis, X(t), axis + 5, "fx-axis"))
        anchor = "start" if t == TICKS[0][0] else "middle"
        out.append(_fx.text(X(t), axis + 22, bound.scale(name), "fx-t fx-small fx-num", anchor))
    legend = axis + (50 if wide else 48)
    lx = x0 if wide else 14
    out.append(_fx.rect(lx, legend - 12, 22, 13, "fx-fill-solid"))
    out.append(_fx.text(lx + 30, legend, "上升點", "fx-t fx-small"))
    out.append(_fx.rect(lx + 100, legend - 12, 22, 13, "fx-track"))
    out.append(_fx.rect(lx + 100, legend - 12, 22, 13, "fx-fill-hatch"))
    out.append(_fx.text(lx + 130, legend, "天體位置", "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)

def _budget_table(rows: list[dict], bound: _fx.Bound) -> str:
    body = []
    for row in rows:
        body.append(f'<tr data-fx-key="{row["key"]}"><th scope="row">{row["label"]}</th><td>{row["moves"]}</td>'
                    f'<td class="n">{bound.num(_arc(row["value"]))}</td><td>{_bind_how(row, bound)}</td></tr>')
    return _fx.data_table(("誤差來源", "移動的是", "移動多少", "怎麼算的"), body)

def _budget_figure(p: dict, rows: list[dict]) -> str:
    bound = _fx.Bound()
    notes = []
    for row in rows:
        value = bound.num(_arc(row["value"]))
        how = _bind_how(row, bound)
        notes.append(_fx.Note(row["key"], None, f"{row['label']}：{row['moves']}移動約 {value}。{how}。"))
    caption = (
        f"<b>{bound.label('圖 1')}</b>同一張合成盤（{bound.num('1990')} 年 {bound.num('5')} 月 {bound.num('15')} 日 "
        f"{bound.num('14:00')}，臺北，不是任何人的出生資料）上，各種誤差讓位置移動多少。橫軸是對數刻度，每一格大十倍；"
        "實心是上升點的移動，排線是天體位置的移動。虛線是只顯示到角分時的捨入：落在虛線左邊的誤差，"
        "在一般顯示到角分的星盤上看不出來。上升點與中天是本站計算服務的實際回應，月亮的兩列以 Swiss Ephemeris 自算。"
    )
    return _fx.figure(
        fid="fig-error-budget",
        hero=True,
        title="誤差預算：每一種誤差讓星盤上的位置移動多少",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _budget, "fig-error-budget", rows, bound,
            notes=notes,
            idle="用 Tab 鍵移到一列上，或用滑鼠指著它，這裡會寫出它怎麼算的。",
        ),
        table=_budget_table(rows, bound),
        bound=bound,
    )

# --- figure 2: a late birth time, with a slider ---------------------------------------

BEFORE, AFTER = 4.0, 16.0  # degrees shown before and after the 14:00 position

def _strip(layout: str, fid: str, p: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (130.0, 850.0) if wide else (14.0, 326.0)
    k = (x1 - x0) / (BEFORE + AFTER)
    rows = (("asc", "上升點", 112.0 if wide else 124.0), ("mc", "中天", 222.0 if wide else 252.0))
    H = (300.0 if wide else 344.0)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    head = (f"合成盤：{bound.num('1990')} 年 {bound.num('5')} 月 {bound.num('15')} 日 {bound.num('14:00')}，臺北。"
            "出生時間往後挪，上升點與中天移到哪裡")
    if wide:
        out.append(_fx.text(24, 36, head, "fx-t fx-small fx-dim"))
    else:
        cut = head.index("出生時間")
        out.append(_fx.text(14, 28, head[:cut], "fx-t fx-small fx-dim"))
        out.append(_fx.text(14, 46, head[cut:], "fx-t fx-small fx-dim"))
    base = p["base"]
    for key, name, y in rows:
        start = base[key] - BEFORE
        X = lambda lon: x0 + k * ((lon - start) % 360.0)  # noqa: E731
        out.append(_fx.text(24 if wide else 14, y - (40 if wide else 54), name, "fx-t"))
        boundary = (math.floor(base[key] / 30) + 1) * 30.0
        xb = X(boundary)
        out.append(_fx.rect(x0, y - 7, x1 - x0, 14, "fx-track"))
        out.append(_fx.rect(xb, y - 7, x1 - xb, 14, "fx-fill-dot"))
        for deg in range(int(math.ceil(start / 5) * 5), int(start + BEFORE + AFTER) + 1, 5):
            xt = X(float(deg))
            out.append(_fx.line(xt, y + 7, xt, y + 12, "fx-axis"))
            out.append(_fx.text(xt, y + (30 if wide else 28), bound.scale(f"{deg % 30}°"), "fx-t fx-small fx-num", "middle"))
        out.append(_fx.line(xb, y - 26, xb, y + 7, "fx-axis"))
        left, right = SIGNS[int(boundary // 30) - 1] + "座", SIGNS[int(boundary // 30) % 12] + "座"
        out.append(_fx.text(xb - 8, y - 14, left, "fx-t fx-small", "end"))
        out.append(_fx.text(xb + 8, y - 14, right, "fx-t fx-small fx-key"))
        out.append(_fx.circle(X(base[key]), y, 6, "fx-mk"))
    for i, (seconds, angles) in enumerate(zip(LATE, p["late"])):
        body = []
        for key, name, y in rows:
            start = base[key] - BEFORE
            xm = x0 + k * ((angles[key] - start) % 360.0)
            body.append(_fx.line(xm, y - 12, xm, y + 12, "fx-cursor"))
            sign, deg_text = _place(angles[key])
            moved = bound.num(_dms(abs(_wrap(angles[key] - base[key])) * 3600))
            info = f"晚 {bound.num(_late_label(seconds))}：移動 {moved}，到{sign} {bound.num(deg_text)}"
            if wide:
                body.append(_fx.text(x1, y - 40, info, "fx-t fx-small fx-num fx-cursor-t", "end"))
            else:
                body.append(_fx.text(14, y - 34, info, "fx-t fx-small fx-num fx-cursor-t"))
        out.append(_fx.step_group(i, DEFAULT_STEP, "".join(body)))
    ly = H - (26 if wide else 40)
    out.append(_fx.circle((24 if wide else 14) + 6, ly - 5, 6, "fx-mk"))
    out.append(_fx.text((24 if wide else 14) + 18, ly, f"{bound.num('14:00')} 的位置", "fx-t fx-small"))
    lx = 220 if wide else 14
    lyy = ly if wide else ly + 20
    out.append(_fx.line(lx + 6, lyy - 13, lx + 6, lyy + 3, "fx-cursor"))
    out.append(_fx.text(lx + 18, lyy, "挪後的位置；點狀底是下一個星座", "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)

def _strip_sentence(seconds: int, angles: dict, base: dict, bound: _fx.Bound) -> str:
    parts = []
    for key, name in (("asc", "上升點"), ("mc", "中天")):
        sign, deg = _place(angles[key])
        moved = bound.num(_dms(abs(_wrap(angles[key] - base[key])) * 3600))
        parts.append(f"{name}移動 {moved}，到{sign} {bound.num(deg)}")
    changed = [name for key, name in (("asc", "上升"), ("mc", "中天")) if int(angles[key] // 30) != int(base[key] // 30)]
    tail = f"；{'與'.join(changed)}已經換了星座。" if changed else "；兩者都還在原來的星座。"
    return f"出生時間晚了 {bound.num(_late_label(seconds))}：" + "；".join(parts) + tail

def _strip_table(p: dict, bound: _fx.Bound) -> str:
    rows = []
    base = p["base"]
    for seconds, angles in zip(LATE, p["late"]):
        cells = []
        for key in ("asc", "mc"):
            sign, deg = _place(angles[key])
            cells.append(f"<td>{sign} {bound.num(deg)}</td>"
                         f'<td class="n">{bound.num(_dms(abs(_wrap(angles[key] - base[key])) * 3600))}</td>')
        rows.append(f'<tr><th scope="row">{bound.num(_late_label(seconds))}</th>{"".join(cells)}</tr>')
    return _fx.data_table(("晚了", "上升點", "移動", "中天", "移動"), rows)

def _strip_figure(p: dict) -> str:
    bound = _fx.Bound()
    base = p["base"]
    notes = [_fx.Note(None, None, _strip_sentence(s, a, base, bound), step=i) for i, (s, a) in enumerate(zip(LATE, p["late"]))]
    asc_sign, asc_deg = _place(base["asc"])
    mc_sign, mc_deg = _place(base["mc"])
    caption = (
        f"<b>{bound.label('圖 2')}</b>合成範例（不是任何人的出生資料）：{bound.num('1990')} 年 {bound.num('5')} 月 "
        f"{bound.num('15')} 日 {bound.num('14:00')}，臺北，上升點在{asc_sign} {bound.num(asc_deg)}、中天在{mc_sign} "
        f"{bound.num(mc_deg)}（空心圓）。拖拉條把出生時間往後挪，從晚 {bound.num(_late_label(LATE[0]))}到晚 "
        f"{bound.num(_late_label(LATE[-1]))}；紅線是挪後的位置，每一步都是本站計算服務對那個時刻的實際回應。"
        "兩條尺都只畫出原本位置前後的一段黃道，點狀底是下一個星座。"
    )
    return _fx.figure(
        fid="fig-time-error",
        title="出生時間晚了幾秒到一小時，上升點與中天移動多少",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _strip, "fig-time-error", p, bound,
            notes=notes,
            idle="拖拉選一個時間誤差，這裡會寫出上升點與中天移動多少、到了哪裡。",
        ),
        controls=_fx.FigureControls(
            steps=len(LATE),
            default_step=DEFAULT_STEP,
            scrub_label="出生時間晚了",
        ),
        table=_strip_table(p, bound),
        bound=bound,
    )

# --- the article ----------------------------------------------------------------------

def build() -> tuple[dict[str, str], list[str]]:
    p = _product()
    with swiss() as swe:
        moon = _swiss(swe, p)
        with backend_on_path():
            from app import domain_catalog, ephemeris
            coverage = {name: tuple(swe.revjul(jd)[0] for jd in ephemeris.SEGMENT_MANIFEST[name]["jd_ut_coverage"])
                        for name in ephemeris.CORE_SEGMENTS}
            years = domain_catalog.PRODUCT_YEAR_RANGE
    rows = _rows(p, moon)
    shifts = [abs(_wrap(a["asc"] - p["base"]["asc"])) * 3600 for a in p["late"]]
    if shifts != sorted(shifts):
        raise RuntimeError("the ascendant's shift does not grow with the error")
    horizons = json.loads((FIXTURES / "jpl_horizons_positions.json").read_text(encoding="utf-8"))
    tol = horizons["tolerances_arcsec"]
    early = [r for r in p["horizons"] if r["year"] <= 2100]
    late = [r for r in p["horizons"] if r["year"] > 2100]
    for r in early + late:
        bound_tol = tol["geocentric_longitude_absolute_1900_2100" if r["year"] <= 2100 else "geocentric_longitude_absolute_after_2100"]
        if r["absolute"] > bound_tol or r["relative"] > tol["geocentric_longitude_relative_to_sun"]:
            raise RuntimeError(f"{r['year']}: the product is outside the Horizons tolerance the test pins")
    house = _test_constants()
    ecl = _eclipses()
    jpl, _created = _site.ephemeris_header()
    swiss_version = p["engine"]["swiss_ephemeris_library_version"]
    (plan_lo, plan_hi), = {coverage[name] for name in ephemeris.CORE_SEGMENTS}
    _points, body_hours = page_validation.size()
    per_second = shifts[0]
    by = {row["key"]: row for row in rows}
    quoted = [
        f"行星位置與 JPL 的星曆相差不到 {tol['geocentric_longitude_absolute_1900_2100']:g} 角秒",
        f"<b>{_arc(by['eph']['value'])}</b><span>",
        f"<b>{_arc(by['minute']['value'])}</b><span>",
        f"<b>{_arc(by['hour']['value'])}</b><span>",
        f"Swiss Ephemeris {swiss_version}",
        f"based on JPL {jpl}",
        f"涵蓋 {plan_lo} 到 {plan_hi} 年初",
        f"本站接受 {years[0]} 到 {years[1]} 年",
        f"每秒約 {p['base']['delta_t_model']['error_propagation']['sidereal_arcsec_per_second_of_delta_t_error']:.2f} 角秒",
        f"1990 年約 {p['base']['delta_t']:.1f} 秒",
        f"1900 年約 {p['y1900']['delta_t']:.1f} 秒".replace("-", "−"),
        f"2399 年約 {p['y2399']['delta_t'] / 60:.1f} 分鐘",
        f"上升點每秒約走 {per_second:.1f} 角秒",
        f"差 1 分鐘，上升點移動 {_arc(by['minute']['value'])}",
        f"座標取到整數度（北緯 {ROUNDED[0]:g} 度、東經 {ROUNDED[1]:g} 度），上升點移動 {_arc(by['coords']['value'])}",
        f"錯 1 小時，上升點移動 {_arc(by['hour']['value'])}",
        f"1900 年的盤只差 {_arc(moon['y1900'])}，1990 年的盤差 {_arc(moon['base'])}",
        f"約 {by['dt-sigma']['sigma']:g} 秒，折合上升點約 {_arc(by['dt-sigma']['value'])}",
        f"晚 {_late_label(LATE[-2])}，上升點已經換到{_place(p['late'][-2]['asc'])[0]}",
        f"黃經差不超過 {tol['geocentric_longitude_absolute_1900_2100']:g} 角秒（2100 年以後 {tol['geocentric_longitude_absolute_after_2100']:g} 角秒）",
        f"黃緯不超過 {tol['geocentric_latitude_absolute']:g} 角秒",
        f"扣掉太陽的差之後不超過 {tol['geocentric_longitude_relative_to_sun']:g} 角秒",
        f"{len(horizons['epochs'])} 個時刻",
        f"實測最大 {max(r['absolute'] for r in early):.2f} 角秒；2100 年以後最大 {max(r['absolute'] for r in late):.2f} 角秒",
        f"{body_hours:,} 列",
        f"{ecl['count']} 次日食",
        f"有 {ecl['differ']} 次與日食典不同",
        f"容許 {ecl['tolerance']:g} 秒，實測最大 {ecl['measured']} 秒",
        f"{len(house['SYSTEM_CODES'])} 種宮位制、{len(house['CASES'])} 個地點與年代",
        f"差小於 {house['TOLERANCE_ARCSEC']:g} 角秒",
        f"容許 {house['USNO_TOLERANCE_ARCSEC']:g} 角秒",
        f"世界時換成地球時差不超過 {tol['time_scale_tt_seconds_utc_era'] * 1000:g} 毫秒",
    ]
    return {"fx-defs": _fx.defs(()), "error-budget": _budget_figure(p, rows), "time-error": _strip_figure(p)}, quoted

def elsewhere(fragment: str) -> dict[str, list[str]]:
    """The validation run's observations the article repeats, and the largest Horizons residuals (the fixture's own
    note places them at 1900 and 2399): the validation page must still say them."""
    measured = re.search(r"實測最大 ([0-9.]+) 角秒；2100 年以後最大 ([0-9.]+) 角秒", fragment)
    if measured is None:
        raise RuntimeError("the article no longer states its largest Horizons residuals")
    return {"validation": ["<b>99.96%</b>", "水星赤緯4.8角秒", "<dt>位置門檻</dt><dd>5角秒；月亮15角秒</dd>",
                           measured[0], f"1900 年約差 {measured[1]} 角秒，2399 年約差 {measured[2]} 角秒"]}
