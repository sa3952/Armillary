"""Closed source discovery and path validation for frontend releases."""

from __future__ import annotations

from collections.abc import Callable, Iterator
import hashlib
import os
from pathlib import Path, PurePosixPath
import stat


MANIFEST_NAME = "frontend-release.json"
DEFAULT_LOCALE_ENTRYPOINT = "zh-TW/index.html"
# Top-level tooling files in frontend/ that must never become runtime assets.
# `.json` and `.mjs` are legitimate asset suffixes, so the suffix allowlist
# alone would ship package.json and change the release digest.
EXCLUDED_SOURCE_BASENAMES = frozenset({
    # npm's project settings (engine-strict, the registry): tooling, never served.
    ".npmrc",
    "README.md",
    "eslint.config.mjs",
    "package-lock.json",
    "package.json",
    "surfaces.json",
})
IGNORED_PLATFORM_METADATA = frozenset({".DS_Store"})
EXCLUDED_SOURCE_DIRECTORIES = frozenset({"tests", "node_modules"})
# Declared, not guessed: Starlette's `mimetypes` reads the host's
# /etc/mime.types, so the same release answered sitemap.xml differently on a
# developer machine and in the container; a crawler reads the header.  Text
# types name UTF-8 (RFC 9116 requires it for security.txt); JSON has no charset
# parameter (RFC 8259 §11).
RUNTIME_MEDIA_TYPES = {
    ".avif": "image/avif",
    ".css": "text/css; charset=utf-8",
    ".gif": "image/gif",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/vnd.microsoft.icon",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".mjs": "text/javascript; charset=utf-8",
    ".otf": "font/otf",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ttf": "font/ttf",
    ".txt": "text/plain; charset=utf-8",
    ".webp": "image/webp",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".xml": "application/xml; charset=utf-8",
}
RUNTIME_SUFFIXES = frozenset(RUNTIME_MEDIA_TYPES)
# A root file whose type is more specific than its suffix's: the Atom feed is
# application/atom+xml (RFC 4287 §7), which feed readers expect and which the
# pages' <link rel="alternate"> already names.
RUNTIME_NAME_MEDIA_TYPES = {
    "feed.xml": "application/atom+xml; charset=utf-8",
}
# The branded 404 page: hashed with the release but with no address of its
# own; the static mount serves it only as a 404 body (runtime_static.py).
# scripts/frontend/build_pages.py generates it from the `error_pages` row of
# frontend/surfaces.json, which must name this output.
NOT_FOUND_PAGE = "zh-TW/404.html"
# The IndexNow ownership key, public by design: an engine receiving a
# submission (scripts/deployment/submit_indexnow.py) checks that
# https://<host>/<key>.txt holds exactly the key.  build_pages writes the file;
# a new key is one no engine has verified yet.
INDEXNOW_KEY = "bbb6ac30c1952dbb592262ea2656d708"
INDEXNOW_KEY_FILE = f"{INDEXNOW_KEY}.txt"
# Root-level discovery files, these names exactly.  build_pages generates
# llms.txt from page titles and descriptions, llms-full.txt from the methods
# page and the articles' openings, feed.xml from the article rows.
ROOT_DISCOVERY_FILES = frozenset({
    INDEXNOW_KEY_FILE,
    "feed.xml",
    "llms-full.txt",
    "llms.txt",
    "robots.txt",
    # The exported public source places the release's security.txt
    # here, so it travels inside the hashed frontend release.
    "security.txt",
    "sitemap.xml",
})
# Content version: the first 16 hex digits (64 bits) of the SHA-256 of the
# exact bytes.  build_pages writes it into every `?v=`; the cache policy grants
# immutable only when `?v=` equals the value recomputed from the served file.
# One definition for both, so the token cannot outlive its bytes.  It is a
# prefix of the manifest's full digest, so an operator can cross-check them.
ASSET_CONTENT_VERSION_HEX_DIGITS = 16
# Text formats compressed on the way out: no per-request secret, no reflected
# input.  The only compressed API body is the chart result (runtime_static.py
# says why that is safe).
COMPRESSIBLE_ASSET_SUFFIXES = frozenset({
    ".css",
    ".html",
    ".js",
    ".json",
    ".mjs",
    ".svg",
    ".txt",
    ".xml",
})


def asset_content_version(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ASSET_CONTENT_VERSION_HEX_DIGITS]


def _discovery_asset_is_allowed(entry: Path, *, at_root: bool) -> bool:
    suffix = entry.suffix.casefold()
    if suffix not in {".txt", ".xml"}:
        return True
    return at_root and entry.name in ROOT_DISCOVERY_FILES


def validate_asset_name(name: object) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise ValueError("frontend asset name is not a safe relative POSIX path")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or path.as_posix() != name
        or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
        or name == MANIFEST_NAME
    ):
        raise ValueError("frontend asset name is not a safe relative POSIX path")
    return name


def walk_regular_tree(
    root: Path,
    refuse: Callable[[PurePosixPath, bool], ValueError],
    *,
    descend: Callable[[Path, PurePosixPath], bool] = lambda _entry, _relative: True,
) -> Iterator[tuple[Path, PurePosixPath, bool]]:
    """Every entry under `root` in name order, as (path, relative path, is directory).

    Shared by source discovery and release verification: lstat once, so a
    symlink is never followed; a symlink or non-file is refused with the
    caller's error.  A directory is yielded, then walked, only if `descend`
    accepts it.
    """

    def visit(directory: Path, parent: PurePosixPath | None) -> Iterator[tuple[Path, PurePosixPath, bool]]:
        for entry in sorted(directory.iterdir(), key=lambda item: item.name):
            relative = PurePosixPath(entry.name) if parent is None else parent / entry.name
            mode = entry.lstat().st_mode
            if stat.S_ISDIR(mode):
                if descend(entry, relative):
                    yield entry, relative, True
                    yield from visit(entry, relative)
            elif stat.S_ISREG(mode):
                yield entry, relative, False
            else:
                raise refuse(relative, stat.S_ISLNK(mode))

    yield from visit(root, None)


def discover_source_assets(frontend_directory: Path) -> frozenset[str]:
    frontend = Path(os.path.abspath(frontend_directory))
    if not stat.S_ISDIR(frontend.lstat().st_mode):
        raise ValueError("frontend source must be a non-symlink directory")

    def unsafe(relative: PurePosixPath, _symlink: bool = False) -> ValueError:
        return ValueError(f"unsafe frontend source entry: {relative}")

    def descend(entry: Path, relative: PurePosixPath) -> bool:
        if len(relative.parts) == 1 and entry.name in EXCLUDED_SOURCE_DIRECTORIES:
            return False
        if entry.name.startswith("."):
            raise unsafe(relative)
        return True

    assets: set[str] = set()
    for entry, relative, is_directory in walk_regular_tree(frontend, unsafe, descend=descend):
        at_root = len(relative.parts) == 1
        if is_directory or entry.name in IGNORED_PLATFORM_METADATA:
            continue
        if at_root and entry.name in EXCLUDED_SOURCE_BASENAMES:
            continue
        if entry.name.startswith("."):
            raise unsafe(relative)
        name = validate_asset_name(relative.as_posix())
        if entry.suffix.casefold() not in RUNTIME_SUFFIXES:
            raise ValueError(f"unsupported frontend asset: {name}")
        if not _discovery_asset_is_allowed(entry, at_root=at_root):
            raise ValueError(f"unsupported frontend discovery asset: {name}")
        assets.add(name)
    if DEFAULT_LOCALE_ENTRYPOINT not in assets:
        raise ValueError(
            f"frontend release requires {DEFAULT_LOCALE_ENTRYPOINT}"
        )
    return frozenset(assets)


def asset_parent_directories(assets: set[str] | frozenset[str]) -> frozenset[str]:
    parents: set[str] = set()
    for name in assets:
        path = PurePosixPath(validate_asset_name(name))
        for parent in path.parents:
            if parent != PurePosixPath("."):
                parents.add(parent.as_posix())
    return frozenset(parents)
