"""〈西洋占星要不要換真太陽時？〉: figure 1 (the product's time pipeline,
and the same clock time first turned into true solar time), figure 2 (the
example's clock time, local mean time and true solar time on one axis),
figure 3 (how far that double count moves the chart through 2025, Taipei and
Jincheng, with a switch between the two) and the numbers the prose quotes.

Figures 1 and 2 and the example are the product's own answers for the
synthetic instant 1990-11-03 14:00 Taipei (GeoNames 1668341): the product
reports the true solar time it computes for reference, and a second request
enters that true solar time as if it were the clock reading.  Figure 2's local
mean time is the product's UTC plus the longitude; it plus the product's
equation of time must give the product's true solar time.  Figure 3 and the
yearly share use Swiss Ephemeris (swe.time_equ, the function the product
reports the equation of time from, and houses_ex) every 10 minutes of 2025.
The one value checked against a second algorithm: the product's equation of
time against NOAA's spreadsheet formula at the same instant.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import _fx, _noaa
from ._common import SIGNS, product_charts, swiss


FRAGMENT = "blog-true-solar-time"
TAIPEI = (25.05306, 121.52639)
JINCHENG = (24.43415, 118.31712)
ZONE_MERIDIAN = 120.0
EXAMPLE = datetime(1990, 11, 3, 14, 0, 0)
YEAR = 2025


def _request(clock: datetime) -> dict:
    return {"birth_time_precision": "exact",
            "datetime": {"year": clock.year, "month": clock.month, "day": clock.day,
                         "hour": clock.hour, "minute": clock.minute, "second": clock.second},
            "location": {"latitude": TAIPEI[0], "longitude": TAIPEI[1]},
            "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
            "options": {"house_system": "W", "include_houses": True}}


def _example() -> dict:
    with product_charts() as post:
        right = post(_request(EXAMPLE))
        time = right["astronomical_data"]["time"]
        step, = [s for s in right["calculation_trace"] if s["title"].startswith("均時差與真太陽時")]
        solar = datetime.strptime(time["apparent_solar_time"], "%Y-%m-%d %H:%M:%S")
        if step["result"]["真太陽時(參考)"] != time["apparent_solar_time"]:
            raise RuntimeError("the trace and the time block disagree on the true solar time")
        wrong = post(_request(solar))
    e = {"step_title": step["title"], "solar": solar, "eot": time["equation_of_time_minutes"]}
    for name, body in (("right", right), ("wrong", wrong)):
        t = body["astronomical_data"]["time"]
        e[name] = {"utc": t["utc_time"][11:16], "last": t["last_hours"], "jd": t["jd_ut"],
                   "asc": body["astronomical_data"]["angles"]["sign_positions"]["asc"]}
    utc = datetime.strptime(e["right"]["utc"], "%H:%M").replace(year=EXAMPLE.year, month=EXAMPLE.month,
                                                                 day=EXAMPLE.day, tzinfo=timezone.utc)
    e["noaa_eot"] = _noaa.sun(_noaa.julian_day(utc))["equation_of_time_minutes"]
    return e


def _year() -> dict:
    out: dict = {"days": [], "share": {}}
    with swiss() as swe:
        start = datetime(YEAR, 1, 1, tzinfo=ZoneInfo("Asia/Taipei"))
        for day in range(365):
            utc = (start + timedelta(days=day, hours=12)).astimezone(timezone.utc)
            j = swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60)
            out["days"].append(swe.time_equ(j) * 1440)
        for name, (lat, lon) in (("臺北", TAIPEI), ("金門", JINCHENG)):
            wrong = total = 0
            for step in range(365 * 144):
                utc = (start + timedelta(minutes=10 * step)).astimezone(timezone.utc)
                j = swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60)
                shift = (lon - ZONE_MERIDIAN) * 4 + swe.time_equ(j) * 1440  # minutes
                a = swe.houses_ex(j, lat, lon, b"W")[1][0]
                b = swe.houses_ex(j + shift / 1440, lat, lon, b"W")[1][0]
                total += 1
                wrong += int(a // 30) != int(b // 30)
            out["share"][name] = wrong / total
    eot = out["days"]
    out["eot_range"] = (min(eot), max(eot))
    return out


def _hm(hours: float) -> str:
    total = round(hours * 60) % 1440
    return f"{total // 60:02d}:{total % 60:02d}"


def _asc(position: list) -> str:
    degrees, rest = position[1].split("°")
    return f"{SIGNS[position[0]]} {degrees}°{rest.split(chr(8242))[0]}′"


def _signed(minutes: float) -> str:
    return f"{'+' if minutes >= 0 else '−'}{abs(minutes):.1f}"


def _clock(minutes: float) -> str:
    """「14:06:06」: a time of day from minutes after midnight, whole seconds."""
    total = round(minutes * 60) % 86400
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


# --- figure 1: the two pipelines ------------------------------------------------

def _lanes(e: dict, bound: _fx.Bound) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """(lane title, [(step, value, tag)]): tag 「…經度」 marks a step that uses the
    birthplace's longitude; 「final」 the ascendant."""
    lon_minutes = (TAIPEI[1] - ZONE_MERIDIAN) * 4
    clock = bound.num(f"{EXAMPLE:%H:%M}")
    return [
        ("本站的做法", [
            ("出生紀錄的鐘面時間", f"{clock}（臺北）", ""),
            (f"依時區 {bound.label('UTC+8')} 換成世界時", bound.num(e["right"]["utc"]), ""),
            (f"加上經度 {bound.num(f'{TAIPEI[1]:.2f}')}°，得地方恆星時", bound.num(_hm(e["right"]["last"])), "只用一次經度"),
            ("上升點", bound.num(_asc(e["right"]["asc"])), "final"),
        ]),
        ("先換真太陽時", [
            ("出生紀錄的鐘面時間", f"{clock}（臺北）", ""),
            (f"經度 {bound.num(_signed(lon_minutes))} 分、均時差 {bound.num(_signed(e['eot']))} 分",
             f"真太陽時 {bound.num(f'{e['solar']:%H:%M}')}", "第一次用經度"),
            ("把它當成鐘面時間，換成世界時", bound.num(e["wrong"]["utc"]), ""),
            ("再加一次經度，得地方恆星時", bound.num(_hm(e["wrong"]["last"])), "第二次用經度"),
            ("上升點", bound.num(_asc(e["wrong"]["asc"])), "final"),
        ]),
    ]


def _box(x: float, y: float, w: float, h: float, step: str, value: str, tag: str, wide: bool) -> list[str]:
    out = [_fx.rect(x, y, w, h, "fx-track")]
    pad = 14
    if tag.endswith("經度"):
        out.append(_fx.rect(x, y, 12, h, "fx-fill-hatch"))
        out.append(_fx.line(x + 12, y, x + 12, y + h, "fx-edge"))
        pad = 24
    if tag == "final":
        out.append(_fx.rect(x + 3, y + 3, w - 6, h - 6, "fx-inset-frame"))
    out.append(_fx.text(x + pad, y + (24 if wide else 21), step, "fx-t fx-small"))
    out.append(_fx.text(x + pad, y + h - (14 if wide else 12), value, "fx-t fx-num"))
    if tag.endswith("經度"):
        out.append(_fx.text(x + w - 12, y + h - (14 if wide else 12), tag, "fx-t fx-small", "end"))
    return out


def _down(x: float, y0: float, y1: float) -> list[str]:
    return [_fx.line(x, y0, x, y1 - 6, "fx-axis"),
            _fx.path(f"M{_fx.f(x)} {_fx.f(y1)} l-5 -8 h10 z", "fx-arrow")]


def _pipelines(layout: str, fid: str, e: dict, gained: str, moved: str, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    lanes = _lanes(e, bound)
    if wide:
        W, H = _fx.WIDE, 512
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        bw, bh, gap = 404, 62, 18
        for (title, boxes), x in zip(lanes, (24, 452)):
            out.append(_fx.text(x, 42, title, "fx-t"))
            y = 58
            for i, (step, value, tag) in enumerate(boxes):
                out += _box(x, y, bw, bh, step, value, tag, True)
                if i < len(boxes) - 1:
                    out += _down(x + bw / 2, y + bh, y + bh + gap)
                y += bh + gap
        legend = 58 + 4 * (bh + gap) + 18
        out.append(_fx.rect(24, legend - 14, 12, 18, "fx-fill-hatch"))
        out.append(_fx.text(46, legend, "排線：用到出生地經度的一步", "fx-t fx-small"))
        out.append(_fx.text(24, legend + 26, "雙框：最後得到的上升點", "fx-t fx-small"))
        out.append(_fx.text(24, H - 30, f"先換真太陽時，經度就算了兩次：地方恆星時多了約 {gained} 分鐘，上升點差了 {moved} 度",
                            "fx-t"))
    else:
        W, H = _fx.NARROW, 832
        out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
        bw, bh, gap = 312, 54, 14
        y = 30
        for title, boxes in lanes:
            out.append(_fx.text(14, y, title, "fx-t"))
            y += 14
            for i, (step, value, tag) in enumerate(boxes):
                out += _box(14, y, bw, bh, step, value, tag, False)
                if i < len(boxes) - 1:
                    out += _down(14 + bw / 2, y + bh, y + bh + gap)
                y += bh + gap
            y += 26
        out.append(_fx.rect(14, y - 13, 12, 16, "fx-fill-hatch"))
        out.append(_fx.text(34, y, "排線：用到出生地經度的一步", "fx-t fx-small"))
        out.append(_fx.text(14, y + 20, "雙框：最後得到的上升點", "fx-t fx-small"))
        out.append(_fx.text(14, y + 50, "先換真太陽時，經度就算了兩次：", "fx-t"))
        out.append(_fx.text(14, y + 72, f"地方恆星時多了約 {gained} 分鐘，", "fx-t"))
        out.append(_fx.text(14, y + 94, f"上升點差了 {moved} 度", "fx-t"))
        if y + 94 > H - 14:
            raise RuntimeError("figure 1 outgrew its phone drawing")
    out.append("</svg>")
    return "".join(out)


def _pipeline_table(e: dict, bound: _fx.Bound) -> str:
    rows = (("世界時", e["right"]["utc"], e["wrong"]["utc"]),
            ("地方恆星時", _hm(e["right"]["last"]), _hm(e["wrong"]["last"])),
            ("上升點", _asc(e["right"]["asc"]), _asc(e["wrong"]["asc"])))
    body = "".join(f'<tr><th scope="row">{name}</th><td class="n">{bound.num(a)}</td><td class="n">{bound.num(b)}</td></tr>'
                   for name, a, b in rows)
    return ('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
            '<table class="ar-table fx-table"><thead><tr><th scope="col">　</th><th scope="col">本站的做法</th>'
            f'<th scope="col">先換真太陽時</th></tr></thead><tbody>{body}</tbody></table></div></details>')


# --- figure 2: three readings of one instant -----------------------------------

def _three(layout: str, fid: str, times: dict, texts: dict, bound: _fx.Bound) -> str:
    """The clock time, local mean time and true solar time of the example on one axis."""
    wide = layout == "fx-wide"
    clock, mean, solar = times["clock"], times["mean"], times["solar"]
    t0, t1 = clock - 3, solar + 4
    if wide:
        W, H = _fx.WIDE, 330
        L, R, AX = 60.0, 820.0, 236.0
    else:
        W, H = _fx.NARROW, 340
        L, R, AX = 24.0, 316.0, 244.0
    X = lambda m: L + (R - L) * (m - t0) / (t1 - t0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    rows = (("clock", clock, texts["clock"]), ("mean", mean, texts["mean"]), ("solar", solar, texts["solar"]))
    for i, (key, minute, (name, note)) in enumerate(rows):
        # Each reading's words beside its own mark, on the side away from the
        # earlier marks' leaders, so no leader crosses a later row's words.
        x = X(minute)
        y = (70 + i * 54) if wide else (46 + i * 64)
        dx, anchor = (14, None) if key != "solar" else (-14, "end")
        out.append(_fx.text(x + dx, y + 6, name, "fx-t fx-num", anchor))
        out.append(_fx.text(x + dx, y + (28 if wide else 25), note, "fx-t fx-small fx-dim", anchor))
        my = y
        out.append(_fx.line(x, my, x, AX, "fx-sunline"))
        out.append(_fx.circle(x, my, 6, "fx-mk"))
    out.append(_fx.line(L, AX, R, AX, "fx-axis"))
    first = int(t0) + (-int(t0)) % 1
    for m in range(first, int(t1) + 1):
        major = m % (5 if wide else 10) == 0
        out.append(_fx.line(X(m), AX, X(m), AX + (7 if major else 3), "fx-axis"))
        if major:
            out.append(_fx.text(X(m), AX + 22, bound.scale(_clock(m)[:5]), "fx-t fx-small fx-num", "middle"))
    by = AX + (46 if wide else 44)
    for a, b, (amount, what) in ((clock, mean, texts["lon"]), (mean, solar, texts["eot"])):
        xa, xb = X(a), X(b)
        out.append(_fx.line(xa, by, xb, by, "fx-axis"))
        out.append(_fx.line(xa, by - 5, xa, by + 5, "fx-axis") + _fx.line(xb, by - 5, xb, by + 5, "fx-axis"))
        if wide:
            out.append(_fx.text((xa + xb) / 2, by + 24, f"{amount}（{what}）", "fx-t fx-small", "middle"))
        else:
            out.append(_fx.text((xa + xb) / 2, by + 20, amount, "fx-t fx-small fx-num", "middle"))
            out.append(_fx.text((xa + xb) / 2, by + 38, what, "fx-t fx-small", "middle"))
    out.append("</svg>")
    return "".join(out)


# --- figure 3: a year at Taipei and Jincheng ------------------------------------

PLACES = (("taipei", "臺北", TAIPEI), ("kinmen", "金門", JINCHENG))
YEAR_SPAN = 25.0
YEAR_IDLE = "用 Tab 鍵移到圖上的圓點，或用滑鼠指著它，這裡會寫出那一點的分鐘數與它怎麼來。"


def _day(index: int) -> str:
    when = datetime(YEAR, 1, 1) + timedelta(days=index)
    return f"{when.month} 月 {when.day} 日"


def _year_sentences(year: dict, bound: _fx.Bound) -> list[_fx.Note]:
    days = year["days"]
    hi = max(range(len(days)), key=lambda i: days[i])
    lo = min(range(len(days)), key=lambda i: days[i])
    notes = []
    for variant, name, (_, lon) in PLACES:
        offset = (lon - ZONE_MERIDIAN) * 4
        for key, i, word in (("max", hi, "最多"), ("min", lo, "最少")):
            total = offset + days[i]
            change = "多出" if total >= 0 else "少掉"
            notes.append(_fx.Note(key, variant, (
                f"{name}：{bound.num(f'{YEAR}')} 年 {bound.num(_day(i))}前後{word}，地方恆星時{change} "
                f"{bound.num(f'{abs(total):.1f}')} 分鐘，也就是經度修正 {bound.num(_signed(offset))} 分鐘，"
                f"加上那天中午的均時差 {bound.num(_signed(days[i]))} 分鐘。")))
        side = "東" if lon > ZONE_MERIDIAN else "西"
        notes.append(_fx.Note("lon", variant, (
            f"{name}在東經 {bound.num(f'{lon:.2f}')} 度，在時區子午線東經 {bound.label('120')} 度以{side}，"
            f"經度修正是 {bound.num(_signed(offset))} 分鐘，一年都不變；曲線在這條虛線上下多遠，就是那天的均時差。")))
    return notes


def _year_art(layout: str, fid: str, year: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    days = year["days"]
    if wide:
        W, H = _fx.WIDE, 400
        L, R, T, B = 84.0, 852.0, 78.0, 330.0
    else:
        W, H = _fx.NARROW, 400
        L, R, T, B = 44.0, 326.0, 100.0, 342.0
    X = lambda day: L + (R - L) * day / (len(days) - 1)  # noqa: E731
    Y = lambda m: T + (B - T) * (YEAR_SPAN - m) / (2 * YEAR_SPAN)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(L if wide else 14, 36 if wide else 28, "地方恆星時多出的分鐘數（經度修正＋均時差）" if wide
                        else "地方恆星時多出的分鐘數", "fx-t fx-small" if not wide else "fx-t"))
    for m in (-20, -10, 0, 10, 20):
        out.append(_fx.line(L, Y(m), R, Y(m), "fx-axis" if m == 0 else "fx-hair"))
        out.append(_fx.text(L - 8, Y(m) + 5, bound.scale(f"{m:+d}".replace("-", "−") if m else "0"), "fx-t fx-small fx-num", "end"))
    starts = [datetime(YEAR, month, 1).timetuple().tm_yday - 1 for month in range(1, 13)] + [len(days) - 1]
    for month in range(12):
        out.append(_fx.line(X(starts[month]), B, X(starts[month]), B + 6, "fx-axis"))
        if wide or month % 3 == 0:
            out.append(_fx.text(X((starts[month] + starts[month + 1]) / 2), B + 24, bound.scale(f"{month + 1} 月"),
                                "fx-t fx-small", "middle"))
    hi = max(range(len(days)), key=lambda i: days[i])
    lo = min(range(len(days)), key=lambda i: days[i])
    curves = {}
    for variant, name, (_, lon) in PLACES:
        offset = (lon - ZONE_MERIDIAN) * 4
        curves[variant] = (offset, "M" + " L".join(f"{_fx.f(X(i))} {_fx.f(Y(offset + v))}" for i, v in enumerate(days)
                                                      if i % 2 == 0 or i == len(days) - 1))
    for variant, name, (_, lon) in PLACES:
        offset, d = curves[variant]
        body = []
        for other, other_name, _ in PLACES:
            if other != variant:
                o_offset, o_d = curves[other]
                body.append(_fx.path(o_d, "fx-curve-dim"))
                body.append(_fx.text(X(hi) - 14, Y(o_offset + days[hi]) - 8, other_name, "fx-t fx-small fx-dim", "end"))
        body.append(_fx.line(L, Y(offset), R, Y(offset), "fx-dash"))
        body.append(_fx.path(d, "fx-curve"))
        crest = 125  # the May crest: clear of the marks
        body.append(_fx.text(X(crest), Y(offset + days[crest]) - 14, name, "fx-t fx-key", "middle"))
        share = bound.num(f"{year['share'][name]:.0%}")
        if wide:
            body.append(_fx.text(R, 36, f"{name}：上升星座被換掉的時刻 {share}", "fx-t fx-small", "end"))
        else:
            body.append(_fx.text(14, 48, f"{name}：上升星座被換掉的時刻 {share}", "fx-t fx-small"))
            body.append(_fx.text(14, 66, "虛線：經度修正；曲線與虛線的距離：均時差", "fx-t fx-small fx-dim"))
        lon_label = f"經度修正 {bound.num(_signed(offset))} 分鐘"
        for key, i in (("max", hi), ("min", lo)):
            total = offset + days[i]
            x, y = X(i), Y(total)
            body.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{name}，{_day(i)}，'
                        f'{bound.num(_signed(total))} 分鐘">')
            body.append(_fx.circle(x, y, 16, "fx-hit") + _fx.circle(x, y, 6, "fx-mk"))
            dy = -14 if key == "max" else 26
            body.append(_fx.text(x, y + dy, bound.num(_signed(total)), "fx-t fx-small fx-num fx-key", "middle"))
            body.append("</g>")
        # On the dashed line below the year's highest point, where the curve is far above it.
        lx = X(hi)
        body.append(f'<g class="fx-row" data-fx-key="lon" tabindex="0" aria-label="{name}，{lon_label}">')
        body.append(_fx.circle(lx, Y(offset), 16, "fx-hit") + _fx.circle(lx, Y(offset), 5, "fx-mk"))
        body.append(_fx.text(lx + 10, Y(offset) + 24, lon_label, "fx-t fx-small fx-key", "end"))
        body.append("</g>")
        out.append(_fx.variant_group(variant, PLACES[0][0], "".join(body)))
    out.append("</svg>")
    return "".join(out)


def _year_table(year: dict, bound: _fx.Bound) -> str:
    lo, hi = year["eot_range"]
    rows = []
    for _, name, (_, lon) in PLACES:
        offset = (lon - ZONE_MERIDIAN) * 4
        rows.append(f'<tr><th scope="row">{name}</th><td class="n">{bound.num(f"{lon:.2f}")}°</td>'
                    f'<td class="n">{bound.num(_signed(offset))}</td><td class="n">{bound.num(_signed(offset + lo))}</td>'
                    f'<td class="n">{bound.num(_signed(offset + hi))}</td>'
                    f'<td class="n">{bound.num(f"{year["share"][name]:.0%}")}</td></tr>')
    return ('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
            '<table class="ar-table fx-table"><thead><tr><th scope="col">地點</th><th scope="col">東經</th>'
            '<th scope="col">經度修正（分鐘）</th><th scope="col">一年內最少（分鐘）</th>'
            '<th scope="col">一年內最多（分鐘）</th><th scope="col">上升星座被換掉的時刻</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></details>')


def _figures(e: dict, year: dict, gained: float, asc_moved: float) -> dict[str, str]:
    out = {}
    # figure 1
    bound = _fx.Bound()
    when = bound.num(f"{EXAMPLE.year} 年 {EXAMPLE.month} 月 {EXAMPLE.day} 日")
    g, m = bound.num(f"{gained:.1f}"), bound.num(f"{asc_moved:.1f}")
    out["two-pipelines"] = (_fx.figure(
        fid="fig-solar-pipelines", hero=True,
        title="同一個鐘面時刻的兩種算法：本站的做法，以及先換真太陽時再輸入",
        caption=(f"<b>{bound.label('圖 1')}</b>合成範例（不是任何人的出生資料）：{when}下午兩點，臺北。"
                 "「本站的做法」是本站的算法；「先換真太陽時」先把鐘面時間換成真太陽時，再把它當成鐘面時間填進同一個計算服務。"
                 "兩邊的數字都是本站計算服務的實際回應；排線標出用到出生地經度的一步。"),
        wide=_pipelines("fx-wide", "fig-solar-pipelines", e, g, m, bound),
        narrow=_pipelines("fx-narrow", "fig-solar-pipelines", e, g, m, bound),
        notes=[], idle="", table=_pipeline_table(e, bound)), bound)
    # figure 2
    bound = _fx.Bound()
    lon_minutes = (TAIPEI[1] - ZONE_MERIDIAN) * 4
    clock = EXAMPLE.hour * 60 + EXAMPLE.minute
    utc = datetime.strptime(e["right"]["utc"], "%H:%M")
    mean = (utc.hour * 60 + utc.minute + TAIPEI[1] * 4) % 1440
    solar = e["solar"].hour * 60 + e["solar"].minute + e["solar"].second / 60
    # True solar time (the product) = local mean time (UTC + longitude) + equation of time (the product).
    if abs(mean + e["eot"] - solar) * 60 > 1:
        raise RuntimeError(f"local mean time {mean} + equation of time {e['eot']} != true solar time {solar}")
    times = {"clock": clock, "mean": mean, "solar": solar}
    texts = {
        "clock": (f"鐘面時間 {bound.num(_clock(clock))}",
                  f"出生紀錄上的時間；臺灣用 {bound.label('UTC+8')}，對應東經 {bound.label('120')} 度"),
        "mean": (f"地方平時 {bound.num(_clock(mean))}", f"依出生地經度（臺北東經 {bound.num(f'{TAIPEI[1]:.2f}')} 度）"),
        "solar": (f"真太陽時 {bound.num(_clock(solar))}", "日晷上的時間"),
        "lon": (f"{bound.num(_signed(lon_minutes))} 分", "經度修正"),
        "eot": (f"{bound.num(_signed(e['eot']))} 分", "均時差"),
    }
    narrow_texts = dict(texts, clock=(texts["clock"][0], f"出生紀錄上的時間（{bound.label('UTC+8')}）"),
                        mean=(texts["mean"][0], "依出生地經度"))
    when = bound.num(f"{EXAMPLE.year} 年 {EXAMPLE.month} 月 {EXAMPLE.day} 日")
    out["three-times"] = (_fx.figure(
        fid="fig-solar-three",
        title="同一個瞬間的三種「幾點」：鐘面時間、地方平時、真太陽時",
        caption=(f"<b>{bound.label('圖 2')}</b>同一個瞬間的三種「幾點」，畫在同一條時間軸上。合成範例：{when}下午兩點，臺北。"
                 f"鐘面時間加上經度修正 {bound.num(_signed(lon_minutes))} 分鐘是地方平時；再加上那天的均時差 "
                 f"{bound.num(_signed(e['eot']))} 分鐘，是真太陽時 {bound.num(_clock(solar))}。真太陽時是本站計算服務的回應，"
                 "地方平時是世界時加上出生地經度。"),
        wide=_three("fx-wide", "fig-solar-three", times, texts, bound),
        narrow=_three("fx-narrow", "fig-solar-three", times, narrow_texts, bound),
        notes=[], idle=""), bound)
    # figure 3
    bound = _fx.Bound()
    out["year-shift"] = (_fx.figure(
        fid="fig-solar-year",
        title=f"{YEAR} 年每天中午，先換真太陽時再輸入，地方恆星時多出或少掉的分鐘數：臺北與金門",
        caption=(f"<b>{bound.label('圖 3')}</b>先換真太陽時、再當成鐘面時間輸入時，地方恆星時多出（正）或少掉（負）的分鐘數，"
                 f"{bound.label(str(YEAR))} 年每天中午一點。虛線是經度修正，一年不變；曲線在虛線上下多遠，就是那天的均時差。"
                 "按鈕切換臺北與金門，另一地畫成淡色虛線。均時差以 Swiss Ephemeris 的 <code>swe_time_equ</code> 計算，"
                 f"本站結果頁的真太陽時用的也是它；上升星座被換掉的比例，以 {bound.label(str(YEAR))} 年每 "
                 f"{bound.label('10')} 分鐘的時刻計算。"),
        wide=_year_art("fx-wide", "fig-solar-year", year, bound),
        narrow=_year_art("fx-narrow", "fig-solar-year", year, bound),
        notes=_year_sentences(year, bound), idle=YEAR_IDLE,
        variants=tuple((v, name) for v, name, _ in PLACES), switch_label="切換地點",
        table=_year_table(year, bound)), bound)
    checked = {}
    for name, (html, bound) in out.items():
        found = _fx.problems(html, bound)
        if found:
            raise RuntimeError("figure check: " + "; ".join(found))
        checked[name] = html
    return checked


def build() -> tuple[dict[str, str], list[str]]:
    e = _example()
    year = _year()
    gained = ((e["wrong"]["last"] - e["right"]["last"]) % 24) * 60
    lon_minutes = (TAIPEI[1] - ZONE_MERIDIAN) * 4
    asc_moved = (float(e["wrong"]["asc"][2]) - float(e["right"]["asc"][2])) % 360
    eot_gap = abs(e["eot"] - e["noaa_eot"]) * 60
    if eot_gap > 10:
        raise RuntimeError(f"the product's equation of time is {eot_gap:.1f} s from NOAA's formula")
    lo, hi = year["eot_range"]
    jin = (JINCHENG[1] - ZONE_MERIDIAN) * 4
    # Before 1896 the tz database gives Taipei its local mean time.
    early = ZoneInfo("Asia/Taipei").utcoffset(datetime(1890, 1, 1))
    if early is None:
        raise RuntimeError("Asia/Taipei has no offset in 1890")
    lmt = int(early.total_seconds())
    quoted = [
        f"經度修正是 {_signed(lon_minutes)} 分鐘",
        f"均時差是 {_signed(e['eot'])} 分鐘",
        f"真太陽時是 {e['solar']:%H:%M:%S}",
        f"地方恆星時從 {_hm(e['right']['last'])} 變成 {_hm(e['wrong']['last'])}，多了約 {gained:.1f} 分鐘",
        f"上升點從{_asc(e['right']['asc'])}移到{_asc(e['wrong']['asc'])}，差了 {asc_moved:.1f} 度",
        f"均時差在 {_signed(lo)} 到 {_signed(hi)} 分鐘之間",
        f"臺北在 {_signed(lon_minutes + lo)} 到 {_signed(lon_minutes + hi)} 分鐘之間",
        f"金門在 {_signed(jin + lo)} 到 {_signed(jin + hi)} 分鐘之間",
        f"臺北有 {year['share']['臺北']:.0%} 的時刻",
        f"金門有 {year['share']['金門']:.0%}",
        f"NOAA 試算表的公式在同一刻給出 {e['noaa_eot']:.2f} 分鐘，本站是 {e['eot']:.2f} 分鐘，相差約 {eot_gap:.0f} 秒",
        e["step_title"],
        f"比世界時快 {lmt // 3600} 小時 {lmt % 3600 // 60} 分",
    ]
    return {"fx-defs": _fx.defs(()), **_figures(e, year, gained, asc_moved)}, quoted
