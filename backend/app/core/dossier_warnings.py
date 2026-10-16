"""The calculation dossier's structured warnings, one function per rule.

A warning flags sensitivity or a limitation of the result; none changes a
calculation.  The rules run in a fixed order and the list keeps that order.
"""

from __future__ import annotations

from collections.abc import Iterator

from .invariants import InternalInvariantError
from ..domain_catalog import PRODUCT_YEAR_RANGE
from .formatting import dms_text
from .method_status import METHOD_STATUS_PROVISIONAL
from .module_state import EVENT_SEARCH_REASON_CODES, MODULE_COMPUTED
import datetime as dtmod
from zoneinfo import ZoneInfo

from .planetary_hours import NO_DIURNAL_CYCLE
from .time_utils import (
    PRC_1988_DISPUTED_LOCAL_INTERVAL,
    PRC_1988_DST_SOURCE_REF,
    TZDB_PRE_1970_SOURCE,
    prc_1988_dst_start_disputed,
)

# The reader's name of each module, for the sentences a person reads on the page
# and in the exports.  The response keeps the keys where a program reads them
# (calculation_policy.modules, affected_paths); a test holds this table to the
# dossier's module set and the two states only the warnings read.
MODULE_NAMES_ZH = {
    "core_positions": "核心天體位置",
    "house_division": "宮位分割",
    "planet_in_house": "行星落宮",
    "aspects": "相位",
    "fixed_stars": "恆星",
    "outer_planets": "外行星",
    "chiron": "凱龍星",
    "south_nodes": "南交點",
    "anti_vertex": "反宿命點",
    "lunar_apsides": "Lilith 與 Priapus",
    "parallax_moon": "站心月亮",
    "essential_dignities": "本質尊貴",
    "antiscia": "反照點",
    "sect": "日夜盤",
    "lots": "阿拉伯點",
    "void_of_course": "月空亡",
    "declination_aspects": "赤緯平行與反平行",
    "lunar_phases": "朔望",
    "eclipses": "日月食",
    "rise_set_transits": "升降與中天",
    "planetary_hours": "行星日與行星時",
    "dodecatemoria": "十二分部",
    "lunar_mansions": "月宿",
    "solar_phase": "焦傷與光束下",
    "classical_classifications": "行星與宮的古典分類",
    "extra_angles": "額外角點",
    "birth_time_sensitivity": "出生時刻敏感度",
    "prenatal_syzygy": "產前朔望",
}


# Why an event search produced nothing, one clause per reason code: leaving
# the bundled coverage is the request's, the other two are the server's.
EVENT_SEARCH_NOTICE_PREFIX_ZH = "星盤主體照常算出，但下列項目這次沒有結果"
EVENT_SEARCH_CAUSES_ZH = {
    EVENT_SEARCH_REASON_CODES[0]: "{modules}：要找的日期超出本站星曆資料涵蓋的年代",
    EVENT_SEARCH_REASON_CODES[1]: (
        "{modules}：伺服器少了計算這一項所需的星曆資料檔（這是本站的問題，不是你的輸入有誤）"
    ),
    EVENT_SEARCH_REASON_CODES[2]: (
        "{modules}：天文計算程式在找這些事件時出錯（這是本站的問題，不是你的輸入有誤）"
    ),
}


def _module_names(keys: list[str]) -> str:
    return "、".join(MODULE_NAMES_ZH[key] for key in keys)


def _warning(
    code: str,
    severity: str,
    message: str,
    source: str,
    affected_paths: list[str],
    params: dict | None = None,
) -> dict:
    # `code` and `params` are the warning; `message` is its Traditional Chinese
    # sentence for a reader without a catalogue.  `params` holds only numbers,
    # booleans, keys and closed-set codes, so another language can write the same
    # sentence from them without parsing `message`.
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "params": params or {},
        "source": source,
        "affected_paths": affected_paths,
    }


# Presentation thresholds flag sensitivity without changing calculations.  The
# zone check is a method-layer signal, not a refusal.  Calibration: the most
# extreme legal pairing in the world is
# western China, where Kashgar at 76E runs on Beijing time — 2.93 hours.  3.5
# lets that through and still catches a zone picked from the wrong continent.
GEOGRAPHIC_ZONE_INCOHERENCE_HOURS = 3.5
SIGN_BOUNDARY_WARNING_DEGREES = 1.0
CUSP_PROXIMITY_WARNING_DEGREES = 1.0


def _zone_incoherence_warnings(
    longitude: float, utc_offset_hours: float
) -> Iterator[dict]:
    # Coordinates and a zone each pass their own validation; their relationship
    # belongs to neither field, so a Taipei latitude paired with a New York zone
    # produced a chart that is wrong in a way nothing said out loud.
    solar_offset_hours = longitude / 15.0
    # UTC+14 and UTC-10 name the same civil-time neighbourhood across the
    # date line.  Compare offsets on the 24-hour circle, not a line.
    divergence = abs((solar_offset_hours - utc_offset_hours + 12.0) % 24.0 - 12.0)
    if divergence > GEOGRAPHIC_ZONE_INCOHERENCE_HOURS:
        yield _warning(
            "geographic_timezone_incoherence",
            "warning",
            (
                f"這個經度的地方平太陽時約為 UTC{solar_offset_hours:+.2f}，"
                f"而所選時區的偏移是 UTC{utc_offset_hours:+.2f}，"
                f"相差 {divergence:.2f} 小時，超過 "
                f"本產品設定的 {GEOGRAPHIC_ZONE_INCOHERENCE_HOURS} 小時提示門檻。"
                "政治時區（如中國西部）、歷史地方時或極區作業時制可能是合法的例外；"
                "計算仍依你提供的值完成，不會自動改動輸入。請確認座標與時區是否同屬一地。"
            ),
            "astronomical_data.time",
            ["astronomical_data.time", "astronomical_data.angles"],
            {
                "solar_offset_hours": solar_offset_hours,
                "utc_offset_hours": utc_offset_hours,
                "divergence_hours": divergence,
                "threshold_hours": GEOGRAPHIC_ZONE_INCOHERENCE_HOURS,
            },
        )


# What a house system that is not a quadrant division keeps at high latitude, and
# how it still draws its boundaries when the MC is below the horizon.  Only these
# systems reach either sentence: the quadrant ones are flagged or refused instead.
_NON_QUADRANT_LATITUDE_CLAUSE = {
    "W": "所選為整宮制，宮界不受緯度影響；",
    "E": "所選為等分宮制（從上升點起每 30 度一宮），宮的大小不受緯度影響；",
}
_NON_QUADRANT_MC_BELOW_CLAUSE = {
    "W": "整宮制的宮界照樣由上升點所在的星座劃分",
    "E": "等分宮制的宮界照樣從上升點起每 30 度劃分",
}
# A system added later without its own sentence still gets a warning: one that
# claims nothing about how it behaves at this latitude, rather than a lookup
# error that would fail the whole chart.
_GENERIC_LATITUDE_CLAUSE = "所選宮位制的宮頭仍為 Swiss Ephemeris 的計算結果；"
_GENERIC_MC_BELOW_CLAUSE = "所選宮位制的宮頭仍為 Swiss Ephemeris 的計算結果"


def _latitude_regime_warnings(latitude_regime: dict | None, house_system_code: str) -> Iterator[dict]:
    if latitude_regime and latitude_regime["band"] != "ordinary":
        beyond_polar = latitude_regime["band"] == "beyond_polar_circle"
        distorted = latitude_regime["quadrant_distortion_expected"]
        # 警告也進預設投影與「運算結果」匯出，那裡不列輸入座標；這句只說區間與半球，
        # 輸入緯度留在驗算資料的 latitude_regime。
        side = "北" if latitude_regime["latitude"] > 0 else "南"
        yield _warning(
            (
                "latitude_beyond_polar_circle"
                if beyond_polar
                else "high_latitude_house_distortion"
            ),
            "warning" if distorted else "notice",
            (
                (
                    f"出生地在{side}極圈以內（{side}緯 "
                    f"{latitude_regime['polar_circle_threshold_degrees']:.2f}° 以上，"
                    "即 90° 減命盤時刻真黃赤交角）。"
                    if beyond_polar
                    else f"出生地屬高緯度（{side}緯 "
                    f"{latitude_regime['high_latitude_threshold_degrees']:g}° 以上）。"
                )
                + (
                    # 整天不升或不落的黃道度數只在極圈（90° − ε）以外才存在（houses.py
                    # 同一條件）；60° 到極圈之間只會宮位大小嚴重不均。
                    "所選為四分宮制，宮位大小在此緯度會嚴重不均，"
                    + ("部分黃道度數可能永不升起或永不落下；" if beyond_polar else "")
                    + "宮頭數值仍為 Swiss Ephemeris 的計算結果，但落宮結論對出生時刻高度敏感。"
                    if distorted
                    else _NON_QUADRANT_LATITUDE_CLAUSE.get(house_system_code, _GENERIC_LATITUDE_CLAUSE)
                    + "但地平座標與升降事件在此緯度仍可能退化。"
                )
            ),
            "houses.latitude_regime",
            [
                "derived_methods.house_division",
                "derived_methods.planet_in_house",
                "astronomical_data.angles",
            ],
            {
                "hemisphere": "north" if latitude_regime["latitude"] > 0 else "south",
                "threshold_degrees": (
                    latitude_regime["polar_circle_threshold_degrees"]
                    if beyond_polar
                    else latitude_regime["high_latitude_threshold_degrees"]
                ),
                "quadrant_distortion_expected": bool(distorted),
                "house_system_code": house_system_code,
            },
        )


def _mc_below_horizon_warnings(latitude_regime: dict | None, house_system_code: str) -> Iterator[dict]:
    if latitude_regime and latitude_regime["mc_below_horizon"] is True:
        yield _warning(
            "mc_below_horizon",
            "notice",
            (
                "中天（MC，黃道在上子午圈的那一點）此刻在地平線下；這只會在極圈內發生。"
                + _NON_QUADRANT_MC_BELOW_CLAUSE.get(house_system_code, _GENERIC_MC_BELOW_CLAUSE)
                + "，但「中天在天頂附近、是黃道最高點」的直觀在此不成立。"
                "同一情形下 Porphyry、Alcabitius、Campanus 與 Regiomontanus 不提供宮位。"
            ),
            "houses.latitude_regime",
            ["astronomical_data.angles", "derived_methods.house_division"],
            {"house_system_code": house_system_code},
        )


# Whole-sign houses 1 and 7 hold the rising and setting signs, which straddle
# the horizon; for a quadrant or an equal division the horizon is the 1st and
# 7th cusps (equal cusp 1 is the ASC and cusp 7 the DSC).
_WHOLE_SIGN_HOUSES_BELOW_HORIZON = frozenset(range(2, 7))
_WHOLE_SIGN_HOUSES_ABOVE_HORIZON = frozenset(range(8, 13))
_QUADRANT_HOUSES_BELOW_HORIZON = frozenset(range(1, 7))
_QUADRANT_HOUSES_ABOVE_HORIZON = frozenset(range(7, 13))


def _sect_house_hemisphere_warnings(
    sect: dict | None,
    essential_dignities: dict | None,
    planet_in_house: dict,
) -> Iterator[dict]:
    # 日夜盤看太陽中心的真高度，宮位看黃經落在哪一宮；兩者各依自己的規則算出。
    # 極圈內的午夜太陽或極夜，上升點與宮位方向退化，兩者可能互相矛盾。
    # 近地平帶內另有 sect_near_horizon_critical，這裡不重複。
    if sect and sect.get("executed") and sect.get("is_day") is not None:
        is_day, near, sect_path = sect["is_day"], sect.get("in_near_horizon_band"), "derived_methods.sect"
    else:
        dignity_sect = (essential_dignities or {}).get("sect") or {}
        if dignity_sect.get("selected_ruler_available") is not True:
            return
        is_day = dignity_sect.get("is_day")
        near = dignity_sect.get("in_near_horizon_band")
        sect_path = "derived_methods.essential_dignities"
    if is_day is None or near:
        return
    sun = next(
        (item for item in planet_in_house.get("placements", []) if item["key"] == "sun"),
        None,
    )
    if sun is None:
        return
    whole_sign = planet_in_house.get("house_system_code") == "W"
    below = _WHOLE_SIGN_HOUSES_BELOW_HORIZON if whole_sign else _QUADRANT_HOUSES_BELOW_HORIZON
    above = _WHOLE_SIGN_HOUSES_ABOVE_HORIZON if whole_sign else _QUADRANT_HOUSES_ABOVE_HORIZON
    house = sun["house"]
    if (is_day and house in below) or (not is_day and house in above):
        yield _warning(
            "sect_vs_house_hemisphere_disagree",
            "notice",
            (
                f"日夜盤依太陽中心的真高度判為{'日盤' if is_day else '夜盤'}，"
                f"但太陽落在第 {house} 宮，屬於宮位圖上{'地平線下' if is_day else '地平線上'}的半邊。"
                "這在極圈附近的午夜太陽或極夜時會發生：上升點與宮位的方向在此退化。"
                "兩者各依自己的規則算出，本產品不替你調和。"
            ),
            "sect_and_house_placement",
            [sect_path, "derived_methods.planet_in_house"],
            {
                "is_day": bool(is_day),
                "sun_house": house,
                "house_system_code": planet_in_house.get("house_system_code"),
            },
        )


def _near_cusp_warnings(planet_in_house: dict) -> Iterator[dict]:
    near_cusp = [
        placement
        for placement in planet_in_house.get("placements", [])
        if placement["distance_to_nearest_cusp_degrees"]
        <= CUSP_PROXIMITY_WARNING_DEGREES
    ]
    if near_cusp:
        yield _warning(
            "body_near_house_cusp",
            "notice",
            (
                "下列天體距最近宮頭在 "
                f"{CUSP_PROXIMITY_WARNING_DEGREES}° 以內，"
                "落宮對出生時刻誤差敏感（上升點每約 4 分鐘移動 1°）："
                + "、".join(
                    f"{item['name']}（第 {item['house']} 宮，"
                    f"距宮頭黃經差 {dms_text(item['distance_to_nearest_cusp_degrees'])}）"
                    for item in near_cusp
                )
            ),
            "planet_in_house.placements",
            ["derived_methods.planet_in_house.placements"],
            {
                "threshold_degrees": CUSP_PROXIMITY_WARNING_DEGREES,
                "bodies": [
                    {
                        "key": item["key"],
                        "house": item["house"],
                        "distance_degrees": item["distance_to_nearest_cusp_degrees"],
                    }
                    for item in near_cusp
                ],
            },
        )


def _near_sign_boundary_warnings(
    bodies: list[dict],
    aspect_participants_present: bool,
) -> Iterator[dict]:
    near_sign_boundary = [
        body
        for body in bodies
        if body.get("longitude") is not None
        and min(
            body["longitude"] % 30.0,
            30.0 - (body["longitude"] % 30.0),
        )
        <= SIGN_BOUNDARY_WARNING_DEGREES
    ]
    if near_sign_boundary:
        yield _warning(
            "body_near_sign_boundary",
            "notice",
            (
                "下列天體距星座邊界在 "
                f"{SIGN_BOUNDARY_WARNING_DEGREES}° 以內，"
                "星座歸屬對出生日期／時刻誤差敏感："
                + "、".join(
                    f"{body['name']}（"
                    f"{dms_text(min(body['longitude'] % 30.0, 30.0 - (body['longitude'] % 30.0)))}）"
                    for body in near_sign_boundary
                )
            ),
            "astronomical_data.bodies",
            # Name only paths present in this response.
            ["astronomical_data.bodies"]
            + (
                ["derived_methods.aspects.participants"]
                if aspect_participants_present
                else []
            ),
            {
                "threshold_degrees": SIGN_BOUNDARY_WARNING_DEGREES,
                "bodies": [
                    {
                        "key": body["key"],
                        "distance_degrees": min(
                            body["longitude"] % 30.0, 30.0 - (body["longitude"] % 30.0)
                        ),
                    }
                    for body in near_sign_boundary
                ],
            },
        )


def _sect_near_critical_warnings(
    sect: dict | None,
    essential_dignities: dict | None,
) -> Iterator[dict]:
    # 近地平的日夜盤不只影響阿拉伯點；本質尊貴的迦勒底界與三分性也依它選主，所以沒有
    # 請求阿拉伯點時也要發這個警告。受影響路徑依本次實際用到的地方列出。
    lots_near = bool(sect and sect.get("in_near_horizon_band"))
    dignity_sect = (essential_dignities or {}).get("sect") or {}
    dignities_near = bool(
        dignity_sect.get("in_near_horizon_band")
        and dignity_sect.get("sect_dependent_components")
    )
    if lots_near or dignities_near:
        tolerance = (sect or {}).get("near_horizon_band_half_width_degrees")
        if tolerance is None:
            tolerance = dignity_sect.get("near_horizon_band_half_width_degrees")
        if tolerance is None:
            raise RuntimeError("near-critical sect receipt lacks its tolerance")
        consequences = []
        consequence_codes = []
        affected = ["derived_methods.sect"] if sect else []
        if lots_near:
            consequences.append("阿拉伯點因此並列日盤與夜盤兩套公式")
            consequence_codes.append("lots_list_both_sect_formulas")
            affected.append("derived_methods.lots")
        if dignities_near:
            consequences.append(
                "本質尊貴的迦勒底界主與三分性主星依這個日夜盤選定，換一種邊界可能改變"
            )
            consequence_codes.append("dignity_rulers_follow_this_sect")
            affected.append("derived_methods.essential_dignities")
        yield _warning(
            "sect_near_horizon_critical",
            "warning",
            (
                "地心太陽真高度在地平上下 "
                f"{tolerance * 60:.0f} 角分內"
                "（本產品的近地平敏感提示帶，屬產品慣例）。判定本身仍是確定的，"
                "但以視日出等其他具名邊界可能得到相反的日夜盤；"
                + "；".join(consequences)
                + "。換算成出生時刻的寬度依緯度與季節而異。"
            ),
            affected[0],
            affected,
            {
                "band_half_width_degrees": tolerance,
                "consequences": consequence_codes,
            },
        )


def _topocentric_speed_warnings(bodies: list[dict]) -> Iterator[dict]:
    limited_topocentric_speeds = [
        body.get("key")
        for body in bodies
        if body.get("speed_position_derivative_status")
        == "known_internal_disagreement_for_sun_moon"
    ]
    if limited_topocentric_speeds:
        yield _warning(
            "topocentric_analytic_speed_limitation",
            "warning",
            "站心的速度欄位是 Swiss Ephemeris 以解析式算出的值；太陽與月亮的部分速度欄位已知"
            "不等於同次站心位置的有限差分導數。位置仍可使用，但"
            "這些速度欄位不得解讀為已驗證的導數精度。",
            "Swiss Ephemeris FLG_SPEED",
            ["astronomical_data.bodies"],
            {"body_keys": limited_topocentric_speeds},
        )


def _ambiguous_time_params(request, time_conversion: dict) -> dict:
    """The two readings of a repeated wall-clock time, from the zone itself."""

    timezone = request.timezone
    stated = request.datetime
    naive = dtmod.datetime(
        stated.year, stated.month, stated.day, stated.hour, stated.minute,
        int(stated.second),
    )
    zone = ZoneInfo(timezone.iana_name)
    other = naive.replace(tzinfo=zone, fold=1 - timezone.fold).utcoffset()
    if other is None:
        raise InternalInvariantError("other is not None")
    return {
        "timezone": timezone.iana_name,
        "fold": timezone.fold,
        "utc_offset_hours": time_conversion["utc_offset_hours"],
        "alternative_fold": 1 - timezone.fold,
        "alternative_utc_offset_hours": other.total_seconds() / 3600.0,
    }


def _time_scale_warnings(request, time_conversion: dict) -> Iterator[dict]:
    if time_conversion["dst_warning"]:
        yield _warning(
            "ambiguous_local_time",
            "warning",
            time_conversion["dst_warning"],
            "time_conversion",
            [
                "calculation_dossier.time_conversion",
                "astronomical_data.time",
            ],
            _ambiguous_time_params(request, time_conversion),
        )

    if time_conversion["swiss_time_input_semantics"] == "ut1_before_1972_swiss_rule":
        yield _warning(
            "pre_1972_ut1_input_semantics",
            "warning",
            "1972 年以前還沒有現行的國際標準時間（含閏秒的 UTC），所以本站把你填的出生時間，"
            "直接當作依地球自轉計算的世界時（UT1）。兩者差異極小（不到 1 秒），對星盤幾乎沒有影響；"
            "只是這裡標示的時間，不能拿來跟現代的 UTC 直接對照。",
            "Swiss Ephemeris handling_of_leap_seconds",
            ["calculation_dossier.time_conversion"],
        )
    if (
        time_conversion["swiss_time_input_semantics"]
        == "ut1_future_leap_table_stale_swiss_rule"
    ):
        yield _warning(
            "future_ut1_input_semantics",
            "warning",
            "國際上何時再加『閏秒』要事先公告，本站內建的閏秒表只涵蓋到約 2033 年 9 月 17 日。"
            "這天以後的時間，本站直接當作依地球自轉計算的世界時（UT1）。"
            "影響：行星位置可能有極小的誤差，上升點與宮位不受影響；換用的那一刻，時間會跳約 1 秒。",
            "Swiss Ephemeris handling_of_leap_seconds",
            ["calculation_dossier.time_conversion"],
        )
    delta_t_model = time_conversion["delta_t_model"]
    if delta_t_model["status"] == "far_epoch_extrapolation":
        yield _warning(
            "delta_t_far_epoch_extrapolation",
            "warning",
            "此年代的ΔT是Swiss內部遠期模型值；精度未由本產品獨立確立，"
            "不可把顯示的小數位讀成已知真值。依 Huber (2000) 外推模型，"
            f"不確定度量級約 {delta_t_model['uncertainty_order_seconds']:.0f} 秒"
            "（研究筆記所引，非權威信賴區間，未經第三方核對）。",
            "Swiss Ephemeris delta_t future estimate; Huber 2000 per the method research notes",
            ["calculation_dossier.time_conversion.delta_t_model"],
            {
                "delta_t_model_status": delta_t_model["status"],
                "uncertainty_order_seconds": delta_t_model["uncertainty_order_seconds"],
            },
        )
    elif delta_t_model["status"] in (
        "swiss_table_prediction",
        "near_future_extrapolation",
    ):
        yield _warning(
            "delta_t_extrapolated",
            "notice",
            "此日期的ΔT已超出Swiss表中的實測值，是預測或外推值（不確定度量級約 "
            f"{delta_t_model['uncertainty_order_seconds']:.0f} 秒）。1972 年起的輸入"
            "由 UTC 推得 UT1，ΔT 的誤差會移動恆星時、宮位與角點，不移動天體位置。",
            "Swiss Ephemeris delta_t table (TABEND 2028); method research notes",
            ["calculation_dossier.time_conversion.delta_t_model"],
            {
                "delta_t_model_status": delta_t_model["status"],
                "uncertainty_order_seconds": delta_t_model["uncertainty_order_seconds"],
            },
        )

    # A notice, not a refusal, and nothing more is
    # asked of the user.
    if (
        time_conversion["offset_status"]["historical_verification_status"]
        == "pre_1970_database_inferred_not_verified"
    ):
        yield _warning(
            "pre_1970_timezone_offset_inferred",
            "notice",
            (
                "1970 年以前的時區偏移由 IANA 時區資料庫推定。該資料庫自述 1970 年以前"
                "的資料多半來源不可靠，本次採用的偏移"
                f"（{time_conversion['timezone_label']}）未經歷史文獻核實。"
            ),
            TZDB_PRE_1970_SOURCE,
            ["calculation_dossier.time_conversion.offset_status"],
            {"timezone": time_conversion["timezone_label"]},
        )


def _utc_offset_label(offset: dtmod.timedelta) -> str:
    minutes = round(offset.total_seconds() / 60)
    sign = "-" if minutes < 0 else "+"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def prc_1988_dst_dispute_warnings(request) -> Iterator[dict]:
    # A notice of disagreeing sources, not a second chart: the calculation keeps
    # the tz database's offset.  Both offsets are read from the running zone
    # data (inside the interval and one hour on), not written here.
    timezone = request.timezone
    if timezone.mode != "iana":
        return
    stated = request.datetime
    local = dtmod.datetime(stated.year, stated.month, stated.day, stated.hour, stated.minute)
    if not prc_1988_dst_start_disputed(
        timezone.iana_name, request.birth_time_precision, local
    ):
        return
    zone = ZoneInfo(timezone.iana_name)
    start, end = PRC_1988_DISPUTED_LOCAL_INTERVAL
    used = (start + (end - start) / 2).replace(tzinfo=zone).utcoffset()
    summer = (end + dtmod.timedelta(hours=1)).replace(tzinfo=zone).utcoffset()
    if used is None or summer is None:
        raise InternalInvariantError("used is not None and summer is not None")
    yield _warning(
        "prc_1988_dst_start_disputed",
        "warning",
        (
            "1988 年中國夏令時間的起始日，資料來源說法不一：IANA 時區資料庫自 2018f 版起依"
            "《人民日報》1988 年 4 月 12 日頭版，定為 4 月 17 日 02:00 起；部分中文說明表寫"
            " 4 月 10 日起。你的出生時間落在兩說之間（1988-04-10 00:00 至 04-17 02:00），"
            f"本服務依時區資料庫採用 {_utc_offset_label(used)}；若依 4 月 10 日之說應為 "
            f"{_utc_offset_label(summer)}，換算出的世界時早 "
            f"{abs(summer - used).total_seconds() / 3600:g} 小時，上升點與宮位可能不同。"
            "本服務只算這一張盤，不替你改動時刻。"
        ),
        f"IANA tz database asia, Rule PRC (2018f); method source {PRC_1988_DST_SOURCE_REF}",
        ["calculation_dossier.time_conversion", "astronomical_data.time"],
        {
            "timezone": timezone.iana_name,
            "utc_offset_hours_used": used.total_seconds() / 3600.0,
            "utc_offset_hours_if_april_10": summer.total_seconds() / 3600.0,
            "difference_hours": abs(summer - used).total_seconds() / 3600.0,
        },
    )


def _supported_range_warnings(
    request,
    time_conversion: dict,
) -> Iterator[dict]:
    # The ephemeris segments are bounded in UTC, not in the local
    # calendar, so the boundary test is keyed to the UTC year of the instant
    # actually computed (a local 2399-12-31 at UTC-10 is UTC 2400-01-01; a
    # local 1901-01-01 00:30 at UTC+14 is UTC 1900-12-31).  The local year is
    # still consulted because date_only / approximate_hour sampling windows
    # span the local civil day around that instant.
    utc_year = int(str(time_conversion["utc_time"])[:4])
    boundary_years = {PRODUCT_YEAR_RANGE[0], PRODUCT_YEAR_RANGE[1]}
    if (
        utc_year in boundary_years
        or utc_year < PRODUCT_YEAR_RANGE[0]
        or utc_year > PRODUCT_YEAR_RANGE[1]
        or request.datetime.year in boundary_years
    ):
        yield _warning(
            "ephemeris_boundary_year",
            "warning",
            (
                "此日期位於目前產品 "
                f"{PRODUCT_YEAR_RANGE[0]}–{PRODUCT_YEAR_RANGE[1]} "
                f"支援範圍的邊界年份（判定以 UTC {utc_year} 年為準；"
                f"本地年份 {request.datetime.year}）。"
                "核心結果在實際星曆來源可用時仍會顯示；需要向支援範圍外"
                "搜尋的事件模組可能明確標為不可用。"
            ),
            "supported_year_range_policy",
            [
                "calculation_dossier.time_conversion.calendar",
                "calculation_dossier.provenance.event_modules",
            ],
            {
                "supported_year_range": list(PRODUCT_YEAR_RANGE),
                "utc_year": utc_year,
                "local_year": request.datetime.year,
            },
        )


def _mixed_origin_moon_warnings(request) -> Iterator[dict]:
    if request.options.moon_position_profile == "moon_only_topocentric_v1":
        yield _warning(
            "mixed_origin_moon_position",
            "warning",
            (
                "本次全盤採地心座標，但有效月亮改採觀測地站心座標。兩個月亮數值均保留；"
                "月亮位置、落宮、反照點、阿拉伯點、月空亡、赤緯與黃道相位、本質尊貴及"
                "出生時刻敏感度使用站心月亮。月相與日月食仍依地心視黃經，升降本來就以站心"
                "計算，日夜盤仍用地心太陽高度。這是刻意的混合原點研究 profile，"
                "不代表站心值普遍較準。"
            ),
            "moon_position_profile",
            [
                "astronomical_data.parallax_moon",
                "astronomical_data.bodies",
                "derived_methods",
            ],
        )


def _ephemeris_source_warnings(
    full_ephemeris_files_available: bool,
    input_files_unchanged_during_chart: bool,
    core_records: list[dict],
    fixed_star_records: list[dict],
    fixed_stars: list[dict],
) -> Iterator[dict]:
    if not input_files_unchanged_during_chart:
        yield _warning(
            "ephemeris_input_files_changed_during_chart",
            "warning",
            (
                "計算這張盤的期間，內附星曆檔被移除、替換或改寫；無法確認 Swiss 讀到的是哪一份檔案，"
                "因此所有物件都不宣稱使用了完整星曆。請重新計算。"
            ),
            "chart_input_file_identity",
            [
                "calculation_dossier.provenance",
                "calculation_dossier.engine.available_input_files",
            ],
        )
    if not full_ephemeris_files_available:
        yield _warning(
            "full_ephemeris_input_files_incomplete",
            "warning",
            "啟動時未偵測到完整的主要行星與月球 Swiss Ephemeris 檔案。",
            "engine_startup_check",
            [
                "calculation_dossier.engine.available_input_files",
                "calculation_dossier.provenance",
            ],
        )

    fallback_core = [
        record["key"]
        for record in core_records
        if record["used_full_ephemeris"] is False
    ]
    fallback_stars = [
        record["key"]
        for record in fixed_star_records
        if record["used_full_ephemeris"] is False
    ]
    if fallback_core or fallback_stars:
        yield _warning(
            "ephemeris_fallback_detected",
            "warning",
            "部分物件未使用完整 Swiss Ephemeris files；請依 retflag 明細核對。",
            "actual_retflags",
            [
                "calculation_dossier.provenance.core_objects",
                "calculation_dossier.provenance.fixed_stars",
            ],
            {"core_keys": fallback_core, "fixed_star_keys": fallback_stars},
        )

    failed_stars = [
        star["key"]
        for star in fixed_stars
        if star.get("error")
    ]
    if failed_stars:
        yield _warning(
            "fixed_star_query_failed",
            "warning",
            f"固定星查詢失敗：{', '.join(failed_stars)}",
            "fixed_star_results",
            ["astronomical_data.fixed_stars"],
            {"fixed_star_keys": failed_stars},
        )


def _module_state_warnings(
    states: dict,
    modules: dict,
    methodology: dict,
) -> Iterator[dict]:
    # A refused event search is recognised by its recorded reason code, wherever
    # the module keeps its state (VOC on its own module object).
    refused_by_reason = {
        reason: [
            name
            for name, state in states.items()
            if state["requested"]
            and not state["available"]
            and state["reason_code"] == reason
        ]
        for reason in EVENT_SEARCH_REASON_CODES
    }
    event_not_applicable_modules = [
        name for names in refused_by_reason.values() for name in names
    ]
    clauses = [
        EVENT_SEARCH_CAUSES_ZH[reason].format(modules=_module_names(names))
        for reason, names in refused_by_reason.items()
        if names
    ]
    if clauses:
        yield _warning(
            "module_not_applicable",
            "notice",
            EVENT_SEARCH_NOTICE_PREFIX_ZH + "。" + "；".join(clauses) + "。",
            "provenance.event_modules",
            [
                "calculation_dossier.calculation_policy.modules",
                "calculation_dossier.provenance.event_modules",
            ],
            {
                "modules_by_reason": {
                    reason: names for reason, names in refused_by_reason.items() if names
                },
            },
        )

    # No sunrise and sunset within one diurnal cycle is a fact of the place and
    # season, not of the request's mode; it has its own notice.
    no_diurnal_cycle_modules = [
        name
        for name, state in states.items()
        if state["requested"]
        and not state["available"]
        and state["reason_code"] == NO_DIURNAL_CYCLE
    ]
    if no_diurnal_cycle_modules:
        yield _warning(
            "no_sunrise_sunset_cycle",
            "notice",
            (
                "出生地在這段時間沒有一天一次的日出與日落（極晝、極夜或其前後幾天），"
                f"因此未產生結果：{_module_names(no_diurnal_cycle_modules)}"
            ),
            "calculation_policy.modules",
            [f"derived_methods.{name}" for name in no_diurnal_cycle_modules],
            {"modules": no_diurnal_cycle_modules},
        )

    not_applicable_modules = [
        name
        for name, status in modules.items()
        if (
            status == "not_applicable"
            and name not in event_not_applicable_modules
            and name not in no_diurnal_cycle_modules
        )
    ]
    if not_applicable_modules:
        yield _warning(
            "module_not_applicable_in_mode",
            "notice",
            (
                "這次的請求條件（計算中心、座標框架或出生時刻的把握程度）不適用下列模組，"
                f"因此未產生結果：{_module_names(not_applicable_modules)}"
            ),
            "calculation_policy.modules",
            [
                "calculation_dossier.calculation_policy.computation_mode.center",
                "calculation_dossier.calculation_policy.modules",
                *[
                    f"derived_methods.{name}"
                    for name in not_applicable_modules
                    if name in methodology["items"]
                ],
            ],
            {"modules": not_applicable_modules},
        )

    for name, item in methodology["items"].items():
        if (
            item["execution_status"] == MODULE_COMPUTED
            and item["method_status"] == METHOD_STATUS_PROVISIONAL
        ):
            yield _warning(
                "provisional_method_result",
                "notice",
                f"{_module_names([name])}已計算，但方法仍待審閱，不能視為正式採用。",
                item["response_path"],
                [item["response_path"]],
                {"module": name},
            )


def _true_position_warnings(
    request,
    horizon_contract_present: bool,
) -> Iterator[dict]:
    if request.computation_mode.position_mode == "true":
        yield _warning(
            "true_position_refraction_semantics_provisional",
            "notice",
            (
                "你選了『真位置』：不計入光從天體傳到地球途中所花的時間，也不計地球運動造成的方向偏移，"
                "得到天體在幾何上實際所在的方向，而不是肉眼看到的方向。大氣折射（空氣把光線折彎，"
                "使天體看起來比實際高一點）屬於『肉眼看到的樣子』，和真位置的前提互相衝突，"
                "所以本站在這個模式下不列出含折射的『看起來的高度』，日出、日落等時刻則照肉眼可見的"
                "定義計算。大氣折射的這項處理只涉及高度與升落時刻，"
                "不影響行星所在的星座與度數。"
            ),
            "product_method_audit_pending",
            [
                "calculation_dossier.calculation_policy.computation_mode",
                "astronomical_data.atmosphere",
            ],
        )
        # Horizon events retain their own apparent topocentric frame.
        # Only when the module produced the contract it points at.
        if request.options.include_rise_set_transits and horizon_contract_present:
            yield _warning(
                "horizon_events_keep_apparent_frame_under_true_position",
                "notice",
                (
                    "你選了『真位置』，也就是不含大氣折射等視覺效果的幾何位置，"
                    "所以這裡不列出天體『看起來』離地平線多高，因為那個數值一定含大氣折射，"
                    "和真位置混用會失真。『日出、日落』這類時刻則照常列出："
                    "日出的定義本來就是太陽上緣經過大氣折射、碰到地平線的那一刻，"
                    "所以這一項固定用肉眼看得到的位置計算，不跟著你選的模式。"
                ),
                "astronomical_data.horizon_events.contract.frame",
                [
                    "astronomical_data.horizon_events.contract.frame",
                    "calculation_dossier.calculation_policy.fixed_module_frames",
                    "astronomical_data.bodies",
                ],
            )


def _date_only_warnings(
    request,
    sensitivity_coverage: dict | None,
) -> Iterator[dict]:
    # Which method results the civil-day samples never revisited is the
    # sensitivity ledger's fact; the warning lists those paths instead of
    # re-deriving them from the options beside it.
    sensitivity_ledger = sensitivity_coverage or {}
    date_only_unscanned_paths = [
        path
        for path, state in sensitivity_ledger.items()
        if path.startswith("derived_methods.") and state == "not_evaluated"
    ]
    if (
        request.birth_time_precision == "date_only"
        and date_only_unscanned_paths
    ):
        yield _warning(
            "date_only_method_sensitivity_not_evaluated",
            "warning",
            (
                "這些方法結果只屬當地正午的可重現計算錨點，"
                "不是出生時刻判定；目前未評估它們在整個民用日"
                "（當地日曆上這一天的所有時刻，通常從午夜到下一個午夜）之內"
                "是否改變。"
            ),
            "birth_time_precision_date_only_policy",
            date_only_unscanned_paths,
        )

    if (
        request.birth_time_precision == "date_only"
        and sensitivity_ledger.get("astronomical_data.lunar_apsides")
        == "not_evaluated"
    ):
        yield _warning(
            "date_only_lunar_apsides_sensitivity_not_evaluated",
            "notice",
            (
                "Lilith／Priapus 數值只屬當地正午計算錨點；目前未評估"
                "它們在整個民用日（當地日曆上這一天的所有時刻，通常從午夜到下一個午夜）"
                "內的變化。"
            ),
            "birth_time_precision_date_only_policy",
            ["astronomical_data.lunar_apsides"],
        )


def _near_lunar_mansion_boundary_warnings(lunar_mansions: dict | None) -> Iterator[dict]:
    # Only for an exact birth time: a stated hour or civil day lists every
    # mansion the Moon is in, which already answers the question.
    if not lunar_mansions or lunar_mansions.get("birth_time_interval") is not None:
        return
    near = [
        placement
        for placement in lunar_mansions.get("placements") or []
        if placement["near_boundary"]
    ]
    if near:
        yield _warning(
            "moon_near_lunar_mansion_boundary",
            "notice",
            (
                "月亮離月宿的交界不到 1′，出生時刻差幾分鐘就可能落在相鄰的另一宿"
                "（月亮大約每 2 分鐘走 1′）："
                + "、".join(
                    f"{item['name']}（第 {item['mansion']['number']} 宿，"
                    f"距交界 {item['distance_to_nearest_boundary_degrees'] * 3600:.1f}″）"
                    for item in near
                )
            ),
            "derived_methods.lunar_mansions",
            ["derived_methods.lunar_mansions.placements"],
            {
                "placements": [
                    {
                        "key": item["key"],
                        "mansion_number": item["mansion"]["number"],
                        "distance_degrees": item["distance_to_nearest_boundary_degrees"],
                    }
                    for item in near
                ],
            },
        )


def _classical_sect_within_hour_warnings(classical: dict | None) -> Iterator[dict]:
    # A stated hour in which the Sun crosses the horizon: the module reads one
    # sect at the representative instant, but day and night both occur in the
    # hour, and every classification that follows the sect follows it.
    chart_sect = (classical or {}).get("chart_sect") or {}
    if chart_sect.get("across_stated_hour") != "differs_between_samples":
        return
    is_day = bool(chart_sect["is_day"])
    yield _warning(
        "classical_sect_differs_within_stated_hour",
        "warning",
        (
            "你給的出生時刻只到小時，而太陽在這一小時之內越過地平線："
            "這一小時裡有一段是日盤、一段是夜盤。"
            f"「{MODULE_NAMES_ZH['classical_classifications']}」照代表性時刻判為"
            f"{'日盤' if is_day else '夜盤'}；行星屬白天或夜晚一組、halb 與 hayyiz（hayz）"
            "都跟著日盤或夜盤判定，所以在這一小時內也可能改變。"
        ),
        "derived_methods.classical_classifications",
        [
            "derived_methods.classical_classifications.chart_sect",
            "derived_methods.classical_classifications.planets",
        ],
        {
            "representative_is_day": is_day,
            "sample_is_day": list(chart_sect["sample_is_day"]),
        },
    )


def structured_warnings(
    *,
    request,
    time_conversion: dict,
    full_ephemeris_files_available: bool,
    input_files_unchanged_during_chart: bool,
    core_records: list[dict],
    fixed_star_records: list[dict],
    fixed_stars: list[dict],
    modules: dict,
    methodology: dict,
    states: dict,
    bodies: list[dict],
    planet_in_house: dict,
    latitude_regime: dict | None,
    sect: dict | None,
    sensitivity_coverage: dict | None,
    aspect_participants_present: bool,
    horizon_contract_present: bool,
    essential_dignities: dict | None,
    lunar_mansions: dict | None = None,
    classical_classifications: dict | None = None,
    effective_request=None,
) -> list[dict]:
    # The time conversion ran on the effective request (an approximate hour's
    # representative minute), so its repeated-time readings are read there.
    time_request = effective_request if effective_request is not None else request
    return [
        # 前五條是敏感度提示，不是錯誤：計算結果本身有效，但若出生時刻或座標有一點
        # 誤差，這個結論就會翻掉，而使用者無從自行看出這一點。
        *_zone_incoherence_warnings(
            request.location.longitude, time_conversion["utc_offset_hours"]
        ),
        *_latitude_regime_warnings(latitude_regime, request.options.house_system),
        *_mc_below_horizon_warnings(latitude_regime, request.options.house_system),
        *_near_cusp_warnings(planet_in_house),
        *_near_sign_boundary_warnings(bodies, aspect_participants_present),
        *_near_lunar_mansion_boundary_warnings(lunar_mansions),
        *_sect_near_critical_warnings(sect, essential_dignities),
        *_sect_house_hemisphere_warnings(sect, essential_dignities, planet_in_house),
        *_classical_sect_within_hour_warnings(classical_classifications),
        *_topocentric_speed_warnings(bodies),
        *_time_scale_warnings(time_request, time_conversion),
        *prc_1988_dst_dispute_warnings(request),
        *_supported_range_warnings(request, time_conversion),
        *_mixed_origin_moon_warnings(request),
        *_ephemeris_source_warnings(
            full_ephemeris_files_available, input_files_unchanged_during_chart,
            core_records, fixed_star_records, fixed_stars,
        ),
        *_module_state_warnings(states, modules, methodology),
        *_true_position_warnings(request, horizon_contract_present),
        *_date_only_warnings(request, sensitivity_coverage),
    ]
