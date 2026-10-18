"""Places whose birth records may be written in either of two civil times.

Xinjiang keeps two clocks: Beijing time (the official time of the People's
Republic, IANA Asia/Shanghai) and Xinjiang time (IANA Asia/Urumqi, two hours
behind).  A birth record from there may use either, and the place alone does not
say which, so a chart for such a place is computed only once the request names
the record's clock (``timezone.civil_time_basis``); the service never picks one.

Which catalogue rows are such places is derived from the catalogue's own fields,
not from a list of cities: a Chinese row whose zone is Xinjiang time.  The
province (admin1) is not used: the question is which clock a record keeps, and
GeoNames' admin1 codes have proved unreliable (Chinese rows carried other
provinces' codes until the catalogue producer's admin1 correction table).  The
Xinjiang places that GeoNames gives Beijing time are added by record;
tests/backend/test_civil_time_basis.py reads each back from the shipped
catalogue so the addition fails when the source moves, and fails when another
Xinjiang row on Beijing time appears unreviewed.

Manual coordinates have no catalogue row, and the service keeps no boundary
polygons, so the zone the person picked decides: a Xinjiang-time zone needs the
record's clock like a dual-time catalogue place, and answering Beijing time
sends Asia/Shanghai, which a manual request may therefore carry with the answer.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final, Literal

CivilTimeBasis = Literal["beijing_time", "xinjiang_time"]

# The zone each answer names.  The request carries both the answer and the zone,
# and the schema refuses a pair that disagrees.
CIVIL_TIME_BASIS_ZONES: Final[dict[str, str]] = {
    "beijing_time": "Asia/Shanghai",
    "xinjiang_time": "Asia/Urumqi",
}

DUAL_CIVIL_TIME_COUNTRY: Final = "CN"
# Asia/Kashgar is the tz database's backward link to Asia/Urumqi.
DUAL_CIVIL_TIME_CATALOGUE_ZONES: Final = frozenset({"Asia/Urumqi", "Asia/Kashgar"})
# (source, source_record_id) of Xinjiang rows whose catalogue zone is Beijing time.
DUAL_CIVIL_TIME_REVIEWED_RECORDS: Final[dict[tuple[str, str], str]] = {
    ("geonames_cities500", "8521718"): "Bole, Bortala, Xinjiang (44.89334, 82.06993)",
    ("geonames_cities500", "8521719"): "Alashankou, Bortala, Xinjiang (45.17018, 82.56981)",
    ("geonames_cities500", "1280244"): "Qilanbulak (依吞布拉克鎮), Ruoqiang, Bayingolin, Xinjiang (38.386, 90.15696)",
}


class CivilTimeBasisRequiredError(ValueError):
    code = "civil_time_basis_required"


class CivilTimeBasisNotApplicableError(ValueError):
    code = "civil_time_basis_not_applicable"


def is_dual_civil_time_place(
    *, source: str, source_record_id: str, country_code: str, timezone: str
) -> bool:
    return (
        country_code == DUAL_CIVIL_TIME_COUNTRY
        and timezone in DUAL_CIVIL_TIME_CATALOGUE_ZONES
    ) or (source, source_record_id) in DUAL_CIVIL_TIME_REVIEWED_RECORDS


def civil_time_basis_choices() -> list[dict[str, str]]:
    """The answers a place search offers for a dual-time place, Beijing time first."""

    return [
        {"civil_time_basis": basis, "iana_name": zone}
        for basis, zone in CIVIL_TIME_BASIS_ZONES.items()
    ]


def check_civil_time_basis(
    request, catalogue_record: Callable[[str, str], dict | None]
) -> None:
    """Refuse a request whose place keeps two clocks but names neither, and an
    answer where none applies.  Every chart route calls this one check, through
    ``place_catalog.check_request_places``, which has already refused an id the
    catalogue does not hold.

    A catalogue place is dual-time by its row.  Manual coordinates are by the
    picked zone: a Xinjiang-time zone requires the answer, and either answer's
    zone may carry it (the schema already ties each answer to its zone).

    ``catalogue_record(source, source_record_id)`` returns the row (at least
    ``country_code`` and ``timezone``).  A missing row is an error here, not a
    place that keeps one clock: deciding without the row would be a guess.
    """

    location = request.location
    basis = request.timezone.civil_time_basis
    zone = request.timezone.iana_name if request.timezone.mode == "iana" else None
    if location.location_source == "manual":
        check_zone_civil_time_basis(zone, basis)
        return
    record = catalogue_record(location.location_source, location.source_record_id)
    if record is None:
        raise LookupError("the catalogue holds no such record; refuse it before this check")
    required = is_dual_civil_time_place(
        source=location.location_source,
        source_record_id=location.source_record_id,
        country_code=record["country_code"],
        timezone=record["timezone"],
    )
    _refuse_unless_answered(required=required, applicable=required, basis=basis)


def check_zone_civil_time_basis(zone: str | None, basis: str | None) -> None:
    """The rule for a request that names a zone and no catalogue place: manual
    coordinates on a chart, and the time-conversion helper.  A Xinjiang-time zone
    requires the answer, and either answer's zone may carry it."""

    required = zone in DUAL_CIVIL_TIME_CATALOGUE_ZONES
    applicable = required or zone in CIVIL_TIME_BASIS_ZONES.values()
    _refuse_unless_answered(required=required, applicable=applicable, basis=basis)


def _refuse_unless_answered(*, required: bool, applicable: bool, basis: str | None) -> None:
    if required and basis is None:
        raise CivilTimeBasisRequiredError(
            "the birth place keeps Beijing time and Xinjiang time; the request must name one"
        )
    if not applicable and basis is not None:
        raise CivilTimeBasisNotApplicableError(
            "civil_time_basis applies only to a catalogue place marked dual-time "
            "or to manual coordinates on Beijing or Xinjiang time"
        )


METHOD_SOURCE_ENTRIES: Final[dict[str, dict]] = {
    "time/xinjiang_civil_time_basis": {
        "applies_to": "input_receipt.timezone.civil_time_basis",
        "basis_vocabulary": list(CIVIL_TIME_BASIS_ZONES),
        "zones": dict(CIVIL_TIME_BASIS_ZONES),
        "source": (
            "IANA tz database, file asia, comments on Asia/Urumqi: Luther Ma (2009-10-17, "
            "2014-04-22) on Beijing time and Xinjiang time both in use; Paul Eggert "
            "(2014-06-30): Xinjiang Time is officially recognized, no good records before 1986"
        ),
        "note": (
            "新疆同時使用北京時間（Asia/Shanghai）與新疆時間（Asia/Urumqi，慢 2 小時）。"
            "目錄裡國別為中國、時區為 Asia/Urumqi 的地點、三個目錄給北京時間的新疆地點"
            "（博樂、阿拉山口、依吞布拉克），以及手動輸入座標而時區為 Asia/Urumqi 或 Asia/Kashgar 的請求，"
            "計算前必須由使用者指明出生紀錄用哪一種；服務不預設。"
        ),
    },
}
