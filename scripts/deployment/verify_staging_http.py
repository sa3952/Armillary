#!/usr/bin/env python3
"""Live HTTPS checks of the public edge plus the privacy canary.

The edge is expected to serve anonymous pages and API without a noindex
header (``--noindex`` expects the header a staging rendering adds),
robots.txt/sitemap.xml/llms.txt and the IndexNow key file holding exactly the
key, a crawlable and indexable site (robots.txt
admits pages and excludes the API, the entry page carries no noindex, a
missing page answers a branded noindex HTML 404 while a missing API path
keeps its JSON 404, discovery files are typed UTF-8, every other spelling of a
page and the www/HTTP origins redirect to the one URL in one hop, the origin
redirects keeping the path only and never stored) and the
cache policy (pages revalidated, content-versioned assets immutable, API and
errors never stored).

Everything here is an observation of the running edge: status codes, headers
and, with ``--apply``, a one-time sensitive
payload sent through the real path and then searched for in the exact
application container's log stream and in every edge sink.  The edge sinks are
not named by the caller: they are derived from ``nginx -T`` and held to the
closed log sink model defined below.  The host itself is searched too: the
whole journal since the canary started (every unit, the
kernel included), every file under /var/log changed since then, and the log
stream of every container on the host.  A sink that was
neither observed nor proven quiet by that model is ``not_observed``; it is
never assumed clean, and the receipt cannot pass.
"""
from __future__ import annotations

import argparse
import base64
from enum import Enum
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, NamedTuple, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote_from_bytes, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.robotparser import RobotFileParser

from scripts.tools.staging_secure_io import (
    deployment_hostnames, emit_json_receipt, read_owner_only, require_privileged_checkout,
    safe_absolute_path as safe_path, validate_server_name, write_owner_only_new,
)

ROOT = Path(__file__).resolve().parents[2]
try:
    import app.frontend_assets  # noqa: F401  the canonical package
except ModuleNotFoundError:
    # The host runs this from a checkout without backend/ on the path.
    sys.path.insert(0, str(ROOT / "backend"))
from app.frontend_assets import INDEXNOW_KEY, INDEXNOW_KEY_FILE  # noqa: E402
from app.settings import ANNUAL_ROUTE_ENVIRONMENT_VARIABLE, load_settings  # noqa: E402

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
HSTS_MIN_AGE_SECONDS = 365 * 24 * 60 * 60
# Must match the `logging.driver` in deploy/compose.yaml; change both together.
EXPECTED_LOG_DRIVER = "journald"
REQUEST_CASE_EXPECTATIONS = {"success": 200, "422": 422, "malformed": 400, "413": 413, "415": 415, "429": 429}
# Cases this verifier cannot produce with ordinary requests, and where each is
# held instead (no drill runs on a production host).  The edge
# bounds are the real-NGINX tests plus the byte-identical host config readback;
# the application bounds are Gate D's drills on the exact image
# (scripts/deployment/image_drills.py).  The receipt names them so a reader
# sees they were not exercised here.
DEFERRED_REQUEST_CASES = {
    "503": "real_nginx_tests_and_host_config_readback",
    "slow_body": "real_nginx_tests_and_host_config_readback",
    "timeout": "gate_d_image_drill", "unexpected_error": "gate_d_image_drill",
    "worker_restart": "gate_d_image_drill",
}


def hsts_is_sufficient(value: str) -> bool:
    match = re.search(r"(?:^|;)\s*max-age=(\d+)(?:;|$)", value.casefold())
    return bool(match and int(match.group(1)) >= HSTS_MIN_AGE_SECONDS)


# --- public cache policy, as a browser or shared cache would read it -------------
# The edge emits the application's split policy beneath its own no-store
# floor (nginx-site.conf.template).  These predicates read the
# directives a cache acts on, not the producer's exact spelling, so the
# verifier is an independent reading of the observed header and not a copy of
# the string the application writes.
IMMUTABLE_MIN_AGE_SECONDS = 365 * 24 * 60 * 60
# Every static reference the page generator stamps: `/zh-TW/<asset>?v=<16 hex>`
# (scripts/frontend/build_pages.py).
_VERSIONED_ASSET_REFERENCE = re.compile(rb'(?:src|href)="(/zh-TW/[^"?#]+)\?v=([0-9a-f]{16})"')
# The IndexNow key file an engine fetches to verify a submission
# (scripts/deployment/submit_indexnow.py).
_INDEXNOW_KEY_PATH = "/" + INDEXNOW_KEY_FILE
_PUBLIC_DISCOVERY_FILES = (
    "/robots.txt", "/sitemap.xml", "/feed.xml", "/llms.txt", "/llms-full.txt", "/.well-known/security.txt",
    _INDEXNOW_KEY_PATH,
)


def _header(headers: dict[str, str], name: str) -> str | None:
    return next((value for key, value in headers.items() if key.casefold() == name), None)


def cache_directives(headers: dict[str, str]) -> dict[str, str | None]:
    """Cache-Control directives by lower-case name; a directive without a value maps to None."""
    directives: dict[str, str | None] = {}
    for item in (_header(headers, "cache-control") or "").split(","):
        name, separator, value = item.strip().partition("=")
        if name:
            directives[name.casefold()] = value.strip().strip('"') if separator else None
    return directives


def is_no_store(headers: dict[str, str]) -> bool:
    return "no-store" in cache_directives(headers)


def is_immutable_for_a_year(headers: dict[str, str]) -> bool:
    directives = cache_directives(headers)
    age = directives.get("max-age") or ""
    return ("immutable" in directives and age.isdigit() and int(age) >= IMMUTABLE_MIN_AGE_SECONDS
            and not {"no-store", "no-cache"} & set(directives))


def revalidates(headers: dict[str, str]) -> bool:
    """May be stored, must be revalidated before every reuse, and can be: it
    carries a validator for a conditional request."""
    directives = cache_directives(headers)
    must_revalidate = "no-cache" in directives or (
        directives.get("max-age") == "0" and "must-revalidate" in directives)
    validator = _header(headers, "etag") is not None or _header(headers, "last-modified") is not None
    return (must_revalidate and validator
            and not {"no-store", "immutable"} & set(directives))


def _public_cache_cases(base_url: str, page: bytes, page_headers: dict[str, str]) -> dict[str, bool]:
    """Observe the public cache policy at the edge, one property per case."""
    cases = {"page_revalidated": revalidates(page_headers)}
    etag = _header(page_headers, "etag")
    cases["page_conditional_304"] = etag is not None and _request(
        base_url + "/zh-TW/", extra_headers={"If-None-Match": etag})[0] == 304
    assets = sorted(set(_VERSIONED_ASSET_REFERENCE.findall(page)))
    observed = [_request(base_url + path.decode() + "?v=" + version.decode()) for path, version in assets]
    cases["versioned_assets_immutable"] = bool(assets) and all(
        status == 200 and is_immutable_for_a_year(headers) for status, _, headers in observed)
    if assets:
        path, version = assets[0][0].decode(), assets[0][1].decode()
        foreign = "1" * 16 if version == "0" * 16 else "0" * 16
        status, _, headers = _request(base_url + path + "?v=" + foreign)
        cases["foreign_version_not_immutable"] = status == 200 and not is_immutable_for_a_year(headers)
    else:
        cases["foreign_version_not_immutable"] = False
    # /api/health is the one GET the application serves.
    status, _, headers = _request(base_url + "/api/health")
    cases["api_no_store"] = status == 200 and is_no_store(headers)
    errors = [_request(base_url + path) for path in ("/openapi.json", "/zh-TW/not-a-page")]
    cases["error_no_store"] = all(status == 404 and is_no_store(headers) for status, _, headers in errors)
    discovery = [_request(base_url + path) for path in _PUBLIC_DISCOVERY_FILES]
    cases["discovery_files_revalidated"] = all(
        status == 200 and revalidates(headers) for status, _, headers in discovery)
    return cases


# --- public indexability, as a crawler would read it --------------------------
# The public site is meant to be crawled and indexed; the API is not.  These
# read what a crawler acts on (robots.txt rules, the page's robots meta, the
# status of a page that does not exist), not the generator's exact spelling.
_META_ROBOTS = re.compile(rb'<meta\s+name="robots"\s+content="([^"]*)"', re.IGNORECASE)
_CRAWLABLE_PROBE_PATHS = ("/zh-TW/", "/zh-TW/calculate", "/zh-TW/methods")
_API_PROBE_PATH = "/api/chart"
_UNKNOWN_PAGE_PROBE_PATH = "/zh-TW/armillary-verifier-no-such-page"


def robots_admit_pages_not_api(base_url: str, robots: bytes) -> bool:
    try:
        lines = robots.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return False
    parser = RobotFileParser()
    parser.parse(lines)
    return (all(parser.can_fetch("*", base_url + path) for path in _CRAWLABLE_PROBE_PATHS)
            and not parser.can_fetch("*", base_url + _API_PROBE_PATH))


def page_meta_indexable(page: bytes) -> bool:
    return not any(b"noindex" in match.group(1).lower() for match in _META_ROBOTS.finditer(page))


# The error page's own file name is not an address of its own: asked for
# directly it is just another missing page, never a 200.
_ERROR_PAGE_PROBE_PATHS = (_UNKNOWN_PAGE_PROBE_PATH, "/zh-TW/404", "/zh-TW/404.html")
_UNKNOWN_API_PROBE_PATH = "/api/armillary-verifier-no-such-route"
# Discovery files and the media types a crawler accepts for each.
# Text names UTF-8 explicitly; RFC 9116 requires it for security.txt.
_DISCOVERY_MEDIA_TYPES = {
    "/robots.txt": ("text/plain",),
    "/llms.txt": ("text/plain",),
    "/llms-full.txt": ("text/plain",),
    "/.well-known/security.txt": ("text/plain",),
    "/sitemap.xml": ("application/xml", "text/xml"),
    # RFC 4287 §7: feed readers expect the Atom type, not plain XML.
    "/feed.xml": ("application/atom+xml",),
    _INDEXNOW_KEY_PATH: ("text/plain",),
}
# Every other spelling of a page is a permanent redirect to its one address,
# in one hop, so no page is reachable at two URLs.
# Where the application's root redirects (backend/app/main.py).
ENTRY_PATH = "/zh-TW/"
_NONCANONICAL_SPELLINGS = (
    ("/zh-TW", "/zh-TW/"),
    ("/zh-TW/index", "/zh-TW/"),
    ("/zh-TW/index.html", "/zh-TW/"),
    ("/zh-TW/calculate/", "/zh-TW/calculate"),
    ("/zh-TW/calculate.html", "/zh-TW/calculate"),
)


def media_type(headers: dict[str, str]) -> tuple[str, dict[str, str]]:
    """The Content-Type's type and its parameters, both lower-cased."""
    kind, *parameters = (_header(headers, "content-type") or "").split(";")
    values = {}
    for parameter in parameters:
        name, _, value = parameter.strip().partition("=")
        values[name.casefold()] = value.strip().strip('"').casefold()
    return kind.strip().casefold(), values


def is_branded_not_found(status: int, body: bytes, headers: dict[str, str]) -> bool:
    """A real 404 that a person can use and a crawler will not index: an HTML
    page that says noindex and links back to the entry page."""
    meta = [match.group(1).lower() for match in _META_ROBOTS.finditer(body)]
    return (status == 404 and media_type(headers)[0] == "text/html"
            and bool(meta) and all(b"noindex" in value for value in meta)
            and b'href="/zh-TW/"' in body)


def _same_origin_location(base_url: str, headers: dict[str, str]) -> str | None:
    location = _header(headers, "location")
    if location is not None and location.startswith(base_url + "/"):
        return location[len(base_url):]
    return location


def _public_discovery_cases(base_url: str, page: bytes) -> dict[str, bool]:
    status, robots, _ = _request(base_url + "/robots.txt")
    cases = {
        "robots_txt_admits_pages_not_api": status == 200 and robots_admit_pages_not_api(base_url, robots),
        "entrypoint_meta_indexable": page_meta_indexable(page),
        "unknown_page_404": _request(base_url + _UNKNOWN_PAGE_PROBE_PATH)[0] == 404,
    }
    cases["unknown_page_branded_noindex_404"] = all(
        is_branded_not_found(*_request(base_url + path)) for path in _ERROR_PAGE_PROBE_PATHS)
    status, _, headers = _request(base_url + _UNKNOWN_API_PROBE_PATH)
    cases["unknown_api_path_json_404"] = status == 404 and media_type(headers)[0] == "application/json"
    typed = []
    for path, accepted in _DISCOVERY_MEDIA_TYPES.items():
        status, body, headers = _request(base_url + path)
        kind, parameters = media_type(headers)
        typed.append(status == 200 and kind in accepted and parameters.get("charset") == "utf-8")
        if path == "/feed.xml":
            cases["atom_feed_served"] = status == 200 and b"<feed" in body \
                and kind == "application/atom+xml"
        if path == "/llms.txt":
            cases["llms_txt_served"] = status == 200 and body.startswith(b"# ")
        if path == "/llms-full.txt":
            cases["llms_full_txt_served"] = status == 200 and body.startswith(b"# ")
        if path == _INDEXNOW_KEY_PATH:
            # Exactly the key: an engine compares the file with the key it was sent.
            cases["indexnow_key_served"] = status == 200 and body == INDEXNOW_KEY.encode("ascii")
    cases["discovery_files_typed_utf8"] = all(typed)
    redirects = []
    for spelling, canonical in _NONCANONICAL_SPELLINGS:
        status, _, headers = _request(base_url + spelling)
        redirects.append(status == 308 and _same_origin_location(base_url, headers) == canonical)
    cases["noncanonical_spellings_redirect_once"] = all(redirects)
    return cases


def origin_redirect_is_bare(status: int, headers: dict[str, str], expected: str) -> bool:
    """A permanent redirect to `expected`, the path without the query the
    request carried (an outside link may put birth data there), that no cache
    keeps."""
    return status == 308 and _header(headers, "location") == expected \
        and "no-store" in cache_directives(headers)


def _canonical_host_cases(base_url: str) -> dict[str, bool]:
    """www and plain HTTP each reach the apex over HTTPS in one permanent hop,
    keeping the path only, so the site has one origin; the plain-HTTP root
    reaches the entry page in that one hop, not the HTTPS root."""
    apex, www = deployment_hostnames(urlparse(base_url).hostname or "")
    path = "/zh-TW/calculate"
    observed = [_request(origin + path + "?armillary-verifier=1") for origin in (f"https://{www}", f"http://{www}")]
    roots = [_request(origin + "/?armillary-verifier=1") for origin in (f"http://{apex}", f"http://{www}")]
    return {"www_redirects_to_apex_308": all(
        origin_redirect_is_bare(status, headers, f"https://{apex}{path}") for status, _, headers in observed),
        "http_root_redirects_to_entry_308": all(
            origin_redirect_is_bare(status, headers, f"https://{apex}{ENTRY_PATH}") for status, _, headers in roots)}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


_DIRECT_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def read_approved_hostname(path: Path) -> str:
    lines = read_owner_only(path, role="approved hostname", minimum_bytes=3, maximum_bytes=254).decode().splitlines()
    if len(lines) != 1 or lines[0] != lines[0].strip():
        raise ValueError("approved hostname file must contain one clean line")
    return validate_server_name(lines[0])


def _bounded_response_body(response, maximum_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    length = response.headers.get("Content-Length")
    if length is not None and int(length) > maximum_bytes:
        raise ValueError("staging response exceeds bounded byte limit")
    body = response.read(maximum_bytes + 1)
    if len(body) > maximum_bytes:
        raise ValueError("staging response exceeds bounded byte limit")
    return body


def _request(url: str, *, body: bytes | None = None,
             content_type: str | None = None, extra_headers: dict[str, str] | None = None,
             timeout: float = 35, maximum_bytes: int = MAX_RESPONSE_BYTES) -> tuple[int, bytes, dict[str, str]]:
    headers = dict(extra_headers or {})
    if content_type:
        headers["Content-Type"] = content_type
    try:
        with _DIRECT_OPENER.open(Request(url, data=body, headers=headers), timeout=timeout) as response:
            return response.status, _bounded_response_body(response, maximum_bytes), dict(response.headers)
    except HTTPError as error:
        return error.code, _bounded_response_body(error, maximum_bytes), dict(error.headers)
    except (URLError, OSError, TimeoutError):
        return 0, b"", {}


def validate_base_url(base_url: str, *, approved_hostname: str | None = None) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or parsed.port not in (None, 443):
        raise ValueError("real staging verification requires HTTPS port 443")
    if (not parsed.hostname or parsed.path not in ("", "/") or parsed.params or parsed.query
            or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("base URL must be a bare origin without credentials")
    if parsed.netloc != parsed.hostname + (f":{parsed.port}" if parsed.port is not None else ""):
        raise ValueError("base URL authority is malformed")
    if approved_hostname is None:
        raise ValueError("real staging verification requires approved hostname")
    if parsed.hostname != validate_server_name(approved_hostname):
        raise ValueError("base URL does not match approved staging hostname")
    return base_url.rstrip("/")


def _entrypoint(base_url: str) -> tuple[int, bytes, dict[str, str]]:
    status, body, headers = _request(base_url + "/")
    if status == 308 and headers.get("location") == ENTRY_PATH:
        # Only the one same-origin entrypoint the frontend owns is followed.
        status, body, headers = _request(base_url + ENTRY_PATH)
    return status, body, headers


def _robots_noindex(headers: dict[str, str]) -> bool:
    return "noindex" in {key.casefold(): value for key, value in headers.items()}.get(
        "x-robots-tag", "").casefold()


def _tls_handshake_signed(address: str, server_name: str, *arguments: str) -> bool | None:
    """Whether `openssl s_client` completes a handshake in which the edge signed; None when it cannot run."""
    try:
        done = subprocess.run(["openssl", "s_client", "-connect", address, "-servername", server_name, *arguments],
                              input="", capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.returncode == 0 and "Peer signature type" in done.stdout


# Python's ssl module cannot narrow the signature algorithms a client offers,
# so the case asks the OpenSSL client.  Its own security level is lowered so
# that only the edge can refuse.
_WEAK_SIGNATURES = ("ECDSA+SHA224:RSA+SHA224", "ECDSA+SHA1:RSA+SHA1")


def tls12_signature_case(hostname: str, *, address: str | None = None) -> bool:
    """An ordinary TLS 1.2 client completes its handshake, and one that offers
    only SHA-224 or only SHA-1 signatures is refused (the edge's
    ssl_conf_command SignatureAlgorithms).  A client that cannot run proves nothing."""
    address = address or f"{hostname}:443"
    ordinary = _tls_handshake_signed(address, hostname, "-tls1_2")
    weak = [_tls_handshake_signed(address, hostname, "-tls1_2", "-sigalgs", offered, "-cipher", "DEFAULT:@SECLEVEL=0")
            for offered in _WEAK_SIGNATURES]
    return ordinary is True and all(result is False for result in weak)


def verify(base_url: str, *, approved_hostname: str | None = None, noindex: bool = False) -> dict[str, object]:
    """Every live case against the edge; `noindex` expects the staging rendering's header."""
    base_url = validate_base_url(base_url, approved_hostname=approved_hostname)
    cases: dict[str, bool] = {}
    http_origin = f"http://{urlparse(base_url).hostname}"
    status, _, headers = _request(http_origin + "/http-boundary?discard=sensitive")
    cases["http_redirect_308"] = origin_redirect_is_bare(status, headers, base_url + "/http-boundary")
    status, _, _ = _request(http_origin + "/.well-known/acme-challenge/armillary-missing")
    cases["http_acme_missing_404"] = status == 404
    status, page, headers = _entrypoint(base_url)
    cases["anonymous_entrypoint_200"] = status == 200
    cases["edge_noindex_as_rendered"] = status == 200 and _robots_noindex(headers) is noindex
    cases["hsts"] = hsts_is_sufficient(headers.get("Strict-Transport-Security", ""))
    cases["tls12_signs_with_sha256_or_stronger"] = tls12_signature_case(urlparse(base_url).hostname or "")
    cases.update(_public_cache_cases(base_url, page, headers))
    cases.update(_public_discovery_cases(base_url, page))
    cases.update(_canonical_host_cases(base_url))
    status, _, api_headers = _request(base_url + "/api/health")
    cases["anonymous_api_200"] = status == 200 and _robots_noindex(api_headers) is noindex
    status, body, _ = _request(base_url + "/robots.txt")
    cases["robots_txt_served"] = status == 200 and b"Sitemap:" in body
    status, body, _ = _request(base_url + "/sitemap.xml")
    cases["sitemap_xml_served"] = status == 200 and b"<urlset" in body
    # Readiness is the container health check's; the edge answers it 404 itself.
    for path in ("/openapi.json", "/api/runtime-health", "/api/health/ready"):
        cases[path] = _request(base_url + path)[0] == 404
    return {"schema_version": 6, "edge_noindex": noindex,
            "result": "pass" if all(cases.values()) else "fail", "cases": cases,
            "base_url_recorded": False}


# --- edge configuration: NGINX parser and the closed log sink model -------------
# The edge's log sinks, closed, with this module as their one producer; the
# configuration generator's --verify applies it to `nginx -T`.  Every directive that can write request data to a file, a socket or
# syslog is listed with the only arguments the deployment approves; any other
# value anywhere in the configuration is a refusal.  Absence is not silence:
# NGINX's compiled-in defaults log every request (`access_log logs/access.log
# combined`) and errors at level `error`, so every server, the http block and
# the main context must each declare the approved value.  The privacy canary
# reads the same model to decide which edge sinks exist (EDGE_FILE_SINKS) and
# why each is quiet; no caller names them.
APPROVED_ACCESS_LOG = ("off",)
APPROVED_ERROR_LOG = ("/var/log/nginx/error.log", "emerg")
LOG_SINK_DIRECTIVES = {
    "access_log": (APPROVED_ACCESS_LOG,),
    "error_log": (APPROVED_ERROR_LOG,),
    "client_body_in_file_only": (("off",),),
    "proxy_store": (("off",),),
    "fastcgi_store": (("off",),),
    "uwsgi_store": (("off",),),
    "scgi_store": (("off",),),
}
EDGE_FILE_SINKS = (Path(APPROVED_ERROR_LOG[0]),)
NGINX_DUMP_TIMEOUT_SECONDS = 30


class _Block(NamedTuple):
    name: str
    args: tuple[str, ...]
    children: tuple["_Block", ...] | None


def _nginx_tokens(text: str):
    """Yield NGINX configuration tokens: words, quoted strings and `{ } ;`."""
    index, length = 0, len(text)
    while index < length:
        character = text[index]
        if character.isspace():
            index += 1
        elif character == "#":
            while index < length and text[index] != "\n":
                index += 1
        elif character in "{};":
            yield character, False
            index += 1
        elif character in "'\"":
            end, value = index + 1, []
            while end < length and text[end] != character:
                if text[end] == "\\" and end + 1 < length:
                    end += 1
                value.append(text[end])
                end += 1
            if end >= length:
                raise ValueError("unterminated quoted string in NGINX configuration")
            yield "".join(value), True
            index = end + 1
        else:
            end = index
            while end < length and not text[end].isspace() and text[end] not in "{};":
                if text[end] == "$" and end + 1 < length and text[end + 1] == "{":
                    end = text.index("}", end) + 1
                    continue
                end += 1
            yield text[index:end], False
            index = end


def parse_nginx(text: str) -> tuple[_Block, ...]:
    """Parse NGINX configuration (one file or an `nginx -T` dump) into blocks."""
    stack: list[list[_Block]] = [[]]
    heads: list[tuple[str, tuple[str, ...]]] = []
    words: list[str] = []
    for token, quoted in _nginx_tokens(text):
        if quoted or token not in "{};":
            words.append(token)
        elif token == ";":
            if not words:
                raise ValueError("empty NGINX directive")
            stack[-1].append(_Block(words[0], tuple(words[1:]), None))
            words = []
        elif token == "{":
            if not words:
                raise ValueError("NGINX block without a name")
            heads.append((words[0], tuple(words[1:])))
            stack.append([])
            words = []
        else:
            if words or not heads:
                raise ValueError("unbalanced NGINX block")
            name, args = heads.pop()
            children = tuple(stack.pop())
            stack[-1].append(_Block(name, args, children))
    if words or heads:
        raise ValueError("NGINX configuration ends inside a directive or block")
    return tuple(stack[0])


def _walk(blocks, *, stop_at: str | None = None):
    for block in blocks:
        yield block
        if block.children is not None and block.name != stop_at:
            yield from _walk(block.children, stop_at=stop_at)


def _directives(block: _Block, name: str) -> list[tuple[str, ...]]:
    return [child.args for child in block.children or () if child.name == name]


def log_sink_model_errors(text: str, *, require_main_context: bool = True) -> list[str]:
    """Name every way `text` could write request data outside the approved sinks.

    `require_main_context` (the default) demands an `nginx -T` dump: without
    the main context and the http block, the defaults that apply when nothing
    is declared cannot be ruled out.  The renderer passes False for a site file.
    """
    try:
        tree = parse_nginx(text)
    except ValueError as error:
        return [f"configuration does not parse: {error}"]
    errors: list[str] = []
    for block in _walk(tree):
        approved = LOG_SINK_DIRECTIVES.get(block.name)
        if approved is not None and block.children is None and block.args not in approved:
            errors.append(f"{block.name} {' '.join(block.args)}: not an approved log sink")
    expected = (("access_log", APPROVED_ACCESS_LOG), ("error_log", APPROVED_ERROR_LOG))
    servers = [block for block in _walk(tree) if block.name == "server" and block.children is not None]
    if not servers:
        errors.append("no server block: nothing to hold to the log sink model")
    for server in servers:
        label = "server " + " ".join(
            next((child.args for child in server.children if child.name == "server_name"), ("?",)))
        for name, value in expected:
            found = _directives(server, name)
            if found != [value]:
                errors.append(f"{label}: {name} {found} is not exactly {[value]}")
    if require_main_context:
        main_error_logs = [block.args for block in tree if block.name == "error_log"]
        if main_error_logs != [APPROVED_ERROR_LOG]:
            errors.append(f"main context: error_log {main_error_logs} is not exactly {[APPROVED_ERROR_LOG]}")
        http_blocks = [block for block in tree if block.name == "http" and block.children is not None]
        if len(http_blocks) != 1:
            errors.append(f"expected exactly one http block, found {len(http_blocks)}")
        elif _directives(http_blocks[0], "access_log") != [APPROVED_ACCESS_LOG]:
            errors.append("http block: access_log is not exactly off")
    return errors


def nginx_effective_configuration() -> str:
    """Return `nginx -T`: every file NGINX reads, includes resolved, as it parses them.

    This is the on-disk configuration as NGINX resolves it, not a dump of a
    running master: a configuration written but not yet reloaded is what is
    checked here.  Failure to obtain it is an error, never an empty pass.
    """
    try:
        completed = subprocess.run(
            ["nginx", "-T"], capture_output=True, text=True, check=False,
            timeout=NGINX_DUMP_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"nginx -T could not run: {error}") from None
    if completed.returncode != 0 or "# configuration file " not in completed.stdout:
        raise ValueError(f"nginx -T reported no configuration (exit {completed.returncode})")
    return completed.stdout



# --- privacy canary --------------------------------------------------------------
class SinkDisposition(str, Enum):
    """Why a sink in the closed universe counts as covered, or that it does not."""

    OBSERVED_ACTIVITY = "observed_activity"
    QUIET_BY_VERIFIED_CONFIGURATION = "quiet_by_verified_configuration"
    # Every file of the sink was searched and none changed after the canary
    # started, so none can hold it (a modification time is set by the writer).
    UNCHANGED_SINCE_CANARY_START = "unchanged_since_canary_start"
    NOT_OBSERVED = "not_observed"


COVERED_DISPOSITIONS = frozenset({
    SinkDisposition.OBSERVED_ACTIVITY.value,
    SinkDisposition.QUIET_BY_VERIFIED_CONFIGURATION.value,
    SinkDisposition.UNCHANGED_SINCE_CANARY_START.value,
})
# The host sinks every receipt must carry, beside the edge and the exact
# application container.  Read-only: the scans run journalctl, read files and
# run `docker inspect`/`docker logs`; nothing is written or rotated.
HOST_SINK_ROLES = ("host_journal_since_canary_start", "host_var_log_tree", "host_container_log_streams")
HOST_LOG_ROOT = Path("/var/log")
HOST_SCAN_TIMEOUT_SECONDS = 120
MAX_HOST_FILE_BYTES = 512 * 1024 * 1024
UNSCANNABLE_SUFFIXES = (".xz", ".zst", ".bz2", ".lz4")


class Canary(NamedTuple):
    marker: str
    payload_bytes: bytes
    sensitive_fragments: tuple[str, ...]


def generate_canary() -> Canary:
    marker = "PA-" + secrets.token_hex(16)
    year, minute = 1960 + secrets.randbelow(55), secrets.randbelow(60)
    latitude = round(-70 + secrets.randbelow(1400000) / 10000, 4)
    longitude = round(-170 + secrets.randbelow(3400000) / 10000, 4)
    payload = {
        "datetime": {"year": year, "month": 2, "day": 3, "hour": 4, "minute": minute, "second": 17},
        "timezone": {"mode": "iana", "iana_name": "Etc/UTC"},
        "location": {"latitude": latitude, "longitude": longitude, "altitude_m": 37},
    }
    return _canary(marker, payload)


def derive_canary(canary: Canary, payload: dict[str, Any]) -> Canary:
    """The same marker carried by another synthetic payload (a drill's variant).

    The fragments are those of the new payload together with the original
    ones, from the one fragment producer below, so a scan for the derived
    canary also finds every rendering of the payload it was derived from.
    """
    derived = _canary(canary.marker, payload)
    return derived._replace(sensitive_fragments=tuple(dict.fromkeys(
        derived.sensitive_fragments + canary.sensitive_fragments)))


def _canary(marker: str, payload: dict[str, Any]) -> Canary:
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    moment, location = payload["datetime"], payload["location"]
    year, minute = moment["year"], moment["minute"]
    latitude, longitude = location["latitude"], location["longitude"]
    fragments = [marker, f'"year":{year}', f'"minute":{minute}', f'"latitude":{latitude}',
                 f'"longitude":{longitude}', payload["timezone"]["iana_name"], f"'year': {year}",
                 f'"year": {year}', f"'minute': {minute}", f'"minute": {minute}', f"{latitude},{longitude}"]
    for field, value in (("latitude", latitude), ("longitude", longitude)):
        for rendered in {str(value), format(value, "g")}:
            fragments += [f"'{field}': {rendered}", f'"{field}": {rendered}', f"{field}={rendered}"]
    fragments += [base64.b64encode(marker.encode("ascii")).decode("ascii"),
                  base64.b64encode(encoded).decode("ascii"), quote_from_bytes(encoded), encoded.hex()]
    return Canary(marker, encoded, tuple(dict.fromkeys(fragments)))


def _matches(canary: Canary, content: str) -> int:
    return sum(1 for fragment in canary.sensitive_fragments if fragment in content)


def scanner_self_test(canary: Canary) -> bool:
    """The scanner must find its own payload in several renderings and in a real file."""
    payload = json.loads(canary.payload_bytes)
    year, location = payload["datetime"]["year"], payload["location"]
    controls = (canary.payload_bytes.decode("utf-8"), json.dumps(payload, indent=2),
                repr({"year": year, "latitude": location["latitude"]}),
                f"chart computed for {location['latitude']},{location['longitude']}")
    if not all(_matches(canary, control) > 0 for control in controls):
        return False
    with tempfile.TemporaryDirectory(prefix="armillary-canary-control-") as directory:
        control_path = Path(directory) / "positive-control.log"
        write_owner_only_new(control_path, (canary.marker + "\n").encode("utf-8"))
        return _matches(canary, control_path.read_text(encoding="utf-8")) > 0


def scan_sinks(canary: Canary, sinks: list[Path], *,
               disposition: SinkDisposition = SinkDisposition.NOT_OBSERVED) -> dict:
    """Search file sinks for the canary.  A missing file holds nothing to match."""
    results: list[dict[str, Any]] = []
    for sink in sinks:
        # Only "no such file" is absence; a sink that cannot be read (its
        # directory closed to this process, say) is not observed, never empty.
        readable = True
        try:
            content = sink.read_text(encoding="utf-8", errors="replace")
            present = True
        except FileNotFoundError:
            content, present = "", False
        except OSError:
            content, present, readable = "", True, False
        results.append({
            "sink_name_sha256": hashlib.sha256(sink.name.encode("utf-8")).hexdigest(),
            "sink_role": "edge_file_sink",
            "present": present,
            "match_count": _matches(canary, content),
            "byte_length": len(content.encode("utf-8")),
            "line_count": len(content.splitlines()),
            "disposition": (SinkDisposition(disposition) if readable
                            else SinkDisposition.NOT_OBSERVED).value,
        })
    observed = [item["disposition"] in COVERED_DISPOSITIONS for item in results]
    return {
        "schema_version": 1,
        "marker_sha256": hashlib.sha256(canary.marker.encode("ascii")).hexdigest(),
        "sinks": results,
        "total_match_count": sum(item["match_count"] for item in results),
        "all_sinks_covered": bool(results) and all(observed),
        "scanner_self_test_passed": scanner_self_test(canary),
        "provider_invisible_sinks": "not_inspectable",
        "credential_material_recorded": False,
        "request_or_response_recorded": False,
    }


def host_fragments(canary: Canary) -> tuple[str, ...]:
    """The fragments searched for in host sinks, which hold everyone's logs.

    The application and edge sinks are searched for every fragment.  The host
    journal and /var/log also carry text this deployment does not write, where
    the low-entropy renderings (the fixed time zone name, a year, a minute)
    would match by chance and fail a clean host.  There the marker and every
    rendering that carries a random coordinate or the whole payload are kept;
    a logged request body always carries those.
    """
    payload = json.loads(canary.payload_bytes)
    generic = (payload["timezone"]["iana_name"], "year", "minute")
    return tuple(fragment for fragment in canary.sensitive_fragments
                 if canary.marker in fragment or not any(word in fragment for word in generic)
                 or len(fragment) > 64)


class _StreamMatches:
    """The canary's host fragments found in a byte stream read in chunks."""

    def __init__(self, canary: Canary) -> None:
        self.fragments = host_fragments(canary)
        self.found: set[str] = set()
        self.tail = ""
        self.overlap = max(len(fragment) for fragment in self.fragments)
        self.byte_length = 0

    def feed(self, chunk: bytes | str) -> None:
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8", errors="replace")
        self.byte_length += len(chunk)
        text = self.tail + chunk.decode("utf-8", errors="replace")
        self.found.update(fragment for fragment in self.fragments if fragment in text)
        self.tail = text[-self.overlap:]


def _as_bytes(value: bytes | str | None) -> bytes:
    return value.encode("utf-8", errors="replace") if isinstance(value, str) else (value or b"")


def _host_sink(role: str, matches: int, disposition: SinkDisposition, **counts: int) -> dict[str, Any]:
    return {"sink_name_sha256": hashlib.sha256(role.encode("ascii")).hexdigest(), "sink_role": role,
            "match_count": matches, **counts, "disposition": SinkDisposition(disposition).value}


def scan_host_journal(canary: Canary, *, since: float, run=subprocess.run) -> dict[str, Any]:
    """The whole journal since the canary started: every unit and the kernel."""
    command = ["journalctl", "--since", f"@{max(int(since) - 1, 0)}", "--output", "export",
               "--no-pager", "--quiet"]
    try:
        completed = run(command, capture_output=True, check=False, timeout=HOST_SCAN_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        completed = None
    if completed is None or completed.returncode != 0:
        return _host_sink(HOST_SINK_ROLES[0], 0, SinkDisposition.NOT_OBSERVED, entry_count=0, byte_length=0)
    matches = _StreamMatches(canary)
    matches.feed(completed.stdout)
    entries = _as_bytes(completed.stdout).count(b"__CURSOR=")
    # The application writes to this journal (journald log driver), so a window
    # with no entry at all means the journal was not readable, not quiet.
    return _host_sink(HOST_SINK_ROLES[0], len(matches.found),
                      SinkDisposition.OBSERVED_ACTIVITY if entries else SinkDisposition.NOT_OBSERVED,
                      entry_count=entries, byte_length=matches.byte_length)


def scan_host_log_tree(canary: Canary, *, since: float, root: Path | None = None) -> dict[str, Any]:
    """Every regular file under /var/log changed since the canary started.

    A file not modified since then cannot hold the canary.  The binary journal
    directory is read through journalctl instead; gzip is decompressed; any
    other compression, an unreadable file or one past the size bound leaves the
    sink not observed.
    """
    root = HOST_LOG_ROOT if root is None else root
    threshold = max(int(since) - 1, 0)
    files = changed = 0
    found: set[str] = set()
    total = 0
    # A directory the walk cannot list may hold a changed file: counted, never skipped.
    unlisted: list[OSError] = []
    unreadable = 0
    for directory, subdirectories, names in os.walk(root, followlinks=False, onerror=unlisted.append):
        if Path(directory) == root:
            subdirectories[:] = [name for name in subdirectories if name != "journal"]
        for name in names:
            path = Path(directory, name)
            try:
                metadata = path.lstat()
            except OSError:
                unreadable += 1
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            files += 1
            if metadata.st_mtime < threshold:
                continue
            changed += 1
            if name.endswith(UNSCANNABLE_SUFFIXES) or metadata.st_size > MAX_HOST_FILE_BYTES:
                unreadable += 1
                continue
            matches = _StreamMatches(canary)
            try:
                with (gzip.open(path, "rb") if name.endswith(".gz") else path.open("rb")) as handle:
                    while chunk := handle.read(1024 * 1024):
                        matches.feed(chunk)
                        if matches.byte_length > MAX_HOST_FILE_BYTES:
                            raise OSError("file grew past the scan bound")
            except (OSError, EOFError, gzip.BadGzipFile):
                unreadable += 1
                continue
            found |= matches.found
            total += matches.byte_length
    unreadable += len(unlisted)
    if not root.is_dir() or unreadable:
        disposition = SinkDisposition.NOT_OBSERVED
    elif changed:
        disposition = SinkDisposition.OBSERVED_ACTIVITY
    else:
        disposition = SinkDisposition.UNCHANGED_SINCE_CANARY_START
    return _host_sink(HOST_SINK_ROLES[1], len(found), disposition, file_count=files,
                      changed_file_count=changed, unreadable_file_count=unreadable, byte_length=total)


def scan_host_containers(canary: Canary, *, since: float, run=subprocess.run) -> dict[str, Any]:
    """The log stream of every container on the host, running or not."""
    def docker(*arguments: str):
        try:
            return run(["docker", *arguments], capture_output=True, check=False,
                       timeout=HOST_SCAN_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            return None

    listed = docker("ps", "--all", "--quiet", "--no-trunc")
    if listed is None or listed.returncode != 0:
        return _host_sink(HOST_SINK_ROLES[2], 0, SinkDisposition.NOT_OBSERVED, container_count=0,
                          unreadable_container_count=0, byte_length=0)
    containers = _as_bytes(listed.stdout).decode("ascii", errors="replace").split()
    found: set[str] = set()
    unreadable = total = 0
    for container in containers:
        inspected = docker("inspect", "--format", "{{.HostConfig.LogConfig.Type}}", container)
        if inspected is None or inspected.returncode != 0:
            unreadable += 1
            continue
        if _as_bytes(inspected.stdout).strip() == b"none":
            continue   # writes no log at all
        logs = docker("logs", "--since", f"{since:.9f}", container)
        if logs is None or logs.returncode != 0:
            unreadable += 1
            continue
        matches = _StreamMatches(canary)
        matches.feed(_as_bytes(logs.stdout) + _as_bytes(logs.stderr))
        found |= matches.found
        total += matches.byte_length
    disposition = (SinkDisposition.NOT_OBSERVED if unreadable or not containers
                   else SinkDisposition.OBSERVED_ACTIVITY)
    return _host_sink(HOST_SINK_ROLES[2], len(found), disposition, container_count=len(containers),
                      unreadable_container_count=unreadable, byte_length=total)


def scan_host_sinks(canary: Canary, since: float) -> list[dict[str, Any]]:
    """The journal window, /var/log and every container, as root on the host."""
    if os.geteuid() != 0:
        # Without root the journal and /var/log are partial: nothing is observed.
        return [_host_sink(role, 0, SinkDisposition.NOT_OBSERVED) for role in HOST_SINK_ROLES]
    return [scan_host_journal(canary, since=since), scan_host_log_tree(canary, since=since),
            scan_host_containers(canary, since=since)]


APPLICATION_SERVICE = "armillary-app"


def _compose_command(*arguments: str) -> list[str]:
    return ["docker", "compose", "--file", str(ROOT / "deploy/compose.yaml"),
            "--file", str(ROOT / "deploy/staging/compose.staging.yaml"), *arguments]


def compose_runtime_declaration() -> dict[str, dict]:
    """The application's tmpfs mounts and networks as `docker compose config` renders the compose files.

    ``tmpfs`` maps a container path to its options (what `docker inspect`
    reports as HostConfig.Tmpfs); ``networks`` maps each network's full name
    to whether it is declared internal.
    """
    completed = subprocess.run(_compose_command("config", "--format", "json"), capture_output=True, text=True,
                               check=False)
    try:
        if completed.returncode != 0:
            raise ValueError(completed.returncode)
        config = json.loads(completed.stdout)
        service = config["services"][APPLICATION_SERVICE]
        tmpfs = dict(entry.split(":", 1) if ":" in entry else (entry, "") for entry in service.get("tmpfs") or ())
        networks = {config["networks"][name]["name"]: config["networks"][name].get("internal") is True
                    for name in service["networks"]}
    except (TypeError, KeyError, AttributeError, ValueError):  # json.JSONDecodeError is a ValueError
        raise ValueError("the compose declaration of the application could not be read "
                         f"(docker compose config exit {completed.returncode})") from None
    return {"tmpfs": tmpfs, "networks": networks}


def _network_is_internal(name: str) -> bool:
    found = subprocess.run(["docker", "network", "inspect", "--format", "{{.Internal}}", name],
                           capture_output=True, text=True, check=False)
    return found.returncode == 0 and found.stdout.strip() == "true"


def require_declared_isolation(observed: dict) -> None:
    """The live container has the declared tmpfs and only internal networks, read back now."""
    declaration = compose_runtime_declaration()
    if not declaration["networks"] or not all(declaration["networks"].values()):
        raise ValueError("the compose declaration gives the application Internet egress (a network not internal)")
    if ((observed.get("HostConfig") or {}).get("Tmpfs") or {}) != declaration["tmpfs"]:
        raise ValueError("application container tmpfs differs from the compose declaration")
    attached = set((observed.get("NetworkSettings") or {}).get("Networks") or {})
    if attached != set(declaration["networks"]):
        raise ValueError("application container networks differ from the compose declaration")
    if not all(_network_is_internal(name) for name in attached):
        raise ValueError("application container has Internet egress: Docker does not report its network internal")


def inspect_application_container(container: str, expected_image_id: str | None) -> str:
    payload = json.loads(subprocess.run(["docker", "inspect", container], check=True, capture_output=True,
                                        text=True).stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise ValueError("application container inspection is incomplete")
    observed = payload[0]
    host_config = observed.get("HostConfig") or {}
    log_config = host_config.get("LogConfig") or {}
    if ((expected_image_id is not None and observed.get("Image") != expected_image_id)
            or log_config.get("Type") != EXPECTED_LOG_DRIVER
            or not isinstance(observed.get("Id"), str) or not observed["Id"]):
        raise ValueError("application log sink is not bound to the exact candidate")
    # The runtime the deployment declares (deploy/compose.yaml), read back from the live container.
    if host_config.get("ReadonlyRootfs") is not True:
        raise ValueError("application container root file system is not read-only")
    ports = (observed.get("NetworkSettings") or {}).get("Ports") or {}
    if host_config.get("PortBindings") or any(ports.values()):
        raise ValueError("application container publishes a host port")
    require_declared_isolation(observed)
    return observed["Id"]


# The application's X-Request-ID (backend/app/privacy_logging.py: uuid4().hex), also its event's request_id.
REQUEST_ID_PATTERN = re.compile(r"[0-9a-f]{32}")


def scan_application_logs(canary: Canary, container: str, *, since: float,
                          run_request_ids: tuple[str, ...] | None = None) -> dict[str, object]:
    """The exact container's log stream since ``since``.

    On the live host it is observed only when it shows one of
    ``run_request_ids``, the IDs the application answered this run's requests
    with: any other line (a health check, another visitor) proves the stream is
    written, not that this run's requests reached it.  The IDs are counted,
    never recorded.  ``None`` is a disposable container (Gate D's drills),
    which only the run that started it writes to.
    """
    completed = subprocess.run(["docker", "logs", "--since", f"{since:.9f}", container], check=True,
                               capture_output=True, text=True)
    content = completed.stdout + completed.stderr
    identifiers = {value for value in run_request_ids or () if REQUEST_ID_PATTERN.fullmatch(value)}
    read = sum(1 for value in identifiers if value in content)
    observed = bool(content) if run_request_ids is None else read > 0
    return {
        "sink_name_sha256": hashlib.sha256(container.encode("utf-8")).hexdigest(),
        "sink_role": "exact_container_docker_log_stream",
        "match_count": _matches(canary, content),
        "byte_length": len(content.encode("utf-8")),
        "line_count": len(content.splitlines()),
        "changed_since_request_start": bool(content),
        "run_request_id_count": len(identifiers),
        "run_request_ids_read": read,
        "disposition": (SinkDisposition.OBSERVED_ACTIVITY if observed
                        else SinkDisposition.NOT_OBSERVED).value,
    }


def exercise_requests(base_url: str, canary: Canary) -> dict[str, object]:
    header = {"X-Private-Alpha-Canary": canary.marker}
    request_ids: list[str] = []

    def chart(body: bytes, content_type: str = "application/json") -> int:
        status, _body, headers = _request(base_url + "/api/chart", body=body, content_type=content_type,
                                          extra_headers=header)
        value = {key.casefold(): item for key, item in headers.items()}.get("x-request-id", "")
        if REQUEST_ID_PATTERN.fullmatch(value):
            request_ids.append(value)
        return status

    # A canary derived from the annual smoke body carries its `annual` member, which the
    # chart route refuses; the chart cases send the chart body it was derived from.
    chart_payload = json.loads(canary.payload_bytes)
    chart_payload.pop("annual", None)
    chart_body = json.dumps(chart_payload, separators=(",", ":")).encode("utf-8")
    invalid = json.loads(chart_body)
    invalid["datetime"]["month"] = 13
    invalid[canary.marker] = canary.marker
    cases: dict[str, object] = {
        "success": chart(chart_body),
        "422": chart(json.dumps(invalid).encode()),
        "malformed": chart(b'{"canary":"' + canary.marker.encode()),
        "413": chart(canary.marker.encode() + b"x" * (17 * 1024)),
        "415": chart(canary.marker.encode(), "text/plain"),
    }
    burst: list[int] = []
    for _ in range(45):
        burst.append(chart(b'{"canary":"' + canary.marker.encode()))
        if burst[-1] == 429:
            break
    cases["429"] = 429 if 429 in burst else "not_observed"
    return {**cases, **DEFERRED_REQUEST_CASES, "run_request_ids": tuple(dict.fromkeys(request_ids))}


# The flagged annual route (backend/app/refusals.py ANNUAL_ROUTE; the host
# cannot import that module).  Whether the live container registers it is read
# from that container's environment with the application's own reading of the
# flag, never inferred from an answer: a container meant to serve it that
# answers 404 is a failure, not an "off".
ANNUAL_ROUTE_PATH = "/api/chart/annual"
ANNUAL_SMOKE_SELECTION = {"target_kind": "completed_years", "target_value": 1}
# The smoke asks for the page view by name, the request the calculator sends,
# so it also runs the projection code on the host.
ANNUAL_SMOKE_QUERY = "?projection=page"
ANNUAL_SMOKE_EXPECTATIONS = {"success": 200, "gzip_json": True, "no_store": True}


def annual_route_flag(container: str | None) -> str:
    """`on`, `off`, `invalid` (a value the application refuses to start with) or
    `not_observed` (no container to read)."""
    if container is None:
        return "not_observed"
    completed = subprocess.run(["docker", "inspect", container], check=False, capture_output=True, text=True)
    try:
        if completed.returncode != 0:
            raise ValueError(completed.returncode)
        [observed] = json.loads(completed.stdout)
        variables = (observed.get("Config") or {}).get("Env") or []
        environment = dict(item.split("=", 1) for item in variables if isinstance(item, str) and "=" in item)
    except (TypeError, ValueError, AttributeError):
        return "not_observed"
    flag = {key: value for key, value in environment.items() if key == ANNUAL_ROUTE_ENVIRONMENT_VARIABLE}
    try:
        return "on" if load_settings(flag).enable_annual_route else "off"
    except RuntimeError:
        return "invalid"


def annual_smoke_payload(canary: Canary) -> dict[str, Any]:
    """The canary's synthetic birth with one annual selection: the same marker
    and fragments, so the sink search also covers what the annual path logs."""
    payload = json.loads(canary.payload_bytes)
    payload["annual"] = dict(ANNUAL_SMOKE_SELECTION)
    return payload


def exercise_annual_route(base_url: str, canary: Canary, flag: str) -> dict[str, Any]:
    """With the flag on, one synthetic annual request through the real path;
    otherwise nothing is sent and the smoke is named `not_run` with its reason."""
    if flag != "on":
        reason = {"off": "flag_off", "not_observed": "application_container_not_observed",
                  "invalid": "flag_value_invalid"}[flag]
        return {"flag": flag, "smoke": "not_run", "not_run_reason": reason, "cases": {}, "run_request_ids": ()}
    status, body, headers = _request(
        # Encoded as the canary encodes a payload, so the body as sent is one of
        # the renderings derive_canary searches for.
        base_url + ANNUAL_ROUTE_PATH + ANNUAL_SMOKE_QUERY,
        body=json.dumps(annual_smoke_payload(canary), separators=(",", ":")).encode(),
        content_type="application/json",
        extra_headers={"X-Private-Alpha-Canary": canary.marker, "Accept-Encoding": "gzip"})
    lowered = {key.casefold(): value for key, value in headers.items()}
    try:
        decoded = json.loads(gzip.decompress(body)) if lowered.get("content-encoding") == "gzip" else None
    except (OSError, ValueError, EOFError):
        decoded = None
    cases = {"success": status, "gzip_json": isinstance(decoded, dict), "no_store": is_no_store(headers)}
    request_id = lowered.get("x-request-id", "")
    return {"flag": flag, "smoke": "pass" if cases == ANNUAL_SMOKE_EXPECTATIONS else "fail",
            "not_run_reason": None, "cases": cases,
            "run_request_ids": (request_id,) if REQUEST_ID_PATTERN.fullmatch(request_id) else ()}


def annual_route_passes(annual: dict[str, Any]) -> bool:
    """An off flag passes with the smoke not run; on must pass its smoke; a
    flag the application would refuse, or one never read, does not pass."""
    return (annual.get("flag") == "off" and annual.get("smoke") == "not_run") or (
        annual.get("flag") == "on" and annual.get("smoke") == "pass")


def evaluate_request_cases(cases: dict[str, Any]) -> dict[str, bool]:
    return {name: cases.get(name) == status for name, status in REQUEST_CASE_EXPECTATIONS.items()}


def evidence_passes(receipt: dict[str, Any], request_checks: dict[str, bool]) -> bool:
    """Pass needs zero matches, every sink in the closed universe covered, an
    actually observed application sink, a verified edge sink model and a
    working scanner.  A sink that was neither observed nor proven quiet fails."""
    sinks = receipt.get("sinks")
    return (receipt.get("total_match_count") == 0 and receipt.get("application_sink_observed") is True
            and receipt.get("edge_log_sink_model") == "verified"
            and isinstance(sinks, list) and bool(sinks)
            and all(isinstance(sink, dict) and sink.get("disposition") in COVERED_DISPOSITIONS
                    for sink in sinks)
            and set(HOST_SINK_ROLES) <= {sink.get("sink_role") for sink in sinks}
            and receipt.get("scanner_self_test_passed") is True and bool(request_checks)
            and all(request_checks.values()))


def edge_sink_universe(edge_configuration: str | None) -> tuple[str, list[str]]:
    """Return (model verdict, departures) for the edge from its `nginx -T` dump.

    The verdict is ``verified``, ``refused`` (the dump names a sink outside the
    model) or ``not_observed`` (no dump).  The sinks themselves are the model's
    EDGE_FILE_SINKS; the caller never adds or removes one.
    """
    if edge_configuration is None:
        return "not_observed", []
    errors = log_sink_model_errors(edge_configuration)
    return ("refused" if errors else "verified"), errors


def privacy_canary(base_url: str, *, application_container: str | None,
                   expected_image_id: str | None, edge_configuration: str | None,
                   host_sinks=None) -> dict[str, object]:
    """Send one-time sensitive input, then look for it in every sink of the closed universe.

    The universe is the exact application container's log stream, the edge
    file sinks of the log sink model and the host sinks (``host_sinks``: the
    journal since the canary started, /var/log, every container).  ``application_sink_observed`` is true
    only when the container log stream shows a request ID this run's requests were answered with; the edge
    sinks are quiet by verified configuration only when ``edge_configuration``
    (the `nginx -T` dump) is inside the model.  Without either the result
    cannot be a pass.
    """
    canary = generate_canary()
    container = None
    if application_container:
        container = inspect_application_container(application_container, expected_image_id)
        receipt_image = expected_image_id
    else:
        receipt_image = None
    edge_model, edge_errors = edge_sink_universe(edge_configuration)
    flag = annual_route_flag(container)
    if flag == "on":
        canary = derive_canary(canary, annual_smoke_payload(canary))
    started = time.time()
    # Before the chart cases: the 429 burst there empties the bucket the edge
    # serves the annual route from.
    annual = exercise_annual_route(base_url, canary, flag)
    cases = exercise_requests(base_url, canary)
    run_request_ids = cast(tuple[str, ...], cases.pop("run_request_ids", ()))
    run_request_ids = tuple(dict.fromkeys(run_request_ids + tuple(annual.pop("run_request_ids", ()))))
    receipt = scan_sinks(canary, list(EDGE_FILE_SINKS), disposition=(
        SinkDisposition.QUIET_BY_VERIFIED_CONFIGURATION if edge_model == "verified"
        else SinkDisposition.NOT_OBSERVED))
    receipt["edge_log_sink_model"] = edge_model
    # The image inspect_application_container bound the application sink to.
    receipt["application_image_id"] = receipt_image
    receipt["edge_log_sink_departures"] = edge_errors
    if container is not None:
        application_log = scan_application_logs(canary, container, since=started, run_request_ids=run_request_ids)
        receipt["sinks"].append(application_log)
        receipt["total_match_count"] += application_log["match_count"]
        read = application_log.get("run_request_ids_read")
        receipt["application_sink_observed"] = isinstance(read, int) and read > 0
    else:
        receipt["application_sink_observed"] = "not_observed"
    for host_sink in (host_sinks or scan_host_sinks)(canary, started):
        receipt["sinks"].append(host_sink)
        receipt["total_match_count"] += host_sink["match_count"]
    receipt["all_sinks_covered"] = all(
        sink.get("disposition") in COVERED_DISPOSITIONS for sink in receipt["sinks"])
    checks = evaluate_request_cases(cases)
    receipt.update({
        "request_cases": cases, "request_case_checks": checks, "deferred_request_cases": DEFERRED_REQUEST_CASES,
        "annual_route": annual,
        "result": "pass" if evidence_passes(receipt, checks) and annual_route_passes(annual) else (
            "not_observed" if container is None or edge_model == "not_observed" else "fail"),
    })
    return receipt


def _compose_app_container() -> str | None:
    completed = subprocess.run(_compose_command("ps", "--quiet", APPLICATION_SERVICE),
                               check=False, capture_output=True, text=True)
    return completed.stdout.strip() or None if completed.returncode == 0 else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--noindex", action="store_true",
                        help="expect the X-Robots-Tag noindex header of a staging rendering")
    parser.add_argument("--approved-hostname-file", type=Path, required=True)
    parser.add_argument("--application-container", help="container for the privacy canary log sink; "
                        "default: the compose armillary-app container")
    parser.add_argument("--expected-image-id")
    parser.add_argument("--apply", action="store_true", help="send real requests; absent means dry run")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        # As root (Gate E) it hands this checkout's compose files to Docker, so
        # the checkout must be one root can trust.
        try:
            require_privileged_checkout(ROOT)
        except (OSError, ValueError) as error:
            raise SystemExit(f"HTTP VERIFIER REFUSED: {error}") from None
    if not args.apply:
        print(json.dumps({"mode": "plan", "edge_noindex": args.noindex, "network_requests_sent": False},
                         indent=2))
        return
    if not args.expected_image_id:
        # Without it any container would do as the application sink.
        raise SystemExit("--apply requires --expected-image-id (the image the live pair records)")
    approved = read_approved_hostname(safe_path(args.approved_hostname_file))
    receipt = verify(args.base_url, approved_hostname=approved, noindex=args.noindex)
    canary = privacy_canary(
        validate_base_url(args.base_url, approved_hostname=approved),
        application_container=args.application_container or _compose_app_container(),
        expected_image_id=args.expected_image_id,
        edge_configuration=_effective_edge_configuration())
    receipt["privacy_canary"] = canary
    if canary["result"] != "pass":
        receipt["result"] = "fail"
    emit_json_receipt(receipt, args.output)


def _effective_edge_configuration() -> str | None:
    """`nginx -T` on this host, or None when it cannot be read (then not_observed)."""
    try:
        return nginx_effective_configuration()
    except ValueError:
        return None


if __name__ == "__main__":
    main()
