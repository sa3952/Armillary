"""Real uvicorn processes: refusals, privacy of process output, admission timing.

TestClient hands the application a whole body in one message and cannot hold a
slot open, so these claims are made against a real server over raw sockets.
They say nothing about NGINX, which buffers bodies in the deployed path.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.error import URLError

from tests.backend import http_request as _request
from tests.backend import synthetic_birth_payload as _payload
from tests.backend import unused_local_port


BACKEND_ROOT = str(Path(__file__).resolve().parents[2] / "backend")
CANARY = "HOSTED_PRIVACY_CANARY_842761"
TRACEBACK = "Traceback (most recent call last)"


@contextmanager
def _hosted_server(*setup: str, scripted: bool = False, environment: dict[str, str] | None = None):
    """A ready server; `.output` holds its stdout+stderr after the block exits.

    By default it is the plain `uvicorn app.main:app` command the deployment
    runs; a scripted process runs `setup` lines before `create_app(AppSettings())`.
    `environment` adds process variables, as the deployment's compose file does.
    """

    port = unused_local_port()
    if scripted or setup:
        script = "\n".join((
            "import uvicorn",
            "from app import main, request_limits",
            "from app.settings import AppSettings",
            *setup,
            "application = main.create_app(AppSettings())",
            f"uvicorn.run(application, host='127.0.0.1', http='h11', port={port}, access_log=False)",
        ))
        command = [sys.executable, "-c", script]
    else:
        command = [
            sys.executable, "-m", "uvicorn", "app.main:app", "--http", "h11",
            "--host", "127.0.0.1", "--port", str(port), "--no-access-log",
        ]
    process = subprocess.Popen(
        command, cwd=BACKEND_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        env=None if environment is None else {**os.environ, **environment},
    )
    server = SimpleNamespace(port=port, url=f"http://127.0.0.1:{port}", output="")
    try:
        deadline = time.monotonic() + 20
        while True:
            if process.poll() is not None:
                raise AssertionError("hosted server stopped early:\n" + process.stdout.read())
            if time.monotonic() > deadline:
                raise AssertionError("hosted server startup timed out")
            try:
                status, health = _request(f"{server.url}/api/health")
                if status == 200:
                    health = json.loads(health)
                    assert health["status"] == "ok" and health["ready"] is True
                    break
            except URLError:
                pass
            time.sleep(0.05)
        yield server
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        server.output = process.stdout.read()


def _post(server, body: bytes, path: str = "/api/chart", content_type: str = "application/json"):
    return _request(f"{server.url}{path}", body=body, content_type=content_type)


def _raw_post(port: int, path: str, body: bytes, *, declared_length: int | None = None) -> socket.socket:
    """Send a request head and `body`; `declared_length` may promise more."""

    client = socket.create_connection(("127.0.0.1", port), timeout=20)
    length = len(body) if declared_length is None else declared_length
    client.sendall(
        f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
        f"Content-Length: {length}\r\nConnection: close\r\n\r\n".encode() + body
    )
    return client


def _read_raw_response(client: socket.socket) -> tuple[int, dict[str, str], bytes]:
    response = b""
    with client:
        while chunk := client.recv(65536):
            response += chunk
    if b"\r\n\r\n" not in response:
        raise AssertionError(f"no HTTP response: {response[:80]!r}")
    head, body = response.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(":")
        headers[name.strip().lower()] = value.strip()
    return int(lines[0].split()[1]), headers, body


def test_real_hosted_server_success_rejections_and_process_output_are_bounded():
    body = json.dumps(_payload()).encode()
    invalid_payload = _payload()
    invalid_payload["datetime"]["month"] = 13
    invalid_payload["location"][CANARY] = CANARY
    coordinate = "25.0337891"
    wrong_latitude = _payload()
    wrong_latitude["location"]["latitude"] = coordinate
    with _hosted_server() as server:
        success = _post(server, body)
        # Content-Length and chunked together, which normal HTTP clients normalize away.
        framing = socket.create_connection(("127.0.0.1", server.port), timeout=5)
        framing.sendall(
            b"POST /api/chart HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nTransfer-Encoding: chunked\r\n".encode()
            + f"Connection: close\r\n\r\n{len(body):x}\r\n".encode() + body + b"\r\n0\r\n\r\n"
        )
        conflicting_framing = _read_raw_response(framing)
        wrong_type = _post(server, CANARY.encode(), content_type="text/plain")
        malformed = _post(server, b'{"datetime":"' + CANARY.encode())
        invalid = _post(server, json.dumps(invalid_payload).encode())
        oversized = _post(server, CANARY.encode() + b"x" * (16 * 1024))
        string_coordinate = _post(server, json.dumps(wrong_latitude).encode())
        # NaN is not JSON text; the strict reader answers json_invalid (400).
        nonfinite = _post(server, json.dumps(_payload()).replace("22.9908", "NaN", 1).encode())
        trailing_slash = _post(server, CANARY.encode(), path="/api/chart/")
        future_child = _post(server, CANARY.encode(), path="/api/chart/future")
        not_found = [
            _request(f"{server.url}{path}")
            for path in ("/api/chartography", "/openapi.json", "/api/runtime-health")
        ]
    output = server.output

    assert success[0] == 200
    assert conflicting_framing[0] == 400
    assert json.loads(conflicting_framing[2])["detail"]["code"] == "conflicting_request_framing"
    assert wrong_type[0] == 415
    # 400 for a body the parser never read, 422 for one it did.
    assert malformed[0] == 400
    assert json.loads(malformed[1])["detail"]["code"] == "json_invalid"
    assert (invalid[0], oversized[0], string_coordinate[0], nonfinite[0]) == (422, 413, 422, 400)
    assert trailing_slash[0] == 404
    assert json.loads(trailing_slash[1])["detail"]["code"] == "unknown_api_path"
    assert [future_child[0], *(status for status, _ in not_found)] == [404] * 4
    assert CANARY not in malformed[1].decode()
    assert CANARY not in invalid[1].decode()
    assert coordinate not in string_coordinate[1].decode()
    assert "NaN" not in nonfinite[1].decode()
    for leaked in (CANARY, coordinate, '"POST /api/chart HTTP/', TRACEBACK):
        assert leaked not in output, leaked
    assert output.count('"route":"/api/chart"') == 8
    assert output.count('"route":"frontend_or_unmatched"') == 5


def test_real_hosted_server_logs_the_flagged_annual_route_under_its_label_without_its_input():
    """The deployment's command with the annual flag set: an annual answer and an
    annual refusal carrying a canary are two events of the annual label, and
    neither the canary nor the birth data reaches the process output."""

    annual = {"target_kind": "completed_years", "target_value": 2}
    success = {**_payload(), "annual": annual}
    invalid = {**_payload(), "annual": {**annual, CANARY: CANARY}}
    with _hosted_server(environment={"ARMILLARY_ENABLE_ANNUAL_ROUTE": "1"}) as server:
        answered = _post(server, json.dumps(success).encode(), path="/api/chart/annual")
        refused = _post(server, json.dumps(invalid).encode(), path="/api/chart/annual")
    output = server.output

    assert answered[0] == 200
    assert refused[0] == 422 and CANARY not in refused[1].decode()
    assert output.count('"route":"/api/chart/annual"') == 2
    assert '"route":"frontend_or_unmatched"' not in output
    birth = success["datetime"]
    for leaked in (CANARY, TRACEBACK, '"annual"', f'"year":{birth["year"]}', str(success["location"]["latitude"])):
        assert leaked not in output, leaked


def test_real_hosted_server_fuzzed_refusals_do_not_echo_or_log_the_input():
    """Canaries as values (a zone name, a text year), as keys (top level and next
    to an out-of-range latitude) and non-object JSON bodies, through the real
    process: the in-process tests cannot see what uvicorn itself prints."""

    canaries = [f"{CANARY}_{index:02d}" for index in range(16)]
    bodies = [b"{", b"[", b"null", b"true", b'"birth"', json.dumps({"birth": canaries[0]}).encode()]
    for index, canary in enumerate(canaries[1:], start=1):
        payload = _payload()
        target = index % 5
        if target == 0:
            payload["datetime"]["year"] = canary
        elif target == 1:
            payload["datetime"].update(month=2, day=30)
            payload["datetime"][canary] = canary
        elif target == 2:
            payload["location"]["latitude"] = 91
            payload["location"][canary] = canary
        elif target == 3:
            payload["timezone"]["iana_name"] = canary
        else:
            payload[canary] = [canary]
        bodies.append(json.dumps(payload).encode())
    with _hosted_server() as server:
        responses = [_post(server, body) for body in bodies]

    # 400 for a body the parser never read, 422 for one it did.
    assert all(status in (400, 422) for status, _ in responses)
    assert any(status == 400 for status, _ in responses)
    combined = b"\n".join(body for _, body in responses).decode()
    for canary in canaries:
        assert canary not in combined, canary
        assert canary not in server.output, canary
    for leaked in ('"POST /api/chart HTTP/', TRACEBACK):
        assert leaked not in server.output, leaked
    assert server.output.count('"route":"/api/chart"') == len(bodies)


def test_real_hosted_server_time_conversion_logs_only_its_route_label():
    """The helper's body is a birth date, time and zone: the process prints its
    route label and nothing it was asked, for an answer and for each refusal."""

    birth = {"year": 1974, "month": 9, "day": 30, "hour": 23, "minute": 30}
    bodies = [
        {"datetime": birth, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"}},
        {"datetime": birth, "timezone": {"mode": "iana", "iana_name": CANARY}},
        {"datetime": {**birth, "year": CANARY}, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"}},
        {"datetime": birth, "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"}, CANARY: CANARY},
        {"datetime": birth, "timezone": {"mode": "iana", "iana_name": "Europe/London"}},
        {"datetime": birth, "timezone": {"mode": "iana", "iana_name": "Asia/Urumqi"}},
    ]
    with _hosted_server() as server:
        responses = [
            _post(server, json.dumps(body).encode(), path="/api/time/convert") for body in bodies
        ]
        malformed = _post(server, b'{"datetime":"' + CANARY.encode(), path="/api/time/convert")

    assert [status for status, _ in responses] == [200, 422, 422, 422, 422, 422]
    assert json.loads(responses[0][1])["status"] == "repeated"
    assert malformed[0] == 400
    for _, body in [*responses[1:], malformed]:
        assert CANARY not in body.decode()
    for leaked in (CANARY, "1974-09-30", "23:30", "Asia/Taipei", "Europe/London",
                   '"POST /api/time/convert HTTP/', TRACEBACK):
        assert leaked not in server.output, leaked
    assert server.output.count('"route":"/api/time/convert"') == len(bodies) + 1


def test_real_hosted_server_unexpected_error_is_generic_and_not_logged():
    with _hosted_server(
        "def fail(_request):", f"    raise RuntimeError({CANARY!r})",
        "main._compute_chart_locked = fail",
    ) as server:
        status, body = _post(server, json.dumps(_payload()).encode())

    assert status == 500
    assert json.loads(body)["detail"]["code"] == "internal_server_error"
    assert CANARY not in body.decode()
    for leaked in (CANARY, '"POST /api/chart HTTP/', TRACEBACK):
        assert leaked not in server.output, leaked
    assert server.output.count('"route":"/api/chart"') == 1


def test_real_server_incomplete_bodies_do_not_hold_compute_slots():
    from app.request_limits import MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER

    body = json.dumps(_payload()).encode()
    held: list[socket.socket] = []
    with _hosted_server(scripted=True) as server:
        try:
            # Each connection sends its head and one byte of a body it never finishes.
            for _ in range(MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER):
                held.append(_raw_post(server.port, "/api/chart", body[:1], declared_length=len(body)))
            time.sleep(0.5)
            status, response_body = _post(server, body)
        finally:
            for client in held:
                client.close()

    assert status == 200, response_body[:300]
    assert TRACEBACK not in server.output


def test_real_server_ends_a_trickled_body_at_the_total_deadline():
    deadline = 1.5
    response = b""
    answered_after = None
    with _hosted_server(f"request_limits.REQUEST_BODY_DEADLINE_SECONDS = {deadline}") as server:
        client = _raw_post(server.port, "/api/chart", b"{", declared_length=4096)
        started = time.monotonic()
        client.settimeout(0.2)
        with client:
            while time.monotonic() - started < deadline + 4.0:
                try:
                    chunk = client.recv(65536)
                except TimeoutError:
                    # Nothing yet: one more byte, far inside any gap timeout.
                    try:
                        client.sendall(b" ")
                    except OSError:
                        break
                    continue
                except OSError:
                    break
                if answered_after is None:
                    answered_after = time.monotonic() - started
                if not chunk:
                    break
                response += chunk

    assert answered_after is not None, "a body trickled under the gap timeout was never refused"
    head, _, payload = response.partition(b"\r\n\r\n")
    assert head.split()[1:2] == [b"408"], head[:80]
    assert json.loads(payload)["detail"]["code"] == "request_body_read_timeout"
    assert deadline - 0.2 <= answered_after < deadline + 2.0, answered_after
    assert TRACEBACK not in server.output


def test_real_server_slow_place_searches_leave_health_and_assets_answerable():
    from app.request_limits import (
        MAX_HOSTED_REQUESTS_PER_WORKER,
        MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER,
        RETRY_AFTER_SECONDS,
    )

    body = json.dumps({"query": "taipei"}).encode()
    lookups: list[socket.socket] = []
    # Each admitted lookup holds a worker thread for four seconds, as one that
    # runs to the catalogue statement budget does.
    with _hosted_server(
        "import time",
        "from app.core import place_catalog",
        "def slow_search(self, **_arguments):",
        "    time.sleep(4.0)",
        "    return {'results': [], 'catalog': {}, 'query': {}, 'execution': {}}",
        "place_catalog.PlaceCatalog.search = slow_search",
    ) as server:
        try:
            # As many lookups as the general pool admits for everything else.
            for _ in range(MAX_HOSTED_REQUESTS_PER_WORKER):
                lookups.append(_raw_post(server.port, "/api/places/search", body))
            time.sleep(0.75)
            started = time.monotonic()
            health = _request(f"{server.url}/api/health", timeout=3)
            health_seconds = time.monotonic() - started
            page = _request(f"{server.url}/zh-TW/", timeout=3)
            answers = [_read_raw_response(client) for client in lookups]
        finally:
            for client in lookups:
                client.close()

    assert health[0] == 200, health[1][:200]
    assert json.loads(health[1])["status"] == "ok"
    assert health_seconds < 2.0, health_seconds
    assert page[0] == 200, page[1][:200]
    statuses = [status for status, _headers, _payload in answers]
    assert statuses.count(200) == MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER, statuses
    refused = [(headers, payload) for status, headers, payload in answers if status == 503]
    assert len(refused) == len(answers) - MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER
    for headers, payload in refused:
        assert headers.get("retry-after") == str(RETRY_AFTER_SECONDS)
        assert json.loads(payload)["detail"]["code"] == "request_capacity_exhausted"
    assert TRACEBACK not in server.output
