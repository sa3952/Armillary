"""〈宮位制有哪些〉: the static celestial-sphere figure of each house system, the
two polar figures, the cusp table of one generic sky, and the oracle numbers
the article quotes.

Each static figure is an article figure plate (`_fx`, direction 甲): a wide
drawing (the sphere with a side panel: what this system cuts, a key to the
lines, each house's size) and a phone drawing recomposed in one column.  The
sphere inside both is the script's own scene (`HouseSphere.plate`), placed by
the frames below.

The figures are drawn by the article's own browser script
(`scripts/frontend/scripts/house-sphere.js`, through Node), so the static figure a reader sees
without JavaScript or on paper is the interactive figure's first frame.  The
numbers are not taken from that script: the cusp table comes from Swiss
Ephemeris `houses_armc`, and every figure's cusps are compared with it here;
the grid comparison the article reports is `oracle_grid()`, which
tests/publication/test_house_sphere_oracle.py also runs.

Generic geometry only: a latitude, a local sidereal time (ARMC) and the fixed
obliquity the script uses.  No date, time or place of birth.
"""
from __future__ import annotations

import re

from html import escape

from . import _fx
from ._common import ROOT, SIGNS, node_json, swiss


FRAGMENT = "blog-house-systems-explained"
SCRIPTS = ROOT / "scripts" / "frontend" / "scripts"
SYSTEMS = "WEOBCRP"
NAMES = {"W": "整宮", "E": "等分宮", "O": "Porphyry", "B": "Alcabitius", "C": "Campanus", "R": "Regiomontanus",
         "P": "Placidus"}
POLAR_LAT = 69.65  # Tromsø
MC_BELOW_ARMC = 270.0  # at Tromsø the MC then culminates about 3° below the horizon


def figures(start: dict) -> dict[str, tuple[str, float, float]]:
    """One figure per system on the article's sky (the interactive figure's
    first frame, `HouseSphere.START`), Placidus in the polar band, and
    Regiomontanus when the MC culminates below the horizon."""
    lat, armc = start["lat"], start["armc"]
    out = {f"sphere-{s.lower()}": (s, lat, armc) for s in SYSTEMS}
    out["sphere-polar-p"] = ("P", POLAR_LAT, armc)
    out["sphere-mc-below"] = ("R", POLAR_LAT, MC_BELOW_ARMC)
    return out
# The script's answers may differ from Swiss Ephemeris by this much (arcseconds).
TOLERANCE_ARCSEC = 0.01
# The oracle grid: every 3° of latitude to ±87° plus the edge of the polar band,
# local sidereal time every 15° (offset 7.5° off the quadrant boundaries).
GRID_LATITUDES = tuple(3.0 * k for k in range(-29, 30)) + (66.5, -66.5, 66.55, -66.55)
GRID_ARMCS = tuple(7.5 + 15.0 * k for k in range(24))

_NODE_SCRIPT = r"""
const Core = require(process.argv[1]);
const Sphere = require(process.argv[2]);
let input = "";
process.stdin.on("data", (chunk) => { input += chunk; }).on("end", () => {
  const job = JSON.parse(input);
  const out = {
    obliquity: Core.OBLIQUITY,
    start: Sphere.START,
    view: Sphere.DEFAULT_VIEW,
    flag: Sphere.FLAG,
    names: Sphere.NAMES,
    captions: Sphere.CAPTIONS,
    cusps: job.cusps.map(([sys, lat, armc]) => {
      const result = Core.cusps(sys, lat, armc, Core.OBLIQUITY);
      return { cusps: result.cusps, status: Core.siteStatus(sys, lat, armc, Core.OBLIQUITY) };
    }),
    scenes: job.scenes.map((item) => Sphere.toMarkup(item.frame ? Sphere.plate(item.state, item.frame) : Sphere.scene(item))),
    describes: (job.describes || []).map(([sys, lat, armc]) => {
      const state = { sys, lat, armc };
      return Sphere.describe(state, Sphere.evaluate(state));
    }),
    texts: job.scenes.map((item) => {
      const state = item.frame ? item.state : item;
      return { describe: Sphere.describe(state, Sphere.evaluate(state)), lat: Sphere.fmtLat(state.lat), lst: Sphere.fmtLst(state.armc) };
    }),
  };
  process.stdout.write(JSON.stringify(out));
});
"""


def run_script(cusps: list, scenes: list, describes: list | None = None) -> dict:
    """The article script's own answers: cusps and site statuses for (system,
    latitude, ARMC) triples, the static markup of scene states, and the screen
    reader summary for (system, latitude, ARMC) triples."""
    return sphere_node(_NODE_SCRIPT, {"cusps": cusps, "scenes": scenes, "describes": describes or []})


def sphere_node(script: str, job: object = None) -> dict:
    """A Node program run with house-sphere-core.js and house-sphere.js as its
    first two arguments (and `job` as JSON on stdin)."""
    return node_json(script, SCRIPTS / "house-sphere-core.js", SCRIPTS / "house-sphere.js", stdin=job,
                     timeout=120, what="run the house-sphere script")


def swiss_cusps(swe, sys: str, lat: float, armc: float, obliquity: float) -> list[float] | None:
    """Swiss Ephemeris houses_armc, or None where it refuses (Placidus in the polar band)."""
    try:
        cusps, _ = swe.houses_armc(armc, lat, obliquity, sys.encode())
    except swe.Error:
        return None
    return list(cusps)


def arcsec(a: float, b: float) -> float:
    return abs((a - b + 540.0) % 360.0 - 180.0) * 3600.0


def grid_cells() -> list[tuple[str, float, float]]:
    return [(s, lat, armc) for lat in GRID_LATITUDES for armc in GRID_ARMCS for s in SYSTEMS]


def compare(cells, script: list[dict], swiss_answers: list) -> dict:
    """Cusp by cusp, the script against Swiss.  Both must refuse the same cells."""
    compared, worst = 0, 0.0
    disagreements: list[tuple] = []
    for cell, mine, theirs in zip(cells, script, swiss_answers, strict=True):
        if (mine["cusps"] is None) != (theirs is None):
            disagreements.append((cell, "only one side refuses"))
            continue
        if theirs is None:
            continue
        for got, want in zip(mine["cusps"], theirs, strict=True):
            difference = arcsec(got, want)
            compared += 1
            worst = max(worst, difference)
            if difference >= TOLERANCE_ARCSEC:
                disagreements.append((cell, difference))
    return {"compared": compared, "worst": worst, "disagreements": disagreements}


def oracle_grid() -> dict:
    """The script on the whole grid against Swiss Ephemeris."""
    cells = grid_cells()
    script = run_script([list(c) for c in cells], [])
    with swiss() as swe:
        theirs = [swiss_cusps(swe, s, lat, armc, script["obliquity"]) for s, lat, armc in cells]
    result = compare(cells, script["cusps"], theirs)
    result["cells"] = cells
    result["script"] = script["cusps"]
    result["swiss"] = theirs
    result["obliquity"] = script["obliquity"]
    return result


def _cell(lon: float) -> str:
    total = round(lon * 60) % (360 * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]} {rest // 60}°{rest % 60:02d}′"


def _table(cusps: dict[str, list[float]]) -> str:
    rows = []
    for i in range(12):
        cells = "".join(f'<td class="n">{_cell(cusps[s][i])}</td>' for s in SYSTEMS)
        rows.append(f'          <tr><td class="n">{i + 1}</td>{cells}</tr>')
    return "\n".join(rows)


def _spread(cusps: dict[str, list[float]], house: int, systems: str) -> tuple[str, str, float]:
    """The earliest and latest cusp of one house among some systems, and the
    arc between them (degrees)."""
    values = [cusps[s][house - 1] for s in systems]
    base = values[0]
    offsets = sorted(((v - base + 180.0) % 360.0 - 180.0, v) for v in values)
    return _cell(offsets[0][1]), _cell(offsets[-1][1]), offsets[-1][0] - offsets[0][0]


# Where the script places the sphere in each drawing (viewBox units).
WIDE_H = 600.0
FRAMES = {
    "fx-wide": {"cx": 290.0, "cy": 304.0, "radius": 222.0, "lift": 6.0, "signs": True},
    "fx-narrow": {"cx": 170.0, "cy": 256.0, "radius": 122.0, "lift": 5.0, "signs": False},
}
# The key to the lines: (class of the sample line, words).  Every plate has the
# circles and the ecliptic; each system adds its own construction.
KEY_COMMON = (("hs-hor", "地平（下半球打點）"), ("hs-mer", "子午圈"), ("hs-equ", "天赤道"), ("hs-pv", "卯酉圈"),
              ("hs-ecl hs-ecl-a", "黃道：每宮一段"), ("hs-mer hs-back", "背面：淡虛線"))
KEY_SYSTEM = {
    "W": (("hs-cut hs-cut-faint", "細線：經過北黃極的宮界"),),
    "E": (("hs-cut hs-cut-faint", "細線：經過北黃極的宮界"),),
    "O": (("hs-cut hs-cut-faint", "細線：經過北黃極的宮界"),),
    "C": (("hs-pv hs-strong", "粗：被切的卯酉圈"), ("hs-cut", "細線：過地平南北兩點的大圓")),
    "R": (("hs-equ hs-strong", "粗：被切的天赤道"), ("hs-cut", "細線：過地平南北兩點的大圓")),
    "B": (("hs-day", "上升點的周日圈"), ("hs-arc", "粗虛線：被三等分的半日弧"),
          ("hs-cut", "細線：通過北天極的時圈")),
    "P": (("hs-arc hs-arc-thin", "粗虛線：各宮頭被三分的半弧"), ("hs-cut", "細線：三分點連成的曲線")),
}
KEY_POLAR = (("hs-none", "排線：整天不升或不落的黃道段"),)
# The captions: the article's own sentences (colour words replaced by the line
# each names in direction 甲).
CAPTIONS = {
    "sphere-w": "整宮。黃道上深淺交替的每一段是一宮，段旁的數字是宮號，黑點是宮頭；這裡每一個宮頭都在星座的 0 度。",
    "sphere-e": "等分宮。和圖 2 一樣是 30 度一宮，只是整組往前移到上升點的度數。",
    "sphere-o": "Porphyry。第 1、4、7、10 宮頭就是四個軸點；中間的宮頭把每一段黃道平分成三份。",
    "sphere-c": "Campanus。加粗的是卯酉圈，細黑線是通過地平南北兩點的大圓。",
    "sphere-r": "Regiomontanus。加粗的是天赤道，細黑線同樣是通過地平南北兩點的大圓。",
    "sphere-b": "Alcabitius。細黑線是通過北天極的時圈，它們把上升點周日圈上的分點帶到黃道上。",
    "sphere-p": "Placidus。細黑線是「半弧走了三分之一」與「三分之二」的點連成的曲線；它們不經過天極，也不經過地平南北兩點。",
    "sphere-polar-p": f"北緯 {POLAR_LAT}°（挪威特羅姆瑟）的 Placidus。交叉排線的粗帶是整天不升或不落的黃道段，那些度數沒有半弧；"
                      "本站在這裡不給 Placidus 的宮頭。",
    "sphere-mc-below": f"北緯 {POLAR_LAT}°、地方恆星時 {round(MC_BELOW_ARMC / 15)} 時 00 分的 Regiomontanus。中天沉到地平線下；照 Swiss Ephemeris 的定義，"
                       "第十宮頭改用地平線上方的天底，宮號因此繞反方向。本站在這種情形不算這種宮位制，可以改用整宮或等分宮。",
}
FIGURE_NUMBERS = {name: n for n, name in enumerate(CAPTIONS, start=2)}


def _bind(text: str, bound: _fx.Bound) -> str:
    """A ratified sentence of the script or the article, its numbers registered
    as labels: they name the sky drawn (inputs), a figure, or a fixed step."""
    bound.label(text)
    return text


def _wrap(text: str, limit: float) -> list[str]:
    """Split at 「，」 or 「：」 so each line stays under `limit` em (a Latin
    letter counts half)."""
    def width(part: str) -> float:
        return sum(0.55 if ch.isascii() else 1.0 for ch in part)
    lines, line = [], ""
    parts: list[str] = []
    buffer = ""
    for ch in text:
        buffer += ch
        if ch in "，：":
            parts.append(buffer)
            buffer = ""
    if buffer:
        parts.append(buffer)
    for part in parts:
        if line and width(line + part) > limit:
            lines.append(line)
            line = part
        else:
            line += part
    if line:
        lines.append(line)
    return lines


def _plate(layout: str, name: str, sys: str, scene: str, status: dict, sizes: list[float] | None,
           bound: _fx.Bound, script: dict) -> str:
    """One layout of one static figure: the script's sphere and the plate around it."""
    fid = f"fig-{name}"
    wide = layout == "fx-wide"
    W = _fx.WIDE if wide else _fx.NARROW
    keys = KEY_COMMON + (KEY_POLAR if sizes is None and sys == "P" else KEY_SYSTEM[sys])
    refused = status["state"] == "unavailable"
    sky = _bind(f"{script['fmt_lat'][name]}｜恆星時 {script['fmt_lst'][name]}", bound)
    head, explain = script["captions"][sys]
    small = "fx-t fx-small"
    out: list[str] = []
    if wide:
        x, y = 590.0, 40.0
        out.append(_fx.text(x, y, script["flag"], "fx-t hs-tx-b"))
        y += 30
        out.append(_fx.text(x, y, script["names"][sys], "fx-t"))
        for line in _wrap(_bind(head, bound), 17.5):
            y += 22
            out.append(_fx.text(x, y, line, small))
        y += 26
        out.append(_fx.text(x, y, sky, small + " fx-num"))
        if refused:
            y += 22
            out.append(_fx.text(x, y, "本站在這種情形不算這種宮位制", "fx-t fx-small hs-tx-b"))
        y += 18
        for cls, words in keys:
            y += 24
            out.append(f'<g class="hs-svg hs-plate">{_fx.line(x, y - 5, x + 30, y - 5, cls)}</g>'
                       + _fx.text(x + 40, y, _bind(words, bound), small))
        y += 36
        H = WIDE_H
    else:
        x, y = 14.0, 30.0
        out.append(_fx.text(x, y, script["flag"], "fx-t hs-tx-b"))
        y += 22
        out.append(_fx.text(x, y, f"{script['names'][sys]}：{_bind(head, bound)}", small))
        y += 20
        out.append(_fx.text(x, y, sky, small + " fx-num"))
        if refused:
            y += 20
            out.append(_fx.text(x, y, "本站在這種情形不算這種宮位制", "fx-t fx-small hs-tx-b"))
        if y > FRAMES[layout]["cy"] - FRAMES[layout]["radius"] - 40:
            raise RuntimeError(f"{fid}: the phone header runs into the sphere")
        y = FRAMES[layout]["cy"] + FRAMES[layout]["radius"] + 40
        common, own = keys[:len(KEY_COMMON)], keys[len(KEY_COMMON):]
        for i, (cls, words) in enumerate(common):
            cx = x + (i % 2) * 160
            yy = y + (i // 2) * 20
            out.append(f'<g class="hs-svg hs-plate">{_fx.line(cx, yy - 4, cx + 24, yy - 4, cls)}</g>'
                       + _fx.text(cx + 32, yy, _bind(words, bound), small))
        y += 20 * ((len(common) + 1) // 2)
        for cls, words in own:
            out.append(f'<g class="hs-svg hs-plate">{_fx.line(x, y - 4, x + 24, y - 4, cls)}</g>'
                       + _fx.text(x + 32, y, _bind(words, bound), small))
            y += 20
        y += 10
        H = 0.0
    # each house's size, or why there is none
    if sizes is None:
        out.append(_fx.text(x, y, "這裡沒有解，不給宮頭。", small))
        y += 10
    elif refused:
        out.append(_fx.text(x, y, "宮頭照畫，宮號繞反方向。", small))
        y += 10
    else:
        out.append(_fx.text(x, y, "每一宮的大小（沿黃道）", small))
        columns, step, row = (2, 136.0, 21.0) if wide else (3, 106.0, 19.0)
        for i, size in enumerate(sizes):
            cx = x + (i // (12 // columns)) * step
            cy = y + 22 + (i % (12 // columns)) * row
            out.append(_fx.text(cx, cy, f"第 {bound.scale(str(i + 1))} 宮 {bound.num(f'{size:.1f}')}°", small + " fx-num"))
        y += 22 + (12 // columns - 1) * row + 6
    if wide and y > H - 12:
        raise RuntimeError(f"{fid}: the side panel outgrew the plate ({y})")
    if not wide:
        H = y + 14
    return (_fx.svg_open(layout, W, H, fid) + _fx.plate(W, H)
            + re.sub(r">\s+<", "><", scene) + "".join(out) + "</svg>")


def _static_figure(name: str, sys: str, scenes: dict, status: dict,
                   swiss_cusps_: list[float] | None, script: dict) -> str:
    bound = _fx.Bound()
    fid = f"fig-{name}"
    sizes = None
    if swiss_cusps_ is not None:
        sizes = [(swiss_cusps_[(i + 1) % 12] - swiss_cusps_[i]) % 360.0 for i in range(12)]
    for n in range(1, 13):
        bound.scale(str(n))  # the house numbers along the ecliptic
    caption = _bind(CAPTIONS[name], bound)
    number = bound.label(f"圖 {FIGURE_NUMBERS[name]}")
    return _fx.figure(
        fid=fid,
        title=script["describe"][name],
        caption=f"<b>{number}</b>{escape(caption)}",
        art=_fx.FigureArt(
            wide=_plate("fx-wide", name, sys, scenes["fx-wide"], status, sizes, bound, script),
            narrow=_plate("fx-narrow", name, sys, scenes["fx-narrow"], status, sizes, bound, script),
            notes=[],
            idle="",
        ),
        bound=bound,
    )


def build() -> tuple[dict[str, str], list[str]]:
    first = run_script([], [])
    start, view = first["start"], first["view"]
    drawn = figures(start)
    states = [{"sys": s, "lat": lat, "armc": armc, "inside": False, **view} for s, lat, armc in drawn.values()]
    jobs = [{"state": state, "frame": FRAMES[layout]} for state in states for layout in FRAMES]
    script = run_script([list(cell) for cell in drawn.values()], jobs)
    reference: dict[str, list[float]] = {}
    with swiss() as swe:
        for s in SYSTEMS:
            cusps = swiss_cusps(swe, s, start["lat"], start["armc"], script["obliquity"])
            if cusps is None:
                raise RuntimeError(f"Swiss Ephemeris refuses {s} on the article's sky")
            reference[s] = cusps
        for (s, lat, armc), mine in zip(drawn.values(), script["cusps"], strict=True):
            theirs = swiss_cusps(swe, s, lat, armc, script["obliquity"])
            if (theirs is None) != (mine["cusps"] is None) or (
                    theirs is not None and max(map(arcsec, mine["cusps"], theirs)) >= TOLERANCE_ARCSEC):
                raise RuntimeError(f"the figure script's {s} cusps at {lat}°, {armc}° differ from Swiss Ephemeris")
    statuses = {name: answer["status"] for name, answer in zip(drawn, script["cusps"], strict=True)}
    # The prose explains these two refusals; a changed rule must fail here.
    if statuses["sphere-polar-p"]["reason"] != "placidus_no_semiarc" or \
            statuses["sphere-mc-below"]["reason"] != "degenerate_cusp_cycle_rejected" or \
            any(statuses[f"sphere-{s.lower()}"]["state"] != "available" for s in SYSTEMS):
        raise RuntimeError(f"the figures' site statuses changed: {statuses}")
    blocks: dict[str, str] = {}
    for i, (name, (s, lat, armc)) in enumerate(drawn.items()):
        scenes = {layout: script["scenes"][len(FRAMES) * i + j] for j, layout in enumerate(FRAMES)}
        texts = script["texts"][len(FRAMES) * i]
        with swiss() as swe:
            theirs = swiss_cusps(swe, s, lat, armc, script["obliquity"])
        meta = {"flag": script["flag"], "names": script["names"], "captions": script["captions"],
                "fmt_lat": {name: texts["lat"]}, "fmt_lst": {name: texts["lst"]}, "describe": {name: texts["describe"]}}
        blocks[name] = _static_figure(name, s, scenes, statuses[name], theirs, meta)
    blocks["fx-defs"] = _fx.defs(())
    blocks["cusps"] = _table(reference)

    grid = oracle_grid()
    if grid["disagreements"]:
        raise RuntimeError(f"the figure script disagrees with Swiss Ephemeris: {grid['disagreements'][:5]}")

    asc, mc = reference["O"][0], reference["O"][9]
    eleven_low, eleven_high, eleven_arc = _spread(reference, 11, "OBCRP")
    with swiss() as swe:
        version = swe.version
    minutes = round(start["armc"] * 4) % 1440
    sky = f"緯度 {start['lat']}°、地方恆星時 {minutes // 60} 時 {minutes % 60:02d} 分"
    quoted = [
        sky,
        f"緯度 {start['lat']}°（臺北的緯度），地方恆星時 {minutes // 60} 時 {minutes % 60:02d} 分",
        f"ARMC {start['armc']:g}°",
        f"上升點在{_cell(asc)}，中天在{_cell(mc)}",
        f"第十宮頭在{_cell(reference['E'][9])}，中天卻在{_cell(mc)}",
        f"從{eleven_low}到{eleven_high}，相差 {eleven_arc:.1f} 度",
        f"Swiss Ephemeris {version} 的 houses_armc",
        f"共 {grid['compared']:,} 個宮頭",
        f"黃赤交角固定為 {script['obliquity']}°",
    ]
    return blocks, quoted
