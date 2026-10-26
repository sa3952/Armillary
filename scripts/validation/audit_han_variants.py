#!/usr/bin/env python3
"""Write the Simplified-to-Traditional character table the place catalogue folds queries with.

Maintainer tool, not part of the build: it runs ICU's ``Simplified-Traditional``
transform through macOS Foundation (``osascript -l JavaScript``), which the
runtime and the producer do not have.  It writes
``han_simplified_to_traditional.json``; the producer reads that table, drops
every character that Taiwan's own place names use as written (后 of 后里, 台,
干), and stores the rest in the catalogue, where the runtime reads it.

Each character of the CJK Unified Ideographs block is transformed alone, so the
table holds ICU's context-free choice; a character ICU leaves unchanged is not
listed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess

TABLE_PATH = Path(__file__).with_name("han_simplified_to_traditional.json")
BLOCK = (0x4E00, 0x9FFF)
_SCRIPT = """
ObjC.import("Foundation");
function run(argv) {
  var text = $.NSString.alloc.initWithUTF8String(argv[0]);
  return ObjC.unwrap(text.stringByApplyingTransformReverse("Simplified-Traditional", false));
}
"""


def icu_simplified_to_traditional(characters: list[str]) -> list[str]:
    joined = "\n".join(characters)
    result = subprocess.run(
        ["osascript", "-l", "JavaScript", "-e", _SCRIPT, joined],
        check=True, capture_output=True, text=True,
    )
    converted = result.stdout.rstrip("\n").split("\n")
    if len(converted) != len(characters):
        raise SystemExit("the transform changed the number of lines; refusing a misaligned table")
    return converted


def build_table() -> dict:
    characters = [chr(code) for code in range(BLOCK[0], BLOCK[1] + 1)]
    converted = icu_simplified_to_traditional(characters)
    mapping = {
        simplified: traditional
        for simplified, traditional in zip(characters, converted)
        if traditional != simplified and len(traditional) == 1
    }
    if not mapping:
        raise SystemExit("the transform mapped no character")
    return {
        "engine": f"ICU Simplified-Traditional via macOS Foundation {platform.mac_ver()[0]}",
        "block": [f"U+{BLOCK[0]:04X}", f"U+{BLOCK[1]:04X}"],
        "rule": "each character transformed alone; unchanged characters and multi-character results are omitted",
        "simplified_to_traditional": dict(sorted(mapping.items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=TABLE_PATH)
    args = parser.parse_args()
    table = build_table()
    args.output.write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(table['simplified_to_traditional'])} characters -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
