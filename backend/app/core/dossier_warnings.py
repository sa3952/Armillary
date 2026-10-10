"""The calculation dossier's structured warnings, one function per rule.

A warning flags sensitivity or a limitation of the result; none changes a
calculation.  The rules run in a fixed order and the list keeps that order.
"""

from __future__ import annotations

from collections.abc import Iterator

from ..config import PRODUCT_YEAR_RANGE
from .method_status import METHOD_STATUS_PROVISIONAL
from .module_state import EVENT_SEARCH_REASON_CODES, MODULE_STATUSES
from .time_utils import TZDB_PRE_1970_SOURCE

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
    "extra_angles": "額外角點",
    "birth_time_sensitivity": "出生時刻敏感度",
}


def _module_names(keys: list[str]) -> str:
    return "、".join(MODULE_NAMES_ZH[key] for key in keys)


def _warning(
    code: str,
    severity: str,
    message: str,
    source: str,
    affected_paths: list[str],
) -> dict:
    return {
        "code": code,
        "severity": severity,
        "message": message,
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
        )


def _latitude_regime_warnings(latitude_regime: dict | None) -> Iterator[dict]:
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
                    else "所選為整宮制，宮界不受緯度影響；"
                    "但地平座標與升降事件在此緯度仍可能退化。"
                )
            ),
            "houses.latitude_regime",
            [
                "derived_methods.house_division",
                "derived_methods.planet_in_house",
                "astronomical_data.angles",
            ],
        )


def _mc_below_horizon_warnings(latitude_regime: dict | None) -> Iterator[dict]:
    if latitude_regime and latitude_regime["mc_below_horizon"] is True:
        yield _warning(
            "mc_below_horizon",
            "notice",
            (
                "MC（天頂點，黃道在上子午圈的那一點）此刻在地平線下；這只會在極圈內發生。"
                "整宮制的宮界照樣由上升點所在的星座劃分，但「MC 在天頂附近、是黃道最高點」"
                "的直觀在此不成立。同一情形下 Regiomontanus 與 Alcabitius 不提供宮位。"
            ),
            "houses.latitude_regime",
            ["astronomical_data.angles", "derived_methods.house_division"],
        )


# Whole-sign houses 1 and 7 hold the rising and setting signs, which straddle
# the horizon; for a quadrant division the horizon is the 1st and 7th cusps.
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
                    f"距宮頭黃經差 {item['distance_to_nearest_cusp_degrees']:.4f}°）"
                    for item in near_cusp
                )
            ),
            "planet_in_house.placements",
            ["derived_methods.planet_in_house.placements"],
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
                    f"{min(body['longitude'] % 30.0, 30.0 - (body['longitude'] % 30.0)):.4f}°）"
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
        affected = ["derived_methods.sect"] if sect else []
        if lots_near:
            consequences.append("阿拉伯點因此並列日盤與夜盤兩套公式")
            affected.append("derived_methods.lots")
        if dignities_near:
            consequences.append(
                "本質尊貴的迦勒底界主與三分性主星依這個日夜盤選定，換一種邊界可能改變"
            )
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
        )


def _time_scale_warnings(time_conversion: dict) -> Iterator[dict]:
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
        )

    if time_conversion["swiss_time_input_semantics"] == "ut1_before_1972_swiss_rule":
        yield _warning(
            "pre_1972_ut1_input_semantics",
            "warning",
            "Swiss Ephemeris在1972年前把utc_to_jd輸入視為UT1；"
            "civil-time標籤不可解讀為現代UTC leap-second尺度。",
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
            "Swiss Ephemeris判定內建閏秒表可能已過期（約2033-09-17起），把utc_to_jd輸入"
            "視為UT1；civil-time標籤不可解讀為UTC。ΔT的誤差因此移動天體位置，"
            "而不是恆星時與宮位；切換瞬間時刻約有1秒的不連續。",
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
        )


def _module_state_warnings(
    states: dict,
    modules: dict,
    methodology: dict,
) -> Iterator[dict]:
    # A refused event search is recognised by its recorded reason code, wherever
    # the module keeps its state (VOC on its own module object).
    event_not_applicable_modules = [
        name
        for name, state in states.items()
        if state["requested"]
        and not state["available"]
        and state["reason_code"] in EVENT_SEARCH_REASON_CODES
    ]
    if event_not_applicable_modules:
        yield _warning(
            "module_not_applicable",
            "notice",
            (
                "核心命盤仍可計算，但下列事件模組超出其完整資料"
                "搜尋範圍，因此未產生結果："
                f"{_module_names(event_not_applicable_modules)}"
            ),
            "provenance.event_modules",
            [
                "calculation_dossier.calculation_policy.modules",
                "calculation_dossier.provenance.event_modules",
            ],
        )

    not_applicable_modules = [
        name
        for name, status in modules.items()
        if (
            status == "not_applicable"
            and name not in event_not_applicable_modules
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
        )

    for name, item in methodology["items"].items():
        if (
            item["execution_status"] == MODULE_STATUSES[1]
            and item["method_status"] == METHOD_STATUS_PROVISIONAL
        ):
            yield _warning(
                "provisional_method_result",
                "notice",
                f"{name} 已計算，但方法仍待審閱，不能視為正式採用。",
                item["response_path"],
                [item["response_path"]],
            )


def _true_position_warnings(
    request,
    horizon_contract_present: bool,
) -> Iterator[dict]:
    if request.computation_mode.position_mode == "true":
        yield _warning(
            "true_position_refraction_semantics_provisional",
            "notice",
            "true position 與大氣折射同時使用時的產品語意仍待確認。",
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
                    "您選了 position_mode=true，因此天體與恆星的視高度"
                    "（altitude_apparent）已抑制為 null——"
                    "幾何方向與大氣折射是互斥前提，混用的數值無法解讀。"
                    "但升降事件模組仍會輸出視高度取樣，這不是疏漏："
                    "「升起」的定義就是天體**經過折射的上緣**穿過地平的時刻，"
                    "把折射拿掉，該事件本身就不存在。因此該模組一律使用"
                    "視位置＋站心框架，不跟隨 computation_mode，"
                    "其輸出的 contract.frame 欄位有完整宣告。"
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
                "不是出生時刻判定；目前未評估它們在整個 civil day 內"
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
                "它們在整個 civil day 內的變化。"
            ),
            "birth_time_precision_date_only_policy",
            ["astronomical_data.lunar_apsides"],
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
) -> list[dict]:
    return [
        # 前五條是敏感度提示，不是錯誤：計算結果本身有效，但若出生時刻或座標有一點
        # 誤差，這個結論就會翻掉，而使用者無從自行看出這一點。
        *_zone_incoherence_warnings(
            request.location.longitude, time_conversion["utc_offset_hours"]
        ),
        *_latitude_regime_warnings(latitude_regime),
        *_mc_below_horizon_warnings(latitude_regime),
        *_near_cusp_warnings(planet_in_house),
        *_near_sign_boundary_warnings(bodies, aspect_participants_present),
        *_sect_near_critical_warnings(sect, essential_dignities),
        *_sect_house_hemisphere_warnings(sect, essential_dignities, planet_in_house),
        *_topocentric_speed_warnings(bodies),
        *_time_scale_warnings(time_conversion),
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
