#!/usr/bin/env python3
"""Draw a reproducible sample of method source citations to re-check by hand.

Before each release a reader re-opens a few cited works and confirms that the
page, chapter or section the register names still says what the entry claims.
This script only chooses which citations and writes the worksheet; it records
nothing as checked.  Every row starts with an empty result for the reader.

The draw is seeded by the release revision, so the same revision always yields
the same rows and anyone can re-draw them.  It is stratified: every reading
level present in the register contributes at least one row (when N allows),
the rest are drawn from all citations alike.

    python -m scripts.verification.sample_source_audit --revision <40-hex> \
        [--count 12] [--output worksheet.md]
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from pathlib import Path
from typing import Any, Iterator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.source_reading import SOURCE_READING_LEVELS  # noqa: E402
from app.method_sources import build_register  # noqa: E402

DEFAULT_COUNT = 12

WHERE_TO_CHECK = {
    "original_language_read": "open the original-language edition named in read_at at the cited page",
    "translation_read": "open the translation named in read_at at the cited page or section",
    "secondary_only": "open the secondary work named in read_at and confirm it reports this",
    "bibliographic_only": "confirm the reference itself (title, chapter, page) exists as cited",
}


def iter_citations(value: Any, ref: str, path: str = "") -> Iterator[dict[str, str]]:
    """Every citation object in an entry, with the ref and the path it sits at."""

    if isinstance(value, dict):
        if "citation" in value and "reading" in value:
            yield {
                "ref": ref,
                "path": path or "/",
                "citation": str(value["citation"]),
                "says": str(value.get("says") or ""),
                "reading": str(value["reading"]),
                "read_at": str(value.get("read_at") or ""),
            }
        for key in sorted(value):
            yield from iter_citations(value[key], ref, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from iter_citations(item, ref, f"{path}/{index}")


def all_citations(register: dict[str, Any] | None = None) -> list[dict[str, str]]:
    register = register if register is not None else build_register()
    rows: list[dict[str, str]] = []
    for ref, entry in sorted(register["entries"].items()):
        rows.extend(iter_citations(entry, ref))
    return rows


def sample(revision: str, count: int = DEFAULT_COUNT,
           citations: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """The rows to re-check for `revision`: deterministic and stratified by reading level."""

    if count < 1:
        raise ValueError("count must be at least 1")
    pool = citations if citations is not None else all_citations()
    seed = int.from_bytes(hashlib.sha256(f"source-audit:{revision}".encode()).digest()[:8], "big")
    rng = random.Random(seed)
    chosen: list[int] = []
    for level in SOURCE_READING_LEVELS:
        indices = [i for i, row in enumerate(pool) if row["reading"] == level]
        if indices and len(chosen) < count:
            chosen.append(rng.choice(indices))
    rest = [i for i in range(len(pool)) if i not in set(chosen)]
    chosen.extend(rng.sample(rest, min(count - len(chosen), len(rest))))
    return [pool[i] for i in sorted(chosen)]


def worksheet(revision: str, rows: list[dict[str, str]], total: int) -> str:
    lines = [
        "# Source page re-check worksheet",
        "",
        f"- release revision: `{revision}`",
        f"- drawn: {len(rows)} of {total} citations (re-draw with the same revision to get the same rows)",
        "- result: fill each row with `confirmed`, `wrong page/section` (give the right one) or `not checked`.",
        "  Nothing here is checked until a reader fills it in.",
        "",
    ]
    for number, row in enumerate(rows, 1):
        lines += [
            f"## {number}. `{row['ref']}` {row['path']}",
            "",
            f"- citation (claimed page/section): {row['citation']}",
            f"- reading level: `{row['reading']}`",
            f"- copy read: {row['read_at']}",
            f"- claims: {row['says'] or '(no summary)'}",
            f"- where to check: {WHERE_TO_CHECK.get(row['reading'], 'see read_at')}",
            "- result: ",
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--revision", required=True, help="the release revision that seeds the draw")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--output", type=Path, help="write the worksheet here instead of stdout")
    args = parser.parse_args(argv)
    pool = all_citations()
    text = worksheet(args.revision, sample(args.revision, args.count, pool), len(pool))
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
