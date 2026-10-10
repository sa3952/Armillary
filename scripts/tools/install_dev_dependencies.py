#!/usr/bin/env python3
"""Install backend/requirements-dev.lock without running unhashed code.

pyswisseph publishes only an sdist for Python 3.14, so pip builds it.  With
build isolation pip would fetch its build backend (setuptools, wheel) outside
`--require-hashes`.  So, as the image build does (deploy/Dockerfile), this
installs exactly the setuptools and wheel entries of the hashed
deploy/build-requirements.lock first, then the development lock with
`--no-build-isolation`.  pip's configuration files and index variables are
not read, and nothing comes from or goes to pip's cache.

Whether the built extension links the host's libsqlite3 or compiles in
Swephelp's bundled SQLite depends on the build host (pkg-config and the
SQLite headers); `--require-system-sqlite` (Linux) then requires the system
linkage, as the image build does.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
BUILD_LOCK = ROOT / "deploy/build-requirements.lock"
DEVELOPMENT_LOCK = ROOT / "backend/requirements-dev.lock"
PYSWISSEPH_SDIST = ROOT / "third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz"
# Run by the interpreter just installed into, from the checkout root.
LINKAGE_PROBE = (
    "import sys, swisseph\n"
    "from pathlib import Path\n"
    "from scripts.publication.verify_image_supply_chain import pyswisseph_sqlite_linkage\n"
    "print(pyswisseph_sqlite_linkage(Path(swisseph.__file__).read_bytes(), Path(sys.argv[1])))\n"
)
BUILD_BACKEND = ("setuptools", "wheel")
# Variables that would point pip at another index, extra links or a config file.
PIP_SOURCE_VARIABLES = ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PIP_FIND_LINKS", "PIP_TRUSTED_HOST",
                        "PIP_CONSTRAINT", "PIP_REQUIREMENT")


def backend_subset(lock_text: str) -> str:
    """The setuptools and wheel entries of the build lock, hashes kept, comments dropped."""
    blocks = re.findall(r"^((?:setuptools|wheel)==[^\n]*(?:\n[ \t]+[^\n]*)*)", lock_text, flags=re.M)
    if sorted(block.split("==")[0] for block in blocks) != sorted(BUILD_BACKEND):
        raise ValueError("the build lock does not pin exactly setuptools and wheel once each")
    return "\n".join(re.sub(r"\n[ \t]+#.*", "", block) for block in blocks) + "\n"


def pip_environment() -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items()
                   if name not in PIP_SOURCE_VARIABLES}
    environment["PIP_CONFIG_FILE"] = os.devnull
    return environment


def require_system_sqlite(environment: dict[str, str]) -> int:
    probe = subprocess.run([sys.executable, "-c", LINKAGE_PROBE, str(PYSWISSEPH_SDIST)], cwd=ROOT,
                           env=environment, capture_output=True, text=True, check=False)
    linkage = probe.stdout.strip()
    if probe.returncode != 0 or linkage != "system":
        print(f"pyswisseph's SQLite linkage is {linkage or 'unknown'}, not the system library: "
              + probe.stderr.strip()[-1000:], file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-system-sqlite", action="store_true",
                        help="after installing, require pyswisseph to link the system libsqlite3 (Linux)")
    arguments = parser.parse_args(argv)
    pip = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir",
           "--require-hashes"]
    environment = pip_environment()
    with tempfile.TemporaryDirectory(prefix="armillary-build-backend-") as directory:
        subset = Path(directory) / "build-backend.lock"
        subset.write_text(backend_subset(BUILD_LOCK.read_text(encoding="utf-8")), encoding="utf-8")
        backend = subprocess.run([*pip, "--no-deps", "-r", str(subset)], env=environment, check=False)
        if backend.returncode != 0:
            return backend.returncode
    installed = subprocess.run([*pip, "--no-build-isolation", "-r", str(DEVELOPMENT_LOCK)],
                               env=environment, check=False).returncode
    if installed != 0 or not arguments.require_system_sqlite:
        return installed
    return require_system_sqlite(environment)


if __name__ == "__main__":
    raise SystemExit(main())
