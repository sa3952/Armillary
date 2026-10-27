"""反照點 (Antiscia) 與反向反照點 (Contra-antiscia)。

鏡射軸（夏至/冬至軸、牡羊/天秤軸）是回歸黃道(tropical)上固定的天文軸，與 sidereal 的
0°無關。若輸入黃經是 sidereal 座標，需先加回 ayanamsa 換算成 tropical 做鏡射，再減回
ayanamsa 換算回 sidereal，淨效果等同在公式中多減一次 2×ayanamsa（tropical 模式 ayanamsa=0，
公式退化回未套用歲差的版本）。

Antiscia：以巨蟹/摩羯 0 度軸 (夏至/冬至軸) 為鏡射軸 -> (180 - 黃經 - 2×ayanamsa) mod 360
Contra-antiscia：以牡羊/天秤 0 度軸為鏡射軸 -> (360 - 黃經 - 2×ayanamsa) mod 360
"""

from .formatting import normalize_longitude
from .module_state import (
    Applicability,
    PRODUCT_FORMULA_SOURCE,
    computed_receipt,
    frame_table_refusal,
)
from .trace import Trace


def compute_antiscia(bodies: list, trace: Trace, ayanamsa: float = 0.0) -> dict:
    trace.add(
        "反照點計算方法",
        formula="Antiscia = (180° − 黃經 − 2×ayanamsa) mod 360°；Contra-antiscia = (360° − 黃經 − 2×ayanamsa) mod 360°",
        note="鏡射軸固定於回歸黃道，sidereal 模式下需扣除 2×ayanamsa 才能對齊真實至點/分點軸" if ayanamsa else "",
    )

    antiscia = []
    contra_antiscia = []
    for body in bodies:
        lon = body["longitude"]
        if lon is None:
            trace.add(f"{body['name']} 反照點", note="⚠ 黃經為 null（degenerate），略過。")
            antiscia.append({"key": body["key"], "name": body["name"], "longitude": None})
            contra_antiscia.append({"key": body["key"], "name": body["name"], "longitude": None})
            continue
        anti = normalize_longitude(180.0 - lon - 2 * ayanamsa)
        contra = normalize_longitude(360.0 - lon - 2 * ayanamsa)

        trace.add(
            f"{body['name']} 反照點",
            inputs={"黃經": lon},
            result={"Antiscia": anti, "Contra-antiscia": contra},
        )

        antiscia.append({"key": body["key"], "name": body["name"], "longitude": anti})
        contra_antiscia.append({"key": body["key"], "name": body["name"], "longitude": contra})

    return {
        **computed_receipt(PRODUCT_FORMULA_SOURCE),
        "antiscia": antiscia,
        "contra_antiscia": contra_antiscia,
    }


def antiscia_not_applicable(state: Applicability, trace: Trace) -> dict:
    """Refuse instead of mirroring in another frame.

    The mirror axis is the solstitial axis of date (method research notes, not
    independently verified).  J2000 and mean (nutation-off) longitudes are not
    measured from it, so the central frame table refuses; nothing is converted.
    Sidereal longitudes are the same with nutation on or off, but the
    ``2 x ayanamsa`` that places the axis is then the mean-equinox value, so
    the sidereal nutation-off cell stays refused as well.
    """

    refusal = frame_table_refusal(
        state, trace, "反照點計算方法",
        note=(
            "鏡射軸是當日真春分點的至點軸；J2000 或不含章動時，黃經（恆星黃道則是"
            "換算用的 ayanamsa）改以另一個春分點為準，參考框架相容表判定不適用："
            "不鏡射，也不轉換座標。"
        ),
    )
    return {**refusal, "antiscia": [], "contra_antiscia": []}
