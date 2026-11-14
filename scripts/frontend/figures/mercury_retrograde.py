"""〈水星逆行，回到原典〉: figure 1 (Mercury's longitude difference from the Sun, October-November 2026, with the bands of
the three traditions), figures 2 and 3 (the night of the inferior conjunction: each tradition's spans on one time axis,
and Mercury's path past the Sun's disc), tables 1-5 and the numbers the prose quotes.

Stations, conjunctions and crossings are roots found here with Swiss Ephemeris: a station is where the geocentric speed
in longitude changes sign, a conjunction where the longitude difference from the Sun does, a crossing where that
difference reaches a tradition's limit.  The limits are the product's own table (the solar-phase module's `limits`) and
Lilly's mean daily motion.  Every instant is printed as the whole minute it lies in, as the calculator prints its turns.
The two synthetic instants are posted to the product in process; the build stops unless its answers agree with the
roots found here.
"""
from __future__ import annotations

import datetime as dt
from html import escape
import math
import statistics

from . import _fx
from ._common import SIGNS, TAIPEI, calc_ut, product_charts, swiss

FRAGMENT = "blog-mercury-retrograde-2026"
TAIPEI_OFFSET_HOURS = 8
YEAR = 2026
SPAN = (1900, 2100)
MOMENTS = ({"year": 2026, "month": 11, "day": 4, "hour": 22, "minute": 24, "second": 0},
    {"year": 2026, "month": 11, "day": 13, "hour": 12, "minute": 0, "second": 0})
PROFILES = (("lilly", "lilly_1647_p113_v1", "Lilly 1647 p.113"), ("hellenistic", "hellenistic_15_v1", "希臘化"),
    ("biruni", "biruni_wright_v1", "al-Bīrūnī"))
BANDS = (("cazimi", "日輪內"), ("combust", "焦傷"), ("under_beams", "在光束下"))
BAND_NAMES = {"cazimi": "日輪內", "combust": "焦傷", "under_beams": "在光束下", "clear": "離開光束",
              "accompanying_high_latitude": "伴隨太陽"}
BAND_CLASS = {"cazimi": "fx-fill-solid", "combust": "fx-fill-cross", "under_beams": "fx-fill-hatch"}
ELEMENTS = ("火", "土", "風", "水")
COURSE_ZH = {"swift": "行速快", "slow": "行速慢", "equal_to_mean_at_source_precision": "等於平均"}
DIRECTION_ZH = {"direct": "順行", "retrograde": "逆行"}
STATION_ZH = {"stationary_before_retrograde": "停滯（第一次：快要轉為逆行）",
    "stationary_before_direct": "停滯（第二次：快要轉回順行）",
    "stationary_after_turning_retrograde": "停滯（第一次：剛轉為逆行）",
    "stationary_after_turning_direct": "停滯（第二次：剛轉回順行）", "not_stationary": "沒有停滯"}
SIDE_ZH = {"oriental": "晨星（東出）", "occidental": "昏星（西入）", "on_the_sun": "與太陽同一黃經"}
P115_ZH = {"listed_as_accidental_fortitude": "列為偶然強", "listed_as_accidental_debility": "列為偶然弱", "not_listed": "不列"}
CROSSING_ZH = {"emerging": "升出光束", "sinking": "隱入光束"}
# Roots: a bisection to about a millisecond; coarse scans step half a day (crossings) or a day (statistics).
TOLERANCE_DAYS = 1e-8
# Swiss and the product agree to about a thousandth of an arcsecond, crossing roots to a fraction of a second.
SAME_ARCSEC = 0.05
SAME_SECONDS = 1.0

# --- time and angle labels -------------------------------------------------------

def _utc(swe, jd: float) -> tuple[int, int, int, int, int, float]:
    y, m, d, h, mi, s = swe.jdut1_to_utc(jd, swe.GREG_CAL)
    return int(y), int(m), int(d), int(h), int(mi), float(s)

# A whole-minute instant made from a clock reading comes back a few microseconds early through the floating-point day;
# a nudge far below the roots' millisecond keeps it in its own minute.
NUDGE_DAYS = 2e-8

def _local(swe, jd: float) -> tuple[int, int, int, int, int]:
    y, m, d, h, mi, _s = _utc(swe, jd + TAIPEI_OFFSET_HOURS / 24 + NUDGE_DAYS)
    return y, m, d, h, mi

# Clock labels truncate to the minute (the rule, not rounding): a root at 19:10:59.6 prints 19:10.
def _when(swe, jd: float, year: bool = False) -> str:
    y, m, d, h, mi = _local(swe, jd)
    return (f"{y} 年 " if year else "") + f"{m} 月 {d} 日 {h:02d}:{mi:02d}"

def _date(swe, jd: float, year: bool = False) -> str:
    y, m, d, _h, _mi = _local(swe, jd)
    return (f"{y} 年 " if year else "") + f"{m} 月 {d} 日"

def _slash(swe, jd: float) -> str:
    _y, m, d, _h, _mi = _local(swe, jd)
    return f"{m}/{d}"

def _dm(degrees: float) -> str:
    units = math.floor(degrees * 60 + 1e-9)
    return f"{units // 60}°{units % 60:02d}′"

def _sign_dm(lon: float) -> str:
    units = math.floor(lon * 60 + 1e-9) % (360 * 60)
    sign, rest = divmod(units, 30 * 60)
    return f"{SIGNS[sign]} {rest // 60}°{rest % 60:02d}′"

def _element(lon: float) -> str:
    return ELEMENTS[int(lon // 30) % 4]

def _signed(degrees: float) -> str:
    return ("−" if degrees < 0 else "+") + _dm(abs(degrees))

def _arcmin(degrees: float) -> str:
    return f"{round(abs(degrees) * 60)}′"

# --- roots -----------------------------------------------------------------------

def _bisect(fn, a: float, b: float) -> float:
    fa = fn(a)
    while b - a > TOLERANCE_DAYS:
        m = (a + b) / 2
        fm = fn(m)
        if (fm < 0) == (fa < 0):
            a, fa = m, fm
        else:
            b = m
    return (a + b) / 2

def _roots(fn, start: float, end: float, step: float) -> list[float]:
    out, t, ft = [], start, fn(start)
    while t < end:
        u = min(t + step, end)
        fu = fn(u)
        if (ft < 0) != (fu < 0):
            out.append(_bisect(fn, t, u))
        t, ft = u, fu
    return out

class Sky:

    def __init__(self, swe) -> None:
        self.swe = swe

    def mercury(self, jd: float) -> tuple:
        return calc_ut(self.swe, jd, self.swe.MERCURY)

    def speed(self, jd: float) -> float:
        return self.mercury(jd)[3]

    def difference(self, jd: float) -> float:
        sun = calc_ut(self.swe, jd, self.swe.SUN)[0]
        return (self.mercury(jd)[0] - sun + 180.0) % 360.0 - 180.0

    def separation(self, jd: float) -> float:
        m, s = self.mercury(jd), calc_ut(self.swe, jd, self.swe.SUN)
        la, lb, ba, bb = map(math.radians, (m[0], s[0], m[1], s[1]))
        c = math.sin(ba) * math.sin(bb) + math.cos(ba) * math.cos(bb) * math.cos(la - lb)
        return math.degrees(math.acos(max(-1.0, min(1.0, c))))

    def sun_semidiameter(self, jd: float) -> float:
        return self.swe.pheno_ut(jd, self.swe.SUN)[3] / 2

    def stations(self, start: float, end: float, step: float = 0.5) -> list[tuple[str, float]]:
        found = _roots(self.speed, start, end, step)
        return [("R" if self.speed(jd - 1e-3) > 0 else "D", jd) for jd in found]

    def conjunctions(self, start: float, end: float, step: float = 0.5) -> list[tuple[str, float]]:
        out = []
        for jd in _roots(self.difference, start, end, step):
            if abs(self.difference(jd)) < 1:  # not the jump at ±180°
                out.append(("inferior" if self.speed(jd) < 0 else "superior", jd))
        return out

# --- the product's limits ----------------------------------------------------------

def _limit(per_band: dict, band: str, motion: str) -> float | None:
    value = per_band[band]
    if value is None:
        return None
    return (value[motion] if "direct" in value else value)["degrees"]

def _edges(limits: dict, side: str, motion: str) -> dict[str, float | None]:
    per_band = limits["mercury"][side]
    return {band: _limit(per_band, band, motion) for band, _ in BANDS}

def _band(limits: dict, difference: float, speed: float) -> str:
    """The band Mercury is in: the innermost limit it is within, edges included (the instants figure 1 names are far
    from every edge, so inclusiveness never decides them)."""
    edges = _edges(limits, "evening" if difference > 0 else "morning", "retrograde" if speed < 0 else "direct")
    band = "clear"
    for name in ("under_beams", "combust", "cazimi"):
        edge = edges[name]
        if edge is not None and abs(difference) <= edge:
            band = name
    return band

def _crossings(sky: Sky, limits: dict, band: str, start: float, end: float) -> list[float]:
    """When Mercury reaches the limit of `band` (which may depend on side and motion): roots of |difference| - limit,
    kept only where the limit holds on both sides (a jump of the limit itself is not a crossing)."""
    def gap(jd: float) -> float:
        d, v = sky.difference(jd), sky.speed(jd)
        edge = _edges(limits, "evening" if d > 0 else "morning", "retrograde" if v < 0 else "direct")[band]
        return abs(d) - (edge if edge is not None else -1.0)
    out = []
    for jd in _roots(gap, start, end, 0.25):
        if abs(gap(jd)) * 3600 > 0.01:
            continue
        out.append(jd)
    return out

# --- the computation ---------------------------------------------------------------

def _answers() -> list[dict]:
    with product_charts() as post:
        return [post({"datetime": moment, "location": {"latitude": TAIPEI[0], "longitude": TAIPEI[1]},
            "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
            "options": {"include_solar_phase": True, "include_motion_states": True}}) for moment in MOMENTS]

def compute() -> dict:
    answers = _answers()
    phase = answers[0]["derived_methods"]["solar_phase"]
    limits = {key: phase["profile_results"][profile]["limits"] for key, profile, _ in PROFILES}
    mean = answers[0]["derived_methods"]["motion_states"]["profile_results"]["lilly_1647_v1"]["means"]["mercury"]
    with swiss() as swe:
        sky = Sky(swe)
        def jd(y: int, m: int, d: int, quarter: int = 0) -> float:
            # Each instant is anchored to the UTC clock on its own; stepping whole days in UT1 drifts off the civil
            # midnight by UT1-UTC's change and the date labels then fall on the day before.
            utc = dt.datetime(y, m, d) + dt.timedelta(hours=6 * quarter - TAIPEI_OFFSET_HOURS)
            return swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour, 0, 0.0, swe.GREG_CAL)[1]
        year_start, year_end = jd(YEAR, 1, 1), jd(YEAR + 1, 1, 1)
        turns = sky.stations(year_start - 40, year_end + 40)
        conj = sky.conjunctions(year_start - 120, year_end + 120)
        retrogrades = []
        for (k1, a), (k2, b) in zip(turns, turns[1:]):
            if k1 == "R" and k2 == "D" and year_start <= a < year_end:
                inferior = [c for kind, c in conj if kind == "inferior" and a < c < b]
                if len(inferior) != 1:
                    raise RuntimeError("a retrograde without exactly one inferior conjunction")
                retrogrades.append({"start": a, "end": b, "conjunction": inferior[0]})
        if len(retrogrades) != 3:
            raise RuntimeError(f"{YEAR} has {len(retrogrades)} retrogrades, the article says three")
        this = retrogrades[-1]
        r, d, c = this["start"], this["end"], this["conjunction"]
        superior_before = max(x for kind, x in conj if kind == "superior" and x < r)
        superior_after = min(x for kind, x in conj if kind == "superior" and x > d)
        # Every crossing of every tradition's limit, from well before the first station to well after the second.
        window = (r - 20, d + 20)
        crossings = {key: {band: _crossings(sky, limits[key], band, *window) for band, _ in BANDS}
                     for key, _, _ in PROFILES}
        swift = _roots(lambda t: abs(sky.speed(t)) - mean["degrees_per_day"], *window, 0.25)
        lilly_beams_sup = _crossings(sky, limits["lilly"], "under_beams", superior_before - 30, superior_before + 30)
        t0, t1 = jd(YEAR, 10, 8), jd(YEAR, 11, 29)
        curve = []
        steps = round((t1 - t0) * 4)
        for i in range(steps + 1):
            t = jd(YEAR, 10, 8, i)
            curve.append((t, sky.difference(t), sky.speed(t)))
        s0, s1 = swe.julday(SPAN[0], 1, 1, 0), swe.julday(SPAN[1], 1, 1, 0)
        long_turns = sky.stations(s0, s1, 1.0)
        long_conj = sky.conjunctions(s0, s1, 1.0)
        inferiors = [x for kind, x in long_conj if kind == "inferior"]
        superiors = [x for kind, x in long_conj if kind == "superior"]
        pairs = [(a, b) for (k1, a), (k2, b) in zip(long_turns, long_turns[1:]) if k1 == "R" and k2 == "D"]
        if not all(any(a < x < b for a, b in pairs) for x in inferiors if pairs[0][0] < x < pairs[-1][1]):
            raise RuntimeError("an inferior conjunction outside every retrograde")
        if any(any(a < x < b for a, b in pairs) for x in superiors):
            raise RuntimeError("a superior conjunction inside a retrograde")
        synodic = [b - a for a, b in zip(inferiors, inferiors[1:])]
        durations = [b - a for a, b in pairs]
        # This retrograde's own entry in the long scan, so the rank counts below leave it out by index, not by luck of
        # two separately found roots comparing equal.
        this_index = min(range(len(pairs)), key=lambda i: abs(pairs[i][0] - r))
        if abs(pairs[this_index][0] - r) > 0.01:
            raise RuntimeError("this retrograde is missing from the long scan")
        arcs = [(sky.mercury(a)[0] - sky.mercury(b)[0]) % 360 for a, b in pairs]
        sun_lon = lambda t: calc_ut(swe, t, swe.SUN)[0]  # noqa: E731
        steps3 = [(sun_lon(inferiors[i + 3]) - sun_lon(inferiors[i]) + 180) % 360 - 180
                  for i in range(len(inferiors) - 3)]
        apart = [(sun_lon(b) - sun_lon(a)) % 360 for a, b in zip(inferiors, inferiors[1:])]
        days3 = [inferiors[i + 3] - inferiors[i] for i in range(len(inferiors) - 3)]
        by_year: dict[int, list[tuple[float, float]]] = {}
        for a, b in pairs:
            by_year.setdefault(_local(swe, a)[0], []).append((a, b))
        whole_years = [y for y in by_year if SPAN[0] <= y < SPAN[1]]
        one_element = sorted(y for y in whole_years
                             if len({_element(sky.mercury(t)[0]) for pair in by_year[y] for t in pair}) == 1)
        four = sorted(y for y in whole_years if len(by_year[y]) == 4)
        # Transits: the next inferior conjunction whose least separation is within the Sun's apparent radius.
        def minimum(fn, lo: float, hi: float) -> float:
            for _ in range(60):
                m1, m2 = lo + (hi - lo) / 3, hi - (hi - lo) / 3
                if fn(m1) < fn(m2):
                    hi = m2
                else:
                    lo = m1
            return (lo + hi) / 2
        def least(c: float) -> float:
            return minimum(sky.separation, c - 0.5, c + 0.5)
        next_transit = None
        for x in inferiors:
            if x > d:
                t = least(x)
                if sky.separation(t) < sky.sun_semidiameter(t):
                    next_transit = x
                    break
        if next_transit is None:
            raise RuntimeError("no transit of Mercury before the end of the span")
        closest = least(c)
        # The western elongation after this conjunction: the most negative longitude difference.
        elongation = minimum(sky.difference, c, superior_after)
        combust_ends = [x for x in crossings["lilly"]["combust"] if r < x < d]
        if len(combust_ends) != 2:
            raise RuntimeError("Lilly's combustion does not have two edges inside the retrograde")
        scorpio = {int(lon // 30) for x in combust_ends for lon in (sky.mercury(x)[0], calc_ut(swe, x, swe.SUN)[0])}
        if scorpio != {7}:
            raise RuntimeError("the night's section says the Sun and Mercury stay in Scorpio through Lilly's combustion")
        helio = [calc_ut(swe, year_start + i, swe.MERCURY, swe.FLG_SWIEPH | swe.FLG_HELCTR)[2] for i in range(366)]
        widest = max(abs(sky.difference(year_start + i / 24)) for i in range(366 * 24))
        before_year = max(y for y in one_element if y < YEAR)
        before_element = _element(sky.mercury(by_year[before_year][0][0])[0])
        drift_rows = []
        for y in range(YEAR - 2, YEAR + 3):
            for a, b in by_year[y]:
                drift_rows.append({"start": a, "end": b, "lon_start": sky.mercury(a)[0], "lon_end": sky.mercury(b)[0]})
        out = {
            "answers": answers,
            "limits": limits,
            "mean": mean,
            "retrogrades": [{**x, "lon_start": sky.mercury(x["start"])[0], "lon_end": sky.mercury(x["end"])[0],
                             "lat_conj": sky.mercury(x["conjunction"])[1]} for x in retrogrades],
            "this": {**this, "lon_start": sky.mercury(r)[0], "lon_end": sky.mercury(d)[0],
                     "lat_conj": sky.mercury(c)[1], "speed_conj": sky.speed(c),
                     "dist_conj": sky.mercury(c)[2], "lon_conj": sky.mercury(c)[0]},
            "superior_before": {"jd": superior_before, "speed": sky.speed(superior_before),
                                "dist": sky.mercury(superior_before)[2], "lat": sky.mercury(superior_before)[1],
                                "lon": sky.mercury(superior_before)[0]},
            "superior_after": superior_after,
            "crossings": crossings,
            "swift": swift,
            "lilly_beams_sup": lilly_beams_sup,
            "curve": curve,
            "stats": {
                "synodic": synodic, "durations": durations, "arcs": arcs, "steps3": steps3, "apart": apart,
                "days3": days3, "years": whole_years, "one_element": one_element, "four": four,
                "this_index": this_index, "this_duration": d - r, "this_arc": (sky.mercury(r)[0] - sky.mercury(d)[0]) % 360,
            },
            "transit": {"next": next_transit, "closest": sky.separation(closest), "closest_at": closest,
                        "radius": sky.sun_semidiameter(closest)},
            "elongation": {"at": elongation, "degrees": abs(sky.difference(elongation))},
            "helio": (min(helio), max(helio)),
            "widest": widest,
            "before_element": before_element,
            "drift": drift_rows,
        }
        _check_product(sky, out)
        out["labels"] = _labels(swe, out)
    return out

def _check_product(sky: Sky, data: dict) -> None:
    """The product's answers against the roots found here: the longitude difference at each instant, each crossing and
    each turn it lists."""
    swe = sky.swe
    crossings = {key: sorted(x for band in data["crossings"][key].values() for x in band) for key, _, _ in PROFILES}
    turns = [data["this"]["start"], data["this"]["end"]]
    for answer in data["answers"]:
        at = answer["astronomical_data"]["time"]["jd_ut"]
        phase = answer["derived_methods"]["solar_phase"]
        row = next(x for x in phase["rows"] if x["key"] == "mercury")
        if abs(row["longitude_difference_degrees"] - sky.difference(at)) * 3600 > SAME_ARCSEC:
            raise RuntimeError(f"the product's difference {row['longitude_difference_degrees']} != Swiss {sky.difference(at)}")
        for key, profile, _ in PROFILES:
            for item in phase["profile_results"][profile]["beam_crossings_within_7_days"]["mercury"]:
                if not any(abs(item["instant"]["jd_ut"] - x) * 86400 < SAME_SECONDS for x in crossings[key]):
                    raise RuntimeError(f"{profile}: the product's crossing {item['instant']} is not one found here")
        motion = answer["derived_methods"]["motion_states"]
        for item in motion["stations_within_window"]["mercury"]:
            printed = item["instant"]["local_time"][-5:]
            if not any(f"{_local(swe, x)[3]:02d}:{_local(swe, x)[4]:02d}" == printed for x in turns):
                raise RuntimeError(f"the product's turn {item['instant']} is not a minute found here")

def _labels(swe, data: dict) -> dict:
    marks = {}
    def add(jd: float) -> None:
        marks[jd] = {"when": _when(swe, jd), "date": _date(swe, jd), "slash": _slash(swe, jd),
                     "year_when": _when(swe, jd, True), "year_date": _date(swe, jd, True),
                     "short": f"{_slash(swe, jd)} {_local(swe, jd)[3]:02d}:{_local(swe, jd)[4]:02d}",
                     "utc": f"UTC {_utc(swe, jd)[3]:02d}:{_utc(swe, jd)[4]:02d}"}
    for x in data["retrogrades"]:
        for k in ("start", "end", "conjunction"):
            add(x[k])
    for key in data["crossings"]:
        for band in data["crossings"][key].values():
            for x in band:
                add(x)
    for x in data["swift"] + data["lilly_beams_sup"]:
        add(x)
    add(data["superior_before"]["jd"])
    add(data["superior_after"])
    add(data["transit"]["next"])
    add(data["transit"]["closest_at"])
    add(data["elongation"]["at"])
    add(data["this"]["start"] - 1)
    add(data["this"]["end"] - 1)
    for i, (t, _, _) in enumerate(data["curve"]):
        marks.setdefault(t, {"slash": _slash(swe, t), "date": _date(swe, t)})
        # The grid index is an oracle independent of the floating-point clock: point i is Taipei 0h of Oct 8 + i/4 day.
        day = dt.date(YEAR, 10, 8) + dt.timedelta(days=i // 4)
        if marks[t]["slash"] != f"{day.month}/{day.day}":
            raise RuntimeError(f"curve point {i} labels {marks[t]['slash']}, its grid date is {day}")
    for row in data["drift"]:
        add(row["start"])
        add(row["end"])
    return marks

# --- tables ------------------------------------------------------------------------

def _year_rows(data: dict) -> str:
    L = data["labels"]
    rows = []
    for x in data["retrogrades"]:
        rows.append(
            f'          <tr><td class="n">{L[x["start"]]["when"]}</td><td>{_sign_dm(x["lon_start"])}</td>'
            f'<td class="n">{L[x["end"]]["when"]}</td><td>{_sign_dm(x["lon_end"])}</td>'
            f'<td class="n">{x["end"] - x["start"]:.1f} 天</td>'
            f'<td class="n">{_dm((x["lon_start"] - x["lon_end"]) % 360)}</td>'
            f'<td class="n">{L[x["conjunction"]]["when"]}</td>'
            f'<td class="n">{"北" if x["lat_conj"] >= 0 else "南"} {_dm(abs(x["lat_conj"]))}</td></tr>')
    return "\n".join(rows)

def _events(data: dict) -> list[tuple[float, str, str]]:
    this, cr, L = data["this"], data["crossings"], data["labels"]
    r, d, c = this["start"], this["end"], this["conjunction"]
    lo, hi = r - 14, d + 9
    out = [(r - 1, "進入 Lilly 的停滯（轉向前 1 天）", "Lilly p.76"),
        (r, f"第一次停滯，轉為逆行（{_sign_dm(this['lon_start'])}）", "星曆"),
        (c, "與太陽正合（下合）：由昏星（西入）轉為晨星（東出）", "星曆；Lilly p.114"),
        (d - 1, "進入 Lilly 的停滯（轉向前 1 天）", "Lilly p.76"),
        (d, f"第二次停滯，轉回順行（{_sign_dm(this['lon_end'])}）", "星曆")]
    words = {
        "lilly": {"under_beams": ("進入光束（17°）", "離開光束（17°）"), "combust": ("焦傷開始（8°30′）", "焦傷結束（8°30′）"),
                  "cazimi": ("日輪內開始（17′）", "日輪內結束（17′）")},
        "hellenistic": {"under_beams": ("進入 15° 線", "離開 15° 線")},
        "biruni": {"under_beams": ("進入光束（12°）", "離開光束（12°）"), "combust": ("焦傷開始（6°）", "焦傷結束（6°）"),
                   "cazimi": ("日輪內開始（16′）", "日輪內結束（16′）")},
    }
    who = {"lilly": "Lilly p.113", "hellenistic": "希臘化 15°", "biruni": "al-Bīrūnī §481–484"}
    for key, bands in words.items():
        for band, (enter, leave) in bands.items():
            found = [x for x in cr[key][band] if lo < x < hi]
            if len(found) != 2:
                raise RuntimeError(f"{key} {band}: {len(found)} crossings in the window, the table expects two")
            out += [(found[0], enter, who[key]), (found[1], leave, who[key])]
    mean_text = data["mean"]["text"]
    swift = [x for x in data["swift"] if lo < x < hi]
    if len(swift) != 4:
        raise RuntimeError(f"{len(swift)} swift/slow changes in the window, the table expects four")
    out += [(swift[0], f"行速轉慢（每天走得比平均 {mean_text} 少）", "Lilly p.168"),
            (swift[1], f"逆行而行速轉快（每天退得比 {mean_text} 多）", "Lilly p.168、p.178"),
            (swift[2], f"行速轉慢（每天退得比 {mean_text} 少）", "Lilly p.168、p.178"),
            (swift[3], f"順行而行速轉快（每天走得比 {mean_text} 多）", "Lilly p.168")]
    return sorted(out)

def _event_rows(data: dict) -> str:
    L = data["labels"]
    rows = []
    for jd, what, whose in _events(data):
        rows.append(f'          <tr><td class="n">{L[jd]["when"]}</td><td>{escape(what)}</td><td>{escape(whose)}</td></tr>')
    return "\n".join(rows)

def _conjunction_rows(data: dict) -> str:
    L, this, sup = data["labels"], data["this"], data["superior_before"]
    beams = data["lilly_beams_sup"]
    inner = [x for x in data["crossings"]["lilly"]["under_beams"] if this["start"] - 10 < x < this["end"] + 10]
    cells = [
        ("時刻", L[sup["jd"]]["year_when"], L[this["conjunction"]]["year_when"]),
        ("水星在哪裡", _sign_dm(sup["lon"]), _sign_dm(this["lon_conj"])),
        ("順行或逆行", "順行", "逆行"),
        ("一天走多少", _dm(abs(sup["speed"])), _dm(abs(this["speed_conj"]))),
        ("離地球（天文單位）", f"{sup['dist']:.2f}", f"{this['dist_conj']:.2f}"),
        ("黃緯", f"{'北' if sup['lat'] >= 0 else '南'} {_dm(abs(sup['lat']))}",
         f"{'北' if this['lat_conj'] >= 0 else '南'} {_dm(abs(this['lat_conj']))}"),
        ("在 Lilly 的 17° 以內", f"{beams[1] - beams[0]:.1f} 天", f"{inner[1] - inner[0]:.1f} 天"),
    ]
    return "\n".join(f'          <tr><th scope="row">{a}</th><td class="n">{b}</td><td class="n">{c}</td></tr>'
                     for a, b, c in cells)

def _night_rows(data: dict, pick) -> str:
    L = data["labels"]
    span = lambda found: f"{L[found[0]]['short']} 到 {L[found[1]]['short']}"  # noqa: E731
    return "\n".join((
        f'          <tr><th scope="row">Lilly p.113（黃經 17′）</th><td>日輪內</td><td class="n">{span(pick("lilly", "cazimi"))}</td></tr>',
        f'          <tr><th scope="row">al-Bīrūnī §481（黃經不到 16′）</th><td>日輪內（samīm）</td><td class="n">{span(pick("biruni", "cazimi"))}</td></tr>',
        f'          <tr><th scope="row">希臘化（15°，轉引）</th><td>在光束下，沒有日輪內這一帶</td><td class="n">{span(pick("hellenistic", "under_beams"))}</td></tr>',
        '          <tr><th scope="row">al-Qabīṣī、Bonatti（黃經與黃緯都在 16′ 內）</th><td>不算日輪內</td><td>這次沒有任何時刻符合</td></tr>'))

def _drift_rows(data: dict) -> str:
    L = data["labels"]
    rows = []
    for x in data["drift"]:
        a, b = x["lon_start"], x["lon_end"]
        same = _element(a) == _element(b)
        rows.append(
            f'          <tr><td class="n">{L[x["start"]]["year_date"]}</td><td>{_sign_dm(a)}（{_element(a)}象）</td>'
            f'<td class="n">{L[x["end"]]["date"]}</td><td>{_sign_dm(b)}（{_element(b)}象）</td>'
            f'<td>{"同一象" if same else "跨兩象"}</td></tr>')
    return "\n".join(rows)

def _demo_rows(data: dict) -> str:
    cols = []
    for answer in data["answers"]:
        motion = next(x for x in answer["derived_methods"]["motion_states"]["rows"] if x["key"] == "mercury")
        phase = answer["derived_methods"]["solar_phase"]
        row = next(x for x in phase["rows"] if x["key"] == "mercury")
        turns = answer["derived_methods"]["motion_states"]["stations_within_window"]["mercury"]
        crossing_lines = []
        for key, profile, label in PROFILES:
            items = phase["profile_results"][profile]["beam_crossings_within_7_days"]["mercury"]
            if not items:
                crossing_lines.append(f"{label}：沒有")
            for item in items:
                crossing_lines.append(f"{label}：{CROSSING_ZH[item['direction']]}，{item['instant']['local_time'][5:16].replace('-', '/', 1)}")
        station = STATION_ZH[motion["station"]["state"]]
        if motion["station"]["turn"]:
            station += f"（轉向在 {motion['station']['turn']['instant']['local_time'][5:].replace('-', '/', 1)}）"
        p115 = motion["lilly_p115"]
        cols.append({
            "direction": DIRECTION_ZH[motion["direction"]],
            "speed": f"{motion['daily_motion_text']}（平均 {motion['mean_motion_text']}）",
            "course": COURSE_ZH[motion["course"]] + ("；比的是每天退的度數" if motion["direction"] == "retrograde" else ""),
            "station": station,
            "turns": "、".join(f"{t['instant']['local_time'][5:].replace('-', '/', 1)}" for t in turns),
            "side": SIDE_ZH[motion["relative_to_sun"]],
            "p115": f"行速：{P115_ZH[p115['course']]}；東出西入：{P115_ZH[p115['relative_to_sun']]}",
            "difference": f"{_signed(row['longitude_difference_degrees'])}（{row['longitude_difference_text']}）",
            "latitude": f"{'北' if row['ecliptic_latitude_degrees'] >= 0 else '南'} {_dm(abs(row['ecliptic_latitude_degrees']))}",
            "disc": "是" if row["within_solar_disc"] else "否",
            **{key: BAND_NAMES[phase["profile_results"][profile]["bands"]["mercury"]] for key, profile, _ in PROFILES},
            "crossings": "；".join(crossing_lines),
        })
    names = (("direction", "順行或逆行"), ("speed", "一天走多少"), ("course", "行速（Lilly 1647）"),
             ("station", "停滯（Lilly 的天數）"), ("turns", "前後 15 天內的轉向"), ("side", "東出西入"),
             ("p115", "Lilly p.115 把它列在哪一邊"), ("difference", "與太陽的黃經差"), ("latitude", "黃緯"),
             ("disc", "中心落在太陽圓面內"), ("lilly", "距離帶：Lilly 1647 p.113"), ("hellenistic", "距離帶：希臘化"),
             ("biruni", "距離帶：al-Bīrūnī"), ("crossings", "前後 7 天內跨過光束界線"))
    return "\n".join(f'          <tr><th scope="row">{label}</th><td>{escape(cols[0][key])}</td><td>{escape(cols[1][key])}</td></tr>'
                     for key, label in names)

# --- figure 1 --------------------------------------------------------------------

Y_RANGE = 27.0
SWITCH_LABEL = "切換三套界線"
IDLE = "用 Tab 鍵移到圖上的圓點，或用滑鼠指著它，這裡會寫出那一刻的時間、位置與距離帶。"
KEYS = (("station-r", "第一次停滯"), ("conj", "下合"), ("station-d", "第二次停滯"))

def _segments(data: dict, key: str, band: str, sign: int) -> list[tuple[float, float, float]]:
    """(start, end, limit) runs over the curve's samples on one side of the Sun; a run ends where the limit changes."""
    side = "evening" if sign > 0 else "morning"
    out: list[list[float]] = []
    curve = data["curve"]
    for i, (t, _, v) in enumerate(curve):
        edge = _edges(data["limits"][key], side, "retrograde" if v < 0 else "direct")[band]
        end = curve[i + 1][0] if i + 1 < len(curve) else t
        if edge is None:
            continue
        if out and out[-1][2] == edge and out[-1][1] == t:
            out[-1][1] = end
        else:
            out.append([t, end, edge])
    return [(start, end, edge) for start, end, edge in out]

def _plot(layout: str, fid: str, data: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (96.0, 860.0) if wide else (44.0, 330.0)
    top, bottom = (64.0, 424.0) if wide else (60.0, 380.0)
    curve = data["curve"]
    t0, t1 = curve[0][0], curve[-1][0]
    x = lambda t: x0 + (t - t0) / (t1 - t0) * (x1 - x0)  # noqa: E731
    y = lambda d: top + (Y_RANGE - d) / (2 * Y_RANGE) * (bottom - top)  # noqa: E731
    H = bottom + (92 if wide else 88)
    L = data["labels"]
    this = data["this"]
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(x0, top - 30, "↑ 太陽東側（昏星）", "fx-t fx-small fx-rub"))
    out.append(f'<clipPath id="{fid}-{layout}-plot">{_fx.rect(x0, top, x1 - x0, bottom - top)}</clipPath>')
    plot = [f'<g clip-path="url(#{fid}-{layout}-plot)">', _fx.rect(x0, top, x1 - x0, bottom - top, "fx-track")]
    for key, _, _ in PROFILES:
        body = []
        for band in ("under_beams", "combust", "cazimi"):
            for sign in (1, -1):
                for a, b, edge in _segments(data, key, band, sign):
                    ya, yb = sorted((y(0), y(sign * edge)))
                    body.append(_fx.rect(x(a), ya, x(b) - x(a), max(yb - ya, 1.2), BAND_CLASS[band]))
        plot.append(_fx.variant_group(key, PROFILES[0][0], "".join(body)))
    plot.append(_fx.line(x0, y(0), x1, y(0), "fx-sunline"))
    plot.append(_fx.line(x(this["start"]), top, x(this["start"]), bottom, "fx-dash"))
    plot.append(_fx.line(x(this["end"]), top, x(this["end"]), bottom, "fx-dash"))
    pts = " ".join(f"{_fx.f(x(t))},{_fx.f(y(d))}" for t, d, _ in curve)
    plot.append(f'<polyline points="{pts}" class="fx-curve"/>')
    plot.append("</g>")
    out += plot
    out.append(_fx.rect(x0, top, x1 - x0, bottom - top, "fx-inset-frame"))
    out.append(_fx.text(x1 - 8, bottom - 10, "↓ 太陽西側（晨星）", "fx-t fx-small fx-rub fx-key", "end"))
    for key, _, _ in PROFILES:
        labels = []
        early = data["curve"][0]
        edges = _edges(data["limits"][key], "morning", "retrograde" if early[2] < 0 else "direct")
        lx = x0 + 8
        prev = 0.0
        for band, name in BANDS:
            band_edge = edges[band]
            if band_edge is None:
                continue
            if band == "cazimi":
                labels.append(_fx.text(lx, y(0) - 6, f"{name}（cazimi，細線）", "fx-t fx-small fx-key"))
            else:
                mid = (prev + band_edge) / 2
                gloss = "under the beams，" if band == "under_beams" else ""
                labels.append(_fx.text(lx, y(-mid) + 5, f"{name}（{gloss}{bound.num(_limit_text(band_edge))}）", "fx-t fx-small fx-key"))
            prev = band_edge
        out.append(_fx.variant_group(key, PROFILES[0][0], "".join(labels)))
    for v in (-24, -16, -8, 0, 8, 16, 24):
        out.append(_fx.line(x0 - 5, y(v), x0, y(v), "fx-axis"))
        out.append(_fx.text(x0 - 8, y(v) + 5, bound.scale(f"{'−' if v < 0 else ''}{abs(v)}°"), "fx-t fx-small fx-num", "end"))
    bar = bottom + 10
    out.append(_fx.rect(x(this["start"]), bar, x(this["end"]) - x(this["start"]), 6, "fx-fill-solid"))
    out.append(_fx.text((x(this["start"]) + x(this["end"])) / 2, bar + 24,
                        f"逆行 {bound.num(f'{this['end'] - this['start']:.1f}')} 天", "fx-t fx-small fx-key", "middle"))
    axis = bar + 34
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    every = 7 if wide else 14
    for i in range(0, round(t1 - t0) + 1, every):
        t = curve[4 * i][0]
        out.append(_fx.line(x(t), axis, x(t), axis + 5, "fx-axis"))
        anchor = "start" if i == 0 else "middle"
        out.append(_fx.text(x(t), axis + 22, bound.scale(L[t]["slash"]), "fx-t fx-small fx-num", anchor))
    points = {"station-r": (this["start"], data["curve_at"](this["start"])), "conj": (this["conjunction"], 0.0),
        "station-d": (this["end"], data["curve_at"](this["end"]))}
    for key, name in KEYS:
        t, d = points[key]
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" ' f'aria-label="{name}，{L[t]["when"]}">')
        out.append(_fx.circle(x(t), y(d), 18, "fx-hit"))
        out.append(_fx.circle(x(t), y(d), 7 if wide else 6, "fx-mk"))
        out.append(_fx.text(x(t), top - 10, name if wide or key == "conj" else name[-2:], "fx-t fx-small", "middle"))
        out.append("</g>")
    out.append("</svg>")
    if axis + 22 > H:
        raise RuntimeError("figure 1 outgrew its drawing")
    return "".join(out)

def _limit_text(edge: float | None) -> str:
    assert edge is not None
    minutes = round(edge * 60)
    if minutes < 60:
        return f"{minutes}′"
    return f"{minutes // 60}°" + (f"{minutes % 60:02d}′" if minutes % 60 else "")

def _note(data: dict, key: str, variant: str, label: str, bound: _fx.Bound) -> str:
    L, this = data["labels"], data["this"]
    t = {"station-r": this["start"], "conj": this["conjunction"], "station-d": this["end"]}[key]
    d = data["curve_at"](t) if key != "conj" else 0.0
    v = data["speed_at"](t)
    band = _band(data["limits"][variant], d, v)
    if key == "conj":
        head = (f"{bound.num(L[t]['when'])}，水星與太陽正合（下合），黃緯南 {bound.num(_dm(abs(this['lat_conj'])))}；" "此後由昏星轉為晨星。")
    else:
        turn = "轉為逆行" if key == "station-r" else "轉回順行"
        lon = this["lon_start"] if key == "station-r" else this["lon_end"]
        head = (f"{bound.num(L[t]['when'])}，水星在{bound.num(_sign_dm(lon))}{turn}，"
                f"在太陽{'東' if d > 0 else '西'}側 {bound.num(_dm(abs(d)))}。")
    return head + f"照{' ' if label[0].isascii() else ''}{label}：{BAND_NAMES[band]}。"

def _figure(data: dict) -> str:
    bound = _fx.Bound()
    for _, _, label in PROFILES:
        bound.label(label)
    L, this = data["labels"], data["this"]
    notes = [_fx.Note(key, variant, _note(data, key, variant, label, bound))
             for variant, _, label in PROFILES for key, _ in KEYS]
    rows = []
    for t, d, v in data["curve"][::8]:
        rows.append(f'<tr><th scope="row">{bound.num(L[t]["date"])}</th><td class="n">{bound.num(_signed(d))}</td>'
                    f'<td>{DIRECTION_ZH["retrograde" if v < 0 else "direct"]}</td></tr>')
    table = _fx.data_table(("日期（臺北 0 時）", "黃經差（水星減太陽）", "順逆"), rows)
    first, last = data["curve"][0][0], data["curve"][-1][0]
    caption = (f"<b>{bound.label('圖 1')}</b>從 {bound.num(L[first]['date'])}到 {bound.num(L[last]['date'])}，"
               "水星減太陽的黃經差（曲線；上方是太陽東側、昏星，下方是西側、晨星）。底色是距離帶：實心是日輪內、"
               "交叉線是焦傷、單線是在光束下，界線依所選那一套，al-Bīrūnī 的焦傷界線還依水星順行或逆行而變；按鈕切換三套。"
               "兩條直虛線是兩次停滯，底下的黑條是逆行的那一段。曲線在逆行的正中間穿過零，那一刻就是下合。")
    return _fx.figure(fid="fig-mr-curve", hero=True,
        title="2026 年 10 月到 11 月，水星與太陽的黃經差，以及三套界線的距離帶", caption=caption,
        art=_fx.FigureArt.drawn(_plot, "fig-mr-curve", data, bound, notes=notes, idle=IDLE),
        controls=_fx.FigureControls(variants=tuple((k, label) for k, _, label in PROFILES), switch_label=SWITCH_LABEL),
        table=table, bound=bound)

# --- figures 2 and 3: the night of November 4 ------------------------------------------

# The plate of figure 3: arcminutes drawn on each side of the Sun, north of it and south of it.
DISC_REACH = 32.0
DISC_NORTH, DISC_SOUTH = 20.0, 30.0
DISC_SCALE = {"fx-wide": 8.4, "fx-narrow": 4.7}
PATH_STEP_DAYS = 10 / 1440
# The longitude and latitude limit the al-Qabīṣī and Bonatti rows of the night's table name (al-Qabīṣī ch. 3; Bonatti).
BOTH_COORDINATES_ARCMIN = 16.0
DISC_SCRUB = "選這一晚的時刻"
DEFAULT_DISC_STEP = 2  # the conjunction
DISC_IDLE = "拖動滑桿，這裡會寫出那一刻水星與太陽的距離和 Lilly 的分類。"
# The drawing plots Δλ·cos β against Δβ; on this small a patch it must agree with the great-circle separation.
SAME_PLANE_ARCSEC = 0.5

def _arc(degrees: float) -> str:
    """To the nearest arcsecond, so a limit's own instant prints the limit: 「17′00″」."""
    total = round(abs(degrees) * 3600)
    return f"{total // 60}′{total % 60:02d}″"

def _short(swe, jd: float) -> str:
    y, m, d, h, mi = _local(swe, jd)
    return f"{m}/{d} {h:02d}:{mi:02d}"

def _clock(swe, jd: float) -> str:
    _y, _m, _d, h, mi = _local(swe, jd)
    return f"{h:02d}:{mi:02d}"

def _night_data(sky: Sky, data: dict, pick) -> dict:
    swe = sky.swe
    this, transit = data["this"], data["transit"]
    def at(month: int, day: int, hour: int) -> float:
        utc = dt.datetime(YEAR, month, day, hour) - dt.timedelta(hours=TAIPEI_OFFSET_HOURS)
        return swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour, 0, 0.0, swe.GREG_CAL)[1]
    start, end = at(11, 4, 18), at(11, 5, 3)
    def plane(t: float) -> tuple[float, float]:
        m, s = sky.mercury(t), calc_ut(swe, t, swe.SUN)
        return (sky.difference(t) * math.cos(math.radians(m[1])) * 60, (m[1] - s[1]) * 60)
    cazimi = pick("lilly", "cazimi")
    moments = (("晚間", start), ("Lilly 的日輪內開始", cazimi[0]), ("下合", this["conjunction"]),
               ("最接近太陽中心", transit["closest_at"]), ("Lilly 的日輪內結束", cazimi[1]), ("過了午夜", end))
    states = []
    for name, t in moments:
        d, v, sep = sky.difference(t), sky.speed(t), sky.separation(t)
        # At a limit's own instant the verdict is the band being entered or left, not the rounding of the root.
        inside = t + 1 / 1440 if t == cazimi[0] else t - 1 / 1440 if t == cazimi[1] else t
        east, north = plane(t)
        if abs(math.hypot(east, north) / 60 - sep) * 3600 > SAME_PLANE_ARCSEC:
            raise RuntimeError("figure 3's flat plate no longer agrees with the separation on the sphere")
        if sep <= sky.sun_semidiameter(t) or (abs(d) * 60 <= BOTH_COORDINATES_ARCMIN and abs(north) <= BOTH_COORDINATES_ARCMIN):
            raise RuntimeError("figure 3 says the centre stays off the disc and out of the 16′ square")
        states.append({"name": name, "t": t, "difference": d, "separation": sep, "east": east, "north": north,
                       "band": _band(data["limits"]["lilly"], sky.difference(inside), v), "when": _when(swe, t)})
    count = math.ceil((end - start) / PATH_STEP_DAYS)
    path = [plane(start + i * (end - start) / count) for i in range(count + 1)]
    if min(abs(n) for _, n in path) <= BOTH_COORDINATES_ARCMIN:
        raise RuntimeError("Mercury's path enters the 16′ square of latitude")
    if max(abs(e) for e, _ in path) >= DISC_REACH or not all(-DISC_SOUTH < n < DISC_NORTH for _, n in path):
        raise RuntimeError("Mercury's path leaves figure 3")
    closest = plane(transit["closest_at"])
    # Three weeks' axis, Taipei midnights: the first and last tick of figure 2's upper panel.
    ticks = [at(10, 26, 0), at(10, 31, 0), at(11, 5, 0), at(11, 10, 0), at(11, 15, 0)]
    close_ticks = [start, at(11, 4, 21), at(11, 5, 0), end]
    spans = {(key, band): pick(key, band) for key, _, _ in PROFILES for band, _ in BANDS if data["crossings"][key][band]}
    return {"start": start, "end": end, "states": states, "path": path, "closest": closest,
            "sun_radius": transit["radius"], "conjunction": this["conjunction"], "closest_at": transit["closest_at"],
            "separation": transit["closest"], "mercury_diameter": swe.pheno_ut(this["conjunction"], swe.MERCURY)[3],
            "spans": spans, "ticks": ticks, "close_ticks": close_ticks, "far_end": at(11, 16, 0),
            "tick_labels": {t: _slash(swe, t) for t in ticks},
            "close_labels": {t: _clock(swe, t) for t in close_ticks},
            "text": {t: _short(swe, t) for pair in spans.values() for t in pair},
            "clocks": {t: _clock(swe, t) for t in (this["conjunction"], transit["closest_at"])},
            "range_text": (_short(swe, start), _short(swe, end)),
            "far_text": (_slash(swe, ticks[0]), _slash(swe, at(11, 16, 0)))}

def _hours(span: list[float]) -> str:
    minutes = math.floor((span[1] - span[0]) * 1440)
    return f"{minutes // 60} 小時 {minutes % 60} 分"

def _swatch(x: float, y: float, cls: str, name: str) -> str:
    return _fx.rect(x, y - 12, 18, 14, cls) + _fx.rect(x, y - 12, 18, 14, "fx-lens") + _fx.text(x + 24, y, name, "fx-t fx-small")

def _scale_plot(layout: str, fid: str, data: dict, night: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (170.0, 860.0) if wide else (14.0, 326.0)
    th = 26.0 if wide else 16.0
    pitch = 36.0 if wide else 38.0
    label_gap = 0.0 if wide else 9.0
    # Row tops: in the phone drawing a row's name sits on its own line above the track.
    far_top, far_axis = (48.0, 152.0) if wide else (40.0, 154.0)
    near_top, near_axis = (250.0, 390.0) if wide else (246.0, 396.0)
    H = 460.0 if wide else 456.0
    far = lambda t: x0 + (t - night["ticks"][0]) / (night["far_end"] - night["ticks"][0]) * (x1 - x0)  # noqa: E731
    near = lambda t: x0 + (t - night["start"]) / (night["end"] - night["start"]) * (x1 - x0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(24 if wide else x0, 32 if wide else 24,
                        f"三週：{bound.num(night['far_text'][0])} 到 {bound.num(night['far_text'][1])}", "fx-t fx-small fx-rub"))
    def name(y: float, label: str) -> None:
        out.append(_fx.text(24, y + 18, label, "fx-t fx-small") if wide else _fx.text(x0, y + 4, label, "fx-t fx-small fx-key"))
    for i, (key, _, label) in enumerate(PROFILES):
        y = far_top + i * pitch + label_gap
        name(y - label_gap, bound.label(label))
        out.append(_fx.rect(x0, y, x1 - x0, th, "fx-track"))
        for band in ("under_beams", "combust", "cazimi"):
            span = night["spans"].get((key, band))
            if span:
                out.append(_fx.rect(far(span[0]), y, max(far(span[1]) - far(span[0]), 1.5), th, BAND_CLASS[band]))
    bottom = far_top + 2 * pitch + label_gap + th
    out.append(_fx.line(far(night["conjunction"]), far_top - 4, far(night["conjunction"]), bottom + 4, "fx-dash"))
    out.append(_fx.text(far(night["conjunction"]), far_top - 8 if wide else 24, "下合", "fx-t fx-small", "middle"))
    out.append(_fx.line(x0, far_axis, x1, far_axis, "fx-axis"))
    for i, t in enumerate(night["ticks"]):
        out.append(_fx.line(far(t), far_axis, far(t), far_axis + 5, "fx-axis"))
        out.append(_fx.text(far(t), far_axis + 22, bound.scale(night["tick_labels"][t]), "fx-t fx-small fx-num",
                            "start" if i == 0 else "middle"))
    # The lens: the night's nine hours on the upper axis, opened out over the lower panel.
    lens_a, lens_b = far(night["start"]), far(night["end"])
    out.append(_fx.rect(lens_a, far_top - 2, lens_b - lens_a, bottom - far_top + 4, "fx-lens"))
    out.append(_fx.line(lens_a, bottom + 2, x0, near_top - 4, "fx-leader"))
    out.append(_fx.line(lens_b, bottom + 2, x1, near_top - 4, "fx-leader"))
    head = near_top - 12 if wide else near_top - 34
    out.append(_fx.text(24 if wide else x0, head, f"這一晚：{bound.num(night['range_text'][0])} 到 {bound.num(night['range_text'][1])}",
                        "fx-t fx-small fx-rub fx-key"))
    c, a = night["conjunction"], night["closest_at"]
    mark_y = near_top - 12 if wide else near_top - 14
    out.append(_fx.text(near(c) - 4, mark_y, f"下合 {bound.num(night['clocks'][c])}", "fx-t fx-small fx-key", "end"))
    out.append(_fx.text(near(a) + 4, mark_y, f"最近 {bound.num(night['clocks'][a])}", "fx-t fx-small fx-key"))
    rows = (("lilly", "cazimi", "combust", PROFILES[0][2]), ("biruni", "cazimi", "combust", PROFILES[2][2]),
            ("hellenistic", None, "under_beams", PROFILES[1][2]), (None, None, None, "al-Qabīṣī、Bonatti"))
    for i, (row_key, row_band, row_ground, row_label) in enumerate(rows):
        y = near_top + i * pitch + label_gap
        span = night["spans"].get((row_key, row_band)) if row_band else None
        note = ""
        if row_key == "hellenistic":
            note = "全段在光束下，沒有日輪內"
        elif row_key is None:
            note = "沒有任何時刻符合"
        elif span:
            note = bound.num(_hours(span))
        if wide:
            name(y, bound.label(row_label))
        else:
            name(y - label_gap, f"{bound.label(row_label)}：{note}")
        out.append(_fx.rect(x0, y, x1 - x0, th, "fx-track"))
        if row_ground:
            out.append(_fx.rect(x0, y, x1 - x0, th, BAND_CLASS[row_ground]))
        if span and row_band:
            out.append(_fx.rect(near(span[0]), y, near(span[1]) - near(span[0]), th, BAND_CLASS[row_band]))
        # The two instants cross each track; on the solid bars they are paper-coloured slits.
        for t, cls in ((c, "fx-dash"), (a, "fx-hair")):
            if span:
                out.append(_fx.rect(near(t) - 1, y, 2, th, "fx-track"))
            else:
                out.append(_fx.line(near(t), y, near(t), y + th, cls))
        if wide and span:
            out.append(_fx.text(near(span[1]) + 8, y + 18, note, "fx-t fx-small fx-key"))
        elif wide:
            out.append(_fx.text((x0 + x1) / 2, y + 18, note, "fx-t fx-small fx-key", "middle"))
    out.append(_fx.line(near(c), near_axis - 4, near(c), near_axis, "fx-axis"))
    out.append(_fx.line(near(a), near_axis - 4, near(a), near_axis, "fx-axis"))
    out.append(_fx.line(x0, near_axis, x1, near_axis, "fx-axis"))
    for i, t in enumerate(night["close_ticks"]):
        out.append(_fx.line(near(t), near_axis, near(t), near_axis + 5, "fx-axis"))
        anchor = "start" if i == 0 else "end" if i == len(night["close_ticks"]) - 1 else "middle"
        out.append(_fx.text(near(t), near_axis + 22, bound.scale(night["close_labels"][t]), "fx-t fx-small fx-num", anchor))
    legend_y, gap = (444.0, 150.0) if wide else (444.0, 106.0)
    lx = x0 if wide else 14.0
    for i, (band, label) in enumerate((("under_beams", "在光束下"), ("combust", "焦傷"), ("cazimi", "日輪內"))):
        out.append(_swatch(lx + i * gap, legend_y, BAND_CLASS[band], label))
    out.append("</svg>")
    return "".join(out)

def _scale_figure(data: dict, night: dict) -> str:
    bound = _fx.Bound()
    words = {"under_beams": "在光束下", "combust": "焦傷", "cazimi": "日輪內"}
    rows = []
    for key, _, label in PROFILES:
        side = _edges(data["limits"][key], "evening", "retrograde")
        for band in ("under_beams", "combust", "cazimi"):
            span = night["spans"].get((key, band))
            if span:
                rows.append(f'<tr><th scope="row">{bound.label(label)}</th>'
                            f'<td>{words[band]}（{bound.num(_limit_text(side[band]))}）</td>'
                            f'<td class="n">{bound.num(night["text"][span[0]])}</td>'
                            f'<td class="n">{bound.num(night["text"][span[1]])}</td></tr>')
    table = _fx.data_table(("誰的規則", "距離帶（逆行時的界線）", "開始", "結束"), rows)
    caption = (f"<b>{bound.label('圖 2')}</b>同一次下合，三套界線在時間軸上的範圍。上半是這三週，下半把框起來的九個小時放大："
               "單線是在光束下、交叉線是焦傷、實心是日輪內。照 Lilly 與 al-Bīrūnī，好幾天的焦傷裡夾著不到六小時的日輪內；"
               "希臘化那一套只有一條線；要求黃經與黃緯都在界線內的 al-Qabīṣī、Bonatti，這一晚沒有任何時刻算日輪內。")
    return _fx.figure(fid="fig-mr-night", title="下合前後，各家的焦傷、光束下與日輪內落在哪一段時間", caption=caption,
        art=_fx.FigureArt.drawn(_scale_plot, "fig-mr-night", data, night, bound), table=table, bound=bound)

def _disc_plot(layout: str, fid: str, data: dict, night: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    k = DISC_SCALE[layout]
    cx = 300.0 if wide else 170.0
    top = 60.0
    cy = top + DISC_NORTH * k
    bottom = cy + DISC_SOUTH * k
    x = lambda east: cx - east * k  # noqa: E731
    y = lambda north: cy - north * k  # noqa: E731
    left, right = x(DISC_REACH), x(-DISC_REACH)
    H = 520.0 if wide else 524.0
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(left, top - 14, "← 東（昏星）", "fx-t fx-small fx-rub"))
    out.append(_fx.text(right, top - 14, "西（晨星）→", "fx-t fx-small fx-rub", "end"))
    clip = f"{fid}-{layout}-plot"
    out.append(f'<clipPath id="{clip}">{_fx.rect(left, top, right - left, bottom - top)}</clipPath>')
    out.append(f'<g clip-path="url(#{clip})">')
    out.append(_fx.rect(left, top, right - left, bottom - top, "fx-track"))
    cazimi_degrees = _edges(data["limits"]["lilly"], "evening", "retrograde")["cazimi"]
    assert cazimi_degrees is not None
    edge = cazimi_degrees * 60
    out.append(_fx.rect(x(edge), top, 2 * edge * k, bottom - top, "fx-fill-dot"))
    out.append(_fx.line(x(edge), top, x(edge), bottom, "fx-edge"))
    out.append(_fx.line(x(-edge), top, x(-edge), bottom, "fx-edge"))
    out.append(_fx.circle(cx, cy, night["sun_radius"] * 60 * k, "fx-disc"))
    side = BOTH_COORDINATES_ARCMIN * k
    out.append(_fx.rect(cx - side, cy - side, 2 * side, 2 * side, "fx-dash"))
    out.append(_fx.line(left, cy, right, cy, "fx-sunline"))
    pts = " ".join(f"{_fx.f(x(e))},{_fx.f(y(n))}" for e, n in night["path"])
    out.append(f'<polyline points="{pts}" class="fx-curve"/>')
    near = night["closest"]
    out.append(_fx.line(cx, cy, x(near[0]), y(near[1]), "fx-axis"))
    out.append("</g>")
    out.append(_fx.rect(left, top, right - left, bottom - top, "fx-inset-frame"))
    out.append(_fx.glyph("sun", cx, cy, 20 if wide else 16, "fx-sun-gl"))
    out.append(_fx.text(cx + 8, (cy + y(near[1])) / 2 + 12, bound.num(_arc(night["separation"])), "fx-t fx-small fx-key fx-num"))
    out.append(_fx.text(cx, cy - side + (20 if wide else 16), "太陽圓面", "fx-t fx-small fx-key", "middle"))
    out.append(_fx.text(right - 6, cy - 6, "黃道", "fx-t fx-small fx-key", "end"))
    # The panel beside the plate (wide) or under it (phone).
    px, py, line = (590.0, 92.0, 28.0) if wide else (x(DISC_REACH), bottom + 28, 22.0)
    for step, state in enumerate(night["states"]):
        lines = (bound.num(state["when"]), state["name"],
                 f"黃經差 {bound.num(_arc(state['difference']))}",
                 f"天空中相距 {bound.num(_arc(state['separation']))}",
                 f"照 {bound.label('Lilly')}：{BAND_NAMES[state['band']]}")
        body = [_fx.circle(x(state["east"]), y(state["north"]), 9 if wide else 7, "fx-mk"),
                _fx.glyph("mercury", x(state["east"]), y(state["north"]), 12 if wide else 10, "fx-mk-gl")]
        for i, value in enumerate(lines):
            body.append(_fx.text(px, py + i * line, value, "fx-t" if i == 0 else "fx-t fx-small"))
        out.append(_fx.step_group(step, DEFAULT_DISC_STEP, "".join(body)))
    ly = (py + 6 * line, 26.0) if wide else (py + 5 * line + 8, 20.0)
    legend = (("fx-fill-dot", f"Lilly：黃經 {bound.num(_limit_text(edge / 60))} 以內"),
              ("fx-dash", f"黃經、黃緯都在 {bound.num(_limit_text(BOTH_COORDINATES_ARCMIN / 60))} 內"),
              ("fx-disc", f"太陽圓面，半徑約 {bound.num(_arcmin(night['sun_radius']))}"))
    for i, (cls, label) in enumerate(legend):
        out.append(_swatch(px, ly[0] + i * ly[1], cls, label))
    out.append("</svg>")
    if ly[0] + 2 * ly[1] + 6 > H:
        raise RuntimeError("figure 3 outgrew its drawing")
    return "".join(out)

def _disc_figure(data: dict, night: dict) -> str:
    bound = _fx.Bound()
    notes, rows = [], []
    for step, s in enumerate(night["states"]):
        where = "東" if s["east"] > 0 else "西"
        place = "與太陽同一黃經" if step == DEFAULT_DISC_STEP else f"在太陽{where}側"
        notes.append(_fx.Note(None, None, f"{bound.num(s['when'])}（{s['name']}）：水星{place}，黃經差 {bound.num(_arc(s['difference']))}，"
                              f"天空中相距 {bound.num(_arc(s['separation']))}。照 {bound.label('Lilly')}：{BAND_NAMES[s['band']]}；"
                              "水星中心不在太陽圓面內。", step=step))
        rows.append(f'<tr><th scope="row">{bound.num(s["when"])}</th><td>{s["name"]}</td>'
                    f'<td class="n">{bound.num(_arc(s["difference"]))}</td>'
                    f'<td class="n">{bound.num(_arc(s["separation"]))}</td><td>{BAND_NAMES[s["band"]]}</td></tr>')
    table = _fx.data_table(("臺北時間", "這一刻", "黃經差", "天空中相距", "照 Lilly"), rows)
    caption = (f"<b>{bound.label('圖 3')}</b>以太陽為中心的天空示意：黃道畫成水平，北在上、東在左，水星由左往右經過。"
               f"點紋是 Lilly 只看黃經的 {bound.num(_limit_text(_edges(data['limits']['lilly'], 'evening', 'retrograde')['cazimi']))}，"
               f"虛線方框是黃經與黃緯都要在 {bound.num(_limit_text(BOTH_COORDINATES_ARCMIN / 60))} 內。"
               f"水星穿過點紋，所以照 Lilly 是日輪內；但它最近也離太陽中心 {bound.num(_arc(night['separation']))}，在圓面與方框的外面。"
               f"水星的記號放大了，它實際的視直徑只有約 {bound.num(f'{night['mercury_diameter'] * 3600:.0f}')}″。"
               "這是算出來的位置；那時臺北的太陽早已下山，不是看得到的景象。")
    return _fx.figure(fid="fig-mr-disc", title="11 月 4 日這一晚，水星從太陽圓面南方經過", caption=caption,
        art=_fx.FigureArt.drawn(_disc_plot, "fig-mr-disc", data, night, bound, notes=notes, idle=DISC_IDLE),
        controls=_fx.FigureControls(steps=len(night["states"]), default_step=DEFAULT_DISC_STEP, scrub_label=DISC_SCRUB),
        table=table, bound=bound)

# --- build -----------------------------------------------------------------------

def build() -> tuple[dict[str, str], list[str]]:
    data = compute()
    curve = data["curve"]
    with swiss() as swe:
        sky = Sky(swe)
        at = {t: d for t, d, _ in curve}
        sp = {t: v for t, _, v in curve}
        data["curve_at"] = lambda t: at[t] if t in at else sky.difference(t)
        data["speed_at"] = lambda t: sp[t] if t in sp else sky.speed(t)
        if max(abs(d) for _, d, _ in curve) >= Y_RANGE:
            raise RuntimeError("the curve leaves figure 1")
        figure = _figure(data)
        night_window = (data["this"]["start"] - 14, data["this"]["end"] + 9)
        night = _night_data(sky, data, lambda key, band: [x for x in data["crossings"][key][band]
                                                          if night_window[0] < x < night_window[1]])
        night_scale, night_disc = _scale_figure(data, night), _disc_figure(data, night)
        demo_differences = [sky.difference(a["astronomical_data"]["time"]["jd_ut"]) for a in data["answers"]]
    L, this, st = data["labels"], data["this"], data["stats"]
    cr = data["crossings"]
    window = (this["start"] - 14, this["end"] + 9)
    pick = lambda key, band: [x for x in cr[key][band] if window[0] < x < window[1]]  # noqa: E731
    beams = pick("lilly", "under_beams")
    combust = pick("lilly", "combust")
    cazimi = pick("lilly", "cazimi")
    hel = pick("hellenistic", "under_beams")
    swift = [x for x in data["swift"] if window[0] < x < window[1]]
    retro_in_beams = min(this["end"], beams[1]) - max(this["start"], beams[0])
    cazimi_minutes = round((cazimi[1] - cazimi[0]) * 1440)
    sup = data["superior_before"]
    sup_beams = data["lilly_beams_sup"]
    syn, dur, arcs = st["synodic"], st["durations"], st["arcs"]
    same = st["one_element"]
    before = max(y for y in same if y < YEAR)
    after = min(y for y in same if y > YEAR)
    years = len(st["years"])
    span_label = f"{SPAN[0]}–{SPAN[1] - 1}"
    others = [i for i in range(len(dur)) if i != st["this_index"]]
    wider = sum(1 for i in others if arcs[i] > st["this_arc"])
    rank_short = sum(1 for i in others if dur[i] < st["this_duration"])
    radius_text = _arcmin(data["transit"]["radius"])
    closest_text = _arcmin(data["transit"]["closest"])
    closest_at = data["transit"]["closest_at"]
    closest_seconds = math.floor(data["transit"]["closest"] * 3600)
    # The night's section rests on these: no instant meets a limit that counts latitude, and the cazimi is under six hours.
    if data["transit"]["closest"] * 60 <= 17 or cazimi_minutes >= 360:
        raise RuntimeError("the night's section no longer holds")
    reentry = min(x for x in cr["lilly"]["under_beams"] if x > beams[1])
    biruni_combust = pick("biruni", "combust")
    quoted = [
        f"{statistics.mean(syn):.1f} 天",
        f"{min(syn):.1f} 天到 {max(syn):.1f} 天",
        f"{st['this_duration']:.1f} 天",
        _dm(st["this_arc"]),
        f"{min(dur):.1f} 天到 {max(dur):.1f} 天",
        f"平均 {statistics.mean(dur):.1f} 天",
        f"{_dm(min(arcs))} 到 {_dm(max(arcs))}",
        f"平均 {_dm(statistics.mean(arcs))}",
        f"{len(dur)} 次逆行",
        f"{rank_short} 次比它短",
        f"只有 {wider} 次比它長",
        f"{statistics.mean(st['apart']):.1f}°",
        f"{statistics.mean(st['days3']):.1f} 天",
        f"{-statistics.mean(st['steps3']):.1f}°",
        f"{len(same)} 年",
        f"{years} 年",
        f"{before} 年（{data['before_element']}象）",
        f"離太陽最遠約 {data['widest']:.0f}°",
        f"{round((this['conjunction'] - data['answers'][0]['astronomical_data']['time']['jd_ut']) * 86400)} 秒之後才是下合",
        f"{after} 年",
        f"{len(st['four'])} 年",
        L[this["start"]]["when"],
        L[this["end"]]["when"],
        L[this["conjunction"]]["when"],
        _sign_dm(this["lon_start"]),
        _sign_dm(this["lon_end"]),
        f"南 {_dm(abs(this['lat_conj']))}",
        f"約 {radius_text}",
        closest_text,
        L[data["transit"]["next"]]["year_date"],
        L[beams[0]]["when"],
        L[beams[1]]["when"],
        L[combust[0]]["when"],
        L[combust[1]]["when"],
        L[cazimi[0]]["when"],
        L[cazimi[1]]["when"],
        f"{cazimi_minutes // 60} 小時 {cazimi_minutes % 60} 分",
        L[hel[0]]["when"],
        L[hel[1]]["when"],
        f"{retro_in_beams:.1f} 天",
        L[swift[0]]["when"],
        L[swift[1]]["when"],
        data["mean"]["text"],
        f"{sup_beams[1] - sup_beams[0]:.1f} 天",
        f"{beams[1] - beams[0]:.1f} 天",
        L[sup["jd"]]["date"],
        f"{data['helio'][0]:.2f}",
        f"{data['helio'][1]:.2f}",
        span_label,
        _arcsec_text(demo_differences[0]),
        f"{span_label} 年",
        L[biruni_combust[0]]["when"],
        L[biruni_combust[1]]["when"],
        f"每天退 {_dm(abs(this['speed_conj']))}",
        L[this["conjunction"]]["utc"],
        _sign_dm(this["lon_conj"]),
        f"{closest_seconds // 60}′{closest_seconds % 60:02d}″",
        L[closest_at]["when"],
        f"比下合晚 {math.floor((closest_at - this['conjunction']) * 1440)} 分鐘",
        f"只在外面 {reentry - beams[1]:.1f} 天",
        L[reentry]["when"],
        L[data["superior_after"]]["year_date"],
        L[data["elongation"]["at"]]["date"],
        _dm(data["elongation"]["degrees"]),
    ]
    quoted = list(dict.fromkeys(quoted))
    return {"fx-defs": _fx.defs(()), "curve": figure, "night-scale": night_scale, "night-disc": night_disc, "year": _year_rows(data), "events": _event_rows(data),
        "conjunctions": _conjunction_rows(data), "drift": _drift_rows(data), "demo": _demo_rows(data), "night": _night_rows(data, pick)}, quoted

def _arcsec_text(degrees: float) -> str:
    return f"{abs(degrees) * 3600:.2f}″"
