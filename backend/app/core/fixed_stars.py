"""恆星位置與星等（含完整赤緯相關資料），套用統一計算模式。

清單（domain_catalog.FIXED_STARS）上的恆星全部標為 `research_only`，
維持預設關閉、明示勾選才計算。逐星的幾何方法、orb 與歲差政策未裁決；清單依據哪些
古典文本記在內部來源表與方法頁，計算輸出不逐星標出處。

`research_only` 的意思是：**位置數值本身是天文計算結果，但「這顆星在古典占星中
如何使用」尚未有本產品採用的方法**。本模組因此只輸出座標與星等，不輸出任何
「合相成立」的判定——恆星合相要先選定幾何（黃道合相、與角點同升或中天、地平事件；
Anonymous of 379 用的是升起與中天，不是黃經合相：CCAG V/1, Boll–Cumont 1904,
pp.194–211），再定 orb 與歲差政策，這些都未裁決。

位置的出處是 Swiss Ephemeris `fixstar2_ut` 加上捆綁的 `sefstars.txt`。
逐星來源表（內部；tests/backend/fixtures/fixed_star_provenance.json）把每顆星
綁到 Swiss 實際比對到的 sefstars 行號與 sha256，並判定數值是否即 Hipparcos 2007 新歸算
（I/311）推到 J2000；常駐測試以不呼叫 Swiss 的 ERFA 公式鏈（DE441 地球狀態）對
/api/chart 三個日期核對黃經黃緯，容差與實測最大值寫在來源表：同一記錄、Hipparcos
2007 由 J1991.25 推算、SIMBAD 現值（部分星 SIMBAD 已改用 Gaia DR3，屬目錄漂移）。
不是 Hipparcos 2007 的記錄（α Cen 是雙星系統的值、θ¹ Eri 精度較低）逐星記下與
Hipparcos、SIMBAD 的差。星團沒有 HIP 號：記錄對 SIMBAD 與 Cantat-Gaudin & Anders 2020
的星團中心逐筆記下差距並設上限（鬼宿星團的記錄偏離中心約 22′），星等是整團合計，
輸出以 `magnitude_basis` 標明。沒有逐星對 Gaia 核對。

安全約束：星名為硬編碼常數，使用者無法控制傳入 Swiss Ephemeris
的字串。若未來開放自訂星名，必須先以 ASan 受控輸入重新評估 `libswe/sweph.c` 的
`fstar[41]` 越界候選。
"""

import swisseph as swe

from .invariants import InternalInvariantError
from ..domain_catalog import (
    FIXED_STAR_ZH_NAME_CHECKED,
    FIXED_STAR_ZH_NAME_CORRECTIONS,
    FIXED_STAR_ZH_NAME_STATES,
    FIXED_STAR_ZH_NAME_TABLES,
)
from ..ephemeris import FIXED_STAR, object_used_full_ephemeris
from .bodies import horizontal_fields, horizontal_position
from .formatting import degrees_number, longitude_number
from .module_state import module_state
from .trace import Trace

FIXED_STAR_METHOD_CLASSIFICATION = "research_only"
FIXED_STAR_SOURCE = "Swiss Ephemeris fixstar2_ut"
# All failing: not computed.  Some failing: usable, but says so.
FIXED_STAR_REASON_CODES = ("fixed_star_query_failed", "fixed_star_query_partially_failed")
# What `magnitude` measures. Closed set: one star's V magnitude, or a cluster's
# integrated magnitude (the whole cluster's light summed, not one star).
FIXED_STAR_MAGNITUDE_BASES = ("single_star", "cluster_integrated")


def _canonical_catalog_name(query: str, matched: str) -> str:
    """Keep Swiss catalog identity while removing platform-only name formatting."""

    query_name, _, query_code = query.partition(",")
    matched_name, _, matched_code = matched.partition(",")
    same_name = "".join(query_name.split()).casefold() == "".join(
        matched_name.split()
    ).casefold()
    name = query_name if same_name else matched_name.strip()
    code = matched_code.strip() or query_code.strip()
    return f"{name},{code}" if code else name


def _zh_name_status(key: str) -> str:
    for records in (FIXED_STAR_ZH_NAME_CORRECTIONS, FIXED_STAR_ZH_NAME_CHECKED):
        if key in records:
            return records[key]["status"]
    return "unverified"


def _zh_name_verification(star_defs: list) -> dict:
    """List every catalogue star's Chinese-name status; absence of a check is stated."""

    return {
        "states": list(FIXED_STAR_ZH_NAME_STATES),
        "status_by_key": {star["key"]: _zh_name_status(star["key"]) for star in star_defs},
        "source_ref": "fixed_stars/zh_names",
    }


def fixed_star_receipt(star_defs: list, requested: bool, results: list) -> dict:
    """恆星模組的分類收據與模組狀態，與座標結果分開，供 dossier 與前端一致引用。

    狀態由逐星結果量出：至少一顆查到才 available；部分失敗仍可用但附原因碼與成功／失敗數。
    """

    failed = sum(1 for star in results if star.get("error"))
    succeeded = len(results) - failed
    available = bool(requested and succeeded)
    return {
        "method_classification": FIXED_STAR_METHOD_CLASSIFICATION,
        **module_state(
            requested=requested,
            executed=requested,
            applicable=requested,
            available=available,
            source=FIXED_STAR_SOURCE if available else None,
            reason_code=(
                None if not requested
                else FIXED_STAR_REASON_CODES[0] if not succeeded
                else FIXED_STAR_REASON_CODES[1] if failed
                else None
            ),
        ),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "catalog_size": len(star_defs),
        "zh_name_verification": _zh_name_verification(star_defs),
        "outputs": "position_and_magnitude_only",
        "excluded": [
            "conjunction_verdicts",
            "orb_policy",
            "precession_policy",
            "per_star_source_attribution",
        ],
        # The explanation is the same for every chart: register entry fixed_stars/policy.
        "policy_source_ref": "fixed_stars/policy",
    }


def _failed_star_record(star: dict, magnitude_basis: str) -> dict:
    """A star Swiss could not answer: the computed record's fields, all null.

    `error` is the closed reason code, never Swiss's message, which can name
    the ephemeris directory and the instant asked for.
    """

    reason_code = FIXED_STAR_REASON_CODES[0]
    return {
        "key": star["key"],
        "name": star["zh"],
        "input_name": star["name"],
        "catalog_name": None,
        "error": reason_code,
        "longitude": None,
        "latitude": None,
        "distance_au": None,
        "right_ascension": None,
        "declination": None,
        "azimuth": None,
        "azimuth_reason_code": reason_code,
        "altitude_true": None,
        "altitude_apparent": None,
        "altitude_apparent_reason_code": reason_code,
        "magnitude": None,
        "magnitude_basis": magnitude_basis,
        "retflag_ecliptic": None,
        "retflag_equatorial": None,
        "retflag_horizontal_source": None,
        "used_full_ephemeris": None,
    }


def compute_fixed_stars(star_defs: list, jd_ut: float, ctx, atmosphere, trace: Trace) -> list:
    flags = ctx.base_flags
    equatorial_flags = ctx.equatorial_source_flags | swe.FLG_EQUATORIAL
    results = []
    for star in star_defs:
        name = star["name"]
        magnitude_basis = star.get("magnitude_basis", FIXED_STAR_MAGNITUDE_BASES[0])
        # Every Swiss call of one star is inside the one guard: a star Swiss
        # cannot answer is one failed star, never a failed chart.
        try:
            ecl, matched_name, retflag_ecl = swe.fixstar2_ut(name, jd_ut, flags)
            equ, _matched_name2, retflag_eq = swe.fixstar2_ut(
                name,
                jd_ut,
                equatorial_flags,
            )
            mag, _ = swe.fixstar2_mag(name)
            az = az_raw = true_alt = app_alt = None
            horizontal_retflag = None
            if ctx.horizon_meaningful:
                horizontal_flags = ctx.horizontal_source_flags
                if horizontal_flags == flags:
                    horizontal_ecl, horizontal_retflag = ecl, retflag_ecl
                else:
                    horizontal_ecl, _horizontal_name, horizontal_retflag = swe.fixstar2_ut(
                        name, jd_ut, horizontal_flags
                    )
                az, az_raw, true_alt, app_alt = horizontal_position(
                    jd_ut, ctx, atmosphere, horizontal_ecl
                )
        except swe.Error:
            trace.add(
                f"恆星 {star['zh']}({name}) 查詢失敗",
                result={"reason_code": FIXED_STAR_REASON_CODES[0]},
                note="⚠ Swiss Ephemeris 回報錯誤（可能缺少 sefstars.txt 或名稱不在星表中），已略過；"
                     "錯誤內容不對外輸出。",
            )
            results.append(_failed_star_record(star, magnitude_basis))
            continue

        # A star's place to 10⁻⁶° (the page's precision; the catalogue's own is
        # milliarcseconds at best) and its distance to the AU: the parallax a
        # catalogue distance comes from carries far fewer digits.
        ecl_lon, ecl_lat, dist = longitude_number(ecl[0]), degrees_number(ecl[1]), round(ecl[2]) + 0.0
        ra, dec = longitude_number(equ[0]), degrees_number(equ[1])
        if az is not None:
            az = longitude_number(az)
        if az_raw is not None:
            az_raw = longitude_number(az_raw)
        if true_alt is not None:
            true_alt = degrees_number(true_alt)
        if app_alt is not None:
            app_alt = degrees_number(app_alt)
        catalog_name = _canonical_catalog_name(name, matched_name)
        # An Earth-centred star position reads the Earth through the Moon
        # segment, which the retflag does not report.
        used_full_ephemeris = object_used_full_ephemeris(
            retflag_ecl, body=FIXED_STAR, flags=flags, jd_ut=jd_ut,
        ) and object_used_full_ephemeris(
            retflag_eq, body=FIXED_STAR, flags=equatorial_flags, jd_ut=jd_ut,
        )
        if ctx.horizon_meaningful:
            if horizontal_retflag is None:  # set in the guarded block above
                raise InternalInvariantError("horizontal_retflag is not None")
            used_full_ephemeris = used_full_ephemeris and object_used_full_ephemeris(
                horizontal_retflag, body=FIXED_STAR, flags=ctx.horizontal_source_flags,
                jd_ut=jd_ut,
            )

        trace.add(
            f"恆星 {star['zh']}（{catalog_name}）位置計算",
            formula="黃道使用計算模式旗標；赤道移除 sidereal 後加 FLG_EQUATORIAL",
            inputs={
                "JD(UT)": jd_ut,
                "氣壓(hPa；0=依海拔估算)": atmosphere.pressure_hpa or 0.0,
                "溫度(°C)": atmosphere.temperature_c,
                "地平座標來源flags(tropical of-date)": ctx.horizontal_source_flags,
            },
            result={
                "黃經": ecl_lon, "黃緯": ecl_lat,
                "赤經": ra, "赤緯": dec,
                **({"方位角Az(北=0,順時針)": az, "方位角Az(Swiss原始,南=0,向西)": az_raw, "真高度Alt": true_alt} if ctx.horizon_meaningful else {}),
                ("星等(整團合計)" if magnitude_basis == "cluster_integrated" else "星等"): mag,
            },
        )

        results.append({
            "key": star["key"],
            "name": star["zh"],
            "input_name": name,
            "catalog_name": catalog_name,
            "error": None,
            "longitude": ecl_lon,
            "latitude": ecl_lat,
            "distance_au": dist,
            "right_ascension": ra,
            "declination": dec,
            **horizontal_fields(ctx, az, true_alt, app_alt),
            "magnitude": mag,
            "magnitude_basis": magnitude_basis,
            "retflag_ecliptic": retflag_ecl,
            "retflag_equatorial": retflag_eq,
            "retflag_horizontal_source": horizontal_retflag,
            "used_full_ephemeris": used_full_ephemeris,
        })
    return results


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "fixed_stars/policy": {
        "applies_to": "astronomical_data.fixed_star_policy",
        "note": (
            "座標為天文計算結果（fixstar2_ut＋sefstars.txt）。每顆星的位置已用獨立換算，"
            "對 Hipparcos 衛星星表 2007 年新歸算與 SIMBAD 現值核對；少數記錄不是 Hipparcos "
            "2007 的值（例如南門二是整個雙星系統的值），另記差距；沒有逐星對 Gaia 核對。"
            "三個星團沒有 Hipparcos 編號，改對 SIMBAD 與 Cantat-Gaudin & Anders 2020 的星團中心"
            "核對：鬼宿星團的星表記錄偏離中心約 22′（黃經約 7′），照用；另兩個在 3′ 以內。"
            "星團的星等是整團合計（magnitude_basis），不是一顆星的亮度。"
            "不輸出合相判定：要先選幾何（黃道合相、同升或中天、地平事件），再定容許度"
            "與歲差。清單依據的古典文本見方法頁，計算結果不逐星標出處。"
        ),
    },
    "fixed_stars/zh_names": {
        "applies_to": "astronomical_data.fixed_star_policy.zh_name_verification",
        "note": "status_by_key 是每顆星中文名的核對狀態；所依對照表與更正紀錄如下。",
        "tables": dict(FIXED_STAR_ZH_NAME_TABLES),
        "corrections": {key: dict(record) for key, record in FIXED_STAR_ZH_NAME_CORRECTIONS.items()},
        "checked": {key: dict(record) for key, record in FIXED_STAR_ZH_NAME_CHECKED.items()},
    },
}
