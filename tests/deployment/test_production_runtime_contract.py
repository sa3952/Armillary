"""The production runtime contract: the container health check, the startup
verifiers, the image gate's environment, inventory and log checks, and the
build-input bounds the image depends on.  Published with the source, so it
uses no shared test fixture."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import tarfile
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_GATE = "scripts/verification/verify_container_runtime.py"


def _load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _healthcheck(monkeypatch, tmp_path):
    module = _load_script("container_healthcheck", "deploy/container_healthcheck.py")
    monkeypatch.setattr(module, "STATE", tmp_path / "health.json")
    return module


def test_container_healthcheck_uses_the_declared_host_and_checks_status_and_flag_only(
        monkeypatch, tmp_path):
    module = _healthcheck(monkeypatch, tmp_path)
    observed = []
    answers = {
        "/api/health": {"status": "ok", "ready": True, "readiness_scope": "process_liveness_only"},
        "/api/chart": {"calculation_dossier": {"provenance": {
            "all_core_calculation_sources_used_full_ephemeris": True}}},
        "/api/places/search": {"results": []},
    }

    class Response:
        status = 200

        def __init__(self, path):
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(answers[self.path]).encode()

    def open_request(request, *, timeout):
        path = request.full_url.removeprefix("http://127.0.0.1:8000")
        observed.append((request.get_method(), path, request.get_header("Host"), timeout))
        return Response(path)

    monkeypatch.setenv("CLASSICAL_ASTROLOGY_EXPECTED_HOST", "projectarmillary.com")
    monkeypatch.setattr(module, "_DIRECT_OPENER", SimpleNamespace(open=open_request))

    assert module.main() == 0                               # the first run is deep
    assert observed == [("GET", "/api/health", "projectarmillary.com", 2.0),
                        ("POST", "/api/chart", "projectarmillary.com", 25.0),
                        ("POST", "/api/places/search", "projectarmillary.com", 8.0)]
    observed.clear()
    assert module.main() == 0                               # then liveness only
    assert [path for _method, path, _host, _timeout in observed] == ["/api/health"]
    answers["/api/chart"]["calculation_dossier"]["provenance"][
        "all_core_calculation_sources_used_full_ephemeris"] = False
    assert module.check(deep=True) == module.FAILED         # the flag is the only chart value read


def test_container_healthcheck_restarts_only_after_three_failures_of_a_once_healthy_container(
        monkeypatch, tmp_path):
    module = _healthcheck(monkeypatch, tmp_path)
    signals, deep_runs = [], []
    monkeypatch.setattr(module, "_pid1_is_container_init", lambda: True)
    monkeypatch.setattr(module.os, "kill", lambda pid, number: signals.append((pid, number)))

    def run(results):
        for healthy in results:
            outcome = module.HEALTHY if healthy else module.FAILED
            monkeypatch.setattr(module, "check", lambda deep, outcome=outcome: (
                deep_runs.append(deep), outcome)[1])
            module.main()

    run([False] * 6)                                        # never healthy: left to the deploy wait
    assert signals == [] and all(deep_runs)
    run([True])
    run([True] * 8)
    # The first pass (run 7) is deep, then every tenth run (run 10); a failure makes the next run deep.
    assert deep_runs[6:] == [True, False, False, True, False, False, False, False, False]
    run([False, False])
    assert signals == []
    run([False])
    assert signals == [(1, module.signal.SIGTERM)]
    run([False, False])
    assert signals[-1] == (-1, module.signal.SIGKILL)
    run([True])
    assert module._read_state()["failures"] == 0


def test_container_healthcheck_counts_busy_refusals_only_after_ten_minutes(monkeypatch, tmp_path):
    """A 503 busy refusal neither fails nor resets; ten minutes of nothing else is one failure."""
    module = _healthcheck(monkeypatch, tmp_path)
    signals, deep_runs, clock = [], [], [1000]
    monkeypatch.setattr(module, "_pid1_is_container_init", lambda: True)
    monkeypatch.setattr(module.os, "kill", lambda pid, number: signals.append((pid, number)))
    monkeypatch.setattr(module.time, "monotonic", lambda: clock[0])

    def run(outcome, *, advance=30):
        monkeypatch.setattr(module, "check", lambda deep: (deep_runs.append(deep), outcome)[1])
        clock[0] += advance
        return module.main()

    assert run(module.HEALTHY) == 0                         # healthy once
    assert run(module.FAILED) == 1
    assert run(module.SATURATED) == 0                       # neither a failure ...
    assert module._read_state()["failures"] == 1            # ... nor a reset
    for _ in range(18):                                     # 9 more minutes of busy refusals
        assert run(module.SATURATED) == 0
    assert all(deep_runs[2:]) and signals == []             # every run after the failure is deep
    assert run(module.SATURATED, advance=59) == 0           # 599 s: not yet ten minutes
    assert run(module.SATURATED, advance=1) == 1            # 600 s of busy refusals: one failure
    assert module._read_state()["failures"] == 2 and signals == []
    assert run(module.FAILED) == 1                          # a real failure breaks the streak
    assert signals == [(1, module.signal.SIGTERM)]
    assert run(module.HEALTHY) == 0
    assert module._read_state() == {"runs": 25, "failures": 0, "deep_passed": 1, "saturated_since": 0}


def test_container_healthcheck_reads_only_busy_503s_as_saturation(monkeypatch, tmp_path):
    module = _healthcheck(monkeypatch, tmp_path)

    class Health:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(module.LIVENESS).encode()

    for status, code, expected in (
        (503, "compute_capacity_exhausted", module.SATURATED),
        (503, "request_capacity_exhausted", module.SATURATED),
        (503, "place_catalog_unavailable", module.FAILED),
        (500, "compute_capacity_exhausted", module.FAILED),
    ):
        def open_request(request, *, timeout, status=status, code=code):
            if request.full_url.endswith("/api/health"):
                return Health()
            body = json.dumps({"detail": {"code": code, "message": "x"}}).encode()
            raise module.HTTPError(request.full_url, status, "refused", {}, io.BytesIO(body))

        monkeypatch.setattr(module, "_DIRECT_OPENER", SimpleNamespace(open=open_request))
        assert module.check(deep=True) == expected, (status, code)


def test_container_healthcheck_signals_nothing_outside_a_container(monkeypatch, tmp_path):
    module = _healthcheck(monkeypatch, tmp_path)
    monkeypatch.setattr(module.os, "kill", lambda *_args: pytest.fail("signalled outside a container"))
    monkeypatch.setattr(module, "_pid1_is_container_init", lambda: False)
    module.restart(10)


def test_container_healthcheck_does_not_follow_an_ambient_proxy(monkeypatch, tmp_path):
    """OPS-19: a proxy answering the expected body must not make a dead listener healthy."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import socket
    import threading

    requests: list[str] = []

    class Proxy(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server naming
            requests.append(self.path)
            body = json.dumps({
                "status": "ok", "ready": True, "readiness_scope": "process_liveness_only",
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        proxy = f"http://127.0.0.1:{server.server_address[1]}"
        for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
            monkeypatch.setenv(name, proxy)
        for name in ("no_proxy", "NO_PROXY"):
            monkeypatch.delenv(name, raising=False)
        healthcheck = _healthcheck(monkeypatch, tmp_path)
        result = healthcheck.main()
    finally:
        server.shutdown()
        server.server_close()

    assert requests == [], "the loopback health request was routed through a proxy"
    with socket.socket() as probe:
        listener_present = probe.connect_ex(("127.0.0.1", 8000)) == 0
    if not listener_present:
        assert result == 1


def test_the_ephemeris_verifier_rejects_a_changed_digest_and_an_extra_input(tmp_path, monkeypatch):
    """The committed manifest is held against the committed ephemeris files here,
    in `make check`; before, only the image entrypoint and Gate D compared them."""
    module = _load_script("verify_ephemeris_integrity", "scripts/verification/verify_ephemeris_integrity.py")
    assert module.verify(PROJECT_ROOT / "deploy/ephemeris.sha256") == []
    lines = (PROJECT_ROOT / "deploy/ephemeris.sha256").read_text(encoding="utf-8").splitlines()
    digest, relative_path = lines[0].split(maxsplit=1)
    lines[0] = f"{'0' if digest[0] != '0' else '1'}{digest[1:]}  {relative_path}"
    (tmp_path / "tampered.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert module.verify(tmp_path / "tampered.sha256") == [f"digest mismatch: {relative_path}"]

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    for path in module.EXPECTED_PATHS:
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(b"known ephemeris input")
    (tmp_path / "backend/ephe/unexpected.se1").write_bytes(b"unexpected")
    (tmp_path / "ephemeris.sha256").write_text("".join(
        f"{hashlib.sha256(b'known ephemeris input').hexdigest()}  {path}\n"
        for path in sorted(module.EXPECTED_PATHS)), encoding="utf-8")
    assert module.verify(tmp_path / "ephemeris.sha256") == [
        "unexpected ephemeris input: backend/ephe/unexpected.se1"]
    (tmp_path / "backend/ephe/unexpected.se1").unlink()
    changed = sorted(module.EXPECTED_PATHS)[0]
    (tmp_path / changed).write_bytes(b"replaced ephemeris input")
    assert module.verify(tmp_path / "ephemeris.sha256") == [f"digest mismatch: {changed}"]


@pytest.mark.parametrize("replacement", ["symlink_to_same_bytes", "directory", "absent"])
def test_the_ephemeris_verifier_refuses_an_input_that_is_not_a_regular_file(
    tmp_path, monkeypatch, replacement
):
    """Only a regular file is a verified input, whatever its bytes hash to.

    A symlink to identical bytes passes a digest check, and a directory or a
    missing file passes an existence check; each must be refused by name.
    """
    module = _load_script("verify_ephemeris_integrity", "scripts/verification/verify_ephemeris_integrity.py")
    root = tmp_path / "root"
    monkeypatch.setattr(module, "PROJECT_ROOT", root)
    content = b"known ephemeris input"
    for path in module.EXPECTED_PATHS:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)
    manifest = tmp_path / "ephemeris.sha256"
    manifest.write_text("".join(
        f"{hashlib.sha256(content).hexdigest()}  {path}\n"
        for path in sorted(module.EXPECTED_PATHS)), encoding="utf-8")
    assert module.verify(manifest) == []

    target = sorted(module.EXPECTED_PATHS)[0]
    (root / target).unlink()
    if replacement == "symlink_to_same_bytes":
        outside = tmp_path / "outside.bin"
        outside.write_bytes(content)
        (root / target).symlink_to(outside)
    elif replacement == "directory":
        (root / target).mkdir()
    assert module.verify(manifest) == [f"missing or non-regular input: {target}"]


def test_image_environment_holds_the_application_contract(monkeypatch):
    module = _load_script("verify_image_environment_contract", CONTAINER_GATE)
    revision = "a" * 40
    environment = [
        "PATH=/opt/venv/bin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", "LANG=C.UTF-8",
        "PYTHON_VERSION=3.14.8", "CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE=1",
        f"CLASSICAL_ASTROLOGY_SOURCE_REVISION={revision}", "PYTHONFAULTHANDLER=1",
        "PYTHONUNBUFFERED=1", "PYTHONDONTWRITEBYTECODE=1", "PYTHON_SHA256=" + "d" * 64,
    ]

    def inspect_with(items, user="10001:10001"):
        payload = [{"Id": "sha256:" + "c" * 64, "Os": "linux", "Architecture": "amd64", "Config": {
            "User": user, "Env": items, "Labels": {"org.opencontainers.image.revision": revision},
            "Healthcheck": {"Test": ["CMD", "container_healthcheck.py"]}}}]
        monkeypatch.setattr(module, "_run", lambda *_args, **_kwargs: SimpleNamespace(stdout=json.dumps(payload)))
        return module._inspect_image("fixture", "linux/amd64")

    assert inspect_with(environment)["revision"] == revision
    with pytest.raises(module.GateFailure, match="application contract"):
        inspect_with(["PATH=/tmp/attacker", *environment[1:]])
    with pytest.raises(module.GateFailure, match="CLASSICAL_ASTROLOGY_SOURCE_REVISION"):
        inspect_with([*environment[:5], "CLASSICAL_ASTROLOGY_SOURCE_REVISION=" + "b" * 40,
                      *environment[6:]])
    with pytest.raises(module.GateFailure, match="repeated"):
        inspect_with([*environment, "LANG=C"])
    # The environment is closed: an extra debug, proxy, secret or interpreter
    # control variable fails even though every contract value still holds.
    for extra in ("HTTPS_PROXY=http://proxy.invalid", "PYTHONPATH=/tmp", "DEBUG=1",
                  "CLASSICAL_ASTROLOGY_TOKEN=x", "PYTHON_GIL=0"):
        with pytest.raises(module.GateFailure, match="outside the application and base set"):
            inspect_with([*environment, extra])
    with pytest.raises(module.GateFailure, match="unexpected image user"):
        inspect_with(environment, user="0:0")
    # The platform vocabulary is build_release_image's; the gate refuses in its own terms.
    assert module._platform_contract("linux/arm64/v8") == ("linux", "arm64")
    with pytest.raises(module.GateFailure):
        module._platform_contract("linux/riscv64")


def test_exact_image_gate_owns_one_bounded_worst_options_observation(monkeypatch):
    module = _load_script("verify_image_worst_options", CONTAINER_GATE)
    from app.schemas import ChartRequest

    payload = module._worst_options_payload()
    request = ChartRequest.model_validate(payload)
    assert request.options.include_aspect_perfection is True
    assert request.options.include_eclipses is True
    assert request.options.include_rise_set_transits is True
    assert request.options.triplicity_include_research_comparison is True
    assert module.MAX_BENCHMARK_RESPONSE_BYTES == 512 * 1024

    sample = {"a": {"bisection_iterations": 3}, "b": [{"bisection_iterations": 5}, {"other": 1}]}
    assert module._count_named_fields(sample, "bisection_iterations") == 2
    metrics = iter(({"cpu_usage_usec": 100, "memory_current": 200, "memory_peak": 300},
                    {"cpu_usage_usec": 175, "memory_current": 240, "memory_peak": 340}))
    monkeypatch.setattr(module, "_cgroup_metrics", lambda _container: next(metrics))
    monkeypatch.setattr(module, "_timed_chart", lambda *_args: {"status": 200})
    assert module._worst_options_observation("container", "http://fixture")["resources"] == {
        "cpu_usage_usec_delta": 75, "memory_current_before": 200, "memory_current_after": 240,
        "memory_peak_after": 340}


def test_image_inventory_rejects_setid_regular_files():
    module = _load_script("verify_container_setid", CONTAINER_GATE)
    member = tarfile.TarInfo("app/payload")
    member.type = tarfile.REGTYPE
    member.mode = 0o4755
    with pytest.raises(module.GateFailure, match="setuid/setgid"):
        module._assert_safe_regular_mode(member, "/app/payload")

    member.mode = 0o755
    module._assert_safe_regular_mode(member, "/app/payload")


def test_container_log_gate_accepts_only_closed_chart_telemetry_and_canaries_from_the_payload():
    module = _load_script("verify_container_runtime_log_contract", CONTAINER_GATE)
    # Built from the emitter's own declaration rather than typed again here: a
    # copy written when the schema had ten fields made the image fail its own check.
    from app import privacy_logging as emitter

    values = {
        "event_schema_version": emitter.EVENT_SCHEMA_VERSION, "event": "http_request_completed",
        "request_id": "0" * 32, "route": "/api/chart", "method": "POST", "status_code": 200,
        "duration_bucket": "50_to_249ms", "request_size_bucket": "1_to_1024b", "outcome": "success",
        "error_code": None, "failure_class": None,
    }
    assert set(values) == set(emitter.ALLOWED_EVENT_FIELDS), "this fixture omits a field the emitter declares"
    safe_event = json.dumps({name: values[name] for name in emitter.ALLOWED_EVENT_FIELDS}, separators=(",", ":"))
    canaries = module._privacy_canaries([{"datetime": {"year": 1990},
                                          "location": {"latitude": 22.9908, "longitude": 120.2133}}])
    assert canaries == frozenset({"1990", "22.9908", "120.2133"})
    with pytest.raises(module.GateFailure, match="complete privacy canary"):
        module._privacy_canaries([{"datetime": {"year": 1990}}])

    result = module._verify_container_logs("PRIVACY_EVENT " + safe_event, canaries)
    assert result["chart_status_only_event_present"] is True and result["raw_chart_access_log_absent"] is True
    with pytest.raises(module.GateFailure, match="disclosed"):
        module._verify_container_logs('"POST /api/chart HTTP/1.1" 200\nPRIVACY_EVENT ' + safe_event, canaries)
    with pytest.raises(module.GateFailure, match="closed schema"):
        module._verify_container_logs("PRIVACY_EVENT " + safe_event[:-1] + ',"unexpected":"x"}', canaries)


def test_place_catalog_startup_verifier_rejects_a_corrupted_catalog(tmp_path, monkeypatch):
    module = _load_script("verify_place_catalog", "scripts/verification/verify_place_catalog.py")
    for name in ("catalog_manifest.json", "places.sqlite3"):
        shutil.copy2(PROJECT_ROOT / "backend/place_data" / name, tmp_path / name)
    with (tmp_path / "places.sqlite3").open("r+b") as handle:
        first = handle.read(1)
        handle.seek(0)
        handle.write(bytes([first[0] ^ 0xFF]))
    monkeypatch.setattr(module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(module, "MANIFEST_PATH", tmp_path / "catalog_manifest.json")
    with pytest.raises(SystemExit, match="SHA-256"):
        module.verify()


@pytest.mark.parametrize(
    ("installed", "must_fail"),
    (("perl-base\tyes\nperl\tno\n", True), ("perl-base\tyes\nlibc6\tyes\n", False)),
)
def test_dockerfile_perl_survivor_check_fails_the_build_under_set_e(tmp_path, installed, must_fail):
    """OPS-36: `! cmd` is exempt from `set -e`, so the old check could not fail."""
    import subprocess

    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("no POSIX shell")
    text = (PROJECT_ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
    start = text.index("| grep -q '^ii  yes$'; \\\n") + len("| grep -q '^ii  yes$'; \\\n")
    end = text.index("    python -m pip uninstall --yes pip", start)
    snippet = text[start:end].replace("\\\n", " ")
    fake = tmp_path / "dpkg-query"
    (tmp_path / "packages").write_text(installed, encoding="utf-8")
    fake.write_text(f"#!/bin/sh\ncat '{tmp_path / 'packages'}'\n", encoding="utf-8")
    fake.chmod(0o755)
    program = f"set -eu\nPATH='{tmp_path}':$PATH\n{snippet}\necho reached\n"
    result = subprocess.run([shell, "-c", program], capture_output=True, text=True, timeout=10)
    if must_fail:
        assert result.returncode != 0 and "reached" not in result.stdout
        assert "non-essential Perl survived" in result.stderr
    else:
        assert result.returncode == 0 and "reached" in result.stdout


def test_graceful_shutdown_lets_a_queued_chart_finish_before_the_container_is_killed():
    """OPS-20: queue wait + compute < graceful window < stop grace."""

    dockerfile = (PROJECT_ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")
    runtime = (PROJECT_ROOT / "scripts/verification/verify_container_runtime.py").read_text(encoding="utf-8")
    compose = (PROJECT_ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
    from app import main

    graceful = int(re.search(r'"--timeout-graceful-shutdown", "(\d+)"', dockerfile).group(1))
    assert re.search(r'"--timeout-graceful-shutdown", "(\d+)"', runtime).group(1) == str(graceful)
    # AR-1: the wait budget is derived in request_limits, so read the value
    # the process runs with rather than a literal in the source.
    queue_wait = main._COMPUTE_LOCK_WAIT_TIMEOUT_SECONDS
    stop_grace = int(re.search(r"stop_grace_period: (\d+)s", compose).group(1))
    assert queue_wait < graceful < stop_grace


# The overflow is reachable only through the old fixed-star API; with the same
# crafted catalogue fixstar2_ut only answers "not found".  The product must keep
# calling the new API alone, so every reference to the old names is refused.
_OLD_FIXED_STAR_API = frozenset({"fixstar", "fixstar_ut", "fixstar_mag"})


def _old_fixed_star_api_uses(source: str, filename: str) -> list[str]:
    uses = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Attribute) and node.attr in _OLD_FIXED_STAR_API:
            uses.append(f"{filename}:{node.lineno} .{node.attr}")
        elif isinstance(node, ast.ImportFrom):
            uses.extend(
                f"{filename}:{node.lineno} import {alias.name}"
                for alias in node.names
                if alias.name in _OLD_FIXED_STAR_API
            )
        elif isinstance(node, ast.Constant) and node.value in _OLD_FIXED_STAR_API:
            uses.append(f"{filename}:{node.lineno} '{node.value}'")
    return uses


def test_the_product_reaches_swiss_fixed_stars_only_through_fixstar2():
    """OPS-29 is accepted permanently on this premise; an AST scan of the
    backend replaces the grep that used to be its only evidence."""
    uses, fixstar2_calls = [], 0
    for path in sorted((PROJECT_ROOT / "backend").rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        uses.extend(_old_fixed_star_api_uses(source, relative))
        fixstar2_calls += sum(
            isinstance(node, ast.Attribute) and node.attr in {"fixstar2_ut", "fixstar2_mag"}
            for node in ast.walk(ast.parse(source, filename=relative))
        )
    assert uses == []
    assert fixstar2_calls > 0  # the scan reads the code that really queries stars
    # The scan itself: each old spelling is caught.
    for probe in (
        "import swisseph as swe\nswe.fixstar_ut('Algol', 0.0, 0)",
        "from swisseph import fixstar",
        "import swisseph\ngetattr(swisseph, 'fixstar_mag')('Algol')",
    ):
        assert _old_fixed_star_api_uses(probe, "probe.py"), probe


def test_bundled_star_catalogue_fits_the_fixed_star_name_buffer():
    """OPS-29: libswe copies up to SE_MAX_STNAME (256) bytes of a catalogue name into
    a SWI_STAR_LENGTH + 1 buffer.  The bundled, hash-verified catalogue must never
    reach that path with a longer field."""
    archive = PROJECT_ROOT / "third_party/pyswisseph/pyswisseph-2.10.3.2.tar.gz"
    with tarfile.open(archive, "r:gz") as source:
        header = source.extractfile("pyswisseph-2.10.3.2/libswe/sweph.h").read().decode()
    limit = int(re.search(r"#define SWI_STAR_LENGTH (\d+)", header).group(1))
    assert limit == 40
    catalogue = PROJECT_ROOT / "backend/ephe/sefstars.txt"
    longest = max(
        len(line.split(",", 1)[0])
        for line in catalogue.read_text(encoding="latin-1").splitlines()
        if line and not line.startswith("#") and "," in line
    )
    assert longest <= limit, longest
    pinned = (PROJECT_ROOT / "deploy/ephemeris.sha256").read_text(encoding="utf-8")
    assert "sefstars.txt" in pinned
