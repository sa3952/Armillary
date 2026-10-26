"""Bounded sensitivity summaries for hour-level and date-only inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
import datetime as dtmod
from typing import Any, TypedDict
from zoneinfo import ZoneInfo

from .invariants import InternalInvariantError
from ..domain_catalog import LUNAR_APSIDES
from ..ephemeris import require_full_ephemeris, require_object_coverage
from .bodies import (
    DATE_ONLY_NO_BIRTH_TIME_REASON,
    EFFECTIVE_TOPOCENTRIC_MOON_LABELS,
    append_south_nodes,
    compute_bodies,
    node_definitions,
    withhold_horizontal_coordinates,
    effective_participants,
    geocentric_sun_true_altitude,
    make_longitude_sampler,
)
from .computation_mode import ComputationContext
from .dodecatemoria import compute_dodecatemoria
from .formatting import (
    ANGLE_KEYS,
    attach_sign_positions,
    degrees_number,
    longitude_number,
    zodiac_sign_index,
)
from .frame_compatibility import method_frame_state
from .house_placements import compute_planet_house_placements, whole_sign_point_placements
from .houses import (
    HouseSystemUnavailableError,
    compute_houses,
    printed_angles,
    printed_house_division,
)
from .extended_lots import attach_extended_lots
from .lots import classify_sect, compute_lots, determine_sect
from .moon import evaluate_void_of_course as void_of_course_verdict
from .time_utils import (
    AmbiguousLocalTimeChoiceRequiredError,
    NonexistentLocalTimeError,
    _existing_utc_instants,
    _to_utc_datetime,
    _local_wall_time_and_fold,
    MICROSECONDS_PER_SECOND,
    civil_hour_spans,
    civil_time_label,
    compute_time_conversion,
    repeated_wall_clock_stretches,
    utc_datetime_to_jd_ut,
    utc_offset_changes,
)
from .trace import Trace


# The one closed sensitivity vocabulary for every per-object, per-path and
# aggregate state in the block and the dossier ledger.  Whether the pass ran is
# a separate fact: the block's `status`, in the event-module vocabulary.
#
#   not_requested            the module that owns the path was not requested
#   not_applicable           requested, but nothing to compare in this mode or
#                            frame (a refused method, an object with no longitude)
#   not_evaluated            the value exists at the representative instant only
#   partially_evaluated      only part of the module was compared across samples
#   same_at_all_samples      the classification agreed at every sampled instant
#   differs_between_samples  the classification differed between sampled instants
#
# The last two describe classifications only: every value a path prints that is
# not a number on a continuum (printed_classifications below).  Longitudes,
# angles and cusps move inside any interval; they are reported as sampled
# envelopes and never carry a state, so "the sign did not change at the
# samples" cannot be read as "the result did not change".
SENSITIVITY_STATES = (
    "not_requested",
    "not_applicable",
    "not_evaluated",
    "partially_evaluated",
    "same_at_all_samples",
    "differs_between_samples",
)
(
    NOT_REQUESTED_STATE,
    NOT_APPLICABLE_STATE,
    NOT_EVALUATED_STATE,
    PARTIALLY_EVALUATED_STATE,
    SAME_AT_ALL_SAMPLES,
    DIFFERS_BETWEEN_SAMPLES,
) = SENSITIVITY_STATES

# Which response paths a sensitivity pass can speak about, and which dossier
# receipt (the one generator of that fact) says whether each path's module was
# requested and applicable.
#
# The universe is fixed, not narrowed to the request: a ledger that shrinks
# with the request leaves the reader to infer the rest from an absence.  Paths
# describing the request (atmosphere, time conversion, fixed-star policy) are
# not assessable.
ASSESSABLE_RESPONSE_PATHS: dict[str, tuple[str, tuple[str, ...]]] = {
    "astronomical_data.angles": ("modules", ("house_division",)),
    "astronomical_data.bodies": ("modules", ("core_positions",)),
    "astronomical_data.extra_angles": ("option_states", ("include_extra_angles",)),
    "astronomical_data.fixed_stars": ("modules", ("fixed_stars",)),
    "astronomical_data.horizon_events": ("modules", ("rise_set_transits",)),
    "astronomical_data.lunar_apsides": ("modules", ("lunar_apsides",)),
    "astronomical_data.lunar_events": ("modules", ("lunar_phases", "eclipses")),
    "astronomical_data.nodes": ("modules", ("core_positions",)),
    "astronomical_data.parallax_moon": ("modules", ("parallax_moon",)),
    "derived_geometry.antiscia": ("modules", ("antiscia",)),
    "derived_methods.aspects": ("modules", ("aspects",)),
    "derived_methods.declination_aspects": ("modules", ("declination_aspects",)),
    "derived_methods.essential_dignities": ("modules", ("essential_dignities",)),
    "derived_methods.house_division": ("modules", ("house_division",)),
    "derived_methods.lots": ("modules", ("lots",)),
    "derived_methods.planet_in_house": ("modules", ("planet_in_house",)),
    "derived_methods.sect": ("modules", ("sect",)),
    "derived_methods.void_of_course": ("modules", ("void_of_course",)),
    "derived_methods.dodecatemoria": ("modules", ("dodecatemoria",)),
    "derived_methods.classical_classifications": ("modules", ("classical_classifications",)),
}

# Which paths each pass recomputes at every sample when the owning module was
# computed (requested-ness comes from the dossier receipts).  What is compared
# inside a path is every classification it prints (printed_classifications);
# classification_coverage states per path what was compared and what differed.
RESAMPLED_PATHS_BY_PRECISION: dict[str, tuple[str, ...]] = {
    "approximate_hour": (
        "astronomical_data.angles",
        "astronomical_data.bodies",
        "derived_methods.house_division",
        "derived_methods.lots",
        "derived_methods.planet_in_house",
        "derived_methods.sect",
        "derived_methods.void_of_course",
        "derived_methods.dodecatemoria",
    ),
    "date_only": (
        "astronomical_data.bodies",
        "astronomical_data.nodes",
        "derived_methods.dodecatemoria",
    ),
}
DODECATEMORIA_PATH = "derived_methods.dodecatemoria"
EXTENDED_LOTS_PATH = "derived_methods.lots.extended_lots"
# Paths whose own changes are read at the samples only, never bisected.
_SAMPLED_ONLY_PATHS = (DODECATEMORIA_PATH, EXTENDED_LOTS_PATH)
# The void-of-course probe recomputes only the flag; the separating sign exit,
# the next perfected aspect, its time and the solver evidence are not
# re-evaluated at the samples, so they stay among the path's classifications
# that were not compared.
VOID_OF_COURSE_PATH = "derived_methods.void_of_course"
VOID_OF_COURSE_FLAG = f"{VOID_OF_COURSE_PATH}.is_void_of_course"

# A probe that cannot evaluate one sample degrades that sample and names the
# declared domain refusal.  A repeated instant with no fold is not here: that is
# the caller's choice, so the hour is refused before any probe
# (approximate_hour_representative_request), and a probe still meeting one
# lets the refusal through rather than shrink the hour.
UNEVALUABLE_SAMPLE_REASON_CODES: dict[type[Exception], str] = {
    NonexistentLocalTimeError: "local_time_nonexistent",
    HouseSystemUnavailableError: "house_system_unavailable_at_sample",
}
UNEVALUABLE_SAMPLE_ERRORS: tuple[type[Exception], ...] = tuple(
    UNEVALUABLE_SAMPLE_REASON_CODES
)


def _unevaluable_reason(error: Exception) -> str:
    # Called only for an instance of one of UNEVALUABLE_SAMPLE_ERRORS.
    return next(
        reason_code
        for kind, reason_code in UNEVALUABLE_SAMPLE_REASON_CODES.items()
        if isinstance(error, kind)
    )


# What a sensitivity result proves, stated once per precision.  Sampled
# evidence is distinct from enumerated transitions and certified enclosure;
# only sampled evidence is implemented, and no invariant argument is used to go
# beyond it.  The text is the same for every chart of a precision, so it is a
# method source register entry and the response names it (`method_source_ref`).
# date_only Moon sign transitions: the two samples lie in one stretch of the
# date, or in two stretches with another date's clock time between them.
MOON_TRANSITION_WITHIN_ONE_STRETCH = "crossing_exists_between_adjacent_samples_exact_time_not_solved"
MOON_TRANSITION_ACROSS_ANOTHER_DATE = (
    "crossing_exists_between_adjacent_samples_across_another_date_exact_time_not_solved"
)

SENSITIVITY_METHOD = {
    "approximate_hour": (
        "Classifications (every non-numeric value each resampled path prints: "
        "the sign of every longitude, angle, cusp and Lot; house placements of "
        "planets and Lots; motion direction; sect and its near-horizon band; the "
        "Lot formula basis; the void-of-course flag only; the twelfth-part of every "
        "point the chart lists) are recomputed at the "
        "listed sampled instants of the stated civil hour [H:00,H+1:00) in the named "
        "fold: a quarter-hour grid plus the seconds either side of any UTC-offset "
        "change inside the hour, located by a one-minute UTC scan refined to the "
        "second. same_at_all_samples means only that those sampled instants "
        "agree; it is not proof that the classification holds between them, and "
        "no invariant is applied to exclude a change and reversal between "
        "adjacent samples. Adjacent samples that differ are bisected to at most "
        "15 s; each bracket holds at least one change, not necessarily one. "
        "A twelfth-part's or an extended Lot's own change is not bisected: its "
        "classifications are those seen at the samples and at the midpoints "
        "other changes needed. "
        "Inside the polar circle the Ascendant can reverse between samples, so "
        "every path read off it is at most partially evaluated. "
        "Numeric values are sampled envelopes, not states. Every sample fails "
        "closed when its calculation did not use the Swiss files."
    ),
    "date_only": (
        "Classifications of bodies and nodes (every non-numeric value they print: "
        "sign, motion direction, reason codes) and of the planets' twelfth-parts "
        "are recomputed at the listed "
        "sampled instants of the local civil day, every instant the zone labels "
        "with the date (one or more UTC stretches): every existing hourly clock "
        "label on both folds, the first and last second of each stretch, and "
        "the seconds either side of every UTC-offset change that fall on the "
        "date, located by a one-minute UTC scan refined to the second. "
        "same_at_all_samples means only that those "
        "sampled instants agree; it is not proof that the classification holds "
        "between them, and no invariant is applied to exclude a change and "
        "reversal between adjacent samples. A Moon sign transition between the "
        "last sample of one stretch and the first of the next is marked as "
        "across another date: part of the time between them is labelled with "
        "another date. Numeric values are sampled "
        "envelopes, not states. Every sample fails closed when its calculation "
        "did not use the Swiss files."
    ),
}


def _option_module_state(receipt: dict) -> str:
    if not receipt["requested"]:
        return "not_requested"
    return "computed" if receipt["applicable"] else "not_applicable"


def coverage_ledger(
    sensitivity: dict,
    *,
    modules: dict,
    option_states: dict,
) -> dict | None:
    """One state per assessable path, or None when no interval exists.

    Requested and applicable come from the dossier's own module and option
    receipts, not from a static table (which would read an unrequested Lots
    module as recomputed and a module the user turned off as "not evaluated");
    what was compared comes from the pass's own per-path coverage, so the
    ledger cannot say more than the pass compared.  A refused pass still gives
    every computed path `not_evaluated`, since nothing was compared.
    """

    if sensitivity.get("status") not in ("computed", "not_applicable"):
        return None
    resampled = (
        RESAMPLED_PATHS_BY_PRECISION[sensitivity["precision"]]
        if sensitivity["status"] == "computed"
        else ()
    )
    compared = sensitivity.get("classification_coverage") or {}
    ledger: dict[str, str] = {}
    for path, (source, names) in ASSESSABLE_RESPONSE_PATHS.items():
        states = (
            [modules[name] for name in names]
            if source == "modules"
            else [_option_module_state(option_states[name]) for name in names]
        )
        if "computed" in states:
            if path not in resampled:
                ledger[path] = NOT_EVALUATED_STATE
            else:
                # A computed module the pass found nothing to compare in
                # (every object without a coordinate) compared nothing.
                ledger[path] = compared.get(path, {}).get(
                    "status", NOT_APPLICABLE_STATE
                )
        elif "not_applicable" in states:
            ledger[path] = NOT_APPLICABLE_STATE
        else:
            ledger[path] = NOT_REQUESTED_STATE
    return ledger


PROBE_OFFSETS_SECONDS = (0, 900, 1800, 2700, 3599)
TRANSITION_RESOLUTION_SECONDS = 15
# transitions[].semantics.  Two adjacent probes in different UTC stretches of
# the hour (the clock left the hour and came back) are not bisected: the
# instants between them are not in the hour, so the change lies outside it.
TRANSITION_SEMANTICS = (
    "bounded_bisection_of_a_sampled_classification_change",
    "sampled_classification_change_across_a_utc_gap_not_bisected",
)


def representative_semantics_for_offset(representative_offset_seconds: int) -> str:
    """The one producer of the approximate-hour representative label.

    HH:30 is preferred; when it does not exist on the clock the first real probe of
    the hour stands in (for example America/Caracas 2016-05-01 02h,
    Africa/Monrovia 1972-01-07 00h), and the label must not say "midpoint" then.
    """
    return (
        "representative_midpoint_not_exact_birth_time"
        if representative_offset_seconds == 1800
        else "representative_first_available_probe_not_exact_birth_time"
    )


def approximate_hour_representative_request(request):
    """Choose the midpoint when real, otherwise the first real governed probe.

    The hour is the whole civil hour, so a repeat anywhere in it needs the
    caller's fold even when HH:30 itself occurs once (else the repeated probes
    would be dropped as unevaluable).
    """

    timezone_input = request.timezone
    if "fold" not in timezone_input.model_fields_set:
        repeated = repeated_wall_clock_stretches(timezone_input, _hour_start(request))
        if repeated:
            first_from, first_to = repeated[0]
            raise AmbiguousLocalTimeChoiceRequiredError(
                f"{timezone_input.iana_name} 在這個民用小時內有一段鐘面時間出現兩次"
                f"（{first_from:%H:%M:%S} 至 {first_to:%H:%M:%S} 前）；approximate_hour 涵蓋"
                "整個小時，必須明確提供 timezone.fold=0 或 1，不能由系統替使用者猜測。"
            )
    preferred = (1800, *(value for value in PROBE_OFFSETS_SECONDS if value != 1800))
    for offset_seconds in preferred:
        candidate = _probe_request(request, offset_seconds)
        try:
            utc_value, _offset, _label, _warning = _to_utc_datetime(
                candidate.datetime,
                candidate.timezone,
                require_explicit_fold=True,
            )
        except NonexistentLocalTimeError:
            continue
        return candidate, offset_seconds, utc_value
    raise NonexistentLocalTimeError(
        "no instant in the stated civil hour exists in this time zone"
    )


class _ResolvedLocalInstant(TypedDict):
    local_time: str
    fold: int
    utc_datetime: dtmod.datetime
    utc_time: str


_ONE_SECOND = dtmod.timedelta(seconds=1)


def _resolved_instant(request, utc_value: dtmod.datetime) -> _ResolvedLocalInstant:
    label, fold = _local_wall_time_and_fold(utc_value, request.timezone)
    return {
        "local_time": label.isoformat(timespec="seconds"),
        "fold": fold,
        "utc_datetime": utc_value,
        "utc_time": utc_value.isoformat().replace("+00:00", "Z"),
    }


def _state(sampled_values: list) -> str:
    """Agreed at every sample or not: the only two things sampling observes."""

    return (
        SAME_AT_ALL_SAMPLES
        if len(sampled_values) <= 1
        else DIFFERS_BETWEEN_SAMPLES
    )


# `sampled_*` sets hold what the listed instants showed (the probes and every
# bisection midpoint), not every value the interval can take: a value between
# two samples is not in them.  The set and the envelope are read off one list
# of sampled values, so neither can include a sample the other left out.
def _sampled_signs(values: list[float]) -> tuple[list[int], dict]:
    envelope = _circular_envelope(values)
    return sorted({zodiac_sign_index(value) for value in envelope["sampled_values"]}), envelope


def _classified_envelope(values: list[float]) -> dict:
    signs, envelope = _sampled_signs(values)
    return {
        **envelope,
        "sampled_sign_indices": signs,
        "status": _state(signs),
    }


def _circular_envelope(values: list[float]) -> dict:
    """Return the smallest sampled arc, avoiding a false 0°/360° min/max span.

    Each sampled value is the number sign_position prints (10⁻⁶°, never across
    a whole degree), so a sign read off it is the sign of the raw value.
    """

    normalized = sorted(longitude_number(value) for value in values)
    # One value is its own arc: the only gap is (x - x) % 360 = 0.0.
    gaps = [
        ((normalized[(index + 1) % len(normalized)] - left) % 360.0, index)
        for index, left in enumerate(normalized)
    ]
    _largest_gap, gap_index = max(gaps)
    start = normalized[(gap_index + 1) % len(normalized)]
    end = normalized[gap_index]
    span = degrees_number((end - start) % 360.0)
    return {
        "start_degrees": start,
        "end_degrees": end,
        "span_degrees": span,
        "crosses_zero": end < start,
        "sampled_values": normalized,
    }


def _probe_request(request, offset_seconds: int):
    minute, second = divmod(offset_seconds, 60)
    return request.model_copy(
        update={
            "datetime": request.datetime.model_copy(
                update={"minute": minute, "second": float(second)}
            )
        }
    )


def _require_file_backed_samples(items: list[dict], jd_ut: float) -> None:
    """Fail closed at every sample, as the dossier's source policy says.

    A sample whose calculation silently changed source fails through the check
    the event searches use (a missing segment file leaves the pass unavailable;
    a fallback the manifest did not predict fails the request).
    """

    for item in items:
        if item.get("longitude") is None:
            continue
        for flag_key in ("retflag_ecliptic", "retflag_equatorial"):
            require_full_ephemeris(
                item[flag_key],
                operation="出生時間敏感度取樣",
                jd_ut=jd_ut,
            )


def _require_sample_coverage(defs: list[dict], jd_ut: float, context) -> None:
    """Refuse a sample before Swiss when a segment it reads does not cover it.

    A sample an hour or a day from the (manifest-gated) anchor can leave a
    segment: Chiron at 2399-12-31 23:59:59 UT is past seas_18 (23:51 UT), and a
    warm worker extrapolated it under SWIEPH, which the after-call retflag
    check accepted.
    """

    for definition in defs:
        require_object_coverage(
            body=definition["id"],
            flags=context.base_flags,
            jd_ut=jd_ut,
            operation="出生時間敏感度取樣",
        )


def _compute_effective_bodies(
    *, request, body_defs: list[dict], jd_ut: float, context, trace: Trace
) -> tuple[list[dict], ComputationContext | None]:
    """Apply the explicitly selected Moon origin to sensitivity probes too."""

    _require_sample_coverage(body_defs, jd_ut, context)
    # Physical records, like the chart's: a sample prints the same fields as
    # the representative chart, so every printed classification is comparable.
    bodies = compute_bodies(
        body_defs,
        jd_ut,
        context,
        request.atmosphere,
        trace,
        physical=True,
    )
    moon_context = None
    if request.options.moon_position_profile == "moon_only_topocentric_v1":
        moon_mode = request.computation_mode.model_copy(update={"center": "topocentric"})
        moon_context = ComputationContext(moon_mode, request.location)
        moon = {
            **compute_bodies(
                [next(body for body in body_defs if body["key"] == "moon")],
                jd_ut,
                moon_context,
                request.atmosphere,
                trace,
                physical=True,
            )[0],
            **EFFECTIVE_TOPOCENTRIC_MOON_LABELS,
        }
        bodies = [moon if body["key"] == "moon" else body for body in bodies]
    _require_file_backed_samples(bodies, jd_ut)
    return bodies, moon_context


def _probe_points(request, jd_ut: float, context, trace: Trace) -> list[dict]:
    """The nodes and lunar apsides a chart with this request emits, at a probe."""

    defs = node_definitions() + (
        [dict(body) for body in LUNAR_APSIDES] if request.options.include_lilith_priapus else []
    )
    _require_sample_coverage(defs, jd_ut, context)
    points = compute_bodies(
        defs, jd_ut, context, request.atmosphere, trace, physical=False, moon_relative=True,
    )
    if request.options.include_south_nodes:
        append_south_nodes(points, jd_ut, context, request.atmosphere, trace)
    return points


def _extract_probe(
    *,
    offset_seconds: int,
    request,
    body_defs: list[dict],
    evaluate_void_of_course: bool = True,
) -> dict:
    probe_request = _probe_request(request, offset_seconds)
    trace = Trace()
    time_conversion = compute_time_conversion(
        probe_request.datetime,
        probe_request.timezone,
        probe_request.location,
        trace,
        require_explicit_fold=True,
    )
    jd_ut = time_conversion["jd_ut"]
    context = ComputationContext(
        probe_request.computation_mode,
        probe_request.location,
    )
    bodies, moon_context = _compute_effective_bodies(
        request=probe_request,
        body_defs=body_defs,
        jd_ut=jd_ut,
        context=context,
        trace=trace,
    )
    houses = None
    if probe_request.options.include_houses:
        houses = compute_houses(
            probe_request.options.house_system,
            jd_ut,
            probe_request.location,
            context,
            trace,
        )
        house_receipt = {
            "system_code": probe_request.options.house_system,
            "system_name": houses["system_name"],
            "cusps": houses["cusps"],
        }
        placements = compute_planet_house_placements(
            bodies,
            house_receipt,
            context,
            trace,
        )
        # The nodes' and apsides' whole-sign places, as the chart prints them.
        placements["point_placements"] = whole_sign_point_placements(
            _probe_points(probe_request, jd_ut, context, trace)
            if probe_request.options.house_system == "W"
            else [],
            house_receipt,
            placements,
            trace,
        )
    else:
        placements = {
            "execution_status": "not_requested",
            "placements": [],
        }

    # Day or night at every probe, for _sect_dependent_dignity_limit.
    sect_is_day = (
        classify_sect(
            geocentric_sun_true_altitude(jd_ut, context, probe_request.atmosphere)
        )["is_day"]
        if context.horizon_meaningful
        else None
    )
    sect = lots = voc = None
    if probe_request.options.include_lots and houses is not None:
        body_map = {item["key"]: item for item in bodies}
        # 與主回應同一個 sect 產生器：地心太陽真高度。
        sect = determine_sect(
            geocentric_sun_true_altitude(jd_ut, context, probe_request.atmosphere),
            trace,
            display_center=probe_request.computation_mode.center,
        )
        # Probes resample only what the frame table lets the chart compute.
        if method_frame_state("lots", probe_request.computation_mode)["applicable"]:
            lots = compute_lots(
                houses["asc"],
                body_map["sun"]["longitude"],
                body_map["moon"]["longitude"],
                sect,
                trace,
                houses=houses,
            )
            attach_extended_lots(
                lots, ascendant=houses["asc"], bodies_by_key=body_map, houses=houses
            )
    dodecatemoria = _sample_dodecatemoria(
        probe_request, bodies, angles=houses, lots=lots, trace=trace
    )
    if evaluate_void_of_course and probe_request.options.include_void_of_course:
        voc = (
            # The chart's own VOC producer and participants (moon.py).
            void_of_course_verdict(
                bodies,
                trace,
                jd_ut=jd_ut,
                longitude_at=make_longitude_sampler(context, moon_ctx=moon_context),
                method=probe_request.options.void_of_course_method,
            )
            if method_frame_state("void_of_course", probe_request.computation_mode)[
                "applicable"
            ]
            else {"is_void_of_course": None}
        )

    return {
        "minute": offset_seconds // 60,
        "second": offset_seconds % 60,
        "input_local_time": time_conversion["input_local_time"],
        "void_of_course_evaluated": voc is not None,
        "bodies": bodies,
        "houses": houses,
        "placements": placements,
        "sect": sect,
        "sect_is_day": sect_is_day,
        "lots": lots,
        "dodecatemoria": dodecatemoria,
        "void_of_course": voc,
    }


def _sample_dodecatemoria(
    request, bodies: list[dict], *, angles: dict | None, lots: dict | None, trace: Trace
) -> dict | None:
    """The twelfth-parts one sample prints, from the chart's own producer.

    The same points as the chart: the seven planets, the ascendant when the
    sample has houses, the Lots when they were computed.  None when the chart
    does not compute the module, so a sample never prints what the chart lacks.
    """

    if not request.options.include_dodecatemoria:
        return None
    if not method_frame_state("dodecatemoria", request.computation_mode)["applicable"]:
        return None
    return compute_dodecatemoria(
        planets=effective_participants(
            bodies, include_nodes=False, include_outer_planets=False
        ),
        angles=angles,
        lots=lots if _usable(lots) else None,
        # The chart's own request ("all" too), so a sample prints the same
        # objects as the chart and every rule's signs are compared.
        profile=request.options.dodecatemoria_profile,
        trace=trace,
    )


def _dodecatemoria_signs(representative: dict | None, samples: list[dict | None]) -> list[dict] | None:
    """Per listed point: the twelfth-part signs the samples showed.

    The rows follow the chart's own points.  A twelfth-part jumps whenever its
    point enters a new sign, so no longitude envelope is given, only the signs
    seen at the listed instants; a sign between two samples is not in the set.
    """

    if representative is None or not _usable(representative):
        return None
    rows = []
    for point in representative["points"]:
        seen = [
            next(
                (row["longitude"] for row in sample["points"] if row["key"] == point["key"]),
                None,
            )
            if sample is not None and _usable(sample)
            else None
            for sample in samples
        ]
        signs = sorted({zodiac_sign_index(value) for value in seen if value is not None})
        rows.append(
            {
                "key": point["key"],
                "name": point["name"],
                "representative_sign_index": zodiac_sign_index(point["longitude"]),
                "sampled_sign_indices": signs,
                "status": (
                    _state(signs)
                    if all(value is not None for value in seen)
                    else PARTIALLY_EVALUATED_STATE
                ),
            }
        )
    return rows


# Lots 包絡的不連續狀態閉集。
LOTS_ENVELOPE_DISCONTINUITIES = ("none", "sect_flip")


# A body may legitimately have no longitude (the heliocentric Sun); anything
# re-reading bodies must carry the same allowance.
UNAVAILABLE_COORDINATE_STATUS = NOT_APPLICABLE_STATE

# A sign is printed as the first member of a sign position; the other two
# members render the longitude itself (in-sign DMS and decimal text) and move
# with it, like the float they render.
SIGN_POSITION_KEYS = frozenset(
    {"sign_position", "sign_positions", "cusp_sign_positions", "point_sign_position"}
)


# A pointer to where the method is documented: fixed per response shape, so no
# sample can move it and counting it would only inflate the count.
_NOT_CLASSIFICATIONS = frozenset({"source_ref"})


def printed_classifications(value: Any, path: str) -> dict[str, Any]:
    """Every classification a printed response object carries, by response path.

    A classification is any printed value that is not a number on a
    continuum: a boolean, an integer, a string or a null, and the sign of every
    printed sign position.  A `source_ref` is a documentation pointer, not a
    classification.  Floats move inside any interval and are reported
    as sampled envelopes.  Nothing is named here, so a classification a module
    starts printing (a Lot's house, sect's band status, a planet's motion) is
    compared without anyone remembering to add it.

    A list member is named by its `key` (and `role`, which tells the two Moon
    records of the mixed-origin profile apart), otherwise by its index.
    """

    found: dict[str, Any] = {}
    _collect(value, path, found)
    return found


def _member_name(item: Any, index: int) -> str:
    if isinstance(item, dict) and isinstance(item.get("key"), str):
        role = item.get("role")
        return f"{item['key']}:{role}" if isinstance(role, str) else item["key"]
    return str(index)


def _collect(value: Any, path: str, found: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _NOT_CLASSIFICATIONS:
                continue
            child = f"{path}.{key}"
            if key in SIGN_POSITION_KEYS:
                _collect_sign_positions(item, child, found)
            else:
                _collect(item, child, found)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _collect(item, f"{path}[{_member_name(item, index)}]", found)
    elif not isinstance(value, float):
        found[path] = value


def _collect_sign_positions(value: Any, path: str, found: dict[str, Any]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_sign_positions(item, f"{path}.{key}", found)
    elif isinstance(value, list) and value and isinstance(value[0], list):
        for index, item in enumerate(value):
            _collect_sign_positions(item, f"{path}[{index}]", found)
    else:
        # [sign_index, in-sign DMS, decimal longitude], or null.
        found[path] = value[0] if isinstance(value, list) and value else None


def _usable(module: Any) -> bool:
    return isinstance(module, dict) and module.get("available") is True


def _approximate_hour_printed_objects(probe: dict, request) -> dict[str, Any]:
    """What a probe prints at each resampled path, from the chart's own producers.

    The void-of-course path is not here: its probe recomputes only the flag.
    """

    houses = probe["houses"]
    objects: dict[str, Any] = {"astronomical_data.bodies": probe["bodies"]}
    if houses is not None:
        objects["astronomical_data.angles"] = printed_angles(houses)
        objects["derived_methods.house_division"] = printed_house_division(
            houses, request.options.house_system
        )
    if probe["placements"]["execution_status"] == "computed":
        objects["derived_methods.planet_in_house"] = probe["placements"]
    for path, module in (
        ("derived_methods.sect", probe["sect"]),
        ("derived_methods.lots", probe["lots"]),
        (DODECATEMORIA_PATH, probe.get("dodecatemoria")),
    ):
        if _usable(module):
            objects[path] = module
    return objects


def _with_sign_positions(objects: dict[str, Any]) -> dict[str, Any]:
    """Copies of printed objects carrying the page's sign positions.

    attach_sign_positions is the one producer of which longitudes print a sign,
    so a sample reads its signs from the same rule as the page.
    """

    layers: dict[str, dict[str, Any]] = {
        "astronomical_data": {}, "derived_geometry": {}, "derived_methods": {},
    }
    for path, value in _container_copy(objects).items():
        layer, name = path.split(".", 1)
        layers[layer][name] = value
    attach_sign_positions(
        astronomical_data=layers["astronomical_data"],
        derived_geometry=layers["derived_geometry"],
        derived_methods=layers["derived_methods"],
        birth_time_sensitivity=None,
    )
    return {
        f"{layer}.{name}": value
        for layer, values in layers.items()
        for name, value in values.items()
    }


def _container_copy(value: Any) -> Any:
    """A copy of every dict, list and tuple in a printed object, leaves shared.

    attach_sign_positions only adds keys to dicts, so copying the containers is
    all that keeps it off the chart's own records; the leaves (numbers,
    strings, None) are immutable.  copy.deepcopy would do the same at several
    times the cost, once per sample.
    """

    if isinstance(value, dict):
        return {key: _container_copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_container_copy(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_container_copy(item) for item in value)
    return value


def _classifications_by_path(objects: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        path: printed_classifications(value, path)
        for path, value in _with_sign_positions(objects).items()
    }


def _prints_a_value(value: Any) -> bool:
    """Whether a printed object holds any number at all.

    A path whose every record is null with its reason (the heliocentric
    nodes) has nothing at this instant that a sample could move.
    """

    if isinstance(value, dict):
        return any(_prints_a_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_prints_a_value(item) for item in value)
    return isinstance(value, float)


def _classification_state(probe: dict, request) -> dict[str, Any]:
    """Every printed classification at one sampled instant, by leaf path."""

    state: dict[str, Any] = {}
    for leaves in _classifications_by_path(
        _approximate_hour_printed_objects(probe, request)
    ).values():
        state.update(leaves)
    voc = probe["void_of_course"]
    if isinstance(voc, dict) and "is_void_of_course" in voc:
        state[VOID_OF_COURSE_FLAG] = voc["is_void_of_course"]
    return state


def _classification_coverage(
    printed: dict[str, Any],
    universe: dict[str, dict[str, Any]],
    compared_states: list[dict[str, Any]],
    refinement_states: list[dict[str, Any]],
) -> dict[str, dict]:
    """Per path: what it prints, what was compared, and what differed.

    The universe is what the representative chart prints at each path.  A
    classification counts as compared when every listed sample evaluated it;
    one that differs between any evaluated instants (the samples and the
    bisection midpoints) makes the path differ, and a path with a
    classification no sample could evaluate is at most partially evaluated.
    A path that prints no value at all is not applicable: nothing was there
    to compare.
    """

    coverage: dict[str, dict] = {}
    for path, leaves in universe.items():
        if not _prints_a_value(printed[path]):
            coverage[path] = {
                "status": NOT_APPLICABLE_STATE,
                "classification_count": len(leaves),
                "not_compared_count": len(leaves),
                "differing_classifications": [],
            }
            continue
        differing = []
        not_compared = 0
        for leaf in leaves:
            values = [state[leaf] for state in compared_states if leaf in state]
            if len(values) < len(compared_states):
                not_compared += 1
            values += [state[leaf] for state in refinement_states if leaf in state]
            if len(set(values)) > 1:
                differing.append(leaf)
        coverage[path] = {
            "status": (
                DIFFERS_BETWEEN_SAMPLES if differing
                else PARTIALLY_EVALUATED_STATE if not_compared
                else SAME_AT_ALL_SAMPLES
            ),
            "classification_count": len(leaves),
            "not_compared_count": not_compared,
            "differing_classifications": sorted(differing),
        }
    return coverage


def _coverage_status(coverage: dict[str, dict]) -> str:
    """The block's one word: differs, else partial, else same.

    A difference seen on a path whose evaluation is limited is still a
    difference between samples.
    """

    if any(record["differing_classifications"] for record in coverage.values()):
        return DIFFERS_BETWEEN_SAMPLES
    states = {record["status"] for record in coverage.values()}
    for state in (
        DIFFERS_BETWEEN_SAMPLES, PARTIALLY_EVALUATED_STATE, SAME_AT_ALL_SAMPLES,
    ):
        if state in states:
            return state
    return NOT_APPLICABLE_STATE


# Inside the polar circle the Ascendant can jump half the zodiac within
# minutes and come back (1968-03-19 14h, 66.56°S: 88.7° to 268.7° at 14:53,
# 93.6° at 14:59:59), so the samples and even the bisection midpoints can
# skip signs and houses that the hour held.  Every path read off the
# Ascendant is then only partly evaluated, whatever the samples showed; what
# differed is still listed.
POLAR_ASCENDANT_LIMIT = "polar_ascendant_can_reverse_between_samples"
# A little inside the circle the Ascendant never turns back, but near the
# moment the ecliptic lies along the horizon it can run through several signs
# within seconds (2065-12-12, 66.56°S: 126° to 248° in 20 s), faster than the
# 15-second bisection.  Everything read off it then moves the same way, one
# sign or house after the next, so two neighbouring evaluated instants whose
# sign or house is two or more apart skipped what lay between: those paths
# are only partly evaluated.
SKIPPED_ASCENDANT_CLASSES_LIMIT = "ascendant_moved_past_whole_signs_or_houses_between_samples"
ASCENDANT_DEPENDENT_PATHS = (
    "astronomical_data.angles",
    "derived_methods.house_division",
    "derived_methods.planet_in_house",
    "derived_methods.lots",
)


def _twelve_step_class(leaf: str, value: Any) -> bool:
    """A sign index or a house number read off the Ascendant: one of twelve
    classes in a cycle (``placements[sun].house``, ``fortune_house``,
    ``house_placement.fortune``, ``cusp_sign_positions[0]``, ...)."""

    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return _twelve_step_leaf(leaf)


def _twelve_step_leaf(leaf: str) -> bool:
    """Whether a leaf path names a sign or a house read off the Ascendant."""

    module = next((path for path in ASCENDANT_DEPENDENT_PATHS if leaf.startswith(path + ".")), None)
    if module is None:
        return False
    within = leaf[len(module) + 1:]
    return "house" in within or any(key in within for key in SIGN_POSITION_KEYS)


def _ascendant_classes_skipped(evaluated: list[tuple[int, int, dict[str, Any]]]) -> bool:
    """Whether two neighbouring evaluated instants of one UTC stretch put a
    sign or a house read off the Ascendant two or more steps apart.

    ``evaluated`` holds (offset seconds, UTC stretch, classification state)
    for every probe and bisection midpoint.
    """

    ordered = sorted(evaluated, key=lambda item: item[0])
    # Every instant prints the same few thousand leaves; whether a path is one
    # of the twelve-step classes is read once per path, not once per pair.
    leaf_kinds: dict[str, bool] = {}
    for (_, left_stretch, left), (_, right_stretch, right) in zip(ordered, ordered[1:]):
        if left_stretch != right_stretch:
            continue
        for leaf, value in left.items():
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            kind = leaf_kinds.get(leaf)
            if kind is None:
                kind = leaf_kinds[leaf] = _twelve_step_leaf(leaf)
            other = right.get(leaf)
            if kind and isinstance(other, int) and _twelve_step_class(leaf, other):
                step = (other - value) % 12
                if min(step, 12 - step) >= 2:
                    return True
    return False


def _evaluation_limits(representative_houses: dict | None, *, skipped: bool) -> list[dict]:
    if representative_houses is None:
        return []
    if representative_houses["latitude_regime"]["band"] == "beyond_polar_circle":
        reason = POLAR_ASCENDANT_LIMIT
    elif skipped:
        reason = SKIPPED_ASCENDANT_CLASSES_LIMIT
    else:
        return []
    return [
        {
            "reason_code": reason,
            "affected_paths": list(ASCENDANT_DEPENDENT_PATHS),
        }
    ]


# The essential dignities are not resampled: every table is read at the
# representative instant, and the triplicity ruler, the Chaldaean bounds and
# peregrine take that instant's day or night.  When the probes of the hour fall
# on both sides of sunrise or sunset, those tables would read the other sect for
# part of the hour; the limit says so beside the dignities' not_evaluated.
SECT_DEPENDENT_DIGNITIES_LIMIT = "sect_differs_between_samples_dignities_read_at_representative_only"
ESSENTIAL_DIGNITIES_PATH = "derived_methods.essential_dignities"


def _sect_dependent_dignity_limit(
    representative_dignities: dict | None, evaluated: list[dict]
) -> list[dict]:
    if not isinstance(representative_dignities, dict) or not representative_dignities.get("available"):
        return []
    if not representative_dignities["sect"]["sect_dependent_components"]:
        return []
    if len({probe["sect_is_day"] for probe in evaluated}) < 2:
        return []
    return [{
        "reason_code": SECT_DEPENDENT_DIGNITIES_LIMIT,
        "affected_paths": [ESSENTIAL_DIGNITIES_PATH],
    }]


def _apply_evaluation_limits(coverage: dict[str, dict], limits: list[dict]) -> None:
    for limit in limits:
        for path in limit["affected_paths"]:
            record = coverage.get(path)
            if record is not None and record["status"] != NOT_APPLICABLE_STATE:
                record["status"] = PARTIALLY_EVALUATED_STATE


def _hour_start(request) -> dtmod.datetime:
    """The stated civil hour's naive wall-clock start."""

    value = request.datetime
    return dtmod.datetime(value.year, value.month, value.day, value.hour)


def _format_local_offset(request, offset_seconds: int) -> str:
    start = _hour_start(request)
    return (start + dtmod.timedelta(seconds=offset_seconds)).isoformat(
        timespec="seconds"
    )


def _refine_transitions(
    *,
    request,
    body_defs: list[dict],
    probes_by_offset: dict[int, dict],
    stretch_of: dict[int, int],
) -> tuple[list[dict], dict[int, dict], dict[int, dict]]:
    """Refine only sampled classification changes; hidden reversals remain possible.

    Returns the brackets, every midpoint probe the bisection computed (so the
    classifications those midpoints printed are not thrown away), and the
    classification state of every probe it read, by offset, each the state of
    the probe kept for that offset.
    ``stretch_of`` gives each probe offset's UTC stretch of the hour; a change
    between two stretches is reported at their facing ends, not bisected, since
    the clock seconds between them name instants outside the hour.
    """

    missing = object()
    brackets: dict[tuple[int, int], set[str]] = {}
    gap_brackets: dict[tuple[int, int], set[str]] = {}
    refinement: dict[int, dict] = {}
    states: dict[int, dict] = {}

    def state_at(offset: int, path: str | None = None) -> dict:
        # The void-of-course verdict is a forward event search and by far the
        # costliest part of a probe.  A midpoint that only has to place a sign
        # or a house skips it; the flag itself is still bisected on full probes.
        probe: dict | None
        if offset in probes_by_offset:
            probe = probes_by_offset[offset]
        else:
            needs_voc = path == VOID_OF_COURSE_FLAG
            probe = refinement.get(offset)
            if probe is None or (needs_voc and not probe["void_of_course_evaluated"]):
                probe = _extract_probe(
                    offset_seconds=offset,
                    request=request,
                    body_defs=body_defs,
                    evaluate_void_of_course=needs_voc,
                )
                refinement[offset] = probe
                states.pop(offset, None)
        if offset not in states:
            states[offset] = _classification_state(probe, request)
        return states[offset]

    ordered_offsets = sorted(probes_by_offset)
    for segment_left, segment_right in zip(
        ordered_offsets,
        ordered_offsets[1:],
    ):
        left_state = state_at(segment_left)
        right_state = state_at(segment_right)
        if left_state == right_state:
            continue

        # A twelfth-part changes sign twelve times faster than its point, and
        # the extended lots are many points each moving with the Ascendant, so
        # bisecting their changes would multiply the probes (about four times
        # for a chart with Lots); their classifications are read at the
        # samples and at the midpoints other changes need, not bisected.
        changed_paths = sorted(
            key
            for key in set(left_state) | set(right_state)
            if left_state.get(key, missing) != right_state.get(key, missing)
            and not key.startswith(_SAMPLED_ONLY_PATHS)
        )
        if stretch_of[segment_left] != stretch_of[segment_right]:
            if changed_paths:
                gap_brackets[(segment_left, segment_right)] = set(changed_paths)
            continue
        for path in changed_paths:
            left_offset = segment_left
            right_offset = segment_right
            left_value = left_state.get(path, missing)
            while right_offset - left_offset > TRANSITION_RESOLUTION_SECONDS:
                midpoint = (left_offset + right_offset) // 2
                try:
                    midpoint_state = state_at(midpoint, path)
                except UNEVALUABLE_SAMPLE_ERRORS:
                    break
                if midpoint_state.get(path, missing) == left_value:
                    left_offset = midpoint
                else:
                    right_offset = midpoint
            brackets.setdefault((left_offset, right_offset), set()).add(path)

    # Paths that change at the same instant bisect through the same midpoints
    # and land in the same bracket (under whole-sign houses one Ascendant sign
    # change moves every placement and cusp at once), so one record names them.
    records = [
        (bounds, paths, TRANSITION_SEMANTICS[0]) for bounds, paths in brackets.items()
    ] + [(bounds, paths, TRANSITION_SEMANTICS[1]) for bounds, paths in gap_brackets.items()]
    transitions = [
        {
            "lower_bound_local": _format_local_offset(request, left_offset),
            "upper_bound_local": _format_local_offset(request, right_offset),
            "resolution_seconds": right_offset - left_offset,
            "changed_paths": sorted(paths),
            "semantics": semantics,
        }
        for (left_offset, right_offset), paths, semantics in sorted(
            records, key=lambda record: record[0]
        )
    ]
    return transitions, refinement, states


def _whole_second_label(iso_local: str) -> str:
    """An ISO wall-clock second in the shape of ``input_local_time``."""

    value = dtmod.datetime.fromisoformat(iso_local)
    return civil_time_label(
        value.year, value.month, value.day, value.hour, value.minute,
        value.second * MICROSECONDS_PER_SECOND,
    )


def _probe_fold(request, offset_seconds: int) -> int:
    """Which occurrence of its wall-clock label a sampled instant is (PEP 495).

    The label alone does not say it.  With fold=1 in a fully repeated
    hour every probe is the second occurrence; in a partly repeated hour
    (America/St_Johns 2005-10-29 23h repeats 23:01-23:59:59) the probes outside
    the repeat occur once and are fold 0.  Read back from the instant the probe
    was computed at, as date_only samples carry theirs.
    """

    probe = _probe_request(request, offset_seconds)
    utc_value, _offset, _label, _warning = _to_utc_datetime(probe.datetime, probe.timezone)
    return _local_wall_time_and_fold(utc_value, request.timezone)[1]


def _probe_utc(request, offset_seconds: int) -> dtmod.datetime:
    probe = _probe_request(request, offset_seconds)
    return _to_utc_datetime(probe.datetime, probe.timezone)[0]


def _stretch_index(spans: list, moment: dtmod.datetime) -> int:
    return next(index for index, (start, end) in enumerate(spans) if start <= moment < end)


def _clock_change_edge_offsets(request) -> list[int]:
    """Seconds into the stated hour on either side of a UTC-offset change.

    The quarter-hour grid assumes the hour is one unbroken stretch
    of clock time.  When the zone changes offset inside it, the first and last
    existing seconds of each stretch are sampled too, keeping only those that
    belong to the fold the request named: both sides of each change, and both
    ends of each UTC stretch the hour covers (``civil_hour_spans``), so where
    the clock leaves the hour and comes back each stretch is bounded by its own
    probes.
    """

    timezone_input = request.timezone
    if timezone_input.mode != "iana":
        return []
    zone = ZoneInfo(timezone_input.iana_name)
    hour_start = _hour_start(request)
    hour_end = hour_start + dtmod.timedelta(hours=1)
    bounds = [
        label.replace(tzinfo=zone, fold=fold).astimezone(dtmod.timezone.utc)
        for label in (hour_start, hour_end)
        for fold in (0, 1)
    ]
    margin = dtmod.timedelta(hours=1)
    offsets: set[int] = set()
    candidates = [
        moment
        for change in utc_offset_changes(zone, min(bounds) - margin, max(bounds) + margin)
        for moment in (change - _ONE_SECOND, change)
    ] + [
        moment
        for start, end in civil_hour_spans(timezone_input, hour_start)
        for moment in (start, end - _ONE_SECOND)
    ]
    for moment in candidates:
        label, _fold = _local_wall_time_and_fold(moment, timezone_input)
        if not hour_start <= label < hour_end:
            continue
        offset_seconds = int((label - hour_start).total_seconds())
        try:
            resolved, _offset, _label, _warning = _to_utc_datetime(
                _probe_request(request, offset_seconds).datetime,
                timezone_input,
            )
        except NonexistentLocalTimeError:
            continue
        if resolved == moment:
            offsets.add(offset_seconds)
    return sorted(offsets)


def _sampled_sign_row(
    key: str,
    name: str,
    values: list[float] | None,
    *,
    representative: tuple[str, Callable[[list[float]], Any]],
    envelope_key: str,
) -> dict:
    """One object's sampled signs; `values` is None when a sample had no longitude."""
    representative_key, representative_of = representative
    if values is None:
        return {
            "key": key,
            "name": name,
            representative_key: None,
            "sampled_sign_indices": [],
            "status": UNAVAILABLE_COORDINATE_STATUS,
            envelope_key: None,
        }
    sampled_signs, envelope = _sampled_signs(values)
    return {
        "key": key,
        "name": name,
        representative_key: representative_of(values),
        "sampled_sign_indices": sampled_signs,
        "status": _state(sampled_signs),
        envelope_key: envelope,
    }


def _probe_receipt(request, probe: dict) -> dict:
    return {
        "minute": probe["minute"],
        "second": probe["second"],
        "input_local_time": probe["input_local_time"],
        "fold": _probe_fold(request, probe["minute"] * 60 + probe["second"]),
    }


def _sample_hour_probes(
    request, body_defs: list[dict], requested_offsets: list[int],
    representative: dict, representative_offset_seconds: int,
) -> tuple[dict[int, dict], list[dict]]:
    """Each requested offset's probe (the representative chart reused), and the skipped ones."""

    probes_by_offset: dict[int, dict] = {}
    skipped: list[dict] = []
    for offset_seconds in requested_offsets:
        try:
            probes_by_offset[offset_seconds] = (
                {
                    "minute": offset_seconds // 60,
                    "second": offset_seconds % 60,
                    **representative,
                }
                if offset_seconds == representative_offset_seconds
                else _extract_probe(
                    offset_seconds=offset_seconds, request=request, body_defs=body_defs
                )
            )
        except UNEVALUABLE_SAMPLE_ERRORS as error:
            skipped.append(
                {
                    "offset_seconds": offset_seconds,
                    "reason_code": _unevaluable_reason(error),
                }
            )
    return probes_by_offset, skipped


def _hour_body_signs(
    body_defs: list[dict], evaluated: list[dict], representative_index: int
) -> list[dict]:
    """Each body's sampled signs and longitude envelope."""

    body_signs = []
    for body_def in body_defs:
        values = [
            next(
                body["longitude"]
                for body in probe["bodies"]
                if body["key"] == body_def["key"]
            )
            for probe in evaluated
        ]
        body_signs.append(_sampled_sign_row(
            body_def["key"], body_def["zh"],
            None if any(value is None for value in values) else values,
            representative=(
                "representative_sign_index",
                lambda found: zodiac_sign_index(found[representative_index]),
            ),
            envelope_key="longitude_envelope",
        ))
    return body_signs


def _hour_planet_in_house(
    body_defs: list[dict], representative_placements: dict, evaluated: list[dict]
) -> list[dict]:
    """Each body's representative and sampled houses."""

    planet_in_house = []
    if representative_placements["execution_status"] == "computed":
        for body_def in body_defs:
            sampled_houses = sorted(
                {
                    next(
                        placement["house"]
                        for placement in probe["placements"]["placements"]
                        if placement["key"] == body_def["key"]
                    )
                    for probe in evaluated
                }
            )
            representative_house = next(
                placement["house"]
                for placement in representative_placements["placements"]
                if placement["key"] == body_def["key"]
            )
            planet_in_house.append(
                {
                    "key": body_def["key"],
                    "name": body_def["zh"],
                    "representative_house": representative_house,
                    "sampled_houses": sampled_houses,
                    "status": _state(sampled_houses),
                }
            )
    return planet_in_house


_ANGLE_AT_CUSP = {1: "asc", 4: "ic", 7: "desc", 10: "mc"}


def _hour_angle_envelopes(
    representative_houses: dict | None, evaluated: list[dict]
) -> tuple[dict, list[dict]]:
    """The angles' and house cusps' sampled envelopes."""

    # Declared so mypy does not type it from whichever branch it reads first.
    angles: dict
    house_cusps: list[dict]
    if representative_houses is not None:
        angle_values = {
            key: [probe["houses"][key] for probe in evaluated] for key in ANGLE_KEYS
        }
        angles = {key: _classified_envelope(values) for key, values in angle_values.items()}
        house_cusps = []
        for index in range(12):
            values = [probe["houses"]["cusps"][index] for probe in evaluated]
            # A quadrant system's cusps 1/4/7/10 are the angles themselves; a
            # cusp equal to its angle at every sample names the angle instead
            # of repeating its envelope.  Whole-sign, equal-from-MC and the
            # like differ from the angle, so they keep their own.
            angle = _ANGLE_AT_CUSP.get(index + 1)
            if angle is not None and angle_values[angle] == values:
                house_cusps.append({
                    "house": index + 1,
                    "same_as_angle": angle,
                    "status": angles[angle]["status"],
                })
            else:
                house_cusps.append({
                    "house": index + 1,
                    "same_as_angle": None,
                    **_classified_envelope(values),
                })
    else:
        angles = {
            "status": NOT_REQUESTED_STATE,
            "reason_code": "house_calculation_not_executed",
        }
        house_cusps = []
    return angles, house_cusps


def _hour_sect_summary(
    classification_coverage: dict, representative_sect: dict | None, evaluated: list[dict]
) -> dict | None:
    """The day/night flag and sect band across the samples, when sect printed."""

    sect_summary = None
    if "derived_methods.sect" in classification_coverage:
        if representative_sect is None:  # usable, so sect ran
            raise InternalInvariantError("representative_sect is not None")
        sect_summary = {
            "representative_is_day": representative_sect["is_day"],
            "sampled_is_day": list(
                dict.fromkeys(probe["sect"]["is_day"] for probe in evaluated)
            ),
            "representative_sect_status": representative_sect["sect_status"],
            "sampled_sect_statuses": list(
                dict.fromkeys(probe["sect"]["sect_status"] for probe in evaluated)
            ),
            # Every classification sect prints: the day flag, the band status
            # and the named boundary disagreement.
            "status": classification_coverage["derived_methods.sect"]["status"],
        }
    return sect_summary


def _hour_lots_summary(
    classification_coverage: dict, representative_lots: dict | None, evaluated: list[dict]
) -> dict[str, Any] | None:
    """The Lots' envelopes and houses across the samples, when the Lots printed."""

    lots_summary: dict[str, Any] | None = None
    if "derived_methods.lots" in classification_coverage:
        if representative_lots is None:  # usable, so the Lots ran
            raise InternalInvariantError("representative_lots is not None")
        lots_summary = {}
        for key in ("fortune", "spirit"):
            houses_at_samples = sorted(
                {probe["lots"]["house_placement"][key] for probe in evaluated}
            )
            lots_summary[key] = {
                **_classified_envelope([probe["lots"][key] for probe in evaluated]),
                "representative_house": (
                    representative_lots["house_placement"][key]
                ),
                "sampled_houses": houses_at_samples,
                "house_status": _state(houses_at_samples),
            }
        # 取樣點跨過日夜盤翻轉時，上面的包絡混了兩套公式，跳躍來自公式切換，
        # 不是點位連續移動。另給每套公式各自的連續包絡，並具名標出不連續。
        sect_flip = len({probe["sect"]["is_day"] for probe in evaluated}) > 1
        lots_summary["discontinuity"] = "sect_flip" if sect_flip else "none"
        lots_summary["discontinuity_states"] = list(LOTS_ENVELOPE_DISCONTINUITIES)
        lots_summary["by_sect"] = (
            {
                sect_key: {
                    key: _circular_envelope(
                        [probe["lots"]["by_sect"][sect_key][key] for probe in evaluated]
                    )
                    for key in ("fortune", "spirit")
                }
                for sect_key in ("day", "night")
            }
            if sect_flip
            else None
        )
        # Every classification the Lots print: signs, houses, the formula
        # basis, the sect status they repeat and the comparison values.
        lots_summary["status"] = classification_coverage["derived_methods.lots"][
            "status"
        ]
    return lots_summary


def _hour_voc_summary(
    voc_usable: bool, representative_void_of_course: dict | None, voc_evaluated: list[dict]
) -> dict | None:
    """The void-of-course verdicts across the samples that searched."""

    voc_summary = None
    if voc_usable:
        if representative_void_of_course is None:
            raise InternalInvariantError("representative_void_of_course is not None")
        sampled = list(
            dict.fromkeys(
                probe["void_of_course"]["is_void_of_course"]
                for probe in voc_evaluated
            )
        )
        voc_summary = {
            "representative_is_void_of_course": (
                representative_void_of_course["is_void_of_course"]
            ),
            "sampled_is_void_of_course": sampled,
            "status": _state(sampled),
        }
    return voc_summary


def _hour_local_time_label(request, offset_seconds: int) -> str:
    return civil_time_label(
        request.datetime.year,
        request.datetime.month,
        request.datetime.day,
        request.datetime.hour,
        offset_seconds // 60,
        offset_seconds % 60 * MICROSECONDS_PER_SECOND,
    )


def _probe_coverage(
    requested_offsets: list[int], usable_offsets: list[int],
    refinement_offsets: list[int], skipped: list[dict],
) -> dict:
    return {
        "requested_offsets_seconds": requested_offsets,
        "sampled_offsets_seconds": usable_offsets,
        "refinement_offsets_seconds": refinement_offsets,
        "skipped": skipped,
        "semantics": (
            "a sample that cannot be evaluated is skipped with its reason; "
            "states, sets and envelopes below cover only the sampled instants, "
            "the probes and the bisection midpoints"
        ),
    }


def _hour_printed_universe(representative: dict, request) -> tuple[dict, dict, bool]:
    """What the representative chart prints at each resampled path, its
    classifications, and whether a void-of-course receipt joins them."""

    representative_void_of_course = representative["void_of_course"]
    printed = _approximate_hour_printed_objects(representative, request)
    universe = _classifications_by_path(printed)
    # An unrequested module is an empty container, not a receipt.
    voc_usable = (
        isinstance(representative_void_of_course, dict)
        and bool(representative_void_of_course)
        and representative_void_of_course.get("applicable") is not False
    )
    if voc_usable:
        printed[VOID_OF_COURSE_PATH] = representative_void_of_course
        universe[VOID_OF_COURSE_PATH] = printed_classifications(
            representative_void_of_course, VOID_OF_COURSE_PATH
        )
    return printed, universe, voc_usable


@dataclass(frozen=True)
class RepresentativeChart:
    """The real chart computed at the representative instant of the interval.

    Each sensitivity builder reads the parts it reuses; the rest stay None.
    """

    bodies: list[dict]
    semantics: str
    houses: dict | None = None
    placements: dict = field(default_factory=dict)
    sect: dict | None = None
    lots: dict | None = None
    void_of_course: dict | None = None
    offset_seconds: int = 0
    nodes: list[dict] | None = None
    local_time: str = ""
    dodecatemoria: dict | None = None
    essential_dignities: dict | None = None


def build_approximate_hour_sensitivity(
    *,
    request,
    body_defs: list[dict],
    chart: RepresentativeChart,
) -> dict:
    """Build governed probes and reuse the selected real representative chart."""

    representative = {
        "input_local_time": _hour_local_time_label(request, chart.offset_seconds),
        "bodies": chart.bodies,
        "houses": chart.houses,
        "placements": chart.placements,
        "sect": chart.sect,
        "sect_is_day": (
            chart.essential_dignities["sect"]["is_day"]
            if isinstance(chart.essential_dignities, dict)
            and chart.essential_dignities.get("available")
            else None
        ),
        "lots": chart.lots,
        "dodecatemoria": chart.dodecatemoria,
        "void_of_course": chart.void_of_course,
        "void_of_course_evaluated": chart.void_of_course is not None,
    }
    # 半小時位移的時區（例如 Australia/Lord_Howe 2024-10-06）會讓民用小時部分不存在
    # （02:00–02:29 不存在，02:30–02:59 存在）；「生於 02 那個小時」仍與時區規則相容，
    # 所以只跳過取不到的取樣點並具名回報。整個小時都不存在時仍拒絕（見下方空分支）。
    requested_offsets = sorted(
        set(PROBE_OFFSETS_SECONDS) | set(_clock_change_edge_offsets(request))
    )
    probes_by_offset, skipped = _sample_hour_probes(
        request, body_defs, requested_offsets, representative, chart.offset_seconds
    )

    usable_offsets = [
        offset for offset in requested_offsets if offset in probes_by_offset
    ]
    if not usable_offsets:
        # 整個小時都不存在。維持既有行為：由呼叫端轉成 422。
        raise NonexistentLocalTimeError(
            "no instant in the stated civil hour exists in this time zone"
        )
    probes = [probes_by_offset[offset] for offset in usable_offsets]
    start = _hour_start(request)
    spans = civil_hour_spans(request.timezone, start)
    transitions, refinement, states = _refine_transitions(
        request=request,
        body_defs=body_defs,
        probes_by_offset=probes_by_offset,
        stretch_of={
            offset: _stretch_index(spans, _probe_utc(request, offset))
            for offset in probes_by_offset
        },
    )
    # Midpoint classifications join the sets, envelopes and states; a midpoint
    # that skipped the void-of-course search adds nothing to that flag.
    refinement_offsets = sorted(refinement)
    refinement_probes = [refinement[offset] for offset in refinement_offsets]
    evaluated = probes + refinement_probes
    voc_evaluated = [probe for probe in evaluated if probe["void_of_course_evaluated"]]
    representative_index = usable_offsets.index(chart.offset_seconds)

    # What the representative chart prints at each resampled path is the
    # universe; every listed sample is held against it.
    printed, universe, voc_usable = _hour_printed_universe(representative, request)
    # The bisection already read the state of every probe it compared (a lone
    # sample has no neighbour, so it is read here).
    def state_of(offset: int, probe: dict) -> dict[str, Any]:
        return states[offset] if offset in states else _classification_state(probe, request)

    sampled_states = [
        state_of(offset, probe) for offset, probe in zip(usable_offsets, probes, strict=True)
    ]
    refinement_states = [
        state_of(offset, probe)
        for offset, probe in zip(refinement_offsets, refinement_probes, strict=True)
    ]
    classification_coverage = _classification_coverage(
        printed, universe, sampled_states, refinement_states,
    )
    evaluation_limits = _evaluation_limits(
        chart.houses,
        skipped=_ascendant_classes_skipped(
            [
                (offset, _stretch_index(spans, _probe_utc(request, offset)), state)
                for offset, state in zip(
                    usable_offsets + refinement_offsets, sampled_states + refinement_states
                )
            ]
        ),
    )
    evaluation_limits += _sect_dependent_dignity_limit(
        chart.essential_dignities, probes + refinement_probes
    )
    _apply_evaluation_limits(classification_coverage, evaluation_limits)

    body_signs = _hour_body_signs(body_defs, evaluated, representative_index)
    planet_in_house = _hour_planet_in_house(body_defs, chart.placements, evaluated)
    angles, house_cusps = _hour_angle_envelopes(chart.houses, evaluated)
    sect_summary = _hour_sect_summary(classification_coverage, chart.sect, evaluated)
    lots_summary = _hour_lots_summary(classification_coverage, chart.lots, evaluated)
    voc_summary = _hour_voc_summary(voc_usable, chart.void_of_course, voc_evaluated)

    end = start + dtmod.timedelta(hours=1)
    return {
        "precision": "approximate_hour",
        "status": "computed",
        "classification_status": _coverage_status(classification_coverage),
        "method_source_ref": "birth_time_sensitivity/approximate_hour",
        "interval_start_local": start.isoformat(timespec="minutes"),
        "interval_end_exclusive_local": end.isoformat(timespec="minutes"),
        "representative_minute": chart.offset_seconds // 60,
        "representative_local_time": representative["input_local_time"],
        "representative_semantics": chart.semantics,
        "sampling_semantics": "discrete_probes_not_continuous_hour_proof",
        "probe_coverage": _probe_coverage(
            requested_offsets, usable_offsets, refinement_offsets, skipped
        ),
        "evaluation_limits": evaluation_limits,
        "probes": [_probe_receipt(request, probe) for probe in probes],
        # One record per probe_coverage.refinement_offsets_seconds entry, in
        # that order; the offset gives the wall-clock time (interval start plus
        # offset), so a record keeps only what the offset does not say.
        "refinement_probes": [
            {
                "fold": _probe_fold(request, offset),
                "void_of_course_evaluated": probe["void_of_course_evaluated"],
            }
            for offset, probe in zip(refinement_offsets, refinement_probes, strict=True)
        ],
        "transitions": transitions,
        "transition_refinement_policy": (
            "bounded_bisection_only_when_adjacent_probe_classifications_differ"
        ),
        "classification_coverage": classification_coverage,
        "angles": angles,
        "house_cusps": house_cusps,
        "body_signs": body_signs,
        "planet_in_house": planet_in_house,
        "sect": sect_summary,
        "lots": lots_summary,
        "void_of_course": voc_summary,
        "dodecatemoria_signs": _dodecatemoria_signs(
            chart.dodecatemoria,
            [probe.get("dodecatemoria") for probe in evaluated],
        ),
    }


def _date_only_local_instants(
    request,
    local_value: dtmod.datetime,
) -> list[_ResolvedLocalInstant]:
    """Resolve all real instants for one wall-clock value, including both folds."""

    return [
        _resolved_instant(request, utc_value)
        for utc_value in _existing_utc_instants(
            request.datetime, request.timezone, local_value
        )
    ]


def _date_only_sample_instants(
    request,
    civil_day: dict,
) -> tuple[
    list[_ResolvedLocalInstant],
    _ResolvedLocalInstant,
    _ResolvedLocalInstant,
    dict,
]:
    start = dtmod.datetime(
        request.datetime.year,
        request.datetime.month,
        request.datetime.day,
    )
    samples: list[_ResolvedLocalInstant] = []
    absent_hourly_labels = []
    for hour in range(24):
        label = start + dtmod.timedelta(hours=hour)
        found = _date_only_local_instants(request, label)
        if not found:
            absent_hourly_labels.append(label.isoformat(timespec="seconds"))
        samples.extend(found)
    samples.extend(
        _date_only_local_instants(
            request,
            start + dtmod.timedelta(hours=23, minutes=59, seconds=59),
        )
    )

    # The day is the time step's civil day (resolve_civil_day): every UTC
    # stretch the zone labels with this date.  Midnight jumps need not be whole
    # minutes, a date-line crossing can skip a date, and a clock set back after
    # midnight returns to this date, so the day's end may carry a later date's
    # label and the day need not be one stretch.
    day_start = _resolved_instant(request, civil_day["start_utc"])
    next_day_start = _resolved_instant(request, civil_day["end_exclusive_utc"])

    def on_this_date(moment: dtmod.datetime) -> bool:
        return any(left <= moment < right for left, right in civil_day["spans"])

    # An hourly grid assumes whole-hour clock changes (Lord Howe's 30-minute
    # repeat left 90 minutes unsampled).  Adding each stretch's first and last
    # second and both sides of every UTC-offset change on this date keeps
    # adjacent samples within a stretch at most an hour apart.
    for span_start, span_end in civil_day["spans"]:
        samples.append(_resolved_instant(request, span_start))
        samples.append(_resolved_instant(request, span_end - _ONE_SECOND))
    utc_offset_changes_seen = []
    if request.timezone.mode == "iana":
        for change in utc_offset_changes(
            ZoneInfo(request.timezone.iana_name),
            civil_day["start_utc"],
            civil_day["last_second_utc"],
        ):
            utc_offset_changes_seen.append(change.isoformat().replace("+00:00", "Z"))
            for moment in (change - _ONE_SECOND, change):
                if on_this_date(moment):
                    samples.append(_resolved_instant(request, moment))
    samples = sorted(
        {item["utc_time"]: item for item in samples}.values(),
        key=lambda item: item["utc_datetime"],
    )
    schedule = {
        "absent_hourly_labels": absent_hourly_labels,
        "utc_offset_changes": utc_offset_changes_seen,
    }
    return samples, day_start, next_day_start, schedule


def _date_only_sample_nodes(request, node_defs: list[dict], jd_ut: float, context, trace: Trace) -> list[dict]:
    """The nodes at one date sample, south nodes derived when requested."""

    _require_sample_coverage(node_defs, jd_ut, context)
    nodes = compute_bodies(
        node_defs, jd_ut, context, request.atmosphere, trace, physical=False, moon_relative=True,
    )
    _require_file_backed_samples(nodes, jd_ut)
    if request.options.include_south_nodes:
        append_south_nodes(nodes, jd_ut, context, request.atmosphere, trace)
    return nodes


def _date_only_position_ranges(
    sampled_objects: dict[str, dict], representative_bodies: list[dict], representative_nodes: list[dict]
) -> list[dict]:
    """Each object's sampled signs and longitude envelope, by key."""

    representative_map = {
        item["key"]: item
        for item in representative_bodies + representative_nodes
    }
    position_ranges = []
    for key, record in sampled_objects.items():
        values = [item["longitude"] for item in record["values"]]
        representative = representative_map.get(key)
        longitude = representative.get("longitude") if representative is not None else None
        position_ranges.append(_sampled_sign_row(
            key, record["name"], values or None,
            representative=("representative_longitude", lambda _found: longitude),
            envelope_key="sampled_longitude_envelope",
        ))
    position_ranges.sort(key=lambda item: item["key"])
    return position_ranges


def _moon_sign_transitions(moon_values: list[dict], sample_instants: list[_ResolvedLocalInstant], civil_day: dict) -> list[dict]:
    """The Moon's sign changes between adjacent date samples."""

    # A date can be more than one UTC stretch (a clock set back just after
    # midnight labels the next hour with the previous date).  The last second of
    # one stretch and the first of the next are adjacent samples, but the
    # crossing between them may lie in time the clock gave to another date.
    stretch_of = {
        sample["utc_time"]: next(
            index
            for index, (start, end) in enumerate(civil_day["spans"])
            if start <= sample["utc_datetime"] < end
        )
        for sample in sample_instants
    }
    moon_transitions = []
    for left, right in zip(moon_values, moon_values[1:]):
        left_sign = zodiac_sign_index(left["longitude"])
        right_sign = zodiac_sign_index(right["longitude"])
        if left_sign != right_sign:
            moon_transitions.append(
                {
                    "from_sign_index": left_sign,
                    "to_sign_index": right_sign,
                    "lower_sample_local": left["local_time"],
                    "upper_sample_local": right["local_time"],
                    "semantics": (
                        MOON_TRANSITION_WITHIN_ONE_STRETCH
                        if stretch_of[left["utc_time"]] == stretch_of[right["utc_time"]]
                        else MOON_TRANSITION_ACROSS_ANOTHER_DATE
                    ),
                }
            )
    return moon_transitions


def _record_sample_longitudes(sampled_objects: dict[str, dict], objects: list[dict], sample: _ResolvedLocalInstant) -> None:
    """Append one sample's longitudes to each object's row."""

    for item in objects:
        # An object with no longitude keeps its row instead of vanishing.
        record = sampled_objects.setdefault(
            item["key"],
            {"key": item["key"], "name": item["name"], "values": []},
        )
        longitude = item.get("longitude")
        if longitude is None:
            continue
        record["values"].append(
            {
                "longitude": longitude,
                "local_time": sample["local_time"],
                "fold": sample["fold"],
                "utc_time": sample["utc_time"],
            }
        )


def build_date_only_sensitivity(
    *,
    request,
    body_defs: list[dict],
    node_defs: list[dict],
    civil_day: dict,
    chart: RepresentativeChart,
) -> dict:
    """Return sampled daily longitude envelopes without inventing a birth time.

    The samples are evidence about the selected civil date at the listed
    instants, not a continuous extrema proof: every existing hourly clock label
    on both folds, the day's first and last second, and both sides of every
    UTC-offset change.  Hourly labels the zone never had are listed, not
    silently dropped.
    """

    representative_nodes = chart.nodes or []
    sample_instants, day_start, next_day_start, schedule = (
        _date_only_sample_instants(request, civil_day)
    )
    context = ComputationContext(request.computation_mode, request.location)
    sampled_objects: dict[str, dict] = {}
    sample_states: list[dict[str, Any]] = []
    sample_dodecatemoria: list[dict | None] = []
    representative_twelfth_parts: dict = chart.dodecatemoria or {}
    dodecatemoria_printed = _usable(representative_twelfth_parts)

    for sample in sample_instants:
        jd_ut = utc_datetime_to_jd_ut(sample["utc_datetime"])
        trace = Trace()
        effective_bodies, _moon_context = _compute_effective_bodies(
            request=request,
            body_defs=body_defs,
            jd_ut=jd_ut,
            context=context,
            trace=trace,
        )
        nodes = _date_only_sample_nodes(request, node_defs, jd_ut, context, trace)
        # The anchor prints no horizon position for a date; neither does a sample.
        for record in effective_bodies + nodes:
            withhold_horizontal_coordinates(record, DATE_ONLY_NO_BIRTH_TIME_REASON)
        sample_objects: dict[str, Any] = {
            "astronomical_data.bodies": effective_bodies,
            "astronomical_data.nodes": nodes,
        }
        if dodecatemoria_printed:
            # A date has no ascendant and no Lots: the planets only, as on the chart.
            dodecatemoria = _sample_dodecatemoria(
                request, effective_bodies, angles=None, lots=None, trace=trace
            )
            sample_dodecatemoria.append(dodecatemoria)
            if dodecatemoria is not None and _usable(dodecatemoria):
                # The chart labels its date-only result with the anchor it was
                # read at; that label describes the chart, not a value a
                # sample could change, so a sample carries the same one.
                sample_objects[DODECATEMORIA_PATH] = {
                    **dodecatemoria,
                    **{
                        key: representative_twelfth_parts[key]
                        for key in ("time_basis",)
                        if key in representative_twelfth_parts
                    },
                }
        sample_states.append(
            {
                leaf: value
                for leaves in _classifications_by_path(sample_objects).values()
                for leaf, value in leaves.items()
            }
        )
        _record_sample_longitudes(sampled_objects, effective_bodies + nodes, sample)

    printed: dict[str, Any] = {
        "astronomical_data.bodies": chart.bodies,
        "astronomical_data.nodes": representative_nodes,
    }
    if dodecatemoria_printed:
        printed[DODECATEMORIA_PATH] = representative_twelfth_parts
    # date_only has no bisection: its samples are the whole evidence.
    classification_coverage = _classification_coverage(
        printed, _classifications_by_path(printed), sample_states, []
    )
    position_ranges = _date_only_position_ranges(
        sampled_objects, chart.bodies, representative_nodes
    )

    moon_values = sampled_objects["moon"]["values"]
    moon_transitions = _moon_sign_transitions(moon_values, sample_instants, civil_day)
    minimum_boundary_distance = min(
        min(value["longitude"] % 30.0, 30.0 - value["longitude"] % 30.0)
        for value in moon_values
    )
    # The sum of the date's stretches, not end minus start: between the bounds
    # the clock may show another date.
    duration_hours = civil_day["duration_seconds"] / 3600.0
    # Local bounds render the same instants as the UTC bounds; deriving them from
    # the nominal date could state a local midnight the zone never had.
    return {
        "precision": "date_only",
        "status": "computed",
        "classification_status": _coverage_status(classification_coverage),
        "method_source_ref": "birth_time_sensitivity/date_only",
        "interval_start_local": day_start["local_time"],
        "interval_end_exclusive_local": next_day_start["local_time"],
        "interval_start_utc": day_start["utc_time"],
        "interval_end_exclusive_utc": next_day_start["utc_time"],
        "civil_day_duration_hours": duration_hours,
        # Local noon, or the first existing instant after it: the chart's own
        # anchor and label, passed in, so the two cannot disagree.
        "representative_local_time": _whole_second_label(chart.local_time),
        "representative_semantics": chart.semantics,
        "sampling_semantics": (
            "hourly_local_clock_samples_plus_day_end_not_continuous_extrema_proof"
        ),
        "sample_schedule": schedule,
        # No houses without a birth time, so no Ascendant to reverse.
        "evaluation_limits": [],
        "samples": [
            {
                "local_time": item["local_time"],
                "fold": item["fold"],
                "utc_time": item["utc_time"],
            }
            for item in sample_instants
        ],
        "classification_coverage": classification_coverage,
        "position_ranges": position_ranges,
        "dodecatemoria_signs": _dodecatemoria_signs(
            chart.dodecatemoria, sample_dodecatemoria
        ),
        # The Moon's signs and envelope are its position_ranges row; this adds
        # only what that row cannot say.
        "moon_boundary_assessment": {
            "minimum_sampled_distance_to_sign_boundary_degrees": (
                minimum_boundary_distance
            ),
            "sampled_sign_boundary_transitions": moon_transitions,
        },
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    f"birth_time_sensitivity/{precision}": {
        "applies_to": f"birth_time_sensitivity (precision {precision})",
        "method": method,
    }
    for precision, method in SENSITIVITY_METHOD.items()
}
