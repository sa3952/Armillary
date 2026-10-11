"""〈不知道出生時間，能排星盤嗎？〉: figure 1 (one day: which classifications
change, and when), table 1 (the 05:00 hour, bracket by bracket) and the
numbers the prose quotes.

Every number is the product's own answer: the requests go to the real
application in process.  Synthetic date only: 1988-07-22, Taipei 25.05306N
121.52639E, Asia/Taipei (UTC+8, no daylight saving that year), whole-sign
houses with Lots.  The date was picked because the Sun, the Moon and Jupiter
all change sign on it; the article says so.  The one value checked against a
second algorithm is the sect change at sunrise: the product's bracket must
hold the geometric sunrise of the NOAA solar calculator's formulas (_noaa).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from . import _noaa
from ._common import SIGNS, calc_ut, indent, product_charts, swiss


FRAGMENT = "blog-unknown-birth-time"
DAY = (1988, 7, 22)
LAT, LON = 25.05306, 121.52639
CLASSICAL = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
NAMES = {"sun": "太陽", "moon": "月亮", "mercury": "水星", "venus": "金星", "mars": "火星", "jupiter": "木星",
         "saturn": "土星"}
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
            })
        d["hours"] = hours
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


def _hms(clock: tuple[int, int, int]) -> str:
    return f"{clock[0]:02d}:{clock[1]:02d}:{clock[2]:02d}"


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


def _hero(d: dict, out: dict) -> str:
    W, H = 640, 420
    L, R = 150, 620
    X = lambda s: L + (R - L) * s / 86400  # noqa: E731
    rows = [("sun", "太陽星座"), ("moon", "月亮星座"), ("jupiter", "木星星座"), ("others", "其餘四星"),
            ("asc", "上升星座"), ("sect", "日夜盤")]
    top, step = 70, 44
    s = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="合成範例：1988 年 7 月 22 日，臺北。一天裡各項判定翻面的時刻。'
        f"木星在 {_hms(out['jupiter'][0][0])} 前後、月亮在 {_hms(out['moon'][0][0])} 前後、太陽在 {_hms(out['sun'][0][0])} 前後換星座；"
        f"水星、金星、火星、土星整天不換。上升點一天換了 {len(out['asc'])} 次星座，日夜盤在日出與日落各翻一次。"
        f'24 個鐘點裡，有 {len(out["quiet_hours"])} 個鐘點所有判定在各取樣點都相同。">'
    ]
    gap = 24
    bottom = top + (len(rows) - 1) * step + gap + 20
    for hour in out["quiet_hours"]:
        s.append(f'<rect class="f-accent-soft" x="{X(hour * 3600):.1f}" y="{top - 22}" '
                 f'width="{X(3600) - X(0):.1f}" height="{bottom - top + 22}"/>')
    s.append(f'<text class="t-faint" x="{L}" y="{top - 34}">只知道日期時也會比對</text>')
    split = top + 3 * step + 18
    s.append(f'<line class="g-dim" x1="10" y1="{split}" x2="{R}" y2="{split}"/>')
    s.append(f'<text class="t-faint" x="{L}" y="{split + 24}">只知道日期時不算</text>')
    for i, (key, label) in enumerate(rows):
        y = top + i * step + (gap if i >= 4 else 0)
        s.append(f'<text class="t-dim" x="10" y="{y + 7}">{label}</text>')
        s.append(f'<line class="g-hair" x1="{L}" y1="{y}" x2="{R}" y2="{y}"/>')
        if key in ("sun", "moon", "jupiter"):
            signs = d["day_signs"][key]
            (lower, upper), = out[key]
            mid = (_seconds(lower) + _seconds(upper)) / 2
            s.append(f'<rect class="f-accent" x="{X(mid) - 1.5:.1f}" y="{y - 14}" width="3" height="28"/>')
            if mid > 40000:
                s.append(f'<text class="t-faint t-end" x="{X(mid) - 8:.1f}" y="{y - 6}">{SIGNS[signs[0]]}</text>')
            else:
                s.append(f'<text class="t-faint" x="{L + 4}" y="{y - 6}">{SIGNS[signs[0]]}</text>')
            s.append(f'<text class="t-faint" x="{X(mid) + 8:.1f}" y="{y - 6}">{SIGNS[signs[1]]}</text>')
        elif key == "others":
            s.append(f'<text class="t-faint" x="{L + 4}" y="{y - 6}">水金火土：整天不換</text>')
        else:
            for lower, upper in out[key]:
                mid = (_seconds(lower) + _seconds(upper)) / 2
                s.append(f'<rect class="f-accent" x="{X(mid) - 1.5:.1f}" y="{y - 14}" width="3" height="28"/>')
    for hour in (0, 6, 12, 18, 24):
        x = X(hour * 3600)
        s.append(f'<line class="g-dim" x1="{x:.1f}" y1="{H - 62}" x2="{x:.1f}" y2="{H - 54}"/>')
        s.append(f'<text class="t-faint t-mid" x="{x:.1f}" y="{H - 32}">{hour:02d}:00</text>')
    s.append(f'<line class="g-ink" x1="{L}" y1="{H - 62}" x2="{R}" y2="{H - 62}"/>')
    s.append(f'<text class="t-faint" x="10" y="{H - 6}">｜翻面的時刻　淡色欄：所有判定在各取樣點都相同的鐘點</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def _sign(chart: dict, path: str) -> str:
    if path == FORTUNE:
        return SIGNS[chart["derived_methods"]["lots"]["sign_positions"]["fortune"][0]]
    key = path.rsplit(".", 1)[-1]
    return SIGNS[chart["astronomical_data"]["angles"]["sign_positions"][key][0]]


def _table(d: dict) -> str:
    rows = []
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
            items.append(("命運點星座", _sign(before, FORTUNE), _sign(after, FORTUNE)))
        if not items:
            raise RuntimeError(f"no label for the change at {lower}: {sorted(paths)}")
        for name, was, now in items:
            rows.append(f'          <tr>{when}<td>{name}</td><td>{was}</td><td class="diff">{now}</td></tr>')
    return "\n".join(rows)


def build() -> tuple[dict[str, str], list[str]]:
    d = _data()
    out = _derive(d)
    ten = decade()
    check = _sunrise_check(out)
    (sun_lo, sun_hi), = out["sun"]
    (moon_lo, moon_hi), = out["moon"]
    (jup_lo, jup_hi), = out["jupiter"]
    names = "、".join(NAMES[key] for key in ("jupiter", "moon", "sun") if key in out["changed"])
    quiet = "、".join(f"{h} 點" for h in out["quiet_hours"])
    sect = out["sect"]
    hour = d["hours"][TABLE_HOUR]
    widths = {width for _, _, width, _ in hour["transitions"]}
    if hour["bodies"] != "same_at_all_samples" or len(widths) != 1:
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
        f"（{quiet}）",
        f"<b>{len(out['body_hours'])}</b><span>個鐘點",
        f"日出那次在 {_hms(sect[0][0])} 到 {_hms(sect[0][1])} 之間，日落那次在 {_hms(sect[1][0])} 到 {_hms(sect[1][1])} 之間",
        f"算出的幾何日出是 {_hms(check['noaa'])}，落在本站的區間裡",
        f"{len(hour['transitions'])} 個翻面區間，每個寬 {widths.pop()} 秒",
        f"命運點在一小時裡換了{count[fortune]}次星座",
        f"一天裡翻了{'十二' if len(out['asc']) == 12 else len(out['asc'])}次",
        f"其他行星裡走最多的是{NAMES[fastest]}，約 {planets[fastest]:.1f} 度，其餘都不到 {int(rest) + 1} 度",
        f"其餘 {others} 個鐘點裡",
        f"月亮這一天走了約 {d['day_spans']['moon']:.1f} 度",
        f"1981 到 1990 年的 {ten['days']} 天裡",
        f"有 {ten['none'] / ten['days']:.0%} 的日子七顆古典行星都不換星座",
        f"{ten['moon_only'] / ten['days']:.0%} 的日子只有月亮換",
        f"太陽換星座的日子有 {ten['sun']} 天",
    ]
    if len(out["house_hours"]) != len(out["asc_hours"]):
        raise RuntimeError("whole-sign houses and the Ascendant's sign changed in different hours")
    return {"day-timeline": _hero(d, out), "hour-five": _table(d)}, quoted
