#!/usr/bin/env python3
"""The release identity a signed release tag carries, and its check.

The frontend release record (``releases/<version>/frontend-release.json``) and
the GitHub Release live where the source lives: whoever can replace one can
replace the other.  The release tag is signed with the release key, which is
not on GitHub, so a tag message naming the same digests is a second record a
reader can check without trusting the repository's content:

    Armillary-Release: <version>
    Armillary-Public-Revision: <40-hex public source revision>
    Armillary-Frontend-Artifact-Digest: sha256:<64 hex>
    Armillary-Backend-Image: sha256:<64 hex>

``render`` writes that message from the frontend release record and the image
ID for ``git tag -s VER -F <file> PUBREV``; Gate F parses every tag on the
released revision and refuses one whose revision or frontend digest differs
from the record it rebuilt.  The backend image ID is not rebuilt from public
material; a reader compares it with ``/api/version`` and the calculation
receipt.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

FIELDS = {
    "Armillary-Release": re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"),
    "Armillary-Public-Revision": re.compile(r"[0-9a-f]{40}"),
    "Armillary-Frontend-Artifact-Digest": re.compile(r"sha256:[0-9a-f]{64}"),
    "Armillary-Backend-Image": re.compile(r"sha256:[0-9a-f]{64}"),
}
_SIGNATURE_START = "-----BEGIN "


class IdentityRefusal(ValueError):
    pass


def _record_identity(record: dict) -> tuple[str, str]:
    try:
        revision = record["source_publication"]["public_source_revision"]
        digest = record["artifact_digest"]
    except (KeyError, TypeError):
        raise IdentityRefusal("the frontend release record names no public revision or artifact digest") from None
    return revision, digest


def render(record: dict, *, version: str, image_id: str) -> str:
    revision, digest = _record_identity(record)
    values = {"Armillary-Release": version, "Armillary-Public-Revision": revision,
              "Armillary-Frontend-Artifact-Digest": digest, "Armillary-Backend-Image": image_id}
    for name, value in values.items():
        if not isinstance(value, str) or FIELDS[name].fullmatch(value) is None:
            raise IdentityRefusal(f"{name} {value!r} is not well formed")
    return f"Armillary {version}\n\n" + "".join(f"{name}: {values[name]}\n" for name in FIELDS)


def parse(message: str) -> dict[str, str]:
    """The identity lines of a tag message (signature block excluded); each field exactly once and well formed."""
    found: dict[str, list[str]] = {name: [] for name in FIELDS}
    for line in message.splitlines():
        if line.startswith(_SIGNATURE_START):
            break
        name, separator, value = line.partition(": ")
        if separator and name in found:
            found[name].append(value)
    identity = {}
    for name, values in found.items():
        if len(values) != 1 or FIELDS[name].fullmatch(values[0]) is None:
            raise IdentityRefusal(f"the tag message must name {name} exactly once, well formed "
                                  f"(found {len(values)})")
        identity[name] = values[0]
    return identity


def check(message: str, record: dict, *, version: str | None = None) -> dict[str, str]:
    """The tag's identity, refused unless it names the record's revision and frontend digest (and `version`)."""
    identity = parse(message)
    revision, digest = _record_identity(record)
    if identity["Armillary-Public-Revision"] != revision:
        raise IdentityRefusal(f"the tag names the revision {identity['Armillary-Public-Revision']}, "
                              f"the frontend release record {revision}")
    if identity["Armillary-Frontend-Artifact-Digest"] != digest:
        raise IdentityRefusal(f"the tag names the frontend digest {identity['Armillary-Frontend-Artifact-Digest']}, "
                              f"the frontend release record {digest}")
    if version is not None and identity["Armillary-Release"] != version:
        raise IdentityRefusal(f"the tag {version} names the release {identity['Armillary-Release']}")
    return identity


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    rendering = commands.add_parser("render", help="print the release tag message")
    rendering.add_argument("--frontend-release-record", type=Path, required=True)
    rendering.add_argument("--version", required=True)
    rendering.add_argument("--image", required=True, help="the release image ID (sha256:...)")
    rendering.add_argument("--output", type=Path, help="the message file for `git tag -F`; stdout when absent")
    checking = commands.add_parser("check", help="check a tag message (stdin) against a frontend release record")
    checking.add_argument("--frontend-release-record", type=Path, required=True)
    checking.add_argument("--version")
    args = parser.parse_args()
    try:
        record = json.loads(args.frontend_release_record.read_text(encoding="utf-8"))
        if args.command == "render":
            message = render(record, version=args.version, image_id=args.image)
            if args.output is None:
                sys.stdout.write(message)
            else:
                args.output.write_text(message, encoding="utf-8")
        else:
            identity = check(sys.stdin.read(), record, version=args.version)
            print("RELEASE IDENTITY MATCHES " + " ".join(f"{k}={v}" for k, v in identity.items()))
    except (OSError, ValueError) as error:
        raise SystemExit(f"RELEASE IDENTITY REFUSED: {error}") from None


if __name__ == "__main__": main()
