"""黃道釋放（zodiacal releasing）：Valens IV.4 自福點與 Daimon（精神點）起的分配。

- 起點：福點、精神點主要值所在星座（整宮）；兩條都算、並列，不依性別或「受剋改用」選一條。
  點的黃經由 `lots.compute_lots` 產生（呼叫端傳入），這裡只收星座。
- 星座年數是獨立的 profile `valens_iv4_sign_periods_capricorn27_v1`：各星座取廟主的最小年，
  但摩羯 27、水瓶 30（Valens IV.4 例表、IV.6 解釋其來由）；不由通用行星小年表推導
  （土星的最小年是 30）。十二星座一圈合計 211。
- 第一層（現代稱 L1）以「年」為單位，第二層（L2）以「月」（年的十二分之一）為單位，數字相同；
  子期從父期星座開始依黃道順序排列，父期到期即截斷（`truncated`，名目長度照留）。
- 解鎖（loosing of the bond）：一圈十二個星座輪完仍未到父期終點，就從這一圈起點的**對宮**
  繼續（IV.4 雙子例：17 年 7 個月後自射手起）；不用三分（Valens 明言不採）。第一層同理，
  滿 211 年後跳對宮；第二圈再滿時再跳一次是同一規則的產品外推，Valens 只寫一次。
- 年長由具名的年模型決定：預設 `zr_year_360_days_v1`（IV.9〈普遍年〉章：分配年 360 日；
  IV.4「不計閏日」）；其他年模型標為現代慣例。邊界 = 出生 JD(UT) + 累計日數，以 Fraction
  累加，不經民用曆、不經太陽回歸年界。
- 每筆期間帶從福點數的位置（1–12，含起點）與 angular／succedent／cadent；精神點的期間也從
  福點數（IV.7 以福點為參照），另附從起點數的位置。不輸出 peak、主題或吉凶。
- L1、L2 以外的層級不輸出。Valens IV.10 其實有日、時兩層（月再取十二分之一為日，每單位
  2½ 日；日再取十二分之一為時，每單位 5 小時；每一層輪完十二星座都解縛到對宮）。v1 不輸出
  的理由是出生時刻的精度與假精度（時層的單位只有 5 小時，與常見的出生時間不確定度同一量級），
  不是「不在 Valens」。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction

from .dignity_tables import SIGNS
from .firdaria import period_instant
from .profections import DOMICILE_LORD, LORD_TABLE
from .source_reading import SOURCE_READING_LEVELS

RELEASING_PROFILE = "valens_fortune_spirit_releasing_v1"
SIGN_PERIOD_TABLE_PROFILE = "valens_iv4_sign_periods_capricorn27_v1"
METHOD_PROVENANCE = "valens_iv4_core_with_modern_level_labels"
SCOPES = ("intersecting_year", "from_birth_through_year", "lifetime_window")
LEVELS_EMITTED = (1, 2)
RELEASING_FROM = ("fortune", "spirit")
ENTRY_KINDS = ("first_of_parent", "sequential", "loosing_of_the_bond")
ANGULARITY = ("angular", "succedent", "cadent")
UNIT_NAMES = {1: "zr_year", 2: "zr_month"}
LEVEL_2_OUTSIDE_YEAR = "level_2_listed_only_for_periods_meeting_the_year"

SIGN_PERIOD_YEARS: dict[str, int] = {
    "aries": 15, "taurus": 8, "gemini": 20, "cancer": 25, "leo": 19, "virgo": 20,
    "libra": 8, "scorpio": 15, "sagittarius": 12, "capricorn": 27, "aquarius": 30,
    "pisces": 12,
}
if set(SIGN_PERIOD_YEARS) != set(SIGNS) or sum(SIGN_PERIOD_YEARS.values()) != 211:
    raise RuntimeError("the sign periods cover the twelve signs and total 211")

DEFAULT_YEAR_MODEL = "zr_year_360_days_v1"
JULIAN_YEAR_MODEL = "zr_year_365_25_days_v1"
ATTESTED = "attested_valens_iv4_iv9"
MODERN_CONVENTION = "modern_convention_not_attested_in_valens"
YEAR_MODELS: dict[str, dict] = {
    DEFAULT_YEAR_MODEL: {"days_per_year": Fraction(360), "provenance": ATTESTED},
    JULIAN_YEAR_MODEL: {"days_per_year": Fraction(1461, 4), "provenance": MODERN_CONVENTION},
}


@dataclass(frozen=True)
class ScopeWindow:
    """Which periods a scope keeps, for releasing and core.decennials alike.

    `to_jd` maps a period's offset from birth (days here, months there) to
    JD(UT).  `intersecting_year` keeps what meets [window start, window end);
    `from_birth_through_year` every period starting before the window end;
    `lifetime_window` every level-1 period meeting [lifetime start, lifetime
    end) and the whole level 2 of the ones listed.  Outside
    `intersecting_year`, level 2 is listed only inside a period meeting the
    window.  A window without an end keeps only what holds its start.
    """

    scope: str
    to_jd: Callable[[Fraction], float]
    window_start_jd_ut: float
    window_end_jd_ut: float | None
    lifetime_start_jd_ut: float
    lifetime_end_jd_ut: float

    @classmethod
    def of(
        cls,
        technique: str,
        scope: str,
        to_jd: Callable[[Fraction], float],
        *,
        window_start_jd_ut: float,
        window_end_jd_ut: float | None,
        lifetime_start_jd_ut: float | None,
        lifetime_end_jd_ut: float | None,
    ) -> ScopeWindow:
        if scope not in SCOPES:
            raise ValueError(f"unknown {technique} scope {scope!r}")
        if scope == SCOPES[2] and (lifetime_start_jd_ut is None or lifetime_end_jd_ut is None):
            raise ValueError("the lifetime window needs both of its instants")
        return cls(
            scope, to_jd, window_start_jd_ut, window_end_jd_ut,
            -math.inf if lifetime_start_jd_ut is None else lifetime_start_jd_ut,
            math.inf if lifetime_end_jd_ut is None else lifetime_end_jd_ut,
        )

    @property
    def lifetime(self) -> bool:
        return self.scope == SCOPES[2]

    def meets(self, start: Fraction, end: Fraction) -> bool:
        if self.window_end_jd_ut is None:
            return self.to_jd(start) <= self.window_start_jd_ut < self.to_jd(end)
        return self.to_jd(start) < self.window_end_jd_ut and self.to_jd(end) > self.window_start_jd_ut

    def _kept(self, start: Fraction, end: Fraction) -> bool:
        if self.scope == SCOPES[1] and self.window_end_jd_ut is not None:
            return self.to_jd(start) < self.window_end_jd_ut
        return self.meets(start, end)

    def keeps_level_1(self, start: Fraction, end: Fraction) -> bool:
        if self.lifetime:
            return self.to_jd(start) < self.lifetime_end_jd_ut and self.to_jd(end) > self.lifetime_start_jd_ut
        return self._kept(start, end)

    def keeps_level_2(self, start: Fraction, end: Fraction) -> bool:
        return self.lifetime or self._kept(start, end)

    def lists_level_2(self, start: Fraction, end: Fraction) -> bool:
        return self.scope == SCOPES[0] or self.meets(start, end)

    def past(self, start: Fraction) -> bool:
        if self.lifetime:
            return self.to_jd(start) >= self.lifetime_end_jd_ut
        if self.window_end_jd_ut is None:
            return self.to_jd(start) > self.window_start_jd_ut
        return self.to_jd(start) >= self.window_end_jd_ut
YEAR_MODEL_IDS = tuple(YEAR_MODELS)


def position_from(reference_sign: str, sign: str) -> int:
    """Whole-sign place of `sign` counted inclusively from `reference_sign`."""

    return (SIGNS.index(sign) - SIGNS.index(reference_sign)) % 12 + 1


def angularity(position: int) -> str:
    return ANGULARITY[(position - 1) % 3]


def elapsed_distribution_time(year_model: str, elapsed_days: float) -> dict:
    """Days since birth as whole years of the model plus the remaining days."""

    days_per_year = float(YEAR_MODELS[year_model]["days_per_year"])
    completed, days = divmod(elapsed_days, days_per_year)
    return {"completed_years": int(completed), "days": days}


def _sign_sequence(first: str) -> Iterator[tuple[str, str]]:
    """Signs in zodiacal order from `first`; after each full circle of twelve,
    the next starts at the sign opposite that circle's own start."""

    circle_start = SIGNS.index(first)
    current, emitted, kind = circle_start, 0, ENTRY_KINDS[0]
    while True:
        yield SIGNS[current], kind
        emitted += 1
        if emitted == 12:
            circle_start = (circle_start + 6) % 12
            current, emitted, kind = circle_start, 0, ENTRY_KINDS[2]
        else:
            current, kind = (current + 1) % 12, ENTRY_KINDS[1]


def releasing_periods(
    *,
    start_sign: str,
    fortune_sign: str,
    year_model: str,
    scope: str,
    birth_jd_ut: float,
    window_start_jd_ut: float,
    window_end_jd_ut: float | None,
    name_lords: bool,
    lifetime_start_jd_ut: float | None = None,
    lifetime_end_jd_ut: float | None = None,
) -> list[dict]:
    """The level-1 periods (with their level-2 periods) the scope keeps.

    `intersecting_year` keeps what meets [window start, window end);
    `from_birth_through_year` every level-1 period that starts before the
    window end, with level 2 only inside the ones meeting the window.
    `lifetime_window` every level-1 period meeting [lifetime start, lifetime
    end), with the whole level 2 of the ones meeting the window: a reader
    asks for a year inside the level-1 period whose level 2 it wants.
    A window without an end (its end lies outside the supported years) keeps
    only what holds its start.
    """

    days_per_year = YEAR_MODELS[year_model]["days_per_year"]
    unit_days = {1: days_per_year, 2: days_per_year / 12}

    def jd(day: Fraction) -> float:
        return birth_jd_ut + float(day)

    window = ScopeWindow.of(
        "zodiacal releasing", scope, jd,
        window_start_jd_ut=window_start_jd_ut, window_end_jd_ut=window_end_jd_ut,
        lifetime_start_jd_ut=lifetime_start_jd_ut, lifetime_end_jd_ut=lifetime_end_jd_ut,
    )

    def row(level, index, sign, kind, start, nominal, end, parent_id) -> dict:
        effective_units = (end - start) / unit_days[level]
        if effective_units.denominator != 1:
            raise RuntimeError("an effective length is a whole number of units")
        position = position_from(fortune_sign, sign)
        prefix = f"{parent_id}." if parent_id else ""
        return {
            "period_id": f"{prefix}L{level}-{index}",
            "level": level,
            "sign": sign,
            "domicile_lord": DOMICILE_LORD[sign] if name_lords else None,
            "entry_kind": kind,
            "unit": UNIT_NAMES[level],
            "nominal_units": SIGN_PERIOD_YEARS[sign],
            "effective_units": int(effective_units),
            "nominal_duration_days": float(nominal),
            "start_day_offset": float(start),
            "effective_end_day_offset": float(end),
            "start": period_instant({"jd_ut": jd(start), "status": "computed"}),
            "effective_end": period_instant({"jd_ut": jd(end), "status": "computed"}),
            "truncated": end < start + nominal,
            "position_from_fortune": position,
            "angularity_from_fortune": angularity(position),
            "position_from_start_lot": position_from(start_sign, sign),
        }

    def children(parent_sign: str, start: Fraction, end: Fraction, parent_id: str) -> list:
        rows = []
        cursor = start
        for index, (sign, kind) in enumerate(_sign_sequence(parent_sign), start=1):
            if cursor >= end:
                break
            nominal = SIGN_PERIOD_YEARS[sign] * unit_days[2]
            child_end = min(cursor + nominal, end)
            if window.keeps_level_2(cursor, child_end):
                rows.append(row(2, index, sign, kind, cursor, nominal, child_end, parent_id))
            cursor = child_end
        return rows

    periods = []
    cursor = Fraction(0)
    for index, (sign, kind) in enumerate(_sign_sequence(start_sign), start=1):
        if window.past(cursor):
            break
        nominal = SIGN_PERIOD_YEARS[sign] * unit_days[1]
        end = cursor + nominal
        if window.keeps_level_1(cursor, end):
            period = row(1, index, sign, kind, cursor, nominal, end, None)
            # From birth, level 2 is listed only where the parent meets the year:
            # every earlier parent's sub-periods would grow the response with
            # the age and multiply by the samples of a non-exact time.
            if not window.lists_level_2(cursor, end):
                period["level_2"] = None
                period["level_2_reason_code"] = LEVEL_2_OUTSIDE_YEAR
            else:
                period["level_2"] = children(sign, cursor, end, period["period_id"])
                period["level_2_reason_code"] = None
            periods.append(period)
        cursor = end
    return periods


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "zodiacal_releasing": {
        "applies_to": "annual_methods.zodiacal_releasing",
        "profile": RELEASING_PROFILE,
        "period_table_profile": SIGN_PERIOD_TABLE_PROFILE,
        "sign_period_years": dict(SIGN_PERIOD_YEARS),
        "method_provenance": METHOD_PROVENANCE,
        "levels_emitted": list(LEVELS_EMITTED),
        "lord_table": LORD_TABLE,
        "statement": (
            "Released from the signs of the Lot of Fortune and the Lot of Spirit "
            "(Daimon), both listed. A sign's period is its number from the period "
            "table: years at level 1, months (a twelfth of the year model) at level 2. "
            "Level-2 periods start in the parent's sign, follow zodiacal order and are "
            "cut where the parent ends (nominal length kept beside the effective one). "
            "When a circle of twelve signs (211 units) is complete before the parent "
            "ends, the next period starts at the sign opposite that circle's start "
            "(loosing of the bond), never the trine. Boundaries are the birth JD(UT) "
            "plus the accumulated days of the year model. Places are counted from the "
            "sign of Fortune for both lots, with the count from the starting lot beside it."
        ),
        "year_models": {
            DEFAULT_YEAR_MODEL: {
                "days_per_year": 360,
                "provenance": ATTESTED,
                "basis": (
                    "Valens IV.9 'The Universal Year' (Kroll p.169): the universal year "
                    "has 365 1/4 days, the year of the distribution 360; IV.4: the 17 "
                    "years 7 months are allotted 'not counting the intercalary days'; "
                    "IV.8: 'he takes the allotment of years and converts it to 360 days'"
                ),
            },
            JULIAN_YEAR_MODEL: {
                "days_per_year": 365.25,
                "provenance": MODERN_CONVENTION,
                "basis": (
                    "the same periods measured in Julian years of 365 1/4 days: a "
                    "single-setting alternative in some modern software (Stellium's "
                    "documented year_length=365.25 'civil-year variant'; AstroApp's "
                    "'Year' setting), never shown beside the 360-day dates there; "
                    "Valens uses 365 1/4 only for the universal year he converts from, "
                    "never for the distribution"
                ),
            },
        },
        "sources": [
            {
                "citation": "Vettius Valens, Anthologies IV.4 (/160K/-/163K/, /152P/-/154P/)",
                "says": (
                    "Fortune and Daimon as starting points; the Aries and Taurus sub-period "
                    "tables; loosing to the opposite sign after 17 years 7 months; the trine "
                    "rejected"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": (
                    "Riley's English translation via the public re-typeset "
                    "(janegca/latex-valens); Pingree's Greek not checked"
                ),
            },
            {
                "citation": "Valens IV.6 (the /156P/ marker falls in it)",
                "says": "why Capricorn allots 27 and Aquarius 30",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset",
            },
            {
                "citation": "Valens IV.7 (/165K/-/167K/, /157P/-/158P/)",
                "says": "places counted from Fortune; the places square with the lots",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset",
            },
            {
                "citation": "Valens IV.8 'A Compelling Example' (/167K/-/169K/, /158P/-/160P/)",
                "says": "Fortune in Leo, Daimon in Scorpio, every period length named",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset",
            },
            {
                "citation": "Valens IV.9 'The Universal Year' (Kroll p.169)",
                "says": (
                    "the 360-day year of the distribution and the worked conversion 32 x 365 "
                    "1/4 + 215 days = 33 distribution years 23 days"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "Kroll's Greek (1908); Riley's English read beside it",
            },
            {
                "citation": (
                    "Valens IV.10 'The Breakdown into Longer and Shorter Periods' "
                    "(/169K/-/171K/, /161P/-/162P/)"
                ),
                "says": (
                    "a twelfth of the month gives the days (2 1/2 days a unit), a twelfth of "
                    "the day the hours (5 hours a unit), with the loosing of the bond at every "
                    "level and a worked example down to the hours"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "Kroll's Greek (1908); Riley's English read beside it",
            },
        ],
        "not_from_valens": [
            "the names 'zodiacal releasing' and 'level 1'/'level 2': modern "
            "systematisation (Schmidt, Brennan)",
            "a second loosing at level 1 after 422 units: the product applies the "
            "same rule again; Valens states it once",
            "any 'peak' grading: not emitted",
        ],
        "not_applied": (
            "Valens IV.4: when Fortune and Daimon share a sign, activity is released "
            "from the following sign; the response flags fortune_spirit_same_sign and "
            "does not apply the rule"
        ),
    },
}
