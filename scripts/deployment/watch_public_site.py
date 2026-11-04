#!/usr/bin/env python3
"""Watch the public site from outside the host.

Run from any machine but the host, on a schedule (launchd, cron or the Windows
task scheduler); it exits non-zero with one line per problem, which the
scheduler can forward to a phone.  It reads only public endpoints and sends
nothing about anyone.

* Certificate: the apex and www certificates must have at least
  `--certificate-days` days left.  An expired certificate behind HSTS is a hard
  outage.  Certbot renews with 30 days left, so a certificate under the floor
  means renewal has failed or stalled; the host needs no reporting channel.
* Domain: the registration's RDAP expiration date must be at least
  `--domain-days` days away.
* security.txt: its one `Expires` (RFC 9116) must be at least
  `--security-txt-days` days away.  The export sets it about seven months
  ahead and only a release renews it, so a long pause between releases lets
  it lapse unnoticed.
* Integrity: every page and asset under frontend/zh-TW/ at the live public
  source revision (`--revision`, read from GitHub, a channel the host does not
  control) must be served with exactly those bytes.  A page is served at its clean URL (`about.html` at
  `/zh-TW/about`, `index.html` at its directory); the 404 page is compared at
  a path that does not exist.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
import hashlib
from http.client import HTTPException
import json
import re
import socket
import ssl
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

CANONICAL_HOST = "projectarmillary.com"
PUBLIC_REPOSITORY = "sa3952/Armillary"
SERVED_PREFIX = "frontend/zh-TW/"
MISSING_PAGE_PROBE = "/zh-TW/no-such-page-integrity-probe"
USER_AGENT = "armillary-public-site-watch"

Fetch = Callable[[str], tuple[int, bytes]]


def fetch(url: str) -> tuple[int, bytes]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"})
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed https URLs only
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()
    except (OSError, HTTPException):
        # Status 0 is "no answer": every caller already reports a status it did not expect.
        return 0, b""


def served_path(name: str) -> str:
    relative = name.removeprefix("frontend")
    if relative.endswith("/index.html"): return relative[: -len("index.html")]
    if relative.endswith("/404.html"): return MISSING_PAGE_PROBE
    if relative.endswith(".html"): return relative[: -len(".html")]
    return relative


# The edge's static zone refills at 10 requests a second; a slower pace stays
# inside it rather than measuring the limiter.
LIVE_REQUEST_PAUSE_SECONDS = 0.15


def integrity_problems(revision: str, *, get: Fetch = fetch, base_url: str = f"https://{CANONICAL_HOST}",
                       pause: float = LIVE_REQUEST_PAUSE_SECONDS) -> list[str]:
    status, body = get(f"https://api.github.com/repos/{PUBLIC_REPOSITORY}/git/trees/{revision}?recursive=1")
    if status != 200: return [f"integrity: cannot read the public tree at {revision} (HTTP {status})"]
    try:
        tree = json.loads(body)
        if tree.get("truncated"): return [f"integrity: the public tree at {revision} is truncated"]
        names = sorted(entry["path"] for entry in tree["tree"]
                       if entry["type"] == "blob" and entry["path"].startswith(SERVED_PREFIX))
    except (ValueError, KeyError, TypeError, AttributeError):
        return [f"integrity: cannot parse the public tree at {revision}"]
    if not names: return [f"integrity: no file under {SERVED_PREFIX} at {revision}"]
    problems = []
    for name in names:
        source_status, source = get(f"https://raw.githubusercontent.com/{PUBLIC_REPOSITORY}/{revision}/{quote(name)}")
        if source_status != 200:
            problems.append(f"integrity: cannot read {name} at {revision} (HTTP {source_status})")
            continue
        path = served_path(name)
        time.sleep(pause)
        live_status, live = get(base_url + quote(path))
        expected_status = 404 if path == MISSING_PAGE_PROBE else 200
        if live_status != expected_status:
            problems.append(f"integrity: {path} answered HTTP {live_status}, expected {expected_status}")
        elif hashlib.sha256(live).digest() != hashlib.sha256(source).digest():
            problems.append(f"integrity: {path} is not the bytes of {name} at {revision}")
    return problems


def certificate_days_left(host: str, *, now: datetime) -> float:
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((host, 443), timeout=15) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            certificate = tls.getpeercert()
    not_after = certificate.get("notAfter") if certificate else None
    if not isinstance(not_after, str): raise ssl.SSLError(f"{host} presented no certificate expiry")
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
    return (expires - now).total_seconds() / 86400


def domain_expiration(domain: str, *, get: Fetch = fetch) -> datetime | None:
    status, body = get(f"https://rdap.org/domain/{domain}")
    if status != 200: return None
    try:
        for event in json.loads(body).get("events", []):
            if event.get("eventAction") == "expiration":
                expiration = datetime.fromisoformat(event["eventDate"].replace("Z", "+00:00"))
                return expiration if expiration.tzinfo is not None else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    return None


def release_revision(path: str) -> str:
    """The live frontend revision in a release record; raises ValueError when it cannot be used."""
    try:
        with open(path, encoding="utf-8") as record:
            revision = json.load(record)["live"]["frontend_public_source"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"release record {path}: cannot read live.frontend_public_source ({error!r})") from error
    return require_revision(revision, f"release record {path}")


def require_revision(revision: object, source: str) -> str:
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError(f"{source}: {revision!r} is not a 40-hex revision")
    return revision


def security_txt_problems(*, now: datetime, days: float, get: Fetch = fetch) -> list[str]:
    status, body = get(f"https://{CANONICAL_HOST}/.well-known/security.txt")
    if status != 200: return [f"security.txt: HTTP {status}"]
    values = [line.split(":", 1)[1].strip() for line in body.decode("utf-8", "replace").splitlines()
              if line.split(":", 1)[0].strip().casefold() == "expires" and ":" in line]
    if not values: return ["security.txt: no Expires field"]
    if len(values) > 1: return [f"security.txt: Expires appears {len(values)} times (RFC 9116 allows one)"]
    try:
        expires = datetime.fromisoformat(values[0].replace("Z", "+00:00"))
    except ValueError:
        expires = None
    if expires is None or expires.tzinfo is None or "T" not in values[0]:
        return [f"security.txt: Expires {values[0]!r} is not an RFC 3339 date-time"]
    left = (expires - now).total_seconds() / 86400
    if left <= 0: return [f"security.txt: Expires {expires.date()} has passed"]
    if left < days: return [f"security.txt: Expires {expires.date()} is {left:.0f} days away"]
    return []


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--certificate-days", type=float, default=21.0)
    parser.add_argument("--domain-days", type=float, default=45.0)
    parser.add_argument("--security-txt-days", type=float, default=60.0)
    integrity = parser.add_mutually_exclusive_group(required=True)
    integrity.add_argument("--revision", help="the live frontend's public source revision (40 hex)")
    integrity.add_argument("--release-record", help="read the revision from this current_release.json")
    integrity.add_argument("--skip-integrity", action="store_true")
    arguments = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    problems: list[str] = []
    revision = None
    try:
        if arguments.release_record:
            revision = release_revision(arguments.release_record)
        elif not arguments.skip_integrity:
            revision = require_revision(arguments.revision, "--revision")
    except ValueError as error:
        problems.append(f"integrity: {error}")
    for host in (CANONICAL_HOST, f"www.{CANONICAL_HOST}"):
        try:
            days = certificate_days_left(host, now=now)
        except (OSError, ssl.SSLError) as error:
            problems.append(f"certificate: {host}: {error}")
            continue
        if days < arguments.certificate_days:
            problems.append(f"certificate: {host} expires in {days:.1f} days; renewal has failed or stalled")
    expiration = domain_expiration(CANONICAL_HOST)
    if expiration is None:
        problems.append(f"domain: no RDAP expiration date for {CANONICAL_HOST}")
    elif (expiration - now).total_seconds() / 86400 < arguments.domain_days:
        problems.append(f"domain: {CANONICAL_HOST} registration expires {expiration.date()}")
    problems += security_txt_problems(now=now, days=arguments.security_txt_days)
    if revision is not None: problems += integrity_problems(revision)
    for problem in problems:
        print(problem)
    if not problems: print("PUBLIC SITE OK")
    return 1 if problems else 0


if __name__ == "__main__": raise SystemExit(main())
