"""Dependency-light fixtures shared by private and exported backend tests."""

from __future__ import annotations

import copy
import json
import math
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Iterator, cast
from urllib.error import HTTPError, URLError
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
# 22.9908 N 120.2133 E, 80 m) is a synthetic test fixture; it was not taken from
# any person's record.  Its coordinates are the bundled catalog's Tainan
# representative point (GeoNames 1668355) rounded to four decimals.  They replaced
# an earlier hand-written point on 2026-10-06 so that no public test carries that
# point.
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


def neutral_chart_payload(*, timezone: dict | None = None) -> dict:
    """`chart_payload` with every computation-mode field and the atmosphere
    stated, and the optional modules named off.  The Falses are sent, not left
    to the defaults: each one makes its option state's `input_presence`
    "explicit" instead of "defaulted"."""

    return chart_payload(
        timezone=timezone,
        atmosphere={"pressure_hpa": None, "temperature_c": 0.0},
        mode={
            "center": "geocentric", "zodiac": "tropical", "ayanamsa": "fagan_bradley",
            "position_mode": "apparent", "ecliptic_frame": "of_date", "nutation": True,
        },
        options={name: False for name in (
            "include_fixed_stars", "include_lots", "include_antiscia",
            "include_void_of_course", "include_declination_aspects",
            "include_outer_planets", "include_lunar_phases", "include_eclipses",
            "include_rise_set_transits",
        )},
    )


# A request's clock read as UTC.  Each use gets its own dict: a test may edit
# the payload it is part of.
def fixed_utc() -> dict:
    return {"mode": "fixed_offset", "utc_offset_hours": 0.0}


def utc_instant(label: str) -> datetime:
    """A response's `...Z` time as an aware datetime."""

    return datetime.fromisoformat(label.replace("Z", "+00:00"))


def sign_index(longitude: float) -> int:
    """0 for Aries through 11 for Pisces."""

    return math.floor(longitude % 360 / 30)


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name: str) -> Any:
    """A JSON file of tests/backend/fixtures, parsed."""

    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHART_REQUESTS_PATH = REPOSITORY_ROOT / "frontend/tests/fixtures/chart-requests.json"


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


def require_frontend_packages(*names: str) -> None:
    """Skip, with the reason, when the frontend package directory lacks a package a test
    runs under node; where every layer must run that skip is a failure."""
    import pytest

    missing = [name for name in names
               if not (REPOSITORY_ROOT / "frontend" / ("node" + "_modules") / name / "package.json").is_file()]
    if missing:
        pytest.skip(f"the frontend package directory has no {', '.join(missing)} (run npm ci --ignore-scripts in frontend/)")


def node_json(script: str, payload: Any = None, *, cwd: Path = REPOSITORY_ROOT) -> Any:
    """Run `node -e script` with `payload` as JSON on stdin; parse what it writes."""

    completed = subprocess.run(
        ["node", "-e", script], cwd=cwd, check=True, capture_output=True, text=True,
        input=None if payload is None else json.dumps(payload, ensure_ascii=False),
    )
    return json.loads(completed.stdout)


JsonPath = tuple[str | int, ...]


def expect_fields(mapping: dict, **expected: Any) -> None:
    """Assert several fields of one record at once (the others are not compared)."""

    assert {key: mapping[key] for key in expected} == expected


def walk_json(node: Any, sequences: tuple[type, ...] = (list,), _path: JsonPath = ()) -> Iterator[tuple[JsonPath, Any, Any]]:
    """(path, key, value) for `node` itself and every value under it, parents
    before children: `path` is the dict keys and sequence indexes from `node`
    to the value, `key` its last step (None for `node` itself).  Dicts and
    `sequences` are descended; everything else is a leaf."""

    yield _path, (_path[-1] if _path else None), node
    if isinstance(node, dict):
        items: Iterable[tuple[Any, Any]] = node.items()
    elif isinstance(node, sequences):
        items = enumerate(cast(Iterable[Any], node))
    else:
        return
    for key, value in items:
        yield from walk_json(value, sequences, (*_path, key))


def json_strings(node: Any) -> list[str]:
    """Every dictionary key and string value in a decoded JSON value."""

    return [text for _path, key, value in walk_json(node)
            for text in ((key,) if isinstance(key, str) else ()) + ((value,) if isinstance(value, str) else ())]


def json_dicts(node: Any, sequences: tuple[type, ...] = (list,)) -> list[dict]:
    """`node` and every dict under it, parents before children."""

    return [value for _path, _key, value in walk_json(node, sequences) if isinstance(value, dict)]


def json_path(path: JsonPath, root: str = "$") -> str:
    """`root.key[0].key` for a `walk_json` path."""

    return root + "".join(f"[{step}]" if isinstance(step, int) else f".{step}" for step in path)


def response_keys(node: Any) -> Iterator[str]:
    """Every dictionary key anywhere in a decoded JSON value."""

    return (key for _path, key, _value in walk_json(node) if isinstance(key, str))


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


def list_every_pair(_pair: dict) -> bool:
    """A `pair_filter` that lists every pair `pair_is_listed` would leave out too."""
    return True


def aspect_participant(key, longitude, *, speed=1.0, category="classical_planet", body_id=None) -> dict:
    """One participant as the aspect module receives it."""

    return {"key": key, "name": key, "longitude": longitude,
            "speed_longitude": speed, "body_id": body_id, "category": category}


def aspect_pair(receipt: dict, key_a: str, key_b: str) -> dict:
    for record in receipt["pairs"]:
        if {record["body_a"], record["body_b"]} == {key_a, key_b}:
            return record
    raise AssertionError(f"pair {key_a}/{key_b} not found")


def aspect_target(record: dict, key: str) -> dict:
    for target in record["aspect_targets"]:
        if target["key"] == key:
            return target
    raise AssertionError(f"target {key} not found")


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


@contextmanager
def real_uvicorn_probe(label: str, *setup: str, command: list[str] | None = None):
    """A real uvicorn server on a free port; `probe.output` holds its log after exit."""

    port = unused_local_port()
    if command is None:
        script = "\n".join((
            "import uvicorn",
            *setup,
            f"uvicorn.run(main.app, host='127.0.0.1', port={port}, access_log=False, http='h11')",
        ))
        command = [sys.executable, "-c", script]
    else:
        command = [*command, "--port", str(port)]
    process = subprocess.Popen(
        command, cwd=REPOSITORY_ROOT / "backend",
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    probe = SimpleNamespace(base_url=f"http://127.0.0.1:{port}", output="")
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"{label} server stopped early:\n" + (process.stdout.read() if process.stdout else ""))
            try:
                if http_request(probe.base_url + "/api/health")[0] == 200:
                    break
            except URLError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError(f"{label} server startup timed out")
        yield probe
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        probe.output = process.stdout.read() if process.stdout else ""
