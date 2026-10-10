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
        contested_methods,
        declination,
        essential_dignities,
        fixed_stars,
        horizon_events,
        houses,
        lots,
        lunar_events,
        moon,
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
        lunar_events,
        bodies,
        contested_methods,
        birth_time_sensitivity,
        houses,
        time_utils,
        tz_database,
    ):
        for ref, entry in module.METHOD_SOURCE_ENTRIES.items():
            if ref in entries:
                raise ValueError(f"duplicate method source ref: {ref}")
            entries[ref] = entry
    return dict(sorted(entries.items()))


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
