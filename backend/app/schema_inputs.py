"""The birth inputs: date and time, time zone, place, atmosphere and the
computation mode."""

import datetime as _dt
from typing import Any, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ConfigDict, Field, model_validator

from .core.civil_time_basis import CIVIL_TIME_BASIS_ZONES, CivilTimeBasis
from .core.time_utils import exact_second_microseconds
from .core.frame_compatibility import request_frame_refusal
from .domain_catalog import (
    AYANAMSA_OPTIONS,
    DEFAULT_ATMOSPHERE_TEMPERATURE_C,
    PRODUCT_YEAR_RANGE,
)
from .schema_rules import (
    StrictInputModel,
    _PORTABLE_IANA_TIMEZONE_KEYS,
    _first_forbidden_label_codepoint,
    _label_has_base_character,
    _rule_error,
)


class DateTimeInput(StrictInputModel):
    # The public request boundary is owned by PRODUCT_YEAR_RANGE. Bundled Swiss
    # files reach farther into the past, but expanding the product boundary is
    # deferred until schema/UI/Dossier/event validation can move together.
    year: int = Field(ge=PRODUCT_YEAR_RANGE[0], le=PRODUCT_YEAR_RANGE[1])
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    second: float = Field(ge=0, le=60, default=0.0)

    @model_validator(mode="after")
    def check_valid_calendar_date(self):
        try:
            _dt.date(self.year, self.month, self.day)
        except ValueError:
            raise _rule_error("calendar_date_invalid", "day") from None
        if exact_second_microseconds(self.second) is None:
            raise _rule_error("second_finer_than_microsecond", "second")
        return self


def _conditional_rules(
    field: str, rules: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    return {
        "allOf": [
            {
                "if": {
                    "properties": {field: {"const": value}},
                    "required": [field],
                },
                "then": rule,
            }
            for value, rule in rules.items()
        ]
    }


_TIMEZONE_SCHEMA_RULES: dict[str, dict[str, Any]] = {
    "iana": {
        "properties": {"iana_name": {"minLength": 1, "type": "string"}},
        "required": ["iana_name"],
    },
    "fixed_offset": {
        "properties": {
            "utc_offset_hours": {"maximum": 14.0, "minimum": -14.0, "type": "number"},
            "fold": {"const": 0},
            "civil_time_basis": {"type": "null"},
        },
        "required": ["utc_offset_hours"],
    },
}
_TIMEZONE_SCHEMA = _conditional_rules("mode", _TIMEZONE_SCHEMA_RULES)
_TIMEZONE_SCHEMA["allOf"].extend(
    _conditional_rules("civil_time_basis", {
        basis: {"properties": {"iana_name": {"const": zone}}, "required": ["iana_name"]}
        for basis, zone in CIVIL_TIME_BASIS_ZONES.items()
    })["allOf"]
)


class TimezoneInput(StrictInputModel):
    model_config = ConfigDict(
        json_schema_extra=_TIMEZONE_SCHEMA
    )
    mode: Literal["iana", "fixed_offset"]
    iana_name: Optional[str] = None
    utc_offset_hours: Optional[float] = Field(default=None, ge=-14, le=14)
    # PEP 495 fold：本地時間在 DST 轉換附近可能模糊（同一時鐘時間對應兩個 UTC），
    # 0=較早/夏令的那一次(預設)，1=較晚/標準時間的那一次。只在 mode='iana' 時有意義。
    fold: int = Field(default=0, ge=0, le=1)
    # Which clock the birth record uses, for a place that keeps two (Xinjiang:
    # Beijing time or Xinjiang time).  It names the record's clock; iana_name
    # still carries the zone, and the two must agree.  Whether the place needs
    # it is the catalogue's to say, or for manual coordinates the zone's
    # (core.civil_time_basis), checked at the route.
    civil_time_basis: Optional[CivilTimeBasis] = None

    _MODE_FIELDS = {"iana": "iana_name", "fixed_offset": "utc_offset_hours"}

    @model_validator(mode="after")
    def check_fields(self):
        inert = [
            field
            for mode, field in self._MODE_FIELDS.items()
            if mode != self.mode and getattr(self, field) is not None
        ]
        if inert:
            raise _rule_error(
                "timezone_field_not_applicable_to_mode", sorted(inert)[0]
            )
        if self.mode == "iana":
            if not self.iana_name:
                raise _rule_error("iana_name_required", "iana_name")
            if self.iana_name not in _PORTABLE_IANA_TIMEZONE_KEYS:
                raise _rule_error("iana_timezone_unknown", "iana_name")
            try:
                ZoneInfo(self.iana_name)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                # ZoneInfo raises ValueError for an absolute or `..` key; catch
                # it here rather than rely on Pydantic converting it.  The value
                # is not echoed: no reliance on the hosted response sanitizer.
                raise _rule_error("iana_timezone_unknown", "iana_name") from exc
        if self.mode == "fixed_offset":
            if self.utc_offset_hours is None:
                raise _rule_error("utc_offset_hours_required", "utc_offset_hours")
            # 固定偏移沒有 DST 轉換，fold 不會有任何作用。與其靜默忽略讓使用者誤以為
            # 自己已經選到了另一種 DST 解讀，不如明確拒絕。
            if self.fold != 0:
                raise _rule_error("fold_requires_iana_mode", "fold")
        if (
            self.civil_time_basis is not None
            and (
                self.mode != "iana"
                or self.iana_name != CIVIL_TIME_BASIS_ZONES[self.civil_time_basis]
            )
        ):
            raise _rule_error("civil_time_basis_zone_mismatch", "civil_time_basis")
        return self


_LOCATION_PRECISIONS = {
    "manual": ("user_supplied_coordinates", "unknown"),
    "geonames_cities500": ("place_representative_point",),
    "taiwan_moi_place_names": (
        "settlement_representative_point",
        "administrative_area_representative_point",
    ),
}


def _precision_schema(source: str) -> dict[str, Any]:
    values = _LOCATION_PRECISIONS[source]
    return {"const": values[0]} if len(values) == 1 else {"enum": list(values)}


_MANUAL_LOCATION_SCHEMA = {
    "properties": {
        "source_record_id": {"type": "null"},
        "location_precision": _precision_schema("manual"),
    }
}
_LOCATION_SCHEMA_RULES: dict[str, dict[str, Any]] = {
    "manual": _MANUAL_LOCATION_SCHEMA,
    **{
        source: {
            "properties": {
                "place_label": {"type": "string", "minLength": 1},
                "source_record_id": {"type": "string", "minLength": 1},
                "location_precision": _precision_schema(source),
            },
            "required": ["place_label", "source_record_id", "location_precision"],
        }
        for source in ("geonames_cities500", "taiwan_moi_place_names")
    },
}
_LOCATION_SCHEMA = _conditional_rules("location_source", _LOCATION_SCHEMA_RULES)
_LOCATION_SCHEMA["allOf"].insert(0, {
    "if": {"not": {"required": ["location_source"]}},
    "then": _MANUAL_LOCATION_SCHEMA,
})


class LocationInput(StrictInputModel):
    model_config = ConfigDict(json_schema_extra=_LOCATION_SCHEMA)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    altitude_m: float = Field(default=0.0, ge=-500, le=10000)
    place_label: Optional[str] = Field(default=None, min_length=1, max_length=200)
    location_source: Literal[
        "manual",
        "geonames_cities500",
        "taiwan_moi_place_names",
    ] = "manual"
    source_record_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    location_precision: Literal[
        "user_supplied_coordinates",
        "place_representative_point",
        "settlement_representative_point",
        "administrative_area_representative_point",
        "unknown",
    ] = "user_supplied_coordinates"

    @model_validator(mode="after")
    def check_place_label_has_no_control_or_bidi_codepoints(self):
        if self.place_label is None:
            return self
        forbidden = _first_forbidden_label_codepoint(self.place_label)
        if forbidden is not None:
            # Reported as U+XXXX, never echoed: no invisible or direction-
            # flipping character in an error string other surfaces render.
            raise _rule_error(
                "place_label_forbidden_codepoint",
                "place_label",
                note=f"U+{ord(forbidden):04X}",
            )
        if not _label_has_base_character(self.place_label):
            # Only combining marks or joiners: nothing a reader can see or
            # tell apart from another such label.
            raise _rule_error("place_label_has_no_base_character", "place_label")
        return self

    @model_validator(mode="after")
    def check_location_resolution_receipt(self):
        if self.location_precision not in _LOCATION_PRECISIONS[
            self.location_source
        ]:
            raise _rule_error(
                "location_precision_not_accepted_for_source", "location_precision"
            )
        if self.location_source == "manual":
            if self.source_record_id is not None:
                raise _rule_error(
                    "source_record_id_not_allowed_for_manual", "source_record_id"
                )
            return self

        if not self.place_label or not self.source_record_id:
            raise _rule_error(
                "catalog_location_requires_label_and_record_id",
                "place_label" if not self.place_label else "source_record_id",
            )
        return self


class AtmosphereInput(StrictInputModel):
    """Swiss refracted-altitude inputs; None pressure means Swiss estimates it from altitude."""

    pressure_hpa: Optional[float] = Field(default=None, gt=0, le=1100)
    # Swiss refracts by iterating its formula; colder than about -43 C at
    # 1100 hPa the iteration lifts directions several degrees below the horizon
    # to a positive apparent altitude (false rises and sets, a sunk Sun reported
    # above the horizon).  -40 C keeps every accepted input inside the domain
    # where it does not.
    temperature_c: float = Field(
        default=DEFAULT_ATMOSPHERE_TEMPERATURE_C, ge=-40, le=60
    )


class ComputationModeInput(StrictInputModel):
    """統一計算模式：一次設定，套用到本次請求的所有星體計算。"""

    center: Literal["geocentric", "topocentric", "heliocentric", "barycentric"] = "geocentric"
    zodiac: Literal["tropical", "sidereal"] = "tropical"
    ayanamsa: Literal["fagan_bradley", "hipparchos", "sassanian", "aldebaran_15_tau"] = "fagan_bradley"
    position_mode: Literal["apparent", "true"] = "apparent"
    ecliptic_frame: Literal["of_date", "j2000"] = "of_date"
    nutation: bool = True

    @model_validator(mode="after")
    def check_ayanamsa(self):
        if self.zodiac == "sidereal" and self.ayanamsa not in AYANAMSA_OPTIONS:
            raise _rule_error("ayanamsa_unsupported", "ayanamsa")
        # 拒絕的框架組合由中央相容表決定，錯誤型別即該表
        # 的閉集理由碼。恆星黃道＋J2000 下收據與實際扣除量不同，故拒絕而不輸出。
        refusal = request_frame_refusal(self)
        if refusal is not None:
            raise _rule_error(refusal)
        return self
