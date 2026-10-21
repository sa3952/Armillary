"""The discovery files the page build writes beside the pages: robots.txt,
the sitemap, llms.txt and llms-full.txt, and the Atom feed.  Paths and shared
helpers are read from build_pages at call time."""

from __future__ import annotations

from collections.abc import Mapping
import html
from html.parser import HTMLParser
from pathlib import Path
import re
from xml.sax.saxutils import escape as xml_escape

from scripts.frontend import build_pages
from scripts.frontend.page_checks import BLOG_SURFACE, is_article, parent_surface
from scripts.frontend.site_locale import DEFAULT_LOCALE

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
        f"Disallow: {build_pages.API_PATH_PREFIX}",
        "Allow: /",
        "",
        f"Sitemap: {origin}/sitemap.xml",
        "",
    ])


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
            [link.group("href") for link in build_pages._FOOTER_LINK.finditer(match.group("links"))],
        )
        for match in _FOOTER_COLUMN.finditer(build_pages._footer(shell))
    ]


def _anchor_label(fragment: str, href: str) -> str:
    """The visible text of the one link to `href` on a page fragment."""

    body = (build_pages.PAGES / f"{fragment}.html").read_text(encoding="utf-8")
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

    shell = build_pages.SHELL.read_text(encoding="utf-8") if shell is None else shell
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
REQUIREMENTS = build_pages.ROOT / "backend" / "requirements.txt"
LLMS_KNOWN_LIMITATIONS_PATH = "/blob/main/docs/KNOWN_LIMITATIONS.md"
LLMS_PRIVACY_CHECK_SURFACE = f"/{DEFAULT_LOCALE}/security/verify"


def pinned_version(package: str, requirements: Path | None = None) -> str:
    text = (REQUIREMENTS if requirements is None else requirements).read_text(encoding="utf-8")
    pins = re.findall(rf"^{re.escape(package)}==(\S+)$", text, re.MULTILINE)
    if len(pins) != 1:
        raise ValueError(f"backend requirements pin {package} {len(pins)} times")
    return pins[0]


def _license_id() -> str:
    return build_pages.LICENSE_URL.rsplit("/", 1)[1].removesuffix(".html")


def llms_facts(origin: str, by_surface: Mapping[str, dict]) -> list[str]:
    houses = build_pages._backend("domain_catalog").HOUSE_SYSTEMS
    if set(houses) != set(build_pages.LLMS_HOUSE_SYSTEM_ORDER):
        raise ValueError("llms.txt house-system order does not match the backend's table")
    repository = build_pages._backend("frontend_release").PUBLIC_REPOSITORY_URL
    license_id = _license_id()
    facts: tuple[tuple[str, str], ...] = (
        ("授權", f"{license_id}（{build_pages.LICENSE_URL}）"),
        ("原始碼", repository),
        ("計算引擎", f"Swiss Ephemeris（pyswisseph {pinned_version('pyswisseph')}）"),
        ("宮位制", "、".join(houses[code] for code in build_pages.LLMS_HOUSE_SYSTEM_ORDER)),
        ("時間主星", build_pages.time_lord_series() + "；只列哪一段時間由哪顆行星或哪個星座輪值"),
        ("本命盤", "；".join(zh for _, zh, _ in build_pages.natal_features())),
        ("狀態", f"公開測試（Public Alpha），自{build_pages.PUBLIC_ALPHA_START.isoformat()}起"),
        ("已知限制（英文）", repository + LLMS_KNOWN_LIMITATIONS_PATH),
        ("方法頁全文與文章重點（純文字）", f"{origin}/{build_pages.LLMS_FULL_NAME}"),
    )
    check = by_surface.get(LLMS_PRIVACY_CHECK_SURFACE)
    if check is not None and check["indexable"]:
        facts += (("親手驗證隱私", origin + LLMS_PRIVACY_CHECK_SURFACE),)
    return [f"- {label}：{value}" for label, value in facts]


# What sets the site apart, each stated as a checkable fact and linked to the
# page that shows the evidence; a line whose page is not published is left
# out.  The reading levels are the legend's own labels (SOURCE_LEVELS).
LLMS_STRENGTHS: tuple[tuple[str, str, str], ...] = (
    ("精度核對", f"/{DEFAULT_LOCALE}/validation",
     "天體位置逐組與 JPL DE442、JPL Horizons 比對，日食、恆星時、宮位、回歸時刻與時區換算另以 NASA、USNO "
     "與獨立算法核對；驗證頁列出每組的範圍、樣本、最大差與重現方法，也寫明證明不了什麼"),
    ("計算收據", f"/{DEFAULT_LOCALE}/blog/verify-chart-calculation",
     "每張星盤附計算收據：時間怎麼換算、用了哪一版程式與哪些星曆檔、逐步計算軌跡與它的雜湊；"
     "匯出的卷宗可以交給別人重算比對"),
    ("不向第三方發出請求", LLMS_PRIVACY_CHECK_SURFACE,
     "網頁只向本站自己的網域要資源與送出計算；沒有第三方字型、CDN、分析或追蹤程式，"
     "內容安全政策（CSP）的 connect-src 只允許本站；這一頁教你用瀏覽器自己檢查"),
    ("方法與出處", f"/{DEFAULT_LOCALE}/methods",
     "每一條計算規則寫明方法版本、來歷與來源狀態；完整出處在 method-sources.json"),
)
LLMS_READING_LEVELS_SURFACE = BLOG_SURFACE


def llms_strengths(origin: str, by_surface: Mapping[str, dict]) -> list[str]:
    lines = [
        f"- {label}：{text}（{origin}{surface}）"
        for label, surface, text in LLMS_STRENGTHS
        if surface in by_surface and by_surface[surface]["indexable"]
    ]
    levels = list(dict.fromkeys(label for _, label, _ in build_pages.SOURCE_LEVELS))
    lines.append(
        "- 出處讀取等級：每篇文章的出處逐則標明讀到哪一層——" + "、".join(levels)
        + f"——沒讀到原文就照實標出（{origin}{LLMS_READING_LEVELS_SURFACE}）"
    )
    return lines


# How the site asks to be cited; each line restates a boundary the site keeps
# (it calculates and does not interpret; a source is only as read as its
# label says).
LLMS_CITATION_GUIDANCE = (
    "引用時請寫站名「渾儀 Armillary」，連到該頁上面列出的網址；文章請一併寫標題與更新日期（見 llms-full.txt）。",
    "引用計算結果時，請同時寫出這次計算的條件：出生日期、時刻、時區、地點座標、宮位制與其他選項；"
    "條件不同，結果就不同。",
    "本站只計算，不解盤，也不預測；請不要把本站的數字或文章寫成本站對某張盤的解讀或預言。",
    "轉述古典文獻的說法時，請照文章出處標的讀取等級描述（例如「只見書目」表示本站沒有讀到原書）。",
    "方法上的問題請引用方法頁的對應段落，或 method-sources.json 裡的條目代碼。",
)


def _english_series(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def llms_english_summary() -> str:
    """The one English passage on a Chinese-only site, for crawlers that read
    English: what the site is, its boundary, the licence, no accounts or trackers."""

    return (
        "Armillary (渾儀) is a classical Western astrology calculator with a Traditional Chinese interface: "
        "enter a birth date, time and place to get a natal chart, with the method source and a calculation "
        "receipt for every number. It also computes the annual time lords: "
        + _english_series([en for _, _, en in build_pages.time_lord_techniques()])
        + ", listing which planet or sign rules each period. The natal chart covers "
        + _english_series([en for _, _, en in build_pages.natal_features()])
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
    boundary is quoted with it, the facts list (llms_facts) follows that, then
    the site's checkable strengths (llms_strengths) and how to cite it
    (LLMS_CITATION_GUIDANCE), and the English summary (llms_english_summary)
    closes the head.
    """

    origin = payload["origin"]
    by_surface = {item["surface"]: item for item in payload["surfaces"]}
    home = by_surface[build_pages.HOME_SURFACE]
    lines = [
        f"# {build_pages.SITE_NAME}", "", f"> {_markdown_text(home['description'])}", "",
        _markdown_text(footer_tagline(shell)) + "。", "",
        *llms_facts(origin, by_surface), "",
        "本站的特點（每一項都能在括號裡的頁面查證）：", "",
        *llms_strengths(origin, by_surface), "",
        "引用本站時：", "",
        *(f"- {line}" for line in LLMS_CITATION_GUIDANCE), "",
        llms_english_summary(), "",
    ]
    listed: set[str] = set()
    columns = footer_columns(shell)
    articles = [item for item in payload["surfaces"] if is_article(item) and item["indexable"]]
    if articles:
        # Articles are linked from the blog page, not the footer; they get a
        # section of their own, headed by the blog's footer label.
        columns.append((build_pages.footer_link_labels(shell)[BLOG_SURFACE], [item["surface"] for item in articles]))
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

    def handle_endtag(self, tag):
        if tag in _PLAIN_VOID_TAGS:
            return
        if self._skip:
            if self._skip[-1] == tag:
                self._skip.pop()
            return
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
        return build_pages._render_parts(item, origin)[0]

    by_key = {item["key"]: item for item in payload["surfaces"]}
    lines = [
        f"# {build_pages.SITE_NAME}：方法頁全文與文章重點", "",
        f"> {_markdown_text(by_key['home']['description'])}", "",
        f"這是 {origin}/llms.txt 的全文版：方法頁的全部文字、其他每一頁的摘要，以及每一篇已發表文章的摘要、開頭一段與重點，"
        "由網站的建置程式從頁面本身轉成純文字。圖表與表單沒有收錄；完整內容與出處請看各頁網址。", "",
    ]
    for key in LLMS_FULL_PAGE_KEYS:
        item = by_key[key]
        lines += [
            f"## {_markdown_text(item['title'])}", "",
            f"網址：{origin}{item['surface']}", "",
            plain_text(body(item)), "",
        ]
    lines += ["## 引用本站時", "", *(f"- {line}" for line in LLMS_CITATION_GUIDANCE), ""]
    # Every other published page by its title, address and description, so the
    # companion names the whole site, as llms.txt does.
    others = [item for item in payload["surfaces"]
              if item["indexable"] and not is_article(item) and item["key"] not in LLMS_FULL_PAGE_KEYS]
    if others:
        lines += ["## 其他頁面", ""]
    for item in others:
        lines += [
            f"### {_markdown_text(item['title'])}", "",
            f"網址：{origin}{item['surface']}", "",
            f"摘要：{_markdown_text(item['description'])}", "",
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


# feed.xml: an Atom feed (RFC 4287) of the published articles, newest first,
# each dated by its row's published and modified days (Taiwan midnight), the
# dates the article page and its structured data state.  No third party: the
# file is served from the site's own origin like the sitemap.
FEED_NAME = "feed.xml"


def _feed_time(day: str) -> str:
    return f"{day}T00:00:00+08:00"


def feed_text(payload: dict) -> str:
    origin = payload["origin"]
    articles = sorted((item for item in payload["surfaces"] if is_article(item) and item["indexable"]),
                      key=lambda item: (item["article"]["published"], item["surface"]), reverse=True)
    if not articles:
        raise ValueError("feed.xml: no published article")
    updated = max(item["article"]["modified"] for item in articles)
    suffix = f"｜{build_pages.SITE_NAME}"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="{xml_escape(payload["default_locale"])}">',
        f"  <title>{xml_escape(build_pages.SITE_NAME)} 文章</title>",
        f'  <link rel="self" type="application/atom+xml" href="{xml_escape(origin)}/{FEED_NAME}"/>',
        f'  <link rel="alternate" type="text/html" href="{xml_escape(origin)}/zh-TW/blog"/>',
        f"  <id>{xml_escape(origin)}/{FEED_NAME}</id>",
        f"  <updated>{_feed_time(updated)}</updated>",
        f"  <author><name>{xml_escape(build_pages.SITE_NAME)}</name></author>",
    ]
    for item in articles:
        url = xml_escape(origin + item["surface"])
        title = item["title"].removesuffix(suffix)
        lines += [
            "  <entry>",
            f"    <title>{xml_escape(title)}</title>",
            f'    <link rel="alternate" type="text/html" href="{url}"/>',
            f"    <id>{url}</id>",
            f"    <published>{_feed_time(item['article']['published'])}</published>",
            f"    <updated>{_feed_time(item['article']['modified'])}</updated>",
            f"    <summary>{xml_escape(item['description'])}</summary>",
            "  </entry>",
        ]
    lines += ["</feed>", ""]
    return "\n".join(lines)


def discovery_outputs(payload: dict, lastmod: dict) -> dict[Path, str]:
    assets = build_pages._frontend_assets_module()
    return {
        build_pages.ROOT / "frontend" / "robots.txt": robots_text(payload),
        build_pages.ROOT / "frontend" / "sitemap.xml": sitemap_text(payload, lastmod),
        build_pages.ROOT / "frontend" / "llms.txt": llms_text(payload),
        build_pages.ROOT / "frontend" / FEED_NAME: feed_text(payload),
        # Exactly the key, with no line end: an IndexNow engine compares the
        # file with the key it was sent.
        build_pages.ROOT / "frontend" / assets.INDEXNOW_KEY_FILE: assets.INDEXNOW_KEY,
    }
