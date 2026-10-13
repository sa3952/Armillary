"""The flagged annual route: one natal anchor, one year boundary, the techniques.

Stages, in order (the caller holds the Swiss line):

1. the natal anchor: ``chart_pipeline.compute_natal_anchor`` on a ChartRequest
   built from the annual request (whole-sign houses, Lots on, aspects off), so
   the birth instant, Sun, ascendant, Sect and Fortune／Spirit are the values
   /api/chart prints for the same input;
2. for a non-exact birth time, the same anchor at the two other representative
   instants: the stated hour's or civil day's first and last
   real seconds, side by side, never merged;
3. the solar-return clock of each sample (``core.year_boundary``) and the year
   boundary [SR_N, SR_N+1) of the request;
4. the techniques the request selected: annual profection, firdaria, zodiacal
   releasing and the extended lots, each reading the anchor and the clock,
   nothing else.  Zodiacal releasing reads the clock only for the window it
   shows; its own boundaries are the birth instant plus days of its year model.

No technique emits an interpretation, a verdict or a coincidence between two
techniques.  The method sources these results cite resolve in the published
register /api/chart names (``method_sources.method_source_register_receipt``);
``output_contract.route_status`` says whether the route is public
(``method_sources.ANNUAL_ROUTE_STATUS``).
"""

from __future__ import annotations

import datetime as dtmod
from fractions import Fraction
from typing import Any, Literal

from zoneinfo import ZoneInfo

import swisseph as swe

from .chart_pipeline import SCHEMA_VERSION, JsonObject, NatalAnchor, compute_natal_anchor
from .core.birth_time_sensitivity import (
    DIFFERS_BETWEEN_SAMPLES,
    NOT_APPLICABLE_STATE,
    NOT_REQUESTED_STATE,
    SAME_AT_ALL_SAMPLES,
)
from .core import decennials as dec
from .core import monthly_profections as monthly
from .core.dignity_tables import SIGNS
from .core.dossier_warnings import SIGN_BOUNDARY_WARNING_DEGREES
from .core.extended_lots import compute_extended_lots
from .core.civil_time_sources import CIVIL_TIME_SOURCES, rule_zone
from .core.dossier import _trace_receipt as trace_receipt
from .core.firdaria import FIRDARIA_PROFILE, PERIOD_DISPLAY_PRECISION, firdaria_periods, period_instant
from .core.formatting import normalize_longitude, zodiac_sign_index
from .core.frame_compatibility import (
    SOLAR_RETURN_FRAME_REFUSAL_CODES,
    body_longitude_frame_label,
    method_frame_state,
)
from .core.method_status import method_receipt
from .core.module_state import (
    MODULE_STATUSES,
    PRODUCT_FORMULA_SOURCE,
    computed_receipt,
    module_status_word,
    not_applicable_receipt,
)
from .core.profections import (
    LORD_TABLE,
    PROFECTION_PROFILE,
    PROFECTION_PROVENANCE,
    lord_frame_state,
    profect,
)
from .core.zodiacal_releasing import (
    LEVELS_EMITTED as ZR_LEVELS_EMITTED,
    METHOD_PROVENANCE as ZR_METHOD_PROVENANCE,
    RELEASING_FROM,
    RELEASING_PROFILE,
    SIGN_PERIOD_TABLE_PROFILE,
    YEAR_MODELS,
    elapsed_distribution_time,
    releasing_periods,
)
from .core.time_utils import (
    DELTA_T_SWISS_TABLE_END_YEAR,
    REPRESENTATIVE_SAMPLE_ROLES,
    civil_date,
    civil_instant,
    representative_sample_instants,
    utc_parts_of_jd,
)
from .core.tz_database import TZ_DATABASE
from .core.year_boundary import (
    COMPUTED,
    FRACTIONAL_YEAR_RULE,
    LIFETIME_WINDOW_RULE,
    OUTSIDE_RANGE,
    RANGE_END_JD_UT,
    SOLAR_MONTH_RULE,
    YEAR_BOUNDARY_DEFINITION,
    SolarReturnClock,
    lifetime_window,
    solar_return_profile,
    solver_receipt,
    year_boundary_record,
)
from .method_sources import ANNUAL_ROUTE_STATUS, method_source_register_receipt, resolve
from .schemas import (
    AnnualInput,
    AnnualRequest,
    ChartRequest,
    DateTimeInput,
    OptionsInput,
    TimezoneInput,
)
from .settings import ANNUAL_ROUTE_ENVIRONMENT_VARIABLE

# One version sequence with /api/chart: the annual response names the main
# API's version, so the two cannot drift apart.
ANNUAL_SCHEMA_VERSION = SCHEMA_VERSION
# Lots and their houses on the annual route are whole-sign (the profection's own
# frame); the route takes no house-system option.
ANNUAL_HOUSE_SYSTEM: Literal["W"] = "W"
_NATAL_OPTIONS = OptionsInput(
    include_houses=True,
    house_system=ANNUAL_HOUSE_SYSTEM,
    include_lots=True,
    include_aspects=False,
)
_ANCHOR_ROLE = REPRESENTATIVE_SAMPLE_ROLES[1]
SECT_PRODUCER = "app.core.lots.classify_sect"
NATAL_ANCHOR_PRODUCER = "app.chart_pipeline.compute_natal_anchor"

REASON_SECT_UNKNOWN_FOR_DATE_ONLY = "sect_unknown_for_date_only"
REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY = "natal_ascendant_unknown_for_date_only"
REASON_LOTS_NOT_DERIVABLE_FOR_DATE_ONLY = "lots_not_derivable_for_date_only"
ANNUAL_REASON_CODES = (
    REASON_SECT_UNKNOWN_FOR_DATE_ONLY,
    REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY,
    REASON_LOTS_NOT_DERIVABLE_FOR_DATE_ONLY,
)
ANNUAL_WARNING_CODES = (
    "natal_ascendant_near_sign_boundary_affects_profection",
    "sect_near_horizon_band_affects_firdaria",
    "extended_lot_near_sign_boundary",
    "year_boundary_delta_t_extrapolated",
    "zr_start_lot_near_sign_boundary",
    "sect_near_horizon_band_affects_decennials",
    "sect_near_horizon_band_affects_zodiacal_releasing",
)


class SolarReturnOutsideSupportedYearRangeError(Exception):
    """The requested year starts after 2399; an end after 2399 is only a status."""

    code = "solar_return_outside_supported_year_range"


class _Sample:
    """One representative instant: its natal anchor and its solar-return clock."""

    def __init__(
        self, role: str, natal: NatalAnchor, zodiac: str, reference: dict | None = None,
    ) -> None:
        self.role = role
        self.natal = natal
        # The instant this sample stands for, as the time step printed it
        # (None for an exact time, which has one instant).
        self.reference = reference
        sampler = natal.positions.longitude_at
        self.clock = SolarReturnClock(
            birth_jd_ut=natal.time.jd_ut,
            natal_sun_longitude=natal.positions.bodies_by_key["sun"]["longitude"],
            sun_longitude_at=lambda jd_ut: sampler(swe.SUN, jd_ut),
            zodiac=zodiac,
        )

    @property
    def ascendant_sign(self) -> str | None:
        asc = self.natal.houses.asc
        return None if asc is None else SIGNS[zodiac_sign_index(asc)]

    @property
    def is_day(self) -> bool | None:
        return (self.natal.sect or {}).get("is_day")


def _natal_request(req: AnnualRequest) -> ChartRequest:
    return ChartRequest(
        birth_time_precision=req.birth_time_precision,
        datetime=req.datetime,
        timezone=req.timezone,
        location=req.location,
        atmosphere=req.atmosphere,
        computation_mode=req.computation_mode,
        options=_NATAL_OPTIONS,
    )


def _sample_request(req: AnnualRequest, utc_text: str) -> ChartRequest:
    # A sample is an instant the time step already resolved, so it is posed as
    # that UTC instant (fixed offset 0) and not re-validated: a sample of a
    # 1900-01-01 birth east of Greenwich is a 1899 UTC date.
    moment = dtmod.datetime.fromisoformat(utc_text.replace("Z", "+00:00"))
    return ChartRequest.model_construct(
        birth_time_precision="exact",
        datetime=DateTimeInput.model_construct(
            year=moment.year, month=moment.month, day=moment.day,
            hour=moment.hour, minute=moment.minute,
            # Spelled as its decimal literal: the time step reads the second
            # from the float's shortest spelling and refuses one finer than a
            # microsecond, which `second + microsecond / 1e6` can produce.
            second=float(f"{moment.second}.{moment.microsecond:06d}"),
        ),
        timezone=TimezoneInput.model_construct(
            mode="fixed_offset", iana_name=None, utc_offset_hours=0.0, fold=0,
        ),
        location=req.location,
        atmosphere=req.atmosphere,
        computation_mode=req.computation_mode,
        options=_NATAL_OPTIONS,
    )


def _samples(req: AnnualRequest, anchor: NatalAnchor) -> list[_Sample]:
    """The anchor alone for an exact time; else the three samples in role order."""

    zodiac = req.computation_mode.zodiac
    if req.birth_time_precision == "exact":
        return [_Sample(_ANCHOR_ROLE, anchor, zodiac)]
    assert anchor.time.anchor_utc is not None  # resolved for every non-exact chart
    instants = representative_sample_instants(
        req.datetime,
        req.timezone,
        precision=req.birth_time_precision,
        anchor_utc=anchor.time.anchor_utc,
        civil_day=anchor.time.civil_day,
    )
    return [
        _Sample(instant["sample_role"], anchor, zodiac, _sample_reference(instant))
        if instant["sample_role"] == _ANCHOR_ROLE
        else _Sample(
            instant["sample_role"],
            compute_natal_anchor(_sample_request(req, instant["reference_utc_time"])),
            zodiac,
            _sample_reference(instant),
        )
        for instant in instants
    ]


def _sample_reference(instant: dict) -> dict:
    return {
        key: instant[key]
        for key in ("sample_role", "reference_local_time", "reference_utc_time", "reference_jd_ut")
    }


def _state_fields(state: dict) -> dict:
    return {**state, "status": module_status_word(state)}


def _not_applicable(reason_code: str) -> dict:
    return _state_fields(not_applicable_receipt({"applicable": False, "reason_code": reason_code}))


def _computed() -> dict:
    return _state_fields(computed_receipt(PRODUCT_FORMULA_SOURCE))


def _lords_receipt(lord_state: dict) -> dict:
    """The domicile-lord table a technique names its lords from, and whether
    the frame lets it name them."""
    if lord_state["applicable"]:
        return {**computed_receipt(LORD_TABLE), "table": LORD_TABLE}
    return {**not_applicable_receipt(lord_state), "table": LORD_TABLE}


def _input_presence(annual: AnnualInput, field: str) -> str:
    return "explicit" if field in annual.model_fields_set else "defaulted"


def _source(ref: str) -> dict[str, str]:
    """A technique head's register ref; how far each of its citations was read
    is stated in the published register's entry, which the ref must name."""
    resolve(ref)
    return {"source_ref": ref}


def _agreement(values: list) -> str:
    return SAME_AT_ALL_SAMPLES if len(set(values)) == 1 else DIFFERS_BETWEEN_SAMPLES


def _sensitivity(samples: list[_Sample], values: list) -> str:
    """not requested for one sample (an exact time), else whether the samples agree."""
    return NOT_REQUESTED_STATE if len(samples) == 1 else _agreement(values)


def _anchor_sample(samples: list[_Sample]) -> _Sample:
    return next(sample for sample in samples if sample.role == _ANCHOR_ROLE)


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


def _year_boundary(req: AnnualRequest, samples: list[_Sample]) -> JsonObject:
    completed = req.annual.completed_years
    anchor = _anchor_sample(samples)
    record = year_boundary_record(anchor.clock, completed_years=completed)
    # A non-exact birth's year is every sample's year: when any sample's start
    # falls after 2399 the year is refused as a whole, as for the anchor, and
    # no technique is handed a year without a start.
    starts = [sample.clock.root(completed)["status"] for sample in samples]
    if OUTSIDE_RANGE in starts:
        raise SolarReturnOutsideSupportedYearRangeError()
    for status in starts:
        if status != COMPUTED:
            raise RuntimeError(f"year boundary start: {status}")
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


def _profection(req: AnnualRequest, samples: list[_Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_profection:
        return None
    completed = annual.completed_years
    head = {
        "profile": PROFECTION_PROFILE,
        **method_receipt("annual_profection"),
        "method_provenance": PROFECTION_PROVENANCE,
        **_source("annual_profection"),
        "age_input_kind": annual.target_kind,
        "completed_years": completed,
        "year_of_life": completed + 1,
        "year_boundary_ref": "year_boundary",
    }
    signs = [sample.ascendant_sign for sample in samples]
    if any(sign is None for sign in signs):
        return {
            **_not_applicable(REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY),
            **head,
            "natal_ascendant_sign": None, "offset_signs": None,
            "profected_sign": None, "profected_place": None, "lord": None,
            "sensitivity_state": NOT_APPLICABLE_STATE, "candidates": None,
            "interpretation": None,
        }
    lord_state = lord_frame_state(req.computation_mode)
    results = [profect(sign, completed_years=completed) for sign in signs if sign]
    state = _sensitivity(samples, signs)
    agreed = results[0] if state != DIFFERS_BETWEEN_SAMPLES else None

    def lord(result: dict | None) -> dict:
        if not lord_state["applicable"]:
            return {**not_applicable_receipt(lord_state), "body_key": None, "table": LORD_TABLE}
        return {
            **computed_receipt(LORD_TABLE),
            "body_key": None if result is None else result["lord_body_key"],
            "table": LORD_TABLE,
        }

    return {
        **_computed(),
        **head,
        "natal_ascendant_sign": None if agreed is None else agreed["natal_ascendant_sign"],
        "offset_signs": completed % 12,
        "profected_sign": None if agreed is None else agreed["profected_sign"],
        "profected_place": None if agreed is None else agreed["profected_place"],
        "lord": lord(agreed),
        "sensitivity_state": state,
        "candidates": None if agreed is not None else [
            {
                "sample_role": sample.role,
                "natal_ascendant_sign": result["natal_ascendant_sign"],
                "profected_sign": result["profected_sign"],
                "profected_place": result["profected_place"],
                "lord_body_key": result["lord_body_key"] if lord_state["applicable"] else None,
            }
            for sample, result in zip(samples, results)
        ],
        "interpretation": None,
    }


def _firdaria(req: AnnualRequest, samples: list[_Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_firdaria:
        return None
    anchor = _anchor_sample(samples)
    sect = anchor.natal.sect or {}
    head = {
        "profile": FIRDARIA_PROFILE,
        "nocturnal_node_profile": annual.firdaria_nocturnal_node_profile,
        "nocturnal_node_profile_input": (
            "explicit"
            if "firdaria_nocturnal_node_profile" in annual.model_fields_set
            else "defaulted"
        ),
        **method_receipt("firdaria"),
        **_source("firdaria"),
        "year_model": {
            "year_boundary_ref": "year_boundary",
            "fractional_year_rule": FRACTIONAL_YEAR_RULE,
            "return_profile": solar_return_profile(req.computation_mode),
        },
        "sect": {
            "is_day": sect.get("is_day"),
            "sect_status": sect.get("sect_status"),
            "sect_in_near_horizon_band": sect.get("in_near_horizon_band"),
            "sect_named_boundary_disagreement": sect.get("named_boundary_disagreement"),
            "producer": SECT_PRODUCER,
        },
        "scope": annual.firdaria_scope,
        "lifetime_window": _lifetime_window_head(annual, annual.firdaria_scope),
    }
    day_flags = [sample.is_day for sample in samples]
    if any(flag is None for flag in day_flags):
        return {
            **_not_applicable(REASON_SECT_UNKNOWN_FOR_DATE_ONLY),
            **head,
            "nocturnal_node_profile_applies": None,
            "method_provenance": None,
            "cycle_index": None, "periods": None, "candidates": None,
            "sensitivity_state": NOT_APPLICABLE_STATE,
            "interpretation": None,
        }

    def periods_for(sample: _Sample) -> dict:
        return firdaria_periods(
            is_day=bool(sample.is_day),
            nocturnal_node_profile=annual.firdaria_nocturnal_node_profile,
            scope=annual.firdaria_scope,
            completed_years=annual.completed_years,
            instant_at_year=sample.clock.instant_at_year,
        )

    by_sample = [periods_for(sample) for sample in samples]
    state = _sensitivity(samples, day_flags)
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    top = next(
        result for sample, result in zip(samples, by_sample) if sample.role == _ANCHOR_ROLE
    )
    return {
        **_computed(),
        **head,
        "nocturnal_node_profile_applies": top["nocturnal_node_profile_applies"] if agreed else None,
        "method_provenance": top["method_provenance"],
        "cycle_index": top["cycle_index"],
        "periods": top["periods"] if agreed else None,
        # Boundaries move with the birth instant, so a non-exact time lists
        # every sample's periods even when the sequence is the same.
        "candidates": None if len(samples) == 1 else [
            {"sample_role": sample.role, "is_day": sample.is_day, "periods": result["periods"]}
            for sample, result in zip(samples, by_sample)
        ],
        "sensitivity_state": state,
        "interpretation": None,
    }


def _sign_of(longitude: float) -> str:
    return SIGNS[zodiac_sign_index(longitude)]


def _releasing_window(sample: _Sample, completed: int, year_model: str) -> dict:
    """The return year [SR_N, SR_N+1) the periods are shown for, and how far
    into the distribution it starts; the periods themselves never read it."""

    birth = sample.natal.time.jd_ut
    start, end = sample.clock.root(completed), sample.clock.root(completed + 1)
    end_jd = end["jd_ut"] if end["status"] == COMPUTED else None

    def elapsed(jd_ut: float | None) -> dict | None:
        return None if jd_ut is None else elapsed_distribution_time(year_model, jd_ut - birth)

    return {
        "year_boundary_ref": "year_boundary",
        "start": period_instant(start),
        "end": period_instant(end) if end_jd is not None else None,
        "end_status": end["status"],
        "start_elapsed": elapsed(start["jd_ut"]),
        "end_elapsed": elapsed(end_jd),
    }


def _lifetime_bounds(
    sample: _Sample, completed: int, scope: str
) -> tuple[float, float] | tuple[None, None]:
    """The lifetime window's instants for a `lifetime_window` scope, else none."""
    return _lifetime_instants(sample, completed) if scope == "lifetime_window" else (None, None)


def _lifetime_instants(sample: _Sample, completed: int) -> tuple[float, float]:
    """JD(UT) of the lifetime window's first start and last end for a sample.

    An end after the supported years is the range end: the window then holds
    what the product can date.
    """

    first, last = lifetime_window(completed)
    start, end = sample.clock.root(first), sample.clock.root(last + 1)
    return start["jd_ut"], end["jd_ut"] if end["status"] == COMPUTED else RANGE_END_JD_UT


def _releases(sample: _Sample, window: dict, annual, name_lords: bool) -> list[dict]:
    lots = sample.natal.lots
    lifetime = _lifetime_bounds(sample, annual.completed_years, annual.zr_scope)
    fortune_sign = _sign_of(lots["fortune"])
    in_band = lots["sect_status"] == "boundary_both_shown"
    other = lots["by_sect"]["night" if lots["sect_applied"] == "day" else "day"]
    rows = []
    for lot in RELEASING_FROM:
        sign = _sign_of(lots[lot])
        other_sign = _sign_of(other[lot]) if in_band else None
        differs = None if other_sign is None else other_sign != sign
        rows.append({
            "releasing_from": lot,
            "start_sign": sign,
            "start_lot_longitude_deg": lots[lot],
            "start_sign_differs_under_other_sect": differs,
            "comparison_start_sign": other_sign if differs else None,
            "periods": releasing_periods(
                start_sign=sign,
                fortune_sign=fortune_sign,
                year_model=annual.zr_year_model,
                scope=annual.zr_scope,
                birth_jd_ut=sample.natal.time.jd_ut,
                window_start_jd_ut=window["start"]["jd_ut"],
                window_end_jd_ut=None if window["end"] is None else window["end"]["jd_ut"],
                name_lords=name_lords,
                lifetime_start_jd_ut=lifetime[0],
                lifetime_end_jd_ut=lifetime[1],
            ),
        })
    return rows


def _zodiacal_releasing(req: AnnualRequest, samples: list[_Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_zodiacal_releasing:
        return None
    model = YEAR_MODELS[annual.zr_year_model]
    lord_state = lord_frame_state(req.computation_mode)
    head = {
        "profile": RELEASING_PROFILE,
        "period_table_profile": SIGN_PERIOD_TABLE_PROFILE,
        "year_model": {
            "profile": annual.zr_year_model,
            "input": _input_presence(annual, "zr_year_model"),
            "days_per_year": float(model["days_per_year"]),
            "days_per_level_2_unit": float(model["days_per_year"] / 12),
            "provenance": model["provenance"],
            "boundary_rule": "birth_jd_ut_plus_accumulated_days",
            "other_profiles": [key for key in YEAR_MODELS if key != annual.zr_year_model],
        },
        "levels_emitted": list(ZR_LEVELS_EMITTED),
        **method_receipt("zodiacal_releasing"),
        "method_provenance": ZR_METHOD_PROVENANCE,
        **_source("zodiacal_releasing"),
        "scope": annual.zr_scope,
        "lifetime_window": _lifetime_window_head(annual, annual.zr_scope),
        "lots_producer": "app.core.lots.compute_lots",
        "lords": _lords_receipt(lord_state),
    }
    frame = method_frame_state("lots", req.computation_mode)
    if not frame["applicable"]:
        reason = frame["reason_code"]
    elif any(sample.natal.houses.asc is None for sample in samples):
        reason = REASON_LOTS_NOT_DERIVABLE_FOR_DATE_ONLY
    else:
        reason = None
    if reason is not None:
        return {
            **_not_applicable(reason), **head,
            "window": None, "fortune_spirit_same_sign": None,
            "releases": None, "candidates": None,
            "sensitivity_state": NOT_APPLICABLE_STATE, "interpretation": None,
        }
    completed = annual.completed_years
    by_sample = []
    for sample in samples:
        window = _releasing_window(sample, completed, annual.zr_year_model)
        by_sample.append((sample, window, _releases(sample, window, annual, lord_state["applicable"])))
    signs = [tuple(r["start_sign"] for r in releases) for _, _, releases in by_sample]
    state = _sensitivity(samples, signs)
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    window, releases = next((w, r) for sample, w, r in by_sample if sample.role == _ANCHOR_ROLE)
    # Valens IV.4 releases activity from the next sign when the two share one;
    # flagged, not applied.
    same_sign = releases[0]["start_sign"] == releases[1]["start_sign"]
    return {
        **_computed(),
        **head,
        "window": window,
        "fortune_spirit_same_sign": same_sign if agreed else None,
        "releases": releases if agreed else None,
        # Boundaries move with the birth instant, so a non-exact time lists
        # every sample's periods even when the start signs agree.
        "candidates": None if len(samples) == 1 else [
            {
                "sample_role": sample.role,
                "fortune_sign": sample_releases[0]["start_sign"],
                "spirit_sign": sample_releases[1]["start_sign"],
                "window": sample_window,
                "releases": sample_releases,
            }
            for sample, sample_window, sample_releases in by_sample
        ],
        "sensitivity_state": state,
        "interpretation": None,
    }


# ── decennials (and the sect light's triplicity lords) ─────────────────────
# Kept in their own functions: boundaries are the birth instant plus 30-day
# months, so like every period here they are birth data and are never logged.


def _planet_longitudes(natal: NatalAnchor) -> dict[str, float]:
    """The seven planets' natal longitudes, which decennials and the extended lots read."""
    return {key: natal.positions.bodies_by_key[key]["longitude"] for key in dec.SEVEN_PLANETS}


def _decennial_sample(sample: _Sample, annual, window: dict) -> dict:
    natal = sample.natal
    lifetime = _lifetime_bounds(sample, annual.completed_years, annual.decennials_scope)
    longitudes = _planet_longitudes(natal)
    start = dec.start_planet(
        annual.decennials_start_profile,
        is_day=sample.is_day,
        longitudes=longitudes,
        ascendant=natal.houses.asc,
        requested_planet=annual.decennials_start_planet,
    )
    order = dec.natal_order(longitudes, start)
    return {
        "start_planet": start,
        "order": [{"body_key": key, "longitude_deg": longitudes[key]} for key in order],
        "periods": dec.decennial_periods(
            order=order,
            scope=annual.decennials_scope,
            birth_jd_ut=natal.time.jd_ut,
            window_start_jd_ut=window["start"]["jd_ut"],
            window_end_jd_ut=None if window["end"] is None else window["end"]["jd_ut"],
            lifetime_start_jd_ut=lifetime[0],
            lifetime_end_jd_ut=lifetime[1],
        ),
    }


def _triplicity_of(sample: _Sample, is_day: bool) -> dict:
    bodies = sample.natal.positions.bodies_by_key
    return dec.sect_light_triplicity_lords(
        is_day=is_day,
        sun_sign=_sign_of(bodies["sun"]["longitude"]),
        moon_sign=_sign_of(bodies["moon"]["longitude"]),
    )


def _sect_light_triplicity(req: AnnualRequest, samples: list[_Sample]) -> JsonObject:
    head = {
        "source_ref": "sect_light_triplicity_lords",
        "table": dec.TRIPLICITY_TABLE,
        "periods": None,
        "periods_reason_code": dec.TRIPLICITY_PERIODS_REASON,
    }
    empty = {
        "sect_light": None, "sect_light_sign": None, "element": None, "lords": None,
        "comparison_under_other_sect": None, "candidates": None,
        "sensitivity_state": NOT_APPLICABLE_STATE, "interpretation": None,
    }
    lord_state = lord_frame_state(req.computation_mode)
    if not lord_state["applicable"]:
        return {**_state_fields(not_applicable_receipt(lord_state)), **head, **empty}
    if any(sample.is_day is None for sample in samples):
        return {**_not_applicable(REASON_SECT_UNKNOWN_FOR_DATE_ONLY), **head, **empty}
    results = [_triplicity_of(sample, bool(sample.is_day)) for sample in samples]
    state = _sensitivity(
        samples, [(r["sect_light"], r["sect_light_sign"], tuple(r["lords"])) for r in results]
    )
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    anchor = _anchor_sample(samples)
    top = results[samples.index(anchor)]
    in_band = bool((anchor.natal.sect or {}).get("in_near_horizon_band"))
    return {
        **_computed(),
        **head,
        "sect_light": top["sect_light"] if agreed else None,
        "sect_light_sign": top["sect_light_sign"] if agreed else None,
        "element": top["element"] if agreed else None,
        "lords": top["lords"] if agreed else None,
        # In the Sect band the other classification is shown beside, never applied.
        "comparison_under_other_sect": (
            _triplicity_of(anchor, not anchor.is_day) if in_band and agreed else None
        ),
        "candidates": None if agreed else [
            {"sample_role": sample.role, "is_day": sample.is_day, **result}
            for sample, result in zip(samples, results)
        ],
        "sensitivity_state": state,
        "interpretation": None,
    }


def _decennials(req: AnnualRequest, samples: list[_Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_decennials:
        return None
    profile = annual.decennials_start_profile
    model = YEAR_MODELS[dec.YEAR_MODEL]
    head = {
        "profile": dec.DECENNIALS_PROFILE,
        "start_profile": {
            "profile": profile,
            "input": _input_presence(annual, "decennials_start_profile"),
            "requested_planet": annual.decennials_start_planet,
            "provenance": dec.START_PROFILE_PROVENANCE[profile],
            "condition_assessment": dec.START_CONDITION_ASSESSMENT,
            "other_profiles": [key for key in dec.START_PROFILES if key != profile],
        },
        "order_rule": dec.ORDER_RULE,
        "equal_longitude_rule": dec.EQUAL_LONGITUDE_RULE,
        "year_model": {
            "profile": dec.YEAR_MODEL,
            "days_per_year": float(model["days_per_year"]),
            "days_per_month": float(model["days_per_year"] / 12),
            "months_per_level_1": dec.MONTHS_PER_LEVEL_1,
            "provenance": "attested_valens_vi6",
            "boundary_rule": "birth_jd_ut_plus_accumulated_days",
        },
        "minor_years_ref": "planetary_years",
        "levels_emitted": list(dec.LEVELS_EMITTED),
        **method_receipt("decennials"),
        "method_provenance": dec.METHOD_PROVENANCE,
        **_source("decennials"),
        "scope": annual.decennials_scope,
        "lifetime_window": _lifetime_window_head(annual, annual.decennials_scope),
        "sect_light_triplicity_lords": _sect_light_triplicity(req, samples),
    }
    if profile == dec.START_PROFILES[0] and any(sample.is_day is None for sample in samples):
        reason = REASON_SECT_UNKNOWN_FOR_DATE_ONLY
    elif profile == dec.START_PROFILES[1] and any(
        sample.natal.houses.asc is None for sample in samples
    ):
        reason = REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY
    else:
        reason = None
    if reason is not None:
        return {
            **_not_applicable(reason), **head,
            "window": None, "start_planet": None, "order": None,
            "start_differs_under_other_sect": None, "comparison_start_planet": None,
            "periods": None, "candidates": None,
            "sensitivity_state": NOT_APPLICABLE_STATE, "interpretation": None,
        }
    completed = annual.completed_years
    by_sample = []
    for sample in samples:
        window = _releasing_window(sample, completed, dec.YEAR_MODEL)
        by_sample.append((sample, window, _decennial_sample(sample, annual, window)))
    state = _sensitivity(samples, [
        (result["start_planet"], tuple(row["body_key"] for row in result["order"]))
        for _, _, result in by_sample
    ])
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    anchor, window, top = next(item for item in by_sample if item[0].role == _ANCHOR_ROLE)
    in_band = bool((anchor.natal.sect or {}).get("in_near_horizon_band"))
    sect_start = profile == dec.START_PROFILES[0]
    return {
        **_computed(),
        **head,
        "window": window,
        "start_planet": top["start_planet"] if agreed else None,
        "order": top["order"] if agreed else None,
        # In the Sect band the other luminary is flagged, never applied.
        "start_differs_under_other_sect": True if sect_start and in_band else None,
        "comparison_start_planet": (
            ("moon" if top["start_planet"] == "sun" else "sun") if sect_start and in_band else None
        ),
        "periods": top["periods"] if agreed else None,
        # Boundaries move with the birth instant, so a non-exact time lists
        # every sample's periods even when the order is the same.
        "candidates": None if len(samples) == 1 else [
            {"sample_role": sample.role, "is_day": sample.is_day, "window": sample_window, **result}
            for sample, sample_window, result in by_sample
        ],
        "sensitivity_state": state,
        "interpretation": None,
    }


# ── monthly profection ─────────────────────────────────────────────────────
# The year's twelve months from the profection's own sign; boundaries are
# fractions of the sample's return year, so like every period they are birth
# data and are never logged.


def _monthly_profection(req: AnnualRequest, samples: list[_Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_monthly_profection:
        return None
    completed = annual.completed_years
    profile = annual.monthly_profection_profile
    solar = profile == monthly.PROFILES[0]
    lord_state = lord_frame_state(req.computation_mode)
    head = {
        "profile": profile,
        "profile_input": _input_presence(annual, "monthly_profection_profile"),
        "profile_provenance": monthly.PROFILE_PROVENANCE[profile],
        "other_profiles": [key for key in monthly.PROFILES if key != profile],
        **method_receipt("monthly_profection"),
        "method_provenance": monthly.METHOD_PROVENANCE,
        **_source("monthly_profection"),
        "completed_years": completed,
        "year_of_life": completed + 1,
        "month_model": {
            "months_per_year": monthly.MONTHS_PER_YEAR,
            "first_month_rule": monthly.FIRST_MONTH_RULE,
            "year_boundary_ref": "year_boundary",
            "boundary_rule": SOLAR_MONTH_RULE if solar else FRACTIONAL_YEAR_RULE,
            "return_profile": solar_return_profile(req.computation_mode),
        },
        "lords": _lords_receipt(lord_state),
    }
    signs = [sample.ascendant_sign for sample in samples]
    if any(sign is None for sign in signs):
        return {
            **_not_applicable(REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY), **head,
            "natal_ascendant_sign": None, "year_sign": None, "periods": None,
            "candidates": None, "sensitivity_state": NOT_APPLICABLE_STATE,
            "interpretation": None,
        }

    def months_of(sample: _Sample) -> list[dict]:
        assert sample.ascendant_sign is not None
        clock = sample.clock

        def boundary_at(step: int) -> dict:
            if solar:
                return clock.sun_advanced(completed, step)
            return clock.instant_at_year(Fraction(completed) + Fraction(step, monthly.MONTHS_PER_YEAR))

        return monthly.monthly_profections(
            sample.ascendant_sign,
            completed_years=completed,
            boundary_at=boundary_at,
            name_lords=lord_state["applicable"],
        )

    by_sample = [months_of(sample) for sample in samples]
    state = _sensitivity(samples, signs)
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    anchor = _anchor_sample(samples)
    top = by_sample[samples.index(anchor)]
    return {
        **_computed(),
        **head,
        "natal_ascendant_sign": anchor.ascendant_sign if agreed else None,
        "year_sign": top[0]["sign"] if agreed else None,
        "periods": top if agreed else None,
        # Boundaries move with the birth instant, so a non-exact time lists
        # every sample's months even when the signs are the same.
        "candidates": None if len(samples) == 1 else [
            {
                "sample_role": sample.role,
                "natal_ascendant_sign": sample.ascendant_sign,
                "year_sign": rows[0]["sign"],
                "periods": rows,
            }
            for sample, rows in zip(samples, by_sample)
        ],
        "sensitivity_state": state,
        "interpretation": None,
    }


def _extended_lots_of(sample: _Sample) -> dict:
    natal = sample.natal
    if natal.houses.asc is None:
        raise RuntimeError("extended lots need the ascendant")
    return compute_extended_lots(
        ascendant=natal.houses.asc,
        longitudes=_planet_longitudes(natal),
        lots=natal.lots,
        houses=natal.houses.houses,
    )


def _natal_lots(req: AnnualRequest, samples: list[_Sample]) -> JsonObject | None:
    if not req.annual.include_natal_lots:
        return None
    anchor = _anchor_sample(samples)
    head = {
        **method_receipt("extended_lots"),
        "producer": "app.core.extended_lots.compute_extended_lots",
        "fortune_spirit_producer": "app.core.lots.compute_lots",
        "boundary_policy_ref": "lots/boundary_policy",
    }
    frame = method_frame_state("lots", req.computation_mode)
    if not frame["applicable"]:
        return {**_not_applicable(frame["reason_code"]), **head, "lots": None,
                "samples": None, "sensitivity_state": NOT_APPLICABLE_STATE,
                "interpretation": None}
    if any(sample.natal.houses.asc is None for sample in samples):
        return {**_not_applicable(REASON_LOTS_NOT_DERIVABLE_FOR_DATE_ONLY), **head,
                "lots": None, "samples": None, "sensitivity_state": NOT_APPLICABLE_STATE,
                "interpretation": None}
    results = {sample.role: _extended_lots_of(sample) for sample in samples}
    top = results[anchor.role]
    lots_sect = anchor.natal.lots
    state = NOT_REQUESTED_STATE
    sample_rows = None
    if len(samples) > 1:
        sample_rows = [
            {
                "sample_role": sample.role,
                "sect_applied": results[sample.role]["sect_applied"],
                "lots": [
                    {key: lot[key] for key in ("lot_method_id", "longitude", "sign", "house")}
                    for lot in results[sample.role]["lots"]
                ],
            }
            for sample in samples
        ]
        state = _agreement([
            tuple(lot["sign"] for lot in results[sample.role]["lots"]) for sample in samples
        ])
    return {
        **_computed(),
        **head,
        "sect_status": top["sect_status"],
        "sect_applied": top["sect_applied"],
        "sect_in_near_horizon_band": lots_sect.get("sect_in_near_horizon_band"),
        "sect_named_boundary_disagreement": lots_sect.get("sect_named_boundary_disagreement"),
        "house_system_code": top["house_system_code"],
        "lots": top["lots"],
        "samples": sample_rows,
        "sensitivity_state": state,
        "interpretation": None,
    }


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


# ── Lifetime window and birth-place dates ─────────────────────────────────
#
# Kept apart from the techniques: they read what the techniques emitted and
# the samples' clocks, and add dates; they change no boundary.


def _lifetime_window_head(annual, scope: str) -> JsonObject | None:
    if scope != "lifetime_window":
        return None
    first, last = lifetime_window(annual.completed_years)
    return {"rule": LIFETIME_WINDOW_RULE, "first_completed_years": first,
            "last_completed_years": last}


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
    req: AnnualRequest, samples: list[_Sample], profection: JsonObject | None
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
    anchor = _anchor_sample(samples)
    if profection is None:
        status, reason = MODULE_STATUSES[0], None
    else:
        status, reason = profection["status"], profection["reason_code"]
    signs = [sample.ascendant_sign for sample in samples]
    agreed = len(set(signs)) == 1
    lord_named = lord_frame_state(req.computation_mode)["applicable"]

    def profection_of(sign: str | None, completed: int) -> tuple[str, str | None]:
        assert sign is not None  # computed: every sample has its ascendant
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
        if status == MODULE_STATUSES[1]:
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
        assert offset is not None and abbreviation is not None
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


def compute_annual_response(req: AnnualRequest, *, build_identity: JsonObject) -> JsonObject:
    anchor = compute_natal_anchor(_natal_request(req))
    samples = _samples(req, anchor)
    year_boundary = _year_boundary(req, samples)
    annual_methods = {
        "annual_profection": _profection(req, samples),
        "firdaria": _firdaria(req, samples),
        "zodiacal_releasing": _zodiacal_releasing(req, samples),
        "decennials": _decennials(req, samples),
        "monthly_profection": _monthly_profection(req, samples),
    }
    natal_lots = _natal_lots(req, samples)
    year_boundaries = _year_boundaries(req, samples, annual_methods["annual_profection"])
    _localize_year_boundary(year_boundary, req.timezone)
    dated: list[float] = [
        instant["jd_ut"]
        for record in [year_boundary, *(year_boundaries or {}).get("years", [])]
        for instant in (record["start"], record["end"]) if instant is not None
    ]
    _date_periods(annual_methods, req.timezone, dated)
    trace = anchor.time.trace
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
    trace_steps = trace.as_list()
    response: dict[str, Any] = {
        "schema_version": ANNUAL_SCHEMA_VERSION,
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
        "calculation_dossier": {
            "annual_policy": {
                "year_boundary_definition": YEAR_BOUNDARY_DEFINITION,
                "fractional_year_rule": FRACTIONAL_YEAR_RULE,
                "solar_return_profile": solar_return_profile(req.computation_mode),
                "solver": solver_receipt(req.computation_mode.zodiac),
                "house_system_code": ANNUAL_HOUSE_SYSTEM,
                "period_display_precision": "day",
                "frame_refusals": list(SOLAR_RETURN_FRAME_REFUSAL_CODES),
                "local_dates": _local_date_policy(req, dated),
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
    return response
