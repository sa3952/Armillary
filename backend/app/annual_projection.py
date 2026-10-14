"""Views of the one annual response.

`detailed` is the response `annual_pipeline.compute_annual_response` builds,
unchanged.  `page` is derived from it by pure functions: the module heads and
dossier narrowed to a closed list of kept paths (the convention of
`response_projection`), plus `annual_timeline`, the lanes, segments and events
a time-lord page draws.  Nothing here calculates a boundary, a sign or a lord:
every segment value is copied from the detailed row its `ref` points at
(a JSON pointer), and the three `flags` are named readings of copied fields.

Lanes are generic.  A period technique (rows with `start`, an end and an
optional `level_2` list, sampled as `periods` or `candidates[].periods`) is
one `_PeriodLane` per level; a later technique adds its lanes to `LANES`
without touching the builders.

tests/backend/test_annual_projection.py holds that every copied value equals
the detailed value at its `ref`, that every kept path resolves in a fixture
response and that the page stays inside its size budget.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .core.birth_time_sensitivity import (
    DIFFERS_BETWEEN_SAMPLES,
    NOT_REQUESTED_STATE,
    SAME_AT_ALL_SAMPLES,
)
from .core import monthly_profections
from .core.module_state import MODULE_STATUSES
from .response_projection import (
    DEFAULT_CHART_PROJECTION,
    _keep,
    _kept_tree,
    project_chart_response,
)
from .schemas import ChartProjection

# The same default as /api/chart: the page view, with the trace by name.
DEFAULT_ANNUAL_PROJECTION: ChartProjection = DEFAULT_CHART_PROJECTION

SEGMENTS_BASES = ("single_instant", "representative_anchor_sample", "each_sample")
EVENT_KINDS = ("year_start", "period_start")
_COMPUTED = MODULE_STATUSES[1]
_STATE = "status,requested,applicable,available,reason_code"
# A segment is drawn to the day: its boundaries are the birth-place dates.
# The Julian days and UTC labels they were dated from are in `detailed`.
_YEAR_INSTANT = "{jd_ut,utc_time,local_date,local_time,utc_offset}"

ANNUAL_PAGE_KEPT_PATHS: tuple[str, ...] = (
    "schema_version",
    "output_contract",
    "requested_annual",
    "computation_mode",
    "birth_time_precision",
    "natal_anchor.{jd_ut,utc_time,time_basis,sun.longitude_deg}",
    "natal_anchor.ascendant.{status,reason_code,sign,longitude_deg}",
    "natal_anchor.sect.{is_day,sect_status,in_near_horizon_band,named_boundary_disagreement}",
    "year_boundary.{definition,completed_years,year_of_life,start_kind,start_status,end_status,"
    "solar_return_profile}",
    f"year_boundary.{{start,end}}.{_YEAR_INSTANT}",
    "year_boundary.samples[].{sample_role,start_status,end_status}",
    f"year_boundary.samples[].{{start,end}}.{_YEAR_INSTANT}",
    "year_boundaries.{definition,window,sample_role,profection_status,profection_reason_code}",
    # Each year's dates; its profection is the annual_profection lane, and the
    # minute-level instants are the requested year's (year_boundary).
    "year_boundaries.years[].{completed_years,end_status,start.local_date,end.local_date}",
    # Module heads: state, method identity, the options echoed, sensitivity.
    # The period rows themselves are annual_timeline.segments.
    f"annual_methods.annual_profection.{{{_STATE},profile,method_status,method_provenance,"
    "source_ref,completed_years,year_of_life,natal_ascendant_sign,offset_signs,profected_sign,"
    "profected_place,sensitivity_state,candidates,lord.{applicable,reason_code,body_key,table}}",
    f"annual_methods.firdaria.{{{_STATE},profile,nocturnal_node_profile,"
    "nocturnal_node_profile_input,nocturnal_node_profile_applies,method_status,"
    "method_provenance,source_ref,scope,lifetime_window,cycle_index,sensitivity_state,"
    "year_model.{fractional_year_rule,return_profile},sect.{is_day,sect_status,"
    "sect_in_near_horizon_band}}",
    "annual_methods.firdaria.candidates[].{sample_role,is_day}",
    f"annual_methods.zodiacal_releasing.{{{_STATE},profile,period_table_profile,year_model,"
    "levels_emitted,method_status,method_provenance,source_ref,scope,lifetime_window,"
    "fortune_spirit_same_sign,sensitivity_state,lords.{applicable,reason_code,table}}",
    "annual_methods.zodiacal_releasing.releases[].{releasing_from,start_sign,"
    "start_lot_longitude_deg,start_sign_differs_under_other_sect,comparison_start_sign}",
    "annual_methods.zodiacal_releasing.candidates[].{sample_role,fortune_sign,spirit_sign}",
    f"annual_methods.decennials.{{{_STATE},profile,start_profile,order_rule,equal_longitude_rule,"
    "year_model,minor_years_ref,levels_emitted,method_status,method_provenance,source_ref,scope,"
    "lifetime_window,start_planet,order,start_differs_under_other_sect,comparison_start_planet,"
    "sensitivity_state}",
    f"annual_methods.decennials.sect_light_triplicity_lords.{{{_STATE},source_ref,table,"
    "sect_light,sect_light_sign,element,lords,comparison_under_other_sect,periods,"
    "periods_reason_code,sensitivity_state}",
    "annual_methods.decennials.candidates[].{sample_role,is_day,start_planet,order}",
    f"annual_methods.monthly_profection.{{{_STATE},profile,profile_input,profile_provenance,"
    "other_profiles,method_status,method_provenance,"
    "source_ref,completed_years,year_of_life,month_model,natal_ascendant_sign,"
    "year_sign,sensitivity_state,lords.{applicable,reason_code,table}}",
    "annual_methods.monthly_profection.candidates[].{sample_role,natal_ascendant_sign,year_sign}",
    f"natal_lots.{{{_STATE},method_status,sect_status,sect_applied,sect_in_near_horizon_band,"
    "house_system_code,sensitivity_state,samples}",
    "natal_lots.lots[].{lot_method_id,source_ref,longitude,sign,house,same_value_both_candidates}",
    # The solar-return chart's head; its `chart` is the /api/chart page view of
    # the detailed chart (project_annual_response), not narrowed here.
    "solar_return_chart.{status,reason_code,method_status,method_provenance,source_ref,definition,"
    "solar_return_profile,completed_years,year_of_life,instant,location,relocation_note,"
    "house_system_code,house_system_note,zodiac_note,chart_options,chart_time_basis,"
    "natal_house_system_code,natal_house_of_return_ascendant,return_planets_in_natal_houses,"
    "profected_sign,profected_sign_ref}",
    "calculation_dossier.annual_policy.{year_boundary_definition,fractional_year_rule,"
    "solar_return_profile,house_system_code,period_display_precision,representative_samples,"
    "merge_policy,local_dates}",
    "calculation_dossier.warnings",
    "calculation_dossier.privacy",
    "calculation_dossier.build_identity",
    "calculation_dossier.trace_receipt.{step_count,python_json_serialization_sha256}",
    "calculation_dossier.method_source_register.{register_id,version,sha256,digest_semantics}",
)

_PAGE_TREE = _kept_tree(ANNUAL_PAGE_KEPT_PATHS)


# ── lanes ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Source:
    """One list of rows a lane reads, with where it sits and whose sample it is."""

    ref: str
    rows: list[dict]
    sample_role: str | None


@dataclass(frozen=True)
class PeriodLane:
    """A level of a period technique.

    `lists(module, base)` returns the level-1 row lists with the basis they
    stand on; level 2 reads each level-1 row's `level_2`.  `flags(row)` names
    the flags a row carries (loosing_of_the_bond, truncated, node_period).
    """

    lane_id: str
    technique: str
    level: int
    label_kind: str
    label_field: str
    lord_field: str | None
    end_field: str
    detail_fields: tuple[str, ...]
    lists: Callable[[dict, str], tuple[list[_Source], str]]
    flags: Callable[[dict], list[str]] = field(default=lambda row: [])
    unit: str | None = None
    # When what one segment measures depends on the module's `profile`: the
    # unit of each profile (`unit` is then the default profile's).
    unit_by_profile: dict[str, str] | None = None
    # A level-1 lane whose rows each lie inside a segment of another
    # technique's lane: that lane, and the row field holding the segment's id.
    under_lane_id: str | None = None
    under_field: str | None = None

    @property
    def parent_lane_id(self) -> str | None:
        if self.level == 1:
            return self.under_lane_id
        return self.lane_id.removesuffix(f"_level_{self.level}") + "_level_1"


def plain_period_lists(module: dict, base: str) -> tuple[list[_Source], str]:
    """`periods` when the samples agree (or there is one), else each sample's."""

    if module["periods"] is not None:
        basis = SEGMENTS_BASES[0] if module["candidates"] is None else SEGMENTS_BASES[1]
        return [_Source(f"{base}/periods", module["periods"], None)], basis
    return [
        _Source(f"{base}/candidates/{index}/periods", candidate["periods"], candidate["sample_role"])
        for index, candidate in enumerate(module["candidates"])
    ], SEGMENTS_BASES[2]


def _releasing_lists(lot: str) -> Callable[[dict, str], tuple[list[_Source], str]]:
    def lists(module: dict, base: str) -> tuple[list[_Source], str]:
        def pick(releases: list[dict], prefix: str, role: str | None) -> _Source:
            index = next(i for i, release in enumerate(releases) if release["releasing_from"] == lot)
            return _Source(f"{prefix}/releases/{index}/periods", releases[index]["periods"], role)

        if module["releases"] is not None:
            basis = SEGMENTS_BASES[0] if module["candidates"] is None else SEGMENTS_BASES[1]
            return [pick(module["releases"], base, None)], basis
        return [
            pick(candidate["releases"], f"{base}/candidates/{index}", candidate["sample_role"])
            for index, candidate in enumerate(module["candidates"])
        ], SEGMENTS_BASES[2]

    return lists


def _firdaria_flags(row: dict) -> list[str]:
    return ["node_period"] if row.get("level_2_reason_code") == "node_period_not_subdivided" else []


def _releasing_flags(row: dict) -> list[str]:
    return [
        flag for flag, held in (
            ("loosing_of_the_bond", row["entry_kind"] == "loosing_of_the_bond"),
            ("truncated", row["truncated"]),
        ) if held
    ]


_FIRDARIA_DETAIL = {1: ("start_year", "end_year"), 2: ()}
_RELEASING_DETAIL = (
    "nominal_units", "effective_units", "position_from_fortune", "angularity_from_fortune",
    "position_from_start_lot",
)


def _firdaria_lane(level: int) -> PeriodLane:
    return PeriodLane(
        lane_id=f"firdaria_level_{level}", technique="firdaria", level=level,
        label_kind="body",
        label_field="level_1_lord" if level == 1 else "level_2_partner", lord_field=None,
        end_field="end", detail_fields=_FIRDARIA_DETAIL[level], lists=plain_period_lists,
        flags=_firdaria_flags,
    )


def _releasing_lane(lot: str, level: int) -> PeriodLane:
    return PeriodLane(
        lane_id=f"zr_{lot}_level_{level}", technique="zodiacal_releasing", level=level,
        label_kind="sign", label_field="sign", lord_field="domicile_lord",
        end_field="effective_end", detail_fields=_RELEASING_DETAIL,
        lists=_releasing_lists(lot), flags=_releasing_flags,
        unit="zr_year" if level == 1 else "zr_month",
    )


_DECENNIALS_DETAIL = {1: ("months", "cycle_index", "position_in_order"), 2: ("months",)}


def _decennials_lane(level: int) -> PeriodLane:
    return PeriodLane(
        lane_id=f"decennials_level_{level}", technique="decennials", level=level,
        label_kind="body", label_field="lord", lord_field=None, end_field="end",
        detail_fields=_DECENNIALS_DETAIL[level], lists=plain_period_lists,
    )


PROFECTION_LANE_ID = "annual_profection"
# The monthly profection: one lane, each month under its year's profection
# segment (`Y<N>`), drawn right after the profection lane.
MONTHLY_PROFECTION_LANE = PeriodLane(
    lane_id="monthly_profection", technique="monthly_profection", level=1,
    label_kind="sign", label_field="sign", lord_field="domicile_lord", end_field="end",
    detail_fields=("completed_years", "month_of_year", "profected_place"),
    lists=plain_period_lists,
    unit=monthly_profections.MONTH_UNIT[monthly_profections.DEFAULT_PROFILE],
    unit_by_profile=monthly_profections.MONTH_UNIT,
    under_lane_id=PROFECTION_LANE_ID, under_field="year_period_id",
)
LANES: tuple[PeriodLane, ...] = (
    MONTHLY_PROFECTION_LANE,
    _firdaria_lane(1), _firdaria_lane(2),
    _releasing_lane("fortune", 1), _releasing_lane("fortune", 2),
    _releasing_lane("spirit", 1), _releasing_lane("spirit", 2),
    _decennials_lane(1), _decennials_lane(2),
)
LANE_IDS: tuple[str, ...] = (PROFECTION_LANE_ID, *(lane.lane_id for lane in LANES))


# ── segments ────────────────────────────────────────────────────────────────


def _boundary(
    instant: dict | None, status: str | None = None
) -> tuple[str | None, str | None, float | None]:
    """(local date, status, JD) of a boundary; `status` is the record's own
    word for an instant that carries none (a year boundary's start_status)."""

    if instant is None:
        return None, status, None
    return instant["local_date"], instant.get("status", status), instant["jd_ut"]


def _dated(segment: dict, start: tuple, end: tuple) -> dict:
    """Put a segment's two boundaries on it: dates, and one status, the first
    boundary's that is not computed."""

    segment["start"], segment["end"] = start[0], end[0]
    segment["status"] = next((b[1] for b in (start, end) if b[1] != "computed"), "computed")
    # Ordering key for the events, not emitted.
    segment[_START_JD] = start[2]
    return segment


_START_JD = "\0start_jd"


def _segment_id(key: str, role: str | None) -> str:
    return key + (f"@{role}" if role else "")


def _period_segments(lane: PeriodLane, module: dict) -> tuple[list[dict], str]:
    sources, basis = lane.lists(module, f"/annual_methods/{lane.technique}")
    segments = []
    for source in sources:
        for index, row in enumerate(source.rows):
            if lane.level == 1:
                under = None if lane.under_field is None else _segment_id(
                    row[lane.under_field], source.sample_role)
                items: list[tuple[str, dict, str | None]] = [(f"{source.ref}/{index}", row, under)]
            else:
                items = [
                    (f"{source.ref}/{index}/level_2/{child_index}", child,
                     _segment_id(row["period_id"], source.sample_role))
                    for child_index, child in enumerate(row["level_2"] or ())
                ]
            for _ref, item, parent in items:
                segments.append(_dated({
                    "id": _segment_id(item["period_id"], source.sample_role),
                    "sample_role": source.sample_role,
                    "parent_id": parent,
                    "label_key": item[lane.label_field],
                    "lord_key": None if lane.lord_field is None else item[lane.lord_field],
                    "flags": lane.flags(item),
                    "detail": {key: item[key] for key in lane.detail_fields},
                }, _boundary(item["start"]), _boundary(item[lane.end_field])))
    return segments, basis


def _profection_segment(sign, lord, role, start, end, detail) -> dict:
    return _dated({
        "id": _segment_id(f"Y{detail['completed_years']}", role),
        "sample_role": role,
        "parent_id": None,
        "label_key": sign,
        "lord_key": lord,
        "flags": [],
        "detail": detail,
    }, start, end)


def _profection_segments(response: dict) -> tuple[list[dict], str, str]:
    """The profection lane: one segment a return year.

    From `year_boundaries` when the request listed them (the lifetime lane),
    else the requested year from `annual_profection` and `year_boundary`.
    """

    exact = response["birth_time_precision"] == "exact"
    years = (response.get("year_boundaries") or {}).get("years")
    segments: list[dict] = []
    if years is not None:
        differs = False
        for index, year in enumerate(years):
            entries = (
                [(year["profection_sign"], year["year_lord"], None)]
                if year["profection_sign"] is not None
                else [
                    (cand["profection_sign"], cand["year_lord"], cand["sample_role"])
                    for cand in year["candidates"] or ()
                ]
            )
            differs = differs or year["candidates"] is not None
            for sign, lord, role in entries:
                segments.append(_profection_segment(
                    sign, lord, role, _boundary(year["start"]),
                    _boundary(year["end"], year["end_status"]),
                    {"completed_years": year["completed_years"],
                     "profected_place": year["profected_place"]},
                ))
        basis = SEGMENTS_BASES[0] if exact else SEGMENTS_BASES[2 if differs else 1]
        return segments, basis, "year_boundaries"
    module = response["annual_methods"]["annual_profection"]
    boundary = response["year_boundary"]
    detail = {key: module[key] for key in ("completed_years", "profected_place")}
    if module["profected_sign"] is not None:
        segments.append(_profection_segment(
            module["profected_sign"], module["lord"]["body_key"], None,
            _boundary(boundary["start"], boundary["start_status"]),
            _boundary(boundary["end"], boundary["end_status"]), detail,
        ))
        basis = SEGMENTS_BASES[0] if exact else SEGMENTS_BASES[1]
    else:
        samples = {sample["sample_role"]: sample for sample in boundary["samples"]}
        for candidate in module["candidates"]:
            sample = samples[candidate["sample_role"]]
            segments.append(_profection_segment(
                candidate["profected_sign"], candidate["lord_body_key"],
                candidate["sample_role"], _boundary(sample["start"], sample["start_status"]),
                _boundary(sample["end"], sample["end_status"]),
                {**detail, "profected_place": candidate["profected_place"]},
            ))
        basis = SEGMENTS_BASES[2]
    return segments, basis, "annual_methods.annual_profection"


# ── the timeline ────────────────────────────────────────────────────────────


def _status(module: dict | None) -> tuple[str, str | None]:
    if module is None:
        return MODULE_STATUSES[0], None
    return module["status"], module["reason_code"]


def _within(jd: float | None, start: float | None, end: float | None) -> bool:
    return jd is not None and start is not None and jd >= start and (end is None or jd < end)


def annual_timeline(response: dict) -> dict:
    """The lanes, their segments and the year's events of one detailed response."""

    boundary = response["year_boundary"]
    start = _boundary(boundary["start"], boundary["start_status"])
    end = _boundary(boundary["end"], boundary["end_status"])
    window = {"year_boundary_ref": "year_boundary", "start": start[0], "end": end[0],
              "end_status": end[1]}
    precision = response["calculation_dossier"]["annual_policy"]["period_display_precision"]
    methods = response["annual_methods"]
    lanes = []

    def lane_entry(lane_id, technique, level, label_kind, unit, parent, module, built):
        status, reason = _status(module)
        computed = status == _COMPUTED
        return {
            "lane_id": lane_id,
            "technique": technique,
            "level": level,
            "status": status,
            "reason_code": reason,
            "sensitivity_state": None if module is None else module["sensitivity_state"],
            "source_path": built[2] if computed else None,
            "segments_basis": built[1] if computed else None,
            "label_kind": label_kind,
            "unit": unit,
            "parent_lane_id": parent,
            "display_precision": precision,
            "segments": built[0] if computed else [],
        }

    profection = methods["annual_profection"]
    computed = profection is not None and profection["status"] == _COMPUTED
    lanes.append(lane_entry(
        PROFECTION_LANE_ID, "annual_profection", 1, "sign", "return_year", None, profection,
        _profection_segments(response) if computed else ([], None, None),
    ))
    for lane in LANES:
        module = methods.get(lane.technique)
        computed = module is not None and module["status"] == _COMPUTED
        built = (*_period_segments(lane, module), f"annual_methods.{lane.technique}") if computed \
            else ([], None, None)
        unit = lane.unit
        if lane.unit_by_profile is not None and module is not None:
            unit = lane.unit_by_profile[module["profile"]]
        # A month names its year's segment id even when this response did not
        # compute the profection lane: a client that asked only for the months
        # (and the level-2 periods) attaches them to the year an earlier
        # response listed.
        lanes.append(lane_entry(
            lane.lane_id, lane.technique, lane.level, lane.label_kind, unit,
            lane.parent_lane_id, module, built,
        ))
    start_jd, end_jd = start[2], end[2]
    order = {lane["lane_id"]: index for index, lane in enumerate(lanes)}
    starts = sorted(
        (
            (segment[_START_JD], order[lane["lane_id"]], lane["lane_id"], segment)
            for lane in lanes for segment in lane["segments"]
            if _within(segment[_START_JD], start_jd, end_jd)
        ),
        key=lambda item: item[:2],
    )
    events = [{"event_kind": EVENT_KINDS[0], "lane_id": None, "segment_id": None,
               "date": window["start"]}]
    events.extend(
        {"event_kind": EVENT_KINDS[1], "lane_id": lane_id, "segment_id": segment["id"],
         "date": segment["start"]}
        for _, _, lane_id, segment in starts
    )
    for lane in lanes:
        for segment in lane["segments"]:
            del segment[_START_JD]
    states = [lane["sensitivity_state"] for lane in lanes if lane["status"] == _COMPUTED]
    if DIFFERS_BETWEEN_SAMPLES in states:
        sensitivity = DIFFERS_BETWEEN_SAMPLES
    elif SAME_AT_ALL_SAMPLES in states:
        sensitivity = SAME_AT_ALL_SAMPLES
    else:
        sensitivity = NOT_REQUESTED_STATE
    return {
        "window": window,
        "lanes": lanes,
        "events": events,
        "sensitivity_state": sensitivity,
        "interpretation": None,
    }


def project_annual_response(response: dict[str, Any], projection: str) -> dict[str, Any]:
    """Derive the requested view from the one detailed annual response."""

    if projection == "detailed":
        return response
    if projection == "page":
        page = _keep(response, _PAGE_TREE)
        solar_return_chart = response.get("solar_return_chart")
        if solar_return_chart is not None:
            chart = solar_return_chart["chart"]
            page["solar_return_chart"]["chart"] = (
                None if chart is None else project_chart_response(chart, "page")
            )
        return {
            "schema_version": page["schema_version"],
            "projection": {
                "name": "page",
                "derived_from": "detailed",
                # The rule, not the list: the kept paths are
                # ANNUAL_PAGE_KEPT_PATHS, printed in the output contract.
                "kept": "module_heads_and_the_annual_timeline",
                "verification_detail": "projection=detailed",
            },
            **{key: value for key, value in page.items() if key != "schema_version"},
            "annual_timeline": annual_timeline(response),
        }
    raise ValueError(f"unsupported annual projection: {projection}")
