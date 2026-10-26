// 計算頁：複製、下載、列印與一頁摘要。

function writeToClipboard(text, okMessage, anchor) {
  const clipboard = navigator.clipboard;
  if (!clipboard || typeof clipboard.writeText !== "function") {
    reportAt(anchor, "這個瀏覽器不允許頁面寫入剪貼簿；請改用下載。", "error");
    return;
  }
  clipboard.writeText(text).then(
    () => reportAt(anchor, okMessage, "info"),
    // 平台丟出的 error.message 是英文的內部訊息，對中文介面的使用者沒有
    // 可行動內容。這裡的失敗原因對使用者只有一種意義：這條路走不通，改用
    // 下載。原始訊息不丟掉，但留在 console 給回報用，不佔畫面。
    (error) => {
      if (error) console.warn("clipboard.writeText 失敗", error);
      reportAt(anchor, "瀏覽器這次沒有允許寫入剪貼簿；請改用下載。", "error");
    }
  );
}

function copySection(sectionId, anchor) {
  let text;
  try {
    requireExportableDocument();                   // 清除後或表單改動後這裡就會拋
    const snapshot = sectionSnapshots.get(sectionId);
    if (!snapshot) throw new Error("找不到這一段的結果資料，請重新計算後再複製。");
    text = window.ChartExport.renderSectionText(snapshot);
  } catch (error) {
    reportAt(anchor, `複製失敗：${error.message}`, "error");
    return;
  }
  writeToClipboard(text, "已複製本區。", anchor);
}

// 結果訊息報在按下的那顆按鈕旁：首屏的常用匯出與最下方的完整工具列各報各的。
function copyAll(button) {
  let text;
  try {
    const mode = selectedExportMode();
    const canonical = requireExportableDocument(mode);
    text = window.ChartExport.renderPlainText(
      window.ChartExport.projectOutputDocument(canonical, mode)
    );
  } catch (error) {
    reportAt(button, `複製失敗：${error.message}`, "error");
    return;
  }
  writeToClipboard(text, "已複製所選內容。", button);
}

function downloadExport(format, button) {
  let canonical;
  const mode = selectedExportMode();
  try {
    canonical = requireExportableDocument(mode);
  } catch (error) {
    reportAt(button, `下載失敗：${error.message}`, "error");
    return;
  }
  const outcome = window.ChartExport.runDownloadAction(
    canonical,
    format,
    deliverArtifact,
    mode,
  );
  reportAt(
    button,
    outcome.ok
      ? `已產生 ${format.toUpperCase()} 檔案。`
      : `下載失敗：${outcome.error_message}`,
    outcome.ok ? "info" : "error"
  );
}

document.querySelectorAll("[data-copy], [data-quick-copy]").forEach((button) => {
  button.addEventListener("click", () => copyAll(button));
});

document.querySelectorAll("[data-download], [data-quick-download]").forEach((button) => {
  button.addEventListener("click", () => downloadExport(
    button.dataset.download || button.dataset.quickDownload, button
  ));
});

function deliverArtifact(artifact) {
  lifecycle.deliverDownload(document, new Blob([artifact.content], { type: artifact.mime_type }), artifact.filename);
}

// 列印鈕：完整結果或一頁摘要。按下時寫下這次要印哪一種，beforeprint 取用；瀏覽器選單與
// Ctrl/⌘+P 不經過按鈕，沒有寫下的就是完整列印。
const PRINT_MODE = Object.freeze({ FULL: "full", BRIEF: "brief" });
function printFromButton(event) {
  try { requireExportableDocument(); }
  catch (error) { setStatus(`無法列印：${error.message}`, "error"); return; }
  pageState.pendingPrintMode = event.currentTarget.dataset.printMode === PRINT_MODE.BRIEF ? PRINT_MODE.BRIEF : PRINT_MODE.FULL;
  results.dataset.printMode = pageState.pendingPrintMode;
  window.print();
}
document.querySelectorAll("button[data-print-mode]").forEach((button) => {
  button.addEventListener("click", printFromButton);
});

// 列印（含瀏覽器選單的列印與 Ctrl/⌘+P）前展開結果區所有
// 摺疊區塊——技術細節、長區、收據與軌跡——否則存成的 PDF 只有摘要；
// 列印後還原使用者原本的展開狀態。
//
// 瀏覽器選單與 Ctrl/⌘+P 不經過列印鈕，beforeprint 也無法取消列印，所以這裡
// 套用與列印鈕、複製、下載同一個守衛（requireExportableDocument）：結果已不
// 對應目前輸入時，標記 data-print-withheld，列印樣式只留下 stale 說明，不把
// 改動前的結果當成目前的結果印出。
//
// 一頁摘要只印首屏的圖與速覽、位置表與收據身分（calculate.css 依 #results 的 data-print-mode）；
// 出生日期、時間、地點與時間收據一行只在勾選「摘要加印…」時印（data-print-input），也不展開摺疊。
function endPrint() {
  if (pageState.restorePrintExpansion) pageState.restorePrintExpansion();
  pageState.restorePrintExpansion = null;
  delete results.dataset.printWithheld;
  delete results.dataset.printMode;
  delete results.dataset.printInput;
  clearPrintInputSummary();
  printBriefTables.querySelectorAll(".print-brief-timelords").forEach((node) => node.remove());
}
window.addEventListener("beforeprint", () => {
  // 按鈕寫下的模式維持到 afterprint：有的瀏覽器（Chromium 存成 PDF）在一次列印裡會再送一次
  // beforeprint，不能因此退回完整列印。
  const mode = pageState.pendingPrintMode
    || (results.dataset.printMode === PRINT_MODE.BRIEF ? PRINT_MODE.BRIEF : PRINT_MODE.FULL);
  pageState.pendingPrintMode = null;
  endPrint();
  try {
    requireExportableDocument();
  } catch (_error) {
    results.dataset.printWithheld = "true";
    return;
  }
  results.dataset.printMode = mode;
  if (mode === PRINT_MODE.BRIEF) renderBriefTimelords();
  if (mode === PRINT_MODE.BRIEF && !printBriefInput.checked) return;
  fillPrintInputSummary();
  results.dataset.printInput = "true";
  if (mode === PRINT_MODE.BRIEF) return;
  // 時間主星年表的十年不展開：打開一段十年會向伺服器取它的第二層，列印不可以送請求。
  // 「第一次看星盤？」的導覽不印（calculate.css），也不展開。
  pageState.restorePrintExpansion = window.ChartExport.printExpansion(
    results.querySelectorAll("details:not(.tl-decade):not(.first-time)")
  );
});
window.addEventListener("afterprint", () => {
  pageState.pendingPrintMode = null;
  endPrint();
});

// 列印的輸入摘要：
// 列印藏起表單，紙上只剩結果，看不出是哪一組輸入算的。列印前把表單上「畫面看得到」的值抄成
// 一張摘要：被精度收起的時分秒、收起的手動座標不印，只印使用者已經在畫面上看到的東西。結果
// 與輸入一致才會走到這裡（上面的匯出守衛），所以表單值就是算出這份結果的輸入。列印後清空，
// 不在頁面上多留一份輸入。
// 紙上沒有工具列，下載鈕旁的匯出隱私提示印不出來；摘要列出了精確座標，所以摘要在頁面上
// 帶著自己那一句寫給紙本的隱私提示（#print-privacy-note）。
const printSummaryList = el("print-input-summary").querySelector("dl");

function clearPrintInputSummary() {
  printSummaryList.replaceChildren();
}

/** 畫面上看得到：沒有 hidden 的祖先；在收起的 <details> 裡則只有它自己的 summary 看得到。 */
function shownOnScreen(node) {
  let child = null;
  for (let cursor = node; cursor; cursor = cursor.parentElement) {
    if (cursor.hidden) return false;
    if (cursor.tagName === "DETAILS" && !cursor.open && !(child && child.tagName === "SUMMARY")) return false;
    child = cursor;
  }
  return true;
}

/** 欄位的標籤字，不含並列的英文。 */
function fieldLabel(id) {
  const label = form.querySelector(`label[for="${id}"]`).cloneNode(true);
  label.querySelectorAll(".en").forEach((node) => node.remove());
  return label.textContent.trim();
}

function printInputEntries() {
  const entries = [];
  const add = (term, value) => { if (value) entries.push([term, value]); };
  const shownField = (id) => {
    const input = el(id);
    return shownOnScreen(input) && input.value.trim() ? input.value.trim() : "";
  };
  const precision = form.querySelector('input[name="precision"]:checked');
  if (precision) add("出生時刻把握程度", precision.closest("label").querySelector("b").textContent.trim());
  // 出生日期印成 YYYY-MM-DD；還不成日期時照填的字印出。
  const dateRead = readDateField();
  const typedDate = datePartInputs().map((input) => input.value.trim()).join("");
  add(el("date-legend").textContent.trim(), dateRead.state === RI.STATES.VALUE ? dateRead.value.iso : typedDate);
  ["hour", "minute", "second"].forEach((id) => add(fieldLabel(id), shownField(id)));
  // 選了目錄地點時，收據是畫面上的地點、座標與時區；手動欄位展開時以欄位為準。
  const receipt = new Map();
  if (shownOnScreen(el("place-receipt"))) {
    el("place-receipt-body").querySelectorAll("dt").forEach((term) => {
      // 收據的欄名後面接並列的英文代碼（span.en），比對時只取中文欄名。
      const own = term.cloneNode(true);
      own.querySelectorAll(".en").forEach((node) => node.remove());
      receipt.set(own.textContent.trim(), term.nextElementSibling.textContent);
    });
  }
  add("地點", receipt.get("地點"));
  [["latitude", "緯度"], ["longitude", "經度"], ["timezone", "時區"]].forEach(([id, receiptTerm]) => {
    add(fieldLabel(id), shownField(id) || receipt.get(receiptTerm));
  });
  add(fieldLabel("altitude"), shownField("altitude"));
  add("計算口徑", el("mode-summary").textContent.trim());
  return entries;
}

function fillPrintInputSummary() {
  printSummaryList.replaceChildren(...printInputEntries().flatMap(([term, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    return [dt, dd];
  }));
}

// 一頁摘要：
// 算完時填入收據身分（與純文字匯出開頭同一組字：三個契約版本、計算模式、出生時刻把握程度）與
// 位置表（ChartViewModel.printBriefRows：每一格是畫面上同名表格的原字）。兩者都是畫面上已有的
// 衍生值，不含輸入；輸入摘要只在列印當下、勾選時由 beforeprint 填入。清除、重新計算與 pagehide
// 時清空，勾選框回到不勾。紙上位置表排在圖的右邊（calculate.css），一張表就放得下。
const printBriefReceipt = el("print-brief-receipt");
const printBriefTables = el("print-brief-tables");

function clearPrintBrief() {
  printBriefReceipt.querySelectorAll("dd").forEach((node) => node.remove());
  printBriefTables.replaceChildren();
  printBriefInput.checked = false;
}

function printBriefTable(caption, columns, rows) {
  const table = make("table", "print-brief-table");
  table.appendChild(make("caption", "", caption));
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = make("th", "", column);
    th.scope = "col";
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((cell, index) => {
      const node = document.createElement(index === 0 ? "th" : "td");
      if (index === 0) node.scope = "row";
      fillCell(node, String(cell == null ? "" : cell), index === 0);
      tr.appendChild(node);
    });
    tbody.appendChild(tr);
  });
  table.append(thead, tbody);
  return table;
}

// 一頁摘要的時間主星一行：只有已排出時間主星時才印，只寫輪值，不寫任何日期。
function renderBriefTimelords() {
  printBriefTables.querySelectorAll(".print-brief-timelords").forEach((node) => node.remove());
  const panel = annualPanel();
  const line = panel ? panel.briefLine() : null;
  if (line) printBriefTables.appendChild(make("p", "print-brief-timelords", line));
}

function renderPrintBrief(tree, canonical) {
  clearPrintBrief();
  const Export = window.ChartExport;
  const mode = Export.computationModeLine(canonical.source_response);
  const precision = Export.inputAssumptionEntries(canonical)
    .find((entry) => entry.key === "birth_time_precision");
  [
    `版號（驗算時對照用）：${Export.contractVersionLines(canonical).join(" · ")}`,
    mode ? `${mode.label}: ${mode.value}` : null,
    precision ? Export.inputAssumptionText(precision) : null,
  ].filter(Boolean).forEach((line) => printBriefReceipt.appendChild(make("dd", "", line)));
  const brief = window.ChartViewModel.printBriefRows(tree);
  if (!brief) {
    printBriefTables.appendChild(make("p", "note", "這次的位置表無法摘要，見完整列印。"));
    return;
  }
  printBriefTables.appendChild(printBriefTable("天體與軸點", brief.columns, brief.rows));
}
