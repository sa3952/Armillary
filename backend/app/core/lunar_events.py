"""Geocentric lunar phases, prenatal syzygy, and preceding eclipse events.

These are astronomical events only. They deliberately use a fixed, documented
geocentric apparent tropical-of-date contract rather than inheriting research
display modes such as heliocentric, sidereal, J2000, or true position.
"""

import math
from collections.abc import Callable
from functools import cache

import swisseph as swe

from ..ephemeris import (
    chart_observer_restored,
    require_full_ephemeris,
    require_object_coverage,
)
from .root_finding import find_crossings_detailed
from .source_reading import SOURCE_READING_LEVELS
from .trace import Trace
from .time_utils import jd_ut_to_iso_utc, time_scale_for_jd_ut


PHASES = {
    "new_moon": 0.0,
    "first_quarter": 90.0,
    "full_moon": 180.0,
    "last_quarter": 270.0,
}
PHASE_FLAGS = swe.FLG_SWIEPH | swe.FLG_SPEED


def _signed_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


def _phase_state(jd_ut: float) -> tuple[float, float, int, int]:
    # Coverage is decided by manifest before Swiss is asked (ephemeris module
    # contract): a Moshier retflag afterwards would come too late, and a warm
    # worker may extrapolate under SWIEPH instead.
    moon_operation, sun_operation = "月相搜尋（月球位置）", "月相搜尋（太陽位置）"
    require_object_coverage(body=swe.MOON, flags=PHASE_FLAGS, jd_ut=jd_ut, operation=moon_operation)
    require_object_coverage(body=swe.SUN, flags=PHASE_FLAGS, jd_ut=jd_ut, operation=sun_operation)
    moon, moon_retflag = swe.calc_ut(jd_ut, swe.MOON, PHASE_FLAGS)
    sun, sun_retflag = swe.calc_ut(jd_ut, swe.SUN, PHASE_FLAGS)
    require_full_ephemeris(moon_retflag, operation=moon_operation, jd_ut=jd_ut)
    require_full_ephemeris(sun_retflag, operation=sun_operation, jd_ut=jd_ut)
    elongation = (moon[0] - sun[0]) % 360.0
    relative_speed = moon[3] - sun[3]
    return elongation, relative_speed, moon_retflag, sun_retflag


# Phases are bracketed and bisected by the one product solver (root_finding):
# an unguarded Newton step could oscillate and fail the whole chart.
_PHASE_BRACKET_DAYS = 1.5
_PHASE_COARSE_STEP_DAYS = 0.05
# 1e-9 days is under a millisecond; the caller independently checks the angular
# residual after refinement.
_PHASE_TOLERANCE_DAYS = 1e-9
# A phase this close to the reference in elongation (about 0.7 ms at
# the mean relative speed) cannot be placed before or after the reference from
# the elongation alone (doing so pushes it a whole synodic cycle away in *both*
# directions).  It is refined as a root and placed by time: an event
# at the reference instant, within the solver tolerance, is the previous event;
# the next event is strictly later.  The prenatal syzygy is stricter still: it
# lies strictly before birth (previous_phase_strictly_before).
_PHASE_NEAR_REFERENCE_DEGREES = 1e-7
PHASE_DIRECTION_POLICY = {
    "previous": "last_event_at_or_before_reference_within_solver_tolerance",
    "next": "first_event_strictly_after_reference_beyond_solver_tolerance",
    "solver_tolerance_days": _PHASE_TOLERANCE_DAYS,
}


PhaseState = Callable[[float], tuple[float, float, int, int]]


def _refine_phase(
    guess_jd_ut: float, target_degrees: float, phase_state: PhaseState = _phase_state,
) -> tuple[float, int, int]:
    """The converged root nearest the guess: (jd_ut, Moon retflag, Sun retflag).

    A root counts only with |residual| <= 1e-7 degrees, so a returned event is
    converged; the residual and the search window are solver diagnostics.
    """

    half_window = _PHASE_BRACKET_DAYS
    while half_window <= 12.0:
        window_start = guess_jd_ut - half_window

        def separation_at(offset_days: float) -> float:
            elongation = phase_state(window_start + offset_days)[0]
            return _signed_degrees(elongation - target_degrees)

        roots = find_crossings_detailed(
            separation_at,
            window_days=2 * half_window,
            coarse_step_days=_PHASE_COARSE_STEP_DAYS,
            tolerance_days=_PHASE_TOLERANCE_DAYS,
        )
        valid = []
        for root in roots:
            jd_ut = window_start + root["t"]
            elongation, _speed, moon_retflag, sun_retflag = phase_state(jd_ut)
            residual = _signed_degrees(elongation - target_degrees)
            if abs(residual) <= 1e-7:
                valid.append((jd_ut, moon_retflag, sun_retflag))
        if valid:
            return min(valid, key=lambda value: abs(value[0] - guess_jd_ut))
        half_window *= 2

    elongation, _relative_speed, moon_retflag, sun_retflag = phase_state(guess_jd_ut)
    residual = _signed_degrees(elongation - target_degrees)
    if abs(residual) > 1e-7:
        raise swe.Error(f"Lunar phase root did not converge; residual={residual} degrees")
    return guess_jd_ut, moon_retflag, sun_retflag


def _phase_event(
    reference_jd_ut: float, phase: str, direction: str, phase_state: PhaseState = _phase_state,
) -> dict:
    target = PHASES[phase]
    elongation, relative_speed, _moon_retflag, _sun_retflag = phase_state(
        reference_jd_ut
    )
    if not math.isfinite(relative_speed) or relative_speed <= 0:
        raise swe.Error(
            f"Lunar phase search requires positive relative speed; got {relative_speed}"
        )
    synodic_guess_days = 360.0 / relative_speed
    if abs(_signed_degrees(elongation - target)) < _PHASE_NEAR_REFERENCE_DEGREES:
        near_jd_ut = _refine_phase(reference_jd_ut, target, phase_state)[0]
        near_is_previous = near_jd_ut <= reference_jd_ut + _PHASE_TOLERANCE_DAYS
        if direction == "previous":
            guess = (
                reference_jd_ut
                if near_is_previous
                else reference_jd_ut - synodic_guess_days
            )
        else:
            guess = (
                reference_jd_ut + synodic_guess_days
                if near_is_previous
                else reference_jd_ut
            )
    elif direction == "next":
        guess = reference_jd_ut + ((target - elongation) % 360.0) / relative_speed
    else:
        guess = reference_jd_ut - ((elongation - target) % 360.0) / relative_speed

    jd_ut, moon_retflag, sun_retflag = _refine_phase(guess, target, phase_state)
    return {
        "phase": phase,
        "target_elongation_degrees": target,
        "direction": direction,
        "jd_ut": jd_ut,
        "utc_time": jd_ut_to_iso_utc(jd_ut),
        "time_scale": time_scale_for_jd_ut(jd_ut),
        "calculation": "Moon-Sun apparent geocentric tropical longitude root",
        "retflag_moon": moon_retflag,
        "retflag_sun": sun_retflag,
    }


def previous_phase_strictly_before(
    reference_jd_ut: float, phase: str, phase_state: PhaseState = _phase_state,
) -> dict:
    """The last `phase` event strictly before the reference.

    The previous event of the direction policy may sit at the reference within
    the solver tolerance, a hair after it; for a birth at that instant it is
    the birth's own syzygy, not one before the birth.  The search then starts a
    day earlier and finds the occurrence a cycle before.
    """

    event = _phase_event(reference_jd_ut, phase, "previous", phase_state)
    if event["jd_ut"] >= reference_jd_ut:
        event = _phase_event(reference_jd_ut - 1.0, phase, "previous", phase_state)
    return event


def compute_primary_phases(reference_jd_ut: float, trace: Trace) -> dict:
    # Each root is rescanned and bisected again at every refinement depth on
    # grids that share points, and every event first reads the reference
    # instant: one Swiss read per instant for this call.  The state is a pure
    # function of the instant under PHASE_FLAGS; a refused read raises and is
    # not cached, and the cache ends with the call.
    phase_state = cache(_phase_state)
    results = {}
    for phase in PHASES:
        results[phase] = {
            "previous": _phase_event(reference_jd_ut, phase, "previous", phase_state),
            "next": _phase_event(reference_jd_ut, phase, "next", phase_state),
        }

    nearest = max(
        (
            results[phase]["previous"]
            if results[phase]["previous"]["jd_ut"] < reference_jd_ut
            else previous_phase_strictly_before(reference_jd_ut, phase, phase_state)
            for phase in ("new_moon", "full_moon")
        ),
        key=lambda event: event["jd_ut"],
    )
    prenatal_syzygy = {
        **nearest,
        "definition": "nearest_previous_geocentric_new_or_full_moon",
        "interpretation": None,
    }

    trace.add(
        "前後朔望弦與出生前朔望",
        formula=(
            "以 Moon-Sun 視地心回歸黃經差對 0°/90°/180°/270° "
            "作粗掃描、分割根區間與二分求根"
        ),
        inputs={
            "reference_JD_UT": reference_jd_ut,
            "flags": PHASE_FLAGS,
            "contract": "geocentric apparent tropical of-date",
        },
        result={
            phase: {
                direction: event["utc_time"]
                for direction, event in pair.items()
            }
            for phase, pair in results.items()
        },
        note=(
            "每個根的殘差都在 1e-7° 之內（未收斂即拒絕）。"
            "prenatal_syzygy 僅指出生前最近一次朔或望，不含古典技法解讀。"
        ),
    )
    return {
        "contract": "geocentric_apparent_tropical_of_date",
        "direction_policy": dict(PHASE_DIRECTION_POLICY),
        "primary_phases": results,
        "prenatal_syzygy": prenatal_syzygy,
    }


def _eclipse_type(retflag: int, lunar: bool) -> str:
    if retflag & swe.ECL_TOTAL:
        return "total"
    if not lunar and retflag & swe.ECL_ANNULAR_TOTAL:
        return "hybrid"
    if not lunar and retflag & swe.ECL_ANNULAR:
        return "annular"
    if retflag & swe.ECL_PARTIAL:
        return "partial"
    if lunar and retflag & swe.ECL_PENUMBRAL:
        return "penumbral"
    return "unknown"


# Contact labels come from one table chosen by kind and type, not one table
# shared by solar and lunar results and by every solar type (an annular eclipse
# has no `totality_begin`, and a solar center-line contact is not
# "penumbral_or_centerline").  Swiss tret indices
# (swecl.c, 2.10.03): solar sol_eclipse_when_glob — 2/3 eclipse begin/end, 4/5
# the central phase ("totality" in the Swiss comment whatever the type), 6/7
# center line begin/end; lunar lun_eclipse_when — 2/3 partial (umbral)
# begin/end, 4/5 totality begin/end, 6/7 penumbral begin/end.
_SOLAR_CONTACT_LABELS = {
    2: "partial_begin",
    3: "partial_end",
    6: "center_line_begin",
    7: "center_line_end",
}
_SOLAR_CENTRAL_PHASE_LABELS = {
    "total": ("totality_begin", "totality_end"),
    "annular": ("annularity_begin", "annularity_end"),
    "hybrid": ("central_phase_begin", "central_phase_end"),
}
_LUNAR_CONTACT_LABELS = {
    2: "partial_begin",
    3: "partial_end",
    4: "totality_begin",
    5: "totality_end",
    6: "penumbral_begin",
    7: "penumbral_end",
}
CONTACT_LABEL_VOCABULARY = {
    "solar": (
        "partial_begin", "partial_end",
        "totality_begin", "totality_end",
        "annularity_begin", "annularity_end",
        "central_phase_begin", "central_phase_end",
        "center_line_begin", "center_line_end",
    ),
    "lunar": (
        "partial_begin", "partial_end",
        "totality_begin", "totality_end",
        "penumbral_begin", "penumbral_end",
    ),
}
CONTACT_PHASES = {
    "partial_begin": "partial",
    "partial_end": "partial",
    "totality_begin": "total",
    "totality_end": "total",
    "annularity_begin": "annular",
    "annularity_end": "annular",
    "central_phase_begin": "hybrid_total_or_annular_by_track_position",
    "central_phase_end": "hybrid_total_or_annular_by_track_position",
    "center_line_begin": "center_line",
    "center_line_end": "center_line",
    "penumbral_begin": "penumbral",
    "penumbral_end": "penumbral",
}
CONTACT_LABEL_SOURCE = (
    "Swiss Ephemeris 2.10.03 swecl.c tret index documentation; labels chosen by "
    "eclipse kind and type"
)
HYBRID_CENTRAL_PHASE_NOTE = (
    "複合日食沿中心線一段為全食、一段為環食；Swiss 回報的中心相位開始與結束時刻"
    "不區分屬於哪一段，故標為 central_phase，不標 totality 或 annularity。"
)


def _contact_labels(kind: str, eclipse_type: str) -> dict[int, str]:
    if kind == "lunar":
        return dict(_LUNAR_CONTACT_LABELS)
    labels = dict(_SOLAR_CONTACT_LABELS)
    begin, end = _SOLAR_CENTRAL_PHASE_LABELS.get(
        eclipse_type, ("central_phase_begin", "central_phase_end")
    )
    labels[4] = begin
    labels[5] = end
    return labels


def _contacts(tret: tuple[float, ...], kind: str, eclipse_type: str) -> dict:
    contacts = {}
    for index, label in sorted(_contact_labels(kind, eclipse_type).items()):
        if tret[index] <= 0:
            continue
        phase = CONTACT_PHASES[label]
        if label.startswith("central_phase") and eclipse_type != "hybrid":
            phase = "central_phase_type_unclassified"
        contacts[label] = {
            "jd_ut": tret[index],
            "utc_time": jd_ut_to_iso_utc(tret[index]),
            "time_scale": time_scale_for_jd_ut(tret[index]),
            "phase": phase,
        }
    return contacts


# Which instant "maximum" names.
# Swiss's time of maximum differs from NASA's greatest eclipse (shadow axis
# closest to Earth's centre, in TD) and IMCCE's (largest magnitude).  Closed set.
ECLIPSE_INSTANT_DEFINITIONS = {
    "solar": "swiss_geocentric_minimum_limb_separation_of_sun_and_moon",
    "lunar": "swiss_minimum_limb_separation_of_sun_and_earth_seen_from_moon_centre",
}


# A solar eclipse type or centrality decided by a sign near zero.
# Swiss Ephemeris 2.10.03 (swecl.c eclipse_where / sol_eclipse_when_glob) calls an
# eclipse total or annular by the sign of the core-shadow diameter at maximum,
# hybrid when that sign changes at the central-phase begin or end, and central
# by whether the shadow axis meets the reference ellipsoid.  Near those zeros
# the class can differ from the NASA Five Millennium Canon without either being
# wrong at the stated precision: 7 of 1181 eclipses in 1900-2399 do, all inside
# the margin below (tests/backend/fixtures/nasa_eclipse_canon_selection.json).
# The rule is that fixture's classification margin applied to this product's own
# quantities: the Moon/Sun apparent diameter ratio at the greatest-eclipse ground
# point of each instant Swiss uses to decide the type, and gamma.
CLASSIFICATION_BORDERLINE_STATES = (
    "inside_classification_margin",
    "outside_classification_margin",
    "no_criterion_for_lunar_eclipses",
)
CLASSIFICATION_BORDERLINE_REASONS = (
    "diameter_ratio_near_one",
    "hybrid_type",
    "shadow_axis_grazes_earth_limb",
)
CLASSIFICATION_DIAMETER_RATIO_MARGIN = 0.001
CLASSIFICATION_GAMMA_BAND = (0.99, 1.005)
CLASSIFICATION_BORDERLINE_SOURCE_REF = "eclipses/classification_borderline"
# The state must be readable by a person, not only by
# a program.  One plain zh-TW explanation per state, and for the borderline
# state one clause per reason, travel with every eclipse as explanation_zh; the
# result page shows that string as it is (frontend/zh-TW/view-model.js), so the
# wording has this one producer.
CLASSIFICATION_BORDERLINE_REASON_CLAUSES_ZH = {
    "diameter_ratio_near_one": (
        "從地面看，月亮和太陽幾乎一樣大（兩者大小的比例與 1 相差在 "
        f"{CLASSIFICATION_DIAMETER_RATIO_MARGIN:g} 以內），全食與環食只差一線"
    ),
    "hybrid_type": "這是複合日食，沿著日食帶有些地方看到全食、有些地方看到環食",
    "shadow_axis_grazes_earth_limb": (
        "月影的中心線幾乎擦過地球邊緣，算不算「中心食」只差一線"
    ),
}
CLASSIFICATION_BORDERLINE_EXPLANATIONS_ZH = {
    "inside_classification_margin": (
        "分類近邊界。原因：{reasons}。這種情況下，本站使用的 Swiss Ephemeris 與 NASA"
        "《五千年日食典》（Five Millennium Canon of Solar Eclipses）可能把這次日食判成不同類型（或一個判中心食、一個判非中心食），"
        "兩種判法在目前的計算精度內都說得通；食甚時刻不受影響。若要引用這次日食的類型，"
        "請註明它是邊界情況，或一併對照 NASA 日食典。"
    ),
    "outside_classification_margin": (
        "這次日食的類型不在分類邊界附近，類型判定沒有這方面的保留。"
    ),
    "no_criterion_for_lunar_eclipses": (
        "月食的類型目前沒有做邊界檢查；這裡列的是 Swiss Ephemeris 的判定。"
    ),
}


def classification_borderline_explanation_zh(state: str, reasons: list[str]) -> str:
    """The plain-language sentence for one classification_borderline record."""

    template = CLASSIFICATION_BORDERLINE_EXPLANATIONS_ZH[state]
    if state != CLASSIFICATION_BORDERLINE_STATES[0]:
        return template
    return template.format(
        reasons="；".join(CLASSIFICATION_BORDERLINE_REASON_CLAUSES_ZH[r] for r in reasons)
    )
_AU_KM = 149597870.700
_EARTH_EQUATORIAL_RADIUS_KM = 6378.137
_GAMMA_FLAGS = swe.FLG_SWIEPH | swe.FLG_EQUATORIAL | swe.FLG_XYZ


def _equatorial_vector_earth_radii(jd_ut: float, body: int, label: str) -> list[float]:
    values, retflag = swe.calc_ut(jd_ut, body, _GAMMA_FLAGS)
    require_full_ephemeris(retflag, operation=f"日食 gamma（{label}）", jd_ut=jd_ut)
    return [value * _AU_KM / _EARTH_EQUATORIAL_RADIUS_KM for value in values[:3]]


def _solar_eclipse_gamma(jd_ut: float) -> float:
    """Signed distance of the shadow axis from Earth's centre, equatorial radii.

    Geocentric apparent equatorial vectors of date at ``jd_ut``; positive when
    the axis passes north of the centre (the canon's sign).  At the instant of
    maximum the distance is near its minimum, so seconds between Swiss maximum
    and NASA greatest eclipse change it by less than 1e-5.
    """

    sun = _equatorial_vector_earth_radii(jd_ut, swe.SUN, "太陽")
    moon = _equatorial_vector_earth_radii(jd_ut, swe.MOON, "月球")
    axis = [s - m for s, m in zip(sun, moon)]
    length = math.sqrt(sum(c * c for c in axis))
    axis = [c / length for c in axis]
    along = sum(m * a for m, a in zip(moon, axis))
    offset = [m - along * a for m, a in zip(moon, axis)]
    north = [-axis[2] * a for a in axis]
    north[2] += 1.0
    distance = math.sqrt(sum(c * c for c in offset))
    return math.copysign(distance, sum(o * n for o, n in zip(offset, north)))


def _diameter_ratio(jd_ut: float) -> float:
    # sol_eclipse_where -> eclipse_how calls swe_set_topo with the ground point
    # it found, the same call sol_eclipse_when_glob makes at the maximum.
    with chart_observer_restored():
        _flag, _geopos, attr = swe.sol_eclipse_where(jd_ut, swe.FLG_SWIEPH)
    return attr[1]


def _classification_borderline(
    kind: str, eclipse_type: str, centrality: str | None, tret: tuple[float, ...]
) -> dict:
    states = CLASSIFICATION_BORDERLINE_STATES
    if kind == "lunar":
        return {
            "state": states[2],
            "reasons": [],
            "gamma_earth_radii": None,
            "moon_sun_diameter_ratio": None,
            "explanation_zh": classification_borderline_explanation_zh(states[2], []),
            "source_ref": CLASSIFICATION_BORDERLINE_SOURCE_REF,
        }
    ratio_near_one, hybrid, grazing = CLASSIFICATION_BORDERLINE_REASONS
    reasons = []
    ratios = None
    if eclipse_type in ("annular", "total", "hybrid"):
        instants = {
            name: tret[index]
            for name, index in (("central_phase_begin", 4), ("central_phase_end", 5))
            if tret[index] > 0
        }
        # The maximum last: the global search left the topocentric observer at
        # this instant's ground point, and the residual state must not move.
        instants["maximum"] = tret[0]
        ratios = {name: _diameter_ratio(jd_ut) for name, jd_ut in instants.items()}
        if any(
            abs(ratio - 1.0) <= CLASSIFICATION_DIAMETER_RATIO_MARGIN
            for ratio in ratios.values()
        ):
            reasons.append(ratio_near_one)
    if eclipse_type == "hybrid":
        reasons.append(hybrid)
    gamma = _solar_eclipse_gamma(tret[0])
    low, high = CLASSIFICATION_GAMMA_BAND
    if centrality is not None and low <= abs(gamma) <= high:
        reasons.append(grazing)
    state = states[0] if reasons else states[1]
    return {
        "state": state,
        "reasons": reasons,
        "gamma_earth_radii": gamma,
        "moon_sun_diameter_ratio": ratios,
        "explanation_zh": classification_borderline_explanation_zh(state, reasons),
        "source_ref": CLASSIFICATION_BORDERLINE_SOURCE_REF,
    }


def _eclipse_result(kind: str, retflag: int, tret: tuple[float, ...]) -> dict:
    lunar = kind == "lunar"
    retflags: dict[int, int] = {}
    for body, label in ((swe.SUN, "太陽"), (swe.MOON, "月球")):
        retflags[body] = swe.calc_ut(tret[0], body, swe.FLG_SWIEPH)[1]
        require_full_ephemeris(
            retflags[body],
            operation=f"{'月食' if lunar else '日食'}事件（{label}位置）",
            jd_ut=tret[0],
        )
    centrality = None
    if not lunar:
        if retflag & swe.ECL_CENTRAL:
            centrality = "central"
        elif retflag & swe.ECL_NONCENTRAL:
            centrality = "noncentral"
    eclipse_type = _eclipse_type(retflag, lunar)
    return {
        "kind": kind,
        "type": eclipse_type,
        "centrality": centrality,
        "retflag": retflag,
        "retflag_sun": retflags[swe.SUN],
        "retflag_moon": retflags[swe.MOON],
        "jd_ut_maximum": tret[0],
        "utc_time_maximum": jd_ut_to_iso_utc(tret[0]),
        "instant_definition": ECLIPSE_INSTANT_DEFINITIONS[kind],
        "instant_definition_source_ref": "eclipses/maximum",
        "time_scale": time_scale_for_jd_ut(tret[0]),
        "contacts": _contacts(tret, kind, eclipse_type),
        # The label sets and their source are constant: register entry
        # eclipses/contact_labels.
        "contact_label_source_ref": "eclipses/contact_labels",
        "central_phase_note": (
            HYBRID_CENTRAL_PHASE_NOTE if eclipse_type == "hybrid" else None
        ),
        "classification_borderline": _classification_borderline(
            kind, eclipse_type, centrality, tret
        ),
        "calculation": (
            "swe.lun_eclipse_when(backwards=True)"
            if lunar
            else "swe.sol_eclipse_when_glob(backwards=True)"
        ),
    }


def compute_previous_eclipses(reference_jd_ut: float, trace: Trace) -> dict:
    start = math.nextafter(reference_jd_ut, -math.inf)
    with chart_observer_restored():
        solar_flag, solar_times = swe.sol_eclipse_when_glob(
            start, swe.FLG_SWIEPH, 0, True
        )
    lunar_flag, lunar_times = swe.lun_eclipse_when(start, swe.FLG_SWIEPH, 0, True)
    solar = _eclipse_result("solar", solar_flag, solar_times)
    lunar = _eclipse_result("lunar", lunar_flag, lunar_times)
    trace.add(
        "出生前最近日食／月食",
        formula="Swiss Ephemeris global eclipse search, backwards=True",
        inputs={"reference_JD_UT": reference_jd_ut, "flags": swe.FLG_SWIEPH},
        result={
            "solar": solar["utc_time_maximum"],
            "lunar": lunar["utc_time_maximum"],
        },
        note="只回報天文事件與 Swiss 類型，不提供古典占星解讀。",
    )
    return {
        "previous_solar": solar,
        "previous_lunar": lunar,
        "interpretation": None,
    }


METHOD_SOURCE_ENTRIES: dict[str, dict] = {
    CLASSIFICATION_BORDERLINE_SOURCE_REF: {
        "applies_to": (
            "astronomical_data.lunar_events.eclipses.previous_*."
            "classification_borderline"
        ),
        "states": list(CLASSIFICATION_BORDERLINE_STATES),
        "reasons": {
            "diameter_ratio_near_one": (
                "an annular, total or hybrid eclipse whose Moon/Sun apparent "
                "diameter ratio at the greatest-eclipse ground point is within "
                f"{CLASSIFICATION_DIAMETER_RATIO_MARGIN} of 1 at the maximum or "
                "at the central-phase begin or end"
            ),
            "hybrid_type": (
                "a hybrid eclipse, whose annular segment may be confined to the "
                "sunrise or sunset ends of the track"
            ),
            "shadow_axis_grazes_earth_limb": (
                "a central or non-central eclipse with "
                f"{CLASSIFICATION_GAMMA_BAND[0]} <= |gamma| <= "
                f"{CLASSIFICATION_GAMMA_BAND[1]}"
            ),
        },
        "quantities": {
            "gamma_earth_radii": (
                "signed distance of the shadow axis from Earth's centre at the "
                "Swiss maximum, in Earth equatorial radii (6378.137 km), from "
                "geocentric apparent equatorial vectors of date; positive north"
            ),
            "moon_sun_diameter_ratio": (
                "Swiss sol_eclipse_where attr[1] at each instant Swiss uses to "
                "decide the type"
            ),
        },
        "sources": [
            {
                "citation": (
                    "Swiss Ephemeris 2.10.03 swecl.c: eclipse_where, "
                    "sol_eclipse_when_glob, swe_sol_eclipse_where"
                ),
                "says": "the functions that find the eclipse type and its maximum",
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Swiss Ephemeris 2.10.03 source file swecl.c",
            },
            {
                "citation": (
                    "NASA GSFC Five Millennium Canon of Solar Eclipses (Espenak & Meeus, "
                    "NASA/TP-2006-214141)"
                ),
                "says": "type, gamma and magnitude columns",
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the canon's type, gamma and magnitude columns",
            },
        ],
        "note": (
            "Over 1181 solar eclipses 1900-2399 the Swiss type or centrality "
            "differs from the NASA canon in 7 cases, all within the canon's own "
            "classification margin. Inside the margin both classifications are "
            "defensible at the stated precision; outside it they agree. Lunar "
            "eclipse classes have no criterion here."
        ),
    },
    "eclipses/maximum": {
        "applies_to": "astronomical_data.lunar_events.eclipses.previous_*.instant_definition",
        "instant_definitions": dict(ECLIPSE_INSTANT_DEFINITIONS),
        "sources": [
            {
                "citation": (
                    "Swiss Ephemeris Programming Interface (2.10.03) §8.3, §8.10, and "
                    "swecl.c"
                ),
                "says": "time of maximum eclipse",
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "the Swiss Ephemeris 2.10.03 documentation and source file swecl.c",
            },
            {
                "citation": "NASA GSFC, Key to Solar Eclipse Maps and Glossary",
                "says": (
                    "greatest eclipse is the instant the shadow axis passes closest to "
                    "Earth's centre, in dynamical time"
                ),
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "NASA GSFC's own text",
            },
            {
                "citation": "IMCCE, Éclipses de Soleil",
                "says": "maximum is the instant of largest magnitude",
                "reading": SOURCE_READING_LEVELS[0],
                "read_at": "IMCCE's own French text",
            },
        ],
        "note": (
            "The three definitions name different instants; external comparison "
            "with NASA greatest eclipse differs by seconds."
        ),
    },
    "eclipses/contact_labels": {
        "applies_to": "astronomical_data.lunar_events.eclipses.previous_*.contacts",
        "vocabulary": {kind: list(labels) for kind, labels in CONTACT_LABEL_VOCABULARY.items()},
        "source": CONTACT_LABEL_SOURCE,
    },
}
