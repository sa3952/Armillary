"""宮位計算：單一宮位制的 12 宮宮頭與古典角點 (ASC/DSC/MC/IC/ARMC)。

恆星黃道下每一種宮位制都由 Swiss 直接以 ``FLG_SIDEREAL`` 計算（ARMC 是恆星時性質的
角度，Swiss 不做 ayanamsa 平移）。Whole Sign 必須如此才得到恆星黃道 30° 整數宮界；
先算 tropical Whole Sign 再減 ayanamsa 會得到落在任意度數的錯誤宮頭。P/R/B 也不用
「tropical 宮頭 − ayanamsa」：章動關閉時 ``ayanamsa_value`` 是相對平春分點的值，而
houses_ex 的 tropical 宮頭相對真春分點，ASC、MC 與每個宮頭會偏一個黃經章動
（≤ 約 17″），且 ASC 隨所選宮位制而異。Swiss 對恆星黃道不理會 ``FLG_NONUT``：天體黃經
與原生宮頭在章動開或關時都相同，所以同一時刻、同一地點只有一個 ASC。

Vertex、Equatorial Ascendant、Co-Ascendant(Koch/Munkasey)、Polar Ascendant 是
swe_houses_ex 附帶回傳的現代/技術性角點，非古典占星角點，因此不進入 `angles`
主要輸出，而是在 `options.include_extra_angles` 開啟時另闢
`astronomical_data.extra_angles` 輸出，每一項附上其定義來源與「非古典角點」標記；
`angles` 的鍵集合維持 asc/mc/desc/ic/armc 不變，既有消費端不受影響。

宮位／ASC／MC／地平系統本質上是「觀測者站在地表看天空」定義出來的概念，恆為地心
（或站心）視角。heliocentric/barycentric 請求不會走到這裡：chart_pipeline.py 依
frame_compatibility 的 house_division 規則判定不適用，宮位與角點回 not_applicable，
reason_code 為 non_earth_observer_center。
"""

import functools
import math

import swisseph as swe

from ..config import HOUSE_SYSTEMS, PRODUCT_YEAR_RANGE
from .method_status import method_receipt
from .module_state import computed_receipt
from .source_reading import SOURCE_READING_LEVELS
from .trace import Trace


# 四分宮制（Placidus/Regiomontanus/Alcabitius/Porphyry/Campanus）在高緯度會嚴重變形：宮位大小差距
# 拉大，Placidus 在超過黃赤交角補角（90° − ε，即極圈）之外失去標準半弧解，
# 因為該處存在永不升起或永不落下的黃道度數（|tan φ · tan δ| > 1，方法研究筆記）。
#
# 極圈門檻不硬編碼 66.5°：以命盤時刻的真黃赤交角算 90° − ε，
# 這也是 Swiss swe_houses 對 Placidus 改用 Porphyry 並回 ERR 的同一條界線，
# 所以「標成極區」與「拒算 Placidus」用同一個數。1900–2399 年間約 66.55°–66.61°。
# 60.0°：經驗上宮位大小已明顯不均、落宮對出生時刻誤差高度敏感的起點。
HIGH_LATITUDE_WARNING_DEGREES = 60.0
# Porphyry and Campanus put cusp 1 on the ASC and cusp 10 on the MC like the other
# three, so they share the quadrant sensitivity.  Equal is ASC + 30° steps: like
# whole sign its house sizes do not depend on latitude.
QUADRANT_HOUSE_SYSTEM_CODES = frozenset({"P", "R", "B", "O", "C"})
# Refused where the MC culminates below the horizon although Swiss still returns an
# ordered cycle: both divide the quadrants that the sunk MC bounds.  Regiomontanus
# and Campanus are refused in the same cells by the cusp-cycle check.
MC_BELOW_HORIZON_REFUSED_CODES = frozenset({"B", "O"})

# 宮位可用性四態（unavailable 仍 422）。
# 方法研究筆記的詞彙。available_polar_geometry 不是新的成功路徑：它只標記
# 「現行本來就算得出來、但落在極區帶」的結果；現行拒絕行為一律保留。
HOUSE_AVAILABILITY_STATES = (
    "available",
    "available_polar_geometry",
    "unstable",
    "unavailable",
)
HOUSE_AVAILABILITY_REASONS = (
    "unique_ascendant_undefined",        # |φ| ≥ 90°：地理極點無唯一上升點
    "placidus_no_semiarc",               # Placidus 於極區帶：標準半弧構造無解（產品選擇：全帶拒絕）
    "swiss_house_fallback_rejected",     # Swiss 對其他宮位制回 ERR／自動 fallback，本產品拒收
    "degenerate_cusp_cycle_rejected",    # 宮頭重複或未形成單一依序完整分割（含反向 Regiomontanus、Campanus）
    "quadrant_high_latitude_sensitivity",# 四分宮制於高緯度（≥60°，含極區帶）：對時刻／緯度微擾高度敏感
    "polar_band_geometry",               # 極區帶內的非四分宮制（整宮、等分宮）
    "mc_below_horizon_rejected",         # Alcabitius、Porphyry：中天（MC）在地平線下（比照 Regiomontanus 拒收）
)


def true_obliquity_degrees(jd_ut: float) -> float:
    return swe.calc_ut(jd_ut, swe.ECL_NUT, 0)[0][0]


def polar_circle_threshold_degrees(jd_ut: float) -> float:
    """極圈門檻：90° − 命盤時刻真黃赤交角。與 Swiss 的 Placidus 拒算界線相同。"""
    return 90.0 - true_obliquity_degrees(jd_ut)


@functools.cache
def product_polar_threshold_range_degrees() -> tuple[float, float]:
    """產品年份範圍內極圈門檻的上下界（向外取整到 0.01°）。

    拒絕本文只能說這個不含日期的範圍：門檻隨黃赤交角每百年約變 0.013°，
    取到 0.1° 時在約 1915–1919 年間由 66.5 變成 66.6，等於回帶出生年份的一個位元。
    章動讓真黃赤交角上下擺動（週期約 18.6 年、振幅約 0.0026°），所以不取兩端，
    而是每 10 日取樣一次整個範圍；向外取整到 0.01° 的餘裕大於取樣間的變化。
    """
    first, last = PRODUCT_YEAR_RANGE
    start = swe.julday(first, 1, 1, 0.0)
    end = swe.julday(last, 12, 31, 24.0)
    samples = [
        polar_circle_threshold_degrees(start + day)
        for day in range(0, int(end - start) + 1, 10)
    ]
    return math.floor(min(samples) * 100) / 100, math.ceil(max(samples) * 100) / 100


# 非古典角點的定義來源，隨值一起輸出，避免使用者把它們誤認為古典四角。
EXTRA_ANGLE_PROVENANCE = {
    "vertex": {
        "calculation_source": "swiss_ephemeris_houses_ex",
        "zh": "宿命點",
        # 「黃道與地平大圓在西方的交點」是**下降點**的定義，不是 Vertex。
        # Vertex 用的是卯酉圈 (prime vertical)：通過天頂、正東與正西的大圓，
        # 與地平圈垂直。數值本身取自 swe.houses_ex。
        "definition": "黃道與卯酉圈（prime vertical，過天頂與正東西的大圓）在西方的交點",
        "not_to_be_confused_with": "下降點（黃道與地平圈在西方的交點）",
        "provenance": "modern_20th_century_l_edward_johndro_and_charles_jayne",
    },
    "equatorial_ascendant": {
        "calculation_source": "swiss_ephemeris_houses_ex",
        "zh": "赤道上升點",
        "definition": "地理緯度視為 0 時的上升點（East Point）",
        "provenance": "technical_construction_not_a_classical_angle",
    },
    "co_ascendant_koch": {
        "calculation_source": "swiss_ephemeris_houses_ex",
        "zh": "共同上升點(Koch)",
        "definition": "Walter Koch 定義的共同上升點",
        "provenance": "modern_20th_century_walter_koch",
    },
    "co_ascendant_munkasey": {
        "calculation_source": "swiss_ephemeris_houses_ex",
        "zh": "共同上升點(Munkasey)",
        "definition": "Michael Munkasey 定義的共同上升點",
        "provenance": "modern_20th_century_michael_munkasey",
    },
    "polar_ascendant": {
        "calculation_source": "swiss_ephemeris_houses_ex",
        "zh": "極地上升點",
        "definition": "Munkasey 定義的極地上升點",
        "provenance": "modern_20th_century_michael_munkasey",
    },
    "anti_vertex": {
        "zh": "反宿命點",
        "definition": "Vertex 黃道經度的精確對蹠點（Vertex + 180° mod 360）",
        "provenance": "modern_20th_century_technical_angle",
        "calculation_source": "vertex_longitude_antipode",
        "derived_from": "vertex",
    },
}
EXTRA_ANGLE_SOURCE_LABEL = {
    "swiss_ephemeris_houses_ex": "swe.houses_ex 附帶回傳",
    "vertex_longitude_antipode": "由 Vertex 黃經對蹠導出",
}


class HouseSystemUnavailableError(Exception):
    """The selected house system is not mathematically available at this latitude."""

    code = "house_system_unavailable"

    def __init__(
        self,
        *,
        code: str,
        name: str,
        latitude: float,
        reason: str | None = None,
        reason_code: str = "swiss_house_fallback_rejected",
    ):
        assert reason_code in HOUSE_AVAILABILITY_REASONS, reason_code
        self.house_system = code
        self.latitude = latitude
        self.reason_code = reason_code
        # 422 detail 的收據：閉集 reason_code，並說明拒絕是產品選擇、幾何理由是什麼。
        self.detail_extra = {
            "availability": "unavailable",
            "reason_code": reason_code,
            "house_system": code,
            "latitude": latitude,
            "refusal_basis": "product_choice",
            "geometric_reason": reason or "Swiss Ephemeris 對此宮位制回報錯誤或自動改用其他宮位制，本產品不接受替代結果",
            # 隱私：拒絕本文不回帶命盤時刻的門檻（90° − 真黃赤交角）。取到 0.1° 也不行：
            # 它在 1915–1919 年間由 66.5 變成 66.6，仍是出生年份的一個位元。拒絕只說公式與
            # 產品年份範圍內的上下界（常數，見 geometric_reason）；成功回應保留全精度。
        }
        if reason:
            message = (
                f"{name} ({code}) 在緯度 {latitude}° 產生退化宮頭（{reason}）；"
                "請改用此緯度可定義的宮位制。"
            )
        else:
            message = (
                f"{name} ({code}) 在緯度 {latitude}° 無法計算；"
                "請改用此緯度可定義的宮位制。"
            )
        super().__init__(message)


def _has_duplicate_cusps(cusps: tuple[float, ...], tolerance: float = 1e-7) -> bool:
    normalized = [cusp % 360.0 for cusp in cusps]
    for index, left in enumerate(normalized):
        for right in normalized[index + 1:]:
            difference = abs((left - right + 180.0) % 360.0 - 180.0)
            if difference < tolerance:
                return True
    return False


def _has_invalid_cusp_cycle(
    cusps: tuple[float, ...], tolerance: float = 1e-7
) -> bool:
    """Reject distinct cusp lists that wind around the zodiac more than once."""

    normalized = [cusp % 360.0 for cusp in cusps]
    spans = [
        (normalized[(index + 1) % 12] - normalized[index]) % 360.0
        for index in range(12)
    ]
    return (
        any(span <= tolerance or span >= 180.0 for span in spans)
        or not math.isclose(sum(spans), 360.0, abs_tol=1e-6)
    )


def mc_true_altitude_degrees(armc: float, obliquity: float, latitude: float) -> float:
    """Geometric altitude of the MC, the ecliptic point on the upper meridian.

    Its right ascension is the ARMC (frame-independent, so a sidereal chart
    gives the same answer), so tan(delta) = sin(ARMC) tan(eps); on the upper
    meridian the altitude is 90 - |phi - delta|.
    """
    declination = math.degrees(
        math.atan(math.sin(math.radians(armc)) * math.tan(math.radians(obliquity)))
    )
    return 90.0 - abs(latitude - declination)


def compute_houses(house_system_code: str, jd_ut: float, location, ctx, trace: Trace) -> dict:
    sidereal = ctx.mode.zodiac == "sidereal"
    houses_flags = swe.FLG_SIDEREAL if sidereal else 0

    def shift(lon):
        # Normalisation only: Swiss already returns the requested zodiac.
        return lon % 360.0

    code = house_system_code
    name = HOUSE_SYSTEMS.get(code, code)
    refusal = functools.partial(
        HouseSystemUnavailableError, code=code, name=name, latitude=location.latitude
    )
    # One Swiss ECL_NUT call serves the Placidus refusal and latitude_regime.
    obliquity = true_obliquity_degrees(jd_ut)
    polar_threshold = 90.0 - obliquity
    if abs(location.latitude) >= 90.0:
        raise refusal(
            reason="地理極點的上升點在數學上未定義",
            reason_code="unique_ascendant_undefined",
        )
    if code == "P" and abs(location.latitude) >= polar_threshold:
        # 產品選擇：整個極區帶拒絕，不逐時刻判半弧是否有解。
        # 幾何理由：|φ| ≥ 90° − ε 時存在永不升起／永不落下的黃道度數，
        # 標準 Placidus 半弧三分對這些度數無解；Swiss 在同一界線改用 Porphyry。
        raise refusal(
            reason=(
                "緯度絕對值 ≥ 極圈門檻（90° − 命盤時刻真黃赤交角；{}–{} 年間在 {:.2f}°–{:.2f}° 之間）："
                "部分黃道度數永不升起或永不落下，標準 Placidus 半弧構造無解；"
                "本產品選擇在整個極區帶拒絕，不逐時刻判定"
            ).format(*PRODUCT_YEAR_RANGE, *product_polar_threshold_range_degrees()),
            reason_code="placidus_no_semiarc",
        )
    try:
        cusps, ascmc = swe.houses_ex(
            jd_ut,
            location.latitude,
            location.longitude,
            code.encode(),
            houses_flags,
        )
    except swe.Error as exc:
        raise refusal(reason_code="swiss_house_fallback_rejected") from exc
    if code != "W" and (
        _has_duplicate_cusps(cusps) or _has_invalid_cusp_cycle(cusps)
    ):
        raise refusal(
            reason="十二宮宮頭未形成單一、依序且完整的黃道分割（含反向排列的宮頭循環；本產品拒收，不宣稱數學上不可用）",
            reason_code="degenerate_cusp_cycle_rejected",
        )
    # In the polar band the MC can culminate below the horizon.  Regiomontanus
    # and Campanus cusps then stop forming one ordered cycle (refused above;
    # measured: in exactly these cells), while Alcabitius and Porphyry still
    # yield an ordered cycle built on the sunk MC.  The product refuses them in
    # the same cells.
    if code in MC_BELOW_HORIZON_REFUSED_CODES and (
        mc_true_altitude_degrees(ascmc[2], obliquity, location.latitude) < 0.0
    ):
        raise refusal(
            reason=(
                "中天（MC，黃道在上子午圈的那一點）此刻在地平線下，這只會在極圈內發生。"
                f"{name} 先用上升點與中天把天空分成四段，再各分成三宮；平常中天在地平線上方，"
                "四段是地平線上、下各兩段，中天沉到地平線下時，這四段就不再是這個方法設想的樣子。"
                "宮頭在數學上仍算得出，但本產品比照同一情形下的 Regiomontanus 與 Campanus 拒收，"
                "不宣稱數學上不可用。可以改用整宮或等分宮（每宮 30 度，不靠中天分宮），或不計算宮位"
            ),
            reason_code="mc_below_horizon_rejected",
        )

    cusps_shifted = [shift(c) for c in cusps]
    asc = shift(ascmc[0])
    mc = shift(ascmc[1])
    armc = ascmc[2]  # 恆星時性質，不做 ayanamsa 平移
    vertex = shift(ascmc[3])
    equatorial_ascendant = shift(ascmc[4])
    co_ascendant_koch = shift(ascmc[5])
    co_ascendant_munkasey = shift(ascmc[6])
    polar_ascendant = shift(ascmc[7])
    desc = (asc + 180.0) % 360.0
    ic = (mc + 180.0) % 360.0

    frame_notes = []
    if ctx.mode.ecliptic_frame == "j2000":
        frame_notes.append("天體黃經採 J2000 參考框架")
    # Sidereal bodies and cusps do not move with the nutation flag,
    # so the mean-frame warning is a tropical statement only.
    if not ctx.mode.nutation and not sidereal:
        frame_notes.append("天體黃經採不含章動的平均框架")
    if frame_notes:
        trace.add(
            "宮位與天體參考框架提醒",
            note="；".join(frame_notes)
            + "；宮頭／ASC／MC 仍由 swe.houses_ex 以當日真回歸框架計算。"
            "本程式不據此產生天體落宮判斷，兩組數值不可直接混合作落宮推論。",
        )
    elif not ctx.mode.nutation:
        trace.add(
            "宮位與天體參考框架提醒",
            note="恆星黃道下，章動開關不改變天體黃經與宮頭：恆星黃經扣除的是從同一個"
            "春分點量起的 ayanamsa，章動互相抵消；宮頭由 swe.houses_ex 以 FLG_SIDEREAL "
            "直接算出，同樣不隨章動開關改變。兩者在同一框架，落宮照常判定。",
        )

    trace.add(
        f"宮位制：{name} ({code})",
        formula=(
            "swe.houses_ex(JD_UT, 地理緯度, 地理經度, 宮位制代碼"
            + (", FLG_SIDEREAL)" if sidereal else ")")
        ),
        inputs={"JD(UT)": jd_ut, "緯度": location.latitude, "經度": location.longitude,
                "houses_ex_flags": houses_flags},
        result={
            "ASC": asc, "MC": mc, "ARMC": armc, "DESC": desc, "IC": ic,
            "12宮宮頭": cusps_shifted,
        },
        note="以下為 swisseph 附帶回傳、非古典占星角點，僅供技術核對：Vertex=%.4f，"
             "Equatorial Ascendant=%.4f，Co-Ascendant(Koch)=%.4f，Co-Ascendant(Munkasey)=%.4f，"
             "Polar Ascendant=%.4f" % (vertex, equatorial_ascendant, co_ascendant_koch,
                                        co_ascendant_munkasey, polar_ascendant),
    )

    extra_angles = {
        "vertex": vertex,
        "equatorial_ascendant": equatorial_ascendant,
        "co_ascendant_koch": co_ascendant_koch,
        "co_ascendant_munkasey": co_ascendant_munkasey,
        "polar_ascendant": polar_ascendant,
    }
    regime = latitude_regime(location.latitude, code, jd_ut, obliquity=obliquity, armc=armc)

    return {
        # `compute_planet_house_placements` reads this key, so the two core
        # modules compose without the web layer supplying it.
        "system_code": code,
        "system_name": name,
        "cusps": cusps_shifted,
        "asc": asc,
        "mc": mc,
        "desc": desc,
        "ic": ic,
        "armc": armc,
        "extra_angles": extra_angles,
        "latitude_regime": regime,
        "availability": house_availability(regime),
    }



def printed_angles(houses: dict) -> dict:
    """`astronomical_data.angles` for one computed house division.

    The chart and every birth-time sample print the angles through this one
    function, so a sample is compared field for field with what the page shows.
    """

    return {
        **computed_receipt("Swiss Ephemeris houses_ex"),
        "asc": houses["asc"],
        "mc": houses["mc"],
        "desc": houses["desc"],
        "ic": houses["ic"],
        "armc": houses["armc"],
    }


def printed_house_division(houses: dict, system_code: str) -> dict:
    """`derived_methods.house_division` for one computed house division."""

    return {
        "method": "swiss_ephemeris_house_division_v1",
        **method_receipt("house_division"),
        **computed_receipt("Swiss Ephemeris houses_ex"),
        "execution_status": "computed",
        "system_code": system_code,
        "system_name": houses["system_name"],
        "cusps": houses["cusps"],
        "angles_source": "astronomical_data.angles",
        "source_ref": HOUSE_SYSTEM_SOURCE_REF,
        # Four-state availability; `unavailable` never reaches here because it
        # is raised as HouseSystemUnavailableError (422).
        "availability": houses["availability"],
    }

def latitude_regime(
    latitude: float,
    house_system_code: str,
    jd_ut: float,
    *,
    obliquity: float | None = None,
    armc: float | None = None,
) -> dict:
    """描述本次計算的緯度處於哪一個「宮位制可信度」區間。

    這是純粹的幾何事實陳述（緯度是否超過極圈、所選宮位制是否為四分宮制），
    不含任何「應該改用哪一種宮位制」的建議——那屬於方法裁決。
    極圈門檻依命盤時刻的真黃赤交角計算；compute_houses 傳入它已讀到的交角。
    """

    magnitude = abs(latitude)
    is_quadrant = house_system_code in QUADRANT_HOUSE_SYSTEM_CODES
    if obliquity is None:
        obliquity = true_obliquity_degrees(jd_ut)
    polar_threshold = 90.0 - obliquity
    if magnitude >= polar_threshold:
        band = "beyond_polar_circle"
    elif magnitude >= HIGH_LATITUDE_WARNING_DEGREES:
        band = "high_latitude"
    else:
        band = "ordinary"
    return {
        "latitude": latitude,
        "band": band,
        "polar_circle_threshold_degrees": polar_threshold,
        "polar_circle_threshold_source": (
            "90° − 命盤時刻真黃赤交角（swe.calc_ut ECL_NUT）；與 Swiss swe_houses 的 "
            "Placidus 拒算界線相同；不再使用固定 66.5°"
        ),
        "true_obliquity_degrees": obliquity,
        "high_latitude_threshold_degrees": HIGH_LATITUDE_WARNING_DEGREES,
        "house_system_is_quadrant": is_quadrant,
        "quadrant_distortion_expected": is_quadrant and band != "ordinary",
        # Only possible inside the polar band; None when no ARMC was given
        # (a regime asked for without a chart instant).
        "mc_below_horizon": (
            None if armc is None
            else mc_true_altitude_degrees(armc, obliquity, latitude) < 0.0
        ),
    }


def house_availability(regime: dict) -> dict:
    """四態可用性。只描述已算出的結果；unavailable 由例外路徑產生。

    四態依嚴重度排序：available < available_polar_geometry < unstable < unavailable，
    同一宮位制在緯度變高時狀態只能變嚴重：四分宮制在極區帶的敏感度只會更高，不能在
    60° 至極圈之間標 unstable、過了極圈反而標成較輕的 available_polar_geometry。極區帶
    記在 latitude_regime.band，所以 available_polar_geometry 只給非四分宮制（整宮、等分宮）。
    """

    if regime["house_system_is_quadrant"] and regime["band"] != "ordinary":
        state, reason = "unstable", "quadrant_high_latitude_sensitivity"
    elif regime["band"] == "beyond_polar_circle":
        state, reason = "available_polar_geometry", "polar_band_geometry"
    else:
        state, reason = "available", None
    assert state in HOUSE_AVAILABILITY_STATES
    assert reason is None or reason in HOUSE_AVAILABILITY_REASONS
    return {
        "state": state,
        "reason_code": reason,
        # The two closed sets and their basis are constant: register entry
        # houses/availability.
        "vocabulary_source_ref": "houses/availability",
    }


HOUSE_SYSTEM_SOURCE_REF = "houses/systems"
_ORIGINAL, _TRANSLATION, _SECONDARY, _BIBLIOGRAPHIC = SOURCE_READING_LEVELS
# One row per code in config.HOUSE_SYSTEMS.  `definition` is the geometry the
# product computes (through swe.houses_ex); `history` says where the name and the
# idea come from, each citation with how far it was read.  Nothing here ranks
# the systems.
HOUSE_SYSTEM_SOURCES: dict[str, dict] = {
    "W": {
        "definition": "The rising sign is the whole first house; each later sign is the next house.",
        "definition_source": "this product's definition (methods page §07.1)",
        "history": [
            {
                "citation": (
                    "Vettius Valens, Anthology V.6 (Pingree 1986 pp. 215-216): a chart whose "
                    "degree-based MC falls in the ninth sign, cited on the methods page and "
                    "not re-read for this entry"
                ),
                "reading": _BIBLIOGRAPHIC,
            },
        ],
    },
    "P": {
        "definition": "Cusps 11, 12, 2 and 3 trisect each cusp degree's own semi-diurnal or semi-nocturnal arc.",
        "definition_source": "Swiss Ephemeris General Documentation §6.2.1 Placidus",
        "history": [
            {
                "citation": "Named after Placidus de Titis (1590-1668) (Swiss Ephemeris §6.2.1)",
                "reading": _SECONDARY,
            },
        ],
    },
    "R": {
        "definition": "The equator is divided into twelve 30° arcs from the meridian; great circles through "
        "the north and south points of the horizon carry the divisions to the ecliptic.",
        "definition_source": "Swiss Ephemeris General Documentation §6.2.3 Regiomontanus",
        "history": [
            {
                "citation": (
                    "Named after Johannes Müller of Königsberg, called Regiomontanus (1436-1476) "
                    "(Swiss Ephemeris §6.2.3)"
                ),
                "reading": _SECONDARY,
            },
        ],
    },
    "B": {
        "definition": "The ascendant's own semi-diurnal and semi-nocturnal arcs are trisected on the equator "
        "and projected to the ecliptic through the celestial poles.",
        "definition_source": "Swiss Ephemeris General Documentation §6.2.11 Alcabitus",
        "history": [
            {
                "citation": "Named after al-Qabīṣī (Alcabitius, d. 967) (Astrodienst FAQ on house systems)",
                "reading": _SECONDARY,
            },
        ],
    },
    "O": {
        "definition": "Each quadrant between ASC, MC, DSC and IC is divided into three equal parts of ecliptic longitude.",
        "definition_source": "Swiss Ephemeris General Documentation §6.2.6.1 Porphyry",
        "history": [
            {
                "citation": (
                    "The trisection of the quadrants appears in Vettius Valens, Anthology book III, in a "
                    "chapter on the active and inactive places (cited via secondary sources; the chapter "
                    "was not read, and R. Schmidt reads it as a measure of planetary activity rather than "
                    "a division into topics)"
                ),
                "reading": _SECONDARY,
            },
            {
                "citation": (
                    "Named after Porphyry of Tyre (3rd century), Introduction to the Tetrabiblos "
                    "(CCAG V.4; trans. Holden 2009); the chapter number was not verified"
                ),
                "reading": _BIBLIOGRAPHIC,
            },
        ],
    },
    "E": {
        "definition": "Twelve houses of 30° each, the first beginning at the ascendant's degree.",
        "definition_source": "Swiss Ephemeris General Documentation §6.2.5 Equal systems",
        "history": [
            {
                "citation": (
                    "Ptolemy, Tetrabiblos III.12 in Ashmand's translation (III.10 in Robbins): the places "
                    "used for the length of life are 30° each, the first from 5° above the horizon to 25° "
                    "below it. That rule starts 5° earlier than this construction, which starts at the "
                    "ascendant's degree"
                ),
                "reading": _TRANSLATION,
            },
            {
                "citation": (
                    "Astrodienst's house-system FAQ says equal houses have been used since antiquity, "
                    "without a named source"
                ),
                "reading": _SECONDARY,
            },
        ],
    },
    "C": {
        "definition": "The prime vertical is divided into twelve 30° arcs from the zenith; great circles through "
        "the north and south points of the horizon carry the divisions to the ecliptic.",
        "definition_source": "Swiss Ephemeris General Documentation §6.2.4 Campanus",
        "history": [
            {
                "citation": "Named after Campanus of Novara (13th century) (Swiss Ephemeris §6.2.4)",
                "reading": _SECONDARY,
            },
            {
                "citation": (
                    "The prime-vertical method was described earlier in Arabic sources: a treatise by Ibn "
                    "Muʿādh al-Jayyānī (11th century; studied by J. Casulleras) and, per J. D. North, "
                    "Horoscopes and History (1986) pp. 175-176, al-Bīrūnī; both cited via secondary "
                    "sources, not read"
                ),
                "reading": _SECONDARY,
            },
        ],
    },
}

METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    HOUSE_SYSTEM_SOURCE_REF: {
        "applies_to": "derived_methods.house_division.system_code",
        "reading_vocabulary": list(SOURCE_READING_LEVELS),
        "systems": HOUSE_SYSTEM_SOURCES,
        "note": "The product offers these systems on an equal footing and does not rank their historical fitness.",
    },
    "houses/availability": {
        "applies_to": "derived_methods.house_division.availability",
        "vocabulary": list(HOUSE_AVAILABILITY_STATES),
        "reason_vocabulary": list(HOUSE_AVAILABILITY_REASONS),
        "source": "本產品依緯度帶與宮位制是否為四分宮制所訂的四態分類",
    },
    "extra_angles": {
        "applies_to": "astronomical_data.extra_angles",
        "calculation_source_labels": dict(EXTRA_ANGLE_SOURCE_LABEL),
        "note": "皆非古典占星的四角。本產品輸出其數值，不對其占星用途表示任何立場。",
    },
}
