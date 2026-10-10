"""出生時間相關轉換：本地時間 -> UT（1972 年起為現代 UTC）-> 儒略日(UT/ET)，以及 ΔT、恆星時、黃赤交角、均時差。

時間尺度的稱呼依年代分四段（前三段依方法研究筆記，未經第三方核對）：1960 年前
沒有協調世界時，這裡換算出的是 UT1 估計；1960–1971 年的舊協調世界時秒長與今日
不同，Swiss Ephemeris 同樣把這段輸入當作 UT1；1972 年起才是以閏秒維持的現代 UTC；
約 2033-09-17 起，Swiss 判定內建閏秒表可能已過期，又把輸入與輸出都當作 UT1
（規則見下方 _swiss_stale_leap_table_rule）。
欄位名 `utc_time` 沿用既有契約，年代語意由 `time_scale_era`／`time_scale` 說明。
"""

from collections.abc import Callable
import datetime as dtmod
import functools
import math
from zoneinfo import ZoneInfo

import swisseph as swe

from ..schemas import DateTimeInput, TimezoneInput, exact_second_microseconds
from .trace import Trace


# --- ΔT ------------------------------------------------
#
# Swiss Ephemeris 2.10.03 swephlib.c calc_deltat(): before 1955-01-01 (JD 2435108.5)
# the default model is Stephenson, Morrison & Hohenkerk 2016 (swephexp.h
# SEMOD_DELTAT_DEFAULT), with a 1000-day linear transition from 1952-04-06; from
# 1955 Swiss interpolates its dt[] table (Astronomical Almanac K8-K9 and IERS;
# TABSTART 1620, TABEND 2028), where 2020.0–2023.0 are the last tabulated values and
# 2024–2028 are marked "Extrapolated values".  Past TABEND Swiss uses its long-term
# formula (the "before 1948" in swisseph.htm §2.1.2.6 is stale).  So for this
# product's 1900–1954 range ΔT comes from the model, not the table, and a chart
# dated today already carries a predicted ΔT, not a plain model value.
#
# For input from 1972 on, Swiss derives UT1 from UTC as TT − ΔT with TT fixed by
# the leap-second table: a ΔT error moves UT1 and every Earth-rotation quantity
# (sidereal time, houses, angles) and leaves body positions at TT alone.  Before
# 1972, and again once Swiss's stale-leap-table rule applies (from about
# 2033-09-17, see _swiss_stale_leap_table_rule), the input is taken as UT1, so the
# error moves TT and the body positions instead.  The receipt states which applies.
DELTA_T_SWISS_TABLE_LAST_MEASURED_YEAR = 2023
DELTA_T_SWISS_TABLE_END_YEAR = 2028
# Method research notes (not third-party verified): modern Earth-orientation
# measurements from 1962; seconds-scale extrapolation for the next decades,
# tens of seconds to minutes from 2050.
DELTA_T_MODERN_MEASUREMENT_START_YEAR = 1962
DELTA_T_FAR_EPOCH_YEAR = 2050
DELTA_T_STATUSES = (
    "historical_reconstruction",
    "measured_era_table",
    "swiss_table_prediction",
    "near_future_extrapolation",
    "far_epoch_extrapolation",
)
# Future uncertainty: Huber (2000) as NASA uses it for eclipse predictions
# (calibration 2005, Q = 0.058 ms²/yr, M = 2500 yr), checked against F. Espenak,
# "Uncertainty in Delta T", NASA GSFC eclipse.gsfc.nasa.gov/SEcat5/uncertainty.html;
# P. J. Huber, "Modeling the Length of Day and Extrapolating the Rotation of the
# Earth", in Astronomical Amusements: Papers in Honor of Jean Meeus, ed. Bònoli,
# De Meis & Panaino (Roma: IsIAO / Milano: Mimesis, 2000), pages not checked.  It is
# not an authoritative confidence interval, so it is reported as an order of
# magnitude with that basis named.  The 1 s (before 1900) and 0.1 s (from 1900)
# orders come from the same NASA page's Table 2, i.e. Stephenson & Houlden 1986;
# Morrison & Stephenson 2004 gives only σ < 1 s for 1900.
_HUBER_CALIBRATION_YEAR = 2005.0
_HUBER_Q = 0.058
_HUBER_M = 2500.0
_SIDEREAL_ARCSEC_PER_SECOND_OF_TIME = 15.041


def _huber_delta_t_sigma_seconds(decimal_year: float) -> float:
    years = decimal_year - _HUBER_CALIBRATION_YEAR
    return (
        365.25
        * years
        * math.sqrt(years * _HUBER_Q / 3.0 * (1.0 + years / _HUBER_M))
        / 1000.0
    )


def delta_t_model_receipt(jd_ut: float, swiss_time_input_semantics: str) -> dict:
    """Where this ΔT comes from, how well it is known, and what an error moves."""

    # Swiss indexes its table by this same decimal year (swephlib.c deltat_aa).
    decimal_year = 2000.0 + (jd_ut - 2451544.5) / 365.25
    if decimal_year < DELTA_T_MODERN_MEASUREMENT_START_YEAR:
        status = DELTA_T_STATUSES[0]
    elif decimal_year < DELTA_T_SWISS_TABLE_LAST_MEASURED_YEAR:
        status = DELTA_T_STATUSES[1]
    elif decimal_year <= DELTA_T_SWISS_TABLE_END_YEAR:
        status = DELTA_T_STATUSES[2]
    elif decimal_year < DELTA_T_FAR_EPOCH_YEAR:
        status = DELTA_T_STATUSES[3]
    else:
        status = DELTA_T_STATUSES[4]

    if decimal_year < 1900.0:
        uncertainty = 1.0
        basis = "stephenson_houlden_1986_via_nasa_espenak_table_2_about_1_second_before_1900"
    elif decimal_year < DELTA_T_MODERN_MEASUREMENT_START_YEAR:
        uncertainty = 0.1
        basis = "stephenson_houlden_1986_via_nasa_espenak_table_2_about_0_1_second_from_1900"
    elif decimal_year < DELTA_T_SWISS_TABLE_LAST_MEASURED_YEAR:
        uncertainty = None
        basis = (
            "measured_era_yearly_swiss_table_interpolation_error_not_quantified"
        )
    elif decimal_year <= DELTA_T_SWISS_TABLE_END_YEAR:
        uncertainty = 1.0
        basis = "research_note_Q104_order_of_magnitude_seconds_beyond_measured_values"
    else:
        uncertainty = _huber_delta_t_sigma_seconds(decimal_year)
        basis = (
            "huber_2000_extrapolation_calibration_2005_q_0_058_m_2500_"
            "per_research_note_Q104_not_an_authoritative_interval"
        )

    if swiss_time_input_semantics == "utc":
        propagation = {
            "input_scale": "utc",
            "affects": [
                "jd_ut",
                "sidereal_time_houses_and_angles",
                "horizontal_coordinates",
            ],
            "does_not_affect": ["jd_et", "body_positions"],
            "sidereal_arcsec_per_second_of_delta_t_error": (
                _SIDEREAL_ARCSEC_PER_SECOND_OF_TIME
            ),
        }
    else:
        propagation = {
            "input_scale": swiss_time_input_semantics,
            "affects": ["jd_et", "body_positions", "horizontal_coordinates"],
            "does_not_affect": ["jd_ut", "sidereal_time_houses_and_angles"],
            "sidereal_arcsec_per_second_of_delta_t_error": None,
        }

    return {
        "source": "swiss_ephemeris_internal_delta_t",
        "status": status,
        # The closed status set and the model's provenance are constant:
        # register entry time/delta_t_model.
        "source_ref": "time/delta_t_model",
        "accuracy_status": "not_independently_established_for_this_epoch",
        "decimal_year": decimal_year,
        "swiss_table_last_measured_year": DELTA_T_SWISS_TABLE_LAST_MEASURED_YEAR,
        "swiss_table_end_year": DELTA_T_SWISS_TABLE_END_YEAR,
        "far_epoch_warning_year": DELTA_T_FAR_EPOCH_YEAR,
        "uncertainty_order_seconds": uncertainty,
        "uncertainty_basis": basis,
        "uncertainty_verification": "not_third_party_verified",
        "error_propagation": propagation,
    }


# --- Sidereal time model --------------------------------------------
#
# swe_sidtime0 (swephlib.c) uses the IAU 2006 short-term expression only strictly
# between SIDT_LTERM_T0 = JD 2396758.5 (1850-01-01) and SIDT_LTERM_T1 = JD
# 2469807.5 (2050-01-01), and a long-term model with a constant offset outside.
# The two do not join: sidereal time, and with it the ARMC every house system
# and angle is built from, steps at both dates.  The step is measured from Swiss
# itself at import so the receipt cannot disagree with the library it describes.
SIDEREAL_TIME_SEGMENTS = ("iau_2006_short_term", "swiss_long_term")
_SIDEREAL_SWITCHES = (("1850-01-01", 2396758.5), ("2050-01-01", 2469807.5))
_SIDEREAL_RATE = 1.00273790935
_SIDEREAL_SWITCH_PROBE_DAYS = 1e-7


def _measured_sidereal_step_seconds(jd_ut: float) -> float:
    probe = _SIDEREAL_SWITCH_PROBE_DAYS
    return (swe.sidtime(jd_ut + probe) - swe.sidtime(jd_ut - probe)) * 3600.0 - (
        2.0 * probe * 86400.0 * _SIDEREAL_RATE
    )


SIDEREAL_SWITCH_POINTS = tuple(
    {
        "date": date_label,
        "jd_ut": switch_jd_ut,
        "measured_step_seconds": round(_measured_sidereal_step_seconds(switch_jd_ut), 4),
    }
    for date_label, switch_jd_ut in _SIDEREAL_SWITCHES
)


def sidereal_time_model_receipt(jd_ut: float) -> dict:
    short_term = _SIDEREAL_SWITCHES[0][1] < jd_ut < _SIDEREAL_SWITCHES[1][1]
    return {
        "segment": SIDEREAL_TIME_SEGMENTS[0 if short_term else 1],
        # The closed segment set and the source are constant: register entry
        # time/sidereal_time_model.
        "source_ref": "time/sidereal_time_model",
        "switch_points": [dict(point) for point in SIDEREAL_SWITCH_POINTS],
        "continuity": "discontinuous_at_switch_points",
        "consumers": [
            "gast_hours",
            "gmst_hours",
            "last_hours",
            "lmst_hours",
            "houses_and_angles_armc",
        ],
    }


# --- Time-scale era ------------------------------------
TIME_SCALE_ERAS = (
    "pre_utc_ut1_estimate",
    "early_utc_era_ut1_by_swiss_rule",
    "modern_leap_second_utc",
    "future_ut1_by_swiss_stale_leap_table_rule",
)
_UTC_ERA_START_JD_UT = 2436934.5  # 1960-01-01
_MODERN_UTC_START_JD_UT = 2441317.5  # 1972-01-01
# Every event timestamp's `utc_time` comes from swe.jdut1_to_utc and carries its
# own `time_scale` from TIME_SCALE_ERAS: before 1972 Swiss Ephemeris returns UT1
# for UTC, before 1960 coordinated time did not exist, and once Swiss judges its
# built-in leap-second table stale (from about 2033-09-17) it returns UT1 again.
# Sources: Swiss pre-1972 UT1 and stale-leap-table rules; 1960: McCarthy (USNO),
# CCTF/09-32 (BIPM 2009) pp.2-7, IANA tz theory ('UTC was not defined until
# 1960'); 1972: IERS TAI-UTC, ITU-R TF.460-6.  The Swiss manual's "UTC
# introduced 1961" (Programming interface 2.10 §9.3, p.43) is BIH coordination;
# 1960 and 1961 are computed as UT1 either way.  OUTPUT_CONTRACT.md states the
# rule once instead of every event module repeating it.
_CIVIL_SCALE_LABELS = {
    "pre_utc_ut1_estimate": "UT1 估計",
    "early_utc_era_ut1_by_swiss_rule": "UT1（舊協調世界時期間）",
    "modern_leap_second_utc": "UTC",
    "future_ut1_by_swiss_stale_leap_table_rule": "UT1（Swiss 遠期規則）",
}
_CIVIL_SCALE_NOTES = {
    "pre_utc_ut1_estimate": (
        "1960 年前沒有協調世界時；此處換算出的是依 Swiss Ephemeris 1972 年前規則"
        "視為 UT1 的估計值。"
    ),
    "early_utc_era_ut1_by_swiss_rule": (
        "1960–1971 年舊協調世界時的秒長與今日不同；Swiss Ephemeris 把這段輸入視為 UT1。"
    ),
    "modern_leap_second_utc": "",
    "future_ut1_by_swiss_stale_leap_table_rule": (
        "Swiss Ephemeris 判定內建閏秒表可能已過期（其 ΔT 模型減 TAI−UTC 再減 32.184 秒"
        "達 1 秒以上），自約 2033-09-17 起把輸入與輸出都當作 UT1；此處的時刻是 UT1，"
        "不是 UTC。切換瞬間時刻約有 1 秒的不連續。"
    ),
}


# --- Swiss stale-leap-table rule --------------------
#
# Swiss Ephemeris 2.10.03 swedate.c: from 1972 on, swe_utc_to_jd() takes its input
# as UT1 instead of UTC when ΔT − (TAI−UTC) − 32.184 s ≥ 1 s at 0h of the input
# date, i.e. when its ΔT model implies the bundled leap-second table must be out
# of date; swe_jdut1_to_utc() applies the same test at the instant itself.  With
# the bundled table (TAI−UTC = 37 s since 2017-01-01) the input switch falls at
# 2033-09-17 00:00 (whole-day test) and the output switch at about 2033-09-16
# 15:59:26 UT1 (instant test), each with a jump of about one second.  The predicates re-derive Swiss's own test from Swiss's own ΔT
# and leap count; tests pin them to Swiss's actual behaviour around the switch.
_SWISS_LEAP_COUNT_REFERENCE_DATE = (2026, 1, 1)


@functools.lru_cache(maxsize=1)
def _swiss_tai_minus_utc_seconds() -> int:
    """TAI−UTC in Swiss's bundled table after its last leap second."""

    year, month, day = _SWISS_LEAP_COUNT_REFERENCE_DATE
    jd_et, _jd_ut = swe.utc_to_jd(year, month, day, 0, 0, 0.0, swe.GREG_CAL)
    return round((jd_et - swe.julday(year, month, day, 0.0)) * 86400.0 - 32.184)


def _swiss_stale_leap_table_rule(jd_ut: float) -> bool:
    if jd_ut < swe.julday(*_SWISS_LEAP_COUNT_REFERENCE_DATE, 0.0):
        return False
    delta_t_seconds = swe.deltat_ex(jd_ut, swe.FLG_SWIEPH) * 86400.0
    return delta_t_seconds - _swiss_tai_minus_utc_seconds() - 32.184 >= 1.0


def swiss_takes_input_as_future_ut1(year: int, month: int, day: int) -> bool:
    """swe_utc_to_jd's test, evaluated at 0h of the input date as Swiss does."""

    return _swiss_stale_leap_table_rule(swe.julday(year, month, day, 0.0))


def time_scale_for_jd_ut(jd_ut: float) -> str:
    """The era a timestamp belongs to, by its own instant (closed set).

    Timestamps are rendered by swe_jdut1_to_utc, so the future rule is applied at
    the instant itself, as that function does.
    """

    if jd_ut < _UTC_ERA_START_JD_UT:
        return TIME_SCALE_ERAS[0]
    if jd_ut < _MODERN_UTC_START_JD_UT:
        return TIME_SCALE_ERAS[1]
    if _swiss_stale_leap_table_rule(jd_ut):
        return TIME_SCALE_ERAS[3]
    return TIME_SCALE_ERAS[2]


MICROSECONDS_PER_SECOND = 1_000_000
_LABEL_MICROSECONDS = 1_000


def civil_time_label(
    year: int,
    month: int,
    day: int,
    hour: int,
    minute: int,
    second_microseconds: int,
    *,
    separator: str = " ",
) -> str:
    """The one quantizer of a printed civil time: milliseconds, truncated.

    Every decision about the instant (clock gap, fold, leap second, date) is
    made before this on exact values; the label only shortens the seconds.  It
    truncates and never carries, so a label cannot name a later minute, day or
    year than its instant, and a second of 60 (inside a positive leap second)
    stays 60 rather than becoming the next minute's 00.
    """

    whole, fraction = divmod(second_microseconds, MICROSECONDS_PER_SECOND)
    return (
        f"{year:04d}-{month:02d}-{day:02d}{separator}{hour:02d}:{minute:02d}:"
        f"{whole:02d}.{fraction // _LABEL_MICROSECONDS:03d}"
    )


# A Julian day near 2.45e6 resolves about 40 µs, so Swiss can split an instant
# made from a whole second as 59.99998659 s.  The instant is rounded to the
# nearest millisecond by moving it half a millisecond before Swiss splits it:
# Swiss then carries minutes, days and leap seconds itself (an instant inside
# a leap second comes back as second 60.x), and the label only truncates.
_HALF_MILLISECOND_DAYS = 0.0005 / 86400.0


def jd_ut_to_iso_utc(jd_ut: float) -> str:
    year, month, day, hour, minute, second = swe.jdut1_to_utc(
        jd_ut + _HALF_MILLISECOND_DAYS, swe.GREG_CAL
    )
    millis = math.floor(second * 1000.0)
    return civil_time_label(
        year, month, day, hour, minute, millis * _LABEL_MICROSECONDS, separator="T"
    ) + "Z"


class NonexistentLocalTimeError(ValueError):
    """Raised when an IANA-zone wall-clock time has no corresponding UTC instant."""

    code = "nonexistent_local_time"


class AmbiguousLocalTimeChoiceRequiredError(ValueError):
    """Raised when a repeated civil time or hour lacks an explicit fold."""

    code = "ambiguous_local_time_choice_required"


def _required_utc_offset_hours(value: dtmod.datetime) -> float:
    offset = value.utcoffset()
    if offset is None:
        raise RuntimeError("timezone-aware datetime has no UTC offset")
    return offset.total_seconds() / 3600.0


# Two independent axes.
# Whether the offset was resolved, and whether that resolution can be trusted
# historically.  The IANA project itself says most pre-1970 entries come from
# unreliable sources (theory.html, "Accuracy of the tz database").  Closed sets.
OFFSET_RESOLUTION_STATUSES = (
    "iana_resolved",
    "iana_resolved_by_fold_choice",
    "fixed_offset_supplied",
)
OFFSET_HISTORICAL_VERIFICATION_STATUSES = (
    "pre_1970_database_inferred_not_verified",
    "post_1970_database_rule",
    "not_applicable_fixed_offset",
)
TZDB_RELIABLE_FROM_UTC = dtmod.datetime(1970, 1, 1, tzinfo=dtmod.timezone.utc)
TZDB_PRE_1970_SOURCE = (
    "IANA tz database, theory.html, 'Accuracy of the tz database': most pre-1970 "
    "entries come from unreliable sources"
)


def offset_status(timezone_mode: str, utc_dt: dtmod.datetime, ambiguous: bool) -> dict:
    if timezone_mode != "iana":
        return {
            "resolution_status": "fixed_offset_supplied",
            "historical_verification_status": "not_applicable_fixed_offset",
        }
    return {
        "resolution_status": (
            "iana_resolved_by_fold_choice" if ambiguous else "iana_resolved"
        ),
        "historical_verification_status": (
            "pre_1970_database_inferred_not_verified"
            if utc_dt < TZDB_RELIABLE_FROM_UTC
            else "post_1970_database_rule"
        ),
    }


def _offset_span_label(offset_hours: float, other_offset_hours: float) -> str:
    """How far apart the two readings of a repeated wall-clock time are."""

    # Seconds, not minutes: an LMT-to-standard change such as Shanghai's
    # +08:05:43 to +08:00 repeats 5 min 43 s, which minutes would round away.
    seconds = round(abs(offset_hours - other_offset_hours) * 3600)
    minutes, secs = divmod(seconds, 60)
    hours, mins = divmod(minutes, 60)
    parts = [
        f"{value} {unit}"
        for value, unit in ((hours, "小時"), (mins, "分鐘"), (secs, "秒"))
        if value
    ]
    return " ".join(parts) or "0 秒"


def _utc_offset_text(offset_hours: float) -> str:
    """UTC±HH:MM, with :SS only when the offset has seconds (historical LMT)."""

    total = round(offset_hours * 3600)
    sign = "-" if total < 0 else "+"
    minutes, secs = divmod(abs(total), 60)
    hours, mins = divmod(minutes, 60)
    text = f"UTC{sign}{hours:02d}:{mins:02d}"
    return f"{text}:{secs:02d}" if secs else text


def _input_local_label(dt_input: DateTimeInput) -> str:
    return civil_time_label(
        dt_input.year,
        dt_input.month,
        dt_input.day,
        dt_input.hour,
        dt_input.minute,
        exact_second_microseconds_or_raise(dt_input.second),
    )


def exact_second_microseconds_or_raise(second: float) -> int:
    microseconds = exact_second_microseconds(second)
    if microseconds is None:
        raise ValueError("second finer than a microsecond reached the time step")
    return microseconds


def _to_utc_datetime(
    dt_input: DateTimeInput,
    tz_input: TimezoneInput,
    *,
    require_explicit_fold: bool = False,
) -> tuple[dtmod.datetime, float, str, str | None]:
    # The exact microseconds, never a rounded float: the gap and fold
    # decisions below must see the instant that was asked for.  Only the second
    # 60 of a leap second carries, into the next minute, which
    # compute_time_conversion steps back before Swiss reads it.
    naive = dtmod.datetime(
        dt_input.year, dt_input.month, dt_input.day,
        dt_input.hour, dt_input.minute, 0, 0,
    ) + dtmod.timedelta(microseconds=exact_second_microseconds_or_raise(dt_input.second))

    dst_warning = None

    if tz_input.mode == "iana":
        zone_name = tz_input.iana_name
        if zone_name is None:
            raise ValueError("IANA timezone name is required")
        tz = ZoneInfo(zone_name)
        fold = tz_input.fold
        local_dt = naive.replace(tzinfo=tz, fold=fold)
        utc_dt = local_dt.astimezone(dtmod.timezone.utc)
        offset_hours = _required_utc_offset_hours(local_dt)
        tz_label = zone_name

        # PEP 495：同一本地時間在兩個 fold 下若解出不同 UTC 偏移，代表這個本地時間
        # 落在 DST 轉換附近（模糊或不存在），需要進一步分辨是哪一種、並讓使用者知道。
        alt_local_dt = naive.replace(tzinfo=tz, fold=1 - fold)
        offsets_differ = local_dt.utcoffset() != alt_local_dt.utcoffset()

        if offsets_differ:
            # 把選定 fold 算出的 UTC 轉回本地時間；若對不回原本輸入的「完整 datetime」，
            # 代表這個本地時間根本不存在（DST 春季跳錶的空隙），而非單純模糊。
            # 必須比對完整 datetime 而非只比 (hour, minute)：像 Pacific/Apia 2011-12-30
            # 這種整天被跳過的跨換日線變更，時分會恰好相同、只有日期差一天，
            # 只比時分會把「不存在」誤判成「模糊」並給出錯誤的 fold 建議。
            round_trip = utc_dt.astimezone(tz)
            if round_trip.replace(tzinfo=None) != naive:
                alternative_utc = alt_local_dt.astimezone(dtmod.timezone.utc)
                alternative_round_trip = alternative_utc.astimezone(tz)
                raise NonexistentLocalTimeError(
                    f"此本地時間在 {tz_label} 因日光節約時間或時區規則變更而不存在（該時鐘從未指向 "
                    f"{naive.strftime('%Y-%m-%d %H:%M')}）。fold=0 與 fold=1 只會強制正規化成 "
                    f"{round_trip.strftime('%Y-%m-%d %H:%M %Z')} 或 "
                    f"{alternative_round_trip.strftime('%Y-%m-%d %H:%M %Z')}，兩者都不是原輸入。"
                    "請改正出生時間；若出生紀錄明確記載 UTC 偏移，才改用 fixed_offset。"
                )
            else:
                if (
                    require_explicit_fold
                    and "fold" not in tz_input.model_fields_set
                ):
                    raise AmbiguousLocalTimeChoiceRequiredError(
                        f"{tz_label} 的這個民用時刻出現兩次；必須明確提供 timezone.fold=0 或 1，"
                        "不能由系統替使用者猜測。"
                    )
                alt_offset_hours = _required_utc_offset_hours(alt_local_dt)
                # 重複多久、為什麼重複都由兩個偏移導出，不寫死「日光節約」「一小時」「秋季」：
                # Lord Howe 2024-04-07 只重複 30 分鐘，臺北 1945-09-21 是標準時變更，
                # Kwajalein 1969-09-30 重複約 23 小時。
                dst_warning = (
                    f"此本地時間在 {tz_label} 為時區偏移改變造成的模糊時刻（例如日光節約時間結束或標準時變更；"
                    f"同一本地時間對應兩個 UTC 時刻，兩次相差 {_offset_span_label(offset_hours, alt_offset_hours)}）。"
                    f"已採用 fold={fold}，對應 {_utc_offset_text(offset_hours)}；"
                    f"另一種解讀為 {_utc_offset_text(alt_offset_hours)}。如果您知道確切是哪一次，"
                    f"請在請求中指定 timezone.fold={1 - fold} 以取得另一種結果。"
                )
    else:
        fixed_offset_hours = tz_input.utc_offset_hours
        if fixed_offset_hours is None:
            raise ValueError("fixed UTC offset is required")
        offset_hours = fixed_offset_hours
        local_dt = naive.replace(tzinfo=dtmod.timezone(dtmod.timedelta(hours=offset_hours)))
        utc_dt = local_dt.astimezone(dtmod.timezone.utc)
        tz_label = _utc_offset_text(offset_hours)

    return utc_dt, offset_hours, tz_label, dst_warning


def compute_time_conversion(
    dt_input,
    tz_input,
    location,
    trace: Trace,
    *,
    # Fail closed: a repeated wall-clock time is refused unless the caller
    # resolves the fold itself and says so.
    require_explicit_fold: bool = True,
    input_semantics: str = "exact_birth_time",
) -> dict:
    utc_dt, offset_hours, tz_label, dst_warning = _to_utc_datetime(
        dt_input,
        tz_input,
        require_explicit_fold=require_explicit_fold,
    )

    if dst_warning:
        trace.add("⚠ 民用時刻重複（時區偏移改變）警告", note=dst_warning)

    leap_second = dt_input.second == 60
    if leap_second:
        swiss_input = utc_dt - dtmod.timedelta(minutes=1)
        utc_microseconds = 60 * MICROSECONDS_PER_SECOND
    else:
        swiss_input = utc_dt
        utc_microseconds = utc_dt.second * MICROSECONDS_PER_SECOND + utc_dt.microsecond
    utc_sec = utc_microseconds / MICROSECONDS_PER_SECOND
    utc_label = civil_time_label(
        swiss_input.year, swiss_input.month, swiss_input.day,
        swiss_input.hour, swiss_input.minute, utc_microseconds,
    )
    swiss_time_input_semantics = (
        "ut1_before_1972_swiss_rule"
        if swiss_input.year < 1972
        else "ut1_future_leap_table_stale_swiss_rule"
        if swiss_takes_input_as_future_ut1(
            swiss_input.year, swiss_input.month, swiss_input.day
        )
        else "utc"
    )
    jd_et, jd_ut = swe.utc_to_jd(
        swiss_input.year, swiss_input.month, swiss_input.day,
        swiss_input.hour, swiss_input.minute, utc_sec,
        swe.GREG_CAL,
    )

    # The chart instant's era follows how Swiss actually read the input; event
    # timestamps follow the output rule at their own instants.
    time_scale_era = {
        "ut1_future_leap_table_stale_swiss_rule": TIME_SCALE_ERAS[3],
        "utc": TIME_SCALE_ERAS[2],
    }.get(swiss_time_input_semantics) or time_scale_for_jd_ut(jd_ut)
    civil_scale_label = _CIVIL_SCALE_LABELS[time_scale_era]
    trace.add(
        f"本地時間 -> {civil_scale_label}",
        formula=f"{civil_scale_label} = 本地時間 - 時區偏移",
        inputs={
            "本地時間": _input_local_label(dt_input),
            "時區": tz_label,
            "時區偏移(小時)": round(offset_hours, 4),
        },
        result={f"{civil_scale_label}時間": utc_label},
        note=_CIVIL_SCALE_NOTES[time_scale_era],
    )

    ut1_input = swiss_time_input_semantics != "utc"
    trace.add(
        (
            "UT1-like input -> 儒略日 (1972年前 Swiss 規則)"
            if swiss_time_input_semantics == "ut1_before_1972_swiss_rule"
            else "UT1-like input -> 儒略日 (Swiss 遠期規則：閏秒表可能過期)"
            if ut1_input
            else "UTC -> 儒略日 (swe.utc_to_jd)"
        ),
        formula=f"JD_ET, JD_UT = swe.utc_to_jd({'UT1' if ut1_input else 'UTC'}年,月,日,時,分,秒, 格里曆)",
        inputs={("UT1-like input" if ut1_input else "UTC"): utc_label},
        result={"JD(UT)": jd_ut, "JD(ET/TT)": jd_et},
        note=(
            "Swiss Ephemeris在1972年前把utc_to_jd輸入視為UT1；"
            "本欄不宣稱存在當代UTC leap-second語義。"
            if swiss_time_input_semantics == "ut1_before_1972_swiss_rule"
            else _CIVIL_SCALE_NOTES[TIME_SCALE_ERAS[3]]
            if ut1_input
            else ""
        ),
    )

    delta_t_seconds = (jd_et - jd_ut) * 86400.0
    trace.add(
        "地球時與世界時之差 ΔT",
        formula="ΔT(秒) = (JD_ET - JD_UT) * 86400",
        inputs={"JD(ET)": jd_et, "JD(UT)": jd_ut},
        result={"ΔT(秒)": round(delta_t_seconds, 4)},
    )

    ecl_nut, retflag = swe.calc_ut(jd_ut, swe.ECL_NUT, 0)
    true_obliquity, mean_obliquity, nut_lon, nut_obl = ecl_nut[0], ecl_nut[1], ecl_nut[2], ecl_nut[3]
    trace.add(
        "黃赤交角與章動 (swe.calc_ut ECL_NUT)",
        formula="ECL_NUT 回傳 [真黃赤交角, 平黃赤交角, 黃經章動, 交角章動]",
        inputs={"JD(UT)": jd_ut},
        result={
            "真黃赤交角ε(度)": true_obliquity,
            "平黃赤交角(度)": mean_obliquity,
            "黃經章動(度)": nut_lon,
            "交角章動(度)": nut_obl,
        },
    )

    # swe.sidtime() 包含章動，回傳的是 Greenwich apparent sidereal time (GAST)，
    # 不是名稱含混的「GST」。平均恆星時則以 sidtime0(..., mean_obliquity, 0)
    # 明確移除章動。
    sidereal_model = sidereal_time_model_receipt(jd_ut)
    gast_hours = swe.sidtime(jd_ut)
    gmst_hours = swe.sidtime0(jd_ut, mean_obliquity, 0.0)
    last_hours = (gast_hours + location.longitude / 15.0) % 24.0
    lmst_hours = (gmst_hours + location.longitude / 15.0) % 24.0
    trace.add(
        "平均／視恆星時 (Sidereal Time)",
        formula=(
            "GAST = swe.sidtime(JD_UT)；GMST = swe.sidtime0(JD_UT, 平黃赤交角, 0)；"
            "LAST/LMST = GAST/GMST + 東經/15"
        ),
        inputs={
            "JD(UT)": jd_ut,
            "地理經度(東正西負)": location.longitude,
            "Swiss 恆星時模型段": sidereal_model["segment"],
        },
        result={
            "GAST(小時)": gast_hours,
            "GMST(小時)": gmst_hours,
            "LAST(小時)": last_hours,
            "LMST(小時)": lmst_hours,
        },
        note=(
            "Swiss 在 1850-01-01 與 2050-01-01 之間用 IAU 2006 短期式，之外改用長期"
            "模型（本次："
            f"{sidereal_model['segment']}）；兩者在切換日不連續，實測跳動見 "
            "time.sidereal_time_model.switch_points，宮位與角點的 ARMC 同受影響。"
        ),
    )

    eq_of_time_days = swe.time_equ(jd_ut)
    eq_of_time_minutes = eq_of_time_days * 1440.0
    lmt_offset_hours = location.longitude / 15.0
    apparent_solar_offset_hours = lmt_offset_hours + eq_of_time_minutes / 60.0
    true_solar_dt = utc_dt + dtmod.timedelta(hours=apparent_solar_offset_hours)
    trace.add(
        "均時差與真太陽時（僅供參考，不影響本次計算）",
        formula="真太陽時 = UTC + 經度/15(小時) + 均時差；均時差 = swe.time_equ(JD_UT) * 1440 分鐘",
        inputs={"JD(UT)": jd_ut, "地理經度": location.longitude},
        result={
            "均時差(分鐘)": round(eq_of_time_minutes, 4),
            "真太陽時(參考)": true_solar_dt.strftime("%Y-%m-%d %H:%M:%S"),
        },
        note=(
            "此為輔助資訊，出生時刻以使用者輸入之精確時鐘時間為準"
            if input_semantics == "exact_birth_time"
            else "此為輔助資訊；本次時鐘值只是代表計算錨點，不是實際出生時刻"
        ),
    )

    return {
        "input_local_time": _input_local_label(dt_input),
        "input_semantics": input_semantics,
        "timezone_label": tz_label,
        "utc_offset_hours": offset_hours,
        "offset_status": offset_status(tz_input.mode, utc_dt, dst_warning is not None),
        "utc_time": utc_label,
        "swiss_time_input_semantics": swiss_time_input_semantics,
        "leap_second_input": leap_second,
        "jd_ut": jd_ut,
        "jd_et": jd_et,
        "delta_t_seconds": delta_t_seconds,
        "delta_t_model": delta_t_model_receipt(jd_ut, swiss_time_input_semantics),
        "time_scale_era": time_scale_era,
        "sidereal_time_model": sidereal_model,
        "gast_hours": gast_hours,
        "gmst_hours": gmst_hours,
        "last_hours": last_hours,
        "lmst_hours": lmst_hours,
        "true_obliquity": true_obliquity,
        "mean_obliquity": mean_obliquity,
        "nutation_longitude": nut_lon,
        "nutation_obliquity": nut_obl,
        "equation_of_time_minutes": eq_of_time_minutes,
        "apparent_solar_time": true_solar_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "ecl_nut_retflag": retflag,
        "dst_warning": dst_warning,
    }


# --- date_only anchor and representative samples ---------

DATE_ONLY_ANCHOR_POLICY = "local_noon_or_first_existing_instant_after"
DATE_ONLY_NOON_POLICY = "local_noon_computational_anchor_not_birth_time"
_REPRESENTATIVE_POLICY = {
    "exact_birth_time": "exact_input",
    "representative_midpoint_not_exact_birth_time": "midpoint_minute_30",
    "representative_first_available_probe_not_exact_birth_time": (
        "representative_first_available_probe_not_exact_birth_time"
    ),
    "representative_computational_anchor_not_birth_time": DATE_ONLY_NOON_POLICY,
}


def representative_policy(input_semantics: str, date_only_anchor: dict | None) -> str:
    """The one producer of the representative anchor's policy label.

    The label names the anchor the time step actually used, never one inferred
    from the precision: an approximate hour without a real HH:30 is computed at
    its first real probe, and a date_only day whose noon the clock skipped is
    computed at the first existing instant after it, which is not local noon.
    The Dossier policy and the date_only sensitivity semantics both read it.
    """

    if date_only_anchor is not None and date_only_anchor["shifted_by_clock_gap"]:
        return DATE_ONLY_ANCHOR_POLICY
    return _REPRESENTATIVE_POLICY[input_semantics]
REPRESENTATIVE_SAMPLE_ROLES = ("interval_start", "representative_anchor", "interval_end")


def _existing_utc_instants(dt_input, tz_input, naive: dtmod.datetime) -> list:
    """Every UTC instant whose wall-clock label in this zone is ``naive``.

    Existence is decided by the round-trip check `_to_utc_datetime` already
    applies to exact and approximate-hour input, not a second rule.
    """

    datetime_value = dt_input.model_copy(
        update={
            "year": naive.year,
            "month": naive.month,
            "day": naive.day,
            "hour": naive.hour,
            "minute": naive.minute,
            "second": float(naive.second),
        }
    )
    folds = (0, 1) if tz_input.mode == "iana" else (tz_input.fold,)
    found: list = []
    for fold in folds:
        timezone_value = tz_input.model_copy(update={"fold": fold})
        try:
            utc_value, _offset, _label, _warning = _to_utc_datetime(
                datetime_value, timezone_value
            )
        except NonexistentLocalTimeError:
            continue
        if utc_value not in found:
            found.append(utc_value)
    return sorted(found)


def utc_datetime_to_jd_ut(utc_value: dtmod.datetime) -> float:
    """JD(UT) of an aware UTC datetime through swe.utc_to_jd (Gregorian)."""

    return swe.utc_to_jd(
        utc_value.year,
        utc_value.month,
        utc_value.day,
        utc_value.hour,
        utc_value.minute,
        utc_value.second + utc_value.microsecond / 1_000_000,
        swe.GREG_CAL,
    )[1]


def _wall_label(utc_value: dtmod.datetime, tz_input) -> tuple[dtmod.datetime, int]:
    if tz_input.mode == "iana":
        local = utc_value.astimezone(ZoneInfo(tz_input.iana_name))
        return local.replace(tzinfo=None), local.fold
    offset = dtmod.timedelta(hours=tz_input.utc_offset_hours)
    return (utc_value + offset).replace(tzinfo=None), 0


def _choose_instant(instants: list, fold_preference: int | None, *, latest: bool):
    if fold_preference is not None and len(instants) == 2:
        return instants[fold_preference]
    return instants[-1] if latest else instants[0]


def first_second_where(
    low: dtmod.datetime,
    high: dtmod.datetime,
    holds: Callable[[dtmod.datetime], bool],
) -> dtmod.datetime:
    """The first whole UTC second in (low, high] at which `holds` is true.

    `holds` must be false at `low`, true at `high` and change once between
    them.  The local-time gap search below and the sensitivity pass's offset
    schedule both locate a clock change this way.
    """

    one_second = dtmod.timedelta(seconds=1)
    while high - low > one_second:
        middle = (low + (high - low) / 2).replace(microsecond=0)
        if middle <= low:
            middle = low + one_second
        if holds(middle):
            high = middle
        else:
            low = middle
    return high


def _first_existing_instant_at_or_after(
    dt_input, tz_input, naive: dtmod.datetime, fold_preference: int | None = None
) -> dtmod.datetime:
    instants = _existing_utc_instants(dt_input, tz_input, naive)
    if instants:
        return _choose_instant(instants, fold_preference, latest=False)
    # Only an IANA zone has gaps.  Inside one, fold=1 applies the offset after
    # the transition (an instant before it) and fold=0 the offset before (an
    # instant after it); the transition lies between, and the wall label rises
    # monotonically across it, so bisection on whole seconds finds it.
    zone = ZoneInfo(tz_input.iana_name)
    low, high = sorted(
        naive.replace(tzinfo=zone, fold=fold).astimezone(dtmod.timezone.utc)
        for fold in (0, 1)
    )
    return first_second_where(
        low, high, lambda moment: _wall_label(moment, tz_input)[0] >= naive
    )


def _last_existing_instant_at_or_before(
    dt_input, tz_input, naive: dtmod.datetime, fold_preference: int | None = None
) -> dtmod.datetime:
    instants = _existing_utc_instants(dt_input, tz_input, naive)
    if instants:
        return _choose_instant(instants, fold_preference, latest=True)
    return _first_existing_instant_at_or_after(
        dt_input, tz_input, naive
    ) - dtmod.timedelta(seconds=1)


_ONE_SECOND = dtmod.timedelta(seconds=1)
_OFFSET_SCAN_STEP = dtmod.timedelta(minutes=1)
# Every UTC instant a wall-clock date or hour can label lies within a day of
# it: no zone's offset, LMT included, reaches 24 h.
_LABEL_WINDOW_MARGIN = dtmod.timedelta(hours=26)


def utc_offset_changes(
    zone: ZoneInfo,
    start_utc: dtmod.datetime,
    end_utc: dtmod.datetime,
) -> list[dtmod.datetime]:
    """UTC instants in (start_utc, end_utc] at which the zone's offset changes.

    A one-minute scan, each change refined to the whole second.  Two changes
    that cancel inside one scan minute would not be seen; the method statement
    says the schedule was located this way instead of claiming the zone's list.
    """

    def offset(moment: dtmod.datetime):
        return moment.astimezone(zone).utcoffset()

    changes: list[dtmod.datetime] = []
    left, left_offset = start_utc, offset(start_utc)
    while left < end_utc:
        right = min(left + _OFFSET_SCAN_STEP, end_utc)
        right_offset = offset(right)
        if right_offset != left_offset:
            def changed(moment: dtmod.datetime) -> bool:
                return offset(moment) != left_offset  # called before left_offset moves on

            changes.append(first_second_where(left, right, changed))
        left, left_offset = right, right_offset
    return changes


def _offset_segments(tz_input, start_utc: dtmod.datetime, end_utc: dtmod.datetime) -> list:
    """[(segment start, segment end, UTC offset)] tiling [start_utc, end_utc)."""

    if tz_input.mode != "iana":
        return [(start_utc, end_utc, dtmod.timedelta(hours=tz_input.utc_offset_hours))]
    zone = ZoneInfo(tz_input.iana_name)
    edges = [start_utc, *utc_offset_changes(zone, start_utc, end_utc), end_utc]
    return [
        (left, right, left.astimezone(zone).utcoffset())
        for left, right in zip(edges, edges[1:])
        if left < right
    ]


def civil_date_spans(tz_input, date: dtmod.date) -> list:
    """Every maximal UTC stretch [start, end) the zone labels with ``date``.

    A civil date need not be one stretch.  America/St_Johns set its clock back
    at 00:01 on 2005-10-30, so 2005-10-29 is a full day plus 23:01-23:59:59 again
    a minute later, and 2005-10-30 is one minute, a 59-minute break, then a
    full day.  Inside each constant-offset segment the labels run with UTC, so
    the date there is one interval; adjacent pieces are merged.
    """

    midnight = dtmod.datetime(date.year, date.month, date.day, tzinfo=dtmod.timezone.utc)
    next_midnight = midnight + dtmod.timedelta(days=1)
    spans: list[list[dtmod.datetime]] = []
    for left, right, offset in _offset_segments(
        tz_input, midnight - _LABEL_WINDOW_MARGIN, next_midnight + _LABEL_WINDOW_MARGIN
    ):
        start = max(left, midnight - offset)
        end = min(right, next_midnight - offset)
        if start >= end:
            continue
        if spans and spans[-1][1] == start:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    return [(start, end) for start, end in spans]


def resolve_civil_day(dt_input, tz_input) -> dict:
    """The requested civil date as its UTC stretches, to the whole second.

    ``spans`` are what the zone labels with the date (``civil_date_spans``);
    the duration is their sum, the day's first second the first span's start
    and its last second the last span's end minus one second.  Neither "the next
    date's first midnight" nor "end minus start" holds for a date the clock
    returns to.
    """

    date = dtmod.date(dt_input.year, dt_input.month, dt_input.day)
    spans = civil_date_spans(tz_input, date)
    if not spans:
        raise NonexistentLocalTimeError(
            "這個民用日期在所選時區因時區規則變更整天被跳過，當天沒有任何真實存在的本地時刻。"
        )
    return {
        "spans": spans,
        "start_utc": spans[0][0],
        "end_exclusive_utc": spans[-1][1],
        "last_second_utc": spans[-1][1] - _ONE_SECOND,
        "duration_seconds": sum((end - start).total_seconds() for start, end in spans),
    }


def civil_day_receipt(civil_day: dict) -> dict:
    """The time step's receipt of a date_only chart's civil date."""

    return {
        "utc_spans": [
            {
                "start_utc": start.isoformat().replace("+00:00", "Z"),
                "end_exclusive_utc": end.isoformat().replace("+00:00", "Z"),
            }
            for start, end in civil_day["spans"]
        ],
        "semantics": "utc_instants_whose_local_date_is_the_input_date",
    }


def repeated_wall_clock_stretches(tz_input, hour_start: dtmod.datetime) -> list:
    """The wall-clock [from, to) inside the hour that the zone shows twice.

    Any second covered by two constant-offset segments' label ranges is
    repeated, however short: St_Johns 2005-10-30 00h repeats only its first
    minute, Asia/Shanghai 1900-12-31 23h only its last 5 min 43 s.
    """

    if tz_input.mode != "iana":
        return []
    hour_end = hour_start + dtmod.timedelta(hours=1)
    anchor = hour_start.replace(tzinfo=dtmod.timezone.utc)
    labelled = [
        (left.replace(tzinfo=None) + offset, right.replace(tzinfo=None) + offset)
        for left, right, offset in _offset_segments(
            tz_input,
            anchor - _LABEL_WINDOW_MARGIN,
            anchor + dtmod.timedelta(hours=1) + _LABEL_WINDOW_MARGIN,
        )
    ]
    stretches = []
    for index, (first_from, first_to) in enumerate(labelled):
        for second_from, second_to in labelled[index + 1:]:
            start = max(first_from, second_from, hour_start)
            end = min(first_to, second_to, hour_end)
            if start < end:
                stretches.append((start, end))
    return sorted(stretches)


def resolve_date_only_anchor(dt_input, tz_input) -> dict:
    """Local noon, or the first instant after it that the zone actually has.

    Fourteen real civil days have no local noon because a clock change
    swallowed it; date_only does not refuse them.  A day with no
    existing instant at all is still refused, and the refusal names no time the
    user did not enter.
    """

    noon = dtmod.datetime(dt_input.year, dt_input.month, dt_input.day, 12)
    anchor_utc = _first_existing_instant_at_or_after(dt_input, tz_input, noon)
    anchor_local, anchor_fold = _wall_label(anchor_utc, tz_input)
    if anchor_local.date() != noon.date():
        zone_label = tz_input.iana_name if tz_input.mode == "iana" else "此固定偏移"
        raise NonexistentLocalTimeError(
            f"這個民用日期在 {zone_label} 因時區規則變更整天被跳過，當天沒有任何"
            "真實存在的本地時刻可作為只知日期時的代表計算錨點；請確認出生日期。"
        )
    return {
        "policy": DATE_ONLY_ANCHOR_POLICY,
        "anchor_local_time": anchor_local.isoformat(timespec="seconds"),
        "anchor_utc_time": anchor_utc.isoformat().replace("+00:00", "Z"),
        "anchor_fold": anchor_fold,
        "shifted_by_clock_gap": anchor_local != noon,
        "shift_seconds": (anchor_local - noon).total_seconds(),
        "semantics": "representative_computational_anchor_not_birth_time",
    }


def representative_sample_instants(
    dt_input,
    tz_input,
    *,
    precision: str,
    anchor_utc: dtmod.datetime,
    civil_day: dict | None = None,
) -> list[dict]:
    """The three reference instants for non-exact birth times.

    date_only samples the civil day's first and last real seconds, the bounds
    the time step resolved (``resolve_civil_day``); an approximate hour samples
    its own first and last existing seconds, honouring the fold the request
    named.  The middle sample is the chart's own computational anchor instant.
    """

    if precision == "date_only":
        assert civil_day is not None  # the time step resolves it for every date_only chart
        start_utc = civil_day["start_utc"]
        end_utc = civil_day["last_second_utc"]
    elif precision == "approximate_hour":
        start_label = dtmod.datetime(
            dt_input.year, dt_input.month, dt_input.day, dt_input.hour
        )
        end_label = start_label + dtmod.timedelta(minutes=59, seconds=59)
        fold_preference = tz_input.fold if tz_input.mode == "iana" else None
        start_utc = _first_existing_instant_at_or_after(
            dt_input, tz_input, start_label, fold_preference
        )
        end_utc = _last_existing_instant_at_or_before(
            dt_input, tz_input, end_label, fold_preference
        )
    else:
        raise ValueError("representative samples apply only to non-exact precision")
    instants = (
        (REPRESENTATIVE_SAMPLE_ROLES[0], start_utc),
        (REPRESENTATIVE_SAMPLE_ROLES[1], anchor_utc),
        (REPRESENTATIVE_SAMPLE_ROLES[2], end_utc),
    )
    samples = []
    for role, utc_value in instants:
        jd_value = utc_datetime_to_jd_ut(utc_value)
        samples.append(
            {
                "sample_role": role,
                "representative": True,
                "time_basis": "representative_sample_not_birth_time",
                "reference_local_time": _wall_label(utc_value, tz_input)[0].isoformat(
                    timespec="seconds"
                ),
                "reference_utc_time": utc_value.isoformat().replace("+00:00", "Z"),
                "reference_jd_ut": jd_value,
                "time_scale": time_scale_for_jd_ut(jd_value),
            }
        )
    return samples


_TIME_RECEIPT_PATHS = (
    "astronomical_data.time.{0} and calculation_dossier.time_conversion.{0}"
)
METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "time/delta_t_model": {
        "applies_to": _TIME_RECEIPT_PATHS.format("delta_t_model"),
        "status_vocabulary": list(DELTA_T_STATUSES),
        "provenance": (
            "Swiss 2.10.03 calc_deltat(): SMH 2016 model before 1955 (1000-day "
            "transition), dt[] table 1955–2028 (2024–2028 extrapolated), long-term "
            "formula beyond; σ orders from NASA GSFC (Espenak): Stephenson & Houlden "
            "1986 to 1962, Huber 2000 after 2028"
        ),
    },
    "time/sidereal_time_model": {
        "applies_to": _TIME_RECEIPT_PATHS.format("sidereal_time_model"),
        "segment_vocabulary": list(SIDEREAL_TIME_SEGMENTS),
        "source": (
            "Swiss Ephemeris 2.10.03 swe_sidtime / swe_sidtime0 "
            "(swephlib.c SIDT_LTERM_T0, SIDT_LTERM_T1)"
        ),
    },
}
