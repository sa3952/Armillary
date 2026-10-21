"""〈日盤還是夜盤怎麼判斷〉: table 1 (the minutes around one sunrise, each as
the product answers it: the Sun's true altitude, the sect, whether the two
named sunrise definitions disagree, and the two Lots of Fortune) and the
numbers the prose quotes.

Synthetic instants only: 1990-05-15 Taipei, whole minutes from 05:00 to 05:30
local clock time, whole signs, tropical, Lots requested (the product judges the
sect when the Lots are asked for).  Each row is one request to the real
application in process; the module reads the product's `derived_methods.sect`
and `derived_methods.lots` and stops if the morning no longer runs night,
inside the band, day.
"""
from __future__ import annotations

import functools

from ._common import product_charts
from ._demo import DEMO, zodiacal_minutes


FRAGMENT = "blog-day-or-night-chart"
HOUR = 5
MINUTES = range(0, 31)
OPTIONS = {"house_system": "W", "include_houses": True, "include_lots": True}
def _request(minute: int) -> dict:
    return {**DEMO, "datetime": {**DEMO["datetime"], "hour": HOUR, "minute": minute}, "options": OPTIONS}


@functools.lru_cache(maxsize=1)
def answers() -> list[dict]:
    rows = []
    with product_charts() as post:
        for minute in MINUTES:
            answer = post(_request(minute))
            sect, lots = answer["derived_methods"]["sect"], answer["derived_methods"]["lots"]
            rows.append({
                "minute": minute,
                "altitude": sect["sun_altitude_used"],
                "is_day": sect["is_day"],
                "status": sect["sect_status"],
                "band": sect["in_near_horizon_band"],
                "disagree": sect["named_boundary_disagreement"],
                "band_degrees": sect["near_horizon_band_half_width_degrees"],
                "basis": lots["formula_basis"],
                "applied": lots["sect_applied"],
                "primary": lots["fortune"],
                "other": lots["by_sect"]["night" if lots["sect_applied"] == "day" else "day"]["fortune"],
            })
    return rows


def _arcmin(altitude: float) -> str:
    """「−12.3′」: the true altitude in arcminutes, one decimal, signed."""
    value = round(altitude * 60, 1)
    return ("+" if value > 0 else "−" if value < 0 else "") + f"{abs(value):.1f}′"


def _shape(rows: list[dict]) -> dict:
    """The morning as the article tells it: night, then the band (first its
    night half, where the named definitions disagree, then its day half), then
    day; the Lots listed both ways exactly inside the band."""
    statuses = [row["status"] for row in rows]
    first_band = statuses.index("boundary_both_shown")
    last_band = len(statuses) - 1 - statuses[::-1].index("boundary_both_shown")
    first_day = next(i for i, row in enumerate(rows) if row["is_day"])
    if not (0 < first_band < first_day <= last_band < len(rows) - 1):
        raise RuntimeError(f"the morning no longer runs night, band, day: {statuses}")
    if set(statuses[:first_band]) != {"night"} or set(statuses[last_band + 1:]) != {"day"}:
        raise RuntimeError(f"the morning no longer runs night, band, day: {statuses}")
    if set(statuses[first_band:last_band + 1]) != {"boundary_both_shown"}:
        raise RuntimeError("the band is not one run of minutes")
    for row in rows:
        inside = row["status"] == "boundary_both_shown"
        if row["basis"] != ("both_formulas_boundary" if inside else f"{row['applied']}_formula"):
            raise RuntimeError(f"05:{row['minute']:02d}: the Lots' basis {row['basis']} does not follow the sect")
        if row["disagree"] != (-row["band_degrees"] < row["altitude"] <= 0):
            raise RuntimeError(f"05:{row['minute']:02d}: the named-boundary flag does not match the altitude")
        if row["band"] != inside:
            raise RuntimeError(f"05:{row['minute']:02d}: the band flag and the status disagree")
    return {"first_band": first_band, "last_band": last_band, "first_day": first_day}


def _clock(row: dict) -> str:
    return f"{HOUR:02d}:{row['minute']:02d}"


def _table(rows: list[dict], shape: dict) -> str:
    out = []
    for row in rows[shape["first_band"] - 1:shape["last_band"] + 2]:
        inside = row["status"] == "boundary_both_shown"
        sect = "日盤" if row["is_day"] else "夜盤"
        status = f"{sect}（近地平，兩套並列）" if inside else sect
        other = zodiacal_minutes(row["other"]) if inside else "—"
        out.append(
            f'          <tr><th scope="row">{_clock(row)}</th><td class="n">{_arcmin(row["altitude"])}</td>'
            f"<td>{status}</td><td>{'是' if row['disagree'] else '否'}</td>"
            f'<td class="n">{zodiacal_minutes(row["primary"])}</td><td class="n">{other}</td></tr>')
    return "\n".join(out)


def build() -> tuple[dict[str, str], list[str]]:
    rows = answers()
    shape = _shape(rows)
    first, last, day = rows[shape["first_band"]], rows[shape["last_band"]], rows[shape["first_day"]]
    disagree = [row for row in rows if row["disagree"]]
    band_minutes = shape["last_band"] - shape["first_band"] + 1
    rate = (rows[shape["last_band"] + 1]["altitude"] - rows[shape["first_band"] - 1]["altitude"]) / (
        shape["last_band"] - shape["first_band"] + 2)
    quoted = [
        f"從 {_clock(first)} 到 {_clock(last)} 共 {band_minutes} 個整分鐘",
        f"{_clock(day)} 起判為日盤",
        f"{_clock(disagree[0])} 到 {_clock(disagree[-1])} 這 {len(disagree)} 分鐘",
        f"每分鐘約升高 {rate * 60:.0f} 角分",
        f"上下 {round(first['band_degrees'] * 60)} 角分",
    ]
    return {"morning": _table(rows, shape)}, quoted
