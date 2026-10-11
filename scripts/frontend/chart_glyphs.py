#!/usr/bin/env python3
"""The chart wheel's astrological glyphs, as SVG path strings.

`frontend/zh-TW/chart-glyphs.js` holds one path per symbol the wheel draws
(the planets, Chiron, the lunar nodes, the twelve signs and the retrograde
mark).  The same string feeds an SVG `<path d>` on the page and in the SVG
download, and a Canvas `Path2D` in the PNG download, so no system font or
emoji presentation decides what a symbol looks like.

The paths are the outlines of three SIL Open Font License 1.1 fonts from the
Google Fonts repository (provenance, versions and checksums in
`third_party/noto-fonts/README.md`).  The fonts themselves stay outside the
repository: run this module with `--fonts DIR`, where DIR holds the three files
named in `FONTS`; each file's SHA-256 is checked before it is read.  TrueType
quadratic contours become `M`/`L`/`Q`/`Z` commands unchanged (implied on-curve
midpoints made explicit), y is flipped to point down, and the unit is the
fonts' own 1/1000 em, rounded to 0.1.

A path taken from a font outline is a Modified Version of the Font Software in
the OFL's sense, so the generated file carries the copyright lines and the full
licence text (from the `third_party/noto-fonts/OFL-*.txt` copies), and uses no
font name as its own.

    python -m scripts.frontend.chart_glyphs --fonts DIR          # write
    python -m scripts.frontend.chart_glyphs --fonts DIR --check  # compare
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "frontend" / "zh-TW" / "chart-glyphs.js"
LICENCES = (
    ROOT / "third_party" / "noto-fonts" / "OFL-noto-sans-symbols.txt",
    ROOT / "third_party" / "noto-fonts" / "OFL-noto-sans.txt",
)

# file name -> SHA-256 of the exact bytes downloaded from google/fonts.
FONTS = {
    "NotoSansSymbols[wght].ttf": "f7e7e04b4a24b6c78893d50cbfd2b2f6cae49617ab047bfef668d252adb128f7",
    "NotoSansSymbols2-Regular.ttf": "7d5fb73b7ca67a6798101741f5d280a3d016a56a197afcd4199dbb57b4b82a21",
    "NotoSans[wdth,wght].ttf": "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d",
}

SYMBOLS = "NotoSansSymbols[wght].ttf"
SYMBOLS_2 = "NotoSansSymbols2-Regular.ttf"
SANS = "NotoSans[wdth,wght].ttf"

# Wheel key -> (code point, font).  Noto Sans Symbols has no U+2609 and no
# U+211E; those two come from Symbols 2 and from Noto Sans.
GLYPHS: dict[str, tuple[int, str]] = {
    "sun": (0x2609, SYMBOLS_2),
    "moon": (0x263D, SYMBOLS),
    "mercury": (0x263F, SYMBOLS),
    "venus": (0x2640, SYMBOLS),
    "mars": (0x2642, SYMBOLS),
    "jupiter": (0x2643, SYMBOLS),
    "saturn": (0x2644, SYMBOLS),
    "uranus": (0x2645, SYMBOLS),
    "neptune": (0x2646, SYMBOLS),
    "pluto": (0x2647, SYMBOLS),
    "chiron": (0x26B7, SYMBOLS),
    "north_node": (0x260A, SYMBOLS),
    "south_node": (0x260B, SYMBOLS),
    "retrograde": (0x211E, SANS),
    "aries": (0x2648, SYMBOLS),
    "taurus": (0x2649, SYMBOLS),
    "gemini": (0x264A, SYMBOLS),
    "cancer": (0x264B, SYMBOLS),
    "leo": (0x264C, SYMBOLS),
    "virgo": (0x264D, SYMBOLS),
    "libra": (0x264E, SYMBOLS),
    "scorpio": (0x264F, SYMBOLS),
    "sagittarius": (0x2650, SYMBOLS),
    "capricorn": (0x2651, SYMBOLS),
    "aquarius": (0x2652, SYMBOLS),
    "pisces": (0x2653, SYMBOLS),
}

Point = tuple[float, float, bool]


class Font:
    """The few TrueType tables a glyph outline needs: cmap, head, maxp, loca, glyf."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        count = struct.unpack(">H", data[4:6])[0]
        self.tables: dict[str, int] = {}
        for index in range(count):
            tag, _checksum, offset, _length = struct.unpack(">4sIII", data[12 + 16 * index: 28 + 16 * index])
            self.tables[tag.decode("latin-1")] = offset
        head = self.tables["head"]
        self.units_per_em = struct.unpack(">H", data[head + 18: head + 20])[0]
        long_offsets = struct.unpack(">h", data[head + 50: head + 52])[0] == 1
        glyph_count = struct.unpack(">H", data[self.tables["maxp"] + 4: self.tables["maxp"] + 6])[0]
        loca = self.tables["loca"]
        if long_offsets:
            self.loca = list(struct.unpack(f">{glyph_count + 1}I", data[loca: loca + 4 * (glyph_count + 1)]))
        else:
            self.loca = [2 * value for value in
                         struct.unpack(f">{glyph_count + 1}H", data[loca: loca + 2 * (glyph_count + 1)])]
        self.cmap = self._cmap()

    def _u16(self, offset: int) -> int:
        return int(struct.unpack(">H", self.data[offset: offset + 2])[0])

    def _cmap(self) -> dict[int, int]:
        data, base = self.data, self.tables["cmap"]
        subtables = []
        for index in range(self._u16(base + 2)):
            _platform, _encoding, offset = struct.unpack(">HHI", data[base + 4 + 8 * index: base + 12 + 8 * index])
            subtables.append(base + offset)
        mapping: dict[int, int] = {}
        for start in subtables:
            if self._u16(start) == 12:
                for group in range(struct.unpack(">I", data[start + 12: start + 16])[0]):
                    first, last, glyph = struct.unpack(">III", data[start + 16 + 12 * group: start + 28 + 12 * group])
                    for code in range(first, last + 1):
                        mapping.setdefault(code, glyph + code - first)
            elif self._u16(start) == 4:
                segments = self._u16(start + 6) // 2
                ends = start + 14
                starts = ends + 2 * segments + 2
                deltas = starts + 2 * segments
                ranges = deltas + 2 * segments
                for segment in range(segments):
                    end = self._u16(ends + 2 * segment)
                    begin = self._u16(starts + 2 * segment)
                    delta = struct.unpack(">h", data[deltas + 2 * segment: deltas + 2 * segment + 2])[0]
                    range_offset = self._u16(ranges + 2 * segment)
                    for code in range(begin, end + 1):
                        if code == 0xFFFF:
                            continue
                        if range_offset == 0:
                            glyph = (code + delta) & 0xFFFF
                        else:
                            glyph = self._u16(ranges + 2 * segment + range_offset + 2 * (code - begin))
                            glyph = (glyph + delta) & 0xFFFF if glyph else 0
                        mapping.setdefault(code, glyph)
        return mapping

    def contours(self, glyph: int) -> list[list[Point]]:
        data = self.data
        if self.loca[glyph + 1] == self.loca[glyph]:
            return []
        offset = self.tables["glyf"] + self.loca[glyph]
        contour_count = struct.unpack(">h", data[offset: offset + 2])[0]
        cursor = offset + 10
        if contour_count < 0:
            return self._composite(cursor)
        ends = struct.unpack(f">{contour_count}H", data[cursor: cursor + 2 * contour_count])
        cursor += 2 * contour_count
        cursor += 2 + self._u16(cursor)          # instructions
        point_count = ends[-1] + 1 if contour_count else 0
        flags: list[int] = []
        while len(flags) < point_count:
            flag = data[cursor]
            cursor += 1
            flags.append(flag)
            if flag & 8:
                flags.extend([flag] * data[cursor])
                cursor += 1
        coordinates: list[list[int]] = []
        for short, same in ((2, 16), (4, 32)):
            value, values = 0, []
            for flag in flags:
                if flag & short:
                    value += data[cursor] if flag & same else -data[cursor]
                    cursor += 1
                elif not flag & same:
                    value += struct.unpack(">h", data[cursor: cursor + 2])[0]
                    cursor += 2
                values.append(value)
            coordinates.append(values)
        xs, ys = coordinates
        contours, first = [], 0
        for end in ends:
            contours.append([(float(xs[k]), float(ys[k]), bool(flags[k] & 1)) for k in range(first, end + 1)])
            first = end + 1
        return contours

    def _composite(self, cursor: int) -> list[list[Point]]:
        data = self.data
        contours: list[list[Point]] = []
        while True:
            flags, component = struct.unpack(">HH", data[cursor: cursor + 4])
            cursor += 4
            if flags & 1:
                dx, dy = struct.unpack(">hh", data[cursor: cursor + 4])
                cursor += 4
            else:
                dx, dy = struct.unpack(">bb", data[cursor: cursor + 2])
                cursor += 2
            if not flags & 2:
                raise ValueError("a point-matched composite glyph is not supported")
            a, b, c, d = 1.0, 0.0, 0.0, 1.0
            if flags & 0x08:
                a = d = struct.unpack(">h", data[cursor: cursor + 2])[0] / 16384
                cursor += 2
            elif flags & 0x40:
                a, d = (value / 16384 for value in struct.unpack(">hh", data[cursor: cursor + 4]))
                cursor += 4
            elif flags & 0x80:
                a, b, c, d = (value / 16384 for value in struct.unpack(">hhhh", data[cursor: cursor + 8]))
                cursor += 8
            for contour in self.contours(component):
                contours.append([(x * a + y * c + dx, x * b + y * d + dy, on) for x, y, on in contour])
            if not flags & 0x20:
                return contours


def _number(value: float) -> str:
    rounded = round(value, 1)
    return str(int(rounded)) if rounded == int(rounded) else str(rounded)


def path_data(contours: list[list[Point]]) -> str:
    """Quadratic TrueType contours as SVG commands, y pointing down."""
    commands: list[str] = []
    for contour in contours:
        points = [(x, -y, on) for x, y, on in contour]
        start_index = next((k for k, point in enumerate(points) if point[2]), None)
        if start_index is None:
            start = ((points[0][0] + points[1][0]) / 2, (points[0][1] + points[1][1]) / 2)
            sequence = points[1:] + points[:1]
        else:
            start = points[start_index][:2]
            sequence = points[start_index + 1:] + points[:start_index]
        commands.append(f"M{_number(start[0])} {_number(start[1])}")
        control: tuple[float, float] | None = None
        for x, y, on in sequence + [(start[0], start[1], True)]:
            if on:
                if control:
                    commands.append(f"Q{_number(control[0])} {_number(control[1])} {_number(x)} {_number(y)}")
                else:
                    commands.append(f"L{_number(x)} {_number(y)}")
                control = None
            else:
                if control:
                    mid_x, mid_y = (control[0] + x) / 2, (control[1] + y) / 2
                    commands.append(f"Q{_number(control[0])} {_number(control[1])} {_number(mid_x)} {_number(mid_y)}")
                control = (x, y)
        if commands[-1] == f"L{_number(start[0])} {_number(start[1])}":
            commands.pop()
        commands.append("Z")
    return "".join(commands)


def load_fonts(directory: Path) -> dict[str, Font]:
    fonts = {}
    for name, digest in FONTS.items():
        data = (directory / name).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != digest:
            raise SystemExit(f"{name}: SHA-256 {actual} is not the pinned {digest}")
        fonts[name] = Font(data)
    return fonts


def extract(fonts: dict[str, Font]) -> dict[str, dict[str, object]]:
    glyphs: dict[str, dict[str, object]] = {}
    for key, (code, name) in GLYPHS.items():
        font = fonts[name]
        if font.units_per_em != 1000:
            raise SystemExit(f"{name}: {font.units_per_em} units per em, expected 1000")
        glyph = font.cmap.get(code)
        if not glyph:
            raise SystemExit(f"{name} has no glyph for U+{code:04X}")
        contours = font.contours(glyph)
        xs = [x for contour in contours for x, _, _ in contour]
        ys = [-y for contour in contours for _, y, _ in contour]
        glyphs[key] = {
            "codepoint": f"U+{code:04X}",
            "font": name,
            "bbox": [_number(min(xs)), _number(min(ys)), _number(max(xs)), _number(max(ys))],
            "d": path_data(contours),
        }
    return glyphs


def licence_comment() -> str:
    texts = [path.read_text(encoding="utf-8") for path in LICENCES]
    copyrights = [text.splitlines()[0] for text in texts]
    bodies = {"\n".join(text.splitlines()[1:]) for text in texts}
    if len(bodies) != 1:
        raise SystemExit("the OFL copies differ beyond their copyright line")
    body = bodies.pop()
    lines = copyrights + body.splitlines()
    return "\n".join((" * " + line).rstrip() for line in lines)


def render(glyphs: dict[str, dict[str, object]]) -> str:
    entries = []
    for key, glyph in glyphs.items():
        bbox = ", ".join(str(value) for value in glyph["bbox"])  # type: ignore[attr-defined]
        entries.append(
            f"    {key}: Object.freeze({{ codepoint: \"{glyph['codepoint']}\", bbox: Object.freeze([{bbox}]),\n"
            f"      d: {json.dumps(glyph['d'])} }}),"
        )
    fonts = "\n".join(f" *   {name}  sha256 {digest}" for name, digest in FONTS.items())
    return f"""/*
 * 星盤圖的符號：每個符號一條 SVG path，同一份字串給頁面與下載 SVG 的 <path d>，
 * 也給 PNG 下載的 Canvas Path2D。不用系統字型或 emoji，所以各平台畫出來一樣。
 *
 * Generated by `python -m scripts.frontend.chart_glyphs --fonts DIR`; do not edit.
 * Outlines taken from (provenance in third_party/noto-fonts/README.md):
{fonts}
 * Units are 1/1000 em, y down; bbox is [xMin, yMin, xMax, yMax].
 *
 * These paths are a Modified Version of the Font Software below and are
 * distributed under the same licence.
 *
{licence_comment()}
 */
(function attachChartGlyphs(root, factory) {{
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ArmillaryChartGlyphs = api;
}})(typeof globalThis !== "undefined" ? globalThis : this, function buildChartGlyphs() {{
  "use strict";

  const GLYPHS = Object.freeze({{
{chr(10).join(entries)}
  }});

  return Object.freeze({{ UNITS_PER_EM: 1000, GLYPHS }});
}});
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fonts", type=Path, required=True, help="directory holding the files named in FONTS")
    parser.add_argument("--check", action="store_true", help="compare instead of writing")
    args = parser.parse_args(argv)
    text = render(extract(load_fonts(args.fonts)))
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != text:
            print(f"{OUTPUT.relative_to(ROOT)} differs from its producer", file=sys.stderr)
            return 1
        print(f"{OUTPUT.relative_to(ROOT)} is current")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)} ({len(GLYPHS)} glyphs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
