"""〈不知道出生時間，能排星盤嗎？〉: figure 1 (one day: which classifications
change, and when), figure 2 (ten years of days: which of the seven bodies
change sign), figure 3 (the day's 24 hours, each in one of three classes),
table 1 (the 05:00 hour, bracket by bracket) and the numbers the prose quotes.

Figures 1 and 3 and table 1 are the product's own answer: the requests go to
the real application in process; figure 2 is Swiss Ephemeris read directly.  Synthetic date only: 1988-07-22, Taipei 25.05306N
121.52639E, Asia/Taipei (UTC+8, no daylight saving that year), whole-sign
houses with Lots.  The date was picked because the Sun, the Moon and Jupiter
all change sign on it; the article says so.  The one value checked against a
second algorithm is the sect change at sunrise: the product's bracket must
hold the geometric sunrise of the NOAA solar calculator's formulas (_noaa).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import _fx, _noaa
from ..javascript import SOURCES, frozen_string_table
from ._common import PLANETS, SIGNS, TAIPEI, calc_ut, hms as _hms, product_charts, swiss


FRAGMENT = "blog-unknown-birth-time"
DAY = (1988, 7, 22)
LAT, LON = TAIPEI
CLASSICAL = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
TABLE_HOUR = 5
ASC = "astronomical_data.angles.sign_positions.asc"
MC = "astronomical_data.angles.sign_positions.mc"
IS_DAY = "derived_methods.sect.is_day"
SECT_STATUS = "derived_methods.sect.sect_status"
FORTUNE = "derived_methods.lots.sign_positions.fortune"


def _body(key: str) -> str:
    return f"astronomical_data.bodies[{key}].sign_position"


def _house(key: str) -> str:
    return f"derived_methods.planet_in_house.placements[{key}].house"


def _request(precision: str, hour: int = 0, minute: int = 0, second: int = 0) -> dict:
    return {"birth_time_precision": precision,
            "datetime": {"year": DAY[0], "month": DAY[1], "day": DAY[2],
                         "hour": hour, "minute": minute, "second": second},
            "location": {"latitude": LAT, "longitude": LON},
            "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
            "options": {"house_system": "W", "include_houses": True, "include_lots": True}}


def _clock(local: str) -> tuple[int, int, int]:
    """'1988-07-22T05:20:23' -> (5, 20, 23); the date must be the article's."""
    stamp = datetime.fromisoformat(local)
    if (stamp.year, stamp.month, stamp.day) != DAY:
        raise RuntimeError(f"a transition left the day: {local}")
    return stamp.hour, stamp.minute, stamp.second


def _data() -> dict:
    d: dict = {}
    with product_charts() as post:
        day = post(_request("date_only"))
        sens = day["birth_time_sensitivity"]
        if (sens["precision"], sens["status"]) != ("date_only", "computed"):
            raise RuntimeError(f"date_only sensitivity did not run: {sens['status']}")
        d["day_samples"] = len(sens["samples"])
        d["day_differs"] = sorted({path for item in sens["classification_coverage"].values()
                                   for path in item["differing_classifications"]})
        d["day_signs"] = {item["key"]: item["sampled_sign_indices"] for item in sens["position_ranges"]}
        d["day_spans"] = {item["key"]: item["sampled_longitude_envelope"]["span_degrees"]
                          for item in sens["position_ranges"]}
        d["day_refused"] = {name: (day["derived_methods"][name]["executed"], day["derived_methods"][name]["reason_code"])
                            for name in ("house_division", "planet_in_house", "lots", "sect")}
        hours = []
        for hour in range(24):
            s = post(_request("approximate_hour", hour))["birth_time_sensitivity"]
            if s["precision"] != "approximate_hour" or s["probe_coverage"]["skipped"]:
                raise RuntimeError(f"hour {hour} was not sampled in full")
            hours.append({
                "status": s["classification_status"],
                "bodies": s["classification_coverage"]["astronomical_data.bodies"]["status"],
                "transitions": [(_clock(t["lower_bound_local"]), _clock(t["upper_bound_local"]),
                                 t["resolution_seconds"], set(t["changed_paths"])) for t in s["transitions"]],
                # The extended lots are read at the samples only, not bisected,
                # so a change of theirs shows here and in no transition.
                "differing": {path for item in s["classification_coverage"].values()
                              for path in item["differing_classifications"]},
            })
        d["hours"] = hours
        # Where the day starts: the Ascendant's sign and the sect at local midnight.
        midnight = post(_request("exact"))
        d["midnight_asc"] = midnight["astronomical_data"]["angles"]["sign_positions"]["asc"][0]
        d["midnight_is_day"] = midnight["derived_methods"]["sect"]["is_day"]
        rows = []
        for lower, upper, _, paths in hours[TABLE_HOUR]["transitions"]:
            before, after = (post(_request("exact", *clock)) for clock in (lower, upper))
            rows.append((lower, upper, paths, before, after))
        d["table"] = rows
    return d


def decade() -> dict:
    """1981–1990, Taipei civil days: which of the seven classical bodies are in
    a different sign at the next local midnight than at this one."""
    bodies = (0, 1, 2, 3, 4, 5, 6)  # Swiss SUN … SATURN
    counts = {"none": 0, "moon_only": 0, "sun": 0, "days": 0}
    with swiss() as swe:
        start = swe.julday(1981, 1, 1, -8.0)
        end = swe.julday(1991, 1, 1, -8.0)
        previous = [int(calc_ut(swe, start, body)[0] // 30) for body in bodies]
        day = start
        while day < end:
            day += 1
            current = [int(calc_ut(swe, day, body)[0] // 30) for body in bodies]
            changed = {body for body, a, b in zip(bodies, previous, current) if a != b}
            counts["days"] += 1
            counts["none"] += not changed
            counts["moon_only"] += changed == {1}
            counts["sun"] += 0 in changed
            previous = current
    return counts


def _seconds(clock: tuple[int, int, int]) -> int:
    return clock[0] * 3600 + clock[1] * 60 + clock[2]


def _crossings(d: dict, path: str) -> list[tuple]:
    return [(lower, upper) for hour in d["hours"] for lower, upper, _, paths in hour["transitions"] if path in paths]


def _derive(d: dict) -> dict:
    out: dict = {}
    for key in CLASSICAL:
        out[key] = _crossings(d, _body(key))
    out["asc"] = _crossings(d, ASC)
    out["mc"] = _crossings(d, MC)
    out["sect"] = _crossings(d, IS_DAY)
    houses = [hour for hour, item in enumerate(d["hours"])
              if any(all(_house(key) in paths for key in CLASSICAL) for *_, paths in item["transitions"])]
    out["house_hours"] = houses
    out["asc_hours"] = sorted({lower[0] for lower, _ in out["asc"]})
    out["quiet_hours"] = [hour for hour, item in enumerate(d["hours"]) if item["status"] == "same_at_all_samples"]
    out["body_hours"] = [hour for hour, item in enumerate(d["hours"]) if item["bodies"] != "same_at_all_samples"]
    # The day's own sampling and the hourly passes must name the same bodies.
    changed = sorted(key for key in CLASSICAL if out[key])
    day_changed = sorted(key for key in CLASSICAL if _body(key) in d["day_differs"])
    if changed != day_changed or any(len(out[key]) != 1 for key in changed):
        raise RuntimeError(f"date_only says {day_changed} change sign, the hours say {changed}")
    out["changed"] = changed
    if d["day_refused"] != {"house_division": (False, "date_only_no_birth_time"),
                            "planet_in_house": (False, "date_only_no_birth_time"),
                            "lots": (False, "house_calculation_not_executed"),
                            "sect": (False, "house_calculation_not_executed")}:
        raise RuntimeError(f"a date-only request computed what needs a birth time: {d['day_refused']}")
    return out


def _sunrise_check(out: dict) -> dict:
    (lower, upper), = [pair for pair in out["sect"] if pair[0][0] < 12]
    rise = _noaa.sunrise_utc(date(*DAY), LAT, LON, zenith=90.0) + timedelta(hours=8)
    noaa = (rise.hour, rise.minute, rise.second + (1 if rise.microsecond >= 500000 else 0))
    gap = min(abs(_seconds(noaa) - _seconds(lower)), abs(_seconds(noaa) - _seconds(upper)))
    inside = _seconds(lower) <= _seconds(noaa) <= _seconds(upper)
    if not inside:
        # The prose says it falls inside; a minute apart (the formulas' stated
        # accuracy) would still be agreement, but the sentence must change.
        raise RuntimeError(f"NOAA geometric sunrise {noaa} is outside the product's {lower}–{upper} (gap {gap} s)")
    return {"noaa": noaa, "lower": lower, "upper": upper, "inside": inside}


def _sign(chart: dict, path: str) -> str:
    if path == FORTUNE:
        return SIGNS[chart["derived_methods"]["lots"]["sign_positions"]["fortune"][0]]
    key = path.rsplit(".", 1)[-1]
    return SIGNS[chart["astronomical_data"]["angles"]["sign_positions"][key][0]]


SIGN_KEYS = ("aries taurus gemini cancer leo virgo libra scorpio sagittarius capricorn aquarius pisces").split()
SECT_NAMES = {"day": "日盤", "night": "夜盤"}
# The article's first mention of each lot carries its English name.
LOT_ENGLISH = {"愛慾點": "Lot of Eros", "必然點": "Lot of Necessity", "勇氣點": "Lot of Courage",
               "勝利點": "Lot of Victory", "復仇點": "Lot of Nemesis"}


def _extended_lot_items(paths: set, before: dict, after: dict) -> list[tuple[str, str, str]]:
    """One row per extended lot whose sign changed: the applied value, else the day or night formula's."""
    names = frozen_string_table((SOURCES / "labels.js").read_text(encoding="utf-8"), "EXTENDED_LOT_NAMES")
    lots = [c["derived_methods"]["lots"]["extended_lots"]["lots"] for c in (before, after)]
    items = []
    for index, lot in enumerate(lots[0]):
        name = names[lot["lot_method_id"]]
        root = f"derived_methods.lots.extended_lots.lots[{index}]"
        if f"{root}.sign" in paths:
            before_sign, after_sign = (SIGNS[SIGN_KEYS.index(l[index]["sign"])] for l in lots)
            items.append((f"{name}星座", before_sign, after_sign))
            continue
        for sect, label in SECT_NAMES.items():
            if f"{root}.by_sect.{sect}.sign" in paths:
                before_sign, after_sign = (SIGNS[SIGN_KEYS.index(l[index]["by_sect"][sect]["sign"])] for l in lots)
                items.append((f"{name}（{label}公式）星座", before_sign, after_sign))
    return items


def _table(d: dict) -> str:
    rows: list[str] = []
    for lower, upper, paths, before, after in d["table"]:
        when = f'<td class="n">{_hms(lower)}–{_hms(upper)}</td>'
        items = []
        if SECT_STATUS in paths and IS_DAY not in paths:
            status = [c["derived_methods"]["sect"]["sect_status"] for c in (before, after)]
            if status != ["night", "boundary_both_shown"]:
                raise RuntimeError(f"unexpected sect states {status}")
            items.append(("日夜盤狀態", "夜盤", "靠近地平，阿拉伯點並列兩套公式"))
        if IS_DAY in paths:
            sect = ["日盤" if c["derived_methods"]["sect"]["is_day"] else "夜盤" for c in (before, after)]
            items.append(("日夜盤", sect[0], sect[1]))
        if ASC in paths:
            items.append(("上升星座", _sign(before, ASC), _sign(after, ASC)))
        if all(_house(key) in paths for key in CLASSICAL):
            houses = [{p["key"]: p["house"] for p in c["derived_methods"]["planet_in_house"]["placements"]}
                      for c in (before, after)]
            items.append(("七顆行星的宮位", f"例：太陽在第 {houses[0]['sun']} 宮",
                          f"太陽在第 {houses[1]['sun']} 宮，其餘六顆也全部換宮"))
        if MC in paths:
            items.append(("中天星座", _sign(before, MC), _sign(after, MC)))
        if FORTUNE in paths:
            # The table is where the article first names the Lot; its English goes with it once.
            label = "命運點星座" if any("命運點" in row for row in rows) else "命運點（Lot of Fortune）星座"
            items.append((label, _sign(before, FORTUNE), _sign(after, FORTUNE)))
        for name, was, now in _extended_lot_items(paths, before, after):
            short = name.removesuffix("星座")
            if short in LOT_ENGLISH and not any(short in row for row in rows + [n for n, *_ in items]):
                name = f"{short}（{LOT_ENGLISH[short]}）星座"
            items.append((name, was, now))
        if not items:
            raise RuntimeError(f"no label for the change at {lower}: {sorted(paths)}")
        for name, was, now in items:
            rows.append(f'          <tr>{when}<td>{name}</td><td>{was}</td><td class="diff">{now}</td></tr>')
    return "\n".join(rows)


# --- the figures -----------------------------------------------------------------

def _mid(pair: tuple) -> float:
    return (_seconds(pair[0]) + _seconds(pair[1])) / 2


def _segments(d: dict, out: dict) -> dict:
    """Each row's states through the day: [(start s, end s, label)]."""
    rows: dict = {}
    for key in ("sun", "moon", "jupiter"):
        (pair,) = out[key]
        a, b = d["day_signs"][key]
        rows[key] = [(0, _mid(pair), SIGNS[a]), (_mid(pair), 86400, SIGNS[b])]
    marks = [_mid(pair) for pair in out["asc"]]
    if marks != sorted(marks):
        raise RuntimeError("the Ascendant's crossings are not in order")
    edges = [0.0, *marks, 86400.0]
    rows["asc"] = [(edges[i], edges[i + 1], SIGNS[(d["midnight_asc"] + i) % 12]) for i in range(len(edges) - 1)]
    # The table hour's own crossing names the signs the walk must give there.
    for lower, upper, paths, before, after in d["table"]:
        if ASC in paths:
            at = next(seg for seg in rows["asc"] if seg[1] == _mid((lower, upper)))
            if (at[2], next(seg for seg in rows["asc"] if seg[0] == at[1])[2]) != (_sign(before, ASC), _sign(after, ASC)):
                raise RuntimeError("the Ascendant's signs walked from midnight disagree with the product at 05:23")
    sect = [_mid(pair) for pair in out["sect"]]
    states = ["日盤", "夜盤"] if d["midnight_is_day"] else ["夜盤", "日盤"]
    edges = [0.0, *sect, 86400.0]
    rows["sect"] = [(edges[i], edges[i + 1], states[i % 2]) for i in range(len(edges) - 1)]
    return rows


DAY_ROWS = (("sun", "太陽星座"), ("moon", "月亮星座"), ("jupiter", "木星星座"), ("others", "其餘四星"),
            ("asc", "上升星座"), ("sect", "日夜盤"))


def _day(layout: str, fid: str, d: dict, out: dict, segs: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (200.0, 840.0) if wide else (14.0, 326.0)
    X = lambda s: x0 + (x1 - x0) * s / 86400  # noqa: E731
    th = 20 if wide else 16
    rh = 52 if wide else 50
    head = 30 if wide else 28
    body: list[str] = []
    y = head + 10
    tracks = []
    for i, (key, name) in enumerate(DAY_ROWS):
        if i in (0, 4):
            text = "只知道日期時也會比對" if i == 0 else "需要已知時刻，只知道日期時不算"
            if i == 4:
                y += 8
                body.append(_fx.line(14, y - 4, W - 14, y - 4, "fx-hair"))
            body.append(_fx.text(24 if wide else 14, y + 16, text, "fx-t fx-small fx-dim"))
            y += 26
        track = y + (rh - th) - 6
        tracks.append((key, name, y, track))
        y += rh
    plot_top, plot_bottom = tracks[0][3] - 8, tracks[-1][3] + th + 8
    for key, name, y, track in tracks:
        if wide:
            if key in ("sun", "moon", "jupiter"):
                body.append(_fx.glyph(key, 34, track + th / 2, 16, "fx-mk-gl"))
            body.append(_fx.text(52, track + th / 2 + 6, name, "fx-t"))
        else:
            summary = {
                "others": "水星、金星、火星、土星整天不換",
                "asc": f"一天換 {bound.num(str(len(out['asc'])))} 次",
                "sect": "日出、日落各翻一次",
            }.get(key)
            if summary is None:
                a, b = segs[key][0][2], segs[key][1][2]
                summary = f"{a} → {b}"
            gx = 14
            if key in ("sun", "moon", "jupiter"):
                body.append(_fx.glyph(key, gx + 7, track - 13, 13, "fx-mk-gl"))
                gx += 20
            body.append(_fx.text(gx, track - 8, f"{name}　{summary}", "fx-t"))
        body.append(_fx.rect(x0, track, x1 - x0, th, "fx-track"))
    for hour in out["quiet_hours"]:
        if wide:
            body.append(_fx.rect(X(hour * 3600), plot_top, X(3600) - X(0), plot_bottom - plot_top, "fx-fill-dot"))
        else:
            # on a phone the label lines sit between the tracks: dot the tracks only
            body += [_fx.rect(X(hour * 3600), track, X(3600) - X(0), th, "fx-fill-dot") for *_, track in tracks]
    for key, name, y, track in tracks:
        if key == "others":
            if wide:
                body.append(_fx.text(x0 + 8, track + th - 5, "水星、金星、火星、土星整天不換", "fx-t fx-small fx-key"))
            continue
        marks = segs[key][1:]
        for start, end, label in segs[key]:
            if start:
                body.append(_fx.rect(X(start) - 1.5, track - 5, 3, th + 10, "fx-fill-solid"))
            if not wide:
                continue
            if key in ("asc", "sect"):
                if X(end) - X(start) >= 40:
                    body.append(_fx.text((X(start) + X(end)) / 2, track + th - 5, label, "fx-t fx-small fx-key", "middle"))
        if wide and key in ("sun", "moon", "jupiter"):
            at = X(marks[0][0])
            body.append(_fx.text(at - 7, track - 7, segs[key][0][2], "fx-t fx-small", "end"))
            body.append(_fx.text(at + 7, track - 7, segs[key][1][2], "fx-t fx-small"))
    axis = plot_bottom + 6
    body.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    for hour in range(25):
        tall = hour % 6 == 0
        body.append(_fx.line(X(hour * 3600), axis, X(hour * 3600), axis + (6 if tall else 3), "fx-axis"))
        if tall:
            anchor = "start" if hour == 0 and not wide else "end" if hour == 24 and not wide else "middle"
            body.append(_fx.text(X(hour * 3600), axis + 23, bound.scale(f"{hour:02d}:00"), "fx-t fx-small fx-num", anchor))
    ly = axis + (54 if wide else 52)
    body.append(_fx.rect(x0 if wide else 14, ly - 13, 3, 16, "fx-fill-solid"))
    body.append(_fx.text((x0 if wide else 14) + 10, ly, "翻面的時刻", "fx-t fx-small"))
    lx = (x0 + 140) if wide else 14
    ly2 = ly if wide else ly + 24
    body.append(_fx.rect(lx, ly2 - 13, 22, 16, "fx-fill-dot"))
    body.append(_fx.rect(lx, ly2 - 13, 22, 16, "fx-inset-frame"))
    body.append(_fx.text(lx + 30, ly2, "所有判定在各取樣點都相同的鐘點", "fx-t fx-small"))
    H = ly2 + 26
    return "".join([_fx.svg_open(layout, W, H, fid), _fx.plate(W, H), *body, "</svg>"])


def _day_table(segs: dict, out: dict, bound: _fx.Bound) -> str:
    rows = []
    for key, name in DAY_ROWS:
        if key == "others":
            rows.append(f'<tr><th scope="row">{name}</th><td>（整天不換）</td><td>水星、金星、火星、土星</td></tr>')
            continue
        pairs = out[key] if key != "sect" else out["sect"]
        for (lower, upper), (_, _, before), (_, _, after) in zip(pairs, segs[key], segs[key][1:]):
            rows.append(f'<tr><th scope="row">{name}</th><td class="n">{bound.num(_hms(lower))}–{bound.num(_hms(upper))}</td>'
                        f"<td>{before} → {after}</td></tr>")
    return _fx.data_table(("判定", "翻面區間", "之前 → 之後"), rows, summary="圖中的時刻（表格）")


def _day_figure(d: dict, out: dict) -> str:
    bound = _fx.Bound()
    segs = _segments(d, out)
    caption = (
        f"<b>{bound.label('圖 1')}</b>合成範例（不是任何人的出生資料）：{bound.num('1988')} 年 {bound.num('7')} 月 "
        f"{bound.num('22')} 日，臺北，整宮制。每一條粗直線是一個判定翻面的時刻，由本站計算服務在這一天的 "
        f"{bound.num('24')} 個鐘點裡逐一取樣、再用二分法夾出。上面四列是「只知道日期」時也會比對的天體星座；"
        "下面兩列需要已知時刻，只知道日期時本站不算。點狀底的欄是所有判定在各取樣點都相同的鐘點。"
    )
    return _fx.figure(
        fid="fig-day",
        hero=True,
        title="一天裡各項判定翻面的時刻",
        caption=caption,
        art=_fx.FigureArt.drawn(_day, "fig-day", d, out, segs, bound),
        table=_day_table(segs, out, bound),
        bound=bound,
    )


DECADE = (("none", "七顆都不換", "fx-track"), ("moon_only", "只有月亮換", "fx-fill-hatch"),
          ("other", "有其他行星換", "fx-fill-cross"))


def _decade(layout: str, fid: str, ten: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (40.0, 840.0) if wide else (14.0, 326.0)
    days = ten["days"]
    counts = {"none": ten["none"], "moon_only": ten["moon_only"], "other": days - ten["none"] - ten["moon_only"]}
    body = [_fx.text(x0, 34 if wide else 28, f"{bound.num('1981')}–{bound.num('1990')} 年的 {bound.num(str(days))} 天",
                     "fx-t fx-small fx-dim")]
    top, bh = (52.0, 40.0) if wide else (44.0, 34.0)
    x = x0
    spans = {}
    for key, name, fill in DECADE:
        w = (x1 - x0) * counts[key] / days
        body.append(_fx.rect(x, top, w, bh, "fx-track"))
        if fill != "fx-track":
            body.append(_fx.rect(x, top, w, bh, fill))
        spans[key] = (x, x + w)
        x += w
    body.append(_fx.rect(x0, top, x1 - x0, bh, "fx-inset-frame"))

    def share(key: str) -> str:
        return f"{bound.num(str(counts[key]))} 天（{bound.num(f'{counts[key] / days:.0%}')}）"

    if wide:
        ly = top + bh + 30
        for key, name, _ in DECADE:
            a, b = spans[key]
            anchor = "end" if key == "other" else None
            at = b if key == "other" else a
            body.append(_fx.line(at, top + bh, at, ly - 18, "fx-leader"))
            body.append(_fx.text(at, ly, name, "fx-t", anchor))
            body.append(_fx.text(at, ly + 22, share(key), "fx-t fx-small fx-num", anchor))
        note_y = ly + 58
        body.append(_fx.text(x0, note_y, f"其中太陽換星座的日子：{bound.num(str(ten['sun']))} 天", "fx-t fx-small"))
        H = note_y + 24
    else:
        ly = top + bh + 34
        for i, (key, name, fill) in enumerate(DECADE):
            y = ly + i * 30
            body.append(_fx.rect(14, y - 13, 22, 16, "fx-track"))
            if fill != "fx-track":
                body.append(_fx.rect(14, y - 13, 22, 16, fill))
            body.append(_fx.text(44, y, name, "fx-t"))
            body.append(_fx.text(x1, y, share(key), "fx-t fx-small fx-num", "end"))
        note_y = ly + 3 * 30 + 4
        body.append(_fx.text(14, note_y, f"其中太陽換星座的日子：{bound.num(str(ten['sun']))} 天", "fx-t fx-small"))
        H = note_y + 22
    return "".join([_fx.svg_open(layout, W, H, fid), _fx.plate(W, H), *body, "</svg>"])


def _decade_figure(ten: dict) -> str:
    bound = _fx.Bound()
    caption = (
        f"<b>{bound.label('圖 2')}</b>從 {bound.num('1981')} 到 {bound.num('1990')} 年的每一天，比較臺北時間 {bound.num('0')} 點"
        f"與隔天 {bound.num('0')} 點七顆古典行星的星座：七顆都不換（空白）、只有月亮換（單線）、有月亮以外的行星換"
        "（交叉線，月亮可能也換）。由本站以 Swiss Ephemeris 自算；一天之內換過去又換回來的情形不在這個統計裡。"
    )
    return _fx.figure(
        fid="fig-decade",
        title="十年裡的每一天：七顆古典行星有沒有換星座",
        caption=caption,
        art=_fx.FigureArt.drawn(_decade, "fig-decade", ten, bound),
        bound=bound,
    )


HOUR_ROWS = (("asc", "上升星座會換", "fx-fill-solid"), ("other", "上升不換，其他判定翻面", "fx-fill-hatch"),
             ("quiet", "所有判定在各取樣點都相同", "fx-fill-dot"))


def _flipped(paths: set[str]) -> list[str]:
    names = []
    if ASC in paths:
        names += ["上升星座", "行星落宮"]
    if MC in paths:
        names.append("中天星座")
    for key in CLASSICAL:
        if _body(key) in paths:
            names.append(f"{PLANETS[key]}星座")
    if IS_DAY in paths:
        names.append("日夜盤")
    elif SECT_STATUS in paths:
        names.append("日夜盤狀態")
    if any(path.startswith("derived_methods.lots.sign_positions.") for path in paths):
        names.append("阿拉伯點星座")
    if any(path.startswith("derived_methods.lots.extended_lots.") and path.endswith(".sign") for path in paths):
        names.append("其他阿拉伯點星座")
    return names


def _hour_kinds(d: dict, out: dict) -> list[tuple[str, list[str]]]:
    kinds = []
    for hour, item in enumerate(d["hours"]):
        names: list[str] = []
        for *_, paths in item["transitions"]:
            names += [name for name in _flipped(paths) if name not in names]
        names += [name for name in _flipped(item["differing"]) if name not in names]
        kind = "quiet" if hour in out["quiet_hours"] else "asc" if hour in out["asc_hours"] else "other"
        if (kind == "quiet") != (not names):
            raise RuntimeError(f"hour {hour}: classified {kind}, flipped {names}")
        kinds.append((kind, names))
    return kinds


def _hours(layout: str, fid: str, kinds: list, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (330.0, 850.0) if wide else (14.0, 326.0)
    cw = (x1 - x0) / 24
    ch = 26 if wide else 20
    body = []
    top = 30 if wide else 22
    y = top
    for key, name, fill in HOUR_ROWS:
        count = sum(kind == key for kind, _ in kinds)
        label = f"{bound.num(str(count))} 個鐘點"
        if wide:
            cy = y + ch / 2
            body.append(_fx.text(24, cy - 2, name, "fx-t"))
            body.append(_fx.text(24, cy + 18, label, "fx-t fx-small fx-num fx-dim"))
            row = y
            y += ch + 26
        else:
            body.append(_fx.text(14, y + 16, f"{name}　{label}", "fx-t"))
            row = y + 26
            y += ch + 40
        for hour, (kind, _) in enumerate(kinds):
            body.append(_fx.rect(x0 + hour * cw, row, cw, ch, "fx-track"))
            if kind == key:
                body.append(_fx.rect(x0 + hour * cw, row, cw, ch, fill))
    axis = row + ch + 6
    shown = range(24) if wide else (0, 6, 12, 18, 23)
    for hour in shown:
        body.append(_fx.text(x0 + (hour + 0.5) * cw, axis + 14, bound.scale(str(hour)), "fx-t fx-small fx-num", "middle"))
    body.append(_fx.text(x0 if wide else 14, axis + 40, "鐘點（0 點到 23 點，每格一小時）".replace("23", bound.scale("23")),
                         "fx-t fx-small fx-dim"))
    H = axis + 58
    return "".join([_fx.svg_open(layout, W, H, fid), _fx.plate(W, H), *body, "</svg>"])


def _hours_table(kinds: list, bound: _fx.Bound) -> str:
    names = {key: name for key, name, _ in HOUR_ROWS}
    rows = [f'<tr><th scope="row">{bound.num(str(hour))} 點</th><td>{names[kind]}</td>'
            f'<td>{"、".join(flipped) or "（無）"}</td></tr>' for hour, (kind, flipped) in enumerate(kinds)]
    return _fx.data_table(("鐘點", "分類", "翻面的判定"), rows, summary="圖中的鐘點（表格）")


def _hours_figure(d: dict, out: dict) -> str:
    bound = _fx.Bound()
    kinds = _hour_kinds(d, out)
    caption = (
        f"<b>{bound.label('圖 3')}</b>同一個合成日子（{bound.num('1988')} 年 {bound.num('7')} 月 {bound.num('22')} 日，臺北）"
        f"的 {bound.num('24')} 個鐘點，每一個都用「只知道約略小時」算一次，再依結果歸入三列之一：上升星座會換（實心）、"
        "上升不換但有其他判定翻面（單線）、所有判定在各取樣點都相同（點狀）。每個鐘點翻了哪些判定，列在下方的表格裡。"
    )
    return _fx.figure(
        fid="fig-hours",
        title="一天 24 個鐘點，各歸哪一類",
        caption=caption,
        art=_fx.FigureArt.drawn(_hours, "fig-hours", kinds, bound),
        table=_hours_table(kinds, bound),
        bound=bound,
    )


def build() -> tuple[dict[str, str], list[str]]:
    d = _data()
    out = _derive(d)
    ten = decade()
    check = _sunrise_check(out)
    (sun_lo, sun_hi), = out["sun"]
    (moon_lo, moon_hi), = out["moon"]
    (jup_lo, jup_hi), = out["jupiter"]
    names = "、".join(PLANETS[key] for key in ("jupiter", "moon", "sun") if key in out["changed"])
    quiet = "、".join(f"{h} 點" for h in out["quiet_hours"])
    sect = out["sect"]
    hour = d["hours"][TABLE_HOUR]
    widths = {width for _, _, width, _ in hour["transitions"]}
    if hour["bodies"] != "same_at_all_samples" or max(widths) - min(widths) > 1:
        raise RuntimeError(f"the table hour's premise changed: bodies {hour['bodies']}, widths {widths}")
    fortune = sum(FORTUNE in paths for *_, paths in hour["transitions"])
    planets = {key: d["day_spans"][key] for key in CLASSICAL if key != "moon"}
    fastest = max(planets, key=lambda key: planets[key])
    rest = max(value for key, value in planets.items() if key != fastest)
    others = 24 - len(out["asc_hours"]) - len(out["quiet_hours"])
    count = "零一二三四五六七八九"
    quoted = [
        f"取樣 {d['day_samples']} 次",
        f"{names}三個天體的星座",
        f"木星在 {_hms(jup_lo)} 到 {_hms(jup_hi)} 之間",
        f"月亮在 {_hms(moon_lo)} 到 {_hms(moon_hi)} 之間",
        f"太陽在 {_hms(sun_lo)} 到 {_hms(sun_hi)} 之間",
        f"<b>{len(out['asc_hours'])}</b><span>個鐘點裡上升星座會換",
        f"<b>{len(out['quiet_hours'])}</b><span>個鐘點",
        f"（{quiet}）" if quiet else "所有判定都相同的鐘點一個也沒有",
        f"<b>{len(out['body_hours'])}</b><span>個鐘點",
        f"日出那次在 {_hms(sect[0][0])} 到 {_hms(sect[0][1])} 之間，日落那次在 {_hms(sect[1][0])} 到 {_hms(sect[1][1])} 之間",
        f"算出的幾何日出是 {_hms(check['noaa'])}，落在本站的區間裡",
        f"{len(hour['transitions'])} 個翻面區間，每個寬 "
        + (f"{min(widths)} 秒" if len(widths) == 1 else f"{min(widths)} 到 {max(widths)} 秒"),
        f"命運點在一小時裡換了{count[fortune]}次星座",
        f"一天裡翻了{'十二' if len(out['asc']) == 12 else len(out['asc'])}次",
        f"其他行星裡走最多的是{PLANETS[fastest]}，約 {planets[fastest]:.1f} 度，其餘都不到 {int(rest) + 1} 度",
        f"其餘 {others} 個鐘點裡",
        f"月亮這一天走了約 {d['day_spans']['moon']:.1f} 度",
        f"1981 到 1990 年的 {ten['days']} 天裡",
        f"有 {ten['none'] / ten['days']:.0%} 的日子七顆古典行星都不換星座",
        f"{ten['moon_only'] / ten['days']:.0%} 的日子只有月亮換",
        f"太陽換星座的日子有 {ten['sun']} 天",
    ]
    if len(out["house_hours"]) != len(out["asc_hours"]):
        raise RuntimeError("whole-sign houses and the Ascendant's sign changed in different hours")
    return {
        "fx-defs": _fx.defs(("sun", "moon", "jupiter")),
        "day-timeline": _day_figure(d, out),
        "decade": _decade_figure(ten),
        "hours": _hours_figure(d, out),
        "hour-five": _table(d),
    }, quoted
