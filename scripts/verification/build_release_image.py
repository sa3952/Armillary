#!/usr/bin/env python3
"""Build the production image from one exact Git revision (Gate D input).

The build context is a `git archive` snapshot of HEAD, never the working tree,
after the `.dockerignore` whitelist check.  A release candidate is built by an
ephemeral BuildKit container (pinned image, no cache) and needs a verified
Corresponding Source publication receipt for its revision; a diagnostic build
uses the default builder and is labelled provisional.  The receipt written to
--evidence-dir binds the image ID to the revision, the context tree and the
publication status.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from typing import Any

from scripts.deployment.frontend_release import validate_publication_receipt
from scripts.tools.output_confinement import external_output_path
from scripts.tools.source_tree_identity import materialize_git_snapshot
from scripts.verification.verify_docker_context import DockerContextFailure, verify as verify_context


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# The buildx-stable-1 index read anonymously 2026-10-06, pinned by digest.
BUILDKIT_IMAGE = (
    "moby/buildkit:buildx-stable-1@sha256:"
    "cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"
)
BUILD_PURPOSES = ("diagnostic", "release-candidate")


class BuildTransactionFailure(RuntimeError):
    pass


def platform_args(platform: str | None) -> list[str]:
    """Docker CLI arguments for `platform`, without normalizing it."""

    return ["--platform", platform] if platform else []


def platform_contract(platform: str) -> tuple[str, str]:
    """(os, architecture) of a production platform: linux/amd64 or linux/arm64[/variant]."""

    parts = platform.split("/")
    if len(parts) not in (2, 3) or not all(parts[:2]):
        raise ValueError(f"unsupported Docker platform syntax: {platform}")
    if parts[0] != "linux" or parts[1] not in {"amd64", "arm64"}:
        raise ValueError(f"unsupported production platform: {platform}")
    return parts[0], parts[1]


def clean_checkout_required(*, purpose: str, requested: bool) -> bool:
    """Release builds are clean-tree operations by definition."""

    if purpose not in BUILD_PURPOSES:
        raise BuildTransactionFailure(f"unknown build purpose: {purpose}")
    return requested or purpose != "diagnostic"


def publication_status_for_build(
    *, purpose: str, publication_receipt: Path | None, revision: str
) -> str:
    if purpose not in BUILD_PURPOSES:
        raise BuildTransactionFailure(f"unknown build purpose: {purpose}")
    if publication_receipt is None:
        if purpose != "diagnostic":
            raise BuildTransactionFailure(f"{purpose} requires a verified publication receipt")
        return "provisional_unpublished"
    try:
        validate_publication_receipt(publication_receipt, expected_revision=revision)
    except (OSError, ValueError) as error:
        raise BuildTransactionFailure(str(error)) from None
    return "published_anonymously_reachable"


def _run(
    command: list[str], *, cwd: Path | None = None, timeout: int = 1800, check: bool = True,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=cwd, check=False, capture_output=True, text=True, timeout=timeout
    )
    if check and completed.returncode:
        raise BuildTransactionFailure(
            f"command failed ({completed.returncode}): {' '.join(command[:4])}\n"
            f"{completed.stderr[-4000:]}"
        )
    return completed


def _revision(root: Path, require_clean: bool) -> str:
    revision = _run(["git", "rev-parse", "HEAD"], cwd=root).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise BuildTransactionFailure("build requires an exact Git revision")
    status = _run(["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root).stdout
    if require_clean and status:
        raise BuildTransactionFailure("release-capable build requires a clean checkout")
    return revision


def build_image(
    *,
    source_root: Path,
    image: str,
    platform: str,
    purpose: str,
    publication_receipt: Path | None,
    evidence_dir: Path,
    require_clean: bool = True,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    evidence_dir = external_output_path(evidence_dir, source_root=source_root, role="build evidence")
    if evidence_dir.exists():
        raise BuildTransactionFailure("build evidence destination already exists")
    platform_contract(platform)
    require_clean = clean_checkout_required(purpose=purpose, requested=require_clean)
    revision = _revision(source_root, require_clean)
    publication_status = publication_status_for_build(
        purpose=purpose, publication_receipt=publication_receipt, revision=revision
    )
    context_tree = _run(["git", "rev-parse", f"{revision}^{{tree}}"], cwd=source_root).stdout.strip()
    command = [
        "docker", "buildx", "build", "--load", "--progress=plain",
        "--platform", platform, "--file", "deploy/Dockerfile", "--tag", image,
        "--build-arg", f"VCS_REF={revision}",
        "--build-arg", f"PUBLICATION_STATUS={publication_status}",
    ]
    builder: str | None = None
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="armillary-build-") as raw:
        context = materialize_git_snapshot(source_root, revision, Path(raw) / "context")
        try:
            verify_context(context)
        except DockerContextFailure as error:
            raise BuildTransactionFailure(f"build context: {error}") from None
        if purpose == "release-candidate":
            builder = "armillary-release-" + secrets.token_hex(8)
            _run([
                "docker", "buildx", "create", "--name", builder,
                "--driver", "docker-container", "--driver-opt", f"image={BUILDKIT_IMAGE}",
            ], timeout=300)
        try:
            completed = _run(
                [*command, *(("--builder", builder, "--no-cache") if builder else ()), "."],
                cwd=context,
            )
        finally:
            if builder is not None and _run(
                ["docker", "buildx", "rm", "--force", builder], timeout=300, check=False
            ).returncode:
                raise BuildTransactionFailure(f"cannot remove isolated builder {builder}")
    try:
        inspection = json.loads(_run(["docker", "image", "inspect", image]).stdout)[0]
        image_id, labels = inspection["Id"], inspection["Config"]["Labels"] or {}
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise BuildTransactionFailure("cannot bind the build to the built image") from error
    if (
        not re.fullmatch(r"sha256:[0-9a-f]{64}", str(image_id))
        or labels.get("org.opencontainers.image.revision") != revision
        or labels.get("org.projectarmillary.publication.status") != publication_status
        or (inspection.get("Os"), inspection.get("Architecture")) != platform_contract(platform)
    ):
        raise BuildTransactionFailure("built image identity, labels or platform are not this build's")
    receipt = {
        "schema_version": "release-build-transaction-v3",
        "source_revision": revision,
        "context_git_tree": context_tree,
        "image": image,
        "image_id": image_id,
        "platform": platform,
        "purpose": purpose,
        "publication_status": publication_status,
        "builder_isolation": (
            "ephemeral_docker_container_builder_no_cache" if builder else "diagnostic_default_builder"
        ),
        "started_unix": started,
        "finished_unix": time.time(),
        "command": [*command, *(("--builder", "<ephemeral>", "--no-cache") if builder else ()), "."],
    }
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "build.stdout.txt").write_text(completed.stdout, encoding="utf-8")
    (evidence_dir / "build.stderr.txt").write_text(completed.stderr, encoding="utf-8")
    (evidence_dir / "build-transaction.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--image", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--purpose", choices=BUILD_PURPOSES, required=True)
    parser.add_argument("--publication-receipt", type=Path)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        receipt = build_image(
            source_root=args.source_root, image=args.image, platform=args.platform,
            purpose=args.purpose, publication_receipt=args.publication_receipt,
            evidence_dir=args.evidence_dir, require_clean=args.require_clean,
        )
    except (BuildTransactionFailure, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"RELEASE BUILD FAILED: {error}", file=sys.stderr)
        return 1
    print(
        "RELEASE BUILD COMPLETE "
        f"revision={receipt['source_revision']} purpose={receipt['purpose']} image={receipt['image_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
