"""年界：第 N 次太陽回歸瞬間是「一年」的唯一產生器（`solar_return_root_v1`）。

年度小限的年界、法達期間的瞬間與年度路由的窗口都讀這裡，不各自做民用日期算術：
「第 N+1 年」= [SR_N, SR_{N+1})，SR_0 是出生瞬間本身。2 月 29 日出生、生日前後一日等
問題因此不存在（回歸瞬間自己落在哪一天就是哪一天）。

## 事件層

SR_N 是出生後太陽黃經第 N 次回到本命太陽黃經的瞬間。目標黃經與搜尋函數用同一個取樣
函式（呼叫端以 ``bodies.make_longitude_sampler`` 給出，旗標即本命星體黃經的旗標），所以
不可能出現「本命用視位置、回歸用真位置」這種旗標不一致（實測會差約 507 秒）。

求根器是產品自己的 ``two_stage_scan_then_bisection_v1``：以 t₀ = 出生 + N × 平均年為中心、
寬 6 日的視窗粗掃 0.5 日，二分到 1e-9 日。平均年依黃道取回歸年 365.24219 日或恆星年
365.256363 日，只決定**在哪裡找**，不進入任何結果；恆星黃道若也用回歸年，根每年晚約
20 分鐘，約 211 年後就漂出 ±3 日的視窗。地心太陽黃經不逆行，視窗內應恰好一根；根數
不是 1 時不挑一根，回報 ``solar_return_root_count_unexpected``。

## 黃道

回歸跟著 computation_mode：恆星黃道的回歸是恆星年，每年晚約 20 分鐘（30 年約晚 10.3
小時）。J2000、章動關與非地心由年度路由在請求邊界拒絕（frame_compatibility），不會走到
這裡；所以 profile 只有黃道（回歸／恆星）× 位置（視／真）四個值。

## 非整數年

法達子期是 L1/7 年這類非整數年。第 y 年（y = k + f，0 ≤ f < 1）對應瞬間
SR_k + f × (SR_{k+1} − SR_k)：在**所屬的回歸年內**線性內插（產品計算慣例，
``solar_return_root_linear_within_year_v1``）。整數年直接取 SR_k，與年界逐位元相等。
年數以 ``Fraction`` 傳入，整數判定不受浮點誤差影響。

## 年份範圍

產品年份範圍 1900–2399（``PRODUCT_YEAR_RANGE``）。視窗完全在 2400-01-01 之後就不呼叫
Swiss，直接回報 ``outside_supported_year_range``；找到的根若在 2400-01-01 之後也一樣。
視窗最遠到 2400-01-07，仍在星曆段（到 2400-01-10）之內。
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from functools import cache

import swisseph as swe

from ..config import PRODUCT_YEAR_RANGE
from .root_finding import SOLVER_NAME, find_crossings_detailed, wrap_to_signed_180
from .source_reading import SOURCE_READING_LEVELS
from .time_utils import jd_ut_to_iso_utc, time_scale_for_jd_ut

YEAR_BOUNDARY_DEFINITION = "solar_return_root_v1"
FRACTIONAL_YEAR_RULE = "solar_return_root_linear_within_year_v1"
INSTANT_STATUSES = (
    "computed",
    "outside_supported_year_range",
    "solar_return_root_count_unexpected",
)
COMPUTED, OUTSIDE_RANGE, ROOT_COUNT_UNEXPECTED = INSTANT_STATUSES
BOUNDARY_START_KINDS = ("birth_instant", "solar_return")

SOLAR_RETURN_PROFILES = tuple(
    f"solar_return_{zodiac}_geocentric_{position}_of_date_v1"
    for zodiac in ("tropical", "sidereal")
    for position in ("apparent", "true")
)

# Where the search looks, never what it finds: the mean year of the zodiac the
# return is measured in (the sidereal year is ~20.4 min longer, which a window
# placed by the tropical year loses after about 211 returns).
SEARCH_CENTRE_DAYS_PER_YEAR = {"tropical": 365.24219, "sidereal": 365.256363}
SEARCH_WINDOW_DAYS = 6.0
COARSE_STEP_DAYS = 0.5
TOLERANCE_DAYS = 1e-9

RANGE_END_JD_UT = swe.julday(PRODUCT_YEAR_RANGE[1] + 1, 1, 1, 0.0)

# A solar month: the Sun's 30-degree steps from its natal longitude inside one
# return year (the monthly profection's boundaries).  The Sun's speed runs
# about 0.95-1.02 degrees a day, and the gains add up over half a year, so a
# step lands up to 3.9 days from the year's twelfth; twelve days (+-6) holds
# that crossing with two days to spare, and no other, since the Sun never
# turns back and needs a year to reach the same longitude again.
SOLAR_MONTH_RULE = "sun_30_degree_steps_from_natal_longitude_v1"
SOLAR_MONTH_WINDOW_DAYS = 12.0


def solver_receipt(zodiac: str) -> dict:
    """The search recipe for returns measured in `zodiac`."""

    return {
        "name": SOLVER_NAME,
        "window_days": SEARCH_WINDOW_DAYS,
        "window_centre": f"birth_plus_n_times_{SEARCH_CENTRE_DAYS_PER_YEAR[zodiac]}_days",
        "coarse_step_days": COARSE_STEP_DAYS,
        "tolerance_days": TOLERANCE_DAYS,
    }


# The span a lifetime view lists: completed years 0-99, or the hundred return
# years ending with the requested one when that is later.  A display span, not
# a lifespan: a later year is listed by asking for it.
LIFETIME_WINDOW_RULE = "hundred_return_years_v1"
LIFETIME_WINDOW_YEARS = 100


def lifetime_window(completed_years: int) -> tuple[int, int]:
    """(first, last) completed years of the lifetime window holding year N+1."""

    last = max(LIFETIME_WINDOW_YEARS - 1, completed_years)
    return last - (LIFETIME_WINDOW_YEARS - 1), last


def solar_return_profile(mode) -> str:
    profile = f"solar_return_{mode.zodiac}_geocentric_{mode.position_mode}_of_date_v1"
    if profile not in SOLAR_RETURN_PROFILES:
        raise ValueError(f"no solar return profile for {profile}")
    return profile


def _unavailable(status: str) -> dict:
    return {"status": status, "jd_ut": None}


class SolarReturnClock:
    """SR_k for one birth, found once and read by every annual technique.

    ``sun_longitude_at(jd_ut)`` is the Sun's longitude in the request's frame;
    ``natal_sun_longitude`` must be that same function at the birth instant (the
    caller passes the emitted body longitude, which is that value). ``zodiac`` is
    that frame's zodiac; it places the search window and nothing else.

    The searches ask for each Sun instant once per clock: each root is rescanned
    and bisected again at every refinement depth on grids that share points,
    which without the cache doubles the Swiss calls.  The longitude is a pure
    function of the instant under the request's fixed flags, so the cache cannot
    change a result; a refused position raises and is not cached.
    """

    def __init__(
        self,
        *,
        birth_jd_ut: float,
        natal_sun_longitude: float,
        sun_longitude_at: Callable[[float], float],
        zodiac: str,
    ) -> None:
        self.birth_jd_ut = birth_jd_ut
        self.natal_sun_longitude = natal_sun_longitude
        self._sun_longitude_at = cache(sun_longitude_at)
        self._days_per_year = SEARCH_CENTRE_DAYS_PER_YEAR[zodiac]
        self._receipt = solver_receipt(zodiac)
        self._roots: dict[int, dict] = {0: {"status": COMPUTED, "jd_ut": birth_jd_ut}}
        self._solver: dict[int, dict | None] = {}
        self._months: dict[tuple[int, int], dict] = {}

    def root(self, n: int) -> dict:
        """``{"status", "jd_ut"}`` of SR_n; n = 0 is the birth instant."""

        if n < 0:
            raise ValueError("return numbers start at 0")
        if n not in self._roots:
            self._roots[n] = self._search(n)
        return dict(self._roots[n])

    def solver_record(self, n: int) -> dict | None:
        """The search evidence for SR_n (n ≥ 1) when a search ran."""

        self.root(n)
        record = self._solver.get(n)
        return None if record is None else dict(record)

    def _search(self, n: int) -> dict:
        window_start = (
            self.birth_jd_ut
            + n * self._days_per_year
            - SEARCH_WINDOW_DAYS / 2.0
        )
        found, self._solver[n] = self._crossing(
            self.natal_sun_longitude, window_start, SEARCH_WINDOW_DAYS)
        return found

    def _crossing(
        self, target: float, window_start: float, window_days: float,
    ) -> tuple[dict, dict | None]:
        """The one instant in the window where the Sun's longitude is `target`,
        with its search evidence (None when no search ran)."""

        if window_start >= RANGE_END_JD_UT:
            return _unavailable(OUTSIDE_RANGE), None

        def offset_at(t: float) -> float:
            return wrap_to_signed_180(self._sun_longitude_at(window_start + t) - target)

        records = find_crossings_detailed(
            offset_at,
            window_days=window_days,
            coarse_step_days=COARSE_STEP_DAYS,
            tolerance_days=TOLERANCE_DAYS,
        )
        if len(records) != 1:
            return _unavailable(ROOT_COUNT_UNEXPECTED), {**self._receipt, "roots_in_window": len(records)}
        record = records[0]
        jd_ut = window_start + record["t"]
        bracket = record["bracket"]
        evidence = {
            **self._receipt,
            "roots_in_window": 1,
            "bracket_jd_ut": [
                window_start + bracket["low_days"],
                window_start + bracket["high_days"],
            ],
            "iterations": record["iterations"],
            "residual_arcsec": record["residual_degrees"] * 3600.0,
        }
        if jd_ut >= RANGE_END_JD_UT:
            return _unavailable(OUTSIDE_RANGE), evidence
        return {"status": COMPUTED, "jd_ut": jd_ut}, evidence

    def sun_advanced(self, n: int, steps: int) -> dict:
        """``{"status", "jd_ut"}``: the instant in return year n+1 when the Sun
        has moved ``steps`` × 30° past its natal longitude (rule
        SOLAR_MONTH_RULE).  Steps 0 and 12 are SR_n and SR_n+1 themselves.

        The window is centred on the year's own twelfth (or the mean year's
        when SR_n+1 cannot be dated) and is wide enough for the Sun's uneven
        speed, which puts a 30° step up to 3.9 days off the twelfth (an early
        April return at the 1900 eccentricity); like the return search, the
        centre only places the search.
        """

        if not 0 <= steps <= 12:
            raise ValueError("a return year has twelve 30-degree steps")
        if steps == 0:
            return self.root(n)
        if steps == 12:
            return self.root(n + 1)
        key = (n, steps)
        if key not in self._months:
            start, end = self.root(n), self.root(n + 1)
            if start["status"] != COMPUTED:
                self._months[key] = dict(start)
            else:
                length = (
                    end["jd_ut"] - start["jd_ut"] if end["status"] == COMPUTED
                    else self._days_per_year
                )
                centre = start["jd_ut"] + steps * length / 12
                target = (self.natal_sun_longitude + 30.0 * steps) % 360.0
                self._months[key], _ = self._crossing(
                    target, centre - SOLAR_MONTH_WINDOW_DAYS / 2.0, SOLAR_MONTH_WINDOW_DAYS)
        return dict(self._months[key])

    def instant_at_year(self, year: Fraction) -> dict:
        """The instant `year` return-years after birth (rule FRACTIONAL_YEAR_RULE)."""

        year = Fraction(year)
        if year < 0:
            raise ValueError("years after birth start at 0")
        whole = year.numerator // year.denominator
        fraction = year - whole
        start = self.root(whole)
        if fraction == 0 or start["status"] != COMPUTED:
            return start
        end = self.root(whole + 1)
        if end["status"] != COMPUTED:
            return end
        return {
            "status": COMPUTED,
            "jd_ut": start["jd_ut"] + float(fraction) * (end["jd_ut"] - start["jd_ut"]),
        }


def instant_receipt(jd_ut: float) -> dict:
    """A boundary instant with the time-scale facts a reader needs to recompute it."""

    delta_t_days = swe.deltat_ex(jd_ut, swe.FLG_SWIEPH)
    return {
        "jd_ut": jd_ut,
        "jd_et": jd_ut + delta_t_days,
        "delta_t_seconds": delta_t_days * 86400.0,
        "utc_time": jd_ut_to_iso_utc(jd_ut),
        "time_scale": time_scale_for_jd_ut(jd_ut),
    }


def year_boundary_record(clock: SolarReturnClock, *, completed_years: int) -> dict:
    """[SR_N, SR_{N+1}) for N completed years, with its definition."""

    start = clock.root(completed_years)
    end = clock.root(completed_years + 1)
    return {
        "definition": YEAR_BOUNDARY_DEFINITION,
        "completed_years": completed_years,
        "year_of_life": completed_years + 1,
        "start_kind": BOUNDARY_START_KINDS[0 if completed_years == 0 else 1],
        "start_status": start["status"],
        "start": None if start["jd_ut"] is None else instant_receipt(start["jd_ut"]),
        "end_status": end["status"],
        "end": None if end["jd_ut"] is None else instant_receipt(end["jd_ut"]),
        "solver": clock.solver_record(completed_years + 1),
    }


# Entries of the published method source register; the annual route's
# responses name that register, as /api/chart's do.
METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    "year_boundary": {
        "applies_to": "year_boundary",
        "definition": YEAR_BOUNDARY_DEFINITION,
        "fractional_year_rule": FRACTIONAL_YEAR_RULE,
        "method_provenance": "product_convention_shared_by_profections_and_firdaria",
        "statement": (
            "Year N+1 of life is [SR_N, SR_N+1): from the N-th solar return to the next, "
            "SR_0 being the birth instant. A non-whole year y = k + f is SR_k + f (SR_k+1 "
            "- SR_k), linear inside its own return year (product convention). The search "
            "window is centred on birth + N mean years (365.24219 days tropical, 365.256363 "
            "days sidereal); that number places the search and enters no result."
        ),
        "other_year_models_not_used": [
            "mean tropical year of 365.2422 days: differs from the return root by up "
            "to 1.57 h within 100 years (four synthetic births, Swiss Ephemeris)",
            "civil anniversary (same UTC date and clock time): differs from the return "
            "root by up to 21.8 h within 100 years (same probe)",
            "360-day year: a period unit inside zodiacal releasing, not a year boundary",
        ],
        "measurement_note": (
            "The differences above are Swiss-on-Swiss magnitudes for the method page, "
            "not an independent check; the return instant itself is checked against JPL "
            "Horizons (DE441) in the test suite."
        ),
        "frame_note": (
            "The return instant is defined on the ecliptic of date of the ephemeris "
            "library's default precession model. Defining it with the IAU 1976 "
            "precession instead would move the instant by about 5 seconds over 63 years "
            "(measured by the test suite's oracle: 4.7 s for a return in 1963 of a 1900 "
            "birth)."
        ),
        "sources": [
            {
                "citation": (
                    "Abu Ma'shar, On the Revolutions of the Years of Nativities, tr. B. Dykes, "
                    "Persian Nativities IV (2019)"
                ),
                "says": "revolutions used together with profections and firdaria",
                "reading": SOURCE_READING_LEVELS[3],
                "read_at": "bibliographic record only; chapter and page not verified",
            },
            {
                "citation": "Swiss Ephemeris 2.10.03 swe_solcross_ut",
                "says": (
                    "the crossing the test suite compares the product's own search against "
                    "(same engine, another algorithm)"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the library's source code and documentation",
            },
        ],
    },
    "solar_return_chart": {
        "applies_to": "solar_return_chart",
        "method_provenance": "Persian and Arabic revolution tradition and its Latin heirs",
        "statement": (
            "The chart cast at SR_N, the instant the Sun returns to its natal ecliptic "
            "longitude (year_boundary), for the birth place, in the house system the "
            "natal chart uses, with the natal chart's zodiac. Positions only; no reading."
        ),
        "product_conventions": [
            "whole sign as the default house system: no pre-modern source read casts a "
            "return chart with whole-sign houses; the sources read use quadrant cusps",
            "a sidereal return when the natal chart is sidereal: no pre-modern source read "
            "gives a rule for it",
            "the birth place only: casting for the place where the native is at the "
            "return (Morin) is not offered",
        ],
        "precession_note": (
            "None of the classical texts read asks for a precession correction of the "
            "return chart; the Fagan and Bradley sources for that practice were not read."
        ),
        "sources": [
            {
                "citation": (
                    "Abraham Ibn Ezra, The Book of the Revolution (Sefer ha-Tequfah) §1:1, "
                    "ed. and tr. S. Sela (2014) p.373"
                ),
                "says": "the revolution is the Sun's return to its natal degree and minute",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Sela's English translation at the cited place",
            },
            {
                "citation": (
                    "Abraham Ibn Ezra, The Book of Nativities (Sefer ha-Moladot) IV 1:9 and "
                    "2:3, ed. and tr. S. Sela (2014) p.185"
                ),
                "says": (
                    "the year's ascendant is found with the rising times of the native's own "
                    "country; the yearly addition he adopts is 87°15′, a tropical-year length"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Sela's English translation at the cited place",
            },
            {
                "citation": (
                    "al-Bīrūnī, The Book of Instruction in the Elements of the Art of "
                    "Astrology, trans. R. Ramsay Wright (1934) §522, p.119"
                ),
                "says": (
                    "the revolution (taḥwīl) is when the Sun arrives at the degree and minute "
                    "it occupied at the nativity"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Wright's English translation at the cited place",
            },
            {
                "citation": (
                    "[Abū Maʿshar], De revolutionibus nativitatum I.1, I.3-6, Latin "
                    "translation printed under the name of Hermes (Basel 1559) pp.211-214"
                ),
                "says": (
                    "the year begins when the Sun returns to its place; the return does not "
                    "override the nativity; the figure has twelve houses with cusps by "
                    "quadrant division and marks the natal ascendant, the profected sign and "
                    "the year's ascendant; the place of casting is not discussed"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": (
                    "the medieval Latin translation at the cited pages; its attribution to "
                    "Abū Maʿshar is the scholarly consensus, not checked here"
                ),
            },
            {
                "citation": "Guido Bonatti, De astronomia, Pars IV preface (Basel 1550) cols. 489-490",
                "says": (
                    "the nativity's yearly revolution runs from the minute of the natal Sun "
                    "until the Sun returns to the same point"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Latin at the cited columns; his chapter on judging it not located",
            },
            {
                "citation": "William Lilly, Christian Astrology (1647) ch. CLXXII pp.734-736",
                "says": (
                    "the revolution is the Sun's return to its natal degree and minute; one "
                    "minute of the natal Sun moves the instant about 24 minutes; the example "
                    "is cast with the birth latitude's table of houses; relocation not "
                    "discussed"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the 1647 first edition at the cited pages",
            },
            {
                "citation": (
                    "J.-B. Morin, Astrologia Gallica XXIII (1661) ch. 4 pp.600-601, ch. 5 "
                    "p.602, ch. 7 p.609, ch. 9 p.634"
                ),
                "says": (
                    "the return chart is to be erected for the place where the native is at "
                    "the return; the ancients left this undetermined and the common practice "
                    "was the place of birth; the return does not override the nativity"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Latin at the cited pages",
            },
            {
                "citation": "John Gadbury, The Doctrine of Nativities (1658) ch. XXXII pp.209-211",
                "says": (
                    "the return is the Sun's coming back to its natal sign, degree and minute; "
                    "the houses are taken from a table of houses for the latitude"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the 1658 printing at the cited pages; the house system is not named",
            },
            {
                "citation": "B. Dykes, Persian Nativities III (2010), introduction pp.6, 10",
                "says": (
                    "Abū Maʿshar casts the return with quadrant cusps and weighs three "
                    "ascendants: the natal, the profected sign and the year's"
                ),
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": "Dykes's introduction; the Arabic text he translates not read",
            },
            {
                "citation": "Ptolemy, Tetrabiblos IV.10 (Robbins, Loeb p.453)",
                "says": "times by profections and ingresses; no return chart",
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "an English translation at the cited chapter",
            },
            {
                "citation": "Vettius Valens, Anthologies V (Riley's English, '5K', p.97)",
                "says": (
                    "a chart is recast each year, but its moment is set by the Moon's return "
                    "to its natal degree, not the Sun's"
                ),
                "reading": SOURCE_READING_LEVELS[1],
                "read_at": "Riley's English at the cited place",
            },
            {
                "citation": "Dorotheus, Carmen Astrologicum IV 1.4 (Arabic recension)",
                "says": (
                    "the year begins when the Sun enters the minute it occupied at birth; the "
                    "recension passed through Persian and Arabic hands"
                ),
                "reading": SOURCE_READING_LEVELS[2],
                "read_at": (
                    "a modern rewritten text that reproduces Pingree's 1976 translation; "
                    "Pingree's own pages not consulted"
                ),
            },
        ],
    },
}
