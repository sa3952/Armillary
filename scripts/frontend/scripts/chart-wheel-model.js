(function attachChartWheelModel(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  const api = factory(
    commonJs ? require("./chart-glyphs.js") : root.ArmillaryChartGlyphs,
    commonJs ? require("./labels.js") : root.ArmillaryLabels,
    commonJs ? require("./chart-wheel-aspects.js") : root.ChartWheelAspects,
  );
  if (commonJs) module.exports = api;
  if (root) root.ChartWheelModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildChartWheelModel(Glyphs, Labels, Aspects) {
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
  // 回應缺鍵或字串不合格式的點不畫，不猜；12 個宮頭不齊就整個宮位環不畫。回應裡其他帶黃經、
  // 圖上不畫的點，一律寫進頁尾「圖上未畫」（POSITION_SOURCES）。

  const SIGN_KEYS = Object.freeze(Object.keys(Labels.VOCABULARIES.zodiac_sign));
  const SIGN_NAMES = Object.freeze(Object.values(Labels.VOCABULARIES.zodiac_sign));

  // 回應的點鍵 → 符號鍵與它所在的那一組。交點與 Lilith 都是兩種都畫（表格兩者分列、不替使用者
  // 擇一），以下標區分；這兩組不標 ℞。
  const POINTS = Object.freeze({
    sun: { glyph: "sun", list: "bodies" }, moon: { glyph: "moon", list: "bodies" },
    mercury: { glyph: "mercury", list: "bodies" }, venus: { glyph: "venus", list: "bodies" },
    mars: { glyph: "mars", list: "bodies" }, jupiter: { glyph: "jupiter", list: "bodies" },
    saturn: { glyph: "saturn", list: "bodies" }, uranus: { glyph: "uranus", list: "bodies" },
    neptune: { glyph: "neptune", list: "bodies" }, pluto: { glyph: "pluto", list: "bodies" },
    chiron: { glyph: "chiron", list: "bodies" },
    true_node: { glyph: "north_node", suffix: "密", node: true, list: "nodes" },
    mean_node: { glyph: "north_node", suffix: "平", node: true, list: "nodes" },
    true_south_node: { glyph: "south_node", suffix: "密", node: true, list: "nodes" },
    mean_south_node: { glyph: "south_node", suffix: "平", node: true, list: "nodes" },
    mean_lilith: { glyph: "lilith", suffix: "平", list: "lunar_apsides" },
    natural_lilith: { glyph: "lilith", suffix: "自然", list: "lunar_apsides" },
  });
  // 三組點，每一點以回應的 key 認出是哪一顆；沒有 key 或不在 POINTS 的點寫進「圖上未畫」，不由名稱猜。
  const POINT_LISTS = Object.freeze([
    ["bodies", (astro) => astro.bodies],
    ["nodes", (astro) => astro.nodes],
    ["lunar_apsides", (astro) => (isRecord(astro.lunar_apsides) ? astro.lunar_apsides.points : null)],
  ]);
  const ANGLES = Object.freeze([["asc", "ASC"], ["mc", "MC"], ["desc", "DSC"], ["ic", "IC"]]);

  // 回應裡每一處帶黃經的鍵（名稱以 sign_position／sign_positions 結尾）圖怎麼處理：
  //   "drawn"：圖上畫（三組點、四軸、宮頭；其中畫不出來的另寫進「圖上未畫」）；
  //   字串：圖上不畫，頁尾「圖上未畫」用這個名稱（與表格區段同名，讀者照名稱找得到）；
  //   null：不是另外的點。
  // 不在這張表裡的位置也一律寫進「圖上未畫」（用它的名稱，沒有名稱寫「其他位置」）：後端新增帶黃經
  // 的點，圖不會無聲地漏掉它。
  const POSITION_SOURCES = Object.freeze([
    ["astronomical_data.bodies[].sign_position", "drawn"],
    ["astronomical_data.nodes[].sign_position", "drawn"],
    ["astronomical_data.lunar_apsides.points[].sign_position", "drawn"],
    ["astronomical_data.angles.sign_positions", "drawn"],
    ["derived_methods.house_division.cusp_sign_positions", "drawn"],
    ["astronomical_data.extra_angles.angles.*.sign_position", "額外角點"],
    ["astronomical_data.parallax_moon.*.sign_position", "站心月亮"],
    ["astronomical_data.fixed_stars[].sign_position", "恆星"],
    ["derived_geometry.antiscia.antiscia[].sign_position", "反照點與反向反照點"],
    ["derived_geometry.antiscia.contra_antiscia[].sign_position", "反照點與反向反照點"],
    ["derived_methods.lots.sign_positions", "阿拉伯點"],
    ["derived_methods.lots.by_sect.*.sign_positions", "阿拉伯點"],
    ["derived_methods.dodecatemoria.points[].sign_position", "十二分部"],
    ["derived_methods.dodecatemoria.points[].point_sign_position", "十二分部"],
    // 出生時刻敏感度的代表值，是圖上同一批點在代表時刻的位置。
    ["birth_time_sensitivity.**", null],
    // 產前朔望與日月食的度數是出生前（或出生時正在進行的日月食）另一個時刻的位置，不是這張盤的點。
    ["astronomical_data.lunar_events.**", null],
    // 月宿的起訖是黃道上的分界，圖上不畫；月亮本身已在天體裡畫出。
    ["derived_methods.lunar_mansions.placements[].mansion.boundary_sign_positions", "月宿"],
  ]);
  const UNLISTED_POSITION = "其他位置";

  const TEXT = Object.freeze({
    noAngles: "本次沒有軸點，圖以牡羊 0° 置於左方",
    dateOnly: "月亮刻線為虛線：正午錨點，非出生時刻",
    accent: "紅色只標四軸，不表示吉凶",
    noHouses: "本次沒有宮位",
    brand: "渾儀 Armillary",
    angles: "四軸",
    cusps: "宮頭",
  });

  // ── 幾何（viewBox 寬 600；圓心 300,300；頁尾在圓下方，高度隨行數）
  const G = Object.freeze({
    width: 600, c: 300,
    rOut: 288, rSignIn: 255, rSignText: 271.5,
    rTickIn: 246,          // 天體刻線：星座環內緣 255 → 246，在真實黃經，不移動
    rElbow: 243.5,         // 引線先沿刻線方向走到這裡，再斜向標籤
    rLabelTop: 238,        // 標籤堆疊的外緣；引線的終點
    footerTop: 600, margin: 8,
  });
  // 三種字級：圖在畫面上越小，字相對於圖越大，才讀得到；越大則相對越小，群聚才不必攤得那麼開。
  // 依圖在畫面上的寬度選（presetForWidth）；下載檔一律 standard（寬 600）。手機版的字較大，
  // 宮位環往內收，讓標籤帶夠長。
  const PRESETS = Object.freeze({
    compact: Object.freeze({ text: 1.2, rHouseOut: 102, rHouseIn: 78 }),
    standard: Object.freeze({ text: 1, rHouseOut: 112, rHouseIn: 86 }),
    wide: Object.freeze({ text: 0.86, rHouseOut: 112, rHouseIn: 86 }),
  });
  /** 圖在畫面上的寬度（CSS px）→ 字級。 */
  function presetForWidth(px) {
    if (!Number.isFinite(px) || px <= 0) return "standard";
    return px < 480 ? "compact" : px < 680 ? "standard" : "wide";
  }

  // 標籤由外往內的徑向堆疊：符號（℞ 右上、交點與 Lilith 的下標右下）→ 度 → 星座 → 分。
  // 文字永遠直立；元素在 θ 方向上的徑向長度＝|w·cosθ|＋|h·sinθ|，切向寬度＝|w·sinθ|＋|h·cosθ|。
  const PARTS = Object.freeze(["glyph", "deg", "sign", "min"]);
  const SIZE = Object.freeze({
    glyph: 24, deg: 16, sign: 14, min: 14, angle: 13, mark: 13, suffix: 11,
    ringGlyph: 15, ringName: 12, house: 14, footer: 12, footerLine: 17,
  });
  const PART_GAP = 1.5;          // 堆疊元素之間的徑向留白
  const ROW_GAP = 4;             // 共用標籤裡兩點之間的徑向留白
  const PAD = 1.5;            // 相鄰標籤之間，每一側的切向留白
  const MONO_ADVANCE = 0.6;      // 等寬字的字寬（em）
  const TEXT_HEIGHT = 1;       // 數字與拉丁字的字高（em）
  const LABEL_SCALES = Object.freeze([1, 0.92, 0.85, 0.78, 0.72, 0.66, 0.6, 0.55, 0.5]);
  const SHARE_DEGREES = 1;       // 角距小於這個值的兩點可共用一條標籤
  const MAX_SIGN_SHIFT = 4;     // 為了讓標籤留在所屬星座，整群最多再移這麼多度
  const SHIFT_STEP = 0.25;

  const DMS = /^(\d{1,2}°)(\d{2}′)\d{2}(?:\.\d+)?″$/;

  // 座標捨入與角度正規化與相位線圖層同一份：兩層的座標必須一致。
  const { round3, mod360, isRecord } = Aspects;
  /** 由 a 到 b 的有號最短角差（−180, 180]。 */
  const signedGap = (a, b) => {
    const d = mod360(b - a);
    return d > 180 ? d - 360 : d;
  };
  const degrees = (radians) => (radians * 180) / Math.PI;

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

  /** 粗估一行字的寬：CJK 一個字一 em，其餘約半 em。只用來換行、排右對齊與量下標。 */
  function textWidth(text, size) {
    let width = 0;
    for (const char of text) width += /[⺀-鿿豈-﫿＀-￯]/.test(char) ? size : size * 0.56;
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

  // ── 標籤
  //
  // 一個「標籤單位」是一個點，或角距不到 1° 的兩個相鄰天體共用的一條標籤（兩點由外往內接著排，
  // 各自一條引線連回自己的刻線）。標籤擠在一起時，同一星座只在第一個標籤印星座符號。
  function partSize(item, part, fs) {
    if (part === "glyph") return (item.kind === "angle" ? SIZE.angle : SIZE.glyph) * fs;
    return SIZE[part] * fs;
  }
  function partBox(item, part, fs) {
    const size = partSize(item, part, fs);
    if (part === "glyph") {
      if (item.kind === "angle") return monoBox(item.label, size);
      const glyph = glyphBox(item.glyph, size);
      const mark = item.retro ? glyphBox("retrograde", SIZE.mark * fs).w
        : item.suffix ? textWidth(item.suffix, SIZE.suffix * fs) : 0;
      return { w: glyph.w + (mark ? 1.5 * fs + mark : 0), h: glyph.h, glyph, mark };
    }
    if (part === "sign") return glyphBox(SIGN_KEYS[item.sign], size);
    return monoBox(part === "deg" ? item.deg : item.min, size);
  }
  /** 單位在圖面角 a 上的徑向堆疊：每個元素的中心半徑與切向寬度；inner 是堆疊內緣的半徑。 */
  function unitStack(unit, a, fs) {
    const t = ((180 + a) * Math.PI) / 180;
    const c = Math.abs(Math.cos(t));
    const s = Math.abs(Math.sin(t));
    let r = G.rLabelTop;
    const parts = [];
    unit.members.forEach((item, row) => {
      for (const part of PARTS) {
        if (part === "sign" && item.omitSign) continue;
        const box = partBox(item, part, fs);
        const radial = box.w * c + box.h * s;
        if (parts.length) r -= (row && part === "glyph" ? ROW_GAP : PART_GAP) * fs;
        parts.push({ item, part, size: partSize(item, part, fs), box, r: r - radial / 2,
          tangential: box.w * s + box.h * c });
        r -= radial;
      }
    });
    return { parts, inner: r };
  }
  /** 單位在圖面角 a 上的切向半寬（度）：每一層「半寬＋留白」除以該層半徑，取最大值。 */
  function halfWidth(unit, a, fs) {
    let worst = 0;
    for (const part of unitStack(unit, a, fs).parts) {
      worst = Math.max(worst, degrees((part.tangential / 2 + PAD * fs) / part.r));
    }
    return worst;
  }
  const fits = (unit, a, fs, floor) => unitStack(unit, a, fs).inner >= floor;

  /**
   * 決定性的循環區間打包（每個標籤的切向寬度可以不同）：
   *  1. 依期望角排序；在最大的「空隙減去兩側半寬」處切開圓周（359°／0° 回繞的兩點因此相鄰）。
   *  2. 線性掃描：每個標籤自成一群；與前一群相撞就合併。群內標籤緊鄰排列，整群的位置讓
   *     往前與往後移得最多的兩個標籤移得一樣多；合併後再往前檢查，直到不相撞。順序永遠不變。
   *  3. 切點兩端若仍相撞，全部併成一群。
   * angles：期望角（度）；halfWidths：各標籤的切向半寬（度）。回傳 placed（圖面角）、groups（依
   * 圓周順序的標籤索引）與 sequence（展開後、不回繞的期望角）。
   */
  function layoutLabels(angles, halfWidths) {
    const n = angles.length;
    if (!n) return { placed: [], groups: [], unwrapped: [] };
    const hw = halfWidths || angles.map(() => 0);
    const order = angles.map((a, index) => ({ index, a })).sort((p, q) => p.a - q.a || p.index - q.index);
    let cut = 0;
    let best = -Infinity;
    for (let k = 0; k < n; k += 1) {
      const next = k + 1 < n ? order[k + 1] : { ...order[0], a: order[0].a + 360 };
      const free = next.a - order[k].a - hw[order[k].index] - hw[next.index];
      if (free > best) {
        best = free;
        cut = (k + 1) % n;
      }
    }
    const sequence = [];
    for (let k = 0; k < n; k += 1) {
      const at = (cut + k) % n;
      sequence.push({ index: order[at].index, u: order[at].a + (cut + k >= n ? 360 : 0) });
    }
    // 群：members 依序緊鄰；offset 是成員相對第一個成員的角距；start 取在「離期望角最遠的標籤」
    // 兩側相等的位置，讓最長的引線盡量短。
    const makeGroup = (members) => {
      let offset = 0;
      let low = Infinity;
      let high = -Infinity;
      const offsets = members.map((entry, k) => {
        if (k) offset += hw[members[k - 1].index] + hw[entry.index];
        low = Math.min(low, entry.u - offset);
        high = Math.max(high, entry.u - offset);
        return offset;
      });
      return { members, offsets, start: (low + high) / 2 };
    };
    const first = (group) => group.members[0].index;
    const last = (group) => group.members[group.members.length - 1].index;
    const end = (group) => group.start + group.offsets[group.offsets.length - 1];
    let groups = [];
    for (const entry of sequence) {
      groups.push(makeGroup([entry]));
      while (groups.length > 1) {
        const tail = groups[groups.length - 1];
        const previous = groups[groups.length - 2];
        if (end(previous) + hw[last(previous)] + hw[first(tail)] <= tail.start + 1e-9) break;
        groups.splice(groups.length - 2, 2, makeGroup([...previous.members, ...tail.members]));
      }
    }
    if (groups.length > 1) {
      const head = groups[0];
      const tail = groups[groups.length - 1];
      if (head.start + 360 - end(tail) < hw[first(head)] + hw[last(tail)] - 1e-9) {
        groups = [makeGroup(groups.flatMap((group) => group.members))];
      }
    }
    const placed = new Array(n);
    const unwrapped = new Array(n);
    for (const group of groups) {
      group.members.forEach((entry, k) => {
        unwrapped[entry.index] = entry.u;
        placed[entry.index] = group.start + group.offsets[k];
      });
    }
    return { placed, unwrapped, groups: groups.map((group) => group.members.map((entry) => entry.index)) };
  }

  /** 單位所屬星座的範圍（以期望角 u 展開、不回繞）：第一個成員的星座起點到最後一個成員的星座終點。 */
  function signRange(unit, u) {
    const within = (item) => Math.min(30, Math.max(0, item.lon - item.sign * 30));
    const head = unit.members[0];
    const tail = unit.members[unit.members.length - 1];
    return [u + signedGap(unit.a, head.a) - within(head), u + signedGap(unit.a, tail.a) - within(tail) + 30];
  }
  const outside = (position, [low, high]) => Math.max(0, low - position) + Math.max(0, position - high);

  /**
   * 為了讓標籤盡量留在自己的星座裡，整群在左右的空隙內平移（最多 MAX_SIGN_SHIFT 度）：
   * 取「各標籤落在所屬星座之外的度數總和」最小的位移，同樣小時取位移最小者。群內次序與間距不變。
   */
  function keepInSigns(units, layout, hw) {
    const { groups, unwrapped } = layout;
    // placed 與 unwrapped 在同一個展開的座標裡（切點之後的加了 360°）。
    const position = [...layout.placed];
    const count = groups.length;
    for (let g = 0; g < count; g += 1) {
      const members = groups[g];
      const head = members[0];
      const tail = members[members.length - 1];
      const before = groups[(g + count - 1) % count];
      const after = groups[(g + 1) % count];
      const previousEnd = position[before[before.length - 1]] - (g === 0 ? 360 : 0);
      const nextStart = position[after[0]] + (g === count - 1 ? 360 : 0);
      const roomBefore = count === 1 ? 360 - (position[tail] - position[head]) - hw[head] - hw[tail]
        : position[head] - previousEnd - hw[before[before.length - 1]] - hw[head];
      const roomAfter = count === 1 ? roomBefore
        : nextStart - position[tail] - hw[tail] - hw[after[0]];
      const low = -Math.min(MAX_SIGN_SHIFT, Math.max(0, roomBefore));
      const high = Math.min(MAX_SIGN_SHIFT, Math.max(0, roomAfter));
      const cost = (shift) => members.reduce((total, index) => total
        + outside(position[index] + shift, signRange(units[index], unwrapped[index])), 0);
      let bestShift = 0;
      let bestCost = cost(0);
      for (let step = 1; step * SHIFT_STEP <= MAX_SIGN_SHIFT; step += 1) {
        for (const shift of [-step * SHIFT_STEP, step * SHIFT_STEP]) {
          if (shift < low - 1e-9 || shift > high + 1e-9) continue;
          const value = cost(shift);
          if (value < bestCost - 0.01) {
            bestCost = value;
            bestShift = shift;
          }
        }
      }
      if (bestShift) for (const index of members) position[index] += bestShift;
    }
    return position.map(mod360);
  }

  /** 依黃經相鄰、角距不到 1° 的兩個天體（不含四軸）兩兩共用一條標籤；已配對的不再配。 */
  function shareUnits(items, sequence) {
    const units = [];
    const taken = new Set();
    sequence.forEach((index, k) => {
      if (taken.has(index)) return;
      const next = sequence[k + 1];
      const item = items[index];
      if (next !== undefined && !taken.has(next) && item.kind === "body" && items[next].kind === "body"
        && mod360(items[next].a - item.a) < SHARE_DEGREES) {
        taken.add(index);
        taken.add(next);
        units.push({ members: [item, items[next]], a: mod360(item.a + mod360(items[next].a - item.a) / 2) });
        return;
      }
      taken.add(index);
      units.push({ members: [item], a: item.a });
    });
    return units;
  }

  /** 一輪排版：共用標籤、切向打包、星座省略、留在星座內。回傳單位、位置與每個點的框。 */
  function arrange(items, fs, padFactor, floor) {
    for (const item of items) item.omitSign = false;
    const order = items.map((item, index) => ({ index, a: item.a })).sort((p, q) => p.a - q.a || p.index - q.index)
      .map((entry) => entry.index);
    // 共用標籤只在放得下（堆疊不壓到宮位環）時成立；共用標籤裡同星座的第二點不印星座。
    let units = shareUnits(items, order).flatMap((unit) => {
      if (unit.members.length === 1) return [unit];
      unit.members[1].omitSign = unit.members[1].sign === unit.members[0].sign;
      if (fits(unit, unit.a, fs, floor)) return [unit];
      unit.members[1].omitSign = false;
      return unit.members.map((item) => ({ members: [item], a: item.a }));
    });
    let hw;
    let layout;
    // 每拆開一條放不下的共用標籤就重排一次；共用標籤只會越來越少，所以一定會停。
    for (;;) {
      hw = units.map((unit) => halfWidth(unit, unit.a, fs) * padFactor);
      layout = layoutLabels(units.map((unit) => unit.a), hw);
      // 切向寬度依位置而變：在排好的位置上重量一次，取較大者再排一次。
      hw = units.map((unit, index) => Math.max(hw[index], halfWidth(unit, layout.placed[index], fs) * padFactor));
      layout = layoutLabels(units.map((unit) => unit.a), hw);
      const split = units.findIndex((unit, index) => unit.members.length > 1 && !fits(unit, layout.placed[index], fs, floor));
      if (split < 0) break;
      units[split].members[1].omitSign = false;
      units = [...units.slice(0, split), ...units[split].members.map((item) => ({ members: [item], a: item.a })),
        ...units.slice(split + 1)];
    }
    // 擠在一起（同一群裡相鄰）的天體標籤，與前一個標籤同星座就不再印星座；四軸照印、也打斷連續。
    const sameSignAsPrevious = (previous, unit) => previous.members[0].kind === "body" && unit.members[0].kind === "body"
      && previous.members[previous.members.length - 1].sign === unit.members[0].sign;
    for (const group of layout.groups) {
      for (let k = 1; k < group.length; k += 1) {
        if (sameSignAsPrevious(units[group[k - 1]], units[group[k]])) units[group[k]].members[0].omitSign = true;
      }
    }
    hw = units.map((unit, index) => halfWidth(unit, layout.placed[index], fs) * padFactor);
    layout = layoutLabels(units.map((unit) => unit.a), hw);
    // 重排後若某個省略星座的標籤不再緊接著同星座的前一個標籤，就把星座印回來。
    const groupOf = new Map();
    layout.groups.forEach((group, g) => group.forEach((index, k) => groupOf.set(index, [g, k])));
    units.forEach((unit, index) => {
      const head = unit.members[0];
      if (!head.omitSign) return;
      const [g, k] = groupOf.get(index);
      if (!k || !sameSignAsPrevious(units[layout.groups[g][k - 1]], unit)) head.omitSign = false;
    });
    hw = units.map((unit, index) => Math.max(hw[index], halfWidth(unit, layout.placed[index], fs) * padFactor));
    const placed = keepInSigns(units, layout, hw);
    const boxes = new Map();
    let fitsAll = true;
    units.forEach((unit, index) => {
      const stack = unitStack(unit, placed[index], fs);
      if (stack.inner < floor - 1e-6) fitsAll = false;
      for (const item of unit.members) boxes.set(item, []);
      for (const part of stack.parts) {
        const p = polar(placed[index], part.r);
        boxes.get(part.item).push({ x0: p.x - part.box.w / 2, y0: p.y - part.box.h / 2,
          x1: p.x + part.box.w / 2, y1: p.y + part.box.h / 2 });
      }
    });
    return { units, placed, fs, boxes: items.map((item) => boxes.get(item)), fitsAll,
      omitted: { signs: items.some((item) => item.omitSign), shared: units.some((unit) => unit.members.length > 1) } };
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
   * 排版；框仍相撞就加大留白重排，整圈放不下（或堆疊壓到宮位環）時整組標籤等比縮小——
   * 不退到第二圈半徑。全部決定性：同一份回應永遠同一張圖。
   */
  function packLabels(items, text, floor) {
    let fallback = null;
    for (const scale of LABEL_SCALES) {
      let padFactor = 1;
      for (let attempt = 0; attempt < 6; attempt += 1) {
        const result = arrange(items, text * scale, padFactor, floor);
        fallback = result;
        // 堆疊壓到宮位環是字太大，加大留白沒有用：直接換小一號。
        if (!result.fitsAll) break;
        if (!anyOverlap(result.boxes)) return result;
        padFactor *= 1.15;
      }
    }
    return fallback;
  }

  // ── 讀回應
  /**
   * 落宮：點鍵 → 宮號。行星讀後端 planet_in_house.placements；月交點與 Lilith 讀 point_placements
   * （後端只在整宮制給）。沒有落宮時是空表。符號對照與方盤用。
   */
  function readHouses(response) {
    const module = isRecord(response.derived_methods) ? response.derived_methods.planet_in_house : null;
    const houses = new Map();
    if (!isRecord(module) || module.execution_status !== "computed" || !Array.isArray(module.placements)) return houses;
    const points = isRecord(module.point_placements) && module.point_placements.execution_status === "computed"
      && Array.isArray(module.point_placements.placements) ? module.point_placements.placements : [];
    for (const place of [...module.placements, ...points]) {
      if (isRecord(place) && typeof place.key === "string" && Number.isInteger(place.house)) houses.set(place.key, place.house);
    }
    return houses;
  }

  function readPoints(response) {
    const astro = isRecord(response.astronomical_data) ? response.astronomical_data : {};
    const dateOnly = isRecord(response.birth_time_sensitivity) && response.birth_time_sensitivity.precision === "date_only";
    const points = [];
    const omitted = [];
    for (const [list, read] of POINT_LISTS) {
      const entries = read(astro);
      for (const body of Array.isArray(entries) ? entries : []) {
        if (!isRecord(body)) continue;
        const position = readPosition(body.sign_position);
        if (!position) continue;
        const key = typeof body.key === "string" ? body.key : null;
        const spec = key && Object.hasOwn(POINTS, key) && POINTS[key].list === list
          ? POINTS[key] : null;
        if (!spec) {
          omitted.push(typeof body.name === "string" && body.name ? body.name : String(body.key));
          continue;
        }
        points.push({
          kind: "body", key, glyph: spec.glyph, suffix: spec.suffix || "", ...position,
          // 回應的名稱，與表格第一欄同字（符號對照用）。
          name: typeof body.name === "string" && body.name ? body.name : key,
          // ℞ 與表格「行進」欄同源；月交點與 Lilith 不標。
          retro: list === "bodies" && body.motion_sign === "negative",
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
      return position ? { kind: "angle", key, label, glyph: null, suffix: "", retro: false, ...position,
        name: Labels.VOCABULARIES.angle_label[key] } : null;
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

  /** 回應裡每一處帶黃經的鍵：{ path（陣列索引寫成 []）, value, record }。 */
  function* positionPaths(value, path) {
    if (Array.isArray(value)) {
      for (const entry of value) yield* positionPaths(entry, `${path}[]`);
      return;
    }
    if (!isRecord(value)) return;
    for (const [key, child] of Object.entries(value)) {
      const childPath = path ? `${path}.${key}` : key;
      if (/sign_positions?$/.test(key)) yield { path: childPath, value: child, record: value };
      else yield* positionPaths(child, childPath);
    }
  }
  /** 一處的值裡有幾個合法的位置（單一位置、位置陣列或以名稱為鍵的位置表）。 */
  function positionCount(value) {
    if (readPosition(value)) return 1;
    const entries = Array.isArray(value) ? value : isRecord(value) ? Object.values(value) : [];
    return entries.filter((entry) => readPosition(entry)).length;
  }
  function matchesPattern(pattern, path) {
    if (pattern.endsWith(".**")) return path.startsWith(pattern.slice(0, -2));
    const want = pattern.split(".");
    const have = path.split(".");
    return want.length === have.length && want.every((segment, index) => segment === "*" || segment === have[index]);
  }
  /**
   * 回應裡所有帶黃經的位置怎麼處理：sources 逐處列出（給測試核對），omitted 是頁尾「圖上未畫」
   * 要加上的名稱（不含三組點裡畫不出來的個別點，那些由 readPoints 依名稱列出）。
   */
  function readPositionSources(response, drawnAngles, drawnCusps) {
    const sources = [];
    const omitted = [];
    const add = (name) => { if (!omitted.includes(name)) omitted.push(name); };
    for (const { path, value, record } of positionPaths(response, "")) {
      const count = positionCount(value);
      if (!count) continue;
      const source = POSITION_SOURCES.find(([pattern]) => matchesPattern(pattern, path));
      let treatment = source ? source[1] : undefined;
      let name = null;
      if (treatment === "drawn") {
        if (path === "astronomical_data.angles.sign_positions" && !drawnAngles) name = TEXT.angles;
        if (path === "derived_methods.house_division.cusp_sign_positions" && !drawnCusps) name = TEXT.cusps;
      } else if (typeof treatment === "string") {
        name = treatment;
        treatment = "omitted";
      } else if (treatment === undefined) {
        name = typeof record.name === "string" && record.name ? record.name : UNLISTED_POSITION;
        treatment = "unlisted";
      } else {
        treatment = "same_points";
      }
      if (name) add(name);
      sources.push({ path, count, treatment, name });
    }
    return { sources, omitted };
  }

  // ── 場景：基本圖元。paint 是角色名（bg／band／fg／dim／hair／accent），由各 renderer 決定實際顏色。
  // 屬於某個點的圖元（刻線、引線、四軸線與標記）另帶 linked：那幾個點的後端點鍵，只給結果頁的
  // 圖表連動讀，三個繪製端的幾何與顏色都不讀它。不叫 points：折線與多邊形的 points 是頂點。
  function linePrim(part, a, b, stroke, width, extra = {}) {
    return { type: "line", part, x1: round3(a.x), y1: round3(a.y), x2: round3(b.x), y2: round3(b.y), stroke, width, ...extra };
  }
  function polylinePrim(part, points, stroke, width) {
    return { type: "polyline", part, points: points.map((p) => [round3(p.x), round3(p.y)]), stroke, width };
  }
  function textPrim(part, x, y, content, size, font, fill, extra = {}) {
    return { type: "text", part, x: round3(x), y: round3(y), text: content, size: round3(size), font, fill,
      anchor: "middle", ...extra };
  }
  function glyphPrim(part, key, x, y, size, fill, extra = {}) {
    return { type: "glyph", part, glyph: key, matrix: glyphMatrix(key, x, y, size), fill, ...extra };
  }

  function zodiacRing(reference, text) {
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
    const glyphSize = SIZE.ringGlyph * text;
    const nameSize = SIZE.ringName * text;
    for (let sign = 0; sign < 12; sign += 1) {
      // 符號與中文名並排置中；中文名寬約兩個字。
      const p = at(sign * 30 + 15, G.rSignText);
      const glyphWidth = glyphBox(SIGN_KEYS[sign], glyphSize).w;
      const total = glyphWidth + 3 * text + 2 * nameSize;
      items.push(glyphPrim("sign-glyph", SIGN_KEYS[sign], p.x - total / 2 + glyphWidth / 2, p.y, glyphSize, "fg"));
      items.push(textPrim("sign-name", p.x - total / 2 + glyphWidth + 3 * text, p.y, SIGN_NAMES[sign], nameSize, "sans",
        "dim", { anchor: "start" }));
    }
    return items;
  }

  function houseRing(cusps, reference, preset) {
    const at = (lon, r) => polar(lon - reference, r);
    const rText = (preset.rHouseOut + preset.rHouseIn) / 2;
    const items = [
      { type: "circle", part: "house-ring", cx: G.c, cy: G.c, r: preset.rHouseOut, fill: null, stroke: "dim", width: 0.9 },
      { type: "circle", part: "house-ring", cx: G.c, cy: G.c, r: preset.rHouseIn, fill: null, stroke: "dim", width: 0.9 },
    ];
    cusps.forEach((lon) => {
      items.push(linePrim("house-cusp", at(lon, preset.rHouseIn), at(lon, preset.rHouseOut), "dim", 1));
      items.push(linePrim("house-cusp-extension", at(lon, preset.rHouseOut), at(lon, G.rSignIn), "hair", 0.7, { dash: "2 3" }));
    });
    cusps.forEach((lon, index) => {
      // 宮號放在兩個宮頭之間的中點（圖面位置，不是方法計算）。
      const next = cusps[(index + 1) % 12];
      const p = at(lon + mod360(next - lon) / 2, rText);
      items.push(textPrim("house-number", p.x, p.y, String(index + 1), SIZE.house * preset.text, "mono", "dim"));
    });
    return items;
  }

  function angleAxes(angles, reference, preset) {
    const at = (lon, r) => polar(lon - reference, r);
    const byKey = Object.fromEntries(angles.map((angle) => [angle.key, angle]));
    const items = angles.map((angle) => linePrim("angle-axis", at(angle.lon, G.rOut + 9), at(angle.lon, G.rTickIn), "accent", 1.6,
      { linked: [angle.key] }));
    for (const [from, to] of [["asc", "desc"], ["mc", "ic"]]) {
      if (!byKey[from] || !byKey[to]) continue;
      items.push(linePrim("angle-line", at(byKey[from].lon, preset.rHouseOut), at(byKey[to].lon, preset.rHouseOut), "accent", 1.2,
        { linked: [from, to] }));
    }
    for (const key of ["asc", "mc"]) {
      if (!byKey[key]) continue;
      // 外緣小三角，指向圓心：只標上升與中天兩個起點。
      const t = ((180 + byKey[key].lon - reference) * Math.PI) / 180;
      const tip = at(byKey[key].lon, G.rOut + 1);
      const ux = Math.cos(t);
      const uy = -Math.sin(t);
      const base = { x: tip.x + ux * 10, y: tip.y + uy * 10 };
      items.push({ type: "polygon", part: "angle-marker", fill: "accent", linked: [key], points: [
        [tip.x, tip.y], [base.x - uy * 5, base.y + ux * 5], [base.x + uy * 5, base.y - ux * 5],
      ].map(([x, y]) => [round3(x), round3(y)]) });
    }
    return items;
  }

  /** 一個標籤單位的圖元，依成員分開（每個點一組）。 */
  function unitScene(unit, angle, fs) {
    const halo = 4 * fs;
    const byItem = new Map(unit.members.map((item) => [item, []]));
    for (const part of unitStack(unit, angle, fs).parts) {
      const { item } = part;
      const items = byItem.get(item);
      const colour = item.kind === "angle" ? "accent" : "fg";
      const p = polar(angle, part.r);
      if (part.part === "glyph" && item.kind === "angle") {
        items.push(textPrim("angle-label", p.x, p.y, item.label, part.size, "mono", colour, { halo }));
      } else if (part.part === "glyph") {
        const { glyph: box, mark } = part.box;
        const gx = p.x - part.box.w / 2 + box.w / 2;
        items.push(glyphPrim("label-glyph", item.glyph, gx, p.y, part.size, colour, { halo: halo / (part.size / 1000) }));
        const mx = p.x + part.box.w / 2 - mark / 2;
        if (item.retro) {
          const size = SIZE.mark * fs;
          const markBox = glyphBox("retrograde", size);
          items.push(glyphPrim("label-mark", "retrograde", mx, p.y - box.h / 2 + markBox.h / 2, size, colour,
            { halo: halo / (size / 1000) }));
        } else if (item.suffix) {
          const size = SIZE.suffix * fs;
          items.push(textPrim("label-suffix", mx, p.y + box.h / 2 - size / 2, item.suffix, size, "sans", "dim", { halo }));
        }
      } else if (part.part === "sign") {
        items.push(glyphPrim("label-sign", SIGN_KEYS[item.sign], p.x, p.y, part.size,
          item.kind === "angle" ? colour : "dim", { halo: halo / (part.size / 1000) }));
      } else {
        items.push(textPrim("label-text", p.x, p.y, part.part === "deg" ? item.deg : item.min, part.size, "mono", colour, { halo }));
      }
    }
    return byItem;
  }

  /** 引線：由刻線內端先沿刻線方向走一小段，再斜向標籤外緣；標籤幾乎沒移動時是一條直線。 */
  function leaderPrim(item, angle) {
    const stroke = item.kind === "angle" ? "accent" : "dim";
    const from = polar(item.a, G.rTickIn);
    const to = polar(angle, G.rLabelTop);
    const path = Math.abs(signedGap(item.a, angle)) < 0.5 ? [from, to] : [from, polar(item.a, G.rElbow), to];
    return { ...polylinePrim("leader", path, stroke, 0.8), linked: [item.key] };
  }

  /**
   * 頁尾（圓盤與方盤共用）：notes 與輸入摘要逐行換行，第一行右側有品牌字，換行寬度扣掉它。
   * 回傳頁尾的圖元與整張圖的高度（高度隨行數）。
   */
  function footerLayout(lines, text) {
    const size = SIZE.footer * text;
    const line = SIZE.footerLine * text;
    const wrapped = lines.flatMap((content, index) => wrap(content, size,
      G.width - 2 * G.margin - (index === 0 ? textWidth(TEXT.brand, size) + 12 : 0)));
    const items = wrapped.map((content, index) => textPrim("footer", G.margin, G.footerTop + 22 * text + index * line,
      content, size, "sans", "dim", { anchor: "start" }));
    items.push(textPrim("footer", G.width - G.margin, G.footerTop + 22 * text, TEXT.brand, size, "sans", "dim",
      { anchor: "end" }));
    return { items, height: Math.ceil(G.footerTop + 22 * text + (wrapped.length - 1) * SIZE.footerLine * text + 16 * text) };
  }

  /** 使用者勾選「加印輸入摘要」時的文字行（預設沒有）。 */
  const summaryLines = (options) => (Array.isArray(options.inputSummary)
    ? options.inputSummary.filter((line) => typeof line === "string" && line) : []);
  const roundBox = (box) => ({ x0: round3(box.x0), y0: round3(box.y0), x1: round3(box.x1), y1: round3(box.y1) });

  /** 模型帶 forPreset(preset)：每種字級只算一次（圓盤與方盤共用）。 */
  function withPresets(buildModel, response, options = {}) {
    const model = buildModel(response, options);
    const cache = { [model.preset]: model };
    Object.defineProperty(model, "forPreset", {
      value: (preset) => {
        if (!cache[preset]) cache[preset] = buildModel(response, { ...options, preset });
        return cache[preset];
      },
    });
    return model;
  }

  /**
   * 相位線圖層（chart-wheel-aspects.js）：端點角就是刻線的圖面角，端點圓在宮位環內緣往內 3。
   * 圖層一律算出（相位資料破損時與相位方格一樣失敗）；options.aspects === false 時不放進場景，
   * 其餘圖元與關閉前逐一相同。沒有宮位時另畫一圈細線當端點的基準。
   */
  function aspectLayer(response, items, hasHouses, preset) {
    const aspects = isRecord(response.derived_methods) ? response.derived_methods.aspects : null;
    const geometry = { cx: G.c, cy: G.c, r: preset.rHouseIn - 3 };
    const result = Aspects.build(aspects === undefined ? null : aspects,
      items.map(({ key, a, anchorOnly }) => ({ key, a, anchorOnly: anchorOnly === true })), geometry);
    const group = result.status === Aspects.STATUS.DRAWN
      ? { group: "aspects", items: [
        ...(hasHouses ? [] : [{ type: "circle", part: "aspect-ring", cx: G.c, cy: G.c, r: geometry.r,
          fill: null, stroke: "hair", width: 0.8 }]),
        ...result.group.items,
      ] }
      : null;
    const names = isRecord(aspects) && isRecord(aspects.degree_based) ? aspects.degree_based.aspect_names_zh : null;
    return {
      group,
      summary: { status: result.status, lines: result.lines, omitted: result.omitted, missingPoints: result.missingPoints },
      legend: Aspects.legendLines(result, names),
    };
  }

  /**
   * 回應 → 星盤圖模型。options.inputSummary：使用者勾選「加印輸入摘要」時的文字行（預設沒有）；
   * options.preset：字級（compact／standard／wide，預設 standard）；options.aspects：false 時不畫相位線
   * （預設畫）。
   */
  function build(response, options = {}) {
    if (!isRecord(response)) throw new Error("星盤圖需要一份回應。");
    const presetName = Object.hasOwn(PRESETS, options.preset) ? options.preset : "standard";
    const preset = PRESETS[presetName];
    const { points, omitted, dateOnly } = readPoints(response);
    const houses = readHouses(response);
    const angles = readAngles(response);
    const cusps = readCusps(response);
    const hasAngles = angles.length > 0;
    const reference = hasAngles ? angles[0].lon : 0;
    const positions = readPositionSources(response, hasAngles, Boolean(cusps));
    const notDrawn = [...omitted, ...positions.omitted.filter((name) => !omitted.includes(name))];

    const notes = [
      cusps ? `宮位制：${cusps.text}` : TEXT.noHouses,
      ...(hasAngles ? [TEXT.accent] : [TEXT.noAngles]),
      ...(points.some((point) => point.anchorOnly) ? [TEXT.dateOnly] : []),
      ...(notDrawn.length ? [`圖上未畫：${notDrawn.join("、")}（見表格）`] : []),
    ];
    const foot = footerLayout([...notes, ...summaryLines(options)], preset.text);

    const items = [...points, ...angles].map((item) => ({ ...item, a: mod360(item.lon - reference) }));
    const packed = items.length ? packLabels(items, preset.text, preset.rHouseOut + 3)
      : { units: [], placed: [], boxes: [], fs: preset.text, omitted: { signs: false, shared: false } };
    const anchorOf = new Map();
    packed.units.forEach((unit, index) => unit.members.forEach((item) => anchorOf.set(item, packed.placed[index])));

    const ticks = points.map((point) => linePrim("body-tick", polar(point.lon - reference, G.rSignIn),
      polar(point.lon - reference, G.rTickIn), "fg", 1.8, { ...(point.anchorOnly ? { dash: "2 1.6" } : {}), linked: [point.key] }));
    const leaders = items.map((item) => leaderPrim(item, anchorOf.get(item)));
    const sceneOf = new Map();
    packed.units.forEach((unit, index) => {
      for (const [item, prims] of unitScene(unit, packed.placed[index], packed.fs)) sceneOf.set(item, prims);
    });

    const partnerOf = new Map();
    for (const unit of packed.units) {
      if (unit.members.length === 2) {
        partnerOf.set(unit.members[0], items.indexOf(unit.members[1]));
        partnerOf.set(unit.members[1], items.indexOf(unit.members[0]));
      }
    }
    const asc = angles.find((angle) => angle.key === "asc");
    const aspects = aspectLayer(response, items, Boolean(cusps), preset);
    const showAspects = options.aspects !== false && aspects.group !== null;
    const scene = [
      { group: "zodiac", items: zodiacRing(reference, preset.text) },
      ...(cusps ? [{ group: "houses", items: houseRing(cusps.lons, reference, preset) }] : []),
      // 相位線在宮位之上、四軸之下：紅色四軸壓在線上。
      ...(showAspects ? [aspects.group] : []),
      ...(hasAngles ? [{ group: "angles", items: angleAxes(angles, reference, preset) }] : []),
      { group: "markers", items: [...ticks, ...leaders] },
      // 共用一條標籤的兩點各自一組（順序與 labels 相同），都加 shared 標記；頁面版以 class
      // cw-label-shared 標出，另一點的索引在 labels[].sharedWith。
      { group: "labels", children: items.map((item) => ({
        group: "label", items: sceneOf.get(item), ...(partnerOf.has(item) ? { shared: true } : {}),
      })) },
      { group: "footer", items: foot.items },
    ];
    return {
      width: G.width,
      height: foot.height,
      preset: presetName,
      center: { x: G.c, y: G.c },
      frame: hasAngles ? "ascendant" : "aries",
      ariaLabel: asc
        ? `星盤圖：上升 ${SIGN_NAMES[asc.sign]} ${asc.deg}${asc.min}；各天體位置見下方表格`
        : "星盤圖：本次沒有軸點，牡羊 0° 置於左方；各天體位置見下方表格",
      notes,
      dateOnly,
      // 相位線：status（閉集，見 chart-wheel-aspects.js）、畫了與未畫的線；shown 是這一份場景有沒有畫。
      aspects: { ...aspects.summary, shown: showAspects },
      aspectLegend: aspects.legend,
      compaction: packed.omitted,
      positionSources: positions.sources,
      scene,
      labels: items.map((item, index) => ({
        key: item.key, kind: item.kind, sign: item.sign,
        // 符號對照：名稱（與表格第一欄同字）、符號、度與分（與標籤同一個切段）、位置文字、逆行、宮號（沒有落宮時 null）。
        name: item.name, glyph: item.glyph, suffix: item.suffix, deg: item.deg, min: item.min, retro: item.retro,
        position: `${SIGN_NAMES[item.sign]} ${item.deg}${item.min}`,
        house: houses.has(item.key) ? houses.get(item.key) : null,
        anchor: round3(anchorOf.get(item)), tick: round3(item.a),
                // sharedWith：共用同一條標籤的另一點在 labels 裡的索引。
        signShown: !item.omitSign, sharedWith: partnerOf.has(item) ? partnerOf.get(item) : null,
        boxes: packed.boxes[index].map(roundBox),
      })),
    };
  }

  // 方盤（chart-square.js）沿用的讀回應、量字、圖元與頁尾：同一套點鍵、同一條「圖上未畫」規則、同一種場景，
  // 不另寫一份。
  const shared = Object.freeze({
    readPosition, readPoints, readAngles, readHouses, readPositionSources, glyphBox, monoBox,
    textWidth, wrap, round3, mod360, isRecord, SIGN_KEYS, SIGN_NAMES,
    linePrim, textPrim, glyphPrim, footerLayout, summaryLines, roundBox, withPresets,
  });

  return Object.freeze({
    build, presetForWidth, PRESETS: Object.keys(PRESETS), POINTS, TEXT, ASPECT_STATUS: Aspects.STATUS, shared,
  });
});
