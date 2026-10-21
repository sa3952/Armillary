"""Read-only bundled place catalog; no runtime geocoder or third-party request."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
import unicodedata
from collections.abc import Callable
from typing import Any, Final

from .hong_kong_place_aliases import (
    ALIAS_SOURCE,
    ALIAS_TABLE_NAME,
    ALIAS_TIER,
    ALIASES_SHARED_WITH_TAIWAN,
    HONG_KONG_ALIASES,
    alias_key,
)
from .civil_time_basis import (
    CIVIL_TIME_BASIS_ZONES,
    check_civil_time_basis,
    civil_time_basis_choices,
    is_dual_civil_time_place,
)


DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parents[2]
    / "place_data"
    / "places.sqlite3"
)

# A single-character FTS5 prefix term matches a large fraction of a
# 200k-row catalog, and cost grows with the number of such terms: one
# 1-char prefix term measured ~260 ms while 50 of them measured ~3.7 s,
# against a 1.0-CPU container.  Request-count rate limiting cannot bound
# that, because a realistic term ("taipei") measured ~7 ms — a ~400x
# spread.  Two deterministic bounds are applied before the query runs.
MAX_SEARCH_TOKENS = 6
MIN_PREFIX_TOKEN_LENGTH = 2

# Catalogue schema versions the runtime can serve.  Schema 4 added the identity
# columns (admin1_name, admin3, name_zh, disambiguator) every result returns;
# schema 5 adds ``match_keys``, the names the match tier compares.  An older
# file would answer them with null or classify every row as other_field, so it
# is refused.
SUPPORTED_SCHEMA_VERSIONS = frozenset({5})


# Producer-assigned record-id prefix of the derived county representative points.
TAIWAN_COUNTY_RECORD_PREFIX = "tw-moi-county-derived:"

# FTS5 bm25() 欄位權重（name、aliases、admin1、admin2）。`place_search` 是 contentless FTS5 表，
# bm25 只看索引且偏好較短的文件；GeoNames 給倫敦數百個語言變體別名，使 London(GB) 的分數
# 反而比美國同名小鎮差。提高 name 欄權重，讓「命中地名本身」而非「別名寫得少」主導相關度。
BM25_COLUMN_WEIGHTS = (8.0, 2.0, 1.0, 1.0)

# 排序法的具名版本。排序規則的變更會直接改變使用者選到哪一個地點、
# 進而改變整張星盤，因此必須是可具名、可比對、可回報的。
RANKING_METHOD_NAME = "match_tier_then_taiwan_county_then_population_then_weighted_bm25_v3"
_BM25_SQL = ", ".join(str(value) for value in BM25_COLUMN_WEIGHTS)
RANKING_STEPS = (
    (
        "CASE match_tier WHEN 'exact_name' THEN 0 "
        "WHEN 'name_prefix' THEN 1 ELSE 2 END ASC",
        "1. match_tier (exact_name → 0, name_prefix → 1, other_field and spelling_fallback → 2) ASC; "
        "the tier compares the name, the Traditional-Chinese name, a Taiwan county's "
        "short and English names and a Taiwan GeoNames row's Chinese aliases, with 台 read as 臺",
    ),
    (
        f"CASE WHEN substr(source_record_id, 1, {len(TAIWAN_COUNTY_RECORD_PREFIX)}) "
        f"= '{TAIWAN_COUNTY_RECORD_PREFIX}' THEN 0 ELSE 1 END ASC",
        "2. is_taiwan_county_representative (→ 0, otherwise → 1) ASC",
    ),
    (
        "population DESC",
        "3. population DESC (0 means the source gives none; it sorts after every known population)",
    ),
    (
        "bm25_rank ASC",
        f"4. bm25(name×{BM25_COLUMN_WEIGHTS[0]}, "
        f"aliases×{BM25_COLUMN_WEIGHTS[1]}, admin1×{BM25_COLUMN_WEIGHTS[2]}, "
        f"admin2×{BM25_COLUMN_WEIGHTS[3]}) ASC",
    ),
    ("source_priority ASC", "5. source_priority ASC"),
    ("display_name ASC", "6. display_name ASC"),
)
_ORDER_BY_SQL = ",\n                    ".join(
    sql for sql, _description in RANKING_STEPS
)
# Backstop for a query shape the token bounds do not anticipate.  SQLite
# has no statement timeout; the connection `timeout` argument bounds lock
# acquisition only.  A progress handler is the one mechanism that can
# abort an already-running statement.
SEARCH_STATEMENT_BUDGET_SECONDS = 2.0
_PROGRESS_HANDLER_INSTRUCTION_INTERVAL = 10_000

# Spelling fallback.  A search that found nothing is retried, inside the same
# budget, against the names the match tier compares (each row's match_keys):
# rows with a name within Levenshtein distance SPELLING_FALLBACK_MAX_DISTANCE of
# the query are returned, ordered by the unchanged ranking, each with match_tier
# "spelling_fallback".  Only a query of Latin letters (spaces allowed) with at
# least SPELLING_FALLBACK_MIN_LETTERS letters is retried: shorter words sit
# within two edits of too many names to mean anything.
SPELLING_FALLBACK_MAX_DISTANCE = 2
SPELLING_FALLBACK_MIN_LETTERS = 5
SPELLING_FALLBACK_TIER = "spelling_fallback"
# Closed: whether the fallback ran and what it found.
SPELLING_FALLBACK_NOT_NEEDED = "not_needed"
SPELLING_FALLBACK_NOT_ELIGIBLE = "not_eligible"
SPELLING_FALLBACK_NO_NAME = "no_name_within_distance"
SPELLING_FALLBACK_APPLIED = "applied"
# How often the name scan, which runs in Python and not under the progress
# handler, looks at the clock.
_SPELLING_SCAN_CLOCK_INTERVAL = 4096


# How every search ran: the bundled read-only catalog, no network.
_EXECUTION_RECEIPT = {"catalog_mode": "bundled_read_only_sqlite", "runtime_outbound": False}


def _ranking_receipt() -> dict:
    return {
        "method": RANKING_METHOD_NAME,
        # 必須與 ORDER BY 逐項對應（同一個 RANKING_STEPS 產生兩者）；自述錯誤等於
        # 可追溯性宣稱不實。
        "order": [description for _sql, description in RANKING_STEPS],
        "why_the_tier_precedes_population": (
            "比對層級比對地名、繁體中文名、臺灣縣市的簡稱與英文名，以及臺灣 GeoNames "
            "城市的中文別名，並把「台」視同「臺」；所以「臺北」「Taipei」對臺北市都是 "
            "exact_name，層級排在人口之前也不會讓人口 0 的『臺北小別墅』（name_prefix）"
            "壓過臺北市。同層之內臺灣縣市代表點優先，所以 Penghu、Nantou 不會先給同名的"
            "中國地點。"
        ),
        "curated_alias": (
            f"{ALIAS_TABLE_NAME}: a curated Chinese name of a Hong Kong district or place "
            "(灣仔、將軍澳、北區…) adds that catalogue row with match_tier curated_alias, "
            "outside the ORDER BY: second when the query does not begin with 香港 and the "
            "ranked first answer lies outside Hong Kong and matches by its own name "
            "(exact_name or name_prefix) or the alias is 北區、南區、東區 or 中西區, "
            "which Taiwanese cities also have; first otherwise; "
            "query.curated_alias says whether and where; a query beginning with 香港, "
            "香港特區, hong kong or hk whose rest is no curated name and whose whole "
            "text finds nothing is searched again as the rest alone, Hong Kong rows "
            "first (query.curated_alias.prefix_stripped)"
        ),
        "population_semantics": (
            "zero_means_the_source_gives_no_population_and_sorts_after_every_known_population"
        ),
    }


class PlaceCatalogUnavailableError(RuntimeError):
    code = "place_catalog_unavailable"


class PlaceSearchBudgetExceededError(RuntimeError):
    """The statement budget interrupted a search; the catalogue itself is fine.

    SQLite reports a progress-handler interrupt as the same `sqlite3.Error` a
    missing or corrupt file raises; this keeps them apart, because retrying or
    narrowing the query is the remedy, and "catalogue unavailable" carries no
    Retry-After.
    """

    code = "place_search_timeout"


def normalize_search_text(value: str) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", value).casefold().split()
    )


def _word_tokens(value: str) -> list[str]:
    r"""Return Unicode words without splitting casefold-introduced marks.

    Python ``\w`` excludes combining marks.  That made U+0130 casefold to
    ``i`` + COMBINING DOT ABOVE and then split ``İstanbul`` into two MATCH
    terms.  FTS5's unicode61 tokenizer treats marks as part of the word and
    removes the diacritic, so mirror that boundary while still discarding all
    FTS syntax characters before quoting terms.
    """

    normalized = normalize_search_text(value)
    # unicode61 keeps only letters, marks and numbers as token characters; "_"
    # (Pc) must separate here too, or "a_b" passes the prefix-length guard as
    # one token while FTS5 runs two one-character prefix scans.
    token_text = "".join(
        character
        if unicodedata.category(character)[0] in {"L", "M", "N"}
        else " "
        for character in normalized
    )
    return token_text.split()


def place_name_match_key(value: str) -> str:
    """Return the punctuation/diacritic-insensitive key used for result tiers.

    FTS5 ``unicode61 remove_diacritics 2`` treats punctuation as word
    boundaries and removes combining marks.  Tier classification must mirror
    those semantics on both the stored name and the bounded query; otherwise a
    successful MATCH can be mislabeled as ``other_field``.
    """

    decomposed = unicodedata.normalize("NFD", normalize_search_text(value))
    without_marks = "".join(
        character
        for character in decomposed
        if unicodedata.category(character)[0] != "M"
    )
    return " ".join(_word_tokens(without_marks))


def place_tier_key(value: str) -> str:
    """Match key with 台 read as 臺, compared on both the stored names and the query.

    The producer indexes both spellings for FTS; the tier must fold them too,
    or 「臺東」 is a name match for 臺東縣 while 「台東」 is only other_field.
    """

    return place_name_match_key(value).replace("台", "臺")


# Separator of the stored ``match_keys``; it cannot occur in a match key,
# which holds only letters, marks, numbers and single spaces.
MATCH_KEY_SEPARATOR = "\x1f"


def match_keys_text(names) -> str:
    """Store a row's tier keys as one delimited string the SQL tier reads with instr()."""

    keys = sorted({key for key in (place_tier_key(name) for name in names if name) if key})
    return MATCH_KEY_SEPARATOR + MATCH_KEY_SEPARATOR.join(keys) + MATCH_KEY_SEPARATOR


def county_prefixes(county_names) -> tuple[str, ...]:
    """Full and short (without 縣／市) county names, 台 read as 臺, longest first.

    The names come from the catalogue's own derived county points, so the
    runtime holds no list of its own that could drift from the data.
    """

    folded = {
        name.replace("台", "臺")
        for county in county_names
        for name in (county, county[:-1])
        if name
    }
    return tuple(sorted(folded, key=lambda name: (-len(name), name)))


def _county_prefix_split(token: str, prefixes: tuple[str, ...]) -> tuple[str, str] | None:
    """Split 「臺北市大安區」 into 「臺北市」 and 「大安區」.

    FTS5 unicode61 keeps a run of Han characters as one token, and labels are
    indexed as 「大安區, 臺北市」, so the unsplit word matches nothing.  Only a
    remainder of two or more characters is split off, so it stays a prefix term.
    """

    folded = token.replace("台", "臺")
    for prefix in prefixes:
        if folded.startswith(prefix) and len(token) - len(prefix) >= MIN_PREFIX_TOKEN_LENGTH:
            return token[: len(prefix)], token[len(prefix):]
    return None


# FTS5 unicode61 keeps these combining marks inside a word and removes them
# (``sqlite3Fts5UnicodeIsdiacritic``, the U+0300-U+0331 set); every other mark
# ends the word.  Probed against the running SQLite by
# tests/backend/test_place_catalog.py.
_FTS5_DIACRITICS = frozenset(
    chr(code)
    for code in (
        *range(0x0300, 0x0305), *range(0x0306, 0x030D), 0x030F, 0x0311,
        0x031B, *range(0x0323, 0x0329), 0x032D, 0x032E, 0x0330, 0x0331,
    )
)


def _fts_sub_tokens(word: str) -> list[str]:
    """Split one word where FTS5 unicode61 splits it.

    ``_word_tokens`` keeps every mark inside a word, but FTS5 ends a word at
    any mark outside its diacritic set (Thai U+0E31, Devanagari U+093E).  A
    leading diacritic starts no word, as in FTS5.
    """

    sub_tokens: list[str] = []
    current: list[str] = []
    for character in word:
        if character in _FTS5_DIACRITICS:
            if current:
                current.append(character)
        elif unicodedata.category(character)[0] in {"L", "N"}:
            current.append(character)
        elif current:
            sub_tokens.append("".join(current))
            current = []
    if current:
        sub_tokens.append("".join(current))
    return sub_tokens


def _fts_prefix_length(sub_token: str) -> int:
    """Characters FTS5 is sure to keep at the end of the word a ``*`` expands.

    Diacritics are removed by FTS5 and do not count.  The count stops at a
    letter or number whose category changed since Unicode 3.2: SQLite's tables
    are older than Python's, and a few such letters (New Tai Lue vowel signs,
    U+19B0) are still marks, and so separators, to FTS5.  Stopping there can
    only withhold a prefix, never let FTS5 run a shorter one.
    """

    length = 0
    for character in reversed(sub_token):
        if character in _FTS5_DIACRITICS:
            continue
        if unicodedata.ucd_3_2_0.category(character)[0] not in {"L", "N"}:
            break
        length += 1
    return length


def _fts_query(value: str, prefixes: tuple[str, ...] = ()) -> tuple[str, dict]:
    """Build a bounded FTS5 MATCH expression, and report what the bound removed.

    Tokenisation keeps only word characters, so no FTS5 metacharacter can
    reach the expression.  Bounding happens here rather than at the HTTP
    boundary because the cost lives in prefix-term breadth, not in the
    length of the submitted string.

    The token bound is not applied silently.  For a place picker that would be
    a correctness problem, not merely a UX one: a query whose distinguishing
    word sits past the limit is answered as though that word had never been
    typed, and the user may accept a coordinate for somewhere else entirely.
    The bound is kept - it is a real cost control - and the caller receives the
    dropped tokens so the response can say so.
    """

    tokens = _word_tokens(value)
    bounded = tokens[:MAX_SEARCH_TOKENS]
    dropped = tokens[MAX_SEARCH_TOKENS:]
    terms = []
    county_splits: list[list[str]] = []
    for token in bounded:
        term = _fts_term(token)
        if term is None:
            continue
        split = _county_prefix_split(token, prefixes)
        split_terms = [_fts_term(part) for part in split] if split else []
        if split and all(split_terms):
            # The word itself stays an alternative, so a name that merely
            # begins with a county name (高雄市政府) is still found.
            terms.append(f"({term} OR ({' '.join(str(item) for item in split_terms)}))")
            county_splits.append(list(split))
        else:
            terms.append(term)
    receipt = {
        # Closed: "searched" ran a MATCH; "no_searchable_tokens" had nothing
        # to match (only punctuation or marks), which is not "no place found".
        "status": "searched" if terms else "no_searchable_tokens",
        "token_count": len(tokens),
        "max_search_tokens": MAX_SEARCH_TOKENS,
        "truncated": bool(dropped),
        "tokens_used": bounded,
        "tokens_ignored": dropped,
        # Words that began with a county name and were also searched as
        # [county, remainder]; the tier still compares the words as typed.
        "county_prefix_splits": county_splits,
        "reason": (
            "token_limit_protects_against_broad_prefix_term_cost"
            if dropped
            else None
        ),
    }
    return " ".join(terms), receipt


def _fts_term(token: str) -> str | None:
    """One quoted FTS5 term for a word; a prefix star only when it is long enough.

    Short tokens stay exact.  A 1-character prefix term is the single largest
    cost multiplier and is almost never the user's intent.  Emit and measure
    what FTS5 will see: a word it splits becomes a phrase of its sub-tokens,
    and only the last one - the one a trailing "*" expands - decides the
    prefix.  A word with no sub-token (marks only) is an empty phrase, which
    FTS5 ignores; it is left out.
    """

    sub_tokens = _fts_sub_tokens(token)
    if not sub_tokens:
        return None
    phrase = " ".join(sub_tokens)
    if _fts_prefix_length(sub_tokens[-1]) >= MIN_PREFIX_TOKEN_LENGTH:
        return f'"{phrase}"*'
    return f'"{phrase}"'


_COUNTY_PREFIX_LOCK = threading.Lock()
_COUNTY_PREFIX_CACHE: dict[tuple[str, int, int], tuple[str, ...]] = {}
_ARTIFACT_DIGEST_LOCK = threading.Lock()
_ARTIFACT_DIGEST_CACHE: dict[tuple[str, int, int], str] = {}
_METADATA_LOCK = threading.Lock()
_METADATA_CACHE: dict[tuple[str, int, int], dict[str, str]] = {}

# The two per-row correction tables are about 100 KB of the catalogue metadata
# and the same for every search, so a typed query carried six times the bytes
# of its results.  The search receipt keeps each table's `*_table_sha256`; the
# rows are in the published catalogue manifest, which the catalogue verifier
# (scripts/verification/verify_place_catalog.py) requires to equal the
# database's own copy.
SEARCH_RECEIPT_OMITTED_METADATA = ("source_admin1_corrections", "source_corrections")
SEARCH_RECEIPT_ROW_LISTS_SOURCE = "backend/place_data/catalog_manifest.json"


def _artifact_digest(path: Path) -> dict:
    """SHA-256 of the catalogue file the runtime opens, cached per (path, size, mtime).

    Metadata digests describe the inputs, not the artifact loaded; this lets a
    coordinate be traced to bytes as the engine manifest traces ephemeris files.
    """

    resolved = path.resolve()
    status = resolved.stat()
    key = (str(resolved), status.st_size, status.st_mtime_ns)
    with _ARTIFACT_DIGEST_LOCK:
        digest = _ARTIFACT_DIGEST_CACHE.get(key)
    if digest is None:
        with resolved.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        with _ARTIFACT_DIGEST_LOCK:
            _ARTIFACT_DIGEST_CACHE.clear()
            _ARTIFACT_DIGEST_CACHE[key] = digest
    return {
        "filename": resolved.name,
        "sha256": digest,
        "size_bytes": status.st_size,
        "digest_basis": "sha256_of_the_file_opened_at_runtime",
    }


def _spelling_fallback_receipt(status: str) -> dict:
    return {
        "status": status,
        "edit_distance": "levenshtein",
        "max_edit_distance": SPELLING_FALLBACK_MAX_DISTANCE,
        "min_latin_letters": SPELLING_FALLBACK_MIN_LETTERS,
    }


# Not memoized: the characters come from the typed place query.
def _is_latin_letter(character: str) -> bool:
    return unicodedata.category(character)[0] == "L" and unicodedata.name(character, "").startswith("LATIN ")


def _latin_name_key(key: str) -> bool:
    letters = key.replace(" ", "")
    if key.isascii():
        return letters.isalpha()
    return bool(letters) and all(_is_latin_letter(character) for character in letters)


def _spelling_fallback_eligible(key: str) -> bool:
    return len(key.replace(" ", "")) >= SPELLING_FALLBACK_MIN_LETTERS and _latin_name_key(key)


_SPELLING_VOCABULARY_LOCK = threading.Lock()
_SPELLING_VOCABULARY_CACHE: dict[tuple[str, int, int], dict[int, str]] = {}


def _spelling_vocabulary(path: Path) -> dict[int, str]:
    """The catalogue's Latin match keys, per key length, read once per file identity.

    Each length's keys are sorted and packed into one string of fixed-width
    slots, which holds about 200,000 names in a few megabytes instead of one
    Python object per name.  The read (about half a second of CPU) runs on its
    own connection, outside a search's progress handler: a search that runs
    out of budget while it is read still leaves it for the next one, and the
    search itself checks its deadline before and during the scan.
    """

    resolved = path.resolve()
    status = resolved.stat()
    identity = (str(resolved), status.st_size, status.st_mtime_ns)
    with _SPELLING_VOCABULARY_LOCK:
        cached = _SPELLING_VOCABULARY_CACHE.get(identity)
        if cached is not None:
            return cached
        keys: set[str] = set()
        connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro&immutable=1", uri=True, timeout=1.0)
        try:
            for (stored,) in connection.execute("SELECT match_keys FROM places"):
                for key in stored.split(MATCH_KEY_SEPARATOR):
                    if key and key not in keys and _latin_name_key(key):
                        keys.add(key)
        finally:
            connection.close()
        by_length: dict[int, list[str]] = {}
        for key in keys:
            by_length.setdefault(len(key), []).append(key)
        packed = {length: "".join(sorted(group)) for length, group in by_length.items()}
        _SPELLING_VOCABULARY_CACHE.clear()
        _SPELLING_VOCABULARY_CACHE[identity] = packed
        return packed


def _within_edit_distance(left: str, right: str, limit: int) -> bool:
    """Levenshtein distance of left and right is at most limit (a band of width 2·limit+1)."""

    if abs(len(left) - len(right)) > limit:
        return False
    beyond = limit + 1
    previous = list(range(len(right) + 1))
    for row in range(1, len(left) + 1):
        character = left[row - 1]
        current = [beyond] * (len(right) + 1)
        low = max(1, row - limit)
        high = min(len(right), row + limit)
        if low == 1:
            current[0] = row
        best = current[0]
        for column in range(low, high + 1):
            value = previous[column - 1] + (character != right[column - 1])
            if previous[column] + 1 < value:
                value = previous[column] + 1
            if current[column - 1] + 1 < value:
                value = current[column - 1] + 1
            current[column] = value
            if value < best:
                best = value
        if best > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _names_within_edit_distance(vocabulary: dict[int, str], key: str, *, deadline: float) -> list[str]:
    """Every vocabulary key within SPELLING_FALLBACK_MAX_DISTANCE of key, sorted.

    A key k edits away from the query changes its set of characters by at most
    2·k (a substitution drops one character and adds one), so the cheap set test
    discards most names before the edit distance is computed.
    """

    limit = SPELLING_FALLBACK_MAX_DISTANCE
    characters = set(key)
    found: list[str] = []
    seen = 0
    for length in range(max(1, len(key) - limit), len(key) + limit + 1):
        packed = vocabulary.get(length, "")
        for start in range(0, len(packed), length):
            seen += 1
            if seen % _SPELLING_SCAN_CLOCK_INTERVAL == 0 and time.monotonic() > deadline:
                raise PlaceSearchBudgetExceededError("place search exceeded its statement budget")
            name = packed[start:start + length]
            if len(characters.symmetric_difference(name)) <= 2 * limit and _within_edit_distance(key, name, limit):
                found.append(name)
    if time.monotonic() > deadline:
        raise PlaceSearchBudgetExceededError("place search exceeded its statement budget")
    return sorted(found)


def _search_sql(*, spelling_fallback: bool) -> str:
    """The search statement; the fallback differs only in which rows it keeps and their tier."""

    if spelling_fallback:
        keep = (
            "AND EXISTS (SELECT 1 FROM fallback_names AS f "
            "WHERE instr(p.match_keys, :separator || f.name || :separator) > 0)"
        )
        tier = f"'{SPELLING_FALLBACK_TIER}'"
        names = "fallback_names(name) AS MATERIALIZED (SELECT value FROM json_each(:fallback_names)),\n                "
    else:
        keep = ""
        tier = """CASE
                        WHEN instr(match_keys, :exact_key) > 0 THEN 'exact_name'
                        WHEN instr(match_keys, :key_prefix) > 0 THEN 'name_prefix'
                        ELSE 'other_field'
                    END"""
        names = ""
    return f"""
                WITH {names}matched AS MATERIALIZED (
                    SELECT
                        p.source,
                        p.source_record_id,
                        p.name,
                        p.display_name,
                        p.country_code,
                        p.admin1,
                        p.admin2,
                        p.admin1_name,
                        p.admin3,
                        p.name_zh,
                        p.disambiguator,
                        p.latitude,
                        p.longitude,
                        p.timezone,
                        p.location_precision,
                        p.population,
                        p.source_priority,
                        p.match_keys,
                        bm25(place_search, {_BM25_SQL}) AS bm25_rank
                    FROM place_search
                    JOIN places AS p ON p.rowid = place_search.rowid
                    WHERE place_search MATCH :match
                      AND (:country IS NULL OR p.country_code = :country)
                      {keep}
                )
                SELECT
                    *,
                    {tier} AS match_tier
                FROM matched
                ORDER BY
                    {_ORDER_BY_SQL}
                LIMIT :limit
                """


_ALIAS_SQL = """
                SELECT source, source_record_id, name, display_name, country_code, admin1,
                    admin1_name, admin2, admin3, name_zh, disambiguator, latitude, longitude,
                    timezone, location_precision, population, :tier AS match_tier
                FROM places
                WHERE source = :source AND source_record_id = :record AND country_code = 'HK'
                """


def _curated_alias(query: str, country_code: str | None) -> tuple[dict, str | None]:
    """The alias receipt and the record id a curated Hong Kong name points to, if any."""

    key, names_hong_kong = alias_key(normalize_search_text(query))
    record = HONG_KONG_ALIASES.get(key)
    receipt = {
        # Internal: the stripped key, for the prefix fallback; removed before the response.
        "alias_lookup_key": key,
        "table": ALIAS_TABLE_NAME,
        "status": "no_alias",
        "alias": None,
        "names_hong_kong": names_hong_kong,
        "placement": None,
    }
    if record is None:
        return receipt, None
    receipt["alias"] = key
    if country_code not in (None, "HK"):
        receipt["status"] = "not_applicable_country_filter"
        return receipt, None
    return receipt, record


# A query that begins with 香港／香港特區／hong kong／hk, whose rest is no curated
# name and whose whole text finds nothing, is searched again without the prefix,
# Hong Kong rows first.  Closed vocabulary.
PREFIX_STRIPPED_NOT_NAMED = "not_named"
PREFIX_STRIPPED_NOT_NEEDED = "not_needed"
PREFIX_STRIPPED_APPLIED = "applied"
PREFIX_STRIPPED_NO_RESULT = "no_result"


def _prefix_stripped_receipt(status: str, remainder: str | None = None) -> dict:
    searched = status in (PREFIX_STRIPPED_APPLIED, PREFIX_STRIPPED_NO_RESULT)
    return {
        "status": status,
        "remainder": remainder if searched else None,
        "hong_kong_rows_first": searched,
    }


def _place_alias_row(rows: list, alias_row, receipt: dict, limit: int) -> list:
    """Put the alias row first, or second after another place's own name match.

    Second when the query does not name Hong Kong and the ranked first answer
    lies elsewhere and either matches by its own name (灣仔 in Taipei) or the
    alias is a district name Taiwanese cities also use (北區 of Tainan).
    """

    identity = (alias_row["source"], alias_row["source_record_id"])
    others = [row for row in rows if (row["source"], row["source_record_id"]) != identity]
    leader = others[0] if others else None
    yields = (
        not receipt["names_hong_kong"]
        and leader is not None
        and leader["country_code"] != "HK"
        and (
            leader["match_tier"] in ("exact_name", "name_prefix")
            or receipt["alias"] in ALIASES_SHARED_WITH_TAIWAN
        )
    )
    first = not yields
    receipt["status"] = "applied"
    receipt["placement"] = "first" if first else "after_first"
    others.insert(0 if first else 1, alias_row)
    return others[:limit]


_SEARCH_SQL = _search_sql(spelling_fallback=False)
_SPELLING_FALLBACK_SQL = _search_sql(spelling_fallback=True)


# The catalog columns a search result carries, in response order.
# `disambiguator` is set only when another row shares the display_name: the
# producer chose the first human-meaningful level that separates the group (see
# catalog.label_disambiguation).  `match_tier` 讓呼叫端看出是地名本身相符，還是只有別名或
# 行政區欄位相符。
_RESULT_COLUMNS: Final = (
    "source", "source_record_id", "name", "display_name", "country_code", "admin1",
    "admin1_name", "admin2", "admin3", "name_zh", "disambiguator", "latitude", "longitude",
    "timezone", "location_precision", "population", "match_tier",
)


class PlaceCatalog:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None else DEFAULT_CATALOG_PATH

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(
                f"{self.path.resolve().as_uri()}?mode=ro&immutable=1",
                uri=True,
                timeout=1.0,
            )
        except sqlite3.Error as exc:
            raise PlaceCatalogUnavailableError(
                "bundled place catalog is unavailable"
            ) from exc
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    def _metadata_json(self, connection: sqlite3.Connection) -> dict[str, str]:
        """The metadata rows as stored, read once per file identity.

        The catalogue is opened immutable, so its metadata changes only with the
        file.  The cache holds the catalogue's own text, never a request value,
        and each caller decodes a fresh copy.
        """

        resolved = self.path.resolve()
        status = resolved.stat()
        key = (str(resolved), status.st_size, status.st_mtime_ns)
        with _METADATA_LOCK:
            cached = _METADATA_CACHE.get(key)
        if cached is None:
            try:
                rows = connection.execute(
                    "SELECT key, value_json FROM catalog_metadata"
                ).fetchall()
            except sqlite3.Error as exc:
                raise PlaceCatalogUnavailableError(
                    "bundled place catalog metadata is unavailable"
                ) from exc
            cached = {row["key"]: row["value_json"] for row in rows}
            with _METADATA_LOCK:
                _METADATA_CACHE.clear()
                _METADATA_CACHE[key] = cached
        return cached

    def _county_prefixes(self, connection: sqlite3.Connection) -> tuple[str, ...]:
        """County names of the catalogue's derived points, read once per file identity."""

        resolved = self.path.resolve()
        status = resolved.stat()
        key = (str(resolved), status.st_size, status.st_mtime_ns)
        with _COUNTY_PREFIX_LOCK:
            cached = _COUNTY_PREFIX_CACHE.get(key)
        if cached is None:
            names = [
                row[0]
                for row in connection.execute(
                    "SELECT name FROM places WHERE substr(source_record_id, 1, ?) = ?",
                    (len(TAIWAN_COUNTY_RECORD_PREFIX), TAIWAN_COUNTY_RECORD_PREFIX),
                )
            ]
            cached = county_prefixes(names)
            with _COUNTY_PREFIX_LOCK:
                _COUNTY_PREFIX_CACHE.clear()
                _COUNTY_PREFIX_CACHE[key] = cached
        return cached

    def _served_metadata(self, connection: sqlite3.Connection) -> dict:
        """The metadata a search receipt carries, the per-row correction lists left out."""

        stored = self._metadata_json(connection)
        metadata = {
            key: json.loads(value_json)
            for key, value_json in stored.items()
            if key not in SEARCH_RECEIPT_OMITTED_METADATA
        }
        if metadata.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
            raise PlaceCatalogUnavailableError(
                "bundled place catalog schema is unsupported"
            )
        omitted = [key for key in SEARCH_RECEIPT_OMITTED_METADATA if key in stored]
        metadata["omitted_row_lists"] = {
            "keys": omitted,
            "bound_by": [f"{key}_table_sha256" for key in omitted],
            "rows_in": SEARCH_RECEIPT_ROW_LISTS_SOURCE,
        }
        return metadata

    def _response(self, results: list[dict], metadata: dict, query_receipt: dict) -> dict:
        return {
            "results": results,
            "catalog": {
                **metadata,
                "artifact": {
                    **_artifact_digest(self.path),
                    "generator_version": metadata.get("generator_version"),
                },
            },
            "query": query_receipt,
            "ranking": _ranking_receipt(),
            "execution": dict(_EXECUTION_RECEIPT),
        }

    def record(self, source: str, source_record_id: str) -> dict | None:
        """One catalogue row by its UNIQUE ``(source, source_record_id)`` key, or None."""

        connection = self._connect()
        try:
            self._served_metadata(connection)
            row = connection.execute(
                "SELECT display_name, latitude, longitude, timezone, location_precision, "
                "country_code FROM places WHERE source = ? AND source_record_id = ?",
                (source, source_record_id),
            ).fetchone()
        except sqlite3.Error as exc:
            raise PlaceCatalogUnavailableError(
                "bundled place catalog query failed"
            ) from exc
        finally:
            connection.close()
        return None if row is None else dict(row)

    def _remainder_rows(self, connection, remainder: str, country_code: str | None, limit: int) -> list:
        """The ranked rows for the query's rest, Hong Kong rows first (order kept within each)."""

        match_query, receipt = _fts_query(remainder, self._county_prefixes(connection))
        if not match_query:
            return []
        tier_query = place_tier_key(" ".join(receipt["tokens_used"]))
        rows = connection.execute(
            _SEARCH_SQL,
            {
                "match": match_query,
                "country": country_code,
                "exact_key": MATCH_KEY_SEPARATOR + tier_query + MATCH_KEY_SEPARATOR,
                "key_prefix": MATCH_KEY_SEPARATOR + tier_query,
                # Read wider than the limit so Hong Kong rows ranked lower still surface.
                "limit": max(limit, 50),
            },
        ).fetchall()
        rows = sorted(rows, key=lambda row: row["country_code"] != "HK")
        return rows[:limit]

    def search(
        self,
        *,
        query: str,
        country_code: str | None,
        limit: int,
    ) -> dict:
        connection = self._connect()
        deadline = time.monotonic() + SEARCH_STATEMENT_BUDGET_SECONDS
        # Recorded, not inferred from the clock afterwards, which would also
        # label a genuine fault that happened to finish late.
        interrupted = False

        def spend_statement_budget() -> int:
            nonlocal interrupted
            if time.monotonic() > deadline:
                interrupted = True
                return 1
            return 0

        connection.set_progress_handler(
            spend_statement_budget,
            _PROGRESS_HANDLER_INSTRUCTION_INTERVAL,
        )
        try:
            metadata = self._served_metadata(connection)
            match_query, query_receipt = _fts_query(query, self._county_prefixes(connection))
            if not match_query:
                # Nothing reached FTS5: say so in a closed field and keep the
                # response the same shape as a search that found nothing.
                query_receipt["spelling_fallback"] = _spelling_fallback_receipt(SPELLING_FALLBACK_NOT_ELIGIBLE)
                empty_alias = _curated_alias(query, country_code)[0]
                del empty_alias["alias_lookup_key"]
                empty_alias["prefix_stripped"] = _prefix_stripped_receipt(PREFIX_STRIPPED_NOT_NAMED)
                query_receipt["curated_alias"] = empty_alias
                return self._response([], metadata, query_receipt)
            # The tier must describe the same bounded tokens that reached FTS5;
            # the raw string made ``London!!!`` run as ``london`` yet report
            # ``other_field``.
            tier_query = place_tier_key(" ".join(query_receipt["tokens_used"]))
            # SQL reads each row's producer-stored match key; computing it in
            # Python per FTS hit (tens of thousands for a common prefix) made
            # concurrent searches exceed the budget under the GIL.
            rows = connection.execute(
                _SEARCH_SQL,
                {
                    "match": match_query,
                    "country": country_code,
                    # 以 instr 而非 LIKE 比對：查詢字串是使用者輸入，LIKE 會把
                    # 其中的 % 與 _ 當成萬用字元；instr 沒有萬用字元語意。鍵以
                    # 分隔字元包住，所以「整個鍵相等」與「鍵以查詢開頭」可分。
                    "exact_key": MATCH_KEY_SEPARATOR + tier_query + MATCH_KEY_SEPARATOR,
                    "key_prefix": MATCH_KEY_SEPARATOR + tier_query,
                    "limit": limit,
                },
            ).fetchall()
            if rows:
                fallback = SPELLING_FALLBACK_NOT_NEEDED
            elif not _spelling_fallback_eligible(tier_query):
                fallback = SPELLING_FALLBACK_NOT_ELIGIBLE
            else:
                names = _names_within_edit_distance(
                    _spelling_vocabulary(self.path), tier_query, deadline=deadline
                )
                if names:
                    rows = connection.execute(
                        _SPELLING_FALLBACK_SQL,
                        {
                            # Each name as an exact FTS5 phrase; a Latin match
                            # key holds only letters and single spaces.
                            "match": " OR ".join(f'"{name}"' for name in names),
                            "country": country_code,
                            "fallback_names": json.dumps(names, ensure_ascii=False),
                            "separator": MATCH_KEY_SEPARATOR,
                            "limit": limit,
                        },
                    ).fetchall()
                fallback = SPELLING_FALLBACK_APPLIED if rows else SPELLING_FALLBACK_NO_NAME
            query_receipt["spelling_fallback"] = _spelling_fallback_receipt(fallback)
            alias_receipt, alias_record = _curated_alias(query, country_code)
            alias_receipt["prefix_stripped"] = _prefix_stripped_receipt(PREFIX_STRIPPED_NOT_NAMED)
            if alias_receipt["names_hong_kong"] and alias_record is None:
                if rows:
                    status = PREFIX_STRIPPED_NOT_NEEDED
                else:
                    # 「香港赤柱」「hong kong stanley」: the whole query finds nothing and
                    # the rest is no curated name, so search the rest, Hong Kong first.
                    rows = self._remainder_rows(
                        connection, alias_receipt["alias_lookup_key"], country_code, limit
                    )
                    status = PREFIX_STRIPPED_APPLIED if rows else PREFIX_STRIPPED_NO_RESULT
                alias_receipt["prefix_stripped"] = _prefix_stripped_receipt(
                    status, alias_receipt["alias_lookup_key"]
                )
            del alias_receipt["alias_lookup_key"]
            if alias_record is not None:
                alias_row = connection.execute(
                    _ALIAS_SQL,
                    {"tier": ALIAS_TIER, "source": ALIAS_SOURCE, "record": alias_record},
                ).fetchone()
                if alias_row is None:
                    raise PlaceCatalogUnavailableError(
                        "curated place alias points at no catalogue row"
                    )
                rows = _place_alias_row(list(rows), alias_row, alias_receipt, limit)
            query_receipt["curated_alias"] = alias_receipt
        except (sqlite3.Error, PlaceCatalogUnavailableError) as exc:
            if interrupted:
                raise PlaceSearchBudgetExceededError(
                    "place search exceeded its statement budget"
                ) from exc
            if isinstance(exc, PlaceCatalogUnavailableError):
                raise
            raise PlaceCatalogUnavailableError(
                "bundled place catalog query failed"
            ) from exc
        finally:
            connection.set_progress_handler(None, 0)
            connection.close()

        results = [
            {
                **{column: row[column] for column in _RESULT_COLUMNS},
                "coordinate_semantics": (
                    "dataset_representative_point_not_birth_address"
                ),
                # A place whose records may use either of two clocks lists both;
                # a chart for it is refused until the request names one.
                "civil_time_basis_choices": (
                    civil_time_basis_choices()
                    if is_dual_civil_time_place(
                        source=row["source"],
                        source_record_id=row["source_record_id"],
                        country_code=row["country_code"],
                        timezone=row["timezone"],
                    )
                    else None
                ),
            }
            for row in rows
        ]
        return self._response(results, metadata, query_receipt)


# A catalogue location in a chart request is the catalogue's row.  A request
# naming a record (location_source other than "manual") is computed only when
# every field arrives exactly as the row holds it: the label is display_name less
# surrounding whitespace; latitude and longitude compare as IEEE-754 binary64,
# so any JSON spelling of the stored number matches and the next double does
# not; the precision is the row's; the zone is the row's, or for a two-clock
# place that of the clock the request names.  Other coordinates or zones go as
# manual.  Check order is the order a refusal names the first difference in.
CATALOG_LOCATION_MISMATCH_REASONS = (
    "place_label_differs",
    "latitude_differs",
    "longitude_differs",
    "location_precision_differs",
    "timezone_differs",
)


class CatalogRecordUnknownError(ValueError):
    code = "catalog_record_unknown"


class CatalogLocationMismatchError(ValueError):
    code = "catalog_location_mismatch"

    def __init__(self, reason_code: str):
        if reason_code not in CATALOG_LOCATION_MISMATCH_REASONS:
            raise RuntimeError(f"unregistered catalogue mismatch reason: {reason_code}")
        super().__init__(reason_code)
        self.detail_extra = {"reason_code": reason_code}


def _is_location(value: Any) -> bool:
    fields = getattr(type(value), "model_fields", None) or {}
    return "location_source" in fields and "source_record_id" in fields


def request_locations(request: Any) -> list[tuple[Any, Any]]:
    """Every location a request carries, each with the zone it is bound to.

    Found by walking the request model, not by a list of field names, so a
    location field added to a request is checked without being registered.
    Only the request's own ``location`` sits beside the request's ``timezone``;
    a nested location (the relocated solar return) has no zone of its own.
    """

    found: list[tuple[Any, Any]] = []
    stack = [(request, True)]
    while stack:
        model, top = stack.pop()
        for name in type(model).model_fields:
            value = getattr(model, name)
            if _is_location(value):
                zone = getattr(request, "timezone", None) if top and name == "location" else None
                found.append((value, zone))
            elif getattr(type(value), "model_fields", None):
                stack.append((value, False))
    return found


def check_request_places(
    request: Any, catalogue_record: Callable[[str, str], dict | None]
) -> None:
    """Refuse a request whose catalogue location is not the catalogue's row,
    then ask the civil-time question of its place.  Every chart route calls
    this one check before computing; each record is read once."""

    rows: dict[tuple[str, str], dict | None] = {}

    def row_of(source: str, source_record_id: str) -> dict | None:
        key = (source, source_record_id)
        if key not in rows:
            rows[key] = catalogue_record(source, source_record_id)
        return rows[key]

    locations = [
        (location, zone)
        for location, zone in request_locations(request)
        if location.location_source != "manual"
    ]
    for location, _zone in locations:
        if row_of(location.location_source, location.source_record_id) is None:
            raise CatalogRecordUnknownError(
                "the catalogue holds no record with this source and id"
            )
    check_civil_time_basis(request, row_of)
    for location, zone in locations:
        row = row_of(location.location_source, location.source_record_id)
        if row is None:  # read above; the loop before refused a missing row
            raise CatalogRecordUnknownError("the catalogue holds no record with this source and id")
        reason = _first_difference(location, zone, row)
        if reason is not None:
            raise CatalogLocationMismatchError(reason)


def _first_difference(location: Any, zone: Any, row: dict) -> str | None:
    # The request schema strips surrounding whitespace from every string, and
    # one Taiwan row's stored label begins with a space; the row is read the
    # same way, so the search result sent back verbatim still matches
    # (tests/backend/test_catalogue_location_binding.py checks every row).
    if location.place_label != row["display_name"].strip():
        return "place_label_differs"
    if location.latitude != row["latitude"]:
        return "latitude_differs"
    if location.longitude != row["longitude"]:
        return "longitude_differs"
    if location.location_precision != row["location_precision"]:
        return "location_precision_differs"
    if zone is None:
        return None
    expected = row["timezone"]
    # The civil-time check has run: a basis here belongs to a two-clock place,
    # and the schema has tied it to its zone.
    if zone.civil_time_basis is not None:
        expected = CIVIL_TIME_BASIS_ZONES[zone.civil_time_basis]
    if zone.mode != "iana" or zone.iana_name != expected:
        return "timezone_differs"
    return None
