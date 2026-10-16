"""The one canonical JSON form every digest in this service is taken over.

The trace receipt publishes these parameters as part of what it claims, so
they are a stated fact, and the same three values were once restated
independently in every module that computed a digest.  One definition, read by
all of them.
"""

from __future__ import annotations

import json
from typing import Final

CANONICAL_JSON_ENSURE_ASCII: Final = False
CANONICAL_JSON_SORT_KEYS: Final = True
CANONICAL_JSON_SEPARATORS: Final = (",", ":")
#: The same call as text, for a trace step that states how a digest was taken.
CANONICAL_JSON_DUMPS_ARGUMENTS: Final = (
    f"ensure_ascii={CANONICAL_JSON_ENSURE_ASCII}, sort_keys={CANONICAL_JSON_SORT_KEYS}, "
    f"separators={CANONICAL_JSON_SEPARATORS!r}"
)


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=CANONICAL_JSON_ENSURE_ASCII,
        sort_keys=CANONICAL_JSON_SORT_KEYS,
        separators=CANONICAL_JSON_SEPARATORS,
    ).encode("utf-8")
