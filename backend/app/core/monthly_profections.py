"""月小限（monthly profection）：年度小限的那一年分成十二個月，每月往後推一個星座。

- 星座：第 N+1 年（completed_years = N）的第 k 個月（k = 1…12）= 年度小限星座往黃道順序推
  (k−1) 個星座，即本命上升星座推 (N + k − 1) 個星座；月主 = 該星座的七政廟主（與年主同一張
  表）。第 1 個月就是年度小限星座本身；每年在太陽回歸時重新從年度小限星座數起，所以一年恰好
  十二個月，不跨年延續。只用上升**星座**，與宮位制無關。
- 月界是具名 profile，由請求選擇、收據照印：
  `monthly_profection_solar_30_degree_months_v1`（預設）：第 k 個月從太陽走到本命太陽黃經
  + 30(k−1)° 的瞬間起（Abū Maʿshar 經 Dykes 轉述；Valens IV.28 日盤以行運太陽到本命太陽的
  距離計月）。第 1 個月的起點與第 12 個月的終點就是兩次太陽回歸；每個月約 29.4–31.5 日，
  隨太陽在近日點、遠日點的快慢而變。
  `monthly_profection_return_year_twelfths_v1`：太陽回歸年的十二等分（現代軟體常見的做法，
  沒有找到古典出處），換成瞬間用年界產生器的 `solar_return_root_linear_within_year_v1`。
  兩者的星座完全相同，只有月界相差，最多將近四天。
- 瞬間由呼叫端注入的 `boundary_at(k)`（k = 0…12，年界產生器的 `SolarReturnClock`）負責，
  這裡不做任何日期算術。
- 不讀日夜盤：Valens IV.28 夜盤改用月亮的距離，這裡不採用，方法出處寫明。
- 其他定義（Ptolemy 每 28 日一宮、al-Bīrūnī 一年 13 個月、Bonatti 以度數推進）只列在方法
  出處，不計算。不輸出度數、place 主題名或任何吉凶；不與其他技法比對重合。
"""

from __future__ import annotations

from collections.abc import Callable

from .dignity_tables import SIGNS
from .firdaria import period_instant
from .profections import DOMICILE_LORD, LORD_TABLE
from .source_reading import SOURCE_READING_LEVELS

PROFILES = (
    "monthly_profection_solar_30_degree_months_v1",
    "monthly_profection_return_year_twelfths_v1",
)
DEFAULT_PROFILE = PROFILES[0]
PROFILE_PROVENANCE = {
    PROFILES[0]: "abu_mashar_as_reported_by_dykes_and_valens_iv28_day_rule_for_every_chart",
    PROFILES[1]: "modern_convention_no_classical_source_found",
}
# What one month is under each profile, for the page lane's `unit`.
MONTH_UNIT = {
    PROFILES[0]: "solar_30_degree_step",
    PROFILES[1]: "return_year_twelfth",
}
METHOD_PROVENANCE = "medieval_monthly_profection_from_the_year_sign_v1"
MONTHS_PER_YEAR = 12
FIRST_MONTH_RULE = "first_month_is_the_annual_profection_sign"


def monthly_profections(
    natal_ascendant_sign: str,
    *,
    completed_years: int,
    boundary_at: Callable[[int], dict],
    name_lords: bool,
) -> list[dict]:
    """The twelve months of year N+1, each with its sign, its lord and its two
    day-precision boundaries; `boundary_at(k)` is the instant month k+1 starts
    (k = 0…11) or month 12 ends (k = 12)."""

    if completed_years < 0:
        raise ValueError("completed years start at 0")
    start_index = SIGNS.index(natal_ascendant_sign)
    edges = [boundary_at(k) for k in range(MONTHS_PER_YEAR + 1)]
    rows = []
    for month in range(1, MONTHS_PER_YEAR + 1):
        offset = completed_years + month - 1
        sign = SIGNS[(start_index + offset) % 12]
        rows.append({
            "period_id": f"Y{completed_years}.M{month}",
            "year_period_id": f"Y{completed_years}",
            "completed_years": completed_years,
            "month_of_year": month,
            "offset_from_year_sign": month - 1,
            "profected_place": offset % 12 + 1,
            "sign": sign,
            "domicile_lord": DOMICILE_LORD[sign] if name_lords else None,
            "start": period_instant(edges[month - 1]),
            "end": period_instant(edges[month]),
        })
    return rows


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "monthly_profection": {
        "applies_to": "annual_methods.monthly_profection",
        "profiles": dict(PROFILE_PROVENANCE),
        "default_profile": DEFAULT_PROFILE,
        "method_provenance": METHOD_PROVENANCE,
        "lord_table": LORD_TABLE,
        "statement": (
            "Month k (k = 1-12) of year of life N+1 is the annual profection sign moved "
            "k-1 signs on in zodiacal order, so the first month is the year's own sign and "
            "the count starts again at every solar return; the lord of the month is that "
            "sign's seven-planet domicile lord. By default month k begins when the Sun has "
            "moved 30(k-1) degrees past its natal longitude, so the first month begins at "
            "the return and the twelfth ends at the next one; the named alternative cuts "
            "the return year into twelve equal parts. Whole signs only; the sect is not "
            "read. No degree, no topic of the place and no verdict is emitted."
        ),
        "sources": [
            {
                "citation": "Vettius Valens, Anthologies IV.28 (Kroll p.204, Pingree p.194)",
                "says": (
                    "for a day birth, the distance from the Sun at the moment in question to "
                    "the natal Sun, counted from the sign allotted the year, gives the month; "
                    "for a night birth the Moon's distance; no worked example with numbers. "
                    "The Greek is not checked, so whether the distance is counted in whole "
                    "signs or in 30-degree steps is not settled from it"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset janegca/latex-valens",
            },
            {
                "citation": (
                    "Abu Ma'shar, On the Revolutions of the Years of Nativities, tr. B. Dykes, "
                    "Persian Nativities IV (2019)"
                ),
                "says": (
                    "the year's sign is also the first month's sign and each following sign "
                    "the next month; the monthly revolution charts are cast when the Sun "
                    "reaches the natal Sun's degree in each following sign, the solar return "
                    "being also the first month; Ptolemy's monthly method rejected. Timing the "
                    "profected months by those same instants is the product's reading of that "
                    "summary"
                ),
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": (
                    "known only from Dykes's spoken summary (The Astrology Podcast, episode "
                    "218, 2019); the book is not checked"
                ),
            },
            {
                "citation": (
                    "al-Biruni, Book of Instruction in the Elements of the Art of Astrology, tr. "
                    "R. R. Wright (1934), section 522"
                ),
                "says": (
                    "the monthly revolution is taken each time the Sun reaches the degree and "
                    "minute it held at the nativity or the revolution; the same section divides "
                    "the profection year into thirteen months of 28 days 1 hour 51 minutes, the "
                    "thirteenth repeating the year's sign, which the product does not compute"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Wright's English translation",
            },
            {
                "citation": "Guido Bonatti, Liber astronomiae Tr.9 (Dykes translation)",
                "says": (
                    "profection by equal degrees, 30 degrees a year, 2 degrees 30 minutes a "
                    "month, 5 minutes a day, counted from birth; a different method the product "
                    "does not compute"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Dykes's English translation",
            },
        ],
        "named_disagreement_not_adopted": {
            "citation": "Ptolemy, Tetrabiblos IV.10 (Robbins, Loeb p.453 and note 82)",
            "says": (
                "months of 28 days to a sign counted from the places that govern the year, "
                "and days of 2 1/3 days to a sign; the note records 30 days to a sign "
                "(Bouche-Leclercq, Cardanus, without manuscript support) and 2 1/2 days (two "
                "manuscripts). About 13.04 such months fall in a year and they do not restart "
                "at the return, so they do not fit the return year; not computed"
            ),
            "reading": SOURCE_READING_LEVELS[1],
            "read_at": (
                "Robbins's English (Loeb 1940): the whole of IV.10 read in the LacusCurtius "
                "transcription; the Greek not checked"
            ),
        },
        "not_from_the_sources": [
            "the Sun's 30-degree steps for a night birth: Valens IV.28 uses the Moon by "
            "night; the product uses the Sun for every chart, as Abu Ma'shar is reported "
            "to do",
            "the equal-twelfths profile: no classical source for it was found; it is the "
            "arrangement common in modern software",
            "the profile names and the word 'month' for a 30-degree step of the Sun",
        ],
        "worked_example": (
            "none: no source read gives a monthly profection with numbers; the tests "
            "check the rule against Swiss Ephemeris's own solar crossing and hand-typed "
            "sign tables"
        ),
    },
}
