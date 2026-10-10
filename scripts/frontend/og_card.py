#!/usr/bin/env python3
"""The link-preview card (og:image), from its one source.

The card: the armillary mark
large on the black plate, the ecliptic as a gold sine behind it, the name and
the home page's second heading beside it.  This module is the card's source:
`card_html()` builds the 1200x630 page as inline SVG with no external request
and no web font (system fonts, as the site itself uses), and `--render` has a
local headless Chromium photograph it into frontend/zh-TW/og-card.png, the one
static file every page names in its og:image.

The rendering depends on the machine's fonts and Chromium build, so the PNG is
committed rather than rebuilt in CI.  What keeps it from drifting from this
source is the render record beside this file: it names the digest of the HTML
that was photographed and of the PNG that came out, and
`python -m scripts.frontend.build_pages --check` fails when either no longer
matches (`render_record_errors`).

Every word on the card is already on a public page: 渾儀 and ARMILLARY are the
header's brand, the two lines are the home page's second heading, and the
domain is the site's.  Colours are scripts/frontend/styles/tokens.css plus the gold
ecliptic, used as decoration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
CARD_ASSET = "zh-TW/og-card.png"
CARD_PATH = ROOT / "frontend" / CARD_ASSET
RENDER_RECORD = ROOT / "scripts" / "frontend" / "og_card_render.json"
RENDERER = ROOT / "scripts" / "frontend" / "render_og_card.cjs"
WIDTH, HEIGHT = 1200, 630

# The card's text, each piece verbatim from a served page (a test reads the
# pages for them): the brand in the shared header and the home page's second
# heading, which the page breaks after the comma as the card does.
BRAND = "渾儀"
BRAND_LATIN = "ARMILLARY"
HEADLINE = ("每一部分都有名字，", "每一步都有出處。")
DOMAIN = "projectarmillary.com"

OBLIQUITY_DEGREES = 23.4393  # mean obliquity
PLATE, PLATE_FG, PLATE_DIM = "#131210", "#F2ECDC", "#968E7C"
ACCENT_REV, GOLD = "#D45633", "#D4AF6E"
GRID, GRID_EQUATOR = "#1E1C19", "#2E2B26"
SANS = '"PingFang TC","Noto Sans TC","Microsoft JhengHei",sans-serif'
MONO = 'ui-monospace,"SF Mono",Menlo,monospace'

# The header's mark (scripts/frontend/pages/_shell.html), drawn large.
_MARK = """<svg viewBox="0 0 40 40" width="400" height="400" fill="none" stroke="{fg}" stroke-width="0.42">
  <circle cx="20" cy="20" r="16"/>
  <ellipse cx="20" cy="20" rx="16" ry="4.5"/>
  <ellipse cx="20" cy="20" rx="16" ry="8" transform="rotate(-32 20 20)" stroke="{ecliptic}" stroke-width="0.55"/>
  <ellipse cx="20" cy="20" rx="5" ry="16"/>
  <line x1="20" y1="4" x2="20" y2="36" transform="rotate(-18 20 20)"/>
</svg>"""


def _declination(longitude: float) -> float:
    """Declination of an ecliptic point at latitude 0: asin(sin λ · sin ε)."""
    return math.degrees(math.asin(
        math.sin(math.radians(longitude)) * math.sin(math.radians(OBLIQUITY_DEGREES))
    ))


def _ecliptic_path(ymid: float, scale: float, lon_start: float) -> str:
    points = []
    for step in range(361):
        x = WIDTH * step / 360
        points.append(f"{x:.1f},{ymid - _declination(lon_start + step) * scale:.1f}")
    return "M" + " L".join(points)


def _graticule(ymid: float, scale: float) -> str:
    lines = []
    for dec in range(-30, 31, 10):
        y = ymid - dec * scale
        colour, width = (GRID_EQUATOR, 1.2) if dec == 0 else (GRID, 0.7)
        lines.append(f'<line x1="0" y1="{y:.1f}" x2="{WIDTH}" y2="{y:.1f}" stroke="{colour}" stroke-width="{width}"/>')
    for ra in range(0, 361, 30):
        x = WIDTH * ra / 360
        lines.append(f'<line x1="{x:.1f}" y1="{ymid - 30 * scale:.1f}" x2="{x:.1f}" y2="{ymid + 30 * scale:.1f}" stroke="{GRID}" stroke-width=".7"/>')
    return "\n".join(lines)


def card_html() -> str:
    ymid, scale = 330, 6.0
    svg = f"""<svg width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" xmlns="http://www.w3.org/2000/svg">
<rect width="{WIDTH}" height="{HEIGHT}" fill="{PLATE}"/>
{_graticule(ymid, scale)}
<path d="{_ecliptic_path(ymid, scale, -90)}" fill="none" stroke="{GOLD}" stroke-width="2" opacity=".85"/>
<g transform="translate(150,130)">{_MARK.format(fg=PLATE_FG, ecliptic=ACCENT_REV)}</g>
<text x="640" y="300" fill="{PLATE_FG}" font-family={SANS!r} font-size="96" font-weight="600">{BRAND}</text>
<text x="646" y="352" fill="{PLATE_DIM}" font-family={MONO!r} font-size="26" letter-spacing="10">{BRAND_LATIN}</text>
<text x="644" y="430" fill="{PLATE_FG}" font-family={SANS!r} font-size="26">{HEADLINE[0]}</text>
<text x="644" y="470" fill="{PLATE_FG}" font-family={SANS!r} font-size="26">{HEADLINE[1]}</text>
<text x="{WIDTH - 64}" y="{HEIGHT - 36}" text-anchor="end" fill="{PLATE_DIM}" font-family={MONO!r} font-size="18">{DOMAIN}</text>
</svg>"""
    return f"""<!doctype html><html lang="zh-TW"><head><meta charset="utf-8">
<style>html,body{{margin:0;width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;background:{PLATE}}}</style>
</head><body>{svg}</body></html>
"""


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def render_record_errors(record_path: Path | None = None, card_path: Path | None = None) -> list[str]:
    """Why the committed card is not the photograph of the current source."""
    record_path = RENDER_RECORD if record_path is None else record_path
    card_path = CARD_PATH if card_path is None else card_path
    if not record_path.is_file():
        return [f"og card render record is missing: {record_path.name}"]
    if not card_path.is_file():
        return [f"og card is missing: {CARD_ASSET}"]
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ["og card render record is not JSON"]
    errors = []
    if not isinstance(record, dict) or set(record) != {
        "schema_version", "asset", "source_html_sha256", "renderer_script_sha256", "png_sha256",
        "width", "height", "renderer",
    } or record.get("schema_version") != 1 or record.get("asset") != CARD_ASSET:
        return ["og card render record is invalid"]
    if record["source_html_sha256"] != _sha256(card_html().encode("utf-8")):
        errors.append("og card source changed since the card was rendered; "
                      "re-run: python -m scripts.frontend.og_card --render")
    if record["renderer_script_sha256"] != _sha256(RENDERER.read_bytes()):
        errors.append("og card renderer script changed since the card was rendered; "
                      "re-run: python -m scripts.frontend.og_card --render")
    if record["png_sha256"] != _sha256(card_path.read_bytes()):
        errors.append("og card PNG is not the one the render record names")
    if (record["width"], record["height"]) != (WIDTH, HEIGHT):
        errors.append("og card render record names the wrong size")
    return errors


def render(node: str | None = None) -> dict:
    """Photograph card_html() in local headless Chromium; write the PNG and its record."""
    node = node or shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to render the og card")
    html = card_html()
    with tempfile.TemporaryDirectory(prefix="armillary-og-card-") as scratch:
        source = Path(scratch) / "card.html"
        output = Path(scratch) / "card.png"
        source.write_text(html, encoding="utf-8")
        completed = subprocess.run(
            [node, str(RENDERER), str(source), str(output), str(WIDTH), str(HEIGHT)],
            cwd=ROOT / "frontend", capture_output=True, text=True, check=False, timeout=120,
        )
        if completed.returncode != 0:
            raise RuntimeError("og card render failed: " + completed.stderr.strip())
        report = json.loads(completed.stdout.strip().splitlines()[-1])
        if report.get("external_requests") != 0:
            raise RuntimeError("og card render attempted an external request")
        png = output.read_bytes()
    CARD_PATH.write_bytes(png)
    record = {
        "schema_version": 1,
        "asset": CARD_ASSET,
        "source_html_sha256": _sha256(html.encode("utf-8")),
        "renderer_script_sha256": _sha256(RENDERER.read_bytes()),
        "png_sha256": _sha256(png),
        "width": WIDTH,
        "height": HEIGHT,
        "renderer": report["renderer"],
    }
    RENDER_RECORD.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--render", action="store_true", help="photograph the card and write its record")
    group.add_argument("--check", action="store_true", help="fail if the card is not current")
    args = parser.parse_args()
    if args.render:
        record = render()
        print(f"OG CARD RENDERED: {CARD_ASSET} {record['png_sha256'][:16]} ({record['renderer']})")
        return 0
    errors = render_record_errors()
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f"OG CARD CURRENT: {CARD_ASSET}")
    return 1 if errors else 0


if __name__ == "__main__":
    os.umask(0o022)
    raise SystemExit(main())
