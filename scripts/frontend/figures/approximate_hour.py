"""〈出生時間不確定怎麼排盤〉: figure 1 (one hour's five samples and the
bisection that closes each change down to its band, one variant per change),
figure 2 (the result page's birth-time summary for each hour from 12 to 18 of
one day, a switch of buttons) and the rows of the clock-change table.

Synthetic instants only: 2001-06-04, Taipei 25.05306N 121.52639E (UTC+8, no
daylight saving that year), sent the way the calculator sends a default form
(`options` empty, tropical) and read in the projection it reads (`page`); the
bisection midpoints are in the `detailed` projection only.  The clock-change
cases are St. John's 2005-10-29 23h and Lord Howe 2024-10-06 02h.

Every number is the product's: the samples, the midpoints and the bands come
from the sensitivity block, each midpoint's sign from the product's own chart
at that second, and the summary text from `birthTimeSummary` in the
calculator's view-model, run by Node on the response.  The bisection is
replayed from the signs alone and must land on the product's band through the
product's midpoints, and Swiss Ephemeris read directly must put each band's
two ends on the two sides of the sign boundary (or the station).
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import shutil
import subprocess
from typing import Any, Iterator

from . import _fx
from ._common import ROOT, SIGNS, TAIPEI as PLACE, backend_on_path, calc_ut, swiss


FRAGMENT = "blog-approximate-birth-hour"
LAT, LON = PLACE
TAIPEI = "Asia/Taipei"
DAY = (2001, 6, 4)
FEATURED = 15
HOURS = tuple(range(12, 19))
ST_JOHNS: dict[str, Any] = {"date": (2005, 10, 29), "hour": 23, "lat": 47.5615, "lon": -52.7126, "tz": "America/St_Johns"}
LORD_HOWE: dict[str, Any] = {"date": (2024, 10, 6), "hour": 2, "lat": -31.5553, "lon": 159.0821, "tz": "Australia/Lord_Howe"}
# A clock hour that never happened at all (the clock went from 02:00 to 03:00).
NEW_YORK: dict[str, Any] = {"date": (2005, 4, 3), "hour": 2, "lat": 40.7128, "lon": -74.006, "tz": "America/New_York"}
# The product's bisection bound (TRANSITION_RESOLUTION_SECONDS), read, not typed.
VIEW_MODEL = ROOT / "scripts" / "frontend" / "scripts" / "view-model.js"
CALCULATE = ROOT / "scripts" / "frontend" / "scripts" / "calculate.js"
# The headings the result page prints around the summary's lists (calculate.js
# renderBirthTimeSummary); held to that file so a renamed heading stops here.
HEADINGS = (("same", "不變的"), ("partial", "只比較了一部分"), ("unchecked", "沒有比較，只算了上面那一刻"))
CHANGED = "會變的"
ANGLE_NAMES = {"asc": "上升", "mc": "中天"}
VARIANTS_1 = (("asc", "上升換星座那一次"), ("mc", "中天換星座那一次"))
SAME_ARCSEC = 3.0


# --- the product ---------------------------------------------------------------

def _request(place: dict | None, date: tuple, hour: int, minute: int = 0, second: int = 0,
             precision: str = "approximate_hour", fold: int | None = None) -> dict:
    lat, lon, tz = (LAT, LON, TAIPEI) if place is None else (place["lat"], place["lon"], place["tz"])
    zone: dict[str, Any] = {"mode": "iana", "iana_name": tz}
    if fold is not None:
        zone["fold"] = fold
    return {"birth_time_precision": precision,
            "datetime": {"year": date[0], "month": date[1], "day": date[2],
                         "hour": hour, "minute": minute, "second": second},
            "location": {"latitude": lat, "longitude": lon},
            "timezone": zone, "computation_mode": {"zodiac": "tropical"}, "options": {}}


@contextmanager
def _service() -> Iterator[Any]:
    """`post(payload, projection, expected)` against the real application in process."""
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        def post(payload: dict, projection: str = "page", expected: int = 200) -> dict:
            response = client.post(f"/api/chart?projection={projection}", json=payload)
            if response.status_code != expected:
                raise RuntimeError(f"chart request answered {response.status_code}: {response.text[:300]}")
            return response.json()

        yield post


def _summaries(responses: list[dict]) -> list[dict]:
    """The result page's summary of each response, built by the calculator's own view-model."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to build the result page's summary")
    script = ("const VM=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d)"
              ".on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(s).map(r=>VM.birthTimeSummary(r)))));")
    done = subprocess.run([node, "-e", script, str(VIEW_MODEL)], input=json.dumps(responses), cwd=ROOT,
                          capture_output=True, text=True, check=False, timeout=60)
    if done.returncode != 0:
        raise RuntimeError("the view-model could not summarise: " + done.stderr.strip())
    out = json.loads(done.stdout)
    if any(summary is None for summary in out):
        raise RuntimeError("the view-model returned no summary for an approximate hour")
    return out


def _clock(local: str) -> str:
    """'2001-06-04T15:15:56' or '2001-06-04 15:15:56.000' -> '15:15:56'."""
    return local.replace("T", " ").split(" ")[1].split(".")[0]


def _hms(offset: int, hour: int) -> str:
    return f"{hour:02d}:{offset // 60:02d}:{offset % 60:02d}"


def _offset(clock: str, hour: int) -> int:
    h, m, s = (int(v) for v in clock.split(":"))
    if h != hour:
        raise RuntimeError(f"{clock} is not in hour {hour}")
    return m * 60 + s


def _angle(chart: dict, key: str) -> tuple[int, str]:
    sign, dms, _ = chart["astronomical_data"]["angles"]["sign_positions"][key]
    return sign, dms


def _chains(post, sensitivity: dict, hour: int) -> dict[str, dict]:
    """Each angle's change replayed from the product's signs at the samples and midpoints."""
    resolution = _resolution()
    samples = [_offset(_clock(p["input_local_time"]), hour) for p in sensitivity["probes"]]
    midpoints = {_offset(_clock(p["input_local_time"]), hour) for p in sensitivity["refinement_probes"]}
    charts: dict[int, dict] = {}

    def chart(offset: int) -> dict:
        if offset not in charts:
            charts[offset] = post(_request(None, DAY, hour, offset // 60, offset % 60, "exact"))
        return charts[offset]

    out = {}
    for key, _ in VARIANTS_1:
        path = f"astronomical_data.angles.sign_positions.{key}"
        (band,) = [t for t in sensitivity["transitions"] if path in t["changed_paths"]]
        lower, upper = (_offset(_clock(band[k]), hour) for k in ("lower_bound_local", "upper_bound_local"))
        left = max(s for s in samples if s <= lower)
        right = min(s for s in samples if s >= upper)
        if samples.index(right) != samples.index(left) + 1:
            raise RuntimeError(f"{key}: the band is not between two adjacent samples")
        signs = {s: _angle(chart(s), key)[0] for s in samples}
        steps = []
        lo, hi = left, right
        start = signs[left]
        while hi - lo > resolution:
            mid = (lo + hi) // 2
            sign = _angle(chart(mid), key)[0]
            keep = "right" if sign == start else "left"
            steps.append({"lo": lo, "hi": hi, "mid": mid, "sign": sign, "keep": keep})
            lo, hi = (mid, hi) if keep == "right" else (lo, mid)
        if (lo, hi) != (lower, upper):
            raise RuntimeError(f"{key}: replayed bisection ends at {(lo, hi)}, the product says {(lower, upper)}")
        if not {step["mid"] for step in steps} <= midpoints:
            raise RuntimeError(f"{key}: a replayed midpoint is not among the product's refinement probes")
        out[key] = {"samples": samples, "signs": signs, "left": left, "right": right, "steps": steps,
                    "lower": lower, "upper": upper, "before": _angle(chart(lower), key),
                    "after": _angle(chart(upper), key), "width": band["resolution_seconds"]}
    return out


def _resolution() -> int:
    with backend_on_path():
        from app.core.birth_time_sensitivity import TRANSITION_RESOLUTION_SECONDS
    return TRANSITION_RESOLUTION_SECONDS


def _check_against_swiss(chains: dict, hour: int, mercury: dict) -> None:
    """Each band's two ends on the two sides of the boundary, read from Swiss directly (UT = Taipei − 8 h)."""
    with swiss() as swe:
        def jd(offset: int, at_hour: int = hour) -> float:
            return swe.julday(*DAY, at_hour - 8 + offset / 3600)

        for key, chain in chains.items():
            index = 0 if key == "asc" else 1
            for end, (sign, dms) in (("lower", chain["before"]), ("upper", chain["after"])):
                value = swe.houses_ex(jd(chain[end]), LAT, LON, b"W")[1][index]
                if int(value // 30) != sign:
                    raise RuntimeError(f"{key} at the band's {end} end: Swiss says {SIGNS[int(value // 30)]}")
                product = sign * 30 + _degrees(dms)
                if abs((value - product + 180) % 360 - 180) * 3600 > SAME_ARCSEC:
                    raise RuntimeError(f"{key} at the band's {end} end: Swiss {value} != product {product}")
        speeds = [calc_ut(swe, jd(mercury[end], mercury["hour"]), swe.MERCURY, swe.FLG_SWIEPH | swe.FLG_SPEED)[3]
                  for end in ("lower", "upper")]
        if not (speeds[0] > 0 > speeds[1]):
            raise RuntimeError(f"Mercury's speed at the band's ends is {speeds}, not a station to retrograde")


def _degrees(dms: str) -> float:
    d, rest = dms.split("°")
    m, rest = rest.split("′")
    return int(d) + int(m) / 60 + float(rest.rstrip("″")) / 3600


def _dm(dms: str) -> str:
    """'29°57′33.19″' -> '29°57′' (whole arcminutes, truncated: the sign is what matters)."""
    return dms.split("′")[0] + "′"


# --- figure 1: the bisection ladder ----------------------------------------------

def _ladder(layout: str, fid: str, chains: dict, hour: int, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (110.0, 820.0) if wide else (18.0, 322.0)
    axis_y = 118.0 if wide else 132.0
    row0 = axis_y + (92 if wide else 96)
    rh = 66.0 if wide else 74.0
    rows = len(next(iter(chains.values()))["steps"]) + 1
    H = row0 + rows * rh + (40 if wide else 62)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    day = bound.num(f"{DAY[0]} 年 {DAY[1]} 月 {DAY[2]} 日 {hour} 點")
    out.append(_fx.text(x0 if wide else 18, 36 if wide else 32, f"{day}，臺北（合成範例）", "fx-t"))
    if not wide:
        out.append(_fx.text(18, 54, "每一列放大上一列留下的那一半", "fx-t fx-small fx-dim"))
    span = 3600

    def hx(offset: float) -> float:
        return x0 + (x1 - x0) * offset / span

    out.append(_fx.line(x0, axis_y, x1, axis_y, "fx-axis"))
    for key, _ in VARIANTS_1:
        chain = chains[key]
        body = []
        name = ANGLE_NAMES[key]
        if wide:
            body.append(_fx.text(24, axis_y - 26, name, "fx-t"))
        else:
            body.append(_fx.text(18, axis_y - 50, f"{name}的星座，在取樣點：", "fx-t fx-small"))
        # the segment whose two ends differ
        body.append(_fx.line(hx(chain["left"]), axis_y, hx(chain["right"]), axis_y, "fx-step"))
        for i, s in enumerate(chain["samples"]):
            body.append(_fx.text(hx(s), axis_y - (16 if wide else 14), SIGNS[chain["signs"][s]],
                                 "fx-t fx-small", _anchor(i, len(chain["samples"]))))
        # funnel from the segment to the first row
        top = row0 - (24 if wide else 30)
        body.append(_fx.line(hx(chain["left"]), axis_y + 6, x0, top, "fx-leader"))
        body.append(_fx.line(hx(chain["right"]), axis_y + 6, x1, top, "fx-leader"))
        for k, step in enumerate(chain["steps"]):
            body.append(_rung(wide, x0, x1, row0 + k * rh, rh, k, step, key, hour, bound,
                              last=k == len(chain["steps"]) - 1))
        body.append(_band_row(wide, x0, x1, row0 + len(chain["steps"]) * rh, chain, key, hour, bound))
        out.append(_fx.variant_group(key, VARIANTS_1[0][0], "".join(body)))
    for i, s in enumerate(next(iter(chains.values()))["samples"]):
        representative = s == 1800
        out.append(_fx.circle(hx(s), axis_y, 6 if wide else 5, "fx-mk" if representative else "fx-mk-on"))
        out.append(_fx.text(hx(s), axis_y + (24 if wide else 22), bound.num(_hms(s, hour) if s % 60 else _hms(s, hour)[:5]),
                            "fx-t fx-small fx-num", _anchor(i, 5)))
    if wide:
        out.append(_fx.text(24, axis_y + 24, "取樣點", "fx-t fx-small fx-dim"))
        out.append(_fx.text(x1, 36, "空心點是代表性時刻", "fx-t fx-small fx-dim", "end"))
        out.append(_fx.text(24, H - 22, "每一列把上一列留下的那一半放大到全寬，各列的比例尺不同。",
                            "fx-t fx-small fx-dim"))
    else:
        out.append(_fx.text(18, H - 38, "空心點是代表性時刻。", "fx-t fx-small fx-dim"))
        out.append(_fx.text(18, H - 18, "各列的比例尺不同。", "fx-t fx-small fx-dim"))
    out.append("</svg>")
    return "".join(out)


def _anchor(i: int, n: int) -> str:
    return "start" if i == 0 else "end" if i == n - 1 else "middle"


def _rung(wide: bool, x0: float, x1: float, y: float, rh: float, k: int, step: dict, key: str, hour: int,
          bound: _fx.Bound, last: bool) -> str:
    cx = (x0 + x1) / 2
    bar = y + (8 if wide else 22)
    lo, mid, hi = (bound.num(_hms(step[v], hour)) for v in ("lo", "mid", "hi"))
    sign = SIGNS[step["sign"]]
    label = bound.label(f"第 {k + 1} 次")
    aria = f"{label}：{lo} 與 {hi} 的中點 {mid}，{ANGLE_NAMES[key]}在{sign}"
    out = [f'<g class="fx-row" data-fx-key="r{k + 1}" tabindex="0" aria-label="{aria}">',
           _fx.rect(8, y - (14 if wide else 2), (x1 + 52 if wide else 324) - 8, rh - 4, "fx-hit")]
    kept = (cx, x1) if step["keep"] == "right" else (x0, cx)
    dropped = (x0, cx) if step["keep"] == "right" else (cx, x1)
    out.append(_fx.line(*_pair(dropped, bar), "fx-hair"))
    out.append(_fx.line(*_pair(kept, bar), "fx-step"))
    for x in (x0, cx, x1):
        out.append(_fx.line(x, bar - 6, x, bar + 6, "fx-axis"))
    out.append(_fx.circle(cx, bar, 5 if wide else 4.5, "fx-mk-on"))
    if wide:
        out.append(_fx.text(24, bar + 6, label, "fx-t fx-small"))
    else:
        out.append(_fx.text(x0, bar - 12, label, "fx-t fx-small"))
    out.append(_fx.text(cx, bar - 12, sign, "fx-t fx-small", "middle"))
    out.append(_fx.text(x0, bar + 22, lo, "fx-t fx-small fx-num fx-dim"))
    out.append(_fx.text(cx, bar + 22, mid, "fx-t fx-small fx-num", "middle"))
    out.append(_fx.text(x1, bar + 22, hi, "fx-t fx-small fx-num fx-dim", "end"))
    nxt = y + rh + (8 if wide else 22)
    out.append(_fx.line(kept[0], bar + 6, x0, nxt - 6, "fx-leader"))
    out.append(_fx.line(kept[1], bar + 6, x1, nxt - 6, "fx-leader"))
    out.append("</g>")
    return "".join(out)


def _pair(span: tuple[float, float], y: float) -> tuple[float, float, float, float]:
    return span[0], y, span[1], y


def _band_row(wide: bool, x0: float, x1: float, y: float, chain: dict, key: str, hour: int,
              bound: _fx.Bound) -> str:
    bar = y + (8 if wide else 22)
    lo, hi = bound.num(_hms(chain["lower"], hour)), bound.num(_hms(chain["upper"], hour))
    width = bound.num(f"{chain['width']} 秒")
    before, after = SIGNS[chain["before"][0]], SIGNS[chain["after"][0]]
    aria = f"找到的那一段：{lo} 到 {hi}，寬 {width}，{ANGLE_NAMES[key]}從{before}換到{after}"
    out = [f'<g class="fx-row" data-fx-key="band" tabindex="0" aria-label="{aria}">',
           _fx.rect(8, y - (14 if wide else 2), (x1 + 52 if wide else 324) - 8, 64 if wide else 72, "fx-hit"),
           _fx.rect(x0, bar - 7, x1 - x0, 14, "fx-fill-cross"),
           _fx.rect(x0, bar - 7, x1 - x0, 14, "fx-inset-frame")]
    if wide:
        out.append(_fx.text(24, bar + 6, "找到", "fx-t fx-small"))
        out.append(_fx.text((x0 + x1) / 2, bar - 14, f"這 {width}之內，{ANGLE_NAMES[key]}從{before}換到{after}",
                            "fx-t fx-small", "middle"))
    else:
        out.append(_fx.text(x0, bar - 14, f"這 {width}之內換：{before}→{after}", "fx-t fx-small"))
    out.append(_fx.text(x0, bar + 26, lo, "fx-t fx-small fx-num"))
    out.append(_fx.text(x1, bar + 26, hi, "fx-t fx-small fx-num", "end"))
    out.append("</g>")
    return "".join(out)


def _ladder_notes(chains: dict, hour: int, bound: _fx.Bound) -> list[_fx.Note]:
    notes = []
    for key, _ in VARIANTS_1:
        chain = chains[key]
        name = ANGLE_NAMES[key]
        for k, step in enumerate(chain["steps"]):
            lo, mid, hi = (bound.num(_hms(step[v], hour)) for v in ("lo", "mid", "hi"))
            half = (f"{bound.num(_hms(step['mid'], hour))}–{hi}" if step["keep"] == "right"
                    else f"{lo}–{bound.num(_hms(step['mid'], hour))}")
            side = "後半" if step["keep"] == "right" else "前半"
            notes.append(_fx.Note(f"r{k + 1}", key,
                                  f"{bound.label(f'第 {k + 1} 次')}對半：取 {lo} 與 {hi} 的中點 {mid} 重算，{name}在"
                                  f"{SIGNS[step['sign']]}座，所以改變發生在{side}（{half}）。"))
        lo, hi = bound.num(_hms(chain["lower"], hour)), bound.num(_hms(chain["upper"], hour))
        width = bound.num(f"{chain['width']} 秒")
        notes.append(_fx.Note("band", key,
                              f"區間寬到 {bound.num(str(_resolution()))} 秒以內就停：本站回報 {lo} 到 {hi}（寬 {width}），"
                              f"{name}在這一段之內從{SIGNS[chain['before'][0]]}換到{SIGNS[chain['after'][0]]}，"
                              "至少換了一次。"))
    return notes


def _ladder_table(chains: dict, hour: int, bound: _fx.Bound) -> str:
    rows = []
    for key, label in VARIANTS_1:
        chain = chains[key]
        for k, step in enumerate(chain["steps"]):
            rows.append(f'<tr data-fx-key="r{k + 1}" data-fx-variant="{key}"><th scope="row">{ANGLE_NAMES[key]}</th>'
                        f'<td>{bound.label(f"第 {k + 1} 次")}</td>'
                        f'<td class="n">{bound.num(_hms(step["lo"], hour))}–'
                        f'{bound.num(_hms(step["hi"], hour))}</td>'
                        f'<td class="n">{bound.num(_hms(step["mid"], hour))}</td><td>{SIGNS[step["sign"]]}</td></tr>')
        rows.append(f'<tr data-fx-key="band" data-fx-variant="{key}"><th scope="row">{ANGLE_NAMES[key]}</th>'
                    f'<td>找到</td><td class="n">{bound.num(_hms(chain["lower"], hour))}–'
                    f'{bound.num(_hms(chain["upper"], hour))}</td><td class="n">—</td>'
                    f'<td>{SIGNS[chain["before"][0]]}→{SIGNS[chain["after"][0]]}</td></tr>')
    return ('<details class="fx-data"><summary>圖中的數字（表格）</summary><div class="ar-scroll">'
            '<table class="ar-table fx-table"><thead><tr><th scope="col">哪一個</th><th scope="col">第幾次</th>'
            '<th scope="col">區間</th><th scope="col">中點</th><th scope="col">中點的星座</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></details>')


# --- figure 2: the summary for each hour -----------------------------------------

def _when_label(transition: dict) -> str:
    lower, upper = _clock(transition["lower_bound_local"])[:5], _clock(transition["upper_bound_local"])[:5]
    return lower if lower == upper else f"{lower}–{upper}"


def _hour_axis(layout: str, fid: str, hours: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (60.0, 820.0) if wide else (18.0, 322.0)
    axis_y = 128.0 if wide else 128.0
    H = 192.0 if wide else 192.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]

    def hx(offset: float) -> float:
        return x0 + (x1 - x0) * offset / 3600

    for step, (hour, item) in enumerate(hours.items()):
        sens = item["page"]["birth_time_sensitivity"]
        body = [_fx.text(x0, 36 if wide else 32,
                         f"{bound.num(f'{hour} 點')}：{bound.num(f'{hour:02d}:00')} 到 {bound.num(f'{hour:02d}:59:59')}",
                         "fx-t")]
        body.append(_fx.line(x0, axis_y, x1, axis_y, "fx-axis"))
        probes = [_offset(_clock(p["input_local_time"]), hour) for p in sens["probes"]]
        representative = _offset(_clock(sens["representative_local_time"]), hour)
        tiers: list[float] = []
        for t in sens["transitions"]:
            lower = _offset(_clock(t["lower_bound_local"]), hour)
            upper = _offset(_clock(t["upper_bound_local"]), hour)
            x = hx((lower + upper) / 2)
            tier = 1 if tiers and abs(x - tiers[-1]) < (130 if wide else 96) and len(tiers) % 2 == 1 else 0
            tiers.append(x)
            ly = axis_y - (30 if wide else 28) - tier * (24 if wide else 22)
            body.append(_fx.rect(x - 2, axis_y - 14, 4, 28, "fx-fill-solid"))
            body.append(_fx.line(x, axis_y - 16, x, ly + 6, "fx-leader"))
            body.append(_fx.text(x, ly, "約 " + bound.num(_when_label(t)), "fx-t fx-small fx-num fx-key", "middle"))
        if not sens["transitions"]:
            body.append(_fx.text((x0 + x1) / 2, axis_y - 30, "取樣點之間沒有看到改變", "fx-t fx-small fx-dim", "middle"))
        for i, s in enumerate(probes):
            body.append(_fx.circle(hx(s), axis_y, 6 if wide else 5, "fx-mk" if s == representative else "fx-mk-on"))
            if wide or i in (0, len(probes) - 1, probes.index(representative)):
                body.append(_fx.text(hx(s), axis_y + 26, bound.num(_hms(s, hour) if s % 60 else _hms(s, hour)[:5]),
                                     "fx-t fx-small fx-num", _anchor(i, len(probes))))
        body.append(_fx.text(x1, H - 18, "空心點是代表性時刻；黑色短條是本站夾出的改變區段",
                             "fx-t fx-small fx-dim", "end") if wide
                    else _fx.text(x0, H - 18, "空心點：代表性時刻；黑條：改變區段", "fx-t fx-small fx-dim"))
        out.append(_fx.step_group(step, HOURS.index(FEATURED), "".join(body)))
    out.append("</svg>")
    return "".join(out)


def _callout(step: int, hour: int, summary: dict, bound: _fx.Bound) -> str:
    """The result page's summary block, the same sentences in the same order."""
    from html import escape

    def p(text: str, cls: str = "") -> str:
        return f'<p{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}>{escape(bound.num(text))}</p>'

    parts = [f'<div class="ar-key fx-callout{"" if hour == FEATURED else " fx-off"}" data-fx-step="{step}">',
             f'<span class="ar-k">結果頁上的摘要（{escape(bound.num(f"{hour} 點"))}，原文）</span>',
             f"<p><b>{escape(summary['title'])}</b></p>", p(summary["lead"]), p(summary["intro"])]
    if summary["changes"]:
        items = "".join(f"<li>{escape(bound.num(c['what']))}：{escape(bound.num(c['when']))}</li>"
                        for c in summary["changes"])
        parts.append(f"<p><b>{CHANGED}</b></p><ul>{items}</ul>")
    for field, label in HEADINGS:
        if summary[field]:
            parts.append(f"<p><b>{label}：</b>{escape(bound.num('、'.join(summary[field])))}。</p>")
    parts.append(p(summary["caveat"]))
    parts.append("</div>")
    return "".join(parts)


def _hours_table(hours: dict, bound: _fx.Bound) -> str:
    from html import escape

    rows = []
    for hour, item in hours.items():
        summary = item["summary"]
        changes = "；".join(f"{c['what']}：{c['when']}" for c in summary["changes"]) or "—"
        rows.append(f'<tr><th scope="row">{bound.num(f"{hour} 點")}</th><td>{escape(bound.num(summary["lead"]))}</td>'
                    f"<td>{escape(bound.num(changes))}</td></tr>")
    return ('<details class="fx-data"><summary>七個鐘點的摘要（表格）</summary><div class="ar-scroll">'
            '<table class="ar-table fx-table"><thead><tr><th scope="col">鐘點</th><th scope="col">第一句</th>'
            f'<th scope="col">會變的與約幾點</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>')


# --- the clock-change table --------------------------------------------------------

def _clock_rows(cases: list[dict]) -> str:
    rows = []
    for case in cases:
        sens = case["page"]["birth_time_sensitivity"]
        clocks = [_clock(p["input_local_time"]) for p in sens["probes"]]
        probes = "、".join(c[:5] if c.endswith(":00") else c for c in clocks)
        skipped = sens["probe_coverage"]["skipped"]
        if skipped:
            gone = "、".join(_hms(s["offset_seconds"], case["hour"])[:5] for s in skipped)
            probes += f"（{gone} 這個時區當天沒有，略過）"
        summary = case["summary"]
        change = summary["changes"][0] if summary["changes"] else None
        what = f"{change['what']}：{change['when']}" if change else summary["lead"]
        rows.append(f'          <tr><td>{case["label"]}</td><td class="n">{len(sens["probes"])}</td>'
                    f'<td>{probes}</td><td>{what}</td></tr>')
    return "\n".join(rows)


# --- build ----------------------------------------------------------------------

def _data() -> dict:
    with _service() as post:
        hours = {h: {"page": post(_request(None, DAY, h))} for h in HOURS}
        detailed = post(_request(None, DAY, FEATURED), "detailed")["birth_time_sensitivity"]
        chains = _chains(post, detailed, FEATURED)
        # the hours without folds and the clock-change cases
        sj = ST_JOHNS
        refused = post(_request(sj, sj["date"], sj["hour"]), expected=422)
        if refused["detail"]["code"] != "ambiguous_local_time_choice_required":
            raise RuntimeError(f"St. John's without a fold answered {refused['detail']['code']}")
        ny = NEW_YORK
        gone = post(_request(ny, ny["date"], ny["hour"]), expected=422)
        if gone["detail"]["code"] != "nonexistent_local_time":
            raise RuntimeError(f"New York's missing hour answered {gone['detail']['code']}")
        cases = [
            {"label": "聖約翰斯 23 點，選第一次", "hour": sj["hour"],
             "page": post(_request(sj, sj["date"], sj["hour"], fold=0))},
            {"label": "聖約翰斯 23 點，選第二次", "hour": sj["hour"],
             "page": post(_request(sj, sj["date"], sj["hour"], fold=1))},
            {"label": "豪勳爵島 2 點", "hour": LORD_HOWE["hour"],
             "page": post(_request(LORD_HOWE, LORD_HOWE["date"], LORD_HOWE["hour"]))},
        ]
    summaries = _summaries([hours[h]["page"] for h in HOURS] + [c["page"] for c in cases])
    for h, summary in zip(HOURS, summaries):
        hours[h]["summary"] = summary
    for case, summary in zip(cases, summaries[len(HOURS):]):
        case["summary"] = summary
    source = CALCULATE.read_text(encoding="utf-8")
    for _, label in HEADINGS + (("changes", CHANGED),):
        if f'"{label}"' not in source:
            raise RuntimeError(f"calculate.js no longer heads a summary list with {label!r}")
    # Mercury's station in hour 13
    (mercury,) = [t for t in hours[13]["page"]["birth_time_sensitivity"]["transitions"]
                  if t["changed_paths"] == ["astronomical_data.bodies[mercury].motion_sign"]]
    station = {"hour": 13, "lower": _offset(_clock(mercury["lower_bound_local"]), 13),
               "upper": _offset(_clock(mercury["upper_bound_local"]), 13)}
    _check_against_swiss(chains, FEATURED, station)
    with backend_on_path():
        from app.core.time_utils import repeated_wall_clock_stretches
        from app.schemas import TimezoneInput
        import datetime as dtmod

        year, month, day = sj["date"]
        (repeat,) = repeated_wall_clock_stretches(TimezoneInput(mode="iana", iana_name=sj["tz"]),
                                                  dtmod.datetime(year, month, day, sj["hour"]))
    return {"hours": hours, "chains": chains, "cases": cases, "station": station, "repeat": repeat,
            "refused": refused["detail"]["message"], "gone": gone["detail"]["message"]}


def build() -> tuple[dict[str, str], list[str]]:
    d = _data()
    chains, hours = d["chains"], d["hours"]

    b1 = _fx.Bound()
    for _, label in VARIANTS_1:
        b1.label(label)
    asc = chains["asc"]
    ladder = _fx.figure(
        fid="fig-bisect",
        title=f"{FEATURED} 點那一小時的五個取樣點，以及把改變夾到 15 秒以內的每一次對半",
        caption=(f"<b>{b1.label('圖 1')}</b>上面一排是本站在這一小時取的五個時刻，每個點上寫著那一刻的星座；"
                 f"兩端不同的那一段（粗線）往下逐列對半：每一列取中點重算，留下兩端星座不同的那一半（粗線），"
                 f"放大成下一列。按鈕切換這一小時裡的兩次改變。時刻、星座與區間都是本站計算服務的實際回應。"),
        wide=_ladder("fx-wide", "fig-bisect", chains, FEATURED, b1),
        narrow=_ladder("fx-narrow", "fig-bisect", chains, FEATURED, b1),
        notes=_ladder_notes(chains, FEATURED, b1),
        idle="用 Tab 鍵移到某一列，或用滑鼠指著它，這裡會說明那一次對半取了哪個中點、留下哪一半。",
        variants=VARIANTS_1, switch_label="切換是哪一次改變",
        table=_ladder_table(chains, FEATURED, b1),
    )
    b2 = _fx.Bound()
    callouts = "".join(_callout(i, h, hours[h]["summary"], b2) for i, h in enumerate(HOURS))
    hour_notes = [_fx.Note(None, None, f"{b2.num(f'{h} 點')}：{b2.num(hours[h]['summary']['lead'])}", step=i)
                  for i, h in enumerate(HOURS)]
    summary_figure = _fx.figure(
        fid="fig-summary",
        title="同一天 12 點到 18 點，每個鐘點的取樣點、改變區段與結果頁摘要",
        caption=(f"<b>{b2.label('圖 2')}</b>同一天（{b2.num(f'{DAY[0]} 年 {DAY[1]} 月 {DAY[2]} 日')}，臺北，計算頁預設選項），"
                 f"從 {b2.num('12')} 點到 {b2.num('18')} 點每個鐘點各用「只知道約略小時」算一次。拖拉條選一個鐘點："
                 "上面是那一小時的取樣點與本站夾出的改變區段，下面是結果頁「出生時間不確定：哪些結果會變」那一塊的原文，"
                 "由結果頁自己的程式對同一份回應產生。"),
        wide=_hour_axis("fx-wide", "fig-summary", hours, b2),
        narrow=_hour_axis("fx-narrow", "fig-summary", hours, b2),
        notes=hour_notes, idle="拖拉條選一個鐘點，這裡會寫出那一小時結果頁摘要的第一句。", steps=len(HOURS), default_step=HOURS.index(FEATURED),
        scrub_label=f"選一個鐘點（{b2.num('12')} 點到 {b2.num('18')} 點）",
        table=callouts + _hours_table(hours, b2),
    )
    for markup, bound in ((ladder, b1), (summary_figure, b2)):
        found = _fx.problems(markup, bound)
        if found:
            raise RuntimeError("figure check: " + "; ".join(found))
    # The callouts sit outside the table the component checks: hold their digits to the bound set too.
    import re
    stray = {t for t in re.findall(r"\d+(?:\.\d+)?", re.sub(r"<[^>]+>", "", callouts))} - b2.tokens()
    if stray:
        raise RuntimeError(f"figure 2: unbound numbers in the summary text: {sorted(stray)}")

    station, repeat = d["station"], d["repeat"]
    mc = chains["mc"]
    sj0, sj1, lh = d["cases"]
    sj1_probes = [_clock(p["input_local_time"]) for p in sj1["page"]["birth_time_sensitivity"]["probes"]]
    sj_gap = [t for t in sj1["page"]["birth_time_sensitivity"]["transitions"] if t["semantics"].endswith("not_bisected")]
    if len(sj_gap) != 1:
        raise RuntimeError("St. John's, second occurrence: expected one change across the clock's jump")
    quoted = [
        f"{_hms(asc['left'], FEATURED)[:5]} 與 {_hms(asc['right'], FEATURED)[:5]}",
        f"{_hms(asc['lower'], FEATURED)} 到 {_hms(asc['upper'], FEATURED)}",
        f"{_hms(mc['lower'], FEATURED)} 到 {_hms(mc['upper'], FEATURED)} 之間從"
        f"{SIGNS[mc['before'][0]]}換到{SIGNS[mc['after'][0]]}",
        f"寬 {asc['width']} 秒",
        f"天秤 {_dm(asc['before'][1])}",
        f"天蠍 {_dm(asc['after'][1])}",
        *(f"中點 {_hms(step['mid'], FEATURED)}" for step in asc["steps"]),
        f"{_hms(station['lower'], 13)} 到 {_hms(station['upper'], 13)}",
        f"{repeat[0]:%H:%M} 到 {repeat[1]:%H:%M}",
        f"取 {len(sj1_probes)} 個時刻",
        f"{_clock(sj_gap[0]['lower_bound_local'])} 與 {_clock(sj_gap[0]['upper_bound_local'])}",
        f"取 {len(lh['page']['birth_time_sensitivity']['probes'])} 個時刻",
        d["gone"],
    ]
    return {
        "fx-defs": _fx.defs(()),
        "bisect": ladder,
        "summary": summary_figure,
        "clock-rows": _clock_rows(d["cases"]),
    }, quoted
