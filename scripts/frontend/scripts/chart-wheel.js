(function attachChartWheel(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  const api = factory(
    commonJs ? require("./chart-glyphs.js") : root.ArmillaryChartGlyphs,
    commonJs ? require("./chart-wheel-model.js") : root.ChartWheelModel,
  );
  if (commonJs) module.exports = api;
  if (root) root.ChartWheel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildChartWheel(Glyphs, WheelModel) {
  "use strict";

  // 星盤圖的三個繪製端，都讀 chart-wheel-model.js 的同一份場景：
  //   - 頁面 SVG：顏色與字體只用 class（calculate.css），紙色底；
  //   - 下載 SVG：只用展示屬性（fill／stroke／font-family），白底，離開頁面也照樣顯示；
  //   - 下載 PNG：Canvas 2D 直接畫同一份場景，符號用 Path2D。不走 SVG→<img>→canvas：
  //     CSP 的 img-src 不允許 blob:／data:。
  // 一律以 createElementNS＋setAttribute＋textContent 建立；沒有 innerHTML、沒有 style 屬性或 <style>
  // （CSP 的 style-src 'self' 與 trusted-types 'none'）。下載檔不放 <metadata>、不放 data-* 原始數值。

  const SVG_NS = "http://www.w3.org/2000/svg";

  // 下載版（白底）的顏色：每一個都是 tokens.css 的 token 值，測試逐一核對。
  // aspect：相位線用結果頁「方法判斷」那一環的顏色，表示這是依容許度表作出的判斷，不表吉凶。
  const DOWNLOAD_PALETTE_TOKENS = Object.freeze({
    bg: "print-bg", band: "paper", fg: "ink", dim: "ink-dim", hair: "hair", accent: "accent", aspect: "ring-3",
  });
  const DOWNLOAD_PALETTE = Object.freeze({
    bg: "#FFFFFF", band: "#F0EAD9", fg: "#1C1913", dim: "#4F483B", hair: "#CFC5AE", accent: "#A03A22",
    aspect: "#A0632B",
  });
  const FONT_TOKENS = Object.freeze({ sans: "sans", mono: "mono", serif: "serif-num", book: "serif" });
  const FONTS = Object.freeze({
    sans: "\"PingFang TC\", \"Noto Sans TC\", \"Noto Sans CJK TC\", \"Microsoft JhengHei\", sans-serif",
    mono: "ui-monospace, \"SF Mono\", SFMono-Regular, Menlo, Consolas, \"DejaVu Sans Mono\", "
      + "\"Liberation Mono\", \"PingFang TC\", \"Noto Sans CJK TC\", \"Microsoft JhengHei\", monospace",
    serif: "Palatino, \"Palatino Linotype\", \"Book Antiqua\", \"Times New Roman\", \"Liberation Serif\", "
      + "\"DejaVu Serif\", serif",
    book: "\"Songti TC\", \"Noto Serif TC\", \"Noto Serif CJK TC\", \"Source Han Serif TC\", \"PMingLiU\", \"MingLiU\", "
      + "\"Times New Roman\", serif",
  });
  const PNG_SCALE = 2;
  const ANCHOR_TO_ALIGN = Object.freeze({ start: "left", middle: "center", end: "right" });

  function svgElement(doc, name, attributes) {
    const node = doc.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) {
      if (value !== null && value !== undefined) node.setAttribute(key, String(value));
    }
    return node;
  }

  /** 一個圖元的幾何屬性（兩種 SVG 相同）。 */
  function geometry(item) {
    if (item.type === "circle") {
      return { cx: item.cx, cy: item.cy, r: item.r, "stroke-width": item.width, "stroke-dasharray": item.dash || null };
    }
    if (item.type === "line") {
      return { x1: item.x1, y1: item.y1, x2: item.x2, y2: item.y2, "stroke-width": item.width,
        "stroke-dasharray": item.dash || null };
    }
    if (item.type === "polygon" || item.type === "polyline") {
      const points = { points: item.points.map((point) => point.join(",")).join(" ") };
      return item.type === "polyline" ? { ...points, "stroke-width": item.width } : points;
    }
    if (item.type === "path") {
      return { d: item.d, "stroke-width": item.width, "stroke-dasharray": item.dash || null };
    }
    if (item.type === "glyph") {
      return { d: Glyphs.GLYPHS[item.glyph].d, transform: `matrix(${item.matrix.join(" ")})`,
        "stroke-width": item.halo === undefined ? null : Math.round(item.halo * 1000) / 1000 };
    }
    return { x: item.x, y: item.y, "font-size": item.size, "text-anchor": item.anchor,
      "dominant-baseline": "central", "stroke-width": item.halo === undefined ? null : item.halo };
  }

  // 只描邊、不填色的圖元（相位線的合相括弧是 path）。
  const STROKE_ONLY = new Set(["line", "polyline", "path"]);

  /** 頁面版：顏色、字體與描邊外圈都是 class，值在 calculate.css。 */
  function pageClasses(item) {
    const names = [`cw-${item.part}`];
    if (item.type === "text") names.push(`cw-font-${item.font}`);
    if (item.halo !== undefined) names.push("cw-halo");
    if (item.fill !== undefined) names.push(item.fill ? `cw-f-${item.fill}` : "cw-f-none");
    else if (STROKE_ONLY.has(item.type)) names.push("cw-f-none");
    if (item.stroke) names.push(`cw-s-${item.stroke}`);
    return { class: names.join(" ") };
  }

  /** 下載版：只用展示屬性。 */
  function presentation(item) {
    const attributes = {};
    if (item.fill !== undefined) attributes.fill = item.fill ? DOWNLOAD_PALETTE[item.fill] : "none";
    else if (STROKE_ONLY.has(item.type)) attributes.fill = "none";
    if (item.stroke) attributes.stroke = DOWNLOAD_PALETTE[item.stroke];
    if (item.type === "text") attributes["font-family"] = FONTS[item.font];
    if (item.halo !== undefined) {
      Object.assign(attributes, { stroke: DOWNLOAD_PALETTE.bg, "paint-order": "stroke", "stroke-linejoin": "round" });
    }
    return attributes;
  }

  const TAG = Object.freeze({
    circle: "circle", line: "line", polyline: "polyline", polygon: "polygon", glyph: "path", path: "path", text: "text",
  });

  /**
   * 相位線圖元連到哪兩點：只有頁面版寫 data-points（點鍵，原樣取自回應的 pairs），供圖表連動讀；
   * 下載版不寫任何 data-*。
   */
  function aspectPointAttributes(group, item, variant) {
    if (variant !== "page" || group.group !== "aspects" || !Array.isArray(item.points)) return {};
    if (!item.points.every((key) => typeof key === "string")) return {};
    return { "data-points": item.points.join(" ") };
  }

  function appendGroup(doc, parent, group, variant, topLevel) {
    const node = svgElement(doc, "g", {
      "aria-hidden": topLevel ? "true" : null,
      class: variant === "page" ? `cw-${group.group}${group.shared ? ` cw-${group.group}-shared` : ""}` : null,
    });
    for (const item of group.items || []) {
      const element = svgElement(doc, TAG[item.type], {
        ...geometry(item),
        ...(variant === "page" ? pageClasses(item) : presentation(item)),
        ...aspectPointAttributes(group, item, variant),
      });
      if (item.type === "text") element.textContent = item.text;
      node.appendChild(element);
    }
    for (const child of group.children || []) appendGroup(doc, node, child, variant, false);
    parent.appendChild(node);
  }

  /**
   * 場景 → SVG 元素。variant "page"：頁面上的圖（class 著色、無底色、隨容器縮放）；
   * "download"：下載檔（展示屬性、白底、帶 <title>、固定寬高）。
   */
  function renderSvg(doc, model, { variant = "page" } = {}) {
    const svg = svgElement(doc, "svg", {
      viewBox: `0 0 ${model.width} ${model.height}`,
      width: variant === "download" ? model.width : null,
      height: variant === "download" ? model.height : null,
      role: "img",
      "aria-label": model.ariaLabel,
      class: variant === "page" ? "chart-wheel-svg" : null,
    });
    if (variant === "download") {
      const title = svgElement(doc, "title", {});
      title.textContent = model.ariaLabel;
      svg.appendChild(title);
      svg.appendChild(svgElement(doc, "rect", {
        x: 0, y: 0, width: model.width, height: model.height, fill: DOWNLOAD_PALETTE.bg,
      }));
    }
    for (const group of model.scene) appendGroup(doc, svg, group, variant, true);
    return svg;
  }

  function serializeSvg(svg) {
    const Serializer = svg.ownerDocument.defaultView.XMLSerializer;
    return new Serializer().serializeToString(svg);
  }

  function* flatten(groups) {
    for (const group of groups) {
      yield* group.items || [];
      yield* flatten(group.children || []);
    }
  }

  /** 同一份場景以 Canvas 2D 畫成白底圖；ctx 的畫布須為 model 尺寸 × scale。 */
  function drawCanvas(ctx, model, scale = PNG_SCALE) {
    const P = DOWNLOAD_PALETTE;
    ctx.save();
    ctx.scale(scale, scale);
    ctx.fillStyle = P.bg;
    ctx.fillRect(0, 0, model.width, model.height);
    for (const item of flatten(model.scene)) {
      ctx.save();
      ctx.setLineDash(item.dash ? item.dash.split(" ").map(Number) : []);
      if (item.width) ctx.lineWidth = item.width;
      if (item.stroke) ctx.strokeStyle = P[item.stroke];
      if (item.fill) ctx.fillStyle = P[item.fill];
      if (item.type === "circle") {
        ctx.beginPath();
        ctx.arc(item.cx, item.cy, item.r, 0, 2 * Math.PI);
        if (item.fill) ctx.fill();
        if (item.stroke) ctx.stroke();
      } else if (item.type === "line") {
        ctx.beginPath();
        ctx.moveTo(item.x1, item.y1);
        ctx.lineTo(item.x2, item.y2);
        ctx.stroke();
      } else if (item.type === "polyline") {
        ctx.beginPath();
        item.points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.stroke();
      } else if (item.type === "path") {
        ctx.stroke(new Path2D(item.d));
      } else if (item.type === "polygon") {
        ctx.beginPath();
        item.points.forEach(([x, y], index) => (index ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.closePath();
        ctx.fill();
      } else if (item.type === "glyph") {
        const shape = new Path2D(Glyphs.GLYPHS[item.glyph].d);
        ctx.transform(...item.matrix);
        if (item.halo !== undefined) {
          ctx.lineJoin = "round";
          ctx.lineWidth = item.halo;
          ctx.strokeStyle = P.bg;
          ctx.stroke(shape);
        }
        ctx.fill(shape);
      } else if (item.type === "text") {
        ctx.font = `${item.size}px ${FONTS[item.font]}`;
        ctx.textAlign = ANCHOR_TO_ALIGN[item.anchor];
        ctx.textBaseline = "middle";
        if (item.halo !== undefined) {
          ctx.lineJoin = "round";
          ctx.lineWidth = item.halo;
          ctx.strokeStyle = P.bg;
          ctx.strokeText(item.text, item.x, item.y);
        }
        ctx.fillText(item.text, item.x, item.y);
      }
      ctx.restore();
    }
    ctx.restore();
  }

  /**
   * 回應 → 模型（預設 standard 字級，也是下載檔用的那一份）。模型帶一個 forPreset(preset)，
   * 頁面依圖的實際寬度換字級時，以同一份回應與選項重算一次（每種字級只算一次）。
   */
  function buildModel(response, options = {}) {
    return WheelModel.shared.withPresets(WheelModel.build, response, options);
  }

  // 結果頁上的「星盤圖」區塊
  const SECTION_TEXT = Object.freeze({
    title: "星盤圖",
    lead: "刻線畫在真實黃經；符號與度數太擠時會移開，以細線連回刻線，前後順序不變。只畫本次所選的宮位制。",
    leadWithAspects: "刻線畫在真實黃經；符號與度數太擠時會移開，以細線連回刻線，前後順序不變。"
      + "中央的線是容許度內的逐度相位，與相位方格同源，可以關閉。只畫本次所選的宮位制。",
    caption: "數值與表格同源；表格是完整版。",
    // 方盤的格子在窄螢幕上很擠，字可能小到認不出來。
    legend: Object.freeze({
      tick: "星座環內緣的短刻線是天體的真實黃經，不會移動。",
      label: "標籤由外往內是符號、度、星座、分；度與分直接取自回應，與表格「星座度數」欄相同（圖只到分）。",
      compact: "標籤擠在一起時，同一星座只在第一個標籤印星座符號，後面的只印度與分；角距不到 1° 的兩點"
        + "可共用一條標籤，由外往內依黃經先後排，各有一條引線連回自己的刻線。",
      retro: "℞：逆行，與表格「行進」欄同源；月交點不標。",
      retroWithLilith: "℞：逆行，與表格「行進」欄同源；月交點與 Lilith 不標。",
      nodes: "密、平：密切交點與平均交點；表格兩者分列，圖也兩者都畫。",
      lilith: "⚸ 平、自然：兩種算法的黑月 Lilith（月球軌道離地球最遠的那一點）。平均：把月球軌道的短期變動平均掉，位置等速前進；自然：依月亮實際經過最遠點的位置推算，會在平均位置前後擺動。表格兩者分列，圖也兩者都畫。",
      angles: "ASC、MC、DSC、IC：四軸畫在真實位置，中天不一定在正上方；紅色只用來標四軸，不表示吉凶。",
      houses: "1–12：宮號，只畫本次所選的宮位制；象限宮制的宮頭度數見表格。",
      aspectColour: "相位線的顏色只表示這是依容許度表作出的方法判斷，不表示吉凶；整宮相位不畫，見相位表。",
      link: "滑鼠移到符號上，表格對應的列會一起標示；手機請用圖下方的符號對照。",
    }),
    symbols: Object.freeze({
      title: "符號對照",
      lead: "滑過或選取符號，圖上與表格會一起標示，畫面不移動；要看表格中那一列，按「到表格看這一顆」。",
      help: "在圖、表與相位方格上標示這一顆，畫面不移動。",
      clear: "清除標示",
      jump: "到表格看這一顆",
      retro: "逆行",
    }),
    showAspects: "顯示相位線",
    enlarge: "放大檢視",
    close: "關閉",
    dialogTitle: "星盤圖（放大）",
    panHint: "圖比螢幕大：用一指拖曳看四周，兩指可再放大。",
    fitWhole: "看整張",
    includeInput: "在圖內加印輸入摘要（出生日期、時間與地點）",
    downloadSvg: "下載 SVG",
    downloadPng: "下載 PNG",
    privacy: "圖內預設不印出生日期、時間與地點；但即使不列座標，星盤數值本身也能推回出生時間與地點。",
    failed: "這次的星盤圖無法繪製；數值見下方表格。",
  });

  function htmlElement(doc, tag, className, text) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function legendItems(model) {
    const kinds = new Set(model.labels.map((label) => label.kind));
    const keys = new Set(model.labels.map((label) => label.key));
    const L = SECTION_TEXT.legend;
    const lilith = [...keys].some((key) => /lilith$/.test(key));
    return [
      L.tick, L.label,
      ...(model.compaction.signs || model.compaction.shared ? [L.compact] : []),
      ...(model.scene.some((group) => (group.children || []).some((label) => label.items.some((item) => item.part === "label-mark")))
        ? [lilith ? L.retroWithLilith : L.retro] : []),
      ...([...keys].some((key) => /node$/.test(key)) ? [L.nodes] : []),
      ...(lilith ? [L.lilith] : []),
      ...(kinds.has("angle") ? [L.angles] : []),
      ...(model.scene.some((group) => group.group === "houses") ? [L.houses] : []),
      // 方向、宮位制、只有日期與未畫的點：與下載圖頁尾同一組句子。
      ...model.notes.filter((note) => note !== WheelModel.TEXT.accent),
    ];
  }

  /** 讀圖說明裡講相位線的句子（線型、同度、未畫的線與原因）；畫了線時另加顏色的說明。 */
  function aspectLegendItems(model) {
    const aspects = model.aspects;
    if (!aspects) return [];
    return [
      ...(model.aspectLegend || []),
      ...(aspects.status === WheelModel.ASPECT_STATUS.DRAWN ? [SECTION_TEXT.legend.aspectColour] : []),
    ];
  }

  /**
   * 「顯示相位線」勾選框：只在有線可畫時出現，預設勾選。切換只加減區塊上的 class（圖、放大的圖與
   * 讀圖說明裡的相位句一起隱藏），不重畫；下載跟著這個設定（readAspects）。
   */
  function aspectToggle(doc, model, section) {
    if (!model.aspects || model.aspects.status !== WheelModel.ASPECT_STATUS.DRAWN) {
      return { control: null, readAspects: () => true };
    }
    const label = htmlElement(doc, "label", "chart-wheel-aspects-toggle");
    const box = doc.createElement("input");
    box.type = "checkbox";
    box.className = "option-control";
    box.checked = true;
    box.addEventListener("change", () => section.classList.toggle("cw-aspects-off", !box.checked));
    label.append(box, doc.createTextNode(SECTION_TEXT.showAspects));
    return { control: label, readAspects: () => box.checked };
  }

  // ariaLabel（可省略）：model → 頁面上這張圖的名稱，取代模型自己的 ariaLabel（例如另一張盤要冠上它的名字）。
  function pageSvg(doc, model, describedBy, ariaLabel = null) {
    const svg = renderSvg(doc, model, { variant: "page" });
    if (typeof ariaLabel === "function") svg.setAttribute("aria-label", ariaLabel(model));
    if (describedBy.length) svg.setAttribute("aria-describedby", describedBy.join(" "));
    return svg;
  }

  // 圖表連動（只在結果頁上的圖；下載的 SVG／PNG 不經過這裡）
  // 每個點的刻線、引線、四軸線與標籤群組帶 data-points（後端的點鍵），標籤上另疊一個透明的
  // 感應框（cw-hit）。鍵讀模型圖元的 linked（本檔的點）或 points（相位線的兩端），先過格式檢查。
  // 標示本身（哪些元素加 class）由呼叫端做，它同時管表格那一側。
  const POINT_KEY = /^[a-z][a-z_]*$/;
  const HIT_PAD = 0.5;

  /** 合格的點鍵清單 → data-points 的值；不合格（含幾何的頂點陣列）回 null。 */
  function pointsValue(keys) {
    if (!Array.isArray(keys) || !keys.length || !keys.every((key) => typeof key === "string" && POINT_KEY.test(key))) {
      return null;
    }
    return keys.join(" ");
  }

  /** 場景與 renderSvg 畫出的元素一一對應（每組一個 <g>，先圖元、後子群組）；數目對不上的那一組不標。 */
  function annotateGroup(node, group, labels) {
    const elements = [...node.children];
    const items = group.items || [];
    const children = group.children || [];
    if (elements.length !== items.length + children.length) return;
    items.forEach((item, index) => {
      const value = pointsValue(item.linked) || pointsValue(item.points);
      if (value) elements[index].setAttribute("data-points", value);
    });
    children.forEach((child, index) => {
      const element = elements[items.length + index];
      // 標籤群組與 model.labels 同序。
      const value = labels ? pointsValue(labels[index] ? [labels[index].key] : null) : pointsValue(child.points);
      if (value) element.setAttribute("data-points", value);
      annotateGroup(element, child, null);
    });
  }

  function annotatePoints(doc, svg, model) {
    const groups = [...svg.children].filter((node) => node.localName === "g");
    if (groups.length !== model.scene.length) return;
    model.scene.forEach((group, index) => annotateGroup(groups[index], group, group.group === "labels" ? model.labels : null));
    // 感應框：每個點自己那幾格（符號、度、星座、分；共用標籤的兩點各自幾格），每格一個透明框，
    // 疊在最上層。不用整個堆疊的外框：斜向的堆疊外框會蓋到隔壁的標籤。排版時不同點的格至少相隔
    // 1 單位，所以每格只往外加半個單位。
    const hits = svgElement(doc, "g", { "aria-hidden": "true", class: "cw-hits" });
    const round = (value) => Math.round(value * 1000) / 1000;
    for (const label of model.labels) {
      const value = pointsValue([label.key]);
      if (!value || !label.boxes.length) continue;
      const hit = svgElement(doc, "g", { class: "cw-hit", "data-points": value });
      for (const box of label.boxes) {
        hit.appendChild(svgElement(doc, "rect", {
          x: round(box.x0 - HIT_PAD), y: round(box.y0 - HIT_PAD),
          width: round(box.x1 - box.x0 + 2 * HIT_PAD), height: round(box.y1 - box.y0 + 2 * HIT_PAD), class: "cw-f-none",
        }));
      }
      hits.appendChild(hit);
    }
    svg.appendChild(hits);
  }

  const hitOf = (node) => (node && typeof node.closest === "function" ? node.closest(".cw-hit") : null);

  /**
   * 圖上的指標：滑鼠滑過感應框＝預覽，滑鼠點感應框＝選取（不捲動）；觸控、筆與其他地方的點擊照舊放大。
   * 回傳一個判斷函式給 click：這一下若已當作選取處理就回 true。
   */
  function linkFigure(figure, link) {
    let pointer = "";
    figure.addEventListener("pointerdown", (event) => { pointer = event.pointerType || ""; });
    figure.addEventListener("pointerover", (event) => {
      if (event.pointerType !== "mouse") return;
      const hit = hitOf(event.target);
      if (hit) link.onPreview(hit.getAttribute("data-points"));
    });
    figure.addEventListener("pointerout", (event) => {
      if (event.pointerType !== "mouse" || !hitOf(event.target) || hitOf(event.relatedTarget)) return;
      link.onPreview(null);
    });
    return (event) => {
      const kind = pointer || event.pointerType || "";
      pointer = "";
      const hit = kind === "mouse" ? hitOf(event.target) : null;
      if (!hit) return false;
      link.onActivate(hit.getAttribute("data-points"));
      return true;
    };
  }

  function symbolGlyph(doc, key) {
    const glyph = Glyphs.GLYPHS[key];
    const svg = svgElement(doc, "svg", {
      class: "chart-wheel-symbol-glyph", viewBox: WheelModel.glyphViewBox(key),
      "aria-hidden": "true", focusable: "false",
    });
    svg.appendChild(svgElement(doc, "path", { d: glyph.d }));
    return svg;
  }

  /**
   * 符號對照：圖上畫的每一點一顆按鈕（順序與表格相同），一個 role="toolbar"，Tab 只停一次，
   * 方向鍵在按鈕間移動。焦點或滑鼠停在按鈕上＝預覽；按下（Enter、空白鍵、點、觸控）＝選取：圖與表格
   * 一起標示，畫面不捲動、焦點留在按鈕上——手機上沒有滑過預覽，一捲走就看不到圖上標了哪一點。
   * 選取後「符號對照」標題那一行（按鈕列之上、緊接在圖下方）出現「清除標示」與「到表格看這一顆」——手機上
   * 按鈕列有好幾行，放在列下方會落在視窗外；後者才打開摺疊、捲到表格那一列並交出焦點。
   * 兩顆的顯示、後者含天體名的名稱與選取的宣告（role="status"）由呼叫端依選取狀態設定。
   * 按鈕名稱以看得見的字開頭，再接宮位與逆行；宮位只在有落宮時寫。
   */
  function symbolBar(doc, model, link) {
    const T = SECTION_TEXT.symbols;
    const block = htmlElement(doc, "div", "chart-wheel-symbols");
    const title = htmlElement(doc, "h4", "chart-wheel-symbols-title", T.title);
    title.id = "chart-wheel-symbols-title";
    const help = htmlElement(doc, "span", "visually-hidden", T.help);
    help.id = "chart-wheel-symbols-help";
    const bar = htmlElement(doc, "div", "chart-wheel-symbols-bar");
    bar.setAttribute("role", "toolbar");
    bar.setAttribute("aria-labelledby", "chart-wheel-symbols-title");
    const buttons = model.labels.filter((label) => pointsValue([label.key])).map((label, index) => {
      const button = htmlElement(doc, "button", "chart-wheel-symbol");
      button.type = "button";
      button.tabIndex = index === 0 ? 0 : -1;
      button.setAttribute("data-points", label.key);
      button.setAttribute("aria-describedby", "chart-wheel-symbols-help");
      button.setAttribute("aria-label", [label.name, label.position,
        ...(Number.isInteger(label.house) ? [`第 ${label.house} 宮`] : []),
        ...(label.retro ? [T.retro] : [])].join("，"));
      if (label.glyph && Glyphs.GLYPHS[label.glyph]) button.appendChild(symbolGlyph(doc, label.glyph));
      button.append(htmlElement(doc, "span", "chart-wheel-symbol-name", label.name),
        htmlElement(doc, "span", "chart-wheel-symbol-position", label.position));
      if (label.retro) button.appendChild(htmlElement(doc, "span", "chart-wheel-symbol-retro", "℞"));
      button.addEventListener("click", () => link.onActivate(label.key));
      return button;
    });
    bar.append(...buttons);
    const move = (from, to) => {
      from.tabIndex = -1;
      to.tabIndex = 0;
      to.focus();
    };
    bar.addEventListener("keydown", (event) => {
      const at = buttons.indexOf(event.target);
      if (at < 0) return;
      const last = buttons.length - 1;
      const next = { ArrowRight: at + 1, ArrowDown: at + 1, ArrowLeft: at - 1, ArrowUp: at - 1, Home: 0, End: last }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      move(buttons[at], buttons[Math.min(last, Math.max(0, next))]);
    });
    bar.addEventListener("focusin", (event) => {
      if (buttons.includes(event.target)) link.onPreview(event.target.getAttribute("data-points"));
    });
    bar.addEventListener("focusout", (event) => {
      if (!bar.contains(event.relatedTarget)) link.onPreview(null);
    });
    bar.addEventListener("pointerover", (event) => {
      const button = event.pointerType === "mouse" && event.target.closest ? event.target.closest(".chart-wheel-symbol") : null;
      if (button) link.onPreview(button.getAttribute("data-points"));
    });
    bar.addEventListener("pointerout", (event) => {
      if (event.pointerType !== "mouse") return;
      const into = event.relatedTarget && event.relatedTarget.closest ? event.relatedTarget.closest(".chart-wheel-symbol") : null;
      if (!into) link.onPreview(null);
    });
    const clear = htmlElement(doc, "button", "ghost small chart-wheel-symbols-clear", T.clear);
    clear.type = "button";
    clear.hidden = true;
    clear.addEventListener("click", () => link.onClear());
    const jump = htmlElement(doc, "button", "chart-wheel-symbols-jump", T.jump);
    jump.type = "button";
    jump.hidden = true;
    jump.addEventListener("click", () => link.onReveal());
    const actions = htmlElement(doc, "div", "chart-wheel-symbols-actions");
    actions.append(clear, jump);
    const head = htmlElement(doc, "div", "chart-wheel-symbols-head");
    head.append(title, actions);
    const status = htmlElement(doc, "p", "visually-hidden chart-wheel-symbols-status");
    status.setAttribute("role", "status");
    block.append(head, htmlElement(doc, "p", "note", T.lead), help, bar, status);
    return block;
  }

  /**
   * 結果頁的星盤圖區塊：圖、圖說、讀圖說明、放大檢視（<dialog>，Esc 關閉）與下載。
   * 下載交給呼叫端（它持有結果是否仍對應目前輸入的守衛、Blob URL 與輸入摘要）：
   * onDownload(format, includeInput, button, showAspects)。
   * link（可省略）：圖表連動的回呼 { onPreview(keys|null), onActivate(key), onClear(), onReveal(), onRedraw() }；
   * onActivate 只選取不捲動，onReveal 跳到所選那一點的表格列；
   * 有它時圖上的點帶 data-points 與感應框，圖下方多一列符號對照。
   * alternate（可省略）：另一種畫法（方盤，chart-square.js 的 sectionOption）{ model, lead, control(doc, onChange) }；
   * 有它時工具列多一組「圓盤／方盤」，圖、放大檢視、讀圖說明與下載都跟著選的那一種，預設圓盤。
   * 下載的回呼多帶第五個參數：目前的畫法（"wheel" 或 "square"）。
   * 同一頁上的第二張盤（例如太陽回歸盤）用下面幾項換掉本命盤那一份的 id 與字，預設就是本命盤：
   * idPrefix（預設 "chart-wheel"）：區塊、標題、圖說、隱私句與放大檢視標題的 id 都以它開頭，
   * 圖的 aria-describedby 第一項是它的圖說；title、dialogTitle：區塊標題與放大檢視的標題字；
   * headingLevel（預設 3）：區塊標題的層級；ariaLabel(model)：頁面上（含放大檢視）那張圖的名稱；
   * includeInput（預設 true）：false 時不列「下載加上輸入摘要」的勾選框，下載回呼的 includeInput 一律 false。
   */
  /** 區塊外框、標題列與一句說明：正常的區塊與失敗時的那一句共用。 */
  function sectionShell(doc, note, { idPrefix = "chart-wheel", title = SECTION_TEXT.title, headingLevel = 3 } = {}) {
    const section = htmlElement(doc, "section", "chart-wheel");
    section.id = idPrefix;
    section.setAttribute("aria-labelledby", `${idPrefix}-title`);
    const head = htmlElement(doc, "div", "head");
    const level = Number.isInteger(headingLevel) && headingLevel >= 2 && headingLevel <= 6 ? headingLevel : 3;
    const heading = htmlElement(doc, `h${level}`, null, title);
    heading.id = `${idPrefix}-title`;
    head.appendChild(heading);
    section.append(head, htmlElement(doc, "p", "section-note", note));
    return section;
  }

  function createSection(doc, model, {
    describedBy = [], onDownload, link = null, alternate = null,
    idPrefix = "chart-wheel", title = SECTION_TEXT.title, dialogTitle: dialogText = SECTION_TEXT.dialogTitle,
    headingLevel = 3, ariaLabel = null, includeInput = true,
  } = {}) {
    const drawsAspects = Boolean(model.aspects) && model.aspects.status === WheelModel.ASPECT_STATUS.DRAWN;
    const section = sectionShell(doc, drawsAspects ? SECTION_TEXT.leadWithAspects : SECTION_TEXT.lead,
      { idPrefix, title, headingLevel });

    const caption = htmlElement(doc, "p", "chart-wheel-caption", SECTION_TEXT.caption);
    caption.id = `${idPrefix}-caption`;
    const description = [caption.id, ...describedBy];

    // 字級依圖在畫面上的寬度（WheelModel.presetForWidth）：先畫 calculate 交來的那一份，量到寬度後
    // 若該換字級就重畫；視窗或轉向改變寬度時同樣重畫。讀圖說明跟著畫出來的那一份。
    let style = "wheel";
    // 符號對照的區塊（沒有連動或沒有點時是 null）；切換畫法時換成那一種的。
    let symbols = null;
    const modelFor = (preset) => {
      const base = style === "square" ? alternate.model : model;
      return typeof base.forPreset === "function" ? base.forPreset(preset) : base;
    };
    const figure = htmlElement(doc, "div", "chart-wheel-figure");
    const legend = htmlElement(doc, "ul", "chart-wheel-legend");
    let shown = null;
    const show = (next) => {
      if (next === shown) return;
      shown = next;
      const svg = pageSvg(doc, shown, description, ariaLabel);
      if (link) annotatePoints(doc, svg, shown);
      figure.replaceChildren(svg);
      legend.replaceChildren(...(shown.legend || legendItems(shown)).map((item) => htmlElement(doc, "li", null, item)),
        ...aspectLegendItems(shown).map((item) => htmlElement(doc, "li", "cw-legend-aspects", item)));
      if (link && shown.labels.length) {
        legend.appendChild(htmlElement(doc, "li", "chart-wheel-legend-link", SECTION_TEXT.legend.link));
        link.onRedraw();
      }
    };
    show(model);
    const View = doc.defaultView;
    if (View && typeof View.ResizeObserver === "function") {
      // 重畫放到下一個畫格：在回呼裡直接換掉被觀察的內容，Safari 會報「ResizeObserver loop」錯誤。
      const frame = typeof View.requestAnimationFrame === "function"
        ? (callback) => View.requestAnimationFrame(callback) : (callback) => callback();
      let pending = false;
      const observer = new View.ResizeObserver(() => {
        if (pending) return;
        pending = true;
        frame(() => {
          pending = false;
          if (!section.isConnected) {
            observer.disconnect();
            return;
          }
          if (figure.clientWidth > 0) show(modelFor(WheelModel.presetForWidth(figure.clientWidth)));
        });
      });
      observer.observe(figure);
    }

    const actions = htmlElement(doc, "div", "chart-wheel-actions");
    const aspects = aspectToggle(doc, model, section);
    const enlarge = htmlElement(doc, "button", "ghost small chart-wheel-enlarge", SECTION_TEXT.enlarge);
    enlarge.type = "button";
    enlarge.setAttribute("aria-haspopup", "dialog");
    const inputLabel = htmlElement(doc, "label", "chart-wheel-input");
    const inputBox = doc.createElement("input");
    inputBox.type = "checkbox";
    inputBox.className = "option-control";
    inputLabel.append(inputBox, doc.createTextNode(SECTION_TEXT.includeInput));
    const privacy = htmlElement(doc, "p", "note", SECTION_TEXT.privacy);
    privacy.id = `${idPrefix}-privacy`;
    const downloads = [["svg", SECTION_TEXT.downloadSvg], ["png", SECTION_TEXT.downloadPng]].map(([format, label]) => {
      const button = htmlElement(doc, "button", "ghost small chart-wheel-download", label);
      button.type = "button";
      button.setAttribute("aria-describedby", privacy.id);
      button.addEventListener("click", () => {
        if (typeof onDownload === "function") onDownload(format, includeInput && inputBox.checked, button, aspects.readAspects(), style);
      });
      return button;
    });
    // 圓盤／方盤：切換只換圖、引言與讀圖說明（區塊加 cw-style-square，calculate.css 依此藏起相位線的勾選框）。
    const styleControl = alternate ? alternate.control(doc, (next) => {
      style = next === "square" ? "square" : "wheel";
      section.classList.toggle("cw-style-square", style === "square");
      // 符號對照跟著畫出來的那一種：方盤沒有放進格子的點（例如四分宮制下的月交點）不列按鈕，
      // 按鈕上的宮號與格子一致。重建後由 show() 的 onRedraw 重新套上標示。
      if (symbols) {
        // 按鈕順序照圓盤（也就是表格）的順序，方盤的標籤是依格子排的。
        const order = new Map(model.labels.map((label, index) => [label.key, index]));
        const rank = (label) => (order.has(label.key) ? order.get(label.key) : model.labels.length);
        const base = style === "square"
          ? { labels: [...alternate.model.labels].sort((a, b) => rank(a) - rank(b)) } : model;
        const rebuilt = base.labels.length ? symbolBar(doc, base, link) : null;
        if (rebuilt) symbols.replaceWith(rebuilt);
        else symbols.remove();
        symbols = rebuilt;
      }
      section.querySelector(".section-note").textContent = style === "square" ? alternate.lead
        : drawsAspects ? SECTION_TEXT.leadWithAspects : SECTION_TEXT.lead;
      show(modelFor(WheelModel.presetForWidth(figure.clientWidth)));
    }) : null;
    actions.append(...(aspects.control ? [aspects.control] : []), enlarge, ...(includeInput ? [inputLabel] : []), ...downloads);

    // 放大檢視：原生 <dialog> 的 showModal 提供焦點圈限、背景 inert 與 Esc 關閉；關閉後焦點回到開啟它的按鈕。
    const dialog = htmlElement(doc, "dialog", "chart-wheel-dialog");
    dialog.setAttribute("aria-labelledby", `${idPrefix}-dialog-title`);
    const dialogHead = htmlElement(doc, "div", "chart-wheel-dialog-head");
    const dialogTitle = htmlElement(doc, "h3", null, dialogText);
    dialogTitle.id = `${idPrefix}-dialog-title`;
    const close = htmlElement(doc, "button", "ghost small", SECTION_TEXT.close);
    close.type = "button";
    // 「看整張」：放大的圖比螢幕大時（手機），一鍵縮回螢幕寬看全圖，再按一次回到放大；aria-pressed 標狀態。
    const fit = htmlElement(doc, "button", "ghost small chart-wheel-fit", SECTION_TEXT.fitWhole);
    fit.type = "button";
    fit.setAttribute("aria-pressed", "false");
    const dialogTools = htmlElement(doc, "div", "chart-wheel-dialog-tools");
    dialogTools.append(fit, close);
    dialogHead.append(dialogTitle, dialogTools);
    // 內容包在一層裡：對話框本身沒有留白，點到 dialog 本身就是點在背景上。
    const dialogBody = htmlElement(doc, "div", "chart-wheel-dialog-body");
    // 放大的圖比螢幕大時，標題下一行說怎麼看（打開時從圖的正中央看起，四周的標籤在畫面外）。
    const panHint = htmlElement(doc, "p", "note chart-wheel-pan-hint", SECTION_TEXT.panHint);
    panHint.id = `${idPrefix}-dialog-hint`;
    // 手機上放大後的圖比螢幕寬，在這一層裡捲動；頁面本身不會橫向溢出。
    const dialogView = htmlElement(doc, "div", "chart-wheel-dialog-view");
    dialogBody.append(dialogHead, panHint, dialogView);
    dialog.appendChild(dialogBody);
    dialog.setAttribute("aria-describedby", panHint.id);
    const overflowing = () => dialogView.scrollWidth > dialogView.clientWidth + 1
      || dialogView.scrollHeight > dialogView.clientHeight + 1;
    // 放大的圖放得進對話框時（桌機），提示與「看整張」都不需要。
    const paintTools = () => {
      const zoomable = dialog.classList.contains("is-fit") || overflowing();
      fit.hidden = !zoomable;
      panHint.hidden = !zoomable || dialog.classList.contains("is-fit");
    };
    const centre = () => {
      dialogView.scrollLeft = (dialogView.scrollWidth - dialogView.clientWidth) / 2;
      dialogView.scrollTop = (dialogView.scrollHeight - dialogView.clientHeight) / 2;
    };
    fit.addEventListener("click", () => {
      const whole = !dialog.classList.contains("is-fit");
      dialog.classList.toggle("is-fit", whole);
      fit.setAttribute("aria-pressed", String(whole));
      paintTools();
      centre();
    });
    let opener = enlarge;
    // 打開前頁面捲到哪裡：關閉後焦點回到「放大檢視」鈕，但不為它捲動頁面（點圖打開時，那顆鈕在圖的下方，
    // 瀏覽器會把頁面往下捲到它，使用者回來時已不在剛才看的圖上）。
    let pageScroll = null;
    const open = (from) => {
      // 放大鈕停用（畫面上已沒有結果）或區塊已移出頁面時不開：點圖本身也走這裡。
      if (dialog.open || enlarge.disabled || !section.isConnected) return;
      opener = from;
      pageScroll = View ? { x: View.scrollX || 0, y: View.scrollY || 0 } : null;
      // 放大的圖在畫面上大於 680px，用相對較小的字級：同一群標籤攤得較窄。
      const zoomed = modelFor("wide");
      const svg = pageSvg(doc, zoomed, description, ariaLabel);
      dialogView.replaceChildren(svg);
      dialog.classList.remove("is-fit");
      fit.setAttribute("aria-pressed", "false");
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      // 放大後比視窗大時從正中央看起：四周哪一邊都只差半個視窗，往哪個方向捲都一樣近。
      centre();
      paintTools();
      close.focus({ preventScroll: true });
    };
    const shut = () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    };
    enlarge.addEventListener("click", () => open(enlarge));
    // 手機上點圖就放大；鍵盤使用者用「放大檢視」按鈕。圖會隨字級重畫，所以聽在外框上。
    // 連動時，滑鼠點在點的標籤上是選取，不放大。
    const picked = link ? linkFigure(figure, link) : () => false;
    figure.addEventListener("click", (event) => { if (!picked(event)) open(enlarge); });
    close.addEventListener("click", shut);
    // 點對話框外的背景（事件落在 dialog 本身）也關閉。
    dialog.addEventListener("click", (event) => { if (event.target === dialog) shut(); });
    dialog.addEventListener("close", () => {
      dialogView.replaceChildren();
      dialog.classList.remove("is-fit");
      if (opener && opener.isConnected) opener.focus({ preventScroll: true });
      if (pageScroll && View && typeof View.scrollTo === "function"
        && (View.scrollX !== pageScroll.x || View.scrollY !== pageScroll.y)) {
        View.scrollTo(pageScroll.x, pageScroll.y);
      }
      pageScroll = null;
    });

    symbols = link && model.labels.length ? symbolBar(doc, model, link) : null;
    // 「圓盤／方盤」緊接在圖的正下方：換了畫法不必往上捲就看得到圖。讀圖的那一句說明移到圖與切換之後：
    // 結果首屏先看到圖。
    const lead = section.querySelector(":scope > .section-note");
    section.append(figure, ...(styleControl ? [styleControl] : []), ...(lead ? [lead] : []), caption,
      ...(symbols ? [symbols] : []), legend, actions, privacy, dialog);
    return section;
  }

  /** 模型或繪製失敗時：只留一句說明，表格照常；不把例外內容放上畫面。 */
  function createFailureSection(doc) {
    return sectionShell(doc, SECTION_TEXT.failed);
  }

  /**
   * 下載一張圖（本命盤、方盤、回歸盤共用）：SVG 直接序列化；PNG 以 Canvas 2D 畫同一份場景。
   * 交給 lifecycle.deliverDownload，結果以 report(訊息, 語氣) 回報。toBlob 是非同步的：交出 PNG
   * 前再問一次 isCurrent()，期間結果已清除或換掉就不交出。
   */
  function downloadImage(doc, lifecycle, model, format, files, isCurrent, report) {
    if (format === "svg") {
      const svg = renderSvg(doc, model, { variant: "download" });
      lifecycle.deliverDownload(doc, new doc.defaultView.Blob([serializeSvg(svg)], { type: "image/svg+xml" }), files.svg);
      report("已產生 SVG 檔案。", "info");
      return;
    }
    const canvas = doc.createElement("canvas");
    canvas.width = model.width * PNG_SCALE;
    canvas.height = model.height * PNG_SCALE;
    const context = typeof canvas.getContext === "function" ? canvas.getContext("2d") : null;
    if (!context || typeof canvas.toBlob !== "function") {
      report("下載失敗：這個瀏覽器無法產生 PNG。", "error");
      return;
    }
    drawCanvas(context, model);
    canvas.toBlob((blob) => {
      if (!isCurrent()) return;
      if (!blob) {
        report("下載失敗：無法產生 PNG。", "error");
        return;
      }
      pngImageOnly(doc, blob).then((image) => {
        if (!isCurrent()) return;
        lifecycle.deliverDownload(doc, image, files.png);
        report("已產生 PNG 檔案。", "info");
      });
    }, "image/png");
  }

  /**
   * 只留 PNG 的必要區塊（型別首字母大寫：IHDR、PLTE、IDAT、IEND）。各瀏覽器的編碼器會自己加附屬
   * 區塊：Firefox 加一段帶識別碼的 deBG，Safari 加 sRGB 與 eXIf；下載的圖只該有圖本身。
   * 讀不了位元組（沒有 arrayBuffer）或格式不對時原樣交出。
   */
  function pngImageOnly(doc, blob) {
    if (typeof blob.arrayBuffer !== "function") return Promise.resolve(blob);
    return blob.arrayBuffer().then((buffer) => {
      const bytes = new Uint8Array(buffer);
      const view = new DataView(buffer);
      const kept = [bytes.subarray(0, 8)];
      let offset = 8;
      while (offset + 12 <= bytes.length) {
        const length = view.getUint32(offset);
        const end = offset + 12 + length;
        if (end > bytes.length) return blob;
        const first = bytes[offset + 4];
        if (first >= 0x41 && first <= 0x5A) kept.push(bytes.subarray(offset, end));
        offset = end;
      }
      return new doc.defaultView.Blob(kept, { type: "image/png" });
    }, () => blob);
  }

  return Object.freeze({
    renderSvg, serializeSvg, drawCanvas, downloadImage, createSection, createFailureSection,
    DOWNLOAD_PALETTE, DOWNLOAD_PALETTE_TOKENS, FONTS, FONT_TOKENS, PNG_SCALE,
    buildModel,
  });
});
