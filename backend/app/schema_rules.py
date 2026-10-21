"""Request validation rule codes, the strict base model and the text and
leap-second checks every request model shares."""

import datetime as _dt
import json
import typing
import unicodedata
from typing import Any
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, GetJsonSchemaHandler, model_validator
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import PydanticCustomError, core_schema

from .core.frame_compatibility import REQUEST_FRAME_REFUSAL_CODES, SOLAR_RETURN_FRAME_REFUSAL_CODES


# Every validation rule has one closed code (raised through `_rule_error`),
# mapped to the model that owns it.  A rule about one field names that field,
# so the refusal's `loc` ends at it; a rule about a combination keeps `loc` at
# the model and its code names the combination.
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
    "place_label_has_no_base_character": "LocationInput",
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
    "annual_request_selects_no_technique": "AnnualInput",
    "year_of_life_must_be_positive": "AnnualInput",
    "firdaria_option_not_applicable": "AnnualInput",
    "zodiacal_releasing_option_not_applicable": "AnnualInput",
    "decennials_option_not_applicable": "AnnualInput",
    "decennials_start_planet_required": "AnnualInput",
    "decennials_start_planet_not_applicable": "AnnualInput",
    "monthly_profection_option_not_applicable": "AnnualInput",
    "solar_return_chart_option_not_applicable": "AnnualInput",
    "solar_return_location_not_yet_offered": "AnnualInput",
    # Raised by the annual route once the N-th solar return is known to fall
    # after 2399; a rule about the requested year, like the other annual rules.
    "solar_return_outside_supported_year_range": "AnnualInput",
    **{code: "AnnualRequest" for code in SOLAR_RETURN_FRAME_REFUSAL_CODES},
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
    # The note never leaves the server (`validation_issues` drops msg and ctx);
    # the client branches on the code.
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
    # TimezoneInput has already refused a missing or unknown zone and offset.
    if timezone_value.mode == "iana":
        zone = ZoneInfo(timezone_value.iana_name)
        offset = local.replace(tzinfo=zone, fold=timezone_value.fold).utcoffset()
    else:
        offset = _dt.timedelta(hours=timezone_value.utc_offset_hours)
    return None if offset is None else local - offset


# `place_label` is the only free-text request field and is copied verbatim
# into the Calculation Dossier and every export.  Serializers still escape, but
# these codepoints have no use in a place name, so the boundary rejects them
# for every consumer: C0/C1 controls (NUL truncates C strings), CR/LF (break
# TSV and plain-text exports), and bidi overrides/isolates (let the rendered
# label disagree with the stored one).
#
# Unicode general categories, not a codepoint list: a blacklist does not
# converge (each release may add format characters), and the enumerated rule
# already missed ZWSP and U+2028/U+2029, which some JSON/JS consumers treat as
# line terminators.
#
#   Cc  C0/C1 controls, including NUL, CR and LF
#   Cf  format characters: bidi overrides and isolates, LRM/RLM, ZWSP,
#       BOM/ZWNBSP
#   Zl  U+2028 line separator
#   Zp  U+2029 paragraph separator
_FORBIDDEN_LABEL_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
# Blank fillers that Unicode files under letters or symbols, so the categories
# above do not reach them, yet render as nothing: the Hangul fillers (all
# Default_Ignorable_Code_Point) and the blank braille pattern.
_INVISIBLE_FILLER_CODEPOINTS = frozenset({"\u115f", "\u1160", "\u3164", "\uffa0", "\u2800"})

# ZWNJ (U+200C) and ZWJ (U+200D) are Cf but deliberately exempt: Persian,
# Arabic and Indic place names need them for joining forms, and unlike bidi
# controls they cannot reorder a rendered label.
_ALLOWED_FORMAT_CODEPOINTS = frozenset("\u200c\u200d")


# A base character is one a reader sees on its own: a letter, number,
# punctuation or symbol (not a combining mark, separator or format character).
_BASE_CHARACTER_CATEGORY_CLASSES = frozenset("LNPS")


def _label_has_base_character(label: str) -> bool:
    return any(unicodedata.category(character)[0] in _BASE_CHARACTER_CATEGORY_CLASSES
               and character not in _INVISIBLE_FILLER_CODEPOINTS
               for character in label)


def _first_forbidden_label_codepoint(label: str) -> str | None:
    for character in label:
        if character in _ALLOWED_FORMAT_CODEPOINTS:
            continue
        if (unicodedata.category(character) in _FORBIDDEN_LABEL_CATEGORIES
                or character in _INVISIBLE_FILLER_CODEPOINTS):
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
        # JSON Schema cannot express strict types, stripping before length
        # checks, or the model rules, so the schema states them in an extension
        # instead of leaving a client to discover them from refusals.
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
        # Keeping JSON's -0.0 leaked impossible civil times (``12:00:-0.00``)
        # and gave equal coordinates different receipts.  Direct float fields
        # only.
        for name in type(self).model_fields:
            value = getattr(self, name)
            if type(value) is float and value == 0.0:
                setattr(self, name, 0.0)
        return self
