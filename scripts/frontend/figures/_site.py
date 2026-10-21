"""Facts the site's pages state about the product, read from the code and data
that decide them: the request schema's choices and defaults, the star
catalogue, the year range, the request limits, the response headers, the
ephemeris files' own headers, the surface list and the options catalogue.
"""
from __future__ import annotations

import collections
import functools
import json
import re
from typing import Union, get_args, get_origin, get_type_hints

from ._common import ROOT, backend_on_path, options_catalogue


def _choices(model, field: str) -> tuple[str, ...]:
    annotation = get_type_hints(model)[field]
    while get_origin(annotation) is Union:  # Optional[Literal[...]]
        (annotation,) = [arg for arg in get_args(annotation) if arg is not type(None)]
    # "all" (全部並列) asks for every named choice; it is not one of them.
    choices = tuple(choice for choice in get_args(annotation) if choice != "all")
    if not choices or not all(isinstance(choice, str) for choice in choices):
        raise RuntimeError(f"{model.__name__}.{field} is not a closed set of names")
    return choices


@functools.lru_cache(maxsize=1)
def product() -> dict:
    with backend_on_path():
        from app import domain_catalog, request_limits, schema_chart, schema_inputs
        from app.core.birth_time_sensitivity import TRANSITION_RESOLUTION_SECONDS
        from app.core.lots import SECT_NEAR_CRITICAL_DEGREES
        from app.privacy_logging import _SECURITY_HEADERS

        options, mode = schema_chart.OptionsInput, schema_inputs.ComputationModeInput
        defaults, mode_defaults = options(), mode()
        named = {
            field: (_choices(options, field), getattr(defaults, field))
            for field in ("house_system", "bounds_profile", "decan_profile", "triplicity_profile",
                          "aspect_set_profile", "aspect_orb_profile", "partile_profile")
        }
        ayanamsas = tuple(choice for choice in _choices(mode, "ayanamsa") if choice in domain_catalog.AYANAMSA_OPTIONS)
        named["ayanamsa"] = (ayanamsas, mode_defaults.ayanamsa)
        if set(ayanamsas) != set(domain_catalog.AYANAMSA_OPTIONS):
            raise RuntimeError("the request schema and the ayanamsa table name different ayanamsas")
        return {
            "named": named,
            "precisions": _choices(schema_chart.ChartRequest, "birth_time_precision"),
            "years": domain_catalog.PRODUCT_YEAR_RANGE,
            "max_chart_bytes": request_limits.MAX_CHART_REQUEST_BYTES,
            "general_pool": request_limits.MAX_HOSTED_REQUESTS_PER_WORKER,
            "compute_pool": request_limits.MAX_HOSTED_COMPUTE_REQUESTS_PER_WORKER,
            "transition_resolution_seconds": TRANSITION_RESOLUTION_SECONDS,
            "sect_band_degrees": SECT_NEAR_CRITICAL_DEGREES,
            "headers": dict(_SECURITY_HEADERS),
        }


def count(field: str) -> int:
    return len(product()["named"][field][0])


def default(field: str):
    return product()["named"][field][1]


def edge_hsts() -> str:
    """The Strict-Transport-Security value the edge template adds (one value)."""
    template = (ROOT / "deploy/staging/nginx-site.conf.template").read_text(encoding="utf-8")
    values = set(re.findall(r'add_header Strict-Transport-Security "([^"]+)" always;', template))
    if len(values) != 1:
        raise RuntimeError(f"the edge template sets Strict-Transport-Security to {sorted(values)}")
    return values.pop()


def ephemeris_header() -> tuple[str, str]:
    """(the JPL ephemeris, the creation date) every bundled .se1 file's header names."""
    found = set()
    files = sorted((ROOT / "backend/ephe").glob("*.se1"))
    for path in files:
        head = path.read_bytes()[:300].decode("latin-1")
        match = re.search(r"Created for Astrodienst in Switzerland (\d{4})/(\d\d)/(\d\d), "
                          r"based on JPL Ephemeris (DE\d+)\.", head)
        if match is None:
            raise RuntimeError(f"{path.name}: no creation line in the header")
        found.add((match.group(4), f"{match.group(1)}-{match.group(2)}-{match.group(3)}"))
    if not files or len(found) != 1:
        raise RuntimeError(f"the ephemeris files' headers disagree or are missing: {sorted(found)}")
    return found.pop()


def surface_count() -> int:
    surfaces = json.loads((ROOT / "frontend/surfaces.json").read_text(encoding="utf-8"))["surfaces"]
    if not surfaces:
        raise RuntimeError("frontend/surfaces.json lists no surface")
    return len(surfaces)


def catalogue_group_sizes() -> dict[str, int]:
    """Options per group in the calculator's options catalogue."""
    return dict(collections.Counter(options_catalogue()["options"]))
