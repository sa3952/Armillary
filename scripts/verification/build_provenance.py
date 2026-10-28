#!/usr/bin/env python3
"""The release image's build provenance: an in-toto Statement with a SLSA v1 predicate.

``build_release_image`` writes ``provenance.intoto.json`` beside its build
transaction.  The statement is unsigned: the image is built on Sebastian's
machine, not in a hosted builder that could sign for it, so the signature is
his, made with ``ssh-keygen -Y sign`` under the namespace ``SIGNING_NAMESPACE``
(the release runbook).  ``verify`` checks that a statement
names exactly the image and revision of a build transaction and, given a
signature, that it verifies against an allowed signers file under that
namespace.

The subject digest is the Docker image ID (the image configuration's SHA-256),
the identity Gate D, the host and ``/api/version`` already use; the image is not
pushed to a registry, so there is no manifest digest to name.
The build type is ``build_release_image``'s build transaction and the builder ID
names this module: the builder is Sebastian's machine running the public
revision's ``build_release_image``, a self-hosted builder, so the provenance is
exactly as trustworthy as its signer.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

STATEMENT_TYPE = "https://in-toto.io/Statement/v1"
PREDICATE_TYPE = "https://slsa.dev/provenance/v1"
BUILD_TYPE = "https://github.com/sa3952/Armillary/blob/main/scripts/verification/build_release_image.py"
SOURCE_URI = "git+https://github.com/sa3952/Armillary"
BUILDER_ID = "https://github.com/sa3952/Armillary/blob/main/scripts/verification/build_provenance.py"
SIGNING_NAMESPACE = "armillary-provenance"
PROVENANCE_NAME = "provenance.intoto.json"
_IMAGE_ID = re.compile(r"sha256:([0-9a-f]{64})")
_REVISION = re.compile(r"[0-9a-f]{40}")


class ProvenanceRefusal(ValueError):
    pass


def _timestamp(unix: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(unix, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def statement(transaction: dict[str, Any]) -> dict[str, Any]:
    """The provenance of one build transaction (build_release_image's receipt)."""
    image = _IMAGE_ID.fullmatch(str(transaction.get("image_id")))
    revision = str(transaction.get("source_revision"))
    if image is None or _REVISION.fullmatch(revision) is None:
        raise ProvenanceRefusal("the build transaction names no image ID or source revision")
    return {
        "_type": STATEMENT_TYPE,
        "subject": [{"name": str(transaction["image"]), "digest": {"sha256": image.group(1)}}],
        "predicateType": PREDICATE_TYPE,
        "predicate": {
            "buildDefinition": {
                "buildType": BUILD_TYPE,
                "externalParameters": {
                    "source": {"uri": f"{SOURCE_URI}@{revision}", "digest": {"gitCommit": revision}},
                    "platform": transaction["platform"], "purpose": transaction["purpose"],
                    "publicationStatus": transaction["publication_status"],
                },
                "internalParameters": {
                    "contextGitTree": transaction["context_git_tree"],
                    "builderIsolation": transaction["builder_isolation"],
                    "command": transaction["command"],
                },
                "resolvedDependencies": [
                    {"uri": f"{SOURCE_URI}@{revision}", "digest": {"gitCommit": revision}},
                    *({"name": f"wheelhouse/{name}", "digest": {"sha256": digest}}
                      for name, digest in sorted(transaction["wheelhouse_sha256"].items())),
                ],
            },
            "runDetails": {
                "builder": {"id": BUILDER_ID},
                "metadata": {"startedOn": _timestamp(transaction["started_unix"]),
                             "finishedOn": _timestamp(transaction["finished_unix"])},
            },
        },
    }


def write(evidence_dir: Path, transaction: dict[str, Any]) -> Path:
    path = evidence_dir / PROVENANCE_NAME
    path.write_text(json.dumps(statement(transaction), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_statement(provenance: dict[str, Any], transaction: dict[str, Any], image_id: str | None = None) -> None:
    """The statement must be exactly the one this transaction yields, and name `image_id` when one is given."""
    if provenance != statement(transaction):
        raise ProvenanceRefusal("the provenance is not the statement of this build transaction")
    if image_id is not None and transaction["image_id"] != image_id:
        raise ProvenanceRefusal(f"the provenance names {transaction['image_id']}, not {image_id}")


def verify_signature(provenance_path: Path, signature: Path, allowed_signers: Path, identity: str) -> None:
    """`ssh-keygen -Y verify` under the provenance namespace; any failure refuses."""
    with provenance_path.open("rb") as message:
        completed = subprocess.run(
            ["/usr/bin/ssh-keygen", "-Y", "verify", "-f", str(allowed_signers), "-I", identity,
             "-n", SIGNING_NAMESPACE, "-s", str(signature)],
            stdin=message, capture_output=True, check=False)
    if completed.returncode != 0:
        raise ProvenanceRefusal("the provenance signature does not verify: "
                                + completed.stderr.decode(errors="replace").strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--build-evidence-dir", type=Path, required=True,
                        help="build_release_image's evidence directory")
    parser.add_argument("--image", help="the image ID the provenance must name")
    parser.add_argument("--signature", type=Path, help="the ssh-keygen signature of the provenance file")
    parser.add_argument("--allowed-signers", type=Path)
    parser.add_argument("--identity", help="the signer identity in the allowed signers file")
    args = parser.parse_args()
    try:
        transaction = json.loads((args.build_evidence_dir / "build-transaction.json").read_text(encoding="utf-8"))
        provenance_path = args.build_evidence_dir / PROVENANCE_NAME
        verify_statement(json.loads(provenance_path.read_text(encoding="utf-8")), transaction, args.image)
        if args.signature is not None:
            if args.allowed_signers is None or args.identity is None:
                raise ProvenanceRefusal("--signature needs --allowed-signers and --identity")
            verify_signature(provenance_path, args.signature, args.allowed_signers, args.identity)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"PROVENANCE REFUSED: {error}") from None
    # Without a signature only the statement matched the build; say so instead of VERIFIED.
    verdict = "VERIFIED" if args.signature else "MATCHED (UNSIGNED)"
    print(f"PROVENANCE {verdict} image={transaction['image_id']} revision={transaction['source_revision']}")


if __name__ == "__main__": main()
