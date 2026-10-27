"""〈黑月 Lilith 的平均、密切與自然〉: figure 1 (osculating and natural apogee minus the mean apogee over 2026), figure 2
(how often each puts Lilith in a different sign from the mean one, 1950–2050), table 1 and the numbers the prose quotes.

The product does not offer the osculating apogee (OSCU_APOG), the point most software labels "true Lilith".  It is
computed directly with Swiss and the repository's ephemeris files, with the product's own flags, and Swiss's mean and
natural points are checked against the product's answer for the demonstration chart.
"""
from __future__ import annotations

import functools
import statistics

from . import _fx
from ._common import calc_ut, product_charts, swiss
from ._demo import DEMO, zodiacal_minutes

FRAGMENT = "blog-black-moon-lilith-mean-true-natural"
MONTH_STARTS = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334, 365)
SCALES = {"osculating": (32.0, (-30, -15, 0, 15, 30)), "natural": (8.0, (-6, -3, 0, 3, 6))}
VARIANTS = (("osculating", "密切（常稱真 Lilith）減平均"), ("natural", "自然減平均"))
LONG_RANGE = (1950, 2050)

def _wrap(value: float) -> float:
    return ((value + 180) % 360) - 180

def _sign(lon: float) -> int:
    return int(lon // 30) % 12

def _year_2026(swe) -> dict:
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    j0 = swe.julday(2026, 1, 1, 0)
    osc, nat, priapus = [], [], []
    for i in range(365 * 4 + 1):
        jd = j0 + i / 4
        mean = calc_ut(swe, jd, swe.MEAN_APOG, flags)[0]
        natural = calc_ut(swe, jd, swe.INTP_APOG, flags)[0]
        osc.append((i / 4, round(_wrap(calc_ut(swe, jd, swe.OSCU_APOG, flags)[0] - mean), 4)))
        nat.append((i / 4, round(_wrap(natural - mean), 4)))
        priapus.append(abs(_wrap(calc_ut(swe, jd, swe.INTP_PERG, flags)[0] - natural - 180)))
    return {"osculating": osc, "natural": nat, "priapus_max": max(priapus),
            "mean_speed": calc_ut(swe, j0, swe.MEAN_APOG, flags)[3]}

def _long_range(swe) -> dict:
    flags = swe.FLG_SWIEPH
    j0, end = swe.julday(LONG_RANGE[0], 1, 1, 0), swe.julday(LONG_RANGE[1], 1, 1, 0)
    osc, nat = [], []
    other = {"osculating": 0, "natural": 0}
    days = int(round(end - j0))
    for i in range(days):
        jd = j0 + i
        mean = calc_ut(swe, jd, swe.MEAN_APOG, flags)[0]
        o = calc_ut(swe, jd, swe.OSCU_APOG, flags)[0]
        n = calc_ut(swe, jd, swe.INTP_APOG, flags)[0]
        osc.append(abs(_wrap(o - mean)))
        nat.append(abs(_wrap(n - mean)))
        other["osculating"] += _sign(o) != _sign(mean)
        other["natural"] += _sign(n) != _sign(mean)
    return {"count": days,
            "osculating": {"max": max(osc), "median": statistics.median(osc), "other_sign": other["osculating"] / days},
            "natural": {"max": max(nat), "median": statistics.median(nat), "other_sign": other["natural"] / days}}

@functools.lru_cache(maxsize=1)
def answers() -> dict:
    with product_charts() as post:
        chart = post({**DEMO, "options": {**DEMO["options"], "include_lilith_priapus": True}})
    apsides = chart["astronomical_data"]["lunar_apsides"]
    points = {p["key"]: p["longitude"] for p in apsides["points"]}
    jd = chart["astronomical_data"]["time"]["jd_ut"]
    with swiss() as swe:
        flags = swe.FLG_SWIEPH | swe.FLG_SPEED
        demo_swiss = {"mean_lilith": calc_ut(swe, jd, swe.MEAN_APOG, flags)[0],
                      "natural_lilith": calc_ut(swe, jd, swe.INTP_APOG, flags)[0],
                      "natural_priapus": calc_ut(swe, jd, swe.INTP_PERG, flags)[0],
                      "osculating": calc_ut(swe, jd, swe.OSCU_APOG, flags)[0]}
        year = _year_2026(swe)
        long_range = _long_range(swe)
    return {"points": points, "swiss": demo_swiss, "source": apsides["source"],
            "scope": apsides["scope"], "year": year, "long": long_range}

def _check(data: dict) -> None:
    if set(data["points"]) != {"mean_lilith", "natural_lilith", "natural_priapus"}:
        raise RuntimeError(f"the product's lunar apsides are now {sorted(data['points'])}")
    for key, lon in data["points"].items():
        if abs(_wrap(lon - data["swiss"][key])) > 1e-9:
            raise RuntimeError(f"the product's {key} is no longer Swiss's point for the same instant")
    if data["scope"]["natural_priapus_is_not_forced_opposite_natural_lilith"] is not True:
        raise RuntimeError("the product now forces natural Priapus opposite natural Lilith")
    for key, (span, _) in SCALES.items():
        values = [abs(v) for _, v in data["year"][key]]
        if not max(values) < span:
            raise RuntimeError(f"the 2026 {key} differences no longer fit figure 1's scale")

# --- figure 1: 2026 ----------------------------------------------------------------

def _deg(v: float) -> str:
    return "0°" if v == 0 else f"{'+' if v > 0 else '−'}{abs(v):g}°"

def _panel(series: list, span: float, grid: tuple, d0: float, d1: float, box: tuple, wide: bool,
           bound: _fx.Bound) -> list[str]:
    L, R, T, B = box
    X = lambda day: L + (R - L) * (day - d0) / (d1 - d0)  # noqa: E731
    Y = lambda v: T + (B - T) * (span - v) / (2 * span)  # noqa: E731
    out = []
    for v in grid:
        out.append(_fx.line(L, Y(v), R, Y(v), "fx-axis" if v == 0 else "fx-hair"))
        out.append(_fx.text(L - (10 if wide else 6), Y(v) + 5, bound.scale(_deg(v)), "fx-t fx-small fx-num", "end"))
    for i, start in enumerate(MONTH_STARTS[:-1]):
        stop = MONTH_STARTS[i + 1]
        if start < d0 or stop > d1:
            continue
        out.append(_fx.line(X(start), B, X(start), B + 6, "fx-axis"))
        out.append(_fx.text(X((start + stop) / 2), B + (24 if wide else 20), bound.scale(f"{i + 1} 月"),
                            "fx-t fx-small", "middle"))
    out.append(_fx.line(X(d1), B, X(d1), B + 6, "fx-axis"))
    points = [(t, v) for t, v in series if d0 <= t <= d1]
    out.append(_fx.path("M" + " L".join(f"{_fx.f(X(t))} {_fx.f(Y(v))}" for t, v in points), "fx-curve"))
    return out

def _year_art(layout: str, fid: str, year: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W, H = (_fx.WIDE, 384) if wide else (_fx.NARROW, 500)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    for key, label in VARIANTS:
        span, grid = SCALES[key]
        body = []
        if wide:
            body.append(_fx.text(92, 36, f"{label}（度）", "fx-t"))
            body.append(_fx.text(852, 36, f"2026 年，每 {bound.label('6')} 小時一點", "fx-t fx-small fx-dim", "end"))
            body += _panel(year[key], span, grid, 0, 365, (92, 852, 64, 300), True, bound)
        else:
            body.append(_fx.text(14, 28, label, "fx-t"))
            body.append(_fx.text(14, 48, f"單位：度；每 {bound.label('6')} 小時一點", "fx-t fx-small fx-dim"))
            for d0, d1, top, name in ((0, 181, 96, "1–6 月"), (181, 365, 298, "7–12 月")):
                body.append(_fx.text(46, top - 14, bound.scale(f"2026 年 {name}"), "fx-t fx-small fx-dim"))
                body += _panel(year[key], span, grid, d0, d1, (46, 326, top, top + 128), False, bound)
        body.append(_fx.text(92 if wide else 14, H - 18,
                             "刻度：上下各 " + bound.scale(f"{grid[-1]}") + " 度" + ("；兩個選項的刻度不同" if wide else ""),
                             "fx-t fx-small fx-dim"))
        out.append(_fx.variant_group(key, VARIANTS[0][0], "".join(body)))
    out.append("</svg>")
    return "".join(out)

def _figure_year(data: dict) -> str:
    bound = _fx.Bound()
    year = data["year"]
    osc = max(abs(v) for _, v in year["osculating"])
    nat = max(abs(v) for _, v in year["natural"])
    osc_text, nat_text = bound.num(f"{osc:.1f}"), bound.num(f"{nat:.1f}")
    rows = []
    for month in range(12):
        lo, hi = MONTH_STARTS[month], MONTH_STARTS[month + 1]
        o = max(abs(v) for t, v in year["osculating"] if lo <= t < hi)
        n = max(abs(v) for t, v in year["natural"] if lo <= t < hi)
        rows.append(f'<tr><th scope="row">{bound.scale(f"{month + 1} 月")}</th>'
                    f'<td class="n">{bound.num(f"{o:.1f}°")}</td><td class="n">{bound.num(f"{n:.1f}°")}</td></tr>')
    table = _fx.data_table(("月份", "密切減平均，最大差", "自然減平均，最大差"), rows)
    caption = (f"<b>{bound.label('圖 1')}</b>以 {bound.label('2026')} 年全年為例，每 {bound.label('6')} 小時算一點："
               "按鈕切換密切 Lilith（多數軟體叫「真 Lilith」）與自然 Lilith，各自減去平均 Lilith 的差。"
               f"密切的這一年最多差 {osc_text} 度，大約每個月來回擺一次；自然的最多差 {nat_text} 度。"
               "兩個選項的縱軸刻度不同；沒有開啟腳本時顯示密切的那一張"
               f"<a class=\"ar-cite\" href=\"#ref-4\">{bound.label('[4]')}</a>。")
    return _fx.figure(fid="fig-lilith-2026", hero=True,
        title="2026 年全年，密切 Lilith 與自然 Lilith 各自減去平均 Lilith 的差", caption=caption,
        art=_fx.FigureArt.drawn(_year_art, "fig-lilith-2026", year, bound),
        controls=_fx.FigureControls(variants=VARIANTS, switch_label="比較哪一種"), table=table, bound=bound)

# --- figure 2: how often the sign differs ---------------------------------------

ROWS = (("osculating", "密切 Lilith", "常稱真 Lilith；本站不提供"), ("natural", "自然 Lilith", "本站提供"))

def _pct(share: float) -> str:
    return f"{share * 100:.1f}%"

def _bars_art(layout: str, fid: str, long: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    W, H = (_fx.WIDE, 300) if wide else (_fx.NARROW, 380)
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    if wide:
        L, R, top, gap = 250.0, 820.0, 92.0, 82.0
        out.append(_fx.text(24, 40, "和平均 Lilith 落在不同星座的時間比例", "fx-t"))
    else:
        L, R, top, gap = 14.0, 300.0, 120.0, 112.0
        out.append(_fx.text(14, 30, "和平均 Lilith 落在", "fx-t"))
        out.append(_fx.text(14, 50, "不同星座的時間比例", "fx-t"))
    X = lambda share: L + (R - L) * share / 0.5  # noqa: E731
    base = top + gap * len(ROWS) - 30
    for tick in (0, 0.1, 0.2, 0.3, 0.4, 0.5):
        if not wide and tick not in (0, 0.25, 0.5) and tick not in (0.1, 0.3):
            continue
        out.append(_fx.line(X(tick), top - 30, X(tick), base, "fx-hair"))
        out.append(_fx.text(X(tick), base + 20, bound.scale(f"{tick * 100:.0f}%"), "fx-t fx-small fx-num", "middle"))
    for i, (key, name, note) in enumerate(ROWS):
        y = top + gap * i
        share = long[key]["other_sign"]
        value = bound.num(_pct(share))
        if wide:
            out.append(_fx.text(24, y + 4, name, "fx-t"))
            out.append(_fx.text(24, y + 26, note, "fx-t fx-small fx-dim"))
        else:
            out.append(_fx.text(14, y - 22, f"{name}（{note}）", "fx-t fx-small"))
        out.append(_fx.rect(L, y - 14, R - L, 24, "fx-track"))
        out.append(_fx.rect(L, y - 14, X(share) - L, 24, "fx-fill-solid" if key == "osculating" else "fx-fill-hatch"))
        out.append(_fx.text(X(share) + 8, y + 5, value, "fx-t fx-num"))
    out.append(_fx.text(L, H - 18 if wide else H - 16,
                        f"{bound.label('1950–2049')} 年每天世界時 {bound.label('0')} 時取一點", "fx-t fx-small fx-dim"))
    out.append("</svg>")
    return "".join(out)

def _figure_bars(data: dict) -> str:
    bound = _fx.Bound()
    long = data["long"]
    rows = []
    for key, name, _ in ROWS:
        item = long[key]
        rows.append(f'<tr><th scope="row">{name}</th><td class="n">{bound.num(_pct(item["other_sign"]))}</td>'
                    f'<td class="n">{bound.num(f"{item["median"]:.1f}°")}</td>'
                    f'<td class="n">{bound.num(f"{item["max"]:.1f}°")}</td></tr>')
    table = _fx.data_table(("和平均 Lilith 比", "落在不同星座的時間", "差的中位數", "最大差"), rows)
    count = bound.num(f"{long['count']:,}")
    caption = (f"<b>{bound.label('圖 2')}</b>從 {bound.label('1950–2049')} 年每天世界時 {bound.label('0')} 時取一點"
               f"（共 {count} 天），看密切 Lilith 與自然 Lilith 跟平均 Lilith 是不是落在同一個星座。"
               f"密切的有 {bound.num(_pct(long['osculating']['other_sign']))} 的時間落在別的星座，"
               f"自然的是 {bound.num(_pct(long['natural']['other_sign']))}。表格另列差的中位數與最大差"
               f"<a class=\"ar-cite\" href=\"#ref-4\">{bound.label('[4]')}</a>。")
    return _fx.figure(fid="fig-lilith-sign", title="1950–2049 年，密切與自然 Lilith 跟平均 Lilith 落在不同星座的時間比例",
        caption=caption, art=_fx.FigureArt.drawn(_bars_art, "fig-lilith-sign", long, bound), table=table, bound=bound)

# --- table 1: the demonstration chart --------------------------------------------

def _signed(value: float) -> str:
    text = f"{abs(value):.1f}°"
    return text if text == "0.0°" else ("+" if value > 0 else "−") + text

def _demo_rows(data: dict) -> str:
    p, s = data["points"], data["swiss"]
    rows = (("平均黑月 Lilith", p["mean_lilith"], "本站提供"), ("自然黑月 Lilith", p["natural_lilith"], "本站提供"),
        ("密切 Lilith（常稱真 Lilith）", s["osculating"], "本站不提供；以同一星曆另算"),
        ("自然月球近地點 Priapus", p["natural_priapus"], "本站提供"))
    return "\n".join(
        f'          <tr><th scope="row">{name}</th><td class="n">{zodiacal_minutes(lon)}</td>'
        f'<td class="n">{_signed(_wrap(lon - p["mean_lilith"] if "Priapus" not in name else lon - p["natural_lilith"] - 180))}</td>'
        f'<td>{note}</td></tr>'
        for name, lon, note in rows)

def build() -> tuple[dict[str, str], list[str]]:
    data = answers()
    _check(data)
    p, s, long, year = data["points"], data["swiss"], data["long"], data["year"]
    osc_demo = _wrap(s["osculating"] - p["mean_lilith"])
    priapus_demo = _wrap(p["natural_priapus"] - p["natural_lilith"] - 180)
    figures = {"lilith-2026": _figure_year(data), "lilith-sign": _figure_bars(data), "demo": _demo_rows(data)}
    quoted = [
        f"平均 Lilith 每天前進約 {year['mean_speed']:.3f} 度，約 {360 / year['mean_speed'] / 365.25:.1f} 年繞黃道一圈",
        f"<b>{long['osculating']['max']:.1f}°</b><span>密切 Lilith 離平均 Lilith 的最大差",
        f"<b>{_pct(long['osculating']['other_sign'])}</b><span>的時間，密切 Lilith",
        f"<b>{long['natural']['max']:.1f}°</b><span>自然 Lilith 離平均 Lilith 的最大差",
        f"<b>{_pct(long['natural']['other_sign'])}</b><span>的時間，自然 Lilith",
        f"密切 Lilith 最多差 {long['osculating']['max']:.1f} 度，中位數 {long['osculating']['median']:.1f} 度",
        f"自然 Lilith 最多差 {long['natural']['max']:.1f} 度，中位數 {long['natural']['median']:.1f} 度",
        f"{_pct(long['osculating']['other_sign'])} 的時間",
        f"自然 Lilith 只有 {_pct(long['natural']['other_sign'])}",
        f"密切 Lilith 在{zodiacal_minutes(s['osculating'])}",
        f"比平均 Lilith {'多' if osc_demo > 0 else '少'} {abs(osc_demo):.1f} 度",
        f"自然 Priapus 離自然 Lilith 的正對面 {abs(priapus_demo):.1f} 度",
        f"2026 年最多差到 {year['priapus_max']:.1f} 度",
        f"平均 Lilith 在{zodiacal_minutes(p['mean_lilith'])}",
        f"自然 Lilith 在{zodiacal_minutes(p['natural_lilith'])}",
    ]
    if _sign(p["mean_lilith"]) != _sign(p["natural_lilith"]) or _sign(s["osculating"]) == _sign(p["mean_lilith"]):
        raise RuntimeError("the example no longer has mean and natural Lilith in one sign and the osculating in another")
    return {"fx-defs": _fx.defs(()), **figures}, quoted
