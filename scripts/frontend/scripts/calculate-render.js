// 計算頁：畫出結果、圖表連動、結果與表單的綁定、驗算資料與章節。

/** 每一章放區塊的容器清空（章的標題、說明與靜態內容不動）。 */
function clearChapterHosts() {
  chapterHosts.forEach((host) => host.replaceChildren());
}

const POSITION_COLUMNS = Object.freeze(["星座度數", "行進"]);

function housesByName(tree) {
  const brief = window.ChartViewModel.printBriefRows(tree);
  return new Map(brief ? brief.rows.map((row) => [row[0], row[2]]) : []);
}

function positionsShowFull() {
  return pageState.positionsFull === null ? !(pageState.resultMode && pageState.resultMode.compactPositions) : pageState.positionsFull;
}

/** 天體位置表：標出只在全欄時顯示的格，插入只在四欄時顯示的「宮」，表上方一顆切換鈕。 */
function decoratePositionTable(wrap, model) {
  const table = wrap.querySelector("table");
  const keep = new Set([0, ...POSITION_COLUMNS.map((name) => model.columns.indexOf(name))]);
  const motion = model.columns.indexOf("行進");
  if ([...keep].some((index) => index < 0) || motion < 1) return null;
  table.id = "positions-table";
  const rows = [table.tHead.rows[0], ...table.tBodies[0].rows];
  rows.forEach((tr, rowIndex) => {
    [...tr.cells].forEach((cell, index) => { if (!keep.has(index)) cell.dataset.fullOnly = ""; });
    const house = document.createElement(rowIndex === 0 ? "th" : "td");
    if (rowIndex === 0) house.scope = "col";
    house.dataset.compactOnly = "";
    house.textContent = rowIndex === 0 ? "宮" : (pageState.positionHouses.get(model.rows[rowIndex - 1][0]) || DASH_TEXT);
    tr.insertBefore(house, tr.cells[motion]);
  });
  const bar = make("div", "table-columns");
  const button = make("button", "ghost small positions-columns");
  button.type = "button";
  button.setAttribute("aria-controls", table.id);
  bar.appendChild(button);
  paintPositionTable(table, button, model.columns.length);
  button.addEventListener("click", () => {
    pageState.positionsFull = !positionsShowFull();
    paintPositionTable(table, button, model.columns.length);
    applyOverflowRegions();
  });
  return bar;
}
const DASH_TEXT = "—";

function paintPositionTable(table, button, fullCount) {
  const full = positionsShowFull();
  table.classList.toggle("is-compact", !full);
  button.textContent = full ? "只顯示常用的 4 欄" : `顯示全部 ${fullCount} 欄`;
}

// 注意事項：每一則都只是提醒時，任何寬度都先收成一行——則數與第一則的開頭，點開看全文，
// 星盤圖不被整張清單推下去；只要有一則可能影響時間、時區或方法，就整張打開。
// 「只是提醒」是下面這張閉集：後端一律標 notice、只說哪些結果對出生時刻敏感或哪個模組這次不適用的代碼。
// 預設的 page 回應不帶嚴重度，所以靠代碼（契約：比對 code，不比對 message）；不在表上的代碼（含新代碼）一律不收。
// 清單本身（#warnings）與匯出讀的是同一份，開合只是畫面。
const INFORMATIONAL_NOTICES = new Set([
  "body_near_house_cusp", "body_near_sign_boundary", "moon_near_lunar_mansion_boundary",
  "module_not_applicable", "module_not_applicable_in_mode",
]);
const informational = (warning) => INFORMATIONAL_NOTICES.has(warning.code);
// 警告文字裡提到的本站文章（後端 params.article_path，view tree 帶成 article_path）在畫面上做成連結；只接受本站
// /zh-TW/ 下的路徑，匯出仍是後端原句的純文字。句子寫成「〈篇名〉（路徑）」時，畫面以篇名作連結文字、
// 不再印出路徑（連結文字是一串網址時，讀者與螢幕閱讀器都看不出要去哪裡）；其他寫法就把路徑本身做成連結。
const SITE_ARTICLE_PATH = /^\/zh-TW\/[a-z0-9/-]+$/;
function appendWarningMessage(host, warning) {
  const message = String(warning.message);
  const path = Object.hasOwn(warning, "article_path") ? warning.article_path : null;
  const at = typeof path === "string" && SITE_ARTICLE_PATH.test(path) ? message.indexOf(path) : -1;
  if (at < 0) {
    host.textContent = message;
    return;
  }
  const link = document.createElement("a");
  link.href = path;
  const titled = message.slice(0, at).match(/〈([^〈〉]+)〉（$/);
  if (titled && message.startsWith("）", at + path.length)) {
    const start = at - titled[0].length;
    link.textContent = `〈${titled[1]}〉`;
    host.append(message.slice(0, start), link, message.slice(at + path.length + 1));
    return;
  }
  link.textContent = path;
  host.append(message.slice(0, at), link, message.slice(at + path.length));
}

function renderWarnings(warnings) {
  warningsHost.replaceChildren();
  warningsHost.hidden = warnings.length === 0;
  warningsFold.hidden = warningsHost.hidden;
  warnings.forEach((warning) => {
    const item = document.createElement("li");
    appendWarningMessage(item, warning);
    warningsHost.appendChild(item);
  });
  el("warnings-summary").textContent = warnings.length
    ? `注意事項 ${warnings.length} 則：${warnings[0].message}` : "";
  warningsFold.dataset.fold = warnings.every(informational) ? "notices" : "attention";
  warningsFold.open = warningsFold.dataset.fold === "attention";
}

/** 「技術細節與驗算資料」一區。頁面文件本身不含技術區段；這一區照樣建出，打開時才取得完整回應。 */
function technicalDetailsBlock(technicalSections) {
  const details = makeFold("technical-results", "技術細節與驗算資料");
  details.id = "technical-results";
  details.append(make("p", "note", "版本、來源、選項、計算軌跡與完整收據。一般閱讀不需要展開。"));
  // 列印只印已在畫面上的東西：驗算資料還沒取得時，這一區只有一句
  // 「打開這一區…」的操作說明，而列印藏起了 summary——紙上會留下指向不存在
  // 控制項的孤兒文字。calculate.css 的 print 規則依這個狀態把整區收起來。
  details.dataset.detail = verification.state === DETAIL.READY ? "ready" : "pending";
  if (verification.state === DETAIL.READY) {
    technicalSections.forEach(
      (section) => details.appendChild(materializeSection(section))
    );
  } else {
    details.appendChild(detailStatusBlock("technical"));
    // 只有使用者自己點開才取得：列印前的全部展開（beforeprint）不觸發第二次計算。
    details.querySelector("summary").addEventListener("click", () => {
      if (!details.open) loadVerificationDetail();
    });
  }
  return details;
}

function renderResponse(response, signature, payload) {
  let canonical;
  try {
    canonical = window.ChartExport.createDocument(
      response, window.ChartViewModel.buildSections(response)
    );
  } catch (error) {
    // 狀態權威缺席或殘缺：回應本身不完整，不是版本問題（exporters 的 assertRenderableResponse）。
    if (isIncompleteResponse(error)) {
      showIncompleteResponse();
      return;
    }
    // 回應裡的 schema/status 值不可信。即使以 textContent 顯示不會造成 XSS，
    // 把原始例外文字放進錯誤面板仍會讓對方的文字看起來像本站公告。
    showError("這個版本的頁面無法安全呈現本次回應。",
      ["重新載入頁面以取得對應版本。", "若重新載入後仍失敗，請透過聯絡頁回報。"]);
    setStatus("回應無法呈現。", "error");
    return;
  }

  lifecycle.setCanonicalDocument(canonical);
  sectionSnapshots.clear();
  canonical.sections.forEach((section) => sectionSnapshots.set(section.id, section));

  const tree = window.ChartViewModel.buildViewTree(canonical);
  pageState.currentViewTree = tree;

  renderBirthTimeSummary(tree.header.birth_time_summary);

  renderWarnings(tree.header.warnings);

  // 結果頁有三十個區塊、三百多列，所以分章，一次看一章。章節欄同時顯示每一區的收據狀態，
  // 讓「哪些被拒絕」在捲之前就看得到；這次沒有算的區塊不畫，在它那一章的最後列一行「加算」。
  const technicalIds = TECHNICAL_SECTION_IDS;
  const summarySection = tree.sections.find((section) => section.id === SUMMARY_SECTION_ID);
  const resultSections = tree.sections.filter(
    (section) => section.status.state !== "not_requested"
      && !technicalIds.has(section.id)
      && section.id !== SUMMARY_SECTION_ID
  );
  const technicalSections = tree.sections.filter(
    (section) => technicalIds.has(section.id)
  );
  const timeSection = resultSections.find((section) => section.id === TIME_SECTION_ID) || null;
  pageState.resultMode = Chapters.mode(pageState.currentModeId);
  if (pageState.lastRenderedMode !== pageState.resultMode.id) {
    el("first-time").open = Chapters.firstTimeOpen(pageState.resultMode.id, narrowScreen());
    pageState.lastRenderedMode = pageState.resultMode.id;
  }
  el("result-mode-name").textContent = pageState.resultMode.label;
  pageState.positionHouses = housesByName(tree);
  renderSummary(summarySection, resultSections);
  renderTimeBrief(timeSection);

  clearChapterHosts();
  const chapterFor = new Map(Chapters.assign(tree.sections.map((section) => section.id))
    .map((entry) => [entry.section, entry.chapter]));
  const hostFor = (section) => chapterHosts.get(chapterFor.get(section.id)) || chapterHosts.get("positions");
  const entries = new Map();
  const addEntry = (chapter, entry) => {
    if (!entries.has(chapter)) entries.set(chapter, []);
    entries.get(chapter).push(entry);
  };
  const hiddenTitles = [];
  resultSections.forEach((section) => {
    const node = materializeSection(section);
    const chapter = chapterFor.get(section.id);
    hostFor(section).appendChild(section === timeSection ? timeReceipt(node) : node);
    addEntry(chapter, { node, title: section.title, status: section.status });
    if (!pageState.resultMode.chapters.includes(chapter)) hiddenTitles.push(section.title);
  });
  mountChartWheel(canonical);
  // 星盤圖不是 view-model 的區段：畫出來了才列在總覽的第一項；畫不出來（只留一句說明）就不列。
  const wheel = el("chart-wheel");
  if (wheel && wheel.querySelector(".chart-wheel-figure svg")) {
    entries.set("overview", [{ node: wheel, title: wheel.querySelector("h3").textContent, status: null },
      ...(entries.get("overview") || [])]);
  }
  renderPrintBrief(tree, canonical);
  // 預設回應不含驗算資料；技術區塊等使用者打開時才取得。
  // 回應若本來就是完整版（沒有 projection 鍵），技術區塊照舊直接畫出。
  beginDetailBinding(canonical, payload);
  const details = technicalDetailsBlock(technicalSections);
  pageState.technicalHost = details;
  chapterHosts.get("receipt").appendChild(details);
  addEntry("receipt", { node: details, title: details.querySelector("summary").textContent, status: null });
  addEntry("receipt", { node: el("export-toolbar"), title: el("export-mode-title").textContent, status: null });

  // 這次沒有算、勾一個選項就能加算的區塊：古典完整與自訂列在各章最後；快速看盤只顯示四章，不列。
  if (pageState.resultMode.id !== "quick") {
    const absent = tree.sections.filter((section) => section.status.state === "not_requested"
      && !technicalIds.has(section.id) && section.id !== SUMMARY_SECTION_ID);
    pageState.resultMode.chapters.forEach((chapter) => {
      const block = absentBlock(chapter, absent.filter((section) => chapterFor.get(section.id) === chapter));
      if (block && chapterHosts.has(chapter)) chapterHosts.get(chapter).appendChild(block);
    });
  }
  buildChapterNav(entries);
  renderModeNote(hiddenTitles);
  el("chapter-timelords-entry").hidden = pageState.resultMode.chapters.includes("timelords");

  showAnnualPanel(payload);
  results.hidden = false;
  // 結果區打開之後分頁列才量得到寬度。
  paintChapterFade();
  pageState.boundInputSignature = signature;
  refreshResultBinding();
  applyOverflowRegions();
  setStatus("計算完成。", "info");
  // 古典完整：算完星盤接著排時間主星（表單上那一格勾著時）；與按「排出時間主星」是同一個請求。
  if (pageState.resultMode.timelordsAfterChart && el("plan-timelords").checked) loadAnnualPanel();
  // 回應已到，中止鈕已無事可做：先收起再捲動。手機上它在送出鈕下自成一列，等 finally 才收起，
  // 結果標題會在捲動途中往上移，停在視窗頂端之外。finally 照舊再收一次。
  cancelButton.hidden = true;
  // 從技法落地頁來的第一份結果：直接打開時間主星一章（這個模式沒有那一章就留在總覽）。
  if (linkedTechnique && !pageState.linkedChapterShown) pageState.linkedChapterShown = showChapter("timelords");
  enterResultView();
  revealResults();
}

// 返回鍵：算出結果時新增一筆歷史紀錄（網址不變，state 只有固定的 {view:"result"}，不含任何輸入），
// 手機的返回手勢因此先回到表單，而不是直接離開本頁。已在結果那一筆時（重新計算、加算）不再新增。
// 回到表單那一筆：表單內容與結果都留著（返回不是清除；要清除有「清除」兩顆鈕），捲回表單、焦點交給
// 模式選擇。再按前進：結果還在就捲回結果標題。換章不碰歷史紀錄。
const RESULT_VIEW = "result";
const inResultView = (state) => Boolean(state) && state.view === RESULT_VIEW;
function enterResultView() {
  if (inResultView(window.history.state)) return;
  // 兩筆是同一頁：瀏覽器自己的捲動還原會在 popstate 之後把畫面拉回送出當時的位置，蓋掉下面的捲動。
  if ("scrollRestoration" in window.history) window.history.scrollRestoration = "manual";
  window.history.pushState({ view: RESULT_VIEW }, "", window.location.pathname);
}
window.addEventListener("popstate", (event) => {
  const behavior = scrollBehavior();
  if (inResultView(event.state)) {
    if (results.hidden) return;
    const heading = el("results-heading");
    heading.scrollIntoView({ block: "start", behavior });
    heading.focus({ preventScroll: true });
    return;
  }
  el("mode-choice").scrollIntoView({ block: "start", behavior });
  focusCheckedMode();
});
function focusCheckedMode() {
  const mode = document.querySelector('input[name="calc-mode"]:checked');
  if (mode) mode.focus({ preventScroll: true });
}

// 結果到達時把結果標題捲到視窗頂端，焦點交給它（HTML 帶 tabindex="-1"），使用者才知道
// 畫面上多了什麼。只 focus() 時瀏覽器只捲到剛好看得見標題，畫面大半仍是表單。
// 偏好減少動態效果時直接跳到位置，不做平滑捲動。
function revealResults() {
  const added = addedSectionNode();
  if (added) {
    unfoldTarget(added);
    added.scrollIntoView({ block: "start", behavior: scrollBehavior() });
    focusSectionHeading(added);
    return;
  }
  const heading = el("results-heading");
  heading.scrollIntoView({ block: "start", behavior: scrollBehavior() });
  heading.focus({ preventScroll: true });
}

// 時間收據的一行重點：取「時間轉換」表格的本地時間（或代表性錨點）、時區與世界時三列，
// 名稱與數值都照表格原字；只把全為 0 的小數秒（「.000」）拿掉：輸入只到分鐘或秒，印出毫秒是假精度，
// 完整值仍在收據表格裡。時區只寫城市名（「臺北」），IANA 名稱留在完整收據與匯出。表格不是預期的形狀時
// 不畫這一行，完整收據照舊在最後。
function renderTimeBrief(section) {
  timeBrief.replaceChildren();
  timeBrief.hidden = true;
  const table = section && section.children.find((child) => child.type === "table");
  const rows = table ? table.rows : [];
  const zone = rows.findIndex((row) => row[0] === "時區");
  const offset = rows.findIndex((row) => row[0] === "UTC 偏移");
  if (zone !== 1 || offset !== 2 || rows.length < 4) return;
  [rows[0], rows[zone], rows[offset + 1]].forEach(([term, value], index) => {
    if (index) timeBrief.append(make("span", "visually-hidden", "；"));
    const item = make("span", "time-brief-item", "");
    const shown = index === 1 ? String(value).replace(/（[A-Za-z_]+\/[A-Za-z_/+-]+）$/, "")
      : String(value).replace(/(:\d\d)\.0+$/, "$1");
    item.append(make("span", "time-brief-term", term), " ", shown);
    timeBrief.append(item);
  });
  const link = document.createElement("a");
  link.href = "#time-receipt";
  link.className = "time-brief-link";
  link.textContent = "完整時間收據";
  timeBrief.append(make("span", "visually-hidden", "；"), link);
  timeBrief.hidden = false;
}

// 完整的時間轉換區收進預設收合的 <details>，排在各區之後、技術細節之前。
function timeReceipt(sectionNode) {
  const details = makeFold("time-receipt", "展開完整時間收據");
  details.id = "time-receipt";
  details.append(sectionNode);
  return details;
}

// 連到收合區塊裡的錨點（時間收據的一行重點、章內目錄的區塊）或跳到表格裡的一列時，先換到它
// 所在的那一章、打開它與它外層的每一個 <details>，再捲過去：沒顯示的章與收合中的元素都沒有版面
// 位置，捲動與焦點都會落空。跳到的是整個區塊時，也打開這一區自己的「展開這一區」：使用者點的是
// 這一區的名字，要看的是它的內容，不是一行摺疊鈕。
function unfoldTarget(target) {
  const chapter = chapterOf(target);
  if (chapter && !chapterVisible(chapter)) showChapter(chapter);
  // 這一章的區塊全部排版（calculate.css 的 content-visibility 對它不再生效）：未排版的區塊只有估計
  // 高度，捲到途中它們才排版、高度一變，目標就被推離章節列底下。只排這一章，其他章照樣延後。
  const chapterNode = chapter ? chapterNodes.get(chapter) : null;
  if (chapterNode) chapterNode.dataset.laidOut = "";
  for (let node = target; node; node = node.parentElement) {
    if (node.tagName === "DETAILS" && !node.open) node.open = true;
  }
  const own = target.matches && target.matches("section.result-section")
    ? target.querySelector(":scope > details.long-section") : null;
  if (own && !own.open) own.open = true;
}
// 區塊的標題：aria-labelledby 指的那一個，否則第一個 h2／h3。焦點交給它，閱讀器從那裡接著讀。
function focusSectionHeading(target) {
  const labelled = (target.getAttribute("aria-labelledby") || "").split(" ")[0];
  const heading = (labelled && document.getElementById(labelled)) || target.querySelector("h2, h3");
  if (!heading) return;
  if (!heading.hasAttribute("tabindex")) heading.tabIndex = -1;
  heading.focus({ preventScroll: true });
}
// 本頁不在網址上留 #片段（見 clearAddressInput）：結果區裡的錨點自己打開、捲動、交焦點，
// 不讓瀏覽器寫網址與歷史紀錄。區塊索引另有 followIndexLink，它先處理並 preventDefault。
results.addEventListener("click", (event) => {
  const link = event.target.closest && event.target.closest('a[href^="#"]');
  if (!link || event.defaultPrevented || event.button !== 0
    || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const target = document.getElementById(decodeURIComponent(link.getAttribute("href").slice(1)));
  if (!target) return;
  event.preventDefault();
  unfoldTarget(target);
  target.scrollIntoView({ behavior: scrollBehavior(), block: "start" });
  focusSectionHeading(target);
});

// 星盤圖：
// 圖由 canonical document 的 source_response 畫出（與表格同一份回應），放在結果首屏
// （#chart-wheel-host，桌機在速覽左側）。清除、重新計算與 pagehide 時與 #sections 一起清空
// （dropResultsForNewAttempt），放大的對話框也在區塊內。圖畫不出來時只留一句說明，表格照常。
const WHEEL_FILES = Object.freeze({ svg: "classical-astrology-chart.svg", png: "classical-astrology-chart.png" });

// 圖例十來條，攤開時比首屏的答案還佔地方：收在一個預設收起的「圖例」裡。圖仍以同一個清單元素
// 重畫圖例（chart-wheel.js 握著它），這裡只把它移進摺疊；列印前的全部展開照樣印出來。
function foldChartLegend(section) {
  const legend = section.querySelector(".chart-wheel-legend");
  if (!legend) return;
  const fold = makeFold("chart-wheel-legend-fold", "圖例：符號、線條與記號的意思");
  legend.replaceWith(fold);
  fold.append(legend);
}

// 圖版編號：結果頁上每一張圖（星盤圖或方盤、出生時刻取樣圖、界的對照圖、人生時間軸、太陽回歸盤）
// 依它在頁面上的順序編為「圖版 I、II…」，像書裡的圖版。號碼寫成真的文字（不是 CSS 計數器），畫面與
// 紙上同一個號碼，圖說也能引用；藏起的章（列印時會印出）照樣占號。圖是分次畫出的（時間主星另一個
// 請求），所以結果區有變動就重編一次；已對的號碼不再寫，不會自己觸發下一次。
const PLATE_SELECTOR = "#chart-wheel, .sampling, .bounds-plate, .tl-life, .tl-sr-wheel";
const PLATE_HEADING = ":scope > .head > h3, :scope > .head > h4, :scope > .tl-life-head > h3, :scope > .tl-life-head > h4";
const ROMAN = [[10, "X"], [9, "IX"], [5, "V"], [4, "IV"], [1, "I"]];
function romanNumeral(value) {
  let rest = value;
  return ROMAN.reduce((text, [size, letters]) => {
    while (rest >= size) { text += letters; rest -= size; }
    return text;
  }, "");
}
function plateLabel(plate) {
  const own = plate.querySelector(".plate-no");
  if (own) return own;
  const label = make("p", "plate-no");
  const heading = plate.querySelector(PLATE_HEADING);
  (heading ? heading.parentElement : plate).insertBefore(label, heading || plate.firstChild);
  return label;
}
function numberPlates() {
  [...results.querySelectorAll(PLATE_SELECTOR)].forEach((plate, index) => {
    const text = `圖版 ${romanNumeral(index + 1)}`;
    const label = plateLabel(plate);
    if (label.textContent !== text) label.textContent = text;
    // 星盤圖的圖說以它的圖版號開頭（「圖版 I：數值與表格同源…」）。
    const caption = plate.querySelector(":scope > .chart-wheel-caption");
    if (!caption) return;
    let ref = caption.querySelector(".plate-ref");
    if (!ref) {
      ref = make("span", "plate-ref");
      caption.prepend(ref);
    }
    if (ref.textContent !== `${text}：`) ref.textContent = `${text}：`;
  });
}
if (typeof MutationObserver === "function") {
  new MutationObserver(numberPlates).observe(results, { childList: true, subtree: true });
}

function mountChartWheel(canonical) {
  let section;
  try {
    const model = window.ChartWheel.buildModel(canonical.source_response);
    // 文字替代就是表格：圖說之外，aria-describedby 指向圖上各點所在的位置表與軸點；畫了相位線時
    // 也指向相位表。
    const drawsAspects = Boolean(model.aspects) && model.aspects.status === window.ChartWheelModel.ASPECT_STATUS.DRAWN;
    const describedBy = ["section-bodies", "section-nodes", "section-lunar_apsides", "section-angles",
      ...(drawsAspects ? ["section-aspects"] : [])]
      .filter((id) => results.querySelector(`#${id}`));
    section = window.ChartWheel.createSection(document, model, {
      describedBy, onDownload: downloadChartWheel, link: POINT_LINK_CALLBACKS,
      // 方盤：同一份回應的另一種畫法；畫不出來（沒有宮位）時是 null，區塊上就沒有切換鈕。
      alternate: window.ChartSquare.sectionOption(canonical.source_response),
    });
  } catch (_error) {
    section = window.ChartWheel.createFailureSection(document);
  }
  foldChartLegend(section);
  lifecycle.registerSectionNode(section);
  chartWheelHost.replaceChildren(section);
  // 圓盤或方盤：上一份結果選了方盤，這一份照樣先畫方盤（這一頁的變數，不寫儲存）。
  // 這份結果畫不出方盤（沒有宮位）時照舊是圓盤，選擇本身留著。
  if (pageState.chartStyle === "square") {
    const square = chartWheelHost.querySelector('input[name="chart-wheel-style"][value="square"]');
    if (square && !square.checked) {
      square.checked = true;
      square.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
}

function rememberChartStyle(event) {
  const input = event.target;
  if (input && input.name === "chart-wheel-style" && input.checked) {
    pageState.chartStyle = input.value === "square" ? "square" : "wheel";
  }
}
chartWheelHost.addEventListener("change", rememberChartStyle);

// 圖表連動：
// 星盤圖上的點、符號對照的按鈕與八張表（天體、月交點、月球拱點、軸點、速覽、行星落宮、逐度相位、
// 相位方格）的列或格都帶 data-points（後端的點鍵，view tree 的 points 給的）。標示只做一件事：
// 對 #results 裡相關的 [data-points] 加 is-linked，圖與符號對照的外框加 is-linking；選取時另加
// is-selected 與 has-selection。外觀全在 calculate.css（只認 class）。滑過是預覽，選取會一直留著，
// 直到按 Esc、「清除標示」、選另一點或結果被清掉。選取不捲動、不移焦點（手機沒有滑過預覽，捲走就
// 看不到圖上標了哪一點）；要到表格那一列另按「到表格看這一顆」。選取與清除由符號對照裡的
// role="status" 宣告；滑過與焦點的預覽不宣告。
const POINT_KEY = /^[a-z][a-z_]*$/;
// 跳表的目標：每個點鍵在這四張位置表裡只有一列，列的 id 是 point-<區塊>-<鍵>。
const POINT_TABLES = new Set(["bodies", "nodes", "lunar_apsides", "angles"]);
const pointLink = { selected: null, preview: null };

function pointKeys(value) {
  const keys = typeof value === "string" ? value.split(" ").filter(Boolean) : [];
  return keys.length && keys.every((key) => POINT_KEY.test(key)) ? keys : null;
}

// 每次滑過都要讀過結果裡每一個 data-points：同一個值只解析一次（值的種類只有點鍵與點對那麼多）。
const parsedPoints = new Map();
function cachedPointKeys(value) {
  if (!parsedPoints.has(value)) parsedPoints.set(value, pointKeys(value));
  return parsedPoints.get(value);
}

/** 一個鍵：凡是含它的元素（逐度相位的組合列也算）；一對鍵：只有這兩點本身與兩點之間的組合。 */
function linkedTo(node, keys) {
  const own = cachedPointKeys(node.getAttribute("data-points"));
  if (!own) return false;
  return keys.length === 1 ? own.includes(keys[0]) : own.every((key) => keys.includes(key));
}

function paintPointLink() {
  const selected = pointLink.selected ? [pointLink.selected] : null;
  const shown = pointLink.preview || selected;
  results.querySelectorAll("[data-points]").forEach((node) => {
    const isSelected = Boolean(selected) && linkedTo(node, selected);
    node.classList.toggle("is-linked", Boolean(shown) && (linkedTo(node, shown) || isSelected));
    node.classList.toggle("is-selected", isSelected);
    if (node.classList.contains("chart-wheel-symbol")) {
      if (isSelected) node.setAttribute("aria-current", "true");
      else node.removeAttribute("aria-current");
    }
  });
  results.querySelectorAll(".chart-wheel-figure, .chart-wheel-symbols").forEach((node) => {
    node.classList.toggle("is-linking", Boolean(shown));
    node.classList.toggle("has-selection", Boolean(selected));
  });
  results.querySelectorAll(".chart-wheel-symbols").forEach((block) => paintSymbolActions(block, selected));
}

/** 符號對照下方的兩顆鈕與選取宣告。名稱取自那一點的按鈕（看得見的那個字），方盤上沒有那一點時不給跳表鈕。 */
function paintSymbolActions(block, selected) {
  const nameNode = selected
    && block.querySelector(`.chart-wheel-symbol[data-points="${selected[0]}"] .chart-wheel-symbol-name`);
  const name = nameNode ? nameNode.textContent : "";
  const clear = block.querySelector(".chart-wheel-symbols-clear");
  if (clear) clear.hidden = !selected;
  const jump = block.querySelector(".chart-wheel-symbols-jump");
  if (jump) {
    jump.hidden = !name;
    if (name) jump.setAttribute("aria-label", `${jump.textContent}：${name}`);
    else jump.removeAttribute("aria-label");
  }
  const status = block.querySelector(".chart-wheel-symbols-status");
  if (!status) return;
  // 只在內容真的變了才寫：重畫（換字級）不重念一次。
  const next = name ? `已標示${name}，圖與表格同步標示。` : selected || !status.textContent ? "" : "已清除標示。";
  if (status.textContent !== next) status.textContent = next;
}

function previewPoint(value) {
  pointLink.preview = pointKeys(value);
  paintPointLink();
}

function clearPointLink() {
  pointLink.selected = null;
  pointLink.preview = null;
  paintPointLink();
}

/** 跳到位置表的那一列：打開外層摺疊、捲到畫面中央（減少動態時直接到位），焦點給列名格。網址不加 #。 */
function revealPointRow(key) {
  const row = [...results.querySelectorAll("tr[id^='point-']")]
    .find((node) => node.getAttribute("data-points") === key);
  if (!row) return;
  unfoldTarget(row);
  row.scrollIntoView({ block: "center", behavior: scrollBehavior() });
  const name = row.querySelector("th");
  if (!name) return;
  if (!name.hasAttribute("tabindex")) name.tabIndex = -1;
  name.focus({ preventScroll: true });
}

function selectPoint(value) {
  const keys = pointKeys(value);
  if (!keys || keys.length !== 1) return;
  pointLink.selected = keys[0];
  pointLink.preview = null;
  paintPointLink();
}

function revealSelectedPoint() {
  if (pointLink.selected) revealPointRow(pointLink.selected);
}

const POINT_LINK_CALLBACKS = Object.freeze({
  onPreview: previewPoint, onActivate: selectPoint, onClear: clearPointLink, onReveal: revealSelectedPoint,
  onRedraw: paintPointLink,
});

/** 表格這一側：view tree 的 points 寫成列（相位方格是欄標頭、列標頭與下三角的格）的 data-points。 */
function linkTableCells(table, model, sectionId) {
  const points = model.points;
  if (!points || !Array.isArray(points.rows)) return;
  const valid = (keys) => (Array.isArray(keys) ? pointKeys(keys.join(" ")) : null);
  const rows = [...table.tBodies[0].rows];
  if (model.variant === "aspect_grid") {
    const columns = Array.isArray(points.columns) ? points.columns : [];
    const heads = [...table.tHead.rows[0].cells];
    columns.forEach((key, index) => {
      if (index > 0 && heads[index] && valid([key])) heads[index].setAttribute("data-points", key);
    });
    rows.forEach((tr, rowIndex) => {
      const own = valid(points.rows[rowIndex]);
      if (!own || own.length !== 1) return;
      [...tr.cells].forEach((cell, index) => {
        if (index === 0) cell.setAttribute("data-points", own[0]);
        else if (index - 1 <= rowIndex && valid([columns[index]])) cell.setAttribute("data-points", `${own[0]} ${columns[index]}`);
      });
    });
    return;
  }
  rows.forEach((tr, rowIndex) => {
    const own = valid(points.rows[rowIndex]);
    if (!own) return;
    tr.setAttribute("data-points", own.join(" "));
    if (POINT_TABLES.has(sectionId) && own.length === 1) tr.id = `point-${sectionId}-${own[0]}`;
  });
}

// 表格滑過（只認滑鼠；觸控沒有 hover）也標示圖上的點。Esc 取消標示（放大檢視的 Esc 只關對話框）。
function previewFromTable(event) {
  if (event.pointerType !== "mouse" || !event.target.closest) return;
  const cell = event.target.closest("table [data-points]");
  if (cell) previewPoint(cell.getAttribute("data-points"));
}
function endTablePreview(event) {
  if (event.pointerType !== "mouse" || !event.target.closest || !event.target.closest("table [data-points]")) return;
  const into = event.relatedTarget && event.relatedTarget.closest ? event.relatedTarget.closest("table [data-points]") : null;
  if (!into) previewPoint(null);
}
function clearPointLinkOnEscape(event) {
  if (event.key !== "Escape" || event.defaultPrevented || (!pointLink.selected && !pointLink.preview)) return;
  if (event.target && event.target.closest && event.target.closest("dialog")) return;
  clearPointLink();
}
results.addEventListener("pointerover", previewFromTable);
results.addEventListener("pointerout", endTablePreview);
document.addEventListener("keydown", clearPointLinkOnEscape);

/**
 * 下載星盤圖。預設不印任何輸入；勾選時加一行與列印摘要同一組的輸入。相位線跟著頁面上
 * 「顯示相位線」的設定（showAspects 為 false 時不畫）。style 是 "square" 時下載方盤（沒有相位線）。
 */
function downloadChartWheel(format, includeInput, button, showAspects, style) {
  let canonical;
  try {
    canonical = requireExportableDocument("chart_data_only");
  } catch (error) {
    reportAt(button, `下載失敗：${error.message}`, "error");
    return;
  }
  const summary = includeInput
    ? [`輸入摘要：${printInputEntries().map(([term, value]) => `${term} ${value}`).join("；")}`]
    : null;
  const square = style === "square";
  const files = square ? window.ChartSquare.FILES : WHEEL_FILES;
  let model;
  try {
    model = square
      ? window.ChartSquare.buildModel(canonical.source_response, { inputSummary: summary })
      : window.ChartWheel.buildModel(canonical.source_response, { inputSummary: summary, aspects: showAspects !== false });
  } catch (_error) {
    reportAt(button, `下載失敗：這次的${square ? "方盤" : "星盤圖"}無法繪製。`, "error");
    return;
  }
  const isCurrent = () => {
    try { return lifecycle.requireCanonicalDocument() === canonical; } catch (_error) { return false; }
  };
  window.ChartWheel.downloadImage(document, lifecycle, model, format, files, isCurrent,
    (message, tone) => reportAt(button, message, tone));
}

const staleNotice = el("stale-notice");
// 結果最下方的完整工具列，加上首屏的常用匯出（data-quick-*）：兩組按鈕走同一套處理與停用規則。
// 列印鈕以 data-print-mode 標出它印哪一種（完整結果或一頁摘要）。
const exportButtons = document.querySelectorAll(
  "[data-copy], [data-download], [data-quick-copy], [data-quick-download], button[data-print-mode]"
);
const printBriefInput = el("print-brief-input");

function inputSignature(payload) {
  return JSON.stringify(payload);
}

function refreshResultBinding() {
  if (pageState.boundInputSignature === null) { setStale(false); return; }
  const built = buildPayload();
  const current = built.ok ? inputSignature(built.payload) : null;
  setStale(current !== pageState.boundInputSignature);
}

function setStale(stale) {
  // 「過期」的說法與複製／下載是否可用只有 view-model
  // 一個出處，這裡是 ChartViewModel.markStale 唯一的呼叫點。畫面上沒有樹（剛清除、尚未
  // 計算）時沒有東西可標，按鈕照 stale 旗標處理。
  const tree = stale && pageState.currentViewTree
    ? window.ChartViewModel.markStale(pageState.currentViewTree)
    : pageState.currentViewTree;
  const actions = tree
    ? tree.header.actions
    : { copy_enabled: !stale, download_enabled: !stale };
  if (stale) results.dataset.stale = "true";
  else delete results.dataset.stale;
  staleAnnualPanel(stale);
  staleNotice.hidden = !stale;
  if (stale && tree && tree.header.stale_notice) staleNotice.textContent = tree.header.stale_notice;
  pageState.lastExportActions = actions;
  applyExportAvailability();
}

/**
 * 複製、下載、列印與放大是否可按，只有這一處決定：畫面上沒有結果（剛載入、清除後）時
 * 全部停用——藏起來或移出 DOM 的按鈕仍可能被程式或舊的參照按到；結果過期時依
 * view-model 的 actions；選了「運算結果＋驗算資料」而驗算資料還沒到手時，複製與下載
 * 也先停用（列印照舊，它印的是畫面）。
 */
function applyExportAvailability() {
  const present = pageState.boundInputSignature !== null;
  const actions = present ? pageState.lastExportActions : { copy_enabled: false, download_enabled: false };
  const waitingForDetail = selectedExportMode() === "reproducibility_detail"
    && verification.state !== DETAIL.READY;
  exportButtons.forEach((button) => {
    const allowed = button.hasAttribute("data-download") || button.hasAttribute("data-quick-download")
      ? actions.download_enabled
      : actions.copy_enabled;
    button.disabled = !allowed
      || (waitingForDetail && !button.hasAttribute("data-print-mode"));
  });
  printBriefInput.disabled = el("print-brief-button").disabled;
  results.querySelectorAll(".section-copy").forEach((button) => {
    button.disabled = !actions.copy_enabled;
  });
  // 「加算」照表單原樣再送一次：結果已不對應目前的表單時停用，免得把改動一起送出而不自知。
  results.querySelectorAll(".chapter-add").forEach((button) => {
    button.disabled = !present || results.dataset.stale === "true";
  });
  // 星盤圖下載畫的是頁面那一份結果，不等驗算資料；結果過期時與其他下載一起停用。
  chartWheelHost.querySelectorAll(".chart-wheel-download").forEach((button) => {
    button.disabled = !actions.download_enabled;
  });
  // 放大只是換個大小看畫面上那張圖：結果過期時照舊可看，沒有結果時停用。
  chartWheelHost.querySelectorAll(".chart-wheel-enlarge").forEach((button) => {
    button.disabled = !present;
  });
}

/** 匯出用：結果存在、且仍與目前表單一致。任一不成立就拋。 */
function requireExportableDocument(mode) {
  const canonical = lifecycle.requireCanonicalDocument();
  if (results.dataset.stale === "true") {
    throw new Error("表單已改動，這份結果對應的不是目前的輸入。請重新計算，或把欄位改回原值。");
  }
  if (mode !== "reproducibility_detail") return canonical;
  // 「運算結果＋驗算資料」只由完整回應產生。
  if (verification.state !== DETAIL.READY || !verification.canonical) {
    throw new Error("驗算資料還沒取得。");
  }
  return verification.canonical;
}

// 驗算資料：
// 預設回應（projection=page）只帶頁面主體畫的欄位。使用者打開「技術細節與驗算資料」，
// 或選「運算結果＋驗算資料」準備匯出時，才以同一份輸入再送一次 projection=detailed：
// 伺服器重算，兩次之間什麼都不保存。第二份回應只接到畫面上那一份結果底下：
// 世代號擋掉結果換掉之後才回來的回應；ChartExport.bindsToPageDocument 要求計算軌跡
// 摘要、建置身分與頁面主體逐區相同。請求與逾時沿用 lifecycle：清除、新的送出與
// pagehide 都會中止它。
const detailStatusNodes = new Set();
const exportDetailStatus = detailStatusBlock("export");
el("export-mode-help").after(exportDetailStatus);
// 首屏常用匯出旁的同一句：常用匯出因為等驗算資料而停用時，首屏就看得到原因。字與顯示條件
// 和下方那一份出自同一個產生器（detailStatusText、renderDetailStatus）；狀態宣告只由下方那一份
// 做，同一句不念兩次。
el("quick-export-data-note").before(detailStatusBlock("quick", { announce: false, nameSuffix: "（常用匯出）" }));

function detailStatusBlock(place, { announce = true, nameSuffix = "" } = {}) {
  const block = make("div", "detail-status");
  block.dataset.place = place;
  const text = make("p", "note");
  if (announce) text.setAttribute("role", "status");
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "ghost small";
  retry.textContent = "重新取得驗算資料";
  // 兩顆同字的按鈕在按鈕清單裡分得開（WCAG 2.5.3：名稱以看得見的字開頭）。
  if (nameSuffix) retry.setAttribute("aria-label", `${retry.textContent}${nameSuffix}`);
  retry.hidden = true;
  retry.addEventListener("click", () => loadVerificationDetail());
  block.append(text, retry);
  detailStatusNodes.add(block);
  renderDetailStatus(block);
  return block;
}

function detailStatusText(place) {
  if (verification.state === DETAIL.LOADING) {
    return "正在取得驗算資料：以同一份輸入請伺服器再算一次，伺服器不保存任何資料。";
  }
  if (verification.state === DETAIL.FAILED) {
    return [`無法取得驗算資料：${verification.message}`, ...verification.actions].join(" ");
  }
  if (verification.state === DETAIL.READY) {
    return place === "export" ? "驗算資料已取得，可以複製或下載「運算結果＋驗算資料」。" : "";
  }
  return place === "export"
    ? ""
    : "尚未取得驗算資料。打開這一區，或選「運算結果＋驗算資料」時，才會以同一份輸入請伺服器再算一次。";
}

function renderDetailStatus(block) {
  // 首屏那一行（quick）照下方匯出工具列那一份（export）的字與顯示條件。
  const place = block.dataset.place === "quick" ? "export" : block.dataset.place;
  const text = detailStatusText(place);
  const [line, retry] = block.children;
  line.textContent = text;
  retry.hidden = verification.state !== DETAIL.FAILED;
  block.hidden = !text
    || (place === "export" && selectedExportMode() !== "reproducibility_detail");
}

function refreshDetailUi() {
  detailStatusNodes.forEach((block) => {
    if (block.isConnected) renderDetailStatus(block);
    else if (block.dataset.place !== "export") detailStatusNodes.delete(block);
  });
  applyExportAvailability();
}

/** 畫出新結果時：綁定它的請求；回應本來就是完整版時，驗算資料就是它自己。 */
function beginDetailBinding(canonical, payload) {
  pageState.resultGeneration += 1;
  pageState.pageCanonical = canonical;
  pageState.boundPayload = payload;
  pageState.technicalHost = null;
  if (window.ChartExport.holdsVerificationDetail(canonical)) {
    Object.assign(verification, { state: DETAIL.READY, canonical, message: "", actions: [] });
  } else {
    Object.assign(verification, { state: DETAIL.IDLE, canonical: null, message: "", actions: [] });
    // 技術區塊的快照只能來自完整回應；頁面版本算出的那幾區不留。
    TECHNICAL_SECTION_IDS.forEach((id) => sectionSnapshots.delete(id));
    if (selectedExportMode() === "reproducibility_detail") {
      window.setTimeout(() => loadVerificationDetail(), 0);
    }
  }
  refreshDetailUi();
}

function forgetDetailBinding() {
  pageState.resultGeneration += 1;
  pageState.pageCanonical = null;
  pageState.boundPayload = null;
  pageState.technicalHost = null;
  Object.assign(verification, { state: DETAIL.IDLE, canonical: null, message: "", actions: [] });
  refreshDetailUi();
}

function failDetail(message, actions) {
  Object.assign(verification, { state: DETAIL.FAILED, canonical: null, message, actions });
  refreshDetailUi();
}

function loadVerificationDetail() {
  if (!pageState.boundPayload || !pageState.pageCanonical) return;
  if (verification.state === DETAIL.LOADING || verification.state === DETAIL.READY) return;
  const generation = pageState.resultGeneration;
  const payload = pageState.boundPayload;
  const { controller, token, timeout } = lifecycle.beginTimedRequest(
    REQUEST_TIMEOUT_MS, window.setTimeout.bind(window)
  );
  Object.assign(verification, { state: DETAIL.LOADING, canonical: null, message: "", actions: [] });
  refreshDetailUi();
  const current = () => generation === pageState.resultGeneration && lifecycle.isCurrentRequest(token);
  // 同一份結果還在、但這次請求被別的動作中止（例如送出前那段等待裡按了中止）：
  // 回到「尚未取得」，使用者可以再打開一次。結果已換掉就什麼都不做。
  const abandoned = () => {
    if (generation === pageState.resultGeneration && verification.state === DETAIL.LOADING) {
      Object.assign(verification, { state: DETAIL.IDLE, canonical: null, message: "", actions: [] });
      refreshDetailUi();
    }
  };

  postJson("/api/chart?projection=detailed", payload, controller.signal)
    .then(({ response, body, invalidJsonMedia }) => {
      if (!current()) { abandoned(); return; }
      if (invalidJsonMedia) {
        failDetail("這次的驗算資料無法讀取：網站回傳的格式不對。", ["稍後再試一次。"]);
        return;
      }
      if (!response.ok) {
        const { detail, code } = refusalOf(body);
        failDetail(
          window.ClientContext.formatApiError(detail, response.status),
          window.ClientContext.apiErrorActions(
            response.status, response.headers.get("Retry-After"), code
          )
        );
        return;
      }
      let canonical;
      try {
        if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("shape");
        canonical = window.ChartExport.createDocument(
          body, window.ChartViewModel.buildSections(body)
        );
      } catch (error) {
        if (isIncompleteResponse(error)) {
          failDetail(INCOMPLETE_RESPONSE_MESSAGE, INCOMPLETE_RESPONSE_ACTIONS);
        } else {
          failDetail("這個版本的頁面無法安全呈現驗算資料。", ["重新載入頁面後再試一次。"]);
        }
        return;
      }
      if (!window.ChartExport.bindsToPageDocument(pageState.pageCanonical, canonical)) {
        failDetail(
          "驗算資料與畫面上的結果對不上，可能是服務在兩次請求之間更新了。",
          ["請重新計算一次，再取得驗算資料。"]
        );
        return;
      }
      applyDetailDocument(canonical);
    })
    .catch((error) => {
      if (!current()) { abandoned(); return; }
      if (error && error.name === "AbortError") {
        failDetail(
          timeout.didTimeout()
            ? `等待超過 ${REQUEST_TIMEOUT_MS / 1000} 秒，已停止等待。`
            : "已停止等待。",
          ["可以再試一次。"]
        );
        return;
      }
      failDetail(window.ClientContext.networkErrorMessage(), ["確認網路連線後再試一次。"]);
    })
    .finally(() => {
      window.clearTimeout(timeout.handle);
      if (lifecycle.isCurrentRequest(token)) lifecycle.finishRequest(token);
    });
}

function applyDetailDocument(canonical) {
  Object.assign(verification, { state: DETAIL.READY, canonical, message: "", actions: [] });
  canonical.sections
    .filter((section) => TECHNICAL_SECTION_IDS.has(section.id))
    .forEach((section) => sectionSnapshots.set(section.id, section));
  if (pageState.technicalHost && pageState.technicalHost.isConnected) {
    pageState.technicalHost.querySelectorAll(".detail-status").forEach((node) => node.remove());
    pageState.technicalHost.dataset.detail = "ready";
    const tree = window.ChartViewModel.buildViewTree(canonical);
    tree.sections
      .filter((section) => TECHNICAL_SECTION_IDS.has(section.id))
      .forEach((section) => pageState.technicalHost.appendChild(materializeSection(section)));
    applyOverflowRegions();
  }
  refreshDetailUi();
}

document.querySelectorAll('input[name="export-detail-mode"]').forEach((input) => {
  input.addEventListener("change", () => {
    if (selectedExportMode() === "reproducibility_detail") loadVerificationDetail();
    refreshDetailUi();
  });
});

// 可捲動表格的 region：
// 只有真的橫向溢出的表格才是 region 與 tab 停留點；未溢出時多一個
// 停留點只是噪音。標籤帶區塊標題，報讀時才分得出是哪一區的表。
// 結果區塊在畫面上是 content-visibility:auto（calculate.css）：離畫面遠的區塊不排版。量它裡面的
// 表格會逼它排版，把省下的時間吃回去，所以只量已排版的區塊；其餘的在接近畫面、開始排版時
// （contentvisibilityautostatechange）再量。不支援 content-visibility 的瀏覽器照舊全部量。
const laidOut = (node) => typeof node.checkVisibility !== "function"
  || !("contentVisibility" in document.documentElement.style)
  || node.checkVisibility({ contentVisibilityAuto: true });
function applyOverflowRegions(scope) {
  // 先量完全部再寫：邊量邊寫時，每寫一次屬性，下一次量就得重排一次版面。
  const wraps = [...(scope instanceof Element ? scope : results).querySelectorAll(".table-wrap")].filter(laidOut);
  // 差 1 px 以內是次像素取整，不算溢出（不給它鍵盤停留點）。
  const overflowing = wraps.map((wrap) => wrap.scrollWidth > wrap.clientWidth + 1);
  wraps.forEach((wrap, index) => {
    if (overflowing[index]) {
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", wrap.dataset.regionLabel);
      wrap.tabIndex = 0;
    } else {
      wrap.removeAttribute("role");
      wrap.removeAttribute("aria-label");
      wrap.removeAttribute("tabindex");
    }
  });
}
window.addEventListener("resize", () => {
  window.requestAnimationFrame(() => applyOverflowRegions());
});
// 這個事件不冒泡：在結果區以捕捉階段聽，任何一個區塊開始排版都量它自己的表格。
results.addEventListener("contentvisibilityautostatechange", (event) => {
  if (!event.skipped) applyOverflowRegions(event.target);
}, true);

// 結果的章：
// 捲動的 behavior：偏好減少動態效果時直接跳到位置，否則平滑捲動。
const scrollBehavior = () => (typeof window.matchMedia === "function"
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth");

// 結果分成六章，一次看一章。哪一區在哪一章、每種模式顯示哪幾章，只在 result-chapters.js 的表；
// 這裡只把畫出來的區塊放進它那一章、建章節欄、切換顯示。寬螢幕是左側黏性的章節欄，每章底下
// 列出這一章畫出來的區塊；窄螢幕是頂端一列橫捲的分頁（calculate.css）。章只在畫面上分組：
// 複製與下載讀 canonical 快照，列印時每一章都印（calculate.css 的 print 規則），所以匯出與列印
// 都不受分章影響。目前在哪一章只是這一頁的變數：不寫網址、不寫儲存；重新計算後留在同一章
// （那一章在新的模式裡不顯示時回到總覽），按「清除」才回到總覽。分頁會擋住瀏覽器的頁內搜尋，
// 所以有「全部章節一次展開」。
const chapterNodes = new Map(
  [...results.querySelectorAll("section.chapter[data-chapter]")].map((node) => [node.dataset.chapter, node])
);
// spy：全部章節展開時，視窗頂端（章節列底下）正在讀的那一章。
const chapterNav = { current: "overview", all: false, shown: new Set(), links: new Map(), spy: null };

function chapterOf(node) {
  const chapter = node && node.closest ? node.closest("section.chapter[data-chapter]") : null;
  return chapter ? chapter.dataset.chapter : null;
}

function chapterVisible(id) {
  return chapterNav.shown.has(id) && (chapterNav.all || chapterNav.current === id);
}

function paintChapters() {
  chapterNodes.forEach((node, id) => { node.hidden = !chapterVisible(id); });
  paintChapterLinks();
  el("chapters-all").setAttribute("aria-pressed", String(chapterNav.all));
}

// 一次看一章時，目前那一章是 aria-current="page"；全部章節展開時，捲到哪一章就標那一章
// （aria-current="location"），兩種模式的章節列都看得到自己在哪一章。
function paintChapterLinks() {
  if (chapterNav.all) chapterNav.spy = spiedChapter();
  chapterNav.links.forEach((link, id) => {
    const value = chapterNav.all ? (id === chapterNav.spy ? "location" : null)
      : (id === chapterNav.current ? "page" : null);
    if (value) link.setAttribute("aria-current", value);
    else link.removeAttribute("aria-current");
  });
}
/** 全部展開時正在讀的章：標題已捲過章節列底緣的最後一章；都還沒捲到時是第一章。 */
function spiedChapter() {
  const ids = [...chapterNav.links.keys()];
  const line = el("chapter-nav").getBoundingClientRect().bottom + 8;
  let spied = ids[0] || null;
  for (const id of ids) {
    const node = chapterNodes.get(id);
    if (node && !node.hidden && node.getBoundingClientRect().top <= line) spied = id;
  }
  return spied;
}
window.addEventListener("scroll", () => {
  if (!chapterNav.all || pageState.spyFrame || el("chapter-nav").hidden) return;
  pageState.spyFrame = window.requestAnimationFrame(() => {
    pageState.spyFrame = 0;
    const before = chapterNav.spy;
    paintChapterLinks();
    const link = chapterNav.links.get(chapterNav.spy);
    if (link && chapterNav.spy !== before) revealIndexLink(link);
  });
}, { passive: true });

/** 換到一章；這個模式不顯示的章不換（回 false）。 */
function showChapter(id) {
  if (!chapterNav.shown.has(id)) return false;
  chapterNav.current = id;
  paintChapters();
  // 隱藏的章裡表格寬 0，量不到溢出：換章後重量，可橫捲的表才保有 region／tabindex／標籤。
  applyOverflowRegions();
  // 換到的那一章置中在分頁列裡（點或觸控已放開，這時捲動不會點錯），兩旁的章也看得到。
  const link = chapterNav.links.get(id);
  if (link) revealIndexLink(link, { center: true });
  return true;
}

function clearChapterNav() {
  results.querySelectorAll(".chapter-contents").forEach((node) => node.remove());
  el("back-to-top").hidden = true;
  el("chapter-index").replaceChildren();
  delete el("chapter-index").dataset.more;
  chapterNav.links.clear();
  chapterNav.shown = new Set();
  el("chapter-nav").hidden = true;
  el("chapter-mode-note").replaceChildren();
  el("chapter-mode-note").hidden = true;
  // 沒有結果時每一章都收起；總覽不另收，它在 #results 裡跟著整區隱藏。
  chapterNodes.forEach((node, id) => {
    node.hidden = id !== "overview";
    delete node.dataset.laidOut;
  });
}

function indexLink(target, title, status) {
  const link = document.createElement("a");
  link.href = `#${target.id}`;
  link.className = "index-link";
  const name = document.createElement("span");
  name.textContent = title;
  link.appendChild(name);
  if (status && status.state !== "present") {
    const flag = make("span", "index-state");
    flag.dataset.state = status.state;
    // 狀態在畫面上靠間距與名稱分開；輔助科技讀的是連在一起的文字，補一個只給它的「：」。
    const separator = make("span", "visually-hidden", "：");
    flag.append(separator, status.label);
    link.appendChild(flag);
  }
  return link;
}

function chapterTitle(node) {
  if (node.dataset.navTitle) return node.dataset.navTitle;
  const heading = document.getElementById(node.getAttribute("aria-labelledby"));
  return heading ? heading.textContent : node.dataset.chapter;
}

/**
 * 章內目錄：章標題與導言之後一列「這一章有」，列出這一章畫出來的每一區（收據狀態照列）。一章十幾區時，
 * 不必往下捲就知道有什麼、點了就跳到那一區（收起的區跟著打開，見 unfoldTarget）。只有一區的章不列。
 * 分頁列只列章名：在手機上它是一列橫捲的分頁，放不下各區。
 */
function renderChapterContents(chapter, own) {
  const old = chapter.querySelector(".chapter-contents");
  if (old) old.remove();
  const head = chapter.querySelector(":scope > .chapter-head");
  if (!head || own.length < 2) return;
  const nav = make("nav", "chapter-contents");
  nav.setAttribute("aria-label", `這一章有：${chapterTitle(chapter)}`);
  nav.append(make("span", "chapter-contents-title", "這一章有"));
  const list = make("ul", "chapter-contents-list");
  own.forEach((entry) => {
    const row = document.createElement("li");
    row.appendChild(indexLink(entry.node, entry.title, entry.status));
    list.appendChild(row);
  });
  nav.appendChild(list);
  head.appendChild(nav);
}

/**
 * entries：章 id → 這一章畫出來的區塊 [{ node, title, status }]，照畫面順序。在區塊都放進畫面之後呼叫。
 */
function buildChapterNav(entries) {
  const host = el("chapter-index");
  host.replaceChildren();
  chapterNav.links.clear();
  chapterNav.shown = new Set(pageState.resultMode.chapters);
  if (!chapterNav.shown.has(chapterNav.current)) chapterNav.current = "overview";
  let number = 0;
  Chapters.CHAPTER_IDS.filter((id) => chapterNav.shown.has(id) && chapterNodes.has(id)).forEach((id) => {
    number += 1;
    const node = chapterNodes.get(id);
    const item = make("li", "chapter-item");
    const link = document.createElement("a");
    link.href = `#${node.id}`;
    link.className = "chapter-link";
    link.dataset.chapter = id;
    const count = make("span", "chapter-number", String(number));
    const name = make("span", "chapter-name", chapterTitle(node));
    link.append(count, name);
    // 很窄的螢幕只顯示短章名（calculate.css）；連結的名稱仍是完整章名，短名不給輔助科技重念一次。
    if (Chapters.SHORT_TITLES[id]) {
      const short = make("span", "chapter-name-short", Chapters.SHORT_TITLES[id]);
      short.setAttribute("aria-hidden", "true");
      link.appendChild(short);
    }
    item.appendChild(link);
    renderChapterContents(node, entries.get(id) || []);
    chapterNav.links.set(id, link);
    host.appendChild(item);
  });
  el("chapter-nav").hidden = false;
  paintChapters();
  paintChapterFade();
}

// 分頁列在自己的範圍裡橫捲：左右哪一邊還有章節，那一邊的邊緣淡出（calculate.css 依 data-more 畫）。
// 寬螢幕的章節欄不橫捲，兩邊都不標。
function paintChapterFade() {
  const strip = el("chapter-index");
  const room = strip.scrollWidth - strip.clientWidth;
  const more = [];
  if (room > 1 && strip.scrollLeft > 1) more.push("start");
  if (room > 1 && strip.scrollLeft < room - 1) more.push("end");
  if (more.length) strip.dataset.more = more.join(" ");
  else delete strip.dataset.more;
}
el("chapter-index").addEventListener("scroll", paintChapterFade, { passive: true });
window.addEventListener("resize", () => { if (!el("chapter-nav").hidden) paintChapterFade(); });

/** 快速看盤只顯示四章：說明另外兩章在哪裡，這次算了卻不在畫面上的區塊照列名稱。 */
function renderModeNote(hiddenTitles) {
  const note = el("chapter-mode-note");
  note.replaceChildren();
  note.hidden = pageState.resultMode.chapters.length === Chapters.CHAPTER_IDS.length;
  if (note.hidden) return;
  const button = make("button", "ghost small chapter-mode-switch");
  button.type = "button";
  button.textContent = "改用古典完整";
  note.append(`${pageState.resultMode.label}只顯示 ${pageState.resultMode.chapters.length} 章。要看古典判斷與時間主星，請`, button, "。");
  if (hiddenTitles.length) {
    note.append(`這次算出的${hiddenTitles.map((title) => `〈${title}〉`).join("")}不在畫面上，但列印與匯出都有。`);
  }
}

// 章節欄底下「改用古典完整」與結果最後「另有時間主星」：只是換模式（表單的選項換成那一組，
// 畫面上的結果因此標成過期），再把焦點交給表單上的模式選擇，由使用者按「開始排盤」；不另外計算。
// 「自訂」只把焦點移到那一格、不替你選：選了自訂，匯出預設帶驗算資料，會為畫面上的結果再取一次。
function switchModeFromNote(event) {
  const button = event.target.closest ? event.target.closest("button.chapter-mode-switch") : null;
  if (!button) return;
  const mode = button.dataset.mode || "classical";
  const radio = document.querySelector(`input[name="calc-mode"][value="${mode}"]`);
  if (button.dataset.focusOnly === undefined) {
    radio.checked = true;
    applyMode(mode);
  }
  radio.scrollIntoView({ block: "center", behavior: scrollBehavior() });
  radio.focus({ preventScroll: true });
}
el("chapter-mode-note").addEventListener("click", switchModeFromNote);

// 手機上的「直接開始填 ↓」：跳到模式選擇、焦點給選中的那一格。不走瀏覽器的錨點跳轉，網址不留 #片段、
// 不多一筆歷史紀錄；沒有 JavaScript 時它照常是頁內連結。
document.querySelector(".skip-to-form a").addEventListener("click", (event) => {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  el("mode-choice").scrollIntoView({ block: "start", behavior: scrollBehavior() });
  focusCheckedMode();
});
el("chapter-timelords-entry").addEventListener("click", switchModeFromNote);

// 回到頂端：結果標題已捲出視窗一個半螢幕以上才出現，按了把結果標題（章節列就在它下面）捲回視窗頂端、
// 焦點交給它。寬螢幕（內容欄右邊有留白）一直顯示；窄螢幕只在往回捲時顯示，往下讀時收起，不蓋住表格。
// 焦點在按鈕上時不收（鍵盤使用者不會失去焦點）。
const backToTop = el("back-to-top");
const BACK_TO_TOP_DEPTH = 1.5;
const BACK_TO_TOP_WIDE = "(min-width: 1280px)";
/** 純函式：給 headingTop（結果標題離視窗頂端，負值是已捲過）、視窗高、寬螢幕與否、最近一次是否往回捲。 */
function backToTopShown({ headingTop, viewport, wide, scrollingUp }) {
  if (!(headingTop < -BACK_TO_TOP_DEPTH * viewport)) return false;
  return wide || scrollingUp;
}
const backToTopState = { lastY: 0, up: false, frame: 0 };
function paintBackToTop() {
  backToTopState.frame = 0;
  const y = window.scrollY || 0;
  if (y !== backToTopState.lastY) backToTopState.up = y < backToTopState.lastY;
  backToTopState.lastY = y;
  const wide = typeof window.matchMedia === "function" && window.matchMedia(BACK_TO_TOP_WIDE).matches;
  const shown = !results.hidden && backToTopShown({
    headingTop: el("results-heading").getBoundingClientRect().top,
    viewport: window.innerHeight || 0, wide, scrollingUp: backToTopState.up,
  });
  backToTop.hidden = !shown && document.activeElement !== backToTop;
}
window.addEventListener("scroll", () => {
  if (!backToTopState.frame) backToTopState.frame = window.requestAnimationFrame(paintBackToTop);
}, { passive: true });
backToTop.addEventListener("click", () => {
  const heading = el("results-heading");
  heading.scrollIntoView({ block: "start", behavior: scrollBehavior() });
  heading.focus({ preventScroll: true });
  backToTop.hidden = true;
});

function toggleAllChapters() {
  chapterNav.all = !chapterNav.all;
  paintChapters();
  applyOverflowRegions();
}
el("chapters-all").addEventListener("click", toggleAllChapters);

// 匯出。
function selectedExportMode() {
  const selected = document.querySelector(
    'input[name="export-detail-mode"]:checked'
  );
  return selected ? selected.value : "chart_data_only";
}
