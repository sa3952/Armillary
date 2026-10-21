"""The time-lords methods page: the firdaria periods and sequences, the
zodiacal releasing sign periods and the seven extended lots' day and night
formulas, from the backend tables that compute them; and the numbers its prose
quotes (the cycle totals, the year lengths and their units, the year-model
differences the year-boundary register entry measured, and how far a literal
reading of al-Biruni's month notation lands from the product's dates).
"""
from __future__ import annotations

import re
from fractions import Fraction

from ..javascript import SOURCES, frozen_string_table

LABELS_SCRIPT = SOURCES / "labels.js"
from ._common import PLANETS, SIGNS, backend_on_path


FRAGMENT = "methods-time-lords"
BODY = {**PLANETS, "north_node": "北交點", "south_node": "南交點"}
OPERAND = {**BODY, "fortune": "命運點", "spirit": "精神點", "ascendant": "上升點"}
TRADITION = {"Paulus Alexandrinus": "Paulus 第 23 章", "Vettius Valens": "Valens IV.25"}
# What al-Biruni's list of the planets' lots (Book of Instruction §476, after
# Abu Ma'shar; Wright 1934) says each same-named lot signifies.  Methods page only:
# the chart itself prints positions.  His list has no counterpart of Valens's two.
LOT_MEANING = {
    "eros_paulus_hermetic_ch23_v1": "友誼與愛",
    "necessity_paulus_hermetic_ch23_v1": "絕望、貧困與詐欺",
    "courage_paulus_hermetic_ch23_v1": "英勇與膽量",
    "victory_paulus_hermetic_ch23_v1": "勝利、凱旋與援助",
    "nemesis_paulus_hermetic_ch23_v1": "囚禁、牢獄與脫逃",
    "love_valens_iv25_v1": "al-Bīrūnī 的清單沒有這個點",
    "necessity_valens_iv25_v1": "al-Bīrūnī 的清單沒有這個點",
}
# A return year's length, only to state a magnitude: the year-boundary producer
# centres its search on the same number, and the result never depends on it.
MEAN_YEAR_DAYS = 365.24219
# al-Biruni writes a sub-period in years, months of 30 days, days and hours.
NOTATION_YEAR_DAYS = 360


def _backend() -> dict:
    with backend_on_path():
        from app.core import extended_lots, firdaria, profections, year_boundary, zodiacal_releasing

        return {
            "firdaria": firdaria,
            "lots": extended_lots,
            "releasing": zodiacal_releasing,
            "lords": dict(profections.DOMICILE_LORD),
            "year_entry": year_boundary.METHOD_SOURCE_ENTRIES["year_boundary"],
        }


def _firdaria_rows(firdaria) -> str:
    day = firdaria.DIURNAL_SEQUENCE
    night = [firdaria.NOCTURNAL_SEQUENCES[profile] for profile in firdaria.NOCTURNAL_NODE_PROFILES]
    rows = []
    for key in day:
        cells = "".join(f'<td class="mono">{order.index(key) + 1}</td>' for order in (day, *night))
        rows.append(f'          <tr><td>{BODY[key]}</td><td class="mono">{firdaria.PERIOD_YEARS[key]}</td>{cells}</tr>')
    return "\n".join(rows)


def _releasing_rows(releasing, lords: dict) -> str:
    keys = ("aries", "taurus", "gemini", "cancer", "leo", "virgo",
            "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces")
    if set(keys) != set(releasing.SIGN_PERIOD_YEARS):
        raise RuntimeError("the sign period table names other signs")
    return "\n".join(
        f'          <tr><td>{SIGNS[index]}</td><td>{BODY[lords[key]]}</td>'
        f'<td class="mono">{releasing.SIGN_PERIOD_YEARS[key]}</td></tr>'
        for index, key in enumerate(keys)
    )


def _formula(rule: dict) -> str:
    return f"上升點＋{OPERAND[rule['plus']]}−{OPERAND[rule['minus']]}"


def _lot_rows(lots) -> str:
    # The ratified short names live once, in the shared labels.
    names = frozen_string_table(LABELS_SCRIPT.read_text(encoding="utf-8"), "EXTENDED_LOT_NAMES")
    if set(names) != {method["lot_method_id"] for method in lots.LOT_METHODS}:
        raise RuntimeError("EXTENDED_LOT_NAMES does not name exactly the backend's extended lots")
    if set(LOT_MEANING) != set(names):
        raise RuntimeError("LOT_MEANING does not cover exactly the backend's extended lots")
    rows = []
    for method in lots.LOT_METHODS:
        if method["projector"] != "ascendant" or method["arc_policy"] != "reverse_arc":
            raise RuntimeError(f"{method['lot_method_id']}: the page states only ASC + plus - minus")
        rows.append(
            f'          <tr data-lot-method="{method["lot_method_id"]}"><td>{names[method["lot_method_id"]]}</td>'
            f'<td>{TRADITION[method["source_author"]]}</td>'
            f'<td>{_formula(method["day_rule"])}</td><td>{_formula(method["night_rule"])}</td>'
            f'<td>{LOT_MEANING[method["lot_method_id"]]}</td></tr>'
        )
    return "\n".join(rows)


def _hours(text: str, label: str) -> str:
    """The figure the year-boundary register entry states for one year model."""
    (found,) = [entry for entry in text if entry.startswith(label)]
    match = re.search(r"up to (\d+(?:\.\d+)?) h within 100 years", found)
    if not match:
        raise RuntimeError(f"the year-boundary entry no longer states a bound for {label!r}")
    return match.group(1)


def _notation_gap(firdaria) -> tuple[float, float, float]:
    """(the largest gap in days between al-Biruni's notation read literally after
    the return-year boundary and the product's proportional date, over every
    planetary sub-period; the first Sun sub-period's length both ways)."""
    gaps = []
    for lord, years in firdaria.PERIOD_YEARS.items():
        if lord in firdaria.NODES:
            continue
        for part in range(1, 7):
            point = Fraction(part * years, 7)
            fraction = point - (point.numerator // point.denominator)
            gaps.append(float(fraction) * (MEAN_YEAR_DAYS - NOTATION_YEAR_DAYS))
    first = Fraction(firdaria.PERIOD_YEARS["sun"], 7)
    whole = first.numerator // first.denominator
    literal = whole * MEAN_YEAR_DAYS + float(first - whole) * NOTATION_YEAR_DAYS
    return max(gaps), literal, float(first) * MEAN_YEAR_DAYS


def build() -> tuple[dict[str, str], list[str]]:
    data = _backend()
    firdaria, releasing, lots = data["firdaria"], data["releasing"], data["lots"]
    year_models = releasing.YEAR_MODELS
    days = year_models[releasing.DEFAULT_YEAR_MODEL]["days_per_year"]
    julian = year_models[releasing.JULIAN_YEAR_MODEL]["days_per_year"]
    if days != 360 or tuple(releasing.LEVELS_EMITTED) != (1, 2):
        raise RuntimeError("the page states a 360-day year and two levels")
    month = days / 12
    day_unit, hour_unit = month / 12, month / 12 / 12 * 24
    if day_unit != Fraction(5, 2):
        raise RuntimeError("the page writes the day unit as 2½ days")
    cycle = sum(releasing.SIGN_PERIOD_YEARS.values())
    gap, literal, proportional = _notation_gap(firdaria)
    others = data["year_entry"]["other_year_models_not_used"]
    chaldean = "、".join(BODY[key] for key in firdaria.CHALDEAN_ORDER)
    quoted = [
        f"九段合計 {firdaria.CYCLE_YEARS} 年",
        f"其餘依迦勒底序（{chaldean}）",
        f"十二個星座一圈合計 {cycle} 年",
        f"第一層的第二次解鎖要 {2 * cycle} 年後才會遇到",
        f"一年 {int(days)} 日、一個月 {int(month)} 日",
        f"一年 {float(julian)} 日",
        f"月再取十二分之一為日（每單位 {int(day_unit)}½ 日）",
        f"日再取十二分之一為時（每單位 {int(hour_unit)} 小時）",
        f"與均勻回歸年最多相差 {_hours(others, 'mean tropical year')} 小時",
        f"與民用週年最多相差 {_hours(others, 'civil anniversary')} 小時",
        f"照字面約 {literal:.1f} 日，比例內插約 {proportional:.1f} 日",
        f"兩種讀法最多相差約 {gap:.1f} 日",
    ]
    blocks = {
        "firdaria-periods": _firdaria_rows(firdaria),
        "zr-sign-periods": _releasing_rows(releasing, data["lords"]),
        "extended-lots": _lot_rows(lots),
    }
    return blocks, quoted
