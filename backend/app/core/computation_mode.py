"""統一「計算模式」設定：一次設定、套用到所有天體計算。

包含：計算中心 (geo/topo/helio/bary)、黃道系統 (tropical/sidereal + ayanamsa)、
視位置/真位置、當日黃道/J2000、章動開關。這裡只負責組出 swisseph flags 與判斷
「地平座標/日夜盤等仰賴地平系統的資料在目前模式下是否仍有意義」，實際計算呼叫仍在
各自的 core 模組內進行。
"""

import math

import swisseph as swe

from ..domain_catalog import AYANAMSA_OPTIONS
from ..ephemeris import configure_chart_swiss_state
from .trace import Trace

CENTER_FLAGS = {
    "geocentric": 0,
    "topocentric": swe.FLG_TOPOCTR,
    "heliocentric": swe.FLG_HELCTR,
    "barycentric": swe.FLG_BARYCTR,
}


class ComputationContext:
    def __init__(self, mode, location):
        self.mode = mode
        self.location = location
        self.base_flags = swe.FLG_SWIEPH | swe.FLG_SPEED | CENTER_FLAGS[mode.center]

        if mode.zodiac == "sidereal":
            self.base_flags |= swe.FLG_SIDEREAL
        if mode.position_mode == "true":
            self.base_flags |= swe.FLG_TRUEPOS
        if mode.ecliptic_frame == "j2000":
            self.base_flags |= swe.FLG_J2000
        if not mode.nutation:
            self.base_flags |= swe.FLG_NONUT

        # 地平座標一律以出生地觀測者為原點（見 horizontal_source_flags），
        # 所以不論計算中心為何都要先登記測站。
        configure_chart_swiss_state(
            geopos=(location.longitude, location.latitude, location.altitude_m),
            sid_mode=(
                AYANAMSA_OPTIONS[mode.ayanamsa] if mode.zodiac == "sidereal" else None
            ),
        )

    @property
    def horizon_meaningful(self) -> bool:
        """地平座標(方位角/高度)、日夜盤、月空亡、阿拉伯點等仰賴「觀測者站在地表看天空」這個前提，
        在 heliocentric/barycentric 模式下沒有物理意義，故回傳 False 時應輸出 null 並註明原因。"""
        return self.mode.center in ("geocentric", "topocentric")

    @property
    def horizontal_source_flags(self) -> int:
        """Return physical-sky flags for the ecliptic input consumed by ``swe.azalt``.

        Sidereal zodiac, J2000, and mean (no-nutation) coordinates are output
        reference-frame choices. Feeding any of them to ``ECL2HOR`` would
        incorrectly rotate the observer's physical sky, because Swiss expects
        true tropical ecliptic coordinates of date at that boundary.
        True/apparent position remains an intentional physical choice.

        The horizon is an observer-on-the-surface concept, so the input is
        always topocentric whatever the display center: the rise/set premise,
        one horizon per response.  For the Moon the difference reaches a degree;
        for the Sun and planets it is seconds of arc.
        """
        return (
            self.base_flags
            & ~swe.FLG_SIDEREAL
            & ~swe.FLG_J2000
            & ~swe.FLG_NONUT
        ) | swe.FLG_TOPOCTR

    HORIZONTAL_COORDINATE_ORIGIN = "topocentric_observer_diurnal_parallax_applied"

    @property
    def equatorial_source_flags(self) -> int:
        """Return flags for RA/Dec without applying a sidereal-zodiac offset.

        Sidereal/tropical is a convention for ecliptic longitude, not a second
        definition of right ascension. J2000 and no-nutation remain available
        because they explicitly select the equatorial reference frame.
        """
        return self.base_flags & ~swe.FLG_SIDEREAL

    def ayanamsa_value(self, jd_ut: float):
        """回傳**本次計算實際套用**的 ayanamsa，供收據與 antiscia.py 使用（houses.py 不用它，見下）。

        這裡回傳的必須是實際套用值，不是 `get_ayanamsa_ut()`：後者是相對**平**
        春分點定義的傳統數值；`calc_ut(FLG_SIDEREAL)` 在章動開啟時輸出的恆星黃經卻是
        相對**真**春分點。兩者相差恰為當下的黃經章動（實測 ±17.4 角秒內）。

        這個差不能當作「遠小於容許誤差」的殘差略過：`astronomical_data.time.ayanamsa`
        宣稱的是本次從星體黃經扣掉的量，第三方拿平春分點值複算會差最多 17.4 角秒——
        那是可追溯性宣稱本身出錯，不是精度問題。

        `get_ayanamsa_ex_ut(jd, base_flags)` 回傳的正是同一組旗標下實際套用的值：實測與
        「同天體同時刻、同一章動設定的 tropical 減 sidereal 黃經」差 0.000000 角秒，章動開
        與關都成立（章動關時兩邊都相對平春分點）。收據與 antiscia 的 2×ayanamsa 因此為真。

        宮頭不能用它換算：`swe.houses_ex` 沒有平春分點框架，它的 tropical 宮頭永遠相對真
        春分點；章動關時「tropical 宮頭 − 本值」會差一個黃經章動（≤ 約 17″），落宮是硬邊界
        分類，那就是一個約一秒出生時刻的翻宮窗。所以 `houses.py` 對每一種宮位制都直接呼叫
        `houses_ex(..., FLG_SIDEREAL)`；Swiss 對恆星黃道不理會 `FLG_NONUT`，宮頭與天體黃經
        在章動開或關時都相同，同一時刻與地點只有一個 ASC。

        此處選擇「回報並套用同一個實際值」，不創設任何占星慣例。

        上述「差 0.000000 角秒」只在當日黃道框架成立（四種 ayanamsa × 章動開關）。
        恆星黃道＋J2000 下，本值與實際扣除量實測相差 3.25e-3 度（密切交點 0.13 度），
        故該組合在請求邊界以 422 拒絕（`frame_compatibility.request_frame_refusal`），
        不會走到這裡。
        """
        if self.mode.zodiac != "sidereal":
            return None
        # 第二個回傳值才是 ayanamsa；第一個是回傳碼。
        return swe.get_ayanamsa_ex_ut(jd_ut, self.base_flags)[1]

    def describe(self, trace: Trace, jd_ut: float):
        ayan = self.ayanamsa_value(jd_ut)
        trace.add(
            "計算模式設定",
            formula="套用於本次所有天體計算的統一旗標",
            inputs={
                "計算中心": self.mode.center,
                "黃道系統": self.mode.zodiac,
                "ayanamsa": self.mode.ayanamsa if self.mode.zodiac == "sidereal" else "-",
                "位置": self.mode.position_mode,
                "黃道參考框架": self.mode.ecliptic_frame,
                "章動": "on" if self.mode.nutation else "off",
            },
            result={
                "requested_flags": self.base_flags,
                "ayanamsa數值(度)": ayan,
            },
        )


_AU_LIGHT_DAYS = 499.004783836 / 86400.0  # light time for one astronomical unit, in days


def _xyz_to_polar(x: float, y: float, z: float) -> tuple[float, float, float]:
    distance = math.sqrt(x * x + y * y + z * z)
    longitude = math.degrees(math.atan2(y, x)) % 360.0
    latitude = math.degrees(math.asin(z / distance))
    return longitude, latitude, distance


def _orthonormal_triad(a, b):
    def unit(v):
        n = math.sqrt(sum(x * x for x in v))
        return [x / n for x in v]

    def cross(u, v):
        return [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]

    first = unit(a)
    second = unit(cross(first, b))
    return first, second, cross(first, second)


def _turn_into_frame_at(jd_ut: float, vector, source_flags: int, target_flags: int):
    """Turn a vector from Swiss's ``source_flags`` frame into its ``target_flags`` frame at jd_ut.

    Swiss applies one rotation (precession, nutation, ayanamsa, equator) to
    every body at an instant, so two reference bodies seen in both frames fix
    it.  Of the Earth, Jupiter and Saturn the pair furthest from parallel is used.
    """
    references = [
        (swe.calc_ut(jd_ut, body, source_flags)[0][:3], swe.calc_ut(jd_ut, body, target_flags)[0][:3])
        for body in (swe.EARTH, swe.JUPITER, swe.SATURN)
    ]

    def separation(pair):
        (a, _), (b, _) = pair
        cosine = sum(a[i] * b[i] for i in range(3)) / math.sqrt(
            sum(x * x for x in a) * sum(x * x for x in b))
        return abs(cosine)

    first, second = min(
        ((references[i], references[j]) for i in range(3) for j in range(i + 1, 3)), key=separation)
    source = _orthonormal_triad(first[0], second[0])
    target = _orthonormal_triad(first[1], second[1])
    coordinates = [sum(axis[i] * vector[i] for i in range(3)) for axis in source]
    return [sum(coordinates[k] * target[k][i] for k in range(3)) for i in range(3)]


def heliocentric_apparent_calc_ut(jd_ut: float, body_id: int, flags: int) -> tuple[tuple, int]:
    """A heliocentric apparent position with light time measured from the Sun.

    Definition: the body is placed where it was at t - tau, the Sun where it is
    at t, and tau is the Sun-body distance at t - tau divided by c (iterated to
    convergence).  No aberration or light deflection is applied, as for Swiss
    heliocentric output.  Swiss's own apparent heliocentric output takes its
    light time from the barycentric distance, which is up to about one
    arcsecond off for Mercury.

    Positions come from Swiss geometric (``FLG_TRUEPOS``) vectors in the fixed
    J2000 frame, turned at the end into the frame the flags request at t.  An
    of-date frame read at t - tau would carry precession and nutation of the
    light-time interval (about 0.05" for Neptune, 0.08" for Pluto).  Speeds
    are Swiss's own apparent heliocentric speeds, which differ from these by a
    negligible amount.  Returns the same shape as ``swe.calc_ut``.
    """
    swiss_apparent, retflag = swe.calc_ut(jd_ut, body_id, flags)
    requested = (flags | swe.FLG_TRUEPOS | swe.FLG_XYZ) & ~swe.FLG_SPEED
    geometric = (requested & ~swe.FLG_SIDEREAL) | swe.FLG_J2000 | swe.FLG_NONUT
    bary = (geometric & ~swe.FLG_HELCTR) | swe.FLG_BARYCTR
    sun_now = swe.calc_ut(jd_ut, swe.SUN, bary)[0]
    tau = 0.0
    for _ in range(4):
        planet_helio = swe.calc_ut(jd_ut - tau, body_id, geometric)[0]
        sun_then = swe.calc_ut(jd_ut - tau, swe.SUN, bary)[0]
        # P(t-tau) - S(t) = [P(t-tau) - S(t-tau)] - [S(t) - S(t-tau)]
        vector = [planet_helio[i] - (sun_now[i] - sun_then[i]) for i in range(3)]
        tau = _xyz_to_polar(*vector)[2] * _AU_LIGHT_DAYS
    if requested != geometric:
        vector = _turn_into_frame_at(jd_ut, vector, geometric, requested)
    if flags & swe.FLG_XYZ:
        position = tuple(vector)
    else:
        position = _xyz_to_polar(*vector)
    return position + tuple(swiss_apparent[3:6]), retflag


def uses_sun_centre_light_time(ctx) -> bool:
    return ctx.mode.center == "heliocentric" and ctx.mode.position_mode == "apparent"
