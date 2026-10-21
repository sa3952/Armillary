"""〈行星時怎麼算〉: figure 1 (one planetary day in Taipei, sunrise to the next
sunrise, its twelve day hours and twelve night hours drawn to length with each
hour's ruler, under a switch between the days of the 2026 March equinox, June
solstice and December solstice), figure 2 (the seven planets in the Chaldean
order and the star the weekdays follow from it), table 1 (the ruler of every
hour of every weekday) and the numbers the prose quotes.

Every hour drawn is the product's answer in process: for each day the module
asks the chart route for the date and the next date with the date known and
the time not (`birth_time_precision: date_only`), and reads the hours the
product lists in `derived_methods.planetary_hours.birth_time_interval`.  The
three days are the Taipei calendar dates of the Sun reaching 0°, 90° and 270°
of tropical longitude in 2026, from Swiss Ephemeris.  The worked examples are
exact instants the product answers.  Table 1 is the product's own rule
(`CHALDEAN_ORDER`, `WEEKDAY_RULERS`), held by the build to the sequence Dio
describes: from Saturn, the hours of day and night one after another.
"""
from __future__ import annotations

import datetime as dt
import functools

from . import _fx
from ._common import PLANETS, TAIPEI, backend_on_path, product_charts, swiss


FRAGMENT = "blog-planetary-hours"
YEAR = 2026
TAIPEI_OFFSET_HOURS = 8
# (key, Sun's tropical longitude, label)
SEASONS = (("summer", 90.0, "夏至"), ("equinox", 0.0, "春分"), ("winter", 270.0, "冬至"))
PLANET_KEYS = ("saturn", "jupiter", "mars", "sun", "venus", "mercury", "moon")
WEEKDAY_ZH = {"monday": "星期一", "tuesday": "星期二", "wednesday": "星期三", "thursday": "星期四",
              "friday": "星期五", "saturday": "星期六", "sunday": "星期日"}
SHORT = {"sun": "日", "moon": "月", "mercury": "水", "venus": "金", "mars": "火", "jupiter": "木", "saturn": "土"}
TAIPEI_PLACE = {"latitude": TAIPEI[0], "longitude": TAIPEI[1]}
TAIPEI_ZONE = {"mode": "iana", "iana_name": "Asia/Taipei"}
# A synthetic place north of the Arctic Circle (Tromsø's latitude and longitude), for the polar example.
POLAR_PLACE = {"latitude": 69.6492, "longitude": 18.9553}
POLAR_ZONE = {"mode": "iana", "iana_name": "Europe/Oslo"}
OPTIONS = {"house_system": "W", "include_houses": False}


def _request(date: dt.date, clock: tuple[int, int] | None, place=TAIPEI_PLACE, zone=TAIPEI_ZONE) -> dict:
    hour, minute = clock or (0, 0)
    payload = {"datetime": {"year": date.year, "month": date.month, "day": date.day, "hour": hour,
                            "minute": minute, "second": 0},
               "location": place, "timezone": zone, "options": OPTIONS}
    if clock is None:
        payload["birth_time_precision"] = "date_only"
    return payload


def _rules():
    with backend_on_path():
        from app.core.dignity_tables import CHALDEAN_ORDER
        from app.core.planetary_hours import WEEKDAY_RULERS, WEEKDAYS
    if tuple(CHALDEAN_ORDER) != PLANET_KEYS:
        raise RuntimeError(f"the Chaldean order is no longer {PLANET_KEYS}: {CHALDEAN_ORDER}")
    return tuple(CHALDEAN_ORDER), dict(zip(WEEKDAYS, WEEKDAY_RULERS, strict=True))


@functools.lru_cache(maxsize=1)
def season_dates() -> dict[str, dt.date]:
    """The Taipei calendar date on which the Sun reaches each season's longitude in YEAR."""
    out = {}
    with swiss() as swe:
        start = swe.julday(YEAR, 1, 1, 0.0)
        for key, longitude, _ in SEASONS:
            jd = swe.solcross_ut(longitude, start, swe.FLG_SWIEPH)
            year, month, day, _hour = swe.revjul(jd + TAIPEI_OFFSET_HOURS / 24)
            out[key] = dt.date(year, month, day)
    return out


def _clock(local_time: str) -> str:
    """「05:04」 from the product's 「2026-06-21 05:04:46」: whole minutes, truncated as a clock shows them."""
    return local_time.split(" ")[1][:5]


def _day(post, date: dt.date) -> dict:
    """The planetary day that starts at sunrise on `date`: its 24 hours as the product lists them."""
    hours: dict[str, dict] = {}
    for civil in (date, date + dt.timedelta(days=1)):
        listed = post(_request(civil, None))["derived_methods"]["planetary_hours"]
        if listed["status"] != "computed":
            raise RuntimeError(f"{civil}: the product gives no planetary hours")
        for hour in listed["birth_time_interval"]["candidates"]:
            hours.setdefault(hour["start"]["utc_time"], hour)
    ordered = sorted(hours.values(), key=lambda hour: hour["start"]["jd_ut"])
    first = next(i for i, hour in enumerate(ordered)
                 if hour["index"] == 1 and hour["start"]["local_time"].startswith(date.isoformat()))
    day = ordered[first:first + 24]
    if [hour["index"] for hour in day] != list(range(1, 25)):
        raise RuntimeError(f"{date}: the product's hours are not one planetary day 1…24")
    if len({hour["planetary_day_ruler"] for hour in day}) != 1:
        raise RuntimeError(f"{date}: the 24 hours name more than one day ruler")
    for before, after in zip(day, day[1:]):
        if before["end"]["jd_ut"] != after["start"]["jd_ut"]:
            raise RuntimeError(f"{date}: hour {before['index']} does not end where hour {after['index']} starts")
    noon = post(_request(date, (12, 0)))["derived_methods"]["planetary_hours"]["chart_instant"]["planetary_day"]
    if noon["sunrise"]["jd_ut"] != day[0]["start"]["jd_ut"] or noon["sunset"]["jd_ut"] != day[12]["start"]["jd_ut"]:
        raise RuntimeError(f"{date}: the listed hours do not start at the product's sunrise and sunset")
    return {"date": date, "hours": day, "ruler": day[0]["planetary_day_ruler"], "weekday": noon["weekday"],
            "day_minutes": noon["day_hour_minutes"], "night_minutes": noon["night_hour_minutes"],
            "sunrise": noon["sunrise"]["local_time"], "sunset": noon["sunset"]["local_time"],
            "next_sunrise": noon["next_sunrise"]["local_time"]}


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    dates = season_dates()
    with product_charts() as post:
        days = {key: _day(post, dates[key]) for key, _, _ in SEASONS}
        summer = dates["summer"]
        morning = post(_request(summer, (10, 0)))["derived_methods"]["planetary_hours"]["chart_instant"]
        small_hours = post(_request(summer + dt.timedelta(days=1), (3, 0)))["derived_methods"]["planetary_hours"]
        polar = post(_request(summer, (12, 0), POLAR_PLACE, POLAR_ZONE))["derived_methods"]["planetary_hours"]
    return {"days": days, "morning": morning, "small_hours": small_hours, "polar": polar}


def table_rows() -> dict[str, list[str]]:
    """{weekday: the rulers of hours 1…24}, by the product's rule."""
    order, weekday_rulers = _rules()
    return {weekday: [order[(order.index(ruler) + i) % 7] for i in range(24)]
            for weekday, ruler in weekday_rulers.items()}


def _check_table(rows: dict[str, list[str]]) -> None:
    """Dio's account, counted out: from Saturn on Saturday, every hour of day
    and night in turn; each weekday's first hour is where the count arrives."""
    order = list(PLANET_KEYS)
    week = ("saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday")
    for n, weekday in enumerate(week):
        expected = [order[(24 * n + i) % 7] for i in range(24)]
        if rows[weekday] != expected:
            raise RuntimeError(f"{weekday}: the product's hour rulers {rows[weekday]} are not Dio's count {expected}")


# --- figure 1: one planetary day, drawn to length --------------------------------

def _label(key: str, day: dict, bound: _fx.Bound) -> str:
    season = next(label for k, _, label in SEASONS if k == key)
    date = day["date"]
    return (f"{bound.num(f'{date.month}/{date.day}')}（{season}，{WEEKDAY_ZH[day['weekday']]}）")


def _band_wide(day: dict, bound: _fx.Bound, x0: float, width: float, y: float, h: float) -> list[str]:
    out = []
    hours = day["hours"]
    total = hours[-1]["end"]["jd_ut"] - hours[0]["start"]["jd_ut"]
    at = lambda jd: x0 + (jd - hours[0]["start"]["jd_ut"]) / total * width  # noqa: E731
    for hour in hours:
        a, b = at(hour["start"]["jd_ut"]), at(hour["end"]["jd_ut"])
        night = hour["period"] == "night"
        out.append(_fx.rect(a, y, b - a, h, "fx-fill-dot" if night else "fx-cell"))
        out.append(_fx.rect(a, y, b - a, h, "fx-lens"))
        out.append(_fx.glyph(hour["ruler"], (a + b) / 2, y + h / 2, 17, "fx-mk-gl"))
        out.append(_fx.text((a + b) / 2, y + h + 18, bound.num(str(hour["index_in_period"])), "fx-t fx-small", "middle"))
    for jd, text, anchor in ((hours[0]["start"]["jd_ut"], "日出 " + _clock(day["sunrise"]), "start"),
                             (hours[12]["start"]["jd_ut"], "日落 " + _clock(day["sunset"]), "middle"),
                             (hours[-1]["end"]["jd_ut"], "次日日出 " + _clock(day["next_sunrise"]), "end")):
        x = at(jd)
        out.append(_fx.line(x, y - 22, x, y + h + 4, "fx-axis"))
        out.append(_fx.text(x, y - 30, bound.num(text), "fx-t fx-small", anchor))
    return out


def _band_narrow(day: dict, bound: _fx.Bound, x0: float, scale: float, y: float, h: float) -> list[str]:
    """Two rows, day over night, each row as long as its twelve hours (one scale for all days)."""
    out = []
    for row, (period, label, minutes) in enumerate((("day", "晝", day["day_minutes"]),
                                                    ("night", "夜", day["night_minutes"]))):
        top = y + row * (h + 56)
        cell = minutes * scale
        out.append(_fx.text(x0 - 8, top + h / 2 + 5, label, "fx-t", "end"))
        hours = [hour for hour in day["hours"] if hour["period"] == period]
        for i, hour in enumerate(hours):
            a = x0 + i * cell
            out.append(_fx.rect(a, top, cell, h, "fx-fill-dot" if period == "night" else "fx-cell"))
            out.append(_fx.rect(a, top, cell, h, "fx-lens"))
            out.append(_fx.glyph(hour["ruler"], a + cell / 2, top + h / 2, 12, "fx-mk-gl"))
        start = day["sunrise"] if period == "day" else day["sunset"]
        each = bound.num(f"{minutes:.1f}")
        out.append(_fx.text(x0, top + h + 18, bound.num(f"{'日出' if period == 'day' else '日落'} {_clock(start)}")
                            + f"・每時 {each} 分", "fx-t fx-small"))
    return out


def _hours_drawing(layout: str, fid: str, days: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    H = 236 if wide else 268
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    longest = max(max(day["day_minutes"], day["night_minutes"]) for day in days.values())
    for key, _, _ in SEASONS:
        day = days[key]
        body = [_fx.text(24 if wide else 18, 40 if wide else 34, _label(key, day, bound), "fx-t fx-key")]
        if wide:
            body.append(_fx.text(W - 24, 40,
                                 f"晝時每時 {bound.num(f'{day['day_minutes']:.1f}')} 分・夜時每時 "
                                 f"{bound.num(f'{day['night_minutes']:.1f}')} 分", "fx-t fx-small", "end"))
            body += _band_wide(day, bound, 36.0, W - 72.0, 112.0, 44.0)
            body.append(_fx.text(36, 214, "白底：晝時（日出到日落十二等分）　點狀底：夜時（日落到次日日出十二等分）",
                                 "fx-t fx-small fx-dim"))
        else:
            body += _band_narrow(day, bound, 36.0, (W - 54.0) / (12 * longest), 62.0, 34.0)
            body.append(_fx.text(18, 250, "白底晝時、點狀底夜時", "fx-t fx-small fx-dim"))
        out.append(_fx.variant_group(key, SEASONS[0][0], "".join(body)))
    out.append("</svg>")
    return "".join(out)


def _hours_table(days: dict, bound: _fx.Bound) -> str:
    columns = ["第幾時"] + [_label(key, days[key], bound) for key, _, _ in SEASONS]
    rows = []
    for i in range(24):
        period = "晝" if i < 12 else "夜"
        cells = "".join(
            f"<td>{bound.num(_clock(days[key]['hours'][i]['start']['local_time']))} "
            f"{PLANETS[days[key]['hours'][i]['ruler']]}</td>" for key, _, _ in SEASONS)
        rows.append(f'<tr><th scope="row">{bound.num(str(i + 1))}（{period} {bound.num(str(i % 12 + 1))}）</th>{cells}</tr>')
    return _fx.data_table(columns, rows, summary="二十四個行星時的開始時刻與主星（表格）")


# --- figure 2: the Chaldean order and the weekdays ----------------------------------

def _star(layout: str, fid: str, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        H, cx, cy, r, side = 464, 240.0, 236.0, 160.0, 480.0
    else:
        H, cx, cy, r, side = 560, 170.0, 172.0, 108.0, 18.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    order, weekday_rulers = _rules()
    at = lambda i, radius: _fx.wheel_point(cx, cy, radius, 90 - i * 360 / 7)  # noqa: E731
    out.append(_fx.circle(cx, cy, r, "fx-hair"))
    for i in range(7):
        (x1, y1), (x2, y2) = at(i, r), at((i + 3) % 7, r)
        out.append(_fx.line(x1, y1, x2, y2, "fx-axis"))
    for i, planet in enumerate(order):
        x, y = at(i, r)
        out.append(_fx.circle(x, y, 19 if wide else 16, "fx-mk") + _fx.glyph(planet, x, y, 22 if wide else 18, "fx-mk-gl"))
        lx, ly = at(i, r + (46 if wide else 38))
        out.append(_fx.text(lx, ly + 5, PLANETS[planet], "fx-t fx-small", "middle"))
    lines = [
        ("圓周（順時針）：迦勒底序", "fx-t"),
        ("土、木、火、日、金、水、月", "fx-t fx-small"),
        ("由慢到快，行星時就照這個順序輪。", "fx-t fx-small fx-dim"),
        ("星形（每次跳三格）：星期的順序", "fx-t"),
        ("一天 " + bound.num("24") + " 時 ＝ " + bound.num("3") + " 輪 × " + bound.num("7") + " ＋ " + bound.num("3"),
         "fx-t fx-small"),
        ("所以下一天的第一時，落在往後數第三顆。", "fx-t fx-small fx-dim"),
    ]
    week = ("saturday", "sunday", "monday", "tuesday", "wednesday", "thursday", "friday")
    names = "→".join(WEEKDAY_ZH[w][-1] for w in week)
    lines.append(("星期" + names, "fx-t fx-small"))
    for a, b in zip(week, week[1:]):
        if order[(order.index(weekday_rulers[a]) + 3) % 7] != weekday_rulers[b]:
            raise RuntimeError(f"{b}'s ruler is not three places after {a}'s in the Chaldean order")
    y = 136.0 if wide else cy + r + 74
    for text, cls in lines:
        out.append(_fx.text(side, y, text, cls))
        y += 30 if "fx-small" not in cls else 26
        if text.startswith("由慢"):
            y += 18
    out.append("</svg>")
    return "".join(out)


# --- table 1 -----------------------------------------------------------------------

def _week_table(rows: dict[str, list[str]], bound: _fx.Bound) -> str:
    week = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
    head = ('<th scope="col">星期（日主）</th>'
            + "".join(f'<th scope="col">晝 {bound.num(str(i))}</th>' for i in range(1, 13))
            + "".join(f'<th scope="col">夜 {bound.num(str(i))}</th>' for i in range(1, 13)))
    body = []
    for weekday in week:
        cells = "".join(f"<td>{SHORT[p]}</td>" for p in rows[weekday])
        body.append(f'        <tr data-weekday="{weekday}"><th scope="row">{WEEKDAY_ZH[weekday]}（{PLANETS[rows[weekday][0]]}）</th>'
                    f"{cells}</tr>")
    return (f'    <table class="ar-table" id="hours-table">\n'
            f'      <caption id="tab1-cap">表 1　一週七天、每天二十四個行星時的主星。日＝太陽、月＝月亮、火＝火星、'
            f'水＝水星、木＝木星、金＝金星、土＝土星；晝時從日出數起，夜時從日落數起。</caption>\n'
            f"      <thead><tr>{head}</tr></thead>\n      <tbody>\n" + "\n".join(body) + "\n      </tbody>\n    </table>")


def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    days = data["days"]
    rows = table_rows()
    _check_table(rows)
    bound = _fx.Bound()
    band = _fx.figure(
        fid="fig-hours-day",
        hero=True,
        title="臺北一個行星日的二十四個行星時，依季節切換",
        caption=(f"<b>{bound.label('圖 1')}</b>臺北的一個行星日，從日出到次日日出。每一格是一個行星時，"
                 "寬度照它實際的長短畫，格中是那一時的主星。白底是晝時，點狀底是夜時；"
                 f"按鈕切換 {bound.num(str(YEAR))} 年夏至、春分、冬至那一天（臺北日期）。沒有開啟指令碼時顯示夏至。"
                 "每一格都是本站計算服務對那一天的回答。"),
        art=_fx.FigureArt.drawn(_hours_drawing, "fig-hours-day", days, bound),
        controls=_fx.FigureControls(variants=tuple((key, f"{label}") for key, _, label in SEASONS),
                                    switch_label="切換季節"),
        table=_hours_table(days, bound),
        bound=bound,
    )
    star = _fx.figure(
        fid="fig-hours-star",
        title="迦勒底序排成一圈，每次跳三格連成的七角星就是星期的順序",
        caption=(f"<b>{bound.label('圖 2')}</b>七顆行星依迦勒底序（由慢到快）排成一圈。行星時照圓周順著輪；"
                 "一天二十四時，輪完三圈還多三時，所以下一天的第一時要往後跳三格。"
                 "照跳三格連線，得到的七角星正是星期六、日、一、二、三、四、五的順序。"),
        art=_fx.FigureArt.drawn(_star, "fig-hours-star", bound),
        bound=bound,
    )
    summer, winter, equinox = days["summer"], days["winter"], days["equinox"]
    morning, small, polar = data["morning"], data["small_hours"], data["polar"]
    if polar["status"] != "not_applicable" or polar["reason_code"] != "no_sunrise_sunset_cycle_around_instant":
        raise RuntimeError(f"the polar example is now {polar['status']} / {polar['reason_code']}")
    small_day, small_hour = small["chart_instant"]["planetary_day"], small["chart_instant"]["planetary_hour"]
    if small_day["sunrise_local_date"] != summer["date"].isoformat() or small_hour["period"] != "night":
        raise RuntimeError("the small-hours example no longer belongs to the summer day's night")
    winter_fourth = winter["hours"][3]
    quoted = [
        f"日出 {_clock(summer['sunrise'])}",
        f"日落 {_clock(summer['sunset'])}",
        f"晝時每時約 {summer['day_minutes']:.1f} 分鐘",
        f"夜時每時約 {summer['night_minutes']:.1f} 分鐘",
        f"冬至那一天（{winter['date'].month} 月 {winter['date'].day} 日）正好反過來：晝時約 {winter['day_minutes']:.1f} 分鐘、"
        f"夜時約 {winter['night_minutes']:.1f} 分鐘",
        f"春分那一天（{equinox['date'].month} 月 {equinox['date'].day} 日）晝時約 {equinox['day_minutes']:.1f} 分鐘",
        f"第 {morning['planetary_hour']['index']} 個行星時，主星是{morning['planetary_hour']['ruler_name']}",
        f"從 {_clock(morning['planetary_hour']['start']['local_time'])} 到 {_clock(morning['planetary_hour']['end']['local_time'])}",
        f"行星日的日主是{small_day['ruler_name']}",
        f"第 {small_hour['index']} 時（夜時第 {small_hour['index_in_period']} 時），主星是{small_hour['ruler_name']}",
        f"第四時是{PLANETS[winter_fourth['ruler']]}",
        f"{summer['date'].month} 月 {summer['date'].day} 日",
        WEEKDAY_ZH[winter["weekday"]],
        f"<b>{summer['day_minutes']:.1f}</b>", f"<b>{summer['night_minutes']:.1f}</b>",
        f"<b>{equinox['day_minutes']:.1f}</b>",
        f"一個晝時約 {summer['day_minutes']:.1f} 分鐘，夜時約 {summer['night_minutes']:.1f} 分鐘",
    ]
    if morning["planetary_day"]["ruler"] != summer["ruler"]:
        raise RuntimeError("the morning example is not on the summer day")
    if winter_fourth["ruler"] != rows[winter["weekday"]][3]:
        raise RuntimeError("the product's fourth hour disagrees with table 1")
    return {"fx-defs": _fx.defs(PLANET_KEYS), "hours-day": band, "hours-star": star,
            "hours-table": _week_table(rows, bound)}, quoted
