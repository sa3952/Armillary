"""Privacy-safe, allowlist-only application telemetry.

Birth date/time and precise coordinates are the application's most sensitive
inputs.  This module therefore never serializes a Request, response, exception,
header value, URL, query string, client address, or user agent.  Callers may
only supply values that are reduced to a closed vocabulary before emission.

The output is operational telemetry, not an audit trail.  Delivery is
best-effort: a broken logging sink must never break a calculation request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from pathlib import PurePosixPath
import re
import time
import uuid

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Final

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .core.invariants import InternalInvariantError
from .refusals import (
    ANNUAL_ROUTE,
    CHART_ROUTE,
    HEALTH_ROUTE,
    PLACE_SEARCH_ROUTE,
    REFUSALS,
    TIME_CONVERT_ROUTE,
    refusal_response,
)
from .request_limits import (
    BOUNDARY_REASON_CODES,
    BOUNDARY_REASON_STATE_KEY,
    CLIENT_DISCONNECTED,
    CLOSURE_REASON_CODES,
    client_disconnected,
    is_api_path,
)


EVENT_SCHEMA_VERSION: Final = "privacy-request-event-v2"
EVENT_NAME: Final = "http_request_completed"
DOMAIN_ERROR_STATE_KEY: Final = "project_armillary_domain_error_code"

ALLOWED_EVENT_FIELDS: Final = (
    "event_schema_version",
    "event",
    "request_id",
    "route",
    "method",
    "status_code",
    "duration_bucket",
    "request_size_bucket",
    "outcome",
    "error_code",
    "failure_class",
)

_ALLOWED_METHODS: Final = frozenset({"GET", "POST", "HEAD", "OPTIONS"})
# The annual route keeps its own label whether or not its flag registered it:
# the label is the fixed path, never request text, and an unregistered probe of
# it stays distinguishable from a page fetch.
_ALLOWED_ROUTES: Final = frozenset({
    ANNUAL_ROUTE, CHART_ROUTE, HEALTH_ROUTE, PLACE_SEARCH_ROUTE, TIME_CONVERT_ROUTE,
})
# A refusal whose occurrence is decided by the birth date, time or place says
# something about the birth record: a skipped or repeated local hour, a place
# that keeps two clocks, a time zone outside the helper's sources, a latitude
# where the house system fails, an instant outside the ephemeris.  The user is
# still answered with the exact code; the event keeps only its category, so the
# log holds no attribute of the birth data.
TELEMETRY_CATEGORY: Final[Mapping[str, str]] = MappingProxyType({
    "nonexistent_local_time": "domain_refused",
    "ambiguous_local_time_choice_required": "domain_refused",
    "civil_time_basis_required": "domain_refused",
    "civil_time_basis_not_applicable": "domain_refused",
    "time_conversion_zone_not_covered": "domain_refused",
    "house_system_unavailable": "domain_refused",
    "full_ephemeris_required": "domain_failed",
    "swiss_ephemeris_error": "domain_failed",
    "catalog_record_unknown": "domain_refused",
    "catalog_location_mismatch": "domain_refused",
})
# Every other refusal code is an event code as it is (the boundary reasons and
# the remaining domain errors are refusal codes); the refusal table in
# refusals.py is the owner, so a new refusal cannot reach a response while
# telemetry reduces it to `unclassified`.  The rest are telemetry's own words.
_ALLOWED_ERROR_CODES: Final = frozenset(
    {"request_rejected", "server_error", "unclassified"}
) | CLOSURE_REASON_CODES | (frozenset(REFUSALS) - frozenset(TELEMETRY_CATEGORY)) | frozenset(
    TELEMETRY_CATEGORY.values()
)


def telemetry_error_code(code: str) -> str:
    """The event's word for a refusal code: the code itself, or its category."""

    return TELEMETRY_CATEGORY.get(code, code)
# Unexpected failures may expose only a closed exception-class vocabulary.
# Anything else becomes `unclassified`; messages, tracebacks and request-derived
# values never reach this field.
_ALLOWED_FAILURE_CLASSES: Final = frozenset(
    {
        "AssertionError",
        "AttributeError",
        "Error",
        "IndexError",
        "KeyError",
        "OSError",
        "OverflowError",
        "RecursionError",
        "RuntimeError",
        "TypeError",
        "UnicodeDecodeError",
        "ValueError",
        "ZeroDivisionError",
    }
)
_UNCLASSIFIED_FAILURE_CLASS: Final = "unclassified"


def public_event_contract() -> dict[str, tuple[str, ...]]:
    """Project the executable event vocabulary for public page generation."""

    return {
        "fields": tuple(sorted(ALLOWED_EVENT_FIELDS)),
        "error_codes": tuple(sorted(_ALLOWED_ERROR_CODES)),
        "failure_classes": tuple(sorted({
            *_ALLOWED_FAILURE_CLASSES,
            _UNCLASSIFIED_FAILURE_CLASS,
        })),
    }


def failure_class(error: BaseException | None) -> str | None:
    """Name the exception type, or say it was not one this service declares."""

    if error is None:
        return None
    # A broken internal guarantee keeps the name of the assertion it replaced.
    name = (
        "AssertionError"
        if isinstance(error, InternalInvariantError)
        else type(error).__name__
    )
    return name if name in _ALLOWED_FAILURE_CLASSES else _UNCLASSIFIED_FAILURE_CLASS


_DOMAIN_FAILURE_CODES: Final = frozenset({
    "domain_failed",
    "place_catalog_unavailable",
})
_ALLOWED_DURATION_BUCKETS: Final = frozenset(
    {
        "invalid",
        "lt_10ms",
        "10_to_49ms",
        "50_to_249ms",
        "250_to_999ms",
        "gte_1000ms",
    }
)
_ALLOWED_SIZE_BUCKETS: Final = frozenset(
    {
        "absent",
        "invalid",
        "empty",
        "1_to_1024b",
        "1025_to_16384b",
        "16385_to_131072b",
        "gt_131072b",
    }
)
_ALLOWED_OUTCOMES: Final = frozenset({"success", "rejected", "error", "unknown"})
_REQUEST_ID_PATTERN: Final = re.compile(r"^[0-9a-f]{32}$")
_PROCESS_CONTROL_EXCEPTIONS: Final = (
    asyncio.CancelledError,
    KeyboardInterrupt,
    SystemExit,
    GeneratorExit,
)

_SECURITY_HEADERS: Final = {
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'none'; object-src 'none'; "
        "frame-ancestors 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; form-action 'self'; "
        "require-trusted-types-for 'script'; trusted-types 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
}
_IMMUTABLE_STATIC_SUFFIXES: Final = frozenset({
    ".avif", ".css", ".gif", ".ico", ".jpeg", ".jpg", ".js", ".mjs",
    ".otf", ".png", ".svg", ".ttf", ".webp", ".woff", ".woff2",
})

_SECURITY_LOGGER = logging.getLogger("classical_astrology.privacy")
_SECURITY_LOGGER.setLevel(logging.INFO)
_SECURITY_LOGGER.propagate = False

if not any(
    getattr(handler, "_classical_astrology_privacy_handler", False)
    for handler in _SECURITY_LOGGER.handlers
):
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _handler._classical_astrology_privacy_handler = True  # type: ignore[attr-defined]
    _SECURITY_LOGGER.addHandler(_handler)


class _DropEveryRecord(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return False


def silence_server_access_log() -> None:
    """Turn the ASGI server's access log off from inside the app.

    Uvicorn's access line carries the request target, path and query string
    included, so a launch that forgets `--no-access-log` would write URLs.
    A later `logging.config.dictConfig` that names this logger re-enables it,
    so a drop-everything filter stays behind as well.
    """
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.disabled = True
    if not any(isinstance(item, _DropEveryRecord) for item in access_logger.filters):
        access_logger.addFilter(_DropEveryRecord())


def _safe_method(value: object) -> str:
    if isinstance(value, str):
        normalized = value.upper()
        if normalized in _ALLOWED_METHODS:
            return normalized
    return "OTHER"


def _safe_route(value: object) -> str:
    if isinstance(value, str) and value in _ALLOWED_ROUTES:
        return value
    return "frontend_or_unmatched"


def _safe_status_code(value: object) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
        return value
    return 0


def _duration_bucket(value: object) -> str:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(value)
        or value < 0
    ):
        return "invalid"
    if value < 10:
        return "lt_10ms"
    if value < 50:
        return "10_to_49ms"
    if value < 250:
        return "50_to_249ms"
    if value < 1_000:
        return "250_to_999ms"
    return "gte_1000ms"


def _request_size_bucket(value: object) -> str:
    if value is None:
        return "absent"
    if not isinstance(value, str):
        return "invalid"
    try:
        size = int(value, 10)
    except (TypeError, ValueError):
        return "invalid"
    if size < 0:
        return "invalid"
    if size == 0:
        return "empty"
    if size <= 1_024:
        return "1_to_1024b"
    if size <= 16_384:
        return "1025_to_16384b"
    if size <= 131_072:
        return "16385_to_131072b"
    return "gt_131072b"


def _outcome(status_code: int, error_code: str | None) -> str:
    # A response can fail after its HTTP status has already been sent.  Keep the
    # wire status truthful while allowing telemetry to record the completed
    # operation as an error.
    if error_code in CLOSURE_REASON_CODES:
        # The client left before a response existed: the service neither
        # refused nor failed it, and there is no status to classify.
        return "unknown"
    if error_code in {"internal_server_error", "server_error"} | _DOMAIN_FAILURE_CODES:
        return "error"
    if error_code in BOUNDARY_REASON_CODES:
        return "rejected"
    if 200 <= status_code <= 399:
        return "success"
    if 400 <= status_code <= 499:
        return "rejected"
    if 500 <= status_code <= 599:
        return "error"
    return "unknown"


def _safe_error_code(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and telemetry_error_code(value) in _ALLOWED_ERROR_CODES:
        return telemetry_error_code(value)
    return "unclassified"


def _boundary_reason(scope: Scope) -> str | None:
    state = scope.get("state")
    if not isinstance(state, Mapping):
        return None
    value = state.get(BOUNDARY_REASON_STATE_KEY)
    if isinstance(value, str) and value in BOUNDARY_REASON_CODES:
        return value
    return None


def _domain_error_reason(scope: Scope) -> str | None:
    state = scope.get("state")
    if not isinstance(state, Mapping):
        return None
    value = state.get(DOMAIN_ERROR_STATE_KEY)
    if not isinstance(value, str):
        return None
    reduced = telemetry_error_code(value)
    return reduced if reduced in _ALLOWED_ERROR_CODES else None


def _safe_request_id(value: object) -> str:
    if isinstance(value, str) and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return "invalid"


def _is_process_control_exception(error: BaseException) -> bool:
    """Keep cancellation and interpreter-control signals outside containment."""

    if isinstance(error, BaseExceptionGroup):
        return any(
            _is_process_control_exception(nested)
            for nested in error.exceptions
        )
    return isinstance(error, _PROCESS_CONTROL_EXCEPTIONS)


def _raise_if_process_control(error: BaseException) -> None:
    if isinstance(error, BaseExceptionGroup):
        control_subgroup = error.subgroup(_PROCESS_CONTROL_EXCEPTIONS)
        if control_subgroup is not None:
            raise control_subgroup
        return
    if isinstance(error, _PROCESS_CONTROL_EXCEPTIONS):
        raise error


def build_request_event(
    *,
    request_id: str,
    method: object,
    path: object,
    status_code: object,
    duration_ms: object,
    content_length: object,
    error_code: object,
    failure: BaseException | None = None,
) -> dict:

    safe_status = _safe_status_code(status_code)
    safe_error = _safe_error_code(error_code)
    event = {
        "event_schema_version": EVENT_SCHEMA_VERSION,
        "event": EVENT_NAME,
        "request_id": _safe_request_id(request_id),
        "route": _safe_route(path),
        "method": _safe_method(method),
        "status_code": safe_status,
        "duration_bucket": _duration_bucket(duration_ms),
        "request_size_bucket": _request_size_bucket(content_length),
        "outcome": _outcome(safe_status, safe_error),
        "error_code": safe_error,
        "failure_class": failure_class(failure),
    }
    return event


def _event_is_safe(event: object) -> bool:
    if not isinstance(event, dict) or tuple(event) != ALLOWED_EVENT_FIELDS:
        return False
    return (
        event["event_schema_version"] == EVENT_SCHEMA_VERSION
        and event["event"] == EVENT_NAME
        and isinstance(event["request_id"], str)
        and (
            event["request_id"] == "invalid"
            or bool(_REQUEST_ID_PATTERN.fullmatch(event["request_id"]))
        )
        and event["route"] in _ALLOWED_ROUTES | {"frontend_or_unmatched"}
        and event["method"] in _ALLOWED_METHODS | {"OTHER"}
        and isinstance(event["status_code"], int)
        and not isinstance(event["status_code"], bool)
        and 0 <= event["status_code"] <= 599
        and event["duration_bucket"] in _ALLOWED_DURATION_BUCKETS
        and event["request_size_bucket"] in _ALLOWED_SIZE_BUCKETS
        and event["outcome"] in _ALLOWED_OUTCOMES
        and (
            event["error_code"] is None
            or event["error_code"] in _ALLOWED_ERROR_CODES
        )
        and (
            event["failure_class"] is None
            or event["failure_class"] in
            _ALLOWED_FAILURE_CLASSES | {_UNCLASSIFIED_FAILURE_CLASS}
        )
    )


def emit_security_event(event: dict) -> bool:
    """Emit an already-sanitized event without affecting request processing."""

    try:
        if not _event_is_safe(event):
            return False
        payload = {field: event[field] for field in ALLOWED_EVENT_FIELDS}
        _SECURITY_LOGGER.info(
            "PRIVACY_EVENT %s",
            json.dumps(payload, ensure_ascii=True, separators=(",", ":")),
        )
    except BaseException as error:
        _raise_if_process_control(error)
        # Do not log the logging failure: fallback logging could reintroduce an
        # uncontrolled sink or exception representation.  Operational metrics
        # may report aggregate sink health only after a deployment is designed.
        return False
    return True


def _content_length_from_scope(scope: Scope) -> str | None:
    """Return only the raw Content-Length value for later numeric bucketing."""

    try:
        for raw_name, raw_value in scope.get("headers", []):
            if raw_name.lower() == b"content-length":
                return raw_value.decode("ascii", errors="replace")
    except BaseException as error:
        _raise_if_process_control(error)
        return None
    return None


def _apply_security_headers(
    message: Message, request_id: str, cache_control: str
) -> None:
    headers = MutableHeaders(scope=message)
    for name, value in _SECURITY_HEADERS.items():
        headers[name] = value
    headers["Cache-Control"] = cache_control
    headers["X-Request-ID"] = request_id


def _cache_control(
    scope: Scope,
    status_code: int,
    policy: str,
    asset_content_version: Callable[[str], str | None] | None = None,
) -> str:
    if policy == "no_store" or status_code >= 400:
        return "no-store"
    path = scope.get("path")
    if not isinstance(path, str) or is_api_path(path):
        return "no-store"
    suffix = PurePosixPath(path).suffix.casefold()
    query = scope.get("query_string", b"")
    if query:
        # A query on a page or asset address may carry birth data typed
        # or linked by someone else (the reason the 308 drops it).  Only the
        # one query this site writes itself — exactly `v=<content version of
        # the bytes served here>`, byte for byte — may be stored; anything else
        # is answered but never kept under that URL.
        version = (
            asset_content_version(path)
            if asset_content_version is not None
            and suffix in _IMMUTABLE_STATIC_SUFFIXES
            else None
        )
        # The year-long immutable entry is bound to the bytes, not to
        # the presence of a key; a label, a stale or foreign digest, a second
        # parameter, or an application with no version source never earns it.
        if version is not None and query == b"v=" + version.encode("ascii"):
            return "public, max-age=31536000, immutable"
        return "no-store"
    if suffix not in _IMMUTABLE_STATIC_SUFFIXES:
        return "no-cache"
    return "public, max-age=300"


class PrivacyBoundaryMiddleware:

    def __init__(
        self,
        app: ASGIApp,
        *,
        event_emitter: Callable[[dict], bool] = emit_security_event,
        cache_policy: str = "no_store",
        asset_content_version: Callable[[str], str | None] | None = None,
    ) -> None:
        if cache_policy not in {"no_store", "public_split"}:
            raise ValueError("unsupported response cache policy")
        self.app = app
        self.event_emitter = event_emitter
        self.cache_policy = cache_policy
        self.asset_content_version = asset_content_version

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        started = time.perf_counter()
        response_started = False
        response_complete = False
        status_code = 0
        error_code: str | None = None
        process_control_exception = False

        async def send_with_boundary(message: Message) -> None:
            nonlocal response_started, response_complete, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = _safe_status_code(message.get("status"))
                _apply_security_headers(
                    message,
                    request_id,
                    _cache_control(
                        scope,
                        status_code,
                        self.cache_policy,
                        self.asset_content_version,
                    ),
                )
            elif message["type"] == "http.response.body":
                response_complete = not message.get("more_body", False)
            await send(message)

        async def send_generic_500() -> None:
            # The same serializer and fixed message every other refusal uses.
            try:
                await refusal_response("internal_server_error")(
                    scope, receive, send_with_boundary
                )
            except BaseException as error:
                _raise_if_process_control(error)
                # A failed ASGI send has no safe fallback sink.  The
                # allowlisted completion event below remains best-effort.

        unexpected_failure: BaseException | None = None
        try:
            await self.app(scope, receive, send_with_boundary)
            if not response_started and client_disconnected(scope):
                # The request boundary stopped because the client had gone.
                # No response is owed to a closed connection, and a
                # synthesized 500 would count a client abort as a server
                # fault.  The status stays 0: none was sent.
                error_code = CLIENT_DISCONNECTED
            elif not response_started:
                error_code = "internal_server_error"
                await send_generic_500()
        except BaseException as error:
            if _is_process_control_exception(error):
                process_control_exception = True
                _raise_if_process_control(error)
            # The class name and nothing else: the traceback and the message can
            # carry a birth time or a coordinate, the type cannot, and the
            # allowlist below reduces anything unfamiliar to `unclassified`.
            unexpected_failure = error
            # Do not re-raise into ServerErrorMiddleware/Uvicorn: their default
            # error logger includes exception text and tracebacks.  Before
            # response start we can still replace the response with a stable
            # generic 500.  Afterwards the HTTP status cannot be changed.
            error_code = "internal_server_error"
            if not response_started:
                await send_generic_500()
            elif not response_complete:
                try:
                    await send({"type": "http.response.body", "body": b""})
                except BaseException as send_error:
                    _raise_if_process_control(send_error)
                    pass
        finally:
            if not process_control_exception:
                if error_code is None:
                    domain_reason = _domain_error_reason(scope)
                    boundary_reason = _boundary_reason(scope)
                    if domain_reason is not None:
                        error_code = domain_reason
                    elif boundary_reason is not None:
                        error_code = boundary_reason
                    elif 400 <= status_code <= 499:
                        error_code = "request_rejected"
                    elif status_code >= 500:
                        error_code = "server_error"

                try:
                    event = build_request_event(
                        request_id=request_id,
                        method=scope.get("method"),
                        # ASGI scope path excludes the query string.  Unknown/static
                        # paths are reduced to a fixed label.
                        path=scope.get("path"),
                        status_code=status_code,
                        duration_ms=(time.perf_counter() - started) * 1_000,
                        content_length=_content_length_from_scope(scope),
                        error_code=error_code,
                        failure=unexpected_failure,
                    )
                    self.event_emitter(event)
                except BaseException as event_error:
                    _raise_if_process_control(event_error)
                    # Completion telemetry is best-effort.  A reviewed future
                    # reducer or sink must not expose its exception to Uvicorn.
                    pass
