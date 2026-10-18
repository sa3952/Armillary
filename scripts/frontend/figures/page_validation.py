"""The validation page's numbers: the DE442 run's size, and the scope,
tolerances and sample sizes of the standing comparisons its table lists.

The run itself (JPL DE442＋Astropy／ERFA against the product, 2026-07-28) and
its findings report are kept outside this repository; the configuration below
is the one that report records (§3.1).  The run's results (the share within
the thresholds, the largest differences) are its observations and are not
recomputed here.

The other rows are read from the tests and fixtures that hold them (JPL
Horizons positions and time scale, the NASA eclipse canon, the house closed
forms and the USNO day, the solar-return oracle, the civil-time sweep, the
fixed-star provenance), never typed.  The largest Horizons residuals are the
ones the accuracy article measures; that module holds this page to them.  The
largest solar-return difference is the resolution of a Julian-day double
(the report `tests.backend.test_solar_return_oracle --report` prints that
maximum); the tolerance above it is the test's.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
import math
import re

from ._common import ROOT, backend_on_path, swiss, zh


FRAGMENT = "validation"
START = datetime(1990, 1, 1, 0, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 28, 15, 30, tzinfo=timezone.utc)  # exclusive
STEP = timedelta(hours=1)
BODIES = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
TESTS = ROOT / "tests" / "backend"
FIXTURES = TESTS / "fixtures"


def size() -> tuple[int, int]:
    points = math.ceil((END - START) / STEP)
    return points, points * len(BODIES)


def _constants(path, names: tuple[str, ...]) -> dict:
    found = {}
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in names:
                found[node.targets[0].id] = ast.literal_eval(node.value)
    if set(found) != set(names):
        raise RuntimeError(f"{path.name}: constants not found: {sorted(set(names) - set(found))}")
    return found


def _search(pattern: str, text: str, what: str) -> re.Match:
    found = re.search(pattern, text)
    if found is None:
        raise RuntimeError(f"{what} no longer states {pattern!r}")
    return found


def _year(utc: str) -> int:
    return int(utc[:4])


def _horizons() -> list[str]:
    fixture = json.loads((FIXTURES / "jpl_horizons_positions.json").read_text(encoding="utf-8"))
    tol = fixture["tolerances_arcsec"]
    years = [_year(epoch["utc"]) for epoch in fixture["epochs"]]
    # The time-scale test reads the epochs in the leap-second era it names.
    source = (TESTS / "test_external_astronomy_baselines.py").read_text(encoding="utf-8")
    lo, hi = map(int, _search(r"if (\d{4}) <= _parse_utc\(epoch\[\"utc\"\]\)\.year <= (\d{4})", source,
                              "the time-scale test").groups())
    utc_era = [year for year in years if lo <= year <= hi]
    return [
        f"<td>{min(years)} 到 {max(years)} 年之間</td>",
        f'<td class="num">{len(years)} 個時刻</td>',
        f"黃經容許 {tol['geocentric_longitude_absolute_1900_2100']:g} 角秒"
        f"（2100 年以後 {tol['geocentric_longitude_absolute_after_2100']:g} 角秒），"
        f"黃緯 {tol['geocentric_latitude_absolute']:g} 角秒，"
        f"扣掉太陽的共同偏移之後 {tol['geocentric_longitude_relative_to_sun']:g} 角秒",
        f"<td>{lo} 到 {hi} 年（有閏秒的年代）</td>",
        f'<td class="num">{len(utc_era)} 個時刻</td>',
        f"<td>容許 {tol['time_scale_tt_seconds_utc_era'] * 1000:g} 毫秒</td>",
        f"要求不超過 {tol['geocentric_longitude_relative_to_sun']:g} 角秒。後者才是在檢查星曆本身",
    ]


def _eclipses() -> list[str]:
    fixture = json.loads((FIXTURES / "nasa_eclipse_canon_selection.json").read_text(encoding="utf-8"))
    selection = fixture["provenance"]["selection"]
    why = fixture["tolerance_td_seconds_why"]
    full = _search(r"all (\d+) eclipses in (\d{4})-(\d{4}) whose .*?\(full comparison of (\d+) eclipses, "
                   r"(\d{4}-\d{2}-\d{2})\)", selection, "the eclipse fixture")
    measured = _search(r"measured \|difference\| <= ([0-9.]+) s over (\d+) eclipses \(median ([0-9.]+) s\)",
                       why, "the eclipse fixture")
    if full[4] != measured[2]:
        raise RuntimeError("the eclipse fixture's two counts differ")
    return [
        f"<td>{full[2]} 到 {full[3]} 年</td>",
        f'<td class="num">{full[4]} 次</td>',
        f"食甚時刻容許 {fixture['tolerance_td_seconds']:g} 秒，實測最大 {measured[1]} 秒（中位數 {measured[3]} 秒）",
        f"有 {full[1]} 次與日食典不同",
        f"全面比對做過一次（{full[5]}）；常設測試保留那 {full[1]} 次",
        f"所以容許值寫的是 {fixture['tolerance_td_seconds']:g} 秒",
    ]


def _houses() -> list[str]:
    found = _constants(TESTS / "test_house_product_path.py",
                       ("SYSTEM_CODES", "CASES", "TOLERANCE_ARCSEC", "USNO_TOLERANCE_ARCSEC"))
    years = [case[1][0] for case in found["CASES"]]
    latitude = max((case[2] for case in found["CASES"]), key=abs)
    if latitude <= 0:
        raise RuntimeError("the highest house-test latitude is no longer northern")
    usno = json.loads((FIXTURES / "usno_2000_01_01_taipei.json").read_text(encoding="utf-8"))
    return [
        f"<td>{min(years)} 到 {max(years)} 年，南北半球、赤道與北緯 {int(latitude)} 度</td>",
        f'<td class="num">{len(found["SYSTEM_CODES"])} 種宮位制 × {len(found["CASES"])} 個地點與年代</td>',
        f"<td>差小於 {found['TOLERANCE_ARCSEC']:g} 角秒</td>",
        f"宮頭容許 {found['USNO_TOLERANCE_ARCSEC']:g} 角秒",
        f"本站提供的{zh(len(found['SYSTEM_CODES']))}種宮位制",
        *_usno(usno),
    ]


def _usno(fixture: dict) -> list[str]:
    if (fixture["input"]["app_local_time"], fixture["input"]["app_timezone"]) != ("2000-01-01 12:00:00", "Asia/Taipei"):
        raise RuntimeError("the USNO fixture is no longer New Year's Day 2000 at noon in Taipei")
    events = (TESTS / "test_horizon_events.py").read_text(encoding="utf-8")
    rise_set = int(_search(r"\(actual_local - expected_local\)\.total_seconds\(\)\) < (\d+)", events,
                           "the USNO rise-set test")[1])
    if rise_set % 60:
        raise RuntimeError("the USNO rise-set tolerance is no longer whole minutes")
    return [
        "<td>2000 年元旦中午，臺北</td>",
        f"恆星時容許 {fixture['tolerance']['time_seconds']:g} 秒",
        f"日出、中天、日落容許 {rise_set // 60} 分鐘",
    ]


def _solar_return() -> list[str]:
    fixture = json.loads((FIXTURES / "solar_return_oracle_sample.json").read_text(encoding="utf-8"))
    cases = fixture["cases"]
    # The returns the test compares: SR_k (k > 0) and SR_k+1, each inside the supported range.
    compared = sum((case["completed_years"] > 0 and case["sr_k_in_range"])
                   + (case["sr_k_in_range"] and case["sr_k_plus_1_in_range"]) for case in cases)
    instants = [case[key] for case in cases for key in ("sr_k_jd_ut", "sr_k_plus_1_jd_ut") if case[key]]
    ulps = {math.ulp(jd) for jd in instants}
    if len(ulps) != 1:
        raise RuntimeError("the sample's Julian days no longer share one resolution")
    resolution_us = ulps.pop() * 86400.0 * 1e6
    years = [case["local"]["year"] for case in cases]
    ages = [case["completed_years"] for case in cases]
    test = TESTS / "test_solar_return_oracle.py"
    source = test.read_text(encoding="utf-8")
    found = _constants(test, ("TOLERANCE_SECONDS", "LOCATIONS"))
    direction = _search(r"_separation_arcsec\(swiss, row\[\"icrf_au\"\]\) < ([0-9.]+)", source,
                        "the DE441 solar-return test")[1]
    frame = _search(r"falls up to ~([0-9.]+) s", source, "the DE441 solar-return test")[1]
    horizons = json.loads((FIXTURES / "jpl_horizons_solar_return_oracle.json").read_text(encoding="utf-8"))
    pairs = [_year(case["sample_utc"]) for case in horizons["cases"]]
    return [
        f"<td>出生 {min(years)} 到 {max(years)} 年，{min(ages)} 到 {max(ages)} 歲</td>",
        f'<td class="num">{len(cases)} 筆出生、{compared} 個回歸時刻</td>',
        f"<td>容許 {found['TOLERANCE_SECONDS']:g} 秒；實測最大 {resolution_us:.0f} 微秒，中位數 0</td>",
        f"最小能分辨的間隔約 {resolution_us:.0f} 微秒",
        f"{compared} 個回歸時刻中，一半以上完全相同",
        f"測試的容許值是 {found['TOLERANCE_SECONDS']:g} 秒",
        f"<td>{'、'.join(map(str, pairs))} 年的出生</td>",
        f'<td class="num">{len(pairs)} 對出生與回歸</td>',
        f"<td>方向差容許 {direction} 角秒</td>",
        f'<td class="num">{len(found["LOCATIONS"])} 個地點</td>',
        f"回歸時刻最多差約 {frame} 秒",
    ]


def _sidereal_time() -> list[str]:
    fixture = json.loads((FIXTURES / "jpl_horizons_sidereal_time_2050_2399.json").read_text(encoding="utf-8"))
    years = [int(row["label"][:4]) for row in fixture["tt_rows"]]
    return [
        f"<td>{min(years)} 到 {max(years)} 年，以及 2050 年元旦前後兩小時</td>"
        f'<td class="num">{len(years)} 個時刻</td>',
    ]


def _civil_time() -> list[str]:
    source = (TESTS / "test_civil_time_exhaustive.py").read_text(encoding="utf-8")
    start = int(_search(r"SWEEP_START = dtmod\.datetime\((\d{4}), 1, 1", source, "the civil-time sweep")[1])
    end = int(_search(r"SWEEP_END = dtmod\.datetime\((\d{4}), 1, 1", source, "the civil-time sweep")[1]) - 1
    return [
        f"<td>{start} 到 {end} 年，每個時區檔的每一次偏移變動</td>",
        f"每一個時區檔，從 {start} 到 {end} 年",
    ]


def _fixed_stars() -> list[str]:
    fixture = json.loads((FIXTURES / "fixed_star_provenance.json").read_text(encoding="utf-8"))
    tol = fixture["tolerances_arcsec"]
    years = [_year(epoch["utc"]) for epoch in fixture["epochs"]]

    def pair(key: str) -> str:
        return f"容許 {tol[key]['value']:g} 角秒（實測 {tol[key]['measured_max']:g} 角秒）"

    return [
        f"<td>{'、'.join(map(str, years))} 年</td>",
        f"同一筆星表記錄{pair('same_record')}；對 Hipparcos 2007 {pair('hipparcos_2007')}；"
        f"SIMBAD 已改用 Gaia DR3 的星{pair('current_simbad_updated_astrometry')}",
    ]


def _engine() -> list[str]:
    with swiss():
        with backend_on_path():
            from app import chart_pipeline, domain_catalog

            library = chart_pipeline._library_info()
            lo, hi = domain_catalog.PRODUCT_YEAR_RANGE
    return [
        f"Swiss Ephemeris {library['swiss_ephemeris_library_version']}"
        f"（Python 介面 pyswisseph {library['pyswisseph_distribution_version']}），接受 {lo} 到 {hi} 年的日期",
        f"在 {lo} 到 {hi} 年之間，本站算出的日月五星位置",
    ]


def build() -> tuple[dict[str, str], list[str]]:
    points, rows = size()
    quoted = [
        f"<b>{rows:,}</b><span>天體—小時比對列</span><small>{START.year}–{END.year}，{zh(len(BODIES))}個天體",
        f"{START:%Y-%m-%d}至{END:%Y-%m-%d}，逐小時，共{points:,}個時點",
        f'<td class="num">{rows:,} 列</td>',
        f"<td>{START.year} 到 {END.year} 年，逐小時</td>",
        *_horizons(), *_eclipses(), *_houses(), *_solar_return(), *_sidereal_time(), *_civil_time(), *_fixed_stars(), *_engine(),
    ]
    return {}, quoted
