"""Per-page stylesheet bundles, built from the readable sources in `styles/`.

A page carries one stylesheet inline in its head (build_pages.inline_stylesheet): tokens.css and page.css, then
calculate.css and timelords.css on the calculator or article.css (and figures.css) on an article, in source order, cut
to the rules its page could match.

Which rules a page receives is read from the page itself: the classes and ids its markup carries and its scripts'
string literals can add (`names_on_page`).  A rule goes to a page when every class and id one of its selectors
requires is present, and a selector list is cut to the selectors that could match (`bundle_items`).  A selector made
only of elements and attributes goes to every page; a @keyframes block goes where a rule that animates with it goes.

An audience is a surface key from frontend/surfaces.json, `blog-article` (every article) or `not-found`; `build_pages`
writes each audience's bundle to `frontend/zh-TW/style/<audience>.css`.  An article whose fragment holds a
`<figure data-fx>` is the audience `blog-article-figures`: the article bundle with figures.css appended.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re
from pathlib import Path
from typing import Iterable, Mapping

from scripts.frontend.site_locale import DEFAULT_LOCALE

STYLES = Path(__file__).resolve().parent / "styles"
DESIGN_SHEET = "tokens.css"
PAGE = "page.css"
CALCULATOR = "calculate.css"
# The time-lord section's rules sit in their own sheet, appended after calculate.css in the same bundle.
CALCULATOR_PARTS = (CALCULATOR, "timelords.css")
ARTICLE = "article.css"
FIGURES = "figures.css"
BUNDLE_DIRECTORY = f"{DEFAULT_LOCALE}/style"
ARTICLE_AUDIENCE = "blog-article"
FIGURES_AUDIENCE = "blog-article-figures"
NOT_FOUND_AUDIENCE = "not-found"
CALCULATOR_AUDIENCE = "calculate"
_GROUPING_AT_RULES = frozenset({"@media", "@supports", "@layer"})

@dataclass(frozen=True)
class Item:

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

    Only plain CSS of the kind these sheets use: statement at-rules (@import, @charset) or stray tokens are refused.
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
            children = tuple(parse(body)) if name in _GROUPING_AT_RULES else ()
            items.append(Item("at", text, prelude, children))
        else:
            items.append(Item("rule", text, prelude))
        index = end

_FIGURE_DECLARATION = re.compile(r"<figure\b[^>]*\sdata-fx(?=[\s>])")

def declares_figures(fragment: str) -> bool:
    return _FIGURE_DECLARATION.search(fragment) is not None

def audience_of(row: Mapping[str, object], pages: Path | None = None) -> str:
    """The stylesheet audience of a surfaces.json row (an article's depends on its fragment, read from `pages`)."""
    if isinstance(row.get("article"), dict):
        if pages is None:
            from scripts.frontend import build_pages
            pages = build_pages.PAGES
        fragment = (pages / f"{row['fragment']}.html").read_text(encoding="utf-8")
        return FIGURES_AUDIENCE if declares_figures(fragment) else ARTICLE_AUDIENCE
    if "status" in row:
        return NOT_FOUND_AUDIENCE
    return str(row["key"])

# Audiences whose bundles are byte for byte the same share one file.  The build refuses identical bundles not named
# here, and a name whose members' bundles differ (sharing must never hand a page another page's rules).
SHARED_BUNDLES: Mapping[str,
    frozenset[str]] = {"calculate-landing": frozenset({"calculate-decennials", "calculate-firdaria",
    "calculate-profections", "calculate-zodiacal-releasing"})}

def bundle_name(audience: str) -> str:
    return next((name for name, members in SHARED_BUNDLES.items() if audience in members), audience)

def bundle_path(audience: str) -> str:
    return f"{BUNDLE_DIRECTORY}/{bundle_name(audience)}.css"

SHEETS: tuple[tuple[str, frozenset[str] | None], ...] = ((DESIGN_SHEET, None), (PAGE, None),
    *((name, frozenset({CALCULATOR_AUDIENCE})) for name in CALCULATOR_PARTS),
    (ARTICLE, frozenset({ARTICLE_AUDIENCE, FIGURES_AUDIENCE})), (FIGURES, frozenset({FIGURES_AUDIENCE})))

@lru_cache(maxsize=16)
def _parsed(css: str) -> tuple[Item, ...]:
    return tuple(parse(css))

def sheet_items(name: str, styles: Path = STYLES) -> tuple[Item, ...]:
    return _parsed((styles / name).read_text(encoding="utf-8"))

def _sheets_for(audience: str) -> list[str]:
    return [name for name, receivers in SHEETS if receivers is None or audience in receivers]

def bundle_items(audience: str, names: frozenset[str] | set[str] | None = None,
    styles: Path = STYLES) -> list[tuple[str, Item]]:
    """The (sheet, item) pairs of `audience`'s bundle: every item of the sheets it receives, cut to what a page naming
    `names` could match (a @keyframes block stays only where a kept rule names it); with no names, uncut."""
    if names is None:
        return [(name, item) for name in _sheets_for(audience) for item in sheet_items(name, styles)]
    present = _presence(names)
    cut = [(name, item) for name in _sheets_for(audience) for item in _matchable(list(sheet_items(name, styles)), present)]
    used = _animations([item for _name, item in cut])
    return [(name, item) for name, item in cut if _keyframes_used(item, used)]

def bundle_source(audience: str, names: frozenset[str] | set[str] | None = None, styles: Path = STYLES) -> str:
    return "\n".join(item.text for _name, item in bundle_items(audience, names, styles)) + "\n"

def build_bundle(audience: str, names: frozenset[str] | set[str] | None = None, styles: Path = STYLES) -> str:
    return minify(bundle_source(audience, names, styles)) + "\n"

def _could_match_selector(selector: str, present) -> bool:
    return all(present(name) for name in required_names(selector))

_KEYFRAMES_NAME = re.compile(r"@keyframes\s+(-?[A-Za-z_][A-Za-z0-9_-]*)", re.IGNORECASE)

def _animations(items: list[Item]) -> str:
    return " ".join(rule.text[_block_start(rule.text):] for rule in style_rules(items))

def _keyframes_used(item: Item, used: str) -> bool:
    match = _KEYFRAMES_NAME.match(item.text) if item.kind == "at" else None
    return match is None or re.search(rf"(?<![\w-]){re.escape(match.group(1))}(?![\w-])", used) is not None

def _matchable(items: list[Item], present) -> list[Item]:
    kept: list[Item] = []
    for item in items:
        if item.kind == "rule":
            parts = split_selector_list(item.prelude)
            matching = [part for part in parts if _could_match_selector(part, present)]
            if len(matching) == len(parts):
                kept.append(item)
            elif matching:
                prelude = ",".join(matching)
                kept.append(Item("rule", prelude + item.text[_block_start(item.text):], prelude))
        elif item.kind == "at" and item.children:
            children = _matchable(list(item.children), present)
            if children == list(item.children):
                kept.append(item)
            elif any(child.kind != "comment" for child in children):
                head = item.text[:_block_start(item.text)]
                body = "\n".join(child.text for child in children)
                kept.append(Item("at", head + "{" + body + "}", item.prelude, tuple(children)))
        else:
            kept.append(item)
    return kept

def unmatchable_selectors(css: str, names: frozenset[str] | set[str]) -> list[str]:
    """Each selector of a (served) stylesheet, even inside a list, that a page naming `names` could not match."""
    present = _presence(names)
    return [
        part
        for rule in style_rules(parse(css))
        for part in split_selector_list(rule.prelude)
        if not _could_match_selector(part, present)
    ]

def build_bundles(rows: Iterable[Mapping[str, object]], names_by_audience: Mapping[str, set[str]],
    styles: Path = STYLES) -> dict[str, str]:
    """Every bundle the rows need, keyed by its path under frontend/, each cut to its audience's `names_on_page`."""
    audiences = {audience_of(row) for row in rows}
    if audiences & set(SHARED_BUNDLES):
        raise ValueError(f"a shared bundle is named after an audience: {sorted(audiences & set(SHARED_BUNDLES))}")
    built = {audience: build_bundle(audience, frozenset(names_by_audience.get(audience, ())),
        styles) for audience in sorted(audiences)}
    bundles: dict[str, str] = {}
    for audience, text in built.items():
        if bundles.setdefault(bundle_path(audience), text) != text:
            raise ValueError(f"{bundle_name(audience)} is shared by audiences whose bundles differ: {audience}")
    by_text: dict[str, set[str]] = {}
    for audience, text in built.items():
        by_text.setdefault(text, set()).add(bundle_name(audience))
    twins = sorted(sorted(names) for names in by_text.values() if len(names) > 1)
    if twins:
        raise ValueError(f"identical bundles not shared (name them in SHARED_BUNDLES): {twins}")
    return bundles

# --- which rules a page could match -------------------------------------------

_FUNCTIONAL_PSEUDO = re.compile(r":(?:not|is|where|has|nth-child|nth-last-child|nth-of-type|nth-last-of-type)\(")
_SELECTOR_TOKEN = re.compile(r"([.#])(-?[A-Za-z_][A-Za-z0-9_-]*)")
_ATTRIBUTE = re.compile(r"\[[^\]]*\]")

def _without_functional_pseudos(selector: str) -> str:
    """Drop :not(...), :is(...) and the like with their arguments: what they require is not a plain conjunction."""
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
    """The class and id names an element tree must contain for `selector` to match anything."""
    plain = _without_functional_pseudos(_ATTRIBUTE.sub("", selector))
    return frozenset(sigil + name for sigil, name in _SELECTOR_TOKEN.findall(plain))

def style_rules(items: Iterable[Item]) -> Iterable[Item]:
    for item in items:
        if item.kind == "rule":
            yield item
        elif item.kind == "at":
            yield from style_rules(item.children)

def _presence(names: frozenset[str] | set[str]):
    """Whether a name is present: named exactly, or a script names a prefix ending in `-` (`"sd-at-" + n`)."""
    prefixes = tuple(other for other in names if other.endswith("-"))
    return lambda name: name in names or name.startswith(prefixes)

# A page's scripts: each <script src>, and every script a data-* attribute names for calculate.js to import later,
# except view-model.js (it builds no elements).
_SCRIPT_SOURCE = re.compile(
    r'(?:<script src|\sdata-(?!view-model=)[a-z-]+)="/(' + re.escape(DEFAULT_LOCALE) + r'/[^"?#]+\.js)'
)

def names_on_page(markup: str, frontend: Path) -> set[str]:
    names = names_in_markup(markup)
    for source in _SCRIPT_SOURCE.findall(markup):
        names |= _script_names((frontend / source).read_text(encoding="utf-8"))
    return names

@lru_cache(maxsize=64)
def _script_names(source: str) -> frozenset[str]:
    return frozenset(names_in_script(source))

_NAME = re.compile(r"-?[A-Za-z_][A-Za-z0-9_-]*")
_MARKUP_NAMES = re.compile(r"""(?<![\w-])(?:class|id)\s*=\s*(?:"([^"]*)"|'([^']*)')""")

def names_in_markup(markup: str) -> set[str]:
    names: set[str] = set()
    for match in _MARKUP_NAMES.finditer(markup):
        sigil = "#" if match.group(0).lstrip().startswith("id") else "."
        names.update(sigil + name for name in (match.group(1) or match.group(2)).split())
    return names

def names_in_script(source: str) -> set[str]:
    """Every name-shaped word inside a string or template literal of a script.

    Scripts set classes and ids only from literals, so these bound what a script can add; identifiers, comments and a
    template's `${...}` code are left out.
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
# Only what CSS syntax makes insignificant is removed: comments (except `/*! … */`), whitespace runs (never removed
# between two tokens that need it), the spaces around `{`, `}`, `;`, a declaration's first `:`, a selector's `,`, `>`,
# `+` and `~`, and a block's last `;`.  Strings are copied byte for byte; selectors keep their descendant spaces.

def _strip_comments(text: str) -> str:
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
        # A value keeps one space after its commas: where a value holds var(), the browser keeps its text as written.
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
        if name in _GROUPING_AT_RULES | {"@keyframes"}:
            out.append(head + "{" + _minify_items(parse(body)) + "}")
        else:
            out.append(head + "{" + _minify_declarations(body) + "}")
    return "".join(out)

def minify(css: str) -> str:
    return _minify_items(parse(css))
