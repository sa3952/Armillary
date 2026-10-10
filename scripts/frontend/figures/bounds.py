"""〈四套界表，四個答案〉: the Aries, Leo and Libra band figures and the
degree-by-degree agreement counts, read from the tables the product computes
with (backend/app/core/dignity_tables.py and essential_dignities.py).
"""
from __future__ import annotations

from ._common import backend_on_path


FRAGMENT = "blog-four-bounds-tables"
GLYPHS = {"saturn": "土", "jupiter": "木", "mars": "火", "venus": "金", "mercury": "水"}
# The Leo row Lilly's bounds had before the transcription was corrected; kept
# in the article for comparison, so it is not in the product's tables.
LILLY_LEO_SUPERSEDED = (("jupiter", 6), ("venus", 7), ("saturn", 6), ("mercury", 6), ("mars", 5))


def _band(segments, mark=None) -> str:
    out = []
    for i, (ruler, width) in enumerate(segments):
        extra = " mark" if mark == i else ""
        out.append(f'<span class="p-{ruler} w{width}{extra}">{GLYPHS[ruler]}{width}</span>')
    return '<div class="band">' + "".join(out) + "</div>"


def _row(name, small, segments, mark=None) -> str:
    return (f'        <div class="band-row"><span class="band-name">{name}<small>{small}</small></span>'
            f"{_band(segments, mark)}</div>")


def _block(rows) -> str:
    scale = ('        <div class="band-scale"><span></span><div><span>0°</span><span>6°</span><span>12°</span>'
             "<span>18°</span><span>24°</span><span>30°</span></div></div>")
    legend = ('      <p class="band-legend"><span><i class="p-saturn"></i>土星</span><span><i class="p-jupiter"></i>木星</span>'
              '<span><i class="p-mars"></i>火星</span><span><i class="p-venus"></i>金星</span><span><i class="p-mercury"></i>'
              "水星</span></p>")
    return '      <div class="bands">\n' + "\n".join(rows) + "\n" + scale + "\n      </div>\n" + legend


def build() -> tuple[dict[str, str], list[str]]:
    with backend_on_path():
        from app.core.dignity_tables import EGYPTIAN_BOUNDS as E, LILLY_RECEIVED_BOUNDS as L, \
            PTOLEMY_ROBBINS_BOUNDS as P
        from app.core.essential_dignities import CHALDAEAN_SEGMENTS_BY_SECT as C

    aries = _block([
        _row("埃及界", "Ptolemy I.20 轉述", E[0]),
        _row("迦勒底界・日盤", "依 I.21 的規則生成", C[True][0]),
        _row("迦勒底界・夜盤", "土、水對調", C[False][0]),
        _row("Ptolemy 界", "Robbins 印本 p.107", P[0]),
        _row("Lilly 1647", "Christian Astrology p.104", L[0]),
    ])
    leo = _block([
        _row("埃及界", "Robbins p.97", E[4]),
        _row("Ptolemy 界", "Robbins p.107", P[4]),
        _row("Lilly 1647・現行", "依初版頁面影像", L[4]),
        _row("Lilly 1647・舊紀錄", "已撤換，保留供對照", LILLY_LEO_SUPERSEDED),
    ])
    # LacusCurtius gives Saturn, where Robbins's print gives Mars, for the last
    # bound of Libra.
    online = list(P[6])
    online[-1] = ("saturn", online[-1][1])
    libra = _block([
        _row("Ptolemy 界・印本", "Robbins p.107：火星", P[6], mark=4),
        _row("Ptolemy 界・線上轉錄", "LacusCurtius：土星", tuple(online), mark=4),
        _row("Lilly 1647", "p.104", L[6]),
    ])

    def ruler(table, sign, degree):
        start = 0
        for name, width in table[sign]:
            if start <= degree < start + width:
                return name
            start += width
        raise RuntimeError(f"no bound covers sign {sign} degree {degree}")

    counts = dict(ep=0, pl=0, epl=0, all5=0)
    for sign in range(12):
        for degree in range(30):
            e, p, l, cd, cn = (ruler(t, sign, degree) for t in (E, P, L, C[True], C[False]))
            counts["ep"] += e == p
            counts["pl"] += p == l
            counts["epl"] += e == p == l
            counts["all5"] += e == p == l == cd == cn
    quoted = [
        f"<b>{counts['pl']}</b><span>度：Ptolemy 界與 Lilly 1647 給同一個界主",
        f"<b>{counts['ep']}</b><span>度：埃及界與 Ptolemy 界一致",
        f"<b>{counts['epl']}</b><span>度：埃及、Ptolemy、Lilly 三套都一致",
        f"<b>{counts['all5']}</b><span>度：連迦勒底界的日盤與夜盤也算進去，全部一致",
    ]
    return {"aries": aries, "leo": leo, "libra": libra}, quoted
