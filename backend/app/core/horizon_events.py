"""Rise/set/transit events in a fixed apparent topocentric frame.

The event definition uses the refracted upper-limb horizon crossing and does
not follow display computation modes. The response and triggered Dossier
warning expose this boundary explicitly.

Search model (method research notes):

* The search is interval-aware, not date-cell-aware.  Each side (previous /
  next) is searched over a bounded seasonal horizon whose extent is written
  into the receipt, so "no rise" can be read as "no rise between these two
  instants" and never as "never rises".
* Every state is a closed enum.  ``not_searched`` (a side that was never
  probed) is a different value from ``no_event_within_search_interval`` (a
  side that was probed and yielded nothing).
* Circumpolar is a statement about the interval that contains the reference
  instant.  For the Sun, Moon and planets the declination moves, so the
  strongest claim this module makes is "continuously above/below during the
  searched interval" — never "circumpolar forever".
"""

import math
from typing import Final, NamedTuple

import swisseph as swe

from ..ephemeris import (
    COVERAGE_STATES,
    chart_observer_restored,
    coverage_state,
    require_object_coverage,
    segments_read_by,
)
from .trace import Trace
from .time_utils import jd_ut_to_iso_utc, time_scale_for_jd_ut


EVENT_FLAGS = {
    "rise": swe.CALC_RISE,
    "set": swe.CALC_SET,
    "upper_transit": swe.CALC_MTRANSIT,
    "lower_transit": swe.CALC_ITRANSIT,
}
HORIZON_CROSSINGS: Final = ("rise", "set")
# At a geographic pole the meridian and the hour angle are undefined, so upper and
# lower transits have no meaning, while rising and setting still do (the same
# reasoning as for azimuth at a pole in core/bodies.py).
MERIDIAN_UNDEFINED_AT_POLE_REASON: Final = "meridian_undefined_at_geographic_pole"
EPHEMERIS_FLAGS = swe.FLG_SWIEPH

# 與輸出一起回報的框架宣告。消費端不必反推本模組吃不吃 computation_mode。
FRAME_DECLARATION = {
    "follows_computation_mode": False,
    "position_mode": "apparent_always",
    "center": "topocentric_always",
    "refraction": "applied_by_definition_of_rise_and_set",
    # Swiss swe_rise_trans 不依海拔套地平俯角（dip）；海拔只用於站心
    # 位置、氣壓估算與折射截斷（swecl.c rise_set_fast()、swe_rise_trans()、calc_dip()）。
    "horizon_model": "flat_unobstructed_no_dip",
    "horizon_model_note": "altitude used only for topocentric position and pressure; no dip (as USNO)",
    "mth_q_009_apparent_altitude_suppression_applies": False,
    "reason": (
        "A rise is the instant the refracted upper limb crosses the horizon; "
        "removing refraction would remove the event being reported, not merely "
        "change its precision."
    ),
}

# --- Closed vocabularies -----------------------------------------------------
#
# Per-event (rise / set / upper_transit / lower_transit) status.  The seven
# values and their meanings are the method research note's vocabulary, taken
# verbatim so the receipt and the note can be read against each other.
EVENT_STATUSES: Final = (
    "event_found",                      # a real crossing on both sides
    "grazing_contact",                  # touches the threshold, no sign change
    "always_above_threshold",           # above the model horizon across the searched interval
    "always_below_threshold",           # below the model horizon across the searched interval
    "no_event_within_search_interval",  # nothing found, evidence insufficient for always-above/below
    "numerically_unavailable",          # ephemeris / solver error
    "method_not_applicable",            # undefined here: meridian transits at a geographic pole
)
# Per-side (previous / next) search outcome.  "not_searched" is not "no event".
SIDE_STATUSES: Final = (
    "event_found",
    "no_event_within_search_interval",
    "numerically_unavailable",
    "not_searched",
)
# The one value of a side's `error`, present only beside numerically_unavailable:
# the response's closed code for a Swiss failure, never Swiss's own message.
SEARCH_SWISS_ERROR_CODE: Final = "swiss_ephemeris_error"
# Body-level statement about the reference instant, derived from the rise/set
# search plus sampled altitudes.  Interval-aware by construction.
VISIBILITY_STATES: Final = (
    "rises_and_sets",                                # bracketing crossings within a diurnal cycle
    "above_horizon_between_bracketing_events",       # polar day: above since a real rise until a real set
    "below_horizon_between_bracketing_events",       # polar night: below since a real set until a real rise
    "continuously_above_during_search_interval",     # no crossing in the whole searched interval, sampled above
    "continuously_below_during_search_interval",     # no crossing in the whole searched interval, sampled below
    "grazing_contact",
    "indeterminate_evidence_conflict",               # no crossing found but samples straddle the horizon
    "numerically_unavailable",
    "method_not_applicable",                         # published closed set; no producer since only bodies are searched
)

# --- Search parameters -------------------------------------------------------
#
# Seasonal horizon.  Polar day/night at the geographic pole lasts about half a
# year; 200 days on each side covers every transition for |lat| < 90 with a
# margin, so a body that finds no crossing here is genuinely without one across
# the whole season, not merely across a calendar day.
SEARCH_HORIZON_DAYS: Final = {"rise": 200.0, "set": 200.0, "upper_transit": 3.0, "lower_transit": 3.0}
# Day-skip pre-filter.  A probe day [t, t + 1] is skipped without asking Swiss
# only when no rise or set of the body can fall inside it.  A rise or set is
# the instant the refracted upper limb reaches the apparent horizon, that is,
# the topocentric true upper limb stands at -R, R the refraction at the
# apparent horizon.  Let h be the centre's altitude from the latitude phi and
# the apparent declination delta, p the topocentric parallax (it only lowers
# the centre) and s the semidiameter; the upper limb lies in [h - p + s, h + s].
#
# * delta on the observer's side (same sign as phi): h never drops below the
#   lower culmination |phi| + |delta| - 90, so the limb stays above
#   |phi| + |delta| - 90 - p.  No crossing when |delta| > 90 - |phi| + p,
#   since -R <= 0.
# * delta on the other side: h never exceeds the upper culmination
#   90 - |phi| - |delta|, so the limb stays below 90 - |phi| - |delta| + s.
#   No crossing when |delta| > 90 - |phi| + R + s.
#
# The rule reads delta at the two ends of the day only.  With
# |d2(delta)/dt2| <= K, delta lies within K/8 of the straight line between the
# ends (the remainder of linear interpolation is at most K t(1 - t)/2), so when
# both ends share a sign and exceed the limit by K/8 the sign holds and the
# limit is exceeded all day.  A day whose ends differ in sign (the Moon near a
# geographic pole) is always probed.
#
# Measured bounds (1800-2399, plain swe.calc_ut): the Moon's |d2(delta)/dt2|
# reaches 2.22 deg/day^2 and its horizontal parallax 1.0255 deg (1.027 from
# 10 km up); every other body stays under 0.10 deg/day^2 (Mercury) and 0.01 deg
# of parallax (Venus at inferior conjunction).  R is at most 0.89 deg over the
# accepted atmosphere (-40 C, 1100 hPa; the request schema refuses colder air,
# where Swiss's refraction is no longer monotonic).  PRE_FILTER_SAFETY_DEGREES
# absorbs the geodetic-versus-geocentric zenith (under 0.004 deg of parallax
# direction) and rounding.
REFRACTION_AT_HORIZON_MAX_DEGREES: Final = 0.90
PRE_FILTER_SAFETY_DEGREES: Final = 0.05


class PreFilterBounds(NamedTuple):
    parallax_degrees: float
    semidiameter_degrees: float
    curvature_allowance_degrees: float  # K / 8

    def same_hemisphere_margin(self) -> float:
        return self.parallax_degrees + self.curvature_allowance_degrees + PRE_FILTER_SAFETY_DEGREES

    def opposite_hemisphere_margin(self) -> float:
        return (
            REFRACTION_AT_HORIZON_MAX_DEGREES + self.semidiameter_degrees
            + self.curvature_allowance_degrees + PRE_FILTER_SAFETY_DEGREES
        )


_MOON_PRE_FILTER_BOUNDS: Final = PreFilterBounds(1.03, 0.29, 0.30)
# The Sun's disc (0.272 at perihelion) is the largest of the other bodies.
_OTHER_PRE_FILTER_BOUNDS: Final = PreFilterBounds(0.01, 0.28, 0.02)


def pre_filter_bounds(body_id: int) -> PreFilterBounds:
    return _MOON_PRE_FILTER_BOUNDS if body_id == swe.MOON else _OTHER_PRE_FILTER_BOUNDS


def pre_filter_margins_receipt() -> dict:
    return {
        group: {
            "same_hemisphere": round(bounds.same_hemisphere_margin(), 6),
            "opposite_hemisphere": round(bounds.opposite_hemisphere_margin(), 6),
        }
        for group, bounds in (("moon", _MOON_PRE_FILTER_BOUNDS), ("other_bodies", _OTHER_PRE_FILTER_BOUNDS))
    }


# Sampled upper-limb altitude within this band of the horizon, with no crossing
# found, is a tangent contact rather than a general rise/set.
GRAZING_TOLERANCE_DEGREES: Final = 0.01
# Bracketing crossings closer together than this are the ordinary daily
# regime; wider brackets are multi-day polar intervals.
DIURNAL_REGIME_MAX_DAYS: Final = 1.5
# Sampled altitude evidence: 97 instants 30 minutes apart, from 12 hours before
# the reference to 36 hours after it.  The contract's window is computed from
# these same numbers, so the receipt cannot drift from what was sampled.
ENVELOPE_SAMPLE_COUNT: Final = 97
ENVELOPE_SAMPLES_PER_DAY: Final = 48.0
ENVELOPE_START_OFFSET_DAYS: Final = -0.5
# The method behind every body's visibility_evidence.  It is the same for every
# body and every representative sample, so the contract's visibility_evidence_window
# carries it once and each body carries only its two extremes (response budget).
VISIBILITY_EVIDENCE_METHOD: Final = {
    "method": (
        f"{ENVELOPE_SAMPLE_COUNT} topocentric apparent upper-limb altitude samples "
        f"across {(ENVELOPE_SAMPLE_COUNT - 1) / ENVELOPE_SAMPLES_PER_DAY * 24:.0f} hours; "
        "each extreme refined by a parabola through the true altitudes of the "
        "extreme sample and its two neighbours, then refracted"
    ),
    "coordinate_origin": "topocentric",
    "disc_position": "upper_limb",
}

PROVENANCE: Final = {
    "event_definition": "Swiss Ephemeris swe_rise_trans default: refracted upper limb crossing the apparent horizon",
    # 定義來源與狀態詞彙來源分開寫。
    "event_definition_sources": (
        "Swiss swephprg.htm (2.10.03) §8.12, §8.12.1; USNO RST_defs (Sun centre at "
        "zenith distance 90.8333° = 16′ + 34′); USNO Astronomical Almanac Glossary "
        "(2023 ed.). Upper limb as USNO for Sun and Moon; planets likewise by Swiss, "
        "arc-second semidiameters"
    ),
    # 方法研究筆記：七態 enum、'event not found' 不得等於 'never rises'；
    # 拱極判準；中天定義。
    "state_vocabulary_source": (
        "這組狀態詞彙是產品的分類，不是 USNO 的；'event not found' 不等於 'never rises'"
    ),
    "circumpolar_geometry_source": (
        "點中心、幾何地平、無折射的判準 |φ|+|δ|>90°；本模組只用它跳過"
        "不可能有事件的日子，不用它作最終判定"
    ),
    "transit_definition_source": (
        "子午圈中天為時角 0（上）／180°（下），不是高度極值；拱極體有中天無升降"
    ),
}

# --- Ephemeris coverage of the whole search ------------------------
#
# Every other module refuses, by manifest and before calling Swiss, a position
# whose segment does not cover its instant (ephemeris.require_object_coverage).
# swe_rise_trans returns no retflag, so past a segment end (the second half of
# 2399: reference + 200 days) Swiss would silently fall back to Moshier and the
# event would read event_found, with last digits that depend on earlier calls.
# Such a search is therefore refused per the manifest like the other modules.
#
# The reach is the seasonal search horizon plus how far Swiss itself looks from
# a probe (swecl.c 2.10.03): the slow method tabulates from start - 2 h to
# start + 26 h and refines inside that; the fast method may restart half a day
# later and then looks up to one more day (about 1.5 days); a meridian transit
# looks up to about one day; the pre-filter reads a probe day's far end
# (+1 day) and the altitude envelope spans -0.5 to +1.5 days.  Two days covers
# all of them on both sides.
SEARCH_COVERAGE_MARGIN_DAYS: Final = 2.0


def search_coverage_reach_days() -> float:
    """How far before and after its reference one search may make Swiss read."""
    return max(SEARCH_HORIZON_DAYS.values()) + SEARCH_COVERAGE_MARGIN_DAYS


def require_search_coverage(
    body_defs: list[dict], reference_jd_ut: float, *, reach_days: float | None = None
) -> None:
    """Refuse, before any Swiss call, a search that would leave the bundled files.

    Raises ``FullEphemerisRequiredError`` (reason ``segment_out_of_coverage`` or
    ``segment_file_missing``), which the chart turns into this module's
    not_applicable with a closed event-search reason code, exactly as for the
    lunar searches.  Coverage is an interval, so the two ends of the reach
    decide it for every instant in between.  ``reach_days`` replaces the
    seasonal reach for a caller that searches a shorter window.
    """
    reach = search_coverage_reach_days() if reach_days is None else reach_days
    flags = EPHEMERIS_FLAGS | swe.FLG_TOPOCTR
    for body in body_defs:
        for instant in (reference_jd_ut - reach, reference_jd_ut + reach):
            require_object_coverage(
                body=body["id"],
                flags=flags,
                jd_ut=instant,
                operation=f"天體升降與上下中天（{body['zh']}，搜尋範圍）",
            )


METHOD_SOURCE_ENTRIES: Final = {
    "horizon_events": {
        "applies_to": "astronomical_data.horizon_events.contract.provenance",
        **PROVENANCE,
    },
    "horizon_events/statuses": {
        "applies_to": "astronomical_data.horizon_events",
        "event_status_vocabulary": list(EVENT_STATUSES),
        "side_status_vocabulary": list(SIDE_STATUSES),
        "visibility_vocabulary": list(VISIBILITY_STATES),
    },
}


def _event_value(jd_ut: float) -> dict:
    return {
        "jd_ut": jd_ut,
        "utc_time": jd_ut_to_iso_utc(jd_ut),
        # Each timestamp names its own era; a pre-1972 event is UT1.
        "time_scale": time_scale_for_jd_ut(jd_ut),
    }


def _interval(start_jd_ut: float, end_jd_ut: float) -> dict:
    return {
        "start_jd_ut": start_jd_ut,
        "end_jd_ut": end_jd_ut,
        "start_utc": jd_ut_to_iso_utc(start_jd_ut),
        "end_utc": jd_ut_to_iso_utc(end_jd_ut),
        "span_days": end_jd_ut - start_jd_ut,
    }


def _envelope_sample_instants(reference_jd_ut: float) -> list[float]:
    return [
        reference_jd_ut + ENVELOPE_START_OFFSET_DAYS + index / ENVELOPE_SAMPLES_PER_DAY
        for index in range(ENVELOPE_SAMPLE_COUNT)
    ]


def _rise_trans_call(
    start_jd_ut: float,
    body_id: int,
    event_flag: int,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
    probe_cache: "HorizonProbeCache | None" = None,
) -> tuple[int, float | None]:
    if probe_cache is not None:
        return probe_cache.probe(
            start_jd_ut, body_id, event_flag, geopos, pressure_hpa, temperature_c
        )
    return _swiss_rise_trans(
        start_jd_ut, body_id, event_flag, geopos, pressure_hpa, temperature_c
    )


def _swiss_rise_trans(
    start_jd_ut: float,
    body_id: int,
    event_flag: int,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
) -> tuple[int, float | None]:
    rsmi = event_flag
    # Swiss default for rise/set is the upper limb with standard refraction.
    # Do not add BIT_DISC_CENTER or BIT_NO_REFRACTION; expose that choice in metadata.
    with chart_observer_restored():
        result, times = swe.rise_trans(
            start_jd_ut,
            body_id,
            rsmi,
            geopos,
            pressure_hpa,
            temperature_c,
            EPHEMERIS_FLAGS,
        )
    return result, times[0] if result == 0 else None


# --- Per-chart probe reuse (performance only; never changes a result) --------
#
# At 70 N a chart with rise/set on makes about 640 Swiss rise_trans probes, and
# an hour-level or date-only chart four times as many, because the
# representative samples repeat the whole search (one of them at exactly the
# anchor instant).  Almost all of that time is day-by-day probes for a body that
# neither rises nor sets for months.
#
# Two reuses, both exact:
#
# 1. A probe with the same arguments is asked of Swiss once per chart.  The
#    anchor sample of an hour-level or date-only chart repeats the anchor search
#    argument for argument.
# 2. A rise and a set probe from the same start instant share one Swiss pass
#    when Swiss uses its slow method there.  In swecl.c (2.10.03)
#    swe_rise_trans_true_hor() builds one altitude table from the start instant
#    (15 two-hour samples plus refined culminations), bisects every sign change,
#    and returns the first crossing later than the start whose direction the
#    CALC_RISE / CALC_SET bits accept.  Nothing else depends on those bits.  So
#    a probe with both bits set returns the first crossing of either direction,
#    and:
#      * if it finds none (-2), the rise probe and the set probe both find none;
#      * if it finds t, the probe of t's direction returns exactly t (same table
#        index, same bisection), and the other probe returns something else.
#    The search asks for the combined probe only inside a run of empty probes,
#    where "none" is the usual answer; a combined result that does not settle
#    a direction falls back to that direction's own probe.
#
# The fast method (rise_set_fast, used below 60 degrees, 65 for the Sun, for
# Sun..true node) is not shared: it is never asked for a combined probe.
#
# Both reuses assume Swiss answers a probe as a function of its arguments
# alone.  Inside the bundled segments it does.  Past a segment end Swiss falls
# back to Moshier, whose answer also depends on the calls made before it (a
# 2400-03 Venus set from the same arguments measured about 1e-9 day apart
# depending on what had been computed earlier).  A chart
# whose search can reach past the manifest coverage is therefore computed with
# no reuse at all, so it makes exactly the calls an uncached search makes.
# The margin covers the representative samples (within a day of the anchor),
# Swiss's own window past a probe start (about 1.2 days), the pre-filter's
# second instant and the altitude envelope (1.5 days).
# A search that would read past the coverage is refused before any
# Swiss call (require_search_coverage), so no reused probe can come from past
# the segment end; this gate stays as a second, independent guard.
PROBE_REUSE_COVERAGE_MARGIN_DAYS: Final = 5.0
COMBINED_CROSSING_FLAG: Final = swe.CALC_RISE | swe.CALC_SET
_UNSETTLED: Final = object()


def probe_cache_for_chart(
    body_defs: list[dict], anchor_jd_ut: float
) -> "HorizonProbeCache | None":
    """A probe cache for one chart, or None when reuse would not be exact.

    None whenever any segment a searched body reads (topocentric, so the Moon
    segment for every body) does not cover the whole reach of the search around
    the anchor, by manifest.
    """
    reach = max(SEARCH_HORIZON_DAYS.values()) + PROBE_REUSE_COVERAGE_MARGIN_DAYS
    flags = EPHEMERIS_FLAGS | swe.FLG_TOPOCTR
    for body in body_defs:
        for segment in segments_read_by(body["id"], flags):
            for instant in (anchor_jd_ut - reach, anchor_jd_ut + reach):
                if coverage_state(instant, segment) != COVERAGE_STATES[0]:
                    return None
    return HorizonProbeCache()


def swiss_slow_rise_set_method_applies(body_id: int, latitude: float) -> bool:
    """True when swe_rise_trans() takes its slow path for this body and latitude.

    A mirror of the fast-path condition in swecl.c swe_rise_trans() (2.10.03),
    for a planet number (never a star name) and a rise/set request without
    twilight or force-slow bits.
    """
    fast = swe.SUN <= body_id <= swe.TRUE_NODE and (
        abs(latitude) <= 60 or (body_id == swe.SUN and abs(latitude) <= 65)
    )
    return not fast


class HorizonProbeCache:
    """Swiss answers already obtained while computing one chart.

    One instance lives for one chart (the anchor search and its representative
    samples) and is then dropped; it is never shared between requests.  Every
    entry is a value Swiss returned for exactly those arguments, or one the
    combined-probe rule above derives from such a value.
    """

    def __init__(self) -> None:
        self._probes: dict[tuple, tuple[int, float | None]] = {}
        self._combined: dict[tuple, object] = {}
        self._declinations: dict[tuple[float, int], float] = {}
        self._envelopes: dict[tuple, dict] = {}

    def probe(
        self,
        start_jd_ut: float,
        body_id: int,
        event_flag: int,
        geopos: tuple[float, float, float],
        pressure_hpa: float,
        temperature_c: float,
    ) -> tuple[int, float | None]:
        key = (start_jd_ut, body_id, event_flag, geopos, pressure_hpa, temperature_c)
        cached = self._probes.get(key)
        if cached is None:
            # A Swiss error propagates and is not remembered: asking again
            # raises again, exactly as an uncached search would.
            cached = _swiss_rise_trans(*key)
            self._probes[key] = cached
        return cached

    def crossing_probe(
        self,
        start_jd_ut: float,
        body_id: int,
        event_name: str,
        geopos: tuple[float, float, float],
        pressure_hpa: float,
        temperature_c: float,
        *,
        within_empty_run: bool,
    ) -> tuple[int, float | None]:
        """The rise or set probe, answered from a shared probe when that is exact."""
        flag = EVENT_FLAGS[event_name]
        key = (start_jd_ut, body_id, flag, geopos, pressure_hpa, temperature_c)
        cached = self._probes.get(key)
        if cached is not None:
            return cached
        shared_key = (start_jd_ut, body_id, geopos, pressure_hpa, temperature_c)
        if not swiss_slow_rise_set_method_applies(body_id, geopos[1]):
            return self.probe(*key)
        combined = self._combined.get(shared_key)
        # Rise is searched before set, so the combined probe is asked on the
        # rise side and read on the set side.
        if combined is None and within_empty_run and event_name == "rise":
            try:
                combined = _swiss_rise_trans(
                    start_jd_ut, body_id, COMBINED_CROSSING_FLAG,
                    geopos, pressure_hpa, temperature_c,
                )
            except swe.Error:
                combined = _UNSETTLED
            self._combined[shared_key] = combined
        settled = self._settle_from_combined(combined, body_id, event_name, shared_key)
        if settled is not None:
            self._probes[key] = settled
            return settled
        return self.probe(*key)

    def _settle_from_combined(
        self, combined, body_id: int, event_name: str, shared_key: tuple
    ) -> tuple[int, float | None] | None:
        if combined is None or combined is _UNSETTLED:
            return None
        status, first_crossing = combined
        if status != 0:
            # No crossing of either direction: neither single-direction probe
            # finds one, and Swiss reports that as the same -2.
            return status, None
        other = "set" if event_name == "rise" else "rise"
        start_jd_ut, _body, geopos, pressure_hpa, temperature_c = shared_key
        other_result = self._probes.get(
            (start_jd_ut, body_id, EVENT_FLAGS[other], geopos, pressure_hpa, temperature_c)
        )
        if other_result is None:
            return None
        if other_result[0] == 0 and other_result[1] == first_crossing:
            # The first crossing was the other direction's; this one's is later.
            return None
        # The first crossing is not the other direction's, so it is this one's.
        return 0, first_crossing

    def altitude_envelope(
        self,
        reference_jd_ut: float,
        body_id: int,
        geopos: tuple[float, float, float],
        pressure_hpa: float,
        temperature_c: float,
    ) -> dict:
        key = (reference_jd_ut, body_id, geopos, pressure_hpa, temperature_c)
        envelope = self._envelopes.get(key)
        if envelope is None:
            # Sampling sets the observer to `geopos`, the chart's own observer
            # in the product; every observer-moving Swiss call restores it, so a
            # cached envelope leaves nothing to re-apply.
            envelope = _sample_altitude_envelope(
                reference_jd_ut, body_id, geopos, pressure_hpa, temperature_c
            )
            self._envelopes[key] = envelope
        return dict(envelope)

    def declination(self, instant: float, body_id: int) -> float:
        key = (instant, body_id)
        value = self._declinations.get(key)
        if value is None:
            value = swe.calc_ut(instant, body_id, EPHEMERIS_FLAGS | swe.FLG_EQUATORIAL)[0][1]
            self._declinations[key] = value
        return value


def _crossing_geometrically_possible(
    jd_ut: float,
    body_id: int,
    latitude: float,
    probe_cache: HorizonProbeCache | None = None,
) -> bool:
    """Cheap pre-filter: False only if no rise or set can fall in [jd_ut, jd_ut + 1].

    The probe at `jd_ut` asks Swiss for the next event after it, so the day it
    stands for is [jd_ut, jd_ut + 1].  The derivation of the rule and of its
    bounds is the comment above `REFRACTION_AT_HORIZON_MAX_DEGREES`: a day is
    skipped only when the declination keeps one sign and stays beyond the
    hemisphere's limit all day, judged from both ends plus the curvature
    allowance.  The pre-filter only saves solver calls; it is never the final
    verdict.
    """
    ends = [
        (
            probe_cache.declination(instant, body_id)
            if probe_cache is not None
            else swe.calc_ut(
                instant, body_id, EPHEMERIS_FLAGS | swe.FLG_EQUATORIAL
            )[0][1]
        )
        for instant in (jd_ut, jd_ut + 1.0)
    ]
    if latitude == 0.0 or ends[0] * ends[1] <= 0.0:
        return True
    bounds = pre_filter_bounds(body_id)
    same_hemisphere = (ends[0] > 0.0) == (latitude > 0.0)
    margin = (
        bounds.same_hemisphere_margin()
        if same_hemisphere
        else bounds.opposite_hemisphere_margin()
    )
    return min(abs(ends[0]), abs(ends[1])) <= 90.0 - abs(latitude) + margin


def _walk_probe(
    cursor: float,
    body_id: int,
    event_name: str,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
    probe_cache: HorizonProbeCache | None,
    *,
    within_empty_run: bool,
) -> tuple[int, float | None]:
    """One day-step probe of a search walk (identical result with or without a cache)."""
    if probe_cache is not None and event_name in HORIZON_CROSSINGS:
        return probe_cache.crossing_probe(
            cursor, body_id, event_name, geopos, pressure_hpa, temperature_c,
            within_empty_run=within_empty_run,
        )
    return _rise_trans_call(
        cursor, body_id, EVENT_FLAGS[event_name], geopos, pressure_hpa, temperature_c,
        probe_cache,
    )


def _first_event_after(
    after_jd_ut: float,
    end_jd_ut: float,
    body_id: int,
    event_name: str,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
    probe_cache: HorizonProbeCache | None,
    *,
    known_empty: tuple[float, float] | None = None,
) -> float | None:
    """First event strictly after ``after_jd_ut`` and not later than ``end_jd_ut``.

    A Swiss probe sees only its own window from the probe start (about 26 hours
    for the slow method), and a -2 means "nothing in that window", not "nothing
    until the end".  Consecutive moonrises or moonsets at high latitude can be
    more than a window apart, so after a -2 the probe start moves one day on and
    the walk continues; one day is shorter than every Swiss window, so the
    windows overlap and no stretch before ``end_jd_ut`` is left unprobed.

    ``known_empty = (low, high)`` says no event lies in (low, high], because
    probes already made under the same one-day rule found none there; a step
    that lands inside that stretch moves straight to ``high``, which probes the
    same remaining time.
    """
    cursor = math.nextafter(after_jd_ut, math.inf)
    crossing = event_name in HORIZON_CROSSINGS
    within_empty_run = False

    def step(current: float) -> float:
        following = current + 1.0
        if known_empty is not None and known_empty[0] < following < known_empty[1]:
            return known_empty[1]
        return following

    while cursor <= end_jd_ut:
        if crossing and not _crossing_geometrically_possible(
            cursor, body_id, geopos[1], probe_cache
        ):
            cursor = step(cursor)
            continue
        status, candidate = _walk_probe(
            cursor, body_id, event_name, geopos, pressure_hpa, temperature_c,
            probe_cache, within_empty_run=within_empty_run,
        )
        within_empty_run = status != 0
        if status == 0 and candidate is not None:
            return candidate if candidate <= end_jd_ut else None
        # -2: no event in Swiss's own one/two-day window from this cursor.
        cursor = step(cursor)
    return None


SUN_CROSSING_RESUME_DAYS: Final = 1.0 / 1440.0


def sun_horizon_crossings(
    start_jd_ut: float, end_jd_ut: float, location, atmosphere
) -> list[tuple[float, str]]:
    """Every sunrise and sunset in (start, end], in time order, by this module's definition.

    The same Swiss probe walk as the rise/set search (refracted upper limb,
    apparent topocentric, the request's atmosphere), over a caller's window
    instead of the seasonal horizon.  The caller checks coverage first
    (``require_search_coverage`` with its own reach).
    """
    geopos = (location.longitude, location.latitude, location.altitude_m)
    pressure_hpa = atmosphere.pressure_hpa if atmosphere.pressure_hpa is not None else 0.0
    crossings = []
    for name in HORIZON_CROSSINGS:
        cursor = start_jd_ut
        while True:
            found = _first_event_after(
                cursor, end_jd_ut, swe.SUN, name, geopos, pressure_hpa,
                atmosphere.temperature_c, None,
            )
            if found is None:
                break
            crossings.append((found, name))
            # Swiss re-solves a root from a start just past it to within a few
            # ULPs, so the walk resumes a minute later; two sunrises a minute
            # apart do not exist outside a grazing contact.
            cursor = found + SUN_CROSSING_RESUME_DAYS
    return sorted(crossings)


def _search_next(
    reference_jd_ut: float,
    body_id: int,
    event_name: str,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
    probe_cache: HorizonProbeCache | None = None,
) -> tuple[str, float | None]:
    """First event strictly after the reference within the seasonal horizon."""
    found = _first_event_after(
        reference_jd_ut, reference_jd_ut + SEARCH_HORIZON_DAYS[event_name],
        body_id, event_name, geopos, pressure_hpa, temperature_c, probe_cache,
    )
    if found is None:
        return "no_event_within_search_interval", None
    return "event_found", found


def _search_previous(
    reference_jd_ut: float,
    body_id: int,
    event_name: str,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
    probe_cache: HorizonProbeCache | None = None,
) -> tuple[str, float | None]:
    """Last event strictly before the reference within the seasonal horizon.

    Walk backwards a day at a time until a probe yields an event before the
    reference; then walk forwards from it, exactly as the next-event search
    does (stepping a day past each empty Swiss window), until the reference, so
    the last event below the reference is returned.  A Swiss -2 only means no
    event in that probe's own window (stopping there would report a moonset at
    68.6 N more than a day too early).
    """
    horizon = SEARCH_HORIZON_DAYS[event_name]
    start = reference_jd_ut - horizon
    crossing = event_name in HORIZON_CROSSINGS
    cursor = reference_jd_ut - 2.0
    within_empty_run = False
    anchor = None
    while cursor >= start:
        if crossing and not _crossing_geometrically_possible(
            cursor, body_id, geopos[1], probe_cache
        ):
            cursor -= 1.0
            continue
        status, candidate = _walk_probe(
            cursor, body_id, event_name, geopos, pressure_hpa, temperature_c,
            probe_cache, within_empty_run=within_empty_run,
        )
        within_empty_run = status != 0
        if status == 0 and candidate is not None and candidate < reference_jd_ut:
            anchor = candidate
            break
        cursor -= 1.0
    # The seasonal horizon may end inside the last day probed above; one more
    # probe at the horizon itself closes that gap.
    if anchor is None and cursor < start and start < reference_jd_ut - 2.0:
        status, candidate = _rise_trans_call(
            start, body_id, EVENT_FLAGS[event_name], geopos, pressure_hpa, temperature_c,
            probe_cache,
        )
        if status == 0 and candidate is not None and candidate < reference_jd_ut:
            anchor = candidate
    # Every backward probe start after the one that found the anchor (or every
    # one, when none did) found nothing before the reference, and each covered
    # at least the day after it: no event lies in (that start, reference - 1].
    # The forward walk below need not probe that stretch again.  The first
    # backward probe (reference - 2) sees only its own window, so the last day
    # before the reference is always probed.
    known_empty = (cursor + 1.0, reference_jd_ut - 1.0)
    if anchor is None:
        anchor = _first_event_after(
            max(start, reference_jd_ut - 1.0), reference_jd_ut,
            body_id, event_name, geopos, pressure_hpa, temperature_c, probe_cache,
        )
        if anchor is None or anchor >= reference_jd_ut:
            return "no_event_within_search_interval", None
    previous = anchor
    while True:
        following = _first_event_after(
            previous, reference_jd_ut,
            body_id, event_name, geopos, pressure_hpa, temperature_c, probe_cache,
            known_empty=known_empty,
        )
        if following is None or following >= reference_jd_ut:
            return "event_found", previous
        previous = following


def _searched_pair(
    reference_jd_ut: float,
    body_id: int,
    event_name: str,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
    probe_cache: HorizonProbeCache | None = None,
) -> dict:
    # Per-side outcome only.  The searched interval depends on nothing but the
    # reference instant and the event kind, so it is declared once in
    # `contract.search_intervals` instead of on every side of every body.
    search = {
        "previous": {"status": "not_searched"},
        "next": {"status": "not_searched"},
    }
    values: dict[str, dict | None] = {"previous": None, "next": None}
    for side, searcher in (("previous", _search_previous), ("next", _search_next)):
        try:
            status, jd = searcher(
                reference_jd_ut, body_id, event_name, geopos, pressure_hpa, temperature_c,
                probe_cache,
            )
        except swe.Error:
            # A closed code only: Swiss messages can name the ephemeris
            # directory and the instant asked for.
            search[side]["status"] = "numerically_unavailable"
            search[side]["error"] = SEARCH_SWISS_ERROR_CODE
            continue
        search[side]["status"] = status
        values[side] = _event_value(jd) if jd is not None else None
    return {
        # Pair-level status is finalised once sampled evidence is available;
        # see `_finalise_event_status`.
        "status": None,
        "previous": values["previous"],
        "next": values["next"],
        "search": search,
    }


def classify_no_crossing(minimum_altitude: float, maximum_altitude: float) -> str:
    """Status for a crossing whose search found nothing on either side.

    Uses the sampled apparent upper-limb altitude envelope around the reference.
    """
    if abs(minimum_altitude) <= GRAZING_TOLERANCE_DEGREES or (
        abs(maximum_altitude) <= GRAZING_TOLERANCE_DEGREES
    ):
        return "grazing_contact"
    if minimum_altitude > 0:
        return "always_above_threshold"
    if maximum_altitude < 0:
        return "always_below_threshold"
    return "no_event_within_search_interval"


def _finalise_event_status(event: dict, envelope: tuple[float, float] | None) -> None:
    sides = event["search"]
    statuses = {sides["previous"]["status"], sides["next"]["status"]}
    if "numerically_unavailable" in statuses:
        event["status"] = "numerically_unavailable"
    elif statuses == {"event_found"}:
        event["status"] = "event_found"
    elif "event_found" in statuses:
        # One side found: the other side is a bounded absence, nothing more.
        event["status"] = "no_event_within_search_interval"
    elif envelope is None:
        event["status"] = "no_event_within_search_interval"
    else:
        event["status"] = classify_no_crossing(*envelope)


def _not_applicable_event(reason_code: str) -> dict:
    return {
        "status": "method_not_applicable",
        "previous": None,
        "next": None,
        "search": {
            "previous": {"status": "not_searched"},
            "next": {"status": "not_searched"},
        },
        "reason_code": reason_code,
    }


def _refined_extreme(values: list[float], index: int, *, maximum: bool) -> float:
    """The extreme sample, refined by a parabola through it and its two neighbours.

    Samples 30 minutes apart can sit about 0.04 degrees from the true extreme,
    four times the 0.01-degree grazing tolerance, so a body that really grazes the
    horizon was classified as always above or always below unless a sample fell
    near the extreme.  Three-point interpolation needs
    no extra Swiss calls; the vertex is used only when it lies between the
    neighbours and is more extreme than the sample itself.  `values` must be a
    smooth function of time: the caller passes TRUE altitudes, never refracted
    ones, which jump where Swiss switches refraction off.
    """
    sample = values[index]
    if index == 0 or index == len(values) - 1:
        return sample
    left, right = values[index - 1], values[index + 1]
    curvature = left - 2.0 * sample + right
    if curvature == 0.0 or (curvature > 0.0) == maximum:
        return sample
    offset = (left - right) / (2.0 * curvature)
    if abs(offset) > 1.0:
        return sample
    vertex = sample - (left - right) ** 2 / (8.0 * curvature)
    return max(vertex, sample) if maximum else min(vertex, sample)


def _sample_altitude_envelope(
    reference_jd_ut: float,
    body_id: int,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
) -> dict:
    swe.set_topo(*geopos)
    topocentric_flags = EPHEMERIS_FLAGS | swe.FLG_TOPOCTR
    samples = []
    for jd_ut in _envelope_sample_instants(reference_jd_ut):
        ecliptic = swe.calc_ut(jd_ut, body_id, topocentric_flags)[0]
        azimuth, true_centre_altitude, _apparent_centre_altitude = swe.azalt(
            jd_ut,
            swe.ECL2HOR,
            geopos,
            pressure_hpa,
            temperature_c,
            (ecliptic[0], ecliptic[1], ecliptic[2]),
        )
        semidiameter = swe.pheno_ut(jd_ut, body_id, topocentric_flags)[3] / 2.0
        # Refraction depends on altitude and Swiss switches it off once the
        # refracted point would sit below the horizon, so the refracted centre
        # plus the radius is not the refracted upper limb: near the horizon the
        # two differ by the whole ~0.57 degree refraction.  Raise the TRUE centre
        # by the radius, then refract that direction, the order swe_rise_trans
        # uses for its upper-limb event (swecl.c: true height of the uppermost
        # point, then azalt_rev -> azalt).
        true_limb_altitude = true_centre_altitude + semidiameter
        samples.append((
            jd_ut,
            azimuth,
            true_limb_altitude,
            _apparent_altitude(jd_ut, azimuth, true_limb_altitude, geopos, pressure_hpa, temperature_c),
        ))
    # Swiss's refraction is monotonic in the true altitude over the accepted
    # atmosphere, so the apparent extreme is the refracted true extreme.  The
    # parabola runs through the smooth true altitudes and only its vertex is
    # refracted: through the refracted samples it would straddle the jump where
    # Swiss switches refraction off and land on neither side of it.
    # Every local extreme is refined, not only the extreme sample: the window
    # holds two culminations, and near a solstice the one whose sample sits
    # nearer its peak need not be the higher one.  Near the jump a thousandth
    # of a degree of true altitude decides the side.
    true_values = [sample[2] for sample in samples]

    def extreme(maximum: bool) -> float:
        pick = max if maximum else min
        sign = 1.0 if maximum else -1.0
        last = len(true_values) - 1
        candidates = {pick(range(len(true_values)), key=true_values.__getitem__)} | {
            index
            for index in range(1, last)
            if sign * true_values[index] >= sign * true_values[index - 1]
            and sign * true_values[index] >= sign * true_values[index + 1]
        }
        refined, index = pick(
            (_refined_extreme(true_values, index, maximum=maximum), index) for index in candidates
        )
        jd_ut, azimuth, true_altitude, apparent_altitude = samples[index]
        if refined == true_altitude:
            return apparent_altitude
        return _apparent_altitude(jd_ut, azimuth, refined, geopos, pressure_hpa, temperature_c)

    # 方法、座標原點與圓面位置對每個天體、每個代表性取樣都相同，只寫在
    # contract.visibility_evidence_window（VISIBILITY_EVIDENCE_METHOD）；逐體只帶兩個極值。
    return {
        "minimum_apparent_upper_limb_altitude_degrees": extreme(False),
        "maximum_apparent_upper_limb_altitude_degrees": extreme(True),
    }


def _apparent_altitude(
    jd_ut: float,
    azimuth: float,
    true_altitude: float,
    geopos: tuple[float, float, float],
    pressure_hpa: float,
    temperature_c: float,
) -> float:
    """Swiss's refracted altitude of the direction at (azimuth, true altitude)."""
    equatorial = swe.azalt_rev(jd_ut, swe.HOR2EQU, geopos, azimuth, true_altitude)
    return swe.azalt(
        jd_ut,
        swe.EQU2HOR,
        geopos,
        pressure_hpa,
        temperature_c,
        (equatorial[0], equatorial[1], 1.0),
    )[2]


def _bracketing_interval(events: dict) -> dict:
    """The last crossing before and the first crossing after the reference."""
    before = [
        (events[name]["previous"]["jd_ut"], name)
        for name in HORIZON_CROSSINGS
        if events[name]["previous"] is not None
    ]
    after = [
        (events[name]["next"]["jd_ut"], name)
        for name in HORIZON_CROSSINGS
        if events[name]["next"] is not None
    ]
    start = max(before) if before else None
    end = min(after) if after else None
    # A summary, not a second copy of the instants: they are
    # events[start_event].previous and events[end_event].next.
    return {
        "start_event": start[1] if start else None,
        "end_event": end[1] if end else None,
        "span_days": (end[0] - start[0]) if start and end else None,
    }


def _visibility(events: dict, bracket: dict, envelope: dict | None) -> str:
    crossings = [events[name] for name in HORIZON_CROSSINGS]
    if any(event["status"] == "numerically_unavailable" for event in crossings):
        return "numerically_unavailable"
    if bracket["start_event"] is None and bracket["end_event"] is None:
        if envelope is None:
            return "indeterminate_evidence_conflict"
        status = classify_no_crossing(
            envelope["minimum_apparent_upper_limb_altitude_degrees"],
            envelope["maximum_apparent_upper_limb_altitude_degrees"],
        )
        return {
            "always_above_threshold": "continuously_above_during_search_interval",
            "always_below_threshold": "continuously_below_during_search_interval",
            "grazing_contact": "grazing_contact",
        }.get(status, "indeterminate_evidence_conflict")
    span = bracket["span_days"]
    if span is not None and span <= DIURNAL_REGIME_MAX_DAYS:
        return "rises_and_sets"
    # State now follows the last crossing before the reference, or, failing
    # that, the first crossing after it.
    above = (
        bracket["start_event"] == "rise"
        if bracket["start_event"] is not None
        else bracket["end_event"] == "set"
    )
    return (
        "above_horizon_between_bracketing_events"
        if above
        else "below_horizon_between_bracketing_events"
    )


def compute_horizon_events(
    body_defs: list[dict],
    reference_jd_ut: float,
    location,
    atmosphere,
    trace: Trace,
    *,
    probe_cache: HorizonProbeCache | None = None,
) -> dict:
    """Rise/set/transit events of every body around one reference instant.

    ``probe_cache`` (from ``probe_cache_for_chart``) lets one chart's anchor
    search and its representative samples reuse Swiss answers; it changes how
    often Swiss is asked, never what is returned.  Without one every probe goes
    to Swiss.
    """
    require_search_coverage(body_defs, reference_jd_ut)
    geopos = (location.longitude, location.latitude, location.altitude_m)
    pressure_hpa = atmosphere.pressure_hpa if atmosphere.pressure_hpa is not None else 0.0
    results = []

    for body in body_defs:
        at_pole = abs(location.latitude) >= 90.0
        events = {
            name: (
                _not_applicable_event(MERIDIAN_UNDEFINED_AT_POLE_REASON)
                if at_pole and name not in HORIZON_CROSSINGS
                else _searched_pair(
                    reference_jd_ut,
                    body["id"],
                    name,
                    geopos,
                    pressure_hpa,
                    atmosphere.temperature_c,
                    probe_cache,
                )
            )
            for name in EVENT_FLAGS
        }
        bracket = _bracketing_interval(events)
        diurnal = (
            bracket["span_days"] is not None
            and bracket["span_days"] <= DIURNAL_REGIME_MAX_DAYS
        )
        # Sampled altitudes are the evidence for any claim beyond "found":
        # skip them only in the ordinary daily regime.
        envelope = None
        if not diurnal:
            sample_envelope = (
                probe_cache.altitude_envelope
                if probe_cache is not None
                else _sample_altitude_envelope
            )
            envelope = sample_envelope(
                reference_jd_ut,
                body["id"],
                geopos,
                pressure_hpa,
                atmosphere.temperature_c,
            )
        pair = (
            (
                envelope["minimum_apparent_upper_limb_altitude_degrees"],
                envelope["maximum_apparent_upper_limb_altitude_degrees"],
            )
            if envelope is not None
            else None
        )
        for name, event in events.items():
            if event["status"] is None:
                _finalise_event_status(
                    event, pair if name in HORIZON_CROSSINGS else None
                )
        results.append({
            "key": body["key"],
            "name": body["zh"],
            "visibility": _visibility(events, bracket, envelope),
            "visibility_evidence": envelope,
            "bracketing_interval": bracket,
            "events": events,
        })

    trace.add(
        "天體升降與上下中天",
        formula=(
            "swe.rise_trans；每側在有界季節區間內逐日搜尋（升降 ±200 日、中天 ±3 日），"
            "探測日首尾兩端赤緯同號、且 |δ| 都超過 90°−|φ| 加該半球的餘裕（contract."
            "crossing_prefilter_margins_degrees）才跳過，首尾異號的日子一律問 Swiss；"
            "previous 取參考時刻前最後一次事件，next 取其後第一次；地理極點上下中天不適用"
        ),
        inputs={
            "reference_JD_UT": reference_jd_ut,
            "geopos": geopos,
            "pressure_hPa": pressure_hpa,
            "temperature_C": atmosphere.temperature_c,
            "rise_set_disc": "upper_limb",
            "refraction": "enabled",
            "flags": EPHEMERIS_FLAGS,
            "search_horizon_days": SEARCH_HORIZON_DAYS,
        },
        result={"body_count": len(results)},
        note="上下中天不使用 disc/refraction；升降使用 Swiss upper-limb + standard-refraction default。"
             "上中天是時角 0 的時刻，不是高度極大值時刻。",
    )
    samples = _envelope_sample_instants(reference_jd_ut)
    return {
        "contract": {
            "reference_time": "birth_instant",
            "directions": ["previous", "next"],
            "disc_position": "upper_limb",
            "refraction": "enabled",
            "frame": dict(FRAME_DECLARATION),
            "pressure_hpa": atmosphere.pressure_hpa,
            "pressure_mode": (
                "user_supplied" if atmosphere.pressure_hpa is not None
                else "swiss_estimate_from_altitude"
            ),
            "temperature_c": atmosphere.temperature_c,
            "ephemeris_flags": EPHEMERIS_FLAGS,
            "transit_definition": "upper_and_lower_meridian_transit",
            "upper_transit_is_hour_angle_zero_not_max_altitude": True,
            "coordinate_origin": "topocentric_observer",
            "display_center_independent": True,
            "search_model": "bounded_seasonal_interval_per_side",
            "search_horizon_days": dict(SEARCH_HORIZON_DAYS),
            "search_intervals": {
                name: {
                    "previous": _interval(reference_jd_ut - horizon, reference_jd_ut),
                    "next": _interval(reference_jd_ut, reference_jd_ut + horizon),
                }
                for name, horizon in SEARCH_HORIZON_DAYS.items()
            },
            "search_interval_scope": "shared_by_every_body; each event carries only search.previous/next.status",
            "bracketing_interval_instants": "events[start_event].previous and events[end_event].next",
            "visibility_evidence_window": {
                **_interval(samples[0], samples[-1]),
                "sample_count": ENVELOPE_SAMPLE_COUNT,
                **VISIBILITY_EVIDENCE_METHOD,
                "is_search_interval": False,
                "emitted_when": "bracketing crossings are not within one diurnal cycle",
            },
            "crossing_prefilter_margins_degrees": pre_filter_margins_receipt(),
            "grazing_tolerance_degrees": GRAZING_TOLERANCE_DEGREES,
            "diurnal_regime_max_days": DIURNAL_REGIME_MAX_DAYS,
            # The three closed sets are constant: register entry horizon_events/statuses.
            "vocabulary_source_ref": "horizon_events/statuses",
            "provenance": {
                "event_definition": PROVENANCE["event_definition"],
                "source_ref": "horizon_events",
            },
        },
        "bodies": results,
    }
