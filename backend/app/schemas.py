"""API 請求資料驗證模型。

日期/時區的「語意有效性」（例如 2 月 30 日不存在、IANA 時區名稱是否真實存在）刻意在此
schema 層驗證，而非留給下游計算時才失敗：這樣所有輸入錯誤都統一走 Pydantic 的 422 回應，
格式一致；下游 core/time_utils.py 若仍拋出同類例外，代表的是未預期的內部錯誤，應該讓它
以 500 曝光，而不是被籠統地當成「使用者輸入錯誤」吞掉。

例外：本地時間不存在（時鐘跳過）與本地時間重疊需指定 fold，必須先把日期時間代入時區
規則才知道，所以由 time_utils 拋出 NonexistentLocalTimeError／
AmbiguousLocalTimeChoiceRequiredError，main.py 把它們對應到 422 的
nonexistent_local_time／ambiguous_local_time_choice_required（refusals.py）。
"""

from typing import Literal, Optional

from pydantic import Field, model_validator

from .core.frame_compatibility import solar_return_frame_refusal

# The chart request models live in schema_rules, schema_inputs, schema_chart
# and schema_refusals; this module owns the annual and helper request models.
from .schema_rules import _rule_error, StrictInputModel
from .schema_inputs import AtmosphereInput, ComputationModeInput, DateTimeInput, LocationInput, TimezoneInput
from .schema_chart import _check_leap_second, _check_precision_clock, HouseSystemCode


# The nocturnal node profiles are app.core.firdaria.NOCTURNAL_NODE_PROFILES
# (the schema cannot import that module: it imports time_utils, which imports
# this one); tests/backend/test_annual_route.py binds the two.
NocturnalNodeProfile = Literal[
    "abu_mashar_nodes_after_mercury_v1",
    "bonatti_reading_nodes_after_mars_v1",
]
# The same binding for core.zodiacal_releasing's year models and scopes.
ZodiacalReleasingYearModel = Literal["zr_year_360_days_v1", "zr_year_365_25_days_v1"]
ZodiacalReleasingScope = Literal[
    "intersecting_year", "from_birth_through_year", "lifetime_window"
]
FirdariaScope = Literal["intersecting_year", "full_cycle", "lifetime_window"]
# And for core.decennials: the start profiles, its scopes and the seven
# planets (core.planetary_years.SEVEN_PLANETS) a user-selected start may name.
DecennialsStartProfile = Literal[
    "firmicus_sect_light_v1",
    "valens_first_after_asc_v1",
    "user_selected_planet_v1",
]
DecennialsScope = Literal["intersecting_year", "from_birth_through_year", "lifetime_window"]
# And for core.monthly_profections' month-boundary profiles.
MonthlyProfectionProfile = Literal[
    "monthly_profection_solar_30_degree_months_v1",
    "monthly_profection_return_year_twelfths_v1",
]
ClassicalPlanet = Literal["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]


# Casting the solar-return chart for a place other than the birth place is
# offered (privacy policy 1.2.0 and later disclose the optional place).  Switched off,
# the route refuses `solar_return_location` with a closed-set code instead of
# computing it; the frontend's SOLAR_RETURN_RELOCATION_OFFERED must agree.
SOLAR_RETURN_LOCATION_OFFERED: bool = True


_ANNUAL_TECHNIQUE_SWITCHES: tuple[str, ...] = (
    "include_profection", "include_firdaria", "include_zodiacal_releasing",
    "include_natal_lots", "include_decennials", "include_monthly_profection",
    "include_solar_return_chart",
)
# A technique's switch, the options only it reads, and the refusal when one of
# them is sent without the switch; checked in this order.
_ANNUAL_OPTION_RULES: tuple[tuple[str, frozenset[str], str], ...] = (
    ("include_firdaria", frozenset({"firdaria_nocturnal_node_profile", "firdaria_scope"}),
     "firdaria_option_not_applicable"),
    ("include_zodiacal_releasing", frozenset({"zr_year_model", "zr_scope"}),
     "zodiacal_releasing_option_not_applicable"),
    ("include_decennials",
     frozenset({"decennials_start_profile", "decennials_start_planet", "decennials_scope"}),
     "decennials_option_not_applicable"),
    ("include_monthly_profection", frozenset({"monthly_profection_profile"}),
     "monthly_profection_option_not_applicable"),
    ("include_solar_return_chart",
     frozenset({"solar_return_house_system", "solar_return_location"}),
     "solar_return_chart_option_not_applicable"),
)


class AnnualInput(StrictInputModel):
    """Which year and which annual techniques; no "today" and no server clock."""

    # completed_years N is the return year [SR_N, SR_N+1); year_of_life is N+1.
    # No lifetime cap: a cap would itself be a lifespan claim.  A year whose
    # start falls after 2399 is refused by the route
    # (solar_return_outside_supported_year_range), not here.
    target_kind: Literal["completed_years", "year_of_life"]
    target_value: int = Field(ge=0, le=500)
    include_profection: bool = True
    include_firdaria: bool = False
    firdaria_nocturnal_node_profile: NocturnalNodeProfile = (
        "abu_mashar_nodes_after_mercury_v1"
    )
    firdaria_scope: FirdariaScope = "intersecting_year"
    include_zodiacal_releasing: bool = False
    # The 360-day year of the distribution is the default; another year model
    # is a named alternative the response labels, never merged with it.
    zr_year_model: ZodiacalReleasingYearModel = "zr_year_360_days_v1"
    zr_scope: ZodiacalReleasingScope = "intersecting_year"
    include_natal_lots: bool = False
    # The lifetime window's year boundaries with their profections
    # (core.year_boundary.lifetime_window); not a technique of its own.
    include_year_boundaries: bool = False
    include_decennials: bool = False
    # The sect light (Firmicus) is the default start; the others are named
    # profiles, and only the user-selected one takes a planet.
    decennials_start_profile: DecennialsStartProfile = "firmicus_sect_light_v1"
    decennials_start_planet: Optional[ClassicalPlanet] = None
    decennials_scope: DecennialsScope = "intersecting_year"
    # The twelve months of year N (core.monthly_profections); year N only, so
    # another year's months are asked for by that year.
    include_monthly_profection: bool = False
    # The Sun's 30-degree steps are the default month boundaries; equal
    # twelfths of the return year are a named alternative.
    monthly_profection_profile: MonthlyProfectionProfile = (
        "monthly_profection_solar_30_degree_months_v1"
    )
    # The chart cast at SR_N (annual_pipeline._solar_return_chart).  This route
    # has no natal house-system input, so the calculate page sends the house
    # system its natal chart uses; absent, whole sign as /api/chart's default.
    # No location means the birth location; another place is cast only while
    # SOLAR_RETURN_LOCATION_OFFERED is on.
    include_solar_return_chart: bool = False
    solar_return_house_system: HouseSystemCode = "W"
    solar_return_location: Optional[LocationInput] = None

    @model_validator(mode="after")
    def check_annual_selection(self):
        if self.target_kind == "year_of_life" and self.target_value < 1:
            raise _rule_error("year_of_life_must_be_positive", "target_value")
        if not any(getattr(self, switch) for switch in _ANNUAL_TECHNIQUE_SWITCHES):
            raise _rule_error("annual_request_selects_no_technique")
        for switch, fields, code in _ANNUAL_OPTION_RULES:
            if not getattr(self, switch) and self.model_fields_set & fields:
                raise _rule_error(code)
        if self.solar_return_location is not None and not SOLAR_RETURN_LOCATION_OFFERED:
            raise _rule_error("solar_return_location_not_yet_offered", "solar_return_location")
        user_selected = self.decennials_start_profile == "user_selected_planet_v1"
        if user_selected and self.decennials_start_planet is None:
            raise _rule_error("decennials_start_planet_required", "decennials_start_planet")
        if not user_selected and self.decennials_start_planet is not None:
            raise _rule_error("decennials_start_planet_not_applicable", "decennials_start_planet")
        return self

    @property
    def completed_years(self) -> int:
        return self.target_value - (1 if self.target_kind == "year_of_life" else 0)


class AnnualRequest(StrictInputModel):
    """The flagged annual route: the natal fields of ChartRequest plus `annual`."""

    birth_time_precision: Literal[
        "exact", "approximate_hour", "date_only"
    ] = "exact"
    datetime: DateTimeInput
    timezone: TimezoneInput
    location: LocationInput
    atmosphere: AtmosphereInput = Field(default_factory=AtmosphereInput)
    computation_mode: ComputationModeInput = Field(default_factory=ComputationModeInput)
    annual: AnnualInput

    @model_validator(mode="after")
    def check_annual_request(self):
        _check_leap_second(self)
        _check_precision_clock(self)
        # Every annual technique reads the solar-return year boundary, so the
        # frame its root needs is the route's (central table).
        refusal = solar_return_frame_refusal(self.computation_mode)
        if refusal is not None:
            raise _rule_error(refusal, "computation_mode")
        return self


class TimeConversionRequest(StrictInputModel):
    """One wall-clock time and its zone, for the calculate page's conversion helper.

    The answer lists every reading of the time, so a fold is not asked for; and
    the helper reads clock offsets, which a leap second's label does not change,
    so second 60 is refused rather than given its own rule here.
    """

    datetime: DateTimeInput
    timezone: TimezoneInput

    @model_validator(mode="after")
    def check_helper_fields(self):
        if "fold" in self.timezone.model_fields_set:
            raise _rule_error("fold_not_accepted_by_time_conversion", "timezone", "fold")
        if self.datetime.second == 60:
            raise _rule_error(
                "leap_second_not_accepted_by_time_conversion", "datetime", "second"
            )
        return self


class PlaceSearchRequest(StrictInputModel):
    query: str = Field(min_length=1, max_length=100)
    country_code: Optional[str] = Field(
        default=None,
        pattern=r"^[A-Z]{2}$",
    )
    limit: int = Field(default=10, ge=1, le=20)
