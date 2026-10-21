#!/usr/bin/env python3
"""Write the Corresponding Source publication receipt from an anonymous readback.

``write`` reads the published revision back as a stranger would (no
credentials, cookies, proxy, Git system/global configuration or credential
helper) and writes a receipt only when

1. the source archive served at ``source_archive_url`` holds exactly the
   exported candidate's files (bytes and executable bit),
2. an anonymous ``git clone`` checked out at the revision, which must be
   reachable from the default branch, holds exactly the same files, and
3. both the candidate and that clone carry the tree digest
   verify_publication_candidate printed (``--verified-tree-sha256``), which
   names every file's path, bytes and Git executable bit: the push is
   irreversible, so a candidate changed between verification and push is
   refused rather than receipted against its new contents.

``compare`` runs before the push (the local commit equals the candidate) and
``verify`` re-checks a receipt.  The consumer is scripts/deployment/frontend_release.py;
the repository and URLs come from its constants, so this producer cannot write
a receipt the consumer would refuse for its identity.  Release records
(``releases/<version>/frontend-release.json``) are the only additions a public
tree may hold beyond the candidate.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from scripts.deployment import frontend_release as consumer
from scripts.tools.output_confinement import external_output_path
from scripts.tools.source_tree_identity import (
    git_executable,
    is_public_release_record,
    observe_publication_tree,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ORIGIN = "https://github.com"
INVENTORY_NAME = "PUBLICATION_FILES.json"
RECEIPT_NAME = "publication-receipt.json"
EVIDENCE_NAME = "publication-evidence.json"
EVIDENCE_SCHEMA = "corresponding-source-publication-evidence-v3"
MAX_EVIDENCE_BYTES = 32 * 1024
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
MAX_ARCHIVE_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
_scrubbed_git_environment = consumer.anonymous_git_environment

# path -> (size, sha256, Git executable bit)
Inventory = dict[str, tuple[int, str, bool]]


class ReceiptRefusal(RuntimeError):
    """The published revision does not demonstrably equal the candidate."""


def accepted_repository() -> str:
    """`owner/name` of the only repository the receipt consumer accepts."""

    prefix = urlparse(consumer.SOURCE_URL_PREFIX)
    parts = PurePosixPath(prefix.path).parts
    if f"{prefix.scheme}://{prefix.hostname}" != PUBLIC_ORIGIN or len(parts) != 4 or parts[3] != "tree":
        raise ReceiptRefusal("receipt consumer source URL prefix is not a GitHub tree URL")
    return f"{parts[1]}/{parts[2]}"


def canonical_urls(revision: str) -> dict[str, str]:
    return {
        "source_url": f"{consumer.SOURCE_URL_PREFIX}{revision}",
        "source_archive_url": f"{consumer.SOURCE_ARCHIVE_URL_PREFIX}{revision}.tar.gz",
        "clone_url": f"{PUBLIC_ORIGIN}/{accepted_repository()}.git",
    }


def require_repository_url(raw: str) -> str:
    parsed = urlparse(raw.strip())
    named = parsed.path.removesuffix("/").removesuffix(".git").lstrip("/")
    accepted = accepted_repository()
    if (
        parsed.scheme != "https" or parsed.hostname != "github.com"
        or parsed.username is not None or parsed.password is not None
        or parsed.port is not None or parsed.query or parsed.fragment
        or named != accepted
    ):
        raise ReceiptRefusal(
            f"repository {raw!r} is not the public source repository the receipt consumer "
            f"accepts (https://github.com/{accepted})"
        )
    return accepted


def tree_inventory(root: Path) -> Inventory:
    """Every regular file under `root` outside `.git`; anything else is refused."""

    observed: Inventory = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ReceiptRefusal(f"non-regular file in tree: {relative.as_posix()}")
        observed[relative.as_posix()] = (path.stat().st_size, sha256_file(path), git_executable(mode))
    return observed


def _load_inventory_declaration(path: Path) -> Inventory:
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["files"]
        declared = {
            entry["path"]: (int(entry["size_bytes"]), str(entry["sha256"]), entry["executable"])
            for entry in entries
        }
        if any(type(executable) is not bool for _size, _digest, executable in declared.values()):
            raise ValueError("an entry does not declare its executable bit")
        return declared
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        raise ReceiptRefusal(f"{path.name} is not a publication inventory: {error}") from None


def candidate_inventory(candidate: Path) -> tuple[Inventory, str]:
    """The exported candidate, proven equal to its own closed inventory."""

    try:
        identity = observe_publication_tree(candidate)
    except (OSError, RuntimeError) as error:
        raise ReceiptRefusal(f"candidate differs from its own inventory: {error}") from None
    return tree_inventory(candidate), identity.index_sha256


def compare_inventories(role: str, expected: Inventory, observed: Inventory) -> None:
    missing = sorted(set(expected) - set(observed))
    unexpected = sorted(p for p in set(observed) - set(expected) if not is_public_release_record(p))
    changed = sorted(p for p in set(expected) & set(observed) if expected[p] != observed[p])
    if missing or unexpected or changed:
        raise ReceiptRefusal(
            f"{role} differs from the exported candidate: missing={missing[:20]} "
            f"unexpected={unexpected[:20]} changed={changed[:20]}"
        )


def archive_inventory(payload: bytes, *, repository: str, revision: str) -> Inventory:
    """Regular files of a GitHub-style source archive, under its one top directory."""

    prefix = f"{repository.split('/', 1)[1]}-{revision}"
    observed: Inventory = {}
    expanded = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
            if archive.pax_headers.get("comment") != revision:
                raise ReceiptRefusal("source archive does not declare the receipt revision")
            for member in archive:
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != prefix or ".." in parts:
                    raise ReceiptRefusal(f"source archive member outside {prefix}/: {member.name!r}")
                if member.isdir():
                    continue
                expanded += member.size
                handle = archive.extractfile(member) if member.isreg() else None
                relative = PurePosixPath(*parts[1:]).as_posix()
                if handle is None or relative in observed or expanded > MAX_ARCHIVE_EXPANDED_BYTES:
                    raise ReceiptRefusal(f"source archive member is not acceptable: {member.name!r}")
                content = handle.read()
                observed[relative] = (
                    len(content), hashlib.sha256(content).hexdigest(), git_executable(member.mode)
                )
    except (tarfile.TarError, gzip.BadGzipFile, EOFError, OSError) as error:
        raise ReceiptRefusal(f"source archive is not a readable tar.gz: {error}") from None
    return observed


def anonymous_clone(clone_url: str, destination: Path, revision: str) -> str:
    """Clone anonymously, check out `revision`, return the default-branch tip."""

    try:
        config = consumer.anonymous_git_config(clone_url)
    except ValueError as error:
        raise ReceiptRefusal(str(error)) from None
    with tempfile.TemporaryDirectory(prefix="anonymous-home-") as raw_home:
        environment = _scrubbed_git_environment(Path(raw_home))

        def git(*arguments: str, cwd: Path | None = None) -> str:
            try:
                completed = subprocess.run(
                    ["git", *config, *arguments], cwd=cwd, env=environment,
                    stdin=subprocess.DEVNULL, capture_output=True, text=True,
                    timeout=900, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise ReceiptRefusal(f"anonymous git {arguments[0]} failed: {error}") from None
            if completed.returncode:
                raise ReceiptRefusal(f"anonymous git {arguments[0]} failed: {completed.stderr[-2000:]}")
            return completed.stdout.strip()

        git("clone", "--quiet", "--no-checkout", "--no-tags", clone_url, str(destination))
        try:
            git("checkout", "--quiet", "--detach", revision, cwd=destination)
        except ReceiptRefusal:
            raise ReceiptRefusal(f"revision {revision} is not in the anonymous clone") from None
        if git("rev-parse", "HEAD", cwd=destination) != revision:
            raise ReceiptRefusal("anonymous checkout HEAD is not the receipt revision")
        tip = git("rev-parse", "refs/remotes/origin/HEAD", cwd=destination)
        try:
            git("merge-base", "--is-ancestor", revision, tip, cwd=destination)
        except ReceiptRefusal:
            raise ReceiptRefusal(consumer.not_on_default_branch(revision)) from None
        return tip


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def produce_receipt(
    *,
    revision: str,
    candidate: Path,
    verified_tree_sha256: str,
    release_version: str,
    output_dir: Path,
    checkout_dir: Path | None = None,
    origin: str = PUBLIC_ORIGIN,
) -> dict[str, str]:
    """`origin` replaces the transport only; recorded URLs stay canonical."""

    fetch = consumer._anonymous_fetch
    if not REVISION_RE.fullmatch(revision):
        raise ReceiptRefusal("revision must be a full lowercase 40-hex commit")
    if not re.fullmatch(r"[0-9a-f]{64}", verified_tree_sha256):
        raise ReceiptRefusal("verified tree sha256 must be the 64-hex digest the candidate verifier printed")
    if not consumer.RELEASE_VERSION_RE.fullmatch(release_version):
        raise ReceiptRefusal(f"release version is invalid: {release_version!r}")
    try:
        output_dir = external_output_path(output_dir, source_root=PROJECT_ROOT, role="receipt output")
        if checkout_dir is not None:
            checkout_dir = external_output_path(checkout_dir, source_root=PROJECT_ROOT, role="checkout")
    except ValueError as error:
        raise ReceiptRefusal(str(error)) from None
    if any(path is not None and (path.exists() or path.is_symlink()) for path in (output_dir, checkout_dir)):
        raise ReceiptRefusal("output already exists, refusing to overwrite")
    expected, inventory_sha256 = candidate_inventory(candidate.resolve())
    if inventory_sha256 != verified_tree_sha256:
        raise ReceiptRefusal("candidate changed after verification: its tree digest is not the verified one")
    repository, urls = accepted_repository(), canonical_urls(revision)

    def transported(url: str) -> str:
        return origin + url[len(PUBLIC_ORIGIN):]

    try:
        archive = fetch(transported(urls["source_archive_url"]))
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise ReceiptRefusal(f"source archive is not anonymously reachable: {error}") from None
    compare_inventories(
        "anonymously fetched source archive", expected,
        archive_inventory(archive, repository=repository, revision=revision),
    )
    with tempfile.TemporaryDirectory(prefix="anonymous-clone-") as raw_clone:
        clone = Path(raw_clone) / "checkout"
        tip = anonymous_clone(transported(urls["clone_url"]), clone, revision)
        compare_inventories("anonymous checkout", expected, tree_inventory(clone))
        try:
            checkout_sha256 = observe_publication_tree(clone).index_sha256
        except (OSError, RuntimeError) as error:
            raise ReceiptRefusal(f"anonymous checkout differs from its own inventory: {error}") from None
        if checkout_sha256 != verified_tree_sha256:
            raise ReceiptRefusal("anonymous checkout tree digest is not the verified candidate's")
        output_dir.mkdir(parents=True)
        if checkout_dir is not None:
            checkout_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(clone), str(checkout_dir))

    observed_at = datetime.now(timezone.utc).astimezone(timezone.utc)
    evidence = {
        "schema_version": EVIDENCE_SCHEMA,
        "observed_at_utc": observed_at.isoformat(timespec="seconds"),
        "public_repository": repository,
        "public_source_revision": revision,
        "default_branch_tip": tip,
        **{key: urls[key] for key in ("source_url", "source_archive_url", "clone_url")},
        "source_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "publication_files_sha256": verified_tree_sha256,
        "public_file_count": len(expected),
        "archive_tree_equals_candidate": True,
        "anonymous_checkout_equals_candidate": True,
    }
    evidence_bytes = _canonical_json(evidence)
    (output_dir / EVIDENCE_NAME).write_bytes(evidence_bytes)
    receipt = {
        "schema_version": "corresponding-source-publication-receipt-v1",
        "status": "published_anonymously_reachable",
        "effective_date": observed_at.date().isoformat(),
        "release_version": release_version,
        "public_source_revision": revision,
        "source_url": urls["source_url"],
        "source_archive_url": urls["source_archive_url"],
        "source_archive_sha256": evidence["source_archive_sha256"],
        "anonymous_checkout_sha256": checkout_sha256,
        "evidence_sha256": hashlib.sha256(evidence_bytes).hexdigest(),
    }
    # The producer's output must satisfy the consumer's own offline validator.
    consumer_view = consumer.validate_publication_evidence(receipt, expected_revision=revision)
    (output_dir / RECEIPT_NAME).write_bytes(_canonical_json(receipt))
    return consumer_view


def _verify_evidence_content(evidence_path: Path, receipt: dict[str, str], checkout: Path) -> None:
    """Every field of the evidence the producer wrote, against the receipt it is
    bound to, the canonical URLs and the checkout it describes."""

    try:
        if evidence_path.is_symlink() or evidence_path.stat().st_size > MAX_EVIDENCE_BYTES:
            raise ValueError("not a bounded regular file")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        observed_date = datetime.fromisoformat(str(evidence["observed_at_utc"])).date().isoformat()
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        raise ReceiptRefusal(f"publication evidence is unreadable: {error}") from None
    revision = receipt["public_source_revision"]
    tip = evidence.get("default_branch_tip")
    expected = {
        "schema_version": EVIDENCE_SCHEMA,
        "public_repository": accepted_repository(),
        "public_source_revision": revision,
        **canonical_urls(revision),
        "source_archive_sha256": receipt["source_archive_sha256"],
        "publication_files_sha256": receipt["anonymous_checkout_sha256"],
        # The checkout's inventory lists every candidate file but itself.
        "public_file_count": len(_load_inventory_declaration(checkout / INVENTORY_NAME)) + 1,
        "archive_tree_equals_candidate": True,
        "anonymous_checkout_equals_candidate": True,
    }
    # Checked below: the observation time against the receipt date, the tip in the checkout.
    observed_fields = {"observed_at_utc", "default_branch_tip"}
    differing = sorted(
        key for key in (set(evidence) | set(expected)) - observed_fields
        if key not in expected or evidence.get(key) != expected[key]
        or type(evidence.get(key)) is not type(expected[key])
    )
    if observed_date != receipt["effective_date"]:
        differing.append("observed_at_utc")
    if not isinstance(tip, str) or not REVISION_RE.fullmatch(tip) or subprocess.run(
        ["git", "merge-base", "--is-ancestor", revision, tip],
        cwd=checkout, capture_output=True, check=False,
    ).returncode != 0:
        differing.append("default_branch_tip")
    if differing:
        raise ReceiptRefusal(f"publication evidence differs from the receipt and checkout in: {differing}")


def verify_receipt(
    *, receipt_path: Path, revision: str, evidence_path: Path | None = None, checkout: Path | None = None,
) -> dict[str, str]:
    """Re-check a receipt: consumer readback, evidence bytes and fields, and checkout identity."""

    if evidence_path is not None and checkout is None:
        raise ReceiptRefusal("publication evidence is verified against the checkout it describes: "
                             "pass the checkout too")
    try:
        evidence = consumer.validate_publication_receipt(receipt_path, expected_revision=revision)
    except (OSError, ValueError) as error:
        raise ReceiptRefusal(str(error)) from None
    if evidence_path is not None and sha256_file(evidence_path) != evidence["evidence_sha256"]:
        raise ReceiptRefusal("publication evidence bytes differ from evidence_sha256")
    if checkout is not None:
        checkout = checkout.resolve()
        try:
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True, text=True, check=False
            )
        except OSError as error:
            raise ReceiptRefusal(f"checkout cannot be read: {error}") from None
        if head.returncode or head.stdout.strip() != revision:
            raise ReceiptRefusal("checkout HEAD is not the receipt revision")
        observed = tree_inventory(checkout)
        observed.pop(INVENTORY_NAME, None)
        compare_inventories("checkout", _load_inventory_declaration(checkout / INVENTORY_NAME), observed)
        try:
            # The closed inventory itself: non-empty, its directories and its own mode.
            observe_publication_tree(checkout)
        except (OSError, RuntimeError) as error:
            raise ReceiptRefusal(f"checkout differs from its own inventory: {error}") from None
        if sha256_file(checkout / INVENTORY_NAME) != evidence["anonymous_checkout_sha256"]:
            raise ReceiptRefusal("checkout inventory differs from anonymous_checkout_sha256")
        if evidence_path is not None:
            _verify_evidence_content(evidence_path, evidence, checkout)
    return evidence


def compare_commit(*, candidate: Path, checkout: Path) -> str:
    """Before any push: the commit at `checkout` HEAD holds exactly the candidate,
    and every commit the push would add (reachable from HEAD, on no
    remote-tracking branch) carries only its subject line: no body, so no
    co-author, generator or other trailer reaches the public history.

    The commit is read through `git archive`, so a file the public `.gitignore`
    kept out of the commit is seen as missing; the operator's Git configuration
    cannot change the bytes compared.
    """

    expected, _ = candidate_inventory(candidate.resolve())
    name = accepted_repository().split("/", 1)[1]
    try:
        with tempfile.TemporaryDirectory(prefix="compare-home-") as raw_home:
            environment = _scrubbed_git_environment(Path(raw_home))
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=checkout, capture_output=True,
                text=True, check=True, env=environment,
            ).stdout.strip()
            archive = subprocess.run(
                ["git", "archive", "--format=tar.gz", f"--prefix={name}-{revision}/", "HEAD"],
                cwd=checkout, capture_output=True, check=True, env=environment,
            ).stdout
            # NUL-separated: commit id, then its whole message.
            added = subprocess.run(
                ["git", "log", "--format=%H%x00%B%x00", "HEAD", "--not", "--remotes"],
                cwd=checkout, capture_output=True, text=True, check=True, env=environment,
            ).stdout.split("\0")
    except (OSError, subprocess.CalledProcessError) as error:
        raise ReceiptRefusal(f"cannot read the commit to be published: {error}") from None
    for commit, message in zip(added[0::2], added[1::2]):
        if "\n" in message.strip():
            raise ReceiptRefusal(
                f"commit to be published {commit.strip()} must carry only its subject line"
            )
    compare_inventories(
        "commit to be published", expected,
        archive_inventory(archive, repository=accepted_repository(), revision=revision),
    )
    return revision


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    write = commands.add_parser("write", help="read the published revision back and write the receipt")
    write.add_argument("--repository-url", required=True)
    write.add_argument("--revision", required=True)
    write.add_argument("--candidate", type=Path, required=True)
    write.add_argument("--verified-tree-sha256", required=True,
                       help="the tree digest verify_publication_candidate printed for this candidate")
    write.add_argument("--release-version", required=True)
    write.add_argument("--output-dir", type=Path, required=True)
    write.add_argument("--checkout-dir", type=Path)
    compare = commands.add_parser("compare", help="before pushing: the local commit equals the candidate")
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--checkout", type=Path, required=True)
    verify = commands.add_parser("verify", help="re-check a receipt anonymously")
    verify.add_argument("--receipt", type=Path, required=True)
    verify.add_argument("--revision", required=True)
    verify.add_argument("--evidence", type=Path)
    verify.add_argument("--checkout", type=Path)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "write":
            require_repository_url(arguments.repository_url)
            result = produce_receipt(
                revision=arguments.revision, candidate=arguments.candidate,
                verified_tree_sha256=arguments.verified_tree_sha256,
                release_version=arguments.release_version, output_dir=arguments.output_dir,
                checkout_dir=arguments.checkout_dir,
            )
            print(f"PUBLICATION RECEIPT WRITTEN: {arguments.output_dir / RECEIPT_NAME}")
        elif arguments.command == "compare":
            revision = compare_commit(candidate=arguments.candidate, checkout=arguments.checkout)
            print(f"COMMIT EQUALS CANDIDATE: {revision}")
            return 0
        else:
            result = verify_receipt(
                receipt_path=arguments.receipt, revision=arguments.revision,
                evidence_path=arguments.evidence, checkout=arguments.checkout,
            )
            print("PUBLICATION RECEIPT VERIFIED")
    except ReceiptRefusal as error:
        print(f"PUBLICATION RECEIPT REFUSED: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
