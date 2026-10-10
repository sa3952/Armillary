"""Serve only the closed set of browser runtime assets, and gzip the chart result."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import os
import re
import stat
from typing import Any, Iterable

from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers, MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import (
    FileResponse,
    MalformedRangeHeader,
    RangeNotSatisfiable,
    RedirectResponse,
    Response,
)
from starlette.staticfiles import NotModifiedResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .frontend_assets import (
    COMPRESSIBLE_ASSET_SUFFIXES,
    DEFAULT_LOCALE_ENTRYPOINT,
    NOT_FOUND_PAGE,
    RUNTIME_MEDIA_TYPES,
    asset_content_version,
    asset_parent_directories,
    validate_asset_name,
)
from .privacy_logging import DOMAIN_ERROR_STATE_KEY
from .refusals import CHART_ROUTE
from .request_limits import is_api_path


# The one address of the default locale's entry page; its file name and the
# other spellings of the directory redirect here.
_ENTRY_PATH = "/" + DEFAULT_LOCALE_ENTRYPOINT.rsplit("/", 1)[0] + "/"
_ENTRY_SPELLINGS = frozenset({
    _ENTRY_PATH.strip("/"),
    DEFAULT_LOCALE_ENTRYPOINT,
    DEFAULT_LOCALE_ENTRYPOINT.removesuffix(".html"),
})


def _media_type(path: str | os.PathLike[str]) -> str | None:
    """The declared type of a runtime asset; None only for an undeclared
    suffix, which the allowlist never admits."""
    return RUNTIME_MEDIA_TYPES.get(os.path.splitext(os.fspath(path))[1].casefold())


# zlib's default speed/size point.  mtime=0 makes the encoded bytes a pure
# function of the asset, so two workers never disagree about a representation.
GZIP_LEVEL = 6


@dataclass(frozen=True)
class _AssetSnapshot:
    identity: tuple[int, int, int]
    version: str
    gzip_body: bytes | None


# RFC 9110 §12.4.2: qvalue = ( "0" [ "." 0*3DIGIT ] ) / ( "1" [ "." 0*3("0") ] )
_QVALUE = re.compile(r"0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?")


def accepts_gzip(request_headers: Headers) -> bool:
    """True only when the client names gzip itself with a valid non-zero quality.

    `*` is not read as consent: browsers name gzip explicitly, and a client
    that does not is served the identity bytes it can always decode.
    """

    for header in request_headers.getlist("accept-encoding"):
        for item in header.split(","):
            coding, _, parameters = item.partition(";")
            if coding.strip().casefold() != "gzip":
                continue
            quality = "1"
            for parameter in parameters.split(";"):
                key, _, value = parameter.partition("=")
                if key.strip().casefold() == "q":
                    quality = value.strip()
            # `float` reads `inf`, `1e0` and `1_0`; none is an RFC 9110 qvalue.
            if _QVALUE.fullmatch(quality) is None:
                return False
            return float(quality) > 0
    return False


class _RangeLenientFileResponse(FileResponse):
    """A file answer that ignores a Range it cannot serve.

    Starlette answers a malformed Range with a bare `400 text/plain` and an
    unsatisfiable one with an empty `416`, both outside the one refusal shape
    this service writes (refusals.py).  RFC 9110 §14.2 lets a server ignore a
    Range header, so such a request gets the whole file with 200, as if it had
    sent none; a Range that can be served still gets its 206.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        requested = Headers(scope=scope).get("range")
        if requested is not None and self.stat_result is not None:
            try:
                self._parse_range_header(requested, self.stat_result.st_size)
            except (MalformedRangeHeader, RangeNotSatisfiable):
                scope = {
                    **scope,
                    "headers": [
                        (name, value) for name, value in scope.get("headers", ())
                        if name.lower() not in {b"range", b"if-range"}
                    ],
                }
        await super().__call__(scope, receive, send)


class RuntimeStaticFiles(StaticFiles):
    """Reject files that are not declared browser runtime assets.

    The policy remains effective for local source checkouts and for hosted
    immutable frontend releases mounted read-only into the application.

    Static text assets are gzip-encoded here for clients that accept it, and
    this class is the one source of each asset's content version for the
    public cache policy.  API responses never pass
    through it; the chart result has its own encoder (ChartResultCompression
    below), and no other API body is compressed.
    The staging NGINX template enables no gzip; NGINX's gzip filter also skips
    a response that already has Content-Encoding, so enabling it at the edge
    later would not compress these twice.
    """

    def __init__(
        self,
        *,
        allowed_assets: Iterable[str],
        **kwargs: Any,
    ) -> None:
        declared = frozenset(validate_asset_name(name) for name in allowed_assets)
        if not declared:
            raise ValueError("runtime frontend allowlist must not be empty")
        # The branded 404 page is declared (it travels in the hashed release)
        # but is not addressable: no request path reaches it, so it can never
        # answer 200 at a URL of its own.
        self._not_found_page = NOT_FOUND_PAGE if NOT_FOUND_PAGE in declared else None
        assets = declared - {NOT_FOUND_PAGE}
        self._assets = assets
        self._allowed_paths = assets | asset_parent_directories(assets)
        # Keyed by resolved path of a declared asset, so bounded by the
        # allowlist.  An entry is reused only while the file's inode, size
        # and mtime are unchanged: a hosted release is read-only, and a source
        # checkout that changes under a running process is re-read.
        self._snapshots: dict[str, _AssetSnapshot] = {}
        super().__init__(**kwargs)

    def _canonical_redirect(self, scope: Scope) -> str | None:
        """The one address of a page or file requested by another spelling.

        Each page has exactly one URL (the one its canonical link names) and
        every other spelling of it is a permanent redirect there in one hop:
        the `.html` file name, a trailing slash, repeated slashes, and for the
        entry page its directory without the slash and its `index` name.  A
        declared file asked for with a trailing slash goes to the file.  A
        spelling that matches nothing is left to the lookup, which refuses it.
        """

        if scope.get("method") not in {"GET", "HEAD"}:
            return None
        original = scope.get("path")
        if not isinstance(original, str) or not original.startswith("/"):
            return None
        name = re.sub(r"/{2,}", "/", original).strip("/")
        target: str | None
        if name in _ENTRY_SPELLINGS and DEFAULT_LOCALE_ENTRYPOINT in self._assets:
            target = _ENTRY_PATH
        elif name.endswith(".html") and name in self._assets:
            target = "/" + name.removesuffix(".html")
        elif name and (f"{name}.html" in self._assets or name in self._assets):
            target = "/" + name
        else:
            target = None
        if target is None or target == original:
            return None
        # The query string is dropped.  No page reads one: the calculation
        # page replaces its own address without query or fragment as the first
        # thing it does on load (clearAddressInput), and every input travels
        # in a POST body.  A query on a page address is therefore something a
        # visitor or a link put there, possibly birth data, and a 308 is
        # cacheable by default: echoing it into Location would store it in the
        # browser's redirect cache and history under the canonical address.
        return target

    def not_found_response(self, scope: Scope) -> Response | None:
        """The branded HTML 404 for a page address, or None to keep JSON.

        The status stays 404 (never a soft 404), the page carries its own
        `noindex`, and the privacy boundary gives it the same no-store and
        security headers as every other refusal.  The closed telemetry code
        is the one the JSON refusal records.
        """

        # A miss under the API prefix keeps the API's JSON refusal; the HTML
        # page is for page addresses only.
        if (
            self._not_found_page is None
            or scope.get("method") not in {"GET", "HEAD"}
            or is_api_path(scope["path"])
        ):
            return None
        full_path, stat_result = super().lookup_path(self._not_found_page)
        if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
            return None
        scope.setdefault("state", {})[DOMAIN_ERROR_STATE_KEY] = "not_found"
        return FileResponse(
            full_path,
            status_code=404,
            stat_result=stat_result,
            media_type=_media_type(full_path),
        )

    async def get_response(self, path: str, scope: Scope) -> Response:
        redirect = self._canonical_redirect(scope)
        if redirect is not None:
            return RedirectResponse(redirect, status_code=308)
        try:
            return await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code == 404:
                page = self.not_found_response(scope)
                if page is not None:
                    return page
            raise

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        normalized = path.strip("/")
        if normalized.startswith("./"):
            normalized = normalized[2:]
        # StaticFiles only resolves extensionless HTML names after lookup_path.
        # Apply that resolution inside the manifest allowlist boundary so
        # /zh-TW/calculate can be canonical without permitting undeclared files.
        html_candidate = f"{normalized}.html"
        if normalized and html_candidate in self._allowed_paths:
            normalized = html_candidate
            path = html_candidate
        if (
            normalized not in {"", "."}
            and normalized not in self._allowed_paths
        ):
            return "", None
        return super().lookup_path(path)

    def _snapshot(
        self, full_path: str, stat_result: os.stat_result
    ) -> _AssetSnapshot:
        identity = (
            stat_result.st_ino, stat_result.st_size, stat_result.st_mtime_ns
        )
        cached = self._snapshots.get(full_path)
        if cached is not None and cached.identity == identity:
            return cached
        with open(full_path, "rb") as handle:
            data = handle.read()
            opened = os.fstat(handle.fileno())
        encoded: bytes | None = None
        if os.path.splitext(full_path)[1].casefold() in COMPRESSIBLE_ASSET_SUFFIXES:
            encoded = gzip.compress(data, compresslevel=GZIP_LEVEL, mtime=0)
            if len(encoded) >= len(data):
                encoded = None
        snapshot = _AssetSnapshot(
            identity=(opened.st_ino, opened.st_size, opened.st_mtime_ns),
            version=asset_content_version(data),
            gzip_body=encoded,
        )
        self._snapshots[full_path] = snapshot
        return snapshot

    def content_version(self, path: object) -> str | None:
        """Content version of the declared asset at an exact request path.

        The public cache policy grants the immutable lifetime only when a
        request's `?v=` equals this value.  Anything that is not
        exactly one declared file (an extensionless page alias, a redirect
        spelling, a missing file) has no version.
        """

        if not isinstance(path, str) or not path.startswith("/"):
            return None
        name = path[1:]
        if name not in self._assets:
            return None
        try:
            full_path, stat_result = self.lookup_path(name)
            if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
                return None
            return self._snapshot(full_path, stat_result).version
        except (OSError, ValueError):
            return None

    def file_response(
        self,
        full_path: Any,
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        suffix = os.path.splitext(os.fspath(full_path))[1].casefold()
        request_headers = Headers(scope=scope)
        identity = _RangeLenientFileResponse(
            full_path,
            status_code=status_code,
            stat_result=stat_result,
            media_type=_media_type(full_path),
        )
        if status_code != 200 or suffix not in COMPRESSIBLE_ASSET_SUFFIXES:
            if self.is_not_modified(identity.headers, request_headers):
                return NotModifiedResponse(identity.headers)
            return identity
        # Both representations name the request header that chose between them.
        identity.headers["vary"] = "Accept-Encoding"
        snapshot: _AssetSnapshot | None = None
        # A byte range addresses the identity bytes, never a gzip stream.
        if "range" not in request_headers and accepts_gzip(request_headers):
            snapshot = self._snapshot(os.fspath(full_path), stat_result)
        if snapshot is None or snapshot.gzip_body is None:
            if self.is_not_modified(identity.headers, request_headers):
                return NotModifiedResponse(identity.headers)
            return identity
        encoded_headers = Headers(headers={
            "content-type": identity.headers["content-type"],
            "content-encoding": "gzip",
            "vary": "Accept-Encoding",
            "last-modified": identity.headers["last-modified"],
            # A strong validator names exactly one representation.
            "etag": identity.headers["etag"][:-1] + '-gzip"',
        })
        if self.is_not_modified(encoded_headers, request_headers):
            return NotModifiedResponse(encoded_headers)
        if scope.get("method") == "HEAD":
            return Response(
                b"",
                headers={
                    **encoded_headers,
                    "content-length": str(len(snapshot.gzip_body)),
                },
            )
        return Response(snapshot.gzip_body, headers=dict(encoded_headers))


# gzip for the chart result.
#
# A chart result is 100-600 KB of JSON that compresses to about a seventh.  Only
# the successful `POST /api/chart` result is encoded, only for a client that
# names gzip in Accept-Encoding (the same reading as the static assets,
# accepts_gzip above), with the same deterministic encoder (level
# GZIP_LEVEL, mtime 0): one request body gives one byte sequence on every worker
# of one image.  Refusals and every other API body stay identity; they are small
# and some echo submitted terms (place search).  Both representations of a
# result carry `Vary: Accept-Encoding`.  Cache-Control (no-store) and the
# security headers are added outside this middleware, so they are the same for
# both.  The edge passes the encoded body through unchanged (no gzip or gunzip
# in the NGINX template; observed in tests/deployment/test_staging_nginx_runtime.py).
#
# Why compressing this body does not open a BREACH/CRIME-class leak: such an
# attack needs a secret and attacker-chosen input in the same compressed body,
# and many requests the attacker can cause the victim's browser to send.  A chart
# result holds no secret of that kind: no session, cookie, CSRF or other token,
# no credential, no server-side state.  The result is a function of the request
# body alone, so the only private data in it is the birth data the same request
# carried.  A request the attacker can cause cannot carry the victim's birth data
# (it exists only in the victim's own submission, and the route accepts only
# `application/json`, which a cross-site page cannot send without a CORS
# preflight this application never grants), so no response ever mixes a guess
# with that data.  What an on-path observer still sees is the length of the victim's own response, which
# the identity encoding reveals as well.
class ChartResultCompression:
    """Encode the 200 chart result with gzip for clients that ask for it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != CHART_ROUTE
        ):
            await self.app(scope, receive, send)
            return

        wants_gzip = accepts_gzip(Headers(scope=scope))
        held_start: Message | None = None
        chunks: list[bytes] = []

        async def send_result(message: Message) -> None:
            nonlocal held_start
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if message.get("status") != 200 or "content-encoding" in headers:
                    await send(message)
                    return
                # Both representations name the header that chose between them.
                headers.add_vary_header("Accept-Encoding")
                if not wants_gzip:
                    await send(message)
                    return
                held_start = message
                return
            if message["type"] == "http.response.body" and held_start is not None:
                chunks.append(message.get("body", b""))
                if message.get("more_body", False):
                    return
                encoded = gzip.compress(b"".join(chunks), compresslevel=GZIP_LEVEL, mtime=0)
                start, held_start = held_start, None
                headers = MutableHeaders(scope=start)
                headers["content-encoding"] = "gzip"
                headers["content-length"] = str(len(encoded))
                await send(start)
                await send({"type": "http.response.body", "body": encoded})
                return
            await send(message)

        await self.app(scope, receive, send_result)
