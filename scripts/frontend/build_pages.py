#!/usr/bin/env python3
"""Generate frontend pages from fragments at commit time.

The project chose "generate at commit time and commit the output" over both a
hand-written set and a build chain: the served files stay readable source, so
AGPL §13's Corresponding Source obligation is discharged by View Source, while
the surfaces (times languages, once more than one is served) do not each carry their own
copy of the head, header and footer.  How many surfaces there are is whatever
frontend/surfaces.json lists; it is not restated here.

The generated files are committed. `--check` re-runs the generation in memory
and fails if any committed file differs, which is what keeps the output from
drifting away from the fragments.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import html
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import textwrap
from xml.sax.saxutils import escape as xml_escape


ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "scripts" / "frontend" / "pages"
SHELL = PAGES / "_shell.html"
SURFACE_MANIFEST = ROOT / "frontend" / "surfaces.json"
# The served tree whose user-visible pages must each have a surface row.
FRONTEND = ROOT / "frontend"
# When each indexable page last changed, for the sitemap's <lastmod>.  This
# generator is its only writer: a page's date moves to the build date only when
# the page's content digest changes, so `--check` stays deterministic and a
# rebuild that changes nothing does not advance any date (search engines ignore
# a lastmod that moves on every build).  It lives beside the producer, not in
# frontend/, so it is never a served asset.
PAGE_LASTMOD = ROOT / "scripts" / "frontend" / "page_lastmod.json"
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A content digest ignores `?v=` stamps: a stylesheet edit re-stamps every page
# but changes no page's content, and must not advance every <lastmod>.
_ASSET_STAMP = re.compile(r"\?v=[0-9a-f]{16}")

SITE_NAME = "渾儀 Armillary"
# The application declares that it is free to use and the
# license it is published under.  The publication manifest's
# `license_expression` (AGPL-3.0-only) is the authority; this is its SPDX page,
# which names the -only variant exactly.  A test binds the two, since the public
# source tree does not carry the publication manifest.
LICENSE_URL = "https://spdx.org/licenses/AGPL-3.0-only.html"
# The day the invitation wall came down
# and Public Alpha began.  This is the one producer of that date: the terms and
# privacy head notes and the about page name it as {{public_alpha_start}}, and
# the last day of the Private Alpha 1.0.0 terms as {{private_alpha_last_day}}
# (the day before).  If the wall comes down after midnight, change this value
# and rebuild; a test refuses any other date written next to the public start,
# and Gate F (verify_pre_image_readiness) refuses the release that opens Public
# Alpha unless the date its pages state is the Taiwan calendar day of that run.
PUBLIC_ALPHA_START = date(2026, 10, 10)
_PUBLIC_ALPHA_PLACEHOLDER = re.compile(r"\{\{(public_alpha_start|private_alpha_last_day)\}\}")


def public_alpha_dates(start: date | None = None) -> dict[str, str]:
    start = PUBLIC_ALPHA_START if start is None else start
    return {
        "public_alpha_start": start.isoformat(),
        "private_alpha_last_day": (start - timedelta(days=1)).isoformat(),
    }


def fill_public_alpha_dates(body: str, start: date | None = None) -> str:
    dates = public_alpha_dates(start)
    return _PUBLIC_ALPHA_PLACEHOLDER.sub(lambda match: dates[match.group(1)], body)


# The copyright page's attribution of the Taiwan place names states the day the
# data was retrieved.  The shipped catalogue's manifest is the one producer of
# that day (the catalogue builder writes it from --source-date), so a rebuilt
# catalogue moves the attribution with it.
PLACE_CATALOG_MANIFEST = ROOT / "backend" / "place_data" / "catalog_manifest.json"
_PLACE_DATE_PLACEHOLDER = "{{place_source_snapshot_date}}"


def place_source_snapshot_date(manifest: Path | None = None) -> str:
    value = json.loads((manifest or PLACE_CATALOG_MANIFEST).read_text(encoding="utf-8"))[
        "source_snapshot_date"
    ]
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(f"place catalogue manifest source_snapshot_date is not a date: {value!r}")
    date.fromisoformat(value)
    return value


def fill_place_source_snapshot_date(body: str) -> str:
    if _PLACE_DATE_PLACEHOLDER not in body:
        return body
    return body.replace(_PLACE_DATE_PLACEHOLDER, place_source_snapshot_date())


# The copyright page lists the shipped ephemeris files and their SHA-256 so a
# reader can compare them with the source tree.  deploy/ephemeris.sha256 (which
# the image build and the entrypoint verify against) is the one statement of
# them: the fragment writes {{ephemeris_digests}} on a line of its own and
# {{ephemeris_file_count}} in the sentence above it.
EPHEMERIS_MANIFEST = ROOT / "deploy" / "ephemeris.sha256"
_EPHEMERIS_DIGESTS_PLACEHOLDER = re.compile(r"^(?P<indent>[ \t]*)\{\{ephemeris_digests\}\}$", re.MULTILINE)
_SHA256_LINE = re.compile(r"^([0-9a-f]{64})  backend/ephe/([A-Za-z0-9_.-]+)$")


def ephemeris_digests(manifest: Path | None = None) -> list[tuple[str, str]]:
    rows = []
    for line in (manifest or EPHEMERIS_MANIFEST).read_text(encoding="utf-8").splitlines():
        match = _SHA256_LINE.fullmatch(line)
        if match is None:
            raise ValueError(f"unexpected line in deploy/ephemeris.sha256: {line!r}")
        rows.append((match.group(2), match.group(1)))
    if not rows or len({name for name, _ in rows}) != len(rows):
        raise ValueError("deploy/ephemeris.sha256 lists no file or a file twice")
    return rows


def fill_ephemeris_digests(body: str) -> str:
    if "{{ephemeris_" not in body:
        return body
    rows = ephemeris_digests()
    filled, count = _EPHEMERIS_DIGESTS_PLACEHOLDER.subn(
        lambda match: "\n".join(
            f'{match.group("indent")}<div><b class="mono">{html.escape(name)}</b>'
            f'<span class="mono">{digest}</span></div>'
            for name, digest in rows
        ),
        body,
    )
    filled = filled.replace("{{ephemeris_file_count}}", zh_count(len(rows)))
    if count != 1 or "{{ephemeris_" in filled:
        raise ValueError("{{ephemeris_digests}} must appear once, on a line of its own")
    return filled


# The features page states how many advanced options there are and in how many
# groups.  The calculator's options catalogue is the one producer of both: the
# page names them as {{advanced_option_count}} and {{advanced_group_count}}, and
# they are read from the catalogue the page ships, so the sentence cannot drift
# from the form.
OPTIONS_CATALOGUE = ROOT / "frontend/zh-TW/options-catalogue.js"
_OPTIONS_PLACEHOLDER = re.compile(r"\{\{(advanced_option_count|advanced_group_count)\}\}")
_ZH_DIGITS = "零一二三四五六七八九"
_CATALOGUE_COUNTS_SCRIPT = (
    "const C=require(process.argv[1]);"
    "const groups=new Set(C.GROUPS.filter((g)=>g.in_advanced).map((g)=>g.key));"
    "process.stdout.write(JSON.stringify({"
    "options:C.OPTIONS.filter((o)=>groups.has(o.group)).length,"
    "groups:groups.size}));"
)


def zh_count(value: int) -> str:
    """A count from 1 to 99 in Chinese numerals, as the pages write group counts."""

    if not 0 < value < 100:
        raise ValueError(f"count out of range for a Chinese numeral: {value}")
    tens, ones = divmod(value, 10)
    if tens == 0:
        return _ZH_DIGITS[ones]
    return ("" if tens == 1 else _ZH_DIGITS[tens]) + "十" + (_ZH_DIGITS[ones] if ones else "")


def options_catalogue_counts(node: str | None = None) -> dict[str, str]:
    node = node or shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to read the options catalogue")
    completed = subprocess.run(
        [node, "-e", _CATALOGUE_COUNTS_SCRIPT, str(OPTIONS_CATALOGUE)],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError("options catalogue could not be read: " + completed.stderr.strip())
    counts = json.loads(completed.stdout)
    return {
        "advanced_option_count": str(counts["options"]),
        "advanced_group_count": zh_count(counts["groups"]),
    }


def fill_options_catalogue_counts(body: str) -> str:
    if not _OPTIONS_PLACEHOLDER.search(body):
        return body
    counts = options_catalogue_counts()
    return _OPTIONS_PLACEHOLDER.sub(lambda match: counts[match.group(1)], body)


# The home page's armillary plate is gen_armillary's projection, injected where
# the fragment writes {{armillary_svg}} on a line of its own and indented to
# match, so the drawing served is the geometry the currentness test checks.
_ARMILLARY_PLACEHOLDER = re.compile(r"^(?P<indent>[ \t]*)\{\{armillary_svg\}\}$", re.MULTILINE)


@lru_cache(maxsize=1)
def armillary_svg() -> str:
    from scripts.frontend import gen_armillary

    return gen_armillary.build(gen_armillary.HOUR_ANGLE, gen_armillary.AZIM, gen_armillary.ELEV)[0]


def fill_armillary_svg(body: str) -> str:
    if "{{armillary_svg}}" not in body:
        return body
    filled, count = _ARMILLARY_PLACEHOLDER.subn(
        lambda match: textwrap.indent(armillary_svg(), match.group("indent")), body
    )
    if count != 1 or "{{armillary_svg}}" in filled:
        raise ValueError("{{armillary_svg}} must appear once, on a line of its own")
    return filled


# Every backend route lives under this prefix; robots.txt keeps crawlers out of
# it while every page stays crawlable.  A test binds it to the routes the
# application actually mounts.
API_PATH_PREFIX = "/api/"

# og:image.  This one constant is the switch: None puts
# no image in any head and keeps the plain summary card; an asset name puts that
# PNG in every page's og:image.  Its
# source and its render record are scripts/frontend/og_card.py, and `--check`
# fails when the committed PNG is not the render of that source.  The URL is
# absolute and carries the asset's content version, so a new card is a new URL
# and every platform cache refetches; the width and height are read from the
# PNG itself, never declared beside it.
OG_IMAGE_ASSET: str | None = "zh-TW/og-card.png"
# Alt text proposed with the wiring.
OG_IMAGE_ALT = "渾儀 Armillary：可驗證的古典西洋占星計算器"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# llms.txt: a plain index of the pages for language-model crawlers,
# built from what the site already says.  The sections are the shared footer's
# columns, each entry is a surface's title and description, and the optional
# links take their label from the anchor text the named page already shows.
# Nothing here is new prose; a link that disappears from its page fails the build.
LLMS_OPTIONAL_LINKS = (
    ("methods", "/zh-TW/method-sources.json"),
    ("legal-copyright", "https://github.com/sa3952/Armillary"),
)

# Every `?v=` is the content version of the exact file it names: the
# first sixteen hex digits of its SHA-256, from the one definition in
# backend/app/frontend_assets.py that the public cache policy also uses to
# decide whether a request earns the immutable lifetime.  A hand-bumped
# release constant used to stand in for it, so an asset could change while its
# URL did not.  Editing a referenced asset without re-running this generator is
# now page drift that `--check` reports.
_VERSIONED_ASSET_REFERENCE = re.compile(
    r'(?P<prefix>(?:src|href)="/(?P<name>zh-TW/[^"?#]+)\?v=)\{\{assets\}\}"'
)


def _backend(module: str):
    """``app.<module>`` from backend/, which is on the path only for the import."""

    backend = str(ROOT / "backend")
    inserted = backend not in sys.path
    if inserted:
        sys.path.insert(0, backend)
    try:
        return importlib.import_module(f"app.{module}")
    finally:
        if inserted:
            sys.path.remove(backend)


def _frontend_assets_module():
    return _backend("frontend_assets")


def referenced_asset_version(name: str, frontend: Path | None = None) -> str:
    assets = _frontend_assets_module()
    path = (FRONTEND if frontend is None else frontend) / assets.validate_asset_name(name)
    if not path.is_file():
        raise ValueError(f"versioned frontend asset is missing: {name}")
    return assets.asset_content_version(path.read_bytes())


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Width and height from a PNG's IHDR chunk, which must come first."""

    if len(data) < 24 or data[:8] != _PNG_SIGNATURE or data[12:16] != b"IHDR":
        raise ValueError("og:image must be a PNG file")
    width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if not width or not height:
        raise ValueError("og:image PNG has no size")
    return width, height


def og_image_markup(
    origin: str,
    asset: str | None = None,
    alt: str | None = None,
    frontend: Path | None = None,
) -> tuple[str, str]:
    """The og:image meta lines and the twitter:card value.

    With no asset the head carries no image and the card is the plain summary.
    With one, every page names the same card by its absolute, content-versioned
    URL, with its type, its measured size and its alt text.
    """

    asset = OG_IMAGE_ASSET if asset is None else asset
    if asset is None:
        return "", "summary"
    alt = OG_IMAGE_ALT if alt is None else alt
    if not alt.strip():
        raise ValueError("og:image needs alt text")
    frontend = FRONTEND if frontend is None else frontend
    name = _frontend_assets_module().validate_asset_name(asset)
    path = frontend / name
    if not path.is_file():
        raise ValueError(f"og:image asset is missing: {asset}")
    width, height = png_dimensions(path.read_bytes())
    url = f"{origin}/{name}?v={referenced_asset_version(name, frontend)}"
    lines = (
        f'<meta property="og:image" content="{html.escape(url, quote=True)}">',
        '<meta property="og:image:type" content="image/png">',
        f'<meta property="og:image:width" content="{width}">',
        f'<meta property="og:image:height" content="{height}">',
        f'<meta property="og:image:alt" content="{html.escape(alt, quote=True)}">',
    )
    return "".join(line + "\n" for line in lines), "summary_large_image"


def stamp_asset_versions(markup: str, key: str) -> str:
    """Replace each `/zh-TW/<asset>?v={{assets}}` with that asset's version."""

    stamped = _VERSIONED_ASSET_REFERENCE.sub(
        lambda match: (
            f'{match.group("prefix")}{referenced_asset_version(match.group("name"))}"'
        ),
        markup,
    )
    if "{{assets}}" in stamped:
        raise ValueError(f"unversionable {{{{assets}}}} placeholder in page {key!r}")
    return stamped

# The served CSP carries no `style-src 'unsafe-inline'`, so an inline
# `style=` attribute is silently dropped by the browser while source/output
# parity stays green.  Match the attribute position
# (a tag, then whitespace, then the attribute) rather than the bare word, so
# prose that mentions `style=` is not an offence.
_INLINE_STYLE_ATTRIBUTE = re.compile(
    r"<[A-Za-z][^<>]*?\s(style\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))",
    re.IGNORECASE | re.DOTALL,
)


def inline_style_attributes(markup: str) -> list[str]:
    """Every inline `style=` attribute in the markup, verbatim."""

    return [match.group(1) for match in _INLINE_STYLE_ATTRIBUTE.finditer(markup)]


def reject_inline_style(markup: str, key: str) -> None:
    offenders = inline_style_attributes(markup)
    if offenders:
        raise ValueError(
            f"inline style attribute in generated page {key!r} is blocked by the "
            f"served CSP: {', '.join(offenders)}"
        )

_TELEMETRY_FIELD_EXPLANATIONS = {
    "event_schema_version": "固定字串",
    "event": "固定字串",
    "request_id": "伺服器產生的32字元十六進位字串",
    "route": "固定分類，不是原始網址",
    "method": "GET／POST／HEAD／OPTIONS／OTHER",
    # A client that leaves before any response is recorded with 0.
    "status_code": "0（沒有送出回應：用戶端在回應之前已中斷連線）或 100–599",
    "duration_bucket": "固定分組，不記精確耗時",
    "request_size_bucket": "固定區間，不記內容",
    "outcome": "success／rejected／error／unknown",
}


def telemetry_contract_rows(
    contract: dict[str, tuple[str, ...]] | None = None,
) -> str:
    """Render membership from the executable event owner, never a copied list."""

    if contract is None:
        contract = telemetry_contract()
    fields = contract.get("fields")
    error_codes = contract.get("error_codes")
    failure_classes = contract.get("failure_classes")
    if not fields or not error_codes or not failure_classes:
        raise ValueError("public telemetry contract is incomplete")
    descriptions = {
        **_TELEMETRY_FIELD_EXPLANATIONS,
        "error_code": "空值，或：" + "、".join(error_codes),
        "failure_class": "空值，或：" + "、".join(failure_classes),
    }
    return "\n".join(
        "          <tr><td class=\"mono\">"
        + html.escape(field)
        + "</td><td>"
        + html.escape(descriptions.get(field, "封閉事件欄位"))
        + "</td></tr>"
        for field in fields
    )


# Chinese labels for the public description of each event field.  The
# membership and the count come from the executable owner; only the wording
# lives here.  A field without a label fails the build instead of rendering
# a placeholder, so a new backend field cannot be described by silence.
_TELEMETRY_FIELD_LABELS = {
    "event_schema_version": "事件版本",
    "event": "事件名",
    "request_id": "請求 ID",
    "route": "路由",
    "method": "方法",
    "status_code": "狀態碼",
    "duration_bucket": "耗時分桶",
    "request_size_bucket": "大小分桶",
    "outcome": "結果",
    "error_code": "錯誤碼",
    "failure_class": "失敗類別",
}


def telemetry_contract() -> dict[str, tuple[str, ...]]:
    privacy_logging = _backend("privacy_logging")
    contract = dict(privacy_logging.public_event_contract())
    # Declaration order, for prose; the sorted tuple stays for the table.
    contract["fields_in_order"] = tuple(privacy_logging.ALLOWED_EVENT_FIELDS)
    return contract


def telemetry_field_count(contract: dict[str, tuple[str, ...]] | None = None) -> str:
    fields = (contract or telemetry_contract())["fields"]
    return str(len(fields))


def telemetry_field_list(contract: dict[str, tuple[str, ...]] | None = None) -> str:
    """The public field names in declaration order, as one 、-joined phrase."""

    contract = contract or telemetry_contract()
    fields = contract.get("fields_in_order") or contract["fields"]
    missing = [field for field in fields if field not in _TELEMETRY_FIELD_LABELS]
    if missing:
        raise ValueError(f"telemetry field has no public label: {missing}")
    return "、".join(html.escape(_TELEMETRY_FIELD_LABELS[field]) for field in fields)


_FRAGMENT_NAME = re.compile(r"[a-z0-9_-]+")


def _common_row_fields_valid(item: dict) -> bool:
    # Surface and error page rows alike: the fragment names a file under pages/, never a path,
    # and a bad one is refused under its own name.
    if not (isinstance(item["fragment"], str) and _FRAGMENT_NAME.fullmatch(item["fragment"])):
        raise ValueError(f"frontend page fragment is invalid: {item.get('key')}")
    return (
        item["locale"] == "zh-TW"
        and isinstance(item["layers"], list)
        and bool(item["layers"])
        and set(item["layers"]) <= {"L1", "L2", "L3"}
        and isinstance(item["title"], str)
        and bool(item["title"].strip())
    )


def load_surface_manifest() -> dict:
    payload = json.loads(SURFACE_MANIFEST.read_text(encoding="utf-8"))
    if set(payload) != {
        "schema_version", "origin", "default_locale", "surfaces", "error_pages",
    } or payload["schema_version"] != 1:
        raise ValueError("frontend surface manifest root is invalid")
    if payload["origin"] != "https://projectarmillary.com":
        raise ValueError("frontend canonical origin is invalid")
    if payload["default_locale"] != "zh-TW":
        raise ValueError("frontend locale is invalid")
    expected_fields = {
        "key", "fragment", "output", "surface", "locale", "layers",
        "indexable", "title", "description",
    }
    seen: dict[str, set[str]] = {name: set() for name in ("key", "output", "surface")}
    for item in payload["surfaces"]:
        if not isinstance(item, dict) or set(item) != expected_fields:
            raise ValueError("frontend surface row field set is invalid")
        if (
            not _common_row_fields_valid(item)
            or not isinstance(item["indexable"], bool)
            or not isinstance(item["description"], str)
            or not item["description"].strip()
            or not item["surface"].startswith("/zh-TW/")
            or not item["output"].startswith("zh-TW/")
            or ".." in Path(item["output"]).parts
        ):
            raise ValueError(f"frontend surface row is invalid: {item.get('key')}")
        for field in seen:
            value = item[field]
            if not isinstance(value, str) or value in seen[field]:
                raise ValueError(f"frontend surface {field} is invalid or duplicated")
            seen[field].add(value)
    if seen["surface"] != {item["surface"] for item in payload["surfaces"]}:
        raise ValueError("frontend surface set is invalid")
    if {"/zh-TW/", "/zh-TW/calculate"} - seen["surface"]:
        raise ValueError("frontend entry surfaces are missing")
    _validate_error_pages(payload, seen)
    return payload


# The error pages a release carries, by the status each one answers with, and
# the served name the static mount looks for (backend/app/frontend_assets.py).
# An error page is not a surface: it has no address, no canonical URL, no
# sitemap entry and no structured data, and it is never indexed.
def error_page_outputs() -> dict[int, str]:
    return {404: _frontend_assets_module().NOT_FOUND_PAGE}


def _validate_error_pages(payload: dict, seen: dict[str, set[str]]) -> None:
    rows = payload["error_pages"]
    expected_fields = {"key", "fragment", "output", "status", "locale", "layers", "title"}
    outputs = error_page_outputs()
    if not isinstance(rows, list):
        raise ValueError("frontend error page list is invalid")
    statuses: set[int] = set()
    for item in rows:
        if not isinstance(item, dict) or set(item) != expected_fields:
            raise ValueError("frontend error page row field set is invalid")
        if (
            not _common_row_fields_valid(item)
            or item["status"] not in outputs
            or item["status"] in statuses
            or item["output"] != outputs[item["status"]]
            or item["key"] in seen["key"]
            or item["output"] in seen["output"]
        ):
            raise ValueError(f"frontend error page row is invalid: {item.get('key')}")
        statuses.add(item["status"])
        seen["key"].add(item["key"])
        seen["output"].add(item["output"])
    if statuses != set(outputs):
        raise ValueError("frontend error page set is incomplete")


def unclassified_pages(payload: dict, frontend: Path) -> list[str]:
    """HTML pages under ``frontend`` that no surface row classifies.

    Every user-visible surface carries an L1／L2／L3 assignment and
    an unclassified surface is itself a violation.  frontend/surfaces.json is
    the only place that assignment lives; this is its consumer in the
    other direction, so a page added beside the manifest cannot ship
    unclassified.  The excluded top-level directories are the ones the served
    asset universe excludes (backend/app/frontend_assets.py).
    """

    excluded = _frontend_assets_module().EXCLUDED_SOURCE_DIRECTORIES
    registered = {
        item["output"] for item in [*payload["surfaces"], *payload["error_pages"]]
    }
    pages: set[str] = set()
    for entry in frontend.iterdir():
        if entry.name in excluded or entry.is_symlink():
            continue
        candidates = [entry] if entry.is_file() else entry.rglob("*")
        for path in candidates:
            if path.is_file() and path.suffix.casefold() == ".html":
                pages.add(path.relative_to(frontend).as_posix())
    return sorted(pages - registered)


_FOOTER_LINK = re.compile(r'<a href="(?P<href>/zh-TW/[^"]*)">(?P<label>[^<>]+)</a>')
HOME_SURFACE = "/zh-TW/"


def _footer(shell: str | None) -> str:
    shell = SHELL.read_text(encoding="utf-8") if shell is None else shell
    start, end = shell.find("<footer>"), shell.find("</footer>")
    if start < 0 or end < start:
        raise ValueError("page shell has no footer")
    return shell[start:end]


def footer_link_labels(shell: str | None = None) -> dict[str, str]:
    """Each surface's label in the shared footer, which every page carries.

    The footer is the site map a crawler follows without running any script,
    and its labels are the visible names of the pages; the breadcrumb trail in
    the structured data reuses them rather than a second list of names.
    """

    labels: dict[str, str] = {}
    for match in _FOOTER_LINK.finditer(_footer(shell)):
        labels.setdefault(match.group("href"), html.unescape(match.group("label")).strip())
    return labels


def require_footer_links(payload: dict, labels: dict[str, str] | None = None) -> None:
    """Every surface is reachable through a plain link on every page."""

    labels = footer_link_labels() if labels is None else labels
    unlinked = [item["surface"] for item in payload["surfaces"] if item["surface"] not in labels]
    if unlinked:
        raise ValueError(
            "surface is not linked from the shared footer: " + ", ".join(unlinked)
        )


def _json_ld(item: dict, origin: str) -> str:
    canonical = origin + item["surface"]
    labels = footer_link_labels()
    graph: list[dict] = [
        {
            "@type": "WebSite",
            "@id": origin + "/#website",
            "url": origin + "/",
            "name": SITE_NAME,
            "inLanguage": item["locale"],
        },
        {
            "@type": "WebPage",
            "@id": canonical + "#webpage",
            "url": canonical,
            "name": item["title"],
            "description": item["description"],
            "inLanguage": item["locale"],
            "isPartOf": {"@id": origin + "/#website"},
        },
    ]
    if item["surface"] == HOME_SURFACE:
        # No `creator` (no person is named in the structured data), no
        # Organization; free to use, and the license it is published under.
        graph.append({
            "@type": "WebApplication",
            "@id": origin + "/#application",
            "url": canonical,
            "name": SITE_NAME,
            "alternateName": "Armillary",
            "description": item["description"],
            "applicationCategory": "ReferenceApplication",
            "operatingSystem": "Web",
            "inLanguage": item["locale"],
            "isAccessibleForFree": True,
            "license": LICENSE_URL,
        })
        graph[1]["about"] = {"@id": origin + "/#application"}
    else:
        if item["surface"] not in labels or HOME_SURFACE not in labels:
            raise ValueError(f"surface has no footer label: {item['surface']}")
        graph.append({
            "@type": "BreadcrumbList",
            "@id": canonical + "#breadcrumb",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": labels[HOME_SURFACE],
                    "item": origin + HOME_SURFACE,
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": labels[item["surface"]],
                    "item": canonical,
                },
            ],
        })
        graph[1]["breadcrumb"] = {"@id": canonical + "#breadcrumb"}
    return json.dumps(
        {"@context": "https://schema.org", "@graph": graph},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")


def metadata_values(item: dict, origin: str) -> dict[str, str]:
    canonical = origin + item["surface"]
    return {
        "robots": "index, follow" if item["indexable"] else "noindex, follow",
        "locale": html.escape(item["locale"], quote=True),
        "og_locale": html.escape(item["locale"].replace("-", "_"), quote=True),
        "site_name": html.escape(SITE_NAME, quote=True),
        "title": html.escape(item["title"], quote=True),
        "description": html.escape(item["description"], quote=True),
        "canonical": html.escape(canonical, quote=True),
        "surface": html.escape(
            f"{item['surface']} · {' ＋ '.join(item['layers'])}", quote=True
        ),
        "json_ld": _json_ld(item, origin),
    }


_DISCOVERY_SECTION = re.compile(r"\{\{#discovery\}\}\n(?P<body>.*?)\{\{/discovery\}\}\n", re.DOTALL)


def _shell_with_discovery(shell: str, keep: bool) -> str:
    """Keep the head's discovery block (description, canonical, hreflang, Open
    Graph, card, structured data) for a surface; drop it for an error page,
    which has no address of its own to describe."""

    if len(_DISCOVERY_SECTION.findall(shell)) != 1:
        raise ValueError("page shell must have exactly one discovery section")
    return _DISCOVERY_SECTION.sub(
        (lambda match: match.group("body")) if keep else "", shell
    )


_NAV_CTA = re.compile(r'<a class="nav-cta" href="(?P<href>[^"]+)">')


def _mark_nav_cta(shell: str, surface: str) -> str:
    """The page the navigation's call to action leads to marks it
    aria-current="page"; page.css styles that state as "you are here"."""

    if len(_NAV_CTA.findall(shell)) != 1:
        raise ValueError("page shell must have exactly one navigation call to action")
    return _NAV_CTA.sub(
        lambda match: match.group(0)[:-1] + ' aria-current="page">'
        if match.group("href") == surface
        else match.group(0),
        shell,
    )


# Comments are for whoever edits the templates; the served pages carry none.
# A comment alone on its line takes the line with it.
_HTML_COMMENT_LINE = re.compile(r"^[ \t]*<!--(?:(?!-->).)*-->[ \t]*\n", re.MULTILINE | re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--(?:(?!-->).)*-->", re.DOTALL)


def strip_html_comments(template: str) -> str:
    return _HTML_COMMENT.sub("", _HTML_COMMENT_LINE.sub("", template))


def _template(path: Path) -> str:
    return strip_html_comments(path.read_text(encoding="utf-8"))


def render(item: dict, origin: str) -> str:
    name = item["fragment"]
    shell = _mark_nav_cta(_template(SHELL), item["surface"])
    body = _template(PAGES / f"{name}.html").rstrip("\n")
    if "{{telemetry_" in body:
        contract = telemetry_contract()
        body = (
            body.replace("{{telemetry_contract_rows}}", telemetry_contract_rows(contract))
            .replace("{{telemetry_field_count}}", telemetry_field_count(contract))
            .replace("{{telemetry_field_list}}", telemetry_field_list(contract))
        )
    if "{{telemetry_" in body:
        raise ValueError(f"unknown telemetry placeholder in fragment {name!r}")
    body = fill_public_alpha_dates(body)
    body = fill_place_source_snapshot_date(body)
    body = fill_ephemeris_digests(body)
    body = fill_options_catalogue_counts(body)
    body = fill_armillary_svg(body)
    reject_inline_style(body, item["key"])
    metadata = metadata_values(item, origin)
    og_image, twitter_card = og_image_markup(origin)
    stylesheets = [
        '<link rel="stylesheet" href="/zh-TW/page.css?v={{assets}}">'
    ]
    if item["key"] == "calculate":
        stylesheets.append(
            '<link rel="stylesheet" href="/zh-TW/calculate.css?v={{assets}}">'
        )
    # {{body}} 先插入，{{assets}} 後蓋上內容版本，順序不可調換：頁面片段自己
    # 也需要版本鍵。/zh-TW/ 的敏感度示範腳本只屬於該頁，放進 _shell.html 會讓
    # 另外十一頁載入一個對它們無用的檔案；留在片段裡，就必須讓片段也能寫
    # ?v={{assets}}。每個靜態資產引用都帶正確的內容版本，由
    # tests/integration/test_hosted_profile.py 逐頁檢查。
    return stamp_asset_versions(
        _shell_with_discovery(shell, keep=True)
        .replace("{{og_image}}", og_image)
        .replace("{{twitter_card}}", twitter_card)
        .replace("{{robots}}", metadata["robots"])
        .replace("{{locale}}", metadata["locale"])
        .replace("{{og_locale}}", metadata["og_locale"])
        .replace("{{site_name}}", metadata["site_name"])
        .replace("{{title}}", metadata["title"])
        .replace("{{description}}", metadata["description"])
        .replace("{{canonical}}", metadata["canonical"])
        .replace("{{json_ld}}", metadata["json_ld"])
        .replace("{{surface}}", metadata["surface"])
        .replace("{{stylesheets}}", "\n".join(stylesheets))
        .replace("{{body}}", body),
        item["key"],
    )


def render_error_page(item: dict) -> str:
    """An error page: the shared header and footer, which link home and to
    every surface, around the page's own fragment, under `noindex`."""

    shell = _shell_with_discovery(_template(SHELL), keep=False)
    body = _template(PAGES / f"{item['fragment']}.html").rstrip("\n")
    reject_inline_style(body, item["key"])
    rendered = (
        shell.replace("{{robots}}", "noindex")
        .replace("{{locale}}", html.escape(item["locale"], quote=True))
        .replace("{{title}}", html.escape(item["title"], quote=True))
        .replace("{{surface}}", html.escape(
            f"{item['status']} · {' ＋ '.join(item['layers'])}", quote=True
        ))
        .replace("{{stylesheets}}", '<link rel="stylesheet" href="/zh-TW/page.css?v={{assets}}">')
        .replace("{{body}}", body)
    )
    leftover = re.findall(r"\{\{(?!assets\}\})[^{}]*\}\}", rendered)
    if leftover:
        raise ValueError(f"unfilled placeholder in error page {item['key']!r}: {leftover}")
    return stamp_asset_versions(rendered, item["key"])


def robots_text(payload: dict) -> str:
    """The crawl posture: every page may be fetched, the API may not.

    Whether a page is indexed is the page's own `<meta name="robots">`, read
    off the surface's `indexable` field.  A surface that is not indexable is
    deliberately NOT disallowed here: a crawler that may not fetch a page never
    sees its noindex, and an outside link can still list the bare URL (the blog's
    Disallow-plus-noindex conflict was resolved that way).  The
    publication verifier compares the served file against this function.
    """

    origin = payload["origin"]
    return "\n".join([
        "User-agent: *",
        f"Disallow: {API_PATH_PREFIX}",
        "Allow: /",
        "",
        f"Sitemap: {origin}/sitemap.xml",
        "",
    ])


def page_digest(page: str) -> str:
    return hashlib.sha256(_ASSET_STAMP.sub("?v=", page).encode("utf-8")).hexdigest()


def load_page_lastmod(path: Path | None = None) -> dict:
    path = PAGE_LASTMOD if path is None else path
    if not path.is_file():
        return {"schema_version": 1, "pages": {}}
    record = json.loads(path.read_text(encoding="utf-8"))
    pages = record.get("pages") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or set(record) != {"schema_version", "pages"}
        or record["schema_version"] != 1
        or not isinstance(pages, dict)
        or any(
            not isinstance(entry, dict)
            or set(entry) != {"content_sha256", "lastmod"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(entry["content_sha256"]))
            or not _ISO_DATE.fullmatch(str(entry["lastmod"]))
            for entry in pages.values()
        )
    ):
        raise ValueError("page lastmod record is invalid")
    return record


def updated_page_lastmod(previous: dict, digests: dict[str, str], build_date: str) -> dict:
    """Carry each unchanged page's date forward; date a changed page today."""

    if not _ISO_DATE.fullmatch(build_date):
        raise ValueError("build date must be YYYY-MM-DD")
    pages: dict[str, dict[str, str]] = {}
    for key, digest in digests.items():
        entry = previous["pages"].get(key)
        if entry is not None and entry["content_sha256"] == digest:
            pages[key] = dict(entry)
        else:
            pages[key] = {"content_sha256": digest, "lastmod": build_date}
    return {"schema_version": 1, "pages": pages}


def page_lastmod_text(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_date(environment: Mapping[str, str] | None = None) -> str:
    """Today in UTC, or SOURCE_DATE_EPOCH's date for a reproducible build."""

    epoch = (os.environ if environment is None else environment).get("SOURCE_DATE_EPOCH")
    moment = (
        datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        if epoch
        else datetime.now(timezone.utc)
    )
    return moment.date().isoformat()


def sitemap_text(payload: dict, lastmod: dict) -> str:
    origin = payload["origin"]
    entries = []
    for item in payload["surfaces"]:
        if not item["indexable"]:
            continue
        url = xml_escape(origin + item["surface"])
        date = lastmod["pages"][item["key"]]["lastmod"]
        entries.append(f"  <url><loc>{url}</loc><lastmod>{date}</lastmod></url>")
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        *entries,
        "</urlset>",
        "",
    ])


_FOOTER_COLUMN = re.compile(
    r'<div class="sitemap-col">\s*<h2>(?P<heading>[^<>]+)</h2>(?P<links>.*?)</div>',
    re.DOTALL,
)


def footer_columns(shell: str | None = None) -> list[tuple[str, list[str]]]:
    """The shared footer's columns: each heading and the surfaces it links, in order."""

    return [
        (
            html.unescape(match.group("heading")).strip(),
            [link.group("href") for link in _FOOTER_LINK.finditer(match.group("links"))],
        )
        for match in _FOOTER_COLUMN.finditer(_footer(shell))
    ]


def _anchor_label(fragment: str, href: str) -> str:
    """The visible text of the one link to `href` on a page fragment."""

    body = (PAGES / f"{fragment}.html").read_text(encoding="utf-8")
    labels = [
        html.unescape(re.sub(r"<[^<>]+>", "", match.group(1))).strip()
        for match in re.finditer(
            r'<a href="' + re.escape(href) + r'"[^<>]*>(.*?)</a>', body, re.DOTALL
        )
    ]
    if not labels or not labels[0]:
        raise ValueError(f"page {fragment!r} has no link to {href}")
    return labels[0]


def _markdown_text(value: str) -> str:
    """One line of llms.txt prose: no line breaks, no link syntax characters."""

    return re.sub(r"\s+", " ", value).replace("[", "［").replace("]", "］").strip()


def llms_text(payload: dict, shell: str | None = None) -> str:
    """/llms.txt (llmstxt.org): the site's name, its summary and its pages.

    Every word is already on the site: the name, the entry page's description
    as the summary, the footer's column headings as sections, each surface's
    title and description, and the optional links' own anchor text.  A surface
    the footer does not group fails the build rather than going unlisted.
    """

    origin = payload["origin"]
    by_surface = {item["surface"]: item for item in payload["surfaces"]}
    home = by_surface[HOME_SURFACE]
    lines = [f"# {SITE_NAME}", "", f"> {_markdown_text(home['description'])}", ""]
    listed: set[str] = set()
    for heading, surfaces in footer_columns(shell):
        entries = [by_surface[surface] for surface in surfaces if surface in by_surface]
        if not entries:
            continue
        lines += [f"## {_markdown_text(heading)}", ""]
        for item in entries:
            if item["surface"] in listed or not item["indexable"]:
                continue
            listed.add(item["surface"])
            lines.append(
                f"- [{_markdown_text(item['title'])}]({origin}{item['surface']}): "
                f"{_markdown_text(item['description'])}"
            )
        lines.append("")
    unlisted = {item["surface"] for item in payload["surfaces"] if item["indexable"]} - listed
    if unlisted:
        raise ValueError("indexable surface missing from llms.txt: " + ", ".join(sorted(unlisted)))
    lines += ["## Optional", ""]
    for fragment, href in LLMS_OPTIONAL_LINKS:
        url = origin + href if href.startswith("/") else href
        lines.append(f"- [{_markdown_text(_anchor_label(fragment, href))}]({url})")
    lines.append("")
    return "\n".join(lines)


def _discovery_outputs(payload: dict, lastmod: dict) -> dict[Path, str]:
    return {
        ROOT / "frontend" / "robots.txt": robots_text(payload),
        ROOT / "frontend" / "sitemap.xml": sitemap_text(payload, lastmod),
        ROOT / "frontend" / "llms.txt": llms_text(payload),
    }


IANA_ZONE_NAMES = ROOT / "backend" / "app" / "iana_zone_names.json"
TIMEZONE_NAMES_SCRIPT = FRONTEND / "zh-TW" / "timezone-names.js"


def timezone_names_script() -> str:
    """The page's copy of the IANA names the request schema accepts.

    Generated, never hand-edited: the free-text time-zone field is checked
    against the same committed list as the service, so a name the service
    refuses is caught before the request is sent.
    """

    names = json.loads(IANA_ZONE_NAMES.read_text(encoding="utf-8"))["names"]
    if not names:
        raise ValueError(f"{IANA_ZONE_NAMES} lists no time-zone names")
    listed = "\n".join(f"    {json.dumps(name)}," for name in names)
    return (
        "// 由 scripts/frontend/build_pages.py 依 backend/app/iana_zone_names.json 產生，不要手改。\n"
        "// 服務接受的 IANA 時區名稱；手動輸入的時區在送出前以同一份名單檢查。\n"
        "(function (root, factory) {\n"
        "  const api = factory();\n"
        "  if (typeof module === \"object\" && module.exports) module.exports = api;\n"
        "  if (root) root.TimezoneNames = api;\n"
        "})(typeof globalThis !== \"undefined\" ? globalThis : this, function () {\n"
        "  \"use strict\";\n"
        "  const NAMES = new Set([\n"
        f"{listed}\n"
        "  ]);\n"
        "  return Object.freeze({\n"
        "    accepts: (name) => NAMES.has(name),\n"
        "    size: NAMES.size,\n"
        "  });\n"
        "});\n"
    )


def _method_source_register_output() -> tuple[Path, str]:
    """The published method source register.

    Chart responses carry only `source_ref` codes and the register's digest; this
    file is what those codes resolve against.
    """

    method_sources = _backend("method_sources")
    return (
        ROOT / "frontend" / method_sources.PUBLISHED_PATH.lstrip("/"),
        method_sources.published_register_text(),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--date",
        help="date a changed page's <lastmod> as YYYY-MM-DD (default: today in UTC, "
        "or SOURCE_DATE_EPOCH)",
    )
    args = parser.parse_args()

    payload = load_surface_manifest()
    unclassified = unclassified_pages(payload, FRONTEND)
    if unclassified:
        print(
            "UNCLASSIFIED SURFACE: no frontend/surfaces.json row: "
            + ", ".join(unclassified),
            file=sys.stderr,
        )
        return 1
    require_footer_links(payload)
    drift: list[str] = []
    # Written before the pages: a page's `?v=` stamp is the content version of
    # the script file as it is on disk.
    zone_script = timezone_names_script()
    if args.check:
        current = (
            TIMEZONE_NAMES_SCRIPT.read_text(encoding="utf-8")
            if TIMEZONE_NAMES_SCRIPT.is_file() else ""
        )
        if current != zone_script:
            drift.append(TIMEZONE_NAMES_SCRIPT.name)
    else:
        TIMEZONE_NAMES_SCRIPT.write_text(zone_script, encoding="utf-8")
    digests: dict[str, str] = {}
    for item in payload["surfaces"]:
        target = ROOT / "frontend" / item["output"]
        rendered = render(item, payload["origin"])
        digests[item["key"]] = page_digest(rendered)
        if args.check:
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if current != rendered:
                drift.append(item["key"])
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered, encoding="utf-8")

    lastmod = updated_page_lastmod(load_page_lastmod(), digests, args.date or build_date())
    outputs = dict(_discovery_outputs(payload, lastmod))
    for item in payload["error_pages"]:
        outputs[ROOT / "frontend" / item["output"]] = render_error_page(item)
    outputs[PAGE_LASTMOD] = page_lastmod_text(lastmod)
    register_target, register_text = _method_source_register_output()
    outputs[register_target] = register_text
    for target, rendered in outputs.items():
        if args.check:
            current = target.read_text(encoding="utf-8") if target.is_file() else ""
            if current != rendered:
                drift.append(target.name)
        else:
            target.write_text(rendered, encoding="utf-8")

    if OG_IMAGE_ASSET is not None:
        from scripts.frontend import og_card

        if OG_IMAGE_ASSET != og_card.CARD_ASSET:
            drift.append("og:image asset is not the card og_card.py renders")
        else:
            for error in og_card.render_record_errors():
                print(error, file=sys.stderr)
                drift.append(og_card.RENDER_RECORD.name)

    if args.check and drift:
        print("PAGE BUILD DRIFT: " + ", ".join(drift), file=sys.stderr)
        print("re-run: python -m scripts.frontend.build_pages", file=sys.stderr)
        return 1
    print(
        f"PAGES {'CHECKED' if args.check else 'BUILT'}: "
        f"{len(payload['surfaces'])} surfaces + {len(payload['error_pages'])} error page(s) "
        "+ 4 discovery assets + page lastmod record + method source register"
        " + time-zone name list"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
