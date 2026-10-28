"""Catalogue places whose zone is disputed for some dates.

A few places keep a zone the tz database cannot settle for every date: the law
names one zone and the place keeps another (Fort Pierre, SD), the place tried
another zone for some years (West Wendover, NV), or the zone holds only from a
known date (LeChee, AZ, on the Navajo Nation's daylight saving time since 1968).
The catalogue keeps a policy beside such a place's zone
(scripts/validation/place_zone_policies.json, carried in the catalogue's
metadata), and every chart route reads it through this module:

* an override in force on the birth date replaces the catalogue zone (LeChee
  before 1967 is on Arizona's America/Phoenix);
* an alternative zone in force on the birth date may be named by the request
  instead of the catalogue zone, and any other zone is refused as before;
* the response states the zone applied and why, with the policy's note and
  source.

Only tz database zones are named; no rule is written here.  The birth date is
placed in a range by the instant the catalogue zone gives the request's local
time, so a date within a few hours of a range's edge may fall either side.
"""

from __future__ import annotations

import datetime as dtmod
from typing import Any, Final, Literal
from zoneinfo import ZoneInfo

PlaceZoneReason = Literal["catalogue_zone", "override", "alternative_chosen"]
PLACE_ZONE_REASONS: Final = ("catalogue_zone", "override", "alternative_chosen")


def policy_key(source: str, source_record_id: str) -> str:
    return f"{source}/{source_record_id}"


def _instant(text: str) -> dtmod.datetime:
    # A bare date is that day's start in UTC.
    moment = dtmod.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=dtmod.UTC)


def _in_range(entry: dict, instant: dtmod.datetime) -> bool:
    start, end = entry.get("from"), entry.get("until")
    return (start is None or _instant(start) <= instant) and (end is None or instant < _instant(end))


def birth_instant(policy: dict, local: dtmod.datetime) -> dtmod.datetime:
    return local.replace(tzinfo=ZoneInfo(policy["zone"])).astimezone(dtmod.UTC)


def offered_alternatives(policy: dict, instant: dtmod.datetime) -> list[dict]:
    return [entry for entry in policy["alt_zones"] if _in_range(entry, instant)]


def offers(policy: dict, zone: str, local: dtmod.datetime) -> bool:
    """Whether the request may name ``zone`` for this place and local time."""

    instant = birth_instant(policy, local)
    return zone == policy["zone"] or any(
        entry["zone"] == zone for entry in offered_alternatives(policy, instant)
    )


def resolve(policy: dict, *, requested_zone: str, local: dtmod.datetime) -> dict[str, Any]:
    """The zone applied for a request naming ``requested_zone``, which ``offers``
    has already accepted, and the receipt that says why."""

    instant = birth_instant(policy, local)
    alternatives = offered_alternatives(policy, instant)
    override = next((entry for entry in policy["overrides"] if _in_range(entry, instant)), None)
    if requested_zone != policy["zone"]:
        applied, reason, confidence = requested_zone, "alternative_chosen", None
    elif override is not None:
        applied, reason, confidence = override["zone"], "override", override["confidence"]
    else:
        applied, reason, confidence = policy["zone"], "catalogue_zone", None
    uncertain_before = policy.get("uncertain_before")
    uncertain = confidence is not None or (
        uncertain_before is not None and instant < _instant(uncertain_before)
    )
    offered = [
        {"zone": zone, "label": label}
        for zone, label in (
            [(policy["zone"], None)] + [(entry["zone"], entry["label"]) for entry in alternatives]
        )
        if zone != applied
    ]
    return {
        "catalogue_zone": policy["zone"],
        "requested_zone": requested_zone,
        "applied_zone": applied,
        "reason": reason,
        "override_confidence": confidence,
        "disputed": bool(alternatives) or uncertain,
        "uncertain": uncertain,
        # The zones the request may name instead at this date: the catalogue
        # zone when another was applied, and each alternative in force.
        "alternatives": offered if (alternatives or reason == "alternative_chosen") else [],
        "legal_zone": policy.get("legal_zone"),
        "note_key": policy["note_key"],
        "note": policy["note"],
        "source": policy["source"],
    }
