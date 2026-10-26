"""The one refusal serializer and its closed vocabulary.

Every non-2xx body the application and the edge's JSON refusals write has
one shape::

    {"detail": {"code": <closed code>, "message": <fixed text>, ...}}

Every layer writes it (request boundary, domain handlers, FastAPI's
malformed-JSON path, Starlette), so a client can branch on ``detail`` without
testing its type, and one condition always arrives with the same message.
What the ASGI server refuses before the application sees a request (uvicorn's
h11: an unparseable request line or framing, such as a non-numeric or
conflicting Content-Length) is a plain-text 400 outside this shape.

This table owns each code's status, fixed message, retryability (and so
``Retry-After``) and emitting routes.  The output contract's refusal table is
generated from it; the offline OpenAPI document (never served: ``openapi_url``
is None), the privacy event vocabulary and the front-end copy coverage test
read it; none keeps its own list.

Privacy: a message is a constant.  Nothing a request contained — a value, a key
it invented, a position in its bytes — may appear in a refusal.  Field *names*
the API declares are the only request-shaped text allowed, and only inside
``issues[].loc``; that sanitising lives with the request models in
``schemas.py``.  Extra receipt fields are an allowlist here, so a domain error
that attaches a request value is filtered rather than trusted.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Final, Mapping, NamedTuple

from starlette.responses import JSONResponse

CHART_ROUTE: Final = "/api/chart"
# Registered only when the deployment sets ARMILLARY_ENABLE_ANNUAL_ROUTE=1
# (settings.py); otherwise it is an unknown API path like any other.
ANNUAL_ROUTE: Final = "/api/chart/annual"
PLACE_SEARCH_ROUTE: Final = "/api/places/search"
HEALTH_ROUTE: Final = "/api/health"
# Readiness: the bundled ephemeris files are present and match the pinned digests.
READY_ROUTE: Final = "/api/health/ready"
TIME_CONVERT_ROUTE: Final = "/api/time/convert"
# Counting only (visit_counts.py): one per page load, one per browser per day.
VISIT_ROUTE: Final = "/api/visit"
DAILY_VISIT_ROUTE: Final = "/api/visit/daily"
# The running build and where its source is, without computing a chart.
VERSION_ROUTE: Final = "/api/version"
# Not an OpenAPI path: the bundled page and its assets under the static mount.
FRONTEND_ASSETS: Final = "frontend_assets"

# One retry contract for every retryable refusal: each carries this Retry-After.
RETRY_AFTER_SECONDS: Final = 5

# A body of invented keys yields one issue per key; past this many the list is
# cut and the refusal says so, so the answer cannot outgrow the request.
MAX_REFUSAL_ISSUES: Final = 32

_JSON_BODY_ROUTES: Final = frozenset({
    CHART_ROUTE, PLACE_SEARCH_ROUTE, ANNUAL_ROUTE, TIME_CONVERT_ROUTE,
})
_API_ROUTES: Final = frozenset({
    CHART_ROUTE, PLACE_SEARCH_ROUTE, HEALTH_ROUTE, READY_ROUTE, ANNUAL_ROUTE, TIME_CONVERT_ROUTE,
    VISIT_ROUTE, DAILY_VISIT_ROUTE, VERSION_ROUTE,
})
_COMPUTE_ROUTES: Final = frozenset({CHART_ROUTE, ANNUAL_ROUTE})
# Every route that reads a birth record's civil time: both calculations and the converter.
_CIVIL_TIME_ROUTES: Final = _COMPUTE_ROUTES | {TIME_CONVERT_ROUTE}
_EVERY_ROUTE: Final = _API_ROUTES | {FRONTEND_ASSETS}
# The edge answers readiness itself (unknown_api_path) before any limiter or
# upstream, so its own rate and upstream refusals never reach that path.
_EDGE_PROXIED_API_ROUTES: Final = _API_ROUTES - {READY_ROUTE}


class Refusal(NamedTuple):
    status: int
    message: str
    routes: frozenset[str]
    retryable: bool = False


REFUSALS: Final[Mapping[str, Refusal]] = MappingProxyType({
    # ── Request boundary (request_limits.py) ────────────────────────────────
    "undeclared_host": Refusal(404, "此服務不回應這個主機名稱。", _EVERY_ROUTE),
    # Answered for a path under /api/ that is not a route; never a declared one.
    # The public edge writes it too, for readiness, which only the container's
    # own health check may ask (deploy/staging/nginx-site.conf.template).
    "unknown_api_path": Refusal(404, "此服務沒有這個 API 路徑。", frozenset()),
    "unsupported_method": Refusal(405, "此路徑不接受這個 HTTP 方法。", _API_ROUTES),
    # The edge writes this one too, on every /api path, when a client's
    # connection limit is reached (deploy/staging/nginx-site.conf.template).
    "request_capacity_exhausted": Refusal(
        503, "服務目前忙碌，請稍後重試。",
        _API_ROUTES | {FRONTEND_ASSETS},
        retryable=True,
    ),
    "compute_capacity_exhausted": Refusal(
        503, "服務目前忙碌，請稍後重試。", _COMPUTE_ROUTES, retryable=True,
    ),
    "request_headers_too_large": Refusal(431, "請求標頭超過 16 KiB 上限。", _EVERY_ROUTE),
    "unsupported_media_type": Refusal(
        415, "此端點只接受 UTF-8 application/json。", _JSON_BODY_ROUTES,
    ),
    "conflicting_request_framing": Refusal(
        400, "請求同時使用 Content-Length 與 Transfer-Encoding。", _JSON_BODY_ROUTES,
    ),
    # Behind uvicorn's h11 a malformed or conflicting Content-Length never
    # reaches the application (the server answers it); kept for a server that
    # forwards one.
    "invalid_content_length": Refusal(
        400, "Content-Length 格式無效或不明確。", _JSON_BODY_ROUTES,
    ),
    "request_body_too_large": Refusal(413, "請求內容超過 16 KiB 上限。", _JSON_BODY_ROUTES),
    "empty_request_body": Refusal(
        400, "此端點需要 JSON 請求內容，但收到的請求內容是空的。", _JSON_BODY_ROUTES,
    ),
    "request_body_read_timeout": Refusal(408, "讀取請求內容逾時。", _JSON_BODY_ROUTES),
    # ── JSON text (main.py strict JSON route; schemas.strict_json_problem) ───
    "request_body_not_utf8": Refusal(
        400, "請求內容必須是不帶 BOM 的 UTF-8 JSON 文字。", _JSON_BODY_ROUTES,
    ),
    "json_invalid": Refusal(400, "請求內容不是有效的 JSON。", _JSON_BODY_ROUTES),
    "duplicate_json_key": Refusal(
        400,
        "請求內容的同一個 JSON 物件裡有重複的鍵；服務不猜測要採用哪一個值。",
        _JSON_BODY_ROUTES,
    ),
    # ── Request models (schemas.py) ──────────────────────────────────────────
    "request_validation_failed": Refusal(
        422,
        "請求欄位未通過驗證；issues 逐項列出閉集代碼與宣告的欄位位置。",
        # Every API route: the GET routes refuse an undeclared query too.
        _API_ROUTES,
    ),
    # ── Domain (main.py handlers) ────────────────────────────────────────────
    "nonexistent_local_time": Refusal(
        422, "這個本地時間在所選時區不存在（時鐘跳過了這段時間）。", _COMPUTE_ROUTES,
    ),
    "ambiguous_local_time_choice_required": Refusal(
        422, "這個本地時間在所選時區出現兩次；請以 fold 指定是哪一次。",
        _COMPUTE_ROUTES,
    ),
    # A catalogue place that keeps Beijing time and Xinjiang time is computed
    # only once the request names the birth record's clock (core.civil_time_basis).
    "civil_time_basis_required": Refusal(
        422,
        "這個出生地的紀錄可能用北京時間，也可能用新疆時間；"
        "請以 timezone.civil_time_basis 指明出生紀錄用的是哪一種。",
        _CIVIL_TIME_ROUTES,
    ),
    "civil_time_basis_not_applicable": Refusal(
        422,
        "timezone.civil_time_basis 只適用於目錄標示為同時使用北京時間與新疆時間的地點。",
        _CIVIL_TIME_ROUTES,
    ),
    # A request that names a catalogue record is computed only as the
    # catalogue's row (core.place_catalog.check_request_places); other
    # coordinates or another zone are sent as manual coordinates.
    "catalog_record_unknown": Refusal(
        422,
        "內建地名目錄裡沒有這個來源與記錄 id；請重新用地名查詢選定地點，或改用手動座標。",
        _COMPUTE_ROUTES,
    ),
    "catalog_location_mismatch": Refusal(
        422,
        "地點的標籤、座標、位置精度或時區與內建地名目錄的這筆記錄不同；"
        "reason_code 指出第一個不同的欄位。要用別的座標或時區，請改用手動座標。",
        _COMPUTE_ROUTES,
    ),
    # The helper answers only where its source table has rows
    # (core.civil_time_sources); elsewhere it would give an offset without a source.
    "time_conversion_zone_not_covered": Refusal(
        422,
        "換算助手目前只涵蓋臺灣、香港、澳門與中國的 IANA 時區；其他時區請直接計算，卷宗會記下換算結果。",
        frozenset({TIME_CONVERT_ROUTE}),
    ),
    "house_system_unavailable": Refusal(
        422, "所選宮位制在這個位置無法計算；reason_code 說明原因。", _COMPUTE_ROUTES,
    ),
    # 422, not 503: an instant outside the bundled segments is refused the
    # same way every time.  A missing segment file or an unpredicted Swiss
    # fallback is a server fault: internal_server_error (main._handle_domain_error).
    "full_ephemeris_required": Refusal(
        422,
        "這次計算需要的完整 Swiss Ephemeris 資料不在服務的覆蓋範圍內；"
        "服務不改用較低精度的替代結果，重送同一請求不會改變結果。",
        _COMPUTE_ROUTES,
    ),
    "swiss_ephemeris_error": Refusal(
        500, "Swiss Ephemeris 無法完成這次計算；錯誤內容不對外輸出。", _COMPUTE_ROUTES,
    ),
    # The chart routes read the catalogue to bind a catalogue place to its row
    # and to learn whether it keeps two clocks; they refuse rather than guess
    # when they cannot.
    "place_catalog_unavailable": Refusal(
        503, "內建地名目錄無法讀取。", frozenset({PLACE_SEARCH_ROUTE, CHART_ROUTE, ANNUAL_ROUTE}),
    ),
    "place_search_timeout": Refusal(
        503, "地名查詢超過語句時間預算而中止；請稍後重試，或改用較具體的查詢。",
        frozenset({PLACE_SEARCH_ROUTE}), retryable=True,
    ),
    # ── Edge (deploy/staging/nginx-site.conf.template) ──────────────────────
    # Written by NGINX, never by this process; listed because an /api client
    # receives them in this shape.  The messages are the edge's own sentences.
    "edge_rate_limited": Refusal(
        429, "短時間內請求過多。請稍後再試。", _EDGE_PROXIED_API_ROUTES, retryable=True,
    ),
    "upstream_unavailable": Refusal(
        502, "服務暫時無法連線。請稍後再試。", _EDGE_PROXIED_API_ROUTES, retryable=True,
    ),
    # ── Framework refusals (Starlette static mount / FastAPI body read) ───────
    "bad_request": Refusal(400, "請求內容無法讀取。", _JSON_BODY_ROUTES),
    "unauthorized": Refusal(401, "此資源無法讀取。", frozenset({FRONTEND_ASSETS})),
    "not_found": Refusal(404, "此路徑沒有資源。", frozenset({FRONTEND_ASSETS})),
    "method_not_allowed": Refusal(
        405, "此路徑不接受這個 HTTP 方法。", frozenset({FRONTEND_ASSETS}),
    ),
    # ── Privacy boundary (privacy_logging.py) ─────────────────────────────────
    "internal_server_error": Refusal(
        500,
        "伺服器無法完成本次計算。請重新嘗試；若持續發生，請回報 request ID。",
        _EVERY_ROUTE,
    ),
})

# Receipt fields a domain refusal may attach, with their published types.  An
# allowlist keeps a producer from deciding on its own what a refusal may echo:
# the request latitude and house code are not on it, nor is
# `polar_circle_threshold_degrees`, which even rounded to 0.1° moves with the
# chart date inside the product range.
REFUSAL_DETAIL_EXTRAS: Final[Mapping[str, Any]] = MappingProxyType({
    "availability": str | None,
    "reason_code": str | None,
    "refusal_basis": str | None,
    "geometric_reason": str | None,
})


def refusal_response(
    code: str,
    *,
    issues: list[dict] | None = None,
    extra: Mapping[str, object] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Write a refusal.  Status, message and Retry-After come from the table."""

    refusal = REFUSALS.get(code)
    if refusal is None:
        raise RuntimeError(f"unregistered refusal code: {code}")
    detail: dict[str, object] = {"code": code, "message": refusal.message}
    for name, value in (extra or {}).items():
        if name in REFUSAL_DETAIL_EXTRAS:
            detail[name] = value
    if issues is not None:
        detail["issues"] = issues[:MAX_REFUSAL_ISSUES]
        if len(issues) > MAX_REFUSAL_ISSUES:
            detail["truncated"] = True
    merged = dict(headers or {})
    if refusal.retryable:
        merged["Retry-After"] = str(RETRY_AFTER_SECONDS)
    return JSONResponse(
        status_code=refusal.status,
        content={"detail": detail},
        headers=merged or None,
    )


def routes_refusals(route: str) -> dict[int, tuple[str, ...]]:
    """Codes a declared route can emit, grouped by status, for the OpenAPI."""

    grouped: dict[int, list[str]] = {}
    for code, refusal in REFUSALS.items():
        if route in refusal.routes:
            grouped.setdefault(refusal.status, []).append(code)
    return {status: tuple(sorted(codes)) for status, codes in sorted(grouped.items())}
