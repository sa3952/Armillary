"""〈整宮制與 Placidus〉: figure 1 (both house divisions on one wheel), the
placement and cusp tables, figure 2 (the polar band) and the polar status
table's states.

Every number is the product's own answer: the requests go to the real
application in process, as the chart fixtures do.  Synthetic instants only:
1990-05-15 11:00 Taipei, and the same date 12:00 at Tromsø for the polar case.
"""
from __future__ import annotations

import math

from ._common import SIGNS, backend_on_path, indent, spoken_longitude as _spoken


FRAGMENT = "blog-whole-sign-vs-placidus"
SYSTEMS = "WPRB"
ORDER = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
NAMES = {"sun": "太陽", "moon": "月亮", "mercury": "水星", "venus": "金星", "mars": "火星", "jupiter": "木星",
         "saturn": "土星"}
COUNT = "零一二三四五六七"
# The polar status table (表 4) as the article states it.
POLAR_STATES = {"W": "available_polar_geometry", "P": "placidus_no_semiarc", "R": "unstable", "B": "unstable"}


def _request(system: str, *, polar: bool = False, houses: bool = True) -> dict:
    lat, lon, hour, zone = (69.6496, 18.9560, 12, "Europe/Oslo") if polar else (25.05306, 121.52639, 11,
                                                                                "Asia/Taipei")
    options: dict[str, object] = {"house_system": system}
    if houses:
        options["include_houses"] = True
    return {"birth_time_precision": "exact",
            "datetime": {"year": 1990, "month": 5, "day": 15, "hour": hour, "minute": 0, "second": 0},
            "location": {"latitude": lat, "longitude": lon, "altitude_m": 10},
            "timezone": {"mode": "iana", "iana_name": zone},
            "options": options}


def _data() -> dict:
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        def post(payload: dict, expected: int = 200) -> dict:
            response = client.post("/api/chart", json=payload)
            if response.status_code != expected:
                raise RuntimeError(f"chart request answered {response.status_code}: {response.text[:300]}")
            return response.json()

        d: dict = {}
        for system in SYSTEMS:
            body = post(_request(system))
            division = body["derived_methods"]["house_division"]
            d[system] = {
                "cusps": division["cusps"],
                "placements": [(p["key"], p["house"]) for p in body["derived_methods"]["planet_in_house"]["placements"]],
                "angles": body["astronomical_data"]["angles"]["sign_positions"],
            }
        body = post(_request("P", houses=False))
        d["bodies"] = {b["key"]: [b["sign_position"][0], b["sign_position"][1], float(b["sign_position"][2])]
                       for b in body["astronomical_data"]["bodies"]}
        polar = {}
        for system in SYSTEMS:
            if system == "P":
                refusal = post(_request(system, polar=True), expected=422)["detail"]
                polar[system] = refusal["reason_code"]
                d["polar_reason"] = refusal["geometric_reason"]
            else:
                division = post(_request(system, polar=True))["derived_methods"]["house_division"]
                polar[system] = division["availability"]["state"]
        if polar != POLAR_STATES:
            raise RuntimeError(f"polar house states changed: {polar}")
    return d


def _written(lon: float) -> str:
    total = round(lon * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]}座 {rest // 60}°{rest % 60:02d}′"


def _wheel(d: dict) -> str:
    ASC = float(d["W"]["angles"]["asc"][2])
    MC = float(d["W"]["angles"]["mc"][2])
    W = H = 640
    cx = cy = 320

    def pt(lon, r):
        a = math.radians(180 + (lon - ASC))
        return cx + r * math.cos(a), cy - r * math.sin(a)

    whole, placidus = dict(d["W"]["placements"]), dict(d["P"]["placements"])
    moved = [key for key in ORDER if whole[key] != placidus[key]]
    differences = "；".join(f"{NAMES[key]}在整宮制落第 {whole[key]} 宮、在 Placidus 落第 {placidus[key]} 宮"
                           for key in moved)
    s = [f'<svg class="sq" viewBox="0 0 {W} {H}" role="img" aria-label="同一張合成星盤的兩種分宮：外圈是十二星座，'
         f"也就是整宮制的十二宮；內圈紅線是 Placidus 的宮頭。上升點在{_spoken(ASC)}，中天在{_spoken(MC)}。"
         f'{differences}；其餘{COUNT[len(ORDER) - len(moved)]}顆兩制相同。">']
    R0, R1, R2 = 300, 250, 205
    for k in range(12):
        a0, a1 = 30 * k, 30 * (k + 1)
        p = [pt(a0, R0), pt(a1, R0), pt(a1, R1), pt(a0, R1)]
        cls = "f-paper2" if k % 2 else "f-hair"
        s.append(f'<path class="{cls}" d="M{p[0][0]:.1f},{p[0][1]:.1f} A{R0},{R0} 0 0 0 {p[1][0]:.1f},{p[1][1]:.1f} '
                 f'L{p[2][0]:.1f},{p[2][1]:.1f} A{R1},{R1} 0 0 1 {p[3][0]:.1f},{p[3][1]:.1f} Z"/>')
        x, y = pt(a0 + 15, (R0 + R1) / 2)
        s.append(f'<text class="t-dim t-mid" x="{x:.1f}" y="{y+7:.1f}">{SIGNS[k]}</text>')
        house = (k - int(ASC // 30)) % 12 + 1
        x, y = pt(a0 + 15, (R1 + R2) / 2)
        s.append(f'<text class="t-mono t-mid" x="{x:.1f}" y="{y+7:.1f}">{house}</text>')
        x0, y0 = pt(a0, R0)
        x1, y1 = pt(a0, R2)
        s.append(f'<line class="g-dim" x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}"/>')
    s.append(f'<circle class="g-dim" cx="{cx}" cy="{cy}" r="{R0}"/>')
    s.append(f'<circle class="g-dim" cx="{cx}" cy="{cy}" r="{R1}"/>')
    s.append(f'<circle class="g-ink" cx="{cx}" cy="{cy}" r="{R2}"/>')
    P = d["P"]["cusps"]
    RP = 60
    for i, c in enumerate(P):
        x0, y0 = pt(c, R2)
        x1, y1 = pt(c, RP)
        cls = "g-ink" if i in (0, 9, 3, 6) else "g-accent-thin"
        s.append(f'<line class="{cls}" x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}"/>')
        nxt = P[(i + 1) % 12]
        mid = c + ((nxt - c) % 360) / 2
        x, y = pt(mid, 82)
        s.append(f'<text class="t-accent t-mid" x="{x:.1f}" y="{y+7:.1f}">{i+1}</text>')
    s.append(f'<circle class="f-paper" cx="{cx}" cy="{cy}" r="{RP-2}"/>')
    s.append(f'<circle class="g-accent-thin" cx="{cx}" cy="{cy}" r="{RP}"/>')
    s.append(f'<text class="t-faint t-mid" x="{cx}" y="{cy-4}">Placidus</text>')
    s.append(f'<text class="t-faint t-mid" x="{cx}" y="{cy+20}">宮號</text>')
    x, y = pt(ASC, R0 + 8)
    s.append(f'<text class="t-accent t-end" x="{x-4:.1f}" y="{y+7:.1f}">上升</text>')
    x, y = pt(MC, R0 + 10)
    s.append(f'<text class="t-accent t-mid" x="{x:.1f}" y="{y-6:.1f}">中天</text>')
    glyph = {"sun": "日", "moon": "月", "mercury": "水", "venus": "金", "mars": "火", "jupiter": "木", "saturn": "土"}
    placed: list[float] = []
    for key, (_, _, lon) in sorted(d["bodies"].items(), key=lambda kv: kv[1][2]):
        r = 165
        for other in placed:
            if abs(((lon - other) + 180) % 360 - 180) < 9:
                r = 130
        placed.append(lon)
        x, y = pt(lon, r)
        xt, yt = pt(lon, R2)
        s.append(f'<line class="g-hair" x1="{xt:.1f}" y1="{yt:.1f}" x2="{x:.1f}" y2="{y:.1f}"/>')
        fill = "f-ink" if key in moved else "f-paper"
        tcls = "t-paper" if key in moved else "t"
        s.append(f'<circle class="{fill}" cx="{x:.1f}" cy="{y:.1f}" r="17"/>')
        s.append(f'<circle class="g-ink" cx="{x:.1f}" cy="{y:.1f}" r="17"/>')
        s.append(f'<text class="{tcls} t-mid" x="{x:.1f}" y="{y+7:.1f}">{glyph[key]}</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def _polar() -> str:
    W2, H2 = 640, 300
    s = [f'<svg viewBox="0 0 {W2} {H2}" role="img" aria-label="地球的緯度示意。北緯與南緯 66.56 度以上的極區帶以紅色標出，'
         "在這裡本站整帶拒絕 Placidus；臺北在北緯 25 度，四種宮位制都可以算；挪威特羅姆瑟在北緯 69.6 度，位於極區帶內。\">"]
    gx, gy, gr = 170, 150, 125

    def lat_y(phi):
        return gy - gr * math.sin(math.radians(phi))

    def lat_half(phi):
        return gr * math.cos(math.radians(phi))

    pol = 66.56
    s.append(f'<circle class="f-paper" cx="{gx}" cy="{gy}" r="{gr}"/>')
    for sgn in (1, -1):
        yb = lat_y(sgn * pol)
        hw = lat_half(pol)
        sweep = 1 if sgn == 1 else 0
        s.append(f'<path class="f-accent-soft" d="M{gx-hw:.1f},{yb:.1f} A{gr},{gr} 0 0 {sweep} {gx+hw:.1f},{yb:.1f} Z"/>')
        s.append(f'<line class="g-accent-thin" x1="{gx-hw:.1f}" y1="{yb:.1f}" x2="{gx+hw:.1f}" y2="{yb:.1f}"/>')
    s.append(f'<line class="g-dim" x1="{gx-gr}" y1="{gy}" x2="{gx+gr}" y2="{gy}"/>')
    s.append(f'<circle class="g-ink" cx="{gx}" cy="{gy}" r="{gr}"/>')
    for name, phi in (("臺北 25.05°N", 25.05), ("特羅姆瑟 69.65°N", 69.65)):
        y = lat_y(phi)
        x = gx + lat_half(phi)
        s.append(f'<circle class="f-ink" cx="{x:.1f}" cy="{y:.1f}" r="6"/>')
        s.append(f'<line class="g-hair" x1="{x+8:.1f}" y1="{y:.1f}" x2="330" y2="{y:.1f}"/>')
        s.append(f'<text class="t" x="340" y="{y+7:.1f}">{name}</text>')
    s.append(f'<text class="t-accent" x="340" y="{lat_y(pol)+40:.1f}">66.56°：90° − 黃赤交角</text>')
    s.append(f'<text class="t-faint" x="{gx}" y="{gy+6}" text-anchor="middle">赤道</text>')
    s.append(f'<text class="t-dim" x="340" y="{lat_y(-40)+7:.1f}">紅色帶內：本站不算 Placidus</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def _cell(lon: float) -> str:
    k = int(lon // 30)
    x = lon - 30 * k
    dd = int(x)
    mm = int(round((x - dd) * 60))
    if mm == 60:
        dd, mm = dd + 1, 0
    return f"{SIGNS[k]} {dd}°{mm:02d}′"


def _cusps(d: dict) -> str:
    rows = []
    for i in range(12):
        cells = "".join(f'<td class="n">{_cell(d[hs]["cusps"][i])}</td>' for hs in SYSTEMS)
        rows.append(f'          <tr><td class="n">{i+1}</td>{cells}</tr>')
    return "\n".join(rows)


def _places(d: dict) -> str:
    rows = []
    placements = {hs: dict(d[hs]["placements"]) for hs in SYSTEMS}
    for key in ORDER:
        sign, dms, _ = d["bodies"][key]
        values = [placements[hs][key] for hs in SYSTEMS]
        highlight = ' class="hl"' if len(set(values)) > 1 else ""
        cells = "".join(f'<td class="n{" diff" if v != values[0] else ""}">{v}</td>' for v in values)
        rows.append(f'          <tr{highlight}><td>{NAMES[key]}</td><td class="n">{SIGNS[sign]} '
                    f'{dms[:dms.index("′")+1]}</td>{cells}</tr>')
    return "\n".join(rows)


def build() -> tuple[dict[str, str], list[str]]:
    d = _data()
    asc = float(d["W"]["angles"]["asc"][2])
    mc = float(d["W"]["angles"]["mc"][2])
    reason = d["polar_reason"]
    quoted = [
        f"上升點在{_written(asc)}，中天在{_written(mc)}",
        f"Placidus 的第十二宮頭在{_written(d['P']['cusps'][11])}",
        f"Alcabitius 的在{_written(d['B']['cusps'][8])}",
        "原因代碼 <code>placidus_no_semiarc</code>",
        "1900 到 2399 年間它落在 66.54 到 66.62 度之間",
    ]
    # The article restates the refusal message's band.
    if "1900–2399 年間在 66.54°–66.62° 之間" not in reason:
        raise RuntimeError(f"the Placidus refusal states a different polar band: {reason}")
    return {"wheel": _wheel(d), "placements": _places(d), "cusps": _cusps(d), "polar-band": _polar()}, quoted
