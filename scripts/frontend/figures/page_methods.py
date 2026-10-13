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


def build() -> tuple[dict[str, str], list[str]]:
    mansion_rows, mansion_width = _mansion_rows()
    quoted = [f"每宿 360°÷28＝{mansion_width}"]
    for field, label, names in CHOICES:
        count, default = _site.count(field), _site.default(field)
        if default is None:
            quoted.append(f'<div class="sl none"><b>{count}</b><span>{label}</span><i>無預設</i></div>')
        else:
            quoted.append(f'<div class="sl"><b>{count}</b><span>{label}</span><i>預設　{names[default]}</i></div>')
    return {"lunar-mansions": mansion_rows, "solar-phase-limits": solar_phase_limit_rows()}, quoted
