#!/usr/bin/env python3
"""Build, verify and install immutable frontend release directories.

The running process verifies a mounted release's tree and identity
(backend/app/frontend_release.py).  Whether a published release's Corresponding
Source receipt is valid, whether its legal fields match the legal pages it
carries, and which former public repository a recorded release pair may name
are decided here, before a release is built, installed or deployed.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Collection, Final, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from scripts.tools.source_tree_identity import observe_publication_tree, sha256_file as _sha256
from scripts.tools.output_confinement import external_output_path

try:
    import app.frontend_release  # noqa: F401  the canonical package
except ModuleNotFoundError:
    # Clean public checkouts run this without backend/ on the path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.frontend_assets import discover_source_assets
from app.frontend_release import (
    DIGEST_RE,
    PUBLIC_REPOSITORY_URL,
    REVISION_RE,
    SOURCE_URL_PREFIX,
    artifact_digest as _runtime_artifact_digest,
    canonical_json_bytes,
    combined_release_id,
    exact_contract as _runtime_exact_contract,
    source_url_for,
    verify_release as _verify_release_tree,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_NAME = "frontend-release.json"
PUBLISHED_SOURCE_STATUS = "published_and_expected_anonymously_reachable"


# --- publication evidence (release time; the running process verifies only the tree)
SOURCE_ARCHIVE_URL_PREFIX = f"{PUBLIC_REPOSITORY_URL}/archive/"
#: The closed set of public repositories a release has ever been
#: published to.  A release pair already recorded in deployment state is
#: verified against the repository it was published to, which its own
#: immutable manifest names: the live 2026-09-12 pair was published to
#: sa3952/Project-Armillary before the source moved to its current repository.  A new release
#: may only name PUBLIC_REPOSITORY_URL.
RECORDED_PUBLIC_REPOSITORY_URLS: Final = frozenset(
    {PUBLIC_REPOSITORY_URL, "https://github.com/sa3952/Project-Armillary"}
)
RELEASE_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# `formal_legal_release_fields.effective_date` is the effective
# date the legal pages themselves show (2026-09-06), not the date the
# source was read back.  The pages are the one producer of that fact; the
# release producer and this verifier both read it from the release's own pages.
LEGAL_EFFECTIVE_DATE_PAGES: Final = ("zh-TW/legal/terms.html", "zh-TW/legal/privacy.html")
_LEGAL_EFFECTIVE_DATE = re.compile(r"<span>生效日</span><b>([0-9]{4}-[0-9]{2}-[0-9]{2})</b>")
FORMAL_LEGAL_FIELDS = frozenset(
    {"effective_date", "release_version", "public_revision", "source_archive_url", "source_archive_sha256"}
)


def _not_after_today(value: date | None) -> bool:
    """A publication cannot have taken effect after today.

    The receipt's `effective_date` is the UTC date of the anonymous readback;
    the legal pages' own date is a separate field.  A UTC date
    after today UTC is a claim about the future, which no readback supports.
    """

    if value is None:
        return False
    return value <= datetime.now(timezone.utc).date()


def legal_effective_date(frontend_root: Path) -> str:
    """The one effective date the terms and privacy pages under `frontend_root` show."""

    shown: set[str] = set()
    for name in LEGAL_EFFECTIVE_DATE_PAGES:
        page = frontend_root / name
        if not page.is_file() or page.is_symlink():
            raise ValueError(f"legal page missing from frontend: {name}")
        found = _LEGAL_EFFECTIVE_DATE.findall(page.read_text(encoding="utf-8"))
        if len(found) != 1:
            raise ValueError(f"legal page does not show exactly one effective date: {name}")
        try:
            date.fromisoformat(found[0])
        except ValueError:
            raise ValueError(f"legal page effective date is not a date: {name}") from None
        shown.add(found[0])
    if len(shown) != 1:
        raise ValueError("legal pages show different effective dates")
    return shown.pop()


def source_archive_url_for(repository: str, revision: str) -> str:
    """The exact-revision source archive URL of `revision` in `repository`."""
    return f"{repository}/archive/{revision}.tar.gz"


def recorded_source_repository(
    source_url: object, revision: object, *, repositories: Collection[str] = RECORDED_PUBLIC_REPOSITORY_URLS
) -> str:
    """The repository in the closed set whose tree URL for `revision` is `source_url`."""
    unknown = set(repositories) - RECORDED_PUBLIC_REPOSITORY_URLS
    if unknown:
        raise ValueError(f"not a recorded public repository: {sorted(unknown)}")
    for repository in sorted(repositories):
        if isinstance(revision, str) and source_url == source_url_for(repository, revision):
            return repository
    raise ValueError("frontend source URL is not pinned to its revision")


def validate_publication_evidence(
    receipt: object, *, expected_revision: str, repository: str = PUBLIC_REPOSITORY_URL
) -> dict[str, str]:
    """Validate a publication receipt naming `repository` (default: the current one)."""
    if repository not in RECORDED_PUBLIC_REPOSITORY_URLS:
        raise ValueError("Corresponding Source publication repository is not recorded")
    keys = {
        "schema_version",
        "status",
        "effective_date",
        "release_version",
        "public_source_revision",
        "source_url",
        "source_archive_url",
        "source_archive_sha256",
        "anonymous_checkout_sha256",
        "evidence_sha256",
    }
    if not isinstance(receipt, dict) or set(receipt) != keys:
        raise ValueError("Corresponding Source publication receipt key set is invalid")
    try:
        parsed_date = date.fromisoformat(str(receipt.get("effective_date", "")))
    except ValueError:
        parsed_date = None
    if (
        receipt.get("schema_version") != "corresponding-source-publication-receipt-v1"
        or receipt.get("status") != "published_anonymously_reachable"
        or receipt.get("public_source_revision") != expected_revision
        or receipt.get("source_url") != source_url_for(repository, expected_revision)
        or receipt.get("source_archive_url") != source_archive_url_for(repository, expected_revision)
        or parsed_date is None
        or parsed_date.isoformat() != receipt.get("effective_date")
        or not _not_after_today(parsed_date)
        or not RELEASE_VERSION_RE.fullmatch(str(receipt.get("release_version", "")))
        or any(
            not DIGEST_RE.fullmatch(str(receipt.get(key, "")))
            for key in ("source_archive_sha256", "anonymous_checkout_sha256", "evidence_sha256")
        )
    ):
        raise ValueError("Corresponding Source publication receipt identity or evidence is invalid")
    return {key: str(receipt[key]) for key in keys}


def load_publication_evidence(path: Path, *, expected_revision: str) -> dict[str, str]:
    metadata = path.lstat()
    if not path.is_file() or path.is_symlink() or metadata.st_size > 32 * 1024:
        raise ValueError("Corresponding Source publication receipt is unsafe")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Corresponding Source publication receipt is unreadable: {error}") from None
    return validate_publication_evidence(receipt, expected_revision=expected_revision)


RELEASE_FILE_MODE: Final = 0o444
RELEASE_DIRECTORY_MODE: Final = 0o555


def _require_release_modes(release: Path) -> None:
    """Every file of a release is RELEASE_FILE_MODE and every directory, the
    release itself included, RELEASE_DIRECTORY_MODE, as build and install
    write them.  The tree verifier has already closed the entry set."""
    for path in (release, *sorted(release.rglob("*"))):
        metadata = path.lstat()
        expected = RELEASE_DIRECTORY_MODE if stat.S_ISDIR(metadata.st_mode) else RELEASE_FILE_MODE
        if stat.S_IMODE(metadata.st_mode) != expected:
            raise ValueError(
                f"frontend release mode {stat.S_IMODE(metadata.st_mode):04o} is not "
                f"{expected:04o}: {path.relative_to(release).as_posix()}"
            )


def verify_published_release(
    release_directory: Path,
    *,
    authority_root: Path | None = None,
    required_contracts: Mapping[str, object] | None = None,
    require_digest_directory_name: bool = True,
    source_repositories: Collection[str] | None = None,
) -> dict[str, object]:
    """The runtime tree verification (backend/app/frontend_release.py) plus the
    publication and legal evidence, which are release-time checks.

    `source_repositories` is the set of public repositories the release may
    name; by default only PUBLIC_REPOSITORY_URL.  Only a recorded pair
    (`required_contracts`) may also name a former repository from
    RECORDED_PUBLIC_REPOSITORY_URLS; its manifest, the receipt inside it
    and its legal fields must all name the same one.
    """
    repositories = frozenset((PUBLIC_REPOSITORY_URL,) if source_repositories is None else source_repositories)
    if not repositories or repositories - RECORDED_PUBLIC_REPOSITORY_URLS:
        raise ValueError("frontend release names an unrecorded public repository set")
    if repositories != {PUBLIC_REPOSITORY_URL} and required_contracts is None:
        raise ValueError("only a recorded release pair may name a former public repository")
    verified = _verify_release_tree(
        release_directory,
        authority_root=authority_root,
        required_contracts=required_contracts,
        require_digest_directory_name=require_digest_directory_name,
        source_repositories=repositories,
    )
    _require_release_modes(Path(os.path.abspath(release_directory)))
    if verified["source_url_status"] == "provisional_pending_publication":
        return verified
    revision = str(verified["frontend_public_source_revision"])
    repository = recorded_source_repository(verified["source_url"], revision, repositories=repositories)
    publication = validate_publication_evidence(
        verified["source_publication"], expected_revision=revision, repository=repository
    )
    legal_fields = verified["formal_legal_release_fields"]
    if not isinstance(legal_fields, dict) or set(legal_fields) != FORMAL_LEGAL_FIELDS:
        raise ValueError("published frontend source evidence is invalid")
    release = Path(os.path.abspath(release_directory))
    if legal_fields != {
        "effective_date": legal_effective_date(release),
        "release_version": publication.get("release_version"),
        "public_revision": revision,
        "source_archive_url": publication.get("source_archive_url"),
        "source_archive_sha256": publication.get("source_archive_sha256"),
    }:
        raise ValueError("frontend source publication evidence identity is invalid")
    return {**verified, "source_publication": publication}


# The receipt claims that an anonymous reader can fetch this revision.
# Only fetching it anonymously can show that, so the build-side consumer does.
READBACK_HOSTS = frozenset({"github.com", "codeload.github.com"})
MAX_SOURCE_ARCHIVE_BYTES = 256 * 1024 * 1024


class _PublicHttpsRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse(newurl)
        if target.scheme != "https" or target.hostname not in READBACK_HOSTS:
            raise URLError(f"readback redirected outside the public source host: {target.hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _anonymous_fetch(url: str) -> bytes:
    """GET `url` as a stranger would: no credentials, cookies or ambient proxy."""

    opener = build_opener(ProxyHandler({}), _PublicHttpsRedirects())
    request = Request(url, headers={"User-Agent": "project-armillary-publication-readback"})
    with opener.open(request, timeout=60) as response:
        if response.status != 200:
            raise URLError(f"readback status {response.status}")
        payload = response.read(MAX_SOURCE_ARCHIVE_BYTES + 1)
    if len(payload) > MAX_SOURCE_ARCHIVE_BYTES:
        raise URLError("readback exceeded the source archive bound")
    return payload


def verify_anonymous_readback(evidence: dict[str, str]) -> None:
    """Fetch the named source archive anonymously and require the receipt's digest."""

    for key in ("source_url", "source_archive_url"):
        if urlparse(evidence[key]).hostname not in READBACK_HOSTS:
            raise ValueError(f"publication {key} is not on the public source host")
    try:
        _anonymous_fetch(evidence["source_url"])
        archive = _anonymous_fetch(evidence["source_archive_url"])
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise ValueError(
            f"Corresponding Source is not anonymously reachable at the receipt's URLs: {error}"
        ) from None
    if hashlib.sha256(archive).hexdigest() != evidence["source_archive_sha256"]:
        raise ValueError(
            "anonymously fetched source archive differs from the receipt's source_archive_sha256"
        )


# GitHub serves the tree page and the archive of any commit in the
# repository network, including pull-request and fork commits, at the same
# URLs.  The receipt producer therefore refuses a revision that the public
# repository's default branch does not contain; the consumers repeat that check
# here instead of trusting the receipt file, because a hand-written receipt for
# any served archive passes every other check.  One definition: the producer
# (scripts/publication/write_publication_receipt.py) uses these helpers too.
ANONYMOUS_GIT_TIMEOUT_SECONDS = 900


def anonymous_git_environment(home: Path) -> dict[str, str]:
    """A stranger's Git: no system/global config, helper, prompt, proxy or askpass."""

    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
        "SSH_ASKPASS": "/usr/bin/false",
        "GIT_NO_LAZY_FETCH": "1",
        "LC_ALL": "C",
    }


def anonymous_git_config(url: str) -> list[str]:
    scheme = urlparse(url).scheme
    if scheme not in {"https", "http"}:
        raise ValueError(f"public clone URL scheme is not HTTP(S): {url!r}")
    return [
        "-c",
        "credential.helper=",
        "-c",
        "core.askPass=",
        "-c",
        "http.proxy=",
        "-c",
        "protocol.allow=never",
        "-c",
        f"protocol.{scheme}.allow=always",
    ]


def not_on_default_branch(revision: str) -> str:
    return (
        f"revision {revision} is not reachable from the public repository's "
        "default branch (a pull-request or fork commit is served by the same "
        "URLs but is not published by this repository)"
    )


def public_clone_url() -> str:
    """The clone URL of the one repository SOURCE_URL_PREFIX names."""

    prefix = urlparse(SOURCE_URL_PREFIX)
    parts = prefix.path.strip("/").split("/")
    if prefix.scheme != "https" or prefix.hostname != "github.com" or len(parts) != 3:
        raise ValueError("source URL prefix is not a GitHub tree URL")
    return f"https://github.com/{parts[0]}/{parts[1]}.git"


def _anonymous_clone_transport(url: str) -> str:
    """The address Git contacts for `url`; tests point it at a local stand-in."""

    return url


def verify_default_branch_reachability(revision: str) -> str:
    """Anonymously fetch the default branch's history; `revision` must be on it.

    A treeless bare clone carries commits only.  Returns the default-branch tip.
    """

    if not REVISION_RE.fullmatch(revision):
        raise ValueError("publication revision must be 40 lowercase hex")
    url = _anonymous_clone_transport(public_clone_url())
    config = anonymous_git_config(url)
    with tempfile.TemporaryDirectory(prefix="public-default-branch-") as raw:
        home = Path(raw) / "home"
        home.mkdir()
        environment = anonymous_git_environment(home)
        history = Path(raw) / "history.git"

        def git(*arguments: str) -> subprocess.CompletedProcess[str]:
            try:
                return subprocess.run(
                    ["git", *config, *arguments],
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    text=True,
                    timeout=ANONYMOUS_GIT_TIMEOUT_SECONDS,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ValueError(f"anonymous git {arguments[0]} failed: {error}") from None

        cloned = git("clone", "--quiet", "--bare", "--filter=tree:0", "--no-tags", url, str(history))
        if cloned.returncode:
            raise ValueError(
                f"public repository history is not anonymously reachable: {cloned.stderr.strip()[-2000:]}"
            )
        tip = git("--git-dir", str(history), "rev-parse", "HEAD")
        if tip.returncode or not REVISION_RE.fullmatch(tip.stdout.strip()):
            raise ValueError("public repository has no default-branch tip")
        ancestor = git("--git-dir", str(history), "merge-base", "--is-ancestor", revision, tip.stdout.strip())
        if ancestor.returncode:
            raise ValueError(not_on_default_branch(revision))
        return tip.stdout.strip()


def validate_publication_receipt(path: Path, *, expected_revision: str) -> dict[str, str]:
    """Consume evidence of publication instead of an operator assertion."""
    evidence = load_publication_evidence(path, expected_revision=expected_revision)
    verify_anonymous_readback(evidence)
    verify_default_branch_reachability(evidence["public_source_revision"])
    return evidence


def formal_legal_release_fields(
    publication_evidence: dict[str, str] | None, shown_effective_date: str
) -> dict[str, str] | None:
    """Bind release-owned legal fields to verified publication evidence.

    The legal approval record is private, so this published producer cannot and
    does not read it: it runs in the public checkout.  That the record leaves
    these fields to this producer is checked privately, by Gate F's
    verify_pre_image_readiness against the private tree.

    `effective_date` is the date the legal pages show, read from
    the pages by `legal_effective_date`; the receipt's own `effective_date` is
    the readback date and stays inside `source_publication`.
    """
    if publication_evidence is None:
        return None
    return {
        "effective_date": shown_effective_date,
        "release_version": publication_evidence["release_version"],
        "public_revision": publication_evidence["public_source_revision"],
        "source_archive_url": publication_evidence["source_archive_url"],
        "source_archive_sha256": publication_evidence["source_archive_sha256"],
    }


def _make_tree_removable(root: Path) -> None:
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()), key=lambda path: len(path.parts)
    ):
        os.chmod(directory, 0o755)
    os.chmod(root, 0o755)


def runtime_asset_names(source_root: Path = ROOT) -> set[str]:
    return set(discover_source_assets(source_root / "frontend"))


def exact_contract(source_root: Path = ROOT) -> dict[str, str | int]:
    return _runtime_exact_contract(source_root)


def _manifest_payload(
    *,
    revision: str,
    contract: dict[str, str | int],
    files: dict[str, dict[str, object]],
    publication_evidence: dict[str, str] | None,
    legal_release_fields: dict[str, str] | None,
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "artifact_type": "classical-astrology-frontend-release",
        "frontend_public_source_revision": revision,
        "source_url": f"{SOURCE_URL_PREFIX}{revision}",
        # Only a verified publication receipt may make an immutable public claim.
        "source_url_status": (
            "published_and_expected_anonymously_reachable"
            if publication_evidence is not None
            else "provisional_pending_publication"
        ),
        "source_publication": publication_evidence,
        "formal_legal_release_fields": legal_release_fields,
        "required_contracts": {
            "api_schema_version": contract["api_schema_version"],
            "dossier_version": contract["dossier_version"],
            "export_contract_version": contract["export_contract_version"],
        },
        "files": files,
    }


def _require_published_checkout(source_root: Path, publication_evidence: dict[str, str]) -> None:
    """A published release is built only from the public checkout its receipt
    read back: then anyone holding that checkout and the release record
    rebuilds the same digest (recompute_release).  Built from another tree
    (the private one, whose frontend set differs), it could not be."""
    try:
        observed = observe_publication_tree(source_root).index_sha256
    except (OSError, RuntimeError) as error:
        raise ValueError(
            f"a published frontend release is built only from the public checkout: {error}"
        ) from None
    if observed != publication_evidence["anonymous_checkout_sha256"]:
        raise ValueError(
            "a published frontend release is built only from the public checkout its receipt "
            "read back; this tree's identity differs"
        )


def build_release(
    *,
    source_root: Path,
    output_parent: Path,
    public_source_revision: str,
    require_clean_revision: bool = True,
    publication_receipt: Path | None = None,
) -> dict[str, object]:
    source_root = source_root.resolve()
    output_parent = Path(os.path.abspath(output_parent))
    if not REVISION_RE.fullmatch(public_source_revision):
        raise ValueError("frontend public source revision must be 40 lowercase hex")
    publication_evidence = (
        validate_publication_receipt(publication_receipt, expected_revision=public_source_revision)
        if publication_receipt is not None
        else None
    )
    if publication_evidence is not None:
        _require_published_checkout(source_root, publication_evidence)
    legal_release_fields = (
        formal_legal_release_fields(publication_evidence, legal_effective_date(source_root / "frontend"))
        if publication_evidence is not None
        else None
    )
    if require_clean_revision:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=source_root, check=True, text=True, capture_output=True
        ).stdout
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=source_root, check=True, text=True, capture_output=True
        ).stdout.strip()
        if status:
            raise RuntimeError("frontend release requires a clean source tree")
        if revision != public_source_revision:
            raise RuntimeError("frontend release revision differs from source HEAD")
    frontend = source_root / "frontend"
    if not frontend.is_dir() or frontend.is_symlink():
        raise ValueError("frontend source must be a regular directory")
    assets = runtime_asset_names(source_root)
    contract = exact_contract(source_root)
    output_parent = external_output_path(
        output_parent, source_root=source_root, role="frontend release output"
    )
    output_parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".frontend-release-", dir=output_parent))
    published = False
    try:
        files: dict[str, dict[str, object]] = {}
        for name in sorted(assets):
            source = frontend / name
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"required frontend asset is missing or unsafe: {name}")
            target = temporary / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if require_clean_revision:
                committed = subprocess.run(
                    ["git", "show", f"{public_source_revision}:frontend/{name}"],
                    cwd=source_root,
                    check=True,
                    capture_output=True,
                ).stdout
                target.write_bytes(committed)
            else:
                shutil.copyfile(source, target)
            os.chmod(target, RELEASE_FILE_MODE)
            files[name] = {"sha256": _sha256(target), "size_bytes": target.stat().st_size}
        payload = _manifest_payload(
            revision=public_source_revision,
            contract=contract,
            files=files,
            publication_evidence=publication_evidence,
            legal_release_fields=legal_release_fields,
        )
        digest = _runtime_artifact_digest(payload)
        manifest = {**payload, "artifact_digest": digest}
        manifest_path = temporary / MANIFEST_NAME
        manifest_path.write_bytes(canonical_json_bytes(manifest) + b"\n")
        os.chmod(manifest_path, RELEASE_FILE_MODE)
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            os.chmod(directory, RELEASE_DIRECTORY_MODE)
        os.chmod(temporary, RELEASE_DIRECTORY_MODE)
        destination = output_parent / digest
        if destination.exists() or destination.is_symlink():
            raise FileExistsError(f"frontend release already exists: {destination}")
        os.replace(temporary, destination)
        published = True
        verified = verify_release(destination, authority_root=source_root)
        return {**verified, "release_directory": str(destination)}
    finally:
        if not published and temporary.exists():
            _make_tree_removable(temporary)
            shutil.rmtree(temporary)


MAX_RELEASE_RECORD_BYTES = 4 * 1024 * 1024


def recompute_release(
    *, source_root: Path, release_record: Path, require_clean_revision: bool = True,
) -> dict[str, object]:
    """Rebuild a published release from the public checkout and the receipt its
    record (frontend-release.json) carries; the rebuilt record must equal it.

    This is how a reader checks the frontend digest the service reports, with
    public material only: the checkout at the record's revision and the record.
    """
    try:
        if release_record.is_symlink() or release_record.stat().st_size > MAX_RELEASE_RECORD_BYTES:
            raise ValueError("not a bounded regular file")
        record = json.loads(release_record.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ValueError(f"frontend release record is unreadable: {error}") from None
    if not isinstance(record, dict) or not isinstance(record.get("source_publication"), dict):
        raise ValueError("only a published frontend release record is recomputable")
    revision = record.get("frontend_public_source_revision")
    if not isinstance(revision, str) or not REVISION_RE.fullmatch(revision):
        raise ValueError("frontend release record names no public revision")
    with tempfile.TemporaryDirectory(prefix="frontend-recompute-") as raw:
        work = Path(raw)
        receipt = work / "publication-receipt.json"
        receipt.write_text(json.dumps(record["source_publication"]), encoding="utf-8")
        rebuilt = build_release(
            source_root=source_root, output_parent=work / "release", public_source_revision=revision,
            require_clean_revision=require_clean_revision, publication_receipt=receipt,
        )
        directory = Path(str(rebuilt["release_directory"]))
        rebuilt_record = json.loads((directory / MANIFEST_NAME).read_text(encoding="utf-8"))
        _make_tree_removable(directory)
    if rebuilt_record != record:
        differing = sorted(key for key in {*record, *rebuilt_record}
                           if record.get(key) != rebuilt_record.get(key))
        raise ValueError(
            "frontend release record differs from its rebuild from the public checkout in: "
            + ", ".join(differing)
        )
    return {"artifact_digest": rebuilt_record["artifact_digest"],
            "frontend_public_source_revision": revision,
            "recomputed_from_public_checkout": str(source_root)}


def verify_release(
    release_directory: Path,
    *,
    authority_root: Path | None = None,
    required_contracts: dict[str, str] | None = None,
) -> dict[str, object]:
    """Verify against this checkout's contract, another tree's, or a recorded one.

    A new release must match the checkout that builds or deploys it.  A release
    pair already recorded in deployment state carries the contract it was
    accepted with; it is verified against that, never against a newer checkout,
    and against the public repository it was published to, from the closed set
    RECORDED_PUBLIC_REPOSITORY_URLS.  A new release names only the
    current repository.
    """
    if required_contracts is not None:
        if authority_root is not None:
            raise ValueError("frontend release needs exactly one contract authority")
        return verify_published_release(
            release_directory,
            required_contracts=required_contracts,
            source_repositories=RECORDED_PUBLIC_REPOSITORY_URLS,
        )
    return verify_published_release(
        release_directory, authority_root=ROOT if authority_root is None else authority_root
    )


def require_published(manifest: dict[str, object]) -> None:
    """A release may only be bound or installed once its source is published.

    Install does not re-read the public repository (a recorded choice): it runs on the host inside the maintenance window, and the
    approved artifact digest it requires binds a manifest that build_release
    writes as published only after validate_publication_receipt, which reads
    the archive and the default branch anonymously.  A host-side readback
    would add an outbound dependency there without checking anything new.
    """
    if manifest.get("source_url_status") != PUBLISHED_SOURCE_STATUS:
        raise ValueError("frontend release must be published and anonymously reachable")


def install_release(
    incoming_release: Path, release_root: Path, *, expected_artifact_digest: str, authority_root: Path = ROOT
) -> dict[str, object]:
    """Copy one verified release into a new immutable digest-named directory.

    Every file is read through a held descriptor and its identity compared
    before and after the copy, then the materialized tree is re-verified
    before the atomic publish; a source changed mid-copy or a corrupted copy
    never becomes a release directory.
    """
    incoming = Path(os.path.abspath(incoming_release))
    if not re.fullmatch(r"[0-9a-f]{64}", expected_artifact_digest):
        raise ValueError("approved frontend digest must be 64 lowercase hex")
    verified = verify_release(incoming, authority_root=authority_root)
    require_published(verified)
    if verified.get("artifact_digest") != expected_artifact_digest:
        raise ValueError("incoming release differs from approved frontend digest")
    root = Path(os.path.abspath(release_root))
    destination = root / expected_artifact_digest
    root.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"frontend release already installed: {destination}")
    temporary = Path(tempfile.mkdtemp(prefix=".frontend-install-", dir=root))
    published = False
    try:
        for source in sorted(incoming.rglob("*")):
            target = temporary / source.relative_to(incoming)
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(source, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
            try:
                before = os.fstat(descriptor)
                with os.fdopen(descriptor, "rb", closefd=False) as reader, target.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                after = os.fstat(descriptor)
                if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise RuntimeError("frontend input changed during descriptor copy")
            finally:
                os.close(descriptor)
            os.chmod(target, RELEASE_FILE_MODE)
        for directory in sorted(
            (path for path in temporary.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts),
            reverse=True,
        ):
            os.chmod(directory, RELEASE_DIRECTORY_MODE)
        os.chmod(temporary, RELEASE_DIRECTORY_MODE)
        materialized = verify_published_release(
            temporary, authority_root=authority_root, require_digest_directory_name=False
        )
        require_published(materialized)
        if materialized.get("artifact_digest") != expected_artifact_digest:
            raise ValueError("frontend bundle differs from approved frontend digest")
        os.replace(temporary, destination)
        published = True
        directory_descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return {**materialized, "release_directory": str(destination)}
    finally:
        if not published and temporary.exists():
            _make_tree_removable(temporary)
            shutil.rmtree(temporary)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--source-root", type=Path, required=True)
    build.add_argument("--output-parent", type=Path, required=True)
    build.add_argument("--public-source-revision", required=True)
    build.add_argument(
        "--publication-receipt",
        type=Path,
        help=(
            "verified Corresponding Source publication receipt for this exact "
            "revision; omission leaves the immutable manifest provisional"
        ),
    )
    verify = commands.add_parser("verify")
    verify.add_argument("--release-directory", type=Path, required=True)
    recompute = commands.add_parser(
        "recompute", help="rebuild a published release from the public checkout and its record"
    )
    recompute.add_argument("--source-root", type=Path, required=True,
                           help="the public checkout at the record's revision")
    recompute.add_argument("--release-record", type=Path, required=True,
                           help="the release's frontend-release.json")
    install = commands.add_parser(
        "install", help="copy a verified release into a new immutable digest directory"
    )
    install.add_argument("--incoming-release-dir", type=Path, required=True)
    install.add_argument("--release-root", type=Path, required=True)
    install.add_argument("--expected-artifact-digest", required=True)
    args = parser.parse_args()
    if args.command == "install":
        if os.geteuid() == 0:
            from scripts.tools.staging_secure_io import require_privileged_checkout

            require_privileged_checkout(ROOT)  # root runs only a trusted checkout
        result = install_release(
            args.incoming_release_dir,
            args.release_root,
            expected_artifact_digest=args.expected_artifact_digest,
        )
    elif args.command == "recompute":
        result = recompute_release(source_root=args.source_root, release_record=args.release_record)
    elif args.command == "build":
        result = build_release(
            source_root=args.source_root,
            output_parent=args.output_parent,
            public_source_revision=args.public_source_revision,
            publication_receipt=args.publication_receipt,
        )
    else:
        result = verify_release(args.release_directory)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
