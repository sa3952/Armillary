"""行星與宮的古典分類：本命盤的選用輸出。

每一條分類都標明出自哪本書哪一章，照該書的用語列出；各書說法不同時並列，不替讀者挑一個：

- 行星的吉凶：Ptolemy《Tetrabiblos》I.5 與 al-Bīrūnī《Tafhīm》§382 各一欄。
- 行星的陰陽與日夜區：Ptolemy I.6、I.7（水星依晨星或昏星），Valens《Anthologies》I.1。
- 喜樂宮（joys）：通行的七星七宮只讀到轉引（Paulus ch.24）；Firmicus《Mathesis》II.19 另說月亮
  只在夜盤喜樂於第 8 宮，兩條並列。
- hayz／halb：al-Bīrūnī §496（halb 與 hayyiz 兩層）與 Lilly《Christian Astrology》p.113（只有
  hayz，夜行星要在地平下）定義不同，兩套並列。
- 十二宮：名稱、始宮／續宮／果宮，以及 Firmicus II.15–17 與 Dorotheus I.5（轉引）兩種好壞分法。
  宮的含義不進個人盤，只在方法頁。

只列分類與這張盤是否符合某書的條件；不加總、不打分，也不寫對這個人的解讀。
"""

from __future__ import annotations

from .dignity_tables import SIGNS
from .formatting import normalize_longitude, zodiac_sign_index
from .method_status import method_receipt
from .module_state import PRODUCT_FORMULA_SOURCE, computed_receipt, not_applicable_receipt
from .source_reading import SOURCE_READING_LEVELS
from .trace import Trace

METHOD_NAME = "classical_planet_and_place_classifications_v1"
SOURCE_REF = "classical_classifications"
PLANET_ORDER = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")

# ── 行星 ────────────────────────────────────────────────────────────────
# 吉凶：每個來源一欄，值是閉集，照該書的說法。
NATURE_VALUES = (
    "beneficent",
    "maleficent",
    "both_powers",  # Ptolemy I.5：太陽與水星兩種力量都有，隨同處的行星
    "beneficent_when_distant_maleficent_when_conjunct",  # al-Bīrūnī §382 的太陽
    "follows_the_planet_nearest_it",  # al-Bīrūnī §382 的水星
)
NATURE_BY_SOURCE = {
    "ptolemy_tetrabiblos_i_5": {
        "sun": "both_powers", "moon": "beneficent", "mercury": "both_powers",
        "venus": "beneficent", "mars": "maleficent", "jupiter": "beneficent",
        "saturn": "maleficent",
    },
    "al_biruni_tafhim_382": {
        "sun": "beneficent_when_distant_maleficent_when_conjunct", "moon": "beneficent",
        "mercury": "follows_the_planet_nearest_it", "venus": "beneficent",
        "mars": "maleficent", "jupiter": "beneficent", "saturn": "maleficent",
    },
}
# 陰陽：Ptolemy I.6；al-Bīrūnī §385 相同（水星隨同處的行星）。
PLANET_GENDER = {
    "sun": "masculine", "moon": "feminine", "mercury": "common", "venus": "feminine",
    "mars": "masculine", "jupiter": "masculine", "saturn": "masculine",
}
# 日夜區：Ptolemy I.7、Valens I.1、al-Bīrūnī §386 對六顆一致；水星依 Ptolemy I.7 的晨昏規則逐盤判定。
PLANET_SECT = {
    "sun": "diurnal", "moon": "nocturnal", "venus": "nocturnal", "mars": "nocturnal",
    "jupiter": "diurnal", "saturn": "diurnal",
}
SECT_MEMBERSHIP_VALUES = (
    "diurnal",
    "nocturnal",
    "diurnal_as_morning_star",
    "nocturnal_as_evening_star",
    "undetermined_same_longitude_as_the_sun",
)
# 星座陰陽：Ptolemy I.12，奇數星座（牡羊起）為陽。
SIGN_GENDER = {sign: ("masculine" if index % 2 == 0 else "feminine") for index, sign in enumerate(SIGNS)}

# 喜樂宮：每一條是一個來源的一句話；同一顆行星可以有不只一條。
JOY_CLAIMS = (
    {"planet": "mercury", "place": 1, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "moon", "place": 3, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "venus", "place": 5, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "mars", "place": 6, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "sun", "place": 9, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "jupiter", "place": 11, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "saturn", "place": 12, "condition": "any_chart", "source": "paulus_introduction_24"},
    {"planet": "moon", "place": 8, "condition": "night_chart_only", "source": "firmicus_mathesis_ii_19"},
)
JOY_CONDITIONS = ("any_chart", "night_chart_only")

HAYZ_PROFILES = ("al_biruni_tafhim_496", "lilly_christian_astrology_p113")
HAYZ_REASON_CODES = (
    "chart_sect_unavailable",
    "planet_altitude_unavailable",
    "mercury_has_no_rule_in_this_source",
    "planet_not_covered_by_this_definition",
)
# 地平上下：行星中心的地心真高度 > 0°，與本產品判日夜盤的太陽同一條規則。
ABOVE_HORIZON_RULE = "geocentric_true_altitude_of_the_centre_above_zero_v1"
NEAR_HORIZON_HALF_WIDTH_DEGREES = 50.0 / 60.0


def _sect_membership(key: str, longitude: float, sun_longitude: float | None) -> str:
    if key != "mercury":
        return PLANET_SECT[key]
    if sun_longitude is None:
        return "undetermined_same_longitude_as_the_sun"
    # 晨星：先於太陽升起，即黃經落在太陽之西（較小）；昏星在太陽之東。
    east = (normalize_longitude(longitude) - normalize_longitude(sun_longitude)) % 360.0
    if east == 0.0:
        return "undetermined_same_longitude_as_the_sun"
    return "nocturnal_as_evening_star" if east < 180.0 else "diurnal_as_morning_star"


def _is_diurnal(membership: str) -> bool | None:
    if membership in {"diurnal", "diurnal_as_morning_star"}:
        return True
    if membership in {"nocturnal", "nocturnal_as_evening_star"}:
        return False
    return None


def _al_biruni(key: str, diurnal: bool | None, is_day: bool | None, above: bool | None,
               sign: str) -> dict:
    """§496：halb＝晝行星白天在地上、夜裡在地下，夜行星相反；hayyiz＝halb 再加陽性行星在陽性
    星座、陰性行星在陰性星座。火星陽性而屬夜：依夜行星判地上地下，星座要陽性。水星書中沒有規則。"""

    if key == "mercury":
        return {"halb": None, "hayyiz": None, "reason_code": "mercury_has_no_rule_in_this_source"}
    if is_day is None:
        return {"halb": None, "hayyiz": None, "reason_code": "chart_sect_unavailable"}
    if above is None:
        return {"halb": None, "hayyiz": None, "reason_code": "planet_altitude_unavailable"}
    wants_above = is_day if diurnal else not is_day
    halb = above == wants_above
    hayyiz = halb and SIGN_GENDER[sign] == PLANET_GENDER[key]
    return {"halb": halb, "hayyiz": hayyiz, "reason_code": None}


def _lilly(key: str, is_day: bool | None, above: bool | None, sign: str) -> dict:
    """p.113：陽性晝行星白天在地上、在陽性星座；陰性夜行星夜裡在地下、在陰性星座。
    火星（陽性夜行星）與水星不在這個定義裡。"""

    gender, sect = PLANET_GENDER[key], PLANET_SECT.get(key)
    covered = (gender, sect) in {("masculine", "diurnal"), ("feminine", "nocturnal")}
    if not covered:
        return {"hayz": None, "reason_code": "planet_not_covered_by_this_definition"}
    if is_day is None:
        return {"hayz": None, "reason_code": "chart_sect_unavailable"}
    if above is None:
        return {"hayz": None, "reason_code": "planet_altitude_unavailable"}
    if sect == "diurnal":
        hayz = is_day and above and SIGN_GENDER[sign] == "masculine"
    else:
        hayz = (not is_day) and (not above) and SIGN_GENDER[sign] == "feminine"
    return {"hayz": hayz, "reason_code": None}


def _joys(key: str, house: int | None, is_day: bool | None) -> list[dict]:
    rows = []
    for claim in JOY_CLAIMS:
        if claim["planet"] != key:
            continue
        if house is None:
            met = None
        elif claim["condition"] == "night_chart_only":
            met = None if is_day is None else (house == claim["place"] and not is_day)
        else:
            met = house == claim["place"]
        rows.append({
            "place": claim["place"],
            "condition": claim["condition"],
            "source": claim["source"],
            "in_joy": met,
        })
    return rows


# ── 十二宮 ──────────────────────────────────────────────────────────────
TRIAD_VALUES = ("angular", "succedent", "cadent")
FIRMICUS_GROUP_VALUES = ("joined_to_the_ascendant", "sluggish_and_cast_down")
DOROTHEUS_RANK_VALUES = ("good", "middling", "bad")
# 名稱：希臘文轉寫與英文依 Robbins 譯 Ptolemy III.10 注 56、Valens 卷二與卷四；拉丁文依
# Firmicus II.19–20。中文是本產品的譯名（沒有通行的中文名），對外第一次出現時並列原文。
PLACES = (
    (1, "上升", "Hōroskopos", "Horoscope", "horoscopus"),
    (2, "冥府之門", "Hadou pylē", "Gate of Hades", "inferna porta"),
    (3, "女神", "Thea", "Goddess", "Dea"),
    (4, "天底", "Hypogeion", "Lower Midheaven", "imum caelum"),
    (5, "好運", "Agathē Tychē", "Good Fortune", "Bona fortuna"),
    (6, "惡運", "Kakē Tychē", "Bad Fortune", "Mala fortuna"),
    (7, "下降", "Dysis", "Descendant", "occasus"),
    (8, "死亡之始", "Epikataphora", "Beginning of Death", "epicatafora"),
    (9, "神", "Theos", "God", "Deus"),
    (10, "中天", "Mesouranēma", "Midheaven", "medium caelum"),
    (11, "善靈", "Agathos Daimōn", "Good Daimon", "Bonus daemon"),
    (12, "惡靈", "Kakos Daimōn", "Bad Daimon", "Malus daemon"),
)
# Firmicus II.15–17：四個樞軸、與上升相連的四處（3、9、5、11），以及與上升沒有關聯的四處
# 「遲滯、低落」（2、8、6、12）。
_FIRMICUS_SLUGGISH = {2, 6, 8, 12}
# Dorotheus I.5（Pingree 譯自阿拉伯文本；轉引）：最好的七處、中等三處、壞的兩處。
_DOROTHEUS = {
    **dict.fromkeys((1, 10, 11, 5, 7, 4, 9), "good"),
    **dict.fromkeys((3, 2, 8), "middling"),
    **dict.fromkeys((6, 12), "bad"),
}


def place_rows() -> list[dict]:
    return [
        {
            "place": number,
            "name_zh": name_zh,
            "name_greek": greek,
            "name_english": english,
            "name_latin": latin,
            "triad": TRIAD_VALUES[(number - 1) % 3],
            "firmicus_ii_15_17": (
                "sluggish_and_cast_down" if number in _FIRMICUS_SLUGGISH else "joined_to_the_ascendant"
            ),
            "dorotheus_i_5": _DOROTHEUS[number],
        }
        for number, name_zh, greek, english, latin in PLACES
    ]


def compute_classical_classifications(
    *,
    planets: list[dict],
    altitudes: dict[str, float | None] | None,
    sect: dict | None,
    placements: dict[str, int] | None,
    trace: Trace,
) -> dict:
    """Each of the seven planets against each named classification, and the twelve places.

    ``altitudes`` are the geocentric true altitudes by planet key, or None when
    the chart has no birth time; ``sect`` is the classify_sect record, or None
    for the same reason; ``placements`` are the planets' houses when the chart
    has houses, else None.
    """

    by_key = {body["key"]: body for body in planets if body.get("longitude") is not None}
    sun = by_key.get("sun")
    is_day = None if sect is None else sect.get("is_day")
    rows = []
    for key in PLANET_ORDER:
        body = by_key.get(key)
        if body is None:
            continue
        longitude = body["longitude"]
        sign = SIGNS[zodiac_sign_index(longitude)]
        membership = _sect_membership(key, longitude, None if sun is None else sun["longitude"])
        diurnal = _is_diurnal(membership)
        altitude = None if altitudes is None else altitudes.get(key)
        above = None if altitude is None else altitude > 0.0
        house = None if placements is None else placements.get(key)
        rows.append({
            "key": key,
            "name": body["name"],
            "nature": {source: table[key] for source, table in NATURE_BY_SOURCE.items()},
            "gender": PLANET_GENDER[key],
            "sect_membership": membership,
            "of_chart_sect": None if is_day is None or diurnal is None else diurnal == is_day,
            "sign": sign,
            "sign_gender": SIGN_GENDER[sign],
            "above_horizon": above,
            "altitude_in_near_horizon_band": (
                None if altitude is None else abs(altitude) <= NEAR_HORIZON_HALF_WIDTH_DEGREES
            ),
            "house": house,
            "joys": _joys(key, house, is_day),
            "hayz": {
                "al_biruni_tafhim_496": _al_biruni(key, diurnal, is_day, above, sign),
                "lilly_christian_astrology_p113": _lilly(key, is_day, above, sign),
            },
        })

    not_evaluated = []
    if sect is None or is_day is None:
        not_evaluated.append("chart_sect_unavailable")
    if placements is None:
        not_evaluated.append("houses_not_computed")
    trace.add(
        "行星與宮的古典分類",
        inputs={"is_day": is_day, "above_horizon_rule": ABOVE_HORIZON_RULE},
        result={
            row["key"]: {
                "sect": row["sect_membership"],
                "halb": row["hayz"]["al_biruni_tafhim_496"]["halb"],
                "hayyiz": row["hayz"]["al_biruni_tafhim_496"]["hayyiz"],
                "lilly_hayz": row["hayz"]["lilly_christian_astrology_p113"]["hayz"],
            }
            for row in rows
        },
        note="只列各書的分類與條件是否符合；不加總、不打分、不解讀。",
    )
    return {
        "method": METHOD_NAME,
        **method_receipt("classical_classifications"),
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "source_ref": SOURCE_REF,
        "chart_sect": None if sect is None else {
            "is_day": sect.get("is_day"),
            "sect_status": sect.get("sect_status"),
            "in_near_horizon_band": sect.get("in_near_horizon_band"),
        },
        "above_horizon_rule": ABOVE_HORIZON_RULE,
        "not_evaluated": not_evaluated,
        "planets": rows,
        "places": place_rows(),
        "semantics": "named_source_classifications_and_conditions_only_no_score_no_reading",
    }


def classical_classifications_not_applicable(state: dict, trace: Trace) -> dict:
    trace.add(
        "行星與宮的古典分類",
        result={"execution_status": "not_applicable", "reason_code": state["reason_code"]},
        note="參考框架相容表判定不適用：沒有地平或不是當日的星座。",
    )
    return {
        "method": METHOD_NAME,
        **method_receipt("classical_classifications"),
        **not_applicable_receipt(state),
        "planets": [],
        "places": [],
    }


SOURCES = {
    "ptolemy_tetrabiblos_i_5": {
        "citation": "Ptolemy, Tetrabiblos (Apotelesmatika) I.5 'Of Beneficent and Maleficent Planets'",
        "says": "Jupiter, Venus and the Moon beneficent; Saturn and Mars maleficent; the Sun and Mercury have both powers",
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "Robbins translation (Loeb 1940), LacusCurtius",
    },
    "ptolemy_tetrabiblos_i_6_7_12": {
        "citation": "Ptolemy, Tetrabiblos I.6 (masculine and feminine planets), I.7 (diurnal and nocturnal planets), I.12 (masculine and feminine signs)",
        "says": (
            "Moon and Venus feminine, Mercury common; Sun and Jupiter diurnal, Moon and Venus "
            "nocturnal, Saturn given to the day and Mars to the night; Mercury diurnal as a "
            "morning star and nocturnal as an evening star; the signs alternate masculine and feminine from Aries"
        ),
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "Robbins translation (Loeb 1940), LacusCurtius",
    },
    "valens_anthologies_i_1": {
        "citation": "Vettius Valens, Anthologies I.1",
        "says": (
            "Saturn, Jupiter and the Sun of the day sect; Mars, Venus and the Moon of the night sect; "
            "no sect stated for Mercury; malefic stars operative in appropriate places in their own sect "
            "are bestowers of good"
        ),
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "Riley's translation in a reformatted online copy (github janegca/latex-valens)",
    },
    "al_biruni_tafhim_382": {
        "citation": "al-Bīrūnī, Kitāb al-tafhīm (Book of Instruction) §382, §385, §386",
        "says": (
            "Saturn and Mars maleficent, Saturn especially; Jupiter and Venus beneficent; the Sun "
            "beneficent when in aspect and distant, maleficent when conjoined and near; Mercury fortunate "
            "or the reverse after the planet nearest it; the Moon fortunate; Mercury's sect after the sign "
            "or the planet it is with (no morning/evening rule)"
        ),
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "R. Ramsay Wright's translation (1934), archive.org OCR text",
    },
    "paulus_introduction_24": {
        "citation": "Paulus Alexandrinus, Introduction (Eisagōgika) ch.24",
        "says": "the joys: Mercury 1st, Moon 3rd, Venus 5th, Mars 6th, Sun 9th, Jupiter 11th, Saturn 12th",
        "reading": SOURCE_READING_LEVELS[2],
        "read_at": (
            "reported by C. Brennan, 'The Planetary Joys and the Origins of the Significations of "
            "the Houses and Triplicities', ISAR Journal 42.1 (2013), n.2, with Olympiodorus ch.23 and "
            "Rhetorius ch.54; none of the three read"
        ),
    },
    "firmicus_mathesis_ii_19": {
        "citation": "Firmicus Maternus, Mathesis II.19 (Kroll-Skutsch)",
        "says": (
            "no star rejoices in the 8th place except the Moon, and only in night births; the 5th is "
            "the place of Venus, the 6th of Mars, the 9th of the Sun, the 11th of Jupiter, the 12th of "
            "Saturn (as places, not in the word 'joy')"
        ),
        "reading": SOURCE_READING_LEVELS[0],
        "read_at": "Latin text, LacusCurtius",
    },
    "valens_anthologies_ii": {
        "citation": "Vettius Valens, Anthologies II.4-15 (Kroll), the places one by one",
        "says": (
            "the 3rd the place of the Goddess Moon, the 6th the place of Mars, the 9th the place of the "
            "God Sun, the 11th the Good Daimon, the 12th the Bad Daimon, the 2nd the Gate of Hades"
        ),
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "Riley's translation in a reformatted online copy",
    },
    "manilius_astronomica_ii": {
        "citation": "Manilius, Astronomica II (the twelve temples, about lines 856-967)",
        "says": (
            "a different scheme of names and patrons: Venus at the midheaven, Saturn at the lower "
            "midheaven, Typhon in the 2nd and 8th; not used for the places listed here"
        ),
        "reading": SOURCE_READING_LEVELS[2],
        "read_at": (
            "Latin, The Latin Library, in part; the place mapping as given by P. Yong "
            "(premieretat.com) not checked against Goold"
        ),
    },
    "al_biruni_tafhim_496": {
        "citation": "al-Bīrūnī, Kitāb al-tafhīm §496",
        "says": (
            "halb: a diurnal planet above the earth by day and below it by night, a nocturnal one the "
            "reverse; hayyiz: halb and a male planet in a male sign or a female planet in a female sign; "
            "Mars, male and nocturnal, above the earth by night in a male sign; every hayyiz is a halb"
        ),
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "R. Ramsay Wright's translation (1934), archive.org OCR text",
        "agrees": [
            {
                "citation": "al-Qabīṣī, Introduction I.78 (Burnett et al. 2004)",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "John of Seville's Latin translation and Burnett's English, read online",
            },
            {
                "citation": "Bonatti, Liber astronomiae III.8",
                "reading": SOURCE_READING_LEVELS[3],
                "read_at": "the chapter reference only",
            },
        ],
    },
    "lilly_christian_astrology_p113": {
        "citation": "William Lilly, Christian Astrology (1647) p.113, 'Hayz'",
        "says": (
            "a masculine diurnal planet by day above the earth in a masculine sign; a feminine "
            "nocturnal planet by night in a feminine sign and under the earth; no halb"
        ),
        "reading": SOURCE_READING_LEVELS[0],
        "read_at": "archive.org OCR text of a modern reset edition",
    },
    "ptolemy_tetrabiblos_iii_3_10": {
        "citation": "Ptolemy, Tetrabiblos III.3 and III.10 with Robbins's notes 56-57",
        "says": (
            "angles, succedent places and places declining from the angles; the names of the twelve "
            "places (Horoscope, Gate of Hades, Goddess, Lower Midheaven, Good Fortune, Bad Fortune, "
            "Occident, Beginning of Death, God, Midheaven, Good Daemon, Bad Daemon)"
        ),
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "Robbins translation (Loeb 1940), LacusCurtius",
    },
    "firmicus_mathesis_ii_15_20": {
        "citation": "Firmicus Maternus, Mathesis II.15-20 (Kroll-Skutsch)",
        "says": (
            "four angles; four places after them joined to the ascendant (3, 9, 5, 11); four sluggish "
            "and cast-down places (2, 8, 6, 12) with no association with the ascendant; the Latin and "
            "Greek names of the twelve places"
        ),
        "reading": SOURCE_READING_LEVELS[0],
        "read_at": "Latin text, LacusCurtius",
    },
    "dorotheus_carmen_i_5": {
        "citation": "Dorotheus of Sidon, Carmen astrologicum I.5 (Pingree, from the Arabic)",
        "says": "the best places 1, 10, 11, 5, 7, 4, 9; middling 3, 2, 8; bad 6 and 12",
        "reading": SOURCE_READING_LEVELS[2],
        "read_at": "reported by sevenstarsastrology.com; Pingree's translation not read",
    },
    "valens_anthologies_iv_12": {
        "citation": "Vettius Valens, Anthologies IV, 'The names of the twelve places'",
        "says": "the 8th the Inactive Place; the topics of each place (methods page only)",
        "reading": SOURCE_READING_LEVELS[1],
        "read_at": "Riley's translation in a reformatted online copy",
    },
}

METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    SOURCE_REF: {
        "applies_to": "derived_methods.classical_classifications",
        "rule": (
            "Each classification is the named source's own; where sources differ each gets its own "
            "field. Nothing is summed or scored. The places' meanings are not part of the chart output."
        ),
        "above_horizon_rule": (
            "Above the earth means the planet centre's geocentric true altitude is above 0 deg, "
            "the rule this product uses for the Sun's sect. The sources say only 'above/under the "
            "earth' and do not choose between the horizon and the house division."
        ),
        "mercury_sect": (
            "Mercury's sect follows Ptolemy I.7 (morning star diurnal, evening star nocturnal), "
            "judged by ecliptic longitude east or west of the Sun; al-Bīrūnī gives no computable rule "
            "and Valens I.1 none."
        ),
        "joy_houses": (
            "A joy is met when the planet's house in the chart's selected house division is the "
            "named place."
        ),
        "sources": SOURCES,
    },
}
