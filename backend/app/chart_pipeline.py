"""The chart pipeline: typed stages from a validated request to one response.

Each stage reads the typed results of the stages before it:

1. ``chart_time._resolve_time`` -> ``TimeResolution``: input and effective
   request, time conversion, computation context, frame table and the one trace;
2. ``chart_astronomy._astronomical_facts`` -> ``AstronomicalFacts``: positions,
   houses, fixed stars and event searches;
3. ``chart_methods._derived_chart`` -> ``DerivedChart``: derived geometry and
   methods;
4. ``_birth_time_sensitivity``: the sampling pass for a non-exact birth time;
5. ``_assemble_chart_response``: the one detailed response, with the
   calculation dossier as a projection of it (``core.dossier``).

The stage results are typed in ``chart_stages``.  Stages run in this order
and append to the trace in this order, so the Swiss call order is the order
written here.  Whether Swiss's state is per thread depends on how the library
was built (per thread in the shipped Linux image, shared on macOS), so the
caller (``main``) holds the compute line either way.  ``response_projection`` derives
every other view from the response.
"""

from dataclasses import dataclass
import importlib.metadata
from typing import Any

import swisseph as swe

from .core.invariants import InternalInvariantError
from .domain_catalog import FIXED_STARS
from .ephemeris import FullEphemerisRequiredError, input_files_unchanged_since
from .schema_chart import ChartRequest, OptionsInput
from .core.tz_database import TZ_DATABASE
from .core.bodies import geocentric_sun_true_altitude
from .core.formatting import attach_sign_positions
from .core.birth_time_sensitivity import (
    RepresentativeChart,
    build_approximate_hour_sensitivity,
    build_date_only_sensitivity,
)
from .core.fixed_stars import fixed_star_receipt
from .core.dossier import build_calculation_dossier
from .core.module_state import module_status_word
from .chart_stages import (
    AstronomicalFacts,
    DerivedChart,
    EventFacts,
    HouseFacts,
    JsonObject,
    _module_container,
    PositionFacts,
    TimeResolution,
)
from .chart_time import _event_search_refusal, _HAS_FULL_EPHEMERIS, _resolve_time
from .chart_astronomy import _astronomical_facts, _houses, _positions
from .chart_methods import _derived_chart, _sect_and_lots


SCHEMA_VERSION = "0.21.0"

# Python distribution and embedded Swiss C-library versions are distinct.
try:
    _PYSWISSEPH_DISTRIBUTION_VERSION: str | None = (
        importlib.metadata.version("pyswisseph")
    )
except importlib.metadata.PackageNotFoundError:
    _PYSWISSEPH_DISTRIBUTION_VERSION = None



def _library_info() -> JsonObject:
    return {
        "pyswisseph_distribution_version": _PYSWISSEPH_DISTRIBUTION_VERSION,
        "swiss_ephemeris_library_version": swe.version,
        # IANA database version is a calculation input and must be receipted.
        "tz_database": dict(TZ_DATABASE),
        # Explained in register entry library_info.
        "note_source_ref": "library_info",
    }


def _astronomical_data(facts: AstronomicalFacts) -> JsonObject:
    time, positions = facts.time, facts.positions
    req = time.request
    # Ownership follows the options as sent (input_request), which is
    # also what option_states reports; the effective request may drop houses
    # for a date-only birth while the house module states its refusal.
    options = time.input_request.options
    return {
        "time": time.time_conversion,
        "atmosphere": {
            "pressure_hpa": req.atmosphere.pressure_hpa,
            "pressure_mode": (
                "user_supplied" if req.atmosphere.pressure_hpa is not None
                else "swiss_estimate_from_altitude"
            ),
            "temperature_c": req.atmosphere.temperature_c,
            "refraction": "swiss_ephemeris_standard_model",
            "applies_to": "altitude_apparent",
        },
        "bodies": positions.bodies,
        "nodes": positions.nodes,
        "fixed_stars": _module_container(facts.fixed_stars, options.include_fixed_stars),
        "fixed_star_policy": fixed_star_receipt(
            FIXED_STARS,
            req.options.include_fixed_stars,
            facts.fixed_stars,
        ),
        "lunar_apsides": _module_container(
            positions.lunar_apsides, options.include_lilith_priapus
        ),
        "parallax_moon": positions.parallax_moon,
        # Owned by include_houses like the house modules.
        "angles": _module_container(facts.houses.angles, options.include_houses),
        "extra_angles": _module_container(
            facts.houses.extra_angles, options.include_extra_angles, options.include_anti_vertex
        ),
        "lunar_events": _module_container(
            facts.events.lunar_events, options.include_lunar_phases, options.include_eclipses
        ),
        "horizon_events": _module_container(
            facts.events.horizon_events, options.include_rise_set_transits
        ),
    }


def _derived_methods(facts: AstronomicalFacts, methods: DerivedChart) -> JsonObject:
    # Ownership follows the options as sent, as in _astronomical_data.
    options = facts.time.input_request.options
    return {
        "house_division": _module_container(facts.houses.house_division, options.include_houses),
        "planet_in_house": _module_container(facts.houses.planet_in_house, options.include_houses),
        "sect": _module_container(methods.sect, options.include_lots),
        "lots": _module_container(methods.lots, options.include_lots),
        "void_of_course": _module_container(
            methods.void_of_course, options.include_void_of_course
        ),
        "declination_aspects": _module_container(
            methods.declination_aspects, options.include_declination_aspects
        ),
        "aspects": _module_container(methods.aspects, options.include_aspects),
        "essential_dignities": methods.essential_dignities,
        # Basic output: written for every chart, with its own state.
        "planetary_hours": methods.planetary_hours,
        "dodecatemoria": _module_container(methods.dodecatemoria, options.include_dodecatemoria),
        "lunar_mansions": _module_container(
            methods.lunar_mansions, options.include_lunar_mansions
        ),
        "solar_phase": _module_container(methods.solar_phase, options.include_solar_phase),
        "motion_states": _module_container(methods.motion_states, options.include_motion_states),
        "classical_classifications": _module_container(
            methods.classical_classifications, options.include_classical_classifications
        ),
    }


def _birth_time_sensitivity(
    facts: AstronomicalFacts, methods: DerivedChart
) -> tuple[JsonObject, JsonObject]:
    """Stage 4: the sampling pass across a non-exact birth-time interval.

    Returns the result and the pass's own event-module state: the one the
    event stage wrote, or the refusal this pass hit.
    """

    time, positions = facts.time, facts.positions
    input_request = time.input_request
    state = facts.events.availability["birth_time_sensitivity"]
    try:
        if input_request.birth_time_precision == "approximate_hour":
            birth_time_sensitivity = build_approximate_hour_sensitivity(
                request=input_request,
                body_defs=positions.body_defs,
                chart=RepresentativeChart(
                    bodies=positions.bodies,
                    houses=facts.houses.houses,
                    placements=facts.houses.planet_in_house,
                    sect=methods.sect,
                    lots=methods.lots,
                    void_of_course=methods.void_of_course,
                    offset_seconds=time.representative_offset_seconds,
                    semantics=time.time_conversion["input_semantics"],
                    dodecatemoria=methods.dodecatemoria,
                    essential_dignities=methods.essential_dignities,
                ),
            )
        elif input_request.birth_time_precision == "date_only":
            if time.civil_day is None:  # resolved for every date_only chart
                raise InternalInvariantError("time.civil_day is not None")
            birth_time_sensitivity = build_date_only_sensitivity(
                request=input_request,
                body_defs=positions.body_defs,
                node_defs=positions.node_defs,
                civil_day=time.civil_day,
                chart=RepresentativeChart(
                    bodies=positions.bodies,
                    nodes=positions.nodes,
                    local_time=time.time_conversion["date_only_anchor"]["anchor_local_time"],
                    semantics=time.representative_policy,
                    dodecatemoria=methods.dodecatemoria,
                ),
            )
        else:
            birth_time_sensitivity = None
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("出生時間敏感度取樣", error, time.trace)
        return {
            "precision": input_request.birth_time_precision,
            "status": "not_applicable",
            "reason_code": refusal["reason_code"],
        }, refusal
    if birth_time_sensitivity is None:
        # The module state is the event-module receipt's word for it
        # (not_requested for an exact birth time), not a second word.
        birth_time_sensitivity = {
            "precision": "exact",
            "status": module_status_word(state),
        }
    return birth_time_sensitivity, state


def _withdraw_full_ephemeris_claims(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "used_full_ephemeris" and value is True:
                node[key] = False
            else:
                _withdraw_full_ephemeris_claims(value)
    elif isinstance(node, list):
        for item in node:
            _withdraw_full_ephemeris_claims(item)


# A fixed star's Swiss return flags and full-ephemeris claim are provenance:
# the dossier's provenance.fixed_stars carries them per star (decoded in
# retflag_names_by_value, cited by the fallback warning), so the star records
# do not repeat them once the dossier has read them.
_STAR_PROVENANCE_KEYS = (
    "retflag_ecliptic", "retflag_equatorial", "retflag_horizontal_source", "used_full_ephemeris",
)


def _leave_star_provenance_to_the_dossier(astronomical_data: JsonObject) -> None:
    for star in astronomical_data["fixed_stars"] or ():
        for key in _STAR_PROVENANCE_KEYS:
            del star[key]


def _assemble_chart_response(
    facts: AstronomicalFacts,
    methods: DerivedChart,
    *,
    build_identity: JsonObject,
) -> JsonObject:
    """Stage 5: the one detailed response; the dossier is a projection of it."""

    time = facts.time
    library_info = _library_info()
    astronomical_data = _astronomical_data(facts)
    derived_geometry = {
        "antiscia": _module_container(
            methods.antiscia, time.input_request.options.include_antiscia
        )
    }
    derived_methods = _derived_methods(facts, methods)
    birth_time_sensitivity, sensitivity_state = _birth_time_sensitivity(facts, methods)
    event_module_availability = {
        **facts.events.availability,
        "birth_time_sensitivity": sensitivity_state,
    }
    # One producer of the sign／DMS／decimal text the page prints.
    attach_sign_positions(
        astronomical_data=astronomical_data,
        derived_geometry=derived_geometry,
        derived_methods=derived_methods,
        birth_time_sensitivity=birth_time_sensitivity,
    )
    # Every Swiss call of the chart is behind this point.  If an input file
    # changed since the chart's manifest was read, which bytes Swiss read
    # cannot be attributed, so no object keeps the full-ephemeris claim.
    input_files_unchanged = input_files_unchanged_since(time.ephemeris_input_watch)
    if not input_files_unchanged:
        _withdraw_full_ephemeris_claims(astronomical_data)
    trace_steps = time.trace.as_list()
    calculation_dossier = build_calculation_dossier(
        time,
        astronomical_data=astronomical_data,
        derived_methods=derived_methods,
        derived_geometry=derived_geometry,
        birth_time_sensitivity=birth_time_sensitivity,
        library_info=library_info,
        full_ephemeris_files_available=_HAS_FULL_EPHEMERIS,
        input_files_unchanged_during_chart=input_files_unchanged,
        build_identity=build_identity,
        trace_steps=trace_steps,
        event_module_availability=event_module_availability,
        latitude_regime=facts.houses.latitude_regime,
    )
    _leave_star_provenance_to_the_dossier(astronomical_data)

    return {
        "schema_version": SCHEMA_VERSION,
        "output_contract": {
            "status": "provisional",
            "compatibility": "additive_during_0.x_unless_a_documented_correctness_fix_requires_change",
            "layers": {
                "astronomical_data": "直接天文計算與座標／時間轉換",
                "derived_geometry": "只需明示公式的幾何轉換",
                "derived_methods": _DERIVED_METHODS_LAYER_TEXT,
            },
        },
        # The options as sent; what they did is each module's state.
        "requested_options": time.input_request.options.model_dump(),
        "library_info": library_info,
        "computation_mode": time.request.computation_mode.model_dump(),
        "calculation_dossier": calculation_dossier,
        "astronomical_data": astronomical_data,
        "derived_geometry": derived_geometry,
        "derived_methods": derived_methods,
        "birth_time_sensitivity": birth_time_sensitivity,
        "calculation_trace": trace_steps,
    }


# 預設開啟的方法選項由 OptionsInput 的預設值產生，不手寫進契約文字。
_DEFAULT_ON_METHOD_OPTIONS = tuple(sorted(
    name
    for name, field in OptionsInput.model_fields.items()
    if name.startswith("include_") and field.default is True
))
_DERIVED_METHODS_LAYER_TEXT = (
    "需要占星方法或門檻選擇的結果；預設開啟："
    + "、".join(_DEFAULT_ON_METHOD_OPTIONS)
    + "；其餘需明示請求"
)


def compute_chart_response(
    req: ChartRequest, *, build_identity: JsonObject, instant_jd_ut: float | None = None,
) -> JsonObject:
    """Every stage in order, for one request; the caller holds the Swiss line.

    ``instant_jd_ut``: an exact instant the caller already holds as JD(UT) (the
    annual route's solar return), computed at that JD rather than at the
    request's civil datetime, which is then only its UTC+00:00 placeholder.
    """

    time = _resolve_time(req, instant_jd_ut=instant_jd_ut)
    facts = _astronomical_facts(time)
    methods = _derived_chart(facts)
    return _assemble_chart_response(facts, methods, build_identity=build_identity)


@dataclass(frozen=True)
class NatalAnchor:
    """Stages 1-2 and Sect／Lots of one request, for the annual route.

    The same stage functions as compute_chart_response, called in the same
    order, so every natal fact the annual techniques read (the birth instant,
    the Sun's longitude, the ascendant, Sect and the Fortune／Spirit pair) is
    the value /api/chart prints for the same request and options.  Event
    searches, fixed stars and the response assembly are not run.
    """

    time: TimeResolution
    positions: PositionFacts
    houses: HouseFacts
    sect: JsonObject | None
    lots: JsonObject


def compute_natal_anchor(req: ChartRequest) -> NatalAnchor:
    """The caller holds the Swiss line, as for compute_chart_response."""

    time = _resolve_time(req)
    positions = _positions(time)
    houses = _houses(time, positions.bodies)
    facts = AstronomicalFacts(
        time=time,
        positions=positions,
        houses=houses,
        fixed_stars=[],
        events=EventFacts(lunar_events={}, horizon_events={}, availability={}),
    )
    sect_sun_altitude = geocentric_sun_true_altitude(
        time.jd_ut, time.context, time.request.atmosphere
    )
    sect, lots = _sect_and_lots(facts, sect_sun_altitude)
    return NatalAnchor(time=time, positions=positions, houses=houses, sect=sect, lots=lots)
