"""黃道相位：整宮配置層（doctrine）與逐度層（doctrine + 容許度）分開輸出。

兩層需要的方法承諾強度不同，所以分開：

**第一層——整宮配置 (whole-sign configuration)。**
只看兩個星體各自落在第幾個星座，兩者相隔幾個星座。相隔 0/2/3/4/6 個星座分別
稱為 合/六分/刑/拱/沖，相隔 1/5 個星座（反方向即 11/7）則互不見（aversion, ἀσύνδετος）。
0/2/3/4/6 是 Ptolemy, Tetrabiblos I.13 的間隔計數；Firmicus 與 Antiochus 用含兩端計數
（拱是「第五個」星座）：關係相同、數字不同。來源見方法登記 `aspects/whole_sign`。
「相隔幾個星座」是算術；「相隔三個星座叫刑」是希臘化占星的成文教義。這一層
**不需要任何容許度決定**，因此預設即計算。

**第二層——逐度相位 (degree-based aspect)。**
兩個星體的實際角距離距離精確相位差幾度，以及該差距是否落在容許度內。
「差幾度」是算術；**「容許度是幾度」則是方法選擇**，而且歷史上的數字彼此不一致。
因此 `compute_aspects` 本身不代選表：未傳入具名 `orb_profile` 或使用者固定配對門檻時，
`in_orb` 一律回傳 null 並附 reason_code，角距離等純幾何量照常輸出。產品預設由 API 層
給定為 `DEFAULT_ORB_PROFILE_KEY`（Lilly 1647），收據以 `profile_selection` 標明它是產品
預設而非使用者所選。

逐度層可改選現代小相位具名集合、縮放具名七政 orb 表、或使用明示固定配對門檻；ASC／MC
可 opt-in，但不互配、不加入整宮 doctrine、不推測 applying。現代小相位與使用者覆寫均不
繼承古典來源宣稱。本模組預設計算、可 opt-out；方法收據仍為 provisional，Dossier 也會
發出 `provisional_method_result` 通知——預設開啟不等於方法已獲採用。

容許度表（皆為 moiety 制：兩星各有自己的 orb，門檻為兩星 orb 的半和）、partile 慣例與
小相位的來源、查核狀態與證據標準在 `aspect_profiles` 的資料與方法登記
（`aspects/orb/*`、`aspects/partile*`、`aspects/minor_aspects`）。只有二手彙編為依據的
數值表可以出貨，但必須在 `source_verification` 明示未轉錄一手文本。

不提供現代固定容許度：常見的「合 8 度、拱 8 度、刑 7 度、六分 6 度」沒有可具名引用的
權威來源，憑空給一組數字並標為「現代」會是可被證偽的權威宣稱。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .invariants import InternalInvariantError
from ..ephemeris import FullEphemerisRequiredError
from .bodies import DEFINITIONAL_EXCLUDED_PAIRS, memoized_longitudes
from .module_state import (
    PRODUCT_FORMULA_SOURCE,
    SEARCH_EPHEMERIS_REFUSALS,
    computed_receipt,
    module_state,
    frame_table_refusal,
)
from .method_status import method_head
from .dignity_tables import SIGNS
from .formatting import degrees_number, normalize_longitude, zodiac_sign_index
from .root_finding import SOLVER_NAME, find_crossings_detailed, wrap_to_signed_180
from .source_reading import BIBLIOGRAPHIC_ONLY, ORIGINAL_LANGUAGE_READ, TRANSLATION_READ, cited, reference_only
from .trace import Trace
from .aspect_profiles import (
    ASPECT_SET_PROFILES,
    LILLY_1647_READ_AT,
    MINOR_ASPECT_ORIGIN_NOTE,
    MODERN_MINOR_ASPECTS,
    ORB_BOUNDARY_OPERATOR,
    ORB_BOUNDARY_RECEIPT,
    ORB_PROFILES,
    PARTILE_PROFILES,
    PARTILE_TABULATED_FROM,
    PARTILE_VALID_ASPECT_BASIS,
    PARTILE_VALID_ASPECT_RULE,
    PTOLEMAIC_ASPECTS,
    SOURCE_VERIFICATION_STATUS_KEYS,
    _ASPECT_BY_KEY,
    _ORB_PROFILE_REGISTER_ONLY_KEYS,
    _PARTILE_SOURCE_VERIFICATION,
    _SIGN_DISTANCE_TO_ASPECT,
)


WHOLE_SIGN_METHOD_NAME = "whole_sign_configuration_v1"
DEGREE_ASPECT_METHOD_NAME = "ptolemaic_degree_aspect_moiety_v1"
EXTENDED_DEGREE_ASPECT_METHOD_NAME = "named_degree_aspect_set_with_explicit_orb_policy_v1"
APPLYING_METHOD_NAME = "relative_longitude_speed_sign_v1"

# 入相位／出相位的四態閉集。ownership 是 pair × aspect-target：
# 兩星相距 74° 且角距增加時，對六分是出相位、對刑是入相位，兩句同時為真，
# 因此每個 target 各自持有一個狀態；頂層的 `applying` 只是最近相位那一格的顯示便利。
# 精確成相（f(t0)=0）與站留（ḟ(t0)≈0）不折入 null，各有具名狀態。
APPLYING_STATES = ("applying", "exact_now", "separating", "indeterminate_relative_station")
# 三個數值政策各自具名（皆為產品數值政策，不是古典教義）：
#   exact_residual_epsilon：|距精確相位| 在此之內即 exact_now（1 角秒；Lilly 1647 p.110 保留約 6′
#     的 post-exact margin，那是 Lilly 1647 的具名慣例，不泛化為本產品的 epsilon）。
#   relative_speed_epsilon：|相對黃經速度| 在此之內時一階速度無法分類 → indeterminate_relative_station。
#   solver_time_tolerance：成相時刻求根的時間收斂容差，見 PERFECTION_TOLERANCE_DAYS。
EXACT_NOW_EPSILON_DEGREES = 1.0 / 3600.0
RELATIVE_SPEED_EPSILON_DEG_PER_DAY = 1e-6
# 成相時刻搜尋的逐 target 閉集狀態。「未搜尋」的每一種理由與
# 「搜尋過但無交會」是不同值；`found` 才代表有根。
PERFECTION_STATUSES = (
    "not_requested",
    "not_applying",
    "no_motion_model",
    "no_orb_verdict_nearest_only",
    "outside_effective_orb",
    "source_unavailable",
    "searched_no_root",
    "found",
)
# 真的跑過求根器的狀態；其餘狀態都是「沒有搜尋」的具名理由。
SEARCHED_PERFECTION_STATUSES = frozenset({"found", "searched_no_root", "source_unavailable"})
# 每個 pair 列出哪些 target（回應大小預算：全選項約 119 pair × 11 target）。
# 夾住角距的兩個精確角必列（最近相位一定是其一）；任何 in_orb 為真或真的搜尋過成相時刻的
# target 必列。未列出者的 in_orb 必為 false 或 null、成相時刻必未搜尋；它們的
# perfection_status 仍計入 perfection.coverage，所以「未搜尋」的計數不因省略而消失。
ASPECT_TARGET_LISTING = {
    "listed": ["bracketing_exact_angles", "in_orb_true", "perfection_searched"],
    "nearest_aspect_entry": "always_listed_find_by_nearest_aspect_key",
    "unlisted_semantics": "in_orb_false_or_null_and_perfection_not_searched",
    "unlisted_counted_in": "derived_methods.aspects.perfection.coverage",
}

# `pairs` 只列「有意義」的組合——
# 逐度層任一 target 在容許度內，或整宮層成相位；含軸點（ASC／MC）的組合沒有整宮 doctrine，
# 一律列出。其餘組合照樣逐一計算（perfection.coverage 仍計入它們每一格的狀態），只以數量
# 回報於 `pair_listing`，不列出角距與最近相位。沒有選容許度表時逐度層沒有容許度判定，只剩
# 整宮層與 partile。
# 任一 target 的 partile 為真也列出：1° 與 1677 三度判準只比度數、不要求
# 整宮成相，跨星座的 partile 可以既不在容許度內（沒選表或固定容許度較小）也不整宮成相；
# 不列出它會把一個有相位判定的組合算進 unlisted_pairs_without_aspect。
PAIR_LISTING_RULE = "in_orb_or_partile_on_degree_layer_or_whole_sign_aspect_angle_pairs_always_v1"


def pair_is_listed(pair: dict) -> bool:
    """唯一判定：這一組是否列在 `pairs`。"""

    whole_sign = pair["whole_sign"]
    if whole_sign.get("applicable") is False:
        return True  # 含軸點：整宮不適用，一律列出
    if whole_sign.get("in_aspect") is True:
        return True
    return any(
        target["in_orb"] is True or target.get("partile") is True
        for target in pair["aspect_targets"]
    )


def whole_sign_aversions(evaluated: list[dict]) -> list[dict]:
    """Every evaluated pair whose signs form no whole-sign configuration.

    A separate list beside `pairs`: the listing rule above leaves a pair in
    aversion out of `pairs` when no degree aspect lists it, which made aversion
    visible only as a count.  Pairs with an angle take no part (the whole-sign
    layer does not apply to them).
    """

    return [
        {
            "body_a": pair["body_a"],
            "body_a_name": pair["body_a_name"],
            "body_b": pair["body_b"],
            "body_b_name": pair["body_b_name"],
            "signed_sign_distance": pair["whole_sign"]["signed_sign_distance"],
            "configuration_key": pair["whole_sign"]["configuration_key"],
            "configuration_zh": pair["whole_sign"]["configuration_zh"],
        }
        for pair in evaluated
        if pair["whole_sign"].get("configuration_key") == "aversion"
    ]


def _pair_listing(evaluated: int, listed: int, rule: str = PAIR_LISTING_RULE) -> dict:
    return {
        "rule": rule,
        "evaluated_pairs": evaluated,
        "listed_pairs": listed,
        "unlisted_pairs_without_aspect": evaluated - listed,
    }


# Partile 的預設慣例。與 orb 表不同，這一項有預設值：三種慣例中「同一整數度」
# 是 Houlding 記為最通行者，故沿用為預設而非留空。
# 使用者可經 `partile_profile` 改選。
DEFAULT_PARTILE_PROFILE_KEY = "same_degree_number_v1"

# 產品預設容許度表（介面提示可切換）：Lilly 1647 moiety 表，方法研究筆記認為 (orb_A + orb_B) / 2
# 是 Lilly p.107 的直接實作。schemas.OptionsInput 的預設值必須等於此鍵（測試看守）。
DEFAULT_ORB_PROFILE_KEY = "lilly_1647_experience_v1"


def orb_profile_selection(options) -> str:
    """Return how the effective orb profile was chosen: product_default,
    user_selected, user_declined or product_default_yielded_to_user_fixed_orb.

    One generator for the aspect receipt and the dossier option state.  A fixed
    pair orb with no profile in force is "yielded" whether the profile was left
    out or sent as null, since the fixed orb is the orb source either way;
    deciding from values, not ``model_fields_set``, lets the
    ``requested_options`` echo reproduce the state.
    """

    if options.aspect_orb_profile is not None:
        explicit = "aspect_orb_profile" in options.model_fields_set
        return "user_selected" if explicit else "product_default"
    if options.aspect_fixed_orb_degrees is not None:
        return "product_default_yielded_to_user_fixed_orb"
    return "user_declined"


def _verification_status(record: dict, ref: str) -> dict:
    return {
        **{key: record[key] for key in SOURCE_VERIFICATION_STATUS_KEYS if key in record},
        "source_ref": ref,
    }


# 逐度層只對「來源明確給了 orb 的星體」下容許度判斷。三王星、南北交點與阿拉伯點
# 在上列任何一個來源中都沒有 orb 數值——三王星在來源成書時尚未發現，交點與阿拉伯點
# 不是有「光芒」的星體。替它們編一個 orb 會是憑空創設，因此這些參與者的
# `in_orb` 在歷史 profile 下為 null，但角距離、入相位／出相位、成相時刻照常輸出。
# 使用者明示固定配對門檻時可以另行得到 verdict；其 source 固定是 user_override，
# 不可被描述成下列古籍替這些參與者提供了 orb。
ORB_ELIGIBLE_CATEGORIES = frozenset({"classical_planet"})

SIGN_ZH = (
    "牡羊", "金牛", "雙子", "巨蟹", "獅子", "處女",
    "天秤", "天蠍", "射手", "摩羯", "水瓶", "雙魚",
)

# 成相時刻搜尋的預設視窗與粗掃描步長。步長 0.125 日（3 小時）之下，黃經相對速度
# 最快的組合（月亮對逆行水星，約 16.8 度/日）單步最多移動約 2.1 度，遠小於
# root_finding 用來區分「真過零」與「環繞不連續」所需的 180 度界線。
DEFAULT_PERFECTION_WINDOW_DAYS = 40.0
PERFECTION_COARSE_STEP_DAYS = 0.125
# 收斂容差 1e-6 日約合 0.086 秒，遠細於出生時刻本身的不確定度。
PERFECTION_TOLERANCE_DAYS = 1e-6


def sign_index(longitude: float) -> int:
    return zodiac_sign_index(longitude)


def _sign_record(longitude: float) -> dict:
    index = sign_index(longitude)
    return {
        "sign_index": index,
        "sign_key": SIGNS[index],
        "sign_zh": SIGN_ZH[index],
        "degree_in_sign": normalize_longitude(longitude) - index * 30.0,
    }


def _whole_sign_configuration(lon_a: float, lon_b: float) -> dict:
    """相隔幾個星座，以及該距離對應的希臘化配置名稱。

    星座距離取兩個方向的較小者（0–6），因為配置本身無方向性：
    相隔 3 個星座與相隔 9 個星座是同一個刑。
    """

    index_a = sign_index(lon_a)
    index_b = sign_index(lon_b)
    forward = (index_b - index_a) % 12
    distance = min(forward, 12 - forward)
    aspect = _SIGN_DISTANCE_TO_ASPECT.get(distance)
    # 星座距離（0–6）＝ min(signed_sign_distance, 12 − signed_sign_distance)，不另存一份。
    return {
        "signed_sign_distance": forward,
        "configuration_key": aspect["key"] if aspect else "aversion",
        "configuration_zh": aspect["zh"] if aspect else "不合意",
        "in_aspect": aspect is not None,
    }


def _nearest_aspect(
    separation_degrees: float,
    aspect_definitions: tuple[dict, ...] = PTOLEMAIC_ASPECTS,
) -> tuple[dict, float, bool]:
    """回傳距離最近的相位、帶號的「還差幾度」，以及是否為並列。

    五個相位角把 0–180 度切成寬度 60/30/30/60 的四段，**並非等距**，因此
    「最近的相位唯一」這句話在合相＋四種傳統相位的集合下有**四個**例外
    （每段的中點）：

        (0, 60)    → 30°   距合與距六分各 30°
        (60, 90)   → 75°   距六分與距刑各 15°
        (90, 120)  → 105°  距刑與距拱各 15°
        (120, 180) → 150°  距拱與距沖各 30°

    75°／105° 距精確相位只有 15°，而 Lilly p.107 主欄的最大 joint moiety
    （Sun+Moon = 8°30′+6°15′ = 14°45′）只差 15′，所以「取哪一個並列點都不改變
    in_orb」不是註解可以宣稱的事，而是一條由測試看守的不變式（所有具名 profile 的
    最大 joint moiety < 15°）。`in_orb` 由每個 target 各自判定，最近相位只決定顯示
    哪個名稱，不擁有 in_orb／applying／partile 的語義。

    並列時回傳 `tie` 旗標，讓輸出說出「這裡有並列，我取了角度較小的那個」，而不是
    由 `PTOLEMAIC_ASPECTS` 的排列順序默默決定。
    """

    best: dict | None = None
    best_offset: float | None = None
    tie = False
    for aspect in aspect_definitions:
        offset = separation_degrees - aspect["angle"]
        if best_offset is None or abs(offset) < abs(best_offset):
            best, best_offset, tie = aspect, offset, False
        elif abs(offset) == abs(best_offset):
            tie = True
    if best is None or best_offset is None:
        # Only an empty set (no caller passes one) gets here; fail clearly rather
        # than with a TypeError one frame later.
        raise ValueError("aspect_definitions must not be empty")
    return best, best_offset, tie


def _signed_target(delta: float, angle: float) -> float:
    """挑出 ±angle 中與目前帶號角差 `delta` 較接近者。

    合 (0°) 與沖 (180°) 兩者的 +angle 與 −angle 在 (-180, 180] 上是同一個值，
    自動退化，不需特別處理。
    """

    candidates = {wrap_to_signed_180(angle), wrap_to_signed_180(-angle)}
    return min(candidates, key=lambda target: abs(wrap_to_signed_180(delta - target)))


def _same_integer_degree(lon_a: float, lon_b: float) -> bool:
    return int((lon_a % 360.0) % 30.0) == int((lon_b % 360.0) % 30.0)


PARTILE_NOT_APPLICABLE_TO_MINOR = "partile_profile_not_applicable_to_modern_minor_aspect"


def _partile_for_target(
    *,
    lon_a: float,
    lon_b: float,
    target_offset: float,
    profile: dict,
    aspect: dict,
    in_orb: bool | None,
    whole_sign: dict,
    contains_angle: bool,
) -> tuple[bool | None, str | None]:
    """依所選 profile 判定該 target 的 partile。

    只有帶前置條件的判準（Lilly 1647 同一整數度）先要求有效相位；1° 與 1677 三度判準
    依各自的度數定義，只比 |距精確相位| 與門檻。

    回傳 (partile, reason_code)。理由碼閉集 PARTILE_REASON_CODES：
      partile_profile_not_applicable_to_modern_minor_aspect
      no_aspect_verdict_available_for_partile      （同度數判準、角點組合且無 orb verdict → null）
      same_degree_without_whole_sign_aspect         （同一整數度，但星座不成此相位 → False）
      no_whole_sign_aspect_for_partile              （星座不成此相位 → False）
      angle_pair_not_in_orb_for_partile             （角點組合不在軸點容許度內 → False）
    """

    if aspect["classification"] == "modern_minor":
        return None, PARTILE_NOT_APPLICABLE_TO_MINOR
    if profile["valid_aspect_precondition"] is None:
        return abs(target_offset) <= profile["threshold_degrees"], None
    if contains_angle:
        # 軸點不參加整宮教義；唯一可用的「有相位」判定是軸點容許度。
        if in_orb is None:
            return None, "no_aspect_verdict_available_for_partile"
        if not in_orb:
            return False, "angle_pair_not_in_orb_for_partile"
    elif not (
        whole_sign.get("in_aspect") is True
        and whole_sign.get("configuration_key") == aspect["key"]
    ):
        if _same_integer_degree(lon_a, lon_b):
            return False, "same_degree_without_whole_sign_aspect"
        return False, "no_whole_sign_aspect_for_partile"
    return _same_integer_degree(lon_a, lon_b), None


def _applying(signed_offset: float, relative_speed: float | None) -> str | None:
    """回傳 APPLYING_STATES 之一；相對速度未知時回 null（呼叫端附理由碼）。

    f = 帶號的距精確相位差，ḟ = 相對黃經速度。|f| ≤ exact epsilon → exact_now；
    |ḟ| ≤ speed epsilon → indeterminate_relative_station（一階速度無法分類，不硬判）；
    f·ḟ < 0 → applying；f·ḟ > 0 → separating。跨 0° 的差已由 wrap_to_signed_180
    處理，不會出現 359.9°→0.1° 的假跳變。
    """

    if relative_speed is None:
        return None
    if abs(signed_offset) <= EXACT_NOW_EPSILON_DEGREES:
        return "exact_now"
    if abs(relative_speed) <= RELATIVE_SPEED_EPSILON_DEG_PER_DAY:
        return "indeterminate_relative_station"
    return "applying" if signed_offset * relative_speed < 0.0 else "separating"


def _perfection_times(
    *,
    participant_a: dict,
    participant_b: dict,
    signed_target: float,
    jd_ut: float,
    longitude_at: Callable[[int, float], float],
    window_days: float,
) -> list[dict]:
    # Called only with a motion model (both body ids present).
    body_a = participant_a["body_id"]
    body_b = participant_b["body_id"]

    def separation_at(offset_days: float) -> float:
        moment = jd_ut + offset_days
        return wrap_to_signed_180(
            longitude_at(body_a, moment)
            - longitude_at(body_b, moment)
            - signed_target
        )

    return find_crossings_detailed(
        separation_at,
        window_days=window_days,
        coarse_step_days=PERFECTION_COARSE_STEP_DAYS,
        tolerance_days=PERFECTION_TOLERANCE_DAYS,
    )


def _orb_receipt(participants: list[dict], policy: OrbPolicy) -> dict:
    """Return the effective orb table independently of pair rendering.

    Pair records keep their local threshold for convenient inspection; this receipt is
    the request-level table needed to reproduce why a verdict was or was not available.
    """

    profile, scale, orb_scale_percent = policy.profile, policy.scale, policy.scale_percent
    fixed_orb_degrees, angle_orb_degrees = policy.fixed_orb_degrees, policy.angle_orb_degrees
    participant_orbs = []
    for participant in participants:
        eligible = participant["category"] in ORB_ELIGIBLE_CATEGORIES
        orb = (
            profile["orbs_degrees"].get(participant["key"]) * scale
            if profile is not None and eligible
            and profile["orbs_degrees"].get(participant["key"]) is not None
            else None
        )
        if participant["category"] == "angle" and angle_orb_degrees is not None:
            reason_code = "angle_pair_threshold_recorded_separately"
        elif fixed_orb_degrees is not None:
            reason_code = "fixed_pair_threshold_has_no_participant_orbs"
        elif profile is None:
            reason_code = "orb_profile_not_selected"
        elif not eligible or orb is None:
            reason_code = "no_sourced_orb_for_participant"
        else:
            reason_code = None
        participant_orbs.append(
            {
                "key": participant["key"],
                "category": participant["category"],
                "orb_eligible": eligible,
                "orb_degrees": orb,
                "reason_code": reason_code,
            }
        )

    # str | None: profile.get("provenance") may be absent.
    source: str | None
    if fixed_orb_degrees is not None:
        configuration_mode = "user_fixed_pair_threshold"
        source = "user_override"
        rule = "fixed_pair_threshold"
    elif profile is not None and orb_scale_percent is not None:
        configuration_mode = "named_profile_scaled"
        source = "user_scaled_named_profile"
        rule = profile["rule"]
    elif profile is not None:
        configuration_mode = "named_profile"
        source = profile.get("provenance")
        rule = profile["rule"]
    elif angle_orb_degrees is not None:
        configuration_mode = "angle_pair_override_only"
        source = "user_override"
        rule = "angle_pair_threshold"
    else:
        configuration_mode = "none"
        source = None
        rule = None

    in_force = (
        profile is not None
        or fixed_orb_degrees is not None
        or angle_orb_degrees is not None
    )
    return {
        **module_state(
            requested=in_force,
            executed=in_force,
            applicable=True,
            available=in_force,
            source=source,
            reason_code=None if in_force else "orb_profile_not_selected",
        ),
        "configuration_mode": configuration_mode,
        "profile_key": policy.profile_key,
        "profile_selection": policy.selection_state,
        "rule": rule,
        "scale_percent": orb_scale_percent,
        "fixed_pair_threshold_degrees": fixed_orb_degrees,
        "angle_pair_threshold_degrees": angle_orb_degrees,
        "participant_orbs": participant_orbs,
        "pair_threshold_formula": (
            "fixed_pair_threshold_degrees"
            if fixed_orb_degrees is not None
            else "(orb_a + orb_b) / 2"
            if profile is not None
            else None
        ),
        # 恰好等於門檻算在容許度內。
        **ORB_BOUNDARY_RECEIPT,
        **(
            {
                "source_verification": _verification_status(
                    profile["source_verification"], f"aspects/orb/{policy.profile_key}"
                )
            }
            if profile is not None
            else {}
        ),
    }


def aspects_not_applicable(state: dict, trace: Trace) -> dict:
    # Lots and angles do not join a refused aspects module either.
    refusal = frame_table_refusal(
        state, trace, f"相位 (method={WHOLE_SIGN_METHOD_NAME})",
        note=(
            "整宮配置、同度與容許度判定都讀當日回歸框架的黃經與星座界線；"
            "J2000 或不含章動的黃經不在這個框架，參考框架相容表判定不適用，不計算、不轉換座標。"
        ),
    )
    return {
        **method_head(WHOLE_SIGN_METHOD_NAME, "aspects"),
        **refusal,
        "participants": [],
        "excluded_participant_keys": [],
        "pairs": [],
        "pair_listing": _pair_listing(0, 0),
        "whole_sign_aversions": [],
    }


@dataclass(frozen=True)
class OrbPolicy:
    """The orb settings one aspect calculation runs under."""

    profile_key: str | None
    profile: dict | None
    scale_percent: float | None
    fixed_orb_degrees: float | None
    angle_orb_degrees: float | None
    selection_state: str | None = None

    @property
    def scale(self) -> float:
        return (self.scale_percent if self.scale_percent is not None else 100.0) / 100.0

    @property
    def scaled(self) -> bool:
        return self.scale_percent is not None


@dataclass(frozen=True)
class AngleUse:
    """Whether the angles were asked for, could join, and did join."""

    requested: bool
    applicable: bool
    used: bool


@dataclass(frozen=True)
class PerfectionSearch:
    """The perfection search settings shared by every pair."""

    include: bool
    jd_ut: float | None
    longitude_at: Callable[[int, float], float] | None
    window_days: float


def _degree_based_receipt(
    usable: list[dict],
    participants: list[dict],
    *,
    aspect_set_profile_key: str,
    partile_profile_key: str,
    degree_method_name: str,
    orb: OrbPolicy,
    angles: AngleUse,
) -> dict:
    """The degree-based layer's receipt: the set, partile, application and orb policies."""
    aspect_set_profile = ASPECT_SET_PROFILES[aspect_set_profile_key]
    partile_profile = PARTILE_PROFILES[partile_profile_key]
    orb_profile_key, profile = orb.profile_key, orb.profile
    fixed_orb_degrees, angle_orb_degrees = orb.fixed_orb_degrees, orb.angle_orb_degrees
    return {
        **method_head(degree_method_name, "aspects"),
        "aspect_set_profile": aspect_set_profile_key,
        "aspect_set_profile_detail": dict(aspect_set_profile),
        # 識別碼不動，只說明名稱各段指什麼。
        "method_name_note": (
            "ptolemaic_ = conjunction plus four traditional aspects (conventional "
            "name); moiety from Lilly 1647 p.107 or product normalization; "
            "Ptolemy I.24 gives neither degrees nor moieties"
        ),
        "aspect_set_profiles_available": sorted(ASPECT_SET_PROFILES),
        "aspect_keys": list(aspect_set_profile["aspect_keys"]),
        # 相位中文名與精確角的唯一一份：nearest_aspect 與 aspect_targets 只帶 key。
        "aspect_names_zh": {
            key: _ASPECT_BY_KEY[key]["zh"]
            for key in aspect_set_profile["aspect_keys"]
        },
        "aspect_angles_degrees": {
            key: _ASPECT_BY_KEY[key]["angle"]
            for key in aspect_set_profile["aspect_keys"]
        },
        # 常數契約文字只寫一次，不在 150 組相位裡各抄一份（回應大小，波 3）。
        "nearest_aspect_semantics": "display_convenience_only_verdicts_live_in_aspect_targets",
        "partile_profile": partile_profile_key,
        "partile_profile_detail": {
            key: value
            for key, value in partile_profile.items()
            if key != "sources"
        }
        | {"source_ref": f"aspects/partile/{partile_profile_key}"},
        "partile_source_verification": _verification_status(
            _PARTILE_SOURCE_VERIFICATION, "aspects/partile"
        ),
        "partile_profiles_available": sorted(PARTILE_PROFILES),
        # A reason that holds for every target of an aspect is stated once per
        # aspect key here; those targets carry partile and partile_reason_code
        # null.  Today that is the modern minor aspects, which no partile
        # profile governs.
        "partile_reason_codes_by_aspect": {
            key: PARTILE_NOT_APPLICABLE_TO_MINOR
            for key in aspect_set_profile["aspect_keys"]
            if _ASPECT_BY_KEY[key]["classification"] == "modern_minor"
        },
        "partile_note": (
            "三種慣例並存且會給出不同答案，其中兩種都載於 Lilly 名下的著作"
            "（1647 同度、1677 三度以內）。預設採最通行的同度慣例，可經 "
            "partile_profile 改選。"
        ),
        "application_method": APPLYING_METHOD_NAME,
        "application_policy": {
            "states": list(APPLYING_STATES),
            "ownership": "pair_by_aspect_target",
            "exact_residual_epsilon_degrees": EXACT_NOW_EPSILON_DEGREES,
            "relative_speed_epsilon_deg_per_day": RELATIVE_SPEED_EPSILON_DEG_PER_DAY,
            "solver_time_tolerance_days": PERFECTION_TOLERANCE_DAYS,
            "policy_kind": "numerical_product_policy_not_classical_doctrine",
            "source": (
                "modern formalisation (sign of f·ḟ) of applying/separating as in "
                "Lilly 1647 pp.107-110; his lighter-to-ponderous rule (p.108) not "
                "modelled; exact_now and station states are product numerical policy"
            ),
        },
        "minor_aspect_origin_note": MINOR_ASPECT_ORIGIN_NOTE,
        "minor_aspect_source_ref": "aspects/minor_aspects",
        "partile_valid_aspect_rule": PARTILE_VALID_ASPECT_RULE,
        "partile_valid_aspect_basis": PARTILE_VALID_ASPECT_BASIS,
        "aspect_target_listing": ASPECT_TARGET_LISTING,
        "orb_profile": orb_profile_key,
        "orb_profile_detail": (
            {
                key: value
                for key, value in profile.items()
                if key not in {"orbs_degrees", *_ORB_PROFILE_REGISTER_ONLY_KEYS}
            }
            | {
                "orbs_degrees": dict(profile["orbs_degrees"]),
                "source_verification": _verification_status(
                    profile["source_verification"], f"aspects/orb/{orb_profile_key}"
                ),
            }
            if profile
            else None
        ),
        "orb_verdict_available": (
            profile is not None
            or fixed_orb_degrees is not None
            or angle_orb_degrees is not None
        ),
        "orb_unavailable_reason_code": (
            None
            if profile is not None
            or fixed_orb_degrees is not None
            or angle_orb_degrees is not None
            else "orb_profile_not_selected"
        ),
        "orb_receipt": _orb_receipt(usable, orb),
        "angle_participation": {
            **module_state(
                requested=angles.requested or any(
                    item["category"] == "angle" for item in participants
                ),
                executed=angles.used,
                applicable=angles.applicable,
                available=angles.used,
                source="astronomical_data.angles.asc_and_mc" if angles.used else None,
                reason_code=(
                    None if angles.applicable else "house_calculation_not_executed"
                ),
            ),
            "participant_keys": [
                item["key"] for item in usable if item["category"] == "angle"
            ],
            "angle_angle_pairs_included": False,
            "applying_semantics": "not_applicable_angle_motion_not_modeled",
            "angle_pair_orb_degrees": angle_orb_degrees,
            "angle_pair_orb_source": (
                "user_override" if angle_orb_degrees is not None else None
            ),
        },
    }


def _perfection_receipt(include_perfection: bool, perfection_window_days: float) -> dict:
    """The perfection search's state before any pair is searched."""
    return {
        **module_state(
            requested=include_perfection,
            executed=include_perfection,
            applicable=include_perfection,
            available=include_perfection,
            source=PRODUCT_FORMULA_SOURCE if include_perfection else None,
            reason_code=None if include_perfection else "option_not_requested",
        ),
        "status": "computed" if include_perfection else "not_requested",
        "solver": SOLVER_NAME if include_perfection else None,
        "search_window_days": (
            perfection_window_days if include_perfection else None
        ),
        # 只對此刻入相位的 target 往後搜尋；其餘標 not_applying（Lilly 1647 p.107
        # 從入相位定義成相）。
        "semantics": (
            "forward_search_from_chart_moment_bounded_by_search_window_"
            "applying_targets_only"
        ),
        "searched_phases": ["applying"],
        "statuses": list(PERFECTION_STATUSES),
        "coverage": dict.fromkeys(PERFECTION_STATUSES, 0),
        "partial": None,
    }


def _evaluate_pairs(
    usable: list[dict],
    aspect_definitions: tuple[dict, ...],
    excluded_by_definition: list[dict],
    *,
    orb: OrbPolicy,
    partile_profile: dict,
    perfection: PerfectionSearch,
) -> tuple[list[dict], dict]:
    """Every comparable pair's record, and the perfection status counts."""

    coverage = dict.fromkeys(PERFECTION_STATUSES, 0)
    evaluated: list[dict] = []
    for index, participant_a in enumerate(usable):
        for participant_b in usable[index + 1:]:
            if (
                participant_a["category"] == "angle"
                and participant_b["category"] == "angle"
            ):
                continue
            pair_keys = frozenset({participant_a["key"], participant_b["key"]})
            exclusion = DEFINITIONAL_EXCLUDED_PAIRS.get(pair_keys)
            if exclusion is not None:
                # 同一條交點軸的南北兩端，或兩種交點模型之間：關係是定義或算法差，
                # 不是發現，不列為相位（bodies.DEFINITIONAL_EXCLUDED_PAIRS；赤緯模組同一表）。
                excluded_by_definition.append({
                    "keys": sorted(pair_keys),
                    "reason_code": exclusion,
                })
                continue
            record, statuses = _pair_record(
                participant_a,
                participant_b,
                aspect_definitions=aspect_definitions,
                orb=orb,
                partile_profile=partile_profile,
                perfection=perfection,
            )
            evaluated.append(record)
            for status in statuses:
                coverage[status] += 1
    return evaluated, coverage


def _settle_perfection(
    perfection: dict, coverage: dict, evaluated: list[dict], include_perfection: bool
) -> None:
    """Write the search coverage, and a refused source, into the perfection receipt."""

    perfection["coverage"] = coverage
    if include_perfection:
        searched = coverage["found"] + coverage["searched_no_root"]
        perfection["partial"] = searched < sum(coverage.values())
    if coverage["source_unavailable"]:
        refused = {
            target["perfection"]["reason_code"]
            for pair in evaluated
            for target in pair["aspect_targets"]
            if target["perfection_status"] == "source_unavailable"
        }
        # A server fault anywhere outranks the request leaving coverage: the
        # search stays applicable and is merely unavailable.
        reason_code, applicable = next(
            refusal
            for refusal in sorted(
                SEARCH_EPHEMERIS_REFUSALS.values(), key=lambda refusal: not refusal[1]
            )
            if refusal[0] in refused
        )
        perfection.update({
            "executed": True,
            "applicable": applicable,
            "available": False,
            "source": None,
            "status": "not_applicable",
            "reason_code": reason_code,
        })


@dataclass(frozen=True)
class AspectSettings:
    """The request's aspect options: set, orbs, angles, partile and perfection."""

    orb_profile_key: str | None = None
    aspect_set_profile_key: str = "ptolemaic_major_v1"
    orb_scale_percent: float | None = None
    fixed_orb_degrees: float | None = None
    angle_orb_degrees: float | None = None
    angles_requested: bool = False
    angles_applicable: bool = True
    partile_profile_key: str = DEFAULT_PARTILE_PROFILE_KEY
    include_perfection: bool = False
    jd_ut: float | None = None
    longitude_at: Callable[[int, float], float] | None = None
    perfection_window_days: float = DEFAULT_PERFECTION_WINDOW_DAYS
    orb_profile_selection_state: str | None = None


def compute_aspects(
    participants: list[dict],
    trace: Trace,
    *,
    settings: AspectSettings = AspectSettings(),
    pair_filter: Callable[[dict], bool] = pair_is_listed,
) -> dict:
    """對所有參與者的兩兩組合計算整宮配置與逐度相位。

    每一組都逐一計算；`pair_filter` 決定哪些列在 `pairs`（產品一律用 S2 的
    `pair_is_listed`），其餘只計數於 `pair_listing`。

    `participants` 的每一筆需要 key、name、longitude、category，
    可選 speed_longitude（缺少時入相位／出相位為 null）與 body_id
    （缺少時不計算成相時刻——阿拉伯點沒有對應的星曆天體）。
    """

    s = settings
    longitude_at = s.longitude_at

    # The request schema already refuses a scale without a profile and a fixed
    # orb beside one; an unknown key is refused here rather than silently
    # running without an orb table.
    profile = ORB_PROFILES.get(s.orb_profile_key) if s.orb_profile_key else None
    if s.orb_profile_key and profile is None:
        raise ValueError(f"unknown orb profile: {s.orb_profile_key}")
    aspect_set_profile = ASPECT_SET_PROFILES.get(s.aspect_set_profile_key)
    if aspect_set_profile is None:
        raise ValueError(f"unknown aspect set profile: {s.aspect_set_profile_key}")
    aspect_definitions = tuple(
        _ASPECT_BY_KEY[key] for key in aspect_set_profile["aspect_keys"]
    )
    degree_method_name = (
        DEGREE_ASPECT_METHOD_NAME
        if s.aspect_set_profile_key == "ptolemaic_major_v1"
        and s.fixed_orb_degrees is None
        and s.angle_orb_degrees is None
        else EXTENDED_DEGREE_ASPECT_METHOD_NAME
    )
    partile_profile = PARTILE_PROFILES.get(s.partile_profile_key)
    if partile_profile is None:
        raise ValueError(f"unknown partile profile: {s.partile_profile_key}")
    if longitude_at is not None:
        # Every pair's perfection search samples the same coarse grid.
        longitude_at = memoized_longitudes(longitude_at)
    usable = [
        participant
        for participant in participants
        if participant.get("longitude") is not None
    ]
    skipped = [
        participant["key"]
        for participant in participants
        if participant.get("longitude") is None
    ]
    orb = OrbPolicy(
        s.orb_profile_key, profile, s.orb_scale_percent, s.fixed_orb_degrees,
        s.angle_orb_degrees, s.orb_profile_selection_state,
    )
    angles = AngleUse(
        s.angles_requested, s.angles_applicable,
        any(item["category"] == "angle" for item in usable),
    )

    receipt: dict = {
        # 頂層 method 欄位讓 dossier methodology receipt 與其餘 derived_methods 同形；
        # 取整宮層的名稱，因為那層預設就產生判斷。
        **method_head(WHOLE_SIGN_METHOD_NAME, "aspects"),
        # Availability is settled below, once the pairs exist.
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "whole_sign": {
            **method_head(WHOLE_SIGN_METHOD_NAME, "aspects"),
            "method_provenance": "hellenistic_whole_sign_configuration_doctrine",
            "requires_orb": False,
            "source_ref": "aspects/whole_sign",
        },
        "degree_based": _degree_based_receipt(
            usable,
            participants,
            aspect_set_profile_key=s.aspect_set_profile_key,
            partile_profile_key=s.partile_profile_key,
            degree_method_name=degree_method_name,
            orb=orb,
            angles=angles,
        ),
        "perfection": _perfection_receipt(s.include_perfection, s.perfection_window_days),
        "participants": [
            {
                "key": participant["key"],
                "name": participant["name"],
                "category": participant["category"],
                "orb_eligible": participant["category"] in ORB_ELIGIBLE_CATEGORIES,
                **_sign_record(participant["longitude"]),
            }
            for participant in usable
        ],
        "excluded_participant_keys": skipped,
        "excluded_pairs_by_definition": [],
        "pairs": [],
        "pair_listing": None,
        "whole_sign_aversions": [],
    }

    evaluated, coverage = _evaluate_pairs(
        usable,
        aspect_definitions,
        receipt["excluded_pairs_by_definition"],
        orb=orb,
        partile_profile=partile_profile,
        perfection=PerfectionSearch(
            s.include_perfection, s.jd_ut, longitude_at, s.perfection_window_days
        ),
    )
    _settle_perfection(receipt["perfection"], coverage, evaluated, s.include_perfection)
    receipt["pairs"] = [pair for pair in evaluated if pair_filter(pair)]
    receipt["whole_sign_aversions"] = whole_sign_aversions(evaluated)
    receipt["pair_listing"] = _pair_listing(
        len(evaluated),
        len(receipt["pairs"]),
        PAIR_LISTING_RULE if pair_filter is pair_is_listed else "every_evaluated_pair",
    )
    if not evaluated:
        # Nothing to compare (fewer than two usable participants, or only a
        # pair excluded by definition): the module ran and has no result.
        receipt.update({
            "available": False,
            "source": None,
            "reason_code": "no_comparable_participant_pair",
        })

    _trace_summary(receipt, evaluated, trace)
    return receipt


def _orb_verdict_for_target(
    *,
    aspect: dict,
    target_offset: float,
    participant_a: dict,
    participant_b: dict,
    orb: OrbPolicy,
    contains_angle: bool,
) -> dict:
    """該 target 的容許度判定。"""

    profile = orb.profile
    fixed_orb_degrees, angle_orb_degrees = orb.fixed_orb_degrees, orb.angle_orb_degrees
    scale = orb.scale

    orb_a = orb_b = None
    in_orb: bool | None = None
    reason_code: str | None = None
    threshold = None
    rule = None
    if contains_angle and angle_orb_degrees is not None:
        threshold = angle_orb_degrees
        rule = "user_angle_pair_threshold"
        in_orb = abs(target_offset) <= threshold
    elif contains_angle:
        reason_code = "angle_orb_not_selected"
    elif fixed_orb_degrees is not None:
        threshold = fixed_orb_degrees
        rule = "user_fixed_pair_threshold"
        in_orb = abs(target_offset) <= threshold
    elif profile is None:
        reason_code = "orb_profile_not_selected"
    elif aspect["classification"] == "modern_minor":
        reason_code = "historical_orb_profile_not_applicable_to_modern_minor_aspect"
    else:
        eligible_a = participant_a["category"] in ORB_ELIGIBLE_CATEGORIES
        eligible_b = participant_b["category"] in ORB_ELIGIBLE_CATEGORIES
        raw_orb_a = profile["orbs_degrees"].get(participant_a["key"])
        raw_orb_b = profile["orbs_degrees"].get(participant_b["key"])
        orb_a = raw_orb_a * scale if raw_orb_a is not None else None
        orb_b = raw_orb_b * scale if raw_orb_b is not None else None
        if not eligible_a or not eligible_b or orb_a is None or orb_b is None:
            reason_code = "no_sourced_orb_for_participant"
        else:
            threshold = (orb_a + orb_b) / 2.0
            rule = "scaled_moiety" if orb.scaled else "moiety"
            in_orb = abs(target_offset) <= threshold
    return {
        "in_orb": in_orb,
        "in_orb_reason_code": reason_code,
        "pair_orb_threshold_degrees": threshold,
        "orb_rule": rule,
        "orb_a": orb_a,
        "orb_b": orb_b,
    }


def _unsearched_perfection(status: str, *, reason_code: str | None = None) -> dict:
    return {"status": status, "reason_code": reason_code, "crossing_count": None}


def _bracket_keys(separation: float, aspect_definitions: tuple[dict, ...]) -> set[str]:
    """The aspects just below and just above the separation."""

    below = max(
        (item for item in aspect_definitions if item["angle"] <= separation),
        key=lambda item: item["angle"],
        default=None,
    )
    above = min(
        (item for item in aspect_definitions if item["angle"] >= separation),
        key=lambda item: item["angle"],
        default=None,
    )
    return {item["key"] for item in (below, above) if item is not None}


def _nearest_aspect_record(key: str, signed_offset: float, is_tied: bool) -> dict:
    return {
        "key": key,
        "signed_offset_from_exact_degrees": degrees_number(signed_offset),
        # 相鄰兩相位中點處並列（見 _nearest_aspect）；消費端看旗標得知非唯一解。
        "is_tied": is_tied,
        "tie_rule": (
            "smaller_exact_angle_wins" if is_tied else None
        ),
    }


def _target_perfection(
    search: PerfectionSearch,
    participant_a: dict,
    participant_b: dict,
    *,
    signed_target: float,
    applying: str | None,
    verdict: dict,
    no_motion_reason: str | None,
    is_nearest: bool,
) -> dict:
    """One target's perfection: searched forward, or why it was not."""

    if not search.include:
        return _unsearched_perfection("not_requested", reason_code="option_not_requested")
    if no_motion_reason is not None:
        return _unsearched_perfection("no_motion_model", reason_code=no_motion_reason)
    if applying != "applying":
        return _unsearched_perfection("not_applying", reason_code=f"phase_now_{applying}")
    if verdict["in_orb"] is False:
        return _unsearched_perfection("outside_effective_orb")
    if verdict["in_orb"] is None and not is_nearest:
        return _unsearched_perfection(
            "no_orb_verdict_nearest_only",
            reason_code=verdict["in_orb_reason_code"],
        )
    # A motion model guarantees jd_ut and the sampler.
    if search.jd_ut is None or search.longitude_at is None:
        raise InternalInvariantError("jd_ut is not None and longitude_at is not None")
    return _search_perfection(
        participant_a=participant_a,
        participant_b=participant_b,
        signed_target=signed_target,
        jd_ut=search.jd_ut,
        longitude_at=search.longitude_at,
        perfection_window_days=search.window_days,
    )


def _pair_motion(
    participant_a: dict, participant_b: dict, perfection: PerfectionSearch, contains_angle: bool
) -> tuple[float | None, str | None, str | None]:
    """(relative speed, why no perfection search can run, why applying is null)."""

    speed_a = participant_a.get("speed_longitude")
    speed_b = participant_b.get("speed_longitude")
    relative_speed = (
        speed_a - speed_b
        if speed_a is not None and speed_b is not None
        else None
    )
    has_motion_model = (
        participant_a.get("body_id") is not None
        and participant_b.get("body_id") is not None
        and perfection.jd_ut is not None
        and perfection.longitude_at is not None
        and relative_speed is not None
    )
    no_motion_reason = (
        None if has_motion_model
        else "angle_motion_not_modeled" if contains_angle
        else "participant_has_no_ephemeris_body_or_speed"
    )
    applying_reason = (
        "angle_motion_not_modeled" if contains_angle
        else "relative_speed_unavailable" if relative_speed is None
        else None
    )
    return relative_speed, no_motion_reason, applying_reason


def _pair_record(
    participant_a: dict,
    participant_b: dict,
    *,
    aspect_definitions: tuple[dict, ...],
    orb: OrbPolicy,
    partile_profile: dict,
    perfection: PerfectionSearch,
) -> tuple[dict, list[str]]:
    """回傳 (pair 紀錄, 所有 target 的 perfection_status)；後者供 coverage 計數。"""

    lon_a = participant_a["longitude"]
    lon_b = participant_b["longitude"]
    delta = wrap_to_signed_180(lon_a - lon_b)
    separation = abs(delta)
    nearest, _nearest_offset, nearest_is_tied = _nearest_aspect(
        separation, aspect_definitions
    )

    contains_angle = (
        participant_a["category"] == "angle"
        or participant_b["category"] == "angle"
    )
    whole_sign = (
        {
            "applicable": False,
            "reason_code": "angle_not_a_whole_sign_doctrine_participant",
        }
        if contains_angle
        else _whole_sign_configuration(lon_a, lon_b)
    )
    relative_speed, no_motion_reason, applying_reason = _pair_motion(
        participant_a, participant_b, perfection, contains_angle
    )

    bracket_keys = _bracket_keys(separation, aspect_definitions)
    targets: list[dict] = []
    statuses: list[str] = []
    nearest_target: dict | None = None
    nearest_signed_offset = 0.0
    orb_a = orb_b = None
    pair_orbs: set[tuple[float, str]] = set()
    for aspect in aspect_definitions:
        signed_target = _signed_target(delta, aspect["angle"])
        signed_offset = wrap_to_signed_180(delta - signed_target)
        offset = separation - aspect["angle"]
        verdict = _orb_verdict_for_target(
            aspect=aspect,
            target_offset=offset,
            participant_a=participant_a,
            participant_b=participant_b,
            orb=orb,
            contains_angle=contains_angle,
        )
        applying = None if contains_angle else _applying(signed_offset, relative_speed)
        partile, partile_reason = _partile_for_target(
            lon_a=lon_a,
            lon_b=lon_b,
            target_offset=offset,
            profile=partile_profile,
            aspect=aspect,
            in_orb=verdict["in_orb"],
            whole_sign=whole_sign,
            contains_angle=contains_angle,
        )
        is_nearest = aspect["key"] == nearest["key"]

        target_perfection = _target_perfection(
            perfection,
            participant_a,
            participant_b,
            signed_target=signed_target,
            applying=applying,
            verdict=verdict,
            no_motion_reason=no_motion_reason,
            is_nearest=is_nearest,
        )

        if verdict["orb_rule"] is not None:
            pair_orbs.add((verdict["pair_orb_threshold_degrees"], verdict["orb_rule"]))
        # 名稱與精確角由 key 查 degree_based.aspect_names_zh／aspect_angles_degrees；
        # applying_reason_code 與容許度門檻對整個 pair 相同，放在 pair 層（回應大小預算）。
        target = {
            "key": aspect["key"],
            "offset_from_exact_degrees": degrees_number(offset),
            "in_orb": verdict["in_orb"],
            "in_orb_reason_code": verdict["in_orb_reason_code"],
            "applying": applying,
            "partile": partile,
            # Stated once per aspect in degree_based.partile_reason_codes_by_aspect.
            "partile_reason_code": (
                None if partile_reason == PARTILE_NOT_APPLICABLE_TO_MINOR else partile_reason
            ),
            "perfection_status": target_perfection["status"],
            "perfection": (
                target_perfection
                if target_perfection["status"] in SEARCHED_PERFECTION_STATUSES
                else None
            ),
        }
        statuses.append(target_perfection["status"])
        if is_nearest:
            nearest_target = target
            nearest_signed_offset = signed_offset
            orb_a, orb_b = verdict["orb_a"], verdict["orb_b"]
        if (
            aspect["key"] in bracket_keys
            or verdict["in_orb"] is True
            or target_perfection["status"] in SEARCHED_PERFECTION_STATUSES
        ):
            targets.append(target)

    if nearest_target is None:
        raise ValueError("nearest aspect must belong to aspect_definitions")
    # The threshold depends only on the pair (its participants and the orb
    # configuration); a target the rule does not govern says why in its
    # in_orb_reason_code.  Two thresholds in one pair would make the pair-level
    # value wrong for some target, so that is refused rather than reported.
    if len(pair_orbs) > 1:
        raise ValueError("one pair cannot have two orb thresholds")
    pair_threshold, pair_rule = next(iter(pair_orbs), (None, None))
    if not any(target is nearest_target for target in targets):
        # ASPECT_TARGET_LISTING.nearest_aspect_entry 是消費端唯一的取值路徑。
        raise ValueError("nearest aspect target must be listed in aspect_targets")

    record = {
        "body_a": participant_a["key"],
        "body_a_name": participant_a["name"],
        "body_b": participant_b["key"],
        "body_b_name": participant_b["name"],
        "separation_degrees": degrees_number(separation),
        "whole_sign": whole_sign,
        # 顯示用摘要：只帶最近相位的 key 與幾何。它的判定（in_orb／applying／partile／
        # perfection 與 offset_from_exact_degrees）只有一個家：aspect_targets 裡 key 相同的那一格
        # （ASPECT_TARGET_LISTING 保證它一定列出）。pair 頂層不另抄一份：全選項回應約多
        # 59 KB，會使非精確出生時間的回應超出 512 KiB 預算。
        "nearest_aspect": _nearest_aspect_record(
            nearest["key"], nearest_signed_offset, nearest_is_tied
        ),
        "aspect_targets": targets,
        "aspects_in_orb": [target["key"] for target in targets if target["in_orb"] is True],
        # Every target with a verdict（in_orb_reason_code null）was judged by this
        # threshold and rule; both are null when no target has a verdict.
        "pair_orb_threshold_degrees": pair_threshold,
        "orb_rule": pair_rule,
        "moiety_sum_degrees": (
            (orb_a + orb_b) / 2.0
            if orb_a is not None and orb_b is not None
            else None
        ),
        "orb_degrees": {
            participant_a["key"]: orb_a,
            participant_b["key"]: orb_b,
        },
        # 對整個 pair 相同（角點不建模、相對速度未知），不屬於任何單一 target。
        "applying_reason_code": applying_reason,
        "relative_longitude_speed": (
            None if relative_speed is None else degrees_number(relative_speed)
        ),
    }
    return record, statuses


def _search_perfection(
    *,
    participant_a: dict,
    participant_b: dict,
    signed_target: float,
    jd_ut: float,
    longitude_at: Callable[[int, float], float],
    perfection_window_days: float,
) -> dict:
    try:
        crossings = _perfection_times(
            participant_a=participant_a,
            participant_b=participant_b,
            signed_target=signed_target,
            jd_ut=jd_ut,
            longitude_at=longitude_at,
            window_days=perfection_window_days,
        )
    except FullEphemerisRequiredError as error:
        if error.reason not in SEARCH_EPHEMERIS_REFUSALS:
            raise
        reason_code = SEARCH_EPHEMERIS_REFUSALS[error.reason][0]
        # The solver and the window are the same for every target and are
        # stated once in the module's `perfection` receipt.
        return {
            "status": "source_unavailable",
            "reason_code": reason_code,
            "crossing_count": 0,
            "hours_from_chart_moment": [],
            "julian_day_ut": [],
            "not_found_reason_code": reason_code,
        }
    times = [crossing["t"] for crossing in crossings]
    return {
        "status": "found" if times else "searched_no_root",
        "reason_code": None,
        "crossing_count": len(times),
        # 距盤時刻只存小時（頁面讀這一份）與 JD；日數是同一個量。
        # To 10⁻⁵ hour and 10⁻⁶ day: finer than the solver's time tolerance
        # (PERFECTION_TOLERANCE_DAYS), so no digit the search resolved is lost.
        "hours_from_chart_moment": [round(value * 24.0, 5) for value in times],
        "julian_day_ut": [round(jd_ut + value, 6) for value in times],
        "not_found_reason_code": (
            None if times else "no_perfection_within_search_window"
        ),
    }


def nearest_aspect_target(pair: dict) -> dict:
    """pair 的最近相位那一格；判定只存在 aspect_targets（ASPECT_TARGET_LISTING）。"""

    key = pair["nearest_aspect"]["key"]
    return next(target for target in pair["aspect_targets"] if target["key"] == key)


def _trace_summary(receipt: dict, evaluated: list[dict], trace: Trace) -> None:
    whole_sign_hits = [
        pair
        for pair in evaluated
        if pair["whole_sign"].get("in_aspect") is True
    ]
    trace.add(
        f"整宮配置 (method={WHOLE_SIGN_METHOD_NAME})",
        formula="星座距離 = min((星座B − 星座A) mod 12, 12 − 同值)；0/2/3/4/6 → 合/六分/刑/拱/沖，其餘不合意",
        inputs={"參與者數": len(receipt["participants"])},
        result={
            "組合總數": len(evaluated),
            "成整宮相位者": len(whole_sign_hits),
            "列出組數": receipt["pair_listing"]["listed_pairs"],
            "未列出（沒有相位）組數": receipt["pair_listing"]["unlisted_pairs_without_aspect"],
        },
        note="此層不需容許度：星座距離是算術，配置名稱是希臘化占星的成文教義。",
    )

    orb_receipt = receipt["degree_based"]["orb_receipt"]
    if not orb_receipt["available"]:
        trace.add(
            f"逐度相位 (method={DEGREE_ASPECT_METHOD_NAME})",
            formula="角距離與距離精確相位的差為純幾何量；是否成立需要容許度表",
            note="⚠ 未指定 orb_profile，故 in_orb 全部回傳 null。角距離、入相位／出相位仍為有效輸出。"
                 "容許度表的選擇屬方法裁決，本程式不自行指定。",
        )
        return

    in_orb_hits = [pair for pair in evaluated if pair["aspects_in_orb"]]
    # The step names the settings and the counts; the full orb receipt and every
    # pair's verdicts are in the response once (degree_based.orb_receipt and the
    # aspects table), not copied into the trace.
    settings = {
        "容許度表": orb_receipt["profile_key"],
        # Product default or the user's choice: the same table, a different receipt.
        "容許度表的選擇": orb_receipt["profile_selection"],
        "容許度比例（%）": orb_receipt["scale_percent"],
        "固定門檻（度）": orb_receipt["fixed_pair_threshold_degrees"],
        "軸點門檻（度）": orb_receipt["angle_pair_threshold_degrees"],
    }
    trace.add(
        f"逐度相位 (method={receipt['degree_based']['method']}, orb_configuration={orb_receipt['configuration_mode']})",
        formula="某相位成立：|角距離 − 該相位的精確角| ≤ 該組的容許度門檻（剛好等於也算）；"
                "門檻算法見 degree_based.orb_receipt.pair_threshold_formula，"
                "每組用的門檻是 pairs[].pair_orb_threshold_degrees",
        inputs={
            **{name: value for name, value in settings.items() if value is not None},
            "逐度相位集合": receipt["degree_based"]["aspect_set_profile"],
            "完整容許度收據": "derived_methods.aspects.degree_based.orb_receipt",
        },
        result={
            "成逐度相位者": sum(len(pair["aspects_in_orb"]) for pair in in_orb_hits),
            "有逐度相位的組合": len(in_orb_hits),
            "逐組明細": "見相位表（derived_methods.aspects.pairs：每組的 aspects_in_orb、"
                        "各相位的距精確度數與入／出相位）",
        },
        note=(
            "orb 數值出自具名歷史來源（degree_based.orb_profile_detail）；method_status 仍為待審閱，"
            "不表示本產品已採用該表為正式技法。"
            if orb_receipt["profile_key"] is not None
            else "門檻是你指定的固定度數，不是歷史容許度表。"
        ),
    )


WHOLE_SIGN_SOURCES = (
    "Ptolemy I.13 (Robbins pp.73-75 = Hübner I.14), I.16 (pp.77-79 = "
    "Hübner I.17); Ps.-Porphyry 'On bearing testimony' (Antiochus; CCAG "
    "V.4 pp.185-228, chapter not checked). Counts signs between; Firmicus "
    "II.22 counts inclusively (trine = fifth sign)"
)
# The loci WHOLE_SIGN_SOURCES names; the record does not say what was read.
WHOLE_SIGN_SOURCE_CITATIONS = [
    cited("Ptolemy, Tetrabiblos I.13 (Robbins pp.73-75 = Hübner I.14), I.16 (pp.77-79 = Hübner I.17)",
          "aspects counted by the signs between", "translation_read",
          ("Robbins's English translation on LacusCurtius (Tetrabiblos/1B*.html): I.13 "
           "after the p73 page mark ('four signs, and 120 degrees'), I.16 between the p77 "
           "and p79 marks ('either one or five signs apart'); the Greek not read")),
    reference_only(
        "Ps.-Porphyry, 'On bearing testimony' (Antiochus; CCAG V.4 pp.185-228)",
        "aspects by sign; chapter not checked",
    ),
    cited("Firmicus Maternus, Mathesis II.22", "counts inclusively (trine = fifth sign)",
          "original_language_read",
          ("the Latin of Kroll-Skutsch as transcribed on LacusCurtius "
           "(Firmicus_Maternus/Mathesis/2*.html), II.22.3: 'Trigonum <est> a signo, a quo "
           "initiamus, V. signum'")),
]
_HARMONICES_MUNDI_READ_AT = (
    "the Latin of the Linz 1619 printing in the archive.org scan of the Smithsonian "
    "Libraries copy (ioanniskepplerih00kepl), read at the cited pages: p.145 leaf n234, "
    "pp.147-148 leaves n236-n237, p.155 leaf n244"
)
KEPLER_MINOR_ASPECT_SOURCES = [
    cited(("Kepler, De fundamentis astrologiae certioribus (Pragae: Schumann, 1602), "
           "Thesis XXXVIII, sig. C1v of the 1602 printing (unpaginated)"),
          ("quintile, biquintile and sesquiquadrate added to the five aspects of the "
           "ancients"),
          ORIGINAL_LANGUAGE_READ,
          ("the 1602 printing, image 21 of the Royal Library Copenhagen copy, "
           "archive.org den-kbd-pil-20002065-001; Frisch, Opera omnia I (1858) p.428 "
           "not checked")),
    cited(("Kepler, Harmonices mundi (Linz 1619) Lib. IV cap. V, Prop. XII p.145, "
           "Prop. XIII pp.147-148, Prop. XIV p.148"),
          ("third grade: trine, sextile, semisextile (Prop. XII); fourth grade: "
           "quintile, biquintile, quincunx (Prop. XIII); fifth, weakest grade: decile, "
           "tridecile, octile = semisquare, trioctile = sesquiquadrate (Prop. XIV)"),
          ORIGINAL_LANGUAGE_READ, _HARMONICES_MUNDI_READ_AT),
    cited("Kepler, Harmonices mundi (1619) Lib. IV cap. VI p.155",
          ("octile and sesquiquadrate have no power unless the primary aspects are "
           "long absent"),
          ORIGINAL_LANGUAGE_READ, _HARMONICES_MUNDI_READ_AT),
]

METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "aspects/whole_sign": {
        "applies_to": "derived_methods.aspects.whole_sign",
        "sources": WHOLE_SIGN_SOURCE_CITATIONS,
        "source_summary": WHOLE_SIGN_SOURCES,
    },
    "aspects/minor_aspects": {
        "applies_to": "derived_methods.aspects.degree_based (modern minor aspects)",
        "kepler_status_by_aspect": {
            aspect["key"]: aspect["kepler_status"] for aspect in MODERN_MINOR_ASPECTS
        },
        "sources": KEPLER_MINOR_ASPECT_SOURCES,
    },
    **{
        f"aspects/orb/{key}": {
            "applies_to": "derived_methods.aspects.degree_based.orb_profile_detail",
            # The status flags the response carries, and the reasons beside them.
            **profile["source_verification"],
            "tabulated_from": list(profile["tabulated_from"]),
            "sources": list(profile["sources"]),
            **{
                note: profile[note]
                for note in ("pair_combination_rule_note", "second_set_not_used")
                if note in profile
            },
        }
        for key, profile in ORB_PROFILES.items()
    },
    "aspects/orb_boundary": {
        "applies_to": "derived_methods.aspects.degree_based.orb_receipt.boundary_operator",
        "boundary_operator": ORB_BOUNDARY_OPERATOR,
        "boundary_provenance": "product_convention",
        "sources": [
            cited("William Lilly, Christian Astrology (1647) p.110",
                  ("the planets are not totally separated until 'fully 9 degrees "
                   "distant' (indirect; reads as leaning exclusive, not a stated rule)"),
                  ORIGINAL_LANGUAGE_READ, LILLY_1647_READ_AT),
        ],
        "note": (
            "No checked pre-modern text states whether an offset exactly equal to the "
            "orb is inside it. The product keeps <= because exact equality practically "
            "never occurs on a real chart."
        ),
    },
    "aspects/partile": {
        "applies_to": "derived_methods.aspects.degree_based.partile_source_verification",
        **_PARTILE_SOURCE_VERIFICATION,
        "tabulated_from": list(PARTILE_TABULATED_FROM),
        "valid_aspect_rule": PARTILE_VALID_ASPECT_RULE,
        # These ground only the same-degree profile's precondition.
        "valid_aspect_rule_profiles": sorted(
            key
            for key, profile in PARTILE_PROFILES.items()
            if profile["valid_aspect_precondition"] is not None
        ),
        "valid_aspect_sources": [
            cited("William Lilly, Christian Astrology (1647) Book I ch. XIX p.106",
                  ("both partile examples (Venus 9 Aries / Jupiter 9 Leo, Sun 1 Taurus / "
                   "Moon 1 Cancer) are sign aspects first"),
                  ORIGINAL_LANGUAGE_READ, LILLY_1647_READ_AT),
            cited("William Lilly, Christian Astrology (1647) p.109",
                  "signs that do not behold one another 'cannot have any aspect'",
                  ORIGINAL_LANGUAGE_READ, LILLY_1647_READ_AT),
            cited("al-Bīrūnī, The Book of Instruction, trans. R. Ramsay Wright (1934) §446",
                  "partile defined among planets in signs that aspect each other",
                  TRANSLATION_READ, "R. Ramsay Wright's English translation (1934)"),
        ],
    },
    **{
        f"aspects/partile/{key}": {
            "applies_to": "derived_methods.aspects.degree_based.partile_profile_detail",
            "sources": list(profile["sources"]),
        }
        for key, profile in PARTILE_PROFILES.items()
    },
}
