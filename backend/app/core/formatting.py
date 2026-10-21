"""數值格式化輔助：黃經的星座內度分秒顯示、方位角座標慣例轉換，
以及輸出前的角度正規化。

## 星座邊界的顯示

星座歸屬一律由**原始值**決定；顯示只是把同一個值寫短。捨入只能在整數度以內進行：
若捨入會讓顯示值碰到下一個整數度（例如 359.9999999° 捨入成 360°00′00.00″、
29.99999995° 捨入成 30°00′00.00″），改用截斷。這就是 Swiss Ephemeris `swe_split_deg`
的 `SE_SPLIT_DEG_KEEP_DEG`（「不要進位到下一度」）；它涵蓋 `SE_SPLIT_DEG_KEEP_SIGN`
（「不要進位到下一個星座」），因為每個星座、界段與旬的邊界都是整數度，所以顯示值
永遠不會跨出原始值所在的半開區間 [n°, n+1°)。十進位黃經用同一條規則，因此不會印出
`360.000000`。`sign_position` 是這個顯示的唯一產生器；前端照印，不自己捨入。
"""

import math
from collections.abc import Iterable, Iterator

# 顯示精度：度分秒到百分之一角秒；十進位黃經到 10⁻⁶ 度。
CENTI_ARCSEC_PER_DEGREE = 360_000
LONGITUDE_DECIMAL_PLACES = 6


def normalize_longitude(degrees: float) -> float:
    """化到 [0, 360)，且結果不會是 −0.0。

    Python 對極小的負數取 `% 360.0` 會進位成恰好 360.0（IEEE-754），那不在 [0, 360) 內；
    −0.0 在數值上等於 0，卻讓 canonical JSON 與 SHA-256 收據和等價的 +0.0 不同。
    """
    normalized = degrees % 360.0
    if normalized >= 360.0 or normalized == 0.0:
        return 0.0
    return normalized


def zodiac_sign_index(longitude: float) -> int:
    """星座索引的唯一產生器：normalize_longitude 之後的 [30k°, 30k+30°) 半開區間。

    星座、尊貴、相位與敏感度都經這一個函式；各自取模的寫法（floor 再 % 12、
    `int((x % 360.0) // 30)`）對負的極小值結果不同，可能讀成索引 12。

    落宮（house_placements）刻意用 Fraction 精確取模，對 [0°, 360°] 內每個
    float 與本函式的整宮結果相同（tests/backend/test_sign_boundary_display.py 的性質測試）。
    兩者只對負值不同，而本產品送進兩者的黃經都來自 Swiss、
    normalize_longitude 或 `% 360.0`，不會是負值。
    """

    return int(normalize_longitude(longitude) // 30.0)


def negate_without_negative_zero(value: float) -> float:
    """−value，但精確零回 +0.0 而不是 −0.0（理由同 normalize_longitude）。"""
    return 0.0 - value


def swiss_azimuth_to_standard(az_south_based: float) -> float:
    """swe.azalt() 回傳的方位角是「以南點為 0°、向西遞增」的天文傳統慣例
    （實測驗證：冬至真太陽正午時 swe.azalt 回傳 ~0°，而非慣用的 ~180°）。
    這裡轉換成一般地圖/羅盤慣用的「北點為 0°、順時針向東遞增」，避免使用者誤讀。"""
    return (az_south_based + 180.0) % 360.0


def quantize_keep_degree(value_degrees: float, ticks_per_degree: int) -> int:
    """把非負的度數量化成整數刻度，捨入不得碰到下一個整數度。

    一般情況用 Python `round()`，也就是捨入到偶數（round half to even），不是四捨五入。
    若捨入結果達到 `floor(value) + 1` 度，改回該整數度之前的最後一個刻度——等同
    Swiss Ephemeris `SE_SPLIT_DEG_KEEP_DEG` 在這種情況下放棄捨入、直接截斷。
    浮點乘法可能把極靠近整數度的值乘成恰好整數刻度，所以用夾住而不是 `floor`。
    """

    if value_degrees < 0:
        raise ValueError("quantize_keep_degree takes a non-negative value")
    whole = math.floor(value_degrees)
    ceiling = (whole + 1) * ticks_per_degree
    ticks = round(value_degrees * ticks_per_degree)
    if ticks >= ceiling:
        return ceiling - 1
    return max(ticks, whole * ticks_per_degree)


def _dms_from_centi_arcsec(total_centi_arcsec: int) -> str:
    total_arcsec, centi = divmod(total_centi_arcsec, 100)
    d, rem = divmod(total_arcsec, 3600)
    m, s = divmod(rem, 60)
    return f"{d}°{m:02d}′{s:02d}.{centi:02d}″"


def dms_text(value_degrees: float) -> str:
    """非負度數的度分秒，到百分之一角秒，捨入不跨整數度（與 sign_position 同一規則）。"""
    return _dms_from_centi_arcsec(
        quantize_keep_degree(value_degrees, CENTI_ARCSEC_PER_DEGREE)
    )


def degree_text(value_degrees: float, places: int) -> str:
    """非負度數的十進位字串，`places` 位小數，捨入不跨整數度（KEEP_DEG）。

    捨入用 Python 的格式化：對浮點數的精確二進位值正確捨入，與瀏覽器 `toFixed`
    相同（只有恰好落在中點時兩者可能不同）。若結果會進到下一個整數度，改寫該度
    之前的最後一個值，例如 359.9999999 → "359.999999"。
    """

    if value_degrees < 0:
        raise ValueError("degree_text takes a non-negative value")
    whole = math.floor(value_degrees)
    text = f"{value_degrees:.{places}f}"
    if float(text) >= whole + 1:
        return f"{whole}.{'9' * places}"
    return text


# 回應裡某些數量很多的度數（出生時間取樣的包絡、相位幾何、恆星座標）只帶到頁面印出的
# 精度：10⁻⁶ 度，約 0.004 角秒，比星曆與取樣本身的不確定小得多。
DEGREE_DECIMAL_PLACES = LONGITUDE_DECIMAL_PLACES


def longitude_number(longitude: float) -> float:
    """黃經化到 [0, 360) 後，取 sign_position 印出的那個十進位值（10⁻⁶ 度，捨入不跨整數度）。

    不跨整數度，所以星座、界與旬的歸屬與原值相同；由這個數讀出的星座就是原值的星座。
    """
    return float(degree_text(normalize_longitude(longitude), LONGITUDE_DECIMAL_PLACES))


def degrees_number(value: float) -> float:
    """非黃經的度數（角距、偏差、緯度、高度、每日度數）到 10⁻⁶。"""
    return round(value, DEGREE_DECIMAL_PLACES) + 0.0


# `sign_position` 用 [sign_index, dms_in_sign, longitude_decimal] 三元陣列而不是物件：
# 約 120 個黃經各帶一份，物件鍵名會多出約 6 KB，而回應預算只剩約 10 KB。
def sign_position(longitude: float | None) -> list | None:
    """一個黃經的顯示：[星座索引, 星座內度分秒, 十進位黃經]（規則見 module docstring）。

    例：359.9999999° 是 [11, "29°59′59.99″", "359.999999"]，
    29.99999995° 是 [0, "29°59′59.99″", "29.999999"]。
    """

    if longitude is None:
        return None
    normalized = normalize_longitude(longitude)
    index = zodiac_sign_index(normalized)
    in_sign = normalized - index * 30.0
    return [
        index,
        dms_text(in_sign),
        degree_text(normalized, LONGITUDE_DECIMAL_PLACES),
    ]


# Attach the one sign/DMS/decimal display to every longitude the result page prints.
# The frontend does not quantize (it would print 359.9999999° as Aries 0°00′00.00″
# beside a Pisces dignity row); `attach_sign_positions` alone decides which
# longitudes carry it, so a new longitude needs one row here and nothing in the frontend.
# Records gain `sign_position` (bare numbers a sibling map), `None` for a `None`
# longitude; raw values never change.
#
# `derived_methods.planet_in_house.placements` is not listed: each placement is a body of
# `astronomical_data.bodies` (the same list, `compute_planet_house_placements(bodies, ...)`)
# and the page reads that body's `sign_position` by key, which saves about 600 bytes of the
# response budget.

ANGLE_KEYS = ("asc", "mc", "desc", "ic")
LOT_KEYS = ("fortune", "spirit")

# (layer, dotted path to a list or a dict of records).
RECORD_COLLECTIONS = (
    ("astronomical_data", "bodies"),
    ("astronomical_data", "nodes"),
    ("astronomical_data", "fixed_stars"),
    ("astronomical_data", "lunar_apsides.points"),
    ("astronomical_data", "extra_angles.angles"),
    ("astronomical_data", "parallax_moon.geocentric_reference"),
    ("astronomical_data", "parallax_moon.topocentric_effective"),
    ("derived_geometry", "antiscia.antiscia"),
    ("derived_geometry", "antiscia.contra_antiscia"),
    ("derived_methods", "dodecatemoria.points"),
)


def _walk(root: object, dotted: str) -> object:
    node = root
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _records(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        if "longitude" in node:
            yield node
            return
        values: Iterable = node.values()
    elif isinstance(node, list):
        values = node
    else:
        return
    for value in values:
        if isinstance(value, dict) and "longitude" in value:
            yield value


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _sign_positions(record: dict, keys: tuple[str, ...]) -> dict:
    return {key: sign_position(_number(record.get(key))) for key in keys}


def attach_sign_positions(
    *,
    astronomical_data: dict,
    derived_geometry: dict,
    derived_methods: dict,
    birth_time_sensitivity: dict | None,
) -> None:
    layers = {
        "astronomical_data": astronomical_data,
        "derived_geometry": derived_geometry,
        "derived_methods": derived_methods,
    }
    for layer, dotted in RECORD_COLLECTIONS:
        for record in _records(_walk(layers[layer], dotted)):
            record["sign_position"] = sign_position(_number(record.get("longitude")))

    angles = astronomical_data.get("angles")
    if isinstance(angles, dict) and any(
        _number(angles.get(key)) is not None for key in ANGLE_KEYS
    ):
        angles["sign_positions"] = _sign_positions(angles, ANGLE_KEYS)

    houses = derived_methods.get("house_division")
    if isinstance(houses, dict) and isinstance(houses.get("cusps"), list):
        houses["cusp_sign_positions"] = [
            sign_position(_number(cusp)) for cusp in houses["cusps"]
        ]

    lots = derived_methods.get("lots")
    if isinstance(lots, dict) and any(
        _number(lots.get(key)) is not None for key in LOT_KEYS
    ):
        lots["sign_positions"] = _sign_positions(lots, LOT_KEYS)
        for entry in (lots.get("by_sect") or {}).values():
            if isinstance(entry, dict):
                entry["sign_positions"] = _sign_positions(entry, LOT_KEYS)

    # A twelfth-part row prints the point it was taken from beside the result;
    # each rule's own rows (profile_results) print the same two positions.
    for record in _records(_walk(derived_methods, "dodecatemoria.points")):
        record["point_sign_position"] = sign_position(_number(record.get("point_longitude")))
    rules = _walk(derived_methods, "dodecatemoria.profile_results")
    for rule in rules.values() if isinstance(rules, dict) else ():
        for record in _records(_walk(rule, "points")):
            record["sign_position"] = sign_position(_number(record.get("longitude")))
            record["point_sign_position"] = sign_position(_number(record.get("point_longitude")))

    for item in (birth_time_sensitivity or {}).get("position_ranges") or []:
        if isinstance(item, dict) and "representative_longitude" in item:
            item["representative_sign_position"] = sign_position(
                _number(item.get("representative_longitude"))
            )
