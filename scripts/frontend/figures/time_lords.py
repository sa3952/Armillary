"""〈年度時間主星入門〉: figure 1 (the annual profection wheel), figure 2 (the
firdaria periods in the day and the two night orders), figure 3 (the
releasing sign periods and one decennial period shared out by the minor
years), figure 4 (years 25–49 of the demonstration chart, every technique a
row, a slider over the years), table 1 (year 37's periods with their own start
and end), table 2 (that year's twelve monthly-profection months and their
lengths), and the numbers the article quotes.

The periods are the product's own answer: the annual route, in process and
switched on only here, for the demonstration birth time the home and features
pages print (_demo.DEMO), year of life 37 and its hundred-year window.  The
cycle totals, sequences and sign periods are the backend's tables; the
firdaria notation gap is the methods page's own computation.
"""
from __future__ import annotations

import math

from . import _fx, page_methods_time_lords
from ._common import SIGNS, backend_on_path, swiss
from ._demo import DEMO


FRAGMENT = "blog-time-lords-introduction"
YEAR_OF_LIFE = 37
SIGN_KEYS = ("aries", "taurus", "gemini", "cancer", "leo", "virgo",
             "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces")
SIGN = dict(zip(SIGN_KEYS, SIGNS))
BODY = page_methods_time_lords.BODY
ANGULARITY = {"angular": "角宮", "succedent": "續宮", "cadent": "果宮"}

def _answer() -> dict:
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.settings import AppSettings

        client = TestClient(create_app(AppSettings(enable_annual_route=True)))
        payload = {key: DEMO[key] for key in ("datetime", "location", "timezone")}
        payload["annual"] = {
            "target_kind": "year_of_life", "target_value": YEAR_OF_LIFE,
            "include_profection": True, "include_monthly_profection": True,
            "include_firdaria": True, "include_zodiacal_releasing": True,
            "include_decennials": True,
        }
        response = client.post("/api/chart/annual", params={"projection": "detailed"}, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"annual request answered {response.status_code}: {response.text[:300]}")
        return response.json()


def _end(period: dict) -> dict:
    return period.get("end") or period["effective_end"]


def _overlaps(period: dict, start: float, end: float) -> bool:
    return period["start"]["jd_ut"] < end and _end(period)["jd_ut"] > start


def _rows(answer: dict) -> list[dict]:
    """Each drawn row: its label and the periods it shows inside the year, in
    order, every one with the name it is drawn with and the table's words."""
    methods = answer["annual_methods"]
    year = answer["year_boundary"]
    start, end = year["start"]["jd_ut"], year["end"]["jd_ut"]
    inside = lambda periods: [p for p in periods if _overlaps(p, start, end)]  # noqa: E731

    profection = methods["annual_profection"]
    rows = [{
        "label": "年度小限", "technique": "年度小限", "level": "—",
        "periods": [{"name": f"{SIGN[profection['profected_sign']]}（{BODY[profection['lord']['body_key']]}）",
                     "who": f"{SIGN[profection['profected_sign']]}；年主星{BODY[profection['lord']['body_key']]}",
                     "start": year["start"], "end": year["end"], "from_fortune": "—"}],
    }]
    months = methods["monthly_profection"]["periods"]
    rows.append({
        "label": "月小限", "technique": "月小限", "level": "第 1–12 個月",
        "periods": [{"name": str(m["month_of_year"]), "start": m["start"], "end": m["end"]} for m in months],
    })

    firdaria = methods["firdaria"]
    (major,) = inside(firdaria["periods"])
    rows.append({"label": "法達・主期", "technique": "法達", "level": "主期", "periods": [{
        "name": BODY[major["level_1_lord"]], "who": BODY[major["level_1_lord"]],
        "start": major["start"], "end": major["end"], "from_fortune": "—"}]})
    rows.append({"label": "法達・子期", "technique": "法達", "level": "子期", "periods": [{
        "name": BODY[sub["level_2_partner"]], "who": BODY[sub["level_2_partner"]],
        "start": sub["start"], "end": sub["end"], "from_fortune": "—"} for sub in inside(major["level_2"])]})

    for release in methods["zodiacal_releasing"]["releases"]:
        lot = {"fortune": "命運點", "spirit": "精神點"}[release["releasing_from"]]
        (period,) = inside(release["periods"])
        for level, label, periods in (("大期", "大期", [period]), ("小期", "小期", inside(period["level_2"]))):
            rows.append({
                "label": f"黃道釋放・{lot}・{label}",
                "technique": f"黃道釋放（從{lot}起，{SIGN[release['start_sign']]}）", "level": level,
                "periods": [{
                    "name": SIGN[p["sign"]],
                    "who": f"{SIGN[p['sign']]}；守護行星{BODY[p['domicile_lord']]}",
                    "start": p["start"], "end": p["effective_end"],
                    "from_fortune": f"第 {p['position_from_fortune']} 個，{ANGULARITY[p['angularity_from_fortune']]}",
                } for p in periods],
            })

    decennials = methods["decennials"]
    (major,) = inside(decennials["periods"])
    rows.append({"label": "十年期・第一層", "technique": "十年期", "level": "第一層", "periods": [{
        "name": BODY[major["lord"]], "who": BODY[major["lord"]],
        "start": major["start"], "end": major["end"], "from_fortune": "—"}]})
    rows.append({"label": "十年期・第二層", "technique": "十年期", "level": "第二層", "periods": [{
        "name": BODY[sub["lord"]], "who": BODY[sub["lord"]],
        "start": sub["start"], "end": sub["end"], "from_fortune": "—"} for sub in inside(major["level_2"])]})
    return rows


# --- the four figures ----------------------------------------------------------
#
# Figure 1, the annual profection wheel, and figure 4, a stretch of the same
# chart's life with a slider, read the product's lifetime answer (the annual
# route asked for its hundred-year window).  Figure 2 draws the firdaria
# sequences and figure 3 the releasing sign periods from the backend's own
# tables; figure 3's 129 months are the product's Saturn decennial of the same
# chart.  The profection of every year is checked against the Ascendant read
# from Swiss directly and a domicile table written out here.

SHORT = {"sun": "日", "moon": "月", "mercury": "水", "venus": "金", "mars": "火", "jupiter": "木", "saturn": "土"}
# The domiciles, written out as the independent answer the product's profection
# lords are checked against.
DOMICILES = {
    "aries": "mars", "taurus": "venus", "gemini": "mercury", "cancer": "moon", "leo": "sun", "virgo": "mercury",
    "libra": "venus", "scorpio": "mars", "sagittarius": "jupiter", "capricorn": "saturn", "aquarius": "saturn",
    "pisces": "jupiter",
}
WINDOW = (25, 49)  # figure 4: years of life drawn; the slider starts at YEAR_OF_LIFE
WHEEL_YEARS = 3  # figure 1 writes each sign's first three years
# The methods page's names of the two nocturnal orders (methods-time-lords, the firdaria table).
FIRDARIA_VARIANTS = (
    ("day", None, "日盤"),
    ("night", "abu_mashar_nodes_after_mercury_v1", "夜盤（預設：交點在水星後）"),
    ("night-mars", "bonatti_reading_nodes_after_mars_v1", "夜盤（另一種讀法：交點在火星後）"),
)


def _lifetime() -> dict:
    """The demonstration chart's hundred return years, as the annual route answers them."""
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.settings import AppSettings

        client = TestClient(create_app(AppSettings(enable_annual_route=True)))
        payload = {key: DEMO[key] for key in ("datetime", "location", "timezone")}
        payload["annual"] = {
            "target_kind": "year_of_life", "target_value": YEAR_OF_LIFE,
            "include_profection": True, "include_year_boundaries": True,
            "include_firdaria": True, "firdaria_scope": "lifetime_window",
            "include_zodiacal_releasing": True, "zr_scope": "lifetime_window",
            "include_decennials": True, "decennials_scope": "lifetime_window",
        }
        response = client.post("/api/chart/annual", params={"projection": "detailed"}, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"lifetime request answered {response.status_code}: {response.text[:300]}")
        return response.json()


def _swiss_ascendant_sign() -> int:
    """The demonstration chart's Ascendant sign, read from Swiss without the product."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    when = datetime(**{k: DEMO["datetime"][k] for k in ("year", "month", "day", "hour", "minute", "second")},
                    tzinfo=ZoneInfo(DEMO["timezone"]["iana_name"]))
    utc = when.astimezone(timezone.utc)
    with swiss() as swe:
        jd = swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60 + utc.second / 3600)
        asc = swe.houses_ex(jd, DEMO["location"]["latitude"], DEMO["location"]["longitude"], b"W")[1][0]
    return int(asc // 30)


def _years(lifetime: dict) -> list[dict]:
    """The product's return years, each checked against the independent profection."""
    years = lifetime["year_boundaries"]["years"]
    asc = _swiss_ascendant_sign()
    for item in years:
        expected = SIGN_KEYS[(asc + item["year_of_life"] - 1) % 12]
        if (item["profection_sign"], item["year_lord"]) != (expected, DOMICILES[expected]):
            raise RuntimeError(f"year {item['year_of_life']}: the product profects to {item['profection_sign']}, "
                               f"Swiss and the domicile table say {expected}")
    return years


def _wedge(cx: float, cy: float, r0: float, r1: float, a0: float, a1: float) -> str:
    """An annular sector from angle a0 to a1 (degrees, counter-clockwise from 3 o'clock)."""
    def at(r: float, a: float) -> str:
        return f"{_fx.f(cx + r * math.cos(math.radians(a)))} {_fx.f(cy - r * math.sin(math.radians(a)))}"
    large = 1 if a1 - a0 > 180 else 0
    return (f"M{at(r1, a0)} A{_fx.f(r1)} {_fx.f(r1)} 0 {large} 0 {at(r1, a1)} L{at(r0, a1)} "
            f"A{_fx.f(r0)} {_fx.f(r0)} 0 {large} 1 {at(r0, a0)} Z")


def _polar(cx: float, cy: float, r: float, a: float) -> tuple[float, float]:
    return cx + r * math.cos(math.radians(a)), cy - r * math.sin(math.radians(a))


def _profection_wheel(layout: str, fid: str, signs: list[dict], bound: _fx.Bound) -> str:
    """Figure 1: twelve sectors from the Ascendant's sign at 9 o'clock, counter-clockwise
    in zodiacal order, each with its lord and the years of life it holds."""
    wide = layout == "fx-wide"
    # Each sector: its glyph in the outer ring, then a block of three lines (sign,
    # lord, its first years) set upright around one point of the sector.
    if wide:
        W, H, cx, cy = _fx.WIDE, 560.0, 440.0, 282.0
        r_out, r_ring, r_block, r_in, gl = 252.0, 216.0, 150.0, 70.0, 18.0
        lines = (-14.0, 7.0, 28.0)
    else:
        W, H, cx, cy = _fx.NARROW, 340.0, 170.0, 170.0
        r_out, r_ring, r_block, r_in, gl = 160.0, 142.0, 100.0, 36.0, 12.0
        lines = (-9.0, 5.0, 19.0)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.circle(cx, cy, r_out, "fx-axis"))
    out.append(_fx.circle(cx, cy, r_ring, "fx-hair"))
    out.append(_fx.circle(cx, cy, r_in, "fx-axis"))
    for i, item in enumerate(signs):
        a = 180.0 + 30.0 * i
        years = item["years"][:WHEEL_YEARS]
        label = (f"{item['name']}，年主星{item['lord_name']}，第 "
                 + "、".join(bound.num(str(y)) for y in item["years"]) + " 年")
        body = [f'<g class="fx-row" data-fx-key="{item["key"]}" tabindex="0" aria-label="{label}">',
                _fx.path(_wedge(cx, cy, r_in, r_out, a - 15, a + 15), "fx-hit"),
                _fx.line(*_polar(cx, cy, r_in, a - 15), *_polar(cx, cy, r_out, a - 15), "fx-hair")]
        body.append(_fx.glyph(item["key"], *_polar(cx, cy, (r_out + r_ring) / 2, a), gl, "fx-mk-gl"))
        x, y = _polar(cx, cy, r_block, a)
        body.append(_fx.text(x, y + lines[0], item["name"], "fx-t", "middle"))
        body.append(_fx.text(x, y + lines[1], item["lord_name"], "fx-t fx-small fx-dim", "middle"))
        body.append(_fx.text(x, y + lines[2], "·".join(bound.num(str(v)) for v in years), "fx-t fx-small fx-num", "middle"))
        body.append("</g>")
        out += body
    out.append(_fx.text(cx, cy - (4 if wide else 2), "上升", "fx-t fx-small", "middle"))
    out.append(_fx.text(cx, cy + (18 if wide else 13), "星座", "fx-t fx-small", "middle"))
    # the Ascendant: a short rule outside the wheel at 9 o'clock
    out.append(_fx.line(cx - r_out - (24 if wide else 6), cy, cx - r_out, cy, "fx-axis"))
    if wide:
        out.append(_fx.text(cx - r_out - 20, cy - 10, "上升點", "fx-t fx-small", "end"))
    out.append("</svg>")
    return "".join(out)


def _firdaria_band(layout: str, fid: str, firdaria, bound: _fx.Bound) -> str:
    """Figure 2: the 75 years from birth as one band, a segment per lord, each
    planet's split into its seven sub-periods; one group per order."""
    wide = layout == "fx-wide"
    total = firdaria.CYCLE_YEARS
    if wide:
        W, H = _fx.WIDE, 330.0
        a0, a1, b0, b1 = 40.0, 840.0, 96.0, 136.0  # years across; the band's top and bottom
    else:
        W, H = _fx.NARROW, 630.0
        a0, a1, b0, b1 = 96.0, 96.0 + total * 6.6, 110.0, 160.0  # years down; the band's left and right
    P = lambda y: a0 + y / total * (a1 - a0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for key, profile, _ in FIRDARIA_VARIANTS:
        order = firdaria.DIURNAL_SEQUENCE if profile is None else firdaria.NOCTURNAL_SEQUENCES[profile]
        body, start, last_label = [], 0, -1e9
        levels: list[float] = []
        for lord in order:
            years = firdaria.PERIOD_YEARS[lord]
            p0, p1 = P(start), P(start + years)
            node = lord in firdaria.NODES
            x, y, w, h = (p0, b0, p1 - p0, b1 - b0) if wide else (b0, p0, b1 - b0, p1 - p0)
            body.append(_fx.rect(x, y, w, h, "fx-b-beam" if node else "fx-cell"))
            if node:
                body.append(_fx.rect(x, y, w, h, "fx-inset-frame"))
            if not node:
                for part in range(1, 7):
                    q = P(start + years * part / 7)
                    body.append(_fx.line(q, b1 - 10, q, b1, "fx-axis") if wide else _fx.line(b1 - 10, q, b1, q, "fx-axis"))
            name = BODY[lord]
            span = f"{bound.num(str(years))} 年"
            mid = (p0 + p1) / 2
            if wide:
                body.append(_fx.glyph(lord, mid, b0 - 18, 15, "fx-mk-gl"))
                # names below the band; where a neighbour is too close, one row lower
                level = 0 if not levels or mid - last_label > 54 or levels[-1] == 1 else 1
                levels.append(level)
                y = b1 + 26 + level * 44
                if level:
                    body.append(_fx.line(mid, b1 + 4, mid, y - 16, "fx-leader"))
                body.append(_fx.text(mid, y, name, "fx-t fx-small", "middle"))
                body.append(_fx.text(mid, y + 19, span, "fx-t fx-small fx-num", "middle"))
                last_label = mid
            else:
                y = max(mid + 5, last_label + 17)
                body.append(_fx.glyph(lord, b1 + 16, y - 5, 12, "fx-mk-gl"))
                body.append(_fx.text(b1 + 30, y, f"{name}　{span}", "fx-t fx-small"))
                if abs(y - 5 - mid) > 2:
                    body.append(_fx.line(b1 + 2, mid, b1 + 8, y - 5, "fx-leader"))
                last_label = y
            start += years
        if start != total:
            raise RuntimeError("the firdaria periods no longer add up to the cycle")
        out.append(_fx.variant_group(key, FIRDARIA_VARIANTS[0][0], "".join(body)))
    # the years from birth
    for year in range(0, total + 1, 5):
        tick = P(year)
        if wide:
            axis = b1 + 112
            out.append(_fx.line(tick, axis, tick, axis + 5, "fx-axis"))
            if year % 15 == 0:
                out.append(_fx.text(tick, axis + 24, bound.scale(str(year)), "fx-t fx-small fx-num",
                                    "start" if year == 0 else "end" if year == total else "middle"))
        else:
            axis = b0 - 12
            out.append(_fx.line(axis - 5, tick, axis, tick, "fx-axis"))
            if year % 15 == 0:
                out.append(_fx.text(axis - 8, tick + 4, bound.scale(str(year)), "fx-t fx-small fx-num", "end"))
    if wide:
        out.append(_fx.line(a0, b1 + 112, a1, b1 + 112, "fx-axis"))
        out.append(_fx.text((a0 + a1) / 2, b1 + 162, "出生後的年數（等比例）", "fx-t fx-small", "middle"))
        out.append(_fx.text(a0, 40, "主期與年數；細刻度把行星的主期七等分成子期", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.line(b0 - 12, a0, b0 - 12, a1, "fx-axis"))
        out.append(_fx.text(18, 34, "出生後的年數（往下）", "fx-t fx-small fx-dim"))
        out.append(_fx.text(18, 54, "細刻度把行星的主期", "fx-t fx-small fx-dim"))
        out.append(_fx.text(18, 72, "七等分成子期", "fx-t fx-small fx-dim"))
    out.append("</svg>")
    return "".join(out)


def _minor_years(layout: str, fid: str, releasing, lords: dict, minor: dict, decennial: dict,
                 bound: _fx.Bound) -> str:
    """Figure 3: the releasing sign periods as a ring in proportion to their
    years; beside it one decennial period's 129 months shared out by the
    planets' minor years."""
    wide = layout == "fx-wide"
    total = sum(releasing.SIGN_PERIOD_YEARS.values())
    if wide:
        W, H = _fx.WIDE, 500.0
        cx, cy, r_out, r_in, r_name, r_years = 230.0, 250.0, 186.0, 104.0, 164.0, 128.0
        bx, by0, by1, bw = 560.0, 86.0, 430.0, 46.0
    else:
        W, H = _fx.NARROW, 880.0
        cx, cy, r_out, r_in, r_name, r_years = 170.0, 206.0, 150.0, 76.0, 132.0, 100.0
        bx, by0, by1, bw = 70.0, 470.0, 820.0, 46.0
    small = "fx-t fx-small"
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(cx - r_out if wide else 18, 40 if wide else 34, "黃道釋放：每個星座的年數", "fx-t"))
    a = 180.0
    for key in SIGN_KEYS:
        years = releasing.SIGN_PERIOD_YEARS[key]
        sweep = years / total * 360
        differs = years != minor[lords[key]]
        out.append(_fx.path(_wedge(cx, cy, r_in, r_out, a, a + sweep), "fx-b-beam" if differs else "fx-cell"))
        mid = a + sweep / 2
        x, y = _polar(cx, cy, r_name, mid)
        out.append(_fx.text(x, y + 5, SIGN[key], small + (" fx-key" if differs else ""), "middle"))
        x, y = _polar(cx, cy, r_years, mid)
        out.append(_fx.text(x, y + 5, bound.num(str(years)), small + " fx-num" + (" fx-key" if differs else ""),
                            "middle"))
        a += sweep
    out.append(_fx.text(cx, cy - 4, f"一圈 {bound.num(str(total))} 年", "fx-t", "middle"))
    out.append(_fx.text(cx, cy + 18, "（比例畫）", small, "middle"))
    note_y = cy + r_out + (30 if wide else 26)
    out.append(_fx.text(cx - r_out if wide else 18, note_y, "排線：年數不等於守護行星小年的星座", small))
    # the decennial bar
    months = decennial["level_2"]
    whole = sum(item["months"] for item in months)
    head_x = bx - (16 if wide else 52)
    head_y = by0 - (44 if wide else 50)
    out.append(_fx.text(head_x, head_y, f"十年期：一段 {bound.num(str(whole))} 個月", "fx-t"))
    out.append(_fx.text(head_x, head_y + 22, f"{BODY[decennial['lord']]}那一段（{bound.num(decennial['start']['local_date'])} "
                        f"至 {bound.num(decennial['end']['local_date'])}）", small))
    Y = lambda m: by0 + m / whole * (by1 - by0)  # noqa: E731
    done, last = 0, -1e9
    for item in months:
        y0, y1 = Y(done), Y(done + item["months"])
        out.append(_fx.rect(bx, y0, bw, y1 - y0, "fx-cell"))
        mid = (y0 + y1) / 2
        out.append(_fx.glyph(item["lord"], bx + bw / 2, mid, 13 if wide else 12, "fx-mk-gl"))
        y = max(mid + 5, last + 20)
        out.append(_fx.text(bx + bw + 14, y, f"{BODY[item['lord']]}　{bound.num(str(item['months']))} 個月", small))
        last = y
        done += item["months"]
    out.append(_fx.text(bx + bw + 14, by1 + (26 if wide else 30), "每顆行星分到它的小年", small))
    out.append("</svg>")
    return "".join(out)


def _coordinate(years: list[dict]):
    """JD(UT) → completed years as a real number, linear within each return year."""
    starts = [item["start"]["jd_ut"] for item in years] + [years[-1]["end"]["jd_ut"]]

    def at(jd: float) -> float:
        if jd <= starts[0]:
            return 0.0
        for k in range(len(starts) - 1):
            if jd < starts[k + 1]:
                return years[k]["completed_years"] + (jd - starts[k]) / (starts[k + 1] - starts[k])
        return float(years[-1]["completed_years"] + 1)
    return at


def _life_rows(lifetime: dict, years: list[dict]) -> list[dict]:
    """Figure 4's rows: each a label and segments (from, to in completed years, name, short name)."""
    at = _coordinate(years)
    methods = lifetime["annual_methods"]
    first, last = WINDOW[0] - 1, WINDOW[1]

    def clip(periods, name, short, end_key="end"):
        segments = []
        for p in periods:
            a, b = at(p["start"]["jd_ut"]), at(p[end_key]["jd_ut"])
            if b > first and a < last:
                segments.append({"from": max(a, first), "to": min(b, last), "name": name(p), "short": short(p)})
        return segments

    firdaria = methods["firdaria"]["periods"]
    subs = [s for p in firdaria for s in (p.get("level_2") or [])]
    rows = [
        {"key": "profection", "label": "年度小限", "head": ("", "小限"), "segments": [
            {"from": float(item["completed_years"]), "to": float(item["completed_years"] + 1),
             "name": SIGN[item["profection_sign"]], "short": SHORT[item["year_lord"]],
             "sign": item["profection_sign"], "lord": BODY[item["year_lord"]]}
            for item in years if WINDOW[0] <= item["year_of_life"] <= WINDOW[1]]},
        {"key": "firdaria", "label": "法達・主期", "head": ("法達", "主期"),
         "segments": clip(firdaria, lambda p: BODY[p["level_1_lord"]], lambda p: SHORT.get(p["level_1_lord"], ""))},
        {"key": "firdaria-sub", "label": "法達・子期", "head": ("法達", "子期"),
         "segments": clip(subs, lambda p: BODY[p["level_2_partner"]], lambda p: SHORT[p["level_2_partner"]])},
    ]
    for release in methods["zodiacal_releasing"]["releases"]:
        lot = {"fortune": "命運點", "spirit": "精神點"}[release["releasing_from"]]
        rows.append({"key": f"zr-{release['releasing_from']}", "label": f"黃道釋放・{lot}", "head": ("黃道釋放", lot),
                     "segments": clip(release["periods"], lambda p: SIGN[p["sign"]], lambda p: SIGN[p["sign"]],
                                      "effective_end")})
    rows.append({"key": "decennials", "label": "十年期・第一層", "head": ("", "十年期"),
                 "segments": clip(methods["decennials"]["periods"], lambda p: BODY[p["lord"]],
                                  lambda p: SHORT[p["lord"]])})
    for row in rows:
        if not row["segments"] or row["segments"][0]["from"] > first + 1e-9 or row["segments"][-1]["to"] < last - 1e-9:
            raise RuntimeError(f"{row['label']}: the product's periods do not cover years {WINDOW}")
    return rows


def _year_sentence(item: dict, rows: list[dict], bound: _fx.Bound) -> str:
    c0, c1 = item["completed_years"], item["completed_years"] + 1

    def names(row: dict) -> str:
        return "→".join(s["name"] for s in row["segments"] if s["to"] > c0 + 1e-9 and s["from"] < c1 - 1e-9)

    by = {row["key"]: row for row in rows}
    return (f"第 {bound.num(str(item['year_of_life']))} 年（{bound.num(item['start']['local_date'])} 至 "
            f"{bound.num(item['end']['local_date'])}）：年度小限{SIGN[item['profection_sign']]}，年主星"
            f"{BODY[item['year_lord']]}；法達{names(by['firdaria'])}主期，子期{names(by['firdaria-sub'])}；"
            f"黃道釋放從命運點起在{names(by['zr-fortune'])}，從精神點起在{names(by['zr-spirit'])}；"
            f"十年期{names(by['decennials'])}。")


def _lifespan(layout: str, fid: str, years: list[dict], rows: list[dict], bound: _fx.Bound) -> str:
    """Figure 4: the window's years across (wide) or down (narrow), a row per technique,
    a cursor per year for the slider."""
    wide = layout == "fx-wide"
    first, last = WINDOW[0] - 1, WINDOW[1]
    if wide:
        W = _fx.WIDE
        a0, a1, top, rh, bh = 186.0, 850.0, 56.0, 46.0, 36.0
        H = top + rh * len(rows) + 64
    else:
        W = _fx.NARROW
        a0, a1 = 96.0, 96.0 + (last - first) * 22.0
        H = a1 + 22
        columns = [(46.0, 50.0), (100.0, 44.0), (148.0, 30.0), (182.0, 48.0), (234.0, 48.0), (286.0, 42.0)]
    P = lambda c: a0 + (c - first) / (last - first) * (a1 - a0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    # The labels inside the bars go on top of the cursor, each with a paper halo.
    labels: list[str] = []
    shown = [item for item in years if WINDOW[0] <= item["year_of_life"] <= WINDOW[1]]
    for index, row in enumerate(rows):
        if wide:
            y = top + index * rh
            out.append(_fx.text(a0 - 12, y + bh / 2 + 6, row["label"], "fx-t fx-small", "end"))
        else:
            x, w = columns[index]
            group, name = row["head"]
            out.append(_fx.text(x + w / 2, a0 - 12, name, "fx-t fx-small", "middle"))
        for segment in row["segments"]:
            p0, p1 = P(segment["from"]), P(segment["to"])
            if wide:
                out.append(_fx.rect(p0, y, p1 - p0, bh, "fx-cell"))
                mid = ((p0 + p1) / 2, y + bh / 2)
            else:
                out.append(_fx.rect(x, p0, w, p1 - p0, "fx-cell"))
                mid = (x + w / 2, (p0 + p1) / 2)
            if row["key"] == "profection":
                if wide:
                    labels.append(_fx.glyph(segment["sign"], mid[0], y + 11, 12, "fx-mk-gl"))
                    labels.append(_fx.text(mid[0], y + bh - 5, segment["short"], "fx-t fx-small", "middle"))
                else:
                    labels.append(_fx.glyph(segment["sign"], x + 13, mid[1], 11, "fx-mk-gl"))
                    labels.append(_fx.text(x + 36, mid[1] + 5, segment["short"], "fx-t fx-small", "middle"))
                continue
            extent = p1 - p0
            room = extent if wide else w
            text = segment["name"] if room >= 15 * len(segment["name"]) + 6 else segment["short"]
            if (extent if wide else p1 - p0) < 16:
                continue
            if not wide and text != segment["short"] and w < 13 * len(text) + 4:
                text = segment["short"]
            # a long bar's name sits near its start, out of the way of most cursor positions
            if wide and extent > 90:
                labels.append(_fx.text(p0 + 12, mid[1] + 5, text, "fx-t fx-small fx-key"))
            elif not wide and p1 - p0 > 90:
                labels.append(_fx.text(mid[0], p0 + 22, text, "fx-t fx-small fx-key", "middle"))
            else:
                labels.append(_fx.text(mid[0], mid[1] + 5, text, "fx-t fx-small fx-key", "middle"))
    if not wide:
        out.append(_fx.text(columns[1][0] + (columns[2][0] + columns[2][1] - columns[1][0]) / 2, a0 - 32, "法達",
                            "fx-t fx-small", "middle"))
        out.append(_fx.text(columns[3][0] + (columns[4][0] + columns[4][1] - columns[3][0]) / 2, a0 - 32, "黃道釋放",
                            "fx-t fx-small", "middle"))
    # the years
    for item in shown:
        c = item["completed_years"]
        n = item["year_of_life"]
        if wide:
            base = top + rh * len(rows) - 4
            out.append(_fx.line(P(c), base, P(c), base + 5, "fx-axis"))
            if (n - WINDOW[0]) % 4 == 0:
                out.append(_fx.text((P(c) + P(c + 1)) / 2, base + 22, bound.scale(str(n)), "fx-t fx-small fx-num",
                                    "middle"))
        elif (n - WINDOW[0]) % 2 == 0:
            out.append(_fx.text(40, (P(c) + P(c + 1)) / 2 + 4, bound.scale(str(n)), "fx-t fx-small fx-num", "end"))
    if wide:
        base = top + rh * len(rows) - 4
        out.append(_fx.line(a0, base, a1, base, "fx-axis"))
        out.append(_fx.text(a0 - 12, base + 22, "第幾年", "fx-t fx-small", "end"))
    else:
        out.append(_fx.text(18, 30, "第幾年（往下）", "fx-t fx-small fx-dim"))
    # the cursor: one group per year
    default = YEAR_OF_LIFE - WINDOW[0]
    for step, item in enumerate(shown):
        c = item["completed_years"]
        if wide:
            body = (_fx.rect(P(c), top - 8, P(c + 1) - P(c), rh * len(rows) - 2, "fx-cursor")
                    + _fx.text((P(c) + P(c + 1)) / 2, top - 16, f"第 {bound.num(str(item['year_of_life']))} 年",
                               "fx-t fx-small", "middle"))
        else:
            body = _fx.rect(columns[0][0] - 4, P(c), columns[-1][0] + columns[-1][1] - columns[0][0] + 8,
                            P(c + 1) - P(c), "fx-cursor")
        out.append(_fx.step_group(step, default, body))
    out += labels
    out.append("</svg>")
    return "".join(out)


def _life_table(shown: list[dict], rows: list[dict], bound: _fx.Bound) -> str:
    by = {row["key"]: row for row in rows}

    def names(key: str, item: dict) -> str:
        c0, c1 = item["completed_years"], item["completed_years"] + 1
        return "→".join(s["name"] for s in by[key]["segments"] if s["to"] > c0 + 1e-9 and s["from"] < c1 - 1e-9)

    body = "".join(
        f'<tr><th scope="row">第 {bound.num(str(item["year_of_life"]))} 年</th>'
        f'<td class="n">{bound.num(item["start"]["local_date"])}</td>'
        f'<td>{SIGN[item["profection_sign"]]}（{BODY[item["year_lord"]]}）</td>'
        f'<td>{names("firdaria", item)}</td><td>{names("firdaria-sub", item)}</td>'
        f'<td>{names("zr-fortune", item)}</td><td>{names("zr-spirit", item)}</td><td>{names("decennials", item)}</td></tr>'
        for item in shown)
    head = "".join(f'<th scope="col">{h}</th>' for h in (
        "年", "起", "年度小限（年主星）", "法達主期", "法達子期", "黃道釋放（命運點）", "黃道釋放（精神點）", "十年期"))
    return ('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
            f'<table class="ar-table fx-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></details>')


def _figures(lifetime: dict) -> dict[str, str]:
    years = _years(lifetime)
    data = page_methods_time_lords._backend()
    firdaria, releasing = data["firdaria"], data["releasing"]
    with backend_on_path():
        from app.core import planetary_years

        minor = dict(planetary_years.MINOR_YEARS)

    # Figure 1.
    b1 = _fx.Bound()
    start = SIGN_KEYS.index(years[0]["profection_sign"])
    signs: list[dict] = []
    for i in range(12):
        key = SIGN_KEYS[(start + i) % 12]
        held = [item["year_of_life"] for item in years if item["profection_sign"] == key]
        signs.append({"key": key, "name": SIGN[key], "lord_name": BODY[DOMICILES[key]], "years": held})
    notes = []
    for i, item in enumerate(signs):
        listed = "、".join(b1.num(str(y)) for y in item["years"])
        where = "（上升星座）" if i == 0 else f"（從上升星座數第 {b1.num(str(i + 1))} 個）"
        notes.append(_fx.Note(item["key"], None, f"{item['name']}{where}：第 {listed} 年，年主星{item['lord_name']}。"))
    table1 = "".join(
        f'<tr data-fx-key="{item["key"]}"><th scope="row">{item["name"]}</th><td>{item["lord_name"]}</td>'
        f'<td>{"、".join(b1.num(str(y)) for y in item["years"])}</td></tr>' for item in signs)
    wheel = _fx.figure(
        fid="fig-profection-wheel",
        title="年度小限：從上升星座起，每年往後推一個星座",
        caption=(f"<b>{b1.label('圖 1')}</b>同一張合成星盤（{b1.label('§06')} 的示範出生時刻）的年度小限。左邊九點鐘方向是上升星座"
                 f"{signs[0]['name']}，之後依黃道順序逆時針排；每格寫星座、它的守護行星，以及落到這一格的前 "
                 f"{b1.scale(str(WHEEL_YEARS))} 個年份。第 {b1.num(str(signs[0]['years'][0]))} 年是上升星座本身，"
                 f"第 {b1.num(str(signs[0]['years'][1]))} 年又回到這裡。"
                 "數字取自本站年度計算服務的回應。"),
        wide=_profection_wheel("fx-wide", "fig-profection-wheel", signs, b1),
        narrow=_profection_wheel("fx-narrow", "fig-profection-wheel", signs, b1),
        notes=notes, idle="用 Tab 鍵移到一個星座上，或用滑鼠指著它，這裡會寫出輪到它的年份與年主星。",
        table=('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
               '<table class="ar-table fx-table"><thead><tr><th scope="col">星座</th><th scope="col">年主星</th>'
               f'<th scope="col">第幾年（前 {b1.num(str(len(years)))} 年）</th></tr></thead><tbody>{table1}</tbody>'
               '</table></div></details>'),
    )

    # Figure 2: the product's day chart follows the diurnal order it draws.
    b2 = _fx.Bound()
    drawn = [p["level_1_lord"] for p in lifetime["annual_methods"]["firdaria"]["periods"]][:len(firdaria.DIURNAL_SEQUENCE)]
    if tuple(drawn) != tuple(firdaria.DIURNAL_SEQUENCE):
        raise RuntimeError(f"the demonstration chart's firdaria {drawn} do not follow the diurnal order drawn")
    for p in lifetime["annual_methods"]["firdaria"]["periods"]:
        if p["cycle_index"] == 0 and abs(p["end_year"] - p["start_year"] - firdaria.PERIOD_YEARS[p["level_1_lord"]]) > 1e-9:
            raise RuntimeError(f"{p['level_1_lord']}: the product's period is not its table's years")
    for _, _, label in FIRDARIA_VARIANTS:
        b2.label(label)
    band = _fx.figure(
        fid="fig-firdaria",
        title="法達的九段主期，日盤與夜盤的兩種順序",
        caption=(f"<b>{b2.label('圖 2')}</b>法達從出生起的 {b2.num(str(firdaria.CYCLE_YEARS))} 年，一段是一個主期，寬度照年數畫。"
                 "細刻度把行星的主期七等分成子期；單線排線是月亮的兩個交點，不分子期。按鈕切換日盤與夜盤的兩種順序，"
                 "年數與順序都取自本站計算用的表，和方法頁那張表相同。"),
        wide=_firdaria_band("fx-wide", "fig-firdaria", firdaria, b2),
        narrow=_firdaria_band("fx-narrow", "fig-firdaria", firdaria, b2),
        notes=[], idle="", variants=tuple((key, label) for key, _, label in FIRDARIA_VARIANTS),
        switch_label="切換日盤與夜盤的順序",
    )

    # Figure 3: the Saturn decennial of the same chart, its months the minor years.
    b3 = _fx.Bound()
    (decennial,) = [p for p in lifetime["annual_methods"]["decennials"]["periods"] if p.get("level_2")]
    for item in decennial["level_2"]:
        if item["months"] != minor[item["lord"]]:
            raise RuntimeError(f"{item['lord']}: {item['months']} months, its minor years are {minor[item['lord']]}")
    if sum(item["months"] for item in decennial["level_2"]) != decennial["months"]:
        raise RuntimeError("the sub-periods do not fill the decennial period")
    differing = "、".join(SIGN[k] for k in SIGN_KEYS if releasing.SIGN_PERIOD_YEARS[k] != minor[data["lords"][k]])
    rings = _fx.figure(
        fid="fig-minor-years",
        title="黃道釋放的星座年數，與十年期一段分給七顆行星的月數",
        caption=(f"<b>{b3.label('圖 3')}</b>左：黃道釋放每個星座的年數，扇形照年數比例畫，一圈 "
                 f"{b3.num(str(sum(releasing.SIGN_PERIOD_YEARS.values())))} 年；排線的{differing}不等於守護行星的小年。"
                 f"右：同一張合成星盤的十年期，{BODY[decennial['lord']]}那一段的 {b3.num(str(decennial['months']))} 個月，"
                 "依七顆行星的小年分成七小段，順序取自本站年度計算服務的回應。"),
        wide=_minor_years("fx-wide", "fig-minor-years", releasing, data["lords"], minor, decennial, b3),
        narrow=_minor_years("fx-narrow", "fig-minor-years", releasing, data["lords"], minor, decennial, b3),
        notes=[], idle="",
    )

    # Figure 4.
    b4 = _fx.Bound()
    rows = _life_rows(lifetime, years)
    shown = [item for item in years if WINDOW[0] <= item["year_of_life"] <= WINDOW[1]]
    steps = [_fx.Note(None, None, _year_sentence(item, rows, b4), step=i) for i, item in enumerate(shown)]
    life = _fx.figure(
        fid="fig-lifespan",
        title=f"同一張合成盤第 {WINDOW[0]} 到第 {WINDOW[1]} 年的時間主星",
        caption=(f"<b>{b4.label('圖 4')}</b>同一張合成星盤從第 {b4.scale(str(WINDOW[0]))} 到第 {b4.scale(str(WINDOW[1]))} 年，"
                 "每一排是一種技法的一層：年度小限每年一格（星座符號與年主星），法達的主期與子期，黃道釋放從兩個點起的大期，"
                 f"十年期的第一層。框線是第 {b4.num(str(YEAR_OF_LIFE))} 年，可以拖拉選別的年。"
                 "數字取自本站年度計算服務的回應。"),
        wide=_lifespan("fx-wide", "fig-lifespan", years, rows, b4),
        narrow=_lifespan("fx-narrow", "fig-lifespan", years, rows, b4),
        notes=steps, idle="拖拉選一年，這裡會寫出那一年各技法輪到誰。",
        steps=len(shown), default_step=YEAR_OF_LIFE - WINDOW[0], scrub_label="第幾年",
        table=_life_table(shown, rows, b4),
    )
    for markup, bound in ((wheel, b1), (band, b2), (rings, b3), (life, b4)):
        found = _fx.problems(markup, bound)
        if found:
            raise RuntimeError("figure check: " + "; ".join(found))
    planets = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "north_node", "south_node")
    return {"fx-defs": _fx.defs(planets + SIGN_KEYS), "profection-wheel": wheel, "firdaria-band": band,
            "minor-years": rings, "lifespan": life}


def _table(rows: list[dict]) -> str:
    lines = []
    for row in rows:
        if row["label"] == "月小限":
            continue
        for period in row["periods"]:
            lines.append(
                f'          <tr><td>{row["technique"]}</td><td>{row["level"]}</td><td>{period["who"]}</td>'
                f'<td>{period["from_fortune"]}</td>'
                f'<td class="n">{period["start"]["local_date"]}</td><td class="n">{period["end"]["local_date"]}</td></tr>'
            )
    return "\n".join(lines)


def _months(answer: dict) -> tuple[str, float, float]:
    periods = answer["annual_methods"]["monthly_profection"]["periods"]
    lines, lengths = [], []
    for m in periods:
        days = m["end"]["jd_ut"] - m["start"]["jd_ut"]
        lengths.append(days)
        lines.append(
            f'          <tr><td class="n">{m["month_of_year"]}</td><td>{SIGN[m["sign"]]}</td>'
            f'<td>{BODY[m["domicile_lord"]]}</td><td class="n">{m["start"]["local_date"]}</td>'
            f'<td class="n">{days:.1f}</td></tr>'
        )
    return "\n".join(lines), min(lengths), max(lengths)


def _spoken(local_date: str) -> str:
    year, month, day = (int(part) for part in local_date.split("-"))
    return f"{year} 年 {month} 月 {day} 日"


def build() -> tuple[dict[str, str], list[str]]:
    answer = _answer()
    methods = answer["annual_methods"]
    if not methods["firdaria"]["sect"]["is_day"]:
        raise RuntimeError("the article describes the demonstration chart as a day chart")
    # The evidence-scope note: both the Ascendant and Fortune lie within 2° of
    # the start of their sign.
    ascendant = answer["natal_anchor"]["ascendant"]["longitude_deg"]
    releases = {r["releasing_from"]: r for r in methods["zodiacal_releasing"]["releases"]}
    fortune, spirit = releases["fortune"], releases["spirit"]
    fortune_degree = fortune["start_lot_longitude_deg"]
    if not all(longitude % 30 < 2 for longitude in (ascendant, fortune_degree)):
        raise RuntimeError("the article says the Ascendant and Fortune are under 2° into their signs")
    rows = _rows(answer)
    months, shortest, longest = _months(answer)
    data = page_methods_time_lords._backend()
    firdaria, releasing = data["firdaria"], data["releasing"]
    gap, _, _ = page_methods_time_lords._notation_gap(firdaria)
    with backend_on_path():
        from app.core import planetary_years

        minor_total = sum(planetary_years.MINOR_YEARS.values())
    decennial = methods["decennials"]
    months_per_period = decennial["year_model"]["months_per_level_1"]
    if minor_total != months_per_period:
        raise RuntimeError("the minor years no longer add up to one decennial period")
    period_days = int(decennial["periods"][0]["duration_days"])
    year = answer["year_boundary"]
    profection = methods["annual_profection"]
    (spirit_major,) = [p for p in spirit["periods"]
                       if _overlaps(p, year["start"]["jd_ut"], year["end"]["jd_ut"])]
    quoted = [
        f"九段合計 {firdaria.CYCLE_YEARS} 年",
        f"十二個星座一圈合計 {sum(releasing.SIGN_PERIOD_YEARS.values())} 年",
        f"每段 {months_per_period} 個月",
        f"一段是 {period_days:,} 日",
        f"兩種讀法最多相差約 {gap:.1f} 日",
        f"第 {YEAR_OF_LIFE} 年",
        f"從 {_spoken(year['start']['local_date'])}到 {_spoken(year['end']['local_date'])}",
        f"年度小限是{SIGN[profection['profected_sign']]}，年主星是{BODY[profection['lord']['body_key']]}",
        f"命運點在{SIGN[fortune['start_sign']]}、精神點在{SIGN[spirit['start_sign']]}",
        f"從命運點數第 {spirit_major['position_from_fortune']} 個星座",
        f"最短 {shortest:.1f} 日、最長 {longest:.1f} 日",
        f"圖 4 畫的是第 {WINDOW[0]} 到第 {WINDOW[1]} 年，框線預設在第 {YEAR_OF_LIFE} 年",
    ]
    blocks = {
        **_figures(_lifetime()),
        "year-periods": _table(rows),
        "year-months": months,
    }
    return blocks, quoted
