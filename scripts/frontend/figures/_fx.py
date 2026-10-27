"""The article figure component: markup helpers and the checks every figure passes.

A figure is one `<figure data-fx>` with two drawings of the same content, a wide one (`svg.fx-wide`, viewBox 880 or 600
wide) and one recomposed for a phone (`svg.fx-narrow`, 340 wide).  `figures.css` shows one by the figure's own width,
never by scaling; print takes the wide one.  Text sizes come from the classes `fx-t` and `fx-small` alone, read from
`figures.css` (`text_sizes`) so the minimum font size is checked against the sheet the browser receives.

Interaction only chooses among drawings already in the page (`data-fx-variant`, `data-fx-step`, `data-fx-key`);
`article-figures.js` computes nothing.  Without it the default variant, the caption and the table are the figure.

Every number in a drawing, sentence or table must come through `Bound.num` or `Bound.scale`; `problems()` refuses any
other digit, so a number typed by hand fails `figures --check`.

Glyphs are the Noto outlines in chart-glyphs.js (SIL OFL 1.1), drawn as `<use>` of a `<symbol>` in the shared
`GLYPH_FILE`, which carries the copyright and licence text in its `<metadata>`.  The page's own sprite holds hatch
patterns only.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import math
import re
from typing import Any

from ._common import ROOT

WIDE = 880
WIDE_SQUARE = 600
NARROW = 340
WIDTHS = {"fx-wide": (WIDE, WIDE_SQUARE), "fx-narrow": (NARROW,)}
TEXT_CLASSES = ("fx-t", "fx-small")
# The narrowest a drawing is shown at the named viewports (wide: 824 px article column at 1440, hero 878; narrow: 375
# and 320 px).  frontend/tests/e2e/article-figures.spec.cjs measures the rendered sizes.
RENDERED = {"fx-wide": {"1440": 824.0}, "fx-narrow": {"375": 341.0, "320": 286.0}}
# Minimum rendered text size in CSS px per layout and viewport; 320 px phones accept the smaller size.
MIN_PX = {("fx-wide", "1440"): 13.0, ("fx-narrow", "375"): 12.0, ("fx-narrow", "320"): 10.0}

STYLESHEET = ROOT / "scripts" / "frontend" / "styles" / "figures.css"
GLYPH_SOURCE = ROOT / "scripts" / "frontend" / "scripts" / "chart-glyphs.js"
GLYPH_FILE = "zh-TW/fx-glyphs.svg"
_GLYPH = re.compile(
    r'^    (?P<key>[a-z_]+): Object\.freeze\(\{ codepoint: "U\+[0-9A-F]+", '
    r'bbox: Object\.freeze\(\[(?P<bbox>[-0-9., ]+)\]\),\n      d: "(?P<d>[^"]+)" \}\),$',
    re.MULTILINE,
)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

def f(value: float) -> str:
    text = f"{value:.1f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text

def text_width(text: str, size: float = 1.0, latin: float = 0.55) -> float:
    """A generous estimate of a label's drawn width: a CJK character is one em, anything else `latin` em."""
    return sum(size if ord(ch) > 0x2E7F else latin * size for ch in text)

def wheel_point(cx: float, cy: float, r: float, degrees: float) -> tuple[float, float]:
    return cx + r * math.cos(math.radians(degrees)), cy - r * math.sin(math.radians(degrees))

# --- numbers -------------------------------------------------------------------

@dataclass
class Bound:
    """The numbers a figure may print: values read from the product, and the axis labels of its scale."""

    values: set[str] = field(default_factory=set)

    def num(self, text: str) -> str:
        self.values.add(text)
        return text

    def scale(self, text: str) -> str:
        self.values.add(text)
        return text

    def label(self, text: str) -> str:
        """A name that holds digits: a source (「Lilly 1647 p.113」), a figure or table number."""
        self.values.add(text)
        return text

    def tokens(self) -> set[str]:
        return {token for text in self.values for token in _NUMBER.findall(text)}

# --- SVG primitives ------------------------------------------------------------

def text(x: float, y: float, value: str, cls: str = "fx-t", anchor: str | None = None) -> str:
    if not any(name in cls.split() for name in TEXT_CLASSES):
        raise ValueError(f"text without a size class: {cls!r}")
    a = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{f(x)}" y="{f(y)}" class="{cls}"{a}>{escape(value)}</text>'

def line(x1: float, y1: float, x2: float, y2: float, cls: str) -> str:
    return f'<line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" class="{cls}"/>'

def rect(x: float, y: float, w: float, h: float, cls: str = "") -> str:
    attr = f' class="{cls}"' if cls else ""
    return f'<rect x="{f(x)}" y="{f(y)}" width="{f(max(w, 0))}" height="{f(max(h, 0))}"{attr}/>'

def circle(cx: float, cy: float, r: float, cls: str) -> str:
    return f'<circle cx="{f(cx)}" cy="{f(cy)}" r="{f(r)}" class="{cls}"/>'

def path(d: str, cls: str) -> str:
    return f'<path d="{d}" class="{cls}"/>'

def plate(width: float, height: float) -> str:
    return rect(1, 1, width - 2, height - 2, "fx-frame") + rect(6, 6, width - 12, height - 12, "fx-frame-in")

def glyphs() -> dict[str, tuple[tuple[float, float, float, float], str]]:
    source = GLYPH_SOURCE.read_text(encoding="utf-8")
    found = {}
    for match in _GLYPH.finditer(source):
        x0, y0, x1, y1 = (float(v) for v in match["bbox"].split(","))
        found[match["key"]] = ((x0, y0, x1, y1), match["d"])
    if "sun" not in found or "venus" not in found:
        raise RuntimeError(f"no glyph outlines read from {GLYPH_SOURCE.name}")
    return found

def glyph(key: str, cx: float, cy: float, size: float, cls: str = "fx-gl") -> str:
    (x0, y0, x1, y1), _ = glyphs()[key]
    w, h = x1 - x0, y1 - y0
    scale = size / max(w, h)
    return (f'<use href="/{GLYPH_FILE}?v={{{{assets}}}}#fx-gl-{key}" x="{f(cx - w * scale / 2)}" y="{f(cy - h * scale / 2)}" '
            f'width="{f(w * scale)}" height="{f(h * scale)}" class="{cls}"/>')

def _licence_text() -> str:
    from scripts.frontend import chart_glyphs
    texts = [p.read_text(encoding="utf-8") for p in chart_glyphs.LICENCES]
    bodies = {"\n".join(t.splitlines()[1:]) for t in texts}
    if len(bodies) != 1:
        raise RuntimeError("the OFL copies differ beyond their copyright line")
    return "\n".join([t.splitlines()[0] for t in texts] + bodies.pop().splitlines())

def defs(keys: tuple[str, ...]) -> str:
    """The page's sprite placeholder that `build_pages` replaces with `sprite()`; glyphs go into `glyph_file`."""
    return "{{fx_defs" + (":" + " ".join(keys) if keys else "") + "}}"

def sprite() -> str:
    patterns = (
        # single hatch: in the beams; cross hatch: combust; dots: background of an enlargement
        '<pattern id="fx-h1" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="5" class="fx-hp"/></pattern>'
        '<pattern id="fx-h2" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        '<line x1="0" y1="0" x2="0" y2="4" class="fx-hp"/><line x1="0" y1="0" x2="4" y2="0" class="fx-hp"/></pattern>'
        '<pattern id="fx-dots" width="4" height="4" patternUnits="userSpaceOnUse">'
        '<circle cx="2" cy="2" r=".7" class="fx-hpf"/></pattern>'
    )
    return f'<svg class="fx-sprite" aria-hidden="true" focusable="false"><defs>{patterns}</defs></svg>'

def glyph_file(keys: Iterable[str]) -> str:
    """The shared glyph file: a `<symbol>` per key in chart-glyphs.js order, with the glyphs' copyright and licence."""
    outlines = glyphs()
    wanted = set(keys)
    unknown = sorted(wanted - set(outlines))
    if unknown:
        raise ValueError(f"no glyph outline for {unknown}")
    symbols = []
    for key in (key for key in outlines if key in wanted):
        (x0, y0, x1, y1), d = outlines[key]
        symbols.append(f'<symbol id="fx-gl-{key}" viewBox="{f(x0)} {f(y0)} {f(x1 - x0)} {f(y1 - y0)}">'
                       f'<path d="{d}"/></symbol>')
    licence = escape(
        "Planet and sign glyphs: outlines from chart-glyphs.js, a Modified Version of the "
        "Noto Sans Symbols, Noto Sans Symbols 2 and Noto Sans fonts, distributed under the same licence.\n"
        + _licence_text(), quote=False)
    return (f'<svg xmlns="http://www.w3.org/2000/svg"><metadata>{licence}</metadata>'
            f'<defs>{"".join(symbols)}</defs></svg>\n')

# --- the figure ----------------------------------------------------------------

@dataclass(frozen=True)
class Note:
    """One sentence the readout shows, for a key or a step, in one variant or all (`variant=None`)."""

    key: str | None
    variant: str | None
    text: str
    step: int | None = None

@dataclass(frozen=True)
class FigureArt:

    wide: str
    narrow: str
    notes: list[Note]
    idle: str

    @classmethod
    def drawn(cls, draw: Callable[..., str], *args: Any, notes: list[Note] | None = None, idle: str = "") -> FigureArt:
        return cls(draw("fx-wide", *args), draw("fx-narrow", *args), notes or [], idle)

@dataclass(frozen=True)
class FigureControls:

    variants: tuple[tuple[str, str], ...] = ()
    switch_label: str = ""
    steps: int = 0
    default_step: int = 0
    scrub_label: str = ""

def figure(*, fid: str, title: str, caption: str, art: FigureArt, controls: FigureControls = FigureControls(),
    table: str = "", hero: bool = False, bound: Bound | None = None) -> str:
    """One `<figure data-fx>`.  `caption` is trusted markup (a `<b>` number then text); everything else is escaped.

    `variants` are (id, button label), the first the default.  `steps` is the number of precomputed slider steps (groups
    and notes carry `data-fx-step="0"` … `"steps - 1"`), `default_step` the one drawn without script.  With `bound`,
    the figure must pass `require_clean`."""
    wide, narrow, notes, idle = art.wide, art.narrow, art.notes, art.idle
    variants, switch_label = controls.variants, controls.switch_label
    steps, default_step, scrub_label = controls.steps, controls.default_step, controls.scrub_label
    default = variants[0][0] if variants else None
    attrs = f' data-fx-default-variant="{default}"' if default else ""
    if steps:
        attrs += f' data-fx-default-step="{default_step}"'
    cls = "fx ar-fig ar-hero" if hero else "fx ar-fig"
    out = [f'<figure class="{cls}" id="{fid}" data-fx{attrs}>']
    if variants:
        buttons = "".join(
            f'<button type="button" data-fx-set="{key}" aria-pressed="{"true" if key == default else "false"}">'
            f'{escape(label)}</button>' for key, label in variants)
        out.append(f'<div class="fx-switch" role="group" aria-label="{escape(switch_label)}" data-fx-switch hidden>'
                   f'{buttons}</div>')
    if steps:
        out.append(f'<div class="fx-scrub" data-fx-scrub-row hidden><label for="{fid}-scrub">{escape(scrub_label)}</label>'
                   f'<input id="{fid}-scrub" type="range" min="0" max="{steps - 1}" step="1" value="{default_step}" '
                   f'data-fx-scrub></div>')
    out.append(f'<div class="fx-art" role="group" aria-labelledby="{fid}-title {fid}-cap">')
    out.append(f'<span class="fx-title" id="{fid}-title">{escape(title)}</span>')
    out += [_marks_as_images(wide), _marks_as_images(narrow), "</div>"]
    # No notes and no slider: no readout (article-figures.js reveals every readout, so it would show an empty box).
    if notes or steps:
        out.append(f'<p class="fx-readout" data-fx-readout aria-live="polite" hidden>{escape(idle)}</p>')
        items = "".join(
            "<li" + (f' data-fx-key="{n.key}"' if n.key else "") + (f' data-fx-step="{n.step}"' if n.step is not None else "")
            + (f' data-fx-variant="{n.variant}"' if n.variant else "")
            + f">{escape(n.text)}</li>" for n in notes)
        out.append(f"<ul data-fx-notes hidden>{items}</ul>")
    # HTML lets nothing follow a figcaption that is not the first child, so the table comes before it.
    if table:
        out.append(_data_table(fid, table))
    out.append(f'<figcaption id="{fid}-cap">{caption}</figcaption>')
    out.append("</figure>")
    markup = "\n".join(out)
    if bound is not None:
        require_clean(markup, bound)
    return markup

_EMPTY_HEADER = re.compile(r"<th\b[^>]*>\s*</th>")

def data_table(columns: str | Iterable[str], rows: str | Iterable[str], summary: str = "圖中的數字（表格）") -> str:
    """A figure's numbers as an fx-data fold; `columns` may be one string (the header row's cells)."""
    head = columns if isinstance(columns, str) else "".join(f'<th scope="col">{label}</th>' for label in columns)
    body = rows if isinstance(rows, str) else "".join(rows)
    return (f'<details class="fx-data"><summary>{summary}</summary><div class="ar-scroll">'
            f'<table class="ar-table fx-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
            '</div></details>')

def _data_table(fid: str, table: str) -> str:
    """The figure's numbers as a table under a summary.  Its scroll frame is a named, focusable region so a keyboard can
    scroll it; no header cell is empty (a screen reader would announce a blank heading)."""
    if _EMPTY_HEADER.search(table):
        raise ValueError(f"{fid}: a table header cell is empty")
    if table.count('<details class="fx-data"><summary>') != 1 or table.count('<div class="ar-scroll">') != 1:
        raise ValueError(f"{fid}: the figure's table is one fx-data fold with one ar-scroll frame")
    return (table .replace('<details class="fx-data"><summary>',
        f'<details class="fx-data"><summary id="{fid}-data">') .replace('<div class="ar-scroll">',
        f'<div class="ar-scroll" tabindex="0" role="region" aria-labelledby="{fid}-data">'))

_FOCUSABLE_MARK = re.compile(r'<g (?![^>]*\brole=)([^>]*\btabindex="0"[^>]*)>')

def _marks_as_images(drawing: str) -> str:
    """Each focusable mark is an `img` named by aria-label: an SVG `<g>` has no role and ARIA prohibits a label on it."""
    return _FOCUSABLE_MARK.sub(r'<g \1 role="img">', drawing)

def svg_open(layout: str, width: float, height: float, fid: str) -> str:
    # role=group, not img: an img would hide the focusable marks inside it.
    return f'<svg class="{layout}" viewBox="0 0 {f(width)} {f(height)}" role="group" aria-labelledby="{fid}-title">'

def variant_group(variant: str, default: str, body: str) -> str:
    off = "" if variant == default else " fx-off"
    return f'<g class="fx-v{off}" data-fx-variant="{variant}">{body}</g>'

def step_group(step: int, default: int, body: str) -> str:
    off = "" if step == default else " fx-off"
    return f'<g class="fx-s{off}" data-fx-step="{step}">{body}</g>'

# --- checks --------------------------------------------------------------------

class _Reader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, dict]] = []
        self.svgs: list[dict] = []
        self.ids: list[str] = []
        self.offences: list[str] = []
        self.texts: list[tuple[str, str, str]] = []  # (layout, classes, text)
        self.keyed: list[dict] = []
        self.notes: list[tuple[str, str | None]] = []
        self.note_texts: list[str] = []
        self.variant_groups: list[tuple[str, bool]] = []
        self.step_groups: list[tuple[str, bool]] = []
        self.step_notes: list[tuple[str, str | None]] = []
        self.scrub: dict = {}
        self.buttons: list[tuple[str, str]] = []
        self.figure: dict = {}
        self.caption = ""
        self.table_text: list[str] = []
        self.readout = ""

    def _inside(self, tag: str) -> dict | None:
        for name, attributes in reversed(self.stack):
            if name == tag:
                return attributes
        return None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name in a:
            if name == "style" or name.startswith("on") or name == "font-size":
                self.offences.append(f"<{tag} {name}=…>")
        if "id" in a:
            self.ids.append(a["id"])
        if tag == "figure":
            self.figure = a
        if tag == "svg":
            self.svgs.append(a)
        if "data-fx-key" in a and self._inside("ul") is None:
            self.keyed.append({"tag": tag, **a})
        if "data-fx-step" in a and tag == "g":
            self.step_groups.append((a["data-fx-step"], "fx-off" in a.get("class", "").split()))
        if tag == "input" and "data-fx-scrub" in a:
            self.scrub = a
        if "data-fx-variant" in a and tag == "g":
            self.variant_groups.append((a["data-fx-variant"], "fx-off" in a.get("class", "").split()))
        if tag == "button" and "data-fx-set" in a:
            self.buttons.append((a["data-fx-set"], a.get("aria-pressed", "")))
        if tag == "li" and self._inside("ul") is not None and "data-fx-notes" in (self._inside("ul") or {}):
            if "data-fx-step" in a:
                self.step_notes.append((a["data-fx-step"], a.get("data-fx-variant")))
            else:
                self.notes.append((a.get("data-fx-key", ""), a.get("data-fx-variant")))
        if tag not in ("path", "line", "rect", "circle", "use", "br", "img", "input"):
            self.stack.append((tag, a))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data.strip():
            return
        text_attrs = self._inside("text")
        svg = self._inside("svg")
        if text_attrs is not None and svg is not None:
            self.texts.append((svg.get("class", ""), text_attrs.get("class", ""), data))
        elif self._inside("li") is not None and self._inside("ul") is not None:
            self.note_texts.append(data)
        elif self._inside("figcaption") is not None:
            self.caption += data
        elif self._inside("table") is not None:
            self.table_text.append(data)
        elif "data-fx-readout" in (self._inside("p") or {}):
            self.readout += data

def text_sizes(stylesheet: Path = STYLESHEET) -> dict[tuple[str, str], float]:
    css = stylesheet.read_text(encoding="utf-8")
    sizes = {}
    for layout in WIDTHS:
        for cls in TEXT_CLASSES:
            match = re.search(rf"\.{layout} \.{cls}\{{font-size:([0-9.]+)px\}}", css)
            if match:
                sizes[(layout, cls)] = float(match[1])
    return sizes

def problems(markup: str, bound: Bound, stylesheet: Path = STYLESHEET) -> list[str]:
    r = _Reader()
    r.feed(markup)
    out: list[str] = []
    fid = r.figure.get("id", "?")
    if "data-fx" not in r.figure:
        out.append(f"{fid}: not a figure[data-fx]")
    out += [f"{fid}: attribute the served CSP or the size rule forbids: {o}" for o in r.offences]
    dupes = sorted({i for i in r.ids if r.ids.count(i) > 1})
    if dupes:
        out.append(f"{fid}: ids used twice: {dupes}")
    layouts = [s.get("class", "") for s in r.svgs]
    if layouts.count("fx-wide") != 1 or layouts.count("fx-narrow") != 1:
        out.append(f"{fid}: needs exactly one fx-wide and one fx-narrow drawing, has {layouts}")
    for s in r.svgs:
        layout = s.get("class", "")
        width = float(s.get("viewbox", "0 0 0 0").split()[2])
        if layout in WIDTHS and width not in WIDTHS[layout]:
            out.append(f"{fid}: {layout} viewBox width {width:g} is not one of {WIDTHS[layout]}")
    if not r.caption.strip():
        out.append(f"{fid}: no caption")
    if f'id="{fid}-title"' not in markup or 'class="fx-art" role="group"' not in markup:
        out.append(f"{fid}: the drawing has no text alternative")
    sizes = text_sizes(stylesheet)
    widths = {s.get("class", ""): float(s.get("viewbox", "0 0 1 0").split()[2]) for s in r.svgs}
    for layout, classes, value in r.texts:
        names = classes.split()
        cls = "fx-small" if "fx-small" in names else "fx-t"
        size = sizes.get((layout, cls))
        if size is None:
            out.append(f"{fid}: figures.css sets no size for .{layout} .{cls}")
            continue
        width = widths.get(layout, NARROW)
        for viewport, rendered in RENDERED[layout].items():
            px = size * min(rendered, width) / width
            if px < MIN_PX[(layout, viewport)]:
                out.append(f"{fid}: {value!r} renders at {px:.1f} px in {layout} at {viewport} px")
    # Each key has one focusable, labelled mark; other elements with its key only light up with it.
    focusable = {item["data-fx-key"] for item in r.keyed if item.get("tabindex") == "0" and item.get("aria-label")}
    for key in sorted({item["data-fx-key"] for item in r.keyed} - focusable):
        out.append(f"{fid}: key {key!r} has no focusable mark with a label")
    for item in r.keyed:
        if item.get("tabindex") == "0" and item.get("role") != "img":
            out.append(f"{fid}: the focusable mark {item['data-fx-key']!r} has no role (its label needs role=img)")
    keys = sorted({k["data-fx-key"] for k in r.keyed})
    variants = [key for key, _ in r.buttons]
    choices: list[str | None] = [*variants] or [None]
    pressed = [key for key, value in r.buttons if value == "true"]
    default = r.figure.get("data-fx-default-variant")
    if variants:
        if pressed != [default]:
            out.append(f"{fid}: the pressed button {pressed} is not the default variant {default!r}")
        drawn = {v for v, _ in r.variant_groups}
        if drawn != set(variants):
            out.append(f"{fid}: variants drawn {sorted(drawn)} != switch {variants}")
        for variant, off in r.variant_groups:
            if off != (variant != default):
                out.append(f"{fid}: variant {variant!r} is {'hidden' if off else 'shown'} without script")
    for key in keys:
        for choice in choices:
            if (key, choice) not in r.notes:
                out.append(f"{fid}: no sentence for key {key!r}" + (f", variant {choice!r}" if choice else ""))
    if r.scrub:
        last = int(r.scrub.get("max", "-1"))
        default_step = r.figure.get("data-fx-default-step")
        steps = [str(i) for i in range(last + 1)]
        if r.scrub.get("value") != default_step or default_step not in steps:
            out.append(f"{fid}: the slider starts at {r.scrub.get('value')!r}, the default step is {default_step!r}")
        if sorted({s for s, _ in r.step_groups}, key=int) != steps:
            out.append(f"{fid}: steps drawn {sorted({s for s, _ in r.step_groups})} != slider 0…{last}")
        for step, off in r.step_groups:
            if off != (step != default_step):
                out.append(f"{fid}: step {step!r} is {'hidden' if off else 'shown'} without script")
        for step in steps:
            for choice in choices:
                if (step, choice) not in r.step_notes and (step, None) not in r.step_notes:
                    out.append(f"{fid}: no sentence for step {step}" + (f", variant {choice!r}" if choice else ""))
    elif r.step_groups:
        out.append(f"{fid}: steps drawn without a slider")
    if (keys or r.scrub) and not r.readout.strip():
        out.append(f"{fid}: keys but no readout")
    allowed = bound.tokens()
    for value in [t for _, _, t in r.texts] + r.note_texts + [r.caption] + r.table_text:
        for token in _NUMBER.findall(value):
            if token not in allowed:
                out.append(f"{fid}: {token!r} in {value!r} is not a number the generator read")
    return out

def require_clean(markup: str, bound: Bound) -> None:
    found = problems(markup, bound)
    if found:
        raise RuntimeError("figure check: " + "; ".join(found))
