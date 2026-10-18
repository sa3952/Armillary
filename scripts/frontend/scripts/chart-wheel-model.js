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
    ["derived_methods.dodecatemoria.profile_results.*.points[].sign_position", "十二分部"],
    ["derived_methods.dodecatemoria.profile_results.*.points[].point_sign_position", "十二分部"],
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
  // folio：符號一層、度星座分合成一行（line）一層。
  const FOLIO_PARTS = Object.freeze(["glyph", "line"]);
  const SIZE = Object.freeze({
    glyph: 24, deg: 16, sign: 14, min: 14, angle: 13, mark: 13, suffix: 11,
    folioGlyph: 26, folioAngle: 14, line: 14.6, lineSign: 14.6,
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

  // ── 標籤樣式
  //   classic：徑向四段堆疊（符號→度→星座→分）、等寬數字、符號依 em 等比；方盤（chart-square.js）沿用。
  //   folio（圓盤）：符號在外、一行「9°♋29′」在內（全圖兩種字級）、符號依墨框做光學正規化、數字用
  //          拉丁襯線、宮位環外擴讓相位圈變大、中心留空圓；不確定的位置畫成範圍（只知日期的月亮、
  //          約略小時的上升）。
  const FOLIO_PRESETS = Object.freeze({
    compact: Object.freeze({ text: 1.2, rHouseOut: 104, rHouseIn: 86 }),
    standard: Object.freeze({ text: 1, rHouseOut: 126, rHouseIn: 104 }),
    wide: Object.freeze({ text: 0.86, rHouseOut: 136, rHouseIn: 114 }),
  });
  const LABEL_STYLES = Object.freeze({
    classic: Object.freeze({ optical: false, numFont: "mono", layout: "radial", disc: false, uncertainty: null, presets: null }),
    folio: Object.freeze({ optical: true, numFont: "serif", layout: "folio", disc: true, uncertainty: "hatch", presets: FOLIO_PRESETS }),
  });
  let S = LABEL_STYLES.classic;   // 方盤讀 shared 時一律是 classic；圓盤 build 期間才換成 folio。

  // 光學正規化：同一個字級下，每個符號墨框的長邊一樣長（em 等比時 ♂ 只有 ☉ 的七成高）。
  // 圓形的 ☉ 看起來比同高的折線符號大，再收一點。
  const OPTICAL_EXTENT = 0.74;
  const OPTICAL_TRIM = Object.freeze({ sun: 0.9, north_node: 0.94, south_node: 0.94, aquarius: 1.06 });
  function glyphScale(key, size) {
    const [x0, y0, x1, y1] = Glyphs.GLYPHS[key].bbox;
    if (!S.optical) return size / Glyphs.UNITS_PER_EM;
    return (size * OPTICAL_EXTENT * (OPTICAL_TRIM[key] || 1)) / Math.max(x1 - x0, y1 - y0);
  }

  // 星盤數字（--serif-num）的字寬與字框高（em），取堆疊裡最大的：Palatino 數字 .5、° .4、′ .22、
  // 行框 1.10；Times New Roman 與同字寬的 Liberation Serif 數字 .5、行框約 1.11–1.15；只有退到 DejaVu Serif 時數字約 .64。
  // 字框高是瀏覽器 getBoundingClientRect 量到的行框，不是墨高：相鄰標籤的字框不相交，真實版面才不相撞。
  const SERIF_ADVANCE = Object.freeze({ digit: 0.58, "°": 0.42, "′": 0.3, upper: 0.72, other: 0.6 });
  const SERIF_HEIGHT = 1.15;
  function serifBox(text, size) {
    let w = 0;
    for (const char of text) {
      w += /\d/.test(char) ? SERIF_ADVANCE.digit : char === "°" || char === "′" ? SERIF_ADVANCE[char]
        : /[A-Z]/.test(char) ? SERIF_ADVANCE.upper : SERIF_ADVANCE.other;
    }
    return { w: w * size, h: size * SERIF_HEIGHT };
  }
  const numBox = (text, size) => (S.numFont === "serif" ? serifBox(text, size) : monoBox(text, size));

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
    const s = glyphScale(key, size);
    return [round3(s), 0, 0, round3(s), round3(x - (s * (x0 + x1)) / 2), round3(y - (s * (y0 + y1)) / 2)];
  }
  function glyphBox(key, size) {
    const [x0, y0, x1, y1] = Glyphs.GLYPHS[key].bbox;
    const s = glyphScale(key, size);
    return { w: (x1 - x0) * s, h: (y1 - y0) * s };
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
  function partSize(item, part, fs, radial = false) {
    const folio = S.layout === "folio" && !radial;
    if (part === "glyph") {
      return (item.kind === "angle" ? (folio ? SIZE.folioAngle : SIZE.angle) : (folio ? SIZE.folioGlyph : SIZE.glyph)) * fs;
    }
    // folio 的徑向退路（攤不開的群）與一行字同一個字級：全圖仍只有兩種字級。
    if (S.layout === "folio" && (part === "deg" || part === "min")) return SIZE.line * fs;
    return SIZE[part] * fs;
  }
  /** folio 的一行：度、（星座）、分，各自的寬與在行內的中心（相對行中心）。 */
  function lineLayout(item, fs) {
    const size = SIZE.line * fs;
    const gap = 0.7 * fs;
    const deg = numBox(item.deg, size);
    const min = numBox(item.min, size);
    const sign = item.omitSign ? null : glyphBox(SIGN_KEYS[item.sign], SIZE.lineSign * fs);
    const w = deg.w + min.w + (sign ? sign.w + 2 * gap : gap);
    const h = Math.max(deg.h, sign ? sign.h : 0);
    const degX = -w / 2 + deg.w / 2;
    const signX = sign ? -w / 2 + deg.w + gap + sign.w / 2 : null;
    const minX = w / 2 - min.w / 2;
    return { w, h, size, degX, signX, minX };
  }
  function partBox(item, part, fs, radial = false) {
    const size = partSize(item, part, fs, radial);
    if (part === "line") {
      const line = lineLayout(item, fs);
      return { w: line.w, h: line.h, line };
    }
    if (part === "glyph") {
      if (item.kind === "angle") return numBox(item.label, size);
      const glyph = glyphBox(item.glyph, size);
      const mark = item.retro ? glyphBox("retrograde", SIZE.mark * fs).w
        : item.suffix ? textWidth(item.suffix, SIZE.suffix * fs) : 0;
      return { w: glyph.w + (mark ? 1.5 * fs + mark : 0), h: glyph.h, glyph, mark };
    }
    if (part === "sign") return glyphBox(SIGN_KEYS[item.sign], size);
    return numBox(part === "deg" ? item.deg : item.min, size);
  }
  /** 單位在圖面角 a 上的徑向堆疊：每個元素的中心半徑與切向寬度；inner 是堆疊內緣的半徑。 */
  function unitStack(unit, a, fs) {
    const t = ((180 + a) * Math.PI) / 180;
    const c = Math.abs(Math.cos(t));
    const s = Math.abs(Math.sin(t));
    let r = unit.top || G.rLabelTop;
    const parts = [];
    unit.members.forEach((item, row) => {
      for (const part of S.layout === "folio" && !unit.radial ? FOLIO_PARTS : PARTS) {
        if (part === "sign" && item.omitSign) continue;
        const box = partBox(item, part, fs, unit.radial);
        const radial = box.w * c + box.h * s;
        if (parts.length) r -= (row && part === "glyph" ? ROW_GAP : PART_GAP) * fs;
        parts.push({ item, part, size: partSize(item, part, fs, unit.radial), box, r: r - radial / 2,
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
  // folio 的扇形展開：一群標籤裡相鄰的兩個交錯放在內外兩層（各自一條引線），切向只需要約一半的寬度，
  // 群聚因此不必縮字。只在兩層都放得下（標籤的徑向深度小，也就是一行字橫躺的上下兩側）時交錯。
  const TIER_SHARE = 0.55;
  const TIER_GAP = 7;   // 內外兩層之間的徑向留白：內層的引線終點不會比外層的字框更靠近別人
  function stackDepth(unit, a, fs) {
    const top = unit.top;
    unit.top = undefined;
    const depth = G.rLabelTop - unitStack(unit, a, fs).inner;
    unit.top = top;
    return depth;
  }
  function tierable(unit, a, fs, floor) {
    return S.layout === "folio" && !unit.radial && unit.members.length === 1
      && G.rLabelTop - 2 * stackDepth(unit, a, fs) - TIER_GAP * fs >= floor;
  }
  const tierFactor = (unit, a, fs, floor) => (tierable(unit, a, fs, floor) ? TIER_SHARE : 1);
  /** 每一群裡連續可交錯的標籤，依圓周順序一外一內；內層的外緣在這一段外層最深處再往內 TIER_GAP。 */
  function assignTiers(units, groups, placed, fs, floor) {
    for (const unit of units) unit.top = undefined;
    for (const group of groups) {
      let run = [];
      const flush = () => {
        if (run.length > 1) {
          const depth = Math.max(...run.map((index) => stackDepth(units[index], placed[index], fs)));
          run.forEach((index, k) => { if (k % 2) units[index].top = G.rLabelTop - depth - TIER_GAP * fs; });
        }
        run = [];
      };
      for (const index of group) {
        if (tierable(units[index], placed[index], fs, floor)) run.push(index);
        else flush();
      }
      flush();
    }
  }

  function arrange(items, fs, padFactor, floor, radial = new Set()) {
    for (const item of items) item.omitSign = false;
    const order = items.map((item, index) => ({ index, a: item.a })).sort((p, q) => p.a - q.a || p.index - q.index)
      .map((entry) => entry.index);
    // 共用標籤只在放得下（堆疊不壓到宮位環）時成立；共用標籤裡同星座的第二點不印星座。
    let units = shareUnits(items, order).map((unit) => ({ ...unit, radial: unit.members.some((item) => radial.has(item)) }))
      .flatMap((unit) => {
      if (unit.members.length === 1) return [unit];
      unit.members[1].omitSign = unit.members[1].sign === unit.members[0].sign;
      if (fits(unit, unit.a, fs, floor)) return [unit];
      unit.members[1].omitSign = false;
      return unit.members.map((item) => ({ members: [item], a: item.a, radial: unit.radial }));
    });
    let hw;
    let layout;
    // 每拆開一條放不下的共用標籤就重排一次；共用標籤只會越來越少，所以一定會停。
    for (;;) {
      hw = units.map((unit) => halfWidth(unit, unit.a, fs) * padFactor * tierFactor(unit, unit.a, fs, floor));
      layout = layoutLabels(units.map((unit) => unit.a), hw);
      // 切向寬度依位置而變：在排好的位置上重量一次，取較大者再排一次。
      hw = units.map((unit, index) => Math.max(hw[index], halfWidth(unit, layout.placed[index], fs) * padFactor
        * tierFactor(unit, layout.placed[index], fs, floor)));
      layout = layoutLabels(units.map((unit) => unit.a), hw);
      const split = units.findIndex((unit, index) => unit.members.length > 1 && !fits(unit, layout.placed[index], fs, floor));
      if (split < 0) break;
      units[split].members[1].omitSign = false;
      units = [...units.slice(0, split), ...units[split].members.map((item) => ({ members: [item], a: item.a,
        radial: units[split].radial })),
        ...units.slice(split + 1)];
    }
    // 擠在一起（同一群裡相鄰）的天體標籤，與前一個標籤同星座就不再印星座；四軸照印、也打斷連續。
    const sameSignAsPrevious = (previous, unit) => previous.members[0].kind === "body" && unit.members[0].kind === "body"
      && previous.members[previous.members.length - 1].sign === unit.members[0].sign;
    // folio 的一行標籤一律印星座：省掉會在「24° 10′」中間留一個洞，讀起來像缺字。
    for (const group of S.layout === "folio" ? [] : layout.groups) {
      for (let k = 1; k < group.length; k += 1) {
        if (sameSignAsPrevious(units[group[k - 1]], units[group[k]])) units[group[k]].members[0].omitSign = true;
      }
    }
    hw = units.map((unit, index) => halfWidth(unit, layout.placed[index], fs) * padFactor
      * tierFactor(unit, layout.placed[index], fs, floor));
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
    hw = units.map((unit, index) => Math.max(hw[index], halfWidth(unit, layout.placed[index], fs) * padFactor
      * tierFactor(unit, layout.placed[index], fs, floor)));
    const placed = keepInSigns(units, layout, hw);
    if (S.layout === "folio") assignTiers(units, layout.groups, placed, fs, floor);
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
    return { units, placed, fs, groups: layout.groups, boxes: items.map((item) => boxes.get(item)), fitsAll,
      omitted: { signs: items.some((item) => item.omitSign), shared: units.some((unit) => unit.members.length > 1) } };
  }

  // folio 的一行字比徑向堆疊寬；一群標籤要攤開超過 FAN_LIMIT 度才放得下時，那一群改用徑向堆疊
  // （窄、深），引線不必拉得那麼長。其餘的群維持 folio。
  const FAN_LIMIT = 20;
  function arrangeFolio(items, fs, padFactor, floor) {
    let radial = new Set();
    let result = arrange(items, fs, padFactor, floor, radial);
    if (S.layout !== "folio") return result;
    for (;;) {
      const next = new Set(radial);
      for (const group of result.groups) {
        const far = group.some((index) => Math.abs(signedGap(result.units[index].a, result.placed[index])) > FAN_LIMIT);
        if (far) for (const index of group) for (const item of result.units[index].members) next.add(item);
      }
      if (next.size === radial.size) return result;
      // 徑向堆疊較深；放不下（壓到宮位環）時由 packLabels 換小一號——只有攤不開的群才走到這一步。
      radial = next;
      result = arrange(items, fs, padFactor, floor, radial);
    }
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
  // folio：攤開（含徑向退路）之後，標籤離刻線仍超過這個角度才縮字——縮字是最後一步。
  const FAN_CAP = Object.freeze({ compact: 40, standard: 28, wide: 21 });
  const maxAway = (result) => Math.max(0, ...result.units.map((unit, index) => Math.abs(signedGap(unit.a, result.placed[index]))));
  function packLabels(items, text, floor, presetName) {
    let fallback = null;
    const cap = S.layout === "folio" ? FAN_CAP[presetName] : Infinity;
    for (const scale of LABEL_SCALES) {
      let padFactor = 1;
      for (let attempt = 0; attempt < 6; attempt += 1) {
        const result = arrangeFolio(items, text * scale, padFactor, floor);
        fallback = result;
        // 堆疊壓到宮位環是字太大，加大留白沒有用：直接換小一號。
        if (!result.fitsAll) break;
        if (!anyOverlap(result.boxes)) {
          if (maxAway(result) <= cap || scale === LABEL_SCALES[LABEL_SCALES.length - 1]) return result;
          break;
        }
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
      items.push(textPrim("house-number", p.x, p.y, String(index + 1), SIZE.house * preset.text, S.numFont, "dim"));
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
        items.push(textPrim("angle-label", p.x, p.y, item.label, part.size, S.numFont, colour, { halo }));
      } else if (part.part === "glyph") {
        const { glyph: box, mark } = part.box;
        const gx = p.x - part.box.w / 2 + box.w / 2;
        items.push(glyphPrim("label-glyph", item.glyph, gx, p.y, part.size, colour, { halo: halo / glyphScale(item.glyph, part.size) }));
        const mx = p.x + part.box.w / 2 - mark / 2;
        if (item.retro) {
          const size = SIZE.mark * fs;
          const markBox = glyphBox("retrograde", size);
          items.push(glyphPrim("label-mark", "retrograde", mx, p.y - box.h / 2 + markBox.h / 2, size, colour,
            { halo: halo / glyphScale("retrograde", size) }));
        } else if (item.suffix) {
          const size = SIZE.suffix * fs;
          items.push(textPrim("label-suffix", mx, p.y + box.h / 2 - size / 2, item.suffix, size, "sans", "dim", { halo }));
        }
      } else if (part.part === "sign") {
        items.push(glyphPrim("label-sign", SIGN_KEYS[item.sign], p.x, p.y, part.size,
          item.kind === "angle" ? colour : "dim", { halo: halo / glyphScale(SIGN_KEYS[item.sign], part.size) }));
      } else if (part.part === "line") {
        // 一行「度 星座 分」：數字與星座同一條中線；星座用淡墨，四軸整行用重點色。
        const { line } = part.box;
        items.push(textPrim("label-text", p.x + line.degX, p.y, item.deg, line.size, S.numFont, colour, { halo }));
        if (line.signX !== null) {
          const size = SIZE.lineSign * fs;
          items.push(glyphPrim("label-sign", SIGN_KEYS[item.sign], p.x + line.signX, p.y, size,
            item.kind === "angle" ? colour : "dim", { halo: halo / glyphScale(SIGN_KEYS[item.sign], size) }));
        }
        items.push(textPrim("label-text", p.x + line.minX, p.y, item.min, line.size, S.numFont, colour, { halo }));
      } else {
        items.push(textPrim("label-text", p.x, p.y, part.part === "deg" ? item.deg : item.min, part.size, S.numFont, colour, { halo }));
      }
    }
    return byItem;
  }

  /** 引線：由刻線內端先沿刻線方向走一小段，再斜向標籤外緣；標籤幾乎沒移動時是一條直線。 */
  function leaderPrim(item, angle, top) {
    const stroke = item.kind === "angle" ? "accent" : "dim";
    const from = polar(item.a, G.rTickIn);
    const to = polar(angle, top || G.rLabelTop);
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
        // 中心留一個空圓：對沖線經過圓心時不在中央打結。
        ...(S.disc ? [{ type: "circle", part: "aspect-clear", cx: G.c, cy: G.c, r: round3(geometry.r * 0.2),
          fill: "bg", stroke: "hair", width: 0.8 }] : []),
      ] }
      : null;
    const names = isRecord(aspects) && isRecord(aspects.degree_based) ? aspects.degree_based.aspect_names_zh : null;
    return {
      group,
      summary: { status: result.status, lines: result.lines, omitted: result.omitted, missingPoints: result.missingPoints },
      legend: Aspects.legendLines(result, names),
    };
  }

  // ── 不確定的位置畫成範圍（folio）：只讀回應的出生時刻敏感度，不另算。
  //   只知日期：月亮在當天取樣到的黃經範圍（position_ranges[moon].sampled_longitude_envelope）；
  //   約略小時：上升在這一小時取樣到的範圍（angles.asc）。範圍是取樣點的包絡，不是連續解。
  const RANGE_TEXT = Object.freeze({
    moon: "斜線弧：月亮當天取樣到的位置範圍", asc: "斜線扇形：上升在這一小時內取樣到的範圍",
  });
  const CENTRE_NOTE = Object.freeze(["只知日期", "沒有宮位"]);
  // 回應少了這些端點時，與表格一樣以 response_incomplete 拒絕（不畫成一個確定的點、也不默默略過範圍）。
  function incomplete(detail) {
    const error = new Error(`回應結構不完整：缺少 ${detail}，星盤圖不能畫出不確定的範圍。`);
    error.code = "response_incomplete";
    return error;
  }
  function readEnvelope(envelope, path) {
    if (!isRecord(envelope)) throw incomplete(path);
    const { start_degrees: start, end_degrees: end } = envelope;
    for (const [key, value] of [["start_degrees", start], ["end_degrees", end]]) {
      if (typeof value !== "number" || !Number.isFinite(value)) throw incomplete(`${path}.${key}`);
    }
    const span = mod360(end - start);
    // 範圍跨過半圈就不是「一段弧」，不畫（不猜方向）；取樣全落在同一點也不畫。
    return span > 0 && span < 180 ? { start, span } : null;
  }
  function readRanges(response) {
    const sensitivity = isRecord(response.birth_time_sensitivity) ? response.birth_time_sensitivity : null;
    if (!sensitivity || sensitivity.status !== "computed") return {};
    const base = "birth_time_sensitivity";
    const out = {};
    if (sensitivity.precision === "date_only") {
      if (!Array.isArray(sensitivity.position_ranges)) throw incomplete(`${base}.position_ranges`);
      const moon = sensitivity.position_ranges.find((entry) => isRecord(entry) && entry.key === "moon");
      if (!moon) throw incomplete(`${base}.position_ranges[moon]`);
      const range = readEnvelope(moon.sampled_longitude_envelope, `${base}.position_ranges[moon].sampled_longitude_envelope`);
      if (range) out.moon = range;
    }
    // 上升的範圍只在有宮位（angles 是包絡而不是未請求的收據）時存在。
    if (sensitivity.precision === "approximate_hour" && isRecord(sensitivity.angles)
      && Object.hasOwn(sensitivity.angles, "asc")) {
      const range = readEnvelope(sensitivity.angles.asc, `${base}.angles.asc`);
      if (range) out.asc = range;
    }
    return out;
  }
  function arcPath(from, span, r) {
    const p = polar(from, r);
    const q = polar(from + span, r);
    return `M ${round3(p.x)} ${round3(p.y)} A ${r} ${r} 0 ${span > 180 ? 1 : 0} 0 ${round3(q.x)} ${round3(q.y)}`;
  }
  /** 一段弧帶：外框（兩條弧、兩條徑向邊）加斜線排線，排線只留在帶內。 */
  function hatchedBand(part, from, span, rIn, rOut, linked) {
    const items = [];
    const step = 1.4;
    for (let t = 0; t + 1 <= span + 1e-9; t += step) {
      items.push(linePrim(`${part}-hatch`, polar(from + t, rIn), polar(from + Math.min(span, t + 1), rOut), "dim", 0.6, { linked }));
    }
    const a = polar(from, rIn);
    const b = polar(from + span, rIn);
    items.push({ type: "path", part: `${part}-edge`, stroke: "fg", width: 0.9, linked,
      d: `${arcPath(from, span, rOut)} L ${round3(b.x)} ${round3(b.y)} `
        + `A ${rIn} ${rIn} 0 ${span > 180 ? 1 : 0} 1 ${round3(a.x)} ${round3(a.y)} Z` });
    return items;
  }
  function rangeLayer(ranges, reference, preset, hasHouses) {
    const items = [];
    const notes = [];
    for (const key of ["moon", "asc"]) {
      const range = ranges[key];
      if (!range) continue;
      const from = range.start - reference;
      items.push(...hatchedBand(`range-${key}`, from, range.span, G.rTickIn, G.rSignIn, [key]));
      if (key === "asc") {
        // 扇形的兩條邊：由宮位環外緣到星座環內緣的虛細線。
        for (const angle of [from, from + range.span]) {
          items.push(linePrim("range-asc-side", polar(angle, preset.rHouseOut), polar(angle, G.rTickIn), "dim", 0.7,
            { dash: "1.5 2", linked: ["asc"] }));
        }
      }
      notes.push(RANGE_TEXT[key]);
    }
    if (ranges.moon && !hasHouses) {
      // 沒有宮位：淡化的宮位環＋中心一句小字，而不是空著的中心。
      for (const r of [preset.rHouseOut, preset.rHouseIn]) {
        items.push({ type: "circle", part: "house-ghost", cx: G.c, cy: G.c, r, fill: null, stroke: "hair", width: 0.8, dash: "2 3" });
      }
    }
    return { items, notes };
  }
  function centreNote(preset) {
    const size = SIZE.house * preset.text * 0.92;
    const r = Math.max(preset.rHouseIn * 0.34, size * 2.6);
    return [
      { type: "circle", part: "centre-note-disc", cx: G.c, cy: G.c, r: round3(r), fill: "bg", stroke: "hair", width: 0.8 },
      ...CENTRE_NOTE.map((line, index) => textPrim("centre-note", G.c, G.c + (index - 0.5) * size * 1.35, line, size, "book", "dim")),
    ];
  }

  /**
   * 回應 → 星盤圖模型。options.inputSummary：使用者勾選「加印輸入摘要」時的文字行（預設沒有）；
   * options.preset：字級（compact／standard／wide，預設 standard）；options.aspects：false 時不畫相位線
   * （預設畫）。
   */
  function build(response, options = {}) {
    const previous = S;
    S = LABEL_STYLES.folio;
    try {
      return buildWith(response, options);
    } finally {
      S = previous;
    }
  }

  function buildWith(response, options) {
    if (!isRecord(response)) throw new Error("星盤圖需要一份回應。");
    const presetName = Object.hasOwn(PRESETS, options.preset) ? options.preset : "standard";
    const preset = (S.presets || PRESETS)[presetName];
    const { points, omitted, dateOnly } = readPoints(response);
    const houses = readHouses(response);
    const angles = readAngles(response);
    const cusps = readCusps(response);
    const hasAngles = angles.length > 0;
    const reference = hasAngles ? angles[0].lon : 0;
    const positions = readPositionSources(response, hasAngles, Boolean(cusps));
    const notDrawn = [...omitted, ...positions.omitted.filter((name) => !omitted.includes(name))];

    const ranges = S.uncertainty ? readRanges(response) : {};
    const range = S.uncertainty ? rangeLayer(ranges, reference, preset, Boolean(cusps)) : { items: [], notes: [] };
    const notes = [
      cusps ? `宮位制：${cusps.text}` : TEXT.noHouses,
      ...(hasAngles ? [TEXT.accent] : [TEXT.noAngles]),
      ...(points.some((point) => point.anchorOnly) ? [TEXT.dateOnly] : []),
      ...range.notes,
      ...(notDrawn.length ? [`圖上未畫：${notDrawn.join("、")}（見表格）`] : []),
    ];
    const foot = footerLayout([...notes, ...summaryLines(options)], preset.text);

    const items = [...points, ...angles].map((item) => ({ ...item, a: mod360(item.lon - reference) }));
    const packed = items.length ? packLabels(items, preset.text, preset.rHouseOut + 3, presetName)
      : { units: [], placed: [], boxes: [], fs: preset.text, omitted: { signs: false, shared: false } };
    const anchorOf = new Map();
    packed.units.forEach((unit, index) => unit.members.forEach((item) => anchorOf.set(item, packed.placed[index])));
    const topOf = new Map();
    packed.units.forEach((unit) => unit.members.forEach((item) => topOf.set(item, unit.top)));

    const ticks = points.map((point) => linePrim("body-tick", polar(point.lon - reference, G.rSignIn),
      polar(point.lon - reference, G.rTickIn), "fg", 1.8, { ...(point.anchorOnly ? { dash: "2 1.6" } : {}), linked: [point.key] }));
    const leaders = items.map((item) => leaderPrim(item, anchorOf.get(item), topOf.get(item)));
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
      ...(range.items.length ? [{ group: "ranges", items: range.items }] : []),
      ...(ranges.moon && !cusps ? [{ group: "centre", items: centreNote(preset) }] : []),
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
