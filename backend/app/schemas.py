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

import datetime as _dt
import json
from decimal import Decimal
import re
import typing
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Literal, Optional
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    JsonValue,
    create_model,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticCustomError, core_schema

from .core.civil_time_basis import CIVIL_TIME_BASIS_ZONES, CivilTimeBasis
from .core.frame_compatibility import (
    REQUEST_FRAME_REFUSAL_CODES,
    request_frame_refusal,
)
from .refusals import REFUSAL_DETAIL_EXTRAS, REFUSALS


# Every validation rule has one closed code, raised through
# `_rule_error`, mapped here to the model that owns it.  22 rule branches used
# to reach a client as 9 distinguishable outcomes — most of them `value_error`
# with a location that stopped at the model.  A rule about one field names that
# field in the error context, so the refusal's `loc` ends at it; a rule about a
# combination keeps `loc` at the model and its code names the combination.
REQUEST_VALIDATION_RULES: dict[str, str] = {
    "calendar_date_invalid": "DateTimeInput",
    "second_finer_than_microsecond": "DateTimeInput",
    "iana_name_required": "TimezoneInput",
    "iana_timezone_unknown": "TimezoneInput",
    "utc_offset_hours_required": "TimezoneInput",
    "timezone_field_not_applicable_to_mode": "TimezoneInput",
    "fold_requires_iana_mode": "TimezoneInput",
    "civil_time_basis_zone_mismatch": "TimezoneInput",
    "place_label_forbidden_codepoint": "LocationInput",
    "location_precision_not_accepted_for_source": "LocationInput",
    "source_record_id_not_allowed_for_manual": "LocationInput",
    "catalog_location_requires_label_and_record_id": "LocationInput",
    "ayanamsa_unsupported": "ComputationModeInput",
    **{code: "ComputationModeInput" for code in REQUEST_FRAME_REFUSAL_CODES},
    "body_selection_conflict": "OptionsInput",
    "aspect_orb_scale_requires_profile": "OptionsInput",
    "aspect_orb_sources_conflict": "OptionsInput",
    "aspect_angle_orb_requires_angles": "OptionsInput",
    "leap_second_not_applicable_to_pre_1972_scale": "ChartRequest",
    "leap_second_requires_exact_utc_2359": "ChartRequest",
    "leap_second_not_in_bundled_table": "ChartRequest",
    "moon_profile_center_conflict": "ChartRequest",
    "approximate_hour_requires_zero_subhour": "ChartRequest",
    "date_only_requires_zero_time": "ChartRequest",
    "fold_not_accepted_by_time_conversion": "TimeConversionRequest",
    "leap_second_not_accepted_by_time_conversion": "TimeConversionRequest",
}
# Pydantic's own error types are a closed Literal in pydantic-core.  With the
# rule codes above and the duplicate-key finding they are every `issues[].type`.
VALIDATION_ISSUE_TYPES: tuple[str, ...] = tuple(sorted(
    set(typing.get_args(core_schema.ErrorType))
    | set(REQUEST_VALIDATION_RULES)
    | {"duplicate_json_key", "duplicate_query_parameter"}
))


def _rule_error(
    code: str, *field_path: str, note: str | None = None
) -> PydanticCustomError:
    if code not in REQUEST_VALIDATION_RULES:
        raise RuntimeError(f"unregistered request validation rule: {code}")
    # The message is the code plus an optional server-side note; neither leaves
    # the server (`validation_issues` drops msg and ctx), and the client
    # branches on the code.
    return PydanticCustomError(
        code,
        f"{code} ({note})" if note else code,
        {"field_path": field_path} if field_path else None,
    )


# Dates whose final UTC minute contains a positive leap second in the bundled
# Swiss 2.10.03 table.  The API accepts 60 only at 23:59 on one of these UTC
# dates; future additions require an explicit source/table update rather than
# making every arbitrary `:60` look valid.
KNOWN_UTC_LEAP_SECOND_DATES = frozenset({
    (1972, 6, 30), (1972, 12, 31), (1973, 12, 31), (1974, 12, 31),
    (1975, 12, 31), (1976, 12, 31), (1977, 12, 31), (1978, 12, 31),
    (1979, 12, 31), (1981, 6, 30), (1982, 6, 30), (1983, 6, 30),
    (1985, 6, 30), (1987, 12, 31), (1989, 12, 31), (1990, 12, 31),
    (1992, 6, 30), (1993, 6, 30), (1994, 6, 30), (1995, 12, 31),
    (1997, 6, 30), (1998, 12, 31), (2005, 12, 31), (2008, 12, 31),
    (2012, 6, 30), (2015, 6, 30), (2016, 12, 31),
})

from .config import (
    AYANAMSA_OPTIONS,
    DEFAULT_ATMOSPHERE_TEMPERATURE_C,
    PRODUCT_YEAR_RANGE,
)


# The accepted IANA names are committed with the code: the production image's
# zoneinfo.available_timezones() without `localtime` (a link to the container's
# own clock setting) and `Factory` (a placeholder, not a place).  Reading the
# host's list instead made one request 200 on one machine and 422 on another.
# Gate D checks the committed list against the image (verify_container_runtime).
IANA_ZONE_NAMES_PATH = Path(__file__).with_name("iana_zone_names.json")
_PORTABLE_IANA_TIMEZONE_KEYS = frozenset(
    json.loads(IANA_ZONE_NAMES_PATH.read_text(encoding="utf-8"))["names"]
)


def _leap_second_label_in_utc(datetime_value, timezone_value) -> _dt.datetime | None:
    """The UTC minute (at :59) of a local `:60` label, through its own offset.

    A leap second is one global instant, so its local label moves with
    the offset — the 2016 leap second is 2017-01-01 07:59:60 in Taipei (RFC 3339
    describes the same shape).  The lookup must therefore happen after resolving
    the zone to UTC, not on the local date.
    """

    local = _dt.datetime(
        datetime_value.year,
        datetime_value.month,
        datetime_value.day,
        datetime_value.hour,
        datetime_value.minute,
        59,
    )
    if timezone_value.mode == "iana":
        if timezone_value.iana_name is None:
            return None
        try:
            zone = ZoneInfo(timezone_value.iana_name)
        except (ZoneInfoNotFoundError, ValueError):
            return None
        offset = local.replace(tzinfo=zone, fold=timezone_value.fold).utcoffset()
    else:
        if timezone_value.utc_offset_hours is None:
            return None
        offset = _dt.timedelta(hours=timezone_value.utc_offset_hours)
    if offset is None:
        return None
    return local - offset


# `place_label` is the only free-text field the request schema accepts, and it
# is copied verbatim into the Calculation Dossier and therefore into every
# export artifact.  A serializer must still do its own escaping, but these
# codepoints have no legitimate use in a place name and are rejected at the
# boundary so that every downstream consumer benefits, not only the CSV
# serializer:
#   - C0/C1 controls, including NUL, which is legal JSON but breaks many
#     consumers and truncates C string handling;
#   - CR/LF, which break the line structure of the TSV-shaped section copy
#     and of plain-text exports;
#   - bidi overrides and isolates, which allow a rendered label to disagree
#     with the stored label in the UI and in every export.
#
# The rule is expressed as Unicode general categories rather than as an
# enumerated codepoint list.  A blacklist of invisible codepoints does not
# converge: every Unicode release may add another format character, and the
# enumerated version of this rule already missed ZWSP (U+200B) and the line and
# paragraph separators (U+2028/U+2029), which some JSON and JavaScript
# consumers treat as line terminators.  Categories cover those, and cover
# additions this code has not seen.
#
#   Cc  C0/C1 controls, including NUL, CR and LF
#   Cf  format characters: bidi overrides and isolates, LRM/RLM, ZWSP,
#       BOM/ZWNBSP
#   Zl  U+2028 line separator
#   Zp  U+2029 paragraph separator
_FORBIDDEN_LABEL_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})

# ZWNJ (U+200C) and ZWJ (U+200D) are category Cf but are deliberately exempt.
# They are orthographically required in Persian, Arabic and Indic scripts,
# where they select joining and non-joining letter forms; banning them would
# reject legitimate place names rather than hostile ones.  Unlike the bidi
# controls they cannot reorder a rendered label, so the display-spoofing
# argument that justifies this boundary does not reach them.
_ALLOWED_FORMAT_CODEPOINTS = frozenset("\u200c\u200d")


def _first_forbidden_label_codepoint(label: str) -> str | None:
    """Return the first codepoint a place label may not contain, if any."""

    for character in label:
        if character in _ALLOWED_FORMAT_CODEPOINTS:
            continue
        if unicodedata.category(character) in _FORBIDDEN_LABEL_CATEGORIES:
            return character
    return None


class StrictInputModel(BaseModel):
    """Reject misspelled/unknown fields and non-finite numbers instead of silently ignoring them."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema_: core_schema.CoreSchema,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        # JSON Schema cannot state three things runtime
        # validation does — strict types, stripping before length checks, and
        # the model rules below — so the published schema states them instead of
        # leaving a client to discover them from refusals.
        json_schema = super().__get_pydantic_json_schema__(core_schema_, handler)
        json_schema = handler.resolve_ref_schema(json_schema)
        semantics: dict[str, Any] = {
            "strict_types": True,
            "strict_types_meaning": (
                "integers must be JSON integer literals (2000.0 is refused as "
                "int_type); numbers are never read from strings or booleans"
            ),
            "length_constraints_apply_after_whitespace_strip": True,
            "undeclared_fields": "refused_as_extra_forbidden",
        }
        rule_codes = sorted(
            code
            for code, owner in REQUEST_VALIDATION_RULES.items()
            if owner == cls.__name__
        )
        if rule_codes:
            semantics["rule_codes"] = rule_codes
        json_schema["x-validation-semantics"] = semantics
        return json_schema

    @model_validator(mode="after")
    def canonicalize_signed_zero(self):
        # JSON distinguishes the spelling -0.0 even though IEEE comparison
        # does not.  Keeping that sign leaked impossible civil times such as
        # ``12:00:-0.00`` and made semantically equal coordinates produce
        # different receipts.  Normalize only direct float fields at the
        # request boundary; bools and nonzero values remain untouched.
        for name in type(self).model_fields:
            value = getattr(self, name)
            if type(value) is float and value == 0.0:
                setattr(self, name, 0.0)
        return self


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


def exact_second_microseconds(second: float) -> int | None:
    """The request second as exact integer microseconds, or None if it is finer.

    The value is read from its shortest decimal spelling — the literal a JSON
    client wrote — so 0.3 is 300 000 µs, not the binary float's 299 999.99….
    Gap, fold and leap-second decisions are then made on this exact value and
    nothing is rounded before them; a finer literal is refused rather than
    rounded, because rounding 59.9999999 carries it into another minute, day
    or year (or across a clock gap or a leap second) before any of those
    decisions is made.
    """

    exact = Decimal(repr(float(second))).scaleb(6)
    if exact != exact.to_integral_value():
        return None
    return int(exact)


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

    # Derive inert-field rejection from the same declaration that owns each
    # mode's meaningful fields.
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
                # ZoneInfo raises ValueError, not ZoneInfoNotFoundError, for an
                # absolute or `..`-containing key.  Catching only the latter
                # relied on Pydantic converting the escaped ValueError, which
                # makes the rejection accidental rather than local.  The message
                # deliberately omits the submitted value: input echo must not
                # depend on the hosted profile's response sanitizer.
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
    "geonames_cities500": {
        "properties": {
            "place_label": {"type": "string", "minLength": 1},
            "source_record_id": {"type": "string", "minLength": 1},
            "location_precision": _precision_schema("geonames_cities500"),
        },
        "required": ["place_label", "source_record_id", "location_precision"],
    },
    "taiwan_moi_place_names": {
        "properties": {
            "place_label": {"type": "string", "minLength": 1},
            "source_record_id": {"type": "string", "minLength": 1},
            "location_precision": _precision_schema("taiwan_moi_place_names"),
        },
        "required": ["place_label", "source_record_id", "location_precision"],
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
            # The offending codepoint is reported as U+XXXX rather than echoed,
            # so the message stays diagnosable without putting an invisible or
            # direction-flipping character into an error string that other
            # surfaces will render.
            raise _rule_error(
                "place_label_forbidden_codepoint",
                "place_label",
                note=f"U+{ord(forbidden):04X}",
            )
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


# 使用者只給固定門檻時，產品預設容許度表讓位而不是衝突。預設值由 pydantic 依已驗證欄位
# 產生（而不是在 after-validator 事後清掉，那會繞過驗證，讓 requested_options 的回聲重送時
# 422）：欄位仍不在 model_fields_set（input_presence 仍為 defaulted），之後的檢查看到的
# 就是生效值。core.aspects.DEFAULT_ORB_PROFILE_KEY 必須等於此值（測試看守）。
OrbProfileKey = Literal["abu_mashar_lineage_v1", "lilly_1647_experience_v1"]
_PRODUCT_DEFAULT_ORB_PROFILE: OrbProfileKey = "lilly_1647_experience_v1"


def _default_aspect_orb_profile(validated: dict[str, Any]) -> OrbProfileKey | None:
    if validated.get("aspect_fixed_orb_degrees") is not None:
        return None
    return _PRODUCT_DEFAULT_ORB_PROFILE


class OptionsInput(StrictInputModel):
    # 一次只計算一種宮位制。選擇何種宮位制屬方法決策，不宣稱四種系統具有相同權威地位。
    # `False` 是真正的無宮位模式：不得先算完再從 response 隱藏。
    # house_system 在此時只保留為未執行的 request 欄位，不得出現在 effective receipt。
    include_houses: bool = True
    house_system: Literal["B", "R", "W", "P"] = "W"
    include_fixed_stars: bool = False
    # 產品核心是可驗證的天文數值；需要古典方法選擇的判斷一律 opt-in，
    # 不因 Swiss Ephemeris 能提供原料就假裝方法已獲採用。
    include_lots: bool = False
    include_antiscia: bool = False
    # 反照點的對象範圍為「七政（必要）＋交點（可選）」，
    # 恆星與軸點不計算。此開關即其中的「可選」。
    antiscia_include_nodes: bool = False
    include_void_of_course: bool = False
    include_declination_aspects: bool = False
    # 赤緯相位的研究性分類不變；1°只是既有產品預設。使用者可在 0–3°
    # 間明示覆寫，response 必須保存 default 與 effective 值。0 是合法值，定義為
    # 「赤緯完全相等才算」。
    declination_aspect_orb_degrees: float = Field(ge=0.0, le=3.0, default=1.0)
    include_outer_planets: bool = False
    include_chiron: bool = False
    # 平均遠地點、Swiss 的
    # interpolated/natural 遠地點，以及獨立計算的 natural 近地點。
    # 三者是現代／研究附加點，不因開啟而自動參與相位或古典方法。
    include_lilith_priapus: bool = False
    # 整體計算模式維持 geocentric，但月亮另以出生地站心位置取代
    # bodies 中的 effective Moon；response 同時保存地心 reference。此選項不等於
    # 「比較準」，而是明示的 mixed-origin coordinate policy。
    moon_position_profile: Literal[
        "global_computation_mode", "moon_only_topocentric_v1"
    ] = "global_computation_mode"
    # 南交點不是另一個 Swiss body：它是所選北交點方向的精確對蹠點。
    # 預設保留既有兩個北交點；明示要求時才把兩個導出南交點加入 nodes。
    include_south_nodes: bool = False
    include_lunar_phases: bool = False
    include_eclipses: bool = False
    include_rise_set_transits: bool = False

    # --- 黃道相位 ---
    #
    # **預設開啟，但可 opt-out。**
    #
    # 預設值是方法決定，不是實作細節：待審閱的方法項目不得默默成為預設的
    # 使用者可見計算；此項經明確決定為預設開啟。
    #
    # 這是本檔唯一預設開啟的判斷類選項。它與其餘項目的差別在於：預設輸出的
    # 整宮配置與角距離都是算術；逐度層的 `in_orb` 預設依 Lilly 1647 moiety 表判定
    # （收據標為產品預設、可切換）。方法收據仍為 provisional，Dossier 也仍會
    # 發出 `provisional_method_result` 通知——預設開啟不等於方法已獲採用。
    include_aspects: bool = True
    # 預設容許度表＝Lilly 1647 moiety 表（預設一組 orb profile，並提示可切換）。值必須等於
    # core.aspects.DEFAULT_ORB_PROFILE_KEY（測試看守）。明示傳 null 表示不套用任何表；
    # 只給 aspect_fixed_orb_degrees 時，預設表讓位給使用者的固定門檻（見下方 validator）。
    # 固定門檻宣告在容許度表之前：表的預設值依已驗證的固定門檻決定（下方 default_factory）。
    aspect_fixed_orb_degrees: Optional[float] = Field(
        gt=0.0, le=30.0, default=None
    )
    aspect_orb_profile: Optional[OrbProfileKey] = Field(
        default_factory=_default_aspect_orb_profile
    )
    # 逐度相位集合與整宮 doctrine 分開：不論選哪個逐度集合，整宮層仍只使用
    # 合相與四種傳統相位。現代小相位 profile 是使用者選項，不宣稱古典權威。
    aspect_set_profile: Literal[
        "ptolemaic_major_v1",
        "modern_common_minor_v1",
        "modern_quintile_family_v1",
        "modern_minor_combined_v1",
    ] = "ptolemaic_major_v1"
    # 兩種明示覆寫互斥：具名七政 orb 表可按百分比縮放；或直接指定所有逐度
    # 配對的固定門檻。後者是 user override，不繼承歷史來源宣稱。
    aspect_orb_scale_percent: Optional[float] = Field(
        gt=0.0, le=300.0, default=None
    )
    # Partile 慣例，做成 profile。三種慣例並存，
    # 其中兩種都載於 Lilly 名下的著作且互相矛盾（1677 那條出自未署名的格言節）。與 orb 表不同，這一項有預設值：
    # 「同一整數度」是最通行者。
    partile_profile: Literal[
        "same_degree_number_v1",
        "within_one_degree_v1",
        "lilly_1677_three_degrees_v1",
    ] = "same_degree_number_v1"
    # 成相時刻需要在時間軸上反覆查星曆，比其餘欄位昂貴一個量級，故預設關閉。
    include_aspect_perfection: bool = False
    # 三王星與阿拉伯點是否參與相位，直接跟隨其本身的計算開關，避免出現
    # 「要求三王星入相位但沒算三王星」這種自相矛盾的請求。交點永遠已算出，
    # 故單獨給一個開關。
    aspect_include_nodes: bool = False
    # ASC／MC 只加入逐度層；不加入整宮 doctrine、不互相配對，也不推測日周運動
    # 的 applying。若未給角點門檻，仍輸出幾何但 in_orb 為 null。
    aspect_include_angles: bool = False
    aspect_angle_orb_degrees: Optional[float] = Field(
        gt=0.0, le=30.0, default=None
    )

    # --- 非古典角點 ---
    # Vertex 等五個角點由 swe.houses_ex 附帶回傳。開啟後另闢
    # astronomical_data.extra_angles 輸出，`angles` 的鍵集合不變。
    include_extra_angles: bool = False
    # Anti-Vertex 是 Vertex 的黃道對蹠點，可單獨要求，不必同時輸出其餘四個
    # 現代技術角點。
    include_anti_vertex: bool = False

    # 純後端 body preset。它只約束「星體目錄」的現代附加物件；交點、Lots 與
    # 額外角點是 points/method outputs，刻意不被此 preset 靜默關閉。
    body_selection_preset: Literal["custom", "classical_seven_v1"] = "custom"

    # --- 具名古典尊貴元件；只回傳規則／表格結果，不打分、不解讀 ---
    # 傳統七政的 domicile/exaltation 星座層級是基礎 profile，預設計算但可明示
    # 關閉。精確擢升度數、陷、弱、互容與總分均不在此開關範圍。
    include_domicile_exaltation: bool = False
    bounds_profile: Optional[
        Literal[
            "egyptian_bounds_robbins_1940_v1",
            "chaldaean_bounds_ptolemy_i_21_v1",
            "ptolemy_bounds_robbins_1940_v1",
            "lilly_received_bounds_1647_v1",
        ]
    ] = None
    decan_profile: Optional[
        Literal[
            "chaldean_planetary_faces_firmicus_ii_4_v1",
            "manilius_sign_decans_astronomica_iv_v1",
        ]
    ] = None
    triplicity_profile: Optional[
        Literal[
            "dorothean_triplicity_three_rulers_v1",
            "ptolemy_triplicity_textual_corulership_v1",
            "lilly_triplicity_compact_1647_v1",
        ]
    ] = None
    triplicity_include_research_comparison: bool = False

    @model_validator(mode="after")
    def check_body_selection_preset(self):
        if self.body_selection_preset != "classical_seven_v1":
            return self
        incompatible = [
            name
            for name in (
                "include_outer_planets",
                "include_fixed_stars",
                "include_chiron",
                "include_lilith_priapus",
            )
            if getattr(self, name)
        ]
        if incompatible:
            raise _rule_error("body_selection_conflict")
        return self

    @model_validator(mode="after")
    def check_aspect_orb_configuration(self):
        if (
            self.aspect_orb_scale_percent is not None
            and self.aspect_orb_profile is None
        ):
            raise _rule_error("aspect_orb_scale_requires_profile")
        if (
            self.aspect_fixed_orb_degrees is not None
            and self.aspect_orb_profile is not None
        ):
            raise _rule_error("aspect_orb_sources_conflict")
        if (
            self.aspect_angle_orb_degrees is not None
            and not self.aspect_include_angles
        ):
            raise _rule_error("aspect_angle_orb_requires_angles")
        return self


class ChartRequest(StrictInputModel):
    birth_time_precision: Literal[
        "exact", "approximate_hour", "date_only"
    ] = "exact"
    datetime: DateTimeInput
    timezone: TimezoneInput
    location: LocationInput
    atmosphere: AtmosphereInput = Field(default_factory=AtmosphereInput)
    computation_mode: ComputationModeInput = Field(default_factory=ComputationModeInput)
    options: OptionsInput = Field(default_factory=OptionsInput)

    @model_validator(mode="after")
    def check_birth_time_precision(self):
        if self.datetime.second == 60:
            utc_label = _leap_second_label_in_utc(self.datetime, self.timezone)
            if self.datetime.year < 1972 or (
                utc_label is not None and utc_label.year < 1972
            ):
                raise _rule_error(
                    "leap_second_not_applicable_to_pre_1972_scale", "datetime", "second"
                )
            # The local `:59` must be exactly 23:59:59 UTC.  An offset that is
            # not whole minutes has no `:60` label for the leap second; checking
            # only the hour and minute let one through to Swiss as 23:58:60.
            if (
                self.birth_time_precision != "exact"
                or utc_label is None
                or (utc_label.hour, utc_label.minute, utc_label.second) != (23, 59, 59)
                or utc_label.microsecond != 0
            ):
                raise _rule_error(
                    "leap_second_requires_exact_utc_2359", "datetime", "second"
                )
            if (
                utc_label.year,
                utc_label.month,
                utc_label.day,
            ) not in KNOWN_UTC_LEAP_SECOND_DATES:
                raise _rule_error(
                    "leap_second_not_in_bundled_table", "datetime", "second"
                )
        if (
            self.options.moon_position_profile
            == "moon_only_topocentric_v1"
            and self.computation_mode.center != "geocentric"
        ):
            raise _rule_error("moon_profile_center_conflict")
        # approximate_hour is the stated civil hour read as the
        # half-open interval [H:00,H+1:00) in the named fold ("born in the 14
        # o'clock hour"), not "around 14:00" and not "rounded to the nearest
        # hour".  The sensitivity pass samples exactly that interval, which is
        # why minute and second must stay zero.
        if self.birth_time_precision == "approximate_hour" and (
            self.datetime.minute != 0 or self.datetime.second != 0
        ):
            raise _rule_error("approximate_hour_requires_zero_subhour")
        if self.birth_time_precision == "date_only":
            if (
                self.datetime.hour != 0
                or self.datetime.minute != 0
                or self.datetime.second != 0
            ):
                raise _rule_error("date_only_requires_zero_time")
            # The request is kept as sent.  Rewriting
            # include_houses here fabricated an explicit input in the receipt and
            # told the user they had not asked for houses.  Houses are not
            # computed without a birth time; the house module says so itself
            # (not_applicable, reason date_only_no_birth_time).
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


# ── Refusal bodies ────────────────────────────────────────────────────

_ISSUE_TYPE_ENUM = typing.cast("list[JsonValue]", list(VALIDATION_ISSUE_TYPES))
_REFUSAL_CODE_ENUM = typing.cast("list[JsonValue]", sorted(REFUSALS))


class RefusalIssue(BaseModel):
    """One validation finding: a closed code and a declared field path."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(json_schema_extra={"enum": _ISSUE_TYPE_ENUM})
    loc: list[str | int] = Field(
        description=(
            "Declared field names and array indices from the request root "
            "('body' or 'query'). A key the API does not declare is reported "
            "as 'input'; no request value is ever included."
        )
    )


# Built from the refusal table so the published codes and receipt fields are the
# runtime ones rather than a second list kept beside them.
_REFUSAL_DETAIL_FIELDS: dict[str, Any] = {
    "code": (str, Field(json_schema_extra={"enum": _REFUSAL_CODE_ENUM})),
    "message": (
        str,
        Field(description="Fixed text for the code; never contains request values."),
    ),
    "issues": (list[RefusalIssue] | None, None),
    "truncated": (
        bool | None,
        Field(
            default=None,
            description=(
                "Present and true only when more issues were found than "
                "`issues` lists (the list keeps the first ones)."
            ),
        ),
    ),
    **{name: (annotation, None) for name, annotation in REFUSAL_DETAIL_EXTRAS.items()},
}
RefusalDetail = create_model(
    "RefusalDetail",
    __config__=ConfigDict(extra="forbid"),
    **_REFUSAL_DETAIL_FIELDS,
)
RefusalResponse = create_model(
    "RefusalResponse",
    __config__=ConfigDict(extra="forbid"),
    detail=(RefusalDetail, ...),
)


def _declared_field_names(*models: type[BaseModel]) -> frozenset[str]:
    names: set[str] = set()
    pending = list(models)
    seen: set[type[BaseModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        for name, field in model.model_fields.items():
            names.add(name)
            for candidate in (field.annotation, *typing.get_args(field.annotation)):
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    pending.append(candidate)
    return frozenset(names)


# The only request-shaped text a refusal may carry: names the models declare.
# Derived from the models; the hand-kept list it replaces lived in main.py and
# had to be edited by every package that added a field.
REQUEST_FIELD_NAMES: frozenset[str] = _declared_field_names(
    ChartRequest, PlaceSearchRequest, TimeConversionRequest
)
_REQUEST_ROOTS = frozenset({"body", "query"})
UNDECLARED_KEY = "input"


def _declared_segment(item: object, declared: frozenset[str]) -> str | int:
    if isinstance(item, int) and not isinstance(item, bool):
        return item
    return item if isinstance(item, str) and item in declared else UNDECLARED_KEY


def validation_issues(
    errors: Iterable[Mapping[str, Any]],
    *,
    parameter_names: frozenset[str] = frozenset(),
) -> list[dict[str, object]]:
    """Reduce Pydantic errors to closed codes and declared field paths.

    Pydantic's `input`, `msg` and `ctx` never leave: they can carry the rejected
    birth values.  Only a rule's own `field_path` is read from the context, and
    only declared names survive in any location.
    """

    declared = REQUEST_FIELD_NAMES | _REQUEST_ROOTS | parameter_names
    issues: list[dict[str, object]] = []
    for error in errors:
        raw_type = error.get("type")
        issue_type = raw_type if raw_type in VALIDATION_ISSUE_TYPES else "value_error"
        location = [_declared_segment(item, declared) for item in error.get("loc", ())]
        context = error.get("ctx")
        field_path = context.get("field_path") if isinstance(context, dict) else None
        if isinstance(field_path, tuple):
            location.extend(_declared_segment(item, declared) for item in field_path)
        issues.append({"type": issue_type, "loc": location})
    return issues


class StrictJsonBodyError(Exception):
    """A body that is not one unambiguous UTF-8 JSON text."""

    def __init__(self, code: str, issues: list[dict[str, object]] | None = None):
        super().__init__(code)
        self.code = code
        self.issues = issues


class _JsonObjectPairs(list):
    """A JSON object as parsed: its (key, value) pairs in order, duplicates kept."""


# No request model nests deeper than a few levels (tests/backend/test_refusal_contract.py measures it), so a
# deeper body is refused as json_invalid before it is parsed or scanned.
MAX_JSON_NESTING_DEPTH = 32
_JSON_STRUCTURE_CHARACTER = re.compile(r'[\[\]{}"\\]')


def _json_nesting_exceeds(text: str, limit: int = MAX_JSON_NESTING_DEPTH) -> bool:
    """Whether the brackets outside strings open more than ``limit`` levels.

    One pass over the structural characters only, stopping at the first level
    past the limit, so a deep body costs ``limit`` steps and ``json.loads``
    never recurses into it.  Text that is not JSON is left to ``json.loads``.
    """

    depth = 0
    in_string = False
    escaped_position = -1
    for match in _JSON_STRUCTURE_CHARACTER.finditer(text):
        character, position = match.group(), match.start()
        if in_string:
            if position == escaped_position:
                continue
            if character == "\\":
                escaped_position = position + 1
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limit:
                return True
        elif character in "]}":
            depth -= 1
    return False


def _first_duplicate_key_path(document: object) -> tuple[str | int, ...] | None:
    # Each pending node carries a link (parent link, key or index) instead of a
    # copy of its whole path, so the scan is linear in the document; the path
    # is spelled out only for the duplicate it reports.
    pending: list[tuple[object, tuple | None]] = [(document, None)]
    while pending:
        node, link = pending.pop()
        if isinstance(node, _JsonObjectPairs):
            seen: set[str] = set()
            for key, _value in node:
                if key in seen:
                    return (*_link_path(link), key)
                seen.add(key)
            pending.extend((value, (link, key)) for key, value in reversed(node))
        elif isinstance(node, list):
            pending.extend(
                (value, (link, index))
                for index, value in reversed(list(enumerate(node)))
            )
    return None


def _link_path(link: tuple | None) -> tuple[str | int, ...]:
    segments: list[str | int] = []
    while link is not None:
        link, segment = link
        segments.append(segment)
    return tuple(reversed(segments))


class _NotJsonText(ValueError):
    """Raised inside `json.loads` for text RFC 8259 does not admit."""


def _refuse_json_constant(_name: str) -> None:
    raise _NotJsonText("not a JSON number")


def check_strict_query(
    items: Iterable[tuple[str, str]], declared: frozenset[str],
) -> None:
    """Refuse a query a route does not declare, or a declared name given twice.

    An unknown body field is refused (`extra_forbidden`) while an unknown query
    parameter was accepted, so `?lat=51.4779` on a chart request was a 200 and
    a request could carry data the receipt never names.  A repeated declared
    name was resolved silently (the last `projection` won).  Unknown names are
    reported as the undeclared placeholder, never echoed.
    """

    counts = Counter(name for name, _value in items)
    issues: list[dict[str, object]] = []
    if any(name not in declared for name in counts):
        issues.append({"type": "extra_forbidden", "loc": ["query", UNDECLARED_KEY]})
    for name in sorted(name for name, seen in counts.items() if name in declared and seen > 1):
        issues.append({"type": "duplicate_query_parameter", "loc": ["query", name]})
    if issues:
        raise StrictJsonBodyError("request_validation_failed", issues)


def check_strict_json_body(raw: bytes) -> None:
    """Refuse a body two JSON readers could read differently.

    `json.loads` on bytes detects UTF-16 and UTF-32 and skips a BOM, and a dict
    keeps the last of two equal keys.  Each is a choice the client did not make,
    and the receipt would then describe a request other than the one sent.
    RFC 8259 §8.1 requires UTF-8 without a BOM between systems.  A raw NUL byte
    cannot occur in UTF-8 JSON text; it is what UTF-16/32 look like without
    their BOM.  An empty body is left to the model, which names what is missing.
    """

    if not raw:
        return
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise StrictJsonBodyError("request_body_not_utf8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise StrictJsonBodyError("request_body_not_utf8") from None
    if _json_nesting_exceeds(text):
        raise StrictJsonBodyError("json_invalid")
    try:
        # NaN, Infinity and -Infinity are not JSON (RFC 8259 §6); Python reads
        # them anyway, so they are refused here as text that is not JSON rather
        # than later by the model as out-of-range numbers (422 finite_number).
        document = json.loads(
            text, object_pairs_hook=_JsonObjectPairs, parse_constant=_refuse_json_constant,
        )
    except (ValueError, RecursionError):
        raise StrictJsonBodyError("json_invalid") from None
    path = _first_duplicate_key_path(document)
    if path is not None:
        raise StrictJsonBodyError(
            "duplicate_json_key",
            [{
                "type": "duplicate_json_key",
                "loc": [
                    "body",
                    *(_declared_segment(item, REQUEST_FIELD_NAMES) for item in path),
                ],
            }],
        )


# `POST /api/chart?projection=`.  It selects a view of
# one response (`page` is the default) and is not a calculation
# input, so it is outside ChartRequest, option_states and every request digest.  app.response_projection owns the views.
ChartProjection = Literal["page", "detailed"]
