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

    # The loopback client address the in-container health check uses, so the
    # readiness route answers here too.
    with TestClient(create_app(AppSettings(enable_annual_route=True)),
                    client=("127.0.0.1", 50000), raise_server_exceptions=False) as api:
        yield api


@pytest.fixture(scope="module")
def quiet_client():
    """A client of the default app that prints no privacy event, answers a
    server error with its 500 instead of raising it, and follows no redirect
    (no API path redirects, so that changes no API answer)."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.settings import AppSettings

    with TestClient(create_app(AppSettings(), event_emitter=lambda event: True),
                    raise_server_exceptions=False, follow_redirects=False) as api:
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
def copied_ephemeris(tmp_path, monkeypatch, request):
    """A byte copy of the bundled ephemeris directory, bound as the ephemeris
    directory; the real directory and the manifest cache are bound again
    afterwards.  Parametrized indirectly with {"link": True} the copy is
    symbolic links, and {"leave_out": (name, ...)} leaves those files out."""
    import shutil
    from pathlib import Path

    import swisseph as swe

    from app import ephemeris

    options = getattr(request, "param", {})
    real_directory = ephemeris.EPHE_DIR
    for path in sorted(Path(real_directory).iterdir()):
        if path.is_file() and path.name not in options.get("leave_out", ()):
            if options.get("link"):
                (tmp_path / path.name).symlink_to(path)
            else:
                shutil.copy2(path, tmp_path / path.name)
    swe.close()
    monkeypatch.setattr(ephemeris, "EPHE_DIR", str(tmp_path))
    yield tmp_path
    swe.close()
    swe.set_ephe_path(real_directory)
    monkeypatch.setattr(ephemeris, "_MANIFEST_CACHE", None)


@pytest.fixture
def relocation_offered(monkeypatch):
    """Casting the solar return at another place, switched on for one test.

    The shipped default refuses `solar_return_location`
    (schemas.SOLAR_RETURN_LOCATION_OFFERED); a test of the relocated path
    asks for this fixture by name so the switch it runs under is explicit.
    """
    from app import schemas

    monkeypatch.setattr(schemas, "SOLAR_RETURN_LOCATION_OFFERED", True)
