"""The page build's validators: the surface manifest, the links that reach every page, inline styles the served CSP
would drop, an article's reference anchors and the page lastmod record's binding to history.

Each check takes what it inspects as arguments and never imports the producer (build_pages); build_pages calls them on
what it reads and writes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
import re

from scripts.frontend.site_locale import DEFAULT_LOCALE

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The served CSP carries no `style-src 'unsafe-inline'`, so an inline `style=` attribute is silently dropped by the
# browser.  Match the attribute position (a tag, whitespace, the attribute) so prose mentioning `style=` is no offence.
_INLINE_STYLE_ATTRIBUTE = re.compile(r"<[A-Za-z][^<>]*?\s(style\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+))",
    re.IGNORECASE | re.DOTALL)

def inline_style_attributes(markup: str) -> list[str]:
    return [match.group(1) for match in _INLINE_STYLE_ATTRIBUTE.finditer(markup)]

def reject_inline_style(markup: str, key: str) -> None:
    offenders = inline_style_attributes(markup)
    if offenders:
        raise ValueError(
            f"inline style attribute in generated page {key!r} is blocked by the "
            f"served CSP: {', '.join(offenders)}"
        )

_FRAGMENT_NAME = re.compile(r"[a-z0-9_-]+")
_LOCALE_CODE = re.compile(r"[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-[A-Z]{2})?")

def _common_row_fields_valid(item: dict, locales: list[str]) -> bool:
    # Surface and error page rows alike: the fragment names a file under pages/, never a path.
    if not (isinstance(item["fragment"], str) and _FRAGMENT_NAME.fullmatch(item["fragment"])):
        raise ValueError(f"frontend page fragment is invalid: {item.get('key')}")
    return (item["locale"] in locales and isinstance(item["layers"],
        list) and bool(item["layers"]) and set(item["layers"]) <= {"L1", "L2", "L3"} and isinstance(item["title"],
        str) and bool(item["title"].strip()))

SURFACE_DEFAULTS: dict[str, object] = {"fragment": None, "locale": None, "indexable": True}

def check_surface_manifest(payload: dict, error_outputs: Mapping[int, str]) -> dict:
    if set(payload) != {"schema_version", "origin", "default_locale", "locales", "surfaces",
        "error_pages"} or payload["schema_version"] != 1:
        raise ValueError("frontend surface manifest root is invalid")
    if payload["origin"] != "https://projectarmillary.com":
        raise ValueError("frontend canonical origin is invalid")
    # A row's locale must be a declared one and its address and output must sit under that locale's directory.
    locales = payload["locales"]
    if (not isinstance(locales,
        list) or not locales or len(set(locales)) != len(locales) or not all(isinstance(code,
        str) and _LOCALE_CODE.fullmatch(code) for code in locales) or payload["default_locale"] not in locales):
        raise ValueError("frontend locale is invalid")
    default = payload["default_locale"]
    expected_fields = {"key", "output", "surface", "layers", "title", "description"}
    seen: dict[str, set[str]] = {name: set() for name in ("key", "output", "surface")}
    for item in payload["surfaces"]:
        if not isinstance(item, dict) or set(item) - {"article", *SURFACE_DEFAULTS} != expected_fields:
            raise ValueError("frontend surface row field set is invalid")
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
    _validate_error_pages(payload, seen, locales, error_outputs)
    return payload

# A blog article is a surface whose row carries an `article` block (published and last-revised days).  It lives under
# the blog's address, is linked from the blog page instead of the shared footer, and is described as a BlogPosting.
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

# A sub-page's address is another page's address plus one segment (/zh-TW/security/verify under /zh-TW/security).
# It is linked from its parent instead of the shared footer, and its trail runs home › parent › its own h1.  An article
# keeps its own rules; a page whose address prefix is no surface (/zh-TW/legal/privacy) is an ordinary footer page.
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

def _validate_error_pages(payload: dict, seen: dict[str, set[str]], locales: list[str],
                          outputs: Mapping[int, str]) -> None:
    rows = payload["error_pages"]
    expected_fields = {"key", "fragment", "output", "status", "locale", "layers", "title"}
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

def unclassified_page_paths(payload: dict, frontend: Path, excluded: Iterable[str]) -> list[str]:
    """HTML pages under ``frontend`` that no surface row classifies.

    Every user-visible surface carries an L1／L2／L3 assignment in frontend/surfaces.json, so a page added beside the
    manifest cannot ship unclassified.  The excluded top-level directories are those the served asset universe excludes
    (backend/app/frontend_assets.py).
    """
    registered = {item["output"] for item in [*payload["surfaces"], *payload["error_pages"]]}
    pages: set[str] = set()
    for entry in frontend.iterdir():
        if entry.name in excluded or entry.is_symlink():
            continue
        candidates = [entry] if entry.is_file() else entry.rglob("*")
        for path in candidates:
            if path.is_file() and path.suffix.casefold() == ".html":
                pages.add(path.relative_to(frontend).as_posix())
    return sorted(pages - registered)

def check_footer_links(payload: dict, labels: Mapping[str, str], pages: Path) -> None:
    """Every surface is reachable through a plain link: a page via the footer, an article via the blog page."""
    surfaces = payload["surfaces"]
    unlinked = [item["surface"] for item in surfaces if not is_article(item) and parent_surface(item,
        surfaces) is None and item["surface"] not in labels]
    if unlinked:
        raise ValueError("surface is not linked from the shared footer: " + ", ".join(unlinked))
    unlinked = []
    for item in surfaces:
        parent = parent_surface(item, surfaces)
        if parent is None:
            continue
        owner = next(other for other in surfaces if other["surface"] == parent)
        body = (pages / f"{owner['fragment']}.html").read_text(encoding="utf-8")
        if f'href="{item["surface"]}"' not in body:
            unlinked.append(item["surface"])
    if unlinked:
        raise ValueError("sub-page is not linked from its parent page: " + ", ".join(unlinked))
    articles = [item for item in payload["surfaces"] if is_article(item)]
    if not articles:
        return
    blog = next(item for item in payload["surfaces"] if item["surface"] == BLOG_SURFACE)
    body = (pages / f"{blog['fragment']}.html").read_text(encoding="utf-8")
    unlinked = [item["surface"] for item in articles if f'href="{item["surface"]}"' not in body]
    if unlinked:
        raise ValueError("article is not linked from the blog page: " + ", ".join(unlinked))
_REFERENCE_LINK = re.compile(r'href="#(ref-\d+)"')
_REFERENCE_TARGET = re.compile(r'\bid="(ref-\d+)"')

def check_article_references(body: str, key: str) -> None:
    """Every numbered citation (href="#ref-N") lands on a listed source (id="ref-N"), and every listed source is cited.
    """
    links = set(_REFERENCE_LINK.findall(body))
    targets = _REFERENCE_TARGET.findall(body)
    if len(set(targets)) != len(targets) or links != set(targets):
        raise ValueError(
            f"article {key!r} citations and sources disagree: "
            f"unlisted {sorted(links - set(targets))}, uncited {sorted(set(targets) - links)}"
        )

def lastmod_binding_errors(record: dict, history: list[tuple[str, dict]], today: str) -> list[str]:
    """A page's date stays what it was committed with while its content digest is unchanged, is no later than the
    commit that introduced that digest (today, if none has yet) and no earlier than the page's previous date.
    History stops at the first record of another digest scheme, whose digests say nothing about these."""
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
