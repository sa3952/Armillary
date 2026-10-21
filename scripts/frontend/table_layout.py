"""Phone layout of the page tables, prepared at build time.

Two kinds of table:

* A table marked ``class="… stack-narrow"`` (few rows, long text: the roadmap,
  feature, privacy, home and security tables) is laid out on a phone as one
  labelled block per row.  Each body cell gets ``data-label`` with its column's
  header, read from the table's own ``<thead>``, so the stylesheet can show the
  header beside the value without the page repeating it.  ``display:block``
  drops a table's implicit roles in some browsers, so the table, its row
  groups, rows and cells are given their ARIA roles explicitly (the same
  pattern as the civil-time rule tables); the visible label is generated
  content the stylesheet gives an empty alternative text, so a screen reader
  hears each header once, as a column header.

* Every other table in a horizontal-scroll wrapper keeps its columns and
  scrolls sideways.  The build puts a hidden 「表格可左右捲動」 line before
  the wrapper; ``table-scroll.js`` shows it only while the table actually
  overflows its box.
"""

from __future__ import annotations

import html
import re

STACK_CLASS = "stack-narrow"
HINT_TEXT = "表格可左右捲動"
HINT = f'<p class="scroll-hint" hidden>{HINT_TEXT}</p>'
SCRIPT = '<script src="/zh-TW/table-scroll.js?v={{assets}}" defer></script>'

_WRAPPERS = ("ar-scroll", "spec-scroll", "mansion-scroll", "validation-scroll")
_TABLE = re.compile(r"<table\b(?P<attrs>[^>]*)>(?P<inner>.*?)</table>", re.S)
_CLASS = re.compile(r'\sclass="(?P<value>[^"]*)"')
_THEAD = re.compile(r"<thead\b[^>]*>(?P<inner>.*?)</thead>", re.S)
_TH = re.compile(r"<th\b[^>]*>(?P<inner>.*?)</th>", re.S)
_TAG = re.compile(r"<[^>]+>")
_ROW = re.compile(r"<tr\b(?P<attrs>[^>]*)>(?P<inner>.*?)</tr>", re.S)
_CELL = re.compile(r"<(?P<tag>td|th)\b(?P<attrs>[^>]*)>", re.S)
_WRAPPER = re.compile(
    r'(?P<indent>[ \t]*)<div class="(?P<cls>[^"]*)"[^>]*>\s*<table\b(?P<attrs>[^>]*)>'
)


def _classes(attrs: str) -> list[str]:
    match = _CLASS.search(attrs)
    return match.group("value").split() if match else []


def _with_attr(attrs: str, name: str, value: str) -> str:
    if re.search(rf"\s{name}=", attrs):
        return attrs
    return f'{attrs} {name}="{value}"'


def _header_text(cell: str) -> str:
    return html.escape(html.unescape(" ".join(_TAG.sub("", cell).split())), quote=True)


def _stack(match: re.Match) -> str:
    attrs, inner = match.group("attrs"), match.group("inner")
    if STACK_CLASS not in _classes(attrs):
        return match.group(0)
    if re.search(r"\s(?:colspan|rowspan)=", inner):
        raise ValueError("a stacked table cannot span cells: each cell needs exactly one column header")
    head = _THEAD.search(inner)
    labels = [_header_text(cell) for cell in _TH.findall(head.group("inner"))] if head else []

    def row(row_match: re.Match) -> str:
        in_head = head is not None and head.start() <= row_match.start() < head.end()
        column = 0

        def cell(cell_match: re.Match) -> str:
            nonlocal column
            tag, cell_attrs = cell_match.group("tag"), cell_match.group("attrs")
            if in_head:
                cell_attrs = _with_attr(_with_attr(cell_attrs, "scope", "col"), "role", "columnheader")
            else:
                role = "rowheader" if tag == "th" else "cell"
                cell_attrs = _with_attr(cell_attrs, "role", role)
                if labels:
                    if column >= len(labels):
                        raise ValueError("a stacked table's row has more cells than its header")
                    cell_attrs = _with_attr(cell_attrs, "data-label", labels[column])
            column += 1
            return f"<{tag}{cell_attrs}>"

        cells = _CELL.sub(cell, row_match.group("inner"))
        if labels and not in_head and column != len(labels):
            raise ValueError("a stacked table's row has fewer cells than its header")
        return f"<tr{_with_attr(row_match.group('attrs'), 'role', 'row')}>{cells}</tr>"

    inner = _ROW.sub(row, inner)
    inner = re.sub(r"<(thead|tbody)\b(?![^>]*\srole=)", r'<\1 role="rowgroup"', inner)
    return f"<table{_with_attr(attrs, 'role', 'table')}>{inner}</table>"


def _hint(match: re.Match) -> str:
    wrapper = set(match.group("cls").split())
    if not wrapper.intersection(_WRAPPERS) or STACK_CLASS in _classes(match.group("attrs")):
        return match.group(0)
    return f'{match.group("indent")}{HINT}\n{match.group(0)}'


def fill(body: str) -> str:
    """Stack-marked tables labelled; a scroll hint before every other scrolling
    table, and the script that shows it when the page has one."""

    if HINT_TEXT in body or "table-scroll.js" in body:
        raise ValueError("a page writes the scroll hint or its script itself; the build adds them")
    body = _TABLE.sub(_stack, body)
    body = _WRAPPER.sub(_hint, body)
    if HINT in body:
        body = body.rstrip("\n") + "\n" + SCRIPT
    return body
