#!/usr/bin/env python3
"""Fail closed on a public source tree that leaks private material or is incomplete.

Checked here: the closed file list (PUBLICATION_FILES.json), no symlink or
private path, no private marker, personal data, secret or private-record
reference in any byte, no ticket or ruling id in a comment, no named path
the tree does not carry, the vendored pyswisseph source against the committed
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
import io
import json
import re
import subprocess
import sys
import tokenize
from pathlib import Path

from scripts.tools.source_tree_identity import (
    is_public_release_record, observe_publication_tree, sha256_file as _sha256,
)


FORBIDDEN_PATH_PARTS = {
    ".DS_Store", ".env", ".pytest_cache", "__pycache__",
    "docs/archive", "docs/development", "docs/red_team",
}
# Names that hold credentials, keys or private notes.  The exporter and this
# verifier refuse a public path with any of them through refused_public_path,
# the one path rule both gates apply.
REFUSED_NAME = re.compile(
    r"(?:^|\.)env(?:\.|$)|secret|passw(?:or)?d|credential|private"
    r"|\.(?:pem|key|p12|pfx|jks|keystore)$|^id_(?:rsa|dsa|ecdsa|ed25519)(?:\.|$)",
    re.IGNORECASE,
)
# The one denylist of the public tree.  The exporter, this verifier and the
# publication tests all scan with these four tables: FORBIDDEN_TEXT (literals,
# every file), PRIVATE_RECORD_PATTERNS and SECRET_PATTERNS (text files), and
# PUBLIC_FILE_PATTERNS (text files; data an API answer may legitimately carry).
# Split so that this public verifier does not match itself.
FORBIDDEN_TEXT = {
    "/" + "Users" + "/",
    "treatment" + "-resistant",
    "@" + "gmail.com",
    "信任說明草案待 " + "Sebastian 定稿",
    # Internal-record references and operator remarks: public files cite public
    # method-source ids and published documents, never the private evidence
    # folders, research notes, agent work areas or ruling records.
    "local" + "-evidence",
    "docs/" + "decisions/",
    "internal" + " record:",
    "(internal" + " record)",
    "（內部" + "紀錄）",
    "RULINGS" + "_",
    "/private" + "/tmp",
    "work" + "trees/",
    "codex" + "-review",
    "open_items" + ".json",
    # The private contracts, register and agent rules: a public file names
    # what they hold in words ("the output contract"), not the file.
    "OUTPUT_CONTRACT" + ".md",
    "EXPORT_CONTRACT" + ".md",
    "DECISION_REGISTER" + ".md",
    "AGENTS" + ".md",
    "UNIFIED" + "_REGISTER",
    "ALL" + "_VERIFIED",
    "CURRENT" + "_HANDOFF",
    "Sebastian" + " wanted",
    "Sebastian" + " 的要求",
    "Sebastian" + "'s request",
    "依 Sebastian" + " 指示",
    # The private configuration generator: published files say "(private)
    # configuration generator", never its module name.
    "render_staging" + "_nginx",
}
PRIVATE_RECORD_PATTERNS = {
    "agent evidence folder": re.compile(
        rb"claude-(?:opus|fable|sonnet|haiku)-[0-9]", re.IGNORECASE
    ),
    "wave work area": re.compile(rb"\bwave-[0-9]+/", re.IGNORECASE),
    "private research folder": re.compile(rb"/research/(?:sources|[A-Z_]+_20[0-9]{2})"),
    "numbered research-note entry": re.compile(
        "(?:research notes?|研究筆記) ?Q[0-9]".encode("utf-8"), re.IGNORECASE
    ),
    # A ruling cited by the owner's name and a date, by a month-day and an item
    # number or by its list number; a decision-register row; a numbered
    # research-list entry; a code value that carries a ruling date.
    "decision-list reference": re.compile(
        (
            r"Sebastian(?:'s)?,? ?(?:ruling )?(?:R[0-9]|[0-9]{4}-[0-9]{2}-[0-9]{2}|\([0-9]{4})"
            r"|(?<![0-9-])(?:[0-9]{4}-)?[01][0-9]-[0-3][0-9] ?(?:#|R|P)[0-9]"
            r"|裁決 ?(?:#|[A-Z]+-?)[0-9]|ruling #[0-9]|Decision" r" Register"
            r"|\b(?:SD|MTH|MTH-Q|BD|PUB|PRIV|GOV-RULE|DEC-DIR|RUL)-[0-9]{2,3}\b"
            r"|\blit[AB] [A-Za-z]-?[0-9]|sebastian_[a-z_]*[0-9]{4}"
        ).encode("utf-8")
    ),
}
# A specific former example place stood for the calculator's synthetic
# example; published files use the catalog's Tainan point.  The binary place
# catalog lists every place and is not searched for patterns.
PUBLIC_FILE_PATTERNS = {
    "former example place": re.compile(
        "tai" "chung|臺" "中|台" "中|24\\.14(?:77|69)|120\\.6(?:736|839)".encode("utf-8"),
        re.IGNORECASE,
    ),
}
_CREDENTIAL_NAME = (
    rb"[A-Za-z0-9_.-]*"
    rb"(?:pass" rb"word|passwd|sec" rb"ret|tok" rb"en|api[_-]?key|private[_-]?key|access[_-]?key)"
    rb"[A-Za-z0-9_.-]*"
)
# At least six characters, one of them a letter, none a quote, space or template sigil.
_CREDENTIAL_LITERAL = rb"(?=[^\s\"']*[A-Za-z])[^\s\"'$(){}\[\]<>,;]{6,}"
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
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


# Ticket and ruling ids of the private project.  A comment keeps the reason and
# drops the id: a reader of the public tree cannot open the record it names.
# The private tests bind this list to every id prefix the project's decision
# register and open items use; DH and AR label review findings, T the time-lord
# specification's items and D the questions a review puts to the owner.  A prefix may carry one round digit (R2, CX2)
# and must start a word, so SHA-256, UTC-10, Etc/GMT-8 and a 2D-3 grid do not match.
INTERNAL_CODE_PREFIXES = (
    "GOV-RULE", "GOV-C", "GOV-Q", "GOV", "MTH-Q", "MTH", "PUB-Q", "PUB", "DEC-DIR",
    "R-FIX", "FRONTEND", "RECEIPT", "SUPPLY", "ASTRO", "CONST", "XDOM", "I18N", "PRIV",
    "GATE", "TIME", "OPS", "API", "CLN", "SEC", "RUL", "FE", "CX", "GK", "SD", "BD", "RT",
    "DH", "AR", "R", "C", "V", "T", "D",
)
INTERNAL_CODE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:" + "|".join(map(re.escape, INTERNAL_CODE_PREFIXES))
    + r")[0-9]?-[0-9]{1,4}(?![0-9])"
    r"|(?<![A-Za-z0-9_])r[0-9]ops-[0-9]"
    r"|(?:裁決|ruling)\s*#\s*[0-9]"
    r"|Claude Security F[0-9]"
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
    return [(text.count("\n", 0, match.start()) + 1, match.group(0)) for match in pattern.finditer(text)]


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


def comment_code_lines(
    relative: str, data: bytes, pattern: re.Pattern[str] = INTERNAL_CODE,
) -> list[tuple[int, str]]:
    """(line, id) for every match of `pattern` in the comments (or prose) of one file."""
    return [
        (line + part.count("\n", 0, match.start()), match.group(0))
        for line, part in comment_parts(relative, data) or []
        for match in pattern.finditer(part)
    ]


def comment_codes(relative: str, data: bytes) -> list[str]:
    """Internal ids in the comments (or prose) of one file; [] for a data file."""
    return [code for _line, code in comment_code_lines(relative, data)]


def scan_comment_codes(root: Path) -> None:
    """Fail on a ticket or ruling id in a comment of any file outside third_party/."""
    scanned = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] in {".git", "third_party"}:
            continue
        scanned += 1
        codes = comment_codes(relative.as_posix(), path.read_bytes())
        if codes:
            raise CandidateFailure(
                f"internal ticket or ruling id {codes[0]!r} in a comment of {relative.as_posix()}"
            )
    if not scanned:
        raise CandidateFailure(f"no file to scan under {root}")


# A repository path a public file names must be one the tree carries: a reader
# cannot open a private document, tool or record.  The two tables below name
# every exception with its reason (strings split so this file names no path).
_REPOSITORY_PATH = re.compile(
    r"(?<![\w.-])((?:backend|deploy|docs|frontend|publication|scripts|tests|third_party)"
    r"/[\w./*{},-]*[\w/*}]|AGENTS\.md|CLAUDE\.md)"
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
    "scripts/publication/verify_publication_candidate.py": (
        "the private directories this denylist refuses",
        frozenset({"docs/" "archive", "docs/" "development", "docs/" "red_team"}),
    ),
    "scripts/verification/verify_docker_context.py": (
        "probes: paths the image build context must deny or never copy",
        frozenset({
            "AGENTS" ".md", "docs/" "README.md", "backend/" "app/.env", "backend/" "app/x.pem",
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


def _names_a_published_path(root: Path, reference: str) -> bool:
    if any(character in reference for character in "*{"):
        pattern = re.sub(r"\{[^}]*\}", "*", reference)
        return any(root.glob(pattern))
    if (root / reference).exists() or (root / f"{reference}.py").is_file():
        return True
    # `module.attribute`: the path of a module and a name inside it.
    module, _, attribute = reference.rpartition(".")
    return bool(module) and attribute.isidentifier() and (root / f"{module}.py").is_file()


def path_references(root: Path, relative: str, data: bytes) -> list[str]:
    """Repository paths one public file names that the tree does not carry."""
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return []
    named = {
        match.group(1).rstrip("./") for match in _REPOSITORY_PATH.finditer(text)
        # After a lone `/` it is an absolute or URL path, not one of the tree;
        # after `../` it is relative to the tree.
        if text[max(0, match.start() - 1):match.start()] != "/"
        or text[max(0, match.start() - 2):match.start()] == "./"
    }
    # A module the way `python -m` and imports name it (a module or a package).
    named |= {match.group(0).replace(".", "/") for match in _MODULE_PATH.finditer(text)}
    site = UNPUBLISHED_REFERENCE_SITES.get(relative, ("", frozenset()))[1]
    return sorted(
        reference for reference in named
        if reference not in site
        and not reference.startswith(tuple(UNPUBLISHED_PATH_CLASSES))
        and not _names_a_published_path(root, reference)
    )


def scan_path_references(root: Path) -> None:
    """Fail on a public file outside third_party/ that names an unpublished path."""
    scanned = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or relative.parts[0] in {".git", "third_party"}:
            continue
        scanned += 1
        missing = path_references(root, relative.as_posix(), path.read_bytes())
        if missing:
            raise CandidateFailure(
                f"{relative.as_posix()} names unpublished path(s): {', '.join(missing)}"
            )
    if not scanned:
        raise CandidateFailure(f"no file to scan under {root}")


def scan_candidate_content(
    root: Path,
    *,
    forbidden_markers: set[str] = FORBIDDEN_TEXT,
    secret_patterns: dict[str, re.Pattern[bytes]] | None = None,
) -> None:
    """Scan every regular file's bytes outside `.git`, whatever its suffix.

    Every byte of every file is searched, case-insensitively, for the literal
    markers.  The patterns are searched in text files only: a file with a NUL
    byte in its first 8 KiB is binary (the 80 MB place catalog, ephemeris
    files, archives, images).  Regular expressions over those bytes took about
    25 s per export and cannot match what a person wrote; the literal markers
    (paths, addresses, record names) still cover them.
    """

    patterns = tuple((
        {**SECRET_PATTERNS, **PRIVATE_RECORD_PATTERNS, **PUBLIC_FILE_PATTERNS}
        if secret_patterns is None else secret_patterns
    ).items())
    literals = tuple(
        (marker, marker.encode("utf-8").lower()) for marker in sorted(forbidden_markers)
    )
    overlap = max([512, *(len(value) for _, value in literals)])
    scanned = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or ".git" in relative.parts:
            continue
        scanned += 1
        tail, text = b"", None
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    if text is None:
                        text = b"\0" not in chunk[:BINARY_SNIFF_BYTES]
                    window = tail + chunk
                    lowered = window.lower()
                    for marker, encoded in literals:
                        if encoded in lowered:
                            raise CandidateFailure(
                                f"private marker {marker!r} in {relative.as_posix()}"
                            )
                    if text:
                        for label, pattern in patterns:
                            if pattern.search(window):
                                raise CandidateFailure(
                                    f"possible {label} in {relative.as_posix()}"
                                )
                    tail = window[-overlap:]
        except OSError as error:
            raise CandidateFailure(f"cannot scan {relative.as_posix()}: {error}") from None
    if not scanned:
        raise CandidateFailure(f"no file to scan under {root}")


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
