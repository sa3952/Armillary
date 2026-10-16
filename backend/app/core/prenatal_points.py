"""The prenatal syzygy's degree and the eclipses around the birth.

Two event searches already exist in ``lunar_events``: the nearest previous new or
full Moon (the prenatal syzygy) and the previous solar and lunar eclipse.  This
module adds what the classical uses of those events read, and nothing that
turns them into the input of another technique:

* the luminaries' longitudes at the syzygy and the degree Ptolemy's rule takes
  (Tetrabiblos III.2: at a new Moon the common degree; at a full Moon the
  luminary above the earth, judged at the syzygy itself, the reading Robbins
  prints; the manuscript variant judged at birth is reported beside it);
* the named day/night pick of Tetrabiblos III.10 and Lilly (previous new Moon
  for a day birth, previous full Moon for a night birth), listed, not default;
* the eclipse degree, the previous eclipse reaching the umbra beside the
  previous lunar eclipse of any kind, and an eclipse under way at birth.

"Above the horizon" is the product's one criterion, the sect rule's: the
body's centre, geocentric true altitude (no refraction), above 0°, with the
same ±50′ near-horizon band (``lots.classify_sect``).  Inside the band no
luminary is chosen and both degrees stay listed.  Within the band the
alternative boundaries (upper limb, refraction, the Moon's topocentric
parallax of up to about a degree) can decide differently; outside it they do
not change the answer for the Sun, and the Moon's parallax is disclosed in the
register entry.

Every longitude is the lunar events' fixed contract: apparent geocentric
tropical of date.  A sidereal chart also gets the same points in its own zodiac.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

import swisseph as swe

from ..ephemeris import (
    chart_observer_restored,
    require_full_ephemeris,
    require_object_coverage,
)
from .bodies import geocentric_sun_true_altitude, horizontal_position
from .computation_mode import ComputationContext
from .formatting import normalize_longitude, sign_position
from .lots import SECT_NEAR_CRITICAL_DEGREES, classify_sect
from .root_finding import wrap_to_signed_180
from .lunar_events import (
    PHASE_FLAGS,
    PHASES,
    _eclipse_result,
    _phase_event,
    _phase_state,
    previous_phase_strictly_before,
)
from .time_utils import civil_instant
from .source_reading import SOURCE_READING_LEVELS
from .trace import Trace

SYZYGY_DEGREE_SOURCE_REF = "lunar_events/prenatal_syzygy_degree"
SYZYGY_SECT_PROFILE_SOURCE_REF = "lunar_events/prenatal_syzygy_sect_profile"
ECLIPSE_SELECTION_SOURCE_REF = "eclipses/prenatal_selection"

DEGREE_SELECTION_PROFILE = "ptolemy_tetrabiblos_iii_2_luminary_above_horizon_at_syzygy"
DEGREE_SELECTION_STATES = (
    "conjunction_degree",
    "selected",
    "near_horizon_not_selected",
    "both_above_horizon_not_selected",
    "both_below_horizon_not_selected",
    "not_applicable_no_horizon",
)
HORIZON_CRITERION = "body_center_geocentric_true_altitude_gt_zero_same_as_sect"
SECT_PROFILE = "ptolemy_iii_10_and_lilly_day_previous_new_moon_night_previous_full_moon"
SECT_PROFILE_STATES = (
    "selected",
    "sect_near_horizon_not_selected",
    "sect_unavailable_not_selected",
)
OTHER_SYZYGY_STATES = ("computed", "outside_ephemeris_coverage")
# A syzygy this close before birth can move to the one before it when the
# recorded birth time is a few minutes off.
NEAR_BIRTH_THRESHOLD_HOURS = 1.0
AT_BIRTH_REFERENCES = ("birth_instant", "representative_anchor_not_birth_instant")
LUMINARIES_AT_BIRTH_STATES = (
    "computed",
    "withheld_date_only",
    "not_applicable_no_horizon",
)
UMBRAL_RELATIONS = ("same_eclipse_as_previous_lunar", "earlier_than_previous_lunar")
IN_PROGRESS_RELATIONS = ("maximum_after_birth", "maximum_at_or_before_birth")

_NEAR_REFERENCE_ELONGATION_DEGREES = 1e-6


@dataclass(frozen=True)
class PrenatalPlace:
    """The chart facts these points read: observer, horizon, zodiac and clock."""

    context: ComputationContext
    atmosphere: object
    timezone: object
    precision: str


def _luminaries(jd_ut: float, operation: str) -> tuple[tuple, tuple]:
    """Sun and Moon at one instant under the lunar events' flags."""

    for body in (swe.SUN, swe.MOON):
        require_object_coverage(body=body, flags=PHASE_FLAGS, jd_ut=jd_ut, operation=operation)
    sun, sun_flag = swe.calc_ut(jd_ut, swe.SUN, PHASE_FLAGS)
    moon, moon_flag = swe.calc_ut(jd_ut, swe.MOON, PHASE_FLAGS)
    require_full_ephemeris(sun_flag, operation=operation, jd_ut=jd_ut)
    require_full_ephemeris(moon_flag, operation=operation, jd_ut=jd_ut)
    return tuple(sun), tuple(moon)


def _chart_zodiac(jd_ut: float, place: PrenatalPlace, longitudes: dict) -> dict | None:
    """The same points in a sidereal chart's own zodiac; None for a tropical chart.

    The offset is the one this flag set actually subtracts (the tropical minus
    sidereal longitude of the Sun at that instant), so the sidereal values are
    what Swiss gives for these bodies under FLG_SIDEREAL.
    """

    ctx = place.context
    if ctx.mode.zodiac != "sidereal":
        return None
    sidereal_flags = PHASE_FLAGS | swe.FLG_SIDEREAL
    sun_tropical, _ = swe.calc_ut(jd_ut, swe.SUN, PHASE_FLAGS)
    sun_sidereal, flag = swe.calc_ut(jd_ut, swe.SUN, sidereal_flags)
    require_full_ephemeris(flag, operation="產前點（恆星黃道換算）", jd_ut=jd_ut)
    offset = normalize_longitude(sun_tropical[0] - sun_sidereal[0])
    converted = {
        key: normalize_longitude(value - offset) for key, value in longitudes.items()
    }
    return {
        "zodiac": "sidereal",
        "ayanamsa": ctx.mode.ayanamsa,
        "ayanamsa_applied_degrees": offset,
        "longitudes": converted,
        "sign_positions": {key: sign_position(value) for key, value in converted.items()},
    }


def _true_altitudes(jd_ut: float, sun: tuple, moon: tuple, place: PrenatalPlace) -> dict:
    ctx, atmosphere = place.context, place.atmosphere
    return {
        "sun": horizontal_position(jd_ut, ctx, atmosphere, sun)[2],
        "moon": horizontal_position(jd_ut, ctx, atmosphere, moon)[2],
    }


def _horizon_reading(altitudes: dict) -> dict:
    """Above/below and the near-horizon band for both luminaries, by the sect rule."""

    reading = {}
    for body, altitude in altitudes.items():
        classified = classify_sect(altitude)
        reading[body] = {
            "altitude_true_degrees": altitude,
            "above_horizon": classified["is_day"],
            "in_near_horizon_band": classified["in_near_horizon_band"],
        }
    return reading


def _ascendant(jd_ut: float, place: PrenatalPlace) -> float:
    location = place.context.location
    # The ascendant does not depend on the house system; equal houses never fail.
    _cusps, ascmc = swe.houses_ex(jd_ut, location.latitude, location.longitude, b"E")
    return ascmc[0]


def _degree_selection(
    jd_ut: float, phase: str, sun: tuple, moon: tuple, place: PrenatalPlace
) -> dict:
    states = DEGREE_SELECTION_STATES
    base = {
        "profile": DEGREE_SELECTION_PROFILE,
        "source_ref": SYZYGY_DEGREE_SOURCE_REF,
        "criterion": HORIZON_CRITERION,
        "near_horizon_band_half_width_degrees": SECT_NEAR_CRITICAL_DEGREES,
    }
    if not place.context.horizon_meaningful:
        return {
            **base,
            "state": states[0] if phase == "new_moon" else states[5],
            "selected_luminary": "both" if phase == "new_moon" else None,
            "selected_longitude": sun[0] if phase == "new_moon" else None,
            "selected_sign_position": sign_position(sun[0]) if phase == "new_moon" else None,
            "horizon_at_syzygy": None,
        }
    if phase == "new_moon":
        # The common degree needs no horizon reading.
        return {
            **base,
            "state": states[0],
            "selected_luminary": "both",
            "selected_longitude": sun[0],
            "selected_sign_position": sign_position(sun[0]),
            "horizon_at_syzygy": None,
        }
    horizon = _horizon_reading(_true_altitudes(jd_ut, sun, moon, place))
    ascendant = _ascendant(jd_ut, place)
    upper = {
        # Houses 7 to 12: from the descendant through the midheaven to the ascendant.
        body: normalize_longitude(longitude - ascendant) >= 180.0
        for body, longitude in (("sun", sun[0]), ("moon", moon[0]))
    }
    if horizon["sun"]["in_near_horizon_band"] or horizon["moon"]["in_near_horizon_band"]:
        state, luminary = states[2], None
    elif horizon["sun"]["above_horizon"] and horizon["moon"]["above_horizon"]:
        state, luminary = states[3], None
    elif not (horizon["sun"]["above_horizon"] or horizon["moon"]["above_horizon"]):
        state, luminary = states[4], None
    else:
        state = states[1]
        luminary = "sun" if horizon["sun"]["above_horizon"] else "moon"
    longitude = None if luminary is None else {"sun": sun[0], "moon": moon[0]}[luminary]
    return {
        **base,
        "state": state,
        "selected_luminary": luminary,
        "selected_longitude": longitude,
        "selected_sign_position": sign_position(longitude),
        "horizon_at_syzygy": {
            **horizon,
            "ecliptic_hemisphere_check": {
                "ascendant_longitude_at_syzygy": ascendant,
                "sun_in_upper_half": upper["sun"],
                "moon_in_upper_half": upper["moon"],
                "agrees_with_altitude": all(
                    upper[body] == horizon[body]["above_horizon"] for body in ("sun", "moon")
                ),
            },
        },
    }


# Keys this module adds to a syzygy or an eclipse record.  They are functions
# of the event's instant and the chart's fixed place and zodiac, so whether a
# representative sample saw the same event is decided without them (they carry
# the solver's last-bit jitter, which is not a different event).
SYZYGY_ADDED_KEYS = (
    "local_time", "utc_offset", "sun_longitude", "moon_longitude", "moon_latitude",
    "sun_sign_position", "moon_sign_position", "chart_zodiac", "degree_selection",
)
ECLIPSE_ADDED_KEYS = (
    "maximum_local_time", "maximum_utc_offset", "sun_longitude", "moon_longitude",
    "moon_latitude", "eclipsed_luminary", "eclipse_longitude", "eclipse_sign_position",
    "chart_zodiac",
)


def comparable_view(key: str, value):
    """The part of a lunar-events result that identifies the event(s)."""

    if key == "prenatal_syzygy" and isinstance(value, dict):
        return {k: v for k, v in value.items() if k not in SYZYGY_ADDED_KEYS}
    if key == "eclipses" and isinstance(value, dict):
        return {
            slot: (
                {k: v for k, v in record.items() if k not in ECLIPSE_ADDED_KEYS}
                if isinstance(record, dict) else record
            )
            for slot, record in value.items()
        }
    return value


def enrich_syzygy(event: dict, place: PrenatalPlace) -> dict:
    """A syzygy event with its luminaries, local time and Ptolemy's degree."""

    jd_ut = event["jd_ut"]
    sun, moon = _luminaries(jd_ut, "產前朔望（日月位置）")
    civil = civil_instant(jd_ut, place.timezone)
    event.update({
        "local_time": civil["local_time"],
        "utc_offset": civil["utc_offset"],
        "sun_longitude": sun[0],
        "moon_longitude": moon[0],
        "moon_latitude": moon[1],
        "sun_sign_position": sign_position(sun[0]),
        "moon_sign_position": sign_position(moon[0]),
        "chart_zodiac": _chart_zodiac(jd_ut, place, {"sun": sun[0], "moon": moon[0]}),
        "degree_selection": _degree_selection(jd_ut, event["phase"], sun, moon, place),
    })
    return event


def nearest_previous_syzygy(reference_jd_ut: float) -> dict:
    """The prenatal syzygy from its own search, without the other phases.

    The elongation at the reference says which kind came last (it grows
    monotonically): below 180° the new Moon, otherwise the full Moon.  Only that
    event is searched, so a birth soon after the start of the bundled ephemeris
    gets its syzygy although the eight-event phase search reaches out of it.
    Next to a syzygy the kind is not read from the elongation; both are searched,
    each strictly before the reference (a syzygy at the birth instant is not
    prenatal).
    """

    phase_state = cache(_phase_state)
    elongation = phase_state(reference_jd_ut)[0]
    near = min(abs(wrap_to_signed_180(elongation - target)) for target in (0.0, 180.0))
    if near < _NEAR_REFERENCE_ELONGATION_DEGREES:
        events = [
            previous_phase_strictly_before(reference_jd_ut, phase, phase_state)
            for phase in ("new_moon", "full_moon")
        ]
        nearest = max(events, key=lambda event: event["jd_ut"])
    else:
        phase = "new_moon" if elongation < 180.0 else "full_moon"
        nearest = _phase_event(reference_jd_ut, phase, "previous", phase_state)
    return {
        **nearest,
        "definition": "nearest_previous_geocentric_new_or_full_moon",
        "interpretation": None,
    }


def _other_previous_syzygy(reference_jd_ut: float, nearest: dict, place: PrenatalPlace) -> dict:
    from ..ephemeris import FullEphemerisRequiredError

    other_phase = "full_moon" if nearest["phase"] == "new_moon" else "new_moon"
    try:
        event = previous_phase_strictly_before(reference_jd_ut, other_phase)
        enrich_syzygy(event, place)
    except FullEphemerisRequiredError as error:
        if error.reason != "segment_out_of_coverage":
            raise
        return {
            "state": OTHER_SYZYGY_STATES[1], "phase": other_phase,
            "hours_before_birth": None, "event": None,
        }
    return {
        "state": OTHER_SYZYGY_STATES[0],
        "phase": other_phase,
        "hours_before_birth": (reference_jd_ut - event["jd_ut"]) * 24.0,
        "event": event,
    }


def _sect_at(reference_jd_ut: float, place: PrenatalPlace) -> dict:
    if place.precision == "date_only" or not place.context.horizon_meaningful:
        return classify_sect(None)
    return classify_sect(
        geocentric_sun_true_altitude(reference_jd_ut, place.context, place.atmosphere)
    )


def _reference_label(place: PrenatalPlace) -> str:
    return AT_BIRTH_REFERENCES[0] if place.precision == "exact" else AT_BIRTH_REFERENCES[1]


def prenatal_syzygy_at_birth(
    reference_jd_ut: float, nearest: dict, place: PrenatalPlace, trace: Trace
) -> dict:
    """What depends on the birth instant: distance, the day/night pick, and
    which luminaries are above the earth at birth (the manuscript variant)."""

    hours = (reference_jd_ut - nearest["jd_ut"]) * 24.0
    other = _other_previous_syzygy(reference_jd_ut, nearest, place)
    sect = _sect_at(reference_jd_ut, place)
    if sect["sect_status"] is None:
        state, selected_phase = SECT_PROFILE_STATES[2], None
    elif sect["sect_status"] == "boundary_both_shown":
        state, selected_phase = SECT_PROFILE_STATES[1], None
    else:
        state = SECT_PROFILE_STATES[0]
        selected_phase = "new_moon" if sect["is_day"] else "full_moon"
    selected = None
    if selected_phase is not None:
        selected = (
            "prenatal_syzygy" if selected_phase == nearest["phase"]
            else "other_previous_syzygy"
        )

    if place.precision == "date_only":
        luminaries = {"state": LUMINARIES_AT_BIRTH_STATES[1], "sun": None, "moon": None}
    elif not place.context.horizon_meaningful:
        luminaries = {"state": LUMINARIES_AT_BIRTH_STATES[2], "sun": None, "moon": None}
    else:
        sun, moon = _luminaries(reference_jd_ut, "出生時日月的地平高度")
        reading = _horizon_reading(_true_altitudes(reference_jd_ut, sun, moon, place))
        luminaries = {"state": LUMINARIES_AT_BIRTH_STATES[0], **reading}

    trace.add(
        "產前朔望：度數與具名挑法",
        formula=(
            "望時取朔望那一刻在出生地地平線上方的發光體（中心地心真高度 > 0°，"
            f"±{SECT_NEAR_CRITICAL_DEGREES * 60:.0f}′ 內不選）；日生盤取前一次朔、夜生盤取前一次望只並列"
        ),
        inputs={"reference_JD_UT": reference_jd_ut, "phase": nearest["phase"]},
        result={
            "degree_selection": nearest["degree_selection"]["state"],
            "selected_luminary": nearest["degree_selection"]["selected_luminary"],
            "sect_profile": state,
            "hours_before_birth": hours,
        },
        note="只列度數與挑法，不改上升點，也不接到其他技法。",
    )
    return {
        "reference": _reference_label(place),
        "hours_before_birth": hours,
        "near_birth": hours < NEAR_BIRTH_THRESHOLD_HOURS,
        "near_birth_threshold_hours": NEAR_BIRTH_THRESHOLD_HOURS,
        "luminaries_above_horizon_at_birth": luminaries,
        "sect_profile": {
            "profile": SECT_PROFILE,
            "source_ref": SYZYGY_SECT_PROFILE_SOURCE_REF,
            "sect_status": sect["sect_status"],
            "state": state,
            "selected_phase": selected_phase,
            "selected": selected,
            "other_previous_syzygy": other,
        },
        "used_as_input_to_other_techniques": False,
    }


# ── eclipses ───────────────────────────────────────────────────────────────


def _enrich_eclipse(record: dict, place: PrenatalPlace) -> dict:
    jd_ut = record["jd_ut_maximum"]
    sun, moon = _luminaries(jd_ut, "日月食（日月位置）")
    lunar = record["kind"] == "lunar"
    eclipse_longitude = moon[0] if lunar else sun[0]
    civil = civil_instant(jd_ut, place.timezone)
    record.update({
        "maximum_local_time": civil["local_time"],
        "maximum_utc_offset": civil["utc_offset"],
        "sun_longitude": sun[0],
        "moon_longitude": moon[0],
        "moon_latitude": moon[1],
        "eclipsed_luminary": "moon" if lunar else "sun",
        "eclipse_longitude": eclipse_longitude,
        "eclipse_sign_position": sign_position(eclipse_longitude),
        "chart_zodiac": _chart_zodiac(jd_ut, place, {"eclipse": eclipse_longitude}),
    })
    return record


def extend_previous_eclipses(
    eclipses: dict, reference_jd_ut: float, place: PrenatalPlace
) -> dict:
    """Degrees on the two previous eclipses and the previous umbral lunar eclipse."""

    start = math.nextafter(reference_jd_ut, -math.inf)
    umbral_flag, umbral_times = swe.lun_eclipse_when(
        start, swe.FLG_SWIEPH, swe.ECL_PARTIAL | swe.ECL_TOTAL, True
    )
    umbral = _eclipse_result("lunar", umbral_flag, umbral_times)
    for key in ("previous_solar", "previous_lunar"):
        _enrich_eclipse(eclipses[key], place)
    _enrich_eclipse(umbral, place)
    same = abs(umbral["jd_ut_maximum"] - eclipses["previous_lunar"]["jd_ut_maximum"]) < 0.5
    umbral["relation_to_previous_lunar"] = UMBRAL_RELATIONS[0 if same else 1]
    eclipses["previous_umbral_lunar"] = umbral
    eclipses["selection_profile"] = "astronomical_previous_by_maximum"
    eclipses["selection_source_ref"] = ECLIPSE_SELECTION_SOURCE_REF
    return eclipses


# The first and last contacts of the whole eclipse: for a solar eclipse the
# penumbra on the Earth (Swiss tret 2 and 3), for a lunar one the Moon in the
# penumbra (tret 6 and 7).
_OUTER_CONTACTS = {"solar": (2, 3), "lunar": (6, 7)}
_OUTER_CONTACT_LABELS = {
    "solar": ("partial_begin", "partial_end"),
    "lunar": ("penumbral_begin", "penumbral_end"),
}


# Longer than half of any eclipse's outer contacts (a lunar penumbral phase
# lasts at most about 6.3 hours, a global solar one about 6.5): an eclipse
# under way at the birth has its maximum within this many days after it.
_IN_PROGRESS_REACH_DAYS = 0.5


def _eclipse_ending_by(kind: str, reference_jd_ut: float) -> tuple[int, tuple]:
    """The last eclipse of ``kind`` whose maximum is before reference + reach.

    A backward search from just after the birth, not a forward one: a forward
    search runs on to the next eclipse, which near the end of the bundled
    files lies outside them, and Swiss then falls back to Moshier for the rest
    of the request.  The end of the reach is checked against the coverage
    first, and Swiss is reset afterwards all the same.
    """

    from ..ephemeris import reset_swiss_state_for_thread

    start = reference_jd_ut + _IN_PROGRESS_REACH_DAYS
    for body in (swe.SUN, swe.MOON):
        require_object_coverage(
            body=body, flags=swe.FLG_SWIEPH, jd_ut=start,
            operation="出生時正在進行的日月食（搜尋範圍）",
        )
    try:
        if kind == "solar":
            with chart_observer_restored():
                return swe.sol_eclipse_when_glob(start, swe.FLG_SWIEPH, 0, True)
        return swe.lun_eclipse_when(start, swe.FLG_SWIEPH, 0, True)
    finally:
        reset_swiss_state_for_thread()


def eclipses_at_birth(
    eclipses: dict, reference_jd_ut: float, place: PrenatalPlace, trace: Trace
) -> dict:
    """Distance of each previous eclipse, and an eclipse under way at the birth.

    "Previous" stays defined by the maximum before the birth.  An eclipse whose
    first contact is at or before the birth and whose maximum comes after it is
    listed here instead of being skipped; the previous eclipse is flagged too
    when its last contact is still after the birth.
    """

    days = {
        key: reference_jd_ut - eclipses[key]["jd_ut_maximum"]
        for key in ("previous_solar", "previous_lunar", "previous_umbral_lunar")
    }
    in_progress: dict = {}
    for kind in ("solar", "lunar"):
        previous = eclipses[f"previous_{kind}"]
        end_label = _OUTER_CONTACT_LABELS[kind][1]
        end = (previous["contacts"].get(end_label) or {}).get("jd_ut")
        begin_index, _end_index = _OUTER_CONTACTS[kind]
        flag, times = _eclipse_ending_by(kind, reference_jd_ut)
        if 0 < times[begin_index] <= reference_jd_ut < times[0]:
            record = _enrich_eclipse(_eclipse_result(kind, flag, times), place)
            in_progress[kind] = {
                "relation": IN_PROGRESS_RELATIONS[0],
                "maximum_minus_birth_minutes": (times[0] - reference_jd_ut) * 1440.0,
                "same_as": None,
                "eclipse": record,
            }
        elif end is not None and end > reference_jd_ut:
            in_progress[kind] = {
                "relation": IN_PROGRESS_RELATIONS[1],
                "maximum_minus_birth_minutes": (
                    previous["jd_ut_maximum"] - reference_jd_ut
                ) * 1440.0,
                "same_as": f"previous_{kind}",
                "eclipse": None,
            }
        else:
            in_progress[kind] = None
    trace.add(
        "出生前的日月食：度數、本影月食與出生時正在進行的日月食",
        formula=(
            "swe.lun_eclipse_when(ECL_PARTIAL|ECL_TOTAL, backwards=True)；"
            "自出生後半日往回搜尋日食與月食，第一次接觸 ≤ 出生 < 食甚即列為正在進行"
        ),
        inputs={"reference_JD_UT": reference_jd_ut},
        result={
            "previous_umbral_lunar": eclipses["previous_umbral_lunar"]["utc_time_maximum"],
            "in_progress": {kind: (value or {}).get("relation") for kind, value in in_progress.items()},
        },
        note="只回報天文事件與度數，不提供古典占星解讀。",
    )
    return {
        "reference": _reference_label(place),
        "days_before_birth": days,
        "in_progress": in_progress,
        "source_ref": ECLIPSE_SELECTION_SOURCE_REF,
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    SYZYGY_DEGREE_SOURCE_REF: {
        "applies_to": (
            "astronomical_data.lunar_events.prenatal_syzygy.degree_selection and "
            "prenatal_syzygy_at_birth.luminaries_above_horizon_at_birth"
        ),
        "definition": (
            "The prenatal syzygy is the nearest new or full Moon before birth (true "
            "syzygy: apparent geocentric Sun and Moon, tropical of date). At a new Moon "
            "the degree is the common degree of the luminaries. At a full Moon it is the "
            "degree of the luminary above the horizon of the birthplace at the moment of "
            "the syzygy."
        ),
        "horizon_criterion": (
            "the sect rule: the body's centre, geocentric true altitude (no refraction) "
            f"above 0°; within ±{SECT_NEAR_CRITICAL_DEGREES * 60:.0f}′ of the horizon, or "
            "when both or neither luminary is above it, no luminary is chosen and both "
            "degrees are listed. The Moon's topocentric altitude can differ from its "
            "geocentric one by up to about a degree; the geocentric value is used so that "
            "the product has one horizon criterion"
        ),
        "cross_check": (
            "ecliptic hemisphere: whether each luminary's longitude lies between the "
            "descendant and the ascendant through the midheaven at the moment of the "
            "syzygy; reported beside the altitude reading, never used to choose"
        ),
        "sources": [
            {
                "citation": (
                    "Ptolemy, Tetrabiblos III.2 (Robbins, Loeb 1940, pp. 229-235, the syzygy "
                    "rule on pp. 231-233; Hübner III.3)"
                ),
                "says": (
                    "take the degree of the most recent syzygy before birth, at a new Moon the "
                    "degree of both luminaries, at a full Moon that of the luminary above the "
                    "earth; then find the planet that rules that degree"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Robbins's English translation; the Greek not checked",
            },
            {
                "citation": "Robbins, note 9 to Tetrabiblos III.2 (Loeb 1940)",
                "says": (
                    "the text follows the two chief manuscripts and the anonymous commentator "
                    "in judging 'above the earth' at the syzygy; another reading judges it at "
                    "the birth. The second reading is reported as information "
                    "(prenatal_syzygy_at_birth.luminaries_above_horizon_at_birth)"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Robbins's English translation and note; the Greek not checked",
            },
        ],
        "not_done": (
            "the ascendant corrected by this degree (the animodar) is not computed and the "
            "degree is not an input to any other technique. The Trutina Hermetis is a "
            "different, birth-time rectification method (from the conception) and is not "
            "provided"
        ),
    },
    SYZYGY_SECT_PROFILE_SOURCE_REF: {
        "applies_to": "astronomical_data.lunar_events.prenatal_syzygy_at_birth.sect_profile",
        "definition": (
            "a named pick listed beside the nearest syzygy, not the default: for a day "
            "birth the previous new Moon, for a night birth the previous full Moon, "
            "passing over a nearer syzygy of the other kind. Day and night by the sect "
            "rule; inside its near-horizon band, or without a birth time, nothing is "
            "picked and both are listed"
        ),
        "sources": [
            {
                "citation": (
                    "Ptolemy, Tetrabiblos III.10 (Robbins pp. 271-307; the relevant passage "
                    "pp. 277-279; Hübner III.11)"
                ),
                "says": (
                    "in a day nativity the candidates include the preceding new Moon, in a "
                    "night nativity the preceding full Moon; the text does not say whether a "
                    "nearer syzygy of the other kind is passed over"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Robbins's English translation; the Greek not checked",
            },
            {
                "citation": "William Lilly, Christian Astrology (1647), Book III, ch. CIV, pp. 527-529",
                "says": (
                    "by day the preceding new Moon, by night the preceding full Moon, passing "
                    "over the nearer one"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": (
                    "the English of 1647, read for the product's methods page; the pages "
                    "were not re-read for this entry"
                ),
            },
        ],
    },
    ECLIPSE_SELECTION_SOURCE_REF: {
        "applies_to": (
            "astronomical_data.lunar_events.eclipses.{previous_umbral_lunar,"
            "selection_profile} and eclipses_at_birth"
        ),
        "definition": (
            "the last solar and lunar eclipse whose Swiss maximum is before birth, as "
            "astronomical events. The lunar one includes penumbral eclipses; the last "
            "eclipse in which the Moon enters the umbra (partial or total) is listed "
            "beside it. The eclipse degree is the Sun's longitude at a solar eclipse and "
            "the Moon's at a lunar one, at the maximum. An eclipse whose first contact "
            "is at or before birth and whose maximum is after it is listed as under way"
        ),
        "classical_use": (
            "Ptolemy, Tetrabiblos II.4-II.8 (Robbins) uses eclipses chiefly for regions, "
            "cities and public affairs: II.4 calls the conjunctions of the Sun and Moon at "
            "eclipse 'the first and most potent cause' of such events; II.8 calls the "
            "positions in which a luminary of a nativity holds the degree of an eclipse "
            "(one after the birth) or the opposite degree 'most dangerous and hardest to "
            "avoid'; II.6 times the effect by the hours the obscuration lasts. Treating "
            "the last eclipse before birth as a point "
            "of the nativity is a twentieth-century practice (Jansky 1977, Lineman "
            "1984 and 1992, Brady 1992, Graves 2004; secondary only). No source read "
            "says whether a penumbral "
            "lunar eclipse counts"
        ),
        "penumbral_note": (
            "In a penumbral lunar eclipse the Moon passes only through the Earth's outer, "
            "partial shadow (the penumbra) and never reaches the dark core (the umbra). "
            "Espenak (eclipsewise.com, Visual Appearance of Lunar Eclipses): a penumbral "
            "magnitude above about 0.6 is needed before skilled observers can detect faint "
            "shading, the early and late stages are invisible, and it becomes readily "
            "apparent only within about 0.05 magnitude of a partial eclipse. For including "
            "it: it is an eclipse in the astronomical catalogues (NASA's lunar catalogue "
            "lists it, type N) and in Swiss Ephemeris's default search. For excluding it: "
            "Ptolemy's eclipses are visible obscurations (II.5: those 'in which the "
            "eclipse, since it took place above the earth, was visible'; II.6 times their "
            "effects by how many hours 'the obscuration' lasts). No astrological source "
            "read states a rule for penumbral eclipses; both are listed and none is chosen"
        ),
        "visibility": "whether the eclipse could be seen at the birthplace is not evaluated",
        "sources": [
            {
                "citation": (
                    "Swiss Ephemeris 2.10.03: swe_sol_eclipse_when_glob, swe_lun_eclipse_when "
                    "(ECL_PARTIAL|ECL_TOTAL for the umbral search)"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Swiss Ephemeris programmer's documentation",
            },
            {
                "citation": (
                    "NASA GSFC Five Millennium Canon of Solar Eclipses and Catalog of Lunar "
                    "Eclipses (Espenak & Meeus): the test oracle. Eclipse Predictions by Fred "
                    "Espenak and Jean Meeus (NASA's GSFC)"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the catalogue pages, parsed for the tests",
            },
            {
                "citation": "Ptolemy, Tetrabiblos II.4-II.8 (Robbins, Loeb 1940)",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Robbins's English translation; the Greek not checked",
            },
            {
                "citation": (
                    "the last eclipse before birth as a point of the nativity: Robert C. "
                    "Jansky, Interpreting the Eclipses (Para Research 1977); Rose Lineman, "
                    "Eclipses (AFA 1984) and Your Prenatal Eclipse (AFA 1992); Bernadette "
                    "Brady, The Eagle and the Lark (Weiser 1992); Philip Graves, "
                    "Introduction to Prenatal Eclipses (web article, 2004)"
                ),
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": (
                    "secondary reports only: Graves's web article seen only in summary; "
                    "the books known only from bibliographies and publishers' descriptions"
                ),
            },
        ],
    },
}


# ── pipeline entry points ──────────────────────────────────────────────────


def attach_prenatal_syzygy(
    lunar_events: dict,
    reference_jd_ut: float,
    place: PrenatalPlace,
    trace: Trace,
    *,
    with_birth_relation: bool = True,
) -> None:
    """Add the degree to the prenatal syzygy, from its own search when the
    phase search was refused; with the birth relation at the chart instant.

    Nothing is written unless every part succeeds, so a refusal leaves the
    container as the phase search left it minus its syzygy.
    """

    from .lunar_events import PHASE_DIRECTION_POLICY

    existing = lunar_events.pop("prenatal_syzygy", None)
    syzygy = dict(existing) if existing else nearest_previous_syzygy(reference_jd_ut)
    enrich_syzygy(syzygy, place)
    at_birth = (
        prenatal_syzygy_at_birth(reference_jd_ut, syzygy, place, trace)
        if with_birth_relation else None
    )
    lunar_events.setdefault("contract", "geocentric_apparent_tropical_of_date")
    lunar_events.setdefault("direction_policy", dict(PHASE_DIRECTION_POLICY))
    lunar_events["prenatal_syzygy"] = syzygy
    if at_birth is not None:
        lunar_events["prenatal_syzygy_at_birth"] = at_birth


def attach_eclipse_points(
    lunar_events: dict,
    reference_jd_ut: float,
    place: PrenatalPlace,
    trace: Trace,
    *,
    with_birth_relation: bool = True,
) -> None:
    eclipses = extend_previous_eclipses(lunar_events["eclipses"], reference_jd_ut, place)
    if with_birth_relation:
        lunar_events["eclipses_at_birth"] = eclipses_at_birth(
            eclipses, reference_jd_ut, place, trace
        )
