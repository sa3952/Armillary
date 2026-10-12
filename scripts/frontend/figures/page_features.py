"""The features page: the demonstration chart's bounds, versions, obliquity,
sampled hour, ascendants, the Sun's three coordinate sets and the dossier
excerpt, from the product's own answers; and the counts, limits and headers it
states, from the code that decides them.
"""
from __future__ import annotations

from . import _demo, _site
from ._common import zh, zh_quantity


FRAGMENT = "features"
# The page's names for the four bounds tables, in _demo.BOUNDS order.
BOUND_LABELS = ("埃及界", "迦勒底界", "Ptolemy 界", "Lilly 1647")
DOSSIER = (
    ("UTC -> 儒略日 (swe.utc_to_jd)", "儒略日 JD(UT)", lambda r: f"{r['JD(UT)']:.7f}", lambda r: "UTC → JD"),
    ("黃赤交角與章動 (swe.calc_ut ECL_NUT)", "真黃赤交角 ε", lambda r: _demo.dms(r["真黃赤交角ε(度)"], 2),
     lambda r: f"平交角 ＋ 章動 Δε {r['交角章動(度)'] * 3600:+.3f}″"),
    ("平均／視恆星時 (Sidereal Time)", "地方真恆星時 LAST", lambda r: f"{r['LAST(小時)']:.7f} h",
     lambda r: "GAST ＋ 東經 ÷ 15"),
)
# Whole sign and equal first, then the quadrant systems in the order they appeared,
# as on the calculate page's menu.
HOUSE_NAMES = {
    "W": "整宮", "E": "等分宮", "O": "Porphyry", "B": "Alcabitius", "C": "Campanus",
    "R": "Regiomontanus", "P": "Placidus",
}
ASPECT_SET_DEFAULT = {"ptolemaic_major_v1": "合相＋四種傳統相位"}
ORB_DEFAULT = {"lilly_1647_experience_v1": "Lilly 1647"}
# The headers the page's table shows, each with the directives it shows.
CSP_SHOWN = ("frame-ancestors", "object-src", "base-uri", "form-action")
PLAIN_SHOWN = ("Referrer-Policy", "Cross-Origin-Opener-Policy", "X-Content-Type-Options")


def _bounds_rows(data: dict) -> tuple[str, int, int]:
    chart, bounds = data["chart"], data["bounds"]
    names = {item["key"]: item["name"] for item in chart["astronomical_data"]["bodies"]}
    rows, differing = [], 0
    for key in _demo.CLASSICAL:
        rulers = [bounds[profile][key] for profile in _demo.BOUNDS]
        answers = len(set(rulers))
        differing += answers > 1
        cells = "".join(f"<td>{names[ruler]}</td>" for ruler in rulers)
        position = _demo.zodiacal(_demo.body(chart, key)["longitude"])
        rows.append(f'            <tr><td>{names[key]}</td><td>{position}</td>{cells}<td class="count">{answers}</td></tr>')
    return "\n".join(rows), len(rows), differing


def _dossier_rows(chart: dict) -> str:
    rows = []
    for title, label, value, how in DOSSIER:
        number, result = _demo.step(chart, title)
        rows.append(f'          <tr><td class="num">{number:03d}</td><td>{label}</td>'
                    f'<td class="num">{value(result)}</td><td>{how(result)}</td></tr>')
    return "\n".join(rows)


def _moon_versus(data: dict) -> list[str]:
    names = {item["key"]: item["name"] for item in data["chart"]["astronomical_data"]["bodies"]}
    rulers = [data["bounds"][profile]["moon"] for profile in _demo.BOUNDS]
    return [f'<span class="vs-label">{label}</span><b class="vs-answer{"" if ruler == rulers[0] else " alt"}">'
            f"{names[ruler]}</b>" for label, ruler in zip(BOUND_LABELS, rulers)]


def _headers() -> list[str]:
    headers = _site.product()["headers"]
    csp = {part.split(" ", 1)[0]: part for part in headers["Content-Security-Policy"].split("; ")}
    permissions = {part.split("=", 1)[0]: part for part in headers["Permissions-Policy"].split(", ")}
    return [
        f'<tr><td>Content-Security-Policy</td><td class="num">{csp["script-src"]}</td>',
        *(f'<td class="num">{csp[name]}</td>' for name in CSP_SHOWN),
        f'<tr><td>Permissions-Policy</td><td class="num">{permissions["geolocation"]}</td>',
        f'<td class="num">{permissions["camera"]}, {permissions["microphone"]}</td>',
        *(f'<tr><td>{name}</td><td class="num">{headers[name]}</td>' for name in PLAIN_SHOWN),
        f'<tr><td>Strict-Transport-Security</td><td class="num">{_site.edge_hsts()}</td>',
    ]


def build() -> tuple[dict[str, str], list[str]]:
    data = _demo.answers()
    chart, sidereal = data["chart"], data["sidereal"]
    bounds, rows, differing = _bounds_rows(data)
    library = chart["library_info"]
    jpl, created = _site.ephemeris_header()
    obliquity = _demo.step(chart, "黃赤交角與章動 (swe.calc_ut ECL_NUT)")[1]
    hour = _demo.hour_summary()
    site = _site.product()
    if hour["width_seconds"] > site["transition_resolution_seconds"]:
        raise RuntimeError("the crossing window is wider than the product's stated resolution")
    tropical = chart["astronomical_data"]["angles"]["asc"]
    sidereal_asc = sidereal["astronomical_data"]["angles"]["asc"]
    ayanamsa = _demo.step(sidereal, "計算模式設定")[1]["ayanamsa數值(度)"]
    if abs((tropical - sidereal_asc) % 360 - ayanamsa) > 1e-6:
        raise RuntimeError("the two ascendants do not differ by the ayanamsa")
    sun = _demo.body(chart, "sun")
    houses = _site.product()["named"]["house_system"][0]
    if set(houses) != set(HOUSE_NAMES):
        raise RuntimeError(f"the request schema offers house systems {houses}")
    first, last = _site.product()["years"]
    if site["max_chart_bytes"] % 1024:
        raise RuntimeError("the chart request limit is not a whole number of KB")
    quoted = [
        f"這張盤的月亮在{_demo.zodiacal_minutes(_demo.body(chart, 'moon')['longitude'])}。",
        *_moon_versus(data),
        f"<b>{zh(rows)}顆星，{zh(differing)}顆的界主都會換。</b>",
        f"面／旬（{zh_quantity(_site.count('decan_profile'))}套）與三分性（{zh_quantity(_site.count('triplicity_profile'))}套）",
        f'<b class="vs-answer sm">{library["pyswisseph_distribution_version"]}</b>',
        f'<b class="vs-answer sm">{library["swiss_ephemeris_library_version"]}</b>',
        f"based on JPL {jpl}（{created} 建立）",
        f'這張盤是 <span class="mono">{_demo.dms(obliquity["真黃赤交角ε(度)"], 2)}</span>，'
        f'平值 <span class="mono">{_demo.dms(obliquity["平黃赤交角(度)"], 2)}</span> '
        f'加章動 <span class="mono">{obliquity["交角章動(度)"] * 3600:+.3f}″</span>',
        f"<b>{zh(len(hour['changed_classical']))}顆星的落宮會在同一個時刻附近一起換宮。"
        f"我們把那個時刻夾在 {site['transition_resolution_seconds']} 秒以內的區間裡。</b>",
        f"<div><b>{len(hour['changed_classical'])}</b><span>顆星的落宮同時改變</span></div>",
        f"<div><b>{hour['asc_range']:.2f}°</b><span>上升點在這一小時內取樣到的範圍</span></div>",
        f"做法是對整個小時取樣{zh(hour['probes'])}個時刻",
        f"月亮在每個取樣點都在{hour['moon_sign']}",
        f'<b class="vs-answer">{_demo.zodiacal(tropical, 1)}</b><span class="vs-src">黃經 {tropical:.6f}°</span>',
        f'<b class="vs-answer alt">{_demo.zodiacal(sidereal_asc, 1)}</b>'
        f'<span class="vs-src">黃經 {sidereal_asc:.6f}°</span>',
        f"兩者相差 <b>{_demo.dms(ayanamsa, 1)}</b>",
        f"黃道系統（回歸／{zh(_site.count('ayanamsa'))}種恆星）、"
        f"宮位制（{'／'.join(HOUSE_NAMES.values())}／不算宮位）",
        f'<b class="vs-answer sm">λ {_demo.dms(sun["longitude"], 2)}</b>'
        f'<span class="vs-src">β {_demo.signed_dms(sun["latitude"], 2)}</span>',
        f'<b class="vs-answer sm">α {_demo.hms(sun["right_ascension"], 2)}</b>'
        f'<span class="vs-src">δ {_demo.signed_dms(sun["declination"], 2)}</span>',
        f'<b class="vs-answer sm">Az {sun["azimuth"]:.3f}°</b>'
        f'<span class="vs-src">真高 {sun["altitude_true"]:.3f}°／視高 {sun["altitude_apparent"]:.3f}°</span>',
        f"{zh(_site.count('aspect_set_profile'))}套相位集合（預設{ASPECT_SET_DEFAULT[_site.default('aspect_set_profile')]}）、"
        f"{zh_quantity(_site.count('aspect_orb_profile'))}套具名容許度表（預設 {ORB_DEFAULT[_site.default('aspect_orb_profile')]}）",
        *_headers(),
        f"單次計算請求最大 {site['max_chart_bytes'] // 1024} KB；每個工作行程同時處理的頁面與資源請求最多 "
        f"{site['general_pool']} 個，計算請求另計、最多 {site['compute_pool']} 個。",
        f"<td>Swiss Ephemeris {library['swiss_ephemeris_library_version']}（套件與 C 函式庫版本分開輸出）</td>",
        f"<td>基於 JPL {jpl}</td>",
        f"<td>可計算年份</td><td>{first}–{last}</td>",
        f"<td>宮位制</td><td>{len(houses)} 種，另可完全不計算宮位</td>",
        f"<td>{_site.count('bounds_profile')} 套／{_site.count('decan_profile')} 套／"
        f"{_site.count('triplicity_profile')} 套，全部具名到作品與章節、行號或頁碼，全部無預設</td>",
        f"{_site.count('aspect_set_profile')} 套相位集合、{_site.count('aspect_orb_profile')} 套具名容許度表、"
        f"{_site.count('partile_profile')} 種同度判準",
        f"<td>出生時刻精度</td><td>{len(site['precisions'])} 種：",
    ]
    if any(_site.default(field) is not None for field in ("bounds_profile", "decan_profile", "triplicity_profile")):
        raise RuntimeError("a bounds, face or triplicity table has a default; the page says none has")
    return {"bounds-rows": bounds, "dossier-steps": _dossier_rows(chart)}, quoted
