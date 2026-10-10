"""The hosted application's own request bounds: media type, body size and
framing, the body deadline, the order of the request boundaries, compute
admission, the expected host and the container's process budget.

The pool isolation, the compute queue and the wire-level proofs (among them
the total body deadline against a trickled body) are in
tests/backend/test_request_capacity.py, tests/backend/test_compute_queue.py
and tests/integration/test_hosted_live_server.py.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]


def _hosted_application(**settings):
    from app.main import create_app
    from app.settings import AppSettings

    return create_app(AppSettings(**settings))


def _scope(*headers: tuple[bytes, bytes]) -> dict:
    return {"type": "http", "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/api/chart", "raw_path": b"/api/chart", "query_string": b"",
            "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
            "headers": list(headers), "state": {}}


JSON = (b"content-type", b"application/json")


def _drive(application, scope: dict, messages) -> tuple[list[dict], bool]:
    """Run one ASGI call with `messages` as the receive sequence; a class is
    wrapped around a downstream application that records being called."""
    sent: list[dict] = []
    called = False

    async def downstream_marker(*_args):
        nonlocal called
        called = True

    iterator = iter(messages)

    async def receive():
        return next(iterator)

    async def send(message):
        sent.append(message)

    asyncio.run(application(downstream_marker)(scope, receive, send) if isinstance(application, type)
                else application(scope, receive, send))
    return sent, called


def _refusal(sent: list[dict]) -> tuple[int, str]:
    start = next(item for item in sent if item["type"] == "http.response.start")
    body = [item for item in sent if item["type"] == "http.response.body"][-1]
    return start["status"], json.loads(body["body"])["detail"]["code"]


@pytest.mark.parametrize(("content_type", "status"), (
    (None, 415), ("text/plain", 415), ("application/json; charset=utf-8; charset=utf-8", 415),
    ("application/json; charset=latin-1", 415), ("application/json; charset=UTF-8", 200),
    # SEC-R2-05: a quoted value must be quoted on both sides.
    ('application/json; charset="utf-8"', 200), ('application/json; charset="utf-8', 415),
    ('application/json; charset=utf-8"', 415), ('application/json; charset=""utf-8""', 415),
))
def test_the_chart_takes_only_utf8_json(content_type, status):
    from tests.backend import synthetic_birth_payload

    headers = {} if content_type is None else {"Content-Type": content_type}
    body = json.dumps(synthetic_birth_payload()).encode() if status == 200 else b"{}"
    with TestClient(_hosted_application()) as client:
        response = client.post("/api/chart", content=body, headers=headers)
    assert response.status_code == status
    if status == 415:
        assert response.json()["detail"]["code"] == "unsupported_media_type"


@pytest.mark.parametrize(("path", "body"), (
    ("/api/chart", b"{" + b" " * (16 * 1024) + b"}"),
    ("/api/places/search", b'{"query":"' + b"x" * (16 * 1024) + b'"}'),
))
def test_hosted_endpoints_reject_known_oversize_before_schema_parse(path, body):
    with TestClient(_hosted_application()) as client:
        response = client.post(path, content=body, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "request_body_too_large"


@pytest.mark.parametrize(("headers", "messages", "expected"), (
    # A small declared length does not let a chunked body past the ceiling.
    ((JSON, (b"content-length", b"2")),
     ({"type": "http.request", "body": b"x" * 10_000, "more_body": True},
      {"type": "http.request", "body": b"x" * 7_000, "more_body": False}),
     (413, "request_body_too_large")),
    # A known oversized length is refused before anything is received.
    ((JSON, (b"content-length", b"16385")), (), (413, "request_body_too_large")),
    ((JSON, (b"content-length", b"2"), (b"content-length", b"2")),
     ({"type": "http.request", "body": b"{}", "more_body": False},),
     (400, "invalid_content_length")),
))
def test_the_body_boundary_refuses_before_the_application_runs(headers, messages, expected):
    from app.request_limits import ChartRequestBoundary

    sent, called = _drive(ChartRequestBoundary, _scope(*headers), messages)
    assert not called and _refusal(sent) == expected


def test_streamed_body_limit_survives_the_assembled_fastapi_stack():
    sent, _ = _drive(_hosted_application(), _scope(JSON), (
        {"type": "http.request", "body": b"x" * 10_000, "more_body": True},
        {"type": "http.request", "body": b"x" * 7_000, "more_body": False}))
    assert [item["status"] for item in sent if item["type"] == "http.response.start"] == [413]
    assert _refusal(sent) == (413, "request_body_too_large")


def test_capacity_boundary_wraps_unsupported_api_method_boundary():
    from app.request_limits import ApiMethodBoundary, ChartRequestBoundary, RequestCapacityBoundary

    application = _hosted_application()
    application.middleware_stack = application.build_middleware_stack()
    current, seen = application.middleware_stack, []
    while hasattr(current, "app"):
        if isinstance(current, (ChartRequestBoundary, RequestCapacityBoundary, ApiMethodBoundary)):
            seen.append(type(current))
        current = current.app
    # Outermost first.  Header-decidable refusals and the bounded body come
    # before any admission slot; only a complete body is charged to a pool
    # (API-12／ASTRO-41／OPS-05).  The body phase is bounded by size and by a
    # total deadline, not by count: that is the edge's `limit_conn`.
    assert seen == [ChartRequestBoundary, RequestCapacityBoundary, ApiMethodBoundary]


def test_capacity_boundary_refuses_a_second_active_compute_request():
    from app.request_limits import RequestCapacityBoundary

    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def downstream(_scope, _receive, send):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    boundary = RequestCapacityBoundary(downstream, max_concurrent=2, max_compute_concurrent=1)

    async def one():
        sent = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        await boundary({"type": "http", "method": "POST", "path": "/api/chart"}, receive, send)
        return sent

    async def exercise():
        first = asyncio.create_task(one())
        await entered.wait()
        second = await one()
        release.set()
        await first
        return second

    assert _refusal(asyncio.run(exercise())) == (503, "compute_capacity_exhausted")


def test_request_boundary_preserves_client_disconnect_and_answers_once():
    """A client gone before its body is complete gets no fabricated response
    (the boundary used to forward the disconnect and log a server 500, AR-2);
    a late oversize after the application answered starts no second response."""
    from app.request_limits import ChartRequestBoundary, client_disconnected

    observed = []

    async def reader(_scope, receive, _send):
        observed.append(await receive())

    async def receive_disconnect():
        return {"type": "http.disconnect"}

    async def no_send(_message):
        raise AssertionError("disconnect must not fabricate a response")

    scope = _scope(JSON)
    asyncio.run(ChartRequestBoundary(reader)(scope, receive_disconnect, no_send))
    assert observed == [] and client_disconnected(scope)

    async def answers_first(_scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    sent, _ = _drive(lambda scope, receive, send: ChartRequestBoundary(
        answers_first, max_body_bytes=16)(scope, receive, send), _scope(JSON),
        ({"type": "http.request", "body": b"x" * 17, "more_body": False},))
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert [start["status"] for start in starts] == [413]


def test_a_request_for_an_undeclared_host_is_refused_before_any_budget():
    """Expected-host checking catches exposure mistakes; it is not authorization."""
    from tests.backend import chart_payload

    client = TestClient(_hosted_application(expected_host="alpha.example.invalid"))
    payload = chart_payload(options={"house_system": "W"})
    for host, expected in (("alpha.example.invalid", 200), ("alpha.example.invalid:443", 200),
                           ("ALPHA.example.invalid:80", 200),
                           ("172.31.240.2", 404), ("scanner.example", 404),
                           # SEC-R2-01: the text after the colon is part of the
                           # host; only the two default ports may follow it.
                           ("alpha.example.invalid:evil", 404), ("alpha.example.invalid:", 404),
                           ("alpha.example.invalid:8000", 404), ("alpha.example.invalid:443:1", 404),
                           ("alpha.example.invalid.", 404)):
        assert client.post("/api/chart", json=payload, headers={"host": host}).status_code == expected, host
    # Undeclared means unchecked: the same module runs in development.
    assert TestClient(_hosted_application()).post(
        "/api/chart", json=payload, headers={"host": "anything.example"}).status_code == 200


def test_every_post_api_route_is_declared_to_both_request_boundaries():
    """The registered routes, `ApiMethodBoundary`'s route table and
    `_BOUNDED_JSON_PATHS` (body ceiling and compute pool) are separate literals;
    a POST route missing from one of them is a defect."""
    from app.request_limits import _BOUNDED_JSON_PATHS
    from scripts.tools.closed_set import require_closed_set

    application = _hosted_application()
    registered: dict[str, frozenset[str]] = {}
    for route in application.routes:
        path, methods = getattr(route, "path", None), getattr(route, "methods", None)
        if isinstance(path, str) and path.startswith("/api/") and methods:
            # HEAD is served wherever GET is (W4-A, API-03) and may be its own route.
            registered[path] = registered.get(path, frozenset()) | frozenset(methods)
    assert registered, "no /api/ routes were discovered"
    declared = next(dict(middleware.kwargs["route_methods"]) for middleware in application.user_middleware
                    if middleware.cls.__name__ == "ApiMethodBoundary")
    require_closed_set(registered.keys(), declared.keys(), role="ApiMethodBoundary route universe")
    assert declared == registered
    require_closed_set({path for path, methods in registered.items() if "POST" in methods},
                       _BOUNDED_JSON_PATHS, role="bounded JSON POST universe")


def test_e014_pids_limit_covers_the_threads_and_the_declared_request_capacity():
    import anyio
    import anyio.to_thread

    from app.request_limits import (
        MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER, MAX_HOSTED_REQUESTS_PER_WORKER,
        MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER,
    )

    compose = (ROOT / "deploy/compose.yaml").read_text(encoding="utf-8")
    limit = int(re.search(r"^\s*pids_limit:\s*(\d+)\s*$", compose, re.MULTILINE).group(1))
    workers = int(re.search(r'"--workers",\s*"(\d+)"',
                            (ROOT / "deploy/Dockerfile").read_text(encoding="utf-8")).group(1))

    async def pool_size() -> int:
        return int(anyio.to_thread.current_default_thread_limiter().total_tokens)

    # main thread per worker, supervisor, resource tracker, init, healthcheck
    overhead = workers + 4
    assert workers * anyio.run(pool_size) + overhead <= limit
    declared = (MAX_HOSTED_REQUESTS_PER_WORKER + MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER
                + MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER)
    assert workers * (declared + 1) + overhead <= limit
