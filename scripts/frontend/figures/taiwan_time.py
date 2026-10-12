"""〈臺灣的時區與夏令時間〉: figure 1 (clock offset from UT, 1890–1985),
table 1 (the daylight-saving summers) and the synthetic 1975 example.

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

from ._common import SIGNS, indent, swiss, zh


FRAGMENT = "blog-taiwan-time-zone-history"
PIN = Path(__file__).with_name("taiwan_tz_2026d.json")
LAT, LON = 25.05306, 121.52639
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


def _figure(pin: dict) -> str:
    W, H = 640, 330
    L, R = 30, 610
    y0, y1 = 1890.0, 1985.0

    def yr(t: datetime) -> float:
        start = datetime(t.year, 1, 1)
        nxt = datetime(t.year + 1, 1, 1)
        return t.year + (t - start) / (nxt - start)

    X = lambda y: L + (R - L) * (y - y0) / (y1 - y0)  # noqa: E731
    tr = pin["transitions"]
    t1896, t1937, t1945 = (yr(_local_before(tr[i])) for i in range(3))
    dst = [(yr(_local_before(tr[i])), yr(_local_before(tr[i + 1]))) for i in range(3, len(tr), 2)]
    s = [
        f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="臺灣鐘面時間與世界時之差，1890 到 1985 年：1896 年以前為'
        "地方平時（比世界時快 8 小時 6 分），1896 年起為 UTC+8，1937 年 10 月 1 日起改為 UTC+9，1945 年 9 月 21 日改回 "
        "UTC+8；1946 到 1961 年每年夏天、以及 1974、1975、1979 年夏天實施日光節約時間，鐘面為 UTC+9。資料依 IANA "
        f'時區資料庫 {pin["tzdata"]} 版。">'
    ]
    s.append('<text class="t-faint" x="30" y="40">鐘面比世界時快</text>')
    BY, BH = 64, 70
    s.append(f'<rect class="f-hair" x="{X(y0):.1f}" y="{BY}" width="{X(t1896)-X(y0):.1f}" height="{BH}"/>')
    s.append(f'<rect class="f-ring2" x="{X(t1896):.1f}" y="{BY}" width="{X(t1937)-X(t1896):.1f}" height="{BH}"/>')
    s.append(f'<rect class="f-accent" x="{X(t1937):.1f}" y="{BY}" width="{X(t1945)-X(t1937):.1f}" height="{BH}"/>')
    s.append(f'<rect class="f-ring2" x="{X(t1945):.1f}" y="{BY}" width="{X(y1)-X(t1945):.1f}" height="{BH}"/>')
    s.append(f'<text class="t-paper" x="{X(t1896)+12:.1f}" y="{BY+30}">UTC+8</text>')
    s.append(f'<text class="t-paper" x="{X(t1896)+12:.1f}" y="{BY+56}">西部標準時</text>')
    s.append(f'<text class="t-paper t-mid" x="{(X(t1937)+X(t1945))/2:.1f}" y="{BY+30}">+9</text>')
    s.append(f'<text class="t-paper" x="{X(t1945)+12:.1f}" y="{BY+30}">UTC+8</text>')
    s.append(f'<text class="t-faint t-mid" x="{(X(y0)+X(t1896))/2:.1f}" y="{BY+42}">LMT</text>')
    DY, DH = 190, 40
    s.append(f'<line class="g-hair" x1="{L}" y1="{DY+DH}" x2="{R}" y2="{DY+DH}"/>')
    s.append(f'<text class="t-faint" x="30" y="{DY-12}">夏季日光節約時間（鐘面 UTC+9）</text>')
    for a, b in dst:
        s.append(f'<rect class="f-accent" x="{X(a):.2f}" y="{DY}" width="{max(X(b)-X(a),2):.2f}" height="{DH}"/>')
    s.append(f'<text class="t-accent t-mid" x="{(X(1946)+X(1962))/2:.1f}" y="{DY+DH+28}">1946–1961</text>')
    s.append(f'<text class="t-accent t-mid" x="{X(1977):.1f}" y="{DY+DH+28}">1974、75、79</text>')
    for y in range(1890, 1990, 10):
        s.append(f'<line class="g-dim" x1="{X(y):.1f}" y1="{H-40}" x2="{X(y):.1f}" y2="{H-32}"/>')
        s.append(f'<text class="t-faint t-mid" x="{X(y):.1f}" y="{H-8}">{y}</text>')
    s.append(f'<line class="g-ink" x1="{L}" y1="{H-40}" x2="{R}" y2="{H-40}"/>')
    s.append("</svg>")
    return indent("\n".join(s))


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
    return {"clock-offset": _figure(pin), "dst-summers": _rows(pin)}, quoted


def elsewhere(fragment: str) -> dict[str, list[str]]:
    """The blog index repeats the article's §02 heading."""
    summers = re.search(r"<b>(\d+)</b><span>個實施日光節約時間的夏季", fragment)
    if summers is None:
        raise RuntimeError(f"{FRAGMENT}: the stat block no longer prints the number of summers")
    return {"blog": [f"{zh(int(summers.group(1)))}個撥快一小時的夏天"]}
