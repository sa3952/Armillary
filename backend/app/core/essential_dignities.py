"""Source-named essential-dignity component lookups.

This module deliberately stops before interpretation or scoring.  It reports which
closed historical rule table applies to a tropical longitude.  Profiles are not
silently treated as interchangeable and no profile is a universal default.

Boundary convention: degree intervals are zero-based and half-open.  A source's
cumulative ``6`` means ``[0, 6)``; exactly 6 degrees belongs to the next segment.
A normalized longitude is in ``[0, 360)``, so 30 degrees within a sign cannot occur.
"""

from __future__ import annotations

from dataclasses import dataclass

import copy
from collections.abc import Iterable
from typing import Any

from .formatting import dms_text, normalize_longitude, zodiac_sign_index
from .frame_compatibility import method_frame_state
from .module_state import computed_receipt, frame_table_refusal
from .method_status import method_head, research_only_profiles
from .source_reading import (
    DOROTHEUS_BOOK_I_ONLINE, ORIGINAL_LANGUAGE_READ, SOURCE_READING_LEVELS, cited, reference_only,
)
from .trace import Trace
from .dignity_tables import (
    ROBBINS_EGYPTIAN_TERMS_PAGES,
    BOUNDS_SOURCES,
    BOUNDS_SOURCE_DETAILS,
    BOUNDS_SOURCE_STATEMENTS,
    BOUNDS_TABLES,
    CHALDAEAN_DAY_ORDER,
    CHALDAEAN_LENGTHS,
    CHALDEAN_FACES,
    DEBILITY_COMPONENT_SOURCES,
    DEBILITY_PARTICIPANT_NOTE,
    DECAN_SOURCES,
    DECAN_SOURCE_DETAILS,
    DOMICILE_EXALTATION_PROFILE_ID,
    DOMICILE_EXALTATION_SOURCES,
    DOMICILE_EXALTATION_SOURCE_SCOPE_NOTE,
    DETRIMENT_SIGNS,
    DOMICILE_SIGNS,
    DOROTHEAN,
    ELEMENTS,
    EXALTATION_SIGNS,
    FALL_SIGNS,
    LILLY_COMPACT,
    LILLY_RECEIVED_BOUNDS,
    MANILIUS_SIGN_DECANS,
    PEREGRINE_BASIS,
    PEREGRINE_BASIS_NOTE,
    PEREGRINE_DIGNITIES,
    PEREGRINE_PROFILE_ID,
    PEREGRINE_RULE,
    PEREGRINE_SOURCE,
    PEREGRINE_SOURCE_REF,
    PEREGRINE_SOURCES,
    PEREGRINE_STATUSES,
    PEREGRINE_TABLE_DEPENDENCE,
    PEREGRINE_TERM_NOTE,
    PTOLEMY_TEXTUAL,
    SIGNS,
    TRIPLICITY_IDS,
    TRIPLICITY_SOURCES,
    TRIPLICITY_SOURCE_DETAILS,
    TRIPLICITY_SOURCE_STATEMENTS,
)


# 「全部並列」：一個技法選這個值，就把本版的每一套具名表都算一次，依目錄順序（下面的
# PROFILE_IDS，也是請求 schema 列出的順序）。每一套的結果與單獨選它時完全相同；不設主要那套。
ALL_PROFILES = "all"
PROFILE_IDS = {
    "bounds": tuple(BOUNDS_SOURCES),
    "face_decan": tuple(DECAN_SOURCES),
    "triplicity": TRIPLICITY_IDS,
}


def expand_profiles(technique: str, requested: str | None) -> list[str]:
    """The concrete profile ids one requested value stands for, in catalogue order."""

    if requested is None:
        return []
    if requested == ALL_PROFILES:
        return list(PROFILE_IDS[technique])
    return [requested]


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
        # Rounded without reaching the next whole degree, so the text never
        # crosses a bound or decan end (all whole degrees).
        "degree_in_sign_text": dms_text(degree),
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
    "Domicile and exaltation: Ptolemy, Tetrabiblos I.17, I.19 (Robbins 1940; = "
    "Hübner I.18, I.20); also attested in Dorotheus, Valens and Firmicus. Fall: the "
    "sign opposite the exaltation, Ptolemy I.19 'depression'. Detriment: the sign "
    "opposite a domicile, al-Bīrūnī, Tafhīm §442 (Wright 1934) and Lilly, Christian "
    "Astrology (1647) pp.104-105; Ptolemy names no detriment."
)


def _domicile_exaltation_profile(bodies: list[dict]) -> dict:
    """Match the traditional seven against whole-sign houses/exaltations and
    the signs opposite them (detriment, fall).

    Deliberately chooses no transmitted exact exaltation degree: the degree
    variants in Dorotheus, Valens and Firmicus need a separate method decision.
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
        detriment_signs = DETRIMENT_SIGNS[key]
        fall_sign = FALL_SIGNS[key]
        item.update(
            {
                "domicile_signs": list(domicile_signs),
                "exaltation_sign": exaltation_sign,
                "domicile_matched": item["sign"] in domicile_signs,
                "exaltation_matched": item["sign"] == exaltation_sign,
                "detriment_signs": list(detriment_signs),
                "detriment_matched": item["sign"] in detriment_signs,
                "fall_sign": fall_sign,
                "fall_matched": item["sign"] == fall_sign,
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


def _peregrine_by_sect(item: dict) -> tuple[list[str], dict[str, bool]]:
    """The dignities a planet holds whatever the sect, and the sect ruler's
    triplicity by day and by night, all on Lilly's p.104 table."""

    key, sign, sign_index = item["key"], item["sign"], item["sign_index"]
    degree = item["degree_in_sign"]
    held = []
    if sign in DOMICILE_SIGNS[key]:
        held.append("domicile")
    if sign == EXALTATION_SIGNS[key]:
        held.append("exaltation")
    if _find_segment(LILLY_RECEIVED_BOUNDS[sign_index], degree)["ruler"] == key:
        held.append("term")
    if CHALDEAN_FACES[sign_index][min(int(degree // 10.0), 2)] == key:
        held.append("face")
    rule = LILLY_COMPACT[ELEMENTS[sign_index % 4]]
    return held, {"day": key in rule["day"], "night": key in rule["night"]}


def _peregrine_profile(bodies: list[dict], sect_classification: dict) -> dict:
    """Lilly's peregrine (p.112) for the classical seven, on his own p.104 set.

    The triplicity counts only for the sect ruler (p.102), so an unknown sect,
    or a Sun inside the near-horizon band, leaves undetermined exactly the
    planets the triplicity alone would decide.  No score.
    """

    unsupported = sorted(
        {str(body.get("key", "<missing>")) for body in bodies if body.get("key") not in DOMICILE_SIGNS}
    )
    if unsupported:
        raise DignityParticipantScopeError(
            "unsupported peregrine participant: " + ", ".join(unsupported)
        )
    is_day = sect_classification["is_day"]
    in_band = sect_classification["in_near_horizon_band"] is True
    objects = []
    for body in bodies:
        item = _base_object(body)
        held, triplicity = _peregrine_by_sect(item)
        by_sect = {
            sect: "not_peregrine" if held or triplicity[sect] else "peregrine"
            for sect in ("day", "night")
        }
        if by_sect["day"] == by_sect["night"]:
            status = by_sect["day"]
        elif is_day is None:
            status = "undetermined_sect_unknown"
        elif in_band:
            status = "undetermined_sect_near_horizon"
        else:
            status = by_sect["day" if is_day else "night"]
        if is_day is not None and not status.startswith("undetermined") and (
            triplicity["day" if is_day else "night"]
        ):
            held.append("triplicity")
        item.update(
            {
                "status": status,
                "dignities_held": [name for name in PEREGRINE_DIGNITIES if name in held],
                "debilities_also": [
                    name
                    for name, signs in (
                        ("detriment", DETRIMENT_SIGNS[item["key"]]),
                        ("fall", (FALL_SIGNS[item["key"]],)),
                    )
                    if item["sign"] in signs
                ],
                "by_sect": by_sect,
            }
        )
        objects.append(item)
    return {
        "profile_id": PEREGRINE_PROFILE_ID,
        "technique": "peregrine",
        "source": PEREGRINE_SOURCE,
        "source_ref": PEREGRINE_SOURCE_REF,
        "basis": dict(PEREGRINE_BASIS),
        "statuses": list(PEREGRINE_STATUSES),
        "participant_scope": "classical_seven_planets_only",
        "objects": objects,
        "interpretation": None,
        "score": None,
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


# Every dignity table's basis; any other frame is refused (central frame table),
# so computed and refused receipts state the same basis.
DIGNITY_ZODIAC_BASIS = "tropical_ecliptic_of_date_nutation_on_earth_center"



def _frame_refused(frame_state, computation_mode, selected, computed, trace: Trace) -> dict:
    """The module refused by the central frame table; nothing is converted."""

    center = computation_mode.center
    refusal = frame_table_refusal(
        frame_state, trace, "具名古典尊貴元件",
        note=_DIGNITY_FRAME_REFUSAL_NOTES[frame_state["reason_code"]],
        inputs={
            "center": center,
            "zodiac": computation_mode.zodiac,
            "ecliptic_frame": computation_mode.ecliptic_frame,
            "nutation": computation_mode.nutation,
            "selected_profiles": selected,
        },
    )
    return {
        **method_head("named_essential_dignity_components_v1", "essential_dignities"),
        **refusal,
        "zodiac_basis": DIGNITY_ZODIAC_BASIS,
        "coordinate_center": center,
        "ecliptic_frame": computation_mode.ecliptic_frame,
        "nutation": computation_mode.nutation,
        "selected_profiles": selected,
        "computed_profiles": computed,
        "research_comparison_profiles": [],
        "research_only_profiles": [],
        "profile_results": {},
        "peregrine": None,
        "interpretation": None,
        "score": None,
    }

def _trace_computed(
    trace: Trace, selected: dict, computed: dict, include_triplicity_comparison: bool,
    sect_is_day, sect_basis: str, results: dict, peregrine: dict | None,
) -> None:
    trace.add(
        "具名古典尊貴元件",
        formula=(
            "tropical longitude -> whole-sign domicile/exaltation/detriment/fall "
            "match and/or "
            "source-named half-open table; no scoring or interpretation"
        ),
        inputs={
            "selected_profiles": selected,
            "computed_profiles": computed,
            "triplicity_research_comparison": include_triplicity_comparison,
            "sect_is_day": sect_is_day,
            "sect_basis": sect_basis,
        },
        result={
            "profile_ids": list(results),
            "peregrine": (
                None
                if peregrine is None
                else {
                    item["key"]: item["status"] for item in peregrine["objects"]
                }
            ),
        },
        note=(
            "Traditional-seven whole-sign domicile/exaltation and the detriment/fall "
            "opposite them are kept separate from exact exaltation- and fall-degree "
            "traditions. Dorothean, Ptolemy textual, "
            "Lilly compact, Egyptian, Chaldaean, Robbins and Lilly tables remain "
            "separate profiles. Peregrine, when requested, is judged on Lilly's "
            "p.104 set (sect ruler only for the triplicity), not on the selected "
            "profiles."
        ),
    )


@dataclass(frozen=True)
class DignitySelection:
    """The dignity techniques and tables the request names."""

    include_domicile_exaltation: bool
    bounds_profile: str | None
    decan_profile: str | None
    triplicity_profile: str | None
    include_triplicity_comparison: bool
    peregrine_profile: str | None


@dataclass(frozen=True)
class DignitySect:
    """The chart's sect as the dignities read it, and on what basis."""

    basis: str
    sun_altitude: float | None
    classification: dict


def compute_essential_dignities(
    *,
    bodies: list[dict],
    selection: DignitySelection,
    computation_mode,
    sect: DignitySect,
    trace: Trace,
) -> dict | None:
    """Compute selected source-named components for the classical seven only."""

    requested = bool(
        selection.include_domicile_exaltation
        or selection.bounds_profile
        or selection.decan_profile
        or selection.triplicity_profile
        or selection.include_triplicity_comparison
        or selection.peregrine_profile
    )
    if not requested:
        return None
    selected = {
        "domicile_exaltation": (
            DOMICILE_EXALTATION_PROFILE_ID
            if selection.include_domicile_exaltation
            else None
        ),
        "bounds": selection.bounds_profile,
        "face_decan": selection.decan_profile,
        "triplicity": selection.triplicity_profile,
        "peregrine": selection.peregrine_profile,
    }
    # What each technique's requested value expands to, in catalogue order: one
    # id for a single choice, every table for "all" (which has no primary
    # table).  The same whether or not the frame lets the module run, as the
    # Dossier's calculation_policy states it; profile_results says what ran.
    computed = {
        technique: expand_profiles(technique, requested)
        for technique, requested in (
            ("bounds", selection.bounds_profile),
            ("face_decan", selection.decan_profile),
            ("triplicity", selection.triplicity_profile),
        )
    }
    center = computation_mode.center
    ecliptic_frame = computation_mode.ecliptic_frame
    nutation = computation_mode.nutation
    sect_is_day = sect.classification["is_day"]
    frame_state = method_frame_state("essential_dignities", computation_mode)
    if not frame_state["applicable"]:
        return _frame_refused(frame_state, computation_mode, selected, computed, trace)
    usable_bodies = [body for body in bodies if body.get("longitude") is not None]
    results = {}
    if selection.include_domicile_exaltation:
        results[DOMICILE_EXALTATION_PROFILE_ID] = (
            _domicile_exaltation_profile(usable_bodies)
        )
    for profile_id in computed["bounds"]:
        results[profile_id] = _bounds_profile(profile_id, usable_bodies, sect_is_day)
    for profile_id in computed["face_decan"]:
        results[profile_id] = _decan_profile(profile_id, usable_bodies)
    # The comparison toggle adds the other tables beside a single choice; with
    # every table already side by side it adds nothing.
    comparison = (
        selection.include_triplicity_comparison and selection.triplicity_profile != ALL_PROFILES
    )
    triplicity_ids = list(computed["triplicity"])
    if comparison:
        triplicity_ids.extend(TRIPLICITY_IDS)
    triplicity_ids = list(dict.fromkeys(triplicity_ids))
    sect_dependent_components = [
        profile_id
        for profile_id in computed["bounds"]
        if profile_id == "chaldaean_bounds_ptolemy_i_21_v1"
    ] + triplicity_ids
    for profile_id in triplicity_ids:
        results[profile_id] = _triplicity_profile(
            profile_id, usable_bodies, sect_is_day
        )
    peregrine = None
    if selection.peregrine_profile:
        peregrine = _peregrine_profile(usable_bodies, sect.classification)
        sect_dependent_components.append(selection.peregrine_profile)

    _trace_computed(
        trace, selected, computed, selection.include_triplicity_comparison,
        sect_is_day, sect.basis, results, peregrine,
    )
    return {
        **method_head("named_essential_dignity_components_v1", "essential_dignities"),
        **computed_receipt(
            "selected_named_primary_text_profiles",
            available=bool(results) or peregrine is not None,
        ),
        "zodiac_basis": DIGNITY_ZODIAC_BASIS,
        "coordinate_center": center,
        "ecliptic_frame": ecliptic_frame,
        "nutation": nutation,
        "participant_scope": "classical_seven_planets_only",
        # 二元日夜盤結果旁必須附近地平提示；全部來自 lots.classify_sect（單一產生器），
        # 這裡不另算。sect_dependent_components 列出本次真正依日夜盤選主的元件。
        "sect": _sect_receipt(
            sect_is_day,
            sect.basis,
            sect.sun_altitude,
            sect.classification,
            sect_dependent_components,
        ),
        "selected_profiles": selected,
        # Read this, not selected_profiles, for the ids (see above).
        "computed_profiles": computed,
        "research_comparison_profiles": list(TRIPLICITY_IDS) if comparison else [],
        # 列為 research-only 的 profile，被選為主要 profile 時也標出。
        "research_only_profiles": research_only_profiles(results),
        "profile_results": results,
        "peregrine": peregrine,
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


_ORIGINAL, _TRANSLATION, _SECONDARY = SOURCE_READING_LEVELS[:3]
_ROBBINS_1964_SCANS = (
    "two scanned copies of the 1964 reprint of Robbins (Loeb 1940): Internet Archive "
    "L350ManethoHistoryOfEgyptPtolemyTetrabiblos and University of Toronto copy "
    "manethowithengli00maneuoft"
)
_LILLY_1647_P104_READ_AT = (
    "the scanned first edition, Wellcome copy, archive.org/details/b30338724 "
    "(leaves n137-n138), and the 1659 edition, p.104"
)

# The places each profile's statement and details name, as citation objects.  A
# level comes from what the profile's own verification record says was read;
# where it says nothing, only the reference is claimed.
PROFILE_SOURCE_CITATIONS: dict[str, list[dict[str, Any]]] = {
    "ptolemy_bounds_robbins_1940_v1": [
        cited(("Ptolemy, Tetrabiblos I.21, trans. Robbins (Loeb 1940) p.107, "
               "table 'Terms according to Ptolemy' (= Hübner 1998 I.21)"),
              "the complete table the profile uses, every cell", _TRANSLATION,
              f"{_ROBBINS_1964_SCANS}, p.107 (page n430)"),
        reference_only(
            "Ptolemy, Tetrabiblos I.20-21, trans. Robbins (Loeb 1940) pp.103-107",
            "Ptolemy's account of the terms (pp.103-105) and the table printed after it",
            "the record names p.107 (the table) and pp.106-107 (the Greek table and its "
            "apparatus) as read; for pp.103-105 only the reference is claimed",
        ),
    ],
    "egyptian_bounds_robbins_1940_v1": [
        cited(("Ptolemy, Tetrabiblos I.20, trans. Robbins (Loeb 1940) pp.96-97, "
               "the Greek and English tables of the Egyptian terms (= Hübner 1998 I.21)"),
              "the table the profile uses, every cell, and its totals (p.96 n.1)", _TRANSLATION,
              f"{_ROBBINS_1964_SCANS}, pp.96-97 (pages n419-n420)"),
        reference_only(
            f"Ptolemy, Tetrabiblos I.20, trans. Robbins (Loeb 1940) "
            f"{ROBBINS_EGYPTIAN_TERMS_PAGES}",
            "the chapter on the Egyptian terms",
            "the record names pp.96-97 as read; for pp.91-95 only the reference is claimed",
        ),
        cited("Firmicus Maternus, Mathesis II.6.2-13 (Kroll-Skutsch 1897 vol. I pp.47-49)",
              ("a variant witness, not support: nine signs agree with the table cell for "
               "cell; Gemini (II.6.4: Mercury, Jupiter, Venus, Mars, Saturn 6 each, against "
               "Venus 5, Mars 7), Cancer (II.6.5: Mercury 7, Saturn 3, against 6 and 4) and "
               "Sagittarius (II.6.10: Mercury 6, Saturn 4, Mars 3, against 4, 5, 4) differ"),
              ORIGINAL_LANGUAGE_READ,
              ("the Kroll-Skutsch Latin in the LacusCurtius transcription (Mathesis "
               "book II), compared sign by sign with the table's bounds")),
        reference_only(
            "Vettius Valens, Anthologies I.3",
            "a witness to the Egyptian terms",
            "the witness list says this was checked but not in which text or edition; "
            "only the reference is claimed",
        ),
    ],
    "chaldaean_bounds_ptolemy_i_21_v1": [
        reference_only(
            "Ptolemy, Tetrabiblos I.21, trans. Robbins (Loeb 1940) pp.99-101 (= Hübner 1998 I.21)",
            "the Chaldaean terms as a prose rule, no table",
            "level pending: the record gives the chapter and Robbins's pages but does not "
            "say what was read; only the reference is claimed",
        ),
    ],
    "ptolemy_triplicity_textual_corulership_v1": [
        reference_only(
            "Ptolemy, Tetrabiblos I.18, trans. Robbins (Loeb 1940) pp.83-87 (= Hübner 1998 I.19)",
            "two planets for each of fire, earth and air; Mars for water, with Venus by "
            "day and the Moon by night",
            "checked against an online transcription, not the printed page (PAL ed. 9 "
            "text 1, 〈I.19〉); the record does not say whether the Greek or a translation "
            "was read, so only the reference is claimed",
        ),
    ],
    "lilly_received_bounds_1647_v1": [
        cited(("William Lilly, Christian Astrology (1647) p.104, Table of the "
               "Essential Dignities, Termes columns"),
              "the table the profile uses", _ORIGINAL, _LILLY_1647_P104_READ_AT),
        cited(("William Lilly, Christian Astrology (1647) planet chapters, "
               "pp.57, 62, 66, 73, 76-77"),
              "the terms each planet's chapter lists, compared with the p.104 table", _ORIGINAL,
              ("as the Leo row's evidence records; the record does not say which "
               "copy of the 1647 text was read for these pages")),
        reference_only(
            "Robbins 1940 p.108 n.1",
            "the manuscripts' planet totals (Jupiter 79, Mars 66)",
            "read for the Ptolemaic terms' Libra row (see that profile); here only the "
            "reference is claimed",
        ),
    ],
    "lilly_triplicity_compact_1647_v1": [
        cited(("William Lilly, Christian Astrology (1647) p.104, triplicity columns Di. "
               "and Noc.; p.105"),
              "the day and night triplicity table; Mars rules water by day and night",
              "original_language_read",
              ("the 1647 printing as scanned at archive.org (b30338724, n137-n138) "
               "(= pp.104-105): the water row reads Mars in both columns, and p.105 "
               "'ruleth onely that Triplicity both day and night'")),
    ],
    "manilius_sign_decans_astronomica_iv_v1": [
        cited("Manilius, Astronomica IV.310-362",
              "the decan assignments, Pisces decans 1-2 at IV.359-360", _ORIGINAL,
              ("Latin text, The Latin Library (manilius4.html), checked against "
               "the online transcription, not the printed page")),
        cited("Manilius, Astronomica IV.294-386", "the decan passage", "original_language_read",
              ("Latin text, The Latin Library (manilius4.html), the whole passage from "
               "'Sed nihil in semet totum valet' (294) to 'mixta sed in pluris sociantur "
               "sidera vires' (386), the online transcription, not the printed page")),
    ],
    "chaldean_planetary_faces_firmicus_ii_4_v1": [
        cited("Firmicus Maternus, Mathesis II.4.3 (Kroll-Skutsch 1897 vol. I p.45)",
              "the complete 36-face table, every face", _ORIGINAL,
              ("the archive.org OCR text of matheseoslibrivi01firmuoft; checked "
               "against the online transcription, not the printed page")),
        reference_only(
            "Firmicus Maternus, Mathesis II.4 (Kroll-Skutsch 1897 vol. I pp.44-46)",
            "the chapter around the table",
            "p.45 was read; for the rest of the chapter only the reference is claimed",
        ),
        cited(("Paulus Alexandrinus, Introduction ch.4 (Boer 1958 numbering, main "
               "text; Schmidt/Hand 1995 pp.9-10)"),
              "the 'seven-zoned sphere', a parallel witness", _SECONDARY,
              ("the order and the term as the method research report gives them; "
               "Boer 1958 and Schmidt/Hand 1995 not checked")),
        reference_only(
            "William Lilly, Christian Astrology (1647) p.104, face columns",
            "a later witness to the same order",
            "level pending: the record does not say which copy, or that the face columns "
            "were read; only the reference is claimed",
        ),
        reference_only(
            "Ptolemy, Tetrabiblos I.23, trans. Robbins (Loeb 1940) pp.111-113",
            "Ptolemy's 'proper face', a different doctrine that shares only the name",
            "level pending: the record does not say what was read; only the reference "
            "is claimed",
        ),
    ],
    "dorothean_triplicity_three_rulers_v1": [
        cited("Dorotheus, Carmen Astrologicum I.1 (Pingree 1976 pp.161-162)",
              "the triplicity rulers; in Virgo also a share for Mercury (p.162)", _TRANSLATION,
              (f"{DOROTHEUS_BOOK_I_ONLINE}: I.1 on pp.161-162, 'and in Virgo is also a "
               "share for Mercury' at the head of p.162; the Arabic not checked")),
        cited("Dorotheus, Carmen Astrologicum I.28 (Pingree 1976 p.196)",
              "the third ruler, 'the associate of these two'", _TRANSLATION,
              (f"{DOROTHEUS_BOOK_I_ONLINE}: I.28 on p.196, 'the associate of these "
               "two'; the Arabic not checked")),
        cited("Hephaestio, Apotelesmatica I.6", "the Greek verse with the same four triads",
              _ORIGINAL,
              ("an online transcription following CCAG/TLG (astrologicon.org, "
               "Apotelesmatika book 1, ch. 6 'Peri ton trigonon hos Dorotheos'), "
               "re-read at that chapter on 2026-10-19: the four triads and Mercury's "
               "share in Virgo; the Pingree 1973 edition not checked")),
        reference_only(("Hephaestio of Thebes, Apotelesmatics Book I, trans. R. Schmidt "
                        "(Project Hindsight, 1994) p.30"),
                       "Hephaestio's verse in translation", "not checked"),
        cited("Dorotheus, Carmen Astrologicum I.4 (Pingree 1976 pp.163-164)", "the use of the rulers",
              "translation_read",
              (f"{DOROTHEUS_BOOK_I_ONLINE}: I.4 begins on p.163 with 'the first, "
               "second, and third lords of the triplicity' and runs on to p.164, where "
               "I.5 begins; the Arabic not checked")),
        cited("Dorotheus, Carmen Astrologicum I.10 (Pingree 1976 p.167)",
              "the word 'participant' for the third ruler", "translation_read",
              (f"{DOROTHEUS_BOOK_I_ONLINE}: I.10 at the foot of p.167, 'the first lord "
               "of the triplicity of the Moon or its participant by night'; the Arabic "
               "not checked")),
    ],
}


def _register_entry(profile_id: str, statement: str, details: dict | None) -> dict:
    entry: dict[str, Any] = {
        "applies_to": f"derived_methods.essential_dignities.profile_results.{profile_id}",
        "statement": statement,
    }
    if details is not None:
        entry["details"] = copy.deepcopy(details)
    if profile_id in PROFILE_SOURCE_CITATIONS:
        entry["sources"] = copy.deepcopy(PROFILE_SOURCE_CITATIONS[profile_id])
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
        "sources": [
            *copy.deepcopy(DOMICILE_EXALTATION_SOURCES),
            {
                **reference_only(
                    "Vettius Valens, Anthologies III.4 (Riley, CSUS PDF (2010) printed p.61)",
                    "the printed page of the chapter in the PDF (PDF page 63) as a locator",
                    "the chapter was read in a reformatted online copy (github "
                    "janegca/latex-valens), not in this PDF; only the page reference is "
                    "claimed",
                ),
                "role": "page_locator_of_an_also_attested_source",
            },
            cited("Firmicus Maternus, Mathesis II.2 (Kroll–Skutsch 1897, vol. I)", "the domiciles",
                  "original_language_read",
                  ("the Latin of Kroll-Skutsch as transcribed on LacusCurtius "
                   "(Firmicus_Maternus/Mathesis/2*.html), II.2 'De Domibus Stellarum', "
                   "II.2.5 'Saturnus habet domicilium in Aquario et Capricorno'"),
                  role="chapter_reference_of_an_also_attested_source"),
        ],
        "source_scope_note": DOMICILE_EXALTATION_SOURCE_SCOPE_NOTE,
        "component_sources": copy.deepcopy(DEBILITY_COMPONENT_SOURCES),
        "participant_note": DEBILITY_PARTICIPANT_NOTE,
        "degree_policy": "specific_exaltation_and_fall_degrees_not_selected_or_evaluated",
        "not_evaluated": ["reception"],
    },
    PEREGRINE_SOURCE_REF: {
        "applies_to": "derived_methods.essential_dignities.peregrine",
        "statement": PEREGRINE_SOURCE,
        "rule": PEREGRINE_RULE,
        "basis": dict(PEREGRINE_BASIS),
        "basis_note": PEREGRINE_BASIS_NOTE,
        "statuses": list(PEREGRINE_STATUSES),
        "table_dependence": PEREGRINE_TABLE_DEPENDENCE,
        "term_note": PEREGRINE_TERM_NOTE,
        "sources": copy.deepcopy(PEREGRINE_SOURCES),
        "not_evaluated": ["reception"],
    },
}
