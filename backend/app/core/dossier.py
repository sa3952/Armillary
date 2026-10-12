"""Backend-authored receipt for validated inputs, policy and provenance."""

from __future__ import annotations

import hashlib

import swisseph as swe

from ..config import OUTER_BODIES, PRODUCT_YEAR_RANGE
from ..ephemeris import input_file_inventory
from ..method_sources import method_source_register_receipt
from ..frontend_release import (
    CANONICAL_JSON_ENSURE_ASCII,
    CANONICAL_JSON_SEPARATORS,
    CANONICAL_JSON_SORT_KEYS,
    canonical_json_bytes,
)
from ..privacy_receipt import privacy_attestation
from . import essential_dignities
from .birth_time_sensitivity import coverage_ledger as _sensitivity_coverage_ledger
from .contested_methods import contested_method_marks
from .frame_compatibility import frame_policy_receipt
from .dossier_warnings import structured_warnings
from .module_state import (
    EVENT_SEARCH_REASON_CODES,
    MODULE_STATUSES,
    module_state,
    module_status_word,
    not_requested_state,
    state_of as _state_of,
)


DOSSIER_VERSION = "0.9.0"

# The six-field vocabulary (MODULE_STATUSES, EVENT_SEARCH_REASON_CODES
# and the builders) lives in module_state; the Dossier copies what each
# producer wrote.  Both names are re-exported here for the response's readers.
__all__ = [
    "DOSSIER_VERSION",
    "EVENT_SEARCH_REASON_CODES",
    "MODULE_STATUSES",
    "build_calculation_dossier",
]
_OUTER_PLANET_KEYS = frozenset(body["key"] for body in OUTER_BODIES)
_SOUTH_NODE_KEYS = frozenset({"true_south_node", "mean_south_node"})

_EPHEMERIS_DATASET_LINEAGE = {
    "status": "declared_from_bundled_file_headers",
    "representation": "Swiss Ephemeris compressed files",
    "jpl_ephemeris_basis": "DE441",
    "applies_to": ["sepl_18.se1", "semo_18.se1"],
    "evidence": "bundled_file_header_checked_at_development_time",
    "runtime_limit": (
        "returned retflags identify the Swiss/Moshier source family, "
        "not the exact opened file or JPL kernel lineage"
    ),
}

_FLAG_NAMES = (
    ("FLG_JPLEPH", swe.FLG_JPLEPH),
    ("FLG_SWIEPH", swe.FLG_SWIEPH),
    ("FLG_MOSEPH", swe.FLG_MOSEPH),
    ("FLG_HELCTR", swe.FLG_HELCTR),
    ("FLG_TRUEPOS", swe.FLG_TRUEPOS),
    ("FLG_J2000", swe.FLG_J2000),
    ("FLG_NONUT", swe.FLG_NONUT),
    ("FLG_SPEED", swe.FLG_SPEED),
    ("FLG_EQUATORIAL", swe.FLG_EQUATORIAL),
    ("FLG_XYZ", swe.FLG_XYZ),
    ("FLG_RADIANS", swe.FLG_RADIANS),
    ("FLG_BARYCTR", swe.FLG_BARYCTR),
    ("FLG_TOPOCTR", swe.FLG_TOPOCTR),
    ("FLG_SIDEREAL", swe.FLG_SIDEREAL),
)


def _retflag_names(value: int) -> list[str]:
    return [name for name, bit in _FLAG_NAMES if value & bit]


def _retflag_receipt(value: int | None) -> dict:
    if value is None:
        return {"value": None, "names": []}
    return {"value": value, "names": _retflag_names(value)}


def _object_provenance(item: dict) -> dict:
    if item.get("error"):
        result_status = "failed"
    elif item.get("longitude") is None:
        result_status = "not_applicable"
    else:
        result_status = "available"

    # Response size is binding: the name is on the record this describes,
    # and a flag value decodes the same way every time, so the decode is written
    # once per value in provenance.retflag_names_by_value.
    return {
        "key": item["key"],
        "result_status": result_status,
        "calculation_source": item.get("calculation_source"),
        "derived_from": item.get("derived_from"),
        "used_full_ephemeris": item.get("used_full_ephemeris"),
        "retflags": {
            "ecliptic": item.get("retflag_ecliptic"),
            "equatorial": item.get("retflag_equatorial"),
            "horizontal_source": item.get("retflag_horizontal_source"),
        },
    }


def _member_group_state(requested: bool, records: list[dict]) -> dict:
    """State of an option whose result is a set of emitted records.

    Outer planets, Chiron and the derived south nodes have no container; the
    records are the producer's output.  A record gated before any Swiss call
    carries a coverage_state other than covered (not executed); a record without
    a longitude carries the producer's availability_reason_code.
    """

    if not requested:
        return not_requested_state()
    reasons = [
        record.get("availability_reason_code")
        for record in records
        if record.get("longitude") is None
    ]
    usable = bool(records) and not reasons
    return module_state(
        requested=True,
        executed=bool(records) and all(
            record.get("coverage_state", "covered") == "covered"
            for record in records
        ),
        applicable=usable,
        available=usable,
        reason_code=reasons[0] if reasons else None,
    )


def _frame_label(label: str, *module_states: dict) -> str:
    """Name a module's fixed frame only when the module produced a result."""

    if any(state["available"] for state in module_states):
        return label
    if not any(state["requested"] for state in module_states):
        return MODULE_STATUSES[0]
    return MODULE_STATUSES[2]


_MODULE_ORDER = (
    "house_division", "planet_in_house", "aspects", "fixed_stars",
    "outer_planets", "chiron", "south_nodes", "anti_vertex", "lunar_apsides",
    "parallax_moon", "essential_dignities", "antiscia", "sect", "lots",
    "void_of_course", "declination_aspects", "lunar_phases", "eclipses",
    "rise_set_transits", "planetary_hours", "dodecatemoria", "lunar_mansions",
    "solar_phase",
    "prenatal_syzygy",
    "classical_classifications",
)
# The derived_methods containers that carry a module state and a method
# receipt, in the order the states and the methodology receipt list them.
_DERIVED_METHOD_MODULES = (
    "house_division", "planet_in_house", "aspects", "sect", "lots",
    "void_of_course", "declination_aspects", "essential_dignities",
    "planetary_hours", "dodecatemoria", "lunar_mansions", "solar_phase",
    "classical_classifications",
)
# The classical bodies are always computed, or the request fails outright.
_CORE_POSITIONS_STATE = module_state(
    requested=True, executed=True, applicable=True, available=True,
)
# A request validation constraint runs nothing and yields no result.
_VALIDATION_CONSTRAINT_STATE = module_state(
    requested=True, executed=False, applicable=True, available=False,
    reason_code="request_validation_constraint_only",
)
_PARENT_NOT_REQUESTED_STATE = not_requested_state(
    "parent_module_not_requested_or_not_applicable"
)


def _module_states(
    options,
    astronomical_data: dict,
    derived_methods: dict,
    derived_geometry: dict,
    event_module_availability: dict,
) -> dict:
    """Every optional module's state, read from where its producer wrote it."""

    bodies = astronomical_data["bodies"]
    extra_angles = astronomical_data.get("extra_angles") or {}
    states = {
        name: _state_of(derived_methods.get(name))
        for name in _DERIVED_METHOD_MODULES
    }
    states.update({
        "antiscia": _state_of(derived_geometry.get("antiscia")),
        "fixed_stars": _state_of(astronomical_data.get("fixed_star_policy")),
        "lunar_apsides": _state_of(astronomical_data.get("lunar_apsides")),
        "parallax_moon": _state_of(astronomical_data.get("parallax_moon")),
        # One container serves both angle options; an option owns it only when
        # it asked for members of it.
        "extra_angles": (
            _state_of(extra_angles)
            if options.include_extra_angles
            else not_requested_state()
        ),
        "anti_vertex": (
            _state_of(extra_angles)
            if "anti_vertex" in (extra_angles.get("angles") or {})
            else not_requested_state()
        ),
        "outer_planets": _member_group_state(
            options.include_outer_planets,
            [body for body in bodies if body["key"] in _OUTER_PLANET_KEYS],
        ),
        "chiron": _member_group_state(
            options.include_chiron,
            [body for body in bodies if body["key"] == "chiron"],
        ),
        "south_nodes": _member_group_state(
            options.include_south_nodes,
            [
                node for node in astronomical_data["nodes"]
                if node["key"] in _SOUTH_NODE_KEYS
            ],
        ),
    })
    for name in ("lunar_phases", "eclipses", "rise_set_transits", "prenatal_syzygy"):
        states[name] = _state_of(event_module_availability.get(name))
    return states


def _methodology_receipt(derived_methods: dict, modules: dict) -> dict:
    items = {}
    for name in _DERIVED_METHOD_MODULES:
        value = derived_methods[name]
        execution_status = modules[name]
        has_method_receipt = isinstance(value, dict) and bool(value)
        items[name] = {
            "execution_status": execution_status,
            "method_status": (
                value.get("method_status") if has_method_receipt else None
            ),
            "response_path": f"derived_methods.{name}",
        }
    # `items` feeds the warnings below and is not emitted.
    return {
        "items": items,
        # The whitelisted public mark for
        # methods whose named pre-modern sources disagree; one producer.
        "classical_source_disagreements": contested_method_marks(
            derived_methods, modules
        ),
    }


def _option_state_receipts(request, states: dict, response_parts: dict) -> dict:
    """Closed execution receipts for the exact OptionsInput set.

    Each receipt copies requested/executed/applicable/available/reason_code from
    the state its module's producer recorded.  ``source`` is the response path
    of a usable result and null without one.
    """

    options = request.options
    explicit = set(options.model_fields_set)
    receipts: dict[str, dict] = {}

    def add(
        name: str,
        *,
        requested: bool,
        state: dict,
        path: str,
        source_path: str | None = None,
        not_requested_reason: str = "option_not_requested",
        also_writes: tuple[str, ...] = (),
    ) -> None:
        requested = bool(requested)
        # state_of reads a missing or empty owner as not requested, which is
        # only true when nobody asked: a requested option whose module recorded
        # no request is a producer defect, not a quiet "did not run".
        if requested and not state["requested"] and state is not _PARENT_NOT_REQUESTED_STATE:
            raise ValueError(f"option {name} was requested but its module recorded no request")
        available = requested and bool(state["available"])
        receipts[name] = {
            "input_presence": "explicit" if name in explicit else "defaulted",
            "requested_value": getattr(options, name),
            **module_state(
                requested=requested,
                executed=requested and bool(state["executed"]),
                applicable=requested and bool(state["applicable"]),
                available=available,
                source=(source_path or path) if available else None,
                reason_code=(
                    state["reason_code"] if requested else not_requested_reason
                ),
            ),
            "response_paths": [path, *also_writes],
        }

    def recorded_state(module: str, path: str) -> dict:
        """The sub-receipt at path when its producer records state there."""

        value: object = response_parts
        for part in path.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if isinstance(value, dict) and "executed" in value:
            return _state_of(value)
        return states[module]

    toggles = {
        "include_houses": ("house_division", "derived_methods.house_division"),
        "include_fixed_stars": ("fixed_stars", "astronomical_data.fixed_stars"),
        "include_lots": ("lots", "derived_methods.lots"),
        "include_antiscia": ("antiscia", "derived_geometry.antiscia"),
        "include_void_of_course": ("void_of_course", "derived_methods.void_of_course"),
        "include_declination_aspects": ("declination_aspects", "derived_methods.declination_aspects"),
        "include_outer_planets": ("outer_planets", "astronomical_data.bodies"),
        "include_chiron": ("chiron", "astronomical_data.bodies"),
        "include_lilith_priapus": ("lunar_apsides", "astronomical_data.lunar_apsides"),
        "include_south_nodes": ("south_nodes", "astronomical_data.nodes"),
        "include_lunar_phases": ("lunar_phases", "astronomical_data.lunar_events"),
        "include_eclipses": ("eclipses", "astronomical_data.lunar_events.eclipses"),
        "include_rise_set_transits": ("rise_set_transits", "astronomical_data.horizon_events"),
        "include_aspects": ("aspects", "derived_methods.aspects"),
        "include_anti_vertex": ("anti_vertex", "astronomical_data.extra_angles.angles.anti_vertex"),
        "include_extra_angles": ("extra_angles", "astronomical_data.extra_angles"),
        "include_dodecatemoria": ("dodecatemoria", "derived_methods.dodecatemoria"),
        "include_lunar_mansions": ("lunar_mansions", "derived_methods.lunar_mansions"),
        "include_solar_phase": ("solar_phase", "derived_methods.solar_phase"),
        "include_classical_classifications": (
            "classical_classifications", "derived_methods.classical_classifications",
        ),
    }
    # Every module container an option writes is named here, so a
    # consumer can resolve each null container to the option that owns it.
    also_written = {
        "include_houses": ("derived_methods.planet_in_house", "astronomical_data.angles"),
        "include_lots": ("derived_methods.sect",),
    }
    for option_name, (module, path) in toggles.items():
        add(
            option_name,
            requested=getattr(options, option_name),
            state=states[module],
            path=path,
            also_writes=also_written.get(option_name, ()),
        )

    add(
        "include_domicile_exaltation",
        requested=options.include_domicile_exaltation,
        state=states["essential_dignities"],
        path="derived_methods.essential_dignities",
        source_path="derived_methods.essential_dignities.profile_results",
    )

    moon_is_global = options.moon_position_profile == "global_computation_mode"
    add(
        "moon_position_profile",
        requested=True,
        state=_CORE_POSITIONS_STATE if moon_is_global else states["parallax_moon"],
        path=(
            "astronomical_data.bodies"
            if moon_is_global
            else "astronomical_data.parallax_moon"
        ),
    )

    orb_path = "derived_methods.aspects.degree_based.orb_receipt"
    degree_path = "derived_methods.aspects.degree_based"
    angle_path = "derived_methods.aspects.degree_based.angle_participation"
    profile_path = "derived_methods.essential_dignities.profile_results"
    configurations = {
        "house_system": (options.include_houses, "house_division", "derived_methods.house_division"),
        "declination_aspect_orb_degrees": (options.include_declination_aspects, "declination_aspects", "derived_methods.declination_aspects"),
        "aspect_orb_profile": (options.aspect_orb_profile is not None and options.include_aspects, "aspects", orb_path),
        "aspect_set_profile": (options.include_aspects, "aspects", degree_path),
        "aspect_orb_scale_percent": (options.aspect_orb_scale_percent is not None and options.include_aspects, "aspects", orb_path),
        "aspect_fixed_orb_degrees": (options.aspect_fixed_orb_degrees is not None and options.include_aspects, "aspects", orb_path),
        "partile_profile": (options.include_aspects, "aspects", degree_path),
        "aspect_angle_orb_degrees": (options.aspect_angle_orb_degrees is not None and options.include_aspects and options.aspect_include_angles, "aspects", angle_path),
        "bounds_profile": (options.bounds_profile is not None, "essential_dignities", profile_path),
        "decan_profile": (options.decan_profile is not None, "essential_dignities", profile_path),
        "triplicity_profile": (options.triplicity_profile is not None, "essential_dignities", profile_path),
        "dodecatemoria_profile": (options.include_dodecatemoria, "dodecatemoria", "derived_methods.dodecatemoria"),
        "solar_phase_profile": (options.include_solar_phase, "solar_phase", "derived_methods.solar_phase"),
    }
    for name, (selected, module, path) in configurations.items():
        add(
            name,
            requested=selected,
            state=recorded_state(module, path),
            path=path,
            not_requested_reason="configuration_not_selected",
        )
    add(
        "body_selection_preset",
        requested=options.body_selection_preset != "custom",
        state=_VALIDATION_CONSTRAINT_STATE,
        path="calculation_dossier.calculation_policy.body_selection",
        not_requested_reason="configuration_not_selected",
    )

    dependents = {
        "antiscia_include_nodes": ("antiscia", "derived_geometry.antiscia.scope"),
        "include_aspect_perfection": ("aspects", "derived_methods.aspects.perfection"),
        "aspect_include_angles": ("aspects", angle_path),
        "triplicity_include_research_comparison": ("essential_dignities", profile_path),
        "solar_phase_disc_cazimi": ("solar_phase", "derived_methods.solar_phase.disc_cazimi"),
    }
    for name, (parent, path) in dependents.items():
        add(
            name,
            requested=getattr(options, name),
            state=(
                recorded_state(parent, path)
                if states[parent]["requested"]
                else _PARENT_NOT_REQUESTED_STATE
            ),
            path=path,
        )

    # 容許度表從哪裡來由 derived_methods.aspects.degree_based.orb_receipt
    # 的 profile_selection 承載（單一產生器）；option_states 維持共同欄位形狀，不重抄。
    receipts["aspect_include_nodes"] = _aspect_include_nodes_receipt(
        options, explicit, states, response_parts
    )
    return receipts


def _aspect_include_nodes_receipt(
    options, explicit: set, states: dict, response_parts: dict
) -> dict:
    # aspect_include_nodes 有兩個消費者（黃道相位、赤緯相位），兩者經
    # bodies.effective_participants 共用同一條交點規則。executed 只在任一消費者
    # 實際納入交點時為真；每個消費者是否納入交點由其自身輸出承載。
    node_consumer_paths = {
        "derived_methods.aspects": "derived_methods.aspects.participants",
        "derived_methods.declination_aspects": (
            "derived_methods.declination_aspects.participant_keys"
        ),
    }
    derived_methods = response_parts["derived_methods"]
    aspect_node_keys = [
        item["key"]
        for item in (derived_methods.get("aspects") or {}).get("participants") or []
        if item.get("category") == "lunar_node"
    ]
    declination_policy = (
        (derived_methods.get("declination_aspects") or {}).get("participant_policy")
        or {}
    )
    node_consumers = {
        "derived_methods.aspects": (states["aspects"], aspect_node_keys),
        "derived_methods.declination_aspects": (
            states["declination_aspects"],
            list(declination_policy.get("node_keys_participating") or []),
        ),
    }
    node_requested = bool(options.aspect_include_nodes)
    consumer_states = {
        consumer: (
            "not_requested" if not state["requested"]
            else "option_not_requested" if not node_requested
            else "executed" if node_keys
            else "node_coordinates_unavailable"
        )
        for consumer, (state, node_keys) in node_consumers.items()
    }
    requested_consumers = [
        consumer
        for consumer, (state, _keys) in node_consumers.items()
        if state["requested"]
    ]
    # The option is applicable only where a consumer that actually runs could
    # take the nodes in; a requested consumer the frame table refused cannot.
    applicable_consumers = [
        consumer
        for consumer, (state, _keys) in node_consumers.items()
        if state["requested"] and state["applicable"]
    ]
    refusal_reason = next(
        (
            state["reason_code"]
            for state, _keys in node_consumers.values()
            if state["requested"] and not state["applicable"]
        ),
        None,
    )
    node_record_reason = next(
        (
            node.get("availability_reason_code")
            for node in response_parts["astronomical_data"]["nodes"]
            if node.get("longitude") is None
        ),
        None,
    )
    # No usable consumer: the refusal's own reason.  A usable consumer that
    # still took no node in: the node records' own reason.
    unavailable_reason = (
        node_record_reason or refusal_reason
        if applicable_consumers
        else refusal_reason or node_record_reason
    )
    node_executed = "executed" in consumer_states.values()
    return {
        "input_presence": (
            "explicit" if "aspect_include_nodes" in explicit else "defaulted"
        ),
        "requested_value": options.aspect_include_nodes,
        "requested": node_requested,
        "executed": node_executed,
        "applicable": node_requested and bool(applicable_consumers),
        "available": node_executed,
        "source": next(
            (
                node_consumer_paths[consumer]
                for consumer, state in consumer_states.items()
                if state == "executed"
            ),
            None,
        ),
        "reason_code": (
            "option_not_requested" if not node_requested
            else "parent_module_not_requested_or_not_applicable"
            if not requested_consumers
            else None if node_executed
            else unavailable_reason or "node_coordinates_unavailable"
        ),
        # 只列實際被請求的消費者路徑；available 時每一條都必須解析得到。
        "response_paths": [
            node_consumer_paths[consumer] for consumer in requested_consumers
        ] or list(node_consumer_paths.values()),
    }


def _trace_receipt(trace_steps: list[dict]) -> dict:
    serialized = canonical_json_bytes(trace_steps)
    return {
        "response_path": "calculation_trace",
        "step_count": len(trace_steps),
        "python_json_serialization_sha256": hashlib.sha256(
            serialized
        ).hexdigest(),
        "serialization_recipe": {
            "implementation": "Python json.dumps",
            "ensure_ascii": CANONICAL_JSON_ENSURE_ASCII,
            "sort_keys": CANONICAL_JSON_SORT_KEYS,
            "separators": list(CANONICAL_JSON_SEPARATORS),
            "encoding": "UTF-8",
            "float_serialization": "Python runtime json encoder",
            "portable_across_languages": False,
        },
    }


def _available_files_receipt(options) -> list[dict]:
    # The bundled input set as hashed when this chart started; listing a file
    # does not claim Swiss opened it.
    available_files = []
    for entry in input_file_inventory():
        entry["required_for_this_request"] = (
            entry["filename"] in {"sepl_18.se1", "semo_18.se1"}
            or (
                entry["filename"] == "seas_18.se1"
                and options.include_chiron
            )
            or (
                entry["filename"] == "sefstars.txt"
                and options.include_fixed_stars
            )
        )
        available_files.append(entry)
    return available_files


def _body_selection_receipt(options) -> dict:
    # The preset is a request constraint; each body
    # group's state is on its records and option receipt, not restated here.
    return {
        "source": "product_preset",
        "classical_body_keys": [
            "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"
        ],
        "excluded_optional_body_groups": (
            ["outer_planets", "chiron", "fixed_stars"]
            if options.body_selection_preset == "classical_seven_v1"
            else []
        ),
        "unaffected_point_groups": [
            "lunar_nodes", "lots", "extra_angles"
        ],
    }


def _aspect_configuration(options, derived_methods: dict) -> dict:
    orb_receipt = (
        ((derived_methods.get("aspects") or {}).get("degree_based") or {})
        .get("orb_receipt")
        or {}
    )
    # The aspect state is derived_methods.aspects' own (angles: its
    # angle_participation); this block keeps only the effective configuration.
    return {
        "aspect_set_profile": options.aspect_set_profile,
        "orb_configuration_mode": orb_receipt.get("configuration_mode", "none"),
        "fixed_pair_threshold_degrees": options.aspect_fixed_orb_degrees,
        "profile_scale_percent": options.aspect_orb_scale_percent,
        "angle_pair_orb_degrees": options.aspect_angle_orb_degrees,
        "declination_orb_degrees": options.declination_aspect_orb_degrees,
    }


def _birth_time_section(
    request,
    time_conversion: dict,
    representative_policy: str,
    sensitivity_coverage: dict | None,
) -> dict:
    return {
        "precision": request.birth_time_precision,
        "input_birth_date": (
            f"{request.datetime.year:04d}-{request.datetime.month:02d}-"
            f"{request.datetime.day:02d}"
        ),
        "input_civil_hour": (
            None
            if request.birth_time_precision == "date_only"
            else (
                f"{request.datetime.year:04d}-{request.datetime.month:02d}-"
                f"{request.datetime.day:02d} {request.datetime.hour:02d}"
            )
        ),
        "birth_time_known": request.birth_time_precision != "date_only",
        "representative_local_time": time_conversion["input_local_time"],
        # The anchor the time step actually chose, as that step labelled it
        # (time_utils.representative_policy), not one inferred from the precision.
        "representative_policy": representative_policy,
        "representative_is_birth_time": (
            request.birth_time_precision == "exact"
        ),
        "sensitivity_coverage": sensitivity_coverage,
    }


def _location_section(request) -> dict:
    return {
        "place_label": request.location.place_label,
        "location_source": request.location.location_source,
        "source_record_id": request.location.source_record_id,
        "location_precision": request.location.location_precision,
        "verification_status": (
            "client_asserted_not_server_verified"
            if request.location.location_source != "manual"
            else "user_supplied"
        ),
    }


def _time_conversion_section(request, time_conversion: dict) -> dict:
    return {
        "calendar": {
            "system": "gregorian",
            "swiss_flag": "GREG_CAL",
            "supported_year_range": list(PRODUCT_YEAR_RANGE),
        },
        "conversion_function": "swe.utc_to_jd",
        "input_local_time": time_conversion["input_local_time"],
        "input_semantics": time_conversion["input_semantics"],
        "timezone_mode": request.timezone.mode,
        "timezone_label": time_conversion["timezone_label"],
        "fold": request.timezone.fold,
        "resolved_utc_offset_hours": time_conversion["utc_offset_hours"],
        "offset_status": dict(time_conversion["offset_status"]),
        "utc_iso_8601": time_conversion["utc_time"].replace(" ", "T") + "Z",
        "jd_ut1": time_conversion["jd_ut"],
        "jd_tt": time_conversion["jd_et"],
        "delta_t_seconds": time_conversion["delta_t_seconds"],
        "delta_t_model": time_conversion["delta_t_model"],
        "swiss_time_input_semantics": time_conversion[
            "swiss_time_input_semantics"
        ],
        "leap_second_input": time_conversion["leap_second_input"],
        "time_scale_era": time_conversion["time_scale_era"],
        "sidereal_time_model": time_conversion["sidereal_time_model"],
        "date_only_anchor": time_conversion.get("date_only_anchor"),
        "civil_day": time_conversion.get("civil_day"),
        "ecl_nut_retflag": _retflag_receipt(
            time_conversion["ecl_nut_retflag"]
        ),
        "ayanamsa_degrees": time_conversion["ayanamsa"],
        "dst_warning": time_conversion["dst_warning"],
    }


def _flag_policy(context) -> dict:
    return {
        "base_position_flags": _retflag_receipt(context.base_flags),
        "equatorial_source_flags": _retflag_receipt(
            context.equatorial_source_flags | swe.FLG_EQUATORIAL
        ),
        "horizontal_source_flags": (
            _retflag_receipt(context.horizontal_source_flags)
            if context.horizon_meaningful
            else None
        ),
        "semantics": (
            "policy flags requested by the App; actual calculation "
            "sources are proven by returned retflags in provenance"
        ),
    }


def _moon_position_policy(request) -> dict:
    return {
        "requested_profile": request.options.moon_position_profile,
        "global_center": request.computation_mode.center,
        "effective_moon_source": (
            "topocentric_observer"
            if request.options.moon_position_profile
            == "moon_only_topocentric_v1"
            else request.computation_mode.center
        ),
        "geocentric_reference_retained": (
            request.options.moon_position_profile
            == "moon_only_topocentric_v1"
        ),
        "source": "astronomical_data.parallax_moon",
    }


def _essential_dignity_profiles(request) -> dict:
    return {
        "domicile_exaltation": (
            essential_dignities.DOMICILE_EXALTATION_PROFILE_ID
            if request.options.include_domicile_exaltation
            else None
        ),
        "bounds": request.options.bounds_profile,
        "face_decan": request.options.decan_profile,
        "triplicity": request.options.triplicity_profile,
        "triplicity_research_comparison": (
            request.options.triplicity_include_research_comparison
        ),
        "source": (
            "derived_methods.essential_dignities.profile_results"
        ),
    }


def _coordinate_conventions() -> dict:
    return {
        "angles": "degrees",
        "right_ascension_numeric": "degrees",
        "sidereal_time": "hours",
        "geographic_latitude": "north_positive",
        "geographic_longitude": "east_positive",
        "azimuth": "north_0_degrees_clockwise_east",
        "altitudes": {
            "true": "without_refraction",
            "apparent": "with_swiss_standard_refraction",
            # The horizon is the
            # observer's; altitudes carry diurnal parallax like the
            # rise/set module, whatever the display center of the
            # longitudes.  One horizon premise per response.
            "origin": "topocentric_observer_diurnal_parallax_applied",
            "same_premise_as": "astronomical_data.horizon_events",
        },
        "not_applicable_value": None,
    }


def _fixed_module_frames(context, states: dict) -> dict:
    return {
        "horizontal_coordinates": (
            "physical_tropical_of_date"
            if context.horizon_meaningful
            else "not_applicable_for_display_center"
        ),
        # A frame is named only for a module with a result.
        "houses_and_angles": _frame_label(
            "earth_observer_frame", states["house_division"]
        ),
        "lunar_events": _frame_label(
            "geocentric_apparent_tropical_of_date",
            states["lunar_phases"],
            states["eclipses"],
            states["prenatal_syzygy"],
        ),
        # 升降事件模組使用自己的固定框架，不跟隨 computation_mode，
        # 且真位置模式的視高度抑制不及於它——折射是升降事件的定義，
        # 不是附加修正。詳見 core/horizon_events.py。
        "rise_set_transits": _frame_label(
            "topocentric_observer_apparent_always_ignores_computation_mode",
            states["rise_set_transits"],
        ),
    }


def _calculation_policy_section(
    *,
    request,
    effective_request,
    context,
    modules: dict,
    option_states: dict,
    frame_states: dict,
    states: dict,
    derived_methods: dict,
    atmosphere: dict,
    latitude_regime: dict | None,
) -> dict:
    return {
        "computation_mode": request.computation_mode.model_dump(mode="json"),
        # The options as sent are input_receipt.options; the
        # second copy under another name is gone.
        "effective_datetime": effective_request.datetime.model_dump(
            mode="json"
        ),
        "flag_policy": _flag_policy(context),
        "modules": modules,
        "option_states": option_states,
        "method_frame_compatibility": frame_policy_receipt(
            request.computation_mode, frame_states
        ),
        "body_selection": _body_selection_receipt(request.options),
        "moon_position": _moon_position_policy(request),
        "essential_dignity_profiles": _essential_dignity_profiles(request),
        "aspect_configuration": _aspect_configuration(
            request.options, derived_methods
        ),
        # The house state is derived_methods.house_division's own.
        "house_system": {
            "requested_code": request.options.house_system,
            "method_layer": True,
            "latitude_regime": latitude_regime,
        },
        "atmosphere": atmosphere,
        "coordinate_conventions": _coordinate_conventions(),
        "fixed_module_frames": _fixed_module_frames(context, states),
    }


def _engine_section(library_info: dict, options) -> dict:
    return {
        "pyswisseph_distribution_version": library_info[
            "pyswisseph_distribution_version"
        ],
        "swiss_ephemeris_library_version": library_info[
            "swiss_ephemeris_library_version"
        ],
        # 時區資料庫版本屬於可重現性證據：不記錄它，卷宗就無法解釋
        # 「同樣的輸入為什麼換算出不同的 UTC」。
        "tz_database": library_info["tz_database"],
        "requested_ephemeris_source": "Swiss Ephemeris files",
        "ephemeris_dataset_lineage": dict(
            _EPHEMERIS_DATASET_LINEAGE
        ),
        "available_input_files": _available_files_receipt(options),
        "manifest_semantics": (
            "availability_only_actual_source_is_proven_by_each_returned_retflag"
        ),
    }


_SWISS_FILES_REQUIRED = "Swiss files required; fail closed on Moshier fallback"


def _event_module_provenance(event_module_availability: dict) -> dict:
    return {
        # An event search has no module object of its own to carry state
        # (one lunar_events container holds two searches), so the entry
        # written where the search runs is the owner.
        "lunar_phases": {
            **event_module_availability["lunar_phases"],
            "source_policy": _SWISS_FILES_REQUIRED,
            "detail_path": "astronomical_data.lunar_events",
        },
        "eclipses": {
            **event_module_availability["eclipses"],
            "source_policy": (
                "Swiss global search plus Sun/Moon retflag verification"
            ),
            "detail_path": (
                "astronomical_data.lunar_events.eclipses"
            ),
        },
        "rise_set_transits": {
            **event_module_availability["rise_set_transits"],
            "source_policy": (
                "Swiss files requested via FLG_SWIEPH"
            ),
            "actual_source_verified": False,
            "source_evidence": (
                "requested_flag_only_rise_trans_returns_no_"
                "ephemeris_retflag"
            ),
            "detail_path": "astronomical_data.horizon_events",
        },
        # VOC's state is on derived_methods.void_of_course (detail_path);
        # this entry keeps only the search's source policy.
        "void_of_course": {
            "source_policy": _SWISS_FILES_REQUIRED,
            "detail_path": "derived_methods.void_of_course",
        },
        "birth_time_sensitivity": {
            **event_module_availability["birth_time_sensitivity"],
            "source_policy": _SWISS_FILES_REQUIRED,
            "detail_path": "birth_time_sensitivity",
        },
        # Its own two-event search, so it can survive a refused phase search.
        "prenatal_syzygy": {
            **event_module_availability["prenatal_syzygy"],
            "source_policy": _SWISS_FILES_REQUIRED,
            "detail_path": "astronomical_data.lunar_events.prenatal_syzygy",
        },
    }


def _provenance_section(
    core_records: list[dict],
    fixed_star_records: list[dict],
    event_module_availability: dict,
    input_files_unchanged_during_chart: bool,
) -> dict:
    return {
        "core_objects": core_records,
        # False when an input file was renamed, replaced or rewritten while the
        # chart was computed; then no object claims the full ephemeris.
        "input_files_unchanged_during_chart": input_files_unchanged_during_chart,
        "fixed_stars": fixed_star_records,
        "retflag_names_by_value": {
            str(value): _retflag_names(value)
            for value in sorted({
                value
                for record in core_records + fixed_star_records
                for value in record["retflags"].values()
                if value is not None
            })
        },
        "source_usage_semantics": (
            "ephemeris source usage and result applicability are "
            "independent; inspect result_status and used_full_ephemeris "
            "separately"
        ),
        "all_core_calculation_sources_used_full_ephemeris": all(
            record["used_full_ephemeris"] is True
            for record in core_records
        ),
        "core_result_status_counts": {
            status: sum(
                record["result_status"] == status
                for record in core_records
            )
            for status in ("available", "not_applicable", "failed")
        },
        "fallback_object_keys": [
            record["key"]
            for record in core_records + fixed_star_records
            if record["used_full_ephemeris"] is False
        ],
        "event_modules": _event_module_provenance(event_module_availability),
    }


def build_calculation_dossier(
    *,
    request,
    effective_request,
    time_conversion: dict,
    representative_policy: str,
    context,
    library_info: dict,
    astronomical_data: dict,
    derived_methods: dict,
    derived_geometry: dict,
    trace_steps: list[dict],
    full_ephemeris_files_available: bool,
    input_files_unchanged_during_chart: bool,
    build_identity: dict,
    birth_time_sensitivity: dict,
    event_module_availability: dict,
    latitude_regime: dict | None,
    method_frame_states: dict,
) -> dict:
    """Build the authoritative receipt after all requested calculations finish."""

    # Provenance aggregates every requested ephemeris point group,
    # the lunar apsides included, rather than a fixed core list.
    core_records = [
        _object_provenance(item)
        for item in (
            astronomical_data["bodies"]
            + astronomical_data["nodes"]
            + list((astronomical_data.get("lunar_apsides") or {}).get("points") or [])
        )
    ]
    fixed_star_records = [
        _object_provenance(item)
        # An unrequested module container is null (option_states owns state).
        for item in astronomical_data["fixed_stars"] or ()
    ]
    # One reading of the states the producers recorded; every receipt
    # below is a projection of it.
    states = _module_states(
        request.options,
        astronomical_data,
        derived_methods,
        derived_geometry,
        event_module_availability,
    )
    modules = {
        "core_positions": MODULE_STATUSES[1],
        **{name: module_status_word(states[name]) for name in _MODULE_ORDER},
    }
    option_states = _option_state_receipts(
        request,
        states,
        {
            "astronomical_data": astronomical_data,
            "derived_methods": derived_methods,
            "derived_geometry": derived_geometry,
        },
    )
    methodology = _methodology_receipt(derived_methods, modules)
    # One state per assessable path, joining what the sampling pass
    # compared with this dossier's module and option receipts (the one
    # generator of requested/applicable).  None when no interval was sampled.
    sensitivity_coverage = _sensitivity_coverage_ledger(
        birth_time_sensitivity,
        modules=modules,
        option_states=option_states,
    )
    warnings = structured_warnings(
        request=request,
        effective_request=effective_request,
        time_conversion=time_conversion,
        full_ephemeris_files_available=full_ephemeris_files_available,
        input_files_unchanged_during_chart=input_files_unchanged_during_chart,
        core_records=core_records,
        fixed_star_records=fixed_star_records,
        fixed_stars=astronomical_data["fixed_stars"] or [],
        modules=modules,
        methodology=methodology,
        states={
            **states,
            "birth_time_sensitivity": _state_of(
                event_module_availability.get("birth_time_sensitivity")
            ),
        },
        bodies=astronomical_data["bodies"],
        planet_in_house=derived_methods["planet_in_house"] or {},
        latitude_regime=latitude_regime,
        sect=derived_methods["sect"],
        essential_dignities=derived_methods.get("essential_dignities"),
        lunar_mansions=derived_methods.get("lunar_mansions"),
        classical_classifications=derived_methods.get("classical_classifications"),
        sensitivity_coverage=sensitivity_coverage,
        aspect_participants_present=bool(
            (derived_methods.get("aspects") or {}).get("participants")
        ),
        horizon_contract_present=bool(
            (astronomical_data.get("horizon_events") or {}).get("contract")
        ),
    )

    return {
        "dossier_version": DOSSIER_VERSION,
        "status": "provisional",
        "authority": "backend_effective_runtime",
        "build_identity": dict(build_identity),
        "input_receipt": request.model_dump(mode="json"),
        "birth_time": _birth_time_section(
            request, time_conversion, representative_policy, sensitivity_coverage
        ),
        "location_resolution": _location_section(request),
        "time_conversion": _time_conversion_section(request, time_conversion),
        "calculation_policy": _calculation_policy_section(
            request=request,
            effective_request=effective_request,
            context=context,
            modules=modules,
            option_states=option_states,
            frame_states=method_frame_states,
            states=states,
            derived_methods=derived_methods,
            atmosphere=astronomical_data["atmosphere"],
            latitude_regime=latitude_regime,
        ),
        "engine": _engine_section(library_info, request.options),
        "provenance": _provenance_section(
            core_records, fixed_star_records, event_module_availability,
            input_files_unchanged_during_chart,
        ),
        # The per-module execution and method states are already in
        # calculation_policy.modules and each derived_methods receipt; the
        # dossier repeats only the public disagreement marks.
        "methodology": {
            "classical_source_disagreements": methodology[
                "classical_source_disagreements"
            ],
        },
        # The register every source_ref resolves in.
        "method_source_register": method_source_register_receipt(),
        "warnings": warnings,
        "trace_receipt": _trace_receipt(trace_steps),
        "privacy": privacy_attestation(),
    }
