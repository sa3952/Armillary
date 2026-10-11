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
  const DOWNLOAD_PALETTE_TOKENS = Object.freeze({
    bg: "print-bg", band: "paper", fg: "ink", dim: "ink-dim", hair: "hair", accent: "accent",
  });
  const DOWNLOAD_PALETTE = Object.freeze({
    bg: "#FFFFFF", band: "#F0EAD9", fg: "#1C1913", dim: "#574F41", hair: "#CFC5AE", accent: "#A03A22",
  });
  const FONT_TOKENS = Object.freeze({ sans: "sans", mono: "mono" });
  const FONTS = Object.freeze({
    sans: "\"PingFang TC\", \"Noto Sans TC\", \"Noto Sans CJK TC\", \"Microsoft JhengHei\", sans-serif",
    mono: "ui-monospace, \"SF Mono\", SFMono-Regular, Menlo, Consolas, \"DejaVu Sans Mono\", "
      + "\"Liberation Mono\", \"PingFang TC\", \"Noto Sans CJK TC\", \"Microsoft JhengHei\", monospace",
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
    if (item.type === "circle") return { cx: item.cx, cy: item.cy, r: item.r, "stroke-width": item.width };
    if (item.type === "line") {
      return { x1: item.x1, y1: item.y1, x2: item.x2, y2: item.y2, "stroke-width": item.width,
        "stroke-dasharray": item.dash || null };
    }
    if (item.type === "polygon") return { points: item.points.map((point) => point.join(",")).join(" ") };
    if (item.type === "glyph") {
      return { d: Glyphs.GLYPHS[item.glyph].d, transform: `matrix(${item.matrix.join(" ")})`,
        "stroke-width": item.halo === undefined ? null : Math.round(item.halo * 1000) / 1000 };
    }
    return { x: item.x, y: item.y, "font-size": item.size, "text-anchor": item.anchor,
      "dominant-baseline": "central", "stroke-width": item.halo === undefined ? null : item.halo };
  }

  /** 頁面版：顏色、字體與描邊外圈都是 class，值在 calculate.css。 */
  function pageClasses(item) {
    const names = [`cw-${item.part}`];
    if (item.type === "text") names.push(`cw-font-${item.font}`);
    if (item.halo !== undefined) names.push("cw-halo");
    if (item.fill !== undefined) names.push(item.fill ? `cw-f-${item.fill}` : "cw-f-none");
    else if (item.type === "line") names.push("cw-f-none");
    if (item.stroke) names.push(`cw-s-${item.stroke}`);
    return { class: names.join(" ") };
  }

  /** 下載版：只用展示屬性。 */
  function presentation(item) {
    const attributes = {};
    if (item.fill !== undefined) attributes.fill = item.fill ? DOWNLOAD_PALETTE[item.fill] : "none";
    else if (item.type === "line") attributes.fill = "none";
    if (item.stroke) attributes.stroke = DOWNLOAD_PALETTE[item.stroke];
    if (item.type === "text") attributes["font-family"] = FONTS[item.font];
    if (item.halo !== undefined) {
      Object.assign(attributes, { stroke: DOWNLOAD_PALETTE.bg, "paint-order": "stroke", "stroke-linejoin": "round" });
    }
    return attributes;
  }

  const TAG = Object.freeze({ circle: "circle", line: "line", polygon: "polygon", glyph: "path", text: "text" });

  function appendGroup(doc, parent, group, variant, topLevel) {
    const node = svgElement(doc, "g", {
      "aria-hidden": topLevel ? "true" : null,
      class: variant === "page" ? `cw-${group.group}` : null,
    });
    for (const item of group.items || []) {
      const element = svgElement(doc, TAG[item.type], {
        ...geometry(item),
        ...(variant === "page" ? pageClasses(item) : presentation(item)),
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

  // ── 結果頁上的「星盤圖」區塊
  const SECTION_TEXT = Object.freeze({
    title: "星盤圖",
    lead: "刻線畫在真實黃經；符號與度數太擠時會移開，以細線連回刻線，前後順序不變。只畫本次所選的宮位制，不畫相位線。",
    caption: "數值與表格同源；表格是完整版。",
    legend: Object.freeze({
      tick: "星座環內緣的短刻線是天體的真實黃經，不會移動。",
      label: "標籤由外往內是符號、度、星座、分；度與分直接取自回應，與表格「星座度數」欄相同（圖只到分）。",
      retro: "℞：逆行，與表格「行進」欄同源；月交點不標。",
      nodes: "密、平：密切交點與平均交點；表格兩者分列，圖也兩者都畫。",
      angles: "ASC、MC、DSC、IC：四軸畫在真實位置，中天不一定在正上方；紅色只用來標四軸，不表示吉凶。",
      houses: "1–12：宮號，只畫本次所選的宮位制；象限宮制的宮頭度數見表格。",
    }),
    enlarge: "放大檢視",
    close: "關閉",
    dialogTitle: "星盤圖（放大）",
    includeInput: "在圖內加印輸入摘要（出生日期、時間與地點）",
    downloadSvg: "下載 SVG",
    downloadPng: "下載 PNG",
    privacy: "圖內預設不印出生日期、時間與地點；但即使不列座標，星盤數值本身也能推回大致的出生時間與地點。",
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
    return [
      L.tick, L.label,
      ...(model.scene.some((group) => (group.children || []).some((label) => label.items.some((item) => item.part === "label-mark")))
        ? [L.retro] : []),
      ...([...keys].some((key) => /node$/.test(key)) ? [L.nodes] : []),
      ...(kinds.has("angle") ? [L.angles] : []),
      ...(model.scene.some((group) => group.group === "houses") ? [L.houses] : []),
      // 方向、宮位制、只有日期與未畫的點：與下載圖頁尾同一組句子。
      ...model.notes.filter((note) => note !== WheelModel.TEXT.accent),
    ];
  }

  function pageSvg(doc, model, describedBy) {
    const svg = renderSvg(doc, model, { variant: "page" });
    if (describedBy.length) svg.setAttribute("aria-describedby", describedBy.join(" "));
    return svg;
  }

  /**
   * 結果頁的星盤圖區塊：圖、圖說、讀圖說明、放大檢視（<dialog>，Esc 關閉）與下載。
   * 下載交給呼叫端（它持有結果是否仍對應目前輸入的守衛、Blob URL 與輸入摘要）：
   * onDownload(format, includeInput, button)。
   */
  function createSection(doc, model, { describedBy = [], onDownload } = {}) {
    const section = htmlElement(doc, "section", "chart-wheel");
    section.id = "chart-wheel";
    section.setAttribute("aria-labelledby", "chart-wheel-title");
    const head = htmlElement(doc, "div", "head");
    const title = htmlElement(doc, "h3", null, SECTION_TEXT.title);
    title.id = "chart-wheel-title";
    head.appendChild(title);
    section.append(head, htmlElement(doc, "p", "section-note", SECTION_TEXT.lead));

    const caption = htmlElement(doc, "p", "chart-wheel-caption", SECTION_TEXT.caption);
    caption.id = "chart-wheel-caption";
    const description = ["chart-wheel-caption", ...describedBy];

    const figure = htmlElement(doc, "div", "chart-wheel-figure");
    const svg = pageSvg(doc, model, description);
    figure.appendChild(svg);

    const legend = htmlElement(doc, "ul", "chart-wheel-legend");
    for (const item of legendItems(model)) legend.appendChild(htmlElement(doc, "li", null, item));

    const actions = htmlElement(doc, "div", "chart-wheel-actions");
    const enlarge = htmlElement(doc, "button", "ghost small", SECTION_TEXT.enlarge);
    enlarge.type = "button";
    enlarge.setAttribute("aria-haspopup", "dialog");
    const inputLabel = htmlElement(doc, "label", "chart-wheel-input");
    const inputBox = doc.createElement("input");
    inputBox.type = "checkbox";
    inputBox.className = "option-control";
    inputLabel.append(inputBox, doc.createTextNode(SECTION_TEXT.includeInput));
    const privacy = htmlElement(doc, "p", "note", SECTION_TEXT.privacy);
    privacy.id = "chart-wheel-privacy";
    const downloads = [["svg", SECTION_TEXT.downloadSvg], ["png", SECTION_TEXT.downloadPng]].map(([format, label]) => {
      const button = htmlElement(doc, "button", "ghost small chart-wheel-download", label);
      button.type = "button";
      button.setAttribute("aria-describedby", "chart-wheel-privacy");
      button.addEventListener("click", () => {
        if (typeof onDownload === "function") onDownload(format, inputBox.checked, button);
      });
      return button;
    });
    actions.append(enlarge, inputLabel, ...downloads);

    // 放大檢視：原生 <dialog> 的 showModal 提供焦點圈限、背景 inert 與 Esc 關閉；關閉後焦點回到開啟它的按鈕。
    const dialog = htmlElement(doc, "dialog", "chart-wheel-dialog");
    dialog.setAttribute("aria-labelledby", "chart-wheel-dialog-title");
    const dialogHead = htmlElement(doc, "div", "chart-wheel-dialog-head");
    const dialogTitle = htmlElement(doc, "h3", null, SECTION_TEXT.dialogTitle);
    dialogTitle.id = "chart-wheel-dialog-title";
    const close = htmlElement(doc, "button", "ghost small", SECTION_TEXT.close);
    close.type = "button";
    dialogHead.append(dialogTitle, close);
    // 內容包在一層裡：對話框本身沒有留白，點到 dialog 本身就是點在背景上。
    const dialogBody = htmlElement(doc, "div", "chart-wheel-dialog-body");
    // 手機上放大後的圖比螢幕寬，在這一層裡捲動；頁面本身不會橫向溢出。
    const dialogView = htmlElement(doc, "div", "chart-wheel-dialog-view");
    dialogBody.append(dialogHead, dialogView);
    dialog.appendChild(dialogBody);
    let opener = enlarge;
    const open = (from) => {
      if (dialog.open) return;
      opener = from;
      dialogView.replaceChildren(pageSvg(doc, model, description));
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      // 放大後比視窗寬時，從圖的中心開始看。
      dialogView.scrollLeft = (dialogView.scrollWidth - dialogView.clientWidth) / 2;
      close.focus();
    };
    const shut = () => {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    };
    enlarge.addEventListener("click", () => open(enlarge));
    // 手機上點圖就放大；鍵盤使用者用「放大檢視」按鈕。
    svg.addEventListener("click", () => open(enlarge));
    close.addEventListener("click", shut);
    // 點對話框外的背景（事件落在 dialog 本身）也關閉。
    dialog.addEventListener("click", (event) => { if (event.target === dialog) shut(); });
    dialog.addEventListener("close", () => {
      dialogView.replaceChildren();
      if (opener && opener.isConnected) opener.focus();
    });

    section.append(figure, caption, legend, actions, privacy, dialog);
    return section;
  }

  /** 模型或繪製失敗時：只留一句說明，表格照常；不把例外內容放上畫面。 */
  function createFailureSection(doc) {
    const section = htmlElement(doc, "section", "chart-wheel");
    section.id = "chart-wheel";
    section.setAttribute("aria-labelledby", "chart-wheel-title");
    const head = htmlElement(doc, "div", "head");
    const title = htmlElement(doc, "h3", null, SECTION_TEXT.title);
    title.id = "chart-wheel-title";
    head.appendChild(title);
    section.append(head, htmlElement(doc, "p", "section-note", SECTION_TEXT.failed));
    return section;
  }

  return Object.freeze({
    renderSvg, serializeSvg, drawCanvas, createSection, createFailureSection, SECTION_TEXT,
    DOWNLOAD_PALETTE, DOWNLOAD_PALETTE_TOKENS, FONTS, FONT_TOKENS, PNG_SCALE,
    buildModel: WheelModel.build,
  });
});
