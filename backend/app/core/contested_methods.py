"""對外「古典文獻說法不一」標記的白名單：唯一產生器。

provisional 只留在內部；只有古典學上明顯有爭議、宣稱確定反而奇怪的方法
才對外標記。白名單：

- 列入：月空亡的定義、命運點／精神點公式、界（標在技法族，不標在某一張表）、逐度相位的
  容許度、同度的定義。
- 不列：日夜盤邊界（古典文本沒有互相否定的兩派，是產品慣例；methods §05.3 已說明）、
  守護星體系（產品沒有輸出程序用的主宰體系，是否採用尚未決定）。

「有爭議」在這裡的意思是：**前現代具名文本彼此給出會改變輸出的不同規則**。內部
`method_status`（method_status.py）與本白名單是兩件事：已採用的方法仍可能在文獻上有爭議
（例如界），provisional 的方法也可能沒有古典爭議。對外文字不用 provisional 一詞
（前端測試看守）。

每一條的對外說明只引用已核的出處（頁影、轉寫或自核原句）；完整書目
在方法出處登錄 `contested/<key>`。標記只在對應模組本次真的算出結果時才出現在回應裡。
"""

from __future__ import annotations

from typing import Any

MARK_POLICY = "marked_only_where_named_pre_modern_texts_give_rules_that_change_the_output"

# 白名單：key → 對外說明與出處。順序即回應中的順序。
CONTESTED_METHODS: dict[str, dict[str, Any]] = {
    "void_of_course_definition": {
        "technique_family": "void_of_course",
        "response_path": "derived_methods.void_of_course",
        "note_zh": (
            "月空亡的定義，古典文獻本身就不一致，同一張盤可能得到不同結論：Porphyry 名下的"
            "《Introduction》ch.23 看月亮在接下來 30° 內是否與行星接合，不管是否換座；"
            "Lilly《Christian Astrology》（1647）p.112 以月亮離開本星座前是否再入相位為準。"
            "本產品採「離開本星座前沒有任何相位精確完成」。"
            "要求換座前精確完成：後人文獻歸於 Al H. Morrison（AFA Journal 1966 年 10 月有專文，原文未讀）；"
            "更早的起源尚未查證。"
        ),
        "sources": [
            "Ps.-Porphyry, Introduction ch.23 (Boer-Weinstock, CCAG V/4, 1940, p.202; "
            "read in an online Greek transcription and Holden 2009 trans. p.18, the "
            "CCAG page itself not checked): the Moon joins no planet, by sign, degree, "
            "aspect or kollesis, within the next 30 degrees, regardless of the sign "
            "boundary",
            "William Lilly, Christian Astrology (1647) p.112 'Voyd of course': bounded "
            "by the sign",
            "Requiring exact perfection before the sign exit: attributed by later "
            "literature to Al H. Morrison (an article in the AFA Journal, October 1966; "
            "the article was not read); an earlier origin has not been checked",
        ],
    },
    "lot_formulas": {
        "technique_family": "lots",
        "response_path": "derived_methods.lots",
        "note_zh": (
            "命運點與精神點的公式，古典文獻本身就不一致：Ptolemy《Tetrabiblos》III.10 主張"
            "命運點日夜都由太陽量到月亮；Valens《Anthologies》III.11（Pingree 編號；Kroll／Riley 為 III.14）記載夜盤另依月亮是否已"
            "落下而改式。本產品採夜盤反轉的公式。"
        ),
        "sources": [
            "Ptolemy, Tetrabiblos III.10 (Robbins numbering; = Hübner III.11): the Lot "
            "of Fortune from Sun to Moon by day and by night",
            "Vettius Valens, Anthologies III.11 (Pingree; = III.14 Kroll/Riley, '14K;11P'): "
            "at night the formula changes with whether the Moon has set",
            "Paulus Alexandrinus ch.23: reversal at night (the product's formula); "
            "read in the Greek-Latin first printing (Wittenberg 1586); Boer 1958 not checked",
        ],
    },
    "bounds_tables": {
        "technique_family": "bounds",
        "response_path": "derived_methods.essential_dignities",
        "technique_key": "bounds",
        "note_zh": (
            "界有多套表並存，同一度數可能歸給不同行星：Ptolemy《Tetrabiblos》I.20–21 並列"
            "埃及界與迦勒底界並加以評比，書中所附的完整界表是否出自 Ptolemy，學界也有爭議。"
            "所以本產品不預設任何一套，由你選表。"
        ),
        "sources": [
            "Ptolemy, Tetrabiblos I.20-21, trans. Robbins (Loeb 1940) pp.91-107: Egyptian "
            "terms (table p.97), Chaldaean terms rule (pp.99-101), complete table p.107",
            "Authorship of the complete table disputed: Tolsa, Philologus 162.2 (2018) "
            "247-264 (abstract only checked)",
        ],
    },
    "degree_aspect_orbs": {
        "technique_family": "aspect_orbs",
        "response_path": "derived_methods.aspects",
        "technique_key": "degree_based.in_orb",
        "note_zh": (
            "容許度的數字與算法，前現代文本本身就不一致：Lilly《Christian Astrology》（1647）"
            "p.107 並列兩組容許度，並說自己兩組交替使用；al-Bīrūnī《Book of Instruction》"
            "§490 記下六種不同說法。「是否在容許度內」因此取決於所選的表。"
            "另外，本產品的逐度層不要求兩星先在星座上相見，Lilly 1647 p.109 與 al-Bīrūnī "
            "§446 則以此為前提；整宮層另列在同一表。"
        ),
        "sources": [
            "William Lilly, Christian Astrology (1647) p.107: two sets of orbs printed "
            "side by side; he uses one or the other as memory serves",
            "al-Bīrūnī, The Book of Instruction, trans. R. Ramsay Wright (1934) §490: "
            "5°, 6°, 12°, 15° (the Sun's orb), the average of the two orbs, or exact "
            "conjunction only",
            "William Lilly, Christian Astrology (1647) p.109; al-Bīrūnī §446: aspects "
            "presuppose signs that behold one another",
        ],
    },
    "partile_definition": {
        "technique_family": "partile",
        "response_path": "derived_methods.aspects",
        "technique_key": "degree_based.partile",
        "note_zh": (
            "「同度」的定義也不一致：Lilly《Christian Astrology》（1647）p.106 指兩星恰好相差"
            "構成相位的度數；載於 Lilly 名下的 1677 年曆格言第 25 條，以相差 3 度內為同度；"
            "「1 度以內」的用法則沒有找到具名出處。本產品預設採同一整數度，而且只在兩星的"
            "星座先構成該相位時才判定同度。"
        ),
        "sources": [
            "William Lilly, Christian Astrology (1647) Book I ch. XIX p.106",
            "Merlini Anglici Ephemeris ... for the Year 1677, 'Useful Astrological "
            "Aphorisms', no. 25 (aphorism section unsigned; prefatory letter signed "
            "William Lilly)",
            "Deborah Houlding, Skyscript glossary 'Partile / Platick' (secondary; "
            "the within-one-degree usage, no named author)",
        ],
    },
}

# 討論過但不標的方法，以及不標的理由（登錄用；不進回應）。
NOT_MARKED: dict[str, str] = {
    "sect_boundary": (
        "Checked texts (Valens III.5, Ptolemy I.7) treat day and night births as "
        "given classes and set no boundary; the 0° rule is a product convention "
        "explained on the methods page (§05.3), not a classical dispute."
    ),
    "rulership_scheme": (
        "The product emits no procedural rulership scheme; whether to adopt one "
        "is an open question."
    ),
}


def _applies(key: str, derived_methods: dict, modules: dict) -> bool:
    entry = CONTESTED_METHODS[key]
    module_name = entry["response_path"].split(".", 1)[1]
    if modules.get(module_name) != "computed":
        return False
    module = derived_methods.get(module_name)
    if not isinstance(module, dict):
        return False
    if key == "bounds_tables":
        selected = module.get("selected_profiles")
        return isinstance(selected, dict) and bool(selected.get("bounds"))
    if key == "degree_aspect_orbs":
        orb_receipt = (module.get("degree_based") or {}).get("orb_receipt") or {}
        return orb_receipt.get("configuration_mode") in {
            "named_profile",
            "named_profile_scaled",
        }
    if key == "partile_definition":
        # Partile is judged for every evaluated pair, listed or not.
        listing = module.get("pair_listing") or {}
        return bool(listing.get("evaluated_pairs"))
    return True


def contested_method_marks(derived_methods: dict, modules: dict) -> dict:
    """The marks for this response: one per whitelisted technique that was computed."""

    return {
        "policy": MARK_POLICY,
        "items": [
            {
                "key": key,
                "technique_family": entry["technique_family"],
                "response_path": entry["response_path"],
                **(
                    {"technique_key": entry["technique_key"]}
                    if "technique_key" in entry
                    else {}
                ),
                "note_zh": entry["note_zh"],
                "source_ref": f"contested/{key}",
            }
            for key, entry in CONTESTED_METHODS.items()
            if _applies(key, derived_methods, modules)
        ],
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "contested/whitelist": {
        "applies_to": "calculation_dossier.methodology.classical_source_disagreements",
        "policy": MARK_POLICY,
        "marked": sorted(CONTESTED_METHODS),
        "not_marked": dict(NOT_MARKED),
    },
    **{
        f"contested/{key}": {
            "applies_to": (
                "calculation_dossier.methodology.classical_source_disagreements"
                f" (key={key}; marks {entry['response_path']})"
            ),
            "technique_family": entry["technique_family"],
            "sources": list(entry["sources"]),
        }
        for key, entry in CONTESTED_METHODS.items()
    },
}
