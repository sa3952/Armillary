"""What the security page's self-check sub-page lists: the requests one
calculation makes and the headers each response carries.

Nothing here is a second list of the calculator's files.  The page assets are
read from the calculator page exactly as build_pages renders it (every
same-origin stylesheet, icon, script and lazily imported module it names, with
the content version stamped into its address); the API calls are the
calculator script's, written once below, and a browser test drives a real
calculation and fails when the requests it observes differ from the rows
printed here (frontend/tests/e2e/privacy-check.spec.cjs).  The cache directive
of each row and the security headers come from the application's own
definitions in backend/app/privacy_logging.py.

The fragment writes, each on a line of its own:

- ``{{calculation_requests:required|icons|optional}}``: one table row per request;
- ``{{network_panel_figure}}``: a schematic network panel drawn from the required rows;
- ``{{security_header_rows}}``: one table row per security header;

and, inline, ``{{calculation_request_count}}`` (the required rows) and
``{{public_repository_url}}``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import html
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import re
import textwrap
from urllib.parse import urlsplit


CALCULATE_KEY = "calculate"

# What each script the calculator page loads does, in the reader's words.  A
# script the page loads without a line here fails the build, so a new file
# cannot appear in the list undescribed.
SCRIPT_ROLES = {
    "labels.js": "代碼的中文名稱，結果與匯出共用",
    "client-context.js": "把錯誤代碼換成看得懂的說明與下一步",
    "exporters.js": "複製與下載檔案的內容，在你的瀏覽器裡產生",
    "privacy-lifecycle.js": "按「清除」或離開頁面時丟掉結果、中止請求",
    "options-catalogue.js": "進階選項的清單",
    "request-input.js": "檢查欄位、組出要送出的請求內容",
    "timezone-names.js": "服務接受的時區名稱，送出前先在本機檢查",
    "location-receipt.js": "地點收據：你選的地點與座標",
    "chart-glyphs.js": "星盤圖的符號（取自開源字型的輪廓，不另載字型）",
    "chart-wheel-aspects.js": "依回應的相位結果畫出星盤圖中央的相位線，在你的瀏覽器裡排版",
    "chart-wheel-model.js": "把回應裡的位置排成星盤圖，在你的瀏覽器裡計算版面",
    "chart-square.js": "把同一份位置依宮位排成方盤（方形的星盤），在你的瀏覽器裡計算版面",
    "chart-wheel.js": "畫出星盤圖、放大檢視與 SVG／PNG 下載，在你的瀏覽器裡產生",
    "timelords-model.js": "把年度回應整理成時間主星的時間軸、年表、行事曆檔與時間主星表，在你的瀏覽器裡計算版面",
    "timelords.js": (
        "畫出時間主星一區；按「排出時間主星」，或在「古典完整」模式勾著接著排出時算完星盤，才送出年度請求"
    ),
    "result-chapters.js": "三種模式各預先勾哪些選項、結果的每一區放在哪一章",
    "glossary.js": "名詞解釋的詞條與抽屜，不送出任何請求",
    "calculate.js": "頁面本身的程式：收表單、送出請求、畫出結果",
    "view-model.js": "把回應整理成畫面；第一次按「計算」時才載入",
}

# When the browser fetches each script calculate.js imports later instead of at
# open.  A deferred script without a line here fails the build.
MODULE_WHEN = {
    "chart-glyphs.js": "第一次操作表單時預先載入",
    "chart-wheel-aspects.js": "第一次操作表單時預先載入",
    "chart-wheel-model.js": "第一次操作表單時預先載入",
    "chart-square.js": "第一次操作表單時預先載入",
    "chart-wheel.js": "第一次操作表單時預先載入",
    "view-model.js": "第一次操作表單時預先載入",
    "timelords-model.js": "第一份結果畫出時",
    "timelords.js": "第一份結果畫出時",
}

# The calculator's own API calls (frontend/zh-TW/calculate.js `postJson`): the
# method, the address, whether one calculation always makes it, when it is
# sent and what it carries.
@dataclass(frozen=True)
class ApiCall:
    method: str
    url: str
    required: bool
    when: str
    carries: str


API_CALLS = (
    ApiCall(
        "POST", "/api/chart", True, "按下「計算」",
        "出生日期時間、座標、時區與你選的選項；回應是星盤與計算卷宗",
    ),
    ApiCall(
        "POST", "/api/places/search", False, "用地名搜尋地點",
        "你輸入的搜尋字串；回應是內建地名目錄裡的候選地點",
    ),
    ApiCall(
        "POST", "/api/time/convert", False, "在換算助手按「核對這個鐘面時間」",
        "出生日期、時刻與時區（不含座標）；回應是這個鐘面時間在當地的 UTC 偏移、規則出處與時區資料庫版本",
    ),
    ApiCall(
        "POST", "/api/chart?projection=detailed", False,
        "打開「技術細節與驗算資料」，或匯出時選「運算結果＋驗算資料」（「自訂」模式預設選它，算完就會取）",
        "與上一次「計算」相同的內容，請伺服器再算一次並附上完整驗算資料",
    ),
)

# A request the page lists only once a script the calculator loads sends it.
# The annual route is registered behind a deployment flag; its row appears the
# build the calculator's own code calls it (timelords.js), so the list never
# names a request no button sends, nor misses one a button does.
GATED_API_CALLS = (
    ApiCall(
        "POST", "/api/chart/annual?projection=page", False,
        "按「排出時間主星」，或在「古典完整」模式勾著「算完星盤後，接著排出時間主星」時算完星盤；"
        "之後每換到一個還沒取過月小限的年度，就再取那一年的月小限（同一個請求也帶回那一年"
        "所在大期的第二層）；捲到另一個大期或打開另一段十年時，再取那一段的第二層（黃道釋放的小期、十年期的第二層）",
        "與「計算」相同的出生資料，加上要查的年份、技法與十年期的起點；回應是一生的分期與那一年"
        "由哪顆行星或哪個星座輪值（小限、月小限、法達、黃道釋放、十年期）與計算卷宗",
    ),
)

# How the calculator's code sends a request (frontend/zh-TW/calculate.js
# `postJson`): the address is always a string literal at the call.
_POST_JSON_CALL = re.compile(r"""\bpostJson\(\s*["']([^"']+)["']""")


def sent_api_urls(sources: dict[str, str]) -> set[str]:
    """Every address a loaded script passes to `postJson`, by its literal."""

    return {url for text in sources.values() for url in _POST_JSON_CALL.findall(text)}


# What each header the application adds to every response means for the
# reader.  A header without a line here fails the build.
HEADER_MEANINGS = {
    "Content-Security-Policy": (
        "瀏覽器只准這個頁面從本站載入程式、樣式、圖片與連線（<span class=\"mono\">'self'</span>），"
        "<span class=\"mono\">connect-src 'self'</span> 讓頁面上的程式連不到其他網域；"
        "<span class=\"mono\">require-trusted-types-for 'script'</span> 與 "
        "<span class=\"mono\">trusted-types 'none'</span> 讓任何程式都不能把一段字串變成 HTML 或程式網址"
    ),
    "X-Content-Type-Options": "瀏覽器照標示的檔案類型處理，不自己猜",
    "Referrer-Policy": "你從本站點出去時，瀏覽器不告訴對方你從哪一頁來",
    "Permissions-Policy": "這個站不得使用相機、麥克風與定位，連詢問都不會跳出",
    "Cross-Origin-Opener-Policy": "別的網站開的視窗拿不到這個頁面的參照",
    "Cross-Origin-Embedder-Policy": "頁面只能嵌入明確允許被嵌入的資源",
    "Cross-Origin-Resource-Policy": "本站的檔案不給其他網站的頁面載入",
}

_KIND_LABELS = {
    "document": "頁面",
    "stylesheet": "樣式",
    "script": "程式",
    "module": "程式",
    "icon": "圖示",
    "fetch": "計算／查詢",
}


@dataclass(frozen=True)
class Request:
    method: str
    url: str
    kind: str
    what: str
    when: str
    cache_control: str
    group: str

    @property
    def name(self) -> str:
        """The last path segment with its query, as a network panel names it."""

        path, _, query = self.url.partition("?")
        segment = PurePosixPath(path).name or path
        return segment + (f"?{query}" if query else "")


class _References(HTMLParser):
    """Every address the calculator page makes the browser fetch, in order."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        rel = (values.get("rel") or "").split()
        if tag == "link" and "stylesheet" in rel:
            self.found.append(("stylesheet", values["href"]))
        elif tag == "link" and ({"icon", "apple-touch-icon"} & set(rel)):
            self.found.append(("icon", values["href"]))
        elif tag == "script" and values.get("src"):
            self.found.append(("script", values["src"]))
        if tag == "script":
            # calculate.js imports the scripts named in its data-* attributes later
            # (the chart scripts and view-model.js on the first submission, the time-lords pair once the
            # first result is drawn).
            self.found.extend(("module", value) for name, value in attrs
                              if name.startswith("data-") and value)


def page_references(calculate_page: str) -> list[tuple[str, str]]:
    parser = _References()
    parser.feed(calculate_page)
    for _, address in parser.found:
        if not address.startswith("/") or address.startswith("//"):
            raise ValueError(f"the calculator page names an address off this site: {address}")
    return parser.found


def _script_name(url: str) -> str:
    return PurePosixPath(url.partition("?")[0]).name


def _what(kind: str, url: str) -> str:
    if kind == "stylesheet":
        return "這一頁的樣式包"
    if kind == "icon":
        return "網站圖示"
    name = _script_name(url)
    if name not in SCRIPT_ROLES:
        raise ValueError(f"the calculator loads a script with no description: {name}")
    return SCRIPT_ROLES[name]


def calculation_requests(
    calculate_page: str,
    calculate_surface: str,
    cache_control: Callable[[str], str],
    script_source: Callable[[str], str],
) -> list[Request]:
    """The rows: the page, its assets in the order the page names them, then
    the API calls; grouped into what every calculation makes (`required`),
    what the browser may fetch for its tab icon (`icons`) and what only an
    action of yours sends (`optional`).

    `script_source` gives the text of a script the page loads, by its name;
    the API rows are checked against the addresses that code sends."""

    rows = [Request(
        "GET", calculate_surface, "document", "計算頁本身", "打開計算頁",
        cache_control(calculate_surface), "required",
    )]
    for kind, url in page_references(calculate_page):
        when = "打開計算頁"
        if kind == "module":
            if _script_name(url) not in MODULE_WHEN:
                raise ValueError(f"the calculator imports a script with no load time: {url}")
            when = MODULE_WHEN[_script_name(url)]
        group = "icons" if kind == "icon" else "required"
        if kind == "icon":
            when = "瀏覽器自己決定要不要拿"
        rows.append(Request("GET", url, kind, _what(kind, url), when, cache_control(url), group))
    used = {name for name in SCRIPT_ROLES}
    loaded = {_script_name(row.url) for row in rows if row.kind in {"script", "module"}}
    if used != loaded:
        raise ValueError(f"script descriptions name files the page does not load: {sorted(used - loaded)}")
    sent = sent_api_urls({name: script_source(name) for name in sorted(loaded)})
    undescribed = sent - {call.url for call in (*API_CALLS, *GATED_API_CALLS)}
    if undescribed:
        raise ValueError(f"the calculator sends a request with no description: {sorted(undescribed)}")
    stale = {call.url for call in API_CALLS} - sent
    if stale:
        raise ValueError(f"the list describes a request the calculator no longer sends: {sorted(stale)}")
    for call in (*API_CALLS, *(call for call in GATED_API_CALLS if call.url in sent)):
        rows.append(Request(
            call.method, call.url, "fetch", call.carries, call.when,
            cache_control(call.url), "required" if call.required else "optional",
        ))
    if len({(row.method, row.url) for row in rows}) != len(rows):
        raise ValueError("the calculator's request list names one request twice")
    return rows


def _cell_url(url: str) -> str:
    # Break opportunities after the path's slashes and before the version, so a
    # long address wraps inside its cell on a phone instead of widening the table.
    return html.escape(url).replace("/", "/<wbr>").replace("?", "<wbr>?")


def request_rows(rows: list[Request], group: str, indent: str) -> str:
    selected = [row for row in rows if row.group == group]
    if not selected:
        raise ValueError(f"no calculator request in group {group!r}")
    return "\n".join(
        f'{indent}<tr data-request="{html.escape(row.method)} {html.escape(row.url, quote=True)}" '
        f'data-cache-control="{html.escape(row.cache_control, quote=True)}">'
        f'<td class="mono">{html.escape(row.method)}</td>'
        f'<td class="mono val">{_cell_url(row.url)}</td>'
        f"<td>{html.escape(_KIND_LABELS[row.kind])}：{html.escape(row.what)}</td>"
        f"<td>{html.escape(row.when)}</td>"
        f'<td class="mono val">{html.escape(row.cache_control)}</td></tr>'
        for row in selected
    )


def header_rows(headers: dict[str, str], indent: str) -> str:
    missing = sorted(set(headers) - set(HEADER_MEANINGS))
    unused = sorted(set(HEADER_MEANINGS) - set(headers))
    if missing or unused:
        raise ValueError(f"security header meanings disagree with the headers: missing {missing}, unused {unused}")
    return "\n".join(
        f'{indent}<tr><td class="mono">{html.escape(name)}</td>'
        f'<td class="mono val">{html.escape(value)}</td>'
        f"<td>{HEADER_MEANINGS[name]}</td></tr>"
        for name, value in headers.items()
    )


# --- the schematic network panel ---------------------------------------------

_ROW_HEIGHT = 24
_PANEL_TOP = 198


def _text(x: float, y: float, value: str, cls: str, anchor: str | None = None) -> str:
    anchor_attr = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text class="{cls}" x="{x:g}" y="{y:g}"{anchor_attr}>{html.escape(value)}</text>'


def _callout(x: float, y: float, number: int) -> str:
    return (
        f'<circle class="vf-callout" cx="{x:g}" cy="{y:g}" r="11"/>'
        + _text(x, y + 4.5, str(number), "vf-callout-n", "middle")
    )


def _short(name: str) -> str:
    """A versioned name with its version cut to six digits, as narrow panels show."""

    return re.sub(r"\?v=([0-9a-f]{6})[0-9a-f]+", r"?v=\1…", name)


def network_panel_figure(rows: list[Request], host: str) -> str:
    """A drawn network panel, with numbered callouts for the steps the page
    lists: (1) the Network tab, (2) Preserve log, (3) the Domain column and
    (4) the calculation request.  Its rows are the required requests."""

    shown = [row for row in rows if row.group == "required"]
    width = 720
    height = _PANEL_TOP + 52 + _ROW_HEIGHT * len(shown) + 20
    chart = next(index for index, row in enumerate(shown) if row.kind == "fetch")
    parts = [
        f'<svg class="vf-svg" viewBox="0 0 {width} {height}" role="img" aria-label="'
        "開發者工具 Network 分頁的示意圖，不是截圖。上方是計算頁，下方是開發者工具。"
        "編號 1 是 Network 分頁，編號 2 是 Preserve log 勾選框，編號 3 是 Domain 欄，"
        "編號 4 是按下「計算」送出的那一筆 POST /api/chart。"
        f'清單共 {len(shown)} 列，每一列的網域都是 {html.escape(host, quote=True)}。">',
        f'<rect class="vf-frame" x="1" y="1" width="{width - 2}" height="{height - 2}" rx="6"/>',
        '<rect class="vf-bar" x="1" y="1" width="718" height="34" rx="6"/>',
        '<circle class="vf-dot" cx="20" cy="18" r="5"/><circle class="vf-dot" cx="36" cy="18" r="5"/>'
        '<circle class="vf-dot" cx="52" cy="18" r="5"/>',
        '<rect class="vf-address" x="76" y="8" width="420" height="20" rx="4"/>',
        _text(88, 23, f"{host}/zh-TW/calculate", "vf-t vf-mono"),
        '<rect class="vf-page" x="12" y="46" width="696" height="92"/>',
        _text(28, 74, "計算頁", "vf-t"),
        '<rect class="vf-button" x="28" y="92" width="150" height="28" rx="2"/>',
        _text(103, 111, "載入合成範例", "vf-t-on vf-t-btn", "middle"),
        '<rect class="vf-button" x="190" y="92" width="80" height="28" rx="2"/>',
        _text(230, 111, "計算", "vf-t-on vf-t-btn", "middle"),
        '<rect class="vf-tools" x="12" y="148" width="696" height="' + str(height - 160) + '"/>',
    ]
    tabs = [("Elements", 24), ("Console", 104), ("Sources", 180), ("Network", 256), ("Application", 348)]
    for label, x in tabs:
        cls = "vf-t vf-mono vf-tab-on" if label == "Network" else "vf-t-dim vf-mono"
        parts.append(_text(x, 168, label, cls))
    parts.append('<line class="vf-accent-line" x1="252" y1="174" x2="318" y2="174"/>')
    parts.append(_callout(328, 163, 1))
    parts.append('<line class="vf-rule" x1="12" y1="180" x2="708" y2="180"/>')
    parts.append('<rect class="vf-check-on" x="24" y="186" width="12" height="12" rx="2"/>')
    parts.append('<path class="vf-tick" d="M26.5 192 l3 3 l5 -6"/>')
    parts.append(_text(42, 196, "Preserve log", "vf-t vf-mono"))
    parts.append('<rect class="vf-check" x="180" y="186" width="12" height="12" rx="2"/>')
    parts.append(_text(198, 196, "Disable cache", "vf-t-dim vf-mono"))
    parts.append(_callout(154, 192, 2))
    header_y = _PANEL_TOP + 22
    columns = [("Name", 24), ("Method", 330), ("Status", 396), ("Domain", 450), ("Type", 616)]
    parts.append(f'<rect class="vf-head" x="12" y="{_PANEL_TOP + 8}" width="696" height="20"/>')
    for label, x in columns:
        parts.append(_text(x, header_y, label, "vf-t-dim vf-mono"))
    parts.append(_callout(514, header_y - 4, 3))
    types = {"document": "document", "stylesheet": "stylesheet", "script": "script",
             "module": "script", "fetch": "fetch"}
    for index, row in enumerate(shown):
        y = _PANEL_TOP + 50 + _ROW_HEIGHT * index
        if index == chart:
            parts.append(f'<rect class="vf-row-on" x="12" y="{y - 16}" width="696" height="{_ROW_HEIGHT}"/>')
        parts.append(_text(24, y, _short(row.name), "vf-t vf-mono"))
        parts.append(_text(330, y, row.method, "vf-t vf-mono"))
        parts.append(_text(396, y, "200", "vf-t vf-mono"))
        parts.append(_text(450, y, host, "vf-t vf-mono"))
        parts.append(_text(616, y, types[row.kind], "vf-t-dim vf-mono"))
    parts.append(_callout(310, _PANEL_TOP + 50 + _ROW_HEIGHT * chart - 4, 4))
    parts.append("</svg>")
    return "\n".join(parts)


# --- filling the fragment ------------------------------------------------------

_ROWS = re.compile(r"^(?P<indent>[ \t]*)\{\{calculation_requests:(?P<group>[a-z]+)\}\}$", re.MULTILINE)
_FIGURE = re.compile(r"^(?P<indent>[ \t]*)\{\{network_panel_figure\}\}$", re.MULTILINE)
_HEADERS = re.compile(r"^(?P<indent>[ \t]*)\{\{security_header_rows\}\}$", re.MULTILINE)
PLACEHOLDER = re.compile(
    r"\{\{(calculation_requests:[a-z]+|calculation_request_count|network_panel_figure|"
    r"security_header_rows|public_repository_url)\}\}"
)


def fill(
    body: str,
    *,
    rows: Callable[[], list[Request]],
    host: str,
    headers: Callable[[], dict[str, str]],
    repository_url: Callable[[], str],
) -> str:
    if not PLACEHOLDER.search(body):
        return body
    listed = rows()
    body = _ROWS.sub(lambda match: request_rows(listed, match.group("group"), match.group("indent")), body)
    body, figures = _FIGURE.subn(
        lambda match: textwrap.indent(
            network_panel_figure(listed, host), match.group("indent")
        ),
        body,
    )
    if figures > 1:
        raise ValueError("{{network_panel_figure}} may appear once")
    body = _HEADERS.sub(lambda match: header_rows(headers(), match.group("indent")), body)
    body = body.replace(
        "{{calculation_request_count}}", str(sum(1 for row in listed if row.group == "required"))
    ).replace("{{public_repository_url}}", html.escape(repository_url(), quote=True))
    leftover = PLACEHOLDER.search(body)
    if leftover is not None:
        raise ValueError("a request-list placeholder must stand on a line of its own: " + leftover.group(0))
    return body


def host_of(origin: str) -> str:
    host = urlsplit(origin).hostname
    if not host:
        raise ValueError(f"origin has no host: {origin}")
    return host


def frontend_cache_control(privacy_logging, frontend_assets, frontend: Path) -> Callable[[str], str]:
    """The Cache-Control the application sends for an address of this tree,
    from its own decision function and content versions."""

    def version(path: str) -> str | None:
        file = frontend / path.lstrip("/")
        return frontend_assets.asset_content_version(file.read_bytes()) if file.is_file() else None

    def decide(url: str) -> str:
        path, _, query = url.partition("?")
        scope = {"type": "http", "path": path, "query_string": query.encode("ascii")}
        return privacy_logging._cache_control(scope, 200, "public_split", version)

    return decide
