(function attachChartWheelModel(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  const api = factory(
    commonJs ? require("./chart-glyphs.js") : root.ArmillaryChartGlyphs,
    commonJs ? require("./labels.js") : root.ArmillaryLabels,
  );
  if (commonJs) module.exports = api;
  if (root) root.ChartWheelModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildChartWheelModel(Glyphs, Labels) {
  "use strict";

  // 星盤圖的幾何模型：純函式，不碰 DOM。頁面 SVG、下載 SVG、PNG（Canvas）與測試都讀同一份輸出。
  //
  // 圖是表格的可讀投影，與表格同源：
  //   - 位置只讀回應的 sign_position[2]（後端的十進位黃經字串）；
  //   - 度數標籤只切 sign_position[1] 字串（「24°10′30.48″」→「24°」「10′」），不捨入、不重新格式化，
  //     所以每個標籤都是表格「星座度數」儲存格的子字串；星座取 sign_position[0]；
  //   - 宮頭與四軸同樣只讀回應的 sign_position。
  // 這裡不做任何天文或方法計算；唯一的換算是把黃經放到圓上：
  //   圖面角 θ = 180° + (λ − λ上升)，上升在 9 點鐘、黃道逆時針；沒有上升點時以牡羊 0° 置左。
  // 回應缺鍵或字串不合格式的點不畫，不猜；12 個宮頭不齊就整個宮位環不畫。

  const SIGN_KEYS = Object.freeze(Object.keys(Labels.VOCABULARIES.zodiac_sign));
  const SIGN_NAMES = Object.freeze(Object.values(Labels.VOCABULARIES.zodiac_sign));

  // 回應的天體鍵 → 符號鍵；交點兩種都畫（表格兩者分列、不替使用者擇一），以「密／平」區分。
  const POINTS = Object.freeze({
    sun: { glyph: "sun" }, moon: { glyph: "moon" }, mercury: { glyph: "mercury" },
    venus: { glyph: "venus" }, mars: { glyph: "mars" }, jupiter: { glyph: "jupiter" },
    saturn: { glyph: "saturn" }, uranus: { glyph: "uranus" }, neptune: { glyph: "neptune" },
    pluto: { glyph: "pluto" }, chiron: { glyph: "chiron" },
    true_node: { glyph: "north_node", suffix: "密", node: true },
    mean_node: { glyph: "north_node", suffix: "平", node: true },
    true_south_node: { glyph: "south_node", suffix: "密", node: true },
    mean_south_node: { glyph: "south_node", suffix: "平", node: true },
  });
  const ANGLES = Object.freeze([["asc", "ASC"], ["mc", "MC"], ["desc", "DSC"], ["ic", "IC"]]);

  const TEXT = Object.freeze({
    noAngles: "本次沒有軸點，圖以牡羊 0° 置於左方",
    dateOnly: "月亮刻線為虛線：正午錨點，非出生時刻",
    accent: "紅色只標四軸，不表示吉凶",
    noHouses: "本次沒有宮位",
    brand: "渾儀 Armillary",
  });

  // ── 幾何（viewBox 寬 600；圓心 300,300；頁尾在圓下方，高度隨行數）
  const G = Object.freeze({
    width: 600, c: 300,
    rOut: 288, rSignIn: 255, rSignText: 271.5,
    rTickIn: 246,          // 天體刻線：星座環內緣 255 → 246，在真實黃經，不移動
    rLabelTop: 241,        // 標籤堆疊的外緣；引線由刻線內端接到這裡
    gap: 1.5,              // 堆疊元素之間的徑向留白
    rHouseOut: 118, rHouseIn: 90, rHouseText: 104,
    footerTop: 600, footerLine: 17, footerSize: 12, margin: 8,
  });
  // 標籤由外往內的徑向堆疊：符號（℞ 右上、交點「密／平」右下）→ 度 → 星座 → 分。
  // 文字永遠直立；元素在 θ 方向上的徑向長度＝|w·cosθ|＋|h·sinθ|。
  const PARTS = Object.freeze([
    { part: "glyph", size: 24 },
    { part: "deg", size: 16 },
    { part: "sign", size: 14 },
    { part: "min", size: 14 },
  ]);
  const ANGLE_LABEL_SIZE = 13;
  const MARK_SIZE = 13;
  const SUFFIX_SIZE = 11;
  const MONO_ADVANCE = 0.6;      // 等寬字的字寬（em）
  const TEXT_HEIGHT = 0.8;       // 數字與拉丁字的字高（em）
  const LABEL_SCALES = Object.freeze([1, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6, 0.55, 0.5]);

  const DMS = /^(\d{1,2}°)(\d{2}′)\d{2}(?:\.\d+)?″$/;

  const round3 = (value) => {
    const rounded = Math.round(value * 1000) / 1000;
    return rounded === 0 ? 0 : rounded;
  };
  const mod360 = (value) => ((value % 360) + 360) % 360;
  const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

  /** 合法的 sign_position，並把度分切出來；任一不合就回 null（該點不畫）。 */
  function readPosition(position) {
    if (!Array.isArray(position) || position.length < 3) return null;
    const [sign, text, decimal] = position;
    if (!Number.isInteger(sign) || sign < 0 || sign > 11) return null;
    if (typeof text !== "string" || typeof decimal !== "string") return null;
    const match = DMS.exec(text);
    const lon = Number(decimal);
    if (!match || decimal.trim() === "" || !Number.isFinite(lon) || lon < 0 || lon >= 360) return null;
    return { sign, deg: match[1], min: match[2], lon };
  }

  /** 圖面角（相對參考點、逆時針，度）→ 座標。SVG 的 y 向下，所以 y 取負。 */
  function polar(angle, r) {
    const t = ((180 + angle) * Math.PI) / 180;
    return { x: G.c + r * Math.cos(t), y: G.c - r * Math.sin(t) };
  }

  /** 符號 path 以框中心放在 (x, y)、高為 size 的 em：回傳 [s, 0, 0, s, e, f]。 */
  function glyphMatrix(key, x, y, size) {
    const [x0, y0, x1, y1] = Glyphs.GLYPHS[key].bbox;
    const s = size / Glyphs.UNITS_PER_EM;
    return [round3(s), 0, 0, round3(s), round3(x - (s * (x0 + x1)) / 2), round3(y - (s * (y0 + y1)) / 2)];
  }
  function glyphBox(key, size) {
    const [x0, y0, x1, y1] = Glyphs.GLYPHS[key].bbox;
    return { w: ((x1 - x0) * size) / Glyphs.UNITS_PER_EM, h: ((y1 - y0) * size) / Glyphs.UNITS_PER_EM };
  }
  const monoBox = (text, size) => ({ w: text.length * size * MONO_ADVANCE, h: size * TEXT_HEIGHT });

  /** 粗估一行字的寬：CJK 一個字一 em，其餘約半 em。只用來換行與排右對齊。 */
  function textWidth(text, size) {
    let width = 0;
    for (const char of text) width += /[⺀-鿿豈-﫿＀-￯]/.test(char) ? size : size * 0.56;
    return width;
  }
  /** 在「；」「、」或空白之後換行，數字與日期不從中間切開；單段太長才逐字切。 */
  function wrap(text, size, maxWidth) {
    const lines = [];
    let line = "";
    for (const segment of text.match(/[^；、\s]+[；、\s]*|[；、\s]+/g) || []) {
      if (line && textWidth(line + segment, size) > maxWidth) {
        lines.push(line.trimEnd());
        line = "";
      }
      for (const char of segment) {
        if (line && textWidth(line + char, size) > maxWidth) {
          lines.push(line);
          line = "";
        }
        line += char;
      }
    }
    if (line.trim()) lines.push(line.trimEnd());
    return lines;
  }

  // ── 標籤：每個元素的框；在圖面角 a 上排出徑向堆疊
  function partBox(item, part, size, scale) {
    if (part === "glyph") {
      if (item.kind === "angle") return monoBox(item.label, ANGLE_LABEL_SIZE * scale);
      const glyph = glyphBox(item.glyph, size);
      const mark = item.retro ? glyphBox("retrograde", MARK_SIZE * scale).w
        : item.suffix ? SUFFIX_SIZE * scale : 0;
      return { w: glyph.w + (mark ? 1.5 * scale + mark : 0), h: glyph.h, glyph, mark };
    }
    if (part === "sign") return glyphBox(SIGN_KEYS[item.sign], size);
    return monoBox(part === "deg" ? item.deg : item.min, size);
  }
  function stackAt(item, a, scale) {
    const t = ((180 + a) * Math.PI) / 180;
    const c = Math.abs(Math.cos(t));
    const s = Math.abs(Math.sin(t));
    let r = G.rLabelTop;
    return PARTS.map((spec, k) => {
      const size = spec.size * scale;
      const box = partBox(item, spec.part, size, scale);
      const radial = box.w * c + box.h * s;
      const tangential = box.w * s + box.h * c;
      if (k) r -= G.gap * scale;
      const centre = r - radial / 2;
      r -= radial;
      return { part: spec.part, size, box, r: centre, tangential };
    });
  }
  /** 相鄰標籤的最小角距（度）：每一層「切向寬度＋留白」除以該層半徑，取最大值。 */
  function separationDegrees(items, scale) {
    let worst = 0;
    for (const item of items) {
      for (const part of stackAt(item, item.a, scale)) {
        worst = Math.max(worst, ((part.tangential + 3) / part.r) * (180 / Math.PI));
      }
    }
    return worst;
  }

  /**
   * 決定性的循環區間打包：
   *  1. 依圖面角排序；在最大空隙處切開圓周（359°／0° 回繞的兩點因此相鄰）。
   *  2. 線性掃描：每個標籤自成一群；與前一群重疊就合併，群組以成員期望角的平均為中心、
   *     等距 sep 對稱展開；合併後再往前檢查，直到不重疊。順序永遠不變。
   *  3. 切點兩端若仍相撞，全部併成一群。
   */
  function layoutLabels(items, sep) {
    const n = items.length;
    if (!n) return [];
    const order = items.map((item, index) => ({ index, a: item.a }))
      .sort((p, q) => p.a - q.a || p.index - q.index);
    let cut = 0;
    let best = -1;
    for (let k = 0; k < n; k += 1) {
      const next = k + 1 < n ? order[k + 1].a : order[0].a + 360;
      if (next - order[k].a > best) {
        best = next - order[k].a;
        cut = (k + 1) % n;
      }
    }
    const sequence = [];
    for (let k = 0; k < n; k += 1) {
      const at = (cut + k) % n;
      sequence.push({ index: order[at].index, u: order[at].a + (cut + k >= n ? 360 : 0) });
    }
    const start = (group) => group.sum / group.members.length - ((group.members.length - 1) * sep) / 2;
    const end = (group) => start(group) + (group.members.length - 1) * sep;
    let groups = [];
    for (const entry of sequence) {
      groups.push({ members: [entry], sum: entry.u });
      while (groups.length > 1) {
        const last = groups[groups.length - 1];
        const previous = groups[groups.length - 2];
        if (end(previous) + sep <= start(last) + 1e-9) break;
        groups.splice(groups.length - 2, 2, {
          members: [...previous.members, ...last.members], sum: previous.sum + last.sum,
        });
      }
    }
    if (groups.length > 1 && start(groups[0]) + 360 - end(groups[groups.length - 1]) < sep - 1e-9) {
      groups = [{
        members: groups.flatMap((group) => group.members),
        sum: groups.reduce((total, group) => total + group.sum, 0),
      }];
    }
    const placed = new Array(n);
    for (const group of groups) {
      group.members.forEach((entry, k) => { placed[entry.index] = mod360(start(group) + k * sep); });
    }
    return placed;
  }

  function labelBoxes(item, angle, scale) {
    return stackAt(item, angle, scale).map((part) => {
      const p = polar(angle, part.r);
      return { x0: p.x - part.box.w / 2, y0: p.y - part.box.h / 2, x1: p.x + part.box.w / 2, y1: p.y + part.box.h / 2 };
    });
  }
  const overlap = (a, b) => a.x0 < b.x1 + 1 && b.x0 < a.x1 + 1 && a.y0 < b.y1 + 1 && b.y0 < a.y1 + 1;
  function anyOverlap(boxesPerLabel) {
    for (let i = 0; i < boxesPerLabel.length; i += 1) {
      for (let j = i + 1; j < boxesPerLabel.length; j += 1) {
        for (const a of boxesPerLabel[i]) for (const b of boxesPerLabel[j]) if (overlap(a, b)) return true;
      }
    }
    return false;
  }

  /**
   * 角距由字框估出；展開後若框仍相撞就加大角距重排，整圈放不下時整組標籤等比縮小——
   * 不退到第二圈半徑。全部決定性：同一份回應永遠同一張圖。
   */
  function packLabels(items) {
    let fallback = null;
    for (const scale of LABEL_SCALES) {
      let sep = separationDegrees(items, scale);
      for (let attempt = 0; attempt < 8 && items.length * sep <= 360; attempt += 1) {
        const placed = layoutLabels(items, sep);
        const boxes = items.map((item, index) => labelBoxes(item, placed[index], scale));
        fallback = { placed, boxes, scale };
        if (!anyOverlap(boxes)) return fallback;
        sep *= 1.12;
      }
    }
    if (fallback) return fallback;
    const scale = LABEL_SCALES[LABEL_SCALES.length - 1];
    const placed = layoutLabels(items, 360 / items.length);
    return { placed, boxes: items.map((item, index) => labelBoxes(item, placed[index], scale)), scale };
  }

  // ── 讀回應
  function readPoints(response) {
    const astro = isRecord(response.astronomical_data) ? response.astronomical_data : {};
    const dateOnly = isRecord(response.birth_time_sensitivity) && response.birth_time_sensitivity.precision === "date_only";
    const points = [];
    const omitted = [];
    for (const [list, isNodes] of [[astro.bodies, false], [astro.nodes, true]]) {
      for (const body of Array.isArray(list) ? list : []) {
        if (!isRecord(body)) continue;
        const position = readPosition(body.sign_position);
        if (!position) continue;
        // 頁面投影的交點只帶名稱：由後端名稱表（labels.js）找回鍵，表外的名稱不猜。
        const key = typeof body.key === "string" ? body.key : isNodes ? Labels.nodeKeyForName(body.name) : null;
        const spec = key && Object.prototype.hasOwnProperty.call(POINTS, key)
          && (isNodes === Boolean(POINTS[key].node)) ? POINTS[key] : null;
        if (!spec) {
          omitted.push(typeof body.name === "string" && body.name ? body.name : String(body.key));
          continue;
        }
        points.push({
          kind: "body", key, glyph: spec.glyph, suffix: spec.suffix || "", ...position,
          // ℞ 與表格「行進」欄同源；月交點不標。
          retro: !spec.node && body.motion_sign === "negative",
          // 只有日期時，月亮在一天內約走 13°：刻線畫成虛線，與「正午錨點」說明同行。
          anchorOnly: dateOnly && key === "moon",
        });
      }
    }
    return { points, omitted, dateOnly };
  }

  function readAngles(response) {
    const angles = isRecord(response.astronomical_data) ? response.astronomical_data.angles : null;
    if (!isRecord(angles) || angles.available !== true || !isRecord(angles.sign_positions)) return [];
    const asc = readPosition(angles.sign_positions.asc);
    if (!asc) return [];
    return ANGLES.map(([key, label]) => {
      const position = readPosition(angles.sign_positions[key]);
      return position ? { kind: "angle", key, label, glyph: null, suffix: "", retro: false, ...position } : null;
    }).filter(Boolean);
  }

  function readCusps(response) {
    const houses = isRecord(response.derived_methods) ? response.derived_methods.house_division : null;
    if (!isRecord(houses) || houses.available !== true || !Array.isArray(houses.cusp_sign_positions)) return null;
    if (houses.cusp_sign_positions.length !== 12) return null;
    const cusps = houses.cusp_sign_positions.map(readPosition);
    if (cusps.some((cusp) => !cusp)) return null;
    return { lons: cusps.map((cusp) => cusp.lon), text: Labels.houseSystemText(houses.system_code, houses.system_name) };
  }

  // ── 場景：基本圖元。paint 是角色名（bg／band／fg／dim／hair／accent），由各 renderer 決定實際顏色。
  function linePrim(part, a, b, stroke, width, extra = {}) {
    return { type: "line", part, x1: round3(a.x), y1: round3(a.y), x2: round3(b.x), y2: round3(b.y), stroke, width, ...extra };
  }
  function textPrim(part, x, y, content, size, font, fill, extra = {}) {
    return { type: "text", part, x: round3(x), y: round3(y), text: content, size: round3(size), font, fill,
      anchor: "middle", ...extra };
  }
  function glyphPrim(part, key, x, y, size, fill, extra = {}) {
    return { type: "glyph", part, glyph: key, matrix: glyphMatrix(key, x, y, size), fill, ...extra };
  }

  function zodiacRing(reference) {
    const at = (lon, r) => polar(lon - reference, r);
    const items = [
      { type: "circle", part: "zodiac-band", cx: G.c, cy: G.c, r: G.rOut, fill: "band", stroke: "dim", width: 1.2 },
      { type: "circle", part: "zodiac-inner", cx: G.c, cy: G.c, r: G.rSignIn, fill: "bg", stroke: "dim", width: 1 },
    ];
    for (let sign = 0; sign < 12; sign += 1) {
      items.push(linePrim("sign-boundary", at(sign * 30, G.rSignIn), at(sign * 30, G.rOut), "dim", 1));
    }
    for (let degree = 0; degree < 360; degree += 1) {
      if (degree % 30 === 0) continue;
      const length = degree % 10 === 0 ? 8 : degree % 5 === 0 ? 5.5 : 3;
      items.push(linePrim("degree-tick", at(degree, G.rSignIn), at(degree, G.rSignIn + length),
        degree % 5 === 0 ? "dim" : "hair", degree % 10 === 0 ? 0.9 : 0.6));
    }
    for (let sign = 0; sign < 12; sign += 1) {
      // 符號與中文名並排置中；中文名寬約兩個字。
      const p = at(sign * 30 + 15, G.rSignText);
      const glyphWidth = glyphBox(SIGN_KEYS[sign], 15).w;
      const total = glyphWidth + 3 + 24;
      items.push(glyphPrim("sign-glyph", SIGN_KEYS[sign], p.x - total / 2 + glyphWidth / 2, p.y, 15, "fg"));
      items.push(textPrim("sign-name", p.x - total / 2 + glyphWidth + 3, p.y, SIGN_NAMES[sign], 12, "sans", "dim",
        { anchor: "start" }));
    }
    return items;
  }

  function houseRing(cusps, reference) {
    const at = (lon, r) => polar(lon - reference, r);
    const items = [
      { type: "circle", part: "house-ring", cx: G.c, cy: G.c, r: G.rHouseOut, fill: null, stroke: "dim", width: 0.9 },
      { type: "circle", part: "house-ring", cx: G.c, cy: G.c, r: G.rHouseIn, fill: null, stroke: "dim", width: 0.9 },
    ];
    cusps.forEach((lon) => {
      items.push(linePrim("house-cusp", at(lon, G.rHouseIn), at(lon, G.rHouseOut), "dim", 1));
      items.push(linePrim("house-cusp-extension", at(lon, G.rHouseOut), at(lon, G.rSignIn), "hair", 0.7, { dash: "2 3" }));
    });
    cusps.forEach((lon, index) => {
      // 宮號放在兩個宮頭之間的中點（圖面位置，不是方法計算）。
      const next = cusps[(index + 1) % 12];
      const p = at(lon + mod360(next - lon) / 2, G.rHouseText);
      items.push(textPrim("house-number", p.x, p.y, String(index + 1), 14, "mono", "dim"));
    });
    return items;
  }

  function angleAxes(angles, reference) {
    const at = (lon, r) => polar(lon - reference, r);
    const byKey = Object.fromEntries(angles.map((angle) => [angle.key, angle]));
    const items = angles.map((angle) => linePrim("angle-axis", at(angle.lon, G.rOut + 9), at(angle.lon, G.rTickIn), "accent", 1.6));
    for (const [from, to] of [["asc", "desc"], ["mc", "ic"]]) {
      if (!byKey[from] || !byKey[to]) continue;
      items.push(linePrim("angle-line", at(byKey[from].lon, G.rHouseOut), at(byKey[to].lon, G.rHouseOut), "accent", 1.2));
    }
    for (const key of ["asc", "mc"]) {
      if (!byKey[key]) continue;
      // 外緣小三角，指向圓心：只標上升與中天兩個起點。
      const t = ((180 + byKey[key].lon - reference) * Math.PI) / 180;
      const tip = at(byKey[key].lon, G.rOut + 1);
      const ux = Math.cos(t);
      const uy = -Math.sin(t);
      const base = { x: tip.x + ux * 10, y: tip.y + uy * 10 };
      items.push({ type: "polygon", part: "angle-marker", fill: "accent", points: [
        [tip.x, tip.y], [base.x - uy * 5, base.y + ux * 5], [base.x + uy * 5, base.y - ux * 5],
      ].map(([x, y]) => [round3(x), round3(y)]) });
    }
    return items;
  }

  function labelScene(item, angle, scale) {
    const colour = item.kind === "angle" ? "accent" : "fg";
    const halo = 4 * scale;
    const items = [];
    for (const part of stackAt(item, angle, scale)) {
      const p = polar(angle, part.r);
      if (part.part === "glyph" && item.kind === "angle") {
        items.push(textPrim("angle-label", p.x, p.y, item.label, ANGLE_LABEL_SIZE * scale, "mono", colour, { halo }));
      } else if (part.part === "glyph") {
        const { glyph: box, mark } = part.box;
        const gx = p.x - part.box.w / 2 + box.w / 2;
        items.push(glyphPrim("label-glyph", item.glyph, gx, p.y, part.size, colour, { halo: halo / (part.size / 1000) }));
        const mx = p.x + part.box.w / 2 - mark / 2;
        if (item.retro) {
          const size = MARK_SIZE * scale;
          const markBox = glyphBox("retrograde", size);
          items.push(glyphPrim("label-mark", "retrograde", mx, p.y - box.h / 2 + markBox.h / 2, size, colour,
            { halo: halo / (size / 1000) }));
        } else if (item.suffix) {
          const size = SUFFIX_SIZE * scale;
          items.push(textPrim("label-suffix", mx, p.y + box.h / 2 - size / 2, item.suffix, size, "sans", "dim", { halo }));
        }
      } else if (part.part === "sign") {
        items.push(glyphPrim("label-sign", SIGN_KEYS[item.sign], p.x, p.y, part.size,
          item.kind === "angle" ? colour : "dim", { halo: halo / (part.size / 1000) }));
      } else {
        items.push(textPrim("label-text", p.x, p.y, part.part === "deg" ? item.deg : item.min, part.size, "mono", colour, { halo }));
      }
    }
    return items;
  }

  function footer(lines) {
    const items = lines.map((content, index) => textPrim("footer", G.margin, G.footerTop + 22 + index * G.footerLine,
      content, G.footerSize, "sans", "dim", { anchor: "start" }));
    items.push(textPrim("footer", G.width - G.margin, G.footerTop + 22, TEXT.brand, G.footerSize, "sans", "dim",
      { anchor: "end" }));
    return items;
  }

  /**
   * 回應 → 星盤圖模型。options.inputSummary：使用者勾選「加印輸入摘要」時的文字行（預設沒有）。
   */
  function build(response, options = {}) {
    if (!isRecord(response)) throw new Error("星盤圖需要一份回應。");
    const { points, omitted, dateOnly } = readPoints(response);
    const angles = readAngles(response);
    const cusps = readCusps(response);
    const hasAngles = angles.length > 0;
    const reference = hasAngles ? angles[0].lon : 0;

    const notes = [
      cusps ? `宮位制：${cusps.text}` : TEXT.noHouses,
      ...(hasAngles ? [TEXT.accent] : [TEXT.noAngles]),
      ...(points.some((point) => point.anchorOnly) ? [TEXT.dateOnly] : []),
      ...(omitted.length ? [`圖上未畫：${omitted.join("、")}（見表格）`] : []),
    ];
    const summary = Array.isArray(options.inputSummary) ? options.inputSummary.filter((line) => typeof line === "string" && line) : [];
    // 第一行右側有品牌字，換行寬度扣掉它。
    const footerLines = [...notes, ...summary].flatMap((line, index) => wrap(line, G.footerSize,
      G.width - 2 * G.margin - (index === 0 ? textWidth(TEXT.brand, G.footerSize) + 12 : 0)));
    const height = G.footerTop + 22 + (footerLines.length - 1) * G.footerLine + 16;

    const items = [...points, ...angles].map((item) => ({ ...item, a: mod360(item.lon - reference) }));
    const packed = packLabels(items);

    const ticks = points.map((point) => linePrim("body-tick", polar(point.lon - reference, G.rSignIn),
      polar(point.lon - reference, G.rTickIn), "fg", 1.8, point.anchorOnly ? { dash: "2 1.6" } : {}));
    const leaders = items.map((item, index) => linePrim("leader", polar(item.a, G.rTickIn),
      polar(packed.placed[index], G.rLabelTop), item.kind === "angle" ? "accent" : "dim", 0.8));

    const asc = angles.find((angle) => angle.key === "asc");
    const scene = [
      { group: "zodiac", items: zodiacRing(reference) },
      ...(cusps ? [{ group: "houses", items: houseRing(cusps.lons, reference) }] : []),
      ...(hasAngles ? [{ group: "angles", items: angleAxes(angles, reference) }] : []),
      { group: "markers", items: [...ticks, ...leaders] },
      { group: "labels", children: items.map((item, index) => ({
        group: "label", items: labelScene(item, packed.placed[index], packed.scale),
      })) },
      { group: "footer", items: footer(footerLines) },
    ];
    return {
      width: G.width,
      height,
      center: { x: G.c, y: G.c },
      frame: hasAngles ? "ascendant" : "aries",
      ariaLabel: asc
        ? `星盤圖：上升 ${SIGN_NAMES[asc.sign]} ${asc.deg}${asc.min}；各天體位置見下方表格`
        : "星盤圖：本次沒有軸點，牡羊 0° 置於左方；各天體位置見下方表格",
      notes,
      dateOnly,
      scene,
      labels: items.map((item, index) => ({
        key: item.key, kind: item.kind,
        boxes: packed.boxes[index].map((box) => ({
          x0: round3(box.x0), y0: round3(box.y0), x1: round3(box.x1), y1: round3(box.y1),
        })),
      })),
    };
  }

  return Object.freeze({ build, layoutLabels, TEXT });
});
