"""The hosted application through TestClient: safety, refusals, pages, asset delivery."""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest
from app.frontend_assets import discover_source_assets
from app.main import create_app
from app.runtime_static import RuntimeStaticFiles
from app.settings import AppSettings, load_settings
from tests.backend import synthetic_birth_payload as _payload


BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
_FRONTEND_ROOT = BACKEND_ROOT.parent / "frontend"
_HEALTH = {"status": "ok", "ready": True, "readiness_scope": "process_liveness_only"}
_ZH_TW_PAGES = (
    "", "calculate", "features", "validation", "trust", "security", "roadmap", "blog",
    "about", "contact", "legal/privacy", "legal/terms", "legal/copyright",
)


def _client(**options) -> TestClient:
    return TestClient(create_app(AppSettings()), **options)


def test_settings_take_the_build_revision_fail_closed_and_ignore_the_retired_profile():
    # One posture: a stale CLASSICAL_ASTROLOGY_PROFILE changes nothing.
    assert not hasattr(AppSettings(), "profile")
    for stale in ("private_alpha", "public", "production"):
        assert load_settings({"CLASSICAL_ASTROLOGY_PROFILE": stale}) == load_settings({})
    variable = "CLASSICAL_ASTROLOGY_SOURCE_REVISION"
    settings = load_settings({variable: "b" * 40})
    assert settings.source_revision == "b" * 40
    assert settings.revision_source == f"build_environment:{variable}"
    for unset in (load_settings({}), load_settings({variable: "uncommitted"})):
        assert (unset.source_revision, unset.revision_source) == (None, None)
    with pytest.raises(RuntimeError, match="source revision"):
        load_settings({variable: "caller-controlled"})


def test_api_method_rejections_keep_allow_header_before_static_mount():
    with _client() as client:
        observed = {
            path: (response.status_code, response.headers.get("allow"))
            for path in ("/api/health", "/api/chart", "/api/places/search")
            for response in [client.request("TRACE", path)]
        }
    assert observed == {
        "/api/health": (405, "GET, HEAD"),
        "/api/chart": (405, "POST"),
        "/api/places/search": (405, "POST"),
    }


def test_hosted_safety_holds_without_indexing_headers():
    """Liveness-only health, no live schema, closed refusals that echo neither the
    validator message nor the input, no CORS grant, and no X-Robots-Tag anywhere
    (indexing is the edge's decision)."""

    payload = _payload()
    payload["datetime"]["month"] = 13
    payload["location"]["unexpected_CANARY_1997_24_1477"] = "HOSTED_SENSITIVE_CANARY"
    with _client() as client:
        health = client.get("/api/health")
        hidden = [client.get(path) for path in ("/api/runtime-health", "/openapi.json")]
        retired = client.get("/api/client-config")
        unsupported = client.post(
            "/api/chart", content=b"{}", headers={"Content-Type": "text/plain"}
        )
        invalid = client.post("/api/chart", json=payload)
        preflight = client.options("/api/chart", headers={
            "Origin": "https://untrusted.invalid", "Access-Control-Request-Method": "POST",
        })
        unindexed = [health, client.get("/"), client.get("/not-a-real-route")]

    assert (health.status_code, health.json()) == (200, _HEALTH)
    assert [response.status_code for response in hidden] == [404, 404]
    # /api/client-config only chose invitee wording; it is retired.
    assert retired.status_code == 404
    assert retired.json()["detail"]["code"] == "unknown_api_path"
    assert unsupported.status_code == 415
    assert invalid.status_code == 422
    assert all(
        set(issue) == {"type", "loc"} for issue in invalid.json()["detail"]["issues"]
    )
    assert "HOSTED_SENSITIVE_CANARY" not in invalid.text
    assert "unexpected_CANARY_1997_24_1477" not in invalid.text
    assert "access-control-allow-origin" not in preflight.headers
    for response in unindexed:
        assert "x-robots-tag" not in response.headers


def test_static_aliases_redirect_to_one_canonical_url_shape():
    """Pages live under explicit /zh-TW/ URLs so the shape does not drift when English
    is added; every alias redirects to one canonical URL and legacy routes are gone."""

    with _client(follow_redirects=False) as client:
        pages = {name: client.get(f"/zh-TW/{name}") for name in _ZH_TW_PAGES}
        redirects = {
            path: client.get(path)
            for path in ("/", "/zh-TW/index.html", "/zh-TW/features.html", "/zh-TW/features/")
        }
        legacy = [client.get(path) for path in ("/calculate", "/trust", "/legal/privacy")]

    for name, response in pages.items():
        assert response.status_code == 200, name
        assert 'lang="zh-TW"' in response.text, name
    assert {
        path: (response.status_code, response.headers.get("location"))
        for path, response in redirects.items()
    } == {
        "/": (308, "/zh-TW/"),
        "/zh-TW/index.html": (308, "/zh-TW/"),
        "/zh-TW/features.html": (308, "/zh-TW/features"),
        "/zh-TW/features/": (308, "/zh-TW/features"),
    }
    assert [response.status_code for response in legacy] == [404, 404, 404]
    runtime = RuntimeStaticFiles(
        directory=_FRONTEND_ROOT, html=True,
        allowed_assets=discover_source_assets(_FRONTEND_ROOT),
    )
    assert runtime._canonical_redirect({
        "method": "GET", "path": "//zh-TW//features", "query_string": b"",
    }) == "/zh-TW/features"


def test_public_discovery_assets_are_exact_runtime_files_not_source_metadata():
    with _client() as client:
        robots = client.get("/robots.txt")
        sitemap = client.get("/sitemap.xml")
        source_manifest = client.get("/surfaces.json")

    assert robots.status_code == 200
    assert robots.headers["content-type"].startswith("text/plain")
    assert robots.text.endswith("Sitemap: https://projectarmillary.com/sitemap.xml\n")
    assert sitemap.status_code == 200
    assert sitemap.headers["content-type"].split(";", 1)[0] in {"application/xml", "text/xml"}
    assert "https://projectarmillary.com/zh-TW/features" in sitemap.text
    assert "features.html" not in sitemap.text
    assert source_manifest.status_code == 404


def test_hosted_static_openapi_is_generated_offline_not_served():
    schema = json.loads(json.dumps(create_app(AppSettings()).openapi(), sort_keys=True))
    components = schema["components"]["schemas"]

    assert set(schema["paths"]) == {"/api/chart", "/api/health", "/api/places/search"}
    chart = schema["paths"]["/api/chart"]["post"]
    search = schema["paths"]["/api/places/search"]["post"]
    for endpoint in (chart, schema["paths"]["/api/health"]["get"], search):
        success = endpoint["responses"]["200"]
        assert success["content"]["application/json"]["schema"]["type"] == "object"
        assert success["description"] != "Successful Response"
    # One refusal envelope for every status; neither the validator message nor
    # the submitted input is part of an issue.
    issue = components["RefusalIssue"]
    assert set(issue["required"]) == {"loc", "type"}
    assert "msg" not in issue["properties"]
    assert "input" not in issue["properties"]
    for endpoint in (chart, search):
        for status in ("400", "413", "415", "422", "431", "503"):
            assert endpoint["responses"][status]["content"]["application/json"][
                "schema"
            ] == {"$ref": "#/components/schemas/RefusalResponse"}
    conditions = components["TimezoneInput"]["allOf"]
    for mode, required in (("iana", "iana_name"), ("fixed_offset", "utc_offset_hours")):
        assert any(
            item.get("if", {}).get("properties", {}).get("mode") == {"const": mode}
            and required in item.get("then", {}).get("required", [])
            for item in conditions
        )
    location = [item.get("if", {}) for item in components["LocationInput"]["allOf"]]
    assert any(
        rule.get("properties", {}).get("location_source", {}).get("const") == "geonames_cities500"
        for rule in location
    )
    assert any(rule.get("not") == {"required": ["location_source"]} for rule in location)


def test_hosted_chart_emits_status_only_allowlisted_event():
    """Events carry closed route labels and no request value."""

    events: list[dict] = []
    application = create_app(AppSettings(), event_emitter=lambda event: events.append(event) or True)
    with TestClient(application, follow_redirects=False) as client:
        response = client.post("/api/chart", json=_payload())
        health = client.get("/api/health")
        trailing_slash = client.post("/api/chart/", json=_payload())
        future_child = client.post("/api/chart/future", json=_payload())
        lookalike = client.get("/api/chartography")

    assert (response.status_code, health.status_code) == (200, 200)
    # The API boundary answers for its own prefix (404), not the asset mount (405).
    assert trailing_slash.json()["detail"]["code"] == "unknown_api_path"
    assert [r.status_code for r in (trailing_slash, future_child, lookalike)] == [404] * 3
    assert [event["route"] for event in events] == [
        "/api/chart", "/api/health", *["frontend_or_unmatched"] * 3,
    ]
    chart_event = events[0]
    assert (chart_event["status_code"], chart_event["outcome"]) == (200, "success")
    # request_id is a random uuid4 hex that can contain "1997" by chance, so it
    # is checked against its domain and every other field is scanned.
    assert re.fullmatch(r"[0-9a-f]{32}", chart_event["request_id"])
    encoded = json.dumps(
        {name: value for name, value in chart_event.items() if name != "request_id"},
        ensure_ascii=False,
    )
    location = _payload()["location"]
    for value in (str(location["latitude"]), str(location["longitude"]), "1997"):
        assert value not in encoded


@pytest.mark.parametrize(
    ("update", "reason_code", "location"),
    [
        ({"birth_time_precision": "approximate_hour"},
         "approximate_hour_requires_zero_subhour", ["body"]),
        ({"birth_time_precision": "date_only"}, "date_only_requires_zero_time", ["body"]),
        ({"computation_mode": {"center": "heliocentric"},
          "options": {"moon_position_profile": "moon_only_topocentric_v1"}},
         "moon_profile_center_conflict", ["body"]),
        ({"options": {"aspect_orb_profile": None, "aspect_orb_scale_percent": 80.0}},
         "aspect_orb_scale_requires_profile", ["body", "options"]),
    ],
)
def test_model_conflicts_expose_closed_actionable_reason_without_values(
    update, reason_code, location
):
    payload = _payload()
    payload.update(update)
    with _client() as client:
        response = client.post("/api/chart", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["issues"] == [{"type": reason_code, "loc": location}]


def test_numeric_fields_reject_boolean_and_string_coercion():
    offset = _payload()
    offset["timezone"] = {"mode": "fixed_offset", "utc_offset_hours": False}
    fold = _payload()
    fold["timezone"]["fold"] = False
    longitude = _payload()
    longitude["location"]["longitude"] = "120.0"
    with _client() as client:
        statuses = [
            client.post("/api/chart", json=payload).status_code
            for payload in (offset, fold, longitude)
        ]
    assert statuses == [422, 422, 422]


def test_ephemeris_refusal_returns_only_the_closed_error_code(monkeypatch):
    from app import main
    from app.ephemeris import FullEphemerisRequiredError
    from app.refusals import REFUSALS

    def fail(_request):
        raise FullEphemerisRequiredError(
            operation="CANARY_OPERATION",
            jd_ut=2597667.2296284684,
            retflag=4,
            # The request's own refusal; the server-fault reasons are 500.
            reason="segment_out_of_coverage",
        )

    monkeypatch.setattr(main, "_compute_chart_locked", fail)
    events = []
    hosted_app = main.create_app(
        AppSettings(), event_emitter=lambda event: events.append(event) or True,
    )
    with TestClient(hosted_app) as client:
        response = client.post("/api/chart", json=_payload())

    assert response.status_code == 422
    assert response.json() == {"detail": {
        "code": "full_ephemeris_required",
        "message": REFUSALS["full_ephemeris_required"].message,
    }}
    assert "2597667" not in response.text
    assert "CANARY_OPERATION" not in response.text
    assert events[-1]["error_code"] == "full_ephemeris_required"
    assert events[-1]["outcome"] == "error"


def test_hosted_boundary_rejects_oversized_headers_before_chart_parsing():
    with _client() as client:
        response = client.post(
            "/api/chart", json=_payload(), headers={"X-Oversized-Probe": "a" * (20 * 1024)},
        )
    assert response.status_code == 431, response.text
    assert response.json()["detail"]["code"] == "request_headers_too_large"


@pytest.mark.parametrize(("method", "path"), (
    ("GET", "/api/health"), ("HEAD", "/api/health"), ("GET", "/zh-TW/calculate"),
    ("GET", "/zh-TW/style/home.css"), ("GET", "/api/not-a-route"),
))
def test_header_budget_holds_on_every_path_not_only_the_json_posts(method, path):
    """SEC-R2-02: the 16 KiB header budget was applied to the two JSON POST
    routes only; a page or health request with 64 KB of headers was a 200,
    and the only bound left was the edge's."""
    with _client() as client:
        within = client.request(method, path, headers={"X-Probe": "a" * 1024})
        over = client.request(method, path, headers={"X-Probe": "a" * (17 * 1024)})
    assert within.status_code != 431
    assert over.status_code == 431, (path, over.status_code)
    if method != "HEAD":
        assert over.json()["detail"]["code"] == "request_headers_too_large"


def test_static_text_assets_are_gzip_encoded_when_the_client_accepts_it():
    """Gzip only for a client that lists it with non-zero quality; every
    representation names Accept-Encoding in Vary so a shared cache cannot mix them."""

    with _client() as client:
        for url, name in (
            ("/zh-TW/calculate", "zh-TW/calculate.html"),
            ("/zh-TW/style/home.css", "zh-TW/style/home.css"),
            ("/zh-TW/view-model.js", "zh-TW/view-model.js"),
            ("/zh-TW/favicon.svg", "zh-TW/favicon.svg"),
        ):
            original = (_FRONTEND_ROOT / name).read_bytes()
            encoded = client.get(url, headers={"Accept-Encoding": "gzip"})
            identity = client.get(url, headers={"Accept-Encoding": "identity"})
            refused = client.get(url, headers={"Accept-Encoding": "gzip;q=0"})

            assert encoded.status_code == 200, url
            assert encoded.headers.get("content-encoding") == "gzip", url
            assert int(encoded.headers["content-length"]) < len(original), url
            assert encoded.content == original, url
            for response in (identity, refused):
                assert response.status_code == 200, url
                assert "content-encoding" not in response.headers, url
                assert response.content == original, url
            for response in (encoded, identity, refused):
                assert "accept-encoding" in response.headers["vary"].lower(), url
            # Two representations cannot share one strong validator.
            assert encoded.headers["etag"] != identity.headers["etag"], url


def test_gzip_representation_keeps_head_validators_and_range_semantics():
    gzip_only = {"Accept-Encoding": "gzip"}
    with _client() as client:
        encoded = client.get("/zh-TW/style/home.css", headers=gzip_only)
        head = client.head("/zh-TW/style/home.css", headers=gzip_only)
        revalidated = client.get(
            "/zh-TW/style/home.css", headers={**gzip_only, "If-None-Match": encoded.headers["etag"]},
        )
        ranged = client.get("/zh-TW/style/home.css", headers={**gzip_only, "Range": "bytes=0-9"})

    assert head.status_code == 200
    for header in ("content-encoding", "content-length", "etag"):
        assert head.headers[header] == encoded.headers[header], header
    assert head.headers["content-encoding"] == "gzip"
    assert head.content == b""
    assert revalidated.status_code == 304
    assert revalidated.headers["etag"] == encoded.headers["etag"]
    assert "accept-encoding" in revalidated.headers["vary"].lower()
    # A byte range addresses the identity bytes; it is never cut from gzip.
    assert ranged.status_code == 206
    assert "content-encoding" not in ranged.headers
    assert ranged.content == (_FRONTEND_ROOT / "zh-TW/style/home.css").read_bytes()[:10]


def test_api_json_other_than_the_chart_result_is_never_compressed():
    """Place search echoes the submitted terms and refusals are small: none is encoded,
    and no blanket compression middleware exists that could reach them."""

    application = create_app(AppSettings())
    assert not any(
        "gzip" in getattr(middleware.cls, "__name__", "").casefold()
        for middleware in application.user_middleware
    )
    gzip_only = {"Accept-Encoding": "gzip"}
    with TestClient(application) as client:
        observations = {
            "places": client.post("/api/places/search", json={"query": "Tainan"}, headers=gzip_only),
            "health": client.get("/api/health", headers=gzip_only),
            "rejected": client.post("/api/chart", json={"unexpected": True}, headers=gzip_only),
        }

    assert observations["rejected"].status_code == 422
    for name, response in observations.items():
        assert "content-encoding" not in response.headers, name
        assert "accept-encoding" not in response.headers.get("vary", "").lower(), name
        assert response.headers["cache-control"] == "no-store", name


@pytest.mark.parametrize(("accept_encoding", "expected"), (
    ("gzip", True), ("GZIP", True), ("gzip;q=1", True), ("gzip; q=1.000", True),
    ("gzip;q=0.001", True), ("br, gzip;q=0.5", True),
    ("gzip;q=0", False), ("gzip;q=0.000", False), ("*", False), ("identity", False),
    # SEC-R2-06: RFC 9110 §12.4.2 qvalues are 0–1 with at most three decimals;
    # anything else is not a quality, and `float` read `inf` as a preference.
    ("gzip;q=inf", False), ("gzip;q=nan", False), ("gzip;q=1e0", False),
    ("gzip;q=1_0", False), ("gzip;q=2", False), ("gzip;q=-1", False),
    ("gzip;q=1.0001", False), ("gzip;q=", False),
))
def test_gzip_is_chosen_only_for_a_valid_nonzero_qvalue(accept_encoding, expected):
    from starlette.datastructures import Headers

    from app.runtime_static import accepts_gzip

    assert accepts_gzip(Headers({"accept-encoding": accept_encoding})) is expected


def test_chart_result_is_gzip_encoded_only_for_clients_that_name_gzip():
    """Decoding gives exactly the identity bytes, encoding is deterministic, and both
    representations carry the same Vary, Cache-Control and security headers."""

    def raw(client: TestClient, accept_encoding: str) -> tuple[int, dict, bytes]:
        with client.stream(
            "POST", "/api/chart", json=_payload(), headers={"Accept-Encoding": accept_encoding}
        ) as response:
            return response.status_code, dict(response.headers), b"".join(response.iter_raw())

    with _client() as client:
        status, identity_headers, identity = raw(client, "identity")
        refused_status, refused_headers, refused = raw(client, "gzip;q=0")
        encoded_status, encoded_headers, encoded = raw(client, "gzip, deflate, br")
        again_status, _, again = raw(client, "gzip")

    assert status == refused_status == encoded_status == again_status == 200
    for headers, body in ((identity_headers, identity), (refused_headers, refused)):
        assert "content-encoding" not in headers
        assert body == identity
    assert encoded_headers["content-encoding"] == "gzip"
    assert int(encoded_headers["content-length"]) == len(encoded) < len(identity) // 3
    assert gzip.decompress(encoded) == identity
    assert again == encoded, "one request body, one encoded byte sequence"
    for headers in (identity_headers, refused_headers, encoded_headers):
        assert "accept-encoding" in headers["vary"].lower()
        assert headers["cache-control"] == "no-store"
    representation = {"content-encoding", "content-length", "x-request-id"}
    assert {
        name: value for name, value in encoded_headers.items() if name not in representation
    } == {
        name: value for name, value in identity_headers.items() if name not in representation
    }


def test_generated_pages_version_every_asset_by_its_served_content_digest():
    """Every `?v=` in every generated page is the first sixteen hex digits of the
    SHA-256 of the file served at that path, and that URL earns the immutable lifetime."""

    # data-* carries a module a page loads later (calculate.js's view-model).
    reference = re.compile(r'(?:src|href|data-[a-z]+(?:-[a-z]+)*)="/(zh-TW/[^"?#]+)(\?[^"#]*)?"')
    pages = sorted((_FRONTEND_ROOT / "zh-TW").rglob("*.html"))
    assert len(pages) >= 14
    versioned: dict[tuple[str, str], str] = {}
    for page in pages:
        for match in reference.finditer(page.read_text(encoding="utf-8")):
            name, query = match.group(1), match.group(2)
            if Path(name).suffix not in {".css", ".js", ".mjs", ".svg"}:
                continue
            label = f"{page.relative_to(_FRONTEND_ROOT)} -> {name}"
            assert query, f"{label}: static asset reference lacks a version key"
            expected = hashlib.sha256((_FRONTEND_ROOT / name).read_bytes()).hexdigest()[:16]
            assert query == f"?v={expected}", label
            versioned[(name, query)] = label
    assert any(name == "zh-TW/calculate.js" for name, _ in versioned)
    assert any(name == "zh-TW/favicon.svg" for name, _ in versioned)
    assert any(name == "zh-TW/view-model.js" for name, _ in versioned)

    with _client() as client:
        for (name, query), label in sorted(versioned.items()):
            response = client.get(f"/{name}{query}")
            assert response.status_code == 200, label
            assert response.headers["cache-control"] == "public, max-age=31536000, immutable", label


def test_content_version_follows_the_bytes_not_the_process_start(tmp_path):
    """A source checkout can change under a running process; the token must follow."""

    frontend = tmp_path / "frontend"
    (frontend / "zh-TW").mkdir(parents=True)
    (frontend / "zh-TW/index.html").write_text("<!doctype html>", encoding="utf-8")
    asset = frontend / "zh-TW/page.css"
    asset.write_bytes(b"body{color:red}")
    runtime = RuntimeStaticFiles(
        directory=frontend, html=True, allowed_assets=discover_source_assets(frontend),
    )
    assert runtime.content_version("/zh-TW/page.css") == (
        hashlib.sha256(b"body{color:red}").hexdigest()[:16]
    )
    asset.write_bytes(b"body{color:blue;margin:0}")
    assert runtime.content_version("/zh-TW/page.css") == (
        hashlib.sha256(b"body{color:blue;margin:0}").hexdigest()[:16]
    )
    for outside in ("/zh-TW/missing.css", "/zh-TW/../frontend/zh-TW/page.css",
                    "zh-TW/page.css", "/zh-TW/page", "/api/chart"):
        assert runtime.content_version(outside) is None, outside


def test_importing_the_application_module_builds_no_application():
    """Arch I-01: the image runs `uvicorn --factory app.main:create_app`, which
    imports app.main and then calls the factory; a module-level `app =
    create_app()` built a second, unused application in every worker.  The module
    builds `app` only when something reads it (`uvicorn app.main:app`, tests)."""
    import subprocess
    import sys

    probe = (
        "import app.main as m\n"
        "assert 'app' not in vars(m), 'importing app.main built an application'\n"
        "from app.main import app\n"
        "from fastapi import FastAPI\n"
        "assert isinstance(app, FastAPI) and m.app is app\n"
    )
    completed = subprocess.run([sys.executable, "-c", probe], cwd=BACKEND_ROOT,
                               capture_output=True, text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr[-2000:]
