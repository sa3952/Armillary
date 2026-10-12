"""Source-tree identity for the delivery and publication tools.

`observe_source_tree` digests a tree: in a Git checkout its maintained paths
(tracked plus untracked, not ignored) with their bytes, symlink targets and
executable bits, and the index; in a checkout without `.git`, the published
tree against its PUBLICATION_FILES.json (`observe_publication_tree`).  The
public tree's verify_delivery is its consumer.

The mutation gate (`make mutation`, private) does not use that
identity: it takes only the path list, `maintained_source_paths`, and copies
those paths from the working tree as it is, dirty or not; only its `--receipt`
mode requires a clean checkout and names its revision.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile


# A public release record, `releases/<release version>/frontend-release.json`,
# is committed to the public repository after the source revision it describes
# (runbook: the frontend release receipt is published with every release).  It
# is never part of an exported candidate and so never in PUBLICATION_FILES.json.
# Every comparison of a public tree against that inventory accepts these paths
# as additions, and only these, so the records of earlier releases stay at the
# tip of the default branch.  The version segment is the receipt consumer's
# RELEASE_VERSION_RE (scripts/deployment/frontend_release.py); a test keeps them equal.
PUBLIC_RELEASE_RECORD = re.compile(r"releases/[A-Za-z0-9][A-Za-z0-9._-]{0,63}/frontend-release\.json")


def is_public_release_record(relative: str) -> bool:
    return PUBLIC_RELEASE_RECORD.fullmatch(relative) is not None


@dataclass(frozen=True)
class SourceTreeIdentity:
    paths: tuple[str, ...]
    content_sha256: str
    index_sha256: str


# PUBLICATION_FILES.json format: every published file's path, size, SHA-256 and
# Git executable bit.  Its own SHA-256 is the candidate digest an operator
# approves, so it names everything Git publishes for a file and nothing Git
# drops (other permission bits, directories).
PUBLICATION_INVENTORY_SCHEMA = 2


def git_executable(mode: int) -> bool:
    """The executable bit as Git records it (100755 when the owner may execute)."""
    return bool(mode & stat.S_IXUSR)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(["git", *arguments], cwd=root, check=True, capture_output=True)
    return completed.stdout


def maintained_source_paths(root: Path) -> tuple[str, ...]:
    output = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = tuple(sorted(raw.decode("utf-8") for raw in output.split(b"\0") if raw))
    if not paths:
        raise RuntimeError("maintained source universe is empty")
    return paths


def observe_publication_tree(root: Path) -> SourceTreeIdentity:
    manifest_path = root / "PUBLICATION_FILES.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read publication identity: {error}") from None
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != PUBLICATION_INVENTORY_SCHEMA
        or manifest.get("hash_algorithm") != "sha256"
        or not isinstance(entries, list)
        or not entries
    ):
        raise RuntimeError("invalid publication identity")
    # The inventory names every other file's executable bit; its own is fixed.
    if git_executable(manifest_path.lstat().st_mode):
        raise RuntimeError("publication file mode changed: PUBLICATION_FILES.json")
    expected: dict[str, tuple[int, str, bool]] = {}
    for entry in entries:
        relative = Path(str(entry.get("path", ""))) if isinstance(entry, dict) else Path()
        size = entry.get("size_bytes") if isinstance(entry, dict) else None
        digest = entry.get("sha256") if isinstance(entry, dict) else None
        executable = entry.get("executable") if isinstance(entry, dict) else None
        rendered = relative.as_posix()
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or rendered in expected
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or type(executable) is not bool
        ):
            raise RuntimeError("invalid publication file entry")
        expected[rendered] = (size, digest, executable)
    actual: dict[str, Path] = {}
    directories: set[str] = set()
    release_records: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git" or path == manifest_path:
            continue
        mode = path.lstat().st_mode
        rendered = relative.as_posix()
        if stat.S_ISDIR(mode):
            directories.add(rendered)
        elif stat.S_ISREG(mode):
            if rendered not in expected and is_public_release_record(rendered):
                release_records.add(rendered)
                continue
            actual[rendered] = path
        else:
            raise RuntimeError(f"unsupported publication object: {rendered}")

    def parents(names: set[str] | dict[str, Path]) -> set[str]:
        return {
            parent.as_posix()
            for relative_name in names
            for parent in Path(relative_name).parents
            if parent != Path(".")
        }

    implied_directories = parents(actual)
    if directories != implied_directories | parents(release_records):
        raise RuntimeError("publication directory identity changed")
    # Release records and the directories only they imply stay outside the
    # identity: it names the published source, not the records added after it.
    directories = implied_directories
    if set(actual) != set(expected):
        raise RuntimeError("publication file set changed")
    content = hashlib.sha256()
    for relative_name in sorted(directories):
        target = root / relative_name
        content.update(relative_name.encode("utf-8"))
        content.update(b"\0directory\0")
        content.update(f"{stat.S_IMODE(target.lstat().st_mode):04o}".encode("ascii"))
        content.update(b"\0")
    for relative_name in sorted(expected):
        target = actual[relative_name]
        size, digest, executable = expected[relative_name]
        observed = hashlib.sha256(target.read_bytes()).hexdigest()
        if target.stat().st_size != size or observed != digest:
            raise RuntimeError(f"publication file changed: {relative_name}")
        if git_executable(target.lstat().st_mode) is not executable:
            raise RuntimeError(f"publication file mode changed: {relative_name}")
        content.update(relative_name.encode("utf-8"))
        content.update(b"\0")
        content.update(b"file\0")
        content.update(f"{stat.S_IMODE(target.lstat().st_mode):04o}".encode("ascii"))
        content.update(b"\0")
        content.update(bytes.fromhex(observed))
    paths = tuple(sorted({*directories, *actual, manifest_path.name}))
    return SourceTreeIdentity(
        paths, content.hexdigest(), hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    )


def observe_source_tree(root: Path) -> SourceTreeIdentity:
    if not (root / ".git").exists():
        return observe_publication_tree(root)
    indexed_paths = maintained_source_paths(root)
    paths = tuple(
        relative for relative in indexed_paths if (root / relative).exists() or (root / relative).is_symlink()
    )
    content = hashlib.sha256()
    for relative in paths:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise RuntimeError(f"unsafe maintained source path: {relative!r}")
        source = root / relative_path
        mode = source.lstat().st_mode
        content.update(relative.encode("utf-8"))
        content.update(b"\0")
        if stat.S_ISLNK(mode):
            content.update(b"symlink\0")
            content.update(os.readlink(source).encode("utf-8"))
        elif stat.S_ISREG(mode):
            content.update(b"executable\0" if git_executable(mode) else b"regular\0")
            content.update(source.read_bytes())
        else:
            raise RuntimeError(f"unsupported maintained source type: {relative!r}")
        content.update(b"\n")
    index = hashlib.sha256(_git(root, "ls-files", "-s", "-z")).hexdigest()
    return SourceTreeIdentity(paths, content.hexdigest(), index)


def materialize_git_snapshot(
    root: Path, revision: str, destination: Path, paths: tuple[str, ...] = ()
) -> Path:
    """Extract `revision` (optionally only `paths` of it) from Git's object store."""
    destination.mkdir(parents=True)
    process = subprocess.Popen(
        ["git", "archive", "--format=tar", revision, *(("--", *paths) if paths else ())],
        cwd=root,
        stdout=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("cannot read Git archive")
    try:
        with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
            archive.extractall(destination, filter="data")
    finally:
        process.stdout.close()
    if process.wait() != 0:
        raise RuntimeError("cannot materialize exact Git snapshot")
    return destination
