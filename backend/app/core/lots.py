"""日夜盤判定 (Sect) 與阿拉伯點 Lot of Fortune / Lot of Spirit ——皆屬「方法層」而非
天文資料層：核心天文事實只有太陽的地平高度，「高度>0=日盤」是一條規則、「日夜盤決定
用哪個阿拉伯點公式」也是規則，因此在此明確標註具名 method，不與原始天文資料混在一起。

兩者都仰賴「觀測者站在地表看天空」這個地平座標前提，heliocentric/barycentric
模式下沒有意義，一律回傳 is_day/fortune/spirit 為 None 並在 trace 註明原因。

## 日夜盤的邊界

判準「太陽中心、未計折射的真高度 > 0° 為日盤」是**產品慣例**：它與天氣、地形解耦、
可重現，且不隨宮位制改變。已核的古典段落（方法登記 `sect`）多半把日生／夜生當作已知
分類，或以「在地上／地下」描述**行星**的條件，**都沒有明定本產品需要的中心、上緣或折射
邊界**——這是已核範圍的陳述，不是「沒有任何來源規定」的全稱主張。恰好 0° 歸夜是工程
端點約定。

Sect 固定消費**地心**真高度，與顯示中心無關：使用者切到 topocentric 時方法結果不得移動。
太陽視差最大約 8.8″，實際翻轉機率極低，但「顯示切換改變方法」這一類行為本身不可接受。

近地平敏感提示 ±50′（`SECT_NEAR_CRITICAL_DEGREES`）同樣是產品慣例。標準視日出（上緣
初現）時太陽中心約在幾何地平下 50′（大氣折射約 34′＋太陽半徑約 16′），故 −50′ < h ≤ 0°
是「以幾何中心」與「以視日出」兩種具名邊界會給出不同日夜盤的區間；本產品把它對稱擴成
±50′ 作為敏感提示帶，h > 0 的那一半兩種邊界其實一致。34′ 不是定值：實測地平折射依地點
與季節約在 14′–101′ 之間（Sampson, Lozowski & Machel 2005, Applied Optics 44:5652；
Schaefer & Liller 1990, PASP 102:796），16′ 與 34′ 相加得到的是視日出位置而非 0° 判準的
誤差。換算成時間依緯度與季節而異，本模組不給固定分鐘數；近極圈時太陽可能整夜停在帶內。

## Lots

採 Valens／Paulus 一系的 sect-reversing 公式（方法登記 `lots`）。Ptolemy、Valens III.11
（Pingree 編號；Kroll／Riley 為 III.14）與 Ibn Ezra 的具名分歧照實記錄於 `LOTS_SOURCE` 而不採用。

近邊界時兩套公式並列輸出（`by_sect`）：已核的古典與中世紀作者沒有「日夜盤不定就並列
兩套阿拉伯點」的程序；並列是**現代不確定性傳播策略**，收據如此標明。
"""

from .formatting import normalize_longitude
from .frame_compatibility import NON_EARTH_OBSERVER_CENTER
from .module_state import Applicability, computed_receipt, frame_table_refusal
from .source_reading import (
    DOROTHEUS_BOOK_I_ONLINE, ORIGINAL_LANGUAGE_READ, SECONDARY_ONLY, TRANSLATION_READ, cited,
    reference_only,
)
from .house_placements import (
    HOUSE_INTERVAL_SEMANTICS,
    METHOD_NAME as HOUSE_PLACEMENT_METHOD_NAME,
    _cusp_spans,
    _house_for_longitude,
)
from .method_status import method_head
from .trace import Trace

SECT_METHOD_NAME = "sun_center_true_altitude_gt_zero_v1"
SECT_METHOD_PROVENANCE = "product_convention_sources_checked_do_not_specify_boundary"
# Passages from the method research notes.  The register carries the citation;
# the response carries SECT_SOURCE_LABEL and source_ref.
SECT_SOURCE_LABEL = "product_convention"
SECT_SOURCE = (
    "Passages (not independently verified): Dorotheus I.1 (Pingree 1976 pp.161–162), "
    "I.22 (Pingree 1976 p.183); Ptolemy I.7 (Robbins p.43); Valens III.5 (Pingree "
    "pp.133–134); Paulus ch.6, ch.23 (Boer 1958, main text; Schmidt 1995 pp.13, "
    "43); Firmicus II.7.1–4; Rhetorius ch.2, ch.44 (Holden 2009 numbering, a "
    "compilation of epitomes; not verified); Abū Maʿshar, Great Introduction "
    "II.9.1 (locator not verified), Abbreviation III.3 (Dykes ITA §III.2); "
    "al-Qabīṣī I (Latin 1512); Lilly 1647 p.113 (Hayz), p.42. "
    "Most treat a diurnal or nocturnal birth as a given category, or describe "
    "planetary conditions as above or below the earth; the closest to a solar "
    "day/night criterion are Valens III.11 (Pingree; = III.14 Kroll/Riley, '14K;11P'; the Moon 'above the earth' read as until "
    "it sets) and Lilly 1647 p.42 (checking the chart time by the Sun's house). None "
    "specifies sun-centre, upper limb or refraction; the >0° rule is a product convention."
)
# The loci SECT_SOURCE names, one citation object each.  Where another register
# entry records how far the same place was read, that record is used; the rest
# claim the reference only.
SECT_SOURCE_CITATIONS = [
    cited("Dorotheus, Carmen Astrologicum I.1 (Pingree 1976 pp.161-162)",
          "day and night births as given categories (the triplicity lords by sect)",
          TRANSLATION_READ, f"{DOROTHEUS_BOOK_I_ONLINE}: I.1 on pp.161-162; the Arabic not checked"),
    cited("Dorotheus, Carmen Astrologicum I.22 (Pingree 1976 p.183)",
          "the sect light's triplicity lords", TRANSLATION_READ,
          f"{DOROTHEUS_BOOK_I_ONLINE}: I.22 on p.183; the Arabic not checked"),
    cited("Ptolemy, Tetrabiblos I.7 (Robbins p.43)", "diurnal and nocturnal planets",
          TRANSLATION_READ,
          ("Robbins's English translation on LacusCurtius (Tetrabiblos/1B*.html), I.7 "
           "after the p43 page mark: 'the sun and Jupiter diurnal'; the Greek not read")),
    cited("Vettius Valens, Anthologies III.5 (Pingree pp.133-134)",
          "day and night births as given categories (the sects of the stars)",
          TRANSLATION_READ,
          ("Riley's translation (Vettius_Valens_Riley.pdf), printed p.62, ch.5 "
           "between the /133P/ and /135P/ markers")),
    reference_only(
        "Paulus Alexandrinus, Introduction ch.6, ch.23 (Boer 1958, main text; Schmidt 1995 pp.13, 43)",
        "sect as a given category; Boer 1958 and Schmidt 1995 not checked",
    ),
    cited("Firmicus Maternus, Mathesis II.7.1-4 (Kroll-Skutsch 1897 vol. I pp.49-50)",
          ("the Sun, Jupiter and (supplied by the editors) Saturn rejoice by day; where they stand is lost in a "
           "lacuna after 'in oportunis locis positi' (II.7.2), so 'above or below the "
           "earth' is not in the surviving text; the waning Moon with Venus or Mars by "
           "night (II.7.3)"),
          ORIGINAL_LANGUAGE_READ,
          "the Kroll-Skutsch Latin in the LacusCurtius transcription (Mathesis book II)"),
    reference_only(
        "Rhetorius ch.2, ch.44 (Holden 2009 numbering, a compilation of epitomes)",
        "sect as a given category; not verified",
    ),
    reference_only("Abū Maʿshar, Great Introduction II.9.1", "sect; the locator not verified"),
    reference_only("Abū Maʿshar, Abbreviation III.3 (Dykes ITA §III.2)", "sect as a given category"),
    reference_only("al-Qabīṣī, Introduction I (Latin 1512)", "sect as a given category"),
    cited("William Lilly, Christian Astrology (1647) p.113, 'Hayz'",
          "a diurnal planet by day above the earth, a nocturnal planet by night under the earth",
          ORIGINAL_LANGUAGE_READ, "archive.org OCR text of a modern reset edition"),
    cited("William Lilly, Christian Astrology (1647) p.42",
          "checking the chart time by the Sun's house", ORIGINAL_LANGUAGE_READ,
          ("the 1647 printing as scanned at archive.org (b30338724, n75 = p.42): "
           "'that they may presently consider whether they have set their Figure right'")),
    cited(
        "Vettius Valens, Anthologies III.11 (Pingree; = III.14 Kroll/Riley, '14K;11P')",
        "the Moon 'above the earth' read as until it sets",
        TRANSLATION_READ,
        ("Riley's translation in a reformatted online copy of his preliminary edition "
         "(github.com/janegca/latex-valens), the chapter headed '(14K,11P)': 'if the "
         "Moon is above the earth, i.e. until the time it sets'; the Greek not checked"),
    ),
]
# 近地平敏感提示帶：±50 角分（理由見 module docstring）。
SECT_NEAR_CRITICAL_DEGREES = 50.0 / 60.0
SECT_STATUSES = ("day", "night", "boundary_both_shown")
SECT_ALTITUDE_CENTER = "geocentric"
# bodies.SECT_SUN_FLAGS：視位置（光行時、光行差）、回歸黃道當日、含章動；與請求的
# position_mode 無關。「真高度」指未計蒙氣折射的高度。
SECT_SUN_POSITION = "apparent_geocentric_tropical_of_date"
# 唯一有名字的替代邊界：USNO 標準日出／日落定義太陽中心幾何天頂距 90°50′（上緣切地平，
# 含平均折射 34′），即真高度 −50′；−50′ < h ≤ 0° 時本產品判夜盤，該定義判太陽仍在地平上。
# 與提示帶半寬數值相同（提示帶由它對稱擴成），
# 但是不同的量，故分開定義。
USNO_STANDARD_SUNRISE_CENTRE_ALTITUDE_DEGREES = -50.0 / 60.0

LOTS_METHOD_NAME = "traditional_day_night_formula_v1"
LOTS_FORMULA_PROFILE = "sect_reversing_fortune_spirit_v1"
LOTS_METHOD_PROVENANCE = "valens_paulus_sect_reversing_lineage"
LOTS_SOURCE = (
    "Paulus, Eisagōgika ch.23 (Boer 1958, main text; Schmidt/Hand 1995 pp.43–45; "
    "neither edition checked), the cleanest witness: the Greek-Latin first printing "
    "(Wittenberg: Lehmann, 1586), chapter on the seven lots of Panaretus, reverses "
    "Fortune and Spirit at night. Valens III.11 (Pingree p.147; = III.14 Kroll/Riley, '14K;11P') also uses the day formula "
    "at night once the Moon has set: not adopted (Greenbaum, Culture and Cosmos 11, "
    "2007, p.183). Abū Maʿshar's line via al-Bīrūnī, Tafhīm §476 (Wright "
    "1934); Abbr. VI.3–4 and Bonatti not checked. Named disagreement not adopted: "
    "Ptolemy III.10 (Robbins pp.275–277) = III.11 (Hübner), Fortune Sun to Moon "
    "by day and night (Sun:ASC = Moon:Fortune); at night it falls on the reversing "
    "Spirit's degree (Rhetorius, CCAG VIII/4 p.121, via Greenbaum 2007 p.181). "
    "Ptolemy gives no Spirit formula there; a non-reversing Spirit attributed to "
    "Ibn Ezra is not checked."
)
# The loci LOTS_SOURCE names, one citation object each, as for SECT_SOURCE.
LOTS_SOURCE_CITATIONS = [
    cited("Paulus Alexandrinus, Introduction ch.23",
          "reverses Fortune and Spirit at night (the product's formula)", TRANSLATION_READ,
          ("the Greek-Latin first printing (Wittenberg 1586) in the archive.org scan of the "
           "Royal Library Copenhagen copy (den-kbd-pil-130018161835-002), 'De septem "
           "sortibus, quae sunt in Panareto': Fortune in the Latin on leaf n81, by night "
           "'contraria ratione', Moon to Sun; the Daimon in the Greek on leaf n82, by night "
           "'τὸ ἀνάπαλιν'; Boer 1958 not checked")),
    reference_only(
        "Paulus Alexandrinus, Eisagōgika ch.23 (Boer 1958; Schmidt/Hand 1995 pp.43-45)",
        "the same chapter in the modern editions, neither edition checked",
        "neither edition checked; only the reference is claimed",
    ),
    cited(
        "Vettius Valens, Anthologies III.11 (Pingree p.147; = III.14 Kroll/Riley, '14K;11P')",
        "the day formula at night once the Moon has set; not adopted",
        TRANSLATION_READ,
        ("Riley's translation in a reformatted online copy of his preliminary edition "
         "(github.com/janegca/latex-valens), the chapter headed '(14K,11P)', after "
         "Riley's /147P/ marker: 'After the Moon has set, determine the distance from "
         "the Sun to it'; the Greek not checked"),
    ),
    cited(("Greenbaum, 'Calculating the Lots of Fortune and Daemon in Hellenistic "
           "Astrology', Culture and Cosmos 11, 2007, p.183 (article pp.163-187)"),
          ("the after-moonset rule (Valens III.11 Pingree = III.14 Kroll/Riley), with "
           "the Greek of III.11.4 in n.54 (p.147.2-6 Pingree)"),
          SECONDARY_ONLY, "the article's PDF on cultureandcosmos.org, p.183 and n.54"),
    cited("al-Bīrūnī, Kitāb al-Tafhīm §476 (Wright 1934; he says after Abū Maʿshar)",
          "Abū Maʿshar's line of the lots", TRANSLATION_READ,
          "Wright's English translation (1934)"),
    reference_only("Abū Maʿshar, Abbreviation VI.3-4", "the lots; not checked",
                   "not consulted"),
    cited("Ptolemy, Tetrabiblos III.10 (Robbins pp.275-277; = Hübner III.11)",
          "the Lot of Fortune from Sun to Moon by day and by night; not adopted",
          TRANSLATION_READ,
          ("Robbins's English (Loeb 1940): the whole of III.10 read in the "
           "LacusCurtius transcription, the Lot of Fortune at pp.275-277; the Greek "
           "not checked")),
    reference_only(
        "Rhetorius, CCAG VIII/4 p.121, via Greenbaum 2007 p.181",
        "at night Ptolemy's Fortune falls on the reversing Spirit's degree",
    ),
]
# Per the method research notes.
LOTS_SOURCE_LABEL = (
    "Paulus, Eisagōgika ch.23 (read in the Wittenberg 1586 printing; Boer 1958 and "
    "Schmidt/Hand 1995 pp.43–45 not checked)"
)
LOT_FORMULA_BASES = ("day_formula", "night_formula", "both_formulas_boundary")

# The band's reasoning text is constant: register entry sect/near_horizon_band.
_NEAR_CRITICAL_BAND = {
    "kind": "product_convention",
    "divergent_interval": "-50_arcmin_lt_h_le_0",
    "refraction_is_not_a_constant": True,
    "source_status": "sources_checked_do_not_specify_this_boundary",
    "source_ref": "sect/near_horizon_band",
}


def classify_sect(sun_altitude_true: float | None) -> dict:
    """日夜盤規則的唯一產生器。

    阿拉伯點的 `derived_methods.sect` 與本質尊貴的 `essential_dignities.sect` 都由這裡
    得到日夜盤、提示帶與具名邊界分歧；呼叫端只提供地心太陽真高度。常數在呼叫時讀取，
    所以兩個消費者不可能各自持有一份。

    `named_boundary_disagreement` 是閉集布林：−50′ < h ≤ 0° 時為 true，表示
    USNO 標準日出日落定義與本產品 h > 0° 規則判法不同；沒有地平時為 None。
    """

    if sun_altitude_true is None:
        return {
            "is_day": None,
            "sect_status": None,
            "in_near_horizon_band": None,
            "near_horizon_band_half_width_degrees": SECT_NEAR_CRITICAL_DEGREES,
            "named_boundary_disagreement": None,
        }
    is_day = sun_altitude_true > 0
    in_band = abs(sun_altitude_true) <= SECT_NEAR_CRITICAL_DEGREES
    return {
        "is_day": is_day,
        "sect_status": (
            "boundary_both_shown" if in_band else "day" if is_day else "night"
        ),
        "in_near_horizon_band": in_band,
        "near_horizon_band_half_width_degrees": SECT_NEAR_CRITICAL_DEGREES,
        "named_boundary_disagreement": (
            USNO_STANDARD_SUNRISE_CENTRE_ALTITUDE_DEGREES < sun_altitude_true <= 0
        ),
    }


def determine_sect(
    sun_altitude_true,
    trace: Trace,
    *,
    display_center: str = SECT_ALTITUDE_CENTER,
) -> dict:
    """地心太陽真高度 > 0 為日生盤，否則夜生盤：方法規則（太陽中心、未計蒙氣折射、地心），
    不是天文事實。"""
    base = {
        **method_head(SECT_METHOD_NAME, "sect"),
        "method_provenance": SECT_METHOD_PROVENANCE,
        "source": SECT_SOURCE_LABEL,
        "source_ref": "sect",
        "altitude_center": SECT_ALTITUDE_CENTER,
        "display_center": display_center,
        "altitude_sun_position": SECT_SUN_POSITION,
        "endpoint_rule": "exactly_zero_is_night_engineering_convention",
        "sect_statuses": list(SECT_STATUSES),
        "near_horizon_band_half_width_degrees": SECT_NEAR_CRITICAL_DEGREES,
        # The half-width is the sibling near_horizon_band_half_width_degrees.
        "near_horizon_band": dict(_NEAR_CRITICAL_BAND),
    }
    if sun_altitude_true is None:
        trace.add(
            "日夜盤判定 (Sect)",
            note="⚠ heliocentric/barycentric 模式下太陽沒有地平高度，日夜盤無法判定，回傳 null。",
        )
        return {
            **base,
            # The altitude was asked for and there is no horizon.
            **computed_receipt(
                SECT_SOURCE_LABEL,
                applicable=False,
                available=False,
                reason_code=NON_EARTH_OBSERVER_CENTER,
            ),
            "is_day": None,
            "sect_status": None,
            "sun_altitude_used": None,
            "in_near_horizon_band": None,
            "named_boundary_disagreement": None,
        }

    classified = classify_sect(sun_altitude_true)
    is_day = classified["is_day"]
    in_band = classified["in_near_horizon_band"]
    sect_status = classified["sect_status"]
    trace.add(
        f"日夜盤判定 (Sect, method={SECT_METHOD_NAME})",
        formula="地心太陽真高度 > 0 → 日生盤；否則 → 夜生盤（採太陽中心，未計入蒙氣折射，與顯示中心無關）",
        inputs={"太陽真高度（地心）": sun_altitude_true, "顯示中心": display_center},
        result={
            "盤性": "日生盤 (Day)" if is_day else "夜生盤 (Night)",
            "狀態": sect_status,
            "臨近地平": in_band,
            "具名邊界分歧": classified["named_boundary_disagreement"],
        },
        note=(
            "⚠ 太陽真高度在地平上下 50 角分內：這是本產品的近地平敏感提示帶（產品慣例）。"
            "判定本身仍是確定的（h 的正負已知），但另一具名邊界（標準視日出：太陽上緣加平均折射）在 "
            "−50′ < h ≤ 0° 區間會給出相反的日夜盤；不計折射的上緣邊界只在 −16′ < h ≤ 0° 相反。"
            "故阿拉伯點同時並列兩套公式。研究筆記所列段落未明定此邊界。"
            if in_band else ""
        ),
    )
    return {
        **base,
        **computed_receipt(SECT_SOURCE_LABEL),
        "is_day": is_day,
        "sect_status": sect_status,
        "sun_altitude_used": sun_altitude_true,
        "in_near_horizon_band": in_band,
        "named_boundary_disagreement": classified["named_boundary_disagreement"],
    }


def _formulas(asc: float, sun_lon: float, moon_lon: float) -> dict:
    return {
        "day": {
            "formula_basis": "day_formula",
            "fortune": normalize_longitude(asc + moon_lon - sun_lon),
            "spirit": normalize_longitude(asc + sun_lon - moon_lon),
            "formula_fortune": "Fortune = ASC + Moon − Sun（日盤公式）",
            "formula_spirit": "Spirit = ASC + Sun − Moon（日盤公式）",
        },
        "night": {
            "formula_basis": "night_formula",
            "fortune": normalize_longitude(asc + sun_lon - moon_lon),
            "spirit": normalize_longitude(asc + moon_lon - sun_lon),
            "formula_fortune": "Fortune = ASC + Sun − Moon（夜盤公式）",
            "formula_spirit": "Spirit = ASC + Moon − Sun（夜盤公式）",
        },
    }


# A Lot's house uses the planet rule exactly: the same half-open function.


def _lot_house(
    longitude: float | None, houses: dict | None, spans: tuple | None = None
) -> int | None:
    if houses is None or longitude is None:
        return None
    return _house_for_longitude(longitude, houses["cusps"], spans)


def _lot_house_placement(
    houses: dict | None, primary: dict, trace: Trace, spans: tuple | None = None
) -> dict | None:
    if houses is None:
        return None
    placement = {
        "method": HOUSE_PLACEMENT_METHOD_NAME,
        "house_system_code": houses.get("system_code"),
        "interval_semantics": HOUSE_INTERVAL_SEMANTICS,
        "fortune": _lot_house(primary["fortune"], houses, spans),
        "spirit": _lot_house(primary["spirit"], houses, spans),
    }
    trace.add(
        "阿拉伯點落宮",
        formula="點黃經 ∈ [第 n 宮宮頭, 第 n+1 宮宮頭)",
        result={"Fortune": placement["fortune"], "Spirit": placement["spirit"]},
        note="與行星落宮同一半開區間函式。",
    )
    return placement


def lots_not_applicable(state: Applicability, sect: dict, trace: Trace) -> dict:
    # Refused Lots do not join aspects either.
    refusal = frame_table_refusal(
        state, trace, "阿拉伯點：Fortune / Spirit",
        note=(
            "上升點由當日真春分點框架算出；日月黃經不在同一框架，或沒有地表觀測者，"
            "參考框架相容表判定不適用，不計算、不轉換座標。"
        ),
    )
    return {
        **method_head(LOTS_METHOD_NAME, "lots"),
        "method_provenance": LOTS_METHOD_PROVENANCE,
        "formula_profile": LOTS_FORMULA_PROFILE,
        **refusal,
        "execution_status": "not_applicable",
        "fortune": None,
        "spirit": None,
        "formula_basis": None,
        # The chart's own sect receipt, refused or not: always a dict from determine_sect.
        "sect_status": sect["sect_status"],
        "sect_applied": None,
        "by_sect": None,
        "house_placement": None,
    }


def _lots_sect_band_fields(sect: dict) -> dict:
    return {
        "sect_in_near_horizon_band": sect.get("in_near_horizon_band"),
        "sect_named_boundary_disagreement": sect.get("named_boundary_disagreement"),
    }


def compute_lots(
    asc: float,
    sun_lon: float,
    moon_lon: float,
    sect: dict,
    trace: Trace,
    *,
    houses: dict | None = None,
) -> dict:
    is_day = sect["is_day"]
    base = {
        **method_head(LOTS_METHOD_NAME, "lots"),
        "method_provenance": LOTS_METHOD_PROVENANCE,
        "formula_profile": LOTS_FORMULA_PROFILE,
        "source": LOTS_SOURCE_LABEL,
        "source_ref": "lots",
        # 常數：所採公式族依日夜盤反轉。不填 is_day，否則每一張夜盤都會被告知
        # 「公式不依日夜盤反轉」。
        "formula_bases": list(LOT_FORMULA_BASES),
        # The near-horizon band shows a primary value and a comparison value,
        # not two formal outputs.
        "boundary_policy": {
            "kind": "modern_uncertainty_propagation_not_a_classical_procedure",
            "source_ref": "lots/boundary_policy",
        },
    }
    by_sect = _formulas(asc, sun_lon, moon_lon)
    sect_applied = "day" if is_day else "night"
    primary = by_sect[sect_applied]
    in_band = bool(sect.get("in_near_horizon_band"))
    sect_status = sect.get("sect_status") or (
        "boundary_both_shown" if in_band else sect_applied
    )
    formula_basis = (
        "both_formulas_boundary" if sect_status == "boundary_both_shown"
        else primary["formula_basis"]
    )

    for lot, label in (("fortune", "Fortune"), ("spirit", "Spirit")):
        trace.add(
            f"阿拉伯點：Lot of {label} (method={LOTS_METHOD_NAME})",
            formula=primary[f"formula_{lot}"],
            inputs={"ASC": asc, "太陽黃經": sun_lon, "月亮黃經": moon_lon},
            result={f"{label} 黃經": primary[lot]},
        )
    if sect_status == "boundary_both_shown":
        other = by_sect["night" if is_day else "day"]
        trace.add(
            "阿拉伯點：近地平敏感帶，兩套公式並列",
            formula=f"{other['formula_fortune']}；{other['formula_spirit']}",
            result={
                "另一日夜盤的 Fortune": other["fortune"],
                "另一日夜盤的 Spirit": other["spirit"],
            },
            note=(
                "我們核過的古典與中世紀作者沒有『日夜盤不定就並列兩套』的程序；兩套並列是現代"
                "不確定性傳播策略。主要值仍依 >0° 判準。"
            ),
        )

    # Six Lot places against one set of cusps: their interval widths once.
    spans = None if houses is None else _cusp_spans(houses["cusps"])
    house_placement = _lot_house_placement(houses, primary, trace, spans)
    return {
        **base,
        **computed_receipt(LOTS_SOURCE_LABEL),
        "fortune": primary["fortune"],
        "spirit": primary["spirit"],
        "formula_basis": formula_basis,
        "sect_status": sect_status,
        "sect_applied": sect_applied,
        "house_placement": house_placement,
        "by_sect": {
            key: {
                "formula_basis": value["formula_basis"],
                "fortune": value["fortune"],
                "spirit": value["spirit"],
                "fortune_house": _lot_house(value["fortune"], houses, spans),
                "spirit_house": _lot_house(value["spirit"], houses, spans),
                "formula_fortune": value["formula_fortune"],
                "formula_spirit": value["formula_spirit"],
            }
            for key, value in by_sect.items()
        },
        **_lots_sect_band_fields(sect),
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "sect": {
        "applies_to": "derived_methods.sect",
        "method_provenance": SECT_METHOD_PROVENANCE,
        "sources": SECT_SOURCE_CITATIONS,
        "source_summary": SECT_SOURCE,
    },
    "sect/near_horizon_band": {
        "applies_to": "derived_methods.sect.near_horizon_band",
        "geometric_reason": (
            "標準視日出（上緣初現）時太陽中心約在幾何地平下 50′（折射約 34′＋太陽半徑約 16′），"
            "故 −50′ < h ≤ 0° 是幾何中心判準與視日出判準會分歧的區間；本產品對稱擴成 ±50′ 作為"
            "敏感提示帶。"
        ),
        "time_span_note": (
            "依緯度與季節而異：低緯每次穿越約數分鐘，60°N 至點約 20 分鐘，更高緯可達數十分鐘，"
            "近極圈時太陽可能整夜停在帶內；不給固定分鐘數。"
        ),
    },
    "lots": {
        "applies_to": "derived_methods.lots",
        "method_provenance": LOTS_METHOD_PROVENANCE,
        "sources": LOTS_SOURCE_CITATIONS,
        "source_summary": LOTS_SOURCE,
    },
    "lots/boundary_policy": {
        "applies_to": "derived_methods.lots.boundary_policy",
        "rule": (
            "sect_status == boundary_both_shown 時，fortune／spirit 是依 >0° 判準的主要值；"
            "by_sect 中另一日夜盤公式的結果並列為比較值，不隱藏；落宮與相位只用主要值"
        ),
    },
}
