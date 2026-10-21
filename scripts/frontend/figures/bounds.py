"""〈四套界表，四個答案〉: the Aries, Leo and Libra bounds figures (figures 1, 3
and 4) and the degree-by-degree agreement figure (figure 2) with the counts the
prose quotes, read from the tables the product computes with
(backend/app/core/dignity_tables.py and essential_dignities.py).  The Leo row
Lilly's bounds had before the transcription was corrected is the one the
product's source details keep (`previous_recorded_row`).

The bounds figures are article figures (`_fx`): a row per table, each bound a
strip as wide as its degrees, filled by its ruler, with the ruler's glyph and
Chinese name and its length written on it.  Pointing at a row writes every
bound of that row with its degree range.
"""
from __future__ import annotations

from html import escape
import re
from typing import Any

from . import _fx
from ._common import backend_on_path


FRAGMENT = "blog-four-bounds-tables"
NAMES = {"saturn": "土星", "jupiter": "木星", "mars": "火星", "venus": "金星", "mercury": "水星"}
SHORT = {key: name[0] for key, name in NAMES.items()}
# Five rulers, five engravings, so a ruler is found again in the next row
# without colour: solid, cross hatch, single hatch, dots, bare paper.
FILLS = {"saturn": "fx-fill-solid", "mars": "fx-fill-cross", "jupiter": "fx-fill-hatch", "venus": "fx-fill-dot",
         "mercury": "fx-fill-blank"}
SIGN_KEYS = ("aries", "taurus", "gemini", "cancer", "leo", "virgo", "libra", "scorpio", "sagittarius",
             "capricorn", "aquarius", "pisces")
EGYPTIAN, CHALDAEAN = "egyptian_bounds_robbins_1940_v1", "chaldaean_bounds_ptolemy_i_21_v1"
PTOLEMY, LILLY = "ptolemy_bounds_robbins_1940_v1", "lilly_received_bounds_1647_v1"
IDLE = "用 Tab 鍵移到一列上，或用滑鼠指著它，這裡會寫出那一套表每一段的界主與度數範圍。"


def _ranges(segments) -> list[tuple[str, int, int]]:
    out, start = [], 0
    for ruler, width in segments:
        out.append((ruler, start, start + width))
        start += width
    if start != 30:
        raise RuntimeError(f"a bounds row sums to {start}°, not 30°")
    return out


def _sentence(row: dict, bound: _fx.Bound) -> str:
    parts = "，".join(f"{NAMES[r]} {bound.num(f'{a}°–{b}°')}" for r, a, b in _ranges(row["segments"]))
    text = f"{row['name']}（{row['source']}）：{parts}。"
    if row.get("mark") is not None:
        text += "框起來的最後一段，就是印本與線上轉錄讀法不同的那一格。"
    return text


def _bands(layout: str, fid: str, rows: list[dict], bound: _fx.Bound) -> str:
    """One bounds figure, one layout: a row per table, 0° to 30° across."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (250.0, 852.0) if wide else (14.0, 326.0)
    k = (x1 - x0) / 30
    top, rh = (20.0, 74.0) if wide else (14.0, 76.0)
    band_y, band_h = (8.0, 32.0) if wide else (26.0, 24.0)
    bottom = top + len(rows) * rh
    H = bottom + (36 if wide else 38)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for i, row in enumerate(rows):
        y = top + i * rh
        by = y + band_y
        cy = by + band_h / 2
        ranges = _ranges(row["segments"])
        label = "，".join(f"{NAMES[r]} {bound.num(f'{a}°–{b}°')}" for r, a, b in ranges)
        out.append(f'<g class="fx-row" data-fx-key="{row["key"]}" tabindex="0" '
                   f'aria-label="{escape(row["name"])}，{escape(row["source"])}：{label}">')
        out.append(_fx.rect(8, y + 2, W - 16, rh - 4, "fx-hit"))
        if wide:
            out.append(_fx.text(24, cy + 2, row["name"], "fx-t fx-name"))
            out.append(_fx.text(24, cy + 24, row["source"], "fx-t fx-small fx-dim"))
        else:
            out.append(_fx.text(x0, y + 18, row["name"], "fx-t fx-name"))
            out.append(_fx.text(x1, y + 18, row["source"], "fx-t fx-small fx-dim", "end"))
        for ruler, a, b in ranges:
            out.append(_fx.rect(x0 + a * k, by, (b - a) * k, band_h, FILLS[ruler]))
        for _, a, _b in ranges[1:]:
            out.append(_fx.line(x0 + a * k, by, x0 + a * k, by + band_h, "fx-axis"))
        out.append(_fx.rect(x0, by, x1 - x0, band_h, "fx-inset-frame"))
        r = 11 if wide else 9
        for j, (ruler, a, b) in enumerate(ranges):
            width = bound.num(f"{b - a}°")
            mx = x0 + (a + b) / 2 * k
            out.append(_fx.circle(mx, cy, r, "fx-mk") + _fx.glyph(ruler, mx, cy, r * 1.25, "fx-mk-gl"))
            out.append(_fx.text(mx, by + band_h + (19 if wide else 16), f"{SHORT[ruler]} {width}" if wide
                                else f"{SHORT[ruler]}{width}", "fx-t fx-small", "middle"))
            if row.get("mark") == j:
                out.append(_fx.rect(x0 + a * k - 3, by - 3, (b - a) * k + 6, band_h + 6, "fx-frame"))
        out.append("</g>")
    axis = bottom + (0 if wide else 4)
    out.append(_fx.line(x0, axis, x1, axis, "fx-axis"))
    for t in range(0, 31, 6):
        out.append(_fx.line(x0 + t * k, axis, x0 + t * k, axis + 5, "fx-axis"))
        anchor = "start" if t == 0 and not wide else "end" if t == 30 and not wide else "middle"
        out.append(_fx.text(x0 + t * k, axis + 22, bound.scale(f"{t}°"), "fx-t fx-small fx-num", anchor))
    out.append("</svg>")
    if axis + 22 > H:
        raise RuntimeError(f"{fid} outgrew its drawing")
    return "".join(out)


def _bands_table(rows: list[dict], bound: _fx.Bound) -> str:
    body = []
    for row in rows:
        cells = "".join(f'<td>{NAMES[r]} <span class="n">{bound.num(f"{a}°–{b}°")}</span></td>'
                        for r, a, b in _ranges(row["segments"]))
        body.append(f'<tr data-fx-key="{row["key"]}"><th scope="row">{escape(row["name"])}<br>'
                    f'<small>{escape(row["source"])}</small></th>{cells}</tr>')
    return _fx.data_table(("界表", *(f"第 {bound.scale(str(i))} 段" for i in range(1, 6))), body)


def _bands_figure(fid: str, title: str, caption: str, rows: list[dict], bound: _fx.Bound, hero: bool = False) -> str:
    for row in rows:
        bound.label(row["name"])
        bound.label(row["source"])
    return _fx.figure(
        fid=fid,
        hero=hero,
        title=title,
        caption=caption,
        art=_fx.FigureArt.drawn(
            _bands, fid, rows, bound,
            notes=[_fx.Note(row["key"], None, _sentence(row, bound)) for row in rows],
            idle=IDLE,
        ),
        table=_bands_table(rows, bound),
        bound=bound,
    )


_ROW = re.compile(r'<g class="fx-row" data-fx-key="(?P<key>[a-z-]+)"(?P<body>.*?)</g>', re.S)
_RECT = re.compile(r'<rect x="(?P<x>[-0-9.]+)" y="[-0-9.]+" width="(?P<w>[0-9.]+)" height="[0-9.]+" class="(?P<cls>[a-z0-9-]+)"/>')


def drawn_rulers(markup: str) -> dict[str, list[tuple[str, float, float]]]:
    """The bounds as the wide drawing shows them, read back from its strips:
    {row key: [(ruler, first degree, end degree)]}."""
    wide = markup[markup.index('<svg class="fx-wide"'):markup.index('<svg class="fx-narrow"')]
    by_fill = {cls: ruler for ruler, cls in FILLS.items()}
    out = {}
    for row in _ROW.finditer(wide):
        strips = [(by_fill[m["cls"]], float(m["x"]), float(m["w"])) for m in _RECT.finditer(row["body"])
                  if m["cls"] in by_fill]
        start, end = strips[0][1], strips[-1][1] + strips[-1][2]
        k = (end - start) / 30
        out[row["key"]] = [(ruler, (x - start) / k, (x + w - start) / k) for ruler, x, w in strips]
    return out


def check_drawn(markup: str, rows: list[dict], sign: int, product_ruler) -> None:
    """Every row drawn from one of the product's profiles must give, read back
    from the drawing, the ruler the product answers for each degree of the
    sign: at the degree itself (a bound's first degree belongs to it) and half
    a degree in."""
    drawn = drawn_rulers(markup)
    for row in rows:
        if "profile" not in row:
            continue
        strips = drawn[row["key"]]
        for degree in range(30):
            for at in (degree, degree + 0.5):
                seen = next(r for r, a, b in strips if a - 0.01 <= at < b - 0.01)
                answer = product_ruler(row["profile"], row.get("sect"), sign * 30 + at)
                if seen != answer:
                    raise RuntimeError(f"{row['key']} at {SIGN_KEYS[sign]} {at}°: drawn {seen}, the product says {answer}")


def product_ruler(profile: str, sect: bool | None, longitude: float) -> str:
    """The ruler the product's dignity module gives a body at `longitude`."""
    with backend_on_path():
        from app.core.essential_dignities import _bounds_profile

    item = _bounds_profile(profile, [{"key": "sun", "name": "sun", "longitude": longitude}], sect)["objects"][0]
    return item["ruler"]


# --- figure 2: where the tables agree ------------------------------------------

COMPARISONS = (
    ("pl", "Ptolemy 界與 Lilly 1647"),
    ("ep", "埃及界與 Ptolemy 界"),
    ("epl", "埃及、Ptolemy、Lilly 三套"),
    ("all5", "再加迦勒底界日盤、夜盤"),
)


def _runs(flags: list[bool]) -> list[tuple[int, int]]:
    """Consecutive agreeing degrees inside one sign, as (first, end)."""
    out, start = [], None
    for degree, agree in enumerate(flags + [False]):
        if agree and start is None:
            start = degree
        elif not agree and start is not None:
            out.append((start, degree))
            start = None
    return out


def _agreement(layout: str, fid: str, agree: dict[str, list[bool]], counts: dict[str, int],
               signs: list[str], bound: _fx.Bound) -> str:
    """Figure 2, one layout: a row per comparison, the zodiac across, each
    degree where the tables give the same ruler filled."""
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    x0, x1 = (270.0, 858.0) if wide else (14.0, 326.0)
    col = (x1 - x0) / 12
    k = (col - 3) / 30
    if wide:
        head, top, rh, bar_y, bar_h = 0.0, 70.0, 52.0, 12.0, 26.0
    else:
        head, top, rh, bar_y, bar_h = 0.0, 64.0, 48.0, 24.0, 18.0
    H = top + len(COMPARISONS) * rh + (6 if wide else 4)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for s, key in enumerate(SIGN_KEYS):
        cx = x0 + s * col + (col - 3) / 2
        if wide:
            out.append(_fx.glyph(key, cx, head + 30, 16, "fx-mk-gl"))
            out.append(_fx.text(cx, head + 58, signs[s], "fx-t fx-small", "middle"))
        else:
            out.append(_fx.glyph(key, cx, head + 20, 12, "fx-mk-gl"))
            out.append(_fx.text(cx, head + 42, signs[s][0], "fx-t fx-small", "middle"))
            out.append(_fx.text(cx, head + 56, signs[s][1], "fx-t fx-small", "middle"))
    for i, (key, name) in enumerate(COMPARISONS):
        y = top + i * rh
        by = y + bar_y
        total = bound.num(f"{counts[key]} 度")
        if wide:
            out.append(_fx.text(24, by + bar_h / 2 - 2, name, "fx-t"))
            out.append(_fx.text(24, by + bar_h / 2 + 17, f"一致 {total}", "fx-t fx-small fx-num"))
        else:
            out.append(_fx.text(x0, y + 18, name, "fx-t fx-small"))
            out.append(_fx.text(x1, y + 18, total, "fx-t fx-small fx-num", "end"))
        for s in range(12):
            sx = x0 + s * col
            out.append(_fx.rect(sx, by, col - 3, bar_h, "fx-track"))
            for a, b in _runs(agree[key][s * 30:(s + 1) * 30]):
                out.append(_fx.rect(sx + a * k, by, (b - a) * k, bar_h, "fx-fill-solid"))
    out.append("</svg>")
    return "".join(out)


def _agreement_figure(agree: dict[str, list[bool]], counts: dict[str, int]) -> str:
    from ._common import SIGNS

    bound = _fx.Bound()
    for _, name in COMPARISONS:
        bound.label(name)
    per_sign = {key: [sum(agree[key][s * 30:(s + 1) * 30]) for s in range(12)] for key, _ in COMPARISONS}
    for key, _ in COMPARISONS:
        if sum(per_sign[key]) != counts[key]:
            raise RuntimeError(f"{key}: the signs add up to {sum(per_sign[key])}, not {counts[key]}")
    head = "".join(f'<th scope="col" class="n">{escape(name)}</th>' for _, name in COMPARISONS)
    body = []
    for s in range(12):
        cells = "".join(f'<td class="n">{bound.num(str(per_sign[key][s]))}</td>' for key, _ in COMPARISONS)
        body.append(f'<tr><th scope="row">{SIGNS[s]}</th>{cells}</tr>')
    totals = "".join(f'<td class="n">{bound.num(str(counts[key]))}</td>' for key, _ in COMPARISONS)
    body.append(f'<tr><th scope="row">合計</th>{totals}</tr>')
    table = _fx.data_table(f'<th scope="col">星座</th>{head}', body, summary="圖中的數字（表格）：每個星座裡一致的度數")
    caption = (f"<b>{bound.label('圖 2')}</b>黃道上 {bound.num('360')} 個一度區間，從牡羊座 {bound.scale('0°')} 排到雙魚座 "
               f"{bound.scale('30°')}，每一格是一個星座。塗黑的度數，表示那一列比較的幾套表在這一度給同一個界主；"
               "留白的度數，就是換一套表、界主跟著換的地方。")
    return _fx.figure(
        fid="fig-agree",
        title="四套界表在黃道上哪些度數給同一個界主",
        caption=caption,
        art=_fx.FigureArt.drawn(_agreement, "fig-agree", agree, counts, SIGNS, bound),
        table=table,
        bound=bound,
    )


def build() -> tuple[dict[str, str], list[str]]:
    with backend_on_path():
        from app.core.dignity_tables import BOUNDS_SOURCE_DETAILS, EGYPTIAN_BOUNDS as E, \
            LILLY_RECEIVED_BOUNDS as L, PTOLEMY_ROBBINS_BOUNDS as P, SIGNS as SIGN_IDS
        from app.core.essential_dignities import CHALDAEAN_SEGMENTS_BY_SECT as C

    if tuple(SIGN_IDS) != SIGN_KEYS:
        raise RuntimeError("the product's sign order is not the figure's")
    leo = SIGN_KEYS.index("leo")
    libra = SIGN_KEYS.index("libra")
    previous = [row["previous_recorded_row"] for row in
                BOUNDS_SOURCE_DETAILS["lilly_received_bounds_1647_v1"]["row_exceptions"] if row["sign"] == "leo"]
    if len(previous) != 1:
        raise RuntimeError("the product no longer keeps one earlier record of Lilly's Leo row")
    superseded = tuple((ruler, width) for ruler, width in previous[0])

    aries_rows: list[dict[str, Any]] = [
        dict(key="egyptian", name="埃及界", source="Ptolemy I.20 轉述", segments=E[0], profile=EGYPTIAN),
        dict(key="chaldaean-day", name="迦勒底界・日盤", source="依 I.21 的規則生成", segments=C[True][0],
             profile=CHALDAEAN, sect=True),
        dict(key="chaldaean-night", name="迦勒底界・夜盤", source="土、水對調", segments=C[False][0],
             profile=CHALDAEAN, sect=False),
        dict(key="ptolemy", name="Ptolemy 界", source="Robbins 印本 p.107", segments=P[0], profile=PTOLEMY),
        dict(key="lilly", name="Lilly 1647", source="Christian Astrology p.104", segments=L[0], profile=LILLY),
    ]
    leo_rows: list[dict[str, Any]] = [
        dict(key="egyptian", name="埃及界", source="Robbins p.97", segments=E[leo], profile=EGYPTIAN),
        dict(key="ptolemy", name="Ptolemy 界", source="Robbins p.107", segments=P[leo], profile=PTOLEMY),
        dict(key="lilly", name="Lilly 1647・現行", source="依初版頁面影像", segments=L[leo], profile=LILLY),
        dict(key="lilly-old", name="Lilly 1647・舊紀錄", source="已撤換，保留供對照", segments=superseded),
    ]
    # LacusCurtius gives Saturn, where Robbins's print gives Mars, for the last
    # bound of Libra.
    online = list(P[libra])
    if online[-1][0] != "mars":
        raise RuntimeError("the printed Ptolemy Libra row no longer ends with Mars")
    online[-1] = ("saturn", online[-1][1])
    libra_rows: list[dict[str, Any]] = [
        dict(key="ptolemy-print", name="Ptolemy 界・印本", source="Robbins p.107：火星", segments=P[libra], mark=4,
             profile=PTOLEMY),
        dict(key="ptolemy-online", name="Ptolemy 界・線上轉錄", source="LacusCurtius：土星", segments=tuple(online),
             mark=4),
        dict(key="lilly", name="Lilly 1647", source="p.104", segments=L[libra], profile=LILLY),
    ]

    def ruler(table, sign, degree):
        start = 0
        for name, width in table[sign]:
            if start <= degree < start + width:
                return name
            start += width
        raise RuntimeError(f"no bound covers sign {sign} degree {degree}")

    agree: dict[str, list[bool]] = {key: [] for key, _ in COMPARISONS}
    for sign in range(12):
        for degree in range(30):
            e, p, l, cd, cn = (ruler(t, sign, degree) for t in (E, P, L, C[True], C[False]))
            agree["ep"].append(e == p)
            agree["pl"].append(p == l)
            agree["epl"].append(e == p == l)
            agree["all5"].append(e == p == l == cd == cn)
    counts = {key: sum(flags) for key, flags in agree.items()}
    quoted = [
        f"<b>{counts['pl']}</b><span>度：Ptolemy 界與 Lilly 1647 給同一個界主",
        f"<b>{counts['ep']}</b><span>度：埃及界與 Ptolemy 界一致",
        f"<b>{counts['epl']}</b><span>度：埃及、Ptolemy、Lilly 三套都一致",
        f"<b>{counts['all5']}</b><span>度：連迦勒底界的日盤與夜盤也算進去，全部一致",
    ]

    b1, b3, b4 = _fx.Bound(), _fx.Bound(), _fx.Bound()
    aries = _bands_figure(
        "fig-aries", "牡羊座在四套界表裡的切法", (
            f"<b>{b1.label('圖 1')}</b>牡羊座 {b1.scale('0°')} 到 {b1.scale('30°')} 在四套界表裡的切法（迦勒底界依日盤、夜盤各一列）。"
            "每一段的寬度就是它的度數，圓裡是界主的符號，段下寫界主與段長；同一顆行星在每一列用同一種排線。"
            "五列都以木星開頭；Ptolemy 界與 Lilly 在牡羊座完全相同，其餘各列從第二段起就分歧。"),
        aries_rows, b1, hero=True)
    leo_figure = _bands_figure(
        "fig-leo", "獅子座在三套界表裡的切法，以及 Lilly 表已撤換的舊紀錄", (
            f"<b>{b3.label('圖 3')}</b>獅子座的界。Lilly 1647 的現行讀法與本站先前的紀錄並列；"
            "後者已撤換，留在這裡讓你看見改了什麼。"),
        leo_rows, b3)
    libra_figure = _bands_figure(
        "fig-libra", "天秤座的界：Ptolemy 界的印本、線上轉錄與 Lilly 1647", (
            f"<b>{b4.label('圖 4')}</b>天秤座的界。框起來的一段就是印本與線上轉錄讀法不同的那一格。"),
        libra_rows, b4)
    for markup, rows, sign in ((aries, aries_rows, 0), (leo_figure, leo_rows, leo), (libra_figure, libra_rows, libra)):
        check_drawn(markup, rows, sign, product_ruler)
    planets = ("saturn", "jupiter", "mars", "venus", "mercury")
    return {
        "fx-defs": _fx.defs(planets + SIGN_KEYS),
        "aries": aries,
        "agreement": _agreement_figure(agree, counts),
        "leo": leo_figure,
        "libra": libra_figure,
    }, quoted
