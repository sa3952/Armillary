"""The calculate page's time-conversion helper: one wall-clock time, read as the chart reads it.

Before computing, the helper asks what the birth record's clock time was in
UTC.  Every reading comes from ``time_utils.wall_clock_readings``, which runs
the chart's own conversion once per fold, so the helper and ``/api/chart``
cannot disagree; what this module adds is the description: whether the time
repeats or never existed, the abbreviation and summer-time flag the tz database
gives it, the rule's regime and source row (``civil_time_sources``), the
warnings the chart would carry (China 1988, Hong Kong 1945–1946), and the tz
database the process converts with.

Scope is the four regions the source table covers (Taiwan, Hong Kong, Macau,
mainland China); any other zone, and a fixed offset, is refused rather than
answered without a source.  A Xinjiang-time zone needs the record's clock named,
by the same rule as manual coordinates on a chart.
"""

from __future__ import annotations

import datetime as dtmod
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from .invariants import InternalInvariantError
from .civil_time_basis import check_zone_civil_time_basis
from .civil_time_sources import CIVIL_TIME_SOURCES, REGIONS, RULE_ZONES, rule_zone
from .dossier_warnings import (
    hk_observatory_summer_time_warnings,
    prc_1988_dst_dispute_warnings,
)
from .time_utils import (
    MICROSECONDS_PER_SECOND,
    civil_time_label,
    exact_second_microseconds_or_raise,
    offset_status,
    utc_offset_text,
    wall_clock_readings,
)
from .tz_database import TZ_DATABASE

STATUSES = ("single", "repeated", "nonexistent")
# The warning keys the helper repeats; affected_paths name chart paths it has not.
_WARNING_KEYS = ("code", "severity", "message", "source")


class TimeConversionZoneNotCoveredError(ValueError):
    code = "time_conversion_zone_not_covered"


def _utc_iso(instant: dtmod.datetime) -> str:
    return civil_time_label(
        instant.year, instant.month, instant.day, instant.hour, instant.minute,
        instant.second * MICROSECONDS_PER_SECOND + instant.microsecond,
        separator="T",
    ) + "Z"


def _wall_clock_text(value: dtmod.datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _reading(fold: int, utc: dtmod.datetime, offset_hours: float, zone: ZoneInfo,
             kept_under: str, repeated: bool) -> dict:
    local = utc.astimezone(zone)
    offset = local.utcoffset()
    abbreviation = local.tzname()
    if offset is None or abbreviation is None:
        raise InternalInvariantError("offset is not None and abbreviation is not None")
    return {
        "fold": fold,
        "utc_iso_8601": _utc_iso(utc),
        "utc_offset_hours": offset_hours,
        "utc_offset_label": utc_offset_text(offset_hours),
        "abbreviation": abbreviation,
        "summer_time": bool(local.dst()),
        "offset_status": offset_status("iana", utc, repeated),
        "rule": CIVIL_TIME_SOURCES.rule_receipt(
            kept_under, utc, offset=offset, abbreviation=abbreviation,
            summer_time=bool(local.dst()),
        ),
    }


def _gap(naive: dtmod.datetime, zone: ZoneInfo, kept_under: str) -> dict:
    # PEP 495: inside a gap fold=0 applies the offset before the transition and
    # fold=1 the one after; the instant the first gives lies after the change.
    before = naive.replace(tzinfo=zone, fold=0).utcoffset()
    after = naive.replace(tzinfo=zone, fold=1).utcoffset()
    if before is None or after is None:
        raise InternalInvariantError("before is not None and after is not None")
    period = CIVIL_TIME_SOURCES.period_at(
        kept_under, (naive - before).replace(tzinfo=dtmod.timezone.utc)
    )
    transition = period.from_utc
    if transition is None:
        raise InternalInvariantError("transition is not None")
    local_after = transition.astimezone(zone)
    abbreviation = local_after.tzname()
    if abbreviation is None:
        raise InternalInvariantError("abbreviation is not None")
    return {
        "skipped_local_start": _wall_clock_text((transition + before).replace(tzinfo=None)),
        "skipped_local_end": _wall_clock_text((transition + after).replace(tzinfo=None)),
        "offset_before_label": utc_offset_text(before.total_seconds() / 3600),
        "offset_after_label": utc_offset_text(after.total_seconds() / 3600),
        "transition_utc": transition.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rule": CIVIL_TIME_SOURCES.rule_receipt(
            kept_under, transition, offset=after, abbreviation=abbreviation,
            summer_time=bool(local_after.dst()),
        ),
    }


def convert_civil_time(request) -> dict:
    """Readings, rule and sources for ``request.datetime`` on ``request.timezone``."""

    timezone = request.timezone
    zone_name = timezone.iana_name if timezone.mode == "iana" else None
    kept_under = rule_zone(zone_name) if zone_name else None
    if zone_name is None or kept_under is None:
        raise TimeConversionZoneNotCoveredError(
            "the helper covers the zones of Taiwan, Hong Kong, Macau and mainland China"
        )
    check_zone_civil_time_basis(zone_name, timezone.civil_time_basis)

    stated = request.datetime
    microseconds = exact_second_microseconds_or_raise(stated.second)
    naive = dtmod.datetime(
        stated.year, stated.month, stated.day, stated.hour, stated.minute,
    ) + dtmod.timedelta(microseconds=microseconds)
    zone = ZoneInfo(zone_name)
    found = wall_clock_readings(stated, timezone)
    status = STATUSES[2] if not found else STATUSES[1] if len(found) == 2 else STATUSES[0]
    exact = SimpleNamespace(timezone=timezone, datetime=stated, birth_time_precision="exact")
    warnings = [
        {key: warning[key] for key in _WARNING_KEYS}
        for rule in (prc_1988_dst_dispute_warnings, hk_observatory_summer_time_warnings)
        for warning in rule(exact)
    ]
    region = RULE_ZONES[kept_under]
    return {
        "input_local_time": civil_time_label(
            stated.year, stated.month, stated.day, stated.hour, stated.minute, microseconds,
        ),
        "timezone": {
            "iana_name": zone_name,
            "civil_time_basis": timezone.civil_time_basis,
            "rule_zone": kept_under,
            "region": region,
            "region_label": REGIONS[region],
        },
        "status": status,
        "readings": [
            _reading(fold, utc, offset_hours, zone, kept_under, status == "repeated")
            for fold, utc, offset_hours in found
        ],
        "gap": _gap(naive, zone, kept_under) if status == "nonexistent" else None,
        "warnings": warnings,
        "tz_database": dict(TZ_DATABASE),
        "source_table": {
            "tzdb_version_checked": CIVIL_TIME_SOURCES.tzdb_version_checked,
            "verification_levels": dict(CIVIL_TIME_SOURCES.level_labels),
        },
    }
