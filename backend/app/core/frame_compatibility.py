"""Method x reference-frame compatibility: the one table every consumer reads.

Sidereal zodiac, the J2000 ecliptic and nutation-off are output reference-frame
choices (``ComputationContext.horizontal_source_flags``).  Several methods are
defined on the ecliptic and equinox of date: the antiscia mirror axis is the
solstitial axis of date; whole-sign bins, VOC sign exits and the Lots operands
read longitudes against it (the ascendant comes from ``swe.houses_ex``, which
is always the true equator and equinox of date); declination parallels read the
equator of date.  Computed in another frame each still returns a plausible
number that belongs to no method.

This module is the only place that decides, for a request's
(center, zodiac, ecliptic_frame, nutation), whether a method applies and which
closed-set reason code it carries when it does not.  Consumers call
``method_frame_state``; none of them tests a frame axis itself.  No coordinate
conversion is offered: an inapplicable method fails closed instead of being
recomputed in a converted frame.

Sidereal of date stays applicable except for the tropical classical tables:
the method research notes find the antiscia ``2 x ayanamsa`` handling correct and
the sidereal dignity refusal right.  With nutation off, sidereal longitudes and
cusps are the nutation-on numbers, so only antiscia and declination parallels,
which still read an equinox or equator the flag selects, are refused.  Sidereal combined with J2000 is refused at
the request boundary (``request_frame_refusal``): in that cell the ayanamsa
receipt differed from the offset actually subtracted (3.25e-3 deg for bodies,
0.13 deg for the true node, measured).
"""

from __future__ import annotations

from typing import Any

FRAME_TABLE_VERSION = "method_frame_compatibility_v1"
AUTHORIZED_METHOD_FRAME = "ecliptic_and_equinox_of_date_nutation_on"
# Kept short: the response budget is shared.  The long form is the module
# docstring and methods page section 07.9.
FRAME_TABLE_PROVENANCE = (
    "Method research notes (not independently verified); product method "
    "decision: method basis is of date, nutation on, applied to every "
    "method here; no frame conversion."
)

EARTH_OBSERVER_CENTERS = frozenset({"geocentric", "topocentric"})

_EARTH_CENTRE = ("center", EARTH_OBSERVER_CENTERS)
_TROPICAL = ("zodiac", frozenset({"tropical"}))
_OF_DATE = ("ecliptic_frame", frozenset({"of_date"}))
_NUTATION_ON = ("nutation", frozenset({True}))
# A sidereal longitude does not depend on the nutation flag.  Swiss
# subtracts the ayanamsa of the same equinox it measured from (true with
# nutation, mean without), so the nutation cancels; the cusps are Swiss's
# native sidereal division, which ignores FLG_NONUT too.
# Measured: body longitudes, cusps, ASC and MC bit-identical with
# nutation on and off (4 ayanamsas x 4 epochs, 1900-2399).  A method that reads
# only those numbers therefore runs in the authorized frame either way.
# Antiscia (mirror axis = the solstitial axis the nutation flag selects) and
# declination parallels (equator of date) still change with the flag and keep
# ``_NUTATION_ON``.
_NUTATION_ON_OR_SIDEREAL = (_NUTATION_ON, ("zodiac", frozenset({"sidereal"})))

NON_EARTH_OBSERVER_CENTER = "non_earth_observer_center"
ANGLE_FRAME_INCOMPATIBLE = "angle_frame_incompatible_with_body_longitudes"
EARTH_OBSERVER_PHENOMENA_NOT_APPLICABLE = (
    "earth_observer_phenomena_not_applicable_for_center"
)

# How many failing requirements a method reports.  Planet-in-house has always
# listed every mismatch; every other receipt carries one reason code.
REPORT_FIRST = "first_failing_requirement"
REPORT_ALL = "every_failing_requirement"

# Each row: ordered (requirement, reason_code) pairs.  A requirement is
# (request axis, accepted values), or a tuple of such pairs of which any one
# suffices.  ``parent`` makes a sub-method inherit its
# parent's refusal, so a refused module never also reports a child reason.
METHOD_FRAME_TABLE: dict[str, dict[str, Any]] = {
    # Phase angle, illuminated fraction, elongation, apparent diameter and
    # magnitude are Earth-observer quantities; Swiss pheno_ut ignores the
    # heliocentric/barycentric flags and returns the geocentric values.
    "earth_observer_phenomena": {
        "requirements": (
            (_EARTH_CENTRE, EARTH_OBSERVER_PHENOMENA_NOT_APPLICABLE),
        ),
    },
    "house_division": {
        "requirements": ((_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),),
    },
    "planet_in_house": {
        "report": REPORT_ALL,
        "requirements": (
            (_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),
            (_OF_DATE, "planet_house_frame_mismatch"),
            (_NUTATION_ON_OR_SIDEREAL, "planet_house_nutation_mismatch"),
        ),
    },
    # Aspects, declination parallels and antiscia are relations in the Earth
    # observer's sky (whole-sign configuration, equator, solstitial axis); seen
    # from the Sun or the barycentre the numbers compute but name no method.
    "antiscia": {
        "requirements": (
            (_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),
            (_OF_DATE, "j2000_antiscia_basis_not_authorized"),
            (_NUTATION_ON, "nutation_off_antiscia_basis_not_authorized"),
        ),
    },
    "aspects": {
        "requirements": (
            (_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),
            (_OF_DATE, "j2000_aspects_basis_not_authorized"),
            (_NUTATION_ON_OR_SIDEREAL, "nutation_off_aspects_basis_not_authorized"),
        ),
    },
    "aspect_angle_participation": {
        "parent": "aspects",
        "requirements": (
            (_EARTH_CENTRE, ANGLE_FRAME_INCOMPATIBLE),
            (_OF_DATE, ANGLE_FRAME_INCOMPATIBLE),
            (_NUTATION_ON_OR_SIDEREAL, ANGLE_FRAME_INCOMPATIBLE),
        ),
    },
    "lots": {
        "requirements": (
            (_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),
            (_OF_DATE, "j2000_lots_basis_not_authorized"),
            (_NUTATION_ON_OR_SIDEREAL, "nutation_off_lots_basis_not_authorized"),
        ),
    },
    "void_of_course": {
        "requirements": (
            (_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),
            (_OF_DATE, "j2000_void_of_course_basis_not_authorized"),
            (_NUTATION_ON_OR_SIDEREAL, "nutation_off_void_of_course_basis_not_authorized"),
        ),
    },
    "declination_aspects": {
        "requirements": (
            (_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),
            (_OF_DATE, "j2000_declination_aspects_basis_not_authorized"),
            (
                _NUTATION_ON,
                "nutation_off_declination_aspects_basis_not_authorized",
            ),
        ),
    },
    # Sunrise and sunset belong to an observer on the Earth's surface; a chart
    # seen from the Sun or the barycentre has no day or night to divide.
    "planetary_hours": {
        "requirements": ((_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),),
    },
    "essential_dignities": {
        "requirements": (
            (_EARTH_CENTRE, "non_earth_center_dignity_basis_not_authorized"),
            (_TROPICAL, "sidereal_dignity_basis_not_authorized"),
            (_OF_DATE, "j2000_dignity_basis_not_authorized"),
            (_NUTATION_ON, "nutation_off_dignity_basis_not_authorized"),
        ),
    },
}

FRAME_REASON_CODES = tuple(
    sorted(
        {
            code
            for row in METHOD_FRAME_TABLE.values()
            for _requirement, code in row["requirements"]
        }
    )
)

# Request-level refusal, raised as a 422 by the request schema (refuse rather
# than emit a receipt that is not the offset actually applied).
SIDEREAL_J2000_REFUSAL = "sidereal_with_j2000_frame_not_supported"
REQUEST_FRAME_REFUSAL_CODES = (SIDEREAL_J2000_REFUSAL,)


def request_frame_refusal(mode) -> str | None:
    """Closed reason code when the requested frame combination is refused."""

    if mode.zodiac == "sidereal" and mode.ecliptic_frame == "j2000":
        return SIDEREAL_J2000_REFUSAL
    return None


def _requirement_met(requirement, mode) -> bool:
    alternatives = (
        requirement if isinstance(requirement[0], tuple) else (requirement,)
    )
    return any(getattr(mode, axis) in accepted for axis, accepted in alternatives)


def method_frame_state(method: str, mode) -> dict:
    """Return ``{applicable, reason_code, reason_codes}`` for one method.

    Only the axes the method's row names are read, so a caller holding a partial
    mode (a probe, a unit test) gets the same answer as the web layer.
    """

    row = METHOD_FRAME_TABLE[method]
    parent = row.get("parent")
    if parent is not None:
        parent_state = method_frame_state(parent, mode)
        if not parent_state["applicable"]:
            return parent_state
    failing: list[str] = []
    for requirement, code in row["requirements"]:
        if not _requirement_met(requirement, mode) and code not in failing:
            failing.append(code)
    if row.get("report", REPORT_FIRST) == REPORT_FIRST:
        failing = failing[:1]
    return {
        "applicable": not failing,
        "reason_code": failing[0] if failing else None,
        "reason_codes": failing,
    }


def method_frame_states(mode) -> dict[str, dict]:
    return {method: method_frame_state(method, mode) for method in METHOD_FRAME_TABLE}


def body_longitude_frame_label(mode) -> str:
    """Effective frame of the emitted body longitudes.

    FLG_J2000 longitudes do not change with the nutation flag (measured for the
    Sun, Moon and Mars), and sidereal with J2000 never reaches here.
    """

    if mode.ecliptic_frame == "j2000":
        return "tropical_ecliptic_j2000_mean_equinox"
    equinox = "true" if mode.nutation else "mean"
    return f"{mode.zodiac}_ecliptic_of_date_{equinox}_equinox"


def frame_policy_receipt(mode, states: dict[str, dict]) -> dict:
    """Dossier receipt: which frame the methods require and what was refused."""

    return {
        "version": FRAME_TABLE_VERSION,
        "authorized_method_frame": AUTHORIZED_METHOD_FRAME,
        "body_longitude_frame": body_longitude_frame_label(mode),
        "conversion_offered": False,
        "provenance": FRAME_TABLE_PROVENANCE,
        "not_applicable": {
            method: state["reason_code"]
            for method, state in states.items()
            if not state["applicable"]
        },
    }
