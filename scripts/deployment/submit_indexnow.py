#!/usr/bin/env python3
"""Tell the IndexNow engines (Bing, Yandex, Naver, Seznam) the site's public URLs.

Run once after a release is live, from the checkout of the released revision:
the URLs are the `<loc>` entries of that revision's frontend/sitemap.xml, the
page list build_pages generates.  Every URL must be on the canonical host and
the list must not be empty; otherwise nothing is sent.

Without `--submit` this is a dry run: it prints the JSON body and sends no
request at all.  With `--submit` it first fetches the live key file,
https://projectarmillary.com/<key>.txt, and stops unless the answer is 200 and
its bytes are exactly the key (an engine checks the same file and drops a
submission it cannot verify).  Then it POSTs the body -- `host`, `key` and
`urlList`, nothing else -- to the shared IndexNow endpoint, which forwards it
to every participating engine, and prints the HTTP status.  200 and 202 are
success; anything else exits non-zero.  The key file is at the root and named
after the key, so no `keyLocation` is sent.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
try:
    import app.frontend_assets  # noqa: F401  the canonical package
except ModuleNotFoundError:
    sys.path.insert(0, str(ROOT / "backend"))
from app.frontend_assets import INDEXNOW_KEY, INDEXNOW_KEY_FILE

CANONICAL_HOST = "projectarmillary.com"
ENDPOINT = "https://api.indexnow.org/indexnow"
KEY_URL = f"https://{CANONICAL_HOST}/{INDEXNOW_KEY_FILE}"
DEFAULT_SITEMAP = ROOT / "frontend" / "sitemap.xml"
SUCCESS_STATUSES = frozenset({200, 202})
# The protocol's own limit for one request.
MAX_URLS = 10_000
MAX_RESPONSE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 30
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
# What the IndexNow documentation says each answer means.
_STATUS_MEANING = {
    0: "no answer (network failure)", 200: "OK: the URLs were submitted",
    202: "Accepted: the URLs were received; key validation pending", 400: "Bad request: invalid format",
    403: "Forbidden: the key is not valid (key file not found or not matching)",
    422: "Unprocessable: a URL is not on the host, or the key does not match the schema",
    429: "Too many requests: possible spam"}

# method, URL, body, headers -> status (0 when nothing answered), body
Transport = Callable[[str, str, bytes | None, dict[str, str] | None], tuple[int, bytes]]


class Refused(ValueError):
    """The input cannot be submitted; nothing was sent."""


class _NoRedirect(HTTPRedirectHandler):
    # The key file must answer at its own address; a redirect is an answer to report, not to follow.
    def redirect_request(self, *_args, **_kwargs):
        return None


_DIRECT_OPENER = build_opener(ProxyHandler({}), _NoRedirect())


def http_transport(method: str, url: str, body: bytes | None = None,
                   headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with _DIRECT_OPENER.open(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status, response.read(MAX_RESPONSE_BYTES)
    except HTTPError as error:
        return error.code, error.read(MAX_RESPONSE_BYTES)
    except (URLError, OSError, TimeoutError):
        return 0, b""


def sitemap_urls(data: bytes) -> list[str]:
    """The `<loc>` of every `<url>`, each on the canonical host over HTTPS."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        raise Refused(f"the sitemap is not XML: {error}") from None
    if root.tag != f"{_SITEMAP_NS}urlset": raise Refused("the sitemap is not a sitemaps.org <urlset>")
    urls = [(entry.findtext(f"{_SITEMAP_NS}loc") or "").strip() for entry in root.findall(f"{_SITEMAP_NS}url")]
    if not urls: raise Refused("the sitemap lists no URL")
    if len(urls) > MAX_URLS:
        raise Refused(f"the sitemap lists {len(urls)} URLs; one submission takes at most {MAX_URLS}")
    for url in urls:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.netloc != CANONICAL_HOST:
            raise Refused(f"not on the canonical host https://{CANONICAL_HOST}: {url!r}")
    return urls


def payload(urls: Sequence[str]) -> dict[str, object]:
    return {"host": CANONICAL_HOST, "key": INDEXNOW_KEY, "urlList": list(urls)}


def run(argv: Sequence[str] | None = None, *, transport: Transport = http_transport) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--sitemap", type=Path, default=DEFAULT_SITEMAP,
                        help="the released revision's sitemap (default: frontend/sitemap.xml)")
    parser.add_argument("--submit", action="store_true", help="send the submission; without it nothing is sent")
    args = parser.parse_args(argv)
    try:
        urls = sitemap_urls(args.sitemap.read_bytes())
    except (OSError, Refused) as error:
        print(f"INDEXNOW REFUSED: {error}", file=sys.stderr)
        return 2
    body = payload(urls)
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if not args.submit:
        print(f"DRY RUN: nothing sent ({len(urls)} URLs); --submit sends this to {ENDPOINT}")
        return 0
    status, served = transport("GET", KEY_URL, None, None)
    if status != 200 or served != INDEXNOW_KEY.encode("ascii"):
        print(f"INDEXNOW KEY MISMATCH: {KEY_URL} answered HTTP {status} with {len(served)} bytes "
              "that are not exactly the key; nothing submitted", file=sys.stderr)
        return 1
    print(f"KEY FILE OK: {KEY_URL}")
    status, _ = transport("POST", ENDPOINT, json.dumps(body).encode("utf-8"),
                          {"Content-Type": "application/json; charset=utf-8"})
    meaning = _STATUS_MEANING.get(status, "unexpected status")
    print(f"INDEXNOW HTTP {status}: {meaning}")
    return 0 if status in SUCCESS_STATUSES else 1


if __name__ == "__main__": raise SystemExit(run())
