"""十年期（decennials）：Valens VI.6–VI.7、Firmicus II.26–27 的「10 年 9 個月」分配。

- 起點是具名 profile，由請求選擇、收據照印：
  `firmicus_sect_light_v1`（預設）：日盤太陽、夜盤月亮，無條件（Firmicus II.26）；
  `valens_first_after_asc_v1`：上升點之後黃道順序上的第一顆行星（Valens VI.6 在兩個光體
  都不好時的起點）；`user_selected_planet_v1`：請求指定七星之一。
  Valens 要求光體「狀態好」；這是判斷，不自動化。三個 profile 都不評估光體狀態，回應以
  `start_condition_assessment` 標明這是現代的簡化。
- 順序：從起點那顆星的本命黃經起，依黃經遞增（跨 0° 回繞）排列七星（Valens VI.6 例、
  VI.7「依星座與度數」；Firmicus II.26「per signorum cursum」）。不用迦勒底序：VI.6a 的
  表用迦勒底序排列，但 Valens 在 VI.7 明白拒絕以迦勒底序找時主。黃經完全相同時依產品的
  星體順序（日 月 水 金 火 木 土）決定先後，這是產品慣例。
- 第一層：每顆星 129 個分配月（10 年 9 個月），七顆輪完再從起點繼續（「只要還有年數就
  繼續分配」）；不以壽命截斷。
- 第二層：第一層時主自己先拿，之後依同一本命順序；每顆星的月數是它的小年
  （`planetary_years.MINOR_YEARS`，合計 129），剛好填滿第一層，不截斷。
- 年模型與黃道釋放共用 `zr_year_360_days_v1`：分配年 360 日、分配月 30 日（Valens VI.6 例
  「日與循環用 360 日」）。邊界 = 出生 JD(UT) + 累計日數，以 Fraction 累加，不經民用曆。
- 只輸出第一、二層。Valens 書內第三層有三種互不相容的算法（VI.6a 表的比例法、VI.6 例的
  129 日循環、VI.7 自出生起連續的 129 日循環），v1 不輸出。
- 不輸出吉凶、主題或與其他技法的重合判斷。
"""

from __future__ import annotations

from fractions import Fraction

from .dignity_tables import DOROTHEAN, ELEMENTS, SIGNS, TRIPLICITY_IDS
from .firdaria import period_instant
from .planetary_years import MINOR_YEARS, SEVEN_PLANETS
from .source_reading import SOURCE_READING_LEVELS
# The scopes, their window and the level-2 reason are releasing's, shared as they are;
# SCOPES is re-exported here as this technique's own scope list.
from .zodiacal_releasing import (
    DEFAULT_YEAR_MODEL,
    LEVEL_2_OUTSIDE_YEAR,
    SCOPES,
    YEAR_MODELS,
    ScopeWindow,
)

DECENNIALS_PROFILE = "valens_firmicus_decennials_v1"
METHOD_PROVENANCE = "valens_vi6_vi7_firmicus_ii26_27_with_modern_level_labels"
START_PROFILES = (
    "firmicus_sect_light_v1",
    "valens_first_after_asc_v1",
    "user_selected_planet_v1",
)
DEFAULT_START_PROFILE = START_PROFILES[0]
START_PROFILE_PROVENANCE = {
    START_PROFILES[0]: "attested_firmicus_ii26",
    START_PROFILES[1]: "attested_valens_vi6_fallback_without_its_condition",
    START_PROFILES[2]: "user_choice_not_a_source_rule",
}
START_CONDITION_ASSESSMENT = "luminary_condition_not_assessed_modern_simplification"
ORDER_RULE = "natal_zodiacal_order_from_start_v1"
EQUAL_LONGITUDE_RULE = "product_body_order_sun_moon_mercury_venus_mars_jupiter_saturn"
LEVELS_EMITTED = (1, 2)
YEAR_MODEL = DEFAULT_YEAR_MODEL
DAYS_PER_YEAR: Fraction = YEAR_MODELS[YEAR_MODEL]["days_per_year"]
MONTHS_PER_LEVEL_1 = sum(MINOR_YEARS.values())

if tuple(sorted(MINOR_YEARS)) != tuple(sorted(SEVEN_PLANETS)) or MONTHS_PER_LEVEL_1 != 129:
    raise RuntimeError("a level-1 period is the 129 months of the seven minor years")


def days_per_month() -> Fraction:
    return DAYS_PER_YEAR / 12


# ── order and starting planet ──────────────────────────────────────────────


def natal_order(longitudes: dict[str, float], start: str) -> tuple[str, ...]:
    """The seven planets in increasing longitude from `start`, wrapping at 0°."""

    if set(longitudes) != set(SEVEN_PLANETS) or start not in SEVEN_PLANETS:
        raise ValueError("decennials need the seven planets' longitudes and one of them as start")
    origin = longitudes[start] % 360.0

    def key(planet: str) -> tuple[float, int]:
        return ((longitudes[planet] % 360.0 - origin) % 360.0, SEVEN_PLANETS.index(planet))

    rest = sorted((planet for planet in SEVEN_PLANETS if planet != start), key=key)
    return (start, *rest)


def sub_period_order(order: tuple[str, ...], lord: str) -> tuple[str, ...]:
    """Level 2 starts with the level-1 lord and follows the same natal order."""

    start = order.index(lord)
    return order[start:] + order[:start]


def first_after_ascendant(longitudes: dict[str, float], ascendant: float) -> str:
    """The first planet after the ascendant in zodiacal order."""

    asc = ascendant % 360.0
    return min(
        SEVEN_PLANETS,
        key=lambda planet: ((longitudes[planet] % 360.0 - asc) % 360.0, SEVEN_PLANETS.index(planet)),
    )


def start_planet(
    profile: str,
    *,
    is_day: bool | None,
    longitudes: dict[str, float],
    ascendant: float | None,
    requested_planet: str | None,
) -> str:
    if profile == START_PROFILES[0]:
        if is_day is None:
            raise ValueError("the sect-light start needs the sect")
        return "sun" if is_day else "moon"
    if profile == START_PROFILES[1]:
        if ascendant is None:
            raise ValueError("the first-after-the-ascendant start needs the ascendant")
        return first_after_ascendant(longitudes, ascendant)
    if profile == START_PROFILES[2]:
        if requested_planet not in SEVEN_PLANETS:
            raise ValueError("the user-selected start needs one of the seven planets")
        return requested_planet
    raise ValueError(f"unknown decennials start profile {profile!r}")


# ── periods ────────────────────────────────────────────────────────────────


def subdivide(parent_months: Fraction, order: tuple[str, ...]) -> list[tuple[str, Fraction]]:
    """Share a period among the seven in `order`, each in proportion to its
    minor years out of 129; level 2 of a 129-month period is the minor years
    as months."""

    return [(planet, parent_months * MINOR_YEARS[planet] / MONTHS_PER_LEVEL_1) for planet in order]


def decennial_periods(
    *,
    order: tuple[str, ...],
    scope: str,
    birth_jd_ut: float,
    window_start_jd_ut: float,
    window_end_jd_ut: float | None,
    lifetime_start_jd_ut: float | None = None,
    lifetime_end_jd_ut: float | None = None,
) -> list[dict]:
    """The level-1 periods (with their level-2 periods) the scope keeps.

    `intersecting_year` keeps what meets [window start, window end);
    `from_birth_through_year` every level-1 period starting before the window
    end, with level 2 only inside the ones meeting the window;
    `lifetime_window` every level-1 period meeting [lifetime start, lifetime
    end), with the whole level 2 of the ones meeting the window, as zodiacal
    releasing does.  A window without an end keeps only what holds its start.
    """

    month_days = days_per_month()

    def jd(months: Fraction) -> float:
        return birth_jd_ut + float(months * month_days)

    window = ScopeWindow.of(
        "decennials", scope, jd,
        window_start_jd_ut=window_start_jd_ut, window_end_jd_ut=window_end_jd_ut,
        lifetime_start_jd_ut=lifetime_start_jd_ut, lifetime_end_jd_ut=lifetime_end_jd_ut,
    )
    if len(order) != 7 or set(order) != set(SEVEN_PLANETS):
        raise ValueError("the order lists the seven planets once each")

    def as_instant(jd_ut: float) -> dict:
        return period_instant({"jd_ut": jd_ut, "status": "computed"})

    def row(period_id: str, level: int, lord: str, start: Fraction, months: Fraction) -> dict:
        if months.denominator != 1:
            raise RuntimeError("level 1 and level 2 are whole months")
        end = start + months
        return {
            "period_id": period_id,
            "level": level,
            "lord": lord,
            "months": int(months),
            "duration_days": float(months * month_days),
            "start_month_offset": int(start),
            "end_month_offset": int(end),
            "start": as_instant(jd(start)),
            "end": as_instant(jd(end)),
        }

    periods = []
    cursor = Fraction(0)
    index = 0
    while not window.past(cursor):
        lord = order[index % 7]
        months = Fraction(MONTHS_PER_LEVEL_1)
        end = cursor + months
        if window.keeps_level_1(cursor, end):
            period_id = f"L1-{index + 1}"
            period = {
                **row(period_id, 1, lord, cursor, months),
                "cycle_index": index // 7,
                "position_in_order": index % 7 + 1,
            }
            if not window.lists_level_2(cursor, end):
                period["level_2"] = None
                period["level_2_reason_code"] = LEVEL_2_OUTSIDE_YEAR
            else:
                children = []
                child_start = cursor
                for sub_index, (sub_lord, sub_months) in enumerate(
                    subdivide(months, sub_period_order(order, lord)), start=1
                ):
                    if window.keeps_level_2(child_start, child_start + sub_months):
                        children.append(
                            row(f"{period_id}.L2-{sub_index}", 2, sub_lord, child_start, sub_months)
                        )
                    child_start += sub_months
                if child_start != end:
                    raise RuntimeError("the level-2 periods fill their parent exactly")
                period["level_2"] = children
                period["level_2_reason_code"] = None
            periods.append(period)
        cursor = end
        index += 1
    return periods


# ── the sect light's triplicity lords (Dorotheus) ─────────────────────────

TRIPLICITY_TABLE = TRIPLICITY_IDS[0]
TRIPLICITY_PERIODS_REASON = "dorotheus_gives_no_handover_ages"


def sect_light_triplicity_lords(*, is_day: bool, sun_sign: str, moon_sign: str) -> dict:
    """The three Dorothean triplicity lords of the sect light's sign, in order."""

    light = "sun" if is_day else "moon"
    sign = sun_sign if is_day else moon_sign
    element = ELEMENTS[SIGNS.index(sign) % 4]
    day_first, night_first, third = DOROTHEAN[element]
    lords = [day_first, night_first, third] if is_day else [night_first, day_first, third]
    return {"sect_light": light, "sect_light_sign": sign, "element": element, "lords": lords}


# ── the printed sub-division table (Valens VI.6a) ─────────────────────────

# The five cells of VI.6a that disagree with the proportional rule by more
# than a fifth of an hour; the other 44 agree within 0.2 hours.  The values
# are Riley's as re-typeset (months, days, hours), with the rule's value in
# hours beside them.  Jupiter→Sun and Sun→Jupiter should be equal by the rule
# and are printed 12 hours apart, so these are copying slips at some stage
# (re-typeset, translation or manuscripts; Pingree's Greek not checked).
VI_6A_KNOWN_VARIANTS: tuple[tuple[str, str, tuple[int, int, float]], ...] = (
    ("saturn", "saturn", (6, 29, 6.25)),
    ("jupiter", "sun", (1, 23, 20.5)),
    ("sun", "jupiter", (1, 23, 8.5)),
    ("venus", "mercury", (1, 7, 4.25)),
    ("mercury", "mercury", (3, 3, 9.5)),
)


def proportional_sub_division_hours(period_lord: str, sub_lord: str) -> float:
    """The VI.6a cell by the rule: the level-2 period of `period_lord` shared
    by minor years out of 129, in hours of the 30-day month."""

    months = dict(subdivide(Fraction(MINOR_YEARS[period_lord]), SEVEN_PLANETS))[sub_lord]
    return float(months * days_per_month() * 24)


def _variant_rows() -> list[dict]:
    rows = []
    for period_lord, sub_lord, (months, days, hours) in VI_6A_KNOWN_VARIANTS:
        printed_hours = (months * 30 + days) * 24 + hours
        rule = proportional_sub_division_hours(period_lord, sub_lord)
        rows.append({
            "period_lord": period_lord,
            "sub_lord": sub_lord,
            "printed": [months, days, hours],
            "printed_hours": printed_hours,
            "rule_hours": round(rule, 3),
            "difference_hours": round(printed_hours - rule, 3),
        })
    return rows


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "decennials": {
        "applies_to": "annual_methods.decennials",
        "profile": DECENNIALS_PROFILE,
        "method_provenance": METHOD_PROVENANCE,
        "levels_emitted": list(LEVELS_EMITTED),
        "start_profiles": dict(START_PROFILE_PROVENANCE),
        "start_condition_assessment": START_CONDITION_ASSESSMENT,
        "order_rule": ORDER_RULE,
        "equal_longitude_rule": EQUAL_LONGITUDE_RULE,
        "year_model": YEAR_MODEL,
        "minor_years_ref": "planetary_years",
        "statement": (
            "Each planet in turn rules 129 months of 30 days (10 years 9 months of the "
            "360-day year), starting from the profile's planet and following the natal "
            "zodiacal order of the seven planets by longitude; after the seventh the "
            "first rules again. Inside each level-1 period the lord itself comes first, "
            "then the others in the same natal order, each for its minor years as months "
            "(the seven minor years total 129, so level 2 fills level 1 exactly). "
            "Boundaries are the birth JD(UT) plus the accumulated days. Levels 1 and 2 "
            "only. The Chaldean order is never used."
        ),
        "start_rules": {
            START_PROFILES[0]: (
                "day chart the Sun, night chart the Moon, unconditionally: Firmicus "
                "Mathesis II.26"
            ),
            START_PROFILES[1]: (
                "the first planet after the ascendant in zodiacal order: Valens VI.6 when "
                "both lights are badly situated; whether they are is not assessed"
            ),
            START_PROFILES[2]: "the planet named by the request",
        },
        "start_condition_note": (
            "Valens VI.6 starts from the sect light only if it is well situated, and from "
            "the first star after the ascendant if both lights are badly situated. That is "
            "a judgement this product does not make: no profile assesses the lights, and "
            "the reader chooses the profile. Treating the start as a fixed rule is a "
            "modern simplification."
        ),
        "not_emitted": (
            "level 3 and below: Valens gives three mutually incompatible rules (the "
            "proportional table of VI.6a, the 129-day cycles from the level-2 start in "
            "the VI.6 example, the continuous 129-day cycles from birth in VI.7), which "
            "give different lords for the same day of his own example"
        ),
        "known_variants": {
            "table": "Valens VI.6a (Kroll p.255, Pingree p.244), the third-stage sub-division",
            "rule": (
                "a cell is the level-2 period's months times the receiving planet's minor "
                "years over 129; 44 of the 49 printed cells agree with it within 0.2 hours"
            ),
            "cells": _variant_rows(),
            "note": (
                "These five printed cells are treated as known manuscript variants: the "
                "rule, not the printed cell, is what the product computes and tests. "
                "Which stage introduced them (the re-typeset, Riley's translation or the "
                "Greek manuscripts) is not checked against Pingree's edition."
            ),
        },
        "table_order_note": (
            "The VI.6a table lists the sub-periods in the Chaldean order (Saturn, Jupiter, "
            "Mars, Sun, Venus, Mercury, Moon from each lord); Valens's own worked example "
            "(VI.6) runs them in the natal zodiacal order, and VI.7 rejects the Chaldean "
            "order for finding the lord. The product follows the example and VI.7."
        ),
        "sources": [
            {
                "citation": "Vettius Valens, Anthologies VI.6 (Kroll pp.252-254, Pingree pp.241-243)",
                "says": (
                    "the sect light as starting point if well situated, else the first star "
                    "after the ascendant; 10 years 9 months each, then the next star in the "
                    "zodiacal circle of the nativity; the night example (Greek Horoscopes "
                    "L132): Moon, Venus, Jupiter, Saturn 43 years, then Mars, with Mars 15, Sun "
                    "19, Mercury 20, Moon 25, Venus 8, Jupiter 12, Saturn 30 months (44 years 3 "
                    "months, 51 years 3 months, 53 years 9 months); 52 years and 124 days is 53 "
                    "distribution years and 37 days, the 667th day of Saturn's sub-period; days "
                    "and cycles counted in 360-day years"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset janegca/latex-valens",
            },
            {
                "citation": "Valens VI.6a (Kroll p.255, Pingree p.244)",
                "says": "the third-stage sub-division table, 49 cells, listed in the Chaldean order",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset; the Greek not checked",
            },
            {
                "citation": "Valens VI.7 (Kroll pp.256-257, Pingree pp.245-246)",
                "says": (
                    "the lord of the day by 129-day cycles; ordering by the stars' actual signs "
                    "and degrees at the nativity, not by the Chaldean order from Saturn"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English translation via the public re-typeset",
            },
            {
                "citation": "Firmicus Maternus, Mathesis II.26-27 (Kroll-Skutsch Teubner)",
                "says": (
                    "by day from the Sun, by night from the Moon, no condition; 10 years 9 "
                    "months each, passed on in the order of the signs; each star shares its "
                    "period among the seven, itself first, in months equal to the minor years; "
                    "VI.33-39 describe each star's decennial"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Latin text of the Kroll-Skutsch Teubner edition, LacusCurtius",
            },
        ],
        "not_from_the_sources": [
            "the names 'level 1' and 'level 2' and the profile names: modern labels",
            "ordering planets of exactly equal longitude by the product's body order: a "
            "product convention",
        ],
    },
    "sect_light_triplicity_lords": {
        "applies_to": "annual_methods.decennials.sect_light_triplicity_lords",
        "table": TRIPLICITY_TABLE,
        "statement": (
            "The three Dorothean triplicity lords of the sign of the sect light (the Sun "
            "by day, the Moon by night), in their order for the chart's sect: first, "
            "second, third. Only the lords are listed; no period, age or verdict."
        ),
        "periods_reason_code": TRIPLICITY_PERIODS_REASON,
        "periods_note": (
            "Dorotheus (Pingree's translation, I.22, p.183) divides life into two parts: "
            "the first lord stands for the earlier part, the second for the later, and "
            "the third has no part of life assigned in that chapter. He gives no age at "
            "which one lord hands over to the next, so no boundary can be computed. The "
            "division of life into three equal parts is medieval (Bonatti after "
            "al-Qabisi), not Dorotheus."
        ),
        "sources": [
            {
                "citation": "Dorotheus, Carmen Astrologicum I.1 (Pingree 1976 pp.161-162)",
                "says": "the triplicity lords and their day and night order",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Pingree's English translation (1976); the Arabic not checked",
            },
            {
                "citation": "Dorotheus, Carmen Astrologicum I.22 (Pingree 1976 p.183)",
                "says": (
                    "the sect light's triplicity lords, the first for the beginning of life, "
                    "the second for its end"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Pingree's English translation (1976); the Arabic not checked",
            },
        ],
    },
}
