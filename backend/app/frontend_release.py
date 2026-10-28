"""Fail-closed identity verification for mounted frontend releases.

What the running process checks before it serves a mounted release: the
manifest's shape, the exact contract versions, the exact file tree and every
file's digest, the artifact digest and the combined release ID.  Whether a
published release's Corresponding Source receipt and legal fields are valid,
and which former public repositories a recorded pair may name, are release-time
questions; scripts/deployment/frontend_release.py answers them before a
release is ever mounted.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from types import MappingProxyType
import re
import stat
from typing import Any, Collection, Final, Mapping

from .canonical_json import canonical_json_bytes
from .frontend_assets import (
    DEFAULT_LOCALE_ENTRYPOINT,
    MANIFEST_NAME,
    asset_parent_directories,
    validate_asset_name,
    walk_regular_tree,
)


CONTRACT_PATH = Path("deploy/frontend-contract.json")
#: The public repository every new release is published to.
PUBLIC_REPOSITORY_URL: Final = "https://github.com/sa3952/Armillary"
SOURCE_URL_PREFIX = f"{PUBLIC_REPOSITORY_URL}/tree/"
#: The public site's product version, major.minor.patch (0.x during the public
#: alpha): a new feature raises the minor, a fix or copy change the patch.  It is
#: not a contract version.  The page footers and /api/version both read it, and
#: the changelog page must carry an entry for it.
SITE_VERSION: Final = "0.13.0"
REQUIRE_ENV = "CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE"
ROOT_ENV = "CLASSICAL_ASTROLOGY_FRONTEND_ROOT"
DIGEST_ENV = "CLASSICAL_ASTROLOGY_FRONTEND_RELEASE_DIGEST"
COMBINED_ENV = "CLASSICAL_ASTROLOGY_COMBINED_RELEASE_ID"
BACKEND_IMAGE_ENV = "CLASSICAL_ASTROLOGY_BACKEND_IMAGE_ID"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SOURCE_URL_STATUSES: Final = frozenset({
    "published_and_expected_anonymously_reachable",
    "provisional_pending_publication",
})


def _load_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required regular JSON file missing: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def source_url_for(repository: str, revision: str) -> str:
    return f"{repository}/tree/{revision}"


def _sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


REQUIRED_CONTRACT_KEYS: Final = (
    "api_schema_version",
    "dossier_version",
    "export_contract_version",
)


def validated_required_contracts(value: object) -> dict[str, str]:
    """The exact three-version contract set a frontend release requires."""
    if not isinstance(value, Mapping) or set(value) != set(REQUIRED_CONTRACT_KEYS):
        raise ValueError("required frontend contracts are not the exact three-version set")
    for key in REQUIRED_CONTRACT_KEYS:
        version = value.get(key)
        if not isinstance(version, str) or not re.fullmatch(r"0\.\d+\.\d+", version):
            raise ValueError(f"invalid exact frontend contract: {key}")
    return {key: str(value[key]) for key in REQUIRED_CONTRACT_KEYS}


def exact_contract(authority_root: Path) -> dict[str, str | int]:
    contract = _load_object(authority_root / CONTRACT_PATH)
    if set(contract) != {"schema_version", *REQUIRED_CONTRACT_KEYS} \
            or contract.get("schema_version") != 1:
        raise ValueError("unsupported frontend contract policy")
    validated_required_contracts(
        {key: contract.get(key) for key in REQUIRED_CONTRACT_KEYS}
    )
    return contract


def artifact_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _release_tree(release: Path) -> tuple[set[str], set[str]]:
    def refuse(relative: PurePosixPath, symlink: bool) -> ValueError:
        kind = "symlink" if symlink else "non-file"
        return ValueError(f"frontend release contains {kind}: {relative}")

    files: set[str] = set()
    directories: set[str] = set()
    for _entry, relative, is_directory in walk_regular_tree(release, refuse):
        (directories if is_directory else files).add(relative.as_posix())
    return files, directories


def verify_release(
    release_directory: Path,
    *,
    authority_root: Path | None = None,
    required_contracts: Mapping[str, object] | None = None,
    require_digest_directory_name: bool = True,
    source_repositories: Collection[str] | None = None,
) -> dict[str, object]:
    """Verify one immutable release tree against exactly one contract authority.

    `authority_root` names a tree whose deploy/frontend-contract.json the
    release must match: the running image, or the checkout that builds and
    deploys a new release.  `required_contracts` is the contract a release
    pair was recorded and accepted with.  `source_repositories` is the set of
    repositories whose exact-revision tree URL the manifest may name; by
    default only PUBLIC_REPOSITORY_URL.

    The publication receipt and the legal fields are checked here for shape
    only (absent while provisional, objects once published); their content is
    scripts/deployment/frontend_release.verify_published_release's.
    """
    expected_contracts = _expected_contracts(authority_root, required_contracts)
    repositories = frozenset(
        (PUBLIC_REPOSITORY_URL,) if source_repositories is None else source_repositories
    )
    if not repositories:
        raise ValueError("frontend release names an unrecorded public repository set")
    release = Path(os.path.abspath(release_directory))
    metadata = release.lstat()
    if not stat.S_ISDIR(metadata.st_mode):
        raise ValueError("frontend release must be a non-symlink directory")
    manifest = _load_object(release / MANIFEST_NAME)
    revision, digest = _verify_manifest(manifest, repositories, expected_contracts)
    files = manifest["files"]
    _verify_release_files(release, files)
    payload = {key: value for key, value in manifest.items() if key != "artifact_digest"}
    if artifact_digest(payload) != digest:
        raise ValueError("frontend artifact digest mismatch")
    if require_digest_directory_name and release.name != digest:
        raise ValueError("frontend release directory identity mismatch")
    return {
        "artifact_digest": digest,
        "frontend_public_source_revision": revision,
        "source_url": manifest["source_url"],
        "source_url_status": manifest["source_url_status"],
        "source_publication": manifest["source_publication"],
        "formal_legal_release_fields": manifest["formal_legal_release_fields"],
        "required_contracts": manifest["required_contracts"],
        "files": files,
    }


def _expected_contracts(
    authority_root: Path | None, required_contracts: Mapping[str, object] | None,
) -> dict[str, str]:
    """The contract set the release must carry, from exactly one authority."""
    if authority_root is not None and required_contracts is None:
        contract = exact_contract(authority_root)
        return {key: str(contract[key]) for key in REQUIRED_CONTRACT_KEYS}
    if authority_root is None and required_contracts is not None:
        return validated_required_contracts(required_contracts)
    raise ValueError("frontend release needs exactly one contract authority")


def _verify_manifest(
    manifest: dict[str, Any],
    repositories: frozenset[str],
    expected_contracts: Mapping[str, str],
) -> tuple[str, str]:
    """The manifest's own fields; returns its source revision and artifact digest."""
    required_keys = {
        "schema_version",
        "artifact_type",
        "frontend_public_source_revision",
        "source_url",
        # An immutable manifest cannot correct its URL later, so until the
        # Corresponding Source is published this says the URL is provisional.
        "source_url_status",
        "source_publication",
        "formal_legal_release_fields",
        "required_contracts",
        "files",
        "artifact_digest",
    }
    if set(manifest) != required_keys:
        raise ValueError("frontend release manifest key set is invalid")
    if manifest.get("source_url_status") not in SOURCE_URL_STATUSES:
        raise ValueError("frontend source URL status is invalid")
    publication = manifest.get("source_publication")
    legal_fields = manifest.get("formal_legal_release_fields")
    if manifest.get("source_url_status") == "provisional_pending_publication":
        if publication is not None or legal_fields is not None:
            raise ValueError("provisional frontend source must not carry publication evidence")
    elif not isinstance(publication, dict) or not isinstance(legal_fields, dict):
        raise ValueError("published frontend source evidence is invalid")
    revision = manifest.get("frontend_public_source_revision")
    digest = manifest.get("artifact_digest")
    if manifest.get("schema_version") != 3 or manifest.get(
        "artifact_type"
    ) != "classical-astrology-frontend-release":
        raise ValueError("frontend release manifest type is invalid")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise ValueError("frontend source revision is invalid")
    if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
        raise ValueError("frontend artifact digest is invalid")
    if not any(
        manifest.get("source_url") == source_url_for(repository, revision)
        for repository in repositories
    ):
        raise ValueError("frontend source URL is not pinned to its revision")
    if manifest.get("required_contracts") != expected_contracts:
        raise ValueError("frontend exact contract mismatch")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("frontend release file receipt is not exact-set")
    return revision, digest


def _verify_release_files(release: Path, files: dict[str, Any]) -> None:
    """The release tree holds exactly the receipted files, each as receipted."""
    expected_assets = {validate_asset_name(name) for name in files}
    if (
        len(expected_assets) != len(files)
        or DEFAULT_LOCALE_ENTRYPOINT not in expected_assets
    ):
        raise ValueError("frontend release file receipt is not exact-set")
    actual_files, actual_directories = _release_tree(release)
    expected_files = expected_assets | {MANIFEST_NAME}
    expected_directories = set(asset_parent_directories(expected_assets))
    if actual_files != expected_files or actual_directories != expected_directories:
        raise ValueError(
            "frontend release has missing or unexpected entries: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"unexpected={sorted(actual_files - expected_files)}, "
            f"unexpected_directories={sorted(actual_directories - expected_directories)}"
        )
    for name in sorted(expected_assets):
        path = release / name
        file_metadata = path.lstat()
        if not stat.S_ISREG(file_metadata.st_mode):
            raise ValueError(f"frontend release asset is a symlink or non-file: {name}")
        receipt = files.get(name)
        if not isinstance(receipt, dict) or set(receipt) != {"sha256", "size_bytes"}:
            raise ValueError(f"frontend release receipt is malformed: {name}")
        if receipt.get("size_bytes") != file_metadata.st_size:
            raise ValueError(f"frontend release size mismatch: {name}")
        if receipt.get("sha256") != _sha256(path):
            raise ValueError(f"frontend release SHA-256 mismatch: {name}")


def combined_release_id(
    *,
    backend_image_id: str,
    backend_public_source_revision: str,
    frontend_artifact_digest: str,
    frontend_public_source_revision: str,
) -> str:
    if not IMAGE_ID_RE.fullmatch(backend_image_id):
        raise ValueError("backend image ID is invalid")
    if not REVISION_RE.fullmatch(backend_public_source_revision):
        raise ValueError("backend public source revision is invalid")
    if not DIGEST_RE.fullmatch(frontend_artifact_digest):
        raise ValueError("frontend artifact digest is invalid")
    if not REVISION_RE.fullmatch(frontend_public_source_revision):
        raise ValueError("frontend public source revision is invalid")
    return hashlib.sha256(canonical_json_bytes({
        "backend_image_id": backend_image_id,
        "backend_public_source_revision": backend_public_source_revision,
        "frontend_artifact_digest": frontend_artifact_digest,
        "frontend_public_source_revision": frontend_public_source_revision,
    })).hexdigest()


def load_runtime_release(
    *,
    environment: Mapping[str, str],
    authority_root: Path,
    backend_public_source_revision: str | None,
    api_schema_version: str,
    dossier_version: str,
) -> tuple[Path | None, dict[str, object] | None, Mapping[str, str] | None]:
    """The mounted release, its identity, and each file's receipted SHA-256."""
    requirement = environment.get(REQUIRE_ENV)
    if requirement in (None, ""):
        return None, None, None
    if requirement != "1":
        raise RuntimeError("frontend release requirement must be exactly '1'")
    if backend_public_source_revision is None:
        raise RuntimeError("external frontend requires a backend public revision")
    raw_root = environment.get(ROOT_ENV)
    expected_digest = environment.get(DIGEST_ENV)
    combined = environment.get(COMBINED_ENV)
    backend_image_id = environment.get(BACKEND_IMAGE_ENV)
    if not raw_root or not Path(raw_root).is_absolute():
        raise RuntimeError("external frontend root must be absolute")
    if not expected_digest or not DIGEST_RE.fullmatch(expected_digest):
        raise RuntimeError("external frontend digest is missing or invalid")
    if not combined or not DIGEST_RE.fullmatch(combined):
        raise RuntimeError("combined release ID is missing or invalid")
    if not backend_image_id or not IMAGE_ID_RE.fullmatch(backend_image_id):
        raise RuntimeError("backend image ID is missing or invalid")
    release_root = Path(raw_root)
    try:
        verified = verify_release(
            release_root,
            authority_root=authority_root,
            require_digest_directory_name=False,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"frontend release verification failed: {exc}") from exc
    if verified["artifact_digest"] != expected_digest:
        raise RuntimeError("mounted frontend digest differs from deployment identity")
    contracts = verified["required_contracts"]
    if not isinstance(contracts, dict) or contracts.get(
        "api_schema_version"
    ) != api_schema_version or contracts.get("dossier_version") != dossier_version:
        raise RuntimeError("mounted frontend is incompatible with backend contracts")
    expected_combined = combined_release_id(
        backend_image_id=backend_image_id,
        backend_public_source_revision=backend_public_source_revision,
        frontend_artifact_digest=expected_digest,
        frontend_public_source_revision=str(
            verified["frontend_public_source_revision"]
        ),
    )
    if expected_combined != combined:
        raise RuntimeError("combined release ID does not match mounted components")
    identity: dict[str, object] = {
        "status": "available",
        "combined_release_id": combined,
        "backend": {
            "image_id": backend_image_id,
            "public_source_revision": backend_public_source_revision,
            "source_url": f"{SOURCE_URL_PREFIX}{backend_public_source_revision}",
        },
        "frontend": {
            "artifact_digest": expected_digest,
            "public_source_revision": verified[
                "frontend_public_source_revision"
            ],
            "source_url": verified["source_url"],
        },
        "contracts": contracts,
    }
    verified_files = verified["files"]
    if not isinstance(verified_files, dict):
        raise RuntimeError("verified frontend file receipt is invalid")
    digests = {name: receipt["sha256"] for name, receipt in verified_files.items()}
    return release_root, identity, MappingProxyType(digests)
