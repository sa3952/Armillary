"""〈民國年、昭和年怎麼換算西元〉: figure 1 (the Japanese eras, the Republic's
years and Taiwan's clock from 1895 to 1950, each era pointable), figure 2 (a
slider over the years the calculator accepts up to 1950: what each calendar
calls that year and which offsets Taiwan's clock kept within it, month by
month), and table 1 (four record readings, as the calculator's era helper and
the time-conversion service answer them).

Three sources, each read where the product reads it:
- the eras (offset, first and last day) from the era helper itself,
  `ERAS` in request-input.js, so the figure cannot disagree with the helper;
- the clock from the pinned tz transitions of the time-zone article
  (`taiwan_time.load_pin`, checked against the host's zoneinfo there), with
  each period's regime and its name as the service's receipt gives them
  (backend civil_time_sources.json, labels.js);
- table 1 from the time-conversion service itself, called in process.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import re
from typing import Any

from . import _fx, taiwan_time
from ._common import ROOT, product_client


FRAGMENT = "blog-taiwan-era-years-birth-time"
REQUEST_INPUT = ROOT / "scripts" / "frontend" / "scripts" / "request-input.js"
LABELS = ROOT / "scripts" / "frontend" / "scripts" / "labels.js"
CALCULATE = ROOT / "scripts" / "frontend" / "pages" / "calculate.html"
SOURCES = ROOT / "backend" / "app" / "civil_time_sources.json"
ZONE = "Asia/Taipei"
AXIS = (1895, 1951)          # figure 1: from 1895 up to the start of 1951
LAST_YEAR = 1950             # figure 2's last year
DEFAULT_YEAR = 1937
JAPANESE = ("meiji", "taisho", "showa")

# The four readings table 1 sends to the service: (era, era year, month, day, hour, minute).
EXAMPLES = (
    ("showa", 12, 6, 1, 10, 0),
    ("showa", 13, 6, 1, 10, 0),
    ("showa", 12, 10, 1, 0, 30),
    ("showa", 20, 9, 21, 0, 30),
)

_ERA = re.compile(
    r'(?P<key>\w+): Object\.freeze\(\{ label: "(?P<label>[^"]+)", offset: (?P<offset>\d+), '
    r'first: (?P<first>\[[\d, ]+\]|null), last: (?P<last>\[[\d, ]+\]|null),'
)


# --- the sources ---------------------------------------------------------------

def read_eras() -> dict[str, dict[str, Any]]:
    """The era helper's table, as request-input.js ships it."""
    source = REQUEST_INPUT.read_text(encoding="utf-8")
    block = source[source.index("const ERAS = Object.freeze({"):]
    block = block[: block.index("});") + 3]
    found: dict[str, dict[str, Any]] = {}
    for match in _ERA.finditer(block):
        day = lambda text: None if text == "null" else date(*json.loads(text))  # noqa: E731
        found[match["key"]] = {"label": match["label"], "offset": int(match["offset"]),
                               "first": day(match["first"]), "last": day(match["last"])}
    if set(found) != {"roc", *JAPANESE}:
        raise RuntimeError(f"read eras {sorted(found)} from {REQUEST_INPUT.name}, expected roc and three Japanese eras")
    for key, era in found.items():
        if era["first"] is not None and era["first"].year != era["offset"] + 1:
            raise RuntimeError(f"{key}: its first day is not in year 1 of its own count")
    for before, after in (("meiji", "taisho"), ("taisho", "showa")):
        if found[before]["last"] + timedelta(days=1) != found[after]["first"]:
            raise RuntimeError(f"{before} does not end the day before {after} begins")
    return found


def calculator_first_year() -> int:
    match = re.search(r'id="birth-date"[^>]* data-min="(\d{4})-01-01"', CALCULATE.read_text(encoding="utf-8"))
    if match is None:
        raise RuntimeError("the calculate page's birth-date field names no first year")
    return int(match[1])


def regime_names() -> dict[str, str]:
    """labels.js civil_time_regime: what the receipt calls each regime."""
    source = LABELS.read_text(encoding="utf-8")
    block = source[source.index("civil_time_regime: Object.freeze({"):]
    block = block[: block.index("})")]
    names = dict(re.findall(r'(\w+): "([^"]+)"', block))
    if not {"local_mean_time", "standard_time", "japan_standard_time", "summer_time"} <= set(names):
        raise RuntimeError("labels.js no longer names the four Taiwan regimes")
    return names


def clock_periods(pin: dict) -> list[dict]:
    """Taiwan's clock as periods of local clock time: start, end (exclusive),
    offset and regime.  The regime comes from the service's source table,
    matched on the transition instant; the table must hold every pinned one."""
    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    regimes = {p["from_utc"]: p["regime"] for p in sources["periods"] if p["zone"] == ZONE}
    tr = pin["transitions"]
    periods = [{"start": datetime(1800, 1, 1), "offset": tr[0]["from"], "regime": "local_mean_time"}]
    for record in tr:
        if record["utc"] not in regimes:
            raise RuntimeError(f"the source table has no {ZONE} period from {record['utc']}")
        periods[-1]["end"] = taiwan_time._local_before(record)
        periods.append({"start": taiwan_time._local_before(record), "offset": record["to"],
                        "regime": regimes[record["utc"]]})
    periods[-1]["end"] = datetime(2100, 1, 1)
    return periods


def convert(examples: tuple, eras: dict) -> list[dict]:
    """Each example sent to the time-conversion service in process."""
    with product_client() as post:
        out = []
        for key, n, month, day, hour, minute in examples:
            year = n + eras[key]["offset"]
            body = post("/api/time/convert", {
                "datetime": {"year": year, "month": month, "day": day, "hour": hour, "minute": minute, "second": 0},
                "timezone": {"mode": "iana", "iana_name": ZONE},
            })
            out.append({"era": key, "n": n, "year": year, "month": month, "day": day, "hour": hour,
                        "minute": minute, "body": body})
        return out


# --- words ---------------------------------------------------------------------

def era_year(label: str, n: int, b) -> str:
    return f"{label}元年" if n == 1 else f"{label} {b(n)} 年"


def roc_year(year: int, eras: dict, b) -> str:
    n = year - eras["roc"]["offset"]
    return era_year("民國", n, b) if n >= 1 else f"民國前 {b(1 - n)} 年"


def japanese_years(year: int, eras: dict) -> list[tuple[str, int, date, date]]:
    """(era key, era year, first day, last day) of each Japanese era within `year`."""
    out = []
    for key in JAPANESE:
        era = eras[key]
        first = max(date(year, 1, 1), era["first"] or date(1, 1, 1))
        last = min(date(year, 12, 31), era["last"] or date(9999, 12, 31))
        if first <= last:
            out.append((key, year - era["offset"], first, last))
    return out


def utc_text(seconds: int, b) -> str:
    hours, rest = divmod(seconds, 3600)
    return f"UTC+{b(hours)}" if not rest else f"UTC+{b(hours)}:{b(f'{rest // 60:02d}')}"


def md(t: date | datetime, b) -> str:
    return f"{b(t.month)} 月 {b(t.day)} 日"


def year_clock(year: int, periods: list[dict]) -> list[tuple[date, date, dict]]:
    """(first day, last day, period) of each clock period within `year`, by clock dates."""
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    out = []
    for p in periods:
        s, e = max(start, p["start"]), min(end, p["end"])
        if s < e:
            out.append((s.date(), (e - timedelta(microseconds=1)).date(), p))
    return out


def clock_sentence(year: int, periods: list[dict], names: dict, b) -> str:
    """The clock within one year, with the hour of a change that is not at midnight
    (1945: 「9 月 21 日凌晨 1 點撥回 0 點之後」)."""
    start, end = datetime(year, 1, 1), datetime(year + 1, 1, 1)
    spans = [(max(start, p["start"]), min(end, p["end"]), p) for p in periods if max(start, p["start"]) < min(end, p["end"])]
    what = lambda p: f"{names[p['regime']]}，{utc_text(p['offset'], b)}"  # noqa: E731
    if len(spans) == 1:
        return f"整年都是{what(spans[0][2])}"
    parts = []
    for i, (s, e, p) in enumerate(spans):
        if s.time() == datetime.min.time():
            lead = md(s, b)
        else:
            after = s + timedelta(seconds=p["offset"] - spans[i - 1][2]["offset"])
            lead = f"{md(s, b)}凌晨 {b(s.hour)} 點撥{'回' if after < s else '到'} {b(after.hour)} 點之後"
        if i == len(spans) - 1:
            when = lead if "之後" in lead else f"{lead}起"
        elif e.time() == datetime.min.time():
            when = f"{lead}至 {md(e - timedelta(days=1), b)}"
        else:
            when = f"{lead}至 {md(e, b)}凌晨 {b(e.hour)} 點"
        parts.append(f"{when}是{what(p)}")
    return "；".join(parts)


def year_sentence(year: int, eras: dict, periods: list[dict], names: dict, b) -> str:
    japan = japanese_years(year, eras)
    jp = "，".join(
        era_year(eras[key]["label"], n, b) + (f"（{md(first, b)}起）" if first.month != 1 or first.day != 1 else
                                               f"（至 {md(last, b)}）" if last.month != 12 or last.day != 31 else "")
        for key, n, first, last in japan)
    roc = roc_year(year, eras, b)
    note = "；換算助手不收民國前的年份，請直接填西元" if year < eras["roc"]["first"].year else ""
    return (f"西元 {b(year)} 年＝{roc}＝{jp}{note}。這一年臺灣的鐘面："
            f"{clock_sentence(year, periods, names, b)}。")


# --- figure 1: eras and clocks, 1895–1950 --------------------------------------

def _frac(t: date | datetime) -> float:
    d = t if isinstance(t, date) and not isinstance(t, datetime) else t.date()
    start = date(d.year, 1, 1)
    return d.year + (d - start).days / (date(d.year + 1, 1, 1) - start).days


def _bands(eras: dict, periods: list[dict], b) -> list[dict]:
    """The seven things figure 1 lets a reader point at, plus the 民國前 and
    local-mean-time stretches it draws without a key."""
    a0, a1 = date(AXIS[0], 1, 1), date(AXIS[1], 1, 1)
    out = []
    for key in JAPANESE:
        era = eras[key]
        first, end = max(a0, era["first"] or a0), min(a1, era["last"] + timedelta(days=1) if era["last"] else a1)
        n0, n1 = first.year - era["offset"], (end - timedelta(days=1)).year - era["offset"]
        span = f"{era_year(era['label'], n0, b)}–{b(n1)} 年" if n0 > 1 else f"{era['label']}元年–{b(n1)} 年"
        start_text = (f"從 {b(era['first'].year)} 年 {md(era['first'], b)}開始" if era["first"]
                      else f"本圖從 {b(AXIS[0])} 年（{era_year(era['label'], AXIS[0] - era['offset'], b)}）畫起")
        end_text = (f"最後一天是 {b(era['last'].year)} 年 {md(era['last'], b)}" if era["last"] and era["last"] < a1
                    else "本圖畫到 " + b(AXIS[1] - 1) + " 年")
        out.append({"key": key, "row": 0, "start": first, "end": end, "fill": "fx-cell",
                    "name": era["label"], "label": span,
                    "sentence": (f"{era['label']}：西元年＝{era['label']}年＋{b(era['offset'])}。{start_text}，"
                                 f"{end_text}。"),
                    "spoken": f"{era['label']}，{span}"})
    roc = eras["roc"]
    out.append({"key": None, "row": 1, "start": a0, "end": roc["first"], "fill": "fx-fill-dot", "name": "民國前",
                "label": "民國前", "sentence": "", "spoken": ""})
    n1 = AXIS[1] - 1 - roc["offset"]
    out.append({"key": "roc", "row": 1, "start": roc["first"], "end": a1, "fill": "fx-cell", "name": "民國",
                "label": f"民國元年–{b(n1)} 年",
                "sentence": (f"民國：西元年＝民國年＋{b(roc['offset'])}，{b(roc['first'].year)} 年 {md(roc['first'], b)}"
                             f"是民國元年第一天。大正年與民國年同數，民國年＝昭和年＋"
                             f"{b(eras['showa']['offset'] - roc['offset'])}。"),
                "spoken": f"民國，民國元年–{b(n1)} 年"})
    # The clock: local mean time, then three standard-time periods; the summers ride on the last.
    keys = {"standard_time": ("west", "post"), "japan_standard_time": ("jst",)}
    seen: dict[str, int] = {}
    post: Any = None
    for p in periods:
        s, e = max(datetime(AXIS[0], 1, 1), p["start"]), min(datetime(AXIS[1], 1, 1), p["end"])
        if s >= e:
            continue
        regime = p["regime"]
        if regime == "local_mean_time":
            out.append({"key": None, "row": 2, "start": s.date(), "end": e.date(), "fill": "fx-fill-dot",
                        "name": "地方平時", "label": "", "offset": p["offset"], "sentence": "", "spoken": ""})
            continue
        if regime == "summer_time":
            post["summers"].append((s, e))
            continue
        if post is not None and regime == "standard_time" and post["regime"] == "standard_time":
            post["end"] = e.date()          # a summer ended: the same post-war period goes on
            continue
        index = seen.get(regime, 0)
        seen[regime] = index + 1
        key = keys[regime][index]
        band = {"key": key, "row": 2, "start": s.date(), "end": e.date(), "end_at": e, "offset": p["offset"],
                "regime": regime,
                "fill": "fx-fill-cross" if regime == "japan_standard_time" else "fx-cell", "summers": []}
        out.append(band)
        post = band
    names = regime_names()
    clock = [x for x in out if x["row"] == 2 and x["key"]]
    if [x["key"] for x in clock] != ["west", "jst", "post"]:
        raise RuntimeError(f"figure 1 names three clock periods, the pin gives {[x['key'] for x in clock]}")
    for x in clock:
        utc = utc_text(x["offset"], b)
        since = f"{b(x['start'].year)} 年 {md(x['start'], b)}"
        name = {"west": "西部標準時", "jst": names["japan_standard_time"], "post": names["standard_time"]}[x["key"]]
        x["name"] = name
        x["label"] = f"{utc}　{name}" if x["key"] == "west" else utc
        if x["key"] == "post":
            years = [s.year for s, _ in x["summers"]]
            x["sentence"] = (f"{since}起：改回 {utc}。{b(years[0])}–{b(years[-1])} 年每年夏天另有夏令時間，"
                             f"鐘面是 {utc_text(clock[1]['offset'], b)}；逐年起訖見〈臺灣的時區與夏令時間〉。")
            x["spoken"] = f"{name}，{since}起，鐘面 {utc}，夏季另有夏令時間"
        else:
            end = x["end_at"]
            until = (f"{b(end.year)} 年 {md(end, b)}凌晨 {b(end.hour)} 點" if end.time() != datetime.min.time()
                     else f"{b(end.year)} 年 {md(end - timedelta(days=1), b)}")
            x["sentence"] = f"{since}到 {until}：鐘面是 {utc}（{name}）。"
            x["spoken"] = f"{name}，{since}起，鐘面 {utc}"
    return out


def _timeline(layout: str, fid: str, bands: list[dict], lmt: int, bound: _fx.Bound) -> str:
    b = lambda v: bound.num(str(v))  # noqa: E731
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        a0, a1 = 150.0, 846.0
        rows = ((54.0, 46.0), (116.0, 46.0), (178.0, 58.0))   # (top, height) of each row
        axis = 252.0
        H = 330.0
    else:
        a0, a1 = 92.0, 92.0 + (AXIS[1] - AXIS[0]) * 8.6
        rows = ((66.0, 84.0), (156.0, 80.0), (242.0, 84.0))  # (left, width) of each column
        axis = 60.0
        H = a1 + 54
    T = lambda t: a0 + (_frac(t) - AXIS[0]) / (AXIS[1] - AXIS[0]) * (a1 - a0)  # noqa: E731

    def box(band: dict) -> tuple[float, float, float, float]:
        top, size = rows[band["row"]]
        t0, t1 = T(band["start"]), T(band["end"])
        return (t0, top, t1 - t0, size) if wide else (top, t0, size, t1 - t0)

    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    heads = ("日本年號", "民國", "臺灣的鐘面")
    for (top, size), head in zip(rows, heads):
        if wide:
            out.append(_fx.text(24, top + size / 2 + 6, head, "fx-t fx-small fx-dim"))
        else:
            out.append(_fx.text(top + size / 2, axis - 22, "鐘面" if head == "臺灣的鐘面" else head,
                                "fx-t fx-small fx-dim", "middle"))
    for year in range(1900, AXIS[1], 10):
        tick = bound.scale(str(year))
        x = T(date(year, 1, 1))
        if wide:
            out.append(_fx.line(x, axis, x, axis + 6, "fx-axis"))
            out.append(_fx.text(x, axis + 26, tick, "fx-t fx-small fx-num", "middle"))
        else:
            out.append(_fx.line(axis - 6, x, axis, x, "fx-axis"))
            out.append(_fx.text(axis - 10, x + 4, tick, "fx-t fx-small fx-num", "end"))
    out.append(_fx.line(*((a0, axis, a1, axis) if wide else (axis, a0, axis, a1)), "fx-axis"))
    # Where an era or a clock changes: a hairline across all rows.
    for band in bands:
        if band["start"] > date(AXIS[0], 1, 1):
            t = T(band["start"])
            hx1, hy1, hx2, hy2 = (t, rows[0][0] - 6, t, axis) if wide else (axis, t, W - 12, t)
            out.append(_fx.line(hx1, hy1, hx2, hy2, "fx-hair"))
    for band in bands:
        x, y, w, h = box(band)
        body = _fx.rect(x, y, w, h, band["fill"])
        for s, e in band.get("summers", []):
            t0, t1 = T(s), T(e)
            if wide:
                body += _fx.rect(t0, y, max(t1 - t0, 1.6), 12, "fx-fill-solid")
            else:
                body += _fx.rect(x + w - 12, t0, 12, max(t1 - t0, 1.6), "fx-fill-solid")
        body += _band_label(band, (x, y, w, h), wide)
        if band["key"]:
            out.append(f'<g class="fx-row" data-fx-key="{band["key"]}" tabindex="0" aria-label="{band["spoken"]}">'
                       + _fx.rect(x, y, w, h, "fx-hit") + body + "</g>")
        else:
            out.append(body)
    # Local mean time is one year wide: named under the axis, not inside its sliver.
    note = f"{b(AXIS[0])} 年：地方平時（點，比世界時快 {b(lmt // 3600)} 小時 {b(lmt % 3600 // 60)} 分）"
    out.append(_fx.text(a0 if wide else 18, H - 22, note if wide else note.replace("（點，", "（"),
                        "fx-t fx-small", "start"))
    out.append("</svg>")
    return "".join(out)


def _band_label(band: dict, rect: tuple[float, float, float, float], wide: bool) -> str:
    if not band["label"]:
        return ""
    x, y, w, h = rect
    cls = "fx-t fx-small fx-key" if band["fill"] != "fx-cell" else "fx-t fx-small"
    if wide:
        name = band["label"] if band["row"] != 0 else f"{band['name']}　{band['label'].replace(band['name'], '', 1)}"
        return _fx.text(x + 10, y + h / 2 + 6, name, cls)
    lines = [band["label"]] if band["row"] != 0 else [band["name"], band["label"].replace(band["name"], "", 1)]
    if band["row"] == 2 and band["key"] == "west":
        lines = band["label"].split("　")
    if band["row"] == 1 and band["key"] == "roc":
        lines = ["民國", band["label"].replace("民國", "", 1)]
    cx, top = x + w / 2, y + min(h / 2, 40) - 8 * (len(lines) - 1)
    return "".join(_fx.text(cx, top + 18 * i + 4, line, cls, "middle") for i, line in enumerate(lines))


def _band_table(bands: list[dict]) -> str:
    rows = "".join(
        f'<tr data-fx-key="{x["key"]}"><th scope="row">{x["name"]}</th><td>{x["label"].replace("　", " ")}</td>'
        f'<td>{x["sentence"]}</td></tr>' for x in bands if x["key"])
    return _fx.data_table(("紀年或時制", "圖上寫的", "說明"), rows)


# --- figure 2: one year at a time ----------------------------------------------

def _year_layout(layout: str, fid: str, years: list[int], eras: dict, periods: list[dict], names: dict,
                 bound: _fx.Bound) -> str:
    b = lambda v: bound.num(str(v))  # noqa: E731
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        x0, x1 = 130.0, 846.0
        era_row, clock_row, rh = (128.0, 182.0, 36.0)
        ticks = 232.0
        H = 290.0
    else:
        x0, x1 = 20.0, 320.0
        era_row, clock_row, rh = (130.0, 196.0, 32.0)
        ticks = 238.0
        H = 290.0
    X = lambda d, year: x0 + (_frac(d) - year) * (x1 - x0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        for hx, head in ((40, "西元"), (300, "民國"), (560, "日本年號")):
            out.append(_fx.text(hx, 40, head, "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, era_row + rh / 2 + 6, "年號", "fx-t fx-small fx-dim"))
        out.append(_fx.text(24, clock_row + rh / 2 + 6, "鐘面", "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(x0, era_row - 8, "年號", "fx-t fx-small fx-dim"))
        out.append(_fx.text(x0, clock_row - 8, "鐘面", "fx-t fx-small fx-dim"))
    for month in range(1, 14):
        x = x0 + (month - 1) / 12 * (x1 - x0)
        out.append(_fx.line(x, era_row, x, ticks, "fx-hair"))
        if month <= 12:
            label = bound.scale(str(month)) if not wide else f"{bound.scale(str(month))} 月"
            out.append(_fx.text(x + (x1 - x0) / 24, ticks + 20, label, "fx-t fx-small fx-num", "middle"))
    out.append(_fx.line(x0, ticks, x1, ticks, "fx-axis"))
    if not wide:
        out.append(_fx.text(x0, ticks + 42, "（月份）", "fx-t fx-small fx-dim"))
    default = years.index(DEFAULT_YEAR)
    for i, year in enumerate(years):
        body = []
        japan = japanese_years(year, eras)
        jp = "／".join(era_year(eras[k]["label"], n, b) for k, n, _, _ in japan)
        heads = (f"西元 {b(year)} 年", roc_year(year, eras, b), jp)
        if wide:
            body += [_fx.text(x, 74, text, "fx-t fx-num") for x, text in zip((40, 300, 560), heads)]
        else:
            body += [_fx.text(x0, 34 + 26 * j, text, "fx-t fx-num") for j, text in enumerate(heads)]
        # The era row.
        for k, n, first, last in japan:
            a, z = X(first, year), X(last + timedelta(days=1), year)
            body.append(_fx.rect(a, era_row, z - a, rh, "fx-cell"))
            label = era_year(eras[k]["label"], n, b)
            if z - a >= (96 if wide else 70):
                body.append(_fx.text(a + 8, era_row + rh / 2 + 5, label, "fx-t fx-small"))
            else:  # 昭和元年 is seven days long: named above its sliver, at the strip's end
                body.append(_fx.text(x1, era_row - 8, f"{label}（{md(first, b)}起）", "fx-t fx-small", "end"))
        # The clock row.
        for first, last, p in year_clock(year, periods):
            a, z = X(first, year), X(last + timedelta(days=1), year)
            fill = {"japan_standard_time": "fx-fill-cross", "summer_time": "fx-fill-hatch"}.get(p["regime"], "fx-cell")
            body.append(_fx.rect(a, clock_row, z - a, rh, fill))
            text = utc_text(p["offset"], b)
            if z - a >= 54:
                body.append(_fx.text(a + 8, clock_row + rh / 2 + 5, text,
                                     "fx-t fx-small fx-num" + (" fx-key" if fill != "fx-cell" else "")))
        # Where the year changes era or clock: a red hairline (the slider's cursor colour).
        cuts = sorted({X(first, year) for _, _, first, _ in japan[1:]}
                      | {X(first, year) for first, _, _ in year_clock(year, periods)[1:]})
        for x in cuts:
            body.append(_fx.line(x, era_row - 4, x, clock_row + rh + 4, "fx-cursor"))
        out.append(_fx.step_group(i, default, "".join(body)))
    out.append("</svg>")
    return "".join(out)


def _year_table(years: list[int], eras: dict, periods: list[dict], names: dict, bound: _fx.Bound) -> str:
    b = lambda v: bound.num(str(v))  # noqa: E731
    rows = []
    for year in years:
        jp = "／".join(era_year(eras[k]["label"], n, b) for k, n, _, _ in japanese_years(year, eras))
        spans = year_clock(year, periods)
        clock = "；".join(
            (f"{md(first, b)}起 " if i else "") + utc_text(p["offset"], b) for i, (first, _, p) in enumerate(spans))
        rows.append(f'<tr><th scope="row" class="n">{b(year)}</th><td>{roc_year(year, eras, b)}</td><td>{jp}</td>'
                    f'<td>{clock}</td></tr>')
    return _fx.data_table(("西元", "民國", "日本年號", "臺灣的鐘面"), rows, summary="逐年對照（表格）")


# --- table 1: what the service answers -----------------------------------------

def _clock(iso: str) -> str:
    return f"{iso[:10]} {iso[11:16]}"


def _example_rows(answers: list[dict], eras: dict, names: dict) -> tuple[str, list[str]]:
    rows, quoted = [], []
    for a in answers:
        body = a["body"]
        label = eras[a["era"]]["label"]
        record = (f"{era_year(label, a['n'], str)} {a['month']} 月 {a['day']} 日 {a['hour']:02d}:{a['minute']:02d}"
                  f"（{roc_year(a['year'], eras, str)}）")
        western = f"{a['year']}-{a['month']:02d}-{a['day']:02d}"
        if body["status"] == "single":
            r = body["readings"][0]
            answer = f"{r['utc_offset_label']}（{names[r['rule']['regime']]}）"
            utc = _clock(r["utc_iso_8601"])
        elif body["status"] == "nonexistent":
            g = body["gap"]
            answer = (f"不存在：{g['skipped_local_start'][11:16]} 到 {g['skipped_local_end'][11:16]} 被跳過"
                      f"（{g['offset_before_label']} → {g['offset_after_label']}）")
            utc = "—"
        else:
            first, second = body["readings"]
            answer = "出現兩次：" + "、".join(
                f"{r['utc_offset_label']}（{names[r['rule']['regime']]}）" for r in (first, second))
            utc = f"{_clock(first['utc_iso_8601'])}／{_clock(second['utc_iso_8601'])[11:]}"
        rows.append(f'          <tr><td>{record}</td><td class="n">{western}</td><td>{answer}</td>'
                    f'<td class="n">{utc}</td></tr>')
        quoted.append(utc if utc != "—" else answer)
    return "\n".join(rows), quoted


def _era_rows(eras: dict, first_year: int) -> str:
    """Table 1: the era helper's table, in the methods page's order."""
    full = lambda d: f"{d.year} 年 {d.month} 月 {d.day} 日"  # noqa: E731
    rows = []
    for key in ("roc", *JAPANESE):
        era = eras[key]
        label = era["label"]
        if era["first"]:
            first = f"{full(era['first'])}（{label}元年）"
        else:
            first = f"—（本站計算器從 {first_year} 年起，即{era_year(label, first_year - era['offset'], str)}）"
        last = f"{full(era['last'])}（{era_year(label, era['last'].year - era['offset'], str)}）" if era["last"] else "—"
        rows.append(f'          <tr><td>{label}</td><td class="n">{label}年 ＋ {era["offset"]}</td><td>{first}</td>'
                    f"<td>{last}</td></tr>")
    return "\n".join(rows)


# --- the page ------------------------------------------------------------------

def build() -> tuple[dict[str, str], list[str]]:
    eras = read_eras()
    pin = taiwan_time.load_pin()
    taiwan_time.check_host_agrees(pin)
    periods = clock_periods(pin)
    names = regime_names()
    first_year = calculator_first_year()
    years = list(range(first_year, LAST_YEAR + 1))
    if DEFAULT_YEAR not in years:
        raise RuntimeError(f"the default year {DEFAULT_YEAR} is outside {first_year}–{LAST_YEAR}")

    b1 = _fx.Bound()
    n1 = lambda v: b1.num(str(v))  # noqa: E731
    bands = _bands(eras, periods, n1)
    lmt = periods[0]["offset"]
    jst = next(x for x in bands if x["key"] == "jst")
    timeline = _fx.figure(
        fid="fig-era-clock",
        hero=True,
        title=f"日本年號、民國紀年與臺灣的鐘面，{AXIS[0]} 到 {AXIS[1] - 1} 年",
        caption=(f"<b>{b1.label('圖 1')}</b>從 {n1(AXIS[0])} 到 {n1(AXIS[1] - 1)} 年，同一段時間的三種讀法：日本年號、民國紀年（點：民國前），"
                 "以及臺灣的鐘面比世界時快多少。鐘面那一條，空白是 "
                 f"{utc_text(next(x for x in bands if x['key'] == 'west')['offset'], n1)}，交叉線是日本中央標準時 "
                 f"{utc_text(jst['offset'], n1)}；邊上的實心細條是戰後的夏令時間。細直線是改元或改制的日子。"
                 f"年號依本站換算助手的年號表，鐘面依 IANA 時區資料庫 {n1(pin['tzdata'])} 版"
                 f"<a class=\"ar-cite\" href=\"#ref-1\">{b1.label('[1]')}</a><a class=\"ar-cite\" href=\"#ref-4\">"
                 f"{b1.label('[4]')}</a>。"),
        art=_fx.FigureArt.drawn(
            _timeline, "fig-era-clock", bands, lmt, b1,
            notes=[_fx.Note(x["key"], None, x["sentence"]) for x in bands if x["key"]],
            idle="用 Tab 鍵移到一段年號或時制上，或用滑鼠指著它，這裡會寫出它的換算與起訖。",
        ),
        table=_band_table(bands),
        bound=b1,
    )

    b2 = _fx.Bound()
    nb2 = lambda v: b2.num(str(v))  # noqa: E731
    notes = [_fx.Note(None, None, year_sentence(year, eras, periods, names, nb2), step=i) for i, year in enumerate(years)]
    converter = _fx.figure(
        fid="fig-era-year",
        title="選一個西元年，看它的民國年、日本年號，以及那一年臺灣的鐘面",
        caption=(f"<b>{b2.label('圖 2')}</b>拖拉選一個年份（{nb2(years[0])} 到 {nb2(years[-1])} 年；本站計算器從 "
                 f"{nb2(first_year)} 年起算）。上方三欄是同一年的三種寫法；下方兩條把這一年從 1 月到 12 月攤開："
                 "年號那一條標出改元的日子，鐘面那一條標出 UTC 偏移，交叉線是日本中央標準時，單線是夏令時間。"
                 "朱紅直線是這一年裡改元或改制的日子。表格列出每一年。"),
        art=_fx.FigureArt.drawn(
            _year_layout, "fig-era-year", years, eras, periods, names, b2,
            notes=notes,
            idle="拖拉選一個年份，這裡會寫出那一年的三種寫法與鐘面。",
        ),
        controls=_fx.FigureControls(
            steps=len(years),
            default_step=years.index(DEFAULT_YEAR),
            scrub_label="西元年",
        ),
        table=_year_table(years, eras, periods, names, b2),
        bound=b2,
    )

    answers = convert(EXAMPLES, eras)
    rows, quoted = _example_rows(answers, eras, names)
    a, c = answers[0]["body"]["readings"][0], answers[1]["body"]["readings"][0]
    gap = answers[2]["body"]["gap"]
    quoted += [
        f"民國年 ＋ {eras['roc']['offset']}",
        f"明治年 ＋ {eras['meiji']['offset']}",
        f"大正年 ＋ {eras['taisho']['offset']}",
        f"昭和年 ＋ {eras['showa']['offset']}",
        f"民國年＝昭和年＋{eras['showa']['offset'] - eras['roc']['offset']}",
        f"{eras['taisho']['first'].year} 年 {eras['taisho']['first'].month} 月 {eras['taisho']['first'].day} 日",
        f"{eras['showa']['first'].year} 年 {eras['showa']['first'].month} 月 {eras['showa']['first'].day} 日",
        f"世界時 {a['utc_iso_8601'][11:16]}",
        f"世界時 {c['utc_iso_8601'][11:16]}",
        f"{gap['skipped_local_start'][11:16]} 到 {gap['skipped_local_end'][11:16]}",
        f"從 {first_year} 年起",
        *(f"{x['start'].year} 年 {x['start'].month} 月 {x['start'].day} 日" for x in bands
          if x["key"] in ("west", "jst", "post")),
        f"快 {lmt // 3600} 小時 {lmt % 3600 // 60} 分",
    ]
    return {"fx-defs": _fx.defs(()), "era-clock": timeline, "era-year": converter, "era-examples": rows,
            "era-table": _era_rows(eras, first_year)}, quoted
