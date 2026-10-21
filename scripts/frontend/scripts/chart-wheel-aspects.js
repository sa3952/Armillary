(function attachChartWheelAspects(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ChartWheelAspects = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildChartWheelAspects() {
  "use strict";

  // 星盤圖的相位線圖層：純函式，不碰 DOM。輸出與 chart-wheel-model.js 場景相同的圖元
  // （line／circle，加上一種 path），頁面 SVG、下載 SVG 與 Canvas 都能直接畫。
  //
  // 線只由回應的 derived_methods.aspects.pairs 產生，這裡不算任何角距：
  //   - 一條線＝一個 pair 的一個 aspect_target，且該 target 的 in_orb 為 true——與結果頁「相位方格」
  //     列出的格子是同一個條件；整宮配置（whole_sign）不畫，in_orb 為 null（沒有容許度判定）也不畫；
  //   - 線的兩端放在兩個點在圖上的角度，角度由呼叫端給（星盤圖模型對每個點算好的圖面角，
  //     與刻線同一個值），這裡只把角度放到圓上。
  // 端點不在圖上（例如命運點）、或端點只是錨點（只有日期時的月亮）的線不畫，列在 omitted，
  // 由呼叫端說明；不在樣式表的相位鍵同樣列出，不猜樣式。

  const STATUS = Object.freeze({
    NOT_REQUESTED: "not_requested",        // 本次沒有相位模組（容器為 null）
    NOT_AVAILABLE: "not_available",        // 模組有請求但沒有結果（例如日心盤不適用），原因見相位區
    ORB_NOT_SELECTED: "orb_not_selected",  // 沒有容許度判定，沒有線可畫
    NONE_IN_ORB: "none_in_orb",            // 有判定，但沒有可畫的線
    DRAWN: "drawn",
  });
  const OMIT_REASON = Object.freeze({
    ENDPOINT_NOT_DRAWN: "endpoint_not_drawn",
    ENDPOINT_ANCHOR_ONLY: "endpoint_anchor_only",
    STYLE_UNKNOWN: "aspect_style_unknown",
  });

  // 端點所在的圓：預設是宮位環內緣（半徑 90）往內 3。接上星盤圖時由模型給。
  const DEFAULT_GEOMETRY = Object.freeze({ cx: 300, cy: 300, r: 87 });

  // 線型：每種相位一種虛線樣式，顏色只有一種（paint 角色 "aspect"），所以分辨相位不靠顏色。
  // 寬度相同，不按原典的「和諧／不和諧」（Ptolemy I.13）分組加粗或換色：線型只是畫法，性質寫在方法頁。同度（partile）加粗。
  // 現代小相位共用一種細點線；名稱見相位方格。
  const WIDTH = 1.2;
  const PARTILE_WIDTH = 2.4;
  const MINOR = Object.freeze({ pattern: "minor", dash: "0.8 2", width: 0.8 });
  const STYLES = Object.freeze({
    conjunction: Object.freeze({ pattern: "bracket", dash: null, width: 1.6 }),
    opposition: Object.freeze({ pattern: "long_dash", dash: "9 3", width: WIDTH }),
    square: Object.freeze({ pattern: "short_dash", dash: "4 2.5", width: WIDTH }),
    trine: Object.freeze({ pattern: "solid", dash: null, width: WIDTH }),
    sextile: Object.freeze({ pattern: "dotted", dash: "1.2 2.4", width: WIDTH }),
    semisextile: MINOR, semisquare: MINOR, sesquiquadrate: MINOR,
    quincunx: MINOR, quintile: MINOR, biquintile: MINOR,
  });
  const PATTERN_ZH = Object.freeze({
    long_dash: "長虛線", short_dash: "短虛線", solid: "實線", dotted: "點線",
    bracket: "內圈的括弧", minor: "細點線",
  });

  // 合相的兩端幾乎重疊，畫成貼著內圈的括弧：兩端各一段往內的短線，以弧相連。所有括弧同一個深度：
  // 星群裡互相重疊的括弧合成一段弧帶，只說「這幾點彼此合相」；哪兩點見相位方格。
  // （逐層往內排過：七星群聚時疊成十一層、深 45，讀不出來。）
  const BRACKET_DEPTH = 6;
  const ANCHOR_RADIUS = 1.8;

  const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const mod360 = (value) => ((value % 360) + 360) % 360;
  const round3 = (value) => {
    const rounded = Math.round(value * 1000) / 1000;
    return rounded === 0 ? 0 : rounded;
  };

  /** 圖面角（相對參考點、逆時針，度）→ 座標；與星盤圖模型的 polar 同一個約定（上升在 9 點鐘）。 */
  function polar(geometry, angle, r) {
    const t = ((180 + angle) * Math.PI) / 180;
    return { x: geometry.cx + r * Math.cos(t), y: geometry.cy - r * Math.sin(t) };
  }

  function readPoints(points) {
    const byKey = new Map();
    for (const point of points || []) {
      if (!isRecord(point) || typeof point.key !== "string") continue;
      if (typeof point.a !== "number" || !Number.isFinite(point.a)) continue;
      byKey.set(point.key, { a: mod360(point.a), anchorOnly: point.anchorOnly === true });
    }
    return byKey;
  }

  function chordItem(geometry, line, style) {
    const p = polar(geometry, line.angleA, geometry.r);
    const q = polar(geometry, line.angleB, geometry.r);
    return {
      type: "line", part: `aspect-${line.aspect}`,
      x1: round3(p.x), y1: round3(p.y), x2: round3(q.x), y2: round3(q.y),
      stroke: "aspect", width: line.partile ? PARTILE_WIDTH : style.width,
      ...(style.dash ? { dash: style.dash } : {}),
    };
  }

  function bracketItem(geometry, line, style) {
    // 由角度較小的一端，逆時針走較短的弧到另一端。
    const delta = mod360(line.angleB - line.angleA);
    const [from, to] = delta <= 180 ? [line.angleA, line.angleB] : [line.angleB, line.angleA];
    const inner = geometry.r - BRACKET_DEPTH;
    const outerFrom = polar(geometry, from, geometry.r);
    const innerFrom = polar(geometry, from, inner);
    const innerTo = polar(geometry, to, inner);
    const outerTo = polar(geometry, to, geometry.r);
    const pt = (point) => `${round3(point.x)} ${round3(point.y)}`;
    // SVG 的 y 向下：螢幕上逆時針是 sweep-flag 0。
    return {
      type: "path", part: `aspect-${line.aspect}`,
      d: `M ${pt(outerFrom)} L ${pt(innerFrom)} A ${round3(inner)} ${round3(inner)} 0 0 0 ${pt(innerTo)} L ${pt(outerTo)}`,
      stroke: "aspect", width: line.partile ? PARTILE_WIDTH : style.width,
    };
  }

  /**
   * aspects：回應的 derived_methods.aspects（頁面投影即可）；null／undefined＝本次沒有相位。
   * points：圖上每個點 { key, a（圖面角，度）, anchorOnly }，與刻線同一個角度。
   * geometry：{ cx, cy, r }，端點所在的圓。
   */
  function build(aspects, points, geometry = DEFAULT_GEOMETRY) {
    const empty = (status) => ({
      status, lines: [], omitted: [], missingPoints: [], group: { group: "aspects", items: [] },
    });
    if (aspects === null || aspects === undefined) return empty(STATUS.NOT_REQUESTED);
    if (!isRecord(aspects) || !Array.isArray(aspects.pairs)) {
      throw new Error("相位資料缺少 pairs，無法畫相位線。");
    }
    if (aspects.available === false) return empty(STATUS.NOT_AVAILABLE);
    const participants = new Set((Array.isArray(aspects.participants) ? aspects.participants : [])
      .filter((item) => isRecord(item) && typeof item.key === "string").map((item) => item.key));
    const byKey = readPoints(points);

    const lines = [];
    const omitted = [];
    const missing = new Map();
    for (const pair of aspects.pairs) {
      if (!isRecord(pair) || !participants.has(pair.body_a) || !participants.has(pair.body_b)) {
        throw new Error("相位組合的天體不在參與者清單裡。");
      }
      for (const target of Array.isArray(pair.aspect_targets) ? pair.aspect_targets : []) {
        if (!isRecord(target) || target.in_orb !== true) continue;
        const record = { a: pair.body_a, b: pair.body_b, aspect: target.key };
        const endA = byKey.get(pair.body_a);
        const endB = byKey.get(pair.body_b);
        if (!endA || !endB) {
          omitted.push({ ...record, reason: OMIT_REASON.ENDPOINT_NOT_DRAWN });
          if (!endA) missing.set(pair.body_a, typeof pair.body_a_name === "string" ? pair.body_a_name : pair.body_a);
          if (!endB) missing.set(pair.body_b, typeof pair.body_b_name === "string" ? pair.body_b_name : pair.body_b);
        } else if (endA.anchorOnly || endB.anchorOnly) {
          omitted.push({ ...record, reason: OMIT_REASON.ENDPOINT_ANCHOR_ONLY });
        } else if (!Object.hasOwn(STYLES, target.key)) {
          omitted.push({ ...record, reason: OMIT_REASON.STYLE_UNKNOWN });
        } else {
          lines.push({
            ...record,
            pattern: STYLES[target.key].pattern,
            partile: target.partile === true,
            applying: typeof target.applying === "string" ? target.applying : null,
            offset: typeof target.offset_from_exact_degrees === "number" ? target.offset_from_exact_degrees : null,
            angleA: endA.a,
            angleB: endB.a,
          });
        }
      }
    }

    const drawn = lines.map((line, index) => {
      const style = STYLES[line.aspect];
      // points：兩端的點鍵，原樣取自 pairs 的 body_a、body_b（頁面版寫成 data-points 供圖表連動，
      // 下載版不寫）；line：這個圖元畫的是 lines 的第幾條。兩者繪製端的幾何都不讀。
      const item = {
        ...(style.pattern === "bracket"
          ? bracketItem(geometry, line, style)
          : chordItem(geometry, line, style)),
        points: [line.a, line.b],
        line: index,
      };
      // 畫的順序：小相位在下，同度在最上；同一層維持回應的順序。
      return { item, rank: line.partile ? 2 : style.pattern === "minor" ? 0 : 1 };
    });
    const ordered = drawn.map((entry, index) => ({ ...entry, index }))
      .sort((p, q) => p.rank - q.rank || p.index - q.index)
      .map((entry) => entry.item);
    // 每個有線的點在圓上放一個小圓點，線的端點才讀得出是哪一點。
    const anchors = [...new Set(lines.flatMap((line) => [line.a, line.b]))].map((key) => {
      const p = polar(geometry, byKey.get(key).a, geometry.r);
      return { type: "circle", part: "aspect-anchor", cx: round3(p.x), cy: round3(p.y), r: ANCHOR_RADIUS,
        fill: "aspect", stroke: null, width: 0, points: [key] };
    });

    const status = lines.length ? STATUS.DRAWN
      : isRecord(aspects.degree_based) && aspects.degree_based.orb_verdict_available === false
        ? STATUS.ORB_NOT_SELECTED : STATUS.NONE_IN_ORB;
    return {
      status, lines, omitted,
      missingPoints: [...missing].map(([key, name]) => ({ key, name })),
      group: { group: "aspects", items: [...ordered, ...anchors] },
    };
  }

  /**
   * 讀圖說明的相位句：線型＝相位名。相位名只取後端 degree_based.aspect_names_zh（唯一產生器），
   * 只列本張圖真的畫了的相位；名稱表沒有的鍵寫原鍵，不代為命名。
   */
  function legendLines(result, namesZh) {
    const names = isRecord(namesZh) ? namesZh : {};
    const nameOf = (key) => (typeof names[key] === "string" ? names[key] : key);
    const byPattern = new Map();
    for (const line of result.lines) {
      const keys = byPattern.get(line.pattern) || [];
      if (!keys.includes(line.aspect)) keys.push(line.aspect);
      byPattern.set(line.pattern, keys);
    }
    const out = [];
    if (byPattern.size) {
      const parts = Object.keys(PATTERN_ZH).filter((pattern) => byPattern.has(pattern))
        .map((pattern) => `${PATTERN_ZH[pattern]}＝${byPattern.get(pattern).map(nameOf).join("、")}`);
      out.push(`相位線：${parts.join("；")}。`);
      if (result.lines.some((line) => line.partile)) out.push("粗線：同度（判準見相位表）。");
    }
    if (result.missingPoints.length) {
      const count = result.omitted.filter((item) => item.reason === OMIT_REASON.ENDPOINT_NOT_DRAWN).length;
      out.push(`${result.missingPoints.map((point) => point.name).join("、")}不在圖上，與它們的 ${count} 條相位線未畫（見相位表）。`);
    }
    if (result.omitted.some((item) => item.reason === OMIT_REASON.ENDPOINT_ANCHOR_ONLY)) {
      out.push("只有日期：月亮一天約走 13°，月亮的相位線不畫（見相位表）。");
    }
    if (result.omitted.some((item) => item.reason === OMIT_REASON.STYLE_UNKNOWN)) {
      out.push("有相位沒有對應的線型，未畫（見相位表）。");
    }
    if (result.status === STATUS.ORB_NOT_SELECTED) out.push("本次沒有選定容許度表，不畫相位線。");
    return out;
  }

  return Object.freeze({ build, legendLines, STATUS, OMIT_REASON, STYLES, DEFAULT_GEOMETRY, round3, mod360, isRecord, polar });
});
