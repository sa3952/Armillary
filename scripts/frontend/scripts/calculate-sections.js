
// 這次沒有算的區塊：「加算」。古典完整與自訂在每一章的最後列出這次沒有算、勾一個選項就能加算的區塊（表裡的 enable）。
// 「加算」把那幾個選項勾上、照表單原樣再送一次：與自己捲回表單勾選、重新計算完全一樣，送到同一個伺服器，伺服器同樣不留
// 副本。被表單上另一個選項擋住的（例如只算古典七顆行星時的恆星）不給按鈕，寫明是被哪一項擋住。界、面、三分性沒有「加
// 算」：要先選一套，按鈕帶使用者回到表單的選單。
const PROFILE_KEYS = Object.freeze(["bounds_profile", "decan_profile", "triplicity_profile"]);

function absentBlock(chapterId, sections) {
  const groups = new Map();
  sections.forEach((section) => {
    const keys = Chapters.enableOptions(section.id);
    if (!keys.length) return;
    const id = keys.join(" ");
    if (!groups.has(id)) groups.set(id, { keys, titles: [] });
    groups.get(id).titles.push(section.title);
  });
  const unchosen = chapterId === "classical"
    ? PROFILE_KEYS.filter((key) => pageState.optionValues[key] === null || pageState.optionValues[key] === undefined) : [];
  if (!groups.size && !unchosen.length) return null;
  const block = make("div", "chapter-absent");
  const title = make("p", "chapter-absent-title", "這次沒有算");
  const list = make("ul", "chapter-absent-list");
  groups.forEach(({ keys, titles }) => {
    const item = document.createElement("li");
    const name = titles.join("、");
    item.append(make("span", "chapter-absent-name", name));
    const blocked = keys.map((key) => Catalogue.conflictFor(Catalogue.BY_KEY[key], { ...pageState.optionValues, [key]: true }))
      .find(Boolean);
    if (blocked) { item.append(make("span", "chapter-absent-why", `要算這一項，先到表單改「${blocked.source.label_zh}」。`)); } else {
      const button = make("button", "ghost small chapter-add");
      button.type = "button";
      button.dataset.enable = keys.join(" ");
      button.textContent = `加算${name}`;
      item.append(button);
    }
    list.appendChild(item);
  });
  if (unchosen.length) {
    const item = document.createElement("li");
    const names = unchosen.map((key) => Catalogue.BY_KEY[key].label_zh).join("、");
    item.append(make("span", "chapter-absent-name", `${names}：還沒選用哪一套`));
    const button = make("button", "ghost small chapter-choose");
    button.type = "button";
    button.dataset.option = unchosen[0];
    button.textContent = "到表單選一套";
    item.append(button);
    list.appendChild(item);
  }
  block.append(title, list);
  return block;
}

function addedSectionNode() {
  const wanted = pageState.resultFocusOptions;
  pageState.resultFocusOptions = null;
  if (!wanted) return null;
  const row = Chapters.SECTION_CHAPTERS.find((entry) => Chapters.enableOptions(entry.section).join(" ") === wanted
    && document.getElementById(`section-${entry.section}`));
  return row ? document.getElementById(`section-${row.section}`) : null;
}

function addFromChapter(event) {
  const target = event.target.closest ? event.target : null;
  const add = target && target.closest("button.chapter-add");
  if (add && !add.disabled) {
    pageState.addRequested = add.dataset.enable;
    add.dataset.enable.split(" ").forEach((key) => { pageState.optionValues = { ...pageState.optionValues, [key]: true }; });
    refreshOptionUi();
    noteFormChanged();
    submitButton.click();
    return;
  }
  const choose = target && target.closest("button.chapter-choose");
  if (choose && !choose.disabled) {
    // 古典完整的流派選單在「這次會算什麼」第一層；其他模式在進階選項裡。
    const plan = el(`plan-${choose.dataset.option}`);
    const control = plan && !el("plan-classical").hidden ? plan : el(`opt-${choose.dataset.option}`);
    unfoldForm(control);
    control.scrollIntoView({ block: "center", behavior: scrollBehavior() });
    control.focus({ preventScroll: true });
  }
}
results.addEventListener("click", addFromChapter);

/** 表單裡收合的 <details>（計算口徑、進階選項）先打開，裡面的控制項才有版面位置。 */
function unfoldForm(control) {
  for (let node = control; node && node !== form; node = node.parentElement) {
    if (node.tagName === "DETAILS" && !node.open) node.open = true;
  }
}

// 目錄比視窗高、或分頁列比螢幕寬時，把那一項捲進章節欄自己的可見範圍；只動章節欄的捲動位置，不動頁面。
// center：已經看得見也置中（換章時）；否則只在露出不全時捲。
function revealIndexLink(link, { center = false } = {}) {
  const inner = link.getBoundingClientRect();
  [el("chapter-index"), el("chapter-nav")].forEach((scroller) => {
    const outer = scroller.getBoundingClientRect();
    if (scroller.scrollWidth > scroller.clientWidth
      && (center || inner.left < outer.left || inner.right > outer.right)) {
      scroller.scrollLeft += inner.left - outer.left - (outer.width - inner.width) / 2;
    }
    if (scroller.scrollHeight > scroller.clientHeight
      && (inner.top < outer.top || inner.bottom > outer.bottom)) {
      scroller.scrollTop += inner.top - outer.top - (outer.height - inner.height) / 2;
    }
  });
}

// 用 Tab 在分頁列裡移動時，瀏覽器只把聚焦的那一項捲到剛好露出邊緣；整項捲進來才看得到焦點框。只對鍵盤的焦點
// （:focus-visible）這樣做：點或觸控時按下就有焦點，這時捲動分頁列，放開時指到的已是別的位置，這一下就不算點到連結。
function revealFocusedLink(event) {
  const link = event.target.closest ? event.target.closest("a.chapter-link, a.index-link") : null;
  if (link && keyboardFocus(link)) revealIndexLink(link);
}
function keyboardFocus(node) { try { return node.matches(":focus-visible"); } catch (_error) { return true; } }
el("chapter-index").addEventListener("focusin", revealFocusedLink);

/** 環標籤只寫中文（天文事實、幾何推導、方法判斷、驗證）；匯出的層級標籤照舊帶英文。 */
function layerText(label) { return String(label || "").replace(/^[A-Z][A-Z ]*[A-Z]\s+/, ""); }

function materializeSection(section) {
  const host = make("section", "result-section");
  host.id = `section-${section.id}`;
  lifecycle.registerSectionNode(host);
  const head = make("div", "head");
  const ring = make("span", "ring-tag");
  ring.dataset.ring = section.ring;
  ring.textContent = layerText(section.layer_label);
  head.appendChild(ring);
  const title = document.createElement("h3");
  title.textContent = section.title;
  head.appendChild(title);
  const state = make("span", "state");
  state.dataset.state = section.status.state;
  state.textContent = section.status.label;
  head.appendChild(state);
  // section copy：讀建立時綁定的 canonical 快照，不在點擊時重掃畫面。
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "ghost small section-copy";
  copy.textContent = "複製本區";
  // 二十多顆同字的按鈕在按鈕清單裡無從分辨；名稱以看得見的字開頭再接區塊標題
  // （WCAG 2.5.3：語音操作念看得見的字仍對得上）。
  copy.setAttribute("aria-label", `複製本區：${section.title}`);
  copy.addEventListener("click", () => copySection(section.id, copy));
  head.appendChild(copy);
  host.appendChild(head);
  // 長區塊改為摺疊（門檻式而非點名式，新的長區塊自動適用）。門檻看字數不看列數：列數兩個方向
  // 都會錯——〈逐步計算軌跡〉20 列、每列上千字，375px 下佔全頁 84%；〈三分性〉21 列只有 159 字。
  const tables = section.children.filter((child) => child.type === "table");
  const rowCount = tables.reduce((total, table) => total + table.rows.length, 0);
  const charCount = tables.reduce(
    (total, table) => total + table.rows.reduce(
      (rowTotal, row) => rowTotal + row.reduce((cellTotal, cell) => cellTotal + String(cell == null ? "" : cell).length, 0), 0,
    ),
    0,
  );
  // 列數門檻留著當保險：「很多列但每列極短」不會被字數抓到。
  // 「全部並列」的區段不整區收起：上面有一覽，各套的完整表已各自收進摺疊（decorateClassicalSection）。
  const comparing = tables.some((table) => String(table.title).startsWith("各家對照："));
  // 專門項目（result-chapters.js 的 folded）不論長短都先收起：一章裡十幾區全攤開，常用的那幾區
  // 會被推到好幾個螢幕之後。收起的區只露出第一句說明，其餘說明跟著表一起收。
  const folded = !comparing && tables.length > 0 && Chapters.foldedByDefault(section.id);
  const collapsible = !comparing && (folded || charCount > LONG_SECTION_CHARS || rowCount > LONG_SECTION_ROWS);
  let body = host;
  if (collapsible) {
    const details = makeFold("long-section", `展開這一區（${rowCount} 列）`);
    // 收起時表格不在版面上；展開後重量溢出，可橫捲的表才保有 region／tabindex／標籤。
    details.addEventListener("toggle", applyOverflowRegions);
    host.appendChild(details);
    body = details;
  }
  // 「說明與原典」摺疊（view-model 的 EXPLAIN_FOLDED_PREFIXES）：第一段收進去的說明出現時才建，
  // 放在它前面那段白話之後；之後收進去的段落都放進同一個，留在外面的段落接在摺疊後面。
  let explain = null;
  // 古書出處的「出處」摺疊：這一區第一條出處時才建，之後的出處都放進同一個。
  let sources = null;
  let leadNote = true;
  section.children.forEach((child) => {
    const target = child.type === "note" && !collapsible ? host : body;
    if (child.type === "figure") {
      // 摘要圖與它的第一行永遠在摺疊之外（預設不得摺疊）。
      host.insertBefore(materializeFigure(child.figure), collapsible ? body : null);
    } else if (child.type === "note") {
      const note = make("p", "section-note", child.text);
      // 備註留在摺疊外面：使用者要在展開前就知道這一區在講什麼。預設收起的區只留第一句。
      if (folded && !leadNote) body.appendChild(note);
      else (collapsible ? host : target).insertBefore(note, collapsible ? body : null);
      leadNote = false;
    } else if (child.type === "explain") {
      if (!explain) { explain = makeFold("section-explain", "說明與原典"); host.insertBefore(explain, collapsible ? body : null); }
      const line = make("p", "section-note", child.text);
      explain.appendChild(line);
    } else if (child.type === "block") {
      const block = make("p", "section-block", child.text);
      body.appendChild(block);
    } else if (child.type === "table") {
      const wrap = materializeTable(child, section.id, section.title);
      const bar = section.id === "bodies" ? decoratePositionTable(wrap, child) : null;
      if (bar) body.appendChild(bar);
      body.appendChild(wrap);
      // 整欄相同而收起的欄：表下註緊接在表的下面（ChartViewModel.buildViewTree）。
      (child.notes || []).forEach((text) => body.appendChild(make("p", "section-note table-note", text)));
    } else if (child.type === "source") {
      if (!sources) { sources = makeFold("section-sources", "出處"); body.appendChild(sources); }
      const line = make("p", "section-source", child.text);
      sources.appendChild(line);
    }
  });
  if (section.id === "trace") host.appendChild(tracePrintLine(rowCount));
  if (section.id === "aspects") arrangeAspectsForPhones(host);
  decorateClassicalSection(host, section);
  linkGlossaryTerms(host, section.id);
  return host;
}

// 手機上相位一區先給相位方格（一眼看完的那張），逐度相位長表收進摺疊（原生 details，鍵盤可開合）；
// 寬螢幕照原順序攤開。只搬節點、不改內容，斷點跨越時（轉向、縮放視窗）換回另一種排法。
// 上一份結果的窄螢幕監聽；換下一份結果時中止，免得舊結果的 DOM 被它一直握住。
let pairsNarrowListener = null;

function arrangeAspectsForPhones(host) {
  const grid = host.querySelector(":scope > .aspect-grid-wrap");
  const pairs = grid && [...host.querySelectorAll(":scope > .table-wrap")].find((wrap) => wrap !== grid
    && wrap.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING);
  if (!pairs) return;
  const pairNotes = [];
  for (let next = pairs.nextElementSibling; next && next.classList.contains("table-note"); next = next.nextElementSibling) {
    pairNotes.push(next);
  }
  const rows = pairs.querySelectorAll("tbody tr").length;
  const fold = makeFold("aspect-pairs-fold", `逐度相位（${rows} 組）`);
  fold.addEventListener("toggle", applyOverflowRegions);
  const arrange = (narrow) => {
    if (narrow && !fold.isConnected) {
      host.insertBefore(fold, grid.nextSibling);
      fold.append(pairs, ...pairNotes);
      host.insertBefore(grid, fold);
    } else if (!narrow && fold.isConnected) {
      host.insertBefore(pairs, grid);
      pairNotes.forEach((note) => host.insertBefore(note, grid));
      fold.remove();
    }
  };
  arrange(narrowScreen());
  if (typeof window.matchMedia === "function") {
    const query = window.matchMedia(NARROW_QUERY);
    if (pairsNarrowListener) pairsNarrowListener.abort();
    pairsNarrowListener = new AbortController();
    if (typeof query.addEventListener === "function") {
      query.addEventListener("change", (event) => arrange(event.matches), { signal: pairsNarrowListener.signal });
    }
  }
}

// 完整列印不印逐步計算軌跡：每步的算式與輸入動輒幾十頁，紙上也無從複製比對。
// 紙上在它的位置只印這一行，指向含整份軌跡的匯出檔；畫面上不顯示（calculate.css 的 print 規則）。
function tracePrintLine(stepCount) {
  return make("p", "section-note trace-print-line",
    `紙本不印逐步計算軌跡（本次 ${stepCount} 步）；整份軌跡在「運算結果＋驗算資料」的 JSON 與 Markdown 匯出檔裡。`);
}

// 古典判斷三區（廟旺陷弱、外來、行速與停滯）的一覽與標記：只改畫面，不改字：一覽、標記與時間軸都讀這一區 canonical 表格
// 裡的同一份字串（匯出、複製不經過這裡），表格照舊留在下面，給精確值、匯出對照與報讀。讀不懂的格（字串對不上已知的寫
// 法）就照原樣不加標記，不猜。標記的框線照 Lilly《Christian Astrology》1647 p.115 那張表（Fortitudes and Debilities）分
// 邊：實線框＝他列在強的一邊，虛線框＝列在弱的一邊，淡底無框＝不在那張表上或這裡不分邊。只分邊、不給分數，也不用紅綠分
// 好壞；字本身就是答案，框線只是第二道提示（不靠顏色）。
const GLANCE_KEY_TEXT = "框線照 Lilly《Christian Astrology》1647 p.115 的表：實線框是他列在強（Fortitudes）的一邊，"
  + "虛線框是列在弱（Debilities）的一邊；只照書分邊，不加分數。";
const DIGNITY_MARK_SIDE = Object.freeze({ 入廟: "fortitude", 入旺: "fortitude", 在陷: "debility", 在弱: "debility" });
const PEREGRINE_MARK_SIDE = Object.freeze({ 陷: "debility", 弱: "debility" });
const P115_SIDE = Object.freeze({ "Lilly 列為偶然強": "fortitude", "Lilly 列為偶然弱": "debility" });
/** p.115 表的一格（可能帶「（他寫的是「漸虧」）」這類補註）落在哪一邊；不在表上回 null。 */
const p115Side = (text) => {
  const head = Object.keys(P115_SIDE).find((label) => String(text || "").startsWith(label));
  return head ? P115_SIDE[head] : null;
};
const GLANCE_DASH = "—";

/** 一個標記：字照原樣，data-side 決定框線（fortitude 實線、debility 虛線、neutral 淡底、quiet 只是淡字）。 */
function stateMark(text, side) { const mark = make("span", "state-mark"); mark.dataset.side = side; mark.textContent = text; return mark; }

/**
 * 把一格的字換成「標記＋原字」：parts 依序接起來必須等於這一格原本的字，否則不動（格內的字一個不改）。
 * part 是 { text, side }（標記）或 { text }（原樣的字）；分隔用的「、」留在 DOM 裡、畫面上收起。
 */
function markCell(cell, parts) {
  if (!cell || parts.map((part) => part.text).join("") !== cell.textContent) return false;
  cell.replaceChildren(...parts.map((part) => {
    if (part.side) return stateMark(part.text, part.side);
    if (part.separator) return make("span", "state-mark-sep", part.text);
    return document.createTextNode(part.text);
  }));
  cell.classList.add("has-marks");
  return true;
}

/** 「入廟、在弱」這種清單：每一項依 sides 標記，「、」留著當分隔；不在表上的項目不標。 */
function listParts(text, sides) {
  const items = text.split("、");
  if (!items.every((item) => sides[item])) return null;
  return items.flatMap((item, index) => (index ? [{ text: "、", separator: true }] : []).concat([{ text: item, side: sides[item] }]));
}

function columnCells(table, name) {
  const heads = [...table.tHead.rows[0].cells].map((cell) => cell.textContent);
  const index = heads.indexOf(name);
  return index < 0 ? [] : [...table.tBodies[0].rows].map((row) => row.cells[index]);
}

function tableModel(section, test) { return section.children.find((child) => child.type === "table" && test(child)) || null; }

/** 天體名稱前的符號（與表格同一套）；對照不到就只有字。 */
function bodyLabel(name) {
  const node = make("span", "glance-body");
  const glyph = tableGlyphs().bodies.get(name);
  if (glyph) node.appendChild(tableGlyph(glyph));
  node.append(name);
  return node;
}

function signLabel(name) {
  const node = make("span", "glance-sign");
  if (tableGlyphs().signs.has(name)) node.appendChild(tableGlyph(tableGlyphs().signs.get(name)));
  node.append(name);
  return node;
}

// 一覽整塊是一張圖（role="img"），名稱是一句由同一份表格字串導出的摘要：報讀器聽到摘要，
// 逐格的精確值在下面的表。圖裡的字（標題、圖例、刻度）只描述這張圖，與摘要圖同一條契約，匯出不印。
function glanceShell(title) {
  const host = make("div", "glance");
  host.setAttribute("role", "img");
  host.appendChild(make("p", "glance-title", title));
  return host;
}
function nameGlance(host, title, lines) {
  host.setAttribute("aria-label", `${title}：${lines.join("；")}。精確值見下方的表。`);
}

// 每顆星一格：星、星座、判定的標記；選了外來時，同一格加上外來的判定（讀〈外來〉一區的表）。
function dignityGlance(section) {
  const model = tableModel(section, (table) => table.columns.join("|")
    === `天體|星座|${window.ChartViewModel.DEGREE_IN_SIGN_COLUMN}|廟|旺|陷|弱|判定`);
  if (!model || !model.rows.length) return null;
  const peregrineSection = pageState.currentViewTree
    && pageState.currentViewTree.sections.find((item) => item.id === "dignity_peregrine" && item.status.state === "present");
  const peregrineModel = peregrineSection
    ? tableModel(peregrineSection, (table) => table.columns[0] === "天體" && table.columns[3] === "判定") : null;
  const peregrineBy = new Map(peregrineModel ? peregrineModel.rows.map((row) => [row[0], row[3]]) : []);
  const title = peregrineModel ? "七顆行星一覽：廟、旺、陷、弱與外來" : "七顆行星一覽：廟、旺、陷、弱";
  const host = glanceShell(title);
  const lines = [];
  host.classList.add("glance-dignity");
  const list = make("ul", "glance-planets");
  model.rows.forEach((row) => {
    const [name, sign, , , , , , judgment] = row.map((cell) => String(cell == null ? "" : cell));
    const item = make("li", "glance-planet");
    const marks = make("span", "glance-marks");
    const parts = listParts(judgment, DIGNITY_MARK_SIDE);
    if (parts) parts.filter((part) => part.side).forEach((part) => marks.appendChild(stateMark(part.text, part.side)));
    else marks.appendChild(stateMark(judgment, "quiet"));
    const peregrine = peregrineBy.get(name);
    if (peregrine) {
      const side = peregrine === "外來" ? "debility" : (peregrine.startsWith("無法判定") ? "neutral" : "quiet");
      marks.appendChild(stateMark(peregrine, side));
    }
    item.append(bodyLabel(name), signLabel(sign), marks);
    list.appendChild(item);
    lines.push(`${name}在${sign}，${[judgment].concat(peregrine ? [peregrine] : []).join("，")}`);
  });
  host.appendChild(list);
  host.appendChild(make("p", "glance-key", GLANCE_KEY_TEXT + (peregrineModel ? "外來依 Lilly 1647 判，細節在〈外來〉一區。" : "")));
  nameGlance(host, title, lines);
  return host;
}

/** 廟旺陷弱表：判定欄加標記；判定是在陷／在弱…時，對應那一欄的星座標成「這一格就是它現在的星座」。 */
function decorateDignityTable(host) {
  const table = host.querySelector('table[data-section="dignity_domicile_exaltation"]');
  if (!table) return;
  const judgments = columnCells(table, "判定");
  const hit = { 入廟: "廟", 入旺: "旺", 在陷: "陷", 在弱: "弱" };
  judgments.forEach((cell, rowIndex) => {
    const text = cell.textContent;
    const parts = listParts(text, DIGNITY_MARK_SIDE);
    if (!parts) { cell.classList.add("is-quiet"); return; }
    markCell(cell, parts);
    // 「牡羊、天蠍」這種兩個星座的格，只標出它現在所在的那一個。
    const sign = columnCells(table, "星座")[rowIndex];
    parts.filter((part) => part.side).forEach((part) => {
      const target = columnCells(table, hit[part.text])[rowIndex];
      if (!target || !sign) return;
      const items = target.textContent.split("、");
      if (!items.includes(sign.textContent)) return;
      target.replaceChildren(...items.flatMap((item, index) => (index ? ["、"] : [])
        .concat([item === sign.textContent ? make("span", "sign-hit", item) : item])));
    });
  });
}

function decoratePeregrineTable(host) {
  const table = host.querySelector('table[data-section="dignity_peregrine"]');
  if (!table) return;
  columnCells(table, "判定").forEach((cell) => {
    const text = cell.textContent;
    if (text === "外來") markCell(cell, [{ text, side: "debility" }]);
    else if (text.startsWith("無法判定")) markCell(cell, [{ text, side: "neutral" }]);
    else cell.classList.add("is-quiet");
  });
  // 有的尊貴照字（一格常有兩三項，全框起來太吵）；同時在的陷、弱加虛線框，與廟旺陷弱表一致。
  ["同時在"].forEach((name) => columnCells(table, name).forEach((cell) => {
    const parts = cell.textContent === GLANCE_DASH ? null : listParts(cell.textContent, PEREGRINE_MARK_SIDE);
    if (parts) markCell(cell, parts);
  }));
}

// 行速、停滯與東出西入。度分秒字串（「14°38′38.77″」「59′08″」「2′00″35‴」）換成度；讀不懂回 null（不畫橫條）。
function dmsDegrees(text) {
  const match = /^(?:(\d+)°)?(?:(\d+)′)?(?:(\d+(?:\.\d+)?)″)?(?:(\d+)‴)?$/.exec(String(text || "").trim());
  if (!match || !match.slice(1).some((part) => part !== undefined)) return null;
  const [deg, min, sec, third] = match.slice(1).map((part) => (part === undefined ? 0 : Number(part)));
  return deg + min / 60 + sec / 3600 + third / 216000;
}

/** 「出生前 14.8 天」「代表性時刻後 3.0 小時」換成日數（前為負）；讀不懂回 null。 */
function offsetDays(text) {
  const match = /(前|後) (\d+(?:\.\d+)?) (天|小時)$/.exec(String(text || ""));
  if (!match) return null;
  const value = Number(match[2]) / (match[3] === "小時" ? 24 : 1);
  return match[1] === "前" ? -value : value;
}

// 橫條：這一刻每天走的度數，刻度到平均的兩倍，平均是正中那條直線；超過兩倍的停在右端並畫一個缺口。
// 逆行畫空心（比的是每天退的度數，與表格同一句）。橫條只是圖，aria-hidden；數字在旁邊的字裡。
const SPEED_SCALE = 2;
function speedGauge(daily, mean, retrograde) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "speed-gauge");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const ratio = daily / mean / SPEED_SCALE;
  const shape = (tag, attributes) => {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    svg.appendChild(node);
    return node;
  };
  shape("rect", { class: "speed-track", x: "0", y: "3", width: "100%", height: "8" });
  if (ratio > 0) {
    shape("rect", {
      class: retrograde ? "speed-bar is-retrograde" : "speed-bar",
      x: "0.5", y: "3.5", width: `${(Math.min(ratio, 1) * 100).toFixed(2)}%`, height: "7",
    });
  }
  if (ratio > 1) shape("line", { class: "speed-over", x1: "97%", x2: "97%", y1: "1", y2: "13" });
  shape("line", { class: "speed-mean", x1: "50%", x2: "50%", y1: "0", y2: "14" });
  return svg;
}

// 轉向時間軸：出生（或代表性時刻）在正中，左右各到搜尋的天數；每一次轉向一根標竿，標上星名與哪一次。
// 標籤太近時往上疊一層。位置用百分比，字級固定，窄螢幕不縮字。精確時刻在下面的表。
const TURN_LABEL_EM = 13;     // 標籤字級（px），與 calculate.css 的 .turn-label 一致
const TURN_ASSUMED_WIDTH = 330;  // 估算碰撞用的寬度：取手機可用寬度，桌機只會更鬆
function turnTimeline(model, windowDays, anchorLabel) {
  const turns = model.rows.map((row) => ({
    planet: String(row[0]), which: String(row[1]), days: offsetDays(row[2]),
  })).filter((turn) => turn.days !== null && Math.abs(turn.days) <= windowDays);
  if (!turns.length) return null;
  const place = (days) => (days + windowDays) / (2 * windowDays);
  // 依位置排，逐一放進第一個不重疊的層；寬度用字數估。
  const lanes = [];
  turns.sort((a, b) => a.days - b.days).forEach((turn) => {
    const text = `${turn.planet}　${turn.which}`;
    const width = text.length * TURN_LABEL_EM / TURN_ASSUMED_WIDTH;
    const x = place(turn.days);
    const anchor = x < 0.3 ? "start" : (x > 0.7 ? "end" : "middle");
    const left = anchor === "start" ? x : (anchor === "end" ? x - width : x - width / 2);
    let lane = lanes.findIndex((end) => left > end + 0.02);
    if (lane < 0) { lanes.push(0); lane = lanes.length - 1; }
    lanes[lane] = left + width;
    Object.assign(turn, { text, x, anchor, lane });
  });
  const laneHeight = 20;
  const axisY = 12 + lanes.length * laneHeight + 8;
  const height = axisY + 24;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("class", "turn-timeline");
  svg.setAttribute("height", String(height));
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const inner = document.createElementNS(SVG_NS, "svg");
  // 左右各留 1.5%，最外側的字不貼邊。
  inner.setAttribute("x", "1.5%");
  inner.setAttribute("width", "97%");
  inner.setAttribute("overflow", "visible");
  svg.appendChild(inner);
  const shape = (tag, attributes, text) => {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    inner.appendChild(node);
    return node;
  };
  shape("line", { class: "turn-axis", x1: "0%", x2: "100%", y1: axisY, y2: axisY });
  const step = windowDays % 5 === 0 ? 5 : windowDays;
  for (let day = -windowDays; day <= windowDays; day += step) {
    const x = `${(place(day) * 100).toFixed(2)}%`;
    shape("line", { class: day === 0 ? "turn-tick is-anchor" : "turn-tick", x1: x, x2: x, y1: axisY - (day === 0 ? 8 : 4), y2: axisY + 4 });
    const label = day === 0 ? anchorLabel : `${day < 0 ? "−" : "+"}${Math.abs(day)}${Math.abs(day) === windowDays ? " 天" : ""}`;
    const anchor = day === -windowDays ? "start" : (day === windowDays ? "end" : "middle");
    shape("text", { class: day === 0 ? "turn-scale is-anchor" : "turn-scale", x, y: axisY + 19, "text-anchor": anchor }, label);
  }
  turns.forEach((turn) => {
    const x = `${(turn.x * 100).toFixed(2)}%`;
    const labelY = 12 + (lanes.length - 1 - turn.lane) * laneHeight + 4;
    shape("line", { class: "turn-stem", x1: x, x2: x, y1: labelY + 5, y2: axisY });
    shape("circle", { class: "turn-dot", cx: x, cy: axisY, r: 4 });
    shape("text", { class: "turn-label", x, y: labelY, "text-anchor": turn.anchor }, turn.text);
  });
  return svg;
}

// 停滯那一格的開頭（「停滯（第一次：…）；…」只取分號前，與表格同一份字）。
const MOTION_COURSE_SHORT = Object.freeze({
  "行速快（swift）": "行速快", "行速慢（slow）": "行速慢", "等於平均（到原典印出的那一位）": "等於平均",
});

function motionGlance(section) {
  const main = tableModel(section, (table) => table.columns.join("|")
    === "天體|這一刻每天走|順行或逆行|Lilly 的平均每日行度|行速|停滯|東出或西入");
  if (!main || !main.rows.length) return null;
  const p115 = tableModel(section, (table) => table.title.startsWith("Lilly 的強弱表"));
  const p115By = new Map(p115 ? p115.rows.map((row) => [row[0], row]) : []);
  const title = main.title.startsWith("代表性時刻") ? "七顆星在代表性時刻" : "七顆星這一刻";
  const host = glanceShell(title);
  const lines = [];
  host.classList.add("glance-motion");
  const list = make("ul", "glance-motion-rows");
  main.rows.forEach((row) => {
    const [name, daily, direction, mean, course, station, side] = row.map((cell) => String(cell == null ? "" : cell));
    const listed = p115By.get(name) || [];
    const item = make("li", "glance-motion-row");
    const speed = make("span", "glance-speed");
    const dailyDegrees = dmsDegrees(daily);
    const meanDegrees = dmsDegrees(mean);
    const retrograde = direction === "逆行";
    if (dailyDegrees !== null && meanDegrees) speed.appendChild(speedGauge(dailyDegrees, meanDegrees, retrograde));
    const numbers = make("span", "glance-speed-text");
    numbers.append(make("span", "glance-speed-value", `每天 ${daily}`), make("span", "glance-speed-value", `平均 ${mean}`));
    speed.appendChild(numbers);
    const marks = make("span", "glance-marks");
    const courseHead = course.split("；")[0];
    if (MOTION_COURSE_SHORT[courseHead]) {
      marks.appendChild(stateMark(MOTION_COURSE_SHORT[courseHead], p115Side(listed[1]) || "neutral"));
    }
    if (retrograde) marks.appendChild(stateMark("逆行", "neutral"));
    if (station.startsWith("停滯")) marks.appendChild(stateMark(station.split("；")[0], "neutral"));
    if (side === "晨星（東出）" || side === "昏星（西入）") { marks.appendChild(stateMark(side, p115Side(listed[2]) || "neutral")); }
    item.append(bodyLabel(name), speed, marks);
    list.appendChild(item);
    lines.push(`${name}每天 ${daily}，平均 ${mean}，${[...marks.childNodes].map((mark) => mark.textContent).join("、")}`);
  });
  host.appendChild(list);
  host.appendChild(make("p", "glance-key",
    "橫條是這一刻每天走的度數，中間的直線是 Lilly 的平均每日行度，到右端是平均的兩倍（超過兩倍停在右端）；"
    + "空心的橫條是逆行，比的是每天退的度數。" + (p115 ? GLANCE_KEY_TEXT : "")));
  const turns = tableModel(section, (table) => /前後 \d+ 天內的轉向時刻/.test(table.title));
  if (turns) {
    const windowDays = Number(/前後 (\d+) 天/.exec(turns.title)[1]);
    const timeline = windowDays > 0 ? turnTimeline(turns, windowDays, turns.title.startsWith("代表性時刻") ? "代表性時刻" : "出生") : null;
    if (timeline) {
      const figure = make("div", "glance-turns");
      figure.appendChild(make("p", "glance-subtitle", `前後 ${windowDays} 天內的轉向（精確時刻見下方的表）`));
      figure.appendChild(timeline);
      host.appendChild(figure);
      lines.push(`前後 ${windowDays} 天內的轉向：`
        + turns.rows.filter((row) => offsetDays(row[2]) !== null).map((row) => `${row[0]}${row[2]}${row[1]}`).join("，"));
    }
  }
  nameGlance(host, title, lines);
  return host;
}

/** 行速主表與 p.115 表：行速、東出西入、Lilly 的分邊加標記（框線取同一列在 p.115 表的那一格）。 */
function decorateMotionTables(host, section) {
  const tables = [...host.querySelectorAll('table[data-section="motion_states"]')];
  const p115Model = tableModel(section, (table) => table.title.startsWith("Lilly 的強弱表"));
  const p115Rows = p115Model ? p115Model.rows : [];
  tables.forEach((table) => {
    const caption = table.caption ? table.caption.textContent : "";
    if (caption.startsWith("Lilly 的強弱表")) {
      ["行速", "東出或西入"].forEach((name) => columnCells(table, name).forEach((cell) => {
        const text = cell.textContent;
        const head = Object.keys(P115_SIDE).find((label) => text.startsWith(label));
        if (head) markCell(cell, [{ text: head, side: P115_SIDE[head] }].concat(text.length > head.length ? [{ text: text.slice(head.length) }] : []));
      }));
      return;
    }
    const heads = [...table.tHead.rows[0].cells].map((cell) => cell.textContent);
    if (!heads.includes("東出或西入") || !heads.includes("停滯")) return;
    columnCells(table, "行速").forEach((cell, index) => {
      const text = cell.textContent;
      const head = text.split("；")[0];
      const listed = p115Rows[index] || [];
      if (!MOTION_COURSE_SHORT[head]) return;
      markCell(cell, [{ text: head, side: p115Side(listed[1]) || "neutral" }]
        .concat(text.length > head.length ? [{ text: text.slice(head.length) }] : []));
    });
    columnCells(table, "東出或西入").forEach((cell, index) => {
      const text = cell.textContent;
      const listed = p115Rows[index] || [];
      if (text === "晨星（東出）" || text === "昏星（西入）") markCell(cell, [{ text, side: p115Side(listed[2]) || "neutral" }]);
      else cell.classList.add("is-quiet");
    });
    columnCells(table, "停滯").forEach((cell) => {
      const text = cell.textContent;
      if (!text.startsWith("停滯")) { cell.classList.add("is-quiet"); return; }
      const head = text.split("；")[0];
      markCell(cell, [{ text: head, side: "neutral" }].concat(text.length > head.length ? [{ text: text.slice(head.length) }] : []));
    });
    columnCells(table, "順行或逆行").forEach((cell) => {
      if (cell.textContent === "逆行") markCell(cell, [{ text: "逆行", side: "neutral" }]);
    });
  });
}

// 指向方法頁的一句（十二分部區的九分部）：畫面上做成連結與較輕的旁註；字一個不改。
const SECTION_XREFS = Object.freeze({ dodecatemoria: [["九分部（novenaria", "方法頁〈十二分部〉一節", "/zh-TW/methods#novenaria"]] });
function linkCrossReferences(host, sectionId) {
  (SECTION_XREFS[sectionId] || []).forEach(([prefix, phrase, href]) => {
    const note = [...host.querySelectorAll("p.section-note")].find((node) => node.textContent.startsWith(prefix));
    if (!note) return;
    note.classList.add("section-xref");
    const text = [...note.childNodes].find((node) => node.nodeType === 3 && node.data.includes(phrase));
    if (!text) return;
    const hit = text.splitText(text.data.indexOf(phrase));
    hit.splitText(phrase.length);
    const link = document.createElement("a");
    link.href = href;
    link.textContent = phrase;
    hit.replaceWith(link);
  });
}

// 對照表各欄的代碼（profile_id）：view-model 把它寫在說明裡一句（匯出照帶）。畫面上那一句拆成
// 一張兩欄小表，代碼用 <code>，蛇形底線的識別碼不夾在中文段落裡；複製與匯出仍是原句。
const PROFILE_ID_PREFIX = "對照表各欄的代碼（profile_id，與 JSON 的 profile_results 同名，供程式對應）：";
// 欄名限 120 字：不設上限時，一段很長又沒有「＝」的文字會讓每個起點都掃到段尾（二次方）。
const PROFILE_ID_PAIR = /([^、＝：]{1,120})＝([a-z0-9_]+)/g;
function profileIdTables(host) {
  host.querySelectorAll("p.section-note").forEach((note) => {
    const text = note.textContent;
    const at = text.indexOf(PROFILE_ID_PREFIX);
    if (at < 0) return;
    const pairs = [...text.slice(at + PROFILE_ID_PREFIX.length).matchAll(PROFILE_ID_PAIR)];
    if (!pairs.length) return;
    const table = make("table", "profile-ids");
    table.appendChild(make("caption", undefined, "對照表各欄的代碼（與 JSON 的 profile_results 同名，供程式對應）"));
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    ["對照表的欄", "profile_id"].forEach((label) => {
      const th = make("th", undefined, label);
      th.scope = "col";
      headRow.appendChild(th);
    });
    head.appendChild(headRow);
    const body = document.createElement("tbody");
    pairs.forEach(([, label, code]) => {
      const row = document.createElement("tr");
      const th = make("th", undefined, label.trim());
      th.scope = "row";
      const td = document.createElement("td");
      td.appendChild(make("code", undefined, code));
      row.append(th, td);
      body.appendChild(row);
    });
    table.append(head, body);
    // 不用 .table-wrap：那是各套完整表的摺疊（profile-table）認的外框，這張小表不收進摺疊。
    const wrap = make("div", "profile-ids-wrap");
    wrap.dataset.canonical = text.slice(at);
    wrap.appendChild(table);
    const before = text.slice(0, at).trim();
    if (before) note.textContent = before;
    else note.remove();
    // 小表排在各家對照與各套完整表之後：區段裡第一張表仍是各家對照。
    const tables = host.querySelectorAll(".table-wrap");
    if (tables.length) tables[tables.length - 1].after(wrap);
    else if (before) note.after(wrap);
    else host.appendChild(wrap);
  });
}

/** 本質尊貴各區的英文來源行（「來源：…」）：畫面上排成較輕的引文，字不改。 */
function quietSourceNotes(host, sectionId) {
  if (!sectionId.startsWith("dignity_")) return;
  host.querySelectorAll("p.section-note").forEach((note) => {
    if (note.textContent.startsWith("來源：")) note.classList.add("section-cite");
  });
}

// 全部並列：各家對照一覽（界、三分性、面；十二分部）。讀這幾區 canonical 的「各家對照：…」表（view-model 的
// comparisonTable），字一個不改：每顆星一張卡，同一技法裡說同一個答案的表放在同一行（依答案分組，表名照目錄順序）；各家
// 相同的星收成一行，有不同的才展開。不印比數、不照幾家相同排序、不用顏色：「有不同」只是一個細實線框的字，不表示哪一家
// 對。面的兩套型別不同（行星與星座），只並排、不比。
const COMPARISON_PREFIX = "各家對照：";
const COMPARISON_DIGNITY_ORDER = Object.freeze(["dignity_bounds", "dignity_triplicity", "dignity_face_decan"]);
const COMPARISON_VERDICT = Object.freeze({
  相同: "same", 有不同: "differ", "無法比：日夜盤未知": "unknown", "不比：一套是行星、一套是星座": "not_compared",
});
const COMPARISON_MARK = Object.freeze({
  same: ["各家相同", "quiet"], differ: ["有不同", "differ"], unknown: ["無法比", "neutral"], not_compared: ["不比", "quiet"],
});

/** 一張「各家對照」表 → { label, rows:[{ name, where, answers:[{school, text}], verdict }] }；讀不懂回 null。 */
function comparisonModel(section) {
  const table = tableModel(section, (item) => String(item.title).startsWith(COMPARISON_PREFIX));
  if (!table || !table.rows.length) return null;
  // 「各家」整欄相同時收成表下註（面／旬每一列都是「不比」）；那時這一欄不在表上。
  const verdictColumn = table.columns[table.columns.length - 1] === "各家";
  if (!verdictColumn && !(table.notes || []).some((note) => note.includes("「各家」一欄每一列都是「不比"))) return null;
  const fixed = table.columns[0] === "點" ? 2 : 3;
  const schools = table.columns.slice(fixed, verdictColumn ? -1 : undefined);
  const rows = table.rows.map((row) => {
    const cells = row.map((cell) => String(cell == null ? "" : cell));
    return {
      name: cells[0], sign: fixed === 3 ? cells[1] : null, where: fixed === 3 ? cells[2] : cells[1],
      answers: schools.map((school, index) => ({ school, text: cells[fixed + index] })),
      verdict: verdictColumn ? COMPARISON_VERDICT[cells[cells.length - 1]] || null : "not_compared",
    };
  });
  if (rows.some((row) => !row.verdict)) return null;
  return { label: String(table.title).slice(COMPARISON_PREFIX.length), rows };
}

/** 同一個答案的表收成一組；組的順序照第一個說它的表（也就是目錄順序）。 */
function answerGroups(answers) {
  const groups = [];
  answers.forEach(({ school, text }) => {
    const group = groups.find((item) => item.text === text);
    if (group) group.schools.push(school);
    else groups.push({ text, schools: [school] });
  });
  return groups;
}

/** 答案前加符號：行星或星座（十二分部「金牛（金星）」取括號前的星座）；其他照原字。 */
function answerLabel(text) {
  const node = make("span", "cmp-answer");
  // 名稱不含「（」：第一個全形左括號就是分界，不必在每個「（」都回溯到句尾。
  const match = /^([^（]+)（(.+)）$/.exec(text);
  const head = match ? match[1] : text;
  const glyph = tableGlyphs().bodies.get(head) || tableGlyphs().signs.get(head);
  if (glyph) node.appendChild(tableGlyph(glyph));
  node.append(head);
  if (match) node.appendChild(make("span", "cmp-answer-lord", `（${match[2]}）`));
  return node;
}

/** 表名：研究用的表把「（研究用）」排成小標籤，字不改。 */
function schoolLabel(name) {
  const node = make("span", "cmp-school");
  const research = name.endsWith("（研究用）");
  node.append(research ? name.slice(0, -"（研究用）".length) : name);
  if (research) node.appendChild(make("span", "cmp-research", "（研究用）"));
  return node;
}

/** 一顆星（或一個點）在全部技法下的判斷：任一技法有不同→有不同；否則有無法比→無法比；否則相同。 */
function subjectVerdict(lines) {
  const compared = lines.filter((line) => line.verdict !== "not_compared");
  if (!compared.length) return "not_compared";
  if (compared.some((line) => line.verdict === "differ")) return "differ";
  if (compared.some((line) => line.verdict === "unknown")) return "unknown";
  return "same";
}

function comparisonCard(subject, lines) {
  const verdict = subjectVerdict(lines);
  const card = make("li", "cmp-card");
  card.dataset.verdict = verdict;
  const head = make("div", "cmp-head");
  head.appendChild(bodyLabel(subject.name));
  const where = make("span", "cmp-where");
  if (subject.sign) where.appendChild(signLabel(subject.sign));
  where.appendChild(make("span", "cmp-degree", subject.where));
  head.appendChild(where);
  const [markText, side] = COMPARISON_MARK[verdict];
  head.appendChild(stateMark(markText, side));
  card.appendChild(head);
  const sentences = [];
  if (verdict === "same" || verdict === "not_compared") {
    // 收成一行：每個技法一個答案（面的兩套並排，用「／」隔開）。
    const line = make("p", "cmp-line");
    lines.forEach((item) => {
      const part = make("span", "cmp-line-part");
      if (item.label) part.appendChild(make("span", "cmp-tech", item.label));
      answerGroups(item.answers).forEach((group, index) => {
        if (index) part.appendChild(make("span", "cmp-slash", "／"));
        part.appendChild(answerLabel(group.text));
      });
      line.appendChild(part);
      sentences.push(`${item.label || ""}${answerGroups(item.answers).map((group) => group.text).join("／")}`);
    });
    card.appendChild(line);
  } else {
    const list = make("dl", lines.some((item) => item.label) ? "cmp-rows" : "cmp-rows no-tech");
    lines.forEach((item) => {
      const term = make("dt", "cmp-tech", item.label || "");
      const detail = make("dd", "cmp-groups");
      const groups = answerGroups(item.answers);
      if (item.verdict === "same") {
        const group = make("span", "cmp-group");
        group.append(answerLabel(groups[0].text), make("span", "cmp-schools is-all", "各家相同"));
        detail.appendChild(group);
        sentences.push(`${item.label || ""}各家相同，${groups[0].text}`);
      } else {
        groups.forEach((entry) => {
          const group = make("span", "cmp-group");
          const schools = make("span", "cmp-schools");
          entry.schools.forEach((school, index) => {
            if (index) schools.appendChild(make("span", "cmp-sep", "、"));
            schools.appendChild(schoolLabel(school));
          });
          group.append(answerLabel(entry.text), schools);
          detail.appendChild(group);
        });
        sentences.push(`${item.label || ""}${groups.map((entry) => `${entry.schools.join("、")}說${entry.text}`).join("，")}`);
      }
      if (item.label) list.append(term, detail);
      else list.append(detail);
    });
    card.appendChild(list);
  }
  return { card, verdict, sentence: `${subject.name}${subject.sign ? `在${subject.sign}` : ""}：${markText}；${sentences.join("；")}` };
}

/**
 * 一覽：models 是 [{ label, rows }]（同一批星、同一順序），label 為 null 時卡片不寫技法名（十二分部）。
 * 回傳一覽節點；讀不懂就回 null，表格照舊。
 */
function comparisonGlance(title, models, unit) {
  if (!models.length) return null;
  const subjects = models[0].rows;
  if (models.some((model) => model.rows.length !== subjects.length
    || model.rows.some((row, index) => row.name !== subjects[index].name))) return null;
  const host = glanceShell(title);
  host.classList.add("glance-compare");
  const list = make("ul", "cmp-cards");
  const counts = { same: 0, differ: 0, unknown: 0 };
  const sentences = [];
  subjects.forEach((subject, index) => {
    const lines = models.map((model) => ({ label: model.label, answers: model.rows[index].answers, verdict: model.rows[index].verdict }));
    const { card, verdict, sentence } = comparisonCard(subject, lines);
    if (verdict in counts) counts[verdict] += 1;
    list.appendChild(card);
    sentences.push(sentence);
  });
  const tally = [["各家相同", counts.same], ["有不同", counts.differ], ["無法比", counts.unknown]]
    .filter(([, count]) => count).map(([name, count]) => `${name} ${count} ${unit}`).join(" · ");
  if (tally) host.appendChild(make("p", "cmp-tally", tally));
  host.appendChild(list);
  host.appendChild(make("p", "glance-key",
    "依答案分組：同一個答案的表寫在同一行，表名照目錄順序。各家相同的收成一行，有不同的才展開；"
    + "「有不同」的框只是提示，不表示哪一家對，也不照幾家相同排序。"
    + (models.some((model) => model.rows.some((row) => row.verdict === "not_compared"))
      ? "面的兩套一套是行星、一套是星座，只並排，不比。" : "")
    + "精確值與各套的完整表在下方。"));
  nameGlance(host, title, (tally ? [tally] : []).concat(sentences));
  return host;
}

// 界的對照圖版（全部並列）。讀這一區每一套的「完整界段」表（view tree，字與下方的表同一份），不另算：每顆星一列、每套表
// 一欄，一條 0–30° 的細框條；這顆星所在的那一段界畫斜線與兩條邊，圈裡是那一段的界主，紅色直線是這顆星在星座內的度數。列
// 首一條紅線＝各套的界主不一致（只標「有不同」，不表示哪一家對）。寬版是一張矩陣；窄版每顆星一張小圖版、各套上下疊。整
// 張圖是 role="img"，名稱是逐星逐套的一句話。
const BOUNDS_FULL_SUFFIX = "：完整界段";
const BOUNDS_RULER_SHORT = Object.freeze({ 土星: "土", 木星: "木", 火星: "火", 金星: "金", 水星: "水" });

/** 一套「完整界段」表 → { name, rows:[{ body, sign, degreeText, ruler, start, end, degree }] }；讀不懂回 null。 */
function boundsProfileModel(table) {
  const column = (label) => table.columns.indexOf(label);
  const at = { body: 0, sign: column("星座"), degree: column(window.ChartViewModel.DEGREE_IN_SIGN_COLUMN),
    ruler: column("守護"), range: column("界段") };
  if (at.sign < 0 || at.degree < 0 || at.ruler < 0 || at.range < 0) return null;
  const rows = table.rows.map((row) => {
    const cell = (index) => String(row[index] == null ? "" : row[index]).trim();
    const range = /^(\d+)°–(\d+)°$/.exec(cell(at.range));
    const degree = /^(\d+)°(\d+)′/.exec(cell(at.degree));
    const start = range ? Number(range[1]) : null;
    const end = range ? Number(range[2]) : null;
    return {
      body: cell(at.body), sign: cell(at.sign), degreeText: cell(at.degree), ruler: cell(at.ruler), rangeText: cell(at.range),
      start: range && start < end && end <= 30 ? start : null, end: range && start < end && end <= 30 ? end : null,
      degree: degree ? Number(degree[1]) + Number(degree[2]) / 60 : null,
    };
  });
  return { name: String(table.title).slice(0, -BOUNDS_FULL_SUFFIX.length), rows };
}

function boundsPlateModel(section) {
  const profiles = section.children.filter((child) => child.type === "table" && String(child.title).endsWith(BOUNDS_FULL_SUFFIX))
    .map(boundsProfileModel);
  if (profiles.length < 2 || profiles.some((profile) => !profile || !profile.rows.length)) return null;
  const bodies = profiles[0].rows.map((row) => row.body);
  if (profiles.some((profile) => profile.rows.length !== bodies.length
    || profile.rows.some((row, index) => row.body !== bodies[index]))) return null;
  return { profiles, bodies };
}

function plateNode(name, attributes = {}, parent = null) {
  const node = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, String(value)));
  if (parent) parent.appendChild(node);
  return node;
}
function plateText(parent, x, y, content, className, anchor = "start") {
  const node = plateNode("text", { x, y, class: className, "text-anchor": anchor }, parent);
  node.textContent = content;
  return node;
}
function plateGlyph(parent, key, cx, cy, size, className) {
  const glyph = key && tableGlyphs().glyphs[key];
  if (!glyph) return;
  const [x0, y0, x1, y1] = glyph.bbox;
  const scale = size / Math.max(x1 - x0, y1 - y0);
  plateNode("path", { d: glyph.d, class: className, transform: `matrix(${scale} 0 0 ${scale} `
    + `${(cx - (scale * (x0 + x1)) / 2).toFixed(2)} ${(cy - (scale * (y0 + y1)) / 2).toFixed(2)})` }, parent);
}
function plateSvg(width, height, hatchId) {
  const svg = plateNode("svg", { viewBox: `0 0 ${width} ${height}`, class: "bp-svg", "aria-hidden": "true", focusable: "false" });
  const defs = plateNode("defs", {}, svg);
  const pattern = plateNode("pattern", { id: hatchId, width: 5, height: 5, patternUnits: "userSpaceOnUse",
    patternTransform: "rotate(45)" }, defs);
  plateNode("line", { x1: 0, y1: 0, x2: 0, y2: 5, class: "bp-hatch-line" }, pattern);
  plateNode("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "bp-plate" }, svg);
  plateNode("rect", { x: 4.5, y: 4.5, width: width - 9, height: height - 9, class: "bp-plate-in" }, svg);
  return svg;
}
/** 一條 0–30° 的框條：x..x+w；所在界段斜線＋兩條邊、圈內界主、星的度數。 */
function plateStrip(parent, x, y, w, h, row, hatchId) {
  const at = (degree) => x + (degree / 30) * w;
  plateNode("rect", { x, y, width: w, height: h, class: "bp-frame" }, parent);
  [10, 20].forEach((degree) => plateNode("line", { x1: at(degree), y1: y + h - 3, x2: at(degree), y2: y + h, class: "bp-tick" }, parent));
  const ranged = row.start !== null;
  if (ranged) {
    plateNode("rect", { x: at(row.start), y, width: at(row.end) - at(row.start), height: h, class: "bp-bound",
      fill: `url(#${hatchId})` }, parent);
    [row.start, row.end].forEach((degree) => plateNode("line", { x1: at(degree), y1: y, x2: at(degree), y2: y + h, class: "bp-edge" }, parent));
  }
  if (row.degree !== null) plateNode("line", { x1: at(row.degree), y1: y - 4, x2: at(row.degree), y2: y + h + 4, class: "bp-body" }, parent);
  const cx = ranged ? (at(row.start) + at(row.end)) / 2 : x + w / 2;
  const key = tableGlyphs().bodies.get(row.ruler);
  if (key && ranged) {
    plateNode("circle", { cx, cy: y + h / 2, r: h / 2 - 1.5, class: "bp-ring" }, parent);
    plateGlyph(parent, key, cx, y + h / 2, h * 0.52, "bp-gl");
  }
  // 框條下面一行小字：界主（一字）與界段；讀不懂的界段照原字寫出界主與界段，不畫斜線。
  const label = ranged ? `${BOUNDS_RULER_SHORT[row.ruler] || row.ruler} ${row.start}°–${row.end}°`
    : [row.ruler, row.rangeText].filter(Boolean).join(" ");
  const anchor = cx - x < 24 ? "start" : x + w - cx < 24 ? "end" : "middle";
  plateText(parent, anchor === "start" ? x : anchor === "end" ? x + w : cx, y + h + 14, label, "bp-t bp-small", anchor);
}
// 只從數字串的開頭試：從中間的每一位數起跑，一長串不以 ″ 結尾的數字會變成二次方。
const plateDegree = (text) => text.replace(/(?<!\d)\d+(?:\.\d+)?″$/, "");
const plateDiffers = (model, index) => new Set(model.profiles.map((profile) => profile.rows[index].ruler)).size > 1;

function boundsPlateMatrix(model) {
  const nameW = 128;
  const cellW = 200;
  const gap = 18;
  const rowH = 60;
  const width = nameW + model.profiles.length * (cellW + gap);
  const height = 46 + model.bodies.length * rowH + 22;
  const hatchId = "bp-hatch-wide";
  const svg = plateSvg(width, height, hatchId);
  svg.classList.add("bp-wide");
  model.profiles.forEach((profile, column) => plateText(svg, nameW + column * (cellW + gap), 32, profile.name, "bp-t bp-head"));
  model.bodies.forEach((body, index) => {
    const y = 46 + index * rowH;
    const group = plateNode("g", {}, svg);
    if (index) plateNode("line", { x1: 14, y1: y - 7, x2: width - 14, y2: y - 7, class: "bp-rule" }, group);
    if (plateDiffers(model, index)) plateNode("line", { x1: 12, y1: y + 2, x2: 12, y2: y + 42, class: "bp-differ-bar" }, group);
    plateGlyph(group, tableGlyphs().bodies.get(body), 28, y + 14, 15, "bp-gl");
    plateText(group, 42, y + 19, body, "bp-t bp-name");
    const first = model.profiles[0].rows[index];
    plateText(group, 42, y + 37, `${first.sign} ${plateDegree(first.degreeText)}`, "bp-t bp-small bp-dim");
    model.profiles.forEach((profile, column) => plateStrip(group, nameW + column * (cellW + gap), y + 4, cellW, 22,
      profile.rows[index], hatchId));
  });
  model.profiles.forEach((_profile, column) => {
    const x = nameW + column * (cellW + gap);
    [0, 10, 20, 30].forEach((degree) => plateText(svg, x + (degree / 30) * cellW, height - 14, `${degree}°`,
      "bp-t bp-small bp-num", degree === 0 ? "start" : degree === 30 ? "end" : "middle"));
  });
  return svg;
}

function boundsPlateStack(model) {
  const list = make("div", "bp-stack");
  const width = 340;
  const rowH = 44;
  model.bodies.forEach((body, index) => {
    const height = 42 + model.profiles.length * rowH + 6;
    const hatchId = `bp-hatch-${index}`;
    const svg = plateSvg(width, height, hatchId);
    const first = model.profiles[0].rows[index];
    if (plateDiffers(model, index)) plateNode("line", { x1: 9, y1: 12, x2: 9, y2: 32, class: "bp-differ-bar" }, svg);
    plateGlyph(svg, tableGlyphs().bodies.get(body), 23, 22, 14, "bp-gl");
    plateText(svg, 37, 27, body, "bp-t bp-name");
    plateText(svg, width - 14, 27, `${first.sign} ${plateDegree(first.degreeText)}`, "bp-t bp-small bp-dim", "end");
    model.profiles.forEach((profile, row) => {
      const y = 42 + row * rowH;
      plateText(svg, 14, y + 16, profile.name.replace(/ 承襲界$/, ""), "bp-t bp-small");
      plateStrip(svg, 116, y + 3, 208, 18, profile.rows[index], hatchId);
    });
    list.appendChild(svg);
  });
  return list;
}

/** 界一區畫得出圖版時，界的對照由圖版承擔，不再進共用一覽的卡片（三分性與面照舊是卡片）。 */
function platedBounds(section) { return section.id === "dignity_bounds" && Boolean(boundsPlateModel(section)); }

/** 界一區（全部並列）的對照圖版；讀不懂就回 null，表格與一覽照舊。 */
function boundsPlate(section) {
  const model = boundsPlateModel(section);
  if (!model) return null;
  const host = glanceShell(`界的對照圖：${model.profiles.map((profile) => profile.name).join("、")}`);
  host.classList.add("bounds-plate");
  host.appendChild(boundsPlateMatrix(model));
  host.appendChild(boundsPlateStack(model));
  host.appendChild(make("p", "glance-key",
    "斜線是這顆星所在的那一段界，圈裡是那一段的界主；紅色直線是這顆星在星座內的度數；"
    + "列首的紅線表示各套的界主不一致（不表示哪一家對）。數字取自下方各套的「完整界段」表。"));
  const sentences = model.bodies.map((body, index) => {
    const first = model.profiles[0].rows[index];
    return `${body}在${first.sign} ${plateDegree(first.degreeText)}，`
      + model.profiles.map((profile) => {
        const row = profile.rows[index];
        return `${profile.name}${[row.ruler, row.rangeText].filter(Boolean).join(" ")}`;
      }).join("、")
      + (plateDiffers(model, index) ? "（界主有不同）" : "");
  });
  nameGlance(host, host.querySelector(".glance-title").textContent, sentences);
  return host;
}

/** 尊貴三區（選了全部並列的）共用一個一覽，放在第一個全部並列的區段；畫成圖版的界不在其中。 */
function dignityComparisonGlance() {
  if (!pageState.currentViewTree) return null;
  const models = COMPARISON_DIGNITY_ORDER.map((id) => {
    const section = pageState.currentViewTree.sections.find((item) => item.id === id && item.status.state === "present");
    return section && !platedBounds(section) ? comparisonModel(section) : null;
  }).filter(Boolean);
  if (!models.length) return null;
  return comparisonGlance(`七顆行星各家對照：${models.map((model) => model.label).join("、")}`, models, "顆");
}

function firstComparisonDignity() {
  if (!pageState.currentViewTree) return null;
  const found = pageState.currentViewTree.sections.find((item) => item.id.startsWith("dignity_")
    && item.status.state === "present" && !platedBounds(item) && comparisonModel(item));
  return found ? found.id : null;
}

// 全部並列一區的說明：第一段（算了哪幾套）與日夜盤的狀況留在外面，怎麼讀對照表與出處收進「說明與原典」。
const COMPARISON_EXPLAIN_PREFIXES = Object.freeze(["「各家」一欄", "三分性的對照只列", "面／旬的兩套守護者", "來源："]);
function foldComparisonNotes(host) {
  const notes = [...host.querySelectorAll(":scope > p.section-note")].filter((note) => (
    COMPARISON_EXPLAIN_PREFIXES.some((prefix) => note.textContent.startsWith(prefix))
    || /列為研究用：/.test(note.textContent)));
  if (!notes.length) return;
  const explain = makeFold("section-explain", "說明與原典");
  notes[0].before(explain);
  notes.forEach((note) => explain.appendChild(note));
}

/** 各套的完整表：每一套收進自己的摺疊（標題就是表名），預設收起；對照表照舊攤開。字與表一個不改。 */
function foldProfileTables(host) {
  [...host.querySelectorAll(".table-wrap")].forEach((wrap) => {
    const caption = wrap.querySelector("caption");
    const name = caption ? caption.textContent : "";
    if (!name || name.startsWith(COMPARISON_PREFIX)) return;
    const fold = makeFold("section-tables profile-table", name);
    wrap.before(fold);
    fold.appendChild(wrap);
    fold.addEventListener("toggle", applyOverflowRegions);
  });
}

/** 古典判斷三區的一覽與標記；其他區段不動。一覽放在標題列之後、任何摺疊之外。 */
function decorateClassicalSection(host, section) {
  quietSourceNotes(host, section.id);
  profileIdTables(host);
  linkCrossReferences(host, section.id);
  let glance = null;
  if (section.id === "dignity_domicile_exaltation") {
    glance = dignityGlance(section);
    decorateDignityTable(host);
  } else if (section.id === "dignity_peregrine") {
    decoratePeregrineTable(host);
  } else if (/^dignity_(bounds|face_decan|triplicity)$/.test(section.id) && comparisonModel(section)) {
    // 全部並列：三區共用一個一覽，放在第一個全部並列的區段；每一區的各套完整表各自收起。
    // 界畫得出圖版時，界一區放圖版，三分性與面的卡片放在下一個全部並列的區段。
    glance = section.id === "dignity_bounds" ? boundsPlate(section) : null;
    if (!glance && firstComparisonDignity() === section.id) glance = dignityComparisonGlance();
    foldProfileTables(host);
    foldComparisonNotes(host);
  } else if (section.id === "dodecatemoria" && comparisonModel(section)) {
    const model = comparisonModel(section);
    glance = comparisonGlance("十二分部：兩種算法逐點對照", [{ ...model, label: null }], "個點");
  } else if (section.id === "motion_states") {
    glance = motionGlance(section);
    decorateMotionTables(host, section);
    // 一覽與時間軸已把每顆星的狀態攤在畫面上；四、五張逐格的表收進一個預設收起的「詳細數值」。
    // 只在一覽畫得出來時收：畫不出來（讀不懂表）就照舊攤開，不讓答案藏在摺疊裡。
    if (glance) foldTables(host, "詳細數值");
  }
  if (glance) host.querySelector(".head").after(glance);
}

/** 把這一區所有的表依序移進一個預設收起的摺疊，放在第一張表原來的位置；字與表一個不改。 */
function foldTables(host, label) {
  const wraps = [...host.querySelectorAll(".table-wrap")];
  if (!wraps.length) return;
  const fold = makeFold("section-tables", `${label}（${wraps.length} 張表）`);
  wraps[0].before(fold);
  wraps.forEach((wrap) => fold.appendChild(wrap));
  // 收起時表格不在版面上；展開後重量溢出，可橫捲的表才保有 region／tabindex／標籤。
  fold.addEventListener("toggle", applyOverflowRegions);
}

// 區段說明裡第一次出現、名詞解釋有條目的詞，做成與章節導言同一種可點的詞（.term，點了打開名詞解釋
// 並捲到那一條，glossary.js 在 document 上接線）。只換畫面上的節點，字一個不改；匯出讀 canonical
// sections，不經過這裡。找不到那個詞（例如這次的說明沒有提到）就不加，不另外補字。
const SECTION_TERMS = Object.freeze({
  fixed_stars: [["fixed_stars", "恆星"]], prenatal_points: [["prenatal_syzygy", "產前朔望"]],
  antiscia: [["antiscia", "反照點"]], dodecatemoria: [["dodecatemoria", "十二分部"], ["novenaria", "九分部"]],
  aspects: [["aversion", "不合意"]], lunar_mansions: [["lunar_mansions", "月宿"]], void_of_course: [["void_of_course", "月空亡"]],
  solar_phase: [["cazimi", "日輪內"], ["combust", "焦傷"], ["under_beams", "在光束下"]],
  motion_states: [["swift_slow", "行速快慢"], ["stationary", "停滯"], ["oriental_occidental", "東出西入"]],
  dignity_peregrine: [["peregrine", "外來"]],
  classical_classifications: [["benefic_malefic", "吉星"], ["joys", "喜樂"], ["hayz", "Hayz 與 halb"], ["house_triad", "始宮"]],
});
function linkGlossaryTerms(host, sectionId) {
  const glossary = window.ArmillaryGlossary;
  const terms = SECTION_TERMS[sectionId];
  if (!terms || !glossary) return;
  const known = new Set(glossary.ENTRIES.map((entry) => entry.key));
  // 先找摺疊外看得到的說明，再找「說明與原典」摺疊裡的：收起的摺疊裡的詞點不到。
  const all = [...host.querySelectorAll("p.section-note")];
  const notes = all.filter((note) => !note.closest("details")).concat(all.filter((note) => note.closest("details")));
  terms.forEach(([key, word]) => {
    if (!known.has(key)) return;
    for (const note of notes) {
      const text = [...note.childNodes].find((node) => node.nodeType === 3 && node.data.includes(word));
      if (!text) continue;
      const hit = text.splitText(text.data.indexOf(word));
      hit.splitText(word.length);
      const button = make("button", "term");
      button.type = "button";
      button.dataset.term = key;
      button.textContent = word;
      hit.replaceWith(button);
      return;
    }
  });
}

// 出生時間不確定時的白話摘要，放在星盤圖與速覽之後：第一行是結論，接著說取了哪些時刻、
// 哪些結果會變（大約幾點變）、哪些不變、哪些沒有比較，最後連到敏感度區的細節。null 時清空並隱藏。
function renderBirthTimeSummary(summary) {
  samplingCalloutHost.replaceChildren();
  samplingCalloutHost.hidden = !summary;
  birthTimeNoticeHost.replaceChildren();
  birthTimeNoticeHost.hidden = !summary;
  if (!summary) return;
  // 結果最上方的一行（每一章都看得到）：整行是連到摘要的連結。
  const notice = document.createElement("a");
  notice.href = `#${summary.notice_target_id}`;
  notice.textContent = summary.notice_text;
  birthTimeNoticeHost.appendChild(notice);
  const title = make("h3", "sampling-callout-title", summary.title);
  title.id = "sampling-callout-title";
  samplingCalloutHost.append(title, make("p", "sampling-callout-lead", summary.lead), make("p", "sampling-callout-intro", summary.intro));
  if (summary.changes.length) {
    samplingCalloutHost.appendChild(make("h4", "sampling-callout-heading", "會變的"));
    const list = document.createElement("ul");
    list.className = "sampling-callout-changes";
    summary.changes.forEach((change) => {
      const item = document.createElement("li");
      const what = make("span", "sampling-callout-what", `${change.what}：`);
      item.append(what, make("span", "sampling-callout-when", change.when));
      list.appendChild(item);
    });
    samplingCalloutHost.appendChild(list);
  }
  [
    ["不變的", summary.same], ["只比較了一部分", summary.partial], ["沒有比較，只算了上面那一刻", summary.unchecked],
  ].forEach(([label, items]) => {
    if (!items.length) return;
    const line = make("p", "sampling-callout-line", "");
    line.append(make("b", "sampling-callout-line-label", `${label}：`), document.createTextNode(`${items.join("、")}。`));
    samplingCalloutHost.appendChild(line);
  });
  samplingCalloutHost.appendChild(make("p", "note sampling-callout-caveat", summary.caveat));
  const link = document.createElement("a");
  link.className = "sampling-callout-link";
  link.href = `#${summary.target_id}`;
  link.textContent = summary.link_text;
  // 連結字只有「看細節」，給輔助科技補上看的是什麼。
  link.setAttribute("aria-label", "看細節：出生時刻敏感度");
  samplingCalloutHost.appendChild(link);
}

// 本命盤速覽。表後那一行的〈區段標題〉換成連到畫面上那一區的連結，文字不變
// （匯出印的是同一句）；沒有畫出的區段照原字。null 時清空並隱藏。
function renderSummary(section, linkable) {
  summaryHost.replaceChildren();
  summaryHost.hidden = !section;
  if (!section) return;
  const node = materializeSection(section);
  // 速覽緊貼星盤圖，不另起一個區塊標頭：標題留給輔助科技與大綱，「複製本區」由常用匯出的「複製結果」承擔。
  const head = node.querySelector(":scope > .head");
  if (head) { head.querySelectorAll(".section-copy").forEach((button) => button.remove()); head.classList.add("visually-hidden"); }
  const targets = new Map(linkable.map((item) => [item.title, `#section-${item.id}`]));
  node.querySelectorAll(".section-block").forEach((note) => {
    // 篇名不含「〈」：沒有收尾的「〈」不會讓後面每一個「〈」都掃到句尾。
    const parts = note.textContent.split(/〈([^〈〉]+)〉/);
    if (parts.length === 1) return;
    note.replaceChildren();
    parts.forEach((part, index) => {
      const href = index % 2 === 1 ? targets.get(part) : null;
      if (!href) { if (part) note.append(index % 2 === 1 ? `〈${part}〉` : part); return; }
      const link = document.createElement("a");
      link.href = href;
      link.textContent = part;
      note.append("〈", link, "〉");
    });
  });
  summaryHost.appendChild(node);
}
