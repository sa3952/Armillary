"""七政（與可選外行星/南北交點）之黃道、赤道、地平座標、速度、物理現象計算。

套用統一的「計算模式」(ComputationContext)：計算中心、tropical/sidereal、apparent/true、
ecliptic-of-date/J2000、章動開關。地平座標/物理現象等在 heliocentric/barycentric 模式或
非物理星體(交點)上沒有意義時，一律輸出 null，原因寫在同一筆紀錄的 *_reason_code 欄位
（物理現象依 frame_compatibility 的 earth_observer_phenomena 規則），不以 0 冒充。

本模組只回傳原始天文事實，不做任何占星方法判斷（例如不判斷 out-of-bounds 是否成立、
不判斷順逆是否構成「停滯」）——這類判斷屬於方法層，見 chart_pipeline.py 的 derived_methods。

方位角 `azimuth` 已轉換成一般慣用的「北=0°、順時針向東遞增」；Swiss 原始的「南=0°、向西遞增」
值只記在計算軌跡的地平座標步驟供核對（回應不另存一份可由 azimuth 推出的雙胞胎欄位），
見 formatting.swiss_azimuth_to_standard()。

地平座標計算 (swe.azalt) 會傳入使用者的 `pressure_hpa` 與 `temperature_c`。氣壓未指定時傳入
0 hPa，讓 Swiss Ephemeris 依海拔估算；氣溫仍使用 request 值（未指定時即
domain_catalog.DEFAULT_ATMOSPHERE_TEMPERATURE_C；數值只寫在該常數，不在註解另抄）。這些大氣參數只影響
視高度(altitude_apparent)的蒙氣折射修正，真高度(altitude_true，未計蒙氣差)不受影響。
"""

from typing import Final

import swisseph as swe

from ..domain_catalog import (
    BODY_ID_BY_KEY,
    CHIRON_JPL_SBDB_REFERENCE,
    CHIRON_PHYSICAL_PARAMETERS_SOURCE_REF,
    NODE_BODIES,
)
from ..ephemeris import (
    COVERAGE_STATES,
    FullEphemerisRequiredError,
    coverage_state,
    guarded_calc,
    object_used_full_ephemeris,
    segments_read_by,
)
from .formatting import (
    negate_without_negative_zero,
    swiss_azimuth_to_standard,
)
from .computation_mode import heliocentric_apparent_calc_ut, uses_sun_centre_light_time
from .frame_compatibility import NON_EARTH_OBSERVER_CENTER, FrameState, method_frame_state
from .source_reading import ORIGINAL_LANGUAGE_READ, cited
from .time_utils import earth_rotation_jd_ut
from .trace import Trace

# `position_mode="true"` 時不輸出視高度。
# true position 已移除光行時與光行差，得到的是幾何方向；再對該方向套用大氣折射，
# 會讓同一個數值同時假設「光瞬時到達」與「光穿過大氣」兩個互斥前提。這個數字
# 無法被正確解讀，也無法被第三方複算，故不輸出優於輸出。
TRUE_POSITION_APPARENT_ALTITUDE_REASON = (
    "suppressed_true_position_refraction_semantics_incompatible"
)


def apparent_altitude_policy(ctx) -> tuple[bool, str | None]:
    """回傳 (是否輸出視高度, 不輸出時的 reason_code)。恆星模組共用同一條規則。"""

    if ctx.mode.position_mode == "true":
        return False, TRUE_POSITION_APPARENT_ALTITUDE_REASON
    return True, None


# At a geographic pole every horizontal direction points the same
# way, so the "north = 0°" convention has no reference and Swiss returns an
# azimuth that merely follows the longitude supplied.  Altitude stays valid.
AZIMUTH_UNDEFINED_AT_POLE_REASON = "azimuth_undefined_at_geographic_pole"


def azimuth_policy(location) -> str | None:
    if abs(location.latitude) >= 90.0:
        return AZIMUTH_UNDEFINED_AT_POLE_REASON
    return None


def horizontal_position(jd_ut: float, ctx, atmosphere, ecl) -> tuple:
    """swe.azalt for one ecliptic position: (azimuth, Swiss azimuth, true, apparent).

    The azimuth is the standard north-clockwise one, null at a pole; the
    apparent altitude is null where the position mode suppresses it.
    """

    pressure_hpa = atmosphere.pressure_hpa if atmosphere.pressure_hpa is not None else 0.0
    az_raw, true_alt, app_alt = swe.azalt(
        earth_rotation_jd_ut(jd_ut),
        swe.ECL2HOR,
        (ctx.location.longitude, ctx.location.latitude, ctx.location.altitude_m),
        pressure_hpa,
        atmosphere.temperature_c,
        (ecl[0], ecl[1], ecl[2]),
    )
    az: float | None = swiss_azimuth_to_standard(az_raw)
    if azimuth_policy(ctx.location) is not None:
        az = az_raw = None
    if not apparent_altitude_policy(ctx)[0]:
        app_alt = None
    return az, az_raw, true_alt, app_alt


def horizontal_fields(ctx, az, true_alt, app_alt) -> dict:
    """The five horizontal fields of a record, each null with its reason."""

    emit_apparent, apparent_reason = apparent_altitude_policy(ctx)
    return {
        "azimuth": az,
        "azimuth_reason_code": (
            None
            if az is not None
            else azimuth_policy(ctx.location)
            if ctx.horizon_meaningful
            else "not_applicable_for_display_center"
        ),
        "altitude_true": true_alt,
        "altitude_apparent": app_alt,
        "altitude_apparent_reason_code": (
            None
            if app_alt is not None
            else apparent_reason
            if not emit_apparent
            else "not_applicable_for_display_center"
        ),
    }


# A date without a time has no horizon position: the azimuth and altitudes at
# the noon anchor would describe a sky the person need not have been born
# under, so they are null with the date-only reason.
DATE_ONLY_NO_BIRTH_TIME_REASON = "date_only_no_birth_time"
HORIZONTAL_VALUE_FIELDS = ("azimuth", "altitude_true", "altitude_apparent")
HORIZONTAL_REASON_FIELDS = ("azimuth_reason_code", "altitude_apparent_reason_code")


def withhold_horizontal_coordinates(record: dict, reason_code: str) -> dict:
    """Null a record's horizontal fields with one reason, in place.

    The date_only anchor chart and every date_only sample go through this,
    so the samples print what the anchor prints.
    """

    if "azimuth" in record:
        record.update(dict.fromkeys(HORIZONTAL_VALUE_FIELDS))
        record.update(dict.fromkeys(HORIZONTAL_REASON_FIELDS, reason_code))
        record["retflag_horizontal_source"] = None
    return record


# The descending nodes the chart derives on request, with their names: the
# chart and every date_only sample derive them from this one table.
SOUTH_NODE_DERIVATIONS = (
    ("true_node", "true_south_node", "南交點（密切）"),
    ("mean_node", "mean_south_node", "南交點（平均）"),
)


# The labels the effective Moon carries under moon_only_topocentric_v1.  The
# chart and the birth-time samples print the same record.
EFFECTIVE_TOPOCENTRIC_MOON_LABELS = {
    "coordinate_origin": "topocentric_observer",
    "effective_coordinate_origin": "topocentric_observer",
    "role": "effective_moon_used_by_downstream",
}


# Swiss Ephemeris 2.10.03 (swecl.c, MAG_MOON_VREIJS) computes the Moon's
# magnitude with Allen (1976) up to a phase angle of 147.1385465° and switches
# to a cube-law formula after Samaha, Asaad and Mikhail (1969) beyond it.  The
# source states no range of validity for the second formula, which diverges as
# the phase angle approaches 180°.  Beyond the stitch the product emits null with
# a reason instead of a number whose model range is not established.
MOON_MAGNITUDE_MODEL_MAX_PHASE_ANGLE_DEGREES = 147.1385465
MOON_MAGNITUDE_BEYOND_MODEL_REASON = "moon_phase_angle_beyond_documented_magnitude_model"

# On the geocentric apparent path Swiss's distance rate for planets
# (not the Sun or the Moon) includes the rate of change of the aberration
# correction, so it is not d(distance_au)/dt: locally measured at J2000 the gap
# is about 2e-6 au/day, against about 1e-9 for true position, heliocentric,
# the Sun and the Moon.  The Swiss value is kept and named for what it is.
SPEED_DISTANCE_SEMANTICS = (
    "swiss_flg_speed_analytic_rate",
    "swiss_flg_speed_rate_includes_aberration_change_not_d_distance_dt",
)

# Swiss computes lunar nodes and apsides as orbital elements; with the
# topocentric flag it returns the geocentric values unchanged while the retflag
# still carries the topocentric bit.  The record says which center it is in.
ORBITAL_POINT_CENTER_POLICY = "lunar_orbital_point_not_parallax_corrected"
# Why a degenerate record carries no longitude, written where
# the degeneracy is decided so option receipts copy it instead of guessing.
BODY_IS_COORDINATE_CENTER = "body_is_the_coordinate_center"


def _orbital_point_center_fields(ctx, moon_relative: bool, *, degenerate: bool) -> dict:
    if not moon_relative:
        return {}
    return {
        "requested_center": ctx.mode.center,
        "effective_center": None if degenerate else "geocentric",
        "center_policy": ORBITAL_POINT_CENTER_POLICY,
    }


def _null_body_record(
    key: str,
    name: str,
    *,
    reason_code: str,
    phenomena_reason_code: str | None,
    retflag_ecliptic: int | None,
    retflag_equatorial: int | None,
    used_full_ephemeris: bool,
    availability_reason_code: str,
) -> dict:
    """A body record with every value null, in the computed record's field set."""

    return {
        "key": key, "name": name,
        "longitude": None, "latitude": None, "distance_au": None,
        "speed_longitude": None, "speed_latitude": None, "speed_distance": None,
        "speed_position_derivative_status": "not_applicable",
        "motion_sign": None,
        "right_ascension": None, "declination": None, "speed_ra": None, "speed_dec": None,
        "azimuth": None, "altitude_true": None, "altitude_apparent": None,
        "altitude_apparent_reason_code": reason_code,
        "azimuth_reason_code": reason_code,
        "speed_distance_semantics": None,
        "phase_angle": None, "illuminated_fraction": None, "elongation": None,
        "apparent_diameter": None, "apparent_magnitude": None,
        "apparent_magnitude_reason_code": reason_code,
        "phenomena_reason_code": phenomena_reason_code,
        "retflag_ecliptic": retflag_ecliptic, "retflag_equatorial": retflag_equatorial,
        "retflag_horizontal_source": None,
        "used_full_ephemeris": used_full_ephemeris,
        "availability_reason_code": availability_reason_code,
    }


# Definition metadata a body record carries over from its catalog entry.
_DEFINITION_METADATA_KEYS = ("calculation_source", "method_classification", "naming_note")


def _motion_sign(speed: float) -> str:
    if speed > 0:
        return "positive"
    if speed < 0:
        return "negative"
    return "zero"


def _horizontal(
    jd_ut: float, body_id: int, ctx, atmosphere, ecliptic: tuple, used_full_ephemeris: bool
) -> tuple[tuple, int, bool]:
    """The horizontal position, its source retflag, and the updated full-ephemeris flag."""

    ecl, retflag_ecl = ecliptic
    flags = ctx.base_flags
    horizontal_flags = ctx.horizontal_source_flags
    horizontal_ecl, horizontal_retflag = (
        (ecl, retflag_ecl)
        if horizontal_flags == flags
        else swe.calc_ut(jd_ut, body_id, horizontal_flags)
    )
    used_full_ephemeris = used_full_ephemeris and object_used_full_ephemeris(
        horizontal_retflag, body=body_id, flags=horizontal_flags, jd_ut=jd_ut,
    )
    position = horizontal_position(jd_ut, ctx, atmosphere, horizontal_ecl)
    return position, horizontal_retflag, used_full_ephemeris


def _speed_semantics(ctx, key: str, physical: bool) -> tuple[str, str]:
    """What the speed fields claim: derivative agreement, and the distance speed's meaning."""

    speed_position_derivative_status = (
        "known_internal_disagreement_for_sun_moon"
        if ctx.mode.center == "topocentric" and key in {"sun", "moon"}
        else "not_independently_established"
        if ctx.mode.center == "topocentric"
        # A specific statement, not "not_evaluated".  The Swiss analytic
        # speed is not claimed to equal the derivative of the emitted position;
        # locally the geocentric Moon differs by about 0.2 arcsec/day.
        else "analytic_swiss_value_agreement_not_claimed"
    )
    speed_distance_semantics = SPEED_DISTANCE_SEMANTICS[
        1
        if ctx.mode.center == "geocentric"
        and ctx.mode.position_mode == "apparent"
        and physical
        and key not in {"sun", "moon"}
        else 0
    ]
    return speed_position_derivative_status, speed_distance_semantics


def _phenomena(jd_ut: float, body_id: int, key: str, flags: int, physical: bool, phenomena_state: FrameState) -> tuple:
    """Swiss pheno_ut's Earth-observer quantities, or null with the reason."""

    phase_angle = illum_fraction = elongation = app_diameter = app_mag = None
    app_mag_reason = None if physical else "not_applicable_non_physical_point"
    phenomena_reason = None if physical else "not_applicable_non_physical_point"
    if physical and not phenomena_state["applicable"]:
        app_mag_reason = phenomena_reason = phenomena_state["reason_code"]
    elif physical:
        try:
            attr = swe.pheno_ut(jd_ut, body_id, flags)
            phase_angle, illum_fraction, elongation, app_diameter, app_mag = attr[0], attr[1], attr[2], attr[3], attr[4]
            # 太陽對自己求「相位角/照明比例/距角」在幾何上是退化的(Sun-Body-Earth三角形兩頂點重合)，
            # 無論計算中心為何都沒有意義，故一律轉為 null；但視直徑與視星等是獨立公式，太陽本身仍是有效值，保留。
            if key == "sun":
                phase_angle = illum_fraction = elongation = None
            if (
                key == "moon"
                and phase_angle is not None
                and phase_angle > MOON_MAGNITUDE_MODEL_MAX_PHASE_ANGLE_DEGREES
            ):
                app_mag = None
                app_mag_reason = MOON_MAGNITUDE_BEYOND_MODEL_REASON
        except swe.Error:
            app_mag_reason = phenomena_reason = "swiss_phenomena_unavailable"
    return (
        phase_angle, illum_fraction, elongation, app_diameter, app_mag,
        app_mag_reason, phenomena_reason,
    )


def compute_body(definition: dict, jd_ut: float, ctx, atmosphere,
                  trace: Trace, physical: bool = True, moon_relative: bool = False) -> dict:
    body_id, key, zh_name = definition["id"], definition["key"], definition["zh"]
    flags = ctx.base_flags
    position_calc = (
        heliocentric_apparent_calc_ut
        if physical and key != "sun" and uses_sun_centre_light_time(ctx)
        else swe.calc_ut
    )
    ecl, retflag_ecl = position_calc(jd_ut, body_id, flags)
    equatorial_flags = ctx.equatorial_source_flags | swe.FLG_EQUATORIAL
    equ, retflag_eq = position_calc(jd_ut, body_id, equatorial_flags)

    ecl_lon, ecl_lat, dist_au, speed_lon, speed_lat, speed_dist = ecl
    ra, dec, _dist2, speed_ra, speed_dec, _speed_dist2 = equ

    # The retflag alone cannot say this (a Moshier Moon keeps the
    # SWIEPH bit); the segments this position reads must also be present.
    used_full_ephemeris = object_used_full_ephemeris(
        retflag_ecl, body=body_id, flags=flags, jd_ut=jd_ut,
    ) and object_used_full_ephemeris(
        retflag_eq, body=body_id, flags=equatorial_flags, jd_ut=jd_ut,
    )

    # 太陽在 heliocentric 模式下沒有物理意義（不能繞自己公轉）；月球相關的合成點(交點/遠近點)
    # 是以「繞地球運行」為前提定義的，heliocentric/barycentric 模式下同樣沒有意義。
    # 兩種情況 swisseph 都只會靜默回傳退化的 0，而非報錯，故需在此明確攔截、輸出 null。
    degenerate = (
        (key == "sun" and ctx.mode.center == "heliocentric")
        or (moon_relative and ctx.mode.center in ("heliocentric", "barycentric"))
    )

    emit_apparent_altitude = apparent_altitude_policy(ctx)[0]
    # Phase angle, illuminated fraction, elongation, apparent
    # diameter and magnitude are Earth-observer quantities.  Swiss pheno_ut
    # ignores the heliocentric/barycentric flags and returns the geocentric
    # values, so outside an Earth centre they are null with the table's reason.
    phenomena_state = method_frame_state("earth_observer_phenomena", ctx.mode)

    if degenerate:
        result = {
            **_null_body_record(
                key,
                zh_name,
                reason_code="not_applicable_for_display_center",
                phenomena_reason_code=(
                    phenomena_state["reason_code"]
                    if physical
                    else "not_applicable_non_physical_point"
                ),
                retflag_ecliptic=retflag_ecl,
                retflag_equatorial=retflag_eq,
                used_full_ephemeris=used_full_ephemeris,
                availability_reason_code=(
                    NON_EARTH_OBSERVER_CENTER if moon_relative else BODY_IS_COORDINATE_CENTER
                ),
            ),
            **_orbital_point_center_fields(ctx, moon_relative, degenerate=True),
        }
        trace.add(
            f"{zh_name} 位置計算",
            note="⚠ 此點在 heliocentric/barycentric 模式下沒有物理意義"
                 + ("（太陽無法繞自身公轉）" if key == "sun" else "（月球相關合成點以繞地運行為前提定義）")
                 + "，本項全部輸出為 null，而非用 0 假冒結果。",
        )
        return result

    motion_sign = _motion_sign(speed_lon)
    speed_position_derivative_status, speed_distance_semantics = _speed_semantics(
        ctx, key, physical
    )

    az = az_raw = true_alt = app_alt = None
    horizontal_retflag = None
    if ctx.horizon_meaningful:
        (az, az_raw, true_alt, app_alt), horizontal_retflag, used_full_ephemeris = (
            _horizontal(jd_ut, body_id, ctx, atmosphere, (ecl, retflag_ecl), used_full_ephemeris)
        )

    (
        phase_angle, illum_fraction, elongation, app_diameter, app_mag,
        app_mag_reason, phenomena_reason,
    ) = _phenomena(jd_ut, body_id, key, flags, physical, phenomena_state)

    trace.add(
        f"{zh_name} 位置計算",
        formula="黃道: swe.calc_ut(計算模式旗標)；赤道: 移除 sidereal 後加 FLG_EQUATORIAL"
                + ("；地平: swe.azalt(ECL2HOR)" if ctx.horizon_meaningful else ""),
        inputs={
            "JD(UT)": jd_ut,
            "flags": flags,
            **({
                "氣壓(hPa；0=依海拔估算)": atmosphere.pressure_hpa or 0.0,
                "溫度(°C)": atmosphere.temperature_c,
                "地平座標來源flags(tropical of-date)": ctx.horizontal_source_flags,
            } if ctx.horizon_meaningful else {}),
        },
        result={
            "黃經": ecl_lon, "黃緯": ecl_lat, "距離(AU)": dist_au,
            "黃經速度(度/日)": speed_lon, "motion_sign": motion_sign,
            "赤經": ra, "赤緯": dec,
            **({"方位角Az(北=0,順時針)": az, "方位角Az(Swiss原始,南=0,向西)": az_raw,
                "真高度Alt": true_alt,
                **({"視高度(含蒙氣差)": app_alt} if emit_apparent_altitude else {})}
               if ctx.horizon_meaningful else {}),
        },
        note=(
            ("" if used_full_ephemeris else "⚠ 此天體退回 Moshier 半分析模型，精度較低")
            + (
                ""
                if emit_apparent_altitude
                else "你選了『真位置』（不含大氣折射的幾何位置），所以這裡不列出天體『看起來』"
                     "離地平線多高：那個數值一定含大氣折射，和真位置混用會失真，也無法正確複算。"
            )
            + (
                "站心的速度欄位是 Swiss Ephemeris 以解析式算出的值；已知太陽與月亮的部分速度欄位"
                "不等於同次站心位置的有限差分導數，故不作導數精度宣稱。"
                if speed_position_derivative_status
                == "known_internal_disagreement_for_sun_moon"
                else ""
            )
        ) if ctx.horizon_meaningful
        else "地平座標於 heliocentric/barycentric 模式下無物理意義，故不計算",
    )

    return {
        "key": key,
        "name": zh_name,
        "longitude": ecl_lon,
        "latitude": ecl_lat,
        "distance_au": dist_au,
        "speed_longitude": speed_lon,
        "speed_latitude": speed_lat,
        "speed_distance": speed_dist,
        "speed_position_derivative_status": speed_position_derivative_status,
        "speed_distance_semantics": speed_distance_semantics,
        "motion_sign": motion_sign,
        "right_ascension": ra,
        "declination": dec,
        "speed_ra": speed_ra,
        "speed_dec": speed_dec,
        **horizontal_fields(ctx, az, true_alt, app_alt),
        "phase_angle": phase_angle,
        "illuminated_fraction": illum_fraction,
        "elongation": elongation,
        "apparent_diameter": app_diameter,
        "apparent_magnitude": app_mag,
        "apparent_magnitude_reason_code": app_mag_reason,
        "phenomena_reason_code": phenomena_reason,
        "retflag_ecliptic": retflag_ecl,
        "retflag_equatorial": retflag_eq,
        "retflag_horizontal_source": horizontal_retflag,
        "used_full_ephemeris": used_full_ephemeris,
        **_orbital_point_center_fields(ctx, moon_relative, degenerate=False),
    }


def make_longitude_sampler(ctx, *, moon_ctx=None, moon_id: int = swe.MOON):
    """回傳 (body_id, jd_ut) -> 黃經 的取樣函式，供求根器在時間軸上重複查星曆。

    刻意沿用 `ctx.base_flags`，讓求根結果與主要輸出處在同一個黃道系統與參考框架：
    若這裡改用別組旗標，sidereal 模式下算出的「成相時刻」會對應到另一套星座界線。
    速度旗標(FLG_SPEED)已包含在 base_flags 內，額外成本可忽略，故不另外拆一組旗標。
    """

    flags = ctx.base_flags
    moon_flags = moon_ctx.base_flags if moon_ctx is not None else None

    def longitude_at(body_id: int, jd_ut: float) -> float:
        effective_flags = (
            moon_flags
            if moon_flags is not None and body_id == moon_id
            else flags
        )
        return guarded_calc(jd_ut, body_id, effective_flags, f"未來事件搜尋（Swiss body {body_id} 黃經）")[0][0]

    return longitude_at


def memoized_longitudes(longitude_at):
    """One Swiss call per (body, instant) within one search.

    Root searches over several pairs sample every pair on the same coarse grid,
    so without this the same position is recomputed once per pair it belongs
    to (the VOC search: up to 48 times per grid point).  Under the fixed flags
    of one sampler a longitude is a pure function of (body_id, jd_ut), so the
    cache cannot change a result; it lives only as long as the caller keeps it.
    A refused position raises and is not cached.
    """

    cache: dict[tuple[int, float], float] = {}

    def cached(body_id: int, jd_ut: float) -> float:
        key = (body_id, jd_ut)
        value = cache.get(key)
        if value is None:
            value = longitude_at(body_id, jd_ut)
            cache[key] = value
        return value

    return cached


def unavailable_body_record(
    definition: dict,
    trace: Trace,
    *,
    coverage: dict,
) -> dict:
    """A body whose Swiss segment cannot serve this instant, stated as such.

    Same shape as a computed record so every consumer that already tolerates
    the degenerate (heliocentric Sun) case tolerates this one; the reason is a
    closed-set code from the ephemeris manifest, never an HTTP failure.
    """

    result = {
        **_null_body_record(
            definition["key"],
            definition["zh"],
            reason_code="not_computed_body_unavailable",
            phenomena_reason_code="not_computed_body_unavailable",
            retflag_ecliptic=None,
            retflag_equatorial=None,
            used_full_ephemeris=False,
            availability_reason_code=coverage["availability_reason_code"],
        ),
        "ephemeris_segment": coverage["ephemeris_segment"],
        "coverage_state": coverage["coverage_state"],
        "segment_jd_ut_coverage": coverage["segment_jd_ut_coverage"],
    }
    for metadata_key in _DEFINITION_METADATA_KEYS:
        if metadata_key in definition:
            result[metadata_key] = definition[metadata_key]
    trace.add(
        f"{definition['zh']} 位置計算",
        inputs={"JD(UT)": coverage["jd_ut"], "星曆段": coverage["ephemeris_segment"]},
        result={"coverage_state": coverage["coverage_state"]},
        note=(
            "此時刻不在該星曆段的檔案覆蓋範圍內（依檔案 manifest 與 UTC 儒略日判定，"
            "不依 retflag）；本項全部輸出為 null 並附理由碼，核心命盤不受影響。"
        ),
    )
    return result


def compute_bodies(body_defs: list, jd_ut: float, ctx, atmosphere, trace: Trace,
                    physical: bool = True, moon_relative: bool = False) -> list:
    results = []
    for definition in body_defs:
        result = compute_body(
            definition, jd_ut, ctx, atmosphere, trace,
            physical=physical, moon_relative=moon_relative,
        )
        for metadata_key in _DEFINITION_METADATA_KEYS:
            if metadata_key in definition:
                result[metadata_key] = definition[metadata_key]
        # The phenomena parameters travel with the record they explain.
        if "physical_parameters" in definition:
            result["physical_parameters"] = dict(definition["physical_parameters"])
        if definition.get("expose_swiss_body_id"):
            result["swiss_body_id"] = definition["id"]
        results.append(result)
    return results


def node_definitions() -> list[dict]:
    return [{"id": b["id"], "key": b["key"], "zh": b["zh"]} for b in NODE_BODIES]


def append_south_nodes(points: list[dict], jd_ut: float, ctx, atmosphere, trace: Trace) -> None:
    """Derive every SOUTH_NODE_DERIVATIONS node from its north node in `points`."""
    by_key = {item["key"]: item for item in points}
    points.extend(
        derive_node_antipode(
            by_key[north_key], key=south_key, name=south_name,
            body_id=BODY_ID_BY_KEY[north_key], jd_ut=jd_ut, ctx=ctx,
            atmosphere=atmosphere, trace=trace,
        )
        for north_key, south_key, south_name in SOUTH_NODE_DERIVATIONS
    )


def derive_node_antipode(
    north: dict,
    *,
    key: str,
    name: str,
    body_id: int,
    jd_ut: float,
    ctx,
    atmosphere,
    trace: Trace,
) -> dict:
    """Derive a descending lunar node as the directional antipode of a north node.

    The adopted product contract is intentionally directional: longitude/latitude and
    equatorial direction are antipodal, while distance is left null because adding 180°
    to a node direction does not independently determine a physical radial distance.
    """

    derivation = {
        "derived_from": north["key"],
        "calculation_source": "north_node_direction_antipode",
        "derivation_formula": (
            "ecliptic_longitude=(north+180) mod 360; ecliptic_latitude=-north; "
            "right_ascension=(north+180) mod 360; declination=-north"
        ),
    }
    if north.get("longitude") is None:
        result = dict(north)
        result.update({"key": key, "name": name, **derivation})
        result["distance_au"] = None
        result["speed_distance"] = None
        trace.add(
            f"{name} 導出",
            formula="北交點方向的黃道／赤道對蹠點",
            note="來源北交點不可用，故南交點同樣不可用。",
        )
        return result

    # 北交點黃緯為精確 0 時，單純取反會得到 −0.0。
    longitude = (north["longitude"] + 180.0) % 360.0
    latitude = negate_without_negative_zero(north["latitude"])
    right_ascension = (north["right_ascension"] + 180.0) % 360.0
    declination = negate_without_negative_zero(north["declination"])
    speed_latitude = negate_without_negative_zero(north["speed_latitude"])
    speed_dec = negate_without_negative_zero(north["speed_dec"])

    azimuth = altitude_true = altitude_apparent = None
    horizontal_retflag = None
    used_full_ephemeris = north.get("used_full_ephemeris")
    if ctx.horizon_meaningful:
        horizontal_values, horizontal_retflag = swe.calc_ut(
            jd_ut, body_id, ctx.horizontal_source_flags
        )
        south_horizontal = (
            (horizontal_values[0] + 180.0) % 360.0,
            -horizontal_values[1],
            horizontal_values[2],
        )
        azimuth, _azimuth_raw, altitude_true, altitude_apparent = horizontal_position(
            jd_ut, ctx, atmosphere, south_horizontal
        )
        used_full_ephemeris = bool(used_full_ephemeris) and object_used_full_ephemeris(
            horizontal_retflag,
            body=body_id,
            flags=ctx.horizontal_source_flags,
            jd_ut=jd_ut,
        )

    trace.add(
        f"{name} 導出",
        formula=derivation["derivation_formula"],
        inputs={"來源": north["key"], "來源黃經": north["longitude"]},
        result={"黃經": longitude, "赤經": right_ascension, "赤緯": declination},
        note="這是北交點方向的幾何對蹠點，不是另一個獨立 Swiss body。",
    )
    return {
        "key": key,
        "name": name,
        "longitude": longitude,
        "latitude": latitude,
        "distance_au": None,
        "speed_longitude": north["speed_longitude"],
        "speed_latitude": speed_latitude,
        "speed_distance": None,
        "motion_sign": north["motion_sign"],
        "right_ascension": right_ascension,
        "declination": declination,
        "speed_ra": north["speed_ra"],
        "speed_dec": speed_dec,
        **horizontal_fields(ctx, azimuth, altitude_true, altitude_apparent),
        "phase_angle": None,
        "illuminated_fraction": None,
        "elongation": None,
        "apparent_diameter": None,
        "apparent_magnitude": None,
        "apparent_magnitude_reason_code": "not_applicable_non_physical_point",
        "phenomena_reason_code": "not_applicable_non_physical_point",
        "speed_distance_semantics": None,
        "retflag_ecliptic": north.get("retflag_ecliptic"),
        "retflag_equatorial": north.get("retflag_equatorial"),
        "retflag_horizontal_source": horizontal_retflag,
        "used_full_ephemeris": used_full_ephemeris,
        "requested_center": north.get("requested_center"),
        "effective_center": north.get("effective_center"),
        "center_policy": north.get("center_policy"),
        **derivation,
    }


# 參與者集合
# 黃道相位、反照點與赤緯相位共用**同一個**參與者選擇器，三個消費者對「哪些星體
# 可以參與」給出同一個答案，收據才能如實描述每個選項是否真的生效：
#   classical_planet：七政，永遠參與。
#   lunar_node：實際存在於 bodies 紀錄中的交點鍵（含明示要求時導出的南交點），
#               只在 include_nodes 為真時參與。鍵取自實際紀錄而不是計算南交點之前
#               的靜態兩鍵，所以明示要求的南交點不會靜默消失。
#   outer_planet：三王星，只在 include_outer_planets 為真時參與。
#   其餘（凱龍、Lilith／Priapus 等現代附加點）**永遠不自動加入**：現代點不因開啟而
#   自動參與相位或古典方法（赤緯相位也不例外）。

LUNAR_NODE_KEYS = frozenset({
    "true_node", "mean_node", "true_south_node", "mean_south_node",
})
# 關係判定（黃道相位、赤緯平行）排除的「定義性」交點對，每對帶一個閉集理由碼：
# - nodal_axis_antipodal_by_definition：南交點是所選北交點的定義性對蹠點
#   （λ_S = λ_N + 180°），兩者的「對沖」與赤緯「反平行」是定義而非發現（方法研究筆記）。
# - node_models_of_same_nodal_axis：密切交點與平均交點是同一條交點軸的兩種算法，不是
#   兩個天體（Swiss Ephemeris 手冊 §2.2.2；前現代文本只有一個 Dragon's Head／Tail）。
#   兩模型之間的「合」「沖」「平行」「反平行」只是兩種算法的差（約 0–2°），不是關係。
#   兩種交點模型並列輸出不受影響：每個交點仍各自與行星成相位，只是不互相配對。
DEFINITIONAL_PAIR_REASON_CODES = (
    "nodal_axis_antipodal_by_definition",
    "node_models_of_same_nodal_axis",
)
DEFINITIONAL_EXCLUDED_PAIRS: dict[frozenset[str], str] = {
    frozenset({"true_node", "true_south_node"}): DEFINITIONAL_PAIR_REASON_CODES[0],
    frozenset({"mean_node", "mean_south_node"}): DEFINITIONAL_PAIR_REASON_CODES[0],
    frozenset({"true_node", "mean_node"}): DEFINITIONAL_PAIR_REASON_CODES[1],
    frozenset({"true_south_node", "mean_south_node"}): DEFINITIONAL_PAIR_REASON_CODES[1],
    frozenset({"true_node", "mean_south_node"}): DEFINITIONAL_PAIR_REASON_CODES[1],
    frozenset({"mean_node", "true_south_node"}): DEFINITIONAL_PAIR_REASON_CODES[1],
}
PARTICIPANT_CATEGORIES = ("classical_planet", "lunar_node", "outer_planet")


def _body_key_sets() -> tuple[frozenset[str], frozenset[str]]:
    from ..domain_catalog import CLASSICAL_BODIES, OUTER_BODIES

    return (
        frozenset(body["key"] for body in CLASSICAL_BODIES),
        frozenset(body["key"] for body in OUTER_BODIES),
    )


def effective_participants(
    bodies_all: list[dict],
    *,
    include_nodes: bool,
    include_outer_planets: bool,
) -> list[dict]:
    """Return the bodies that may participate in relationship methods, with a category.

    Each returned record is the original body record plus ``participant_category``.
    Order: category order of ``PARTICIPANT_CATEGORIES`` (classical, nodes, outer),
    then ``bodies_all`` order within a category. Bodies outside the three
    categories never join.
    """

    classical, outer = _body_key_sets()
    selected = []
    for body in bodies_all:
        key = body["key"]
        if key in classical:
            category = "classical_planet"
        elif key in LUNAR_NODE_KEYS:
            if not include_nodes:
                continue
            category = "lunar_node"
        elif key in outer:
            if not include_outer_planets:
                continue
            category = "outer_planet"
        else:
            continue
        selected.append({**body, "participant_category": category})
    rank = {category: index for index, category in enumerate(PARTICIPANT_CATEGORIES)}
    return sorted(selected, key=lambda body: rank[body["participant_category"]])


def participant_policy_receipt(
    participants: list[dict],
    *,
    include_nodes: bool,
    include_outer_planets: bool,
) -> dict:
    """Describe which categories actually joined, for the option receipts."""

    keys = [body["key"] for body in participants]
    return {
        "categories": list(PARTICIPANT_CATEGORIES),
        "include_nodes_requested": include_nodes,
        "include_outer_planets_requested": include_outer_planets,
        "node_keys_participating": [key for key in keys if key in LUNAR_NODE_KEYS],
        "modern_points_auto_join": False,
        "excluded_pairs_by_definition": [
            {"keys": sorted(pair), "reason_code": reason_code}
            for pair, reason_code in sorted(
                DEFINITIONAL_EXCLUDED_PAIRS.items(), key=lambda item: sorted(item[0])
            )
            if pair <= set(keys)
        ],
    }


# The one definition of the Sun position the sect altitude reads.  Geocentric,
# tropical of date with nutation (what ECL2HOR expects), and the *apparent*
# place: light-time and aberration applied, as the request's default
# position_mode.  "真高度"／"true altitude" in the sect method and the methods
# page means the altitude without atmospheric refraction (Swiss azalt's true vs
# apparent altitude), not FLG_TRUEPOS: the named comparison boundary, the USNO
# sunrise definition (geometric zenith distance 90°50′), is stated for the Sun's
# apparent place.  Not read from the request's position_mode, or sect would move
# with a display switch: about 20″ of aberration flips day/night for about a
# second each sunrise and sunset (2000-03-20 10:01:29 UTC at 25°N: apparent
# −4.9″, true +15.7″).
SECT_SUN_FLAGS: Final = swe.FLG_SWIEPH | swe.FLG_SPEED
# lots.SECT_SUN_POSITION names these flags in the sect receipt.


def geocentric_sun_true_altitude(jd_ut: float, ctx, atmosphere) -> float | None:
    """Sun-centre true altitude from the geocentre, whatever the display settings.

    日夜盤判定固定消費地心真高度：使用者把顯示中心切到 topocentric、或把
    位置切到 true（幾何位置）時，日夜盤都不得跟著移動（太陽視差最大約 8.8″、光行差約
    20″，翻轉機率極低，但「顯示切換改變方法結果」這一類行為本身不可接受）。太陽位置
    一律用 ``SECT_SUN_FLAGS``；heliocentric／barycentric 沒有地平，回傳 None。

    時刻是否在星曆段範圍內，依 manifest 在呼叫 Swiss 前判定（ephemeris 模組契約）：範圍外就拒絕，不讓 Swiss 退回 Moshier 或在 warm worker 外插。檔案缺漏則與核心
    命盤同一政策——照算，由太陽紀錄的 used_full_ephemeris 與 dossier 警示揭露——所以這裡
    只擋範圍外，不擋缺檔。
    """

    return geocentric_true_altitude(jd_ut, ctx, atmosphere, swe.SUN)


def geocentric_true_altitude(jd_ut: float, ctx, atmosphere, body_id: int) -> float | None:
    """One body's centre true altitude from the geocentre, read like the Sun's for sect."""

    if not ctx.horizon_meaningful:
        return None
    for segment in segments_read_by(body_id, SECT_SUN_FLAGS):
        if coverage_state(jd_ut, segment) == COVERAGE_STATES[1]:
            raise FullEphemerisRequiredError(
                operation=(
                    "日夜盤（太陽地心高度）" if body_id == swe.SUN else "行星地心高度"
                ),
                jd_ut=jd_ut,
                retflag=0,
                reason="segment_out_of_coverage",
            )
    ecl, _retflag = swe.calc_ut(jd_ut, body_id, SECT_SUN_FLAGS)
    return horizontal_position(jd_ut, ctx, atmosphere, ecl)[2]


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    CHIRON_PHYSICAL_PARAMETERS_SOURCE_REF: {
        "applies_to": (
            "astronomical_data.bodies[key=chiron].apparent_diameter, "
            "apparent_magnitude and physical_parameters"
        ),
        "sources": [
            cited(("Swiss Ephemeris 2.10.03 sweph.h pla_diam[] and swecl.c mag_elem[], "
                   "used by swe_pheno"),
                  ("pla_diam[]: Chiron 271370 m; mag_elem[]: Chiron H 6.5, G 0.15, "
                   "\"from Bowell data base\""),
                  ORIGINAL_LANGUAGE_READ, "the Swiss Ephemeris 2.10.03 source files"),
            cited("JPL Small-Body Database, 2060 Chiron, physical parameters",
                  (f"diameter {CHIRON_JPL_SBDB_REFERENCE['diameter_km']:g} km "
                   f"(Dunham 1998), H {CHIRON_JPL_SBDB_REFERENCE['absolute_magnitude_h']:g}"),
                  ORIGINAL_LANGUAGE_READ,
                  f"the database record, retrieved {CHIRON_JPL_SBDB_REFERENCE['retrieved']}"),
            cited("JPL Horizons, 2060 Chiron orbit solution JPL#171",
                  "the orbit solution the Swiss position is measured against",
                  ORIGINAL_LANGUAGE_READ, "the Horizons service, solution JPL#171"),
        ],
        "note": (
            "Apparent diameter and magnitude use the parameters built into Swiss "
            "Ephemeris, not the current JPL SBDB solution: the diameter is about "
            "63.5% larger and the magnitude about 0.96 mag fainter than SBDB "
            "values. Published Chiron diameters differ between sources, so the "
            "built-in values are disclosed rather than replaced. The position "
            "comes from the Swiss seas_18 file; measured against JPL#171 relative "
            "to the Sun it agrees within 0.04 arcsec at 1987, 2000 and 2024 and "
            "differs by up to 1.48 arcsec at 2399. This is a measurement, not an "
            "accuracy claim."
        ),
    },
}
