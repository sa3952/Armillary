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
EXAMPLE_YEAR = 35      # the year Valens IV.11 works, as the methods page reads it
DECENNIAL_LEAST_MONTHS = {"sun": 19}  # the page's least-years list; only the demonstration chart's first lord is quoted

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

def _example(text: str) -> str:
    return f'    <p class="lp-example"><b>算例。</b>{text}</p>'

def _profections_example(lifetime: dict) -> str:
    years = time_lords._years(lifetime)
    rising, year = years[0], years[EXAMPLE_YEAR - 1]
    return _example(
        f"第 {year['year_of_life']} 年就是已滿 {year['completed_years']} 歲。{EXAMPLE_YEAR} 除以 12 餘 {EXAMPLE_YEAR % 12}，"
        f"從上升星座{SIGN[rising['profection_sign']]}起、含起點數到第 {EXAMPLE_YEAR % 12} 個星座，是{SIGN[year['profection_sign']]}；"
        f"{SIGN[year['profection_sign']]}的守護行星是{BODY[year['year_lord']]}，所以這一年的年主星是{BODY[year['year_lord']]}。"
        f"本站算出這一年從 {year['start']['local_date']} 起。")

def _firdaria_example(answer: dict) -> str:
    periods = [p for p in answer["annual_methods"]["firdaria"]["periods"] if p["level"] == 1]
    sun, venus, third = periods[:3]
    span = [_age(p["end_year"] - p["start_year"]) for p in (sun, venus, third)]
    return _example(
        f"日盤從{BODY[sun['level_1_lord']]}起：{BODY[sun['level_1_lord']]} {span[0]} 年、{BODY[venus['level_1_lord']]} {span[1]} 年，"
        f"接著{BODY[third['level_1_lord']]} {span[2]} 年，所以{BODY[third['level_1_lord']]}主期從 {_age(third['start_year'])} 足歲到 "
        f"{_age(third['end_year'])} 足歲；本站算出的日期是 {third['start']['local_date']} 到 {third['end']['local_date']}。"
        f"這段主期再平分成七個子期，每個子期是 {span[2]}/7 年。")

def _releasing_example(answer: dict) -> str:
    releases = answer["annual_methods"]["zodiacal_releasing"]["releases"]
    fortune = next(r for r in releases if r["releasing_from"] == "fortune")
    first, second = [p for p in fortune["periods"] if p["level"] == 1][:2]
    def days(period: dict) -> str:
        return f"{period['effective_units'] * 360:,}"
    return _example(
        f"命運點在{SIGN[first['sign']]}，第一段是{SIGN[first['sign']]} {first['effective_units']} 年。一年算 360 日，"
        f"{first['effective_units']} × 360 = {days(first)} 日，從 {first['start']['local_date']} 起算到 {first['effective_end']['local_date']}；"
        f"下一段{SIGN[second['sign']]} {second['effective_units']} 年，{days(second)} 日，到 {second['effective_end']['local_date']}。")

def _decennials_example(answer: dict) -> str:
    method = answer["annual_methods"]["decennials"]
    model = method["year_model"]
    first = next(p for p in method["periods"] if p["level"] == 1)
    months, per_month = model["months_per_level_1"], int(model["days_per_month"])
    least = DECENNIAL_LEAST_MONTHS[first["lord"]]
    return _example(
        f"第一段是{BODY[first['lord']]}。每段 {months} 個月、一個月 {per_month} 日，{months} × {per_month} = {months * per_month:,} 日，"
        f"從 {first['start']['local_date']} 起算到 {first['end']['local_date']}。這一段裡{BODY[first['lord']]}的小段是 {least} 個月"
        f"（{BODY[first['lord']]}的小年），{least} × {per_month} = {least * per_month} 日。")

def build_for(technique: str) -> tuple[dict[str, str], list[str]]:
    lifetime = time_lords._lifetime()
    if technique == "profections":
        rows, quoted = _profections(lifetime)
    else:
        rows, quoted = {"firdaria": _firdaria, "releasing": _releasing, "decennials": _decennials}[technique](lifetime)
    example = {"profections": _profections_example, "firdaria": _firdaria_example, "releasing": _releasing_example,
               "decennials": _decennials_example}[technique](lifetime)
    return {f"lp-{technique}": rows, f"lp-{technique}-example": example}, quoted

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
