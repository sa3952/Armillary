#!/usr/bin/env python3
"""The site icons, drawn from the header's armillary mark.

Reads the inline `<svg class="mark">` geometry from the page shell and the plate, ring and accent colours from
styles/tokens.css, and writes `frontend/zh-TW/favicon.svg`, `frontend/favicon.ico` (16, 32 and 48 px; search engines
read ICO and PNG, not SVG) and `frontend/apple-touch-icon.png` (180 px, opaque, the mark inset so the iOS mask never
cuts it).

The mark always sits on the black plate, so one icon reads on a light and a dark browser bar.  Rings use the plate's
foreground colour, not the header's dim one, which blurs into the plate at 16 px.  Stroke widths are set per size in
device pixels so the rings stay about one pixel wide at 16 px.

The rasters are rendered here, not photographed: coverage comes from exact distances (only + - x / and sqrt, which
IEEE 754 rounds identically everywhere) and the PNGs use the small deflate encoder below instead of the host's zlib,
whose output varies by version.  The same source gives the same bytes everywhere, and `--check` compares them.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
import math
import os
from pathlib import Path
import re
import struct
import sys
import zlib

from scripts.frontend.site_locale import DEFAULT_LOCALE

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
SHELL = ROOT / "scripts" / "frontend" / "pages" / "_shell.html"
TOKENS = ROOT / "scripts" / "frontend" / "styles" / "tokens.css"

SVG_ASSET = f"{DEFAULT_LOCALE}/favicon.svg"
ICO_ASSET = "favicon.ico"
TOUCH_ASSET = "apple-touch-icon.png"
ICO_SIZES = (16, 32, 48)
TOUCH_SIZE = 180

# The plate's corner radius as a share of its side: the repository mark's (12 on 120).  The touch icon stays square:
# iOS applies its own mask.
CORNER = 0.1
# The touch icon's ring is 70 % of the side, inside the area every iOS mask keeps.
TOUCH_RING_SHARE = 0.7

# Ring and accent stroke widths in device pixels per raster size: about one pixel at tab sizes, thinner relative to
# the side from 48 px up.
STROKES_PX = {16: (1.0, 1.3), 32: (1.75, 2.25), 48: (1.4, 1.8), TOUCH_SIZE: (3.6, 4.4)}
# The SVG is drawn at 16 CSS px; its widths are in the mark's 40-unit space (2.2 units is 0.88 CSS px).
SVG_STROKES = (2.2, 2.8)
# At tab size the meridian and axis blur together, so the tab icons (the SVG, the ICO's 16 and 32 px) omit the
# meridian; the 48 px entry and the touch icon carry the whole mark.
FULL_MARK_FROM_PX = 48

# --- the mark, read from the shell -----------------------------------------

@dataclass(frozen=True)
class Shape:
    kind: str                 # "circle", "ellipse" or "line"
    values: tuple[float, ...]  # circle: cx cy r; ellipse: cx cy rx ry; line: x1 y1 x2 y2
    rotate: tuple[float, float, float] | None  # degrees, about (x, y)
    accent: bool

@dataclass(frozen=True)
class Mark:
    view: float
    shapes: tuple[Shape, ...]

class _MarkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.view: str | None = None
        self.shapes: list[tuple[str, dict[str, str]]] = []
        self.marks = 0
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        if tag == "svg" and "mark" in attributes.get("class", "").split():
            self.marks += 1
            self.view = attributes.get("viewbox")
            self._depth = 1
            return
        if self._depth:
            if tag in {"circle", "ellipse", "line"}:
                self.shapes.append((tag, attributes))
            elif tag != "svg":
                raise ValueError(f"unexpected <{tag}> in the header mark")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "svg" and self._depth:
            self._depth = 0

_ROTATE = re.compile(r"rotate\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\)")
_FIELDS = {"circle": ("cx", "cy", "r"), "ellipse": ("cx", "cy", "rx", "ry"), "line": ("x1", "y1", "x2", "y2")}

def read_mark(shell: str | None = None) -> Mark:
    parser = _MarkParser()
    parser.feed(SHELL.read_text(encoding="utf-8") if shell is None else shell)
    if parser.marks != 1 or parser.view is None:
        raise ValueError("the page shell must carry exactly one <svg class=\"mark\">")
    view = parser.view.split()
    if len(view) != 4 or view[:2] != ["0", "0"] or view[2] != view[3]:
        raise ValueError("the header mark's viewBox must be a square from the origin")
    shapes = []
    for tag, attributes in parser.shapes:
        transform = attributes.get("transform", "").strip()
        rotate: tuple[float, float, float] | None = None
        if transform:
            match = _ROTATE.fullmatch(transform)
            if match is None:
                raise ValueError(f"unsupported transform in the header mark: {transform}")
            angle, ox, oy = (float(value) for value in match.groups())
            rotate = (angle, ox, oy)
        shapes.append(Shape(kind=tag, values=tuple(float(attributes[name]) for name in _FIELDS[tag]), rotate=rotate,
            accent="mark-ecliptic" in attributes.get("class", "").split()))
    if not shapes or sum(shape.accent for shape in shapes) != 1:
        raise ValueError("the header mark must have shapes and exactly one accent ring")
    return Mark(view=float(view[2]), shapes=tuple(shapes))

def tab_mark(mark: Mark) -> Mark:
    meridians = [
        shape for shape in mark.shapes
        if shape.kind == "ellipse" and shape.rotate is None and shape.values[2] < shape.values[3]
    ]
    if len(meridians) != 1:
        raise ValueError("the header mark must have exactly one meridian ellipse")
    return Mark(view=mark.view, shapes=tuple(shape for shape in mark.shapes if shape is not meridians[0]))

_TOKEN = r"--{name}:\s*(#[0-9A-Fa-f]{{6}})\s*;"

def read_palette(tokens: str | None = None) -> dict[str, str]:
    text = TOKENS.read_text(encoding="utf-8") if tokens is None else tokens
    palette = {}
    for role, name in (("plate", "plate"), ("ring", "plate-fg"), ("accent", "accent-rev")):
        found = re.findall(_TOKEN.format(name=re.escape(name)), text)
        if len(set(value.upper() for value in found)) != 1:
            raise ValueError(f"tokens.css must define --{name} once as #RRGGBB")
        palette[role] = found[0].upper()
    return palette

# --- SVG ---------------------------------------------------------------------

def _number(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".")

def svg_text(mark: Mark, palette: dict[str, str]) -> str:
    mark = tab_mark(mark)
    ring, accent = SVG_STROKES
    side = _number(mark.view)
    lines = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side} {side}">',
        f'<rect width="{side}" height="{side}" rx="{_number(mark.view * CORNER)}" fill="{palette["plate"]}"/>',
        f'<g fill="none" stroke="{palette["ring"]}" stroke-width="{_number(ring)}">']
    for shape in mark.shapes:
        attributes = " ".join(f'{name}="{_number(value)}"' for name, value in zip(_FIELDS[shape.kind], shape.values))
        if shape.rotate is not None:
            attributes += ' transform="rotate({})"'.format(" ".join(_number(v) for v in shape.rotate))
        if shape.accent:
            attributes += f' stroke="{palette["accent"]}" stroke-width="{_number(accent)}"'
        lines.append(f"<{shape.kind} {attributes}/>")
    lines += ["</g>", "</svg>"]
    return "\n".join(lines) + "\n"

# --- raster ------------------------------------------------------------------
# Distances are in the mark's units.  Rotation sines and cosines are rounded to twelve places so a last-bit libm
# difference between hosts cannot reach the pixels.

def _rotation(rotate: tuple[float, float, float] | None) -> tuple[float, float, float, float]:
    if rotate is None:
        return 1.0, 0.0, 0.0, 0.0
    angle, cx, cy = rotate
    radians = math.radians(angle)
    return round(math.cos(radians), 12), round(math.sin(radians), 12), cx, cy

def _ellipse_distance(e0: float, e1: float, y0: float, y1: float) -> float:
    """Distance from (y0, y1) to the ellipse with semi-axes e0 >= e1 > 0.

    Eberly, "Distance from a Point to an Ellipse, an Ellipsoid, or a Hyperellipsoid" (Geometric Tools, 2013):
    bisection on the root of the tangency condition."""
    y0, y1 = abs(y0), abs(y1)
    if y1 > 0:
        if y0 > 0:
            z0, z1 = y0 / e0, y1 / e1
            g = z0 * z0 + z1 * z1 - 1
            if g == 0:
                return 0.0
            r0 = (e0 / e1) * (e0 / e1)
            n0 = r0 * z0
            s0 = z1 - 1
            s1 = 0.0 if g < 0 else math.sqrt(n0 * n0 + z1 * z1) - 1
            s = 0.0
            while True:
                s = (s0 + s1) / 2
                if s == s0 or s == s1:
                    break
                ratio0, ratio1 = n0 / (s + r0), z1 / (s + 1)
                g = ratio0 * ratio0 + ratio1 * ratio1 - 1
                if g > 0:
                    s0 = s
                elif g < 0:
                    s1 = s
                else:
                    break
            x0, x1 = r0 * y0 / (s + r0), y1 / (s + 1)
            return math.sqrt((x0 - y0) * (x0 - y0) + (x1 - y1) * (x1 - y1))
        return abs(y1 - e1)
    numer0, denom0 = e0 * y0, e0 * e0 - e1 * e1
    if numer0 < denom0:
        xde0 = numer0 / denom0
        x0, x1 = e0 * xde0, e1 * math.sqrt(1 - xde0 * xde0)
        return math.sqrt((x0 - y0) * (x0 - y0) + x1 * x1)
    return abs(y0 - e0)

def _segment_distance(x1: float, y1: float, x2: float, y2: float, px: float, py: float) -> float:
    dx, dy = x2 - x1, y2 - y1
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    ex, ey = x1 + t * dx - px, y1 + t * dy - py
    return math.sqrt(ex * ex + ey * ey)

def _shape_distance(shape: Shape, rotation, px: float, py: float, reach: float) -> float | None:
    """Distance from a point to a ring, or None when it is surely beyond `reach`."""
    cos, sin, ox, oy = rotation
    if shape.kind == "line":
        x1, y1, x2, y2 = shape.values
        ax = ox + (x1 - ox) * cos - (y1 - oy) * sin
        ay = oy + (x1 - ox) * sin + (y1 - oy) * cos
        bx = ox + (x2 - ox) * cos - (y2 - oy) * sin
        by = oy + (x2 - ox) * sin + (y2 - oy) * cos
        return _segment_distance(ax, ay, bx, by, px, py)
    qx = ox + (px - ox) * cos + (py - oy) * sin
    qy = oy - (px - ox) * sin + (py - oy) * cos
    if shape.kind == "circle":
        cx, cy, r = shape.values
        return abs(math.sqrt((qx - cx) * (qx - cx) + (qy - cy) * (qy - cy)) - r)
    cx, cy, rx, ry = shape.values
    dx, dy = qx - cx, qy - cy
    # The point lies on the ring scaled by rho; two such rings are at least
    # |rho - 1| times the minor semi-axis apart.
    rho = math.sqrt((dx / rx) * (dx / rx) + (dy / ry) * (dy / ry))
    if abs(rho - 1) * min(rx, ry) > reach:
        return None
    if rx >= ry:
        return _ellipse_distance(rx, ry, dx, dy)
    return _ellipse_distance(ry, rx, dy, dx)

def _rounded_square_coverage(side: float, radius: float, px: float, py: float) -> float:
    half = side / 2
    qx, qy = abs(px - half) - (half - radius), abs(py - half) - (half - radius)
    outside = math.sqrt(max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) + min(max(qx, qy), 0.0) - radius
    return min(max(0.5 - outside, 0.0), 1.0)

def _rgb(hex_colour: str) -> tuple[int, int, int]:
    return int(hex_colour[1:3], 16), int(hex_colour[3:5], 16), int(hex_colour[5:7], 16)

def render(mark: Mark, palette: dict[str, str], size: int, *, opaque: bool) -> bytes:
    ring_px, accent_px = STROKES_PX[size]
    if size < FULL_MARK_FROM_PX:
        mark = tab_mark(mark)
    if opaque:
        # The touch icon: a square plate, the ring at TOUCH_RING_SHARE of the side.
        outer = max(shape.values[2] if shape.kind == "circle" else 0.0 for shape in mark.shapes)
        scale = size * TOUCH_RING_SHARE / (2 * outer)
    else:
        scale = size / mark.view
    centre = mark.view / 2
    plate, ring, accent = (_rgb(palette[key]) for key in ("plate", "ring", "accent"))
    shapes = [(shape, _rotation(shape.rotate)) for shape in mark.shapes]
    rows = bytearray()
    for j in range(size):
        rows.append(0)  # PNG filter type None
        for i in range(size):
            colour = [float(channel) for channel in plate]
            px = centre + (i + 0.5 - size / 2) / scale
            py = centre + (j + 0.5 - size / 2) / scale
            for shape, rotation in shapes:
                width = (accent_px if shape.accent else ring_px) / 2
                distance = _shape_distance(shape, rotation, px, py, (width + 1) / scale)
                if distance is None:
                    continue
                alpha = min(max(width - distance * scale + 0.5, 0.0), 1.0)
                if alpha:
                    paint = accent if shape.accent else ring
                    colour = [c * (1 - alpha) + p * alpha for c, p in zip(colour, paint)]
            pixel = [round(channel) for channel in colour]
            if opaque:
                rows.extend(pixel)
            else:
                cover = _rounded_square_coverage(size, size * CORNER, i + 0.5, j + 0.5)
                rows.extend(pixel + [round(cover * 255)])
    return bytes(rows)

# --- PNG and ICO -------------------------------------------------------------
# A fixed-Huffman deflate stream (RFC 1951 3.2.6) whose only matches repeat the pixel to the left or the row above.
# Its bytes do not depend on the host's zlib version.

_LENGTH_BASE = (3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59,
                67, 83, 99, 115, 131, 163, 195, 227, 258)
_LENGTH_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0)
_DIST_BASE = (1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769,
              1025, 1537, 2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577)
_DIST_EXTRA = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13)

class _Bits:
    def __init__(self) -> None:
        self.out = bytearray()
        self.value = 0
        self.count = 0

    def put(self, value: int, count: int) -> None:
        self.value |= value << self.count
        self.count += count
        while self.count >= 8:
            self.out.append(self.value & 0xFF)
            self.value >>= 8
            self.count -= 8

    def huffman(self, code: int, length: int) -> None:
        self.put(int(f"{code:0{length}b}"[::-1], 2), length)

    def finish(self) -> bytes:
        if self.count:
            self.out.append(self.value & 0xFF)
        return bytes(self.out)

def _literal(bits: _Bits, symbol: int) -> None:
    if symbol < 144:
        bits.huffman(0x30 + symbol, 8)
    elif symbol < 256:
        bits.huffman(0x190 + symbol - 144, 9)
    elif symbol < 280:
        bits.huffman(symbol - 256, 7)
    else:
        bits.huffman(0xC0 + symbol - 280, 8)

def _bucket(value: int, bases: tuple[int, ...]) -> int:
    index = 0
    while index + 1 < len(bases) and bases[index + 1] <= value:
        index += 1
    return index

def deflate(data: bytes, distances: tuple[int, ...]) -> bytes:
    """A zlib stream of `data`, matching only at the given back distances."""
    bits = _Bits()
    bits.put(0b011, 3)  # final block, fixed Huffman codes
    position = 0
    while position < len(data):
        best_length, best_distance = 0, 0
        for distance in distances:
            if distance > position:
                continue
            length = 0
            while (length < 258 and position + length < len(data)
                   and data[position + length] == data[position + length - distance]):
                length += 1
            if length > best_length:
                best_length, best_distance = length, distance
        if best_length >= 3:
            code = _bucket(best_length, _LENGTH_BASE)
            _literal(bits, 257 + code)
            bits.put(best_length - _LENGTH_BASE[code], _LENGTH_EXTRA[code])
            code = _bucket(best_distance, _DIST_BASE)
            bits.huffman(code, 5)
            bits.put(best_distance - _DIST_BASE[code], _DIST_EXTRA[code])
            position += best_length
        else:
            _literal(bits, data[position])
            position += 1
    _literal(bits, 256)
    # zlib header: deflate, 32 KiB window, no dictionary, check bits.
    return b"\x78\x01" + bits.finish() + struct.pack(">I", zlib.adler32(data))

def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

def png(size: int, rows: bytes, *, opaque: bool) -> bytes:
    channels = 3 if opaque else 4
    header = struct.pack(">IIBBBBB", size, size, 8, 2 if opaque else 6, 0, 0, 0)
    stream = deflate(rows, (channels, size * channels + 1))
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", stream) + _chunk(b"IEND", b"")

def ico(images: list[tuple[int, bytes]]) -> bytes:
    directory = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    body = b""
    for size, data in images:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        body += data
    return directory + body

# --- producer ----------------------------------------------------------------

def outputs() -> dict[Path, bytes]:
    mark, palette = read_mark(), read_palette()
    icons = [(size, png(size, render(mark, palette, size, opaque=False), opaque=False)) for size in ICO_SIZES]
    touch = png(TOUCH_SIZE, render(mark, palette, TOUCH_SIZE, opaque=True), opaque=True)
    return {FRONTEND / SVG_ASSET: svg_text(mark, palette).encode("utf-8"), FRONTEND / ICO_ASSET: ico(icons),
        FRONTEND / TOUCH_ASSET: touch}

def drift(produced: dict[Path, bytes] | None = None) -> list[str]:
    produced = outputs() if produced is None else produced
    return [path.relative_to(ROOT).as_posix() for path,
        data in produced.items() if not path.is_file() or path.read_bytes() != data]

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="fail if a committed icon differs")
    args = parser.parse_args(argv)
    produced = outputs()
    if args.check:
        stale = drift(produced)
        for name in stale:
            print(f"icon differs from its producer: {name}; re-run: python -m scripts.frontend.favicon",
                  file=sys.stderr)
        if not stale:
            print("ICONS CURRENT: " + ", ".join(path.relative_to(FRONTEND).as_posix() for path in produced))
        return 1 if stale else 0
    for path, data in produced.items():
        path.write_bytes(data)
    print("ICONS WRITTEN: " + ", ".join(path.relative_to(FRONTEND).as_posix() for path in produced))
    return 0

if __name__ == "__main__":
    os.umask(0o022)
    raise SystemExit(main())
