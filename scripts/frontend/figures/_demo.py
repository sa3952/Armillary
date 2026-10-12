"""The demonstration chart the home and features pages print, as the product
answers it in process: 1990-05-15 14:30 Taipei, whole signs, tropical,
apparent, geocentric, with the outer planets and Chiron; and the hour
14:00–15:00 of the same day as the product samples it when only the hour is
known.
"""
from __future__ import annotations

import functools
from typing import Any

from ._common import SIGNS, product_charts


DEMO: dict[str, Any] = {
    "datetime": {"year": 1990, "month": 5, "day": 15, "hour": 14, "minute": 30, "second": 0},
    "location": {"latitude": 25.05306, "longitude": 121.52639},
    "timezone": {"mode": "iana", "iana_name": "Asia/Taipei"},
    "options": {"house_system": "W", "include_houses": True,
                "include_outer_planets": True, "include_chiron": True},
}
CLASSICAL = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
# The four bounds tables, in the order the features page sets them side by side.
BOUNDS = (
    "egyptian_bounds_robbins_1940_v1",
    "chaldaean_bounds_ptolemy_i_21_v1",
    "ptolemy_bounds_robbins_1940_v1",
    "lilly_received_bounds_1647_v1",
)


def _clock(local_time: str) -> tuple[int, int, int]:
    hour, minute, second = local_time.split(" ")[1].split(".")[0].split(":")
    return int(hour), int(minute), int(second)


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    """The product's responses, read once per process."""
    with product_charts() as post:
        chart = post(DEMO)
        sidereal = post({**DEMO, "computation_mode": {"zodiac": "sidereal", "ayanamsa": "fagan_bradley"}})
        bounds = {}
        for profile in BOUNDS:
            answer = post({**DEMO, "options": {**DEMO["options"], "bounds_profile": profile}})
            objects = answer["derived_methods"]["essential_dignities"]["profile_results"][profile]["objects"]
            bounds[profile] = {item["key"]: item["ruler"] for item in objects}
        hour_request = {**DEMO, "birth_time_precision": "approximate_hour",
                        "datetime": {**DEMO["datetime"], "minute": 0, "second": 0}}
        hour = post(hour_request)["birth_time_sensitivity"]
        probes = []
        for probe in hour["probes"]:
            h, m, s = _clock(probe["input_local_time"])
            answer = post({**hour_request, "birth_time_precision": "exact",
                           "datetime": {**hour_request["datetime"], "hour": h, "minute": m, "second": s}})
            probes.append({
                "second": (h - 14) * 3600 + m * 60 + s,
                "asc": answer["astronomical_data"]["angles"]["asc"],
                "moon": next(body["longitude"] for body in answer["astronomical_data"]["bodies"]
                             if body["key"] == "moon"),
                "houses": {item["key"]: item["house"]
                           for item in answer["derived_methods"]["planet_in_house"]["placements"]},
            })
    return {"chart": chart, "sidereal": sidereal, "bounds": bounds, "hour": hour, "probes": probes}


def step(answer: dict, title: str) -> tuple[int, dict]:
    """(the step's number as the result page and the exports print it, its result)."""
    found = [(index + 1, item["result"]) for index, item in enumerate(answer["calculation_trace"])
             if item["title"] == title]
    if len(found) != 1:
        raise RuntimeError(f"the trace has {len(found)} steps titled {title!r}")
    return found[0]


def body(answer: dict, key: str) -> dict:
    (found,) = [item for item in answer["astronomical_data"]["bodies"] if item["key"] == key]
    return found


def dms(degrees: float, places: int = 0) -> str:
    """|degrees| as 「D°MM′SS″」, rounded once at `places` decimals of an arcsecond."""
    scale = 10 ** places
    units = round(abs(degrees) * 3600 * scale)
    whole, rest = divmod(units, 3600 * scale)
    minutes, seconds = divmod(rest, 60 * scale)
    text = f"{seconds // scale:02d}" + (f".{seconds % scale:0{places}d}" if places else "")
    return f"{whole}°{minutes:02d}′{text}″"


def signed_dms(degrees: float, places: int) -> str:
    return ("+" if degrees >= 0 else "−") + dms(degrees, places)


def zodiacal(longitude: float, places: int = 0) -> str:
    """「天秤 1°35′32.3″」: the sign and the position in it, rounded once on the
    whole longitude (so 29°59′59.96″ prints as 0°00′00″ of the next sign)."""
    scale = 10 ** places
    units = round((longitude % 360) * 3600 * scale)
    sign, rest = divmod(units, 30 * 3600 * scale)
    return f"{SIGNS[sign % 12]} {dms(rest / (3600 * scale), places)}"


def zodiacal_minutes(longitude: float) -> str:
    """「摩羯 24°20′」: whole arcminutes."""
    sign, rest = divmod(round((longitude % 360) * 60), 30 * 60)
    return f"{SIGNS[sign % 12]} {rest // 60}°{rest % 60:02d}′"


def hms(degrees: float, places: int) -> str:
    """Right ascension as 「03h27m12.82s」."""
    scale = 10 ** places
    units = round(degrees / 15 * 3600 * scale)
    hours, rest = divmod(units, 3600 * scale)
    minutes, seconds = divmod(rest, 60 * scale)
    return f"{hours:02d}h{minutes:02d}m{seconds // scale:02d}.{seconds % scale:0{places}d}s"


def hour_summary() -> dict:
    """What the sampled hour says: the ascendant's sampled range, the one
    transition and which bodies change house across it."""
    data = answers()
    probes, hour = data["probes"], data["hour"]
    transitions = hour["transitions"]
    if len(transitions) != 1:
        raise RuntimeError(f"the demonstration hour has {len(transitions)} transitions, not one")
    first, last = probes[0], probes[-1]
    changed = [key for key, house in first["houses"].items() if last["houses"][key] != house]
    moon_signs = {int(probe["moon"] // 30) for probe in probes}
    if len(moon_signs) != 1:
        raise RuntimeError("the Moon changes sign between the demonstration hour's samples")
    return {
        "probes": len(probes),
        "span_seconds": last["second"] - first["second"],
        "asc_range": (last["asc"] - first["asc"]) % 360,
        "width_seconds": transitions[0]["resolution_seconds"],
        "changed": changed,
        "changed_classical": [key for key in changed if key in CLASSICAL],
        "moon_sign": SIGNS[moon_signs.pop()],
    }
