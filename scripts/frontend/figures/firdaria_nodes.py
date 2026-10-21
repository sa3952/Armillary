"""〈法達夜盤的交點排在哪裡〉: figure 1 (the 75 years of the day order and the
two night orders as three bands, the node periods hatched, the years where the
night orders part marked), its data table, and the numbers the prose quotes.

The years and orders are the backend's own tables, read through the product's
`firdaria_periods` for a night chart under each named profile (and a day chart).
The independent answer they are checked against is written out below from the
sources the article cites: al-Biruni's table (Book of Instruction §438-439,
Wright 1934 p.48) for the day order and the nodes-last night order, and the
reading of Bonatti that puts the nodes after Mars.
"""
from __future__ import annotations

from fractions import Fraction

from . import _fx, page_methods_time_lords
from ._common import backend_on_path


FRAGMENT = "blog-firdaria-night-node-order"
BODY = page_methods_time_lords.BODY
# Written out from the sources, not read from the product.
EXPECTED_YEARS = {"sun": 10, "venus": 8, "mercury": 13, "moon": 9, "saturn": 11, "jupiter": 12, "mars": 7,
                  "north_node": 3, "south_node": 2}
EXPECTED_ORDERS = {
    "day": ("sun", "venus", "mercury", "moon", "saturn", "jupiter", "mars", "north_node", "south_node"),
    "night": ("moon", "saturn", "jupiter", "mars", "sun", "venus", "mercury", "north_node", "south_node"),
    "night-mars": ("moon", "saturn", "jupiter", "mars", "north_node", "south_node", "sun", "venus", "mercury"),
}
# (key, is_day, profile, label lines, table head)
ROWS = (
    ("day", True, "abu_mashar_nodes_after_mercury_v1", ("日盤",), "日盤"),
    ("night", False, "abu_mashar_nodes_after_mercury_v1", ("夜盤（預設）", "交點在水星後"), "夜盤：交點在水星後（預設）"),
    ("night-mars", False, "bonatti_reading_nodes_after_mars_v1", ("夜盤（另一讀法）", "交點在火星後"),
     "夜盤：交點在火星後"),
)


def _orders() -> dict[str, list[tuple[str, int, int]]]:
    """Each order as the product answers it: (lord, start, end) in years from birth."""
    with backend_on_path():
        from app.core import firdaria

        if dict(firdaria.PERIOD_YEARS) != EXPECTED_YEARS:
            raise RuntimeError("the product's firdaria years differ from the sources' table")
        out = {}
        for key, is_day, profile, _, _ in ROWS:
            answer = firdaria.firdaria_periods(
                is_day=is_day, nocturnal_node_profile=profile, scope="full_cycle", completed_years=0,
                instant_at_year=lambda year: {"jd_ut": None, "status": "not_computed"})
            periods = [(p["level_1_lord"], p["start_year"], p["end_year"]) for p in answer["periods"]]
            if tuple(lord for lord, _, _ in periods) != EXPECTED_ORDERS[key]:
                raise RuntimeError(f"{key}: the product's order {periods} is not the sources' order")
            start = 0
            for lord, s, e in periods:
                if (s, e) != (start, start + EXPECTED_YEARS[lord]):
                    raise RuntimeError(f"{key} {lord}: the product's span {s}–{e} is not its years")
                start += EXPECTED_YEARS[lord]
            out[key] = [(lord, int(s), int(e)) for lord, s, e in periods]
        return out


def _parting(orders: dict) -> int:
    """The first year from birth at which the two night orders name different lords."""
    def lord_at(order, year):
        return next(lord for lord, s, e in order if s <= year < e)

    return next(year for year in range(75) if lord_at(orders["night"], year) != lord_at(orders["night-mars"], year))


def _year_runs(orders: dict, parting: int) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """From `parting` to 75: runs of whole years whose major lords differ, and runs where they agree.

    Every period starts on a whole year, so a year's lord is the lord at its start.  Where the major
    lords agree, the period started at a different year in each order, so the sub-periods differ.
    """
    def lord_at(order, year):
        return next(lord for lord, s, e in order if s <= year < e)

    runs: dict[bool, list[tuple[int, int]]] = {True: [], False: []}
    for year in range(parting, 75):
        same = lord_at(orders["night"], year) == lord_at(orders["night-mars"], year)
        bucket = runs[same]
        if bucket and bucket[-1][1] == year:
            bucket[-1] = (bucket[-1][0], year + 1)
        else:
            bucket.append((year, year + 1))
    return runs[False], runs[True]


def _plate(layout: str, fid: str, orders: dict, parting: int, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    total = 75
    if wide:
        W, H = _fx.WIDE, 470.0
        a0, a1 = 190.0, 850.0
        tops = (70.0, 170.0, 270.0)
        thick = 40.0
    else:
        W, H = _fx.NARROW, 690.0
        a0, a1 = 92.0, 92.0 + total * 6.8
        tops = (60.0, 138.0, 216.0)  # column left edges
        thick = 40.0
    P = lambda y: a0 + y / total * (a1 - a0)  # noqa: E731
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for (key, _, _, lines, _), top in zip(ROWS, tops):
        for lord, s, e in orders[key]:
            p0, p1 = P(s), P(e)
            node = lord in ("north_node", "south_node")
            x, y, w, h = (p0, top, p1 - p0, thick) if wide else (top, p0, thick, p1 - p0)
            out.append(_fx.rect(x, y, w, h, "fx-fill-hatch" if node else "fx-cell"))
            if node:
                out.append(_fx.rect(x, y, w, h, "fx-inset-frame"))
            mid = (p0 + p1) / 2
            if wide:
                out.append(_fx.glyph(lord, mid, top + thick / 2, 14, "fx-mk-gl"))
            else:
                out.append(_fx.glyph(lord, top + thick / 2, mid, 11, "fx-mk-gl"))
        # where the nodes fall in this order
        (n0,) = [s for lord, s, _ in orders[key] if lord == "north_node"]
        (n1,) = [e for lord, _, e in orders[key] if lord == "south_node"]
        span = f"交點：滿 {bound.num(str(n0))}–{bound.num(str(n1))} 歲"
        if wide:
            for i, part in enumerate(lines):
                out.append(_fx.text(a0 - 14, top + 12 + i * 22, part, "fx-t fx-small", "end"))
            at_end = n1 == total
            out.append(_fx.text(P(n1) if at_end else (P(n0) + P(n1)) / 2, top + thick + 22, span,
                                "fx-t fx-small fx-num", "end" if at_end else "middle"))
        else:
            for i, part in enumerate(lines[0].replace("（", "\n（").split("\n")):
                out.append(_fx.text(top + thick / 2, 32 + i * 18, part, "fx-t fx-small", "middle"))
            out.append(_fx.text(top + thick + 3, P(n0) + 12, f"{bound.num(str(n0))}–{bound.num(str(n1))}",
                                "fx-t fx-small fx-num"))
    # the years where the two night orders part
    if wide:
        y = tops[2] + thick + 52
        out.append(_fx.line(P(parting), y, P(total), y, "fx-axis"))
        out.append(_fx.line(P(parting), y - 6, P(parting), y + 6, "fx-axis"))
        out.append(_fx.line(P(total), y - 6, P(total), y + 6, "fx-axis"))
        out.append(_fx.text((P(parting) + P(total)) / 2, y + 22,
                            f"滿 {bound.num(str(parting))} 歲起，兩種夜盤順序開始分歧", "fx-t fx-small", "middle"))
        axis = H - 64
        out.append(_fx.line(a0, axis, a1, axis, "fx-axis"))
        for year in range(0, total + 1, 5):
            out.append(_fx.line(P(year), axis, P(year), axis + 5, "fx-axis"))
            if year % 15 == 0:
                out.append(_fx.text(P(year), axis + 24, bound.scale(str(year)), "fx-t fx-small fx-num",
                                    "start" if year == 0 else "end" if year == total else "middle"))
        out.append(_fx.text((a0 + a1) / 2, axis + 48, "出生後的年數（等比例）", "fx-t fx-small", "middle"))
        out.append(_fx.text(a0, 40, "排線格是兩個月交點；圓滿一輪之後照同一順序重來", "fx-t fx-small fx-dim"))
    else:
        x = W - 12
        out.append(_fx.line(x, P(parting), x, P(total), "fx-axis"))
        out.append(_fx.line(x - 5, P(parting), x + 5, P(parting), "fx-axis"))
        out.append(_fx.line(x - 5, P(total), x + 5, P(total), "fx-axis"))
        out.append(_fx.text(x - 4, P(total) + 20, f"滿 {bound.num(str(parting))} 歲起兩種夜盤分歧",
                            "fx-t fx-small", "end"))
        axis = tops[0] - 10
        out.append(_fx.line(axis, a0, axis, a1, "fx-axis"))
        for year in range(0, total + 1, 5):
            out.append(_fx.line(axis - 5, P(year), axis, P(year), "fx-axis"))
            if year % 15 == 0:
                out.append(_fx.text(axis - 8, P(year) + 4, bound.scale(str(year)), "fx-t fx-small fx-num", "end"))
        out.append(_fx.text(8, a1 + 54, "出生後的年數（往下）；排線格是交點", "fx-t fx-small fx-dim"))
    out.append("</svg>")
    return "".join(out)


def _table(orders: dict, bound: _fx.Bound) -> str:
    rows = []
    for lord in EXPECTED_ORDERS["day"]:
        cells = []
        for key, *_ in ROWS:
            (s, e) = next((s, e) for name, s, e in orders[key] if name == lord)
            cells.append(f'<td class="n">{bound.num(str(s))}–{bound.num(str(e))}</td>')
        rows.append(f'<tr><th scope="row">{BODY[lord]}</th><td class="n">{bound.num(str(EXPECTED_YEARS[lord]))}</td>'
                    f'{"".join(cells)}</tr>')
    return _fx.data_table(("主期主星", "年數", *(label for *_, label in ROWS)), rows)


def build() -> tuple[dict[str, str], list[str]]:
    orders = _orders()
    parting = _parting(orders)
    bound = _fx.Bound()
    bound.label("圖 1")
    plate = _fx.figure(
        fid="fig-night-nodes",
        title="法達九段主期：日盤，與夜盤交點的兩種排法",
        caption=(f"<b>{bound.label('圖 1')}</b>從出生起的 {bound.num('75')} 年，一格是一個主期，寬度照年數畫；"
                 "排線格是北交點與南交點。三條依序是日盤、本站預設的夜盤順序（交點排在七顆行星之後），"
                 "以及另一種讀法（交點排在火星之後、太陽之前）。年數與順序取自本站計算用的表，"
                 "並與 al-Bīrūnī 的表逐格核對。"),
        art=_fx.FigureArt.drawn(_plate, "fig-night-nodes", orders, parting, bound),
        table=_table(orders, bound),
        bound=bound,
    )

    def nodes(key: str) -> tuple[int, int]:
        (n0,) = [s for lord, s, _ in orders[key] if lord == "north_node"]
        (n1,) = [e for lord, _, e in orders[key] if lord == "south_node"]
        return n0, n1

    default, alternative = nodes("night"), nodes("night-mars")
    differ, agree = _year_runs(orders, parting)
    sun_alt = next((s, e) for lord, s, e in orders["night-mars"] if lord == "sun")
    quoted = [
        f"滿 {default[0]} 歲到滿 {default[1]} 歲",
        f"滿 {alternative[0]} 歲到滿 {alternative[1]} 歲",
        f"從滿 {parting} 歲起",
        f"之後的 {75 - parting} 年裡",
        f"有 {sum(e - s for s, e in differ)} 年（滿 {'、'.join(f'{s}–{e}' for s, e in differ)} 歲）",
        f"另外 {sum(e - s for s, e in agree)} 年（滿 {'、'.join(f'{s}–{e}' for s, e in agree)} 歲）",
        f"太陽主期移到滿 {sun_alt[0]} 歲到滿 {sun_alt[1]} 歲",
    ]
    if Fraction(sum(EXPECTED_YEARS.values())) != 75:
        raise RuntimeError("the cycle no longer totals 75 years")
    return {"fx-defs": _fx.defs(tuple(EXPECTED_YEARS)), "night-nodes": plate}, quoted
