"""Planet-in-house placements using explicit zodiacal half-open cusp intervals."""

from __future__ import annotations

from fractions import Fraction
from collections.abc import Sequence

from .invariants import InternalInvariantError
from .frame_compatibility import method_frame_state
from .module_state import PRODUCT_FORMULA_SOURCE, computed_receipt, unavailable_state
from .method_status import method_receipt
from .trace import Trace


METHOD_NAME = "zodiacal_cusp_half_open_intervals_v1"
# One half-open house interval for planets and Lots alike.
HOUSE_INTERVAL_SEMANTICS = "[cusp_n,cusp_n_plus_1)"
_BOUNDARY_TOLERANCE_DEGREES = 1e-9


_FULL_CIRCLE = Fraction(360)


def _exact_forward_distance(start: float, end: float) -> Fraction:
    """Forward zodiacal distance from start to end, exact for binary floats."""

    return (Fraction(end) - Fraction(start)) % _FULL_CIRCLE


def _house_for_longitude(
    longitude: float,
    cusps: Sequence[float],
    spans: tuple[Fraction, ...] | None = None,
) -> int:
    """Return the 1-based house for [cusp_n, cusp_n+1) in zodiacal order.

    The comparison is done in exact rational arithmetic.  Shifting a
    float longitude by +360 to meet an unwrapped cusp rounds: one ulp below cusp
    12 became cusp 12 itself (a wrong house), and -5e-324 % 360.0 became 360.0,
    which no half-open interval contains.  Every float is an exact binary
    rational, so measuring each interval and the point from its start cusp with
    Fraction partitions the circle with no gaps and no overlaps.

    ``spans`` is ``_cusp_spans(cusps)`` when the caller places several points
    against the same cusps; it is never kept beyond that caller's loop.
    """

    point = Fraction(longitude) % _FULL_CIRCLE
    if spans is None:
        spans = _cusp_spans(cusps)
    for index in range(12):
        if (point - Fraction(cusps[index])) % _FULL_CIRCLE < spans[index]:
            return index + 1
    raise RuntimeError("longitude did not match any house interval")


def _cusp_spans(cusps: Sequence[float]) -> tuple[Fraction, ...]:
    """The exact width of each house interval, checked.

    Not memoized across calls: cusps follow from the birth instant and place,
    and a process-wide memo would keep them in worker memory after the request.
    A caller placing many points computes this once and passes it down.
    """

    spans = []
    for index in range(12):
        span = _exact_forward_distance(cusps[index], cusps[(index + 1) % 12])
        if span <= Fraction(_BOUNDARY_TOLERANCE_DEGREES):
            raise ValueError("house cusps contain a zero-width interval")
        spans.append(span)
    if sum(spans) != _FULL_CIRCLE:
        raise ValueError("house cusps do not run once around the zodiac in order")
    return tuple(spans)


def compute_planet_house_placements(
    bodies: list[dict],
    houses: dict | None,
    context,
    trace: Trace,
) -> dict:
    """Place physical planets only; lunar nodes remain separate non-planet points."""

    # The frame premise and its closed reason codes come from the central
    # compatibility table; this module does not test a frame axis itself.
    reasons = list(method_frame_state("planet_in_house", context.mode)["reason_codes"])
    # A refusal must not depend on the thing it is refusing about: when the
    # observer has no horizon the caller has no houses to hand over, and this
    # function still has to answer.
    placements: list[dict] = []
    receipt = {
        "method": METHOD_NAME,
        **method_receipt("planet_in_house"),
        # The six state fields are written here, once.
        **(
            unavailable_state(reasons[0], requested=True)
            if reasons
            else computed_receipt(PRODUCT_FORMULA_SOURCE)
        ),
        "execution_status": (
            "not_applicable" if reasons else "computed"
        ),
        "reason_codes": reasons,
        "house_system_code": houses["system_code"] if houses else None,
        "house_system_name": houses["system_name"] if houses else None,
        "interval_semantics": HOUSE_INTERVAL_SEMANTICS,
        # The field keeps its
        # name for compatibility; this says what it measures.
        "distance_to_nearest_cusp_semantics": (
            "ecliptic_longitude_difference_latitude_ignored_not_mundane_house_distance"
        ),
        "placements": placements,
    }
    if reasons:
        trace.add(
            "行星落宮",
            note=(
                "目前天體黃經與地表宮頭不在可直接比較的同一框架，"
                f"因此不產生落宮：{', '.join(reasons)}。"
            ),
        )
        return receipt

    if houses is None:  # the refusal above is the only path without them
        raise InternalInvariantError("houses is not None")
    cusps = houses["cusps"]
    spans = _cusp_spans(cusps)
    for body in bodies:
        longitude = body.get("longitude")
        if longitude is None:
            continue
        house = _house_for_longitude(longitude, cusps, spans)
        start = cusps[house - 1] % 360.0
        end = cusps[house % 12] % 360.0
        # Exact, like the assignment: a float forward distance one ulp below a
        # cusp rounds to 360 and would report a whole house as the distance.
        distance_from_start = float(_exact_forward_distance(cusps[house - 1], longitude))
        distance_to_end = float(_exact_forward_distance(longitude, cusps[house % 12]))
        placements.append(
            {
                "key": body["key"],
                "name": body["name"],
                "longitude": longitude,
                "house": house,
                "cusp_start_longitude": start,
                "cusp_end_longitude": end,
                "distance_to_nearest_cusp_degrees": min(distance_from_start, distance_to_end),
                "on_cusp": distance_from_start <= _BOUNDARY_TOLERANCE_DEGREES,
            }
        )

    trace.add(
        "行星落宮",
        formula="天體黃經 ∈ [第 n 宮宮頭, 第 n+1 宮宮頭)",
        inputs={
            "house_system": houses["system_code"],
            "cusps": cusps,
            "planet_count": len(placements),
        },
        result={
            item["key"]: item["house"]
            for item in placements
        },
        note=(
            "宮頭使用半開區間；精確落在宮頭時歸入從該宮頭開始的新宮。"
            "本輸出只做落宮定位，不加入占星解讀。"
        ),
    )
    return receipt


# The lunar nodes and the lunar apsides are not planets and stay out of
# `placements`.  Under whole-sign houses a place is the sign itself, so these
# points get their place there without any further method claim; under the
# cusp-based systems this product gives them none.
POINT_PLACEMENT_RULE = "whole_sign_place_of_the_point_sign_v1"


def whole_sign_point_placements(
    points: list[dict],
    houses: dict | None,
    planet_in_house: dict,
    trace: Trace,
) -> dict:
    """The whole-sign place of each node and lunar apsis, or a named refusal."""

    def refused(reason_code: str | None) -> dict:
        return {
            "execution_status": "not_applicable",
            "reason_code": reason_code,
            "rule": POINT_PLACEMENT_RULE,
            "placements": [],
        }

    if planet_in_house.get("execution_status") != "computed" or houses is None:
        # The planets' own refusal is the reason: one premise, one code.
        return refused(planet_in_house.get("reason_code"))
    if houses.get("system_code") != "W":
        return refused("not_whole_sign_house_system")
    cusps = houses["cusps"]
    spans = _cusp_spans(cusps)
    placements = []
    for point in points:
        longitude = point.get("longitude")
        if longitude is None:
            continue
        house = _house_for_longitude(longitude, cusps, spans)
        placements.append({
            "key": point["key"],
            "name": point["name"],
            "longitude": longitude,
            "house": house,
            "on_cusp": _exact_forward_distance(cusps[house - 1], longitude) == 0,
        })
    trace.add(
        "月交點與月球拱點的整宮落宮",
        formula="點的黃經 ∈ [第 n 宮宮頭, 第 n+1 宮宮頭)，整宮制宮頭是星座起點",
        result={item["key"]: item["house"] for item in placements},
        note="只在整宮制給：整宮制的宮就是星座；其他宮位制不給這些點落宮。",
    )
    return {
        "execution_status": "computed",
        "reason_code": None,
        "rule": POINT_PLACEMENT_RULE,
        "placements": placements,
    }
