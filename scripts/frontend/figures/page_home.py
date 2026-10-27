"""The home page: the demonstration chart's numbers and the counts it states, from the product's own answers."""
from __future__ import annotations

from . import _demo, _site
from ._common import zh, zh_quantity

FRAGMENT = "home"
# Trace steps the page prints: (product step title, page name, call shorthand, result).
STEPS = (
    ("本地時間 -> UTC", "本地時間 → UTC", "UTC ＝ 本地時間 − 時區偏移", lambda r: r["UTC時間"]),
    ("UTC -> 儒略日 (swe.utc_to_jd)", "UTC → 儒略日", "<code>swe.utc_to_jd(年,月,日,時,分,秒, 格里曆)</code>",
     lambda r: f"JD(UT) {r['JD(UT)']:.7f}"),
    ("地球時與世界時之差 ΔT", "地球時與世界時之差", "ΔT（地球自轉與均勻時間的差）＝ <code>swe.deltat_ex(JD_UT)</code> × 86400 秒", lambda r: f"{r['ΔT(秒)']:.4f} 秒"),
    ("黃赤交角與章動 (swe.calc_ut ECL_NUT)", "黃赤交角與章動", "<code>swe.calc_ut(JD_UT, ECL_NUT)</code>",
     lambda r: f"真 ε {_demo.dms(r['真黃赤交角ε(度)'], 2)}"),
    ("平均／視恆星時 (Sidereal Time)", "地方真恆星時", "LAST ＝ <code>swe.sidtime(JD_UT)</code> ＋ 東經 ÷ 15",
     lambda r: f"{r['LAST(小時)']:.7f} 小時"),
)
ZODIAC = {"tropical": "回歸黃道", "sidereal": "恆星黃道"}
POSITION = {"apparent": "視位置", "true": "真位置"}
CENTER = {"geocentric": "地心", "topocentric": "站心"}
HOUSES = {"W": "整宮制"}

def _trace_rows(chart: dict) -> tuple[str, int, int]:
    rows, numbers = [], []
    for i, (title, label, formula, result) in enumerate(STEPS):
        number, values = _demo.step(chart, title)
        numbers.append(number)
        mark = ' class="mark"' if i == len(STEPS) - 1 else ""
        rows.append(f"          <tr{mark}><td>{number:03d}</td><td>{label}</td><td>{formula}</td>"
                    f"<td>{result(values)}</td></tr>")
    if numbers != list(range(numbers[0], numbers[0] + len(numbers))):
        raise RuntimeError(f"the excerpted trace steps are not consecutive: {numbers}")
    return "\n".join(rows), numbers[0], numbers[-1]

def _half_minutes(minutes: float) -> str:
    """「四分半鐘」: to the nearest half minute."""
    halves = round(minutes * 2)
    return f"{zh(halves // 2)}分{'半' if halves % 2 else ''}鐘"

def _teens(seconds: int) -> str:
    if not 10 <= seconds < 20:
        raise RuntimeError(f"the crossing window is {seconds} s, which 「十幾秒」 does not describe")
    return "十幾"

def _plate_inputs(epsilon: float) -> None:
    """The caption says both ecliptic obliquity and horizon latitude are true values."""
    from scripts.frontend import gen_armillary
    latitude = _demo.DEMO["location"]["latitude"]
    if abs(gen_armillary.EPS - epsilon) > 5e-8 or gen_armillary.PHI != round(latitude, 3):
        raise RuntimeError(f"the armillary plate draws ε={gen_armillary.EPS}, φ={gen_armillary.PHI}; "
                           f"the chart has ε={epsilon}, φ={latitude}")

def build() -> tuple[dict[str, str], list[str]]:
    data = _demo.answers()
    chart, sidereal = data["chart"], data["sidereal"]
    trace, first, last = _trace_rows(chart)
    epsilon = _demo.step(chart, "黃赤交角與章動 (swe.calc_ut ECL_NUT)")[1]["真黃赤交角ε(度)"]
    _plate_inputs(epsilon)
    ayanamsa = _demo.step(sidereal, "計算模式設定")[1]["ayanamsa數值(度)"]
    when, where, mode = _demo.DEMO["datetime"], _demo.DEMO["location"], chart["computation_mode"]
    hour = _demo.hour_summary()
    rate = hour["span_seconds"] / 60 / hour["asc_range"]
    quoted = [
        f"傾角 ε＝{_demo.dms(epsilon, 2)}，取這一刻的真黃赤交角",
        f"{when['year']}-{when['month']:02d}-{when['day']:02d} {when['hour']:02d}:{when['minute']:02d} 臺北"
        f"（{where['latitude']:.4f}°N {where['longitude']:.4f}°E），{HOUSES[_demo.DEMO['options']['house_system']]}、"
        f"{ZODIAC[mode['zodiac']]}、{POSITION[mode['position_mode']]}、{CENTER[mode['center']]}。",
        f"上升 ASC　<b>{_demo.zodiacal(chart['astronomical_data']['angles']['asc'], 1)}</b>",
        f"上升 ASC　<b>{_demo.zodiacal(sidereal['astronomical_data']['angles']['asc'], 1)}</b>",
        f"扣掉歲差 {_demo.dms(ayanamsa, 1)}（Fagan–Bradley）",
        f"這是那次計算的第 {first:03d}–{last:03d} 步，依卷宗整理。",
        f"上升點<b>每{_half_minutes(rate)}移動約一度</b>",
        f"那一小時裡它會走過 {hour['asc_range']:.2f}°",
        f"整宮制下<b>{zh(len(hour['changed']))}個天體的落宮同時改變</b>",
        f"翻面卡在哪{_teens(hour['width_seconds'])}秒之間",
        f"{zh(hour['probes'])}個刻度是後端實際取樣的時刻",
        f"宮位分割<em>{zh(_site.count('house_system'))}種，或不算宮位</em>",
    ]
    return {"trace-steps": trace}, quoted

def elsewhere(fragment: str) -> dict[str, list[str]]:
    return {"about": [
        f"<b>{zh(_site.count('bounds_profile'))}套具名界表、{zh_quantity(_site.count('decan_profile'))}套面／旬、"
        f"{zh(_site.count('triplicity_profile'))}套三分性</b>",
    ]}
