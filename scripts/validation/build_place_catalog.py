#!/usr/bin/env python3
"""Build the immutable GeoNames + Taiwan MOI place-search SQLite catalog.

Schema 5 (2026-10-10) adds ``match_keys``: every name the runtime match tier
compares, folded the way the runtime folds the query (台 read as 臺).  A row's
keys are its name and Traditional-Chinese name; a Taiwan county's derived point
adds its short name and English names derived from the inputs; a Taiwan
GeoNames row adds the Chinese-script names of its alternate-name list, because
GeoNames tags almost none of them zh-Hant and the city would otherwise rank
below every hamlet whose name merely starts with the query.

Schema 4 (2026-09-14) added four identity columns so that a person can tell
two search results apart without reading raw coordinates:

* ``admin1_name`` — the GeoNames admin1 code resolved through
  ``admin1CodesASCII.txt`` when that table is supplied; otherwise null and the
  code is omitted from ``display_name`` instead of being shown raw.
* ``name_zh`` — a Traditional-Chinese name from ``alternateNamesV2.txt`` when
  supplied: ``zh-Hant`` preferred, then ``zh-TW``.  Untagged ``zh`` is not
  used; GeoNames mostly fills it with Simplified forms.
* ``admin3`` — the MOI village field, which is what separates the many
  same-named settlement points inside one town.  GeoNames rows leave it null:
  their admin3 is a bare code with no name table among the declared sources.
* ``disambiguator`` — filled only for rows whose ``display_name`` collides
  with another row; the producer picks the first human-meaningful level that
  separates the group and records which level it used.

The producer rejects rows whose name is blank or contains no word character,
validates every timezone against the IANA database, applies a closed table of
named source corrections, and hashes each input through the same descriptor
it streams from, so the manifest describes the bytes that were consumed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import BinaryIO, TypedDict
import unicodedata
import zipfile
import zoneinfo

_BACKEND_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PACKAGE_ROOT))
from app.core.place_catalog import (
    MATCH_KEY_SEPARATOR,
    TAIWAN_COUNTY_RECORD_PREFIX,
    match_keys_text,
    normalize_search_text,
    place_name_match_key,
)
from scripts.tools.source_tree_identity import sha256_file


GEONAMES_SOURCE_URL = "https://download.geonames.org/export/dump/cities500.zip"
GEONAMES_ADMIN1_SOURCE_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
GEONAMES_ADMIN2_SOURCE_URL = "https://download.geonames.org/export/dump/admin2Codes.txt"
GEONAMES_ALTERNATE_NAMES_SOURCE_URL = "https://download.geonames.org/export/dump/alternateNamesV2.zip"
TAIWAN_ADMIN_SOURCE_URL = (
    "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/"
    "C8DB1578-7554-4DBA-82AD-AD0105992C68/resource/"
    "83911F2D-F552-4E6B-99D0-6267FC9CD0E5/download"
)
TAIWAN_SETTLEMENT_SOURCE_URL = (
    "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/"
    "4A5AB0C9-0395-4B04-AE50-02624075516F/resource/"
    "AE5B85B6-0895-4D32-8027-1713F018A649/download"
)
GENERATOR_VERSION = "place-catalog-builder-v7"
SCHEMA_VERSION = 5
MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_LINE_CHARS = 1_000_000
MAX_SOURCE_ROWS = 10_000_000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024 * 1024

# Closed set of row-rejection reasons.  A rejected row is counted in the
# manifest under its source and reason; it is never silently dropped.
REJECT_EMPTY_NAME = "empty_name"
REJECT_NONWORD_NAME = "nonword_name"
REJECT_MISSING_COORDINATES = "missing_coordinates"
# A record the publisher left in the file while testing its system: the MOI
# settlement file ships 「cindy崙」 with AnotherName and PlaceMean 「cindytest」
# at a point in the sea.  The marker is the ASCII word "test" in a free-text
# field; the source's own text is Chinese or an Indigenous-language name, and
# no other record in the 2026-10-09 files carries it.
REJECT_UPSTREAM_TEST_ROW = "upstream_test_row"
_UPSTREAM_TEST_FIELDS = ("PlaceName", "AnotherName", "PlaceMean")

# The MOI settlement file writes a character its encoding lacked as "?" or
# "●"; GeoNames has a few such names too.  The name is kept as the source has
# it (the record is real and its other characters are searchable) and its label
# carries this mark, so a user does not take the question mark for the name.
MISSING_GLYPHS = ("?", "●")
MISSING_GLYPH_MARK = "（原始資料缺字）"


def _missing_glyph(*names: str | None) -> bool:
    return any(glyph in (name or "") for name in names for glyph in MISSING_GLYPHS)


# Closed set of source-correction outcomes.
CORRECTION_APPLIED = "applied"
CORRECTION_ALREADY_UPSTREAM = "already_upstream"
CORRECTION_STALE_NOT_APPLIED = "stale_not_applied"
CORRECTION_ROW_ABSENT = "row_absent"

# Named corrections to individual source rows.  Each entry states the value
# the source is expected to carry; the correction is applied only when that
# expectation holds, so a silently changed upstream row is reported rather
# than overwritten.  ASTRO-34: two Auckland suburbs carry Pacific/Chatham
# (UTC+12:45 / +13:45) although they sit at 174.74°E, -36.7°, inside
# Pacific/Auckland; the 45-minute offset moves every house cusp.  The other
# rows were found by checking each zone against the country's zone.tab entries
# and against the zone most of the row's nearest same-country neighbours carry;
# rows on a real or disputed boundary are left as GeoNames has them.
SOURCE_TIMEZONE_CORRECTIONS: dict[str, dict[str, str]] = {
    "13631316": {
        "expected": "Pacific/Chatham",
        "corrected": "Pacific/Auckland",
        "reason": (
            "Windsor Park, Auckland (-36.73966, 174.7423) lies on the North "
            "Island; Pacific/Chatham is the Chatham Islands zone (ASTRO-34)"
        ),
    },
    "13631317": {
        "expected": "Pacific/Chatham",
        "corrected": "Pacific/Auckland",
        "reason": (
            "Wairau Valley, Auckland (-36.77235, 174.74107) lies on the North "
            "Island; Pacific/Chatham is the Chatham Islands zone (ASTRO-34)"
        ),
    },
    "13535832": {
        "expected": "Asia/Pontianak",
        "corrected": "Asia/Brunei",
        "reason": (
            "Kampong Ayer, Brunei-Muara (4.88265, 114.94487) is in Brunei; "
            "Asia/Pontianak is West Kalimantan, Indonesia (UTC+7 against UTC+8)"
        ),
    },
    "8558983": {
        "expected": "Asia/Yakutsk",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Kunheda Woerzu Manzu, Heilongjiang (49.88477, 127.5032) is in China; "
            "Asia/Yakutsk is a Russian zone (UTC+9/+10 in 2000 against UTC+8)"
        ),
    },
    "8594765": {
        "expected": "Asia/Yakutsk",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Shangmachang, Heilongjiang (50.37191, 127.32717) is in China; "
            "Asia/Yakutsk is a Russian zone (UTC+9/+10 in 2000 against UTC+8)"
        ),
    },
    "1790891": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Wuyang, Guangdong (21.34766, 110.68829): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "1915237": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Tangwei, Guangdong (21.39545, 110.72832): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "6844287": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Haibin, Guangdong (21.39876, 110.78328): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "8558517": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Meilu, Guangdong (21.43412, 110.77555): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "13405902": {
        "expected": "Asia/Ho_Chi_Minh",
        "corrected": "Asia/Pontianak",
        "reason": (
            "Kota Sambas, West Kalimantan (1.36259, 109.30093) is in Indonesia; "
            "Asia/Ho_Chi_Minh is Vietnam, whose history differs (UTC+8 until 1988 in Pontianak)"
        ),
    },
    "9887822": {
        "expected": "Asia/Hebron",
        "corrected": "Asia/Jerusalem",
        "reason": (
            "Merav, Northern District (32.45285, 35.42152) is an Israeli kibbutz on "
            "Mount Gilboa; Asia/Hebron follows Palestinian DST dates"
        ),
    },
    "97473": {
        "expected": "Asia/Baghdad",
        "corrected": "Europe/Istanbul",
        "reason": (
            "Cey, Hakkari (37.2621, 44.04086) is in Turkey; Asia/Baghdad is Iraq "
            "(UTC+3/+4 in 2000 against UTC+2/+3)"
        ),
    },
    "1216189": {
        "expected": "Asia/Bishkek",
        "corrected": "Asia/Tashkent",
        "reason": (
            "Shohimardon, Fergana (39.98322, 71.80512) is an Uzbek exclave; "
            "Asia/Bishkek is Kyrgyz time (summer UTC+6 in 2000 against UTC+5)"
        ),
    },
    "4653999": {
        "expected": "America/Chicago",
        "corrected": "America/New_York",
        "reason": (
            "Rockwood, Roane County, Tennessee (35.86563, -84.68494): Roane County "
            "keeps Eastern time; Central time starts in the counties to its west"
        ),
    },
    "4263848": {
        "expected": "America/Chicago",
        "corrected": "America/Indiana/Indianapolis",
        "reason": (
            "Rockport, Parke County, Indiana (39.88087, -87.2789): GeoNames codes it Parke County and "
            "links it to that community; Parke County keeps Eastern time, America/Chicago is the zone "
            "of the Spencer County Rockport at 37.88 N"
        ),
    },
    "3471834": {
        "expected": "America/Sao_Paulo",
        "corrected": "America/Cuiaba",
        "reason": (
            "Araguaiana, Mato Grosso (-15.73389, -51.83139): Mato Grosso keeps "
            "America/Cuiaba time, one hour behind Goias across the Araguaia"
        ),
    },
    "3991533": {
        "expected": "America/Mazatlan",
        "corrected": "America/Mexico_City",
        "reason": (
            "Puente de Camotlan, Jalisco (21.6987, -104.07996): Jalisco keeps "
            "central time; America/Mazatlan is the neighbouring Nayarit zone"
        ),
    },
}


# Named source rows left out because another row is the same place.  Each
# entry states the name the source row is expected to carry and the row that
# stays; a source row that no longer carries that name is kept and reported.
CORRECTION_EXCLUDED = "excluded"
SOURCE_ROW_EXCLUSIONS: dict[str, dict[str, str]] = {
    "1679136": {
        "expected_name": "Chang-hua",
        "kept": "1993459",
        "reason": (
            "Changhua City twice: 1679136 Chang-hua and 1993459 Changhua both link "
            "en.wikipedia.org/wiki/Changhua and carry population 226564, 1.3 km apart; "
            "1993459 carries the zh-Hant name 彰化市"
        ),
    },
}


def _table_sha256(table: dict) -> str:
    canonical = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def exclusion_table_sha256() -> str:
    """Digest of the exclusion table; the verifier recomputes it like the correction digest."""

    return _table_sha256(SOURCE_ROW_EXCLUSIONS)


def correction_table_sha256() -> str:
    """Digest of the correction table, recorded so a stale artifact is detectable.

    ``scripts/verification/verify_place_catalog.py`` recomputes this from the
    table it imports and fails when the shipped manifest records another value:
    a correction added or changed here without a rebuild is a stale catalogue.
    """

    return _table_sha256(SOURCE_TIMEZONE_CORRECTIONS)


# Chinese-name language preference, most preferred first.  Untagged "zh" is
# left out: its script is unknown and mostly Simplified, which mixed scripts in
# a Traditional-Chinese picker.
ZH_LANGUAGE_PREFERENCE = ("zh-Hant", "zh-TW")

# Disambiguation levels, most human-meaningful first.  ``coordinate`` is the
# last resort and is reported as such in the manifest.
DISAMBIGUATION_LEVELS = ("admin3", "admin2_name", "coordinate")


class _CountyGroup(TypedDict):
    county_code: str
    coordinates: list[tuple[float, float]]
    aliases: set[str]


@dataclass
class BoundedInput:
    """One input opened once; hashed and streamed through the same descriptor."""

    path: Path
    handle: BinaryIO
    sha256: str
    size_bytes: int

    def rewind(self) -> BinaryIO:
        self.handle.seek(0)
        return self.handle

    def close(self) -> None:
        self.handle.close()


def _open_bounded_input(path: Path) -> BoundedInput:
    """Open ``path`` once, bound it by ``fstat`` on the open descriptor, hash it.

    The previous producer checked the path, read the rows through one open and
    hashed the path through a second.  Replacing the file between those two
    opens produced a manifest that described bytes the build never consumed.
    Here the descriptor is held for the whole build: size, digest and the
    streamed rows all come from the same open file.
    """

    if path.is_symlink():
        raise ValueError(f"input must be a regular non-symlink file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"input must be a regular non-symlink file: {path}") from exc
    handle = os.fdopen(descriptor, "rb")
    try:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode):
            raise ValueError(f"input must be a regular non-symlink file: {path}")
        if status.st_size > MAX_INPUT_BYTES:
            raise ValueError(f"input exceeds bounded byte limit: {path.name}")
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
        handle.seek(0)
    except Exception:
        handle.close()
        raise
    return BoundedInput(path=path, handle=handle, sha256=digest.hexdigest(), size_bytes=status.st_size)


def _as_bounded_input(source: Path | BoundedInput) -> tuple[BoundedInput, bool]:
    if isinstance(source, BoundedInput):
        return source, False
    return _open_bounded_input(Path(source)), True


def _taiwan_character_variants(value: str) -> str:
    """Index both common 臺/台 spellings without a runtime conversion service."""

    return " ".join(dict.fromkeys((value, value.replace("台", "臺"), value.replace("臺", "台"))))


def _has_han(value: str) -> bool:
    return any(unicodedata.name(character, "").startswith("CJK ") for character in value)


def _han_alternate_names(alternate_names: str) -> list[str]:
    """The Chinese-script entries of a GeoNames alternate-name list."""

    return [item.strip() for item in alternate_names.split(",") if item.strip() and _has_han(item)]


def _is_upstream_test_row(row: dict) -> bool:
    return any("test" in str(row.get(field) or "").casefold() for field in _UPSTREAM_TEST_FIELDS)


def _semantic_name_rejection(name: str) -> str | None:
    """Return the closed rejection reason for an unusable name, else None."""

    if not normalize_search_text(name):
        return REJECT_EMPTY_NAME
    if not place_name_match_key(name):
        return REJECT_NONWORD_NAME
    return None


_IANA_ZONES: frozenset[str] | None = None


def _require_iana_timezone(value: str, *, record_id: str) -> None:
    global _IANA_ZONES
    if _IANA_ZONES is None:
        _IANA_ZONES = frozenset(zoneinfo.available_timezones())
    if value not in _IANA_ZONES:
        raise ValueError(f"source row {record_id} carries a timezone unknown to the IANA database: {value!r}")


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        CREATE TABLE places (
            source TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            match_keys TEXT NOT NULL,
            display_name TEXT NOT NULL,
            country_code TEXT NOT NULL,
            admin1 TEXT,
            admin1_name TEXT,
            admin2 TEXT,
            admin3 TEXT,
            name_zh TEXT,
            disambiguator TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timezone TEXT NOT NULL,
            location_precision TEXT NOT NULL,
            population INTEGER NOT NULL,
            source_priority INTEGER NOT NULL,
            UNIQUE(source, source_record_id)
        );
        CREATE VIRTUAL TABLE place_search USING fts5(
            name,
            aliases,
            admin1,
            admin2,
            content='',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        """
    )


def _insert(connection: sqlite3.Connection, record: dict) -> bool:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO places (
            source, source_record_id, name, normalized_name, match_keys, display_name,
            country_code, admin1, admin1_name, admin2, admin3, name_zh,
            disambiguator, latitude, longitude, timezone,
            location_precision, population, source_priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["source"],
            record["source_record_id"],
            record["name"],
            place_name_match_key(record["name"]),
            match_keys_text((record["name"], record.get("name_zh"), *record.get("match_names", ()))),
            record["display_name"],
            record["country_code"],
            record["admin1"],
            record.get("admin1_name"),
            record["admin2"],
            record.get("admin3"),
            record.get("name_zh"),
            None,
            record["latitude"],
            record["longitude"],
            record["timezone"],
            record["location_precision"],
            record["population"],
            record["source_priority"],
        ),
    )
    if cursor.rowcount == 0:
        return False
    rowid = cursor.lastrowid
    connection.execute(
        """
        INSERT INTO place_search(rowid, name, aliases, admin1, admin2)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            rowid,
            normalize_search_text(
                _taiwan_character_variants(
                    f"{record['name']} {record['display_name'].replace(MISSING_GLYPH_MARK, '')}"
                )
            ),
            normalize_search_text(_taiwan_character_variants(record["aliases"])),
            normalize_search_text(record["admin1"] or ""),
            normalize_search_text(record["admin2"] or ""),
        ),
    )
    return True


def _bounded_lines(handle):
    for line in handle:
        if len(line) > MAX_LINE_CHARS:
            raise ValueError("GeoNames row exceeds bounded line limit")
        yield line


def _geonames_lines(source: Path | BoundedInput, *, member_name: str | None = None):
    """Yield the lines of a GeoNames text file or of one member of its archive.

    ``alternateNamesV2.zip`` carries ``iso-languagecodes.txt`` beside the data
    file, so a caller that knows the data member names it; otherwise the
    archive must hold exactly one text file.
    """

    bounded, owned = _as_bounded_input(source)
    try:
        handle = bounded.rewind()
        if zipfile.is_zipfile(handle):
            handle.seek(0)
            with zipfile.ZipFile(handle) as archive:
                members = [
                    info
                    for info in archive.infolist()
                    if (info.filename == member_name if member_name else info.filename.endswith(".txt"))
                ]
                if len(members) != 1:
                    raise ValueError(
                        f"GeoNames archive must contain exactly one {member_name or 'text file'}"
                    )
                member = members[0]
                if member.file_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("GeoNames member exceeds bounded uncompressed limit")
                with archive.open(member) as raw:
                    yield from _bounded_lines(io.TextIOWrapper(raw, encoding="utf-8"))
        else:
            handle.seek(0)
            wrapper = io.TextIOWrapper(handle, encoding="utf-8")
            try:
                yield from _bounded_lines(wrapper)
            finally:
                wrapper.detach()
    finally:
        if owned:
            bounded.close()


def _geonames_display_name(name: str, name_zh: str | None, admin1_name: str | None, country_code: str) -> str:
    label = f"{name_zh}（{name}）" if name_zh and name_zh != name else name
    if _missing_glyph(name, name_zh):
        label += MISSING_GLYPH_MARK
    parts = [label]
    # 「臺北市（Taipei）, 臺北市, TW」 repeats itself; the county is already the label.
    if admin1_name and admin1_name != name_zh:
        parts.append(admin1_name)
    parts.append(country_code)
    return ", ".join(parts)


def load_geonames_code_table(source: Path | BoundedInput | None) -> dict[str, str]:
    """Load ``admin1CodesASCII.txt`` / ``admin2Codes.txt`` as code -> name."""

    if source is None:
        return {}
    bounded, owned = _as_bounded_input(source)
    table: dict[str, str] = {}
    try:
        wrapper = io.TextIOWrapper(bounded.rewind(), encoding="utf-8")
        try:
            for line in _bounded_lines(wrapper):
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 2:
                    continue
                code, name = fields[0], fields[1]
                if code and name:
                    table[code] = name
        finally:
            wrapper.detach()
    finally:
        if owned:
            bounded.close()
    return table


# Taiwan's 22 top-level counties and cities, by MOI CountyCode, with the
# GeoNames admin1.admin2 code of the same area.  GeoNames' admin1 for Taiwan is
# the pre-1998 province (Fukien, Takao, Taipei, Taiwan), so labels read
# 「Kaohsiung, Takao, TW」; its admin2 is the county.  GeoNames codes Hsinchu
# City HSQ and Hsinchu County HSZ (Chiayi City CYI, County CYQ), as its own
# rows and names confirm.  Names are not written here: the county name comes
# from the MOI files and its English names from them and from admin2Codes.
TAIWAN_COUNTY_CODES: dict[str, str] = {
    "63000": "04.TPE", "65000": "03.TPQ", "68000": "04.TAO", "66000": "04.TXG",
    "67000": "04.TNN", "64000": "02.KHH", "10017": "04.KEE", "10018": "04.HSQ",
    "10004": "04.HSZ", "10020": "04.CYI", "10010": "04.CYQ", "10005": "04.MIA",
    "10007": "04.CHA", "10008": "04.NAN", "10009": "04.YUN", "10013": "04.PIF",
    "10002": "04.ILA", "10015": "04.HUA", "10014": "04.TTT", "10016": "04.PEN",
    "9020": "01.KIN", "9007": "01.LIE",
}
# Names in common use for a county that neither source gives as its name.
TAIWAN_COUNTY_EXTRA_NAMES: dict[str, tuple[str, ...]] = {
    "10016": ("Pescadores",),
    "9020": ("Quemoy",),
    "9007": ("Matsu", "Matsu Islands", "馬祖"),
}
_ENGLISH_ADMIN_SUFFIX = re.compile(r"\s*(?:city|county)$", re.IGNORECASE)


def taiwan_counties_by_code(sources: tuple[Path | BoundedInput, ...]) -> dict[str, str]:
    """MOI CountyCode -> County name, read from the MOI files themselves."""

    counties: dict[str, str] = {}
    for source in sources:
        bounded, owned = _as_bounded_input(source)
        try:
            for line_number, row in enumerate(_taiwan_reader(bounded), start=2):
                if line_number > MAX_SOURCE_ROWS + 1:
                    raise ValueError("Taiwan input exceeds bounded row limit")
                county = str(row.get("County") or "").strip()
                code = str(row.get("CountyCode") or "").strip()
                if county and code:
                    if counties.setdefault(code, county) != county:
                        raise ValueError(f"MOI CountyCode {code} names two counties")
        finally:
            if owned:
                bounded.close()
    return counties


def _taiwan_county_search_names(
    county: str, county_code: str, phonetics: set[str], admin2_name: str | None
) -> tuple[str, ...]:
    """Full and short name, the English names of the sources, and named extras.

    Each English name (GeoNames admin2, MOI phonetics such as 「TaibeiCity」 or
    「Pingdong City」) is reduced to its base and given the county's own
    suffix, so 「Taipei City」, 「Taipei」 and 「Taibei」 all name 臺北市.
    """

    suffix = "City" if county.endswith("市") else "County"
    names = [county, county[:-1]]
    for raw in (admin2_name, *sorted(phonetics)):
        if not raw or not raw.isascii():
            continue
        base = _ENGLISH_ADMIN_SUFFIX.sub("", raw.strip()).strip()
        if base:
            names += [base, f"{base} {suffix}"]
    names += TAIWAN_COUNTY_EXTRA_NAMES.get(county_code, ())
    return tuple(dict.fromkeys(names))


def _taiwan_county(geonameid: str, admin1: str, admin2: str, counties: dict[str, str]) -> str:
    county = counties.get(f"{admin1}.{admin2}")
    if county is None:
        raise ValueError(
            f"Taiwan GeoNames row {geonameid} has admin {admin1}.{admin2}, "
            "which TAIWAN_COUNTY_CODES and the MOI files do not name"
        )
    return county


def import_geonames(
    connection: sqlite3.Connection,
    source: Path | BoundedInput,
    *,
    admin1_names: dict[str, str] | None = None,
    taiwan_counties: dict[str, str] | None = None,
    rejected: Counter | None = None,
    corrections: list[dict] | None = None,
    exclusions: list[dict] | None = None,
) -> int:
    """Import cities500; ``taiwan_counties`` maps a GeoNames admin1.admin2 code to its MOI county."""

    admin1_names = admin1_names or {}
    taiwan_counties = taiwan_counties or {}
    rejected = rejected if rejected is not None else Counter()
    corrections = corrections if corrections is not None else []
    exclusions = exclusions if exclusions is not None else []
    pending_corrections = dict(SOURCE_TIMEZONE_CORRECTIONS)
    pending_exclusions = dict(SOURCE_ROW_EXCLUSIONS)
    count = 0
    for line in _geonames_lines(source):
        if count >= MAX_SOURCE_ROWS:
            raise ValueError("GeoNames input exceeds bounded row limit")
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 19:
            raise ValueError("invalid GeoNames cities500 row")
        (
            geonameid,
            name,
            ascii_name,
            alternate_names,
            latitude,
            longitude,
            _feature_class,
            _feature_code,
            country_code,
            _cc2,
            admin1,
            admin2,
            _admin3,
            _admin4,
            population,
            _elevation,
            _dem,
            timezone,
            _modified,
        ) = fields[:19]
        rejection = _semantic_name_rejection(name)
        if rejection is not None:
            rejected[rejection] += 1
            continue
        exclusion = pending_exclusions.pop(geonameid, None)
        if exclusion is not None:
            excluded = name == exclusion["expected_name"]
            exclusions.append(
                {
                    "source": "geonames_cities500",
                    "source_record_id": geonameid,
                    "expected_name": exclusion["expected_name"],
                    "observed_name": name,
                    "kept": exclusion["kept"],
                    "status": CORRECTION_EXCLUDED if excluded else CORRECTION_STALE_NOT_APPLIED,
                    "reason": exclusion["reason"],
                }
            )
            if excluded:
                continue
        correction = pending_corrections.pop(geonameid, None)
        if correction is not None:
            if timezone == correction["expected"]:
                status = CORRECTION_APPLIED
                timezone = correction["corrected"]
            elif timezone == correction["corrected"]:
                status = CORRECTION_ALREADY_UPSTREAM
            else:
                status = CORRECTION_STALE_NOT_APPLIED
            corrections.append(
                {
                    "source": "geonames_cities500",
                    "source_record_id": geonameid,
                    "field": "timezone",
                    "expected": correction["expected"],
                    "corrected": correction["corrected"],
                    "observed": fields[17],
                    "status": status,
                    "reason": correction["reason"],
                }
            )
        _require_iana_timezone(timezone, record_id=geonameid)
        aliases = " ".join(item for item in (ascii_name, alternate_names.replace(",", " ")) if item)
        admin1_name: str | None
        if country_code == "TW":
            admin1_name = _taiwan_county(geonameid, admin1, admin2, taiwan_counties)
        else:
            admin1_name = admin1_names.get(f"{country_code}.{admin1}") if admin1 else None
        # A Taiwan city GeoNames names only in an untagged alias (板橋 for
        # Banqiao) must still be a name match for a Chinese query.  Other
        # countries are left out: their Chinese aliases include other cities'
        # names (台東 for Tokyo's Taito), which would make foreign rows exact.
        match_names = _han_alternate_names(alternate_names) if country_code == "TW" else []
        inserted = _insert(
            connection,
            {
                "source": "geonames_cities500",
                "source_record_id": geonameid,
                "name": name,
                "display_name": _geonames_display_name(name, None, admin1_name, country_code),
                "aliases": aliases,
                "country_code": country_code,
                "admin1": admin1 or None,
                "admin1_name": admin1_name,
                "admin2": admin2 or None,
                "admin3": None,
                "name_zh": None,
                "match_names": match_names,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "timezone": timezone,
                "location_precision": "place_representative_point",
                "population": int(population or 0),
                "source_priority": 10,
            },
        )
        count += int(inserted)
    for geonameid, exclusion in pending_exclusions.items():
        exclusions.append(
            {
                "source": "geonames_cities500",
                "source_record_id": geonameid,
                "expected_name": exclusion["expected_name"],
                "observed_name": None,
                "kept": exclusion["kept"],
                "status": CORRECTION_ROW_ABSENT,
                "reason": exclusion["reason"],
            }
        )
    for geonameid, correction in pending_corrections.items():
        corrections.append(
            {
                "source": "geonames_cities500",
                "source_record_id": geonameid,
                "field": "timezone",
                "expected": correction["expected"],
                "corrected": correction["corrected"],
                "observed": None,
                "status": CORRECTION_ROW_ABSENT,
                "reason": correction["reason"],
            }
        )
    return count


def apply_geonames_chinese_names(connection: sqlite3.Connection, source: Path | BoundedInput | None) -> int:
    """Attach one Traditional-Chinese name per GeoNames row from alternateNamesV2.

    Preference: language in ``ZH_LANGUAGE_PREFERENCE`` order, then the row
    flagged ``isPreferredName``, then the lowest ``alternateNameId`` so a
    rebuild from the same inputs picks the same name.
    """

    if source is None:
        return 0
    wanted = {
        row[0]
        for row in connection.execute(
            "SELECT source_record_id FROM places WHERE source = 'geonames_cities500'"
        )
    }
    best: dict[str, tuple[int, int, int, str]] = {}
    rank = {code: index for index, code in enumerate(ZH_LANGUAGE_PREFERENCE)}
    for line in _geonames_lines(source, member_name="alternateNamesV2.txt"):
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 4:
            continue
        alternate_id, geonameid, language, value = fields[:4]
        if geonameid not in wanted or language not in rank:
            continue
        value = value.strip()
        if not value:
            continue
        preferred = 0 if (len(fields) > 4 and fields[4] == "1") else 1
        try:
            order = int(alternate_id)
        except ValueError:
            continue
        candidate = (rank[language], preferred, order, value)
        if geonameid not in best or candidate < best[geonameid]:
            best[geonameid] = candidate
    updated = 0
    for geonameid, (_rank, _preferred, _order, value) in best.items():
        row = connection.execute(
            "SELECT rowid, name, admin1_name, country_code, match_keys FROM places "
            "WHERE source = 'geonames_cities500' AND source_record_id = ?",
            (geonameid,),
        ).fetchone()
        if row is None:
            continue
        rowid, name, admin1_name, country_code, match_keys = row
        connection.execute(
            "UPDATE places SET name_zh = ?, display_name = ?, match_keys = ? WHERE rowid = ?",
            (
                value,
                _geonames_display_name(name, value, admin1_name, country_code),
                match_keys_text((*match_keys.split(MATCH_KEY_SEPARATOR), value)),
                rowid,
            ),
        )
        updated += 1
    return updated


def _taiwan_record_id(kind: str, row: dict) -> str:
    stable = "\x1f".join(
        str(row.get(key) or "")
        for key in ("Type", "PlaceName", "CountyCode", "TownCode", "Village", "Longitude", "Latitude")
    ).encode("utf-8")
    return f"tw-moi-{kind}:{hashlib.sha256(stable).hexdigest()[:20]}"


def _taiwan_reader(bounded: BoundedInput):
    wrapper = io.TextIOWrapper(bounded.rewind(), encoding="utf-8-sig", newline="")
    try:
        yield from csv.DictReader(wrapper)
    finally:
        wrapper.detach()


def import_taiwan(
    connection: sqlite3.Connection,
    source: Path | BoundedInput,
    *,
    kind: str,
    precision: str,
    source_priority: int,
    rejected: Counter | None = None,
) -> int:
    rejected = rejected if rejected is not None else Counter()
    bounded, owned = _as_bounded_input(source)
    count = 0
    try:
        for line_number, row in enumerate(_taiwan_reader(bounded), start=2):
            if line_number > MAX_SOURCE_ROWS + 1:
                raise ValueError("Taiwan input exceeds bounded row limit")
            if not row.get("Longitude") or not row.get("Latitude"):
                rejected[REJECT_MISSING_COORDINATES] += 1
                continue
            if _is_upstream_test_row(row):
                rejected[REJECT_UPSTREAM_TEST_ROW] += 1
                continue
            name = str(row.get("PlaceName") or "")
            rejection = _semantic_name_rejection(name)
            if rejection is not None:
                rejected[rejection] += 1
                continue
            aliases = " ".join(
                str(row.get(key) or "") for key in ("ChinesePhonetic", "CommonPhonetic", "AnotherName")
            )
            label = f"{name}{MISSING_GLYPH_MARK}" if _missing_glyph(name) else name
            display_parts = [label, row.get("Town") or "", row.get("County") or ""]
            inserted = _insert(
                connection,
                {
                    "source": "taiwan_moi_place_names",
                    "source_record_id": _taiwan_record_id(kind, row),
                    "name": name,
                    "display_name": ", ".join(item for item in display_parts if item),
                    "aliases": aliases,
                    "country_code": "TW",
                    "admin1": row.get("County") or None,
                    "admin1_name": row.get("County") or None,
                    "admin2": row.get("Town") or None,
                    "admin3": (row.get("Village") or "").strip() or None,
                    "latitude": float(row["Latitude"]),
                    "longitude": float(row["Longitude"]),
                    "timezone": "Asia/Taipei",
                    "location_precision": precision,
                    "population": 0,
                    "source_priority": source_priority,
                },
            )
            count += int(inserted)
    finally:
        if owned:
            bounded.close()
    return count


def import_taiwan_county_representatives(
    connection: sqlite3.Connection,
    sources: tuple[Path | BoundedInput, ...],
    *,
    admin2_names: dict[str, str] | None = None,
) -> int:
    """Add one explicitly derived representative point for each county/city.

    The MOI files name the top-level administrative areas but omit coordinates
    on those rows.  Their coordinate-bearing child records form the closed
    source set used here.  The arithmetic mean is only a search/picker anchor;
    ``location_precision`` prevents it being presented as a city hall,
    geometric centroid, address, or birth location.
    """

    groups: dict[str, _CountyGroup] = {}
    for source in sources:
        bounded, owned = _as_bounded_input(source)
        try:
            for line_number, row in enumerate(_taiwan_reader(bounded), start=2):
                if line_number > MAX_SOURCE_ROWS + 1:
                    raise ValueError("Taiwan input exceeds bounded row limit")
                county = str(row.get("County") or "").strip()
                if not county:
                    continue
                group = groups.setdefault(
                    county,
                    {"county_code": str(row.get("CountyCode") or ""), "coordinates": [], "aliases": set()},
                )
                if row.get("Longitude") and row.get("Latitude") and not _is_upstream_test_row(row):
                    group["coordinates"].append((float(row["Longitude"]), float(row["Latitude"])))
                if row.get("PlaceName") == county:
                    group["aliases"].update(
                        str(row.get(key) or "").strip()
                        for key in ("ChinesePhonetic", "CommonPhonetic", "AnotherName")
                        if str(row.get(key) or "").strip()
                    )
        finally:
            if owned:
                bounded.close()

    admin2_names = admin2_names or {}
    count = 0
    for county in sorted(groups):
        group = groups[county]
        coordinates = group["coordinates"]
        if not coordinates:
            continue
        geonames_admin = TAIWAN_COUNTY_CODES.get(group["county_code"])
        names = _taiwan_county_search_names(
            county,
            group["county_code"],
            group["aliases"],
            admin2_names.get(f"TW.{geonames_admin}") if geonames_admin else None,
        )
        longitude = sum(item[0] for item in coordinates) / len(coordinates)
        latitude = sum(item[1] for item in coordinates) / len(coordinates)
        stable = f"{group['county_code']}\x1f{county}".encode("utf-8")
        count += int(
            _insert(
                connection,
                {
                    "source": "taiwan_moi_place_names",
                    "source_record_id": f"{TAIWAN_COUNTY_RECORD_PREFIX}{hashlib.sha256(stable).hexdigest()[:20]}",
                    "name": county,
                    "display_name": f"{county}, TW",
                    "aliases": " ".join(sorted(group["aliases"] | set(names[1:]))),
                    "match_names": names,
                    "country_code": "TW",
                    "admin1": county,
                    "admin1_name": county,
                    "admin2": None,
                    "admin3": None,
                    "latitude": round(latitude, 6),
                    "longitude": round(longitude, 6),
                    "timezone": "Asia/Taipei",
                    "location_precision": ("administrative_area_representative_point"),
                    "population": 0,
                    "source_priority": -1,
                },
            )
        )
    return count


def _coordinate_label(latitude: float, longitude: float, digits: int) -> str:
    return (
        f"{abs(latitude):.{digits}f}°{'N' if latitude >= 0 else 'S'} "
        f"{abs(longitude):.{digits}f}°{'E' if longitude >= 0 else 'W'}"
    )


def disambiguate_duplicate_labels(
    connection: sqlite3.Connection, *, admin2_names: dict[str, str] | None = None
) -> dict:
    """Fill ``disambiguator`` for every group of rows sharing a display_name.

    For each colliding group the first level in ``DISAMBIGUATION_LEVELS``
    whose values are distinct across the group's distinct coordinate points is
    used.  The coordinate fallback rounds to 0.01° and widens to 0.0001° only
    when two points share a cell.
    """

    admin2_names = admin2_names or {}
    groups: dict[str, list[tuple]] = {}
    for row in connection.execute(
        "SELECT rowid, display_name, country_code, admin1, admin2, admin3, "
        "latitude, longitude FROM places ORDER BY rowid"
    ):
        groups.setdefault(row[1], []).append(row)
    level_used: Counter = Counter()
    group_count = 0
    row_count = 0
    updates: list[tuple[str | None, int]] = []
    for _display_name, rows in groups.items():
        if len(rows) < 2:
            continue
        group_count += 1
        row_count += len(rows)
        points = {(row[6], row[7]) for row in rows}

        def candidates(level: str) -> list[str | None]:
            values: list[str | None] = []
            for row in rows:
                _rowid, _label, country, admin1, admin2, admin3, lat, lon = row
                if level == "admin3":
                    values.append(admin3)
                elif level == "admin2_name":
                    key = f"{country}.{admin1}.{admin2}" if admin2 else None
                    values.append(admin2_names.get(key) if key else None)
                else:
                    values.append(_coordinate_label(lat, lon, 2))
            return values

        chosen_level = "coordinate"
        chosen_values: list[str | None] = []
        for level in DISAMBIGUATION_LEVELS:
            values = candidates(level)
            if any(value is None for value in values):
                continue
            distinct_by_point: dict[tuple, set] = {}
            for row, value in zip(rows, values, strict=True):
                distinct_by_point.setdefault((row[6], row[7]), set()).add(value)
            point_values = [next(iter(items)) for items in distinct_by_point.values() if len(items) == 1]
            if len(point_values) == len(points) and len(set(point_values)) == len(points):
                chosen_level = level
                chosen_values = values
                break
        if chosen_level == "coordinate" and not chosen_values:
            chosen_values = candidates("coordinate")
            if len(set(chosen_values)) < len(points):
                chosen_values = [_coordinate_label(row[6], row[7], 4) for row in rows]
        level_used[chosen_level] += 1
        for row, value in zip(rows, chosen_values, strict=True):
            updates.append((value, row[0]))
    connection.executemany("UPDATE places SET disambiguator = ? WHERE rowid = ?", updates)
    return {
        "groups": group_count,
        "rows": row_count,
        "level_used": dict(sorted(level_used.items())),
        "levels_in_preference_order": list(DISAMBIGUATION_LEVELS),
        "policy": (
            "rows sharing one display_name receive the first level in "
            "preference order that separates their distinct coordinate points; "
            "coordinate is the last resort"
        ),
    }


def check_timezones_against_coordinates(connection: sqlite3.Connection) -> dict:
    """Compare every GeoNames timezone with the zone at its coordinate.

    Uses ``timezonefinder`` when it is importable; otherwise reports
    ``not_run`` rather than claiming a pass.  A mismatch after the named
    corrections fails the build: a wrong zone changes every house cusp.
    """

    try:
        import timezonefinder  # type: ignore[import-not-found]
    except ImportError:
        return {"status": "not_run", "engine": None, "reason": "timezonefinder_not_installed"}
    finder = timezonefinder.TimezoneFinder(in_memory=True)
    mismatches: list[dict] = []
    checked = 0
    for record_id, lat, lon, zone in connection.execute(
        "SELECT source_record_id, latitude, longitude, timezone FROM places "
        "WHERE source = 'geonames_cities500'"
    ):
        checked += 1
        found = finder.timezone_at(lat=lat, lng=lon)
        if found is None or found == zone:
            continue
        mismatches.append(
            {"source_record_id": record_id, "catalog_timezone": zone, "coordinate_timezone": found}
        )
    if mismatches:
        preview = ", ".join(
            f"{item['source_record_id']} {item['catalog_timezone']}->{item['coordinate_timezone']}"
            for item in mismatches[:20]
        )
        raise ValueError(
            f"{len(mismatches)} GeoNames rows carry a timezone that disagrees "
            f"with their coordinate: {preview}"
        )
    return {
        "status": "passed",
        "engine": f"timezonefinder {getattr(timezonefinder, '__version__', '?')}",
        "rows_checked": checked,
    }


def build_catalog(
    *,
    geonames_zip: Path,
    taiwan_admin_csv: Path,
    taiwan_settlement_csv: Path,
    output: Path,
    source_date: str,
    geonames_admin1_codes: Path | None = None,
    geonames_admin2_codes: Path | None = None,
    geonames_alternate_names: Path | None = None,
) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    working_output = output.with_name(f".{output.name}.building")
    if working_output.exists():
        working_output.unlink()
    inputs: dict[str, BoundedInput] = {}
    connection = sqlite3.connect(working_output)
    try:
        inputs["geonames_cities500"] = _open_bounded_input(geonames_zip)
        inputs["taiwan_moi_administrative"] = _open_bounded_input(taiwan_admin_csv)
        inputs["taiwan_moi_settlement"] = _open_bounded_input(taiwan_settlement_csv)
        optional = {
            "geonames_admin1_codes": geonames_admin1_codes,
            "geonames_admin2_codes": geonames_admin2_codes,
            "geonames_alternate_names": geonames_alternate_names,
        }
        for key, path in optional.items():
            if path is not None:
                inputs[key] = _open_bounded_input(path)

        admin1_names = load_geonames_code_table(inputs.get("geonames_admin1_codes"))
        admin2_names = load_geonames_code_table(inputs.get("geonames_admin2_codes"))
        _schema(connection)
        rejected: dict[str, Counter] = {
            "geonames_cities500": Counter(),
            "taiwan_moi_administrative": Counter(),
            "taiwan_moi_settlement": Counter(),
        }
        corrections: list[dict] = []
        exclusions: list[dict] = []
        moi_inputs = (inputs["taiwan_moi_administrative"], inputs["taiwan_moi_settlement"])
        moi_counties = taiwan_counties_by_code(moi_inputs)
        taiwan_counties = {
            geonames_admin: moi_counties[code]
            for code, geonames_admin in TAIWAN_COUNTY_CODES.items()
            if code in moi_counties
        }
        counts = {
            "geonames_cities500": import_geonames(
                connection,
                inputs["geonames_cities500"],
                admin1_names=admin1_names,
                taiwan_counties=taiwan_counties,
                rejected=rejected["geonames_cities500"],
                corrections=corrections,
                exclusions=exclusions,
            ),
            "taiwan_moi_administrative": import_taiwan(
                connection,
                inputs["taiwan_moi_administrative"],
                kind="administrative",
                precision="administrative_area_representative_point",
                source_priority=1,
                rejected=rejected["taiwan_moi_administrative"],
            ),
            "taiwan_moi_settlement": import_taiwan(
                connection,
                inputs["taiwan_moi_settlement"],
                kind="settlement",
                precision="settlement_representative_point",
                source_priority=0,
                rejected=rejected["taiwan_moi_settlement"],
            ),
        }
        counts["taiwan_moi_county_representative"] = import_taiwan_county_representatives(
            connection, moi_inputs, admin2_names=admin2_names
        )
        chinese_names_attached = apply_geonames_chinese_names(
            connection, inputs.get("geonames_alternate_names")
        )
        timezone_check = check_timezones_against_coordinates(connection)
        label_disambiguation = disambiguate_duplicate_labels(connection, admin2_names=admin2_names)
        (rows_marked,) = connection.execute(
            "SELECT COUNT(*) FROM places WHERE instr(display_name, ?) > 0", (MISSING_GLYPH_MARK,)
        ).fetchone()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "source_snapshot_date": source_date,
            "row_counts": counts,
            "geonames_chinese_names_attached": chinese_names_attached,
            "rejected_rows": {source: dict(sorted(counter.items())) for source, counter in rejected.items()},
            "rejection_reasons": [
                REJECT_EMPTY_NAME, REJECT_NONWORD_NAME, REJECT_MISSING_COORDINATES, REJECT_UPSTREAM_TEST_ROW,
            ],
            "source_corrections": corrections,
            "source_corrections_table_sha256": correction_table_sha256(),
            "source_exclusions": exclusions,
            "source_exclusions_table_sha256": exclusion_table_sha256(),
            "timezone_coordinate_check": timezone_check,
            "label_disambiguation": label_disambiguation,
            "missing_glyph_policy": {
                "glyphs": list(MISSING_GLYPHS),
                "label_mark": MISSING_GLYPH_MARK,
                "rows_marked": rows_marked,
            },
            "display_name_policy": {
                "admin1": ("resolved_name" if admin1_names else "code_omitted_no_admin1_table"),
                "chinese_name": (
                    "zh_hant_then_zh_tw_leads_label"
                    if "geonames_alternate_names" in inputs
                    else "not_attached_no_alternate_names_table"
                ),
                "raw_admin1_code_column": "admin1",
                "taiwan_admin1": "county_from_geonames_admin2",
            },
            "licenses": {
                "geonames_cities500": "CC-BY-4.0",
                "taiwan_moi_place_names": ("Taiwan Government Data Open License 1.0"),
            },
            "sources": {
                "geonames_cities500": GEONAMES_SOURCE_URL,
                "geonames_admin1_codes": GEONAMES_ADMIN1_SOURCE_URL,
                "geonames_admin2_codes": GEONAMES_ADMIN2_SOURCE_URL,
                "geonames_alternate_names": GEONAMES_ALTERNATE_NAMES_SOURCE_URL,
                "taiwan_moi_administrative": TAIWAN_ADMIN_SOURCE_URL,
                "taiwan_moi_settlement": TAIWAN_SETTLEMENT_SOURCE_URL,
            },
            "source_sha256": {key: bounded.sha256 for key, bounded in sorted(inputs.items())},
            "source_size_bytes": {key: bounded.size_bytes for key, bounded in sorted(inputs.items())},
            "source_hash_basis": ("sha256_over_the_descriptor_the_rows_were_read_from"),
            "runtime_outbound": False,
            "derived_record_policy": {
                "taiwan_moi_county_representative": (
                    "arithmetic mean of all coordinate-bearing MOI child "
                    "records in the named county/city except upstream test rows; picker anchor only"
                )
            },
        }
        connection.executemany(
            """
            INSERT INTO catalog_metadata(key, value_json)
            VALUES (?, ?)
            """,
            [
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                for key, value in metadata.items()
            ],
        )
        connection.commit()
        connection.execute("VACUUM")
        if working_output.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("place catalog exceeds bounded output limit")
    except Exception:
        connection.close()
        working_output.unlink(missing_ok=True)
        raise
    finally:
        for bounded in inputs.values():
            bounded.close()
        if working_output.exists():
            connection.close()
    os.replace(working_output, output)
    return metadata


def build_artifact_manifest(metadata: dict, *, catalog_path: Path) -> dict:
    return {
        "producer": "scripts/validation/build_place_catalog.py",
        "generator_version": GENERATOR_VERSION,
        "rebuild": {
            "command": (
                "python -m scripts.validation.build_place_catalog "
                "--geonames-zip <cities500.zip> "
                "--geonames-admin1-codes <admin1CodesASCII.txt> "
                "--geonames-admin2-codes <admin2Codes.txt> "
                "--geonames-alternate-names <alternateNamesV2.zip> "
                "--taiwan-admin-csv <taiwan-admin.csv> "
                "--taiwan-settlement-csv <taiwan-settlement.csv> "
                "--output backend/place_data/places.sqlite3 "
                "--manifest backend/place_data/catalog_manifest.json "
                f"--source-date {metadata['source_snapshot_date']}"
            ),
            "exact_inputs_required": True,
            "input_identity": "source_sha256",
        },
        "catalog": {
            "filename": catalog_path.name,
            "sha256": sha256_file(catalog_path),
            "size_bytes": catalog_path.stat().st_size,
        },
        "licenses": metadata["licenses"],
        "derived_record_policy": metadata["derived_record_policy"],
        "row_counts": metadata["row_counts"],
        "rejected_rows": metadata["rejected_rows"],
        "source_corrections": metadata["source_corrections"],
        "source_corrections_table_sha256": metadata["source_corrections_table_sha256"],
        "source_exclusions": metadata["source_exclusions"],
        "source_exclusions_table_sha256": metadata["source_exclusions_table_sha256"],
        "timezone_coordinate_check": metadata["timezone_coordinate_check"],
        "label_disambiguation": metadata["label_disambiguation"],
        "missing_glyph_policy": metadata["missing_glyph_policy"],
        "display_name_policy": metadata["display_name_policy"],
        "runtime_policy": {
            "catalog_mode": "bundled_read_only_sqlite",
            "runtime_outbound": metadata["runtime_outbound"],
            "user_data_written": False,
        },
        "schema_version": metadata["schema_version"],
        "source_sha256": metadata["source_sha256"],
        "source_hash_basis": metadata["source_hash_basis"],
        "source_snapshot_date": metadata["source_snapshot_date"],
        "sources": metadata["sources"],
    }


def write_artifact_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_name(f".{path.name}.building")
    try:
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geonames-zip", type=Path, required=True)
    parser.add_argument("--geonames-admin1-codes", type=Path)
    parser.add_argument("--geonames-admin2-codes", type=Path)
    parser.add_argument("--geonames-alternate-names", type=Path)
    parser.add_argument("--taiwan-admin-csv", type=Path, required=True)
    parser.add_argument("--taiwan-settlement-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="default: catalog_manifest.json beside --output")
    parser.add_argument("--source-date", required=True)
    args = parser.parse_args()
    metadata = build_catalog(
        geonames_zip=args.geonames_zip,
        taiwan_admin_csv=args.taiwan_admin_csv,
        taiwan_settlement_csv=args.taiwan_settlement_csv,
        output=args.output,
        source_date=args.source_date,
        geonames_admin1_codes=args.geonames_admin1_codes,
        geonames_admin2_codes=args.geonames_admin2_codes,
        geonames_alternate_names=args.geonames_alternate_names,
    )
    manifest_path = args.manifest or (args.output.parent / "catalog_manifest.json")
    manifest = build_artifact_manifest(metadata, catalog_path=args.output)
    write_artifact_manifest(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
