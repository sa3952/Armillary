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
from collections.abc import Callable, Iterable, Mapping
import copy
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import functools
import hashlib
import html
from html.parser import HTMLParser
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap
from zoneinfo import ZoneInfo

from scripts.frontend.page_checks import (
    _ISO_DATE,
    check_article_references,
    check_footer_links,
    check_surface_manifest,
    is_article,
    lastmod_binding_errors,
    parent_surface,
    reject_inline_style,
    unclassified_page_paths,
)
from scripts.frontend.site_locale import DEFAULT_LOCALE


ROOT: Path = Path(__file__).resolve().parents[2]
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
# (the day before).  A test refuses any other date written next to the public
# start, and Gate F (verify_pre_image_readiness) refuses pages that disagree on
# it or state it after the day of that run.
PUBLIC_ALPHA_START = date(2026, 10, 10)


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


# The copyright page's attribution of the Taiwan place names states the day the
# data was retrieved.  The shipped catalogue's manifest is the one producer of
# that day (the catalogue builder writes it from --source-date), so a rebuilt
# catalogue moves the attribution with it.
PLACE_CATALOG_MANIFEST = ROOT / "backend" / "place_data" / "catalog_manifest.json"


def place_source_snapshot_date(manifest: Path | None = None) -> str:
    value = json.loads((manifest or PLACE_CATALOG_MANIFEST).read_text(encoding="utf-8"))[
        "source_snapshot_date"
    ]
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value):
        raise ValueError(f"place catalogue manifest source_snapshot_date is not a date: {value!r}")
    date.fromisoformat(value)
    return value


# The copyright page lists the shipped ephemeris files and their SHA-256 so a
# reader can compare them with the source tree.  deploy/ephemeris.sha256 (which
# the image build and the entrypoint verify against) is the one statement of
# them: the fragment writes {{ephemeris_digests}} on a line of its own and
# {{ephemeris_file_count}} in the sentence above it.
EPHEMERIS_MANIFEST = ROOT / "deploy" / "ephemeris.sha256"
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


def _fill_block(body: str, name: str, lines: Callable[[str], str]) -> str:
    """{{name}}, which must stand once on a line of its own, replaced by
    `lines(indent)`: a block of lines at that line's indent."""

    token = "{{" + name + "}}"
    if token not in body:
        return body
    filled, count = re.subn(rf"^([ \t]*){re.escape(token)}$", lambda match: lines(match.group(1)), body,
                            flags=re.MULTILINE)
    if count != 1 or token in filled:
        raise ValueError(f"{token} must appear once, on a line of its own")
    return filled


# The features page states how many advanced options there are and in how many
# groups.  The calculator's options catalogue is the one producer of both: the
# page names them as {{advanced_option_count}} and {{advanced_group_count}}, and
# they are read from the catalogue the page ships, so the sentence cannot drift
# from the form.
_ZH_DIGITS = "零一二三四五六七八九"


def zh_count(value: int) -> str:
    """A count from 1 to 99 in Chinese numerals, as the pages write group counts."""

    if not 0 < value < 100:
        raise ValueError(f"count out of range for a Chinese numeral: {value}")
    tens, ones = divmod(value, 10)
    if tens == 0:
        return _ZH_DIGITS[ones]
    return ("" if tens == 1 else _ZH_DIGITS[tens]) + "十" + (_ZH_DIGITS[ones] if ones else "")


def options_catalogue_counts() -> dict[str, str]:
    from scripts.frontend.figures._common import options_catalogue

    catalogue = options_catalogue()
    groups = set(catalogue["advanced"])
    return {
        "advanced_option_count": str(sum(group in groups for group in catalogue["options"])),
        "advanced_group_count": zh_count(len(groups)),
    }


# Several pages state how many fixed stars and star clusters the calculator
# offers.  The product's star list (app.domain_catalog.FIXED_STARS) is the one producer
# of both numbers: an entry whose magnitude is a cluster's integrated light is a
# cluster, every other entry a star.  The pages write {{fixed_star_count}} and
# {{fixed_star_cluster_count}} and the build fills them.


def _is_cluster(entry: dict) -> bool:
    return entry.get("magnitude_basis") == "cluster_integrated"


def fixed_star_count() -> int:
    return sum(not _is_cluster(entry) for entry in _backend("domain_catalog").FIXED_STARS)


def fixed_star_cluster_count() -> int:
    return sum(_is_cluster(entry) for entry in _backend("domain_catalog").FIXED_STARS)


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

    options = _backend("schema_chart").OptionsInput.model_fields
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
@lru_cache(maxsize=1)
def armillary_svg() -> str:
    from scripts.frontend import gen_armillary

    return gen_armillary.build(gen_armillary.HOUR_ANGLE, gen_armillary.AZIM, gen_armillary.ELEV)[0]


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

# Every `?v=` is the content version of the exact file it names: the
# first sixteen hex digits of its SHA-256, from the one definition in
# backend/app/frontend_assets.py that the public cache policy also uses to
# decide whether a request earns the immutable lifetime, so an asset cannot
# change while its URL stays.  Editing a referenced asset without re-running
# this generator is page drift that `--check` reports.
_VERSIONED_ASSET_REFERENCE = re.compile(
    r'(?P<prefix>(?:src|href|data-[a-z]+(?:-[a-z]+)*)="/(?P<name>'
    + re.escape(DEFAULT_LOCALE)
    + r'/[^"?#]+)\?v=)\{\{assets\}\}(?P<fragment>#[^"]*)?"'
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
            f'{match.group("prefix")}{referenced_asset_version(match.group("name"))}{match.group("fragment") or ""}"'
        ),
        markup,
    )
    if "{{assets}}" in stamped:
        raise ValueError(f"unversionable {{{{assets}}}} placeholder in page {key!r}")
    return stamped

_TELEMETRY_FIELD_EXPLANATIONS = {
    "event_schema_version": "固定字串",
    "event": "固定字串",
    "request_id": "伺服器產生的32字元十六進位字串",
    "route": "固定分類，不是原始網址",
    "method": "GET／POST／HEAD／OPTIONS／OTHER",
    # A client that leaves before any response is recorded with 0.
    "status_code": "0（沒有送出回應：用戶端在回應之前已中斷連線）或 100–599",
    "duration_bucket": "以秒分三組（不到 1 秒、1–9 秒、10 秒以上），不記精確耗時",
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


def load_surface_manifest() -> dict:
    stat = SURFACE_MANIFEST.stat()
    return copy.deepcopy(_checked_surface_manifest(str(SURFACE_MANIFEST), stat.st_mtime_ns, stat.st_size))


@lru_cache(maxsize=4)
def _checked_surface_manifest(path: str, _mtime_ns: int, _size: int) -> dict:
    # A build reads the manifest once per page; the file's identity keys the cache.
    return check_surface_manifest(json.loads(Path(path).read_text(encoding="utf-8")), error_page_outputs())


# The error pages a release carries, by the status each one answers with, and
# the served name the static mount looks for (backend/app/frontend_assets.py).
# An error page is not a surface: it has no address, no canonical URL, no
# sitemap entry and no structured data, and it is never indexed.
def error_page_outputs() -> dict[int, str]:
    return {404: _frontend_assets_module().NOT_FOUND_PAGE}


def unclassified_pages(payload: dict, frontend: Path) -> list[str]:
    return unclassified_page_paths(payload, frontend, _frontend_assets_module().EXCLUDED_SOURCE_DIRECTORIES)


_FOOTER_LINK = re.compile(
    r'<a href="(?P<href>/' + re.escape(DEFAULT_LOCALE) + r'/[^"]*)">(?P<label>[^<>]+)</a>'
)
HOME_SURFACE: str = f"/{DEFAULT_LOCALE}/"


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
    check_footer_links(payload, footer_link_labels() if labels is None else labels, PAGES)


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


# The version an article prints is how many distinct dates its lastmod record
# entry has held: every committed revision of the record on the first-parent
# line (less the withdrawn dates below), and the record the build dates the
# page from.  The byline carries a
# placeholder until the page is dated, so the page's digest, which decides its
# date, never reads its own version.
ARTICLE_VERSION_PLACEHOLDER = "{{article_version}}"
_SOURCE_ENTRY = re.compile(r'<li id="ref-\d+">')


def article_source_count(body: str) -> int:
    """How many entries the article's sources section lists."""
    sections = re.findall(r'<section class="ar-refs".*?</section>', body, re.DOTALL)
    if len(sections) != 1:
        raise ValueError("an article has exactly one sources section")
    count = len(_SOURCE_ENTRY.findall(sections[0]))
    if count == 0:
        raise ValueError("an article's sources section lists no source")
    return count


# Record revisions whose new dates were not content changes: a rebuild that
# only marked table frames for a script moved the date of every page with a
# table while the digest still read those attributes.  A date one of these
# gave a page is not a version of it.
WITHDRAWN_LASTMOD_REVISIONS = ("e1d22173c30d192a45440ffc7de54c1a98e352a7",)


def _withdrawn_lastmod_dates(root: Path = ROOT) -> set[tuple[str, str]]:
    withdrawn = set()
    for revision in WITHDRAWN_LASTMOD_REVISIONS:
        try:
            before, after = (json.loads(subprocess.run(
                ["git", "show", f"{commit}:{PAGE_LASTMOD_PATH}"], cwd=root, check=True,
                capture_output=True, timeout=120).stdout) for commit in (f"{revision}^", revision))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            raise ValueError(f"the article versions need record revision {revision[:8]}: {error}") from None
        for key, entry in after["pages"].items():
            if before["pages"].get(key, {}).get("lastmod") != entry["lastmod"]:
                withdrawn.add((key, entry["lastmod"]))
    return withdrawn


@functools.lru_cache(maxsize=1)
def _committed_lastmod_dates() -> dict[str, frozenset[str]]:
    dates: dict[str, set[str]] = {}
    withdrawn = _withdrawn_lastmod_dates()
    for _committed, record in committed_page_lastmod():
        for key, entry in record.get("pages", {}).items():
            if (key, entry["lastmod"]) not in withdrawn:
                dates.setdefault(key, set()).add(entry["lastmod"])
    return {key: frozenset(found) for key, found in dates.items()}


def article_version(key: str, lastmod: dict) -> int:
    dates = set(_committed_lastmod_dates().get(key, ()))
    entry = lastmod["pages"].get(key)
    if entry is None:
        raise ValueError(f"article has no lastmod record entry: {key}")
    dates.add(entry["lastmod"])
    return len(dates)


def fill_article_version(page: str, item: Mapping, lastmod: dict | None) -> str:
    if ARTICLE_VERSION_PLACEHOLDER not in page:
        return page
    if not is_article(item) or page.count(ARTICLE_VERSION_PLACEHOLDER) != 1:
        raise ValueError(f"{item['key']!r}: an article prints its version once, any other page never")
    lastmod = load_page_lastmod() if lastmod is None else lastmod
    return page.replace(ARTICLE_VERSION_PLACEHOLDER, str(article_version(item["key"], lastmod)))


def fill_article_byline(body: str, item: Mapping) -> str:
    def byline(match: re.Match) -> str:
        if match.group(1) not in ARTICLE_TIERS:
            raise ValueError(f"article {item['key']!r} names tier {match.group(1)!r}, not one of {ARTICLE_TIERS}")
        return (f'<p class="ar-byline"><span class="ar-tier">{match.group(1)}</span>'
                '<span>發布 <time datetime="{{article_published}}">{{article_published}}</time></span>'
                f'<span class="ar-version">第 {ARTICLE_VERSION_PLACEHOLDER} 版・出處 {article_source_count(body)} 則</span>'
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
    (scripts/frontend/figures/_fx.defs); the glyphs it names are in the
    shared glyph file (`figure_glyph_file`)."""

    if not _FX_DEFS.search(body):
        return body
    from scripts.frontend.figures import _fx

    return _FX_DEFS.sub(lambda _match: _fx.sprite(), body)


def figure_glyph_file(surfaces: Iterable[dict]) -> tuple[Path, str]:
    """The shared figure glyph file: every glyph a page fragment's
    `{{fx_defs:KEYS}}` names."""

    from scripts.frontend.figures import _fx

    keys = {
        key
        for item in surfaces
        for match in _FX_DEFS.finditer(_template(PAGES / f"{item['fragment']}.html"))
        for key in (match.group(1) or "").split()
    }
    return FRONTEND / _fx.GLYPH_FILE, _fx.glyph_file(keys)


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


def reading_minutes(markup: str) -> int:
    """Minutes to read the words of a page: no drawing, no markup."""

    text = re.sub(r"<svg\b.*?</svg>", " ", markup, flags=re.DOTALL | re.IGNORECASE)
    text = html.unescape(re.sub(r"<[^<>]+>", " ", text))
    cjk = len(_CJK_CHARACTER.findall(text))
    words = len(_LATIN_WORD.findall(text))
    return max(1, -(-(cjk * _LATIN_WORDS_PER_MINUTE + words * _CJK_PER_MINUTE)
                    // (_CJK_PER_MINUTE * _LATIN_WORDS_PER_MINUTE)))


def fill_article_reading_time(body: str, item: dict) -> str:
    if not is_article(item):
        if "{{article_reading_minutes}}" in body:
            raise ValueError(f"reading time placeholder outside an article: {item['key']!r}")
        return body
    check_article_references(body, item["key"])
    return body.replace("{{article_reading_minutes}}", str(reading_minutes(body)))


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
        _readable_script,
    )


def _readable_script(name: str) -> str:
    from scripts.frontend import javascript

    return javascript.readable(name)


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


def fill_table_layout(body: str) -> str:
    from scripts.frontend import table_layout

    return table_layout.fill(body)


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

    return fill_article_version(_render_dated(item, origin, *_render_parts(item, origin),
                                              recorded_page_date(item, lastmod)), item, lastmod)


def _public_alpha_date(item: Mapping, key: str) -> str:
    return public_alpha_dates(non_breaking=item["fragment"] in NON_BREAKING_DATE_FRAGMENTS)[key]


# The values a fragment writes as {{name}}, each produced from its one owner
# only when the fragment names it: (row) -> text.
SCALARS: dict[str, Callable[[Mapping], str]] = {
    "telemetry_contract_rows": lambda item: telemetry_contract_rows(),
    "telemetry_field_count": lambda item: telemetry_field_count(),
    "telemetry_field_list": lambda item: telemetry_field_list(),
    "public_alpha_start": lambda item: _public_alpha_date(item, "public_alpha_start"),
    "private_alpha_last_day": lambda item: _public_alpha_date(item, "private_alpha_last_day"),
    "place_source_snapshot_date": lambda item: place_source_snapshot_date(),
    "ephemeris_file_count": lambda item: zh_count(len(ephemeris_digests())),
    "advanced_option_count": lambda item: options_catalogue_counts()["advanced_option_count"],
    "advanced_group_count": lambda item: options_catalogue_counts()["advanced_group_count"],
    "fixed_star_count": lambda item: str(fixed_star_count()),
    "fixed_star_cluster_count": lambda item: str(fixed_star_cluster_count()),
    "time_lord_techniques": lambda item: html.escape(time_lord_series(), quote=False),
    "published_article_count": lambda item: str(
        sum(1 for row in load_surface_manifest()["surfaces"] if is_article(row))),
}
_SCALAR = re.compile(r"\{\{([a-z_]+)\}\}")
# The placeholder the shell stage fills after the body: the content version.
_LATER_PLACEHOLDERS = frozenset({"assets", "article_version"})


def fill_scalars(body: str, item: Mapping) -> str:
    """Every {{name}} of SCALARS in `body`, each producer run once."""

    values: dict[str, str] = {}

    def value(match: re.Match) -> str:
        name = match.group(1)
        if name not in SCALARS:
            return match.group(0)
        if name not in values:
            values[name] = SCALARS[name](item)
        return values[name]

    return _SCALAR.sub(value, body)


def _ephemeris_lines(indent: str) -> str:
    return "\n".join(f'{indent}<div><b class="mono">{html.escape(name)}</b><span class="mono">{digest}</span></div>'
                     for name, digest in ephemeris_digests())


# Every fill a page fragment goes through, in order: (body, row, origin) -> body.
# A filler is a no-op on a fragment without its placeholder.
BODY_FILLERS: tuple[Callable[[str, dict, str], str], ...] = (
    lambda body, item, origin: fill_scalars(body, item),
    lambda body, item, origin: _fill_block(body, "ephemeris_digests", _ephemeris_lines),
    lambda body, item, origin: _fill_block(body, "armillary_svg",
                                           lambda indent: textwrap.indent(armillary_svg(), indent)),
    lambda body, item, origin: fill_fx_defs(body),
    lambda body, item, origin: fill_article_byline(body, item),
    lambda body, item, origin: fill_source_legend(body, item),
    lambda body, item, origin: fill_article_dates(body, item),
    lambda body, item, origin: fill_article_reading_time(body, item),
    lambda body, item, origin: fill_slate_numbers(body),
    lambda body, item, origin: fill_slate_counts(body),
    lambda body, item, origin: fill_calculation_requests(body, origin),
    lambda body, item, origin: fill_civil_time_tables(body),
    lambda body, item, origin: fill_figure_script(body, item),
    lambda body, item, origin: fill_table_layout(body),
)


def fill_placeholders(text: str, values: Mapping[str, str]) -> str:
    """`{{name}}` replaced by each value in turn, in the mapping's order."""

    for name, value in values.items():
        text = text.replace("{{" + name + "}}", value)
    return text


def _render_parts(item: dict, origin: str) -> tuple[str, str | None]:
    body = _template(PAGES / f"{item['fragment']}.html").rstrip("\n")
    for fill in BODY_FILLERS:
        body = fill(body, item, origin)
    unknown = sorted({name for name in _SCALAR.findall(body) if name not in _LATER_PLACEHOLDERS})
    if unknown:
        raise ValueError(f"page {item['key']!r} names unknown placeholders: {unknown}")
    reject_inline_style(body, item["key"])
    headline = (
        page_headline(body, item["key"])
        if is_article(item) or parent_surface(item, load_surface_manifest()["surfaces"])
        else None
    )
    return body, headline


def _render_dated(item: dict, origin: str, body: str, headline: str | None,
                  updated: str | None, stamp: bool = True) -> str:
    if updated is not None and not is_dated(item):
        raise ValueError(f"an article states its own dates, not a page date: {item['key']}")
    shell = _mark_nav_cta(_template(SHELL), item["surface"])
    if shell.count(_PAGE_UPDATED_PLACEHOLDER) != 1:
        raise ValueError("page shell must have exactly one page date placeholder")
    shell = shell.replace(
        _PAGE_UPDATED_PLACEHOLDER, "" if updated is None else page_updated_line(updated)
    )
    metadata = structured_data.metadata_values(item, origin, headline, updated, body)
    og_image, twitter_card = og_image_markup(origin)
    # {{body}} 先插入，{{assets}} 後蓋上內容版本，順序不可調換：頁面片段自己
    # 也需要版本鍵。/zh-TW/ 的敏感度示範腳本只屬於該頁，放進 _shell.html 會讓
    # 其他每一頁都載入一個對它們無用的檔案；留在片段裡，就必須讓片段也能寫
    # ?v={{assets}}。每個靜態資產引用都帶正確的內容版本，由
    # tests/integration/test_hosted_profile.py 逐頁檢查。
    page = fill_placeholders(_shell_with_discovery(shell, keep=True), {
        "og_image": og_image,
        "twitter_card": twitter_card,
        **{key: metadata[key] for key in (
            "og_type", "og_article", "robots", "locale", "og_locale", "site_name", "title",
            "description", "canonical", "json_ld", "surface",
        )},
        "stylesheets": stylesheet_link(item),
        "body": body,
    })
    return stamp_asset_versions(page, item["key"]) if stamp else page


def render_error_page(item: dict, stamp: bool = True) -> str:
    """An error page: the shared header and footer, which link home and to
    every surface, around the page's own fragment, under `noindex`."""

    shell = _shell_with_discovery(_template(SHELL), keep=False)
    body = _template(PAGES / f"{item['fragment']}.html").rstrip("\n")
    reject_inline_style(body, item["key"])
    rendered = fill_placeholders(shell, {
        "robots": "noindex",
        "locale": html.escape(item["locale"], quote=True),
        "title": html.escape(item["title"], quote=True),
        "surface": html.escape(f"{item['status']} · {' ＋ '.join(item['layers'])}", quote=True),
        "stylesheets": stylesheet_link(item),
        "page_updated": "",
        "body": body,
    })
    leftover = re.findall(r"\{\{(?!assets\}\})[^{}]*\}\}", rendered)
    if leftover:
        raise ValueError(f"unfilled placeholder in error page {item['key']!r}: {leftover}")
    return stamp_asset_versions(rendered, item["key"]) if stamp else rendered


# A page's content, for its <lastmod>, is what a reader reads and a search
# result shows: the title, the description and what <main> holds.  The shared
# header and footer, the head's links and the structured data are restated by
# every build that touches the site's chrome, a `?v=` stamp is the version of a
# file the page names, not the page, a class only picks a style, and a data-*
# hook, a tab stop, a landmark role or a script the page loads only changes how
# the page behaves; none of them moves the date.
_MAIN_CONTENT = re.compile(r'<main id="main-content">(.*?)</main>', re.S)
_PAGE_TITLE = re.compile(r"<title>(.*?)</title>", re.S)
_PAGE_DESCRIPTION = re.compile(r'<meta name="description" content="([^"]*)">')
# A version a page prints, whole or shortened to a few digits and an ellipsis
# (the verify page's request list) or not yet stamped.
_PRINTED_VERSION = re.compile(r"\?v=(?:[0-9a-f]{6,16}…?|\{\{assets\}\})")
# Attributes that name a style or a behaviour rather than what the reader reads,
# and the scripts the page loads.  A data-* attribute a stylesheet prints with
# attr() (a stacked table's column label, the calculator's status message) is
# text the reader reads, so it stays.
_BEHAVIOUR_ATTRIBUTE = re.compile(r' (class|data-[a-z0-9-]+|tabindex|role)(?:="[^"]*")?(?=[\s/>])')
_LOADED_SCRIPT = re.compile(r'\s*<script [^>]*\bsrc="[^"]*"[^>]*></script>')
_STYLE_PRINTED_ATTRIBUTE = re.compile(r"attr\((data-[a-z0-9-]+)\)")


@functools.lru_cache(maxsize=1)
def _printed_data_attributes() -> frozenset[str]:
    from scripts.frontend import stylesheets

    return frozenset(name for sheet in sorted(stylesheets.STYLES.glob("*.css"))
                     for name in _STYLE_PRINTED_ATTRIBUTE.findall(sheet.read_text(encoding="utf-8")))


def _without_behaviour_attributes(body: str) -> str:
    printed = _printed_data_attributes()
    return _BEHAVIOUR_ATTRIBUTE.sub(lambda found: found.group(0) if found.group(1) in printed else "", body)
# An article's version and source count restate its record and its sources
# section; the line itself is not content that moves the page's date.
_ARTICLE_VERSION_LINE = re.compile(r'<span class="ar-version">[^<]*</span>')
# The digest scheme the record's content_sha256 values are written under; a
# record of another scheme has no digest comparable with these.
PAGE_LASTMOD_SCHEMA = 3


def page_digest(page: str) -> str:
    main = _MAIN_CONTENT.findall(page)
    title = _PAGE_TITLE.findall(page)
    description = _PAGE_DESCRIPTION.findall(page)
    if len(main) != 1 or len(title) != 1 or len(description) > 1:
        raise ValueError("a page to date has one <main id=\"main-content\">, one <title> and at most one description")
    body = _LOADED_SCRIPT.sub("", _without_behaviour_attributes(
        _PRINTED_VERSION.sub("?v=", _ARTICLE_VERSION_LINE.sub("", main[0]))))
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
LLMS_HOUSE_SYSTEM_ORDER = ("W", "E", "O", "B", "C", "R", "P")


# llms-full.txt: the long companion llms.txt links, for a reader that wants
# the text rather than the index.  It holds the methods page as a reader sees
# it and, for each published article, its summary, its opening paragraph and
# its key points (`p.ar-lead` and `section.ar-points`, which every article
# fragment has).  Each part is the rendered page body turned into plain text,
# so it can only say what the pages say.
LLMS_FULL_NAME = "llms-full.txt"
LLMS_FULL = FRONTEND / LLMS_FULL_NAME


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
    # Packed by area: one run of consecutive names per prefix (the part before the
    # first "/"; none for UTC), space-separated, unpacked in the same order at load.
    runs: list[tuple[str, list[str]]] = []
    for name in names:
        area, slash, rest = name.partition("/")
        prefix, local = (area, rest) if slash else ("", name)
        if " " in local:
            raise ValueError(f"time-zone name with a space: {name!r}")
        if runs and runs[-1][0] == prefix:
            runs[-1][1].append(local)
        else:
            runs.append((prefix, [local]))
    listed = "\n".join(f"    [{json.dumps(prefix)}, {json.dumps(' '.join(locals_))}]," for prefix, locals_ in runs)
    return (
        "// 由 scripts/frontend/build_pages.py 依 backend/app/iana_zone_names.json 產生，不要手改。\n"
        "// 服務接受的 IANA 時區名稱；手動輸入的時區在送出前以同一份名單檢查。\n"
        "(function (root, factory) {\n"
        "  const api = factory();\n"
        "  if (typeof module === \"object\" && module.exports) module.exports = api;\n"
        "  if (root) root.TimezoneNames = api;\n"
        "})(typeof globalThis !== \"undefined\" ? globalThis : this, function () {\n"
        "  \"use strict\";\n"
        "  // [區域, 以空格分開的其餘部分]：依名單原順序展開（沒有區域的名稱如 UTC，區域是空字串）。\n"
        "  const RUNS = [\n"
        f"{listed}\n"
        "  ];\n"
        "  const NAMES = new Set(RUNS.flatMap(([area, rest]) => rest.split(\" \").map((name) => (area ? `${area}/${name}` : name))));\n"
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


OPTIONS_CATALOGUE_SCRIPT = ROOT / "scripts" / "frontend" / "scripts" / "options-catalogue.js"
_OPTIONS_SCHEMA_BLOCK = re.compile(
    r"(  // <options-schema>[^\n]*\n)  const SCHEMA = Object\.freeze\(\{.*?\}\);\n(  // </options-schema>)", re.S,
)


def options_schema_entries() -> dict[str, dict]:
    """The machine part of the options catalogue: each OptionsInput field's
    type, default, value set and bounds, read from the request schema."""

    options_input = _backend("schema_chart").OptionsInput
    properties = options_input.model_json_schema()["properties"]
    entries: dict[str, dict] = {}
    for key, prop in properties.items():
        variants = prop.get("anyOf", [prop])
        nullable = any(variant.get("type") == "null" for variant in variants)
        (main,) = [variant for variant in variants if variant.get("type") != "null"]
        # A factory default (no "default" in the schema) is the value an empty request gets.
        default = prop["default"] if "default" in prop else getattr(options_input(), key)
        if main["type"] == "boolean" and not nullable:
            entry: dict = {"type": "boolean", "default": default}
        elif main["type"] == "string" and ("enum" in main or "const" in main):
            values = list(main["enum"]) if "enum" in main else [main["const"]]
            entry = {"type": "choice", "default": default, "values": values + ([None] if nullable else [])}
        elif main["type"] == "number":
            exclusive = "exclusiveMinimum" in main
            entry = {
                "type": "number", "default": default,
                "min": main["exclusiveMinimum"] if exclusive else main["minimum"],
                "exclusive_min": exclusive, "max": main["maximum"],
            }
        else:
            raise ValueError(f"OptionsInput.{key}: no catalogue type for schema {prop!r}")
        entries[key] = entry
    return entries


def options_catalogue_script() -> str:
    """options-catalogue.js with its schema block regenerated from OptionsInput;
    the hand-written labels, grouping and help text around it are kept."""

    source = OPTIONS_CATALOGUE_SCRIPT.read_text(encoding="utf-8")
    lines = "".join(
        f"    {json.dumps(key)}: {json.dumps(entry, ensure_ascii=False)},\n"
        for key, entry in options_schema_entries().items()
    )
    replaced, count = _OPTIONS_SCHEMA_BLOCK.subn(
        lambda match: f"{match.group(1)}  const SCHEMA = Object.freeze({{\n{lines}  }});\n{match.group(2)}", source,
    )
    if count != 1:
        raise ValueError(f"{OPTIONS_CATALOGUE_SCRIPT} has no single <options-schema> block")
    return replaced


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
    _emit(OPTIONS_CATALOGUE_SCRIPT, options_catalogue_script(), OPTIONS_CATALOGUE_SCRIPT.name, drift, check=args.check)
    from scripts.frontend import javascript

    drift.extend(_write_or_compare(
        javascript.build_scripts(), FRONTEND / javascript.SHIPPED_DIRECTORY, "*.js", check=args.check,
    ))
    # Before the pages too: their figures name the glyph file by content version.
    glyph_target, glyph_text = figure_glyph_file(payload["surfaces"])
    _emit(glyph_target, glyph_text, glyph_target.name, drift, check=args.check)
    from scripts.frontend import stylesheets

    digests: dict[str, str] = {}
    parts: dict[str, tuple[str, str | None]] = {}
    for item in payload["surfaces"]:
        parts[item["key"]] = _render_parts(item, payload["origin"])
        # The digest is of the undated page: a page's date is not its content.
        digests[item["key"]] = page_digest(
            _render_dated(item, payload["origin"], *parts[item["key"]], None, stamp=False)
        )

    lastmod = updated_page_lastmod(load_page_lastmod(), digests, args.date or build_date())
    # A page's stylesheet bundle holds the rules its own classes and ids could
    # match (stylesheets.py), so the bundles are cut from the pages, unstamped,
    # and written before the pages that name them by content version.
    names_by_audience: dict[str, set[str]] = {}
    for item in payload["surfaces"]:
        page = _render_dated(item, payload["origin"], *parts[item["key"]],
                             recorded_page_date(item, lastmod), stamp=False)
        names_by_audience.setdefault(stylesheets.audience_of(item), set()).update(
            stylesheets.names_on_page(page, FRONTEND))
    for item in payload["error_pages"]:
        names_by_audience.setdefault(stylesheets.audience_of(item), set()).update(
            stylesheets.names_on_page(render_error_page(item, stamp=False), FRONTEND))
    drift.extend(_write_or_compare(
        stylesheets.build_bundles([*payload["surfaces"], *payload["error_pages"]], names_by_audience),
        FRONTEND / stylesheets.BUNDLE_DIRECTORY, "*", check=args.check,
    ))
    for item in payload["surfaces"]:
        # Again: a fragment may print a bundle's content version (the verify page's request list).
        parts[item["key"]] = _render_parts(item, payload["origin"])
        rendered = fill_article_version(_render_dated(item, payload["origin"], *parts[item["key"]],
                                                      recorded_page_date(item, lastmod)), item, lastmod)
        _emit(ROOT / "frontend" / item["output"], rendered, item["key"], drift, check=args.check)

    outputs = dict(discovery.discovery_outputs(payload, lastmod))
    outputs[LLMS_FULL] = discovery.llms_full_text(
        payload, {key: body for key, (body, _) in parts.items()}
    )
    for item in payload["error_pages"]:
        outputs[ROOT / "frontend" / item["output"]] = render_error_page(item)
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
        "+ 6 discovery assets + page lastmod record + method source register"
        " + time-zone name list + shipped scripts"
    )
    return 0


# Imported last: they read this module's paths and helpers at call time (so a
# test that repoints PAGES or SHELL repoints them too), and their own
# module-level names are built from this module's constants.
from scripts.frontend import discovery, structured_data  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
