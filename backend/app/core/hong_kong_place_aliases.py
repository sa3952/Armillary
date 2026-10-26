"""Curated Chinese (and a few English) names for Hong Kong places, read at query time.

The bundled catalogue takes its Chinese names from GeoNames, which gives most
Hong Kong rows none: 灣仔、大埔、北角 found only Taiwanese villages, and 將軍澳、
油尖旺、葵青、離島、大嶼山 found nothing.  This table maps such a name to one
catalogue row (a GeoNames ``cities500`` record id), so the catalogue file is
unchanged and the row a chart then uses is the catalogue's own.

The catalogue has no district-level rows, so a district name (油尖旺、北區) maps
to a representative place inside the district, and a place the catalogue lacks
(北角、大嶼山) to its nearest or main catalogued place: 北角 to Fortress Hill
(炮台山, inside North Point), 大嶼山 and 離島 to Tung Chung, 南丫島 to Yung Shue
Wan.  The result keeps the row's own label, so the reader sees which place the
coordinates belong to.

Placement (``place_catalog``): a query that names Hong Kong (香港 before the
name) puts the row first; otherwise it goes second when the catalogue's own
first answer is a place elsewhere matched by its own name (灣仔、大埔、北角 are
also Taiwanese village names) or the name is a district name Taiwanese cities
share (北區、南區、東區、中西區), and first otherwise.
"""

from __future__ import annotations

from typing import Final

ALIAS_TABLE_NAME: Final = "hong_kong_place_aliases_v1"
ALIAS_TIER: Final = "curated_alias"
ALIAS_SOURCE: Final = "geonames_cities500"

# Prefixes that make a query clearly about Hong Kong; stripped before lookup.
HONG_KONG_PREFIXES: Final = ("香港特別行政區", "香港特區", "香港", "hong kong", "hong-kong", "hongkong", "hk")
_SPECIAL_REGION: Final = frozenset({"香港特別行政區", "香港特區"})

# The 18 districts (區議會分區), each with its main or largest catalogued place.
_DISTRICTS: Final = {
    "中西": "8223932",     # Central
    "灣仔": "1818379",     # Wan Chai
    "東": "10170102",      # Tai Koo (東區; looked up only as 東區)
    "南": "1819757",       # Aberdeen (南區)
    "油尖旺": "1819353",   # Mong Kok
    "深水埗": "1818953",   # Sham Shui Po
    "九龍城": "1819607",   # Kowloon City
    "黃大仙": "1818304",   # Wong Tai Sin
    "觀塘": "1819577",     # Kwun Tong
    "葵青": "1819595",     # Kwai Chung
    "荃灣": "1818209",     # Tsuen Wan
    "屯門": "1818446",     # Tuen Mun
    "元朗": "1818225",     # Yuen Long
    "北": "1819873",       # Fanling (北區)
    "大埔": "1818673",     # Tai Po
    "沙田": "1818920",     # Sha Tin
    "西貢": "1819050",     # Sai Kung
    "離島": "11101593",    # Tung Chung
}

_PLACES: Final = {
    "北角": "7778986",     # Fortress Hill, inside North Point
    "炮台山": "7778986",
    "將軍澳": "1818506",
    "坑口": "1819791",
    "調景嶺": "1818550",
    "長洲": "1819968",
    "大嶼山": "11101593",  # Tung Chung
    "東涌": "11101593",
    "大澳": "1818684",
    "梅窩": "1819333",
    "坪洲": "1819112",
    "愉景灣": "1819894",
    "南丫島": "1818211",   # Yung Shue Wan
    "榕樹灣": "1818211",
    "索罟灣": "1818775",
    "馬灣": "1819374",
    "尖沙咀": "1818501",
    "中環": "8223932",
    "金鐘": "8223931",
    "旺角": "1819353",
    "油麻地": "1818268",
    "佐敦": "8224045",
    "大角咀": "1818721",
    "何文田": "1819731",
    "九龍塘": "1819602",
    "長沙灣": "1819952",
    "藍田": "1819554",
    "秀茂坪": "1818972",
    "樂富": "12719429",
    "竹園": "1819923",
    "葵涌": "1819595",
    "天水圍": "1818558",
    "錦田": "1819685",
    "粉嶺": "1819873",
    "上水": "1818845",
    "馬鞍山": "1819400",
    "大圍": "1818628",
    "火炭": "1819855",
    "深井": "1818950",
    "太古": "10170102",
    "西灣河": "1819029",
    "筲箕灣": "1818911",
    "天后": "12719546",
    "大坑": "1818734",
    "香港仔": "1819757",
    "薄扶林": "1819091",
    "黃竹坑": "9172583",
    "西營盤": "1819026",
    "堅尼地城": "1819638",
}

# MTR stations whose name the catalogue gives no Hong Kong row for, each with
# the catalogued place it lies in or beside (stations named after a catalogued
# place, 旺角 or 尖沙咀, are found by that row or by the tables above).  Stations
# whose nearest catalogued place is uncertain are left out: 欣澳、博覽館、機場、
# 迪士尼、大學、馬場.
_MTR_STATIONS: Final = {
    "香港大學": "1819031",   # Sai Wan
    "上環": "8223932",       # Central
    "杏花邨": "12719592",    # Heng Fa Chuen
    "柴灣": "12719606",      # Chai Wan Estate
    "葵興": "1819595",       # Kwai Chung
    "葵芳": "1819595",
    "荔景": "1819595",
    "荔枝角": "1819952",     # Cheung Sha Wan
    "太子": "1819353",       # Mong Kok (the Prince Edward row lies east, in Kowloon City)
    "黃埔": "12689057",      # Whampoa
    "鑽石山": "1818304",     # Wong Tai Sin (黃大仙區)
    "彩虹": "1819932",       # Choi Hung
    "牛頭角": "1819577",     # Kwun Tong
    "寶琳": "1818506",       # Tseung Kwan O
    "康城": "12719433",      # LOHAS Park
    "日出康城": "12719433",
    "奧運": "12689056",      # Olympic
    "南昌": "12689055",      # Nam Cheong
    "會展": "1818379",       # Wan Chai
    "旺角東": "1819353",     # Mong Kok
    "太和": "1818616",       # Tai Wo
    "羅湖": "1818845",       # Sheung Shui
    "落馬洲": "1818996",     # San Tin, Yuen Long
    "烏溪沙": "12719443",    # Wu Kai Sha
    "恒安": "1819400",       # Ma On Shan
    "大水坑": "1818654",     # Tai Shui Hang
    "石門": "1818920",       # Sha Tin
    "沙田圍": "1818916",     # Sha Tin Wai
    "車公廟": "1818628",     # Tai Wai
    "顯徑": "1818628",
    "尖東": "1818501",       # Tsim Sha Tsui
    "柯士甸": "8224045",     # Jordan
    "荃灣西": "1818209",     # Tsuen Wan
    "錦上路": "1819685",     # Kam Tin
    "朗屏": "1818225",       # Yuen Long
    "兆康": "1818446",       # Tuen Mun
    "海洋公園": "9172583",   # Wong Chuk Hang
    "海怡半島": "12719432",  # South Horizons
    "淺水灣": "1818818",     # Shouson Hill, the nearest catalogued place
}

# English names GeoNames lacks a row for.
_ENGLISH: Final = {
    "north point": "7778986",
    "lantau": "11101593",
    "lantau island": "11101593",
    "lamma island": "1818211",
    "hku": "1819031",
    "sheung wan": "8223932",
    "kwai hing": "1819595",
    "kwai fong": "1819595",
    "lai king": "1819595",
    "lai chi kok": "1819952",
    "diamond hill": "1818304",
    "ngau tau kok": "1819577",
    "po lam": "1818506",
    "exhibition centre": "1818379",
    "mong kok east": "1819353",
    "lo wu": "1818845",
    "lok ma chau": "1818996",
    "heng on": "1819400",
    "shek mun": "1818920",
    "che kung temple": "1818628",
    "hin keng": "1818628",
    "east tsim sha tsui": "1818501",
    "austin": "8224045",
    "tsuen wan west": "1818209",
    "kam sheung road": "1819685",
    "long ping": "1818225",
    "siu hong": "1818446",
    "ocean park": "9172583",
    "repulse bay": "1818818",
}


def _build() -> dict[str, str]:
    table: dict[str, str] = {}
    for name, record in _DISTRICTS.items():
        table[f"{name}區"] = record
        # 東、南、北 alone are not place names; the others are also used bare.
        if len(name) > 1:
            table[name] = record
    table.update(_PLACES)
    table.update(_MTR_STATIONS)
    table.update(_ENGLISH)
    # The rest of the place search reads 台 as 臺 (place_catalog.place_tier_key);
    # an alias must too, or 炮臺山 misses 炮台山.
    for name, record in list(table.items()):
        for a, b in (("台", "臺"), ("臺", "台")):
            table.setdefault(name.replace(a, b), record)
    return table


HONG_KONG_ALIASES: Final = _build()

# District names that are also district names in Taiwanese cities (臺南市北區、
# 中西區…); without 香港 they leave the catalogue's first answer first.
ALIASES_SHARED_WITH_TAIWAN: Final = frozenset({"北區", "南區", "東區", "中西區"})


def alias_key(query: str) -> tuple[str, bool]:
    """The lookup key of a normalized query, and whether it named Hong Kong first.

    ``query`` is already NFKC-casefolded with single spaces.  Spaces are
    dropped for Chinese names (香港 灣仔) and kept between English words.
    """

    text = query.strip()
    if _compact(text) in HONG_KONG_ALIASES:
        return _compact(text), False  # 香港仔 is a name, not 香港 + 仔
    if _compact(text) in _SPECIAL_REGION:
        return "香港", True  # 香港特區 alone: search 香港
    for prefix in HONG_KONG_PREFIXES:
        if not text.startswith(prefix) or len(text) <= len(prefix):
            continue
        # hka, hkust, hongkongese: a Latin prefix ends at a word boundary.
        if prefix.isascii() and text[len(prefix)].isascii() and text[len(prefix)].isalnum():
            continue
        rest = _compact(text[len(prefix):].lstrip(" ,，、"))
        # 香港x, hk 1: one character is no place name to search for.  The
        # longest prefix that matched decides: 香港特區x is not 香港 + 特區x.
        if len(rest) >= 2:
            return rest, True
        break
    return _compact(text), False


def _compact(text: str) -> str:
    if text.isascii():
        return " ".join(text.split())
    return "".join(text.split())
