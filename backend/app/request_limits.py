"""Pure-ASGI request boundary for hosted JSON calculation/search endpoints."""

from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
import threading
from typing import Final, Mapping

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .refusals import (
    ANNUAL_ROUTE,
    CHART_ROUTE,
    HEALTH_ROUTE,
    PLACE_SEARCH_ROUTE,
    READY_ROUTE,
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
# evenly and only one worker's pool is guaranteed (measured on 2026-10-04).
MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER: Final = 4
# The annual route's own pool.  An annual projection with every technique and
# lifetime scopes at an approximate hour measured 0.44-0.46 CPU-s (2026-10-26,
# Apple M-series, in process, 1 to 300 completed years, Taipei and 68.5 N), and
# a 2026-10-24 review measured 0.59 CPU-s on amd64.  It once held a chart slot
# while waiting for Swiss, so an annual burst left no chart admitted.  Both still
# share the one Swiss line, where an annual request delays a chart by its own
# compute time only.  Eight admitted annual requests wait in that line within
# the queue budget rather than being refused on arrival; at 0.6 s each a full
# annual pool delays a chart by about 5 s, inside the budget, and the chart pool
# stays separate.
MAX_HOSTED_ANNUAL_REQUESTS_PER_WORKER: Final = 8
# Place lookup and time conversion.  A lookup holds a worker thread for up to
# the catalogue statement budget, and in the general pool a burst of lookups
# refused assets and the health probe.  A time conversion is microseconds, but
# its body is birth data and it is the same explicit-action kind, so it shares
# this pool.  The page starts either only on an explicit action and aborts the
# previous one, so four per worker is not a typeahead budget.
MAX_HOSTED_SEARCH_REQUESTS_PER_WORKER: Final = 4
# RETRY_AFTER_SECONDS (re-exported above) is the one retry contract for every
# admission refusal; refusal_response adds it.
# Total time for a bounded JSON body, first read to last byte.  A per-chunk
# gap timeout let one byte per gap keep a 16 KiB body arriving for hours.
# Deployed, NGINX buffers the body first (`proxy_request_buffering on`,
# `client_body_timeout 10s`), so this is defence in depth; how many connections
# sit in the body phase is the edge's `limit_conn`.
REQUEST_BODY_DEADLINE_SECONDS: Final = 10.0
# The Swiss-lock wait budget is derived from who waits for the answer.  The
# edge gives `/api/chart` 30 s (`proxy_read_timeout` in `location = /api/chart`
# of deploy/staging/nginx-site.conf.template) and the page aborts at 30 s
# (`REQUEST_TIMEOUT_MS` in frontend/zh-TW/calculate.js); tests/backend/
# test_compute_queue.py pins both copies, since the template cannot import it.
# A chart starting later than the budget would, at p99, finish after both gave
# up, so it is refused while the refusal is still readable and retryable.
EDGE_CHART_READ_TIMEOUT_SECONDS: Final = 30.0
# p99 wall time of one chart: an estimate, not a host measurement.  Slowest
# local request (Apple M1, 2026-10-10) ~1.5 s CPU, every module at 69°N, date
# only, 2150 (~6.5 s before the direction-aware rise/set pre-filter; at the end
# of 2399 only the search modules are refused out-of-coverage, before any Swiss
# call); ~2.9 s worst-options under amd64 emulation (2026-10-04), doubled when
# two workers share one CPU.  2026-10-18: pre-filter reads the request's
# refraction and each body's disc on a shared fixed day grid; slowest polar
# chart 2,505 -> 327 Swiss probes (median CPU 1.27 -> 0.19 s, 68.5 N,
# 2150-03-21, date only).  The slowest chart is no longer a polar date-only
# one but every module at an approximate hour, whose birth-time sensitivity
# probes re-derive the extended lots: 0.84 CPU-s at 68.5 N, 2150-12-21 on an
# idle 8-vCPU amd64 host, and 1.2-1.75 CPU-s on a loaded host (two later
# reviews), well inside this estimate.  2026-10-26 sweep (Apple M-series, in
# process): Placidus at 2200-12-21 on the southern polar circle, approximate
# hour, 0.79 CPU-s against a 0.22 median; tests/backend/test_compute_cost.py
# holds that chart under 3 CPU-s and under 8x an ordinary one.  Revisit with a
# production-host measurement.
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
# The calculation pool.  An app registering another calculation route (the
# flagged annual route) passes both sets; an unregistered route is never
# admitted here and reaches unknown_api_path like any undeclared path.
_COMPUTE_PATHS: Final = frozenset({CHART_ROUTE})
_LOOKUP_PATHS: Final = frozenset({PLACE_SEARCH_ROUTE, TIME_CONVERT_ROUTE})
# The liveness probe returns a constant on the event loop and is never charged
# to a pool: a full pool of any class must not make the container look dead.
# The readiness probe reads the cached ephemeris manifest (a stat per file
# unless the files changed), so it is exempt for the same reason.
_ADMISSION_EXEMPT_PATHS: Final = frozenset({HEALTH_ROUTE, READY_ROUTE})
BOUNDARY_REASON_STATE_KEY: Final = "armillary.boundary_reason.v1"
COMPUTE_ENTERED_STATE_KEY: Final = "armillary.compute_entered.v1"
# Read synchronously before a queued chart enters Swiss, so a disconnect in
# the same loop turn as the lock hand-over is still honoured.
CLIENT_DISCONNECTED_STATE_KEY: Final = "armillary.client_disconnected.v1"
# Not a refusal: no response is written to a client that has gone.  It names,
# for telemetry only, why a request ended without one.
CLIENT_DISCONNECTED: Final = "client_disconnected"
CLOSURE_REASON_CODES: Final = frozenset({CLIENT_DISCONNECTED})

# Every reason this boundary can place in the request scope: an unregistered
# reason fails at the producer instead of vanishing in telemetry or docs.
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

    A release hands ownership directly to the head of the line, so no later
    arrival can take it in between (with polling, the earliest arrival was the
    most likely to run out of budget).

    Ownership passes under one thread lock, so a worker-thread release and a
    waiter giving up cannot both decide who owns the queue; a waiter that gives
    up after being granted passes the grant on.  Nothing about a request is
    kept, only its place in line.
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
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
        max_annual_concurrent: int = MAX_HOSTED_ANNUAL_REQUESTS_PER_WORKER,
        compute_paths: frozenset[str] = _COMPUTE_PATHS,
    ) -> None:
        self._limits = {
            "max_concurrent": max_concurrent,
            "max_compute_concurrent": max_compute_concurrent,
            "max_search_concurrent": max_search_concurrent,
            "max_annual_concurrent": max_annual_concurrent,
        }
        for name, limit in self._limits.items():
            if limit <= 0:
                raise ValueError(f"{name} must be positive")
        self.app = app
        self.compute_paths = frozenset(compute_paths)
        # Admitted requests per pool, keyed like the limits.
        self._active = dict.fromkeys(self._limits, 0)
        self._lock = threading.Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path")
        if scope["type"] != "http" or path in _ADMISSION_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        compute = path in self.compute_paths
        # The annual calculation has its own pool; every other calculation
        # path counts against the chart's.
        if compute:
            pool = "max_annual_concurrent" if path == ANNUAL_ROUTE else "max_compute_concurrent"
        else:
            pool = "max_search_concurrent" if path in _LOOKUP_PATHS else "max_concurrent"
        with self._lock:
            accepted = self._active[pool] < self._limits[pool]
            if accepted:
                self._active[pool] += 1
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
                self._active[pool] -= 1

    async def _run_compute(self, scope: Scope, receive: Receive, send: Send) -> None:
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

    The host check comes first, before any budget is spent.  The service is
    public and deliberately has no authorization; the proxy sets the declared
    host and strips `Authorization`, `Proxy-Authorization` and forwarding
    headers.  The check notices a route the deployment never declared — a
    published container port, where a scanner sends the address as the host.
    A caller who can reach the socket can also set this header, so this catches
    the accident, not the attacker.  Unset (development and tests): no check.

    The header budget then applies to every path; the body limit runs before
    JSON/Pydantic parsing.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        expected_host: str | None = None,
        max_body_bytes: int = MAX_CHART_REQUEST_BYTES,
        bounded_json_paths: frozenset[str] = _BOUNDED_JSON_PATHS,
    ) -> None:
        if max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.bounded_json_paths = frozenset(bounded_json_paths)
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.expected_host is not None and scope.get("type") == "http":
            # RFC 9110 §7.2 / RFC 9112 §3.2: more than one Host is refused.
            # A dict over the headers kept the last copy while Starlette reads
            # the first, so the check and the application could disagree.
            hosts = _header_values(scope, b"host")
            raw = hosts[0].decode("latin-1") if len(hosts) == 1 else ""
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
            or scope.get("path") not in self.bounded_json_paths
        ):
            await self.app(scope, receive, send)
            return

        try:
            content_length = _content_length(scope)
        except ValueError:
            content_length = -1
        # The first failing header check answers.  A declared empty body would
        # otherwise come back as a 422 listing every missing field, describing
        # the schema rather than the fault.
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

        # Buffer the whole bounded body first, so an app that responds before
        # draining receive cannot start a 2xx and then meet an oversized chunk.
        # Also why this sits outside admission: an arriving body holds no slot.
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
                # Client gone mid-body: nothing is owed, and the app would only
                # have failed to parse half a body as a logged 500.
                mark_client_disconnected(scope)
                return
            received_bytes += len(message.get("body", b""))
            if received_bytes > self.max_body_bytes:
                await _refuse(scope, receive, send, "request_body_too_large")
                return
            buffered.append(message)
            if not message.get("more_body", False):
                break
        if received_bytes == 0:
            # A chunked body that ends at once is as empty as Content-Length: 0.
            await _refuse(scope, receive, send, "empty_request_body")
            return

        async def receive_buffered() -> Message:
            if buffered:
                return buffered.pop(0)
            # Then the real channel: fabricating a disconnect here made every
            # request look abandoned to downstream admission control.
            return await receive()

        await self.app(scope, receive_buffered, send)
