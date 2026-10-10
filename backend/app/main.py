"""FastAPI application: the HTTP boundary, the Swiss compute line and identity.

The chart itself is computed by ``chart_pipeline`` (typed stages from a
request to one response); this module admits, queues, refuses and routes.
Importing it imports the pipeline, which binds the bundled ephemeris.
"""

import asyncio
import os
from pathlib import Path
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from typing import Any

import swisseph as swe
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse

from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ephemeris import (
    FULL_EPHEMERIS_OUT_OF_COVERAGE,
    FullEphemerisRequiredError,
    release_ephemeris_for_thread,
)
from .schemas import (
    ChartRequest,
    PlaceSearchRequest,
    RefusalResponse,
    StrictJsonBodyError,
    check_strict_json_body,
    check_strict_query,
    validation_issues,
)
from .refusals import (
    CHART_ROUTE,
    HEALTH_ROUTE,
    PLACE_SEARCH_ROUTE,
    refusal_response,
    routes_refusals,
)
from .core.time_utils import (
    AmbiguousLocalTimeChoiceRequiredError,
    NonexistentLocalTimeError,
)
from .core.houses import HouseSystemUnavailableError
from .core.dossier import DOSSIER_VERSION
from .response_projection import (
    DEFAULT_CHART_PROJECTION,
    ChartProjection,
    project_chart_response,
)
from .core.place_catalog import (
    PlaceCatalog,
    PlaceCatalogUnavailableError,
    PlaceSearchBudgetExceededError,
)
from .privacy_logging import (
    DOMAIN_ERROR_STATE_KEY,
    PrivacyBoundaryMiddleware,
    emit_security_event,
    silence_server_access_log,
)
from .request_limits import (
    COMPUTE_QUEUE_WAIT_BUDGET_SECONDS,
    ApiMethodBoundary,
    ChartRequestBoundary,
    ClientDisconnectedBeforeCompute,
    FifoComputeQueue,
    RequestCapacityBoundary,
    client_disconnected,
    is_api_path,
    mark_compute_entered,
)
from .runtime_static import ChartResultCompression, RuntimeStaticFiles
from .frontend_release import load_runtime_release
from .frontend_assets import discover_source_assets
from .settings import AppSettings, load_settings

# Imported last: importing the pipeline binds the bundled ephemeris path and
# reads the bundled file set once, after every other module has loaded.
from .chart_pipeline import SCHEMA_VERSION, compute_chart_response


async def health_check() -> dict[str, object]:
    """Report process liveness, not end-to-end calculation readiness.

    Answered on the event loop rather than a worker thread, and never charged
    to an admission pool, so a full lookup, calculation or asset pool
    does not refuse the container's own probe.
    """
    return {
        "status": "ok",
        "ready": True,
        "readiness_scope": "process_liveness_only",
    }


def _refuse(request: Request, code: str, **kwargs: Any) -> JSONResponse:
    """Every refusal written here: record the closed code, then serialize once."""

    request.scope.setdefault("state", {})[DOMAIN_ERROR_STATE_KEY] = code
    return refusal_response(code, **kwargs)


async def _handle_domain_error(request: Request, exc: Exception):
    """Map closed domain failures without giving each class a parallel owner."""

    code = (
        "swiss_ephemeris_error"
        if isinstance(exc, swe.Error)
        else getattr(exc, "code", "internal_server_error")
    )
    # Only an instant outside the bundled coverage is the request's own,
    # deterministic refusal (422).  A segment file missing from this deployment,
    # or a Swiss fallback the manifest said could not happen, is the server's.
    if (
        isinstance(exc, FullEphemerisRequiredError)
        and exc.reason != FULL_EPHEMERIS_OUT_OF_COVERAGE
    ):
        code = "internal_server_error"
    return _refuse(request, code, extra=getattr(exc, "detail_extra", None))


# Starlette's static mount and FastAPI's body reader raise these statuses and no
# others in the installed versions; anything else is a server fault and says so.
_FRAMEWORK_REFUSAL_CODES = {
    400: "bad_request",
    401: "unauthorized",
    404: "not_found",
    405: "method_not_allowed",
}
# The static mount serves GET and HEAD only, and is the one producer that raises
# 405 without naming them.  RFC 9110 §15.5.6: a 405 must carry Allow.
_STATIC_MOUNT_METHODS = "GET, HEAD"


async def _handle_http_exception(request: Request, exc: Exception):
    """Give the framework's own refusals the one shape this service declares.

    Every refusal, the framework's included, carries the same object-shaped
    `detail`, so a consumer can branch on it.
    """

    status_code = getattr(exc, "status_code", 500)
    headers = dict(getattr(exc, "headers", None) or {})
    if status_code == 405 and "allow" not in {name.lower() for name in headers}:
        headers["Allow"] = _STATIC_MOUNT_METHODS
    return _refuse(
        request,
        _FRAMEWORK_REFUSAL_CODES.get(status_code, "internal_server_error"),
        headers=headers or None,
    )


def _declared_parameter_names(request: Request) -> frozenset[str]:
    # Query parameters are declared by the routes, not by the body models.
    return frozenset(
        parameter.name
        for route in getattr(request.scope.get("app"), "routes", ())
        if isinstance(route, APIRoute)
        for parameter in route.dependant.query_params
    )


async def _handle_request_validation(
    request: Request,
    exc: RequestValidationError,
):
    issues = validation_issues(
        exc.errors(), parameter_names=_declared_parameter_names(request)
    )
    # A body the parser never read is a syntax refusal, not a field finding.
    if any(issue["type"] == "json_invalid" for issue in issues):
        return _refuse(request, "json_invalid")
    return _refuse(request, "request_validation_failed", issues=issues)


async def _handle_strict_json_body(request: Request, exc: StrictJsonBodyError):
    return _refuse(request, exc.code, issues=exc.issues)


class _StrictJsonRoute(APIRoute):
    """Read a JSON body as exactly one UTF-8 JSON text before FastAPI parses it.

    FastAPI hands the bytes to `json.loads`, which detects UTF-16/32, skips a
    BOM and keeps the last of two equal keys.  The request
    boundary has already bounded these bytes; this refuses what another reader
    could read differently, then lets FastAPI parse the same buffered body.
    """

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()
        has_body = self.body_field is not None
        if not has_body and not is_api_path(self.path):
            # The `/` redirect is a page address, not an API contract.
            return handler
        declared_query = frozenset(
            parameter.alias for parameter in self.dependant.query_params
        )

        # One query rule for every API route.  A GET or HEAD route declares no
        # query, so any parameter is refused, as on the POST routes, without
        # echoing it.
        async def strict_handler(request: Request) -> Response:
            check_strict_query(request.query_params.multi_items(), declared_query)
            if has_body:
                check_strict_json_body(await request.body())
            return await handler(request)

        return strict_handler


# Swiss center／sidereal mode are process-global; serialize per worker.  The
# line is the mutual exclusion: requests are admitted in arrival order
# and a place is released only when its Swiss worker thread has exited.
_COMPUTE_QUEUE = FifoComputeQueue()

# Bound queue wait without interrupting an in-flight Swiss calculation.  The
# budget is derived from the edge read timeout and the p99 compute estimate in
# request_limits, so wait plus compute stays inside what the edge waits for.
_COMPUTE_LOCK_WAIT_TIMEOUT_SECONDS = COMPUTE_QUEUE_WAIT_BUDGET_SECONDS
_BUILD_IDENTITY_CONTEXT: ContextVar[dict | None] = ContextVar(
    "classical_astrology_build_identity",
    default=None,
)


class ComputeCapacityExhaustedError(Exception):
    """Waiting in the Swiss compute line exceeded the bounded queue budget."""

    code = "compute_capacity_exhausted"


def _compute_chart_in_worker(req: ChartRequest):
    try:
        return _compute_chart_locked(req)
    finally:
        release_ephemeris_for_thread()


async def compute_chart_for_request(req: ChartRequest, request: Request):
    """Wait in line for Swiss, then compute; cancel only queued work.

    The line is first come, first served, and the wait is bounded from arrival.
    A request whose client has gone never enters Swiss: the check and the mark
    that it entered happen in one event-loop step, so a disconnect noticed in
    the same turn as the hand-over still wins.  Once Swiss starts, the place
    in line and the admission are kept until its worker exits.
    """

    if not await _COMPUTE_QUEUE.acquire(timeout=_COMPUTE_LOCK_WAIT_TIMEOUT_SECONDS):
        raise ComputeCapacityExhaustedError()
    handed_to_worker = False
    try:
        scope = getattr(request, "scope", None)
        if client_disconnected(scope):
            raise ClientDisconnectedBeforeCompute()
        if isinstance(scope, dict):
            mark_compute_entered(scope)

        worker = asyncio.create_task(run_in_threadpool(_compute_chart_in_worker, req))
        # The place in line is released when the worker exits, not when this
        # request returns, so a cancelled request cannot let the next one in
        # while Swiss is still running.
        worker.add_done_callback(lambda _task: _COMPUTE_QUEUE.release())
        handed_to_worker = True
    finally:
        if not handed_to_worker:
            _COMPUTE_QUEUE.release()
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Native Swiss work cannot be cancelled safely.  Keep this request's
        # capacity and its place in line until its worker actually exits.
        await asyncio.shield(worker)
        raise


def _compute_chart_locked(req: ChartRequest):
    return compute_chart_response(
        req,
        build_identity=_BUILD_IDENTITY_CONTEXT.get() or {
            "status": "unavailable",
            "source_revision": None,
            "revision_source": None,
        },
    )


def _declared_refusals(route: str) -> dict[int | str, dict[str, Any]]:
    # Every status a route can refuse with, and the closed codes
    # that arrive under it, read from the one refusal table.
    return {
        status: {
            "model": RefusalResponse,
            "description": "Refusal codes: " + ", ".join(codes),
        }
        for status, codes in routes_refusals(route).items()
    }


def _add_api_routes(
    application: FastAPI,
    *,
    place_catalog: PlaceCatalog,
    runtime_build_identity: dict,
) -> dict[str, frozenset[str]]:
    """The three API routes; returns the methods each one serves."""

    async def identified_compute_chart(
        req: ChartRequest,
        request: Request,
        projection: ChartProjection = DEFAULT_CHART_PROJECTION,
    ):
        token = _BUILD_IDENTITY_CONTEXT.set(runtime_build_identity)
        try:
            # page is derived from this one detailed response.
            return project_chart_response(
                await compute_chart_for_request(req, request), projection
            )
        finally:
            _BUILD_IDENTITY_CONTEXT.reset(token)

    def search_places(request: PlaceSearchRequest):
        return place_catalog.search(
            query=request.query,
            country_code=request.country_code,
            limit=request.limit,
        )

    api_method_routes = {
        # HEAD wherever GET is served.
        "/api/health": frozenset({"GET", "HEAD"}),
        "/api/chart": frozenset({"POST"}),
        "/api/places/search": frozenset({"POST"}),
    }
    # GET and HEAD are separate routes so each has its own OpenAPI operation ID;
    # one route carrying both methods published a duplicate ID.
    for method, route_name in (("GET", "health_check"), ("HEAD", "health_check_head")):
        application.add_api_route(
            "/api/health",
            health_check,
            methods=[method],
            name=route_name,
            response_model=dict[str, object],
            response_description=(
                "Process-liveness response; this is not end-to-end calculation readiness."
            ),
            responses=_declared_refusals(HEALTH_ROUTE),
        )
    application.add_api_route(
        "/api/chart",
        identified_compute_chart,
        methods=["POST"],
        name="compute_chart",
        response_model=dict[str, Any],
        response_description=(
            "Versioned chart response; see output_contract and deploy/frontend-contract.json."
        ),
        responses=_declared_refusals(CHART_ROUTE),
    )
    application.add_api_route(
        "/api/places/search",
        search_places,
        methods=["POST"],
        name="search_places",
        response_model=dict[str, Any],
        response_description=(
            "Bundled-catalog search response with query and execution receipts."
        ),
        responses=_declared_refusals(PLACE_SEARCH_ROUTE),
    )
    return api_method_routes


def _add_refusal_handlers(application: FastAPI) -> None:
    # Validation output never echoes rejected birth values.
    for error_type, handler in (
        (NonexistentLocalTimeError, _handle_domain_error),
        (AmbiguousLocalTimeChoiceRequiredError, _handle_domain_error),
        (FullEphemerisRequiredError, _handle_domain_error),
        (HouseSystemUnavailableError, _handle_domain_error),
        (PlaceCatalogUnavailableError, _handle_domain_error),
        (PlaceSearchBudgetExceededError, _handle_domain_error),
        (StrictJsonBodyError, _handle_strict_json_body),
        (RequestValidationError, _handle_request_validation),
        (ComputeCapacityExhaustedError, _handle_domain_error),
        (swe.Error, _handle_domain_error),
        (StarletteHTTPException, _handle_http_exception),
    ):
        application.add_exception_handler(error_type, handler)  # type: ignore[arg-type]


def _mount_frontend(
    application: FastAPI,
    frontend_dir: str,
    release_assets: Any,
) -> Callable[[str], str | None] | None:
    """Mount the frontend when it exists; returns its content-version source."""

    # The public cache policy asks the static mount for the content
    # version of the bytes it serves.  Without a mounted frontend there is no
    # version source, and nothing is ever immutable.
    if not os.path.isdir(frontend_dir):
        return None
    allowed_assets = (
        release_assets
        if release_assets is not None
        else discover_source_assets(Path(frontend_dir))
    )
    @application.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
    async def redirect_default_locale() -> RedirectResponse:
        """Keep the public entry deterministic; never infer browser language."""
        return RedirectResponse(url="/zh-TW/", status_code=308)

    runtime_static = RuntimeStaticFiles(
        directory=frontend_dir,
        html=True,
        allowed_assets=allowed_assets,
    )
    application.mount("/", runtime_static, name="frontend")
    return runtime_static.content_version


def _add_boundary_middleware(
    application: FastAPI,
    *,
    api_method_routes: dict[str, frozenset[str]],
    expected_host: Any,
    event_emitter: Callable[[dict], bool] | None,
    static_asset_version: Callable[[str], str | None] | None,
) -> None:
    # Innermost: it sees only what the routes and their refusal handlers send,
    # and the privacy boundary adds Cache-Control and the security headers to
    # both representations.
    application.add_middleware(ChartResultCompression)
    application.add_middleware(
        ApiMethodBoundary,
        route_methods=api_method_routes,
    )

    # Middleware order is inside-out: the last one added runs first.  The host
    # check, header-decidable refusals and the bounded body (size and total
    # deadline) come before admission, so a body still arriving holds no
    # compute or lookup slot.
    application.add_middleware(RequestCapacityBoundary)
    application.add_middleware(ChartRequestBoundary, expected_host=expected_host)

    # Privacy remains the outer user middleware so it can contain downstream
    # response-lifecycle failures and apply headers to request-boundary errors.
    # The lambda preserves existing tests that replace the module-level sink.
    emitter = event_emitter or (lambda event: emit_security_event(event))
    application.add_middleware(
        PrivacyBoundaryMiddleware,
        event_emitter=emitter,
        cache_policy="public_split",
        asset_content_version=static_asset_version,
    )


def create_app(
    settings: AppSettings | None = None,
    *,
    event_emitter: Callable[[dict], bool] | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    silence_server_access_log()
    authority_root = os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    release_frontend_root, release_identity, release_assets = load_runtime_release(
        environment=os.environ,
        authority_root=Path(authority_root),
        backend_public_source_revision=resolved_settings.source_revision,
        api_schema_version=SCHEMA_VERSION,
        dossier_version=DOSSIER_VERSION,
    )
    runtime_build_identity = dict(resolved_settings.build_identity)
    if release_identity is not None:
        runtime_build_identity["release_identity"] = release_identity
    place_catalog = PlaceCatalog(resolved_settings.place_catalog_path)
    application = FastAPI(
        title="古典西洋占星天文計算 API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    # Every API route reads its JSON body strictly.
    application.router.route_class = _StrictJsonRoute
    api_method_routes = _add_api_routes(
        application,
        place_catalog=place_catalog,
        runtime_build_identity=runtime_build_identity,
    )
    _add_refusal_handlers(application)
    frontend_dir = str(
        release_frontend_root
        if release_frontend_root is not None
        else Path(authority_root) / "frontend"
    )
    static_asset_version = _mount_frontend(
        application, frontend_dir, release_assets
    )
    _add_boundary_middleware(
        application,
        api_method_routes=api_method_routes,
        expected_host=resolved_settings.expected_host,
        event_emitter=event_emitter,
        static_asset_version=static_asset_version,
    )
    return application



# `uvicorn app.main:app` and the tests read a module-level application; it is
# built on that first read, not at import, because the image's
# `uvicorn --factory app.main:create_app` imports this module and then calls the
# factory, and an import-time build would make a second, unused application in
# every worker.
app: FastAPI


def __getattr__(name: str) -> FastAPI:
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    application = create_app()
    globals()["app"] = application
    return application
