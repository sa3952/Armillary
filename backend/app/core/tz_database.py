"""Identify the IANA time zone database the running process is using.

The tz database is a calculation *input* like the ephemeris files, so the
Dossier records it beside the Swiss versions: IANA releases often *correct
historical offsets*, so the same request can convert to a different UTC.  The
version is not pinned (macOS supplies it, the container its image's tzdata);
recording it explains why a chart moved.

Resolution follows zoneinfo's own lookup order, so the receipt names the
database that actually converted the time, not whichever one is installed:

1. the first ``zoneinfo.TZPATH`` directory that holds the probe zone file —
   zoneinfo reads that directory before it ever consults the tzdata package; the
   version comes from its ``+VERSION`` file, else the ``# version`` line of its
   ``tzdata.zi`` (with any build variant such as ``rearguard``);
2. only when no TZPATH directory holds zone data, the ``tzdata`` PyPI package;
3. otherwise ``unavailable``, with a reason code, never a silent omission.

A version string counts only when it matches the IANA release grammar;
anything else is ``tz_database_version_unrecognized_format``.

The receipt names *which* file carried the version (``+VERSION`` or
``tzdata.zi``) but never *where* it is: a server's filesystem layout is not
part of a chart's provenance and does not belong in every response and export.
``source`` already says the TZPATH was read.
"""
from __future__ import annotations

import importlib.metadata
import re
import zoneinfo
from pathlib import Path
from typing import Final

# IANA release names are a four-digit year and one lowercase letter ("2026b").
# Two or three digits, an uppercase letter or trailing text are not releases,
# and accepting them would let a truncated or foreign read pass as verified.
_IANA_RELEASE: Final = re.compile(r"^\d{4}[a-z]$")
# tzdata.zi opens with "# version 2026c", optionally with a build variant suffix
# ("-rearguard" is what macOS ships).
_TZDATA_ZI_VERSION_LINE: Final = re.compile(r"^# version (\d{4}[a-z])(?:-([a-z]+))?$")
# This key decides which TZPATH directory zoneinfo would actually read.
_PROBE_KEY: Final = "UTC"
RESOLUTION_ORDER: Final = ("zoneinfo.TZPATH", "tzdata_package")
SOURCES: Final = ("zoneinfo_tzpath", "pypi_tzdata_package")
REASON_CODES: Final = (
    "tz_database_version_not_identifiable",
    "tz_database_version_unrecognized_format",
)


def _pypi_tzdata_versions() -> tuple[str | None, str] | None:
    """(IANA release, distribution version) of the installed tzdata package."""

    try:
        distribution_version = importlib.metadata.version("tzdata")
    except importlib.metadata.PackageNotFoundError:
        return None
    try:
        import tzdata  # type: ignore[import-untyped]
    except ImportError:
        return None
    iana_version = getattr(tzdata, "IANA_VERSION", None)
    if not isinstance(iana_version, str) or not _IANA_RELEASE.fullmatch(iana_version):
        return None, distribution_version
    return iana_version, distribution_version


def _tzpath_base_holding_zone_data() -> str | None:
    for base in zoneinfo.TZPATH:
        if (Path(base) / _PROBE_KEY).is_file():
            return str(base)
    return None


def _first_line(path: Path) -> str | None:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return handle.readline().strip()
    except OSError:
        return None


def _version_in_base(base: str) -> dict:
    """The version named by one TZPATH directory's +VERSION, else its tzdata.zi."""

    def entry(version, version_file, build_variant=None, unrecognized=False) -> dict:
        return {
            "version": version,
            "version_file": version_file,
            "build_variant": build_variant,
            "unrecognized": unrecognized,
        }

    unrecognized = False
    line = _first_line(Path(base) / "+VERSION")
    if line is not None:
        if _IANA_RELEASE.fullmatch(line):
            return entry(line, "+VERSION")
        unrecognized = True
    line = _first_line(Path(base) / "tzdata.zi")
    if line is not None:
        match = _TZDATA_ZI_VERSION_LINE.fullmatch(line)
        if match:
            return entry(match.group(1), "tzdata.zi", match.group(2))
        unrecognized = True
    return entry(None, None, unrecognized=unrecognized)


def resolve_tz_database_version() -> dict:
    """Return a receipt for the tz database, never an omission."""

    receipt = {
        "version": None,
        "source": None,
        "available": False,
        "reason_code": None,
        "resolution_order": list(RESOLUTION_ORDER),
        "probe_key": _PROBE_KEY,
        "version_file": None,
        "build_variant": None,
        "package_distribution_version": None,
        "shadowed_pypi_tzdata_version": None,
    }
    pypi = _pypi_tzdata_versions()
    base = _tzpath_base_holding_zone_data()
    if base is not None:
        found = _version_in_base(base)
        receipt.update(
            source=SOURCES[0],
            version_file=found["version_file"],
            build_variant=found["build_variant"],
            # Installed, but zoneinfo never reads it while TZPATH has the zone.
            shadowed_pypi_tzdata_version=pypi[0] if pypi else None,
        )
        if found["version"] is not None:
            receipt.update(version=found["version"], available=True)
        else:
            receipt["reason_code"] = REASON_CODES[1 if found["unrecognized"] else 0]
        return receipt
    if pypi is not None:
        iana_version, distribution_version = pypi
        receipt.update(
            source=SOURCES[1],
            package_distribution_version=distribution_version,
        )
        if iana_version is not None:
            receipt.update(version=iana_version, available=True)
        else:
            receipt["reason_code"] = REASON_CODES[1]
        return receipt
    # The conversion happened; we just cannot name the database.  A weaker
    # receipt, not a failed calculation, so reported rather than raised.
    receipt["reason_code"] = REASON_CODES[0]
    return receipt


# Resolved once at import: the database does not change inside a process.  A
# system update takes effect on the next restart, which is also when the
# recorded version changes, so the two stay consistent.
TZ_DATABASE: Final = resolve_tz_database_version()


METHOD_SOURCE_ENTRIES: Final[dict[str, dict]] = {
    "library_info": {
        "applies_to": "library_info",
        "note": (
            "兩者是不同的版本號：前者是 pip 安裝的 pyswisseph 套件版本，後者是其內建 "
            "Swiss Ephemeris C 函式庫自報的版本，數字格式相近但並非同一個值。"
            "tz_database 是本地時間換算所用的 IANA 時區資料庫版本，"
            "它不由本產品固定：macOS 由作業系統提供、容器由 image 提供，"
            "更新後同一組輸入可能換算出不同的 UTC。"
        ),
    },
}
