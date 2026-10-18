"""Fixtures the backend test files share."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def on():
    """A client of an app with the flagged annual route switched on."""
    # Imported here, not at collection: a product module that refuses to load
    # then fails the tests that use it by name, not every backend file at once.
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import AppSettings

    with TestClient(create_app(AppSettings(enable_annual_route=True)),
                    raise_server_exceptions=False) as api:
        yield api


@pytest.fixture
def bundled_ephemeris() -> None:
    """Bind the product's own ephemeris files before the test.

    Per test: the ephemeris path is process-global Swiss state, and another
    file's test on the same xdist worker can leave it elsewhere, making Swiss
    fall back to Moshier (moves a sidereal comparison by ~1e-8 degrees)."""
    from app import ephemeris

    ephemeris.init_ephemeris()


@pytest.fixture
def relocation_offered(monkeypatch):
    """Casting the solar return at another place, switched on for one test.

    The shipped default refuses `solar_return_location`
    (schemas.SOLAR_RETURN_LOCATION_OFFERED); a test of the relocated path
    asks for this fixture by name so the switch it runs under is explicit.
    """
    from app import schemas

    monkeypatch.setattr(schemas, "SOLAR_RETURN_LOCATION_OFFERED", True)
