"""The typed results the chart pipeline's stages hand each other."""

from dataclasses import dataclass
import datetime as dtmod
from collections.abc import Callable
from typing import Any

from .schema_chart import ChartRequest
from .core.trace import Trace
from .core.computation_mode import ComputationContext
from .core.frame_compatibility import FrameState
from .core.module_state import EventModuleState


def _module_container[T](value: T, *owner_options_requested: bool) -> T | None:
    """The one place an unrequested module's container is written.

    ``calculation_dossier.calculation_policy.option_states`` is the single
    authority for whether a module was requested, executed, applicable and
    available.  A container therefore never answers that question: a module
    none of whose owning options was requested is ``null`` (key present), not
    ``{}``, ``[]``, a missing key or a receipt that repeats ``requested: false``.
    A requested module keeps whatever its producer wrote.
    """

    return value if any(owner_options_requested) else None


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
    # Produced once here, read (not re-derived) downstream: a non-exact chart's
    # anchor instant and a date_only chart's civil day bound the event samples
    # and the sensitivity pass.
    anchor_utc: dtmod.datetime | None
    civil_day: JsonObject | None
    # Read by the Dossier policy and the date_only sensitivity semantics.
    representative_policy: str
    jd_ut: float
    context: ComputationContext
    # The method x frame compatibility table, evaluated once per chart.
    frame_states: dict[str, FrameState]
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
    availability: dict[str, EventModuleState]


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
    """Stage 3: derived geometry and methods, each as its producer wrote it."""

    antiscia: JsonObject
    aspects: JsonObject
    declination_aspects: JsonObject
    dodecatemoria: JsonObject
    essential_dignities: JsonObject | None
    lots: JsonObject
    planetary_hours: JsonObject
    sect: JsonObject | None
    void_of_course: JsonObject
    lunar_mansions: JsonObject
    solar_phase: JsonObject
    motion_states: JsonObject
    classical_classifications: JsonObject


@dataclass(frozen=True)
class ChartSections:
    """Stage 5's response sections, as the calculation dossier reads them.

    The same objects the response carries, not copies: the dossier is a
    projection of them.
    """

    astronomical_data: JsonObject
    derived_geometry: JsonObject
    derived_methods: JsonObject
    birth_time_sensitivity: JsonObject
    event_module_availability: dict[str, EventModuleState]
