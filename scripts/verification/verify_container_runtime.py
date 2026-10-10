#!/usr/bin/env python3
"""Gate D runtime acceptance of one built production image.

Checked here: the image identity (non-root user, bounded healthcheck, pinned
base, platform, revision label, application environment); its `/app` tree
equals deploy/image-app-tree.json, no setuid file and no development or
secret path is present, and the installed Python distributions equal the
marker-evaluated runtime lock; one container started with compose's own
production settings (read-only root, all capabilities dropped,
no-new-privileges, resource limits) becomes healthy as non-root, refuses the
hidden endpoints and malformed bodies, answers a representative chart with
the image's own build identity, keeps the worst-options request inside its
time and byte budget, and logs no request data (privacy canary) and only the
closed telemetry schema.
"""

from __future__ import annotations

import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any
import uuid

from scripts.deployment.frontend_release import (
    build_release as build_frontend_release,
    combined_release_id,
)
from scripts.deployment.verify_staging_http import _request as _direct_request
from scripts.publication.verify_image_supply_chain import (
    AuditFailure,
    image_swisseph_extension,
    locked_runtime_versions,
    pyswisseph_sqlite_linkage,
)
from scripts.tools.output_confinement import external_output_path
from scripts.tools.source_tree_identity import materialize_git_snapshot
from scripts.verification.build_release_image import platform_args as _platform_args
from scripts.verification.build_release_image import platform_contract
from scripts.verification.verify_docker_context import (
    DockerContextFailure,
    dockerfile_logical_lines,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IMAGE = "armillary:runtime-test"
MACHINE_BY_DOCKER_ARCHITECTURE = {"amd64": "x86_64", "arm64": "aarch64"}


class GateFailure(RuntimeError):
    pass


def _privacy_event_fields() -> frozenset[str]:
    """Read the telemetry field set from its sole emitter."""

    source = PROJECT_ROOT / "backend" / "app" / "privacy_logging.py"
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError) as error:
        raise GateFailure(f"cannot read {source}: {error}") from error
    for node in tree.body:
        target, value = None, None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
        if target != "ALLOWED_EVENT_FIELDS" or value is None:
            continue
        try:
            fields = frozenset(ast.literal_eval(value))
        except (ValueError, TypeError) as error:
            raise GateFailure("ALLOWED_EVENT_FIELDS is not a literal this gate can read") from error
        if not fields or not all(isinstance(name, str) for name in fields):
            raise GateFailure("ALLOWED_EVENT_FIELDS is empty or not a set of names")
        return fields
    raise GateFailure(f"{source} declares no ALLOWED_EVENT_FIELDS")


EXPECTED_PRIVACY_EVENT_FIELDS = _privacy_event_fields()
# Why a known-bad distribution is bad; the closed comparison with the lock decides.
FORBIDDEN_PACKAGES = frozenset({
    "httpx", "httpx2", "httptools", "pip-audit", "pip-tools", "pip", "pytest",
    "python-dotenv", "pyyaml", "uvloop", "watchfiles", "websockets",
})
# 512 KiB bounds the default /api/chart response (projection=page), which is
# what the worst-options request receives.  The `detailed` view gets its own,
# wider documented budget; tests/backend/test_api_properties.py enforces it.
MAX_BENCHMARK_RESPONSE_BYTES = 512 * 1024
MAX_DETAILED_RESPONSE_BYTES = 768 * 1024
CHART_REQUESTS = PROJECT_ROOT / "frontend" / "tests" / "fixtures" / "chart-requests.json"
DOCKERFILE = PROJECT_ROOT / "deploy" / "Dockerfile"
APP_TREE_MANIFEST = PROJECT_ROOT / "deploy" / "image-app-tree.json"
EXPECTED_IMAGE_ENVIRONMENT = {
    "LANG": "C.UTF-8",
    "PYTHON_VERSION": "3.14.8",
    "CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE": "1",
    "PYTHONFAULTHANDLER": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}
# Keys the pinned python base declares that the application does not set
# (PATH is extended, PYTHON_VERSION and LANG are pinned above).  With the
# application's own keys this closes the image environment: a debug, proxy or
# secret variable added to the Dockerfile or base fails the gate.
BASE_IMAGE_ENVIRONMENT_KEYS = frozenset({"PATH", "PYTHON_SHA256"})
HIDDEN_RUNTIME_PATHS = ("/openapi.json", "/docs", "/api/runtime-health")
# Read-only introspection of candidate image code: no network, capability or
# more than a few processes.
_INSPECTION_SANDBOX = (
    "--network", "none", "--cap-drop", "ALL",
    "--security-opt", "no-new-privileges",
    "--pids-limit", "64", "--memory", "512m", "--memory-swap", "512m",
)
_DIGEST_PINNED_REFERENCE = re.compile(r"[^\s@$]+@sha256:[0-9a-f]{64}")


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    timeout: float = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command, cwd=cwd or PROJECT_ROOT, check=False, capture_output=True,
        text=True, timeout=timeout, env=env,
    )
    if check and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise GateFailure(
            f"command failed ({completed.returncode}): {' '.join(command[:4])}: {detail[-2000:]}"
        )
    return completed


def _platform_contract(platform: str) -> tuple[str, str]:
    try:
        return platform_contract(platform)
    except ValueError as error:
        raise GateFailure(str(error)) from error


def pinned_base_reference(dockerfile: Path | None = None) -> str:
    """The runtime base, read from the Dockerfile that must pin every stage.

    A builder stage compiles the extension the runtime stage copies, so every
    FROM and the `# syntax=` frontend are pinned by digest; an ARG-expanded
    reference cannot be checked and is refused.
    """

    dockerfile = dockerfile or DOCKERFILE
    try:
        text = dockerfile.read_text(encoding="utf-8")
        lines = dockerfile_logical_lines(text)
    except (OSError, DockerContextFailure) as error:
        raise GateFailure(f"cannot read {dockerfile}: {error}") from None
    syntax = re.match(r"\A(?:[ \t]*#[^\n]*\n)*?[ \t]*#[ \t]*syntax[ \t]*=[ \t]*(\S+)", text, re.IGNORECASE)
    if syntax is not None and not _DIGEST_PINNED_REFERENCE.fullmatch(syntax.group(1)):
        raise GateFailure(f"{dockerfile} syntax frontend {syntax.group(1)} is not pinned by digest")
    aliases: dict[str, str | None] = {}
    external: set[str] = set()
    final: str | None = None
    for line in lines:
        words = [word for word in line.split() if not word.startswith("--")]
        if not words or words[0].upper() != "FROM":
            continue
        if len(words) == 4 and words[2].upper() == "AS":
            reference, alias = words[1], words[3].casefold()
        elif len(words) == 2:
            reference, alias = words[1], None
        else:
            raise GateFailure(f"{dockerfile} has an unparsable FROM: {line}")
        if "$" in reference:
            raise GateFailure(f"{dockerfile} FROM {reference} is expanded from a build argument")
        if reference.casefold() in aliases:
            resolved = aliases[reference.casefold()]
        elif reference == "scratch":
            resolved = None
        elif _DIGEST_PINNED_REFERENCE.fullmatch(reference):
            external.add(reference)
            resolved = reference
        else:
            raise GateFailure(f"{dockerfile} FROM {reference} pins no base image by digest")
        if alias is not None:
            aliases[alias] = resolved
        final = resolved
    if len(external) != 1:
        raise GateFailure(f"{dockerfile} pins more than one base digest, or none: {sorted(external)}")
    if final is None:
        raise GateFailure(f"{dockerfile} runtime stage has no pinned base")
    return final


def _inspect_image(image: str, platform: str | None) -> dict[str, Any]:
    pinned_base_reference()
    image_info = json.loads(_run(["docker", "image", "inspect", image]).stdout)[0]
    config = image_info["Config"]
    if config["User"] != "10001:10001":
        raise GateFailure(f"unexpected image user: {config['User']!r}")
    pairs: dict[str, str] = {}
    for item in config.get("Env") or []:
        key, separator, value = str(item).partition("=")
        if not separator or key in pairs:
            raise GateFailure(f"image environment entry is invalid or repeated: {key}")
        pairs[key] = value
    labels = config.get("Labels") or {}
    revision = labels.get("org.opencontainers.image.revision")
    expected = {**EXPECTED_IMAGE_ENVIRONMENT, "CLASSICAL_ASTROLOGY_SOURCE_REVISION": revision}
    differing = sorted(key for key, value in expected.items() if pairs.get(key) != value)
    if differing or not pairs.get("PATH", "").startswith("/opt/venv/bin:"):
        raise GateFailure(f"image environment differs from the application contract: {differing}")
    unexpected = sorted(set(pairs) - set(expected) - BASE_IMAGE_ENVIRONMENT_KEYS)
    if unexpected:
        raise GateFailure(f"image environment has keys outside the application and base set: {unexpected}")
    if "container_healthcheck.py" not in " ".join((config.get("Healthcheck") or {}).get("Test") or []):
        raise GateFailure("image healthcheck does not use the bounded readiness probe")
    if platform and (image_info["Os"], image_info["Architecture"]) != _platform_contract(platform):
        raise GateFailure(
            f"image platform is {image_info['Os']}/{image_info['Architecture']}, not {platform}"
        )
    return {
        "id": image_info["Id"],
        "os": image_info["Os"],
        "architecture": image_info["Architecture"],
        "user": config["User"],
        "revision": revision,
    }


def _assert_safe_regular_mode(member: tarfile.TarInfo, normalized: str) -> None:
    if member.isfile() and member.mode & 0o6000:
        raise GateFailure(
            f"image regular file has setuid/setgid mode: {normalized} mode={member.mode:04o}"
        )


def _forbidden_image_path(normalized: str) -> bool:
    lowered = normalized.casefold()
    return (
        any(part in lowered for part in ("/.git/", "/.build/", "/backend/.venv/", "/tests/",
                                         "/docs/red_team/", "/docs/archive/", "/.env."))
        or lowered.endswith("/.ds_store")
        # The base image bundles pip as a wheel under ensurepip; uninstalling pip leaves it
        # importable from its path, and neither the package inventory nor the SBOM sees it.
        or "ensurepip" in lowered.split("/") or lowered.endswith(".whl")
        or lowered == "/app/frontend" or lowered.startswith("/app/frontend/")
        or normalized in {"/build", "/source", "/wheels", "/usr/bin/gcc", "/usr/bin/cc"}
        or (lowered.startswith("/app/") and lowered.endswith((".pem", ".key", "/.env")))
    )


def _inventory_image(image: str, platform: str | None) -> dict[str, Any]:
    inspection = _inspect_image(image, platform)
    architecture = str(inspection["architecture"])
    container = f"armillary-inventory-{uuid.uuid4().hex[:12]}"
    _run(["docker", "create", *_platform_args(platform), "--name", container, image])
    app_entries: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="armillary-inventory-") as raw:
            archive_path = Path(raw) / "rootfs.tar"
            _run(["docker", "export", "--output", str(archive_path), container], timeout=600)
            with tarfile.open(archive_path, mode="r") as archive:
                for member in archive:
                    normalized = "/" + member.name.lstrip("./")
                    _assert_safe_regular_mode(member, normalized)
                    if _forbidden_image_path(normalized):
                        raise GateFailure(f"forbidden path included in image: {normalized}")
                    if normalized.startswith("/app/"):
                        app_entries.append(normalized)
    finally:
        _run(["docker", "rm", "--force", container], check=False)
    expected_tree = sorted(json.loads(APP_TREE_MANIFEST.read_text(encoding="utf-8"))["paths"])
    if sorted(app_entries) != expected_tree:
        raise GateFailure(
            "image /app tree does not match deploy/image-app-tree.json: "
            f"unexpected={sorted(set(app_entries) - set(expected_tree))}, "
            f"missing={sorted(set(expected_tree) - set(app_entries))}"
        )
    runtime = json.loads(_run([
        "docker", "run", "--rm", *_platform_args(platform), *_INSPECTION_SANDBOX,
        "--entrypoint", "/opt/venv/bin/python", image, "-c",
        "import importlib.metadata,json,platform,re,zoneinfo;"
        "print(json.dumps({"
        "'packages':sorted({re.sub(r'[-_.]+','-',d.metadata['Name']).lower() "
        "for d in importlib.metadata.distributions()}),"
        "'python':platform.python_version(),'machine':platform.machine(),"
        "'pyswisseph':importlib.metadata.version('pyswisseph'),"
        "'timezones':sorted(zoneinfo.available_timezones())}))",
    ]).stdout.strip().splitlines()[-1])
    runtime["accepted_iana_zone_names"] = _assert_zone_names_are_the_images(
        runtime.pop("timezones", None) or []
    )
    packages = frozenset(runtime.pop("packages"))
    expected_packages = frozenset(
        locked_runtime_versions(PROJECT_ROOT / "deploy" / "requirements.lock", architecture)
    )
    if packages != expected_packages:
        unexpected = packages - expected_packages
        raise GateFailure(
            "production package inventory differs from the runtime lock: "
            f"missing={sorted(expected_packages - packages)}, unexpected={sorted(unexpected)}, "
            f"of which forbidden={sorted(FORBIDDEN_PACKAGES & unexpected)}"
        )
    if (
        runtime["python"] != "3.14.8"
        or runtime["pyswisseph"] != "2.10.3.2"
        or runtime.get("machine") != MACHINE_BY_DOCKER_ARCHITECTURE.get(architecture)
    ):
        raise GateFailure("runtime Python, pyswisseph, or machine mismatch")
    try:
        extension = image_swisseph_extension(image, (*_platform_args(platform), *_INSPECTION_SANDBOX))
    except AuditFailure as error:
        raise GateFailure(str(error)) from None
    runtime["pyswisseph_sqlite"] = _assert_system_sqlite(
        extension, PROJECT_ROOT / "third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz",
    )
    return {
        "app_tree_entries": len(app_entries),
        "production_packages": sorted(packages),
        "runtime": runtime,
    }


def _assert_zone_names_are_the_images(image_zones: list[str]) -> int:
    """The request schema accepts a committed list of IANA names (schemas.py).

    It must be this image's own zoneinfo.available_timezones() less the
    excluded placeholders, or a chart accepted by the list fails to resolve
    its zone in the image, or an image zone is refused for no reason.
    """
    pinned = json.loads(
        (PROJECT_ROOT / "backend" / "app" / "iana_zone_names.json").read_text(encoding="utf-8")
    )
    expected = set(pinned["names"]) | set(pinned["excluded_from_image"])
    actual = set(image_zones)
    if actual != expected or not pinned["names"]:
        raise GateFailure(
            "the image's zoneinfo.available_timezones() is not backend/app/iana_zone_names.json "
            f"plus its excluded names: in image only={sorted(actual - expected)}, "
            f"in list only={sorted(expected - actual)}"
        )
    return len(pinned["names"])


def _assert_system_sqlite(extension: bytes, sdist: Path) -> str:
    """deploy/Dockerfile builds pyswisseph against Debian's libsqlite3 (security
    updates); an extension that carries Swephelp's bundled amalgamation is refused."""
    try:
        linkage = pyswisseph_sqlite_linkage(extension, sdist)
    except AuditFailure as error:
        raise GateFailure(str(error)) from None
    if linkage != "system":
        raise GateFailure("the pyswisseph extension carries the bundled SQLite amalgamation, not Debian's libsqlite3")
    return linkage


def _request_fixture(name: str) -> dict[str, Any]:
    payload = json.loads(CHART_REQUESTS.read_text(encoding="utf-8")).get(name)
    if not isinstance(payload, dict):
        raise GateFailure(f"chart request fixture is unavailable: {name}")
    return payload


def _payloads() -> list[dict[str, Any]]:
    payload = _request_fixture("chart-exact.json")
    payload["computation_mode"] = {
        "zodiac": "sidereal", "center": "barycentric", "ayanamsa": "hipparchos",
    }
    payload["options"] = {"include_fixed_stars": True}
    return [payload]


def _worst_options_payload() -> dict[str, Any]:
    # Every module requested, at an exact minute.
    payload = _request_fixture("chart-approximate-hour.json")
    payload["birth_time_precision"] = "exact"
    payload["datetime"]["minute"] = 30
    payload["options"].update(
        declination_aspect_orb_degrees=0.5,
        aspect_angle_orb_degrees=2.0,
        bounds_profile="chaldaean_bounds_ptolemy_i_21_v1",
        decan_profile="chaldean_planetary_faces_firmicus_ii_4_v1",
        triplicity_profile="ptolemy_triplicity_textual_corulership_v1",
    )
    return payload


def _count_named_fields(value: object, name: str) -> int:
    if isinstance(value, dict):
        return int(name in value) + sum(_count_named_fields(item, name) for item in value.values())
    if isinstance(value, list):
        return sum(_count_named_fields(item, name) for item in value)
    return 0


def _timed_chart(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    started = time.monotonic()
    status, body, _ = _http(
        base_url, "/api/chart", body=json.dumps(payload, separators=(",", ":")).encode(),
        content_type="application/json",
    )
    elapsed = time.monotonic() - started
    if status != 200:
        raise GateFailure(f"worst-options request failed with HTTP {status}")
    if len(body) > MAX_BENCHMARK_RESPONSE_BYTES:
        raise GateFailure("worst-options response exceeded the release byte budget")
    return {
        "status": status, "elapsed_seconds": round(elapsed, 6), "response_bytes": len(body),
        "bisection_receipts": _count_named_fields(json.loads(body), "bisection_iterations"),
    }


def _cgroup_metrics(container: str) -> dict[str, int]:
    code = (
        "import json;from pathlib import Path;"
        "paths={'memory_current':'/sys/fs/cgroup/memory.current',"
        "'memory_peak':'/sys/fs/cgroup/memory.peak'};"
        "result={k:int(Path(v).read_text().strip()) for k,v in paths.items()};"
        "cpu=dict(line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines());"
        "result['cpu_usage_usec']=int(cpu['usage_usec']);"
        "print(json.dumps(result,sort_keys=True))"
    )
    output = _run(["docker", "exec", container, "/opt/venv/bin/python", "-c", code]).stdout
    try:
        metrics = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise GateFailure("container cgroup metrics are unreadable") from error
    if set(metrics) != {"memory_current", "memory_peak", "cpu_usage_usec"} or any(
        type(value) is not int or value < 0 for value in metrics.values()
    ):
        raise GateFailure("container cgroup metrics are invalid")
    return metrics


def _worst_options_observation(container: str, base_url: str) -> dict[str, Any]:
    """Time and memory of the heaviest legal request, sequential and concurrent."""

    payload = _worst_options_payload()
    before = _cgroup_metrics(container)
    sequential = [_timed_chart(base_url, payload) for _ in range(2)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(executor.map(lambda _: _timed_chart(base_url, payload), range(2)))
    after = _cgroup_metrics(container)
    return {
        "claim_boundary": "local exact-image observation; not a general SLA",
        "payload_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "sequential": sequential,
        "concurrent": concurrent,
        "resources": {
            "cpu_usage_usec_delta": max(0, after["cpu_usage_usec"] - before["cpu_usage_usec"]),
            "memory_current_before": before["memory_current"],
            "memory_current_after": after["memory_current"],
            "memory_peak_after": after["memory_peak"],
        },
        "response_byte_budget": MAX_BENCHMARK_RESPONSE_BYTES,
    }


def _http(
    base_url: str, path: str, *, body: bytes | None = None,
    content_type: str | None = None, timeout: float = 60,
) -> tuple[int, bytes, dict[str, str]]:
    try:
        status, payload, headers = _direct_request(
            f"{base_url}{path}", body=body, content_type=content_type,
            extra_headers={"Accept": "application/json", "Host": GATE_D_EXPECTED_HOST},
            timeout=timeout, maximum_bytes=MAX_BENCHMARK_RESPONSE_BYTES,
        )
    except (OSError, TimeoutError, ValueError) as error:
        raise GateFailure(f"HTTP request failed: {error.__class__.__name__}") from error
    if status == 0:
        raise GateFailure("HTTP request failed: endpoint unavailable")
    return status, payload, headers


def _chart(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    status, body, _ = _http(
        base_url, "/api/chart", body=json.dumps(payload, separators=(",", ":")).encode(),
        content_type="application/json",
    )
    if status != 200:
        raise GateFailure(f"container chart request failed with HTTP {status}")
    return json.loads(body)


def _host_port(container: str) -> int:
    output = _run(["docker", "port", container, "8000/tcp"]).stdout.strip()
    if not output:
        raise GateFailure("Docker did not publish the test-only localhost port")
    return int(output.rsplit(":", maxsplit=1)[1])


def _wait_healthy(container: str, timeout: float = 120) -> None:
    deadline, last_status = time.monotonic() + timeout, "unknown"
    while time.monotonic() < deadline:
        raw = _run([
            "docker", "inspect", "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}", container,
        ], check=False)
        if raw.returncode == 0:
            last_status = raw.stdout.strip()
            if last_status in ("healthy", "unhealthy"):
                break
        time.sleep(1)
    if last_status != "healthy":
        logs = _run(["docker", "logs", container], check=False).stdout[-2000:]
        raise GateFailure(f"container health was {last_status}: {logs}")


# The production run settings are read from compose itself (`docker compose
# config`) and translated.  A key compose declares that is neither translated
# nor a declared deviation is refused, so a new setting cannot go unexercised.
COMPOSE_SERVICE = "armillary-app"
COMPOSE_FILES = ("deploy/compose.yaml", "deploy/compose.frontend-release.yaml")
COMPOSE_TRANSLATED_KEYS = frozenset({
    "cap_add", "cap_drop", "cpus", "environment", "init", "logging",
    "mem_limit", "memswap_limit", "pids_limit", "read_only", "security_opt",
    "stop_grace_period", "tmpfs", "ulimits", "volumes",
})
COMPOSE_DECLARED_DEVIATIONS = {
    "image": "Gate D runs the image under test by the reference it was given; compose names "
             "the same image by its ID (checked)",
    "networks": "the internal network is replaced by one loopback-published port the host probes",
}
# Production logs to the host journal; a developer Docker daemon has no
# journald, so Gate D runs the local driver and reads the same stdout/stderr.
JOURNALD_LOG_DRIVER = "journald"
GATE_D_LOG_DRIVER = "local"
GATE_D_LOG_DEVIATION = "journald in production; Docker's local driver here, read through docker logs"
GATE_D_PROCESS_DEVIATION = "one uvicorn worker instead of the image's two"
# A reserved, unresolvable name: the application refuses any other Host, so
# every probe presents it, as the proxy does in production.
GATE_D_EXPECTED_HOST = "gate-d.invalid"
SINGLE_WORKER_COMMAND = (
    "/opt/venv/bin/python", "-m", "uvicorn", "app.main:create_app",
    "--factory", "--app-dir", "/app/backend", "--host", "0.0.0.0",
    "--port", "8000", "--workers", "1",
    "--loop", "asyncio", "--http", "h11", "--ws", "none",
    "--no-access-log", "--timeout-worker-healthcheck", "5",
    "--timeout-graceful-shutdown", "25", "--backlog", "32",
)


def _compose_environment(interpolation: dict[str, str]) -> dict[str, str]:
    """No ambient COMPOSE_* variable (env files, profiles, project dir) is inherited."""

    inherited = {
        key: value for key, value in os.environ.items()
        if not key.startswith("COMPOSE_") and key not in interpolation
    }
    return {**inherited, **interpolation}


def _compose_service_model(
    interpolation: dict[str, str], files: tuple[str, ...] = COMPOSE_FILES,
) -> dict[str, Any]:
    command = ["docker", "compose"]
    for relative in files:
        command += ["--file", str(PROJECT_ROOT / relative)]
    output = _run([*command, "config", "--format", "json"], env=_compose_environment(interpolation)).stdout
    try:
        service = json.loads(output)["services"][COMPOSE_SERVICE]
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise GateFailure("compose did not return the production service model") from error
    if not isinstance(service, dict):
        raise GateFailure("compose production service model is not an object")
    return service


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)(h|ms|m|s|us|ns)")
_DURATION_SECONDS = {"h": 3600, "m": 60, "s": 1, "ms": 1e-3, "us": 1e-6, "ns": 1e-9}


def _duration_seconds(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    parts = _DURATION_PART.findall(str(value))
    if not parts or "".join(number + unit for number, unit in parts) != str(value):
        raise GateFailure(f"compose duration is not understood: {value!r}")
    return int(sum(float(number) * _DURATION_SECONDS[unit] for number, unit in parts))


def _compose_run_arguments(service: dict[str, Any]) -> list[str]:
    """Translate the compose service model into `docker run` arguments."""

    # compose v5 emits keys the files never set as null: not a declaration.
    service = {key: value for key, value in service.items() if value is not None}
    unknown = sorted(set(service) - COMPOSE_TRANSLATED_KEYS - set(COMPOSE_DECLARED_DEVIATIONS))
    if unknown:
        raise GateFailure(
            f"compose declares runtime settings Gate D does not reproduce: {unknown}; "
            "translate them or declare the deviation"
        )
    arguments: list[str] = []
    for key, flag in (("init", "--init"), ("read_only", "--read-only")):
        if not isinstance(service.get(key, False), bool):
            raise GateFailure(f"compose {key} is not a boolean")
        arguments += [flag] if service.get(key) else []
    for key, flag in (
        ("tmpfs", "--tmpfs"), ("cap_drop", "--cap-drop"),
        ("cap_add", "--cap-add"), ("security_opt", "--security-opt"),
    ):
        values = service.get(key, [])
        values = [values] if isinstance(values, str) else values
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise GateFailure(f"compose {key} is not a list of strings")
        for value in values:
            arguments += [flag, value]
    for key, flag in (
        ("pids_limit", "--pids-limit"), ("mem_limit", "--memory"),
        ("memswap_limit", "--memory-swap"), ("cpus", "--cpus"),
    ):
        if key in service:
            if isinstance(service[key], bool) or not isinstance(service[key], (int, float, str)):
                raise GateFailure(f"compose {key} is not a scalar")
            arguments += [flag, str(service[key])]
    logging = service.get("logging")
    if logging is not None:
        if not isinstance(logging, dict) or set(logging) - {"driver", "options"}:
            raise GateFailure("compose logging is not understood")
        if logging.get("driver") == JOURNALD_LOG_DRIVER:
            if logging.get("options"):
                raise GateFailure("compose journald log options are not understood")
            arguments += ["--log-driver", GATE_D_LOG_DRIVER]
        else:
            arguments += ["--log-driver", str(logging["driver"])] if "driver" in logging else []
            for name, value in sorted((logging.get("options") or {}).items()):
                arguments += ["--log-opt", f"{name}={value}"]
    for name, limit in sorted((service.get("ulimits") or {}).items()):
        if isinstance(limit, dict) and set(limit) == {"soft", "hard"}:
            arguments += ["--ulimit", f"{name}={limit['soft']}:{limit['hard']}"]
        elif isinstance(limit, int) and not isinstance(limit, bool):
            arguments += ["--ulimit", f"{name}={limit}:{limit}"]
        else:
            raise GateFailure(f"compose ulimit is not understood: {name}")
    environment = service.get("environment") or {}
    if isinstance(environment, list):
        environment = dict(item.split("=", 1) for item in environment)
    if not isinstance(environment, dict) or any(not isinstance(v, str) for v in environment.values()):
        raise GateFailure("compose environment is not a resolved string map")
    for name, value in sorted(environment.items()):
        arguments += ["--env", f"{name}={value}"]
    for volume in service.get("volumes") or []:
        if (
            not isinstance(volume, dict) or volume.get("type") != "bind"
            or not isinstance(volume.get("source"), str) or not isinstance(volume.get("target"), str)
            or set(volume) - {"type", "source", "target", "read_only", "bind"}
        ):
            raise GateFailure(f"compose volume is not a bind Gate D understands: {volume!r}")
        mount = f"type=bind,src={volume['source']},dst={volume['target']}"
        arguments += ["--mount", mount + (",readonly" if volume.get("read_only") is True else "")]
    if "stop_grace_period" in service:
        arguments += ["--stop-timeout", str(_duration_seconds(service["stop_grace_period"]))]
    # Candidate code never starts with capabilities or privilege escalation,
    # whatever the compose file says.
    pairs = set(zip(arguments, arguments[1:]))
    if ("--cap-drop", "ALL") not in pairs or not any(
        flag == "--security-opt" and value.startswith("no-new-privileges")
        and value.split(":", 1)[-1] in ("no-new-privileges", "true")
        for flag, value in pairs
    ):
        raise GateFailure(
            "compose no longer drops all capabilities and privilege escalation; "
            "Gate D will not run candidate code without both"
        )
    return arguments


# What frontend_release.build_release reads from a source root without a receipt.
FRONTEND_RELEASE_INPUTS = ("frontend", "deploy/frontend-contract.json")


def _frontend_release_for_revision(revision: str, parent: Path) -> dict[str, object]:
    """The mounted frontend is built from the image's own revision, not the working tree."""

    try:
        snapshot = materialize_git_snapshot(PROJECT_ROOT, revision, parent / "source", FRONTEND_RELEASE_INPUTS)
        return build_frontend_release(
            source_root=snapshot, output_parent=parent / "release",
            public_source_revision=revision, require_clean_revision=False,
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise GateFailure(f"frontend release for the image revision failed: {error}") from None


def _start_container(image: str, workers: int, platform: str | None) -> tuple[str, str, Path]:
    if workers != 1:
        raise GateFailure("Gate D's container acceptance is single-worker by scope")
    container = f"armillary-{workers}w-{uuid.uuid4().hex[:10]}"
    identity = _inspect_image(image, platform)
    revision, image_id = identity.get("revision"), identity.get("id")
    if not isinstance(revision, str) or not isinstance(image_id, str):
        raise GateFailure("image identity is unavailable for frontend release")
    temporary = Path(tempfile.mkdtemp(prefix="container-frontend-release-"))
    try:
        built = _frontend_release_for_revision(revision, temporary)
        digest = str(built["artifact_digest"])
        service = _compose_service_model({
            "IMAGE_TAG": "gate-d",
            "STAGING_SERVER_NAME": GATE_D_EXPECTED_HOST,
            "FRONTEND_RELEASE_DIR": str(built["release_directory"]),
            "FRONTEND_RELEASE_DIGEST": digest,
            "COMBINED_RELEASE_ID": combined_release_id(
                backend_image_id=image_id, backend_public_source_revision=revision,
                frontend_artifact_digest=digest,
                frontend_public_source_revision=str(built["frontend_public_source_revision"]),
            ),
            "BACKEND_IMAGE_ID": image_id,
        })
        # Production compose activates the pair's immutable image ID, never a
        # tag another image of the same revision could move (CX-1009 #1).
        if service.get("image") != image_id:
            raise GateFailure(
                f"compose activates {service.get('image')!r}, not the image ID under test {image_id}"
            )
        _run([
            "docker", "run", *_platform_args(platform), "--detach", "--name", container,
            *_compose_run_arguments(service), "--publish", "127.0.0.1::8000",
            image, *SINGLE_WORKER_COMMAND,
        ])
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    try:
        _wait_healthy(container)
        return container, f"http://127.0.0.1:{_host_port(container)}", temporary
    except Exception:
        _run(["docker", "rm", "--force", container], check=False)
        shutil.rmtree(temporary, ignore_errors=True)
        raise


# Measured, not inferred: the root mount's flag from /proc/self/mountinfo, a
# write where the runtime user's permissions would allow it (/var/tmp is 1777)
# so only a read-only mount refuses it with EROFS, and the privilege state of
# this process and PID 1.
_CONTAINER_CONTROL_PROBE = r"""
import errno, json, os
root_options = None
with open("/proc/self/mountinfo", encoding="utf-8") as handle:
    for line in handle:
        fields = line.split()
        if len(fields) > 5 and fields[4] == "/":
            root_options = fields[5].split(",")
def attempt(path):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        return errno.errorcode.get(error.errno, str(error.errno))
    os.close(descriptor)
    os.unlink(path)
    return "written"
def status(pid):
    values = {}
    with open(f"/proc/{pid}/status", encoding="utf-8") as handle:
        for line in handle:
            key, _, value = line.partition(":")
            values[key] = value.strip()
    return {"no_new_privs": values.get("NoNewPrivs"), "cap_eff": values.get("CapEff")}
print(json.dumps({
    "root_mount_options": root_options,
    "dac_writable_root_path": attempt("/var/tmp/.gate-d-write-probe"),
    "tmpfs": attempt("/tmp/.gate-d-write-probe"),
    "self": status("self"),
    "pid1": status(1),
}, sort_keys=True))
"""


def _container_controls(container: str) -> dict[str, Any]:
    output = _run(["docker", "exec", container, "/opt/venv/bin/python", "-c", _CONTAINER_CONTROL_PROBE]).stdout
    try:
        observed = json.loads(output.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise GateFailure("container control probe output is unreadable") from error
    options = observed.get("root_mount_options")
    if not isinstance(options, list) or "ro" not in options:
        raise GateFailure(f"root filesystem is not mounted read-only: {options!r}")
    if observed.get("dac_writable_root_path") != "EROFS":
        raise GateFailure(
            f"a root path the runtime user may write was not refused: {observed.get('dac_writable_root_path')!r}"
        )
    if observed.get("tmpfs") != "written":
        raise GateFailure("bounded tmpfs did not accept a temporary write")
    for process in ("self", "pid1"):
        state = observed.get(process)
        if not isinstance(state, dict) or state.get("no_new_privs") != "1":
            raise GateFailure(f"{process} runs without no_new_privs")
        try:
            effective = int(str(state.get("cap_eff")), 16)
        except ValueError:
            raise GateFailure(f"{process} effective capabilities are unreadable") from None
        if effective != 0:
            raise GateFailure(f"{process} holds effective capabilities: {effective:#x}")
    return observed


def _resource_limits(container: str) -> dict[str, Any]:
    """The limits compose declares, as Docker applied them to this container."""

    host = json.loads(_run(["docker", "inspect", container]).stdout)[0]["HostConfig"]
    limits = {key: host.get(key) for key in ("Memory", "PidsLimit", "NanoCpus", "ReadonlyRootfs")}
    if (
        not all(isinstance(limits[key], int) and limits[key] > 0 for key in ("Memory", "PidsLimit", "NanoCpus"))
        or limits["ReadonlyRootfs"] is not True
        or "ALL" not in [str(item).upper() for item in host.get("CapDrop") or []]
    ):
        raise GateFailure(f"container runs without its resource limits or capability drop: {limits}")
    return limits


def _runtime_controls(container: str, base_url: str) -> dict[str, Any]:
    uid = _run(["docker", "exec", container, "id", "-u"]).stdout.strip()
    if uid != "10001":
        raise GateFailure(f"runtime uid is {uid}, not 10001")
    _container_controls(container)
    limits = _resource_limits(container)
    status, body, _ = _http(base_url, "/api/health")
    if status != 200 or json.loads(body) != {
        "status": "ok", "ready": True, "readiness_scope": "process_liveness_only",
    }:
        raise GateFailure("hosted readiness endpoint contract failed")
    for hidden_path in HIDDEN_RUNTIME_PATHS:
        if _http(base_url, hidden_path)[0] != 404:
            raise GateFailure(f"hosted endpoint remained visible: {hidden_path}")
    statuses = {
        name: _http(base_url, "/api/chart", body=body, content_type=content_type)[0]
        for name, (body, content_type) in {
            "unsupported_media_type": (b"{}", "text/plain"),
            "oversized": (b" " * (16 * 1024 + 1), "application/json"),
            "malformed": (b'{"datetime":', "application/json"),
        }.items()
    }
    if statuses["unsupported_media_type"] != 415 or statuses["oversized"] != 413 or statuses["malformed"] >= 500:
        raise GateFailure(f"request boundary mismatch: {statuses}")
    return {
        "uid": int(uid),
        "rootfs_write_rejected": True,
        "root_mount_read_only": True,
        "tmpfs_write_accepted": True,
        "no_new_privs": True,
        "effective_capabilities": 0,
        "resource_limits": limits,
        "compose_deviations": {
            **COMPOSE_DECLARED_DEVIATIONS, "command": GATE_D_PROCESS_DEVIATION,
            "logging": GATE_D_LOG_DEVIATION,
        },
        "health": "ready",
        "hidden_endpoints": list(HIDDEN_RUNTIME_PATHS),
        "request_boundary_statuses": statuses,
    }


def _privacy_canaries(payloads: list[dict[str, Any]]) -> frozenset[str]:
    """Birth year and coordinates actually sent; none may reach the logs."""

    canaries: set[str] = set()
    serialized = json.dumps(payloads, sort_keys=True, separators=(",", ":"))
    for payload in payloads:
        datetime_, location = payload.get("datetime", {}), payload.get("location", {})
        for value in (datetime_.get("year"), location.get("latitude"), location.get("longitude")):
            if isinstance(value, (int, float)):
                if str(value) not in serialized:
                    raise GateFailure("privacy canary is absent from the sent payload")
                canaries.add(str(value))
    if len(canaries) < 3:
        raise GateFailure("actual chart requests provide no complete privacy canary set")
    return frozenset(canaries)


def _verify_container_logs(logs: str, sensitive_values: frozenset[str]) -> dict[str, Any]:
    for forbidden in ('"POST /api/chart HTTP/', *sorted(sensitive_values)):
        if forbidden in logs:
            raise GateFailure("container log disclosed request or canary data")
    events: list[dict[str, Any]] = []
    for line in logs.splitlines():
        if "PRIVACY_EVENT " not in line:
            continue
        try:
            event = json.loads(line.split("PRIVACY_EVENT ", 1)[1])
        except (json.JSONDecodeError, IndexError) as error:
            raise GateFailure("container emitted malformed privacy telemetry") from error
        if set(event) != EXPECTED_PRIVACY_EVENT_FIELDS:
            raise GateFailure("container privacy telemetry escaped its closed schema")
        events.append(event)
    if not any(event["route"] == "/api/chart" for event in events):
        raise GateFailure("container emitted no status-only chart telemetry")
    return {
        "privacy_event_count": len(events),
        "chart_status_only_event_present": True,
        "raw_chart_access_log_absent": True,
    }


def _single_worker_acceptance(
    image: str, payloads: list[dict[str, Any]], platform: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    container, base_url, frontend_temporary = _start_container(image, 1, platform)
    try:
        controls = _runtime_controls(container, base_url)
        results = []
        for index, payload in enumerate(payloads):
            try:
                results.append(_chart(base_url, payload))
            except GateFailure as error:
                raise GateFailure(f"single-worker case {index}: {error}") from error
        worst_options = _worst_options_observation(container, base_url)
        logs = _run(["docker", "logs", container], check=False)
        return {
            "calculation_cases": len(payloads),
            "runtime_smoke": "one_nondefault_synthetic_chart",
            "controls": controls,
            "log_controls": _verify_container_logs(logs.stdout + logs.stderr, _privacy_canaries(payloads)),
            "worst_options": worst_options,
        }, results
    finally:
        _run(["docker", "rm", "--force", container], check=False)
        shutil.rmtree(frontend_temporary, ignore_errors=True)


def _assert_container_build_identity(
    image_revision: str | None, container_results: list[dict[str, Any]],
) -> None:
    """Each answer names the image's revision and the mounted frontend release."""

    if image_revision is None or not re.fullmatch(r"[0-9a-f]{40}", image_revision):
        raise GateFailure("image revision label is not a full lowercase Git revision")
    if not container_results:
        raise GateFailure("no answer from the container to bind to the image revision")
    for index, result in enumerate(container_results):
        identity = result.get("calculation_dossier", {}).get("build_identity")
        release = identity.get("release_identity") if isinstance(identity, dict) else None
        if (
            not isinstance(identity, dict)
            or identity.get("status") != "available"
            or identity.get("source_revision") != image_revision
            or identity.get("revision_source") != "build_environment:CLASSICAL_ASTROLOGY_SOURCE_REVISION"
            or not isinstance(release, dict)
            or release.get("status") != "available"
            or release.get("backend", {}).get("public_source_revision") != image_revision
            or not re.fullmatch(r"[0-9a-f]{64}", str(release.get("combined_release_id", "")))
        ):
            raise GateFailure(
                f"single-worker case {index}: Dossier build identity "
                "does not match the OCI and mounted frontend release"
            )


def main() -> int:
    global PROJECT_ROOT, CHART_REQUESTS, DOCKERFILE, APP_TREE_MANIFEST, EXPECTED_PRIVACY_EVENT_FIELDS
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--platform", help="Docker target platform, for example linux/amd64")
    parser.add_argument("--receipt", type=Path)
    parser.add_argument(
        "--quiet", action="store_true",
        help="emit only a closed summary; retain full JSON in --receipt",
    )
    args = parser.parse_args()

    PROJECT_ROOT = args.source_root.resolve()
    CHART_REQUESTS = PROJECT_ROOT / "frontend/tests/fixtures/chart-requests.json"
    DOCKERFILE = PROJECT_ROOT / "deploy/Dockerfile"
    APP_TREE_MANIFEST = PROJECT_ROOT / "deploy/image-app-tree.json"
    EXPECTED_PRIVACY_EVENT_FIELDS = _privacy_event_fields()

    started = time.monotonic()
    try:
        image = _inspect_image(args.image, args.platform)
        inventory = _inventory_image(args.image, args.platform)
        payloads = _payloads()
        single_worker, container_results = _single_worker_acceptance(
            args.image, payloads, args.platform,
        )
        _assert_container_build_identity(image["revision"], container_results)
        receipt = {
            "schema_version": "image-runtime-acceptance-v3",
            "image": image,
            "inventory": inventory,
            "single_worker": single_worker,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
        if args.receipt is not None:
            receipt_path = external_output_path(
                args.receipt, source_root=PROJECT_ROOT, role="container runtime receipt"
            )
            receipt_path.parent.mkdir(parents=True, exist_ok=True)
            receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.quiet:
            print(f"OK: image runtime acceptance (architecture={image['architecture']})")
        else:
            print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (GateFailure, OSError, subprocess.TimeoutExpired, ValueError) as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
