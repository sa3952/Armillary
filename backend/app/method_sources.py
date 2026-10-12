"""Method source register: the citations behind each method, table and model.

A chart response carries a `source_ref` code instead of the full bibliography,
and the register those codes resolve against is published once per release at
`PUBLISHED_PATH` (written by scripts/frontend/build_pages.py).  The response
records the register's identity and digest in
`calculation_dossier.method_source_register`, so a reader can prove which
register text a chart was computed under.

Status fields that say how far a source was checked (enums and booleans such as
`primary_texts_independently_transcribed`) stay in the response; only prose
moves.  Internal process notes (who checked what, when, under which review
finding) are not part of the register; they live in code comments and the
project's internal records.

Each core module owns its entries in a `METHOD_SOURCE_ENTRIES` mapping next to
the code that emits the matching `source_ref`, so a citation and its use change
together.  This module only assembles them; it imports the core modules, never
the other way round.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from .frontend_release import canonical_json_bytes

REGISTER_ID: Final = "armillary-method-sources"
REGISTER_VERSION: Final = "1"
PUBLISHED_PATH: Final = "/zh-TW/method-sources.json"
DIGEST_SEMANTICS: Final = (
    "sha256 of the register object serialized as UTF-8 JSON with sorted keys "
    "and separators (',', ':')"
)


def _module_entries() -> dict[str, dict[str, Any]]:
    from .core import (
        aspects,
        birth_time_sensitivity,
        bodies,
        civil_time_basis,
        classical_classifications,
        contested_methods,
        declination,
        dodecatemoria,
        essential_dignities,
        fixed_stars,
        horizon_events,
        houses,
        lots,
        lunar_events,
        lunar_mansions,
        moon,
        planetary_hours,
        solar_phase,
        prenatal_points,
        time_utils,
        tz_database,
    )

    entries: dict[str, dict[str, Any]] = {}
    for module in (
        essential_dignities,
        aspects,
        lots,
        moon,
        declination,
        fixed_stars,
        horizon_events,
        planetary_hours,
        lunar_events,
        bodies,
        contested_methods,
        birth_time_sensitivity,
        houses,
        time_utils,
        civil_time_basis,
        tz_database,
        dodecatemoria,
        lunar_mansions,
        solar_phase,
        prenatal_points,
        classical_classifications,
    ):
        for ref, entry in module.METHOD_SOURCE_ENTRIES.items():
            if ref in entries:
                raise ValueError(f"duplicate method source ref: {ref}")
            _require_closed_readings(entry, ref)
            entries[ref] = entry
    return dict(sorted(entries.items()))


def _require_closed_readings(value: Any, ref: str) -> None:
    """Every `reading` in a published entry is one of the closed levels."""

    from .core.source_reading import (
        SOURCE_READING_LEVELS,
        TRANSLATION_MARKERS_CITATION,
        TRANSLATION_MARKERS_READ_AT,
    )

    if isinstance(value, dict):
        for key, item in value.items():
            if key == "reading" and item not in SOURCE_READING_LEVELS:
                raise ValueError(f"{ref}: reading {item!r} outside the closed set")
            _require_closed_readings(item, ref)
        # What was read is a translation, so it cannot be the original language.
        says_translation = TRANSLATION_MARKERS_READ_AT.search(
            str(value.get("read_at") or "")
        ) or TRANSLATION_MARKERS_CITATION.search(str(value.get("citation") or ""))
        if value.get("reading") == SOURCE_READING_LEVELS[0] and says_translation:
            raise ValueError(
                f"{ref}: reading 'original_language_read' on a cited translation"
            )
    elif isinstance(value, list):
        for item in value:
            _require_closed_readings(item, ref)


ANNUAL_CANDIDATE_REGISTER_ID: Final = "armillary-method-sources-annual-candidate"
# How far the sources of an annual entry were read: what was read, then what
# was not.  A closed set, so a new reading level is a new value here first.
ANNUAL_SOURCE_VERIFICATION_STATES: Final = (
    "translation_and_kroll_greek_read_pingree_not_checked",
    "biruni_and_bonatti_translations_read_abu_mashar_not_checked",
    "research_notes_checked_edition_not_reread",
    "bibliographic_record_only_chapter_not_verified",
    "riley_translation_and_firmicus_latin_read_greek_not_checked",
    "pingree_translation_read_arabic_not_checked",
    "valens_translation_read_abu_mashar_secondary_only",
)


# Where the annual route stands (closed set).  It was a candidate behind its
# deployment flag; it is now released to the public, still served only where
# the deployment sets the flag.  Its response and its register say which.
ANNUAL_ROUTE_STATUSES: Final = ("candidate_behind_flag", "published")
ANNUAL_ROUTE_STATUS: Final = ANNUAL_ROUTE_STATUSES[1]


def annual_candidate_register() -> dict[str, Any]:
    """The annual route's entries, carried in its own response.

    They are a register of their own (with their own digest), not entries of
    the register every /api/chart response names: adding them there would
    change that digest.  ``published`` says whether the route, and so this
    register, is public.  A ref here may not repeat a ref of the /api/chart
    register, so the entries can move into _module_entries unchanged.
    """

    from .core import (
        decennials,
        extended_lots,
        firdaria,
        monthly_profections,
        planetary_years,
        profections,
        year_boundary,
        zodiacal_releasing,
    )

    published = _REGISTER["entries"]
    entries: dict[str, dict[str, Any]] = {}
    for module in (
        year_boundary, profections, firdaria, zodiacal_releasing, extended_lots,
        decennials, planetary_years, monthly_profections,
    ):
        for ref, entry in module.METHOD_SOURCE_ENTRIES.items():
            if ref in entries or ref in published:
                raise ValueError(f"duplicate method source ref: {ref}")
            if entry.get("source_verification") not in ANNUAL_SOURCE_VERIFICATION_STATES:
                raise ValueError(f"{ref}: source_verification outside the closed set")
            entries[ref] = entry
    register = {
        "register_id": ANNUAL_CANDIDATE_REGISTER_ID,
        "version": REGISTER_VERSION,
        "published": ANNUAL_ROUTE_STATUS == ANNUAL_ROUTE_STATUSES[1],
        "entries": dict(sorted(entries.items())),
    }
    return {**register, "sha256": register_digest(register), "digest_semantics": DIGEST_SEMANTICS}


def build_register() -> dict[str, Any]:
    return {
        "register_id": REGISTER_ID,
        "version": REGISTER_VERSION,
        "entries": _module_entries(),
    }


def register_digest(register: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(register)).hexdigest()


def published_register_text() -> str:
    """The exact bytes build_pages publishes at PUBLISHED_PATH."""

    return (
        json.dumps(build_register(), ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    )


_REGISTER: Final = build_register()
_RECEIPT: Final = {
    "register_id": REGISTER_ID,
    "version": REGISTER_VERSION,
    "sha256": register_digest(_REGISTER),
    "digest_semantics": DIGEST_SEMANTICS,
    "published_path": PUBLISHED_PATH,
    "resolves": "every source_ref in this response",
}


def method_source_register_receipt() -> dict[str, Any]:
    return dict(_RECEIPT)


def resolve(ref: str) -> dict[str, Any]:
    return _REGISTER["entries"][ref]
