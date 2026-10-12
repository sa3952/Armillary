"""Where each historical clock rule of the time-conversion helper comes from.

The helper covers four regions: Taiwan, Hong Kong, Macau and mainland China
(Beijing time, and Xinjiang time for a record kept on it).  For each of their
IANA zones the data file ``backend/app/civil_time_sources.json`` lists every
*period* of the tz database from the one in effect on 1900-01-01: the UTC
instant it starts (null for the zone's first, local-mean-time period), the
offset, abbreviation and summer-time flag the database gives it, a closed
``regime``, and the id of the source row the rule rests on, or ``not_cited``
when no document is known.  A source row says how far we checked it
(``verification_level``), what we read, and where the original is held.

The periods are a pinned copy of the tz database, so the copy is checked both
ways: tests/backend/test_civil_time_sources.py fails when the installed
database has a transition in scope that the file lacks (or the reverse), and
at run time a reading whose offset, abbreviation or summer-time flag differs
from its period is reported as ``source_table_mismatch`` with no source,
rather than with the source of a rule the database no longer applies.
"""

from __future__ import annotations

import bisect
import datetime as dtmod
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from .civil_time_basis import DUAL_CIVIL_TIME_CATALOGUE_ZONES
from .time_utils import PRC_RULE_ZONES

SOURCES_PATH: Final = Path(__file__).resolve().parents[1] / "civil_time_sources.json"
SCHEMA: Final = "civil-time-sources-v1"

VERIFICATION_LEVELS: Final = ("read_original", "read_transcription", "relayed")
REGIMES: Final = (
    "local_mean_time",
    "standard_time",
    "summer_time",
    "japan_standard_time",
    "wartime_time",
)
NOT_CITED: Final = "not_cited"
RULE_STATUSES: Final = ("cited", NOT_CITED, "source_table_mismatch")

REGIONS: Final[dict[str, str]] = {
    "taiwan": "臺灣",
    "hong_kong": "香港",
    "macau": "澳門",
    "mainland_china": "中國",
}
# The zone each rule is kept under, with its region.
RULE_ZONES: Final[dict[str, str]] = {
    "Asia/Taipei": "taiwan",
    "Asia/Hong_Kong": "hong_kong",
    "Asia/Macau": "macau",
    "Asia/Shanghai": "mainland_china",
    "Asia/Urumqi": "mainland_china",
}
# The accepted names that are tz database backward links to a rule zone: the
# PRC links and Xinjiang's Asia/Kashgar, the same sets the 1988 warning and the
# Beijing/Xinjiang choice use.
ZONE_LINKS: Final[dict[str, str]] = {
    **{zone: "Asia/Shanghai" for zone in PRC_RULE_ZONES if zone != "Asia/Shanghai"},
    **{zone: "Asia/Urumqi" for zone in DUAL_CIVIL_TIME_CATALOGUE_ZONES if zone != "Asia/Urumqi"},
}
COVERED_ZONES: Final = frozenset(RULE_ZONES) | frozenset(ZONE_LINKS)


def rule_zone(zone_name: str) -> str | None:
    """The rule zone an accepted name is kept under, or None outside the four regions."""

    if zone_name in RULE_ZONES:
        return zone_name
    return ZONE_LINKS.get(zone_name)


def offset_seconds(text: str) -> int:
    """'+08:00' or '+08:05:43' as seconds east of UTC."""

    sign = -1 if text[0] == "-" else 1
    parts = [int(part) for part in text[1:].split(":")]
    hours, minutes, seconds = (parts + [0, 0])[:3]
    return sign * (hours * 3600 + minutes * 60 + seconds)


@dataclass(frozen=True)
class Period:
    zone: str
    from_utc: dtmod.datetime | None
    utc_offset: str
    abbreviation: str
    summer_time: bool
    regime: str
    source: str

    def matches(self, offset: dtmod.timedelta, abbreviation: str, summer_time: bool) -> bool:
        return (
            round(offset.total_seconds()) == offset_seconds(self.utc_offset)
            and abbreviation == self.abbreviation
            and summer_time == self.summer_time
        )


class CivilTimeSourcesError(ValueError):
    """The data file breaks its own schema; nothing is served from it."""


def _parse_instant(text: str | None) -> dtmod.datetime | None:
    if text is None:
        return None
    if not text.endswith("Z"):
        raise CivilTimeSourcesError(f"from_utc must end in Z: {text}")
    return dtmod.datetime.fromisoformat(text[:-1]).replace(tzinfo=dtmod.timezone.utc)


def _web_address(url: object) -> bool:
    # Some holders (a provincial gazette scan) answer only over plain HTTP.
    return isinstance(url, str) and url.startswith(("https://", "http://"))


def _check_source(key: str, row: dict) -> None:
    required = {"region", "title", "document", "verification_level", "read", "holder"}
    if set(row) != required:
        raise CivilTimeSourcesError(f"source {key}: fields {sorted(row)}")
    if row["region"] is not None and row["region"] not in REGIONS:
        raise CivilTimeSourcesError(f"source {key}: region {row['region']}")
    if row["verification_level"] not in VERIFICATION_LEVELS:
        raise CivilTimeSourcesError(f"source {key}: level {row['verification_level']}")
    if not row["title"] or not row["document"] or not row["read"]:
        raise CivilTimeSourcesError(f"source {key}: empty title, document or read list")
    for item in row["read"]:
        if set(item) != {"label", "url"} or not item["label"] or not _web_address(item["url"]):
            raise CivilTimeSourcesError(f"source {key}: read entry {item}")
    holder = row["holder"]
    if set(holder) != {"name", "url", "note"} or not holder["note"]:
        raise CivilTimeSourcesError(f"source {key}: holder needs name, url and a note")
    if holder["url"] is not None and not _web_address(holder["url"]):
        raise CivilTimeSourcesError(f"source {key}: holder url {holder['url']}")


class CivilTimeSources:
    """The loaded, validated data file."""

    def __init__(self, document: dict) -> None:
        if document.get("schema") != SCHEMA:
            raise CivilTimeSourcesError("unknown schema")
        if document.get("verification_levels", {}).keys() != set(VERIFICATION_LEVELS):
            raise CivilTimeSourcesError("verification level labels do not match the closed set")
        self.tzdb_version_checked: str = document["tzdb_version_checked"]
        self.level_labels: dict[str, str] = dict(document["verification_levels"])
        self.sources: dict[str, dict] = dict(document["sources"])
        if NOT_CITED in self.sources:
            raise CivilTimeSourcesError("not_cited is a status, not a source id")
        for key, row in self.sources.items():
            _check_source(key, row)
        self.periods: dict[str, list[Period]] = {zone: [] for zone in RULE_ZONES}
        for row in document["periods"]:
            period = Period(
                zone=row["zone"],
                from_utc=_parse_instant(row["from_utc"]),
                utc_offset=row["utc_offset"],
                abbreviation=row["abbreviation"],
                summer_time=row["summer_time"],
                regime=row["regime"],
                source=row["source"],
            )
            if period.zone not in self.periods:
                raise CivilTimeSourcesError(f"zone outside the four regions: {period.zone}")
            if period.regime not in REGIMES:
                raise CivilTimeSourcesError(f"regime {period.regime}")
            if period.source != NOT_CITED and period.source not in self.sources:
                raise CivilTimeSourcesError(f"unknown source {period.source}")
            self.periods[period.zone].append(period)
        used = {p.source for rows in self.periods.values() for p in rows} - {NOT_CITED}
        if used != set(self.sources):
            raise CivilTimeSourcesError(f"sources never used: {sorted(set(self.sources) - used)}")
        for zone, rows in self.periods.items():
            if not rows:
                raise CivilTimeSourcesError(f"{zone}: no periods")
            starts = [p.from_utc for p in rows if p.from_utc is not None]
            if (
                any(p.from_utc is None for p in rows[1:])
                or any(later <= earlier for earlier, later in zip(starts, starts[1:]))
            ):
                raise CivilTimeSourcesError(
                    f"{zone}: only the first period may lack a start; starts strictly increase"
                )
        self._starts: dict[str, list[dtmod.datetime]] = {
            zone: [p.from_utc for p in rows[1:] if p.from_utc is not None]
            for zone, rows in self.periods.items()
        }

    def period_at(self, zone: str, instant: dtmod.datetime) -> Period:
        """The period of a rule zone that contains the UTC instant."""

        rows = self.periods[zone]
        return rows[bisect.bisect_right(self._starts[zone], instant)]

    def source_row(self, key: str) -> dict:
        row = self.sources[key]
        return {
            "id": key,
            **row,
            "verification_label": self.level_labels[row["verification_level"]],
        }

    def rule_receipt(
        self,
        zone: str,
        instant: dtmod.datetime,
        *,
        offset: dtmod.timedelta,
        abbreviation: str,
        summer_time: bool,
    ) -> dict:
        """The rule a reading falls under, checked against what the database applied."""

        period = self.period_at(zone, instant)
        receipt = {
            "rule_zone": zone,
            "period_start_utc": (
                period.from_utc.strftime("%Y-%m-%dT%H:%M:%SZ") if period.from_utc else None
            ),
            "regime": period.regime,
        }
        if not period.matches(offset, abbreviation, summer_time):
            return {
                **receipt,
                "regime": None,
                "status": "source_table_mismatch",
                "source": None,
            }
        if period.source == NOT_CITED:
            return {**receipt, "status": NOT_CITED, "source": None}
        return {**receipt, "status": "cited", "source": self.source_row(period.source)}


def load_civil_time_sources(path: Path = SOURCES_PATH) -> CivilTimeSources:
    return CivilTimeSources(json.loads(path.read_text(encoding="utf-8")))


CIVIL_TIME_SOURCES: Final = load_civil_time_sources()
