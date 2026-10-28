"""Planetary day and planetary hours: Chaldean order, unequal hours from sunrise.

The definition is METHOD_SOURCE_ENTRIES["planetary_hours"].  Sunrise and
sunset are the horizon module's events (refracted upper limb, topocentric,
request atmosphere, no dip): the USNO definition the product already checks
against.  It does not follow the display computation mode.

A planetary day exists only within one diurnal cycle (sunrises at most
``DIURNAL_REGIME_MAX_DAYS`` apart, one sunset between).  Polar day, polar night
and the transition days are not applicable; no hour is stretched across a
multi-day day.
"""

from __future__ import annotations

import datetime as dtmod
import math
from typing import Final

from .dignity_tables import CHALDEAN_ORDER
from ..domain_catalog import CLASSICAL_BODIES
from .horizon_events import (
    DIURNAL_REGIME_MAX_DAYS,
    FRAME_DECLARATION,
    RISE_TRANS_REPEATABILITY_DAYS,
    SEARCH_COVERAGE_MARGIN_DAYS,
    require_search_coverage,
    sun_horizon_crossings,
)
from .module_state import computed_receipt, module_state
from .method_status import method_head
from .source_reading import ORIGINAL_LANGUAGE_READ, TRANSLATION_READ, cited
from .time_utils import civil_date as _local_date
from .time_utils import civil_instant, solved_instant
from .trace import Trace

def _instant(jd_ut: float, tz_input) -> dict:
    """An event or hour boundary, printed no finer than sunrise/sunset are."""

    return solved_instant(
        jd_ut, RISE_TRANS_REPEATABILITY_DAYS, lambda jd: civil_instant(jd, tz_input)
    )[1]


METHOD: Final = "chaldean_unequal_hours_from_sunrise_v1"
SOURCE: Final = "Swiss Ephemeris swe_rise_trans (Sun), product hour division"
SOURCE_REF: Final = "planetary_hours"

# Descending order of the planets' periods; hour n+1 is ruled by the planet
# after hour n's.
# datetime.date.weekday(): Monday is 0.
WEEKDAYS: Final = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
WEEKDAY_RULERS: Final = ("moon", "mars", "mercury", "jupiter", "venus", "saturn", "sun")
PERIODS: Final = ("day", "night")
HOURS_PER_PERIOD: Final = 12

NO_DIURNAL_CYCLE: Final = "no_sunrise_sunset_cycle_around_instant"
# Closed reasons this module writes itself; the frame table's and the
# event-search refusals are written by the chart pipeline.
REASON_CODES: Final = (NO_DIURNAL_CYCLE,)
INTERVALS: Final = ("stated_civil_hour", "civil_day")

# Two days each side: a margin beyond the 1.5-day diurnal-cycle bound.
SEARCH_WINDOW_DAYS: Final = 2.0

_NAMES: Final = {body["key"]: body["zh"] for body in CLASSICAL_BODIES}
_SUN: Final = next(body for body in CLASSICAL_BODIES if body["key"] == "sun")

SUNRISE_DEFINITION: Final = {
    "event": "rise_and_set_of_the_sun",
    "disc_position": "upper_limb",
    "refraction": "enabled",
    "refraction_model": "swiss_ephemeris_standard_with_request_atmosphere",
    "coordinate_origin": "topocentric_observer",
    "position_mode": FRAME_DECLARATION["position_mode"],
    "horizon_model": FRAME_DECLARATION["horizon_model"],
    "follows_computation_mode": False,
    "same_premise_as": "astronomical_data.horizon_events",
}

METHOD_SOURCE_ENTRIES: Final = {
    SOURCE_REF: {
        "applies_to": "derived_methods.planetary_hours",
        "definition": (
            "Planetary day from sunrise to the next sunrise; twelve equal day hours "
            "sunrise→sunset and twelve equal night hours sunset→next sunrise "
            "(unequal or seasonal hours); hours ruled in the Chaldean order "
            "Saturn, Jupiter, Mars, Sun, Venus, Mercury, Moon; the first hour's "
            "ruler is the weekday ruler of the sunrise's civil date in the request "
            "time zone"
        ),
        "source_status": "standard_tradition",
        "source_note": (
            "Cassius Dio, Roman History XXXVII.19: the weekday names follow from "
            "giving the planets, from Saturn on, to the successive hours of day and "
            "night. Dio defines neither unequal hours nor a day starting at sunrise; "
            "for those two the primary text cited is Lilly, Christian Astrology "
            "(1647) ch. XCVII, pp. 482-484"
        ),
        "primary_text_checked": (
            "dio_xxxvii_19_in_english_translation_only; lilly_1647_ch_xcvii_in_the_first_edition"
        ),
        "sources": [
            cited("Cassius Dio, Roman History XXXVII.19",
                  ("the weekday names follow from giving the planets, from Saturn on, to "
                   "the successive hours of day and night"),
                  TRANSLATION_READ,
                  ("Cary's English translation (Loeb, Dio's Roman History vol. III, 1914), "
                   "p.131, in the LacusCurtius transcription; the Greek not checked")),
            cited("William Lilly, Christian Astrology (London, 1647), ch. XCVII, pp. 482-484",
                  ("the first hour of every day goes to the planet of the day, beginning "
                   "ever at sunrise and numbering on to the next sunrise; sunrise to sunset "
                   "and sunset to the next sunrise are each divided into twelve equal parts, "
                   "so the astrological hours are unequal, just sixty minutes only on the "
                   "day the Sun enters Aries or Libra; worked example: Monday 9:30 a.m. "
                   "falls in the hour of Mars"),
                  ORIGINAL_LANGUAGE_READ,
                  ("the first edition (archive.org/details/b30338724), read in the "
                   "scan's OCR text of pp. 482-484")),
        ],
        "sunrise_definition": (
            "the horizon module's event: refracted upper limb crossing the apparent "
            "horizon, topocentric, request atmosphere, no dip (USNO standard "
            "definition; Swiss swe_rise_trans default)"
        ),
        "not_applicable_rule": (
            "applicable only when the sunrise before and the sunrise after the "
            "instant are at most 1.5 days apart with exactly one sunset between "
            "them (the horizon module's diurnal regime); otherwise "
            f"{NO_DIURNAL_CYCLE}"
        ),
        "day_ruler_rule_boundary": (
            "the weekday is read from the sunrise's civil date; where two "
            "consecutive sunrises fall on one civil date or skip one (near polar "
            "transitions) the Chaldean sequence across the two days does not "
            "continue, and the product does not adjust it"
        ),
        "reason_vocabulary": list(REASON_CODES),
        "interval_vocabulary": list(INTERVALS),
    },
}


def _ruler(key: str) -> dict:
    return {"ruler": key, "ruler_name": _NAMES[key]}


def _hour_at(instant: float, crossings: list[tuple[float, str]]) -> dict | None:
    """The planetary hour holding ``instant``, as JDs, or None without a diurnal cycle."""

    rises = [jd for jd, kind in crossings if kind == "rise"]
    before = [jd for jd in rises if jd <= instant]
    after = [jd for jd in rises if jd > instant]
    if not before or not after:
        return None
    sunrise, next_sunrise = before[-1], after[0]
    if next_sunrise - sunrise > DIURNAL_REGIME_MAX_DAYS:
        return None
    sets = [jd for jd, kind in crossings if kind == "set" and sunrise < jd < next_sunrise]
    if len(sets) != 1:
        return None
    sunset = sets[0]
    period, origin, close = (
        ("day", sunrise, sunset) if instant < sunset else ("night", sunset, next_sunrise)
    )
    part = (close - origin) / HOURS_PER_PERIOD

    def bound(k: int) -> float:
        # The last boundary is the event itself, not origin + 12 parts.
        return close if k == HOURS_PER_PERIOD else origin + k * part

    k = min(HOURS_PER_PERIOD - 1, max(0, int((instant - origin) / part)))
    while k > 0 and instant < bound(k):
        k -= 1
    while k < HOURS_PER_PERIOD - 1 and instant >= bound(k + 1):
        k += 1
    return {
        "sunrise": sunrise,
        "sunset": sunset,
        "next_sunrise": next_sunrise,
        "period": period,
        "index_in_period": k + 1,
        "start": bound(k),
        "end": bound(k + 1),
    }


def _day_ruler(sunrise: float, tz_input) -> tuple[str, dtmod.date]:
    date = _local_date(sunrise, tz_input)
    return WEEKDAY_RULERS[date.weekday()], date


def _hour_ruler(day_ruler: str, index: int) -> str:
    return CHALDEAN_ORDER[(CHALDEAN_ORDER.index(day_ruler) + index - 1) % len(CHALDEAN_ORDER)]


def _hour_index(hour: dict) -> int:
    return hour["index_in_period"] + (HOURS_PER_PERIOD if hour["period"] == "night" else 0)


def _candidate(hour: dict, tz_input) -> dict:
    day_ruler, _date = _day_ruler(hour["sunrise"], tz_input)
    index = _hour_index(hour)
    ruler = _hour_ruler(day_ruler, index)
    return {
        "planetary_day_ruler": day_ruler,
        "planetary_day_ruler_name": _NAMES[day_ruler],
        "index": index,
        "period": hour["period"],
        "index_in_period": hour["index_in_period"],
        **_ruler(ruler),
        "start": _instant(hour["start"], tz_input),
        "end": _instant(hour["end"], tz_input),
    }


def _chart_instant(hour: dict, tz_input) -> dict:
    day_ruler, date = _day_ruler(hour["sunrise"], tz_input)
    index = _hour_index(hour)
    minutes = 1440.0 / HOURS_PER_PERIOD
    return {
        "planetary_day": {
            **_ruler(day_ruler),
            "weekday": WEEKDAYS[date.weekday()],
            "sunrise_local_date": date.isoformat(),
            "sunrise": _instant(hour["sunrise"], tz_input),
            "sunset": _instant(hour["sunset"], tz_input),
            "next_sunrise": _instant(hour["next_sunrise"], tz_input),
            "day_hour_minutes": (hour["sunset"] - hour["sunrise"]) * minutes,
            "night_hour_minutes": (hour["next_sunrise"] - hour["sunset"]) * minutes,
        },
        "planetary_hour": {
            "index": index,
            "period": hour["period"],
            "index_in_period": hour["index_in_period"],
            **_ruler(_hour_ruler(day_ruler, index)),
            "start": _instant(hour["start"], tz_input),
            "end": _instant(hour["end"], tz_input),
            "length_minutes": (hour["end"] - hour["start"]) * 1440.0,
        },
    }


def _receipt_head() -> dict:
    return method_head(
        METHOD, "planetary_hours", source_ref=SOURCE_REF,
        sunrise_definition=dict(SUNRISE_DEFINITION),
    )


def planetary_hours_not_applicable(
    reason_code: str | None,
    *,
    executed: bool,
    applicable: bool = False,
    trace: Trace | None = None,
) -> dict:
    """The module's receipt when no hour can be named, for the stated reason.

    The frame table's refusal (not executed), a search the ephemeris refused
    (executed; applicable when the server lacks a file) and the polar case
    (executed, not applicable) all end here.
    """

    if trace is not None:
        trace.add(
            "行星日與行星時",
            result={"reason_code": reason_code},
            note="無法定出行星日：此項標為不適用或不可用，不以其他時刻代替。",
        )
    return {
        **_receipt_head(),
        **module_state(
            requested=True, executed=executed, applicable=applicable,
            available=False, reason_code=reason_code,
        ),
        "status": "not_applicable",
        "time_basis": None,
        "chart_instant": None,
        "birth_time_interval": None,
    }


def compute_planetary_hours(
    *,
    reference_jd_ut: float,
    interval_spans: list[tuple[float, float]] | None,
    interval: str | None,
    time_basis: str,
    location,
    atmosphere,
    tz_input,
    trace: Trace,
) -> dict:
    """Planetary day and hour at the chart instant and over the birth-time interval.

    ``interval_spans`` are half-open [start, end) JD(UT) stretches the birth
    time may lie in (None for an exact birth time).  Raises the coverage
    refusal of ``require_search_coverage`` before any Swiss call.
    """

    if (interval is None) != (interval_spans is None) or (
        interval is not None and interval not in INTERVALS
    ):
        raise ValueError("interval and its spans go together")
    spans = interval_spans or [(reference_jd_ut, math.nextafter(reference_jd_ut, math.inf))]
    low = min(reference_jd_ut, spans[0][0]) - SEARCH_WINDOW_DAYS
    high = max(reference_jd_ut, spans[-1][1]) + SEARCH_WINDOW_DAYS
    require_search_coverage(
        [_SUN], (low + high) / 2.0,
        reach_days=(high - low) / 2.0 + SEARCH_COVERAGE_MARGIN_DAYS,
    )
    crossings = sun_horizon_crossings(low, high, location, atmosphere)

    anchor = _hour_at(reference_jd_ut, crossings)
    hours: list[dict] = []
    for start, end in spans:
        cursor = start
        while cursor < end:
            hour = _hour_at(cursor, crossings)
            if hour is None:
                anchor = None
                break
            if not hours or hours[-1]["start"] != hour["start"]:
                hours.append(hour)
            cursor = hour["end"]
        if anchor is None:
            break
    trace.add(
        "行星日與行星時",
        formula=(
            "行星日自日出起至下一次日出；日出→日落十二等分為晝時、日落→下一次日出十二等分為夜時；"
            "第一時之主為日出所在民用日（出生地日曆上的那一天，從午夜到午夜）的七曜之主，其後依迦勒底序（土、木、火、日、金、水、月）"
        ),
        inputs={
            "reference_JD_UT": reference_jd_ut,
            "search_window_JD_UT": [low, high],
            "interval": interval,
            "rise_set_disc": "upper_limb",
            "refraction": "enabled",
        },
        result={
            "sun_crossings": len(crossings),
            "candidates": len(hours) if anchor is not None else 0,
        },
        note="日出日落與天體升降模組同一定義（上緣、標準折射、站心、無地平俯角）。",
    )
    if anchor is None:
        return planetary_hours_not_applicable(NO_DIURNAL_CYCLE, executed=True)
    candidates = [_candidate(hour, tz_input) for hour in hours]
    return {
        **_receipt_head(),
        **computed_receipt(SOURCE),
        "status": "computed",
        "time_basis": time_basis,
        "chart_instant": _chart_instant(anchor, tz_input),
        "birth_time_interval": {
            "interval": interval,
            "candidates": candidates,
            "crosses_hour_boundary": len(candidates) > 1,
            "crosses_planetary_day_boundary": (
                len({hour["sunrise"] for hour in hours}) > 1
            ),
        },
    }
