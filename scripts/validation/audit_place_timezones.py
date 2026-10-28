#!/usr/bin/env python3
"""Find GeoNames rows whose timezone disagrees with the zone at their coordinate.

Maintainer tool, not part of the build: it needs ``timezonefinder`` (the
timezone-boundary-builder polygons), which the runtime and the producer do not
install.  It writes ``place_timezone_corrections.json``, which the producer
reads as a table of named corrections like the hand-written ones.

A row is corrected only when all of these hold:

* the zone at its coordinate is another zone of the row's own country
  (``zone.tab``), so a coordinate that strays over a border or out to sea is
  not given a foreign zone;
* the two zones' UTC offsets differ at some instant 1900-2030, the years a
  chart can be cast for and the tz database records, sampled four times a year;
* the row's country is not one the producer settles by its own rule or leaves
  as GeoNames has it because the boundary itself is disputed;
* after the corrections, the corrected zone is the one most of the row's eight
  nearest same-country rows within 50 km carry (150 km where fewer than two
  are that near), the oracle tests/backend/test_place_catalog.py holds every
  named correction to.  A row the two oracles disagree on is a boundary row,
  unless AUTHORITATIVE_ZONE_EXCEPTIONS names it: a jurisdiction a governing
  rule puts on another zone than its neighbours is kept by that rule, and the
  audit refuses to run if the rule's zone is not the zone at the coordinate.

Rows that meet the first two conditions but sit in such a country are written
to ``left_as_source`` with the reason, so the coordinate check can tell a known
row from a new one.

The output depends on the polygons and on the tz database's zone histories:
the committed table reproduces with timezonefinder 9.2.0 (timezonefinder-data
4.2026.5) and the ``tzdata`` package's build (PYTHONTZPATH empty, --zone-tab
from that package), in which linked zones such as Africa/Mogadishu share their
target's history.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from collections import Counter
import io
import json
import math
from pathlib import Path
import sys
import zipfile
from zoneinfo import ZoneInfo

# Settled elsewhere, or a boundary the product does not draw.
LEFT_AS_SOURCE_COUNTRIES = {
    "VN": "Vietnam's 1954-1976 line is applied by the producer's own north/south table",
    "PS": "West Bank and Gaza: Asia/Hebron and Asia/Jerusalem follow who administers a place, which the product does not decide",
    "IL": "Asia/Hebron and Asia/Jerusalem follow who administers a place, which the product does not decide",
    "SY": "Golan Heights: the administering zone is disputed",
    "CY": "Northern Cyprus: Asia/Famagusta and Asia/Nicosia follow a disputed line",
    "GB": "Akrotiri and Dhekelia on Cyprus: a disputed line",
    "EH": "Western Sahara: a disputed territory",
    "MA": "Western Sahara: a disputed territory",
    "UA": "Crimea: a disputed territory",
    "GE": "Abkhazia and South Ossetia: disputed territories",
    "CN": "Xinjiang keeps both Asia/Urumqi and Beijing time; the producer's hand table settles rows by their neighbours",
}
# Jurisdictions whose zone differs from their neighbours' by a governing rule,
# each with the rule that sets it.  Neighbour voting alone cannot tell such a
# place from a coordinate that strays over a line, so these are not put to it.
AUTHORITATIVE_ZONE_EXCEPTIONS = {
    "5710035": {
        "zone": "America/Denver",
        "jurisdiction": "City of West Wendover, Elko County, Nevada",
        "effective": "1999-10-31",
        "authority": "US DOT final rule, Relocation of Standard Time Zone Boundary in the State of "
                     "Nevada, Federal Register 1999-10-21 (FR Doc. 99-27240); 49 CFR 71.9(b)",
    },
    "4266307": {
        "zone": "America/Indiana/Vincennes",
        "jurisdiction": "Knox County, Indiana",
        "effective": "2007-11-04",
        "authority": "US DOT final rule, Standard Time Zone Boundary in the State of Indiana, "
                     "72 FR 54367 (2007-09-25)",
    },
    "7261646": {
        "zone": "America/Denver",
        "jurisdiction": "Navajo Nation (Western Agency), LeChee Chapter",
        "effective": "1968-03",
        "authority": "Navajo Tribal Council resolution of March 1968 (number not found), reported by "
                     "AP 2024-03 (T. Tang); LeChee Chapter minutes 2026-09-14 ('All times are Day "
                     "Light Time'); tzdb northamerica: America/Denver for the Navajo Nation",
        "note": "Births before 1967 are presumed: tzdb's America/Denver applies Denver city rules in "
                "1920-21 and 1965-66, which differ from Arizona's America/Phoenix",
    },
}
SAMPLE_INSTANTS = tuple(
    datetime(year, month, 15, 12, tzinfo=timezone.utc) for year in range(1900, 2031) for month in (1, 4, 7, 10)
)


def _offsets(zone: str, cache: dict) -> tuple:
    if zone not in cache:
        info = ZoneInfo(zone)
        cache[zone] = tuple(instant.astimezone(info).utcoffset() for instant in SAMPLE_INSTANTS)
    return cache[zone]


def _country_zones(zone_tab: Path) -> dict[str, set[str]]:
    zones: dict[str, set[str]] = {}
    for line in zone_tab.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        country, _coordinates, zone, *_ = line.split("\t")
        for code in country.split(","):
            zones.setdefault(code, set()).add(zone)
    return zones


def _neighbour_majority(row, by_cell, zones, k=8, radius_km=50.0, minimum=2, sparse_radius_km=150.0):
    """The same oracle as the place catalogue test, over the corrected rows."""

    record_id, country, latitude, longitude = row
    scale = math.cos(math.radians(latitude))
    for radius in (radius_km, sparse_radius_km):
        degrees = radius / 111.0
        widen = degrees / max(scale, 0.01)
        near = []
        for cell_lat in range(math.floor(latitude - degrees), math.floor(latitude + degrees) + 1):
            for cell_lon in range(math.floor(longitude - widen), math.floor(longitude + widen) + 1):
                for other_id, other_country, lat, lon in by_cell.get((cell_lat, cell_lon), ()):
                    if other_id == record_id or other_country != country:
                        continue
                    if abs(lat - latitude) > degrees or abs(lon - longitude) > widen:
                        continue
                    distance = 111.2 * math.hypot(lat - latitude, (lon - longitude) * scale)
                    if distance <= radius:
                        near.append((distance, zones[other_id]))
        near = sorted(near)[:k]
        if len(near) >= minimum:
            break
    if len(near) < minimum:
        return None, False
    zone, votes = Counter(zone for _distance, zone in near).most_common(1)[0]
    return zone, votes * 2 > len(near)


def audit(cities500: Path, zone_tab: Path) -> dict:
    import timezonefinder  # type: ignore[import-not-found]

    finder = timezonefinder.TimezoneFinder(in_memory=True)
    country_zones = _country_zones(zone_tab)
    cache: dict = {}
    corrections: list[dict] = []
    left: list[dict] = []
    Row = tuple[str, str, float, float]
    rows: dict[str, Row] = {}
    zones: dict[str, str] = {}
    by_cell: dict[tuple[int, int], list[Row]] = {}
    with zipfile.ZipFile(cities500) as archive:
        for line in io.TextIOWrapper(archive.open("cities500.txt"), encoding="utf-8"):
            fields = line.rstrip("\n").split("\t")
            record_id, name, country, zone = fields[0], fields[1], fields[8], fields[17]
            latitude, longitude = float(fields[4]), float(fields[5])
            rows[record_id] = (record_id, country, latitude, longitude)
            zones[record_id] = zone
            by_cell.setdefault((math.floor(latitude), math.floor(longitude)), []).append(rows[record_id])
            if not zone:
                continue
            found = finder.timezone_at(lat=latitude, lng=longitude)
            if found is None or found == zone or found not in country_zones.get(country, ()):
                continue
            if _offsets(zone, cache) == _offsets(found, cache):
                continue
            entry = {"source_record_id": record_id, "expected": zone, "corrected": found,
                     "place": f"{name} ({latitude}, {longitude}), {country}"}
            if country in LEFT_AS_SOURCE_COUNTRIES:
                left.append({**entry, "reason": LEFT_AS_SOURCE_COUNTRIES[country]})
            else:
                corrections.append(entry)
    found_ids = {entry["source_record_id"]: entry["corrected"] for entry in corrections}
    for record_id, rule in AUTHORITATIVE_ZONE_EXCEPTIONS.items():
        if found_ids.get(record_id) != rule["zone"]:
            raise SystemExit(f"authoritative zone exception {record_id}: the zone at the coordinate is "
                             f"{found_ids.get(record_id)!r}, not the rule's {rule['zone']}")
    # Keep only corrections the neighbours agree with once applied; dropping one
    # can change its neighbours' votes, so repeat until nothing changes.
    while True:
        applied = {**zones, **{entry["source_record_id"]: entry["corrected"] for entry in corrections}}
        disagreeing = [
            entry for entry in corrections
            if entry["source_record_id"] not in AUTHORITATIVE_ZONE_EXCEPTIONS
            and _neighbour_majority(rows[entry["source_record_id"]], by_cell, applied)
            != (entry["corrected"], True)
        ]
        if not disagreeing:
            break
        for entry in disagreeing:
            corrections.remove(entry)
            left.append({**entry, "reason": "a boundary row: the coordinate's zone is not the zone "
                                             "most of its nearest same-country neighbours carry"})
    for entry in corrections:
        if entry["source_record_id"] in AUTHORITATIVE_ZONE_EXCEPTIONS:
            rule = AUTHORITATIVE_ZONE_EXCEPTIONS[entry["source_record_id"]]
            entry["authority"] = f"{rule['jurisdiction']}: {rule['authority']}, effective {rule['effective']}"
            if "note" in rule:
                entry["authority"] += f". {rule['note']}"
    return {
        "engine": f"timezonefinder {timezonefinder.__version__ if hasattr(timezonefinder, '__version__') else '?'}",
        "zone_tab": zone_tab.name,
        "offset_sampling": "UTC 12:00 on the 15th of January, April, July and October, 1900-2030",
        "corrections": sorted(corrections, key=lambda item: int(item["source_record_id"])),
        "left_as_source": sorted(left, key=lambda item: int(item["source_record_id"])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--geonames-zip", type=Path, required=True)
    parser.add_argument("--zone-tab", type=Path, default=Path("/usr/share/zoneinfo/zone.tab"))
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = audit(arguments.geonames_zip, arguments.zone_tab)
    arguments.output.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"TIMEZONE AUDIT: {len(result['corrections'])} corrections, "
          f"{len(result['left_as_source'])} left as source", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
