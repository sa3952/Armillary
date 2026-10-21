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
from typing import Any, cast

import swisseph as swe
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

import anyio.to_thread
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ephemeris import (
    FULL_EPHEMERIS_OUT_OF_COVERAGE,
    FullEphemerisRequiredError,
    refresh_ephemeris_file_manifest,
    release_ephemeris_for_thread,
)
from .schemas import AnnualRequest, PlaceSearchRequest, TimeConversionRequest
from .schema_chart import ChartRequest
from .schema_refusals import (
    RefusalResponse,
    StrictJsonBodyError,
    check_strict_json_body,
    check_strict_query,
    request_field_names,
    validation_issues,
)
from .refusals import (
    ANNUAL_ROUTE,
    CHART_ROUTE,
    HEALTH_ROUTE,
    PLACE_SEARCH_ROUTE,
    READY_ROUTE,
    TIME_CONVERT_ROUTE,
    refusal_response,
    routes_refusals,
)
from .core.time_utils import (
    AmbiguousLocalTimeChoiceRequiredError,
    NonexistentLocalTimeError,
    earth_rotation_memo,
)
from .core.civil_time_basis import (
    CivilTimeBasisNotApplicableError,
    CivilTimeBasisRequiredError,
)
from .core.houses import HouseSystemUnavailableError
from .core.time_conversion import (
    TimeConversionZoneNotCoveredError,
    convert_civil_time,
)
from .core.dossier import DOSSIER_VERSION
from .response_projection import (
    DEFAULT_CHART_PROJECTION,
    ChartProjection,
    project_chart_response,
)
from .annual_projection import project_annual_response
from .core.place_catalog import (
    CatalogLocationMismatchError,
    CatalogRecordUnknownError,
    PlaceCatalog,
    PlaceCatalogUnavailableError,
    PlaceSearchBudgetExceededError,
    check_request_places,
)
from .privacy_logging import (
    DOMAIN_ERROR_STATE_KEY,
    PrivacyBoundaryMiddleware,
    emit_security_event,
    silence_server_access_log,
)
from .request_limits import (
    _BOUNDED_JSON_PATHS,
    _COMPUTE_PATHS,
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
from .annual_pipeline import (
    SolarReturnOutsideSupportedYearRangeError,
    compute_annual_response,
)


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


def ephemeris_ready() -> bool:
    """Every bundled ephemeris input is present and has its pinned digest."""
    manifest = refresh_ephemeris_file_manifest()
    return bool(manifest) and all(
        entry["present"] and entry["matches_pinned_sha256"] for entry in manifest.values()
    )


# The probe is exempt from admission; one thread for all of its checks keeps a
# flood of probes from taking the threads place search and chart binding run on.
_READINESS_THREADS = anyio.CapacityLimiter(1)


async def readiness_check() -> Response:
    """Whether this process can calculate from its pinned ephemeris; a closed body."""
    ready = await anyio.to_thread.run_sync(ephemeris_ready, limiter=_READINESS_THREADS)
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "readiness_scope": "ephemeris_manifest"},
        status_code=200 if ready else 503,
    )


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
    """Give the framework's own refusals the same object-shaped `detail`."""

    status_code = getattr(exc, "status_code", 500)
    headers = dict(getattr(exc, "headers", None) or {})
    if status_code == 405 and "allow" not in {name.lower() for name in headers}:
        headers["Allow"] = _STATIC_MOUNT_METHODS
    return _refuse(
        request,
        _FRAMEWORK_REFUSAL_CODES.get(status_code, "internal_server_error"),
        headers=headers or None,
    )


def _declared_request_names(request: Request) -> frozenset[str]:
    # The answering route's own names only; no route means every name masked.
    return getattr(request.scope.get("route"), "declared_request_names", frozenset())


async def _handle_request_validation(
    request: Request,
    exc: RequestValidationError,
):
    issues = validation_issues(
        exc.errors(), declared_names=_declared_request_names(request)
    )
    # A body the parser never read is a syntax refusal, not a field finding.
    if any(issue["type"] == "json_invalid" for issue in issues):
        return _refuse(request, "json_invalid")
    return _refuse(request, "request_validation_failed", issues=issues)


async def _handle_annual_year_out_of_range(
    request: Request, exc: SolarReturnOutsideSupportedYearRangeError
):
    # Known only once the N-th return is found, but a fact about the requested
    # year: the same closed refusal as the other annual rules, at its field.
    return _refuse(
        request,
        "request_validation_failed",
        issues=[{"type": exc.code, "loc": ["body", "annual", "target_value"]}],
    )


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
        # pydantic types a field's annotation as any type form; every API body
        # here is a model, which request_field_names walks.
        declared_fields = request_field_names(
            cast("type[BaseModel] | None", self.body_field.field_info.annotation)
            if self.body_field is not None else None
        )
        # Read back by the validation handler: a refusal names only these.
        self.declared_request_names = declared_fields | declared_query

        # One query rule for every API route.  A GET or HEAD route declares no
        # query, so any parameter is refused, as on the POST routes, without
        # echoing it.
        async def strict_handler(request: Request) -> Response:
            check_strict_query(
                request.query_params.multi_items(), declared_query,
                request.scope.get("query_string", b""),
            )
            if has_body:
                check_strict_json_body(await request.body(), declared_fields)
            return await handler(request)

        return strict_handler


# Swiss center／sidereal mode are process-global; serialize per worker.  The
# FIFO line is the mutual exclusion.
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


def _in_worker(work: Callable[[Any], Any], req: Any):
    try:
        with earth_rotation_memo():
            return work(req)
    finally:
        release_ephemeris_for_thread()


async def compute_chart_for_request(req: ChartRequest, request: Request):
    return await _compute_in_line(_compute_chart_locked, req, request)


async def compute_annual_for_request(req: AnnualRequest, request: Request):
    return await _compute_in_line(_compute_annual_locked, req, request)


async def _compute_in_line(work: Callable[[Any], Any], req: Any, request: Request):
    """Wait in line for Swiss, then compute; cancel only queued work.

    A request whose client has gone never enters Swiss: the check and the
    entered mark happen in one event-loop step, so a disconnect noticed in the
    same turn as the hand-over still wins.
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

        worker = asyncio.create_task(run_in_threadpool(_in_worker, work, req))
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
        # Native Swiss work cannot be cancelled safely; hold capacity and the
        # line until the worker exits.
        await asyncio.shield(worker)
        raise


def _build_identity() -> dict:
    return _BUILD_IDENTITY_CONTEXT.get() or {
        "status": "unavailable",
        "source_revision": None,
        "revision_source": None,
    }


# The compute seams tests replace by name: _compute_in_line looks them up when
# a request arrives, so a patched one is the one that runs.
def _compute_chart_locked(req: ChartRequest):
    return compute_chart_response(req, build_identity=_build_identity())


def _compute_annual_locked(req: AnnualRequest):
    return compute_annual_response(req, build_identity=_build_identity())


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


async def _identified(req, request: Request, compute, project, projection, place_catalog, identity):
    # Before the compute line: a refusal here costs no Swiss slot.
    await run_in_threadpool(check_request_places, req, place_catalog.record)
    token = _BUILD_IDENTITY_CONTEXT.set(identity)
    try:
        # page is derived from this one detailed response.
        return project(await compute(req, request), projection)
    finally:
        _BUILD_IDENTITY_CONTEXT.reset(token)


def _add_api_routes(
    application: FastAPI,
    *,
    place_catalog: PlaceCatalog,
    runtime_build_identity: dict,
    enable_annual_route: bool = False,
) -> dict[str, frozenset[str]]:
    """The API routes; returns the methods each one serves.

    The annual route is a candidate: without its flag it is not registered,
    so it is an unknown API path and absent from the OpenAPI document.
    """

    async def identified_compute_chart(
        req: ChartRequest,
        request: Request,
        projection: ChartProjection = DEFAULT_CHART_PROJECTION,
    ):
        return await _identified(
            req, request, compute_chart_for_request, project_chart_response, projection,
            place_catalog, runtime_build_identity,
        )

    async def identified_compute_annual(
        req: AnnualRequest,
        request: Request,
        projection: ChartProjection = DEFAULT_CHART_PROJECTION,
    ):
        # The same natal input as /api/chart, so the same question first.
        return await _identified(
            req, request, compute_annual_for_request, project_annual_response, projection,
            place_catalog, runtime_build_identity,
        )

    def search_places(request: PlaceSearchRequest):
        return place_catalog.search(
            query=request.query,
            country_code=request.country_code,
            limit=request.limit,
        )

    # On the event loop: zone arithmetic for one wall-clock time, no Swiss and
    # no file; a worker thread would cost more than the answer.
    async def convert_time(request: TimeConversionRequest):
        return convert_civil_time(request)

    # GET and HEAD of the health route are separate routes so each has its own
    # OpenAPI operation ID; one route carrying both methods published a duplicate ID.
    routes: list[tuple[str, Callable[..., Any], str, str, Any, str]] = [
        (HEALTH_ROUTE, health_check, "GET", "health_check", dict[str, object],
         "Process-liveness response; this is not end-to-end calculation readiness."),
        (HEALTH_ROUTE, health_check, "HEAD", "health_check_head", dict[str, object],
         "Process-liveness response; this is not end-to-end calculation readiness."),
        (READY_ROUTE, readiness_check, "GET", "readiness_check", dict[str, object],
         "200 when the bundled ephemeris files are present and match their pinned digests; 503 otherwise."),
        (CHART_ROUTE, identified_compute_chart, "POST", "compute_chart", dict[str, Any],
         "Versioned chart response; see output_contract and deploy/frontend-contract.json."),
        (PLACE_SEARCH_ROUTE, search_places, "POST", "search_places", dict[str, Any],
         "Bundled-catalog search response with query and execution receipts."),
        (TIME_CONVERT_ROUTE, convert_time, "POST", "convert_time", dict[str, Any],
         "Every reading of one wall-clock time, with its rule's source row and the tz database."),
    ]
    if enable_annual_route:
        routes.append((
            ANNUAL_ROUTE, identified_compute_annual, "POST", "compute_annual", dict[str, Any],
            "Annual-techniques response (year boundary, profection, "
            "firdaria, extended lots, zodiacal releasing); see output_contract.",
        ))
    api_method_routes: dict[str, frozenset[str]] = {}
    for path, endpoint, method, name, model, description in routes:
        application.add_api_route(
            path, endpoint, methods=[method], name=name, response_model=model,
            response_description=description, responses=_declared_refusals(path),
        )
        api_method_routes[path] = api_method_routes.get(path, frozenset()) | {method}
    return api_method_routes


def _add_refusal_handlers(application: FastAPI) -> None:
    # Validation output never echoes rejected birth values.
    domain_errors = (
        NonexistentLocalTimeError, AmbiguousLocalTimeChoiceRequiredError,
        FullEphemerisRequiredError, HouseSystemUnavailableError, CivilTimeBasisRequiredError,
        CivilTimeBasisNotApplicableError, CatalogRecordUnknownError,
        CatalogLocationMismatchError, TimeConversionZoneNotCoveredError,
        PlaceCatalogUnavailableError, PlaceSearchBudgetExceededError,
    )
    for error_type, handler in (
        *((error, _handle_domain_error) for error in domain_errors),
        (StrictJsonBodyError, _handle_strict_json_body),
        (RequestValidationError, _handle_request_validation),
        (ComputeCapacityExhaustedError, _handle_domain_error),
        (SolarReturnOutsideSupportedYearRangeError, _handle_annual_year_out_of_range),
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

    # Without a mounted frontend there is no content-version source, so
    # nothing is ever cached as immutable.
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
        asset_digests=release_assets,
    )
    application.mount("/", runtime_static, name="frontend")
    return runtime_static.content_version


def _add_boundary_middleware(
    application: FastAPI,
    *,
    api_method_routes: dict[str, frozenset[str]],
    compute_paths: frozenset[str],
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
    application.add_middleware(RequestCapacityBoundary, compute_paths=compute_paths)
    application.add_middleware(
        ChartRequestBoundary,
        expected_host=expected_host,
        bounded_json_paths=_BOUNDED_JSON_PATHS | compute_paths,
    )

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
    application.router.route_class = _StrictJsonRoute
    api_method_routes = _add_api_routes(
        application,
        place_catalog=place_catalog,
        runtime_build_identity=runtime_build_identity,
        enable_annual_route=resolved_settings.enable_annual_route,
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
        compute_paths=_COMPUTE_PATHS | (
            {ANNUAL_ROUTE} if resolved_settings.enable_annual_route else frozenset()
        ),
        expected_host=resolved_settings.expected_host,
        event_emitter=event_emitter,
        static_asset_version=static_asset_version,
    )
    return application



# `uvicorn app.main:app` and the tests read a module-level application, built
# on first read: the image's `uvicorn --factory app.main:create_app` imports
# this module, so an import-time build would make a second, unused app per worker.
app: FastAPI


def __getattr__(name: str) -> FastAPI:
    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    application = create_app()
    globals()["app"] = application
    return application
