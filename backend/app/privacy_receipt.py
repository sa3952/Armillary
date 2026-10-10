"""The privacy fields a calculation receipt carries.

Only what the receipt table and the exports print: the attestation version and
status, the two birth-data facts, and the layers outside this product's
control.  The controls themselves are described in the privacy logging policy
(docs/PRIVACY_LOGGING_POLICY.md in the public source) and pinned by tests, not
restated in every response.
"""
from __future__ import annotations

_UNCOVERED_LAYERS = (
    "reverse_proxy_cdn_waf",
    "hosting_supervisor",
    "third_party_telemetry",
    "browser_os_native_memory",
)


def privacy_attestation() -> dict:
    """The same block for every request: nothing in it depends on the input."""

    return {
        "privacy_attestation_version": "1.3.0",
        "attestation_status": "provisional_pending_external_review",
        "contains_sensitive_birth_data": True,
        "anonymous_share_ready": False,
        "uncovered_layers": [
            {"layer": layer, "status": "outside_current_control_scope"}
            for layer in _UNCOVERED_LAYERS
        ],
    }
