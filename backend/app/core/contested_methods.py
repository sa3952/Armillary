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

from .aspect_profiles import LILLY_1647_READ_AT, MERLINI_1677_READ_AT
from .source_reading import SOURCE_READING_LEVELS

_ORIGINAL, _TRANSLATION, _SECONDARY, _BIBLIOGRAPHIC = SOURCE_READING_LEVELS

MARK_POLICY = "marked_only_where_named_pre_modern_texts_give_rules_that_change_the_output"

# 白名單：key → 對外說明與出處。順序即回應中的順序。
CONTESTED_METHODS: dict[str, dict[str, Any]] = {
    "void_of_course_definition": {
        "technique_family": "void_of_course",
        "response_path": "derived_methods.void_of_course",
        "note_zh": (
            "月空亡的定義有兩種，同一張盤可能得到不同結論：Porphyry 名下的"
            "《占星四書導論》（Eisagōgē）第 23 章看月亮在接下來 30° 內是否與行星接合，不管是否換座；"
            "Lilly《Christian Astrology》（1647）p.112 以月亮離開本星座前是否再入相位為準。"
            "本產品採「離開本星座前沒有任何相位精確完成」。"
            "要求換座前精確完成：後人文獻歸於 Al H. Morrison（AFA Bulletin 第 28 卷第 10 期，1966 年 10 月；原是當年 AFA 大會的演講，後來印成 AFA 小冊《The Void of Course Moon》；原文未讀）；"
            "更早的起源尚未查證。"
        ),
        "sources": [
            {
                "citation": (
                    "Ps.-Porphyry, Introduction ch.23 (Boer-Weinstock, CCAG V/4, 1940, p.202)"
                ),
                "says": (
                    "the Moon joins no planet, by sign, degree, aspect or kollesis, within "
                    "the next 30 degrees, regardless of the sign boundary"
                ),
                # Both a Greek transcription and Holden's translation were read; the
                # record does not say the Greek was read closely, so only the
                # translation is claimed until that is confirmed.
                "reading": _TRANSLATION,
                "read_at": (
                    "an online Greek transcription and Holden 2009 trans. p.18, the CCAG "
                    "page itself not checked; level pending: the record does not say "
                    "whether the Greek was read closely enough to count as the original "
                    "language, so only the translation is claimed"
                ),
            },
            {
                "citation": "William Lilly, Christian Astrology (1647) p.112 'Voyd of course'",
                "says": "bounded by the sign",
                "reading": _ORIGINAL,
                "read_at": LILLY_1647_READ_AT,
            },
            {
                "citation": (
                    "Al H. Morrison, a talk at the AFA's 1966 meeting, printed in the AFA "
                    "Bulletin vol. 28 no. 10 (October 1966) and later as the AFA booklet The "
                    "Void of Course Moon"
                ),
                "says": (
                    "requiring exact perfection before the sign exit: attributed to him by "
                    "later literature; an earlier origin has not been checked"
                ),
                "reading": _BIBLIOGRAPHIC,
                "read_at": "the article was not read",
            },
        ],
    },
    "lot_formulas": {
        "technique_family": "lots",
        "response_path": "derived_methods.lots",
        "note_zh": (
            "命運點與精神點的公式有兩種：Ptolemy《占星四書》（Tetrabiblos）III.10 主張"
            "命運點日夜都由太陽量到月亮；Valens《占星選集》（Anthologiae）III.11（Pingree 編號；Kroll／Riley 為 III.14）記載夜盤另依月亮是否已"
            "落下而改式。本產品採夜盤反轉的公式。"
        ),
        "sources": [
            {
                "citation": "Ptolemy, Tetrabiblos III.10 (Robbins numbering; = Hübner III.11)",
                "says": "the Lot of Fortune from Sun to Moon by day and by night",
                "reading": _TRANSLATION,
                "read_at": (
                    "Robbins's English (Loeb 1940): the whole of III.10 read in the "
                    "LacusCurtius transcription, the Lot of Fortune at pp.275-277; the Greek "
                    "not checked"
                ),
            },
            {
                "citation": (
                    "Vettius Valens, Anthologies III.11 (Pingree; = III.14 Kroll/Riley, "
                    "'14K;11P')"
                ),
                "says": "at night the formula changes with whether the Moon has set",
                # The record cites the chapter in two numberings but does not say what
                # was read; only the reference is claimed until that is confirmed.
                "reading": _BIBLIOGRAPHIC,
                "read_at": (
                    "level pending: the record does not say whether the Greek, Pingree's "
                    "or Riley's translation, or a secondary report was read; only the "
                    "reference is claimed until that is confirmed"
                ),
            },
            {
                "citation": "Paulus Alexandrinus, Introduction ch.23",
                "says": "reversal at night (the product's formula)",
                # The first printing is bilingual; which side was read is not recorded,
                # so the lower of the two levels is claimed.
                "reading": _TRANSLATION,
                "read_at": (
                    "the Greek-Latin first printing (Wittenberg 1586); Boer 1958 not "
                    "checked; level pending: the record does not say whether the Greek or "
                    "the Latin translation of that printing was read, so only the "
                    "translation level is claimed"
                ),
            },
        ],
    },
    "bounds_tables": {
        "technique_family": "bounds",
        "response_path": "derived_methods.essential_dignities",
        "technique_key": "bounds",
        "note_zh": (
            "界有多套表並存，同一度數可能歸給不同行星：Ptolemy《占星四書》（Tetrabiblos）I.20–21 並列"
            "埃及界與迦勒底界並加以評比，書中所附的完整界表是否出自 Ptolemy，學界也有爭議。"
            "所以本產品不預設任何一套，由你選表。"
        ),
        "sources": [
            {
                "citation": "Ptolemy, Tetrabiblos I.20-21, trans. Robbins (Loeb 1940) pp.91-107",
                "says": (
                    "Egyptian terms (table p.97), Chaldaean terms rule (pp.99-101), "
                    "complete table p.107"
                ),
                "reading": _TRANSLATION,
                "read_at": "Robbins's English translation (Loeb 1940)",
            },
            {
                "citation": "Tolsa, Philologus 162.2 (2018) 247-264",
                "says": "the authorship of the complete table is disputed",
                "reading": _BIBLIOGRAPHIC,
                "read_at": "abstract only checked",
            },
        ],
    },
    "degree_aspect_orbs": {
        "technique_family": "aspect_orbs",
        "response_path": "derived_methods.aspects",
        "technique_key": "degree_based.in_orb",
        "note_zh": (
            "容許度的數字與算法有好幾種：Lilly《Christian Astrology》（1647）"
            "p.107 並列兩組容許度，並說自己兩組交替使用；al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）"
            "§490 記下六種不同說法。「是否在容許度內」因此取決於所選的表。"
            "另外，本產品的逐度層不要求兩星先在星座上相見，Lilly 1647 p.109 與 al-Bīrūnī "
            "§446 則以此為前提；整宮層另列在同一表。"
        ),
        "sources": [
            {
                "citation": "William Lilly, Christian Astrology (1647) p.107",
                "says": (
                    "two sets of orbs printed side by side; he uses one or the other as "
                    "memory serves"
                ),
                "reading": _ORIGINAL,
                "read_at": LILLY_1647_READ_AT,
            },
            {
                "citation": (
                    "al-Bīrūnī, The Book of Instruction, trans. R. Ramsay Wright (1934) §490"
                ),
                "says": (
                    "5°, 6°, 12°, 15° (the Sun's orb), the average of the two orbs, or "
                    "exact conjunction only"
                ),
                "reading": _TRANSLATION,
                "read_at": "R. Ramsay Wright's English translation (1934)",
            },
            {
                "citation": "William Lilly, Christian Astrology (1647) p.109",
                "says": "aspects presuppose signs that behold one another",
                "reading": _ORIGINAL,
                "read_at": LILLY_1647_READ_AT,
            },
            {
                "citation": "al-Bīrūnī, The Book of Instruction §446",
                "says": "aspects presuppose signs that behold one another",
                "reading": _TRANSLATION,
                "read_at": "R. Ramsay Wright's English translation (1934)",
            },
        ],
    },
    "partile_definition": {
        "technique_family": "partile",
        "response_path": "derived_methods.aspects",
        "technique_key": "degree_based.partile",
        "note_zh": (
            "「同度」的定義有幾種：Lilly《Christian Astrology》（1647）p.106 指兩星恰好相差"
            "構成相位的度數；載於 Lilly 名下的 1677 年曆格言第 25 條，以相差 3 度內為同度；"
            "「1 度以內」的用法則沒有找到具名出處。本產品預設採同一整數度，而且只在兩星的"
            "星座先構成該相位時才判定同度。"
        ),
        "sources": [
            {
                "citation": "William Lilly, Christian Astrology (1647) Book I ch. XIX p.106",
                "says": (
                    "partile: exactly so many degrees apart as make a perfect aspect"
                ),
                "reading": _ORIGINAL,
                "read_at": LILLY_1647_READ_AT,
            },
            {
                "citation": (
                    "Merlini Anglici Ephemeris ... for the Year 1677, 'Useful Astrological "
                    "Aphorisms', no. 25"
                ),
                "says": (
                    "partile within three degrees; the aphorism section is unsigned and "
                    "the prefatory letter is signed William Lilly"
                ),
                "reading": _BIBLIOGRAPHIC,
                "read_at": MERLINI_1677_READ_AT,
            },
            {
                "citation": "Deborah Houlding, Skyscript glossary 'Partile / Platick'",
                "says": "the within-one-degree usage, no named author",
                "reading": _SECONDARY,
                "read_at": "the online glossary entry, a secondary work",
            },
        ],
    },
    "dodecatemoria_formula": {
        "technique_family": "dodecatemoria",
        "response_path": "derived_methods.dodecatemoria",
        "note_zh": (
            "十二分部有兩種算法：Firmicus《Mathesis》II.13 乘以 12，Paulus《導論》（Eisagōgika）第 22 章乘以 13，"
            "同一個點常落在不同星座。本產品預設乘以 12，另一種可在選項裡改選。"
        ),
        "sources": [
            {
                "citation": "Firmicus Maternus, Mathesis II.13 (Kroll-Skutsch numbering)",
                "says": (
                    "degrees and minutes times 12 from the start of the sign; example Sun "
                    "Aries 5 deg 05 min, first degree of Gemini"
                ),
                "reading": _ORIGINAL,
                "read_at": "the Latin text",
            },
            {
                "citation": "Paulus Alexandrinus, Introduction ch.22",
                "says": "degrees times 13; example Aries 11 deg, Leo 23 deg",
                "reading": _SECONDARY,
                "read_at": (
                    "via Greenbaum and Jones, ISAW Papers 12, 2017, para. 185; the Greek "
                    "not checked"
                ),
            },
        ],
    },
    "solar_phase_limits": {
        "technique_family": "solar_phase",
        "response_path": "derived_methods.solar_phase",
        "note_zh": (
            "日輪內、焦傷與在光束下的界線有三套數值：Lilly《Christian Astrology》"
            "（1647）p.113 寫 17′、8°30′、17°，同書格言第 26 條又寫光束下 12°、日輪內 16′；"
            "al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）§481–484 寫日輪內不到 16′、焦傷 6°，"
            "光束下依行星與東西側不同，從 12° 到 18°；希臘化作者只有一條 15° 的線。"
            "本站預設 Lilly p.113，三種分法的結果都列出。"
        ),
        "sources": [
            {
                "citation": "William Lilly, Christian Astrology (1647) p.113",
                "says": "17 minutes, 8 deg 30 min, 17 degrees",
                "reading": _ORIGINAL,
                "read_at": LILLY_1647_READ_AT,
            },
            {
                "citation": "William Lilly, Christian Astrology, aphorism 26 (p.300 per Houlding)",
                "says": "12 degrees and 16 minutes",
                "reading": _ORIGINAL,
                "read_at": "the English text; the page number is Houlding's",
            },
            {
                "citation": "al-Biruni, Book of Instruction, trans. Wright (1934) §481-484",
                "says": (
                    "under 16 minutes, 6 degrees (§481; 7 for Mercury and Venus direct, "
                    "§482), under the rays 12-18 degrees by planet and side (§481: rising "
                    "in the east 12 Venus and Mercury, 15 Saturn and Jupiter, 16 Mars; "
                    "setting in the west 16 Saturn and Jupiter, 18 Mars)"
                ),
                "reading": _TRANSLATION,
                "read_at": "R. Ramsay Wright's English translation (1934)",
            },
            {
                "citation": "Porphyry, Introduction ch.2; Antiochus",
                "says": "one band of 15 degrees",
                "reading": _SECONDARY,
                "read_at": "via Brennan 2017, a secondary work",
            },
        ],
    },
    "hayz_definition": {
        "technique_family": "classical_classifications",
        "response_path": "derived_methods.classical_classifications",
        "note_zh": (
            "hayz 的定義：al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）第 496 節說，夜行星要夜裡在地平上、"
            "白天在地平下，只合這一條叫 halb，再加上行星與星座的陰陽相合才叫 hayyiz（al-Qabīṣī、"
            "Bonatti 相同）；Lilly《Christian Astrology》（1647）第 113 頁說陰性夜行星要夜裡在地平下，"
            "而且沒有 halb 這一層，火星與水星也不在他的定義裡。同一張盤兩種說法常常結果不同，"
            "本產品兩種都列出，不替你挑。"
        ),
        "sources": [
            {
                "citation": "al-Bīrūnī, Kitāb al-tafhīm §496 (Wright 1934)",
                "says": (
                    "a nocturnal planet above the earth by night and below it by day; "
                    "halb, and hayyiz with the sign's gender"
                ),
                "reading": _TRANSLATION,
                "read_at": "Wright's English translation, in the archive.org OCR text",
            },
            {
                "citation": "William Lilly, Christian Astrology (1647) p.113",
                "says": (
                    "a feminine nocturnal planet by night under the earth in a feminine "
                    "sign; no halb"
                ),
                "reading": _ORIGINAL,
                "read_at": "an archive.org OCR text of a modern reset edition",
            },
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
