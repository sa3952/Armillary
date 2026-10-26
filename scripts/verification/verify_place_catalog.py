#!/usr/bin/env python3
"""Verify the immutable place catalog against its tracked manifest.

A matching SHA-256 only says the bytes were not altered after the manifest was
written; it says nothing about whether those bytes carry the producer's named
corrections.  So besides identity and integrity this reads every corrected row
(timezone and admin1 code) from the catalogue itself and, in the repository,
binds the artifact to the producer that should have built it: a correction or
generator version changed in ``scripts/validation/build_place_catalog.py``
without a rebuild fails here.

The build's timezone/coordinate cross-check outcome is bound too: the
manifest and the catalogue must record the same closed-set outcome, a pass
must name its engine and cover every GeoNames row, and an outcome of
``not_run`` is printed on every run so that "VERIFIED" never reads as a
checked zone.

The container image ships this verifier and the catalogue but not the
producer, so the entrypoint passes ``--installed-image``: the freshness binding
was enforced in the repository, and the image still checks every recorded
correction row by row.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sqlite3
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "backend" / "place_data"
MANIFEST_PATH = DATA_DIR / "catalog_manifest.json"
PRODUCER_PATH = PROJECT_ROOT / "scripts" / "validation" / "build_place_catalog.py"
APPLIED_CORRECTION_STATUSES = frozenset({"applied", "already_upstream"})


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _table_sha256(table: dict) -> str:
    # Kept apart from the producer's identical function on purpose: the
    # verifier recomputes the table digest itself rather than trust the code
    # that wrote it, and the image carries this file without the producer.
    canonical = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load_producer():
    """Import the producer the repository would rebuild the catalogue with."""

    if not PRODUCER_PATH.is_file():
        raise SystemExit(f"place catalog producer is missing: {PRODUCER_PATH}")
    for entry in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    module = importlib.import_module("scripts.validation.build_place_catalog")
    if Path(module.__file__ or "").resolve() != PRODUCER_PATH.resolve():
        raise SystemExit(f"imported a place catalog producer other than {PRODUCER_PATH}")
    return module


def _check_producer_freshness(manifest: dict) -> None:
    producer = _load_producer()
    if manifest.get("generator_version") != producer.GENERATOR_VERSION:
        raise SystemExit(
            "place catalog generator version differs from the producer "
            f"({manifest.get('generator_version')!r} != {producer.GENERATOR_VERSION!r}); rebuild the catalogue"
        )
    table = producer.SOURCE_TIMEZONE_CORRECTIONS
    if not table:
        raise SystemExit("producer correction table is empty; there is no correction to verify")
    if manifest.get("source_corrections_table_sha256") != _table_sha256(table):
        raise SystemExit("producer correction table changed since the catalogue was built; rebuild it")
    recorded = {item.get("source_record_id"): item for item in manifest.get("source_corrections") or []}
    if set(recorded) != set(table):
        raise SystemExit(
            "producer correction table and recorded corrections name different rows: "
            f"{sorted(set(table) ^ set(recorded))}"
        )
    for record_id, correction in table.items():
        if recorded[record_id].get("corrected") != correction["corrected"]:
            raise SystemExit(f"recorded correction for {record_id} differs from the producer")
    admin1_table = producer.SOURCE_ADMIN1_CORRECTIONS
    if manifest.get("source_admin1_corrections_table_sha256") != _table_sha256(admin1_table):
        raise SystemExit("producer admin1 correction table changed since the catalogue was built; rebuild it")
    recorded_admin1 = {
        item.get("source_record_id"): item for item in manifest.get("source_admin1_corrections") or []
    }
    if set(recorded_admin1) != set(admin1_table):
        raise SystemExit(
            "producer admin1 correction table and recorded admin1 corrections name different rows: "
            f"{sorted(set(admin1_table) ^ set(recorded_admin1))}"
        )
    for record_id, correction in admin1_table.items():
        if recorded_admin1[record_id].get("corrected") != correction["corrected"]:
            raise SystemExit(f"recorded admin1 correction for {record_id} differs from the producer")
    chinese = producer.SOURCE_CHINESE_NAME_EXCLUSIONS
    if manifest.get("source_chinese_name_exclusions_table_sha256") != _table_sha256(chinese):
        raise SystemExit("producer Chinese-name exclusion table changed since the catalogue was built; rebuild it")
    recorded_chinese = {
        item.get("source_record_id"): item for item in manifest.get("source_chinese_name_exclusions") or []
    }
    if set(recorded_chinese) != set(chinese) or any(
        recorded_chinese[record_id].get("names") != entry["names"] for record_id, entry in chinese.items()
    ):
        raise SystemExit("producer Chinese-name exclusion table and recorded exclusions differ")
    folding = manifest.get("han_script_folding") or {}
    if folding.get("source_table_sha256") != _table_sha256(producer.load_han_fold_source()["simplified_to_traditional"]):
        raise SystemExit("the Simplified-to-Traditional table changed since the catalogue was built; rebuild it")
    exclusions = producer.SOURCE_ROW_EXCLUSIONS
    if manifest.get("source_exclusions_table_sha256") != _table_sha256(exclusions):
        raise SystemExit("producer exclusion table changed since the catalogue was built; rebuild it")
    recorded_exclusions = {item.get("source_record_id") for item in manifest.get("source_exclusions") or []}
    if recorded_exclusions != set(exclusions):
        raise SystemExit(
            "producer exclusion table and recorded exclusions name different rows: "
            f"{sorted(recorded_exclusions ^ set(exclusions))}"
        )


def _check_corrections(connection: sqlite3.Connection, manifest: dict) -> int:
    corrections = manifest.get("source_corrections")
    if not isinstance(corrections, list) or not corrections:
        raise SystemExit("place catalog manifest records no source correction to verify")
    stored = connection.execute(
        "SELECT value_json FROM catalog_metadata WHERE key = 'source_corrections'"
    ).fetchone()
    if stored is None or json.loads(stored[0]) != corrections:
        raise SystemExit("catalogue and manifest record different source corrections")
    for item in corrections:
        record_id = item.get("source_record_id")
        if item.get("field") != "timezone" or item.get("source") != "geonames_cities500":
            raise SystemExit(f"unsupported source correction for {record_id}")
        if item.get("status") not in APPLIED_CORRECTION_STATUSES:
            raise SystemExit(f"source correction {record_id} was not applied: {item.get('status')}")
        rows = connection.execute(
            "SELECT timezone FROM places WHERE source = ? AND source_record_id = ?",
            (item["source"], record_id),
        ).fetchall()
        if [row[0] for row in rows] != [item.get("corrected")]:
            raise SystemExit(
                f"place catalog row {record_id} does not carry its corrected timezone "
                f"{item.get('corrected')!r}: {[row[0] for row in rows]!r}"
            )
    return len(corrections)


def _check_admin1_corrections(connection: sqlite3.Connection, manifest: dict) -> int:
    """Each recorded admin1 correction was applied: the row carries the corrected code and its name."""

    corrections = manifest.get("source_admin1_corrections")
    if not isinstance(corrections, list):
        raise SystemExit("place catalog manifest records no admin1 correction list")
    stored = connection.execute(
        "SELECT value_json FROM catalog_metadata WHERE key = 'source_admin1_corrections'"
    ).fetchone()
    if stored is None or json.loads(stored[0]) != corrections:
        raise SystemExit("catalogue and manifest record different admin1 corrections")
    for item in corrections:
        record_id = item.get("source_record_id")
        if item.get("field") != "admin1" or item.get("source") != "geonames_cities500":
            raise SystemExit(f"unsupported admin1 correction for {record_id}")
        if item.get("status") not in APPLIED_CORRECTION_STATUSES or not item.get("corrected_name"):
            raise SystemExit(f"admin1 correction {record_id} was not applied: {item.get('status')}")
        rows = connection.execute(
            "SELECT country_code, admin1, admin1_name FROM places WHERE source = ? AND source_record_id = ?",
            (item["source"], record_id),
        ).fetchall()
        wanted = [(item.get("country_code"), item.get("corrected"), item.get("corrected_name"))]
        if [tuple(row) for row in rows] != wanted:
            raise SystemExit(
                f"place catalog row {record_id} does not carry its corrected admin1 {wanted!r}: "
                f"{[tuple(row) for row in rows]!r}"
            )
    return len(corrections)


def _check_exclusions(connection: sqlite3.Connection, manifest: dict) -> None:
    """Each recorded exclusion was applied: the row is absent and the row kept in its place, if any, is present."""

    exclusions = manifest.get("source_exclusions")
    if not isinstance(exclusions, list):
        raise SystemExit("place catalog manifest records no source exclusion list")
    stored = connection.execute(
        "SELECT value_json FROM catalog_metadata WHERE key = 'source_exclusions'"
    ).fetchone()
    if stored is None or json.loads(stored[0]) != exclusions:
        raise SystemExit("catalogue and manifest record different source exclusions")
    for item in exclusions:
        record_id = item.get("source_record_id")
        if item.get("source") != "geonames_cities500" or item.get("status") != "excluded":
            raise SystemExit(f"source exclusion {record_id} was not applied: {item.get('status')}")
        expected_rows = [(record_id, 0)]
        if item.get("kept") is not None:
            expected_rows.append((item["kept"], 1))
        for wanted, count in expected_rows:
            (found,) = connection.execute(
                "SELECT COUNT(*) FROM places WHERE source = 'geonames_cities500' AND source_record_id = ?",
                (wanted,),
            ).fetchone()
            if found != count:
                raise SystemExit(f"place catalog exclusion {record_id}: row {wanted} found {found} times, expected {count}")


def _stored_metadata(connection: sqlite3.Connection, key: str):
    stored = connection.execute("SELECT value_json FROM catalog_metadata WHERE key = ?", (key,)).fetchone()
    return None if stored is None else json.loads(stored[0])


def _check_chinese_name_exclusions(connection: sqlite3.Connection, manifest: dict) -> None:
    """No row leads its label with a Chinese name the producer excludes for it."""

    exclusions = manifest.get("source_chinese_name_exclusions")
    if not isinstance(exclusions, list) or not exclusions:
        raise SystemExit("place catalog manifest records no Chinese-name exclusion list")
    if _stored_metadata(connection, "source_chinese_name_exclusions") != exclusions:
        raise SystemExit("catalogue and manifest record different Chinese-name exclusions")
    for item in exclusions:
        record_id, names = item.get("source_record_id"), item.get("names")
        if item.get("status") not in {"excluded", "not_offered"} or not names:
            raise SystemExit(f"Chinese-name exclusion {record_id} has no recorded outcome")
        rows = connection.execute(
            "SELECT name_zh, display_name, match_keys FROM places "
            "WHERE source = 'geonames_cities500' AND source_record_id = ?",
            (record_id,),
        ).fetchall()
        for name_zh, display_name, match_keys in rows:
            if name_zh in names or any(name in display_name for name in names) or any(
                f"\x1f{name}\x1f" in match_keys for name in names
            ):
                raise SystemExit(f"place catalog row {record_id} still carries an excluded Chinese name")


def _check_han_script_folding(connection: sqlite3.Connection, manifest: dict) -> int:
    """The folding table the runtime reads holds no character a MOI name writes.

    Folding a query character that a Taiwanese name uses as written (后 of
    后里) would send that name elsewhere; the check reads the catalogue's own
    MOI rows, not the producer's account of them.
    """

    folding = manifest.get("han_script_folding")
    if not isinstance(folding, dict) or not isinstance(folding.get("simplified_to_traditional"), dict):
        raise SystemExit("place catalog manifest records no script folding table")
    if _stored_metadata(connection, "han_script_folding") != folding:
        raise SystemExit("catalogue and manifest record different script folding tables")
    table = folding["simplified_to_traditional"]
    if manifest.get("han_script_folding_table_sha256") != _table_sha256(table) or _stored_metadata(
        connection, "han_script_folding_table_sha256"
    ) != _table_sha256(table):
        raise SystemExit("script folding table digest does not match the table")
    written: set[str] = set()
    for row in connection.execute(
        "SELECT name, coalesce(admin1, ''), coalesce(admin2, ''), coalesce(admin3, '') FROM places "
        "WHERE source = 'taiwan_moi_place_names' AND substr(source_record_id, 1, 15) != 'tw-moi-county-d' "
        "AND substr(source_record_id, 1, 13) != 'tw-moi-town-d'"
    ):
        written.update("".join(row))
    kept = set(folding.get("kept_as_written_because_taiwan_names_use_them") or "")
    if not written or written & set(table):
        raise SystemExit(f"script folding would rewrite characters MOI names use: {''.join(sorted(written & set(table)))}")
    if kept & set(table):
        raise SystemExit("script folding both keeps and folds a character")
    return len(table)


def _check_taiwan_counties(connection: sqlite3.Connection, expected_count: int | None) -> int:
    """Each county has one derived point carrying its full, short and an English name.

    The runtime ranks a county name to that point only through its stored
    match keys; a catalogue missing a county or its names would send 「臺東」
    or 「Penghu」 abroad again while every hash still matched.  In the
    repository the count is bound to the producer's county table.
    """

    for entry in (str(PROJECT_ROOT), str(PROJECT_ROOT / "backend")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    from app.core.place_catalog import MATCH_KEY_SEPARATOR, TAIWAN_COUNTY_RECORD_PREFIX, place_tier_key

    rows = connection.execute(
        "SELECT name, match_keys FROM places WHERE substr(source_record_id, 1, ?) = ?",
        (len(TAIWAN_COUNTY_RECORD_PREFIX), TAIWAN_COUNTY_RECORD_PREFIX),
    ).fetchall()
    names = [name for name, _keys in rows]
    if not rows or len(set(names)) != len(names) or (expected_count is not None and len(rows) != expected_count):
        raise SystemExit(
            f"Taiwan county representative points: {len(rows)} rows, {len(set(names))} names, "
            f"expected {expected_count}"
        )
    for name, match_keys in rows:
        stored = set(match_keys.split(MATCH_KEY_SEPARATOR)) - {""}
        if not {place_tier_key(name), place_tier_key(name[:-1])} <= stored or not any(
            key.isascii() for key in stored
        ):
            raise SystemExit(f"Taiwan county {name} lacks its full, short or English match keys")
    return len(rows)


def _check_missing_glyph_marks(connection: sqlite3.Connection, manifest: dict) -> None:
    """Every name with a source placeholder glyph is labelled, and no other name is."""

    policy = manifest.get("missing_glyph_policy")
    if not isinstance(policy, dict) or not policy.get("glyphs") or not policy.get("label_mark"):
        raise SystemExit("place catalog manifest records no missing-glyph policy")
    mark = policy["label_mark"]
    has_glyph = " OR ".join(
        "instr(name, ?) > 0 OR instr(coalesce(name_zh, ''), ?) > 0" for _glyph in policy["glyphs"]
    )
    glyph_params = [glyph for glyph in policy["glyphs"] for _field in (0, 1)]
    (unmarked,) = connection.execute(
        f"SELECT COUNT(*) FROM places WHERE ({has_glyph}) AND instr(display_name, ?) = 0",
        (*glyph_params, mark),
    ).fetchone()
    (stray,) = connection.execute(
        f"SELECT COUNT(*) FROM places WHERE NOT ({has_glyph}) AND instr(display_name, ?) > 0",
        (*glyph_params, mark),
    ).fetchone()
    (marked,) = connection.execute(
        "SELECT COUNT(*) FROM places WHERE instr(display_name, ?) > 0", (mark,)
    ).fetchone()
    if unmarked or stray or marked != policy.get("rows_marked"):
        raise SystemExit(
            f"missing-glyph labels disagree: {unmarked} unmarked, {stray} marked without a glyph, "
            f"{marked} marked against {policy.get('rows_marked')} recorded"
        )


TIMEZONE_CHECK_NOT_RUN_REASONS = frozenset({"timezonefinder_not_installed"})


def _check_timezone_check(metadata: dict, manifest: dict) -> str:
    """The recorded timezone/coordinate cross-check outcome, refused unless it is one the producer writes."""

    outcome = manifest.get("timezone_coordinate_check")
    if metadata.get("timezone_coordinate_check") != outcome:
        raise SystemExit("catalogue and manifest disagree on timezone_coordinate_check")
    if not isinstance(outcome, dict):
        raise SystemExit(f"unknown timezone/coordinate check outcome: {outcome!r}")
    status = outcome.get("status")
    if status == "passed":
        engine, rows = outcome.get("engine"), outcome.get("rows_checked")
        if (not isinstance(engine, str) or not engine.strip()
                or rows != manifest.get("row_counts", {}).get("geonames_cities500")):
            raise SystemExit(f"timezone/coordinate check outcome is not a pass over every GeoNames row: {outcome!r}")
        return f"timezone/coordinate cross-check passed ({rows} rows, {engine})"
    if (status == "not_run" and outcome.get("engine") is None
            and outcome.get("reason") in TIMEZONE_CHECK_NOT_RUN_REASONS):
        audit = outcome.get("offline_audit")
        if isinstance(audit, dict):
            return (f"timezone/coordinate cross-check NOT RUN ({outcome['reason']}) at build; the build applied "
                    f"the offline audit table ({audit.get('engine')}: {audit.get('corrections')} corrections, "
                    f"{audit.get('left_as_source')} rows left as the source has them)")
        return (f"timezone/coordinate cross-check NOT RUN ({outcome['reason']}): no GeoNames zone was "
                "compared with its coordinate when this catalogue was built")
    raise SystemExit(f"unknown timezone/coordinate check outcome: {outcome!r}")


def verify(*, installed_image: bool = False) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    catalog = manifest.get("catalog")
    if not isinstance(catalog, dict):
        raise SystemExit("place catalog identity is missing")
    filename = catalog.get("filename")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise SystemExit("place catalog filename is unsafe")
    catalog_path = DATA_DIR / filename
    if not catalog_path.is_file():
        raise SystemExit(f"missing place catalog: {catalog_path}")
    if catalog_path.stat().st_size != catalog.get("size_bytes"):
        raise SystemExit("place catalog size does not match manifest")
    if _sha256(catalog_path) != catalog.get("sha256"):
        raise SystemExit("place catalog SHA-256 does not match manifest")
    for suffix in ("-journal", "-wal", "-shm"):
        if Path(f"{catalog_path}{suffix}").exists():
            raise SystemExit(f"mutable SQLite sidecar exists: {catalog_path}{suffix}")
    if not installed_image:
        _check_producer_freshness(manifest)

    connection = sqlite3.connect(
        f"{catalog_path.resolve().as_uri()}?mode=ro&immutable=1",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("place catalog SQLite integrity_check failed")
        metadata = {
            row["key"]: json.loads(row["value_json"])
            for row in connection.execute("SELECT key, value_json FROM catalog_metadata")
        }
        for key in (
            "schema_version", "generator_version", "source_corrections_table_sha256",
            "source_admin1_corrections_table_sha256",
        ):
            if metadata.get(key) != manifest.get(key):
                raise SystemExit(f"catalogue and manifest disagree on {key}")
        counts = {
            row["source"]: row["count"]
            for row in connection.execute(
                """
                SELECT
                    CASE
                        WHEN source = 'geonames_cities500'
                            THEN 'geonames_cities500'
                        WHEN source_record_id LIKE 'tw-moi-administrative:%'
                            THEN 'taiwan_moi_administrative'
                        WHEN source_record_id LIKE 'tw-moi-settlement:%'
                            THEN 'taiwan_moi_settlement'
                        WHEN source_record_id LIKE 'tw-moi-county-derived:%'
                            THEN 'taiwan_moi_county_representative'
                        WHEN source_record_id LIKE 'tw-moi-town-derived:%'
                            THEN 'taiwan_moi_town_representative'
                    END AS source,
                    COUNT(*) AS count
                FROM places
                GROUP BY 1
                """
            )
        }
        # A kind the inputs yield no row of (a test catalogue without townships) has no row to count.
        if counts != {kind: count for kind, count in manifest["row_counts"].items() if count}:
            raise SystemExit(
                f"place catalog row counts differ: {counts!r}"
            )
        if metadata.get("runtime_outbound") is not False:
            raise SystemExit("place catalog claims runtime outbound")
        timezone_check = _check_timezone_check(metadata, manifest)
        corrected_rows = _check_corrections(connection, manifest)
        admin1_rows = _check_admin1_corrections(connection, manifest)
        _check_exclusions(connection, manifest)
        _check_chinese_name_exclusions(connection, manifest)
        folded_characters = _check_han_script_folding(connection, manifest)
        _check_taiwan_counties(
            connection, None if installed_image else len(_load_producer().TAIWAN_COUNTY_CODES)
        )
        _check_missing_glyph_marks(connection, manifest)
        taiwan_hit = connection.execute(
            """
            SELECT p.source
            FROM place_search
            JOIN places AS p ON p.rowid = place_search.rowid
            WHERE place_search MATCH '"臺南"*'
              AND p.country_code = 'TW'
            ORDER BY p.source_priority ASC
            LIMIT 1
            """
        ).fetchone()
        if taiwan_hit is None or taiwan_hit["source"] != (
            "taiwan_moi_place_names"
        ):
            raise SystemExit("Taiwan overlay priority canary failed")
    finally:
        connection.close()

    print(
        f"PLACE CATALOG VERIFIED ({corrected_rows} corrected rows and "
        f"{admin1_rows} admin1-corrected rows read back; {folded_characters} folding characters "
        f"checked against the MOI names; {timezone_check})"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument(
        "--installed-image",
        action="store_true",
        help="the container image: no producer is shipped, so skip the producer freshness binding",
    )
    args = parser.parse_args()
    verify(installed_image=args.installed_image)


if __name__ == "__main__":
    main()
