"""〈香港出生時間怎麼換算〉: figure 1 (Hong Kong's clock from 1900 to 1985 beside
the Observatory's summer-time years, each period pointable), figure 2 (a
slider over 1941–1979: one year's clock as the tz database keeps it and as the
Observatory's table lists it, the days they differ marked), table 1 (the two
year by year) and table 2 (two synthetic clock readings, as the
time-conversion service answers them, with the Ascendant either way).

Three sources, each read where the product reads it:
- the clock from the service's own source table, `civil_time_sources.json`
  (periods, regimes, source rows), held here to the host's zoneinfo: a host
  whose tz database tells Hong Kong's history otherwise fails the check;
- the Observatory's table from `hko_summer_time_2026.json`, a transcription of
  the page as retrieved (dates only, as the page prints them);
- the example readings from the time-conversion service, called in process,
  and the Ascendant from Swiss Ephemeris at the catalogue's Hong Kong point.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re

from . import _fx, era_time, taiwan_time
from ._common import ROOT, SIGNS, backend_on_path, product_client, swiss, zh


FRAGMENT = "blog-hong-kong-birth-time"
SOURCES = ROOT / "backend" / "app" / "civil_time_sources.json"
HKO = Path(__file__).with_name("hko_summer_time_2026.json")
ZONE = "Asia/Hong_Kong"
AXIS = (1900, 1985)
YEARS = (1941, 1979)
DEFAULT_YEAR = 1945
# The two readings table 2 sends to the service: a summer of the 1960s, and a
# day the Observatory's table and the tz database disagree on.
EXAMPLES = ((1965, 7, 15, 15, 0), (1945, 12, 1, 10, 0))
FILLS = {"standard_time": "fx-cell", "summer_time": "fx-fill-hatch", "japan_standard_time": "fx-fill-cross",
         "wartime_time": "fx-fill-dot", "local_mean_time": "fx-fill-dot"}


# --- the sources ---------------------------------------------------------------

def _seconds(label: str) -> int:
    sign = -1 if label[0] == "-" else 1
    parts = [int(p) for p in label[1:].split(":")] + [0, 0]
    return sign * (parts[0] * 3600 + parts[1] * 60 + parts[2])


def source_periods() -> list[dict]:
    """The service's Hong Kong rows, in order."""
    table = json.loads(SOURCES.read_text(encoding="utf-8"))
    rows = [p for p in table["periods"] if p["zone"] == ZONE]
    if not rows or rows[0]["from_utc"] is not None or rows[0]["regime"] != "local_mean_time":
        raise RuntimeError(f"the source table no longer opens {ZONE} with local mean time")
    return rows


def check_host_agrees(rows: list[dict]) -> None:
    """The source table's changes are the host zoneinfo's changes, to the second."""
    observed = [(r["utc"], r["to"]) for r in taiwan_time.derive_transitions(ZONE, AXIS[0], 2000)]
    listed = [(r["from_utc"], _seconds(r["utc_offset"])) for r in rows[1:]]
    if observed != listed:
        raise RuntimeError(f"the host's zoneinfo disagrees with civil_time_sources.json on {ZONE}: "
                           f"{len(observed)} changes observed, {len(listed)} listed")


def clock_periods(rows: list[dict]) -> list[dict]:
    """Hong Kong's clock as periods of local clock time (start inclusive, end
    exclusive, each boundary read on the clock that was running before it)."""
    periods = [{"start": datetime(1800, 1, 1), "offset": _seconds(rows[0]["utc_offset"]),
                "regime": rows[0]["regime"]}]
    for row in rows[1:]:
        utc = datetime.strptime(row["from_utc"], "%Y-%m-%dT%H:%M:%SZ")
        at = utc + timedelta(seconds=periods[-1]["offset"])
        periods[-1]["end"] = at
        periods.append({"start": at, "offset": _seconds(row["utc_offset"]), "regime": row["regime"]})
    periods[-1]["end"] = datetime(2100, 1, 1)
    return periods


def load_hko() -> dict:
    pin = json.loads(HKO.read_text(encoding="utf-8"))
    if not pin.get("rows"):
        raise RuntimeError(f"{HKO.name} holds no rows")
    return pin


def hko_summer_days(pin: dict) -> set[date]:
    """The days the table lists as summer time, read at noon: a period's first
    day is in, its last day is out (the clock went back that morning, as the
    tz database has it for every year from 1947); 全年 is the whole year."""
    days: set[date] = set()
    for row in pin["rows"]:
        if row.get("period") == "none":
            continue
        if row.get("period") == "whole_year":
            first, end = date(int(row["year"]), 1, 1), date(int(row["year"]) + 1, 1, 1)
        else:
            first, end = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
        while first < end:
            days.add(first)
            first += timedelta(days=1)
    return days


def offset_at_noon(periods: list[dict], day: date) -> dict:
    noon = datetime(day.year, day.month, day.day, 12)
    for p in periods:
        if p["start"] <= noon < p["end"]:
            return p
    raise RuntimeError(f"no period holds {day}")


def differences(periods: list[dict], summer: set[date], standard: int) -> list[dict]:
    """Runs of days, 1941–1979, on which the clock at noon differs from the table's."""
    out: list[dict] = []
    day = date(YEARS[0], 1, 1)
    while day <= date(YEARS[1], 12, 31):
        tz = offset_at_noon(periods, day)["offset"]
        table = standard + 3600 if day in summer else standard
        if tz != table:
            last = out[-1] if out else None
            if last and last["last"] + timedelta(days=1) == day and (last["tz"], last["table"]) == (tz, table):
                last["last"] = day
            else:
                out.append({"first": day, "last": day, "tz": tz, "table": table})
        day += timedelta(days=1)
    return out


# --- words ---------------------------------------------------------------------

def md(t: date | datetime, b) -> str:
    return f"{b(t.month)} 月 {b(t.day)} 日"


def ymd(t: date | datetime, b) -> str:
    return f"{b(t.year)} 年 {b(t.month)} 月 {b(t.day)} 日"


def at(t: datetime, b) -> str:
    """「4 月 18 日 03:30」: a change's clock reading."""
    return md(t, b) + ("" if (t.hour, t.minute) == (0, 0) else f" {b(f'{t:%H:%M}')} ")


def utc_text(seconds: int, b) -> str:
    return era_time.utc_text(seconds, b)


def year_spans(year: int, periods: list[dict]) -> list[tuple[datetime, datetime, dict]]:
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    return [(max(start, p["start"]), min(end, p["end"]), p) for p in periods
            if max(start, p["start"]) < min(end, p["end"])]


def clock_sentence(year: int, periods: list[dict], names: dict, b) -> str:
    spans = year_spans(year, periods)
    what = lambda p: f"{names[p['regime']]}，{utc_text(p['offset'], b)}"  # noqa: E731
    if len(spans) == 1:
        return f"整年是{what(spans[0][2])}"
    parts = []
    for i, (s, e, p) in enumerate(spans):
        if i == 0:
            parts.append(f"{at(e, b)}以前是{what(p)}")
        elif i == len(spans) - 1:
            parts.append(f"{at(s, b)}起是{what(p)}")
        else:
            parts.append(f"{at(s, b)}至 {at(e, b)}是{what(p)}")
    return "；".join(parts)


def hko_rows_of(year: int, pin: dict) -> list[dict]:
    return [r for r in pin["rows"] if str(year) in r["year"].replace("73/74", "73/1974").split("/")
            or r["year"] == str(year)]


def hko_text(row: dict, b) -> str:
    if row.get("period") == "whole_year":
        return "全年"
    if row.get("period") == "none":
        return "無"
    s, e = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
    if s.year != e.year:
        return f"{ymd(s, b)}至 {ymd(e, b)}"
    return f"{md(s, b)}至 {md(e, b)}"


def hko_sentence(year: int, pin: dict, b) -> str:
    rows = hko_rows_of(year, pin)
    if not rows:
        raise RuntimeError(f"the Observatory's table has no row for {year}")
    texts = []
    for row in rows:
        text = hko_text(row, b)
        texts.append("全年實施夏令時間" if text == "全年" else "沒有實施夏令時間" if text == "無"
                     else f"{text}實施夏令時間")
    return "；".join(texts)


def diff_sentence(year: int, diffs: list[dict], b) -> str:
    mine = [d for d in diffs if d["first"].year == year]
    if not mine:
        return "兩者逐日相同。"
    parts = []
    for d in mine:
        span = md(d["first"], b) if d["first"] == d["last"] else f"{md(d['first'], b)}至 {md(d['last'], b)}"
        parts.append(f"{span}（資料庫 {utc_text(d['tz'], b)}，表 {utc_text(d['table'], b)}）")
    return "兩者不同的日子：" + "；".join(parts) + "。"


def year_sentence(year: int, periods: list[dict], pin: dict, diffs: list[dict], names: dict, b) -> str:
    return (f"{b(year)} 年。時區資料庫（本站計算採用）：{clock_sentence(year, periods, names, b)}。"
            f"天文台的表：{hko_sentence(year, pin, b)}。{diff_sentence(year, diffs, b)}")


# --- figure 1: 1900–1985 -------------------------------------------------------

def _frac(t: date | datetime) -> float:
    return era_time._frac(t)


def _eras(periods: list[dict], names: dict, b) -> list[dict]:
    """The five periods figure 1 lets a reader point at."""
    a0, a1 = datetime(AXIS[0], 1, 1), datetime(AXIS[1], 1, 1)
    clock = [p for p in periods if p["end"] > a0 and p["start"] < a1]
    regimes = [p["regime"] for p in clock]
    expected = ["local_mean_time", "standard_time", "summer_time", "wartime_time", "japan_standard_time",
                "standard_time"]
    if regimes[:6] != expected or set(regimes[6:]) != {"summer_time", "standard_time"}:
        raise RuntimeError(f"figure 1 expects LMT, UTC+8, the 1941 changes, the occupation and then summers; "
                           f"the table gives {regimes[:7]}")
    lmt, hkt, s41, w41, jst, post = clock[:6]
    summers = [p for p in clock[6:] if p["regime"] == "summer_time"]
    years = [p["start"].year for p in summers]
    post_end = a1
    jst_end = b(f"{jst['end']:%H:%M}")
    jump = hkt["offset"] - lmt["offset"]
    u = lambda p: utc_text(p["offset"], b)  # noqa: E731
    gaps = [y for y in range(years[0], years[-1] + 1) if y not in years and y not in
            {p["end"].year for p in summers}]
    eras = [
        {"key": "lmt", "start": a0, "end": lmt["end"], "parts": [(a0, lmt["end"], lmt)],
         "name": names["local_mean_time"], "label": "",
         "sentence": (f"{ymd(lmt['end'], b)}以前：沒有官定的標準時。時區資料庫用香港的地方平時代表這一段，"
                      f"比世界時快 {b(lmt['offset'] // 3600)} 小時 {b(lmt['offset'] % 3600 // 60)} 分"
                      f" {b(lmt['offset'] % 60)} 秒，這只是依經度推算的代表值。"),
         "spoken": f"地方平時，{b(lmt['end'].year)} 年以前"},
        {"key": "hkt", "start": hkt["start"], "end": hkt["end"], "parts": [(hkt["start"], hkt["end"], hkt)],
         "name": "香港時間", "label": f"{u(hkt)}　香港時間",
         "sentence": (f"{ymd(hkt['start'], b)}起：依當年的憲報公告，香港改用東經 {b(hkt['offset'] // 240)} 度的時間，"
                      f"也就是 {u(hkt)}，鐘面撥快 {b(jump // 60)} 分 {b(jump % 60)} 秒。這個制度一直用到 "
                      f"{b(s41['start'].year)} 年夏天。"),
         "spoken": f"香港時間 {u(hkt)}，{ymd(hkt['start'], b)}起"},
        {"key": "y1941", "start": s41["start"], "end": jst["start"],
         "parts": [(s41["start"], s41["end"], s41), (w41["start"], w41["end"], w41)],
         "name": f"{b(s41['start'].year)} 年", "label": f"{b(s41['start'].year)} 年",
         "sentence": (f"{b(s41['start'].year)} 年：{at(s41['start'], b)}起第一次實施夏令時間（{u(s41)}），"
                      f"{at(w41['start'], b)}起改為{names['wartime_time']}（{u(w41)}，憲報稱冬令時間），"
                      f"直到日軍佔領。"),
         "spoken": f"{b(s41['start'].year)} 年的夏令時間與冬令時間"},
        {"key": "jst", "start": jst["start"], "end": jst["end"], "parts": [(jst["start"], jst["end"], jst)],
         "name": "日佔時期", "label": f"日佔 {u(jst)}",
         "sentence": (f"{b(jst['start'].year)} 年 {at(jst['start'], b)}起到 {ymd(jst['end'], b)} {jst_end}："
                      f"日佔時期用東京時間 {u(jst)}（{names['japan_standard_time']}）。天文台的表把 "
                      f"{b(jst['start'].year + 1)}–{b(jst['end'].year)} 年寫成全年夏令時間，鐘面同樣快 "
                      f"{b(jst['offset'] // 3600)} 小時；兩者在 {b(jst['end'].year)} 年底分歧。"),
         "spoken": f"日佔時期，{u(jst)}"},
        {"key": "post", "start": post["start"], "end": post_end,
         "parts": [(max(a0, p["start"]), min(a1, p["end"]), p) for p in clock[5:]],
         "name": "戰後", "label": f"{u(post)}　戰後的香港時間",
         "sentence": (f"{ymd(post['start'], b)}起：改回 {u(post)}。{b(years[0])}–{b(years[-1])} 年間共 "
                      f"{b(len(summers))} 段夏令時間，鐘面是 {utc_text(post['offset'] + 3600, b)}"
                      + (f"（{'、'.join(b(y) for y in gaps)} 年沒有實施）" if gaps else "")
                      + f"；{b(years[-1] + 1)} 年起不再實施。逐年起訖見圖 2 與表 1。"),
         "spoken": f"戰後的香港時間 {u(post)}，夏季另有夏令時間"},
    ]
    return eras


def _hero(layout: str, fid: str, eras: list[dict], summer: set[date], bound: _fx.Bound) -> str:
    b = lambda v: bound.num(str(v))  # noqa: E731
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        a0, a1 = 150.0, 846.0
        tz_row, hko_row = (92.0, 84.0), (196.0, 28.0)
        axis, H = 244.0, 318.0
    else:
        a0, a1 = 84.0, 84.0 + (AXIS[1] - AXIS[0]) * 5.6
        tz_row, hko_row = (70.0, 120.0), (202.0, 34.0)
        axis, H = 60.0, a1 + 54
    T = lambda t: a0 + (_frac(t) - AXIS[0]) / (AXIS[1] - AXIS[0]) * (a1 - a0)  # noqa: E731

    def box(row: tuple[float, float], s, e) -> tuple[float, float, float, float]:
        top, size = row
        t0, t1 = T(s), T(e)
        return (t0, top, t1 - t0, size) if wide else (top, t0, size, t1 - t0)

    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        out.append(_fx.text(24, tz_row[0] + tz_row[1] / 2 - 4, "時區資料庫", "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, tz_row[0] + tz_row[1] / 2 + 16, "（本站採用）", "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, hko_row[0] + hko_row[1] / 2 + 5, "天文台的表", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(tz_row[0] + tz_row[1] / 2, axis - 22, "時區資料庫", "fx-t fx-small fx-dim", "middle"))
        out.append(_fx.text(hko_row[0] + hko_row[1] / 2, axis - 22, "天文台", "fx-t fx-small fx-dim", "middle"))
    for year in range(AXIS[0], AXIS[1] + 1, 10):
        tick = bound.scale(str(year))
        x = T(date(year, 1, 1))
        if wide:
            out.append(_fx.line(x, axis, x, axis + 6, "fx-axis"))
            out.append(_fx.text(x, axis + 26, tick, "fx-t fx-small fx-num", "middle"))
        else:
            out.append(_fx.line(axis - 6, x, axis, x, "fx-axis"))
            out.append(_fx.text(axis - 10, x + 4, tick, "fx-t fx-small fx-num", "end"))
    out.append(_fx.line(*((a0, axis, a1, axis) if wide else (axis, a0, axis, a1)), "fx-axis"))
    # The Observatory's summer-time days, as solid runs.
    runs: list[list[date]] = []
    for day in sorted(summer):
        if runs and runs[-1][1] + timedelta(days=1) == day:
            runs[-1][1] = day
        else:
            runs.append([day, day])
    for first, last in runs:
        x, y, w, h = box(hko_row, first, last + timedelta(days=1))
        out.append(_fx.rect(x, y, max(w, 1.6) if wide else w, h if wide else max(h, 1.6), "fx-fill-solid"))
    out.append(_fx.rect(*box(hko_row, date(AXIS[0], 1, 1), date(AXIS[1], 1, 1)), "fx-dash"))
    for era in eras:
        x, y, w, h = box(tz_row, era["start"], era["end"])
        # The post-war era (and 1941) is one area; its summers ride on it as solid bars.
        body = _fx.rect(x, y, w, h, "fx-cell") if era["key"] in ("post", "y1941") else ""
        for s, e, p in era["parts"]:
            if p["regime"] == "summer_time":
                bx, by, bw, bh = box(tz_row, s, e)
                if wide:
                    body += _fx.rect(bx, by, max(bw, 1.6), 16, "fx-fill-solid")
                else:
                    body += _fx.rect(bx + bw - 16, by, 16, max(bh, 1.6), "fx-fill-solid")
            elif era["key"] != "post":
                body += _fx.rect(*box(tz_row, s, e), FILLS[p["regime"]])
        body += _label(era, (x, y, w, h), wide)
        hit = (x, y - (40 if wide and era["key"] in ("y1941", "jst") else 0), w, h + (40 if wide and era["key"] in ("y1941", "jst") else 0)) \
            if wide else (x, y, W - 12 - x, h)
        out.append(f'<g class="fx-row" data-fx-key="{era["key"]}" tabindex="0" aria-label="{era["spoken"]}">'
                   + _fx.rect(*hit, "fx-hit") + body + "</g>")
    lmt = eras[0]["parts"][0][2]["offset"]
    note = f"{b(AXIS[0])} 年起的點：地方平時（快 {b(lmt // 3600)} 小時 {b(lmt % 3600 // 60)} 分）"
    out.append(_fx.text(a0 if wide else 18, H - 20, note, "fx-t fx-small", "start"))
    out.append("</svg>")
    return "".join(out)


def _label(era: dict, rect: tuple[float, float, float, float], wide: bool) -> str:
    x, y, w, h = rect
    key = era["key"]
    if not era["label"]:
        return ""
    if wide:
        if key in ("y1941", "jst"):
            dy = 34 if key == "y1941" else 12
            anchor = "end" if key == "y1941" else "start"
            cx = x + w / 2
            return (_fx.line(cx, y - dy + 4, cx, y, "fx-leader")
                    + _fx.text(cx + (-4 if anchor == "end" else 4), y - dy, era["label"], "fx-t fx-small fx-key", anchor))
        return _fx.text(x + 14, y + h / 2 + 14, era["label"], "fx-t")
    if key in ("y1941", "jst"):
        cy = y + h / 2 + (-6 if key == "y1941" else 10)
        return _fx.text(258, cy + 4, era["label"], "fx-t fx-small fx-key", "start")
    lines = era["label"].split("　")
    return "".join(_fx.text(x + w / 2 - 8, y + min(h / 2, 90) + 20 * i, line, "fx-t fx-small", "middle")
                   for i, line in enumerate(lines))


def _hero_table(eras: list[dict]) -> str:
    rows = "".join(f'<tr data-fx-key="{e["key"]}"><th scope="row">{e["name"]}</th><td>{e["sentence"]}</td></tr>'
                   for e in eras)
    return _fx.data_table(("時期", "說明"), rows)


# --- figure 2: one year at a time ----------------------------------------------

def _year_layout(layout: str, fid: str, years: list[int], periods: list[dict], summer: set[date],
                 diffs: list[dict], standard: int, bound: _fx.Bound) -> str:
    b = lambda v: bound.num(str(v))  # noqa: E731
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        x0, x1 = 170.0, 846.0
        tz_row, hko_row, rh = 96.0, 166.0, 40.0
        ticks, H = 228.0, 284.0
    else:
        x0, x1 = 20.0, 320.0
        tz_row, hko_row, rh = 98.0, 176.0, 36.0
        ticks, H = 236.0, 300.0
    X = lambda d, year: x0 + (_frac(d) - year) * (x1 - x0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        out.append(_fx.text(24, tz_row + rh / 2 - 2, "時區資料庫", "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, tz_row + rh / 2 + 16, "（本站採用）", "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, hko_row + rh / 2 + 6, "天文台的表", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(x0, tz_row - 8, "時區資料庫（本站採用）", "fx-t fx-small fx-dim"))
        out.append(_fx.text(x0, hko_row - 8, "天文台的表", "fx-t fx-small fx-dim"))
    for month in range(1, 14):
        x = x0 + (month - 1) / 12 * (x1 - x0)
        # Month lines through each row only, so the rows' own labels stay clear.
        out.append(_fx.line(x, tz_row, x, tz_row + rh, "fx-hair"))
        out.append(_fx.line(x, hko_row, x, ticks, "fx-hair"))
        if month <= 12:
            label = f"{bound.scale(str(month))} 月" if wide else bound.scale(str(month))
            out.append(_fx.text(x + (x1 - x0) / 24, ticks + 20, label, "fx-t fx-small fx-num", "middle"))
    out.append(_fx.line(x0, ticks, x1, ticks, "fx-axis"))
    default = years.index(DEFAULT_YEAR)
    for i, year in enumerate(years):
        body = []
        mine = [d for d in diffs if d["first"].year == year]
        days = sum((d["last"] - d["first"]).days + 1 for d in mine)
        verdict = "兩者逐日相同" if not mine else f"{b(days)} 天不同（朱紅框）"
        if wide:
            body.append(_fx.text(24, 52, f"{b(year)} 年", "fx-t fx-num"))
            body.append(_fx.text(x0, 52, verdict, "fx-t" + (" fx-cursor-t" if mine else "")))
        else:
            body.append(_fx.text(x0, 36, f"{b(year)} 年", "fx-t fx-num"))
            body.append(_fx.text(x0, 60, verdict, "fx-t fx-small" + (" fx-cursor-t" if mine else "")))
        for s, e, p in year_spans(year, periods):
            a, z = X(s, year), X(e, year)
            body.append(_fx.rect(a, tz_row, z - a, rh, FILLS[p["regime"]]))
            if z - a >= (64 if wide else 52):
                body.append(_fx.text(a + 6, tz_row + rh / 2 + 5, utc_text(p["offset"], b),
                                     "fx-t fx-small fx-num" + (" fx-key" if p["regime"] != "standard_time" else "")))
        # The table's row for the year: summer days hatched, the rest standard time.
        day, end = date(year, 1, 1), date(year + 1, 1, 1)
        while day < end:
            inside = day in summer
            run_end = day
            while run_end + timedelta(days=1) < end and ((run_end + timedelta(days=1)) in summer) == inside:
                run_end += timedelta(days=1)
            a, z = X(day, year), X(run_end + timedelta(days=1), year)
            body.append(_fx.rect(a, hko_row, z - a, rh, "fx-fill-hatch" if inside else "fx-cell"))
            if z - a >= (64 if wide else 52):
                body.append(_fx.text(a + 6, hko_row + rh / 2 + 5, utc_text(standard + (3600 if inside else 0), b),
                                     "fx-t fx-small fx-num" + (" fx-key" if inside else "")))
            day = run_end + timedelta(days=1)
        for d in mine:
            a, z = X(d["first"], year), X(d["last"] + timedelta(days=1), year)
            body.append(_fx.rect(a - 1, tz_row - 4, max(z - a, 2) + 2, hko_row + rh - tz_row + 8, "fx-cursor"))
        out.append(_fx.step_group(i, default, "".join(body)))
    out.append("</svg>")
    return "".join(out)


# --- tables --------------------------------------------------------------------

def _summer_rows(years: list[int], periods: list[dict], pin: dict, diffs: list[dict], names: dict) -> str:
    """Table 1: per year, the table's row and the tz database's summer time."""
    b = str
    rows = []
    for year in years:
        rows_of = hko_rows_of(year, pin)
        table = "；".join(hko_text(r, b) for r in rows_of)
        spans = [(s, e, p) for s, e, p in year_spans(year, periods) if p["regime"] != "standard_time"]
        if not spans:
            tz = "無"
        else:
            tz = "；".join(
                (names[p["regime"]] + " " if p["regime"] != "summer_time" else "")
                + ("全年" if (s, e) == (datetime(year, 1, 1), datetime(year + 1, 1, 1)) else
                   f"{at(s, b) if s != datetime(year, 1, 1) else '1 月 1 日'}至 "
                   f"{(at(e, b) if e != datetime(year + 1, 1, 1) else '12 月 31 日').rstrip()}")
                for s, e, p in spans)
        mine = [d for d in diffs if d["first"].year == year]
        verdict = "一致" if not mine else "不同"
        cls = "" if not mine else ' class="diff"'
        rows.append(f'          <tr><td class="n">{year}</td><td>{table}</td><td>{tz}</td><td{cls}>{verdict}</td></tr>')
    return "\n".join(rows)


def _deg_min(lon: float) -> str:
    total = round(lon * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]} {rest // 60}°{rest % 60:02d}′"


def catalogue_point() -> tuple[float, float, str, int]:
    """The place the calculator's catalogue answers first for 「Hong Kong」, and
    how many catalogue places keep Hong Kong's clock."""
    with backend_on_path():
        from app.core.place_catalog import PlaceCatalog

        catalog = PlaceCatalog()
        found = catalog.search(query="Hong Kong", country_code="HK", limit=1)["results"]
        connection = catalog._connect()
        try:
            count = connection.execute("SELECT count(*) FROM places WHERE timezone = ?", (ZONE,)).fetchone()[0]
        finally:
            connection.close()
    if not found or found[0]["timezone"] != ZONE:
        raise RuntimeError("the place catalogue no longer answers 「Hong Kong」 with a Hong Kong place")
    return found[0]["latitude"], found[0]["longitude"], found[0]["display_name"], count


def convert(examples: tuple) -> list[dict]:
    with product_client() as post:
        return [post("/api/time/convert", {
            "datetime": {"year": y, "month": m, "day": d, "hour": h, "minute": mi, "second": 0},
            "timezone": {"mode": "iana", "iana_name": ZONE},
        }) for y, m, d, h, mi in examples]


# --- the page ------------------------------------------------------------------

def build() -> tuple[dict[str, str], list[str]]:
    rows = source_periods()
    check_host_agrees(rows)
    periods = clock_periods(rows)
    pin = load_hko()
    summer = hko_summer_days(pin)
    names = era_time.regime_names()
    standard = next(p["offset"] for p in periods if p["regime"] == "standard_time")
    diffs = differences(periods, summer, standard)
    years = list(range(YEARS[0], YEARS[1] + 1))
    summers = [p for p in periods if p["regime"] == "summer_time"]
    agree_from = max(d["first"].year for d in diffs) + 1

    b1 = _fx.Bound()
    n1 = lambda v: b1.num(str(v))  # noqa: E731
    eras = _eras(periods, names, n1)
    hero = _fx.figure(
        fid="fig-hk-clock",
        hero=True,
        title=f"香港的鐘面比世界時快多少，{AXIS[0]} 到 {AXIS[1]} 年",
        caption=(f"<b>{b1.label('圖 1')}</b>上方是時區資料庫記的香港鐘面（本站計算用這一條）：點是地方平時，空白是 "
                 f"{utc_text(standard, n1)} 的香港時間，交叉線是日佔時期的東京時間，實心細條是夏令時間。下方是天文台"
                 "〈香港夏令時間〉表列的夏令時間（實心）。兩條在這個比例下幾乎重合；它們不同的幾段日子，見圖 2。"
                 f"依 IANA 時區資料庫<a class=\"ar-cite\" href=\"#ref-1\">{b1.label('[1]')}</a>與天文台的表"
                 f"<a class=\"ar-cite\" href=\"#ref-2\">{b1.label('[2]')}</a>。"),
        art=_fx.FigureArt.drawn(
            _hero, "fig-hk-clock", eras, summer, b1,
            notes=[_fx.Note(e["key"], None, e["sentence"]) for e in eras],
            idle="用 Tab 鍵移到一段時期上，或用滑鼠指著它，這裡會寫出那段時期的制度與起訖。",
        ),
        table=_hero_table(eras),
        bound=b1,
    )

    b2 = _fx.Bound()
    n2 = lambda v: b2.num(str(v))  # noqa: E731
    notes = [_fx.Note(None, None, year_sentence(y, periods, pin, diffs, names, n2), step=i) for i, y in enumerate(years)]
    lookup = _fx.figure(
        fid="fig-hk-year",
        title=f"選一個年份，看那一年香港的鐘面：時區資料庫與天文台的表，{YEARS[0]} 到 {YEARS[1]} 年",
        caption=(f"<b>{b2.label('圖 2')}</b>拖拉選一個年份（{n2(YEARS[0])} 到 {n2(YEARS[1])} 年）。上面一條是時區資料庫記的"
                 "鐘面，本站計算用的就是它：單線是夏令時間，交叉線是東京時間，點是 1941 年的冬令時間；下面一條是天文台的表，"
                 "單線是表列的夏令時間。朱紅框是兩者在中午的鐘面不同的日子。滑桿下方的文字逐年寫出兩邊的日期。"),
        art=_fx.FigureArt.drawn(
            _year_layout, "fig-hk-year", years, periods, summer, diffs, standard, b2,
            notes=notes,
            idle="拖拉選一個年份，這裡會寫出那一年兩邊的日期。",
        ),
        controls=_fx.FigureControls(steps=len(years), default_step=years.index(DEFAULT_YEAR), scrub_label="年份"),
        bound=b2,
    )

    lat, lon, place, places = catalogue_point()
    answers = convert(EXAMPLES)
    readings = [a["readings"][0] for a in answers]
    with swiss() as swe:
        def asc(iso: str, shift_hours: float = 0.0) -> float:
            t = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=shift_hours)
            j = swe.julday(t.year, t.month, t.day, t.hour + t.minute / 60)
            return swe.houses_ex(j, lat, lon, b"W")[1][0]

        # 1965: kept as summer time (the service) or read as standard time (one hour later);
        # 1945: as the service keeps it (UTC+8) or as the table reads it (UTC+9, one hour earlier).
        a65, a65_wrong = asc(readings[0]["utc_iso_8601"]), asc(readings[0]["utc_iso_8601"], 1)
        a45, a45_table = asc(readings[1]["utc_iso_8601"]), asc(readings[1]["utc_iso_8601"], -1)
    utc = lambda iso, shift=0: (datetime.strptime(iso[:16], "%Y-%m-%dT%H:%M") + timedelta(hours=shift)).strftime("%H:%M")  # noqa: E731
    example_rows = "\n".join([
        f'          <tr class="hl"><td>1965-07-15 15:00，依當時的夏令時間（{readings[0]["utc_offset_label"]}，本站）</td>'
        f'<td class="n">{utc(readings[0]["utc_iso_8601"])}</td><td>{_deg_min(a65)}</td></tr>',
        f'          <tr><td>同一個鐘面，忽略夏令時間（UTC+08:00）</td><td class="n">{utc(readings[0]["utc_iso_8601"], 1)}</td>'
        f'<td class="diff">{_deg_min(a65_wrong)}</td></tr>',
        f'          <tr class="hl"><td>1945-12-01 10:00，依時區資料庫（{readings[1]["utc_offset_label"]}，本站）</td>'
        f'<td class="n">{utc(readings[1]["utc_iso_8601"])}</td><td>{_deg_min(a45)}</td></tr>',
        f'          <tr><td>同一個鐘面，依天文台表的「全年夏令時間」（UTC+09:00）</td>'
        f'<td class="n">{utc(readings[1]["utc_iso_8601"], -1)}</td><td class="diff">{_deg_min(a45_table)}</td></tr>',
    ])
    late = [d for d in diffs if d["first"].year == 1945]
    if len(late) != 1:
        raise RuntimeError("the article names one 1945 disagreement")
    total_days = sum((d["last"] - d["first"]).days + 1 for d in diffs)
    quoted = [
        f"<b>{len(summers)}</b><span>段夏令時間",
        f"<b>{len(diffs)}</b><span>段日子",
        f"<b>{total_days}</b><span>天",
        f"{agree_from}–{YEARS[1]} 年",
        f"{ymd(late[0]['first'], str)}至 {ymd(late[0]['last'], str)}",
        f"上升點差了 {(a65_wrong - a65) % 360:.0f} 度",
        f"上升點差 {(a45 - a45_table) % 360:.0f} 度",
        place,
        f"{lat:.4f}, {lon:.4f}",
        f"收了香港 {places} 個地名",
    ]
    return {"fx-defs": _fx.defs(()), "hk-clock": hero, "hk-year": lookup, "hk-summers": _summer_rows(years, periods, pin, diffs, names),
            "hk-examples": example_rows}, quoted


def elsewhere(fragment: str) -> dict[str, list[str]]:
    """The blog index repeats the number of summers."""
    found = re.search(r"<b>(\d+)</b><span>段夏令時間", fragment)
    if found is None:
        raise RuntimeError(f"{FRAGMENT}: the stat block no longer prints the number of summers")
    return {"blog": [f"{zh(int(found.group(1)))}段夏令時間"]}
