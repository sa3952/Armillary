"""〈時間主星參考案例〉: the reference tables for two synthetic charts (the
site's demonstration date 1990-05-15 Taipei at 14:30, a day chart, and at
22:30, a night chart): the profection years, the firdaria periods (the night
chart under both nocturnal node orders), zodiacal releasing levels 1 and 2 from
Fortune and Spirit with every loosing of the bond, and the decennials' first
level.

Every date and lord is the product's own answer: the annual route, in process,
asked for the hundred-year lifetime window, and once more for a year inside
each releasing level-1 period (the route lists level 2 only for the periods
that meet the asked year).  Nothing here is typed by hand.
"""
from __future__ import annotations

import functools

from . import page_methods_time_lords
from ._common import SIGNS, product_client
from ._demo import DEMO


FRAGMENT = "blog-time-lord-reference-cases"
BODY = page_methods_time_lords.BODY
SIGN_KEYS = ("aries", "taurus", "gemini", "cancer", "leo", "virgo",
             "libra", "scorpio", "sagittarius", "capricorn", "aquarius", "pisces")
SIGN = dict(zip(SIGN_KEYS, SIGNS))
LOT = {"fortune": "命運點", "spirit": "精神點"}
NODE_ORDERS = (("abu_mashar_nodes_after_mercury_v1", "交點在水星後（預設）"),
               ("bonatti_reading_nodes_after_mars_v1", "交點在火星後"))
CHARTS = (("day", "例盤 A（日盤）", (14, 30)), ("night", "例盤 B（夜盤）", (22, 30)))
PROFECTION_YEARS = 25


def _request(clock: tuple[int, int], annual: dict) -> dict:
    payload = {key: DEMO[key] for key in ("datetime", "location", "timezone")}
    payload["datetime"] = {**payload["datetime"], "hour": clock[0], "minute": clock[1]}
    payload["annual"] = {"include_profection": True, **annual}
    return payload


@functools.lru_cache(maxsize=1)
def answers() -> dict:
    out = {}
    with product_client(annual=True) as post:
        ask = lambda clock, annual: post("/api/chart/annual?projection=detailed", _request(clock, annual))  # noqa: E731
        for key, _, clock in CHARTS:
            life = {"target_kind": "completed_years", "target_value": 0}
            lifetime = ask(clock, {**life, "include_year_boundaries": True,
                                   "include_zodiacal_releasing": True, "zr_scope": "lifetime_window",
                                   "include_decennials": True, "decennials_scope": "lifetime_window"})
            firdaria = {profile: ask(clock, {**life, "include_firdaria": True, "firdaria_scope": "lifetime_window",
                                             "firdaria_nocturnal_node_profile": profile})["annual_methods"]["firdaria"]
                        for profile, _ in NODE_ORDERS}
            # Level 2 as the route lists it for each return year, gathered over the window.
            level_2: dict = {}
            for year in lifetime["year_boundaries"]["years"]:
                inner = ask(clock, {"target_kind": "completed_years", "target_value": year["completed_years"],
                                    "include_zodiacal_releasing": True})
                for release in inner["annual_methods"]["zodiacal_releasing"]["releases"]:
                    for period in release["periods"]:
                        listed = level_2.setdefault((release["releasing_from"], period["period_id"]), {})
                        for sub in period["level_2"] or ():
                            if listed.setdefault(sub["period_id"], sub) != sub:
                                raise RuntimeError(f"{key}: two years list {sub['period_id']} differently")
            level_2 = {name: sorted(subs.values(), key=lambda sub: sub["start"]["jd_ut"])
                       for name, subs in level_2.items()}
            for release in lifetime["annual_methods"]["zodiacal_releasing"]["releases"]:
                for period in release["periods"]:
                    subs = level_2.get((release["releasing_from"], period["period_id"]), [])
                    if not subs or subs[0]["start"] != period["start"]:
                        raise RuntimeError(f"{key}: level 2 of {period['period_id']} does not start with it")
                    for a, b in zip(subs, subs[1:]):
                        if a["effective_end"]["jd_ut"] != b["start"]["jd_ut"]:
                            raise RuntimeError(f"{key}: a gap in level 2 of {period['period_id']}")
            out[key] = {"lifetime": lifetime, "firdaria": firdaria, "level_2": level_2}
    return out


def _date(instant: dict) -> str:
    return instant["local_date"]


def _local(instant: dict) -> str:
    return instant["local_time"][:16] + f"（{instant['utc_offset']}）"


def _table(tid: str, caption: str, head: tuple[str, ...], rows: list[str]) -> str:
    cols = "".join(f'<th scope="col">{label}</th>' for label in head)
    return (f'<div class="ar-scroll" tabindex="0" role="region" aria-labelledby="{tid}">'
            f'<table class="ar-table"><caption id="{tid}">{caption}</caption>'
            f'<thead><tr>{cols}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def _profections(key: str, title: str, data: dict) -> str:
    rows = []
    for year in data["lifetime"]["year_boundaries"]["years"][:PROFECTION_YEARS]:
        rows.append(f'<tr><td class="n">{year["completed_years"]}</td><td class="n">{_local(year["start"])}</td>'
                    f'<td>{SIGN[year["profection_sign"]]}（第 {year["profected_place"]} 宮）</td>'
                    f'<td>{BODY[year["year_lord"]]}</td></tr>')
    return _table(f"rc-{key}-profection", f"{title}：年度小限，滿 0 到 {PROFECTION_YEARS - 1} 歲",
                  ("滿幾歲", "這一年從何時起", "小限星座", "年主星"), rows)


def _firdaria(key: str, title: str, data: dict) -> str:
    profiles = NODE_ORDERS if key == "night" else NODE_ORDERS[:1]
    blocks = []
    for profile, label in profiles:
        answer = data["firdaria"][profile]
        rows = []
        for period in answer["periods"]:
            subs = "、".join(f'<span class="keep">{BODY[s["level_2_partner"]]} {_date(s["start"])}</span>' for s in period["level_2"] or ())
            rows.append(f'<tr><td>{BODY[period["level_1_lord"]]}</td>'
                        f'<td class="n">{period["start_year"]:g}–{period["end_year"]:g}</td>'
                        f'<td class="n">{_date(period["start"])}</td><td class="n">{_date(period["end"])}</td>'
                        f'<td>{subs or "（交點不分子期）"}</td></tr>')
        name = f"夜盤，{label}" if key == "night" else "日盤（兩種交點排法在日盤相同）"
        blocks.append(_table(f"rc-{key}-firdaria-{profile.split('_')[0]}", f"{title}：法達，{name}",
                             ("主期", "滿幾歲到滿幾歲", "起", "止", "子期（起日）"), rows))
    return "\n".join(blocks)


def _releasing(key: str, title: str, data: dict) -> str:
    blocks = []
    zr = data["lifetime"]["annual_methods"]["zodiacal_releasing"]
    for release in zr["releases"]:
        lot = release["releasing_from"]
        rows = []
        for period in release["periods"]:
            loose = "解鎖" if period["entry_kind"] == "loosing_of_the_bond" else ""
            rows.append(f'<tr class="rc-l1"><th scope="row">第一層 {SIGN[period["sign"]]}{("・" + loose) if loose else ""}</th>'
                        f'<td class="n">{period["nominal_units"]} 年</td><td class="n">{_date(period["start"])}</td>'
                        f'<td class="n">{_date(period["effective_end"])}</td></tr>')
            for sub in data["level_2"][(lot, period["period_id"])]:
                mark = "<b>解鎖</b>" if sub["entry_kind"] == "loosing_of_the_bond" else ""
                cut = "（截斷）" if sub["truncated"] else ""
                rows.append(f'<tr><td>第二層 {SIGN[sub["sign"]]}{" " + mark if mark else ""}</td>'
                            f'<td class="n">{sub["effective_units"]:g} 月{cut}</td>'
                            f'<td class="n">{_date(sub["start"])}</td><td class="n">{_date(sub["effective_end"])}</td></tr>')
        blocks.append(_table(f"rc-{key}-zr-{lot}",
                             f"{title}：黃道釋放，從{LOT[lot]}（{SIGN[release['start_sign']]}）起，第一層與第二層",
                             ("期間", "長度", "起", "止"), rows))
    return "\n".join(blocks)


def _decennials(key: str, title: str, data: dict) -> str:
    dec = data["lifetime"]["annual_methods"]["decennials"]
    rows = [f'<tr><td>{BODY[p["lord"]]}</td><td class="n">{p["months"]} 月</td>'
            f'<td class="n">{_date(p["start"])}</td><td class="n">{_date(p["end"])}</td></tr>' for p in dec["periods"]]
    return _table(f"rc-{key}-decennials", f"{title}：十年期第一層（從{BODY[dec['start_planet']]}起）",
                  ("主星", "長度", "起", "止"), rows)


def loosings(data: dict) -> list[tuple[str, str, str, str]]:
    """(lot, level-1 sign, the sign loosed to, its start date) for every level-2 loosing."""
    found = []
    for release in data["lifetime"]["annual_methods"]["zodiacal_releasing"]["releases"]:
        lot = release["releasing_from"]
        for period in release["periods"]:
            for sub in data["level_2"][(lot, period["period_id"])]:
                if sub["entry_kind"] == "loosing_of_the_bond":
                    found.append((lot, period["sign"], sub["sign"], _date(sub["start"])))
    return found


def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    blocks: dict[str, str] = {}
    quoted: list[str] = []
    for key, title, _ in CHARTS:
        chart = data[key]
        sect = chart["firdaria"][NODE_ORDERS[0][0]]["sect"]["is_day"]
        if sect != (key == "day"):
            raise RuntimeError(f"{key}: the product no longer calls this chart a {key} chart")
        blocks[f"rc-{key}-profection"] = _profections(key, title, chart)
        blocks[f"rc-{key}-firdaria"] = _firdaria(key, title, chart)
        blocks[f"rc-{key}-releasing"] = _releasing(key, title, chart)
        blocks[f"rc-{key}-decennials"] = _decennials(key, title, chart)
        for lot, parent, loosed, start in loosings(chart):
            quoted.append(f"{title}從{LOT[lot]}起的第一層{SIGN[parent]}期，第二層在 {start} 解鎖到{SIGN[loosed]}")
    if not any("解鎖到" in text for text in quoted):
        raise RuntimeError("neither chart looses the bond in its window; the article shows one")
    night = data["night"]["firdaria"]
    nodes = {profile: next(p["start_year"] for p in night[profile]["periods"] if p["level_1_lord"] == "north_node")
             for profile, _ in NODE_ORDERS}
    quoted.append(f"北交點主期在滿 {nodes[NODE_ORDERS[0][0]]:g} 歲起（交點在水星後）或滿 {nodes[NODE_ORDERS[1][0]]:g} 歲起（交點在火星後）")
    second = data["day"]["lifetime"]["year_boundaries"]["years"][1]["start"]
    quoted.append(f"例盤 A 的第二個小限年從 {_local(second)} 起")
    return blocks, quoted
