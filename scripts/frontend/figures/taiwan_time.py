"""〈臺灣的時區與夏令時間〉: figure 1 (clock offset from UT, 1890–1985, each
era and run of summers can be pointed at), figure 2 (the clock hour skipped
and the one repeated in 1974), figure 3 (what the two documented revisions of
the database touched), table 1 (the daylight-saving summers) and the
synthetic 1975 example.

The offsets are pinned in taiwan_tz_2026d.json (IANA tz 2026d, Asia/Taipei,
1890–1990), so the figure does not change with the host's tz database.  The
check re-derives the same transitions from the host's zoneinfo and fails if
they differ: then either the host's tz data is older than 2014f or a newer
release rewrote Taiwan's history, and the article must be revisited before
the pin is replaced.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from . import _fx
from ._common import SIGNS, TAIPEI, swiss, zh


FRAGMENT = "blog-taiwan-time-zone-history"
PIN = Path(__file__).with_name("taiwan_tz_2026d.json")
LAT, LON = TAIPEI
EXAMPLE_LOCAL = datetime(1975, 7, 15, 15, 0)


def derive_transitions(zone: str, first_year: int, end_year: int) -> list[dict]:
    """Every UTC-offset change of `zone` in [first_year, end_year), to the second.

    Scans day by day, then bisects on whole POSIX seconds; a day holding two
    changes (which would hide one) is refused rather than missed.
    """
    z = ZoneInfo(zone)

    def offset(second: int) -> timedelta:
        value = datetime.fromtimestamp(second, timezone.utc).astimezone(z).utcoffset()
        if value is None:
            raise RuntimeError(f"{zone} has no UTC offset at {second}")
        return value

    day = 86400
    t = int(datetime(first_year, 1, 1, tzinfo=timezone.utc).timestamp())
    stop = int(datetime(end_year, 1, 1, tzinfo=timezone.utc).timestamp())
    previous = offset(t)
    found = []
    while t < stop:
        n = t + day
        current = offset(n)
        if current != previous:
            lo, hi = t, n
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if offset(mid) == previous:
                    lo = mid
                else:
                    hi = mid
            if offset(hi) != current:
                raise RuntimeError(f"more than one offset change within a day after {lo}")
            instant = datetime.fromtimestamp(hi, timezone.utc)
            found.append({
                "utc": instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "from": int(previous.total_seconds()),
                "to": int(current.total_seconds()),
                "abbr": instant.astimezone(z).tzname(),
            })
            previous = current
        t = n
    return found


def load_pin() -> dict:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    if not pin.get("transitions"):
        raise RuntimeError(f"{PIN.name} holds no transitions")
    return pin


def check_host_agrees(pin: dict) -> None:
    observed = derive_transitions(pin["zone"], *pin["years"])
    if observed != pin["transitions"]:
        raise RuntimeError(
            f"the host's zoneinfo disagrees with the pinned tz {pin['tzdata']} transitions for "
            f"{pin['zone']} {pin['years']}: {len(observed)} observed, {len(pin['transitions'])} pinned"
        )


def _utc(record: dict) -> datetime:
    return datetime.strptime(record["utc"], "%Y-%m-%dT%H:%M:%SZ")


def _local_before(record: dict) -> datetime:
    return _utc(record) + timedelta(seconds=record["from"])


def _local_after(record: dict) -> datetime:
    return _utc(record) + timedelta(seconds=record["to"])


def _offset_at(transitions: list[dict], utc: datetime) -> int:
    current = transitions[0]["from"]
    for record in transitions:
        if _utc(record) <= utc:
            current = record["to"]
    return current


# The three figures: the offset over 1890–1985 (each era and each run of
# summers can be pointed at), the hour skipped and the hour repeated in 1974,
# and the two documented revisions of the database.  Every date, offset and
# clock reading is read from the pinned transitions; the only numbers that are
# not are the citations' own (the decree, the meridian, the release names, and
# the year the 2010 mail says the database then held).
AXIS = (1890, 1985)
IDLE = "用 Tab 鍵移到一段時期上，或用滑鼠指著它，這裡會寫出那段時期的制度與起訖。"
SUMMER = ("CDT", "CST")


def _year(t: datetime) -> float:
    start, nxt = datetime(t.year, 1, 1), datetime(t.year + 1, 1, 1)
    return t.year + (t - start) / (nxt - start)


def _hm(seconds: int) -> tuple[int, int]:
    return seconds // 3600, seconds % 3600 // 60


def _date(t: datetime) -> str:
    return f"{t.year} 年 {t.month} 月 {t.day} 日"


def _summers(tr: list[dict]) -> list[tuple[datetime, datetime]]:
    """Every daylight-saving summer: (clock start, clock end), as the clock read them."""
    pairs = tr[3:]
    if len(pairs) % 2 or any((a["abbr"], b["abbr"]) != SUMMER for a, b in zip(pairs[::2], pairs[1::2])):
        raise RuntimeError("after the third change the pinned transitions are no longer summer pairs")
    return [(_local_before(a), _local_before(b)) for a, b in zip(pairs[::2], pairs[1::2])]


def _runs(summers: list[tuple[datetime, datetime]]) -> list[list[tuple[datetime, datetime]]]:
    """The summers in runs, split where more than five years pass without one."""
    runs: list[list] = []
    for summer in summers:
        if runs and summer[0].year - runs[-1][-1][0].year <= 5:
            runs[-1].append(summer)
        else:
            runs.append([summer])
    if len(runs) != 2:
        raise RuntimeError(f"the figure names two runs of summers, the pin has {len(runs)}")
    return runs


def _eras(pin: dict, bound: _fx.Bound) -> list[dict]:
    """The six things figure 1 lets a reader point at, each with its sentence."""
    tr = pin["transitions"]
    if [r["abbr"] for r in tr[:3]] != ["CST", "JST", "CST"] or tr[0]["to"] != tr[2]["to"]:
        raise RuntimeError("the first three pinned changes are no longer LMT→UTC+8→UTC+9→UTC+8")
    standard, japan = tr[0]["to"], tr[1]["to"]
    lmt_h, lmt_m = _hm(tr[0]["from"])
    b = lambda v: bound.num(str(v))  # noqa: E731
    utc8, utc9 = f"UTC+{b(standard // 3600)}", f"UTC+{b(japan // 3600)}"
    t1896, t1937, t1945 = (_local_before(r) for r in tr[:3])
    # The clock readings at each change: before and after.
    jump = (bound.num(f"{t1937:%H:%M}"), bound.num(f"{_local_after(tr[1]):%H:%M}"))
    back = (_local_before(tr[2]), _local_after(tr[2]))
    runs = _runs(_summers(tr))
    first, second = runs
    years = lambda run: [s[0].year for s in run]  # noqa: E731
    eras = [
        {"key": "lmt", "start": datetime(AXIS[0], 1, 1), "end": t1896, "offset": tr[0]["from"],
         "name": "地方平時", "fill": "fx-fill-dot",
         "label": f"地方平時，快 {b(lmt_h)} 小時 {b(lmt_m)} 分",
         "sentence": (f"{b(t1896.year)} 年以前：沒有官定的標準時。時區資料庫用臺北的地方平時代表這一段，"
                      f"比世界時快 {b(lmt_h)} 小時 {b(lmt_m)} 分，這只是依經度推算的代表值。"),
         "from": f"（{b(t1896.year)} 年以前）", "to": _date_b(t1896, bound),
         "offset_text": f"{b(lmt_h)} 小時 {b(lmt_m)} 分",
         "spoken": f"地方平時，{b(t1896.year)} 年以前，鐘面比世界時快 {b(lmt_h)} 小時 {b(lmt_m)} 分"},
        {"key": "cst1", "start": t1896, "end": t1937, "offset": standard, "name": "西部標準時",
         "fill": "fx-cell", "label": f"{utc8}　西部標準時",
         "sentence": (f"{_date_b(t1896, bound)}起：依{bound.label('明治 28 年敕令第 167 號')}，以"
                      f"{bound.label('東經 120 度')}子午線的時間為標準，稱為「西部標準時」，也就是 {utc8}。"),
         "from": _date_b(t1896, bound), "to": _date_b(t1937, bound), "offset_text": utc8,
         "spoken": f"西部標準時，{_date_b(t1896, bound)}到 {_date_b(t1937, bound)}，鐘面是 {utc8}"},
        {"key": "jst", "start": t1937, "end": back[0], "offset": japan, "name": "中央標準時",
         "fill": "fx-fill-cross", "label": utc9,
         "sentence": (f"{_date_b(t1937, bound)}起：臺灣改用日本的中央標準時 {utc9}。"
                      f"時鐘在那天午夜直接從 {jump[0]} 跳到 {jump[1]}。"),
         "from": _date_b(t1937, bound), "to": _date_b(back[0], bound), "offset_text": utc9,
         "spoken": f"中央標準時，{_date_b(t1937, bound)}到 {_date_b(back[0], bound)}，鐘面是 {utc9}"},
        {"key": "cst2", "start": back[0], "end": datetime(AXIS[1], 1, 1), "offset": standard,
         "name": "改回標準時", "fill": "fx-cell", "label": utc8,
         "sentence": (f"{_date_b(back[0], bound)}：改回 {utc8}，時鐘在凌晨 {b(back[0].hour)} 點撥回 "
                      f"{b(back[1].hour)} 點。之後的標準時一直是 {utc8}。"),
         "from": _date_b(back[0], bound), "to": "（至今）", "offset_text": utc8,
         "spoken": f"改回標準時，{_date_b(back[0], bound)}起至今，鐘面是 {utc8}"},
        {"key": "dst1", "run": first, "name": "日光節約時間",
         "label": f"{b(years(first)[0])}–{b(years(first)[-1])}",
         "sentence": (f"{b(years(first)[0])}–{b(years(first)[-1])} 年：每年夏天實施日光節約時間，"
                      f"共 {b(len(first))} 個夏季，期間鐘面為 {utc9}。各年的起訖見{bound.label('表 1')}。"),
         "from": f"{b(years(first)[0])} 年", "to": f"{b(years(first)[-1])} 年", "offset_text": f"夏季 {utc9}",
         "spoken": f"日光節約時間，{b(years(first)[0])} 到 {b(years(first)[-1])} 年每年夏季，鐘面是 {utc9}"},
        {"key": "dst2", "run": second, "name": "日光節約時間",
         "label": "、".join(b(y) for y in years(second)),
         "sentence": (f"{'、'.join(b(y) for y in years(second))} 年：又實施了 {b(len(second))} 個夏季，"
                      f"鐘面同樣是 {utc9}。各年的起訖見{bound.label('表 1')}。"),
         "from": f"{b(years(second)[0])} 年", "to": f"{b(years(second)[-1])} 年{_gap(years(second), bound)}",
         "offset_text": f"夏季 {utc9}",
         "spoken": f"日光節約時間，{'、'.join(b(y) for y in years(second))} 年的夏季，鐘面是 {utc9}"},
    ]
    return eras


def _gap(years: list[int], bound: _fx.Bound) -> str:
    """「（1976–1978 年沒有實施）」: the years inside a run of summers without one,
    so a table row from 1974 to 1979 is not read as six summers."""
    missing = [y for y in range(years[0], years[-1] + 1) if y not in years]
    if not missing:
        return ""
    if missing != list(range(missing[0], missing[-1] + 1)):
        raise RuntimeError(f"the summers {years} leave more than one gap")
    span = bound.num(str(missing[0])) if len(missing) == 1 else \
        f"{bound.num(str(missing[0]))}–{bound.num(str(missing[-1]))}"
    return f"（{span} 年沒有實施）"


def _date_b(t: datetime, bound: _fx.Bound) -> str:
    return bound.num(_date(t))


def _span(era: dict) -> tuple[float, float]:
    if "run" in era:
        return _year(era["run"][0][0]), _year(era["run"][-1][1])
    return _year(era["start"]), _year(era["end"])


def _row(era: dict, body: str, hit: tuple[float, float, float, float]) -> str:
    x, y, w, h = hit
    label = era["spoken"]
    return (f'<g class="fx-row" data-fx-key="{era["key"]}" tabindex="0" aria-label="{label}">'
            + _fx.rect(x, y, w, h, "fx-hit") + body + "</g>")


def _offsets(layout: str, fid: str, eras: list[dict], bound: _fx.Bound) -> str:
    """Figure 1, one layout.  Wide: years across, the offset up.  Narrow: years
    down, the offset across."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    standard = eras[1]["offset"]

    if wide:
        a0, a1 = 110.0, 846.0           # the year axis
        l8, l9, base = 236.0, 120.0, 268.0  # the offset axis: +8, +9, the floor of the areas
        H = 330.0
    else:
        a0, a1 = 84.0, 84.0 + (AXIS[1] - AXIS[0]) * 5.8
        l8, l9, base = 150.0, 262.0, 84.0
        H = a1 + 26
    T = lambda year: a0 + (year - AXIS[0]) / (AXIS[1] - AXIS[0]) * (a1 - a0)  # noqa: E731
    L = lambda seconds: l8 + (seconds - standard) / 3600 * (l9 - l8)  # noqa: E731

    def box(t0: float, t1: float, v0: float, v1: float) -> tuple[float, float, float, float]:
        """(x, y, w, h) of the area between two years and two offset positions."""
        if wide:
            return T(t0), min(v0, v1), T(t1) - T(t0), abs(v1 - v0)
        return min(v0, v1), T(t0), abs(v1 - v0), T(t1) - T(t0)

    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(24 if wide else 18, 40 if wide else 32, "鐘面比世界時快", "fx-t fx-small fx-dim"))
    for seconds in (standard, eras[2]["offset"]):
        name = f"UTC+{bound.num(str(seconds // 3600))}"
        if wide:
            out.append(_fx.line(a0, L(seconds), a1, L(seconds), "fx-hair"))
            out.append(_fx.text(a0 - 12, L(seconds) + 5, name, "fx-t fx-small fx-num", "end"))
        else:
            out.append(_fx.line(L(seconds), a0 - 4, L(seconds), a1, "fx-hair"))
            out.append(_fx.text(L(seconds), a0 - 14, name, "fx-t fx-small fx-num", "middle"))
    # The years.
    for year in range(AXIS[0], AXIS[1] + 1, 10):
        tick = bound.scale(str(year))
        if wide:
            out.append(_fx.line(T(year), base, T(year), base + 6, "fx-axis"))
            out.append(_fx.text(T(year), base + 26, tick, "fx-t fx-small fx-num", "middle"))
        else:
            out.append(_fx.line(base - 6, T(year), base, T(year), "fx-axis"))
            out.append(_fx.text(base - 10, T(year) + 4, tick, "fx-t fx-small fx-num", "end"))
    out.append(_fx.line(*((a0, base, a1, base) if wide else (base, a0, base, a1)), "fx-axis"))

    # The standard-time eras: an area up to the offset, then the stepped line over them.
    step = []
    for era in eras[:4]:
        t0, t1 = _span(era)
        level = L(era["offset"])
        area = _fx.rect(*box(t0, t1, base, level), era["fill"])
        step.append((T(t0), level, T(t1)))
        if wide:
            hit = (T(t0), l9 - 52 if era["key"] in ("lmt", "cst1") else l9 - 8, T(t1) - T(t0),
                   base - (l9 - 52 if era["key"] in ("lmt", "cst1") else l9 - 8))
        else:
            hit = (14.0, T(t0), W - 28, T(t1) - T(t0))
        out.append(_row(era, area + _label(era, wide, T, L, base, l8, l9), hit))
    if wide:
        d = " ".join(f"{'M' if i == 0 else 'L'}{_fx.f(x0)} {_fx.f(y)} L{_fx.f(x1)} {_fx.f(y)}"
                     for i, (x0, y, x1) in enumerate(step))
    else:
        d = " ".join(f"{'M' if i == 0 else 'L'}{_fx.f(y)} {_fx.f(x0)} L{_fx.f(y)} {_fx.f(x1)}"
                     for i, (x0, y, x1) in enumerate(step))
    out.append(_fx.path(d, "fx-step"))

    # The summers: a solid bar from +8 to +9 for each, the run's years beside it.
    for era in eras[4:]:
        bars = "".join(_fx.rect(*_min_bar(box(_year(s), _year(e), L(standard), L(eras[2]["offset"])), wide), "fx-fill-solid")
                       for s, e in era["run"])
        t0, t1 = _span(era)
        if wide:
            hit = (T(t0) - 4, l9 - 40, T(t1) - T(t0) + 8, l8 - l9 + 40)
            text = _fx.text((T(t0) + T(t1)) / 2, l9 - 12, era["label"], "fx-t fx-small fx-num", "middle")
        else:
            hit = (l8 - 4, T(t0) - 3, W - 14 - (l8 - 4), T(t1) - T(t0) + 6)
            if era["key"] == "dst1":
                text = (_fx.text(l9 + 8, T(t0) + 12, "日光節約", "fx-t fx-small")
                        + _fx.text(l9 + 8, T(t0) + 28, "（夏季）", "fx-t fx-small")
                        + _fx.text(l9 + 8, T(t0) + 46, era["label"], "fx-t fx-small fx-num"))
            else:
                # consecutive years share a line: 「1974、75」, then 「1979」
                lines: list[list[int]] = []
                for s, _ in era["run"]:
                    if lines and s.year == lines[-1][-1] + 1:
                        lines[-1].append(s.year)
                    else:
                        lines.append([s.year])
                text = "".join(
                    _fx.text(l9 + 8, T(line[0] + len(line) / 2) + 4,
                             "、".join([bound.num(str(line[0]))] + [bound.num(f"{y % 100:02d}") for y in line[1:]]),
                             "fx-t fx-small fx-num") for line in lines)
        out.append(_row(era, bars + text, hit))
    if wide:
        t0, t1 = _span(eras[4])[0], _span(eras[5])[1]
        out.append(_fx.text((T(t0) + T(t1)) / 2, l9 - 34, f"夏季日光節約時間（鐘面 {eras[2]['label']}）",
                            "fx-t fx-small", "middle"))
    out.append("</svg>")
    return "".join(out)


def _min_bar(box: tuple[float, float, float, float], wide: bool) -> tuple[float, float, float, float]:
    """A summer is a few pixels thick at most; never thinner than 1.6 units."""
    x, y, w, h = box
    if wide:
        return x, y, max(w, 1.6), h
    return x, y, w, max(h, 1.6)


def _label(era: dict, wide: bool, T, L, base: float, l8: float, l9: float) -> str:
    """An era's name: inside its area where it fits, otherwise beside it."""
    t0, t1 = _span(era)
    key = era["key"]
    if wide:
        if key == "lmt":
            return _fx.text(T(t0), L(era["offset"]) - 12, era["label"], "fx-t fx-small")
        if key == "jst":
            return _fx.text((T(t0) + T(t1)) / 2, (l9 + base) / 2 + 6, era["label"], "fx-t fx-num fx-key", "middle")
        if key == "cst1":
            return _fx.text(T(t0) + 14, (l8 + base) / 2 + 6, era["label"], "fx-t")
        # cst2: between the two runs of summers
        return _fx.text(T(1962.5), (l8 + base) / 2 + 6, era["label"], "fx-t fx-num")
    if key == "jst":
        return _fx.text((base + L(era["offset"])) / 2, (T(t0) + T(t1)) / 2 + 5, era["label"],
                        "fx-t fx-num fx-key", "middle")
    y = (T(t0) + T(t1)) / 2 + 5 if key != "cst2" else T(1966.5)
    x = L(era["offset"]) + 10
    return _fx.text(x, y, era["label"], "fx-t fx-small fx-key" if key == "lmt" else "fx-t fx-key")


def _offset_table(eras: list[dict]) -> str:
    rows = "".join(
        f'<tr data-fx-key="{e["key"]}"><th scope="row">{e["name"]}</th><td>{e["offset_text"]}</td>'
        f'<td>{e["from"]}</td><td>{e["to"]}</td></tr>' for e in eras)
    return _fx.data_table(("時期", "鐘面比世界時快", "起", "迄"), rows)


def _clock(t: datetime) -> str:
    return f"{t:%H:%M}"


def _mapping(x0: float, top: float, k: float, record: dict, bound: _fx.Bound, wide: bool) -> str:
    """One panel of figure 2: universal time above, the clock below, a line
    from each quarter hour to what the clock read then.  A skipped hour is left
    without lines; a repeated hour receives them twice."""
    utc = _utc(record)
    before, after = record["from"], record["to"]
    skipped = after > before
    span = timedelta(minutes=90)
    u0 = utc - span
    c0 = u0 + timedelta(seconds=before)
    c_end = utc + span + timedelta(seconds=after)
    U = lambda t: x0 + (t - u0).total_seconds() / 3600 * k  # noqa: E731
    C = lambda t: x0 + (t - c0).total_seconds() / 3600 * k  # noqa: E731
    yu, yc = top + 70, top + 170
    small = "fx-t fx-small"
    date = _local_after(record) if skipped else _local_before(record) - timedelta(seconds=1)
    title = (f"{bound.num(_date(date))}凌晨：跳過一小時" if skipped
             else f"{bound.num(_date(date))}深夜：重複一小時")
    out = [_fx.text(x0, top + 20, title, "fx-t")]
    out.append(_fx.text(x0, yu - 34, "世界時", small + " fx-dim"))
    out.append(_fx.text(x0, yc + 42, "臺灣的鐘面時間", small + " fx-dim"))
    # The hour without a counterpart, or with two.
    hour_start = _local_before(record) if skipped else _local_after(record)
    hour_end = hour_start + timedelta(hours=1)
    band = "fx-fill-hatch" if skipped else "fx-fill-cross"
    out.append(_fx.rect(C(hour_start), yc - 22, C(hour_end) - C(hour_start), 22, band))
    # The mapping lines, every quarter hour; at the change itself both readings.
    t = u0
    while t <= utc + span:
        offsets = [before, after] if t == utc else [before if t < utc else after]
        for offset in offsets:
            out.append(_fx.line(U(t), yu, C(t + timedelta(seconds=offset)), yc - 22, "fx-hair"))
        t += timedelta(minutes=15)
    out.append(_fx.line(U(u0), yu, U(utc + span), yu, "fx-axis"))
    out.append(_fx.line(C(c0), yc, C(c_end), yc, "fx-axis"))
    out.append(_fx.line(C(c0), yc - 22, C(c_end), yc - 22, "fx-hair"))
    for t in _hours(u0, utc + span):
        out.append(_fx.line(U(t), yu - 5, U(t), yu, "fx-axis"))
        out.append(_fx.text(U(t), yu - 10, bound.scale(f"{t:%H:%M}"), small + " fx-num", "middle"))
    for t in _hours(c0, c_end):
        out.append(_fx.line(C(t), yc, C(t), yc + 5, "fx-axis"))
        out.append(_fx.text(C(t), yc + 20, bound.scale(_clock(t)), small + " fx-num", "middle"))
    # The reading the article names: the middle of that hour.
    middle = hour_start + timedelta(minutes=30)
    reading = bound.num(_clock(middle))
    out.append(_fx.path(f"M{_fx.f(C(middle))} {_fx.f(yc - 26)} l-5 -9 h10 z", "fx-arrow"))
    if skipped:
        out.append(_fx.text(C(middle), yc - 40, f"{reading}　不存在", small + " fx-key", "middle"))
    else:
        out.append(_fx.text(C(middle), yc - 40, f"{reading}　出現兩次", small + " fx-key", "middle"))
        for n, offset in (("第一次", before), ("第二次", after)):
            when = middle - timedelta(seconds=offset)
            out.append(_fx.line(U(when), yu, C(middle), yc - 22, "fx-axis"))
            out.append(_fx.text(U(when), yu - 34, n, small, "middle"))
    return "".join(out)


def _hours(start: datetime, end: datetime) -> list[datetime]:
    first = start.replace(minute=0, second=0) + (timedelta(hours=1) if (start.minute, start.second) != (0, 0) else timedelta())
    out = []
    while first <= end:
        out.append(first)
        first += timedelta(hours=1)
    return out


def _gap_and_fold(layout: str, fid: str, pair: tuple[dict, dict], bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    if wide:
        k, H = 90.0, 262.0
        panels = ((34.0, 18.0), (476.0, 18.0))
    else:
        k, H = 72.0, 482.0
        panels = ((20.0, 12.0), (20.0, 250.0))
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for (x0, top), record in zip(panels, pair):
        out.append(_mapping(x0, top, k, record, bound, wide))
    if not wide:
        out.append(_fx.line(14, 242, W - 14, 242, "fx-hair"))
    out.append("</svg>")
    return "".join(out)


def _revisions(layout: str, fid: str, pin: dict, bound: _fx.Bound) -> str:
    """Figure 3: what the two documented revisions touched.  Above: the summer
    the 2010 mail moved (the database then held it in 1980); below: the span
    2014f rewrote, with the changes the current release holds there."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    tr = pin["transitions"]
    summers = _summers(tr)
    last = summers[-1]
    old_year = int(bound.label("1980"))
    rewritten = [r for r in tr if _utc(r).year <= 1947]
    first_year, last_year = _local_before(rewritten[0]).year, _local_before(rewritten[-1]).year
    if wide:
        x0, x1, H = 250.0, 846.0, 300.0
        rows = (40.0, 168.0)
    else:
        x0, x1, H = 20.0, 320.0, 340.0
        rows = (30.0, 186.0)
    small = "fx-t fx-small"
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]

    def axis(y: float, a: int, b: int, every: int, X) -> list[str]:
        parts = [_fx.line(x0, y, x1, y, "fx-axis")]
        for year in range(a, b + 1, every):
            parts.append(_fx.line(X(year), y, X(year), y + 5, "fx-axis"))
            anchor = "start" if year == a else "end" if year + every > b else "middle"
            parts.append(_fx.text(X(year), y + 22, bound.scale(str(year)), small + " fx-num", anchor))
        return parts

    # Row 1: 1974–1984.
    top = rows[0]
    a, b = last[0].year - 5, last[0].year + 5
    X = lambda year: x0 + (year - a) / (b - a) * (x1 - x0)  # noqa: E731
    head = f"{bound.label('2010 年')}：tz 郵件列表"
    if wide:
        out.append(_fx.text(24, top + 30, head, "fx-t"))
        out.append(_fx.text(24, top + 54, "指出放錯的一年", small))
        bar_y = top + 34
    else:
        out.append(_fx.text(x0, top + 14, head + "指出放錯的一年", small))
        bar_y = top + 52
    for s, e in summers:
        if a <= s.year <= b:
            out.append(_fx.rect(X(_year(s)), bar_y, X(_year(e)) - X(_year(s)), 26, "fx-fill-solid"))
    moved = (last[0].replace(year=old_year), last[1].replace(year=old_year))
    out.append(_fx.rect(X(_year(moved[0])), bar_y, X(_year(moved[1])) - X(_year(moved[0])), 26, "fx-dash"))
    out.append(_fx.path(f"M{_fx.f(X(_year(moved[0])) - 4)} {_fx.f(bar_y + 13)} "
                        f"L{_fx.f(X(_year(last[1])) + 8)} {_fx.f(bar_y + 13)}", "fx-leader"))
    out.append(_fx.path(f"M{_fx.f(X(_year(last[1])) + 3)} {_fx.f(bar_y + 13)} l8 -5 v10 z", "fx-arrow"))
    out.append(_fx.text((X(_year(moved[0])) + X(_year(moved[1]))) / 2, bar_y - 10, f"當時的資料庫：{old_year} 年",
                        small, "middle"))
    out += axis(bar_y + 34, a, b, 2 if not wide else 1, X)
    out.append(_fx.text(x1 if wide else x0, bar_y + 78 if wide else bar_y + 80,
                        f"實心：現行 {bound.num(pin['tzdata'])} 版；虛線：當時的位置",
                        small, "end" if wide else "start"))
    # Row 2: 1890–1950.
    top = rows[1]
    a, b = AXIS[0], 1950
    X = lambda year: x0 + (year - a) / (b - a) * (x1 - x0)  # noqa: E731
    head = f"{bound.label('2014f 版')}"
    if wide:
        out.append(_fx.text(24, top + 30, head, "fx-t"))
        out.append(_fx.text(24, top + 54, "依官報與公報改寫", small))
        bar_y = top + 34
    else:
        out.append(_fx.text(x0, top + 14, head + "：依官報與公報改寫", small))
        bar_y = top + 44
    start, end = _year(_local_before(rewritten[0])), _year(_local_before(rewritten[-1]))
    out.append(_fx.rect(X(start), bar_y, X(end) - X(start), 26, "fx-fill-hatch"))
    for record in rewritten:
        x = X(_year(_local_before(record)))
        out.append(_fx.line(x, bar_y - 6, x, bar_y + 32, "fx-axis"))
    span = f"改寫的範圍：{bound.num(str(first_year))}–{bound.num(str(last_year))} 年"
    out.append(_fx.text((X(start) + X(end)) / 2, bar_y + 18, span, small + " fx-key", "middle"))
    out += axis(bar_y + 34, a, b, 10 if wide else 20, X)
    out.append(_fx.text(x1 if wide else x0, bar_y + 78 if wide else bar_y + 80,
                        f"直線：{bound.num(pin['tzdata'])} 版在這段的每一次改撥", small, "end" if wide else "start"))
    out.append("</svg>")
    return "".join(out)


def _figures(pin: dict) -> dict[str, str]:
    tr = pin["transitions"]
    b1 = _fx.Bound()
    eras = _eras(pin, b1)
    tzdata = b1.num(pin["tzdata"])
    years = (b1.scale(str(AXIS[0])), b1.scale(str(AXIS[1])))
    cite = b1.label("[1]")
    offsets = _fx.figure(
        fid="fig-clock-offset",
        hero=True,
        title="臺灣的鐘面時間比世界時快多少，1890 到 1985 年",
        caption=(f"<b>{b1.label('圖 1')}</b>臺灣的鐘面時間比世界時（UTC）快多少，{years[0]} 到 {years[1]} 年。"
                 "粗線是鐘面比世界時快多少；線下的填法分出三種制度：地方平時（點）、西部標準時與戰後的標準時（空白）、日本的中央標準時（交叉線）；"
                 f"實心細條是實施日光節約時間的{zh(len(_summers(tr)))}個夏季，那段期間鐘面也是 {eras[2]['label']}。"
                 f"依 IANA 時區資料庫 {tzdata} 版<a class=\"ar-cite\" href=\"#ref-1\">{cite}</a>。"),
        art=_fx.FigureArt.drawn(
            _offsets, "fig-clock-offset", eras, b1,
            notes=[_fx.Note(e["key"], None, e["sentence"]) for e in eras],
            idle=IDLE,
        ),
        table=_offset_table(eras),
        bound=b1,
    )
    b2 = _fx.Bound()
    pair = tuple(r for r in tr if _utc(r).year == 1974)
    if len(pair) != 2 or pair[0]["to"] <= pair[0]["from"]:
        raise RuntimeError("1974 no longer holds one summer in the pin")
    gap = _fx.figure(
        fid="fig-gap-fold",
        title="1974 年臺灣的鐘面：春天跳過一小時，秋天重複一小時",
        caption=(f"<b>{b2.label('圖 2')}</b>上方的軸是世界時，下方是臺灣的鐘面時間，每一條細線連起同一個瞬間（每 "
                 f"{b2.scale('15')} 分鐘一條）。左：時鐘從 {b2.num(_clock(_local_before(pair[0])))} 直接跳到 "
                 f"{b2.num(_clock(_local_after(pair[0])))}，單線的那一小時沒有任何瞬間對得上。右：時鐘在午夜撥回 "
                 f"{b2.num(_clock(_local_after(pair[1])))}，交叉線的那一小時，每個鐘面讀數都對到兩個相隔一小時的瞬間。"
                 f"依 IANA 時區資料庫 {b2.num(pin['tzdata'])} 版<a class=\"ar-cite\" href=\"#ref-1\">{b2.label('[1]')}</a>。"),
        art=_fx.FigureArt.drawn(_gap_and_fold, "fig-gap-fold", pair, b2),
        bound=b2,
    )
    b3 = _fx.Bound()
    revisions = _fx.figure(
        fid="fig-tz-revisions",
        title="時區資料庫改過的兩處臺灣歷史：1979 年的夏令時間，以及 1896 到 1947 年",
        caption=(f"<b>{b3.label('圖 3')}</b>時區資料庫有據可查的兩次修訂。上：{b3.label('2010 年')}郵件列表指出，資料庫當時把 "
                 f"{b3.num(str(_summers(tr)[-1][0].year))} 年夏天的日光節約時間放在 {b3.label('1980')} 年"
                 f"<a class=\"ar-cite\" href=\"#ref-5\">{b3.label('[5]')}</a>。下：{b3.label('2014f 版')}改寫的年份範圍"
                 f"<a class=\"ar-cite\" href=\"#ref-7\">{b3.label('[7]')}</a>。用不同年代的軟體排這些年份的盤，"
                 "世界時可能相差一小時。"),
        art=_fx.FigureArt.drawn(_revisions, "fig-tz-revisions", pin, b3),
        bound=b3,
    )
    return {"fx-defs": _fx.defs(()), "clock-offset": offsets, "gap-fold": gap, "tz-revisions": revisions}


def _rows(pin: dict) -> str:
    tr = pin["transitions"]
    md = lambda t: f"{t.month} 月 {t.day} 日"  # noqa: E731
    groups: list[list] = []
    for i in range(3, len(tr), 2):
        start, end = _local_before(tr[i]), _local_after(tr[i + 1])
        y, st, en = start.year, md(start), md(end)
        if groups and groups[-1][2] == st and groups[-1][3] == en and groups[-1][1] == y - 1:
            groups[-1][1] = y
        else:
            groups.append([y, y, st, en])
    rows = []
    for first, last, st, en in groups:
        years = f"{first}" if first == last else f"{first}–{last}"
        rows.append(
            f'          <tr><td class="n">{years}</td><td>{st}至 {en}</td><td>{st} <span class="n">00:00–00:59</span>'
            f'</td><td>{en} <span class="n">23:00–23:59</span></td></tr>'
        )
    return "\n".join(rows)


def _deg_min(lon: float) -> str:
    total = round(lon * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]} {rest // 60}°{rest % 60:02d}′"


def build() -> tuple[dict[str, str], list[str]]:
    pin = load_pin()
    check_host_agrees(pin)
    tr = pin["transitions"]
    gaps = sum(1 for record in tr if record["to"] > record["from"])
    hour_folds = sum(1 for record in tr if record["from"] - record["to"] == 3600)
    summers = sum(1 for record in tr if (record["from"], record["to"]) == (28800, 32400)
                  and _utc(record).year >= 1946)
    # The example: the clock reading with the offset in force, and as if UTC+8.
    candidates = [EXAMPLE_LOCAL - timedelta(seconds=o) for o in sorted({r["to"] for r in tr})]
    right = [utc for utc in candidates if EXAMPLE_LOCAL - utc == timedelta(seconds=_offset_at(tr, utc))]
    if len(right) != 1:
        raise RuntimeError(f"the example clock time maps to {len(right)} UT instants")
    wrong = EXAMPLE_LOCAL - timedelta(hours=8)
    with swiss() as swe:
        def asc(utc: datetime) -> float:
            j = swe.julday(utc.year, utc.month, utc.day, utc.hour + utc.minute / 60)
            return swe.houses_ex(j, LAT, LON, b"W")[1][0]

        asc_right, asc_wrong = asc(right[0]), asc(wrong)
    quoted = [
        f"<b>{summers}</b><span>個實施日光節約時間的夏季",
        f"{zh(summers)}個撥快一小時的夏天",
        f"<b>{gaps}</b><span>個不存在的鐘點",
        f"<b>{hour_folds}</b><span>個出現兩次的鐘點",
        f'<td class="n">{right[0]:%H:%M}</td><td>{_deg_min(asc_right)}</td>',
        f'<td class="n">{wrong:%H:%M}</td><td class="diff">{_deg_min(asc_wrong)}</td>',
        f"上升點差了 {(asc_wrong - asc_right) % 360:.0f} 度",
    ]
    return {**_figures(pin), "dst-summers": _rows(pin)}, quoted


def elsewhere(fragment: str) -> dict[str, list[str]]:
    """The blog index repeats the article's §02 heading."""
    summers = re.search(r"<b>(\d+)</b><span>個實施日光節約時間的夏季", fragment)
    if summers is None:
        raise RuntimeError(f"{FRAGMENT}: the stat block no longer prints the number of summers")
    return {"blog": [f"{zh(int(summers.group(1)))}個撥快一小時的夏天"]}
