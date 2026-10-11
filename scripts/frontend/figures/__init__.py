"""Check or regenerate the blog articles' figures from their computations.

Each article module computes its numbers (Swiss Ephemeris with the bundled
ephemeris files, the product's own tables and chart answers, or the pinned tz
data) and returns its figure blocks (inline SVG, bar rows, table rows) plus the
strings its prose quotes.  In the page fragment every block sits between

    <!-- figure:NAME -->
    ...
    <!-- /figure:NAME -->

(comment lines, stripped from the built page).  `--check` regenerates every
block and compares it byte for byte with the fragment, and requires every
quoted string to appear in it (and, where a module names them, the strings
other pages repeat); `--write` rewrites the blocks.  Prose is never
rewritten: a quoted number that no longer holds fails both modes.

    python -m scripts.frontend.figures --check
    python -m scripts.frontend.figures --write
"""
from __future__ import annotations

import argparse
import re


_BLOCK = re.compile(
    r"^(?P<indent>[ \t]*)<!-- figure:(?P<name>[a-z0-9-]+) -->\n(?P<body>.*?)^(?P=indent)<!-- /figure:(?P=name) -->\n",
    re.MULTILINE | re.DOTALL,
)


def articles() -> tuple:
    from . import birth_time, bounds, houses, nodes, rising_tables, solar_time, taiwan_time, unknown_time

    return (birth_time, taiwan_time, houses, bounds, nodes, unknown_time, rising_tables, solar_time)


def blocks_in(fragment: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for match in _BLOCK.finditer(fragment):
        if match["name"] in found:
            raise RuntimeError(f"figure block {match['name']!r} appears twice")
        found[match["name"]] = match["body"]
    return found


def _replace(fragment: str, blocks: dict[str, str]) -> str:
    def body(match: re.Match) -> str:
        start, end = match.span("body")
        offset = match.start()
        whole = match.group(0)
        return whole[: start - offset] + blocks[match["name"]] + "\n" + whole[end - offset:]

    return _BLOCK.sub(body, fragment)


def problems(fragment_name: str, fragment: str, blocks: dict[str, str], quoted: list[str]) -> list[str]:
    found = blocks_in(fragment)
    out = []
    if set(found) != set(blocks):
        out.append(f"{fragment_name}: blocks in the page {sorted(found)} != generated {sorted(blocks)}")
    for name in sorted(set(found) & set(blocks)):
        if found[name] != blocks[name] + "\n":
            out.append(f"{fragment_name}: figure {name!r} differs from its generator")
    out += [f"{fragment_name}: the prose no longer says {text!r}" for text in quoted if text not in fragment]
    return out


def main(argv: list[str] | None = None) -> int:
    from scripts.frontend import build_pages

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    failures: list[str] = []
    count = 0
    modules = articles()
    for module in modules:
        path = build_pages.PAGES / f"{module.FRAGMENT}.html"
        fragment = path.read_text(encoding="utf-8")
        blocks, quoted = module.build()
        if not blocks or not quoted:
            raise RuntimeError(f"{module.__name__} produced no figure or no quoted number")
        count += len(blocks)
        if args.write:
            if set(blocks_in(fragment)) != set(blocks):
                raise RuntimeError(f"{module.FRAGMENT}: the page's figure markers do not name {sorted(blocks)}")
            fragment = _replace(fragment, blocks)
            if path.read_text(encoding="utf-8") != fragment:
                path.write_text(fragment, encoding="utf-8")
        failures += problems(module.FRAGMENT, fragment, blocks, quoted)
        # Numbers the article computes that other prose repeats.
        for name, texts in getattr(module, "elsewhere", lambda _: {})(fragment).items():
            page = (build_pages.PAGES / f"{name}.html").read_text(encoding="utf-8")
            failures += [f"{name}: the prose no longer says {text!r}" for text in texts if text not in page]
    if failures:
        print("ARTICLE FIGURES STALE:\n  " + "\n  ".join(failures))
        return 1
    print(f"ARTICLE FIGURES {'WRITTEN' if args.write else 'CURRENT'}: {count} blocks in {len(modules)} articles")
    return 0
