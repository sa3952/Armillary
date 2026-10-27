"""Stage 1 of the chart pipeline: the effective request, the time conversion
and the representative-sample event receipts."""

import datetime as dtmod

from .core.invariants import InternalInvariantError
from .ephemeris import (
    FullEphemerisRequiredError,
    ensure_ephemeris_initialized_for_thread,
    has_full_ephemeris_files,
    init_ephemeris,
    reset_swiss_state_for_thread,
    watch_chart_input_files,
)
from .schema_chart import ChartRequest
from .core.trace import Trace
from .core.computation_mode import ComputationContext
from .core.frame_compatibility import method_frame_states
from .core.time_utils import (
    civil_day_receipt,
    compute_time_conversion,
    representative_policy,
    resolve_civil_day,
    resolve_date_only_anchor,
)
from .core.birth_time_sensitivity import (
    approximate_hour_representative_request,
    representative_semantics_for_offset,
)
from .core.prenatal_points import PrenatalPlace
from .core.dossier import EVENT_SEARCH_REASON_CODES
from .core.module_state import (
    EventModuleState,
    MODULE_NOT_APPLICABLE,
    SEARCH_EPHEMERIS_REFUSALS,
    computed_receipt,
    module_state,
    module_status_word,
    not_requested_state,
)
from .chart_stages import JsonObject, TimeResolution


# The Swiss path is bound once on import, before the bundled file set is
# read; that availability is immutable for the process lifetime.
init_ephemeris()
_HAS_FULL_EPHEMERIS = has_full_ephemeris_files()

# Event-search containment: an optional search that leaves Swiss coverage or
# trips a Swiss error becomes that module's own not_applicable with one of
# EVENT_SEARCH_REASON_CODES; the core chart survives, and the Swiss state is
# reset so the next search in this worker does not inherit a segment left open.
EVENT_SEARCH_SOURCE = "Swiss Ephemeris"


def _prenatal_place(input_request: ChartRequest, context: ComputationContext) -> PrenatalPlace:
    return PrenatalPlace(
        context=context,
        atmosphere=input_request.atmosphere,
        timezone=input_request.timezone,
        precision=input_request.birth_time_precision,
    )


def _event_availability_entry(requested: bool) -> EventModuleState:
    """Six-field state of an event search, written where the search runs.

    A refusal from the search replaces it with ``_event_search_refusal``.
    """

    state = (
        computed_receipt(EVENT_SEARCH_SOURCE)
        if requested
        else not_requested_state()
    )
    # The closed status word consumers read, projected once from the six fields.
    return EventModuleState(**state, status=module_status_word(state))


def _event_search_refusal(module_label: str, error: Exception, trace: Trace) -> EventModuleState:
    if isinstance(error, FullEphemerisRequiredError):
        if error.reason not in SEARCH_EPHEMERIS_REFUSALS:
            raise error
        reason_code, applicable = SEARCH_EPHEMERIS_REFUSALS[error.reason]
        note = (
            "請求日期的核心命盤可計算，但此搜尋會離開完整 "
            "Swiss Ephemeris files 覆蓋範圍；此模組標為不可用。"
            if not applicable
            else "伺服器缺少此搜尋所需的 Swiss Ephemeris 檔；此模組標為不可用。"
        )
    else:
        reason_code, applicable = EVENT_SEARCH_REASON_CODES[2], True
        note = (
            "Swiss Ephemeris 在此搜尋中回報錯誤；此模組標為不可用，"
            "核心命盤不受影響。錯誤內容不對外輸出。"
        )
    reset_swiss_state_for_thread()
    trace.add(module_label, result={"reason_code": reason_code}, note=note)
    # The search was attempted (executed) and produced nothing.  Only leaving
    # the coverage makes it inapplicable to the request; a server fault does not.
    return EventModuleState(
        **module_state(
            requested=True, executed=True, applicable=applicable, available=False,
            reason_code=reason_code,
        ),
        status=MODULE_NOT_APPLICABLE,
    )


def _effective_request(
    input_request: ChartRequest,
) -> tuple[ChartRequest, int, JsonObject | None, dtmod.datetime | None]:
    """The request the chart is computed for, its anchor offset, date anchor
    and, for a non-exact birth time, the anchor's UTC instant."""

    req = input_request
    representative_offset_seconds = 1800
    date_only_anchor = None
    anchor_utc = None
    if input_request.birth_time_precision == "approximate_hour":
        req, representative_offset_seconds, anchor_utc = (
            approximate_hour_representative_request(input_request)
        )
    elif input_request.birth_time_precision == "date_only":
        # 當地正午只是重現性良好的 representative anchor；input receipt 仍保留
        # 00:00:00 日期容器，且 Dossier 明示這不是出生時刻。正午落在時鐘跳躍的
        # 空隙時，錨點改取其後第一個真實存在的瞬間並寫進收據。
        date_only_anchor = resolve_date_only_anchor(
            input_request.datetime, input_request.timezone
        )
        anchor_utc = dtmod.datetime.fromisoformat(
            date_only_anchor["anchor_utc_time"].replace("Z", "+00:00")
        )
        anchor_hour, anchor_minute, anchor_second = (
            int(part) for part in date_only_anchor["anchor_local_time"][11:19].split(":")
        )
        req = input_request.model_copy(
            update={
                "datetime": input_request.datetime.model_copy(
                    update={
                        "hour": anchor_hour,
                        "minute": anchor_minute,
                        "second": float(anchor_second),
                    }
                ),
                "timezone": input_request.timezone.model_copy(
                    update={"fold": date_only_anchor["anchor_fold"]}
                ),
                # Houses need a birth time.  Only the effective request drops
                # them; the input request keeps them and the house module refuses.
                "options": input_request.options.model_copy(
                    update={"include_houses": False}
                ),
            }
        )
    return req, representative_offset_seconds, date_only_anchor, anchor_utc


def _resolve_time(
    input_request: ChartRequest, *, instant_jd_ut: float | None = None,
) -> TimeResolution:
    if instant_jd_ut is not None and input_request.birth_time_precision != "exact":
        raise InternalInvariantError("an instant given as JD(UT) is an exact instant")
    req, representative_offset_seconds, date_only_anchor, anchor_utc = (
        _effective_request(input_request)
    )
    # Segment presence is re-checked once per chart, not after every Swiss
    # call, and before the path is bound: Swiss opens the segments there, so a
    # manifest read afterwards could describe files Swiss never saw.
    ephemeris_input_watch = watch_chart_input_files()
    # Bind the verified ephemeris path while holding the Swiss-state lock.  The
    # chart's `finally` releases it (release_ephemeris_for_thread), so every
    # chart binds here once; repeat calls within the same chart are no-ops.
    ensure_ephemeris_initialized_for_thread()
    trace = Trace()
    # The trace receipt hashes the trace and nothing else.  An option whose
    # effect never reached a step (a partile threshold, the perfection search,
    # the opt-in extra angles) changed the response under an unchanged digest,
    # so the options as sent are a step of their own.
    trace.add(
        "請求選項",
        inputs=input_request.options.model_dump(mode="json"),
        note="這次請求送出的全部選項；它們在計算軌跡裡，所以計算軌跡的 SHA-256 也涵蓋選項。",
    )

    if not _HAS_FULL_EPHEMERIS:
        trace.add(
            "⚠ 星曆檔檢查",
            note=(
                "backend/ephe 缺少完整星曆檔（本服務隨映像內附，正常部署不會出現）；"
                "計算將退回 Moshier 半分析模型（精度較低），此結果不應當作完整星曆結果使用。"
            ),
        )

    time_conv = compute_time_conversion(
        req.datetime,
        req.timezone,
        req.location,
        trace,
        # A repeated wall-clock time is the user's to resolve, for an
        # exact time as for an hour.  date_only's anchor carries the fold its
        # own resolution chose, so the effective request never lacks one.
        require_explicit_fold=(
            input_request.birth_time_precision != "date_only"
        ),
        input_semantics=(
            "representative_computational_anchor_not_birth_time"
            if input_request.birth_time_precision == "date_only"
            else representative_semantics_for_offset(representative_offset_seconds)
            if input_request.birth_time_precision == "approximate_hour"
            else "exact_birth_time"
        ),
        instant_jd_ut=instant_jd_ut,
    )
    jd_ut = time_conv["jd_ut"]

    ctx = ComputationContext(req.computation_mode, req.location)
    ctx.describe(trace, jd_ut)
    # Every frame-dependent consumer reads this one table.
    frame_states = method_frame_states(req.computation_mode)
    time_conv["ayanamsa"] = ctx.ayanamsa_value(jd_ut)
    civil_day = None
    if date_only_anchor is not None:
        time_conv["date_only_anchor"] = date_only_anchor
        civil_day = resolve_civil_day(input_request.datetime, input_request.timezone)
        time_conv["civil_day"] = civil_day_receipt(civil_day)

    return TimeResolution(
        input_request=input_request,
        request=req,
        representative_offset_seconds=representative_offset_seconds,
        time_conversion=time_conv,
        anchor_utc=anchor_utc,
        representative_policy=representative_policy(
            time_conv["input_semantics"], date_only_anchor
        ),
        civil_day=civil_day,
        jd_ut=jd_ut,
        context=ctx,
        frame_states=frame_states,
        trace=trace,
        ephemeris_input_watch=ephemeris_input_watch,
    )
