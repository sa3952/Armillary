#!/usr/bin/env python3
"""Container-local health probe that restarts its own container when it stays down.

Every run asks ``/api/health`` (process liveness) and ``/api/health/ready``
(the bundled ephemeris files present with their pinned digests; 503 otherwise).  Until a deep check has
passed once in this container, every ``DEEP_EVERY``-th run after that, and every
run that follows a failure, it also posts a synthetic chart and a place search
and requires HTTP 200 and the chart's full-ephemeris flag; no value is compared.
The consecutive-failure count lives in ``/tmp`` (the compose tmpfs, fresh on
every start).  After ``RESTART_THRESHOLD`` consecutive failures in a container
that was healthy once, PID 1 (docker-init) gets SIGTERM, the container exits and
Docker's ``unless-stopped`` policy starts it again; two runs later, a container
still alive (a stopped process ignores SIGTERM) has every process but PID 1
killed.  A container that never became healthy is left to the deploy's health
wait rather than restarted in a loop.  Notification is the external monitor's.

Load is not a fault.  A deep check answered with the application's busy
refusal (HTTP 503 ``compute_capacity_exhausted``, immediate or after the
bounded queue wait, or ``request_capacity_exhausted``) is *saturated*: it
neither counts as a failure nor resets the count, the probe exits 0, and every
following run is deep.  When the deep check has seen nothing but such refusals
for ``SATURATION_LIMIT_SECONDS``, the probe exits 1 while it lasts, so Docker
marks the container unhealthy for the operator to see; it never counts toward
a restart, because restarting under a flood only drops the requests in flight
and the flood is still there when the container is back.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

# The probe is about this container's own listener.  An ambient
# HTTP_PROXY (Docker injects the daemon's proxy settings into containers)
# would otherwise carry the loopback request to a proxy, and a proxy that
# answers with the expected body would make a dead listener look healthy.
_DIRECT_OPENER = build_opener(ProxyHandler({}))
BASE = "http://127.0.0.1:8000"
STATE = Path("/tmp/.container-health.json")
DEEP_EVERY = 10  # every 5 minutes at the image's 30 s interval
RESTART_THRESHOLD = 3
SATURATION_LIMIT_SECONDS = 10 * 60
# Liveness and readiness answer in milliseconds; when the listen backlog
# overflows under load a SYN is dropped and retried after 1 s, then 2 s, so
# 3.5 s still answers after one lost SYN instead of reading a busy listener as dead.
LIVENESS_TIMEOUT_SECONDS = 3.5
SATURATION_CODES = frozenset({"compute_capacity_exhausted", "request_capacity_exhausted", "place_search_timeout"})
# Longer than the application's 18 s queue-wait budget (request_limits.py), so a
# chart queued behind real work returns its 503 instead of timing the probe out.
CHART_TIMEOUT_SECONDS = 25.0
HEALTHY, FAILED, SATURATED = "healthy", "failed", "saturated"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
LIVENESS = {"status": "ok", "ready": True, "readiness_scope": "process_liveness_only"}
READINESS = {"status": "ready", "readiness_scope": "ephemeris_manifest"}
SYNTHETIC_CHART = {
    "birth_time_precision": "exact",
    "datetime": {"year": 2000, "month": 1, "day": 1, "hour": 12, "minute": 0, "second": 0},
    "location": {"altitude_m": 0, "latitude": 0, "longitude": 0,
                 "location_precision": "user_supplied_coordinates", "location_source": "manual",
                 "place_label": "synthetic-availability-probe", "source_record_id": None},
    "options": {},
    "timezone": {"iana_name": "UTC", "mode": "iana"},
}
SYNTHETIC_PLACE_SEARCH = {"query": "臺南", "country_code": "TW", "limit": 3}


class Saturated(Exception):
    """The application refused the probe as busy; neither healthy nor failed."""


def _refusal_code(error: HTTPError) -> object:
    try:
        return json.loads(error.read(MAX_RESPONSE_BYTES))["detail"]["code"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _request(path: str, body: object | None = None, timeout: float = LIVENESS_TIMEOUT_SECONDS) -> object:
    host = os.environ.get("CLASSICAL_ASTROLOGY_EXPECTED_HOST", "127.0.0.1").strip() or "127.0.0.1"
    headers = {"Accept": "application/json", "Host": host}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(BASE + path, data=data, headers=headers, method="GET" if data is None else "POST")
    try:
        with _DIRECT_OPENER.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise ValueError(f"{path} answered {response.status}")
            return json.loads(response.read(MAX_RESPONSE_BYTES))
    except HTTPError as error:
        if body is not None and error.code == 503 and _refusal_code(error) in SATURATION_CODES:
            raise Saturated(path) from None
        raise


def check(deep: bool) -> str:
    """Liveness and readiness, and with ``deep`` the synthetic chart and place search (status and flag only)."""
    try:
        if _request("/api/health") != LIVENESS:
            return FAILED
        if _request("/api/health/ready") != READINESS:
            return FAILED
        if deep:
            chart = _request("/api/chart", SYNTHETIC_CHART, timeout=CHART_TIMEOUT_SECONDS)
            provenance = (chart.get("calculation_dossier") or {}).get("provenance") or {}
            if provenance.get("all_core_calculation_sources_used_full_ephemeris") is not True:
                return FAILED
            _request("/api/places/search", SYNTHETIC_PLACE_SEARCH, timeout=8.0)
    except Saturated:
        return SATURATED
    except (OSError, URLError, ValueError, AttributeError):  # HTTPError and JSON errors included
        return FAILED
    return HEALTHY


_STATE_KEYS = ("runs", "failures", "deep_passed", "saturated_since")


def _read_state() -> dict[str, int]:
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        return {key: int(state.get(key, 0)) for key in _STATE_KEYS}
    except (OSError, ValueError, AttributeError, TypeError):
        return dict.fromkeys(_STATE_KEYS, 0)


def _write_state(state: dict[str, int]) -> bool:
    staged = STATE.with_suffix(".tmp")
    try:
        staged.write_text(json.dumps(state), encoding="utf-8")
        os.replace(staged, STATE)
    except OSError:
        return False
    return True


def _pid1_is_container_init() -> bool:
    """Only docker-init (tini) is signalled; under any other PID 1 (a test host) nothing is."""
    try:
        argv0 = Path("/proc/1/cmdline").read_bytes().split(b"\0", 1)[0]
    except OSError:
        return False
    return os.path.basename(argv0) in (b"docker-init", b"tini")


def restart(failures: int) -> None:
    if failures < RESTART_THRESHOLD or not _pid1_is_container_init():
        return
    try:
        if failures >= RESTART_THRESHOLD + 2:
            os.kill(-1, signal.SIGKILL)  # every process but PID 1 and this probe
        else:
            os.kill(1, signal.SIGTERM)  # docker-init forwards it to the application
    except OSError:
        pass


def _now() -> int:
    # CLOCK_MONOTONIC is per boot, not per process, so successive probes share it.
    return max(1, int(time.monotonic()))


def main() -> int:
    state = _read_state()
    state["runs"] += 1
    deep = (not state["deep_passed"] or state["failures"] > 0 or state["saturated_since"] > 0
            or state["runs"] % DEEP_EVERY == 0)
    outcome = check(deep)
    saturated_too_long = False
    if outcome == SATURATED:
        now = _now()
        if not state["saturated_since"]:
            state["saturated_since"] = now
        # Ten minutes of nothing but busy refusals: marked, never a failure.
        saturated_too_long = now - state["saturated_since"] >= SATURATION_LIMIT_SECONDS
    elif outcome == HEALTHY:
        state["failures"] = 0
        state["deep_passed"] = 1
        state["saturated_since"] = 0
    else:
        state["failures"] += 1
        state["saturated_since"] = 0
    if not _write_state(state) and state["deep_passed"]:
        # The state lives on the /tmp tmpfs: when it cannot be written (a full
        # /tmp) every later run would be a first run and never restart.  A
        # restart empties the tmpfs.
        restart(RESTART_THRESHOLD)
        return 1
    if outcome == FAILED and state["deep_passed"]:
        restart(state["failures"])
    return 1 if outcome == FAILED or saturated_too_long else 0


if __name__ == "__main__":
    sys.exit(main())
