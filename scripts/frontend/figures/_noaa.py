"""The NOAA solar calculator's formulas, as an oracle independent of Swiss.

Transcribed from the cell formulas of NOAA Global Monitoring Laboratory's
spreadsheet NOAA_Solar_Calculations_day (linked from
https://gml.noaa.gov/grad/solcalc/calcdetails.html; the page says the
equations come from Meeus, Astronomical Algorithms, and are accurate to about a
minute between ±72° latitude).  Nothing here calls Swiss Ephemeris or the
product, so an article can check one of its numbers against a second
algorithm.  Time argument: Julian Day of UT (the spreadsheet's input is local
clock time minus its time zone; the difference between UTC and UT1 is below a
second and far below the formulas' accuracy).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import math


def julian_day(utc: datetime) -> float:
    if utc.tzinfo is None:
        raise ValueError("an aware UTC datetime is required")
    return utc.timestamp() / 86400.0 + 2440587.5


def sun(jd: float) -> dict[str, float]:
    """Columns G–V of the spreadsheet: apparent longitude, declination and the
    equation of time (minutes) at one instant."""
    rad, deg = math.radians, math.degrees
    t = (jd - 2451545) / 36525
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    c = (math.sin(rad(m)) * (1.914602 - t * (0.004817 + 0.000014 * t))
         + math.sin(rad(2 * m)) * (0.019993 - 0.000101 * t) + math.sin(rad(3 * m)) * 0.000289)
    true_long = l0 + c
    app_long = true_long - 0.00569 - 0.00478 * math.sin(rad(125.04 - 1934.136 * t))
    mean_obliq = 23 + (26 + ((21.448 - t * (46.815 + t * (0.00059 - t * 0.001813)))) / 60) / 60
    obliq = mean_obliq + 0.00256 * math.cos(rad(125.04 - 1934.136 * t))
    decl = deg(math.asin(math.sin(rad(obliq)) * math.sin(rad(app_long))))
    y = math.tan(rad(obliq / 2)) ** 2
    eot = 4 * deg(y * math.sin(2 * rad(l0)) - 2 * e * math.sin(rad(m))
                  + 4 * e * y * math.sin(rad(m)) * math.cos(2 * rad(l0))
                  - 0.5 * y * y * math.sin(4 * rad(l0)) - 1.25 * e * e * math.sin(2 * rad(m)))
    return {"apparent_longitude": app_long % 360, "declination": decl, "equation_of_time_minutes": eot}


def sunrise_utc(noon_date: date, latitude: float, longitude: float, zenith: float = 90.833) -> datetime:
    """Sunrise (UTC) before the local solar noon that falls on the UT date
    `noon_date`, from the spreadsheet's hour-angle formula (column W, with the
    zenith as a parameter: 90.833 is NOAA's refracted upper limb, 90 the
    geometric centre) and solar noon (column X with time zone 0), re-evaluated
    at its own result until it settles."""
    rad, deg = math.radians, math.degrees
    base = datetime(noon_date.year, noon_date.month, noon_date.day, tzinfo=timezone.utc)
    t = base + timedelta(minutes=720 - 4 * longitude)
    for _ in range(8):
        s = sun(julian_day(t))
        cos_ha = (math.cos(rad(zenith)) / (math.cos(rad(latitude)) * math.cos(rad(s["declination"])))
                  - math.tan(rad(latitude)) * math.tan(rad(s["declination"])))
        ha = deg(math.acos(cos_ha))
        t = base + timedelta(minutes=720 - 4 * longitude - s["equation_of_time_minutes"] - 4 * ha)
    return t
