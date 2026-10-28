"""The structured data (JSON-LD) and the head metadata of each page.  Paths and shared helpers are read from
build_pages at call time."""

from __future__ import annotations

from collections.abc import Mapping
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re

from scripts.frontend import build_pages
from scripts.frontend.page_checks import BLOG_SURFACE, is_article, parent_surface
from scripts.frontend.site_locale import DEFAULT_LOCALE

# The site as publisher of the application and the articles.  It names no person.  The description tells the site
# apart from the astronomical instrument it is named after; `sameAs` is the public source repository.
ORGANIZATION_ID = "/#organization"
ORGANIZATION_ALTERNATE_NAMES = (*build_pages.SITE_NAME.split(" "), "Project Armillary")
# The one entity string every first-read surface (home lede, about hero, llms.txt, the public README) uses.
ENTITY_NAME_ZH = "渾儀 Armillary（Project Armillary）"
ENTITY_NAME_EN = "Armillary (Project Armillary)"
ORGANIZATION_DISAMBIGUATION = ("古典西洋占星的計算網站與開源程式；名稱取自天文儀器渾儀（armillary sphere），本身不是那件儀器。")

def _organization(origin: str) -> dict:
    return {"@type": "Organization", "@id": origin + ORGANIZATION_ID, "name": build_pages.SITE_NAME,
        "alternateName": list(ORGANIZATION_ALTERNATE_NAMES), "url": origin + "/",
        "disambiguatingDescription": ORGANIZATION_DISAMBIGUATION, "logo": _organization_logo(origin),
        "sameAs": [build_pages._backend("frontend_release").PUBLIC_REPOSITORY_URL]}

def _organization_logo(origin: str, frontend: Path | None = None) -> dict:
    """The site's mark as its logo: the square, opaque touch icon scripts/frontend/favicon.py draws; size read from
    the PNG."""
    from scripts.frontend import favicon
    path = (build_pages.FRONTEND if frontend is None else frontend) / favicon.TOUCH_ASSET
    if not path.is_file():
        raise ValueError(f"organization logo is missing: {favicon.TOUCH_ASSET}")
    width, height = build_pages.png_dimensions(path.read_bytes())
    return {"@type": "ImageObject", "url": f"{origin}/{favicon.TOUCH_ASSET}", "width": width, "height": height}

# The entry page and the calculator page carry the one WebApplication node, built from the entry page's row so the two
# cannot describe two applications.
CALCULATE_SURFACE = f"/{DEFAULT_LOCALE}/calculate"
APPLICATION_SURFACES = (build_pages.HOME_SURFACE, CALCULATE_SURFACE)
APPLICATION_ID = "/#application"

def _web_application(origin: str, home: Mapping) -> dict:
    return {
        "@type": "WebApplication",
        "@id": origin + APPLICATION_ID,
        "url": origin + home["surface"],
        "name": build_pages.SITE_NAME,
        "alternateName": "Armillary",
        "description": home["description"],
        "applicationCategory": "ReferenceApplication",
        "operatingSystem": "Web",
        "inLanguage": home["locale"],
        "isAccessibleForFree": True,
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "TWD"},
        "featureList": build_pages.application_features(),
        "license": build_pages.LICENSE_URL,
        "sameAs": [build_pages._backend("frontend_release").PUBLIC_REPOSITORY_URL],
        "publisher": {"@id": origin + ORGANIZATION_ID},
    }

SOURCE_CODE_ID = "/#source-code"
SOURCE_CODE_LANGUAGES = ("Python", "JavaScript")

def _source_code(origin: str) -> dict:
    return {"@type": "SoftwareSourceCode", "@id": origin + SOURCE_CODE_ID, "name": f"{build_pages.SITE_NAME} 原始碼",
        "codeRepository": build_pages._backend("frontend_release").PUBLIC_REPOSITORY_URL,
        "license": build_pages.LICENSE_URL, "programmingLanguage": list(SOURCE_CODE_LANGUAGES),
        "targetProduct": {"@id": origin + APPLICATION_ID}, "publisher": {"@id": origin + ORGANIZATION_ID}}

class _GlossaryEntries(HTMLParser):
    """A glossary page's entries: each `div.gl-item` inside `dl.gl-list` with its anchor, term (the `dt` without its
    original-language span), that span's text, and explanation (the first `p` of its `dd`)."""

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

def _entries(parser: "_GlossaryEntries | _FaqEntries", body: str, marker: str, required: tuple[str, ...], refusal: str) -> list[dict]:
    if marker not in body:
        return []
    parser.feed(body)
    entries = [{name: re.sub(r"\s+", " ", value).strip() for name, value in entry.items()} for entry in parser.entries]
    if any(not entry[name] for entry in entries for name in required):
        raise ValueError(refusal)
    return entries

def glossary_entries(body: str) -> list[dict]:
    entries = _entries(_GlossaryEntries(), body, "gl-list", ("id", "term", "text"),
        "a glossary entry has no anchor, term or explanation")
    if len({entry["id"] for entry in entries}) != len(entries):
        raise ValueError("two glossary entries share an anchor")
    return entries

class _FaqEntries(HTMLParser):
    """A page's questions and answers: a `details` in `section.calc-faq` or a `details.tr-faq`, or an article's `h3`
    after the `h2#faq` heading (the paragraphs up to the next `h3`, `h2`, `aside` or section edge are the answer)."""

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict] = []
        self._calc_depth = 0
        self._in_details = False
        self._in_article = False
        self._field: str | None = None

    def _start(self, field: str) -> None:
        if field == "question":
            self.entries.append({"question": "", "answer": ""})
        elif self.entries[-1]["answer"]:
            self.entries[-1]["answer"] += " "
        self._field = field

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "section":
            self._in_article = False
            if self._calc_depth or "calc-faq" in classes:
                self._calc_depth += 1
        elif tag == "details" and (self._calc_depth or "tr-faq" in classes):
            self._in_details = True
        elif tag == "summary" and self._in_details:
            self._start("question")
        elif tag == "h2":
            self._in_article = attributes.get("id") == "faq"
        elif tag == "aside":
            self._in_article = False
        elif tag == "h3" and self._in_article:
            self._start("question")
        elif tag in {"p", "li"} and (self._in_details or self._in_article) and self.entries:
            self._start("answer")

    def handle_endtag(self, tag):
        if tag == "section":
            self._in_article = False
            if self._calc_depth:
                self._calc_depth -= 1
        elif tag == "details":
            self._in_details = False
            self._field = None
        elif tag in {"summary", "h3", "p", "li"}:
            self._field = None

    def handle_data(self, data):
        if self._field:
            self.entries[-1][self._field] += data

def faq_entries(body: str) -> list[dict]:
    return _entries(_FaqEntries(), body, "faq", ("question", "answer"), "a FAQ entry has no question or answer")

def _faq_page(item: Mapping, origin: str, entries: list[dict]) -> dict:
    """The page's visible FAQ as FAQPage structured data, for answer engines."""
    canonical = origin + item["surface"]
    return {"@type": "FAQPage", "@id": canonical + "#faq", "url": canonical, "inLanguage": item["locale"],
        "isPartOf": {"@id": canonical + "#webpage"},
        "mainEntity": [{"@type": "Question", "name": entry["question"],
        "acceptedAnswer": {"@type": "Answer", "text": entry["answer"]}} for entry in entries]}

def _defined_term_set(item: Mapping, origin: str, entries: list[dict]) -> dict:
    """The glossary as a DefinedTermSet: one DefinedTerm per entry, at the entry's own anchor."""
    canonical = origin + item["surface"]
    terms = [{**_defined_term(canonical, entry), "description": entry["text"]} for entry in entries]
    return {"@type": "DefinedTermSet", "@id": canonical + "#terms", "url": canonical, "name": item["title"].split("｜")[0],
        "inLanguage": item["locale"], "hasDefinedTerm": terms}

# An article's sources: each `li` of its `section.ar-refs` list as a CreativeWork, the entry's first link its url.  Read
# from the rendered page so a new article's sources need no second copy.
_REFS_SECTION = re.compile(r'<section class="ar-refs"[^<>]*>(.*?)</section>', re.DOTALL)
_REF_ITEM = re.compile(r'<li id="(ref-\d+)">(.*?)</li>', re.DOTALL)
_FIRST_LINK = re.compile(r'<a href="([^"]+)"')
# A span whose class list holds the token rs, with at most one level of span nested inside it.
_READING_MARK = re.compile(r'<span class="(?:[^"]*\s)?rs(?:\s[^"]*)?"[^>]*>(?:<span\b.*?</span>|.)*?</span>', re.DOTALL)
# The reading level that marks a source as the site's own calculation.
COMPUTED_READING_LABEL = "rs-computed"

def _plain(markup: str) -> str:
    from scripts.frontend.discovery import plain_text
    return re.sub(r"\s+", " ", plain_text(markup)).strip()

def article_source_links(body: str) -> list[dict]:
    """An article's numbered sources: anchor, first link and whether it is marked as the site's own calculation."""
    sections = _REFS_SECTION.findall(body)
    if len(sections) > 1:
        raise ValueError("an article has more than one section.ar-refs")
    items = _REF_ITEM.findall(sections[0]) if sections else []
    if sections and len(re.findall(r"<li\b", sections[0])) != len(items):
        raise ValueError("article source list is not numbered ref-1..")
    sources = []
    for anchor, markup in items:
        link = _FIRST_LINK.search(markup)
        sources.append({"id": anchor, "href": html.unescape(link.group(1)) if link else None,
            "computed": COMPUTED_READING_LABEL in markup, "text": _plain(_READING_MARK.sub("", markup))})
    if any(not source["text"] for source in sources):
        raise ValueError("an article source has no text")
    return sources

def _citation(canonical: str, origin: str, source: Mapping) -> dict:
    work = {"@type": "CreativeWork", "@id": f"{canonical}#{source['id']}", "name": source["text"]}
    href = source["href"]
    if href is not None and href.startswith(("https://", "http://")):
        work["url"] = href
    elif href is not None and href.startswith("/"):
        work["url"] = origin + href
    return work

# The glossary's terms an article names: `about` those its headline names, `mentions` those its text names.  Terms match
# by name and by each part of a name joined with ／ or 與; single characters (界, 陷, 廟) never match, since they occur
# inside unrelated words.  恆星 and 行星時 are ordinary words as often as terms, so only a headline names them.
GLOSSARY_SURFACE = f"/{DEFAULT_LOCALE}/methods/glossary"
GLOSSARY_FRAGMENT = "methods-glossary"
_TERM_PART = re.compile(r"\s*(?:／|與)\s*")
_HEADLINE_ONLY_TERMS = frozenset({"fixed_stars", "planetary_hours"})

def _glossary_terms() -> list[dict]:
    body = (build_pages.PAGES / f"{GLOSSARY_FRAGMENT}.html").read_text(encoding="utf-8")
    terms = []
    for entry in glossary_entries(body):
        parts = {entry["term"], *_TERM_PART.split(entry["term"])}
        terms.append({**entry, "parts": sorted(part for part in parts if len(part) >= 2)})
    return terms

def _names_term(text: str, term: Mapping) -> bool:
    return any(part in text for part in term["parts"])

def _defined_term(glossary: str, term: Mapping) -> dict:
    url = f"{glossary}#{term['id']}"
    node = {"@type": "DefinedTerm", "@id": url, "url": url, "name": term["term"],
        "inDefinedTermSet": {"@id": glossary + "#terms"}}
    if term["en"]:
        node["alternateName"] = term["en"]
    return node

def article_terms(headline: str, body: str) -> tuple[list[dict], list[dict]]:
    text = _plain(body)
    terms = _glossary_terms()
    about = [term for term in terms if _names_term(headline, term)]
    mentions = [term for term in terms if term not in about and term["id"] not in _HEADLINE_ONLY_TERMS
                and _names_term(text, term)]
    return about, mentions

# A list marked with the class `howto` is a HowTo, named by the nearest heading or `summary` before it, each item a
# step.  Only a real procedure carries the class.
_HOWTO_LIST = re.compile(r'<(ol|ul) class="(?:[^"]* )?howto(?: [^"]*)?"[^<>]*>(.*?)</\1>', re.DOTALL)
_HOWTO_NAME = re.compile(r"<(h2|h3|summary)\b[^<>]*>(.*?)</\1>", re.DOTALL)
_SECTION_NUMBER = re.compile(r"<span\b[^<>]*>\s*§?\d+\s*</span>")
_LIST_ITEM = re.compile(r"<li\b[^<>]*>(.*?)</li>", re.DOTALL)

def howto_lists(body: str) -> list[dict]:
    lists = []
    for match in _HOWTO_LIST.finditer(body):
        names = list(_HOWTO_NAME.finditer(body, 0, match.start()))
        if not names:
            raise ValueError("a howto list has no heading before it")
        if re.search(r"<(?:ol|ul)\b", match.group(2)):
            raise ValueError("a howto list holds a nested list")
        steps = [_plain(item) for item in _LIST_ITEM.findall(match.group(2))]
        name = _plain(_SECTION_NUMBER.sub("", names[-1].group(2)))
        if len(steps) < 2 or not all(steps) or not name:
            raise ValueError(f"a howto list needs a name and at least two steps: {name!r}")
        lists.append({"name": name, "steps": steps})
    return lists

def _howto(canonical: str, locale: str, index: int, howto: Mapping) -> dict:
    return {"@type": "HowTo", "@id": f"{canonical}#howto-{index}", "name": howto["name"], "inLanguage": locale,
        "isPartOf": {"@id": canonical + "#webpage"},
        "step": [{"@type": "HowToStep", "position": position, "text": text} for position,
        text in enumerate(howto["steps"], start=1)]}

# The methods page's source register is a downloadable dataset: the JSON every calculation receipt names by version and
# hash; the version is read from the file.
METHODS_SURFACE = f"/{DEFAULT_LOCALE}/methods"
METHOD_SOURCES_PATH = f"/{DEFAULT_LOCALE}/method-sources.json"
METHOD_SOURCES_DESCRIPTION = ("渾儀每一條計算規則的出處登記（JSON，內文為英文）：規則套用到哪個輸出、依據哪個文本與版本、" "章節或頁碼，以及本站核到哪一層。計算收據記下這份清單的版本與雜湊。")

def _method_sources_dataset(origin: str) -> dict:
    path = build_pages.ROOT / "frontend" / METHOD_SOURCES_PATH.lstrip("/")
    record = json.loads(path.read_text(encoding="utf-8"))
    url = origin + METHOD_SOURCES_PATH
    return {"@type": "Dataset", "@id": url + "#dataset", "name": "方法出處清單", "description": METHOD_SOURCES_DESCRIPTION,
        "url": url, "version": str(record["version"]), "inLanguage": "en", "isAccessibleForFree": True,
        "publisher": {"@id": origin + ORGANIZATION_ID},
        "distribution": {"@type": "DataDownload", "contentUrl": url, "encodingFormat": "application/json"}}

def _json_ld(item: dict, origin: str, headline: str | None = None,
             updated: str | None = None, body: str | None = None) -> str:
    canonical = origin + item["surface"]
    labels = build_pages.footer_link_labels()
    graph: list[dict] = [
        {
            "@type": "WebSite",
            "@id": origin + "/#website",
            "url": origin + "/",
            "name": build_pages.SITE_NAME,
            "alternateName": build_pages.SITE_NAME.split(" "),
            "inLanguage": item["locale"],
            "publisher": {"@id": origin + ORGANIZATION_ID},
        },
        {
            "@type": "WebPage",
            "@id": canonical + "#webpage",
            "url": canonical,
            "name": item["title"],
            "description": item["description"],
            "inLanguage": item["locale"],
            "isPartOf": {"@id": origin + "/#website"},
            "isAccessibleForFree": True,
        },
        _organization(origin),
    ]
    if updated is not None:
        # The page's recorded lastmod.  No datePublished: only an article has a recorded first-publication date.
        graph[1]["dateModified"] = updated
    # The calculator's sub-pages (the time-lord landing pages) describe the same application.
    surfaces = build_pages.load_surface_manifest()["surfaces"]
    application = item["surface"] in APPLICATION_SURFACES or parent_surface(item, surfaces) == CALCULATE_SURFACE
    if application:
        home = item if item["surface"] == build_pages.HOME_SURFACE else next(
            row for row in surfaces if row["surface"] == build_pages.HOME_SURFACE
        )
        graph.append(_web_application(origin, home))
        graph.append(_source_code(origin))
        graph[1]["about"] = {"@id": origin + APPLICATION_ID}
    if item["surface"] != build_pages.HOME_SURFACE:
        # A trail is home and the page; an article's is home, the blog and its headline; a sub-page's is home, its
        # parent and its headline.
        trail = [(build_pages.HOME_SURFACE, labels.get(build_pages.HOME_SURFACE))]
        parent = BLOG_SURFACE if is_article(item) else parent_surface(item, surfaces)
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
    questions = faq_entries(body) if body is not None else []
    if questions:
        graph.append(_faq_page(item, origin, questions))
    for index, howto in enumerate(howto_lists(body) if body is not None else [], start=1):
        graph.append(_howto(canonical, item["locale"], index, howto))
    if item["surface"] == METHODS_SURFACE:
        graph.append(_method_sources_dataset(origin))
    if is_article(item):
        # The byline names a person; the structured data names none.
        post = {"@type": "BlogPosting", "@id": canonical + "#article", "url": canonical, "headline": headline,
            "description": item["description"], "datePublished": item["article"]["published"],
            "dateModified": item["article"]["modified"], "inLanguage": item["locale"],
            "mainEntityOfPage": {"@id": canonical + "#webpage"},
            "isPartOf": {"@id": origin + BLOG_SURFACE + "#webpage"}, "publisher": {"@id": origin + ORGANIZATION_ID},
            "author": {"@id": origin + ORGANIZATION_ID}}
        post["isAccessibleForFree"] = True
        image = build_pages.og_image_url(origin)
        if image is not None:
            post["image"] = image
        if body is not None:
            # The article's source list for answer engines: each source a CreativeWork at its anchor.
            sources = article_source_links(body)
            if sources:
                post["citation"] = [_citation(canonical, origin, source) for source in sources]
            if any(source["computed"] for source in sources):
                post["isBasedOn"] = {"@type": "WebApplication", "@id": origin + APPLICATION_ID, "name": build_pages.SITE_NAME,
                    "url": origin + build_pages.HOME_SURFACE}
            about, mentions = article_terms(headline or "", body)
            glossary = origin + GLOSSARY_SURFACE
            if about:
                post["about"] = [_defined_term(glossary, term) for term in about]
            if mentions:
                post["mentions"] = [_defined_term(glossary, term) for term in mentions]
        graph.append(post)
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).replace("<", "\\u003c")

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
        "site_name": html.escape(build_pages.SITE_NAME, quote=True),
        "title": html.escape(item["title"], quote=True),
        "description": html.escape(item["description"], quote=True),
        "canonical": html.escape(canonical, quote=True),
        "surface": html.escape(
            f"{item['surface']} · {' ＋ '.join(item['layers'])}", quote=True
        ),
        "json_ld": _json_ld(item, origin, headline, updated, body),
    }
