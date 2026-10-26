"""A structural oracle for request events: every field has the shape its
reader expects, and no request value appears in any field.

Searching the serialised event for a birth year fails at random: the request
ID is 32 random hex digits and contains "1987" about once in 2,200 events.
Here each field is checked against its own value shape instead, written from
the event's documented meaning rather than read from the module under test,
so the request ID can carry nothing but hex and a value smuggled into any
other field is caught where it lands.
"""

from __future__ import annotations

import re


FIELDS = (
    "event_schema_version", "event", "request_id", "route", "method", "status_code",
    "duration_bucket", "request_size_bucket", "outcome", "error_code", "failure_class",
)
ROUTES = frozenset({
    "/api/chart", "/api/chart/annual", "/api/health", "/api/places/search", "/api/time/convert",
    "frontend_or_unmatched",
})
METHODS = frozenset({"GET", "POST", "HEAD", "OPTIONS", "OTHER"})
OUTCOMES = frozenset({"success", "rejected", "error", "unknown"})
# The error codes: whether these occur depends on the request's framing, the service's state or
# the client, never on the birth date, time or place.
COARSE_EVENT_CODES = frozenset({
    # telemetry's own words
    "request_rejected", "server_error", "unclassified", "client_disconnected",
    # the request boundary and the JSON text
    "undeclared_host", "unknown_api_path", "unsupported_method", "request_capacity_exhausted",
    "compute_capacity_exhausted", "request_headers_too_large", "unsupported_media_type",
    "conflicting_request_framing", "invalid_content_length", "request_body_too_large",
    "empty_request_body", "request_body_read_timeout", "request_body_not_utf8", "json_invalid",
    "duplicate_json_key",
    # any field of any request failing its declared type or range
    "request_validation_failed",
    # the service's own state
    "place_catalog_unavailable", "place_search_timeout", "internal_server_error",
    # the edge and the framework
    "edge_rate_limited", "upstream_unavailable", "bad_request", "unauthorized", "not_found",
    "method_not_allowed",
    # the categories a birth-record-dependent refusal is reduced to
    "domain_refused", "domain_failed",
})
_REQUEST_ID = re.compile(r"[0-9a-f]{32}|invalid")
DURATION_BUCKETS = frozenset({"invalid", "lt_1s", "1_to_9s", "gte_10s"})
SIZE_BUCKETS = frozenset({"absent", "invalid", "empty", "1_to_1024b", "1025_to_16384b", "16385_to_131072b",
                          "gt_131072b"})
_FAILURE_CLASS = re.compile(r"[A-Z][A-Za-z]*(?:Error|Exception)?|unclassified")


def shape_problems(event: object) -> list[str]:
    """Every way the event departs from the closed shape (empty when it holds)."""
    if not isinstance(event, dict):
        return [f"not an object: {type(event).__name__}"]
    if tuple(event) != FIELDS:
        return [f"fields {tuple(event)}"]
    problems = []

    def need(field: str, ok: bool) -> None:
        if not ok:
            problems.append(f"{field}={event[field]!r}")

    need("event_schema_version", event["event_schema_version"] == "privacy-request-event-v3")
    need("event", event["event"] == "http_request_completed")
    need("request_id", isinstance(event["request_id"], str) and bool(_REQUEST_ID.fullmatch(event["request_id"])))
    need("route", event["route"] in ROUTES)
    need("method", event["method"] in METHODS)
    need("status_code", type(event["status_code"]) is int and 0 <= event["status_code"] <= 599)
    need("duration_bucket", event["duration_bucket"] in DURATION_BUCKETS)
    need("request_size_bucket", event["request_size_bucket"] in SIZE_BUCKETS)
    need("outcome", event["outcome"] in OUTCOMES)
    need("error_code", event["error_code"] is None or event["error_code"] in COARSE_EVENT_CODES)
    need("failure_class", event["failure_class"] is None
         or (isinstance(event["failure_class"], str) and bool(_FAILURE_CLASS.fullmatch(event["failure_class"]))))
    return problems


def assert_events_hold_no(events: list[dict], values: list[object]) -> None:
    """Each event has the closed shape, and the one field whose shape is open
    (the failure class) contains none of the request's values.  The other
    fields are confined to closed sets or to hex, so a value can reach them only
    as a shape failure."""
    assert events, "no event to check"
    assert values, "no request value to look for"
    for event in events:
        assert shape_problems(event) == [], event
        for field in ("failure_class",):
            content = event[field]
            if content is None:
                continue
            for value in values:
                assert str(value) not in str(content), (field, content, value)
