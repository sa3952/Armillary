"""The refusal models and the strict JSON body and query checks."""

import json
import re
import typing
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, create_model

from .refusals import REFUSAL_DETAIL_EXTRAS, REFUSALS
from .schema_rules import VALIDATION_ISSUE_TYPES


_ISSUE_TYPE_ENUM = typing.cast("list[JsonValue]", list(VALIDATION_ISSUE_TYPES))
_REFUSAL_CODE_ENUM = typing.cast("list[JsonValue]", sorted(REFUSALS))


class RefusalIssue(BaseModel):
    """One validation finding: a closed code and a declared field path."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(json_schema_extra={"enum": _ISSUE_TYPE_ENUM})
    loc: list[str | int] = Field(
        description=(
            "Declared field names and array indices from the request root "
            "('body' or 'query'). A key the API does not declare is reported "
            "as 'input'; no request value is ever included."
        )
    )


# Built from the refusal table so the published codes and receipt fields are the
# runtime ones rather than a second list kept beside them.
_REFUSAL_DETAIL_FIELDS: dict[str, Any] = {
    "code": (str, Field(json_schema_extra={"enum": _REFUSAL_CODE_ENUM})),
    "message": (
        str,
        Field(description="Fixed text for the code; never contains request values."),
    ),
    "issues": (list[RefusalIssue] | None, None),
    "truncated": (
        bool | None,
        Field(
            default=None,
            description=(
                "Present and true only when more issues were found than "
                "`issues` lists (the list keeps the first ones)."
            ),
        ),
    ),
    **{name: (annotation, None) for name, annotation in REFUSAL_DETAIL_EXTRAS.items()},
}
RefusalDetail = create_model(
    "RefusalDetail",
    __config__=ConfigDict(extra="forbid"),
    **_REFUSAL_DETAIL_FIELDS,
)
RefusalResponse = create_model(
    "RefusalResponse",
    __config__=ConfigDict(extra="forbid"),
    detail=(RefusalDetail, ...),
)


def request_field_names(model: type[BaseModel] | None) -> frozenset[str]:
    """The only request-shaped text a refusal on one route may carry: the names
    that route's own body model declares.  A union over every
    model let a place search echo a chart or annual field name back."""

    names: set[str] = set()
    pending = [] if model is None else [model]
    seen: set[type[BaseModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        for name, field in model.model_fields.items():
            names.add(name)
            for candidate in (field.annotation, *typing.get_args(field.annotation)):
                if isinstance(candidate, type) and issubclass(candidate, BaseModel):
                    pending.append(candidate)
    return frozenset(names)


_REQUEST_ROOTS = frozenset({"body", "query"})
UNDECLARED_KEY = "input"


def _declared_segment(item: object, declared: frozenset[str]) -> str | int:
    if isinstance(item, int) and not isinstance(item, bool):
        return item
    return item if isinstance(item, str) and item in declared else UNDECLARED_KEY


def validation_issues(
    errors: Iterable[Mapping[str, Any]],
    *,
    declared_names: frozenset[str],
) -> list[dict[str, object]]:
    """Reduce Pydantic errors to closed codes and declared field paths.

    Pydantic's `input`, `msg` and `ctx` never leave: they can carry the rejected
    birth values.  Only a rule's own `field_path` is read from the context, and
    only the names the answering route declares (its body model's fields and
    its query parameters) survive in any location.
    """

    declared = declared_names | _REQUEST_ROOTS
    issues: list[dict[str, object]] = []
    for error in errors:
        raw_type = error.get("type")
        issue_type = raw_type if raw_type in VALIDATION_ISSUE_TYPES else "value_error"
        location = [_declared_segment(item, declared) for item in error.get("loc", ())]
        context = error.get("ctx")
        field_path = context.get("field_path") if isinstance(context, dict) else None
        if isinstance(field_path, tuple):
            location.extend(_declared_segment(item, declared) for item in field_path)
        issues.append({"type": issue_type, "loc": location})
    return issues


class StrictJsonBodyError(Exception):
    """A body that is not one unambiguous UTF-8 JSON text."""

    def __init__(self, code: str, issues: list[dict[str, object]] | None = None):
        super().__init__(code)
        self.code = code
        self.issues = issues


class _JsonObjectPairs(list):
    """A JSON object as parsed: its (key, value) pairs in order, duplicates kept."""


# No request model nests more than a few levels (test_refusal_contract.py
# measures it); a deeper body is refused as json_invalid before parsing.
MAX_JSON_NESTING_DEPTH = 32
_JSON_STRUCTURE_CHARACTER = re.compile(r'[\[\]{}"\\]')


def _json_nesting_exceeds(text: str, limit: int = MAX_JSON_NESTING_DEPTH) -> bool:
    """Whether the brackets outside strings open more than ``limit`` levels.

    One pass over the structural characters only, stopping at the first level
    past the limit, so a deep body costs ``limit`` steps and ``json.loads``
    never recurses into it.  Text that is not JSON is left to ``json.loads``.
    """

    depth = 0
    in_string = False
    escaped_position = -1
    for match in _JSON_STRUCTURE_CHARACTER.finditer(text):
        character, position = match.group(), match.start()
        if in_string:
            if position == escaped_position:
                continue
            if character == "\\":
                escaped_position = position + 1
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > limit:
                return True
        elif character in "]}":
            depth -= 1
    return False


def _first_duplicate_key_path(document: object) -> tuple[str | int, ...] | None:
    # Nodes carry a (parent link, key) link rather than a path copy, so the
    # scan stays linear; a path is spelled out only for the duplicate.
    pending: list[tuple[object, tuple | None]] = [(document, None)]
    while pending:
        node, link = pending.pop()
        if isinstance(node, _JsonObjectPairs):
            seen: set[str] = set()
            for key, _value in node:
                if key in seen:
                    return (*_link_path(link), key)
                seen.add(key)
            pending.extend((value, (link, key)) for key, value in reversed(node))
        elif isinstance(node, list):
            pending.extend(
                (value, (link, index))
                for index, value in reversed(list(enumerate(node)))
            )
    return None


def _link_path(link: tuple | None) -> tuple[str | int, ...]:
    segments: list[str | int] = []
    while link is not None:
        link, segment = link
        segments.append(segment)
    return tuple(reversed(segments))


class _NotJsonText(ValueError):
    """Raised inside `json.loads` for text RFC 8259 does not admit."""


def _refuse_json_constant(_name: str) -> None:
    raise _NotJsonText("not a JSON number")


def check_strict_query(
    items: Iterable[tuple[str, str]], declared: frozenset[str], raw: bytes = b"",
) -> None:
    """Refuse a query a route does not declare, or a declared name given twice.

    An unknown body field is refused (`extra_forbidden`) while an unknown query
    parameter was accepted, so `?lat=51.4779` on a chart request was a 200 and
    a request could carry data the receipt never names.  A repeated declared
    name was resolved silently (the last `projection` won).  Unknown names are
    reported as the undeclared placeholder, never echoed.

    `raw` is the query as sent.  The parsed items drop empty segments, so
    `?&&&` read as no query at all; a segment that names nothing
    is undeclared like any other.
    """

    counts = Counter(name for name, _value in items)
    issues: list[dict[str, object]] = []
    empty_segment = bool(raw) and b"" in raw.split(b"&")
    if empty_segment or any(name not in declared for name in counts):
        issues.append({"type": "extra_forbidden", "loc": ["query", UNDECLARED_KEY]})
    for name in sorted(name for name, seen in counts.items() if name in declared and seen > 1):
        issues.append({"type": "duplicate_query_parameter", "loc": ["query", name]})
    if issues:
        raise StrictJsonBodyError("request_validation_failed", issues)


def check_strict_json_body(raw: bytes, declared_names: frozenset[str] = frozenset()) -> None:
    """Refuse a body two JSON readers could read differently.

    `json.loads` on bytes detects UTF-16 and UTF-32 and skips a BOM, and a dict
    keeps the last of two equal keys.  Each is a choice the client did not make,
    and the receipt would then describe a request other than the one sent.
    RFC 8259 §8.1 requires UTF-8 without a BOM between systems.  A raw NUL byte
    cannot occur in UTF-8 JSON text; it is what UTF-16/32 look like without
    their BOM.  An empty body is left to the model, which names what is missing.
    """

    if not raw:
        return
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise StrictJsonBodyError("request_body_not_utf8")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise StrictJsonBodyError("request_body_not_utf8") from None
    if _json_nesting_exceeds(text):
        raise StrictJsonBodyError("json_invalid")
    try:
        # NaN/Infinity are not JSON (RFC 8259 §6) though Python reads them;
        # refused here as json_invalid, not later as finite_number.
        document = json.loads(
            text, object_pairs_hook=_JsonObjectPairs, parse_constant=_refuse_json_constant,
        )
    except (ValueError, RecursionError):
        raise StrictJsonBodyError("json_invalid") from None
    path = _first_duplicate_key_path(document)
    if path is not None:
        raise StrictJsonBodyError(
            "duplicate_json_key",
            [{
                "type": "duplicate_json_key",
                "loc": [
                    "body",
                    *(_declared_segment(item, declared_names) for item in path),
                ],
            }],
        )


# `POST /api/chart?projection=` selects a view of one response, not a
# calculation input, so it is outside ChartRequest, option_states and every
# request digest.  app.response_projection owns the views.
ChartProjection = Literal["page", "detailed"]
