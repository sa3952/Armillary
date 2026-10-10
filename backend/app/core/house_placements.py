"""Planet-in-house placements using explicit zodiacal half-open cusp intervals."""

from __future__ import annotations

from fractions import Fraction

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


def _house_for_longitude(longitude: float, cusps: list[float]) -> int:
    """Return the 1-based house for [cusp_n, cusp_n+1) in zodiacal order.

    The comparison is done in exact rational arithmetic.  Shifting a
    float longitude by +360 to meet an unwrapped cusp rounds: one ulp below cusp
    12 became cusp 12 itself (a wrong house), and -5e-324 % 360.0 became 360.0,
    which no half-open interval contains.  Every float is an exact binary
    rational, so measuring each interval and the point from its start cusp with
    Fraction partitions the circle with no gaps and no overlaps.
    """

    point = Fraction(longitude) % _FULL_CIRCLE
    spans = []
    for index in range(12):
        span = _exact_forward_distance(cusps[index], cusps[(index + 1) % 12])
        if span <= Fraction(_BOUNDARY_TOLERANCE_DEGREES):
            raise ValueError("house cusps contain a zero-width interval")
        spans.append(span)
    if sum(spans) != _FULL_CIRCLE:
        raise ValueError("house cusps do not run once around the zodiac in order")
    for index in range(12):
        if (point - Fraction(cusps[index])) % _FULL_CIRCLE < spans[index]:
            return index + 1
    raise RuntimeError("longitude did not match any house interval")


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

    assert houses is not None  # the refusal above is the only path without them
    cusps = houses["cusps"]
    for body in bodies:
        longitude = body.get("longitude")
        if longitude is None:
            continue
        house = _house_for_longitude(longitude, cusps)
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
