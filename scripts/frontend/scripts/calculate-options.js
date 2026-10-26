// 計算頁：網址清理、共用的小工具、頁面狀態、選項與模式的介面。
"use strict";
// 這一層只做接線：收表單、打同源 API、把 view tree 變成元素、接匯出與清除。
// 「回應長什麼樣」在 view-model.js，「有哪些選項」在 options-catalogue.js，
// 序列化在 exporters.js。這裡不得自行讀 source_response 組畫面（契約 §10）。

// 本頁不讀網址的 query 或 fragment；帶著它們來的，是訪客或連結放進去的東西，
// 可能就是出生資料。第一件事就從網址列與這一筆歷史紀錄拿掉（取代，不新增），
// 排在任何可能丟錯的初始化之前，載入失敗時也不留在網址上。瀏覽器在載入前
// 已記下的全域歷史，本頁收不回。唯一的例外是站內連結帶的模式（mode）與時間主星技法
// （technique）：拿掉之前各讀一次，只認固定的幾個值，其餘的鍵一概不讀。
const linkedMode = window.ResultChapters ? window.ResultChapters.modeFromQuery(window.location.search) : null;
const linkedTechnique = window.ResultChapters ? window.ResultChapters.techniqueFromQuery(window.location.search) : null;
// 頁面開著時才貼上或改動的 #片段（同一份文件內的導覽，不重新載入，瀏覽器為它新增一筆紀錄）
// 也一樣清掉。
function clearAddressInput() {
  if (window.location.search || window.location.hash) {
    window.history.replaceState(null, "", window.location.pathname);
  }
}
clearAddressInput();
window.addEventListener("hashchange", clearAddressInput);

const Catalogue = window.OptionsCatalogue;
const Labels = window.ArmillaryLabels;
const LocationReceipt = window.LocationReceipt;
const lifecycle = window.PrivacyLifecycle.createSensitiveDataLifecycle();
const placeSearchLifecycle = window.PrivacyLifecycle.createSensitiveDataLifecycle();

const el = (id) => document.getElementById(id);
// class 一律照字寫：樣式包的檢查讀得到。
const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className !== undefined) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};
const makeFold = (className, summaryText) => {
  const details = make("details", className);
  details.appendChild(make("summary", undefined, summaryText));
  return details;
};
// 手機版面（calculate.css 的 640px 斷點）：只決定預設開合與捲動，不決定內容。
const NARROW_QUERY = "(max-width:640px)";
const narrowScreen = () => typeof window.matchMedia === "function" && window.matchMedia(NARROW_QUERY).matches;
const form = el("chart-form");
const statusLine = el("status-line");
const errorPanel = el("error-panel");
const errorMessage = el("error-message");
const errorActions = el("error-actions");
const results = el("results");
// 結果的六章各有一個放區塊的容器（calculate.html 的 data-chapter-host）；哪一區放哪一章由
// result-chapters.js 的表決定。
const Chapters = window.ResultChapters;
const chapterHosts = new Map(
  [...document.querySelectorAll("[data-chapter-host]")].map((node) => [node.dataset.chapterHost, node])
);
const warningsHost = el("warnings");
const warningsFold = el("warnings-fold");
const samplingCalloutHost = el("sampling-callout");
const birthTimeNoticeHost = el("birth-time-notice");
// 速覽排在警告之後、匯出工具列之前（#result-lead 的第一個子元素）：算完不必捲過工具列就看得到。
// 窄螢幕依序上下排，桌機由 calculate.css 排成左圖右速覽。
const SUMMARY_SECTION_ID = "summary";
const summaryHost = make("div", "chart-summary");
summaryHost.hidden = true;
el("result-lead").prepend(summaryHost);
const chartWheelHost = el("chart-wheel-host");
// 「時間轉換」在畫面上拆成兩處：結果標題下一行重點，完整表格收在結果最後的 <details>。
// 匯出不受影響：匯出讀 canonical document 的區段順序，這裡只決定畫面上的位置。
const TIME_SECTION_ID = "time";
const timeBrief = el("time-brief");
const submitButton = el("submit-button");
const cancelButton = el("cancel-button");
const bootstrapStatus = el("bootstrap-status");
// 只在畫結果時才用得到的 script 不在開機時載入。星盤圖一族（chart-*.js）與 view-model.js（回應 →
// sections → view tree）第一次與表單互動時開始抓，送出時與計算請求一起等，兩者都到了才畫。
// 時間主星一區（timelords-model.js、timelords.js）等第一份結果畫出時才抓。網址（含內容
// 版本）由 build_pages 寫在本 script 的 data-* 上。用 import() 而不是插入 <script>：同源模組
// 符合 script-src 'self'，也不經過 script.src 這個 Trusted Types 的注入點。
const lazySource = document.querySelector("script[data-view-model]");
/** 依序載入 [data-* 鍵, 全域名稱]；已在的（jsdom 測試先載好）不再抓。 */
function lazyScripts(parts) {
  const pending = parts.filter(([, global]) => !window[global])
    .map(([key, global]) => [lazySource ? lazySource.dataset[key] : null, global]);
  if (pending.some(([url]) => !url)) throw new Error("calculate.js 沒有延後載入的 script 位址。");
  const ready = () => parts.every(([, global]) => window[global]);
  let load = null;
  let failures = 0;
  return function loadLazy() {
    if (ready()) return Promise.resolve();
    if (!load) {
      // 瀏覽器把抓取失敗的模組網址記成失敗，同一網址再 import 不會重抓；
      // 重試時換一個查詢參數，下一次才真的再抓一次。已載入的不重抓。
      const retry = failures ? `&retry=${failures}` : "";
      load = pending.reduce(
        (chain, [url, global]) => chain.then(() => (window[global] ? null : import(url + retry))),
        Promise.resolve(),
      ).then(() => {
        if (!ready()) throw new Error("延後載入的 script 沒有提供它的全域物件。");
      }).catch((error) => {
        failures += 1;
        load = null;
        throw error;
      });
    }
    return load;
  };
}
const loadResultScripts = lazyScripts([
  ["chartGlyphs", "ArmillaryChartGlyphs"], ["chartWheelAspects", "ChartWheelAspects"],
  ["chartWheelModel", "ChartWheelModel"], ["chartSquare", "ChartSquare"], ["chartWheel", "ChartWheel"],
  ["viewModel", "ChartViewModel"],
]);
const loadTimelords = lazyScripts([["timelordsModel", "ArmillaryTimelordsModel"], ["timelords", "ArmillaryTimelords"]]);
form.addEventListener("focusin", () => { loadResultScripts().catch(() => {}); }, { once: true });
// 技術區塊的集合只有一個出處：exporters 匯出的驗算區段集合。「運算結果」
// 匯出排除哪些區段，畫面就把哪些收進「技術細節」；不另抄一份 id 清單。
// 不從投影結果反推：投影同時排除「未請求」的區段，反推
// 會把它們錯收進技術細節。缺少這個集合時讓初始化失敗，載入訊息留在畫面上。
const TECHNICAL_SECTION_IDS = window.ChartExport.REPRODUCIBILITY_SECTION_IDS;
if (!TECHNICAL_SECTION_IDS || typeof TECHNICAL_SECTION_IDS.has !== "function") {
  throw new Error("exporters 未提供驗算區段集合。");
}

// 宣告在這裡而不是 buildPayload 附近：更早定義的 refreshFoldChoice 也用它（const 有 TDZ）。
const RI = window.RequestInput;
const TimezoneNames = window.TimezoneNames;

// 每一次送出都拿一個不可重用的世代號。中止與清除讓世代
// 前進；任何還握著舊世代的續行——遲到的回應、finally——都只能放棄，不得碰
// 送出鈕與中止鈕。地點查詢的 lifecycle token 就是同一個模式。狀態是閉集：
// 閒置／飛行中。
const ATTEMPT = Object.freeze({ IDLE: "idle", IN_FLIGHT: "in_flight" });

// 頁面的可變狀態只有這一份：各處讀寫 pageState.<名稱>，依頁面由上而下的順序排列。
const pageState = {
  optionValues: Catalogue.defaults(),
  selectedPlace: null,  // 目錄選定的地點，含收據欄位
  civilTimeBasis: null,  // 新疆的地點：出生紀錄用的鐘點；null = 尚未選
  manualCivilTime: false,  // 手動座標、時區填的是新疆時間：同樣要問鐘點
  boundPayload: null,  // 畫面上那份結果的請求；清除結果時一併放掉
  pageCanonical: null,  // 畫面上那份結果（預設回應）的 canonical document
  resultGeneration: 0,  // 每次畫出或清除結果都前進；遲到的驗算資料比對它
  technicalHost: null,  // 「技術細節與驗算資料」的 <details>
  lastExportActions: { copy_enabled: true, download_enabled: true },
  // 每個選項的控制項、它那一列與子選項區；控制項只由 buildOptionUi 建一次，所以查一次就夠
  // （refreshOptionUi 每次改模式會被叫好幾次）。
  optionNodes: null,
  currentModeId: "quick",
  linkedChapterShown: false,
  lastRenderedMode: null,
  // 重複的民用小時：秋季調慢當天同一鐘面時間出現兩次，後端以 fold 指明是哪一次。偵測到模糊時
  // 把選擇交還給使用者，沒選之前 fail closed；不替使用者選第一次（盤可能整個差一小時）。
  foldChoice: null,  // null = 尚未選；0/1 = 使用者選定的那一次
  // 服務判定為重複、本頁自己沒看出來的那個時刻：exact 與大約時辰都由
  // ambiguous_local_time_choice_required 拒絕給出（伺服器不替使用者猜）。只存比對用的鍵，
  // 「清除敏感資料」與任何重設都會清掉（resetFormState）。
  serviceRepeatedTime: null,
  timeCheckShownKey: null,
  // 錯誤面板是不是本頁自己擋下的表單錯誤（沒送出）：是的話，欄位都改好時面板自己收起，
  // 不必等下一次送出；伺服器的錯誤說的是上一次送出，不在這裡收。
  formErrorShown: false,
  attemptState: ATTEMPT.IDLE,
  attemptGeneration: 0,
  // 位置表在快速看盤先只顯示四欄（天體、星座度數、宮、行進），其餘一鍵展開；匯出照舊全欄。
  // 「宮」一欄照行星落宮表的原字（與一頁摘要的位置表同一個來源：ChartViewModel.printBriefRows）。
  // positionsFull 是這一頁的變數：null＝照模式的預設；換模式時回到 null。
  positionHouses: new Map(),
  positionsFull: null,
  // 使用者在圖的工具列上換圓盤／方盤時記下來，重新計算後沿用；按「清除本頁敏感資料」時回到圓盤。
  chartStyle: "wheel",
  // 結果與表單的綁定：
  // 畫面上的結果只對它送出當下的輸入成立。表單任何一處改動後，結果標為
  // stale、複製與下載停用；改回原值則綁定又成立。飛行中改動也一樣：回來的
  // 結果在渲染那一刻就會被比對。
  boundInputSignature: null,  // null = 畫面上沒有結果
  currentViewTree: null,  // 畫面上那棵 view tree；清除結果時一併放掉
  // 這一份結果是用哪一種模式算的（章節欄、位置表的預設欄數、算完要不要接著排時間主星都看它）。
  resultMode: null,
  spyFrame: 0,
  // 「加算」：按下時記下要打開的選項；送出時移到 resultFocusOptions（只屬於那一次送出），結果到了
  // 由 revealResults 把焦點與捲動交給新加的那一區的標題，不回到頁首。
  addRequested: null,
  resultFocusOptions: null,
  pendingPrintMode: null,
  restorePrintExpansion: null,
  annualPayload: null,  // 交給年度一區（或等它載入）的那份請求；丟棄時放掉
};
const sectionSnapshots = new Map();  // section id -> canonical section

// 驗算資料的取得狀態。宣告在最前面：清除與過期判定在初始化時
// 就會被呼叫，而它們都要讀這份狀態（const 有 TDZ）。
const DETAIL = Object.freeze({
  IDLE: "idle", LOADING: "loading", READY: "ready", FAILED: "failed",
});
const verification = { state: DETAIL.IDLE, canonical: null, message: "", actions: [] };

// 選項介面由目錄產生，不手寫。
// 摺疊只有一層：「進階選項」開或關。展開後所有選項一次攤在畫面上，
// 分組只是視覺分隔線，不是要點開的容器，也沒有搜尋框——
// 使用者是看到 Lilith 才想起要看它，不是先想起名字再去搜尋（辨識優於回憶）。
// 相依子項縮排在父項底下，不另外摺疊。

function buildOptionUi() {
  pageState.optionNodes = null;
  const host = el("option-groups");
  host.replaceChildren();

  Catalogue.GROUPS.filter((group) => group.in_advanced).forEach((group) => {
    const block = make("div", "option-block");
    block.dataset.group = group.key;
    block.setAttribute("role", "group");

    const heading = make("div", "option-heading");
    heading.id = `option-group-${group.key}-heading`;
    block.setAttribute("aria-labelledby", heading.id);
    // 組名只寫中文：英文並列只給第一次出現的術語（各選項的標籤），一般的分組名不另掛英文。
    heading.append(group.label_zh);
    block.appendChild(heading);

    Catalogue.OPTIONS
      .filter((option) => option.group === group.key && !option.depends_on)
      .forEach((option) => block.appendChild(buildOptionRow(option)));

    host.appendChild(block);
  });

  // 宮位兩項已升到主表單，插進口徑區而不是進階選項。
  el("house-system-slot").replaceChildren(buildHouseControl());
  // 下拉選單由這裡產生，靜態 HTML 的 label 不能先寫 for：指向不存在的
  // id 是 HTML 錯誤（W3C Nu checker）。控制項出現後才接上。
  el("house-system-label").htmlFor = "opt-house_system";

  refreshOptionUi();
}

// 宮位以單一下拉表達兩個欄位：選「不計算宮位」等於 include_houses=false。
// 使用者不需要先勾一個開關才能選制度。
const NO_HOUSES = "__none__";

function buildHouseControl() {
  const option = Catalogue.BY_KEY.house_system;
  const select = markNoRestore(document.createElement("select"));
  select.id = "opt-house_system";
  select.className = "option-control";
  // 說明文字在靜態 HTML：#opt-house_system-detail 寫所選的那一種怎麼切天空（由這裡填），
  // #opt-house_system-hint 寫各種之間的差別。控制項由這裡產生。
  select.setAttribute("aria-describedby", "opt-house_system-detail opt-house_system-hint");

  const none = document.createElement("option");
  none.value = NO_HOUSES;
  none.textContent = "不計算宮位　No houses";
  select.appendChild(none);

  // 選單依目錄的 value_groups 分組；每個值只出現在一組裡，組外的值不存在。
  const byValue = new Map(option.values.map((value) => [String(value.value), value]));
  option.value_groups.forEach((group) => {
    const optgroup = document.createElement("optgroup");
    optgroup.label = group.label_zh;
    group.values.forEach((code) => {
      const value = byValue.get(String(code));
      const opt = document.createElement("option");
      opt.value = String(value.value);
      // 以人名命名的宮位制中英同名，只寫一次。
      opt.textContent = value.label_zh === value.label_en ? value.label_zh : `${value.label_zh}　${value.label_en}`;
      optgroup.appendChild(opt);
    });
    select.appendChild(optgroup);
  });

  select.addEventListener("change", () => {
    if (select.value === NO_HOUSES) {
      pageState.optionValues = { ...pageState.optionValues, include_houses: false };
    } else {
      pageState.optionValues = {
        ...pageState.optionValues, include_houses: true, house_system: select.value,
      };
    }
    refreshOptionUi();
  });

  // include_houses 仍需一個具名節點，讓覆蓋率檢查與測試找得到它。
  const mirror = document.createElement("input");
  mirror.type = "hidden";
  mirror.id = "opt-include_houses";
  mirror.className = "option-control";
  const wrap = make("div", "house-control");
  wrap.appendChild(select);
  wrap.appendChild(mirror);
  return wrap;
}

// 所選宮位制的一句白話，取自目錄；不計算宮位時說明略過了什麼。
function houseSystemDetail() {
  if (pageState.optionValues.include_houses === false) {
    return "不計算宮位：這次完全不算宮位；要用到上升點或中天的項目會標成不可用。";
  }
  const chosen = Catalogue.BY_KEY.house_system.values.find(
    (value) => String(value.value) === String(pageState.optionValues.house_system),
  );
  return chosen ? `${chosen.label_zh}：${chosen.help_zh}` : "";
}

function buildOptionRow(option) {
  const row = make("div", "option-row");
  row.dataset.option = option.key;

  const label = make("label", "option-label");
  label.htmlFor = `opt-${option.key}`;
  label.append(option.label_zh);
  const en = make("span", "en");
  en.lang = "en";
  en.textContent = option.label_en;
  label.appendChild(en);

  row.appendChild(label);
  const control = buildControl(option);
  row.appendChild(control);

  const helpText = Catalogue.helpText(option);
  if (helpText) {
    const help = make("p", "option-help");
    help.id = `opt-${option.key}-help`;
    help.textContent = helpText;
    row.appendChild(help);
    // 說明關聯到控制項，聚焦時就念得到（WCAG 1.3.1）。
    const target = control.id === label.htmlFor ? control : control.querySelector(`#${label.htmlFor}`);
    if (target) target.setAttribute("aria-describedby", help.id);
  }

  const children = Catalogue.OPTIONS.filter((child) => child.depends_on === option.key);
  if (children.length) {
    const nest = make("div", "option-children");
    nest.dataset.childrenOf = option.key;
    children.forEach((child) => nest.appendChild(buildOptionRow(child)));
    row.appendChild(nest);
  }
  return row;
}

// 動態產生的控制項都關閉表單還原：否則重新載入時瀏覽器復原控制項並觸發 change，
// 送出的模組組合與畫面初始狀態不符。checkbox 與 radio 沒有 autocomplete 屬性可用（HTML 不給
// 它意義），它們由所屬表單的 autocomplete="off" 關掉還原。
function markNoRestore(control) {
  control.setAttribute("autocomplete", "off");
  return control;
}

function buildControl(option) {
  if (option.type === "boolean" && option.render === "select") {
    const select = markNoRestore(document.createElement("select"));
    select.id = `opt-${option.key}`;
    select.className = "option-control";
    option.value_labels.forEach((entry) => {
      const opt = document.createElement("option");
      opt.value = entry.value ? "true" : "false";
      opt.textContent = `${entry.label_zh}　${entry.label_en}`;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => setOption(option.key, select.value === "true"));
    return select;
  }
  if (option.type === "boolean") {
    const input = document.createElement("input");
    input.type = "checkbox";
    input.id = `opt-${option.key}`;
    input.className = "option-control";
    input.addEventListener("change", () => setOption(option.key, input.checked));
    return input;
  }
  if (option.type === "choice") {
    const select = markNoRestore(document.createElement("select"));
    select.id = `opt-${option.key}`;
    select.className = "option-control";
    option.values.forEach((value) => {
      const opt = document.createElement("option");
      // null 在 DOM 只能是字串，用固定哨兵往返，避免與真實值 "null" 混淆。
      opt.value = value.value === null ? "\u0000null" : String(value.value);
      opt.textContent = `${value.label_zh}　${value.label_en}`;
      select.appendChild(opt);
    });
    select.addEventListener("change", () => {
      setOption(option.key, select.value === "\u0000null" ? null : select.value);
    });
    return select;
  }
  const input = markNoRestore(document.createElement("input"));
  input.type = "number";
  input.id = `opt-${option.key}`;
  input.className = "option-control";
  if (option.min !== undefined) input.min = String(option.min);
  if (option.max !== undefined) input.max = String(option.max);
  if (option.step !== undefined) input.step = String(option.step);
  input.addEventListener("change", () => {
    const raw = input.value.trim();
    setOption(option.key, raw === "" ? null : Number(raw));
  });
  return input;
}

function setOption(key, value) {
  pageState.optionValues = { ...pageState.optionValues, [key]: value };
  refreshOptionUi();
}

function optionNodeList() {
  if (!pageState.optionNodes) {
    pageState.optionNodes = Catalogue.OPTIONS.map((option) => {
      const control = document.getElementById(`opt-${option.key}`);
      return control && {
        option,
        control,
        row: control.closest(".option-row"),
        nest: document.querySelector(`[data-children-of="${option.key}"]`),
      };
    }).filter(Boolean);
  }
  return pageState.optionNodes;
}

function refreshOptionUi() {
  optionNodeList().forEach(({ option, control, row, nest }) => {
    const value = pageState.optionValues[option.key];
    if (option.type === "boolean" && option.render === "select") {
      control.value = value === true ? "true" : "false";
    } else if (option.type === "boolean") control.checked = value === true;
    else if (option.type === "choice") {
      control.value = value === null ? "\u0000null" : String(value);
    } else control.value = value === null || value === undefined ? "" : String(value);

    if (row) row.classList.toggle("is-changed", Catalogue.isEnabled(option, value));
    // 此刻沒有意義的一項（例如三分性已選「全部並列」時的「並列其餘三分性」）收起；它也不會送出。
    if (row) row.hidden = Catalogue.isHidden(option, pageState.optionValues);

    // 互斥：停用並就地說明，不隱藏。隱藏會讓人以為選項不存在。
    const conflict = Catalogue.conflictFor(option, pageState.optionValues);
    control.disabled = !!conflict;
    if (row) {
      row.classList.toggle("is-blocked", !!conflict);
      let note = row.querySelector(".conflict-note");
      if (conflict) {
        if (!note) {
          note = document.createElement("p");
          note.className = "conflict-note";
          row.appendChild(note);
        }
        note.textContent = `已由「${conflict.source.label_zh}」停用：${conflict.reason_zh}`;
      } else if (note) {
        note.remove();
      }
    }

    if (nest) {
      const active = option.type === "boolean"
        ? value === true
        : value !== null && value !== undefined;
      nest.hidden = !active;
    }
  });

  const houseSelect = document.getElementById("opt-house_system");
  if (houseSelect) {
    houseSelect.value = pageState.optionValues.include_houses === false
      ? NO_HOUSES : String(pageState.optionValues.house_system);
    const mirror = document.getElementById("opt-include_houses");
    if (mirror) mirror.value = String(pageState.optionValues.include_houses === true);
    const detail = document.getElementById("opt-house_system-detail");
    if (detail) detail.textContent = houseSystemDetail();
  }

  // 標題說的是「進階選項」，只數進階群組。主表單的宮位選擇就在眼前；計進來會讓
  // 只選了「不計算宮位」的人讀到「已調整 1 項」，卻在進階選項裡找不到那一項。
  // 「已調整」只數使用者自己改的：模式預先勾好的那幾項（例如古典完整的 5 項）不算，
  // 改寫成「古典完整預設 5 項」，不用強調色。模式讀畫面上選中的那一顆（這個函式在
  // currentModeId 宣告之前就會被呼叫）。
  const checkedMode = document.querySelector('input[name="calc-mode"]:checked');
  const mode = Chapters.mode(checkedMode ? checkedMode.value : "quick");
  const preset = Chapters.modeOptions(mode.id, Catalogue.defaults());
  const advanced = (key) => Catalogue.GROUPS.some(
    (group) => group.in_advanced && group.key === Catalogue.BY_KEY[key].group
  );
  const sentNow = Object.keys(Catalogue.toRequestOptions(pageState.optionValues)).filter(advanced);
  const sentByPreset = Object.keys(Catalogue.toRequestOptions(preset)).filter(advanced);
  const same = (key) => JSON.stringify(pageState.optionValues[key]) === JSON.stringify(preset[key]);
  const changed = new Set([...sentNow, ...sentByPreset].filter((key) => !same(key))).size;
  el("advanced-summary").textContent = changed
    ? `進階選項：已調整 ${changed} 項`
    : sentByPreset.length
      ? `進階選項：${mode.label}預設 ${sentByPreset.length} 項`
      : "進階選項：全部為產品預設";
  el("advanced-summary").dataset.state = changed ? "changed" : "default";
  refreshModeSummary();
}

// 計算口徑收合後，摘要印出實際生效的值：不設推薦值不等於逼人先選一次，預設仍然存在。
function refreshModeSummary() {
  const summary = document.getElementById("mode-summary");
  if (!summary) return;
  const zodiac = document.getElementById("zodiac");
  const parts = [];
  if (zodiac) {
    parts.push(zodiac.value === "sidereal" ? "恆星黃道" : "回歸黃道");
    if (zodiac.value === "sidereal") {
      const ayanamsa = document.getElementById("ayanamsa");
      if (ayanamsa && ayanamsa.selectedIndex >= 0) {
        parts.push(ayanamsa.options[ayanamsa.selectedIndex].textContent);
      }
    }
  }
  if (pageState.optionValues.include_houses === false) {
    parts.push("不計算宮位");
  } else {
    const option = Catalogue.BY_KEY.house_system;
    const chosen = option.values.filter(
      (value) => String(value.value) === String(pageState.optionValues.house_system),
    )[0];
    // 中文名接「制」（整宮制、等分宮制）；以人名命名的拉丁名不接中文字。
    if (chosen) parts.push(chosen.label_zh === chosen.label_en ? chosen.label_zh : `${chosen.label_zh}制`);
  }
  summary.textContent = parts.join(" · ");
  refreshPlanUi();
}

el("reset-options").addEventListener("click", () => {
  pageState.optionValues = Catalogue.defaults();
  refreshOptionUi();
  noteFormChanged();
  setStatus("進階選項已回到產品預設。", "info");
});

// 模式只是一組預先勾好的選項（result-chapters.js 的 MODES），換模式＝把選項換成那一組：
// 快速看盤就是產品預設，表單只留出生資料與一行「這次會算什麼」；古典完整另有第一層的勾選、
// 三個流派選單與「算完接著排時間主星」；自訂把計算口徑與進階選項全部攤開，匯出預設帶驗算資料。
// 送出的仍是同一份選項，收據照舊列出實際生效的每一項。模式不寫任何儲存，站內連結帶的 mode
// 只在載入時讀一次（linkedMode）。

// 古典完整第一層的三個流派選單：選項由目錄產生，與進階選項裡的同名選單同步（都讀寫 optionValues）。
function buildPlanProfiles() {
  const slots = el("plan-profile-slots");
  PLAN_PROFILE_KEYS.forEach((key) => {
    const option = Catalogue.BY_KEY[key];
    const field = make("div", "field");
    const label = document.createElement("label");
    label.htmlFor = `plan-${key}`;
    label.textContent = option.label_zh;
    const select = markNoRestore(document.createElement("select"));
    select.id = `plan-${key}`;
    select.className = "option-control";
    select.dataset.planKey = key;
    option.values.forEach((value) => {
      const opt = document.createElement("option");
      opt.value = value.value === null ? "\u0000null" : String(value.value);
      opt.textContent = value.label_zh;
      select.appendChild(opt);
    });
    field.append(label, select);
    slots.appendChild(field);
  });
}
const PLAN_PROFILE_KEYS = Object.freeze(["bounds_profile", "decan_profile", "triplicity_profile"]);

/** 第一層的控制項照 optionValues 重畫；被互斥擋住的照進階選項的做法停用。 */
function refreshPlanUi() {
  el("plan-classical").querySelectorAll("[data-plan-key]").forEach((control) => {
    const key = control.dataset.planKey;
    const value = pageState.optionValues[key];
    if (control.type === "checkbox") {
      control.checked = control.dataset.planOn ? value === control.dataset.planOn : value === true;
    } else {
      control.value = value === null || value === undefined ? "\u0000null" : String(value);
    }
  });
  el("plan-summary").textContent = planSummary();
}

function onPlanChange(event) {
  const control = event.target;
  const key = control.dataset ? control.dataset.planKey : null;
  if (!key) return;
  let value;
  if (control.type === "checkbox") {
    // 沒寫 data-plan-off 的選單式選項，取消勾選就回到「不計算」（null）。
    value = control.dataset.planOn
      ? (control.checked ? control.dataset.planOn : (control.dataset.planOff ?? null))
      : control.checked;
  } else {
    value = control.value === "\u0000null" ? null : control.value;
  }
  setOption(key, value);
}
el("plan-classical").addEventListener("change", onPlanChange);

/** 「這次會算什麼」的一行：讀目前的選項與口徑，名稱取自目錄，不另寫一份。 */
function planSummary() {
  const label = (key) => {
    const option = Catalogue.BY_KEY[key];
    const chosen = (option.values || []).find((value) => value.value === pageState.optionValues[key]);
    return chosen ? chosen.label_zh : "";
  };
  const parts = [el("mode-summary").textContent];
  parts.push(pageState.optionValues.body_selection_preset === "classical_seven_v1"
    ? "古典七顆行星與月交點"
    : `太陽到土星七顆行星${pageState.optionValues.include_outer_planets ? "、外行星" : ""}與月交點`);
  if (pageState.optionValues.include_aspects !== false) {
    const orb = label("aspect_orb_profile");
    parts.push(`相位：${label("aspect_set_profile")}${orb ? `（容許度：${orb}）` : ""}`);
  }
  const extras = Catalogue.OPTIONS
    .filter((option) => option.type === "boolean" && option.default === false && !option.depends_on
      && pageState.optionValues[option.key] === true)
    .map((option) => option.label_zh);
  if (extras.length) parts.push(`另加：${extras.join("、")}`);
  [...PLAN_PROFILE_KEYS, "peregrine_profile"].forEach((key) => {
    if (pageState.optionValues[key] !== null && pageState.optionValues[key] !== undefined) {
      // 「全部並列」說出是幾套（具名的那幾個值，不含「不計算」與「全部並列」本身）。
      const named = Catalogue.BY_KEY[key].values.filter((value) => value.value !== null && value.value !== "all");
      const count = pageState.optionValues[key] === "all" ? `（${named.length} 套）` : "";
      parts.push(`${Catalogue.BY_KEY[key].label_zh}：${label(key)}${count}`);
    }
  });
  const line = `這次會算：${parts.join("；")}。`;
  return pageState.currentModeId === "quick" ? `${line}要多算或改設定，請改選「古典完整」或「自訂」。` : line;
}

/**
 * 換成一種模式：選項換成那一組、口徑回到預設、表單收合或攤開、匯出內容的預設跟著換。
 * 結果若已畫出，表單因此改變時照常標成過期（noteFormChanged）。
 */
function applyMode(id) {
  const mode = Chapters.mode(id);
  pageState.currentModeId = mode.id;
  const radio = document.querySelector(`input[name="calc-mode"][value="${mode.id}"]`);
  if (radio) radio.checked = true;
  pageState.optionValues = Chapters.modeOptions(mode.id, Catalogue.defaults());
  pageState.positionsFull = null;
  zodiacSelect.value = "tropical";
  ayanamsaSelect.selectedIndex = 0;
  applyZodiacConsequences();
  el("settings-mode").hidden = !mode.showSettings;
  el("settings-advanced").hidden = !mode.showSettings;
  el("mode").open = mode.openSettings;
  el("advanced").open = mode.openSettings;
  el("plan-classical").hidden = mode.id !== "classical";
  el("plan-timelords").checked = mode.timelordsAfterChart;
  // 匯出內容的預設跟著模式（自訂預設帶驗算資料）。畫面上已有結果時與自己點選同一個效果：
  // 選了「運算結果＋驗算資料」就去取驗算資料。
  const exportMode = document.querySelector(`input[name="export-detail-mode"][value="${mode.exportDetail}"]`);
  if (exportMode && !exportMode.checked) {
    exportMode.checked = true;
    if (mode.exportDetail === "reproducibility_detail") loadVerificationDetail();
    refreshDetailUi();
  }
  refreshOptionUi();
  noteFormChanged();
}

function onModeChange(event) {
  if (event.target.name === "calc-mode" && event.target.checked) {
    applyMode(event.target.value);
    setStatus(`已換成「${Chapters.mode(event.target.value).label}」：選項改成這個模式預先勾好的那一組。`, "info");
  }
}
el("mode-choice").addEventListener("change", onModeChange);

// 地點：離線目錄查詢。
const placeQuery = el("place-query");
const placeResults = el("place-results");
const placeStatus = el("place-status");
