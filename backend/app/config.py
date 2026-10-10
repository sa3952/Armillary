"""古典占星計算所需的固定設定：星體清單、恆星清單、宮位制代碼、ayanamsa選項、預設容許誤差。"""

from typing import Any

import swisseph as swe

# Public request-contract boundary.  Consumers that expose or describe the
# accepted year range import this tuple instead of duplicating the numbers.
PRODUCT_YEAR_RANGE = (1900, 2399)

# 古典七政
CLASSICAL_BODIES = [
    {"key": "sun", "zh": "太陽", "id": swe.SUN},
    {"key": "moon", "zh": "月亮", "id": swe.MOON},
    {"key": "mercury", "zh": "水星", "id": swe.MERCURY},
    {"key": "venus", "zh": "金星", "id": swe.VENUS},
    {"key": "mars", "zh": "火星", "id": swe.MARS},
    {"key": "jupiter", "zh": "木星", "id": swe.JUPITER},
    {"key": "saturn", "zh": "土星", "id": swe.SATURN},
]

# 現代外行星（三王星，非古典占星本體，預設不計算，使用者可另外勾選）
OUTER_BODIES = [
    {"key": "uranus", "zh": "天王星", "id": swe.URANUS},
    {"key": "neptune", "zh": "海王星", "id": swe.NEPTUNE},
    {"key": "pluto", "zh": "冥王星", "id": swe.PLUTO},
]

# The parameters Swiss Ephemeris 2.10.03 swe_pheno uses for Chiron's
# apparent diameter and magnitude, built into the library (swecl.c pla_diam[] in
# sweph.h, 271370 m; mag_elem[] "from Bowell data base", H 6.5, G 0.15, IAU H-G
# phase law).  They are disclosed, not overridden: JPL SBDB lists
# 166 km (Dunham 1998) and H 5.54, and the literature has other values again.
# tests/backend/test_astronomy_disclosures.py reproduces the emitted diameter and
# magnitude from these numbers, so a library change cannot leave them stale.
CHIRON_PHYSICAL_PARAMETERS_SOURCE_REF = "chiron/physical_parameters"
_CHIRON_BUILTIN_DIAMETER_KM = 271.37
_CHIRON_BUILTIN_H = 6.5
_CHIRON_BUILTIN_G = 0.15
# The comparison values a reader is told about (JPL SBDB, retrieved 2026-10-04).
CHIRON_JPL_SBDB_REFERENCE: dict[str, Any] = {
    "diameter_km": 166.0,
    "absolute_magnitude_h": 5.54,
    "retrieved": "2026-10-04",
}
# Disclose the source, do not override it, and say
# so in words a reader understands.  The sentence is built from the numbers
# above, so it cannot drift from the parameters it explains.
CHIRON_PHYSICAL_PARAMETERS_EXPLANATION_ZH = (
    "凱龍星的「視直徑」與「視星等」，是用星曆程式 Swiss Ephemeris 內建的大小與亮度"
    f"參數算出來的：直徑 {_CHIRON_BUILTIN_DIAMETER_KM:g} 公里、絕對星等 {_CHIRON_BUILTIN_H:g}。"
    "美國 JPL 小天體資料庫目前列的是直徑約 "
    f"{CHIRON_JPL_SBDB_REFERENCE['diameter_km']:g} 公里、絕對星等 "
    f"{CHIRON_JPL_SBDB_REFERENCE['absolute_magnitude_h']:g}；照那組數值算，視直徑會小約 "
    f"{round((1 - CHIRON_JPL_SBDB_REFERENCE['diameter_km'] / _CHIRON_BUILTIN_DIAMETER_KM) * 100)}%，"
    f"看起來亮約 {_CHIRON_BUILTIN_H - CHIRON_JPL_SBDB_REFERENCE['absolute_magnitude_h']:.2f} 等。"
    "凱龍星有多大，不同文獻本來就說法不一，所以本站照實標明用的是哪一組，不自行改值。"
    "凱龍星在天上的位置不受這組參數影響。"
)
CHIRON_PHYSICAL_PARAMETERS: dict[str, Any] = {
    "source": "swiss_ephemeris_2_10_03_builtin_table",
    "diameter_km": _CHIRON_BUILTIN_DIAMETER_KM,
    "absolute_magnitude_h": _CHIRON_BUILTIN_H,
    "phase_slope_g": _CHIRON_BUILTIN_G,
    "magnitude_model": "iau_h_g_two_parameter",
    "explanation_zh": CHIRON_PHYSICAL_PARAMETERS_EXPLANATION_ZH,
    "source_ref": CHIRON_PHYSICAL_PARAMETERS_SOURCE_REF,
}

# 現代小天體。與三王星分開設選項，避免「include_outer_planets」在不知情下
# 擴張成另一套物件集合。這些物件不自動加入古典方法或相位參與者。
MODERN_MINOR_BODIES = [
    {
        "key": "chiron",
        "zh": "凱龍星",
        "id": swe.CHIRON,
        "calculation_source": "swiss_ephemeris_minor_planet",
        "method_classification": "modern_body_not_classical_planet",
        "physical_parameters": CHIRON_PHYSICAL_PARAMETERS,
    },
]

# 這些是月球軌道遠近地點，不是
# 物理天體，也不是小行星 1181 Lilith。Natural Priapus 必須用 Swiss 的
# INTP_PERG 獨立計算；Swiss 文件明示 natural apogee/perigee 通常不精確對沖。
LUNAR_APSIDES = [
    {
        "key": "mean_lilith",
        "zh": "平均黑月 Lilith",
        "id": swe.MEAN_APOG,
        "expose_swiss_body_id": True,
        "calculation_source": "swiss_ephemeris_mean_lunar_apogee",
        "method_classification": "modern_research_lunar_apsis_not_physical_body",
        "naming_note": (
            "Swiss Ephemeris mean lunar apogee; astrological Mean Black Moon "
            "Lilith, not asteroid 1181 Lilith"
        ),
    },
    {
        "key": "natural_lilith",
        "zh": "自然／插值月球遠地點（Lilith）",
        "id": swe.INTP_APOG,
        "expose_swiss_body_id": True,
        "calculation_source": (
            "swiss_ephemeris_interpolated_natural_lunar_apogee"
        ),
        "method_classification": "modern_research_lunar_apsis_not_physical_body",
        "naming_note": (
            "Swiss Ephemeris interpolated/natural lunar apogee; not the "
            "osculating point marketed as True Lilith"
        ),
    },
    {
        "key": "natural_priapus",
        "zh": "自然／插值月球近地點（Priapus）",
        "id": swe.INTP_PERG,
        "expose_swiss_body_id": True,
        "calculation_source": (
            "swiss_ephemeris_interpolated_natural_lunar_perigee"
        ),
        "method_classification": "modern_research_lunar_apsis_not_physical_body",
        "naming_note": (
            "Swiss Ephemeris interpolated/natural lunar perigee (Priapus); "
            "independently calculated, not Lilith plus 180 degrees"
        ),
    },
]

# 南北交點
#
# 標籤刻意不用「真交點」。Swiss Ephemeris General Documentation 自己說得很清楚：
#   §2.2.2 "In the strict sense of the word, even the 'true' nodes are true only twice a
#    month, viz. at the times when the Moon crosses the ecliptic."
#   §2.2.5 "There are no planetary nodes or apsides ... that really deserve the label
#    'true'. ... It is more appropriate to call them 'osculating'."
# （第二句在 §2.2.5，不在 §2.2.2。）
# 所謂真交點是密切軌道(osculating orbit)的交點：把此刻的瞬時軌道當成兩體問題來解，
# 只在月亮實際穿越黃道的那兩個時刻為真，其餘時間是數學構造。它在平均交點附近振盪；
# 本產品以內建星曆在 1800–2400 年每 6 小時比較：最大差 1.98°、中位數 1.04°。1950–2050
# 年平均每年約 27 次短暫順行、合計約 94 天——那個順行是模型產物，不是天象。Swiss 文件
# 沒有給振盪幅度；上述數字可用本產品內建星曆以每 6 小時取樣重算（自算腳本未隨原始碼發布）。
#
# **正式技法採平均交點**，
# 理由是古代與中世紀的主要天文表以平均運動給交點（Ptolemy《Handy Tables》、印度 siddhānta）；
# Tycho（1587 年之後）已發現交點運動不均勻並給出改正（Dreyer 1890 ch.XII，真平差可達
# 1°46′），但那不是現代的密切交點，前現代技法也不以它為輸入。
# 本產品定位為古典西洋占星。兩者仍並列輸出，因為差距最大約 2°，讀者有權看到。
#
# API 鍵值 true_node 維持不變以保相容；顯示標籤如實寫「密切」。
NODE_BODIES = [
    {"key": "true_node", "zh": "北交點(密切)", "id": swe.TRUE_NODE},
    {"key": "mean_node", "zh": "北交點(平均)", "id": swe.MEAN_NODE},
]

BODY_ID_BY_KEY = {
    body["key"]: body["id"]
    for body in (
        CLASSICAL_BODIES + OUTER_BODIES + MODERN_MINOR_BODIES + NODE_BODIES
    )
}

# 產品恆星清單（名稱需與 sefstars.txt 內拼寫完全一致，大小寫不拘）。前 15 顆依
# Agrippa, De occulta philosophia I.32（星名表）與 II.47（Behenian 星像）的 Behenian
# 十五星（Pleiades 以 Alcyone 代表；Ala Corvi 取 δ Crv Algorab，Agrippa 未指明）；其餘 19 顆
# 由產品自選；清單來歷不對使用者標示。
FIXED_STARS = [
    {"key": "algol", "zh": "大陵五", "name": "Algol"},
    {"key": "alcyone", "zh": "昴宿六(昴星團)", "name": "Alcyone"},
    {"key": "aldebaran", "zh": "畢宿五", "name": "Aldebaran"},
    {"key": "capella", "zh": "五車二", "name": "Capella"},
    {"key": "sirius", "zh": "天狼星", "name": "Sirius"},
    {"key": "procyon", "zh": "南河三", "name": "Procyon"},
    {"key": "regulus", "zh": "軒轅十四", "name": "Regulus"},
    {"key": "alkaid", "zh": "搖光(大熊座η)", "name": "Alkaid"},
    {"key": "algorab", "zh": "軫宿三", "name": "Algorab"},
    {"key": "spica", "zh": "角宿一", "name": "Spica"},
    {"key": "arcturus", "zh": "大角", "name": "Arcturus"},
    {"key": "alphecca", "zh": "貫索四", "name": "Alphecca"},
    {"key": "antares", "zh": "心宿二", "name": "Antares"},
    {"key": "vega", "zh": "織女一", "name": "Vega"},
    {"key": "deneb_algedi", "zh": "壘壁陣四", "name": "Deneb Algedi"},
    {"key": "rigel", "zh": "參宿七", "name": "Rigel"},
    {"key": "altair", "zh": "河鼓二(牛郎星)", "name": "Altair"},
    {"key": "castor", "zh": "北河二", "name": "Castor"},
    {"key": "pollux", "zh": "北河三", "name": "Pollux"},
    {"key": "betelgeuse", "zh": "參宿四", "name": "Betelgeuse"},
    {"key": "alpheratz", "zh": "壁宿二", "name": "Alpheratz"},
    {"key": "mira", "zh": "蒭藁增二", "name": "Mira"},
    {"key": "bellatrix", "zh": "參宿五", "name": "Bellatrix"},
    {"key": "canopus", "zh": "老人星", "name": "Canopus"},
    {"key": "vindemiatrix", "zh": "東次將", "name": "Vindemiatrix"},
    {"key": "fomalhaut", "zh": "北落師門", "name": "Fomalhaut"},
    {"key": "achernar", "zh": "水委一", "name": "Achernar"},
    {"key": "polaris", "zh": "勾陳一(北極星)", "name": "Polaris"},
    {"key": "deneb", "zh": "天津四", "name": "Deneb"},
    {"key": "hadar", "zh": "馬腹一", "name": "Hadar"},
    # sefstars.txt 裡 "Menkar" 這個名字被兩顆不同的星共用（alCet 鯨魚座α本尊，
    # 與較暗的 laCet 鯨魚座λ），純文字查詢 "Menkar" 實測會比對到後者（星等4.7，
    # 並非一般認知、星等2.53 的鯨魚座α）。用 "名稱,星座縮寫" 格式明確指定星座編號解除歧義。
    {"key": "menkar", "zh": "天囷一", "name": "Menkar,alCet"},
    {"key": "schedar", "zh": "王良四", "name": "Schedar"},
    {"key": "hamal", "zh": "婁宿三", "name": "Hamal"},
    {"key": "zubenelgenubi", "zh": "氐宿一", "name": "Zubenelgenubi"},
]

# 恆星中文名的查證狀態。閉集。
# - corrected_against_cited_star_name_table：依具名對照表、對著 Swiss 目錄實際比對到的星體
#   （Bayer 代號）更正過標籤。
# - checked_against_cited_star_name_table：標籤與具名對照表的同一 Bayer 星相符，未改。
#   產品在表名後加的括號說明（如「（牛郎星）」）與表上的「天狼」「老人」不加「星」不算不符。
# - unverified：本產品沒有逐一核對，不是「已確認正確」，也不是「已知有誤」。
# 每筆更正與核對所依的對照表記在 cited_tables；何時、由誰核對不給使用者看。
FIXED_STAR_ZH_NAME_STATES = (
    "corrected_against_cited_star_name_table",
    "checked_against_cited_star_name_table",
    "unverified",
)
FIXED_STAR_ZH_NAME_TABLES = {
    "hksm_bright_stars": (
        "香港太空館〈亮星中英對照表〉（星座與神話，教師專區），繁體版"
    ),
    "tam_journal_2017_02_mira": (
        "臺北市立天文科學教育館《天文館期刊》2017 年 2 月，p.32"
        "〈不可思議的星星：蒭藁增二〉"
    ),
    "zh_wikipedia_star_name_table": "zh.wikipedia〈中西星名對照表〉",
}
FIXED_STAR_ZH_NAME_CORRECTIONS: dict[str, dict[str, Any]] = {
    "algorab": {
        "status": "corrected_against_cited_star_name_table",
        "previous_label": "軫宿一",
        "swiss_catalogue_designation": "deCrv",
        "reason": (
            "per the cited tables 軫宿一 is γ Crv; the catalogue record matched "
            "here is δ Crv, which the tables name 軫宿三"
        ),
        "cited_tables": ["zh_wikipedia_star_name_table", "hksm_bright_stars"],
    },
    "mira": {
        "status": "corrected_against_cited_star_name_table",
        # The label shipped before any correction, as for Algorab.
        "previous_label": "芻蒿增二",
        "swiss_catalogue_designation": "omiCet",
        "reason": (
            "the cited Taipei Astronomical Museum article names ο Ceti 蒭藁增二 "
            "(蒭 is a variant of 芻); the earlier label 芻蒿增二 had the wrong "
            "asterism character"
        ),
        "cited_tables": ["tam_journal_2017_02_mira"],
    },
}
# 依香港太空館表核對相符、未改標籤的 32 顆（Algorab、Mira 另列於上）。
FIXED_STAR_ZH_NAME_CHECKED: dict[str, dict[str, Any]] = {
    key: {
        "status": "checked_against_cited_star_name_table",
        "cited_tables": ["hksm_bright_stars"],
    }
    for key in (
        "algol", "alcyone", "aldebaran", "capella", "sirius", "procyon",
        "regulus", "alkaid", "spica", "arcturus", "alphecca", "antares",
        "vega", "deneb_algedi", "rigel", "altair", "castor", "pollux",
        "betelgeuse", "alpheratz", "bellatrix", "canopus", "vindemiatrix",
        "fomalhaut", "achernar", "polaris", "deneb", "hadar", "menkar",
        "schedar", "hamal", "zubenelgenubi",
    )
}

# 宮位制代碼 (swe_houses hsys 單一字元)
HOUSE_SYSTEMS = {
    "B": "Alcabitius",
    "R": "Regiomontanus",
    "W": "Whole Sign",
    "P": "Placidus",
}

# 古典占星脈絡下較站得住腳的西方歷史性 ayanamsa（非印度占星常用的 Lahiri/KP）
AYANAMSA_OPTIONS = {
    "fagan_bradley": swe.SIDM_FAGAN_BRADLEY,
    "hipparchos": swe.SIDM_HIPPARCHOS,
    "sassanian": swe.SIDM_SASSANIAN,
    "aldebaran_15_tau": swe.SIDM_ALDEBARAN_15TAU,
}

# 預設容許誤差 (度)
DECLINATION_ASPECT_ORB = 1.0

# 月空亡(VOC)判斷用的合相與四種傳統相位角度（常數名是既有識別碼，不宣稱五者皆出自 Ptolemy）
PTOLEMAIC_ASPECTS = [0.0, 60.0, 90.0, 120.0, 180.0]

# One declared default for the refraction atmosphere.  The bundled client sent
# 15 and the schema defaulted to 0.0, so anyone reproducing a published chart
# through the API without an atmosphere block computed against a different sky.
DEFAULT_ATMOSPHERE_TEMPERATURE_C = 15.0
