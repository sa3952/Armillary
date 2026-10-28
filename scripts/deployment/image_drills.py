#!/usr/bin/env python3
"""Gate D's five resilience drills, run against the exact built image.

Each drill runs in a disposable container of the image with no network and
the run settings of ``deploy/compose.yaml`` (read-only root, tmpfs, no
capabilities or privilege escalation, resource limits, init), read through
``docker compose config`` and translated by Gate D's own compose translator;
no container is published and none is the live one.  Production hosts run no
drill.  The ``slow_body`` and ``503`` edge cases are held by the real-NGINX
tests and the byte-identical host config readback.

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
``tmpfs_full`` (disposable fault runtime)
    /tmp and /dev/shm are filled until the kernel answers ENOSPC; with both
    full, the failing and an ordinary chart are sent.  The failing one must be
    the generic 500, the ordinary one must be served, and the filler is removed
    before the tmpfs scan.
``oom`` (disposable OOM runtime)
    The fault runtime under a minimal restarting parent, in the compose memory
    cap.  A chart makes the application allocate until the kernel's cgroup OOM
    killer ends it (``oom_kill`` in ``memory.events`` must rise); the parent
    restarts it and it must serve a chart again.  Without a cgroup (the local
    stand-in) the drill is ``not_observed``.

Every response, each container's log stream and every file of each
container's tmpfs (/tmp and /dev/shm, after its drills) is searched for the
canary.

Gate D runs this module after the image artifact acceptance.  The module exits 1
unless all five drills passed and the canary matched nothing.
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

from scripts.deployment.verify_staging_http import (Canary, derive_canary, generate_canary, scan_application_logs)
from scripts.tools.staging_secure_io import emit_json_receipt
# One source for the sandbox: Gate D's compose reader and translator, which
# refuses a model that keeps capabilities or privilege escalation.
from scripts.verification.verify_container_runtime import (
    _compose_run_arguments, _compose_service_model, _wait_healthy)

RECEIPT_SCHEMA_VERSION = 5
# The disposable fault runtime holds the compute lock this long.  It must exceed the application's queue wait, which the
# drill observes rather than restates: the queued chart has to be refused before the holder returns.
HOLD_SECONDS = 30
WORKER_REPLACEMENT_WAIT_SECONDS = 30
DRILL_LABEL = "org.classical-astrology.drill=gate-d"
# The API-only service: compose.yaml without the frontend-release overlay.
DRILL_COMPOSE_FILES = ("deploy/compose.yaml",)
# The drills need no frontend release: an empty requirement serves the API only.
# These follow (and so override) whatever environment compose declares.
DRILL_EXPECTED_HOST = "image-drill.invalid"
DRILL_ENVIRONMENT = (
    f"CLASSICAL_ASTROLOGY_EXPECTED_HOST={DRILL_EXPECTED_HOST}", "CLASSICAL_ASTROLOGY_REQUIRE_FRONTEND_RELEASE=")
ROOT = Path(__file__).resolve().parents[2]
CONTAINER_PYTHON = "/opt/venv/bin/python"
CONTAINER_APP_DIR = "/app/backend"
CONTAINER_PORT = 8000


class DrillResult(str, Enum):
    """A drill either observed the bounded behaviour, observed a violation, or could not reach the case; only ``passed``
    counts toward Gate D."""
    PASSED = "passed"
    FAILED = "failed"
    NOT_OBSERVED = "not_observed"


class Where(str, Enum):
    DISPOSABLE_TWIN = "disposable_twin_of_image"
    DISPOSABLE_FAULT_RUNTIME = "disposable_fault_runtime_of_image"
    DISPOSABLE_OOM_RUNTIME = "disposable_oom_runtime_of_image"


DRILL_LOCATIONS = {
    "worker_restart": Where.DISPOSABLE_TWIN, "timeout": Where.DISPOSABLE_FAULT_RUNTIME,
    "unexpected_error": Where.DISPOSABLE_FAULT_RUNTIME, "tmpfs_full": Where.DISPOSABLE_FAULT_RUNTIME,
    "oom": Where.DISPOSABLE_OOM_RUNTIME}
DRILLS = tuple(DRILL_LOCATIONS)


def _drill(result: DrillResult, **observation: Any) -> dict[str, Any]:
    return {"result": DrillResult(result).value, "observation": observation}


# Synthetic, built on the canary's random year and longitude.  The capacity payload asks for rise／set searches on a
# date-only chart at 66°N, which costs about a second of Swiss work per chart (2026-10-05, Apple Silicon): long enough
# that a worker is busy when the worker drill kills it.
FAULT_SECOND_ALLOCATE = 57
FAULT_SECOND_RAISE = 58
FAULT_SECOND_HOLD = 59


FAULT_FREE_SECOND = 17
FAULT_SECONDS = frozenset({FAULT_SECOND_ALLOCATE, FAULT_SECOND_RAISE, FAULT_SECOND_HOLD})


def drill_payloads(canary: Canary) -> dict[str, dict[str, Any]]:
    # The canary passed in may be derived from a fault payload (scan_canary), so the ordinary chart's second is set
    # explicitly: an ordinary chart must never select a fault.
    base = json.loads(canary.payload_bytes)
    base["datetime"]["second"] = FAULT_FREE_SECOND
    capacity = json.loads(canary.payload_bytes)
    capacity["birth_time_precision"] = "date_only"
    capacity["datetime"].update({"hour": 0, "minute": 0, "second": 0})
    capacity["location"]["latitude"] = 66.0
    capacity["options"] = {"include_rise_set_transits": True}
    raising, holding = json.loads(canary.payload_bytes), json.loads(canary.payload_bytes)
    allocating = json.loads(canary.payload_bytes)
    raising["datetime"]["second"] = FAULT_SECOND_RAISE
    holding["datetime"]["second"] = FAULT_SECOND_HOLD
    allocating["datetime"]["second"] = FAULT_SECOND_ALLOCATE
    return {"ordinary": base, "capacity": capacity, "raise": raising, "hold": holding, "allocate": allocating}


def scan_canary(canary: Canary) -> Canary:
    return reduce(derive_canary, drill_payloads(canary).values(), canary)


# Every program below runs with the image's Python (or, in tests, the local one) and reads one JSON object on stdin.
# None takes a value on argv except the fault harness, whose two arguments are the hold time and the marker.
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

# Fills each root with zero blocks until ENOSPC (or, in the local stand-in, until `fill_limit_bytes`, which is
# `not_observed`), sends the failing and an ordinary chart while full, then removes the filler.
TMPFS_FULL_PROBE = _PROBE_PRELUDE + r'''
import errno
fillers, reasons = [], []
for root in d.get("fill_roots", ["/tmp", "/dev/shm"]):
    path, written, reason = os.path.join(root, "drill-fill-%d" % os.getpid()), 0, None
    fillers.append(path)
    try:
        with open(path, "wb") as handle:
            while True:
                if d.get("fill_limit_bytes") and written >= d["fill_limit_bytes"]: reason = "limit"; break
                handle.write(bytes(1 << 20)); handle.flush(); os.fsync(handle.fileno()); written += 1 << 20
    except OSError as error:
        reason = "enospc" if error.errno == errno.ENOSPC else "oserror"
    reasons.append(reason)
failing = req("/api/chart", d["raise"])
ordinary = req("/api/chart", d["ordinary"])
health = req("/api/health")
for path in fillers:
    try: os.unlink(path)
    except OSError: pass
print(json.dumps({"full_reasons": reasons, "failing": failing, "ordinary": ordinary, "health": health}))
'''

# Reads the container's cgroup v2 OOM-kill count around one allocating chart; the restarting parent brings the
# application back.  Without a cgroup nothing is allocated.
OOM_PROBE = _PROBE_PRELUDE + r'''
def oom_kills():
    try:
        with open("/sys/fs/cgroup/memory.events") as handle:
            return int(dict(line.split() for line in handle)["oom_kill"])
    except (OSError, KeyError, ValueError): return None
before = oom_kills()
if before is None:
    print(json.dumps({"cgroup": False})); sys.exit(0)
allocating = req("/api/chart", d["allocate"], timeout=120)
started, health = time.monotonic(), {"status": 0}
while time.monotonic() - started < d["replacement_wait_seconds"] * 2:
    health = req("/api/health", timeout=5)
    if health["status"] == 200: break
    time.sleep(0.5)
after = req("/api/chart", d["ordinary"])
print(json.dumps({"cgroup": True, "oom_kills_before": before, "oom_kills_after": oom_kills(),
                  "allocating": allocating, "health": health, "after": after}))
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

# Every regular file under the roots, read whole in 1 MiB chunks that overlap by the longest fragment less one byte,
# so a fragment split across two reads is still found; a file past the byte bound is counted unreadable, never clean.
# The fragments are counted, never printed.  Runs as the
# container's own user after the drills, so it reads what the application could have left there.
TMPFS_SCAN = r'''
import json, os, sys
d = json.load(sys.stdin)
fragments = [f.encode() for f in d["fragments"]]
bound = d.get("max_file_bytes", 256 * 1024 * 1024)
overlap = max([len(f) for f in fragments] + [1]) - 1
files = matches = unreadable = 0
for root in d.get("roots", ["/tmp", "/dev/shm"]):
    for directory, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(directory, name)
            if os.path.islink(path) or not os.path.isfile(path): continue
            found, total, tail = set(), 0, b""
            try:
                with open(path, "rb") as handle:
                    while total <= bound:
                        chunk = handle.read(1024 * 1024)
                        if not chunk: break
                        total += len(chunk)
                        window = tail + chunk
                        found.update(i for i, fragment in enumerate(fragments) if fragment in window)
                        tail = window[-overlap:] if overlap else b""
            except OSError:
                unreadable += 1; continue
            if total > bound:
                unreadable += 1; continue
            files += 1
            matches += len(found)
print(json.dumps({"files_read": files, "unreadable": unreadable, "match_count": matches}))
'''


def tmpfs_sink(observed: dict[str, Any]) -> dict[str, Any]:
    """The receipt entry of one container's tmpfs scan; a file it could not read counts as a match."""
    unreadable = int(observed.get("unreadable", 1))
    return {"sink_role": "disposable_container_tmpfs", "match_count": int(observed.get("match_count", 1)) + unreadable,
            "files_read": int(observed.get("files_read", 0)), "unreadable": unreadable,
            "disposition": "observed_activity"}


# The fault runtime: the exact image's application, one worker, with one function replaced.  The replacement is selected
# by the chart's `second` (58 raises with the marker and the request in the message, 59 holds the compute lock); every
# other chart runs the real computation.
FAULT_HARNESS = r'''
import sys, time
hold_seconds, marker, port, app_dir = float(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4]
sys.path.insert(0, app_dir)
import uvicorn
from app import main
real = main._compute_chart_locked
def drilled(req):
    second = int(req.datetime.second)
    if second == %(allocate)d:
        # Only under a numeric cgroup memory cap, and never past twice that cap: outside a capped container
        # (a developer's host) the fault refuses instead of allocating.
        try:
            with open("/sys/fs/cgroup/memory.max") as handle: cap = int(handle.read().strip())
        except (OSError, ValueError):
            raise RuntimeError("drill allocation refused: no cgroup memory cap")
        blocks = []
        for _ in range(2 * cap // (64 << 20) + 1): blocks.append(b"\x01" * (64 << 20))
        raise RuntimeError("drill allocation survived its cap")
    if second == %(raise)d:
        raise RuntimeError("drill fault %%s %%r" %% (marker, req))
    if second == %(hold)d:
        time.sleep(hold_seconds)
    return real(req)
main._compute_chart_locked = drilled
uvicorn.run(main.create_app, factory=True, host="127.0.0.1", port=port, http="h11", loop="asyncio",
            ws="none", access_log=False)
''' % {"raise": FAULT_SECOND_RAISE, "hold": FAULT_SECOND_HOLD, "allocate": FAULT_SECOND_ALLOCATE}

# The OOM runtime's parent stays small, so the cgroup OOM killer picks the allocating child, and restarts the child
# whenever it dies.  It prints only the child's exit status.
OOM_PARENT = r'''
import subprocess, sys, time
while True:
    status = subprocess.call([sys.executable, "-c", sys.argv[1], *sys.argv[2:]])
    print("drill child exited %d" % status, file=sys.stderr, flush=True)
    time.sleep(0.5)
'''


def evaluate_worker_restart(observed: dict[str, Any]) -> dict:
    if not observed.get("supervisor_found"): return _drill(DrillResult.NOT_OBSERVED, reason="supervisor_not_found")
    health, after = observed.get("health") or {}, observed.get("after") or {}
    passed = (observed.get("workers_before", 0) >= 2 and observed.get("replaced") is True
              and observed.get("workers_after") == observed.get("workers_before")
              and health.get("status") == 200 and after.get("status") == 200 and not observed.get("inflight_echo"))
    return _drill(DrillResult.PASSED if passed else DrillResult.FAILED, **{
        key: observed.get(key) for key in (
            "workers_before", "workers_after", "victim_was_busy", "replaced", "replacement_seconds",
            "inflight_statuses")}, health_status=health.get("status"), chart_after_status=after.get("status"))


def evaluate_timeout(observed: dict[str, Any]) -> dict:
    holder, queued = observed.get("holder") or {}, observed.get("queued") or {}
    refused = (queued.get("status") == 503 and queued.get("code") == "compute_capacity_exhausted"
               and bool(queued.get("retry_after")) and not queued.get("echo"))
    # Refused after it had queued (not at admission) and before the holder returned: the wait itself was bounded.
    bounded = (refused and holder.get("status") == 200
               and 2.0 <= queued.get("seconds", 0) < holder.get("seconds", 0) - 2.0)
    return _drill(DrillResult.PASSED if bounded else DrillResult.FAILED,
                  holder_status=holder.get("status"), holder_seconds=holder.get("seconds"),
                  queued_status=queued.get("status"), queued_code=queued.get("code"),
                  queued_seconds=queued.get("seconds"), queued_retry_after=queued.get("retry_after"))


def evaluate_tmpfs_full(observed: dict[str, Any]) -> dict:
    reasons = observed.get("full_reasons") or []
    failing, ordinary, health = (observed.get(key) or {} for key in ("failing", "ordinary", "health"))
    if not reasons or any(reason != "enospc" for reason in reasons):
        return _drill(DrillResult.NOT_OBSERVED, reason="tmpfs_not_full", full_reasons=reasons)
    passed = (failing.get("status") == 500 and failing.get("code") == "internal_server_error"
              and not failing.get("echo") and ordinary.get("status") == 200 and health.get("status") == 200)
    return _drill(DrillResult.PASSED if passed else DrillResult.FAILED, full_reasons=reasons,
                  failing_status=failing.get("status"), failing_code=failing.get("code"),
                  failing_echoed_canary=failing.get("echo"), ordinary_status=ordinary.get("status"),
                  health_status=health.get("status"))


def evaluate_oom(observed: dict[str, Any]) -> dict:
    if not observed.get("cgroup"): return _drill(DrillResult.NOT_OBSERVED, reason="no_cgroup_memory_events")
    allocating, health, after = (observed.get(key) or {} for key in ("allocating", "health", "after"))
    killed = (observed.get("oom_kills_after") or 0) > (observed.get("oom_kills_before") or 0)
    passed = (killed and not allocating.get("echo") and allocating.get("status") != 200
              and health.get("status") == 200 and after.get("status") == 200)
    return _drill(DrillResult.PASSED if passed else DrillResult.FAILED,
                  oom_kills_before=observed.get("oom_kills_before"), oom_kills_after=observed.get("oom_kills_after"),
                  allocating_status=allocating.get("status"), allocating_echoed_canary=allocating.get("echo"),
                  health_status=health.get("status"), chart_after_status=after.get("status"))


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
        """A context manager yielding a handle with `probe(program, payload)`, `log_sink(canary)` and
        `tmpfs_sink(canary)`."""
        ...


def _probe_input(canary: Canary, *, host: str, port: int, **extra: Any) -> dict[str, Any]:
    payloads = drill_payloads(canary)
    return {"host": host, "port": port, "marker": canary.marker, "fragments": list(canary.sensitive_fragments),
            **{name: json.dumps(payload, separators=(",", ":")) for name, payload in payloads.items()},
            "hold_seconds": HOLD_SECONDS, "replacement_wait_seconds": WORKER_REPLACEMENT_WAIT_SECONDS, **extra}


def run_disposable_drills(runtime: Runtime, canary: Canary) -> tuple[dict[str, dict], list[dict]]:
    """worker_restart in a twin; timeout, unexpected_error and tmpfs_full in the fault runtime; oom in its own."""
    drills: dict[str, dict] = {}
    sinks: list[dict] = []
    try:
        with runtime.disposable(Where.DISPOSABLE_TWIN, canary) as twin:
            drills["worker_restart"] = evaluate_worker_restart(twin.probe(WORKER_RESTART_PROBE, {}))
            sinks.append(twin.log_sink(canary))
            sinks.append(twin.tmpfs_sink(canary))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        drills["worker_restart"] = _drill(DrillResult.NOT_OBSERVED, reason=f"twin: {type(error).__name__}")
    try:
        with runtime.disposable(Where.DISPOSABLE_FAULT_RUNTIME, canary) as faulty:
            drills["timeout"] = evaluate_timeout(faulty.probe(TIMEOUT_PROBE, {}))
            drills["unexpected_error"] = evaluate_unexpected_error(faulty.probe(UNEXPECTED_ERROR_PROBE, {}))
            drills["tmpfs_full"] = evaluate_tmpfs_full(faulty.probe(TMPFS_FULL_PROBE, {}))
            sinks.append(faulty.log_sink(canary))
            sinks.append(faulty.tmpfs_sink(canary))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        for name in ("timeout", "unexpected_error", "tmpfs_full"):
            drills.setdefault(name, _drill(DrillResult.NOT_OBSERVED, reason=f"fault runtime: {type(error).__name__}"))
    try:
        with runtime.disposable(Where.DISPOSABLE_OOM_RUNTIME, canary) as starved:
            drills["oom"] = evaluate_oom(starved.probe(OOM_PROBE, {}))
            sinks.append(starved.log_sink(canary))
            sinks.append(starved.tmpfs_sink(canary))
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        drills["oom"] = _drill(DrillResult.NOT_OBSERVED, reason=f"oom runtime: {type(error).__name__}")
    for sink in sinks:
        sink.setdefault("sink_role", "disposable_container_docker_log_stream")
        if sink["sink_role"] == "exact_container_docker_log_stream":
            sink["sink_role"] = "disposable_container_docker_log_stream"
    return drills, sinks


def _docker(*arguments: str, stdin: str | None = None, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *arguments], input=stdin, capture_output=True, text=True,
                          check=False, timeout=timeout)


class _DockerDisposable:
    def __init__(self, container: str, probe_input: dict[str, Any]) -> None:
        self.container, self.probe_input = container, probe_input

    def probe(self, program: str, payload: dict[str, Any]) -> dict[str, Any]:
        completed = _docker("exec", "--interactive", self.container, CONTAINER_PYTHON, "-c", program,
                            stdin=json.dumps({**self.probe_input, **payload}), timeout=HOLD_SECONDS + 180)
        if completed.returncode != 0: raise RuntimeError(f"drill probe exited {completed.returncode}")
        return json.loads(completed.stdout)

    def log_sink(self, canary: Canary) -> dict[str, Any]:
        return scan_application_logs(canary, self.container, since=0.0)

    def tmpfs_sink(self, canary: Canary) -> dict[str, Any]:
        return tmpfs_sink(self.probe(TMPFS_SCAN, {"roots": ["/tmp", "/dev/shm"]}))


class ImageRuntime:
    """Disposable containers of one exact image, with the run settings of `source_root`'s compose (Gate D's: the image's
    revision) and no network.

    The reference is resolved to an image ID once; every container runs that ID and must report it."""
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
            "--network", "none", "--label", DRILL_LABEL]
        for item in DRILL_ENVIRONMENT:
            arguments += ["--env", item]
        fault = (str(HOLD_SECONDS), canary.marker, str(CONTAINER_PORT), CONTAINER_APP_DIR)
        if kind is Where.DISPOSABLE_FAULT_RUNTIME:
            arguments += ["--entrypoint", CONTAINER_PYTHON, self.image, "-c", FAULT_HARNESS, *fault]
        elif kind is Where.DISPOSABLE_OOM_RUNTIME:
            arguments += ["--entrypoint", CONTAINER_PYTHON, self.image, "-c", OOM_PARENT, FAULT_HARNESS, *fault]
        else:
            arguments.append(self.image)   # the image's own entrypoint and command
        started = _docker(*arguments)
        container = started.stdout.strip()
        if started.returncode != 0 or not container: raise RuntimeError("disposable container did not start")
        try:
            _wait_healthy(container)
            inspection = json.loads(_docker("inspect", container).stdout)[0]
            host_config = inspection.get("HostConfig") or {}
            if (host_config.get("NetworkMode") != "none" or host_config.get("PortBindings")
                    or inspection.get("Image") != self.image):
                raise RuntimeError("disposable container is not an unexposed container of the image")
            yield _DockerDisposable(container, _probe_input(canary, host=DRILL_EXPECTED_HOST, port=CONTAINER_PORT))
        finally:
            _docker("rm", "--force", container)


def run_image_drills(runtime: Runtime, image: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the five drills and search every disposable log stream for the canary; `image` is the reference and the ID
    the containers ran."""
    canary = scan_canary(generate_canary())
    drills, sinks = run_disposable_drills(runtime, canary)
    for name, drill in drills.items():
        drill["where"] = DRILL_LOCATIONS[name].value
    matches = sum(sink["match_count"] for sink in sinks)
    # A log stream and a tmpfs scan for each disposable container.
    privacy = "pass" if matches == 0 and len(sinks) == 2 * len(set(DRILL_LOCATIONS.values())) else "fail"
    passed = all(drills[name]["result"] == DrillResult.PASSED.value for name in DRILLS)
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION, "image": image, "drills": {name: drills[name] for name in DRILLS},
        "privacy_canary": {"result": privacy, "total_match_count": matches, "sinks": sinks},
        "result": "pass" if passed and privacy == "pass" else "fail"}


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


if __name__ == "__main__": main()
