"""Stage 2 of the chart pipeline: positions, houses, fixed stars and event
searches (``AstronomicalFacts``)."""

import math

import swisseph as swe

from .core.invariants import InternalInvariantError
from .domain_catalog import (
    CLASSICAL_BODIES,
    OUTER_BODIES,
    MODERN_MINOR_BODIES,
    LUNAR_APSIDES,
    FIXED_STARS,
)
from .ephemeris import CHIRON_SEGMENT, FullEphemerisRequiredError, coverage_receipt
from .schema_chart import ChartRequest, OptionsInput
from .core.trace import Trace
from .core.computation_mode import ComputationContext
from .core.time_utils import REPRESENTATIVE_SAMPLE_ROLES, representative_sample_instants
from .core.bodies import (
    DATE_ONLY_NO_BIRTH_TIME_REASON,
    compute_bodies,
    EFFECTIVE_TOPOCENTRIC_MOON_LABELS,
    append_south_nodes,
    make_longitude_sampler,
    node_definitions,
    unavailable_body_record,
    withhold_horizontal_coordinates,
)
from .core.houses import (
    EXTRA_ANGLE_PROVENANCE,
    compute_houses,
    printed_angles,
    printed_house_division,
)
from .core.house_placements import compute_planet_house_placements, whole_sign_point_placements
from .core.fixed_stars import compute_fixed_stars
from .core.lunar_events import compute_primary_phases, compute_previous_eclipses
from .core.prenatal_points import (
    PrenatalPlace,
    attach_eclipse_points,
    attach_prenatal_syzygy,
    comparable_view as prenatal_comparable_view,
)
from .core.horizon_events import (
    RISE_TRANS_REPEATABILITY_DAYS,
    HorizonProbeCache,
    compute_horizon_events,
    probe_cache_for_chart,
)
from .core.root_finding import wrap_to_signed_180
from .core.module_state import (
    computed_receipt,
    module_state,
    unavailable_state as _unavailable_state,
)
from .core.method_status import method_head
from .chart_stages import (
    AstronomicalFacts,
    EventFacts,
    HouseFacts,
    JsonObject,
    PositionFacts,
    TimeResolution,
)
from .chart_time import _event_availability_entry, _event_search_refusal, _prenatal_place


# With a non-exact birth time one anchor's event search would read as the
# birth's event identity, so three samples (interval ends and anchor) stand side
# by side, labelled, never merged.  Interval: the civil day for date_only, the
# stated civil hour for approximate_hour.
REPRESENTATIVE_SAMPLING_STATUSES = (
    "sampled_interval_ends_and_anchor",
    "not_applicable_exact_birth_time",
)
# Where a sample's result lives.  The anchor sample is the module's own top-level
# computation (same reference JD, same producers), so it points there instead of
# carrying a second copy (~29 KB with every event module, against the response
# budget).  The interval start and end samples are inline.
SAMPLE_RESULT_LOCATIONS = ("inline", "module_top_level")
# An inline sample does not repeat a sub-result that is the same as the anchor's:
# it lists the omitted keys (`same_as_anchor`; per horizon body
# `events_same_as_anchor`), so an absent key reads as "same value as the anchor",
# never as missing.  "Same" is `_same_event`: a root found again from another
# reference instant can differ from the anchor's in the last bits, so an exact
# float comparison made the omission depend on the platform's rounding.
_LUNAR_SAMPLE_RESULT_KEYS = (
    "contract", "direction_policy", "primary_phases", "prenatal_syzygy", "eclipses",
)
_ANCHOR_SAMPLE_ROLE = REPRESENTATIVE_SAMPLE_ROLES[1]
# Julian-day values (any key containing "jd_ut") agree within two seconds: a
# horizon event re-solved from another anchor moves by up to about a second
# (RISE_TRANS_REPEATABILITY_DAYS) and is printed as the whole second it lies in,
# so two prints of one event are at most one second apart, while distinct events
# of one kind are at least ~0.9 day apart.  Any other float (eclipse gamma and
# diameter ratios, solver residuals and speeds) agrees within a relative 1e-9:
# rounding of one quantity, never a different value.  `utc_time*` strings are
# derived from the compared JD (truncated, so one ULP can flip them) and not
# compared.
_SAME_EVENT_JD_TOLERANCE_DAYS = 2 * RISE_TRANS_REPEATABILITY_DAYS
_SAME_EVENT_FLOAT_REL_TOLERANCE = 1e-9


def _same_event(a, b, *, jd_valued: bool = False) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        if jd_valued:
            return abs(a - b) <= _SAME_EVENT_JD_TOLERANCE_DAYS
        return math.isclose(a, b, rel_tol=_SAME_EVENT_FLOAT_REL_TOLERANCE)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(
            key.startswith("utc_time")
            or _same_event(a[key], b[key], jd_valued=jd_valued or "jd_ut" in key)
            for key in a
        )
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return (
            type(a) is type(b)
            and len(a) == len(b)
            and all(_same_event(x, y, jd_valued=jd_valued) for x, y in zip(a, b))
        )
    return type(a) is type(b) and a == b


def _omit_lunar_keys_same_as_anchor(sample: dict, anchor: dict) -> None:
    same = [
        key
        for key in _LUNAR_SAMPLE_RESULT_KEYS
        if key in sample and key in anchor and _same_event(
            prenatal_comparable_view(key, sample[key]),
            prenatal_comparable_view(key, anchor[key]),
        )
    ]
    for key in same:
        del sample[key]
    sample["same_as_anchor"] = same


def _omit_horizon_events_same_as_anchor(bodies: list[dict], anchor: dict) -> None:
    anchor_by_key = {body["key"]: body for body in anchor.get("bodies", [])}
    for body in bodies:
        anchor_events = (anchor_by_key.get(body["key"]) or {}).get("events") or {}
        same = [
            name
            for name, event in body["events"].items()
            if name in anchor_events and _same_event(anchor_events[name], event)
        ]
        for name in same:
            del body["events"][name]
        body["events_same_as_anchor"] = same


_EXACT_EVENT_TIME_BASIS = "birth_instant"


def _event_time_basis(time: TimeResolution) -> str:
    """What an event module's instants stand for: the birth instant for an
    exact time, else the request's own input semantics."""

    if time.input_request.birth_time_precision == "exact":
        return _EXACT_EVENT_TIME_BASIS
    return time.time_conversion["input_semantics"]


def _representative_sampling_receipt(precision: str) -> dict:
    if precision == "exact":
        return {
            "status": REPRESENTATIVE_SAMPLING_STATUSES[1],
            "interval": None,
        }
    return {
        "status": REPRESENTATIVE_SAMPLING_STATUSES[0],
        "interval": "civil_day" if precision == "date_only" else "stated_civil_hour",
        "sample_roles": list(REPRESENTATIVE_SAMPLE_ROLES),
        "merge_policy": "side_by_side_not_merged",
        "result_locations": list(SAMPLE_RESULT_LOCATIONS),
        "same_as_anchor_semantics": "listed_keys_omitted_because_equal_to_the_anchor_value",
        "note": (
            "區間兩端與代表錨點各自完整計算、並列輸出；代表錨點的結果就是本模組頂層的結果"
            "（result_location=module_top_level），不另抄一份。三者都是代表性取樣，"
            "不是出生時刻，也不合併成單一答案。"
        ),
    }


def _search_events(
    lunar: JsonObject,
    reference: float,
    req: ChartRequest,
    search_trace: Trace,
    refusal_trace: Trace,
    *,
    place: PrenatalPlace,
    body_defs: list[JsonObject],
    horizon: bool,
    probe_cache: HorizonProbeCache | None,
    sample_role: str | None = None,
) -> tuple[JsonObject | None, dict]:
    """The requested lunar and horizon searches at one instant: the chart's own
    (``sample_role`` None, with the birth relations) or an interval-end sample's.
    Lunar results go into ``lunar``; returns the horizon result (None when not
    searched or refused) and each refused module's state."""

    prefix = "" if sample_role is None else f"代表性取樣（{sample_role}）："
    at_birth = sample_role is None
    refusals: dict = {}

    def attempt(module: str, label: str, search, *undo: str):
        try:
            return search()
        except (FullEphemerisRequiredError, swe.Error) as error:
            for key in undo:
                lunar.pop(key, None)
            refusals[module] = _event_search_refusal(prefix + label, error, refusal_trace)
            return None

    if req.options.include_lunar_phases:
        attempt("lunar_phases", "主要月相事件",
                lambda: lunar.update(compute_primary_phases(reference, search_trace)))
        # The prenatal syzygy needs only its own event, so it survives a
        # refusal of the eight-event phase search.
        attempt("prenatal_syzygy", "產前朔望", lambda: attach_prenatal_syzygy(
            lunar, reference, place, search_trace, with_birth_relation=at_birth))
    if req.options.include_eclipses:
        def eclipses() -> None:
            lunar["eclipses"] = compute_previous_eclipses(reference, search_trace)
            attach_eclipse_points(
                lunar, reference, place, search_trace, with_birth_relation=at_birth
            )
        attempt("eclipses", "出生前最近日食／月食", eclipses, "eclipses", "eclipses_at_birth")
    horizon_result = None
    if horizon:
        horizon_result = attempt(
            "rise_set_transits", "天體升降與上下中天",
            lambda: compute_horizon_events(
                body_defs, reference, req.location, req.atmosphere, search_trace,
                probe_cache=probe_cache,
            ),
        )
    return horizon_result, refusals


def _representative_event_sample(
    instant: JsonObject,
    *,
    req: ChartRequest,
    body_defs: list[JsonObject],
    anchors: tuple[JsonObject, JsonObject],
    horizon_probe_cache: HorizonProbeCache | None,
    sample_trace: Trace,
    trace: Trace,
    place: PrenatalPlace,
) -> tuple[JsonObject, JsonObject]:
    """One interval-end sample's lunar and horizon searches, beside the anchor."""

    # The anchor's lunar and horizon results; an empty one was not produced.
    lunar_anchor, horizon_anchor = anchors
    horizon_requested = bool(horizon_anchor)

    role = instant["sample_role"]
    reference = instant["reference_jd_ut"]
    lunar_sample = {**instant, "result_location": SAMPLE_RESULT_LOCATIONS[0]}
    horizon_sample = {**instant, "result_location": SAMPLE_RESULT_LOCATIONS[0]}
    horizon, refusals = _search_events(
        lunar_sample, reference, req, sample_trace, trace, place=place, body_defs=body_defs,
        horizon=horizon_requested, probe_cache=horizon_probe_cache, sample_role=role,
    )
    if horizon_requested:
        horizon_sample["bodies"] = horizon["bodies"] if horizon is not None else []
    lunar_refusals = {key: value for key, value in refusals.items() if key != "rise_set_transits"}
    horizon_refusals = {key: value for key, value in refusals.items() if key == "rise_set_transits"}
    _omit_lunar_keys_same_as_anchor(lunar_sample, lunar_anchor)
    _omit_horizon_events_same_as_anchor(
        horizon_sample.get("bodies", []), horizon_anchor
    )
    lunar_sample["module_refusals"] = lunar_refusals
    horizon_sample["module_refusals"] = horizon_refusals
    return lunar_sample, horizon_sample


def _label_event_identity(
    *,
    time: TimeResolution,
    body_defs: list[dict],
    lunar_events: dict,
    horizon_events: dict,
    horizon_probe_cache: HorizonProbeCache | None,
) -> None:
    input_request, req, trace = time.input_request, time.request, time.trace
    precision = input_request.birth_time_precision
    # A module that was requested and refused stays an empty object — that is
    # how the response says "unavailable" — so labels and samples follow only
    # the modules that produced a result at the anchor.
    lunar_requested = bool(lunar_events)
    horizon_requested = bool(horizon_events)
    if not (lunar_requested or horizon_requested):
        return
    receipt = _representative_sampling_receipt(precision)
    time_basis = _event_time_basis(time)
    if lunar_requested:
        lunar_events["time_basis"] = time_basis
        lunar_events["representative_sampling"] = receipt
    if horizon_requested:
        horizon_events["contract"]["reference_time"] = time_basis
        horizon_events["representative_sampling"] = receipt
    if precision == "exact":
        return

    if time.anchor_utc is None:  # resolved for every non-exact chart
        raise InternalInvariantError("time.anchor_utc is not None")
    instants = representative_sample_instants(
        input_request.datetime,
        input_request.timezone,
        precision=precision,
        anchor_utc=time.anchor_utc,
        civil_day=time.civil_day,
    )
    # Sample searches repeat the anchor's steps; their detail stays out of the
    # main trace, which records the samples and any refusal.
    sample_trace = Trace()
    lunar_samples = []
    horizon_samples = []
    for instant in instants:
        if instant["sample_role"] == _ANCHOR_SAMPLE_ROLE:
            # The anchor sample is the top-level computation (same instant, same
            # producers); its refusals are the modules' own availability.
            pointer = {**instant, "result_location": SAMPLE_RESULT_LOCATIONS[1]}
            lunar_samples.append(dict(pointer))
            horizon_samples.append(dict(pointer))
            continue
        lunar_sample, horizon_sample = _representative_event_sample(
            instant,
            req=req,
            body_defs=body_defs,
            anchors=(lunar_events, horizon_events),
            horizon_probe_cache=horizon_probe_cache,
            sample_trace=sample_trace,
            trace=trace,
            place=_prenatal_place(input_request, time.context),
        )
        lunar_samples.append(lunar_sample)
        horizon_samples.append(horizon_sample)
    if lunar_requested:
        lunar_events["representative_samples"] = lunar_samples
    if horizon_requested:
        horizon_events["representative_samples"] = horizon_samples
    trace.add(
        "非精確出生時間：事件模組的三個代表性取樣",
        inputs={
            "取樣": [
                f"{item['sample_role']} {item['reference_local_time']}"
                for item in instants
            ]
        },
        note=(
            "出生時間不精確時，區間兩端與代表錨點各算一次，"
            "三個結果並列、不合併；它們是代表性取樣，不是出生時刻。"
        ),
    )


def _requested_body_defs(options: OptionsInput) -> list[JsonObject]:
    return (
        [{"id": b["id"], "key": b["key"], "zh": b["zh"]} for b in CLASSICAL_BODIES]
        + ([{"id": b["id"], "key": b["key"], "zh": b["zh"]} for b in OUTER_BODIES] if options.include_outer_planets else [])
        + ([dict(b) for b in MODERN_MINOR_BODIES] if options.include_chiron else [])
    )


def _bodies(time: TimeResolution) -> tuple[list[JsonObject], list[JsonObject]]:
    req, jd_ut, ctx, trace = time.request, time.jd_ut, time.context, time.trace
    body_defs = _requested_body_defs(req.options)
    # Optional bodies are gated on their own segment's coverage before any Swiss
    # call: a warm worker would otherwise extrapolate Chiron past seas_18 under
    # SWIEPH while a fresh worker raised.
    unavailable_bodies = []
    if req.options.include_chiron:
        chiron_coverage = coverage_receipt(jd_ut, CHIRON_SEGMENT)
        if chiron_coverage["coverage_state"] != "covered":
            unavailable_bodies = [
                unavailable_body_record(definition, trace, coverage=chiron_coverage)
                for definition in body_defs
                if definition["key"] == "chiron"
            ]
            body_defs = [
                definition for definition in body_defs if definition["key"] != "chiron"
            ]
    bodies = compute_bodies(body_defs, jd_ut, ctx, req.atmosphere, trace, physical=True)
    bodies.extend(unavailable_bodies)
    return body_defs, bodies


def _topocentric_moon(
    time: TimeResolution,
    body_defs: list[JsonObject],
    bodies: list[JsonObject],
) -> tuple[list[JsonObject], JsonObject | None, ComputationContext | None]:
    req, jd_ut, ctx, trace = time.request, time.jd_ut, time.context, time.trace
    # Optional Moon-only topocentric mode retains the geocentric reference and
    # makes the selected downstream origin explicit; it is not a precision claim.
    parallax_moon = None
    moon_ctx = None
    if req.options.moon_position_profile == "moon_only_topocentric_v1":
        geocentric_moon = next(body for body in bodies if body["key"] == "moon")
        moon_mode = req.computation_mode.model_copy(update={"center": "topocentric"})
        moon_ctx = ComputationContext(moon_mode, req.location)
        topocentric_moon = compute_bodies(
            [next(body for body in body_defs if body["key"] == "moon")],
            jd_ut,
            moon_ctx,
            req.atmosphere,
            trace,
            physical=True,
        )[0]
        # coordinate_origin names the origin of the ecliptic and equatorial
        # values.  Altitude and azimuth follow the response-wide horizontal
        # convention (computation_mode.horizontal_source_flags): topocentric for
        # every record, so the geocentric reference's altitude equals the
        # effective Moon's.  Labelled, not recomputed, per the contract's
        # `altitudes.origin`.
        geocentric_reference = {
            **geocentric_moon,
            "coordinate_origin": "earth_center",
            "horizontal_coordinate_origin": ctx.HORIZONTAL_COORDINATE_ORIGIN,
            "role": "retained_reference_not_used_by_effective_downstream",
        }
        effective_topocentric = {**topocentric_moon, **EFFECTIVE_TOPOCENTRIC_MOON_LABELS}
        bodies = [
            effective_topocentric if body["key"] == "moon" else body
            for body in bodies
        ]
        moon_longitude_delta = wrap_to_signed_180(
            topocentric_moon["longitude"] - geocentric_moon["longitude"]
        )
        parallax_moon = {
            **method_head("moon_only_topocentric_comparison_v1", "parallax_moon"),
            **computed_receipt(
                "Swiss Ephemeris SEFLG_TOPOCTR with observer geoposition"
            ),
            "coordinate_frame": (
                "mixed_origin_geocentric_chart_with_topocentric_effective_moon"
            ),
            "global_center": "geocentric",
            "effective_moon_center": "topocentric",
            "geocentric_reference": geocentric_reference,
            "topocentric_effective": effective_topocentric,
            "longitude_delta_degrees": moon_longitude_delta,
            "effective_downstream_paths": [
                "astronomical_data.bodies[moon]",
                "derived_methods.planet_in_house",
                "derived_geometry.antiscia",
                "derived_methods.lots",
                "derived_methods.void_of_course",
                "derived_methods.declination_aspects",
                "derived_methods.aspects",
                "derived_methods.essential_dignities",
                "birth_time_sensitivity",
            ],
            "claim": "different_observer_origin_not_more_accurate",
            "difference": {
                "longitude_signed_degrees": moon_longitude_delta,
                "latitude_degrees": (
                    topocentric_moon["latitude"] - geocentric_moon["latitude"]
                ),
                "right_ascension_signed_degrees": wrap_to_signed_180(
                    topocentric_moon["right_ascension"]
                    - geocentric_moon["right_ascension"]
                ),
                "declination_degrees": (
                    topocentric_moon["declination"] - geocentric_moon["declination"]
                ),
            },
            "downstream_policy": {
                "effective_moon": "topocentric",
                "other_bodies": "geocentric",
                "frame_semantics": "intentional_mixed_origin_profile",
                "interpretive_claim": None,
            },
        }
    return bodies, parallax_moon, moon_ctx


def _lunar_apsides(time: TimeResolution) -> JsonObject | None:
    req, jd_ut, ctx, trace = time.request, time.jd_ut, time.context, time.trace
    lunar_apsides = None
    if req.options.include_lilith_priapus:
        apsis_points = compute_bodies(
            [dict(body) for body in LUNAR_APSIDES], jd_ut, ctx, req.atmosphere, trace,
            physical=False, moon_relative=True,
        )
        lunar_apsides = {
            **method_head("swiss_lunar_apsides_named_points_v1", "lunar_apsides"),
            # Executed (Swiss ran); the reason comes from the records.
            **computed_receipt(
                "Swiss Ephemeris MEAN_APOG, INTP_APOG and INTP_PERG",
                applicable=ctx.mode.center in {"geocentric", "topocentric"},
                available=all(
                    point.get("longitude") is not None for point in apsis_points
                ),
                reason_code=next(
                    (
                        point.get("availability_reason_code")
                        for point in apsis_points
                        if point.get("longitude") is None
                    ),
                    None,
                ),
            ),
            "coordinate_policy": {
                "orbital_reference": "geocentric_lunar_orbit_model",
                "topocentric_parallax_applied": False,
                "reason": (
                    "Swiss Ephemeris does not distinguish topocentric from "
                    "geocentric lunar nodes/apogees for these orbital points"
                ),
            },
            "aspect_participation": "not_included_by_this_option",
            "points": apsis_points,
            "scope": {
                "classification": "modern_research_additional_points",
                "automatic_aspects": False,
                "automatic_classical_methods": False,
                "natural_priapus_is_independently_calculated": True,
                "natural_priapus_is_not_forced_opposite_natural_lilith": True,
            },
        }
    return lunar_apsides


def _nodes(time: TimeResolution) -> tuple[list[JsonObject], list[JsonObject]]:
    req, jd_ut, ctx, trace = time.request, time.jd_ut, time.context, time.trace
    node_defs = node_definitions()
    nodes = compute_bodies(
        node_defs, jd_ut, ctx, req.atmosphere, trace, physical=False, moon_relative=True,
    )
    if req.options.include_south_nodes:
        append_south_nodes(nodes, jd_ut, ctx, req.atmosphere, trace)
    return node_defs, nodes


def _horizontal_records(
    bodies: list[JsonObject],
    nodes: list[JsonObject],
    lunar_apsides: JsonObject | None,
    parallax_moon: JsonObject | None,
) -> list[JsonObject]:
    """Every position record that prints an azimuth and altitudes."""

    records = [*bodies, *nodes, *((lunar_apsides or {}).get("points") or [])]
    for key in ("geocentric_reference", "topocentric_effective"):
        record = (parallax_moon or {}).get(key)
        if isinstance(record, dict):
            records.append(record)
    return records


def _positions(time: TimeResolution) -> PositionFacts:
    body_defs, bodies = _bodies(time)
    bodies, parallax_moon, moon_ctx = _topocentric_moon(time, body_defs, bodies)
    lunar_apsides = _lunar_apsides(time)
    node_defs, nodes = _nodes(time)
    if time.input_request.birth_time_precision == "date_only":
        for record in _horizontal_records(bodies, nodes, lunar_apsides, parallax_moon):
            withhold_horizontal_coordinates(record, DATE_ONLY_NO_BIRTH_TIME_REASON)
    bodies_all = bodies + nodes
    return PositionFacts(
        body_defs=body_defs,
        bodies=bodies,
        parallax_moon=parallax_moon,
        lunar_apsides=lunar_apsides,
        node_defs=node_defs,
        nodes=nodes,
        bodies_all=bodies_all,
        bodies_by_key={b["key"]: b for b in bodies_all},
        longitude_at=make_longitude_sampler(time.context, moon_ctx=moon_ctx),
    )


def _extra_angles(
    options: OptionsInput,
    values: JsonObject | None,
    unavailable_reason: str | None = None,
) -> JsonObject | None:
    """The requested non-classical angles, or None when neither option asked.

    Without house values (``values`` None) the requested angles fail closed by
    presence, the way the nodes do: each stays with a null longitude and the
    reason, so a consumer sees that the module answered rather than vanished.
    The container's source is read off the members, so a container holding
    only the anti-vertex (derived from the Vertex, not returned by
    `swe.houses_ex`) cannot contradict its member's own receipt; a refused
    container's source is null like every other refused receipt.
    """

    if not (options.include_extra_angles or options.include_anti_vertex):
        return None
    applicable = values is not None
    missing = {} if applicable else {"reason_code": unavailable_reason}
    selected: dict[str, dict] = {}
    if options.include_extra_angles:
        selected.update({
            key: {
                "longitude": values[key] if values is not None else None,
                **missing,
                **EXTRA_ANGLE_PROVENANCE[key],
            }
            for key in EXTRA_ANGLE_PROVENANCE
            if key != "anti_vertex"
        })
    if options.include_anti_vertex:
        vertex = values["vertex"] if values is not None else None
        selected["anti_vertex"] = {
            "longitude": (vertex + 180.0) % 360.0 if vertex is not None else None,
            "source_vertex_longitude_degrees": vertex,
            **missing,
            **EXTRA_ANGLE_PROVENANCE["anti_vertex"],
        }
    sources = sorted({entry["calculation_source"] for entry in selected.values()})
    container = {
        **module_state(
            requested=True,
            executed=applicable,
            applicable=applicable,
            available=applicable,
            source=(
                None if not applicable
                else sources[0] if len(sources) == 1 else "per_angle"
            ),
            reason_code=unavailable_reason,
        ),
        "semantics": "non_classical_technical_angles_opt_in",
        # Constant text and the source labels: register entry extra_angles.
        "note_source_ref": "extra_angles",
        "angles": selected,
    }
    return container if applicable else {**container, "status": "not_applicable"}


def _computed_houses(time: TimeResolution, bodies: list[JsonObject]) -> HouseFacts:
    req, jd_ut, ctx, trace = time.request, time.jd_ut, time.context, time.trace
    houses = compute_houses(
        req.options.house_system, jd_ut, req.location, ctx, trace
    )
    angles = printed_angles(houses)
    extra_angles = _extra_angles(req.options, houses["extra_angles"])
    house_division = printed_house_division(houses, req.options.house_system)
    planet_in_house = compute_planet_house_placements(bodies, houses, ctx, trace)
    return HouseFacts(
        angles=angles,
        asc=houses["asc"],
        extra_angles=extra_angles,
        house_division=house_division,
        planet_in_house=planet_in_house,
        houses=houses,
        latitude_regime=houses["latitude_regime"],
    )


def _unavailable_houses(
    time: TimeResolution,
    bodies: list[JsonObject],
    *,
    unavailable_reason: str,
    houses_requested: bool,
) -> HouseFacts:
    req, ctx, trace = time.request, time.context, time.trace
    state = _unavailable_state(unavailable_reason, requested=houses_requested)
    status = "not_applicable" if houses_requested else "not_requested"
    angles = {
        **state,
        "status": status,
        "asc": None,
        "mc": None,
        "desc": None,
        "ic": None,
        "armc": None,
    }
    extra_angles = _extra_angles(req.options, None, unavailable_reason)
    house_division = {
        **state,
        "method": None,
        "method_status": None,
        "period": None,
        "name_status": None,
        "execution_status": status,
        "requested_system_code": req.options.house_system,
        "system_code": None,
        "system_name": None,
        "cusps": [],
        "angles_source": None,
    }
    # When houses were asked for but the observer has no horizon, the placement
    # writes its own not_applicable and reason code, not "not requested".
    planet_in_house = (
        compute_planet_house_placements(bodies, None, ctx, trace)
        if req.options.include_houses
        else {
            "method": None,
            "method_status": None,
            "period": None,
            "name_status": None,
            **state,
            "execution_status": status,
            "reason_codes": [unavailable_reason],
            "house_system_code": None,
            "house_system_name": None,
            "interval_semantics": None,
            "placements": [],
        }
    )
    trace.add(
        "宮位與角點",
        inputs={"include_houses": houses_requested},
        result={"execution_status": status, "reason_code": unavailable_reason},
        note=(
            "未呼叫 swe.houses_ex；非地心觀測中心沒有地平圈，"
            "只有出生日期時沒有出生時刻，未請求宮位時則不執行。"
        ),
    )
    return HouseFacts(
        angles=angles,
        asc=None,
        extra_angles=extra_angles,
        house_division=house_division,
        planet_in_house=planet_in_house,
        houses=None,
        latitude_regime=None,
    )


def _houses(time: TimeResolution, bodies: list[JsonObject]) -> HouseFacts:
    req = time.request
    # Whether an Earth-relative frame exists is one premise, read from the
    # central frame table by every consumer (else a heliocentric chart printed
    # an ascendant beside a refusal naming the same frame).
    house_frame = time.frame_states["house_division"]
    # Whether houses were asked for is the input request's fact; the
    # effective request drops them for date_only.
    houses_requested = time.input_request.options.include_houses
    if req.options.include_houses and house_frame["applicable"]:
        return _computed_houses(time, bodies)
    unavailable_reason = (
        house_frame["reason_code"]
        if req.options.include_houses
        else DATE_ONLY_NO_BIRTH_TIME_REASON
        if houses_requested
        else "house_calculation_not_executed"
    )
    return _unavailable_houses(
        time,
        bodies,
        unavailable_reason=unavailable_reason,
        houses_requested=houses_requested,
    )


# Whole-sign places of the nodes and lunar apsides beside the planets'.
def _place_nodes_and_apsides(
    time: TimeResolution, positions: PositionFacts, houses: HouseFacts
) -> None:
    if not isinstance(houses.planet_in_house, dict) or "placements" not in houses.planet_in_house:
        return
    houses.planet_in_house["point_placements"] = whole_sign_point_placements(
        [*positions.nodes, *((positions.lunar_apsides or {}).get("points") or [])],
        houses.houses,
        houses.planet_in_house,
        time.trace,
    )


def _fixed_stars(time: TimeResolution) -> list[JsonObject]:
    req = time.request
    if not req.options.include_fixed_stars:
        return []
    stars = compute_fixed_stars(FIXED_STARS, time.jd_ut, time.context, req.atmosphere, time.trace)
    if time.input_request.birth_time_precision == "date_only":
        for star in stars:
            withhold_horizontal_coordinates(star, DATE_ONLY_NO_BIRTH_TIME_REASON)
    return stars


def _events(time: TimeResolution, body_defs: list[JsonObject]) -> EventFacts:
    req, jd_ut, trace = time.request, time.jd_ut, time.trace
    lunar_events: JsonObject = {}
    # No VOC entry: its state is on derived_methods.void_of_course, written by
    # the code that runs or refuses it.
    event_module_availability = {
        name: _event_availability_entry(requested)
        for name, requested in (
            ("lunar_phases", req.options.include_lunar_phases),
            ("eclipses", req.options.include_eclipses),
            ("rise_set_transits", req.options.include_rise_set_transits),
            ("birth_time_sensitivity", time.input_request.birth_time_precision != "exact"),
            ("prenatal_syzygy", req.options.include_lunar_phases),
        )
    }
    # The anchor search and the samples share one set of Swiss rise/set answers
    # (performance only); None near the bundled ephemeris end, where reuse is inexact.
    horizon_probe_cache: HorizonProbeCache | None = None
    if req.options.include_rise_set_transits:
        horizon_probe_cache = probe_cache_for_chart(body_defs, jd_ut)
    horizon, refusals = _search_events(
        lunar_events, jd_ut, req, trace, trace,
        place=_prenatal_place(time.input_request, time.context), body_defs=body_defs,
        horizon=req.options.include_rise_set_transits, probe_cache=horizon_probe_cache,
    )
    horizon_events = horizon or {}
    event_module_availability.update(refusals)
    _label_event_identity(
        time=time,
        body_defs=body_defs,
        lunar_events=lunar_events,
        horizon_events=horizon_events,
        horizon_probe_cache=horizon_probe_cache,
    )
    return EventFacts(
        lunar_events=lunar_events,
        horizon_events=horizon_events,
        availability=event_module_availability,
    )


def _astronomical_facts(time: TimeResolution) -> AstronomicalFacts:
    positions = _positions(time)
    houses = _houses(time, positions.bodies)
    _place_nodes_and_apsides(time, positions, houses)
    fixed_stars = _fixed_stars(time)
    events = _events(time, positions.body_defs)
    return AstronomicalFacts(
        time=time,
        positions=positions,
        houses=houses,
        fixed_stars=fixed_stars,
        events=events,
    )
