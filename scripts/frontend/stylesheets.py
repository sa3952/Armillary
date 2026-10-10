"""Per-page stylesheet bundles, built from the readable sources in `styles/`.

Every page used to load tokens.css and the whole of page.css (131 KB, most of
it the other pages' layouts) as two render-blocking requests.  A page now loads
one bundle: tokens.css, then the parts of page.css its audience needs, then
calculate.css on the calculator or article.css on an article, all in source
order, so the cascade among the rules a page receives is the cascade it always
had.

page.css says which pages need which part with marker comments alone on a
top-level line:

    /* @pages home features */      the rules below go to these audiences
    /* @pages all */                the rules below go to every page

Rules before the first marker go to every page.  An audience is a surface key
from frontend/surfaces.json, `blog-article` (every article: a new article
needs no marker) or `not-found` (the error page).  `build_pages` writes each
bundle to `frontend/zh-TW/style/<audience>.css` and links it from the page;
`check_bundle_coverage` refuses a page whose markup or scripts name a class or
id that page.css styles in a part the page does not receive.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from pathlib import Path
from typing import Iterable, Mapping

STYLES = Path(__file__).resolve().parent / "styles"
DESIGN_SHEET = "tokens.css"
PAGE = "page.css"
CALCULATOR = "calculate.css"
ARTICLE = "article.css"
# Where the bundles live, relative to frontend/ and as served.
BUNDLE_DIRECTORY = "zh-TW/style"
SHARED = "all"
ARTICLE_AUDIENCE = "blog-article"
NOT_FOUND_AUDIENCE = "not-found"
CALCULATOR_AUDIENCE = "calculate"

_MARKER_START = re.compile(r"/\*\s*@pages\b")
_MARKER = re.compile(r"/\* @pages ((?:[a-z][a-z0-9-]*)(?: [a-z][a-z0-9-]*)*) \*/")


@dataclass(frozen=True)
class Item:
    """One top-level construct of a stylesheet, with its exact source text."""

    kind: str  # "comment", "rule" or "at"
    text: str
    prelude: str = ""  # selector list, or the at-rule's name and condition
    children: tuple["Item", ...] = ()


def _skip_string(css: str, index: int) -> int:
    quote = css[index]
    index += 1
    while index < len(css):
        char = css[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if char == "\n":
            raise ValueError("unterminated string in stylesheet")
        index += 1
    raise ValueError("unterminated string in stylesheet")


def _skip_comment(css: str, index: int) -> int:
    end = css.find("*/", index + 2)
    if end < 0:
        raise ValueError("unterminated comment in stylesheet")
    return end + 2


def _block_start(text: str) -> int:
    """The index of the `{` that opens the block of a rule or at-rule."""

    index = 0
    while index < len(text):
        if text[index] in "\"'":
            index = _skip_string(text, index)
        elif text.startswith("/*", index):
            index = _skip_comment(text, index)
        elif text[index] == "{":
            return index
        else:
            index += 1
    raise ValueError("rule without a block")


def _block_end(css: str, index: int) -> int:
    """The index just past the `}` that closes the block opened at `index`."""

    depth = 0
    while index < len(css):
        char = css[index]
        if char in "\"'":
            index = _skip_string(css, index)
            continue
        if css.startswith("/*", index):
            index = _skip_comment(css, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index + 1
            if depth < 0:
                break
        index += 1
    raise ValueError("unbalanced braces in stylesheet")


def parse(css: str) -> list[Item]:
    """Split a stylesheet into its top-level comments, rules and at-rules.

    The source must be plain CSS of the kind these sheets use: rules, comments,
    and block at-rules (@media, @keyframes, @supports); a statement at-rule
    (@import, @charset) or a stray token is refused rather than guessed at.
    """

    items: list[Item] = []
    index = 0
    while True:
        while index < len(css) and css[index].isspace():
            index += 1
        if index >= len(css):
            return items
        if css.startswith("/*", index):
            end = _skip_comment(css, index)
            items.append(Item("comment", css[index:end]))
            index = end
            continue
        start = index
        while index < len(css) and css[index] not in "{};":
            if css[index] in "\"'":
                index = _skip_string(css, index)
            elif css.startswith("/*", index):
                index = _skip_comment(css, index)
            else:
                index += 1
        if index >= len(css) or css[index] != "{":
            raise ValueError(f"unsupported stylesheet construct at offset {start}")
        prelude = css[start:index].strip()
        end = _block_end(css, index)
        text = css[start:end]
        if prelude.startswith("@"):
            name = prelude.split(None, 1)[0].lower()
            body = css[index + 1:end - 1]
            children = tuple(parse(body)) if name in {"@media", "@supports"} else ()
            items.append(Item("at", text, prelude, children))
        else:
            items.append(Item("rule", text, prelude))
        index = end


def marker_audiences(item: Item) -> frozenset[str] | None:
    """The audiences a marker comment names, or None for any other item."""

    if item.kind != "comment":
        return None
    match = _MARKER.fullmatch(item.text)
    return frozenset(match.group(1).split()) if match else None


def regions(items: Iterable[Item]) -> list[tuple[frozenset[str], list[Item]]]:
    """The items of page.css grouped under the audiences their marker names."""

    current = frozenset({SHARED})
    grouped: list[tuple[frozenset[str], list[Item]]] = [(current, [])]
    for item in items:
        audiences = marker_audiences(item)
        if audiences is not None:
            if SHARED in audiences and len(audiences) > 1:
                raise ValueError(f"marker names `all` together with other audiences: {item.text}")
            current = audiences
            grouped.append((current, []))
            continue
        if item.kind == "comment" and _MARKER_START.match(item.text):
            raise ValueError(f"malformed @pages marker: {item.text!r}")
        for child in item.children:
            if child.kind == "comment" and _MARKER_START.match(child.text):
                raise ValueError("an @pages marker must stand at the top level, not inside an at-rule")
        grouped[-1][1].append(item)
    return [(audiences, members) for audiences, members in grouped if members]


def audience_of(row: Mapping[str, object]) -> str:
    """The stylesheet audience of a surfaces.json row."""

    if isinstance(row.get("article"), dict):
        return ARTICLE_AUDIENCE
    if "status" in row:
        return NOT_FOUND_AUDIENCE
    return str(row["key"])


def bundle_path(audience: str) -> str:
    return f"{BUNDLE_DIRECTORY}/{audience}.css"


def _source(name: str, styles: Path) -> str:
    return (styles / name).read_text(encoding="utf-8")


def page_items_for(audience: str, styles: Path = STYLES) -> list[Item]:
    return _items_for(audience, regions(parse(_source(PAGE, styles))))


def _items_for(audience: str, grouped: list[tuple[frozenset[str], list[Item]]]) -> list[Item]:
    chosen: list[Item] = []
    for audiences, members in grouped:
        if SHARED in audiences or audience in audiences:
            chosen.extend(members)
    return chosen


def declared_audiences(styles: Path = STYLES) -> set[str]:
    named: set[str] = set()
    for audiences, _members in regions(parse(_source(PAGE, styles))):
        named |= audiences
    return named - {SHARED}


def bundle_source(audience: str, styles: Path = STYLES) -> str:
    """tokens.css, the page.css parts for `audience`, and calculate.css on the
    calculator or article.css on an article, readable: the order the separate
    <link>s used to give them."""

    parts = [_source(DESIGN_SHEET, styles).strip()]
    parts.extend(item.text for item in page_items_for(audience, styles))
    if audience == CALCULATOR_AUDIENCE:
        parts.append(_source(CALCULATOR, styles).strip())
    elif audience == ARTICLE_AUDIENCE:
        parts.append(_source(ARTICLE, styles).strip())
    return "\n".join(parts) + "\n"


def build_bundle(audience: str, styles: Path = STYLES) -> str:
    """The bundle as served: `bundle_source` minified."""

    return minify(bundle_source(audience, styles)) + "\n"


def build_bundles(rows: Iterable[Mapping[str, object]], styles: Path = STYLES) -> dict[str, str]:
    """Every bundle the rows need, keyed by its path under frontend/."""

    audiences = {audience_of(row) for row in rows}
    unknown = declared_audiences(styles) - audiences
    if unknown:
        raise ValueError(f"page.css names audiences no page has: {sorted(unknown)}")
    return {bundle_path(audience): build_bundle(audience, styles) for audience in sorted(audiences)}


# --- coverage: a page that names a styled class must receive its rule ---------

_FUNCTIONAL_PSEUDO = re.compile(r":(?:not|is|where|has|nth-child|nth-last-child|nth-of-type|nth-last-of-type)\(")
_SELECTOR_TOKEN = re.compile(r"([.#])(-?[A-Za-z_][A-Za-z0-9_-]*)")
_ATTRIBUTE = re.compile(r"\[[^\]]*\]")


def _without_functional_pseudos(selector: str) -> str:
    """Drop :not(...), :is(...) and the like with their arguments: what they
    require is not a plain conjunction, so leaving them out only widens a match."""

    out = []
    index = 0
    while index < len(selector):
        match = _FUNCTIONAL_PSEUDO.match(selector, index)
        if match:
            depth = 1
            index = match.end()
            while index < len(selector) and depth:
                depth += {"(": 1, ")": -1}.get(selector[index], 0)
                index += 1
            continue
        out.append(selector[index])
        index += 1
    return "".join(out)


def split_selector_list(prelude: str) -> list[str]:
    parts, depth, start = [], 0, 0
    for index, char in enumerate(prelude):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(prelude[start:index])
            start = index + 1
    parts.append(prelude[start:])
    return [part.strip() for part in parts]


def required_names(selector: str) -> frozenset[str]:
    """The class and id names an element tree must contain for `selector` to
    match anything (attribute values and negations are not requirements)."""

    plain = _without_functional_pseudos(_ATTRIBUTE.sub("", selector))
    return frozenset(sigil + name for sigil, name in _SELECTOR_TOKEN.findall(plain))


def style_rules(items: Iterable[Item]) -> Iterable[Item]:
    for item in items:
        if item.kind == "rule":
            yield item
        elif item.kind == "at":
            yield from style_rules(item.children)


def _present(name: str, names: frozenset[str] | set[str]) -> bool:
    """A name is present when named exactly, or when a script names a prefix
    ending in `-` (`"sd-at-" + n` may build any `sd-at-*`)."""

    return name in names or any(
        other.endswith("-") and name.startswith(other) for other in names
    )


def could_match(rule: Item, names: frozenset[str] | set[str]) -> bool:
    return any(
        all(_present(name, names) for name in required_names(part))
        for part in split_selector_list(rule.prelude)
    )


def uncovered_rules(audience: str, names: set[str], styles: Path = STYLES) -> list[str]:
    """page.css rules that could match a page naming `names` but that the
    page's bundle leaves out."""

    grouped = regions(parse(_source(PAGE, styles)))
    received = {id(rule) for rule in style_rules(_items_for(audience, grouped))}
    return [
        rule.prelude
        for _audiences, members in grouped
        for rule in style_rules(members)
        if id(rule) not in received and could_match(rule, names)
    ]


_SCRIPT_SOURCE = re.compile(r'<script src="/(zh-TW/[^"?#]+)')


def names_on_page(markup: str, frontend: Path) -> set[str]:
    """The classes and ids a served page can carry: its markup's, and any its
    scripts' literals can add."""

    names = names_in_markup(markup)
    for source in _SCRIPT_SOURCE.findall(markup):
        names |= names_in_script((frontend / source).read_text(encoding="utf-8"))
    return names


_NAME = re.compile(r"-?[A-Za-z_][A-Za-z0-9_-]*")
_MARKUP_NAMES = re.compile(r"""(?<![\w-])(?:class|id)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def names_in_markup(markup: str) -> set[str]:
    """Every class (`.name`) and id (`#name`) a page's markup gives its elements."""

    names: set[str] = set()
    for match in _MARKUP_NAMES.finditer(markup):
        sigil = "#" if match.group(0).lstrip().startswith("id") else "."
        names.update(sigil + name for name in (match.group(1) or match.group(2)).split())
    return names


def names_in_script(source: str) -> set[str]:
    """Every name-shaped word inside a string or template literal of a script.

    The scripts set classes and ids only from literals (`node.className =
    "note"`), so the words of the literals bound what a script can add.  Words
    outside literals (identifiers, comments, a template's `${...}` code) are
    left out: `path` as a variable does not put `.path` on the page.
    """

    names: set[str] = set()

    def literal(text: str) -> None:
        for word in _NAME.findall(text):
            names.update(("." + word, "#" + word))

    def code(index: int, closing: str | None) -> int:
        depth = 0
        while index < len(source):
            char = source[index]
            if source.startswith("//", index):
                end = source.find("\n", index)
                index = len(source) if end < 0 else end
            elif source.startswith("/*", index):
                end = source.find("*/", index + 2)
                index = len(source) if end < 0 else end + 2
            elif char in "\"'":
                start = index + 1
                index += 1
                while index < len(source) and source[index] not in (char, "\n"):
                    index += 2 if source[index] == "\\" else 1
                literal(source[start:index])
                index += 1
            elif char == "`":
                index = template(index + 1)
            elif char == "{":
                depth += 1
                index += 1
            elif char == "}":
                if depth == 0 and closing == "}":
                    return index + 1
                depth -= 1
                index += 1
            else:
                index += 1
        return index

    def template(index: int) -> int:
        start = index
        while index < len(source):
            char = source[index]
            if char == "\\":
                index += 2
            elif char == "`":
                literal(source[start:index])
                return index + 1
            elif source.startswith("${", index):
                literal(source[start:index])
                index = code(index + 2, "}")
                start = index
            else:
                index += 1
        literal(source[start:index])
        return index

    code(0, None)
    return names


# --- minification -------------------------------------------------------------
#
# The bundles ship without the sources' comments and layout.  Only what CSS
# syntax makes insignificant is removed: comments (except `/*! … */`, kept for
# licence notices), whitespace runs (collapsed to one space, never removed
# between two tokens that need it), the spaces around `{`, `}`, `;` and a
# declaration's first `:`, the spaces around a selector's `,`, `>`, `+` and
# `~`, and a block's last `;`.  Strings are copied byte for byte; selectors keep their
# descendant spaces (`a :hover` is not `a:hover`) and values keep theirs
# (`calc(1px + 2px)` needs them).


def _strip_comments(text: str) -> str:
    """`text` with each comment replaced by a space (`/*! … */` kept)."""

    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            end = _skip_string(text, index)
            out.append(text[index:end])
            index = end
        elif text.startswith("/*", index):
            end = _skip_comment(text, index)
            out.append(text[index:end] if text.startswith("/*!", index) else " ")
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _squeeze(text: str, tight: str) -> str:
    """Collapse whitespace runs outside strings to one space, and drop it next
    to any character in `tight`."""

    out: list[str] = []
    index = 0
    pending_space = False
    while index < len(text):
        char = text[index]
        if char.isspace():
            pending_space = True
            index += 1
            continue
        if char in "\"'":
            end = _skip_string(text, index)
            piece = text[index:end]
        elif text.startswith("/*!", index):
            end = _skip_comment(text, index)
            piece = text[index:end]
        else:
            end = index + 1
            piece = char
        if pending_space and out and out[-1][-1] not in tight and piece[0] not in tight:
            out.append(" ")
        pending_space = False
        out.append(piece)
        index = end
    return "".join(out)


def _split_top(text: str, separator: str) -> list[str]:
    """Split on `separator` outside strings and parentheses."""

    parts, depth, start, index = [], 0, 0, 0
    while index < len(text):
        char = text[index]
        if char in "\"'":
            index = _skip_string(text, index)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
        index += 1
    parts.append(text[start:])
    return parts


def _minify_declarations(body: str) -> str:
    declarations = []
    for declaration in _split_top(_strip_comments(body), ";"):
        if not declaration.strip():
            continue
        name, colon, value = declaration.partition(":")
        if not colon:
            raise ValueError(f"declaration without a colon: {declaration.strip()!r}")
        # A value keeps one space after its commas: where a value holds var(),
        # the browser keeps its text as written, so `a, b` and `a,b` would
        # serialise differently although they mean the same.
        declarations.append(f"{name.strip()}:{_squeeze(value, '').strip()}")
    return ";".join(declarations)


def _minify_items(items: Iterable[Item]) -> str:
    out: list[str] = []
    for item in items:
        if item.kind == "comment":
            if item.text.startswith("/*!"):
                out.append(item.text)
            continue
        brace = _block_start(item.text)
        prelude = _strip_comments(item.text[:brace])
        body = item.text[brace + 1:-1]
        if item.kind == "rule":
            out.append(_squeeze(prelude, ",>+~").strip() + "{" + _minify_declarations(body) + "}")
            continue
        name = item.prelude.split(None, 1)[0].lower()
        head = _squeeze(prelude, ",").strip()
        if name in {"@media", "@supports", "@keyframes"}:
            out.append(head + "{" + _minify_items(parse(body)) + "}")
        else:
            out.append(head + "{" + _minify_declarations(body) + "}")
    return "".join(out)


def minify(css: str) -> str:
    """The stylesheet with comments and insignificant whitespace removed."""

    return _minify_items(parse(css))
