"""Shared pieces of the article figure generators."""
from __future__ import annotations

from contextlib import contextmanager
import functools
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Callable, Iterator


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
SIGNS = "牡羊 金牛 雙子 巨蟹 獅子 處女 天秤 天蠍 射手 摩羯 水瓶 雙魚".split()
PLANETS = {"sun": "太陽", "moon": "月亮", "mercury": "水星", "venus": "金星", "mars": "火星", "jupiter": "木星",
           "saturn": "土星"}
# The synthetic place every Taipei demonstration uses (latitude, longitude).
TAIPEI = (25.05306, 121.52639)


@contextmanager
def backend_on_path() -> Iterator[None]:
    """backend/ is importable only while a generator reads the product."""
    sys.path.insert(0, str(BACKEND))
    try:
        yield
    finally:
        sys.path.remove(str(BACKEND))


def node_json(script: str | Path, *args: object, stdin: object = None, timeout: int = 30,
              what: str, cwd: Path = ROOT) -> Any:
    """The JSON a Node script prints last: `script` is a file to run or, as a
    string, a program for `node -e`; `stdin`, when given, is sent as JSON.
    `what` completes "node is required to …" and "could not …"."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError(f"node is required to {what}")
    program = [str(script)] if isinstance(script, Path) else ["-e", script]
    completed = subprocess.run(
        [node, *program, *map(str, args)], input=None if stdin is None else json.dumps(stdin),
        cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"could not {what}: " + completed.stderr.strip())
    return json.loads(completed.stdout.strip().splitlines()[-1])


@functools.lru_cache(maxsize=1)
def options_catalogue() -> dict[str, list[str]]:
    """The calculator's options catalogue: each option's group, in order, and
    the keys of the groups the advanced panel shows."""
    return node_json(
        "const C=require(process.argv[1]);process.stdout.write(JSON.stringify({"
        "options:C.OPTIONS.map((o)=>o.group),advanced:C.GROUPS.filter((g)=>g.in_advanced).map((g)=>g.key)}));",
        ROOT / "frontend/zh-TW/options-catalogue.js", what="read the options catalogue")


@contextmanager
def swiss() -> Iterator[Any]:
    """Swiss Ephemeris bound to the repository's own ephemeris files.

    Binding and release go through the product's per-thread bookkeeping, so a
    test that runs a generator does not leave a later chart in the same thread
    believing the path is still bound after Swiss was closed.
    """
    with backend_on_path():
        import swisseph as swe
        from app import ephemeris

        ephemeris.release_ephemeris_for_thread()
        ephemeris.ensure_ephemeris_initialized_for_thread()
        try:
            yield swe
        finally:
            ephemeris.release_ephemeris_for_thread()


def calc_ut(swe, jd: float, body: int, flags: int | None = None) -> tuple:
    """swe.calc_ut that refuses a silent fall back to the Moshier model."""
    if flags is None:
        position, used = swe.calc_ut(jd, body)
    else:
        position, used = swe.calc_ut(jd, body, flags)
    if not used & swe.FLG_SWIEPH:
        raise RuntimeError(f"Swiss did not read the ephemeris files for body {body} at JD {jd}")
    return position


def sign_degree_minute(lon: float) -> tuple[str, int, int]:
    """(sign, degree, minute) of an ecliptic longitude, rounded to the whole arcminute."""
    sign, rest = divmod(round(lon * 60), 30 * 60)
    return SIGNS[sign % 12], rest // 60, rest % 60


def degree_minute(degrees: float) -> str:
    """「116°03′」: whole arcminutes, rounded."""
    units = round(degrees * 60)
    return f"{units // 60}°{units % 60:02d}′"


def spoken_longitude(lon: float) -> str:
    """「處女座 24 度 47 分」: whole minutes, rounded."""
    sign, degree, minute = sign_degree_minute(lon)
    return f"{sign}座 {degree} 度 {minute} 分"


def hms(clock: tuple[int, int, int]) -> str:
    """「14:05:09」."""
    return f"{clock[0]:02d}:{clock[1]:02d}:{clock[2]:02d}"


def indent(block: str, prefix: str = "    ") -> str:
    """A whole SVG placed inside a <figure>: every line indented once."""
    return "\n".join(prefix + line for line in block.splitlines())


@functools.lru_cache(maxsize=2)
def _quiet_app(annual: bool) -> Any:
    # The figures post hundreds of charts; their privacy events would bury the
    # build's own output, so this application's event sink drops them.
    from app.main import create_app
    from app.settings import AppSettings

    return create_app(AppSettings(enable_annual_route=True) if annual else None, event_emitter=lambda _event: True)


@contextmanager
def product_client(annual: bool = False) -> Iterator[Callable[..., Any]]:
    """`post(path, payload, expected=200)` against the real application in
    process (with the annual route enabled when `annual`): the JSON answer,
    refused unless the status is `expected`."""
    with backend_on_path():
        from fastapi.testclient import TestClient

        client = TestClient(_quiet_app(annual))

        def post(path: str, payload: dict, expected: int = 200) -> Any:
            response = client.post(path, json=payload)
            if response.status_code != expected:
                raise RuntimeError(f"{path} answered {response.status_code}: {response.text[:300]}")
            return response.json()

        yield post


@contextmanager
def product_charts() -> Iterator[Callable[..., dict]]:
    """`post(payload, expected=200)`: the full (`detailed`) chart response, as
    the chart fixtures read it."""
    with product_client() as post:
        yield lambda payload, expected=200: post("/api/chart?projection=detailed", payload, expected)


def zh(value: int) -> str:
    """A count in Chinese numerals, as the pages write it (「十一」)."""
    from scripts.frontend.build_pages import zh_count

    return zh_count(value)


def zh_quantity(value: int) -> str:
    """The same before a measure word, where two is 「兩」(「兩套」)."""
    return "兩" if value == 2 else zh(value)
