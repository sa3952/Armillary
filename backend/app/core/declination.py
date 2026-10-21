"""赤緯相位 (平行 Parallel／反平行 Contra-parallel) ——屬方法層而非天文資料層。

赤緯數值本身（見 astronomical_data.bodies 的 declination 欄位）是天文事實；
「相差在 orb 之內即構成相位」是帶容許誤差的技法判斷，因此在此明確標註具名 method
與所用 orb，回傳結果應歸類為 derived_methods，不與原始星體位置混在同一層。

比照三王星處理：
標為 `research_only`，維持預設關閉、opt-in，介面須明示其為**非古典傳統**（介面各處統一寫
「17 世紀 Placidus 的界定，非古典傳統」，與方法頁一致）。
赤緯平行／反平行不是希臘化或中世紀的相位。可核的出處是 Placidus de Titis
《Tabulae primi mobilis》（Padua 1657）卷二論題第 50 條：他把 Ptolemy 所說星座之間的
相見與命從關係，改以「與赤道等距」（赤緯相等）界定——同半球為平行，異半球為反平行。
1657 以前是否有人使用，未核，不主張「最早」。**稱之為「古典」將構成不實陳述**，
而可被證偽的陳述一律不得出現。
"""

from .bodies import DEFINITIONAL_EXCLUDED_PAIRS
from .module_state import (
    PRODUCT_FORMULA_SOURCE,
    computed_receipt,
    module_state,
    frame_table_refusal,
)
from .method_status import method_head
from .source_reading import cited, reference_only
from .trace import Trace

DECLINATION_ASPECT_METHOD_NAME = "parallel_contra_parallel_fixed_orb_v1"
DECLINATION_ASPECT_CLASSIFICATION = "research_only"
DECLINATION_ASPECT_PROVENANCE = "not_classical_earliest_use_attribution_unverified"
# Closed set: the state before a primary page is read, then the 1657
# attestation (the printed theses define the technique).
DECLINATION_ATTRIBUTION_STATES = (
    "attributed_pending_primary_check",
    "attested_placidus_1657",
)
DECLINATION_ASPECT_PROVENANCE_ATTRIBUTION = {
    "status": "attested_placidus_1657",
    "attributed_to": (
        "Placidus de Titis, Tabulae primi mobilis (Padua: Frambotti, 1657): "
        "parallels and their opposite-hemisphere counterpart defined by equal "
        "declination"
    ),
    "attribution_source": (
        "Placidus de Titis, Tabulae primi mobilis, Padua: Frambotti 1657, "
        "Theses ex II. libro, no. 50, p.9: the commonly so-called antiscia are "
        "renamed 'Parallelos', defined as equally distant from the equator and "
        "taken from the declination table; in the same hemisphere 'primarius "
        "seu intuens', in opposite hemispheres commanding and obeying (the "
        "contra-parallel). Placidus presents this as Ptolemy's relation of "
        "signs of equal rising and the same parallel (Tetrabiblos I.14-I.15), "
        "which concerns signs, not bodies."
    ),
    "date_claim": "1657",
    "note": (
        "The date is that of the cited printed definition, not a claim of "
        "earliest use; earlier uses are not checked. Whether the declinations "
        "include planetary latitude is not asserted. The technique is not "
        "presented as Hellenistic or medieval."
    ),
}
# 預設 1° 容許度是本產品的選擇，不歸屬任何作者；研究報告稱未找到 Placidus 的靜態本命 orb。
DECLINATION_DEFAULT_ORB_PROVENANCE = "modern_product_default"
# orb 0 合法：比較式 |差| ≤ orb 自然退化為赤緯完全相等，不另設特例。
ZERO_ORB_SEMANTICS = "exact_equality_only"
# 參與者由 app.core.bodies.effective_participants 選出——與黃道相位、反照點共用同一個
# helper。本模組只接收選好的名單，不自帶交點或現代點的納入規則（否則凱龍星會在開啟時
# 自動加入赤緯相位）。


def _declination_side(value: float) -> str:
    if value == 0.0:
        return "zero"
    return "north" if value > 0.0 else "south"


def compute_declination_aspects(
    bodies: list,
    orb: float,
    trace: Trace,
    *,
    default_orb: float = 1.0,
    participant_policy: dict | None = None,
    orb_explicit: bool | None = None,
) -> dict:
    # The request path says whether the orb was sent, so an explicit 1.0 is the
    # user's choice.  None is only for unit callers that hold no request.
    explicit = orb != default_orb if orb_explicit is None else orb_explicit
    trace.add(
        f"赤緯相位判斷方法 (method={DECLINATION_ASPECT_METHOD_NAME})",
        formula="平行(Parallel): |δ1 - δ2| ≤ 容許誤差 且 同號；反平行(Contra-parallel): |δ1 + δ2| ≤ 容許誤差 且 異號",
        inputs={"容許誤差(度)": orb},
        result={"參與天體數": len(bodies)},
    )

    aspects = []
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if frozenset({a.get("key"), b.get("key")}) in DEFINITIONAL_EXCLUDED_PAIRS:
                continue
            d1, d2 = a["declination"], b["declination"]
            if d1 is None or d2 is None:
                continue
            side_a = _declination_side(d1)
            side_b = _declination_side(d2)
            if "zero" in (side_a, side_b):
                continue
            if side_a == side_b:
                kind, label, diff = "parallel", "平行", abs(d1 - d2)
            else:
                kind, label, diff = "contra_parallel", "反平行", abs(d1 + d2)
            if diff > orb:
                continue
            aspects.append({
                "type": kind, "body_a": a["name"], "body_b": b["name"],
                "declination_a": d1, "declination_b": d2, "diff": diff,
            })
            trace.add(
                f"{a['name']} 與 {b['name']} 成赤緯{label}",
                inputs={f"δ({a['name']})": d1, f"δ({b['name']})": d2},
                result={"誤差(度)": diff},
            )

    return {
        **method_head(DECLINATION_ASPECT_METHOD_NAME, "declination_aspects"),
        "method_classification": DECLINATION_ASPECT_CLASSIFICATION,
        "method_provenance": DECLINATION_ASPECT_PROVENANCE,
        "method_provenance_attribution": {
            "status": DECLINATION_ASPECT_PROVENANCE_ATTRIBUTION["status"],
            "date_claim": DECLINATION_ASPECT_PROVENANCE_ATTRIBUTION["date_claim"],
            "source_ref": "declination_aspects",
        },
        "default_orb_provenance": DECLINATION_DEFAULT_ORB_PROVENANCE,
        "participant_keys": [
            body["key"] for body in bodies if body.get("declination") is not None
        ],
        "excluded_participant_keys": [
            body["key"] for body in bodies if body.get("declination") is None
        ],
        "participant_policy": participant_policy,
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "orb_receipt": {
            **module_state(
                requested=explicit,
                executed=True,
                applicable=True,
                available=True,
                source="user_override" if explicit else "product_default",
            ),
            "default_orb_degrees": default_orb,
            "effective_orb_degrees": orb,
            "comparison": "abs_difference_le_orb",
            "zero_orb_semantics": ZERO_ORB_SEMANTICS,
        },
        "aspects": aspects,
    }


def declination_aspects_not_applicable(state: dict, trace: Trace) -> dict:
    refusal = frame_table_refusal(
        state, trace, f"赤緯相位判斷方法 (method={DECLINATION_ASPECT_METHOD_NAME})",
        note=(
            "赤緯平行比較的是當日赤道上的赤緯；J2000 或不含章動的赤道不是這個框架，"
            "參考框架相容表判定不適用，不計算、不轉換座標。"
        ),
    )
    return {
        **method_head(DECLINATION_ASPECT_METHOD_NAME, "declination_aspects"),
        "method_classification": DECLINATION_ASPECT_CLASSIFICATION,
        **refusal,
        "participant_keys": [],
        "excluded_participant_keys": [],
        "participant_policy": None,
        "aspects": [],
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "declination_aspects": {
        "applies_to": "derived_methods.declination_aspects.method_provenance_attribution",
        "method_provenance": DECLINATION_ASPECT_PROVENANCE,
        "attribution": dict(DECLINATION_ASPECT_PROVENANCE_ATTRIBUTION),
        "sources": [
            cited(("Placidus de Titis, Tabulae primi mobilis (Padua: Frambotti 1657), "
                   "Theses ex II. libro, no. 50, p.9"),
                  ("the so-called antiscia renamed 'Parallelos', equal distance from the "
                   "equator, and the contra-parallel"),
                  "original_language_read",
                  ("the 1657 printing as scanned at archive.org "
                   "(bub_gb_3RHgMAUa5fMC, n28 = p.9), thesis 50: 'Antiscia "
                   "communiter vocata nos Parallelos ... nuncupamus'")),
            reference_only(
                "Ptolemy, Tetrabiblos I.14-I.15",
                "signs of equal rising and the same parallel, as Placidus presents it",
                "level pending: named through Placidus; the record does not say Ptolemy "
                "was read for this entry",
            ),
        ],
    },
}
