"""〈澳門出生時間怎麼換算〉: figures 1-3 (Macau's clock 1904-1979; the days its noon clock differs from Hong Kong's; what a
wrong place or a wrong hour does to the Ascendant) and the year table.

The clock comes from the service's source table, held to the host's zoneinfo; the places from the shipped catalogue,
matched by name so that a renamed row fails here; the Ascendant from Swiss Ephemeris.  All instants are synthetic.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from typing import Any
from zoneinfo import ZoneInfo

from . import _fx, taiwan_time
from ._common import ROOT, backend_on_path, swiss

FRAGMENT = "blog-macau-birth-time"
SOURCES = ROOT / "backend" / "app" / "civil_time_sources.json"
MO, HK = "Asia/Macau", "Asia/Hong_Kong"
HK_POINT = (22.2783, 114.1747)
AXIS = (1900, 1985)
ZOOM = (1941, 1947)
DISPUTE = (datetime(1942, 10, 17, 23), datetime(1942, 11, 17, 23))

def sec(label: str) -> int:
    parts = [int(p) for p in label[1:].split(":")] + [0, 0]
    return (-1 if label[0] == "-" else 1) * (parts[0] * 3600 + parts[1] * 60 + parts[2])


def periods(zone: str) -> list[dict]:
    rows = [p for p in json.loads(SOURCES.read_text(encoding="utf-8"))["periods"] if p["zone"] == zone]
    observed = [(r["utc"], r["to"]) for r in taiwan_time.derive_transitions(zone, 1900, 2000)]
    if observed != [(r["from_utc"], sec(r["utc_offset"])) for r in rows[1:]]:
        raise RuntimeError(f"zoneinfo disagrees with the source table on {zone}")
    out = [{"start": datetime(1800, 1, 1), "offset": sec(rows[0]["utc_offset"]), "regime": rows[0]["regime"]}]
    for row in rows[1:]:
        at = datetime.strptime(row["from_utc"], "%Y-%m-%dT%H:%M:%SZ") + timedelta(seconds=out[-1]["offset"])
        out[-1]["end"] = at
        out.append({"start": at, "offset": sec(row["utc_offset"]), "regime": row["regime"]})
    out[-1]["end"] = datetime(2100, 1, 1)
    return out


def frac(t) -> float:
    start = datetime(t.year, 1, 1)
    t = datetime(t.year, t.month, t.day, getattr(t, "hour", 0), getattr(t, "minute", 0))
    return t.year + (t - start) / (datetime(t.year + 1, 1, 1) - start)


def noon_runs() -> list[dict]:
    mo, hk = ZoneInfo(MO), ZoneInfo(HK)
    runs: list[dict[str, Any]] = []
    day = date(1941, 1, 1)
    while day <= date(1979, 12, 31):
        noon = datetime(day.year, day.month, day.day, 12)
        a, h = noon.replace(tzinfo=mo).utcoffset(), noon.replace(tzinfo=hk).utcoffset()
        if a != h:
            if runs and runs[-1]["last"] + timedelta(days=1) == day and (runs[-1]["mo"], runs[-1]["hk"]) == (a, h):
                runs[-1]["last"] = day
            else:
                runs.append({"first": day, "last": day, "mo": a, "hk": h})
        day += timedelta(days=1)
    return runs


def ascendant_numbers() -> dict:
    with backend_on_path():
        from app.core.place_catalog import PlaceCatalog
        cat = PlaceCatalog()
        base = cat.search(query="Macau", country_code="MO", limit=1)["results"][0]
        conn = cat._connect()
        cols = [d[0] for d in conn.execute("select * from places limit 1").description]
        rows = [dict(zip(cols, r)) for r in conn.execute("select * from places where timezone=?", (MO,)).fetchall()]
    points = {}
    for key, name in (("Fátima", "花地瑪堂區"), ("Taipa", "氹仔"), ("Cotai", "路氹"), ("Coloane", "路環"), ("Jiu", "九澳")):
        hit = [r for r in rows if key in r["display_name"]]
        if len(hit) != 1:
            raise RuntimeError(f"catalogue rows for {key}: {[r['display_name'] for r in hit]}")
        points[name] = (hit[0]["latitude"], hit[0]["longitude"])
    if len(rows) != 12:
        raise RuntimeError(f"expected 12 Macau rows, got {len(rows)}")
    lat, lon = base["latitude"], base["longitude"]
    grid = [datetime(1970, 1, 1) + timedelta(days=5 * i, hours=h) for i in range(73) for h in range(24)]
    diff = lambda x, y: abs((x - y + 180) % 360 - 180)  # noqa: E731
    with swiss() as swe:
        def asc(t, la=lat, lo=lon):
            return swe.houses_ex(swe.julday(t.year, t.month, t.day, t.hour + t.minute / 60), la, lo, b"W")[1][0]
        base_asc = [asc(t) for t in grid]
        rowsout = []
        for name, (la, lo) in {**points, "香港（對照）": HK_POINT}.items():
            ds = [diff(asc(t, la, lo), b) * 60 for t, b in zip(grid, base_asc)]
            rowsout.append({"name": name, "mean": sum(ds) / len(ds), "max": max(ds), "unit": "arcmin"})
        one = [diff(asc(t + timedelta(hours=1)), b) for t, b in zip(grid, base_asc)]
        example = (asc(datetime(1970, 7, 15, 6)), asc(datetime(1970, 7, 15, 7)))
        # 1970 夏令段（04-19 03:30 至 10-18 03:30 鐘面）內，同一鐘面用 +9 與 +8 算，上升星座不同的比例；每天每小時
        z, same, total = ZoneInfo(MO), 0, 0
        day = datetime(1970, 4, 20)
        while day < datetime(1970, 10, 18):
            for h in range(24):
                ut9 = day + timedelta(hours=h - 9)
                if int(asc(ut9) // 30) == int(asc(ut9 + timedelta(hours=1)) // 30):
                    same += 1
                total += 1
            day += timedelta(days=1)
    return {"rows": rowsout, "one_mean": sum(one) / len(one), "one_max": max(one), "n": len(grid),
            "example": example, "example_diff": diff(*example), "sign_changed": (total - same) / total,
            "sign_total": total, "base": (lat, lon)}


# --- 圖 1 ----------------------------------------------------------------------

def draw_clock(layout: str, fid: str, ps: list[dict], b: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W, H = (880, 452) if wide else (340, 452)
    x0, x1 = (92, 856) if wide else (70, 326)
    X = lambda v: x0 + (v - AXIS[0]) / (AXIS[1] - AXIS[0]) * (x1 - x0)  # noqa: E731
    top, per = 62, 56
    Y = lambda off: top + (10 - off / 3600) * per  # noqa: E731
    base = Y(8 * 3600)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for h in (8, 9, 10):
        out.append(_fx.line(x0, Y(h * 3600), x1, Y(h * 3600), "fx-hair"))
        out.append(_fx.text(x0 - 8, Y(h * 3600) + 5, "UTC+" + b.num(str(h)), "fx-t fx-small fx-num fx-dim", "end"))
    for p in ps:
        s, e = max(frac(p["start"]) if p["start"].year > 1800 else AXIS[0], AXIS[0]), min(frac(p["end"]) if p["end"].year < 2100 else AXIS[1], AXIS[1])
        if s >= e:
            continue
        if p["regime"] == "local_mean_time":
            out.append(_fx.rect(X(s), base, X(e) - X(s), Y(p["offset"]) - base, "fx-fill-dot"))
        elif p["offset"] > 8 * 3600:
            cls = "fx-fill-cross" if p["start"].year < 1946 else "fx-fill-solid"
            out.append(_fx.rect(X(s), Y(p["offset"]), max(X(e) - X(s), 1.2), base - Y(p["offset"]), cls))
    axis = Y(7.5 * 3600) + 4
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    for tick in (1904, 1946, 1979) if not wide else (1904, 1920, 1941, 1946, 1960, 1979):
        out.append(_fx.line(X(tick), axis, X(tick), axis + 5, "fx-axis"))
        out.append(_fx.text(X(tick), axis + 22, b.scale(str(tick)), "fx-t fx-small fx-num", "middle"))
    war_x = X(1943.5)
    out.append(_fx.text(war_x, top - 10, "戰時最快 UTC+" + b.num("10") if wide else "戰時 UTC+" + b.num("10"), "fx-t fx-small fx-key", "middle"))
    if wide:
        out.append(_fx.text(X(1905), Y(8.5 * 3600) + 5, f"{b.num('1904')} 年起 UTC+{b.num('8')}", "fx-t fx-small fx-key"))
        out.append(_fx.text(X(1948), Y(9 * 3600) - 12, f"{b.num('1946')}–{b.num('1979')} 年：{b.num('32')} 段夏令時間，鐘面 UTC+{b.num('9')}", "fx-t fx-small fx-key"))
        out.append(_fx.text(x1, Y(7.72 * 3600) + 5, f"{b.num('1977')}、{b.num('1978')} 年沒有；{b.num('1980')} 年起不再實施", "fx-t fx-small fx-key", "end"))
    else:
        out.append(_fx.text(X(1905), Y(8.5 * 3600) + 5, f"{b.num('1904')} 起 UTC+{b.num('8')}", "fx-t fx-small fx-key"))
        out.append(_fx.text(x1, Y(9 * 3600) - 12, f"夏令 {b.num('32')} 段", "fx-t fx-small fx-key", "end"))
    # 放大 1941–1946
    zx0, zx1 = x0, x1
    ZX = lambda v: zx0 + (v - ZOOM[0]) / (ZOOM[1] - ZOOM[0]) * (zx1 - zx0)  # noqa: E731
    ztop, zper = 296, 44
    ZY = lambda off: ztop + (10 - off / 3600) * zper  # noqa: E731
    zbase = ZY(8 * 3600)
    out.append(_fx.text(24, ztop - 40, f"放大：{b.num('1941')}–{b.num('1946')} 年", "fx-t fx-small"))
    for h in (8, 9, 10):
        out.append(_fx.line(zx0, ZY(h * 3600), zx1, ZY(h * 3600), "fx-hair"))
        out.append(_fx.text(zx0 - 8, ZY(h * 3600) + 5, "UTC+" + b.num(str(h)), "fx-t fx-small fx-num fx-dim", "end"))
    for p in ps:
        if p["regime"] == "local_mean_time" or p["offset"] <= 8 * 3600:
            continue
        s, e = max(frac(p["start"]), ZOOM[0]), min(frac(p["end"]), ZOOM[1])
        if s < e:
            cls = "fx-fill-cross" if p["start"].year < 1946 else "fx-fill-solid"
            out.append(_fx.rect(ZX(s), ZY(p["offset"]), ZX(e) - ZX(s), zbase - ZY(p["offset"]), cls))
    out.append(_fx.line(zx0, zbase, zx1, zbase, "fx-axis"))
    for y in range(ZOOM[0], ZOOM[1] + 1):
        out.append(_fx.line(ZX(y), zbase, ZX(y), zbase + 5, "fx-axis"))
        if y < ZOOM[1]:
            out.append(_fx.text((ZX(y) + ZX(y + 1)) / 2, zbase + 22, b.scale(str(y)), "fx-t fx-small fx-num", "middle"))
    a, z = ZX(frac(DISPUTE[0])), ZX(frac(DISPUTE[1]))
    out.append(_fx.rect(a - 1, ZY(10 * 3600) - 3, z - a + 2, zbase - ZY(10 * 3600) + 3, "fx-cursor"))
    days = b.num(str((DISPUTE[1] - DISPUTE[0]).days))
    out.append(_fx.text((a + z) / 2 - (0 if wide else 0), ZY(10 * 3600) - 11, f"這 {days} 天尚未定論", "fx-t fx-small fx-cursor-t", "middle"))
    out.append("</svg>")
    return "".join(out)


# --- 圖 2 ----------------------------------------------------------------------

def draw_hk(layout: str, fid: str, runs: list[dict], b: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    years = list(range(1941, 1952))
    rh, gap = (22, 8) if wide else (18, 7)
    head = 54
    bottom = head + len(years) * (rh + gap)
    W, H = (880, bottom + 112) if wide else (340, bottom + 138)
    x0, x1 = (96, 770) if wide else (56, 288)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    mw = (x1 - x0) / 12
    for m in range(1, 13):
        if wide or m in (1, 4, 7, 10):
            out.append(_fx.text(x0 + (m - .5) * mw, head - 12, f"{b.scale(str(m))} 月" if wide else b.scale(str(m)) + "月", "fx-t fx-small fx-num fx-dim", "middle"))
    for i, y in enumerate(years):
        top = head + i * (rh + gap)
        out.append(_fx.text(x0 - 10, top + rh - 5, b.num(str(y)), "fx-t fx-small fx-num", "end"))
        out.append(_fx.rect(x0, top, x1 - x0, rh, "fx-cell"))
        n = 0
        for r in runs:
            if r["first"].year != y:
                continue
            n += (r["last"] - r["first"]).days + 1
            a = x0 + (frac(r["first"]) - y) * (x1 - x0)
            w = ((r["last"] - r["first"]).days + 1) / 365 * (x1 - x0)
            delta = (r["mo"] - r["hk"]).total_seconds()
            cls = "fx-fill-dot" if abs(delta) == 1800 else "fx-fill-solid" if delta > 0 else "fx-fill-hatch"
            out.append(_fx.rect(a, top, max(w, 2.4), rh, cls))
            if abs(delta) == 1800:
                out.append(_fx.rect(a, top, max(w, 2.4), rh, "fx-frame-in"))
        out.append(_fx.text(x1 + 8, top + rh - 5, f"{b.num(str(n))} 天" if n else "相同", "fx-t fx-small fx-num" + ("" if n else " fx-dim")))
        if y == 1942:
            a, z = (x0 + (frac(DISPUTE[k]) - y) * (x1 - x0) for k in (0, 1))
            out.append(_fx.rect(a, top - 3, z - a, rh + 6, "fx-cursor"))
    ly = bottom + 8
    items = (("fx-fill-solid", "澳門快一小時"), ("fx-fill-hatch", "澳門慢一小時"), ("fx-fill-dot", "相差半小時"))
    if wide:
        for k, (cls, label) in enumerate(items):
            lx = x0 + k * 190
            out.append(_fx.rect(lx, ly + 2, 26, 15, cls) + _fx.rect(lx, ly + 2, 26, 15, "fx-frame-in"))
            out.append(_fx.text(lx + 34, ly + 15, label, "fx-t fx-small"))
        out.append(_fx.rect(x0 + 570, ly + 2, 26, 15, "fx-cursor"))
        out.append(_fx.text(x0 + 604, ly + 15, "尚未定論", "fx-t fx-small fx-cursor-t"))
        out.append(_fx.text(x0, ly + 58, f"{b.num('1952')}–{b.num('1979')} 年：逐日比對中午鐘面，沒有不同的日子。", "fx-t"))
    else:
        for k, (cls, label) in enumerate(items):
            lx, yy = (x0 - 34 + (k % 2) * 142), ly + (k // 2) * 26
            out.append(_fx.rect(lx, yy + 2, 22, 14, cls) + _fx.rect(lx, yy + 2, 22, 14, "fx-frame-in"))
            out.append(_fx.text(lx + 28, yy + 14, label, "fx-t fx-small"))
        lx = x0 - 34 + 142
        out.append(_fx.rect(lx, ly + 28, 22, 14, "fx-cursor"))
        out.append(_fx.text(lx + 28, ly + 40, "尚未定論", "fx-t fx-small fx-cursor-t"))
        out.append(_fx.text(22, ly + 84, f"{b.num('1952')}–{b.num('1979')} 年：逐日比對中午", "fx-t fx-small"))
        out.append(_fx.text(22, ly + 104, "鐘面，沒有不同的日子。", "fx-t fx-small"))
    out.append("</svg>")
    return "".join(out)


# --- 圖 3 ----------------------------------------------------------------------

def fmt_value(row: dict, b) -> str:
    if row["unit"] == "arcmin":
        return f"最大 {b.num(f'{row['max']:.1f}')}′（平均 {b.num(f'{row['mean']:.1f}')}′）"
    if row.get("mean") is None:
        return f"{b.num(f'{row['max']:.1f}')}°"
    return f"最大 {b.num(f'{row['max']:.1f}')}°（平均 {b.num(f'{row['mean']:.1f}')}°）"


def draw_compare(layout: str, fid: str, rows: list[dict], b: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    deg = lambda r: r["max"] / 60 if r["unit"] == "arcmin" else r["max"]  # noqa: E731
    if wide:
        x0, x1, rh, top = 236, 660, 34, 52
    else:
        x0, x1, rh, top = 20, 320, 50, 50
    H = top + len(rows) * rh + (84 if wide else 88)
    W = 880 if wide else 340
    X = lambda d: x0 + d / 20 * (x1 - x0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    end = top + len(rows) * rh + 8
    for t in (0, 5, 10, 15, 20):
        out.append(_fx.line(X(t), top - 4, X(t), end, "fx-hair"))
        out.append(_fx.text(X(t), end + 20, b.scale(str(t)) + "°", "fx-t fx-small fx-num", "middle"))
    out.append(_fx.line(x0, end, x1, end, "fx-axis"))
    out.append(_fx.text(x0 if not wide else x0, end + 44, "上升點的差距（度）", "fx-t fx-small fx-dim"))
    for i, r in enumerate(rows):
        y = top + i * rh
        solid = r["unit"] != "arcmin"
        if wide:
            out.append(_fx.text(x0 - 12, y + 19, r["name"], "fx-t fx-small", "end"))
            out.append(_fx.rect(x0, y + 6, max(X(deg(r)) - x0, 1.6), 18, "fx-fill-solid" if solid else "fx-fill-solid"))
            out.append(_fx.text(X(deg(r)) + 8, y + 19, fmt_value(r, b), "fx-t fx-small fx-num fx-key"))
        else:
            out.append(_fx.text(x0, y + 14, r["name"], "fx-t fx-small fx-key"))
            out.append(_fx.text(x1, y + 14, fmt_value(r, b), "fx-t fx-small fx-num fx-key", "end"))
            out.append(_fx.rect(x0, y + 21, max(X(deg(r)) - x0, 1.6), 14, "fx-fill-solid"))
    out.append("</svg>")
    return "".join(out)


# --- assembly ------------------------------------------------------------------

def table(cols, rows):
    return _fx.data_table(cols, ["<tr><th scope=\"row\">" + r[0] + "</th>" + "".join(f"<td>{c}</td>" for c in r[1:]) + "</tr>"
                                 for r in rows])

def _clock_text(t: datetime) -> str:
    return f"{t.month} 月 {t.day} 日 " + t.strftime("%H:%M")

def _switch(t: datetime) -> str:
    """A switch as the old clock read it; midnight is written as 24:00 of the day before."""
    if t.hour == 0 and t.minute == 0:
        t -= timedelta(days=1)
        return f"{t.month} 月 {t.day} 日 24:00"
    return _clock_text(t)

def year_table(ps: list[dict]) -> str:
    rows = []
    summers = [p for p in ps if p["regime"] == "summer_time" and p["start"].year >= 1946]
    for p in summers:
        s, e = p["start"], p["end"]
        if s.year != e.year:
            rows.append((f"{s.year}–{str(e.year)[2:]}", f"{s.year} 年 {_switch(s)}", f"{e.year} 年 {_switch(e)}"))
        else:
            rows.append((str(s.year), _switch(s), _switch(e)))
    out = ['<div class="ar-scroll" tabindex="0" role="region" aria-labelledby="tab-years-cap">', '<table class="ar-table">',
           '<caption id="tab-years-cap">表 1　澳門 1946–1979 年的夏令時間（切換那一刻的舊鐘面，依時區資料庫）。1977、1978 年沒有。</caption>',
           "<thead><tr><th>年</th><th>撥快（鐘面）</th><th>撥回（鐘面）</th></tr></thead>", "<tbody>"]
    out += [f'<tr><th scope="row">{a}</th><td>{b}</td><td>{c}</td></tr>' for a, b, c in rows]
    out += ["</tbody>", "</table>", "</div>"]
    return "\n".join("    " + line for line in out)

def place_table(a: dict) -> str:
    out = ['<div class="ar-scroll" tabindex="0" role="region" aria-labelledby="tab-places-cap">', '<table class="ar-table">',
           f'<caption id="tab-places-cap">表 3　相對目錄的澳門代表點，上升點差多少（{a["n"]:,} 個合成時刻）</caption>',
           '<thead><tr><th>地點</th><th class="n">平均</th><th class="n">最大</th></tr></thead>', "<tbody>"]
    for r in a["rows"]:
        out.append(f'<tr><th scope="row">{r["name"]}</th><td class="n">{r["mean"]:.1f}′</td><td class="n">{r["max"]:.1f}′</td></tr>')
    out.append(f'<tr><th scope="row">同一地點，鐘面差一小時（對照）</th><td class="n">{a["one_mean"]:.1f}°</td><td class="n">{a["one_max"]:.1f}°</td></tr>')
    out += ["</tbody>", "</table>", "</div>"]
    return "\n".join("    " + line for line in out)

def build() -> tuple[dict[str, str], list[str]]:
    ps, runs = periods(MO), noon_runs()
    a = ascendant_numbers()
    figs = {}

    # 圖 1
    b = _fx.Bound(); n = lambda v: b.num(str(v))  # noqa: E731
    summers = [p for p in ps if p["regime"] == "summer_time" and p["start"].year >= 1946]
    if len(summers) != 32:
        raise RuntimeError(len(summers))
    title = "澳門的鐘面比世界時快多少，1904 到 1979 年，下方放大 1941 到 1946 年"
    cap = (f"<b>{b.label('圖 1')}</b>澳門鐘面相對世界時的偏移。交叉線是 {n(1941)}–{n(1945)} 年戰時撥快的時段（UTC+{n(9)}，"
           f"{n(1942)}、{n(1943)} 年夏天 UTC+{n(10)}），實心細條是 {n(1946)}–{n(1979)} 年的 {n(32)} 段夏令時間（UTC+{n(9)}），"
           f"{n(1904)} 年以前的點是地方平時。朱紅框是 {n(1942)} 年那 {n(31)} 天：圖依時區資料庫畫，公報條文的自然讀法則是這段已撥回，見 §04。"
           "依本站出處表與時區資料庫。")
    alt = (f"上圖：1904 年起澳門為 UTC+8；1941 年 12 月 21 日撥快到 UTC+9，1942 年 4 月 30 日到 UTC+10，資料庫記 1942 年 11 月 17 日回 UTC+9；"
           "1943 年 4 月 30 日到 9 月 30 日再為 UTC+10，其後 UTC+9；1945 年 9 月 30 日回 UTC+8。1946 到 1979 年共 32 段夏令時間為 UTC+9，1977、1978 年沒有。"
           "下圖放大 1941 到 1946 年，並框出 1942 年 10 月 17 日到 11 月 17 日尚未定論的 31 天。")
    rows = []
    for p in ps:
        if p["start"].year < 1946 and p["start"].year > 1800:
            off = p["offset"]
            rows.append((p["start"].strftime("%Y-%m-%d %H:%M"), f"UTC+{off/3600:g}"))
    rows.append(("1946–1979", "夏天 UTC+9（共 32 段，逐段見 §02）"))
    for r in rows:
        for tok in _fx._NUMBER.findall(" ".join(r)):
            b.num(tok)
    figs["mo-clock"] = (_fx.figure(
        fid="fig-mo-clock", title=title, caption=cap,
        art=_fx.FigureArt.drawn(draw_clock, "fig-mo-clock", ps, b),
        table=table(["切換（舊鐘面）", "新鐘面"], rows), hero=True, bound=b))

    # 圖 2
    b = _fx.Bound(); n = lambda v: b.num(str(v))  # noqa: E731
    total = sum((r["last"] - r["first"]).days + 1 for r in runs)
    if {r["first"].year for r in runs} - set(range(1941, 1952)):
        raise RuntimeError("difference outside 1941–1951")
    title = "澳門與香港中午鐘面不同的日子，1941 到 1951 年"
    cap = (f"<b>{b.label('圖 2')}</b>逐日比對 {n(1941)} 到 {n(1979)} 年的中午鐘面，共 {n(f'{total:,}')} 天不同，全部落在 {n(1941)}–{n(1951)} 年。"
           f"右欄是當年不同的天數。朱紅框是 {n(1942)} 年尚未定論的 {n(31)} 天，圖依時區資料庫；若公報的 10 月讀法才對，這幾天兩地鐘面其實相同。"
           "切換當下的鐘點沒有比對。香港依時區資料庫，不含天文台表與資料庫不同之處。")
    alt = "十一列年份，每列一條一到十二月的色帶，標出兩地不同的日子。" + "；".join(
        f"{r['first']} 至 {r['last']} 澳門 UTC+{r['mo'].total_seconds()/3600:g}、香港 UTC+{r['hk'].total_seconds()/3600:g}" for r in runs) + "。1952 到 1979 年沒有不同。"
    run_rows = [(f"{r['first']}" + ("" if r["first"] == r["last"] else f" 至 {r['last']}"),
                 f"UTC+{r['mo'].total_seconds()/3600:g}", f"UTC+{r['hk'].total_seconds()/3600:g}",
                 str((r["last"] - r["first"]).days + 1)) for r in runs]
    for row in run_rows:
        for tok in _fx._NUMBER.findall(" ".join(row)):
            b.num(tok)
    figs["mo-hk"] = (_fx.figure(
        fid="fig-mo-hk", title=title, caption=cap,
        art=_fx.FigureArt.drawn(draw_hk, "fig-mo-hk", runs, b),
        table=table(["期間", "澳門", "香港", "天數"], run_rows), bound=b))

    # 圖 3
    b = _fx.Bound(); n = lambda v: b.num(str(v))  # noqa: E731
    bars = a["rows"] + [
        {"name": "漏算夏令（本文例子）", "max": a["example_diff"], "mean": None, "unit": "deg"},
        {"name": "同地鐘面差一小時", "max": a["one_max"], "mean": a["one_mean"], "unit": "deg"}]
    jiu = next(r for r in a["rows"] if r["name"] == "九澳")
    title = "選錯地點與鐘面差一小時，對上升點的影響（同一比例尺）"
    cap = (f"<b>{b.label('圖 3')}</b>相對目錄的澳門代表點，上升點差多少；{n(1970)} 年全年每 {n(5)} 天每小時共 {n(f'{a['n']:,}')} 個合成時刻。"
           f"澳門境內最遠的九澳最多差 {n(f'{jiu['max']:.1f}')}′，在這個比例尺下幾乎看不見；同一地點鐘面差一小時，平均差 {n(f'{a['one_mean']:.1f}')}°。"
           f"「本文例子」是 {n(1970)} 年 {n(7)} 月 {n(15)} 日 {n(15)}:{n('00')} 這一個時刻。其他年份未測。")
    alt = "橫條圖，比例尺 0 到 20 度。" + "；".join(f"{r['name']} {fmt_value(r, b)}" for r in bars) + "。"
    bar_rows = [(r["name"], fmt_value(r, b)) for r in bars]
    figs["mo-asc"] = (_fx.figure(
        fid="fig-mo-asc", title=title, caption=cap,
        art=_fx.FigureArt.drawn(draw_compare, "fig-mo-asc", bars, b),
        table=table(["比較", "上升點差距"], bar_rows), bound=b))

    d0, d1 = date(1946, 1, 1), date(1979, 12, 31)
    zone, days = ZoneInfo(MO), (d1 - d0).days + 1
    noon = sum(datetime.combine(d0 + timedelta(days=i), datetime.min.time()).replace(hour=12, tzinfo=zone).utcoffset()
               == timedelta(hours=9) for i in range(days))
    jiu = next(r for r in a["rows"] if r["name"] == "九澳")
    quoted = [f"{days:,} 天裡，有 {noon:,} 天（{noon / days:.0%}）", f"約一半的時刻（{a['sign_changed']:.0%}）",
              f"共 {total:,} 天不同", f"差 {a['example_diff']:.1f}°", f"{a['n']:,} 個合成時刻"]
    return {"fx-defs": _fx.defs(()), "mo-clock": figs["mo-clock"],
            "mo-hk": figs["mo-hk"], "mo-asc": figs["mo-asc"], "mo-years": year_table(ps),
            "mo-places": place_table(a)}, quoted
