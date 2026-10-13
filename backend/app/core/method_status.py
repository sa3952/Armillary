"""方法狀態的唯一產生器。

每個模組讀這裡，不各自寫一個 `METHOD_STATUS` 常數：各自的常數在方法採用之後沒有人
回頭改，已採用的方法會繼續自稱「待審閱」。

`method_status` 是兩值閉集：

- `decided`：產品已採用這個方法的輸出方式。採用是產品決定，不是歷史或天文上的驗證。
- `provisional_pending_method_audit`：還沒有採用這個方法，或明文維持 provisional；
  Dossier 對算出的結果發出 `provisional_method_result`。

方法狀態只是內部收據欄位：一般畫面不顯示。
"""

from __future__ import annotations

from collections.abc import Iterable

METHOD_STATUS_DECIDED = "decided"
METHOD_STATUS_PROVISIONAL = "provisional_pending_method_audit"

# 已採用的方法。
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
})

# 維持 provisional 的方法：Lots 隨可用的上升點保留 provisional；月空亡的定義仍未定，
# 已定的只有求解法；相位預設開啟不等於採用該方法；行星時隨基本輸出計算，但核准加入
# 輸出不等於採用其定義（日主取日出所在民用日期等）。
PROVISIONAL_METHODS: frozenset[str] = frozenset({
    "lots", "void_of_course", "aspects", "planetary_hours",
})

# The flagged annual route's methods: provisional until their "how it is
# output" rows are decided.  Kept apart so the chart's own partition
# test can name the methods /api/chart emits.
ANNUAL_PROVISIONAL_METHODS: frozenset[str] = frozenset({
    "annual_profection", "firdaria", "zodiacal_releasing", "extended_lots", "decennials",
    "monthly_profection",
})

# 列為研究用途的 profile；被選為主要 profile 時也要標出。
RESEARCH_ONLY_PROFILES: frozenset[str] = frozenset({"lilly_triplicity_compact_1647_v1"})

if DECIDED_METHODS & (PROVISIONAL_METHODS | ANNUAL_PROVISIONAL_METHODS):
    raise RuntimeError("a method is either decided or provisional, never both")


def method_status(module: str) -> str:
    if module in DECIDED_METHODS:
        return METHOD_STATUS_DECIDED
    if module in PROVISIONAL_METHODS | ANNUAL_PROVISIONAL_METHODS:
        return METHOD_STATUS_PROVISIONAL
    raise KeyError(f"method {module!r} has no status basis")


def method_receipt(module: str) -> dict[str, str]:
    """The receipt key for spreading into a method receipt."""

    return {"method_status": method_status(module)}


def research_only_profiles(profile_ids: Iterable[str]) -> list[str]:
    return sorted(set(profile_ids) & RESEARCH_ONLY_PROFILES)
