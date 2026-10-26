"""方法狀態的唯一產生器。

每個模組讀這裡，不各自寫一個 `METHOD_STATUS` 常數：各自的常數在方法採用之後沒有人
回頭改，已採用的方法會繼續自稱「待審閱」。

`method_status` 是兩值閉集：

- `decided`：產品已採用這個方法的輸出方式。採用是產品決定，不是歷史或天文上的驗證。
- `provisional_pending_method_audit`：還沒有採用這個方法，或明文維持 provisional；
  Dossier 對算出的結果發出 `provisional_method_result`。

方法狀態只是內部收據欄位：一般畫面不顯示。

每張方法收據也帶時期標籤：

- `period`：產品預設所依循的出處屬於哪個時期（閉集 `METHOD_PERIODS`）。天文計算本身
  （宮位分割的數值、月亮遠近點、視差）不是古典方法，標 `modern`。
- `name_status`：輸出用來稱呼這個方法的名字是不是所引出處自己的用語（`source_term`），
  還是現代整理者或本產品的稱呼（`modern_label`）。「古典」一詞因此可以逐方法標出時期，
  不必整體宣稱。
"""

from __future__ import annotations

from collections.abc import Iterable

METHOD_STATUS_DECIDED = "decided"
METHOD_STATUS_PROVISIONAL = "provisional_pending_method_audit"

DECIDED_METHODS: frozenset[str] = frozenset({
    "house_division",
    "planet_in_house",
    "sect",
    "declination_aspects",
    "lunar_apsides",
    "parallax_moon",
    "essential_dignities",
    # 十二分部：預設算法、列出的點與守護行星表已追認。
    "dodecatemoria",
    # 月宿：起點、等分、不適用的口徑、交界門檻、出生時刻不精確時的列法與宿名寫法都已裁定。
    "lunar_mansions",
    # 焦傷與光束下：預設分法、界線開閉、7 天門檻與月亮的晨昏側都已裁定。
    "solar_phase",
    # 行星與宮的古典分類：地平上下的判準、預設的出處組合與各欄寫法都已裁定。
    "classical_classifications",
    # 行速、停滯與東出西入：平均行度、逆行比法、月亮門檻、停滯天數與東出西入的意思都已裁定。
    "motion_states",
})

# 維持 provisional 的方法：Lots 隨可用的上升點保留 provisional；月空亡的定義仍未定，
# 已定的只有求解法；相位預設開啟不等於採用該方法；行星時隨基本輸出計算，但核准加入
# 輸出不等於採用其定義（日主取日出所在民用日期等）。
PROVISIONAL_METHODS: frozenset[str] = frozenset({
    "lots", "void_of_course", "aspects", "planetary_hours",
})

# The annual route's methods: provisional until their output rows are decided.
# Kept apart so the chart's partition test can name what /api/chart emits.
ANNUAL_PROVISIONAL_METHODS: frozenset[str] = frozenset({
    "annual_profection", "firdaria", "zodiacal_releasing", "extended_lots", "decennials",
    "monthly_profection", "solar_return_chart",
})

METHOD_PERIODS: tuple[str, ...] = (
    "hellenistic", "medieval_arabic", "medieval_latin", "renaissance_early_modern", "modern",
)
NAME_STATUSES: tuple[str, ...] = ("source_term", "modern_label")

# method module -> (period, name_status)
METHOD_PERIOD_LABELS: dict[str, tuple[str, str]] = {
    "house_division": ("modern", "modern_label"),
    "planet_in_house": ("hellenistic", "modern_label"),
    "sect": ("hellenistic", "source_term"),
    "declination_aspects": ("renaissance_early_modern", "modern_label"),
    "lunar_apsides": ("modern", "modern_label"),
    "parallax_moon": ("modern", "modern_label"),
    "essential_dignities": ("medieval_arabic", "source_term"),
    "dodecatemoria": ("hellenistic", "source_term"),
    "lunar_mansions": ("medieval_arabic", "source_term"),
    "solar_phase": ("renaissance_early_modern", "source_term"),
    "classical_classifications": ("hellenistic", "modern_label"),
    "motion_states": ("renaissance_early_modern", "modern_label"),
    "lots": ("hellenistic", "source_term"),
    # The default VOC definition: attribution unresolved, combined form is modern
    # (moon.VOC_METHOD_PROVENANCE).  The two alternatives carry their own period
    # through moon.VOC_METHOD_PERIODS.
    "void_of_course": ("modern", "source_term"),
    "aspects": ("hellenistic", "source_term"),
    # Unequal hours counted from sunrise are cited only to Lilly 1647; Dio gives
    # no more than the weekday order.
    "planetary_hours": ("renaissance_early_modern", "source_term"),
    "annual_profection": ("hellenistic", "source_term"),
    "firdaria": ("medieval_arabic", "source_term"),
    "zodiacal_releasing": ("hellenistic", "modern_label"),
    # Formulas from Paulus ch.23 and Valens IV.25; the chart route nests them under
    # lots (hellenistic), so both routes say the same (report L3).
    "extended_lots": ("hellenistic", "modern_label"),
    "decennials": ("hellenistic", "modern_label"),
    "monthly_profection": ("medieval_arabic", "source_term"),
    "solar_return_chart": ("medieval_arabic", "modern_label"),
}

# Each selectable named profile's own period: a module's profiles can follow sources
# of different periods (Lilly's bounds beside Ptolemy's), so a profile result
# carries this besides its module's `period`.  The period is that of the sources
# the profile cites; a modern editor reporting an unnamed older usage is modern.
PROFILE_PERIODS: dict[str, str] = {
    # Essential dignities.
    "traditional_seven_domicile_exaltation_signs_v1": "hellenistic",
    "egyptian_bounds_robbins_1940_v1": "hellenistic",
    "chaldaean_bounds_ptolemy_i_21_v1": "hellenistic",
    "ptolemy_bounds_robbins_1940_v1": "hellenistic",
    "lilly_received_bounds_1647_v1": "renaissance_early_modern",
    "chaldean_planetary_faces_firmicus_ii_4_v1": "hellenistic",
    "manilius_sign_decans_astronomica_iv_v1": "hellenistic",
    "dorothean_triplicity_three_rulers_v1": "hellenistic",
    "ptolemy_triplicity_textual_corulership_v1": "hellenistic",
    "lilly_triplicity_compact_1647_v1": "renaissance_early_modern",
    "lilly_1647_p112_v1": "renaissance_early_modern",
    # Aspects: the degree set, the orbs and the partile rule.
    "ptolemaic_major_v1": "hellenistic",
    "modern_common_minor_v1": "modern",
    "modern_quintile_family_v1": "modern",
    "modern_minor_combined_v1": "modern",
    "abu_mashar_lineage_v1": "medieval_arabic",
    "lilly_1647_experience_v1": "renaissance_early_modern",
    "same_degree_number_v1": "renaissance_early_modern",
    "within_one_degree_v1": "modern",
    "lilly_1677_three_degrees_v1": "renaissance_early_modern",
}


def _require_closed_periods(periods: Iterable[str]) -> None:
    """Refuse a period outside METHOD_PERIODS; any part of the set, the whole set included, is fine."""
    if not set(periods) <= set(METHOD_PERIODS):
        raise RuntimeError("profile periods come from the closed set")


_require_closed_periods(PROFILE_PERIODS.values())


def profile_period(profile_id: str) -> str:
    return PROFILE_PERIODS[profile_id]


# 列為研究用途的 profile；被選為主要 profile 時也要標出。
RESEARCH_ONLY_PROFILES: frozenset[str] = frozenset({"lilly_triplicity_compact_1647_v1"})

if DECIDED_METHODS & (PROVISIONAL_METHODS | ANNUAL_PROVISIONAL_METHODS):
    raise RuntimeError("a method is either decided or provisional, never both")
if set(METHOD_PERIOD_LABELS) != DECIDED_METHODS | PROVISIONAL_METHODS | ANNUAL_PROVISIONAL_METHODS:
    raise RuntimeError("every method with a status has a period label, and only those")
if any(
    period not in METHOD_PERIODS or name not in NAME_STATUSES
    for period, name in METHOD_PERIOD_LABELS.values()
):
    raise RuntimeError("period labels come from the closed sets")


def method_status(module: str) -> str:
    if module in DECIDED_METHODS:
        return METHOD_STATUS_DECIDED
    if module in PROVISIONAL_METHODS | ANNUAL_PROVISIONAL_METHODS:
        return METHOD_STATUS_PROVISIONAL
    raise KeyError(f"method {module!r} has no status basis")


def method_receipt(module: str) -> dict[str, str]:
    """The receipt key for spreading into a method receipt."""

    period, name_status = METHOD_PERIOD_LABELS[module]
    return {"method_status": method_status(module), "period": period, "name_status": name_status}


def method_head(method: str, module: str, **extra) -> dict:
    """The keys a method receipt opens with: its name, status, then ``extra``."""

    return {"method": method, **method_receipt(module), **extra}


def research_only_profiles(profile_ids: Iterable[str]) -> list[str]:
    return sorted(set(profile_ids) & RESEARCH_ONLY_PROFILES)
