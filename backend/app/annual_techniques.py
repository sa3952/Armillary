"""The annual route's time-lord techniques, each one block in one envelope.

Every block states whether it was computed (``status``), the head of what was
asked and by which method, its result fields, and never an interpretation.
Each technique reads the samples' natal anchors and solar-return clocks only.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Final

from .annual_samples import (
    REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY,
    REASON_LOTS_NOT_DERIVABLE_FOR_DATE_ONLY,
    REASON_SECT_UNKNOWN_FOR_DATE_ONLY,
    SECT_PRODUCER,
    Sample,
    anchor_sample,
)
from .chart_pipeline import JsonObject, NatalAnchor
from .core import decennials as dec
from .core import monthly_profections as monthly
from .core.birth_time_sensitivity import (
    DIFFERS_BETWEEN_SAMPLES,
    NOT_APPLICABLE_STATE,
    NOT_REQUESTED_STATE,
    SAME_AT_ALL_SAMPLES,
)
from .core.dignity_tables import SIGNS
from .core.extended_lots import compute_extended_lots
from .core.firdaria import FIRDARIA_PROFILE, firdaria_periods, period_instant
from .core.formatting import zodiac_sign_index
from .core.frame_compatibility import method_frame_state
from .core.invariants import InternalInvariantError
from .core.method_status import method_receipt
from .core.module_state import (
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
from .core.year_boundary import (
    COMPUTED,
    FRACTIONAL_YEAR_RULE,
    LIFETIME_WINDOW_RULE,
    RANGE_END_JD_UT,
    SOLAR_MONTH_RULE,
    lifetime_window,
    solar_return_profile,
)
from .core.zodiacal_releasing import (
    LEVELS_EMITTED as ZR_LEVELS_EMITTED,
    METHOD_PROVENANCE as ZR_METHOD_PROVENANCE,
    RELEASING_FROM,
    PeriodBounds,
    RELEASING_PROFILE,
    SIGN_PERIOD_TABLE_PROFILE,
    YEAR_MODELS,
    elapsed_distribution_time,
    releasing_periods,
)
from .method_sources import resolve
from .schemas import AnnualInput, AnnualRequest


def _state_fields(state: dict) -> dict:
    return {**state, "status": module_status_word(state)}


# One envelope for every technique block: its state, its head (what was asked
# and by which method), its result fields, and never an interpretation.


def _withheld(
    head: JsonObject, fields: tuple[str, ...], reason_code: str | None = None,
    *, state: dict | None = None,
) -> JsonObject:
    """A technique that is not applicable: every result field withheld."""

    receipt = not_applicable_receipt(state or {"applicable": False, "reason_code": reason_code})
    return {
        **_state_fields(receipt),
        **head,
        **{key: NOT_APPLICABLE_STATE if key == "sensitivity_state" else None for key in fields},
        "interpretation": None,
    }


def _technique(head: JsonObject, body: JsonObject) -> JsonObject:
    """A computed technique: ``body`` holds the result fields in print order."""

    return {
        **_state_fields(computed_receipt(PRODUCT_FORMULA_SOURCE)),
        **head,
        **body,
        "interpretation": None,
    }


def _anchor_result(samples: list[Sample], results: list):
    return results[samples.index(anchor_sample(samples))]


def _lots_reason(req: AnnualRequest, samples: list[Sample]) -> str | None:
    """Why the Lots cannot be derived for this request, or None."""

    frame = method_frame_state("lots", req.computation_mode)
    if not frame["applicable"]:
        return frame["reason_code"]
    if any(sample.natal.houses.asc is None for sample in samples):
        return REASON_LOTS_NOT_DERIVABLE_FOR_DATE_ONLY
    return None

def _lords_receipt(lord_state: dict) -> dict:
    """The domicile-lord table a technique names its lords from, and whether
    the frame lets it name them."""
    if lord_state["applicable"]:
        return {**computed_receipt(LORD_TABLE), "table": LORD_TABLE}
    return {**not_applicable_receipt(lord_state), "table": LORD_TABLE}


def _input_presence(annual: AnnualInput, field: str) -> str:
    return "explicit" if field in annual.model_fields_set else "defaulted"


def source_head(ref: str) -> dict[str, str]:
    """A technique head's register ref; how far each of its citations was read
    is stated in the published register's entry, which the ref must name."""
    resolve(ref)
    return {"source_ref": ref}


def _agreement(values: list) -> str:
    return SAME_AT_ALL_SAMPLES if len(set(values)) == 1 else DIFFERS_BETWEEN_SAMPLES


def _sensitivity(samples: list[Sample], values: list) -> str:
    return NOT_REQUESTED_STATE if len(samples) == 1 else _agreement(values)


_PROFECTION_FIELDS = (
    "natal_ascendant_sign", "offset_signs", "profected_sign", "profected_place", "lord",
    "sensitivity_state", "candidates",
)


def _profection(req: AnnualRequest, samples: list[Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_profection:
        return None
    completed = annual.completed_years
    head = {
        "profile": PROFECTION_PROFILE,
        **method_receipt("annual_profection"),
        "method_provenance": PROFECTION_PROVENANCE,
        **source_head("annual_profection"),
        "age_input_kind": annual.target_kind,
        "completed_years": completed,
        "year_of_life": completed + 1,
        "year_boundary_ref": "year_boundary",
    }
    signs = [sample.ascendant_sign for sample in samples]
    if any(sign is None for sign in signs):
        return _withheld(head, _PROFECTION_FIELDS, REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY)
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

    return _technique(head, {
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
    })


_FIRDARIA_FIELDS = (
    "nocturnal_node_profile_applies", "method_provenance", "cycle_index", "periods",
    "candidates", "sensitivity_state",
)


def _firdaria(req: AnnualRequest, samples: list[Sample]) -> JsonObject | None:
    annual = req.annual
    if not annual.include_firdaria:
        return None
    sect = anchor_sample(samples).natal.sect or {}
    head = {
        "profile": FIRDARIA_PROFILE,
        "nocturnal_node_profile": annual.firdaria_nocturnal_node_profile,
        "nocturnal_node_profile_input": _input_presence(annual, "firdaria_nocturnal_node_profile"),
        **method_receipt("firdaria"),
        **source_head("firdaria"),
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
        "lifetime_window": lifetime_window_head(annual, annual.firdaria_scope),
    }
    day_flags = [sample.is_day for sample in samples]
    if any(flag is None for flag in day_flags):
        return _withheld(head, _FIRDARIA_FIELDS, REASON_SECT_UNKNOWN_FOR_DATE_ONLY)
    by_sample = [
        firdaria_periods(
            is_day=bool(sample.is_day),
            nocturnal_node_profile=annual.firdaria_nocturnal_node_profile,
            scope=annual.firdaria_scope,
            completed_years=annual.completed_years,
            instant_at_year=sample.clock.instant_at_year,
        )
        for sample in samples
    ]
    state = _sensitivity(samples, day_flags)
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    top = _anchor_result(samples, by_sample)
    return _technique(head, {
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
    })


def _sign_of(longitude: float) -> str:
    return SIGNS[zodiac_sign_index(longitude)]


def _releasing_window(sample: Sample, completed: int, year_model: str) -> dict:
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


def _period_bounds(sample: Sample, window: dict, completed: int, scope: str) -> PeriodBounds:
    """The window and lifetime-window JD(UT) bounds a period builder reads.

    A lifetime end after the supported years is the range end: the window
    then holds what the product can date.
    """

    lifetime: tuple[float | None, float | None] = (None, None)
    if scope == "lifetime_window":
        first, last = lifetime_window(completed)
        start, end = sample.clock.root(first), sample.clock.root(last + 1)
        lifetime = (start["jd_ut"], end["jd_ut"] if end["status"] == COMPUTED else RANGE_END_JD_UT)
    return PeriodBounds(
        scope=scope,
        birth_jd_ut=sample.natal.time.jd_ut,
        window_start_jd_ut=window["start"]["jd_ut"],
        window_end_jd_ut=None if window["end"] is None else window["end"]["jd_ut"],
        lifetime_start_jd_ut=lifetime[0],
        lifetime_end_jd_ut=lifetime[1],
    )


def _releases(sample: Sample, window: dict, annual, name_lords: bool) -> list[dict]:
    lots = sample.natal.lots
    bounds = _period_bounds(sample, window, annual.completed_years, annual.zr_scope)
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
                start_sign=sign, fortune_sign=fortune_sign, year_model=annual.zr_year_model,
                name_lords=name_lords, bounds=bounds,
            ),
        })
    return rows


_RELEASING_FIELDS = (
    "window", "fortune_spirit_same_sign", "releases", "candidates", "sensitivity_state",
)


def _zodiacal_releasing(req: AnnualRequest, samples: list[Sample]) -> JsonObject | None:
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
        **source_head("zodiacal_releasing"),
        "scope": annual.zr_scope,
        "lifetime_window": lifetime_window_head(annual, annual.zr_scope),
        "lots_producer": "app.core.lots.compute_lots",
        "lords": _lords_receipt(lord_state),
    }
    reason = _lots_reason(req, samples)
    if reason is not None:
        return _withheld(head, _RELEASING_FIELDS, reason)
    by_sample = []
    for sample in samples:
        window = _releasing_window(sample, annual.completed_years, annual.zr_year_model)
        by_sample.append((sample, window, _releases(sample, window, annual, lord_state["applicable"])))
    signs = [tuple(r["start_sign"] for r in releases) for _, _, releases in by_sample]
    state = _sensitivity(samples, signs)
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    _, window, releases = _anchor_result(samples, by_sample)
    # Valens IV.4 releases activity from the next sign when the two share one;
    # flagged, not applied.
    same_sign = releases[0]["start_sign"] == releases[1]["start_sign"]
    return _technique(head, {
        "window": window,
        "fortune_spirit_same_sign": same_sign if agreed else None,
        "releases": releases if agreed else None,
        # Every sample's periods, as in _firdaria.
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
    })


# Decennials: boundaries are the birth instant plus 30-day months, so like
# every period here they are birth data and are never logged.


def _planet_longitudes(natal: NatalAnchor) -> dict[str, float]:
    return {key: natal.positions.bodies_by_key[key]["longitude"] for key in dec.SEVEN_PLANETS}


def _decennial_sample(sample: Sample, annual, window: dict) -> dict:
    natal = sample.natal
    bounds = _period_bounds(sample, window, annual.completed_years, annual.decennials_scope)
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
        "periods": dec.decennial_periods(order=order, bounds=bounds),
    }


def _triplicity_of(sample: Sample, is_day: bool) -> dict:
    bodies = sample.natal.positions.bodies_by_key
    return dec.sect_light_triplicity_lords(
        is_day=is_day,
        sun_sign=_sign_of(bodies["sun"]["longitude"]),
        moon_sign=_sign_of(bodies["moon"]["longitude"]),
    )


_TRIPLICITY_FIELDS = (
    "sect_light", "sect_light_sign", "element", "lords", "comparison_under_other_sect",
    "candidates", "sensitivity_state",
)


def _sect_light_triplicity(req: AnnualRequest, samples: list[Sample]) -> JsonObject:
    head = {
        "source_ref": "sect_light_triplicity_lords",
        "table": dec.TRIPLICITY_TABLE,
        "periods": None,
        "periods_reason_code": dec.TRIPLICITY_PERIODS_REASON,
    }
    lord_state = lord_frame_state(req.computation_mode)
    if not lord_state["applicable"]:
        return _withheld(head, _TRIPLICITY_FIELDS, state=lord_state)
    if any(sample.is_day is None for sample in samples):
        return _withheld(head, _TRIPLICITY_FIELDS, REASON_SECT_UNKNOWN_FOR_DATE_ONLY)
    results = [_triplicity_of(sample, bool(sample.is_day)) for sample in samples]
    state = _sensitivity(
        samples, [(r["sect_light"], r["sect_light_sign"], tuple(r["lords"])) for r in results]
    )
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    anchor = anchor_sample(samples)
    top = _anchor_result(samples, results)
    in_band = bool((anchor.natal.sect or {}).get("in_near_horizon_band"))
    return _technique(head, {
        **{key: top[key] if agreed else None
           for key in ("sect_light", "sect_light_sign", "element", "lords")},
        # In the Sect band the other classification is shown beside, never applied.
        "comparison_under_other_sect": (
            _triplicity_of(anchor, not anchor.is_day) if in_band and agreed else None
        ),
        "candidates": None if agreed else [
            {"sample_role": sample.role, "is_day": sample.is_day, **result}
            for sample, result in zip(samples, results)
        ],
        "sensitivity_state": state,
    })


_DECENNIALS_FIELDS = (
    "window", "start_planet", "order", "start_differs_under_other_sect",
    "comparison_start_planet", "periods", "candidates", "sensitivity_state",
)


def _decennials(req: AnnualRequest, samples: list[Sample]) -> JsonObject | None:
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
        **source_head("decennials"),
        "scope": annual.decennials_scope,
        "lifetime_window": lifetime_window_head(annual, annual.decennials_scope),
        "sect_light_triplicity_lords": _sect_light_triplicity(req, samples),
    }
    sect_start = profile == dec.START_PROFILES[0]
    if sect_start and any(sample.is_day is None for sample in samples):
        return _withheld(head, _DECENNIALS_FIELDS, REASON_SECT_UNKNOWN_FOR_DATE_ONLY)
    if profile == dec.START_PROFILES[1] and any(
        sample.natal.houses.asc is None for sample in samples
    ):
        return _withheld(head, _DECENNIALS_FIELDS, REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY)
    by_sample = []
    for sample in samples:
        window = _releasing_window(sample, annual.completed_years, dec.YEAR_MODEL)
        by_sample.append((sample, window, _decennial_sample(sample, annual, window)))
    state = _sensitivity(samples, [
        (result["start_planet"], tuple(row["body_key"] for row in result["order"]))
        for _, _, result in by_sample
    ])
    agreed = state != DIFFERS_BETWEEN_SAMPLES
    anchor, window, top = _anchor_result(samples, by_sample)
    in_band = sect_start and bool((anchor.natal.sect or {}).get("in_near_horizon_band"))
    return _technique(head, {
        "window": window,
        "start_planet": top["start_planet"] if agreed else None,
        "order": top["order"] if agreed else None,
        # In the Sect band the other luminary is flagged, never applied.
        "start_differs_under_other_sect": True if in_band else None,
        "comparison_start_planet": (
            ("moon" if top["start_planet"] == "sun" else "sun") if in_band else None
        ),
        "periods": top["periods"] if agreed else None,
        # Every sample's periods, as in _firdaria.
        "candidates": None if len(samples) == 1 else [
            {"sample_role": sample.role, "is_day": sample.is_day, "window": sample_window, **result}
            for sample, sample_window, result in by_sample
        ],
        "sensitivity_state": state,
    })


# Monthly profection: boundaries are fractions of the sample's return year,
# so like every period they are birth data and are never logged.

_MONTHLY_FIELDS = (
    "natal_ascendant_sign", "year_sign", "periods", "candidates", "sensitivity_state",
)


def _monthly_profection(req: AnnualRequest, samples: list[Sample]) -> JsonObject | None:
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
        **source_head("monthly_profection"),
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
        return _withheld(head, _MONTHLY_FIELDS, REASON_ASCENDANT_UNKNOWN_FOR_DATE_ONLY)

    def months_of(sample: Sample) -> list[dict]:
        if sample.ascendant_sign is None:
            raise InternalInvariantError("sample.ascendant_sign is not None")
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
    top = _anchor_result(samples, by_sample)
    return _technique(head, {
        "natal_ascendant_sign": anchor_sample(samples).ascendant_sign if agreed else None,
        "year_sign": top[0]["sign"] if agreed else None,
        "periods": top if agreed else None,
        # Every sample's months, as in _firdaria.
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
    })


def _extended_lots_of(sample: Sample) -> dict:
    natal = sample.natal
    if natal.houses.asc is None:
        raise RuntimeError("extended lots need the ascendant")
    return compute_extended_lots(
        ascendant=natal.houses.asc,
        longitudes=_planet_longitudes(natal),
        lots=natal.lots,
        houses=natal.houses.houses,
    )


_NATAL_LOTS_ROW_KEYS = ("lot_method_id", "longitude", "sign", "house")


def natal_lots_block(req: AnnualRequest, samples: list[Sample]) -> JsonObject | None:
    if not req.annual.include_natal_lots:
        return None
    head = {
        **method_receipt("extended_lots"),
        "producer": "app.core.extended_lots.compute_extended_lots",
        "fortune_spirit_producer": "app.core.lots.compute_lots",
        "boundary_policy_ref": "lots/boundary_policy",
    }
    reason = _lots_reason(req, samples)
    if reason is not None:
        return _withheld(head, ("lots", "samples", "sensitivity_state"), reason)
    results = [_extended_lots_of(sample) for sample in samples]
    top = _anchor_result(samples, results)
    lots_sect = anchor_sample(samples).natal.lots
    several = len(samples) > 1
    return _technique(head, {
        "sect_status": top["sect_status"],
        "sect_applied": top["sect_applied"],
        "sect_in_near_horizon_band": lots_sect.get("sect_in_near_horizon_band"),
        "sect_named_boundary_disagreement": lots_sect.get("sect_named_boundary_disagreement"),
        "house_system_code": top["house_system_code"],
        "lots": top["lots"],
        "samples": [
            {
                "sample_role": sample.role,
                "sect_applied": result["sect_applied"],
                "lots": [{key: lot[key] for key in _NATAL_LOTS_ROW_KEYS} for lot in result["lots"]],
            }
            for sample, result in zip(samples, results)
        ] if several else None,
        "sensitivity_state": _agreement(
            [tuple(lot["sign"] for lot in result["lots"]) for result in results]
        ) if several else NOT_REQUESTED_STATE,
    })



def lifetime_window_head(annual, scope: str) -> JsonObject | None:
    if scope != "lifetime_window":
        return None
    first, last = lifetime_window(annual.completed_years)
    return {"rule": LIFETIME_WINDOW_RULE, "first_completed_years": first,
            "last_completed_years": last}



# The time-lord techniques the route computes, in the order the response
# prints them under `annual_methods`.  The public pages name the techniques
# this site offers from these keys (scripts/frontend/build_pages.py).
ANNUAL_TECHNIQUES: Final = {
    "annual_profection": _profection,
    "firdaria": _firdaria,
    "zodiacal_releasing": _zodiacal_releasing,
    "decennials": _decennials,
    "monthly_profection": _monthly_profection,
}
