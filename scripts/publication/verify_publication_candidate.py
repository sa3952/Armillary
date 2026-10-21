#!/usr/bin/env python3
"""Fail closed on a public source tree that leaks private material or is incomplete.

Checked here: the closed file list (PUBLICATION_FILES.json), no symlink or
secret-looking path, no local path or secret in any byte, no ticket or
ruling id in a comment, Python string or JSON file, no named path the tree
does not carry, the vendored pyswisseph source against the committed
source lock, and no dependency bundle: the other dependencies are named by
their locked hashes and fetched from PyPI, not shipped.  Whether the tree
builds and its tests pass is the public repository CI's job (its
scripts/verify_delivery.py).

`--reconstruction-mode online-clean` additionally rebuilds the dependency set
from PyPI by the locked hashes in a pinned Linux builder; Gate F runs it only
when the locks or third_party/ changed.
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import io
import ipaddress
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Callable

from scripts.tools.source_tree_identity import (
    is_public_release_record, observe_publication_tree, sha256_file as _sha256,
)


FORBIDDEN_PATH_PARTS = {".DS_Store", ".env", ".pytest_cache", "__pycache__"}
# Names that hold credentials, keys or private notes.  The exporter and this
# verifier refuse a public path with any of them through refused_public_path,
# the one path rule both gates apply.
REFUSED_NAME = re.compile(
    r"(?:^|\.)env(?:\.|$)|secret|passw(?:or)?d|credential|private"
    r"|\.(?:pem|key|p12|pfx|jks|keystore)$|^id_(?:rsa|dsa|ecdsa|ed25519)(?:\.|$)",
    re.IGNORECASE,
)
# The generic content rules of a public tree: no local home or temporary path
# (FORBIDDEN_TEXT, every file) and no secret (SECRET_PATTERNS, text files).
# The exporter adds the project's own list, which is not published.  Split so
# that this verifier does not match itself.
FORBIDDEN_TEXT = {
    "/" + "Users" + "/",
    "/private" + "/tmp",
}
_CREDENTIAL_NAME = (
    rb"[A-Za-z0-9_.-]*"
    rb"(?:pass" rb"word|passwd|sec" rb"ret|tok" rb"en|api[_-]?key|private[_-]?key|access[_-]?key)"
    rb"[A-Za-z0-9_.-]*"
)
# At least six characters, one of them a letter, none a quote, space or template sigil.
_CREDENTIAL_LITERAL = rb"(?=[^\s\"']*[A-Za-z])[^\s\"'$(){}\[\]<>,;]{6,}"
# A password, token or key in a form a configuration file writes it.  A
# template (`${NPM_TOKEN}`), a placeholder (`<token>`) or an expression in
# backticks is not matched.
_URL_PART = rb"[^\s/:@\"'<>`$(){}\[\]]"
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"),
    # .npmrc: `//registry.example/:_authToken=...`, `_auth=...`, `_password=...`.
    "npm auth": re.compile(
        rb"(?im)^[ \t]*(?://[^\s=]*:)?_(?:auth|authToken|password)[ \t]*=[ \t]*(?!\$\{)[^\s]{6,}"
    ),
    "npm token": re.compile(rb"\bnpm_[A-Za-z0-9]{36}\b"),
    "PyPI token": re.compile(rb"\bpypi-AgE[A-Za-z0-9_-]{16,}"),
    # A URL that carries a user and a password before its host.
    "password in a URL": re.compile(
        rb"\b[A-Za-z][A-Za-z0-9+.-]*://" + _URL_PART + rb"+:" + _URL_PART + rb"+@[A-Za-z0-9.-]"
    ),
    # `Authorization: Bearer ...`, `proxy_set_header Authorization "Basic ..."`.
    "authorization header": re.compile(
        rb"(?i)\bauthorization\b[\"']?[ \t]*[:=,]?[ \t]*[\"']?[ \t]*(?:bearer|basic|token)[ \t]+"
        rb"[A-Za-z0-9._~+/=-]{8,}"
    ),
    # An htpasswd line: user, then an apr1, bcrypt, SHA or crypt(3) hash.
    "htpasswd hash": re.compile(
        rb"(?m)^[^\s:#]+:(?:\$apr1\$|\$2[aby]\$[0-9]{2}\$|\{SHA\}|\$[156y]\$)[^\s:]{8,}"
    ),
    "GitHub token": re.compile(rb"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"),
    "GitHub fine-grained token": re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Google API key": re.compile(rb"\bAIza[A-Za-z0-9_-]{35}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Stripe live key": re.compile(rb"\bsk_live_[A-Za-z0-9]{20,}\b"),
    "generic API token": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    # A literal assigned to a password, secret, token or key name: a whole line,
    # as an env file, shell profile or config writes it (`DB_PASSWORD=...`), or
    # a quoted key anywhere on a line, as a JSON object, a Python dict or a
    # JavaScript object writes it (`"password": "..."`, `{ accessToken: "..." }`).
    # Code that assigns an expression, a number, null or a ${reference} is not matched.
    "credential assignment": re.compile(
        rb"(?im)^[ \t]*(?:export[ \t]+)?" + _CREDENTIAL_NAME
        + rb"[ \t]*[:=][ \t]*[\"']?" + _CREDENTIAL_LITERAL + rb"[\"']?[ \t]*(?:#.*)?$"
        rb"|(?:[\"']" + _CREDENTIAL_NAME + rb"[\"']|[{,][ \t]*" + _CREDENTIAL_NAME + rb")"
        rb"[ \t]*[:=][ \t]*[\"']" + _CREDENTIAL_LITERAL + rb"[\"']"
    ),
}
SOURCE_LOCK = "publication/third_party_source_lock.json"
PYSWISSEPH_FILES = (
    "pyswisseph-2.10.3.2.tar.gz", "LICENSE.txt", "SWISS_EPHEMERIS_LICENSE",
    "SWEPHELP_LICENSE", "SWEPHELP_README.txt",
)
# What third_party/ holds: the AGPL pyswisseph source with its notices, the
# glyph licence files and the exporter's manifest of the shipped source.
THIRD_PARTY_ENTRIES = frozenset({"SOURCE_MANIFEST.json", "noto-fonts", "pyswisseph"})
# Paths of the retired dependency bundle (sdists, wheel indexes, their checksum
# list and licence table), refused by name so that it cannot come back unnoticed
# (strings split so this file names no path the tree does not carry).
DEPENDENCY_BUNDLE_PATHS = ("third_party/" "sources", "third_party/" "build_wheels",
                           "third_party/" "dependency_wheels", "third_party/" "SHA256SUMS",
                           "docs/" "DEPENDENCY_LICENSES.md")
RECONSTRUCTION_MODES = ("online-clean",)
RECONSTRUCTION_BUILDER_IMAGE = (
    "python:3.14.8-trixie@"
    "sha256:d0ef532dea88a06a0f950a40f95c553086c1f282bf8e313d328f11d289f72582"
)


class CandidateFailure(RuntimeError):
    """Raised when a public candidate is unsafe or incomplete."""


BINARY_SNIFF_BYTES = 8192

# Every binary the public tree carries (a NUL byte anywhere, or bytes that are
# not UTF-8), each by its public path and SHA-256.  The content scan cannot
# read a credential inside a binary, so a binary not named here, or named with
# other bytes, is refused rather than skipped.  Updating the place catalog, an
# ephemeris file or an image means approving its new digest here.
BINARY_APPROVALS = "publication/public_binary_files.json"
# An approved binary up to this size is still searched for the secret patterns:
# only the large data files (the place catalog) cost the scan its time, and
# approving an image's new digest in the same commit must not let a token
# appended to it through.
APPROVED_BINARY_PATTERN_SCAN_BYTES = 16 * 1024 * 1024
# What a public .npmrc may set: the registry, the engine check and the release
# cool-down, nothing that authenticates.
NPMRC_SETTING = re.compile(
    rb"registry=https://registry\.npmjs\.org/|engine-strict=true|min-release-age=[0-9]{1,3}"
)


# A ticket or ruling id: an upper-case word of two or more letters, then any
# hyphenated letter groups (each may end in one round digit), then a hyphen and
# a number of up to four digits.  A comment or a string keeps the reason and
# drops the id: a reader of the public tree cannot open the record it names.
# Standard names of the same shape (SHA-256, UTF-8, GPL-2, UTC-10, CC-BY-4.0)
# are not ids, and neither is a path or URL segment (Etc/GMT-8, NASA/TP-2006).
STANDARD_IDENTIFIERS = (
    "AGPL", "BSD", "CC", "CVE", "CWE", "GMT", "GPL", "HTTP", "IEEE", "ISO", "LGPL",
    "MIT", "OFL", "RFC", "SHA", "UTC", "UTF",
)
TICKET_ID = re.compile(
    r"(?<![A-Za-z0-9_/.-])(?!(?:" + "|".join(STANDARD_IDENTIFIERS) + r")[0-9]?-)"
    r"[A-Z]{2,}[0-9]?(?:-[A-Z]+[0-9]?)*-[0-9]{1,4}(?![0-9])"
)
# Where a file's comments are.  Prose (Markdown, plain text, LICENSE) is read
# whole; data (JSON, images, catalogues) carries no comment.
_HASH_COMMENT = re.compile(r"(?m)(?:^|\s)#.*$")
_C_COMMENT = re.compile(r"/\*.*?\*/|(?<![:\"'\\])//.*$", re.DOTALL | re.MULTILINE)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HASH_SUFFIXES = {
    ".yaml", ".yml", ".conf", ".template", ".sh", ".in", ".lock", ".ini", ".cff",
    ".npmrc", ".gitignore", ".dockerignore", ".toml", ".cfg", ".service", ".nft",
}
_C_SUFFIXES = {".js", ".cjs", ".mjs", ".css", ".ts"}
_MARKUP_SUFFIXES = {".html", ".svg", ".xml"}


def _python_comments(text: str) -> list[tuple[int, str]]:
    """Comments and docstrings (a string literal that is a whole statement),
    each with the line it starts on."""
    found: list[tuple[int, str]] = []
    previous = tokenize.NEWLINE
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                found.append((token.start[0], token.string))
            elif token.type == tokenize.STRING and previous in (
                tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT,
            ):
                found.append((token.start[0], token.string))
            # A line break inside brackets (NL) does not start a statement.
            if token.type not in (tokenize.COMMENT, tokenize.NL):
                previous = token.type
    except (tokenize.TokenError, SyntaxError) as error:
        raise CandidateFailure(f"cannot read the comments of a Python file: {error}") from None
    return found


def _matches(pattern: re.Pattern[str], text: str) -> list[tuple[int, str]]:
    # Matches come in order, so each counts only the line breaks since the one
    # before it rather than recounting from the start of the file.
    found: list[tuple[int, str]] = []
    line, counted = 1, 0
    for match in pattern.finditer(text):
        line += text.count("\n", counted, match.start())
        counted = match.start()
        found.append((line, match.group(0)))
    return found


def comment_parts(relative: str, data: bytes) -> list[tuple[int, str]] | None:
    """Each comment (or docstring) of one file with the line it starts on; the
    whole text of a prose file; None for a data or binary file."""
    name = relative.rsplit("/", 1)[-1]
    suffix = name[name.rfind("."):] if "." in name else ""
    if b"\0" in data[:BINARY_SNIFF_BYTES] or suffix == ".json":
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if suffix == ".py":
        return _python_comments(text)
    if suffix in _HASH_SUFFIXES or name == "Dockerfile":
        return _matches(_HASH_COMMENT, text)
    if suffix in _C_SUFFIXES:
        return _matches(_C_COMMENT, text)
    if suffix in _MARKUP_SUFFIXES:
        return _matches(_HTML_COMMENT, text) + _matches(_C_COMMENT, text)
    # Prose, and any text file whose comment syntax is not named above.
    return [(1, text)]


def _python_strings(text: str) -> list[tuple[int, str]]:
    """Every string literal of a Python file (f-string text included), with its line."""
    kinds = {tokenize.STRING} | {
        kind for name in ("FSTRING_MIDDLE", "TSTRING_MIDDLE")
        if (kind := getattr(tokenize, name, None)) is not None
    }
    try:
        return [(token.start[0], token.string)
                for token in tokenize.generate_tokens(io.StringIO(text).readline)
                if token.type in kinds]
    except (tokenize.TokenError, SyntaxError) as error:
        raise CandidateFailure(f"cannot read the strings of a Python file: {error}") from None


def id_parts(relative: str, data: bytes) -> list[tuple[int, str]]:
    """Where a ticket id may not stand: comment_parts, every string literal of a
    Python file and the whole text of a JSON file."""
    parts = comment_parts(relative, data) or []
    if relative.endswith((".py", ".json")) and b"\0" not in data[:BINARY_SNIFF_BYTES]:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return parts
        parts += _python_strings(text) if relative.endswith(".py") else [(1, text)]
    return parts


def comment_code_lines(
    relative: str, data: bytes, pattern: re.Pattern[str] = TICKET_ID,
) -> list[tuple[int, str]]:
    """(line, id) for every match of `pattern` in the comments (or prose) of one file."""
    return matches_in_parts(comment_parts(relative, data) or [], pattern)


def matches_in_parts(parts: list[tuple[int, str]], pattern: re.Pattern[str]) -> list[tuple[int, str]]:
    """(line, match) for every match of `pattern` in comment_parts' (line, text) pairs."""
    return [
        (line + part.count("\n", 0, match.start()), match.group(0))
        for line, part in parts
        for match in pattern.finditer(part)
    ]


def scan_comment_codes(
    root: Path,
    *,
    pattern: re.Pattern[str] = TICKET_ID,
    parts: Callable[[str, bytes], list[tuple[int, str]] | None] = id_parts,
) -> None:
    """Fail on a ticket or ruling id where `parts` looks (by default a comment,
    a Python string or JSON) in any file outside third_party/."""
    scanned = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] in {".git", "third_party"}:
            continue
        scanned += 1
        codes = matches_in_parts(parts(relative.as_posix(), path.read_bytes()) or [], pattern)
        if codes:
            raise CandidateFailure(
                f"internal ticket or ruling id {codes[0][1]!r} in {relative.as_posix()}"
            )
    if not scanned:
        raise CandidateFailure(f"no file to scan under {root}")


# A repository path a public file names must be one the tree carries: a reader
# cannot open a private document, tool or record.  The two tables below name
# every exception with its reason (strings split so this file names no path).
_REPOSITORY_PATH = re.compile(
    r"(?<![\w.-])((?:backend|deploy|docs|frontend|publication|scripts|tests|third_party)"
    r"/[\w./*{},-]*[\w/*}])"
)
_MODULE_PATH = re.compile(
    r"(?<![\w.])scripts\.(?:deployment|frontend|publication|tools|validation|verification)"
    r"\.[a-z_][a-z0-9_]*(?![\w.])"
)
UNPUBLISHED_PATH_CLASSES = {
    "tests" "/": "the private test suite: a comment may name the test that guards a rule",
    "frontend/" "tests/": "frontend tests and response fixtures the public tree does not carry",
}
UNPUBLISHED_REFERENCE_SITES = {
    "scripts/verification/verify_docker_context.py": (
        "probes: paths the image build context must deny or never copy",
        frozenset({
            "docs/" "README.md", "backend/" "app/.env", "backend/" "app/x.pem",
            "backend/" "app/x.key", "backend/" "app/tests/test_x.py",
            "backend/" "app/__pycache__/x.pyc", "backend/" "app/secret_settings.py",
            "publication/" "public_overlay/THIRD_PARTY_NOTICES.md",
        }),
    ),
    "tests/deployment/test_production_runtime_contract.py": (
        "a file the test plants and removes",
        frozenset({"backend/" "ephe/unexpected.se1"}),
    ),
    "docs/REPRODUCIBLE_BUILD.md": (
        "prose: a backend and frontend pair, not a path",
        frozenset({"backend/" "frontend"}),
    ),
    "scripts/verify_delivery.py": (
        "prose: backend and image consumers, not a path",
        frozenset({"backend/" "image"}),
    ),
    "tests/integration/test_hosted_profile.py": (
        "a path-traversal probe the static server must refuse",
        frozenset({"frontend/" "zh-TW/page.css"}),
    ),
}


# Markdown emphasis closing right after a path (two asterisks in bold): the
# path regex admits `*` for patterns, so a trailing run of it after a name is
# the markup, not part of the path.
_EMPHASIS_CLOSE = re.compile(r"(?<=[^/*])\*+$")
_BRACES = re.compile(r"(\{[^{}/]*\})")


def _published_paths(root: Path) -> frozenset[str]:
    """Every file and directory of the tree, each with a trailing `/`."""
    return frozenset(
        relative.as_posix() + "/" for path in root.rglob("*")
        if (relative := path.relative_to(root)).parts[0] != ".git"
    )


def _component_regex(part: str) -> str:
    def literal(text: str) -> str:
        return "".join("[^/]*" if character == "*" else re.escape(character) for character in text)
    # `{a,b}` is either; `{name}` (a placeholder, as an f-string writes it) is any name.
    return "".join(
        ("(?:" + "|".join(literal(option) for option in piece[1:-1].split(",")) + ")"
         if "," in piece else "[^/]*")
        if _BRACES.fullmatch(piece) else literal(piece)
        for piece in _BRACES.split(part)
    )


def reference_pattern(reference: str) -> re.Pattern[str]:
    """A named path pattern (`*`, `**`, `{a,b}`) as a regular expression over
    _published_paths.  The text is a reader's prose, so it is translated here
    rather than handed to pathlib's glob, whose rules differ between Python
    versions; what is not a pattern is refused as such."""
    pieces = []
    for part in reference.split("/"):
        if "**" in part and part != "**":
            raise CandidateFailure(
                f"cannot read {reference!r} as a path or a pattern: '**' is not a whole path component"
            )
        pieces.append("(?:[^/]+/)*" if part == "**" else _component_regex(part) + "/")
    return re.compile("".join(pieces))


def _names_a_published_path(root: Path, reference: str, published: Callable[[], frozenset[str]]) -> bool:
    if any(character in reference for character in "*{"):
        pattern = reference_pattern(reference)
        return any(pattern.fullmatch(path) for path in published())
    if (root / reference).exists() or (root / f"{reference}.py").is_file():
        return True
    # `module.attribute`: the path of a module and a name inside it.
    module, _, attribute = reference.rpartition(".")
    return bool(module) and attribute.isidentifier() and (root / f"{module}.py").is_file()


def named_paths(text: str) -> set[str]:
    """The repository paths and modules a text names, without the Markdown
    emphasis or the sentence punctuation around them."""
    named = {
        _EMPHASIS_CLOSE.sub("", match.group(1)).rstrip("./") for match in _REPOSITORY_PATH.finditer(text)
        # After a lone `/` it is an absolute or URL path, not one of the tree;
        # after `../` it is relative to the tree.
        if text[max(0, match.start() - 1):match.start()] != "/"
        or text[max(0, match.start() - 2):match.start()] == "./"
    }
    # A module the way `python -m` and imports name it (a module or a package).
    named |= {match.group(0).replace(".", "/") for match in _MODULE_PATH.finditer(text)}
    return named


def path_references(
    root: Path, relative: str, data: bytes, published: Callable[[], frozenset[str]] | None = None,
) -> list[str]:
    """Repository paths one public file names that the tree does not carry.
    `published` gives the tree's paths for a pattern (read once per scan)."""
    if published is None:
        cache: list[frozenset[str]] = []

        def read_once() -> frozenset[str]:
            if not cache:
                cache.append(_published_paths(root))
            return cache[0]
        published = read_once
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    site = UNPUBLISHED_REFERENCE_SITES.get(relative, ("", frozenset()))[1]
    try:
        return sorted(
            reference for reference in named_paths(text)
            if reference not in site
            and not reference.startswith(tuple(UNPUBLISHED_PATH_CLASSES))
            and not _names_a_published_path(root, reference, published)
        )
    except CandidateFailure as error:
        raise CandidateFailure(f"{relative}: {error}") from None


def scan_path_references(root: Path) -> None:
    """Fail on a public file outside third_party/ that names an unpublished path."""
    paths = _published_paths(root)

    def published() -> frozenset[str]:
        return paths

    scanned = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] in {".git", "third_party"}:
            continue
        scanned += 1
        missing = path_references(root, relative.as_posix(), path.read_bytes(), published)
        if missing:
            raise CandidateFailure(
                f"{relative.as_posix()} names unpublished path(s): {', '.join(missing)}"
            )
    if not scanned:
        raise CandidateFailure(f"no file to scan under {root}")


def load_binary_approvals(root: Path) -> dict[str, str]:
    """{public path: SHA-256} of the binaries `root` may carry; {} when it names none."""
    path = root / BINARY_APPROVALS
    if not path.exists():
        return {}
    document = _load_json(path)
    files = document.get("files")
    if document.get("schema_version") != 1 or not isinstance(files, dict) or not files or any(
        not isinstance(name, str) or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for name, digest in files.items()
    ):
        raise CandidateFailure(f"{BINARY_APPROVALS} is not a map of public paths to SHA-256 digests")
    return dict(files)


# Deployment configuration the export carries (compose files, NGINX templates,
# deploy JSON and scripts): a host's public address there is operating detail,
# not source.  Loopback, private and documentation ranges pass; package
# versions (a.b.c.d) live in the lock files and the Dockerfile, not here.
HOST_CONFIG_SUFFIXES = (".json", ".yaml", ".yml", ".conf", ".template", ".sh", ".py", ".env")
_IPV4 = re.compile(rb"(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])")


def _verify_no_host_address(relative: str, data: bytes) -> None:
    if not (relative.startswith("deploy/") and relative.endswith(HOST_CONFIG_SUFFIXES)):
        return
    for match in _IPV4.finditer(data):
        try:
            address = ipaddress.IPv4Address(match.group().decode("ascii"))
        except ValueError:
            continue
        if address.is_global:
            raise CandidateFailure(f"public IPv4 address {address} in {relative}: a host's address "
                                   "is operating detail, not source")


def _verify_npmrc(relative: str, data: bytes) -> None:
    lines = [line.strip() for line in data.splitlines() if line.strip()]
    unreviewed = [line for line in lines if NPMRC_SETTING.fullmatch(line) is None]
    if unreviewed:
        raise CandidateFailure(
            f"{relative} sets more than the registry, engine-strict and min-release-age "
            f"({len(unreviewed)} other line(s)); a public .npmrc carries no other setting"
        )


# (approved SHA-256, marker-set digest) pairs whose bytes this process has
# already searched for every marker and found clean.  An approved binary is
# skipped only when both its digest and the marker set match an earlier full
# scan; changed bytes or a changed marker set are scanned again in full.
_MARKER_CLEAN_BINARIES: set[tuple[str, str]] = set()


def _sha256_path(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def scan_candidate_content(
    root: Path,
    *,
    forbidden_markers: set[str] = FORBIDDEN_TEXT,
    secret_patterns: dict[str, re.Pattern[bytes]] | None = None,
    binary_files: dict[str, str] | None = None,
    file_check: Callable[[str, bytes], None] | None = None,
) -> None:
    """Scan every regular file's bytes outside `.git`, whatever its suffix.

    `file_check(path, bytes)` also runs, from the same read, on every file
    outside third_party/ that does not start (first 8 KiB) with a NUL byte.

    Every byte of every file is searched, case-insensitively, for the literal
    markers.  Every byte of every file is searched for the patterns too, except
    a binary over APPROVED_BINARY_PATTERN_SCAN_BYTES approved by path and
    SHA-256 (BINARY_APPROVALS, or `binary_files`): regular expressions over the
    80 MB place catalog took most of 25 s per export and cannot match what a
    person wrote, so those exact bytes are approved once instead.  Any other binary (a NUL byte
    anywhere, or bytes that are not UTF-8) is refused: what the scan cannot
    read as text it does not pass.
    """

    patterns = tuple((SECRET_PATTERNS if secret_patterns is None else secret_patterns).items())
    approvals = load_binary_approvals(root) if binary_files is None else binary_files
    literals = tuple(
        (marker, marker.encode("utf-8").lower()) for marker in sorted(forbidden_markers)
    )
    overlap = max([512, *(len(value) for _, value in literals)])
    marker_key = hashlib.sha256(b"\0".join(value for _, value in literals)).hexdigest()
    scanned = 0
    approved_seen: set[str] = set()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or ".git" in relative.parts:
            continue
        scanned += 1
        rendered = relative.as_posix()
        approved = approvals.get(rendered)
        try:
            searched = approved is None or path.stat().st_size <= APPROVED_BINARY_PATTERN_SCAN_BYTES
        except OSError as error:
            raise CandidateFailure(f"cannot scan {rendered}: {error}") from None
        if not searched and (approved, marker_key) in _MARKER_CLEAN_BINARIES:
            # These exact bytes already passed these exact markers: hash only.
            try:
                if _sha256_path(path) == approved:
                    approved_seen.add(rendered)
                    continue
            except OSError as error:
                raise CandidateFailure(f"cannot scan {rendered}: {error}") from None
        digest = hashlib.sha256()
        kept: list[bytes] | None = (
            [] if file_check is not None and relative.parts[0] != "third_party" else None
        )
        decoder = codecs.getincrementaldecoder("utf-8")()
        binary = False
        tail = b""
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    window = tail + chunk
                    lowered = window.lower()
                    for marker, encoded in literals:
                        if encoded in lowered:
                            raise CandidateFailure(f"private marker {marker!r} in {rendered}")
                    if kept is not None:
                        # file_check reads no comment or id in a NUL-sniffed binary.
                        if not tail and b"\0" in chunk[:BINARY_SNIFF_BYTES]:
                            kept = None
                        else:
                            kept.append(chunk)
                    if approved is not None:
                        digest.update(chunk)
                    elif not binary:
                        try:
                            decoder.decode(chunk)
                            binary = b"\0" in chunk
                        except UnicodeDecodeError:
                            binary = True
                    if searched:
                        for label, pattern in patterns:
                            if pattern.search(window):
                                raise CandidateFailure(f"possible {label} in {rendered}")
                    tail = window[-overlap:]
            if approved is None and not binary:
                try:
                    decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    binary = True
            if path.name == ".npmrc":
                _verify_npmrc(rendered, path.read_bytes())
            if approved is None and not binary:
                _verify_no_host_address(rendered, path.read_bytes())
            if kept is not None and file_check is not None:
                file_check(rendered, b"".join(kept))
        except OSError as error:
            raise CandidateFailure(f"cannot scan {rendered}: {error}") from None
        if approved is not None:
            approved_seen.add(rendered)
            if digest.hexdigest() == approved:
                if kept is None:
                    _MARKER_CLEAN_BINARIES.add((approved, marker_key))
            else:
                raise CandidateFailure(
                    f"approved binary changed: {rendered} (sha256 {digest.hexdigest()}; "
                    f"{BINARY_APPROVALS} approves {approved})"
                )
        elif binary:
            raise CandidateFailure(
                f"binary file not approved for publication: {rendered} (the scan cannot read "
                f"it as text; {BINARY_APPROVALS} names each published binary by its SHA-256)"
            )
    if not scanned:
        raise CandidateFailure(f"no file to scan under {root}")
    missing = sorted(set(approvals) - approved_seen)
    if missing:
        raise CandidateFailure(f"approved binary is missing: {', '.join(missing)}")


def refused_public_path(rendered: str) -> str | None:
    """Why a public path is refused (a private part or a secret-looking name), or None."""
    parts = tuple(part for part in rendered.split("/") if part)
    if any((part in parts) if "/" not in part else rendered == part or rendered.startswith(part + "/")
           for part in FORBIDDEN_PATH_PARTS):
        return "private path"
    if any(REFUSED_NAME.search(part) for part in parts):
        return "secret-looking name"
    return None


def _verify_paths(root: Path) -> None:
    seen = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        seen += 1
        rendered = relative.as_posix()
        if path.is_symlink():
            raise CandidateFailure(f"symlink is forbidden: {rendered}")
        reason = refused_public_path(rendered)
        if reason is not None:
            raise CandidateFailure(f"{reason} is forbidden: {rendered}")
    if not seen:
        raise CandidateFailure(f"no file to check under {root}")


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CandidateFailure(f"cannot read {path.name}: {error}") from None
    if not isinstance(value, dict):
        raise CandidateFailure(f"{path.name} is not an object")
    return value


def source_lock_sdists(source_lock: dict) -> dict[tuple[str, str], str]:
    """(lowercase name, version) -> sdist sha256, keyed as prepare_third_party_sources does."""

    return {
        (str(item["name"]).lower(), str(item["version"])): item["sha256"]
        for item in source_lock.get("packages", [])
        if isinstance(item, dict) and {"name", "version", "sha256"} <= set(item)
    }


def _verify_sha256sums(base: Path, expected: set[str]) -> None:
    entries: dict[str, str] = {}
    try:
        lines = (base / "SHA256SUMS").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as error:
        raise CandidateFailure(f"cannot read {base.name}/SHA256SUMS: {error}") from None
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\s/][^\s]*)", line)
        if match is None or ".." in match.group(2).split("/") or match.group(2) in entries:
            raise CandidateFailure(f"invalid SHA256SUMS line: {line!r}")
        entries[match.group(2)] = match.group(1)
    if set(entries) != expected:
        raise CandidateFailure(f"{base.name}/SHA256SUMS does not list exactly the shipped files")
    for relative, digest in entries.items():
        if not (base / relative).is_file() or _sha256(base / relative) != digest:
            raise CandidateFailure(f"SHA256SUMS mismatch for {relative}")


def _verify_third_party(root: Path, authority_lock: Path | None) -> None:
    candidate_lock = root / SOURCE_LOCK
    if authority_lock is not None and (
        not authority_lock.is_file() or _sha256(authority_lock) != _sha256(candidate_lock)
    ):
        raise CandidateFailure("candidate third-party source lock differs from release authority")
    bundled = sorted(relative for relative in DEPENDENCY_BUNDLE_PATHS if (root / relative).exists())
    unexpected = sorted(
        f"third_party/{path.name}" for path in (root / "third_party").iterdir()
        if path.name not in THIRD_PARTY_ENTRIES
    ) if (root / "third_party").is_dir() else []
    if bundled or unexpected:
        raise CandidateFailure(
            "candidate carries a dependency bundle the public tree does not ship "
            f"(dependency sources come from PyPI by their locked hashes): {sorted({*bundled, *unexpected})}"
        )
    locked = source_lock_sdists(_load_json(candidate_lock))
    vendor = root / "third_party" / "pyswisseph"
    _verify_sha256sums(vendor, set(PYSWISSEPH_FILES))
    if locked.get(("pyswisseph", "2.10.3.2")) != _sha256(vendor / PYSWISSEPH_FILES[0]):
        raise CandidateFailure("pyswisseph source differs from the third-party source lock")


def verify_candidate(root: Path, third_party_source_lock: Path | None = None) -> str:
    """Verify the candidate; return its tree digest, the SHA-256 of the
    PUBLICATION_FILES.json the tree was proven equal to: every file's path,
    bytes and Git executable bit.  The receipt producer binds the published
    tree to this digest, not to a re-read of the candidate directory, so a
    candidate changed after verification (content or executable bit) cannot
    be receipted."""
    root = root.resolve()
    _verify_paths(root)
    try:
        identity = observe_publication_tree(root)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        raise CandidateFailure(str(error)) from None
    scan_candidate_content(root)
    scan_comment_codes(root)
    scan_path_references(root)
    _verify_third_party(root, third_party_source_lock)
    return identity.index_sha256


PUBLIC_FILE_INVENTORY = "PUBLICATION_FILES.json"


def _inventory_paths(path: Path) -> set[str]:
    files = _load_json(path).get("files")
    entries = [entry.get("path") if isinstance(entry, dict) else None
               for entry in (files if isinstance(files, list) else [])]
    paths = {item for item in entries if isinstance(item, str) and item}
    if not paths or len(paths) != len(entries):
        raise CandidateFailure(f"{path} is not a list of distinct public file paths")
    return paths


def _public_tree_paths(root: Path) -> set[str]:
    """Regular files of a public checkout, without its Git administration and
    the release records committed after its source revision."""
    paths = {
        relative.as_posix() for path in root.rglob("*")
        if (relative := path.relative_to(root)).parts[0] != ".git" and path.is_file()
    }
    paths = {path for path in paths if path != PUBLIC_FILE_INVENTORY and not is_public_release_record(path)}
    if not paths:
        raise CandidateFailure(f"{root} holds no public files")
    return paths


def public_file_delta(root: Path, previous: Path) -> dict:
    """The public paths `root` adds and removes against the previous public
    release: its checkout (a directory) or its PUBLICATION_FILES.json.  A new
    file under an included directory is exported without a manifest entry, so
    this is where approving a candidate sees it."""
    current = _inventory_paths(root / PUBLIC_FILE_INVENTORY)
    before = _inventory_paths(previous) if previous.is_file() else _public_tree_paths(previous)
    return {"added": sorted(current - before), "removed": sorted(before - current),
            "kept": len(current & before)}


def _reconstruction_script(mode: str) -> str:
    if mode not in RECONSTRUCTION_MODES:
        raise CandidateFailure(f"unsupported reconstruction mode: {mode}")
    # The hashed build backend, then the lock without build isolation, from PyPI.
    install = '"$VENV/python" -m scripts.tools.install_dev_dependencies'
    # The concurrency test has a product timeout and measures QEMU speed here.
    return f"""set -eu
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PYTHONDONTWRITEBYTECODE=1
python -m venv /work/venv
VENV=/work/venv/bin
cd /candidate
{install}
PYTHONPATH=.:backend "$VENV/python" -m pytest -p no:cacheprovider -q \\
  tests/integration/test_hosted_live_server.py tests/integration/test_hosted_profile.py \\
  -k 'not test_concurrent_requests_do_not_cross_contaminate'
"""


def verify_dependency_reconstruction(root: Path, *, mode: str, builder_image: str) -> None:
    if not builder_image or any(character.isspace() for character in builder_image):
        raise CandidateFailure("builder image identity is missing or unsafe")
    completed = subprocess.run(
        [
            "docker", "run", "--rm", "--platform", "linux/amd64",
            "--network", "bridge",
            "--volume", f"{root.resolve()}:/candidate:ro",
            "--tmpfs", "/work:exec,size=4g",
            builder_image, "sh", "-c", _reconstruction_script(mode),
        ],
        check=False, capture_output=True, text=True,
    )
    if completed.returncode:
        detail = (completed.stderr + "\n" + completed.stdout).strip()
        raise CandidateFailure(f"{mode} dependency reconstruction failed: {detail[-8000:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--third-party-source-lock", type=Path)
    parser.add_argument("--reconstruction-mode", choices=RECONSTRUCTION_MODES)
    parser.add_argument("--builder-image", default=RECONSTRUCTION_BUILDER_IMAGE)
    parser.add_argument(
        "--previous-public", type=Path,
        help="the previous public release (its checkout, or its PUBLICATION_FILES.json): "
        "print the public paths this candidate adds and removes",
    )
    args = parser.parse_args()
    try:
        tree_sha256 = verify_candidate(args.root, args.third_party_source_lock)
        if args.reconstruction_mode:
            verify_dependency_reconstruction(
                args.root, mode=args.reconstruction_mode, builder_image=args.builder_image
            )
        delta = public_file_delta(args.root, args.previous_public) if args.previous_public else None
    except (CandidateFailure, OSError, UnicodeError) as error:
        print(f"PUBLICATION CANDIDATE FAILED: {error}", file=sys.stderr)
        return 1
    print("PUBLICATION CANDIDATE PASSED")
    print(f"verified tree sha256: {tree_sha256}  (write_publication_receipt write --verified-tree-sha256)")
    if delta is None:
        print("public file set delta: not computed (no --previous-public)")
    else:
        print(f"public file set vs {args.previous_public}: {len(delta['added'])} added, "
              f"{len(delta['removed'])} removed, {delta['kept']} kept")
        print("".join(f"  + {path}\n" for path in delta["added"])
              + "".join(f"  - {path}\n" for path in delta["removed"]), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
