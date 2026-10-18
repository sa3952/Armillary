"""行星年表：七顆行星的小年、中年、大年、最大年，每一格附出處與查證狀態。

只是資料，不是時間軸。十年期的子期月數讀這裡的小年（唯一產生器）；法達的年數與黃道
釋放的星座年數是各自的表，不由這張表推導（法達的年數本來就不同；黃道釋放的摩羯是 27，
不是土星的小年 30）。

- 小年：Valens IV.1、IV.30（四分之一期間的基礎）；Firmicus II.27（十年期的子期月數）；
  Dorotheus（Pingree 英譯）I.23。三處數字相同。
- 大年：Valens IV.30 稱為「maximum」的那一列，即通稱的大年。
- 中年：小年與大年的平均。這是推論；希臘化文獻中的明確數值與用語沒有查到。
- 最大年：後世（中世紀）文獻另有一組數值；沒有查到希臘化出處，也沒有核對任何原典，所以不給數值
  （null），只留查證狀態。

查證狀態是閉集，逐格標出；未查到希臘化出處的格子不得當作已查證的古代數字引用。
"""

from __future__ import annotations

from fractions import Fraction

from .source_reading import SOURCE_READING_LEVELS

SEVEN_PLANETS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")

YEAR_KINDS = ("minor", "middle", "greater", "greatest")
VERIFICATION_STATES = (
    "attested_hellenistic_text_read",
    "derived_mean_hellenistic_source_not_confirmed",
    "later_literature_hellenistic_source_not_confirmed",
)
ATTESTED, DERIVED_MEAN, LATER_ONLY = VERIFICATION_STATES

MINOR_YEARS: dict[str, int] = {
    "saturn": 30, "jupiter": 12, "mars": 15, "sun": 19, "venus": 8, "mercury": 20, "moon": 25,
}
GREATER_YEARS: dict[str, int] = {
    "saturn": 57, "jupiter": 79, "mars": 66, "sun": 120, "venus": 82, "mercury": 76, "moon": 108,
}
# No source has been checked for the greatest years, so no number is given:
# the cell keeps its place and its state, and its value is null.
GREATEST_YEARS: dict[str, None] = {planet: None for planet in SEVEN_PLANETS}
MIDDLE_YEARS: dict[str, Fraction] = {
    planet: Fraction(MINOR_YEARS[planet] + GREATER_YEARS[planet], 2) for planet in SEVEN_PLANETS
}
for _table in (MINOR_YEARS, GREATER_YEARS, GREATEST_YEARS, MIDDLE_YEARS):
    if set(_table) != set(SEVEN_PLANETS):
        raise RuntimeError("every planetary-years row covers the seven planets")
# The decennial month count rests on this sum: 129 months fill one period exactly.
if sum(MINOR_YEARS.values()) != 129:
    raise RuntimeError("the minor years total 129")

_SOURCES: dict[str, dict] = {
    "minor": {
        "verification": ATTESTED,
        "sources": [
            {
                "citation": "Vettius Valens, Anthologies IV.1 and IV.30",
                "says": (
                    "the quarter periods are a quarter of these least periods (Saturn 7 1/2, "
                    "Jupiter 3, Mars 3 3/4, Venus 2, Mercury 5, Sun 4 3/4, Moon 6 1/4)"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset janegca/latex-valens",
            },
            {
                "citation": "Firmicus Maternus, Mathesis II.27 (Kroll-Skutsch Teubner)",
                "says": (
                    "the months of the decennial sub-periods, Sun 19, Moon 25, Saturn 30, "
                    "Jupiter 12, Mars 15, Venus 8, Mercury 20"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Latin text of the Kroll-Skutsch Teubner edition, LacusCurtius",
            },
            {
                "citation": "Dorotheus, Carmen Astrologicum I.23 (Pingree 1976)",
                "says": (
                    "the same years for a benefic on an angle; the Moon in a masculine sign "
                    "only 25 months"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Pingree's English translation (1976); the Arabic not checked",
            },
        ],
    },
    "greater": {
        "verification": ATTESTED,
        "sources": [
            {
                "citation": "Valens, Anthologies IV.30",
                "says": (
                    "the row he calls 'maximum', i.e. the periods usually called the greater "
                    "years; III.10 mentions giving the greatest, the mean or the least years "
                    "as the case requires"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the re-typeset",
            },
            {
                "citation": "Valens, Anthologies III.10, the re-typeset's editor's note",
                "says": "Venus's greater years are 'usually 82, not 84' (an editor's note, not Valens's text)",
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "the re-typeset of Riley's English translation",
            },
        ],
        "note": (
            "Venus 82 as printed in IV.30; the re-typeset's note at III.10 says Venus's "
            "greater years are 'usually 82, not 84' (an editor's note, not Valens's text)"
        ),
    },
    "middle": {
        "verification": DERIVED_MEAN,
        "sources": [],
        "note": (
            "computed here as (minor + greater) / 2; no Hellenistic text giving these "
            "values or naming the 'middle' years has been found"
        ),
    },
    "greatest": {
        "verification": LATER_ONLY,
        "sources": [],
        "note": (
            "no value is given: later (medieval) literature tabulates greatest years, but "
            "no Hellenistic source was found and no primary text was checked, so the cells "
            "stay empty until one is"
        ),
    },
}
VERIFICATION_BY_KIND = {kind: _SOURCES[kind]["verification"] for kind in YEAR_KINDS}


def _years(value: int | Fraction | None) -> float | None:
    return None if value is None else float(value)


def planetary_years_table() -> dict[str, dict]:
    """Every cell with its number and its verification state."""

    values: dict[str, dict[str, int] | dict[str, Fraction] | dict[str, None]] = {
        "minor": MINOR_YEARS, "middle": MIDDLE_YEARS,
        "greater": GREATER_YEARS, "greatest": GREATEST_YEARS,
    }
    return {
        planet: {
            kind: {
                "years": _years(values[kind][planet]),
                "verification": VERIFICATION_BY_KIND[kind],
            }
            for kind in YEAR_KINDS
        }
        for planet in SEVEN_PLANETS
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "planetary_years": {
        "applies_to": "annual_methods.decennials.minor_years_ref",
        "statement": (
            "The planets' minor, middle, greater and greatest years, every cell with its "
            "verification state. Only the minor years are used in a computation (the "
            "decennial sub-period months). Firdaria periods and the zodiacal-releasing "
            "sign periods are their own tables and are not derived from this one."
        ),
        "table": planetary_years_table(),
        "verification_states": list(VERIFICATION_STATES),
        "columns": {kind: dict(_SOURCES[kind]) for kind in YEAR_KINDS},
    },
}
