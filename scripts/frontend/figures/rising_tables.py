"""〈上升星座查詢表為什麼常常不準〉: figure 1 (how often two model lookup
tables give a different rising sign than the exact computation), figure 2 (a
table made for 25°N used at other latitudes), table 1 (clock time against
local mean time, abroad and in Taiwan), table 2 (the product's Ascendant for
one clock time at four Taiwanese places) and the numbers the prose quotes.

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

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import _noaa
from ._common import SIGNS, backend_on_path, calc_ut, indent, product_charts, swiss


FRAGMENT = "blog-rising-sign-tables"
YEAR = 2025
STEP_MINUTES = 10
# name: (GeoNames id, latitude, longitude, IANA zone)
PLACES = {
    "臺北": ("1668341", 25.05306, 121.52639, "Asia/Taipei"),
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
# Table 2: one synthetic clock time, the same at four places.
EXAMPLE = datetime(YEAR, 3, 21, 6, 0)
SUNRISE_DAY = date(YEAR, 3, 21)


def _check_catalogue() -> None:
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)
        for name, (record, lat, lon, zone) in PLACES.items():
            response = client.post("/api/places/search", json={"query": SEARCH[name], "limit": 10})
            rows = [row for row in response.json()["results"] if row.get("source_record_id") == record]
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
        split = {}
        for start in range(0, 1440, STEP_MINUTES):
            split[start] = sum((sun + (minute - start) // 120) % 12 != asc for minute, sun, asc, _ in rows) / n
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
        # Sidereal-time sweeps: one sidereal day in 0.25° of ARMC, the year's mean obliquity.
        eps = sum(swe.calc_ut(swe.julday(YEAR, month, 1, 0.0), swe.ECL_NUT)[0][0] for month in range(1, 13)) / 12

        def armc_signs(lat: float, shift: float = 0.0) -> list[int]:
            return [int(swe.houses_armc((k * 0.25 + shift) % 360, lat, eps, b"W")[1][0] // 30) for k in range(1440)]

        base = armc_signs(TABLE_LATITUDE)
        lats = sorted(set(range(-40, 61, 5)) | {PLACES[name][1] for name in FIG2_MARKS})
        d["latitude"] = {lat: sum(a != b for a, b in zip(base, armc_signs(lat))) / 1440 for lat in lats}
        # Rising time of each sign at Taipei, from the same sweep (minutes of a sidereal day).
        def asc_at(armc: float) -> float:
            return swe.houses_armc(armc % 360, tp[1], eps, b"W")[1][0]

        crossings = []
        for k in range(12):  # the ARMC at which each sign begins to rise, by bisection
            lo = next(step * 0.25 for step in range(1440)
                      if int(asc_at(step * 0.25) // 30) == (k - 1) % 12
                      and int(asc_at(step * 0.25 + 0.25) // 30) == k)
            hi = lo + 0.25
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
                share = sum(a != b for a, b in zip(local, armc_signs(lat, shift))) / 1440
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


def _bars(d: dict) -> list[tuple[str, float]]:
    start, share = d["table_a"]
    out = [(f"太陽星座＋兩小時時段表，用在臺北（最有利的切法）", share)]
    for name in ELSEWHERE_IN_TAIWAN:
        out.append((f"臺北精算表，用在{name}", d["table_b"][name]))
    out.append((f"臺北精算表，{DST_YEAR} 年臺北的夏令時間期間", d["dst"][0]))
    return out


def _hero(d: dict) -> str:
    W, step, top = 640, 66, 34
    bars = _bars(d)
    H = top + step * len(bars) + 30
    span = 470
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="查表與精算給出不同上升星座的時刻佔比：'
         + "；".join(f"{label} {_pct(share)}" for label, share in bars) + '。">']
    for i, (label, share) in enumerate(bars):
        y = top + i * step
        cls = "f-accent" if i in (0, len(bars) - 1) else "f-ring2"
        s.append(f'<text class="t-dim" x="10" y="{y}">{label}</text>')
        s.append(f'<rect class="f-hair" x="10" y="{y + 12}" width="{span}" height="22"/>')
        s.append(f'<rect class="{cls}" x="10" y="{y + 12}" width="{max(span * share, 2):.1f}" height="22"/>')
        s.append(f'<text class="t-mono" x="{10 + span + 14}" y="{y + 30}">{_pct(share)}</text>')
    s.append(f'<text class="t-faint" x="10" y="{H - 6}">{YEAR} 年（夏令時間一列為 {DST_YEAR} 年）每 {STEP_MINUTES} 分鐘的鐘面時刻</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def _curve(d: dict) -> str:
    W, H = 640, 360
    L, R, T, B = 70, 610, 30, 290
    X = lambda lat: L + (R - L) * (lat + 40) / 100  # noqa: E731
    Y = lambda share: B - (B - T) * share / 0.7  # noqa: E731
    grid = [lat for lat in d["latitude"] if lat in range(-40, 61, 5)]
    path = "M" + " L".join(f"{X(lat):.1f},{Y(d['latitude'][lat]):.1f}" for lat in grid)
    marks = "、".join(f"{name}（{PLACES[name][1]:.1f}°）{_pct(d['latitude'][PLACES[name][1]])}" for name in FIG2_MARKS)
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="一張為北緯 25 度精算的上升星座表，用在其他緯度時，'
         f'一個恆星日裡查錯的時刻佔比：{marks}。緯度離 25 度越遠，錯得越多。">']
    for share in (0, 0.2, 0.4, 0.6):
        s.append(f'<line class="g-hair" x1="{L}" y1="{Y(share):.1f}" x2="{R}" y2="{Y(share):.1f}"/>')
        s.append(f'<text class="t-faint t-end" x="{L - 10}" y="{Y(share) + 6:.1f}">{share * 100:.0f}%</text>')
    for lat in (-40, -20, 0, 20, 40, 60):
        s.append(f'<text class="t-faint t-mid" x="{X(lat):.1f}" y="{B + 28}">{"南" if lat < 0 else "北" if lat > 0 else ""}{abs(lat)}°</text>')
    s.append(f'<line class="g-ink" x1="{L}" y1="{B}" x2="{R}" y2="{B}"/>')
    s.append(f'<path class="g-ink" d="{path}"/>')
    for name in FIG2_MARKS:
        mark = PLACES[name][1]
        x, y = X(mark), Y(d["latitude"][mark])
        s.append(f'<circle class="f-paper" cx="{x:.1f}" cy="{y:.1f}" r="7"/>')
        s.append(f'<circle class="g-accent-thin" cx="{x:.1f}" cy="{y:.1f}" r="7"/>')
        s.append(f'<text class="t-accent t-mid" x="{x:.1f}" y="{y - 16:.1f}">{name}</text>')
    s.append(f'<text class="t-faint" x="{L}" y="{H - 8}">橫軸：出生地緯度　縱軸：上升星座與表不同的時刻佔比</text>')
    s.append("</svg>")
    return indent("\n".join(s))


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
        f"{start // 60:02d}:{start % 60:02d} 到 {(start + 120) // 60:02d}:{(start + 120) % 60:02d}",
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
    blocks = {"table-share": _hero(d), "fixed-latitude": _curve(d), "clock-offsets": _offset_rows(d),
              "same-clock": _example_rows(d)}
    return blocks, quoted
