#!/usr/bin/env python3
"""Generate frontend pages from fragments at commit time.

The project chose "generate at commit time and commit the output" over both a
hand-written set and a build chain: the release copies committed files, and the
surfaces (times languages, once more than one is served) do not each carry their own
copy of the head, header and footer.  How many surfaces there are is whatever
frontend/surfaces.json lists; it is not restated here.  The stylesheets and the
page scripts ship minified; their readable forms (scripts/frontend/styles/ and
scripts/frontend/scripts/), the form to edit, are what the public source export
carries beside the shipped files.

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
from html.parser import HTMLParser
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
from zoneinfo import ZoneInfo

from scripts.frontend.site_locale import DEFAULT_LOCALE


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
# frontend/, so it is never a served asset.  An unchanged page carries its
# date forward, so `--check` alone would accept an edited date; it also holds
# each date to the record's first-parent Git history (lastmod_binding_errors).
PAGE_LASTMOD_PATH = "scripts/frontend/page_lastmod.json"
PAGE_LASTMOD = ROOT / PAGE_LASTMOD_PATH
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

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


# The privacy and terms head notes write their dates with U+2011 (non-breaking
# hyphen): a wrapping head note would otherwise break a date at its hyphen.  It
# looks the same as "-".  Other pages keep the plain hyphen.
NON_BREAKING_HYPHEN = "\u2011"
NON_BREAKING_DATE_FRAGMENTS = frozenset({"legal-privacy", "legal-terms"})


def public_alpha_dates(start: date | None = None, *, non_breaking: bool = False) -> dict[str, str]:
    start = PUBLIC_ALPHA_START if start is None else start
    hyphen = NON_BREAKING_HYPHEN if non_breaking else "-"
    return {
        key: value.isoformat().replace("-", hyphen)
        for key, value in (
            ("public_alpha_start", start),
            ("private_alpha_last_day", start - timedelta(days=1)),
        )
    }


def fill_public_alpha_dates(body: str, start: date | None = None, *, non_breaking: bool = False) -> str:
    dates = public_alpha_dates(start, non_breaking=non_breaking)
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
OPTIONS_CATALOGUE = ROOT / "frontend" / DEFAULT_LOCALE / "options-catalogue.js"
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


# Several pages state how many fixed stars and star clusters the calculator
# offers.  The product's star list (app.domain_catalog.FIXED_STARS) is the one producer
# of both numbers: an entry whose magnitude is a cluster's integrated light is a
# cluster, every other entry a star.  The pages write {{fixed_star_count}} and
# {{fixed_star_cluster_count}} and the build fills them.
_FIXED_STAR_COUNT_PLACEHOLDER = "{{fixed_star_count}}"
_FIXED_STAR_CLUSTER_COUNT_PLACEHOLDER = "{{fixed_star_cluster_count}}"


def _is_cluster(entry: dict) -> bool:
    return entry.get("magnitude_basis") == "cluster_integrated"


def fixed_star_count() -> int:
    return sum(not _is_cluster(entry) for entry in _backend("domain_catalog").FIXED_STARS)


def fixed_star_cluster_count() -> int:
    return sum(_is_cluster(entry) for entry in _backend("domain_catalog").FIXED_STARS)


def fill_fixed_star_count(body: str) -> str:
    if _FIXED_STAR_COUNT_PLACEHOLDER in body:
        body = body.replace(_FIXED_STAR_COUNT_PLACEHOLDER, str(fixed_star_count()))
    if _FIXED_STAR_CLUSTER_COUNT_PLACEHOLDER in body:
        body = body.replace(_FIXED_STAR_CLUSTER_COUNT_PLACEHOLDER, str(fixed_star_cluster_count()))
    return body


# What the calculator computes, as the home page, the calculator's lede,
# llms.txt and the WebApplication featureList state it.  The time-lord
# techniques are the annual route's own registry (annual_pipeline
# .ANNUAL_TECHNIQUES): a technique added there without a name here, or named
# here and gone from there, fails the build, so no page claims a technique the
# route does not compute.  Each natal family names the request option that
# turns it on (OptionsInput) or the method that always runs with the chart
# (method_status); a name whose owner is gone fails the build too.
TIME_LORD_TECHNIQUES: tuple[tuple[str, str, str], ...] = (
    ("annual_profection", "年度小限", "annual profections"),
    ("monthly_profection", "月小限", "monthly profections"),
    ("firdaria", "法達", "firdaria"),
    ("zodiacal_releasing", "黃道釋放", "zodiacal releasing"),
    ("decennials", "十年期", "decennials"),
)
NATAL_FEATURES: tuple[tuple[str, str, str], ...] = (
    ("include_houses", "行星位置、上升點、中天與行星落宮", "planet positions with the ascendant, midheaven and house placements"),
    ("include_aspects", "相位", "aspects"),
    ("essential_dignities", "本質尊貴：廟、旺、陷、弱、界、面、三分性、外來", "essential dignities and debilities"),
    ("sect", "日盤夜盤", "sect"),
    ("include_lots", "命運點與精神點", "Lots of Fortune and Spirit"),
    ("include_fixed_stars", "恆星", "fixed stars"),
    ("include_antiscia", "反照點", "antiscia"),
    ("include_declination_aspects", "赤緯平行與反平行", "parallels and contra-parallels"),
    ("include_void_of_course", "月空亡", "void-of-course Moon"),
    ("include_dodecatemoria", "十二分部", "dodecatemoria"),
    ("include_lunar_mansions", "月宿", "lunar mansions"),
    ("include_solar_phase", "焦傷、在光束下與日輪內", "solar phase: combustion, under the beams, cazimi"),
    ("include_motion_states", "行速、停滯與東出西入", "swift or slow, stationary, oriental or occidental of the Sun"),
    ("include_lunar_phases", "月相與產前朔望", "lunar phases and the prenatal syzygy"),
    ("include_eclipses", "日月食", "eclipses"),
    ("planetary_hours", "行星時", "planetary hours"),
)
_TIME_LORD_PLACEHOLDER = "{{time_lord_techniques}}"


def time_lord_techniques() -> tuple[tuple[str, str, str], ...]:
    """The annual time-lord techniques this site offers, (key, 中文, English)."""

    computed = set(_backend("annual_pipeline").ANNUAL_TECHNIQUES)
    named = {key for key, _, _ in TIME_LORD_TECHNIQUES}
    if computed != named:
        raise ValueError(
            "time-lord techniques named on the pages do not match the annual route: "
            f"computed only {sorted(computed - named)}, named only {sorted(named - computed)}"
        )
    sources = _backend("method_sources")
    if sources.ANNUAL_ROUTE_STATUS != "published":
        raise ValueError("the pages name the time-lord techniques, but the annual route is not published")
    return TIME_LORD_TECHNIQUES


def natal_features() -> tuple[tuple[str, str, str], ...]:
    """The natal outputs the pages name, each still owned by an option or a method."""

    options = _backend("schemas").OptionsInput.model_fields
    status = _backend("core.method_status")
    methods = status.DECIDED_METHODS | status.PROVISIONAL_METHODS
    missing = [
        key for key, _, _ in NATAL_FEATURES
        if not (key in options if key.startswith("include_") else key in methods)
    ]
    if missing:
        raise ValueError("natal features named on the pages have no owner: " + ", ".join(missing))
    return NATAL_FEATURES


def _zh_series(names: list[str]) -> str:
    return names[0] if len(names) == 1 else "、".join(names[:-1]) + "與" + names[-1]


def time_lord_series(with_english: bool = True) -> str:
    """年度小限（annual profections）、…與十年期（decennials）."""

    return _zh_series([
        f"{zh}（{en}）" if with_english else zh for _, zh, en in time_lord_techniques()
    ])


def fill_time_lord_techniques(body: str) -> str:
    if _TIME_LORD_PLACEHOLDER in body:
        body = body.replace(_TIME_LORD_PLACEHOLDER, html.escape(time_lord_series(), quote=False))
    return body


def application_features() -> list[str]:
    """The WebApplication featureList: one plain item per computed output."""

    houses = _backend("domain_catalog").HOUSE_SYSTEMS
    items = [f"{zh}（{en}）" for _, zh, en in natal_features()]
    items.insert(1, "七種宮位制：" + "、".join(houses[code] for code in LLMS_HOUSE_SYSTEM_ORDER) + "（house systems）")
    items += [f"年度時間主星：{zh}（{en}）" for _, zh, en in time_lord_techniques()]
    items += [
        "出生時間不確定時標出會變的結果（birth-time sensitivity）",
        "計算收據與 JSON、Markdown、CSV、純文字匯出（calculation receipt and exports）",
    ]
    return items


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
OG_IMAGE_ASSET: str | None = f"{DEFAULT_LOCALE}/og-card.png"
# Alt text proposed with the wiring.
OG_IMAGE_ALT = "渾儀 Armillary：可驗證的古典西洋占星計算器"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# llms.txt: a plain index of the pages for language-model crawlers,
# built from what the site already says.  The sections are the shared footer's
# columns, each entry is a surface's title and description, and the optional
# links take their label from the anchor text the named page already shows; a
# link that disappears from its page fails the build.  Only the facts list
# (llms_facts) has labels of its own.
LLMS_OPTIONAL_LINKS = (
    ("methods", f"/{DEFAULT_LOCALE}/method-sources.json"),
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
    r'(?P<prefix>(?:src|href|data-[a-z]+(?:-[a-z]+)*)="/(?P<name>'
    + re.escape(DEFAULT_LOCALE)
    + r'/[^"?#]+)\?v=)\{\{assets\}\}"'
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


def og_image_url(origin: str, asset: str | None = None, frontend: Path | None = None) -> str | None:
    """The card's absolute, content-versioned URL, or None with no card."""

    asset = OG_IMAGE_ASSET if asset is None else asset
    if asset is None:
        return None
    frontend = FRONTEND if frontend is None else frontend
    name = _frontend_assets_module().validate_asset_name(asset)
    if not (frontend / name).is_file():
        raise ValueError(f"og:image asset is missing: {asset}")
    return _versioned_url(origin, name, frontend)


def _versioned_url(origin: str, name: str, frontend: Path) -> str:
    return f"{origin}/{name}?v={referenced_asset_version(name, frontend)}"


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
    url = _versioned_url(origin, name, frontend)
    lines = (
        f'<meta property="og:image" content="{html.escape(url, quote=True)}">',
        '<meta property="og:image:type" content="image/png">',
        f'<meta property="og:image:width" content="{width}">',
        f'<meta property="og:image:height" content="{height}">',
        f'<meta property="og:image:alt" content="{html.escape(alt, quote=True)}">',
    )
    return "".join(line + "\n" for line in lines), "summary_large_image"


def stamp_asset_versions(markup: str, key: str) -> str:
    """Replace each `/<locale>/<asset>?v={{assets}}` with that asset's version."""

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
# A declared locale: a language subtag, optionally a script and a region.
_LOCALE_CODE = re.compile(r"[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2})?")


def _common_row_fields_valid(item: dict, locales: list[str]) -> bool:
    # Surface and error page rows alike: the fragment names a file under pages/, never a path,
    # and a bad one is refused under its own name.
    if not (isinstance(item["fragment"], str) and _FRAGMENT_NAME.fullmatch(item["fragment"])):
        raise ValueError(f"frontend page fragment is invalid: {item.get('key')}")
    return (
        item["locale"] in locales
        and isinstance(item["layers"], list)
        and bool(item["layers"])
        and set(item["layers"]) <= {"L1", "L2", "L3"}
        and isinstance(item["title"], str)
        and bool(item["title"].strip())
    )


# A surface row's optional fields and their defaults: the fragment is named
# like the key, the locale is the manifest's default, and a page is indexed.
SURFACE_DEFAULTS: dict[str, object] = {"fragment": None, "locale": None, "indexable": True}


def load_surface_manifest() -> dict:
    payload = json.loads(SURFACE_MANIFEST.read_text(encoding="utf-8"))
    if set(payload) != {
        "schema_version", "origin", "default_locale", "locales", "surfaces", "error_pages",
    } or payload["schema_version"] != 1:
        raise ValueError("frontend surface manifest root is invalid")
    if payload["origin"] != "https://projectarmillary.com":
        raise ValueError("frontend canonical origin is invalid")
    # The declared locales are data: a row's locale must be one of them and its
    # address and output must sit under that locale's directory.
    locales = payload["locales"]
    if (
        not isinstance(locales, list)
        or not locales
        or len(set(locales)) != len(locales)
        or not all(isinstance(code, str) and _LOCALE_CODE.fullmatch(code) for code in locales)
        or payload["default_locale"] not in locales
    ):
        raise ValueError("frontend locale is invalid")
    default = payload["default_locale"]
    expected_fields = {"key", "output", "surface", "layers", "title", "description"}
    seen: dict[str, set[str]] = {name: set() for name in ("key", "output", "surface")}
    for item in payload["surfaces"]:
        if not isinstance(item, dict) or set(item) - {"article", *SURFACE_DEFAULTS} != expected_fields:
            raise ValueError("frontend surface row field set is invalid")
        # A field a row leaves out takes its default.
        for field, value in SURFACE_DEFAULTS.items():
            item.setdefault(field, item["key"] if field == "fragment" else default if field == "locale" else value)
        if (
            not _common_row_fields_valid(item, locales)
            or not isinstance(item["indexable"], bool)
            or not isinstance(item["description"], str)
            or not item["description"].strip()
            or not item["surface"].startswith(f"/{item['locale']}/")
            or not item["output"].startswith(f"{item['locale']}/")
            or ".." in Path(item["output"]).parts
        ):
            raise ValueError(f"frontend surface row is invalid: {item.get('key')}")
        _validate_article(item)
        for field in seen:
            value = item[field]
            if not isinstance(value, str) or value in seen[field]:
                raise ValueError(f"frontend surface {field} is invalid or duplicated")
            seen[field].add(value)
    if seen["surface"] != {item["surface"] for item in payload["surfaces"]}:
        raise ValueError("frontend surface set is invalid")
    if {f"/{default}/", f"/{default}/calculate"} - seen["surface"]:
        raise ValueError("frontend entry surfaces are missing")
    for item in payload["surfaces"]:
        _validate_sub_page(item, payload["surfaces"])
    _validate_error_pages(payload, seen, locales)
    return payload


# A blog article is a surface like any other page, whose row carries an
# `article` block with the day it was published and the day it was last
# revised.  It lives under the blog's address, is linked from the blog page
# instead of the shared footer, and is described as a BlogPosting.
BLOG_SURFACE = f"/{DEFAULT_LOCALE}/blog"
ARTICLE_FIELDS = frozenset({"published", "modified"})


def is_article(item: Mapping) -> bool:
    return "article" in item


def _validate_article(item: dict) -> None:
    under_blog = item["surface"].startswith(BLOG_SURFACE + "/")
    if not is_article(item):
        if under_blog:
            raise ValueError(f"page under the blog address has no article block: {item['key']}")
        return
    article = item["article"]
    slug = item["surface"].removeprefix(BLOG_SURFACE + "/")
    if (
        not under_blog
        or not _FRAGMENT_NAME.fullmatch(slug)
        or item["output"] != f"{DEFAULT_LOCALE}/blog/{slug}.html"
        or not isinstance(article, dict)
        or set(article) != ARTICLE_FIELDS
        or not all(isinstance(article[name], str) and _ISO_DATE.fullmatch(article[name])
                   for name in ARTICLE_FIELDS)
    ):
        raise ValueError(f"frontend article row is invalid: {item.get('key')}")
    published, modified = (date.fromisoformat(article[name]) for name in ("published", "modified"))
    if modified < published:
        raise ValueError(f"article is modified before it was published: {item['key']}")


# A sub-page is a page whose address is another page's address plus one more
# segment (/zh-TW/security/verify under /zh-TW/security).  Like an article
# under the blog, it is linked from its parent page instead of the shared
# footer, and its trail runs home › parent › its own h1.  An article is the
# blog's kind of child and keeps its own rules; a page whose address prefix is
# no surface (/zh-TW/legal/privacy) is an ordinary footer page.
def parent_surface(item: Mapping, surfaces: list[dict]) -> str | None:
    if is_article(item):
        return None
    parent = item["surface"].rsplit("/", 1)[0]
    return parent if any(other["surface"] == parent for other in surfaces) else None


def _validate_sub_page(item: dict, surfaces: list[dict]) -> None:
    parent = parent_surface(item, surfaces)
    if parent is None:
        return
    slug = item["surface"].removeprefix(parent + "/")
    owner = next(other for other in surfaces if other["surface"] == parent)
    if (
        not _FRAGMENT_NAME.fullmatch(slug)
        or item["output"] != f"{parent.removeprefix('/')}/{slug}.html"
        or is_article(owner)
        or parent_surface(owner, surfaces) is not None
    ):
        raise ValueError(f"frontend sub-page row is invalid: {item.get('key')}")


# The error pages a release carries, by the status each one answers with, and
# the served name the static mount looks for (backend/app/frontend_assets.py).
# An error page is not a surface: it has no address, no canonical URL, no
# sitemap entry and no structured data, and it is never indexed.
def error_page_outputs() -> dict[int, str]:
    return {404: _frontend_assets_module().NOT_FOUND_PAGE}


def _validate_error_pages(payload: dict, seen: dict[str, set[str]], locales: list[str]) -> None:
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
            not _common_row_fields_valid(item, locales)
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


_FOOTER_LINK = re.compile(
    r'<a href="(?P<href>/' + re.escape(DEFAULT_LOCALE) + r'/[^"]*)">(?P<label>[^<>]+)</a>'
)
HOME_SURFACE = f"/{DEFAULT_LOCALE}/"


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
    """Every surface is reachable through a plain link: a page through the
    footer on every page, an article through the blog page."""

    labels = footer_link_labels() if labels is None else labels
    surfaces = payload["surfaces"]
    unlinked = [
        item["surface"] for item in surfaces
        if not is_article(item) and parent_surface(item, surfaces) is None
        and item["surface"] not in labels
    ]
    if unlinked:
        raise ValueError(
            "surface is not linked from the shared footer: " + ", ".join(unlinked)
        )
    unlinked = []
    for item in surfaces:
        parent = parent_surface(item, surfaces)
        if parent is None:
            continue
        owner = next(other for other in surfaces if other["surface"] == parent)
        body = (PAGES / f"{owner['fragment']}.html").read_text(encoding="utf-8")
        if f'href="{item["surface"]}"' not in body:
            unlinked.append(item["surface"])
    if unlinked:
        raise ValueError("sub-page is not linked from its parent page: " + ", ".join(unlinked))
    articles = [item for item in payload["surfaces"] if is_article(item)]
    if not articles:
        return
    blog = next(item for item in payload["surfaces"] if item["surface"] == BLOG_SURFACE)
    body = (PAGES / f"{blog['fragment']}.html").read_text(encoding="utf-8")
    unlinked = [item["surface"] for item in articles if f'href="{item["surface"]}"' not in body]
    if unlinked:
        raise ValueError("article is not linked from the blog page: " + ", ".join(unlinked))


def page_headline(body: str, key: str) -> str:
    """An article's or a sub-page's headline is the text of its one h1, as the
    reader sees it."""

    headings = re.findall(r"<h1\b[^>]*>(.*?)</h1>", body, re.DOTALL)
    if len(headings) != 1:
        raise ValueError(f"page {key!r} must have exactly one h1")
    text = html.unescape(re.sub(r"<[^<>]+>", "", headings[0]))
    return re.sub(r"\s+", " ", text).strip()


_ARTICLE_DATE_PLACEHOLDER = re.compile(r"\{\{article_(published|modified)\}\}")


def fill_article_dates(body: str, item: dict) -> str:
    """The dates a reader sees are the row's dates the structured data states."""

    if not is_article(item):
        if _ARTICLE_DATE_PLACEHOLDER.search(body):
            raise ValueError(f"article date placeholder outside an article: {item['key']!r}")
        return body
    if "{{article_published}}" not in body:
        raise ValueError(f"article {item['key']!r} must show {{{{article_published}}}}")
    return _ARTICLE_DATE_PLACEHOLDER.sub(lambda match: item["article"][match.group(1)], body)


# The byline every article carries under its headline: its tier, as the blog
# page lists it, then the dates, the reading time and the one signer.
_ARTICLE_BYLINE = re.compile(r"\{\{article_byline:([^{}]*)\}\}")
ARTICLE_TIERS = ("講方法", "帶數據")
ARTICLE_SIGNER = "Sebastian"


def fill_article_byline(body: str, item: Mapping) -> str:
    def byline(match: re.Match) -> str:
        if match.group(1) not in ARTICLE_TIERS:
            raise ValueError(f"article {item['key']!r} names tier {match.group(1)!r}, not one of {ARTICLE_TIERS}")
        return (f'<p class="ar-byline"><span class="ar-tier">{match.group(1)}</span>'
                '<span>發布 <time datetime="{{article_published}}">{{article_published}}</time></span>'
                f"<span>閱讀約 {{{{article_reading_minutes}}}} 分鐘</span><span>{ARTICLE_SIGNER}</span></p>")

    found = len(_ARTICLE_BYLINE.findall(body))
    if found > (1 if is_article(item) else 0):
        raise ValueError(f"{item['key']!r} has {found} article bylines; an article has at most one, any other page none")
    return _ARTICLE_BYLINE.sub(byline, body)


# The reading level each cited source is marked with, in the order the legend
# above an article's sources explains them: (class, label, what it means).
SOURCE_LEVELS = (
    ("rs-checked", "已讀原件", "是我讀過當年刊載它的原件或原件影像"),
    ("rs-checked", "已讀原文", "是我親自讀過的原文"),
    ("rs-checked", "已讀轉錄本", "是我讀過別人轉錄的全文、沒有讀原件影像"),
    ("rs-checked", "已讀譯本", "是我讀過的譯本、沒有讀原文"),
    ("rs-relayed", "轉引", "是我只讀到別人的引述、摘要或整理，沒有讀到原書"),
    ("rs-relayed", "只見書目", "是我只確認了書目"),
    ("rs-register", "本站出處清單", "是本站公開的方法說明與原始碼"),
    ("rs-computed", "本站自算", "是本站計算服務或我依標明版本的程式算出、可以照著重算的結果"),
)
# `{{source_legend}}`, or `{{source_legend|補充句}}` with one sentence of the
# article's own after the shared legend (which versions, which documents).
_SOURCE_LEGEND = re.compile(r"\{\{source_legend(?:\|([^{}]*))?\}\}")
_SOURCE_SECTION = re.compile(r'<section class="ar-refs".*?</section>', re.DOTALL)
_SOURCE_LEVEL = re.compile(r'<span class="rs (rs-[a-z]+)">([^<]*)</span>')


def _legend_supplement(text: str) -> str:
    """One plain sentence in the legend's voice: ends with its only 「。」,
    no markup, and 我 rather than 我們."""

    if (not text.endswith("。") or text.count("。") != 1 or len(text) < 2
            or any(mark in text for mark in "<>|") or "我們" in text):
        raise ValueError(f"a source legend supplement is one plain sentence ending in 。 without 我們: {text!r}")
    return text


def source_legend(sources: str, supplement: str | None = None) -> str:
    """The legend for the reading levels the sources section marks, each
    explained once, in `SOURCE_LEVELS` order, then the article's own
    sentence if it gives one."""

    known = {(cls, label): meaning for cls, label, meaning in SOURCE_LEVELS}
    used = set(_SOURCE_LEVEL.findall(sources))
    unknown = sorted(used - set(known))
    if unknown:
        raise ValueError(f"source level not in SOURCE_LEVELS: {unknown}")
    if not used:
        raise ValueError("a source legend with no marked source")
    entries = "；".join(f'<span class="rs {cls}">{label}</span>{meaning}'
                       for cls, label, meaning in SOURCE_LEVELS if (cls, label) in used)
    extra = "" if supplement is None else _legend_supplement(supplement)
    return f"<p>每一條後面標明我核到哪一層：{entries}。{extra}</p>"


def fill_source_legend(body: str, item: Mapping) -> str:
    """An article's sources section states its legend as `{{source_legend}}`
    (or `{{source_legend|補充句}}`), built from the levels the section marks;
    a page marks no source level without it."""

    sections = _SOURCE_SECTION.findall(body)
    marked = [section for section in sections if _SOURCE_LEVEL.search(section)]
    if (len(_SOURCE_LEGEND.findall(body)) != len(marked)
            or any(len(_SOURCE_LEGEND.findall(section)) != 1 for section in marked)):
        raise ValueError(f"{item['key']!r}: each sources section that marks a reading level holds one "
                         "{{source_legend}}, and no other place does")
    return _SOURCE_SECTION.sub(
        lambda section: _SOURCE_LEGEND.sub(
            lambda legend: source_legend(section.group(0), legend.group(1)), section.group(0)
        ),
        body,
    )


_FX_DEFS = re.compile(r"\{\{fx_defs(?::([a-z_ ]+))?\}\}")


def fill_fx_defs(body: str) -> str:
    """The figure sprite a figure generator asks for as `{{fx_defs:KEYS}}`
    (scripts/frontend/figures/_fx.defs), drawn with the glyphs it names."""

    if not _FX_DEFS.search(body):
        return body
    from scripts.frontend.figures import _fx

    return _FX_DEFS.sub(lambda match: _fx.sprite(tuple((match.group(1) or "").split())), body)


# An article figure is interactive when it has marks to point at, a variant
# switch or a slider; only then does the page load article-figures.js.
FIGURE_SCRIPT = '<script src="/zh-TW/article-figures.js?v={{assets}}" defer></script>'
_INTERACTIVE_FIGURE = re.compile(r"\sdata-fx-(?:key|set|scrub)[\s=>]")


def fill_figure_script(body: str, item: Mapping) -> str:
    """Append the figure script to an article whose figures are interactive."""

    from scripts.frontend import stylesheets

    if "article-figures.js" in body:
        raise ValueError(f"page {item['key']!r} loads the figure script itself; the build adds it")
    if not stylesheets.declares_figures(body):
        if _INTERACTIVE_FIGURE.search(body):
            raise ValueError(f"page {item['key']!r} has figure controls outside a figure[data-fx]")
        return body
    if not is_article(item):
        raise ValueError(f"article figure on a page that is not an article: {item['key']!r}")
    return body + "\n" + FIGURE_SCRIPT if _INTERACTIVE_FIGURE.search(body) else body


def stylesheet_link(item: Mapping) -> str:
    """The one bundle a page loads: tokens, its parts of page.css and, on the
    calculator, calculate.css, on an article, article.css
    (scripts/frontend/stylesheets.py)."""

    from scripts.frontend import stylesheets

    return (
        f'<link rel="stylesheet" href="/{stylesheets.bundle_path(stylesheets.audience_of(item))}'
        '?v={{assets}}">'
    )


# The byline's reading-time estimate: Chinese characters and Latin words per
# minute, rounded up; the page prints it with 「約」.
_CJK_PER_MINUTE = 400
_LATIN_WORDS_PER_MINUTE = 200
_CJK_CHARACTER = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")
_LATIN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’.\-]*")
_REFERENCE_LINK = re.compile(r'href="#(ref-\d+)"')
_REFERENCE_TARGET = re.compile(r'\bid="(ref-\d+)"')


def reading_minutes(markup: str) -> int:
    """Minutes to read the words of a page: no drawing, no markup."""

    text = re.sub(r"<svg\b.*?</svg>", " ", markup, flags=re.DOTALL | re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^<>]+>", " ", text))
    cjk = len(_CJK_CHARACTER.findall(text))
    words = len(_LATIN_WORD.findall(text))
    return max(1, -(-(cjk * _LATIN_WORDS_PER_MINUTE + words * _CJK_PER_MINUTE)
                    // (_CJK_PER_MINUTE * _LATIN_WORDS_PER_MINUTE)))


def check_article_references(body: str, key: str) -> None:
    """Every numbered citation (href="#ref-N") lands on a listed source
    (id="ref-N"), and every listed source is cited."""

    links = set(_REFERENCE_LINK.findall(body))
    targets = _REFERENCE_TARGET.findall(body)
    if len(set(targets)) != len(targets) or links != set(targets):
        raise ValueError(
            f"article {key!r} citations and sources disagree: "
            f"unlisted {sorted(links - set(targets))}, uncited {sorted(set(targets) - links)}"
        )


def fill_article_reading_time(body: str, item: dict) -> str:
    if not is_article(item):
        if "{{article_reading_minutes}}" in body:
            raise ValueError(f"reading time placeholder outside an article: {item['key']!r}")
        return body
    check_article_references(body, item["key"])
    return body.replace("{{article_reading_minutes}}", str(reading_minutes(body)))


def fill_published_article_count(body: str) -> str:
    if "{{published_article_count}}" not in body:
        return body
    count = sum(1 for item in load_surface_manifest()["surfaces"] if is_article(item))
    return body.replace("{{published_article_count}}", str(count))


class _SlateTopics(HTMLParser):
    """The blog page's topic slate: how many topics each group lists, keyed by
    the group's label (`p.gp-k`); a topic is an `li` directly in `ol.slate`,
    and a written one carries the 已發表 mark (`span.tp-pub`)."""

    def __init__(self) -> None:
        super().__init__()
        self.groups: dict[str, int] = {}
        self.published = 0
        self._parents: list[tuple[str, list[str]]] = []
        self._label: list[str] | None = None
        self._group = ""

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        parent = self._parents[-1] if self._parents else ("", [])
        if tag == "p" and "gp-k" in classes:
            self._label = []
        elif tag == "li" and parent[0] == "ol" and "slate" in parent[1]:
            self.groups[self._group] = self.groups.get(self._group, 0) + 1
        elif tag == "span" and "tp-pub" in classes:
            self.published += 1
        if tag != "br":
            self._parents.append((tag, classes))

    def handle_endtag(self, tag):
        if self._parents:
            self._parents.pop()
        if tag == "p" and self._label is not None:
            self._group, self._label = "".join(self._label).strip(), None

    def handle_data(self, data):
        if self._label is not None:
            self._label.append(data)


_SLATE_COUNT = re.compile(r"\{\{slate_topic_count(?::([^{}]+))?\}\}")
_SLATE_UNWRITTEN = "{{slate_unwritten_count}}"


def fill_slate_counts(body: str) -> str:
    """{{slate_topic_count}} is the number of topics the page's slate lists;
    {{slate_topic_count:LABEL}} the number listed under the group named LABEL;
    {{slate_unwritten_count}} the number without the 已發表 mark."""

    if not _SLATE_COUNT.search(body) and _SLATE_UNWRITTEN not in body:
        return body
    parser = _SlateTopics()
    parser.feed(body)
    if not parser.groups:
        raise ValueError("slate count placeholder on a page without a topic slate")
    body = body.replace(_SLATE_UNWRITTEN, str(sum(parser.groups.values()) - parser.published))

    def count(match: re.Match) -> str:
        label = match.group(1)
        if label is None:
            return str(sum(parser.groups.values()))
        if label not in parser.groups:
            raise ValueError(f"no slate group is labelled {label!r}")
        return str(parser.groups[label])

    return _SLATE_COUNT.sub(count, body)


_SLATE_LIST = re.compile(r'<ol class="slate"([^>]*)>(.*?)</ol>', re.DOTALL)
_SLATE_ITEM = re.compile(r"<li[\s>]")
_SLATE_NUMBER = "{{slate_topic_number}}"


def fill_slate_numbers(body: str) -> str:
    """{{slate_topic_number}} is a topic's place in the whole slate (01, 02, ...),
    counted across the groups in page order; each later list gets the `start`
    the browser needs to number its first topic the same way."""

    if _SLATE_NUMBER not in body:
        return body
    place = 1

    def number(match: re.Match) -> str:
        nonlocal place
        if match.group(1).strip():
            raise ValueError("a slate list's start is generated; remove its attributes")
        items = match.group(2)
        topics = len(_SLATE_ITEM.findall(items))
        if items.count(_SLATE_NUMBER) != topics:
            raise ValueError("every slate topic needs exactly one {{slate_topic_number}}")
        start = "" if place == 1 else f' start="{place}"'
        for offset in range(topics):
            items = items.replace(_SLATE_NUMBER, f"{place + offset:02d}", 1)
        place += topics
        return f'<ol class="slate"{start}>{items}</ol>'

    body = _SLATE_LIST.sub(number, body)
    if _SLATE_NUMBER in body:
        raise ValueError("{{slate_topic_number}} outside a topic slate")
    return body


# The site as the publisher of the application and the articles.  It names
# no person.  The alternate names are the two halves of the site name and the
# domain's form of it; the description tells the site apart from the
# astronomical instrument it is named after (the about page's 這個名字), and
# `sameAs` is the public source repository, as on the application.
ORGANIZATION_ID = "/#organization"
ORGANIZATION_ALTERNATE_NAMES = (*SITE_NAME.split(" "), "Project Armillary")
ORGANIZATION_DISAMBIGUATION = (
    "古典西洋占星的計算網站與開源程式；名稱取自天文儀器渾儀（armillary sphere），本身不是那件儀器。"
)


def _organization(origin: str) -> dict:
    return {
        "@type": "Organization",
        "@id": origin + ORGANIZATION_ID,
        "name": SITE_NAME,
        "alternateName": list(ORGANIZATION_ALTERNATE_NAMES),
        "url": origin + "/",
        "disambiguatingDescription": ORGANIZATION_DISAMBIGUATION,
        "logo": _organization_logo(origin),
        "sameAs": [_backend("frontend_release").PUBLIC_REPOSITORY_URL],
    }


def _organization_logo(origin: str, frontend: Path | None = None) -> dict:
    """The site's mark as its logo: the square, opaque touch icon that
    scripts/frontend/favicon.py draws, at the root URL every page's head
    already links; its size is read from the PNG."""

    from scripts.frontend import favicon

    path = (FRONTEND if frontend is None else frontend) / favicon.TOUCH_ASSET
    if not path.is_file():
        raise ValueError(f"organization logo is missing: {favicon.TOUCH_ASSET}")
    width, height = png_dimensions(path.read_bytes())
    return {"@type": "ImageObject", "url": f"{origin}/{favicon.TOUCH_ASSET}", "width": width, "height": height}


# The pages that describe the calculator itself carry the one WebApplication
# node: the entry page and the calculator page.  Both state the same node, built
# from the entry page's row, so the two cannot describe two applications.
CALCULATE_SURFACE = f"/{DEFAULT_LOCALE}/calculate"
APPLICATION_SURFACES = (HOME_SURFACE, CALCULATE_SURFACE)
APPLICATION_ID = "/#application"


def _web_application(origin: str, home: Mapping) -> dict:
    # No `creator` (no person is named in the structured data); free to
    # use, and the license it is published under.
    return {
        "@type": "WebApplication",
        "@id": origin + APPLICATION_ID,
        "url": origin + home["surface"],
        "name": SITE_NAME,
        "alternateName": "Armillary",
        "description": home["description"],
        "applicationCategory": "ReferenceApplication",
        "operatingSystem": "Web",
        "inLanguage": home["locale"],
        "isAccessibleForFree": True,
        # Engines read "free" from an Offer; the pages say 目前全部免費.
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "TWD"},
        "featureList": application_features(),
        "license": LICENSE_URL,
        # The public source repository tells this application apart from
        # same-named ones; it names no person or organisation.
        "sameAs": [_backend("frontend_release").PUBLIC_REPOSITORY_URL],
        "publisher": {"@id": origin + ORGANIZATION_ID},
    }


SOURCE_CODE_ID = "/#source-code"
SOURCE_CODE_LANGUAGES = ("Python", "JavaScript")


def _source_code(origin: str) -> dict:
    # The application's public source: the repository, its licence and the
    # languages its code is written in, published by the site; no person.
    return {
        "@type": "SoftwareSourceCode",
        "@id": origin + SOURCE_CODE_ID,
        "name": f"{SITE_NAME} 原始碼",
        "codeRepository": _backend("frontend_release").PUBLIC_REPOSITORY_URL,
        "license": LICENSE_URL,
        "programmingLanguage": list(SOURCE_CODE_LANGUAGES),
        "targetProduct": {"@id": origin + APPLICATION_ID},
        "publisher": {"@id": origin + ORGANIZATION_ID},
    }


class _GlossaryEntries(HTMLParser):
    """A glossary page's entries as the reader sees them: each `div.gl-item`
    inside `dl.gl-list`, with its anchor (the div's id), its term (the `dt`
    without its original-language span), that span's text, and the entry's
    explanation (the first `p` of its `dd`)."""

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []
        self._in_list = False
        self._field: str | None = None
        self._paragraphs = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "dl" and "gl-list" in classes:
            self._in_list = True
        elif not self._in_list:
            return
        elif tag == "div" and "gl-item" in classes:
            self.entries.append({"id": attributes.get("id") or "", "term": "", "en": "", "text": ""})
            self._paragraphs = 0
        elif tag == "dt" and self.entries:
            self._field = "term"
        elif tag == "span" and self._field == "term" and "en" in classes:
            self._field = "en"
        elif tag == "p" and self.entries:
            self._paragraphs += 1
            self._field = "text" if self._paragraphs == 1 else None

    def handle_endtag(self, tag):
        if tag == "dl":
            self._in_list = False
        elif tag == "span" and self._field == "en":
            self._field = "term"
        elif tag in {"dt", "p"}:
            self._field = None

    def handle_data(self, data):
        if self._field and self.entries:
            self.entries[-1][self._field] += data


def glossary_entries(body: str) -> list[dict]:
    if "gl-list" not in body:
        return []  # the parser only collects inside a dl.gl-list
    parser = _GlossaryEntries()
    parser.feed(body)
    entries = [{name: re.sub(r"\s+", " ", value).strip() for name, value in entry.items()}
               for entry in parser.entries]
    if any(not entry["id"] or not entry["term"] or not entry["text"] for entry in entries):
        raise ValueError("a glossary entry has no anchor, term or explanation")
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("two glossary entries share an anchor")
    return entries


def _defined_term_set(item: Mapping, origin: str, entries: list[dict]) -> dict:
    """The glossary as a DefinedTermSet: one DefinedTerm per entry, in the
    page's words, each at the entry's own anchor on the page."""

    canonical = origin + item["surface"]
    terms = []
    for entry in entries:
        term = {
            "@type": "DefinedTerm",
            "@id": f"{canonical}#{entry['id']}",
            "url": f"{canonical}#{entry['id']}",
            "name": entry["term"],
            "description": entry["text"],
            "inDefinedTermSet": {"@id": canonical + "#terms"},
        }
        if entry["en"]:
            term["alternateName"] = entry["en"]
        terms.append(term)
    return {
        "@type": "DefinedTermSet",
        "@id": canonical + "#terms",
        "url": canonical,
        "name": item["title"].split("｜")[0],
        "inLanguage": item["locale"],
        "hasDefinedTerm": terms,
    }


def _json_ld(item: dict, origin: str, headline: str | None = None,
             updated: str | None = None, body: str | None = None) -> str:
    canonical = origin + item["surface"]
    labels = footer_link_labels()
    graph: list[dict] = [
        {
            "@type": "WebSite",
            "@id": origin + "/#website",
            "url": origin + "/",
            "name": SITE_NAME,
            # The two halves of the name, which search engines may show as the
            # site name on their own.
            "alternateName": SITE_NAME.split(" "),
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
    if updated is not None:
        # The page's recorded lastmod, the sitemap's date and the footer's.
        # No datePublished: no page other than an article has a recorded
        # first-publication date.
        graph[1]["dateModified"] = updated
    if item["surface"] in APPLICATION_SURFACES or is_article(item):
        graph.append(_organization(origin))
    if item["surface"] in APPLICATION_SURFACES:
        home = item if item["surface"] == HOME_SURFACE else next(
            row for row in load_surface_manifest()["surfaces"] if row["surface"] == HOME_SURFACE
        )
        graph.append(_web_application(origin, home))
        graph.append(_source_code(origin))
        graph[1]["about"] = {"@id": origin + APPLICATION_ID}
    if item["surface"] != HOME_SURFACE:
        # A page's trail is home and the page, named by their footer links; an
        # article's is home, the blog and the article's own headline, and a
        # sub-page's home, its parent and its own headline.
        trail = [(HOME_SURFACE, labels.get(HOME_SURFACE))]
        parent = BLOG_SURFACE if is_article(item) else parent_surface(
            item, load_surface_manifest()["surfaces"]
        )
        if parent is not None:
            if not headline:
                raise ValueError(f"page has no headline: {item['surface']}")
            trail += [(parent, labels.get(parent)), (item["surface"], headline)]
        else:
            trail.append((item["surface"], labels.get(item["surface"])))
        if not all(name for _, name in trail):
            raise ValueError(f"surface has no footer label: {item['surface']}")
        graph.append({
            "@type": "BreadcrumbList",
            "@id": canonical + "#breadcrumb",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": position,
                    "name": name,
                    "item": origin + surface,
                }
                for position, (surface, name) in enumerate(trail, start=1)
            ],
        })
        graph[1]["breadcrumb"] = {"@id": canonical + "#breadcrumb"}
    entries = glossary_entries(body) if body is not None else []
    if entries:
        graph.append(_defined_term_set(item, origin, entries))
        graph[1]["mainEntity"] = {"@id": canonical + "#terms"}
    if is_article(item):
        # The site is both publisher and author: the byline on the page names a
        # person, and the structured data names none.
        post = {
            "@type": "BlogPosting",
            "@id": canonical + "#article",
            "url": canonical,
            "headline": headline,
            "description": item["description"],
            "datePublished": item["article"]["published"],
            "dateModified": item["article"]["modified"],
            "inLanguage": item["locale"],
            "mainEntityOfPage": {"@id": canonical + "#webpage"},
            "isPartOf": {"@id": origin + BLOG_SURFACE + "#webpage"},
            "publisher": {"@id": origin + ORGANIZATION_ID},
            "author": {"@id": origin + ORGANIZATION_ID},
        }
        image = og_image_url(origin)
        if image is not None:
            post["image"] = image
        graph.append(post)
    return json.dumps(
        {"@context": "https://schema.org", "@graph": graph},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("<", "\\u003c")


def metadata_values(item: dict, origin: str, headline: str | None = None,
                    updated: str | None = None, body: str | None = None) -> dict[str, str]:
    canonical = origin + item["surface"]
    return {
        "og_type": "article" if is_article(item) else "website",
        "og_article": "".join(
            f'<meta property="article:{name}_time" content="{item["article"][name]}">\n'
            for name in ("published", "modified")
        ) if is_article(item) else "",
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
        "json_ld": _json_ld(item, origin, headline, updated, body),
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


def calculation_requests(origin: str) -> list:
    """The requests one calculation makes, read from the calculator page as
    rendered here (scripts/frontend/privacy_check.py)."""

    from scripts.frontend import privacy_check

    calculate = next(
        item for item in load_surface_manifest()["surfaces"]
        if item["key"] == privacy_check.CALCULATE_KEY
    )
    return privacy_check.calculation_requests(
        render(calculate, origin),
        calculate["surface"],
        privacy_check.frontend_cache_control(
            _backend("privacy_logging"), _frontend_assets_module(), FRONTEND
        ),
        # The readable source, not the shipped copy this build may be rewriting.
        lambda name: (ROOT / "scripts" / "frontend" / "scripts" / name).read_text(encoding="utf-8"),
    )


def fill_calculation_requests(body: str, origin: str) -> str:
    from scripts.frontend import privacy_check

    return privacy_check.fill(
        body,
        rows=lambda: calculation_requests(origin),
        host=privacy_check.host_of(origin),
        # The headers the application adds to every response; the security
        # page prints the same table, bound by test_page_copy_facts.
        headers=lambda: dict(_backend("privacy_logging")._SECURITY_HEADERS),
        repository_url=lambda: _backend("frontend_release").PUBLIC_REPOSITORY_URL,
    )


def fill_civil_time_tables(body: str) -> str:
    from scripts.frontend import civil_time_tables

    return civil_time_tables.fill(body)


# A page other than an article states the day it last changed in its footer
# and as its WebPage's dateModified: the page's date in the lastmod record,
# which the sitemap also gives.  An article shows its own row's dates instead,
# and an error page states none.  The date is left out of the content digest
# (page_digest of the undated page), so stating it never moves it.
_PAGE_UPDATED_PLACEHOLDER = "{{page_updated}}"


def is_dated(item: Mapping) -> bool:
    return not is_article(item)


def page_updated_line(updated: str) -> str:
    if not _ISO_DATE.fullmatch(updated):
        raise ValueError(f"page date must be YYYY-MM-DD: {updated!r}")
    return f'\n    <span>最後更新：<time datetime="{updated}">{updated}</time></span>'


def recorded_page_date(item: Mapping, lastmod: dict | None = None) -> str | None:
    """The date a page states: its lastmod record entry, if it is dated."""

    if not is_dated(item):
        return None
    lastmod = load_page_lastmod() if lastmod is None else lastmod
    entry = lastmod["pages"].get(item["key"])
    if entry is None:
        raise ValueError(f"page has no lastmod record entry: {item['key']}")
    return entry["lastmod"]


def render(item: dict, origin: str, lastmod: dict | None = None) -> str:
    """The page as shipped, dated from `lastmod` (default: the committed record)."""

    return _render_dated(item, origin, *_render_parts(item, origin),
                         recorded_page_date(item, lastmod))


def _render_parts(item: dict, origin: str) -> tuple[str, str | None]:
    name = item["fragment"]
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
    body = fill_public_alpha_dates(body, non_breaking=name in NON_BREAKING_DATE_FRAGMENTS)
    body = fill_place_source_snapshot_date(body)
    body = fill_ephemeris_digests(body)
    body = fill_options_catalogue_counts(body)
    body = fill_fixed_star_count(body)
    body = fill_time_lord_techniques(body)
    body = fill_armillary_svg(body)
    body = fill_fx_defs(body)
    body = fill_article_byline(body, item)
    body = fill_source_legend(body, item)
    body = fill_article_dates(body, item)
    body = fill_article_reading_time(body, item)
    body = fill_published_article_count(body)
    body = fill_slate_numbers(body)
    body = fill_slate_counts(body)
    body = fill_calculation_requests(body, origin)
    body = fill_civil_time_tables(body)
    body = fill_figure_script(body, item)
    reject_inline_style(body, item["key"])
    headline = (
        page_headline(body, item["key"])
        if is_article(item) or parent_surface(item, load_surface_manifest()["surfaces"])
        else None
    )
    return body, headline


def _render_dated(item: dict, origin: str, body: str, headline: str | None,
                  updated: str | None) -> str:
    if updated is not None and not is_dated(item):
        raise ValueError(f"an article states its own dates, not a page date: {item['key']}")
    shell = _mark_nav_cta(_template(SHELL), item["surface"])
    if shell.count(_PAGE_UPDATED_PLACEHOLDER) != 1:
        raise ValueError("page shell must have exactly one page date placeholder")
    shell = shell.replace(
        _PAGE_UPDATED_PLACEHOLDER, "" if updated is None else page_updated_line(updated)
    )
    metadata = metadata_values(item, origin, headline, updated, body)
    og_image, twitter_card = og_image_markup(origin)
    # {{body}} 先插入，{{assets}} 後蓋上內容版本，順序不可調換：頁面片段自己
    # 也需要版本鍵。/zh-TW/ 的敏感度示範腳本只屬於該頁，放進 _shell.html 會讓
    # 其他每一頁都載入一個對它們無用的檔案；留在片段裡，就必須讓片段也能寫
    # ?v={{assets}}。每個靜態資產引用都帶正確的內容版本，由
    # tests/integration/test_hosted_profile.py 逐頁檢查。
    return stamp_asset_versions(
        _shell_with_discovery(shell, keep=True)
        .replace("{{og_image}}", og_image)
        .replace("{{twitter_card}}", twitter_card)
        .replace("{{og_type}}", metadata["og_type"])
        .replace("{{og_article}}", metadata["og_article"])
        .replace("{{robots}}", metadata["robots"])
        .replace("{{locale}}", metadata["locale"])
        .replace("{{og_locale}}", metadata["og_locale"])
        .replace("{{site_name}}", metadata["site_name"])
        .replace("{{title}}", metadata["title"])
        .replace("{{description}}", metadata["description"])
        .replace("{{canonical}}", metadata["canonical"])
        .replace("{{json_ld}}", metadata["json_ld"])
        .replace("{{surface}}", metadata["surface"])
        .replace("{{stylesheets}}", stylesheet_link(item))
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
        .replace("{{stylesheets}}", stylesheet_link(item))
        .replace(_PAGE_UPDATED_PLACEHOLDER, "")
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

    Crawlers for AI answers and AI training are admitted like any other, and
    the Content Signals line (contentsignals.org) says so in the one group;
    there is deliberately no per-bot block.
    """

    origin = payload["origin"]
    return "\n".join([
        "User-agent: *",
        "Content-Signal: search=yes, ai-input=yes, ai-train=yes",
        f"Disallow: {API_PATH_PREFIX}",
        "Allow: /",
        "",
        f"Sitemap: {origin}/sitemap.xml",
        "",
    ])


# A page's content, for its <lastmod>, is what a reader reads and a search
# result shows: the title, the description and what <main> holds.  The shared
# header and footer, the head's links and the structured data are restated by
# every build that touches the site's chrome, a `?v=` stamp is the version of a
# file the page names, not the page, and a class only picks a style; none of
# them moves the date.
_MAIN_CONTENT = re.compile(r'<main id="main-content">(.*?)</main>', re.S)
_PAGE_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_PAGE_DESCRIPTION = re.compile(r'<meta name="description" content="([^"]*)">')
# A version a page prints, whole or shortened to a few digits and an ellipsis
# (the verify page's request list), and a class attribute, which names a style
# rather than what the reader reads.
_PRINTED_VERSION = re.compile(r"\?v=[0-9a-f]{6,16}…?")
_CLASS_ATTRIBUTE = re.compile(r' class="[^"]*"')
# The digest scheme the record's content_sha256 values are written under; a
# record of another scheme has no digest comparable with these.
PAGE_LASTMOD_SCHEMA = 2


def _uncovered_styles(item: Mapping, page: str, names_by_audience: dict[str, set[str]]) -> list[str]:
    """A page.css rule the page's markup or scripts could match but its
    bundle leaves out, as "<page>: <selector>"; the page's names are added to
    its audience's in `names_by_audience`."""

    from scripts.frontend import stylesheets

    audience = stylesheets.audience_of(item)
    names = stylesheets.names_on_page(page, FRONTEND)
    names_by_audience.setdefault(audience, set()).update(names)
    return [f"{item['key']}: {selector}" for selector in stylesheets.uncovered_rules(audience, names)]


def page_digest(page: str) -> str:
    main = _MAIN_CONTENT.findall(page)
    title = _PAGE_TITLE.findall(page)
    description = _PAGE_DESCRIPTION.findall(page)
    if len(main) != 1 or len(title) != 1 or len(description) > 1:
        raise ValueError("a page to date has one <main id=\"main-content\">, one <title> and at most one description")
    body = _CLASS_ATTRIBUTE.sub("", _PRINTED_VERSION.sub("?v=", main[0]))
    content = "\0".join([title[0], *description, body])
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def load_page_lastmod(path: Path | None = None) -> dict:
    path = PAGE_LASTMOD if path is None else path
    if not path.is_file():
        return {"schema_version": PAGE_LASTMOD_SCHEMA, "pages": {}}
    record = json.loads(path.read_text(encoding="utf-8"))
    pages = record.get("pages") if isinstance(record, dict) else None
    if (
        not isinstance(record, dict)
        or set(record) != {"schema_version", "pages"}
        or record["schema_version"] != PAGE_LASTMOD_SCHEMA
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
    return {"schema_version": PAGE_LASTMOD_SCHEMA, "pages": pages}


def committed_page_lastmod(root: Path = ROOT) -> list[tuple[str, dict]]:
    """Every committed revision of the lastmod record on the first-parent line,
    newest first, with its committer's calendar date (YYYY-MM-DD)."""

    def git(*arguments: str, given: bytes | None = None) -> bytes:
        return subprocess.run(["git", *arguments], cwd=root, input=given, check=True,
                              capture_output=True, timeout=120).stdout

    try:
        if git("rev-parse", "--is-shallow-repository").strip() != b"false":
            raise ValueError("a shallow clone")
        commits = [line.split() for line in git(
            "log", "--first-parent", "--format=%H %cs", "--", PAGE_LASTMOD_PATH).decode().splitlines()]
        batch = git("cat-file", "--batch", given="".join(
            f"{commit}:{PAGE_LASTMOD_PATH}\n" for commit, _date in commits).encode())
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise ValueError(f"the page lastmod dates need the record's full Git history: {error}") from None
    history = []
    for _commit, committed in commits:
        header, _, batch = batch.partition(b"\n")
        size = int(header.split()[2])
        history.append((committed, json.loads(batch[:size])))
        batch = batch[size + 1:]
    return history


def lastmod_binding_errors(record: dict, history: list[tuple[str, dict]], today: str) -> list[str]:
    """A page's date stays what it was committed with while its content digest
    is unchanged, is no later than the commit that introduced that digest
    (today, if none has yet) and no earlier than the page's previous date.
    History stops at the first record of another digest scheme, whose digests
    say nothing about these."""

    errors = []
    for key, entry in sorted(record["pages"].items()):
        introduced, previous = today, None
        for committed, revision in history:
            if revision.get("schema_version") != record["schema_version"]:
                break
            old = revision.get("pages", {}).get(key)
            if not isinstance(old, dict) or old.get("content_sha256") != entry["content_sha256"]:
                previous = old.get("lastmod") if isinstance(old, dict) else None
                break
            if old.get("lastmod") != entry["lastmod"]:
                errors.append(f"{key}: lastmod {entry['lastmod']}, but the same content was "
                              f"committed with {old.get('lastmod')}")
                break
            introduced = committed
        if entry["lastmod"] > introduced:
            errors.append(f"{key}: lastmod {entry['lastmod']} is after {introduced}, "
                          "when its content was introduced")
        if previous is not None and entry["lastmod"] < previous:
            errors.append(f"{key}: lastmod {entry['lastmod']} is before its previous date {previous}")
    return errors


def page_lastmod_text(record: dict) -> str:
    return json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# The calendar every date the site states is a day of: an article's published
# and modified dates are the Taiwan day of the release that carries them, so a
# changed page is dated on the same calendar.  A release built in the early
# Taiwan morning would otherwise date its pages the previous (UTC) day, and the
# sitemap would name a day before the article's own dateModified.
SITE_DATE_ZONE = ZoneInfo("Asia/Taipei")


def build_date(environment: Mapping[str, str] | None = None) -> str:
    """Today in Taiwan, or SOURCE_DATE_EPOCH's Taiwan date for a reproducible build."""

    epoch = (os.environ if environment is None else environment).get("SOURCE_DATE_EPOCH")
    moment = (
        datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        if epoch
        else datetime.now(timezone.utc)
    )
    return moment.astimezone(SITE_DATE_ZONE).date().isoformat()


def sitemap_date(item: Mapping, lastmod: dict) -> str:
    """A page's <lastmod>: its lastmod record date; for an article, the later of
    that and the article's own modified date, so the sitemap never names a day
    before the dateModified the page's structured data states."""

    recorded = lastmod["pages"][item["key"]]["lastmod"]
    return max(recorded, item["article"]["modified"]) if is_article(item) else recorded


def sitemap_text(payload: dict, lastmod: dict) -> str:
    origin = payload["origin"]
    entries = []
    for item in payload["surfaces"]:
        if not item["indexable"]:
            continue
        url = xml_escape(origin + item["surface"])
        date = sitemap_date(item, lastmod)
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


def footer_tagline(shell: str | None = None) -> str:
    """The line closing the shared footer: what the site does not do."""

    shell = SHELL.read_text(encoding="utf-8") if shell is None else shell
    end = shell.find("</footer>")
    match = re.search(r"<span>([^<>]+)</span>(?:\{\{page_updated\}\})?\s*</div>\s*$", shell[:end])
    if end < 0 or match is None:
        raise ValueError("page shell footer has no closing line")
    return html.unescape(match.group(1)).strip()


# The facts llms.txt states before its page lists, each read from its owner:
# the license from LICENSE_URL, the source repository and the engine pin from
# the backend, the house systems from the backend's table (in the order the
# calculate page lists them), the time-lord techniques and the natal outputs
# from time_lord_techniques() and natal_features(), the phase from
# PUBLIC_ALPHA_START with the about page's own words for it, and three links.  The known limitations are the
# public repository's docs/KNOWN_LIMITATIONS.md, in English; the plain-text
# companion is llms_full_text's output.
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
LLMS_HOUSE_SYSTEM_ORDER = ("W", "E", "O", "B", "C", "R", "P")
LLMS_KNOWN_LIMITATIONS_PATH = "/blob/main/docs/KNOWN_LIMITATIONS.md"
LLMS_PRIVACY_CHECK_SURFACE = f"/{DEFAULT_LOCALE}/security/verify"


def pinned_version(package: str, requirements: Path | None = None) -> str:
    text = (REQUIREMENTS if requirements is None else requirements).read_text(encoding="utf-8")
    pins = re.findall(rf"^{re.escape(package)}==(\S+)$", text, re.MULTILINE)
    if len(pins) != 1:
        raise ValueError(f"backend requirements pin {package} {len(pins)} times")
    return pins[0]


def _license_id() -> str:
    return LICENSE_URL.rsplit("/", 1)[1].removesuffix(".html")


def llms_facts(origin: str, by_surface: Mapping[str, dict]) -> list[str]:
    houses = _backend("domain_catalog").HOUSE_SYSTEMS
    if set(houses) != set(LLMS_HOUSE_SYSTEM_ORDER):
        raise ValueError("llms.txt house-system order does not match the backend's table")
    repository = _backend("frontend_release").PUBLIC_REPOSITORY_URL
    license_id = _license_id()
    facts: tuple[tuple[str, str], ...] = (
        ("授權", f"{license_id}（{LICENSE_URL}）"),
        ("原始碼", repository),
        ("計算引擎", f"Swiss Ephemeris（pyswisseph {pinned_version('pyswisseph')}）"),
        ("宮位制", "、".join(houses[code] for code in LLMS_HOUSE_SYSTEM_ORDER)),
        ("時間主星", time_lord_series() + "；只列哪一段時間由哪顆行星或哪個星座輪值"),
        ("本命盤", "；".join(zh for _, zh, _ in natal_features())),
        ("狀態", f"公開測試（Public Alpha），自{PUBLIC_ALPHA_START.isoformat()}起"),
        ("已知限制（英文）", repository + LLMS_KNOWN_LIMITATIONS_PATH),
        ("方法頁全文與文章重點（純文字）", f"{origin}/{LLMS_FULL_NAME}"),
    )
    check = by_surface.get(LLMS_PRIVACY_CHECK_SURFACE)
    if check is not None and check["indexable"]:
        facts += (("親手驗證隱私", origin + LLMS_PRIVACY_CHECK_SURFACE),)
    return [f"- {label}：{value}" for label, value in facts]


def _english_series(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def llms_english_summary() -> str:
    """The one English passage on a Chinese-only site, for crawlers that read
    English: what the site is, its boundary, the licence, no accounts or trackers."""

    return (
        "Armillary (渾儀) is a classical Western astrology calculator with a Traditional Chinese interface: "
        "enter a birth date, time and place to get a natal chart, with the method source and a calculation "
        "receipt for every number. It also computes the annual time lords: "
        + _english_series([en for _, _, en in time_lord_techniques()])
        + ", listing which planet or sign rules each period. The natal chart covers "
        + _english_series([en for _, _, en in natal_features()])
        + ". It only calculates; it does not interpret charts or make predictions. "
        f"The code is licensed {_license_id()}, and the site has no accounts, no cookies and no third-party "
        "analytics or trackers."
    )


def llms_text(payload: dict, shell: str | None = None) -> str:
    """/llms.txt (llmstxt.org): the site's name, its summary and its pages.

    The name, the entry page's description as the summary, the footer's
    column headings as sections, each surface's title and description, and
    the optional links' own anchor text are words already on the site.  A
    surface the footer does not group fails the build rather than going
    unlisted.  The footer's closing line follows the summary, so the site's
    boundary is quoted with it, the facts list (llms_facts) follows that, and
    the English summary (llms_english_summary) closes the head.
    """

    origin = payload["origin"]
    by_surface = {item["surface"]: item for item in payload["surfaces"]}
    home = by_surface[HOME_SURFACE]
    lines = [
        f"# {SITE_NAME}", "", f"> {_markdown_text(home['description'])}", "",
        _markdown_text(footer_tagline(shell)) + "。", "",
        *llms_facts(origin, by_surface), "",
        llms_english_summary(), "",
    ]
    listed: set[str] = set()
    columns = footer_columns(shell)
    articles = [item for item in payload["surfaces"] if is_article(item) and item["indexable"]]
    if articles:
        # Articles are linked from the blog page, not the footer; they get a
        # section of their own, headed by the blog's footer label.
        columns.append((footer_link_labels(shell)[BLOG_SURFACE], [item["surface"] for item in articles]))
    for heading, surfaces in columns:
        # A sub-page follows its parent, in the parent's column.
        surfaces = [
            listed_surface
            for surface in surfaces
            for listed_surface in [surface, *(
                item["surface"] for item in payload["surfaces"]
                if parent_surface(item, payload["surfaces"]) == surface
            )]
        ]
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


# llms-full.txt: the long companion llms.txt links, for a reader that wants
# the text rather than the index.  It holds the methods page as a reader sees
# it and, for each published article, its summary, its opening paragraph and
# its key points (`p.ar-lead` and `section.ar-points`, which every article
# fragment has).  Each part is the rendered page body turned into plain text,
# so it can only say what the pages say.
LLMS_FULL_NAME = "llms-full.txt"
LLMS_FULL = FRONTEND / LLMS_FULL_NAME
LLMS_FULL_PAGE_KEYS = ("methods",)
# Interface text with no meaning outside the page: the fold toggles' 展開／收合,
# the fold-all buttons, the in-page section index and the numbered citation
# marks, whose sources are not carried here.
_PLAIN_SKIPPED_TAGS = frozenset({"script", "style", "svg", "button", "summary", "template", "nav"})
_PLAIN_SKIPPED_CLASSES = frozenset({"ar-cite"})
_PLAIN_VOID_TAGS = frozenset({"br", "hr", "img", "input", "meta", "link", "source", "wbr", "col", "area"})
_PLAIN_BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "header", "footer", "nav", "aside", "main", "ul", "ol",
    "li", "dl", "dt", "dd", "table", "thead", "tbody", "tr", "caption", "figure", "figcaption",
    "details", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "pre",
})
_PLAIN_HEADING_MARKS = {"h2": "### ", "h3": "#### ", "h4": "#### "}


class _PlainText(HTMLParser):
    """A page body as lines of plain text: one line per block, list items
    marked `- `, table cells joined by `｜`, h2 and h3 as Markdown headings.
    Hidden elements and interface text are left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._line: list[str] = []
        self._skip: list[str] = []
        self._labels: list[bool] = []
        self._cell = False
        # Two inline elements with nothing between them (a number and its
        # label in a tally) get a space, so they do not read as one word.
        self._after_inline = False

    def _break(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._line)).strip()
        if text and text not in {"-", "- "}:
            self.lines.append(text)
        self._line = []

    def handle_starttag(self, tag, attrs):
        if tag in _PLAIN_VOID_TAGS:
            return
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._skip or tag in _PLAIN_SKIPPED_TAGS or classes & _PLAIN_SKIPPED_CLASSES \
                or "hidden" in attributes or attributes.get("aria-hidden") == "true":
            self._skip.append(tag)
            return
        if tag not in _PLAIN_BLOCK_TAGS and tag not in {"td", "th"}:
            if self._after_inline and self._line and not self._line[-1].endswith(" "):
                self._line.append(" ")
        self._after_inline = False
        if tag in {"td", "th"}:
            if self._cell:
                self._line.append(" ｜ ")
            self._cell = True
        elif tag in _PLAIN_BLOCK_TAGS:
            self._break()
            if tag == "tr":
                self._cell = False
            elif tag == "li":
                self._line.append("- ")
            elif tag in _PLAIN_HEADING_MARKS:
                self.lines.append("")
                self._line.append(_PLAIN_HEADING_MARKS[tag])
        # The 重點 label opening a fold's gist reads as a label, not as the
        # first word of the sentence after it.
        self._labels.append("fold-k" in classes)

    def handle_endtag(self, tag):
        if tag in _PLAIN_VOID_TAGS:
            return
        if self._skip:
            if self._skip[-1] == tag:
                self._skip.pop()
            return
        if self._labels and self._labels.pop():
            self._line.append("：")
        self._after_inline = tag not in _PLAIN_BLOCK_TAGS and tag not in {"td", "th"}
        if tag in _PLAIN_BLOCK_TAGS:
            self._break()
            if tag in _PLAIN_HEADING_MARKS:
                self.lines.append("")

    def handle_data(self, data):
        if not self._skip:
            self._line.append(data)
            if data.strip():
                self._after_inline = False

    def text(self) -> str:
        self._break()
        lines: list[str] = []
        for line in self.lines:
            if line == "" and (not lines or lines[-1] == ""):
                continue
            lines.append(line)
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines)


def plain_text(markup: str) -> str:
    parser = _PlainText()
    parser.feed(markup)
    parser.close()
    return parser.text()


def _article_summary_parts(body: str, key: str) -> tuple[str, str]:
    """An article's opening paragraph and its key points, as plain text."""

    lead = re.findall(r'<p class="ar-lead">.*?</p>', body, re.DOTALL)
    points = re.findall(r'<section class="ar-points"[^<>]*>.*?(<ul>.*?</ul>)\s*</section>', body, re.DOTALL)
    if len(lead) != 1 or len(points) != 1:
        raise ValueError(f"article {key!r} needs exactly one p.ar-lead and one list in section.ar-points")
    return plain_text(lead[0]), plain_text(points[0])


def llms_full_text(payload: dict, bodies: Mapping[str, str] | None = None) -> str:
    """/llms-full.txt: the methods page in full and every published article's
    summary, opening and key points, in plain text.  `bodies` maps a surface
    key to its rendered page body (main() passes the bodies it has already
    rendered); a missing body is rendered here."""

    origin = payload["origin"]

    def body(item: dict) -> str:
        if bodies is not None and item["key"] in bodies:
            return bodies[item["key"]]
        return _render_parts(item, origin)[0]

    by_key = {item["key"]: item for item in payload["surfaces"]}
    lines = [
        f"# {SITE_NAME}：方法頁全文與文章重點", "",
        f"> {_markdown_text(by_key['home']['description'])}", "",
        f"這是 {origin}/llms.txt 的全文版：方法頁的全部文字，以及每一篇已發表文章的摘要、開頭一段與重點，"
        "由網站的建置程式從頁面本身轉成純文字。圖表與表單沒有收錄；完整內容與出處請看各頁網址。", "",
    ]
    for key in LLMS_FULL_PAGE_KEYS:
        item = by_key[key]
        lines += [
            f"## {_markdown_text(item['title'])}", "",
            f"網址：{origin}{item['surface']}", "",
            plain_text(body(item)), "",
        ]
    articles = [item for item in payload["surfaces"] if is_article(item) and item["indexable"]]
    if articles:
        lines += ["## 文章", ""]
    for item in articles:
        lead, points = _article_summary_parts(body(item), item["key"])
        dates = item["article"]
        lines += [
            f"### {_markdown_text(item['title'])}", "",
            f"網址：{origin}{item['surface']}",
            f"發表：{dates['published']}；更新：{dates['modified']}", "",
            f"摘要：{_markdown_text(item['description'])}", "",
            lead, "",
            "重點：", points, "",
        ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _discovery_outputs(payload: dict, lastmod: dict) -> dict[Path, str]:
    assets = _frontend_assets_module()
    return {
        ROOT / "frontend" / "robots.txt": robots_text(payload),
        ROOT / "frontend" / "sitemap.xml": sitemap_text(payload, lastmod),
        ROOT / "frontend" / "llms.txt": llms_text(payload),
        # Exactly the key, with no line end: an IndexNow engine compares the
        # file with the key it was sent.
        ROOT / "frontend" / assets.INDEXNOW_KEY_FILE: assets.INDEXNOW_KEY,
    }


IANA_ZONE_NAMES = ROOT / "backend" / "app" / "iana_zone_names.json"
# The readable script; it ships minified like every page script (javascript.py).
TIMEZONE_NAMES_SCRIPT = ROOT / "scripts" / "frontend" / "scripts" / "timezone-names.js"


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


def _emit(target: Path, text: str, label: str, drift: list[str], *, check: bool) -> None:
    """Write `text` to `target`; with `check`, write nothing and add `label`
    to `drift` when the file differs."""

    if check:
        current = target.read_text(encoding="utf-8") if target.is_file() else ""
        if current != text:
            drift.append(label)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def _write_or_compare(outputs: Mapping[str, str], directory: Path, pattern: str, *, check: bool) -> list[str]:
    """Write `outputs` (keyed by path under frontend/) and delete any other
    file of `directory` matching `pattern`; with `check`, write nothing and
    return what differs or is left over."""

    stale = sorted(
        path.relative_to(FRONTEND).as_posix()
        for path in (directory.glob(pattern) if directory.is_dir() else ())
        if path.relative_to(FRONTEND).as_posix() not in outputs
    )
    drift: list[str] = []
    for name, text in outputs.items():
        _emit(FRONTEND / name, text, name, drift, check=check)
    if check:
        return drift + stale
    for name in stale:
        (FRONTEND / name).unlink()
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--date",
        help="date a changed page's <lastmod> as YYYY-MM-DD (default: today in Taiwan, "
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
    # the shipped script as it is on disk.  The time-zone list's readable
    # script comes first, then every shipped script from its readable source.
    _emit(TIMEZONE_NAMES_SCRIPT, timezone_names_script(), TIMEZONE_NAMES_SCRIPT.name, drift, check=args.check)
    from scripts.frontend import javascript

    drift.extend(_write_or_compare(
        javascript.build_scripts(), FRONTEND / javascript.SHIPPED_DIRECTORY, "*.js", check=args.check,
    ))
    from scripts.frontend import stylesheets

    rows = [*payload["surfaces"], *payload["error_pages"]]
    drift.extend(_write_or_compare(
        stylesheets.build_bundles(rows), FRONTEND / stylesheets.BUNDLE_DIRECTORY, "*", check=args.check,
    ))
    uncovered: list[str] = []
    names_by_audience: dict[str, set[str]] = {}
    digests: dict[str, str] = {}
    parts: dict[str, tuple[str, str | None]] = {}
    for item in payload["surfaces"]:
        parts[item["key"]] = _render_parts(item, payload["origin"])
        # The digest is of the undated page: a page's date is not its content.
        digests[item["key"]] = page_digest(
            _render_dated(item, payload["origin"], *parts[item["key"]], None)
        )

    lastmod = updated_page_lastmod(load_page_lastmod(), digests, args.date or build_date())
    for item in payload["surfaces"]:
        rendered = _render_dated(item, payload["origin"], *parts[item["key"]],
                                 recorded_page_date(item, lastmod))
        uncovered.extend(_uncovered_styles(item, rendered, names_by_audience))
        _emit(ROOT / "frontend" / item["output"], rendered, item["key"], drift, check=args.check)

    outputs = dict(_discovery_outputs(payload, lastmod))
    outputs[LLMS_FULL] = llms_full_text(
        payload, {key: body for key, (body, _) in parts.items()}
    )
    for item in payload["error_pages"]:
        outputs[ROOT / "frontend" / item["output"]] = render_error_page(item)
        uncovered.extend(_uncovered_styles(item, outputs[ROOT / "frontend" / item["output"]], names_by_audience))
    if uncovered:
        print("UNCOVERED STYLE: " + "; ".join(uncovered), file=sys.stderr)
        print(
            "add the page to the @pages marker above these rules in "
            "scripts/frontend/styles/page.css",
            file=sys.stderr,
        )
        return 1
    unused = stylesheets.unused_rules(names_by_audience)
    if unused:
        print("UNUSED STYLE: " + "; ".join(unused), file=sys.stderr)
        print(
            "no page these rules reach names their classes or ids: delete them, or list them in "
            "stylesheets.UNUSED_RULES_KEPT",
            file=sys.stderr,
        )
        return 1
    outputs[PAGE_LASTMOD] = page_lastmod_text(lastmod)
    if args.check:
        # Both calendars: a build dated in Taiwan or in the committer's zone is not in the future.
        today = max(build_date(), date.today().isoformat())
        try:
            unbound = lastmod_binding_errors(load_page_lastmod(), committed_page_lastmod(), today)
        except ValueError as refusal:
            unbound = [str(refusal)]
        for finding in unbound:
            print(f"{PAGE_LASTMOD.name}: {finding}", file=sys.stderr)
        if unbound:
            drift.append(f"{PAGE_LASTMOD.name} dates")
    register_target, register_text = _method_source_register_output()
    outputs[register_target] = register_text
    for target, rendered in outputs.items():
        _emit(target, rendered, target.name, drift, check=args.check)

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
        "+ 5 discovery assets + page lastmod record + method source register"
        " + time-zone name list + shipped scripts"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
