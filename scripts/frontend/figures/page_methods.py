"""The methods page's index of named choices: how many the request schema
offers for each, and its default (or that it has none); the lunar mansion
table, from the backend table that names the mansions; and the limits of the
three combustion traditions, from the backend profile table."""
from __future__ import annotations

from html import escape

from . import _site
from ._common import SIGNS, backend_on_path


FRAGMENT = "methods"
# (schema field, the page's name for it, the page's name for each default it may have)
CHOICES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("bounds_profile", "界", {}),
    ("decan_profile", "面／旬", {}),
    ("triplicity_profile", "三分性", {}),
    ("aspect_orb_profile", "容許度表", {"lilly_1647_experience_v1": "Lilly 1647"}),
    ("house_system", "宮位制", {"W": "整宮"}),
    ("aspect_set_profile", "相位集合", {"ptolemaic_major_v1": "合相＋四種傳統相位"}),
    ("partile_profile", "同度判準", {"same_degree_number_v1": "同度數編號"}),
    ("ayanamsa", "AYANAMSA", {"fagan_bradley": "Fagan–Bradley"}),
)


def _mansion_rows() -> tuple[str, str]:
    with backend_on_path():
        from app.core import lunar_mansions
        from app.core.formatting import dms_text, sign_position

        rows = []
        for index, (arabic, transliteration) in enumerate(lunar_mansions.MANSIONS):
            position = sign_position(lunar_mansions.mansion_start_degrees(index))
            assert position is not None
            sign, dms = position[0], position[1]
            rows.append(
                f'          <tr><td class="mono">{index + 1}</td>'
                f'<td class="mono">{SIGNS[sign]} {dms}</td>'
                f'<td lang="ar" dir="rtl">{escape(arabic)}</td>'
                f'<td lang="ar-Latn">{escape(transliteration)}</td></tr>'
            )
        width = dms_text(lunar_mansions.MANSION_WIDTH_DEGREES)
    return "\n".join(rows), width


_SOLAR_BODIES = {"moon": "月亮", "mercury": "水星", "venus": "金星", "mars": "火星", "jupiter": "木星", "saturn": "土星"}
_SOLAR_BANDS = (("cazimi", "日輪內"), ("combust", "焦傷"), ("under_beams", "在光束下"))
_SOLAR_SIDES = {"morning": "西側（晨星）", "evening": "東側（昏星）"}
_SOLAR_MOTIONS = {"direct": "順行", "retrograde": "逆行"}


def solar_limit_text(limit: dict) -> str:
    """「≤ 17′」「< 16′」「≤ 8°30′」; a limit split by the planet's own motion lists both."""
    if "direct" in limit:
        return "；".join(f"{_SOLAR_MOTIONS[m]} {solar_limit_text(limit[m])}" for m in ("direct", "retrograde"))
    minutes = round(limit["degrees"] * 60)
    whole, rest = divmod(minutes, 60)
    text = f"{whole}°{rest:02d}′" if whole and rest else (f"{whole}°" if whole else f"{rest}′")
    return f"{'≤' if limit['inclusive'] else '<'} {text}"


def _solar_cell(per_side: dict) -> str:
    return "；".join(
        f"{label} {solar_limit_text(per_side[band])}" for band, label in _SOLAR_BANDS if per_side[band] is not None
    )


def solar_phase_limit_rows() -> str:
    """The three traditions' limits per body and side, one table row each; the
    methods page and the combustion article print the same rows."""
    with backend_on_path():
        from app.core import solar_phase

        tables = [solar_phase.limits_table(profile) for profile in solar_phase.PROFILE_IDS]
    rows = []
    for key, name in _SOLAR_BODIES.items():
        cells = {side: [_solar_cell(table[key][side]) for table in tables] for side in _SOLAR_SIDES}
        sides = [("兩側相同", cells["morning"])] if cells["morning"] == cells["evening"] else [
            (_SOLAR_SIDES[side], cells[side]) for side in _SOLAR_SIDES
        ]
        for side_label, row in sides:
            rows.append(
                f"          <tr><th scope=\"row\">{name}</th><td>{side_label}</td>"
                + "".join(f"<td>{escape(cell)}</td>" for cell in row)
                + "</tr>"
            )
    return "\n".join(rows)


_PLANETS = {"sun": "太陽", "moon": "月亮", "mercury": "水星", "venus": "金星",
            "mars": "火星", "jupiter": "木星", "saturn": "土星"}


def _dignity_tables():
    with backend_on_path():
        from app.core import dignity_tables
    return dignity_tables


def dignity_sign_rows() -> str:
    """七政的廟、旺、陷、弱：the product's own domicile/exaltation table and the
    detriment/fall signs it derives from it, one row per planet."""
    tables = _dignity_tables()
    name = lambda sign: SIGNS[tables.SIGNS.index(sign)]  # noqa: E731
    rows = []
    for key, planet in _PLANETS.items():
        cells = (
            "、".join(name(sign) for sign in tables.DOMICILE_SIGNS[key]),
            name(tables.EXALTATION_SIGNS[key]),
            "、".join(name(sign) for sign in tables.DETRIMENT_SIGNS[key]),
            name(tables.FALL_SIGNS[key]),
        )
        rows.append(f'          <tr><th scope="row">{planet}</th>' + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>")
    return "\n".join(rows)


# 九分部的示意：本站不算九分部（方法頁 §07.14），這裡只把那一段寫的規則與 Bonatti 的例子畫成一條。
# 規則等於把整個黃經乘以 9：星座 s 的第 i 份（從 0 起）落在第 (9s + i) mod 12 個星座。
NOVENARIA_EXAMPLE = ("taurus", 21)          # Bonatti：金牛 21° 落在第七份，巨蟹，月亮
NOVENARIA_CHECKS = (("taurus", 21, "cancer", "moon"), ("aquarius", 18, "pisces", "jupiter"))  # 段落裡的兩個例子


def _novenaria_part(tables, sign: str, degree: float) -> tuple[int, str]:
    part = int(degree * 9 // 30)
    return part, tables.SIGNS[(tables.SIGNS.index(sign) * 9 + part) % 12]


def _ruler(tables, sign: str) -> str:
    (planet,) = [key for key, signs in tables.DOMICILE_SIGNS.items() if sign in signs]
    return planet


def novenaria_strip() -> str:
    tables = _dignity_tables()
    for sign, degree, expected, ruler in NOVENARIA_CHECKS:
        _part, found = _novenaria_part(tables, sign, degree)
        if (found, _ruler(tables, found)) != (expected, ruler):
            raise RuntimeError(f"novenaria of {sign} {degree}° is {found}, the methods page says {expected}")
    sign, degree = NOVENARIA_EXAMPLE
    example, _found = _novenaria_part(tables, sign, degree)
    items = []
    for part in range(9):
        start, end = part * 200, (part + 1) * 200  # arc-minutes: each part is 3°20′
        low, high = (f"{value // 60}°{value % 60:02d}′".replace("°00′", "°") for value in (start, end))
        span = f"<span>{low}</span><span>–{high}</span>"  # 窄格裡在「–」前換行
        target = tables.SIGNS[(tables.SIGNS.index(sign) * 9 + part) % 12]
        current = ' class="is-example" aria-current="true"' if part == example else ""
        items.append(
            f'        <li{current}><span class="nv-n">第 {part + 1} 份</span><span class="nv-span">{span}</span>'
            f'<b class="nv-sign">{SIGNS[tables.SIGNS.index(target)]}</b>'
            f'<span class="nv-ruler">{_PLANETS[_ruler(tables, target)]}</span></li>'
        )
    return "\n".join(items)


# The place the methods page uses to show what the sidereal-time step does to the angles.
TAIPEI_EXAMPLE = (25.033, 121.5654)


def _signed(value: float, places: int) -> str:
    return f"{'−' if value < 0 else '+'}{abs(value):.{places}f}"


def _angle_steps(swe, jd: float, step: float) -> tuple[float, float]:
    """What a sidereal-time step alone does to the Taipei ascendant and MC (arcsec)."""
    obliquity = swe.calc_ut(jd, swe.ECL_NUT)[0][0]
    armc = swe.sidtime(jd - 1e-7) * 15 + TAIPEI_EXAMPLE[1]
    before = swe.houses_armc(armc, TAIPEI_EXAMPLE[0], obliquity, b"W")[1]
    after = swe.houses_armc(armc + step * 15 / 3600, TAIPEI_EXAMPLE[0], obliquity, b"W")[1]
    ascendant, midheaven = ((after[i] - before[i] + 180) % 360 - 180 for i in (0, 1))
    return ascendant * 3600, midheaven * 3600


def sidereal_switch_sentences() -> list[str]:
    """The sidereal-time model's two switch dates and the measured step at each
    (the receipt's constants), with what the step does to the angles in Taipei
    at that instant: the houses recomputed from an ARMC moved by the step alone,
    so the normal rotation is not counted.  Where the product joins Swiss's step
    (2050), the sentence also gives Swiss's own step; then Swiss's long-term
    drift by the end of the range and the JPL Horizons residuals of both."""
    with backend_on_path():
        import swisseph as swe

        from app import ephemeris
        from app.core.time_utils import SIDEREAL_SWITCH_POINTS, sidereal_time_hours

        ephemeris.init_ephemeris()
        sentences = []
        for point in SIDEREAL_SWITCH_POINTS:
            step = float(point["measured_step_seconds"])  # type: ignore[arg-type]
            swiss = float(point["swiss_step_seconds"])  # type: ignore[arg-type]
            jd = float(point["jd_ut"])  # type: ignore[arg-type]
            ascendant, midheaven = _angle_steps(swe, jd, swiss)
            effect = (
                f"約 {_signed(swiss * 15, 1)}″，以臺北為例上升點多跳 {_signed(ascendant, 1)}″、"
                f"天頂 {_signed(midheaven, 1)}″）"
            )
            if step == swiss:
                sentences.append(f"{point['date']} 跳 {_signed(step, 4)} 秒（{effect}")
            else:
                sentences.append(
                    f"{point['date']} 跳 {_signed(step, 4)} 秒（Swiss 原本在這天跳 {_signed(swiss, 4)} 秒，{effect}"
                )
        end = swe.julday(2399, 12, 31, 0.0)
        drift = (swe.sidtime(end) - sidereal_time_hours(end, 0.0)[0]) * 3600
        sentences.append(f"到 2399 年底差 {_signed(drift, 2)} 秒（換成角度約 {_signed(drift * 15, 1)}″）")
        return sentences


def build() -> tuple[dict[str, str], list[str]]:
    mansion_rows, mansion_width = _mansion_rows()
    quoted = [f"每宿 360°÷28＝{mansion_width}", *sidereal_switch_sentences()]
    for field, label, names in CHOICES:
        count, default = _site.count(field), _site.default(field)
        if default is None:
            quoted.append(f'<div class="sl none"><b>{count}</b><span>{label}</span><i>無預設</i></div>')
        else:
            quoted.append(f'<div class="sl"><b>{count}</b><span>{label}</span><i>預設　{names[default]}</i></div>')
    return {
        "lunar-mansions": mansion_rows, "solar-phase-limits": solar_phase_limit_rows(),
        "dignity-signs": dignity_sign_rows(), "novenaria": novenaria_strip(),
    }, quoted
