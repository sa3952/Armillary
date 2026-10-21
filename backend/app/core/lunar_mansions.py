"""Lunar mansions (Arabic manāzil al-qamar): which of 28 equal parts of the
zodiac the Moon is in.  The definition, the points placed, the names and how the
mansions differ from the Chinese xiu are stated in ``METHOD_SOURCE_ENTRIES`` below.

Membership is decided exactly: the float longitude is read as the rational it is
(``Fraction``), so a longitude on a boundary belongs to the mansion that starts
there and no rounding moves it across.  A Moon within ``BOUNDARY_FLAG_DEGREES``
of either edge is flagged: at that distance the medieval rounding of the width
and a birth time a few minutes off can each change the mansion.

For a birth time that is not exact the Moon moves through part of a mansion or
more (about 0.5° an hour, 12–15° a civil day), so the module also lists every
mansion the Moon is in during the stated hour or civil day.  The Moon's apparent
longitude only increases (also topocentric: the parallax rate stays well below the
orbital rate), so the Moon's longitudes at the ends of each stretch bound it;
this is an enumeration between two computed positions, not a sample.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Final

from .formatting import dms_text, sign_position
from .method_status import method_head
from .module_state import (
    PRODUCT_FORMULA_SOURCE,
    STATE_FIELDS,
    computed_receipt,
    frame_table_refusal,
)
from .source_reading import TRANSLATION_READ, cited
from .trace import Trace

METHOD: Final = "equal_28_mansions_from_tropical_0_aries_v1"
SOURCE_REF: Final = "lunar_mansions"
MANSION_COUNT: Final = 28
_FULL_CIRCLE: Final = Fraction(360)
_WIDTH: Final = _FULL_CIRCLE / MANSION_COUNT
MANSION_WIDTH_DEGREES: Final = float(_WIDTH)
ZERO_POINT: Final = "tropical_0_aries_of_date"
# One arcminute: the gap between the exact width and the medieval 12°51′26″
# grows to 8″ by the last mansion, and the Moon covers 1′ in about two minutes.
BOUNDARY_FLAG_DEGREES: Final = 1.0 / 60.0
INTERVALS: Final = ("stated_civil_hour", "civil_day")
PLACED_BODIES: Final = ("moon",)

# (Arabic script, transliteration), al-Biruni's names; original only, no translation.
MANSIONS: Final = (
    ("الشرطان", "al-Sharaṭān"),
    ("البطين", "al-Buṭayn"),
    ("الثريا", "al-Thurayyā"),
    ("الدبران", "al-Dabarān"),
    ("الهقعة", "al-Haqʿa"),
    ("الهنعة", "al-Hanʿa"),
    ("الذراع", "al-Dhirāʿ"),
    ("النثرة", "al-Nathra"),
    ("الطرف", "al-Ṭarf"),
    ("الجبهة", "al-Jabha"),
    ("الزبرة", "al-Zubra"),
    ("الصرفة", "al-Ṣarfa"),
    ("العواء", "al-ʿAwwāʾ"),
    ("السماك", "al-Simāk"),
    ("الغفر", "al-Ghafr"),
    ("الزبانى", "al-Zubānā"),
    ("الإكليل", "al-Iklīl"),
    ("القلب", "al-Qalb"),
    ("الشولة", "al-Shawla"),
    ("النعائم", "al-Naʿāʾim"),
    ("البلدة", "al-Balda"),
    ("سعد الذابح", "Saʿd al-Dhābiḥ"),
    ("سعد بلع", "Saʿd Bulaʿ"),
    ("سعد السعود", "Saʿd al-Suʿūd"),
    ("سعد الأخبية", "Saʿd al-Akhbiya"),
    ("الفرغ المقدم", "al-Fargh al-Muqaddam"),
    ("الفرغ المؤخر", "al-Fargh al-Muʾakhkhar"),
    ("بطن الحوت", "Baṭn al-Ḥūt"),
)
if len(MANSIONS) != MANSION_COUNT:
    raise RuntimeError("the mansion table must name exactly 28 mansions")

METHOD_SOURCE_ENTRIES: Final = {
    SOURCE_REF: {
        "applies_to": "derived_methods.lunar_mansions",
        "definition": (
            "28 equal mansions of 360°/28 (12°51′25.714″; medieval texts round it to "
            "12°51′26″) on the tropical ecliptic of date, the first starting at 0° Aries; "
            "mansion n is [(n−1)·360°/28, n·360°/28); only the Moon is placed"
        ),
        "sources": [
            cited("Agrippa, De occulta philosophia II.33 (English translation, London 1651)", None,
                  TRANSLATION_READ,
                  "the archive.org scan of the 1651 English translation and its OCR text"),
            cited("al-Biruni, Chronology of Ancient Nations ch. XXI (tr. Sachau 1879, pp. 335-366)",
                  None, TRANSLATION_READ, "a scanned copy of Sachau's translation"),
        ],
        "zero_point_basis": "product_convention",
        "source_note": (
            "Agrippa, De occulta philosophia II.33 (English translation, London 1651): "
            "28 mansions of 12°51′ and almost 26″ each, after Abraham; mansions 1, 8, 15 "
            "and 22 begin at the heads of Aries, Cancer, Libra and Capricorn, but Agrippa "
            "places them in the zodiac of the eighth sphere. al-Biruni, Chronology of "
            "Ancient Nations ch. XXI (tr. Sachau 1879, pp. 335-366): the Arabs divided "
            "the sphere into 28 parts, 2 1/3 to a sign, beginning with al-Sharatan because "
            "its stars stood in the first part of Aries in their time, and the stars have "
            "since moved. Counting from the tropical vernal point of date is the product's "
            "convention for these equal parts. Picatrix, Ibn Abi al-Rijal and al-Biruni's "
            "Book of Instruction were not read. No page numbers for Agrippa"
        ),
        "names_note": (
            "Arabic names as al-Biruni lists them (Sachau's translation, read in a scanned "
            "text); the Arabic script and the forms al-Fargh al-Muqaddam and al-Fargh "
            "al-Mu'akhkhar were not checked against a printed source; no. 1 is also called "
            "al-Nath. The names are given in the original only (Arabic script and "
            "transliteration), with no translated name"
        ),
        "points_note": (
            "every source read gives a mansion on a chart only to the Moon; none "
            "places the ascendant or another planet in them"
        ),
        "not_the_chinese_xiu": (
            "the 二十八宿 of ancient China are unequal lodges measured in right ascension "
            "from determinative stars; this module does not compute them and gives "
            "no Chinese lodge name"
        ),
        "boundary_rule": (
            "membership by exact rational comparison of the float longitude; a Moon "
            "within 1′ of an edge is flagged (near_boundary)"
        ),
        "interval_rule": (
            "for a non-exact birth time, every mansion the Moon is in between its "
            "longitudes at the ends of the stated hour or civil day; the Moon's "
            "apparent longitude only increases"
        ),
        "interval_vocabulary": list(INTERVALS),
    },
}


def _mansion_index(longitude: float) -> int:
    """0-based mansion of a longitude, exact on the half-open intervals."""

    point = Fraction(longitude) % _FULL_CIRCLE
    return int(point // _WIDTH)


def mansion_start_degrees(index: int) -> float:
    """Start longitude of the 0-based mansion, from the exact width."""

    return float(_WIDTH * index) % 360.0


def _name(index: int) -> dict:
    arabic, transliteration = MANSIONS[index]
    return {
        "number": index + 1,
        "arabic": arabic,
        "transliteration": transliteration,
    }


def _mansion(index: int) -> dict:
    start = mansion_start_degrees(index)
    end = mansion_start_degrees(index + 1)
    return {
        **_name(index),
        "start_degrees": start,
        "end_degrees": end,
        "boundary_sign_positions": {
            "start": sign_position(start),
            "end": sign_position(end),
        },
    }


def _placement(body: dict) -> dict:
    longitude = body["longitude"]
    index = _mansion_index(longitude)
    into = Fraction(longitude) % _FULL_CIRCLE - _WIDTH * index
    distance = min(into, _WIDTH - into)
    return {
        "key": body["key"],
        "name": body["name"],
        "longitude": longitude,
        "mansion": _mansion(index),
        "degrees_into_mansion": float(into),
        "degrees_into_mansion_text": dms_text(float(into)),
        "distance_to_nearest_boundary_degrees": float(distance),
        "near_boundary": distance <= Fraction(BOUNDARY_FLAG_DEGREES),
    }


def _interval_mansions(stretches: list[tuple[float, float]]) -> list[int]:
    """Every 0-based mansion the Moon is in over half-open stretches.

    Each stretch is (longitude at its start, longitude at its end); the end
    instant is excluded, so a Moon reaching a boundary exactly there does not
    enter the next mansion.
    """

    indices: list[int] = []
    for start, end in stretches:
        advance = (Fraction(end) - Fraction(start)) % _FULL_CIRCLE
        first = Fraction(start) % _FULL_CIRCLE
        # Mansion starts in (first, first + advance); a start equal to the end is
        # the excluded end instant.
        index = int(first // _WIDTH)
        steps = [index]
        boundary = _WIDTH * (index + 1)
        while boundary < first + advance:
            index += 1
            steps.append(index % MANSION_COUNT)
            boundary += _WIDTH
        for step in steps:
            if step not in indices:
                indices.append(step)
    return indices


def compute_lunar_mansions(
    bodies: list[dict],
    trace: Trace,
    *,
    time_basis: str,
    interval: str | None = None,
    interval_moon_longitudes: list[tuple[float, float]] | None = None,
) -> dict:
    """The Moon's mansion at the chart instant, and over a non-exact birth time.

    ``interval_moon_longitudes`` holds the Moon's longitude at the start and the
    (excluded) end of each stretch of the stated hour or civil day; it is None
    for an exact birth time.
    """

    by_key = {body["key"]: body for body in bodies}
    placements = [_placement(by_key[key]) for key in PLACED_BODIES]
    birth_time_interval = None
    interval_numbers: list[int] | None = None
    if interval is not None:
        if interval not in INTERVALS or not interval_moon_longitudes:
            raise ValueError("a non-exact birth time needs its interval and the Moon at its ends")
        indices = _interval_mansions(interval_moon_longitudes)
        interval_numbers = [index + 1 for index in indices]
        birth_time_interval = {
            "interval": interval,
            "moon_longitudes": [list(pair) for pair in interval_moon_longitudes],
            "mansions": [_name(index) for index in indices],
            "crosses_mansion_boundary": len(indices) > 1,
        }
    moon = placements[0]
    trace.add(
        "月宿",
        formula=(
            "月宿編號＝⌊月亮黃經 ÷ (360°/28)⌋＋1；第 1 宿自回歸黃道牡羊 0° 起，"
            "每宿 360°/28＝12°51′25.714″"
        ),
        inputs={"moon_longitude": moon["longitude"], "interval": interval},
        result={
            "mansion": moon["mansion"]["number"],
            "degrees_into_mansion": moon["degrees_into_mansion"],
            "near_boundary": moon["near_boundary"],
            "interval_mansions": interval_numbers,
        },
        note="只計算月亮所在的月宿與它在宿內的位置，不解讀。",
    )
    return {
        **method_head(METHOD, "lunar_mansions", source_ref=SOURCE_REF),
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "division": {
            "count": MANSION_COUNT,
            "width_degrees": MANSION_WIDTH_DEGREES,
            "width_text": dms_text(MANSION_WIDTH_DEGREES),
            "zero_point": ZERO_POINT,
        },
        "boundary_flag_degrees": BOUNDARY_FLAG_DEGREES,
        "time_basis": time_basis,
        "placements": placements,
        "birth_time_interval": birth_time_interval,
    }


def lunar_mansions_not_applicable(state: dict, trace: Trace) -> dict:
    refusal = frame_table_refusal(
        state, trace, "月宿",
        note=(
            "月宿從當日真春分點（回歸黃道牡羊 0°）起算；恆星黃道、J2000、不含章動或"
            "非地心觀測點會移動起點或沒有月亮的「宿」可言，參考框架相容表判定不適用。"
        ),
    )
    return lunar_mansions_unavailable(refusal)


def lunar_mansions_unavailable(receipt: dict) -> dict:
    """The module with no result, under the six state fields given.

    The frame table's refusal (not executed) and a Moon position the ephemeris
    refused at an end of the birth-time interval (executed) both end here.
    """

    return {
        **method_head(METHOD, "lunar_mansions", source_ref=SOURCE_REF),
        **{field: receipt[field] for field in STATE_FIELDS},
        "division": None,
        "boundary_flag_degrees": None,
        "time_basis": None,
        "placements": [],
        "birth_time_interval": None,
    }
