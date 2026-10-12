"""擴充阿拉伯點：Paulus ch.23 的 Hermetic 五點與 Valens IV.25 的兩點，只出位置。

- **點的名稱永遠不決定公式**：每個公式由綁定傳承的 `lot_method_id` 決定
  （`eros_paulus_hermetic_ch23_v1`），沒有 `eros_v1`。Valens 的兩點是另一傳承，與 Paulus
  同名點並列、不合併、不互相替代。
- **夜盤規則明寫**，不由日盤規則推導（同名點在不同傳承有不同夜盤政策）；本批七點的
  夜盤規則恰好都是日盤規則兩端互換，測試照字面核對。
- 依賴 Fortune／Spirit 的點只在**同一個日夜候選內**計算：日候選的 Eros 只用日候選的
  Spirit。Fortune／Spirit 一律讀 `lots.compute_lots` 的 `by_sect`（唯一產生器），
  這裡不重算。
- 主要值依該產生器的 `sect_applied`（>0° 判準）；兩個候選都列出，臨界帶時並列兩候選
  是 `lots/boundary_policy` 的同一政策。
- 輸出黃經、星座、落宮與展開的公式；不輸出主星吉凶、主題、與行星的相位，Courage 與
  Nemesis 不附任何描述字。
- 公式文法 v1 只有一種：上升點投射（`projector=ascendant`），ASC + plus − minus
  （`arc_policy=reverse_arc`，即自 minus 到 plus 的弧加到上升點）。
"""

from __future__ import annotations

from .dignity_tables import SIGNS
from .formatting import normalize_longitude, zodiac_sign_index
from .house_placements import _house_for_longitude

OPERANDS = (
    "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn",
    "fortune", "spirit",
)
SECT_CANDIDATES = ("day", "night")

_PAULUS = {
    "source_author": "Paulus Alexandrinus",
    "source_work": "Eisagogika",
    "source_passage": "ch.23 (seven lots of the Hermetic tradition)",
    "source_ref": "extended_lots/paulus_hermetic_ch23",
}
_VALENS = {
    "source_author": "Vettius Valens",
    "source_work": "Anthologies",
    "source_passage": "IV.25 (Kroll main text p.202; Riley marks it as a marginal note)",
    "source_ref": "extended_lots/valens_iv25",
}


def _method(lot_method_id, display_name_key, tradition, day_plus, day_minus):
    return {
        "lot_method_id": lot_method_id,
        "display_name_key": display_name_key,
        **tradition,
        "projector": "ascendant",
        "day_rule": {"plus": day_plus, "minus": day_minus},
        "night_rule": {"plus": day_minus, "minus": day_plus},
        "arc_policy": "reverse_arc",
        "dependencies": sorted({day_plus, day_minus} & {"fortune", "spirit"}),
    }


LOT_METHODS = (
    _method("eros_paulus_hermetic_ch23_v1", "lot_eros_paulus", _PAULUS, "venus", "spirit"),
    _method("necessity_paulus_hermetic_ch23_v1", "lot_necessity_paulus", _PAULUS, "fortune", "mercury"),
    _method("courage_paulus_hermetic_ch23_v1", "lot_courage_paulus", _PAULUS, "fortune", "mars"),
    _method("victory_paulus_hermetic_ch23_v1", "lot_victory_paulus", _PAULUS, "jupiter", "spirit"),
    _method("nemesis_paulus_hermetic_ch23_v1", "lot_nemesis_paulus", _PAULUS, "fortune", "saturn"),
    _method("love_valens_iv25_v1", "lot_love_valens", _VALENS, "spirit", "fortune"),
    _method("necessity_valens_iv25_v1", "lot_necessity_valens", _VALENS, "fortune", "spirit"),
)
if any(
    operand not in OPERANDS
    for method in LOT_METHODS
    for rule in ("day_rule", "night_rule")
    for operand in method[rule].values()
):
    raise RuntimeError("a lot operand is outside the closed operand set")


def _operand_longitude(operand: str, longitudes: dict, candidate: dict) -> float:
    if operand in ("fortune", "spirit"):
        return candidate[operand]
    return longitudes[operand]


def _position(longitude: float, houses: dict | None) -> dict:
    return {
        "longitude": longitude,
        "sign": SIGNS[zodiac_sign_index(longitude)],
        "house": None if houses is None else _house_for_longitude(longitude, houses["cusps"]),
    }


def compute_extended_lots(
    *,
    ascendant: float,
    longitudes: dict[str, float],
    lots: dict,
    houses: dict | None,
) -> dict:
    """Every lot method under both sect candidates, primary by the Lots producer.

    ``lots`` is a computed ``lots.compute_lots`` result: its ``by_sect`` holds the
    Fortune and Spirit of each candidate and ``sect_applied`` names the primary.
    """

    primary = lots["sect_applied"]
    results = []
    for method in LOT_METHODS:
        by_sect = {}
        for candidate in SECT_CANDIDATES:
            rule = method[f"{candidate}_rule"]
            fortune_spirit = lots["by_sect"][candidate]
            plus = _operand_longitude(rule["plus"], longitudes, fortune_spirit)
            minus = _operand_longitude(rule["minus"], longitudes, fortune_spirit)
            longitude = normalize_longitude(ascendant + plus - minus)
            by_sect[candidate] = {
                **_position(longitude, houses),
                "formula_expanded": {
                    "projector": {"operand": "ascendant", "longitude": ascendant},
                    "plus": {"operand": rule["plus"], "longitude": plus},
                    "minus": {"operand": rule["minus"], "longitude": minus},
                },
            }
        chosen = by_sect[primary]
        results.append({
            "lot_method_id": method["lot_method_id"],
            "display_name_key": method["display_name_key"],
            "source_ref": method["source_ref"],
            "sect_applied": primary,
            "longitude": chosen["longitude"],
            "sign": chosen["sign"],
            "house": chosen["house"],
            "same_value_both_candidates": (
                by_sect["day"]["longitude"] == by_sect["night"]["longitude"]
            ),
            "by_sect": by_sect,
        })
    return {
        "sect_status": lots["sect_status"],
        "sect_applied": primary,
        "house_system_code": None if houses is None else houses.get("system_code"),
        "lots": results,
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "extended_lots/paulus_hermetic_ch23": {
        "applies_to": "natal_lots.lots[source_ref=extended_lots/paulus_hermetic_ch23]",
        "lot_methods": [m for m in LOT_METHODS if m["source_author"] == "Paulus Alexandrinus"],
        "sources": [
            "Paulus Alexandrinus, Eisagogika ch.23 (Boer 1958; Schmidt/Hand 1995 "
            "pp.43-45): Eros, Necessity, Courage, Victory, Nemesis with Fortune and "
            "Spirit; citation as corrected by the research notes after checking, "
            "editions not re-read for this entry",
            "P.Berol. 9825 (AD 319; Greenbaum 2015, MHNH 15:85-116): a papyrus "
            "computing the seven lots, per the research notes; not checked",
        ],
        "courage_direction_note": (
            "Courage is ASC + Fortune - Mars by day: an earlier research draft wrote "
            "it reversed, which the research notes found to be their own error "
            "against the 1588 printing and the papyrus"
        ),
        "output_policy": (
            "positions only; no topic, no lord, no aspect, no descriptive word "
            "(Courage and Nemesis included)"
        ),
        "source_verification": "research_notes_checked_edition_not_reread",
    },
    "extended_lots/valens_iv25": {
        "applies_to": "natal_lots.lots[source_ref=extended_lots/valens_iv25]",
        "lot_methods": [m for m in LOT_METHODS if m["source_author"] == "Vettius Valens"],
        "sources": [
            "Vettius Valens, Anthologies IV.25: the formulas (Riley: 'from Fortune to "
            "the Daimon, counted from the Ascendant; at night the reverse') are in "
            "Kroll's main text (1908, p.202), read in the Greek; Riley marks the "
            "passage as a marginal note; Pingree's treatment not checked",
        ],
        "separate_tradition_note": (
            "Listed beside the Paulus lots of the same name, never merged with them "
            "and never substituted for them."
        ),
        "algebra_note": (
            "Under one sect candidate both reduce to ASC +/- 2(Sun - Moon), so their "
            "day and night values coincide"
        ),
        "source_verification": "translation_and_kroll_greek_read_pingree_not_checked",
    },
}
