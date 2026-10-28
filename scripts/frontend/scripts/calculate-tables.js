
// 取樣摘要圖：不可操作：沒有把手、沒有焦點停留點。每個取樣點是一個獨立的點，點與點之間是虛線（那裡沒有計算），不畫連續
// 填滿的條。點列整體是一張 role="img"，名稱是 view-model 給的文字版；畫面上的時刻標籤只是同一份資訊的視覺版。位置與樣式
// 全部由 calculate.css 的 class 與 data 屬性決定，不寫 style 屬性（release CSP 的 style-src 'self'）。文字一律走
// textContent。
function materializeFigure(figure) {
  const host = make("div", "sampling");
  host.dataset.tone = figure.tone;
  host.appendChild(make("p", "sampling-lead", figure.lead));
  const marks = make("div", "sampling-marks");
  marks.setAttribute("role", "img");
  // 名稱是一句摘要（點數、首尾、代表性時刻、有改變的間隔數），由同一份 marks 導出；逐點的 text_alternative 放在圖之後的
  // 文字裡。名稱塞進二十五個時刻，報讀每經過這張圖都得聽完。
  const representative = figure.marks.find((mark) => mark.representative);
  const changed = figure.marks.filter((mark) => mark.bands_after > 0).length;
  marks.setAttribute("aria-label",
    `取樣點 ${figure.marks.length} 個，${figure.marks[0].label} 到 ${figure.marks.at(-1).label}`
    + (representative ? `，代表性時刻 ${representative.label}` : "") + (changed ? `；${changed} 個間隔內有改變` : "")
    + "。");
  marks.dataset.density = figure.marks.length > 7 ? "dense" : "sparse";
  figure.marks.forEach((mark, index) => {
    const item = make("span", "sampling-mark");
    if (mark.representative) item.dataset.representative = "true";
    if (index === 0) item.dataset.edge = "first";
    if (index === figure.marks.length - 1) item.dataset.edge = "last";
    const dot = make("span", "sampling-dot");
    item.append(dot, make("span", "sampling-time", mark.label));
    marks.appendChild(item);
    if (index < figure.marks.length - 1) {
      const gap = make("span", "sampling-gap");
      if (mark.bands_after > 0) {
        gap.dataset.bands = String(mark.bands_after);
        const band = make("span", "sampling-gap-band");
        gap.append(band, make("span", "sampling-gap-count", mark.gap_label));
      }
      marks.appendChild(gap);
    }
  });
  host.appendChild(marks);
  // 逐點的時刻只給輔助科技，緊接在圖之後；明眼使用者從圖上的標籤讀同一份資訊。
  host.appendChild(make("p", "visually-hidden", figure.text_alternative));
  // 圖例只描述圖形，文字輸出不印（契約）；與備註分在兩個節點，畫面上仍是同一段。
  const note = make("p", "sampling-note");
  if (figure.legend) note.appendChild(make("span", "sampling-legend", figure.legend));
  if (figure.note) note.appendChild(document.createTextNode(figure.note));
  host.appendChild(note);
  figure.groups.forEach((group) => {
    const block = make("div", "sampling-group");
    block.dataset.tone = group.tone;
    block.appendChild(make("h4", "sampling-group-title", group.title));
    if (group.note) block.appendChild(make("p", "sampling-group-note", group.note));
    if (group.bands.length) {
      const list = make("ul", "sampling-bands");
      group.bands.forEach((band) => {
        const row = document.createElement("li");
        const glyph = make("span", "sampling-band");
        glyph.setAttribute("aria-hidden", "true");
        row.append(
          glyph, make("span", "sampling-band-range", band.range),
          make("span", "sampling-band-resolution", band.resolution), make("span", "sampling-band-what", band.text),
        );
        list.appendChild(row);
      });
      block.appendChild(list);
    }
    if (group.items.length) { block.appendChild(make("p", "sampling-items", group.items.join("、"))); }
    host.appendChild(block);
  });
  return host;
}

// 900 字以 chart-exact fixture 校準：〈計算收據〉1,364 字、〈本次請求的選項〉946 字該摺疊；
// 〈天體位置〉569 字、〈相位〉481 字留在外面。
const LONG_SECTION_CHARS = 900;
const LONG_SECTION_ROWS = 30;

// 表格的畫面加工（數字欄與名稱符號）：只改畫面，不改內容。每一格的 textContent 仍是 view-model 給的那一格（唯一的例外是
// 整格負數的負號排成 U+2212，Labels.displayNumber），欄序照 view-model。複製本區、複製結果與四種下載都由 canonical 快照
// 產生，不讀 DOM；符號是沒有文字節點的 SVG，aria-hidden，報讀、選取複製與 textContent 都讀不到。
const SVG_NS = "http://www.w3.org/2000/svg";

// 數字欄：每一格都是帶號十進位數或度分秒（或「—」、空白），而且至少一格是數字。
// 「金牛 24°10′30.48″」、時刻字串與文字不算，維持靠左。
const NUMERIC_CELL = /^[+\-−]?\d+(?:\.\d+)?(?:°\d+′\d+(?:\.\d+)?″)?$/;
const NEUTRAL_CELL = (text) => text === "" || text === "—";
// 時刻（「1990-05-15 05:18:34 UTC+08:00」）與度數範圍（「26°–30°」）不靠右，但字面與數字欄相同。
const NUMERIC_TEXT_CELL = /^(?:(?:\d{4}-\d\d-\d\d[ T])?\d\d:\d\d(?::\d\d(?:\.\d+)?)?Z?(?: UTC[+-]\d\d:\d\d(?::\d\d)?)?|\d+°(?:\d\d′)?\s*[–-]\s*\d+°(?:\d\d′)?)$/;

function numericColumns(model) {
  return model.columns.map((_column, index) => {
    if (index === 0) return false;
    const cells = model.rows.map((row) => String(row[index] == null ? "" : row[index]).trim());
    return cells.some((text) => NUMERIC_CELL.test(text)) && cells.every((text) => NEUTRAL_CELL(text) || NUMERIC_CELL.test(text));
  });
}

// 天體、交點與月球拱點的符號：表格帶點鍵（圖表連動的那幾張）時照每一列的鍵取，與星盤圖用同一張對照
// （ChartWheelModel.POINTS）；鍵只認 labels.js 後端名稱表裡的天體、交點與拱點（軸點不加符號）。沒有點鍵的表（與一頁摘
// 要）才退回用名稱對照，名稱取同一張後端名稱表。星座的鍵就是符號鍵。對照不到的（Priapus、恆星、阿拉伯點…）不加符號，不
// 猜。星盤圖一族在第一份結果之前才載入（calculate-options.js），所以對照表在第一次畫表格時才建。
let tableGlyphTables = null;
function tableGlyphs() {
  if (tableGlyphTables) return tableGlyphTables;
  const glyphs = window.ArmillaryChartGlyphs;
  const points = window.ChartWheelModel.POINTS;
  const bodies = new Map();
  const keys = new Map();
  const signs = new Map();
  const vocabulary = Labels.VOCABULARIES;
  [vocabulary.body_backend_name, vocabulary.node_backend_name, vocabulary.lunar_apsis_backend_name].forEach((table) => {
    Object.entries(table).forEach(([key, name]) => {
      const point = points[key];
      if (!point || !glyphs.GLYPHS[point.glyph]) return;
      bodies.set(name, point.glyph);
      keys.set(key, point.glyph);
    });
  });
  Object.entries(vocabulary.zodiac_sign).forEach(([key, name]) => { if (glyphs.GLYPHS[key]) signs.set(name, key); });
  const signAtStart = new RegExp(`^(${[...signs.keys()].join("|") || "(?!)"}) (?=\\d)`);
  tableGlyphTables = { bodies, keys, signs, glyphs: glyphs.GLYPHS, signAtStart };
  return tableGlyphTables;
}
const PAIR_SEPARATOR = " — ";

// 符號框與星盤同一條光學規則（墨框長邊正規化、太陽與交點略收）：同一個符號在圖上與表裡一樣大。
function tableGlyph(key) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "cell-glyph");
  svg.setAttribute("viewBox", window.ChartWheelModel.glyphViewBox(key));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.dataset.glyph = key;
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", tableGlyphs().glyphs[key].d);
  svg.appendChild(path);
  return svg;
}

/**
 * 填入一格：文字原樣（只有整格負數的負號換成 U+2212）；認得的天體或星座度數前加符號。cellKeys：這一格的點鍵（表格帶點鍵時；
 * 相位組合欄「太陽 — 月亮」是兩個），有就照鍵取符號，不看名稱；null 時才照名稱對照。
 */
function fillCell(node, rawText, withBodies, cellKeys = null) {
  const text = Labels.displayNumber(rawText);
  const glyphs = tableGlyphs();
  const appendParts = (parts, glyphOf) => parts.forEach((part, index) => {
    if (index > 0) node.append(PAIR_SEPARATOR);
    const glyph = glyphOf(part, index);
    if (glyph) node.append(tableGlyph(glyph));
    node.append(part);
  });
  if (withBodies && Array.isArray(cellKeys)) {
    const parts = cellKeys.length > 1 ? text.split(PAIR_SEPARATOR) : [text];
    if (parts.length === cellKeys.length) { appendParts(parts, (_, index) => glyphs.keys.get(cellKeys[index])); return; }
  }
  if (withBodies) {
    const parts = text.split(PAIR_SEPARATOR);
    if (parts.some((part) => glyphs.bodies.has(part))) { appendParts(parts, (part) => glyphs.bodies.get(part)); return; }
  }
  const sign = glyphs.signAtStart.exec(text);
  if (!sign) { node.append(text); return; }
  // 星座度數：星座名照表格的黑體，度分秒包成 .deg，與數字欄同一套襯線（calculate.css）。
  node.append(tableGlyph(glyphs.signs.get(sign[1])), sign[0], make("span", "deg", text.slice(sign[0].length)));
}

// 相位方格的格內記號：幾何線條畫的相位符號（☌ ☍ △ □ ⚹），不靠字型；其他相位只寫名稱。
// 文字照原字放在只給報讀器的 span 裡（複製、匯出與報讀讀到的仍是同一句），記號與容許度只是畫面。
const ASPECT_MARKS = Object.freeze({
  conjunction: [["circle", { cx: 8, cy: 12, r: 4.6 }], ["line", { x1: 11.3, y1: 8.7, x2: 16.5, y2: 3.5 }]],
  opposition: [["circle", { cx: 5.2, cy: 14.8, r: 3.2 }], ["circle", { cx: 14.8, cy: 5.2, r: 3.2 }],
    ["line", { x1: 7.5, y1: 12.5, x2: 12.5, y2: 7.5 }]],
  trine: [["path", { d: "M10 3 L17.5 16.5 L2.5 16.5 Z" }]], square: [["path", { d: "M4 4 H16 V16 H4 Z" }]],
  sextile: [["line", { x1: 10, y1: 2.5, x2: 10, y2: 17.5 }], ["line", { x1: 3.5, y1: 6.25, x2: 16.5, y2: 13.75 }],
    ["line", { x1: 3.5, y1: 13.75, x2: 16.5, y2: 6.25 }]],
});
// 方格裡整宮成相位的格（「整宮合」…）與星座不合意的格（「不合意」）。名稱是後端 configuration_zh 的閉集。
const WHOLE_SIGN_ASPECTS = Object.freeze({ 合: "conjunction", 沖: "opposition", 拱: "trine", 刑: "square", 六分: "sextile" });
const WHOLE_SIGN_CELL = new RegExp(`^整宮(${Object.keys(WHOLE_SIGN_ASPECTS).join("|")})$`);
const AVERSION_CELL = "不合意";
function aspectMark(mark) {
  const holder = make("span", "asp-mark");
  holder.setAttribute("aria-hidden", "true");
  if (mark.orb) holder.dataset.orb = mark.orb;
  const shape = ASPECT_MARKS[mark.aspect];
  if (!shape) { holder.classList.add("asp-mark-name"); holder.dataset.name = mark.name; return holder; }
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 20 20");
  svg.setAttribute("class", `asp-glyph asp-${mark.aspect}`);
  svg.setAttribute("focusable", "false");
  for (const [name, attributes] of shape) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    svg.appendChild(node);
  }
  holder.appendChild(svg);
  return holder;
}

// 驗算軌跡與生效選項的格裡有很長、中間沒有空白的一串（「cusps=[180.40…,209.28…,…]」、
// 「flags=258;…」、「geocentric_true_altitude_…_v1」）。這種格只在逗號、分號、等號、斜線與底線之後多給
// 一個換行點（<wbr>），JSON 的「"鍵":」之後也給，數值本身仍不從中間斷開（時刻裡的冒號不算）；字一個不改（textContent 相同），紙上與窄螢幕上整串才折得進欄寬，不被裁掉。
const BREAKABLE_SECTIONS = new Set(["trace", "requested_options"]);
const LIST_BREAK = /(":|[,;=/|_])(?=\S)/;
// 把一格裡每個文字節點依 pattern（含一個捕捉組）切開，捕捉到的部分交給 emit 換成節點。
function splitTextNodes(cell, pattern, emit) {
  const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
  const texts = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) texts.push(node);
  texts.forEach((text) => {
    const parts = text.data.split(pattern);
    if (parts.length < 2) return;
    const fragment = document.createDocumentFragment();
    parts.forEach((part, index) => {
      if (index % 2 === 1) fragment.append(...emit(part));
      else if (part) fragment.append(part);
    });
    text.replaceWith(fragment);
  });
}
function addListBreaks(cell) { splitTextNodes(cell, LIST_BREAK, (mark) => [mark, document.createElement("wbr")]); }
// 日期（1990-05-15）是一個數，不在連字號斷行：每一格裡的日期包成不換行的 span，字一個不改（textContent 相同）。
// 驗算軌跡的長串也一樣，換行點仍由 addListBreaks 給。
const WHOLE_DATE = /(\d{4}-\d\d-\d\d)/;
function keepDatesWhole(cell) { splitTextNodes(cell, WHOLE_DATE, (date) => [make("span", "date-whole", date)]); }

// 時刻、欄頭的時間尺度與「本次請求的選項」的排字在 view-model（displayFormat），畫面與匯出讀同一份字。
// 同一欄上一格已寫過同一天時，view-model 只印時刻；這種欄的格長短不一，靠右排時分秒才上下對齊。
const DATED_CELL = /^\d{4}-\d\d-\d\d \d\d:\d\d/;
const CLOCK_CELL = /^\d\d:\d\d(?::\d\d)?(?:\.\d+)?$/;
function elidedDateColumns(model) {
  return model.columns.map((_column, index) => index > 0
    && model.rows.some((row) => typeof row[index] === "string" && CLOCK_CELL.test(row[index]))
    && model.rows.some((row) => typeof row[index] === "string" && DATED_CELL.test(row[index])));
}

/** 畫面上的數字寫法與 view-model 原字不同時，原字記在 data-canonical：畫面 ⊆ 匯出的對照讀這一份。 */
function markCanonical(node, raw) {
  const original = String(raw == null ? "" : raw);
  if (node.textContent !== Labels.displayNumber(original)) node.dataset.canonical = original;
}

function materializeTable(model, sectionId, sectionTitle) {
  const wrap = make("div", "table-wrap");
  // role／tabindex 由 applyOverflowRegions 依實際溢出決定，不在這裡寫死。
  wrap.dataset.regionLabel = [sectionTitle, model.title || "可橫向捲動的資料表"].filter(Boolean).join("：");
  const table = document.createElement("table");
  if (sectionId) table.dataset.section = sectionId;
  // 版面變體（相位方格）只換 class，樣式在 calculate.css；不寫 style 屬性（CSP）。
  if (model.variant === "aspect_grid") {
    table.className = "aspect-grid";
    wrap.classList.add("aspect-grid-wrap");
  } else if (model.columns.length === 2) {
    // 「項目／數值」這種兩欄表：窄螢幕上數值欄折行，不必橫捲（calculate.css）。
    table.className = "two-column";
  }
  if (model.title) { const caption = document.createElement("caption"); caption.textContent = model.title; table.appendChild(caption); }
  // 相位方格的格內是相位與度數的組合，不是單一數值，維持置中；欄頭是天體名稱。
  const isGrid = model.variant === "aspect_grid";
  const numeric = isGrid ? model.columns.map(() => false) : numericColumns(model);
  const clockColumns = isGrid ? model.columns.map(() => false) : elidedDateColumns(model);
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  model.columns.forEach((column, index) => {
    const th = document.createElement("th");
    th.scope = "col";
    if (numeric[index]) th.className = "num";
    if (clockColumns[index]) th.classList.add("num-time");
    const columnKey = isGrid && model.points && Array.isArray(model.points.columns) ? model.points.columns[index] : null;
    fillCell(th, column, isGrid && index > 0, columnKey ? [columnKey] : null);
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  model.rows.forEach((row, rowIndex) => {
    const tr = document.createElement("tr");
    const rowKeys = model.points && Array.isArray(model.points.rows) ? model.points.rows[rowIndex] : null;
    row.forEach((cell, index) => {
      // 第一格說明這一列是什麼（天體、步驟、項目），做成列標頭；報讀器讀到後面的數值時才知道屬於哪一列。
      const node = document.createElement(index === 0 ? "th" : "td");
      if (index === 0) node.scope = "row";
      if (numeric[index]) node.className = "num";
      else if (index > 0 && NUMERIC_TEXT_CELL.test(String(cell == null ? "" : cell).trim())) node.className = "num-text";
      if (clockColumns[index]) node.classList.add("num-time");
      // 格內連結（十二宮表的宮名連到方法頁宮義對照表的那一列）：文字照原字，包在連結裡。
      const href = index > 0 && model.links && model.links.column === index && Array.isArray(model.links.rows)
        ? model.links.rows[rowIndex] : null;
      const host = typeof href === "string" && href.startsWith("/zh-TW/") ? document.createElement("a") : node;
      if (host !== node) { host.href = href; node.appendChild(host); }
      const marks = isGrid && index > 0 && Array.isArray(model.marks) && Array.isArray(model.marks[rowIndex])
        ? model.marks[rowIndex][index - 1] : null;
      const wholeSign = isGrid && index > 0 ? WHOLE_SIGN_CELL.exec(String(cell == null ? "" : cell)) : null;
      if (Array.isArray(marks) && marks.length) {
        const spoken = make("span", "visually-hidden", String(cell));
        host.append(spoken, ...marks.map(aspectMark));
        node.classList.add("asp-cell");
      } else if (wholeSign) {
        // 整宮成相位、逐度不在容許度內：淡墨虛線的同一個記號；字只給報讀與複製。
        host.append(make("span", "visually-hidden", String(cell)), aspectMark({ aspect: WHOLE_SIGN_ASPECTS[wholeSign[1]] }));
        node.classList.add("asp-cell", "asp-whole");
      } else if (isGrid && index > 0 && String(cell) === AVERSION_CELL) {
        // 星座不合意：畫一個淡墨的「×」（CSS 畫，不進複製），與沒算的空格分開；字只給報讀與複製（說明在相位一區的備註）。
        const mark = make("span", "asp-aversion-mark", "");
        mark.setAttribute("aria-hidden", "true");
        host.append(make("span", "visually-hidden", String(cell)), mark);
        node.classList.add("asp-cell", "asp-aversion");
      } else {
        fillCell(host, String(cell == null ? "" : cell), index === 0, index === 0 && Array.isArray(rowKeys) ? rowKeys : null);
        markCanonical(node, cell);
      }
      tr.appendChild(node);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  table.querySelectorAll("th, td").forEach(keepDatesWhole);
  if (BREAKABLE_SECTIONS.has(sectionId)) table.querySelectorAll("td").forEach(addListBreaks);
  linkTableCells(table, model, sectionId);
  wrap.appendChild(table);
  return wrap;
}
