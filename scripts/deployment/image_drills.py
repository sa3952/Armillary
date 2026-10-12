#!/usr/bin/env python3
"""Gate D's three resilience drills, run against the exact built image.

Each drill runs in a disposable container of the image with no network and
the run settings of ``deploy/compose.yaml`` (read-only root, tmpfs, no
capabilities or privilege escalation, resource limits, init), read through
``docker compose config`` and translated by Gate D's own compose translator;
no container is published and none is the live one.  Production hosts run no
drill.  The two edge cases the host gate used to drill live (``slow_body``,
``503``) are held by the real-NGINX tests and the byte-identical host config
readback instead.

``worker_restart`` (disposable twin)
    The image's own entrypoint and command (two workers).  One worker is killed
    while chart requests are in flight; the supervisor must replace it and the
    twin must serve a chart afterwards.
``timeout`` (disposable fault runtime)
    The image's application in-process with one injected fault: a chart holds
    the Swiss compute lock for ``HOLD_SECONDS``.  A chart queued behind it must
    be refused with ``503 compute_capacity_exhausted`` before the holder
    finishes: the queue wait is bounded.
``unexpected_error`` (disposable fault runtime)
    The same runtime raises an exception carrying the canary and the request
    from inside the chart computation.  The response must be the generic 500
    and the process must keep serving.

Every response and each container's log stream is searched for the canary.

Gate D runs this module after the image artifact acceptance.  The module exits 1
unless all three drills passed and the canary matched nothing.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from enum import Enum
from functools import reduce
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Iterator, Protocol

from scripts.deployment.verify_staging_http import (
    Canary, derive_canary, generate_canary, scan_application_logs,
)
from scripts.tools.staging_secure_io import emit_json_receipt
# One source for the sandbox: Gate D's compose reader and translator, which
# refuses a model that keeps capabilities or privilege escalation.
from scripts.verification.verify_container_runtime import (
    _compose_run_arguments, _compose_service_model, _wait_healthy,
)

RECEIPT_SCHEMA_VERSION = 3
# The disposable fault runtime holds the compute lock this long.  It must
# exceed the application's queue wait, which the drill observes rather than
# restates: the queued chart has to be refused before the holder returns.
HOLD_SECONDS = 30
WORKER_REPLACEMENT_WAIT_SECONDS = 30
DRILL_LABEL = "org.classical-astrology.drill=gate-d"
# The API-only service: compose.yaml without the frontend-release overlay.
DRILL_COMPOSE_FILES = ("deploy/compose.yaml",)
# The drills need no frontend release: an empty requirement serves the API only.
# These follow (and so override) whatever environment compose declares.
DRILL_EXPECTED_HOST = "image-drill.invalid"
DRILL_ENVIRONMENT = (
    f"CLASSICAL_ASTROLOGY_EXPECTED_HOST={DRILL_EXPECTED_HOST}",
    "CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE=",
)
ROOT = Path(__file__).resolve().parents[2]
CONTAINER_PYTHON = "/opt/venv/bin/python"
CONTAINER_APP_DIR = "/app/backend"
CONTAINER_PORT = 8000


class DrillResult(str, Enum):
    """A drill either observed the bounded behaviour, observed a violation, or
    could not reach the case; only ``passed`` counts toward Gate D."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_OBSERVED = "not_observed"


class Where(str, Enum):
    DISPOSABLE_TWIN = "disposable_twin_of_image"
    DISPOSABLE_FAULT_RUNTIME = "disposable_fault_runtime_of_image"


DRILL_LOCATIONS = {
    "worker_restart": Where.DISPOSABLE_TWIN,
    "timeout": Where.DISPOSABLE_FAULT_RUNTIME,
    "unexpected_error": Where.DISPOSABLE_FAULT_RUNTIME,
}
DRILLS = tuple(DRILL_LOCATIONS)


def _drill(result: DrillResult, **observation: Any) -> dict[str, Any]:
    return {"result": DrillResult(result).value, "observation": observation}


# --- drill payloads ---------------------------------------------------------------
# Synthetic, built on the canary's random year and longitude.  The capacity
# payload asks for rise／set searches on a date-only chart at 66°N, which costs
# about a second of Swiss work per chart (2026-10-05, Apple Silicon): long
# enough that a worker is busy when the worker drill kills it.
FAULT_SECOND_RAISE = 58
FAULT_SECOND_HOLD = 59


def drill_payloads(canary: Canary) -> dict[str, dict[str, Any]]:
    base = json.loads(canary.payload_bytes)
    capacity = json.loads(canary.payload_bytes)
    capacity["birth_time_precision"] = "date_only"
    capacity["datetime"].update({"hour": 0, "minute": 0, "second": 0})
    capacity["location"]["latitude"] = 66.0
    capacity["options"] = {"include_rise_set_transits": True}
    raising, holding = json.loads(canary.payload_bytes), json.loads(canary.payload_bytes)
    raising["datetime"]["second"] = FAULT_SECOND_RAISE
    holding["datetime"]["second"] = FAULT_SECOND_HOLD
    return {"ordinary": base, "capacity": capacity, "raise": raising, "hold": holding}


def scan_canary(canary: Canary) -> Canary:
    """One canary whose fragments cover every drill payload."""
    return reduce(derive_canary, drill_payloads(canary).values(), canary)


def _encoded(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


# Every program below runs with the image's Python (or, in tests, the local
# one) and reads one JSON object on stdin.  None takes a value on argv except
# the fault harness, whose two arguments are the hold time and the marker.
_PROBE_PRELUDE = r'''
import json, os, signal, subprocess, sys, threading, time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener
d = json.load(sys.stdin)
OPEN = build_opener(ProxyHandler({})).open
def req(path, body=None, timeout=90):
    h = {"Accept": "application/json", "Host": d["host"], "X-Private-Alpha-Canary": d["marker"]}
    if body is not None: h["Content-Type"] = "application/json"
    started = time.monotonic()
    try: r = OPEN(Request("http://127.0.0.1:%d%s" % (d["port"], path), data=body and body.encode(), headers=h), timeout=timeout)
    except HTTPError as e: r = e
    except (URLError, OSError): return {"status": 0, "seconds": round(time.monotonic() - started, 3), "code": None, "retry_after": None, "echo": False}
    with r:
        raw = r.read(4 * 1024 * 1024)
        code = None
        if r.status >= 400:
            try: code = json.loads(raw)["detail"]["code"]
            except Exception: code = None
        return {"status": r.status, "seconds": round(time.monotonic() - started, 3), "code": code,
                "retry_after": r.headers.get("Retry-After"),
                "echo": r.status >= 400 and any(f.encode() in raw for f in d["fragments"])}
'''

TIMEOUT_PROBE = _PROBE_PRELUDE + r'''
holder = {}
def hold(): holder.update(req("/api/chart", d["hold"], timeout=d["hold_seconds"] + 60))
thread = threading.Thread(target=hold); thread.start(); time.sleep(1.0)
queued = req("/api/chart", d["ordinary"])
thread.join()
print(json.dumps({"holder": holder, "queued": queued}))
'''

UNEXPECTED_ERROR_PROBE = _PROBE_PRELUDE + r'''
failing = req("/api/chart", d["raise"])
health = req("/api/health")
after = req("/api/chart", d["ordinary"])
print(json.dumps({"failing": failing, "health": health, "after": after}))
'''

WORKER_RESTART_PROBE = _PROBE_PRELUDE + r'''
def processes():
    table = {}
    if os.path.isdir("/proc/self"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit(): continue
            try:
                with open("/proc/%s/stat" % entry) as handle: fields = handle.read().rsplit(")", 1)[1].split()
                with open("/proc/%s/cmdline" % entry, "rb") as handle: command = handle.read().replace(b"\0", b" ").decode("utf-8", "replace")
            except OSError: continue
            table[int(entry)] = (int(fields[1]), command, int(fields[11]) + int(fields[12]))
    else:
        for line in subprocess.run(["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True).stdout.splitlines():
            pid, ppid, command = line.split(None, 2)
            table[int(pid)] = (int(ppid), command, None)
    return table
def supervisor():
    if d.get("supervisor_pid"): return d["supervisor_pid"]
    # docker-init (PID 1 under --init) carries the whole command line too, and so
    # does this probe (its program text names both words); neither is the supervisor.
    found = [pid for pid, (_, command, _) in processes().items() if "uvicorn" in command
             and "--workers" in command and pid != os.getpid()
             and not command.split(" ", 1)[0].endswith(("docker-init", "tini"))]
    return found[0] if len(found) == 1 else None
def workers(parent):
    return {pid: cpu for pid, (ppid, command, cpu) in processes().items() if ppid == parent and "resource_tracker" not in command}
parent = supervisor()
if parent is None:
    print(json.dumps({"supervisor_found": False})); sys.exit(0)
before = workers(parent)
inflight = []
threads = [threading.Thread(target=lambda: inflight.append(req("/api/chart", d["capacity"]))) for _ in range(4)]
for thread in threads: thread.start()
time.sleep(0.5)
during = workers(parent)
victim = max(during, key=lambda pid: (during[pid] or 0) - (before.get(pid) or 0)) if during else None
busy = None if victim is None or during[victim] is None else during[victim] > (before.get(victim) or 0)
if victim is not None: os.kill(victim, signal.SIGKILL)
started, replaced, after = time.monotonic(), False, {}
while time.monotonic() - started < d["replacement_wait_seconds"]:
    after = workers(parent)
    if victim not in after and len(after) == len(before): replaced = True; break
    time.sleep(0.25)
replacement_seconds = round(time.monotonic() - started, 3)
for thread in threads: thread.join()
health = req("/api/health")
chart = req("/api/chart", d["ordinary"])
print(json.dumps({"supervisor_found": True, "workers_before": len(before), "workers_after": len(after),
                  "victim_was_busy": busy, "replaced": replaced, "replacement_seconds": replacement_seconds,
                  "inflight_statuses": sorted(item["status"] for item in inflight),
                  "inflight_echo": any(item["echo"] for item in inflight), "health": health, "after": chart}))
'''

# The fault runtime: the exact image's application, one worker, with one
# function replaced.  The replacement is selected by the chart's `second`
# (58 raises with the marker and the request in the message, 59 holds the
# compute lock); every other chart runs the real computation.
FAULT_HARNESS = r'''
import sys, time
hold_seconds, marker, port, app_dir = float(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
sys.path.insert(0, app_dir)
import uvicorn
from app import main
real = main._compute_chart_locked
def drilled(req):
    second = int(req.datetime.second)
    if second == %(raise)d:
        raise RuntimeError("drill fault %%s %%r" %% (marker, req))
    if second == %(hold)d:
        time.sleep(hold_seconds)
    return real(req)
main._compute_chart_locked = drilled
uvicorn.run(main.create_app, factory=True, host="127.0.0.1", port=port, http="h11", loop="asyncio",
            ws="none", access_log=False)
''' % {"raise": FAULT_SECOND_RAISE, "hold": FAULT_SECOND_HOLD}


def evaluate_worker_restart(observed: dict[str, Any]) -> dict:
    if not observed.get("supervisor_found"):
        return _drill(DrillResult.NOT_OBSERVED, reason="supervisor_not_found")
    health, after = observed.get("health") or {}, observed.get("after") or {}
    passed = (observed.get("workers_before", 0) >= 2 and observed.get("replaced") is True
              and observed.get("workers_after") == observed.get("workers_before")
              and health.get("status") == 200 and after.get("status") == 200
              and not observed.get("inflight_echo"))
    return _drill(DrillResult.PASSED if passed else DrillResult.FAILED, **{
        key: observed.get(key) for key in (
            "workers_before", "workers_after", "victim_was_busy", "replaced", "replacement_seconds",
            "inflight_statuses")},
        health_status=health.get("status"), chart_after_status=after.get("status"))


def evaluate_timeout(observed: dict[str, Any]) -> dict:
    holder, queued = observed.get("holder") or {}, observed.get("queued") or {}
    refused = (queued.get("status") == 503 and queued.get("code") == "compute_capacity_exhausted"
               and bool(queued.get("retry_after")) and not queued.get("echo"))
    # Refused after it had queued (not at admission) and before the holder
    # returned: the wait itself was bounded.
    bounded = (refused and holder.get("status") == 200
               and 2.0 <= queued.get("seconds", 0) < holder.get("seconds", 0) - 2.0)
    return _drill(DrillResult.PASSED if bounded else DrillResult.FAILED,
                  holder_status=holder.get("status"), holder_seconds=holder.get("seconds"),
                  queued_status=queued.get("status"), queued_code=queued.get("code"),
                  queued_seconds=queued.get("seconds"), queued_retry_after=queued.get("retry_after"))


def evaluate_unexpected_error(observed: dict[str, Any]) -> dict:
    failing = observed.get("failing") or {}
    health, after = observed.get("health") or {}, observed.get("after") or {}
    passed = (failing.get("status") == 500 and failing.get("code") == "internal_server_error"
              and not failing.get("echo") and health.get("status") == 200 and after.get("status") == 200)
    return _drill(DrillResult.PASSED if passed else DrillResult.FAILED,
                  failing_status=failing.get("status"), failing_code=failing.get("code"),
                  failing_echoed_canary=failing.get("echo"), health_status=health.get("status"),
                  chart_after_status=after.get("status"))


class Runtime(Protocol):
    """How a disposable container of the image starts."""

    def disposable(self, kind: Where, canary: Canary) -> Any:
        """A context manager yielding a handle with `probe(program, payload)` and `log_sink(canary)`."""
        ...


def _probe_input(canary: Canary, *, host: str, port: int, **extra: Any) -> dict[str, Any]:
    payloads = drill_payloads(canary)
    return {"host": host, "port": port, "marker": canary.marker,
            "fragments": list(canary.sensitive_fragments),
            **{name: _encoded(payload).decode("utf-8") for name, payload in payloads.items()},
            "hold_seconds": HOLD_SECONDS, "replacement_wait_seconds": WORKER_REPLACEMENT_WAIT_SECONDS,
            **extra}


def run_disposable_drills(runtime: Runtime, canary: Canary) -> tuple[dict[str, dict], list[dict]]:
    """worker_restart in a twin; timeout and unexpected_error in the fault runtime."""
    drills: dict[str, dict] = {}
    sinks: list[dict] = []
    try:
        with runtime.disposable(Where.DISPOSABLE_TWIN, canary) as twin:
            drills["worker_restart"] = evaluate_worker_restart(twin.probe(WORKER_RESTART_PROBE, {}))
            sinks.append(twin.log_sink(canary))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        drills["worker_restart"] = _drill(DrillResult.NOT_OBSERVED, reason=f"twin: {type(error).__name__}")
    try:
        with runtime.disposable(Where.DISPOSABLE_FAULT_RUNTIME, canary) as faulty:
            drills["timeout"] = evaluate_timeout(faulty.probe(TIMEOUT_PROBE, {}))
            drills["unexpected_error"] = evaluate_unexpected_error(faulty.probe(UNEXPECTED_ERROR_PROBE, {}))
            sinks.append(faulty.log_sink(canary))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        for name in ("timeout", "unexpected_error"):
            drills.setdefault(name, _drill(DrillResult.NOT_OBSERVED,
                                           reason=f"fault runtime: {type(error).__name__}"))
    for sink in sinks:
        sink["sink_role"] = "disposable_container_docker_log_stream"
    return drills, sinks


# --- docker runtime: disposable containers of one image --------------------------------
def _docker(*arguments: str, stdin: str | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], input=stdin, capture_output=True, text=True,
                          check=False, timeout=timeout)


class _DockerDisposable:
    def __init__(self, container: str, probe_input: dict[str, Any]) -> None:
        self.container, self.probe_input = container, probe_input

    def probe(self, program: str, payload: dict[str, Any]) -> dict[str, Any]:
        completed = _docker("exec", "--interactive", self.container, CONTAINER_PYTHON, "-c", program,
                            stdin=json.dumps({**self.probe_input, **payload}), timeout=HOLD_SECONDS + 180)
        if completed.returncode != 0:
            raise RuntimeError(f"drill probe exited {completed.returncode}")
        return json.loads(completed.stdout)

    def log_sink(self, canary: Canary) -> dict[str, Any]:
        return scan_application_logs(canary, self.container, since=0.0)


class ImageRuntime:
    """Disposable containers of one exact image, with the run settings of
    `source_root`'s compose (Gate D's: the image's revision) and no network.

    The reference is resolved to an image ID once; every container runs that
    ID and must report it."""

    def __init__(self, image: str, platform: str | None = None, *, source_root: Path = ROOT) -> None:
        resolved = _docker("image", "inspect", "--format", "{{.Id}}", image)
        image_id = resolved.stdout.strip()
        if resolved.returncode != 0 or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise RuntimeError(f"cannot resolve {image} to an image ID")
        self.identity = {"reference": image, "id": image_id}
        self.image, self.platform, self.source_root = image_id, platform, source_root

    @contextmanager
    def disposable(self, kind: Where, canary: Canary) -> Iterator[_DockerDisposable]:
        for leftover in _docker("ps", "--all", "--quiet", "--filter", f"label={DRILL_LABEL}").stdout.split():
            _docker("rm", "--force", leftover)
        arguments = [
            "run", "--detach", *(("--platform", self.platform) if self.platform else ()),
            *_compose_run_arguments(_compose_service_model({}, DRILL_COMPOSE_FILES, self.source_root)),
            "--network", "none", "--label", DRILL_LABEL,
        ]
        for item in DRILL_ENVIRONMENT:
            arguments += ["--env", item]
        if kind is Where.DISPOSABLE_FAULT_RUNTIME:
            arguments += ["--entrypoint", CONTAINER_PYTHON, self.image, "-c", FAULT_HARNESS,
                          str(HOLD_SECONDS), canary.marker, str(CONTAINER_PORT), CONTAINER_APP_DIR]
        else:
            arguments.append(self.image)   # the image's own entrypoint and command
        started = _docker(*arguments)
        container = started.stdout.strip()
        if started.returncode != 0 or not container:
            raise RuntimeError("disposable container did not start")
        try:
            _wait_healthy(container)
            inspection = json.loads(_docker("inspect", container).stdout)[0]
            host_config = inspection.get("HostConfig") or {}
            if (host_config.get("NetworkMode") != "none" or host_config.get("PortBindings")
                    or inspection.get("Image") != self.image):
                raise RuntimeError("disposable container is not an unexposed container of the image")
            yield _DockerDisposable(
                container, _probe_input(canary, host=DRILL_EXPECTED_HOST, port=CONTAINER_PORT))
        finally:
            _docker("rm", "--force", container)


# --- the receipt ---------------------------------------------------------------------------
def run_image_drills(runtime: Runtime, image: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the three drills and search every disposable log stream for the canary;
    `image` is the reference and the ID the containers ran."""
    canary = scan_canary(generate_canary())
    drills, sinks = run_disposable_drills(runtime, canary)
    for name, drill in drills.items():
        drill["where"] = DRILL_LOCATIONS[name].value
    matches = sum(sink["match_count"] for sink in sinks)
    privacy = "pass" if matches == 0 and len(sinks) == 2 else "fail"
    passed = all(drills[name]["result"] == DrillResult.PASSED.value for name in DRILLS)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "image": image,
        "drills": {name: drills[name] for name in DRILLS},
        "privacy_canary": {"result": privacy, "total_match_count": matches, "sinks": sinks},
        "result": "pass" if passed and privacy == "pass" else "fail",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", required=True, help="the exact built image (ID or reference)")
    parser.add_argument("--platform", choices=("linux/amd64", "linux/arm64"))
    parser.add_argument("--source-root", type=Path, default=ROOT,
                        help="the checkout whose deploy/compose.yaml sets the run settings "
                             "(Gate D: the image's revision)")
    parser.add_argument("--output", type=Path, help="receipt path (repository-external); stdout when absent")
    parser.add_argument("--plan", action="store_true", help="print the drills and start nothing")
    args = parser.parse_args()
    if args.plan:
        print(json.dumps({"mode": "plan", "image": args.image, "containers_started": False,
                          "drills": {name: DRILL_LOCATIONS[name].value for name in DRILLS}}, indent=2))
        return
    runtime = ImageRuntime(args.image, args.platform, source_root=args.source_root.resolve())
    receipt = run_image_drills(runtime, runtime.identity)
    for name, drill in receipt["drills"].items():
        print(f"DRILL {name}: {drill['result']} ({drill['where']})", file=sys.stderr)
    print(f"DRILL privacy canary: {receipt['privacy_canary']['result']}", file=sys.stderr)
    emit_json_receipt(receipt, args.output)


if __name__ == "__main__":
    main()
