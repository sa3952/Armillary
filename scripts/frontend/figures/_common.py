"""Shared pieces of the article figure generators."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sys
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "backend"
SIGNS = "牡羊 金牛 雙子 巨蟹 獅子 處女 天秤 天蠍 射手 摩羯 水瓶 雙魚".split()


@contextmanager
def backend_on_path() -> Iterator[None]:
    """backend/ is importable only while a generator reads the product."""
    sys.path.insert(0, str(BACKEND))
    try:
        yield
    finally:
        sys.path.remove(str(BACKEND))


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


def spoken_longitude(lon: float) -> str:
    """「處女座 24 度 47 分」: whole minutes, rounded."""
    total = round(lon * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]}座 {rest // 60} 度 {rest % 60} 分"


def indent(block: str, prefix: str = "    ") -> str:
    """A whole SVG placed inside a <figure>: every line indented once."""
    return "\n".join(prefix + line for line in block.splitlines())


@contextmanager
def product_charts() -> Iterator[Any]:
    """`post(payload, expected=200)` against the real application in process,
    the full (`detailed`) response, as the chart fixtures read it."""
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        def post(payload: dict, expected: int = 200) -> dict:
            response = client.post("/api/chart?projection=detailed", json=payload)
            if response.status_code != expected:
                raise RuntimeError(f"chart request answered {response.status_code}: {response.text[:300]}")
            return response.json()

        yield post


def zh(value: int) -> str:
    """A count in Chinese numerals, as the pages write it (「十一」)."""
    from scripts.frontend.build_pages import zh_count

    return zh_count(value)


def zh_quantity(value: int) -> str:
    """The same before a measure word, where two is 「兩」(「兩套」)."""
    return "兩" if value == 2 else zh(value)
