"""Answers reused within one calculation, and never beyond it.

Some pure functions are asked the same question many times while one chart is
computed: the time zone's offset segments around the stated hour (a one-minute
scan of about two days, asked by every module that reads the birth-time
interval) and the widths of one set of house cusps (asked by the planets, the
Lots and the extended Lots at every birth-time sample).  Their arguments are the
request's birth instant, place and cusps, so a process-wide cache would keep
them in worker memory after the answer is sent
(tests/backend/test_request_state_not_retained.py).  This memo exists only
inside ``request_memo()``, which the compute worker wraps around one
calculation; it is emptied and unset when the block exits, and outside a block
every call computes afresh.

Only values that are never mutated may be kept: callers store tuples or other
immutable values, or hand out a fresh container on each read.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeVar

T = TypeVar("T")

_REQUEST_MEMO: ContextVar[dict[tuple[str, Hashable], object] | None] = ContextVar(
    "armillary_request_memo", default=None,
)


@contextmanager
def request_memo() -> Iterator[dict[tuple[str, Hashable], object]]:
    """Memoise ``remembered`` answers for the calculation run inside."""

    memo: dict[tuple[str, Hashable], object] = {}
    token = _REQUEST_MEMO.set(memo)
    try:
        yield memo
    finally:
        memo.clear()
        _REQUEST_MEMO.reset(token)


def remembered(kind: str, key: Hashable, compute: Callable[[], T]) -> T:
    """``compute()``, asked once per ``(kind, key)`` inside a ``request_memo``.

    An exception is not remembered: asking again raises again, as an
    unmemoised call would.
    """

    memo = _REQUEST_MEMO.get()
    if memo is None:
        return compute()
    entry = (kind, key)
    if entry in memo:
        return memo[entry]  # type: ignore[return-value]
    value = compute()
    memo[entry] = value
    return value
