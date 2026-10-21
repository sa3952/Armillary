"""Process settings read from the environment once, at application start.

There is one posture: the public one.  Indexing and caching are decided by
the response paths themselves (privacy_logging's cache split) and, for a
staging host, by the edge, which owns X-Robots-Tag.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
from collections.abc import Mapping


# The host this deployment answers for (request_limits.ChartRequestBoundary says
# what the check is and is not).  Unset means no check: the same module runs in
# development and in tests, and the staging configuration verifier requires it
# on the deployment, where the obligation belongs.
EXPECTED_HOST_ENVIRONMENT_VARIABLE = "CLASSICAL_ASTROLOGY_EXPECTED_HOST"
SOURCE_REVISION_ENVIRONMENT_VARIABLE = (
    "CLASSICAL_ASTROLOGY_SOURCE_REVISION"
)
BUILD_ENVIRONMENT_REVISION_SOURCE = (
    "build_environment:CLASSICAL_ASTROLOGY_SOURCE_REVISION"
)
_SOURCE_REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
# Per deployment (the release compose file sets it): unset or "0" leaves the
# annual route unregistered (404 unknown_api_path, absent from OpenAPI); "1"
# registers it; any other value fails start-up rather than guess.
ANNUAL_ROUTE_ENVIRONMENT_VARIABLE = "ARMILLARY_ENABLE_ANNUAL_ROUTE"
_FLAG_VALUES = {None: False, "": False, "0": False, "1": True}


@dataclass(frozen=True)
class AppSettings:
    source_revision: str | None = None
    revision_source: str | None = None
    # Test-only seam for a missing/corrupt catalog path; production leaves it
    # unset so PlaceCatalog selects its bundled immutable default.
    place_catalog_path: str | None = None
    expected_host: str | None = None
    enable_annual_route: bool = False

    def __post_init__(self) -> None:
        if self.source_revision is None:
            if self.revision_source is not None:
                raise RuntimeError(
                    "revision_source requires an available source revision"
                )
            return
        if not _SOURCE_REVISION_PATTERN.fullmatch(self.source_revision):
            raise RuntimeError(
                "source revision must be exactly 40 lowercase hexadecimal "
                "characters"
            )
        if self.revision_source != BUILD_ENVIRONMENT_REVISION_SOURCE:
            raise RuntimeError(
                "source revision must identify its controlled build source"
            )

    @property
    def build_identity(self) -> dict:
        return {
            "status": (
                "available"
                if self.source_revision is not None
                else "unavailable"
            ),
            "source_revision": self.source_revision,
            "revision_source": self.revision_source,
        }


def load_settings(environment: Mapping[str, str] | None = None) -> AppSettings:
    source = os.environ if environment is None else environment
    expected_host = (source.get(EXPECTED_HOST_ENVIRONMENT_VARIABLE) or "").strip()
    raw_revision = source.get(SOURCE_REVISION_ENVIRONMENT_VARIABLE)
    if raw_revision in (None, "", "uncommitted"):
        source_revision = None
        revision_source = None
    elif _SOURCE_REVISION_PATTERN.fullmatch(raw_revision):
        source_revision = raw_revision
        revision_source = BUILD_ENVIRONMENT_REVISION_SOURCE
    else:
        raise RuntimeError(
            "source revision must be 'uncommitted' or exactly 40 lowercase "
            "hexadecimal characters"
        )

    raw_annual_flag = source.get(ANNUAL_ROUTE_ENVIRONMENT_VARIABLE)
    if raw_annual_flag not in _FLAG_VALUES:
        raise RuntimeError(
            f"{ANNUAL_ROUTE_ENVIRONMENT_VARIABLE} must be unset, '0' or '1'"
        )

    return AppSettings(
        expected_host=expected_host or None,
        source_revision=source_revision,
        revision_source=revision_source,
        enable_annual_route=_FLAG_VALUES[raw_annual_flag],
    )
