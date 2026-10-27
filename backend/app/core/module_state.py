"""The six state fields every optional module writes about itself.

One vocabulary for every producer: ``requested`` (the request asked),
``executed`` (the calculation was attempted and ran), ``applicable`` (the
request configuration permits it), ``available`` (it produced a usable
result), ``source`` and ``reason_code``.  Producers build the fields here; the
Dossier copies them with ``state_of`` and never infers state from request
flags.  A module status word is a projection of the six fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict, cast

if TYPE_CHECKING:
    from .trace import Trace

MODULE_STATUSES = ("not_requested", "computed", "not_applicable")
MODULE_NOT_REQUESTED, MODULE_COMPUTED, MODULE_NOT_APPLICABLE = MODULE_STATUSES
# Why an attempted event search produced nothing (contained, not a failed
# chart); written by the chart pipeline, read by the dossier warnings.
EVENT_SEARCH_REASON_CODES = (
    "full_ephemeris_unavailable_for_search_window",
    "ephemeris_segment_file_missing",
    "swiss_ephemeris_error_in_search",
)
# FullEphemerisRequiredError.reason -> (reason code, still applicable).  Leaving
# the bundled coverage is the request's own (not applicable); a missing segment
# file is the server's fault (applicable, merely unavailable).  Any other reason
# (an unpredicted Swiss fallback) is not contained: it fails the request.
SEARCH_EPHEMERIS_REFUSALS = {
    "segment_out_of_coverage": (EVENT_SEARCH_REASON_CODES[0], False),
    "segment_file_missing": (EVENT_SEARCH_REASON_CODES[1], True),
}



class Applicability(TypedDict):
    """Whether the request configuration permits a module, and why not."""

    applicable: bool
    reason_code: str | None


class ModuleState(TypedDict):
    """The six fields, in their one order (the order JSON writes them in)."""

    requested: bool
    executed: bool
    applicable: bool
    available: bool
    source: str | None
    reason_code: str | None


class EventModuleState(ModuleState):
    """An event search's six fields, with the status word consumers read."""

    status: str


# A result the product computes itself from emitted positions, as opposed to
# one read from Swiss Ephemeris or from a named text table.
PRODUCT_FORMULA_SOURCE = "product_formula"


def module_state(
    *,
    requested: bool,
    executed: bool,
    applicable: bool,
    available: bool,
    source: str | None = None,
    reason_code: str | None = None,
) -> ModuleState:
    """The six fields, in their one order."""

    return ModuleState(
        requested=requested, executed=executed, applicable=applicable,
        available=available, source=source, reason_code=reason_code,
    )


def not_requested_state(reason_code: str | None = None) -> ModuleState:
    return module_state(
        requested=False, executed=False, applicable=False, available=False,
        reason_code=reason_code,
    )


def unavailable_state(reason_code: str | None, *, requested: bool) -> ModuleState:
    """Nothing ran and nothing is available, for the stated reason."""

    return module_state(
        requested=requested, executed=False, applicable=False, available=False,
        reason_code=reason_code,
    )


def not_applicable_receipt(state: Applicability) -> ModuleState:
    """A requested module the frame table (or a mode) refused before running."""

    if state["applicable"]:
        raise ValueError("not_applicable_receipt requires an inapplicable state")
    return unavailable_state(state["reason_code"], requested=True)


def computed_receipt(
    source: str | None,
    *,
    applicable: bool = True,
    available: bool = True,
    reason_code: str | None = None,
) -> ModuleState:
    """A requested module whose calculation ran."""

    return module_state(
        requested=True, executed=True, applicable=applicable,
        available=available, source=source, reason_code=reason_code,
    )


def state_of(owner: object) -> ModuleState:
    """The six state fields exactly as the module's producer wrote them.

    A module that was not produced (None, or an empty container) was not
    requested.  That reading is only safe beside the request: the Dossier's
    option receipts refuse a requested option whose module reads as not
    requested.  A produced module missing a field is a producer defect and
    raises here instead of being filled in by the reader.
    """

    if not isinstance(owner, dict) or not owner.get("requested"):
        return not_requested_state()
    return state_fields(cast(ModuleState, owner))


def state_fields(receipt: ModuleState) -> ModuleState:
    """Exactly the six fields of a receipt that may carry more keys."""

    return ModuleState(
        requested=receipt["requested"], executed=receipt["executed"],
        applicable=receipt["applicable"], available=receipt["available"],
        source=receipt["source"], reason_code=receipt["reason_code"],
    )


def module_status_word(state: ModuleState) -> str:
    """Project one recorded state onto the closed module-status vocabulary."""

    if not state["requested"]:
        return MODULE_NOT_REQUESTED
    return MODULE_COMPUTED if state["available"] else MODULE_NOT_APPLICABLE


def frame_table_refusal(
    state: Applicability, trace: Trace, title: str, note: str, *, inputs: dict | None = None
) -> ModuleState:
    """Trace the frame table's refusal of a module and return its receipt."""

    trace.add(
        title,
        result={"execution_status": "not_applicable", "reason_code": state["reason_code"]},
        note=note,
        inputs=inputs,
    )
    return not_applicable_receipt(state)
