"""月空亡 (Void of Course)：候選入相位事件搜尋（含技法假設）與最終判定，明確分層。

搜尋本身已內含技法假設——採用哪些星體(古典七政)、哪些相位角(合相與四種傳統相位)、
以何種數值方法估計精確時刻——因此以具名 method 標註；「是否構成空亡」的最終布林判定
獨立成 determine_void_of_course()，不與搜尋結果混在一起，方便日後替換不同流派規則。

本模組實作的是「月亮離開現在的星座前不完成合相與四種傳統相位中的任何一個」＋要求相位
精確完成。兩個成分來歷不同：星座條件最晚見於 Lilly, Christian Astrology 1647 p.112，
更早亦見於 Māshāʾallāh；「必須在離座前精確完成、不採容許度」，後人文獻歸於 Al H.
Morrison（AFA Journal 1966 年 10 月有專文，原文未讀），更早的起源尚未查證。兩者
合起來的歷史歸屬仍未定（VOC_SOURCE_VERIFICATION；方法登記 `void_of_course`）。其他具名
定義：Ps.-Porphyry 的「未來 30° 內不與行星接合」（方法登記
`contested/void_of_course_definition`）；Antiochus 名下「一日一夜（約 13°）內不與任何行星
結合」之說只見二手轉述（Louis 2013 引 Gramaglia p.188），原文未核。方法名稱因此不含
"classical"；日後若要提供古典定義，應另立具名方法
並列（例如 hellenistic_30_degree_kenodromia_v1、lilly_moiety_application_v1），而非改寫
本方法。

數值解法：由 `core/root_finding.py` 的兩段式求根器求解，**換座邊界本身也以求根**而非
除法外插——月亮在 2.5 天內的黃經速度變化足以讓「(邊界 − 現在黃經) / 現在速度」產生
數分鐘到數十分鐘的誤差，而該誤差直接決定哪些候選相位算在邊界之內，也就直接決定空亡的
布林結果。
"""

import math

from ..config import BODY_ID_BY_KEY, CLASSICAL_BODIES, PTOLEMAIC_ASPECTS
from .aspects import EXACT_NOW_EPSILON_DEGREES
from .module_state import (
    PRODUCT_FORMULA_SOURCE,
    computed_receipt,
    not_applicable_receipt,
)
from .method_status import method_receipt
from .root_finding import SOLVER_NAME, find_crossings_detailed, wrap_to_signed_180
from .trace import Trace

VOC_METHOD_NAME = "modern_sign_bounded_exact_perfection_v1"

# 現行預設的來源尚未解決，而輸出必須說出這件事。
#
# `modern_sign_bounded_exact_perfection_v1` 的核心規則是「星座界線阻斷 application」，
# 由兩個成分組成：星座條件已在 Māshāʾallāh（Dykes 2008 p.443 節錄）與 Lilly 1647 p.112
# 讀到；「離座前精確完成」後人文獻歸於 Al H. Morrison（1966，原文未讀），更早的起源
# 未查證。收據明示未轉錄一手文本，且 `method_provenance` 說出合起來的歸屬未定，不只說
# 「現代、非古典」。
#
# 被揭露的是**規則本身的來源強度**，不是判定數值：換座時刻與相位完成時刻由求根器算出。
# 星座條件最晚見於 Lilly 1647 p.112，所以不把整條規則判給 20 世紀；「非古典」仍成立，
# 歸屬則未定，與 VOC_SOURCE_VERIFICATION 一致。
VOC_METHOD_PROVENANCE = "not_classical_attribution_unresolved"
# The two components have
# different histories, so each carries its own attribution; method_status is not
# raised.  Closed vocabularies.
VOC_SIGN_CONDITION_ATTRIBUTIONS = (
    "attested_masha_allah_and_lilly_1647_earliest_unresolved",
)
# The publisher's index locates Morrison's 1966 article; its text, and any
# earlier origin of the requirement, are not checked, so the code claims only
# that later literature attributes the requirement to him (the code's wording,
# "found in 20th-century literature", names where the attribution is found).
VOC_EXACT_PERFECTION_ATTRIBUTIONS = (
    "found_in_20th_century_literature_morrison_1966_earlier_origin_unchecked",
)
# What the response carries: status codes and a register reference.
VOC_SOURCE_STATUS = {
    "primary_texts_independently_transcribed": False,
    "sign_condition_attribution": VOC_SIGN_CONDITION_ATTRIBUTIONS[0],
    "exact_perfection_attribution": VOC_EXACT_PERFECTION_ATTRIBUTIONS[0],
    # Unchanged name: the attribution of the combined rule.
    "sign_boundary_rule_attribution": "unresolved",
    "source_ref": "void_of_course",
}
# The register entry: the citations behind those codes.
VOC_SOURCE_VERIFICATION = {
    "primary_texts_independently_transcribed": False,
    "sign_boundary_rule_attribution": "unresolved",
    "sign_condition": (
        "The Moon not perfecting an aspect before leaving its sign: Māshāʾallāh, "
        "On Reception ch.1 (Dykes 2008 p.443; ch.7, p.467, not checked); Lilly, "
        "Christian Astrology 1647 p.112 'Voyd of course' (bounded by the sign; the "
        "page does not mention moieties). Sahl's definition in the Latin "
        "Quadripartitum collection (Venice 1519) is that the Moon joins no planet "
        "and none joins it; it names neither the sign boundary nor an orb. "
        "An earlier explicit statement is attributed to Abū Maʿshar, Abbreviation "
        "III.21-22 (not consulted)."
    ),
    "exact_perfection": (
        "Later literature attributes requiring exact perfection before the sign exit "
        "to Al H. Morrison (an article in the AFA Journal, October 1966; the article "
        "was not read); an earlier origin has not been checked."
    ),
    "competing_attributions": (
        "al_h_morrison_20th_century",
        "medieval_arabic_transmission",
    ),
    "consulted": (
        "Lilly, Christian Astrology 1647 p.112",
        "Māshāʾallāh, On Reception ch.1 (Dykes 2008 p.443, in the translator's "
        "published excerpt pp.443-446)",
        "Sahl, 'De cursu planete vacui', in Quadripartitum Ptolomei ... (Venice "
        "1519; Seville copy, archive.org ARes08317, PDF p.246, left column)",
    ),
    "not_consulted": (
        "Al H. Morrison, 'Void of Course Moon Periods: Their Uses and What May "
        "Come of Ignoring Them', AFA Journal XXVIII.10 (October 1966) p.10: "
        "located through the AFA journal author index; the article was not read",
        "Māshāʾallāh, On Reception ch.7 (Dykes 2008 p.467)",
        "Abū Maʿshar, Abbreviation III.21-22 (Brill 1994 / ARHAT 1997)",
        "al-Qabīṣī, Introduction III (Warburg 2004)",
        "Sahl, Introduction §5.10 (Dykes 2008 p.35) and the Arabic text",
        "Bonatti, Tract 3 definition chapter",
    ),
    "consequence": (
        "method_status cannot be raised to adopted until the attribution is "
        "settled against a named edition"
    ),
}

# 換座搜尋視窗。
#
# 「月亮速度介於 11.7–15.4 度/日，故 30/11.7 ≈ 2.57 日，取 3.0 日有餘裕」這個
# 推理不能用：**那個速度區間只對地心成立**。實測
# topocentric 模式在高海拔測站可低到 6.21 度/日、高到 21.15 度/日——視差在一天
# 之內就能讓瞬時黃經速度變動一倍以上。以最低瞬時速度外推，跨越 30 度需要 4.83 日，
# 超過 3.0 日的視窗。
#
# 實際量測：在該測站掃描一整年、每 3 小時起算一次，最久的一次換座是 2.65 日，
# 且 topocentric 黃經在取樣中未曾倒退（monotonic），故「第一個根即換座時刻」的
# 前提成立。2.65 對 3.0 只有 12% 餘裕，而該量測只涵蓋一個測站一年，
# 因此視窗放寬到 6.0 日。搜尋是掃描式的，放寬只多花幾次星曆查詢。
_SIGN_EXIT_SEARCH_WINDOW_DAYS = 6.0
# 粗掃描步長 0.05 日（72 分鐘）。取 topocentric 上限 21.2 度/日再加上被相位行星
# 逆行的貢獻，單步最多移動約 1.1 度，遠低於 root_finding 區分真過零與環繞不連續
# 所需的 180 度。
_COARSE_STEP_DAYS = 0.05
# 收斂容差 1e-6 日約 0.086 秒。
_TOLERANCE_DAYS = 1e-6
# 「此刻精確」（計入判定的那一類）與相位模組用**同一條角度標準**：盤上時刻
# 月亮距精確相位 ≤ aspects.EXACT_NOW_EPSILON_DEGREES（1″），兩側皆算（剛要完成或剛完成）。
# 不用 ±1e-9 日之類的時間窗：那只有 JD 浮點最小間隔的約兩倍，實際上等於「浮點相等」，
# 在日月合相前 1 秒起盤時，相位表會寫「此刻精確」（0.50″），月空亡卻把同一個合相列為
# 1.09 秒後的未來候選。
# 1″ 換算成時間隨相對速度而變：日月約 2 秒、站心月亮最慢時約 4 秒。
#
# 判定依角度，求根只為了報出完成時刻與括號端點：在 ±_EXACT_NOW_ROOT_HALF_WINDOW_DAYS 內
# 求那一個根。月亮相對任何行星的黃經速度至少約 4 度/日（站心月亮最低 6.21 度/日減去
# 水星最快約 2.2 度/日），1″ 之內的根離盤上時刻不超過 7e-5 日；窗取 1e-3 日（約 86 秒）
# 留十倍以上餘裕，而同一個相位不可能在 86 秒內再完成一次。
_EXACT_NOW_ROOT_HALF_WINDOW_DAYS = 1e-3
# 此刻精確的根以更細的容差收斂（約 0.9 毫秒）：窗只有 2e-3 日，多幾次二分即可，
# 報出的完成時刻才不會比 1″ 對應的秒數還粗。
_EXACT_NOW_ROOT_TOLERANCE_DAYS = 1e-8
# 兩個都以 _TOLERANCE_DAYS 收斂的根，時間差不超過此值便無法排出先後。
_SIMULTANEITY_TOLERANCE_DAYS = _TOLERANCE_DAYS
PRESENT_INSTANT_CRITERION = "abs_offset_from_exact_at_chart_moment_le_epsilon"
# The two policies are the same for every chart; they are stated once, in the
# method source register entry `void_of_course` the receipt's source_ref names.
PRESENT_INSTANT_POLICY = {
    "counts_toward_void_verdict": True,
    "coverage": "two_sided",
    "criterion": PRESENT_INSTANT_CRITERION,
    "exact_residual_epsilon_degrees": EXACT_NOW_EPSILON_DEGREES,
    "shared_with": (
        "derived_methods.aspects.degree_based.application_policy."
        "exact_residual_epsilon_degrees"
    ),
    "root_search_half_window_days": _EXACT_NOW_ROOT_HALF_WINDOW_DAYS,
    "root_tolerance_days": _EXACT_NOW_ROOT_TOLERANCE_DAYS,
    "note": (
        "盤上時刻月亮距精確相位 1 角秒以內（剛要完成或剛完成都算）的相位，與相位表的"
        "「此刻精確」同一標準；它此刻正在完成，故計入空亡判定（月亮不空亡）。"
        "它與未來相位分列兩個欄位以便分辨；all_candidates 只列未來相位，第一個最快完成。"
    ),
}
BOUNDARY_SIMULTANEITY_POLICY = {
    "tolerance_days": _SIMULTANEITY_TOLERANCE_DAYS,
    "result_when_only_simultaneous": "simultaneous_boundary",
    "note": (
        "simultaneous_boundary：某個相位精確完成的時刻與月亮離開本星座的時刻，"
        f"相差不超過求根容差 {_SIMULTANEITY_TOLERANCE_DAYS:g} 日（約 0.086 秒），"
        "數值上分不出先後。此情形既不判為"
        "空亡、也不判為非空亡：is_void_of_course 為 null，verdict 為 "
        "simultaneous_boundary；該相位與兩個根的括號區間一併列出，供複算。"
    ),
}

# Closed sets: a perfection that
# cannot be ordered against the sign exit returns `simultaneous_boundary`.
# The page words each verdict itself (ChartViewModel VOC_VERDICT_ZH).
VOC_VERDICTS = ("void", "not_void", "simultaneous_boundary", "not_evaluated")


def voc_receipt_head() -> dict:
    """The keys every VOC receipt opens with."""

    return {"method": VOC_METHOD_NAME, **method_receipt("void_of_course")}


_SEARCH_HEAD_KEYS = (
    "method", "method_status", "method_provenance", "source_verification",
    "solver", "solver_status",
)


def _search_head(solver_status: str) -> dict:
    """The keys the search result and the verdict built from it open with."""

    return {
        **voc_receipt_head(),
        "method_provenance": VOC_METHOD_PROVENANCE,
        "source_verification": dict(VOC_SOURCE_STATUS),
        "solver": SOLVER_NAME,
        "solver_status": solver_status,
    }


def _memoized_longitudes(longitude_at):
    """One Swiss call per (body, instant) within one VOC search.

    Every aspect target of one body is sampled on the same coarse grid, and the
    Moon is sampled on that grid again for every body, so without this the same
    position is recomputed up to 48 times per grid point.  Under the fixed flags
    of one sampler a longitude is a pure function of (body_id, jd_ut), so the
    cache cannot change a result; it lives only as long as the search.
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


def _find_sign_exit_days(moon_id, jd_ut, longitude_at, current_longitude):
    """求月亮實際跨過下一個星座界線的時刻（自盤上時刻起算的日數）。

    以「距離下一個星座起點還差幾度」為求根函式，在整個搜尋視窗上實際查星曆，
    因此不受月亮速度變化影響。月亮在視窗內不可能逆行（其黃經速度恆為正），
    故第一個根即為換座時刻。
    """

    boundary = math.floor(current_longitude / 30.0) * 30.0 + 30.0

    def distance_to_boundary(offset_days: float) -> float:
        return wrap_to_signed_180(longitude_at(moon_id, jd_ut + offset_days) - boundary)

    crossings = find_crossings_detailed(
        distance_to_boundary,
        window_days=_SIGN_EXIT_SEARCH_WINDOW_DAYS,
        coarse_step_days=_COARSE_STEP_DAYS,
        tolerance_days=_TOLERANCE_DAYS,
        max_roots=1,
    )
    return (crossings[0] if crossings else None), boundary


def _find_aspect_perfections(
    moon_id,
    body,
    jd_ut,
    longitude_at,
    window_days,
) -> tuple[list[dict], list[dict]]:
    """回傳月亮與某天體的精確成相：(此刻精確, 未來成相)。

    此刻精確：盤上時刻距精確 ≤ 1″（EXACT_NOW_EPSILON_DEGREES）；它的根在盤上時刻前後
    _EXACT_NOW_ROOT_HALF_WINDOW_DAYS 內求出，可能略早或略晚於盤上時刻。
    未來成相：(0, window_days] 內其餘的根。同一個根不會同時出現在兩類：此刻精確的
    target，後段略去離盤上時刻不到半窗的根。
    """

    present_events: list[dict] = []
    future_events: list[dict] = []
    body_id = body["body_id"]
    half_window = _EXACT_NOW_ROOT_HALF_WINDOW_DAYS

    for aspect_angle in PTOLEMAIC_ASPECTS:
        # 合(0°)與沖(180°)的 +angle 與 −angle 在 (-180,180] 上重合，用集合自動去重。
        targets = {
            wrap_to_signed_180(aspect_angle),
            wrap_to_signed_180(-aspect_angle),
        }
        for target in targets:
            def separation_at(offset_days: float, _target=target) -> float:
                moment = jd_ut + offset_days
                return wrap_to_signed_180(
                    longitude_at(moon_id, moment)
                    - longitude_at(body_id, moment)
                    - _target
                )

            offset_now = separation_at(0.0)
            exact_now = abs(offset_now) <= EXACT_NOW_EPSILON_DEGREES
            present = (
                find_crossings_detailed(
                    separation_at,
                    start_days=-half_window,
                    window_days=2.0 * half_window,
                    coarse_step_days=half_window / 8.0,
                    tolerance_days=_EXACT_NOW_ROOT_TOLERANCE_DAYS,
                    max_roots=1,
                )
                if exact_now
                else []
            )
            future = [
                record
                for record in find_crossings_detailed(
                    separation_at,
                    window_days=window_days,
                    coarse_step_days=_COARSE_STEP_DAYS,
                    tolerance_days=_TOLERANCE_DAYS,
                )
                if record["t"] > (half_window if present else 0.0)
            ]
            for records, events, is_exact_now in (
                (present, present_events, True),
                (future, future_events, False),
            ):
                events.extend(
                    {
                        "body": body["name"],
                        "body_key": body["key"],
                        "aspect_angle": aspect_angle,
                        "time_days": record["t"],
                        # 輸出括號端點與迭代次數供第三方複算。
                        "solver_evidence": {
                            "bracket": record["bracket"],
                            "bisection_iterations": record["iterations"],
                            "residual_degrees": record["residual_degrees"],
                        },
                        **(
                            {"offset_at_chart_moment_degrees": offset_now}
                            if is_exact_now
                            else {}
                        ),
                    }
                    for record in records
                )
    return present_events, future_events


def find_voc_candidates(
    moon: dict,
    other_bodies: list,
    trace: Trace,
    *,
    jd_ut: float,
    longitude_at,
    moon_id: int,
) -> dict:
    """回傳距離換座邊界的時間，以及邊界前會精確成立的所有候選入相位事件（依時間排序）。"""

    moon_lon = moon["longitude"]
    moon_speed = moon["speed_longitude"]
    longitude_at = _memoized_longitudes(longitude_at)

    sign_exit, boundary = _find_sign_exit_days(
        moon_id, jd_ut, longitude_at, moon_lon
    )
    time_to_boundary_days = sign_exit["t"] if sign_exit else None

    if time_to_boundary_days is None:
        # 找不到根代表星曆或輸入異常；不得從瞬時速度推定換座期限，
        # 也不得靜默當成「邊界在無限遠」而讓所有相位都算數。
        trace.add(
            "VOC候選搜尋：距離下一個星座邊界的時間",
            inputs={"月亮黃經": moon_lon, "下一星座起點": boundary},
            note=(
                f"⚠ 求根器在 {_SIGN_EXIT_SEARCH_WINDOW_DAYS:g} 日視窗內找不到"
                "換座時刻，VOC 判定無法進行。"
            ),
        )
        return {
            **_search_head("sign_exit_not_found_in_search_window"),
            "time_to_sign_exit_hours": None,
            "candidates": [],
            "exact_at_chart_moment": [],
            "simultaneous_boundary_events": [],
        }

    trace.add(
        "VOC候選搜尋：距離下一個星座邊界的時間",
        formula="以 root_finding 求 月亮黃經(t) − 下一星座起點 = 0 的最早時刻",
        inputs={
            "月亮黃經": moon_lon,
            "月亮瞬時速度(度/日)": moon_speed,
            "下一星座起點": boundary,
            "求根器": SOLVER_NAME,
            "搜尋視窗(天)": _SIGN_EXIT_SEARCH_WINDOW_DAYS,
        },
        result={
            "距邊界時間(天)": time_to_boundary_days,
            "括號區間(天)": [
                sign_exit["bracket"]["low_days"],
                sign_exit["bracket"]["high_days"],
            ],
            "括號端點殘差(度)": [
                sign_exit["bracket"]["low_offset_degrees"],
                sign_exit["bracket"]["high_offset_degrees"],
            ],
            "二分迭代次數": sign_exit["iterations"],
            "收斂殘差(度)": sign_exit["residual_degrees"],
        },
        note=(
            "改以整段實際星曆取樣與求根取代瞬時速度外插；搜尋視窗、"
            "括號端點與迭代次數一併輸出，第三方可據以複算。"
        ),
    )

    exact_now: list[dict] = []
    future: list[dict] = []
    for body in other_bodies:
        if body["longitude"] is None or body["speed_longitude"] is None:
            continue
        present_events, future_events = _find_aspect_perfections(
            moon_id,
            body,
            jd_ut,
            longitude_at,
            # The window runs past the exit by the simultaneity tolerance so
            # a perfection that cannot be ordered against the exit is found
            # and named, rather than falling either side by rounding.
            time_to_boundary_days + _SIMULTANEITY_TOLERANCE_DAYS,
        )
        exact_now.extend(present_events)
        future.extend(future_events)

    # **恰在盤上時刻精確成立的相位
    # 計入空亡判定。** 理由是它此刻正在完成——有事情正在發生，月亮不是空亡。
    #
    # 需要區分的不是「t=0 是否計入」，而是它不得**默默**被當成一個未來事件
    # 回報：求根器會讓 t=0 混進 candidates。
    #
    # 因此實作是「計入，但可分辨」：t=0 的事件另列在
    # exact_at_chart_moment，不混進代表未來的 candidates；空亡判定則同時看兩者。
    # all_candidates 只列**未來**相位，依時間排序，可能為空。
    #
    # 與換座時刻在求根容差內分不出先後的
    # 完成點，既不是「邊界前」也不是「邊界後」，另列 simultaneous_boundary_events，
    # 並帶上換座根的括號區間，讓第三方能看出兩個根為何無法排序。
    #
    # 「此刻」以角度判定（距精確 ≤ 1″，與相位模組同一常數）。
    exit_low = time_to_boundary_days - _SIMULTANEITY_TOLERANCE_DAYS
    candidates = [event for event in future if event["time_days"] < exit_low]
    simultaneous = [
        {**event, "sign_exit_bracket": sign_exit["bracket"]}
        for event in future
        if event["time_days"] >= exit_low
    ]
    candidates.sort(key=lambda c: c["time_days"])
    exact_now.sort(key=lambda c: c["time_days"])
    simultaneous.sort(key=lambda c: c["time_days"])

    trace.add(
        f"VOC候選搜尋 (method={VOC_METHOD_NAME}, solver={SOLVER_NAME})",
        formula="對合相與四種傳統相位角(0/60/90/120/180°)的兩個帶號目標，"
                "以粗掃描分割根區間後二分求根；盤上時刻距精確 ≤ 1″ 者列為此刻完成，"
                "換座時刻前（超出求根容差）者列為候選，與換座時刻在求根容差內"
                "分不出先後者另列 simultaneous_boundary",
        result={
            "候選事件數": len(candidates),
            "候選清單": candidates,
            "此刻完成數": len(exact_now),
            "與換座同時數": len(simultaneous),
        },
        note="求根器在每個取樣點實際查詢星曆，不假設速度為定值，"
             "月亮速度變化與被相位行星站留都照實計入；"
             "以有限間隔搜尋；間距極近的根或切點可能遺漏。"
             "此搜尋仍內含「用哪些天體/哪些相位角」的技法假設，屬方法假設而非純天文事實。"
             "定義為星座界線＋精確完成：星座條件最晚見於 Lilly 1647 p.112；"
             "要求換座前精確完成：後人文獻歸於 Al H. Morrison（AFA Journal 1966 年 10 月有專文，原文未讀）；"
             "更早的起源尚未查證。兩者合起來的歷史歸屬未定；與 Porphyry《Introduction》ch.23 的 30° 定義、"
             "以及 Lilly 1647 以容許度判入相位的做法都不同。",
    )

    return {
        **_search_head("converged"),
        "time_to_sign_exit_hours": time_to_boundary_days * 24.0,
        "sign_exit_solver_evidence": {
            "boundary_longitude": boundary,
            "bracket": sign_exit["bracket"],
            "bisection_iterations": sign_exit["iterations"],
            "residual_degrees": sign_exit["residual_degrees"],
            "search_window_days": _SIGN_EXIT_SEARCH_WINDOW_DAYS,
        },
        "candidates": candidates,
        "exact_at_chart_moment": exact_now,
        "simultaneous_boundary_events": simultaneous,
    }


def determine_void_of_course(voc_data: dict, trace: Trace) -> dict:
    """方法層最終判定，結果屬閉集 VOC_VERDICTS。

    - not_void：換座前（超出求根容差）有相位完成，或盤上時刻恰好精確成立
      （後者也計入）。
    - simultaneous_boundary：沒有上述相位，但有相位與換座時刻在求根容差內分不出
      先後；is_void_of_course 為 null。
    - void：以上皆無。
    - not_evaluated：換座時刻求根失敗。
    """

    candidates = voc_data["candidates"]
    exact_now = voc_data.get("exact_at_chart_moment", [])
    simultaneous = voc_data.get("simultaneous_boundary_events", [])
    solver_failed = voc_data.get("solver_status") != "converged"
    if solver_failed:
        verdict = "not_evaluated"
    elif candidates or exact_now:
        verdict = "not_void"
    elif simultaneous:
        verdict = "simultaneous_boundary"
    else:
        verdict = "void"
    is_void = {"void": True, "not_void": False}.get(verdict)
    soonest = candidates[0] if candidates else None

    trace.add(
        "月空亡(VOC)最終判定",
        formula="若邊界前無任何相位完成（含盤上時刻恰好精確者）-> 空亡；"
                "否則以最快完成者為離開星座前的入相位",
        result=(
            {"結果": "⚠ 求根器未收斂，無法判定"}
            if solver_failed
            else {
                "結果": "⚠ 相位完成與換座時刻在求根容差內同時，回報 "
                        "simultaneous_boundary，不判定空亡與否",
                "同時完成": [
                    f"{item['body']} {item['aspect_angle']}°"
                    for item in simultaneous
                ],
            }
            if verdict == "simultaneous_boundary"
            else {
                **(
                    {
                        "盤上時刻恰好精確成立": [
                            f"{item['body']} {item['aspect_angle']}°"
                            for item in exact_now
                        ]
                    }
                    if exact_now else {}
                ),
                **(
                    {"最快入相位": f"{soonest['body']} {soonest['aspect_angle']}°，約 {soonest['time_days']*24:.2f} 小時後"}
                    if soonest else {}
                ),
            }
            or {"結果": "離開星座前無任何相位完成 -> 月空亡"}
        ),
        note=(
            "盤上時刻恰好精確成立的相位也計入判定。"
            if exact_now else ""
        ),
    )

    return {
        # This dict is rebuilt rather than spread, so anything added upstream has
        # to be carried across explicitly or it never reaches the response.
        **{key: voc_data[key] for key in _SEARCH_HEAD_KEYS},
        # not_evaluated is a search that ran and found no sign exit.
        **computed_receipt(
            PRODUCT_FORMULA_SOURCE,
            available=verdict != "not_evaluated",
            reason_code=(
                voc_data.get("solver_status") if verdict == "not_evaluated" else None
            ),
        ),
        "verdict": verdict,
        "is_void_of_course": is_void,
        "simultaneous_boundary_events": simultaneous,
        "time_to_sign_exit_hours": voc_data["time_to_sign_exit_hours"],
        # all_candidates[0] is the soonest future perfection.
        "all_candidates": candidates,
        "exact_at_chart_moment": voc_data.get("exact_at_chart_moment", []),
    }


_VOC_OTHER_BODY_KEYS = frozenset(
    body["key"] for body in CLASSICAL_BODIES if body["key"] != "moon"
)


def evaluate_void_of_course(
    bodies: list[dict], trace: Trace, *, jd_ut: float, longitude_at
) -> dict:
    """The VOC verdict from one set of computed bodies.

    The chart and every birth-time sensitivity probe call this, so both read
    the same participants (the classical bodies other than the Moon, with
    their Swiss ids) and the same search.
    """

    moon = next(body for body in bodies if body["key"] == "moon")
    others = [
        {**body, "body_id": BODY_ID_BY_KEY[body["key"]]}
        for body in bodies
        if body["key"] in _VOC_OTHER_BODY_KEYS
    ]
    return determine_void_of_course(
        find_voc_candidates(
            moon,
            others,
            trace,
            jd_ut=jd_ut,
            longitude_at=longitude_at,
            moon_id=BODY_ID_BY_KEY["moon"],
        ),
        trace,
    )


def void_of_course_not_applicable(state: dict, trace: Trace) -> dict:
    """VOC refused by the central frame table.

    The sign exit is a boundary of the tropical ecliptic of date, and the method
    needs an Earth observer.  Outside that frame nothing is searched or converted.
    """

    trace.add(
        "月空亡(VOC)",
        result={"verdict": "not_evaluated", "reason_code": state["reason_code"]},
        note=(
            "月亮換座所依的星座界線屬當日回歸框架，且方法需要地表觀測者；"
            "參考框架相容表判定本次不適用，不搜尋、回傳 null。"
        ),
    )
    return {
        **voc_receipt_head(),
        **not_applicable_receipt(state),
        "verdict": "not_evaluated",
        "is_void_of_course": None,
        "time_to_sign_exit_hours": None,
        "all_candidates": [],
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "void_of_course": {
        "applies_to": "derived_methods.void_of_course",
        "method": VOC_METHOD_NAME,
        "method_provenance": VOC_METHOD_PROVENANCE,
        "source_verification": dict(VOC_SOURCE_VERIFICATION),
        "present_instant_policy": dict(PRESENT_INSTANT_POLICY),
        "boundary_simultaneity_policy": dict(BOUNDARY_SIMULTANEITY_POLICY),
    },
}
