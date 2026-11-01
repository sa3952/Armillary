"""The public glossary: every entry of the calculator's glossary drawer (scripts/frontend/scripts/glossary.js), in the
drawer's order and words, so the page and the drawer cannot say two different things; and the entry count its prose
quotes."""
from __future__ import annotations

import functools
import html
import json

from ._common import ROOT, node_json, zh

FRAGMENT = "methods-glossary"
GLOSSARY_SCRIPT = ROOT / "scripts/frontend/scripts/glossary.js"

def entries() -> list[dict]:
    found = node_json("const G=require(process.argv[1]);process.stdout.write(JSON.stringify(G.ENTRIES));",
                      GLOSSARY_SCRIPT, what="read the glossary entries")
    if not found or len({entry["key"] for entry in found}) != len(found):
        raise RuntimeError("the glossary has no entries or repeats a key")
    return found

# Where each entry is explained at length on the site: an article (labelled by its title) or a section of a methods
# page (labelled here).  Only the public page links out; the drawer's words stay the drawer's.
_ARTICLE = "/zh-TW/blog/"
_METHODS = "/zh-TW/methods"
FURTHER_READING: dict[str, tuple[str, str | None]] = {
    "asc": (_ARTICLE + "rising-sign-tables", None),
    "whole_sign": (_ARTICLE + "whole-sign-vs-placidus", None),
    "retrograde": (_ARTICLE + "mercury-retrograde-2026", None),
    "node": (_ARTICLE + "mean-vs-osculating-node", None),
    "orb": (_METHODS + "#aspects", "方法頁：相位與容許度"),
    "aspect": (_METHODS + "#aspects", "方法頁：相位與容許度"),
    "aversion": (_METHODS + "#aspects", "方法頁：相位與容許度"),
    "benefic_malefic": (_METHODS + "#classical-classifications", "方法頁：行星與宮的古典分類"),
    "sect": (_ARTICLE + "day-or-night-chart", None),
    "domicile_exaltation": (_METHODS + "#dignities", "方法頁：面、三分性、廟旺陷弱與外來"),
    "detriment": (_METHODS + "#dignities", "方法頁：面、三分性、廟旺陷弱與外來"),
    "fall": (_METHODS + "#dignities", "方法頁：面、三分性、廟旺陷弱與外來"),
    "peregrine": (_METHODS + "#dignities", "方法頁：面、三分性、廟旺陷弱與外來"),
    "bounds_dignity": (_ARTICLE + "four-bounds-tables", None),
    "face": (_METHODS + "#dignities", "方法頁：面、三分性、廟旺陷弱與外來"),
    "triplicity": (_ARTICLE + "triplicity-rulers", None),
    "lots": (_ARTICLE + "lot-of-fortune-formula", None),
    "dodecatemoria": (_ARTICLE + "dodecatemoria", None),
    "novenaria": (_METHODS + "#novenaria", "方法頁：九分部"),
    "lunar_mansions": (_ARTICLE + "lunar-mansions", None),
    "planetary_hours": (_ARTICLE + "planetary-hours", None),
    "time_lords": (_ARTICLE + "time-lords-introduction", None),
    "profection": (_METHODS + "/time-lords#profection", "時間主星方法頁：年度小限"),
    "monthly_profection": (_METHODS + "/time-lords#monthly-profection", "時間主星方法頁：月小限"),
    "firdaria": (_METHODS + "/time-lords#firdaria", "時間主星方法頁：法達"),
    "zodiacal_releasing": (_METHODS + "/time-lords#releasing", "時間主星方法頁：黃道釋放"),
    "decennials": (_METHODS + "/decennials", "十年期的規則、出處與驗算"),
    "cazimi": (_ARTICLE + "combustion-under-beams-cazimi", None),
    "combust": (_ARTICLE + "combustion-under-beams-cazimi", None),
    "under_beams": (_ARTICLE + "combustion-under-beams-cazimi", None),
    "swift_slow": (_METHODS + "#motion-states", "方法頁：行速、停滯與東出西入"),
    "stationary": (_METHODS + "#motion-states", "方法頁：行速、停滯與東出西入"),
    "oriental_occidental": (_METHODS + "#motion-states", "方法頁：行速、停滯與東出西入"),
    "void_of_course": (_METHODS + "#void-of-course", "方法頁：月空亡"),
    "joys": (_METHODS + "#classical-classifications", "方法頁：行星與宮的古典分類"),
    "hayz": (_ARTICLE + "day-or-night-chart", None),
    "house_triad": (_METHODS + "#classical-classifications", "方法頁：行星與宮的古典分類"),
    "prenatal_syzygy": (_ARTICLE + "prenatal-syzygy", None),
    "fixed_stars": (_METHODS + "#fixed-stars", "方法頁：恆星清單依據哪些古書"),
    "antiscia": (_ARTICLE + "antiscia", None),
    "tropical": (_ARTICLE + "tropical-vs-sidereal-zodiac", None),
    "sidereal": (_ARTICLE + "tropical-vs-sidereal-zodiac", None),
    "precession": (_ARTICLE + "tropical-vs-sidereal-zodiac", None),
    "placidus": (_ARTICLE + "house-systems-explained", None),
    "regiomontanus": (_ARTICLE + "house-systems-explained", None),
    "alcabitius": (_ARTICLE + "house-systems-explained", None),
    "porphyry": (_ARTICLE + "house-systems-explained", None),
    "equal_house": (_ARTICLE + "house-systems-explained", None),
    "campanus": (_ARTICLE + "house-systems-explained", None),
    "iana_timezone": (_METHODS + "/birth-time-conversion", "出生時間換算的規則與出處"),
    "representative_instant": (_ARTICLE + "unknown-birth-time", None),
    "receipt": (_ARTICLE + "verify-chart-calculation", None),
}

@functools.lru_cache(maxsize=1)
def _surfaces() -> dict[str, dict]:
    manifest = json.loads((ROOT / "frontend/surfaces.json").read_text(encoding="utf-8"))
    return {item["surface"]: item for item in manifest["surfaces"]}

def further_reading(key: str) -> tuple[str, str] | None:
    """The entry's link and its label; refuses a link to a page the site does not publish or an anchor its fragment
    lacks, so a renamed article or section fails the build instead of shipping a dead link."""
    if key not in FURTHER_READING:
        return None
    href, label = FURTHER_READING[key]
    surface, _, anchor = href.partition("#")
    item = _surfaces().get(surface)
    if item is None:
        raise RuntimeError(f"glossary entry {key!r} links to an unpublished page {surface}")
    if anchor:
        fragment = (ROOT / "scripts/frontend/pages" / f"{item['key']}.html").read_text(encoding="utf-8")
        if f'id="{anchor}"' not in fragment:
            raise RuntimeError(f"glossary entry {key!r} links to a missing anchor {href}")
    if label is None:
        label = item["title"].rpartition("｜")[0] or item["title"]
    return href, label

def _entry(entry: dict) -> str:
    term = html.escape(entry["term"])
    if entry.get("en"):
        term += f' <span class="en" lang="en">{html.escape(entry["en"])}</span>'
    return "\n".join([
        f'        <div class="gl-item" id="{entry["key"]}">',
        f"          <dt>{term}</dt>",
        f'          <dd><p>{html.escape(entry["text"])}</p>'
        f'<p class="gl-where">在結果頁：{html.escape(entry["chapter"])}</p>{_further_line(entry["key"])}</dd>',
        "        </div>",
    ])

def _further_line(key: str) -> str:
    found = further_reading(key)
    if found is None:
        return ""
    href, label = found
    return f'<p class="gl-where">延伸閱讀：<a href="{html.escape(href)}">{html.escape(label)}</a></p>'

def build() -> tuple[dict[str, str], list[str]]:
    found = entries()
    block = "\n".join(['      <dl class="gl-list">', *(_entry(entry) for entry in found), "      </dl>"])
    return {"glossary-entries": block}, [f"共{zh(len(found))}條"]
