
function beginAttempt() {
  pageState.attemptGeneration += 1;
  pageState.attemptState = ATTEMPT.IN_FLIGHT;
  return pageState.attemptGeneration;
}
function isCurrentAttempt(generation) { return generation === pageState.attemptGeneration && pageState.attemptState !== ATTEMPT.IDLE; }
function endAttempt(generation) {
  if (generation !== pageState.attemptGeneration) return false;
  pageState.attemptState = ATTEMPT.IDLE;
  return true;
}
function invalidateAttempt() { pageState.attemptGeneration += 1; pageState.attemptState = ATTEMPT.IDLE; }

form.addEventListener("submit", (event) => {
  event.preventDefault();
  if (pageState.attemptState !== ATTEMPT.IDLE) return;
  // 「加算」送出的這一次，結果到了把焦點交給新加的那一區；其他任何一次送出都不帶。
  const addedFocus = pageState.addRequested;
  pageState.addRequested = null;
  hideError();
  clearAllFieldInvalid();
  const built = buildPayload();
  if (!built.ok) {
    // 缺漏與不合法分開陳述。把兩者混成一句「必填欄位沒有填」，會讓
    // 「12.5 不是整數」讀起來像是那一格空著，使用者就會去填一個已經填了的欄位。
    const parts = [];
    if (built.missing.length) parts.push(`還有必填欄位沒有填：${built.missing.join("、")}。`);
    if (built.invalid.length) parts.push(`這些值送不出去：${built.invalid.join("；")}。`);
    const actions = [];
    if (built.fields.some((input) => input.name === "fold")) actions.push(FOLD_ACTION);
    if (built.missing.length) actions.push("補齊上列欄位後再送出。");
    if (built.invalid.length) actions.push("修正上列數值後再送出。");
    if (currentPrecision() === "exact") { actions.push("若只知道大約時辰或只知道日期，改選對應的把握程度。"); }
    // 上一次的結果必須先消失，這條「連送都沒送出去」的分支也一樣：留著舊卷宗等於在錯誤訊息底下展示一份描述舊輸入的結
    // 果，而且它的複製／下載鈕仍然可用，可以匯出一份與表單不符的卷宗。先清再報，順序不可調換：
    // dropResultsForNewAttempt() 會 hideError()。
    dropResultsForNewAttempt();
    showError(parts.join(" "), actions);
    pageState.formErrorShown = true;
    markInvalidFields(built.fields, built.messages);
    setStatus("尚未送出。", "error");
    return;
  }
  const generation = beginAttempt();
  pageState.resultFocusOptions = addedFocus;
  // 結果綁定送出當下的輸入快照：回來的結果只對這一份 payload 成立，表單之後任何改動都會讓它被標為 stale。
  const signature = inputSignature(built.payload);
  submitButton.disabled = true;
  // 狀態與中止入口在守衛通過當下就出現：否則送出鈕已 disabled，畫面上卻沒有訊息、也沒有中止。
  setStatus("計算中…", "info");
  cancelButton.hidden = false;
  // 送出鈕剛被 disabled，焦點會掉到 body；移到中止鈕。
  cancelButton.focus();
  submitPayload(built.payload, generation, signature);
});

// 每次送出都有上限，中止入口在送出當下即可達；逾時只清這一次的請求狀態，不清出生資料。
// 30 秒遠超最重組合（全恆星＋成相推算）的本機耗時（數百毫秒）。
const REQUEST_TIMEOUT_MS = 30000;

// 往返本身在 privacy-lifecycle.js（時間主星一區共用）；網址照字寫在每一個呼叫點，
// 自我檢查頁依那些字面列出本頁會送的請求。
function postJson(url, payload, signal) { return window.PrivacyLifecycle.postJson(window, url, payload, signal); }

// 連不上本站（請求沒送到，或呈現結果的模組沒抓到）：同一句說明、同一行狀態。
function showServiceUnreachable() {
  showError(window.ClientContext.networkErrorMessage(), ["確認網路連線後再試一次。", "重新載入頁面。"]);
  setStatus("沒有送達本站的計算功能。", "error");
}

function submitPayload(payload, generation, signature) {
  dropResultsForNewAttempt();
  // 上限屬於整次嘗試，不只屬於計算請求：請求已回來而呈現結果的模組還在載入時，到期一樣
  // 結束這一次。到期時除了中止請求，也讓 deadline 以 AbortError 落定，下面的 race 因此結束；
  // 之後才完成的請求或模組被 race 丟棄，碰不到畫面，也碰不到下一次嘗試。
  let expire = null;
  const deadline = new Promise((_resolve, reject) => { expire = reject; });
  const scheduleDeadline = (abortRequest, delay) => window.setTimeout(() => {
    abortRequest();
    expire(new window.DOMException("等待計算結果逾時。", "AbortError"));
  }, delay);
  const { controller, token, timeout } = lifecycle.beginTimedRequest(REQUEST_TIMEOUT_MS, scheduleDeadline);
  const finishAttempt = () => { window.clearTimeout(timeout.handle); cancelButton.hidden = true; };
  submitButton.disabled = true;
  cancelButton.hidden = false;
  // 在送出這次互動之內占住結果的位置（calculate.css .result-pending）。
  resultPending.hidden = false;
  setStatus("計算中…", "info");
  Promise.race([
    Promise.all([postJson("/api/chart", payload, controller.signal), loadResultScripts().then(() => true, () => false)]),
    deadline]).then(([{ response, body, invalidJsonMedia }, viewModelReady]) => {
      if (!lifecycle.isCurrentRequest(token)) return;   // late response 丟棄
      if (invalidJsonMedia) {
        showError("這次的計算結果無法讀取：網站回傳的格式不對。", ["稍後再試一次。", "若持續發生，請透過聯絡頁回報。"]);
        setStatus("計算結果無法讀取。", "error");
        return;
      }
      if (!response.ok) { handleApiError(response, body, payload); return; }
      // 結構檢查要響亮：一個 2xx 但不是物件的 body 不得走進渲染器變成一頁破折號。更深的必要結構檢查由 view-model／
      // exporters 的 createDocument 負責，失敗同樣落到下面的完整性錯誤。
      if (!body || typeof body !== "object" || Array.isArray(body)) { showIncompleteResponse(); return; }
      // 呈現結果的模組沒抓到，與計算請求沒送到是同一種失敗：連不上本站。
      if (!viewModelReady) { showServiceUnreachable(); return; }
      return renderResponse(body, signature, payload);
    }).catch((error) => {
      if (!lifecycle.isCurrentRequest(token)) return;
      if (error && error.name === "AbortError") {
        // 逾時與主動中止都是 AbortError，但說不同的話：逾時不能看起來像使用者自己按到的。
        if (timeout.didTimeout()) {
          showError(
            `等待計算結果超過 ${REQUEST_TIMEOUT_MS / 1000} 秒，已停止等待並捨棄這次結果。`,
            ["表單內容仍在，可以直接再送出一次。", "若持續逾時，改用較少的選項組合，或稍後再試一次。"]
          );
          setStatus("計算逾時，已停止等待。", "error");
        } else { setStatus(CANCELLED_MESSAGE, "info"); }
        return;
      }
      showServiceUnreachable();
    }).finally(() => {
      // 只有仍是當前世代的嘗試可以碰送出鈕與中止鈕；被中止或被取代的
      // 嘗試連 finishAttempt 都不做，否則會把下一次嘗試的中止鈕收掉。
      if (!isCurrentAttempt(generation)) { window.clearTimeout(timeout.handle); return; }
      resultPending.hidden = true;
      finishAttempt();
      endAttempt(generation);
      if (lifecycle.isCurrentRequest(token)) lifecycle.finishRequest(token);
      submitButton.disabled = false;
    });
}

// 中止鈕能做的只有「停止等待並捨棄這次結果」：瀏覽器端不再等、不再顯示。伺服器若已開始計算，這裡不能打斷它（security 頁
// 已說明），它只會算完後不留副本。文案不得說「已中止計算」。
const CANCELLED_MESSAGE = "已停止等待，這次的結果不會顯示也不會保存。伺服器若已開始計算，會算完但不留副本。表單內容保留。";

/**
 * 只讀 `detail`，且只交給 ClientContext 的封閉對照表。伺服器的拒絕只帶閉集代碼、固定訊息與宣告過的欄位位置
 * （schemas.validation_issues 丟掉 Pydantic 的 input／msg／ctx；tests/backend/test_api_properties.py 逐類觀測），不回帶
 * 出生日期、時刻或座標。這裡仍不把回應裡的任何文字直接放進畫面（契約 §9）。
 */
function handleApiError(response, body, payload) {
  const statusCode = response.status;
  const { detail, code } = refusalOf(body);
  const message = window.ClientContext.formatApiError(detail, statusCode);
  // 星曆拒絕重送不會改變結果，動作清單依代碼不建議重試。
  const actions = window.ClientContext.apiErrorActions(statusCode, response.headers.get("Retry-After"), code);
  // 出路由頁面自己的狀態導出，不由一句寫死的文案宣稱。服務說這個時刻或大約時辰需要指明是哪一次，而本頁沒有顯示選擇區時
  // （本頁的判定與服務不同），照服務的判定把選擇區打開，再指向它——不叫使用者去改一個在這個模式下看不到的分鐘欄位，也不
  // 猜落差的原因。date_only 由服務自己取樣整天，不會收到這個拒絕。
  if (code === "ambiguous_local_time_choice_required") {
    if (el("fold-choice").hidden && payload
        && payload.birth_time_precision !== "date_only" && payload.timezone && payload.timezone.mode === "iana") {
      pageState.serviceRepeatedTime = timeKeyOfPayload(payload);
      refreshFoldChoice();
    }
    if (!el("fold-choice").hidden) actions.unshift(FOLD_ACTION);
  }
  // 服務說這個地點要指明鐘點：選擇區在就指向它；不在表示頁面不知道這個地點有兩種鐘點
  // （頁面版本較舊），重新查詢地點才會帶出選項。
  if (code === "civil_time_basis_required") {
    actions.unshift(el("civil-time-choice").hidden ? "請重新載入頁面，再用「地名查詢」選定地點。" : CIVIL_TIME_ACTION);
  }
  showError(message, actions);
  setStatus(window.ClientContext.refusalStatus(statusCode), "error");
  // 對照表在 ClientContext；選項若由另一個控制項代為呈現（rendered_by），標在看得見的那個上。
  const invalid = window.ClientContext.fieldControlIds(detail)
    .map((id) => {
      const key = id.startsWith("opt-") ? id.slice(4) : null;
      const option = key && Object.hasOwn(Catalogue.BY_KEY, key) ? Catalogue.BY_KEY[key] : null;
      return el(option && option.rendered_by ? `opt-${option.rendered_by}` : id);
    })
    .filter((node, index, list) => node && list.indexOf(node) === index);
  if (invalid.length) {
    clearAllFieldInvalid();
    markInvalidFields(invalid);
  } else if (code === "ambiguous_local_time_choice_required" && !el("fold-choice").hidden) {
    // 服務要的是重複時刻的選擇：帶人到那一組選項，與本頁自己擋下時同一個落點。
    const firstFold = form.querySelector('#fold-choice input[name="fold"]');
    if (firstFold) markInvalidFields([firstFold]);
  } else if (code === "civil_time_basis_required" && !el("civil-time-choice").hidden) {
    const firstChoice = form.querySelector('#civil-time-choice input[name="civil_time_basis"]');
    if (firstChoice) markInvalidFields([firstChoice]);
  }
}

function refusalOf(body) {
  const detail = body && typeof body === "object" ? body.detail : null;
  const code = window.ChartExport.isRecord(detail) ? detail.code : null;
  return { detail, code };
}

// 2xx 但不是物件、或狀態權威缺席／殘缺的回應：同一句話，不渲染任何結果。
const INCOMPLETE_RESPONSE_MESSAGE = "這次的計算結果不完整，無法確認是一份完整的結果，所以不顯示。";
const INCOMPLETE_RESPONSE_ACTIONS = Object.freeze(["再試一次。", "若持續發生，請透過聯絡頁回報。"]);
function isIncompleteResponse(error) { return Boolean(error) && error.code === window.ChartExport.INCOMPLETE_RESPONSE; }
function showIncompleteResponse() {
  showError(INCOMPLETE_RESPONSE_MESSAGE, INCOMPLETE_RESPONSE_ACTIONS);
  setStatus("回應完整性檢查未通過。", "error");
}
