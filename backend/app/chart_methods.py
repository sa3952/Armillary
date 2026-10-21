"""Stage 3 of the chart pipeline: derived geometry and the classical methods
(``DerivedChart``)."""

import datetime as dtmod

import swisseph as swe

from .core.invariants import InternalInvariantError
from .domain_catalog import BODY_ID_BY_KEY, CLASSICAL_BODIES, DECLINATION_ASPECT_ORB
from .ephemeris import FullEphemerisRequiredError
from .core.time_utils import (
    civil_hour_spans,
    civil_instant,
    representative_sample_instants,
    utc_datetime_to_jd_ut,
)
from .core.bodies import (
    effective_participants,
    geocentric_sun_true_altitude,
    geocentric_true_altitude,
    participant_policy_receipt,
)
from .core.essential_dignities import (
    DignitySect,
    DignitySelection,
    compute_essential_dignities,
)
from .core.aspects import (
    AspectSettings,
    aspects_not_applicable,
    compute_aspects,
    orb_profile_selection,
)
from .core.declination import compute_declination_aspects, declination_aspects_not_applicable
from .core.birth_time_sensitivity import DIFFERS_BETWEEN_SAMPLES, SAME_AT_ALL_SAMPLES
from .core.lots import (
    LOTS_FORMULA_PROFILE, LOTS_METHOD_PROVENANCE,
    compute_lots, classify_sect, determine_sect, lots_not_applicable,
)
from .core.extended_lots import attach_extended_lots
from .core.antiscia import antiscia_not_applicable, compute_antiscia
from .core.dodecatemoria import compute_dodecatemoria, dodecatemoria_not_applicable
from .core.classical_classifications import (
    classical_classifications_not_applicable,
    compute_classical_classifications,
)
from .core.moon import evaluate_void_of_course, voc_receipt_head, void_of_course_not_applicable
from .core.planetary_hours import compute_planetary_hours, planetary_hours_not_applicable
from .core.lunar_mansions import (
    compute_lunar_mansions,
    lunar_mansions_not_applicable,
    lunar_mansions_unavailable,
)
from .core.motion_states import (
    compute_motion_states,
    make_speed_sampler,
    motion_states_not_applicable,
    motion_states_unavailable,
)
from .core.solar_phase import (
    EclipticSampler,
    EventClock,
    compute_solar_phase,
    make_ecliptic_sampler,
    solar_phase_not_applicable,
    solar_phase_unavailable,
)
from .core.module_state import unavailable_state as _unavailable_state
from .chart_stages import AstronomicalFacts, DerivedChart, JsonObject, TimeResolution
from .chart_time import _event_search_refusal
from .chart_astronomy import _event_time_basis


_CLASSICAL_KEYS = tuple(body["key"] for body in CLASSICAL_BODIES)

def _aspect_participants(
    options,
    bodies_all: list,
    lots: dict,
    angles: dict,
    *,
    angle_aspects_applicable: bool,
) -> list[dict]:
    # 與赤緯相位、反照點同一個 effective_participants；交點鍵取自實際 bodies 紀錄，
    # 明示要求的南交點因此一定在內。
    participants = [
        {
            "key": body["key"],
            "name": body["name"],
            "longitude": body["longitude"],
            "speed_longitude": body["speed_longitude"],
            # 導出的南交點不是獨立 Swiss body，沒有取樣器 → 成相時刻記為 no_motion_model。
            "body_id": BODY_ID_BY_KEY.get(body["key"]),
            "category": body["participant_category"],
        }
        for body in effective_participants(
            bodies_all,
            include_nodes=options.aspect_include_nodes,
            include_outer_planets=options.include_outer_planets,
        )
    ]

    point_groups = (
        (lots or {}, (("fortune", "命運點"), ("spirit", "精神點")), "lot", options.include_lots),
        # 天頂（zenith）是觀測者正上方，不是 MC；全站 MC 稱「中天」。
        (angles, (("asc", "上升點"), ("mc", "中天")), "angle", options.aspect_include_angles and angle_aspects_applicable),
    )
    for values, definitions, category, enabled in point_groups:
        if enabled:
            for key, name in definitions:
                longitude = values.get(key)
                if longitude is None:
                    continue
                participants.append({
                    "key": key, "name": name, "longitude": longitude,
                    "speed_longitude": None, "body_id": None,
                    "category": category,
                })
    return participants


def _antiscia(facts: AstronomicalFacts) -> JsonObject:
    # derived_geometry：純幾何轉換，不做「是否成立」的判斷。
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    antiscia_frame = time.frame_states["antiscia"]
    if not req.options.include_antiscia:
        return {}
    if not antiscia_frame["applicable"]:
        # The mirror axis is the solstitial axis of date; outside that frame, refuse.
        return antiscia_not_applicable(antiscia_frame, trace)
    # Adopted scope: classical seven, plus nodes only when explicitly requested.
    # 同一個參與者 helper：交點鍵取自實際紀錄，含明示要求的南交點。
    antiscia_input = effective_participants(
        positions.bodies_all,
        include_nodes=req.options.antiscia_include_nodes,
        include_outer_planets=False,
    )
    antiscia = compute_antiscia(
        antiscia_input,
        trace,
        ayanamsa=time.time_conversion["ayanamsa"] or 0.0,
    )
    antiscia["scope"] = {
        "included": (
            ["classical_planets", "lunar_nodes"]
            if req.options.antiscia_include_nodes
            else ["classical_planets"]
        ),
        "excluded": (
            ["fixed_stars", "angles", "outer_planets", "lots"]
            + ([] if req.options.antiscia_include_nodes else ["lunar_nodes"])
        ),
        "included_keys": [body["key"] for body in antiscia_input],
        "semantics": (
            "geometric_mirror_coordinates_only_no_relationship_verdict_no_orb"
        ),
        # 七政有 Firmicus II.29 與 Lilly 1647 的逐度見證；交點作為 antiscia
        # 參與者未找到直接見證（方法研究筆記的有界負面結果，未經第三方核對）。
        # 南交點＝北交點＋180°，故 antiscion(南)＝contra-antiscion(北)；照實並列，不去重。
        "historical_method_status": {
            "classical_planets": "attested_firmicus_ii_29_and_lilly_1647",
            "lunar_nodes": "not_established",
        },
    }
    return antiscia




def _sect_and_lots(
    facts: AstronomicalFacts, sect_sun_altitude: float | None
) -> tuple[JsonObject | None, JsonObject]:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    if not req.options.include_lots:
        return None, {}
    if req.options.include_houses:
        sect = determine_sect(
            sect_sun_altitude,
            trace,
            display_center=req.computation_mode.center,
        )
        # The frame table decides; the Lots are placed with the planet
        # half-open cusp rule against the same house division.
        lots_frame = time.frame_states["lots"]
        if not lots_frame["applicable"]:
            return sect, lots_not_applicable(lots_frame, sect, trace)
        if facts.houses.asc is None:
            raise RuntimeError("the ascendant must exist when lots are applicable")
        lots = compute_lots(
            facts.houses.asc,
            positions.bodies_by_key["sun"]["longitude"],
            positions.bodies_by_key["moon"]["longitude"],
            sect,
            trace,
            houses=facts.houses.houses,
        )
        # The Paulus and Valens lots share the Fortune/Spirit sect candidate
        # and are placed in the same user-selected house division.
        attach_extended_lots(
            lots, ascendant=facts.houses.asc, bodies_by_key=positions.bodies_by_key,
            houses=facts.houses.houses,
        )
        return sect, lots
    unavailable = {
        **_unavailable_state("house_calculation_not_executed", requested=True),
        "method": None,
        "method_status": None,
        "period": None,
        "name_status": None,
        "execution_status": "not_applicable",
        "source": None,
    }
    trace.add(
        "Sect 與 Lots",
        inputs={"include_lots": True, "include_houses": False},
        result={"execution_status": "not_applicable"},
        note="Lots 依賴 ASC；無宮位模式不以代表性時刻產生 ASC 或 Sect 下游判定。",
    )
    return (
        {**unavailable, "is_day": None, "sect_status": None},
        {
            **unavailable,
            # The same keys as the frame-table refusal of the Lots.
            "method_provenance": LOTS_METHOD_PROVENANCE,
            "formula_profile": LOTS_FORMULA_PROFILE,
            "fortune": None,
            "spirit": None,
            "formula_basis": None,
            "sect_status": None,
            "sect_applied": None,
            "by_sect": None,
            "house_placement": None,
        },
    )


def _void_of_course(facts: AstronomicalFacts) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    voc_frame = time.frame_states["void_of_course"]
    if not req.options.include_void_of_course:
        return {}
    if not voc_frame["applicable"]:
        return {
            **void_of_course_not_applicable(
                voc_frame, trace, req.options.void_of_course_method
            ),
            "time_basis": None,
        }
    try:
        # The verdict holds at one instant: the birth instant, or for an hour
        # or a date the representative anchor, which time_basis names.
        return {
            **evaluate_void_of_course(
                positions.bodies_all, trace, jd_ut=time.jd_ut,
                longitude_at=positions.longitude_at,
                method=req.options.void_of_course_method,
            ),
            "time_basis": _event_time_basis(time),
        }
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("月空亡(VOC)", error, trace)
        return {
            **voc_receipt_head(req.options.void_of_course_method),
            # The six state fields only; VOC carries no event status word.
            **{key: value for key, value in refusal.items() if key != "status"},
            "verdict": "not_evaluated",
            "is_void_of_course": None,
            "time_to_sign_exit_hours": None,
            "all_candidates": [],
            "time_basis": None,
        }


def _declination_aspects(facts: AstronomicalFacts) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    declination_frame = time.frame_states["declination_aspects"]
    if not req.options.include_declination_aspects:
        return {}
    if not declination_frame["applicable"]:
        return declination_aspects_not_applicable(declination_frame, trace)
    declination_inputs = effective_participants(
        positions.bodies_all,
        include_nodes=req.options.aspect_include_nodes,
        include_outer_planets=req.options.include_outer_planets,
    )
    return compute_declination_aspects(
        declination_inputs,
        req.options.declination_aspect_orb_degrees,
        trace,
        default_orb=DECLINATION_ASPECT_ORB,
        orb_explicit=(
            "declination_aspect_orb_degrees"
            in time.input_request.options.model_fields_set
        ),
        participant_policy=participant_policy_receipt(
            [body for body in declination_inputs if body.get("declination") is not None],
            include_nodes=req.options.aspect_include_nodes,
            include_outer_planets=req.options.include_outer_planets,
        ),
    )


def _aspects(facts: AstronomicalFacts, lots: JsonObject) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    aspects_frame = time.frame_states["aspects"]
    if not req.options.include_aspects:
        return {}
    if not aspects_frame["applicable"]:
        return aspects_not_applicable(aspects_frame, trace)
    # Aspects run only in the frame the angles share (the aspects row of the
    # frame table), so the angles take part whenever the houses ran.
    angle_aspects_applicable = req.options.include_houses
    return compute_aspects(
        _aspect_participants(
            req.options,
            positions.bodies_all,
            lots,
            facts.houses.angles,
            angle_aspects_applicable=angle_aspects_applicable,
        ),
        trace,
        settings=AspectSettings(
            orb_profile_key=req.options.aspect_orb_profile,
            aspect_set_profile_key=req.options.aspect_set_profile,
            orb_scale_percent=req.options.aspect_orb_scale_percent,
            fixed_orb_degrees=req.options.aspect_fixed_orb_degrees,
            angle_orb_degrees=req.options.aspect_angle_orb_degrees,
            angles_requested=req.options.aspect_include_angles,
            angles_applicable=angle_aspects_applicable,
            partile_profile_key=req.options.partile_profile,
            orb_profile_selection_state=orb_profile_selection(req.options),
            include_perfection=req.options.include_aspect_perfection,
            jd_ut=time.jd_ut,
            longitude_at=positions.longitude_at,
        ),
    )


def _essential_dignities(
    facts: AstronomicalFacts, sect_sun_altitude: float | None
) -> JsonObject | None:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    # The dignities read the same sect producer as the Lots, classify_sect,
    # rather than restating the >0° rule or the band here.
    dignity_sect = classify_sect(None)
    dignity_sect_basis = "unavailable_date_only"
    if time.input_request.birth_time_precision != "date_only" and time.context.horizon_meaningful:
        dignity_sect = classify_sect(sect_sun_altitude)
        dignity_sect_basis = (
            "sun_center_true_altitude_gt_zero_v1_exact_birth_time"
            if time.input_request.birth_time_precision == "exact"
            else (
                "sun_center_true_altitude_gt_zero_v1_"
                + time.time_conversion["input_semantics"]
            )
        )
    elif not time.context.horizon_meaningful:
        dignity_sect_basis = "unavailable_for_display_center"
    return compute_essential_dignities(
        bodies=[body for body in positions.bodies if body["key"] in _CLASSICAL_KEYS],
        selection=DignitySelection(
            include_domicile_exaltation=req.options.include_domicile_exaltation,
            bounds_profile=req.options.bounds_profile,
            decan_profile=req.options.decan_profile,
            triplicity_profile=req.options.triplicity_profile,
            include_triplicity_comparison=req.options.triplicity_include_research_comparison,
            peregrine_profile=req.options.peregrine_profile,
        ),
        computation_mode=req.computation_mode,
        sect=DignitySect(
            basis=dignity_sect_basis,
            sun_altitude=sect_sun_altitude,
            classification=dignity_sect,
        ),
        trace=trace,
    )


def _birth_time_interval_spans(time: TimeResolution) -> tuple[str | None, list | None]:
    """The half-open JD(UT) stretches a non-exact birth time may lie in.

    approximate_hour: every UTC stretch the zone labels with the stated hour in
    the named fold (``civil_hour_spans``), which is two stretches when the clock
    leaves the hour and comes back to it; date_only: every UTC stretch the zone
    labels with the date.
    """

    input_request = time.input_request
    precision = input_request.birth_time_precision
    if precision == "date_only":
        if time.civil_day is None:  # resolved for every date_only chart
            raise InternalInvariantError("time.civil_day is not None")
        return "civil_day", [
            (utc_datetime_to_jd_ut(start), utc_datetime_to_jd_ut(end))
            for start, end in time.civil_day["spans"]
        ]
    if precision == "approximate_hour":
        value = input_request.datetime
        hour_start = dtmod.datetime(value.year, value.month, value.day, value.hour)
        return "stated_civil_hour", [
            (utc_datetime_to_jd_ut(start), utc_datetime_to_jd_ut(end))
            for start, end in civil_hour_spans(input_request.timezone, hour_start)
        ]
    return None, None


def _planetary_hours(facts: AstronomicalFacts) -> JsonObject:
    """Planetary day and hours: basic output, computed for every chart."""

    time = facts.time
    req, trace = time.request, time.trace
    frame = time.frame_states["planetary_hours"]
    if not frame["applicable"]:
        return planetary_hours_not_applicable(
            frame["reason_code"], executed=False, trace=trace
        )
    interval, spans = _birth_time_interval_spans(time)
    try:
        return compute_planetary_hours(
            reference_jd_ut=time.jd_ut,
            interval_spans=spans,
            interval=interval,
            time_basis=_event_time_basis(time),
            location=req.location,
            atmosphere=req.atmosphere,
            tz_input=time.input_request.timezone,
            trace=trace,
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("行星日與行星時", error, trace)
        return planetary_hours_not_applicable(
            refusal["reason_code"],
            executed=refusal["executed"],
            applicable=refusal["applicable"],
        )


# Twelfth-parts: an optional natal technique, read off emitted positions.
def _dodecatemoria(facts: AstronomicalFacts, lots: JsonObject) -> JsonObject:
    time = facts.time
    req, trace = time.request, time.trace
    if not req.options.include_dodecatemoria:
        return {}
    frame = time.frame_states["dodecatemoria"]
    if not frame["applicable"]:
        return dodecatemoria_not_applicable(frame, trace, req.options.dodecatemoria_profile)
    planets = effective_participants(
        facts.positions.bodies_all, include_nodes=False, include_outer_planets=False
    )
    angles = facts.houses.angles if facts.houses.angles.get("available") else None
    return compute_dodecatemoria(
        planets=planets,
        angles=angles,
        lots=lots if lots and lots.get("available") else None,
        profile=req.options.dodecatemoria_profile,
        trace=trace,
    )


def _classical_classifications(
    facts: AstronomicalFacts, sect_sun_altitude: float | None
) -> JsonObject:
    time, positions = facts.time, facts.positions
    req, trace = time.request, time.trace
    if not time.input_request.options.include_classical_classifications:
        return {}
    frame = time.frame_states["classical_classifications"]
    if not frame["applicable"]:
        return classical_classifications_not_applicable(frame, trace)
    timed = time.input_request.birth_time_precision != "date_only"
    planets = [body for body in positions.bodies if body["key"] in _CLASSICAL_KEYS]
    ids = {item["key"]: item["id"] for item in positions.body_defs}
    # The planets were just computed at this instant from the same files, so
    # their altitudes read nothing the chart has not read already.
    altitudes = (
        {
            body["key"]: geocentric_true_altitude(
                time.jd_ut, time.context, req.atmosphere, ids[body["key"]]
            )
            for body in planets
        }
        if timed
        else None
    )
    module = facts.houses.planet_in_house
    placements = (
        {place["key"]: place["house"] for place in module["placements"]}
        if isinstance(module, dict) and module.get("execution_status") == "computed"
        else None
    )
    result = compute_classical_classifications(
        planets=planets,
        altitudes=altitudes,
        sect=classify_sect(sect_sun_altitude) if timed else None,
        placements=placements,
        trace=trace,
    )
    if result.get("chart_sect") is not None:
        result["chart_sect"].update(_sect_across_stated_hour(time))
    return result


def _sect_across_stated_hour(time: TimeResolution) -> JsonObject:
    """Day or night at each representative sample of a stated hour.

    The classifications follow one sect, read at the representative instant;
    when the Sun crosses the horizon inside the stated hour the sect, and so
    sect membership, halb and hayyiz, change within it.  Only the sect is
    probed: it is the one input of the module that flips as a whole.
    """

    input_request = time.input_request
    if input_request.birth_time_precision != "approximate_hour":
        return {"across_stated_hour": None, "sample_is_day": None}
    if time.anchor_utc is None:  # resolved for every non-exact chart
        raise InternalInvariantError("time.anchor_utc is not None")
    instants = representative_sample_instants(
        input_request.datetime,
        input_request.timezone,
        precision="approximate_hour",
        anchor_utc=time.anchor_utc,
    )
    try:
        sample_is_day = [
            classify_sect(
                geocentric_sun_true_altitude(
                    instant["reference_jd_ut"], time.context, time.request.atmosphere
                )
            )["is_day"]
            for instant in instants
        ]
    except FullEphemerisRequiredError:
        return {"across_stated_hour": None, "sample_is_day": None}
    state = (
        SAME_AT_ALL_SAMPLES if len(set(sample_is_day)) == 1 else DIFFERS_BETWEEN_SAMPLES
    )
    return {"across_stated_hour": state, "sample_is_day": sample_is_day}


def _lunar_mansions(facts: AstronomicalFacts) -> JsonObject:
    """The Moon's mansion; for a non-exact birth time, every mansion it is in."""

    time, positions = facts.time, facts.positions
    trace = time.trace
    if not time.input_request.options.include_lunar_mansions:
        return {}
    frame = time.frame_states["lunar_mansions"]
    if not frame["applicable"]:
        return lunar_mansions_not_applicable(frame, trace)
    interval, spans = _birth_time_interval_spans(time)
    try:
        # The core chart prints a Moshier Moon when its segment file is missing
        # and says so (used_full_ephemeris); a mansion read off that Moon is
        # refused as every module that samples the Moon itself refuses it.
        moon = next(body for body in positions.bodies if body["key"] == "moon")
        if moon.get("used_full_ephemeris") is not True:
            raise FullEphemerisRequiredError(
                operation="月宿（月亮位置）", jd_ut=time.jd_ut, retflag=0,
                reason="segment_file_missing",
            )
        moon_at_ends = (
            None
            if spans is None
            else [
                (
                    positions.longitude_at(swe.MOON, start),
                    positions.longitude_at(swe.MOON, end),
                )
                for start, end in spans
            ]
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("月宿", error, trace)
        return lunar_mansions_unavailable(refusal)
    return compute_lunar_mansions(
        positions.bodies,
        trace,
        time_basis=_event_time_basis(time),
        interval=interval,
        interval_moon_longitudes=moon_at_ends,
    )


def _event_clock(
    time: TimeResolution,
    sample: EclipticSampler,
    interval: str | None,
    spans: list | None,
) -> EventClock:
    """The chart instant, its birth-place labels and the birth-time stretches."""

    return EventClock(
        time_basis=_event_time_basis(time),
        jd_ut=time.jd_ut,
        instant_of=lambda jd: civil_instant(jd, time.input_request.timezone),
        sample=sample,
        interval=interval,
        interval_spans=spans,
    )


def _solar_phase(facts: AstronomicalFacts) -> JsonObject:
    """Each planet's and the Moon's distance from the Sun and its band."""

    time, positions = facts.time, facts.positions
    options = time.input_request.options
    if not options.include_solar_phase:
        return {}
    frame = time.frame_states["solar_phase"]
    if not frame["applicable"]:
        return solar_phase_not_applicable(frame, time.trace)
    flags = time.context.base_flags
    # The effective Moon: topocentric under the Moon-only profile.
    moon_topocentric = (
        time.request.options.moon_position_profile == "moon_only_topocentric_v1"
        or time.request.computation_mode.center == "topocentric"
    )
    moon_flags = flags | swe.FLG_TOPOCTR if moon_topocentric else flags
    interval, spans = _birth_time_interval_spans(time)
    try:
        return compute_solar_phase(
            positions.bodies,
            time.trace,
            profile=options.solar_phase_profile,
            disc_cazimi=options.solar_phase_disc_cazimi,
            moon_center="topocentric" if moon_topocentric else "geocentric",
            sun_flags=flags,
            clock=_event_clock(time, make_ecliptic_sampler(flags, moon_flags), interval, spans),
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("焦傷與光束下", error, time.trace)
        return solar_phase_unavailable(refusal)


def _motion_states(facts: AstronomicalFacts) -> JsonObject:
    """Swift or slow, stationary, and oriental or occidental of the Sun."""

    time, positions = facts.time, facts.positions
    if not time.input_request.options.include_motion_states:
        return {}
    frame = time.frame_states["motion_states"]
    if not frame["applicable"]:
        return motion_states_not_applicable(frame, time.trace)
    flags = time.context.base_flags
    # The side of the Sun reads the effective Moon, as solar_phase does.
    moon_topocentric = (
        time.request.options.moon_position_profile == "moon_only_topocentric_v1"
        or time.request.computation_mode.center == "topocentric"
    )
    interval, spans = _birth_time_interval_spans(time)
    try:
        return compute_motion_states(
            positions.bodies,
            time.trace,
            speed=make_speed_sampler(flags),
            clock=_event_clock(
                time,
                make_ecliptic_sampler(
                    flags, flags | swe.FLG_TOPOCTR if moon_topocentric else flags
                ),
                interval,
                spans,
            ),
        )
    except (FullEphemerisRequiredError, swe.Error) as error:
        refusal = _event_search_refusal("行速、停滯與東出西入", error, time.trace)
        return motion_states_unavailable(refusal)


def _derived_chart(facts: AstronomicalFacts) -> DerivedChart:
    time = facts.time
    req = time.request
    antiscia = _antiscia(facts)
    # derived_methods：帶技法假設的判斷結果，每項皆標註具名 method。
    # 日夜盤只有一個產生器：地心太陽中心真高度，與顯示中心無關；
    # Lots 與尊貴元件的 sect 共用這個值。heliocentric／barycentric 為 None。
    sect_sun_altitude = geocentric_sun_true_altitude(
        time.jd_ut, time.context, req.atmosphere
    )
    sect, lots = _sect_and_lots(facts, sect_sun_altitude)
    void_of_course = _void_of_course(facts)
    declination_aspects = _declination_aspects(facts)
    aspects = _aspects(facts, lots)
    essential_dignities = _essential_dignities(facts, sect_sun_altitude)
    planetary_hours = _planetary_hours(facts)
    dodecatemoria = _dodecatemoria(facts, lots)
    lunar_mansions = _lunar_mansions(facts)
    solar_phase = _solar_phase(facts)
    motion_states = _motion_states(facts)
    classical_classifications = _classical_classifications(facts, sect_sun_altitude)

    if time.input_request.birth_time_precision == "date_only":
        for requested, result in (
            (req.options.include_aspects, aspects),
            (req.options.include_declination_aspects, declination_aspects),
            (essential_dignities is not None, essential_dignities),
            (req.options.include_dodecatemoria, dodecatemoria),
            (req.options.include_classical_classifications, classical_classifications),
        ):
            if requested and result:
                result["time_basis"] = (
                    "representative_computational_anchor_not_birth_time"
                )
        # Whether these were revisited across the civil day is the
        # sensitivity ledger's fact (calculation_dossier.birth_time.
        # sensitivity_coverage), not a second flag written onto each result.
        if facts.positions.lunar_apsides is not None:
            facts.positions.lunar_apsides["time_basis"] = (
                "representative_computational_anchor_not_birth_time"
            )

    return DerivedChart(
        antiscia=antiscia,
        aspects=aspects,
        declination_aspects=declination_aspects,
        dodecatemoria=dodecatemoria,
        essential_dignities=essential_dignities,
        lots=lots,
        planetary_hours=planetary_hours,
        sect=sect,
        void_of_course=void_of_course,
        lunar_mansions=lunar_mansions,
        solar_phase=solar_phase,
        motion_states=motion_states,
        classical_classifications=classical_classifications,
    )
