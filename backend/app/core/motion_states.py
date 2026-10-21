"""Each planet's course against its mean daily motion (swift or slow), whether
it is stationary about a turn, and on which side of the Sun it stands
(oriental or occidental), as the named texts define them.

The definitions, the mean-motion profiles, Lilly's station days and their pages
are stated once, in ``METHOD_SOURCE_ENTRIES`` below.  The speed is geocentric
even for a topocentric chart: the topocentric Moon's speed swings about
±5.5°/day within a day.  No speed-percentage station threshold is used: none
reproduces Lilly's days for every planet.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from fractions import Fraction
from typing import Final

import swisseph as swe

from ..ephemeris import guarded_calc
from .formatting import dms_text
from .invariants import InternalInvariantError
from .method_status import method_head
from .module_state import (
    PRODUCT_FORMULA_SOURCE,
    STATE_FIELDS,
    computed_receipt,
    frame_table_refusal,
)
from .root_finding import (
    SOLVER_NAME, find_crossings_around, find_crossings_detailed, wrap_to_signed_180,
)
from .solar_phase import SIDES, EclipticSampler, EventClock, side_of_sun
from .source_reading import ORIGINAL_LANGUAGE_READ, TRANSLATION_READ, cited
from .time_utils import solved_instant
from .trace import Trace

METHOD: Final = "planetary_motion_states_v1"
SOURCE_REF: Final = "motion_states"
SPEED_BASIS: Final = "geocentric_longitude_speed_swiss_analytic_at_the_instant"
STATION_PROFILE: Final = "lilly_1647_station_days_v1"
DEFAULT_MEAN_MOTION_PROFILE: Final = "lilly_1647_v1"
MEAN_MOTION_PROFILES: Final = ("lilly_1647_v1", "bonatti_1550_v1")

LISTED_BODIES: Final = (
    ("sun", swe.SUN),
    ("moon", swe.MOON),
    ("mercury", swe.MERCURY),
    ("venus", swe.VENUS),
    ("mars", swe.MARS),
    ("jupiter", swe.JUPITER),
    ("saturn", swe.SATURN),
)

COURSES: Final = ("swift", "slow", "equal_to_mean_at_source_precision")
DIRECTIONS: Final = ("direct", "retrograde")
STATION_KINDS: Final = ("first_station_to_retrograde", "second_station_to_direct")
STATION_STATES: Final = (
    "stationary_before_retrograde",
    "stationary_before_direct",
    "not_stationary",
    "not_applicable_luminary",
    "stationary_after_turning_retrograde",
    "stationary_after_turning_direct",
)
ORIENTALITY: Final = ("oriental", "occidental", "on_the_sun", "not_applicable_sun")
LILLY_P115: Final = (
    "listed_as_accidental_fortitude",
    "listed_as_accidental_debility",
    "not_listed",
)
INTERVALS: Final = ("stated_civil_hour", "civil_day")

# The side of the Sun in solar_phase's words, renamed in Lilly's (p.114).
_ORIENTALITY_OF_SIDE: Final = dict(zip(SIDES, ORIENTALITY[:3]))

# Mean daily motion in arcseconds, exact as printed, and the unit of the last
# place printed (the equality band is half of it either way).
_THIRD: Final = Fraction(1, 60)
MEAN_MOTIONS: Final[dict[str, dict[str, tuple[Fraction, Fraction, str]]]] = {
    "lilly_1647_v1": {
        "sun": (Fraction(59 * 60 + 8), Fraction(1), "59′08″"),
        "moon": (Fraction(13 * 3600 + 10 * 60 + 36), Fraction(1), "13°10′36″"),
        "mercury": (Fraction(59 * 60 + 8), Fraction(1), "59′08″"),
        "venus": (Fraction(59 * 60 + 8), Fraction(1), "59′08″"),
        "mars": (Fraction(31 * 60 + 27), Fraction(1), "31′27″"),
        "jupiter": (Fraction(4 * 60 + 59), Fraction(1), "4′59″"),
        "saturn": (Fraction(2 * 60 + 1), Fraction(1), "2′01″"),
    },
    "bonatti_1550_v1": {
        "sun": (Fraction(59 * 60 + 8), Fraction(1), "59′08″"),
        "moon": (Fraction(13 * 3600 + 10 * 60 + 35), Fraction(1), "13°10′35″"),
        "mercury": (Fraction(59 * 60 + 8), Fraction(1), "59′08″"),
        "venus": (Fraction(59 * 60 + 8), Fraction(1), "59′08″"),
        "mars": (Fraction(31 * 60 + 26), Fraction(1), "31′26″"),
        "jupiter": (Fraction(4 * 60 + 59), Fraction(1), "4′59″"),
        "saturn": (Fraction(2 * 60) + 35 * _THIRD, _THIRD, "2′00″35‴"),
    },
}

# Lilly's days before each turn (pp.58, 62, 65, 73, 76).
STATION_DAYS: Final[dict[str, dict[str, int]]] = {
    "saturn": {STATION_KINDS[0]: 5, STATION_KINDS[1]: 5},
    "jupiter": {STATION_KINDS[0]: 5, STATION_KINDS[1]: 4},
    "mars": {STATION_KINDS[0]: 3, STATION_KINDS[1]: 2},
    "venus": {STATION_KINDS[0]: 2, STATION_KINDS[1]: 2},
    "mercury": {STATION_KINDS[0]: 1, STATION_KINDS[1]: 1},
}
# Lilly's days after each turn: only Mars after direction, "after, but one day"
# (p.65).  No other planet chapter gives days after a turn, so those are none.
STATION_DAYS_AFTER: Final[dict[str, dict[str, int]]] = {
    "saturn": {STATION_KINDS[0]: 0, STATION_KINDS[1]: 0},
    "jupiter": {STATION_KINDS[0]: 0, STATION_KINDS[1]: 0},
    "mars": {STATION_KINDS[0]: 0, STATION_KINDS[1]: 1},
    "venus": {STATION_KINDS[0]: 0, STATION_KINDS[1]: 0},
    "mercury": {STATION_KINDS[0]: 0, STATION_KINDS[1]: 0},
}
_STATE_OF_KIND: Final = dict(zip(STATION_KINDS, STATION_STATES[:2]))
_STATE_AFTER_KIND: Final = dict(zip(STATION_KINDS, STATION_STATES[4:6]))

# Stations of one planet are at least about 20 days apart (Mercury), so half a
# day never steps over a pair; the window covers Lilly's longest five days with
# room to list the stations either side.
STATION_WINDOW_DAYS: Final = 15.0
STATION_STEP_DAYS: Final = 0.5
TOLERANCE_DAYS: Final = 1.0e-6
# How far a turn is defined at all.  The root of Swiss's speed and the turning
# point of the longitude itself (where the difference of the positions 0.05 day
# either side changes sign) fall apart by up to 38 s for Saturn, 14 s for Mars
# and Jupiter, 3 s for Mercury and Venus (every turn found from 1 January of
# every seventh year 1900-2400, 963 turns); positions a minute either side,
# where their own last places show, move Saturn's to 51 s.  That is far more
# than the bisection leaves open, so the printed unit follows from this bound,
# not from TOLERANCE_DAYS: time_utils.printed_unit_seconds makes it the minute.
STATION_DEFINITION_SPREAD_SECONDS: Final = 60.0
STATION_INSTANT_UNCERTAINTY_DAYS: Final = STATION_DEFINITION_SPREAD_SECONDS / 86400.0
INTERVAL_STEP_DAYS: Final = 1.0 / 48.0

_INFERIOR: Final = ("mercury", "venus")
_SUPERIOR: Final = ("mars", "jupiter", "saturn")


def _shifted(fn: Callable[[float], float], base: float) -> Callable[[float], float]:
    """``fn`` read from ``base``, for a root finder that searches from zero."""
    return lambda t: fn(base + t)


def course_band_edges(profile: str, key: str) -> tuple[Fraction, Fraction]:
    """The two |speed| values, arcseconds a day, where the course changes:
    the mean less and more half the last printed unit."""

    mean, unit, _text = MEAN_MOTIONS[profile][key]
    return mean - unit / 2, mean + unit / 2


def classify_course(profile: str, key: str, speed_degrees_per_day: float) -> str:
    """Swift, slow or equal: |speed| against the profile's mean daily motion."""

    mean, unit, _text = MEAN_MOTIONS[profile][key]
    speed = abs(Fraction(speed_degrees_per_day)) * 3600
    lower, upper = course_band_edges(profile, key)
    if lower < speed < upper:
        return COURSES[2]
    return COURSES[0] if speed > mean else COURSES[1]


def station_state(
    key: str, stations: list[dict], day_offset: float
) -> tuple[str, dict | None, int | None]:
    """Stationary when a turn falls within Lilly's days after this instant, or
    this instant within Lilly's days after a turn.

    ``stations`` carry ``kind`` and ``day_offset`` (days from the chart
    instant); ``day_offset`` is the instant being judged on the same scale.
    Returns the state, the turn it is about, and Lilly's days on that side.
    """

    if key not in STATION_DAYS:
        return STATION_STATES[3], None, None
    for station in stations:
        ahead = station["day_offset"] - day_offset
        days = STATION_DAYS[key][station["kind"]]
        if 0.0 <= ahead <= days:
            return _STATE_OF_KIND[station["kind"]], station, days
    for station in stations:
        ahead = station["day_offset"] - day_offset
        days = STATION_DAYS_AFTER[key][station["kind"]]
        if -days <= ahead < 0.0:
            return _STATE_AFTER_KIND[station["kind"]], station, days
    return STATION_STATES[2], None, None


def orientality(key: str, longitude: float, sun_longitude: float) -> str:
    if key == "sun":
        return ORIENTALITY[3]
    return _ORIENTALITY_OF_SIDE[side_of_sun(longitude, sun_longitude)]


def lilly_p115(key: str, course: str, oriental: str) -> dict:
    """Which of Lilly's p.115 lists a state is on; never a score."""

    fortitude, debility, unlisted = LILLY_P115
    by_course = {COURSES[0]: fortitude, COURSES[1]: debility}.get(course, unlisted)
    if key in _SUPERIOR:
        strong = ORIENTALITY[0]
    elif key in _INFERIOR or key == "moon":
        strong = ORIENTALITY[1]
    else:
        strong = None
    if strong is None or oriental not in ORIENTALITY[:2]:
        by_side = unlisted
    else:
        by_side = fortitude if oriental == strong else debility
    return {"course": by_course, "relative_to_sun": by_side}


SpeedSampler = Callable[[int, float], float]


def make_speed_sampler(flags: int) -> SpeedSampler:
    """(body, JD UT) -> geocentric longitude speed in degrees a day.

    The chart's own frame flags without the topocentric flag: the course is
    judged on the geocentric motion whatever the chart's centre.
    """

    geocentric = (flags & ~swe.FLG_TOPOCTR) | swe.FLG_SPEED
    cache: dict[tuple[int, float], float] = {}

    def at(body: int, jd_ut: float) -> float:
        cached = cache.get((body, jd_ut))
        if cached is not None:
            return cached
        values, _ = guarded_calc(jd_ut, body, geocentric, f"行速與停滯（Swiss body {body} 地心黃經速度）")
        cache[(body, jd_ut)] = values[3]
        return values[3]

    return at


def find_stations(
    speed: SpeedSampler, body: int, jd_ut: float, instant_of: Callable[[float], dict]
) -> list[dict]:
    """Every sign change of the geocentric speed within the window.

    The coarse scan runs on a grid fixed in absolute time, not on the chart
    instant, so one turn is bisected through the same Julian days whichever
    instant anchors the search (a birth instant, an hour's representative, a
    day's noon) and is printed the same.  The turn is printed as the whole
    minute it lies in: the bisection stops at ``TOLERANCE_DAYS`` (about 86 ms),
    but the turn itself is defined only to ``STATION_INSTANT_UNCERTAINTY_DAYS``
    (speed root against position turning point), so no finer place is
    determined; ``day_offset`` and ``instant`` are that minute, and the
    Lilly-day windows are judged from it.
    """

    roots = find_crossings_around(
        lambda jd: speed(body, jd),
        center_jd=jd_ut,
        half_window_days=STATION_WINDOW_DAYS,
        coarse_step_days=STATION_STEP_DAYS,
        tolerance_days=TOLERANCE_DAYS,
    )
    stations = []
    for root in roots:
        jd = root["jd"]
        # Read the turn from either side of the root, not from the coarse
        # bracket: a sample may have landed on it.
        kind = turn_kind(speed(body, jd - 1e-3), speed(body, jd + 1e-3))
        if kind is None:
            continue  # a touch, not a turn
        start, instant = solved_instant(jd, STATION_INSTANT_UNCERTAINTY_DAYS, instant_of)
        stations.append({"kind": kind, "day_offset": start - jd_ut, "instant": instant})
    return stations


def turn_kind(before: float, after: float) -> str | None:
    """The turn the speed makes from ``before`` to ``after``, or None for none.

    A turn is a change in the sign of the speed (-1, 0 or +1): it rises towards
    direct motion, or falls towards retrograde.  A zero on either side counts as
    its own sign, the same on both sides: direct to zero and zero to retrograde
    are both the turn to retrograde, retrograde to zero and zero to direct the
    turn to direct, and the same sign (zero to zero included) on both sides is
    no turn.  Reversing time and motion together, (before, after) to
    (-after, -before), names the same turn.
    """

    change = _sign(after) - _sign(before)
    if change < 0:
        return STATION_KINDS[0]
    if change > 0:
        return STATION_KINDS[1]
    return None


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _interval_seen(
    key: str,
    body: int,
    spans: list[tuple[float, float]],
    *,
    jd_ut: float,
    speed: SpeedSampler,
    sample: EclipticSampler,
    stations: list[dict],
) -> dict:
    """Every state each profile puts the body in over the stretches."""

    # The course changes only where |speed| leaves or enters the equal band,
    # so the stretch is cut at both band edges of every profile; the mean
    # itself is no edge.
    edges: list[Callable[[float], float]] = [
        (lambda edge: lambda jd: abs(speed(body, jd)) * 3600 - edge)(float(edge))
        for profile in MEAN_MOTION_PROFILES
        for edge in course_band_edges(profile, key)
    ]
    if key != "sun":
        edges.append(lambda jd: math.sin(math.radians(
            wrap_to_signed_180(sample(body, jd)[0] - sample(swe.SUN, jd)[0])
        )))
    marks = [
        jd_ut + station["day_offset"] - shift
        for station in stations
        for shift in (
            0.0, STATION_DAYS[key][station["kind"]], -STATION_DAYS_AFTER[key][station["kind"]]
        )
    ] if key in STATION_DAYS else []
    seen: dict[str, list[str]] = {name: [] for name in (*MEAN_MOTION_PROFILES, "station", "side")}

    def note(name: str, value: str) -> None:
        if value not in seen[name]:
            seen[name].append(value)

    for start, end in spans:
        cuts = {start, end, *(t for t in marks if start < t < end)}
        for edge in edges:
            cuts.update(
                start + root["t"]
                for root in find_crossings_detailed(
                    _shifted(edge, start),
                    window_days=end - start,
                    coarse_step_days=INTERVAL_STEP_DAYS,
                    tolerance_days=TOLERANCE_DAYS,
                )
                if 0.0 < root["t"] < end - start
            )
        ordered = sorted(cuts)
        probes = [ordered[0]] + [(a + b) / 2.0 for a, b in zip(ordered, ordered[1:])]
        for jd in probes:
            v = speed(body, jd)
            for profile in MEAN_MOTION_PROFILES:
                note(profile, classify_course(profile, key, v))
            note("station", station_state(key, stations, jd - jd_ut)[0])
            note("side", orientality(key, sample(body, jd)[0], sample(swe.SUN, jd)[0]))
    return seen


def _means_table(profile: str) -> dict:
    return {
        key: {
            "degrees_per_day": float(mean) / 3600,
            "text": text,
            "printed_to_arcseconds": float(unit),
        }
        for key, (mean, unit, text) in MEAN_MOTIONS[profile].items()
    }


def compute_motion_states(
    bodies: list[dict],
    trace: Trace,
    *,
    speed: SpeedSampler,
    clock: EventClock,
) -> dict:
    """Course, station and orientality of the Sun, the Moon and five planets.

    ``bodies`` are the chart's effective body records (their longitudes give
    the side of the Sun, as in ``solar_phase``); ``speed`` reads the geocentric
    speed at any instant; ``sample`` reads effective longitudes for a non-exact
    birth time's ``interval_spans``.
    """

    time_basis, jd_ut, instant_of = clock.time_basis, clock.jd_ut, clock.instant_of
    sample, interval, interval_spans = clock.sample, clock.interval, clock.interval_spans
    if interval is not None and (interval not in INTERVALS or not interval_spans):
        raise ValueError("a non-exact birth time needs its interval and its stretches")
    by_key = {body["key"]: body for body in bodies}
    sun = by_key["sun"]
    profile_results: dict[str, dict] = {
        profile: {
            "means": _means_table(profile),
            "courses": {},
            "courses_seen_in_birth_time_interval": None if interval is None else {},
        }
        for profile in MEAN_MOTION_PROFILES
    }
    stations_by_key: dict[str, list[dict] | None] = {}
    rows = []
    interval_rows = []
    for key, body_id in LISTED_BODIES:
        body = by_key.get(key)
        if body is None or body.get("longitude") is None:
            continue
        v = speed(body_id, jd_ut)
        for profile in MEAN_MOTION_PROFILES:
            profile_results[profile]["courses"][key] = classify_course(profile, key, v)
        stations = (
            find_stations(speed, body_id, jd_ut, instant_of) if key in STATION_DAYS else None
        )
        stations_by_key[key] = stations
        state, turn, lilly_days = station_state(key, stations or [], 0.0)
        course = profile_results[DEFAULT_MEAN_MOTION_PROFILE]["courses"][key]
        side = orientality(key, body["longitude"], sun["longitude"])
        mean = MEAN_MOTIONS[DEFAULT_MEAN_MOTION_PROFILE][key][0]
        rows.append({
            "key": key,
            "name": body["name"],
            "speed_longitude_degrees_per_day": v,
            "daily_motion_text": dms_text(abs(v)),
            "direction": DIRECTIONS[1] if v < 0 else DIRECTIONS[0],
            "mean_motion_degrees_per_day": float(mean) / 3600,
            "mean_motion_text": MEAN_MOTIONS[DEFAULT_MEAN_MOTION_PROFILE][key][2],
            "speed_ratio_to_mean": abs(v) * 3600 / float(mean),
            "course": course,
            "station": {
                "state": state,
                "lilly_days": lilly_days,
                "turn": turn,
            },
            "relative_to_sun": side,
            "lilly_p115": lilly_p115(key, course, side),
        })
        if interval is not None:
            if interval_spans is None:
                raise InternalInvariantError("interval_spans is not None")
            seen = _interval_seen(
                key, body_id, interval_spans, jd_ut=jd_ut, speed=speed, sample=sample,
                stations=stations or [],
            )
            for profile in MEAN_MOTION_PROFILES:
                profile_results[profile]["courses_seen_in_birth_time_interval"][key] = seen[profile]
            interval_rows.append({
                "key": key,
                "name": body["name"],
                "courses_seen": seen[DEFAULT_MEAN_MOTION_PROFILE],
                "station_states_seen": seen["station"],
                "relative_to_sun_seen": seen["side"],
                "stable": all(
                    len(seen[name]) == 1 for name in (DEFAULT_MEAN_MOTION_PROFILE, "station", "side")
                ),
            })
    trace.add(
        "行速、停滯與東出西入",
        formula=(
            "行速：|地心黃經速度| 與平均每日行度比，多於平均為快、少於為慢，"
            "相差不到原典印出的最後一位的一半為相等；停滯：前後 15 天內速度變號的時刻，"
            "轉向前在 Lilly 給的天數之內、或轉向後在他給的轉向後天數之內為停滯；東出西入：行星在太陽西側（黃經差為負）為東出"
        ),
        inputs={"mean_motion_profile": DEFAULT_MEAN_MOTION_PROFILE, "station_profile": STATION_PROFILE},
        result={row["key"]: {
            "speed": row["speed_longitude_degrees_per_day"], "course": row["course"],
            "station": row["station"]["state"], "relative_to_sun": row["relative_to_sun"],
        } for row in rows},
        note="照原典列出。不替你解盤，也不預測。",
    )
    return {
        **method_head(METHOD, "motion_states", source_ref=SOURCE_REF),
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "speed_basis": SPEED_BASIS,
        "mean_motion_profile": DEFAULT_MEAN_MOTION_PROFILE,
        "station_profile": STATION_PROFILE,
        "time_basis": time_basis,
        "scope": {"listed": [key for key, _ in LISTED_BODIES]},
        "rows": rows,
        "profile_results": profile_results,
        "station_days": {
            key: {
                kind: {"before": STATION_DAYS[key][kind], "after": STATION_DAYS_AFTER[key][kind]}
                for kind in STATION_KINDS
            }
            for key in STATION_DAYS
        },
        "stations_within_window": stations_by_key,
        "station_search": {
            "window_days": STATION_WINDOW_DAYS,
            "solver": SOLVER_NAME,
            "coarse_step_days": STATION_STEP_DAYS,
            "tolerance_days": TOLERANCE_DAYS,
            "reference_instant": time_basis,
        },
        "birth_time_interval": (
            None if interval is None else {"interval": interval, "rows": interval_rows}
        ),
    }


def motion_states_not_applicable(state: dict, trace: Trace) -> dict:
    refusal = frame_table_refusal(
        state, trace, "行速、停滯與東出西入",
        note=(
            "參考框架相容表判定不適用：日心、質心沒有從地球看到的行速與太陽；恆星黃道、J2000 "
            "與不含章動的速度不是原典比的當日回歸黃經速度，不換框架重算。"
        ),
    )
    return motion_states_unavailable(refusal)


def motion_states_unavailable(receipt: dict) -> dict:
    """The module with no result, under the six state fields given."""

    return {
        **method_head(METHOD, "motion_states", source_ref=SOURCE_REF),
        **{field: receipt[field] for field in STATE_FIELDS},
        "speed_basis": SPEED_BASIS,
        "mean_motion_profile": None,
        "station_profile": None,
        "time_basis": None,
        "scope": None,
        "rows": [],
        "profile_results": None,
        "station_days": None,
        "stations_within_window": None,
        "station_search": None,
        "birth_time_interval": None,
    }


_LILLY_SCAN = "Wellcome Library copy, archive.org b30338724, scans n90-n211"
METHOD_SOURCE_ENTRIES: Final = {
    SOURCE_REF: {
        "applies_to": "derived_methods.motion_states",
        "definition": (
            "Course: the absolute geocentric longitude speed (Swiss Ephemeris analytic speed "
            "at the instant) against the mean daily motion; more is swift, less is slow "
            "(Lilly p.168), equal only within half the last place the source printed. A "
            "retrograde planet is compared by the degrees it goes back a day (Lilly p.178 "
            "calls a retrograde Saturn of 2 minutes a day slow). Stations: every sign change "
            "of the geocentric speed within 15 days before or after the chart instant, by "
            "root-finding; a planet is stationary when a turn falls within Lilly's days after "
            "the instant, or the instant within Lilly's days after a turn. Oriental or occidental of the Sun: the side of the Sun from "
            "solar_phase, west of the Sun (rising before it) oriental (Lilly p.114); the Moon "
            "oriental from opposition to conjunction; the Sun has none. Listed: the Sun, the "
            "Moon and the five planets."
        ),
        "mean_motion_profiles": {
            "lilly_1647_v1": (
                "Lilly 1647: Saturn 2'01\" (p.57), Jupiter 4'59\" (p.61), Mars 31'27\" "
                "(p.178; p.65 prints '31 degr. 27 min.'), Sun 59'08\" (p.69), Venus and "
                "Mercury the Sun's 59'08\" (p.72, p.76), Moon 13 deg 10'36\" (p.80). The "
                "default; it fills rows[]."
            ),
            "bonatti_1550_v1": (
                "Bonatti 1550 tractatus III cols.129-130: Saturn 2'00\"35''', Jupiter 4'59\", "
                "Mars 31'26\", Sun, Venus and Mercury 59'08\", Moon 13 deg 10'35\"; equal to "
                "the mean is 'aequalis'. Listed beside the default."
            ),
        },
        "default_mean_motion_profile": DEFAULT_MEAN_MOTION_PROFILE,
        "moon_slow_limit": (
            "The Moon is slow below her mean 13 deg 10'36\", Lilly's p.168 rule; p.80 says "
            "less than 13 deg 10' in 24 hours is slow, 'equivalent to a Retrograde Planet'. "
            "The 36\" between the two is disclosed, not applied."
        ),
        "station_days": (
            "Lilly's days before each turn: Saturn 5 and 5 (p.58), Jupiter 5 and 4 (p.62), "
            "Mars 'two or three' taken as 3 and 2 (p.65), Venus 2 and 2 (p.73), Mercury "
            "'Stationary one day' taken as 1 before each turn (p.76); p.114: the superiors "
            "move not 2, 3 or 4 days before retrogradation. After a turn: Mars 1 day after "
            "direction, 'after, but one day' (p.65); no other planet chapter gives days "
            "after a turn, so none. Counting the days after a turn is this site's reading "
            "of the planet chapters, not a rule Lilly states. The exact turns within the "
            "window are listed."
        ),
        "daily_motion_basis": (
            "The texts' daily motion is the difference of two noon positions; the product "
            "uses the instantaneous speed. Measured 1950-2050 (Swiss Ephemeris, geocentric): "
            "against the next 24 hours the Moon's swift/slow differs on 3.6% of instants "
            "(Mercury 1.4%, Saturn 0.5%, Mars 0.1%); against the 24 hours centred on the "
            "instant, 0.025% (Mercury 0.005%)."
        ),
        "doctrine": [
            "Lilly 1647 p.115: swift in motion, Saturn, Jupiter and Mars oriental, Venus and "
            "Mercury occidental, the Moon increasing or occidental are accidental "
            "fortitudes; slow in motion, Saturn, Jupiter and Mars occidental, Venus and "
            "Mercury oriental, the Moon decreasing in light are debilities",
            "Lilly 1647 p.80: the Moon slow is 'equivalent to a Retrograde Planet'",
            "Ptolemy, Tetrabiblos I.24 (Robbins pp.115-117): planets oriental and adding to "
            "their motion are most powerful; occidental and diminishing in speed, weaker",
            "al-Biruni, Book of Instruction §486: the influence is greatest when oriental "
            "and weak when occidental",
            "Vettius Valens, Anthologies IV.14: passing the first station into retrograde "
            "delays what is expected; the second station removes the delay",
        ],
        "sources": [
            cited(("William Lilly, Christian Astrology (London 1647) pp.57-58, 61-62, 65, "
                   "69-70, 72-73, 76, 80, 114-115, 168, 178"),
                  None, ORIGINAL_LANGUAGE_READ,
                  f"{_LILLY_SCAN}; each listed page checked on the scan"),
            cited(("Guido Bonatti, De astronomia tractatus X (Basel 1550) tractatus III part 2 "
                   "ch.1 and 3, cols.129-130"),
                  None, ORIGINAL_LANGUAGE_READ, "archive.org bub_gb_BgWuc5O-JzIC, scan n82"),
            cited(("Ptolemy, Tetrabiblos I.6, I.8, I.24, trans. Robbins (Loeb 1940) "
                   "pp.41, 45, 115-117"),
                  None, TRANSLATION_READ, "LacusCurtius transcription"),
            cited(("al-Biruni, Book of Instruction, trans. R. Ramsay Wright (1934) "
                   "§481-486, §498, §512"),
                  None, TRANSLATION_READ,
                  "archive.org typescript OCR; the 1934 page numbers not checked"),
            cited("Vettius Valens, Anthologies IV.14, V.7, V.11 (Kroll), trans. Riley", None,
                  TRANSLATION_READ,
                  ("Riley's PDF (Vettius_Valens_Riley.pdf), printed pp.82, 98, 108 "
                   "(PDF pages 84, 100, 110)")),
            cited("Ptolemy, Tetrabiblos III.3 (Robbins pp.235-241, the quadrants on pp.239-241); cf. III.10",
                  ("oriental and occidental to the Sun and to the horoscope by quadrants: the "
                   "quadrants preceding each and those opposite are oriental, the others "
                   "occidental; "
                   "III.10 only uses the quadrants; not applied"),
                  TRANSLATION_READ,
                  ("Robbins's translation in the LacusCurtius transcription, read at the "
                   "pp.239-241 page marks")),
        ],
        "not_applied": (
            "Increasing or decreasing in course (Bonatti's three definitions disagree for the "
            "superior planets, cols.129-130; Ptolemy I.24 and al-Biruni §512 keep rapid and "
            "increasing apart); al-Biruni's phased orientality (§481-482) and Bonatti's "
            "graded phases (tractatus III part 2 ch.5-6); the eastern and western quadrants of the "
            "horizon (Ptolemy I.6, III.3; al-Biruni §486); masculine and feminine by "
            "orientality (Ptolemy I.6); any speed-percentage station threshold; Lilly's "
            "p.115 points."
        ),
        "boundary_rule": (
            "exact rational comparison of |speed| in arcseconds a day with the printed mean; "
            "equal when the difference is less than half the last printed unit; a turn "
            "exactly Lilly's days ahead, or at the instant itself, counts as stationary; after "
            "a turn, an instant exactly Lilly's days after it still counts"
        ),
        "interval_rule": (
            "for a non-exact birth time, every course, station state and side of the Sun "
            "each body is in over the stated hour or civil day, from the roots of every "
            "edge over it"
        ),
        "interval_vocabulary": list(INTERVALS),
    },
}
