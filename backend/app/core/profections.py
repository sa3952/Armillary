"""年度小限（annual profection）：自本命上升星座起，每年推進一個星座。

v1 唯一 profile `annual_profection_ascendant_sign_v1`：第 Y 年（completed_years = Y−1）的
年傳星座 = 本命上升星座往黃道順序推進 (Y−1) 個星座；第幾 place = ((Y−1) mod 12) + 1
（自上升星座起算、含起點）；年主 = 該星座的七政廟主。

- 只用上升**星座**，與宮位制無關：換宮制不得改變年傳。
- 年主表固定七政（現代外行星主宰不在產品範圍）：天蠍、水瓶、雙魚永遠是火星、土星、木星；廟主由尊貴表的
  `DOMICILE_SIGNS` 反查，不另寫一張。
- 不輸出度數、place 主題名或任何吉凶；年界由 `year_boundary` 提供，這裡不算日期。
- 恆星黃道下年傳星座照算（恆星黃道星座），年主沿用尊貴表對恆星黃道的拒絕：
  `lord_frame_state` 讀中央相容表的 essential_dignities 列，不自己判斷。

Valens IV.11 的「第 35 年」從處女座上升數 11 個星座到巨蟹，即 completed_years = 34、
place 11，與本公式一致；若把 35 讀成「已滿 35 歲」會得獅子（place 12），與原文不符。
"""

from __future__ import annotations

from .dignity_tables import DOMICILE_SIGNS, SIGNS
from .frame_compatibility import method_frame_state
from .source_reading import SOURCE_READING_LEVELS

PROFECTION_PROFILE = "annual_profection_ascendant_sign_v1"
PROFECTION_PROVENANCE = "hellenistic_annual_profection_from_ascendant_v1"
LORD_TABLE = "traditional_seven_domicile_v1"

DOMICILE_LORD: dict[str, str] = {
    sign: planet for planet, signs in DOMICILE_SIGNS.items() for sign in signs
}
if set(DOMICILE_LORD) != set(SIGNS):
    raise RuntimeError("every sign needs exactly one seven-planet domicile lord")


def profect(natal_ascendant_sign: str, *, completed_years: int) -> dict:
    """The profected sign, place and lord after `completed_years` years."""

    if completed_years < 0:
        raise ValueError("completed years start at 0")
    offset = completed_years % 12
    sign = SIGNS[(SIGNS.index(natal_ascendant_sign) + offset) % 12]
    return {
        "natal_ascendant_sign": natal_ascendant_sign,
        "offset_signs": offset,
        "profected_sign": sign,
        "profected_place": offset + 1,
        "lord_body_key": DOMICILE_LORD[sign],
    }


def lord_frame_state(mode) -> dict:
    """Whether a domicile lord may be named in this frame (the dignity row)."""

    return method_frame_state("essential_dignities", mode)


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "annual_profection": {
        "applies_to": "annual_methods.annual_profection",
        "profile": PROFECTION_PROFILE,
        "method_provenance": PROFECTION_PROVENANCE,
        "lord_table": LORD_TABLE,
        "statement": (
            "Year of life Y profects the natal ascendant sign by Y-1 signs in zodiacal "
            "order; the place is ((Y-1) mod 12) + 1 counted inclusively from the "
            "ascendant sign; the lord of the year is that sign's seven-planet domicile "
            "lord. Whole signs only: the house system does not enter. No degree, no "
            "topic of the place and no verdict is emitted."
        ),
        "sources": [
            {
                "citation": "Vettius Valens, Anthologies IV.11 (Kroll p.174, Pingree p.165)",
                "says": (
                    "in Riley's English: 'We are investigating the 35th year. I divide <35> by 12 ... remainder "
                    "11 ... 11 signs from the Ascendant and Mars <in Virgo> to Saturn in "
                    "Cancer'"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": (
                    "Kroll's Greek (1908, p.174) for the sentence on the 35th year (see "
                    "counting_note); the rest in Riley's English; Pingree's edition not checked"
                ),
            },
            {
                "citation": "Vettius Valens, Anthologies IV.9 (Kroll 1908 p.169), Kroll's note on the 33rd year",
                "says": "reads the 31st and 32nd years as complete and the 33rd as not yet complete",
                "reading": SOURCE_READING_LEVELS[3],
                "read_at": (
                    "level pending: the counting note reports Kroll's note, but the record "
                    "does not say p.169 was read; only the reference is claimed"
                ),
            },
            {
                "citation": "Firmicus Maternus, Mathesis II.27.3-4, II.28.3 (Kroll-Skutsch 1897 vol.1 pp.76-77)",
                "says": "annual profection and lord of the year",
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "as checked by the project's research notes, not re-read for this entry",
            },
            {
                "citation": "Paulus Alexandrinus ch.31",
                "says": "profection",
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "as cited by the research notes after their correction, not re-read for this entry",
            },
        ],
        "named_disagreement_not_adopted": {
            "citation": "Ptolemy, Tetrabiblos IV.10 (Robbins, Loeb p.453)",
            "says": (
                "profections from each of several releasing places; v1 profects the "
                "ascendant only and is not Ptolemy's procedure"
            ),
            "reading": SOURCE_READING_LEVELS[1],
            "read_at": (
                "Robbins's English (Loeb 1940): the whole of IV.10 read in the LacusCurtius "
                "transcription; the Greek not checked"
            ),
        },
        "counting_note": (
            "Valens's '35th year' is an ordinal, so it is 34 completed years: Kroll's "
            "Greek (1908, p.174) has the singular with the article, 'ἐν τῷ λε' ἔτει', "
            "where a cardinal count would be the plural ἔτη. Supporting: at IV.9 "
            "(p.169) Kroll's note on the 33rd year reads the 31st and 32nd as complete "
            "and the 33rd as not yet complete. Pingree's edition not checked."
        ),
    },
}
