#!/usr/bin/env python3
"""Build the immutable GeoNames + Taiwan MOI place-search SQLite catalog.

Schema 5 (2026-10-10) adds ``match_keys``: every name the runtime match tier
compares, folded the way the runtime folds the query (台 read as 臺).  A row's
keys are its name and Traditional-Chinese name; a Taiwan county's derived point
adds its short name and English names derived from the inputs; a Taiwan
GeoNames row adds the Chinese-script names of its alternate-name list, because
GeoNames tags almost none of them zh-Hant and the city would otherwise rank
below every hamlet whose name merely starts with the query.

Schema 4 (2026-09-14) added four identity columns so that a person can tell
two search results apart without reading raw coordinates:

* ``admin1_name`` — the GeoNames admin1 code resolved through
  ``admin1CodesASCII.txt`` when that table is supplied; otherwise null and the
  code is omitted from ``display_name`` instead of being shown raw.
* ``name_zh`` — a Traditional-Chinese name from ``alternateNamesV2.txt`` when
  supplied: ``zh-Hant`` preferred, then ``zh-TW``.  Untagged ``zh`` is not
  used; GeoNames mostly fills it with Simplified forms.
* ``admin3`` — the MOI village field, which is what separates the many
  same-named settlement points inside one town.  GeoNames rows leave it null:
  their admin3 is a bare code with no name table among the declared sources.
* ``disambiguator`` — filled only for rows whose ``display_name`` collides
  with another row; the producer picks the first human-meaningful level that
  separates the group and records which level it used.

The producer rejects rows whose name is blank or contains no word character,
validates every timezone against the IANA database, applies closed tables of
named source corrections (timezone and admin1 code), and hashes each input through the same descriptor
it streams from, so the manifest describes the bytes that were consumed.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
from typing import BinaryIO, TypedDict
import unicodedata
import zipfile
import zoneinfo

_BACKEND_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_PACKAGE_ROOT))
from app.core.place_catalog import (
    MATCH_KEY_SEPARATOR,
    TAIWAN_COUNTY_RECORD_PREFIX,
    match_keys_text,
    normalize_search_text,
    place_name_match_key,
)
from scripts.tools.source_tree_identity import sha256_file


GEONAMES_SOURCE_URL = "https://download.geonames.org/export/dump/cities500.zip"
GEONAMES_ADMIN1_SOURCE_URL = "https://download.geonames.org/export/dump/admin1CodesASCII.txt"
GEONAMES_ADMIN2_SOURCE_URL = "https://download.geonames.org/export/dump/admin2Codes.txt"
GEONAMES_ALTERNATE_NAMES_SOURCE_URL = "https://download.geonames.org/export/dump/alternateNamesV2.zip"
TAIWAN_ADMIN_SOURCE_URL = (
    "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/"
    "C8DB1578-7554-4DBA-82AD-AD0105992C68/resource/"
    "83911F2D-F552-4E6B-99D0-6267FC9CD0E5/download"
)
TAIWAN_SETTLEMENT_SOURCE_URL = (
    "https://opdadm.moi.gov.tw/api/v1/no-auth/resource/api/dataset/"
    "4A5AB0C9-0395-4B04-AE50-02624075516F/resource/"
    "AE5B85B6-0895-4D32-8027-1713F018A649/download"
)
GENERATOR_VERSION = "place-catalog-builder-v8"
SCHEMA_VERSION = 5
MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_LINE_CHARS = 1_000_000
MAX_SOURCE_ROWS = 10_000_000
MAX_OUTPUT_BYTES = 4 * 1024 * 1024 * 1024

# Closed set of row-rejection reasons.  A rejected row is counted in the
# manifest under its source and reason; it is never silently dropped.
REJECT_EMPTY_NAME = "empty_name"
REJECT_NONWORD_NAME = "nonword_name"
REJECT_MISSING_COORDINATES = "missing_coordinates"
# A record the publisher left in the file while testing its system: the MOI
# settlement file ships 「cindy崙」 with AnotherName and PlaceMean 「cindytest」
# at a point in the sea.  The marker is the ASCII word "test" in a free-text
# field; the source's own text is Chinese or an Indigenous-language name, and
# no other record in the 2026-10-09 files carries it.
REJECT_UPSTREAM_TEST_ROW = "upstream_test_row"
_UPSTREAM_TEST_FIELDS = ("PlaceName", "AnotherName", "PlaceMean")

# The MOI settlement file writes a character its encoding lacked as "?" or
# "●"; GeoNames has a few such names too.  The name is kept as the source has
# it (the record is real and its other characters are searchable) and its label
# carries this mark, so a user does not take the question mark for the name.
MISSING_GLYPHS = ("?", "●")
MISSING_GLYPH_MARK = "（原始資料缺字）"


def _missing_glyph(*names: str | None) -> bool:
    return any(glyph in (name or "") for name in names for glyph in MISSING_GLYPHS)


# Closed set of source-correction outcomes.
CORRECTION_APPLIED = "applied"
CORRECTION_ALREADY_UPSTREAM = "already_upstream"
CORRECTION_STALE_NOT_APPLIED = "stale_not_applied"
CORRECTION_ROW_ABSENT = "row_absent"

# Named corrections to individual source rows.  Each entry states the value
# the source is expected to carry; the correction is applied only when that
# expectation holds, so a silently changed upstream row is reported rather
# than overwritten.  Two Auckland suburbs carry Pacific/Chatham
# (UTC+12:45 / +13:45) although they sit at 174.74°E, -36.7°, inside
# Pacific/Auckland; the 45-minute offset moves every house cusp.  The other
# rows were found by checking each zone against the country's zone.tab entries
# and against the zone most of the row's nearest same-country neighbours carry;
# rows on a real or disputed boundary are left as GeoNames has them.
SOURCE_TIMEZONE_CORRECTIONS: dict[str, dict[str, str]] = {
    "13631316": {
        "expected": "Pacific/Chatham",
        "corrected": "Pacific/Auckland",
        "reason": (
            "Windsor Park, Auckland (-36.73966, 174.7423) lies on the North "
            "Island; Pacific/Chatham is the Chatham Islands zone"
        ),
    },
    "13631317": {
        "expected": "Pacific/Chatham",
        "corrected": "Pacific/Auckland",
        "reason": (
            "Wairau Valley, Auckland (-36.77235, 174.74107) lies on the North "
            "Island; Pacific/Chatham is the Chatham Islands zone"
        ),
    },
    "13535832": {
        "expected": "Asia/Pontianak",
        "corrected": "Asia/Brunei",
        "reason": (
            "Kampong Ayer, Brunei-Muara (4.88265, 114.94487) is in Brunei; "
            "Asia/Pontianak is West Kalimantan, Indonesia (UTC+7 against UTC+8)"
        ),
    },
    "8558983": {
        "expected": "Asia/Yakutsk",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Kunheda Woerzu Manzu, Heilongjiang (49.88477, 127.5032) is in China; "
            "Asia/Yakutsk is a Russian zone (UTC+9/+10 in 2000 against UTC+8)"
        ),
    },
    "8594765": {
        "expected": "Asia/Yakutsk",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Shangmachang, Heilongjiang (50.37191, 127.32717) is in China; "
            "Asia/Yakutsk is a Russian zone (UTC+9/+10 in 2000 against UTC+8)"
        ),
    },
    "1790891": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Wuyang, Guangdong (21.34766, 110.68829): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "1915237": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Tangwei, Guangdong (21.39545, 110.72832): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "6844287": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Haibin, Guangdong (21.39876, 110.78328): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "8558517": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Meilu, Guangdong (21.43412, 110.77555): Asia/Urumqi is Xinjiang "
            "time (UTC+6); every neighbour in Zhanjiang carries Asia/Shanghai"
        ),
    },
    "13405902": {
        "expected": "Asia/Ho_Chi_Minh",
        "corrected": "Asia/Pontianak",
        "reason": (
            "Kota Sambas, West Kalimantan (1.36259, 109.30093) is in Indonesia; "
            "Asia/Ho_Chi_Minh is Vietnam, whose history differs (UTC+8 until 1988 in Pontianak)"
        ),
    },
    "9887822": {
        "expected": "Asia/Hebron",
        "corrected": "Asia/Jerusalem",
        "reason": (
            "Merav, Northern District (32.45285, 35.42152) is an Israeli kibbutz on "
            "Mount Gilboa; Asia/Hebron follows Palestinian DST dates"
        ),
    },
    "97473": {
        "expected": "Asia/Baghdad",
        "corrected": "Europe/Istanbul",
        "reason": (
            "Cey, Hakkari (37.2621, 44.04086) is in Turkey; Asia/Baghdad is Iraq "
            "(UTC+3/+4 in 2000 against UTC+2/+3)"
        ),
    },
    "1216189": {
        "expected": "Asia/Bishkek",
        "corrected": "Asia/Tashkent",
        "reason": (
            "Shohimardon, Fergana (39.98322, 71.80512) is an Uzbek exclave; "
            "Asia/Bishkek is Kyrgyz time (summer UTC+6 in 2000 against UTC+5)"
        ),
    },
    "4653999": {
        "expected": "America/Chicago",
        "corrected": "America/New_York",
        "reason": (
            "Rockwood, Roane County, Tennessee (35.86563, -84.68494): Roane County "
            "keeps Eastern time; Central time starts in the counties to its west"
        ),
    },
    "4263848": {
        "expected": "America/Chicago",
        "corrected": "America/Indiana/Indianapolis",
        "reason": (
            "Rockport, Parke County, Indiana (39.88087, -87.2789): GeoNames codes it Parke County and "
            "links it to that community; Parke County keeps Eastern time, America/Chicago is the zone "
            "of the Spencer County Rockport at 37.88 N"
        ),
    },
    "3471834": {
        "expected": "America/Sao_Paulo",
        "corrected": "America/Cuiaba",
        "reason": (
            "Araguaiana, Mato Grosso (-15.73389, -51.83139): Mato Grosso keeps "
            "America/Cuiaba time, one hour behind Goias across the Araguaia"
        ),
    },
    "3991533": {
        "expected": "America/Mazatlan",
        "corrected": "America/Mexico_City",
        "reason": (
            "Puente de Camotlan, Jalisco (21.6987, -104.07996): Jalisco keeps "
            "central time; America/Mazatlan is the neighbouring Nayarit zone"
        ),
    },
    "8550587": {
        "expected": "Asia/Urumqi",
        "corrected": "Asia/Shanghai",
        "reason": (
            "Duobagou 多坝沟 (39.75181, 93.48198) is in Akqi Township, Aksay Kazakh Autonomous "
            "County, Gansu (Wikidata Q13924614 多坝沟村, in Q13924602 阿克旗乡 at 39.288 N 93.007 E, "
            "west of this row); Gansu keeps Beijing time, and every catalogue row within 120 km, "
            "Aksay's seat Hongliuwan 8550586 included, carries Asia/Shanghai; Asia/Urumqi is Xinjiang time"
        ),
    },
}

# Vietnam was divided from 1954 to 1976 at a line that ran down the Bến Hải river
# (source 16.919 N, mouth 17.015 N; Wikidata Q1931412) and, west of Bo Ho Su, due
# west to the Laos border.  South Vietnam kept UTC+8 from 1959-12-31 23:00 to
# 1975-06-13 while the North kept UTC+7; tzdata's zone1970.tab gives south
# Vietnam Asia/Ho_Chi_Minh and north Vietnam Asia/Bangkok.  GeoNames gives these
# rows the other side's zone, which moves a birth of those years by an hour.
# Each row lies outside 16.88-17.10 N, the band the line runs in, except Gio
# Linh, which is placed by its district.  Each entry is (row id, name and
# coordinates as GeoNames gives them).
_VIETNAM_SIDE_ZONES = {"north": "Asia/Bangkok", "south": "Asia/Ho_Chi_Minh"}
_VIETNAM_SIDE_REASONS = {
    "south": (
        "south of the 1954-1976 Bến Hải demarcation line (Wikidata Q1931412), where South Vietnam "
        "kept UTC+8 from 1959-12-31 to 1975-06-13; tzdata zone1970.tab gives south Vietnam "
        "Asia/Ho_Chi_Minh, and Asia/Bangkok stays at UTC+7"
    ),
    "north": (
        "north of the 1954-1976 Bến Hải demarcation line (Wikidata Q1931412), where North Vietnam "
        "kept UTC+7; tzdata zone1970.tab gives north Vietnam Asia/Bangkok, and Asia/Ho_Chi_Minh "
        "carries South Vietnam's UTC+8 of 1959-12-31 to 1975-06-13"
    ),
}
_VIETNAM_ROWS_BY_SIDE: dict[str, tuple[tuple[str, str], ...]] = {
    "south": (
        ("8656223", "A Roàng Hai (16.11247, 107.39699)"),
        ("8656112", "Khe Tre (16.1691, 107.71793)"),
        ("8656219", "Hương Nguyên (16.23873, 107.44103)"),
        ("1594548", "A Lưới (16.27228, 107.23385)"),
        ("1569850", "Phú Vang (16.43911, 107.71438)"),
        ("1580240", "Huế (16.4619, 107.59546)"),
        ("1580092", "Hương Trà (16.52539, 107.4755)"),
        ("8656203", "Sịa (16.57452, 107.51066)"),
        ("1570863", "Phong Điền (16.58321, 107.36438)"),
        ("1579363", "Khe Sanh (16.62825, 106.73884)"),
        ("8650753", "Krông Klang (16.68906, 106.8874)"),
        ("1581317", "Hải Lăng (16.69347, 107.25124)"),
        ("1565760", "Ái Tử (16.76886, 107.16504)"),
        ("1586384", "Cam Lộ (16.80797, 106.99405)"),
        ("1582926", "Ðông Hà (16.81625, 107.10031)"),
        (
            "1581673",
            "Gio Linh (16.9248, 107.08438), Gio Linh commune of Gio Linh District (Wikidata Q10761602), "
            "across the Hiền Lương bridge (Q1537236, 17.004 N) from Vĩnh Linh",
        ),
    ),
    "north": (
        ("1570668", "Phúc Trạch (18.13333, 105.76667)"),
        ("10275425", "Hòa Hợp (18.3114, 105.9099)"),
        ("13526847", "Đồng Lộc (18.37606, 105.71747)"),
        ("1563559", "Trường Sơn (18.38333, 105.73333)"),
        ("1587254", "Bùi Xá (18.38983, 105.82503)"),
        ("1560038", "Khánh Vĩnh Yên (18.46312, 105.7131)"),
        ("13512656", "Kim Song Trường (18.46343, 105.68731)"),
        ("13589184", "Yên Lộc (18.46476, 105.70884)"),
        ("1584601", "Cửa Lô (18.81667, 105.71667)"),
        ("1560065", "Yên Thượng (18.88333, 105.28333)"),
        ("1578904", "Kim Liên (18.88333, 105.31667)"),
        ("8628059", "Thái Hòa (18.92031, 104.97441)"),
        ("1570686", "Phúc Sơn (18.96667, 105.05)"),
        ("1560578", "Xuân Lạc (19.0, 105.28333)"),
        ("1572588", "Nghĩa Đàn (19.3, 105.43333)"),
        ("8628018", "Bản Na Hỷ (19.56361, 104.53459)"),
        ("1568142", "Sầm Sơn (19.73333, 105.9)"),
        ("1577859", "Thị Trấn Lam Sơn (19.9047, 105.40562)"),
        ("1587919", "Bỉm Sơn (20.07806, 105.86028)"),
        ("8554466", "Hanoi (20.32773, 106.01208)"),
        ("1582367", "Đố Sơn (20.71361, 106.78944)"),
        ("1586052", "Cát Bà (20.72779, 107.04819)"),
        ("1560551", "Xuân Mai (20.9, 105.58333)"),
        ("13494192", "Ecopark (20.9621, 105.9318)"),
        ("13494195", "Vinhomes Royal City (21.0028, 105.8151)"),
        ("13494193", "Vinhomes Smart City (21.0045, 105.7404)"),
        ("1586357", "Cẩm Phả Mines (21.01667, 107.3)"),
        ("12808881", "Ô Chợ Dừa (21.02146, 105.82464)"),
        ("12808882", "Láng Thượng (21.02374, 105.8036)"),
        ("1563241", "Thành Phố Uông Bí (21.03433, 106.77049)"),
        ("8200721", "Xuân Trùng (21.05751, 105.28383)"),
        ("1574873", "Thị Trấn Mạo Khê (21.05858, 106.59255)"),
        ("13405933", "Bắc Từ Liêm (21.06532, 105.74661)"),
        ("1585489", "Chí Linh (21.06667, 106.31667)"),
        ("8232480", "Pú Hồng (21.0696, 103.23711)"),
        ("1570263", "Phù Ninh (21.08333, 105.95)"),
        ("1584955", "Cổ Lóa (21.11667, 105.86667)"),
        ("1560830", "Trại Khoai (21.13174, 105.34479)"),
        ("8340760", "Cung Kiệm (21.18697, 106.16076)"),
        ("12382295", "Quang Minh (21.18884, 105.77269)"),
        ("8201690", "Phong Châu (21.23931, 105.43247)"),
        ("1562818", "Việt Yên (21.26667, 106.13333)"),
        ("1591468", "Bắc Lũng (21.26667, 106.38333)"),
        ("1564589", "Thị Trấn Tiên Yên (21.33133, 107.40533)"),
        ("1579752", "Kép (21.4, 106.26667)"),
        ("1590900", "Thị Trấn Thuận Châu (21.43849, 103.69)"),
        ("1572221", "Nhã Nam (21.45, 106.1)"),
        ("13513036", "Phổng Lăng (21.46463, 103.67036)"),
        ("1564065", "Thị Trấn Trạm Tấu (21.46659, 104.37966)"),
        ("1570043", "Phương Linh (21.46709, 105.09871)"),
        ("13513037", "Thành phố Sông Công (21.4772, 105.84137)"),
        ("1589412", "Nà Tấu (21.50635, 103.1178)"),
        ("1563509", "Tuần Giáo (21.58333, 103.41667)"),
        ("1572565", "Nghĩa Lộ (21.6, 104.51667)"),
        ("1584242", "Thị Trấn Đại Từ (21.63384, 105.63766)"),
        ("1575247", "Lương Bằng (21.64841, 105.02855)"),
        ("1573844", "Thị Trấn Na Dương (21.7025, 106.95552)"),
        ("1560344", "Thị Trấn Yên Bình (21.72585, 104.96346)"),
        ("8425634", "Mường Chà (21.76172, 103.09783)"),
        ("13513035", "Si Pa Phìn (21.80147, 102.96263)"),
        ("1571833", "Nong Hạ (21.95, 105.8)"),
        ("1582998", "Thị Trấn Đồng Đăng (21.9511, 106.69767)"),
        ("1586153", "Cao Ký (21.98333, 105.85)"),
        ("1574257", "Mường Lay (22.0, 103.13333)"),
        ("13494381", "Lay Nưa (22.01758, 103.11625)"),
        ("13526660", "Na Lay (22.03509, 103.15347)"),
        ("1572898", "Thị Trấn Na Sầm (22.05639, 106.6151)"),
        ("1579615", "Thị Trấn Khánh Yên (22.08935, 104.25149)"),
        ("1573111", "Nằm Vi (22.21667, 102.51667)"),
        ("1588242", "Thị Trấn Phố Ràng (22.23429, 104.47643)"),
        ("1565969", "Thị Trấn Thất Khê (22.25525, 106.47359)"),
        ("1576275", "Lao Chải (22.31377, 103.86844)"),
        ("1570880", "Thị Trấn Phố Lu (22.31918, 104.18719)"),
        ("1581341", "Hạ Hiệu (22.43333, 105.85)"),
        ("1585312", "Chợ Rã (22.45, 105.7)"),
        ("1591440", "Bắc Quang (22.48333, 104.86667)"),
        ("1567221", "Thị Trấn Tà Lùng (22.4979, 106.5669)"),
        ("1571725", "Thị Trấn Nước Hai (22.73738, 106.15216)"),
        ("1563704", "Thị Trấn Trùng Khánh (22.83514, 106.52496)"),
        ("1574706", "Thị Trấn Mèo Vạc (23.16411, 105.40993)"),
        ("1570907", "Thị Trấn Phố Bảng (23.25432, 105.18448)"),
        ("1568039", "Sà Phìn (23.26667, 105.25)"),
        ("1575552", "Lũng Cú (23.36106, 105.31552)"),
    ),
}
SOURCE_TIMEZONE_CORRECTIONS.update(
    {
        record_id: {
            "expected": _VIETNAM_SIDE_ZONES["south" if side == "north" else "north"],
            "corrected": _VIETNAM_SIDE_ZONES[side],
            "reason": f"{place}: {_VIETNAM_SIDE_REASONS[side]}",
        }
        for side, rows in _VIETNAM_ROWS_BY_SIDE.items()
        for record_id, place in rows
    }
)


# Named admin1 errors in GeoNames rows: the row's code names a province the row
# is nowhere near, so the label read "Baiyanghe, Heilongjiang, CN" for a Xinjiang
# township.  admin1CodesASCII.txt maps each code correctly; the rows carry the
# wrong code.  Found by testing every Chinese row against its province's
# published extent (tests/backend/test_place_catalog.py keeps that check) and
# identified by the township names the rows carry.  Each group is
# (expected code, corrected code, reason, row ids); like the zone table, a row
# is changed only while the source still carries the expected code.
_ADMIN1_CORRECTION_GROUPS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "08", "13",
        "Xinjiang townships of the 2013 GeoNames import (e.g. 柏杨河哈萨克族乡, 吉木萨尔镇, "
        "塔克什肯镇, 铁干里克乡) at 37-48 N, 83-91 E, all on Asia/Urumqi: inside Xinjiang "
        "(73.5-96.4 E); CN.08 Heilongjiang lies east of 121.2 E",
        (
            "8548587", "8548588", "8548589", "8548590", "8548592", "8548593", "8548594",
            "8548595", "8548619", "8548621", "8548622", "8548623", "8548624", "8548625",
            "8548626", "8548705", "8548749", "8548750", "8548754", "8548876", "8548877",
            "8548878", "8548879", "8548894", "8548895", "8548896", "8548902", "8548903",
            "8548904", "8549034", "8549035", "8549133", "8549135", "8549136", "8549378",
            "8550443", "8550444",
        ),
    ),
    (
        "08", "15",
        "Duobagou 多坝沟乡 (39.75181, 93.48198) is in Aksay Kazakh Autonomous County, Gansu "
        "(the county's 多坝沟 forest station and 多坝沟胡杨峡 scenic area); its GeoNames id "
        "follows Aksay's seat Hongliuwan 8550586 (CN.15) and its eight nearest rows are CN.15; "
        "CN.08 Heilongjiang lies east of 121.2 E",
        ("8550587",),
    ),
    (
        "13", "20",
        "Townships of Baotou, Inner Mongolia (下湿壕镇, 卜塔亥, 红泥井, 吉忽伦图苏木) at "
        "40.8-41.4 N, 109.8-110.6 E: inside Inner Mongolia (97.2-126.1 E); CN.13 Xinjiang "
        "lies west of 96.4 E",
        ("8544212", "8544248", "8544438", "8545763", "8545899", "8545941", "8545962"),
    ),
    (
        "09", "10",
        "Townships of Shijiazhuang and Baoding, Hebei (九门回族乡, 白鹿泉乡, 北正乡, 羊平镇) "
        "at 38.0-39.0 N, 114.1-115.0 E among 119 rows coded CN.10 Hebei; CN.09 Henan lies "
        "south of 36.4 N",
        (
            "8561593", "8561608", "8561612", "8561617", "8561623", "8561628", "8561645",
            "8561736", "8561780", "8561781", "8561816", "8561827", "8561844", "8561845",
            "8561876", "8561878", "8561887", "8561889", "8561901", "8561903", "8561907",
            "8561919", "8561933", "8561935", "8561956", "8561970", "8562004", "8562010",
            "8562026", "8562030", "8562049", "8562065", "8562069", "8562077", "8562089",
            "8562152", "8562161", "8562162", "8562169", "8562192", "8562300", "8562381",
            "8594797", "8594798",
        ),
    ),
    (
        "10", "14",
        "Townships of Nagqu and Chamdo, Tibet (强玛镇, 嘎美乡, 赤多乡, 马武乡, 措折强玛乡) "
        "at 30.9-33.3 N, 87.8-95.2 E; CN.10 Hebei lies east of 113.4 E",
        ("8577878", "8578325", "8578737", "8578738", "8579135"),
    ),
    (
        "33", "02",
        "Townships of Yongjia County, Wenzhou, Zhejiang (大箬岩镇, 潘坑乡, 茗岙乡, 西溪乡) "
        "at 28.2-28.5 N, 120.4-120.6 E; CN.33 Chongqing lies west of 110.2 E",
        ("8415423", "8415425", "8415426", "8415429", "8415430", "8415431", "8415432"),
    ),
    (
        "04", "06",
        "Tuohua 托勒蒙古族乡 (37.08139, 100.68358) lies north-east of Qinghai Lake in Haibei, "
        "Qinghai, and its eight nearest rows are CN.06; CN.04 Jiangsu lies east of 116.3 E",
        ("7351996",),
    ),
    (
        "04", "32",
        "Daocheng (29.0379, 100.2974) is the seat of Daocheng County 稻城县, Garze, Sichuan, "
        "at these exact coordinates (GeoNames' 道成 is a homophone); CN.04 Jiangsu lies east "
        "of 116.3 E",
        ("8395541",),
    ),
)
# Named admin1 errors outside China, found by comparing each row's admin1 with
# its nearest same-country neighbours and checked one by one against the
# place's own administrative statement (Wikidata, or the PhilAtlas gazetteer
# for a Philippine barangay).  Rows whose code is right but whose coordinates
# belong elsewhere are not corrected here: changing the province would label a
# different place.
_OTHER_ADMIN1_CORRECTIONS: dict[str, dict[str, str]] = {
    "1218089": {
        "country": "TM", "expected": "03", "corrected": "04",
        "reason": "Garlyk (37.5899, 66.34081) is a village of Köýtendag District, Lebap "
        "(Wikidata Q25389108 at 37.5897, 66.3407); Dasoguz is the country's north, its seat at 41.8 N",
    },
    "1644833": {
        "country": "ID", "expected": "36", "corrected": "39",
        "reason": "Fakfak (-2.92481, 132.29813) is the seat of Fakfak Regency, West Papua "
        "(Wikidata Q26727, Q1393640 at -2.930, 132.303); Papua province lies east of it",
    },
    "1717066": {
        "country": "PH", "expected": "03", "corrected": "41",
        "reason": "Communal (alternate name Comunal; 13.2548, 121.1366, population 2773) is "
        "barangay Comunal, Calapan, Oriental Mindoro, Mimaropa (PhilAtlas: 13.3075, 121.1606, "
        "2,700 in 2007); Central Luzon's southern tip, Bataan, is near 14.4 N",
    },
    "1824888": {
        "country": "KH", "expected": "24", "corrected": "07",
        "reason": "Siem Reab (11.40035, 104.86384) is a commune of Kandal Stueng District, Kandal "
        "(Wikidata Q56320412 at 11.4001, 104.8686); Siem Reap province is on the north shore of the Tonle Sap",
    },
    "2281606": {
        "country": "CI", "expected": "92", "corrected": "96",
        "reason": "Sinfra (6.62103, -5.91144) is the seat of Sinfra Department, Marahoué Region, "
        "Sassandra-Marahoué District (Wikidata Q12709357); Zanzan is the north-east of the country",
    },
    "3080533": {
        "country": "PL", "expected": "83", "corrected": "72",
        "reason": "Zawidów (51.02546, 15.06213) is a town of Zgorzelec County, Lower Silesian "
        "Voivodeship (Wikidata Q167756 at 51.0262, 15.0624); Silesian Voivodeship lies at 18-20 E",
    },
    "3084237": {
        "country": "PL", "expected": "77", "corrected": "76",
        "reason": "Sulęcin (52.44429, 15.11676) is the seat of Sulęcin County, Lubusz Voivodeship "
        "(Wikidata Q718038 at 52.4417, 15.1167); Lesser Poland lies south-east, near 50 N 20 E",
    },
    "548040": {
        "country": "RU", "expected": "40", "corrected": "21",
        "reason": "Kitovo (56.86586, 41.28246) is a village of Shuysky District, Ivanovo Oblast "
        "(Wikidata Q18398963 at 56.8656, 41.2919); Kurgan Oblast lies beyond the Urals, east of 61 E",
    },
    "693305": {
        "country": "UA", "expected": "05", "corrected": "04",
        "reason": "Sofiyivka (48.00675, 33.11347) is Sofiivka, Kryvyi Rih Raion, Dnipropetrovsk "
        "Oblast (Wikidata Q4102960 at 48.0089, 33.1152); its Donetsk code and Kramatorsk admin2 "
        "belong to the Sofiyivka of row 693315",
    },
    "693315": {
        "country": "UA", "expected": "04", "corrected": "05",
        "reason": "Sofiyivka (48.74078, 37.51411) is the settlement of Kramatorsk Raion, Donetsk "
        "Oblast (Wikidata Q4429956 at 48.7408, 37.5131); its Dnipropetrovsk code belongs to row 693305",
    },
    "8529147": {
        "country": "TO", "expected": "03", "corrected": "02",
        "reason": "Pelehake (-21.21283, -175.14328) is on Tongatapu, in Tatakamotonga "
        "(Wikidata Q124791606 at -21.2160, -175.1399); Vava'u lies near 18.6 S",
    },
    "8613348": {
        "country": "ID", "expected": "14", "corrected": "42",
        "reason": "Sungai Nyamuk (4.14383, 117.91087) is a village of East Sebatik, Nunukan, "
        "North Kalimantan (Wikidata Q12517896 at 4.1289, 117.8828); North Kalimantan was separated "
        "from East Kalimantan in 2012",
    },
}
SOURCE_ADMIN1_CORRECTIONS: dict[str, dict[str, str]] = {
    **{
        record_id: {"country": "CN", "expected": expected, "corrected": corrected, "reason": reason}
        for expected, corrected, reason, record_ids in _ADMIN1_CORRECTION_GROUPS
        for record_id in record_ids
    },
    **_OTHER_ADMIN1_CORRECTIONS,
}

# Named source rows left out: another row is the same place, or the row's
# coordinates are another place's and no source gives its own.  Each entry
# states the name the source row is expected to carry and the row that stays in
# its place (None when none does); a source row that no longer carries that name
# is kept and reported.
CORRECTION_EXCLUDED = "excluded"
SOURCE_ROW_EXCLUSIONS: dict[str, dict[str, str | None]] = {
    "1679136": {
        "expected_name": "Chang-hua",
        "kept": "1993459",
        "reason": (
            "Changhua City twice: 1679136 Chang-hua and 1993459 Changhua both link "
            "en.wikipedia.org/wiki/Changhua and carry population 226564, 1.3 km apart; "
            "1993459 carries the zh-Hant name 彰化市"
        ),
    },
    "2460584": {
        "expected_name": "Bamba",
        "kept": None,
        "reason": (
            "Bamba of Bourem Cercle, Gao (admin2 and population 28524 are that commune's; "
            "en.wikipedia.org/wiki/Bamba,_Gao_Region at 17.033, -1.400) carries the coordinates "
            "10.38333, -7.15 of Daladiéko, Sikasso (GeoNames 2459430), about 965 km away"
        ),
    },
}


def _table_sha256(table: dict) -> str:
    canonical = json.dumps(table, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def exclusion_table_sha256() -> str:
    """Digest of the exclusion table; the verifier recomputes it like the correction digest."""

    return _table_sha256(SOURCE_ROW_EXCLUSIONS)


def correction_table_sha256() -> str:
    """Digest of the correction table, recorded so a stale artifact is detectable.

    ``scripts/verification/verify_place_catalog.py`` recomputes this from the
    table it imports and fails when the shipped manifest records another value:
    a correction added or changed here without a rebuild is a stale catalogue.
    """

    return _table_sha256(SOURCE_TIMEZONE_CORRECTIONS)


def admin1_correction_table_sha256() -> str:
    """Digest of the admin1 correction table; the verifier binds it like the zone table."""

    return _table_sha256(SOURCE_ADMIN1_CORRECTIONS)


# Chinese-name language preference, most preferred first.  Untagged "zh" is
# left out: its script is unknown and mostly Simplified, which mixed scripts in
# a Traditional-Chinese picker.
ZH_LANGUAGE_PREFERENCE = ("zh-Hant", "zh-TW")

# Disambiguation levels, most human-meaningful first.  ``coordinate`` is the
# last resort and is reported as such in the manifest.
DISAMBIGUATION_LEVELS = ("admin3", "admin2_name", "coordinate")


class _CountyGroup(TypedDict):
    county_code: str
    coordinates: list[tuple[float, float]]
    aliases: set[str]


@dataclass
class BoundedInput:
    """One input opened once; hashed and streamed through the same descriptor."""

    path: Path
    handle: BinaryIO
    sha256: str
    size_bytes: int

    def rewind(self) -> BinaryIO:
        self.handle.seek(0)
        return self.handle

    def close(self) -> None:
        self.handle.close()


def _open_bounded_input(path: Path) -> BoundedInput:
    """Open ``path`` once, bound it by ``fstat`` on the open descriptor, hash it.

    The previous producer checked the path, read the rows through one open and
    hashed the path through a second.  Replacing the file between those two
    opens produced a manifest that described bytes the build never consumed.
    Here the descriptor is held for the whole build: size, digest and the
    streamed rows all come from the same open file.
    """

    if path.is_symlink():
        raise ValueError(f"input must be a regular non-symlink file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError(f"input must be a regular non-symlink file: {path}") from exc
    handle = os.fdopen(descriptor, "rb")
    try:
        status = os.fstat(handle.fileno())
        if not stat.S_ISREG(status.st_mode):
            raise ValueError(f"input must be a regular non-symlink file: {path}")
        if status.st_size > MAX_INPUT_BYTES:
            raise ValueError(f"input exceeds bounded byte limit: {path.name}")
        digest = hashlib.file_digest(handle, "sha256")
        handle.seek(0)
    except Exception:
        handle.close()
        raise
    return BoundedInput(path=path, handle=handle, sha256=digest.hexdigest(), size_bytes=status.st_size)


def _as_bounded_input(source: Path | BoundedInput) -> tuple[BoundedInput, bool]:
    if isinstance(source, BoundedInput):
        return source, False
    return _open_bounded_input(Path(source)), True


def _taiwan_character_variants(value: str) -> str:
    """Index both common 臺/台 spellings without a runtime conversion service."""

    return " ".join(dict.fromkeys((value, value.replace("台", "臺"), value.replace("臺", "台"))))


def _has_han(value: str) -> bool:
    return any(unicodedata.name(character, "").startswith("CJK ") for character in value)


def _han_alternate_names(alternate_names: str) -> list[str]:
    """The Chinese-script entries of a GeoNames alternate-name list."""

    return [item.strip() for item in alternate_names.split(",") if item.strip() and _has_han(item)]


def _is_upstream_test_row(row: dict) -> bool:
    return any("test" in str(row.get(field) or "").casefold() for field in _UPSTREAM_TEST_FIELDS)


def _semantic_name_rejection(name: str) -> str | None:
    """Return the closed rejection reason for an unusable name, else None."""

    if not normalize_search_text(name):
        return REJECT_EMPTY_NAME
    if not place_name_match_key(name):
        return REJECT_NONWORD_NAME
    return None


_IANA_ZONES: frozenset[str] | None = None


def _require_iana_timezone(value: str, *, record_id: str) -> None:
    global _IANA_ZONES
    if _IANA_ZONES is None:
        _IANA_ZONES = frozenset(zoneinfo.available_timezones())
    if value not in _IANA_ZONES:
        raise ValueError(f"source row {record_id} carries a timezone unknown to the IANA database: {value!r}")


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;
        CREATE TABLE places (
            source TEXT NOT NULL,
            source_record_id TEXT NOT NULL,
            name TEXT NOT NULL,
            normalized_name TEXT NOT NULL,
            match_keys TEXT NOT NULL,
            display_name TEXT NOT NULL,
            country_code TEXT NOT NULL,
            admin1 TEXT,
            admin1_name TEXT,
            admin2 TEXT,
            admin3 TEXT,
            name_zh TEXT,
            disambiguator TEXT,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timezone TEXT NOT NULL,
            location_precision TEXT NOT NULL,
            population INTEGER NOT NULL,
            source_priority INTEGER NOT NULL,
            UNIQUE(source, source_record_id)
        );
        CREATE VIRTUAL TABLE place_search USING fts5(
            name,
            aliases,
            admin1,
            admin2,
            content='',
            tokenize='unicode61 remove_diacritics 2'
        );
        CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        """
    )


def _insert(connection: sqlite3.Connection, record: dict) -> bool:
    cursor = connection.execute(
        """
        INSERT OR IGNORE INTO places (
            source, source_record_id, name, normalized_name, match_keys, display_name,
            country_code, admin1, admin1_name, admin2, admin3, name_zh,
            disambiguator, latitude, longitude, timezone,
            location_precision, population, source_priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record["source"],
            record["source_record_id"],
            record["name"],
            place_name_match_key(record["name"]),
            match_keys_text((record["name"], record.get("name_zh"), *record.get("match_names", ()))),
            record["display_name"],
            record["country_code"],
            record["admin1"],
            record.get("admin1_name"),
            record["admin2"],
            record.get("admin3"),
            record.get("name_zh"),
            None,
            record["latitude"],
            record["longitude"],
            record["timezone"],
            record["location_precision"],
            record["population"],
            record["source_priority"],
        ),
    )
    if cursor.rowcount == 0:
        return False
    rowid = cursor.lastrowid
    connection.execute(
        """
        INSERT INTO place_search(rowid, name, aliases, admin1, admin2)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            rowid,
            normalize_search_text(
                _taiwan_character_variants(
                    f"{record['name']} {record['display_name'].replace(MISSING_GLYPH_MARK, '')}"
                )
            ),
            normalize_search_text(_taiwan_character_variants(record["aliases"])),
            normalize_search_text(record["admin1"] or ""),
            normalize_search_text(record["admin2"] or ""),
        ),
    )
    return True


def _bounded_lines(handle):
    for line in handle:
        if len(line) > MAX_LINE_CHARS:
            raise ValueError("GeoNames row exceeds bounded line limit")
        yield line


def _geonames_lines(source: Path | BoundedInput, *, member_name: str | None = None):
    """Yield the lines of a GeoNames text file or of one member of its archive.

    ``alternateNamesV2.zip`` carries ``iso-languagecodes.txt`` beside the data
    file, so a caller that knows the data member names it; otherwise the
    archive must hold exactly one text file.
    """

    bounded, owned = _as_bounded_input(source)
    try:
        handle = bounded.rewind()
        if zipfile.is_zipfile(handle):
            handle.seek(0)
            with zipfile.ZipFile(handle) as archive:
                members = [
                    info
                    for info in archive.infolist()
                    if (info.filename == member_name if member_name else info.filename.endswith(".txt"))
                ]
                if len(members) != 1:
                    raise ValueError(
                        f"GeoNames archive must contain exactly one {member_name or 'text file'}"
                    )
                member = members[0]
                if member.file_size > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("GeoNames member exceeds bounded uncompressed limit")
                with archive.open(member) as raw:
                    yield from _bounded_lines(io.TextIOWrapper(raw, encoding="utf-8"))
        else:
            handle.seek(0)
            wrapper = io.TextIOWrapper(handle, encoding="utf-8")
            try:
                yield from _bounded_lines(wrapper)
            finally:
                wrapper.detach()
    finally:
        if owned:
            bounded.close()


def _geonames_display_name(name: str, name_zh: str | None, admin1_name: str | None, country_code: str) -> str:
    label = f"{name_zh}（{name}）" if name_zh and name_zh != name else name
    if _missing_glyph(name, name_zh):
        label += MISSING_GLYPH_MARK
    parts = [label]
    # 「臺北市（Taipei）, 臺北市, TW」 repeats itself; the county is already the label.
    if admin1_name and admin1_name != name_zh:
        parts.append(admin1_name)
    parts.append(country_code)
    return ", ".join(parts)


def load_geonames_code_table(source: Path | BoundedInput | None) -> dict[str, str]:
    """Load ``admin1CodesASCII.txt`` / ``admin2Codes.txt`` as code -> name."""

    if source is None:
        return {}
    bounded, owned = _as_bounded_input(source)
    table: dict[str, str] = {}
    try:
        wrapper = io.TextIOWrapper(bounded.rewind(), encoding="utf-8")
        try:
            for line in _bounded_lines(wrapper):
                fields = line.rstrip("\n").split("\t")
                if len(fields) < 2:
                    continue
                code, name = fields[0], fields[1]
                if code and name:
                    table[code] = name
        finally:
            wrapper.detach()
    finally:
        if owned:
            bounded.close()
    return table


# Taiwan's 22 top-level counties and cities, by MOI CountyCode, with the
# GeoNames admin1.admin2 code of the same area.  GeoNames' admin1 for Taiwan is
# the pre-1998 province (Fukien, Takao, Taipei, Taiwan), so labels read
# 「Kaohsiung, Takao, TW」; its admin2 is the county.  GeoNames codes Hsinchu
# City HSQ and Hsinchu County HSZ (Chiayi City CYI, County CYQ), as its own
# rows and names confirm.  Names are not written here: the county name comes
# from the MOI files and its English names from them and from admin2Codes.
TAIWAN_COUNTY_CODES: dict[str, str] = {
    "63000": "04.TPE", "65000": "03.TPQ", "68000": "04.TAO", "66000": "04.TXG",
    "67000": "04.TNN", "64000": "02.KHH", "10017": "04.KEE", "10018": "04.HSQ",
    "10004": "04.HSZ", "10020": "04.CYI", "10010": "04.CYQ", "10005": "04.MIA",
    "10007": "04.CHA", "10008": "04.NAN", "10009": "04.YUN", "10013": "04.PIF",
    "10002": "04.ILA", "10015": "04.HUA", "10014": "04.TTT", "10016": "04.PEN",
    "9020": "01.KIN", "9007": "01.LIE",
}
# Names in common use for a county that neither source gives as its name.
TAIWAN_COUNTY_EXTRA_NAMES: dict[str, tuple[str, ...]] = {
    "10016": ("Pescadores",),
    "9020": ("Quemoy",),
    "9007": ("Matsu", "Matsu Islands", "馬祖"),
}
_ENGLISH_ADMIN_SUFFIX = re.compile(r"\s*(?:city|county)$", re.IGNORECASE)


def taiwan_counties_by_code(sources: tuple[Path | BoundedInput, ...]) -> dict[str, str]:
    """MOI CountyCode -> County name, read from the MOI files themselves."""

    counties: dict[str, str] = {}
    for source in sources:
        bounded, owned = _as_bounded_input(source)
        try:
            for line_number, row in enumerate(_taiwan_reader(bounded), start=2):
                if line_number > MAX_SOURCE_ROWS + 1:
                    raise ValueError("Taiwan input exceeds bounded row limit")
                county = str(row.get("County") or "").strip()
                code = str(row.get("CountyCode") or "").strip()
                if county and code:
                    if counties.setdefault(code, county) != county:
                        raise ValueError(f"MOI CountyCode {code} names two counties")
        finally:
            if owned:
                bounded.close()
    return counties


def _taiwan_county_search_names(
    county: str, county_code: str, phonetics: set[str], admin2_name: str | None
) -> tuple[str, ...]:
    """Full and short name, the English names of the sources, and named extras.

    Each English name (GeoNames admin2, MOI phonetics such as 「TaibeiCity」 or
    「Pingdong City」) is reduced to its base and given the county's own
    suffix, so 「Taipei City」, 「Taipei」 and 「Taibei」 all name 臺北市.
    """

    suffix = "City" if county.endswith("市") else "County"
    names = [county, county[:-1]]
    for raw in (admin2_name, *sorted(phonetics)):
        if not raw or not raw.isascii():
            continue
        base = _ENGLISH_ADMIN_SUFFIX.sub("", raw.strip()).strip()
        if base:
            names += [base, f"{base} {suffix}"]
    names += TAIWAN_COUNTY_EXTRA_NAMES.get(county_code, ())
    return tuple(dict.fromkeys(names))


def _taiwan_county(geonameid: str, admin1: str, admin2: str, counties: dict[str, str]) -> str:
    county = counties.get(f"{admin1}.{admin2}")
    if county is None:
        raise ValueError(
            f"Taiwan GeoNames row {geonameid} has admin {admin1}.{admin2}, "
            "which TAIWAN_COUNTY_CODES and the MOI files do not name"
        )
    return county


def _admin1_correction_record(
    geonameid: str, correction: dict[str, str], observed: str | None, status: str,
    admin1_names: dict[str, str],
) -> dict:
    return {
        "source": "geonames_cities500",
        "source_record_id": geonameid,
        "field": "admin1",
        "country_code": correction["country"],
        "expected": correction["expected"],
        "corrected": correction["corrected"],
        "corrected_name": admin1_names.get(f"{correction['country']}.{correction['corrected']}"),
        "observed": observed,
        "status": status,
        "reason": correction["reason"],
    }


def import_geonames(
    connection: sqlite3.Connection,
    source: Path | BoundedInput,
    *,
    admin1_names: dict[str, str] | None = None,
    taiwan_counties: dict[str, str] | None = None,
    rejected: Counter | None = None,
    corrections: list[dict] | None = None,
    exclusions: list[dict] | None = None,
    admin1_corrections: list[dict] | None = None,
) -> int:
    """Import cities500; ``taiwan_counties`` maps a GeoNames admin1.admin2 code to its MOI county."""

    admin1_names = admin1_names or {}
    taiwan_counties = taiwan_counties or {}
    rejected = rejected if rejected is not None else Counter()
    corrections = corrections if corrections is not None else []
    exclusions = exclusions if exclusions is not None else []
    pending_corrections = dict(SOURCE_TIMEZONE_CORRECTIONS)
    pending_exclusions = dict(SOURCE_ROW_EXCLUSIONS)
    admin1_corrections = admin1_corrections if admin1_corrections is not None else []
    pending_admin1 = dict(SOURCE_ADMIN1_CORRECTIONS)
    count = 0
    for line in _geonames_lines(source):
        if count >= MAX_SOURCE_ROWS:
            raise ValueError("GeoNames input exceeds bounded row limit")
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 19:
            raise ValueError("invalid GeoNames cities500 row")
        (
            geonameid,
            name,
            ascii_name,
            alternate_names,
            latitude,
            longitude,
            _feature_class,
            _feature_code,
            country_code,
            _cc2,
            admin1,
            admin2,
            _admin3,
            _admin4,
            population,
            _elevation,
            _dem,
            timezone,
            _modified,
        ) = fields[:19]
        rejection = _semantic_name_rejection(name)
        if rejection is not None:
            rejected[rejection] += 1
            continue
        exclusion = pending_exclusions.pop(geonameid, None)
        if exclusion is not None:
            excluded = name == exclusion["expected_name"]
            exclusions.append(
                {
                    "source": "geonames_cities500",
                    "source_record_id": geonameid,
                    "expected_name": exclusion["expected_name"],
                    "observed_name": name,
                    "kept": exclusion["kept"],
                    "status": CORRECTION_EXCLUDED if excluded else CORRECTION_STALE_NOT_APPLIED,
                    "reason": exclusion["reason"],
                }
            )
            if excluded:
                continue
        correction = pending_corrections.pop(geonameid, None)
        if correction is not None:
            if timezone == correction["expected"]:
                status = CORRECTION_APPLIED
                timezone = correction["corrected"]
            elif timezone == correction["corrected"]:
                status = CORRECTION_ALREADY_UPSTREAM
            else:
                status = CORRECTION_STALE_NOT_APPLIED
            corrections.append(
                {
                    "source": "geonames_cities500",
                    "source_record_id": geonameid,
                    "field": "timezone",
                    "expected": correction["expected"],
                    "corrected": correction["corrected"],
                    "observed": fields[17],
                    "status": status,
                    "reason": correction["reason"],
                }
            )
        _require_iana_timezone(timezone, record_id=geonameid)
        admin1_fix = pending_admin1.pop(geonameid, None)
        if admin1_fix is not None:
            observed_admin1 = admin1
            if country_code == admin1_fix["country"] and admin1 == admin1_fix["expected"]:
                admin1_status = CORRECTION_APPLIED
                admin1 = admin1_fix["corrected"]
            elif country_code == admin1_fix["country"] and admin1 == admin1_fix["corrected"]:
                admin1_status = CORRECTION_ALREADY_UPSTREAM
            else:
                admin1_status = CORRECTION_STALE_NOT_APPLIED
            admin1_corrections.append(
                _admin1_correction_record(geonameid, admin1_fix, observed_admin1, admin1_status, admin1_names)
            )
        aliases = " ".join(item for item in (ascii_name, alternate_names.replace(",", " ")) if item)
        admin1_name: str | None
        if country_code == "TW":
            admin1_name = _taiwan_county(geonameid, admin1, admin2, taiwan_counties)
        else:
            admin1_name = admin1_names.get(f"{country_code}.{admin1}") if admin1 else None
        # A Taiwan city GeoNames names only in an untagged alias (板橋 for
        # Banqiao) must still be a name match for a Chinese query.  Other
        # countries are left out: their Chinese aliases include other cities'
        # names (台東 for Tokyo's Taito), which would make foreign rows exact.
        match_names = _han_alternate_names(alternate_names) if country_code == "TW" else []
        inserted = _insert(
            connection,
            {
                "source": "geonames_cities500",
                "source_record_id": geonameid,
                "name": name,
                "display_name": _geonames_display_name(name, None, admin1_name, country_code),
                "aliases": aliases,
                "country_code": country_code,
                "admin1": admin1 or None,
                "admin1_name": admin1_name,
                "admin2": admin2 or None,
                "admin3": None,
                "name_zh": None,
                "match_names": match_names,
                "latitude": float(latitude),
                "longitude": float(longitude),
                "timezone": timezone,
                "location_precision": "place_representative_point",
                "population": int(population or 0),
                "source_priority": 10,
            },
        )
        count += int(inserted)
    for geonameid, exclusion in pending_exclusions.items():
        exclusions.append(
            {
                "source": "geonames_cities500",
                "source_record_id": geonameid,
                "expected_name": exclusion["expected_name"],
                "observed_name": None,
                "kept": exclusion["kept"],
                "status": CORRECTION_ROW_ABSENT,
                "reason": exclusion["reason"],
            }
        )
    for geonameid, admin1_fix in pending_admin1.items():
        admin1_corrections.append(
            _admin1_correction_record(geonameid, admin1_fix, None, CORRECTION_ROW_ABSENT, admin1_names)
        )
    for geonameid, correction in pending_corrections.items():
        corrections.append(
            {
                "source": "geonames_cities500",
                "source_record_id": geonameid,
                "field": "timezone",
                "expected": correction["expected"],
                "corrected": correction["corrected"],
                "observed": None,
                "status": CORRECTION_ROW_ABSENT,
                "reason": correction["reason"],
            }
        )
    return count


def apply_geonames_chinese_names(connection: sqlite3.Connection, source: Path | BoundedInput | None) -> int:
    """Attach one Traditional-Chinese name per GeoNames row from alternateNamesV2.

    Preference: language in ``ZH_LANGUAGE_PREFERENCE`` order, then the row
    flagged ``isPreferredName``, then the lowest ``alternateNameId`` so a
    rebuild from the same inputs picks the same name.
    """

    if source is None:
        return 0
    wanted = {
        row[0]
        for row in connection.execute(
            "SELECT source_record_id FROM places WHERE source = 'geonames_cities500'"
        )
    }
    best: dict[str, tuple[int, int, int, str]] = {}
    rank = {code: index for index, code in enumerate(ZH_LANGUAGE_PREFERENCE)}
    for line in _geonames_lines(source, member_name="alternateNamesV2.txt"):
        fields = line.rstrip("\n").split("\t")
        if len(fields) < 4:
            continue
        alternate_id, geonameid, language, value = fields[:4]
        if geonameid not in wanted or language not in rank:
            continue
        value = value.strip()
        if not value:
            continue
        preferred = 0 if (len(fields) > 4 and fields[4] == "1") else 1
        try:
            order = int(alternate_id)
        except ValueError:
            continue
        candidate = (rank[language], preferred, order, value)
        if geonameid not in best or candidate < best[geonameid]:
            best[geonameid] = candidate
    updated = 0
    for geonameid, (_rank, _preferred, _order, value) in best.items():
        row = connection.execute(
            "SELECT rowid, name, admin1_name, country_code, match_keys FROM places "
            "WHERE source = 'geonames_cities500' AND source_record_id = ?",
            (geonameid,),
        ).fetchone()
        if row is None:
            continue
        rowid, name, admin1_name, country_code, match_keys = row
        connection.execute(
            "UPDATE places SET name_zh = ?, display_name = ?, match_keys = ? WHERE rowid = ?",
            (
                value,
                _geonames_display_name(name, value, admin1_name, country_code),
                match_keys_text((*match_keys.split(MATCH_KEY_SEPARATOR), value)),
                rowid,
            ),
        )
        updated += 1
    return updated


def _taiwan_record_id(kind: str, row: dict) -> str:
    stable = "\x1f".join(
        str(row.get(key) or "")
        for key in ("Type", "PlaceName", "CountyCode", "TownCode", "Village", "Longitude", "Latitude")
    ).encode("utf-8")
    return f"tw-moi-{kind}:{hashlib.sha256(stable).hexdigest()[:20]}"


def _taiwan_reader(bounded: BoundedInput):
    wrapper = io.TextIOWrapper(bounded.rewind(), encoding="utf-8-sig", newline="")
    try:
        yield from csv.DictReader(wrapper)
    finally:
        wrapper.detach()


def import_taiwan(
    connection: sqlite3.Connection,
    source: Path | BoundedInput,
    *,
    kind: str,
    precision: str,
    source_priority: int,
    rejected: Counter | None = None,
) -> int:
    rejected = rejected if rejected is not None else Counter()
    bounded, owned = _as_bounded_input(source)
    count = 0
    try:
        for line_number, row in enumerate(_taiwan_reader(bounded), start=2):
            if line_number > MAX_SOURCE_ROWS + 1:
                raise ValueError("Taiwan input exceeds bounded row limit")
            if not row.get("Longitude") or not row.get("Latitude"):
                rejected[REJECT_MISSING_COORDINATES] += 1
                continue
            if _is_upstream_test_row(row):
                rejected[REJECT_UPSTREAM_TEST_ROW] += 1
                continue
            name = str(row.get("PlaceName") or "")
            rejection = _semantic_name_rejection(name)
            if rejection is not None:
                rejected[rejection] += 1
                continue
            aliases = " ".join(
                str(row.get(key) or "") for key in ("ChinesePhonetic", "CommonPhonetic", "AnotherName")
            )
            label = f"{name}{MISSING_GLYPH_MARK}" if _missing_glyph(name) else name
            display_parts = [label, row.get("Town") or "", row.get("County") or ""]
            inserted = _insert(
                connection,
                {
                    "source": "taiwan_moi_place_names",
                    "source_record_id": _taiwan_record_id(kind, row),
                    "name": name,
                    "display_name": ", ".join(item for item in display_parts if item),
                    "aliases": aliases,
                    "country_code": "TW",
                    "admin1": row.get("County") or None,
                    "admin1_name": row.get("County") or None,
                    "admin2": row.get("Town") or None,
                    "admin3": (row.get("Village") or "").strip() or None,
                    "latitude": float(row["Latitude"]),
                    "longitude": float(row["Longitude"]),
                    "timezone": "Asia/Taipei",
                    "location_precision": precision,
                    "population": 0,
                    "source_priority": source_priority,
                },
            )
            count += int(inserted)
    finally:
        if owned:
            bounded.close()
    return count


def import_taiwan_county_representatives(
    connection: sqlite3.Connection,
    sources: tuple[Path | BoundedInput, ...],
    *,
    admin2_names: dict[str, str] | None = None,
) -> int:
    """Add one explicitly derived representative point for each county/city.

    The MOI files name the top-level administrative areas but omit coordinates
    on those rows.  Their coordinate-bearing child records form the closed
    source set used here.  The arithmetic mean is only a search/picker anchor;
    ``location_precision`` prevents it being presented as a city hall,
    geometric centroid, address, or birth location.
    """

    groups: dict[str, _CountyGroup] = {}
    for source in sources:
        bounded, owned = _as_bounded_input(source)
        try:
            for line_number, row in enumerate(_taiwan_reader(bounded), start=2):
                if line_number > MAX_SOURCE_ROWS + 1:
                    raise ValueError("Taiwan input exceeds bounded row limit")
                county = str(row.get("County") or "").strip()
                if not county:
                    continue
                group = groups.setdefault(
                    county,
                    {"county_code": str(row.get("CountyCode") or ""), "coordinates": [], "aliases": set()},
                )
                if row.get("Longitude") and row.get("Latitude") and not _is_upstream_test_row(row):
                    group["coordinates"].append((float(row["Longitude"]), float(row["Latitude"])))
                if row.get("PlaceName") == county:
                    group["aliases"].update(
                        str(row.get(key) or "").strip()
                        for key in ("ChinesePhonetic", "CommonPhonetic", "AnotherName")
                        if str(row.get(key) or "").strip()
                    )
        finally:
            if owned:
                bounded.close()

    admin2_names = admin2_names or {}
    count = 0
    for county in sorted(groups):
        group = groups[county]
        coordinates = group["coordinates"]
        if not coordinates:
            continue
        geonames_admin = TAIWAN_COUNTY_CODES.get(group["county_code"])
        names = _taiwan_county_search_names(
            county,
            group["county_code"],
            group["aliases"],
            admin2_names.get(f"TW.{geonames_admin}") if geonames_admin else None,
        )
        longitude = sum(item[0] for item in coordinates) / len(coordinates)
        latitude = sum(item[1] for item in coordinates) / len(coordinates)
        stable = f"{group['county_code']}\x1f{county}".encode("utf-8")
        count += int(
            _insert(
                connection,
                {
                    "source": "taiwan_moi_place_names",
                    "source_record_id": f"{TAIWAN_COUNTY_RECORD_PREFIX}{hashlib.sha256(stable).hexdigest()[:20]}",
                    "name": county,
                    "display_name": f"{county}, TW",
                    "aliases": " ".join(sorted(group["aliases"] | set(names[1:]))),
                    "match_names": names,
                    "country_code": "TW",
                    "admin1": county,
                    "admin1_name": county,
                    "admin2": None,
                    "admin3": None,
                    "latitude": round(latitude, 6),
                    "longitude": round(longitude, 6),
                    "timezone": "Asia/Taipei",
                    "location_precision": ("administrative_area_representative_point"),
                    "population": 0,
                    "source_priority": -1,
                },
            )
        )
    return count


def _coordinate_label(latitude: float, longitude: float, digits: int) -> str:
    return (
        f"{abs(latitude):.{digits}f}°{'N' if latitude >= 0 else 'S'} "
        f"{abs(longitude):.{digits}f}°{'E' if longitude >= 0 else 'W'}"
    )


def disambiguate_duplicate_labels(
    connection: sqlite3.Connection, *, admin2_names: dict[str, str] | None = None
) -> dict:
    """Fill ``disambiguator`` for every group of rows sharing a display_name.

    For each colliding group the first level in ``DISAMBIGUATION_LEVELS``
    whose values are distinct across the group's distinct coordinate points is
    used.  The coordinate fallback rounds to 0.01° and widens to 0.0001° only
    when two points share a cell.
    """

    admin2_names = admin2_names or {}
    groups: dict[str, list[tuple]] = {}
    for row in connection.execute(
        "SELECT rowid, display_name, country_code, admin1, admin2, admin3, "
        "latitude, longitude FROM places ORDER BY rowid"
    ):
        groups.setdefault(row[1], []).append(row)
    level_used: Counter = Counter()
    group_count = 0
    row_count = 0
    updates: list[tuple[str | None, int]] = []
    for _display_name, rows in groups.items():
        if len(rows) < 2:
            continue
        group_count += 1
        row_count += len(rows)
        points = {(row[6], row[7]) for row in rows}

        def candidates(level: str) -> list[str | None]:
            values: list[str | None] = []
            for row in rows:
                _rowid, _label, country, admin1, admin2, admin3, lat, lon = row
                if level == "admin3":
                    values.append(admin3)
                elif level == "admin2_name":
                    key = f"{country}.{admin1}.{admin2}" if admin2 else None
                    values.append(admin2_names.get(key) if key else None)
                else:
                    values.append(_coordinate_label(lat, lon, 2))
            return values

        chosen_level = "coordinate"
        chosen_values: list[str | None] = []
        for level in DISAMBIGUATION_LEVELS:
            values = candidates(level)
            if any(value is None for value in values):
                continue
            distinct_by_point: dict[tuple, set] = {}
            for row, value in zip(rows, values, strict=True):
                distinct_by_point.setdefault((row[6], row[7]), set()).add(value)
            point_values = [next(iter(items)) for items in distinct_by_point.values() if len(items) == 1]
            if len(point_values) == len(points) and len(set(point_values)) == len(points):
                chosen_level = level
                chosen_values = values
                break
        if chosen_level == "coordinate" and not chosen_values:
            chosen_values = candidates("coordinate")
            if len(set(chosen_values)) < len(points):
                chosen_values = [_coordinate_label(row[6], row[7], 4) for row in rows]
        level_used[chosen_level] += 1
        for row, value in zip(rows, chosen_values, strict=True):
            updates.append((value, row[0]))
    connection.executemany("UPDATE places SET disambiguator = ? WHERE rowid = ?", updates)
    return {
        "groups": group_count,
        "rows": row_count,
        "level_used": dict(sorted(level_used.items())),
        "levels_in_preference_order": list(DISAMBIGUATION_LEVELS),
        "policy": (
            "rows sharing one display_name receive the first level in "
            "preference order that separates their distinct coordinate points; "
            "coordinate is the last resort"
        ),
    }


def check_timezones_against_coordinates(connection: sqlite3.Connection) -> dict:
    """Compare every GeoNames timezone with the zone at its coordinate.

    Uses ``timezonefinder`` when it is importable; otherwise reports
    ``not_run`` rather than claiming a pass.  A mismatch after the named
    corrections fails the build: a wrong zone changes every house cusp.
    """

    try:
        import timezonefinder  # type: ignore[import-not-found]
    except ImportError:
        return {"status": "not_run", "engine": None, "reason": "timezonefinder_not_installed"}
    finder = timezonefinder.TimezoneFinder(in_memory=True)
    mismatches: list[dict] = []
    checked = 0
    for record_id, lat, lon, zone in connection.execute(
        "SELECT source_record_id, latitude, longitude, timezone FROM places "
        "WHERE source = 'geonames_cities500'"
    ):
        checked += 1
        found = finder.timezone_at(lat=lat, lng=lon)
        if found is None or found == zone:
            continue
        mismatches.append(
            {"source_record_id": record_id, "catalog_timezone": zone, "coordinate_timezone": found}
        )
    if mismatches:
        preview = ", ".join(
            f"{item['source_record_id']} {item['catalog_timezone']}->{item['coordinate_timezone']}"
            for item in mismatches[:20]
        )
        raise ValueError(
            f"{len(mismatches)} GeoNames rows carry a timezone that disagrees "
            f"with their coordinate: {preview}"
        )
    return {
        "status": "passed",
        "engine": f"timezonefinder {getattr(timezonefinder, '__version__', '?')}",
        "rows_checked": checked,
    }


def build_catalog(
    *,
    geonames_zip: Path,
    taiwan_admin_csv: Path,
    taiwan_settlement_csv: Path,
    output: Path,
    source_date: str,
    geonames_admin1_codes: Path | None = None,
    geonames_admin2_codes: Path | None = None,
    geonames_alternate_names: Path | None = None,
) -> dict:
    output.parent.mkdir(parents=True, exist_ok=True)
    working_output = output.with_name(f".{output.name}.building")
    if working_output.exists():
        working_output.unlink()
    inputs: dict[str, BoundedInput] = {}
    connection = sqlite3.connect(working_output)
    try:
        inputs["geonames_cities500"] = _open_bounded_input(geonames_zip)
        inputs["taiwan_moi_administrative"] = _open_bounded_input(taiwan_admin_csv)
        inputs["taiwan_moi_settlement"] = _open_bounded_input(taiwan_settlement_csv)
        optional = {
            "geonames_admin1_codes": geonames_admin1_codes,
            "geonames_admin2_codes": geonames_admin2_codes,
            "geonames_alternate_names": geonames_alternate_names,
        }
        for key, path in optional.items():
            if path is not None:
                inputs[key] = _open_bounded_input(path)

        admin1_names = load_geonames_code_table(inputs.get("geonames_admin1_codes"))
        admin2_names = load_geonames_code_table(inputs.get("geonames_admin2_codes"))
        _schema(connection)
        rejected: dict[str, Counter] = {
            "geonames_cities500": Counter(),
            "taiwan_moi_administrative": Counter(),
            "taiwan_moi_settlement": Counter(),
        }
        corrections: list[dict] = []
        exclusions: list[dict] = []
        admin1_corrections: list[dict] = []
        moi_inputs = (inputs["taiwan_moi_administrative"], inputs["taiwan_moi_settlement"])
        moi_counties = taiwan_counties_by_code(moi_inputs)
        taiwan_counties = {
            geonames_admin: moi_counties[code]
            for code, geonames_admin in TAIWAN_COUNTY_CODES.items()
            if code in moi_counties
        }
        counts = {
            "geonames_cities500": import_geonames(
                connection,
                inputs["geonames_cities500"],
                admin1_names=admin1_names,
                taiwan_counties=taiwan_counties,
                rejected=rejected["geonames_cities500"],
                corrections=corrections,
                exclusions=exclusions,
                admin1_corrections=admin1_corrections,
            ),
            "taiwan_moi_administrative": import_taiwan(
                connection,
                inputs["taiwan_moi_administrative"],
                kind="administrative",
                precision="administrative_area_representative_point",
                source_priority=1,
                rejected=rejected["taiwan_moi_administrative"],
            ),
            "taiwan_moi_settlement": import_taiwan(
                connection,
                inputs["taiwan_moi_settlement"],
                kind="settlement",
                precision="settlement_representative_point",
                source_priority=0,
                rejected=rejected["taiwan_moi_settlement"],
            ),
        }
        counts["taiwan_moi_county_representative"] = import_taiwan_county_representatives(
            connection, moi_inputs, admin2_names=admin2_names
        )
        chinese_names_attached = apply_geonames_chinese_names(
            connection, inputs.get("geonames_alternate_names")
        )
        timezone_check = check_timezones_against_coordinates(connection)
        label_disambiguation = disambiguate_duplicate_labels(connection, admin2_names=admin2_names)
        (rows_marked,) = connection.execute(
            "SELECT COUNT(*) FROM places WHERE instr(display_name, ?) > 0", (MISSING_GLYPH_MARK,)
        ).fetchone()
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "generator_version": GENERATOR_VERSION,
            "source_snapshot_date": source_date,
            "row_counts": counts,
            "geonames_chinese_names_attached": chinese_names_attached,
            "rejected_rows": {source: dict(sorted(counter.items())) for source, counter in rejected.items()},
            "rejection_reasons": [
                REJECT_EMPTY_NAME, REJECT_NONWORD_NAME, REJECT_MISSING_COORDINATES, REJECT_UPSTREAM_TEST_ROW,
            ],
            "source_corrections": corrections,
            "source_corrections_table_sha256": correction_table_sha256(),
            "source_exclusions": exclusions,
            "source_exclusions_table_sha256": exclusion_table_sha256(),
            "source_admin1_corrections": admin1_corrections,
            "source_admin1_corrections_table_sha256": admin1_correction_table_sha256(),
            "timezone_coordinate_check": timezone_check,
            "label_disambiguation": label_disambiguation,
            "missing_glyph_policy": {
                "glyphs": list(MISSING_GLYPHS),
                "label_mark": MISSING_GLYPH_MARK,
                "rows_marked": rows_marked,
            },
            "display_name_policy": {
                "admin1": ("resolved_name" if admin1_names else "code_omitted_no_admin1_table"),
                "chinese_name": (
                    "zh_hant_then_zh_tw_leads_label"
                    if "geonames_alternate_names" in inputs
                    else "not_attached_no_alternate_names_table"
                ),
                "raw_admin1_code_column": "admin1",
                "taiwan_admin1": "county_from_geonames_admin2",
            },
            "licenses": {
                "geonames_cities500": "CC-BY-4.0",
                "taiwan_moi_place_names": ("Taiwan Government Data Open License 1.0"),
            },
            "sources": {
                "geonames_cities500": GEONAMES_SOURCE_URL,
                "geonames_admin1_codes": GEONAMES_ADMIN1_SOURCE_URL,
                "geonames_admin2_codes": GEONAMES_ADMIN2_SOURCE_URL,
                "geonames_alternate_names": GEONAMES_ALTERNATE_NAMES_SOURCE_URL,
                "taiwan_moi_administrative": TAIWAN_ADMIN_SOURCE_URL,
                "taiwan_moi_settlement": TAIWAN_SETTLEMENT_SOURCE_URL,
            },
            "source_sha256": {key: bounded.sha256 for key, bounded in sorted(inputs.items())},
            "source_size_bytes": {key: bounded.size_bytes for key, bounded in sorted(inputs.items())},
            "source_hash_basis": ("sha256_over_the_descriptor_the_rows_were_read_from"),
            "runtime_outbound": False,
            "derived_record_policy": {
                "taiwan_moi_county_representative": (
                    "arithmetic mean of all coordinate-bearing MOI child "
                    "records in the named county/city except upstream test rows; picker anchor only"
                )
            },
        }
        connection.executemany(
            """
            INSERT INTO catalog_metadata(key, value_json)
            VALUES (?, ?)
            """,
            [
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                for key, value in metadata.items()
            ],
        )
        connection.commit()
        connection.execute("VACUUM")
        if working_output.stat().st_size > MAX_OUTPUT_BYTES:
            raise ValueError("place catalog exceeds bounded output limit")
    except Exception:
        connection.close()
        working_output.unlink(missing_ok=True)
        raise
    finally:
        for bounded in inputs.values():
            bounded.close()
        if working_output.exists():
            connection.close()
    os.replace(working_output, output)
    return metadata


def build_artifact_manifest(metadata: dict, *, catalog_path: Path) -> dict:
    return {
        "producer": "scripts/validation/build_place_catalog.py",
        "generator_version": GENERATOR_VERSION,
        "rebuild": {
            "command": (
                "python -m scripts.validation.build_place_catalog "
                "--geonames-zip <cities500.zip> "
                "--geonames-admin1-codes <admin1CodesASCII.txt> "
                "--geonames-admin2-codes <admin2Codes.txt> "
                "--geonames-alternate-names <alternateNamesV2.zip> "
                "--taiwan-admin-csv <taiwan-admin.csv> "
                "--taiwan-settlement-csv <taiwan-settlement.csv> "
                "--output backend/place_data/places.sqlite3 "
                "--manifest backend/place_data/catalog_manifest.json "
                f"--source-date {metadata['source_snapshot_date']}"
            ),
            "exact_inputs_required": True,
            "input_identity": "source_sha256",
        },
        "catalog": {
            "filename": catalog_path.name,
            "sha256": sha256_file(catalog_path),
            "size_bytes": catalog_path.stat().st_size,
        },
        "licenses": metadata["licenses"],
        "derived_record_policy": metadata["derived_record_policy"],
        "row_counts": metadata["row_counts"],
        "rejected_rows": metadata["rejected_rows"],
        "source_corrections": metadata["source_corrections"],
        "source_corrections_table_sha256": metadata["source_corrections_table_sha256"],
        "source_exclusions": metadata["source_exclusions"],
        "source_exclusions_table_sha256": metadata["source_exclusions_table_sha256"],
        "source_admin1_corrections": metadata["source_admin1_corrections"],
        "source_admin1_corrections_table_sha256": metadata["source_admin1_corrections_table_sha256"],
        "timezone_coordinate_check": metadata["timezone_coordinate_check"],
        "label_disambiguation": metadata["label_disambiguation"],
        "missing_glyph_policy": metadata["missing_glyph_policy"],
        "display_name_policy": metadata["display_name_policy"],
        "runtime_policy": {
            "catalog_mode": "bundled_read_only_sqlite",
            "runtime_outbound": metadata["runtime_outbound"],
            "user_data_written": False,
        },
        "schema_version": metadata["schema_version"],
        "source_sha256": metadata["source_sha256"],
        "source_hash_basis": metadata["source_hash_basis"],
        "source_snapshot_date": metadata["source_snapshot_date"],
        "sources": metadata["sources"],
    }


def write_artifact_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_name(f".{path.name}.building")
    try:
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--geonames-zip", type=Path, required=True)
    parser.add_argument("--geonames-admin1-codes", type=Path)
    parser.add_argument("--geonames-admin2-codes", type=Path)
    parser.add_argument("--geonames-alternate-names", type=Path)
    parser.add_argument("--taiwan-admin-csv", type=Path, required=True)
    parser.add_argument("--taiwan-settlement-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="default: catalog_manifest.json beside --output")
    parser.add_argument("--source-date", required=True)
    args = parser.parse_args()
    metadata = build_catalog(
        geonames_zip=args.geonames_zip,
        taiwan_admin_csv=args.taiwan_admin_csv,
        taiwan_settlement_csv=args.taiwan_settlement_csv,
        output=args.output,
        source_date=args.source_date,
        geonames_admin1_codes=args.geonames_admin1_codes,
        geonames_admin2_codes=args.geonames_admin2_codes,
        geonames_alternate_names=args.geonames_alternate_names,
    )
    manifest_path = args.manifest or (args.output.parent / "catalog_manifest.json")
    manifest = build_artifact_manifest(metadata, catalog_path=args.output)
    write_artifact_manifest(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
