"""Source-named essential-dignity component lookups.

This module deliberately stops before interpretation or scoring.  It reports which
closed historical rule table applies to a tropical longitude.  Profiles are not
silently treated as interchangeable and no profile is a universal default.

Boundary convention
-------------------
All degree intervals are zero-based and half-open.  A source's cumulative ``6``
therefore means ``[0, 6)``; exactly 6 degrees belongs to the next segment.  A
normalized longitude is always in ``[0, 360)``, so 30 degrees within a sign cannot
occur.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from .formatting import degree_text, normalize_longitude, zodiac_sign_index
from .frame_compatibility import method_frame_state
from .module_state import computed_receipt, not_applicable_receipt
from .method_status import method_receipt, research_only_profiles
from .trace import Trace
from .dignity_tables import (
    BOUNDS_SOURCES,
    BOUNDS_SOURCE_DETAILS,
    BOUNDS_SOURCE_STATEMENTS,
    BOUNDS_TABLES,
    CHALDAEAN_DAY_ORDER,
    CHALDAEAN_LENGTHS,
    CHALDEAN_FACES,
    DECAN_SOURCES,
    DECAN_SOURCE_DETAILS,
    DOMICILE_EXALTATION_PROFILE_ID,
    DOMICILE_EXALTATION_SOURCES,
    DOMICILE_EXALTATION_SOURCE_SCOPE_NOTE,
    DOMICILE_SIGNS,
    DOROTHEAN,
    ELEMENTS,
    EXALTATION_SIGNS,
    LILLY_COMPACT,
    MANILIUS_SIGN_DECANS,
    PTOLEMY_TEXTUAL,
    SIGNS,
    TRIPLICITY_IDS,
    TRIPLICITY_SOURCES,
    TRIPLICITY_SOURCE_DETAILS,
    TRIPLICITY_SOURCE_STATEMENTS,
)


class DignityParticipantScopeError(ValueError):
    """A profile received a participant outside its declared closed scope."""


# Status fields stay in the response; everything else in a profile's source
# details is prose and lives in the method source register.
SOURCE_STATUS_KEYS = ("attribution", "citation_verification")


def _profile_header(
    profile_id: str, technique: str, sources: dict, details: dict
) -> dict:
    """The keys every table profile result opens with."""

    return {
        "profile_id": profile_id,
        "technique": technique,
        "source": sources[profile_id],
        "source_ref": f"dignities/{profile_id}",
        **{
            key: details[profile_id][key]
            for key in SOURCE_STATUS_KEYS
            if key in details[profile_id]
        },
    }


def _by_sect(is_day: bool | None, day, night):
    """The sect's own choice; None when the sect is unknown."""

    return None if is_day is None else day if is_day else night


def _bounds_row_verification(profile_id: str, sign: str) -> str:
    details: dict[str, Any] = BOUNDS_SOURCE_DETAILS[profile_id]
    return next(
        (row["row_verification"] for row in details["row_exceptions"] if row["sign"] == sign),
        details["default_row_verification"],
    )


def _decan_reading(profile_id: str, sign: str, decan_number: int) -> str:
    decan_details: dict[str, Any] = DECAN_SOURCE_DETAILS[profile_id]
    corrected = any(
        correction["sign"] == sign and decan_number in correction["decan_numbers"]
        for correction in decan_details["editorial_corrections"]
    )
    return "editorial_correction" if corrected else "transmitted_text"


def _location(longitude: float) -> tuple[int, str, float]:
    # IEEE-754 can round a subnormal negative remainder up to exactly 360.
    normalized = normalize_longitude(longitude)
    sign_index = zodiac_sign_index(normalized)
    return sign_index, SIGNS[sign_index], normalized - sign_index * 30.0


def _find_segment(
    segments: Iterable[tuple[str, int]], degree: float
) -> dict:
    start = 0.0
    for ruler, length in segments:
        end = start + length
        if start <= degree < end:
            return {
                "ruler": ruler,
                "segment_start_degrees": start,
                "segment_end_degrees": end,
            }
        start = end
    raise AssertionError(f"degree outside normalized sign: {degree}")


def _base_object(body: dict) -> dict:
    sign_index, sign, degree = _location(body["longitude"])
    return {
        "key": body["key"],
        "name": body["name"],
        "longitude": body["longitude"],
        "sign_index": sign_index,
        "sign": sign,
        "degree_in_sign": degree,
        # The table's text, rounded without reaching the next whole degree, so
        # it never crosses a bound or decan end (all are whole degrees).
        "degree_in_sign_text": degree_text(degree, 4),
    }


def _chaldaean_segments(sign_index: int, *, is_day: bool) -> tuple:
    order = list(CHALDAEAN_DAY_ORDER[sign_index % 4])
    if not is_day:
        saturn = order.index("saturn")
        mercury = order.index("mercury")
        order[saturn], order[mercury] = order[mercury], order[saturn]
    return tuple(zip(order, CHALDAEAN_LENGTHS, strict=True))


CHALDAEAN_SEGMENTS_BY_SECT = {
    True: tuple(_chaldaean_segments(index, is_day=True) for index in range(12)),
    False: tuple(_chaldaean_segments(index, is_day=False) for index in range(12)),
}


def _bounds_profile(
    profile_id: str, bodies: list[dict], sect_is_day: bool | None
) -> dict:
    objects = []
    for body in bodies:
        item = _base_object(body)
        sign_index = item["sign_index"]
        degree = item["degree_in_sign"]
        if profile_id == "chaldaean_bounds_ptolemy_i_21_v1":
            day = _find_segment(CHALDAEAN_SEGMENTS_BY_SECT[True][sign_index], degree)
            night = _find_segment(CHALDAEAN_SEGMENTS_BY_SECT[False][sign_index], degree)
            # The selected segment is the top-level ruler/segment (null when the
            # sect is unknown, which essential_dignities.sect states once).
            item.update(_by_sect(sect_is_day, day, night) or dict.fromkeys(day))
            item.update({"day_candidate": day, "night_candidate": night})
        else:
            table = BOUNDS_TABLES[profile_id]
            item.update(_find_segment(table[sign_index], degree))
        item["row_verification"] = _bounds_row_verification(
            profile_id, item["sign"]
        )
        objects.append(item)
    return {
        **_profile_header(profile_id, "bounds", BOUNDS_SOURCES, BOUNDS_SOURCE_DETAILS),
        "interval_semantics": "half_open_[start,end)",
        "sect_dependency": (
            "saturn_mercury_order" if profile_id.startswith("chaldaean_") else None
        ),
        "objects": objects,
    }


def _decan_profile(profile_id: str, bodies: list[dict]) -> dict:
    ruler_type = (
        "planet"
        if profile_id == "chaldean_planetary_faces_firmicus_ii_4_v1"
        else "sign"
    )
    objects = []
    for body in bodies:
        item = _base_object(body)
        decan_index = min(int(item["degree_in_sign"] // 10.0), 2)
        if ruler_type == "planet":
            ruler = CHALDEAN_FACES[item["sign_index"]][decan_index]
        else:
            ruler = MANILIUS_SIGN_DECANS[item["sign_index"]][decan_index]
        item.update(
            {
                "decan_number": decan_index + 1,
                "segment_start_degrees": float(decan_index * 10),
                "segment_end_degrees": float((decan_index + 1) * 10),
                "ruler_type": ruler_type,
                "ruler": ruler,
                "ruler_reading": _decan_reading(
                    profile_id, item["sign"], decan_index + 1
                ),
            }
        )
        objects.append(item)
    return {
        **_profile_header(profile_id, "face_decan", DECAN_SOURCES, DECAN_SOURCE_DETAILS),
        "ruler_type": ruler_type,
        "interval_semantics": "half_open_10_degree_bins",
        "objects": objects,
    }


_DOMICILE_EXALTATION_SOURCE = (
    "Ptolemy, Tetrabiblos I.17, I.19 (Robbins 1940; = Hübner I.18, I.20); "
    "also attested in Dorotheus, Valens and Firmicus"
)


def _domicile_exaltation_profile(bodies: list[dict]) -> dict:
    """Match the traditional seven against whole-sign houses/exaltations.

    This profile deliberately does not choose among transmitted exact exaltation
    degrees.  Ptolemy, Tetrabiblos I.17 and I.19 (Robbins; Hübner I.18 and I.20)
    supplies a whole-sign scheme;
    Dorotheus I.1-2, Valens III.4, and Firmicus Mathesis II.2-3 also preserve
    the familiar sign assignments while supplying degree traditions whose
    variants require a separate method decision.
    """

    unsupported = sorted(
        {
            str(body.get("key", "<missing>"))
            for body in bodies
            if body.get("key") not in DOMICILE_SIGNS
        }
    )
    if unsupported:
        raise DignityParticipantScopeError(
            "unsupported domicile/exaltation participant: "
            + ", ".join(unsupported)
        )

    objects = []
    for body in bodies:
        item = _base_object(body)
        key = item["key"]
        domicile_signs = DOMICILE_SIGNS[key]
        exaltation_sign = EXALTATION_SIGNS[key]
        item.update(
            {
                "domicile_signs": list(domicile_signs),
                "exaltation_sign": exaltation_sign,
                "domicile_matched": item["sign"] in domicile_signs,
                "exaltation_matched": item["sign"] == exaltation_sign,
            }
        )
        objects.append(item)
    return {
        "profile_id": DOMICILE_EXALTATION_PROFILE_ID,
        "technique": "domicile_exaltation",
        "source": _DOMICILE_EXALTATION_SOURCE,
        "source_ref": f"dignities/{DOMICILE_EXALTATION_PROFILE_ID}",
        "match_basis": "whole_tropical_sign",
        # The degree policy and the list of what is not evaluated are constant
        # text in the register entry source_ref names.
        "exact_exaltation_degrees_evaluated": False,
        "debility_evaluated": False,
        "participant_scope": "classical_seven_planets_only",
        "objects": objects,
        "interpretation": None,
        "score": None,
    }


def _triplicity_profile(
    profile_id: str, bodies: list[dict], sect_is_day: bool | None
) -> dict:
    objects = []
    for body in bodies:
        item = _base_object(body)
        element = ELEMENTS[item["sign_index"] % 4]
        if profile_id == TRIPLICITY_IDS[0]:
            day, night, third = DOROTHEAN[element]
            day_rulers = [day, night, third]
            night_rulers = [night, day, third]
            structure = "ordered_day_night_third_participating"
        elif profile_id == TRIPLICITY_IDS[1]:
            ptolemy_rule = PTOLEMY_TEXTUAL[element]
            day_rulers = list(ptolemy_rule["day"])
            night_rulers = list(ptolemy_rule["night"])
            structure = ptolemy_rule["structure"]
            item["principal_ruler"] = ptolemy_rule["principal"]
            item["assigned_rulers"] = list(ptolemy_rule["assigned"])
            item["secondary_ruler"] = _by_sect(
                sect_is_day, ptolemy_rule["secondary_day"], ptolemy_rule["secondary_night"]
            )
        else:
            lilly_rule = LILLY_COMPACT[element]
            day_rulers = list(lilly_rule["day"])
            night_rulers = list(lilly_rule["night"])
            structure = "compact_day_night_table"
        selected = _by_sect(sect_is_day, day_rulers, night_rulers)
        selected = list(selected) if selected is not None else None
        item.update(
            {
                "element": element,
                "day_rulers": day_rulers,
                "night_rulers": night_rulers,
                "selected_rulers": selected,
                "structure": structure,
            }
        )
        objects.append(item)
    return {
        **_profile_header(
            profile_id, "triplicity", TRIPLICITY_SOURCES, TRIPLICITY_SOURCE_DETAILS
        ),
        "objects": objects,
    }


# The refusal decision and its code come from the central frame table; the
# trace keeps the reason each code rests on.  A table code missing here is a
# KeyError, so the two cannot drift apart silently.
_DIGNITY_FRAME_REFUSAL_NOTES = {
    "non_earth_center_dignity_basis_not_authorized": (
        "本產品的方法未授權把古典尊貴表套入 heliocentric／barycentric longitude，故 fail closed。"
    ),
    "sidereal_dignity_basis_not_authorized": (
        "本產品的方法未授權把古典 tropical tables 靜默套入 sidereal longitude，故 fail closed。"
    ),
    "j2000_dignity_basis_not_authorized": (
        "本產品的正式 dignity 基準使用 of-date；"
        "J2000 只保留天文／研究座標，不查古典表。"
    ),
    "nutation_off_dignity_basis_not_authorized": (
        "本產品的正式 dignity 基準使用 nutation-on；"
        "mean-of-date 比較留待日後另設 research-only profile。"
    ),
}


# The basis every dignity table is defined in; a chart in any other frame is
# refused (the central frame table), so the computed and the refused receipt
# state the same basis.
DIGNITY_ZODIAC_BASIS = "tropical_ecliptic_of_date_nutation_on_earth_center"


def compute_essential_dignities(
    *,
    bodies: list[dict],
    include_domicile_exaltation: bool,
    bounds_profile: str | None,
    decan_profile: str | None,
    triplicity_profile: str | None,
    include_triplicity_comparison: bool,
    computation_mode,
    sect_basis: str,
    trace: Trace,
    sect_sun_altitude: float | None,
    sect_classification: dict,
) -> dict | None:
    """Compute selected source-named components for the classical seven only."""

    requested = bool(
        include_domicile_exaltation
        or bounds_profile
        or decan_profile
        or triplicity_profile
        or include_triplicity_comparison
    )
    if not requested:
        return None
    selected = {
        "domicile_exaltation": (
            DOMICILE_EXALTATION_PROFILE_ID
            if include_domicile_exaltation
            else None
        ),
        "bounds": bounds_profile,
        "face_decan": decan_profile,
        "triplicity": triplicity_profile,
    }
    center = computation_mode.center
    ecliptic_frame = computation_mode.ecliptic_frame
    nutation = computation_mode.nutation
    sect_is_day = sect_classification["is_day"]
    frame_state = method_frame_state("essential_dignities", computation_mode)
    if not frame_state["applicable"]:
        reason_code = frame_state["reason_code"]
        trace.add(
            "具名古典尊貴元件",
            inputs={
                "center": center,
                "zodiac": computation_mode.zodiac,
                "ecliptic_frame": ecliptic_frame,
                "nutation": nutation,
                "selected_profiles": selected,
            },
            result={"execution_status": "not_applicable", "reason_code": reason_code},
            note=_DIGNITY_FRAME_REFUSAL_NOTES[reason_code],
        )
        return {
            "method": "named_essential_dignity_components_v1",
            **method_receipt("essential_dignities"),
            **not_applicable_receipt(frame_state),
            "zodiac_basis": DIGNITY_ZODIAC_BASIS,
            "coordinate_center": center,
            "ecliptic_frame": ecliptic_frame,
            "nutation": nutation,
            "selected_profiles": selected,
            "research_comparison_profiles": [],
            "research_only_profiles": [],
            "profile_results": {},
            "interpretation": None,
            "score": None,
        }
    usable_bodies = [body for body in bodies if body.get("longitude") is not None]
    results = {}
    if include_domicile_exaltation:
        results[DOMICILE_EXALTATION_PROFILE_ID] = (
            _domicile_exaltation_profile(usable_bodies)
        )
    if bounds_profile:
        results[bounds_profile] = _bounds_profile(
            bounds_profile, usable_bodies, sect_is_day
        )
    if decan_profile:
        results[decan_profile] = _decan_profile(decan_profile, usable_bodies)
    triplicity_ids = []
    if triplicity_profile:
        triplicity_ids.append(triplicity_profile)
    if include_triplicity_comparison:
        triplicity_ids.extend(TRIPLICITY_IDS)
    triplicity_ids = list(dict.fromkeys(triplicity_ids))
    sect_dependent_components = (
        [bounds_profile] if bounds_profile == "chaldaean_bounds_ptolemy_i_21_v1" else []
    ) + triplicity_ids
    for profile_id in triplicity_ids:
        results[profile_id] = _triplicity_profile(
            profile_id, usable_bodies, sect_is_day
        )

    trace.add(
        "具名古典尊貴元件",
        formula=(
            "tropical longitude -> whole-sign domicile/exaltation match and/or "
            "source-named half-open table; no scoring or interpretation"
        ),
        inputs={
            "selected_profiles": selected,
            "triplicity_research_comparison": include_triplicity_comparison,
            "sect_is_day": sect_is_day,
            "sect_basis": sect_basis,
        },
        result={"profile_ids": list(results)},
        note=(
            "Traditional-seven whole-sign domicile/exaltation is kept separate "
            "from exact exaltation-degree traditions. Dorothean, Ptolemy textual, "
            "Lilly compact, Egyptian, Chaldaean, Robbins and Lilly tables remain "
            "separate profiles."
        ),
    )
    return {
        "method": "named_essential_dignity_components_v1",
        **method_receipt("essential_dignities"),
        **computed_receipt(
            "selected_named_primary_text_profiles", available=bool(results)
        ),
        "zodiac_basis": DIGNITY_ZODIAC_BASIS,
        "coordinate_center": center,
        "ecliptic_frame": ecliptic_frame,
        "nutation": nutation,
        "participant_scope": "classical_seven_planets_only",
        # 二元日夜盤結果旁必須附上近地平提示。日夜盤、
        # 提示帶與具名邊界分歧都來自 lots.classify_sect（單一產生器），這裡不另算；
        # sect_dependent_components 列出本次真正依日夜盤選主的元件。
        "sect": _sect_receipt(
            sect_is_day,
            sect_basis,
            sect_sun_altitude,
            sect_classification,
            sect_dependent_components,
        ),
        "selected_profiles": selected,
        "research_comparison_profiles": (
            list(TRIPLICITY_IDS) if include_triplicity_comparison else []
        ),
        # 列為 research-only 的 profile，被選為主要 profile 時也標出。
        "research_only_profiles": research_only_profiles(results),
        "profile_results": results,
        "interpretation": None,
        "score": None,
    }


def _sect_receipt(
    is_day: bool | None,
    basis: str,
    sun_altitude: float | None,
    classification: dict,
    dependent_components: list,
) -> dict:
    # classify_sect(None) already carries None for the band and disagreement.
    known = is_day is not None
    return {
        "is_day": is_day,
        "basis": basis,
        "selected_ruler_available": known,
        "sun_altitude_used": sun_altitude if known else None,
        "in_near_horizon_band": classification["in_near_horizon_band"],
        "near_horizon_band_half_width_degrees": classification[
            "near_horizon_band_half_width_degrees"
        ],
        "named_boundary_disagreement": classification["named_boundary_disagreement"],
        "sect_dependent_components": dependent_components,
    }


def _register_entry(profile_id: str, statement: str, details: dict | None) -> dict:
    entry: dict[str, Any] = {
        "applies_to": f"derived_methods.essential_dignities.profile_results.{profile_id}",
        "statement": statement,
    }
    if details is not None:
        entry["details"] = copy.deepcopy(details)
    return entry


METHOD_SOURCE_ENTRIES: dict[str, dict[str, Any]] = {
    **{
        f"dignities/{profile_id}": _register_entry(
            profile_id, statements[profile_id], details[profile_id]
        )
        for statements, details in (
            (BOUNDS_SOURCE_STATEMENTS, BOUNDS_SOURCE_DETAILS),
            (DECAN_SOURCES, DECAN_SOURCE_DETAILS),
            (TRIPLICITY_SOURCE_STATEMENTS, TRIPLICITY_SOURCE_DETAILS),
        )
        for profile_id in details
    },
    f"dignities/{DOMICILE_EXALTATION_PROFILE_ID}": {
        **_register_entry(DOMICILE_EXALTATION_PROFILE_ID, _DOMICILE_EXALTATION_SOURCE, None),
        "sources": copy.deepcopy(DOMICILE_EXALTATION_SOURCES),
        "source_scope_note": DOMICILE_EXALTATION_SOURCE_SCOPE_NOTE,
        "degree_policy": "specific_exaltation_degrees_not_selected_or_evaluated",
        "not_evaluated": ["detriment", "fall", "peregrine", "reception"],
    },
}
