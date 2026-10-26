"""Serve only the closed set of browser runtime assets, and gzip the chart result."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
import gzip
import hashlib
import os
import posixpath
import re
import stat
from typing import Any, AsyncIterator, Iterable, Mapping

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
    RUNTIME_NAME_MEDIA_TYPES,
    asset_content_version,
    asset_parent_directories,
    validate_asset_name,
)
from .privacy_logging import DOMAIN_ERROR_STATE_KEY
from .refusals import ANNUAL_ROUTE, CHART_ROUTE
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
    named = RUNTIME_NAME_MEDIA_TYPES.get(os.path.basename(os.fspath(path)))
    if named is not None:
        return named
    return RUNTIME_MEDIA_TYPES.get(os.path.splitext(os.fspath(path))[1].casefold())


# The site's machine-readable descriptions, named in a Link header (RFC 8288)
# on every page answer, so an agent that reads headers finds them without
# parsing the page.  A release that does not carry one does not link it.
_PAGE_LINKS = (
    ("sitemap.xml", "sitemap", "application/xml"),
    ("llms.txt", "describedby", "text/plain"),
)


def page_link_header(assets: frozenset[str]) -> str | None:
    links = [
        f'</{name}>; rel="{rel}"; type="{media_type}"'
        for name, rel, media_type in _PAGE_LINKS
        if name in assets
    ]
    return ", ".join(links) or None


# zlib's default speed/size point.  mtime=0 makes the encoded bytes a pure
# function of the asset, so two workers never disagree about a representation.
GZIP_LEVEL = 6


def _file_identity(stat_result: os.stat_result) -> tuple[int, ...]:
    return (
        stat_result.st_dev, stat_result.st_ino, stat_result.st_size,
        stat_result.st_mtime_ns, stat_result.st_ctime_ns,
    )


@dataclass(frozen=True)
class _AssetSnapshot:
    identity: tuple[int, ...]
    # The bytes read and the open file's own status: a receipted release
    # serves exactly these, never a second read of the path.
    body: bytes
    stat_result: os.stat_result
    version: str
    sha256: str
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


_RANGE_SPEC = r"(?:[0-9]+-[0-9]*|-[0-9]+)"
_STRICT_RANGE = re.compile(rf"bytes={_RANGE_SPEC}(?:[ \t]*,[ \t]*{_RANGE_SPEC})*")


class _RangeLenientFileResponse(FileResponse):
    """A file answer that ignores a Range it cannot serve.

    Starlette answers a malformed Range with a bare `400 text/plain` and an
    unsatisfiable one with an empty `416`, outside the one refusal shape
    (refusals.py).  RFC 9110 §14.2 lets a server ignore Range, so such a request
    gets the whole file with 200; a servable Range still gets its 206.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        requested = Headers(scope=scope).get("range")
        if requested is not None and self.stat_result is not None:
            try:
                if not _STRICT_RANGE.fullmatch(requested):
                    raise MalformedRangeHeader()
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


class _HeldBytes:
    """The read and seek a file answer uses, over bytes already in memory."""

    def __init__(self, body: bytes) -> None:
        self._body = body
        self._position = 0

    async def seek(self, position: int) -> None:
        self._position = position

    async def read(self, size: int) -> bytes:
        chunk = self._body[self._position:self._position + size]
        self._position += len(chunk)
        return chunk


class _HeldFileResponse(_RangeLenientFileResponse):
    """A file answer whose bytes are the ones already checked against the receipt.

    Reading the path again to send it would let a file changed between the
    check and the send go out unchecked; the server's pathsend shortcut would
    do the same, so it is not offered.
    """

    def __init__(self, *args: Any, body: bytes, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._held = body

    @asynccontextmanager
    async def _open_file(self) -> AsyncIterator[Any]:
        yield _HeldBytes(self._held)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        extensions = {
            key: value for key, value in scope.get("extensions", {}).items()
            if key != "http.response.pathsend"
        }
        await super().__call__({**scope, "extensions": extensions}, receive, send)


class RuntimeStaticFiles(StaticFiles):
    """Reject files that are not declared browser runtime assets.

    Applies to source checkouts and to read-only hosted releases alike.

    Static text assets are gzip-encoded here, and this class is the one source
    of each asset's content version for the public cache policy.  API responses
    never pass through it.  The staging NGINX enables no gzip, and its gzip
    filter skips a response that already has Content-Encoding, so enabling it
    later would not compress twice.
    """

    def __init__(
        self,
        *,
        allowed_assets: Iterable[str],
        asset_digests: Mapping[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        declared = frozenset(validate_asset_name(name) for name in allowed_assets)
        # A mounted release's receipted SHA-256 per file.  The
        # release is verified at start; with digests, every file is also held
        # to its receipt whenever it is (re)read, at the exact path that was
        # asked for, so a file changed or swapped for a symlink under the
        # running process is refused (404) instead of served.
        if asset_digests is not None and set(asset_digests) != declared:
            raise ValueError("release digests must name exactly the declared assets")
        self._asset_digests = dict(asset_digests) if asset_digests is not None else None
        if not declared:
            raise ValueError("runtime frontend allowlist must not be empty")
        # The branded 404 page travels in the hashed release but is not
        # addressable, so it can never answer 200 at a URL of its own.
        self._not_found_page = NOT_FOUND_PAGE if NOT_FOUND_PAGE in declared else None
        assets = declared - {NOT_FOUND_PAGE}
        self._assets = assets
        self._page_links = page_link_header(assets)
        self._allowed_paths = assets | asset_parent_directories(assets)
        # Keyed by resolved path of a declared asset, so bounded by the
        # allowlist.  An entry is reused only while the file's device, inode,
        # size, mtime and ctime are unchanged: a hosted release is read-only,
        # and a file that changes under a running process is re-read (ctime
        # moves on any write, even one that restores the mtime).
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
        name = posixpath.normpath(re.sub(r"/{2,}", "/", original)).strip("/")
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
        # The query string is dropped.  No page reads one (the calculation page
        # clears its own on load, clearAddressInput; inputs travel in POST
        # bodies), so a query is something a visitor or link put there,
        # possibly birth data; a 308 is cacheable, and echoing it into Location
        # would store it in the redirect cache and history.
        return target

    def not_found_response(self, scope: Scope) -> Response | None:
        """The branded HTML 404 for a page address, or None to keep JSON.

        The status stays 404 (never a soft 404), the page carries its own
        `noindex`, and the privacy boundary gives it the same no-store and
        security headers as every other refusal.  The closed telemetry code
        is the one the JSON refusal records.
        """

        if (
            self._not_found_page is None
            or scope.get("method") not in {"GET", "HEAD"}
            or is_api_path(scope["path"])
        ):
            return None
        full_path, stat_result = self._verified(
            self._not_found_page, *super().lookup_path(self._not_found_page)
        )
        if stat_result is None or not stat.S_ISREG(stat_result.st_mode):
            return None
        held = self._receipted(self._not_found_page, full_path, stat_result)
        scope.setdefault("state", {})[DOMAIN_ERROR_STATE_KEY] = "not_found"
        if held is not None:
            return _HeldFileResponse(
                full_path,
                status_code=404,
                stat_result=held.stat_result,
                media_type=_media_type(full_path),
                body=held.body,
            )
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
            response = await super().get_response(path, scope)
            if 300 <= response.status_code < 400 and "location" in response.headers:
                # Directory redirects from StaticFiles build an absolute URL
                # from the upstream scheme and retain its query parameters.
                # Only the canonical producer above may redirect a static URL.
                raise HTTPException(status_code=404)
            return response
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
        return self._verified(normalized, *super().lookup_path(path))

    def _verified(
        self, name: str, full_path: str, stat_result: os.stat_result | None
    ) -> tuple[str, os.stat_result | None]:
        """The looked-up file, or nothing if it is not its receipted bytes."""
        if self._asset_digests is None or stat_result is None:
            return full_path, stat_result
        expected = self._asset_digests.get(name)
        if expected is None:  # a directory of the release
            return full_path, stat_result
        exact = os.path.join(os.path.realpath(self.directory or "."), *name.split("/"))
        # The lookup resolves symlinks; the file served must be the very
        # path asked for, a regular file holding its receipted bytes.
        if full_path != exact or not stat.S_ISREG(stat_result.st_mode):
            return "", None
        try:
            snapshot = self._snapshot(full_path, stat_result)
        except OSError:
            return "", None
        if snapshot.sha256 != expected:
            return "", None
        return full_path, stat_result

    def _receipted(
        self, name: str, full_path: str, stat_result: os.stat_result
    ) -> _AssetSnapshot | None:
        """The receipted bytes of a release file, read once; None without receipts.

        The lookup has already held the file to its receipt, but the file can
        change again before the answer is sent, so the bytes sent are taken from
        one read that is itself held to the receipt.  A file that no longer
        matches is refused (404).
        """
        if self._asset_digests is None:
            return None
        expected = self._asset_digests.get(name)
        if expected is None:
            return None
        try:
            snapshot = self._snapshot(full_path, stat_result)
        except OSError:
            raise HTTPException(status_code=404) from None
        if snapshot.sha256 != expected:
            raise HTTPException(status_code=404)
        return snapshot

    def _snapshot(
        self, full_path: str, stat_result: os.stat_result
    ) -> _AssetSnapshot:
        identity = _file_identity(stat_result)
        cached = self._snapshots.get(full_path)
        if cached is not None and cached.identity == identity:
            return cached
        with open(full_path, "rb") as handle:
            data = handle.read()
            opened = os.fstat(handle.fileno())
        if opened.st_size != len(data):
            raise OSError(f"{full_path} changed while it was read")
        encoded: bytes | None = None
        if os.path.splitext(full_path)[1].casefold() in COMPRESSIBLE_ASSET_SUFFIXES:
            encoded = gzip.compress(data, compresslevel=GZIP_LEVEL, mtime=0)
            if len(encoded) >= len(data):
                encoded = None
        snapshot = _AssetSnapshot(
            identity=_file_identity(opened),
            body=data,
            stat_result=opened,
            version=asset_content_version(data),
            sha256=hashlib.sha256(data).hexdigest(),
            gzip_body=encoded,
        )
        self._snapshots[full_path] = snapshot
        return snapshot

    def content_version(self, path: object) -> str | None:
        """Content version of the declared asset at an exact request path.

        The cache policy grants immutable only when `?v=` equals this value.
        Anything not exactly one declared file (page alias, redirect spelling,
        missing file) has no version.
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
        held: _AssetSnapshot | None = None
        if self._asset_digests is not None:
            root = os.path.realpath(self.directory or ".")
            name = os.path.relpath(os.fspath(full_path), root).replace(os.sep, "/")
            held = self._receipted(name, os.fspath(full_path), stat_result)
        identity: FileResponse
        if held is not None:
            identity = _HeldFileResponse(
                full_path,
                status_code=status_code,
                stat_result=held.stat_result,
                media_type=_media_type(full_path),
                body=held.body,
            )
        else:
            identity = _RangeLenientFileResponse(
                full_path,
                status_code=status_code,
                stat_result=stat_result,
                media_type=_media_type(full_path),
            )
        page_links = self._page_links if status_code == 200 and suffix == ".html" else None
        if page_links is not None:
            identity.headers["link"] = page_links
        if status_code != 200 or suffix not in COMPRESSIBLE_ASSET_SUFFIXES:
            if self.is_not_modified(identity.headers, request_headers):
                return NotModifiedResponse(identity.headers)
            return identity
        # Both representations name the request header that chose between them.
        identity.headers["vary"] = "Accept-Encoding"
        snapshot: _AssetSnapshot | None = None
        # A byte range addresses the identity bytes, never a gzip stream.
        if "range" not in request_headers and accepts_gzip(request_headers):
            snapshot = held or self._snapshot(os.fspath(full_path), stat_result)
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
            **({"link": page_links} if page_links is not None else {}),
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


# gzip for the chart result: 100-600 KB of JSON that compresses to about a
# seventh.  Only the successful `POST /api/chart` (and flagged annual) result,
# only for a client naming gzip (accepts_gzip), with the deterministic encoder
# (GZIP_LEVEL, mtime 0): one body, one byte sequence on every worker.  Refusals
# and other API bodies stay identity; they are small and some echo submitted
# terms (place search).  Cache-Control and security headers are added outside,
# so both representations match.  The edge passes the body through unchanged
# (no gzip in the NGINX template; tests/deployment/test_staging_nginx_runtime.py).
#
# No BREACH/CRIME-class leak: that needs a secret and attacker-chosen input in
# one compressed body, over many requests the attacker can make the victim's
# browser send.  A result holds no session, cookie, token, credential or server
# state; it is a function of its own request body, so its only private data is
# the birth data that request carried.  An attacker-caused request cannot carry
# the victim's birth data (the route accepts only `application/json`, which a
# cross-site page cannot send without a CORS preflight never granted), so no
# response mixes a guess with it.  An on-path observer sees only the length of
# the victim's own response, which identity encoding reveals as well.
_COMPRESSED_RESULT_ROUTES = frozenset({CHART_ROUTE, ANNUAL_ROUTE})


class ChartResultCompression:
    """Encode the 200 chart result with gzip for clients that ask for it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") not in _COMPRESSED_RESULT_ROUTES
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
