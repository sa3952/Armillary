"""Dependency-light fixtures shared by private and exported backend tests."""

from __future__ import annotations

import copy
import json
import socket
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def minimal_chart_payload(
    *,
    year: int = 2000,
    month: int = 1,
    day: int = 1,
    hour: int = 12,
    minute: int = 0,
    latitude: float = 25.033,
    longitude: float = 121.5654,
    altitude_m: float = 10,
    timezone: dict | None = None,
) -> dict:
    return {
        "datetime": {
            "year": year, "month": month, "day": day,
            "hour": hour, "minute": minute, "second": 0,
        },
        "timezone": timezone or {
            "mode": "iana", "iana_name": "Asia/Taipei", "fold": 0,
        },
        "location": {
            "latitude": latitude, "longitude": longitude,
            "altitude_m": altitude_m,
        },
    }


# Provenance.  The person-shaped tuple below (1997-08-17 09:42 Asia/Taipei,
# 22.9908 N 120.2133 E, 80 m) is a synthetic test fixture written by an earlier AI
# coding session; it was not taken from any person's record.  Its coordinates are
# the bundled catalog's Tainan representative point (GeoNames 1668355) rounded to
# four decimals; they replaced an earlier hand-written point on 2026-10-06,
# so no public test names that place.
# The project's record lists it as synthetic with no known person linkage
# and notes that the generation method (random or hand-picked) is not known.  Any
# complete birth tuple can coincide with an unknown real person, so this note claims
# only "synthetic / no known person linkage", never that a match is impossible.
# Exported tests take the tuple from here so the note lives beside every use.
SYNTHETIC_BIRTH_FIXTURE: dict[str, Any] = {
    "year": 1997, "month": 8, "day": 17, "hour": 9, "minute": 42,
    "latitude": 22.9908, "longitude": 120.2133, "altitude_m": 80,
}


def synthetic_birth_payload() -> dict:
    """Minimal chart request for the synthetic fixture documented above."""

    return minimal_chart_payload(**SYNTHETIC_BIRTH_FIXTURE)


def chart_payload(
    *,
    precision: str = "exact",
    atmosphere: dict | None = None,
    mode: dict | None = None,
    options: dict | None = None,
    **values,
) -> dict:
    payload = minimal_chart_payload(**{
        key: values.pop(key)
        for key in tuple(values)
        if key in {
            "year", "month", "day", "hour", "minute", "latitude",
            "longitude", "altitude_m", "timezone",
        }
    })
    payload.update({
        "birth_time_precision": precision,
        "options": {"house_system": "W", **(options or {}), **values},
    })
    if atmosphere is not None:
        payload["atmosphere"] = atmosphere
    if mode is not None:
        payload["computation_mode"] = mode
    return payload


CHART_REQUESTS_PATH = (
    Path(__file__).resolve().parents[2] / "frontend/tests/fixtures/chart-requests.json"
)


def chart_requests() -> dict[str, dict]:
    """The frontend fixture requests, plus two requests derived from them.

    ``exact-all-modules`` is the every-module request at an exact minute;
    ``sidereal-dignity-refused`` asks for essential dignities in the sidereal
    zodiac, which the backend refuses.  Every value is a fresh copy.
    """

    requests = json.loads(CHART_REQUESTS_PATH.read_text(encoding="utf-8"))
    every_module = requests["chart-approximate-hour.json"]
    requests["exact-all-modules"] = {
        **every_module,
        "birth_time_precision": "exact",
        "datetime": {**every_module["datetime"], "minute": 30},
    }
    requests["sidereal-dignity-refused"] = {
        **requests["chart-exact.json"],
        "computation_mode": {"ayanamsa": "fagan_bradley", "zodiac": "sidereal"},
        "options": {"include_domicile_exaltation": True},
    }
    return copy.deepcopy(requests)


def unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_request(
    url: str,
    body: bytes | None = None,
    *,
    content_type: str | None = None,
    timeout: float = 20,
) -> tuple[int, bytes]:
    media_type = content_type or ("application/json" if body is not None else None)
    headers = {"Content-Type": media_type} if media_type else {}
    try:
        with urlopen(Request(url, data=body, headers=headers), timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def list_every_pair(pair: dict) -> bool:
    """An aspect listing rule that lists every evaluated pair.

    The product lists by `pair_is_listed`; tests pass this as `pair_filter` to
    see the pairs that rule leaves out.
    """

    return True


def find_crossings(separation_at, **kwargs) -> list[float]:
    """Root times only, from `find_crossings_detailed`."""

    from app.core.root_finding import find_crossings_detailed

    return [record["t"] for record in find_crossings_detailed(separation_at, **kwargs)]


@contextmanager
def compute_queue_held() -> Iterator[None]:
    """Hold the Swiss compute line, as a running calculation does."""

    import asyncio

    from app import main

    assert asyncio.run(main._COMPUTE_QUEUE.acquire(timeout=0)), "compute line already held"
    try:
        yield
    finally:
        main._COMPUTE_QUEUE.release()
