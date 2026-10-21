"""How far each planet and the Moon stand from the Sun, and which distance band
of a named tradition that puts them in: in the heart of the Sun (cazimi),
combust, under the Sun's beams, or clear of them.

The definition, the profiles, the argument for deciding on ecliptic longitude,
the reported-not-applied same-sign rule, the 7-day search and the birth-time
interval rule are stated once, in ``METHOD_SOURCE_ENTRIES`` below.

The Moon is the effective Moon of ``astronomical_data.bodies`` (with the
Moon-only topocentric profile, the topocentric one), so its distance from the
Sun is the one the page's positions give; geocentric and topocentric values of
the Moon differ by up to about a degree.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Final, Literal

import swisseph as swe

from .invariants import InternalInvariantError
from ..ephemeris import guarded_calc
from .formatting import dms_text, zodiac_sign_index
from .method_status import method_head
from .module_state import (
    PRODUCT_FORMULA_SOURCE,
    STATE_FIELDS,
    computed_receipt,
    module_state,
    frame_table_refusal,
)
from .root_finding import (
    SOLVER_NAME, find_crossings_around, find_crossings_detailed, wrap_to_signed_180,
)
from .source_reading import ORIGINAL_LANGUAGE_READ, SECONDARY_ONLY, TRANSLATION_READ, cited
from .time_utils import solved_instant
from .trace import Trace


SolarPhaseProfile = Literal[
    "lilly_1647_p113_v1",
    "hellenistic_15_v1",
    "biruni_wright_v1",
]
DEFAULT_SOLAR_PHASE_PROFILE: SolarPhaseProfile = "lilly_1647_p113_v1"
PROFILE_IDS: Final = ("lilly_1647_p113_v1", "hellenistic_15_v1", "biruni_wright_v1")

METHOD: Final = "solar_phase_ecliptic_longitude_difference_v1"
SOURCE_REF: Final = "solar_phase"
DECISION_BASIS: Final = "ecliptic_longitude_difference"
SAME_SIGN_RULE: Final = "reported_not_applied"

# The five planets and the Moon, in the bodies table's order.
LISTED_BODIES: Final = (
    ("moon", swe.MOON),
    ("mercury", swe.MERCURY),
    ("venus", swe.VENUS),
    ("mars", swe.MARS),
    ("jupiter", swe.JUPITER),
    ("saturn", swe.SATURN),
)
SEARCHED_BODIES: Final = ("mercury", "venus", "mars", "jupiter", "saturn")
NOT_LISTED: Final = ("sun", "uranus", "neptune", "pluto", "chiron", "lunar_nodes", "points")

BANDS: Final = ("cazimi", "combust", "under_beams", "clear", "accompanying_high_latitude")
LIMITED_BANDS: Final = ("cazimi", "combust", "under_beams")
SIDES: Final = ("morning", "evening", "on_the_sun")
LIMIT_SIDES: Final = ("morning", "evening")
RELATIVE_MOTIONS: Final = ("approaching_sun", "separating_from_sun", "no_relative_motion")
CROSSING_DIRECTIONS: Final = ("emerging", "sinking")
INTERVALS: Final = ("stated_civil_hour", "civil_day")
DISC_REASON_CODES: Final = (
    "disc_cazimi_not_requested",
    "profile_has_no_cazimi_band",
    # Swiss phenomena gave no apparent diameter for the Sun at the chart instant.
    "sun_apparent_diameter_unavailable",
)
DAILY_OFFSETS: Final = tuple(range(-7, 8))
RANGE_SAMPLING: Final = "every_half_hour_and_both_ends_unwrapped_from_the_first_sample"

# A limit in whole arcseconds and whether the edge itself belongs to the band.
_Limit = tuple[int, bool]
_ARCSEC_PER_DEGREE: Final = 3600


def _deg(value: float) -> int:
    return int(round(value * _ARCSEC_PER_DEGREE))


# Profile rules.  `limits` maps a band to a limit per body key ("*" for every
# listed body).  A limit is an (arcseconds, inclusive) pair, or a mapping that
# splits it by side ({"morning": ..., "evening": ...}) or by the planet's own
# motion ({"direct": ..., "retrograde": ...}).  A band missing from a profile
# does not exist in it; the outermost band is always under_beams.
_BIRUNI_COMBUST = (_deg(6), True)
PROFILES: Final[dict[str, dict]] = {
    "lilly_1647_p113_v1": {
        "limits": {
            "cazimi": {"*": (17 * 60, True)},
            "combust": {"*": (_deg(8.5), True)},
            "under_beams": {"*": (_deg(17), True)},
        },
        "venus_latitude_exception_degrees": None,
    },
    "hellenistic_15_v1": {
        "limits": {
            "under_beams": {"*": (_deg(15), True)},
        },
        "venus_latitude_exception_degrees": None,
    },
    # Book of Instruction §481-484, as stated in METHOD_SOURCE_ENTRIES "profiles".
    "biruni_wright_v1": {
        "limits": {
            "cazimi": {"*": (16 * 60, False)},
            "combust": {
                "*": _BIRUNI_COMBUST,
                "mercury": {"direct": (_deg(7), True), "retrograde": _BIRUNI_COMBUST},
                "venus": {"direct": (_deg(7), True), "retrograde": _BIRUNI_COMBUST},
                "moon": (_deg(7), False),
            },
            "under_beams": {
                "mercury": (_deg(12), True),
                "venus": (_deg(12), True),
                "mars": {"morning": (_deg(16), True), "evening": (_deg(18), True)},
                "jupiter": {"morning": (_deg(15), True), "evening": (_deg(16), True)},
                "saturn": {"morning": (_deg(15), True), "evening": (_deg(16), True)},
                "moon": (_deg(12), True),
            },
        },
        "venus_latitude_exception_degrees": 7,
    },
}
MOTIONS: Final = ("direct", "retrograde")

# Stepping: the fastest relative motion of a planet against the Sun is
# Mercury's near inferior conjunction (about 2.4°/day), 0.3° per eighth of a
# day; the Moon gains about 12-15°/day, 0.3° per 1/48 day.
SEARCH_WINDOW_DAYS: Final = 7.0
PLANET_STEP_DAYS: Final = 0.125
INTERVAL_STEP_DAYS: Final = 1.0 / 48.0
TOLERANCE_DAYS: Final = 1.0e-6


def _limit_spec(profile: str, band: str, key: str):
    per_body = PROFILES[profile]["limits"].get(band)
    if per_body is None:
        return None
    return per_body.get(key, per_body.get("*"))


def _resolve(spec, side: str, motion: str):
    """Narrow a limit spec to one (arcseconds, inclusive) pair."""

    while isinstance(spec, dict):
        spec = spec["evening" if side == "evening" else "morning"] if "morning" in spec else spec[motion]
    return spec


def _leaves(spec) -> list:
    if spec is None:
        return []
    if isinstance(spec, dict):
        return [leaf for value in spec.values() for leaf in _leaves(value)]
    return [spec]


def _limit(profile: str, band: str, key: str, side: str, motion: str = "direct") -> _Limit | None:
    spec = _limit_spec(profile, band, key)
    return None if spec is None else _resolve(spec, side, motion)


def _limit_degrees(profile: str, band: str, key: str, side: str) -> float | None:
    limit = _limit(profile, band, key, side)
    return None if limit is None else limit[0] / _ARCSEC_PER_DEGREE


def _inside_limit(distance: Fraction, limit: _Limit | None) -> bool:
    if limit is None:
        return False
    arcsec, inclusive = limit
    edge = Fraction(arcsec, _ARCSEC_PER_DEGREE)
    return distance <= edge if inclusive else distance < edge


def profile_has_cazimi(profile: str) -> bool:
    return "cazimi" in PROFILES[profile]["limits"]


def angular_separation_degrees(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle distance by the haversine form (stable near zero)."""

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = phi2 - phi1
    dlam = math.radians(wrap_to_signed_180(lon2 - lon1))
    h = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(h))))


def _side(longitude_difference: float) -> str:
    if longitude_difference < 0:
        return SIDES[0]
    if longitude_difference > 0:
        return SIDES[1]
    return SIDES[2]


def side_of_sun(longitude: float, sun_longitude: float) -> str:
    """The side of the Sun a body stands on, by its longitude difference."""

    return _side(wrap_to_signed_180(longitude - sun_longitude))


def classify(
    profile: str,
    key: str,
    *,
    longitude_difference: float,
    latitude: float,
    separation: float,
    sun_semidiameter: float | None,
    disc_cazimi: bool,
    motion: str = "direct",
) -> str:
    """The band of one body, by the profile's limits on |Δλ| for its side and
    its own motion (direct or retrograde)."""

    distance = abs(Fraction(longitude_difference))
    side = _side(longitude_difference)
    if disc_cazimi and profile_has_cazimi(profile):
        if sun_semidiameter is None:
            raise ValueError("the solar-disc cazimi needs the Sun's semidiameter")
        band = "cazimi" if separation <= sun_semidiameter else None
    else:
        band = "cazimi" if _inside_limit(distance, _limit(profile, "cazimi", key, side, motion)) else None
    if band is None:
        if _inside_limit(distance, _limit(profile, "combust", key, side, motion)):
            band = "combust"
        elif _inside_limit(distance, _limit(profile, "under_beams", key, side, motion)):
            band = "under_beams"
        else:
            band = "clear"
    exception = PROFILES[profile]["venus_latitude_exception_degrees"]
    if (
        exception is not None
        and key == "venus"
        and latitude > exception
        and band in ("cazimi", "combust")
    ):
        band = "accompanying_high_latitude"
    return band


def _relative_motion(longitude_difference: float, body_speed: float, sun_speed: float) -> str:
    rate = math.copysign(1.0, longitude_difference) * (body_speed - sun_speed)
    if longitude_difference == 0 or rate == 0:
        return RELATIVE_MOTIONS[2]
    return RELATIVE_MOTIONS[1] if rate > 0 else RELATIVE_MOTIONS[0]


def _limit_record(spec) -> dict | None:
    if spec is None:
        return None
    if isinstance(spec, dict) and "direct" in spec:
        return {motion: _limit_record(spec[motion]) for motion in MOTIONS}
    return {"degrees": spec[0] / _ARCSEC_PER_DEGREE, "inclusive": spec[1]}


def limits_table(profile: str) -> dict:
    """Every listed body's limits on each side under the profile; a limit that
    depends on the planet's own motion is split into direct and retrograde."""

    def on_side(spec, side):
        if isinstance(spec, dict) and "morning" in spec:
            return spec["evening" if side == "evening" else "morning"]
        return spec

    return {
        key: {
            side: {
                band: _limit_record(on_side(_limit_spec(profile, band, key), side))
                for band in LIMITED_BANDS
            }
            for side in LIMIT_SIDES
        }
        for key, _body_id in LISTED_BODIES
    }


EclipticSampler = Callable[[int, float], tuple[float, float]]


@dataclass(frozen=True)
class EventClock:
    """The chart instant and how to read and label other instants around it.

    ``sample`` reads effective longitudes at further instants; ``instant_of``
    labels a found crossing; ``interval`` and ``interval_spans`` are a
    non-exact birth time's stretches.
    """

    time_basis: str
    jd_ut: float
    instant_of: Callable[[float], dict]
    sample: EclipticSampler
    interval: str | None = None
    interval_spans: list[tuple[float, float]] | None = None


def make_ecliptic_sampler(flags: int, moon_flags: int) -> EclipticSampler:
    """(body, JD UT) -> (longitude, latitude), in the chart's own flags.

    One Swiss call per (body, instant) within one chart; the Moon uses the
    effective Moon's flags (topocentric under the Moon-only profile).
    """

    cache: dict[tuple[int, float], tuple[float, float]] = {}

    def at(body: int, jd_ut: float) -> tuple[float, float]:
        cached = cache.get((body, jd_ut))
        if cached is not None:
            return cached
        effective = moon_flags if body == swe.MOON else flags
        values, _ = guarded_calc(jd_ut, body, effective, f"焦傷與光束下搜尋（Swiss body {body} 黃經黃緯）")
        cache[(body, jd_ut)] = (values[0], values[1])
        return cache[(body, jd_ut)]

    return at


def sun_semidiameter_at(jd_ut: float, flags: int) -> float:
    return swe.pheno_ut(jd_ut, swe.SUN, flags)[3] / 2.0


def _motion_at(sample: EclipticSampler, body: int, jd_ut: float) -> str:
    """Direct or retrograde, from the longitude an hour either side."""

    change = wrap_to_signed_180(sample(body, jd_ut + 1 / 24)[0] - sample(body, jd_ut - 1 / 24)[0])
    return MOTIONS[1] if change < 0 else MOTIONS[0]


def _state_at(sample: EclipticSampler, body: int, jd_ut: float) -> tuple[float, float, float]:
    lon, lat = sample(body, jd_ut)
    sun_lon, sun_lat = sample(swe.SUN, jd_ut)
    return (
        wrap_to_signed_180(lon - sun_lon),
        lat,
        angular_separation_degrees(lon, lat, sun_lon, sun_lat),
    )


def _beam_crossings(
    sample: EclipticSampler, body: int, key: str, profile: str, jd_ut: float,
    instant_of: Callable[[float], dict],
) -> list[dict]:
    """Crossings of the profile's under-the-beams limit (on the side the body
    is on at that moment) within 7 days of the chart instant.

    The search grid is fixed in absolute time and each crossing is printed no
    finer than the bisection determines it (``solved_instant``), so the same
    crossing reads the same whichever instant anchors the search."""

    def threshold(dl: float) -> float:
        value = _limit_degrees(profile, "under_beams", key, _side(dl))
        if value is None:
            raise InternalInvariantError("value is not None")
        return value

    def outside_by(jd: float) -> float:
        dl = _state_at(sample, body, jd)[0]
        return abs(dl) - threshold(dl)

    roots = find_crossings_around(
        outside_by,
        center_jd=jd_ut,
        half_window_days=SEARCH_WINDOW_DAYS,
        coarse_step_days=PLANET_STEP_DAYS,
        tolerance_days=TOLERANCE_DAYS,
    )
    crossings = []
    for root in roots:
        bracket = root["bracket"]
        low, high = bracket["low_offset_degrees"], bracket["high_offset_degrees"]
        if low == high:
            # A sample landed on the root: read the direction off its neighbours.
            low = outside_by(root["jd"] - 1e-4)
            high = outside_by(root["jd"] + 1e-4)
        if low == high or (low > 0) == (high > 0):
            continue  # a touch, not a crossing
        second, instant = solved_instant(root["jd"], TOLERANCE_DAYS, instant_of)
        crossings.append({
            "direction": CROSSING_DIRECTIONS[0] if high > low else CROSSING_DIRECTIONS[1],
            "threshold_degrees": threshold(_state_at(sample, body, root["jd"])[0]),
            "day_offset": second - jd_ut,
            "instant": instant,
        })
    return crossings


def _side_edge(
    sample: EclipticSampler, body: int, degrees: float, side: str
) -> Callable[[float], float]:
    """|Δλ| minus a limit on one side; on the other side it stays negative, so
    its only zeros are crossings of that side's limit."""

    def edge(jd: float) -> float:
        dl = _state_at(sample, body, jd)[0]
        return abs(dl) - degrees if _side(dl) in (side, SIDES[2]) else -degrees

    return edge


def _offset_edge(value: Callable[[float], float], offset: float) -> Callable[[float], float]:
    """value(jd) − offset: a root where the value crosses the offset."""

    return lambda jd: value(jd) - offset


def _shifted_edge(edge: Callable[[float], float], start: float) -> Callable[[float], float]:
    """The edge read from `start`: the root finder counts time from zero."""

    return lambda t: edge(start + t)


def _interval_cuts(
    sample: EclipticSampler,
    body: int,
    key: str,
    spans: list[tuple[float, float]],
    *,
    disc: bool,
    sun_flags: int,
) -> list[list[float]]:
    """Per span, the instants where any band edge of any profile is crossed,
    with the span's ends: between two cuts no profile changes band."""

    edges: list[Callable[[float], float]] = []
    for profile in PROFILE_IDS:
        for band in LIMITED_BANDS:
            if band == "cazimi" and disc and profile_has_cazimi(profile):
                continue
            spec = _limit_spec(profile, band, key)
            for side in LIMIT_SIDES:
                side_spec = spec[side] if isinstance(spec, dict) and "morning" in spec else spec
                for arcsec, _inclusive in _leaves(side_spec):
                    edges.append(_side_edge(sample, body, arcsec / _ARCSEC_PER_DEGREE, side))
        exception = PROFILES[profile]["venus_latitude_exception_degrees"]
        if exception is not None and key == "venus":
            edges.append(_offset_edge(lambda jd: _state_at(sample, body, jd)[1], exception))
    if disc:
        edges.append(
            lambda jd: _state_at(sample, body, jd)[2] - sun_semidiameter_at(jd, sun_flags)
        )
    out = []
    for start, end in spans:
        instants = []
        for edge in edges:
            instants += [
                start + root["t"]
                for root in find_crossings_detailed(
                    _shifted_edge(edge, start),
                    window_days=end - start,
                    coarse_step_days=INTERVAL_STEP_DAYS,
                    tolerance_days=TOLERANCE_DAYS,
                )
            ]
        out.append(sorted({start, *(t for t in instants if start < t < end), end}))
    return out


def _interval_record(
    sample: EclipticSampler,
    body: int,
    key: str,
    spans: list[tuple[float, float]],
    *,
    disc_requested: bool,
    sun_flags: int,
) -> dict:
    """Every band each profile puts the body in over the stretches, and the
    least and greatest Δλ reached."""

    # A station changes only al-Bīrūnī's combust limit of Mercury and Venus
    # (7° direct, 6° retrograde), and they station far outside 7° of the Sun,
    # so a station is never a band edge.
    cuts = _interval_cuts(
        sample, body, key, spans, disc=disc_requested, sun_flags=sun_flags
    )
    seen: dict[str, list[str]] = {profile: [] for profile in PROFILE_IDS}
    for span_cuts in cuts:
        probes = [span_cuts[0]] + [(a + b) / 2.0 for a, b in zip(span_cuts, span_cuts[1:])]
        for jd in probes:
            dl, lat, sep = _state_at(sample, body, jd)
            for profile in PROFILE_IDS:
                disc = disc_requested and profile_has_cazimi(profile)
                band = classify(
                    profile, key, longitude_difference=dl, latitude=lat, separation=sep,
                    sun_semidiameter=sun_semidiameter_at(jd, sun_flags) if disc else None,
                    disc_cazimi=disc, motion=_motion_at(sample, body, jd),
                )
                if band not in seen[profile]:
                    seen[profile].append(band)
    # The range of Δλ: continuous along the path (no jump at ±180°), sampled
    # every half hour and at both ends of each stretch.
    path: list[float] = []
    for start, end in spans:
        steps = max(1, math.ceil((end - start) / INTERVAL_STEP_DAYS))
        for index in range(steps + 1):
            jd = min(end, start + index * INTERVAL_STEP_DAYS)
            dl = _state_at(sample, body, jd)[0]
            path.append(dl if not path else path[-1] + wrap_to_signed_180(dl - path[-1]))
    return {
        "bands_seen": seen,
        "longitude_difference_min_degrees": min(path),
        "longitude_difference_max_degrees": max(path),
    }


def _band(profile: str, body: dict, dl: float, separation: float,
          sun_semidiameter: float | None, disc_requested: bool) -> str:
    disc = disc_requested and profile_has_cazimi(profile)
    return classify(
        profile, body["key"], longitude_difference=dl, latitude=body["latitude"],
        separation=separation, sun_semidiameter=sun_semidiameter if disc else None,
        disc_cazimi=disc, motion=MOTIONS[1] if body["speed_longitude"] < 0 else MOTIONS[0],
    )


def _disc_receipt(requested: bool, profile: str) -> dict:
    if not requested:
        return module_state(
            requested=False, executed=False, applicable=False, available=False,
            reason_code=DISC_REASON_CODES[0],
        )
    if not profile_has_cazimi(profile):
        return module_state(
            requested=True, executed=False, applicable=False, available=False,
            reason_code=DISC_REASON_CODES[1],
        )
    return computed_receipt(PRODUCT_FORMULA_SOURCE)


def _empty_profile_results(disc_cazimi: bool, interval: str | None) -> dict[str, dict]:
    """Every profile's limits and empty per-body tables, filled body by body."""

    return {
        pid: {
            "limits": limits_table(pid),
            "venus_latitude_exception_degrees": PROFILES[pid]["venus_latitude_exception_degrees"],
            "disc_cazimi_applied": disc_cazimi and profile_has_cazimi(pid),
            "bands": {},
            "beam_crossings_within_7_days": {},
            "bands_seen_in_birth_time_interval": None if interval is None else {},
        }
        for pid in PROFILE_IDS
    }


def _seven_day_search(time_basis: str) -> dict:
    return {
        "window_days": SEARCH_WINDOW_DAYS,
        "bodies": list(SEARCHED_BODIES),
        "threshold_rule": "profile_under_beams_limit_on_the_side_crossed",
        "stations": "not_searched",
        "solver": SOLVER_NAME,
        "coarse_step_days": PLANET_STEP_DAYS,
        "reference_instant": time_basis,
    }


def compute_solar_phase(
    bodies: list[dict],
    trace: Trace,
    *,
    profile: str,
    disc_cazimi: bool,
    moon_center: str,
    sun_flags: int,
    clock: EventClock,
) -> dict:
    """Every listed body's distance from the Sun and its band under every
    profile; ``rows`` carry the selected ``profile``.

    ``bodies`` are the chart's effective body records at ``jd_ut``; ``sample``
    reads further instants in the same flags for the daily series, the 7-day
    search and a non-exact birth time's ``interval_spans``; ``instant_of``
    labels a found crossing with its UTC and birth-place time.
    """

    time_basis, jd_ut, instant_of = clock.time_basis, clock.jd_ut, clock.instant_of
    sample, interval, interval_spans = clock.sample, clock.interval, clock.interval_spans
    by_key = {body["key"]: body for body in bodies}
    sun = by_key["sun"]
    diameter = sun.get("apparent_diameter")
    sun_semidiameter = diameter / 2.0 if diameter is not None else None
    # Without the Sun's diameter the disc reading cannot be made: it is
    # reported unavailable and the profile's own limits apply alone.
    disc_unavailable = disc_cazimi and sun_semidiameter is None and profile_has_cazimi(profile)
    if disc_unavailable:
        disc_cazimi = False
    listed = [
        (key, body_id, by_key[key]) for key, body_id in LISTED_BODIES
        if key in by_key and by_key[key].get("longitude") is not None
    ]
    if interval is not None and (interval not in INTERVALS or not interval_spans):
        raise ValueError("a non-exact birth time needs its interval and its stretches")

    profile_results = _empty_profile_results(disc_cazimi, interval)
    rows = []
    interval_rows = []
    for key, body_id, body in listed:
        dl = wrap_to_signed_180(body["longitude"] - sun["longitude"])
        separation = angular_separation_degrees(
            body["longitude"], body["latitude"], sun["longitude"], sun["latitude"]
        )
        side = side_of_sun(body["longitude"], sun["longitude"])
        for pid in PROFILE_IDS:
            result = profile_results[pid]
            result["bands"][key] = _band(pid, body, dl, separation, sun_semidiameter, disc_cazimi)
            result["beam_crossings_within_7_days"][key] = (
                _beam_crossings(sample, body_id, key, pid, jd_ut, instant_of)
                if key in SEARCHED_BODIES else None
            )
        rows.append({
            "key": key,
            "name": body["name"],
            "longitude_difference_degrees": dl,
            "longitude_difference_text": dms_text(abs(dl)),
            "angular_separation_degrees": separation,
            "ecliptic_latitude_degrees": body["latitude"],
            "side": side,
            "relative_motion": _relative_motion(dl, body["speed_longitude"], sun["speed_longitude"]),
            "same_sign_as_sun": zodiac_sign_index(body["longitude"]) == zodiac_sign_index(sun["longitude"]),
            "within_solar_disc": (
                separation <= sun_semidiameter if sun_semidiameter is not None else None
            ),
            "band": profile_results[profile]["bands"][key],
            "limits_applied": limits_table(profile)[key][
                "evening" if side == "evening" else "morning"
            ],
            "beam_crossings_within_7_days": profile_results[profile]["beam_crossings_within_7_days"][key],
            "daily_longitude_differences": [
                {"day_offset": offset, "longitude_difference_degrees": _state_at(
                    sample, body_id, jd_ut + offset)[0]}
                for offset in DAILY_OFFSETS
            ],
        })
        if interval is not None:
            if interval_spans is None:
                raise InternalInvariantError("interval_spans is not None")
            record = _interval_record(
                sample, body_id, key, interval_spans,
                disc_requested=disc_cazimi, sun_flags=sun_flags,
            )
            for pid in PROFILE_IDS:
                profile_results[pid]["bands_seen_in_birth_time_interval"][key] = (
                    record["bands_seen"][pid]
                )
            interval_rows.append({
                "key": key,
                "name": body["name"],
                "bands_seen": record["bands_seen"][profile],
                "stable": len(record["bands_seen"][profile]) == 1,
                "longitude_difference_min_degrees": record["longitude_difference_min_degrees"],
                "longitude_difference_max_degrees": record["longitude_difference_max_degrees"],
            })
    disc = (
        module_state(
            requested=True, executed=True, applicable=True, available=False,
            reason_code=DISC_REASON_CODES[2],
        )
        if disc_unavailable
        else _disc_receipt(disc_cazimi, profile)
    )
    trace.add(
        "各行星離太陽多遠（焦傷與光束下）",
        formula=(
            "Δλ＝行星黃經－太陽黃經，化到 (−180°, 180°]；距離帶依 |Δλ| 與所選分法在該側的界線判定；"
            "三維角距與黃緯照列，不參與判定"
            + ("；日輪內改以三維角距 ≤ 太陽視半徑判定" if disc["applicable"] else "")
        ),
        inputs={"profile": profile, "disc_cazimi": disc_cazimi, "moon_center": moon_center},
        result={row["key"]: {"Δλ": row["longitude_difference_degrees"], "band": row["band"]}
                for row in rows},
        note="照原典列出各分法的距離帶；不替這張盤做個人解讀，也不預測。",
    )
    return {
        **method_head(METHOD, "solar_phase", source_ref=SOURCE_REF),
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "profile": profile,
        "decision_basis": DECISION_BASIS,
        "same_sign_rule": SAME_SIGN_RULE,
        "disc_cazimi": disc,
        "moon_center": moon_center,
        "time_basis": time_basis,
        "sun": {
            "longitude": sun["longitude"],
            "semidiameter_degrees": sun_semidiameter,
        },
        "scope": {"listed": [key for key, _ in LISTED_BODIES], "not_listed": list(NOT_LISTED)},
        "rows": rows,
        "profile_results": profile_results,
        "seven_day_search": _seven_day_search(time_basis),
        "birth_time_interval": (
            None if interval is None
            else {"interval": interval, "range_sampling": RANGE_SAMPLING, "rows": interval_rows}
        ),
    }


def solar_phase_not_applicable(state: dict, trace: Trace) -> dict:
    refusal = frame_table_refusal(
        state, trace, "各行星離太陽多遠（焦傷與光束下）",
        note="參考框架相容表判定不適用：日心、質心沒有從地球看到的太陽，不換框架重算。",
    )
    return solar_phase_unavailable(refusal)


def solar_phase_unavailable(receipt: dict) -> dict:
    """The module with no result, under the six state fields given."""

    return {
        **method_head(METHOD, "solar_phase", source_ref=SOURCE_REF),
        **{field: receipt[field] for field in STATE_FIELDS},
        "profile": None,
        "decision_basis": DECISION_BASIS,
        "same_sign_rule": SAME_SIGN_RULE,
        "disc_cazimi": None,
        "moon_center": None,
        "time_basis": None,
        "sun": None,
        "scope": None,
        "rows": [],
        "profile_results": None,
        "seven_day_search": None,
        "birth_time_interval": None,
    }



METHOD_SOURCE_ENTRIES: Final = {
    SOURCE_REF: {
        "applies_to": "derived_methods.solar_phase",
        "definition": (
            "The signed difference of ecliptic longitude, body minus Sun, in (-180, 180]; "
            "the band is read from |difference| against the profile's limits for the side "
            "the body is on (negative: west of the Sun, rising before it, the morning side). "
            "The true angular separation and the ecliptic latitude are listed and decide "
            "nothing, except the optional solar-disc cazimi (separation at most the Sun's "
            "apparent semidiameter at that instant), which changes only the cazimi band. "
            "Listed: the Moon and the five planets. All three profiles are computed; the "
            "selected one fills rows[]."
        ),
        "decision_basis_argument": (
            "Inference by this product, not a statement found in a source: al-Biruni "
            "(Book of Instruction §483) says a Venus whose north latitude exceeds 7 degrees "
            "at the conjunction is to be called neither samim nor combust but 'accompanying "
            "the Sun', and that at her greatest north latitude she remains visible; Abu "
            "Ma'shar (Great Introduction VII.2, Latin of Hermann of Carinthia) says Venus "
            "can be seen 'ex eodem cum Sole gradu' because of her latitude and is then not "
            "to be called burnt but appearing. Had these authors measured the true distance "
            "on the sky, such a Venus would already be 7-8 degrees from the Sun, outside "
            "16 minutes and outside 6 degrees, and no exception would be needed; the "
            "exception is needed because the distance they read is in degrees of the zodiac "
            "(longitude), on which this Venus stands in the Sun's own degree."
        ),
        "profiles": {
            "lilly_1647_p113_v1": (
                "Lilly 1647 p.113: cazimi within 17 minutes, combust within 8 deg 30 min, "
                "under the Sun-beams until 17 degrees; every limit inclusive; the same "
                "numbers for every body and side. The default."
            ),
            "hellenistic_15_v1": (
                "One band, under the beams within 15 degrees on either side; no cazimi or "
                "combust band (Porphyry, Antiochus as reported by Brennan 2017)."
            ),
            "biruni_wright_v1": (
                "al-Biruni §481-484: samim under 16 minutes (exclusive); combust to 6 "
                "degrees, to 7 degrees for Mercury and Venus in direct motion (§482); "
                "the Moon combust under 7 degrees and under the rays to 12 degrees "
                "(§484); under the rays rising in the east (morning side) to 12 Venus and "
                "Mercury, 15 Saturn and Jupiter, 16 Mars, setting in the west (evening "
                "side) from 16 Saturn and Jupiter, 18 Mars; Mercury and Venus take 12 on "
                "both sides, since §482 says only that their west 'resembles' the "
                "superior planets'; Venus north of 7 degrees latitude in the samim or "
                "combust band is 'accompanying the Sun' (§483)."
            ),
        },
        "default_profile": DEFAULT_SOLAR_PHASE_PROFILE,
        "default_basis": (
            "Lilly p.113 was read in the 1647 text, gives a limit for every band, and "
            "halves the Sun's orb of 17 degrees (p.107) that the product's default aspect "
            "orbs already use. Lilly himself writes 12 degrees and 16 minutes in aphorism "
            "26 (p.300 as cited by Houlding; no page number in the transcription read); "
            "that disagreement is disclosed, not resolved."
        ),
        "same_sign_rule": (
            "Lilly p.113-114: combustion only by bodily conjunction in one sign, not by "
            "aspect. No other source read has the rule and Lilly's aphorism 26 puts a "
            "planet under the beams 'in what Signe it will'; the product reports "
            "same_sign_as_sun and does not apply the rule. In the sidereal zodiac only "
            "this flag can differ; the distance and the band cannot."
        ),
        "seven_day_rule": (
            "For the five planets, every crossing of the profile's under-the-beams limit "
            "within 7 days before or after the chart instant, emerging or sinking; "
            "stations not searched; the Moon not searched. The 7-day rule is reported "
            "from Porphyry, Introduction ch.30 and Rhetorius (Holden 2009 pp.24, 134) "
            "via a secondary page; the original was not read."
        ),
        "doctrine": [
            "Lilly 1647 p.111: 'the combustion of any Planet is the greatest misfortune "
            "that can be'",
            "Lilly 1647 p.113: when the Sun applies to the planet it is more afflicted "
            "than when the Sun separates from it; 'all Authors doe hold a Planet in "
            "Cazimi to be fortified thereby'",
            "Lilly aphorism 26: under the beams within 12 degrees it 'hath no "
            "fortitude'; within 16 minutes in Cazimi it is 'wonderous strong'",
            "al-Biruni §481: under the rays 'they remain like prisoners in "
            "confinement'; §486: the influence 'is at its minimum in combustion'",
            "Abu Ma'shar, Great Introduction VII.2 (Latin): the Sun burns, weakens and "
            "corrupts every star joined to it except one in zamim",
            "Ptolemy, Tetrabiblos III.10 (Robbins p.285): no planet under the rays of "
            "the Sun is admitted to destroy or to aid",
        ],
        "sources": [
            cited("William Lilly, Christian Astrology (London 1647) Book I, pp.111, 113-114", None,
                  ORIGINAL_LANGUAGE_READ,
                  ("archive.org full text of the 1647 printing and of a 1659 transcription; "
                   "pp.111 and 113 not checked on the scan. The p.115 table of fortitudes "
                   "and debilities was read on the scan (Wellcome Library copy, "
                   "archive.org b30338724 n148); it is cited under motion_states")),
            cited("William Lilly, Christian Astrology, aphorism 26 (p.300 per Houlding)", None,
                  ORIGINAL_LANGUAGE_READ,
                  "archive.org 1659 transcription; page number from Houlding"),
            cited(("al-Biruni, The Book of Instruction in the Elements of the Art of "
                   "Astrology, trans. R. Ramsay Wright (London 1934) §481-486"),
                  None, TRANSLATION_READ,
                  ("archive.org typescript OCR (the Skyscript facsimile, pp.88-93 of the "
                   "facsimile); the 1934 page numbers not checked")),
            cited(("Abu Ma'shar, Great Introduction VII.2, Latin of Hermann of Carinthia "
                   "(Liber introductorius maior), Wurzburg Arabic-Latin Corpus lines 130_123-126; "
                   "English: Dykes's translation p.418, publication year not checked"),
                  None, TRANSLATION_READ,
                  ("Hermann's Latin translation read online, the Arabic not read; "
                   "Dykes's English only as cited by Tony Louis")),
            cited("Ptolemy, Tetrabiblos III.10, trans. Robbins (Loeb 1940) p.285", None,
                  TRANSLATION_READ, "LacusCurtius transcription"),
            cited(("Porphyry, Introduction ch.2 and ch.30; Antiochus; Rhetorius "
                   "(Holden 2009 pp.24, 134); Brennan, Hellenistic Astrology (2017)"),
                  None, SECONDARY_ONLY, "secondary pages and search excerpts only"),
            cited(("William Lilly, Christian Astrology (1647) Book I ch. XIX p.107, "
                   "first column"),
                  "the Sun's orb of 17 degrees, which the default limits halve",
                  ORIGINAL_LANGUAGE_READ, "the first edition (archive.org/details/b30338724)"),
            cited("Bonatti, as given in Dykes 2007 p.211",
                  "cazimi requires the latitude as well as the longitude within 16 minutes",
                  SECONDARY_ONLY,
                  "Dykes 2007, a secondary report; Bonatti's Latin not read"),
        ],
        "not_applied": (
            "Bonatti and al-Qabisi require the latitude as well as the longitude within "
            "16 minutes for cazimi (al-Qabisi Introduction III, John of Seville's Latin translation read; Bonatti via "
            "Dykes 2007 p.211, secondary); the optional solar-disc reading comes close but "
            "is not their rule. Abu Ma'shar's own limits (combust 6 degrees, Mars 10; "
            "under the rays east 15, Mars 18) are not offered as a profile. Visibility "
            "by place and atmosphere (Swiss heliacal functions) is not computed."
        ),
        "boundary_rule": (
            "membership by exact rational comparison of the float |difference| with the "
            "limit in whole arcseconds; each limit inclusive or exclusive as worded"
        ),
        "interval_rule": (
            "for a non-exact birth time, every band each profile puts each body in over "
            "the stated hour or civil day, from the roots of every band edge; the least "
            "and greatest difference over it sampled every half hour and at the ends"
        ),
        "interval_vocabulary": list(INTERVALS),
    },
}
