(function calculatePage() {
  "use strict";

  // 這一層只做接線：收表單、打同源 API、把 view tree 變成元素、接匯出與清除。
  // 「回應長什麼樣」在 view-model.js，「有哪些選項」在 options-catalogue.js，
  // 序列化在 exporters.js。這裡不得自行讀 source_response 組畫面（契約 §10）。

  // 本頁不讀網址的 query 或 fragment；帶著它們來的，是訪客或連結放進去的東西，
  // 可能就是出生資料。第一件事就從網址列與這一筆歷史紀錄拿掉（取代，不新增），
  // 排在任何可能丟錯的初始化之前，載入失敗時也不留在網址上。瀏覽器在載入前
  // 已記下的全域歷史，本頁收不回。唯一的例外是站內連結帶的模式（mode）：拿掉之前讀一次，
  // 只認三個固定值，其餘的鍵一概不讀。
  const linkedMode = window.ResultChapters ? window.ResultChapters.modeFromQuery(window.location.search) : null;
  function clearAddressInput() {
    if (window.location.search || window.location.hash) {
      window.history.replaceState(null, "", window.location.pathname);
    }
  }
  clearAddressInput();

  const Catalogue = window.OptionsCatalogue;
  const Labels = window.ArmillaryLabels;
  const LocationReceipt = window.LocationReceipt;
  const lifecycle = window.PrivacyLifecycle.createSensitiveDataLifecycle({
    revokeObjectUrl: (url) => URL.revokeObjectURL(url),
  });
  const placeSearchLifecycle = window.PrivacyLifecycle.createSensitiveDataLifecycle();

  const el = (id) => document.getElementById(id);
  /** 新元素與它的 class（class 一律照字寫，樣式包的檢查讀得到）。 */
  const make = (tag, className) => {
    const node = document.createElement(tag);
    node.className = className;
    return node;
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
  // 本命盤速覽排在警告之後、匯出工具列之前：算完不必捲過工具列與區塊索引就看得到。
  // 它是結果首屏（#result-lead）的第一個子元素，接著是常用匯出與星盤圖；窄螢幕依這個順序
  // 上下排，桌機由 calculate.css 排成左圖右速覽。內容是 view tree 的 summary 區段，畫法與其他區段相同。
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
  // view-model.js（回應 → sections → view tree）只在畫結果時才用得到，卻是本頁最大的
  // script，所以不在開機時載入：第一次與表單互動時開始抓，送出時與計算請求一起等，
  // 兩者都到了才畫。網址（含內容版本）由 build_pages 寫在本 script 的 data-view-model。
  // 用 import() 而不是插入 <script>：同源模組符合 script-src 'self'，也不經過
  // script.src 這個 Trusted Types 的注入點。
  const viewModelSource = document.querySelector("script[data-view-model]");
  const VIEW_MODEL_URL = viewModelSource ? viewModelSource.dataset.viewModel : null;
  if (!window.ChartViewModel && !VIEW_MODEL_URL) {
    throw new Error("calculate.js 沒有 view-model.js 的位址。");
  }
  let viewModelLoad = null;
  let viewModelFailures = 0;
  function loadViewModel() {
    if (window.ChartViewModel) return Promise.resolve();
    if (!viewModelLoad) {
      // 瀏覽器把抓取失敗的模組網址記成失敗，同一網址再 import 不會重抓；
      // 重試時換一個查詢參數，下一次送出才真的再抓一次。
      const url = viewModelFailures ? `${VIEW_MODEL_URL}&retry=${viewModelFailures}` : VIEW_MODEL_URL;
      viewModelLoad = Promise.resolve().then(() => import(url)).then(() => {
        if (!window.ChartViewModel) throw new Error("view-model.js 沒有提供 ChartViewModel。");
      }).catch((error) => {
        viewModelFailures += 1;
        viewModelLoad = null;
        throw error;
      });
    }
    return viewModelLoad;
  }
  form.addEventListener("focusin", () => { loadViewModel().catch(() => {}); }, { once: true });
  // 技術區塊的集合只有一個出處：exporters 匯出的驗算區段集合。「運算結果」
  // 匯出排除哪些區段，畫面就把哪些收進「技術細節」；不另抄一份 id 清單。
  // 不從投影結果反推：投影同時排除「未請求」的區段，反推
  // 會把它們錯收進技術細節。缺少這個集合時讓初始化失敗，載入訊息留在畫面上。
  const TECHNICAL_SECTION_IDS = window.ChartExport.REPRODUCIBILITY_SECTION_IDS;
  if (!TECHNICAL_SECTION_IDS || typeof TECHNICAL_SECTION_IDS.has !== "function") {
    throw new Error("exporters 未提供驗算區段集合。");
  }

  // 讀值、範圍檢查與模糊時刻判定都在 RequestInput，理由見該模組開頭。
  // 宣告放在這裡而不是 buildPayload 附近，因為 refreshFoldChoice
  // 也用它，而那個函式定義得更早（const 有 TDZ，宣告必須先於任何呼叫）。
  const RI = window.RequestInput;
  const TimezoneNames = window.TimezoneNames;

  let optionValues = Catalogue.defaults();
  let selectedPlace = null;            // 目錄選定的地點，含收據欄位
  let civilTimeBasis = null;           // 新疆的地點：出生紀錄用的鐘點；null = 尚未選
  let manualCivilTime = false;         // 手動座標、時區填的是新疆時間：同樣要問鐘點
  const sectionSnapshots = new Map();  // section id -> canonical section

  // 驗算資料的取得狀態。宣告在最前面：清除與過期判定在初始化時
  // 就會被呼叫，而它們都要讀這份狀態（const 有 TDZ）。
  const DETAIL = Object.freeze({
    IDLE: "idle", LOADING: "loading", READY: "ready", FAILED: "failed",
  });
  const verification = { state: DETAIL.IDLE, canonical: null, message: "", actions: [] };
  let boundPayload = null;       // 畫面上那份結果的請求；清除結果時一併放掉
  let pageCanonical = null;      // 畫面上那份結果（預設回應）的 canonical document
  let resultGeneration = 0;      // 每次畫出或清除結果都前進；遲到的驗算資料比對它
  let technicalHost = null;      // 「技術細節與驗算資料」的 <details>
  let lastExportActions = { copy_enabled: true, download_enabled: true };

  // ══ 選項介面：由目錄產生，不手寫 ══════════════════════
  //
  // 摺疊只有一層：「進階選項」開或關。展開後所有選項一次攤在畫面上，
  // 分組只是視覺分隔線，不是要點開的容器，也沒有搜尋框——
  // 使用者是看到 Lilith 才想起要看它，不是先想起名字再去搜尋（辨識優於回憶）。
  // 相依子項縮排在父項底下，不另外摺疊。

  function buildOptionUi() {
    const host = el("option-groups");
    host.replaceChildren();

    Catalogue.GROUPS.filter((group) => group.in_advanced).forEach((group) => {
      const block = make("div", "option-block");
      block.dataset.group = group.key;
      block.setAttribute("role", "group");

      const heading = make("div", "option-heading");
      heading.id = `option-group-${group.key}-heading`;
      block.setAttribute("aria-labelledby", heading.id);
      heading.append(group.label_zh);
      const en = make("span", "en");
      en.lang = "en";   // WCAG 3.1.2：英文並列標籤用英文念
      en.textContent = group.label_en;
      heading.appendChild(en);
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
        optionValues = { ...optionValues, include_houses: false };
      } else {
        optionValues = {
          ...optionValues, include_houses: true, house_system: select.value,
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
    if (optionValues.include_houses === false) {
      return "不計算宮位：這次完全不算宮位；要用到上升點或中天的項目會標成不可用。";
    }
    const chosen = Catalogue.BY_KEY.house_system.values.find(
      (value) => String(value.value) === String(optionValues.house_system),
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

  // 每個動態產生的控制項都必須關閉瀏覽器的表單還原。
  //
  // 不關閉時，重新載入會讓瀏覽器把 checkbox 復原成上一次的狀態並觸發
  // change，於是送出的模組組合與畫面初始狀態不符——一個看不見的預設值
  // 因此影響了結果。
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
      const input = markNoRestore(document.createElement("input"));
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
    optionValues = { ...optionValues, [key]: value };
    refreshOptionUi();
  }

  function refreshOptionUi() {
    Catalogue.OPTIONS.forEach((option) => {
      const control = document.getElementById(`opt-${option.key}`);
      if (!control) return;
      const value = optionValues[option.key];
      if (option.type === "boolean" && option.render === "select") {
        control.value = value === true ? "true" : "false";
      } else if (option.type === "boolean") control.checked = value === true;
      else if (option.type === "choice") {
        control.value = value === null ? "\u0000null" : String(value);
      } else control.value = value === null || value === undefined ? "" : String(value);

      const row = control.closest(".option-row");
      if (row) row.classList.toggle("is-changed", Catalogue.isEnabled(option, value));

      // 互斥：停用並就地說明，不隱藏。隱藏會讓人以為選項不存在。
      const conflict = Catalogue.conflictFor(option, optionValues);
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

      const nest = document.querySelector(`[data-children-of="${option.key}"]`);
      if (nest) {
        const active = option.type === "boolean"
          ? value === true
          : value !== null && value !== undefined;
        nest.hidden = !active;
      }
    });

    const houseSelect = document.getElementById("opt-house_system");
    if (houseSelect) {
      houseSelect.value = optionValues.include_houses === false
        ? NO_HOUSES : String(optionValues.house_system);
      const mirror = document.getElementById("opt-include_houses");
      if (mirror) mirror.value = String(optionValues.include_houses === true);
      const detail = document.getElementById("opt-house_system-detail");
      if (detail) detail.textContent = houseSystemDetail();
    }

    // 標題說的是「進階選項」，只數進階群組。主表單的宮位選擇就在眼前；計進來會讓
    // 只選了「不計算宮位」的人讀到「已調整 1 項」，卻在進階選項裡找不到那一項。
    // 「已調整」只數使用者自己改的：模式預先勾好的那幾項（例如古典完整的 4 項）不算，
    // 改寫成「古典完整預設 4 項」，不用強調色。模式讀畫面上選中的那一顆（這個函式在
    // currentModeId 宣告之前就會被呼叫）。
    const checkedMode = document.querySelector('input[name="calc-mode"]:checked');
    const mode = Chapters.mode(checkedMode ? checkedMode.value : "quick");
    const preset = Chapters.modeOptions(mode.id, Catalogue.defaults());
    const advanced = (key) => Catalogue.GROUPS.some(
      (group) => group.in_advanced && group.key === Catalogue.BY_KEY[key].group
    );
    const sentNow = Object.keys(Catalogue.toRequestOptions(optionValues)).filter(advanced);
    const sentByPreset = Object.keys(Catalogue.toRequestOptions(preset)).filter(advanced);
    const same = (key) => JSON.stringify(optionValues[key]) === JSON.stringify(preset[key]);
    const changed = new Set([...sentNow, ...sentByPreset].filter((key) => !same(key))).size;
    el("advanced-summary").textContent = changed
      ? `進階選項：已調整 ${changed} 項`
      : sentByPreset.length
        ? `進階選項：${mode.label}預設 ${sentByPreset.length} 項`
        : "進階選項：全部為產品預設";
    el("advanced-summary").dataset.state = changed ? "changed" : "default";
    refreshModeSummary();
  }

  // 計算口徑收合後，摘要必須把目前實際生效的值講出來。
  // 「不設推薦值」與「不要求使用者在第一屏就決定」是兩件事：預設仍然存在，
  // 誠實的做法是把它印出來，不是逼人先選一次。
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
    if (optionValues.include_houses === false) {
      parts.push("不計算宮位");
    } else {
      const option = Catalogue.BY_KEY.house_system;
      const chosen = option.values.filter(
        (value) => String(value.value) === String(optionValues.house_system),
      )[0];
      // 中文名接「制」（整宮制、等分宮制）；以人名命名的拉丁名不接中文字。
      if (chosen) parts.push(chosen.label_zh === chosen.label_en ? chosen.label_zh : `${chosen.label_zh}制`);
    }
    summary.textContent = parts.join(" · ");
    refreshPlanUi();
  }

  el("reset-options").addEventListener("click", () => {
    optionValues = Catalogue.defaults();
    refreshOptionUi();
    noteFormChanged();
    setStatus("進階選項已回到產品預設。", "info");
  });

  // ══ 三種模式 ══════════════════════════════════════════
  //
  // 模式只是一組預先勾好的選項（result-chapters.js 的 MODES），換模式＝把選項換成那一組：
  // 快速看盤就是產品預設，表單只留出生資料與一行「這次會算什麼」；古典完整另有第一層的勾選、
  // 三個流派選單與「算完接著排時間主星」；自訂把計算口徑與進階選項全部攤開，匯出預設帶驗算資料。
  // 送出的仍是同一份選項，收據照舊列出實際生效的每一項。模式不寫任何儲存，站內連結帶的 mode
  // 只在載入時讀一次（linkedMode）。
  let currentModeId = "quick";
  let lastRenderedMode = null;

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
      const value = optionValues[key];
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
      value = control.dataset.planOn
        ? (control.checked ? control.dataset.planOn : control.dataset.planOff)
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
      const chosen = (option.values || []).find((value) => value.value === optionValues[key]);
      return chosen ? chosen.label_zh : "";
    };
    const parts = [el("mode-summary").textContent];
    parts.push(optionValues.body_selection_preset === "classical_seven_v1"
      ? "古典七顆行星與月交點"
      : `太陽到土星七顆行星${optionValues.include_outer_planets ? "、外行星" : ""}與月交點`);
    if (optionValues.include_aspects !== false) {
      const orb = label("aspect_orb_profile");
      parts.push(`相位：${label("aspect_set_profile")}${orb ? `（容許度：${orb}）` : ""}`);
    }
    const extras = Catalogue.OPTIONS
      .filter((option) => option.type === "boolean" && option.default === false && !option.depends_on
        && optionValues[option.key] === true)
      .map((option) => option.label_zh);
    if (extras.length) parts.push(`另加：${extras.join("、")}`);
    PLAN_PROFILE_KEYS.forEach((key) => {
      if (optionValues[key] !== null && optionValues[key] !== undefined) {
        parts.push(`${Catalogue.BY_KEY[key].label_zh}：${label(key)}`);
      }
    });
    const line = `這次會算：${parts.join("；")}。`;
    return currentModeId === "quick" ? `${line}要多算或改設定，請改選「古典完整」或「自訂」。` : line;
  }

  /**
   * 換成一種模式：選項換成那一組、口徑回到預設、表單收合或攤開、匯出內容的預設跟著換。
   * 結果若已畫出，表單因此改變時照常標成過期（noteFormChanged）。
   */
  function applyMode(id) {
    const mode = Chapters.mode(id);
    currentModeId = mode.id;
    const radio = document.querySelector(`input[name="calc-mode"][value="${mode.id}"]`);
    if (radio) radio.checked = true;
    optionValues = Chapters.modeOptions(mode.id, Catalogue.defaults());
    positionsFull = null;
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

  // ══ 地點：離線目錄查詢 ════════════════════════════════
  const placeQuery = el("place-query");
  const placeResults = el("place-results");
  const placeStatus = el("place-status");
  const PLACE_SEARCH_TIMEOUT_MS = 10000;
  // 地點查詢的狀態是閉集：「未搜尋」「查詢中」「找到」「原字零筆、改列拼法相近的地名」
  // 「服務答了但零筆」「查詢裡沒有可比對的文字」「服務答了但答案讀不懂」「服務拒絕」「逾時」
  // 「沒送達」「字太少」各是不同值。
  // 寫在 #place-status 的 data-state，訊息文字只是它的呈現。
  const PLACE_SEARCH = Object.freeze({
    NOT_SEARCHED: "not_searched",
    SEARCHING: "searching",
    FOUND: "found",
    SPELLING_FALLBACK: "spelling_fallback",
    NONE: "none",
    NOTHING_SEARCHABLE: "no_searchable_tokens",
    UNREADABLE: "unreadable",
    REJECTED: "rejected",
    TIMEOUT: "timeout",
    FAILED: "failed",
    TOO_SHORT: "too_short",
  });

  function setPlaceStatus(state, message, tone) {
    placeStatus.dataset.state = state;
    placeStatus.textContent = message;
    placeStatus.dataset.tone = tone;
  }

  el("place-search-button").addEventListener("click", searchPlaces);
  placeQuery.addEventListener("keydown", (event) => {
    // 注音、倉頡選字時的 Enter 是確認組字。組字中 isComposing 為真；Safari 等在
    // 組字結束那一下只給 keyCode 229。兩者都不是要查詢。
    if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    searchPlaces();
  });

  function revealPlaceResults() {
    if (typeof placeResults.scrollIntoView !== "function") return;
    placeResults.scrollIntoView({ block: "nearest", behavior: prefersReducedMotion() ? "auto" : "smooth" });
  }

  function searchPlaces() {
    placeSearchLifecycle.abortActiveRequest();
    const query = placeQuery.value.trim();
    placeResults.replaceChildren();
    placeResults.hidden = true;
    if (query.length < 2) {
      setPlaceStatus(PLACE_SEARCH.TOO_SHORT, "請輸入至少兩個字再查詢。", "error");
      return;
    }
    setPlaceStatus(PLACE_SEARCH.SEARCHING, "查詢中…", "info");
    const { controller, token, timeout } = placeSearchLifecycle.beginTimedRequest(
      PLACE_SEARCH_TIMEOUT_MS, window.setTimeout.bind(window)
    );

    // 與 /api/chart 同一條政策：2xx 也要驗 media type 與形狀。
    postJson("/api/places/search", { query, limit: 10 }, controller.signal)
      .then(({ response, body, invalidJsonMedia }) => {
        if (!placeSearchLifecycle.isCurrentRequest(token)) return;
        if (!response.ok) {
          setPlaceStatus(
            PLACE_SEARCH.REJECTED,
            window.ClientContext.formatApiError(body && body.detail, response.status),
            "error"
          );
          return;
        }
        // 「服務答了但零筆」與「服務答了但答案讀不懂」是兩個值。把畸形回應
        // 當成零筆，會讓使用者以為目錄裡真的沒有這個地方。
        const shaped = !invalidJsonMedia
          && body && typeof body === "object" && !Array.isArray(body)
          && Array.isArray(body.results);
        if (!shaped) {
          setPlaceStatus(
            PLACE_SEARCH.UNREADABLE,
            "地名查詢的回應無法解讀，這不代表目錄裡沒有這個地方。請重試；若持續發生，請在下方手動輸入座標與時區。",
            "error"
          );
          return;
        }
        // 只有標點或符號時後端沒有搜尋；說「目錄裡沒有」會是假話。
        if (body.query && body.query.status === "no_searchable_tokens") {
          setPlaceStatus(
            PLACE_SEARCH.NOTHING_SEARCHABLE,
            "查詢裡沒有可比對的文字（標點與符號會被略過）。請輸入地名，或在下方手動輸入座標與時區。",
            "error"
          );
          return;
        }
        const found = body.results;
        // 後端會回一份 query 收據，說明有沒有詞被丟掉。不讀它，等於把一個
        // 被改寫過的查詢報成使用者自己的查詢。
        const truncation = window.ClientContext.placeQueryNotice(body.query);
        if (!found.length) {
          setPlaceStatus(
            PLACE_SEARCH.NONE,
            truncation
              ? `內建目錄沒有符合的地名。${truncation}`
              : "內建目錄沒有符合的地名。可以改用鄰近的較大地點，或在下方手動輸入座標與時區。",
            "error"
          );
          return;
        }
        // 原字查無結果時後端改列拼法相近的地名；不說明，使用者會以為列出的就是他打的字。
        // 被截斷時是警告而不是單純資訊：結果不涵蓋使用者打的全部內容。
        const fallback = Boolean(body.query && body.query.spelling_fallback
          && body.query.spelling_fallback.status === "applied");
        if (fallback) {
          setPlaceStatus(
            PLACE_SEARCH.SPELLING_FALLBACK,
            `找不到與「${query}」相符的地名；以下 ${found.length} 筆是拼法相近（最多差兩個字母）的地名，`
              + `請確認是不是你要找的地方。座標為目錄的代表點，不是出生地址。${truncation || ""}`,
            "warning"
          );
        } else {
          setPlaceStatus(
            PLACE_SEARCH.FOUND,
            truncation
              ? `找到 ${found.length} 筆。座標為目錄的代表點，不是出生地址。${truncation}`
              : `找到 ${found.length} 筆。座標為目錄的代表點，不是出生地址。`,
            truncation ? "warning" : "info"
          );
        }
        found.forEach((place) => placeResults.appendChild(buildPlaceRow(place)));
        placeResults.hidden = false;
        // 手機上清單常落在視窗下緣之外，看起來像沒反應：捲到剛好看得見（已看得見就不動）。焦點留在查詢欄。
        revealPlaceResults();
      })
      .catch((error) => {
        if (!placeSearchLifecycle.isCurrentRequest(token)) return;
        const timedOut = timeout.didTimeout() && error && error.name === "AbortError";
        setPlaceStatus(
          timedOut ? PLACE_SEARCH.TIMEOUT : PLACE_SEARCH.FAILED,
          timedOut
            ? "地名查詢逾時。請重試，或在下方手動輸入座標與時區。"
            : "地名查詢沒有完成。這個查詢只讀取內建目錄，不會對外連線；請重試，或在下方手動輸入座標與時區。",
          "error"
        );
      })
      .finally(() => {
        window.clearTimeout(timeout.handle);
        placeSearchLifecycle.finishRequest(token);
      });
  }

  function buildPlaceRow(place) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "place-option";

    // 目錄只在標籤與他筆相同時給 disambiguator（二級行政區或座標），附在標籤後。
    const name = document.createElement("b");
    const label = place.display_name || place.name;
    name.textContent = place.disambiguator ? `${label}（${place.disambiguator}）` : label;
    button.appendChild(name);

    // 同名地點必須靠這一行分辨，因此經緯度、時區、來源與人口都要出現。
    const meta = make("span", "place-meta mono");
    // 來源念中文短名，不念目錄代碼；原始代碼在選定後的收據技術細節裡。
    meta.textContent = [
      `${Number(place.latitude).toFixed(4)}, ${Number(place.longitude).toFixed(4)}`,
      place.timezone,
      place.country_code,
      place.population ? `人口 ${place.population.toLocaleString("en-US")}` : "人口不詳",
      Labels.label("place_source_short", place.source),
    ].filter(Boolean).join("　·　");
    button.appendChild(meta);

    button.addEventListener("click", () => selectPlace(place));
    item.appendChild(button);
    return item;
  }

  // ── 出生紀錄用北京時間還是新疆時間 ─────────────────────
  //
  // 新疆同時使用北京時間與新疆時間；目錄對這類地點回兩種鐘點
  // （civil_time_basis_choices，北京時間在前）。沒有預設：選定前時區欄留空、
  // 送出 fail closed；選定後時區欄填入那一種的 IANA 時區，請求一併送出所選的鐘點。
  //
  // 手動輸入座標沒有目錄列可問，服務也不以座標判定（沒有省界多邊形）：使用者親手把時區
  // 填成新疆時間（Asia/Urumqi 或其 tz 連結 Asia/Kashgar）時，問同一個問題、給同樣兩個選項；
  // 服務對這種請求同樣要求指明鐘點。選項之後由程式改寫時區欄，不會再觸發這個判定。
  const XINJIANG_TIME_ZONES = Object.freeze(["Asia/Urumqi", "Asia/Kashgar"]);
  const MANUAL_CIVIL_TIME_CHOICES = Object.freeze([
    Object.freeze({ civil_time_basis: "beijing_time", iana_name: "Asia/Shanghai" }),
    Object.freeze({ civil_time_basis: "xinjiang_time", iana_name: "Asia/Urumqi" }),
  ]);
  function civilTimeChoices(place) {
    if (!place) return manualCivilTime ? MANUAL_CIVIL_TIME_CHOICES : null;
    return Array.isArray(place.civil_time_basis_choices)
      && place.civil_time_basis_choices.length
      ? place.civil_time_basis_choices
      : null;
  }

  function chosenCivilTime() {
    const choices = civilTimeChoices(selectedPlace);
    if (!choices || civilTimeBasis === null) return null;
    return choices.find((choice) => choice.civil_time_basis === civilTimeBasis) || null;
  }

  // 目錄收據仍成立時，時區欄應有的值；不同就是使用者手動改過。
  function expectedPlaceTimezone(place) {
    if (!civilTimeChoices(place)) return String(place.timezone || "");
    const chosen = chosenCivilTime();
    return chosen ? chosen.iana_name : "";
  }

  function renderCivilTimeChoice(place) {
    const choices = civilTimeChoices(place);
    const options = el("civil-time-choice-options");
    options.replaceChildren();
    // 上一組選項的錯誤訊息不再對應任何選項。
    const stale = document.getElementById("civil_time_basis-error");
    if (stale) stale.remove();
    civilTimeBasis = null;
    el("civil-time-choice").hidden = !choices;
    (choices || []).forEach((choice) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "civil_time_basis";
      input.value = choice.civil_time_basis;
      // 先於表單層的 change 執行：noteFormChanged 重算模糊時刻時，時區欄已是所選的那一種。
      input.addEventListener("change", () => {
        civilTimeBasis = choice.civil_time_basis;
        el("timezone").value = choice.iana_name;
      });
      const caption = document.createElement("span");
      const bold = document.createElement("b");
      bold.textContent = Labels.label("civil_time_basis", choice.civil_time_basis);
      const zone = make("span", "mono");
      zone.lang = "en";
      zone.textContent = choice.iana_name;
      caption.append(bold, zone);
      label.append(input, caption);
      options.appendChild(label);
    });
  }

  function selectPlace(place) {
    selectedPlace = place;
    manualCivilTime = false;
    el("latitude").value = String(place.latitude);
    el("longitude").value = String(place.longitude);
    if (!el("altitude").value.trim()) el("altitude").value = "0";
    renderCivilTimeChoice(place);
    const dualClock = Boolean(civilTimeChoices(place));
    el("timezone").value = expectedPlaceTimezone(place);

    // 收據念的是中文標籤；目錄的原始代碼與記錄 id 收在「技術細節」摺疊裡，
    // 回報問題或對照目錄時仍拿得到，平常讀收據時不會聽到一串底線英文。
    const describe = (list, rows, lang) => {
      list.replaceChildren();
      rows.forEach(([term, en, value]) => {
        const dt = document.createElement("dt");
        dt.append(term);
        if (en) {
          const tag = make("span", "en");
          tag.lang = "en";
          tag.textContent = en;
          dt.appendChild(tag);
        }
        const dd = document.createElement("dd");
        dd.textContent = value === undefined || value === null ? "—" : String(value);
        if (lang) dd.lang = lang;
        list.append(dt, dd);
      });
    };
    // 臺灣以外的地點寫出國家或地區：同名或近名的外國地點（例：東京的台東區）一眼可辨。
    const abroad = place.country_code && place.country_code !== "TW"
      ? [["國家或地區", null, Labels.regionName(place.country_code)]]
      : [];
    describe(el("place-receipt-body"), [
      ["地點", null, place.display_name || place.name],
      ...abroad,
      ["緯度", "latitude", Number(place.latitude).toFixed(6)],
      ["經度", "longitude", Number(place.longitude).toFixed(6)],
      ["時區", "timezone", dualClock
        ? `${place.timezone}（目錄的時區；出生紀錄可能用北京時間或新疆時間，請在下方選擇）`
        : place.timezone || "—"],
      ["目錄來源", null, Labels.label("place_source", place.source)],
      ["座標語義", null, Labels.label("coordinate_semantics", place.coordinate_semantics)],
      ["位置精度", null, Labels.label("location_precision", place.location_precision)],
      ["比對層級", null, Labels.label("match_tier", place.match_tier)],
    ]);
    describe(el("place-receipt-codes"), [
      ["目錄來源", "source", place.source],
      ["目錄記錄 id", "source_record_id", place.source_record_id],
      ["座標語義", "coordinate_semantics", place.coordinate_semantics],
      ["位置精度", "location_precision", place.location_precision],
      ["比對層級", "match_tier", place.match_tier],
    ], "en");

    el("place-caveat").textContent =
      "這組座標是目錄對該地點的代表點，不是你的出生地址。上升點對經緯度敏感，"
      + "若你知道更精確的座標，請在下方手動輸入取代它。"
      + (dualClock
        ? "這個地點同時使用北京時間與新疆時間，請在下方指明出生紀錄用的是哪一種；選定前不會計算。"
        : "時區已依目錄帶入，仍請確認出生當時實際適用的時區。");
    el("place-receipt").hidden = false;
    placeResults.hidden = true;
    setPlaceStatus(
      PLACE_SEARCH.FOUND,
      dualClock
        ? "已選定地點，座標已填入；請選擇出生紀錄用的是北京時間還是新疆時間。"
        : "已選定地點，座標與時區已填入。",
      "info"
    );
    // 程式寫入座標與時區，和使用者親手輸入走同一條狀態轉移：模糊時刻的
    // 選擇區、欄位錯誤旗標、結果與表單的綁定都由 noteFormChanged 重算。
    // 少了這一步，「先填時間再選地點」的順序永遠看不到
    // 選擇區，送出卻被 fail-closed 擋住。
    noteFormChanged();
    // 剛按下的那顆結果按鈕已隨清單隱藏，焦點會掉到 body；把它移到收據上。
    // 收據在 HTML 帶 tabindex="-1"，只能被程式聚焦。
    el("place-receipt").focus();
  }

  // 手動改動座標或時區時，目錄收據不再成立，必須撤下。
  ["latitude", "longitude", "timezone"].forEach((id) => {
    el(id).addEventListener("input", () => {
      if (!selectedPlace) return;
      const drifted =
        !LocationReceipt.sameCoordinate(el("latitude").value, selectedPlace.latitude)
        || !LocationReceipt.sameCoordinate(el("longitude").value, selectedPlace.longitude)
        || String(el("timezone").value) !== expectedPlaceTimezone(selectedPlace);
      if (drifted) {
        selectedPlace = null;
        clearPlaceReceipt();
        setPlaceStatus(PLACE_SEARCH.NOT_SEARCHED, "座標或時區已手動修改，目錄收據不再適用。", "info");
      }
    });
  });

  // 手動座標親手填的時區是新疆時間：顯示鐘點選擇（重新填一次就重新問）；改成別的時區就撤下。
  el("timezone").addEventListener("input", () => {
    if (selectedPlace) return;
    const xinjiang = XINJIANG_TIME_ZONES.includes(String(el("timezone").value).trim());
    if (!xinjiang && !manualCivilTime) return;
    manualCivilTime = xinjiang;
    renderCivilTimeChoice(null);
  });

  // 時區欄的建議清單與結果的時區列取同一組中文地名（labels.js），不在頁面另寫一份。
  Object.entries(Labels.VOCABULARIES.timezone_place).forEach(([zone, place]) => {
    const option = document.createElement("option");
    option.value = zone;
    option.label = place;
    el("timezone-suggestions").appendChild(option);
  });

  // Etc/GMT±N 的正負號與 UTC 偏移相反；手動填這種名稱時，在欄位下寫出解析後的偏移。
  // 由表單的 input 事件與程式改值後的 noteFormChanged 一起更新。
  function refreshTimezoneOffset() {
    const line = el("timezone-offset");
    const zone = String(el("timezone").value).trim();
    const offset = TimezoneNames.accepts(zone) ? RI.etcGmtOffsetText(zone) : null;
    line.textContent = offset ? `${zone} 即 ${offset}（Etc/GMT 名稱的正負號與 UTC 偏移相反）。` : "";
    line.hidden = !offset;
  }

  // ══ 表單連動 ══════════════════════════════════════════
  const precisionConsequence = el("precision-consequence");
  const zodiacConsequence = el("zodiac-consequence");
  const hourInput = el("hour");
  const minuteInput = el("minute");
  const secondInput = el("second");
  const zodiacSelect = el("zodiac");
  const ayanamsaSelect = el("ayanamsa");

  function currentPrecision() {
    const checked = form.querySelector('input[name="precision"]:checked');
    return checked ? checked.value : "exact";
  }

  function applyPrecisionConsequences() {
    const precision = currentPrecision();
    minuteInput.disabled = precision !== "exact";
    secondInput.disabled = precision !== "exact";
    hourInput.disabled = precision === "date_only";
    // 停用之外還要收起來。一個灰掉的「秒」欄位不帶任何資訊，只是佔位子，
    // 而且「灰掉」還得先看懂才知道自己不必填。收起來則不必解讀。
    // 實測：整份表單並不會因此變矮（exact 1053px、approximate_hour 1112px、
    // date_only 1137px），因為讓路給了那段 .consequence 說明。這是划算的：
    // 換掉的是兩個無資訊的輸入格，換來的是一句說明後端會怎麼處理。
    // disabled 保留不動：hidden 只管版面，送出路徑仍照 precision 讀值。
    el("field-minute").hidden = precision !== "exact";
    el("field-second").hidden = precision !== "exact";
    el("field-hour").hidden = precision === "date_only";
    if (precision !== "exact") { minuteInput.value = ""; secondInput.value = ""; }
    if (precision === "date_only") hourInput.value = "";
    const messages = {
      exact: "",
      approximate_hour:
        "分與秒會以 0 送出，因為後端只接受已知的民用小時，並會自行對整個小時取樣。這些 0 不代表你出生在整點。",
      date_only:
        "時、分、秒都會以 0 送出，那只是 API 的日期容器，不代表你出生在午夜。"
        + "後端在這個模式下會關閉宮位計算，因為宮位需要已知時刻；結果中的宮位區塊會標示為未請求。",
    };
    // 不切 hidden：這一段是 aria-live 宣告區，必須常駐在無障礙樹裡，內容改變才念得到。
    precisionConsequence.textContent = messages[precision];
  }

  function applyZodiacConsequences() {
    refreshModeSummary();
    const sidereal = zodiacSelect.value === "sidereal";
    ayanamsaSelect.disabled = !sidereal;
    // 歲差校正只對恆星黃道有意義；`depends_on` 這件事本來就寫在資料裡，
    // 但畫面一直無條件呈現它，只是灰掉。回歸黃道下它是純粹的噪音。
    el("field-ayanamsa").hidden = !sidereal;
    zodiacConsequence.textContent = sidereal
      ? "恆星黃道下，本質尊貴會被產品明確拒絕而不是算錯，尊貴的判準建立在回歸黃道上，"
        + "尚未有授權的恆星黃道版本。結果中會顯示拒絕的原因代碼。"
      : "";
  }

  // ── 重複的民用小時 ─────────────────────────────────────
  //
  // 秋季調慢當天，同一個時鐘時間出現兩次。後端支援 fold 指明是哪一次，
  // 但介面送不出去，於是永遠採用第一次——盤可能整個差一小時，而畫面不說。
  // 這裡在偵測到模糊時把選擇交還給使用者，並在沒選之前 fail closed。
  let foldChoice = null;   // null = 尚未選；0/1 = 使用者選定的那一次
  // 服務判定為重複、本頁自己沒看出來的那個時刻：exact 與大約時辰都由
  // ambiguous_local_time_choice_required 拒絕給出（伺服器不替使用者猜）。只存比對用的鍵，
  // 「清除敏感資料」與任何重設都會清掉（resetFormState）。
  let serviceRepeatedTime = null;

  // 大約時辰的分與秒恆為 0（送出的 payload 也是），所以同一個鍵涵蓋兩種精確度。
  function timeKey(precision, dateValue, hour, minute, second, timezone) {
    return `${precision}|${dateValue}|${hour}|${minute}|${second}|${timezone}`;
  }

  function timeKeyOfPayload(payload) {
    const { datetime, timezone } = payload;
    return timeKey(
      payload.birth_time_precision,
      RI.isoDate(datetime.year, datetime.month, datetime.day),
      datetime.hour,
      datetime.minute,
      datetime.second,
      timezone.iana_name
    );
  }

  const SERVICE_AMBIGUITY = Object.freeze(
    { state: "ambiguous", source: "service", occurrences: [{ fold: 0 }, { fold: 1 }] }
  );

  // 出生日期欄的讀取只有這一個出處：格式、日曆與範圍（欄位自己的 min／max）。表單帶
  // novalidate，鍵盤打進來的 1895 年或 2400 年不會被瀏覽器擋下。
  function readDateField() {
    const input = el("date");
    return RI.readBirthDate(String(input.value), { min: input.min, max: input.max });
  }

  function currentAmbiguity() {
    const dateValue = String(el("date").value).trim();
    const timezone = String(el("timezone").value).trim();
    const dateRead = readDateField();
    // 範圍外或不成日期的值不問 fold：送出守衛會先指名日期本身的問題。
    if (dateRead.state !== RI.STATES.VALUE || !timezone) return null;
    const { year, month, day } = dateRead.value;
    const precision = currentPrecision();
    // date_only 由後端對整個民用日取樣，不需要這個選擇。exact 與
    // approximate_hour 都需要：後端對兩者都要求指明是重複小時的哪一次，
    // 而它拒絕的那件事，這裡就得提供得出來——否則使用者被擋在一個他無法
    // 回答的問題前面。
    if (precision === "date_only") return null;
    const hour = RI.readInteger(String(hourInput.value));
    if (hour.state !== RI.STATES.VALUE) return null;
    if (precision === "approximate_hour") {
      // 後端對整個小時取樣，所以判定的單位是整個小時，不是 HH:00:00。
      // 重複區段在小時中間開始或結束（St_Johns 23:01 起、Lord Howe 01:30 起）時，
      // 整點只出現一次，舊判法因此不給選擇，後端卻要求 fold。
      const hourResult = RI.civilHourOccurrences(
        { year, month, day, hour: hour.value }, timezone
      );
      if (hourResult && hourResult.state === "ambiguous") return hourResult;
      // 服務是時區事實的單一來源：它對這個小時回過「需要指明是哪一次」，
      // 而本頁自己的判定沒看出來時，照服務的判定提供選擇，不讓使用者卡住。
      if (serviceRepeatedTime === timeKey(precision, dateValue, hour.value, 0, 0, timezone)) {
        return SERVICE_AMBIGUITY;
      }
      return null;
    }
    const minute = RI.readInteger(String(minuteInput.value));
    if (minute.state !== RI.STATES.VALUE) return null;
    const secondRead = RI.readSecond(String(secondInput.value));
    const second = secondRead.state === RI.STATES.VALUE ? secondRead.value : 0;
    const result = RI.civilTimeOccurrences(
      { year, month, day, hour: hour.value, minute: minute.value, second },
      timezone
    );
    if (result && result.state === "ambiguous") return result;
    // 同上：服務對這個 exact 時刻回過「需要指明是哪一次」（本頁判定為單次），照服務的判定提供選擇。
    if (serviceRepeatedTime === timeKey(precision, dateValue, hour.value, minute.value, second, timezone)) {
      return SERVICE_AMBIGUITY;
    }
    return null;
  }

  function repeatSpanText(occurrences) {
    const times = occurrences.map((o) => Date.parse(o.utcIso)).filter(Number.isFinite);
    if (times.length < 2) return null;
    const minutes = Math.round(Math.abs(times[1] - times[0]) / 60000);
    if (!minutes) return null;
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    if (hours && rest) return `${hours} 小時 ${rest} 分鐘`;
    return hours ? `${hours} 小時` : `${rest} 分鐘`;
  }

  // 選擇區出現在使用者剛填完的欄位下方，視線與報讀游標都可能已經離開；狀態列
  // （role=status）是本頁的宣告管道，出現時在那裡說一次，收起時撤下這句。
  const FOLD_ANNOUNCEMENT = "這個時間在所選時區出現了兩次：請在出生時間下方的選擇區指明是哪一次。";

  // 選項重建或收起時，上一組選項的錯誤訊息不再對應任何選項。
  function removeFoldError() {
    const stale = document.getElementById("fold-error");
    if (stale) stale.remove();
  }

  function refreshFoldChoice() {
    const ambiguity = currentAmbiguity();
    const host = el("fold-choice");
    if (!ambiguity) {
      if (statusLine.textContent === FOLD_ANNOUNCEMENT) setStatus("", "info");
      removeFoldError();
      host.hidden = true;
      el("fold-choice-options").replaceChildren();
      // signature 必須一起清掉。留著的話，使用者清空表單後再輸入**同一個**
      // 模糊時刻，下面的早退會判定「選項沒變」而不重建——於是選擇區永遠不再
      // 出現，但送出仍被 fail-closed 擋下，使用者陷入無法完成計算的死路。
      delete host.dataset.signature;
      foldChoice = null;
      return;
    }
    const signature = ambiguity.source === "service"
      ? "service"
      : ambiguity.occurrences.map((o) => o.utcIso).join("|");
    if (host.dataset.signature === signature) return;   // 同一組選項不重建
    host.dataset.signature = signature;
    foldChoice = null;
    removeFoldError();

    el("fold-choice-title").textContent =
      "這個時間在所選時區出現了兩次，請指明是哪一次。";
    const options = el("fold-choice-options");
    options.replaceChildren();
    ambiguity.occurrences.forEach((occurrence, index) => {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "fold";
      input.value = String(occurrence.fold);
      input.addEventListener("change", () => { foldChoice = occurrence.fold; });
      const caption = document.createElement("span");
      const which = index === 0 ? "第一次（較早）" : "第二次（較晚）";
      if (!Number.isFinite(occurrence.offsetHours) || !occurrence.utcIso) {
        // 只有服務的判定、本頁算不出兩次各自的偏移：只列先後，不編造世界時。
        const bold = document.createElement("b");
        bold.textContent = which;
        caption.append(bold);
        label.append(input, caption);
        options.appendChild(label);
        return;
      }
      // 秒級的歷史偏移不印成長小數，一律 ±時:分:秒。
      const sign = occurrence.offsetHours >= 0 ? "+" : "−";
      const seconds = Math.round(Math.abs(occurrence.offsetHours) * 3600);
      const pad = (value) => String(value).padStart(2, "0");
      const magnitude = `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor((seconds % 3600) / 60))}`
        + (seconds % 60 ? `:${pad(seconds % 60)}` : "");
      const bold = document.createElement("b");
      bold.textContent = `${which}　UTC${sign}${magnitude}`;
      const detail = document.createElement("span");
      detail.textContent = `對應世界時 ${occurrence.utcIso.replace(".000Z", "Z")}`;
      caption.append(bold, detail);
      label.append(input, caption);
      options.appendChild(label);
    });
    // 重複的長度不一定是一小時、原因也不一定是日光節約
    // （Lord Howe 2024-04-07 重複 30 分鐘；臺北 1945-09-21 是日本標準時改回中原標準時；
    // Kwajalein 1969-09-30 重複約 23 小時），所以相差多久由兩個 UTC 時刻相減得出。
    const span = ambiguity.source === "service" ? null : repeatSpanText(ambiguity.occurrences);
    el("fold-choice-note").textContent =
      "這個時區在此時刻改變了 UTC 偏移（例如日光節約時間結束，或標準時變更），時鐘往回撥，"
      + "於是同一個鐘面時間出現兩次。"
      + (span ? `兩次相差 ${span}，` : "")
      + "算出來的上升點可能落在不同星座，所以這裡不替你猜。"
      + "若真的無法確定，任選一個，並把這件事記在結果之外，收據會記下採用了哪一次。";
    host.hidden = false;
    setStatus(FOLD_ANNOUNCEMENT, "warning");
  }

  // 表單任何一處改動——使用者輸入、程式寫入（選地點、範例）、選項重設——
  // 都走這一個轉移。相依狀態（模糊時刻選擇區、欄位錯誤旗標、結果與表單的
  // 綁定）只在這裡重算，程式寫入不得繞過它。
  function noteFormChanged(target) {
    if (!target || target.name !== "fold") refreshFoldChoice();
    refreshTimezoneOffset();
    if (target && typeof target.hasAttribute === "function" && target.hasAttribute("aria-invalid")) {
      clearFieldInvalid(target);
    }
    refreshResultBinding();
    refreshTimeCheckBinding();
  }

  form.addEventListener("change", (event) => {
    if (event.target.name === "precision") applyPrecisionConsequences();
    if (event.target.id === "zodiac") applyZodiacConsequences();
    if (event.target.id === "ayanamsa") refreshModeSummary();
    noteFormChanged(event.target);
  });
  form.addEventListener("input", (event) => { noteFormChanged(event.target); });

  // ── 換算助手：民國年與日本年號 ─────────────────────────
  //
  // 換算在 RequestInput（純函式，範圍讀出生日期欄自己的 min／max）；這裡只把結果寫進
  // 出生日期欄，並走與使用者輸入相同的轉移。助手的欄位沒有 name，不進請求。
  function setEraEcho(message, tone) {
    const echo = el("era-echo");
    echo.textContent = message;
    echo.dataset.tone = tone;
  }

  el("era-apply").addEventListener("click", () => {
    const dateInput = el("date");
    const read = RI.readEraDate({
      era: el("era-name").value,
      year: String(el("era-year").value),
      month: String(el("era-month").value),
      day: String(el("era-day").value),
    }, { min: dateInput.min, max: dateInput.max });
    if (read.state === RI.STATES.EMPTY) {
      setEraEcho("請填年、月、日。", "error");
      return;
    }
    if (read.state === RI.STATES.INVALID) {
      setEraEcho(`${read.reason}。出生日期沒有改動。`, "error");
      return;
    }
    const { eraText, gregorianText, formula, iso } = read.value;
    dateInput.value = iso;
    noteFormChanged(dateInput);
    setEraEcho(`${eraText} ＝ ${gregorianText}（${formula}），已填入出生日期。`, "info");
  });

  // ── 換算助手：核對鐘面時間 ─────────────────────────────
  //
  // 由計算服務回答（POST /api/time/convert）：它跑的是排盤時同一個換算函式、同一份時區資料庫。
  // 瀏覽器自己的時區資料版本不明，不拿來回答這個問題。請求只帶日期、時刻與時區，不帶座標；
  // 回答只留在畫面上，對應的輸入一改就撤下，清除敏感資料時與進行中的請求一起作廢。
  const TIME_CHECK_TIMEOUT_MS = 10000;
  const timeCheckLifecycle = window.PrivacyLifecycle.createSensitiveDataLifecycle();
  let timeCheckShownKey = null;

  function setTimeCheckStatus(message, tone) {
    const status = el("time-check-status");
    status.textContent = message;
    status.dataset.tone = tone;
  }

  function clearTimeCheck(message, tone) {
    timeCheckLifecycle.abortActiveRequest();
    const host = el("time-check-result");
    host.replaceChildren();
    host.hidden = true;
    timeCheckShownKey = null;
    setTimeCheckStatus(message || "", tone || "info");
  }

  /** 從目前的表單組出核對請求，或說出還缺什麼。不動 DOM。 */
  function timeCheckRequest() {
    const dateRead = readDateField();
    if (dateRead.state === RI.STATES.EMPTY) return { problem: "請先填出生日期（或用上面的年號換算）。" };
    if (dateRead.state === RI.STATES.INVALID) return { problem: `出生日期${dateRead.reason}。` };
    const precision = currentPrecision();
    if (precision === "date_only") {
      return { problem: "「只知道日期」沒有單一的鐘面時刻可以核對；請填上時刻並改選較精確的出生時間，或直接計算。" };
    }
    const inRange = (read, low, high) => read.state === RI.STATES.VALUE && read.value >= low && read.value <= high;
    const hour = RI.readInteger(String(hourInput.value));
    if (!inRange(hour, 0, 23)) return { problem: "請先填小時（0–23）。" };
    let minute = 0;
    let second = 0;
    if (precision === "exact") {
      const minuteRead = RI.readInteger(String(minuteInput.value));
      if (!inRange(minuteRead, 0, 59)) return { problem: "請先填分（0–59）。" };
      minute = minuteRead.value;
      const secondRead = RI.readSecond(String(secondInput.value));
      if (secondRead.state === RI.STATES.INVALID) return { problem: `秒${secondRead.reason}。` };
      second = secondRead.state === RI.STATES.VALUE ? secondRead.value : 0;
    }
    const civilTime = chosenCivilTime();
    if (civilTimeChoices(selectedPlace) && !civilTime) {
      return { problem: "請先在出生地點下方選擇出生紀錄用的是北京時間還是新疆時間。" };
    }
    const timezone = String(el("timezone").value).trim();
    if (!timezone) return { problem: "請先選定出生地點，或在手動輸入裡填 IANA 時區名稱。" };
    if (!TimezoneNames.accepts(timezone)) {
      return { problem: "時區名稱不在服務接受的 IANA 名單內（例如 Asia/Taipei，大小寫須相符）。" };
    }
    const { year, month, day } = dateRead.value;
    return {
      approximate: precision === "approximate_hour",
      body: {
        datetime: { year, month, day, hour: hour.value, minute, second },
        timezone: {
          mode: "iana",
          iana_name: timezone,
          ...(civilTime ? { civil_time_basis: civilTime.civil_time_basis } : {}),
        },
      },
    };
  }

  const timeCheckKey = (request) => (request.body ? JSON.stringify(request.body) : null);

  // 表單改動後，畫面上的核對結果若不再對應目前的輸入就撤下（由 noteFormChanged 呼叫）。
  function refreshTimeCheckBinding() {
    if (timeCheckShownKey === null) return;
    if (timeCheckKey(timeCheckRequest()) === timeCheckShownKey) return;
    clearTimeCheck("出生日期、時刻或時區改了；先前的核對結果已撤下，請重新核對。", "info");
  }

  function appendText(host, tag, text, className) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    node.textContent = text;
    host.appendChild(node);
    return node;
  }

  function externalLink(label, url) {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.rel = "noopener noreferrer";
    anchor.target = "_blank";
    anchor.textContent = label;
    return anchor;
  }

  const wallTime = (label) => String(label).replace(/\.000$/, "");

  function readingKind(reading) {
    const regime = reading.rule && reading.rule.regime;
    const kind = regime ? Labels.label("civil_time_regime", regime) : (reading.summer_time ? "夏令時間" : "非夏令時間");
    return `${kind}，時區縮寫 ${reading.abbreviation}`;
  }

  function renderRule(host, rule, checkedVersion) {
    if (!rule || rule.status === "not_cited") {
      appendText(host, "p", "這一段沒有可引用的文件（未引用）：時區資料庫的值是它自己的推定。", "caveat");
      return;
    }
    if (rule.status !== "cited" || !rule.source) {
      appendText(host, "p",
        `服務正在使用的時區資料庫對這一段的說法，與本站出處表（依 ${checkedVersion} 核對）不同，因此不列出處。`,
        "caveat");
      return;
    }
    const source = rule.source;
    const list = document.createElement("dl");
    const row = (term, ...content) => {
      const dt = document.createElement("dt");
      dt.textContent = term;
      const dd = document.createElement("dd");
      dd.append(...content);
      list.append(dt, dd);
    };
    row("規則", source.title);
    row("依據文件", source.document);
    row("我們核到哪一層", source.verification_label);
    const read = [];
    source.read.forEach((item, index) => {
      if (index) read.push("；");
      read.push(externalLink(item.label, item.url));
    });
    row("我們讀過的", ...read);
    const holder = [];
    if (source.holder.name) {
      holder.push(source.holder.url ? externalLink(source.holder.name, source.holder.url) : source.holder.name);
      holder.push("。");
    }
    holder.push(source.holder.note);
    row("原件在哪裡", ...holder);
    host.appendChild(list);
  }

  function renderTimeCheck(body, approximate) {
    const host = el("time-check-result");
    host.replaceChildren();
    const zone = body.timezone;
    const where = `${zone.region_label}（${zone.iana_name}）`;
    const local = wallTime(body.input_local_time);
    if (approximate) {
      appendText(host, "p", `只知道約略小時：這裡核對的是 ${local} 這一刻；計算時會對整個小時取樣。`, "note");
    }
    const readings = Array.isArray(body.readings) ? body.readings : [];
    let rules;
    if (body.status === "nonexistent" && body.gap) {
      const gap = body.gap;
      appendText(host, "p",
        `${local} 在${where}不存在：時鐘在 ${gap.skipped_local_start} 從 ${gap.offset_before_label} `
        + `撥到 ${gap.offset_after_label}，${gap.skipped_local_start} 到 ${gap.skipped_local_end} 之間的鐘面時間被跳過了。`
        + "請核對出生紀錄的日期與時刻；服務不會替你挪動。");
      rules = [gap.rule];
    } else if (body.status === "repeated" && readings.length === 2) {
      appendText(host, "p", `${local} 在${where}出現了兩次：`);
      const list = document.createElement("ul");
      readings.forEach((reading, index) => {
        appendText(list, "li",
          `${index === 0 ? "第一次（較早）" : "第二次（較晚）"}　${reading.utc_offset_label}（${readingKind(reading)}），`
          + `世界時 ${reading.utc_iso_8601}`);
      });
      host.appendChild(list);
      appendText(host, "p", "計算時，請在出生時間下方指明是哪一次。");
      rules = readings.map((reading) => reading.rule);
    } else if (body.status === "single" && readings.length === 1) {
      const reading = readings[0];
      appendText(host, "p",
        `${local} 在${where}是 ${reading.utc_offset_label}（${readingKind(reading)}），即世界時 ${reading.utc_iso_8601}。`);
      rules = [reading.rule];
    } else {
      throw new Error("換算助手的回應無法解讀。");
    }
    (body.warnings || []).forEach((warning) => appendText(host, "p", warning.message, "caveat"));
    const checkedVersion = body.source_table && body.source_table.tzdb_version_checked;
    const seen = new Set();
    rules.forEach((rule) => {
      const key = rule && rule.source ? rule.source.id : JSON.stringify(rule && rule.status);
      if (seen.has(key)) return;
      seen.add(key);
      renderRule(host, rule, checkedVersion);
    });
    const tz = body.tz_database || {};
    appendText(host, "p",
      `時區資料庫：${tz.version || "無法辨識版本"}（服務實際使用的版本）；出處表依 ${checkedVersion} 核對。`, "note");
    if (readings.some((reading) => reading.offset_status
      && reading.offset_status.historical_verification_status === "pre_1970_database_inferred_not_verified")) {
      appendText(host, "p", "1970 年以前的偏移多為時區資料庫的推定，未經歷史文獻核實。", "note");
    }
    host.hidden = false;
  }

  el("time-check-button").addEventListener("click", () => {
    clearTimeCheck();
    const request = timeCheckRequest();
    if (!request.body) {
      setTimeCheckStatus(request.problem, "error");
      return;
    }
    setTimeCheckStatus("核對中…", "info");
    const { controller, token, timeout } = timeCheckLifecycle.beginTimedRequest(
      TIME_CHECK_TIMEOUT_MS, window.setTimeout.bind(window)
    );
    const key = timeCheckKey(request);
    postJson("/api/time/convert", request.body, controller.signal)
      .then(({ response, body, invalidJsonMedia }) => {
        if (!timeCheckLifecycle.isCurrentRequest(token)) return;
        if (!response.ok) {
          setTimeCheckStatus(window.ClientContext.formatApiError(body && body.detail, response.status), "error");
          return;
        }
        if (invalidJsonMedia || !body || typeof body !== "object" || !body.timezone) {
          setTimeCheckStatus("換算助手的回應無法解讀；這不影響計算，請重試或直接計算。", "error");
          return;
        }
        if (timeCheckKey(timeCheckRequest()) !== key) {
          setTimeCheckStatus("出生日期、時刻或時區在核對途中改了；請重新核對。", "info");
          return;
        }
        try {
          renderTimeCheck(body, request.approximate);
        } catch (_) {
          el("time-check-result").replaceChildren();
          el("time-check-result").hidden = true;
          setTimeCheckStatus("換算助手的回應無法解讀；這不影響計算，請重試或直接計算。", "error");
          return;
        }
        timeCheckShownKey = key;
        setTimeCheckStatus("", "info");
      })
      .catch((error) => {
        if (!timeCheckLifecycle.isCurrentRequest(token)) return;
        const timedOut = timeout.didTimeout() && error && error.name === "AbortError";
        setTimeCheckStatus(
          timedOut ? "核對逾時；請重試，或直接計算。" : "核對沒有完成；請重試，或直接計算。",
          "error"
        );
      })
      .finally(() => {
        window.clearTimeout(timeout.handle);
        timeCheckLifecycle.finishRequest(token);
      });
  });

  // 範例載入是完整的狀態取代：先走與「清除敏感資料」相同的
  // 重設，把舊結果、地點收據、查詢結果、錯誤、選項與欄位旗標全部換掉，再
  // 寫入範例值，最後經同一條轉移重算相依狀態。從髒頁面載入與從新頁面載入
  // 必須得到同一個狀態。
  el("example-button").addEventListener("click", () => {
    resetFormState();
    form.querySelector('input[name="precision"][value="exact"]').checked = true;
    applyPrecisionConsequences();
    el("date").value = "1990-05-15";
    hourInput.value = "14";
    minuteInput.value = "30";
    el("latitude").value = "22.9908";
    el("longitude").value = "120.2133";
    el("altitude").value = "80";
    el("timezone").value = "Asia/Taipei";
    el("manual-place").open = true;
    noteFormChanged();
    setStatus("已載入合成範例。這不是任何真實人物的出生資料。", "info");
  });

  // ══ 送出 ══════════════════════════════════════════════
  /**
   * 讀一個欄位，把問題分流到 missing 或 invalid。回傳數值或 null。
   * 兩者給使用者的下一步不同：一個是「去填」，一個是「你填的那個值不對」。
   */
  // 欄位自己的錯誤訊息：聚焦時念的是這一欄錯在哪，不是整張表的總表。
  function missingMessage(label) { return `${label}：尚未填寫。`; }

  function collect(reader, input, label, required, problems) {
    const { missing, invalid, fields, messages } = problems;
    const read = reader(String(input.value));
    if (read.state === RI.STATES.EMPTY) {
      if (required) {
        missing.push(label);
        fields.push(input);
        messages.set(input, missingMessage(label));
      }
      return null;
    }
    // 主欄位的上下界只有一個出處：HTML 的 min/max。表單帶 novalidate，
    // 那些屬性不會自己守門，所以在這裡讀同一份值來守。
    const reason = read.state === RI.STATES.INVALID
      ? read.reason
      : RI.boundsProblem(htmlBounds(input), read.value);
    if (reason) {
      invalid.push(`${label}${reason}`);
      fields.push(input);
      messages.set(input, `${label}${reason}。`);
      return null;
    }
    return read.value;
  }

  function htmlBounds(input) {
    const min = input.min === "" ? undefined : Number(input.min);
    const max = input.max === "" ? undefined : Number(input.max);
    return {
      min: Number.isFinite(min) ? min : undefined,
      max: Number.isFinite(max) ? max : undefined,
    };
  }

  function documentOrder(a, b) {
    if (a === b) return 0;
    return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
  }

  /**
   * 回傳 { ok, missing, invalid, fields } 或 { ok, payload }。fields 是依畫面
   * 順序排好的問題欄位，供送出處標 aria-invalid 與移焦點；這個函式本身不動
   * DOM，所以結果綁定可以拿它來比對而沒有副作用。
   */
  function buildPayload() {
    const missing = [];
    const invalid = [];
    const fields = [];
    const messages = new Map();
    const problems = { missing, invalid, fields, messages };
    const requireField = (input, label) => {
      missing.push(label);
      fields.push(input);
      messages.set(input, missingMessage(label));
    };
    const dateRead = readDateField();
    if (dateRead.state === RI.STATES.EMPTY) requireField(el("date"), "出生日期");
    else if (dateRead.state === RI.STATES.INVALID) {
      invalid.push(`出生日期${dateRead.reason}`);
      fields.push(el("date"));
      messages.set(el("date"), `出生日期${dateRead.reason}。`);
    }
    const timezone = String(el("timezone").value).trim();
    // 新疆的地點在選定鐘點前時區欄是空的：指向那一組選項，不叫人去填時區欄。
    const civilTime = chosenCivilTime();
    if (civilTimeChoices(selectedPlace) && !civilTime) {
      invalid.push("請先選擇出生紀錄用的是北京時間還是新疆時間");
      const firstChoice = form.querySelector('#civil-time-choice input[name="civil_time_basis"]');
      if (firstChoice) {
        fields.push(firstChoice);
        messages.set(firstChoice, "請選擇北京時間或新疆時間。");
      }
    } else if (!timezone) requireField(el("timezone"), "時區（查詢地點或手動輸入）");
    // 服務只接受隨程式碼釘選的 IANA 名單（不含 localtime、Factory 與舊別名）；
    // 頁面讀同一份產生出來的名單，不讓使用者送出後才被拒。
    else if (!TimezoneNames.accepts(timezone)) {
      const reason = "時區名稱不在服務接受的 IANA 名單內（例如 Asia/Taipei，大小寫須相符）";
      invalid.push(reason);
      fields.push(el("timezone"));
      messages.set(el("timezone"), `${reason}。`);
    }

    const precision = currentPrecision();
    const hour = precision === "date_only"
      ? 0
      : collect(RI.readInteger, hourInput, "小時", true, problems);
    const minute = precision === "exact"
      ? collect(RI.readInteger, minuteInput, "分", true, problems)
      : 0;
    // 秒不填視為 0；非 exact 模式下後端要求必須為 0。
    const secondRead = precision === "exact"
      ? collect(RI.readSecond, secondInput, "秒", false, problems)
      : 0;

    const latitude = collect(RI.readDecimal, el("latitude"), "緯度", true, problems);
    const longitude = collect(RI.readDecimal, el("longitude"), "經度", true, problems);
    const altitude = collect(RI.readDecimal, el("altitude"), "海拔", true, problems);

    // 數字選項的上下界在這裡檢查，不倚賴 HTML min/max：表單帶 novalidate，
    // 原生驗證不會執行，所以那些屬性只是提示，不是守衛。
    invalid.push(...RI.numericOptionProblems(Catalogue, optionValues));

    // 模糊時刻沒選就 fail closed。與其猜一個再附帶告知，不如
    // 停下來問——猜錯的代價是整張盤的上升點，而使用者當場就能回答。
    const ambiguity = currentAmbiguity();
    if (ambiguity && foldChoice === null) {
      invalid.push("這個時間在所選時區出現了兩次，請先指明是哪一次");
      // 第一個選項代表整組：送出處把整組標無效，焦點也落在這裡。
      const firstFold = form.querySelector('#fold-choice input[name="fold"]');
      if (firstFold) {
        fields.push(firstFold);
        messages.set(firstFold, "請指明是第一次還是第二次。");
      }
    }

    if (missing.length || invalid.length) {
      return { ok: false, missing, invalid, fields: fields.slice().sort(documentOrder), messages };
    }

    const { year, month, day } = dateRead.value;
    return {
      ok: true,
      payload: {
        birth_time_precision: precision,
        datetime: {
          year, month, day, hour, minute,
          second: secondRead === null ? 0 : secondRead,
        },
        // fold 只在真的模糊時送出。平時省略，讓收據忠實反映「使用者沒有
        // 需要做這個選擇」，而不是「他選了第一次」。
        // 鐘點只在新疆的地點送出，收據因此只在使用者真的做了這個選擇時記下它。
        timezone: {
          mode: "iana",
          iana_name: timezone,
          ...(ambiguity ? { fold: foldChoice } : {}),
          ...(civilTime ? { civil_time_basis: civilTime.civil_time_basis } : {}),
        },
        location: LocationReceipt.buildLocationInput({
          latitude,
          longitude,
          altitudeM: altitude,
          selectedPlace,
        }),
        // 不送 atmosphere。折射用的溫度與氣壓預設值只在伺服器
        // （app.domain_catalog.DEFAULT_ATMOSPHERE_TEMPERATURE_C 與 AtmosphereInput），
        // 頁面不另寫一份；實際採用的值由回應的 astronomical_data.atmosphere 顯示。
        computation_mode: zodiacSelect.value === "sidereal"
          ? { zodiac: "sidereal", ayanamsa: ayanamsaSelect.value }
          : { zodiac: "tropical" },
        options: Catalogue.toRequestOptions(optionValues),
      },
    };
  }

  function setStatus(message, tone) {
    statusLine.textContent = message || "";
    statusLine.dataset.tone = tone || "info";
  }

  // 匯出的成功／失敗訊息全都寫進 #status-line，而那個元素
  // 在表單的 action 區；匯出工具列在結果區，「複製本區」更散布在其下二十多個區塊
  // 之中。使用者捲到結果深處按下按鈕時，訊息更新在視窗外——`aria-live` 對螢幕
  // 報讀有效，明眼使用者看到的是「按了沒反應」。
  //
  // 這裡在按下的那個按鈕旁補一則同文的短訊，全域那條保留不動：它承載 aria-live，
  // 移掉會把已經有效的無障礙回饋換成另一個問題。訊息內容只有固定字串與
  // error.message，不含使用者輸入。
  const INLINE_STATUS_TIMEOUT_MS = 6000;
  const inlineStatusTimers = new WeakMap();

  function reportAt(anchor, message, tone) {
    setStatus(message, tone);
    if (!anchor || !anchor.parentNode) return;
    let note = anchor.nextElementSibling;
    if (!note || !note.classList.contains("inline-status")) {
      note = document.createElement("span");
      note.className = "inline-status";
      anchor.insertAdjacentElement("afterend", note);
    }
    note.textContent = message;
    note.dataset.tone = tone || "info";
    window.clearTimeout(inlineStatusTimers.get(note));
    inlineStatusTimers.set(
      note,
      window.setTimeout(() => {
        note.textContent = "";
      }, INLINE_STATUS_TIMEOUT_MS)
    );
  }

  // 指向頁面上某個控制項的動作做成連結，按下就到那裡；其餘是一般文字。
  const FOLD_ACTION = Object.freeze({
    text: "到「這個時間出現了兩次」的選擇區指定是第一次還是第二次。",
    href: "#fold-choice",
  });
  const CIVIL_TIME_ACTION = Object.freeze({
    text: "到「出生紀錄用的是北京時間還是新疆時間？」選擇其中一種。",
    href: "#civil-time-choice",
  });

  function showError(message, actions) {
    errorMessage.textContent = message;
    errorActions.replaceChildren();
    (actions || []).forEach((action) => {
      const item = document.createElement("li");
      if (action && typeof action === "object") {
        const link = document.createElement("a");
        link.href = action.href;
        link.textContent = action.text;
        item.appendChild(link);
      } else {
        item.textContent = action;
      }
      errorActions.appendChild(item);
    });
    errorPanel.hidden = false;
    // 送出鈕在飛行中是 disabled，焦點會掉到 body；錯誤出現時把焦點交給
    // 錯誤標題（HTML 帶 tabindex="-1"），讓鍵盤與螢幕報讀使用者停在錯誤上。
    // 表單驗證失敗時，送出處隨後會再把焦點移到第一個問題欄位。
    el("error-title").focus();
  }

  // aria-describedby 同時承載欄位說明（靜態 HTML 或選項 UI 寫入）與錯誤訊息；
  // 錯誤只加減自己那個 token，不得覆蓋說明的關聯。錯誤排在前面，
  // 報讀時先聽到出了什麼錯。
  function describedByTokens(input) {
    return (input.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
  }

  function setDescribedBy(input, tokens) {
    if (tokens.length) input.setAttribute("aria-describedby", tokens.join(" "));
    else input.removeAttribute("aria-describedby");
  }

  // 單選鈕的對錯屬於整組：標記與撤下都作用在同名的每一顆上。
  function fieldGroup(input) {
    return input.type === "radio" && input.name
      ? [...form.querySelectorAll(`input[type="radio"][name="${input.name}"]`)]
      : [input];
  }

  // 描述裡屬於錯誤的 token：整張表的 #error-message，或欄位自己的 <id>-error。
  const isErrorToken = (token) => token === "error-message" || token.endsWith("-error");
  const fieldErrorId = (input) => `${input.id || input.name}-error`;

  /** 欄位自己的錯誤訊息，緊跟在欄位（單選鈕則是整組選項）後面，畫面上看得到。 */
  function showFieldError(input, message) {
    const id = fieldErrorId(input);
    let node = document.getElementById(id);
    if (!node) {
      node = document.createElement("span");
      node.id = id;
      node.className = "field-error";
      const anchor = input.type === "radio" ? input.closest(".choice") || input : input;
      anchor.insertAdjacentElement("afterend", node);
    }
    node.textContent = message;
    return id;
  }

  /**
   * messages 是本頁自己擋下時每一欄的訊息；伺服器點名的欄位沒有逐欄訊息，
   * 連到錯誤面板裡伺服器那一句。
   */
  function markInvalidFields(fields, messages) {
    fields.forEach((leader) => {
      const message = messages && messages.get(leader);
      const token = message ? showFieldError(leader, message) : "error-message";
      fieldGroup(leader).forEach((input) => {
        input.setAttribute("aria-invalid", "true");
        setDescribedBy(input, [token, ...describedByTokens(input).filter((t) => !isErrorToken(t))]);
      });
    });
    const first = fields[0];
    if (!first) return;
    // 手動座標區收在 <details> 裡；一個看不見的無效欄位無法被修正。每一個含
    // 無效欄位的 <details> 都要展開，不只第一個欄位所在的那個——否則焦點落在
    // 小時，緯度的錯誤仍藏在收合的區塊裡。
    fields.forEach((input) => {
      const details = input.closest("details");
      if (details) details.open = true;
    });
    first.focus();
  }

  function clearFieldInvalid(input) {
    fieldGroup(input).forEach((node) => {
      node.removeAttribute("aria-invalid");
      setDescribedBy(node, describedByTokens(node).filter((t) => !isErrorToken(t)));
      const message = document.getElementById(fieldErrorId(node));
      if (message) message.remove();
    });
  }

  function clearAllFieldInvalid() {
    form.querySelectorAll("[aria-invalid]").forEach(clearFieldInvalid);
    form.querySelectorAll(".field-error").forEach((node) => node.remove());
  }

  function hideError() {
    errorPanel.hidden = true;
    errorMessage.textContent = "";
    errorActions.replaceChildren();
  }

  // 每一次送出都拿一個不可重用的世代號。中止與清除讓世代
  // 前進；任何還握著舊世代的續行——遲到的回應、finally——都只能放棄，不得碰
  // 送出鈕與中止鈕。地點查詢的 lifecycle token 就是同一個模式。狀態是閉集：
  // 閒置／飛行中。
  const ATTEMPT = Object.freeze({ IDLE: "idle", IN_FLIGHT: "in_flight" });
  let attemptState = ATTEMPT.IDLE;
  let attemptGeneration = 0;

  function beginAttempt() {
    attemptGeneration += 1;
    attemptState = ATTEMPT.IN_FLIGHT;
    return attemptGeneration;
  }
  function isCurrentAttempt(generation) {
    return generation === attemptGeneration && attemptState !== ATTEMPT.IDLE;
  }
  function endAttempt(generation) {
    if (generation !== attemptGeneration) return false;
    attemptState = ATTEMPT.IDLE;
    return true;
  }
  function invalidateAttempt() {
    attemptGeneration += 1;
    attemptState = ATTEMPT.IDLE;
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (attemptState !== ATTEMPT.IDLE) return;
    // 「加算」送出的這一次，結果到了把焦點交給新加的那一區；其他任何一次送出都不帶。
    const addedFocus = addRequested;
    addRequested = null;
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
      if (currentPrecision() === "exact") {
        actions.push("若只知道大約時辰或只知道日期，改選對應的把握程度。");
      }
      // 上一次的結果必須先消失，這條「連送都沒送出去」的分支也一樣：留著舊
      // 卷宗等於在錯誤訊息底下展示一份描述舊輸入的結果，而且它的複製／下載
      // 鈕仍然可用，可以匯出一份與表單不符的卷宗。
      // 先清再報，順序不可調換：dropResultsForNewAttempt() 會 hideError()。
      dropResultsForNewAttempt();
      showError(parts.join(" "), actions);
      markInvalidFields(built.fields, built.messages);
      setStatus("尚未送出。", "error");
      return;
    }
    const generation = beginAttempt();
    resultFocusOptions = addedFocus;
    // 結果綁定送出當下的輸入快照：回來的結果只對這一份
    // payload 成立，表單之後任何改動都會讓它被標為 stale。
    const signature = inputSignature(built.payload);
    submitButton.disabled = true;
    // 狀態與中止入口在守衛通過的當下就出現，不等任何網路往返：兩者都不得
    // 落在任何網路往返之後，否則送出鈕已 disabled 而畫面上沒有訊息、也沒有
    // 可按的中止。
    setStatus("計算中…", "info");
    cancelButton.hidden = false;
    // 送出鈕剛被 disabled，焦點會掉到 body；移到中止鈕。
    cancelButton.focus();
    submitPayload(built.payload, generation, signature);
  });

  /**
   * 每一次送出都有上限，且中止入口在送出當下即可達；逾時只清掉這一次的
   * 請求狀態，不清掉使用者已經輸入的出生資料。
   *
   * 30 秒：目前最重的組合（全恆星＋成相推算）在本機是數百毫秒等級，30 秒
   * 已遠超正常範圍；再長只是延長使用者對著沒有反應的畫面枯等。
   */
  const REQUEST_TIMEOUT_MS = 30000;

  // 往返本身在 privacy-lifecycle.js（時間主星一區共用）；網址照字寫在每一個呼叫點，
  // 自我檢查頁依那些字面列出本頁會送的請求。
  function postJson(url, payload, signal) {
    return window.PrivacyLifecycle.postJson(window, url, payload, signal);
  }

  // 連不上本站（請求沒送到，或呈現結果的模組沒抓到）：同一句說明、同一行狀態。
  function showServiceUnreachable() {
    showError(window.ClientContext.networkErrorMessage(), ["確認服務仍在執行後重試。", "重新載入頁面。"]);
    setStatus("沒有送達計算服務。", "error");
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
    const finishAttempt = () => {
      window.clearTimeout(timeout.handle);
      cancelButton.hidden = true;
    };

    submitButton.disabled = true;
    cancelButton.hidden = false;
    setStatus("計算中…", "info");

    Promise.race([
      Promise.all([
        postJson("/api/chart", payload, controller.signal),
        loadViewModel().then(() => true, () => false),
      ]),
      deadline,
    ])
      .then(([{ response, body, invalidJsonMedia }, viewModelReady]) => {
        if (!lifecycle.isCurrentRequest(token)) return;   // late response 丟棄
        if (invalidJsonMedia) {
          showError("計算服務的回應格式不是 JSON。", ["請稍後重試。"]);
          setStatus("服務回應格式錯誤。", "error");
          return;
        }
        if (!response.ok) { handleApiError(response, body, payload); return; }
        // 結構檢查要響亮：一個 2xx 但不是物件的 body 不得
        // 走進渲染器變成一頁破折號。更深的必要結構檢查由 view-model／
        // exporters 的 createDocument 負責，失敗同樣落到下面的完整性錯誤。
        if (!body || typeof body !== "object" || Array.isArray(body)) {
          showIncompleteResponse();
          return;
        }
        // 呈現結果的模組沒抓到，與計算請求沒送到是同一種失敗：連不上本站。
        if (!viewModelReady) {
          showServiceUnreachable();
          return;
        }
        renderResponse(body, signature, payload);
      })
      .catch((error) => {
        if (!lifecycle.isCurrentRequest(token)) return;
        if (error && error.name === "AbortError") {
          // 逾時與使用者主動中止都走 AbortError，但兩者要說不同的話：
          // 一個是「服務沒回應」，一個是「你叫停了」。混為一談會讓逾時
          // 看起來像使用者自己按到的。
          if (timeout.didTimeout()) {
            showError(
              `等待計算結果超過 ${REQUEST_TIMEOUT_MS / 1000} 秒，已停止等待並捨棄這次結果。`,
              ["表單內容仍在，可以直接再送出一次。",
               "若持續逾時，改用較少的選項組合，或稍後重試。"]
            );
            setStatus("計算逾時，已停止等待。", "error");
          } else {
            setStatus(CANCELLED_MESSAGE, "info");
          }
          return;
        }
        showServiceUnreachable();
      })
      .finally(() => {
        // 只有仍是當前世代的嘗試可以碰送出鈕與中止鈕；被中止或被取代的
        // 嘗試連 finishAttempt 都不做，否則會把下一次嘗試的中止鈕收掉。
        if (!isCurrentAttempt(generation)) {
          window.clearTimeout(timeout.handle);
          return;
        }
        finishAttempt();
        endAttempt(generation);
        if (lifecycle.isCurrentRequest(token)) lifecycle.finishRequest(token);
        submitButton.disabled = false;
      });
  }

  // 中止鈕能做的只有「停止等待並捨棄這次結果」：瀏覽器端不再等、不再顯示。
  // 伺服器若已開始計算，這裡不能打斷它（security 頁已說明），它只會算完
  // 後不留副本。文案不得說「已中止計算」。
  const CANCELLED_MESSAGE =
    "已停止等待，這次的結果不會顯示也不會保存。伺服器若已開始計算，會算完但不留副本。表單內容保留。";

  /**
   * 只讀 `detail`，且只交給 ClientContext 的封閉對照表。
   * 伺服器的拒絕只帶閉集代碼、固定訊息與宣告過的欄位位置（schemas.validation_issues
   * 丟掉 Pydantic 的 input／msg／ctx；
   * tests/backend/test_api_properties.py 逐類觀測），不回帶出生日期、時刻或座標。
   * 這裡仍不把回應裡的任何文字直接放進畫面（契約 §9）。
   */
  function handleApiError(response, body, payload) {
    const statusCode = response.status;
    const { detail, code } = refusalOf(body);
    const message = window.ClientContext.formatApiError(detail, statusCode);
    // 星曆拒絕重送不會改變結果，動作清單依代碼不建議重試。
    const actions = window.ClientContext.apiErrorActions(
      statusCode, response.headers.get("Retry-After"), code
    );
    // 出路由頁面自己的狀態導出，不由一句寫死的文案宣稱。服務說這個時刻或大約
    // 時辰需要指明是哪一次，而本頁沒有顯示選擇區時（本頁的判定與服務不同），
    // 照服務的判定把選擇區打開，再指向它——不叫使用者去改一個在這個模式下
    // 看不到的分鐘欄位，也不猜落差的原因。date_only 由服務自己取樣整天，不會收到這個拒絕。
    if (code === "ambiguous_local_time_choice_required") {
      if (el("fold-choice").hidden && payload
          && payload.birth_time_precision !== "date_only"
          && payload.timezone && payload.timezone.mode === "iana") {
        serviceRepeatedTime = timeKeyOfPayload(payload);
        refreshFoldChoice();
      }
      if (!el("fold-choice").hidden) actions.unshift(FOLD_ACTION);
    }
    // 服務說這個地點要指明鐘點：選擇區在就指向它；不在表示頁面不知道這個地點有兩種鐘點
    // （頁面版本較舊），重新查詢地點才會帶出選項。
    if (code === "civil_time_basis_required") {
      actions.unshift(el("civil-time-choice").hidden
        ? "請重新載入頁面，再用「地名查詢」選定地點。"
        : CIVIL_TIME_ACTION);
    }
    showError(message, actions);
    setStatus("服務拒絕了這次計算。", "error");
    // 伺服器點名的欄位標 aria-invalid、展開所在摺疊區並移焦點。
    // 對照表在 ClientContext；選項若由另一個控制項代為呈現（rendered_by），標在看得見的那個上。
    const invalid = window.ClientContext.fieldControlIds(detail)
      .map((id) => {
        const key = id.startsWith("opt-") ? id.slice(4) : null;
        const option = key && Object.hasOwn(Catalogue.BY_KEY, key)
          ? Catalogue.BY_KEY[key] : null;
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

  /** 拒絕回應的 detail，以及 detail 是物件時其中的代碼。 */
  function refusalOf(body) {
    const detail = body && typeof body === "object" ? body.detail : null;
    const code = detail && typeof detail === "object" && !Array.isArray(detail) ? detail.code : null;
    return { detail, code };
  }

  // ══ 渲染 ══════════════════════════════════════════════
  // 2xx 但不是物件、或狀態權威缺席／殘缺的回應：同一句話，不渲染任何結果。
  const INCOMPLETE_RESPONSE_MESSAGE = "計算服務的回應結構不完整，無法確認這是一份完整的結果。";
  const INCOMPLETE_RESPONSE_ACTIONS = Object.freeze(["請重試。", "若持續發生，請聯絡服務管理者。"]);
  function isIncompleteResponse(error) {
    return Boolean(error) && error.code === window.ChartExport.INCOMPLETE_RESPONSE;
  }
  function showIncompleteResponse() {
    showError(INCOMPLETE_RESPONSE_MESSAGE, INCOMPLETE_RESPONSE_ACTIONS);
    setStatus("回應完整性檢查未通過。", "error");
  }

  /** 每一章放區塊的容器清空（章的標題、說明與靜態內容不動）。 */
  function clearChapterHosts() {
    chapterHosts.forEach((host) => host.replaceChildren());
  }

  // 位置表在快速看盤先只顯示四欄（天體、星座度數、宮、行進），其餘一鍵展開；匯出照舊全欄。
  // 「宮」一欄照行星落宮表的原字（與一頁摘要的位置表同一個來源：ChartViewModel.printBriefRows）。
  // positionsFull 是這一頁的變數：null＝照模式的預設；換模式時回到 null。
  let positionHouses = new Map();
  let positionsFull = null;
  const POSITION_COLUMNS = Object.freeze(["星座度數", "行進"]);

  function housesByName(tree) {
    const brief = window.ChartViewModel.printBriefRows(tree);
    return new Map(brief ? brief.rows.map((row) => [row[0], row[2]]) : []);
  }

  function positionsShowFull() {
    return positionsFull === null ? !(resultMode && resultMode.compactPositions) : positionsFull;
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
      house.textContent = rowIndex === 0 ? "宮" : (positionHouses.get(model.rows[rowIndex - 1][0]) || DASH_TEXT);
      tr.insertBefore(house, tr.cells[motion]);
    });
    const bar = make("div", "table-columns");
    const button = make("button", "ghost small positions-columns");
    button.type = "button";
    button.setAttribute("aria-controls", table.id);
    bar.appendChild(button);
    paintPositionTable(table, button, model.columns.length);
    button.addEventListener("click", () => {
      positionsFull = !positionsShowFull();
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

  /** 時間主星：與按「排出時間主星」同一個請求（古典完整算完星盤後自動接著排）。 */
  function loadAnnualPanel() {
    const panel = annualPanel();
    if (panel && typeof panel.load === "function") panel.load();
  }

  // 注意事項：寬螢幕整張清單常駐（摘要那一行由 calculate.css 藏起）。窄螢幕只在每一則都只是提醒時才先收成
  // 一行——則數與第一則的開頭，點開看全文；只要有一則可能影響時間、時區或方法，就和寬螢幕一樣整張打開。
  // 「只是提醒」是下面這張閉集：後端一律標 notice、只說哪些結果對出生時刻敏感或哪個模組這次不適用的代碼。
  // 預設的 page 回應不帶嚴重度，所以靠代碼（契約：比對 code，不比對 message）；不在表上的代碼（含新代碼）一律不收。
  // 清單本身（#warnings）與匯出讀的是同一份，開合只是畫面。
  const INFORMATIONAL_NOTICES = new Set([
    "body_near_house_cusp", "body_near_sign_boundary", "moon_near_lunar_mansion_boundary",
    "module_not_applicable", "module_not_applicable_in_mode",
  ]);
  const informational = (warning) => INFORMATIONAL_NOTICES.has(warning.code);
  function renderWarnings(warnings) {
    warningsHost.replaceChildren();
    warningsHost.hidden = warnings.length === 0;
    warningsFold.hidden = warningsHost.hidden;
    warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning.message;
      warningsHost.appendChild(item);
    });
    el("warnings-summary").textContent = warnings.length
      ? `注意事項 ${warnings.length} 則：${warnings[0].message}` : "";
    warningsFold.dataset.fold = warnings.every(informational) ? "notices" : "attention";
    warningsFold.open = !narrowScreen() || warningsFold.dataset.fold === "attention";
  }
  // 轉成寬螢幕（轉向、拉寬視窗）時摘要那一行不見了，清單必須是打開的；轉回窄螢幕不替使用者收起。
  if (typeof window.matchMedia === "function") {
    const narrowQuery = window.matchMedia(NARROW_QUERY);
    if (typeof narrowQuery.addEventListener === "function") {
      narrowQuery.addEventListener("change", (event) => { if (!event.matches) warningsFold.open = true; });
    }
  }

  /** 「技術細節與驗算資料」一區。頁面文件本身不含技術區段；這一區照樣建出，打開時才取得完整回應。 */
  function technicalDetailsBlock(technicalSections) {
    const details = make("details", "technical-results");
    details.id = "technical-results";
    const summary = document.createElement("summary");
    summary.textContent = "技術細節與驗算資料";
    const note = make("p", "note");
    note.textContent = "版本、來源、選項、計算軌跡與完整收據。一般閱讀不需要展開。";
    details.append(summary, note);
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
      summary.addEventListener("click", () => {
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
        ["重新載入頁面以取得對應版本。", "若重新載入後仍失敗，請聯絡服務管理者。"]);
      setStatus("回應無法呈現。", "error");
      return;
    }

    lifecycle.setCanonicalDocument(canonical);
    sectionSnapshots.clear();
    canonical.sections.forEach((section) => sectionSnapshots.set(section.id, section));

    const tree = window.ChartViewModel.buildViewTree(canonical);
    currentViewTree = tree;

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
    resultMode = Chapters.mode(currentModeId);
    if (lastRenderedMode !== resultMode.id) {
      el("first-time").open = Chapters.firstTimeOpen(resultMode.id, narrowScreen());
      lastRenderedMode = resultMode.id;
    }
    el("result-mode-name").textContent = resultMode.label;
    positionHouses = housesByName(tree);
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
      if (!resultMode.chapters.includes(chapter)) hiddenTitles.push(section.title);
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
    technicalHost = details;
    chapterHosts.get("receipt").appendChild(details);
    addEntry("receipt", { node: details, title: details.querySelector("summary").textContent, status: null });
    addEntry("receipt", { node: el("export-toolbar"), title: el("export-mode-title").textContent, status: null });

    // 這次沒有算、勾一個選項就能加算的區塊：古典完整與自訂列在各章最後；快速看盤只顯示四章，不列。
    if (resultMode.id !== "quick") {
      const absent = tree.sections.filter((section) => section.status.state === "not_requested"
        && !technicalIds.has(section.id) && section.id !== SUMMARY_SECTION_ID);
      resultMode.chapters.forEach((chapter) => {
        const block = absentBlock(chapter, absent.filter((section) => chapterFor.get(section.id) === chapter));
        if (block && chapterHosts.has(chapter)) chapterHosts.get(chapter).appendChild(block);
      });
    }
    buildChapterNav(entries);
    renderModeNote(hiddenTitles);
    el("chapter-timelords-entry").hidden = resultMode.chapters.includes("timelords");

    showAnnualPanel(payload);
    results.hidden = false;
    // 結果區打開之後分頁列才量得到寬度。
    paintChapterFade();
    boundInputSignature = signature;
    refreshResultBinding();
    applyOverflowRegions();
    setStatus("計算完成。", "info");
    // 古典完整：算完星盤接著排時間主星（表單上那一格勾著時）；與按「排出時間主星」是同一個請求。
    if (resultMode.timelordsAfterChart && el("plan-timelords").checked) loadAnnualPanel();
    // 回應已到，中止鈕已無事可做：先收起再捲動。手機上它在送出鈕下自成一列，等 finally 才收起，
    // 結果標題會在捲動途中往上移，停在視窗頂端之外。finally 照舊再收一次。
    cancelButton.hidden = true;
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
    const behavior = prefersReducedMotion() ? "auto" : "smooth";
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
      if (typeof added.scrollIntoView === "function") {
        added.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
      }
      focusSectionHeading(added);
      return;
    }
    const heading = el("results-heading");
    if (typeof heading.scrollIntoView === "function") {
      heading.scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    }
    heading.focus({ preventScroll: true });
  }

  // 時間收據的一行重點：取「時間轉換」表格的本地時間（或代表性錨點）、時區與世界時三列，
  // 名稱與數值都照表格原字，不另外格式化。表格不是預期的形狀時不畫這一行，完整收據照舊在最後。
  function renderTimeBrief(section) {
    timeBrief.replaceChildren();
    timeBrief.hidden = true;
    const table = section && section.children.find((child) => child.type === "table");
    const rows = table ? table.rows : [];
    const zone = rows.findIndex((row) => row[0] === "時區");
    const offset = rows.findIndex((row) => row[0] === "UTC 偏移");
    if (zone !== 1 || offset !== 2 || rows.length < 4) return;
    [rows[0], rows[zone], rows[offset + 1]].forEach(([term, value], index) => {
      if (index) timeBrief.append(figureText("span", "visually-hidden", "；"));
      const item = figureText("span", "time-brief-item", "");
      item.append(figureText("span", "time-brief-term", term), " ", String(value));
      timeBrief.append(item);
    });
    const link = document.createElement("a");
    link.href = "#time-receipt";
    link.className = "time-brief-link";
    link.textContent = "完整時間收據";
    timeBrief.append(figureText("span", "visually-hidden", "；"), link);
    timeBrief.hidden = false;
  }

  // 完整的時間轉換區收進預設收合的 <details>，排在各區之後、技術細節之前。
  function timeReceipt(sectionNode) {
    const details = make("details", "time-receipt");
    details.id = "time-receipt";
    const summary = document.createElement("summary");
    summary.textContent = "展開完整時間收據";
    details.append(summary, sectionNode);
    return details;
  }

  // 連到收合區塊裡的錨點（時間收據的一行重點、章節欄的區塊）或跳到表格裡的一列時，先換到它
  // 所在的那一章、打開它與它外層的每一個 <details>，再捲過去：沒顯示的章與收合中的元素都沒有版面
  // 位置，捲動與焦點都會落空。
  function unfoldTarget(target) {
    const chapter = chapterOf(target);
    if (chapter && !chapterVisible(chapter)) showChapter(chapter);
    for (let node = target; node; node = node.parentElement) {
      if (node.tagName === "DETAILS" && !node.open) node.open = true;
    }
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
    target.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "start" });
    focusSectionHeading(target);
  });

  // ── 星盤圖 ──────────────────────────────────────────
  //
  // 圖由 canonical document 的 source_response 畫出（與表格同一份回應），放在結果首屏
  // （#chart-wheel-host，桌機在速覽左側）。清除、重新計算與 pagehide 時與 #sections 一起清空
  // （dropResultsForNewAttempt），放大的對話框也在區塊內。圖畫不出來時只留一句說明，表格照常。
  const WHEEL_FILES = Object.freeze({ svg: "classical-astrology-chart.svg", png: "classical-astrology-chart.png" });

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
    lifecycle.registerSectionNode(section);
    chartWheelHost.replaceChildren(section);
    // 圓盤或方盤：上一份結果選了方盤，這一份照樣先畫方盤（這一頁的變數，不寫儲存）。
    // 這份結果畫不出方盤（沒有宮位）時照舊是圓盤，選擇本身留著。
    if (chartStyle === "square") {
      const square = chartWheelHost.querySelector('input[name="chart-wheel-style"][value="square"]');
      if (square && !square.checked) {
        square.checked = true;
        square.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  }

  // 使用者在圖的工具列上換圓盤／方盤時記下來，重新計算後沿用；按「清除本頁敏感資料」時回到圓盤。
  let chartStyle = "wheel";
  function rememberChartStyle(event) {
    const input = event.target;
    if (input && input.name === "chart-wheel-style" && input.checked) {
      chartStyle = input.value === "square" ? "square" : "wheel";
    }
  }
  chartWheelHost.addEventListener("change", rememberChartStyle);

  // ── 圖表連動 ──────────────────────────────────────────
  //
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

  /** 一個鍵：凡是含它的元素（逐度相位的組合列也算）；一對鍵：只有這兩點本身與兩點之間的組合。 */
  function linkedTo(node, keys) {
    const own = pointKeys(node.getAttribute("data-points"));
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
    row.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
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
    if (format === "svg") {
      const svg = window.ChartWheel.renderSvg(document, model, { variant: "download" });
      lifecycle.deliverDownload(document, new Blob([window.ChartWheel.serializeSvg(svg)], { type: "image/svg+xml" }), files.svg);
      reportAt(button, "已產生 SVG 檔案。", "info");
      return;
    }
    // PNG：同一份場景以 Canvas 2D 直接畫，不經 SVG→<img>（CSP 的 img-src 不允許 blob:）。
    const canvas = document.createElement("canvas");
    canvas.width = model.width * window.ChartWheel.PNG_SCALE;
    canvas.height = model.height * window.ChartWheel.PNG_SCALE;
    const context = canvas.getContext("2d");
    if (!context || typeof canvas.toBlob !== "function") {
      reportAt(button, "下載失敗：這個瀏覽器無法產生 PNG。", "error");
      return;
    }
    window.ChartWheel.drawCanvas(context, model);
    canvas.toBlob((blob) => {
      // toBlob 是非同步的：期間若已清除或換了結果，就不交出這張圖。
      let current = null;
      try { current = lifecycle.requireCanonicalDocument(); } catch (_error) { current = null; }
      if (current !== canonical) return;
      if (!blob) {
        reportAt(button, "下載失敗：無法產生 PNG。", "error");
        return;
      }
      lifecycle.deliverDownload(document, blob, files.png);
      reportAt(button, "已產生 PNG 檔案。", "info");
    }, "image/png");
  }

  // ── 結果與表單的綁定──────────────────────
  //
  // 畫面上的結果只對它送出當下的輸入成立。表單任何一處改動後，結果標為
  // stale、複製與下載停用；改回原值則綁定又成立。飛行中改動也一樣：回來的
  // 結果在渲染那一刻就會被比對。
  let boundInputSignature = null;   // null = 畫面上沒有結果
  let currentViewTree = null;       // 畫面上那棵 view tree；清除結果時一併放掉
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
    if (boundInputSignature === null) { setStale(false); return; }
    const built = buildPayload();
    const current = built.ok ? inputSignature(built.payload) : null;
    setStale(current !== boundInputSignature);
  }

  function setStale(stale) {
    // 「過期」的說法與複製／下載是否可用只有 view-model
    // 一個出處，這裡是 ChartViewModel.markStale 唯一的呼叫點。畫面上沒有樹（剛清除、尚未
    // 計算）時沒有東西可標，按鈕照 stale 旗標處理。
    const tree = stale && currentViewTree
      ? window.ChartViewModel.markStale(currentViewTree)
      : currentViewTree;
    const actions = tree
      ? tree.header.actions
      : { copy_enabled: !stale, download_enabled: !stale };
    if (stale) results.dataset.stale = "true";
    else delete results.dataset.stale;
    staleAnnualPanel(stale);
    staleNotice.hidden = !stale;
    if (stale && tree && tree.header.stale_notice) staleNotice.textContent = tree.header.stale_notice;
    lastExportActions = actions;
    applyExportAvailability();
  }

  /**
   * 複製、下載、列印與放大是否可按，只有這一處決定：畫面上沒有結果（剛載入、清除後）時
   * 全部停用——藏起來或移出 DOM 的按鈕仍可能被程式或舊的參照按到；結果過期時依
   * view-model 的 actions；選了「運算結果＋驗算資料」而驗算資料還沒到手時，複製與下載
   * 也先停用（列印照舊，它印的是畫面）。
   */
  function applyExportAvailability() {
    const present = boundInputSignature !== null;
    const actions = present ? lastExportActions : { copy_enabled: false, download_enabled: false };
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

  // ══ 驗算資料 ══════════════════════════════════════════
  //
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
    resultGeneration += 1;
    pageCanonical = canonical;
    boundPayload = payload;
    technicalHost = null;
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
    resultGeneration += 1;
    pageCanonical = null;
    boundPayload = null;
    technicalHost = null;
    Object.assign(verification, { state: DETAIL.IDLE, canonical: null, message: "", actions: [] });
    refreshDetailUi();
  }

  function failDetail(message, actions) {
    Object.assign(verification, { state: DETAIL.FAILED, canonical: null, message, actions });
    refreshDetailUi();
  }

  function loadVerificationDetail() {
    if (!boundPayload || !pageCanonical) return;
    if (verification.state === DETAIL.LOADING || verification.state === DETAIL.READY) return;
    const generation = resultGeneration;
    const payload = boundPayload;
    const { controller, token, timeout } = lifecycle.beginTimedRequest(
      REQUEST_TIMEOUT_MS, window.setTimeout.bind(window)
    );
    Object.assign(verification, { state: DETAIL.LOADING, canonical: null, message: "", actions: [] });
    refreshDetailUi();
    const current = () => generation === resultGeneration && lifecycle.isCurrentRequest(token);
    // 同一份結果還在、但這次請求被別的動作中止（例如送出前那段等待裡按了中止）：
    // 回到「尚未取得」，使用者可以再打開一次。結果已換掉就什麼都不做。
    const abandoned = () => {
      if (generation === resultGeneration && verification.state === DETAIL.LOADING) {
        Object.assign(verification, { state: DETAIL.IDLE, canonical: null, message: "", actions: [] });
        refreshDetailUi();
      }
    };

    postJson("/api/chart?projection=detailed", payload, controller.signal)
      .then(({ response, body, invalidJsonMedia }) => {
        if (!current()) { abandoned(); return; }
        if (invalidJsonMedia) {
          failDetail("計算服務的回應格式不是 JSON。", ["請稍後再試一次。"]);
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
            failDetail("這個版本的頁面無法安全呈現驗算資料。", ["重新載入頁面後再試。"]);
          }
          return;
        }
        if (!window.ChartExport.bindsToPageDocument(pageCanonical, canonical)) {
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
        failDetail(window.ClientContext.networkErrorMessage(), ["確認連線後再試一次。"]);
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
    if (technicalHost && technicalHost.isConnected) {
      technicalHost.querySelectorAll(".detail-status").forEach((node) => node.remove());
      technicalHost.dataset.detail = "ready";
      const tree = window.ChartViewModel.buildViewTree(canonical);
      tree.sections
        .filter((section) => TECHNICAL_SECTION_IDS.has(section.id))
        .forEach((section) => technicalHost.appendChild(materializeSection(section)));
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

  // ── 可捲動表格的 region────────────────────
  //
  // 只有真的橫向溢出的表格才是 region 與 tab 停留點；未溢出時多一個
  // 停留點只是噪音。標籤帶區塊標題，報讀時才分得出是哪一區的表。
  function applyOverflowRegions() {
    // 先量完全部再寫：邊量邊寫時，每寫一次屬性，下一次量就得重排一次版面。
    const wraps = [...results.querySelectorAll(".table-wrap")];
    const overflowing = wraps.map((wrap) => wrap.scrollWidth > wrap.clientWidth);
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
    window.requestAnimationFrame(applyOverflowRegions);
  });

  // ── 結果的章 ─────────────────────────────────────────
  //
  // 結果分成六章，一次看一章。哪一區在哪一章、每種模式顯示哪幾章，只在 result-chapters.js 的表；
  // 這裡只把畫出來的區塊放進它那一章、建章節欄、切換顯示。寬螢幕是左側黏性的章節欄，每章底下
  // 列出這一章畫出來的區塊；窄螢幕是頂端一列橫捲的分頁（calculate.css）。章只在畫面上分組：
  // 複製與下載讀 canonical 快照，列印時每一章都印（calculate.css 的 print 規則），所以匯出與列印
  // 都不受分章影響。目前在哪一章只是這一頁的變數：不寫網址、不寫儲存；重新計算後留在同一章
  // （那一章在新的模式裡不顯示時回到總覽），按「清除」才回到總覽。分頁會擋住瀏覽器的頁內搜尋，
  // 所以有「全部章節一次展開」。
  const prefersReducedMotion = () => typeof window.matchMedia === "function"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const chapterNodes = new Map(
    [...results.querySelectorAll("section.chapter[data-chapter]")].map((node) => [node.dataset.chapter, node])
  );
  const chapterNav = { current: "overview", all: false, shown: new Set(), links: new Map() };
  // 這一份結果是用哪一種模式算的（章節欄、位置表的預設欄數、算完要不要接著排時間主星都看它）。
  let resultMode = null;

  function chapterOf(node) {
    const chapter = node && node.closest ? node.closest("section.chapter[data-chapter]") : null;
    return chapter ? chapter.dataset.chapter : null;
  }

  function chapterVisible(id) {
    return chapterNav.shown.has(id) && (chapterNav.all || chapterNav.current === id);
  }

  function paintChapters() {
    chapterNodes.forEach((node, id) => { node.hidden = !chapterVisible(id); });
    chapterNav.links.forEach((link, id) => {
      if (!chapterNav.all && id === chapterNav.current) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    el("chapters-all").setAttribute("aria-pressed", String(chapterNav.all));
  }

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
    el("chapter-index").replaceChildren();
    delete el("chapter-index").dataset.more;
    chapterNav.links.clear();
    chapterNav.shown = new Set();
    el("chapter-nav").hidden = true;
    el("chapter-mode-note").replaceChildren();
    el("chapter-mode-note").hidden = true;
    // 沒有結果時每一章都收起；總覽不另收，它在 #results 裡跟著整區隱藏。
    chapterNodes.forEach((node, id) => { node.hidden = id !== "overview"; });
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
      const separator = make("span", "visually-hidden");
      separator.textContent = "：";
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
   * entries：章 id → 這一章畫出來的區塊 [{ node, title, status }]，照畫面順序。在區塊都放進畫面之後呼叫。
   */
  function buildChapterNav(entries) {
    const host = el("chapter-index");
    host.replaceChildren();
    chapterNav.links.clear();
    chapterNav.shown = new Set(resultMode.chapters);
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
      const count = make("span", "chapter-number");
      count.textContent = String(number);
      const name = make("span", "chapter-name");
      name.textContent = chapterTitle(node);
      link.append(count, name);
      // 很窄的螢幕只顯示短章名（calculate.css）；連結的名稱仍是完整章名，短名不給輔助科技重念一次。
      if (Chapters.SHORT_TITLES[id]) {
        const short = make("span", "chapter-name-short");
        short.textContent = Chapters.SHORT_TITLES[id];
        short.setAttribute("aria-hidden", "true");
        link.appendChild(short);
      }
      item.appendChild(link);
      const own = entries.get(id) || [];
      if (own.length) {
        const list = make("ul", "chapter-sections-index");
        own.forEach((entry) => {
          const row = document.createElement("li");
          row.appendChild(indexLink(entry.node, entry.title, entry.status));
          list.appendChild(row);
        });
        item.appendChild(list);
      }
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
    note.hidden = resultMode.chapters.length === Chapters.CHAPTER_IDS.length;
    if (note.hidden) return;
    const button = make("button", "ghost small chapter-mode-switch");
    button.type = "button";
    button.textContent = "改用古典完整";
    note.append(`${resultMode.label}只顯示 ${resultMode.chapters.length} 章。要看古典判斷與時間主星，請`, button, "。");
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
    radio.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    radio.focus({ preventScroll: true });
  }
  el("chapter-mode-note").addEventListener("click", switchModeFromNote);

  // 手機上的「直接開始填 ↓」：跳到模式選擇、焦點給選中的那一格。不走瀏覽器的錨點跳轉，網址不留 #片段、
  // 不多一筆歷史紀錄；沒有 JavaScript 時它照常是頁內連結。
  document.querySelector(".skip-to-form a").addEventListener("click", (event) => {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    el("mode-choice").scrollIntoView({ block: "start", behavior: prefersReducedMotion() ? "auto" : "smooth" });
    focusCheckedMode();
  });
  el("chapter-timelords-entry").addEventListener("click", switchModeFromNote);

  function toggleAllChapters() {
    chapterNav.all = !chapterNav.all;
    paintChapters();
    applyOverflowRegions();
  }
  el("chapters-all").addEventListener("click", toggleAllChapters);

  // ── 這次沒有算的區塊：「加算」 ──────────────────────────
  //
  // 古典完整與自訂在每一章的最後列出這次沒有算、勾一個選項就能加算的區塊（表裡的 enable）。
  // 「加算」把那幾個選項勾上、照表單原樣再送一次：與自己捲回表單勾選、重新計算完全一樣，送到同一個
  // 伺服器，伺服器同樣不留副本。被表單上另一個選項擋住的（例如只算古典七顆行星時的恆星）不給按鈕，
  // 寫明是被哪一項擋住。界、面、三分性沒有「加算」：要先選一套，按鈕帶使用者回到表單的選單。
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
      ? PROFILE_KEYS.filter((key) => optionValues[key] === null || optionValues[key] === undefined)
      : [];
    if (!groups.size && !unchosen.length) return null;
    const block = make("div", "chapter-absent");
    const title = make("p", "chapter-absent-title");
    title.textContent = "這次沒有算";
    const list = make("ul", "chapter-absent-list");
    groups.forEach(({ keys, titles }) => {
      const item = document.createElement("li");
      const name = titles.join("、");
      item.append(figureText("span", "chapter-absent-name", name));
      const blocked = keys.map((key) => Catalogue.conflictFor(Catalogue.BY_KEY[key], { ...optionValues, [key]: true }))
        .find(Boolean);
      if (blocked) {
        item.append(figureText("span", "chapter-absent-why", `要算這一項，先到表單改「${blocked.source.label_zh}」。`));
      } else {
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
      item.append(figureText("span", "chapter-absent-name", `${names}：還沒選用哪一套`));
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

  // 「加算」：按下時記下要打開的選項；送出時移到 resultFocusOptions（只屬於那一次送出），結果到了
  // 由 revealResults 把焦點與捲動交給新加的那一區的標題，不回到頁首。
  let addRequested = null;
  let resultFocusOptions = null;
  function addedSectionNode() {
    const wanted = resultFocusOptions;
    resultFocusOptions = null;
    if (!wanted) return null;
    const row = Chapters.SECTION_CHAPTERS.find((entry) => Chapters.enableOptions(entry.section).join(" ") === wanted
      && document.getElementById(`section-${entry.section}`));
    return row ? document.getElementById(`section-${row.section}`) : null;
  }

  function addFromChapter(event) {
    const target = event.target.closest ? event.target : null;
    const add = target && target.closest("button.chapter-add");
    if (add && !add.disabled) {
      addRequested = add.dataset.enable;
      add.dataset.enable.split(" ").forEach((key) => { optionValues = { ...optionValues, [key]: true }; });
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
      control.scrollIntoView({ block: "center", behavior: prefersReducedMotion() ? "auto" : "smooth" });
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

  // 用 Tab 在分頁列裡移動時，瀏覽器只把聚焦的那一項捲到剛好露出邊緣；整項捲進來才看得到焦點框。
  // 只對鍵盤的焦點（:focus-visible）這樣做：點或觸控時按下就有焦點，這時捲動分頁列，放開時指到的
  // 已是別的位置，這一下就不算點到連結。
  function revealFocusedLink(event) {
    const link = event.target.closest ? event.target.closest("a.chapter-link, a.index-link") : null;
    if (link && keyboardFocus(link)) revealIndexLink(link);
  }
  function keyboardFocus(node) {
    try {
      return node.matches(":focus-visible");
    } catch (_error) {
      return true;
    }
  }
  el("chapter-index").addEventListener("focusin", revealFocusedLink);

  /** 環標籤只寫中文（天文事實、幾何推導、方法判斷、驗證）；匯出的層級標籤照舊帶英文。 */
  function layerText(label) {
    return String(label || "").replace(/^[A-Z][A-Z ]*[A-Z]\s+/, "");
  }

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

    // 長區塊改為摺疊：一頁四百多列，全部攤開等於沒有結構。
    // 門檻式而非點名式——新的長區塊會自動適用，不必記得回來加。
    //
    // 門檻看字數，不看列數。列數是很差的高度代理，而且兩個方向都會錯：
    //   ·〈逐步計算軌跡〉在預設選項下正好 20 列，於是 rowCount > 20 為假、
    //     不摺疊；但它一列平均上千字，375px 下整區量到 67,984px，佔整份結果
    //     頁 80,776px 的 84%。使用者要看〈輸出契約〉或〈計算收據〉得先捲過
    //     84 個螢幕。
    //   ·〈三分性 Triplicity〉有 21 列但全部合計只有 159 字，卻因為 21 > 20
    //     被收進摺疊，等於為了幾行字要使用者多點一下。
    // 字數同時反映列數與每一列的長度，是「這一區要鋪多少版面」的直接量。
    const tables = section.children.filter((child) => child.type === "table");
    const rowCount = tables.reduce((total, table) => total + table.rows.length, 0);
    const charCount = tables.reduce(
      (total, table) => total + table.rows.reduce(
        (rowTotal, row) => rowTotal + row.reduce(
          (cellTotal, cell) => cellTotal + String(cell == null ? "" : cell).length,
          0,
        ),
        0,
      ),
      0,
    );
    // 列數門檻留著當保險：極端的「很多列但每列極短」不會被字數抓到。
    // 現有 fixture 都由字數先觸發，這一條沒有實際生效過。
    const collapsible =
      charCount > LONG_SECTION_CHARS || rowCount > LONG_SECTION_ROWS;
    let body = host;
    if (collapsible) {
      const details = make("details", "long-section");
      const summary = document.createElement("summary");
      summary.textContent = `展開這一區（${rowCount} 列）`;
      details.appendChild(summary);
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
    section.children.forEach((child) => {
      const target = child.type === "note" && !collapsible ? host : body;
      if (child.type === "figure") {
        // 摘要圖與它的第一行永遠在摺疊之外（預設不得摺疊）。
        host.insertBefore(materializeFigure(child.figure), collapsible ? body : null);
      } else if (child.type === "note") {
        const note = make("p", "section-note");
        note.textContent = child.text;
        // 備註留在摺疊外面：使用者要在展開前就知道這一區在講什麼。
        (collapsible ? host : target).insertBefore(note, collapsible ? body : null);
      } else if (child.type === "explain") {
        if (!explain) {
          explain = make("details", "section-explain");
          const summary = document.createElement("summary");
          summary.textContent = "說明與原典";
          explain.appendChild(summary);
          host.insertBefore(explain, collapsible ? body : null);
        }
        const line = make("p", "section-note");
        line.textContent = child.text;
        explain.appendChild(line);
      } else if (child.type === "block") {
        const block = make("p", "section-block");
        block.textContent = child.text;
        body.appendChild(block);
      } else if (child.type === "table") {
        const wrap = materializeTable(child, section.id, section.title);
        const bar = section.id === "bodies" ? decoratePositionTable(wrap, child) : null;
        if (bar) body.appendChild(bar);
        body.appendChild(wrap);
      } else if (child.type === "source") {
        // 古書出處：同一區的出處收在一個「出處」摺疊裡，預設收起。
        if (!sources) {
          sources = make("details", "section-sources");
          const summary = document.createElement("summary");
          summary.textContent = "出處";
          sources.appendChild(summary);
          body.appendChild(sources);
        }
        const line = make("p", "section-source");
        line.textContent = child.text;
        sources.appendChild(line);
      }
    });
    linkGlossaryTerms(host, section.id);
    return host;
  }

  // 區段說明裡第一次出現、名詞解釋有條目的詞，做成與章節導言同一種可點的詞（.term，點了打開名詞解釋
  // 並捲到那一條，glossary.js 在 document 上接線）。只換畫面上的節點，字一個不改；匯出讀 canonical
  // sections，不經過這裡。找不到那個詞（例如這次的說明沒有提到）就不加，不另外補字。
  const SECTION_TERMS = Object.freeze({
    fixed_stars: [["fixed_stars", "恆星"]],
    prenatal_points: [["prenatal_syzygy", "產前朔望"]],
    antiscia: [["antiscia", "反照點"]],
    dodecatemoria: [["dodecatemoria", "十二分部"]],
    aspects: [["aversion", "不合意"]],
    lunar_mansions: [["lunar_mansions", "月宿"]],
    void_of_course: [["void_of_course", "月空亡"]],
    solar_phase: [["cazimi", "日輪內"], ["combust", "焦傷"], ["under_beams", "在光束下"]],
    classical_classifications: [["benefic_malefic", "吉星"], ["joys", "喜樂"], ["hayz", "Hayz 與 halb"],
      ["house_triad", "始宮"]],
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
    const title = figureText("h3", "sampling-callout-title", summary.title);
    title.id = "sampling-callout-title";
    samplingCalloutHost.append(
      title,
      figureText("p", "sampling-callout-lead", summary.lead),
      figureText("p", "sampling-callout-intro", summary.intro),
    );
    if (summary.changes.length) {
      samplingCalloutHost.appendChild(figureText("h4", "sampling-callout-heading", "會變的"));
      const list = document.createElement("ul");
      list.className = "sampling-callout-changes";
      summary.changes.forEach((change) => {
        const item = document.createElement("li");
        const what = figureText("span", "sampling-callout-what", `${change.what}：`);
        item.append(what, figureText("span", "sampling-callout-when", change.when));
        list.appendChild(item);
      });
      samplingCalloutHost.appendChild(list);
    }
    [
      ["不變的", summary.same],
      ["只比較了一部分", summary.partial],
      ["沒有比較，只算了上面那一刻", summary.unchecked],
    ].forEach(([label, items]) => {
      if (!items.length) return;
      const line = figureText("p", "sampling-callout-line", "");
      line.append(figureText("b", "sampling-callout-line-label", `${label}：`), document.createTextNode(`${items.join("、")}。`));
      samplingCalloutHost.appendChild(line);
    });
    samplingCalloutHost.appendChild(figureText("p", "note sampling-callout-caveat", summary.caveat));
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
    const targets = new Map(linkable.map((item) => [item.title, `#section-${item.id}`]));
    node.querySelectorAll(".section-block").forEach((note) => {
      const parts = note.textContent.split(/〈([^〉]+)〉/);
      if (parts.length === 1) return;
      note.replaceChildren();
      parts.forEach((part, index) => {
        const href = index % 2 === 1 ? targets.get(part) : null;
        if (!href) {
          if (part) note.append(index % 2 === 1 ? `〈${part}〉` : part);
          return;
        }
        const link = document.createElement("a");
        link.href = href;
        link.textContent = part;
        note.append("〈", link, "〉");
      });
    });
    summaryHost.appendChild(node);
  }

  // ── 取樣摘要圖 ─────────────────────────────────────────
  //
  // 不可操作：沒有把手、沒有焦點停留點。每個取樣點是一個獨立的點，點與點之間
  // 是虛線（那裡沒有計算），不畫連續填滿的條。點列整體是一張 role="img"，
  // 名稱是 view-model 給的文字版；畫面上的時刻標籤只是同一份資訊的視覺版。
  // 位置與樣式全部由 calculate.css 的 class 與 data 屬性決定，不寫 style 屬性
  // （release CSP 的 style-src 'self'）。文字一律走 textContent。
  function figureText(tag, className, content) {
    const node = document.createElement(tag);
    node.className = className;
    node.textContent = content;
    return node;
  }

  function materializeFigure(figure) {
    const host = make("div", "sampling");
    host.dataset.tone = figure.tone;

    host.appendChild(figureText("p", "sampling-lead", figure.lead));

    const marks = make("div", "sampling-marks");
    marks.setAttribute("role", "img");
    // 名稱是一句摘要（點數、首尾、代表性時刻、有改變的間隔數），由同一份 marks 導出；
    // 逐點的 text_alternative 放在圖之後的文字裡。名稱塞進二十五個時刻，報讀每經過
    // 這張圖都得聽完。
    const representative = figure.marks.find((mark) => mark.representative);
    const changed = figure.marks.filter((mark) => mark.bands_after > 0).length;
    marks.setAttribute("aria-label",
      `取樣點 ${figure.marks.length} 個，${figure.marks[0].label} 到 ${figure.marks.at(-1).label}`
      + (representative ? `，代表性時刻 ${representative.label}` : "")
      + (changed ? `；${changed} 個間隔內有改變` : "")
      + "。");
    // 點太多時只標首、尾與代表性時刻，其餘的時刻在文字版裡。
    marks.dataset.density = figure.marks.length > 7 ? "dense" : "sparse";
    figure.marks.forEach((mark, index) => {
      const item = make("span", "sampling-mark");
      if (mark.representative) item.dataset.representative = "true";
      if (index === 0) item.dataset.edge = "first";
      if (index === figure.marks.length - 1) item.dataset.edge = "last";
      const dot = make("span", "sampling-dot");
      item.append(dot, figureText("span", "sampling-time", mark.label));
      marks.appendChild(item);
      if (index < figure.marks.length - 1) {
        const gap = make("span", "sampling-gap");
        if (mark.bands_after > 0) {
          gap.dataset.bands = String(mark.bands_after);
          const band = make("span", "sampling-gap-band");
          gap.append(band, figureText("span", "sampling-gap-count", mark.gap_label));
        }
        marks.appendChild(gap);
      }
    });
    host.appendChild(marks);
    // 逐點的時刻只給輔助科技，緊接在圖之後；明眼使用者從圖上的標籤讀同一份資訊。
    host.appendChild(figureText("p", "visually-hidden", figure.text_alternative));

    // 圖例只描述圖形，文字輸出不印（契約）；與備註分在兩個節點，畫面上仍是同一段。
    const note = make("p", "sampling-note");
    if (figure.legend) note.appendChild(figureText("span", "sampling-legend", figure.legend));
    if (figure.note) note.appendChild(document.createTextNode(figure.note));
    host.appendChild(note);

    figure.groups.forEach((group) => {
      const block = make("div", "sampling-group");
      block.dataset.tone = group.tone;
      block.appendChild(figureText("h4", "sampling-group-title", group.title));
      if (group.note) block.appendChild(figureText("p", "sampling-group-note", group.note));
      if (group.bands.length) {
        const list = make("ul", "sampling-bands");
        group.bands.forEach((band) => {
          const row = document.createElement("li");
          const glyph = make("span", "sampling-band");
          glyph.setAttribute("aria-hidden", "true");
          row.append(
            glyph,
            figureText("span", "sampling-band-range", band.range),
            figureText("span", "sampling-band-resolution", band.resolution),
            figureText("span", "sampling-band-what", band.text),
          );
          list.appendChild(row);
        });
        block.appendChild(list);
      }
      if (group.items.length) {
        block.appendChild(figureText("p", "sampling-items", group.items.join("、")));
      }
      host.appendChild(block);
    });
    return host;
  }

  // 900 字：以現有 fixture 校準。chart-exact 下最大的非軌跡區塊是
  // 〈計算收據〉1,364 字，而〈本次請求的選項〉946 字——兩者都該摺疊；
  // 〈天體位置〉569 字、〈相位〉481 字則該留在外面。全部模組開啟時
  // 〈軌跡〉、〈相位〉、〈恆星〉都超過門檻而摺疊。
  const LONG_SECTION_CHARS = 900;
  const LONG_SECTION_ROWS = 30;

  // ── 表格的畫面加工：數字欄與名稱符號 ──────────────────────
  //
  // 只改畫面，不改內容。每一格的 textContent 仍是 view-model 給的那一格，欄序照
  // view-model。複製本區、複製結果與四種下載都由 canonical 快照產生，不讀 DOM；
  // 符號是沒有文字節點的 SVG，aria-hidden，報讀、選取複製與 textContent 都讀不到。
  const SVG_NS = "http://www.w3.org/2000/svg";

  // 數字欄：每一格都是帶號十進位數或度分秒（或「—」、空白），而且至少一格是數字。
  // 「金牛 24°10′30.48″」、時刻字串與文字不算，維持靠左。
  const NUMERIC_CELL = /^[+\-−]?\d+(?:\.\d+)?(?:°\d+′\d+(?:\.\d+)?″)?$/;
  const NEUTRAL_CELL = (text) => text === "" || text === "—";

  function numericColumns(model) {
    return model.columns.map((_column, index) => {
      if (index === 0) return false;
      const cells = model.rows.map((row) => String(row[index] == null ? "" : row[index]).trim());
      return cells.some((text) => NUMERIC_CELL.test(text))
        && cells.every((text) => NEUTRAL_CELL(text) || NUMERIC_CELL.test(text));
    });
  }

  // 天體、交點與月球拱點的符號：表格帶點鍵（圖表連動的那幾張）時照每一列的鍵取，與星盤圖用同一張
  // 對照（ChartWheelModel.POINTS）；鍵只認 labels.js 後端名稱表裡的天體、交點與拱點（軸點不加符號）。
  // 沒有點鍵的表（與一頁摘要）才退回用名稱對照，名稱取同一張後端名稱表。星座的鍵就是符號鍵。
  // 對照不到的（Priapus、恆星、阿拉伯點…）不加符號，不猜。
  const TABLE_GLYPHS = (() => {
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
    Object.entries(vocabulary.zodiac_sign).forEach(([key, name]) => {
      if (glyphs.GLYPHS[key]) signs.set(name, key);
    });
    return { bodies, keys, signs, glyphs: glyphs.GLYPHS };
  })();
  const SIGN_AT_START = new RegExp(`^(${[...TABLE_GLYPHS.signs.keys()].join("|") || "(?!)"}) (?=\\d)`);
  // 相位表的組合欄「太陽 — 月亮」：兩邊各自對照。
  const PAIR_SEPARATOR = " — ";

  // 符號框：寬依字形置中，高固定為基線上 810、下 240 單位（1/1000 em），各符號與文字
  // 同一條基線，像同一套字型。
  function tableGlyph(key) {
    const [x0, , x1] = TABLE_GLYPHS.glyphs[key].bbox;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "cell-glyph");
    svg.setAttribute("viewBox", `${Math.round((x0 + x1) / 2) - 525} -810 1050 1050`);
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.dataset.glyph = key;
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", TABLE_GLYPHS.glyphs[key].d);
    svg.appendChild(path);
    return svg;
  }

  /**
   * 填入一格：文字原樣；認得的天體或星座度數前加符號。cellKeys：這一格的點鍵（表格帶點鍵時；
   * 相位組合欄「太陽 — 月亮」是兩個），有就照鍵取符號，不看名稱；null 時才照名稱對照。
   */
  function fillCell(node, text, withBodies, cellKeys = null) {
    if (withBodies && Array.isArray(cellKeys)) {
      const parts = cellKeys.length > 1 ? text.split(PAIR_SEPARATOR) : [text];
      if (parts.length === cellKeys.length) {
        parts.forEach((part, index) => {
          if (index > 0) node.append(PAIR_SEPARATOR);
          const glyph = TABLE_GLYPHS.keys.get(cellKeys[index]);
          if (glyph) node.append(tableGlyph(glyph));
          node.append(part);
        });
        return;
      }
    }
    if (withBodies) {
      const parts = text.split(PAIR_SEPARATOR);
      if (parts.some((part) => TABLE_GLYPHS.bodies.has(part))) {
        parts.forEach((part, index) => {
          if (index > 0) node.append(PAIR_SEPARATOR);
          if (TABLE_GLYPHS.bodies.has(part)) node.append(tableGlyph(TABLE_GLYPHS.bodies.get(part)));
          node.append(part);
        });
        return;
      }
    }
    const sign = SIGN_AT_START.exec(text);
    if (sign) node.append(tableGlyph(TABLE_GLYPHS.signs.get(sign[1])));
    node.append(text);
  }

  function materializeTable(model, sectionId, sectionTitle) {
    const wrap = make("div", "table-wrap");
    // role／tabindex 由 applyOverflowRegions 依實際溢出決定，不在這裡寫死。
    wrap.dataset.regionLabel = [sectionTitle, model.title || "可橫向捲動的資料表"]
      .filter(Boolean).join("：");
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
    if (model.title) {
      const caption = document.createElement("caption");
      caption.textContent = model.title;
      table.appendChild(caption);
    }
    // 相位方格的格內是相位與度數的組合，不是單一數值，維持置中；欄頭是天體名稱。
    const isGrid = model.variant === "aspect_grid";
    const numeric = isGrid ? model.columns.map(() => false) : numericColumns(model);
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    model.columns.forEach((column, index) => {
      const th = document.createElement("th");
      th.scope = "col";
      if (numeric[index]) th.className = "num";
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
        // 第一格說明這一列是什麼（天體、步驟、項目），做成列標頭；報讀器讀到
        // 後面的數值時才知道屬於哪一列。
        const node = document.createElement(index === 0 ? "th" : "td");
        if (index === 0) node.scope = "row";
        if (numeric[index]) node.className = "num";
        // 格內連結（十二宮表的宮名連到方法頁宮義對照表的那一列）：文字照原字，包在連結裡。
        const href = index > 0 && model.links && model.links.column === index && Array.isArray(model.links.rows)
          ? model.links.rows[rowIndex] : null;
        const host = typeof href === "string" && href.startsWith("/zh-TW/") ? document.createElement("a") : node;
        if (host !== node) {
          host.href = href;
          node.appendChild(host);
        }
        fillCell(host, String(cell == null ? "" : cell), index === 0, index === 0 && Array.isArray(rowKeys) ? rowKeys : null);
        tr.appendChild(node);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    linkTableCells(table, model, sectionId);
    wrap.appendChild(table);
    return wrap;
  }

  // ══ 匯出 ══════════════════════════════════════════════
  function selectedExportMode() {
    const selected = document.querySelector(
      'input[name="export-detail-mode"]:checked'
    );
    return selected ? selected.value : "chart_data_only";
  }

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
      if (!snapshot) throw new Error("找不到這個區段的 canonical 快照。");
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
  let pendingPrintMode = null;
  function printFromButton(event) {
    try { requireExportableDocument(); }
    catch (error) { setStatus(`無法列印：${error.message}`, "error"); return; }
    pendingPrintMode = event.currentTarget.dataset.printMode === PRINT_MODE.BRIEF ? PRINT_MODE.BRIEF : PRINT_MODE.FULL;
    results.dataset.printMode = pendingPrintMode;
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
  let restorePrintExpansion = null;
  function endPrint() {
    if (restorePrintExpansion) restorePrintExpansion();
    restorePrintExpansion = null;
    delete results.dataset.printWithheld;
    delete results.dataset.printMode;
    delete results.dataset.printInput;
    clearPrintInputSummary();
    printBriefTables.querySelectorAll(".print-brief-timelords").forEach((node) => node.remove());
  }
  window.addEventListener("beforeprint", () => {
    // 按鈕寫下的模式維持到 afterprint：有的瀏覽器（Chromium 存成 PDF）在一次列印裡會再送一次
    // beforeprint，不能因此退回完整列印。
    const mode = pendingPrintMode
      || (results.dataset.printMode === PRINT_MODE.BRIEF ? PRINT_MODE.BRIEF : PRINT_MODE.FULL);
    pendingPrintMode = null;
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
    restorePrintExpansion = window.ChartExport.printExpansion(
      results.querySelectorAll("details:not(.tl-decade):not(.first-time)")
    );
  });
  window.addEventListener("afterprint", () => {
    pendingPrintMode = null;
    endPrint();
  });

  // ── 列印的輸入摘要 ──────────────────────────────────────
  //
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
    ["date", "hour", "minute", "second"].forEach((id) => add(fieldLabel(id), shownField(id)));
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

  // ── 一頁摘要 ──────────────────────────────────────────
  //
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
    table.appendChild(figureText("caption", "", caption));
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    columns.forEach((column) => {
      const th = figureText("th", "", column);
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
    if (line) printBriefTables.appendChild(figureText("p", "print-brief-timelords", line));
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
    ].filter(Boolean).forEach((line) => printBriefReceipt.appendChild(figureText("dd", "", line)));
    const brief = window.ChartViewModel.printBriefRows(tree);
    if (!brief) {
      printBriefTables.appendChild(figureText("p", "note", "這次的位置表無法摘要，見完整列印。"));
      return;
    }
    printBriefTables.appendChild(printBriefTable("天體與軸點", brief.columns, brief.rows));
  }

  // ══ 年度時間主星的接點 ══════════════════════════════════
  //
  // 年度一區（timelords.js）只讀畫面上這份結果的請求，不另收出生資料；結果換掉或清除時
  // 跟著丟棄，表單改動時跟著停用。頁面上沒有那一區時三者都不做事。
  function annualPanel() {
    return window.ArmillaryTimelords.forPage(document);
  }
  function showAnnualPanel(payload) {
    const panel = annualPanel();
    if (panel) panel.show(payload);
  }
  function staleAnnualPanel(stale) {
    const panel = annualPanel();
    if (panel) panel.setStale(stale);
  }
  function dropAnnualPanel() {
    const panel = annualPanel();
    if (panel) panel.drop();
  }

  // ══ 兩種清除（匯出契約驗收 16）══════════════════════════
  function dropResultsForNewAttempt() {
    // 先放掉綁定、停用全部匯出控制項，再把結果移出 DOM：移走的按鈕若仍被舊的參照按到，
    // 它已是 disabled，處理函式也因 lifecycle 已清空而拒絕。
    boundInputSignature = null;
    currentViewTree = null;
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
    manualCivilTime = false;
    renderCivilTimeChoice(null);
  }

  /**
   * 把表單、選項、地點狀態、錯誤、結果、進行中的請求全部回到初始狀態。
   * 「清除敏感資料」、範例載入、pagehide、pageshow(persisted) 都走這一個
   * 函式；分開寫就會各漏一塊。
   */
  function resetFormState() {
    dropResults();
    // 進行中的送出與地點查詢一起作廢；
    // 遲到的回應被世代號與 lifecycle token 擋下。
    invalidateAttempt();
    cancelButton.hidden = true;
    placeSearchLifecycle.abortActiveRequest();
    form.reset();
    clearAllFieldInvalid();
    // 選項回到目前這個模式預先勾好的那一組（載入合成範例時模式不變）；「時間主星」那一格同理。
    optionValues = Chapters.modeOptions(currentModeId, Catalogue.defaults());
    el("plan-timelords").checked = Chapters.mode(currentModeId).timelordsAfterChart;
    selectedPlace = null;
    clearPlaceReceipt();
    placeResults.replaceChildren();
    placeResults.hidden = true;
    placeQuery.value = "";
    secondInput.value = "";
    setPlaceStatus(PLACE_SEARCH.NOT_SEARCHED, "", "info");
    applyPrecisionConsequences();
    applyZodiacConsequences();
    refreshOptionUi();
    // 模糊時刻的選擇區是從已清空的輸入推導出來的，必須跟著重算——否則表單
    // 空了，畫面卻還留著「這個時間出現了兩次」，等於洩漏上一筆輸入的性質。
    // 服務回報過的那個時刻同樣是上一筆輸入的痕跡，一起清掉。
    serviceRepeatedTime = null;
    refreshFoldChoice();
    refreshTimezoneOffset();
    setEraEcho("", "info");
    clearTimeCheck();
  }

  function clearSensitiveState() {
    resetFormState();
    // 回到剛載入的樣子：模式回到快速看盤、圖回到圓盤。
    chartStyle = "wheel";
    lastRenderedMode = null;
    applyMode("quick");
    clearAddressInput();
  }

  // 送出中唯一可達的中止入口。只停止等待這一次，不動已算出的結果——
  // 那是「清除」的語意，不是「中止」的。
  cancelButton.addEventListener("click", () => {
    const aborted = lifecycle.abortActiveRequest();
    // 世代號前進，遲到的回應與 finally 一律放棄。
    const active = attemptState !== ATTEMPT.IDLE;
    invalidateAttempt();
    cancelButton.hidden = true;
    submitButton.disabled = false;
    setStatus(aborted || active ? CANCELLED_MESSAGE : "目前沒有進行中的計算。", "info");
    submitButton.focus();
  });

  // 兩顆清除鈕都在 #results 裡，清除會把 #results 隱藏；焦點留在原地會掉到
  // body，下一個 Tab 從頁尾開始、跳過整張表單。移到送出鈕：狀態列就在它
  // 旁邊，與中止鈕的落點一致。
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

  // 離開頁面時走與「清除敏感資料」相同的清除；這不是記憶體安全抹除，也不
  // 控制瀏覽器當機還原。bfcache 可能把整個 DOM 原樣端回來，所以 pageshow
  // 帶 persisted 時再清一次。
  window.addEventListener("pagehide", () => { try { clearSensitiveState(); } catch (_) {} });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    try { clearSensitiveState(); } catch (_) {}
  });

  // ══ 起始狀態 ══════════════════════════════════════════
  buildPlanProfiles();
  buildOptionUi();
  // 名詞解釋的抽屜：表單上方與結果標題旁各一顆「名詞解釋」，頁面上帶虛線底的詞點了也打開它。
  window.ArmillaryGlossary.mount(document, { host: document.querySelector(".calc-body") });
  // 站內連結帶了模式就用它，否則快速看盤（就是產品預設）。
  applyMode(linkedMode || "quick");
  applyPrecisionConsequences();
  applyZodiacConsequences();
  // 還沒有結果：匯出控制項從一開始就停用，與清除之後同一個狀態。
  applyExportAvailability();
  // HTML 先以不依賴 JavaScript 的方式顯示「介面正在載入」。只有全部必要
  // dependencies、選項 UI、表單守衛與事件接線都完成，才在最後把它隱藏。
  // 任一前置 script 失敗或本檔初始化中途丟錯時，訊息會自然留下，而不是
  // 端出一個看似正常、選項為空且永遠不能送出的表單。
  bootstrapStatus.hidden = true;
  // 表單沒有 action 也沒有 method，原生送出會把出生資料放進query string。
  // HTML先disabled，且必須等submit守衛、選項UI及兩個結果約束全部成功後才
  // 解除；任何半初始化狀態都同時保留警告與disabled submit。
  submitButton.disabled = false;
  submitButton.removeAttribute("title");

})();
