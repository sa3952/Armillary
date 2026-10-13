"""〈整宮制與 Placidus〉: figure 1 (the house divisions on one wheel, with a
switch among the overlay of whole-sign and Placidus and each of the four
systems alone), the placement and cusp tables, figure 2 (the two divisions
on the celestial sphere, drawn by the house-system article's own sphere
script), figure 3 (the polar band) and the polar status table's states.

Every chart number is the product's own answer: the requests go to the real
application in process, as the chart fixtures do.  Synthetic instants only:
1990-05-15 11:00 Taipei, and the same date 12:00 at Tromsø for the polar case.
The drawn house of each body is re-read from the drawn cusps and must agree
with the product's placement.  Figure 2 is generic geometry (a latitude and a
local sidereal time, no date or place of birth); its cusps are compared with
Swiss Ephemeris here.
"""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess

from . import _fx, house_sphere
from ._common import ROOT, SIGNS, backend_on_path, spoken_longitude as _spoken, swiss


FRAGMENT = "blog-whole-sign-vs-placidus"
SYSTEMS = "WPRB"
ORDER = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
NAMES = {"sun": "太陽", "moon": "月亮", "mercury": "水星", "venus": "金星", "mars": "火星", "jupiter": "木星",
         "saturn": "土星"}
COUNT = "零一二三四五六七"
# The polar status table (表 4) as the article states it.
POLAR_STATES = {"W": "available_polar_geometry", "P": "placidus_no_semiarc", "R": "unstable", "B": "unstable"}
SYSTEM_NAMES = {"W": "整宮制", "P": "Placidus", "R": "Regiomontanus", "B": "Alcabitius"}
SHORT = {"W": "整宮", "P": "Placidus", "R": "Regiomontanus", "B": "Alcabitius"}
# Figure 1's switch: the overlay the article is about first, then each system alone.
VARIANTS = (("both", "整宮＋Placidus"), ("whole", "整宮制"), ("placidus", "Placidus"),
            ("regio", "Regiomontanus"), ("alcab", "Alcabitius"))
QUADRANT = {"both": "P", "whole": None, "placidus": "P", "regio": "R", "alcab": "B"}
SWITCH_LABEL = "切換宮位制"
IDLE = "用 Tab 鍵移到一顆行星上，或用滑鼠指著它，這裡會寫出它的位置與落在第幾宮。"


def _request(system: str, *, polar: bool = False, houses: bool = True) -> dict:
    lat, lon, hour, zone = (69.6496, 18.9560, 12, "Europe/Oslo") if polar else (25.05306, 121.52639, 11,
                                                                                "Asia/Taipei")
    options: dict[str, object] = {"house_system": system}
    if houses:
        options["include_houses"] = True
    return {"birth_time_precision": "exact",
            "datetime": {"year": 1990, "month": 5, "day": 15, "hour": hour, "minute": 0, "second": 0},
            "location": {"latitude": lat, "longitude": lon, "altitude_m": 10},
            "timezone": {"mode": "iana", "iana_name": zone},
            "options": options}


def _data() -> dict:
    with backend_on_path():
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        def post(payload: dict, expected: int = 200) -> dict:
            response = client.post("/api/chart", json=payload)
            if response.status_code != expected:
                raise RuntimeError(f"chart request answered {response.status_code}: {response.text[:300]}")
            return response.json()

        d: dict = {}
        for system in SYSTEMS:
            body = post(_request(system))
            division = body["derived_methods"]["house_division"]
            d[system] = {
                "cusps": division["cusps"],
                "placements": [(p["key"], p["house"]) for p in body["derived_methods"]["planet_in_house"]["placements"]],
                "angles": body["astronomical_data"]["angles"]["sign_positions"],
            }
        body = post(_request("P", houses=False))
        d["bodies"] = {b["key"]: [b["sign_position"][0], b["sign_position"][1], float(b["sign_position"][2])]
                       for b in body["astronomical_data"]["bodies"]}
        polar = {}
        for system in SYSTEMS:
            if system == "P":
                refusal = post(_request(system, polar=True), expected=422)["detail"]
                polar[system] = refusal["reason_code"]
                d["polar_reason"] = refusal["geometric_reason"]
            else:
                answer = post(_request(system, polar=True))
                polar[system] = answer["derived_methods"]["house_division"]["availability"]["state"]
                d["polar_obliquity"] = answer["astronomical_data"]["time"]["true_obliquity"]
        if polar != POLAR_STATES:
            raise RuntimeError(f"polar house states changed: {polar}")
    return d


def _written(lon: float) -> str:
    total = round(lon * 60)
    sign, rest = divmod(total, 30 * 60)
    return f"{SIGNS[sign]}座 {rest // 60}°{rest % 60:02d}′"


def _cell(lon: float) -> str:
    k = int(lon // 30)
    x = lon - 30 * k
    dd = int(x)
    mm = int(round((x - dd) * 60))
    if mm == 60:
        dd, mm = dd + 1, 0
    return f"{SIGNS[k]} {dd}°{mm:02d}′"


def _position(d: dict, key: str) -> str:
    """A body's place as table 2 prints it (whole minutes, not rounded), with 座."""
    sign, dms, _ = d["bodies"][key]
    return f"{SIGNS[sign]}座 {dms[:dms.index('′') + 1]}"


def _cusp_text(lon: float) -> str:
    """A cusp as table 3 prints it, with 座."""
    sign, rest = _cell(lon).split(" ")
    return f"{sign}座 {rest}"


# --- figure 1: the wheel ------------------------------------------------------

def _house_of(cusps: list[float], lon: float) -> int:
    """The house a longitude falls in between the drawn cusps (a cusp opens its house)."""
    for i, start in enumerate(cusps):
        span = (cusps[(i + 1) % 12] - start) % 360
        if (lon - start) % 360 < span:
            return i + 1
    raise RuntimeError(f"no house holds {lon}")


def _check_drawn_houses(d: dict) -> None:
    """Each body's house, read from the cusps the wheel draws, is the product's placement."""
    for system in SYSTEMS:
        placements = dict(d[system]["placements"])
        cusps = d[system]["cusps"]
        for key in ORDER:
            drawn = _house_of(cusps, d["bodies"][key][2])
            if drawn != placements[key]:
                raise RuntimeError(f"{system} {key}: drawn in house {drawn}, the product says {placements[key]}")


def _width(value: str, size: float) -> float:
    """A generous estimate of a label's drawn width: a CJK character is one em,
    anything else 0.55 em."""
    return sum(size if ord(ch) > 0x2E7F else 0.55 * size for ch in value)


_TEXT = re.compile(r'<text x="([-0-9.]+)" y="([-0-9.]+)" class="([^"]+)"(?: text-anchor="(\w+)")?>([^<]*)</text>')


def _inside_plate(markup: str, layout: str, width: float, height: float) -> None:
    """Every label of a drawing lies inside its plate (the old wheel cut 「上升」 off at 375 px)."""
    sizes = _fx.text_sizes()
    for x, y, cls, anchor, value in _TEXT.findall(markup):
        size = sizes[(layout, "fx-small" if "fx-small" in cls.split() else "fx-t")]
        w = _width(value.replace("&amp;", "&"), size)
        left = float(x) - {"middle": w / 2, "end": w}.get(anchor, 0.0)
        if left < 6 or left + w > width - 6 or float(y) - size < 6 or float(y) > height - 6:
            raise RuntimeError(f"{layout}: the label {value!r} runs past the plate")


def _geometry(layout: str) -> dict:
    if layout == "fx-wide":
        return {"W": _fx.WIDE, "H": 600.0, "cx": 306.0, "cy": 304.0, "R0": 250.0, "R1": 214.0, "R2": 184.0,
                "hub": 60.0, "qnum": 78.0, "orbits": (150.0, 118.0), "mark": 11.0, "glyph": 14.0, "pad": 9.0}
    return {"W": _fx.NARROW, "H": 616.0, "cx": 170.0, "cy": 172.0, "R0": 130.0, "R1": 110.0, "R2": 92.0,
            "hub": 25.0, "qnum": 37.0, "orbits": (78.0, 56.0), "mark": 9.0, "glyph": 11.5, "pad": 7.0}


def _placed(d: dict, g: dict, pt) -> dict[str, tuple[float, float]]:
    """Each body's mark: at its longitude on the outer orbit, or the inner one
    when that would touch a mark already placed."""
    placed: dict[str, tuple[float, float]] = {}
    for key, (_, _, lon) in sorted(d["bodies"].items(), key=lambda kv: kv[1][2]):
        if key not in ORDER:
            continue
        for r in g["orbits"]:
            x, y = pt(lon, r)
            if all(math.hypot(x - a, y - b) >= 2 * g["mark"] + 3 for a, b in placed.values()):
                break
        else:
            raise RuntimeError(f"no room for {key} on the wheel")
        placed[key] = (x, y)
    return placed


def _mark(key: str, x: float, y: float, g: dict, solid: bool) -> str:
    disc, gl = ("fx-mk-on", "fx-mk-gl-on") if solid else ("fx-mk", "fx-mk-gl")
    return _fx.circle(x, y, g["mark"], disc) + _fx.glyph(key, x, y, g["glyph"], gl)


def _houses_text(variant: str, w: int, q: int | None, bound: _fx.Bound) -> str:
    system = QUADRANT[variant]
    whole = f"整宮 {bound.num(str(w))}"
    if system is None:
        return whole
    quadrant = f"{SHORT[system]} {bound.num(str(q))}"
    return f"{whole}・{quadrant}" if variant == "both" else f"{quadrant}・{whole}"


def _wheel(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    g = _geometry(layout)
    wide = layout == "fx-wide"
    W, H, cx, cy = g["W"], g["H"], g["cx"], g["cy"]
    R0, R1, R2, hub = g["R0"], g["R1"], g["R2"], g["hub"]
    asc = float(d["W"]["angles"]["asc"][2])
    mc = float(d["W"]["angles"]["mc"][2])

    def pt(lon: float, r: float) -> tuple[float, float]:
        a = math.radians(180 + (lon - asc))
        return cx + r * math.cos(a), cy - r * math.sin(a)

    def ray(lon: float, r0: float, r1: float, cls: str) -> str:
        (x0, y0), (x1, y1) = pt(lon, r0), pt(lon, r1)
        return _fx.line(x0, y0, x1, y1, cls)

    houses = {s: dict(d[s]["placements"]) for s in SYSTEMS}
    small = "fx-t fx-small"
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.circle(cx, cy, R0, "fx-wh-ring"))
    # the signs: names in the outer ring, their boundaries across it
    for k in range(12):
        x, y = pt(30 * k + 15, (R0 + R1) / 2)
        out.append(_fx.text(x, y + (5 if wide else 4), SIGNS[k], small + " fx-dim", "middle"))
        out.append(ray(30 * k, R1, R0, "fx-axis"))
    out.append(_fx.circle(cx, cy, R1, "fx-wh-line"))
    out.append(_fx.circle(cx, cy, R2, "fx-wh-line"))
    first_sign = int(asc // 30)
    variants = []
    for variant, _ in VARIANTS:
        body = []
        system = QUADRANT[variant]
        if variant in ("both", "whole"):
            # whole-sign houses: the sign boundaries are the house boundaries
            for k in range(12):
                x, y = pt(30 * k + 15, (R1 + R2) / 2)
                body.append(_fx.text(x, y + (5 if wide else 4), bound.label(str((k - first_sign) % 12 + 1)),
                                     small + " fx-num", "middle"))
                body.append(ray(30 * k, R2, R1, "fx-axis"))
                if variant == "whole":
                    body.append(ray(30 * k, hub, R2, "fx-wh-whole"))
        if system:
            cusps = d[system]["cusps"]
            for i, c in enumerate(cusps):
                if i % 3:
                    body.append(ray(c, hub, R2, "fx-wh-cusp"))
                mid = c + ((cusps[(i + 1) % 12] - c) % 360) / 2
                x, y = pt(mid, g["qnum"])
                body.append(_fx.text(x, y + (5 if wide else 4), bound.label(str(i + 1)), small + " fx-num", "middle"))
        variants.append(_fx.variant_group(variant, VARIANTS[0][0], "".join(body)))
    out += variants
    # the axes: the quadrant systems' cusps 1, 4, 7 and 10; whole-sign houses do not start there
    for lon in (asc, mc):
        out.append(ray(lon, hub, R2, "fx-wh-axis") + ray(lon + 180, hub, R2, "fx-wh-axis"))
    out.append(_fx.circle(cx, cy, hub, "fx-wh-hub"))
    if wide:
        for variant, _ in VARIANTS:
            system = QUADRANT[variant]
            label = ""
            if system:
                label = (_fx.text(cx, cy - 2, SHORT[system], small, "middle")
                         + _fx.text(cx, cy + 18, "宮號", small + " fx-dim", "middle"))
            out.append(_fx.variant_group(variant, VARIANTS[0][0], label))
    ax, ay = pt(asc, R0)
    out.append(_fx.line(ax, ay, 8, ay, "fx-wh-axis"))
    tick = 14 if wide else 10
    out.append(ray(asc + 180, R0, R0 + tick, "fx-wh-axis") + ray(mc + 180, R0, R0 + tick, "fx-wh-axis"))
    out.append(_fx.text(10, ay - 7, "上升", "fx-t", None))
    mx, my = pt(mc, R0 + (30 if wide else 22))
    out.append(_fx.text(mx, my, "中天", "fx-t", "middle"))
    out.append(ray(mc, R0, R0 + tick, "fx-wh-axis"))

    # the bodies: on the wheel, and listed with their houses
    marks = _placed(d, g, pt)
    if wide:
        lx, ly, row = 590.0, 74.0, 50.0
        out.append(_fx.text(lx, 42, "各行星落在第幾宮", "fx-t"))
    else:
        lx, ly, row = 14.0, 350.0, 26.0
        out.append(_fx.text(lx, 330, "各行星落在第幾宮", "fx-t"))
    for i, key in enumerate(ORDER):
        lon = d["bodies"][key][2]
        w = houses["W"][key]
        position = bound.num(_position(d, key))
        top = ly + i * row
        out.append(f'<g class="fx-row" data-fx-key="{key}" tabindex="0" aria-label="{NAMES[key]}，{position}">')
        out.append(_fx.rect(lx - 6, top - 2, W - lx - 8, row - 4, "fx-hit"))
        mx, my = marks[key]
        out.append(_fx.circle(mx, my, g["mark"] + 6, "fx-hit"))
        out.append(ray(lon, R2 - (8 if wide else 6), R2, "fx-axis"))
        tx, ty = pt(lon, R2 - (8 if wide else 6))
        out.append(_fx.line(tx, ty, mx, my, "fx-hair"))
        rx, ry = lx + g["mark"] + 2, top + row / 2 - (8 if wide else 2)
        # the open mark under every system; a solid one drawn over it where this system moves the planet
        body = [_mark(key, mx, my, g, False) + _mark(key, rx, ry, g, False)]
        for variant, _ in VARIANTS:
            system = QUADRANT[variant]
            q = houses[system][key] if system else None
            moved = system is not None and q != w
            drawn = _mark(key, mx, my, g, True) + _mark(key, rx, ry, g, True) if moved else ""
            label = _houses_text(variant, w, q, bound)
            if wide:
                drawn += _fx.text(lx + 2 * g["mark"] + 14, top + row - 8, label, small + " fx-num")
            else:
                drawn += _fx.text(150, ry + 4, label, small + " fx-num")
            body.append(_fx.variant_group(variant, VARIANTS[0][0], drawn))
        out += body
        name_x = lx + 2 * g["mark"] + (14 if wide else 8)
        out.append(_fx.text(name_x, ry + (6 if wide else 5), NAMES[key], "fx-t fx-name"))
        out.append(_fx.text(name_x + (44 if wide else 32), ry + (6 if wide else 5), position, small + " fx-num"))
        out.append("</g>")
    # how to read the lines, next to the list
    ky = ly + len(ORDER) * row + (22 if wide else 18)
    sample = 34 if wide else 26
    out.append(_fx.line(lx, ky - 5, lx + sample, ky - 5, "fx-wh-whole")
               + _fx.text(lx + sample + 8, ky, "實線：整宮制的宮界，就是星座交界", small))
    for variant, _ in VARIANTS:
        system = QUADRANT[variant]
        lines = ""
        if system:
            lines = (_fx.line(lx, ky + 19, lx + sample, ky + 19, "fx-wh-cusp")
                     + _fx.text(lx + sample + 8, ky + 24, f"虛線：{SYSTEM_NAMES[system]} 的宮頭", small)
                     + _fx.circle(lx + sample / 2, ky + 44, g["mark"] - 3, "fx-mk-on")
                     + _fx.text(lx + sample + 8, ky + 49, "實心：與整宮制落在不同的宮", small))
        out.append(_fx.variant_group(variant, VARIANTS[0][0], lines))
    out.append("</svg>")
    markup = "".join(out)
    if ky + 49 > H - 8:
        raise RuntimeError(f"figure 1 {layout} outgrew its drawing")
    _inside_plate(markup, layout, W, H)
    return markup


def _wheel_sentence(d: dict, variant: str, key: str, bound: _fx.Bound) -> str:
    name = NAMES[key]
    lon = d["bodies"][key][2]
    w = dict(d["W"]["placements"])[key]
    text = f"{name}：{bound.num(_position(d, key))}。整宮制：{SIGNS[int(lon // 30)]}座整座是第 {bound.num(str(w))} 宮。"
    system = QUADRANT[variant]
    if system is None:
        return text
    q = dict(d[system]["placements"])[key]
    cusps = d[system]["cusps"]
    nxt = q % 12 + 1
    text += (f"{SYSTEM_NAMES[system]}：第 {bound.num(str(q))} 宮，在第 {bound.num(str(q))} 宮頭"
             f"（{bound.num(_cusp_text(cusps[q - 1]))}）與第 {bound.num(str(nxt))} 宮頭"
             f"（{bound.num(_cusp_text(cusps[nxt - 1]))}）之間。")
    text += "兩者相同。" if q == w else "兩者不同。"
    return text


def _wheel_figure(d: dict) -> tuple[str, _fx.Bound]:
    bound = _fx.Bound()
    asc = float(d["W"]["angles"]["asc"][2])
    mc = float(d["W"]["angles"]["mc"][2])
    whole, placidus = dict(d["W"]["placements"]), dict(d["P"]["placements"])
    moved = [key for key in ORDER if whole[key] != placidus[key]]
    differences = "；".join(f"{NAMES[key]}在整宮制落第 {whole[key]} 宮、在 Placidus 落第 {placidus[key]} 宮"
                           for key in moved)
    moment = _request("W")["datetime"]
    when = bound.num(f"{moment['year']} 年 {moment['month']} 月 {moment['day']} 日上午 {moment['hour']} 點")
    notes = [_fx.Note(key, variant, _wheel_sentence(d, variant, key, bound)) for variant, _ in VARIANTS for key in ORDER]
    html = _fx.figure(
        fid="fig-wheel", hero=True,
        title=(f"同一張合成星盤的分宮：外圈是十二星座，也就是整宮制的十二宮；虛線是 Placidus 的宮頭。"
               f"上升點在{_spoken(asc)}，中天在{_spoken(mc)}。{differences}；"
               f"其餘{COUNT[len(ORDER) - len(moved)]}顆兩制相同。按鈕可以換成只看一種宮位制。"),
        caption=(f"<b>{bound.label('圖 1')}</b>同一張合成星盤（{when}，臺北），兩種分宮疊在一起。外圈是十二星座；"
                 f"實線是整宮制的宮界，也就是星座交界，緊貼在內的數字是整宮制的宮號；虛線是 Placidus 的宮頭，"
                 f"中間一圈數字是 Placidus 的宮號。實心的{'、'.join(NAMES[key] for key in moved)}在兩種宮位制裡"
                 f"落在不同的宮。按鈕可以只看整宮制，或換成 Placidus、Regiomontanus、Alcabitius；"
                 f"各宮頭的度數見{bound.label('表 3')}。"),
        wide=_wheel("fx-wide", "fig-wheel", d, bound),
        narrow=_wheel("fx-narrow", "fig-wheel", d, bound),
        notes=notes, idle=IDLE, variants=VARIANTS, switch_label=SWITCH_LABEL,
    )
    return html, bound


# --- figure 2: the sphere -----------------------------------------------------

_SPHERE_SCRIPT = r"""
const Core = require(process.argv[1]);
const Sphere = require(process.argv[2]);
const out = { flag: Sphere.FLAG, start: Sphere.START, obliquity: Core.OBLIQUITY, panels: [] };
for (const sys of ["W", "P"]) {
  const state = { sys, lat: Sphere.START.lat, armc: Sphere.START.armc, inside: false, ...Sphere.DEFAULT_VIEW };
  out.panels.push({ sys, scene: Sphere.scene(state), cusps: Core.cusps(sys, state.lat, state.armc, Core.OBLIQUITY).cusps });
}
process.stdout.write(JSON.stringify(out));
"""
# The scene's own 640-unit drawing, cropped to the sphere and its labels.
SPHERE_CROP = (20.0, 95.0, 620.0, 605.0)
# The sphere script's roles, drawn in the engraved-plate style.
SPHERE_ROLES = (
    ("hs-ball", "fx-sph-ball"), ("hs-ground", "fx-sph-ground"), ("hs-hor", "fx-sph-hor"),
    ("hs-strong", "fx-sph-line"), ("hs-mer", "fx-sph-faint"), ("hs-equ", "fx-sph-faint"),
    ("hs-pv", "fx-sph-faint"), ("hs-cut-faint", "fx-sph-cut fx-sph-dim"), ("hs-cut", "fx-sph-cut"),
    ("hs-arc", "fx-sph-arc"), ("hs-day", "fx-sph-faint"), ("hs-ecl-a", "fx-sph-ecl"), ("hs-ecl-b", "fx-sph-ecl-b"),
    ("hs-tick", "fx-axis"), ("hs-pt-hor", "fx-sph-pt-open"), ("hs-pt-equ", "fx-sph-pt-open"),
    ("hs-pt-pv", "fx-sph-pt-open"), ("hs-pt-dim", "fx-sph-pt-dim"), ("hs-pt", "fx-sph-pt"),
)


def _sphere_script() -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to draw the house-system sphere")
    scripts = ROOT / "scripts" / "frontend" / "scripts"
    completed = subprocess.run(
        [node, "-e", _SPHERE_SCRIPT, str(scripts / "house-sphere-core.js"), str(scripts / "house-sphere.js")],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError("the house-sphere script failed: " + completed.stderr.strip())
    return json.loads(completed.stdout)


def _role(classes: str) -> str:
    names = classes.split()
    for source, role in SPHERE_ROLES:
        if source in names:
            return role + (" fx-sph-back" if "hs-back" in names else "")
    raise RuntimeError(f"no plate role for the sphere's {classes!r}")


def _label_class(classes: str) -> tuple[str, str]:
    names = classes.split()
    cls = "fx-t" if "hs-t-axis" in names else "fx-t fx-small"
    if "hs-t-num" in names:
        cls += " fx-num"
    if {"hs-t-dim", "hs-t-sign", "hs-t-back"} & set(names):
        cls += " fx-dim"
    return cls, "end" if "hs-t-end" in names else "middle"


def _sphere_panel(scene: dict, layout: str, ox: float, oy: float, s: float, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    size_of = _fx.text_sizes()
    x0, y0 = SPHERE_CROP[:2]
    X = lambda x: ox + (float(x) - x0) * s  # noqa: E731
    Y = lambda y: oy + (float(y) - y0) * s  # noqa: E731
    out: list[str] = []

    def walk(node: dict) -> None:
        tag, a = node["tag"], node["attrs"]
        if tag == "g" and "hs-title" in a.get("class", ""):
            return  # the panel's own heading replaces the script's
        if tag in ("polyline", "polygon"):
            drawn = _simplified([(X(p.split(",")[0]), Y(p.split(",")[1])) for p in a["points"].split()])
            points = " ".join(f"{_fx.f(x)},{_fx.f(y)}" for x, y in drawn)
            out.append(f'<{tag} points="{points}" class="{_role(a["class"])}"/>')
        elif tag == "circle":
            r = float(a["r"]) * s if "hs-ball" in a["class"] else max(float(a["r"]) * s, 2.6)
            out.append(_fx.circle(X(a["cx"]), Y(a["cy"]), r, _role(a["class"])))
        elif tag == "line":
            out.append(_fx.line(X(a["x1"]), Y(a["y1"]), X(a["x2"]), Y(a["y2"]), _role(a["class"])))
        elif tag == "text":
            labels.append((_rank(a["class"]), a, node["text"]))
        for child in node["children"]:
            walk(child)

    labels: list[tuple[int, dict, str]] = []
    walk(scene)
    # The script's labels can touch where the sphere is crowded (the zenith and
    # the ecliptic pole, a house number and a compass point): a label that would
    # overlap one ranked higher moves a line aside, or is left out where no place is free.
    placed: list[tuple[float, float, float, float]] = []
    for _, a, value in sorted(labels, key=lambda item: item[0]):
        cls, anchor = _label_class(a["class"])
        if not wide and "hs-t-sign" in a["class"]:
            continue  # the narrow drawing leaves the sign names out, as the article's own figure does
        size = size_of[(layout, "fx-small" if "fx-small" in cls else "fx-t")]
        w = _width(value, size)
        for dx, dy in ((0, 0), (0, -size), (0, size), (size, 0), (-size, 0)):
            x, y = X(a["x"]) + dx, Y(float(a["y"]) - 2) + dy
            left = x - (w if anchor == "end" else w / 2)
            box = (left - 1, y - size, left + w + 1, y + 2)
            if not any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
                break
        else:
            continue
        placed.append(box)
        if any(ch.isdigit() for ch in value):
            value = bound.label(value)
        out.append(_fx.text(x, y, value, cls, anchor))
    return "".join(out)


def _simplified(points: list[tuple[float, float]], tolerance: float = 0.3) -> list[tuple[float, float]]:
    """The points a line needs at this scale (Ramer–Douglas–Peucker): the
    script samples its circles every few degrees, more than a 420-unit panel
    can show; a point within `tolerance` units of the chord is dropped."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    length = math.hypot(x1 - x0, y1 - y0)
    def off(p: tuple[float, float]) -> float:
        if length == 0:
            return math.hypot(p[0] - x0, p[1] - y0)
        return abs((x1 - x0) * (y0 - p[1]) - (x0 - p[0]) * (y1 - y0)) / length
    far = max(range(1, len(points) - 1), key=lambda i: off(points[i]))
    if off(points[far]) <= tolerance:
        return [points[0], points[-1]]
    return _simplified(points[: far + 1], tolerance)[:-1] + _simplified(points[far:], tolerance)


def _rank(classes: str) -> int:
    """Which sphere label keeps its place (others move a line aside, or are left
    out): the axes first, then house numbers, the compass and the zenith, the
    dim ones, the sign names, the far side last."""
    names = set(classes.split())
    if "hs-t-axis" in names:
        return 0
    if "hs-t-back" in names:
        return 5
    if "hs-t-num" in names:
        return 1
    if names & {"hs-t-hor", "hs-t-end"}:
        return 2
    return 4 if "hs-t-sign" in names else 3


def _sphere(layout: str, fid: str, script: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    x0, y0, x1, y1 = SPHERE_CROP
    start = script["start"]
    minutes = round(start["armc"] * 4) % 1440
    sky = bound.num(f"緯度 {start['lat']}°、地方恆星時 {minutes // 60} 時 {minutes % 60:02d} 分")
    if wide:
        W, panel, gap, top = _fx.WIDE, 420.0, 16.0, 78.0
        s = panel / (x1 - x0)
        H = top + (y1 - y0) * s + 16
        origins = [(14.0, top), (14.0 + panel + gap, top)]
    else:
        W, panel, top = _fx.NARROW, 320.0, 64.0
        s = panel / (x1 - x0)
        height = (y1 - y0) * s
        H = top + 2 * height + 46
        origins = [(10.0, top), (10.0, top + height + 30)]
    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.text(16, 32 if wide else 28, script["flag"], "fx-t"))
    out.append(_fx.text(16, 56 if wide else 48, sky, "fx-t fx-small fx-dim"))
    for (ox, oy), item in zip(origins, script["panels"], strict=True):
        head = f"{SYSTEM_NAMES[item['sys']]}"
        out.append(_sphere_panel(item["scene"], layout, ox, oy, s, bound))
        out.append(_fx.text(ox + panel - 8, oy + 18, head, "fx-t", "end"))
    out.append("</svg>")
    markup = "".join(out)
    _inside_plate(markup, layout, W, H)
    return markup


def _sphere_figure() -> tuple[str, _fx.Bound]:
    script = _sphere_script()
    start = script["start"]
    with swiss() as swe:
        for item in script["panels"]:
            theirs = house_sphere.swiss_cusps(swe, item["sys"], start["lat"], start["armc"], script["obliquity"])
            if theirs is None or max(map(house_sphere.arcsec, item["cusps"], theirs)) >= house_sphere.TOLERANCE_ARCSEC:
                raise RuntimeError(f"the sphere script's {item['sys']} cusps differ from Swiss Ephemeris")
            if item["sys"] == "P":
                # Placidus cusps 1 and 10 are the ascendant and the MC of this sky.
                angles = theirs[0], theirs[9]
    bound = _fx.Bound()
    minutes = round(start["armc"] * 4) % 1440
    sky = bound.num(f"緯度 {start['lat']}°、地方恆星時 {minutes // 60} 時 {minutes % 60:02d} 分")
    asc, mc = (bound.num(_written(lon)) for lon in angles)
    html = _fx.figure(
        fid="fig-sphere",
        title="同一片天空在天球上的兩種分宮：一顆畫整宮制，一顆畫 Placidus。教學示意，不是任何人的命盤。",
        caption=(f"<b>{bound.label('圖 2')}</b>同一片天空在天球上的兩種分宮（教學示意：{sky}，"
                 f"這時上升點在{asc}、中天在{mc}；和圖 1 那張合成盤不是同一片天空，也不是任何人的命盤）。"
                 "粗線是黃道，每一宮一段，實線與點線交替，旁邊是宮號；黑點是宮頭；打點的平面是地平面。"
                 "整宮制不切天空，只數星座，所以宮界就是星座交界；Placidus 讓每個宮頭各量自己的半日弧，"
                 "所以宮界在球上是彎的。可以轉動、換緯度、換七種宮位制的天球，在"
                 '〈<a href="/zh-TW/blog/house-systems-explained">宮位制有哪些</a>〉。'),
        wide=_sphere("fx-wide", "fig-sphere", script, bound),
        narrow=_sphere("fx-narrow", "fig-sphere", script, bound),
        notes=[], idle="",
    )
    return html, bound


# --- figure 3: the polar band -------------------------------------------------

def _polar(layout: str, fid: str, d: dict, bound: _fx.Bound) -> str:
    wide = layout == "fx-wide"
    if wide:
        W, H, gx, gy, gr, lx = _fx.WIDE, 300.0, 170.0, 150.0, 122.0, 340.0
    else:
        W, H, gx, gy, gr, lx = _fx.NARROW, 250.0, 84.0, 126.0, 72.0, 166.0
    small = "fx-t fx-small"
    limit = 90.0 - d["polar_obliquity"]
    band = bound.num(f"{limit:.2f}")
    right = bound.scale("90°")
    places = (("臺北", _request("W")["location"]["latitude"], "四種宮位制都可以算"),
              ("特羅姆瑟", _request("W", polar=True)["location"]["latitude"], "在極區帶內"))

    def lat_y(phi: float) -> float:
        return gy - gr * math.sin(math.radians(phi))

    def half(phi: float) -> float:
        return gr * math.cos(math.radians(phi))

    out = [_fx.svg_open(layout, W, H, fid), _fx.plate(W, H)]
    out.append(_fx.circle(gx, gy, gr, "fx-track"))
    for sign in (1, -1):
        yb, hw = lat_y(sign * limit), half(limit)
        out.append(_fx.path(f"M{_fx.f(gx - hw)} {_fx.f(yb)} A{_fx.f(gr)} {_fx.f(gr)} 0 0 {1 if sign == 1 else 0} "
                            f"{_fx.f(gx + hw)} {_fx.f(yb)} Z", "fx-b-beam"))
        out.append(_fx.line(gx - hw, yb, gx + hw, yb, "fx-b-edge"))
    out.append(_fx.line(gx - gr, gy, gx + gr, gy, "fx-hair"))
    out.append(_fx.circle(gx, gy, gr, "fx-axis"))
    out.append(_fx.text(gx, gy - 6, "赤道", small + " fx-dim", "middle"))
    for name, phi, status in places:
        y, x = lat_y(phi), gx + half(phi)
        lat = bound.num(f"{phi:.2f}")
        out.append(_fx.circle(x, y, 5, "fx-wh-dot"))
        out.append(_fx.line(x + 8, y, lx - 8, y, "fx-leader"))
        if wide:
            out.append(_fx.text(lx, y + 6, f"{name}　北緯 {lat}°：{status}", "fx-t"))
        else:
            out.append(_fx.text(lx, y + 4, f"{name}　北緯 {lat}°", small))
            out.append(_fx.text(lx, y + 20, status, small))
    edge = lat_y(limit)
    if wide:
        out.append(_fx.text(lx, edge + 36, f"斜線帶：北緯與南緯 {band}° 以上（{right} − 黃赤交角）", small))
        out.append(_fx.text(lx, lat_y(-40) + 6, "斜線帶內：本站不算 Placidus", "fx-t"))
    else:
        out.append(_fx.text(lx, gy + 22, f"斜線帶：南北緯 {band}° 以上", small))
        out.append(_fx.text(lx, gy + 40, f"（{right} − 黃赤交角）", small))
        out.append(_fx.text(lx, gy + 64, "斜線帶內：本站不算", small))
        out.append(_fx.text(lx, gy + 82, "Placidus", small))
    out.append("</svg>")
    markup = "".join(out)
    _inside_plate(markup, layout, W, H)
    return markup


def _polar_figure(d: dict) -> tuple[str, _fx.Bound]:
    bound = _fx.Bound()
    limit = bound.num(f"{90.0 - d['polar_obliquity']:.2f}")
    tromso = bound.num(f"{_request('W', polar=True)['location']['latitude']:.2f}")
    html = _fx.figure(
        fid="fig-polar",
        title=(f"地球的緯度示意。北緯與南緯 {limit} 度以上的極區帶畫成斜線，本站在帶內整帶拒絕 Placidus；"
               f"臺北遠在帶外，四種宮位制都可以算；挪威特羅姆瑟在北緯 {tromso} 度，位於極區帶內。"),
        caption=(f"<b>{bound.label('圖 3')}</b>極區帶的邊界是 {bound.scale('90')} 度減去命盤時刻的真黃赤交角，目前約 {limit} 度，"
                 f'隨年代緩慢變動<a class="ar-cite" href="#ref-1">[{bound.label("1")}]</a>。臺北遠在帶外；'
                 f"挪威的特羅姆瑟（北緯 {tromso} 度）在帶內。"),
        wide=_polar("fx-wide", "fig-polar", d, bound),
        narrow=_polar("fx-narrow", "fig-polar", d, bound),
        notes=[], idle="",
    )
    return html, bound


# --- tables -------------------------------------------------------------------

def _cusps(d: dict) -> str:
    rows = []
    for i in range(12):
        cells = "".join(f'<td class="n">{_cell(d[hs]["cusps"][i])}</td>' for hs in SYSTEMS)
        rows.append(f'          <tr><td class="n">{i+1}</td>{cells}</tr>')
    return "\n".join(rows)


def _places(d: dict) -> str:
    rows = []
    placements = {hs: dict(d[hs]["placements"]) for hs in SYSTEMS}
    for key in ORDER:
        sign, dms, _ = d["bodies"][key]
        values = [placements[hs][key] for hs in SYSTEMS]
        highlight = ' class="hl"' if len(set(values)) > 1 else ""
        cells = "".join(f'<td class="n{" diff" if v != values[0] else ""}">{v}</td>' for v in values)
        rows.append(f'          <tr{highlight}><td>{NAMES[key]}</td><td class="n">{SIGNS[sign]} '
                    f'{dms[:dms.index("′")+1]}</td>{cells}</tr>')
    return "\n".join(rows)


def _figures(d: dict) -> dict[str, str]:
    """The page's sprite and its three figures, each checked by `_fx.problems`."""
    _check_drawn_houses(d)
    blocks = {}
    for name, (markup, bound) in (("wheel", _wheel_figure(d)), ("sphere", _sphere_figure()),
                                  ("polar-band", _polar_figure(d))):
        found = _fx.problems(markup, bound)
        if found:
            raise RuntimeError("figure check: " + "; ".join(found))
        blocks[name] = markup
    blocks["fx-defs"] = _fx.defs(ORDER)
    return blocks


def build() -> tuple[dict[str, str], list[str]]:
    d = _data()
    asc = float(d["W"]["angles"]["asc"][2])
    mc = float(d["W"]["angles"]["mc"][2])
    reason = d["polar_reason"]
    quoted = [
        f"上升點在{_written(asc)}，中天在{_written(mc)}",
        f"Placidus 的第十二宮頭在{_written(d['P']['cusps'][11])}",
        f"Alcabitius 的在{_written(d['B']['cusps'][8])}",
        "原因代碼 <code>placidus_no_semiarc</code>",
        "1900 到 2399 年間它落在 66.54 到 66.62 度之間",
    ]
    # The article restates the refusal message's band.
    if "1900–2399 年間在 66.54°–66.62° 之間" not in reason:
        raise RuntimeError(f"the Placidus refusal states a different polar band: {reason}")
    return {**_figures(d), "placements": _places(d), "cusps": _cusps(d)}, quoted
