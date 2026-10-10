#!/usr/bin/env python3
"""Check the `.dockerignore` whitelist against what the image is built from.

`.dockerignore` denies everything (`**`), reopens exact files or `dir/**`
trees, then re-denies sensitive names.  Every reopened path must be used by a
Dockerfile COPY (or be the Dockerfile, the notices file or the ignore file
itself), every COPY source must be reopened, deploy/image-app-tree.json must be
exactly the `/app` tree those COPY lines build from the admitted context (so a
file added to or removed from a copied tree fails here, not first in Gate D),
and no secret or private-looking path may survive the final deny rules.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from pathlib import Path, PurePosixPath


PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Read by the build without COPY: the build file itself, the ignore file, and
# the notices installed through a read-only bind mount (either location).
UNCOPIED_INPUTS = {
    ".dockerignore", "deploy/Dockerfile",
    "THIRD_PARTY_NOTICES.md", "publication/public_overlay/THIRD_PARTY_NOTICES.md",
}
UNCOPIED_APP_FILES = {"/app/THIRD_PARTY_NOTICES.md"}
MUST_STAY_DENIED = (
    ".env", ".git/config", "AGENTS.md", "docs/README.md", "tests/x.py",
    "backend/app/.env", "backend/app/x.pem", "backend/app/x.key",
    "backend/app/tests/test_x.py", "backend/app/__pycache__/x.pyc",
    "backend/app/secret_settings.py", "backend/place_data/README.md",
    "deploy/staging/nginx.conf", "frontend/zh-TW/index.html",
)


class DockerContextFailure(RuntimeError):
    pass


def _regex(pattern: str) -> re.Pattern[str]:
    rendered = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*\*", ".*")
    rendered = rendered.replace(r"\*", "[^/]*").replace(r"\?", "[^/]")
    rendered = re.sub(r"\\\[(.*?)\\\]", lambda m: "[" + m.group(1).replace("\\", "") + "]", rendered)
    # A rule that matches a directory also covers everything below it.
    return re.compile(rendered + "(?:/.*)?")


def ignore_rules(text: str) -> list[tuple[bool, str]]:
    """(reopen, pattern) in file order; the last matching rule wins."""

    rules = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            # Docker cleans each pattern: a leading or trailing slash names the same path.
            rules.append((line.startswith("!"), line.lstrip("!").strip().strip("/")))
    return rules


def admitted(rules: list[tuple[bool, str]], path: str) -> bool:
    # As in Docker, a path no rule matches is sent; verify() requires `**` first.
    result = True
    for reopen, pattern in rules:
        if _regex(pattern).fullmatch(path):
            result = reopen
    return result


def dockerfile_logical_lines(dockerfile: str) -> list[str]:
    """Join backslash continuations and drop comments, as Docker's parser does."""

    lines, continued = [], ""
    for raw in dockerfile.splitlines():
        line = raw.strip()
        if not line or (line.startswith("#") and not continued):
            continue
        continued += (" " if continued else "") + line
        if continued.endswith("\\"):
            continued = continued[:-1].rstrip()
            continue
        lines.append(continued)
        continued = ""
    if continued:
        raise DockerContextFailure("unterminated Dockerfile line continuation")
    return lines


def dockerfile_copies(dockerfile: str) -> list[tuple[str, str]]:
    """(source, destination) of every COPY/ADD from the build context."""

    copies = []
    for line in dockerfile_logical_lines(dockerfile):
        words = shlex.split(line)
        if words[0].upper() not in {"COPY", "ADD"} or any(w.startswith("--from") for w in words):
            continue
        arguments = [word for word in words[1:] if not word.startswith("--")]
        copies += [(source, arguments[-1]) for source in arguments[:-1]]
    return copies


def app_tree(root: Path, rules: list[tuple[bool, str]], copies: list[tuple[str, str]]) -> set[str]:
    """Every /app path (files and their directories) the COPY lines produce."""
    paths = set(UNCOPIED_APP_FILES)
    for source, destination in copies:
        if not destination.startswith("/app/"):
            continue
        tree = root / source
        if tree.is_dir():
            paths |= {
                destination.rstrip("/") + "/" + path.relative_to(tree).as_posix()
                for path in tree.rglob("*")
                if path.is_file() and admitted(rules, (Path(source) / path.relative_to(tree)).as_posix())
            }
        elif tree.is_file():
            paths.add(destination)
    for path in list(paths):
        parent = PurePosixPath(path).parent
        while parent != PurePosixPath("/app"):
            paths.add(str(parent))
            parent = parent.parent
    return paths


def verify(root: Path = PROJECT_ROOT) -> dict[str, int]:
    rules = ignore_rules((root / ".dockerignore").read_text(encoding="utf-8"))
    if not rules or rules[0] != (False, "**"):
        raise DockerContextFailure(".dockerignore must start by denying everything (**)")
    reopened = {pattern for reopen, pattern in rules if reopen}
    copies = dockerfile_copies((root / "deploy/Dockerfile").read_text(encoding="utf-8"))
    # Nothing reopened, copied or listed would make every check below vacuous.
    if not reopened:
        raise DockerContextFailure(".dockerignore reopens nothing")
    if not copies:
        raise DockerContextFailure("deploy/Dockerfile copies nothing from the build context")
    problems = []
    for source, _ in copies:
        probe = source + "/probe" if (root / source).is_dir() else source
        if not admitted(rules, probe) or not (root / source).exists():
            problems.append(f"COPY source not admitted or absent: {source}")
    used = {source for source, _ in copies} | UNCOPIED_INPUTS
    for pattern in sorted(reopened):
        if pattern.removesuffix("/**") not in used:
            problems.append(f"reopened but never read by the build: {pattern}")
    paths = json.loads((root / "deploy/image-app-tree.json").read_text(encoding="utf-8"))["paths"]
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise DockerContextFailure("deploy/image-app-tree.json paths is not a list of paths")
    listed = set(paths)
    built = app_tree(root, rules, copies)
    if not built - UNCOPIED_APP_FILES - {str(PurePosixPath(path).parent) for path in built}:
        problems.append("the Dockerfile copies no file into /app")
    if listed != built:
        problems.append(
            "deploy/image-app-tree.json is not the /app tree the Dockerfile copies: "
            f"unlisted={sorted(built - listed)}, not_built={sorted(listed - built)}"
        )
    leaked = [path for path in MUST_STAY_DENIED if admitted(rules, path)]
    if leaked:
        problems.append(f"sensitive paths would enter the build context: {leaked}")
    if problems:
        raise DockerContextFailure("; ".join(problems))
    return {"reopened": len(reopened), "copies": len(copies), "app_tree_entries": len(listed)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--check", action="store_true", required=True)
    args = parser.parse_args()
    try:
        receipt = verify(args.root.resolve())
    except (DockerContextFailure, OSError, ValueError, KeyError) as error:
        print(f"DOCKER CONTEXT FAILED: {error}", file=sys.stderr)
        return 1
    print("DOCKER CONTEXT VERIFIED " + " ".join(f"{k}={v}" for k, v in receipt.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
