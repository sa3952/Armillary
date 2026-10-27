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
the sidereal dignity refusal right.  Nutation off with sidereal: see
``_NUTATION_ON_OR_SIDEREAL``.  Sidereal combined with J2000 is refused at
the request boundary (``request_frame_refusal``): in that cell the ayanamsa
receipt differed from the offset actually subtracted (3.25e-3 deg for bodies,
0.13 deg for the true node, measured).
"""

from __future__ import annotations

from typing import Any

from .module_state import Applicability

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
# A sidereal longitude does not depend on the nutation flag.  Swiss subtracts
# the ayanamsa of the same equinox it measured from (true with nutation, mean
# without), so the nutation cancels; the cusps are Swiss's native sidereal
# division, which ignores FLG_NONUT too.  Measured: body longitudes, cusps, ASC
# and MC bit-identical with nutation on and off (4 ayanamsas x 4 epochs,
# 1900-2399), so a method reading only those runs in the authorized frame.
# Antiscia (mirror axis = the solstitial axis the nutation flag selects) and
# declination parallels (equator of date) still change with the flag and keep
# ``_NUTATION_ON``.
_NUTATION_ON_OR_SIDEREAL = (_NUTATION_ON, ("zodiac", frozenset({"sidereal"})))

NON_EARTH_OBSERVER_CENTER = "non_earth_observer_center"
EARTH_OBSERVER_PHENOMENA_NOT_APPLICABLE = (
    "earth_observer_phenomena_not_applicable_for_center"
)

# How many failing requirements a method reports.  Planet-in-house has always
# listed every mismatch; every other receipt carries one reason code.
REPORT_FIRST = "first_failing_requirement"
REPORT_ALL = "every_failing_requirement"

# Each row: ordered (requirement, reason_code) pairs.  A requirement is
# (request axis, accepted values), or a tuple of such pairs of which any one
# suffices.


def _of_date_row(
    basis: str,
    nutation: tuple = _NUTATION_ON_OR_SIDEREAL,
    *,
    tropical: bool = False,
    centre_code: str = NON_EARTH_OBSERVER_CENTER,
) -> dict[str, Any]:
    """An Earth-observer method of date: its codes are
    ``sidereal_<basis>_basis_not_authorized`` (tropical tables only),
    ``j2000_<basis>_...`` and ``nutation_off_<basis>_...``."""
    zodiac = ((_TROPICAL, f"sidereal_{basis}_basis_not_authorized"),) if tropical else ()
    return {
        "requirements": (
            (_EARTH_CENTRE, centre_code),
            *zodiac,
            (_OF_DATE, f"j2000_{basis}_basis_not_authorized"),
            (nutation, f"nutation_off_{basis}_basis_not_authorized"),
        ),
    }


_EARTH_CENTRE_ONLY: dict[str, Any] = {"requirements": ((_EARTH_CENTRE, NON_EARTH_OBSERVER_CENTER),)}

METHOD_FRAME_TABLE: dict[str, dict[str, Any]] = {
    # Phase angle, illuminated fraction, elongation, apparent diameter and
    # magnitude are Earth-observer quantities; Swiss pheno_ut ignores the
    # heliocentric/barycentric flags and returns the geocentric values.
    "earth_observer_phenomena": {
        "requirements": ((_EARTH_CENTRE, EARTH_OBSERVER_PHENOMENA_NOT_APPLICABLE),),
    },
    "house_division": _EARTH_CENTRE_ONLY,
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
    "antiscia": _of_date_row("antiscia", _NUTATION_ON),
    "aspects": _of_date_row("aspects"),
    "lots": _of_date_row("lots"),
    "void_of_course": _of_date_row("void_of_course"),
    "declination_aspects": _of_date_row("declination_aspects", _NUTATION_ON),
    # Sunrise and sunset belong to an observer on the Earth's surface; a chart
    # seen from the Sun or the barycentre has no day or night to divide.
    "planetary_hours": _EARTH_CENTRE_ONLY,
    "essential_dignities": _of_date_row(
        "dignity", _NUTATION_ON, tropical=True,
        centre_code="non_earth_center_dignity_basis_not_authorized",
    ),
    # Twelfth-parts read the degree inside the sign of date, as the Lots do; a
    # sidereal longitude is unchanged by the nutation flag, so it stays allowed.
    "dodecatemoria": _of_date_row("dodecatemoria"),
    # Planet and place classifications read the horizon (sect, above or under
    # the earth) and the sign of date, as the Lots do.
    "classical_classifications": _of_date_row("classical_classification"),
    # The mansions start at the vernal point of date: a sidereal zodiac, the
    # J2000 ecliptic or a mean equinox moves the zero point, and a chart seen
    # from the Sun or the barycentre has no Moon's station to name.
    "lunar_mansions": _of_date_row("lunar_mansion", _NUTATION_ON, tropical=True),
    # The distance from the Sun is a difference of two longitudes of date as
    # seen from the Earth; a sidereal zodiac subtracts the same ayanamsa from
    # both, so only the frame and the centre are restricted.
    "solar_phase": _of_date_row("solar_phase"),
    # Swift or slow compares a speed with mean motions the texts give in the
    # tropical zodiac of date; a sidereal, J2000 or mean-equinox speed differs
    # by the precession or nutation rate, so those frames are refused.  The side
    # of the Sun is solar_phase's.
    "motion_states": _of_date_row("motion_states", _NUTATION_ON, tropical=True),
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


# The annual route's request-level frame.  Its year boundary is a solar
# return root, and three frames move that root while still returning a number:
# a topocentric Sun moves it with the place (+38 s Taipei to -289 s Santiago,
# measured), the J2000 ecliptic turns it into the sidereal return (identical to
# 0.0 s), and nutation off moves it by -760 to +81 s over the 18.6-year cycle.
# Every annual technique reads that boundary, so the route refuses them all.
_GEOCENTRE = ("center", frozenset({"geocentric"}))
SOLAR_RETURN_FRAME_REQUIREMENTS = (
    (_GEOCENTRE, "solar_return_requires_geocentric_center"),
    (_OF_DATE, "solar_return_requires_ecliptic_of_date"),
    (_NUTATION_ON, "solar_return_requires_nutation"),
)
SOLAR_RETURN_FRAME_REFUSAL_CODES = tuple(
    code for _requirement, code in SOLAR_RETURN_FRAME_REQUIREMENTS
)


def solar_return_frame_refusal(mode) -> str | None:
    """The first closed reason the annual route refuses this frame for, if any."""

    for requirement, code in SOLAR_RETURN_FRAME_REQUIREMENTS:
        if not _requirement_met(requirement, mode):
            return code
    return None


class FrameState(Applicability):
    """One method's answer from the frame table; every failing reason, in order."""

    reason_codes: list[str]


def _requirement_met(requirement, mode) -> bool:
    alternatives = (
        requirement if isinstance(requirement[0], tuple) else (requirement,)
    )
    return any(getattr(mode, axis) in accepted for axis, accepted in alternatives)


def method_frame_state(method: str, mode) -> FrameState:
    """Return ``{applicable, reason_code, reason_codes}`` for one method.

    Only the axes the method's row names are read, so a caller holding a partial
    mode (a probe, a unit test) gets the same answer as the web layer.
    """

    row = METHOD_FRAME_TABLE[method]
    failing: list[str] = []
    for requirement, code in row["requirements"]:
        if not _requirement_met(requirement, mode) and code not in failing:
            failing.append(code)
    if row.get("report", REPORT_FIRST) == REPORT_FIRST:
        failing = failing[:1]
    return FrameState(
        applicable=not failing, reason_code=failing[0] if failing else None, reason_codes=failing,
    )


def method_frame_states(mode) -> dict[str, FrameState]:
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


def frame_policy_receipt(mode, states: dict[str, FrameState]) -> dict:
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
