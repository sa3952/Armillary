"""十二分部（dodecatemoria，twelfth-parts）：本命盤的選用技法。

一個點在星座內的度數，依具名算法放大後，從同一星座的起點往後數出另一個黃經位置；
該位置所在星座的守護行星（廟主）一併列出。只列位置與守護行星，不判定關係、不解讀。

文獻有兩種會改變結果的算法，以具名 profile 平等提供：

- 預設：度數乘以 12，從星座起點往後數（Firmicus《Mathesis》II.13 的規則與例子）。到星座
  為止，它與 Manilius 把每座分成十二段、每段 2°30′、依序配給本座及其後各座的分法相同。
- 另一種：度數乘以 13，從星座起點往後數，也就是乘以 12 之後從該點自己的度數往後數
  （Paulus《導論》（Eisagōgika）ch.22 與 Olympiodorus 的例子）。

兩者讀到哪一層、哪些點有見證，寫在 METHOD_SOURCE_ENTRIES；預設算法已定（method_status 為 decided）。
"""

from __future__ import annotations

import copy
import math
from fractions import Fraction
from typing import Literal, get_args

from .dignity_tables import DOMICILE_SIGNS, SIGNS
from .essential_dignities import ALL_PROFILES
from .formatting import normalize_longitude, zodiac_sign_index
from .method_status import method_head
from .module_state import PRODUCT_FORMULA_SOURCE, computed_receipt, frame_table_refusal
from .source_reading import BIBLIOGRAPHIC_ONLY, ORIGINAL_LANGUAGE_READ, SECONDARY_ONLY, TRANSLATION_READ, cited
from .trace import Trace

DodecatemoriaProfile = Literal[
    "twelvefold_from_sign_start_v1",
    "thirteenfold_from_sign_start_v1",
]
DEFAULT_DODECATEMORIA_PROFILE: DodecatemoriaProfile = "twelvefold_from_sign_start_v1"
# The request may also ask for every rule side by side ("all", the same value
# as the dignity tables').  The listed points then stay the default rule's.
DodecatemoriaProfileOption = Literal[
    "twelvefold_from_sign_start_v1",
    "thirteenfold_from_sign_start_v1",
    "all",
]
PROFILE_IDS: tuple[DodecatemoriaProfile, ...] = get_args(DodecatemoriaProfile)


def computed_profiles(requested: str) -> list[str]:
    """The rules one requested value stands for, in catalogue order."""

    return list(PROFILE_IDS) if requested == ALL_PROFILES else [requested]


def points_profile(requested: str) -> str:
    """The rule the top-level points (and the birth-time samples) use."""

    return DEFAULT_DODECATEMORIA_PROFILE if requested == ALL_PROFILES else requested

# How many degrees each degree inside the sign moves the result, counted from
# the start of the same sign.  Thirteen times from the sign's start is twelve
# times counted on from the point's own degree.
MULTIPLIER_FROM_SIGN_START = {
    "twelvefold_from_sign_start_v1": 12,
    "thirteenfold_from_sign_start_v1": 13,
}
FORMULAS = {
    "twelvefold_from_sign_start_v1": (
        "十二分部黃經＝星座起點＋12×d（超過 360° 減 360°）；d＝這個點在星座內的度數"
    ),
    "thirteenfold_from_sign_start_v1": (
        "十二分部黃經＝星座起點＋13×d＝這個點的黃經＋12×d（超過 360° 減 360°）；"
        "d＝這個點在星座內的度數"
    ),
}

DOMICILE_LORD_BY_SIGN = {
    sign: planet for planet, signs in DOMICILE_SIGNS.items() for sign in signs
}

# Listed points, in order: the seven planets; the ascendant when the chart has
# angles; Fortune and Spirit when computed.  No text read computes the
# midheaven's twelfth-part (Paulus names angles only as signs one may fall in).
POINT_CATEGORIES = ("classical_planet", "angle", "lot")
_ANGLE_POINTS = (("asc", "上升"),)
_LOT_POINTS = (("fortune", "命運點"), ("spirit", "精神點"))
# How far the witness for each listed category was read.  Closed set.
POINT_ATTESTATION = {
    "classical_planet": "firmicus_ii_13_latin_read_paulus_22_via_greenbaum_jones_2017",
    "angle": "ascendant_olympiodorus_20_via_greenbaum_jones_2017_greek_not_read",
    "lot": "olympiodorus_21_chapter_title_only_text_not_read",
}
METHOD_NAME = "dodecatemoria_named_profiles_v1"
SOURCE_REF = "dodecatemoria"


def twelfth_part_longitude(longitude: float, profile: str) -> float:
    """The twelfth-part of one ecliptic longitude under the named profile."""

    sign_index = zodiac_sign_index(longitude)
    in_sign = normalize_longitude(longitude) - 30.0 * sign_index
    multiplier = MULTIPLIER_FROM_SIGN_START[profile]
    result = normalize_longitude(30.0 * sign_index + multiplier * in_sign)
    # The float product can round onto a sign boundary the exact result has not
    # reached (13 x d near 30k/13), or fall just short of one it has; the sign
    # is the exact result's, as for every other point on the half-open signs.
    exact = Fraction(longitude) % 360
    exact_sign_start = exact // 30 * 30
    exact_result = (exact_sign_start + multiplier * (exact - exact_sign_start)) % 360
    exact_sign = int(exact_result // 30)
    float_sign = zodiac_sign_index(result)
    if float_sign == (exact_sign + 1) % 12:
        result = math.nextafter(30.0 * (exact_sign + 1), 0.0)
    elif float_sign != exact_sign:
        result = 30.0 * exact_sign
    return result


def _row(
    key: str,
    name: str,
    category: str,
    longitude: float,
    profile: str,
    other_sect_longitude: float | None = None,
) -> dict:
    """One listed point.  ``other_sect_longitude`` is the Lot under the other
    sect's formula when the Sun is in the near-horizon band, else None."""

    result = twelfth_part_longitude(longitude, profile)
    sign = SIGNS[zodiac_sign_index(result)]
    other_sign = (
        None
        if other_sect_longitude is None
        else SIGNS[zodiac_sign_index(twelfth_part_longitude(other_sect_longitude, profile))]
    )
    differs = None if other_sign is None else other_sign != sign
    return {
        "key": key,
        "name": name,
        "category": category,
        "point_longitude": longitude,
        "longitude": result,
        "sign": sign,
        "domicile_lord": DOMICILE_LORD_BY_SIGN[sign],
        # As the zodiacal-releasing rows do: null outside the band and for
        # every point that does not depend on the sect.
        "sign_differs_under_other_sect": differs,
        "comparison_sign": other_sign if differs else None,
    }


def _other_sect_lots(lots: dict) -> dict | None:
    """The other sect's Lots when the chart shows both formulas, else None."""

    if lots.get("sect_status") != "boundary_both_shown":
        return None
    by_sect = lots.get("by_sect") or {}
    other = by_sect.get("night" if lots.get("sect_applied") == "day" else "day")
    return other if isinstance(other, dict) else None


def _points(
    planets: list[dict], angles: dict | None, lots: dict | None, profile: str
) -> tuple[list[dict], list[str]]:
    rows = [
        _row(body["key"], body["name"], "classical_planet", body["longitude"], profile)
        for body in planets
        if body.get("longitude") is not None
    ]
    not_listed = []
    if angles is not None:
        rows += [
            _row(key, name, "angle", angles[key], profile)
            for key, name in _ANGLE_POINTS
            if angles.get(key) is not None
        ]
    else:
        not_listed.append("angles_not_computed")
    if lots is not None:
        other = _other_sect_lots(lots)
        rows += [
            _row(
                key, name, "lot", lots[key], profile,
                None if other is None else other.get(key),
            )
            for key, name in _LOT_POINTS
            if lots.get(key) is not None
        ]
    else:
        not_listed.append("lots_not_requested_or_not_computed")
    return rows, not_listed


def compute_dodecatemoria(
    *,
    planets: list[dict],
    angles: dict | None,
    lots: dict | None,
    profile: str,
    trace: Trace,
) -> dict:
    """Every listed point's twelfth-part under ``profile`` (or under each rule).

    ``angles``/``lots`` are None when unusable; a missing group is named in
    ``scope.not_listed``.  A rule's ``profile_results`` entry is the same alone
    or under ``"all"``; the top-level points are the ``points_profile`` rule's.
    """

    profile_results = {}
    not_listed: list[str] = []
    for profile_id in computed_profiles(profile):
        rows, not_listed = _points(planets, angles, lots, profile_id)
        trace.add(
            "十二分部",
            formula=FORMULAS[profile_id],
            inputs={"profile": profile_id},
            result={row["key"]: row["longitude"] for row in rows},
        )
        profile_results[profile_id] = {
            "profile": profile_id,
            "formula": FORMULAS[profile_id],
            "points": rows,
        }
    listed = profile_results[points_profile(profile)]
    return {
        **method_head(METHOD_NAME, "dodecatemoria"),
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "source_ref": SOURCE_REF,
        "profile": profile,
        "points_profile": listed["profile"],
        "computed_profiles": list(profile_results),
        "formula": listed["formula"],
        "lord_rule": "domicile_lord_of_the_twelfth_part_sign_traditional_seven",
        "scope": {
            "categories": list(POINT_CATEGORIES),
            "not_listed": not_listed,
            "excluded": ["midheaven", "lunar_nodes", "outer_planets", "fixed_stars"],
            "historical_method_status": dict(POINT_ATTESTATION),
        },
        "semantics": "positions_and_sign_lords_only_no_relationship_verdict",
        # A copy: the response's formatting pass writes into each list once.
        "points": copy.deepcopy(listed["points"]),
        "profile_results": profile_results,
    }


def dodecatemoria_not_applicable(state: dict, trace: Trace, requested: str) -> dict:
    refusal = frame_table_refusal(
        state, trace, "十二分部",
        note="參考框架相容表判定不適用：不換框架重算。",
    )
    return {
        **method_head(METHOD_NAME, "dodecatemoria"),
        **refusal,
        "profile": requested,
        # No points are listed, so no rule's points are the top-level ones.
        "points_profile": None,
        "points": [],
        "computed_profiles": computed_profiles(requested),
        "profile_results": {},
    }



_ROBBINS_I_22_PAGES = (
    "the scanned 1964 reprint of Robbins (Loeb 1940), University of "
    "Toronto copy, Internet Archive manethowithengli00maneuoft, pages n431-n432"
)

METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    SOURCE_REF: {
        "applies_to": "derived_methods.dodecatemoria",
        "profiles": {
            "twelvefold_from_sign_start_v1": (
                "Multiply the degrees and minutes inside the sign by 12 and count the "
                "product on from the start of the same sign, 30 to each sign. The product's "
                "default. At sign level this equals the division "
                "of each sign into twelve parts of 2 deg 30 min given to the sign itself "
                "and the following signs in order."
            ),
            "thirteenfold_from_sign_start_v1": (
                "Multiply the degrees inside the sign by 13 and count on from the start "
                "of the same sign; the same as multiplying by 12 and counting on from "
                "the point's own degree. The product multiplies the full position, "
                "minutes included; the worked examples of Paulus and Olympiodorus use "
                "whole degrees, and Greenbaum and Jones infer that P.Berl. 9825 "
                "multiplied the whole degrees and disregarded the minutes."
            ),
        },
        "default_profile": DEFAULT_DODECATEMORIA_PROFILE,
        "default_basis": (
            "The only text read in its own words that states the rule and works an "
            "example is Firmicus II.13, and it multiplies by 12 from the start of the "
            "sign; the 2 deg 30 min division of Manilius and Ptolemy gives the same sign. "
            "The 13-fold rule is attested by the examples of Paulus and Olympiodorus as "
            "reported by Greenbaum and Jones; both are offered."
        ),
        "lord_rule": (
            "The lord listed is the domicile lord of the twelfth-part's sign in the "
            "traditional seven-planet scheme (the product's domicile table). Later "
            "steps that look at which planets occupy or aspect that sign are not "
            "computed; this product lists positions and lords only."
        ),
        "sources": [
            {
                "citation": (
                    "Firmicus Maternus, Mathesis II.13 (Kroll-Skutsch numbering; "
                    "Holden's translation numbers it II.17)"
                ),
                "rule": (
                    "degrees and minutes of the star times 12, given 30 to each sign "
                    "starting with the sign the star is in"
                ),
                "example": "Sun Aries 5 deg 05 min: 60 + 1 = 61, the first degree of Gemini",
                "profile": "twelvefold_from_sign_start_v1",
                "reading": ORIGINAL_LANGUAGE_READ,
                "read_at": (
                    "Latin text, LacusCurtius (penelope.uchicago.edu); the rule and "
                    "example re-read on p.56 of Kroll-Skutsch 1897 vol. I in the "
                    "archive.org OCR text (matheseoslibrivi01firmuoft)"
                ),
            },
            {
                "citation": "Manilius, Astronomica II.693-748",
                "rule": (
                    "each sign in twelve parts of 2 1/2 degrees, the first to the sign "
                    "itself and the rest to the following signs; for the Moon its degrees "
                    "times 12, 30 to each sign from the Moon's sign; each part halved "
                    "again among the five planets (not computed)"
                ),
                "profile": "twelvefold_from_sign_start_v1",
                "profile_agreement": "sign_level_only",
                "reading": ORIGINAL_LANGUAGE_READ,
                "read_at": "Latin text, The Latin Library; lines 732-734 bracketed as suspect",
                "note": (
                    "Whether the Moon rule counts from the sign's start or the Moon's "
                    "degree is ambiguous in the Latin; Goold's and Housman's readings "
                    "were not checked."
                ),
            },
            {
                "citation": (
                    "Ptolemy, Tetrabiblos I.22 (Robbins, Loeb 1940, Greek p.108, "
                    "English p.109)"
                ),
                "rule": (
                    "describes the twelfth of a sign (2 1/2 degrees) assigned to the "
                    "signs in order, and rejects it as unfounded"
                ),
                "profile_agreement": "sign_level_only",
                "reading": TRANSLATION_READ,
                "read_at": _ROBBINS_I_22_PAGES,
                "manuscript_variants": [
                    cited("Robbins 1940 p.108 n.3 (Greek apparatus) and p.109 n.2",
                          ("one manuscript (N) and Camerarius's printed editions add "
                           "after 'to the signs in order' the words 'beginning from "
                           "the twelfth-part in which the star is' (ἀρχόμενοι ἀπὸ τοῦ "
                           "δωδεκατημορίου καθ᾽ ὅ ἐστιν ὁ ἀστήρ); the other "
                           "manuscripts and Proclus omit them, and so does Robbins's "
                           "text. The added words name where the count starts."),
                          SECONDARY_ONLY,
                          (f"{_ROBBINS_I_22_PAGES}; manuscript N and Camerarius's "
                           "printings were not read"))
                ],
            },
            {
                "citation": "Paulus Alexandrinus, Introduction ch.22",
                "rule": "degrees times 13, added to the start of the sign",
                "example": "Aries 11 deg: 143 deg, Leo 23 deg",
                "profile": "thirteenfold_from_sign_start_v1",
                "reading": SECONDARY_ONLY,
                "read_at": (
                    "Greenbaum and Jones, P.Berl. 9825, ISAW Papers 12 (2017) para. 185; "
                    "the Greek text and Greenbaum's translation not checked"
                ),
            },
            {
                "citation": "Olympiodorus, Commentary on Paulus ch.20 (Boer 1962, 41.12-20)",
                "rule": "the same as Paulus, worked for the ascendant",
                "example": "Ascendant Scorpio 20 deg: 20 x 13 = 260, + 210 = 470, - 360 = 110, Cancer 20 deg",
                "profile": "thirteenfold_from_sign_start_v1",
                "reading": SECONDARY_ONLY,
                "read_at": "Greenbaum and Jones 2017 para. 186; the Greek text not checked",
            },
            {
                "citation": "Olympiodorus, Commentary on Paulus ch.21",
                "rule": "chapter on the Lots and their twelfth-parts",
                "reading": BIBLIOGRAPHIC_ONLY,
                "read_at": "chapter title in a published table of contents only",
            },
            {
                "citation": "Vettius Valens, Anthology I.4",
                "rule": "the Sun's twelfth-part used to find the ascendant",
                "example": "Sun Aquarius 22 deg, twelfth-part in Scorpio (fits the 13-fold rule only)",
                "reading": TRANSLATION_READ,
                "read_at": (
                    "Riley's translation, the PDF of his preliminary edition "
                    "(Vettius_Valens_Riley.pdf), printed p.8 (PDF page 10), between /19K/ and /20K/"
                ),
            },
            {
                "citation": "Porphyry, Introduction ch.39 (Holden 2009)",
                "rule": "the Moon's degrees measured off by 2 1/2 degrees through the following signs",
                "example": "Moon Aries 13 deg, Virgo (both rules agree)",
                "reading": SECONDARY_ONLY,
                "read_at": "reported by secondary summaries; Holden's translation not read",
            },
        ],
        "documentary_evidence": (
            "P.Berl. 9825 (horoscope of 319 CE) gives the twelfth-part signs only. "
            "Greenbaum and Jones 2017 para. 188: the Moon, Saturn, Jupiter (at its "
            "corrected position), Mars and Venus match the 13-fold formula; Mercury, "
            "both nodes and the prenatal full Moon do not, and match the 12-fold "
            "formula, which also fits Saturn, Jupiter and Mars. So only the Moon and "
            "Venus favour the 13-fold rule against the 12-fold one, and three planets "
            "fit both. They leave two explanations open: the 13-fold rule with the "
            "minutes neglected, or the 12-fold rule miscalculated for the Moon and "
            "Venus."
        ),
        "sect_band": (
            "When the Sun is in the near-horizon band and the Lots show both "
            "formulas, each Lot row says whether the other sect's formula gives "
            "another twelfth-part sign (sign_differs_under_other_sect, "
            "comparison_sign), as the zodiacal-releasing rows do; the listed "
            "value follows the product's sect rule."
        ),
        "not_computed": (
            "Manilius's further division of each part among the five planets; the "
            "midheaven (no witness read); judgements of which planets occupy or aspect "
            "the twelfth-part."
        ),
    },
}
