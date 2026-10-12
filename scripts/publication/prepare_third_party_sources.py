#!/usr/bin/env python3
"""Download and verify exact source distributions for locked dependencies.

Every package the requirement locks pin must have exactly the sdist the
committed source lock names: PyPI's declared SHA-256 and the downloaded bytes
are both checked against it, and each sdist must carry license evidence.  The
public tree ships none of these archives; this is how a reader obtains them,
and Gate F runs it (into a throwaway directory) whenever a lock changed.
"""

from __future__ import annotations

import argparse
import email.policy
import hashlib
import json
import re
import shutil
import sys
import tarfile
import urllib.error
import urllib.request
import urllib.parse
from email.parser import BytesParser
from pathlib import Path
from typing import Any

from scripts.tools.output_confinement import external_output_path
from scripts.tools.source_tree_identity import sha256_file as _sha256


PACKAGE_LINE = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\s\\]+)")
HASH_LINE = re.compile(r"--hash=sha256:([0-9a-f]{64})")
PYPI_JSON = "https://pypi.org/pypi/{name}/{version}/json"
USER_AGENT = "classical-astrology-corresponding-source/1"
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_SOURCE_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 50_000
MAX_ARCHIVE_MEMBER_BYTES = 32 * 1024 * 1024
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SourcePreparationError(RuntimeError):
    """Raised when exact third-party source cannot be proven."""


def parse_lock(path: Path, role: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        package_match = PACKAGE_LINE.match(line)
        if package_match:
            current = {
                "name": package_match.group(1),
                "version": package_match.group(2),
                "roles": [role],
                "allowed_sha256": [],
            }
            packages.append(current)
            continue
        hash_match = HASH_LINE.search(line)
        if hash_match and current is not None:
            current["allowed_sha256"].append(hash_match.group(1))
            continue
        if stripped == "\\":
            continue
        raise SourcePreparationError(f"unsupported dependency-lock directive in {path}: {stripped}")
    if not packages or any(not item["allowed_sha256"] for item in packages):
        raise SourcePreparationError(f"cannot parse complete hashes from {path}")
    return packages


def _request_json(url: str) -> dict[str, Any]:
    _require_https_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _https_only_opener().open(  # nosemgrep: dynamic-urllib-use-detected
        request, timeout=30
    ) as response:
        _require_https_url(response.geturl())
        body = _read_bounded(response, MAX_METADATA_BYTES, "PyPI metadata")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            raise SourcePreparationError("PyPI metadata is not valid JSON") from error
        if not isinstance(payload, dict):
            raise SourcePreparationError("PyPI metadata root must be an object")
        return payload


def _download(url: str, destination: Path) -> None:
    _require_https_url(url)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with (
        _https_only_opener().open(  # nosemgrep: dynamic-urllib-use-detected
            request, timeout=60
        ) as response,
        destination.open("wb") as output,
    ):
        _require_https_url(response.geturl())
        content_length = response.headers.get("Content-Length")
        if content_length is not None and int(content_length) > MAX_SOURCE_ARCHIVE_BYTES:
            raise SourcePreparationError("source archive exceeds bounded byte limit")
        written = 0
        while True:
            chunk = response.read(min(1024 * 1024, MAX_SOURCE_ARCHIVE_BYTES - written + 1))
            if not chunk:
                break
            written += len(chunk)
            if written > MAX_SOURCE_ARCHIVE_BYTES:
                raise SourcePreparationError("source archive exceeds bounded byte limit")
            output.write(chunk)


def _read_bounded(handle, limit: int, label: str) -> bytes:
    headers = getattr(handle, "headers", {})
    content_length = headers.get("Content-Length") if headers is not None else None
    if content_length is not None and int(content_length) > limit:
        raise SourcePreparationError(f"{label} exceeds bounded byte limit")
    body = handle.read(limit + 1)
    if len(body) > limit:
        raise SourcePreparationError(f"{label} exceeds bounded byte limit")
    return body


def _require_https_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourcePreparationError("third-party source URL must use credential-free HTTPS")


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirect targets before urllib can contact them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _require_https_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _https_only_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_HttpsOnlyRedirectHandler())


def _inspect_sdist_license(archive: Path) -> dict[str, Any]:
    inferred_expressions: set[str] = set()
    try:
        with tarfile.open(archive, "r:gz") as source:
            members = [member for member in source.getmembers() if member.isfile()]
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise SourcePreparationError("source archive has too many members")
            if any(member.size > MAX_ARCHIVE_MEMBER_BYTES for member in members):
                raise SourcePreparationError("source archive member exceeds bounded limit")
            pkg_info = next((member for member in members if member.name.endswith("/PKG-INFO")), None)
            if pkg_info is None:
                raise SourcePreparationError(f"source archive has no PKG-INFO: {archive.name}")
            handle = source.extractfile(pkg_info)
            if handle is None:
                raise SourcePreparationError(f"cannot read PKG-INFO: {archive.name}")
            metadata = BytesParser(policy=email.policy.default).parsebytes(
                _read_bounded(handle, MAX_ARCHIVE_MEMBER_BYTES, "PKG-INFO")
            )
            root = pkg_info.name.rsplit("/", 1)[0]
            declared = metadata.get_all("License-File") or []
            candidates = []
            for raw in declared:
                normalized = Path(str(raw)).as_posix()
                candidates.append(f"{root}/{normalized}")
            if not candidates:
                candidates = [
                    member.name
                    for member in members
                    if len(Path(member.name).parts) == 2
                    and Path(member.name).name.lower().startswith(("license", "copying", "notice"))
                ]
            license_files = sorted(set(candidates))
            license_hashes: dict[str, str] = {}
            member_map = {member.name: member for member in members}
            for relative in license_files:
                member = member_map.get(relative)
                if member is None:
                    raise SourcePreparationError(
                        f"declared license file missing in {archive.name}: {relative}"
                    )
                license_handle = source.extractfile(member)
                if license_handle is None:
                    raise SourcePreparationError(f"cannot read license file in {archive.name}: {relative}")
                license_bytes = _read_bounded(license_handle, MAX_ARCHIVE_MEMBER_BYTES, "license file")
                license_hashes[relative] = hashlib.sha256(license_bytes).hexdigest()
                license_text = license_bytes.decode("utf-8", errors="replace")
                if all(
                    marker in license_text
                    for marker in (
                        "MIT License",
                        "Permission is hereby granted, free of charge",
                        'THE SOFTWARE IS PROVIDED "AS IS"',
                    )
                ):
                    inferred_expressions.add("MIT")
    except (OSError, tarfile.TarError) as exc:
        raise SourcePreparationError(
            f"cannot inspect source license evidence: {archive.name}: {exc}"
        ) from exc
    return {
        "license_expression": (
            metadata.get("License-Expression")
            or (next(iter(inferred_expressions)) if len(inferred_expressions) == 1 else None)
        ),
        "license_metadata": metadata.get("License") or None,
        "license_files": license_files,
        "license_file_sha256": license_hashes,
    }


def license_evidence_complete(package: dict[str, Any]) -> bool:
    has_identity = bool(
        package.get("license_expression")
        or package.get("license_metadata")
        or package.get("license_classifiers")
    )
    license_files = package.get("license_files")
    license_hashes = package.get("license_file_sha256")
    return bool(
        has_identity
        and isinstance(license_files, list)
        and license_files
        and isinstance(license_hashes, dict)
        and set(license_files) == set(license_hashes)
        and all(
            isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
            for value in license_hashes.values()
        )
    )


def _prepare_package(
    package: dict[str, Any], sources_dir: Path, source_lock: dict[tuple[str, str], str]
) -> dict[str, Any]:
    name = package["name"]
    version = package["version"]
    metadata = _request_json(PYPI_JSON.format(name=name, version=version))
    sdists = [item for item in metadata.get("urls", []) if item.get("packagetype") == "sdist"]
    if len(sdists) != 1:
        raise SourcePreparationError(f"{name}=={version} has {len(sdists)} source distributions")
    artifact = sdists[0]
    declared_hash = artifact.get("digests", {}).get("sha256")
    source_lock_hash = source_lock.get((name.lower(), version))
    if declared_hash != source_lock_hash:
        raise SourcePreparationError(f"{name}=={version} sdist hash differs from the source lock")
    if declared_hash in package["allowed_sha256"]:
        hash_basis = "dependency_lock_and_committed_source_lock"
    else:
        hash_basis = "committed_source_lock"
    filename = artifact["filename"]
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise SourcePreparationError("source filename is not a confined basename")
    destination = sources_dir / filename
    try:
        destination.resolve().relative_to(sources_dir.resolve())
    except ValueError as error:
        raise SourcePreparationError("source filename escapes destination") from error
    _download(artifact["url"], destination)
    actual_hash = _sha256(destination)
    if actual_hash != declared_hash:
        destination.unlink(missing_ok=True)
        raise SourcePreparationError(f"{name}=={version} source hash mismatch")
    info = metadata.get("info", {})
    sdist_license = _inspect_sdist_license(destination)
    return {
        "name": name,
        "version": version,
        "roles": package["roles"],
        "filename": filename,
        "sha256": actual_hash,
        "hash_basis": hash_basis,
        "upstream": info.get("project_url")
        or info.get("package_url")
        or PYPI_JSON.format(name=name, version=version),
        "download_url": artifact["url"],
        "license_expression": sdist_license["license_expression"],
        "license_metadata": (info.get("license") or sdist_license["license_metadata"] or None),
        "license_classifiers": [
            classifier for classifier in info.get("classifiers", []) if classifier.startswith("License ::")
        ],
        "license_files": sdist_license["license_files"],
        "license_file_sha256": sdist_license["license_file_sha256"],
    }


def prepare_sources(
    runtime_lock: Path,
    build_lock: Path,
    destination: Path,
    source_lock_path: Path,
    development_lock: Path | None = None,
) -> dict[str, Any]:
    try:
        destination = external_output_path(
            destination, source_root=PROJECT_ROOT, role="third-party source destination"
        )
    except ValueError as error:
        raise SourcePreparationError(str(error)) from None
    if destination.exists():
        raise SourcePreparationError(f"destination already exists: {destination}")
    destination.mkdir(parents=True)
    sources_dir = destination / "sources"
    sources_dir.mkdir()
    try:
        source_lock_payload = json.loads(source_lock_path.read_text(encoding="utf-8"))
        source_lock = {
            (item["name"].lower(), item["version"]): item["sha256"]
            for item in source_lock_payload["packages"]
        }
        combined: dict[tuple[str, str], dict[str, Any]] = {}
        lock_inputs = {"production": runtime_lock, "build": build_lock}
        if development_lock is not None:
            lock_inputs["development"] = development_lock
        parsed_packages = [
            package for role, lock_path in lock_inputs.items() for package in parse_lock(lock_path, role)
        ]
        for package in parsed_packages:
            key = (package["name"].lower(), package["version"])
            if key in combined:
                existing = combined[key]
                existing["roles"] = sorted(set(existing["roles"]) | set(package["roles"]))
                existing["allowed_sha256"] = sorted(
                    set(existing["allowed_sha256"]) | set(package["allowed_sha256"])
                )
            else:
                combined[key] = package

        if set(source_lock) != set(combined):
            raise SourcePreparationError("source lock package versions differ from dependency locks")

        inventory = [
            _prepare_package(package, sources_dir, source_lock) for _, package in sorted(combined.items())
        ]
        licenses_complete = all(license_evidence_complete(item) for item in inventory)
        complete = licenses_complete

        def lock_identity(role: str, lock_path: Path) -> dict[str, str]:
            try:
                source_path = lock_path.resolve().relative_to(Path(__file__).resolve().parents[2]).as_posix()
            except ValueError:
                source_path = f"external_input/{lock_path.name}"
            return {
                "filename": lock_path.name,
                "sha256": _sha256(lock_path),
                "selection": "caller_supplied",
                "source_path": source_path,
                "role": role,
            }

        payload = {
            "schema_version": 2,
            "complete": complete,
            "source_hashes_complete": True,
            "license_evidence_complete": licenses_complete,
            "source": "PyPI version metadata plus locked SHA-256 verification",
            "lock_inputs": {
                role: lock_identity(role, lock_path) for role, lock_path in sorted(lock_inputs.items())
            },
            "packages": inventory,
        }
        (destination / "SOURCE_MANIFEST.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        sums = "".join(f"{item['sha256']}  sources/{item['filename']}\n" for item in inventory)
        (destination / "SHA256SUMS").write_text(sums, encoding="ascii")
        return payload
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-lock", type=Path, required=True)
    parser.add_argument("--build-lock", type=Path, required=True)
    parser.add_argument("--development-lock", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        payload = prepare_sources(
            args.runtime_lock,
            args.build_lock,
            args.destination,
            args.source_lock,
            args.development_lock,
        )
    except (OSError, SourcePreparationError, urllib.error.URLError) as exc:
        print(f"THIRD-PARTY SOURCE PREPARATION FAILED: {exc}", file=sys.stderr)
        return 1
    if payload.get("complete") is not True:
        print("THIRD-PARTY SOURCE PREPARATION INCOMPLETE", file=sys.stderr)
        return 1
    print(f"THIRD-PARTY SOURCE PREPARATION PASSED: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
