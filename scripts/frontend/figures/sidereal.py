"""〈回歸黃道和恆星黃道差在哪〉: table 1 (one chart in the tropical zodiac and
in the product's four sidereal ones: the ayanamsa subtracted, the Sun, the Moon,
the Ascendant and the first whole-sign house), table 2 (the Fagan–Bradley
ayanamsa on four dates) and the numbers the prose quotes.

Synthetic instants only: the demonstration chart (1990-05-15 14:30 Taipei,
whole signs) and noon in Taipei on 1 January of four years.  Every value is
the product's answer in process: `astronomical_data.time.ayanamsa` is the
offset the product reports as applied.  The module also asks the product for
the refusals the prose names (the dignities and the lunar mansions in a
sidereal zodiac, the sidereal zodiac with the J2000 frame) and checks that the
degree-based aspects do not change with the zodiac.
"""
from __future__ import annotations

import functools
from typing import Any

from ._common import SIGNS, degree_minute, product_charts
from ._demo import DEMO, zodiacal_minutes


FRAGMENT = "blog-tropical-vs-sidereal-zodiac"
# The product's four, in the order the calculator lists them.
AYANAMSAS = (
    ("fagan_bradley", "Fagan–Bradley"),
    ("hipparchos", "Hipparchos"),
    ("sassanian", "Sassanian"),
    ("aldebaran_15_tau", "Aldebaran 15° 金牛"),
)
YEARS = (1900, 1950, 2000, 2026)
OPTIONS = {"house_system": "W", "include_houses": True, "include_domicile_exaltation": True,
           "include_lunar_mansions": True}


def _sidereal(ayanamsa: str) -> dict:
    return {"zodiac": "sidereal", "ayanamsa": ayanamsa}


def _read(answer: dict) -> dict:
    bodies = {item["key"]: item["longitude"] for item in answer["astronomical_data"]["bodies"]}
    pairs = answer["derived_methods"]["aspects"]["pairs"]
    return {
        "ayanamsa": answer["astronomical_data"]["time"]["ayanamsa"],
        "bodies": bodies,
        "sun": bodies["sun"],
        "moon": bodies["moon"],
        "asc": answer["astronomical_data"]["angles"]["asc"],
        "first_house": answer["derived_methods"]["house_division"]["cusps"][0],
        # Each pair's degree-based verdicts (separation, aspects in orb) and its whole-sign configuration.
        "degree": {(p["body_a"], p["body_b"]): (round(p["separation_degrees"], 9),
                                                tuple(t["key"] for t in p["aspect_targets"] if t["in_orb"]))
                   for p in pairs},
        "whole_sign": {**{(p["body_a"], p["body_b"]): p["configuration_key"]
                          for p in answer["derived_methods"]["aspects"]["whole_sign_aversions"]},
                       **{(p["body_a"], p["body_b"]): p["whole_sign"]["configuration_key"] for p in pairs}},
        "evaluated": answer["derived_methods"]["aspects"]["pair_listing"]["evaluated_pairs"],
        "dignities": answer["derived_methods"]["essential_dignities"]["reason_code"],
        "mansions": answer["derived_methods"]["lunar_mansions"]["reason_code"],
    }


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    chart = {**DEMO, "options": {**DEMO["options"], **OPTIONS}}
    with product_charts() as post:
        out: dict[str, Any] = {"tropical": _read(post(chart))}
        for key, _ in AYANAMSAS:
            out[key] = _read(post({**chart, "computation_mode": _sidereal(key)}))
        out["years"] = {}
        for year in YEARS:
            noon = {**DEMO, "datetime": {"year": year, "month": 1, "day": 1, "hour": 12, "minute": 0, "second": 0},
                    "computation_mode": _sidereal("fagan_bradley")}
            out["years"][year] = post(noon)["astronomical_data"]["time"]["ayanamsa"]
        refused = post({**DEMO, "computation_mode": {**_sidereal("fagan_bradley"), "ecliptic_frame": "j2000"}},
                       expected=422)
        out["j2000"] = [issue["type"] for issue in refused["detail"]["issues"]]
    return out


def _check(data: dict) -> None:
    tropical = data["tropical"]
    if tropical["ayanamsa"] is not None or tropical["dignities"] is not None or tropical["mansions"] is not None:
        raise RuntimeError("the tropical chart no longer computes the dignities and mansions without an ayanamsa")
    for key, _ in AYANAMSAS:
        chart = data[key]
        for body in ("sun", "moon", "asc"):
            if abs((tropical[body] - chart["ayanamsa"] - chart[body] + 180) % 360 - 180) > 1 / 3600:
                raise RuntimeError(f"{key}: the {body} is not the tropical one less the reported ayanamsa")
        if chart["first_house"] != (chart["asc"] // 30) * 30:
            raise RuntimeError(f"{key}: the first whole-sign house is not the sidereal Ascendant's sign")
        # A pair is listed when it has an aspect; one listed under a single zodiac must have none in orb.
        for pair in set(chart["degree"]) | set(tropical["degree"]):
            here, there = chart["degree"].get(pair), tropical["degree"].get(pair)
            if (here and there and here != there) or (here is None and there[1]) or (there is None and here[1]):
                raise RuntimeError(f"{key}: the degree-based aspects of {pair} change with the zodiac")
        if len(chart["whole_sign"]) != chart["evaluated"] or set(chart["whole_sign"]) != set(tropical["whole_sign"]):
            raise RuntimeError(f"{key}: the whole-sign configurations do not cover every evaluated pair")
        if (chart["dignities"], chart["mansions"]) != ("sidereal_dignity_basis_not_authorized",
                                                       "sidereal_lunar_mansion_basis_not_authorized"):
            raise RuntimeError(f"{key}: the dignities or mansions are no longer refused in a sidereal zodiac")
    if data["j2000"] != ["sidereal_with_j2000_frame_not_supported"]:
        raise RuntimeError(f"the sidereal J2000 request is refused for {data['j2000']}")
    years = [data["years"][year] for year in YEARS]
    if years != sorted(years):
        raise RuntimeError("the Fagan–Bradley ayanamsa no longer grows from date to date")


def _sign(longitude: float) -> str:
    return SIGNS[int(longitude // 30) % 12]


def _rows(data: dict) -> str:
    out = []
    for key, name in (("tropical", "回歸黃道"),) + tuple((k, f"恆星：{n}") for k, n in AYANAMSAS):
        chart = data[key]
        ayanamsa = "—" if chart["ayanamsa"] is None else degree_minute(chart["ayanamsa"])
        first = _sign((chart["asc"] // 30) * 30)
        out.append(
            f'          <tr><th scope="row">{name}</th><td class="n">{ayanamsa}</td>'
            f'<td class="n">{zodiacal_minutes(chart["sun"])}</td><td class="n">{zodiacal_minutes(chart["moon"])}</td>'
            f'<td class="n">{zodiacal_minutes(chart["asc"])}</td><td>{first}</td></tr>')
    return "\n".join(out)


def _years(data: dict) -> str:
    return "\n".join(f'          <tr><th scope="row">{year} 年 1 月 1 日</th><td class="n">{degree_minute(data["years"][year])}</td></tr>'
                     for year in YEARS)


def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    _check(data)
    values = [data[key]["ayanamsa"] for key, _ in AYANAMSAS]
    spread = max(values) - min(values)
    century = data["years"][2000] - data["years"][1900]
    fb = data["fagan_bradley"]
    tropical = data["tropical"]
    in_orb = sum(1 for _, targets in tropical["degree"].values() if targets)
    # Every body but Saturn moves back one sign, so exactly the pairs with Saturn change configuration.
    changed = {pair for pair, config in fb["whole_sign"].items() if tropical["whole_sign"][pair] != config}
    stayed = [key for key, lon in tropical["bodies"].items() if int(lon // 30) == int(fb["bodies"][key] // 30)]
    if stayed != ["saturn"] or changed != {pair for pair in fb["whole_sign"] if "saturn" in pair}:
        raise RuntimeError(f"the example no longer keeps only Saturn in its sign, changing every pair with it: {stayed}")
    quoted = [
        f"扣掉 {degree_minute(fb['ayanamsa'])}",
        f"太陽從{zodiacal_minutes(tropical['sun'])}變成{zodiacal_minutes(fb['sun'])}",
        f"上升點從{zodiacal_minutes(tropical['asc'])}變成{zodiacal_minutes(fb['asc'])}",
        f"四種之間最多相差約 {spread:.1f}°",
        f"1900 到 2000 年增加了約 {century:.2f}°",
        f"{tropical['evaluated']} 組配對",
        f"其中 {in_orb} 組在容許度內",
        f"有 {len(changed)} 組的整宮相位變了",
        f"土星從{zodiacal_minutes(tropical['bodies']['saturn'])}變成{zodiacal_minutes(fb['bodies']['saturn'])}",
    ]
    return {"zodiacs": _rows(data), "years": _years(data)}, quoted
