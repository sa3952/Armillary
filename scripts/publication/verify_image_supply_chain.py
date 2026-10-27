#!/usr/bin/env python3
"""SBOM and vulnerability scan of one built image (Gate D).

The SBOM is produced from the image itself (syft); it is the only SBOM the
project keeps.  syft cannot see the C sources the build compiles into the
pyswisseph extension (Swiss Ephemeris and Swephelp, plus Swephelp's bundled
SQLite when the extension was built without the system libsqlite3), so they
are added to it from the vendored sdist the image was built from.  Grype
scans it; with --with-trivy (Gate D always passes it), Trivy also scans the
same saved image archive on its own detection and database, and the findings
are united by vulnerability ID: each scanner has reported advisories the other
missed.  Without the flag only Grype runs, so an outside verifier needs no
Trivy.  Each scanner runs only after a positive
control proves it can see a vulnerability at all.  pip-audit checks the
production lock, and the image's Python inventory must equal the
marker-evaluated lock.

A High or Critical rating from either scanner gates (the higher rating wins).
An advisory no scanner rates (Unknown) gates as High when a scanner reports a
fix for it: the distribution has already shipped the fixed package, so the
image is behind its own base and needs a rebuild or a triage entry.  An unrated
advisory without a fix is listed in the receipt as unrated and does not gate.

Exit codes: 0 no High/Critical finding; 3 every High/Critical is covered by a
current reviewed triage entry (recorded acceptance) and the image's runtime base
is the base the triage was reviewed for; 2 a High/Critical finding is not
covered, or the triage is absent, expired, or for another or an unprovable base;
1 the evidence failed.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from packaging.markers import Marker, default_environment
from packaging.requirements import Requirement

from scripts.tools.commands import run_checked
from scripts.tools.output_confinement import external_output_path
from scripts.tools.source_tree_identity import sha256_file as _sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRODUCTION_LOCK = PROJECT_ROOT / "deploy" / "requirements.lock"
DEFAULT_PYSWISSEPH_SDIST = PROJECT_ROOT / "third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz"
MAX_GRYPE_DB_AGE_HOURS = 72
MAX_TRIVY_DB_AGE_HOURS = MAX_GRYPE_DB_AGE_HOURS
# The Trivy release this gate was verified against, and the database schema
# generation that release reads.
TRIVY_VERSION = "0.76.1"
TRIVY_DB_SCHEMA = 2
# Every Trivy run reads only the database already downloaded and checked;
# nothing else is fetched during a scan.
TRIVY_SCAN_OPTIONS = (
    "--skip-db-update", "--skip-java-db-update", "--offline-scan", "--skip-version-check", "--quiet",
    "--scanners", "vuln", "--severity", "UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL", "--format", "json",
)
RATED_SEVERITIES = ("Negligible", "Low", "Medium", "High", "Critical")
REQUIRED = {"fastapi", "pydantic", "pyswisseph", "starlette", "uvicorn"}
# Why a known-bad distribution is bad; the closed lock comparison decides.
FORBIDDEN = {
    "httpx", "httpx2", "httptools", "pip-audit", "pip-tools", "pip", "pytest",
    "python-dotenv", "pyyaml", "uvloop", "watchfiles", "websockets",
}
TRIAGE_SCHEMA = "image-cve-triage-v1"
_DIGEST_PINNED_BASE = re.compile(r"[^\s@$]+@sha256:[0-9a-f]{64}")
EXIT_UNTRIAGED_HIGH = 2
EXIT_ALL_TRIAGED = 3
GATING_SEVERITIES = ("High", "Critical")
_SEVERITY_RANK = {"High": 1, "Critical": 2}
# A genuinely old, genuinely vulnerable release, only ever named in a synthetic SBOM.
POSITIVE_CONTROL_PACKAGE = ("django", "1.11.0")


class AuditFailure(RuntimeError):
    pass


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_runtime_versions(lock: Path, architecture: str = "amd64") -> dict[str, str]:
    """Distributions the image installs from `lock`: name -> pinned version.

    A line whose PEP 508 marker is false in the image (CPython 3.14.10 on
    Linux) is listed in the lock but never installed.
    """

    environment = cast(dict[str, str], default_environment())
    environment.update({
        "os_name": "posix", "platform_system": "Linux", "sys_platform": "linux",
        "platform_machine": {"amd64": "x86_64", "arm64": "aarch64"}[architecture],
        "python_full_version": "3.14.10", "python_version": "3.14",
    })
    logical = re.sub(r"\\\n", " ", lock.read_text(encoding="utf-8"))
    versions: dict[str, str] = {}
    for line in logical.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line.split("--hash=", 1)[0].strip())
        pins = list(requirement.specifier)
        if len(pins) != 1 or pins[0].operator != "==" or "--hash=sha256:" not in line:
            raise AuditFailure(f"lock line is not exactly pinned and hashed: {requirement}")
        if requirement.marker is None or Marker(str(requirement.marker)).evaluate(environment):
            versions[normalized(requirement.name)] = pins[0].version
    if not versions:
        raise AuditFailure(f"{lock} installs nothing in the image")
    return versions


def grype_matches(path: Path) -> list[Any]:
    """The scanner's match list; an output without one is not "no findings"."""
    document = json.loads(path.read_text(encoding="utf-8"))
    matches = document.get("matches") if isinstance(document, dict) else None
    if not isinstance(matches, list):
        raise AuditFailure(f"{path.name} carries no matches list")
    return matches


def _sdist_define(archive: tarfile.TarFile, member: str, name: str) -> str:
    root = archive.getnames()[0].split("/", 1)[0]
    handle = archive.extractfile(f"{root}/{member}")
    match = re.search(rf'#define {name}\s+"([^"]+)"', handle.read().decode("utf-8", "replace")) if handle else None
    if match is None:
        raise AuditFailure(f"vendored pyswisseph {member} does not define {name}")
    return match.group(1)


def _sdist_defines(sdist: Path, *wanted: tuple[str, str]) -> list[str]:
    try:
        with tarfile.open(sdist, "r:gz") as archive:
            return [_sdist_define(archive, member, name) for member, name in wanted]
    except (OSError, tarfile.TarError, KeyError) as error:
        raise AuditFailure(f"cannot read the vendored pyswisseph sdist: {error}") from None


def elf_needed(data: bytes) -> list[str]:
    """DT_NEEDED entries of a 64-bit little-endian ELF shared object."""
    try:
        if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
            raise ValueError("not a 64-bit little-endian ELF")
        shoff = int.from_bytes(data[0x28:0x30], "little")
        shentsize, shnum = struct.unpack_from("<HH", data, 0x3A)
        sections = [struct.unpack_from("<IIQQQQIIQQ", data, shoff + index * shentsize) for index in range(shnum)]
        needed: list[str] = []
        for _name, kind, _flags, _addr, offset, size, link, _info, _align, _entsize in sections:
            if kind != 6:  # SHT_DYNAMIC
                continue
            strings = sections[link][4]
            for position in range(offset, offset + size, 16):
                tag, value = struct.unpack_from("<qQ", data, position)
                if tag == 0:
                    break
                if tag == 1:  # DT_NEEDED
                    start = strings + value
                    needed.append(data[start:data.index(b"\0", start)].decode("ascii"))
        return needed
    except (ValueError, IndexError, struct.error, UnicodeError) as error:
        raise AuditFailure(f"cannot read the pyswisseph extension as ELF: {error}") from None


def pyswisseph_sqlite_linkage(extension: bytes, sdist: Path) -> str:
    """"system" when the extension needs Debian's libsqlite3 and carries no
    copy of the sdist's bundled amalgamation, "bundled" for the reverse; any
    other combination is refused."""
    (source_id,) = _sdist_defines(sdist, ("swephelp/sqlite3/sqlite3.h", "SQLITE_SOURCE_ID"))
    system = "libsqlite3.so.0" in elf_needed(extension)
    bundled = source_id.encode() in extension
    if system != bundled:
        return "system" if system else "bundled"
    raise AuditFailure(
        f"pyswisseph extension SQLite linkage is ambiguous: needs libsqlite3={system}, "
        f"carries the bundled amalgamation={bundled}"
    )


SWISSEPH_EXTENSION_BYTES = (
    "import swisseph,sys; sys.stdout.buffer.write(open(swisseph.__file__,'rb').read())"
)


def _run_bytes(command: list[str], *, timeout: int = 600) -> bytes:
    completed = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    if completed.returncode:
        raise AuditFailure(f"{command[0]} failed: {completed.stderr.decode(errors='replace')[-2000:]}")
    return completed.stdout


def image_swisseph_extension(image: str, run_options: tuple[str, ...] = ("--network", "none")) -> bytes:
    """The bytes of the pyswisseph extension module the image imports."""
    return _run_bytes(["docker", "run", "--rm", *run_options, "--entrypoint", "/opt/venv/bin/python",
                       image, "-c", SWISSEPH_EXTENSION_BYTES])


def image_archive_identity(archive: Path) -> tuple[set[str], str]:
    """(the manifest digests its index.json names, the config digest its
    manifest.json names) of a `docker save` archive."""
    try:
        with tarfile.open(archive) as saved:
            def member(name: str) -> Any:
                handle = saved.extractfile(name)
                if handle is None:
                    raise KeyError(name)
                return json.loads(handle.read())

            index, manifest = member("index.json"), member("manifest.json")
        manifests = {str(entry["digest"]) for entry in index["manifests"]}
        configs = [str(entry["Config"]) for entry in manifest]
    except (OSError, KeyError, TypeError, ValueError, tarfile.TarError) as error:
        raise AuditFailure(f"the saved image archive is unreadable: {error}") from None
    if len(configs) != 1 or not configs[0].startswith("blobs/sha256/"):
        raise AuditFailure(f"the saved image archive does not hold exactly one image: {configs}")
    return manifests, "sha256:" + configs[0].removeprefix("blobs/sha256/")


def image_sbom(image_id: str, syft: str, sbom_path: Path, workspace: Path) -> str:
    """syft's SBOM of a `docker save` of the image ID (left at
    workspace/image.tar for the second scanner): syft reads that archive
    and resolves no reference of its own.  The archive must be the image (its
    index names the ID, or, in Docker's classic store, its config is the ID)
    and the SBOM must be of the archive's config.  Returns that config digest."""
    archive = workspace / "image.tar"
    _run(["docker", "save", "--output", str(archive), image_id])
    manifests, config = image_archive_identity(archive)
    if image_id not in manifests | {config}:
        raise AuditFailure(f"docker save of {image_id} wrote another image: {sorted(manifests)} / {config}")
    _run([syft, f"docker-archive:{archive}", "-o", f"syft-json={sbom_path}"])
    scanned = ((json.loads(sbom_path.read_text(encoding="utf-8")).get("source") or {})
               .get("metadata") or {}).get("imageID")
    if scanned != config:
        raise AuditFailure(f"the SBOM is of image config {scanned!r}, not the saved image's {config}")
    return config


# The licences the vendored sources state: pyswisseph.c and the Swephelp
# headers grant "version 3 / version 2, or any later version"; libswe/LICENSE
# offers the AGPL or Astrodienst's Swiss Ephemeris Professional License.
EMBEDDED_LICENSES: dict[str, str] = {
    "pyswisseph": "AGPL-3.0-or-later",
    "swiss-ephemeris": "AGPL-3.0-only OR LicenseRef-SwissEph-Professional",
    "swephelp": "GPL-2.0-or-later",
}
# Swephelp carries no version.  The sdist's swephelp/ equals, blob for blob,
# the upstream astrorigin/swephelp submodule commit below; that holds for this
# sdist only, so the identity names the sdist digest it was established for.
SWEPHELP_UPSTREAM_COMMIT = "git-5db9f591"
SWEPHELP_IDENTITY_SDIST_SHA256 = "c54c305e83dbd5d2b71e58d8a69d8ee41de24c4d3328ce09e2af860a3537624d"


def _concluded_license(expression: str) -> list[dict[str, Any]]:
    return [{"value": expression, "spdxExpression": expression, "type": "concluded",
             "urls": [], "locations": []}]


def with_embedded_components(sbom: dict[str, Any], sdist: Path, sqlite_linkage: str) -> dict[str, Any]:
    """`sbom` plus the C sources compiled into the pyswisseph extension.

    Swiss Ephemeris and Swephelp are always compiled in.  deploy/Dockerfile's
    builder installs pkg-config and libsqlite3-dev, so pyswisseph's setup.py
    links Debian's libsqlite3, which syft lists as a deb; an extension built
    without them ("bundled") carries Swephelp's SQLite amalgamation instead,
    which only this addition names.  Versions come from the sdist's headers.
    """
    if sqlite_linkage not in ("system", "bundled"):
        raise AuditFailure(f"unknown pyswisseph SQLite linkage: {sqlite_linkage!r}")
    owners = [a for a in sbom.get("artifacts", []) if a.get("type") == "python" and a.get("name") == "pyswisseph"]
    if len(owners) != 1:
        raise AuditFailure("the image SBOM does not hold exactly one pyswisseph to attach its C sources to")
    owner = owners[0]
    swiss, sqlite = _sdist_defines(
        sdist, ("libswe/sweph.h", "SE_VERSION"), ("swephelp/sqlite3/sqlite3.h", "SQLITE_VERSION"),
    )
    if hashlib.sha256(sdist.read_bytes()).hexdigest() != SWEPHELP_IDENTITY_SDIST_SHA256:
        raise AuditFailure("the Swephelp identity was established for another pyswisseph sdist")
    if not owner.get("licenses"):
        owner = {**owner, "licenses": _concluded_license(EMBEDDED_LICENSES["pyswisseph"])}
    components: list[tuple[str, str, list[dict[str, str]]]] = [
        ("swiss-ephemeris", swiss, []), ("swephelp", SWEPHELP_UPSTREAM_COMMIT, []),
    ]
    if sqlite_linkage == "bundled":
        components.append(("sqlite", sqlite, [{"cpe": f"cpe:2.3:a:sqlite:sqlite:{sqlite}:*:*:*:*:*:*:*",
                                                "source": "nvd-cpe-dictionary"}]))
    added = [{
        "id": hashlib.sha256(f"pyswisseph-embedded/{name}@{version}".encode()).hexdigest()[:16],
        "name": name, "version": version, "type": "binary",
        "foundBy": "armillary-vendored-pyswisseph-sdist", "locations": owner.get("locations", [])[:1],
        "licenses": _concluded_license(EMBEDDED_LICENSES[name]) if name in EMBEDDED_LICENSES else [],
        "language": "", "cpes": cpes,
        "purl": f"pkg:generic/{name}@{version}",
    } for name, version, cpes in components]
    return {
        **sbom,
        "artifacts": [*(owner if artifact is owners[0] else artifact for artifact in sbom["artifacts"]), *added],
        "artifactRelationships": [
            *sbom.get("artifactRelationships", []),
            *({"parent": owner["id"], "child": item["id"], "type": "contains"} for item in added),
        ],
    }


def load_cve_triage(path: Path) -> dict[str, Any]:
    """A reviewed triage record; anything malformed is refused, not ignored."""

    try:
        triage = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise AuditFailure(f"CVE triage is unreadable: {error}") from None
    keys = {
        "schema_version", "reviewed_on", "accepted_on", "accepted_by", "acceptance",
        "record", "base_image", "recheck_by", "recheck_rule", "entries",
    }
    entries = triage.get("entries") if isinstance(triage, dict) else None
    if (
        not isinstance(triage, dict) or set(triage) != keys
        or triage.get("schema_version") != TRIAGE_SCHEMA
        or not _DIGEST_PINNED_BASE.fullmatch(str(triage.get("base_image")))
        or not isinstance(entries, list) or not entries
        or any(
            not isinstance(triage.get(key), str) or not triage[key].strip()
            for key in keys - {"schema_version", "entries"}
        )
    ):
        raise AuditFailure("CVE triage record is invalid")
    try:
        for key in ("reviewed_on", "accepted_on", "recheck_by"):
            date.fromisoformat(triage[key])
    except ValueError:
        raise AuditFailure("CVE triage dates are invalid") from None
    seen: set[str] = set()
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"id", "severity", "debian_state", "packages", "reachability", "reason"}
            or not re.fullmatch(r"(?:CVE|GHSA)-[0-9A-Za-z-]+", str(entry.get("id", "")))
            or entry["id"] in seen
            or entry.get("severity") not in GATING_SEVERITIES
            or entry.get("reachability") != "unreachable"
            or not isinstance(entry.get("reason"), str) or not entry["reason"].strip()
            or not isinstance(entry.get("packages"), list) or not entry["packages"]
            or any(not isinstance(name, str) or not name for name in entry["packages"])
        ):
            raise AuditFailure(f"CVE triage entry is invalid: {entry!r}"[:300])
        seen.add(entry["id"])
    return triage


def dockerfile_runtime_base(dockerfile: Path | None) -> str | None:
    """The digest-pinned base of the runtime stage of the Dockerfile the image
    was built from, or None when that cannot be proven (no Dockerfile, or a
    stage that is unpinned or chosen by a build argument).

    The Dockerfile, not an image label, is the identity: Gate D binds the
    image's revision label and build transaction to the clean checkout it
    passes, while a label is whatever the build wrote and the base's own layers
    are not available offline to compare against."""

    if dockerfile is None:
        return None
    # Imported here: the container gate imports this module.
    from scripts.verification.verify_container_runtime import GateFailure, pinned_base_reference

    try:
        return pinned_base_reference(dockerfile)
    except GateFailure:
        return None


def trivy_matches(path: Path, config: str) -> list[dict[str, Any]]:
    """Trivy's findings for the saved image whose config is `config`, in the
    shape of grype matches.  A report of another image, or one in which Trivy
    detected no operating-system packages, is not "no findings"."""

    document = json.loads(path.read_text(encoding="utf-8"))
    metadata = document.get("Metadata") if isinstance(document, dict) else None
    if not isinstance(metadata, dict) or document.get("ArtifactType") != "container_image":
        raise AuditFailure(f"{path.name} is not a Trivy container image report")
    if metadata.get("ImageID") != config:
        raise AuditFailure(f"Trivy scanned image config {metadata.get('ImageID')!r}, not the saved image's {config}")
    results = document.get("Results")
    if not isinstance(results, list) or not any(
        isinstance(result, dict) and result.get("Class") == "os-pkgs" for result in results
    ):
        raise AuditFailure(f"{path.name}: Trivy detected no operating-system packages")
    matches: list[dict[str, Any]] = []
    for result in results:
        vulnerabilities = result.get("Vulnerabilities") or [] if isinstance(result, dict) else None
        if not isinstance(vulnerabilities, list):
            raise AuditFailure(f"{path.name} carries a malformed result")
        for item in vulnerabilities:
            if not isinstance(item, dict):
                raise AuditFailure(f"{path.name} carries a malformed vulnerability")
            matches.append({
                "vulnerability": {
                    "id": item.get("VulnerabilityID"),
                    # Trivy writes HIGH, grype High.
                    "severity": str(item.get("Severity") or "UNKNOWN").capitalize(),
                    "fix": {"state": item.get("Status") or ""},
                },
                "artifact": {"name": item.get("PkgName"), "version": item.get("InstalledVersion")},
                "scanner": "trivy",
            })
    return matches


def _findings_by_id(matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for match in matches:
        vulnerability = match.get("vulnerability", {}) if isinstance(match, dict) else {}
        artifact = match.get("artifact", {}) if isinstance(match, dict) else {}
        identifier = str(vulnerability.get("id") or "unidentified")
        row = found.setdefault(identifier, {
            "id": identifier, "severities": set(), "packages": set(), "package_names": set(),
            "fix_states": set(), "scanners": set(),
        })
        row["severities"].add(str(vulnerability.get("severity") or "Unknown"))
        row["packages"].add(f"{artifact.get('name') or ''}@{artifact.get('version') or ''}")
        row["package_names"].add(str(artifact.get("name") or ""))
        row["fix_states"].add(str((vulnerability.get("fix") or {}).get("state") or ""))
        row["scanners"].add(str(match.get("scanner") or "grype") if isinstance(match, dict) else "grype")
    return found


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"], "fix_state": ",".join(sorted(state for state in row["fix_states"] if state)),
        "packages": sorted(row["packages"]), "scanners": sorted(row["scanners"]),
    }


def gating_findings(matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """High/Critical findings by vulnerability ID, across every scanner's
    matches: the highest rating any scanner gives, every affected package."""

    found: dict[str, dict[str, Any]] = {}
    for identifier, row in _findings_by_id(matches).items():
        gating = [severity for severity in row["severities"] if severity in GATING_SEVERITIES]
        if gating:
            found[identifier] = {**row, "severity": max(gating, key=_SEVERITY_RANK.__getitem__)}
        elif _unrated_with_fix(row):
            found[identifier] = {**row, "severity": "High"}
    return found


def _unrated_with_fix(row: dict[str, Any]) -> bool:
    return not row["severities"] & set(RATED_SEVERITIES) and "fixed" in {
        state.lower() for state in row["fix_states"]
    }


def unrated_findings(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Advisories no scanner rates and none reports a fix for: reported, never gating."""

    return [
        _public_row(row) for identifier, row in sorted(_findings_by_id(matches).items())
        if not row["severities"] & set(RATED_SEVERITIES) and not _unrated_with_fix(row)
    ]


def triage_decision(
    found: dict[str, dict[str, Any]], triage: dict[str, Any] | None, *, today: date,
    image_base: str | None,
) -> tuple[str, list[dict[str, Any]], str]:
    """A finding is accepted only by an entry with its ID, a severity at least as
    high and every affected package named; an expired triage, or one reviewed
    for another base than `image_base` or with that base unproven, accepts
    nothing."""

    entries: dict[str, dict[str, Any]]
    if triage is None:
        status, entries = "absent", {}
    elif today > date.fromisoformat(triage["recheck_by"]):
        status, entries = "expired", {}
    elif image_base is None:
        status, entries = "base_unproven", {}
    elif image_base != triage["base_image"]:
        status, entries = "base_mismatch", {}
    else:
        status, entries = "current", {entry["id"]: entry for entry in triage["entries"]}
    rows = []
    for identifier in sorted(found):
        row, entry = found[identifier], entries.get(identifier)
        accepted = (
            entry is not None
            and _SEVERITY_RANK[row["severity"]] <= _SEVERITY_RANK[entry["severity"]]
            and row["package_names"] <= set(entry["packages"])
        )
        rows.append({
            **_public_row(row), "severity": row["severity"],
            "triage": "accepted_unreachable" if accepted else "untriaged",
        })
    if not rows:
        decision = "no_high_or_critical_matches"
    elif all(row["triage"] == "accepted_unreachable" for row in rows):
        decision = "high_or_critical_all_triaged"
    else:
        decision = "manual_triage_required"
    return decision, rows, status


def _run(command: list[str], *, timeout: int = 1800) -> str:
    return run_checked(command, error=AuditFailure, timeout=timeout).stdout


def _database(grype: str) -> dict[str, Any]:
    """Fresh, checksummed, and of the schema generation this grype reads."""

    status = json.loads(_run([grype, "db", "status", "-o", "json"]))
    grype_version = re.search(r"^Version:\s*(\S+)", _run([grype, "version"]), re.MULTILINE)
    built = status.get("built") or status.get("buildDate") or status.get("database", {}).get("built")
    checksum = status.get("checksum") or parse_qs(urlparse(status.get("from", "")).query).get(
        "checksum", [None]
    )[0]
    if not built or not checksum:
        raise AuditFailure("Grype database status omitted its build time or checksum")
    built_at = datetime.fromisoformat(str(built).replace("Z", "+00:00"))
    if built_at.tzinfo is None:
        raise AuditFailure("Grype database build time omitted timezone")
    age = (datetime.now(timezone.utc) - built_at).total_seconds() / 3600
    if not -1 <= age <= MAX_GRYPE_DB_AGE_HOURS:
        raise AuditFailure(f"Grype database age {age:.1f}h is outside 0..{MAX_GRYPE_DB_AGE_HOURS}h")
    schema = status.get("schemaVersion") or status.get("schema_version")
    supported = re.search(r"Supported DB Schema:\s*(\d+)", _run([grype, "version"]))
    if grype_version is None:
        raise AuditFailure("grype did not report its version")
    generation = re.fullmatch(r"v?(\d+)(?:\.\d+)*", str(schema or ""))
    if supported is None or generation is None or supported.group(1) != generation.group(1):
        raise AuditFailure(f"Grype database schema {schema!r} is not the generation grype reads")
    return {"database_built": built, "age_hours": round(max(age, 0), 3),
            "schema_version": schema, "checksum": checksum, "grype_version": grype_version.group(1)}


def _trivy_database(trivy: str) -> dict[str, Any]:
    """The pinned Trivy release, with a fresh database of the schema it reads."""

    _run([trivy, "image", "--download-db-only", "--skip-java-db-update", "--skip-version-check", "--quiet"])
    try:
        status = json.loads(_run([trivy, "version", "--format", "json"]))
        database = status["VulnerabilityDB"]
        version, schema, updated = status["Version"], database["Version"], database["UpdatedAt"]
        updated_at = datetime.fromisoformat(str(updated).replace("Z", "+00:00"))
    except (TypeError, KeyError, ValueError) as error:
        raise AuditFailure(f"Trivy did not report its version and database: {error}") from None
    if version != TRIVY_VERSION:
        raise AuditFailure(f"Trivy {version!r} is not the pinned {TRIVY_VERSION}")
    if schema != TRIVY_DB_SCHEMA:
        raise AuditFailure(f"Trivy database schema {schema!r} is not {TRIVY_DB_SCHEMA}")
    if updated_at.tzinfo is None:
        raise AuditFailure("Trivy database update time omitted timezone")
    age = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
    if not -1 <= age <= MAX_TRIVY_DB_AGE_HOURS:
        raise AuditFailure(f"Trivy database age {age:.1f}h is outside 0..{MAX_TRIVY_DB_AGE_HOURS}h")
    return {"trivy_version": version, "schema_version": schema, "database_updated": updated,
            "downloaded_at": database.get("DownloadedAt"), "age_hours": round(max(age, 0), 3)}


def _positive_control_sbom(workspace: Path) -> Path:
    name, version = POSITIVE_CONTROL_PACKAGE
    control = workspace / "positive-control.sbom.json"
    control.write_text(json.dumps({
        "bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
        "components": [{"type": "library", "name": name, "version": version,
                        "purl": f"pkg:pypi/{name}@{version}"}],
    }), encoding="utf-8")
    return control


def _scanner_positive_control(grype: str, workspace: Path) -> dict[str, Any]:
    """An empty database, a wrong target or a failed load all report clean, so a
    zero on the real image means nothing until the scanner reports a known match."""

    name, version = POSITIVE_CONTROL_PACKAGE
    control = _positive_control_sbom(workspace)
    output = workspace / "positive-control.grype.json"
    _run([grype, f"sbom:{control}", "-o", "json", "--file", str(output)])
    found = len(grype_matches(output))
    if found < 1:
        raise AuditFailure(f"scanner positive control failed: no match for {name} {version}")
    return {"package": f"{name}@{version}", "matches": found}


def _trivy_positive_control(trivy: str, workspace: Path) -> dict[str, Any]:
    name, version = POSITIVE_CONTROL_PACKAGE
    output = workspace / "positive-control.trivy.json"
    _run([trivy, "sbom", *TRIVY_SCAN_OPTIONS, "--output", str(output), str(_positive_control_sbom(workspace))])
    document = json.loads(output.read_text(encoding="utf-8"))
    results = document.get("Results") if isinstance(document, dict) else None
    found = sum(len(result.get("Vulnerabilities") or []) for result in results or [] if isinstance(result, dict))
    if found < 1:
        raise AuditFailure(f"Trivy positive control failed: no match for {name} {version}")
    return {"package": f"{name}@{version}", "matches": found}


def _severity_counts(matches: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        severity = str(((match.get("vulnerability") or {}) if isinstance(match, dict) else {}).get("severity")
                       or "Unknown")
        counts[severity] = counts.get(severity, 0) + 1
    return dict(sorted(counts.items()))


def _verify_python_inventory(sbom: dict[str, Any], audited: list[Any], lock: Path) -> dict[str, str]:
    installed = {
        normalized(str(artifact.get("name", ""))): str(artifact.get("version") or "")
        for artifact in sbom.get("artifacts", []) if artifact.get("type") == "python"
    }
    if REQUIRED - set(installed) or FORBIDDEN & set(installed):
        raise AuditFailure(
            f"Python inventory: missing={sorted(REQUIRED - set(installed))}, "
            f"forbidden={sorted(FORBIDDEN & set(installed))}"
        )
    expected = locked_runtime_versions(lock)
    audit = {
        normalized(str(item.get("name"))): str(item.get("version"))
        for item in audited if isinstance(item, dict) and item.get("name") and item.get("version")
    }
    for role, observed in (("image Python inventory", installed), ("pip-audit universe", audit)):
        if observed != expected:
            differing = sorted(set(observed) ^ set(expected) | {
                name for name in set(observed) & set(expected) if observed[name] != expected[name]
            })
            raise AuditFailure(f"{role} differs from the runtime lock: {differing}")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--image", required=True)
    parser.add_argument("--syft", default="syft")
    parser.add_argument("--grype", default="grype")
    parser.add_argument("--trivy", default="trivy")
    parser.add_argument("--with-trivy", action="store_true",
                        help="also scan with the pinned Trivy and unite its findings with Grype's")
    parser.add_argument("--pip-audit", default="pip-audit")
    parser.add_argument("--production-lock", type=Path, default=DEFAULT_PRODUCTION_LOCK)
    parser.add_argument("--pyswisseph-sdist", type=Path, default=DEFAULT_PYSWISSEPH_SDIST,
                        help="the vendored sdist the image's pyswisseph was built from")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--triage", type=Path, help="reviewed CVE triage (image-cve-triage-v1)")
    parser.add_argument("--dockerfile", type=Path,
                        help="the Dockerfile the image was built from; without it no triage accepts anything")
    args = parser.parse_args()
    try:
        output = external_output_path(args.output_dir, source_root=PROJECT_ROOT, role="supply-chain output")
        output.mkdir(parents=True, exist_ok=True)
        lock = args.production_lock.resolve()
        sbom_path, grype_path, trivy_path, audit_path = (
            output / "sbom.syft.json", output / "grype.json", output / "trivy.json", output / "pip-audit.json"
        )
        # The reference is read once; every scan below reads that image ID.
        image = json.loads(_run(["docker", "image", "inspect", args.image]))[0]
        image_id = image["Id"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(image_id)):
            raise AuditFailure(f"{args.image} has no image ID")
        _run([args.grype, "db", "update"])
        positive_control = _scanner_positive_control(args.grype, output)
        trivy_database = _trivy_database(args.trivy) if args.with_trivy else None
        trivy_positive_control = _trivy_positive_control(args.trivy, output) if args.with_trivy else None
        with tempfile.TemporaryDirectory(prefix="image-archive-") as workspace:
            sbom_config = image_sbom(image_id, args.syft, sbom_path, Path(workspace))
            if args.with_trivy:
                _run([args.trivy, "image", *TRIVY_SCAN_OPTIONS, "--output", str(trivy_path),
                      "--input", str(Path(workspace) / "image.tar")])
        sqlite_linkage = pyswisseph_sqlite_linkage(
            image_swisseph_extension(image_id), args.pyswisseph_sdist,
        )
        sbom_path.write_text(json.dumps(with_embedded_components(
            json.loads(sbom_path.read_text(encoding="utf-8")), args.pyswisseph_sdist, sqlite_linkage,
        )), encoding="utf-8")
        _run([args.grype, f"sbom:{sbom_path}", "-o", "json", "--file", str(grype_path)])
        _run([
            args.pip_audit, "--require-hashes", "--disable-pip", "--no-deps", "--format", "json",
            "--output", str(audit_path), "--requirement", str(lock),
        ])
        sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
        matches = [{**match, "scanner": "grype"} if isinstance(match, dict) else match
                   for match in grype_matches(grype_path)]
        trivy_found = trivy_matches(trivy_path, sbom_config) if args.with_trivy else []
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        dependencies = audit if isinstance(audit, list) else audit.get("dependencies", [])
        versions = _verify_python_inventory(sbom, dependencies, lock)
        database = _database(args.grype)
        triage = load_cve_triage(args.triage) if args.triage is not None else None
        image_base = dockerfile_runtime_base(args.dockerfile)
        decision, rows, triage_status = triage_decision(
            gating_findings([*matches, *trivy_found]), triage, today=datetime.now(timezone.utc).date(), image_base=image_base,
        )
        receipt = {
            "schema_version": "image-supply-chain-summary-v6",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "image": {
                "reference": args.image, "id": image_id, "architecture": image["Architecture"],
                "sbom_config_digest": sbom_config,
                "revision": (image.get("Config", {}).get("Labels") or {}).get(
                    "org.opencontainers.image.revision"
                ),
            },
            "grype_database": database,
            "scanners": ["grype", "trivy"] if args.with_trivy else ["grype"],
            "trivy_database": trivy_database,
            "pyswisseph_sqlite_linkage": sqlite_linkage,
            "scanner_positive_control": {"grype": positive_control,
                                         **({"trivy": trivy_positive_control} if args.with_trivy else {})},
            "artifact_sha256": {
                "sbom_syft_json": _sha256(sbom_path), "grype_json": _sha256(grype_path),
                **({"trivy_json": _sha256(trivy_path)} if args.with_trivy else {}),
                "pip_audit_json": _sha256(audit_path), "production_lock": _sha256(lock),
            },
            "lock_bound_python_versions": dict(sorted(versions.items())),
            "pip_audit_known_vulnerabilities": sum(len(item.get("vulns", [])) for item in dependencies),
            "grype_matches_total": len(matches),
            "trivy_findings_total": len(trivy_found) if args.with_trivy else None,
            "severity_counts": {"grype": _severity_counts(matches),
                                **({"trivy": _severity_counts(trivy_found)} if args.with_trivy else {})},
            "high_or_critical_findings": rows,
            "unrated_findings": unrated_findings([*matches, *trivy_found]),
            "cve_triage": {
                "status": triage_status,
                # The file name only: never a local absolute path.
                "record": args.triage.name if args.triage is not None else None,
                "sha256": _sha256(args.triage) if args.triage is not None else None,
                "recheck_by": triage["recheck_by"] if triage else None,
                # The identities compared: the base the triage was reviewed
                # for and the runtime base of the Dockerfile the image was built from.
                "base_image": {"triage": triage["base_image"] if triage else None, "image": image_base},
            },
            "decision": decision,
        }
        receipt_path = external_output_path(
            args.receipt or output / "receipt.json", source_root=PROJECT_ROOT, role="supply-chain receipt"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return {
            "manual_triage_required": EXIT_UNTRIAGED_HIGH,
            "high_or_critical_all_triaged": EXIT_ALL_TRIAGED,
        }.get(decision, 0)
    except (AuditFailure, OSError, subprocess.TimeoutExpired, ValueError, KeyError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
