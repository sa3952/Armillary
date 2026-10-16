"""The one exception a broken internal guarantee raises.

A condition the code itself guarantees (a value an earlier step always sets, a
code drawn from a closed set) is checked with an explicit ``if`` and this
exception, never ``assert``: ``python -O`` strips assertions, and a check that
can vanish is not a check.  Nothing catches it on a request path; it leaves as
the closed ``internal_server_error`` refusal, because a broken guarantee is the
server's fault, not the request's.  It subclasses ``AssertionError`` so
telemetry keeps naming it by the class the bare assertions used to raise.

The message names the condition that failed, as source text; it never carries a
value, so nothing a request contained can ride on it.
"""

from __future__ import annotations


class InternalInvariantError(AssertionError):
    """A condition the code guarantees did not hold."""
