"""The flagged annual route: one natal anchor, one year boundary, the techniques.

Stages, in order (the caller holds the Swiss line):

1. the natal anchor: ``chart_pipeline.compute_natal_anchor`` on a ChartRequest
   built from the annual request (whole-sign houses, Lots on, aspects off), so
   the birth instant, Sun, ascendant, Sect and Fortune／Spirit are the values
   /api/chart prints for the same input;
2. for a non-exact birth time, the same anchor at the two other representative
   instants (the stated hour's or civil day's first and last real seconds),
   side by side, never merged (``annual_samples``);
3. the solar-return clock of each sample (``core.year_boundary``) and the year
   boundary [SR_N, SR_N+1) of the request;
4. the techniques the request selected: annual profection, firdaria, zodiacal
   releasing and the extended lots (``annual_techniques``), each reading the anchor and the clock,
   nothing else.  Zodiacal releasing reads the clock only for the window it
   shows; its own boundaries are the birth instant plus days of its year model.

No technique emits an interpretation, a verdict or a coincidence between two
techniques.  The method sources these results cite resolve in the published
register /api/chart names (``method_sources.method_source_register_receipt``);
``output_contract.route_status`` says whether the route is public
(``method_sources.ANNUAL_ROUTE_STATUS``).
"""

from __future__ import annotations

import hashlib
from typing import Any

from zoneinfo import ZoneInfo

from .core.invariants import InternalInvariantError
from .chart_pipeline import (
    SCHEMA_VERSION,
    JsonObject,
    NatalAnchor,
    compute_chart_response,
    compute_natal_anchor,
)
# ANNUAL_REASON_CODES is re-exported: the screen-code tests read it here.
from .annual_samples import (
    ANNUAL_HOUSE_SYSTEM,
    ANNUAL_REASON_CODES,
    NATAL_ANCHOR_PRODUCER,
    REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY,
    SECT_PRODUCER,
    Sample,
    anchor_sample,
    natal_request,
    representative_samples,
    utc_instant_request,
)
from .annual_techniques import ANNUAL_TECHNIQUES, natal_lots_block, source_head
from .ephemeris import FullEphemerisRequiredError, input_files_unchanged_since
from .canonical_json import CANONICAL_JSON_DUMPS_ARGUMENTS, canonical_json_bytes
from .core import decennials as dec
from .core.dignity_tables import SIGNS
from .core.dossier_warnings import SIGN_BOUNDARY_WARNING_DEGREES
from .core.civil_time_sources import CIVIL_TIME_SOURCES, rule_zone
from .core.dossier import _trace_receipt as trace_receipt
from .core.firdaria import PERIOD_DISPLAY_PRECISION
from .core.formatting import normalize_longitude, zodiac_sign_index
from .core.frame_compatibility import (
    SOLAR_RETURN_FRAME_REFUSAL_CODES,
    body_longitude_frame_label,
)
from .core.house_placements import _cusp_spans, _house_for_longitude
from .core.houses import HouseSystemUnavailableError, compute_houses
from .core.method_status import method_receipt
from .core.module_state import MODULE_COMPUTED, MODULE_NOT_REQUESTED
from .core.profections import lord_frame_state, profect
from .core.zodiacal_releasing import RELEASING_FROM
from .core.trace import Trace
from .core.time_utils import (
    DELTA_T_SWISS_TABLE_END_YEAR,
    civil_date,
    civil_instant,
    utc_parts_of_jd,
)
from .core.tz_database import TZ_DATABASE
from .core.year_boundary import (
    COMPUTED,
    FRACTIONAL_YEAR_RULE,
    LIFETIME_WINDOW_RULE,
    OUTSIDE_RANGE,
    YEAR_BOUNDARY_DEFINITION,
    lifetime_window,
    solar_return_profile,
    solver_receipt,
    ROOT_COUNT_UNEXPECTED,
    instant_receipt,
    year_boundary_record,
)
from .method_sources import ANNUAL_ROUTE_STATUS, method_source_register_receipt
from .schemas import AnnualInput, AnnualRequest
from .schema_chart import OptionsInput
from .settings import ANNUAL_ROUTE_ENVIRONMENT_VARIABLE

ANNUAL_WARNING_CODES = (
    "natal_ascendant_near_sign_boundary_affects_profection",
    "sect_near_horizon_band_affects_firdaria",
    "extended_lot_near_sign_boundary",
    "year_boundary_delta_t_extrapolated",
    "zr_start_lot_near_sign_boundary",
    "sect_near_horizon_band_affects_decennials",
    "sect_near_horizon_band_affects_zodiacal_releasing",
)


# The solar-return chart (cast at SR_N, the start of the requested year).
SOLAR_RETURN_CHART_PRODUCER = "app.chart_pipeline.compute_chart_response"
REASON_SR_CHART_REQUIRES_EXACT_BIRTH_TIME = "solar_return_chart_requires_exact_birth_time"
REASON_FIRST_YEAR_HAS_NO_SOLAR_RETURN = "first_year_has_no_solar_return"
SOLAR_RETURN_CHART_REASON_CODES = (
    REASON_SR_CHART_REQUIRES_EXACT_BIRTH_TIME,
    REASON_FIRST_YEAR_HAS_NO_SOLAR_RETURN,
    ROOT_COUNT_UNEXPECTED,
)
SOLAR_RETURN_LOCATION_SOURCES = ("birth_location", "solar_return_location")
# A product default kept in one place for the method research to change: the
# /api/chart defaults with the Lots and domicile／exaltation switched on.
SOLAR_RETURN_CHART_FIXED_OPTIONS: dict[str, Any] = {
    "include_houses": True,
    "include_lots": True,
    "include_domicile_exaltation": True,
}
SOLAR_RETURN_METHOD_PROVENANCE = "波斯／阿拉伯回歸傳統"
SOLAR_RETURN_RELOCATION_NOTE = (
    "回歸盤改用你填的地點起盤，這是 Morin 的做法（Astrologia Gallica 第 XXIII 卷，1661）；"
    "較早的回歸傳統用出生地點。"
)
SOLAR_RETURN_WHOLE_SIGN_NOTE = (
    "目前讀過的古典作者（Abū Maʿshar 經 Dykes 英譯、Morin、Gadbury）替回歸盤分宮時，"
    "都用依天球四象限切分的宮位（例如 Regiomontanus），沒有一本用整宮制；"
    "整宮是本站的預設，不是這些書的做法。"
)
SOLAR_RETURN_SIDEREAL_NOTE = (
    "目前讀過的前現代出處沒有給恆星黃道回歸的規則；以恆星黃道計算回歸是本產品的約定。"
)
NATAL_PROFECTION_SIGN_REF = "annual_methods.annual_profection.profected_sign"


class SolarReturnOutsideSupportedYearRangeError(Exception):
    """The requested year starts after 2399; an end after 2399 is only a status."""

    code = "solar_return_outside_supported_year_range"


def _near_sign_boundary(longitude: float) -> bool:
    within = normalize_longitude(longitude) % 30.0
    return min(within, 30.0 - within) < SIGN_BOUNDARY_WARNING_DEGREES


def _natal_anchor_block(req: AnnualRequest, anchor: NatalAnchor) -> JsonObject:
    time = anchor.time
    asc = anchor.houses.asc
    sect = anchor.sect or {}
    return {
        "producer": NATAL_ANCHOR_PRODUCER,
        "time_basis": time.time_conversion["input_semantics"],
        "jd_ut": time.jd_ut,
        # ISO 8601 UTC like every boundary below (the dossier's utc_iso_8601 rule).
        "utc_time": time.time_conversion["utc_time"].replace(" ", "T") + "Z",
        "sun": {
            "longitude_deg": anchor.positions.bodies_by_key["sun"]["longitude"],
            "frame": body_longitude_frame_label(req.computation_mode),
        },
        "ascendant": {
            "status": "computed" if asc is not None else "not_applicable",
            "reason_code": None if asc is not None else REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY,
            "longitude_deg": asc,
            "sign": None if asc is None else SIGNS[zodiac_sign_index(asc)],
        },
        "sect": {
            "is_day": sect.get("is_day"),
            "sect_status": sect.get("sect_status"),
            "in_near_horizon_band": sect.get("in_near_horizon_band"),
            "named_boundary_disagreement": sect.get("named_boundary_disagreement"),
            "producer": SECT_PRODUCER,
        },
    }


def _year_boundary(req: AnnualRequest, samples: list[Sample]) -> JsonObject:
    completed = req.annual.completed_years
    anchor = anchor_sample(samples)
    record = year_boundary_record(anchor.clock, completed_years=completed)
    # A non-exact birth's year is every sample's year: any sample starting
    # after 2399 refuses the whole year, so no technique gets a year without a start.
    starts = [sample.clock.root(completed)["status"] for sample in samples]
    if OUTSIDE_RANGE in starts:
        raise SolarReturnOutsideSupportedYearRangeError()
    # The Sun never turns back, so the window holds exactly one root
    # (year_boundary); any other count is the server's fault, not the request's.
    if any(status != COMPUTED for status in starts):
        raise InternalInvariantError("every sample's year start is computed")
    return {
        **record,
        "time_basis": anchor.natal.time.time_conversion["input_semantics"],
        "solar_return_profile": solar_return_profile(req.computation_mode),
        "samples": None if len(samples) == 1 else [
            {
                "sample_role": sample.role,
                **{
                    key: value
                    for key, value in year_boundary_record(
                        sample.clock, completed_years=completed
                    ).items()
                    if key in ("start_status", "start", "end_status", "end")
                },
            }
            for sample in samples
        ],
    }


def _solar_return_location(req: AnnualRequest) -> tuple[str, Any]:
    annual = req.annual
    if annual.solar_return_location is None:
        return SOLAR_RETURN_LOCATION_SOURCES[0], req.location
    return SOLAR_RETURN_LOCATION_SOURCES[1], annual.solar_return_location


def _solar_return_chart(
    req: AnnualRequest, samples: list[Sample], *, build_identity: JsonObject,
) -> JsonObject | None:
    """The chart of SR_N at the requested place: /api/chart's own pipeline.

    SR_N is the year boundary's start, read from the same clock, so the chart
    and the year cannot name two instants.  The chart is computed at that
    JD(UT) itself, labelled at UTC+00:00; its response is the detailed
    /api/chart response, unchanged.
    """

    annual = req.annual
    if not annual.include_solar_return_chart:
        return None
    completed = annual.completed_years
    source, location = _solar_return_location(req)
    options = OptionsInput(
        **SOLAR_RETURN_CHART_FIXED_OPTIONS, house_system=annual.solar_return_house_system,
    )
    head: dict[str, Any] = {
        **method_receipt("solar_return_chart"),
        "method_provenance": SOLAR_RETURN_METHOD_PROVENANCE,
        **source_head("solar_return_chart"),
        "definition": YEAR_BOUNDARY_DEFINITION,
        "solar_return_profile": solar_return_profile(req.computation_mode),
        "completed_years": completed,
        "year_of_life": completed + 1,
        "instant": None,
        "location": {"source": source, **location.model_dump(mode="json")},
        "relocation_note": (
            SOLAR_RETURN_RELOCATION_NOTE if source == SOLAR_RETURN_LOCATION_SOURCES[1] else None
        ),
        "house_system_code": annual.solar_return_house_system,
        "house_system_note": (
            SOLAR_RETURN_WHOLE_SIGN_NOTE if annual.solar_return_house_system == "W" else None
        ),
        "zodiac_note": (
            SOLAR_RETURN_SIDEREAL_NOTE if req.computation_mode.zodiac == "sidereal" else None
        ),
        "chart_options": options.model_dump(mode="json"),
        "chart_time_basis": "utc_instant",
        "producer": SOLAR_RETURN_CHART_PRODUCER,
    }
    no_comparison = _natal_comparison(None, None, completed)

    def refused(reason_code: str) -> JsonObject:
        return {
            "status": "not_applicable", "reason_code": reason_code, **head, **no_comparison,
            "chart": None,
        }

    if req.birth_time_precision != "exact":
        return refused(REASON_SR_CHART_REQUIRES_EXACT_BIRTH_TIME)
    if completed == 0:
        return refused(REASON_FIRST_YEAR_HAS_NO_SOLAR_RETURN)
    anchor = anchor_sample(samples)
    root = anchor.clock.root(completed)
    if root["status"] != COMPUTED:
        # The year boundary refused an out-of-range start already; what is
        # left is the clock's own failure status.
        return refused(root["status"])
    # The chart is computed at the root's JD itself.  A civil label of it can
    # name another instant (a positive leap second; Swiss's far-future rule
    # reads input by date and writes output by instant), so the label in the
    # request is a placeholder only.
    chart_request = utc_instant_request(
        req, utc_parts_of_jd(root["jd_ut"])[0].isoformat(), location=location, options=options,
    )
    chart = compute_chart_response(
        chart_request, build_identity=build_identity, instant_jd_ut=root["jd_ut"],
    )
    return {
        "status": "computed",
        "reason_code": None,
        **head,
        "instant": instant_receipt(root["jd_ut"]),
        **_natal_comparison(
            anchor, chart, completed,
            _natal_houses(anchor, annual.solar_return_natal_house_system or annual.solar_return_house_system),
        ),
        "chart": chart,
    }


def _natal_houses(anchor: Sample, system_code: str) -> JsonObject | None:
    """The natal houses in the natal chart's own house system.  The
    anchor's own houses are whole sign (the lots' frame), so a comparison
    read from them would place the return chart in another natal chart than
    the one the selection names.  None where that system has no houses at the
    birthplace's latitude."""

    time = anchor.natal.time
    try:
        # A trace of its own: the natal chart's trace records the anchor's
        # whole-sign houses only.
        return compute_houses(system_code, time.jd_ut, time.request.location, time.context, Trace())
    except HouseSystemUnavailableError:
        return None


def _natal_comparison(
    anchor: Sample | None, chart: JsonObject | None, completed: int,
    natal_houses: JsonObject | None = None,
) -> JsonObject:
    """Where the return chart's ascendant and planets fall among the natal
    houses, and the year's profected sign: positions only, no reading."""

    natal_sign = None if anchor is None else anchor.ascendant_sign
    comparison: dict[str, Any] = {
        "natal_house_system_code": None if natal_houses is None else natal_houses["system_code"],
        "natal_house_of_return_ascendant": None,
        "return_planets_in_natal_houses": None,
        "profected_sign": None,
        "profected_sign_ref": NATAL_PROFECTION_SIGN_REF,
    }
    if chart is None:
        return comparison
    if natal_sign is not None:
        comparison["profected_sign"] = profect(natal_sign, completed_years=completed)["profected_sign"]
    if natal_houses is None:
        return comparison
    cusps: list[float] = natal_houses["cusps"]
    spans = _cusp_spans(cusps)
    asc = chart["astronomical_data"]["angles"].get("asc")
    if asc is not None:
        comparison["natal_house_of_return_ascendant"] = _house_for_longitude(asc, cusps, spans)
    comparison["return_planets_in_natal_houses"] = [
        {
            "key": body["key"],
            "longitude": body["longitude"],
            "natal_house": _house_for_longitude(body["longitude"], cusps, spans),
        }
        for body in chart["astronomical_data"]["bodies"]
        if body.get("longitude") is not None
    ]
    return comparison


def _decimal_year(jd_ut: float) -> float:
    return 2000.0 + (jd_ut - 2451544.5) / 365.25


def _warnings(
    req: AnnualRequest,
    anchor: NatalAnchor,
    year_boundary: JsonObject,
    natal_lots: JsonObject | None,
    releasing: JsonObject | None,
) -> list[dict]:
    warnings: list[dict[str, Any]] = []
    annual = req.annual
    asc = anchor.houses.asc
    if asc is not None and _near_sign_boundary(asc):
        # The monthly profection counts from the same ascendant sign.
        for requested, path in (
            (annual.include_profection, "annual_methods.annual_profection"),
            (annual.include_monthly_profection, "annual_methods.monthly_profection"),
        ):
            if requested:
                warnings.append({"code": ANNUAL_WARNING_CODES[0], "path": path})
    if annual.include_firdaria and (anchor.sect or {}).get("in_near_horizon_band"):
        warnings.append({"code": ANNUAL_WARNING_CODES[1], "path": "annual_methods.firdaria"})
    # Only the sect-light start reads the Sect; the other two profiles do not.
    if (
        annual.include_decennials
        and annual.decennials_start_profile == dec.START_PROFILES[0]
        and (anchor.sect or {}).get("in_near_horizon_band")
    ):
        warnings.append({"code": ANNUAL_WARNING_CODES[5], "path": "annual_methods.decennials"})
    if natal_lots is not None and natal_lots["lots"]:
        near = [lot["lot_method_id"] for lot in natal_lots["lots"] if _near_sign_boundary(lot["longitude"])]
        if near:
            warnings.append({"code": ANNUAL_WARNING_CODES[2], "path": "natal_lots", "lot_method_ids": near})
    # Fortune and Spirit exchange formulas with the sect; the warning is given
    # only when that would move a starting sign, in any sample listed.
    if releasing is not None and releasing["status"] == "computed" and any(
        row["start_sign_differs_under_other_sect"] is True
        for rows in [releasing["releases"] or [],
                     *(candidate["releases"] for candidate in releasing["candidates"] or [])]
        for row in rows
    ):
        warnings.append({"code": ANNUAL_WARNING_CODES[6], "path": "annual_methods.zodiacal_releasing"})
    if releasing is not None and releasing["status"] == "computed":
        near_lots = [lot for lot in RELEASING_FROM if _near_sign_boundary(anchor.lots[lot])]
        if near_lots:
            warnings.append({"code": ANNUAL_WARNING_CODES[4],
                             "path": "annual_methods.zodiacal_releasing",
                             "releasing_from": near_lots})
    boundary_instants = [
        year_boundary[key]["jd_ut"] for key in ("start", "end") if year_boundary[key] is not None
    ]
    if any(_decimal_year(jd) > DELTA_T_SWISS_TABLE_END_YEAR for jd in boundary_instants):
        warnings.append({"code": ANNUAL_WARNING_CODES[3], "path": "year_boundary"})
    return warnings


def _civil_boundary(jd_ut: float, tz_input) -> JsonObject:
    """A year boundary instant with the birth place's civil date and time."""

    return {**civil_instant(jd_ut, tz_input), "local_date": civil_date(jd_ut, tz_input).isoformat()}


def _localize_year_boundary(year_boundary: JsonObject, tz_input) -> None:
    for record in [year_boundary, *(year_boundary["samples"] or [])]:
        for key in ("start", "end"):
            instant = record[key]
            if instant is not None:
                civil = _civil_boundary(instant["jd_ut"], tz_input)
                instant.update({name: civil[name] for name in ("local_date", "local_time", "utc_offset")})


def _year_boundaries(
    req: AnnualRequest, samples: list[Sample], profection: JsonObject | None
) -> JsonObject | None:
    """Every return year of the lifetime window, each with its profection.

    The anchor sample's clock (the requested year's own roots, bit for bit);
    the profection follows annual_profection: withheld where it is not
    requested or not applicable, one sign per sample where the samples'
    ascendant signs differ.
    """

    annual = req.annual
    if not annual.include_year_boundaries:
        return None
    first, last = lifetime_window(annual.completed_years)
    anchor = anchor_sample(samples)
    if profection is None:
        status, reason = MODULE_NOT_REQUESTED, None
    else:
        status, reason = profection["status"], profection["reason_code"]
    signs = [sample.ascendant_sign for sample in samples]
    agreed = len(set(signs)) == 1
    lord_named = lord_frame_state(req.computation_mode)["applicable"]

    def profection_of(sign: str | None, completed: int) -> tuple[str, str | None]:
        if sign is None:  # computed: every sample has its ascendant
            raise InternalInvariantError("sign is not None")
        result = profect(sign, completed_years=completed)
        return result["profected_sign"], result["lord_body_key"] if lord_named else None

    years = []
    for completed in range(first, last + 1):
        start = anchor.clock.root(completed)
        if start["status"] != COMPUTED:
            break
        end = anchor.clock.root(completed + 1)
        entry: dict[str, Any] = {
            "completed_years": completed,
            "year_of_life": completed + 1,
            "start": {**_civil_boundary(start["jd_ut"], req.timezone), "status": COMPUTED},
            "end_status": end["status"],
            "end": (
                {**_civil_boundary(end["jd_ut"], req.timezone), "status": COMPUTED}
                if end["status"] == COMPUTED else None
            ),
            "profection_sign": None, "profected_place": None, "year_lord": None,
            "candidates": None,
        }
        if status == MODULE_COMPUTED:
            entry["profected_place"] = completed % 12 + 1
            if agreed:
                entry["profection_sign"], entry["year_lord"] = profection_of(signs[0], completed)
            else:
                entry["candidates"] = [
                    dict(zip(("sample_role", "profection_sign", "year_lord"),
                             (sample.role, *profection_of(sample.ascendant_sign, completed))))
                    for sample in samples
                ]
        years.append(entry)
    return {
        "definition": YEAR_BOUNDARY_DEFINITION,
        "window": {"rule": LIFETIME_WINDOW_RULE, "first_completed_years": first,
                   "last_completed_years": last},
        "sample_role": anchor.role,
        "profection_ref": "annual_methods.annual_profection",
        "profection_status": status,
        "profection_reason_code": reason,
        "years": years,
    }


def _date_periods(node: Any, tz_input, dated: list[float]) -> None:
    """Add the birth place's civil date to every period boundary under node.

    A period boundary is what core.firdaria.period_instant builds (day
    precision); any technique that builds its boundaries there is dated here.
    """

    if isinstance(node, dict):
        if node.get("display_precision") == PERIOD_DISPLAY_PRECISION and "jd_ut" in node:
            jd_ut = node["jd_ut"]
            node["local_date"] = None if jd_ut is None else civil_date(jd_ut, tz_input).isoformat()
            if jd_ut is not None:
                dated.append(jd_ut)
            return
        for value in node.values():
            _date_periods(value, tz_input, dated)
    elif isinstance(node, list):
        for item in node:
            _date_periods(item, tz_input, dated)


LOCAL_DATE_SOURCE_TABLE_CHECKS = ("consistent", "mismatch_found", "zone_not_covered")


def _source_table_check(tz_input, instants: list[float]) -> str:
    """Whether the tz database's reading at each dated instant is the rule the
    product's civil-time source table holds for the birth zone."""

    kept_under = rule_zone(tz_input.iana_name) if tz_input.mode == "iana" else None
    if kept_under is None:
        return LOCAL_DATE_SOURCE_TABLE_CHECKS[2]
    for jd_ut in instants:
        utc_value = utc_parts_of_jd(jd_ut)[0]
        local = utc_value.astimezone(ZoneInfo(tz_input.iana_name))
        offset, abbreviation = local.utcoffset(), local.tzname()
        if offset is None or abbreviation is None:
            raise InternalInvariantError("offset is not None and abbreviation is not None")
        receipt = CIVIL_TIME_SOURCES.rule_receipt(
            kept_under, utc_value, offset=offset, abbreviation=abbreviation,
            summer_time=bool(local.dst()),
        )
        if receipt["status"] == "source_table_mismatch":
            return LOCAL_DATE_SOURCE_TABLE_CHECKS[1]
    return LOCAL_DATE_SOURCE_TABLE_CHECKS[0]


def _local_date_policy(req: AnnualRequest, instants: list[float]) -> JsonObject:
    tz_input = req.timezone
    return {
        "basis": "birth_place_civil_time",
        "applies_to": (
            "local_date of every period boundary and of the year boundaries; "
            "local_time and utc_offset of the year boundaries"
        ),
        "timezone_mode": tz_input.mode,
        "iana_name": tz_input.iana_name if tz_input.mode == "iana" else None,
        "utc_offset_hours": tz_input.utc_offset_hours if tz_input.mode != "iana" else None,
        "civil_time_basis": getattr(tz_input, "civil_time_basis", None),
        "display_precision": PERIOD_DISPLAY_PRECISION,
        "tz_database": dict(TZ_DATABASE),
        "source_table_check": _source_table_check(tz_input, instants),
    }


# FullEphemerisRequiredError.reason when an input file changed while the year
# was computed: the server's, so it leaves as internal_server_error.
ANNUAL_INPUT_FILES_CHANGED = "input_files_changed_during_calculation"
_OPTIONS_STEP_TITLE = "請求選項"


def _bind_annual_options(trace, annual: AnnualInput) -> None:
    """The trace's first step holds the options as sent (the Dossier contract).

    The natal anchor wrote its own first step for the fixed whole-sign options
    it runs under; on this route the options as sent are ``annual``, so they
    take the first step and the anchor's options follow, named as fixed.
    """

    steps = trace.steps
    if not steps or steps[0]["title"] != _OPTIONS_STEP_TITLE:
        raise InternalInvariantError("natal trace order changed")
    natal_options = steps[0]["inputs"]
    steps[0] = {
        "title": _OPTIONS_STEP_TITLE,
        "formula": "",
        "inputs": annual.model_dump(mode="json"),
        "result": {},
        "note": "這次年度請求送出的全部選項；它們在計算軌跡裡，所以計算軌跡的 SHA-256 也涵蓋選項。",
    }
    steps.insert(1, {
        "title": "本命錨點選項（本路由固定）",
        "formula": "",
        "inputs": natal_options,
        "result": {},
        "note": "本命錨點一律以整宮制、開啟阿拉伯點、不算相位來計算；這些不是請求送出的選項。",
    })


def _technique_steps(
    trace, annual_methods: dict, natal_lots: JsonObject | None, year_boundaries: JsonObject | None,
    solar_return_chart: JsonObject | None,
) -> None:
    """One step per technique: its status, its profile and its output's digest.

    The digest is over the block the response prints at ``response_path``
    (Python JSON recipe of the trace receipt), so the trace receipt also binds
    each technique's output, sample-dependent dates included.
    """

    blocks = [
        *((key, f"annual_methods.{key}", block) for key, block in annual_methods.items()),
        ("natal_lots", "natal_lots", natal_lots),
        ("year_boundaries", "year_boundaries", year_boundaries),
        ("solar_return_chart", "solar_return_chart", solar_return_chart),
    ]
    for key, path, block in blocks:
        trace.add(
            f"年度技法：{key}",
            formula=f"輸出 SHA-256 ＝ sha256(Python json.dumps(該區塊, {CANONICAL_JSON_DUMPS_ARGUMENTS}))",
            inputs={"response_path": path},
            result={
                "status": MODULE_NOT_REQUESTED if block is None else block.get("status", MODULE_COMPUTED),
                "profile": None if block is None else block.get(
                    "profile", block.get("solar_return_profile")),
                "output_sha256": (
                    None if block is None else hashlib.sha256(canonical_json_bytes(block)).hexdigest()
                ),
            },
        )


def _solar_return_chart_step(trace, block: JsonObject) -> None:
    chart = block["chart"]
    trace.add(
        "太陽回歸盤",
        formula="在 SR_N（本年年界的起點）與所選地點，以本命盤同一條計算管線起盤",
        inputs={
            "completed_years": block["completed_years"],
            "location_source": block["location"]["source"],
            "house_system_code": block["house_system_code"],
            "chart_time_basis": block["chart_time_basis"],
        },
        result={
            "status": block["status"],
            "reason_code": block["reason_code"],
            "instant_jd_ut": (block["instant"] or {}).get("jd_ut"),
            "chart_jd_ut": None if chart is None else chart["astronomical_data"]["time"]["jd_ut"],
            "chart_trace_sha256": None if chart is None else (
                chart["calculation_dossier"]["trace_receipt"]["python_json_serialization_sha256"]),
        },
        note=(
            "回歸瞬間與年界讀同一個太陽回歸時鐘；星盤本身的計算軌跡在 solar_return_chart.chart "
            "（detailed）裡，這一步記下它的 SHA-256。"
        ),
    )


def compute_annual_response(
    req: AnnualRequest, *, build_identity: JsonObject, localize_timezone: Any = None
) -> JsonObject:
    """``localize_timezone`` is the zone the request named when a place zone
    policy replaced it for the birth instant only; the dates after the birth
    are localized in it, each instant resolved on its own."""

    shown = req if localize_timezone is None else req.model_copy(update={"timezone": localize_timezone})
    anchor = compute_natal_anchor(natal_request(req))
    samples = representative_samples(req, anchor)
    year_boundary = _year_boundary(req, samples)
    annual_methods = {key: build(req, samples) for key, build in ANNUAL_TECHNIQUES.items()}
    natal_lots = natal_lots_block(req, samples)
    year_boundaries = _year_boundaries(shown, samples, annual_methods["annual_profection"])
    solar_return_chart = _solar_return_chart(req, samples, build_identity=build_identity)
    _localize_year_boundary(year_boundary, shown.timezone)
    dated: list[float] = [
        instant["jd_ut"]
        for record in [year_boundary, *(year_boundaries or {}).get("years", [])]
        for instant in (record["start"], record["end"]) if instant is not None
    ]
    _date_periods(annual_methods, shown.timezone, dated)
    trace = anchor.time.trace
    _bind_annual_options(trace, req.annual)
    trace.add(
        "年界（第 N 次太陽回歸）",
        formula="SR_N：太陽黃經第 N 次回到本命太陽黃經的瞬間；第 N+1 年 = [SR_N, SR_N+1)",
        inputs={"completed_years": req.annual.completed_years},
        result={
            "start_utc": (year_boundary["start"] or {}).get("utc_time"),
            "end_utc": (year_boundary["end"] or {}).get("utc_time"),
            "end_status": year_boundary["end_status"],
        },
        note=(
            "年度小限與法達共用這一個年界；不做民用日算術。黃道釋放只用它決定顯示哪些期間，"
            "期間邊界是出生瞬間加上所選年模型的日數。"
        ),
    )
    if solar_return_chart is not None:
        _solar_return_chart_step(trace, solar_return_chart)
    _technique_steps(trace, annual_methods, natal_lots, year_boundaries, solar_return_chart)
    trace_steps = trace.as_list()
    response: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "output_contract": {
            "status": "provisional",
            "route_status": ANNUAL_ROUTE_STATUS,
            "flag": ANNUAL_ROUTE_ENVIRONMENT_VARIABLE,
            "compatibility": "additive_during_0.x_unless_a_documented_correctness_fix_requires_change",
            "interpretation": "none_emitted",
        },
        "requested_annual": req.annual.model_dump(),
        "computation_mode": req.computation_mode.model_dump(),
        "birth_time_precision": req.birth_time_precision,
        "natal_anchor": _natal_anchor_block(req, anchor),
        "year_boundary": year_boundary,
        "year_boundaries": year_boundaries,
        "annual_methods": annual_methods,
        "natal_lots": natal_lots,
        "solar_return_chart": solar_return_chart,
        "calculation_dossier": {
            "annual_policy": {
                "year_boundary_definition": YEAR_BOUNDARY_DEFINITION,
                "fractional_year_rule": FRACTIONAL_YEAR_RULE,
                "solar_return_profile": solar_return_profile(req.computation_mode),
                "solver": solver_receipt(req.computation_mode.zodiac),
                "house_system_code": ANNUAL_HOUSE_SYSTEM,
                "period_display_precision": "day",
                "frame_refusals": list(SOLAR_RETURN_FRAME_REFUSAL_CODES),
                "local_dates": _local_date_policy(shown, dated),
                "representative_samples": (
                    None if len(samples) == 1 else [sample.reference for sample in samples]
                ),
                "merge_policy": None if len(samples) == 1 else "side_by_side_not_merged",
            },
            "time_conversion": anchor.time.time_conversion,
            "method_source_register": method_source_register_receipt(),
            "warnings": _warnings(
                req, anchor, year_boundary, natal_lots, annual_methods["zodiacal_releasing"]
            ),
            "privacy": {
                "contains_birth_data": True,
                "period_boundaries_reveal_birth_time_and_sect": True,
                "server_persistence": "none",
            },
            "build_identity": build_identity,
            "trace_receipt": trace_receipt(trace_steps),
        },
        "calculation_trace": trace_steps,
    }
    # Every Swiss call of the year is behind this point.  If an input file
    # changed since the anchor read its identity, which bytes those calls read
    # cannot be attributed.  /api/chart withdraws its full-ephemeris claims; this
    # response has none to withdraw, so it is refused like an unpredicted Swiss
    # fallback (internal_server_error, main._handle_domain_error).
    if not input_files_unchanged_since(anchor.time.ephemeris_input_watch):
        raise FullEphemerisRequiredError(
            operation="年度計算",
            jd_ut=anchor.time.jd_ut,
            retflag=0,
            reason=ANNUAL_INPUT_FILES_CHANGED,
        )
    return response
