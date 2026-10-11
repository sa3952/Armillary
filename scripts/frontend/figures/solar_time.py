"""〈西洋占星要不要換真太陽時？〉: figure 1 (the product's time pipeline,
and the same clock time first turned into true solar time), figure 2 (how far
that double count moves the chart through 2025, Taipei and Jincheng) and the
numbers the prose quotes.

Figure 1 and the example are the product's own answers for the synthetic
instant 1990-11-03 14:00 Taipei (GeoNames 1668341): the product reports the
true solar time it computes for reference, and a second request enters that
true solar time as if it were the clock reading.  Figure 2 and the yearly
share use Swiss Ephemeris (swe.time_equ, the function the product reports
the equation of time from, and houses_ex) every 10 minutes of 2025.  The one
value checked against a second algorithm: the product's equation of time
against NOAA's spreadsheet formula at the same instant.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import _noaa
from ._common import SIGNS, indent, product_charts, swiss


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


def _hero(e: dict) -> str:
    W, H = 640, 520
    lon_minutes = (TAIPEI[1] - ZONE_MERIDIAN) * 4
    gained = ((e["wrong"]["last"] - e["right"]["last"]) % 24) * 60
    colx = (10, 330)
    bw = 300
    lanes = [
        ("本站的做法", [
            ("出生紀錄的鐘面時間", f"{EXAMPLE:%H:%M}（臺北）"),
            ("依時區 UTC+8 換成世界時", e["right"]["utc"]),
            ("加上經度 121.53°，得地方恆星時", _hm(e["right"]["last"])),
            ("上升點", _asc(e["right"]["asc"])),
        ]),
        ("先換真太陽時", [
            ("出生紀錄的鐘面時間", f"{EXAMPLE:%H:%M}（臺北）"),
            (f"經度 {_signed(lon_minutes)} 分、均時差 {_signed(e['eot'])} 分", f"真太陽時 {e['solar']:%H:%M}"),
            ("把它當成鐘面時間，換成世界時", e["wrong"]["utc"]),
            ("再加一次經度，得地方恆星時", _hm(e["wrong"]["last"])),
            ("上升點", _asc(e["wrong"]["asc"])),
        ]),
    ]
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="同一個鐘面時刻，兩種算法。合成範例：1990 年 11 月 3 日'
         f"下午兩點，臺北。本站：世界時 {e['right']['utc']}，地方恆星時 {_hm(e['right']['last'])}，上升點 {_asc(e['right']['asc'])}。"
         f"先換成真太陽時 {e['solar']:%H:%M} 再當成鐘面時間輸入：世界時 {e['wrong']['utc']}，地方恆星時 {_hm(e['wrong']['last'])}，"
         f'多了約 {gained:.1f} 分鐘，上升點 {_asc(e["wrong"]["asc"])}。">']
    for (title, boxes), x in zip(lanes, colx):
        accent = title != "本站的做法"
        s.append(f'<text class="{"t-accent" if accent else "t"}" x="{x}" y="30">{title}</text>')
        y = 50
        for i, (label, value) in enumerate(boxes):
            last = i == len(boxes) - 1
            hot = accent and i in (1, 3)
            s.append(f'<rect class="{"f-accent-soft" if hot else "f-paper2"}" x="{x}" y="{y}" width="{bw}" height="72"/>')
            s.append(f'<text class="t-dim" x="{x + 14}" y="{y + 28}">{label}</text>')
            s.append(f'<text class="{"t-accent" if (accent and (last or hot)) else "t-mono"}" x="{x + 14}" y="{y + 58}">{value}</text>')
            if not last:
                s.append(f'<line class="g-dim" x1="{x + bw / 2}" y1="{y + 72}" x2="{x + bw / 2}" y2="{y + 90}"/>')
            y += 90
    s.append(f'<text class="t-faint" x="10" y="{H - 8}">右欄的經度算了兩次：地方恆星時多了約 {gained:.1f} 分鐘</text>')
    s.append("</svg>")
    return indent("\n".join(s))


def _curve(year: dict) -> str:
    W, H = 640, 340
    L, R, T, B = 70, 610, 30, 270
    days = year["days"]
    X = lambda day: L + (R - L) * day / 364  # noqa: E731
    Y = lambda minutes: T + (B - T) * (30 - minutes) / 60  # noqa: E731
    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{YEAR} 年每天中午，先換真太陽時再當成鐘面時間輸入，'
         "地方恆星時多出或少掉的分鐘數：臺北為經度修正加均時差，"
         f"在 {_signed((TAIPEI[1] - ZONE_MERIDIAN) * 4 + min(days))} 到 {_signed((TAIPEI[1] - ZONE_MERIDIAN) * 4 + max(days))} 分鐘之間；"
         f"金門在 {_signed((JINCHENG[1] - ZONE_MERIDIAN) * 4 + min(days))} 到 {_signed((JINCHENG[1] - ZONE_MERIDIAN) * 4 + max(days))} 分鐘之間。\">"]
    for minutes in (-20, -10, 0, 10, 20, 30):
        cls = "g-ink" if minutes == 0 else "g-hair"
        s.append(f'<line class="{cls}" x1="{L}" y1="{Y(minutes):.1f}" x2="{R}" y2="{Y(minutes):.1f}"/>')
        s.append(f'<text class="t-faint t-end" x="{L - 10}" y="{Y(minutes) + 6:.1f}">{f"{minutes:+d}" if minutes else "0"}</text>')
    for month, label in ((0, "1 月"), (90, "4 月"), (181, "7 月"), (273, "10 月")):
        s.append(f'<text class="t-faint t-mid" x="{X(month) + 20:.1f}" y="{B + 28}">{label}</text>')
    for (name, (_, lon)), cls in zip((("臺北", TAIPEI), ("金門", JINCHENG)), ("g-accent", "g-ring2")):
        offset = (lon - ZONE_MERIDIAN) * 4
        path = "M" + " L".join(f"{X(day):.1f},{Y(offset + eot):.1f}" for day, eot in enumerate(days) if day % 2 == 0)
        s.append(f'<path class="{cls}" d="{path}"/>')
        peak = max(range(len(days)), key=lambda day: days[day])
        s.append(f'<text class="{"t-accent" if name == "臺北" else "t-dim"} t-end" x="{X(peak) - 14:.1f}" '
                 f'y="{Y(offset + days[peak]) - 8:.1f}">{name}</text>')
    s.append(f'<text class="t-faint" x="{L}" y="{H - 8}">縱軸：地方恆星時多出的分鐘數（經度修正＋均時差）</text>')
    s.append("</svg>")
    return indent("\n".join(s))


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
    return {"two-pipelines": _hero(e), "year-shift": _curve(year)}, quoted
