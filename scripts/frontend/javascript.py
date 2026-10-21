"""The page scripts, shipped without the comments and layout of their sources.

The readable scripts are in `scripts/` beside this module; `build_pages` writes
each one minified to `frontend/zh-TW/<name>` (and `--check` compares), so the
release still copies committed files and the readable form stays the one to
edit.  The minifier is a tokenizer for the JavaScript these scripts are written
in (classic scripts, ES2022): it reads strings, template literals (with the
code in `${}`), regular expression literals and comments as such, drops the
comments, and joins the tokens with the least whitespace that keeps both the
same tokens and the same program:

- one space between two tokens only where they would otherwise fuse (`a in`,
  `+ +`, `/ /re/`, `1 .x`);
- a line break kept wherever it can decide where a statement ends: after a
  token that cannot end an expression (`(`, `,`, `=`, `+`, ...) and before one
  that continues it (`)`, `.`, `+`, ...) it goes; after `return`, `throw`,
  `break`, `continue`, `yield`, `async` and similar, around `++`/`--`, and
  between any other pair (`}` then `const`, `1` then `const`) it stays.

A `/*! ... */` comment at the head of a file (a licence notice) is kept.
frontend/tests/shipped_scripts.test.cjs proves the result: each shipped file
has its source's token stream and syntax tree under ESLint's parser.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from scripts.frontend.site_locale import DEFAULT_LOCALE


SOURCES = Path(__file__).resolve().parent / "scripts"
# Where the shipped scripts live, relative to frontend/ and as served.
SHIPPED_DIRECTORY = DEFAULT_LOCALE

_LINE_TERMINATORS = "\n\r\u2028\u2029"
_PUNCTUATORS = sorted(
    """
    >>>= ... === !== **= <<= >>= >>> &&= ||= ??= => == != <= >= && || ?? ?. ++ -- += -= *= /= %= &=
    |= ^= ** << >> { } ( ) [ ] ; , < > + - * / % & | ^ ! ~ ? : = .
    """.split(),
    key=len, reverse=True,
)
# Character runs that would read as something else if two tokens met: a longer
# punctuator, a comment, or an HTML-like comment (a script's legacy syntax).
_FUSING = (*_PUNCTUATORS, "//", "/*", "<!--", "-->")
_NUMBER = re.compile(
    r"0[xX][0-9a-fA-F_]+n?|0[oO][0-7_]+n?|0[bB][01_]+n?"
    r"|(?:\d[\d_]*(?:\.[\d_]*)?|\.\d[\d_]*)(?:[eE][+-]?\d[\d_]*)?n?"
)
# After one of these words a `/` starts a regular expression, not a division.
_EXPRESSION_KEYWORDS = frozenset(
    "return typeof instanceof in of new delete void throw case do else yield await".split()
)
# [no LineTerminator here] follows these words in some production, or a line
# break after them can end the statement (`let`, `get`, `set`, `static` as names).
_RESTRICTED_WORDS = frozenset(
    "return throw break continue yield async await let get set static".split()
)
# Tokens that cannot end an expression or statement: a line break after them
# never decides anything.
_OPEN_AFTER = frozenset(set(_PUNCTUATORS) - {")", "]", "}", "++", "--"})
# Tokens that can only continue what precedes them: a line break before them
# never ends a statement (no automatic semicolon is inserted before a token the
# grammar allows there, and these are allowed wherever the line before ended).
_CONTINUING = frozenset(
    """
    ) ] } , ; : ? ?. . ( [ = += -= *= /= %= **= <<= >>= >>>= &= |= ^= &&= ||= ??= == != === !==
    < > <= >= && || ?? + - * / % ** & | ^ << >> >>>
    """.split()
)
_BRACKETS = {")": "(", "]": "[", "}": "{"}


@dataclass(frozen=True)
class Token:
    # "name" (identifier, keyword or #private), "number", "string", "regex",
    # "template" (a whole literal or the part up to / between / after a
    # `${...}`), "punct" or "comment".
    kind: str
    text: str
    # A line terminator (or a comment holding one) came before this token.
    newline: bool


def _is_identifier_start(char: str) -> bool:
    return char in "$_\\" or char.isalpha() or (ord(char) > 127 and char.isidentifier())


def _is_identifier_part(char: str) -> bool:
    return (
        char in "$_\\\u200c\u200d" or char.isalnum()
        or (ord(char) > 127 and ("a" + char).isidentifier())
    )


def _regex_allowed(previous: Token | None) -> bool:
    """Whether a `/` after `previous` starts a regular expression."""

    if previous is None:
        return True
    if previous.kind == "punct":
        return previous.text not in {")", "]", "++", "--"}
    if previous.kind == "name":
        return previous.text in _EXPRESSION_KEYWORDS
    if previous.kind == "template":
        return previous.text.endswith("${")
    return False


class _Reader:
    def __init__(self, source: str) -> None:
        self.source = source
        self.index = 0

    def fail(self, message: str) -> ValueError:
        line = self.source.count("\n", 0, self.index) + 1
        return ValueError(f"{message} at line {line}")

    def string(self) -> str:
        start = self.index
        quote = self.source[start]
        index = start + 1
        while index < len(self.source):
            char = self.source[index]
            if char == "\\":
                index += 2
                continue
            if char == quote:
                self.index = index + 1
                return self.source[start:self.index]
            if char in "\n\r":
                break
            index += 1
        self.index = start
        raise self.fail("unterminated string")

    def template_part(self) -> str:
        """From a backtick or the `}` that closes a substitution, up to and
        including the closing backtick or the next `${`."""

        start = self.index
        index = start + 1
        while index < len(self.source):
            char = self.source[index]
            if char == "\\":
                index += 2
                continue
            if char == "`":
                self.index = index + 1
                return self.source[start:self.index]
            if self.source.startswith("${", index):
                self.index = index + 2
                return self.source[start:self.index]
            index += 1
        raise self.fail("unterminated template literal")

    def regex(self) -> str:
        start = self.index
        index = start + 1
        in_class = False
        while index < len(self.source):
            char = self.source[index]
            if char in _LINE_TERMINATORS:
                break
            if char == "\\":
                index += 2
                continue
            if char == "[":
                in_class = True
            elif char == "]":
                in_class = False
            elif char == "/" and not in_class:
                index += 1
                while index < len(self.source) and _is_identifier_part(self.source[index]):
                    index += 1
                self.index = index
                return self.source[start:index]
            index += 1
        self.index = start
        raise self.fail("unterminated regular expression")

    def name(self) -> str:
        start = self.index
        index = start + 1 if self.source[start] == "#" else start
        if index >= len(self.source) or not _is_identifier_start(self.source[index]):
            raise self.fail(f"unexpected character {self.source[start]!r}")
        while index < len(self.source) and _is_identifier_part(self.source[index]):
            index += 1
        self.index = index
        return self.source[start:index]


def _scan(source: str) -> list[Token]:
    """Every token of `source`, each comment included as a "comment" token."""

    reader = _Reader(source)
    tokens: list[Token] = []
    # Open brackets, and "${" for each template substitution being read.
    brackets: list[str] = []
    previous: Token | None = None
    newline = False
    while reader.index < len(source):
        index = reader.index
        char = source[index]
        if char in _LINE_TERMINATORS:
            newline = True
            reader.index += 1
            continue
        if char.isspace() or char == "\ufeff":
            reader.index += 1
            continue
        if source.startswith("//", index):
            ends = [position for position in (source.find(t, index) for t in _LINE_TERMINATORS) if position >= 0]
            reader.index = min(ends, default=len(source))
            tokens.append(Token("comment", source[index:reader.index], newline))
            newline = False
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise reader.fail("unterminated comment")
            reader.index = end + 2
            tokens.append(Token("comment", source[index:reader.index], newline))
            newline = False
            continue
        if char in "\"'":
            token = Token("string", reader.string(), newline)
        elif char == "`" or (char == "}" and brackets and brackets[-1] == "${"):
            if char == "}":
                brackets.pop()
            token = Token("template", reader.template_part(), newline)
            if token.text.endswith("${"):
                brackets.append("${")
        elif char.isdigit() or (char == "." and source[index + 1:index + 2].isdigit()):
            match = _NUMBER.match(source, index)
            assert match is not None
            reader.index = match.end()
            if reader.index < len(source) and _is_identifier_part(source[reader.index]):
                raise reader.fail("an identifier or digit directly after a number")
            token = Token("number", match.group(), newline)
        elif char == "/" and _regex_allowed(previous):
            token = Token("regex", reader.regex(), newline)
        elif _is_identifier_start(char) or char == "#":
            token = Token("name", reader.name(), newline)
        else:
            text = next((p for p in _PUNCTUATORS if source.startswith(p, index)), None)
            if text == "?." and source[index + 2:index + 3].isdigit():
                text = "?"
            if text is None:
                raise reader.fail(f"unexpected character {char!r}")
            if text in "([{":
                brackets.append(text)
            elif text in _BRACKETS:
                if not brackets or brackets[-1] != _BRACKETS[text]:
                    raise reader.fail(f"unbalanced {text!r}")
                brackets.pop()
            reader.index = index + len(text)
            token = Token("punct", text, newline)
        tokens.append(token)
        previous = token
        newline = False
    if brackets:
        raise reader.fail(f"unclosed {brackets[-1]!r}")
    return tokens


def comments(source: str) -> list[str]:
    """Every comment of `source`, as written."""

    return [token.text for token in _scan(source) if token.kind == "comment"]


def tokenize(source: str) -> list[Token]:
    """The tokens of `source` without its comments, except a `/*! ... */`
    comment at its head; a dropped comment holding a line break counts as one."""

    tokens: list[Token] = []
    pending = False
    for token in _scan(source):
        if token.kind == "comment":
            if token.text.startswith("/*!"):
                if tokens:
                    raise ValueError("a /*! comment is kept only at the head of a file")
                tokens.append(token)
                continue
            pending = pending or token.newline or any(t in token.text for t in _LINE_TERMINATORS)
            continue
        if pending and not token.newline:
            token = Token(token.kind, token.text, True)
        tokens.append(token)
        pending = False
    return tokens



def frozen_string_table(source: str, name: str) -> dict[str, str]:
    """The table `const <name> = Object.freeze({ key: "text", ... });` of a
    readable script, so a generator reads the page's own names instead of a copy.

    Only that shape is read (identifier or double-quoted keys, double-quoted
    values); a missing, repeated or reshaped table raises."""

    tokens = tokenize(source)
    head = ["const", name, "=", "Object", ".", "freeze", "(", "{"]
    starts = [index for index in range(len(tokens)) if [t.text for t in tokens[index:index + len(head)]] == head]
    if len(starts) != 1:
        raise ValueError(f"expected one `const {name} = Object.freeze({{...}})`, found {len(starts)}")
    table: dict[str, str] = {}
    index = starts[0] + len(head)
    while tokens[index].text != "}":
        key, colon, value, after = tokens[index:index + 4]
        if (key.kind not in ("name", "string") or colon.text != ":" or value.kind != "string"
                or not value.text.startswith('"') or after.text not in (",", "}")):
            raise ValueError(f"{name}: not a flat table of double-quoted strings at {key.text!r}")
        text = json.loads(key.text) if key.kind == "string" else key.text
        if text in table:
            raise ValueError(f"{name}: key {text!r} repeated")
        table[text] = json.loads(value.text)
        index += 4 if after.text == "," else 3
    if tokens[index + 1].text != ")":
        raise ValueError(f"{name}: the table is not the whole Object.freeze argument")
    return table

def _separator(before: Token, after: Token) -> str:
    """The least whitespace between two tokens that keeps both and their meaning."""

    if after.newline and not _line_break_droppable(before, after):
        return "\n"
    if _is_identifier_part(before.text[-1]) and _is_identifier_part(after.text[0]):
        return " "
    if before.kind == "number" and after.text.startswith("."):
        return " "
    if before.text.endswith("/") and after.text[0] in "/*":
        return " "
    if before.kind == "punct":
        joined = before.text + after.text[0]
        if any(fused.startswith(joined) for fused in _FUSING):
            return " "
    return ""


def _line_break_droppable(before: Token, after: Token) -> bool:
    if before.kind == "name" and before.text in _RESTRICTED_WORDS:
        return False
    if before.text in {"++", "--"} or after.text in {"++", "--", "=>"}:
        return False
    if before.kind == "punct" and before.text in _OPEN_AFTER:
        return True
    if before.kind == "template" and before.text.endswith("${"):
        return True
    if after.kind == "template" and after.text.startswith("}"):
        return True
    return after.kind == "punct" and after.text in _CONTINUING


def minify(source: str) -> str:
    """`source` without comments (a leading `/*! ... */` kept) and without the
    whitespace its tokens and statements do not need; ends with a line break."""

    tokens = tokenize(source)
    out: list[str] = []
    previous: Token | None = None
    for token in tokens:
        if token.kind == "comment":
            out.append(token.text + "\n")
            continue
        if previous is not None:
            out.append(_separator(previous, token))
        out.append(token.text)
        previous = token
    return "".join(out) + "\n"


def shipped_path(name: str) -> str:
    return f"{SHIPPED_DIRECTORY}/{name}"


# Scripts shipped as one file made of several readable sources, in order (the
# last one names the shipped file).  The sources stay split for editing; the
# page pays one request per bundle, as before the split.  A bundle is one
# function scope: its sources are joined inside `(function () { ... })();`, so
# they name each other's top-level declarations directly and none of them
# becomes a global.  While loading, a source uses only names an earlier source
# defined; a later source's functions are used only when called.  The first
# source carries the bundle's "use strict".  frontend/tests/script-bundles.cjs
# reads them the same way.
BUNDLES_PATH = Path(__file__).resolve().parent / "script_bundles.json"


BUNDLE_OPEN = "(function () {\n"
BUNDLE_CLOSE = "})();\n"


def bundles(path: Path = BUNDLES_PATH) -> dict[str, list[str]]:
    declared = json.loads(path.read_text(encoding="utf-8"))
    for name, members in declared.items():
        if not members or members[-1] != name:
            raise ValueError(f"bundle {name} must end with its own source")
    return declared


def readable(name: str, sources: Path = SOURCES) -> str:
    """The readable text behind shipped script `name`: its source, or a
    bundle's sources joined in order."""

    members = bundles().get(name)
    if members is None:
        return (sources / name).read_text(encoding="utf-8")
    return BUNDLE_OPEN + "\n".join((sources / member).read_text(encoding="utf-8") for member in members) + BUNDLE_CLOSE


def build_scripts(sources: Path = SOURCES) -> dict[str, str]:
    """Every shipped script, minified from its readable source (a bundle from
    its sources in order), keyed by its path under frontend/."""

    declared = bundles()
    folded = {member for name, members in declared.items() for member in members if member != name}
    built = {
        shipped_path(path.name): minify(readable(path.name, sources))
        for path in sorted(sources.glob("*.js"))
        if path.name not in folded
    }
    if not built:
        raise ValueError(f"no readable script in {sources}")
    return built
