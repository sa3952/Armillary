# Offline place catalog

`places.sqlite3`is an immutable generated runtime catalog：GeoNames`cities500`provides the global
base and Taiwan Ministry of the Interior data provides a higher-priority overlay. Deterministic
ranking (v3) orders by match tier, then Taiwan county representative points, then population; the tier
compares each row's stored `match_keys` (name, Traditional-Chinese name, a county's short name and the
English names its MOI phonetics and GeoNames `admin2Codes` give, keyed by MOI CountyCode in the producer's
`TAIWAN_COUNTY_CODES`, and a Taiwan GeoNames row's Chinese-script aliases), with 台 read as 臺. Both`臺／台`forms are indexed. For every top-level Taiwan county/city, the
producer derives one picker-only administrative representative point from the
coordinate-bearing MOI child records. It is explicitly not a city hall,
geometric centroid, address, or asserted birth location.

The application opens SQLite with`mode=ro&immutable=1`. `POST /api/places/search`is same-origin and
makes no outbound request；the catalog stores no query、birth data、account or runtime cache. Results
retain source record、representative coordinates、timezone and precision so users can correct them；
representative points are not verified addresses.

**Reproducing the bundled catalogue.** `catalog_manifest.json` records each input's SHA-256
(`source_sha256`), size and URL (`sources`). GeoNames replaces its dump files under the same unversioned names
daily, so the URLs do not serve the hashed bytes for long; the exact input files of the current catalogue are
kept outside the repository beside its review record, and only those bytes reproduce it. A command run on
fresh downloads produces a **new** catalogue (new input hashes, new release unit).

`scripts/verification/verify_place_catalog.py --check` verifies identity, integrity, row counts and the Taiwan
priority canary, reads every row named in `source_corrections` back from the database and requires its
corrected value, and binds the artifact to the producer: the manifest's `generator_version` and
`source_corrections_table_sha256` must equal the producer's current `GENERATOR_VERSION` and correction table,
so a correction added without a rebuild fails. The container image ships no producer and runs it with
`--installed-image`, which keeps the row checks and skips only that binding.

Producing a catalogue from pinned snapshots：

```bash
python -m scripts.validation.build_place_catalog \
  --geonames-zip /path/to/cities500.zip \
  --geonames-admin1-codes /path/to/admin1CodesASCII.txt \
  --geonames-admin2-codes /path/to/admin2Codes.txt \
  --geonames-alternate-names /path/to/alternateNamesV2.zip \
  --taiwan-admin-csv /path/to/taiwan-admin.csv \
  --taiwan-settlement-csv /path/to/taiwan-settlement.csv \
  --output backend/place_data/places.sqlite3 \
  --manifest backend/place_data/catalog_manifest.json \
  --source-date YYYY-MM-DD
```

**Rebuilding the shipped catalogue exactly.** `input_archive.json` lists the six inputs of the current
catalogue: upstream URL, retrieval date (2026-10-09), licence, SHA-256, and where a copy can be
found. The files are not in this tree, and the upstream URLs no longer serve these bytes (see the list's
`upstream_note`); a copy is usable only if its SHA-256 equals the list. With the six files in `inputs/`:

```bash
sha256sum inputs/*          # each must equal input_archive.json
python -m scripts.validation.build_place_catalog \
  --geonames-zip inputs/cities500.zip \
  --geonames-admin1-codes inputs/admin1CodesASCII.txt \
  --geonames-admin2-codes inputs/admin2Codes.txt \
  --geonames-alternate-names inputs/alternateNamesV2.zip \
  --taiwan-admin-csv inputs/taiwan-admin.csv \
  --taiwan-settlement-csv inputs/taiwan-settlement.csv \
  --output backend/place_data/places.sqlite3 \
  --manifest backend/place_data/catalog_manifest.json \
  --source-date 2026-10-09
python scripts/verification/verify_place_catalog.py --check
```

Expected: `places.sqlite3` SHA-256 `a977c5774acb75d5f92ecc09db7bdd4241be3cd7c1af4c98cdc955b918da2f72` (90791936 bytes), and
`catalog_manifest.json` unchanged (`git diff --exit-code backend/place_data/`). Input digests:

| input | sha256 |
|---|---|
| `geonames_admin1_codes` | `1da92a6323a5fec3176f3f743bf4cf4040fd56a876da55e46fbca23c863aa60a` |
| `geonames_admin2_codes` | `2fbfc577d4d3f7d2db4a5aef851631521c89d3cbbeb5c33bf658054ee05b5af0` |
| `geonames_alternate_names` | `5e61abd63b30bff4f0b34cb562f850c15ecafbbf9f52c3d56a92e28fb8f47d1b` |
| `geonames_cities500` | `4022ba76d34abbcd7c7b32597a6f968f51edfa4fb262bf04f15c109624ae3db2` |
| `taiwan_moi_administrative` | `b9aaca5b04bd19c622a675354d2f5c1b67a5c7d7409263bc1e379191beffdb39` |
| `taiwan_moi_settlement` | `e1e72eb17fb26852860f4d5dc5f0ca99200bdd8a65b37bc0bd523efbd0fa66a5` |

Catalog、manifest、hashes、row counts、notices、Docker context and publication candidate change as one
reviewed release unit. Source identity and licenses come from the manifest and distributed notices.

`place-catalog-builder-v8` (2026-10-11, still schema 5) corrects GeoNames rows whose admin1 code names a
province the row is nowhere near (the label read "Baiyanghe, Heilongjiang, CN" for a Xinjiang township):
`SOURCE_ADMIN1_CORRECTIONS` names the Chinese rows found so far, each applied only while the source still carries the
expected code and recorded under `source_admin1_corrections` with its own table digest, which the verifier
binds and reads back row by row like the zone corrections. `tests/backend/test_place_catalog.py` checks every
shipped Chinese row against its province's published extent.
The table also names rows outside China, each checked in the same test file against the place's own
administrative statement (Wikidata or the PhilAtlas gazetteer); a row whose region is right but whose coordinates
belong to another place is not relabelled.

Schema 5 (`place-catalog-builder-v7`, 2026-10-10) adds the `match_keys` column; the runtime serves
schema 5 only. The v7 producer also rejects MOI rows the publisher left in while testing
(`upstream_test_row`), appends 「（原始資料缺字）」 to the label of a name whose source wrote a lost
character as `?` or `●` (`missing_glyph_policy`), labels Taiwan GeoNames rows with the county their
admin2 code names instead of GeoNames' pre-1998 province (`display_name_policy.taiwan_admin1`), and
leaves out named duplicate source rows through `SOURCE_ROW_EXCLUSIONS` (`source_exclusions`, bound
like the corrections); the same table also leaves out a row whose coordinates are another place's, with
no row kept in its place. Schema 4 producer (`place-catalog-builder-v4` from 2026-09-14): rows with a blank
or non-word name are rejected and counted in the manifest (`rejected_rows`);
rows sharing one `display_name` receive a `disambiguator` (MOI village first,
then a resolved GeoNames admin2 name, then a rounded coordinate as last
resort; the level used is recorded); the admin1 code is resolved to a name
through `admin1CodesASCII.txt` or omitted from the label, never shown raw; a
Traditional-Chinese name from `alternateNamesV2` leads the label when available
(`zh-Hant`, then `zh-TW`; untagged `zh`, mostly Simplified, is not used); every timezone must be an IANA zone; rows whose GeoNames timezone is a source
error (the two Auckland suburbs tagged `Pacific/Chatham`, and others found by
checking each zone against its country's IANA `zone.tab` entries and against
the zone of its nearest same-country neighbours) are corrected through the
producer's `SOURCE_TIMEZONE_CORRECTIONS` and recorded under `source_corrections`
(Vietnamese rows take the zone of their side of the 1954-1976 Bến Hải line, as tzdata's
`zone1970.tab` assigns them: Asia/Bangkok north, Asia/Ho_Chi_Minh south, one hour apart from
1960 to mid-1975);
rows on real or disputed boundaries are left as the source has them and listed
as reviewed cases in `tests/backend/test_place_catalog.py`;
when `timezonefinder` is installed every GeoNames timezone is checked against
its coordinate and a mismatch fails the build; without it the check does not run
and the manifest says so (`timezone_coordinate_check.status` `not_run`,
`timezonefinder_not_installed`), which is how the bundled catalogue was built:
its timezones were not checked against their coordinates this way;
each input is hashed through the descriptor it was read from. The runtime
refuses any schema it does not serve and reports the SHA-256 of the file it opened in every
search receipt (`catalog.artifact`). GeoNames `admin3` is a bare code with no
declared name table, so GeoNames rows leave `admin3` null and it is never a
disambiguator. The bundled catalogue is built with all six inputs; its schema,
its generator, snapshot date and counts are in `catalog_manifest.json`.
