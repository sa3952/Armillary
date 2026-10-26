"""swisseph 星曆檔路徑初始化、覆蓋範圍 manifest 與精度檢查。

覆蓋範圍不從 retflag 推定。兩個本地已證的 Swiss 行為說明為什麼：

1. 缺 ``semo_18.se1`` 時，Swiss 以 Moshier 月球代替，但 retflag 仍回報
   ``FLG_SWIEPH``。
2. 已開啟 ``seas_18.se1`` 的 warm worker，對超出該段尾端的時刻會外插並回報
   ``FLG_SWIEPH``；同一請求在 fresh worker 則丟出 ``swe.Error``。

因此「檔案在不在」看 manifest，「時刻在不在覆蓋內」看 UTC 儒略日對照每段的
實測邊界；兩者都在呼叫 Swiss 之前判定。
"""

import hashlib
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import swisseph as swe

EPHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ephe")
# The digests the image's entrypoint verifies (verify_ephemeris_integrity) are
# the dataset the full-ephemeris claim is about.  Fixed to the tree this module
# ships in (repository and image share the layout), not to EPHE_DIR.
PINNED_DIGEST_MANIFEST = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "deploy",
    "ephemeris.sha256",
)
AMBIENT_EPHEMERIS_PATHS = ("SE_EPHE_PATH", "SE_EP_PATH")

# JD(UT) coverage of each bundled segment, measured in a fresh process against
# Swiss Ephemeris 2.10.03 with swe.close() between probes (a warm process
# extrapolates past these and must not be used to measure them).  Each bound is
# rounded *inward* by about a minute so that any instant the manifest calls
# covered is one Swiss serves from the file.  The Moon and major-planet files
# both end at 2400-01-10 20:28 UT; the asteroid file ends at 2399-12-31 23:51 UT
# (2400-01-01 00:00 TT), which is why a legal local 2399-12-31 birth at a
# negative UTC offset leaves Chiron coverage while the core chart stays inside.
SEGMENT_MANIFEST: Final[dict[str, dict]] = {
    "sepl_18.se1": {
        "role": "major_planet_segment_1800_2399",
        "jd_ut_coverage": (2378496.51, 2597651.35),
    },
    "semo_18.se1": {
        "role": "moon_segment_1800_2399",
        "jd_ut_coverage": (2378496.51, 2597651.35),
    },
    "seas_18.se1": {
        "role": "minor_planet_segment_for_optional_chiron",
        "jd_ut_coverage": (2378496.56, 2597641.49),
    },
}
# The other bundled files Swiss reads by name; inventoried with the segments so
# one manifest (and one digest of each file) serves the checks and the dossier.
FIXED_STAR_CATALOGUE: Final = "sefstars.txt"
AUXILIARY_INPUT_FILES: Final[dict[str, str]] = {
    FIXED_STAR_CATALOGUE: "fixed_star_catalog",
    "seorbel.txt": "auxiliary_orbital_elements",
}
CORE_SEGMENTS: Final = ("sepl_18.se1", "semo_18.se1")
CHIRON_SEGMENT: Final = "seas_18.se1"

# Closed set.  "covered" is the only state under which a Swiss file-backed call
# may be issued for that segment.
COVERAGE_STATES: Final = ("covered", "outside_segment", "segment_file_missing")
COVERAGE_REASON_CODES: Final = {
    "outside_segment": "ephemeris_segment_out_of_coverage",
    "segment_file_missing": "ephemeris_segment_file_missing",
}


# The one reason that is the request's own: its instant lies outside every
# bundled segment.  The others (file missing, retflag fallback) are the server's.
FULL_EPHEMERIS_OUT_OF_COVERAGE: Final = "segment_out_of_coverage"


class FullEphemerisRequiredError(Exception):
    """A calculation requested Swiss files but Swiss silently fell back to Moshier."""

    code = "full_ephemeris_required"

    def __init__(
        self,
        *,
        operation: str,
        jd_ut: float,
        retflag: int,
        reason: str = "retflag_not_swieph",
    ):
        self.operation = operation
        self.jd_ut = jd_ut
        self.retflag = retflag
        self.reason = reason
        super().__init__(
            f"{operation} 超出目前完整 Swiss Ephemeris 資料檔可計算的範圍；"
            "已拒絕改用 Moshier 近似模型。"
        )


def _refuse_ambient_ephemeris_path() -> None:
    inherited = [name for name in AMBIENT_EPHEMERIS_PATHS if name in os.environ]
    if inherited:
        raise RuntimeError(
            "ambient Swiss ephemeris path would override the bundled dataset: "
            + ", ".join(inherited)
        )


def init_ephemeris():
    """Bind the bundled path, refusing an ambient one that would override it."""

    _refuse_ambient_ephemeris_path()
    swe.set_ephe_path(EPHE_DIR)


# The Linux pyswisseph source build initialises its ephemeris path per worker
# thread, so a path set on the import thread does not reach FastAPI's sync
# endpoint threads, whose first calculation silently falls back to Moshier.
# Hence a per-thread flag.
_THREAD_STATE = threading.local()


def ensure_ephemeris_initialized_for_thread() -> bool:
    """Bind the ephemeris path unless this thread has bound it since its last
    ``release_ephemeris_for_thread``.  True if this call did the work.

    The chart worker releases after every chart, so in production this binds once
    per chart, not once per thread lifetime.
    """

    if getattr(_THREAD_STATE, "initialized", False):
        return False
    init_ephemeris()
    _THREAD_STATE.initialized = True
    return True


def release_ephemeris_for_thread() -> bool:
    """Close Swiss files and clear this thread's initialization flag."""

    _THREAD_STATE.chart_configuration = {}
    if not getattr(_THREAD_STATE, "initialized", False):
        return False
    swe.close()
    _THREAD_STATE.initialized = False
    return True


def swiss_state_scope(library=swe) -> str:
    """``thread`` when Swiss keeps its state per thread, ``process`` when threads share it.

    A compile-time property of the library (its TLS switch), not of this code:
    the shipped Linux image's build is per thread, a macOS build is shared.  The
    compute line serializes either way; the image gate reads this to confirm the
    build it ships.  Observed in two fresh threads, so no request's state is touched:
    the first sets an observer and reads the Moon, the second sets another
    observer, and the first reads again.  Moshier needs no file.
    """

    readings: list[float] = []

    def moon() -> float:
        return library.calc_ut(2451545.0, library.MOON, library.FLG_MOSEPH | library.FLG_TOPOCTR)[0][0]

    def other_observer() -> None:
        library.set_topo(-74.0, 40.7, 0.0)

    def first() -> None:
        library.set_topo(121.5, 25.0, 0.0)
        readings.append(moon())
        intruder = threading.Thread(target=other_observer)
        intruder.start()
        intruder.join()
        readings.append(moon())

    probe = threading.Thread(target=first)
    probe.start()
    probe.join()
    if len(readings) != 2:
        raise RuntimeError("the Swiss state probe did not finish")
    return "thread" if readings[0] == readings[1] else "process"


def configure_chart_swiss_state(
    *, geopos: tuple[float, float, float], sid_mode: int | None
) -> None:
    """Set the observer and, for a sidereal chart, the ayanamsa; remember both.

    ``swe.close()`` resets this state as well as the files: the sidereal mode
    returns to Fagan/Bradley and the observer is forgotten.  A reset in the
    middle of a chart therefore has to put it back, or every later Swiss call
    in that chart reads the default ayanamsa or fails for want of an observer.
    This is the one place that state is set, so the reset re-applies exactly it.
    """

    swe.set_topo(*geopos)
    configuration = getattr(_THREAD_STATE, "chart_configuration", None)
    if configuration is None:
        configuration = _THREAD_STATE.chart_configuration = {}
    configuration["geopos"] = tuple(geopos)
    if sid_mode is not None:
        swe.set_sid_mode(sid_mode, 0, 0)
        configuration["sid_mode"] = sid_mode


# Swiss functions that move the global observer as a side effect: each reaches
# ``swe_set_topo`` inside swecl.c (2.10.03: eclipse_how l.992 via
# sol_eclipse_where／sol_eclipse_when_glob／lun_occult_*; swe_sol_eclipse_how
# l.948; eclipse_when_loc l.2117／2164; occult_when_loc l.2442;
# swe_lun_eclipse_how l.3220; rise_set_fast l.4233／4297 and
# swe_rise_trans_true_hor l.4434 via rise_trans; gauquelin_sector calls
# rise_trans; swehel.c sets the observer for the heliacal functions).  The
# eclipse search sets it to the eclipse's ground point, so every topocentric
# position later in the chart was computed for that point instead of the
# birthplace.  A call to any of these must sit inside ``chart_observer_restored()``;
# tests/backend/test_ephemeris_coverage.py enforces that and measures the calls.
OBSERVER_MUTATING_SWISS_CALLS: Final = frozenset({
    "sol_eclipse_where", "sol_eclipse_how", "sol_eclipse_when_glob",
    "sol_eclipse_when_loc", "lun_occult_where", "lun_occult_when_glob",
    "lun_occult_when_loc", "lun_eclipse_how", "lun_eclipse_when_loc",
    "rise_trans", "rise_trans_true_hor", "gauquelin_sector",
    "heliacal_ut", "heliacal_pheno_ut", "vis_limit_mag",
})


def restore_chart_observer() -> None:
    """Put back the observer ``configure_chart_swiss_state`` recorded, if any.

    ``swe_set_topo`` returns at once when the observer is unchanged, so this is
    free after a call that left the birthplace in place.
    """

    configuration = getattr(_THREAD_STATE, "chart_configuration", None) or {}
    if "geopos" in configuration:
        swe.set_topo(*configuration["geopos"])


@contextmanager
def chart_observer_restored() -> Iterator[None]:
    """Run Swiss calls that move the observer, then re-apply the chart's observer.

    One guard for every call in ``OBSERVER_MUTATING_SWISS_CALLS``, also on the
    error path, so no later topocentric position in the chart can read a point
    some search left behind.  Only the observer is re-applied: none of these
    calls changes the sidereal mode (only ``swe.close`` does, handled by
    ``reset_swiss_state_for_thread``).
    """

    try:
        yield
    finally:
        restore_chart_observer()


def reset_swiss_state_for_thread() -> None:
    """Close and reopen Swiss so a caught coverage error leaves no warm state.

    After an out-of-coverage search Swiss may hold a segment open at its edge
    or have switched a body to Moshier; a later search in the same request or
    the same worker would inherit that.  Closing and re-binding the path is the
    only reset the library offers, and it is cheap.  Closing also clears the
    chart's observer and sidereal mode, so those are re-applied from
    ``configure_chart_swiss_state``.
    """

    swe.close()
    init_ephemeris()
    _THREAD_STATE.initialized = True
    configuration = getattr(_THREAD_STATE, "chart_configuration", None) or {}
    if "geopos" in configuration:
        swe.set_topo(*configuration["geopos"])
    if "sid_mode" in configuration:
        swe.set_sid_mode(configuration["sid_mode"], 0, 0)


def _sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _input_files() -> tuple[str, ...]:
    return (*SEGMENT_MANIFEST, *AUXILIARY_INPUT_FILES)


def pinned_input_digests() -> dict[str, str]:
    """File name -> pinned sha256, read from the deploy manifest; {} if unreadable."""

    try:
        with open(PINNED_DIGEST_MANIFEST, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return {}
    pinned = {}
    for line in lines:
        parts = line.split()
        if len(parts) == 2:
            pinned[os.path.basename(parts[1])] = parts[0]
    return pinned


def _build_manifest() -> dict[str, dict]:
    pinned = pinned_input_digests()
    manifest = {}
    for filename in _input_files():
        path = os.path.join(EPHE_DIR, filename)
        present = os.path.isfile(path)
        digest = _sha256(path) if present else None
        manifest[filename] = {
            "present": present,
            "size_bytes": os.path.getsize(path) if present else None,
            "sha256": digest,
            # False for a file that is not the pinned dataset, and for any file
            # when the pinned manifest cannot be read.
            "matches_pinned_sha256": present and digest == pinned.get(filename),
        }
    return manifest


# The digests are cached, keyed by the directory plus each file's stat identity
# (device, inode, size, mtime, ctime), so the cache cannot outlive the files: a
# removed, replaced or re-pointed file changes the inode; a rewrite in place
# changes the ctime even if size and mtime are put back (ctime cannot be set
# from user space).  A key that changes during hashing is not cached.  Nor is
# one whose file was written within a timestamp tick of hashing ("racily clean",
# as git treats its index): a second write in that tick can leave the identity
# unchanged.  Such a manifest serves its chart and is rebuilt at the next refresh.
_TIMESTAMP_TICK_NS: Final = 2_000_000_000  # the coarsest common tick (FAT's 2 s)
_MANIFEST_RACY = False
# The re-stat is not on the hot path: `require_full_ephemeris` runs after every
# Swiss call (thousands per chart) and three stats each tripled a void-of-course
# search.  The signature is checked once per chart start and on explicit file
# checks; in between the hot path reads the manifest as of the chart's start.
_MANIFEST_CACHE: tuple[tuple | None, dict[str, dict]] | None = None


def _stat_identity(stat: os.stat_result) -> tuple:
    return (
        stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
    )


def input_files_signature() -> tuple:
    """The directory and each input file's stat identity, as of now.

    Both the path itself (lstat) and what it resolves to (stat), so a symbolic
    link re-pointed and put back still changes the signature.
    """

    signature: list = [EPHE_DIR]
    for filename in _input_files():
        path = os.path.join(EPHE_DIR, filename)
        try:
            signature.append(
                (filename, _stat_identity(os.lstat(path)), _stat_identity(os.stat(path)))
            )
        except OSError:
            signature.append((filename, None))
    return tuple(signature)


def refresh_ephemeris_file_manifest() -> dict[str, dict]:
    """Re-stat the input files and rebuild the manifest when any of them changed."""

    global _MANIFEST_CACHE, _MANIFEST_RACY
    signature = input_files_signature()
    if _MANIFEST_CACHE is None or _MANIFEST_CACHE[0] != signature or _MANIFEST_RACY:
        hashing_began_ns = time.time_ns()
        manifest = _build_manifest()
        stable = input_files_signature() == signature
        _MANIFEST_RACY = _written_within_a_tick_of(signature, hashing_began_ns)
        _MANIFEST_CACHE = (signature if stable else None, manifest)
    return _MANIFEST_CACHE[1]


def _written_within_a_tick_of(signature: tuple, moment_ns: int) -> bool:
    """Whether any file's mtime or ctime is within one tick of ``moment_ns``.

    Only a stamp that close can be repeated by a later write in the same tick.
    A stamp more than a tick in the future (clock skew, a tree copied with its
    stamps) is not racy: any later write sets ctime to the then-current time,
    which differs from it, so the identity changes.  Treating it as racy
    rehashed every file at every chart start and readiness probe.
    """

    for entry in signature[1:]:
        for identity in entry[1:]:
            if identity is None:
                continue
            for stamp_ns in (identity[3], identity[4]):
                if abs(stamp_ns - moment_ns) < _TIMESTAMP_TICK_NS:
                    return True
    return False


def watch_chart_input_files() -> tuple | None:
    """Refresh the manifest and return the identity of the files it describes.

    Call before Swiss opens any file for a chart: Swiss opens the segments when
    the path is bound and again whenever it finds one missing, so what it read
    is known only if the files are the same at the chart's end
    (`input_files_unchanged_since`).  None when the files changed while they
    were being hashed.
    """

    refresh_ephemeris_file_manifest()
    return _MANIFEST_CACHE[0] if _MANIFEST_CACHE is not None else None


def input_files_unchanged_since(watch: tuple | None) -> bool:
    """True only if every input file still has the identity ``watch`` recorded.

    A rename, replacement or rewrite changes the inode or the ctime, so equal
    identities at both ends mean every Swiss read in between saw these files.
    """

    return watch is not None and input_files_signature() == watch


def ephemeris_file_manifest() -> dict[str, dict]:
    """Presence, size and sha256 of each bundled segment, as of the last refresh.

    A manifest built for a different directory is never returned: the directory
    comparison is a string compare, cheap enough for the hot path.
    """

    if (
        _MANIFEST_CACHE is None
        or _MANIFEST_CACHE[0] is None
        or _MANIFEST_CACHE[0][0] != EPHE_DIR
    ):
        return refresh_ephemeris_file_manifest()
    return _MANIFEST_CACHE[1]


def input_file_inventory() -> list[dict]:
    """Each bundled input file with its role, as of the last manifest refresh."""

    manifest = ephemeris_file_manifest()
    return [
        {
            "filename": filename,
            "role": (
                SEGMENT_MANIFEST[filename]["role"]
                if filename in SEGMENT_MANIFEST
                else AUXILIARY_INPUT_FILES[filename]
            ),
            "exists": manifest[filename]["present"],
            "size_bytes": manifest[filename]["size_bytes"],
            "sha256": manifest[filename]["sha256"],
            "matches_pinned_sha256": manifest[filename]["matches_pinned_sha256"],
        }
        for filename in _input_files()
    ]


# The answer for each file set, remembered for the manifest it was read from.
# Coverage checks ask before and after every Swiss call (tens of thousands of
# times for a high-latitude chart with every module), always for the same few
# sets; a new manifest (a refresh after the files changed) starts a new memo,
# and a manifest that was not cached is never answered from it.
_PRESENCE_MEMO: tuple[dict | None, dict[tuple[str, ...], bool]] = (None, {})


def segment_files_present(*filenames: str) -> bool:
    global _PRESENCE_MEMO
    source, answers = _PRESENCE_MEMO
    cache = _MANIFEST_CACHE
    # The hot path: the memo belongs to the manifest ephemeris_file_manifest()
    # would return now (same cached object, same directory).
    if (
        cache is not None
        and cache[1] is source
        and cache[0] is not None
        and cache[0][0] == EPHE_DIR
    ):
        present = answers.get(filenames)
        if present is not None:
            return present
    manifest = ephemeris_file_manifest()
    if source is not manifest:
        answers = {}
        _PRESENCE_MEMO = (manifest, answers)
    present = all(manifest.get(name, {}).get("present", False) for name in filenames)
    answers[filenames] = present
    return present


def has_full_ephemeris_files() -> bool:
    """Check the exact 1800–2399 planet/Moon segment used by the API, by manifest."""

    refresh_ephemeris_file_manifest()
    return segment_files_present(*CORE_SEGMENTS)


def coverage_state(jd_ut: float, segment: str) -> str:
    """Where ``jd_ut`` stands relative to one bundled segment (closed set)."""

    if not segment_files_present(segment):
        return COVERAGE_STATES[2]
    return _span_state(jd_ut, segment)


def _span_state(jd_ut: float, segment: str) -> str:
    """Covered or outside, for a segment whose file is present."""

    low, high = SEGMENT_MANIFEST[segment]["jd_ut_coverage"]
    if low <= jd_ut <= high:
        return COVERAGE_STATES[0]
    return COVERAGE_STATES[1]


def coverage_receipt(jd_ut: float, segment: str) -> dict:
    """The manifest facts a refusal or a body record carries."""

    state = coverage_state(jd_ut, segment)
    low, high = SEGMENT_MANIFEST[segment]["jd_ut_coverage"]
    return {
        "ephemeris_segment": segment,
        "coverage_state": state,
        "availability_reason_code": COVERAGE_REASON_CODES.get(state),
        "segment_jd_ut_coverage": {"low": low, "high": high},
        "jd_ut": jd_ut,
        "coverage_basis": "file_manifest_and_utc_julian_day_not_retflag",
    }


def _retflag_says_files(retflag: int) -> bool:
    """swe.calc_ut 的回傳旗標是否說這次用了星曆檔：有 SWIEPH、沒有 MOSEPH。"""
    return bool(retflag & swe.FLG_SWIEPH) and not retflag & swe.FLG_MOSEPH


# Which bundled segments one Swiss position actually reads, so a
# per-object source flag is not decided by the retflag alone.  Measured against
# Swiss Ephemeris 2.10.03 at JD(UT) 2447000.3, each core segment removed in turn
# with swe.close() between calls:
#
# - without semo_18 the Moon is a Moshier Moon (about 1.2″ geocentric, 0.003″
#   heliocentric or barycentric) while the retflag still says SWIEPH;
# - an Earth-observer (geocentric or topocentric) position reads the Earth as
#   the Earth-Moon barycentre minus the Moon's share, so the Sun, the planets,
#   Chiron and the fixed stars also move without semo_18 (at most about 5e-5″),
#   again under SWIEPH; their heliocentric and barycentric positions do not;
# - the true node and osculating apogee move without semo_18 on an Earth
#   centre (there Swiss does report MOSEPH) and do not read sepl_18;
# - the mean node, mean apogee and interpolated apogee/perigee are identical
#   with either core segment removed: they read no segment;
# - without sepl_18 Swiss reports MOSEPH, but presence is checked by manifest
#   all the same.
# tests/backend/test_ephemeris_coverage.py re-measures the semo_18 column
# against Swiss on every run.
_SEGMENT_FREE_BODIES: Final = frozenset({
    swe.MEAN_NODE, swe.MEAN_APOG, swe.INTP_APOG, swe.INTP_PERG,
})
_LUNAR_ORBIT_POINTS: Final = frozenset({swe.TRUE_NODE, swe.OSCU_APOG})
FIXED_STAR: Final = None


def segments_read_by(body: int | None, flags: int) -> tuple[str, ...]:
    """The bundled segments a Swiss position of ``body`` reads under ``flags``.

    ``body`` is a Swiss body number, or ``FIXED_STAR`` for a catalogue star.
    A body number outside the measured table is taken to read the planet
    segment and, from an Earth centre, the Moon segment, so an unmeasured body
    can only lose the file-backed claim, never gain it.
    """

    earth_observer = not flags & (swe.FLG_HELCTR | swe.FLG_BARYCTR)
    if body in _SEGMENT_FREE_BODIES:
        return ()
    if body == swe.MOON:
        return CORE_SEGMENTS
    if body in _LUNAR_ORBIT_POINTS:
        return ("semo_18.se1",) if earth_observer else ()
    segments = ("sepl_18.se1",) + (("semo_18.se1",) if earth_observer else ())
    if body == swe.CHIRON:
        segments += (CHIRON_SEGMENT,)
    return segments


def object_used_full_ephemeris(
    retflag: int,
    *,
    body: int | None,
    flags: int,
    jd_ut: float,
) -> bool:
    """Whether one position was served from the bundled files.

    The retflag must say SWIEPH and not MOSEPH, and every segment the position
    reads must cover ``jd_ut`` by manifest and be the pinned file: a Moshier
    Moon under a SWIEPH retflag, or a segment that is not the pinned dataset,
    is not reported as file-backed.  Only the flag is decided here; the
    computed values are whatever Swiss returned.
    """

    if not _retflag_says_files(retflag):
        return False
    manifest = ephemeris_file_manifest()
    # A star's position is read from the catalogue as well as the segments, so
    # the catalogue must be the pinned file too.
    if body is FIXED_STAR and manifest[FIXED_STAR_CATALOGUE]["matches_pinned_sha256"] is not True:
        return False
    return all(
        coverage_state(jd_ut, segment) == COVERAGE_STATES[0]
        and manifest[segment]["matches_pinned_sha256"]
        for segment in segments_read_by(body, flags)
    )


def require_object_coverage(
    *,
    body: int | None,
    flags: int,
    jd_ut: float,
    operation: str,
) -> None:
    """Refuse before calling Swiss when a segment the position reads is not covered.

    The module contract is that coverage is decided by manifest before the
    call.  Asking Swiss anyway is not a safe probe: a geocentric position past
    the segment end comes back as Moshier (refused by retflag afterwards), but
    a barycentric one raises ``swe.Error`` and a warm worker may extrapolate.
    """

    segments = segments_read_by(body, flags)
    # One presence question for the whole set; per segment only when a file is missing.
    all_present = segment_files_present(*segments)
    for segment in segments:
        state = _span_state(jd_ut, segment) if all_present else coverage_state(jd_ut, segment)
        if state != COVERAGE_STATES[0]:
            raise FullEphemerisRequiredError(
                operation=operation,
                jd_ut=jd_ut,
                retflag=0,
                reason=(
                    "segment_file_missing"
                    if state == COVERAGE_STATES[2]
                    else FULL_EPHEMERIS_OUT_OF_COVERAGE
                ),
            )


def guarded_calc(jd_ut: float, body: int, flags: int, operation: str) -> tuple[tuple, int]:
    """swe.calc_ut between the coverage check before and the retflag check after."""

    require_object_coverage(body=body, flags=flags, jd_ut=jd_ut, operation=operation)
    values, retflag = swe.calc_ut(jd_ut, body, flags)
    require_full_ephemeris(retflag, operation=operation, jd_ut=jd_ut)
    return values, retflag


def require_full_ephemeris(
    retflag: int,
    *,
    operation: str,
    jd_ut: float,
    segments: tuple[str, ...] = CORE_SEGMENTS,
) -> None:
    """Fail closed when a file-backed calculation silently changes ephemeris source.

    The retflag alone is not enough (module docstring, point 1): the segment
    files must also be present by manifest.
    """

    if not segment_files_present(*segments):
        raise FullEphemerisRequiredError(
            operation=operation,
            jd_ut=jd_ut,
            retflag=retflag,
            reason="segment_file_missing",
        )
    if not _retflag_says_files(retflag):
        raise FullEphemerisRequiredError(
            operation=operation,
            jd_ut=jd_ut,
            retflag=retflag,
        )
