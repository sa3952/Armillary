(function calculatePage() {
  "use strict";

  // 這一層只做接線：收表單、打同源 API、把 view tree 變成元素、接匯出與清除。
  // 「回應長什麼樣」在 view-model.js，「有哪些選項」在 options-catalogue.js，
  // 序列化在 exporters.js。這裡不得自行讀 source_response 組畫面（契約 §10）。

  // 本頁不讀網址的 query 或 fragment；帶著它們來的，是訪客或連結放進去的東西，
  // 可能就是出生資料。第一件事就從網址列與這一筆歷史紀錄拿掉（取代，不新增），
  // 排在任何可能丟錯的初始化之前，載入失敗時也不留在網址上。瀏覽器在載入前
  // 已記下的全域歷史，本頁收不回。
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
  const form = el("chart-form");
  const statusLine = el("status-line");
  const errorPanel = el("error-panel");
  const errorMessage = el("error-message");
  const errorActions = el("error-actions");
  const results = el("results");
  const sectionsHost = el("sections");
  const warningsHost = el("warnings");
  const samplingCalloutHost = el("sampling-callout");
  const submitButton = el("submit-button");
  const cancelButton = el("cancel-button");
  const bootstrapStatus = el("bootstrap-status");
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
      const block = document.createElement("div");
      block.className = "option-block";
      block.dataset.group = group.key;
      block.setAttribute("role", "group");

      const heading = document.createElement("div");
      heading.className = "option-heading";
      heading.id = `option-group-${group.key}-heading`;
      block.setAttribute("aria-labelledby", heading.id);
      heading.append(group.label_zh);
      const en = document.createElement("span");
      en.className = "en";
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
    // 說明文字在靜態 HTML（#opt-house_system-hint），控制項由這裡產生。
    select.setAttribute("aria-describedby", "opt-house_system-hint");

    const none = document.createElement("option");
    none.value = NO_HOUSES;
    none.textContent = "不計算宮位　No houses";
    select.appendChild(none);

    option.values.forEach((value) => {
      const opt = document.createElement("option");
      opt.value = String(value.value);
      opt.textContent = `${value.label_zh}　${value.label_en}`;
      select.appendChild(opt);
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
    const wrap = document.createElement("div");
    wrap.className = "house-control";
    wrap.appendChild(select);
    wrap.appendChild(mirror);
    return wrap;
  }

  function buildOptionRow(option) {
    const row = document.createElement("div");
    row.className = "option-row";
    row.dataset.option = option.key;

    const label = document.createElement("label");
    label.className = "option-label";
    label.htmlFor = `opt-${option.key}`;
    label.append(option.label_zh);
    const en = document.createElement("span");
    en.className = "en";
    en.lang = "en";
    en.textContent = option.label_en;
    label.appendChild(en);

    row.appendChild(label);
    const control = buildControl(option);
    row.appendChild(control);

    const helpText = Catalogue.helpText(option);
    if (helpText) {
      const help = document.createElement("p");
      help.className = "option-help";
      help.id = `opt-${option.key}-help`;
      help.textContent = helpText;
      row.appendChild(help);
      // 說明關聯到控制項，聚焦時就念得到（WCAG 1.3.1）。
      const target = control.id === label.htmlFor ? control : control.querySelector(`#${label.htmlFor}`);
      if (target) target.setAttribute("aria-describedby", help.id);
    }

    const children = Catalogue.OPTIONS.filter((child) => child.depends_on === option.key);
    if (children.length) {
      const nest = document.createElement("div");
      nest.className = "option-children";
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
    }

    const counts = Catalogue.enabledCountByGroup(optionValues);
    // 標題說的是「進階選項」，只數進階群組。主表單的宮位選擇就在眼前；計進來會讓
    // 只選了「不計算宮位」的人讀到「已調整 1 項」，卻在進階選項裡找不到那一項。
    const total = Catalogue.GROUPS
      .filter((group) => group.in_advanced)
      .reduce((sum, group) => sum + counts[group.key], 0);
    el("advanced-summary").textContent = total
      ? `進階選項：已調整 ${total} 項`
      : "進階選項：全部為產品預設";
    el("advanced-summary").dataset.state = total ? "changed" : "default";
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
      if (chosen) parts.push(`${chosen.label_zh}制`);
    }
    summary.textContent = parts.join(" · ");
  }

  el("reset-options").addEventListener("click", () => {
    optionValues = Catalogue.defaults();
    refreshOptionUi();
    noteFormChanged();
    setStatus("進階選項已回到產品預設。", "info");
  });

  // ══ 地點：離線目錄查詢 ════════════════════════════════
  const placeQuery = el("place-query");
  const placeResults = el("place-results");
  const placeStatus = el("place-status");
  const PLACE_SEARCH_TIMEOUT_MS = 10000;
  // 地點查詢的狀態是閉集：「未搜尋」「查詢中」「找到」「服務答了但零筆」
  // 「查詢裡沒有可比對的文字」「服務答了但答案讀不懂」「服務拒絕」「逾時」
  // 「沒送達」「字太少」各是不同值。
  // 寫在 #place-status 的 data-state，訊息文字只是它的呈現。
  const PLACE_SEARCH = Object.freeze({
    NOT_SEARCHED: "not_searched",
    SEARCHING: "searching",
    FOUND: "found",
    NONE: "none",
    NO_SEARCHABLE_TOKENS: "no_searchable_tokens",
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
    const controller = new AbortController();
    const token = placeSearchLifecycle.beginRequest(controller);
    const timeout = placeSearchLifecycle.scheduleAbort(
      controller, PLACE_SEARCH_TIMEOUT_MS, window.setTimeout.bind(window)
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
            PLACE_SEARCH.NO_SEARCHABLE_TOKENS,
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
        // 被截斷時是警告而不是單純資訊：結果不涵蓋使用者打的全部內容。
        setPlaceStatus(
          PLACE_SEARCH.FOUND,
          truncation
            ? `找到 ${found.length} 筆。座標為目錄的代表點，不是出生地址。${truncation}`
            : `找到 ${found.length} 筆。座標為目錄的代表點，不是出生地址。`,
          truncation ? "warning" : "info"
        );
        found.forEach((place) => placeResults.appendChild(buildPlaceRow(place)));
        placeResults.hidden = false;
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
    const meta = document.createElement("span");
    meta.className = "place-meta mono";
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

  function selectPlace(place) {
    selectedPlace = place;
    el("latitude").value = String(place.latitude);
    el("longitude").value = String(place.longitude);
    if (!el("altitude").value.trim()) el("altitude").value = "0";
    el("timezone").value = place.timezone || "";

    // 收據念的是中文標籤；目錄的原始代碼與記錄 id 收在「技術細節」摺疊裡，
    // 回報問題或對照目錄時仍拿得到，平常讀收據時不會聽到一串底線英文。
    const describe = (list, rows, lang) => {
      list.replaceChildren();
      rows.forEach(([term, en, value]) => {
        const dt = document.createElement("dt");
        dt.append(term);
        if (en) {
          const tag = document.createElement("span");
          tag.className = "en";
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
    describe(el("place-receipt-body"), [
      ["地點", null, place.display_name || place.name],
      ["緯度", "latitude", Number(place.latitude).toFixed(6)],
      ["經度", "longitude", Number(place.longitude).toFixed(6)],
      ["時區", "timezone", place.timezone || "—"],
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
      + "若你知道更精確的座標，請在下方手動輸入取代它。時區已依目錄帶入，仍請確認出生當時實際適用的時區。";
    el("place-receipt").hidden = false;
    placeResults.hidden = true;
    setPlaceStatus(PLACE_SEARCH.FOUND, "已選定地點，座標與時區已填入。", "info");
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
        || String(el("timezone").value) !== String(selectedPlace.timezone || "");
      if (drifted) {
        selectedPlace = null;
        clearPlaceReceipt();
        setPlaceStatus(PLACE_SEARCH.NOT_SEARCHED, "座標或時區已手動修改，目錄收據不再適用。", "info");
      }
    });
  });

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
    const pad = (value, width) => String(value).padStart(width, "0");
    return timeKey(
      payload.birth_time_precision,
      `${pad(datetime.year, 4)}-${pad(datetime.month, 2)}-${pad(datetime.day, 2)}`,
      datetime.hour,
      datetime.minute,
      datetime.second,
      timezone.iana_name
    );
  }

  const SERVICE_AMBIGUITY = Object.freeze(
    { state: "ambiguous", source: "service", occurrences: [{ fold: 0 }, { fold: 1 }] }
  );

  function currentAmbiguity() {
    const dateValue = String(el("date").value).trim();
    const timezone = String(el("timezone").value).trim();
    if (!dateValue || !timezone) return null;
    const [year, month, day] = dateValue.split("-").map(Number);
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
    if (target && typeof target.hasAttribute === "function" && target.hasAttribute("aria-invalid")) {
      clearFieldInvalid(target);
    }
    refreshResultBinding();
  }

  form.addEventListener("change", (event) => {
    if (event.target.name === "precision") applyPrecisionConsequences();
    if (event.target.id === "zodiac") applyZodiacConsequences();
    if (event.target.id === "ayanamsa") refreshModeSummary();
    noteFormChanged(event.target);
  });
  form.addEventListener("input", (event) => { noteFormChanged(event.target); });

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
    const dateValue = String(el("date").value).trim();
    if (!dateValue) requireField(el("date"), "出生日期");
    const timezone = String(el("timezone").value).trim();
    if (!timezone) requireField(el("timezone"), "時區（查詢地點或手動輸入）");
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

    const [year, month, day] = dateValue.split("-").map(Number);
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
        timezone: ambiguity
          ? { mode: "iana", iana_name: timezone, fold: foldChoice }
          : { mode: "iana", iana_name: timezone },
        location: LocationReceipt.buildLocationInput({
          latitude,
          longitude,
          altitudeM: altitude,
          selectedPlace,
        }),
        // 不送 atmosphere。折射用的溫度與氣壓預設值只在伺服器
        // （app.config.DEFAULT_ATMOSPHERE_TEMPERATURE_C 與 AtmosphereInput），
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

  function isJsonResponse(response) {
    const mediaType = (response.headers.get("Content-Type") || "")
      .split(";", 1)[0].trim().toLowerCase();
    return mediaType === "application/json" || mediaType.endsWith("+json");
  }

  /**
   * 三個 POST 端點共用的一次往返：送 JSON、收 JSON。2xx 但 media type 不是 JSON
   * 時不讀 body，標成 invalidJsonMedia；body 解析失敗為 null。怎麼對使用者說由呼叫端決定。
   */
  function postJson(url, payload, signal) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
    }).then((response) => {
      if (response.ok && !isJsonResponse(response)) {
        return { response, body: null, invalidJsonMedia: true };
      }
      return response.json().catch(() => null)
        .then((body) => ({ response, body, invalidJsonMedia: false }));
    });
  }

  function submitPayload(payload, generation, signature) {
    dropResultsForNewAttempt();
    const controller = new AbortController();
    const token = lifecycle.beginRequest(controller);
    const timeout = lifecycle.scheduleAbort(
      controller, REQUEST_TIMEOUT_MS, window.setTimeout.bind(window)
    );
    const finishAttempt = () => {
      window.clearTimeout(timeout.handle);
      cancelButton.hidden = true;
    };

    submitButton.disabled = true;
    cancelButton.hidden = false;
    setStatus("計算中…", "info");

    postJson("/api/chart", payload, controller.signal)
      .then(({ response, body, invalidJsonMedia }) => {
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
        showError(window.ClientContext.networkErrorMessage(),
          ["確認服務仍在執行後重試。", "重新載入頁面。"]);
        setStatus("沒有送達計算服務。", "error");
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
    showError(message, actions);
    setStatus("服務拒絕了這次計算。", "error");
    // 伺服器點名的欄位標 aria-invalid、展開所在摺疊區並移焦點。
    // 對照表在 ClientContext；選項若由另一個控制項代為呈現（rendered_by），標在看得見的那個上。
    const invalid = window.ClientContext.fieldControlIds(detail)
      .map((id) => {
        const key = id.startsWith("opt-") ? id.slice(4) : null;
        const option = key && Object.prototype.hasOwnProperty.call(Catalogue.BY_KEY, key)
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

    renderSamplingCallout(tree.header.sampling_callout);

    warningsHost.replaceChildren();
    warningsHost.hidden = tree.header.warnings.length === 0;
    tree.header.warnings.forEach((warning) => {
      const item = document.createElement("li");
      item.textContent = warning.message;
      warningsHost.appendChild(item);
    });

    // 結果頁有二十一個區塊、三百多列，沒有索引就只能一路捲。
    // 索引同時顯示每一區的環與收據狀態，讓「哪些被拒絕、哪些沒請求」在捲之前就看得到。
    const technicalIds = TECHNICAL_SECTION_IDS;
    const resultSections = tree.sections.filter(
      (section) => section.status.state !== "not_requested"
        && !technicalIds.has(section.id)
    );
    const technicalSections = tree.sections.filter(
      (section) => technicalIds.has(section.id)
    );
    buildSectionIndex(resultSections);

    sectionsHost.replaceChildren();
    resultSections.forEach(
      (section) => sectionsHost.appendChild(materializeSection(section))
    );
    // 預設回應不含驗算資料；技術區塊等使用者打開時才取得。
    // 回應若本來就是完整版（沒有 projection 鍵），技術區塊照舊直接畫出。
    beginDetailBinding(canonical, payload);
    if (technicalSections.length) {
      const details = document.createElement("details");
      details.className = "technical-results";
      const summary = document.createElement("summary");
      summary.textContent = "技術細節與驗算資料";
      const note = document.createElement("p");
      note.className = "note";
      note.textContent = "版本、來源、選項、計算軌跡與完整收據。一般閱讀不需要展開。";
      details.append(summary, note);
      technicalHost = details;
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
      sectionsHost.appendChild(details);
    }

    results.hidden = false;
    boundInputSignature = signature;
    refreshResultBinding();
    applyOverflowRegions();
    setStatus("計算完成。", "info");
    // 結果到達時把焦點交給結果標題（HTML 帶 tabindex="-1"），使用者才知道
    // 畫面上多了什麼。
    el("results-heading").focus();
  }

  // ── 結果與表單的綁定──────────────────────
  //
  // 畫面上的結果只對它送出當下的輸入成立。表單任何一處改動後，結果標為
  // stale、複製與下載停用；改回原值則綁定又成立。飛行中改動也一樣：回來的
  // 結果在渲染那一刻就會被比對。
  let boundInputSignature = null;   // null = 畫面上沒有結果
  let currentViewTree = null;       // 畫面上那棵 view tree；清除結果時一併放掉
  const staleNotice = el("stale-notice");
  const exportButtons = document.querySelectorAll("[data-copy], [data-download], #print-button");

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
    staleNotice.hidden = !stale;
    if (stale && tree && tree.header.stale_notice) staleNotice.textContent = tree.header.stale_notice;
    lastExportActions = actions;
    applyExportAvailability();
  }

  /**
   * 複製與下載是否可按，只有這一處決定：結果過期時依 view-model 的 actions；
   * 選了「運算結果＋驗算資料」而驗算資料還沒到手時，複製與下載也先停用（列印照舊，
   * 它印的是畫面）。
   */
  function applyExportAvailability() {
    const actions = lastExportActions;
    const waitingForDetail = selectedExportMode() === "reproducibility_detail"
      && verification.state !== DETAIL.READY;
    exportButtons.forEach((button) => {
      const allowed = button.hasAttribute("data-download")
        ? actions.download_enabled
        : actions.copy_enabled;
      button.disabled = !allowed
        || (waitingForDetail && button.id !== "print-button");
    });
    sectionsHost.querySelectorAll(".section-copy").forEach((button) => {
      button.disabled = !actions.copy_enabled;
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

  function detailStatusBlock(place) {
    const block = document.createElement("div");
    block.className = "detail-status";
    block.dataset.place = place;
    const text = document.createElement("p");
    text.className = "note";
    text.setAttribute("role", "status");
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "ghost small";
    retry.textContent = "重新取得驗算資料";
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
    const place = block.dataset.place;
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
    const controller = new AbortController();
    const token = lifecycle.beginRequest(controller);
    const timeout = lifecycle.scheduleAbort(
      controller, REQUEST_TIMEOUT_MS, window.setTimeout.bind(window)
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
    sectionsHost.querySelectorAll(".table-wrap").forEach((wrap) => {
      if (wrap.scrollWidth > wrap.clientWidth) {
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

  function buildSectionIndex(sections) {
    const host = el("section-index");
    host.replaceChildren();
    sections.forEach((section) => {
      const item = document.createElement("li");
      const link = document.createElement("a");
      link.href = `#section-${section.id}`;
      link.className = "index-link";
      link.dataset.ring = section.ring;

      const name = document.createElement("span");
      name.textContent = section.title;
      link.appendChild(name);

      if (section.status.state !== "present") {
        const flag = document.createElement("span");
        flag.className = "index-state";
        flag.dataset.state = section.status.state;
        flag.textContent = section.status.label;
        link.appendChild(flag);
      }
      item.appendChild(link);
      host.appendChild(item);
    });
    el("section-index-wrap").hidden = sections.length === 0;
  }

  function materializeSection(section) {
    const host = document.createElement("section");
    host.className = "result-section";
    host.id = `section-${section.id}`;
    lifecycle.registerSectionNode(host);

    const head = document.createElement("div");
    head.className = "head";

    const ring = document.createElement("span");
    ring.className = "ring-tag";
    ring.dataset.ring = section.ring;
    // 「RING I 天文事實」：英文那半段標 lang=en，中文語音才不會用中文規則念（WCAG 3.1.2）。
    const layerLatin = /^([A-Z][A-Z ]*[A-Z])(\s+)(.*)$/.exec(section.layer_label || "");
    if (layerLatin) {
      const en = document.createElement("span");
      en.lang = "en";
      en.textContent = layerLatin[1];
      ring.append(en, layerLatin[2] + layerLatin[3]);
    } else {
      ring.textContent = section.layer_label;
    }
    head.appendChild(ring);

    const title = document.createElement("h3");
    title.textContent = section.title;
    head.appendChild(title);

    const state = document.createElement("span");
    state.className = "state";
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
      const details = document.createElement("details");
      details.className = "long-section";
      const summary = document.createElement("summary");
      summary.textContent = `展開這一區（${rowCount} 列）`;
      details.appendChild(summary);
      host.appendChild(details);
      body = details;
    }

    section.children.forEach((child) => {
      const target = child.type === "note" && !collapsible ? host : body;
      if (child.type === "figure") {
        // 摘要圖與它的第一行永遠在摺疊之外（預設不得摺疊）。
        host.insertBefore(materializeFigure(child.figure), collapsible ? body : null);
      } else if (child.type === "note") {
        const note = document.createElement("p");
        note.className = "section-note";
        note.textContent = child.text;
        // 備註留在摺疊外面：使用者要在展開前就知道這一區在講什麼。
        (collapsible ? host : target).insertBefore(note, collapsible ? body : null);
      } else if (child.type === "block") {
        const block = document.createElement("p");
        block.className = "section-block";
        block.textContent = child.text;
        body.appendChild(block);
      } else if (child.type === "table") {
        body.appendChild(materializeTable(child, section.id, section.title));
      }
    });
    return host;
  }

  // 結果頂端的敏感度結論：一行，連到區段本身。null 時清空並隱藏。
  function renderSamplingCallout(callout) {
    samplingCalloutHost.replaceChildren();
    samplingCalloutHost.hidden = !callout;
    if (!callout) return;
    const link = document.createElement("a");
    link.href = `#${callout.target_id}`;
    link.textContent = callout.link_text;
    // 三段在畫面上靠 flex 間距分開，輔助科技讀的是連在一起的文字，
    // 「出生時刻敏感度這五個取樣點…」會讀成一句。標籤後補一個只給輔助科技的「：」，
    // 版面不變。
    const label = figureText("span", "sampling-callout-label", callout.label);
    label.append(figureText("span", "visually-hidden", "："));
    samplingCalloutHost.append(
      label,
      figureText("span", "sampling-callout-lead", callout.lead),
      link,
    );
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
    const host = document.createElement("div");
    host.className = "sampling";
    host.dataset.tone = figure.tone;

    host.appendChild(figureText("p", "sampling-lead", figure.lead));

    const marks = document.createElement("div");
    marks.className = "sampling-marks";
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
      const item = document.createElement("span");
      item.className = "sampling-mark";
      if (mark.representative) item.dataset.representative = "true";
      if (index === 0) item.dataset.edge = "first";
      if (index === figure.marks.length - 1) item.dataset.edge = "last";
      const dot = document.createElement("span");
      dot.className = "sampling-dot";
      item.append(dot, figureText("span", "sampling-time", mark.label));
      marks.appendChild(item);
      if (index < figure.marks.length - 1) {
        const gap = document.createElement("span");
        gap.className = "sampling-gap";
        if (mark.bands_after > 0) {
          gap.dataset.bands = String(mark.bands_after);
          const band = document.createElement("span");
          band.className = "sampling-gap-band";
          gap.append(band, figureText("span", "sampling-gap-count", mark.gap_label));
        }
        marks.appendChild(gap);
      }
    });
    host.appendChild(marks);
    // 逐點的時刻只給輔助科技，緊接在圖之後；明眼使用者從圖上的標籤讀同一份資訊。
    host.appendChild(figureText("p", "visually-hidden", figure.text_alternative));

    // 圖例只描述圖形，文字輸出不印（契約）；與備註分在兩個節點，畫面上仍是同一段。
    const note = document.createElement("p");
    note.className = "sampling-note";
    if (figure.legend) note.appendChild(figureText("span", "sampling-legend", figure.legend));
    if (figure.note) note.appendChild(document.createTextNode(figure.note));
    host.appendChild(note);

    figure.groups.forEach((group) => {
      const block = document.createElement("div");
      block.className = "sampling-group";
      block.dataset.tone = group.tone;
      block.appendChild(figureText("h4", "sampling-group-title", group.title));
      if (group.note) block.appendChild(figureText("p", "sampling-group-note", group.note));
      if (group.bands.length) {
        const list = document.createElement("ul");
        list.className = "sampling-bands";
        group.bands.forEach((band) => {
          const row = document.createElement("li");
          const glyph = document.createElement("span");
          glyph.className = "sampling-band";
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

  function materializeTable(model, sectionId, sectionTitle) {
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    // role／tabindex 由 applyOverflowRegions 依實際溢出決定，不在這裡寫死。
    wrap.dataset.regionLabel = [sectionTitle, model.title || "可橫向捲動的資料表"]
      .filter(Boolean).join("：");
    const table = document.createElement("table");
    if (sectionId) table.dataset.section = sectionId;
    if (model.title) {
      const caption = document.createElement("caption");
      caption.textContent = model.title;
      table.appendChild(caption);
    }
    const thead = document.createElement("thead");
    const headRow = document.createElement("tr");
    model.columns.forEach((column) => {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = column;
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    model.rows.forEach((row) => {
      const tr = document.createElement("tr");
      row.forEach((cell, index) => {
        // 第一格說明這一列是什麼（天體、步驟、項目），做成列標頭；報讀器讀到
        // 後面的數值時才知道屬於哪一列。
        const node = document.createElement(index === 0 ? "th" : "td");
        if (index === 0) node.scope = "row";
        node.textContent = cell;
        tr.appendChild(node);
      });
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
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

  document.querySelectorAll("[data-copy]").forEach((button) => {
    button.addEventListener("click", () => {
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
    });
  });

  document.querySelectorAll("[data-download]").forEach((button) => {
    button.addEventListener("click", () => {
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
        button.dataset.download,
        deliverArtifact,
        mode,
      );
      reportAt(
        button,
        outcome.ok
          ? `已產生 ${button.dataset.download.toUpperCase()} 檔案。`
          : `下載失敗：${outcome.error_message}`,
        outcome.ok ? "info" : "error"
      );
    });
  });

  function deliverArtifact(artifact) {
    const blob = new Blob([artifact.content], { type: artifact.mime_type });
    const url = URL.createObjectURL(blob);
    lifecycle.registerObjectUrl(url);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = artifact.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    // 同一個 task 內 revoke 會讓部分瀏覽器取消下載；排到下一個 task。
    // release 是冪等的，因此使用者若先按清除也不會重複撤銷。
    setTimeout(() => lifecycle.releaseObjectUrl(url), 0);
  }

  el("print-button").addEventListener("click", () => {
    try { requireExportableDocument(); }
    catch (error) { setStatus(`無法列印：${error.message}`, "error"); return; }
    window.print();
  });

  // 列印（含瀏覽器選單的列印與 Ctrl/⌘+P）前展開結果區所有
  // 摺疊區塊——技術細節、長區、收據與軌跡——否則存成的 PDF 只有摘要；
  // 列印後還原使用者原本的展開狀態。
  //
  // 瀏覽器選單與 Ctrl/⌘+P 不經過列印鈕，beforeprint 也無法取消列印，所以這裡
  // 套用與列印鈕、複製、下載同一個守衛（requireExportableDocument）：結果已不
  // 對應目前輸入時，標記 data-print-withheld，列印樣式只留下 stale 說明，不把
  // 改動前的結果當成目前的結果印出。
  let restorePrintExpansion = null;
  window.addEventListener("beforeprint", () => {
    if (restorePrintExpansion) restorePrintExpansion();
    restorePrintExpansion = null;
    clearPrintInputSummary();
    try {
      requireExportableDocument();
    } catch (_error) {
      results.dataset.printWithheld = "true";
      return;
    }
    delete results.dataset.printWithheld;
    fillPrintInputSummary();
    restorePrintExpansion = window.ChartExport.printExpansion(
      results.querySelectorAll("details")
    );
  });
  window.addEventListener("afterprint", () => {
    if (restorePrintExpansion) restorePrintExpansion();
    restorePrintExpansion = null;
    delete results.dataset.printWithheld;
    clearPrintInputSummary();
  });

  // ── 列印的輸入摘要 ──────────────────────────────────────
  //
  // 列印藏起表單，紙上只剩結果，看不出是哪一組輸入算的。列印前把表單上「畫面看得到」的值抄成
  // 一張摘要：被精度收起的時分秒、收起的手動座標不印，只印使用者已經在畫面上看到的東西。結果
  // 與輸入一致才會走到這裡（上面的匯出守衛），所以表單值就是算出這份結果的輸入。列印後清空，
  // 不在頁面上多留一份輸入。
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

  // ══ 兩種清除（匯出契約驗收 16）══════════════════════════
  function dropResultsForNewAttempt() {
    lifecycle.clear();
    clearPrintInputSummary();
    forgetDetailBinding();
    sectionSnapshots.clear();
    sectionsHost.replaceChildren();
    warningsHost.replaceChildren();
    renderSamplingCallout(null);
    results.hidden = true;
    boundInputSignature = null;
    currentViewTree = null;
    setStale(false);
    hideError();
  }

  function dropResults() {
    dropResultsForNewAttempt();
    submitButton.disabled = false;
  }

  function clearPlaceReceipt() {
    // 收據隱藏不等於清除：dl 裡的地名與座標仍在 DOM。
    el("place-receipt").hidden = true;
    el("place-receipt-body").replaceChildren();
    el("place-receipt-codes").replaceChildren();
    el("place-caveat").textContent = "";
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
    optionValues = Catalogue.defaults();
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
  }

  function clearSensitiveState() {
    resetFormState();
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
  buildOptionUi();
  applyPrecisionConsequences();
  applyZodiacConsequences();
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
