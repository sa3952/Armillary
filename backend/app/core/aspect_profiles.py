"""Aspect definitions and the named aspect-set, orb and partile profiles.

Tables only: ``core.aspects`` evaluates a chart against them.
"""

from __future__ import annotations

from .source_reading import BIBLIOGRAPHIC_ONLY, ORIGINAL_LANGUAGE_READ, SECONDARY_ONLY, TRANSLATION_READ, cited

# 合相＋四種傳統相位（俗稱「托勒密五大相位」，該俗稱是雙重誤稱）：
# Tetrabiblos I.13 只列四種配置——六分（2 sign／60°）、刑（3／90°）、拱（4／120°）、
# 沖（6／180°）；合相不在該清單。Ptolemy 於 I.24 另以 bodily conjunction 與
# configurations 並列處理，Lilly 1647 p.105 亦說把合相稱為 aspect「very improperly」。
# Kepler, De fundamentis astrologiae certioribus (Pragae 1602) thesis XXXVIII
# 已把古人歸為五個 vulgo dictos aspectus（含合相）並另加三相位；László（Aestimatio 13,
# p.111 勘誤清單第 (23) 條）稱「Ptolemaic aspects」是雙重誤稱，此稱呼在 17 世紀 Kepler 小
# 相位之後才出現。最早書證未窮盡。故合相的 classification 與其餘四者區分。
_TETRABIBLOS_I13 = (
    "Ptolemy, Tetrabiblos I.13 (Robbins LCL 435, 1940; 1964 reprint, same pagination; pp.73-75, "
    "editor's note p.72 n.2 [LacusCurtius n.76]; = Hübner 1998 I.14)"
)
PTOLEMAIC_ASPECTS = (
    {
        "key": "conjunction", "zh": "合", "angle": 0.0, "sign_distance": 0,
        "classification": "classical_bodily_conjunction",
        "source": "Ptolemy, Tetrabiblos I.24 (bodily conjunction, distinct from the I.13 configurations; "
                  "Robbins pp.113-117, p.114 nn.1-2 [LacusCurtius nn.130-131]; = Hübner I.24); computed on ecliptic longitude only - "
                  "I.24's same-side-of-ecliptic latitude condition for bodily application is not "
                  "modelled; Lilly, Christian Astrology (1647) p.105",
    },
    {"key": "sextile", "zh": "六分", "angle": 60.0, "sign_distance": 2, "classification": "classical_major", "source": _TETRABIBLOS_I13},
    {"key": "square", "zh": "刑", "angle": 90.0, "sign_distance": 3, "classification": "classical_major", "source": _TETRABIBLOS_I13},
    {"key": "trine", "zh": "拱", "angle": 120.0, "sign_distance": 4, "classification": "classical_major", "source": _TETRABIBLOS_I13},
    {"key": "opposition", "zh": "沖", "angle": 180.0, "sign_distance": 6, "classification": "classical_major", "source": _TETRABIBLOS_I13},
)

# 六個小相位全部可追到 Kepler（1619 初版頁影核對）：
# - De fundamentis astrologiae certioribus（1602 刊；「1601 撰」無法由印本本身確定）
#   Thesis XXXVIII（1602 印本無頁碼，sig. C1v；哥本哈根皇家圖書館本影像 21）新增五分、倍五分、
#   倍半刑（Frisch I p.428 未核）。
#   135° 因此是早期就加入、1619 才降到最弱一級：kepler_status 記的是它在後期體系的
#   地位（later_downgraded），不是說 1602 沒有它。
# - Harmonices mundi（1619）Lib. IV cap. V：Prop. XII（p.145）第三級含半六分；Prop. XIII
#   （pp.147–148）第四級為五分、倍五分、梅花；Prop. XIV（p.148）第五、最弱一級為十分、
#   倍十分、八分（半刑）、倍八分（倍半刑）。cap. VI p.155：半刑與倍半刑平常沒有作用，
#   主要相位長期缺席時「或許」有作用。
# kepler_status 的狀態值依上述查證命名。30° 與 150° 在希臘化
# 星座教義中正是「不合意」的鄰座／五座距離；Kepler 把它們當 aspect 是逐度幾何的
# 新理論，不是把整宮 aversion「重新發現」成小相位，兩個方法層須分開。
_KEPLERIAN = {"historical_origin": "keplerian", "interpretive_authority": None}
MODERN_MINOR_ASPECTS = (
    {"key": "semisextile", "zh": "半六分", "angle": 30.0, "classification": "modern_minor", "kepler_status": "later_adopted", **_KEPLERIAN},
    {"key": "semisquare", "zh": "半刑", "angle": 45.0, "classification": "modern_minor", "kepler_status": "later_admitted_weakest_grade", **_KEPLERIAN},
    {"key": "quintile", "zh": "五分", "angle": 72.0, "classification": "modern_minor", "kepler_status": "early_core", **_KEPLERIAN},
    {"key": "sesquiquadrate", "zh": "倍半刑", "angle": 135.0, "classification": "modern_minor", "kepler_status": "later_downgraded", **_KEPLERIAN},
    {"key": "biquintile", "zh": "倍五分", "angle": 144.0, "classification": "modern_minor", "kepler_status": "early_core", **_KEPLERIAN},
    {"key": "quincunx", "zh": "梅花／補十二分", "angle": 150.0, "classification": "modern_minor", "kepler_status": "later_adopted", **_KEPLERIAN},
)
KEPLER_STATUSES = (
    "early_core",
    "later_adopted",
    "later_downgraded",
    "later_admitted_weakest_grade",
)
MINOR_ASPECT_ORIGIN_NOTE = (
    "六個小相位均可追到 Kepler；kepler_status 記其在 Kepler 體系內的地位。"
    "later_admitted_weakest_grade：1619 年列入最弱一級，並說平常幾乎沒有作用。"
)

_ASPECT_BY_KEY = {
    aspect["key"]: aspect for aspect in PTOLEMAIC_ASPECTS + MODERN_MINOR_ASPECTS
}

# 小相位只擴充逐度幾何層；整宮 doctrine 仍固定為
# 合相與四種傳統相位。常用 30/45/135/150 與五分相家族 72/144 分開具名，並提供一個
# 明示的聯合集合；所有現代集合都包含合相與四種傳統相位，避免「選小相位後反而遺失主相位」。
ASPECT_SET_PROFILES: dict[str, dict] = {
    "ptolemaic_major_v1": {
        "display_name": "合相＋四種傳統逐度相位",
        "aspect_keys": ["conjunction", "sextile", "square", "trine", "opposition"],
        "method_classification": "classical_major_degree_aspects",
        "source": "Ptolemy, Tetrabiblos I.13 (four configurations) and I.24 (bodily conjunction)",
        # 識別碼保留以維持 API 相容；名稱不宣稱五者皆出自 Ptolemy。
        "name_note": {
            "colloquial_name": "五大相位",
            "colloquial_name_status": "modern_collective_label_not_a_historical_classification",
            "reason": (
                "Tetrabiblos I.13 只列六分／刑／拱／沖四種配置；合相於 I.24 另行處理，"
                "Lilly 1647 p.105 亦稱把合相叫 aspect 是 very improperly。"
            ),
        },
    },
    "modern_common_minor_v1": {
        "display_name": "合相與四種傳統相位＋常用 Keplerian 小相位",
        "aspect_keys": [
            "conjunction", "semisextile", "semisquare", "sextile", "square",
            "trine", "sesquiquadrate", "quincunx", "opposition",
        ],
        "method_classification": "modern_degree_aspect_geometry",
        "source": "product_selected_profile",
    },
    "modern_quintile_family_v1": {
        "display_name": "合相與四種傳統相位＋五分相家族（Keplerian）",
        "aspect_keys": [
            "conjunction", "sextile", "quintile", "square", "trine",
            "biquintile", "opposition",
        ],
        "method_classification": "modern_degree_aspect_geometry",
        "source": "product_selected_profile",
    },
    "modern_minor_combined_v1": {
        "display_name": "合相與四種傳統相位＋常用小相位＋五分相家族（Keplerian）",
        "aspect_keys": [
            "conjunction", "semisextile", "semisquare", "sextile", "quintile",
            "square", "trine", "sesquiquadrate", "biquintile", "quincunx",
            "opposition",
        ],
        "method_classification": "modern_degree_aspect_geometry",
        "source": "product_selected_profile",
    },
}

_SIGN_DISTANCE_TO_ASPECT = {
    aspect["sign_distance"]: aspect for aspect in PTOLEMAIC_ASPECTS
}

# 容許度邊界 ≤ 是產品慣例（理由見 boundary_note）：Lilly、al-Bīrūnī、Bonatti 都沒有明文規定；
# Lilly 1647 p.110「fully 9 degrees distant」只是傾向不含邊界，不是明文。
ORB_BOUNDARY_OPERATOR = "<="
ORB_BOUNDARY_RECEIPT = {
    "boundary_operator": ORB_BOUNDARY_OPERATOR,
    "boundary_provenance": "product_convention",
    "boundary_note": (
        "恰好等於容許度時算在容許度內（≤）。古典文本沒有明文規定；Lilly 1647 p.110 "
        "讀起來傾向不算，但恰好相等在實際星盤上幾乎不會發生，所以本產品維持 ≤，"
        "並標明這是產品慣例。"
    ),
}

# 數值表與「兩星 orb 如何合成門檻」是兩個不同的來源宣稱。
# Lilly p.107 自己寫出 moiety 合成規則並舉例（p.110 再寫一次）；Abū Maʿshar 一系的
# 數值表套用同一條 (orb_a + orb_b) / 2，是本產品在該傳統的諸說中選定一說：al-Bīrūnī §490
# 把「兩星 orb 的平均」列為諸說之一。Abū Maʿshar《大導論》（Kitāb al-mudkhal al-kabīr）2019 校勘英譯本的七個數值在
# VII.3 行 204–210，入相位／離相位在 VII.5 行 443–465，那幾行沒有寫出平均式；VII.4 行
# 354–389 在該版談合相的性質，不是兩星門檻。
# 為此有一個閉集值；數值不動。
#   named_author_text                    — 具名作者自己寫出的合成規則（Lilly p.107）
#   one_of_views_recorded_in_named_text  — 具名文本記載的諸說之一，產品從中選定（al-Bīrūnī §490）
#   product_normalization                — 沒有文本依據、產品自定的合成規則
PAIR_COMBINATION_RULE_PROVENANCE_STATES = (
    "named_author_text",
    "one_of_views_recorded_in_named_text",
    "product_normalization",
)

_AS_TABULATED_BY_BIRCHFIELD = (
    "as tabulated by Steven Birchfield, 'Orbs of Influence' (2nd ed. 2013); the "
    "primary text was not independently transcribed"
)

ORB_PROFILES: dict[str, dict] = {
    # 鍵名說「lineage」而非「consensus」：重複出現的數字證明的是傳承，不是彼此獨立的
    # 來源一致（見 source_verification.independence_claim_withdrawn）。
    "abu_mashar_lineage_v1": {
        "display_name": "Abu Ma'shar 一系傳承的重複數值",
        "rule": "moiety",
        "orbs_degrees": {
            "sun": 15.0,
            "moon": 12.0,
            "mercury": 7.0,
            "venus": 7.0,
            "mars": 8.0,
            "jupiter": 9.0,
            "saturn": 9.0,
        },
        "provenance": (
            "recurring_value_in_one_transmission_lineage_secondary_tabulation"
        ),
        "pair_combination_rule_provenance": "one_of_views_recorded_in_named_text",
        "source_verification": {
            "primary_texts_independently_transcribed": False,
            "independence_claim_withdrawn": (
                "Holden notes a probable derivation relationship between the "
                "Porphyry chapter and Sahl; Pingree regards chs. 53-55 as a "
                "later insertion. Repetition across medieval authors evidences "
                "transmission, not independent attestation."
            ),
            "retracted_claim": "five_independent_pre_modern_sources_in_agreement",
            "renamed_from": "abu_mashar_consensus_v1",
            "evidence_standard": "secondary_tabulation_permitted_when_disclosed",
        },
        "tabulated_from": [
            cited("Steven Birchfield, 'Orbs of Influence', 2nd ed. 2013",
                  "the seven orb values of this table", SECONDARY_ONLY,
                  ("Birchfield's secondary tabulation, from which the table was taken; "
                   "the primary texts were not independently transcribed")),
        ],
        "sources": [
            cited(("Introduction to the Tetrabiblos under Porphyry's name, §55, a later "
                   "added passage (chs. 53-55, regarded by Pingree as a later insertion; "
                   "Holden notes a probable derivation link with Sahl) (trans. Holden, AFA 2009)"),
                  "the seven orb values of this table", SECONDARY_ONLY,
                  _AS_TABULATED_BY_BIRCHFIELD),
            cited(("Abū Maʿshar, Abbreviation of the Introduction to Astrology II.11-12 "
                   "(Burnett-Yamamoto-Yano, Brill 1994; ARHAT ed. 1997, 2nd printing "
                   "2000); Dykes, ITA (2010) §II.6 pp.90-91"),
                  "the seven orb values of this table", SECONDARY_ONLY,
                  _AS_TABULATED_BY_BIRCHFIELD),
            cited(("Abū Maʿshar, The Great Introduction to Astrology, ed. Yamamoto, "
                   "Burnett and Pingree (2019), VII.3 lines 204-210 and VII.5 lines "
                   "443-465"),
                  ("the seven values (VII.3 lines 204-210); application and separation "
                   "(VII.5 lines 443-465)"),
                  TRANSLATION_READ,
                  ("the edition's English translation; the Arabic text and the Dykes "
                   "ITA (2010) locators are not compared")),
            cited(("Sahl ibn Bishr, Introduction ch.3 §§13-18, trans. Dykes, The "
                   "Astrology of Sahl b. Bishr vol. I (Cazimi 2019)"),
                  "the seven orb values of this table", SECONDARY_ONLY,
                  ("via Birchfield, The Planets Degrees of Influence (rev. 2019) "
                   "pp.5-6 n.12")),
            cited("Ibn Ezra, The Beginning of Wisdom ch. IV (trans. Epstein, ARHAT 1998)",
                  "the seven orb values of this table", SECONDARY_ONLY,
                  _AS_TABULATED_BY_BIRCHFIELD),
            cited(("Guido Bonatti, De astronomia tractatus X (Basel 1550), tractatus III "
                   "part 1 chs. I-VII (one chapter per planet), cols.100-116"),
                  ("the same seven values, one in each planet's chapter ('Et quantitas "
                   "orbis eius est ... graduum'): Saturn 9 (col.100), Jupiter 9 (col.102), "
                   "Mars 8 (col.105), Sun 15 (col.107), Venus 7 (col.111), "
                   "Mercury 7 (col.113), Moon 12 (col.116)"),
                  ORIGINAL_LANGUAGE_READ,
                  ("the Latin in the archive.org scan bub_gb_BgWuc5O-JzIC: Saturn, "
                   "Jupiter and Moon read on the scanned columns (n67 = cols.99-100, "
                   "n68 = cols.101-102, n75 = cols.115-116); Mars col.105 (n70), Sun "
                   "col.107 (n71), Venus col.111 (n73) and Mercury col.113 (n74) also read "
                   "on the scanned columns")),
            cited(("al-Bīrūnī, The Book of Instruction in the Elements of the Art of "
                   "Astrology, trans. R. Ramsay Wright (London: Luzac 1934) §436"),
                  "the same seven values", TRANSLATION_READ,
                  ("Wright's translation in the archive.org reproduction of the 1934 "
                   "typescript; cited by section")),
        ],
        "pair_combination_rule_note": (
            "The pair threshold is the average of the two orbs. al-Bīrūnī, Book of "
            "Instruction §490, lists it as one of several views on where application "
            "begins (others: 5°, 6°, 12°, 15° the Sun's orb, exact conjunction only). "
            "Abū Maʿshar, Great Introduction (2019 ed.), gives the seven values in "
            "VII.3 lines 204-210 and treats application and separation in VII.5 lines "
            "443-465, in terms of each planet's own orb; those lines state no "
            "averaging formula. The product applies the average to this table: one "
            "attested view chosen among several."
        ),
    },
    "lilly_1647_experience_v1": {
        "display_name": "William Lilly 1647 自述經驗值",
        "rule": "moiety",
        "orbs_degrees": {
            "sun": 17.0,
            "moon": 12.5,
            "mercury": 7.0,
            "venus": 8.0,
            "mars": 7.5,
            "jupiter": 12.0,
            "saturn": 10.0,
        },
        "provenance": "single_named_author_stated_as_personal_experience",
        "pair_combination_rule_provenance": "named_author_text",
        "source_verification": {
            # p.107 was read on first-edition page images and the first column
            # matches; the profile counts as checked on that reading.
            "primary_texts_independently_transcribed": True,
            "evidence_standard": "checked_against_first_edition_page_images",
        },
        "tabulated_from": [
            cited("William Lilly, Christian Astrology (1647) p.107, first column",
                  "the seven orbs of this table", ORIGINAL_LANGUAGE_READ,
                  ("the first edition (archive.org/details/b30338724); the 1659 second "
                   "edition has the same pagination and readings")),
            cited("Steven Birchfield, 'Orbs of Influence', 2nd ed. 2013",
                  "the same values as p.107's first column", SECONDARY_ONLY,
                  "Birchfield's secondary tabulation; it agrees with p.107"),
        ],
        "sources": [
            cited(("William Lilly, Christian Astrology (1647) Book I ch. XIX p.107, "
                   "first column"),
                  ("the planets' orbs, the first column given as those of 'the best "
                   "Authors and my owne Experience'"),
                  ORIGINAL_LANGUAGE_READ, "the first edition (archive.org/details/b30338724)"),
            cited("William Lilly, Christian Astrology (1647) Book I p.110",
                  "a separation example that uses the second set of orbs",
                  BIBLIOGRAPHIC_ONLY,
                  ("level pending: the record describes the example but does not say "
                   "which copy was read; only the reference is claimed")),
        ],
        "second_set_not_used": (
            "p.107 prints a second set beside the first (Saturn 9, Jupiter 9, Mars 7, "
            "Sun 15, Venus 7, Mercury 7, Moon 12; rows marked 'According to others', "
            "'All consent' and the like), and Lilly says he uses one or the other as "
            "memory serves; his separation example on p.110 uses the second set. The "
            "product offers only the first set, the one he gives as 'the best Authors "
            "and my owne Experience'."
        ),
    },
}

# Status flags stay in the response; the citation prose of each orb profile is a
# method source register entry.
_ORB_PROFILE_REGISTER_ONLY_KEYS = frozenset({
    "sources",
    "tabulated_from",
    "source_verification",
    "pair_combination_rule_note",
    "second_set_not_used",
})
SOURCE_VERIFICATION_STATUS_KEYS = (
    "primary_texts_independently_transcribed",
    "evidence_standard",
)


# Partile 的三種具名慣例，做成 profile；沒有哪一種是「傳統定義」。三者並存且會給出
# 不同答案（金牛 29.9° 與處女 0.1° 只在「1 度以內」與「3 度以內」下是 partile），其中
# 兩種都載於 Lilly 名下而互相矛盾（1647 同一整數度、1677 三度以內）。來源與查核狀態見
# 各 profile 的 sources、_PARTILE_SOURCE_VERIFICATION 與 PARTILE_TABULATED_FROM（二手轉引，原文未獨立轉錄）；
# Houlding 條目裡的編輯意見不是來源，不編入權威欄位。None＝該判準沒有星座相位前置條件。
PARTILE_PRECONDITION_SIGN_ASPECT = "whole_sign_aspect_or_angle_orb_lilly_1647"
_HOULDING_PARTILE = "Deborah Houlding, Skyscript glossary 'Partile / Platick'"
_HOULDING_READ_AT = "the online glossary entry, a secondary work"
MERLINI_1677_READ_AT = (
    "the 1677 almanac itself, read in the archive.org scan of the printed copy "
    "(bim_early-english-books-1641-1700_merlini-anglici-ephemeri_almanacs-lilly-william_1677, "
    "leaf n32, aphorisms 15-29, no signature on that leaf); the prefatory letter is signed "
    "William Lilly, Hersham, 26 Sept. 1676"
)
LILLY_1647_READ_AT = (
    "reading level as recorded; the record does not say which copy of the 1647 English text "
    "was read"
)
PARTILE_PROFILES: dict[str, dict] = {
    "same_degree_number_v1": {
        "display_name": "同一整數度",
        "rule": "same_integer_degree_of_sign",
        "threshold_degrees": None,
        "provenance": "lilly_christian_astrology_1647_and_general_usage",
        "sources": [
            cited("William Lilly, Christian Astrology (1647) Book I ch. XIX p.106",
                  ("partile definition and examples; Lilly writes 'exactly so many "
                   "degrees ... as make a perfect aspect', not 'same degree': the "
                   "same-degree reading is Houlding's"),
                  ORIGINAL_LANGUAGE_READ, LILLY_1647_READ_AT),
            cited(_HOULDING_PARTILE,
                  "partile read as the same degree, the usage she records as the commonest",
                  SECONDARY_ONLY, _HOULDING_READ_AT),
        ],
        "note": (
            "Houlding 記為最通行的用法。兩星必須落在各自星座的同一個整數度，"
            "與角距離無關。"
        ),
        # 「同度須先整宮相見」只屬於這個（Lilly 1647）判準。
        "valid_aspect_precondition": PARTILE_PRECONDITION_SIGN_ASPECT,
    },
    "within_one_degree_v1": {
        "display_name": "距精確 1 度以內",
        "rule": "absolute_offset_within_threshold",
        "threshold_degrees": 1.0,
        # 二手（Houlding）轉述「traditional authors 曾用」，本輪未定位任何具名前現代
        # 作者（方法研究筆記；另一份核對清單亦列為未解）。不得讓使用者看到 traditional
        # 就以為已核原典，故降為 secondary_reported。
        "provenance": "secondary_reported_traditional_usage",
        "sources": [
            cited(_HOULDING_PARTILE,
                  ("partile within one degree, recorded as the usage of traditional "
                   "authors without naming any individual author"),
                  SECONDARY_ONLY, _HOULDING_READ_AT),
        ],
        "note": "只看距離精確相位的角差，與整數度無關。具名前現代來源至今未定位。",
        "valid_aspect_precondition": None,
    },
    "lilly_1677_three_degrees_v1": {
        "display_name": "Lilly 1677：距精確 3 度以內",
        "rule": "absolute_offset_within_threshold",
        "threshold_degrees": 3.0,
        # 格言節未署名，所以 provenance 不說「his own」。
        "provenance": "lilly_attributed_merlini_anglici_1677_differs_from_1647",
        "sources": [
            cited(("Merlini Anglici Ephemeris ... for the Year 1677 (London: J. Macock for "
                   "the Company of Stationers), 'Useful Astrological Aphorisms for Young "
                   "Students and others', no. 25"),
                  "partile within the difference of three degrees", ORIGINAL_LANGUAGE_READ,
                  MERLINI_1677_READ_AT),
            cited(_HOULDING_PARTILE, "cited beside the 1677 aphorism for the three-degree usage",
                  SECONDARY_ONLY, _HOULDING_READ_AT),
        ],
        # 格言第 25 條確有此句，但該節未署名；冊首致讀者書署名
        # William Lilly（1676-09-26）並指定 Coley 為承續者。1675、1676、1678 冊都沒有這句。
        # 只能說「載於 Lilly 名下」，不能說「Lilly 本人改寫」；也不寫「Coley 代筆」（推測）。
        "note": (
            "載於 Lilly 名下 1677 年曆《Merlini Anglici Ephemeris》的格言第 25 條以相差三度內"
            "為 partile，與《Christian Astrology》1647 的同度定義不一致；該格言節未署名，"
            "作者意圖未知，兩者分別具名並列。"
        ),
        # 1677 原文「within the difference of three degrees」對恰好 3° 整未給
        # inclusive／exclusive 定義；本實作取 |offset| ≤ 3° 是產品慣例。
        "inclusive_boundary": "product_convention",
        "valid_aspect_precondition": None,
    },
}

PARTILE_VALID_ASPECT_RULE = (
    "lilly_1647_same_degree_requires_whole_sign_configuration_angle_pairs_use_in_orb;"
    "degree_offset_profiles_use_their_threshold_only"
)
PARTILE_REASON_CODES = (
    "partile_profile_not_applicable_to_modern_minor_aspect",
    "no_aspect_verdict_available_for_partile",
    "same_degree_without_whole_sign_aspect",
    "no_whole_sign_aspect_for_partile",
    "angle_pair_not_in_orb_for_partile",
)
# 收據說明（常數，每份回應只出現一次）：為什麼 Lilly 1647 的同度要先看星座，其他判準不必。
PARTILE_VALID_ASPECT_BASIS = {
    "rule": PARTILE_VALID_ASPECT_RULE,
    "note": (
        "依 Lilly 1647 的同一整數度判準判同度時，兩星必須先在整宮上構成該相位："
        "星座先相隔該相位的星座數，再看是否落在各自星座的同一度；容許度設定不影響這一步。"
        "依據：Lilly 1647 p.106 的同度例都先是星座相位，p.109 說不相見的星座之間沒有相位；"
        "al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）§446 把同度定義在星座相見之下。"
        "上升點、中天沒有整宮教義，改用軸點容許度判定。"
        "距精確 1° 以內與 Lilly 1677 三度以內兩種判準依各自的度數定義，"
        "只看距精確相位的角差，不要求星座先相見。"
    ),
    "source_ref": "aspects/partile",
}

_PARTILE_SOURCE_VERIFICATION = {
    "primary_texts_independently_transcribed": False,
    "evidence_standard": "secondary_tabulation_permitted_when_disclosed",
}
# What the partile conventions were tabulated from (register only).
PARTILE_TABULATED_FROM = (
    cited(_HOULDING_PARTILE,
          ("the partile conventions; she cites Lilly's Christian Astrology p.107 - the "
           "definition runs pp.106-107 of the 1647 printing, the example is on p.106"),
          SECONDARY_ONLY, _HOULDING_READ_AT),
    cited("Merlini Anglici Ephemeris ... for the Year 1677",
          "partile within three degrees (aphorism no. 25)", ORIGINAL_LANGUAGE_READ,
          MERLINI_1677_READ_AT),
)
