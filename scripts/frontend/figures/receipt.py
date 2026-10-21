"""〈怎麼自己驗算一張星盤〉: figure 1 (the calculation receipt of one synthetic
chart, annotated) and figure 2 (the same request with one input changed: which
receipt lines and results change), with the numbers the prose quotes.

Figure 1 reads the committed test fixture `frontend/tests/fixtures/chart-exact.json`,
a real `projection=detailed` answer to the synthetic request filed under that name
in `chart-requests.json` (1990-05-15 14:30, 22.9908N 120.2133E, Asia/Taipei, not a
person's birth data).  Its rows are the result page's own: the fixture goes through
`view-model.js` (`buildSections`) in Node, and the figure prints the cells that
function returns.  The ephemeris file rows are the Dossier's `engine` record,
which the screen table does not print and the JSON export does.

Figure 2 sends that request, and three variants of it, to the application in
process.  The trace digest is the SHA-256 of the Python text of every float in
the trace, so it differs between the macOS and the Linux builds of Swiss
Ephemeris in the last bits (the chart fixtures' cross-platform float bound); a figure that
printed a digest computed here would differ between hosts.  So the only digest
it prints is the fixture's, and for each variant it prints whether the digest is
the same as the unchanged request's, computed on the same host, which holds on
every host.
"""
from __future__ import annotations

import copy
from html import escape
import json

from . import _fx
from ._common import ROOT, SIGNS, node_json, product_charts


FRAGMENT = "blog-verify-chart-calculation"
FIXTURES = ROOT / "frontend" / "tests" / "fixtures"
FIXTURE = FIXTURES / "chart-exact.json"
# Runs view-model.js from its readable sources, as the page tests do.
SCRIPT_BUNDLES = ROOT / "frontend" / "tests" / "script-bundles.cjs"

_NODE_SCRIPT = r"""
const ViewModel = require(process.argv[1]).load("view-model.js");
let input = "";
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const out = JSON.parse(input).map((response) => {
    const tables = {};
    for (const section of ViewModel.buildSections(response)) {
      if (section.id !== "receipt" && section.id !== "time") continue;
      for (const table of section.tables) tables[`${section.id}/${table.title}`] = table.rows;
    }
    return tables;
  });
  process.stdout.write(JSON.stringify(out));
});
"""


def rendered(responses: list[dict]) -> list[dict[str, dict[str, str]]]:
    """For each response, the result page's receipt and time tables:
    {"receipt/版本與來源": {label: cell}, …}, as view-model.js prints them."""
    found = node_json(_NODE_SCRIPT, SCRIPT_BUNDLES, stdin=responses, timeout=120,
                      what="read the receipt as the result page prints it")
    return [{name: {row[0]: row[1] for row in rows} for name, rows in tables.items()} for tables in found]


def request() -> dict:
    return json.loads((FIXTURES / "chart-requests.json").read_text(encoding="utf-8"))["chart-exact.json"]


def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- text width, for laying a row out on one line or two ------------------------

# --- figure 1: the receipt, annotated ------------------------------------------

GROUPS = (
    # key, number, heading, one-line annotation (wide: two lines)
    ("versions", "①", "版本與來源", ("哪一版程式、哪一版", "星曆函式庫算的")),
    ("time", "②", "時間換算", ("鐘面時間怎麼一步步", "換成天文計算用的時間")),
    ("files", "③", "星曆檔（在匯出的卷宗裡）", ("讀了哪幾個資料檔，", "位元組和釘選的一不一樣")),
    ("trace", "④", "軌跡收據", ("整串計算步驟的指紋：", "只要一步不同，它就不同")),
    ("privacy", "⑤", "隱私聲明", ("提醒你：這份收據", "含有出生資料")),
)


def receipt_data() -> dict:
    """Figure 1's rows, read from the fixture as the result page prints it."""
    response = fixture()
    (tables,) = rendered([response])
    versions = tables["receipt/版本與來源"]
    given = tables["receipt/已驗證的輸入（input receipt）"]
    trace = tables["receipt/軌跡收據"]
    privacy = tables["receipt/隱私聲明"]
    engine = response["calculation_dossier"]["engine"]
    files = [f for f in engine["available_input_files"] if f["required_for_this_request"]]
    if not files or not all(f["matches_pinned_sha256"] for f in files):
        raise RuntimeError("the fixture's required ephemeris files do not all match their pinned digests")
    digest = trace["序列化雜湊 SHA-256"]
    if digest != response["calculation_dossier"]["trace_receipt"]["python_json_serialization_sha256"]:
        raise RuntimeError("the receipt table does not print the trace receipt's digest")
    if trace["逐步軌跡步數"] != trace["後端回報步數"]:
        raise RuntimeError("the trace and the trace receipt count different steps")
    return {
        "versions": [(label, versions[label]) for label in
                     ("API schema", "Calculation Dossier", "建置識別", "pyswisseph", "Swiss Ephemeris")],
        "time": [(label, given[label]) for label in
                 ("本地時間", "時區", "UTC 偏移", "UTC", "儒略日 JD(UT)", "ΔT（秒）")],
        "files": [(f["filename"], f["sha256"]) for f in files],
        "steps": trace["逐步軌跡步數"],
        "digest": digest,
        "portable": trace["跨語言可攜"],
        "privacy": [(label, privacy[label]) for label in ("含敏感出生資料", "可匿名分享")],
        "lineage": engine["ephemeris_dataset_lineage"]["jpl_ephemeris_basis"],
        "trace_titles": [step["title"] for step in response["calculation_trace"]],
    }


def _group_rows(key: str, d: dict, bound: _fx.Bound) -> list[tuple[str, str]]:
    """(label, value) rows of one group; a digest is split over two rows."""
    if key == "files":
        return [(bound.num(name), bound.num(sha[:16]) + "…　" + "符合釘選值") for name, sha in d["files"]]
    if key == "trace":
        digest = bound.num(d["digest"])
        # Each printed half is its own number: a run of digits the split cuts in two
        # is two numbers on the page, neither of them the run the full digest holds.
        return [("逐步軌跡步數", bound.num(d["steps"])), (bound.label("SHA-256"), bound.num(digest[:32])),
                ("", bound.num(digest[32:])),
                ("跨語言可攜", d["portable"])]
    return [(label, bound.num(value)) for label, value in d[key]]


def _group_label(key: str, d: dict) -> str:
    heading = next(g[2] for g in GROUPS if g[0] == key)
    pairs = _group_rows(key, d, _fx.Bound())
    if key == "trace":
        pairs = [(label, d["digest"] if label == "SHA-256" else value) for label, value in pairs]
    rows = "；".join(f"{label} {value}" for label, value in pairs if label)
    return f"{heading}：{rows}"


def _receipt(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    small = 15.0 if wide else 12.0
    body: list[str] = []
    y = 64.0 if wide else 56.0
    for key, number, heading, note in GROUPS:
        rows = _group_rows(key, d, bound)
        top = y - (26 if wide else 22)
        part = [_fx.text(24 if wide else 16, y, number, "fx-t"),
                _fx.text(52 if wide else 40, y, heading, "fx-t")]
        if wide:
            part += [_fx.text(612, y, note[0], "fx-t fx-small fx-dim"),
                     _fx.text(612, y + 22, note[1], "fx-t fx-small fx-dim")]
            y += 30
        else:
            y += 20
            part.append(_fx.text(40, y, "".join(note), "fx-t fx-small fx-dim"))
            y += 22
        for label, value in rows:
            if wide:
                part.append(_fx.text(52, y, label, "fx-t fx-small"))
                part.append(_fx.text(262, y, value, "fx-t fx-small fx-num"))
                y += 25
            elif (label and key != "trace" or label == "逐步軌跡步數" or label == "跨語言可攜") \
                    and _fx.text_width(label, small, 0.56) + _fx.text_width(value, small, 0.56) + 14 <= W - 70:
                part.append(_fx.text(40, y, label, "fx-t fx-small"))
                part.append(_fx.text(W - 16, y, value, "fx-t fx-small fx-num", "end"))
                y += 20
            else:
                if label:
                    part.append(_fx.text(40, y, label, "fx-t fx-small"))
                    y += 18
                part.append(_fx.text(52, y, value, "fx-t fx-small fx-num"))
                y += 20
        bottom = y - (14 if wide else 12)
        hit = _fx.rect(10 if wide else 8, top, (590 if wide else W - 16) - (10 if wide else 8), bottom - top, "fx-hit")
        body.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{escape(_group_label(key, d))}">'
                    + hit + "".join(part) + "</g>")
        body.append(_fx.line(16 if wide else 12, bottom + 4, (594 if wide else W - 12), bottom + 4, "fx-hair"))
        y += 34 if wide else 30
    H = y - (22 if wide else 18)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        out.append(_fx.line(600, 20, 600, H - 20, "fx-hair"))
    out += body
    out.append("</svg>")
    # One group per line: the ephemeris rows and the trace digest never share a
    # line, so no reader pairs a file name with the trace's hash.
    return "\n".join(out)


def _receipt_table(d: dict, bound: _fx.Bound) -> str:
    rows = []
    for key, number, heading, _ in GROUPS:
        for label, value in _group_rows(key, d, bound):
            if key == "trace" and label in ("SHA-256", ""):
                if label == "":
                    continue
                label, value = "序列化雜湊 SHA-256", bound.num(d["digest"])
            if key == "files":
                label = f"{label}（SHA-256 開頭）"
            rows.append(f'<tr data-fx-key="{key}"><th scope="row">{number} {escape(label)}</th>'
                        f'<td class="fx-num">{escape(value)}</td></tr>')
    return _fx.data_table(("項目", "數值"), "\n" + "\n".join(rows) + "\n", summary="收據上的值（表格，軌跡雜湊不截短）")


def _receipt_notes(d: dict, bound: _fx.Bound) -> list[_fx.Note]:
    first = bound.num(d["files"][0][0])
    titles = d["trace_titles"]
    # The time note names trace steps 2 to 4: local time to UTC, UTC to Julian
    # day, ΔT.
    if not (titles[1].startswith("本地時間") and "儒略日" in titles[2] and "ΔT" in titles[3]):
        raise RuntimeError(f"trace steps 2-4 are not the time conversion: {titles[1:4]}")
    return [
        _fx.Note("versions", None,
                 f"API schema 與 Calculation Dossier 是回應與卷宗格式的版號，pyswisseph 與 Swiss Ephemeris "
                 f"是算位置的函式庫版本。這份範例是在本機產生的，所以建置識別寫「未提供」；線上的收據在這裡印出"
                 f"原始碼修訂與發布識別。"),
        _fx.Note("time", None,
                 f"你輸入的是鐘面時間；收據寫出它用的時區與 UTC 偏移、換成的 UTC、儒略日，以及這一刻地球自轉"
                 f"與均勻時間的差 ΔT。軌跡第 {bound.num('2')} 到第 {bound.num('4')} 步逐步寫出同一段換算。"),
        _fx.Note("files", None,
                 f"畫面上的收據只寫星曆譜系；匯出的卷宗另外列出每個星曆檔的大小、SHA-256，以及它和本站釘選的"
                 f"雜湊是否相符。{first} 是行星檔，雜湊相同代表位元組相同，不代表天文上正確。"),
        _fx.Note("trace", None,
                 f"軌跡共 {bound.num(d['steps'])} 步，從「{titles[0]}」到「{titles[-1]}」。SHA-256 是把整份軌跡"
                 f"照固定的 Python 寫法序列化之後算的；第一步就是你送出的全部選項，所以改任何一個選項，它都會變。"),
        _fx.Note("privacy", None,
                 "含敏感出生資料：是。收據與匯出的卷宗裡有出生日期、時刻與座標；伺服器不保存它，"
                 "但你下載或傳給別人之後，那一份就在你或對方手上。"),
    ]


def _receipt_figure(d: dict) -> str:
    bound = _fx.Bound()
    req = request()
    dt = req["datetime"]
    loc = req["location"]
    clock = f"{dt['hour']:02d}:{dt['minute']:02d}"
    caption = (
        f"<b>{bound.label('圖 1')}</b>一張合成星盤（不是任何人的出生資料：{bound.num(str(dt['year']))} 年 "
        f"{bound.num(str(dt['month']))} 月 {bound.num(str(dt['day']))} 日 {bound.num(clock)}，"
        f"北緯 {bound.num(str(loc['latitude']))} 度、東經 {bound.num(str(loc['longitude']))} 度，臺北時區）的計算收據，"
        "摘出五組。①②④⑤是結果頁「技術細節與驗算資料」裡〈計算收據〉印的原字，③是匯出的卷宗 JSON 裡的星曆檔紀錄；"
        "星曆檔的雜湊只印開頭，完整值在匯出的卷宗裡；軌跡雜湊在圖上分成兩行，表格裡是一整串。"
    )
    return _fx.figure(
        fid="fig-receipt",
        title="一張合成星盤的計算收據：版本、時間換算、星曆檔、軌跡雜湊與隱私聲明",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _receipt, "fig-receipt", d, bound,
            notes=_receipt_notes(d, bound),
            idle="用 Tab 鍵移到一組，或用滑鼠指著它，這裡會寫出那一組在說什麼。",
        ),
        table=_receipt_table(d, bound),
        bound=bound,
    )


# --- figure 2: change one input -------------------------------------------------

VARIANTS = (
    ("again", "原樣再算一次"),
    ("second", "出生時刻多一秒"),
    ("houses", "宮位制改成 Placidus"),
    ("option", "改一個沒用到的選項"),
)
ROWS = (
    ("local", "本地時間"),
    ("utc", "UTC"),
    ("jd", "儒略日 JD(UT)"),
    ("asc", "上升點"),
    ("cusp2", "第 2 宮起點"),
    ("steps", "軌跡步數"),
    ("digest", "軌跡雜湊"),
)
# The option figure 2 changes: the orb of declination aspects, which this
# request does not compute, so nothing but the trace's first step reads it.
UNUSED_OPTION = ("declination_aspect_orb_degrees", 2.0)


def _variant_request(variant: str) -> dict:
    req = copy.deepcopy(request())
    if variant == "second":
        req["datetime"]["second"] = req["datetime"]["second"] + 1
    elif variant == "houses":
        req["options"]["house_system"] = "P"
    elif variant == "option":
        req["options"][UNUSED_OPTION[0]] = UNUSED_OPTION[1]
    return req


def _sign_text(position: list) -> str:
    return f"{SIGNS[position[0]]}座 {position[1]}"


def diff_data() -> dict:
    """The unchanged request and each variant, answered by the product."""
    with product_charts() as post:
        base = post(request())
        answers = {variant: post(_variant_request(variant)) for variant, _ in VARIANTS}
    order = [base] + [answers[v] for v, _ in VARIANTS]
    tables = rendered(order)

    def row_values(response: dict, table: dict) -> dict:
        given = table["receipt/已驗證的輸入（input receipt）"]
        trace = table["receipt/軌跡收據"]
        division = response["derived_methods"]["house_division"]
        return {
            "local": given["本地時間"], "utc": given["UTC"], "jd": given["儒略日 JD(UT)"],
            "asc": _sign_text(response["astronomical_data"]["angles"]["sign_positions"]["asc"]),
            "cusp2": _sign_text(division["cusp_sign_positions"][1]),
            "steps": trace["逐步軌跡步數"],
            "digest": trace["序列化雜湊 SHA-256"],
            "system": division["system_name"],
            "asc_degrees": response["astronomical_data"]["angles"]["asc"],
            "asc_sign": response["astronomical_data"]["angles"]["sign_positions"]["asc"][0],
            "cusp2_sign": division["cusp_sign_positions"][1][0],
            "titles": [step["title"] for step in response["calculation_trace"]],
        }

    values = [row_values(r, t) for r, t in zip(order, tables, strict=True)]
    base_values = values[0]
    fixed = fixture()
    (fixed_table,) = rendered([fixed])
    fixed_values = row_values(fixed, fixed_table)
    # The fixture is the same request: every printed line but the digest (host
    # dependent, see the module docstring) must match what the product says now.
    for key, _ in ROWS:
        if key != "digest" and fixed_values[key] != base_values[key]:
            raise RuntimeError(f"the fixture's {key} {fixed_values[key]!r} != the product's {base_values[key]!r}")
    option_value = fixed["calculation_dossier"]["input_receipt"]["options"][UNUSED_OPTION[0]]
    out = {"base": {**base_values, "digest": fixed_values["digest"], "option_value": f"{option_value:g}"},
           "variants": {}}
    for (variant, _), v in zip(VARIANTS, values[1:], strict=True):
        moved = abs(v["asc_degrees"] - base_values["asc_degrees"]) * 3600
        out["variants"][variant] = {**v, "same_digest": v["digest"] == base_values["digest"],
                                    "asc_moved": f"{moved:.1f}"}
        del out["variants"][variant]["digest"]
    houses = out["variants"]["houses"]
    # The sentences on the house variant: its second cusp is still in the
    # ascendant's sign, and the whole-sign trace has one step the Placidus one lacks.
    if houses["cusp2_sign"] != houses["asc_sign"]:
        raise RuntimeError("the Placidus second cusp left the ascendant's sign")
    dropped = [t for t in base_values["titles"] if t not in houses["titles"]]
    if "月交點與月球拱點的整宮落宮" not in dropped or len(base_values["titles"]) - len(houses["titles"]) != 1:
        raise RuntimeError(f"the whole-sign trace no longer has the one extra step: {dropped}")
    expected = {"again": set(), "second": {"local", "utc", "jd", "asc", "digest"},
                "houses": {"cusp2", "steps", "digest"}, "option": {"digest"}}
    for variant, v in out["variants"].items():
        changed = {key for key, _ in ROWS if not _same(out["base"], v, key)}
        if changed != expected[variant]:
            raise RuntimeError(f"variant {variant!r} changes {sorted(changed)}, the prose says {sorted(expected[variant])}")
    return out


def _same(base: dict, variant: dict, key: str) -> bool:
    return variant["same_digest"] if key == "digest" else base[key] == variant[key]


def _shown(base: dict, variant: dict, key: str, bound: _fx.Bound) -> tuple[str, str]:
    """(原本, 這一次) cells of one row."""
    if key == "digest":
        return bound.num(base["digest"][:16]) + "…", "同一串" if variant["same_digest"] else "另一串"
    return bound.num(base[key]), bound.num(variant[key])


def _diff_sentence(variant: str, key: str, base: dict, v: dict, bound: _fx.Bound) -> str:
    label = dict(ROWS)[key]
    same = _same(base, v, key)
    if key == "digest":
        what = "同一串雜湊" if same else "雜湊整串換掉"
        why = {
            "again": "同一個輸入、同一版程式，算兩次得到同一串；所以兩份結果的雜湊相同，就代表兩次走過的每一步都一樣。",
            "second": "時刻多一秒，第二步以後的數字都跟著變，雜湊也就不同。",
            "houses": "宮位制換了，軌跡裡的宮位步驟換了，雜湊也就不同。",
            "option": (f"這個選項（赤緯相位的容許度，{bound.num(base['option_value'])} 度改成 "
                       f"{bound.num(f'{UNUSED_OPTION[1]:g}')} 度）這次沒有用到，"
                       "沒有任何結果改變；但它寫在軌跡第一步「請求選項」，所以雜湊不同。"),
        }[variant]
        return f"軌跡雜湊：{what}。{why}"
    if same:
        tail = {
            "again": "沒有改任何輸入。",
            "second": "這一列和出生時刻無關。" if key == "cusp2" else "",
            "houses": "宮位制不影響時間換算與上升點。" if key in ("local", "utc", "jd", "asc") else "",
            "option": "這個選項沒有用到，結果不變。",
        }[variant]
        if variant == "second" and key == "cusp2":
            tail = "整宮制的宮從星座的起點起算，上升點這一秒沒有離開原本的星座，所以不變。"
        if variant == "second" and key == "steps":
            tail = "步驟還是那幾步，只是每一步的數字不同。"
        return f"{label}：和原本相同，{bound.num(v[key])}。{tail}"
    change = f"{label}：從 {bound.num(base[key])} 變成 {bound.num(v[key])}。"
    why = {
        ("second", "local"): "這是唯一改動的輸入。",
        ("second", "utc"): "鐘面時間多一秒，換成的 UTC 也多一秒。",
        ("second", "jd"): "儒略日以「日」為單位，一秒約是十萬分之一日。",
        ("second", "asc"): f"地球在轉，這一秒上升點沿黃道走了約 {bound.num(v['asc_moved'])} 角秒。",
        ("houses", "cusp2"): (f"整宮制的第 {bound.label('2')} 宮從下一個星座的 0 度起算；{v['system']} 的宮頭由時間"
                              "三等分決定，這一刻的第二宮起點還在上升點的同一個星座裡。"),
        ("houses", "steps"): "整宮制多一步「月交點與月球拱點的整宮落宮」，換成 Placidus 就沒有這一步。",
    }[(variant, key)]
    return change + why


def _diff(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    base = d["base"]
    out_rows: list[str] = []
    if wide:
        head_y, y0, rh = 46.0, 92.0, 46.0
        cols = (40, 236, 480, 760)
        header = [_fx.text(cols[0], head_y, "收據與結果的一行", "fx-t fx-small fx-dim"),
                  _fx.text(cols[1], head_y, "原本", "fx-t fx-small fx-dim"),
                  _fx.text(cols[2], head_y, "改了一個輸入之後", "fx-t fx-small fx-dim"),
                  _fx.text(cols[3], head_y, "比較", "fx-t fx-small fx-dim", "middle")]
        for i, (key, label) in enumerate(ROWS):
            y = y0 + i * rh
            cells = []
            for variant, _ in VARIANTS:
                v = d["variants"][variant]
                old, new = _shown(base, v, key, bound)
                same = _same(base, v, key)
                cells.append(_fx.variant_group(variant, VARIANTS[0][0], (
                    _fx.text(cols[2], y, new, "fx-t fx-small fx-num")
                    + _fx.rect(cols[3] - 44, y - 21, 88, 30, "fx-fill-blank" if same else "fx-fill-cross")
                    + _fx.text(cols[3], y, "相同" if same else "不同", "fx-t fx-small fx-key", "middle"))))
            old, _ = _shown(base, d["variants"]["again"], key, bound)
            out_rows.append(
                f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{escape(label)}">'
                + _fx.rect(16, y - 30, W - 32, rh - 2, "fx-hit")
                + _fx.text(cols[0], y, bound.label(label), "fx-t fx-small")
                + _fx.text(cols[1], y, old, "fx-t fx-small fx-num") + "".join(cells) + "</g>")
            out_rows.append(_fx.line(24, y + 14, W - 24, y + 14, "fx-hair"))
        H = y0 + len(ROWS) * rh + 6
    else:
        header = [_fx.text(16, 30, "每一列：原本／改了之後", "fx-t fx-small fx-dim")]
        y0, rh = 62.0, 76.0
        for i, (key, label) in enumerate(ROWS):
            y = y0 + i * rh
            cells = []
            for variant, _ in VARIANTS:
                v = d["variants"][variant]
                _, new = _shown(base, v, key, bound)
                same = _same(base, v, key)
                cells.append(_fx.variant_group(variant, VARIANTS[0][0], (
                    _fx.text(70, y + 44, new, "fx-t fx-small fx-num")
                    + _fx.rect(W - 74, y - 17, 58, 24, "fx-fill-blank" if same else "fx-fill-cross")
                    + _fx.text(W - 45, y, "相同" if same else "不同", "fx-t fx-small fx-key", "middle"))))
            old, _ = _shown(base, d["variants"]["again"], key, bound)
            out_rows.append(
                f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{escape(label)}">'
                + _fx.rect(8, y - 22, W - 16, rh - 4, "fx-hit")
                + _fx.text(16, y, bound.label(label), "fx-t")
                + _fx.text(16, y + 22, "原本", "fx-t fx-small fx-dim")
                + _fx.text(70, y + 22, old, "fx-t fx-small fx-num")
                + _fx.text(16, y + 44, "改了", "fx-t fx-small fx-dim")
                + "".join(cells) + "</g>")
            out_rows.append(_fx.line(12, y + 56, W - 12, y + 56, "fx-hair"))
        H = y0 + len(ROWS) * rh - 6
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H), *header, *out_rows, "</svg>"]
    return "".join(out)


def _diff_table(d: dict, bound: _fx.Bound) -> str:
    base = d["base"]
    rows = []
    for key, label in ROWS:
        cells = []
        for variant, _ in VARIANTS:
            v = d["variants"][variant]
            _, new = _shown(base, v, key, bound)
            mark = "" if _same(base, v, key) else "（不同）"
            cells.append(f'<td class="fx-num">{escape(new)}{mark}</td>')
        old, _ = _shown(base, d["variants"]["again"], key, bound)
        rows.append(f'<tr data-fx-key="{key}"><th scope="row">{escape(label)}</th>'
                    f'<td class="fx-num">{escape(old)}</td>{"".join(cells)}</tr>')
    return _fx.data_table(("項目", "原本", *(escape(name) for _, name in VARIANTS)), rows,
                          summary="四種改法的每一列（表格）")


def _diff_figure(d: dict) -> str:
    bound = _fx.Bound()
    notes = [_fx.Note(key, variant, _diff_sentence(variant, key, d["base"], d["variants"][variant], bound))
             for key, _ in ROWS for variant, _ in VARIANTS]
    caption = (
        f"<b>{bound.label('圖 2')}</b>把{bound.label('圖 1')} 那個請求送給本站的計算服務，再分別改一個輸入送一次。"
        "按鈕選改法，右欄的排線格是和原本不同的那幾列。「原樣再算一次」每一列都相同，雜湊也相同；"
        "只改一個沒有用到的選項，所有數字都不變，只有雜湊不同。圖上的雜湊只比相同或不同：同一個請求在不同的電腦上"
        "算，雜湊可能不一樣（見內文），所以這裡只印出圖 1 那一份的開頭。"
    )
    return _fx.figure(
        fid="fig-receipt-diff",
        title="改一個輸入，收據上哪幾行會變",
        caption=caption,
        art=_fx.FigureArt.drawn(
            _diff, "fig-receipt-diff", d, bound,
            notes=notes,
            idle="選一種改法，再用 Tab 鍵移到一列，或用滑鼠指著它，這裡會寫出那一列為什麼變或不變。",
        ),
        controls=_fx.FigureControls(
            variants=VARIANTS,
            switch_label="選一種改法",
        ),
        table=_diff_table(d, bound),
        bound=bound,
    )


def _zh_arcsec(value: str) -> str:
    """「十幾」: how the prose says the ascendant's one-second move."""
    whole = int(float(value))
    if not 10 <= whole < 20:
        raise RuntimeError(f"the prose says the ascendant moved 「十幾」 arcseconds, the product says {value}")
    return "十幾"


def build() -> tuple[dict[str, str], list[str]]:
    d = receipt_data()
    diff = diff_data()
    time = dict(d["time"])
    loc = request()["location"]
    quoted = [
        f"軌跡共 {d['steps']} 步",
        f"Swiss Ephemeris {dict(d['versions'])['Swiss Ephemeris']}",
        f"JPL {d['lineage']}",
        f"{d['files'][0][0]}、{d['files'][1][0]}",
        f"「{d['trace_titles'][0]}」",
        escape(f"「{d['trace_titles'][1]}」"),
        f"（這張是 {time['UTC 偏移']}）",
        f"這張是 {time['儒略日 JD(UT)']}",
        f"這張是 {time['ΔT（秒）']} 秒",
        f"北緯 {loc['latitude']} 度、東經 {loc['longitude']} 度",
        f"走了{_zh_arcsec(diff['variants']['second']['asc_moved'])}角秒",
    ]
    return {
        "fx-defs": _fx.defs(()),
        "receipt": _receipt_figure(d),
        "receipt-diff": _diff_figure(diff),
    }, quoted
