"""Small fail-closed file helpers for privileged staging transactions."""

from __future__ import annotations

import os
import ipaddress
import json
from pathlib import Path
import re
import stat
import tempfile


def safe_absolute_path(path: Path, *, role: str = "staging") -> Path:
    absolute = Path(os.path.abspath(path))
    if any(candidate.is_symlink() for candidate in (absolute, *absolute.parents)):
        raise ValueError(f"{role} path contains a symlink")
    return absolute


def require_trusted_parent(path: Path, *, role: str) -> None:
    """Require a parent in which only the current operator can replace names."""

    parent = path.parent
    metadata = parent.stat()
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o022
    ):
        raise ValueError(
            f"{role} parent must be operator-owned and not group/world writable"
        )


# Privileged commands run `sudo python3 -m scripts...` and
# the host installer under `sudo bash` from a checkout.  Root then
# reads from it: the Python it imports (scripts/, and backend/app/ through
# backend/, which goes first on sys.path), and the deploy/ files it hands to
# Docker Compose (the compose files and their project directory's .env),
# renders (NGINX and Certbot templates), installs into /etc (the host configuration files,
# nginx.conf) or reads as input (the frontend contract, the synthetic chart).
# tests/deployment/test_privileged_checkout.py observes that set.  These trees
# must be root-owned, not group/world writable, without symlinks; so must the
# checkout directory, every directory above it and the directories below that
# hold a tree, since a writer of any of them could swap what was checked.
PRIVILEGED_CODE_TREES = ("scripts", "backend/app", "deploy")
PRIVILEGED_DIRECTORIES = ("backend",)


def require_root_owned_tree(root: Path, *, expected_uid: int = 0, recursive: bool = True,
                            owners: frozenset[int] | None = None) -> None:
    allowed = frozenset({expected_uid}) if owners is None else owners

    def check(path: Path) -> os.stat_result:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError(f"privileged code path contains a symlink: {path}")
        if metadata.st_uid not in allowed or stat.S_IMODE(metadata.st_mode) & 0o022:
            raise ValueError(
                f"privileged code path must be owned by uid {expected_uid} and not "
                f"group/world writable: {path}"
            )
        return metadata

    if not stat.S_ISDIR(check(root).st_mode):
        raise ValueError(f"privileged code root is not a directory: {root}")
    if not recursive:
        return
    def unlisted(error: OSError) -> None:
        raise ValueError(f"privileged code tree cannot be listed: {error.filename}") from error

    for directory, subdirectories, files in os.walk(root, followlinks=False, onerror=unlisted):
        for name in [*subdirectories, *files]:
            check(Path(directory, name))


def require_privileged_checkout(checkout: Path, *, expected_uid: int = 0) -> None:
    checkout = Path(os.path.abspath(checkout))
    # Above the checkout root may also own a directory (/, /var, ...).
    for ancestor in reversed(checkout.parents):
        require_root_owned_tree(ancestor, expected_uid=expected_uid, recursive=False,
                                owners=frozenset({0, expected_uid}))
    require_root_owned_tree(checkout, expected_uid=expected_uid, recursive=False)
    for relative in PRIVILEGED_DIRECTORIES:
        directory = checkout / relative
        if directory.exists() or directory.is_symlink():
            require_root_owned_tree(directory, expected_uid=expected_uid, recursive=False)
    for relative in PRIVILEGED_CODE_TREES:
        tree = checkout / relative
        if tree.exists() or tree.is_symlink():
            require_root_owned_tree(tree, expected_uid=expected_uid)


def read_owner_only(
    path: Path,
    *,
    role: str,
    maximum_bytes: int,
    minimum_bytes: int = 1,
) -> bytes:
    path = safe_absolute_path(path, role=role)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ValueError(f"{role} must be an owner-only regular file") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or not minimum_bytes <= metadata.st_size <= maximum_bytes
        ):
            raise ValueError(f"{role} ownership, mode, or size is unsafe")
        payload = os.read(descriptor, maximum_bytes + 1)
        if len(payload) > maximum_bytes:
            raise ValueError(f"{role} exceeds its bounded size")
        return payload
    finally:
        os.close(descriptor)


_DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def validate_server_name(value: str) -> str:
    """Return one canonical FQDN and reject IP literals or DNS-invalid labels."""

    value = value.rstrip(".").lower()
    try:
        ipaddress.ip_address(value)
    except ValueError:
        pass
    else:
        raise ValueError("server name must be a fully qualified DNS name")
    if len(value) > 253 or len(value.split(".")) < 2:
        raise ValueError("server name must be a fully qualified DNS name")
    if not all(_DOMAIN_LABEL.fullmatch(label) for label in value.split(".")):
        raise ValueError("server name contains invalid DNS syntax")
    return value


def deployment_hostnames(value: str) -> tuple[str, str]:
    """Return the one apex/www set shared by ACME and NGINX producers."""

    apex = validate_server_name(value)
    return apex, validate_server_name(f"www.{apex}")


def atomic_owner_only_replace(path: Path, payload: bytes, *, role: str) -> None:
    path = safe_absolute_path(path, role=role)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # The rename lives in the directory: without this a power loss can
        # bring back the old file (or none) although the call returned.
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | os.O_CLOEXEC)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def write_owner_only_new(path: Path, payload: bytes) -> None:
    """Create one new owner-only regular file without a permissive interval."""
    write_new_file(path, payload, mode=0o600)


def write_new_file(path: Path, payload: bytes, *, mode: int) -> None:
    """Create one new regular file with exactly `mode` and write it through the
    descriptor that created it: no name is opened twice, none is followed."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def emit_json_receipt(receipt: dict, output: Path | None) -> None:
    payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    if output is None:
        print(payload.decode(), end="")
    else:
        target = safe_absolute_path(output, role="receipt")
        if target.exists():
            raise SystemExit(f"refusing to overwrite receipt: {target}")
        write_owner_only_new(target, payload)
    if receipt.get("result") != "pass":
        raise SystemExit(1)


# --- privileged environment --------------------------------------------------
# A privileged action keeps only these inherited variables.  Anything
# else is routing or loader input the operator's shell happened to carry:
# DOCKER_HOST/DOCKER_CONTEXT/DOCKER_CONFIG and BUILDKIT_HOST choose which daemon
# the root actions talk to, COMPOSE_* changes the model compose deploys, proxy
# variables reroute the live probes, PYTHON*/LD_*/DYLD_* change what code runs.
# STAGING_SERVER_NAME is the one deployment input read from the environment.
PRIVILEGED_ENVIRONMENT_ALLOWLIST = frozenset({
    "HOME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "LC_MESSAGES", "LOGNAME",
    "TERM", "TZ", "USER", "SUDO_USER", "SUDO_UID", "SUDO_GID", "STAGING_SERVER_NAME",
})
PRIVILEGED_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"


def privileged_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    """The closed environment a privileged action and its children run with."""
    inherited = os.environ if source is None else source
    return {
        **{name: value for name, value in inherited.items()
           if name in PRIVILEGED_ENVIRONMENT_ALLOWLIST},
        "PATH": PRIVILEGED_PATH,
    }


def sanitize_privileged_environment() -> None:
    """Replace this process's environment with the closed privileged set."""
    closed = privileged_environment()
    os.environ.clear()
    os.environ.update(closed)


def main(arguments: list[str]) -> None:
    """host_install.sh's guard: the check every Python root entry runs."""
    if len(arguments) != 2 or arguments[0] != "require-privileged-checkout":
        raise SystemExit("usage: staging_secure_io.py require-privileged-checkout CHECKOUT")
    try:
        require_privileged_checkout(Path(arguments[1]))
    except (OSError, ValueError) as error:
        raise SystemExit(f"checkout must be root-owned and not group/world writable: {error}") from None


if __name__ == "__main__":
    import sys

    main(sys.argv[1:])
