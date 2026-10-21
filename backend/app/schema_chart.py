"""The /api/chart options and request."""

from typing import Any, Literal, Optional

from pydantic import Field, model_validator

from .core.moon import DEFAULT_VOC_METHOD, VocMethod
from .core.dodecatemoria import DEFAULT_DODECATEMORIA_PROFILE, DodecatemoriaProfileOption
from .core.solar_phase import DEFAULT_SOLAR_PHASE_PROFILE, SolarPhaseProfile
from .schema_rules import (
    KNOWN_UTC_LEAP_SECOND_DATES,
    StrictInputModel,
    _leap_second_label_in_utc,
    _rule_error,
)
from .schema_inputs import (
    AtmosphereInput,
    ComputationModeInput,
    DateTimeInput,
    LocationInput,
    TimezoneInput,
)


# 使用者只給固定門檻時，產品預設容許度表讓位而不是衝突。預設值由 pydantic 依已驗證欄位
# 產生（而不是在 after-validator 事後清掉，那會繞過驗證，讓 requested_options 的回聲重送時
# 422）：欄位仍不在 model_fields_set（input_presence 仍為 defaulted），之後的檢查看到的
# 就是生效值。core.aspects.DEFAULT_ORB_PROFILE_KEY 必須等於此值（測試看守）。
OrbProfileKey = Literal["abu_mashar_lineage_v1", "lilly_1647_experience_v1"]
_PRODUCT_DEFAULT_ORB_PROFILE: OrbProfileKey = "lilly_1647_experience_v1"


def _default_aspect_orb_profile(validated: dict[str, Any]) -> OrbProfileKey | None:
    if validated.get("aspect_fixed_orb_degrees") is not None:
        return None
    return _PRODUCT_DEFAULT_ORB_PROFILE


# The house systems /api/chart casts; the annual route's solar-return chart
# accepts the same set.
HouseSystemCode = Literal["B", "R", "W", "P", "O", "E", "C"]


class OptionsInput(StrictInputModel):
    # 一次只計算一種宮位制。選擇何種宮位制屬方法決策，不宣稱各宮位制具有相同權威地位。
    # `False` 是真正的無宮位模式：不得先算完再從 response 隱藏。
    # house_system 在此時只保留為未執行的 request 欄位，不得出現在 effective receipt。
    include_houses: bool = True
    house_system: HouseSystemCode = "W"
    include_fixed_stars: bool = False
    # 產品核心是可驗證的天文數值；需要古典方法選擇的判斷一律 opt-in，
    # 不因 Swiss Ephemeris 能提供原料就假裝方法已獲採用。
    include_lots: bool = False
    include_antiscia: bool = False
    # 反照點的對象範圍為「七政（必要）＋交點（可選）」，
    # 恆星與軸點不計算。此開關即其中的「可選」。
    antiscia_include_nodes: bool = False
    include_void_of_course: bool = False
    # 月空亡的定義：預設為換座前精確完成；另可選 Porphyry 名下的 30° 定義，或 Lilly
    # 以換座為界、以 moiety 容許度判入相位的定義。
    void_of_course_method: VocMethod = DEFAULT_VOC_METHOD
    include_declination_aspects: bool = False
    # 赤緯相位的研究性分類不變；1°只是既有產品預設。使用者可在 0–3°
    # 間明示覆寫，response 必須保存 default 與 effective 值。0 是合法值，定義為
    # 「赤緯完全相等才算」。
    declination_aspect_orb_degrees: float = Field(ge=0.0, le=3.0, default=1.0)
    include_outer_planets: bool = False
    include_chiron: bool = False
    # 平均遠地點、Swiss 的
    # interpolated/natural 遠地點，以及獨立計算的 natural 近地點。
    # 三者是現代／研究附加點，不因開啟而自動參與相位或古典方法。
    include_lilith_priapus: bool = False
    # 整體計算模式維持 geocentric，但月亮另以出生地站心位置取代
    # bodies 中的 effective Moon；response 同時保存地心 reference。此選項不等於
    # 「比較準」，而是明示的 mixed-origin coordinate policy。
    moon_position_profile: Literal[
        "global_computation_mode", "moon_only_topocentric_v1"
    ] = "global_computation_mode"
    # 南交點不是另一個 Swiss body：它是所選北交點方向的精確對蹠點。
    # 預設保留既有兩個北交點；明示要求時才把兩個導出南交點加入 nodes。
    include_south_nodes: bool = False
    include_lunar_phases: bool = False
    include_eclipses: bool = False
    include_rise_set_transits: bool = False

    # 黃道相位：預設開啟、可 opt-out，經明確方法決定（待審閱方法項目不得默默成為預設）。
    # 本檔唯一預設開啟的判斷類選項：整宮配置與角距離是算術；逐度層 `in_orb` 預設依
    # Lilly 1647 moiety 表（收據標為產品預設、可切換）。方法收據仍為 provisional，Dossier
    # 仍發出 `provisional_method_result`——預設開啟不等於方法已獲採用。
    include_aspects: bool = True
    # 明示傳 null 表示不套用任何表（預設表見 _PRODUCT_DEFAULT_ORB_PROFILE）。
    # 固定門檻宣告在容許度表之前：表的預設值依已驗證的固定門檻決定（default_factory）。
    aspect_fixed_orb_degrees: Optional[float] = Field(
        gt=0.0, le=30.0, default=None
    )
    aspect_orb_profile: Optional[OrbProfileKey] = Field(
        default_factory=_default_aspect_orb_profile
    )
    # 逐度相位集合與整宮 doctrine 分開：不論選哪個逐度集合，整宮層仍只使用
    # 合相與四種傳統相位。現代小相位 profile 是使用者選項，不宣稱古典權威。
    aspect_set_profile: Literal[
        "ptolemaic_major_v1",
        "modern_common_minor_v1",
        "modern_quintile_family_v1",
        "modern_minor_combined_v1",
    ] = "ptolemaic_major_v1"
    # 兩種明示覆寫互斥：具名七政 orb 表可按百分比縮放；或直接指定所有逐度
    # 配對的固定門檻。後者是 user override，不繼承歷史來源宣稱。
    aspect_orb_scale_percent: Optional[float] = Field(
        gt=0.0, le=300.0, default=None
    )
    # Partile 三種慣例並存，其中兩種載於 Lilly 名下著作且互相矛盾（1677 那條出自未署名的
    # 格言節）。與 orb 表不同，這一項有預設值：「同一整數度」是最通行者。
    partile_profile: Literal[
        "same_degree_number_v1",
        "within_one_degree_v1",
        "lilly_1677_three_degrees_v1",
    ] = "same_degree_number_v1"
    # 成相時刻需要在時間軸上反覆查星曆，比其餘欄位昂貴一個量級，故預設關閉。
    include_aspect_perfection: bool = False
    # 三王星與阿拉伯點是否參與相位，直接跟隨其本身的計算開關，避免出現
    # 「要求三王星入相位但沒算三王星」這種自相矛盾的請求。交點永遠已算出，
    # 故單獨給一個開關。
    aspect_include_nodes: bool = False
    # ASC／MC 只加入逐度層；不加入整宮 doctrine、不互相配對，也不推測日周運動
    # 的 applying。若未給角點門檻，仍輸出幾何但 in_orb 為 null。
    aspect_include_angles: bool = False
    aspect_angle_orb_degrees: Optional[float] = Field(
        gt=0.0, le=30.0, default=None
    )

    # 非古典角點：Vertex 等五個由 swe.houses_ex 附帶回傳，輸出在
    # astronomical_data.extra_angles，`angles` 的鍵集合不變。
    include_extra_angles: bool = False
    # Anti-Vertex 是 Vertex 的黃道對蹠點，可單獨要求，不必同時輸出其餘四個
    # 現代技術角點。
    include_anti_vertex: bool = False

    # 純後端 body preset。它只約束「星體目錄」的現代附加物件；交點、Lots 與
    # 額外角點是 points/method outputs，刻意不被此 preset 靜默關閉。
    body_selection_preset: Literal["custom", "classical_seven_v1"] = "custom"

    # 具名古典尊貴元件：只回傳規則／表格結果，不打分、不解讀。
    # 界、面、三分性另可選「all」（全部並列）：本版每一套具名表都算，依下面列出的順序，
    # 回應的 computed_profiles 寫出展開後的 id（core/essential_dignities.py PROFILE_IDS）。
    # 傳統七政的廟、旺與其對面的陷、弱，只判整個星座。精確擢升度數、互容與總分
    # 均不在此開關範圍。
    include_domicile_exaltation: bool = False
    bounds_profile: Optional[
        Literal[
            "egyptian_bounds_robbins_1940_v1",
            "chaldaean_bounds_ptolemy_i_21_v1",
            "ptolemy_bounds_robbins_1940_v1",
            "lilly_received_bounds_1647_v1",
            "all",
        ]
    ] = None
    decan_profile: Optional[
        Literal[
            "chaldean_planetary_faces_firmicus_ii_4_v1",
            "manilius_sign_decans_astronomica_iv_v1",
            "all",
        ]
    ] = None
    triplicity_profile: Optional[
        Literal[
            "dorothean_triplicity_three_rulers_v1",
            "ptolemy_triplicity_textual_corulership_v1",
            "lilly_triplicity_compact_1647_v1",
            "all",
        ]
    ] = None
    # 選了「all」（全部並列）時三套都已並列，這個開關不再多加什麼；舊請求照樣接受。
    triplicity_include_research_comparison: bool = False
    # 外來：五項本質尊貴一項都沒有。只有一套定義（Lilly 1647 p.112），固定用他自己
    # p.104 的表判定，不跟上面選的界、面、三分性。
    peregrine_profile: Optional[Literal["lilly_1647_p112_v1"]] = None

    # 十二分部（dodecatemoria）：名單與規則在 core/dodecatemoria.py；文獻兩種算法
    # 並存，具名 profile 平等提供。
    include_dodecatemoria: bool = False
    # 「all」：兩種都算；頂層的 points 仍是預設那一種（出生時刻敏感度也讀它），
    # 每一種的結果在 profile_results。
    dodecatemoria_profile: DodecatemoriaProfileOption = DEFAULT_DODECATEMORIA_PROFILE
    # 月宿：月亮落在黃道二十八等分的哪一宿。只計算位置，不解讀。
    include_lunar_mansions: bool = False
    # 各行星離太陽多遠：日輪內、焦傷、在光束下。門檻與分法在 core/solar_phase.py；
    # 文獻有三套數值，具名 profile 提供；落在太陽圓面內的日輪內判法是選用旗標，不設預設。
    include_solar_phase: bool = False
    solar_phase_profile: SolarPhaseProfile = DEFAULT_SOLAR_PHASE_PROFILE
    solar_phase_disc_cazimi: bool = False
    # 行星與宮的古典分類：吉凶、日夜區、喜樂宮、hayz／halb、十二宮的名稱與分類，各標出處。
    include_classical_classifications: bool = False
    # 行速快慢、停滯、東出西入（相對太陽）。平均行度與停滯天數在 core/motion_states.py。
    include_motion_states: bool = False

    @model_validator(mode="after")
    def check_body_selection_preset(self):
        if self.body_selection_preset != "classical_seven_v1":
            return self
        incompatible = [
            name
            for name in (
                "include_outer_planets",
                "include_fixed_stars",
                "include_chiron",
                "include_lilith_priapus",
            )
            if getattr(self, name)
        ]
        if incompatible:
            raise _rule_error("body_selection_conflict")
        return self

    @model_validator(mode="after")
    def check_aspect_orb_configuration(self):
        if (
            self.aspect_orb_scale_percent is not None
            and self.aspect_orb_profile is None
        ):
            raise _rule_error("aspect_orb_scale_requires_profile")
        if (
            self.aspect_fixed_orb_degrees is not None
            and self.aspect_orb_profile is not None
        ):
            raise _rule_error("aspect_orb_sources_conflict")
        if (
            self.aspect_angle_orb_degrees is not None
            and not self.aspect_include_angles
        ):
            raise _rule_error("aspect_angle_orb_requires_angles")
        return self


def _check_leap_second(model) -> None:
    if model.datetime.second != 60:
        return
    utc_label = _leap_second_label_in_utc(model.datetime, model.timezone)
    if model.datetime.year < 1972 or (
        utc_label is not None and utc_label.year < 1972
    ):
        raise _rule_error(
            "leap_second_not_applicable_to_pre_1972_scale", "datetime", "second"
        )
    # Exactly 23:59:59 UTC: an offset that is not whole minutes has no `:60`
    # label, and checking only hour and minute let one through as 23:58:60.
    if (
        model.birth_time_precision != "exact"
        or utc_label is None
        or (utc_label.hour, utc_label.minute, utc_label.second) != (23, 59, 59)
        or utc_label.microsecond != 0
    ):
        raise _rule_error(
            "leap_second_requires_exact_utc_2359", "datetime", "second"
        )
    if (
        utc_label.year,
        utc_label.month,
        utc_label.day,
    ) not in KNOWN_UTC_LEAP_SECOND_DATES:
        raise _rule_error(
            "leap_second_not_in_bundled_table", "datetime", "second"
        )


def _check_precision_clock(model) -> None:
    # approximate_hour means [H:00,H+1:00) in the named fold ("born in the 14
    # o'clock hour"), not "around 14:00"; the sensitivity pass samples exactly
    # that interval, so minute and second must stay zero.
    if model.birth_time_precision == "approximate_hour" and (
        model.datetime.minute != 0 or model.datetime.second != 0
    ):
        raise _rule_error("approximate_hour_requires_zero_subhour")
    if model.birth_time_precision == "date_only":
        if (
            model.datetime.hour != 0
            or model.datetime.minute != 0
            or model.datetime.second != 0
        ):
            raise _rule_error("date_only_requires_zero_time")
        # include_houses is kept as sent: rewriting it fabricated an input in
        # the receipt.  The house module reports not_applicable itself
        # (date_only_no_birth_time).


class ChartRequest(StrictInputModel):
    birth_time_precision: Literal[
        "exact", "approximate_hour", "date_only"
    ] = "exact"
    datetime: DateTimeInput
    timezone: TimezoneInput
    location: LocationInput
    atmosphere: AtmosphereInput = Field(default_factory=AtmosphereInput)
    computation_mode: ComputationModeInput = Field(default_factory=ComputationModeInput)
    options: OptionsInput = Field(default_factory=OptionsInput)

    @model_validator(mode="after")
    def check_birth_time_precision(self):
        _check_leap_second(self)
        if (
            self.options.moon_position_profile
            == "moon_only_topocentric_v1"
            and self.computation_mode.center != "geocentric"
        ):
            raise _rule_error("moon_profile_center_conflict")
        _check_precision_clock(self)
        return self
