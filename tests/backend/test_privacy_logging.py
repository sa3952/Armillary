"""Executable privacy controls, checked with recognizable canaries.

Passing requires more than "no body logger today": the application emits only a
closed structured event schema, and successful, rejected, malformed and
unexpected-error paths never leak the canaries.
"""

from __future__ import annotations

import asyncio
import builtins
from contextlib import contextmanager
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.error import URLError

from fastapi.testclient import TestClient
import pytest
import swisseph as swe
from tests.backend import http_request as _request
from tests.backend import minimal_chart_payload
from tests.backend import unused_local_port as _unused_local_port


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
CANARY_TEXT = "PRIVACY_CANARY_DO_NOT_LOG_6C_734991"
CANARY_LATITUDE = 23.456789
CANARY_LONGITUDE = 123.456789

EXPECTED_EVENT_FIELDS = {
    "event_schema_version", "event", "request_id", "route", "method",
    "status_code", "duration_bucket", "request_size_bucket", "outcome",
    "error_code", "failure_class",
}
HEALTH_SCOPE = {"type": "http", "method": "GET", "path": "/api/health", "headers": []}


def _payload() -> dict:
    return minimal_chart_payload(
        year=1997, month=8, day=17, hour=9, minute=42,
        latitude=CANARY_LATITUDE, longitude=CANARY_LONGITUDE, altitude_m=87,
    )


def _event(**overrides) -> dict:
    from app.privacy_logging import build_request_event

    return build_request_event(**{
        "request_id": "0123456789abcdef0123456789abcdef", "method": "POST",
        "path": "/api/chart", "status_code": 200, "duration_ms": 10.0,
        "content_length": "512", "error_code": None, **overrides,
    })


async def _empty_request():
    return {"type": "http.request", "body": b"", "more_body": False}


async def _ignore_send(_message):
    return None


async def _no_content_app(_scope, _receive, send):
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _run(middleware, scope=None, send=_ignore_send) -> None:
    asyncio.run(middleware(scope or {**HEALTH_SCOPE, "headers": []}, _empty_request, send))


@contextmanager
def _real_uvicorn_probe(label: str, *setup: str, command: list[str] | None = None):
    port = _unused_local_port()
    if command is None:
        script = "\n".join((
            "import uvicorn",
            *setup,
            f"uvicorn.run(main.app, host='127.0.0.1', port={port}, access_log=False, http='h11')",
        ))
        command = [sys.executable, "-c", script]
    else:
        command = [*command, "--port", str(port)]
    process = subprocess.Popen(
        command, cwd=BACKEND_ROOT,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    probe = SimpleNamespace(base_url=f"http://127.0.0.1:{port}", output="")
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"{label} server stopped early:\n" + process.stdout.read())
            try:
                if _request(probe.base_url + "/api/health")[0] == 200:
                    break
            except URLError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError(f"{label} server startup timed out")
        yield probe
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        probe.output = process.stdout.read()


def test_structured_event_schema_is_closed_and_discards_attacker_controlled_text():
    from app.privacy_logging import ALLOWED_EVENT_FIELDS, build_request_event

    event = build_request_event(
        request_id=f"server-generated-{CANARY_TEXT}",
        method=f"POST\r\n{CANARY_TEXT}",
        path=f"/attacker/{CANARY_TEXT}",
        status_code=422,
        duration_ms=731.0,
        content_length=f"invalid-{CANARY_TEXT}",
        error_code="request_rejected",
    )
    encoded = json.dumps(event, ensure_ascii=False)

    assert set(event) == EXPECTED_EVENT_FIELDS
    assert set(event) == set(ALLOWED_EVENT_FIELDS)
    assert event["method"] == "OTHER"
    assert event["route"] == "frontend_or_unmatched"
    assert event["request_id"] == "invalid"
    assert event["request_size_bucket"] == "invalid"
    assert CANARY_TEXT not in encoded
    for forbidden_field in (
        "request_body", "response_body", "query_string", "client_ip", "user_agent",
        "headers", "exception", "latitude", "longitude", "datetime",
    ):
        assert forbidden_field not in event

    # Place search is logged under its fixed route label, never with the query.
    place = _event(path="/api/places/search", content_length="72")
    assert place["route"] == "/api/places/search"
    assert "query" not in place
    # So is the time-conversion helper, never with the birth time it was asked about.
    conversion = _event(path="/api/time/convert", content_length="120")
    assert conversion["route"] == "/api/time/convert"
    assert "datetime" not in conversion and "timezone" not in conversion


def test_duration_bucket_rejects_non_finite_values():
    for duration, bucket in (
        (math.nan, "invalid"), (math.inf, "invalid"), (-math.inf, "invalid"),
        (999.9, "250_to_999ms"), (1_000.0, "gte_1000ms"),
    ):
        assert _event(duration_ms=duration)["duration_bucket"] == bucket, duration


def test_completion_event_failures_do_not_escape_the_asgi_boundary(monkeypatch):
    from app import privacy_logging

    class CompletionProbe(BaseException):
        pass

    def fail_builder(**_kwargs):
        raise CompletionProbe("completion-event-canary")

    monkeypatch.setattr(privacy_logging, "build_request_event", fail_builder)
    sent = []

    async def send(message):
        sent.append(message)

    _run(privacy_logging.PrivacyBoundaryMiddleware(_no_content_app), send=send)
    assert sent[0]["status"] == 204


def test_capacity_rejection_stays_inside_headers_and_telemetry_boundary():
    from app.privacy_logging import PrivacyBoundaryMiddleware
    from app.request_limits import RequestCapacityBoundary

    async def exercise():
        release, all_entered = asyncio.Event(), asyncio.Event()
        entered = 0
        events: list[dict] = []

        async def held_app(_scope, _receive, send):
            nonlocal entered
            entered += 1
            if entered == 2:
                all_entered.set()
            await release.wait()
            await _no_content_app(_scope, _receive, send)

        boundary = PrivacyBoundaryMiddleware(
            RequestCapacityBoundary(held_app, max_concurrent=2),
            event_emitter=lambda event: events.append(event) or True,
        )

        async def call():
            messages = []

            async def send(message):
                messages.append(message)

            # A page is general traffic; `/api/health` is never charged to a pool.
            scope = {"type": "http", "method": "GET", "path": "/zh-TW/calculate", "headers": []}
            await boundary(scope, _empty_request, send)
            return messages

        accepted = [asyncio.create_task(call()) for _ in range(2)]
        await asyncio.wait_for(all_entered.wait(), timeout=2)
        rejected = await call()
        release.set()
        await asyncio.gather(*accepted)
        return rejected, events

    rejected, events = asyncio.run(exercise())
    start = rejected[0]
    assert start["status"] == 503
    headers = {name.decode().lower(): value.decode() for name, value in start["headers"]}
    assert "content-security-policy" in headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-request-id"]
    (rejected_event,) = [event for event in events if event["status_code"] == 503]
    assert rejected_event["outcome"] == "rejected"
    assert rejected_event["error_code"] == "request_capacity_exhausted"


def test_boundary_reason_producer_and_privacy_consumer_are_closed():
    from app import privacy_logging, request_limits

    for reason in sorted(request_limits.BOUNDARY_REASON_CODES):
        scope = {"type": "http", "state": {}}
        request_limits._mark_boundary_reason(scope, reason)
        assert privacy_logging._boundary_reason(scope) == reason
        event = _event(
            request_id="a" * 32, status_code=503 if "capacity" in reason else 400,
            duration_ms=1, content_length="1",
            error_code=privacy_logging._boundary_reason(scope),
        )
        assert event["error_code"] == reason
        assert event["outcome"] == "rejected"

    assert privacy_logging._boundary_reason({
        "type": "http",
        "state": {request_limits.BOUNDARY_REASON_STATE_KEY: "attacker_text"},
    }) is None

    domain_scope = {
        "type": "http",
        "state": {privacy_logging.DOMAIN_ERROR_STATE_KEY: "full_ephemeris_required"},
    }
    assert privacy_logging._domain_error_reason(domain_scope) == "full_ephemeris_required"
    domain_event = _event(
        request_id="b" * 32, status_code=503, duration_ms=1, content_length="1",
        error_code=privacy_logging._domain_error_reason(domain_scope),
    )
    assert domain_event["outcome"] == "error"

    # Single assignment: the first producer's reason survives a second marker.
    scope = {"type": "http", "state": {}}
    request_limits._mark_boundary_reason(scope, "request_body_too_large")
    with pytest.raises(RuntimeError, match="already assigned"):
        request_limits._mark_boundary_reason(scope, "compute_capacity_exhausted")
    assert privacy_logging._boundary_reason(scope) == "request_body_too_large"


def test_each_request_rejection_reaches_telemetry_under_its_own_code():
    """Through the real application, the wire code and the event code are the
    same closed value for every in-process rejection, and no two share one."""
    from app.main import create_app
    from app.request_limits import MAX_HOSTED_HEADER_BYTES
    from app.settings import AppSettings

    events: list[dict] = []
    application = create_app(
        AppSettings(expected_host="armillary.test"),
        event_emitter=lambda event: events.append(event) or True,
    )
    json_type = (b"content-type", b"application/json")

    def headers(*extra, body=b"", host=b"armillary.test", content_type=json_type):
        base = [(b"host", host)]
        if content_type is not None:
            base.append(content_type)
        if not any(name == b"content-length" for name, _ in extra):
            base.append((b"content-length", str(len(body)).encode()))
        return base + list(extra)

    padding = (b"x-padding", b"a" * (MAX_HOSTED_HEADER_BYTES + 1))
    cases = {
        "undeclared_host": ("GET", "/api/health", headers(host=b"elsewhere.test", content_type=None), b""),
        "unknown_api_path": ("POST", "/api/not-a-route", headers(body=b"{}"), b"{}"),
        "unsupported_method": ("GET", "/api/chart", headers(content_type=None), b""),
        "unsupported_media_type": (
            "POST", "/api/chart", headers(body=b"{}", content_type=(b"content-type", b"text/plain")), b"{}",
        ),
        "conflicting_request_framing": (
            "POST", "/api/chart", headers((b"transfer-encoding", b"chunked"), body=b"{}"), b"{}",
        ),
        "invalid_content_length": ("POST", "/api/chart", headers((b"content-length", b"two")), b"{}"),
        "request_body_too_large": ("POST", "/api/chart", headers((b"content-length", b"999999999")), b"{}"),
        "empty_request_body": ("POST", "/api/chart", headers(body=b""), b""),
        "request_headers_too_large": ("POST", "/api/chart", headers(padding, body=b"{}"), b"{}"),
        "json_invalid": ("POST", "/api/chart", headers(body=b"{"), b"{"),
        "request_validation_failed": ("POST", "/api/chart", headers(body=b"{}"), b"{}"),
    }

    async def request(method, path, raw_headers, body):
        sent: list[dict] = []
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            sent.append(message)

        await application(
            {
                "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                "method": method, "scheme": "http", "path": path,
                "raw_path": path.encode(), "query_string": b"", "root_path": "",
                "headers": raw_headers, "client": ("127.0.0.1", 50000),
                "server": ("armillary.test", 80), "state": {},
            },
            receive,
            send,
        )
        payload = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        return json.loads(payload)["detail"]["code"]

    observed = {}
    for expected, (method, path, raw_headers, body) in cases.items():
        before = len(events)
        assert asyncio.run(request(method, path, raw_headers, body)) == expected
        assert len(events) == before + 1, expected
        observed[expected] = events[-1]["error_code"]

    assert observed == {code: code for code in cases}


def test_hostile_scope_header_iterator_is_reduced_without_escaping():
    from app import privacy_logging

    class HeaderProbe(BaseException):
        pass

    class HostileHeaders:
        def __iter__(self):
            raise HeaderProbe("header-iterator-canary")

    captured_events = []
    middleware = privacy_logging.PrivacyBoundaryMiddleware(
        _no_content_app, event_emitter=lambda event: captured_events.append(event) or True,
    )
    _run(middleware, {**HEALTH_SCOPE, "headers": HostileHeaders()})
    assert captured_events[-1]["request_size_bucket"] == "absent"


def test_process_control_base_exceptions_remain_propagating():
    from app import privacy_logging

    class PrivacyProbe(BaseException):
        pass

    for error in (
        asyncio.CancelledError(), KeyboardInterrupt(), SystemExit(), GeneratorExit(),
        BaseExceptionGroup("cancelled task group", [asyncio.CancelledError()]),
    ):
        assert privacy_logging._is_process_control_exception(error), error
    for error in (PrivacyProbe(), BaseExceptionGroup("non-control task group", [PrivacyProbe()])):
        assert not privacy_logging._is_process_control_exception(error), error


@pytest.mark.parametrize(
    ("source", "control_error"),
    [
        ("app", asyncio.CancelledError("middleware-cancellation-canary")),
        ("app", BaseExceptionGroup("cancelled task group", [asyncio.CancelledError()])),
        ("event_emitter", asyncio.CancelledError("event-emitter-cancellation-canary")),
    ],
    ids=["app_cancelled", "app_cancelled_group", "event_emitter_cancelled"],
)
def test_process_control_exceptions_propagate_through_middleware(source, control_error):
    from app import privacy_logging

    captured_events = []

    async def failing_app(_scope, _receive, _send):
        raise control_error

    def emitter(event):
        if source == "event_emitter":
            raise control_error
        captured_events.append(event)
        return True

    middleware = privacy_logging.PrivacyBoundaryMiddleware(
        failing_app if source == "app" else _no_content_app, event_emitter=emitter,
    )
    with pytest.raises(BaseException) as captured:
        _run(middleware)

    if isinstance(control_error, BaseExceptionGroup):
        assert privacy_logging._is_process_control_exception(captured.value)
        assert len(captured.value.exceptions) == 1
    else:
        # asyncio.run may re-raise a fresh CancelledError; what matters is that
        # cancellation stays process control and is neither swallowed nor a 500.
        assert isinstance(captured.value, asyncio.CancelledError)
    assert captured_events == []


def test_mixed_exception_group_propagates_only_process_control_subgroup():
    from app import privacy_logging

    class PrivacyProbe(BaseException):
        pass

    sensitive_canary = "MIXED_BASE_EXCEPTION_PRIVACY_CANARY"
    mixed_error = BaseExceptionGroup(
        "mixed task group", [asyncio.CancelledError(), PrivacyProbe(sensitive_canary)],
    )

    async def app(_scope, _receive, _send):
        raise mixed_error

    with pytest.raises(BaseExceptionGroup) as captured:
        _run(privacy_logging.PrivacyBoundaryMiddleware(app))

    assert privacy_logging._is_process_control_exception(captured.value)
    assert sensitive_canary not in repr(captured.value)
    assert all(not isinstance(nested, PrivacyProbe) for nested in captured.value.exceptions)


def test_emitter_refuses_unsafe_events_and_survives_a_failing_sink(capsys, monkeypatch):
    """The emitter is the last gate before the log: every field's closed domain,
    the exact field set, and a failing sink all end in `False`, never a leak."""
    from app import privacy_logging

    event = _event()
    assert privacy_logging.emit_security_event(dict(event)) is True
    capsys.readouterr()

    hostile_route = {**event, "route": f"/api/chart?private={CANARY_TEXT}"}
    assert privacy_logging.emit_security_event(hostile_route) is False
    assert CANARY_TEXT not in capsys.readouterr().err
    # The universe is the declared field tuple, so a later field is covered too.
    for field in privacy_logging.ALLOWED_EVENT_FIELDS:
        assert privacy_logging.emit_security_event({**event, field: CANARY_TEXT}) is False, field
        assert CANARY_TEXT not in capsys.readouterr().err, field

    assert privacy_logging.emit_security_event({**event, "future_field": "apparently harmless"}) is False
    missing = {key: value for key, value in event.items() if key != "failure_class"}
    assert privacy_logging.emit_security_event(missing) is False

    def fail_sink(*_args, **_kwargs):
        raise OSError("simulated unavailable logging sink")

    monkeypatch.setattr(privacy_logging._SECURITY_LOGGER, "info", fail_sink)
    assert privacy_logging.emit_security_event(event) is False


def test_caller_supplied_request_id_is_ignored(monkeypatch):
    from app import main as app_main

    captured_events: list[dict] = []
    monkeypatch.setattr(
        app_main, "emit_security_event", lambda event: captured_events.append(event) or True,
    )

    with TestClient(app_main.app) as client:
        response = client.get("/api/health", headers={"X-Request-ID": CANARY_TEXT})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != CANARY_TEXT
    assert response.headers["Content-Security-Policy"] == (
        "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; "
        "script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; "
        "require-trusted-types-for 'script'; trusted-types 'none'"
    )
    for name, value in {
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Embedder-Policy": "require-corp",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Cache-Control": "no-store",
    }.items():
        assert response.headers[name] == value, name
    assert captured_events[-1]["request_id"] == response.headers["X-Request-ID"]
    assert CANARY_TEXT not in json.dumps(captured_events, ensure_ascii=False)


def test_public_cache_policy_separates_api_html_and_versioned_assets():
    """Only the exact content digest of the served bytes earns the one-year
    immutable entry; any other `?v=` (or other query) is not stored at all."""
    import hashlib

    from app.main import create_app
    from app.settings import AppSettings

    # Independent oracle for the `?v=` token: SHA-256 prefix of the served bytes.
    page_css, tokens_css = (
        hashlib.sha256((PROJECT_ROOT / "frontend/zh-TW" / name).read_bytes()).hexdigest()[:16]
        for name in ("style/home.css", "style/calculate.css")
    )
    immutable = "public, max-age=31536000, immutable"
    expected = {
        "/api/health": "no-store",
        "/zh-TW/features": "no-cache",
        f"/zh-TW/style/home.css?v={page_css}": immutable,
        "/zh-TW/favicon.svg": "public, max-age=300",
        f"/missing.css?v={page_css}": "no-store",
    }
    not_stored = (
        f"/zh-TW/style/home.css?preview={page_css}",
        "/zh-TW/style/home.css?v=",
        "/zh-TW/style/home.css?v=release-test",
        "/zh-TW/style/home.css?v=0.16.6",
        f"/zh-TW/style/home.css?v={tokens_css}",
        f"/zh-TW/style/home.css?v={page_css[:-1]}",
        f"/zh-TW/style/home.css?v={page_css.upper()}",
        f"/zh-TW/style/home.css?v={page_css}&v=release-test",
    )
    with TestClient(create_app(AppSettings())) as client:
        for url, cache_control in expected.items():
            assert client.get(url).headers["cache-control"] == cache_control, url
        for url in not_stored:
            response = client.get(url)
            assert response.status_code == 200, url
            assert response.headers["cache-control"] == "no-store", url
        exact = client.get(f"/zh-TW/style/home.css?v={page_css}")
        exact_head = client.head(f"/zh-TW/style/home.css?v={page_css}")
    assert exact.status_code == 200
    assert exact_head.headers["cache-control"] == immutable


def _all_modules_payload(precision: str) -> dict:
    """Every module on, with the widest option values the container gate uses."""

    from scripts.verification.verify_container_runtime import _worst_options_payload

    payload = _payload()
    payload["birth_time_precision"] = precision
    if precision == "date_only":
        payload["datetime"].update(hour=0, minute=0, second=0)
    elif precision == "approximate_hour":
        payload["datetime"].update(minute=0, second=0)
    payload["options"] = _worst_options_payload()["options"]
    return payload


def _raise_unexpected(_request):
    raise RuntimeError(CANARY_TEXT)


# The published privacy pages promise that a write during request handling fails
# a test, on every route and outcome class.  (method, path, body, compute
# override, expected status)
_WRITE_GUARD_CASES = {
    "chart_default": ("POST", "/api/chart", _payload, None, 200),
    "chart_all_modules_exact": ("POST", "/api/chart", lambda: _all_modules_payload("exact"), None, 200),
    "chart_all_modules_approximate_hour": (
        "POST", "/api/chart", lambda: _all_modules_payload("approximate_hour"), None, 200,
    ),
    "chart_all_modules_date_only": (
        "POST", "/api/chart", lambda: _all_modules_payload("date_only"), None, 200,
    ),
    "chart_detailed_projection": ("POST", "/api/chart?projection=detailed", _payload, None, 200),
    "chart_validation_refusal": (
        "POST", "/api/chart", lambda: {**_payload(), "location": {"latitude": 999}}, None, 422,
    ),
    "chart_nonexistent_local_time_refusal": (
        "POST", "/api/chart",
        lambda: minimal_chart_payload(
            year=2021, month=3, day=14, hour=2, minute=30,
            latitude=CANARY_LATITUDE, longitude=CANARY_LONGITUDE,
            timezone={"mode": "iana", "iana_name": "America/New_York", "fold": 0},
        ),
        None, 422,
    ),
    "chart_malformed_body": ("POST", "/api/chart", b"{not json", None, 400),
    "chart_unexpected_error": ("POST", "/api/chart", _payload, _raise_unexpected, 500),
    "place_search": ("POST", "/api/places/search", {"query": "Tainan"}, None, 200),
    "place_search_refusal": ("POST", "/api/places/search", {"query": CANARY_TEXT * 10}, None, 422),
    "time_convert": (
        "POST", "/api/time/convert",
        {"datetime": {"year": 1974, "month": 9, "day": 30, "hour": 23, "minute": 30},
         "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"}},
        None, 200,
    ),
    "time_convert_refusal": (
        "POST", "/api/time/convert",
        {"datetime": {"year": 1974, "month": 9, "day": 30, "hour": 23, "minute": 30},
         "timezone": {"mode": "iana", "iana_name": "Europe/London"}},
        None, 422,
    ),
    "health": ("GET", "/api/health", None, None, 200),
    "static_page": ("GET", "/zh-TW/calculate", None, None, 200),
    "static_asset": ("GET", "/zh-TW/calculate.js", None, None, 200),
    "not_found_page": ("GET", "/zh-TW/no-such-page", None, None, 404),
}


@pytest.mark.parametrize("case", sorted(_WRITE_GUARD_CASES))
def test_request_handling_does_not_use_python_file_write_apis(monkeypatch, case):
    import sqlite3

    from app import main as app_main
    from app.settings import AppSettings

    method, path, body, compute_override, expected_status = _WRITE_GUARD_CASES[case]
    if callable(body):
        body = body()
    if compute_override is not None:
        monkeypatch.setattr(app_main, "_compute_chart_locked", compute_override)

    observed_writes: list[str] = []
    original_os_open = os.open
    original_sqlite_connect = sqlite3.connect

    def guarded_stream_open(original):
        def open_without_writes(file, mode="r", *args, **kwargs):
            if any(flag in str(mode) for flag in ("w", "a", "x", "+")):
                observed_writes.append(str(file))
                raise AssertionError(f"request attempted file persistence: {file}")
            return original(file, mode, *args, **kwargs)

        return open_without_writes

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            observed_writes.append(str(path))
            raise AssertionError(f"request attempted os.open persistence: {path}")
        return original_os_open(path, flags, *args, **kwargs)

    def guarded_sqlite_connect(database, *args, **kwargs):
        # SQLite opens files below os.open; the bundled place catalog is the
        # only database and must be opened read-only and immutable.
        target = str(database)
        if not (kwargs.get("uri") is True and "mode=ro" in target and "immutable=1" in target):
            observed_writes.append(target)
            raise AssertionError(f"request opened a writable database: {target}")
        return original_sqlite_connect(database, *args, **kwargs)

    application = app_main.create_app(AppSettings())
    with TestClient(application, raise_server_exceptions=False) as client:
        # Guards go in after startup so they cover request handling only.
        monkeypatch.setattr(builtins, "open", guarded_stream_open(builtins.open))
        monkeypatch.setattr(io, "open", guarded_stream_open(io.open))
        monkeypatch.setattr(os, "open", guarded_os_open)
        monkeypatch.setattr(sqlite3, "connect", guarded_sqlite_connect)
        if isinstance(body, bytes):
            response = client.request(
                method, path, content=body, headers={"Content-Type": "application/json"},
            )
        elif body is None:
            response = client.request(method, path)
        else:
            response = client.request(method, path, json=body)

    assert observed_writes == [], case
    # Each case reached the outcome it names, so the guard watched that path.
    assert response.status_code == expected_status, (case, response.status_code)


def test_backend_has_no_third_party_telemetry_or_persistence_dependency():
    completed = subprocess.run(
        [sys.executable, "-m", "scripts.verification.verify_privacy_dependencies", "--check"],
        cwd=PROJECT_ROOT, check=False, capture_output=True, text=True, timeout=20,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PRIVACY DEPENDENCY CHECK PASSED" in completed.stdout


@pytest.mark.parametrize(
    ("error_type", "code"),
    [(RuntimeError, "internal_server_error"), (swe.Error, "swiss_ephemeris_error")],
    ids=["unexpected_exception", "swisseph_error"],
)
def test_chart_failure_returns_closed_refusal_and_logs_no_exception_text(
    monkeypatch, error_type, code,
):
    from app import main as app_main
    from app.refusals import REFUSALS

    captured_events: list[dict] = []

    def fail_with_sensitive_exception(_request):
        raise error_type(f"{CANARY_TEXT}:{CANARY_LATITUDE}:{CANARY_LONGITUDE}")

    monkeypatch.setattr(app_main, "_compute_chart_locked", fail_with_sensitive_exception)
    monkeypatch.setattr(
        app_main, "emit_security_event", lambda event: captured_events.append(event) or True,
    )

    with TestClient(app_main.app, raise_server_exceptions=False) as client:
        response = client.post("/api/chart", json=_payload())

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": code, "message": REFUSALS[code].message}}
    if code == "internal_server_error":
        assert REFUSALS[code].message == (
            "伺服器無法完成本次計算。請重新嘗試；若持續發生，請回報 request ID。"
        )
    for canary in (CANARY_TEXT, str(CANARY_LATITUDE), str(CANARY_LONGITUDE)):
        assert canary not in response.text
    assert captured_events[-1]["error_code"] == code
    assert CANARY_TEXT not in json.dumps(captured_events, ensure_ascii=False)


def test_real_uvicorn_unexpected_errors_emit_no_traceback_or_canary():
    """One real server: a chart failure, a non-control BaseException, and
    failures after the response started (stream, background task)."""
    base_canary = "PRIVACY_BASE_EXCEPTION_CANARY_6C_734991"
    stream_canary = "PRIVACY_STREAM_CANARY_6C_734991"
    background_canary = "PRIVACY_BACKGROUND_CANARY_6C_734991"
    with _real_uvicorn_probe(
        "unexpected-error",
        "from fastapi.responses import PlainTextResponse, StreamingResponse",
        "from starlette.background import BackgroundTask",
        "from starlette.routing import Route",
        "from app import main",
        "def fail(_request):",
        f"    raise RuntimeError({CANARY_TEXT!r})",
        "main._compute_chart_locked = fail",
        "class PrivacyProbe(BaseException): pass",
        "async def base_fail(_request):",
        f"    raise PrivacyProbe({base_canary!r})",
        "async def broken_stream():",
        "    yield b'ok'",
        f"    raise RuntimeError({stream_canary!r})",
        "async def stream_route(_request): return StreamingResponse(broken_stream())",
        "def broken_background():",
        f"    raise RuntimeError({background_canary!r})",
        "async def background_route(_request):",
        "    return PlainTextResponse(b'ok', background=BackgroundTask(broken_background))",
        "main.app.router.routes.insert(0, Route('/__privacy_base_exception', base_fail))",
        "main.app.router.routes.insert(0, Route('/__privacy_stream', stream_route))",
        "main.app.router.routes.insert(0, Route('/__privacy_background', background_route))",
    ) as probe:
        status, body = _request(probe.base_url + "/api/chart", json.dumps(_payload()).encode())
        assert status == 500
        assert json.loads(body)["detail"]["code"] == "internal_server_error"
        status, body = _request(probe.base_url + "/__privacy_base_exception")
        assert status == 500
        assert json.loads(body)["detail"]["code"] == "internal_server_error"
        assert _request(probe.base_url + "/__privacy_stream") == (200, b"ok")
        assert _request(probe.base_url + "/__privacy_background") == (200, b"ok")
    output = probe.output
    for canary in (CANARY_TEXT, base_canary, stream_canary, background_canary):
        assert canary not in output
    assert "Traceback (most recent call last)" not in output
    # An unexpected failure may carry its exception class name from a closed
    # allowlist and nothing else; an undeclared class becomes `unclassified`.
    assert '"failure_class":"RuntimeError"' in output
    assert '"failure_class":"unclassified"' in output
    assert "PrivacyProbe" not in output
    assert "RuntimeError" not in output.replace('"failure_class":"RuntimeError"', "")

    marker = "PRIVACY_EVENT "
    records = [
        json.loads(line.split(marker, 1)[1]) for line in output.splitlines() if marker in line
    ]
    unmatched_failures = [
        record for record in records
        if record["route"] == "frontend_or_unmatched"
        and record["error_code"] == "internal_server_error"
    ]
    # Base exception (500) plus the two post-start failures (status already 200).
    assert sorted(record["status_code"] for record in unmatched_failures) == [200, 200, 500]
    assert all(record["outcome"] == "error" for record in unmatched_failures)
    # The stream and background failures are RuntimeErrors too, so the chart
    # path's own classification is read from its own record.
    chart_failures = [
        record for record in records
        if record["route"] == "/api/chart" and record["error_code"] == "internal_server_error"
    ]
    assert [record["failure_class"] for record in chart_failures] == ["RuntimeError"]


def test_real_uvicorn_event_emitter_failure_is_isolated():
    emitter_canary = "PRIVACY_EMITTER_FAILURE_CANARY_6C_734991"
    with _real_uvicorn_probe(
        "emitter-failure",
        "from app import main",
        "def fail_emitter(_event):",
        f"    raise OSError({emitter_canary!r})",
        "main.emit_security_event = fail_emitter",
    ) as probe:
        status, body = _request(probe.base_url + "/api/health")
        assert status == 200
        assert json.loads(body)["status"] == "ok"
    output = probe.output
    assert emitter_canary not in output
    assert "Traceback (most recent call last)" not in output
    assert "OSError" not in output


@pytest.mark.parametrize("launch", ("cli_without_flag", "run_with_access_log_true"))
def test_real_uvicorn_started_without_access_log_flag_logs_no_url(launch):
    """The app itself turns the access log off; a launch that forgets
    `--no-access-log` (or passes access_log=True) still writes no URL."""
    query_canary = "PRIVACY_ACCESS_LOG_CANARY_6C_734991"
    if launch == "cli_without_flag":
        command = [
            sys.executable, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--http", "h11",
        ]
    else:
        command = [sys.executable, "-c", "\n".join((
            "import sys, uvicorn",
            "from app import main",
            "uvicorn.run(main.app, host='127.0.0.1', port=int(sys.argv[2]),"
            " access_log=True, http='h11')",
        ))]
    with _real_uvicorn_probe(f"access-log-{launch}", command=command) as probe:
        assert _request(
            probe.base_url + f"/zh-TW/calculate?birth={query_canary}"
        )[0] == 200
        status, _body = _request(
            probe.base_url + f"/api/chart?dob={query_canary}",
            json.dumps(_payload()).encode(),
        )
        assert status == 422
    output = probe.output
    assert query_canary not in output
    assert "/zh-TW/calculate" not in output
    assert '"GET /api/health' not in output


def test_fault_handler_dump_names_frames_but_carries_no_values():
    """The image sets PYTHONFAULTHANDLER=1, so a fatal signal writes every
    thread's stack to stderr, which the host journal keeps.  The dump names
    files, lines and functions; an argument or local holding birth data does
    not appear.  `dump_traceback` is the writer the fatal handler uses,
    without crashing the test process into the host's crash reporter."""
    script = "\n".join((
        "import faulthandler, sys",
        "def chart_frame(latitude, place):",
        f"    held = {CANARY_TEXT!r} + place",
        "    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)",
        f"chart_frame({CANARY_LATITUDE!r}, {str(CANARY_LONGITUDE)!r})",
    ))
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PYTHONFAULTHANDLER": "1"},
        capture_output=True, text=True, timeout=30, check=True,
    )
    output = completed.stdout + completed.stderr
    assert "chart_frame" in output and "line 4" in output
    for canary in (CANARY_TEXT, str(CANARY_LATITUDE), str(CANARY_LONGITUDE)):
        assert canary not in output
