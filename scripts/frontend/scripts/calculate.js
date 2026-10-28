// 計算頁的開機步驟；出貨的 calculate.js 由 calculate-*.js 與本檔合併而成（javascript.py）。

// 年度時間主星的接點：年度一區（timelords.js）只讀畫面上這份結果的請求，不另收出生資料；結果換掉或清除時跟著丟棄，表單
// 改動時跟著停用。它的 script 第一份結果畫出時才載入：載入前沒有面板，停用與丟棄都無事可做；載入失敗時這一區照樣出現，
// 只寫連不上本站、排出鈕停用，下一份結果再試。
function annualPanel() { return window.ArmillaryTimelords ? window.ArmillaryTimelords.forPage(document) : null; }
function whenAnnualPanel(use) {
  if (window.ArmillaryTimelords) { const panel = annualPanel(); if (panel) use(panel); return; }
  const payload = pageState.annualPayload;
  loadTimelords().then(() => {
    const panel = pageState.annualPayload === payload ? annualPanel() : null;
    if (panel) use(panel);
  }, () => { if (pageState.annualPayload === payload) showAnnualLoadFailure(); });
}
function showAnnualLoadFailure() {
  const host = document.getElementById("annual");
  if (!host) return;
  host.hidden = false;
  el("annual-load").disabled = true;
  const status = el("annual-status");
  status.textContent = window.ClientContext.networkErrorMessage();
  status.dataset.tone = "error";
}
function showAnnualPanel(payload) {
  pageState.annualPayload = payload;
  whenAnnualPanel((panel) => {
    panel.prefer(linkedTechnique);
    panel.show(payload);
    // 等載入的時候表單可能已改動。
    if (results.dataset.stale === "true") panel.setStale(true);
  });
}
function loadAnnualPanel() { whenAnnualPanel((panel) => panel.load()); }
function staleAnnualPanel(stale) { const panel = annualPanel(); if (panel) panel.setStale(stale); }
function dropAnnualPanel() {
  pageState.annualPayload = null;
  const panel = annualPanel();
  if (panel) { panel.drop(); return; }
  const host = document.getElementById("annual");
  if (host) { host.hidden = true; el("annual-status").textContent = ""; }
}

function dropResultsForNewAttempt() {
  // 先放掉綁定、停用全部匯出控制項，再把結果移出 DOM：移走的按鈕若仍被舊的參照按到，
  // 它已是 disabled，處理函式也因 lifecycle 已清空而拒絕。
  pageState.boundInputSignature = null;
  pageState.currentViewTree = null;
  setStale(false);
  lifecycle.clear();
  clearPrintInputSummary();
  clearPrintBrief();
  forgetDetailBinding();
  sectionSnapshots.clear();
  clearChapterHosts();
  chartWheelHost.replaceChildren();
  Object.assign(pointLink, { selected: null, preview: null });
  clearChapterNav();
  warningsHost.replaceChildren();
  renderBirthTimeSummary(null);
  renderSummary(null, []);
  renderTimeBrief(null);
  dropAnnualPanel();
  results.hidden = true;
  resultPending.hidden = true;
  hideError();
}

function dropResults() {
  dropResultsForNewAttempt();
  // 按「清除」之後下一份結果從總覽開始；重新計算（不經清除）則留在原來那一章。
  Object.assign(chapterNav, { current: "overview", all: false });
  submitButton.disabled = false;
}

function clearPlaceReceipt() {
  // 收據隱藏不等於清除：dl 裡的地名與座標仍在 DOM。
  el("place-receipt").hidden = true;
  el("place-receipt-body").replaceChildren();
  el("place-receipt-codes").replaceChildren();
  el("place-caveat").textContent = "";
  // 鐘點的選擇屬於那個目錄地點；地點撤下，選擇一起撤下。
  pageState.manualCivilTime = false;
  renderCivilTimeChoice(null);
  pageState.placeZone = null;
  renderPlaceZoneChoice(null);
}

/**
 * 把表單、選項、地點狀態、錯誤、結果、進行中的請求全部回到初始狀態。「清除敏感資料」、範例載入、pagehide、
 * pageshow(persisted) 都走這一個函式；分開寫就會各漏一塊。
 */
function resetFormState() {
  dropResults();
  // 進行中的送出與地點查詢一起作廢；遲到的回應被世代號與 lifecycle token 擋下。
  invalidateAttempt();
  cancelButton.hidden = true;
  submitButton.disabled = false;
  // 狀態列是上一次計算的痕跡；bfcache 端回頁面時不能留著「計算完成。」或「計算中…」。
  setStatus("", "info");
  placeSearchLifecycle.abortActiveRequest();
  form.reset();
  clearAllFieldInvalid();
  pageState.optionValues = Chapters.modeOptions(pageState.currentModeId, Catalogue.defaults());
  el("plan-timelords").checked = Chapters.mode(pageState.currentModeId).timelordsAfterChart;
  pageState.selectedPlace = null;
  clearPlaceReceipt();
  placeResults.replaceChildren();
  placeResults.hidden = true;
  placeQuery.value = "";
  secondInput.value = "";
  setPlaceStatus(PLACE_SEARCH.NOT_SEARCHED, "", "info");
  applyPrecisionConsequences();
  applyZodiacConsequences();
  refreshOptionUi();
  // 模糊時刻的選擇區是從已清空的輸入推導出來的，必須跟著重算——否則表單空了，畫面卻還留著「這個時間出現了兩次」，等於洩
  // 漏上一筆輸入的性質。服務回報過的那個時刻同樣是上一筆輸入的痕跡，一起清掉。
  pageState.serviceRepeatedTime = null;
  refreshFoldChoice();
  refreshTimezoneOffset();
  setEraEcho("", "info");
  clearTimeCheck();
}

function clearSensitiveState() {
  resetFormState();
  pageState.chartStyle = "wheel";
  pageState.lastRenderedMode = null;
  applyMode("quick");
  clearAddressInput();
}

// 送出中唯一可達的中止入口。只停止等待這一次，不動已算出的結果——那是「清除」的語意，不是「中止」的。
cancelButton.addEventListener("click", () => {
  const aborted = lifecycle.abortActiveRequest();
  const active = pageState.attemptState !== ATTEMPT.IDLE;
  invalidateAttempt();
  cancelButton.hidden = true;
  resultPending.hidden = true;
  submitButton.disabled = false;
  setStatus(aborted || active ? CANCELLED_MESSAGE : "目前沒有進行中的計算。", "info");
  submitButton.focus();
});

// 兩顆清除鈕都在 #results 裡，清除會把 #results 隱藏；焦點留在原地會掉到 body，下一個 Tab 從頁尾開始、跳過整張表單。移
// 到送出鈕：狀態列就在它旁邊，與中止鈕的落點一致。
el("clear-results").addEventListener("click", () => {
  dropResults();
  setStatus("已清除計算結果。表單保留，可以直接改一個欄位再算一次。", "info");
  submitButton.focus();
});

el("clear-sensitive").addEventListener("click", () => {
  clearSensitiveState();
  setStatus("已清除本頁的輸入與結果。已複製到剪貼簿或已下載的檔案無法由本頁收回。", "info");
  submitButton.focus();
});

// 離開頁面時走與「清除敏感資料」相同的清除；這不是記憶體安全抹除，也不控制瀏覽器當機還原。bfcache 可能把整個 DOM 原樣端
// 回來，所以 pageshow 帶 persisted 時再清一次。
window.addEventListener("pagehide", () => { try { clearSensitiveState(); } catch (_) {} });
window.addEventListener("pageshow", (event) => { if (!event.persisted) return; try { clearSensitiveState(); } catch (_) {} });

buildPlanProfiles();
buildOptionUi();
window.ArmillaryGlossary.mount(document, { host: document.querySelector(".calc-body") });
// 站內連結帶了模式就用它，否則快速看盤（就是產品預設）。只帶技法的連結：時間主星在古典完整（算完星盤接著排）。
applyMode(linkedMode || (linkedTechnique ? "classical" : "quick"));
applyPrecisionConsequences();
applyZodiacConsequences();
// 還沒有結果：匯出控制項從一開始就停用，與清除之後同一個狀態。
applyExportAvailability();
// HTML 先以不依賴 JavaScript 的方式顯示「介面正在載入」。只有全部必要 dependencies、選項 UI、表單守衛與事件接線都完成，
// 才在最後把它隱藏。任一前置 script 失敗或本檔初始化中途丟錯時，訊息會自然留下，而不是端出一個看似正常、選項為空且永遠
// 不能送出的表單。
bootstrapStatus.hidden = true;
// 表單沒有 action 也沒有 method，原生送出會把出生資料放進query string。HTML先disabled，且必須等submit守衛、選項UI及兩個
// 結果約束全部成功後才解除；任何半初始化狀態都同時保留警告與disabled submit。
submitButton.disabled = false;
submitButton.removeAttribute("title");
