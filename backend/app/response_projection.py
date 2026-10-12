"""Views of the one chart response.

`detailed` is the response `chart_pipeline._assemble_chart_response` builds, unchanged.
`page` is that same response narrowed to a closed list of kept paths.
Nothing here calculates, formats or reorders a value, so every value the page
view keeps is the value `detailed` has at the same path; the chart has one
producer.

`page` is the default.  It keeps the fields
the result page reads: what its body renders and what it needs to check the
response (schema and dossier versions, option states with their response
paths, the trace digest and build identity that bind a later `detailed`
request to this one), plus the few fields PAGE_KEPT_UNREAD_PATHS names for
other readers.  Verification detail -- the step trace, contract text, method
identity and prose, receipts, unread twins -- is requested separately with
`projection=detailed`, recomputed from the same input; nothing is stored
between the two requests.

tests/backend/test_chart_projections.py pins that the page body built
from `page` equals the one built from `detailed` and that the page reads
every field `page` keeps.

Path syntax: `.` separates object keys, `name[]` means every item of the list
at `name`, `*` means every value of an object, and `{a,b}` means each of the
named keys.  A kept path keeps the whole value at its end.
"""

from __future__ import annotations

from typing import Any, get_args

from .schemas import ChartProjection

__all__ = [
    "CHART_PROJECTIONS",
    "ChartProjection",
    "DEFAULT_CHART_PROJECTION",
    "PAGE_KEPT_PATHS",
    "PAGE_KEPT_UNREAD_PATHS",
    "project_chart_response",
]

CHART_PROJECTIONS: tuple[str, ...] = get_args(ChartProjection)
DEFAULT_CHART_PROJECTION: ChartProjection = "page"

# ── page ───────────────────────────────────────────────────────────────────
# What the result page reads from a response, and nothing else.  The page reads
# a response through its view-model (ChartViewModel.buildSections and
# buildViewTree), createDocument's checks, the three text serializers of the
# 「運算結果」 export and the binding of a later `detailed` document
# (ChartExport.bindsToPageDocument).  tests/backend/test_chart_projections.py
# runs all of them over a set of requests behind a read-recording proxy and
# fails on any kept field none of them reads, unless the field is listed in
# PAGE_KEPT_UNREAD_PATHS with its reason; the same test fails when the page body
# built from this view differs from the one built from `detailed`.  Where
# siblings share one shape the entry names them all (`*` or `{a,b}`) so an
# unmeasured profile or event of the same shape is kept too.
#
# A module receipt keeps the four fields ChartViewModel.receiptStatus reads
# (requested, applicable, available, reason_code); method identity, provenance
# and the rest of the receipt are verification detail.
_RECEIPT = "requested,applicable,available,reason_code"
_OPTION_STATE = "requested,executed,applicable,available,reason_code"
_POSITION = (
    "name,sign_position,latitude,right_ascension,declination,azimuth,"
    "altitude_true,altitude_apparent,motion_sign"
)
_INSTANT = "{next,previous}.{utc_time,time_scale}"
_ECLIPSE = (
    "{time_scale,type,utc_time_maximum,classification_borderline.{state,explanation_zh}}"
)
_DIGNITY_OBJECT = (
    "name,sign,degree_in_sign_text,ruler,ruler_reading,decan_number,"
    "segment_start_degrees,segment_end_degrees,day_candidate,night_candidate,"
    "selected_rulers,element,day_rulers,night_rulers,"
    "assigned_rulers,principal_ruler,secondary_ruler,domicile_matched,"
    "domicile_signs,exaltation_matched,exaltation_sign"
)
_SAMPLES = "representative_samples[]"
_SYZYGY_POINT = (
    "local_time,utc_offset,sun_sign_position,moon_sign_position,chart_zodiac.sign_positions,"
    "degree_selection.{state,selected_luminary,selected_sign_position,"
    "horizon_at_syzygy.{sun,moon}.{altitude_true_degrees,above_horizon,in_near_horizon_band},"
    "horizon_at_syzygy.ecliptic_hemisphere_check.agrees_with_altitude}"
)
_ECLIPSE_POINT = "maximum_local_time,maximum_utc_offset,eclipsed_luminary,eclipse_sign_position"
_LOCAL_INSTANT = "local_time,utc_offset,utc_time,time_scale"

# Kept although the page reads no value under them, each for a stated reader.
PAGE_KEPT_UNREAD_PATHS: tuple[str, ...] = (
    # The availability probes (deploy/container_healthcheck.py and the
    # operator's deploy tool) read these from the default response.
    "calculation_dossier.input_receipt.location.place_label",
    "calculation_dossier.provenance.all_core_calculation_sources_used_full_ephemeris",
    # createDocument refuses a response in which an executed option's response
    # path is missing or an empty object.  One small field keeps
    # each such path present where the page reads nothing under it.
    "calculation_dossier.calculation_policy.body_selection.excluded_optional_body_groups",
    "derived_geometry.antiscia.scope.semantics",
    "derived_methods.aspects.perfection.status",
    "derived_methods.declination_aspects.participant_keys",
    # A sample's own event carries no instant only when the sample and the
    # anchor disagree on it near a polar day or night; ChartViewModel then
    # prints that side's search status (horizonSideCell).
    f"astronomical_data.horizon_events.{_SAMPLES}.bodies[].events.*.search.*.status",
    # A warning is its code and params; the zh-TW page prints the backend's
    # message, and a reader writing the sentence in another language from the
    # code reads params from the default response as well.
    "calculation_dossier.warnings[].params",
)

PAGE_KEPT_PATHS: tuple[str, ...] = (
    "schema_version",
    # The reference frame of every longitude below (zodiac, ayanamsa, center,
    # position mode, ecliptic frame, nutation).  Without it a sidereal chart's
    # 「運算結果」 exports read as tropical; every export prints it.
    "computation_mode",
    # Dossier: versions, warnings, the chart instant, the option states the page
    # reads (and createDocument checks), and the trace digest and build identity
    # that bind a `detailed` request to this response.
    "calculation_dossier.{dossier_version,build_identity}",
    "calculation_dossier.trace_receipt.python_json_serialization_sha256",
    "calculation_dossier.warnings[].{code,message}",
    "calculation_dossier.time_conversion.{utc_iso_8601,time_scale_era}",
    "calculation_dossier.birth_time.sensitivity_coverage",
    "calculation_dossier.calculation_policy.modules.*",
    f"calculation_dossier.calculation_policy.option_states.*.{{{_OPTION_STATE},response_paths,"
    "input_presence}",
    "calculation_dossier.methodology.classical_source_disagreements.items[].{response_path,note_zh}",
    # Astronomical layer.
    "astronomical_data.time.{input_local_time,input_semantics,timezone_label,utc_offset_hours,"
    "utc_time,time_scale_era,jd_ut,delta_t_seconds,last_hours,true_obliquity,ayanamsa}",
    "astronomical_data.atmosphere.{temperature_c,pressure_hpa,pressure_mode,refraction}",
    f"astronomical_data.bodies[].{{key,speed_position_derivative_status,{_POSITION}}}",
    f"astronomical_data.nodes[].{{key,{_POSITION}}}",
    f"astronomical_data.lunar_apsides.{{{_RECEIPT}}}",
    f"astronomical_data.lunar_apsides.points[].{{key,{_POSITION}}}",
    f"astronomical_data.parallax_moon.{{{_RECEIPT},longitude_delta_degrees}}",
    "astronomical_data.parallax_moon.{geocentric_reference,topocentric_effective}.sign_position",
    "astronomical_data.fixed_star_policy.catalog_size",
    "astronomical_data.fixed_stars[].{name,catalog_name,magnitude,latitude,declination,sign_position}",
    f"astronomical_data.angles.{{{_RECEIPT},sign_positions}}",
    f"astronomical_data.extra_angles.{{{_RECEIPT}}}",
    "astronomical_data.extra_angles.angles.*.{zh,sign_position}",
    "astronomical_data.lunar_events.contract",
    f"astronomical_data.lunar_events.primary_phases.*.{_INSTANT}",
    "astronomical_data.lunar_events.prenatal_syzygy.{phase,utc_time,time_scale}",
    f"astronomical_data.lunar_events.eclipses.{{previous_lunar,previous_solar}}.{_ECLIPSE}",
    "astronomical_data.lunar_events.representative_sampling.{interval,status}",
    f"astronomical_data.lunar_events.{_SAMPLES}.{{sample_role,reference_local_time,"
    "result_location,same_as_anchor,module_refusals}",
    f"astronomical_data.lunar_events.{_SAMPLES}.primary_phases.*.{_INSTANT}",
    f"astronomical_data.lunar_events.{_SAMPLES}.prenatal_syzygy.{{utc_time,time_scale,phase}}",
    f"astronomical_data.lunar_events.{_SAMPLES}.eclipses.{{previous_lunar,previous_solar}}."
    "{time_scale,type,utc_time_maximum}",
    # The prenatal syzygy's degree and the eclipses around the birth
    # (ChartViewModel prenatalPointsSection).
    f"astronomical_data.lunar_events.prenatal_syzygy.{{{_SYZYGY_POINT}}}",
    "astronomical_data.lunar_events.prenatal_syzygy_at_birth.{reference,hours_before_birth,"
    "near_birth,luminaries_above_horizon_at_birth.{state,sun.above_horizon,moon.above_horizon},"
    "sect_profile.{state,selected_phase,selected,other_previous_syzygy.{state,phase,"
    "hours_before_birth}}}",
    "astronomical_data.lunar_events.prenatal_syzygy_at_birth.sect_profile.other_previous_syzygy."
    f"event.{{{_SYZYGY_POINT}}}",
    "astronomical_data.lunar_events.eclipses.{previous_lunar,previous_solar,previous_umbral_lunar}."
    f"{{{_ECLIPSE_POINT}}}",
    "astronomical_data.lunar_events.eclipses.previous_umbral_lunar.{type,relation_to_previous_lunar}",
    "astronomical_data.lunar_events.eclipses_at_birth.{reference,days_before_birth.*,"
    "in_progress.*.{relation,maximum_minus_birth_minutes}}",
    f"astronomical_data.lunar_events.eclipses_at_birth.in_progress.*.eclipse.{{type,{_ECLIPSE_POINT}}}",
    "astronomical_data.horizon_events.contract.{disc_position,refraction,"
    "upper_transit_is_hour_angle_zero_not_max_altitude,search_horizon_days.{rise,upper_transit}}",
    "astronomical_data.horizon_events.bodies[].{key,name,visibility,"
    f"events.*.{{status,search.*.status,{_INSTANT}}}}}",
    "astronomical_data.horizon_events.representative_sampling.{interval,status}",
    f"astronomical_data.horizon_events.{_SAMPLES}.{{sample_role,reference_local_time,"
    "result_location,module_refusals}",
    f"astronomical_data.horizon_events.{_SAMPLES}.bodies[].{{key,events_same_as_anchor,"
    f"events.*.{_INSTANT}}}",
    # Derived geometry.
    f"derived_geometry.antiscia.{{{_RECEIPT}}}",
    "derived_geometry.antiscia.antiscia[].{key,name,sign_position}",
    "derived_geometry.antiscia.contra_antiscia[].{key,sign_position}",
    # Birth-time sensitivity: what ChartViewModel.sensitivitySection and its
    # sampling summary read for each precision and state.
    "birth_time_sensitivity.{precision,status,reason_code,classification_status,"
    "interval_start_local,interval_end_exclusive_local,representative_local_time,"
    "representative_semantics,sampling_semantics}",
    "birth_time_sensitivity.probe_coverage.skipped[].{offset_seconds,reason_code}",
    "birth_time_sensitivity.probe_coverage.refinement_offsets_seconds",
    "birth_time_sensitivity.evaluation_limits[].{reason_code,affected_paths}",
    "birth_time_sensitivity.sample_schedule.{utc_offset_changes,absent_hourly_labels}",
    "birth_time_sensitivity.position_ranges[].{key,name,status,representative_sign_position,"
    "sampled_sign_indices}",
    "birth_time_sensitivity.body_signs[].{key,name,status,representative_sign_index,"
    "sampled_sign_indices}",
    "birth_time_sensitivity.dodecatemoria_signs[].{key,sampled_sign_indices}",
    "birth_time_sensitivity.planet_in_house[].{name,status,representative_house,"
    "sampled_houses}",
    "birth_time_sensitivity.angles.*.status",
    "birth_time_sensitivity.angles.asc.sampled_sign_indices",
    "birth_time_sensitivity.house_cusps[].{house,status}",
    "birth_time_sensitivity.{sect,void_of_course}.status",
    "birth_time_sensitivity.lots.{discontinuity,fortune.status,spirit.status,"
    "fortune.house_status,spirit.house_status}",
    "birth_time_sensitivity.classification_coverage.*.differing_classifications",
    "birth_time_sensitivity.probes[].{input_local_time,fold}",
    "birth_time_sensitivity.samples[].{local_time,fold}",
    "birth_time_sensitivity.transitions[].{lower_bound_local,upper_bound_local,changed_paths,"
    "resolution_seconds}",
    "birth_time_sensitivity.moon_boundary_assessment.sampled_sign_boundary_transitions[]."
    "{lower_sample_local,upper_sample_local,semantics}",
    # Methods.
    f"derived_methods.house_division.{{{_RECEIPT},execution_status,system_code,system_name,cusps,"
    "cusp_sign_positions,availability.state}",
    f"derived_methods.planet_in_house.{{{_RECEIPT},execution_status,house_system_code,house_system_name}}",
    "derived_methods.planet_in_house.placements[].{key,name,house,on_cusp,"
    "distance_to_nearest_cusp_degrees}",
    "derived_methods.planet_in_house.point_placements.{execution_status,reason_code}",
    "derived_methods.planet_in_house.point_placements.placements[].{key,name,house}",
    f"derived_methods.sect.{{{_RECEIPT},sect_status,is_day,sun_altitude_used,"
    "in_near_horizon_band,near_horizon_band_half_width_degrees,named_boundary_disagreement}",
    f"derived_methods.lots.{{{_RECEIPT},formula_basis,fortune,sign_positions,"
    "house_placement.{fortune,spirit},sect_applied,sect_named_boundary_disagreement}",
    "derived_methods.lots.by_sect.*.{fortune_house,spirit_house,sign_positions}",
    f"derived_methods.void_of_course.{{{_RECEIPT},is_void_of_course,verdict,"
    "solver,time_to_sign_exit_hours}",
    "derived_methods.void_of_course.all_candidates[].{body,aspect_angle,time_days}",
    f"derived_methods.declination_aspects.{{{_RECEIPT},aspects,orb_receipt.effective_orb_degrees}}",
    f"derived_methods.aspects.{{{_RECEIPT},pair_listing.unlisted_pairs_without_aspect}}",
    "derived_methods.aspects.degree_based.{aspect_names_zh,orb_verdict_available,"
    "orb_profile_detail.display_name}",
    "derived_methods.aspects.degree_based.angle_participation.executed",
    f"derived_methods.aspects.degree_based.orb_receipt.{{{_RECEIPT},fixed_pair_threshold_degrees}}",
    # The aspect grid places each pair by its participants' keys and order.
    "derived_methods.aspects.participants[].{key,name}",
    "derived_methods.aspects.pairs[].{body_a,body_b,body_a_name,body_b_name,separation_degrees,"
    "applying_reason_code,aspects_in_orb}",
    "derived_methods.aspects.pairs[].whole_sign.{applicable,in_aspect,configuration_zh}",
    "derived_methods.aspects.whole_sign_aversions[].{body_a,body_b,signed_sign_distance,configuration_zh}",
    "derived_methods.aspects.pairs[].nearest_aspect.{key,signed_offset_from_exact_degrees}",
    "derived_methods.aspects.pairs[].aspect_targets[].{key,in_orb,in_orb_reason_code,applying,"
    "offset_from_exact_degrees,"
    "partile,partile_reason_code,perfection_status,"
    "perfection.{hours_from_chart_moment,search_window_days}}",
    f"derived_methods.planetary_hours.{{{_RECEIPT},time_basis}}",
    "derived_methods.planetary_hours.chart_instant.planetary_day.{ruler_name,weekday,"
    "sunrise_local_date,day_hour_minutes,night_hour_minutes}",
    f"derived_methods.planetary_hours.chart_instant.planetary_day.{{sunrise,sunset,next_sunrise}}."
    f"{{{_LOCAL_INSTANT}}}",
    "derived_methods.planetary_hours.chart_instant.planetary_hour.{index,period,index_in_period,"
    "ruler_name}",
    f"derived_methods.planetary_hours.chart_instant.planetary_hour.{{start,end}}.{{{_LOCAL_INSTANT}}}",
    "derived_methods.planetary_hours.birth_time_interval.{interval,crosses_hour_boundary,"
    "crosses_planetary_day_boundary}",
    "derived_methods.planetary_hours.birth_time_interval.candidates[].{planetary_day_ruler_name,"
    "index,period,index_in_period,ruler_name,start.{local_time,utc_offset},end.{local_time,utc_offset}}",
    f"derived_methods.lunar_mansions.{{{_RECEIPT}}}",
    "derived_methods.lunar_mansions.division.width_text",
    "derived_methods.lunar_mansions.placements[].{key,name,degrees_into_mansion_text,"
    "distance_to_nearest_boundary_degrees,near_boundary}",
    "derived_methods.lunar_mansions.placements[].mansion.{number,transliteration,"
    "boundary_sign_positions}",
    "derived_methods.lunar_mansions.birth_time_interval.{interval,crosses_mansion_boundary}",
    "derived_methods.lunar_mansions.birth_time_interval.mansions[].{number,transliteration}",
    f"derived_methods.solar_phase.{{{_RECEIPT},profile,decision_basis,moon_center,time_basis}}",
    "derived_methods.solar_phase.disc_cazimi.{requested,applicable,reason_code}",
    "derived_methods.solar_phase.sun.semidiameter_degrees",
    "derived_methods.solar_phase.rows[].{key,name,longitude_difference_degrees,"
    "longitude_difference_text,angular_separation_degrees,ecliptic_latitude_degrees,side,"
    "relative_motion,band,within_solar_disc,same_sign_as_sun}",
    "derived_methods.solar_phase.rows[].daily_longitude_differences[].{day_offset,"
    "longitude_difference_degrees}",
    "derived_methods.solar_phase.profile_results.*.{limits,venus_latitude_exception_degrees,"
    "disc_cazimi_applied,bands,bands_seen_in_birth_time_interval}",
    "derived_methods.solar_phase.profile_results.*.beam_crossings_within_7_days.*[].{direction,"
    "threshold_degrees,day_offset,instant.{local_time,utc_offset}}",
    "derived_methods.solar_phase.seven_day_search.window_days",
    "derived_methods.solar_phase.birth_time_interval.interval",
    "derived_methods.solar_phase.birth_time_interval.rows[].{key,name,stable,"
    "longitude_difference_min_degrees,longitude_difference_max_degrees}",
    f"derived_methods.essential_dignities.{{{_RECEIPT},selected_profiles,"
    "research_comparison_profiles,sect.{selected_ruler_available,sect_dependent_components,"
    "in_near_horizon_band,near_horizon_band_half_width_degrees,is_day}}",
    "derived_methods.essential_dignities.profile_results.*.{profile_id,technique,ruler_type,source}",
    f"derived_methods.essential_dignities.profile_results.*.objects[].{{{_DIGNITY_OBJECT}}}",
    f"derived_methods.dodecatemoria.{{{_RECEIPT},profile,scope.not_listed}}",
    "derived_methods.dodecatemoria.points[].{key,name,category,point_sign_position,"
    "sign_position,domicile_lord,sign_differs_under_other_sect,comparison_sign}",
    f"derived_methods.classical_classifications.{{{_RECEIPT},not_evaluated}}",
    "derived_methods.classical_classifications.chart_sect.{is_day,in_near_horizon_band}",
    "derived_methods.classical_classifications.planets[].{name,nature,gender,sect_membership,"
    "of_chart_sect,sign,sign_gender,above_horizon,altitude_in_near_horizon_band,house,joys,hayz}",
    "derived_methods.classical_classifications.places",
    *PAGE_KEPT_UNREAD_PATHS,
)


def _expand(expression: str) -> list[tuple[str, ...]]:
    """Expand one kept-path expression into plain step tuples.

    `{a,b.c}` alternatives may hold dotted paths and nested groups; what
    follows a group applies to every alternative.
    """

    position = 0

    def sequence() -> list[tuple[str, ...]]:
        nonlocal position
        paths: list[tuple[str, ...]] = [()]
        while True:
            alternatives = segment()
            paths = [head + tail for head in paths for tail in alternatives]
            if position < len(expression) and expression[position] == ".":
                position += 1
                continue
            return paths

    def segment() -> list[tuple[str, ...]]:
        nonlocal position
        if expression.startswith("{", position):
            position += 1
            alternatives: list[tuple[str, ...]] = []
            while True:
                alternatives.extend(sequence())
                if expression.startswith(",", position):
                    position += 1
                    continue
                if not expression.startswith("}", position):
                    raise ValueError(f"unbalanced group in kept path: {expression}")
                position += 1
                break
        else:
            start = position
            while position < len(expression) and (
                expression[position].isalnum() or expression[position] in "_*"
            ):
                position += 1
            name = expression[start:position]
            if not name or ("*" in name and name != "*"):
                raise ValueError(f"bad segment in kept path: {expression}")
            alternatives = [(name,)]
        while expression.startswith("[]", position):
            position += 2
            alternatives = [steps + ("[]",) for steps in alternatives]
        return alternatives

    paths = sequence()
    if position != len(expression):
        raise ValueError(f"trailing text in kept path: {expression}")
    return paths


_WHOLE = "\0whole"


def _kept_tree(expressions: tuple[str, ...]) -> dict:
    tree: dict = {}
    for expression in expressions:
        for steps in _expand(expression):
            node = tree
            for step in steps:
                if node.get(_WHOLE):
                    break
                node = node.setdefault(step, {})
            else:
                node.clear()
                node[_WHOLE] = True

    def merge(into: dict, other: dict) -> None:
        if into.get(_WHOLE):
            return
        if other.get(_WHOLE):
            into.clear()
            into[_WHOLE] = True
            return
        for key, child in other.items():
            merge(into.setdefault(key, {}), child)

    def settle(node: dict) -> None:
        # An explicit key under a `*` also keeps what the `*` keeps.
        star = node.get("*")
        for key, child in node.items():
            if key == _WHOLE:
                continue
            if star is not None and key not in {"*", "[]"}:
                merge(child, star)
            settle(child)

    settle(tree)
    return tree


_PAGE_TREE = _kept_tree(PAGE_KEPT_PATHS)


def _keep(node: Any, tree: dict) -> Any:
    """Return `node` with only the kept paths, copying only containers it narrows.

    A value whose shape the tree does not describe (a `null` module slot, a
    scalar where an object would be) is returned unchanged.
    """

    if tree.get(_WHOLE):
        return node
    if isinstance(node, list):
        item_tree = tree.get("[]")
        return node if item_tree is None else [_keep(item, item_tree) for item in node]
    if not isinstance(node, dict):
        return node
    star = tree.get("*")
    kept = {}
    for key, value in node.items():
        child = tree.get(key, star)
        if child is not None:
            kept[key] = _keep(value, child)
    return kept


def project_chart_response(response: dict[str, Any], projection: str) -> dict[str, Any]:
    """Derive the requested view from the one detailed chart response."""

    if projection == "detailed":
        return response
    if projection == "page":
        page = _keep(response, _PAGE_TREE)
        page_descriptor = {
            "name": "page",
            "derived_from": "detailed",
            # The rule, not the list: the kept paths are PAGE_KEPT_PATHS, printed
            # in the output contract's「Projections」.
            "kept": "fields_the_result_page_body_reads",
            "verification_detail": "projection=detailed",
        }
        return {
            "schema_version": page["schema_version"],
            "projection": page_descriptor,
            **{key: value for key, value in page.items() if key != "schema_version"},
        }
    raise ValueError(f"unsupported chart projection: {projection}")
