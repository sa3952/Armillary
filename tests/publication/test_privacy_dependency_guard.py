"""The privacy dependency guard: no source or requirement may reach an outbound
or persistent sink the privacy policy does not name.  Published with the
source, so it uses no shared test fixture."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "verification" / "verify_privacy_dependencies.py"


@pytest.fixture
def guard():
    assert GUARD.is_file(), "privacy dependency guard must be repository-owned"
    spec = importlib.util.spec_from_file_location("verify_privacy_dependencies", GUARD)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("source", [
    # Static and dynamic forms of an import.
    "import sentry_sdk\n", "from sentry_sdk import init\n",
    'import importlib\nimportlib.import_module("sentry_sdk")\n',
    'import importlib.metadata\nimportlib.import_module("sentry_sdk")\n',
    'import importlib as loader\nloader.import_module("sen" + "try_sdk")\n',
    'import importlib\ngetattr(importlib, "import_module")("sentry_sdk")\n',
    'from importlib import import_module as load\nload("http" + "x")\n', '__import__("httpx")\n',
    # Standard-library and third-party outbound or persistent sinks.
    "from urllib.request import urlopen\n", "from urllib import request\n", "import http.client\n",
    "from http import client\n", "import smtplib\n", "import ftplib\n", "import socket\n",
    "import logging.handlers\n", "from logging import handlers\n", "import boto3\n", "import dbm\n",
    "import posthog\n", "import psycopg2\n", "import pymongo\n",
    # sqlite3 outside the one reviewed module, even under that module's file name.
    "import sqlite3\n",
])
def test_the_guard_rejects_sink_imports_in_every_form(tmp_path, guard, source):
    (tmp_path / "place_catalog.py").write_text(source, encoding="utf-8")
    with pytest.raises(guard.PrivacyDependencyFailure):
        guard.check_python_source(tmp_path / "place_catalog.py")


def test_the_guard_keeps_the_stdlib_siblings_and_the_reviewed_sqlite_module(tmp_path, guard):
    (tmp_path / "candidate.py").write_text(
        "import json\nfrom pathlib import Path\nfrom urllib.parse import urlsplit\n"
        "from http import HTTPStatus\nimport logging\n", encoding="utf-8")
    guard.check_python_source(tmp_path / "candidate.py")
    guard.check_python_source(ROOT / "backend/app/core/place_catalog.py")


@pytest.mark.parametrize(("files", "refusal"), [
    ({"requirements.txt": "fastapi==0.139.2\nsentry-sdk==2.0.0\n"}, "privacy-sensitive"),
    *(({"requirements.txt": requirement}, None) for requirement in (
        "opentelemetry-api==1.40.0\n", "opentelemetry-sdk==1.40.0\n",
        "opentelemetry-instrumentation-fastapi==0.61b0\n", "datadog-api-client==2.0.0\n",
        "boto3==1.42.76\n", "posthog==7.11.0\n", "psycopg2-binary==2.9.11\n", "pymongo==4.16.0\n",
        "file:///tmp/unreviewed.whl\n")),
    ({"requirements.txt": "-r nested.txt\n", "nested.txt": "sentry-sdk==2.0.0\n"}, "privacy-sensitive"),
    ({"requirements.txt": "ordinary-package @ https://example.invalid/package.whl\n"}, "direct-URL"),
    ({"reviewed/requirements.txt": "-r ../outside.txt\n", "outside.txt": "fastapi==1\n"}, "escapes"),
    # The published-tree abort was a FileNotFoundError, not a refusal.
    ({"requirements.txt": "-r absent.txt\n"}, "cannot read"),
])
def test_the_guard_rejects_sink_distributions_urls_and_unsafe_includes(tmp_path, guard, files, refusal):
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text, encoding="utf-8")
    with pytest.raises(guard.PrivacyDependencyFailure, match=refusal):
        guard.check_requirements(tmp_path / next(iter(files)))


def test_the_guard_scans_the_requirement_files_it_discovers(tmp_path, guard):
    """The real set against the real tree, and a file nobody listed: a fixed
    list cannot satisfy this, the name is chosen at call time."""
    guard.check_repository()
    (tmp_path / "root").mkdir()
    (tmp_path / "root/unlisted-requirements.lock").write_text("sentry-sdk==2.0.0\n", encoding="utf-8")
    discovered = guard.discover_requirement_files((tmp_path / "root",))
    assert discovered == (tmp_path / "root/unlisted-requirements.lock",)
    with pytest.raises(guard.PrivacyDependencyFailure, match="privacy-sensitive"):
        guard.check_requirements(discovered[0])
    with pytest.raises(guard.PrivacyDependencyFailure, match="root is absent"):
        guard.discover_requirement_files((tmp_path / "absent",))
    (tmp_path / "empty").mkdir()
    with pytest.raises(guard.PrivacyDependencyFailure, match="no requirement file"):
        guard.discover_requirement_files((tmp_path / "empty",))


@pytest.mark.parametrize(("state", "program", "verdict"), [
    # A guard that scanned nothing has not passed anything.
    ("source-missing", None, "FAILED"),
    ("source-empty", "", "FAILED"),
    ("source-unparsable", "def broken(:\n", "FAILED"),
    # Controls: the refusal path and the pass path both still exist.
    ("known-sink-positive", "import requests\n", "FAILED"),
    ("benign-negative", "import math\n", "PASSED"),
])
def test_the_guard_cli_fails_closed_unless_it_scanned_a_source(tmp_path, state, program, verdict):
    """The real command on a copied tree: the guard's own file, no monkeypatch."""
    import subprocess
    import sys

    copied = tmp_path / "scripts" / "verification" / GUARD.name
    copied.parent.mkdir(parents=True)
    copied.write_bytes(GUARD.read_bytes())
    for root in ("backend", "deploy"):
        (tmp_path / root).mkdir()
        (tmp_path / root / "requirements.lock").write_text("fastapi==0.135.1\n", encoding="utf-8")
    if program is not None:
        (tmp_path / "backend" / "app").mkdir()
        if program:
            (tmp_path / "backend" / "app" / "consumer.py").write_text(program, encoding="utf-8")
    completed = subprocess.run([sys.executable, "-B", str(copied), "--check"], cwd=tmp_path,
                               capture_output=True, text=True, check=False, timeout=60)
    assert completed.returncode == (0 if verdict == "PASSED" else 1), completed
    assert f"PRIVACY DEPENDENCY CHECK {verdict}" in completed.stdout + completed.stderr
