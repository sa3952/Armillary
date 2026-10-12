"""The chart pipeline: typed stages from a validated request to one response.

Each stage reads the typed results of the stages before it:

1. ``_resolve_time`` -> ``TimeResolution``: input and effective request, time
   conversion, computation context, frame table and the one trace;
2. ``_astronomical_facts`` -> ``AstronomicalFacts``: positions, houses, fixed
   stars and event searches;
3. ``_derived_chart`` -> ``DerivedChart``: derived geometry and methods;
4. ``_birth_time_sensitivity``: the sampling pass for a non-exact birth time;
5. ``_assemble_chart_response``: the one detailed response, with the
   calculation dossier as a projection of it (``core.dossier``).

Stages run in this order and append to the trace in this order, so the Swiss
call order is the order written here.  Swiss state is process-global: the
caller (``main``) holds the compute line.  ``response_projection`` derives
every other view from the response.
"""

from dataclasses import dataclass
import datetime as dtmod
import importlib.metadata
import math
from collections.abc import Callable
from typing import Any

import swisseph as swe

from .config import (
    BODY_ID_BY_KEY,
    CLASSICAL_BODIES,
    NODE_BODIES,
    OUTER_BODIES,
    MODERN_MINOR_BODIES,
    LUNAR_APSIDES,
    FIXED_STARS,
    DECLINATION_ASPECT_ORB,
)
from .ephemeris import (
    CHIRON_SEGMENT,
    FullEphemerisRequiredError,
    coverage_receipt,
    ensure_ephemeris_initialized_for_thread,
    has_full_ephemeris_files,
    init_ephemeris,
    input_files_unchanged_since,
    reset_swiss_state_for_thread,
    watch_chart_input_files,
)
from .schemas import ChartRequest, OptionsInput
from .core.trace import Trace
from .core.tz_database import TZ_DATABASE
from .core.computation_mode import ComputationContext
from .core.frame_compatibility import method_frame_states
from .core.time_utils import (
    REPRESENTATIVE_SAMPLE_ROLES,
    civil_day_receipt,
    civil_instant,
    compute_time_conversion,
    representative_policy,
    representative_sample_instants,
    resolve_civil_day,
    resolve_date_only_anchor,
    utc_datetime_to_jd_ut,
)
from .core.bodies import (
    DATE_ONLY_NO_BIRTH_TIME_REASON,
    compute_bodies,
    EFFECTIVE_TOPOCENTRIC_MOON_LABELS,
    SOUTH_NODE_DERIVATIONS,
    derive_node_antipode,
    effective_participants,
    geocentric_sun_true_altitude,
    geocentric_true_altitude,
    make_longitude_sampler,
    participant_policy_receipt,
    unavailable_body_record,
    withhold_horizontal_coordinates,
)
from .core.essential_dignities import compute_essential_dignities
from .core.formatting import attach_sign_positions
from .core.aspects import (
    aspects_not_applicable,
    compute_aspects,
    orb_profile_selection,
)
from .core.declination import (
    compute_declination_aspects,
    declination_aspects_not_applicable,
)
from .core.houses import (
    EXTRA_ANGLE_PROVENANCE,
    compute_houses,
    printed_angles,
    printed_house_division,
)
from .core.house_placements import compute_planet_house_placements, whole_sign_point_placements
from .core.birth_time_sensitivity import (
    DIFFERS_BETWEEN_SAMPLES,
    SAME_AT_ALL_SAMPLES,
    approximate_hour_representative_request,
    build_approximate_hour_sensitivity,
    build_date_only_sensitivity,
    representative_semantics_for_offset,
)
from .core.fixed_stars import compute_fixed_stars, fixed_star_receipt
from .core.lots import (
    compute_lots,
    classify_sect,
    determine_sect,
    lots_not_applicable,
)
from .core.antiscia import antiscia_not_applicable, compute_antiscia
from .core.dodecatemoria import compute_dodecatemoria, dodecatemoria_not_applicable
from .core.classical_classifications import (
    classical_classifications_not_applicable,
    compute_classical_classifications,
)
from .core.moon import (
    evaluate_void_of_course,
    voc_receipt_head,
    void_of_course_not_applicable,
)
from .core.lunar_events import (
    compute_primary_phases,
    compute_previous_eclipses,
)
from .core.prenatal_points import (
    PrenatalPlace,
    attach_eclipse_points,
    attach_prenatal_syzygy,
    comparable_view as prenatal_comparable_view,
)
from .core.horizon_events import (
    HorizonProbeCache,
    compute_horizon_events,
    probe_cache_for_chart,
)
from .core.planetary_hours import (
    compute_planetary_hours,
    planetary_hours_not_applicable,
)
from .core.lunar_mansions import (
    compute_lunar_mansions,
    lunar_mansions_not_applicable,
    lunar_mansions_unavailable,
)
from .core.solar_phase import (
    compute_solar_phase,
    make_ecliptic_sampler,
    solar_phase_not_applicable,
    solar_phase_unavailable,
)
from .core.root_finding import wrap_to_signed_180
from .core.dossier import EVENT_SEARCH_REASON_CODES, build_calculation_dossier
from .core.module_state import (
    MODULE_STATUSES as EVENT_MODULE_STATUSES,
    SEARCH_EPHEMERIS_REFUSALS,
    computed_receipt,
    module_state,
    module_status_word,
    not_requested_state,
    unavailable_state as _unavailable_state,
)
from .core.method_status import method_receipt


SCHEMA_VERSION = "0.16.0"

_CLASSICAL_KEYS = tuple(body["key"] for body in CLASSICAL_BODIES)

# The Swiss path is bound once on import, before the bundled file set is
# read; that availability is immutable for the process lifetime.
init_ephemeris()
_HAS_FULL_EPHEMERIS = has_full_ephemeris_files()

# Python distribution and embedded Swiss C-library versions are distinct.
try:
    _PYSWISSEPH_DISTRIBUTION_VERSION: str | None = (
        importlib.metadata.version("pyswisseph")
    )
except importlib.metadata.PackageNotFoundError:
    _PYSWISSEPH_DISTRIBUTION_VERSION = None


def _aspect_participants(
    options,
    bodies_all: list,
    lots: dict,
    angles: dict,
    *,
    angle_aspects_applicable: bool,
) -> list[dict]:
    # 參與者集合由 bodies.effective_participants 決定，
    # 與赤緯相位、反照點同一個 helper；交點鍵取自實際 bodies 紀錄，明示要求的南交點
    # 因此一定在內。
    participants = [
        {
            "key": body["key"],
            "name": body["name"],
            "longitude": body["longitude"],
            "speed_longitude": body["speed_longitude"],
            # 導出的南交點不是獨立 Swiss body，沒有取樣器 → 成相時刻記為 no_motion_model。
            "body_id": BODY_ID_BY_KEY.get(body["key"]),
            "category": body["participant_category"],
        }
        for body in effective_participants(
            bodies_all,
            include_nodes=options.aspect_include_nodes,
            include_outer_planets=options.include_outer_planets,
        )
    ]

    point_groups = (
        (lots or {}, (("fortune", "命運點"), ("spirit", "精神點")), "lot", options.include_lots),
        # 天頂（zenith）是觀測者正上方，不是 MC；全站 MC 稱「中天」。
        (angles, (("asc", "上升點"), ("mc", "中天")), "angle", options.aspect_include_angles and angle_aspects_applicable),
    )
    for values, definitions, category, enabled in point_groups:
        if enabled:
            for key, name in definitions:
                longitude = values.get(key)
                if longitude is None:
                    continue
                participants.append({
                    "key": key, "name": name, "longitude": longitude,
                    "speed_longitude": None, "body_id": None,
                    "category": category,
                })
    return participants


def _module_container(value: Any, *owner_options_requested: bool) -> Any:
    """The one place an unrequested module's container is written.

    ``calculation_dossier.calculation_policy.option_states`` is the single
    authority for whether a module was requested, executed, applicable and
    available.  A container therefore never answers that question: a module
    none of whose owning options was requested is ``null`` (key present), not
    ``{}``, ``[]``, a missing key or a receipt that repeats ``requested: false``.
    A requested module keeps whatever its producer wrote.
    """

    return value if any(owner_options_requested) else None


# Houses, and everything read off the ascendant, need a birth time.
DATE_ONLY_HOUSE_REASON = DATE_ONLY_NO_BIRTH_TIME_REASON


# A JSON-shaped module payload.  Each module is serialised exactly as its
# producer wrote it, key order included, so the stage boundaries below type the
# containers between stages and leave a payload's inner shape to its producer.
JsonObject = dict[str, Any]


@dataclass(frozen=True)
class TimeResolution:
    """Stage 1: the instant and frame the chart is computed for.

    ``input_request`` is the request as sent.  ``request`` is the effective
    request: the representative anchor for approximate_hour and date_only, with
    houses dropped for date_only.  ``trace`` is the chart's one step trace;
    every later stage appends to it in pipeline order.
    """

    input_request: ChartRequest
    request: ChartRequest
    representative_offset_seconds: int
    time_conversion: JsonObject
    # Time facts produced once here and read, not re-derived, downstream: the
    # anchor's own record is time_conversion.input_semantics (event basis, sect
    # basis, approximate-hour sensitivity) and its policy label below (Dossier
    # policy, date_only sensitivity); a non-exact chart's anchor instant
    # and a date_only chart's civil day (resolve_civil_day) bound the event
    # samples and the sensitivity pass.
    anchor_utc: dtmod.datetime | None
    civil_day: JsonObject | None
    # The anchor's policy label (time_utils.representative_policy): the Dossier
    # policy and the date_only sensitivity semantics read it.
    representative_policy: str
    jd_ut: float
    context: ComputationContext
    # The method x frame compatibility table, evaluated once per chart.
    frame_states: dict[str, JsonObject]
    trace: Trace
    # The input files' identity before Swiss opened any of them for this chart.
    ephemeris_input_watch: tuple | None


@dataclass(frozen=True)
class PositionFacts:
    """Stage 2a: bodies, nodes and optional point groups at the instant."""

    body_defs: list[JsonObject]
    # The effective bodies: with the Moon-only topocentric profile, the Moon
    # record here is the topocentric one (parallax_moon keeps both).
    bodies: list[JsonObject]
    parallax_moon: JsonObject | None
    lunar_apsides: JsonObject | None
    node_defs: list[JsonObject]
    nodes: list[JsonObject]
    bodies_all: list[JsonObject]
    bodies_by_key: dict[str, JsonObject]
    longitude_at: Callable[[int, float], float]


@dataclass(frozen=True)
class HouseFacts:
    """Stage 2b: houses, angles and the planet placements read off them.

    Every member exists whether or not houses ran; a module that did not run
    carries its own not_applicable or not_requested state.
    """

    angles: JsonObject
    asc: float | None
    extra_angles: JsonObject | None
    house_division: JsonObject
    planet_in_house: JsonObject
    # The Swiss house division the placements (and Lots) were read against.
    houses: JsonObject | None
    latitude_regime: JsonObject | None


@dataclass(frozen=True)
class EventFacts:
    """Stage 2c: event searches and the state each search wrote about itself."""

    lunar_events: JsonObject
    horizon_events: JsonObject
    availability: dict[str, JsonObject]


@dataclass(frozen=True)
class AstronomicalFacts:
    """Stages 1-2: everything later stages read without recomputing."""

    time: TimeResolution
    positions: PositionFacts
    houses: HouseFacts
    fixed_stars: list[JsonObject]
    events: EventFacts


@dataclass(frozen=True)
class DerivedChart:
    antiscia: Any
    aspects: Any
    declination_aspects: Any
    dodecatemoria: Any
    essential_dignities: Any
    lots: Any
    planetary_hours: Any
    sect: Any
    void_of_course: Any
    lunar_mansions: Any
    solar_phase: Any
    classical_classifications: Any


# Event-search containment boundary.  Every optional search that
# leaves Swiss coverage or trips a Swiss error becomes that module's own
# not_applicable with one of EVENT_SEARCH_REASON_CODES (closed set, defined with
# the receipt vocabulary in core/module_state.py); the core chart is never taken down
# with it, and the Swiss state is reset so the next search in this worker does
# not inherit a segment left open at its edge.
EVENT_SEARCH_SOURCE = "Swiss Ephemeris"


def _prenatal_place(input_request: ChartRequest, context: ComputationContext) -> PrenatalPlace:
    return PrenatalPlace(
        context=context,
        atmosphere=input_request.atmosphere,
        timezone=input_request.timezone,
        precision=input_request.birth_time_precision,
    )


def _event_availability_entry(requested: bool) -> dict:
    """Six-field state of an event search, written where the search runs.

    A refusal from the search replaces it with ``_event_search_refusal``.
    """

    state = (
        computed_receipt(EVENT_SEARCH_SOURCE)
        if requested
        else not_requested_state()
    )
    # The closed status word consumers read, projected once from the six fields.
    return {**state, "status": module_status_word(state)}


def _event_search_refusal(module_label: str, error: Exception, trace: Trace) -> dict:
    if isinstance(error, FullEphemerisRequiredError):
        if error.reason not in SEARCH_EPHEMERIS_REFUSALS:
            raise error
        reason_code, applicable = SEARCH_EPHEMERIS_REFUSALS[error.reason]
        note = (
            "請求日期的核心命盤可計算，但此搜尋會離開完整 "
            "Swiss Ephemeris files 覆蓋範圍；此模組標為不可用。"
            if not applicable
            else "伺服器缺少此搜尋所需的 Swiss Ephemeris 檔；此模組標為不可用。"
        )
    else:
        reason_code, applicable = EVENT_SEARCH_REASON_CODES[2], True
        note = (
            "Swiss Ephemeris 在此搜尋中回報錯誤；此模組標為不可用，"
            "核心命盤不受影響。錯誤內容不對外輸出。"
        )
    reset_swiss_state_for_thread()
    trace.add(module_label, result={"reason_code": reason_code}, note=note)
    # The search was attempted (executed) and produced nothing.  Only leaving
    # the coverage makes it inapplicable to the request; a server fault does not.
    return {
        **module_state(
            requested=True, executed=True, applicable=applicable, available=False,
            reason_code=reason_code,
        ),
        "status": EVENT_MODULE_STATUSES[2],
    }


# With a non-exact birth time an
# event search at one computational anchor reads as the event identity of the
# birth.  The form is three representative samples side by side — the two
# ends of the stated interval and the anchor — each labelled as a sample and
# never merged into one answer.  The civil day is the interval for date_only; the
# stated civil hour of approximate_hour is sampled the same way.
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
# Julian-day values (any key containing "jd_ut") agree within 1e-6 day (86 ms):
# the observed re-solve jitter is at most ~1.4e-7 day and distinct events of one
# kind are at least ~0.9 day apart.  Any other float (eclipse gamma and diameter
# ratios, solver residuals and speeds) agrees within a relative 1e-9: rounding of
# one quantity, never a different value.  `utc_time*` strings are derived from the
# compared JD (millisecond-truncated, so one ULP can flip them) and not compared.
_SAME_EVENT_JD_TOLERANCE_DAYS = 1e-6
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


def _representative_event_sample(
    instant: JsonObject,
    *,
    req: ChartRequest,
    body_defs: list[JsonObject],
    horizon_requested: bool,
    lunar_anchor: JsonObject,
    horizon_anchor: JsonObject,
    horizon_probe_cache: HorizonProbeCache | None,
    sample_trace: Trace,
    trace: Trace,
    place: PrenatalPlace,
) -> tuple[JsonObject, JsonObject]:
    """One interval-end sample's lunar and horizon searches, beside the anchor."""

    role = instant["sample_role"]
    reference = instant["reference_jd_ut"]
    lunar_sample = {**instant, "result_location": SAMPLE_RESULT_LOCATIONS[0]}
    horizon_sample = {**instant, "result_location": SAMPLE_RESULT_LOCATIONS[0]}
    lunar_refusals: dict = {}
    horizon_refusals: dict = {}
    if req.options.include_lunar_phases:
        try:
            lunar_sample.update(compute_primary_phases(reference, sample_trace))
        except (FullEphemerisRequiredError, swe.Error) as error:
            lunar_refusals["lunar_phases"] = _event_search_refusal(
                f"代表性取樣（{role}）：主要月相事件", error, trace
            )
        try:
            attach_prenatal_syzygy(
                lunar_sample, reference, place, sample_trace, with_birth_relation=False
            )
        except (FullEphemerisRequiredError, swe.Error) as error:
            lunar_refusals["prenatal_syzygy"] = _event_search_refusal(
                f"代表性取樣（{role}）：產前朔望", error, trace
            )
    if req.options.include_eclipses:
        try:
            lunar_sample["eclipses"] = compute_previous_eclipses(
                reference, sample_trace
            )
            attach_eclipse_points(
                lunar_sample, reference, place, sample_trace, with_birth_relation=False
            )
        except (FullEphemerisRequiredError, swe.Error) as error:
            lunar_sample.pop("eclipses", None)
            lunar_refusals["eclipses"] = _event_search_refusal(
                f"代表性取樣（{role}）：出生前最近日食／月食", error, trace
            )
    if horizon_requested:
        try:
            horizon_sample["bodies"] = compute_horizon_events(
                body_defs, reference, req.location, req.atmosphere, sample_trace,
                probe_cache=horizon_probe_cache,
            )["bodies"]
        except (FullEphemerisRequiredError, swe.Error) as error:
            horizon_sample["bodies"] = []
            horizon_refusals["rise_set_transits"] = _event_search_refusal(
                f"代表性取樣（{role}）：天體升降與上下中天", error, trace
            )
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

    assert time.anchor_utc is not None  # resolved for every non-exact chart
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
            horizon_requested=horizon_requested,
            lunar_anchor=lunar_events,
            horizon_anchor=horizon_events,
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


def _effective_request(
    input_request: ChartRequest,
) -> tuple[ChartRequest, int, JsonObject | None, dtmod.datetime | None]:
    """The request the chart is computed for, its anchor offset, date anchor
    and, for a non-exact birth time, the anchor's UTC instant."""

    req = input_request
    representative_offset_seconds = 1800
    date_only_anchor = None
    anchor_utc = None
    if input_request.birth_time_precision == "approximate_hour":
        req, representative_offset_seconds, anchor_utc = (
            approximate_hour_representative_request(input_request)
        )
    elif input_request.birth_time_precision == "date_only":
        # 當地正午只是重現性良好的 representative anchor；input receipt 仍保留
        # 00:00:00 日期容器，且 Dossier 明示這不是出生時刻。正午落在時鐘跳躍的
        # 空隙時，錨點改取其後第一個真實存在的瞬間並寫進收據。
        date_only_anchor = resolve_date_only_anchor(
            input_request.datetime, input_request.timezone
        )
        anchor_utc = dtmod.datetime.fromisoformat(
            date_only_anchor["anchor_utc_time"].replace("Z", "+00:00")
        )
        anchor_hour, anchor_minute, anchor_second = (
            int(part) for part in date_only_anchor["anchor_local_time"][11:19].split(":")
        )
        req = input_request.model_copy(
            update={
                "datetime": input_request.datetime.model_copy(
                    update={
                        "hour": anchor_hour,
                        "minute": anchor_minute,
                        "second": float(anchor_second),
                    }
                ),
                "timezone": input_request.timezone.model_copy(
                    update={"fold": date_only_anchor["anchor_fold"]}
                ),
                # Houses need a birth time.  Only the effective
                # request drops them; the input request and its receipt keep
                # what was sent, and the house module states the refusal.
                "options": input_request.options.model_copy(
                    update={"include_houses": False}
                ),
            }
        )
    return req, representative_offset_seconds, date_only_anchor, anchor_utc


def _resolve_time(input_request: ChartRequest) -> TimeResolution:
    req, representative_offset_seconds, date_only_anchor, anchor_utc = (
        _effective_request(input_request)
    )
    # Segment presence is re-checked once per chart, not after every Swiss
    # call, and before the path is bound: Swiss opens the segments there, so a
    # manifest read afterwards could describe files Swiss never saw.
    ephemeris_input_watch = watch_chart_input_files()
    # Bind the verified ephemeris path while holding the Swiss-state lock.  The
    # chart's `finally` releases it (release_ephemeris_for_thread), so every
    # chart binds here once; repeat calls within the same chart are no-ops.
    ensure_ephemeris_initialized_for_thread()
    trace = Trace()
    # The trace receipt hashes the trace and nothing else.  An option whose
    # effect never reached a step (a partile threshold, the perfection search,
    # the opt-in extra angles) changed the response under an unchanged digest,
    # so the options as sent are a step of their own.
    trace.add(
        "請求選項",
        inputs=input_request.options.model_dump(mode="json"),
        note="這次請求送出的全部選項；它們在計算軌跡裡，所以計算軌跡的 SHA-256 也涵蓋選項。",
    )

    if not _HAS_FULL_EPHEMERIS:
        trace.add(
            "⚠ 星曆檔檢查",
            note=(
                "backend/ephe 缺少完整星曆檔（本服務隨映像內附，正常部署不會出現）；"
                "計算將退回 Moshier 半分析模型（精度較低），此結果不應當作完整星曆結果使用。"
            ),
        )

    time_conv = compute_time_conversion(
        req.datetime,
        req.timezone,
        req.location,
        trace,
        # A repeated wall-clock time is the user's to resolve, for an
        # exact time as for an hour.  date_only's anchor carries the fold its
        # own resolution chose, so the effective request never lacks one.
        require_explicit_fold=(
            input_request.birth_time_precision != "date_only"
        ),
        input_semantics=(
            "representative_computational_anchor_not_birth_time"
            if input_request.birth_time_precision == "date_only"
            else representative_semantics_for_offset(representative_offset_seconds)
            if input_request.birth_time_precision == "approximate_hour"
            else "exact_birth_time"
        ),
    )
    jd_ut = time_conv["jd_ut"]

    ctx = ComputationContext(req.computation_mode, req.location)
    ctx.describe(trace, jd_ut)
    # One method x frame compatibility table,
    # evaluated once per chart; every frame-dependent consumer reads it.
    frame_states = method_frame_states(req.computation_mode)
    time_conv["ayanamsa"] = ctx.ayanamsa_value(jd_ut)
    civil_day = None
    if date_only_anchor is not None:
        time_conv["date_only_anchor"] = date_only_anchor
        civil_day = resolve_civil_day(input_request.datetime, input_request.timezone)
        time_conv["civil_day"] = civil_day_receipt(civil_day)

    return TimeResolution(
        input_request=input_request,
        request=req,
        representative_offset_seconds=representative_offset_seconds,
        time_conversion=time_conv,
        anchor_utc=anchor_utc,
        representative_policy=representative_policy(
            time_conv["input_semantics"], date_only_anchor
        ),
        civil_day=civil_day,
        jd_ut=jd_ut,
        context=ctx,
        frame_states=frame_states,
        trace=trace,
        ephemeris_input_watch=ephemeris_input_watch,
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
    # Optional bodies are gated on their own segment's coverage before any
    # Swiss call.  A warm worker would otherwise extrapolate
    # Chiron past seas_18 under the SWIEPH flag while a fresh worker raised.
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
            "method": "moon_only_topocentric_comparison_v1",
            **method_receipt("parallax_moon"),
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
            [dict(body) for body in LUNAR_APSIDES],
            jd_ut,
            ctx,
            req.atmosphere,
            trace,
            physical=False,
            moon_relative=True,
        )
        lunar_apsides = {
            "method": "swiss_lunar_apsides_named_points_v1",
            **method_receipt("lunar_apsides"),
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
    node_defs = [{"id": b["id"], "key": b["key"], "zh": b["zh"]} for b in NODE_BODIES]
    nodes = compute_bodies(
        node_defs,
        jd_ut,
        ctx,
        req.atmosphere,
        trace,
        physical=False,
        moon_relative=True,
    )
    if req.options.include_south_nodes:
        nodes_by_key = {node["key"]: node for node in nodes}
        nodes.extend(
            derive_node_antipode(
                nodes_by_key[north_key],
                key=south_key,
                name=south_name,
                body_id=BODY_ID_BY_KEY[north_key],
                jd_ut=jd_ut,
                ctx=ctx,
                atmosphere=req.atmosphere,
                trace=trace,
            )
            for north_key, south_key, south_name in SOUTH_NODE_DERIVATIONS
        )
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
            withhold_horizontal_coordinates(record, DATE_ONLY_HOUSE_REASON)
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
        "execution_status": status,
        "requested_system_code": req.options.house_system,
        "system_code": None,
        "system_name": None,
        "cusps": [],
        "angles_source": None,
    }
    # The placement answers for itself rather than being told it was not
    # requested: when houses were asked for and the observer has no horizon,
    # the honest receipt is the module's own not_applicable with its own
    # reason code, which is the same premise the angles above now read.
    planet_in_house = (
        compute_planet_house_placements(bodies, None, ctx, trace)
        if req.options.include_houses
        else {
            "method": None,
            "method_status": None,
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
    # Whether an Earth-relative frame exists at all is one premise.  Only the
    # planet placement read it, so a heliocentric chart returned an applicable
    # ascendant beside a refusal that named the same frame.  Every consumer of
    # that frame now reads the central frame table.
    house_frame = time.frame_states["house_division"]
    # Whether houses were asked for is the input request's fact; the
    # effective request drops them for date_only.
    houses_requested = time.input_request.options.include_houses
    if req.options.include_houses and house_frame["applicable"]:
        return _computed_houses(time, bodies)
    unavailable_reason = (
        house_frame["reason_code"]
        if req.options.include_houses
        else DATE_ONLY_HOUSE_REASON
        if houses_requested
        else "house_calculation_not_executed"
    )
    return _unavailable_houses(
        time,
        bodies,
        unavailable_reason=unavailable_reason,
        houses_requested=houses_requested,
    )


# --- Whole-sign places of the nodes and lunar apsides beside the planets' ---
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
            withhold_horizontal_coordinates(star, DATE_ONLY_HOUSE_REASON)
    return stars


def _events(time: TimeResolution, body_defs: list[JsonObject]) -> EventFacts:
    req, jd_ut, trace = time.request, time.jd_ut, time.trace
    lunar_events = {}
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
    place = _prenatal_place(time.input_request, time.context)
    if req.options.include_lunar_phases:
        try:
            lunar_events.update(compute_primary_phases(jd_ut, trace))
        except (FullEphemerisRequiredError, swe.Error) as error:
            event_module_availability["lunar_phases"] = _event_search_refusal(
                "主要月相事件", error, trace
            )
        # The prenatal syzygy needs only its own event, so it survives a
        # refusal of the eight-event phase search.
        try:
            attach_prenatal_syzygy(lunar_events, jd_ut, place, trace)
        except (FullEphemerisRequiredError, swe.Error) as error:
            event_module_availability["prenatal_syzygy"] = _event_search_refusal(
                "產前朔望", error, trace
            )
    if req.options.include_eclipses:
        try:
            lunar_events["eclipses"] = compute_previous_eclipses(jd_ut, trace)
            attach_eclipse_points(lunar_events, jd_ut, place, trace)
        except (FullEphemerisRequiredError, swe.Error) as error:
            lunar_events.pop("eclipses", None)
            lunar_events.pop("eclipses_at_birth", None)
            event_module_availability["eclipses"] = _event_search_refusal(
                "出生前最近日食／月食", error, trace
            )

    horizon_events = {}
    # One chart, one set of Swiss rise/set answers: the anchor search and the
    # representative samples share it (performance only).  None
    # near the end of the bundled ephemeris, where reuse would not be exact.
    horizon_probe_cache: HorizonProbeCache | None = None
    if req.options.include_rise_set_transits:
        horizon_probe_cache = probe_cache_for_chart(body_defs, jd_ut)
        try:
            horizon_events = compute_horizon_events(
                body_defs,
                jd_ut,
                req.location,
                req.atmosphere,
                trace,
                probe_cache=horizon_probe_cache,
            )
        except (FullEphemerisRequiredError, swe.Error) as error:
            event_module_availability["rise_set_transits"] = _event_search_refusal(
                "天體升降與上下中天", error, trace
            )
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


def _antiscia(facts: AstronomicalFacts) -> JsonObject:
    # --- derived_geometry：純幾何轉換，不做「是否成立」的判斷 ---
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    antiscia_frame = time.frame_states["antiscia"]
    if not req.options.include_antiscia:
        return {}
    if not antiscia_frame["applicable"]:
        # The mirror axis is the solstitial axis of
        # date; outside that frame the table refuses instead of mirroring.
        return antiscia_not_applicable(antiscia_frame, trace)
    # Adopted scope: classical seven, plus nodes only when explicitly requested.
    # 同一個參與者 helper：交點鍵取自實際紀錄，含明示要求的南交點。
    antiscia_input = effective_participants(
        positions.bodies_all,
        include_nodes=req.options.antiscia_include_nodes,
        include_outer_planets=False,
    )
    antiscia = compute_antiscia(
        antiscia_input,
        trace,
        ayanamsa=time.time_conversion["ayanamsa"] or 0.0,
    )
    antiscia["scope"] = {
        "included": (
            ["classical_planets", "lunar_nodes"]
            if req.options.antiscia_include_nodes
            else ["classical_planets"]
        ),
        "excluded": (
            ["fixed_stars", "angles", "outer_planets", "lots"]
            + ([] if req.options.antiscia_include_nodes else ["lunar_nodes"])
        ),
        "included_keys": [body["key"] for body in antiscia_input],
        "semantics": (
            "geometric_mirror_coordinates_only_no_relationship_verdict_no_orb"
        ),
        # 七政有 Firmicus II.29 與 Lilly 1647 的逐度見證；交點作為 antiscia
        # 參與者未找到直接見證（方法研究筆記的有界負面結果，未經第三方核對）。
        # 南交點＝北交點＋180°，故 antiscion(南)＝contra-antiscion(北)；照實並列，不去重。
        "historical_method_status": {
            "classical_planets": "attested_firmicus_ii_29_and_lilly_1647",
            "lunar_nodes": "not_established",
        },
    }
    return antiscia


def _sect_and_lots(
    facts: AstronomicalFacts, sect_sun_altitude: float | None
) -> tuple[JsonObject | None, JsonObject]:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    if not req.options.include_lots:
        return None, {}
    if req.options.include_houses:
        sect = determine_sect(
            sect_sun_altitude,
            trace,
            display_center=req.computation_mode.center,
        )
        # The frame table decides; the Lots are placed with the planet
        # half-open cusp rule against the same house division.
        lots_frame = time.frame_states["lots"]
        if not lots_frame["applicable"]:
            return sect, lots_not_applicable(lots_frame, sect, trace)
        if facts.houses.asc is None:
            raise RuntimeError("the ascendant must exist when lots are applicable")
        return sect, compute_lots(
            facts.houses.asc,
            positions.bodies_by_key["sun"]["longitude"],
            positions.bodies_by_key["moon"]["longitude"],
            sect,
            trace,
            houses=facts.houses.houses,
        )
    unavailable = {
        **_unavailable_state("house_calculation_not_executed", requested=True),
        "method": None,
        "method_status": None,
        "execution_status": "not_applicable",
        "source": None,
    }
    trace.add(
        "Sect 與 Lots",
        inputs={"include_lots": True, "include_houses": False},
        result={"execution_status": "not_applicable"},
        note="Lots 依賴 ASC；無宮位模式不以代表時刻產生 ASC 或 Sect 下游判定。",
    )
    return (
        {**unavailable, "is_day": None, "sect_status": None},
        {
            **unavailable,
            "fortune": None,
            "spirit": None,
            "formula_basis": None,
            "sect_status": None,
            "by_sect": None,
        },
    )


def _void_of_course(facts: AstronomicalFacts) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    voc_frame = time.frame_states["void_of_course"]
    if not req.options.include_void_of_course:
        return {}
    if not voc_frame["applicable"]:
        return void_of_course_not_applicable(voc_frame, trace)
    try:
        return evaluate_void_of_course(
            positions.bodies_all, trace, jd_ut=time.jd_ut, longitude_at=positions.longitude_at
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("月空亡(VOC)", error, trace)
        return {
            **voc_receipt_head(),
            # The six state fields only; VOC carries no event status word.
            **{key: value for key, value in refusal.items() if key != "status"},
            "verdict": "not_evaluated",
            "is_void_of_course": None,
            "time_to_sign_exit_hours": None,
            "all_candidates": [],
        }


def _declination_aspects(facts: AstronomicalFacts) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    declination_frame = time.frame_states["declination_aspects"]
    if not req.options.include_declination_aspects:
        return {}
    if not declination_frame["applicable"]:
        return declination_aspects_not_applicable(declination_frame, trace)
    declination_inputs = effective_participants(
        positions.bodies_all,
        include_nodes=req.options.aspect_include_nodes,
        include_outer_planets=req.options.include_outer_planets,
    )
    return compute_declination_aspects(
        declination_inputs,
        req.options.declination_aspect_orb_degrees,
        trace,
        default_orb=DECLINATION_ASPECT_ORB,
        orb_explicit=(
            "declination_aspect_orb_degrees"
            in time.input_request.options.model_fields_set
        ),
        participant_policy=participant_policy_receipt(
            [body for body in declination_inputs if body.get("declination") is not None],
            include_nodes=req.options.aspect_include_nodes,
            include_outer_planets=req.options.include_outer_planets,
        ),
    )


def _aspects(facts: AstronomicalFacts, lots: JsonObject) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    aspects_frame = time.frame_states["aspects"]
    if not req.options.include_aspects:
        return {}
    if not aspects_frame["applicable"]:
        return aspects_not_applicable(aspects_frame, trace)
    # Aspects run only in the frame the angles share (the aspects row of the
    # frame table), so the angles take part whenever the houses ran.
    angle_aspects_applicable = req.options.include_houses
    return compute_aspects(
        _aspect_participants(
            req.options,
            positions.bodies_all,
            lots,
            facts.houses.angles,
            angle_aspects_applicable=angle_aspects_applicable,
        ),
        trace,
        orb_profile_key=req.options.aspect_orb_profile,
        aspect_set_profile_key=req.options.aspect_set_profile,
        orb_scale_percent=req.options.aspect_orb_scale_percent,
        fixed_orb_degrees=req.options.aspect_fixed_orb_degrees,
        angle_orb_degrees=req.options.aspect_angle_orb_degrees,
        angles_requested=req.options.aspect_include_angles,
        angles_applicable=angle_aspects_applicable,
        partile_profile_key=req.options.partile_profile,
        orb_profile_selection_state=orb_profile_selection(req.options),
        include_perfection=req.options.include_aspect_perfection,
        jd_ut=time.jd_ut,
        longitude_at=positions.longitude_at,
    )


def _essential_dignities(
    facts: AstronomicalFacts, sect_sun_altitude: float | None
) -> JsonObject | None:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    # The dignities read the same sect producer as the Lots, classify_sect,
    # rather than restating the >0° rule or the band here.
    dignity_sect = classify_sect(None)
    dignity_sect_basis = "unavailable_date_only"
    if time.input_request.birth_time_precision != "date_only" and time.context.horizon_meaningful:
        dignity_sect = classify_sect(sect_sun_altitude)
        dignity_sect_basis = (
            "sun_center_true_altitude_gt_zero_v1_exact_birth_time"
            if time.input_request.birth_time_precision == "exact"
            else (
                "sun_center_true_altitude_gt_zero_v1_"
                + time.time_conversion["input_semantics"]
            )
        )
    elif not time.context.horizon_meaningful:
        dignity_sect_basis = "unavailable_for_display_center"
    return compute_essential_dignities(
        bodies=[body for body in positions.bodies if body["key"] in _CLASSICAL_KEYS],
        include_domicile_exaltation=req.options.include_domicile_exaltation,
        bounds_profile=req.options.bounds_profile,
        decan_profile=req.options.decan_profile,
        triplicity_profile=req.options.triplicity_profile,
        include_triplicity_comparison=req.options.triplicity_include_research_comparison,
        computation_mode=req.computation_mode,
        sect_basis=dignity_sect_basis,
        trace=trace,
        sect_sun_altitude=sect_sun_altitude,
        sect_classification=dignity_sect,
    )


_ONE_SECOND = dtmod.timedelta(seconds=1)


def _birth_time_interval_spans(time: TimeResolution) -> tuple[str | None, list | None]:
    """The half-open JD(UT) stretches a non-exact birth time may lie in.

    approximate_hour: the stated civil hour's first to last existing second
    (the representative samples' own ends); date_only: every UTC stretch the
    zone labels with the date.
    """

    input_request = time.input_request
    precision = input_request.birth_time_precision
    if precision == "date_only":
        assert time.civil_day is not None  # resolved for every date_only chart
        return "civil_day", [
            (utc_datetime_to_jd_ut(start), utc_datetime_to_jd_ut(end))
            for start, end in time.civil_day["spans"]
        ]
    if precision == "approximate_hour":
        assert time.anchor_utc is not None  # resolved for every non-exact chart
        samples = representative_sample_instants(
            input_request.datetime,
            input_request.timezone,
            precision=precision,
            anchor_utc=time.anchor_utc,
        )
        first, last = samples[0]["reference_utc_time"], samples[-1]["reference_utc_time"]
        start = dtmod.datetime.fromisoformat(first.replace("Z", "+00:00"))
        end = dtmod.datetime.fromisoformat(last.replace("Z", "+00:00")) + _ONE_SECOND
        return "stated_civil_hour", [
            (utc_datetime_to_jd_ut(start), utc_datetime_to_jd_ut(end))
        ]
    return None, None


def _planetary_hours(facts: AstronomicalFacts) -> JsonObject:
    """Planetary day and hours: basic output, computed for every chart."""

    time = facts.time
    req, trace = time.request, time.trace
    frame = time.frame_states["planetary_hours"]
    if not frame["applicable"]:
        return planetary_hours_not_applicable(
            frame["reason_code"], executed=False, trace=trace
        )
    interval, spans = _birth_time_interval_spans(time)
    try:
        return compute_planetary_hours(
            reference_jd_ut=time.jd_ut,
            interval_spans=spans,
            interval=interval,
            time_basis=_event_time_basis(time),
            location=req.location,
            atmosphere=req.atmosphere,
            tz_input=time.input_request.timezone,
            trace=trace,
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("行星日與行星時", error, trace)
        return planetary_hours_not_applicable(
            refusal["reason_code"],
            executed=refusal["executed"],
            applicable=refusal["applicable"],
        )


# --- Twelfth-parts: an optional natal technique, read off emitted positions ---
def _dodecatemoria(facts: AstronomicalFacts, lots: JsonObject) -> JsonObject:
    time = facts.time
    req, trace = time.request, time.trace
    if not req.options.include_dodecatemoria:
        return {}
    frame = time.frame_states["dodecatemoria"]
    if not frame["applicable"]:
        return dodecatemoria_not_applicable(frame, trace)
    planets = effective_participants(
        facts.positions.bodies_all, include_nodes=False, include_outer_planets=False
    )
    angles = facts.houses.angles if facts.houses.angles.get("available") else None
    return compute_dodecatemoria(
        planets=planets,
        angles=angles,
        lots=lots if lots and lots.get("available") else None,
        profile=req.options.dodecatemoria_profile,
        trace=trace,
    )


# --- Planet and place classifications: an optional natal output ---
def _classical_classifications(
    facts: AstronomicalFacts, sect_sun_altitude: float | None
) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    if not time.input_request.options.include_classical_classifications:
        return {}
    frame = time.frame_states["classical_classifications"]
    if not frame["applicable"]:
        return classical_classifications_not_applicable(frame, trace)
    timed = time.input_request.birth_time_precision != "date_only"
    planets = [body for body in positions.bodies if body["key"] in _CLASSICAL_KEYS]
    ids = {item["key"]: item["id"] for item in positions.body_defs}
    # The planets were just computed at this instant from the same files, so
    # their altitudes read nothing the chart has not read already.
    altitudes = (
        {
            body["key"]: geocentric_true_altitude(
                time.jd_ut, time.context, req.atmosphere, ids[body["key"]]
            )
            for body in planets
        }
        if timed
        else None
    )
    module = facts.houses.planet_in_house
    placements = (
        {place["key"]: place["house"] for place in module["placements"]}
        if isinstance(module, dict) and module.get("execution_status") == "computed"
        else None
    )
    result = compute_classical_classifications(
        planets=planets,
        altitudes=altitudes,
        sect=classify_sect(sect_sun_altitude) if timed else None,
        placements=placements,
        trace=trace,
    )
    if result.get("chart_sect") is not None:
        result["chart_sect"].update(_sect_across_stated_hour(time))
    return result


def _sect_across_stated_hour(time: TimeResolution) -> JsonObject:
    """Day or night at each representative sample of a stated hour.

    The classifications follow one sect, read at the representative instant;
    when the Sun crosses the horizon inside the stated hour the sect, and so
    sect membership, halb and hayyiz, change within it.  Only the sect is
    probed: it is the one input of the module that flips as a whole.
    """

    input_request = time.input_request
    if input_request.birth_time_precision != "approximate_hour":
        return {"across_stated_hour": None, "sample_is_day": None}
    assert time.anchor_utc is not None  # resolved for every non-exact chart
    instants = representative_sample_instants(
        input_request.datetime,
        input_request.timezone,
        precision="approximate_hour",
        anchor_utc=time.anchor_utc,
    )
    try:
        sample_is_day = [
            classify_sect(
                geocentric_sun_true_altitude(
                    instant["reference_jd_ut"], time.context, time.request.atmosphere
                )
            )["is_day"]
            for instant in instants
        ]
    except FullEphemerisRequiredError:
        return {"across_stated_hour": None, "sample_is_day": None}
    state = (
        SAME_AT_ALL_SAMPLES if len(set(sample_is_day)) == 1 else DIFFERS_BETWEEN_SAMPLES
    )
    return {"across_stated_hour": state, "sample_is_day": sample_is_day}


def _lunar_mansions(facts: AstronomicalFacts) -> JsonObject:
    """The Moon's mansion; for a non-exact birth time, every mansion it is in."""

    time, positions = facts.time, facts.positions
    trace = time.trace
    if not time.input_request.options.include_lunar_mansions:
        return {}
    frame = time.frame_states["lunar_mansions"]
    if not frame["applicable"]:
        return lunar_mansions_not_applicable(frame, trace)
    interval, spans = _birth_time_interval_spans(time)
    try:
        moon_at_ends = (
            None
            if spans is None
            else [
                (
                    positions.longitude_at(swe.MOON, start),
                    positions.longitude_at(swe.MOON, end),
                )
                for start, end in spans
            ]
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("月宿", error, trace)
        return lunar_mansions_unavailable(refusal)
    return compute_lunar_mansions(
        positions.bodies,
        trace,
        time_basis=_event_time_basis(time),
        interval=interval,
        interval_moon_longitudes=moon_at_ends,
    )


def _solar_phase(facts: AstronomicalFacts) -> JsonObject:
    """Each planet's and the Moon's distance from the Sun and its band."""

    time, positions = facts.time, facts.positions
    options = time.input_request.options
    if not options.include_solar_phase:
        return {}
    frame = time.frame_states["solar_phase"]
    if not frame["applicable"]:
        return solar_phase_not_applicable(frame, time.trace)
    flags = time.context.base_flags
    # The effective Moon: topocentric under the Moon-only profile.
    moon_topocentric = (
        time.request.options.moon_position_profile == "moon_only_topocentric_v1"
        or time.request.computation_mode.center == "topocentric"
    )
    moon_flags = flags | swe.FLG_TOPOCTR if moon_topocentric else flags
    interval, spans = _birth_time_interval_spans(time)
    try:
        return compute_solar_phase(
            positions.bodies,
            time.trace,
            profile=options.solar_phase_profile,
            disc_cazimi=options.solar_phase_disc_cazimi,
            time_basis=_event_time_basis(time),
            moon_center="topocentric" if moon_topocentric else "geocentric",
            jd_ut=time.jd_ut,
            instant_of=lambda jd: civil_instant(jd, time.input_request.timezone),
            sample=make_ecliptic_sampler(flags, moon_flags),
            sun_flags=flags,
            interval=interval,
            interval_spans=spans,
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("焦傷與光束下", error, time.trace)
        return solar_phase_unavailable(refusal)


def _derived_chart(facts: AstronomicalFacts) -> DerivedChart:
    time = facts.time
    req = time.request
    antiscia = _antiscia(facts)
    # --- derived_methods：帶技法假設的判斷結果，每項皆標註具名 method ---
    # 日夜盤只有一個產生器：地心太陽中心真高度，與顯示中心無關；
    # Lots 與尊貴元件的 sect 共用這個值。heliocentric／barycentric 為 None。
    sect_sun_altitude = geocentric_sun_true_altitude(
        time.jd_ut, time.context, req.atmosphere
    )
    sect, lots = _sect_and_lots(facts, sect_sun_altitude)
    void_of_course = _void_of_course(facts)
    declination_aspects = _declination_aspects(facts)
    aspects = _aspects(facts, lots)
    essential_dignities = _essential_dignities(facts, sect_sun_altitude)
    planetary_hours = _planetary_hours(facts)
    dodecatemoria = _dodecatemoria(facts, lots)
    lunar_mansions = _lunar_mansions(facts)
    solar_phase = _solar_phase(facts)
    classical_classifications = _classical_classifications(facts, sect_sun_altitude)

    if time.input_request.birth_time_precision == "date_only":
        for requested, result in (
            (req.options.include_void_of_course, void_of_course),
            (req.options.include_aspects, aspects),
            (req.options.include_declination_aspects, declination_aspects),
            (essential_dignities is not None, essential_dignities),
            (req.options.include_dodecatemoria, dodecatemoria),
            (req.options.include_classical_classifications, classical_classifications),
        ):
            if requested and result:
                result["time_basis"] = (
                    "representative_computational_anchor_not_birth_time"
                )
        # Whether these were revisited across the civil day is the
        # sensitivity ledger's fact (calculation_dossier.birth_time.
        # sensitivity_coverage), not a second flag written onto each result.
        if facts.positions.lunar_apsides is not None:
            facts.positions.lunar_apsides["time_basis"] = (
                "representative_computational_anchor_not_birth_time"
            )

    return DerivedChart(
        antiscia=antiscia,
        aspects=aspects,
        declination_aspects=declination_aspects,
        dodecatemoria=dodecatemoria,
        essential_dignities=essential_dignities,
        lots=lots,
        planetary_hours=planetary_hours,
        sect=sect,
        void_of_course=void_of_course,
        lunar_mansions=lunar_mansions,
        solar_phase=solar_phase,
        classical_classifications=classical_classifications,
    )


def _library_info() -> JsonObject:
    return {
        "pyswisseph_distribution_version": _PYSWISSEPH_DISTRIBUTION_VERSION,
        "swiss_ephemeris_library_version": swe.version,
        # IANA database version is a calculation input and must be receipted.
        "tz_database": dict(TZ_DATABASE),
        # What the two version numbers and the tz database are: register entry
        # library_info.
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
        # Owned by include_houses like the house modules; an
        # unrequested chart has no angles receipt repeating `requested: false`.
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
    # Ownership follows the options as sent (input_request), which is
    # also what option_states reports; the effective request may drop houses
    # for a date-only birth while the house module states its refusal.
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
                representative_bodies=positions.bodies,
                representative_houses=facts.houses.houses,
                representative_placements=facts.houses.planet_in_house,
                representative_sect=methods.sect,
                representative_lots=methods.lots,
                representative_void_of_course=methods.void_of_course,
                representative_offset_seconds=time.representative_offset_seconds,
                representative_semantics=time.time_conversion["input_semantics"],
                representative_dodecatemoria=methods.dodecatemoria,
            )
        elif input_request.birth_time_precision == "date_only":
            assert time.civil_day is not None  # resolved for every date_only chart
            birth_time_sensitivity = build_date_only_sensitivity(
                request=input_request,
                body_defs=positions.body_defs,
                node_defs=positions.node_defs,
                representative_bodies=positions.bodies,
                representative_nodes=positions.nodes,
                civil_day=time.civil_day,
                representative_local_time=(
                    time.time_conversion["date_only_anchor"]["anchor_local_time"]
                ),
                representative_semantics=time.representative_policy,
                representative_dodecatemoria=methods.dodecatemoria,
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
    """Set every ``used_full_ephemeris: true`` under ``node`` to false."""

    if isinstance(node, dict):
        for key, value in node.items():
            if key == "used_full_ephemeris" and value is True:
                node[key] = False
            else:
                _withdraw_full_ephemeris_claims(value)
    elif isinstance(node, list):
        for item in node:
            _withdraw_full_ephemeris_claims(item)


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
        request=time.input_request,
        effective_request=time.request,
        time_conversion=time.time_conversion,
        representative_policy=time.representative_policy,
        context=time.context,
        library_info=library_info,
        astronomical_data=astronomical_data,
        derived_methods=derived_methods,
        derived_geometry=derived_geometry,
        trace_steps=trace_steps,
        full_ephemeris_files_available=_HAS_FULL_EPHEMERIS,
        input_files_unchanged_during_chart=input_files_unchanged,
        build_identity=build_identity,
        birth_time_sensitivity=birth_time_sensitivity,
        event_module_availability=event_module_availability,
        latitude_regime=facts.houses.latitude_regime,
        method_frame_states=time.frame_states,
    )

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


def compute_chart_response(req: ChartRequest, *, build_identity: JsonObject) -> JsonObject:
    """Every stage in order, for one request; the caller holds the Swiss line."""

    time = _resolve_time(req)
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
