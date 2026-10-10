#!/usr/bin/env python3
"""Fail closed on a public source tree that leaks private material or is incomplete.

Checked here: the closed file list (PUBLICATION_FILES.json), no symlink or
private path, no private marker, personal data, secret or private-record
reference in any byte, and the third-party sources against the committed
source lock.  Whether the tree builds and its tests pass is the public
repository CI's job (its scripts/verify_delivery.py).

`--reconstruction-mode` additionally rebuilds the dependency set in a pinned
Linux builder; Gate F runs it only when the locks or third_party/ changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
from pathlib import Path

from scripts.publication.prepare_third_party_sources import (
    DEPENDENCY_SOURCE_BUILD_PACKAGES,
    MAX_ARCHIVE_MEMBER_BYTES,
    SourcePreparationError,
    license_evidence_complete,
    parse_lock,
    render_dependency_license_table,
    verify_manifest_lock_inputs,
)
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
SECRET_PATTERNS = {
    "private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\bgh[opsu]_[A-Za-z0-9_]{20,}\b"),
    "GitHub fine-grained token": re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{22,}\b"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Google API key": re.compile(rb"\bAIza[A-Za-z0-9_-]{35}\b"),
    "Slack token": re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "Stripe live key": re.compile(rb"\bsk_live_[A-Za-z0-9]{20,}\b"),
    "generic API token": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    # A line that assigns a literal to a password, secret, token or key name,
    # as an env file, shell profile or config does (`DB_PASSWORD=...`).  Code
    # that assigns an expression, a number or a ${reference} is not matched.
    "credential assignment": re.compile(
        rb"(?im)^[ \t]*(?:export[ \t]+)?[A-Za-z0-9_.-]*"
        rb"(?:pass" rb"word|passwd|sec" rb"ret|tok" rb"en|api[_-]?key|private[_-]?key|access[_-]?key)"
        rb"[A-Za-z0-9_.-]*[ \t]*[:=][ \t]*[\"']?(?=[^\s\"']*[A-Za-z])[^\s\"'$(){}\[\]<>,;]{6,}[\"']?"
        rb"[ \t]*(?:#.*)?$"
    ),
}
SOURCE_LOCK = "publication/third_party_source_lock.json"
PYSWISSEPH_FILES = (
    "pyswisseph-2.10.3.2.tar.gz", "LICENSE.txt", "SWISS_EPHEMERIS_LICENSE",
    "SWEPHELP_LICENSE", "SWEPHELP_README.txt",
)
RECONSTRUCTION_BUILDER_IMAGE = (
    "python:3.14.8-trixie@"
    "sha256:d0ef532dea88a06a0f950a40f95c553086c1f282bf8e313d328f11d289f72582"
)


class CandidateFailure(RuntimeError):
    """Raised when a public candidate is unsafe or incomplete."""


BINARY_SNIFF_BYTES = 8192


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


def _verify_license_files(archive: Path, package: dict) -> None:
    if not license_evidence_complete(package):
        raise CandidateFailure(f"license evidence incomplete for {package.get('name')}")
    try:
        with tarfile.open(archive, "r:gz") as source:
            members = {member.name: member for member in source.getmembers() if member.isfile()}
            for relative in package["license_files"]:
                member = members.get(relative)
                handle = (
                    source.extractfile(member)
                    if member is not None and member.size <= MAX_ARCHIVE_MEMBER_BYTES else None
                )
                if handle is None or hashlib.sha256(handle.read()).hexdigest() != (
                    package["license_file_sha256"][relative]
                ):
                    raise CandidateFailure(f"license file differs for {package['name']}: {relative}")
    except (OSError, tarfile.TarError) as error:
        raise CandidateFailure(f"cannot inspect licenses of {package['name']}: {error}") from None


def _verify_third_party(root: Path, authority_lock: Path | None, require_bundle: bool) -> None:
    candidate_lock = root / SOURCE_LOCK
    if authority_lock is not None and (
        not authority_lock.is_file() or _sha256(authority_lock) != _sha256(candidate_lock)
    ):
        raise CandidateFailure("candidate third-party source lock differs from release authority")
    locked = source_lock_sdists(_load_json(candidate_lock))
    vendor = root / "third_party" / "pyswisseph"
    _verify_sha256sums(vendor, set(PYSWISSEPH_FILES))
    if locked.get(("pyswisseph", "2.10.3.2")) != _sha256(vendor / PYSWISSEPH_FILES[0]):
        raise CandidateFailure("pyswisseph source differs from the third-party source lock")
    bundle = root / "third_party"
    if not (bundle / "SHA256SUMS").is_file():
        if require_bundle:
            raise CandidateFailure("third-party source bundle is absent")
        return
    manifest = _load_json(bundle / "SOURCE_MANIFEST.json")
    shipped: set[str] = set()
    for package in manifest.get("packages", []):
        archive = bundle / "sources" / str(package.get("filename", ""))
        key = (str(package.get("name", "")).lower(), str(package.get("version", "")))
        if not archive.is_file() or _sha256(archive) != package.get("sha256"):
            raise CandidateFailure(f"source archive differs for {package.get('name')}")
        # The candidate's own manifest is not the authority; the committed lock is.
        if locked.get(key) != package["sha256"]:
            raise CandidateFailure(f"retained sdist is not the source-lock artifact for {key[0]}")
        _verify_license_files(archive, package)
        shipped.add(f"sources/{package['filename']}")
    for index_name, directory, lock, source_built in (
        ("build_wheel_index", "build_wheels", "deploy/build-requirements.lock", frozenset()),
        ("dependency_wheel_index", "dependency_wheels", "backend/requirements-dev.lock",
         DEPENDENCY_SOURCE_BUILD_PACKAGES),
    ):
        index = manifest.get(index_name)
        if not isinstance(index, dict):
            raise CandidateFailure(f"{index_name} is missing")
        artifacts = index.get("artifacts")
        try:
            wanted = [p for p in parse_lock(root / lock, index_name) if p["name"].lower() not in source_built]
        except (OSError, SourcePreparationError) as error:
            raise CandidateFailure(f"{index_name}: cannot read {lock}: {error}") from None
        # One retained wheel per lock entry, as the producer requires; an
        # incomplete or empty index would leave the offline rebuild nothing.
        if (
            index.get("complete") is not True
            or not isinstance(artifacts, list)
            or not artifacts
            or len(artifacts) != len(wanted)
        ):
            raise CandidateFailure(
                f"{index_name} is incomplete: {len(artifacts) if isinstance(artifacts, list) else 0} "
                f"wheel artifact(s) for {len(wanted)} {lock} entries"
            )
        # SHA256SUMS is written with the bundle; the committed lock's hashes are the authority.
        allowed = {digest for package in wanted for digest in package["allowed_sha256"]}
        for artifact in artifacts:
            if f"sources/{artifact.get('source_sdist_filename')}" not in shipped:
                raise CandidateFailure(f"wheel lacks a retained sdist: {artifact.get('filename')}")
            filename = str(artifact.get("filename", ""))
            wheel = bundle / directory / filename
            if (
                Path(filename).name != filename
                or wheel.is_symlink()
                or not wheel.is_file()
                or _sha256(wheel) != artifact.get("sha256")
                or artifact.get("sha256") not in allowed
            ):
                raise CandidateFailure(f"retained wheel is not the lock's artifact: {filename!r}")
            shipped.add(f"{directory}/{filename}")
    _verify_sha256sums(bundle, shipped)
    try:
        verify_manifest_lock_inputs(manifest, {
            "production": root / "deploy/requirements.lock",
            "build": root / "deploy/build-requirements.lock",
            "development": root / "backend/requirements-dev.lock",
        })
        table = render_dependency_license_table(manifest)
    except SourcePreparationError as error:
        raise CandidateFailure(str(error)) from None
    if (root / "docs/DEPENDENCY_LICENSES.md").read_text(encoding="utf-8") != table:
        raise CandidateFailure("human-readable dependency license table has drifted")


def verify_candidate(
    root: Path,
    third_party_source_lock: Path | None = None,
    *,
    require_third_party_sources: bool = False,
) -> str:
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
    _verify_third_party(root, third_party_source_lock, require_third_party_sources)
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
    if mode == "online-clean":
        # The hashed build backend, then the lock without build isolation.
        install = '"$VENV/python" -m scripts.tools.install_dev_dependencies'
    elif mode == "offline-source-only":
        install = (
            '"$VENV/pip" install --no-index --find-links=third_party/build_wheels '
            "--require-hashes --requirement deploy/build-requirements.lock\n"
            '"$VENV/pip" install --no-index --find-links=third_party/dependency_wheels '
            "--find-links=third_party/sources --only-binary=:all: --no-binary=pyswisseph "
            "--no-build-isolation --require-hashes --requirement backend/requirements-dev.lock"
        )
    else:
        raise CandidateFailure(f"unsupported reconstruction mode: {mode}")
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
            "--network", "none" if mode == "offline-source-only" else "bridge",
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
    parser.add_argument(
        "--require-third-party-sources", action="store_true",
        help="a release candidate must carry the vendored sdist bundle",
    )
    parser.add_argument("--reconstruction-mode", choices=("online-clean", "offline-source-only"))
    parser.add_argument("--builder-image", default=RECONSTRUCTION_BUILDER_IMAGE)
    parser.add_argument(
        "--previous-public", type=Path,
        help="the previous public release (its checkout, or its PUBLICATION_FILES.json): "
        "print the public paths this candidate adds and removes",
    )
    args = parser.parse_args()
    try:
        tree_sha256 = verify_candidate(
            args.root, args.third_party_source_lock,
            require_third_party_sources=args.require_third_party_sources,
        )
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
