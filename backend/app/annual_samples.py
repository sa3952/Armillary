"""The annual route's representative samples: one natal anchor per instant.

An exact birth time has one sample, the anchor; a non-exact time has the
stated hour's or civil day's first and last real seconds beside it, each with
its own natal anchor and solar-return clock, side by side and never merged.
"""

from __future__ import annotations

import datetime as dtmod
from typing import Literal

import swisseph as swe

from .chart_pipeline import NatalAnchor, compute_natal_anchor
from .core.dignity_tables import SIGNS
from .core.formatting import zodiac_sign_index
from .core.invariants import InternalInvariantError
from .core.time_utils import REPRESENTATIVE_SAMPLE_ROLES, representative_sample_instants
from .core.year_boundary import SolarReturnClock
from .schemas import AnnualRequest
from .schema_chart import ChartRequest, OptionsInput
from .schema_inputs import DateTimeInput, TimezoneInput

# Lots and their houses on the annual route are whole-sign (the profection's own
# frame); the route takes no house-system option.
ANNUAL_HOUSE_SYSTEM: Literal["W"] = "W"
NATAL_OPTIONS = OptionsInput(
    include_houses=True,
    house_system=ANNUAL_HOUSE_SYSTEM,
    include_lots=True,
    include_aspects=False,
)
ANCHOR_ROLE = REPRESENTATIVE_SAMPLE_ROLES[1]
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



class Sample:
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


def utc_instant_request(
    req: AnnualRequest, utc_text: str, *, location, options: OptionsInput,
) -> ChartRequest:
    # An instant the route already resolved, posed as that UTC instant (fixed
    # offset 0) and not re-validated: a sample of a 1900-01-01 birth east of
    # Greenwich is a 1899 UTC date.
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
        location=location,
        atmosphere=req.atmosphere,
        computation_mode=req.computation_mode,
        options=options,
    )


def natal_request(req: AnnualRequest) -> ChartRequest:
    return ChartRequest(
        birth_time_precision=req.birth_time_precision,
        datetime=req.datetime,
        timezone=req.timezone,
        location=req.location,
        atmosphere=req.atmosphere,
        computation_mode=req.computation_mode,
        options=NATAL_OPTIONS,
    )


def representative_samples(req: AnnualRequest, anchor: NatalAnchor) -> list[Sample]:
    """The anchor alone for an exact time; else the three samples in role order."""

    zodiac = req.computation_mode.zodiac
    if req.birth_time_precision == "exact":
        return [Sample(ANCHOR_ROLE, anchor, zodiac)]
    if anchor.time.anchor_utc is None:  # resolved for every non-exact chart
        raise InternalInvariantError("anchor.time.anchor_utc is not None")
    instants = representative_sample_instants(
        req.datetime,
        req.timezone,
        precision=req.birth_time_precision,
        anchor_utc=anchor.time.anchor_utc,
        civil_day=anchor.time.civil_day,
    )
    return [
        Sample(instant["sample_role"], anchor, zodiac, _sample_reference(instant))
        if instant["sample_role"] == ANCHOR_ROLE
        else Sample(
            instant["sample_role"],
            compute_natal_anchor(utc_instant_request(
                req, instant["reference_utc_time"], location=req.location, options=NATAL_OPTIONS,
            )),
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

def anchor_sample(samples: list[Sample]) -> Sample:
    return next(sample for sample in samples if sample.role == ANCHOR_ROLE)
