"""Check or regenerate the figures and quoted numbers of the blog articles and
the site's pages from their computations.

Each module computes its numbers (Swiss Ephemeris with the bundled ephemeris
files, the product's own tables, limits and chart answers, or the pinned tz
data) and returns its figure blocks (inline SVG, bar rows, table rows) plus the
strings its prose quotes.  The article modules are named after their topic,
the page modules `page_<fragment>` (the calculate-* landing pages are
`_landing.PAGES`).  In the page fragment every block sits between

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
    from . import (accuracy, antiscia, approximate_hour, ascendant_coordinates, birth_time, bounds, combustion,
                   dodecatemoria, era_time, firdaria_nodes, hk_time, house_sphere, houses, lilith, lots, mansions, nodes, planetary_hours,
                   receipt, reference_cases, rising_tables, sect, sidereal, solar_time, syzygy, taiwan_time, time_lords,
                   topocentric_moon, triplicity, unknown_time)

    return (birth_time, taiwan_time, hk_time, houses, bounds, nodes, unknown_time, rising_tables, solar_time,
            time_lords, dodecatemoria, combustion, mansions, syzygy, house_sphere, era_time, accuracy,
            approximate_hour, receipt, lots, sect, sidereal, firdaria_nodes, ascendant_coordinates,
            reference_cases, triplicity, lilith, topocentric_moon, planetary_hours, antiscia)


def pages() -> tuple:
    from . import (_landing, page_features, page_home, page_methods, page_methods_glossary, page_methods_time_lords,
                   page_roadmap, page_validation)

    return (page_home, page_features, page_methods, page_methods_time_lords, page_roadmap, page_validation,
            page_methods_glossary, *_landing.PAGES)


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


def _build_named(name: str) -> tuple[dict[str, str], list[str]]:
    """Build the module named `name`, or the landing page `<module>:<fragment>`."""
    import importlib

    module, _, landing = name.partition(":")
    found = importlib.import_module(module)
    return (found.page(landing) if landing else found).build()


def _build_all(modules) -> dict[str, tuple[dict[str, str], list[str]]]:
    """Every module's blocks and quoted strings, the modules built side by
    side in worker processes when there are several (each opens its own
    Swiss Ephemeris and application in-process client)."""
    import os

    jobs = min(len(modules), os.cpu_count() or 1)
    if jobs <= 1:
        return {module.__name__: module.build() for module in modules}
    from concurrent.futures import ProcessPoolExecutor

    names = [module.__name__ for module in modules]
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        return dict(zip(names, pool.map(_build_named, names), strict=True))


def check(modules, write: bool = False) -> list[str]:
    """Every failure the modules' blocks and quoted strings find in the page
    fragments; with `write`, the blocks are rewritten first."""
    from scripts.frontend import build_pages

    failures: list[str] = []
    built = _build_all(modules)
    for module in modules:
        path = build_pages.PAGES / f"{module.FRAGMENT}.html"
        fragment = path.read_text(encoding="utf-8")
        blocks, quoted = built[module.__name__]
        if not quoted:
            raise RuntimeError(f"{module.__name__} quotes no number")
        if write:
            if set(blocks_in(fragment)) != set(blocks):
                raise RuntimeError(f"{module.FRAGMENT}: the page's figure markers do not name {sorted(blocks)}")
            fragment = _replace(fragment, blocks)
            if path.read_text(encoding="utf-8") != fragment:
                path.write_text(fragment, encoding="utf-8")
        failures += problems(module.FRAGMENT, fragment, blocks, quoted)
        # Numbers the module computes that other prose repeats.
        for name, texts in getattr(module, "elsewhere", lambda _: {})(fragment).items():
            page = (build_pages.PAGES / f"{name}.html").read_text(encoding="utf-8")
            failures += [f"{name}: the prose no longer says {text!r}" for text in texts if text not in page]
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    modules = articles() + pages()
    failures = check(modules, write=args.write)
    if failures:
        print("PAGE FIGURES STALE:\n  " + "\n  ".join(failures))
        return 1
    print(f"PAGE FIGURES {'WRITTEN' if args.write else 'CURRENT'}: {len(modules)} articles and pages")
    return 0
