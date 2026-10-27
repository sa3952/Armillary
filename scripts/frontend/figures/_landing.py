"""The time-lord landing pages (/zh-TW/calculate/<technique>): each page's 合成範例 table, the periods the product's
annual route gives the demonstration chart (_demo.DEMO, synthetic), and the numbers the page's prose quotes.

The lifetime answer is the one the time-lords article draws its life figure from (time_lords._lifetime).  The tables
only list periods; nothing here interprets them.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import time_lords

BODY = time_lords.BODY
SIGN = time_lords.SIGN
PROFECTION_YEARS = 13  # years 1-13: one full round of the twelve signs and the return to the first
FIRDARIA_ROWS = 9      # one 75-year cycle

def _age(value: float) -> str:
    return f"{value:g}"

def _firdaria(answer: dict) -> tuple[str, list[str]]:
    method = answer["annual_methods"]["firdaria"]
    if not method["sect"]["is_day"]:
        raise RuntimeError("the firdaria page describes the demonstration chart as a day chart")
    periods = [p for p in method["periods"] if p["level"] == 1][:FIRDARIA_ROWS]
    if periods[-1]["end_year"] != 75:
        raise RuntimeError("the firdaria page says the first cycle ends at 75")
    rows = "\n".join(
        f'          <tr><td>{BODY[p["level_1_lord"]]}</td>'
        f'<td class="mono">{_age(p["start_year"])}–{_age(p["end_year"])}</td>'
        f'<td class="mono">{p["start"]["local_date"]}</td><td class="mono">{p["end"]["local_date"]}</td></tr>'
        for p in periods
    )
    first = periods[0]
    quoted = [f"第一段是{BODY[first['level_1_lord']]}主期，從 0 到 {_age(first['end_year'])} 足歲"]
    return rows, quoted

def _releasing(answer: dict) -> tuple[str, list[str]]:
    releases = {r["releasing_from"]: r for r in answer["annual_methods"]["zodiacal_releasing"]["releases"]}
    fortune = releases["fortune"]
    rows = "\n".join(
        f'          <tr><td>{SIGN[p["sign"]]}</td><td>{BODY[p["domicile_lord"]]}</td>'
        f'<td class="mono">{p["effective_units"]}</td>'
        f'<td class="mono">{p["start"]["local_date"]}</td><td class="mono">{p["effective_end"]["local_date"]}</td></tr>'
        for p in fortune["periods"] if p["level"] == 1
    )
    quoted = [f"命運點在{SIGN[fortune['start_sign']]}", f"精神點在{SIGN[releases['spirit']['start_sign']]}"]
    return rows, quoted

def _profections(lifetime: dict) -> tuple[str, list[str]]:
    years = time_lords._years(lifetime)[:PROFECTION_YEARS]
    if years[12]["profection_sign"] != years[0]["profection_sign"]:
        raise RuntimeError("the profections page says year 13 returns to the rising sign")
    rows = "\n".join(
        f'          <tr><td class="mono">{y["year_of_life"]}</td><td class="mono">{y["completed_years"]}</td>'
        f'<td class="mono">{y["start"]["local_date"]}</td><td>{SIGN[y["profection_sign"]]}</td>'
        f'<td>{BODY[y["year_lord"]]}</td></tr>'
        for y in years
    )
    quoted = [f"上升星座是{SIGN[years[0]['profection_sign']]}"]
    return rows, quoted

def _decennials(answer: dict) -> tuple[str, list[str]]:
    method = answer["annual_methods"]["decennials"]
    if method["start_profile"]["profile"] != "firmicus_sect_light_v1":
        raise RuntimeError("the decennials page shows the default Firmicus start")
    periods = [p for p in method["periods"] if p["level"] == 1]
    rows = "\n".join(
        f'          <tr><td class="mono">{p["position_in_order"] + 7 * p["cycle_index"]}</td><td>{BODY[p["lord"]]}</td>'
        f'<td class="mono">{p["start"]["local_date"]}</td><td class="mono">{p["end"]["local_date"]}</td></tr>'
        for p in periods
    )
    months = method["year_model"]["months_per_level_1"]
    quoted = [f"每段 {months} 個月", f"從{BODY[method['start_planet']]}起"]
    return rows, quoted

def build_for(technique: str) -> tuple[dict[str, str], list[str]]:
    lifetime = time_lords._lifetime()
    if technique == "profections":
        rows, quoted = _profections(lifetime)
    else:
        rows, quoted = {"firdaria": _firdaria, "releasing": _releasing, "decennials": _decennials}[technique](lifetime)
    return {f"lp-{technique}": rows}, quoted

@dataclass(frozen=True)
class Landing:
    """One landing page as `figures` builds it: `FRAGMENT` names the page, `__name__` finds the page again in a worker
    process (`page`)."""

    FRAGMENT: str
    technique: str

    @property
    def __name__(self) -> str:
        return f"{__name__}:{self.FRAGMENT}"

    def build(self) -> tuple[dict[str, str], list[str]]:
        return build_for(self.technique)

PAGES = (Landing("calculate-firdaria", "firdaria"), Landing("calculate-zodiacal-releasing", "releasing"),
         Landing("calculate-profections", "profections"), Landing("calculate-decennials", "decennials"))

def page(fragment: str) -> Landing:
    return next(landing for landing in PAGES if landing.FRAGMENT == fragment)
