"""〈為什麼兩個網站算出的上升差 2′〉: figure 1 (the Ascendant against the east longitude of the place, one instant, the
catalogue's Taipei latitude), the step table (UTC, UT1, ΔT, sidereal time, obliquity, Ascendant, MC) and the numbers
the prose quotes.

Synthetic instant only: 1990-01-15 12:00 Asia/Taipei.  The product's answer is the chart route in process for the
catalogue's Taipei row (GeoNames 1668341), sent the way the calculator sends a catalogue place.  The independent answer
is spherical trigonometry written here (no `app` import): UT1 from Swiss's own UTC conversion, apparent sidereal time
from `swe.sidtime`, true obliquity from ECL_NUT, then MC = atan2(sin RAMC, cos RAMC cos e) and the rising
ecliptic-horizon intersection, the same closed formulas as the test oracle `tests/backend/solar_return_oracle.py`.  The
formula must agree with the product's Ascendant and MC within 0.05″; the other two coordinates are the formula alone,
once with UT1 and once with the clock time taken as UT (the plain `swe.julday` path a simple calculator uses).
"""
from __future__ import annotations

import functools
import math
import sqlite3

from . import _fx
from ._common import SIGNS, backend_on_path, product_charts, swiss

FRAGMENT = "blog-ascendant-coordinates"
LOCAL = (1990, 1, 15, 12, 0, 0)
UTC_HOUR = 4.0  # Asia/Taipei is UTC+8 in 1990, no daylight saving
RECORD = "1668341"
# The other catalogue row a search for 臺北 lists (first, above the GeoNames row).
MOI = ("taiwan_moi_place_names", "tw-moi-county-derived:93aa68efdc7c1301a133")
# Two other "Taipei" points that circulate as the city's coordinates.
OTHERS = ((25.0330, 121.5654), (25.04, 121.516))
LON_RANGE = (121.48, 121.60)
SAME_ARCSEC = 0.05

def _row(source: str = "geonames_cities500", record: str = RECORD) -> dict:
    with backend_on_path():
        from app.core.place_catalog import DEFAULT_CATALOG_PATH
    columns = "source, source_record_id, display_name, latitude, longitude, timezone, location_precision"
    connection = sqlite3.connect(f"{DEFAULT_CATALOG_PATH.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        row = connection.execute(f"SELECT {columns} FROM places WHERE source = ? AND source_record_id = ?",
            (source, record)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError(f"the catalogue no longer holds {source} {record}")
    return dict(zip(columns.split(", "), row))

def _product(row: dict) -> dict:
    payload = {"datetime": dict(zip(("year", "month", "day", "hour", "minute", "second"), LOCAL)),
        "timezone": {"mode": "iana", "iana_name": row["timezone"]},
        "location": {"latitude": row["latitude"], "longitude": row["longitude"], "place_label": row["display_name"],
        "location_source": row["source"], "source_record_id": row["source_record_id"],
        "location_precision": row["location_precision"]}}
    with product_charts() as post:
        answer = post(payload)
    if answer["calculation_dossier"]["location_resolution"]["verification_status"] != "server_matched_catalog_record":
        raise RuntimeError("the chart did not bind the catalogue row")
    time, angles = answer["astronomical_data"]["time"], answer["astronomical_data"]["angles"]
    return {"asc": angles["asc"], "mc": angles["mc"], "armc": angles["armc"], "jd_ut": time["jd_ut"],
            "delta_t": time["delta_t_seconds"], "gast": time["gast_hours"], "obliquity": time["true_obliquity"],
            "utc": time["utc_time"], "asc_dms": angles["sign_positions"]["asc"][1],
            "mc_dms": angles["sign_positions"]["mc"][1]}

def _angles(sidereal_hours: float, obliquity: float, lat: float, lon: float) -> tuple[float, float]:
    ramc = math.radians((sidereal_hours * 15.0 + lon) % 360.0)
    eps, phi = math.radians(obliquity), math.radians(lat)
    mc = math.degrees(math.atan2(math.sin(ramc), math.cos(ramc) * math.cos(eps))) % 360.0
    asc = math.atan2(math.cos(ramc), -(math.sin(ramc) * math.cos(eps) + math.tan(phi) * math.sin(eps)))
    right_ascension = math.atan2(math.sin(asc) * math.cos(eps), math.cos(asc))
    if math.sin(ramc - right_ascension) > 0.0:
        asc += math.pi
    return math.degrees(asc) % 360.0, mc

@functools.lru_cache(maxsize=1)
def data() -> dict:
    row = _row()
    product = _product(row)
    moi_row = _row(*MOI)
    moi = _product(moi_row)
    lat, lon = row["latitude"], row["longitude"]
    with swiss() as swe:
        jd_et, jd_ut1 = swe.utc_to_jd(*LOCAL[:3], int(UTC_HOUR), 0, 0.0, swe.GREG_CAL)
        jd_plain = swe.julday(*LOCAL[:3], UTC_HOUR)
        obliquity = swe.calc_ut(jd_ut1, swe.ECL_NUT, 0)[0][0]
        obliquity_plain = swe.calc_ut(jd_plain, swe.ECL_NUT, 0)[0][0]
        sid, sid_plain = float(swe.sidtime(jd_ut1)), float(swe.sidtime(jd_plain))
        delta_t = (jd_et - jd_ut1) * 86400.0
    def ut1(la: float, lo: float) -> tuple[float, float]:
        return _angles(sid, obliquity, la, lo)
    def plain(la: float, lo: float) -> tuple[float, float]:
        return _angles(sid_plain, obliquity_plain, la, lo)
    asc, mc = ut1(lat, lon)
    for name, ours, theirs in (("asc", asc, product["asc"]), ("mc", mc, product["mc"])):
        if abs((ours - theirs + 180) % 360 - 180) * 3600 > SAME_ARCSEC:
            raise RuntimeError(f"{name}: the formula says {ours}, the product {theirs}")
    if abs(jd_ut1 - product["jd_ut"]) * 86400 > 1e-3 or abs(delta_t - product["delta_t"]) > 1e-3:
        raise RuntimeError("Swiss's UTC conversion no longer gives the product's JD(UT) and ΔT")
    step = 0.01
    curve = []
    n = 60
    for i in range(n + 1):
        lo = LON_RANGE[0] + (LON_RANGE[1] - LON_RANGE[0]) * i / n
        curve.append((lo, ut1(lat, lo)[0]))
    return {"row": row, "product": product, "moi_row": moi_row, "moi": moi, "asc": asc, "mc": mc, "jd_ut1": jd_ut1,
        "jd_plain": jd_plain, "delta_t": delta_t, "ut1_minus_utc": (jd_ut1 - jd_plain) * 86400.0, "sidereal": sid,
        "lst": (sid * 15.0 + lon) % 360.0, "obliquity": obliquity, "per_lon": (ut1(lat, lon + step)[0] - asc) * 60,
        "per_lat": (ut1(lat + step, lon)[0] - asc) * 60, "plain_here": plain(lat, lon)[0],
        "others": [{"lat": la, "lon": lo, "ut1": ut1(la, lo)[0], "plain": plain(la, lo)[0]} for la, lo in OTHERS],
        "curve": curve}

def _in_sign(lon: float) -> float:
    return lon % 30.0

def _dms(lon: float) -> str:
    total = round(_in_sign(lon) * 3600)
    return f"{SIGNS[int(lon // 30) % 12]} {total // 3600}°{total // 60 % 60:02d}′{total % 60:02d}″"

def _dmm(lon: float) -> str:
    minutes = _in_sign(lon) * 60
    return f"{int(minutes // 60)}°{minutes % 60:05.2f}′"

def _hms(hours: float) -> str:
    total = hours * 3600
    h, rest = divmod(total, 3600)
    m, s = divmod(rest, 60)
    return f"{int(h)}h{int(m):02d}m{s:05.2f}s"


def _drawing(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    L, R, T, B = (96.0, 840.0, 70.0, 320.0) if wide else (52.0, 324.0, 66.0, 300.0)
    H = B + (72 if wide else 70)
    values = [v for _, v in d["curve"]]
    lo_v = math.floor(min(_in_sign(v) * 60 for v in values))
    hi_v = math.ceil(max(_in_sign(v) * 60 for v in values))
    X = lambda lon: L + (R - L) * (lon - LON_RANGE[0]) / (LON_RANGE[1] - LON_RANGE[0])  # noqa: E731
    Y = lambda v: B - (B - T) * (_in_sign(v) * 60 - lo_v) / (hi_v - lo_v)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    lat = bound.num(f"{d['row']['latitude']:.5f}")
    out.append(_fx.text(L if wide else 14, 34 if wide else 28, f"上升點（金牛座內），北緯 {lat}°", "fx-t fx-small fx-dim"))
    out.append(_fx.rect(L, T, R - L, B - T, "fx-inset-frame"))
    ticks = [round(LON_RANGE[0] + 0.02 * k, 2) for k in range(7)]
    for t in ticks if wide else ticks[::2]:
        out.append(_fx.line(X(t), T, X(t), B, "fx-hair"))
        out.append(_fx.text(X(t), B + 24, bound.scale(f"{t:.2f}°"), "fx-t fx-small fx-num", "middle"))
    for m in range(lo_v, hi_v + 1, 2 if wide else 4):
        y = B - (B - T) * (m - lo_v) / (hi_v - lo_v)
        out.append(_fx.text(L - 8, y + 5, bound.scale(f"{m // 60}°{m % 60:02d}′"), "fx-t fx-small fx-num", "end"))
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(lon))} {_fx.f(Y(v))}" for lon, v in d["curve"]), "fx-curve"))
    out.append(_fx.text(R, B + 50, "東經", "fx-t fx-small fx-dim", "end"))
    marks = (("here", d["row"]["longitude"], "本站目錄的臺北點"), ("east", OTHERS[0][1], "往東約 0.04°"))
    for key, lon, name in marks:
        lat0 = d["row"]["latitude"]
        value = _angles(d["sidereal"], d["obliquity"], lat0, lon)[0]
        x, y = X(lon), Y(value)
        label = f"{name}：東經 {bound.num(f'{lon:.5f}'.rstrip('0'))}°，{bound.num(_dmm(value))}"
        out.append(f'<g data-fx-key="{key}" tabindex="0" aria-label="{label}">')
        out.append(_fx.circle(x, y, 7 if wide else 6, "fx-mk-on" if key == "here" else "fx-mk"))
        anchor = "start" if key == "here" else "end"
        dx = 12 if key == "here" else -12
        out.append(_fx.text(x + dx, y + (-14 if key == "here" else 26), bound.num(_dmm(value)), "fx-t fx-small fx-num", anchor))
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)

def _figure(d: dict) -> str:
    bound = _fx.Bound()
    lat0 = d["row"]["latitude"]
    east = _angles(d["sidereal"], d["obliquity"], lat0, OTHERS[0][1])[0]
    notes = [
        _fx.Note("here", None, f"本站地點目錄的臺北點（GeoNames {bound.label(RECORD)}）：東經 "
                 f"{bound.num(f'{d['row']['longitude']:.5f}')}°，上升點金牛 {bound.num(_dmm(d['asc']))}。"),
        _fx.Note("east", None, f"緯度不變、經度換成 {bound.num(f'{OTHERS[0][1]:.4f}')}°（往東約 "
                 f"{bound.num(f'{OTHERS[0][1] - d['row']['longitude']:.2f}')}°）：上升點金牛 {bound.num(_dmm(east))}。"),
    ]
    caption = (
        f"<b>{bound.label('圖 1')}</b>合成時刻（不是任何人的出生資料）：{bound.num('1990')} 年 {bound.num('1')} 月 "
        f"{bound.num('15')} 日 {bound.num('12:00')}，臺北時間。緯度固定在本站目錄臺北點的北緯 "
        f"{bound.num(f'{lat0:.5f}')}°，只改經度：每往東 {bound.num('0.01')}°，上升點約前進 "
        f"{bound.num(f'{d['per_lon']:.2f}')}′。實心點是本站目錄的臺北點，空心點是同緯度、往東約 "
        f"{bound.num(f'{OTHERS[0][1] - d['row']['longitude']:.2f}')}° 的地方。"
    )
    rows = []
    for lon, value in d["curve"][::10]:
        rows.append(f'<tr><th scope="row">{bound.num(f"{lon:.2f}")}°</th><td class="n">{bound.num(_dmm(value))}</td></tr>')
    table = _fx.data_table(("東經", "上升點（金牛座內）"), rows)
    return _fx.figure(
        fid="fig-asc-longitude",
        title="同一刻、同一緯度，只改經度：上升點怎麼移動",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _drawing, "fig-asc-longitude", d, bound,
            notes=notes,
            idle="指向圖上的點，這裡會寫出那個經度的上升點。",
        ),
        table=table,
        bound=bound,
    )

# --- the step table ---------------------------------------------------------------

def _steps(d: dict) -> str:
    p = d["product"]
    rows = (("鐘面時間（臺北）", "1990-01-15 12:00:00"), ("換成協調世界時（UTC）", p["utc"].split(".")[0]),
        ("UT1 − UTC", f"+{d['ut1_minus_utc']:.2f} 秒"), ("儒略日 JD(UT1)", f"{d['jd_ut1']:.6f}"),
        ("ΔT（地球時減世界時）", f"{d['delta_t']:.2f} 秒"), ("格林威治視恆星時", _hms(d["sidereal"])),
        ("地方恆星時（加上東經）", f"{d['lst']:.4f}°"), ("黃赤交角（真）", f"{d['obliquity']:.4f}°"),
        ("上升點", _dms(d["asc"])), ("中天（MC）", _dms(d["mc"])))
    return "\n".join(f'          <tr><th scope="row">{name}</th><td class="n">{value}</td></tr>' for name, value in rows)

def _points(d: dict) -> str:
    row = d["row"]
    out = [f'          <tr><th scope="row">本站目錄（GeoNames {RECORD}）</th><td class="n">{row["latitude"]:.5f}, '
           f'{row["longitude"]:.5f}</td><td class="n">{_dmm(d["asc"])}</td><td class="n">{_dmm(d["plain_here"])}</td></tr>']
    for name, item in zip(("另一組常見座標 A", "另一組常見座標 B"), d["others"], strict=True):
        out.append(f'          <tr><th scope="row">{name}</th><td class="n">{item["lat"]:.4f}, {item["lon"]:.4f}</td>'
                   f'<td class="n">{_dmm(item["ut1"])}</td><td class="n">{_dmm(item["plain"])}</td></tr>')
    return "\n".join(out)

def build() -> tuple[dict[str, str], list[str]]:
    d = data()
    p = d["product"]
    a, b = d["others"]
    spread = (a["plain"] - b["plain"]) * 60
    lon0, lat0 = d["row"]["longitude"], d["row"]["latitude"]
    quoted = [f"往東 {a['lon'] - lon0:.3f}°", f"往南 {lat0 - a['lat']:.3f}°", f"差約 {(a['plain'] - d['asc']) * 60:.1f}′",
        f"{(a['ut1'] - d['asc']) * 60:.2f}′", f"金牛 {p['asc_dms']}", f"{_dmm(a['plain'])}", f"{_dmm(b['plain'])}",
        f"約 {spread:.1f}′", f"約差 {d['per_lon']:.2f}′", f"約差 {d['per_lat']:.2f}′", f"{d['ut1_minus_utc']:.2f} 秒",
        f"{d['delta_t']:.2f} 秒", f"約 {abs(d['plain_here'] - d['asc']) * 3600:.0f}″",
        f"北緯 {d['moi_row']['latitude']:.4f}、東經 {d['moi_row']['longitude']:.4f}", f"金牛 {_dmm(d['moi']['asc'])}",
        f"多約 {(d['moi']['asc'] - p['asc']) * 60:.1f}′"]
    return {"fx-defs": _fx.defs(()), "ascendant-longitude": _figure(d), "steps": _steps(d), "points": _points(d)}, quoted
