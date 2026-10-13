"""法達（firdaria）：日夜盤決定的九段主星序列，與行星期的七等分夥伴。

期間（年）：太陽 10、金星 8、水星 13、月亮 9、土星 11、木星 12、火星 7、北交 3、南交 2，
合計 75 年後以同一序列重新開始（Bonatti Tr.9 Ch.3 對日盤明寫；夜盤「一切照日盤」）。

- 日盤序：日 金 水 月 土 木 火 北交 南交。
- 夜盤兩個具名 profile，請求選擇、收據照印：
  `abu_mashar_nodes_after_mercury_v1` 月 土 木 火 日 金 水 北交 南交；
  `bonatti_reading_nodes_after_mars_v1` 月 土 木 火 北交 南交 日 金 水。
  日盤的最後一顆行星本來就是火星，所以兩個 profile 在日盤完全相同（profile 照印，
  `nocturnal_node_profile_applies=false`）。「交點在土星後」不是任何具名版本，不做。
- 第二層：行星期七等分，第一個夥伴是本主，其餘依迦勒底序（土 木 火 日 金 水 月）往下；
  交點期不分（`node_period_not_subdivided`）。
- 年數以 `Fraction` 累加，邊界年數是精確有理數；換成瞬間由注入的 `instant_at_year`
  （年界產生器的 `SolarReturnClock.instant_at_year`）負責，這裡不做任何日期算術。
  所以第 7 個夥伴的終點與 L1 終點是同一個年數、同一個瞬間。
- 日夜盤不在這裡判定：呼叫端傳入 `lots.classify_sect` 的結果（唯一產生器）。
- 邊界只到日：原典只給年數，分秒是假精度；回應仍帶 `jd_ut` 供重算。
- 不輸出任何吉凶、主題或「與小限同星」之類的重合判斷；不以壽命設上限。
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction

from .source_reading import SOURCE_READING_LEVELS
from .time_utils import jd_ut_to_iso_utc
from .year_boundary import lifetime_window

FIRDARIA_PROFILE = "firdaria_small_periods_v1"
NOCTURNAL_NODE_PROFILES = (
    "abu_mashar_nodes_after_mercury_v1",
    "bonatti_reading_nodes_after_mars_v1",
)
DEFAULT_NOCTURNAL_NODE_PROFILE = NOCTURNAL_NODE_PROFILES[0]
_METHOD_PROVENANCE = {
    NOCTURNAL_NODE_PROFILES[0]: "persian_arabic_tradition_explicit_profile_abu_mashar_v1",
    NOCTURNAL_NODE_PROFILES[1]: "latin_transmission_interpretive_reading_of_bonatti_v1",
}
SCOPES = ("intersecting_year", "full_cycle", "lifetime_window")
NODE_PERIOD_NOT_SUBDIVIDED = "node_period_not_subdivided"
PERIOD_DISPLAY_PRECISION = "day"

PERIOD_YEARS: dict[str, int] = {
    "sun": 10, "venus": 8, "mercury": 13, "moon": 9, "saturn": 11,
    "jupiter": 12, "mars": 7, "north_node": 3, "south_node": 2,
}
CYCLE_YEARS = sum(PERIOD_YEARS.values())
DIURNAL_SEQUENCE = (
    "sun", "venus", "mercury", "moon", "saturn", "jupiter", "mars",
    "north_node", "south_node",
)
NOCTURNAL_SEQUENCES = {
    NOCTURNAL_NODE_PROFILES[0]: (
        "moon", "saturn", "jupiter", "mars", "sun", "venus", "mercury",
        "north_node", "south_node",
    ),
    NOCTURNAL_NODE_PROFILES[1]: (
        "moon", "saturn", "jupiter", "mars", "north_node", "south_node",
        "sun", "venus", "mercury",
    ),
}
CHALDEAN_ORDER = ("saturn", "jupiter", "mars", "sun", "venus", "mercury", "moon")
NODES = frozenset({"north_node", "south_node"})
if CYCLE_YEARS != 75:
    raise RuntimeError("the firdaria periods total 75 years")


def method_provenance(nocturnal_node_profile: str) -> str:
    return _METHOD_PROVENANCE[nocturnal_node_profile]


def sequence(is_day: bool, nocturnal_node_profile: str) -> tuple[str, ...]:
    if nocturnal_node_profile not in NOCTURNAL_SEQUENCES:
        raise ValueError(f"unknown nocturnal node profile {nocturnal_node_profile!r}")
    return DIURNAL_SEQUENCE if is_day else NOCTURNAL_SEQUENCES[nocturnal_node_profile]


def partners(lord: str) -> tuple[str, ...]:
    start = CHALDEAN_ORDER.index(lord)
    return tuple(CHALDEAN_ORDER[(start + step) % 7] for step in range(7))


def period_instant(instant: dict) -> dict:
    """A period boundary: day precision, with the JD kept for recomputation."""

    jd_ut = instant["jd_ut"]
    return {
        "jd_ut": jd_ut,
        "utc_time": None if jd_ut is None else jd_ut_to_iso_utc(jd_ut),
        "display_precision": PERIOD_DISPLAY_PRECISION,
        "status": instant["status"],
    }


def firdaria_periods(
    *,
    is_day: bool,
    nocturnal_node_profile: str,
    scope: str,
    completed_years: int,
    instant_at_year: Callable[[Fraction], dict],
) -> dict:
    """The periods the scope keeps around year N+1.

    `intersecting_year` keeps what meets [N, N+1); `full_cycle` the 75-year
    cycle that holds it; `lifetime_window` everything meeting the lifetime
    window (``year_boundary.lifetime_window``), across cycles.  A period id
    names its cycle (``C1.L1-3.L2-4``), so two cycles never share one.
    """

    if scope not in SCOPES:
        raise ValueError(f"unknown firdaria scope {scope!r}")
    lords = sequence(is_day, nocturnal_node_profile)
    cycle_index = completed_years // CYCLE_YEARS
    if scope == SCOPES[0]:
        window = (Fraction(completed_years), Fraction(completed_years + 1))
    elif scope == SCOPES[1]:
        window = (Fraction(cycle_index * CYCLE_YEARS), Fraction((cycle_index + 1) * CYCLE_YEARS))
    else:
        first, last = lifetime_window(completed_years)
        window = (Fraction(first), Fraction(last + 1))
    instants: dict[Fraction, dict] = {}

    def at(year: Fraction) -> dict:
        if year not in instants:
            instants[year] = period_instant(instant_at_year(year))
        return dict(instants[year])

    def meets_window(start: Fraction, end: Fraction) -> bool:
        return start < window[1] and end > window[0]

    periods = []
    first_cycle = int(window[0]) // CYCLE_YEARS
    last_cycle = (int(window[1]) - 1) // CYCLE_YEARS
    for cycle in range(first_cycle, last_cycle + 1):
        start = Fraction(cycle * CYCLE_YEARS)
        for index, lord in enumerate(lords, start=1):
            end = start + PERIOD_YEARS[lord]
            if meets_window(start, end):
                period_id = f"C{cycle}.L1-{index}"
                level_2 = None
                if lord not in NODES:
                    step = (end - start) / 7
                    level_2 = []
                    for sub_index, partner in enumerate(partners(lord), start=1):
                        sub_start = start + step * (sub_index - 1)
                        sub_end = end if sub_index == 7 else start + step * sub_index
                        if meets_window(sub_start, sub_end):
                            level_2.append({
                                "period_id": f"{period_id}.L2-{sub_index}",
                                "level": 2,
                                "cycle_index": cycle,
                                "level_2_partner": partner,
                                "start_year": float(sub_start),
                                "end_year": float(sub_end),
                                "start": at(sub_start),
                                "end": at(sub_end),
                            })
                periods.append({
                    "period_id": period_id,
                    "level": 1,
                    "cycle_index": cycle,
                    "level_1_lord": lord,
                    "start_year": float(start),
                    "end_year": float(end),
                    "start": at(start),
                    "end": at(end),
                    "level_2": level_2,
                    "level_2_reason_code": NODE_PERIOD_NOT_SUBDIVIDED if lord in NODES else None,
                })
            start = end
    return {
        "nocturnal_node_profile": nocturnal_node_profile,
        "nocturnal_node_profile_applies": not is_day,
        "method_provenance": method_provenance(nocturnal_node_profile),
        "scope": scope,
        "cycle_index": cycle_index,
        "periods": periods,
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "firdaria": {
        "applies_to": "annual_methods.firdaria",
        "profile": FIRDARIA_PROFILE,
        "period_years": dict(PERIOD_YEARS),
        "diurnal_sequence": list(DIURNAL_SEQUENCE),
        "nocturnal_sequences": {key: list(value) for key, value in NOCTURNAL_SEQUENCES.items()},
        "level_2_rule": (
            "a planet's period is cut into seven equal parts; the first partner is "
            "the period lord, the rest follow the Chaldean order (Saturn, Jupiter, "
            "Mars, Sun, Venus, Mercury, Moon); node periods are not subdivided"
        ),
        "cycle_rule": (
            "after 75 years the same sequence starts again: explicit in Bonatti Tr.9 "
            "Ch.3 for the diurnal sequence (after the South Node it returns to the Sun "
            "and runs on in order); the nocturnal sequence follows the diurnal one, "
            "since Bonatti says 'all as for the day'"
        ),
        "method_provenance": dict(_METHOD_PROVENANCE),
        "sources": [
            {
                "citation": (
                    "Abu Ma'shar, On the Revolutions of the Years of Nativities, tr. B. Dykes, "
                    "Persian Nativities IV (2019); Latin abridgement in Persian Nativities III (2010)"
                ),
                "says": (
                    "the fullest surviving operational account per the research notes, "
                    "nocturnal nodes after Mercury; chapter located as PN IV IV.8 via secondary "
                    "sources"
                ),
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "secondary sources and the research notes; the book not consulted",
            },
            {
                "citation": (
                    "al-Biruni, Book of Instruction in the Elements of the Art of Astrology "
                    "§438-439 (tr. R. R. Wright, 1934, p.48)"
                ),
                "says": (
                    "the table of periods and sequences; the nodes, 3 and 2 years for day and "
                    "night alike, follow the seven planets, so by night they come after "
                    "Mercury; the nodes have no sub-periods"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Wright's English translation, the scanned 1934 printing",
            },
            {
                "citation": "al-Qabisi, Introduction",
                "says": (
                    "an abridged nocturnal sequence, named by the research notes as the source "
                    "of the Latin divergence"
                ),
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "the research notes only; not verified",
            },
            {
                "citation": "Bonatti, Liber astronomiae Tr.9 Ch.3 (tr. B. Dykes, 2007)",
                "says": (
                    "the periods, the diurnal sequence and the return after 75 years; for the "
                    "night the text starts from the Moon and says 'all as for the day'; "
                    "nocturnal nodes after Mars is Zoller's reading, not Bonatti's words"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Dykes's English translation",
            },
            {
                "citation": "Schoener (Renaissance)",
                "says": "keeps the nodes-last order",
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "the research notes only; not verified",
            },
        ],
        "naming_note": (
            "Neither nocturnal profile is marked the only correct one; the "
            "provenance says 'tradition, explicit profile per Abu Ma'shar', not that "
            "Abu Ma'shar invented the technique."
        ),
    },
}
