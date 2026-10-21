"""〈上升星座查詢表為什麼常常不準〉: figure 1 (how often two model lookup
tables give a different rising sign than the exact computation), figure 2 (the
minutes each sign takes to rise at Taipei against table A's two hours, a
switch between the two), figure 3 (a table made for 25°N used at other
latitudes; pointing at a city writes its share), table 1 (clock time against
local mean time, abroad and in Taiwan), table 2 (the product's Ascendant for
one clock time at four Taiwanese places) and the numbers the prose quotes.
The figures are article figures (`_fx`).

The tables are models the article defines, not anyone's published table:
  A  sun sign plus two-hour blocks: during the two hours that start at clock
     time C the rising sign is the Sun's own sign, then one sign later every
     two hours; C is the start that suits Taipei best over the year, and the
     table is given the Sun's exact sign, so A is the best case of its kind.
  B  exact for Taipei (GeoNames 1668341) at the clock time read as UTC+8 all
     year: exact at Taipei by construction, used at another place or in a
     daylight-saving summer.
"Exact" is Swiss Ephemeris houses_ex at the instant the IANA zone gives for
the clock time (UT1 = UTC here; under a second, irrelevant at 10-minute
steps).  Places are the product's catalogue rows (GeoNames cities500); the
generator reads them back through the product's place search.  The one value
checked against a second algorithm: at NOAA's geometric sunrise the product's
Ascendant must equal NOAA's apparent longitude of the Sun (the rising Sun is
on the ecliptic and on the horizon).
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import _fx, _noaa
from ._common import SIGNS, TAIPEI, calc_ut, product_charts, product_client, swiss


FRAGMENT = "blog-rising-sign-tables"
YEAR = 2025
STEP_MINUTES = 10
# name: (GeoNames id, latitude, longitude, IANA zone)
PLACES = {
    "臺北": ("1668341", *TAIPEI, "Asia/Taipei"),
    "金門": ("1678008", 24.43415, 118.31712, "Asia/Taipei"),
    "花蓮": ("1674504", 23.97694, 121.60444, "Asia/Taipei"),
    "恆春": ("1676242", 22.00417, 120.74389, "Asia/Taipei"),
    "東京": ("1850147", 35.6895, 139.69171, "Asia/Tokyo"),
    "首爾": ("1835848", 37.566, 126.9784, "Asia/Seoul"),
    "新加坡": ("1880252", 1.28967, 103.85007, "Asia/Singapore"),
    "倫敦": ("2643743", 51.50853, -0.12574, "Europe/London"),
    "馬德里": ("3117735", 40.4165, -3.70256, "Europe/Madrid"),
    "紐約": ("5128581", 40.71427, -74.00597, "America/New_York"),
    "雪梨": ("2147714", -33.86785, 151.20732, "Australia/Sydney"),
}
SEARCH = {"臺北": "Taipei", "金門": "Jincheng", "花蓮": "Hualien City", "恆春": "Hengchun", "東京": "Tokyo",
          "首爾": "Seoul", "新加坡": "Singapore", "倫敦": "London", "馬德里": "Madrid", "紐約": "New York City",
          "雪梨": "Sydney"}
ELSEWHERE_IN_TAIWAN = ("金門", "恆春", "花蓮")
ABROAD = ("東京", "首爾", "新加坡", "倫敦", "馬德里", "紐約")
FIG2_MARKS = ("雪梨", "新加坡", "臺北", "東京", "倫敦")
DST_YEAR = 1975
TABLE_LATITUDE = 25.0
# Table A's block: one sign every two hours.
BLOCK_MINUTES = 120
# The sidereal-time sweeps step the ARMC by this many degrees.
ARMC_STEP = 0.25
SWEEP = round(360 / ARMC_STEP)
SIGN_KEYS = ("aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius",
             "capricorn", "aquarius", "pisces")
CITY_KEYS = {"雪梨": "sydney", "新加坡": "singapore", "臺北": "taipei", "東京": "tokyo", "倫敦": "london"}
# Table 2: one synthetic clock time, the same at four places.
EXAMPLE = datetime(YEAR, 3, 21, 6, 0)
SUNRISE_DAY = date(YEAR, 3, 21)


def _check_catalogue() -> None:
    with product_client() as post:
        for name, (record, lat, lon, zone) in PLACES.items():
            found = post("/api/places/search", {"query": SEARCH[name], "limit": 10})
            rows = [row for row in found["results"] if row.get("source_record_id") == record]
            if not rows or (rows[0]["latitude"], rows[0]["longitude"], rows[0]["timezone"]) != (lat, lon, zone):
                raise RuntimeError(f"the catalogue no longer has {name} as {record} {lat} {lon} {zone}")


def _year_instants(year: int, zone: str):
    """Every STEP_MINUTES of local clock time in the year: (clock minute of day, aware local time)."""
    z = ZoneInfo(zone)
    clock = datetime(year, 1, 1)
    while clock.year == year:
        local = clock.replace(tzinfo=z)
        # A clock time the zone skips is not a birth time anyone has.
        if local.astimezone(timezone.utc).astimezone(z).replace(tzinfo=None) == clock:
            yield clock.hour * 60 + clock.minute, local
        clock += timedelta(minutes=STEP_MINUTES)


def _data() -> dict:
    d: dict = {}
    with swiss() as swe:
        def jd(utc: datetime) -> float:
            return swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60 + utc.second / 3600)

        def sign(j: float, lat: float, lon: float) -> int:
            return int(swe.houses_ex(j, lat, lon, b"W")[1][0] // 30)

        tp = PLACES["臺北"]
        rows = []
        for minute, local in _year_instants(YEAR, tp[3]):
            j = jd(local.astimezone(timezone.utc))
            rows.append((minute, int(calc_ut(swe, j, swe.SUN)[0] // 30), sign(j, tp[1], tp[2]),
                         {name: sign(j, PLACES[name][1], PLACES[name][2]) for name in ELSEWHERE_IN_TAIWAN}))
        n = len(rows)
        # The same (clock minute, Sun sign, rising sign) recurs on many days; count each once.
        triples = Counter((minute, sun, asc) for minute, sun, asc, _ in rows)
        split = {}
        for start in range(0, 1440, STEP_MINUTES):
            split[start] = sum(count for (minute, sun, asc), count in triples.items()
                               if (sun + (minute - start) // BLOCK_MINUTES) % 12 != asc) / n
        best = min(split, key=lambda start: split[start])
        d["table_a"] = (best, split[best])
        d["table_b"] = {name: sum(other[name] != asc for _, _, asc, other in rows) / n for name in ELSEWHERE_IN_TAIWAN}
        # Table B in a daylight-saving year: the table reads the clock as UTC+8.
        wrong = summer = summer_wrong = total = 0
        for _, local in _year_instants(DST_YEAR, tp[3]):
            truth = sign(jd(local.astimezone(timezone.utc)), tp[1], tp[2])
            table = sign(jd(local.replace(tzinfo=None) - timedelta(hours=8)), tp[1], tp[2])
            total += 1
            wrong += truth != table
            if local.utcoffset() != timedelta(hours=8):
                summer += 1
                summer_wrong += truth != table
        d["dst"] = (summer_wrong / summer, wrong / total)
        # Sidereal-time sweeps: one sidereal day in ARMC_STEP degrees of ARMC, the year's mean obliquity.
        eps = sum(swe.calc_ut(swe.julday(YEAR, month, 1, 0.0), swe.ECL_NUT)[0][0] for month in range(1, 13)) / 12

        def armc_signs(lat: float, shift: float = 0.0) -> list[int]:
            return [int(swe.houses_armc((k * ARMC_STEP + shift) % 360, lat, eps, b"W")[1][0] // 30) for k in range(SWEEP)]

        base = armc_signs(TABLE_LATITUDE)
        lats = sorted(set(range(-40, 61, 5)) | {PLACES[name][1] for name in FIG2_MARKS})
        d["latitude"] = {lat: sum(a != b for a, b in zip(base, armc_signs(lat))) / SWEEP for lat in lats}
        # Rising time of each sign at Taipei, from the same sweep (minutes of a sidereal day).
        def asc_at(armc: float) -> float:
            return swe.houses_armc(armc % 360, tp[1], eps, b"W")[1][0]

        crossings = []
        for k in range(12):  # the ARMC at which each sign begins to rise, by bisection
            lo = next(step * ARMC_STEP for step in range(SWEEP)
                      if int(asc_at(step * ARMC_STEP) // 30) == (k - 1) % 12
                      and int(asc_at(step * ARMC_STEP + ARMC_STEP) // 30) == k)
            hi = lo + ARMC_STEP
            for _ in range(40):
                mid = (lo + hi) / 2
                if int(asc_at(mid) // 30) == k:
                    hi = mid
                else:
                    lo = mid
            crossings.append(hi)
        sidereal_day = 1436.0682  # minutes of mean solar time
        d["rising"] = [((crossings[(k + 1) % 12] - crossings[k]) % 360) / 360 * sidereal_day for k in range(12)]
        # Clock against local mean time, mid-January and mid-July.
        offsets = []
        for name in ("臺北", "金門") + ABROAD:
            _, lat, lon, zone = PLACES[name]
            seen: list[tuple[int, float, float, float]] = []
            for month in (1, 7):
                utc_offset = datetime(YEAR, month, 15, 12, tzinfo=ZoneInfo(zone)).utcoffset()
                if utc_offset is None:
                    raise RuntimeError(f"{zone} has no offset in {YEAR}-{month:02d}")
                offset = utc_offset.total_seconds() / 60
                lead = lon * 4 - offset  # local mean time minus clock time, minutes
                if seen and seen[-1][1] == offset:
                    continue
                shift = lead * 360 / 1436.0682
                local = armc_signs(lat)
                share = sum(a != b for a, b in zip(local, armc_signs(lat, shift))) / SWEEP
                seen.append((month, offset, lead, share))
            offsets.append((name, seen))
        d["offsets"] = offsets
    return d


def _product(d: dict) -> None:
    """Table 2 and the sunrise check, from the product's own answers."""
    rows = []
    with product_charts() as post:
        def chart(name: str, local: datetime) -> dict:
            _, lat, lon, zone = PLACES[name]
            return post({"birth_time_precision": "exact",
                         "datetime": {"year": local.year, "month": local.month, "day": local.day,
                                      "hour": local.hour, "minute": local.minute, "second": local.second},
                         "location": {"latitude": lat, "longitude": lon},
                         "timezone": {"mode": "iana", "iana_name": zone},
                         "options": {"house_system": "W", "include_houses": True}})

        for name in ("臺北",) + ELSEWHERE_IN_TAIWAN:
            asc = chart(name, EXAMPLE)["astronomical_data"]["angles"]
            rows.append((name, asc["sign_positions"]["asc"], asc["asc"]))
        d["example"] = rows
        _, lat, lon, _ = PLACES["臺北"]
        rise = _noaa.sunrise_utc(SUNRISE_DAY, lat, lon, zenith=90.0)
        rise = (rise + timedelta(microseconds=500000)).replace(microsecond=0)
        local = rise.astimezone(ZoneInfo("Asia/Taipei")).replace(tzinfo=None)
        asc = chart("臺北", local)["astronomical_data"]["angles"]["asc"]
        sun = _noaa.sun(_noaa.julian_day(rise))["apparent_longitude"]
        d["sunrise"] = (local, asc, sun)
    # The year's earliest and latest sunrise at Taipei (NOAA's refracted upper limb).
    rises = []
    day = date(YEAR, 1, 1)
    while day.year == YEAR:
        rise = _noaa.sunrise_utc(day, lat, lon).astimezone(ZoneInfo("Asia/Taipei"))
        rises.append(rise.hour * 60 + rise.minute + rise.second / 60)
        day += timedelta(days=1)
    d["sunrise_range"] = (min(rises), max(rises))


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _hm(minutes: float) -> str:
    sign = "+" if minutes >= 0 else "−"
    m = round(abs(minutes))
    return f"{sign}{m // 60} 小時 {m % 60:02d} 分" if m >= 60 else f"{sign}{m} 分"


def _bars(d: dict) -> list[tuple[str, str, str, float]]:
    """Figure 1's rows: (table, where it is used, its engraving, share of clock times it gets wrong)."""
    _, share = d["table_a"]
    out = [("太陽星座＋兩小時時段表", "用在臺北（最有利的切法）", "fx-fill-cross", share)]
    for name in ELSEWHERE_IN_TAIWAN:
        out.append(("臺北精算表", f"用在{name}", "fx-fill-hatch", d["table_b"][name]))
    out.append(("臺北精算表", f"{DST_YEAR} 年臺北的夏令時間期間", "fx-fill-hatch", d["dst"][0]))
    return out


def _share_drawing(layout: str, fid: str, bars: list, bound: _fx.Bound) -> str:
    """Figure 1, one layout: a row per table and place, the share of clock times
    the table gets wrong as a bar on a 0–100% scale."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (24.0, 760.0) if wide else (14.0, 326.0)
    out = []
    y = 20.0 if wide else 14.0
    for table, where, fill, share in bars:
        label, value = f"{table}，{where}", bound.num(_pct(share))
        if wide:
            out.append(_fx.text(x0, y + 20, label, "fx-t"))
            by, bh = y + 30, 24.0
            out.append(_fx.text(x1 + 16, by + 18, value, "fx-t fx-num"))
            y += 66
        else:
            lines = [label] if _fx.text_width(label, latin=0.52) * 13.5 < 250 else [f"{table}，", where]
            for i, line in enumerate(lines):
                out.append(_fx.text(x0, y + 16 + i * 18, line, "fx-t"))
            out.append(_fx.text(x1, y + 16, value, "fx-t fx-num", "end"))
            by, bh = y + 16 + (len(lines) - 1) * 18 + 8, 18.0
            y = by + bh + 12
        out.append(_fx.rect(x0, by, x1 - x0, bh, "fx-track"))
        out.append(_fx.rect(x0, by, max((x1 - x0) * share, 2), bh, fill))
    axis = y + (2 if wide else 0)
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    for t in (0, 25, 50, 75, 100):
        x = x0 + (x1 - x0) * t / 100
        out.append(_fx.line(x, axis, x, axis + 5, "fx-axis"))
        anchor = "start" if t == 0 else "end" if t == 100 and not wide else "middle"
        out.append(_fx.text(x, axis + 22, bound.scale(f"{t}%"), "fx-t fx-small fx-num", anchor))
    note = (f"{bound.num(str(YEAR))} 年（夏令時間一列為 {bound.num(str(DST_YEAR))} 年）",
            f"每 {bound.num(str(STEP_MINUTES))} 分鐘的鐘面時刻")
    if wide:
        out.append(_fx.text(x0, axis + 50, "".join(note), "fx-t fx-small fx-dim"))
        H = axis + 66
    else:
        out.append(_fx.text(x0, axis + 46, note[0], "fx-t fx-small fx-dim"))
        out.append(_fx.text(x0, axis + 62, note[1], "fx-t fx-small fx-dim"))
        H = axis + 76
    return "".join([_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)] + out + ["</svg>"])


def _share_figure(d: dict) -> str:
    bound = _fx.Bound()
    bars = _bars(d)
    rows = "".join(f'<tr><th scope="row">{table}，{where}</th><td class="n">{bound.num(_pct(share))}</td></tr>'
                   for table, where, _, share in bars)
    table = _fx.data_table('<th scope="col">查詢表與用在哪裡</th><th scope="col" class="n">查錯的時刻佔比</th>', rows)
    markup = _fx.figure(
        fid="fig-share",
        hero=True,
        title="兩種模型查詢表與精算給出不同上升星座的時刻佔比",
        caption=(f"<b>{bound.label('圖 1')}</b>兩種模型查詢表與精算給出不同上升星座的時刻佔比。第一列是只看太陽星座與出生時段的表，"
                 "已經把時段的切點挑到對臺北最有利、並給它太陽的精確星座；其餘四列是一張照臺北精確算出的表，"
                 "拿到別的地方或夏令時間的年份去用。兩種表都是本文自己定義的模型，不是任何特定網站或書上的表。"),
        art=_fx.FigureArt.drawn(_share_drawing, "fig-share", bars, bound),
        table=table,
        bound=bound,
    )
    return markup


def _lat_text(lat: float) -> str:
    return f"{'南' if lat < 0 else '北'}緯 {abs(lat):.1f}°"


def _latitude_drawing(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    """Figure 3, one layout: the share of a sidereal day a table made for 25°N
    gets wrong at each latitude, the five cities as marks."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    L, R, T, B = (96.0, 846.0, 40.0, 316.0) if wide else (52.0, 322.0, 36.0, 286.0)
    top_share = 0.7
    X = lambda lat: L + (R - L) * (lat + 40) / 100  # noqa: E731
    Y = lambda share: B - (B - T) * share / top_share  # noqa: E731
    H = B + (74 if wide else 84)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for share in (0, 0.2, 0.4, 0.6):
        out.append(_fx.line(L, Y(share), R, Y(share), "fx-hair" if share else "fx-axis"))
        out.append(_fx.text(L - 8, Y(share) + 5, bound.scale(_pct(share)), "fx-t fx-small fx-num", "end"))
    for lat in (-40, -20, 0, 20, 40, 60):
        out.append(_fx.line(X(lat), B, X(lat), B + 5, "fx-axis"))
        name = f"{'南' if lat < 0 else '北' if lat > 0 else ''}{bound.scale(f'{abs(lat)}°')}"
        anchor = "end" if lat == 60 and not wide else "middle"
        out.append(_fx.text(X(lat), B + 22, name, "fx-t fx-small fx-num", anchor))
    table_x = X(TABLE_LATITUDE)
    out.append(_fx.line(table_x, T, table_x, B, "fx-sunline"))
    out.append(_fx.text(table_x + 6, T + 14, f"表的緯度：北 {bound.num(f'{TABLE_LATITUDE:g}')}°", "fx-t fx-small fx-key"))
    grid = [lat for lat in d["latitude"] if lat in range(-40, 61, 5)]
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(lat))} {_fx.f(Y(d['latitude'][lat]))}" for lat in grid), "fx-axis"))
    for name in FIG2_MARKS:
        place = PLACES[name][1]
        share = d["latitude"][place]
        x, y = X(place), Y(share)
        value = bound.num(_pct(share))
        out.append(f'<g class="fx-row" data-fx-key="{CITY_KEYS[name]}" tabindex="0" '
                   f'aria-label="{name}，{bound.num(_lat_text(place))}，查錯 {value}">')
        out.append(_fx.circle(x, y, 18, "fx-hit"))
        out.append(_fx.circle(x, y, 7 if wide else 6, "fx-mk"))
        label = f"{name} {value}"
        if x > R - 40:
            out.append(_fx.text(x + 8, y - 14, label, "fx-t fx-key", "end"))
        elif x < L + 40:
            out.append(_fx.text(x - 8, y - 14, label, "fx-t fx-key"))
        else:
            out.append(_fx.text(x, y - 14, label, "fx-t fx-key", "middle"))
        out.append("</g>")
    if wide:
        out.append(_fx.text(L, B + 52, "橫軸：出生地緯度　縱軸：上升星座與表不同的時刻佔比", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(14, B + 50, "橫軸：出生地緯度", "fx-t fx-small fx-dim"))
        out.append(_fx.text(14, B + 68, "縱軸：上升星座與表不同的時刻佔比", "fx-t fx-small fx-dim"))
    out.append("</svg>")
    if max(d["latitude"].values()) > top_share:
        raise RuntimeError("the latitude curve outgrew figure 3's scale")
    return "".join(out)


def _latitude_figure(d: dict) -> str:
    bound = _fx.Bound()
    for label in ("圖 3", "表 1"):
        bound.label(label)
    marks = {PLACES[name][1]: name for name in FIG2_MARKS}
    rows = []
    for lat in sorted(d["latitude"]):
        name = marks.get(lat)
        if name is None and lat not in range(-40, 61, 5):
            continue
        key = f' data-fx-key="{CITY_KEYS[name]}"' if name else ""
        # 每一列都有緯度、不一定有城市：緯度是列標頭，城市是一般的格（沒有城市的列，列標頭不會是空的）。
        rows.append(f'<tr{key}><th scope="row" class="n">{bound.num(_lat_text(lat))}</th><td>{name or ""}</td>'
                    f'<td class="n">{bound.num(_pct(d["latitude"][lat]))}</td></tr>')
    table = _fx.data_table('<th scope="col" class="n">緯度</th><th scope="col">城市</th>'
                           '<th scope="col" class="n">查錯的時刻佔比</th>', rows)
    notes = []
    for name in FIG2_MARKS:
        lat = PLACES[name][1]
        notes.append(_fx.Note(CITY_KEYS[name], None, (
            f"{name}（{bound.num(_lat_text(lat))}）：拿為北緯 {bound.num(f'{TABLE_LATITUDE:g}')} 度精確算出的表來查，"
            f"一個恆星日裡有 {bound.num(_pct(d['latitude'][lat]))} 的時刻查錯。")))
    markup = _fx.figure(
        fid="fig-latitude",
        title=f"一張為北緯 {bound.num(f'{TABLE_LATITUDE:g}')} 度精算的上升星座表，用在其他緯度時查錯的時刻佔比",
        caption=(f"<b>{bound.label('圖 3')}</b>一張為北緯 {bound.num(f'{TABLE_LATITUDE:g}')} 度精確算出的上升星座表，"
                 "用在其他緯度時，一個恆星日裡查錯的時刻佔比"
                 f"（恆星時每 {bound.num(f'{ARMC_STEP:g}')} 度取樣一次，黃赤交角取 {bound.num(str(YEAR))} 年的平均）。"
                 f"只有緯度不同；經度與時鐘的差別另見{bound.label('表 1')}。"),
        art=_fx.FigureArt.drawn(
            _latitude_drawing, "fig-latitude", d, bound,
            notes=notes,
            idle="用 Tab 鍵移到一個城市上，或用滑鼠指著它，這裡會寫出它的緯度與查錯的時刻佔比。",
        ),
        table=table,
        bound=bound,
    )
    return markup


RISING_VARIANTS = (("actual", f"實際：{YEAR} 年臺北"), ("model", "模型：每個星座兩小時"))


def _rising_drawing(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    """Figure 2, one layout: the minutes each sign takes to rise, the model's
    two hours each against Taipei's own; the buttons switch between them."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    top_minutes = 150
    minutes = {"actual": d["rising"], "model": [float(BLOCK_MINUTES)] * 12}
    fills = {"actual": "fx-fill-cross", "model": "fx-fill-hatch"}
    out = []
    if wide:
        L, R, T, B = 96.0, 852.0, 44.0, 300.0
        col = (R - L) / 12
        Y = lambda m: B - (B - T) * m / top_minutes  # noqa: E731
        H = B + 66
        for t in range(0, top_minutes + 1, 30):
            out.append(_fx.line(L, Y(t), R, Y(t), "fx-hair" if t else "fx-axis"))
            out.append(_fx.text(L - 8, Y(t) + 5, bound.scale(str(t)), "fx-t fx-small fx-num", "end"))
        out.append(_fx.text(L - 8, T - 16, "分鐘", "fx-t fx-small fx-dim", "end"))
        for s, key in enumerate(SIGN_KEYS):
            cx = L + (s + 0.5) * col
            out.append(_fx.glyph(key, cx, B + 20, 16, "fx-mk-gl"))
            out.append(_fx.text(cx, B + 50, SIGNS[s], "fx-t fx-small", "middle"))
        for variant, _ in RISING_VARIANTS:
            body = []
            for s in range(12):
                cx = L + (s + 0.5) * col
                m = minutes[variant][s]
                body.append(_fx.rect(cx - 17, Y(m), 34, B - Y(m), fills[variant]))
                body.append(_fx.rect(cx - 17, Y(m), 34, B - Y(m), "fx-inset-frame"))
                body.append(_fx.text(cx, Y(m) - 8, bound.num(f"{m:.0f}"), "fx-t fx-small fx-num fx-key", "middle"))
            out.append(_fx.variant_group(variant, RISING_VARIANTS[0][0], "".join(body)))
        ref = Y(BLOCK_MINUTES)
        out.append(_fx.line(L, ref, R, ref, "fx-sunline"))
        out.append(_fx.text(R, T - 16, f"虛線：兩小時（{bound.num(str(BLOCK_MINUTES))} 分鐘）", "fx-t fx-small", "end"))
    else:
        L, R, top, rh = 72.0, 284.0, 44.0, 26.0
        X = lambda m: L + (R - L) * m / top_minutes  # noqa: E731
        B = top + 12 * rh
        H = B + 70
        for s, key in enumerate(SIGN_KEYS):
            cy = top + (s + 0.5) * rh
            out.append(_fx.glyph(key, 24, cy, 12, "fx-mk-gl"))
            out.append(_fx.text(36, cy + 5, SIGNS[s], "fx-t fx-small"))
        for variant, _ in RISING_VARIANTS:
            body = []
            for s in range(12):
                cy = top + (s + 0.5) * rh
                m = minutes[variant][s]
                body.append(_fx.rect(L, cy - 8, X(m) - L, 16, fills[variant]))
                body.append(_fx.rect(L, cy - 8, X(m) - L, 16, "fx-inset-frame"))
                body.append(_fx.text(X(m) + 5, cy + 5, bound.num(f"{m:.0f}"), "fx-t fx-small fx-num"))
            out.append(_fx.variant_group(variant, RISING_VARIANTS[0][0], "".join(body)))
        ref = X(BLOCK_MINUTES)
        out.append(_fx.line(ref, top - 6, ref, B, "fx-sunline"))
        out.append(_fx.text(R + 30, top - 14, f"虛線：兩小時（{bound.num(str(BLOCK_MINUTES))} 分鐘）", "fx-t fx-small", "end"))
        out.append(_fx.line(L, B, R, B, "fx-axis"))
        for t in range(0, top_minutes + 1, 30):
            out.append(_fx.line(X(t), B, X(t), B + 5, "fx-axis"))
            out.append(_fx.text(X(t), B + 22, bound.scale(str(t)), "fx-t fx-small fx-num", "middle"))
        out.append(_fx.text(L, B + 48, "分鐘", "fx-t fx-small fx-dim"))
    if max(d["rising"]) > top_minutes:
        raise RuntimeError("a sign takes longer than figure 2's scale")
    return "".join([_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)] + out + ["</svg>"])


def _rising_figure(d: dict) -> str:
    bound = _fx.Bound()
    for _, label in RISING_VARIANTS:
        bound.label(label)
    rows = "".join(f'<tr><th scope="row">{SIGNS[s]}</th><td class="n">{bound.num(str(BLOCK_MINUTES))}</td>'
                   f'<td class="n">{bound.num(f"{m:.0f}")}</td></tr>' for s, m in enumerate(d["rising"]))
    table = _fx.data_table('<th scope="col">星座</th><th scope="col" class="n">模型（分鐘）</th>'
                           f'<th scope="col" class="n">{bound.num(str(YEAR))} 年臺北（分鐘）</th>', rows)
    markup = _fx.figure(
        fid="fig-rising",
        title="每個星座升起要多少分鐘：每兩小時一個星座的模型，與臺北的實際",
        caption=(f"<b>{bound.label('圖 2')}</b>每個星座從開始升起到整個升完，要多少分鐘的鐘面時間。按鈕切換兩種說法："
                 "「太陽星座加出生時段」那種表假設每個星座都是兩小時；實際上，在 "
                 f"{bound.num(str(YEAR))} 年臺北的緯度，有的星座約一個半小時就升完，有的要兩個多小時"
                 f"（恆星時每 {bound.num(f'{ARMC_STEP:g}')} 度取樣，黃赤交角取 {bound.num(str(YEAR))} 年的平均）。"
                 "虛線是兩小時。"),
        art=_fx.FigureArt.drawn(_rising_drawing, "fig-rising", d, bound),
        controls=_fx.FigureControls(
            variants=RISING_VARIANTS,
            switch_label="切換模型與實際",
        ),
        table=table,
        bound=bound,
    )
    return markup


def _offset_rows(d: dict) -> str:
    rows = []
    for name, seen in d["offsets"]:
        for month, offset, lead, share in seen:
            hours = offset / 60
            zone = f"UTC{'+' if hours >= 0 else '−'}{abs(hours):g}"
            when = "全年" if len(seen) == 1 else f"{month} 月"
            rows.append(f'          <tr><td>{name}</td><td class="n">{when}</td><td class="n">{zone}</td>'
                        f'<td class="n">{_hm(lead)}</td><td class="n">{_pct(share)}</td></tr>')
    return "\n".join(rows)


def _example_rows(d: dict) -> str:
    rows = []
    for name, (sign, dms, _), _lon in d["example"]:
        hl = ' class="hl"' if name == "臺北" else ""
        rows.append(f'          <tr{hl}><td>{name}</td><td class="n">{PLACES[name][1]:.2f}°N、{PLACES[name][2]:.2f}°E</td>'
                    f'<td>{SIGNS[sign]} {dms.split(chr(8242))[0]}′</td></tr>')
    return "\n".join(rows)


def build() -> tuple[dict[str, str], list[str]]:
    _check_catalogue()
    d = _data()
    _product(d)
    start, share = d["table_a"]
    taipei = [row for row in d["example"] if row[0] == "臺北"][0]
    differing = [row[0] for row in d["example"] if row[1][0] != taipei[1][0]]
    if not differing:
        raise RuntimeError("the example clock time gives every place Taipei's rising sign")
    local, asc, sun = d["sunrise"]
    gap = abs((asc - sun + 180) % 360 - 180)
    if gap > 0.25:  # about a minute of the Ascendant's motion: NOAA's stated accuracy
        raise RuntimeError(f"Ascendant {asc} at NOAA's sunrise is {gap}° from NOAA's Sun {sun}")
    rising = d["rising"]
    if rising.index(min(rising)) not in (0, 11) or rising.index(max(rising)) not in (4, 7):
        raise RuntimeError("the fastest and slowest signs are no longer Aries/Pisces and Leo/Scorpio")
    offsets = {name: seen for name, seen in d["offsets"]}
    quoted = [
        f"{start // 60:02d}:{start % 60:02d} 到 {(start + BLOCK_MINUTES) // 60:02d}:{(start + BLOCK_MINUTES) % 60:02d}",
        f"仍有 {_pct(share)} 的時刻查錯",
        f"金門有 {_pct(d['table_b']['金門'])}、恆春有 {_pct(d['table_b']['恆春'])}、花蓮有 {_pct(d['table_b']['花蓮'])}",
        f"夏令時間期間有 {_pct(d['dst'][0])} 的時刻查錯，全年平均也有 {_pct(d['dst'][1])}",
        f"最快的牡羊與雙魚約 {min(rising):.0f} 分鐘，最慢的獅子與天蠍約 {max(rising):.0f} 分鐘",
        "臺北的日出從 {} 到 {}".format(*(f"{int(m // 60)}:{int(m % 60):02d}" for m in d["sunrise_range"])),
        f"東京有 {_pct(d['latitude'][PLACES['東京'][1]])}、倫敦有 {_pct(d['latitude'][PLACES['倫敦'][1]])}",
        f"南半球的雪梨有 {_pct(d['latitude'][PLACES['雪梨'][1]])}",
        f"夏天比鐘面慢 {_hm(-offsets['馬德里'][-1][2])[1:]}",
        f"本站在 {local:%H:%M:%S} 算出的上升點是{SIGNS[int(asc // 30)]} {asc % 30:.2f} 度",
        f"NOAA 公式在同一刻給出的太陽視黃經是{SIGNS[int(sun // 30)]} {sun % 30:.2f} 度，相差 {gap:.2f} 度",
        f"上升星座與臺北不同的有{'、'.join(differing)}",
    ]
    blocks = {"fx-defs": _fx.defs(SIGN_KEYS), "table-share": _share_figure(d), "rising-time": _rising_figure(d),
              "fixed-latitude": _latitude_figure(d), "clock-offsets": _offset_rows(d), "same-clock": _example_rows(d)}
    return blocks, quoted
