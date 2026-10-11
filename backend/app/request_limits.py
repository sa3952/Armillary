"""Pure-ASGI request boundary for hosted JSON calculation/search endpoints."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
import threading
from typing import Final, Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .refusals import (
    CHART_ROUTE,
    HEALTH_ROUTE,
    PLACE_SEARCH_ROUTE,
    RETRY_AFTER_SECONDS,
    TIME_CONVERT_ROUTE,
    refusal_response,
)


MAX_CHART_REQUEST_BYTES: Final = 16 * 1024
MAX_HOSTED_HEADER_BYTES: Final = 16 * 1024
# Three admission pools, so no class of path can starve another; all remain
# inside the reviewed ASGI response boundary.  General page traffic (pages and
# assets):
MAX_HOSTED_REQUESTS_PER_WORKER: Final = 32
# Chart computation, serialized on the Swiss lock.  Per worker: the workers
# accept connections independently, so simultaneous charts are not spread
# evenly and only one worker's pool is guaranteed (measured:
# docs/operations/CAPACITY_MEASUREMENT_2026-10-04.md §8.1).
MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER: Final = 4
# Place lookup and time conversion.  They are neither page traffic nor chart
# computation: an admitted place lookup holds a worker thread for up to the
# catalogue statement budget, and in the general pool a burst of lookups refused
# assets and the health probe.  A time conversion is microseconds on the event
# loop, but its body is birth data and it is the same kind of explicit-action
# request, so it shares this pool rather than the page's.  The page starts either
# only on an explicit action and aborts the previous one, so four per worker is
# not a typeahead budget.
MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER: Final = 4
# RETRY_AFTER_SECONDS (re-exported above) is the one retry contract for every
# admission refusal; refusal_response adds it.
# Total time a bounded JSON body may take, from the first read to the last
# byte.  The per-chunk gap timeout this replaces did not bound the total: one
# byte sent just inside the gap kept a 16 KiB body arriving for hours.  In the
# deployed path NGINX buffers the whole body before proxying
# (`proxy_request_buffering on`, `client_body_timeout 10s`), so this deadline is
# defence in depth there.  How many connections may sit in the body phase is
# the edge's `limit_conn`; this module bounds each body's size and time only.
REQUEST_BODY_DEADLINE_SECONDS: Final = 10.0
# How long a chart may wait for the Swiss lock is derived from what is waiting
# for its answer.  The edge gives `/api/chart` 30 s to answer
# (`proxy_read_timeout` in `location = /api/chart` of
# deploy/staging/nginx-site.conf.template) and the page aborts at the same 30 s
# (`REQUEST_TIMEOUT_MS` in frontend/zh-TW/calculate.js); both copies are pinned
# to this constant by tests/backend/test_compute_queue.py, because the template
# is rendered by literal replacement and cannot import it.  A chart that starts
# computing later than the wait budget below would, at the p99 compute time,
# finish after both have given up: it is refused while the refusal is still
# readable and retryable, instead of spending the worker's CPU on an answer
# nobody receives.
EDGE_CHART_READ_TIMEOUT_SECONDS: Final = 30.0
# p99 wall time of one chart calculation, an estimate, not a measurement of the
# host: the slowest single request measured locally (Apple M1, 2026-10-10)
# is ~1.5 s CPU, every module at 69°N on a date only in 2150, its high-latitude
# rise/set searches skipping only days the direction-aware pre-filter proves
# crossing-free (~6.5 s before that pre-filter; at the end of 2399 the chart
# itself is computed, and only the search modules, whose windows run past the
# bundled segments, are refused out-of-coverage before any Swiss call), and
# ~2.9 s for the worst-options chart under amd64 emulation on 2026-10-04,
# doubled when the two workers share one CPU
# (docs/operations/CAPACITY_MEASUREMENT_2026-10-04.md §4.2).  Revisit with a
# measurement on the production host.
COMPUTE_P99_ESTIMATE_SECONDS: Final = 8.0
# Serialization, compression and the edge hop after the calculation returns
# (tens of milliseconds measured), plus the page's own request set-up inside
# its 30 s.
EDGE_RESPONSE_MARGIN_SECONDS: Final = 4.0
COMPUTE_QUEUE_WAIT_BUDGET_SECONDS: Final = (
    EDGE_CHART_READ_TIMEOUT_SECONDS
    - COMPUTE_P99_ESTIMATE_SECONDS
    - EDGE_RESPONSE_MARGIN_SECONDS
)
API_PATH_PREFIX: Final = "/api/"
# "Takes a bounded JSON body" and "which admission pool" are separate
# questions with separate sets.
_BOUNDED_JSON_PATHS: Final = frozenset({CHART_ROUTE, PLACE_SEARCH_ROUTE, TIME_CONVERT_ROUTE})
_LOOKUP_PATHS: Final = frozenset({PLACE_SEARCH_ROUTE, TIME_CONVERT_ROUTE})
# The liveness probe returns a constant on the event loop and is never charged
# to a pool: a full pool of any class must not make the container look dead.
_ADMISSION_EXEMPT_PATHS: Final = frozenset({HEALTH_ROUTE})
BOUNDARY_REASON_STATE_KEY: Final = "armillary.boundary_reason.v1"
COMPUTE_ENTERED_STATE_KEY: Final = "armillary.compute_entered.v1"
# Set by the boundary the moment it learns the client has gone.  It is
# read synchronously before a queued chart enters Swiss, so a disconnect that
# arrives in the same loop turn as the lock hand-over is still honoured.
CLIENT_DISCONNECTED_STATE_KEY: Final = "armillary.client_disconnected.v1"
# Not a refusal: no response is written to a client that has gone.  It names,
# for telemetry only, why a request ended without one.
CLIENT_DISCONNECTED: Final = "client_disconnected"
CLOSURE_REASON_CODES: Final = frozenset({CLIENT_DISCONNECTED})

# One vocabulary owns every reason this boundary can place in the request
# scope.  Call sites still name the reason they observed; this set makes an
# unregistered new reason fail at the producer instead of disappearing later
# in telemetry or public documentation.
BOUNDARY_REASON_CODES: Final = frozenset({
    "undeclared_host",
    "unknown_api_path",
    "unsupported_method",
    "request_capacity_exhausted",
    "compute_capacity_exhausted",
    "request_headers_too_large",
    "unsupported_media_type",
    "conflicting_request_framing",
    "invalid_content_length",
    "request_body_too_large",
    "empty_request_body",
    "request_body_read_timeout",
})


def _state(scope: Scope) -> dict:
    """The request's scope state, created on first use."""

    state = scope.get("state")
    if not isinstance(state, dict):
        state = {}
        scope["state"] = state
    return state


def _mark_boundary_reason(scope: Scope, reason: str) -> None:
    if reason not in BOUNDARY_REASON_CODES:
        raise RuntimeError(f"unregistered request boundary reason: {reason}")
    state = _state(scope)
    if BOUNDARY_REASON_STATE_KEY in state:
        raise RuntimeError("request boundary reason was already assigned")
    state[BOUNDARY_REASON_STATE_KEY] = reason


async def _refuse(
    scope: Scope, receive: Receive, send: Send, code: str, **kwargs
) -> None:
    """Record the boundary reason, then send its refusal."""

    _mark_boundary_reason(scope, code)
    await refusal_response(code, **kwargs)(scope, receive, send)


def mark_compute_entered(scope: Scope) -> None:
    _state(scope)[COMPUTE_ENTERED_STATE_KEY] = True


def _compute_entered(scope: Scope) -> bool:
    state = scope.get("state")
    return isinstance(state, dict) and state.get(COMPUTE_ENTERED_STATE_KEY) is True


def mark_client_disconnected(scope: Scope) -> None:
    _state(scope)[CLIENT_DISCONNECTED_STATE_KEY] = True


def client_disconnected(scope: object) -> bool:
    if not isinstance(scope, dict):
        return False
    state = scope.get("state")
    return isinstance(state, dict) and state.get(CLIENT_DISCONNECTED_STATE_KEY) is True


class ClientDisconnectedBeforeCompute(Exception):
    """A queued chart reached the head of the queue after its client had gone."""


class _QueueWaiter:
    __slots__ = ("loop", "future", "granted")

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.future: asyncio.Future[None] = loop.create_future()
        self.granted = False


def _grant(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


class FifoComputeQueue:
    """First come, first served admission to the Swiss lock.

    Each waiter takes a place in line and a release hands ownership directly
    to the head of the line, so no later arrival can take it in between.  With
    polling, whichever poll landed first after a release would win, and the
    earliest arrival would be the one most likely to run out of its wait
    budget.

    Ownership passes under one thread lock, so a release from a worker thread
    and a waiter giving up (timeout or cancellation) cannot both decide who
    owns the queue.  A waiter that gives up after it was granted passes the
    grant on.  Nothing about a request is kept, only its place in line.
    """

    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._held = False
        self._waiters: deque[_QueueWaiter] = deque()

    @property
    def waiting(self) -> int:
        with self._mutex:
            return len(self._waiters)

    @property
    def held(self) -> bool:
        with self._mutex:
            return self._held

    async def acquire(self, timeout: float) -> bool:
        """Wait in line for at most `timeout` seconds; True once owned."""

        loop = asyncio.get_running_loop()
        with self._mutex:
            if not self._held and not self._waiters:
                self._held = True
                return True
            if timeout <= 0:
                return False
            waiter = _QueueWaiter(loop)
            self._waiters.append(waiter)
        try:
            # The shield keeps a timeout or cancellation from cancelling the
            # grant future itself; `granted` below is the one authority.
            await asyncio.wait_for(asyncio.shield(waiter.future), timeout)
            return True
        except BaseException as error:
            with self._mutex:
                owned = waiter.granted
                if not owned:
                    self._waiters.remove(waiter)
            timed_out = isinstance(error, TimeoutError)
            if owned and timed_out:
                # Granted in the same turn the budget ran out: it is ours.
                return True
            if owned:
                self.release()
            if timed_out:
                return False
            raise

    def release(self) -> None:
        with self._mutex:
            if not self._held:
                raise RuntimeError("compute queue released while not held")
            if self._waiters:
                waiter = self._waiters.popleft()
                waiter.granted = True
                waiter.loop.call_soon_threadsafe(_grant, waiter.future)
                return
            self._held = False


def is_api_path(path: str) -> bool:
    """The API prefix, bare `/api` included; the static mount and the
    cache policy draw the same line."""

    return path == API_PATH_PREFIX.rstrip("/") or path.startswith(API_PATH_PREFIX)


class ApiMethodBoundary:

    def __init__(
        self,
        app: ASGIApp,
        *,
        route_methods: Mapping[str, frozenset[str]],
    ) -> None:
        self.app = app
        self.route_methods = dict(route_methods)

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") == "http":
            path = scope["path"]
            methods = self.route_methods.get(path)
            # The API boundary answers for the whole API prefix, so an
            # unregistered /api path never falls through to the frontend asset
            # mount (which would answer 405 with no Allow header).
            if methods is None and is_api_path(path):
                await _refuse(scope, receive, send, "unknown_api_path")
                return
            if methods is not None and scope.get("method") not in methods:
                await _refuse(
                    scope, receive, send, "unsupported_method",
                    headers={"Allow": ", ".join(sorted(methods))},
                )
                return
        await self.app(scope, receive, send)


class RequestCapacityBoundary:

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_concurrent: int = MAX_HOSTED_REQUESTS_PER_WORKER,
        max_compute_concurrent: int = MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER,
        max_search_concurrent: int = MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER,
    ) -> None:
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")
        if max_compute_concurrent <= 0:
            raise ValueError("max_compute_concurrent must be positive")
        if max_search_concurrent <= 0:
            raise ValueError("max_search_concurrent must be positive")
        self.app = app
        self.max_concurrent = max_concurrent
        self.max_compute_concurrent = max_compute_concurrent
        self.max_search_concurrent = max_search_concurrent
        self._active = 0
        self._active_compute = 0
        self._active_search = 0
        self._lock = threading.Lock()

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        path = scope.get("path")
        if scope["type"] != "http" or path in _ADMISSION_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        compute = path == CHART_ROUTE
        search = path in _LOOKUP_PATHS
        with self._lock:
            if compute:
                accepted = self._active_compute < self.max_compute_concurrent
                if accepted:
                    self._active_compute += 1
            elif search:
                accepted = self._active_search < self.max_search_concurrent
                if accepted:
                    self._active_search += 1
            else:
                accepted = self._active < self.max_concurrent
                if accepted:
                    self._active += 1
        if not accepted:
            # Lookup and general refusals share the non-compute code; the
            # request event's `route` says which pool answered.
            await _refuse(
                scope, receive, send,
                "compute_capacity_exhausted" if compute else "request_capacity_exhausted",
            )
            return

        try:
            if compute:
                await self._run_compute(scope, receive, send)
            else:
                await self.app(scope, receive, send)
        finally:
            with self._lock:
                if compute:
                    self._active_compute -= 1
                elif search:
                    self._active_search -= 1
                else:
                    self._active -= 1

    async def _run_compute(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=1)
        disconnected = asyncio.Event()

        async def pump() -> None:
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    mark_client_disconnected(scope)
                    disconnected.set()
                    if not queue.full():
                        queue.put_nowait(message)
                    return
                await queue.put(message)

        async def receive_brokered() -> Message:
            if disconnected.is_set() and queue.empty():
                return {"type": "http.disconnect"}
            return await queue.get()

        pump_task = asyncio.create_task(pump())
        app_task: asyncio.Future[None] = asyncio.ensure_future(
            self.app(scope, receive_brokered, send)
        )
        try:
            done, _pending = await asyncio.wait(
                {pump_task, app_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if app_task in done:
                try:
                    await app_task
                except ClientDisconnectedBeforeCompute:
                    # The line reached this request after its client had
                    # gone (the pump has already marked it); no response is
                    # owed and none was started.
                    pass
                return
            error = pump_task.exception()
            if error is not None:
                app_task.cancel()
                with suppress(asyncio.CancelledError):
                    await app_task
                raise error
            if not _compute_entered(scope):
                app_task.cancel()
                with suppress(asyncio.CancelledError, ClientDisconnectedBeforeCompute):
                    await app_task
                return
            await app_task
        finally:
            for task in (pump_task, app_task):
                if not task.done():
                    task.cancel()
            for task in (pump_task, app_task):
                with suppress(asyncio.CancelledError):
                    await task


def _header_values(scope: Scope, name: bytes) -> list[bytes]:
    return [
        value
        for raw_name, value in scope.get("headers", [])
        if raw_name.lower() == name
    ]


def _header_bytes(scope: Scope) -> int:
    return sum(
        len(name) + len(value) + 4
        for name, value in scope.get("headers", [])
    )


def _content_length(scope: Scope) -> int | None:
    values = _header_values(scope, b"content-length")
    if not values:
        return None
    if len(values) != 1:
        raise ValueError("ambiguous content length")
    try:
        rendered = values[0].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("non-ASCII content length") from error
    if not rendered.isdecimal():
        raise ValueError("invalid content length")
    return int(rendered, 10)


def _has_conflicting_framing(scope: Scope) -> bool:

    return bool(
        _header_values(scope, b"content-length")
        and _header_values(scope, b"transfer-encoding")
    )


def _is_supported_json_content_type(scope: Scope) -> bool:
    values = _header_values(scope, b"content-type")
    if len(values) != 1:
        return False
    try:
        rendered = values[0].decode("ascii")
    except UnicodeDecodeError:
        return False
    parts = [part.strip() for part in rendered.split(";")]
    if parts[0].casefold() != "application/json":
        return False
    if len(parts) > 2:
        return False
    for parameter in parts[1:]:
        if "=" not in parameter:
            return False
        name, value = (item.strip() for item in parameter.split("=", maxsplit=1))
        if name.casefold() != "charset":
            return False
        # RFC 9110 §5.6.6: a token, or a quoted string quoted on both sides.
        if value.casefold() not in {"utf-8", '"utf-8"'}:
            return False
    return True


class ChartRequestBoundary:
    """Refuse an undeclared host, then bound hosted JSON POST bodies.

    The host check comes first, before any budget is spent on the request.
    Admission belongs to the proxy, which strips `Authorization` before
    forwarding; the application therefore has no authorization of its own and
    that is deliberate.  What it can do cheaply is notice that it was reached by
    a route the deployment never declared — the shape a published container port
    produces, where a scanner sends the address as the host.  A caller who can
    reach the socket can also set this header, so this catches the accident, not
    the attacker, and the difference is stated rather than implied.  Unset
    (development and tests) means no check.

    The header budget then applies to every path; the body limit runs before
    JSON/Pydantic parsing.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        expected_host: str | None = None,
        max_body_bytes: int = MAX_CHART_REQUEST_BYTES,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.expected_host = (expected_host or "").strip().lower() or None
        # The whole header is compared: a split at the first colon accepted
        # `host:anything`.  Only the scheme default ports may be spelled out.
        self.accepted_hosts = (
            frozenset({
                self.expected_host,
                f"{self.expected_host}:80",
                f"{self.expected_host}:443",
            })
            if self.expected_host is not None
            else frozenset()
        )
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if self.expected_host is not None and scope.get("type") == "http":
            raw = dict(scope.get("headers") or ()).get(b"host", b"").decode("latin-1")
            if raw.strip().lower() not in self.accepted_hosts:
                await _refuse(scope, receive, send, "undeclared_host")
                return
        # Every path, not only the JSON posts: the application states its own
        # header budget instead of leaving the only bound to the edge.
        if (
            scope.get("type") == "http"
            and _header_bytes(scope) > MAX_HOSTED_HEADER_BYTES
        ):
            await _refuse(scope, receive, send, "request_headers_too_large")
            return
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in _BOUNDED_JSON_PATHS
        ):
            await self.app(scope, receive, send)
            return

        try:
            content_length = _content_length(scope)
        except ValueError:
            content_length = -1
        # In order: the first failing header check answers.  A declared empty
        # body would otherwise reach Pydantic as a JSON parse failure and come
        # back as a 422 listing every missing field, which describes the schema
        # rather than the actual fault; the framing is this boundary's own.
        refusal = (
            "unsupported_media_type"
            if not _is_supported_json_content_type(scope)
            else "conflicting_request_framing"
            if _has_conflicting_framing(scope)
            else "invalid_content_length"
            if content_length == -1
            else "request_body_too_large"
            if content_length is not None and content_length > self.max_body_bytes
            else "empty_request_body"
            if content_length == 0
            else None
        )
        if refusal is not None:
            await _refuse(scope, receive, send, refusal)
            return

        # Read the complete, already bounded JSON body before entering the
        # application.  This prevents an application that responds before
        # consuming its whole receive stream from starting a 2xx response and
        # only then discovering a late oversized chunk.  It is also why this
        # boundary sits outside admission: a body still arriving holds no pool
        # slot, and the deadline covers the whole body rather than each chunk.
        buffered: list[Message] = []
        received_bytes = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + REQUEST_BODY_DEADLINE_SECONDS
        while True:
            try:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                message = await asyncio.wait_for(receive(), timeout=remaining)
            except TimeoutError:
                await _refuse(scope, receive, send, "request_body_read_timeout")
                return
            if message["type"] != "http.request":
                # The client went away before its body was complete.
                # Nothing is owed to it, and the application would only have
                # failed to parse half a body and been logged as a 500.
                mark_client_disconnected(scope)
                return
            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_body_bytes:
                await _refuse(scope, receive, send, "request_body_too_large")
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break

        async def receive_buffered() -> Message:
            if buffered:
                return buffered.pop(0)
            # Once the bounded body has been replayed, preserve the real ASGI
            # receive channel.  Fabricating disconnect here made every normal
            # request look abandoned to downstream admission control.
            return await receive()

        await self.app(scope, receive_buffered, send)
