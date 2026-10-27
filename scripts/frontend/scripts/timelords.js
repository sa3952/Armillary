(function attachTimelords(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  // 畫面模型在 timelords-model.js，符號在 chart-glyphs.js，清除與中止在 privacy-lifecycle.js；頁面在本檔之前載入三者。
  const api = factory(
    commonJs ? require("./timelords-model.js") : root.ArmillaryTimelordsModel,
    commonJs ? require("./chart-glyphs.js") : root.ArmillaryChartGlyphs,
    commonJs ? require("./privacy-lifecycle.js") : root.PrivacyLifecycle,
  );
  if (commonJs) module.exports = api;
  if (root) root.ArmillaryTimelords = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildTimelords(Model, Glyphs, Lifecycle) {
  "use strict";

  // 計算頁「年度時間主星」一區的畫面與接線。
  //
  // 出生資料只有一個來源：畫面上那張本命盤送出的請求（calculate.js 交給 show()）。本區不另收任何資料、不寫網址（沒有
  // #hash、沒有 query）、不用任何瀏覽器儲存；結果清除、過期或離開頁面時，calculate.js 呼叫 drop()／setStale()，本區跟著
  // 丟棄或停用。所有日期都是伺服器給的出生地日期，本檔不換算日期。元素一律逐個建立，不經過 HTML 字串（Trusted Types）。

  const SVG_NS = "http://www.w3.org/2000/svg";
  const REQUEST_TIMEOUT_MS = 30000;
  const SCROLL_SETTLE_MS = 250;
  // 與 timelords.css 的抽屜斷點相同。
  const NARROW_QUERY = "(max-width: 1100px)";
  const MOBILE_QUERY = "(max-width: 640px)";
  const ZOOMS = Object.freeze([["life", "一生"], ["decade", "前後十年"], ["year", "本年度"]]);
  const VIEWS = Object.freeze([["timeline", "時間軸"], ["yearbook", "逐年年表"]]);
  const DAYS_PER_DECADE_VIEW = 3653;
  // 換了年度之後等一下才取：連按「下一年」時只取最後停下的那一年。
  const YEAR_FETCH_DELAY_MS = 300;
  // 暫時的失敗（伺服器忙、請求太多、連線斷了）稍後自動再試，間隔逐次加長，最多三次；其他失敗不再試。
  const RETRY_DELAYS_MS = Object.freeze([2000, 4000, 8000]);
  const MONTHS_PREFIX = "annual_profection/";
  // 排隊的按需請求以期間 id 為鍵：月小限掛在年度小限的期間下，其他是黃道釋放與十年期的大期。
  const isMonths = (id) => id.startsWith(MONTHS_PREFIX);
  /** 一份結果的按需狀態從空的開始：排隊、失敗、要收下月小限的年度、暫時失敗的再試次數。 */
  const freshLevel2 = () => ({ level2Queue: [], level2Failed: new Set(), monthsWanted: new Set(), level2Retries: new Map() });
  /** 太陽回歸盤一格的狀態：另一個地點的兩格字、請求中、取到的那一年（n）與畫面模型。 */
  const freshSolar = () => ({ latitude: "", longitude: "", houseSystem: "", loading: false, generation: 0, result: null });
  const ICS_MONTHS_PENDING = "這一年的月小限還在取；取到之後才能存檔，檔案裡才會有月小限。";
  const ICS_MONTHS_FAILED = "這一年的月小限沒有取到，存下的檔案裡不會有月小限。";

  function createPanel(options) {
    const doc = options.document;
    const win = options.window;
    const host = options.host;
    const postJson = options.postJson;
    const today = options.today;
    const now = options.now;
    const token = options.token;
    const describeError = options.describeError || (() => "年度時間主星沒有算出來。");
    // 站內連結指定的技法（計算頁從網址讀一次，見 result-chapters.js 的 techniqueFromQuery）：只決定
    // 先選哪一段，不改請求，也不記住到下次載入。
    let preferredTechnique = null;
    const lifecycle = Lifecycle.createSensitiveDataLifecycle({ revokeObjectUrl: (url) => win.URL.revokeObjectURL(url) });
    // 按需的第二層另用一個請求槽：同一個槽裡新請求會中止舊請求，共用時第二層會中止使用者按下的重排。
    const level2Lifecycle = Lifecycle.createSensitiveDataLifecycle({ revokeObjectUrl: (url) => win.URL.revokeObjectURL(url) });
    const el = (id) => doc.getElementById(id);
    const startButton = el("annual-load");
    const startNote = el("annual-start");
    // 十年期的起點：排出之前選；排出之後改了，「排出時間主星」再出現，按下才重新請求。
    const decennialsProfile = el("annual-dec-profile");
    const decennialsPlanet = el("annual-dec-planet");
    // 法達夜盤交點的排法與黃道釋放的一年：與十年期的起點同一種流程。
    const firdariaNode = el("annual-fir-node");
    const zrYear = el("annual-zr-year");
    const statusLine = el("annual-status");
    const body = el("annual-body");
    const state = {
      payload: null, stale: false, loading: false, data: null, model: null, sources: [], view: null, zoom: "decade",
      yearIndex: -1, selected: null, generation: 0, level2Generation: 0, level2Busy: false, ...freshLevel2(),
      returnFocus: null, decennials: null, firdariaNode: null, zrYear: null,
      // 年表各段十年使用者自己打開或收起的狀態（以該段第一個年度的索引為鍵）；重畫時照舊。
      openDecades: new Map(),
      // 手機年表裡使用者自己展開或收起的年度（以年度索引為鍵）；預設只展開選定的那一年。
      openYears: new Map(), solar: freshSolar(),
    };
    const solarReturn = createSolarReturn({ doc, win, state, el, node, titledSection, post, failureMessage, codeNote });
    const life = createLifeOverview({ doc, win, state, node, titledSection, onOpen: (id, trigger) => select(id, trigger) });
    // 伺服器沒有開年度路由（回 404／405）：這是部署狀態，不是這次輸入的問題。記住它，之後同一頁
    // 的每一張盤都直接顯示「尚未開放」，不再送出。
    let routeUnavailable = false;
    let scrollTimer = null;
    // 換年度後的延遲取用，與暫時失敗後的再試（期間 id → 計時器）。
    let yearTimer = null;
    const retryTimers = new Map();
    function node(tag, className, text) {
      const element = doc.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined && text !== null) element.textContent = text;
      return element;
    }
    /** 回應原值的代碼：標明是代碼、標英文，報讀器不把它當中文念；畫面上照字可查。 */
    function codeNote(code) {
      const wrap = node("span", "tl-code", "代碼 ");
      const value = node("code", null, code);
      value.lang = "en";
      wrap.appendChild(value);
      return wrap;
    }
    function glyph(key) {
      const entry = key && Glyphs.GLYPHS[key];
      if (!entry) return null;
      const [x0, , x1] = entry.bbox;
      const svg = doc.createElementNS(SVG_NS, "svg");
      svg.setAttribute("class", "tl-glyph");
      svg.setAttribute("viewBox", `${Math.round((x0 + x1) / 2) - 525} -810 1050 1050`);
      svg.setAttribute("aria-hidden", "true");
      svg.setAttribute("focusable", "false");
      const path = doc.createElementNS(SVG_NS, "path");
      path.setAttribute("d", entry.d);
      svg.appendChild(path);
      return svg;
    }
    function titledSection(className, id, title) {
      const section = node("section", className);
      section.setAttribute("aria-labelledby", id);
      const heading = node("h3", null, title);
      heading.id = id;
      return [section, heading];
    }
    function runs(parent, list) {
      (list || []).forEach((run) => {
        if (run === null || run === undefined || run === "") return;
        if (typeof run === "string") { parent.appendChild(doc.createTextNode(run)); return; }
        if (run.glyph) { const svg = glyph(run.glyph); if (svg) parent.appendChild(svg); return; }
        if (run.strong) { parent.appendChild(node("strong", null, run.strong)); return; }
        if (run.mono) { parent.appendChild(node("span", "tl-num", run.mono)); return; }
        if (run.small) { parent.appendChild(node("span", "tl-small", run.small)); }
      });
      return parent;
    }
    function matches(query) { return typeof win.matchMedia === "function" && win.matchMedia(query).matches; }
    function reducedMotion() { return matches("(prefers-reduced-motion: reduce)"); }
    function setStatus(message, tone) { statusLine.textContent = message; statusLine.dataset.tone = tone || "info"; }
    // 請求每個槽一次只有一個請求（重排在 state.loading 時不再送，第二層一次一個），所以槽裡的請求只會被 drop()、
    // setStale() 或重排開始時中止；那三處都會遞增對應的 generation，回呼只看 generation。
    function post(channel, requestBody) {
      const { controller, token: ticket, timeout: timer } = channel.beginTimedRequest(
        REQUEST_TIMEOUT_MS, win.setTimeout.bind(win), win.AbortController
      );
      // 網址照字寫在這裡：自我檢查頁依這一行列出本頁會送的請求。
      return postJson("/api/chart/annual?projection=page", requestBody, controller.signal)
        .catch((error) => ({ error, timedOut: timer.didTimeout() }))
        .finally(() => { win.clearTimeout(timer.handle); channel.finishRequest(ticket); });
    }
    /** 使用者看得懂的失敗訊息；其他例外（程式錯誤）只顯示通用的一句，不把例外原文放上畫面。 */
    function plainFailure(message) { const error = new Error(message); error.plain = true; return error; }
    /** 停掉所有按需的第二層：排隊的丟掉、路上的中止，之後回來的回應因 generation 不符而忽略。 */
    function stopLevel2() {
      state.level2Generation += 1;
      level2Lifecycle.abortActiveRequest();
      state.level2Queue = [];
      state.level2Busy = false;
      clearLevel2Timers();
    }
    function clearLevel2Timers() {
      if (yearTimer !== null) { win.clearTimeout(yearTimer); yearTimer = null; }
      retryTimers.forEach((handle) => win.clearTimeout(handle));
      retryTimers.clear();
    }
    function failureMessage(result) {
      if (result.error) {
        return result.timedOut ? `等待超過 ${REQUEST_TIMEOUT_MS / 1000} 秒，已停止等待。`
          : "沒有送達本站的計算功能。請確認網路連線後再試一次。";
      }
      const status = result.response ? result.response.status : 0;
      return describeError(result.body, status);
    }
    function decennialsChoice() {
      const profile = decennialsProfile ? decennialsProfile.value : Model.DECENNIALS_START_PROFILES[0];
      const planet = decennialsPlanet ? decennialsPlanet.value : null;
      return { profile, planet: profile === Model.DECENNIALS_START_PROFILES[2] ? planet : null };
    }
    function refreshDecennialsControls() {
      if (!decennialsPlanet) return;
      const wanted = Boolean(decennialsProfile) && decennialsProfile.value === Model.DECENNIALS_START_PROFILES[2];
      decennialsPlanet.disabled = !wanted;
      const wrap = decennialsPlanet.closest(".annual-dec-planet");
      if (wrap) wrap.hidden = !wanted;
    }
    // 法達夜盤交點的排法與黃道釋放的一年：選單上的值（預設是閉集的第一個）。
    function methodChoices() {
      return {
        firdariaNode: firdariaNode ? firdariaNode.value : Model.FIRDARIA_NODE_PROFILES[0],
        zrYear: zrYear ? zrYear.value : Model.ZR_YEAR_MODELS[0],
      };
    }
    // 手機上選單只有約 300 px 寬，長的選項字被截掉：窄螢幕改用短字（option 的 label），完整的字
    // 照舊在 option 裡，選定那一項的完整字另由 aria-describedby 交給輔助科技。寬螢幕時拿掉短字。
    const shortLabelled = [
      [decennialsProfile, Model.DECENNIALS_START_SHORT], [firdariaNode, Model.METHOD_CHOICE_SHORT], [zrYear, Model.METHOD_CHOICE_SHORT],
    ].filter(([control]) => control).map(([control, shorts]) => {
      const full = node("span", "visually-hidden");
      full.id = `${control.id}-full`;
      control.insertAdjacentElement("afterend", full);
      return { control, shorts, full };
    });
    function syncOptionLabels() {
      const narrow = matches(MOBILE_QUERY);
      shortLabelled.forEach(({ control, shorts, full }) => {
        [...control.options].forEach((option) => {
          const short = shorts[option.value];
          if (narrow && short) option.label = short;
          else option.removeAttribute("label");
        });
        const chosen = control.selectedOptions[0];
        full.textContent = narrow && chosen ? chosen.textContent : "";
        if (narrow) control.setAttribute("aria-describedby", full.id);
        else control.removeAttribute("aria-describedby");
      });
    }
    function onChoiceChange() {
      syncOptionLabels();
      refreshDecennialsControls();
      if (!state.model || state.loading) return;
      const choice = decennialsChoice();
      const methods = methodChoices();
      const changed = [];
      if (!(state.decennials && choice.profile === state.decennials.profile && choice.planet === state.decennials.planet)) {
        changed.push("十年期的起點");
      }
      if (methods.firdariaNode !== state.firdariaNode) changed.push("法達夜盤交點的排法");
      if (methods.zrYear !== state.zrYear) changed.push("黃道釋放的一年");
      startNote.hidden = !changed.length;
      setStatus(changed.length ? `${changed.join("、")}改了；按「排出時間主星」重新排出。` : "", "info");
    }
    function load() {
      if (!state.payload || state.stale || state.loading) return;
      // 舊起點的第二層與這次重排無關，先停掉；重排進行中也不送新的第二層（pumpLevel2）。
      stopLevel2();
      const generation = state.generation;
      const decennials = decennialsChoice();
      const methods = methodChoices();
      const todayDate = today();
      const birth = state.payload.datetime;
      const estimate = Model.estimateCompletedYears(birth, todayDate);
      state.loading = true;
      // 停用中的按鈕會丟掉鍵盤焦點（焦點掉回頁首）；算完後把焦點還給按鈕，或交給這一章的標題。
      const keyboardWasHere = document.activeElement === startButton;
      startButton.disabled = true;
      setStatus("計算中…", "info");
      const request = (years) => post(lifecycle, Model.annualRequestBody(state.payload, years, { decennials, ...methods }));
      async function fetchYear() {
        let years = estimate;
        for (let attempt = 0; ; attempt += 1) {
          const result = await request(years);
          if (!result.error && (result.response.status === 404 || result.response.status === 405)) return { unavailable: true };
          if (result.error || !result.response.ok || !result.body) throw plainFailure(failureMessage(result));
          const data = Model.adaptAnnualSource(result.body);
          if (attempt > 0) return { data, body: result.body };
          // 民用生日估的年度可能差一年（生日前後一天）：今天落在相鄰年度時，改請求那一年一次。
          const where = Model.locateToday(data, todayDate);
          if (where === "today_after_year") years += 1;
          else if (where === "today_before_year" && years > 0) years -= 1;
          else return { data, body: result.body };
        }
      }
      fetchYear().catch((failure) => ({ failure })).then((outcome) => {
        // 唯一的守衛：這段期間清除了結果、表單過期，或已有新的一次（drop／setStale 遞增 generation）。
        if (generation !== state.generation) return;
        state.loading = false;
        try {
          if (outcome.failure) throw outcome.failure;
          if (outcome.unavailable) { routeUnavailable = true; showUnavailable(); return; }
          showLoaded(outcome.data, decennials, methods, todayDate, outcome.body);
        } catch (error) {
          // 畫到一半失敗的區塊不留在畫面上；程式例外的原文不上畫面。
          Object.assign(state, { data: null, model: null, sources: [], selected: null, yearIndex: -1 });
          body.replaceChildren();
          body.hidden = true;
          let message = "年度時間主星沒有算出來。";
          if (error && error.plain) message = error.message;
          else if (error && typeof error.message === "string" && error.message.startsWith("年度回應形狀不符")) {
            message = "這個版本的頁面無法呈現這次的年度回應。請重新載入頁面。";
          }
          setStatus(message, "error");
        } finally {
          refreshControls();
          if (keyboardWasHere && (!document.activeElement || document.activeElement === document.body)) {
            if (!startButton.disabled) startButton.focus();
            // 按鈕在結果出來後收起（隱藏）時 focus() 不生效，改交給這一章的標題。
            if (document.activeElement !== startButton) {
              const heading = el("annual-heading");
              if (heading) { heading.tabIndex = -1; heading.focus(); }
            }
          }
        }
      });
    }
    function showLoaded(data, decennials, methods, todayDate, sourceBody) {
      const model = Model.buildModel(data, todayDate);
      // 一生視窗裡沒有任何算得出的年界（例如出生在可計算範圍的最後一年）：沒有年度可以畫。
      if (!model.years.length) {
        throw plainFailure("這張盤的年界超出本站可以計算的範圍（到西元 2399 年），排不出年度時間主星；本命盤的結果不受影響。");
      }
      state.decennials = decennials;
      state.firdariaNode = methods.firdariaNode;
      state.zrYear = methods.zrYear;
      // 排在舊結果上的按需請求（例如重排進行中換了年度）屬於舊的那一份，不帶到新結果；
      // 選過的年度（只有這幾年的月小限會從按需回應收下）也從頭記。
      Object.assign(state, freshLevel2());
      clearLevel2Timers();
      state.openDecades = new Map();
      state.openYears = new Map();
      state.data = data;
      state.model = model;
      // 時間主星表的 JSON 原樣附上頁面收到的每一份年度回應：這一份，加上之後按需取的那些。
      state.sources = [sourceBody];
      const requested = model.years.findIndex((year) => year.n === data.requestedYears);
      state.yearIndex = model.currentIndex >= 0 ? model.currentIndex : Math.max(0, requested);
      state.selected = defaultSelection();
      state.view = matches(MOBILE_QUERY) ? "yearbook" : "timeline";
      renderAll();
      setStatus("年度時間主星已算出。", "info");
      startNote.hidden = true;
      queueLevel2ForYear();
    }
    // 第二層（小期）按需取：只取選定年度與時間軸可見範圍裡、尚未載入的大期；一次一個請求。
    // 月小限只取選定的那一年，排在最前面：同一個請求也帶回那一年所在大期的第二層。
    function enqueueMissing(list) {
      list.forEach((missing) => {
        if (state.level2Failed.has(missing.id)) return;
        if (state.level2Queue.some((queued) => queued.id === missing.id)) return;
        state.level2Queue.push(missing);
      });
    }
    function queueLevel2(startDay, endDay) {
      if (!state.model || state.stale) return;
      enqueueMissing(Model.missingLevel2(state.model, startDay, endDay));
      pumpLevel2();
    }
    function queueLevel2ForYear() {
      const year = state.model && state.model.years[state.yearIndex];
      if (!year || state.stale) return;
      const parent = Model.monthsParentId(state.model, state.yearIndex);
      if (parent) state.monthsWanted.add(parent);
      // 排隊中其他年度的月小限不要了（路上的那一個照常回來）；選定年度的月小限排在最前面，
      // 接著是這一年所在大期的第二層。等著再試的那一段由它的計時器排回來。
      const months = Model.missingMonths(state.model, state.yearIndex)
        .filter((missing) => !state.level2Failed.has(missing.id) && !retryTimers.has(missing.id));
      state.level2Queue = [...months, ...state.level2Queue.filter((queued) => !isMonths(queued.id))];
      queueLevel2(year.startDay, year.endDay);
    }
    /** 換年度之後：先丟掉排隊中其他年度的月小限，等 YEAR_FETCH_DELAY_MS 沒有再換，才排這一年的請求。 */
    function queueLevel2ForYearSoon() {
      state.level2Queue = state.level2Queue.filter((queued) => !isMonths(queued.id));
      if (yearTimer !== null) win.clearTimeout(yearTimer);
      const generation = state.level2Generation;
      yearTimer = win.setTimeout(() => {
        yearTimer = null;
        if (generation === state.level2Generation) queueLevel2ForYear();
      }, YEAR_FETCH_DELAY_MS);
    }
    /** 暫時的失敗：過一陣子把這一段排回最前面；月小限只在仍是選定的那一年時才排回。 */
    function retryLater(item, delay) {
      const generation = state.level2Generation;
      const handle = win.setTimeout(() => {
        retryTimers.delete(item.id);
        if (generation !== state.level2Generation || !state.model || state.stale) return;
        if (state.data.level2LoadedFor.has(item.id)) return;
        if (isMonths(item.id) && item.id !== Model.monthsParentId(state.model, state.yearIndex)) return;
        if (!state.level2Queue.some((queued) => queued.id === item.id)) state.level2Queue.unshift(item);
        pumpLevel2();
      }, delay);
      retryTimers.set(item.id, handle);
    }
    /** 選定那一年的月小限：ready（已有或不必有）、pending（還在取）、failed（沒有取到）。 */
    function monthsState() {
      if (!state.model || state.yearIndex < 0) return "ready";
      const missing = Model.missingMonths(state.model, state.yearIndex);
      if (!missing.length) return "ready";
      return state.level2Failed.has(missing[0].id) ? "failed" : "pending";
    }
    function pumpLevel2() {
      // 換年度的延遲還沒過：先不送，等選定的那一年排到最前面。
      if (yearTimer !== null) return;
      if (state.loading || state.level2Busy || state.stale || !state.level2Queue.length) return;
      const next = state.level2Queue.shift();
      if (state.data.level2LoadedFor.has(next.id)) { pumpLevel2(); return; }
      const generation = state.level2Generation;
      const months = isMonths(next.id);
      state.level2Busy = true;
      setStatus(months ? "正在取這一年的月小限…" : "正在取這一段的第二層…", "info");
      post(level2Lifecycle, Model.annualRequestBody(state.payload, next.n, { level2Only: true, decennials: state.decennials, zrYear: state.zrYear })).then((result) => {
        // 唯一的守衛：清除、表單過期或重排開始時 stopLevel2() 遞增 level2Generation。
        if (generation !== state.level2Generation) return;
        state.level2Busy = false;
        try {
          if (result.error || !result.response.ok || !result.body) {
            const what = months ? "這一年的月小限" : "第二層";
            const code = result.response ? result.response.status : 0;
            const tries = state.level2Retries.get(next.id) || 0;
            if ((result.error || code === 429 || code >= 500) && tries < RETRY_DELAYS_MS.length) {
              state.level2Retries.set(next.id, tries + 1);
              retryLater(next, RETRY_DELAYS_MS[tries]);
              setStatus(`${what}沒有取到，稍後會自動再試：${failureMessage(result)}`, "error");
            } else {
              state.level2Failed.add(next.id);
              setStatus(`${what}沒有取到：${failureMessage(result)}`, "error");
              if (months) refreshAfterLevel2();
            }
          } else {
            const extra = Model.adaptAnnualSource(result.body);
            state.data = Model.mergeLevel2(state.data, extra, { monthsFor: state.monthsWanted });
            state.sources = state.sources.concat([result.body]);
            if (!state.data.level2LoadedFor.has(next.id)) state.level2Failed.add(next.id);
            state.model = Model.buildModel(state.data, state.model.today);
            refreshAfterLevel2();
            setStatus("", "info");
          }
        } catch (error) {
          state.level2Failed.add(next.id);
          // 版本或出處清單與已載入的不同，也是形狀不符：只有重新載入頁面才會一致。
          const reload = error && typeof error.message === "string" && error.message.startsWith("年度回應形狀不符");
          setStatus(`這個版本的頁面無法呈現這次的第二層回應。${reload ? "請重新載入頁面。" : ""}`, "error");
        }
        pumpLevel2();
      });
    }
    function defaultSelection() { return Model.preferredSelection(state.model, state.yearIndex, preferredTechnique); }
    function select(id, trigger) {
      if (!state.model.byId.has(id)) return;
      state.selected = id;
      state.returnFocus = trigger || null;
      markSelection();
      renderDetail();
      openDrawer(Boolean(trigger));
    }
    function markSelection() {
      // 只改真的變了的那幾個：年表一打開就有上百個按鈕，同值重寫也會讓樣式重算。
      body.querySelectorAll("[data-item]").forEach((button) => {
        const pressed = String(button.dataset.item === state.selected);
        if (button.getAttribute("aria-pressed") !== pressed) button.setAttribute("aria-pressed", pressed);
      });
    }
    /** 焦點元素的身分：同一段期間（data-item 加類別）或同一個具名控制項，重畫後用它找回。 */
    function focusIdentity(element) {
      if (!element || !body.contains(element)) return null;
      // 跨好幾年的期間在年表每一年各有一格（同一個 data-item）：連同年列一起記。
      if (element.dataset && element.dataset.item) {
        return { item: element.dataset.item, kind: element.classList[0], year: element.dataset.year };
      }
      if (element.id) return { id: element.id };
      const decade = element.closest && element.closest("details.tl-decade");
      if (decade && element.tagName === "SUMMARY") return { decade: decade.dataset.start };
      return null;
    }
    function findByIdentity(identity) {
      if (!identity) return null;
      if (identity.id) return el(identity.id);
      if (identity.decade !== undefined) return body.querySelector(`details.tl-decade[data-start="${identity.decade}"] > summary`);
      return [...body.querySelectorAll("[data-item]")]
        .find((candidate) => candidate.dataset.item === identity.item && candidate.classList[0] === identity.kind
          && candidate.dataset.year === identity.year) || null;
    }
    // 第二層回來：只換掉摘要卡與主欄（時間軸或年表），細節欄（手機的抽屜）不動；焦點、捲動位置與使用者打開的十年照舊。
    function refreshAfterLevel2() {
      const main = body.querySelector(".tl-main");
      const oldSummary = body.querySelector(".tl-summary");
      if (!main || !oldSummary) { renderAll({ keepScroll: true }); return; }
      const identity = focusIdentity(doc.activeElement);
      // 抽屜開著時焦點在抽屜裡，關上時要回去的那一格也會被重畫取代：記下它是哪一段，重畫後換成新的那一格。
      const returnIdentity = focusIdentity(state.returnFocus);
      const scroller = body.querySelector(".tl-scroll");
      const keepLeft = scroller ? scroller.scrollLeft : null;
      const bookWraps = [...body.querySelectorAll("details.tl-decade")].map((details) => [details.dataset.start,
        details.querySelector(".tl-book-wrap") ? details.querySelector(".tl-book-wrap").scrollLeft : 0]);
      oldSummary.replaceWith(summary());
      main.replaceChildren(state.view === "timeline" ? timeline() : yearbook());
      if (state.view === "timeline") positionTimeline(keepLeft);
      bookWraps.forEach(([start, left]) => {
        const wrap = body.querySelector(`details.tl-decade[data-start="${start}"] .tl-book-wrap`);
        if (wrap) wrap.scrollLeft = left;
      });
      if (returnIdentity) state.returnFocus = findByIdentity(returnIdentity);
      const again = findByIdentity(identity);
      if (again && again !== doc.activeElement) {
        if (again.classList.contains("tl-seg-item")) {
          again.closest(".tl-lane").querySelectorAll(".tl-seg-item").forEach((candidate) => { candidate.tabIndex = -1; });
          again.tabIndex = 0;
        }
        again.focus({ preventScroll: true });
      }
      refreshControls();
    }
    function renderAll(opts = {}) {
      const scroller = body.querySelector(".tl-scroll");
      const keepLeft = opts.keepScroll && scroller ? scroller.scrollLeft : null;
      body.replaceChildren();
      body.hidden = false;
      const model = state.model;
      if (!model.lanes.length) { life.stop(); renderUnavailableOnly(); return; }
      const lifeBox = life.section();
      if (lifeBox) body.appendChild(lifeBox);
      body.append(viewSwitch(), yearNav(), summary(), node("p", "tl-reference note", Model.referenceNote(model, state.yearIndex)));
      warnings().forEach((notice) => body.appendChild(notice));
      const samples = sampleBox();
      if (samples) body.appendChild(samples);
      const layout = node("div", "tl-layout");
      const main = node("div", "tl-main");
      main.appendChild(state.view === "timeline" ? timeline() : yearbook());
      const detail = node("aside", "tl-detail");
      detail.id = "annual-detail";
      detail.setAttribute("aria-labelledby", "annual-detail-title");
      layout.append(main, detail);
      body.append(layout, ...(Model.supportsSolarReturn(state.sources[0]) ? [solarReturn.box()] : []),
        exportBox(), tableExportBox(), conventionsBox());
      renderDetail();
      refreshControls();
      if (lifeBox) life.draw();
      if (state.view === "timeline") positionTimeline(keepLeft);
    }
    // 換年：只換掉跟著年度變的部分（年度列、摘要卡、參考說明、主欄、細節欄、行事曆檔與回歸盤兩格），
    // 呈現方式、注意事項、取樣說明、時間主星表、慣例與延伸點不動。
    function refreshForYear(opts) {
      const parts = [".tl-year-nav", ".tl-summary", ".tl-reference", ".tl-main", "#annual-detail", ".tl-export:not(.tl-table-export)"]
        .map((selector) => body.querySelector(selector));
      const solar = body.querySelector(".tl-box.tl-sr");
      if (parts.some((part) => !part) || (!solar && Model.supportsSolarReturn(state.sources[0]))) { renderAll(opts); return; }
      const [nav, oldSummary, reference, main, oldDetail, ics] = parts;
      const scroller = body.querySelector(".tl-scroll");
      const keepLeft = opts.keepScroll && scroller ? scroller.scrollLeft : null;
      nav.replaceWith(yearNav());
      oldSummary.replaceWith(summary());
      reference.replaceWith(node("p", "tl-reference note", Model.referenceNote(state.model, state.yearIndex)));
      main.replaceChildren(state.view === "timeline" ? timeline() : yearbook());
      const detail = node("aside", "tl-detail");
      detail.id = "annual-detail";
      detail.setAttribute("aria-labelledby", "annual-detail-title");
      oldDetail.replaceWith(detail);
      if (solar) solar.replaceWith(solarReturn.box());
      ics.replaceWith(exportBox());
      renderDetail();
      refreshControls();
      if (state.view === "timeline") positionTimeline(keepLeft);
    }
    function renderUnavailableOnly() {
      const [box, heading] = titledSection("tl-box tl-unavailable", "annual-unavailable-title", "這張盤沒有畫出時間軸");
      box.appendChild(heading);
      box.appendChild(node("p", "note", "這些時間技法都要從出生時刻算起；只知道出生日期時，畫面直接說明原因，不畫空的時間軸。"));
      Model.unavailableTechniques(state.model).forEach((entry) => {
        const item = node("p", "tl-na");
        item.append(node("strong", null, `${entry.title}：沒有算。`), doc.createTextNode(entry.text));
        item.appendChild(codeNote(entry.code));
        box.appendChild(item);
      });
      body.append(box, conventionsBox());
    }
    function segmented(label, entries, current, onPick, className) {
      const group = node("div", `tl-seg ${className || ""}`.trim());
      group.setAttribute("role", "group");
      group.setAttribute("aria-label", label);
      entries.forEach(([value, text]) => {
        const button = node("button", null, text);
        button.type = "button";
        button.dataset.value = value;
        button.setAttribute("aria-pressed", String(value === current));
        button.addEventListener("click", () => onPick(value));
        group.appendChild(button);
      });
      return group;
    }
    function viewSwitch() {
      const wrap = node("div", "tl-view-switch");
      wrap.appendChild(node("span", "tl-dim", "呈現方式"));
      wrap.appendChild(segmented("呈現方式", VIEWS, state.view, (value) => {
        if (state.view === value) return;
        state.view = value;
        renderAll();
        const pressed = body.querySelector(`.tl-view-switch button[data-value="${value}"]`);
        if (pressed) pressed.focus();
      }));
      return wrap;
    }
    function yearNav() {
      const model = state.model;
      const nav = node("div", "tl-year-nav");
      nav.setAttribute("role", "group");
      nav.setAttribute("aria-label", "選擇年度");
      // 手機上只剩箭頭（「‹ 年 ›」一列三欄）；字留給輔助科技（timelords.css 的 .tl-nav-word）。
      const prev = navButton("‹", "上一年", true);
      prev.type = "button";
      prev.id = "annual-prev-year";
      prev.disabled = state.yearIndex <= 0;
      prev.addEventListener("click", () => moveYear(-1, prev.id));
      const title = node("span", "tl-year-title", Model.yearTitle(model, state.yearIndex));
      title.id = "annual-year-title";
      title.setAttribute("aria-live", "polite");
      const next = navButton("›", "下一年", false);
      next.type = "button";
      next.id = "annual-next-year";
      next.disabled = state.yearIndex >= model.years.length - 1;
      next.addEventListener("click", () => moveYear(1, next.id));
      const back = node("button", "tl-nav-today", "回到今年");
      back.type = "button";
      back.id = "annual-this-year";
      back.disabled = model.currentIndex < 0 || state.yearIndex === model.currentIndex;
      back.addEventListener("click", () => moveYear(model.currentIndex - state.yearIndex, back.id));
      const range = runs(node("span", "tl-year-range"), Model.yearRange(model, state.yearIndex));
      nav.append(prev, title, next, back, range);
      return nav;
    }
    /** 上一年／下一年：箭頭加一段字；窄螢幕只藏字的外觀，名稱仍是「‹ 上一年」。 */
    function navButton(arrow, word, before) {
      const button = node("button", "tl-nav-step");
      const text = node("span", "tl-nav-word", word);
      if (before) button.append(doc.createTextNode(`${arrow} `), text);
      else button.append(text, doc.createTextNode(` ${arrow}`));
      return button;
    }
    function moveYear(delta, focusId) {
      const target = state.yearIndex + delta;
      if (target < 0 || target >= state.model.years.length || delta === 0) return;
      state.yearIndex = target;
      state.openDecades.delete(target - (target % 10));
      state.openYears.delete(target);
      const pick = Model.preferredSelection(state.model, target, preferredTechnique);
      if (pick) state.selected = pick;
      refreshForYear({ keepScroll: state.zoom === "life" });
      const again = el(focusId);
      if (again && !again.disabled) again.focus();
      else { const title = el("annual-year-title"); if (title) { title.tabIndex = -1; title.focus(); } }
      queueLevel2ForYearSoon();
    }
    function summary() {
      const grid = node("div", "tl-summary");
      grid.setAttribute("role", "group");
      grid.setAttribute("aria-label", state.yearIndex === state.model.currentIndex ? "今年" : Model.yearTitle(state.model, state.yearIndex));
      Model.summaryTiles(state.model, state.yearIndex).forEach((tile) => {
        const card = node(tile.select ? "button" : "div", "tl-tile");
        if (tile.select) {
          card.type = "button";
          card.dataset.item = tile.select;
          card.setAttribute("aria-controls", "annual-detail");
          card.addEventListener("click", () => select(tile.select, card));
        }
        const parts = [
          node("span", "tl-tile-key", tile.title), runs(node("span", "tl-tile-value"), tile.value),
          runs(node("span", "tl-tile-sub"), tile.sub),
        ];
        if (tile.gloss) parts.push(node("span", "tl-tile-gloss", tile.gloss));
        card.append(...parts);
        if (tile.select) {
          // 按鈕的名稱只是「技法：主星」；其下的期間與名詞解釋是描述，不併進名稱（否則一顆按鈕念兩百字）。
          parts.forEach((part, index) => { part.id = `annual-tile-${tile.key}-${index}`; });
          card.setAttribute("aria-labelledby", parts.slice(0, 2).map((part) => part.id).join(" "));
          if (parts.length > 2) card.setAttribute("aria-describedby", parts.slice(2).map((part) => part.id).join(" "));
        }
        grid.appendChild(card);
      });
      return grid;
    }
    function warnings() {
      return Model.warningNotices(state.model).map((warning) => {
        const notice = node("p", "tl-notice");
        notice.append(node("strong", null, "注意："), doc.createTextNode(warning.text));
        notice.appendChild(codeNote(warning.code));
        return notice;
      });
    }
    function sampleBox() {
      const summaryData = Model.sampleSummary(state.model);
      if (!summaryData) return null;
      const [box, heading] = titledSection("tl-box tl-samples", "annual-samples-title", "出生時間只知道到小時");
      box.appendChild(heading);
      box.appendChild(node("p", "note", "本站對這一小時的開頭、中間、結尾三個時刻各算一次。三個時刻相同的技法照常畫成一條；不同的技法畫成三條並列，標明哪一條對應哪個時刻，不合併、也不替你挑一個。"));
      const list = node("ul", "tl-sample-list");
      summaryData.techniques.forEach((entry) => {
        list.appendChild(node("li", null, `${entry.title}：${entry.differs ? "三個時刻不同，並列三條" : "三個時刻相同"}`));
      });
      box.appendChild(list);
      const times = summaryData.samples.filter((sample) => sample.localTime);
      if (times.length) {
        box.appendChild(node("p", "note", `三個時刻：${times.map((sample) => `${sample.title} ${sample.localTime}`).join("；")}。`));
      }
      return box;
    }
    function timeline() {
      const model = state.model;
      const [section, heading] = titledSection("tl-timeline", "annual-timeline-title", "一生的時間軸");
      const head = node("div", "tl-panel-title");
      head.append(heading, node("span", "note", "橫向捲動瀏覽；點任何一段看起訖、主星與算法。鍵盤：左右鍵換一段，上下鍵換到上一排或下一排。"));
      section.appendChild(head);
      const toolbar = node("div", "tl-toolbar");
      toolbar.appendChild(node("span", "tl-dim", "範圍"));
      toolbar.appendChild(segmented("時間軸範圍", ZOOMS, state.zoom, (value) => {
        state.zoom = value;
        renderAll();
        const pressed = body.querySelector(`.tl-toolbar button[data-value="${value}"]`);
        if (pressed) pressed.focus();
      }));
      section.appendChild(toolbar);
      const frame = node("div", "tl-frame");
      const labels = node("div", "tl-labels");
      labels.setAttribute("aria-hidden", "true");
      const axisLabel = node("div", "tl-axis-label", "足歲");
      axisLabel.append(doc.createElement("br"), doc.createTextNode("年界日期"));
      labels.appendChild(axisLabel);
      const scroll = node("div", "tl-scroll");
      const canvas = node("div", "tl-canvas");
      // 刻度只是畫面上的尺：每一段的名稱已寫明起訖日期，報讀器不必再念一串「0 1990 1 1991」。
      const axisRow = node("div", "tl-axis");
      axisRow.setAttribute("aria-hidden", "true");
      canvas.appendChild(axisRow);
      let previousGroup = null;
      model.lanes.forEach((lane) => {
        const first = lane.group !== previousGroup;
        previousGroup = lane.group;
        const label = node("div", `tl-lane-label level-${Math.min(lane.level, 2)}${first ? " first" : ""}`);
        const name = node("b");
        name.append(node("span", "tl-long", lane.title), node("span", "tl-short", lane.short));
        label.append(name, node("small", null, lane.subtitle));
        labels.appendChild(label);
        const row = node("div", `tl-lane level-${Math.min(lane.level, 2)}${first ? " first" : ""}`);
        row.setAttribute("role", "group");
        row.setAttribute("aria-label", lane.title);
        row.dataset.lane = lane.id;
        lane.items.forEach((item, index) => row.appendChild(segmentButton(lane, item, index)));
        canvas.appendChild(row);
      });
      scroll.appendChild(canvas);
      frame.append(labels, scroll);
      section.appendChild(frame);
      scroll.addEventListener("scroll", onTimelineScroll, { passive: true });
      canvas.addEventListener("keydown", onTimelineKey);
      const legend = node("div", "tl-legend");
      [
        ["tl-lg-today", "今天"], ["tl-lg-year", "年界（每年太陽回到出生位置的時刻）"],
        ["tl-lg-loose", "解鎖（輪完一圈跳到對宮）"], ["tl-lg-trunc", "被上一層截斷"], ["tl-lg-node", "交點期不分子期"],
      ].forEach(([className, text]) => {
        const entry = node("span");
        entry.append(node("i", className), doc.createTextNode(text));
        legend.appendChild(entry);
      });
      section.appendChild(legend);
      section.appendChild(node("p", "note", `底色只用兩種紙色交替，分辨相鄰兩段；顏色不代表任何好壞。期間起訖只到「日」：原典只給年數，分秒是假精度。日期是${Model.DATE_NOTE}。`));
      return section;
    }
    function segmentButton(lane, item, index) {
      const button = node("button", `tl-seg-item${index % 2 ? " alt" : ""}${item.kind === "node" ? " node" : ""}${item.truncated ? " trunc" : ""}${item.kind === "loosing" ? " loose" : ""}`);
      button.type = "button";
      button.dataset.item = item.id;
      button.dataset.start = String(item.startDay);
      button.dataset.end = String(item.endDay);
      button.tabIndex = -1;
      button.setAttribute("aria-pressed", String(item.id === state.selected));
      button.setAttribute("aria-controls", "annual-detail");
      const marks = [item.kind === "loosing" ? "解鎖" : "", item.truncated ? "被上一層截斷" : ""].filter(Boolean);
      button.setAttribute("aria-label", `${lane.title}：${item.label}，${item.start.localDate} 到 ${item.end.localDate}${marks.length ? `，${marks.join("，")}` : ""}`);
      const label = node("span", "tl-seg-label");
      const svg = glyph(item.glyph);
      if (svg) label.appendChild(svg);
      label.appendChild(node("span", "tl-seg-text", item.label));
      button.dataset.labelLength = String([...(item.label || "")].length);
      button.appendChild(label);
      if (item.kind === "loosing") {
        button.appendChild(node("span", "tl-loose-mark"));
        button.appendChild(node("span", "tl-loose-text", "解鎖"));
      }
      if (item.startDay <= state.model.todayDay && state.model.todayDay < item.endDay) button.classList.add("now");
      button.addEventListener("click", () => select(item.id, button));
      return button;
    }
    function pixelsPerDay(width) {
      const model = state.model;
      if (state.zoom === "life") return width / Math.max(1, model.domain.endDay - model.domain.startDay);
      if (state.zoom === "decade") return width / DAYS_PER_DECADE_VIEW;
      const year = model.years[state.yearIndex];
      return width / Math.max(1, (year.endDay - year.startDay) * 1.16);
    }
    /** 量出捲動區寬度後才排位置；排版只用日序，不換算任何日期。 */
    function positionTimeline(keepLeft) {
      const model = state.model;
      const scroll = body.querySelector(".tl-scroll");
      const canvas = body.querySelector(".tl-canvas");
      if (!scroll || !canvas) return;
      const width = Math.max(240, scroll.clientWidth || 0);
      const ppd = pixelsPerDay(width);
      const domain = model.domain;
      const x = (day) => (Math.min(Math.max(day, domain.startDay), domain.endDay) - domain.startDay) * ppd;
      const total = Math.ceil((domain.endDay - domain.startDay) * ppd);
      canvas.style.width = `${total}px`;
      const axis = canvas.querySelector(".tl-axis");
      // 刻度先每年畫一個，量出最寬的標籤（字型由瀏覽器決定，Linux 的 Noto 比 macOS 寬），再只留每 step 年一個：
      // 相鄰兩個標籤之間至少放得下一個標籤。固定的「每 10 年一格」在窄的主欄或寬的字型下會讓年份疊成「1981988199…」。
      axis.replaceChildren();
      const ticks = model.years.map((year) => {
        const tick = node("div", "tl-tick");
        tick.style.left = `${x(year.startDay)}px`;
        tick.appendChild(node("b", null, `${year.n}`));
        tick.appendChild(doc.createElement("br"));
        tick.appendChild(doc.createTextNode(state.zoom === "year"
          ? `${year.start.localDate} ${year.start.localTime || ""}`.trim() : year.start.localDate.slice(0, 4)));
        axis.appendChild(tick);
        return [year, tick];
      });
      const widest = Math.max(0, ...ticks.map(([, tick]) => tick.scrollWidth || 0));
      // 量不到寬度（尚未排版）時以字數估：數字約 0.6em。
      const labelPx = widest > 0 ? widest + 6 : (state.zoom === "year" ? 17 : 5) * 14 * 0.6 + 6;
      const yearPx = 365.25 * ppd;
      const step = [1, 2, 5, 10, 20, 25, 50].find((every) => every * yearPx >= labelPx) || 50;
      ticks.forEach(([year, tick]) => { if (year.n % step) tick.remove(); });
      canvas.querySelectorAll(".tl-seg-item").forEach((button) => {
        const start = Number(button.dataset.start);
        const end = Number(button.dataset.end);
        const visible = start < domain.endDay;
        button.hidden = !visible;
        if (!visible) return;
        const left = x(start);
        const w = Math.max(1, x(end) - left);
        button.style.left = `${left}px`;
        button.style.width = `${w}px`;
        button.dataset.size = Model.segmentSize(w, Number(button.dataset.labelLength) || 0);
      });
      canvas.querySelectorAll(".tl-vline").forEach((line) => line.remove());
      const vline = (className, day, text) => {
        const line = node("div", `tl-vline ${className}`);
        line.style.left = `${x(day)}px`;
        line.setAttribute("aria-hidden", "true");
        if (text) line.appendChild(node("span", null, text));
        canvas.appendChild(line);
      };
      if (state.zoom !== "life") model.years.forEach((year) => vline("year", year.startDay, null));
      const year = model.years[state.yearIndex];
      vline("selected", year.startDay, `第 ${year.n + 1} 年起`);
      vline("selected", year.endDay, null);
      if (model.todayDay >= domain.startDay && model.todayDay <= domain.endDay) vline("today", model.todayDay, `今天 ${model.today}`);
      refreshRovingStops();
      if (keepLeft !== null && keepLeft !== undefined) { scroll.scrollLeft = keepLeft; } else if (state.zoom === "life") {
        scroll.scrollLeft = 0;
      } else {
        const centre = state.yearIndex === model.currentIndex && state.zoom !== "year" ? model.todayDay : (year.startDay + year.endDay) / 2;
        scroll.scrollLeft = Math.max(0, x(centre) - width / 2);
      }
    }
    // 每條泳道只有一個 Tab 停點：選取中的那段，否則是參考日那一段，否則第一段。
    function refreshRovingStops() {
      const model = state.model;
      const reference = Model.referenceDay(model, state.yearIndex);
      body.querySelectorAll(".tl-lane").forEach((row) => {
        const buttons = [...row.querySelectorAll(".tl-seg-item:not([hidden])")];
        buttons.forEach((button) => { button.tabIndex = -1; });
        const stop = buttons.find((button) => button.dataset.item === state.selected)
          || buttons.find((button) => Number(button.dataset.start) <= reference && reference < Number(button.dataset.end)) || buttons[0];
        if (stop) stop.tabIndex = 0;
      });
    }
    function onTimelineKey(event) {
      const button = event.target.closest && event.target.closest(".tl-seg-item");
      if (!button) return;
      const row = button.closest(".tl-lane");
      const buttons = [...row.querySelectorAll(".tl-seg-item:not([hidden])")];
      const index = buttons.indexOf(button);
      let target = null;
      if (event.key === "ArrowRight") target = buttons[index + 1];
      else if (event.key === "ArrowLeft") target = buttons[index - 1];
      else if (event.key === "Home") target = buttons[0];
      else if (event.key === "End") target = buttons[buttons.length - 1];
      else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        const rows = [...body.querySelectorAll(".tl-lane")];
        const other = rows[rows.indexOf(row) + (event.key === "ArrowDown" ? 1 : -1)];
        if (other) {
          const day = Number(button.dataset.start);
          const candidates = [...other.querySelectorAll(".tl-seg-item:not([hidden])")];
          target = candidates.find((candidate) => Number(candidate.dataset.start) <= day && day < Number(candidate.dataset.end))
            || candidates.find((candidate) => Number(candidate.dataset.start) >= day) || candidates[candidates.length - 1];
        }
      } else { return; }
      event.preventDefault();
      if (!target) return;
      row.querySelectorAll(".tl-seg-item").forEach((candidate) => { candidate.tabIndex = -1; });
      target.closest(".tl-lane").querySelectorAll(".tl-seg-item").forEach((candidate) => { candidate.tabIndex = -1; });
      target.tabIndex = 0;
      button.tabIndex = row.contains(target) ? -1 : 0;
      target.focus({ preventScroll: true });
      if (typeof target.scrollIntoView === "function") {
        target.scrollIntoView({ block: "nearest", inline: "nearest", behavior: reducedMotion() ? "auto" : "smooth" });
      }
    }
    function onTimelineScroll() {
      if (scrollTimer !== null) win.clearTimeout(scrollTimer);
      scrollTimer = win.setTimeout(() => {
        scrollTimer = null;
        if (!state.model || state.zoom === "life") return;
        const scroll = body.querySelector(".tl-scroll");
        if (!scroll) return;
        const width = Math.max(240, scroll.clientWidth || 0);
        const ppd = pixelsPerDay(width);
        const from = state.model.domain.startDay + scroll.scrollLeft / ppd;
        queueLevel2(Math.floor(from), Math.ceil(from + width / ppd));
      }, SCROLL_SETTLE_MS);
    }
    function yearbook() {
      const model = state.model;
      const [section, heading] = titledSection("tl-yearbook", "annual-yearbook-title", "逐年年表");
      const head = node("div", "tl-panel-title");
      head.append(heading, node("span", "note", "一列＝一個年度（從這次太陽回歸到下一次）。年中換期的寫在格內。"));
      section.appendChild(head);
      const groups = [];
      model.lanes.forEach((lane) => {
        let group = groups.find((candidate) => candidate.id === lane.group);
        if (!group) { group = { id: lane.group, lanes: [] }; groups.push(group); }
        group.lanes.push(lane);
      });
      const headings = groups.map((group) => groupTitle(group));
      // 手機上一年的格子要好幾個螢幕高：只展開選定的那一年，其他年度只留年度列，點一下展開。
      // 列印與桌機照舊全部展開（收起只在窄螢幕的畫面上生效，見 timelords.css）。
      const collapsible = matches(MOBILE_QUERY);
      for (let start = 0; start < model.years.length; start += 10) {
        const years = model.years.slice(start, start + 10);
        const indexes = years.map((_, offset) => start + offset);
        const details = node("details", "tl-decade");
        details.dataset.start = String(start);
        details.open = state.openDecades.has(start) ? state.openDecades.get(start) : indexes.includes(state.yearIndex);
        const first = years[0];
        const last = years[years.length - 1];
        details.appendChild(node("summary", null, `${first.n}–${last.n} 足歲（${first.start.localDate.slice(0, 4)}–${last.end.localDate.slice(0, 4)}）`));
        details.addEventListener("toggle", () => {
          state.openDecades.set(start, details.open);
          if (details.open) queueLevel2(first.startDay, last.endDay);
        });
        const table = node("table", "tl-book-table");
        table.appendChild(node("caption", "visually-hidden", `年表：${first.n}–${last.n} 足歲`));
        const thead = node("thead");
        const headRow = node("tr");
        const corner = node("th", null, "年度");
        corner.scope = "col";
        headRow.appendChild(corner);
        headings.forEach((text) => { const th = node("th", null, text); th.scope = "col"; headRow.appendChild(th); });
        thead.appendChild(headRow);
        const tbody = node("tbody");
        indexes.forEach((index) => {
          const year = model.years[index];
          const row = node("tr", index === model.currentIndex ? "is-current" : "");
          if (index === state.yearIndex) row.classList.add("is-selected");
          const th = node("th", "tl-book-year");
          th.scope = "row";
          const label = collapsible ? yearToggle(row, index) : th;
          label.appendChild(node("b", null, `第 ${year.n + 1} 年`));
          if (index === model.currentIndex) label.appendChild(node("span", "tl-now-tag", "今年"));
          label.appendChild(runs(node("span", "tl-book-sub"), [`${year.n} 足歲・`, { mono: year.start.localDate }, " 起"]));
          if (label !== th) th.appendChild(label);
          row.appendChild(th);
          groups.forEach((group, column) => {
            const cell = node("td");
            cell.dataset.h = headings[column];
            group.lanes.forEach((lane) => cell.appendChild(bookLine(lane, index)));
            row.appendChild(cell);
          });
          tbody.appendChild(row);
        });
        table.append(thead, tbody);
        const wrap = node("div", "tl-book-wrap");
        // 窄螢幕上年表在自己的框裡橫捲；框是有名字的區域，可以用鍵盤捲動。
        wrap.setAttribute("role", "region");
        wrap.setAttribute("aria-label", `年表：${first.n}–${last.n} 足歲`);
        wrap.tabIndex = 0;
        wrap.appendChild(table);
        details.appendChild(wrap);
        section.appendChild(details);
      }
      section.appendChild(node("p", "note", `日期是${Model.DATE_NOTE}。`));
      // 只在紙上出現：列印不展開收著的十年，也不為了列印向伺服器取第二層。
      section.appendChild(node("p", "note tl-print-note", "列印只印畫面上已展開的十年；收著的十年與還沒取到的第二層，列印時不會另外向伺服器取。"));
      return section;
    }
    /** 手機年表的年度列：整列標題是一個展開／收起的按鈕（aria-expanded），收起時藏起那一年的格子。 */
    function yearToggle(row, index) {
      const open = state.openYears.has(index) ? state.openYears.get(index) : index === state.yearIndex;
      const button = node("button", "tl-book-toggle");
      button.type = "button";
      button.id = `annual-book-year-${index}`;
      button.setAttribute("aria-expanded", String(open));
      row.classList.toggle("is-collapsed", !open);
      button.addEventListener("click", () => {
        const next = button.getAttribute("aria-expanded") !== "true";
        state.openYears.set(index, next);
        button.setAttribute("aria-expanded", String(next));
        row.classList.toggle("is-collapsed", !next);
      });
      return button;
    }
    function groupTitle(group) {
      const lane = group.lanes[0];
      if (lane.technique === "annual_profection") {
        return group.lanes.some((member) => member.technique === "monthly_profection") ? "年度小限／月小限" : "年度小限・年主星";
      }
      if (lane.technique === "firdaria") return "法達 主期／子期";
      if (lane.lot === "fortune") return "命運點 大期／小期";
      if (lane.lot === "spirit") return "精神點 大期／小期";
      if (lane.technique === "decennials") return "十年期 第一層／第二層";
      return lane.title;
    }
    function bookLine(lane, index) {
      const line = node("div", "tl-book-line");
      const items = Model.itemsInYear(state.model, lane.id, index);
      if (!items.length) {
        if (lane.lot && lane.level === 2) line.appendChild(node("span", "tl-dim", "（小期未載入）"));
        if (lane.technique === "decennials" && lane.level === 2) line.appendChild(node("span", "tl-dim", "（第二層未載入）"));
        if (lane.technique === "monthly_profection" && !lane.sampleRole) {
          const parent = Model.monthsParentId(state.model, index);
          line.appendChild(node("span", "tl-dim", parent && state.level2Failed.has(parent) ? "（沒有取到）" : "（選到這一年時列出）"));
        }
        return line;
      }
      items.forEach((item, position) => {
        const holder = position === 0 ? line : node("span", "tl-book-change");
        if (position === 0 && lane.prefix) holder.appendChild(node("span", "tl-prefix", lane.prefix));
        if (position > 0) {
          holder.append(doc.createTextNode("↳ "), node("span", "tl-num", item.start.localDate.slice(5)), doc.createTextNode(" 起 "));
        }
        const chip = node("button", `tl-chip${item.kind === "node" ? " node" : ""}`);
        chip.type = "button";
        chip.dataset.item = item.id;
        chip.dataset.year = String(index);
        chip.setAttribute("aria-pressed", String(item.id === state.selected));
        chip.setAttribute("aria-controls", "annual-detail");
        const svg = glyph(item.glyph);
        if (svg) chip.appendChild(svg);
        chip.appendChild(doc.createTextNode(item.label));
        if (item.aside) {
          chip.appendChild(doc.createTextNode(" → "));
          const lordGlyph = glyph(item.aside.glyph);
          if (lordGlyph) chip.appendChild(lordGlyph);
          chip.appendChild(doc.createTextNode(item.aside.label));
        }
        chip.addEventListener("click", () => select(item.id, chip));
        holder.appendChild(chip);
        if (item.kind === "loosing") holder.appendChild(node("span", "tl-mark", "解鎖"));
        if (item.truncated) holder.appendChild(node("span", "tl-mark dashed", "截斷"));
        if (position > 0) line.appendChild(holder);
      });
      return line;
    }
    function renderDetail() {
      const panel = el("annual-detail");
      if (!panel) return;
      panel.replaceChildren();
      const detail = state.selected ? Model.describeItem(state.model, state.selected) : null;
      const head = node("div", "tl-detail-head");
      const titleBox = node("div");
      const title = node("h3", null);
      title.id = "annual-detail-title";
      title.tabIndex = -1;
      const close = node("button", "ghost small tl-detail-close", "關閉");
      close.type = "button";
      close.addEventListener("click", closeDrawer);
      if (!detail) {
        title.textContent = "期間細節";
        titleBox.appendChild(title);
        head.append(titleBox, close);
        panel.append(head, node("p", "note tl-detail-body", "點時間軸或年表上的任何一段，這裡顯示起訖、主星、算法與收據。"));
        return;
      }
      titleBox.append(node("div", "tl-detail-kind", detail.kind), runs(title, detail.title));
      head.append(titleBox, close);
      const content = node("div", "tl-detail-body");
      const list = node("dl");
      detail.rows.forEach(([term, value]) => { list.append(node("dt", null, term), runs(node("dd"), value)); });
      content.appendChild(list);
      if (detail.explanation.length) content.appendChild(runs(node("p", "tl-explain"), detail.explanation));
      content.appendChild(node("p", "note", detail.dateNote));
      if (detail.sources.length) {
        // 與結果區的「出處」摺疊同一種外觀（calculate.css 的 .section-sources）；內容仍是這一段的出處。
        const sources = node("details", "tl-sources section-sources");
        sources.appendChild(node("summary", null, "出處"));
        const ul = node("ul");
        detail.sources.forEach((line) => ul.appendChild(node("li", null, line)));
        const more = node("li");
        const link = node("a", null, "方法頁");
        link.href = detail.methodHref || "/zh-TW/methods/time-lords";
        more.append(doc.createTextNode("完整出處與每一條核到哪一層見"), link, doc.createTextNode("。"));
        ul.appendChild(more);
        sources.appendChild(ul);
        content.appendChild(sources);
      }
      const receipt = node("details", "tl-receipt");
      receipt.appendChild(node("summary", null, "收據（回應原值）"));
      receipt.appendChild(node("pre", "mono", JSON.stringify(detail.receipt, null, 1)));
      content.appendChild(receipt);
      panel.append(head, content);
    }
    function openDrawer(fromUser) {
      const panel = el("annual-detail");
      if (!panel || !matches(NARROW_QUERY)) return;
      panel.classList.add("is-open");
      if (fromUser) { const title = el("annual-detail-title"); if (title) title.focus({ preventScroll: true }); }
    }
    function closeDrawer() {
      const panel = el("annual-detail");
      if (!panel) return;
      panel.classList.remove("is-open");
      const back = state.returnFocus;
      state.returnFocus = null;
      if (back && back.isConnected) back.focus({ preventScroll: true });
    }
    function exportBox() {
      const [box, heading] = titledSection("tl-box tl-export", "annual-export-title", "存成行事曆檔");
      const year = state.model.years[state.yearIndex];
      const button = node("button", "ghost small", `把第 ${year.n + 1} 年的期間存成行事曆檔（.ics）`);
      button.type = "button";
      button.id = "annual-ics";
      button.setAttribute("aria-describedby", "annual-ics-months annual-ics-note");
      button.addEventListener("click", downloadIcs);
      // 月小限還在取或沒有取到時說一句：還在取時按鈕停用，免得存下少了月小限的檔案。
      const months = node("p", "note tl-ics-months");
      months.id = "annual-ics-months";
      months.hidden = true;
      const use = node("p", "note");
      use.id = "annual-ics-use";
      use.textContent = `行事曆檔（.ics）是手機與電腦的行事曆都認得的一種檔案。把它匯入你的行事曆（Google 日曆、Apple 行事曆、Outlook 都可以），行事曆就會在對應的日期上，標出第 ${year.n + 1} 年小限、月小限、法達、黃道釋放、十年期各段由哪顆行星或哪個星座輪值，從哪天到哪天。`;
      const steps = node("p", "note");
      steps.id = "annual-ics-steps";
      steps.textContent = "怎麼加進行事曆：先按下面的按鈕存下檔案。在 iPhone 或 Mac 上，點開這個檔案，照畫面提示加入行事曆；Google 日曆要用電腦開網頁版，到「設定」裡的匯入功能選這個檔案；Outlook 可以直接開啟這個檔案匯入。";
      const note = node("p", "note");
      note.id = "annual-ics-note";
      note.append(node("strong", null, `${Model.ICS_LABEL}。`),
        doc.createTextNode("任何一段期間的起點都能推回出生時刻與日夜盤。檔案在你的瀏覽器裡、只由畫面上這一年的期間產生，不經過伺服器；本站不提供訂閱網址，也不加提醒。檔名不含出生資料，但內容含有；請自行決定存放位置。匯入雲端行事曆之後，這些日期就由那個行事曆服務保存。"));
      box.append(heading, use, steps, months, button, note);
      return box;
    }
    function downloadIcs() {
      if (state.stale || !state.model || monthsState() === "pending") return;
      let artifact;
      try { artifact = Model.buildIcs(state.model, state.yearIndex, { now: now(), token: token() }); } catch (error) {
        setStatus(`沒有產生行事曆檔：${error.message}`, "error");
        return;
      }
      deliver(artifact);
      setStatus(`已產生行事曆檔（${artifact.count} 段期間，${Model.ICS_LABEL}）。${monthsState() === "failed" ? ICS_MONTHS_FAILED : ""}`, "info");
    }
    /** 檔案交給瀏覽器下載：Blob 網址登記在本區的生命週期，清除或離開頁面時一併收回。 */
    function deliver(artifact) {
      lifecycle.deliverDownload(doc, new win.Blob([artifact.content], { type: artifact.mime_type }), artifact.filename);
    }
    function tableExportBox() {
      const [box, heading] = titledSection("tl-box tl-export tl-table-export", "annual-table-title", "存成時間主星表");
      const use = node("p", "note", "時間主星表把這一區的期間整理成一份資料檔：每一段的技法、層級、起訖日期、輪值的星座或行星與守護行星，加上算法代碼、注意事項與本工具採用的約定，可以留存、核對，或拿去自己整理。行事曆檔只放選定的這一年，給行事曆用；這份表放畫面目前取到的每一段。");
      use.id = "annual-table-use";
      const formats = node("p", "note", "三種格式內容相同，挑順手的一種：Markdown（.md）是帶標題與表格的純文字，任何文字編輯器都能開，貼進支援 Markdown 的筆記軟體會排成表格；CSV（.csv）用 Excel、Numbers 或 Google 試算表開啟，每一列是一段期間的一個欄位，用「表」那一欄篩選就能只看一種技法；JSON（.json）給程式讀，另附伺服器的原始回應，可以拿來驗算。");
      formats.id = "annual-table-formats";
      const coverage = node("p", "note", "表裡只有畫面已經取到的期間：黃道釋放與十年期的第二層、月小限，要在畫面上看過那一段或那一年才會取；還沒取的，表裡寫「未取得」，不代表那一段沒有細分。");
      coverage.id = "annual-table-coverage";
      const actions = node("div", "tl-table-actions");
      Model.TIME_LORD_TABLE_FORMATS.forEach((format) => {
        const name = Model.TIME_LORD_TABLE_FORMAT_NAMES[format];
        const button = node("button", "ghost small", name);
        button.type = "button";
        button.dataset.annualTable = format;
        // 看得見的字開頭再接用途：與本命盤匯出工具列同名的按鈕在按鈕清單裡分得開。
        button.setAttribute("aria-label", `${name}（時間主星表）`);
        button.setAttribute("aria-describedby", "annual-table-note");
        button.addEventListener("click", () => downloadTable(format));
        actions.appendChild(button);
      });
      const note = node("p", "note");
      note.id = "annual-table-note";
      note.append(node("strong", null, `${Model.ICS_LABEL}。`),
        doc.createTextNode("任何一段期間的起點都能推回出生時刻與日夜盤；JSON 另附的伺服器原始回應裡，還有本命盤的時刻（UTC）與出生地的時區名稱。檔案在你的瀏覽器裡、只由畫面已經收到的資料產生，不另外送出請求。檔名不含出生資料，但內容含有；請自行決定存放位置。"));
      box.append(heading, use, formats, coverage, actions, note);
      return box;
    }
    function downloadTable(format) {
      if (state.stale || !state.model) return;
      let artifact;
      try { artifact = Model.buildTimeLordTableArtifact(state.model, state.sources, format); } catch (error) {
        setStatus(`沒有產生時間主星表：${error.message}`, "error");
        return;
      }
      deliver(artifact);
      setStatus(`已產生時間主星表（${artifact.format_name}，${artifact.count} 段期間，${Model.ICS_LABEL}）。`, "info");
    }
    function conventionsBox() {
      const [box, heading] = titledSection("tl-box tl-conventions", "annual-conventions-title", "本工具採用的約定");
      box.append(heading, node("p", "note", "同一套技法，各家軟體的預設不同。這裡列出本頁用了哪一種。"));
      const list = node("ul");
      Model.conventions(state.model).forEach(([term, text]) => {
        const item = node("li");
        item.append(node("strong", null, term), doc.createTextNode(text));
        list.appendChild(item);
      });
      box.appendChild(list);
      return box;
    }
    const START_LABEL = startButton.textContent;
    function showUnavailable() {
      startButton.textContent = "年度時間主星尚未開放";
      setStatus("這個伺服器還沒有開放年度時間主星；本命盤的結果不受影響。", "info");
      refreshControls();
    }
    function refreshControls() {
      startButton.disabled = routeUnavailable || !state.payload || state.stale || state.loading;
      if (!routeUnavailable) startButton.textContent = START_LABEL;
      const months = monthsState();
      const ics = el("annual-ics");
      if (ics) ics.disabled = state.stale || !state.model || months === "pending";
      body.querySelectorAll("[data-annual-table]").forEach((button) => { button.disabled = state.stale || !state.model; });
      solarReturn.syncButton();
      const note = el("annual-ics-months");
      if (note) {
        note.hidden = months === "ready";
        note.textContent = months === "failed" ? ICS_MONTHS_FAILED : months === "pending" ? ICS_MONTHS_PENDING : "";
      }
    }
    function show(payload) {
      drop();
      syncOptionLabels();
      state.payload = payload;
      host.hidden = false;
      startNote.hidden = false;
      setStatus("", "info");
      refreshControls();
      if (routeUnavailable) showUnavailable();
    }
    function drop() {
      state.generation += 1;
      state.level2Generation += 1;
      lifecycle.clear();
      level2Lifecycle.clear();
      solarReturn.clear();
      life.clear();
      if (scrollTimer !== null) { win.clearTimeout(scrollTimer); scrollTimer = null; }
      clearLevel2Timers();
      Object.assign(state, {
        payload: null, stale: false, loading: false, data: null, model: null, sources: [], view: null,
        zoom: "decade", yearIndex: -1, selected: null, level2Busy: false, ...freshLevel2(),
        returnFocus: null, decennials: null, firdariaNode: null, zrYear: null, openDecades: new Map(), openYears: new Map(),
        solar: { ...freshSolar(), generation: state.solar.generation + 1 },
      });
      body.replaceChildren();
      body.hidden = true;
      host.hidden = true;
      startNote.hidden = false;
      setStatus("", "info");
      refreshControls();
    }
    function setStale(stale) {
      state.stale = Boolean(stale);
      host.dataset.stale = state.stale ? "true" : "false";
      if (state.stale) {
        const busy = state.loading || state.level2Busy;
        if (state.loading) {
          // 進行中的重排作廢：回應對應的是改動前的表單。
          state.generation += 1;
          state.loading = false;
        }
        lifecycle.abortActiveRequest();
        stopLevel2();
        solarReturn.stop();
        if (busy) setStatus("表單已改動，這次的年度計算已停止。", "info");
      }
      refreshControls();
    }
    startButton.addEventListener("click", load);
    [decennialsProfile, decennialsPlanet, firdariaNode, zrYear].forEach((control) => {
      if (control) control.addEventListener("change", onChoiceChange);
    });
    refreshDecennialsControls();
    syncOptionLabels();
    // 跨過手機斷點（轉向、縮放視窗）時：選單換短字或長字，年表換成有沒有收起年度的那一種。
    const mobileQuery = typeof win.matchMedia === "function" ? win.matchMedia(MOBILE_QUERY) : null;
    if (mobileQuery && typeof mobileQuery.addEventListener === "function") {
      mobileQuery.addEventListener("change", () => {
        syncOptionLabels();
        if (state.model && state.view === "yearbook" && body.querySelector(".tl-main")) refreshAfterLevel2();
      });
    }
    // Esc 只關最上層的東西：抽屜開著時只關抽屜（捕獲階段先處理並標記 defaultPrevented，星盤的點選標示就不跟著清除）。
    doc.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const panel = el("annual-detail");
      if (!panel || !panel.classList.contains("is-open")) return;
      event.preventDefault();
      closeDrawer();
    }, true);
    return Object.freeze({
      show, drop, setStale,
      // 與按「排出時間主星」同一個動作（計算頁在古典完整算完星盤後呼叫）。
      load, prefer: (technique) => { preferredTechnique = technique || null; },
      // 一頁摘要的一行（選定的那一年由誰輪值）；還沒排出或表單已改動時是 null。
      briefLine: () => (state.model && !state.stale ? Model.briefLine(state.model, state.yearIndex) : null),
      snapshot: () => ({
        view: state.view, zoom: state.zoom, yearIndex: state.yearIndex, selected: state.selected,
        stale: state.stale, hasModel: Boolean(state.model), loaded: state.data ? [...state.data.level2LoadedFor] : [],
      }),
    });
  }

  // 太陽回歸盤選定年度的年界那一刻起的星盤：按了才請求（同一條年度路由，只要這一張盤），預設在出生地。結果只對那一年；
  // 換到別的年度時這一格回到按鈕。清除、過期或離開頁面時跟著丟棄。人生時間軸：寬的畫成橫向（時間往右），窄於這個寬度
  // （px）時改畫直向（時間往下、每種技法一欄）。
  const LIFE_VERTICAL_BELOW = 560;
  const LIFE_FALLBACK_WIDTH = 960;
  const LIFE_PROMPT = "點任一段（或按 Tab 再用方向鍵）看它的起訖日期與主星。";

  /**
   * 人生時間軸一格：每種技法的第一層各一條，排在同一條足歲軸上並列（資料見 Model.lifeOverview）。
   * 圖是 SVG，位置全寫在屬性上，不用 style；量出容器寬度後才畫，寬度改變時重畫。每一段是一個可聚焦的
   * 按鈕（每條一個 Tab 停點，方向鍵移動），聚焦、滑過或點按都在圖下的讀出列寫出起訖與主星；同一份資料
   * 另列成表格給報讀器與列印。回傳 section()（建出這一格）、draw()（量寬後畫圖）與 stop()（停止量寬）。
   */
  function createLifeOverview(context) {
    const { doc, win, state, node, titledSection, onOpen } = context;
    let observer = null;
    let figure = null;
    let readout = null;
    let overview = null;
    let drawnWidth = 0;
    let picked = null;
    function svg(tag, attributes, className) {
      const element = doc.createElementNS(SVG_NS, tag);
      if (className) element.setAttribute("class", className);
      Object.entries(attributes || {}).forEach(([key, value]) => element.setAttribute(key, String(value)));
      return element;
    }
    function text(x, y, content, className, anchor) {
      const element = svg("text", { x: round(x), y: round(y), "text-anchor": anchor || "start" }, className);
      element.textContent = content;
      return element;
    }
    const round = (value) => Math.round(value * 10) / 10;
    function glyphAt(key, x, y, size) {
      const entry = key && Glyphs.GLYPHS[key];
      if (!entry) return null;
      const [x0, , x1] = entry.bbox;
      const box = svg("svg", {
        x: round(x), y: round(y), width: size, height: size,
        viewBox: `${Math.round((x0 + x1) / 2) - 525} -810 1050 1050`, "aria-hidden": "true", focusable: "false",
      }, "tl-life-glyph");
      box.appendChild(svg("path", { d: entry.d }));
      return box;
    }
    function findItem(id) {
      if (!overview) return null;
      for (const lane of overview.lanes) {
        const item = lane.items.find((candidate) => candidate.id === id);
        if (item) return { lane, item };
      }
      return null;
    }
    function showReadout(id) {
      if (!readout) return;
      const found = id ? findItem(id) : null;
      readout.replaceChildren();
      if (!found) { readout.appendChild(node("span", "tl-life-prompt", LIFE_PROMPT)); return; }
      const { lane, item } = found;
      const head = node("span", "tl-life-read-lane", lane.title);
      const ruler = node("span", "tl-life-read-ruler");
      const svgGlyph = glyphFor(item.glyph);
      if (svgGlyph) ruler.appendChild(svgGlyph);
      ruler.appendChild(doc.createTextNode(item.label));
      if (item.lord) {
        ruler.appendChild(doc.createTextNode("・年主星 "));
        const lordGlyph = glyphFor(item.lordGlyph);
        if (lordGlyph) ruler.appendChild(lordGlyph);
        ruler.appendChild(doc.createTextNode(item.lord));
      }
      const dates = node("span", "tl-life-read-dates tl-num", `${item.start} → ${item.end}`);
      const ages = node("span", "tl-life-read-ages", lane.technique === "annual_profection"
        ? `${item.startAge} 足歲這一年` : `${item.startAge} 至 ${item.endAge} 足歲`);
      readout.append(head, ruler, dates, ages);
      if (item.loosing) readout.appendChild(node("span", "tl-life-read-mark", "解鎖"));
      if (item.continuesAfter) readout.appendChild(node("span", "tl-life-read-mark", "延續到圖的範圍之後"));
      if (onOpen && state.model && state.model.byId.has(item.id)) {
        const open = node("button", "tl-life-open", "在下方看這一段的細節");
        open.type = "button";
        open.addEventListener("click", () => onOpen(item.id, open));
        readout.appendChild(open);
      }
    }
    function glyphFor(key) {
      const entry = key && Glyphs.GLYPHS[key];
      if (!entry) return null;
      const [x0, , x1] = entry.bbox;
      const box = svg("svg", { viewBox: `${Math.round((x0 + x1) / 2) - 525} -810 1050 1050`, "aria-hidden": "true", focusable: "false" }, "tl-glyph");
      box.appendChild(svg("path", { d: entry.d }));
      return box;
    }
    function markPicked() {
      if (!figure) return;
      figure.querySelectorAll(".tl-life-band").forEach((band) => {
        const on = band.dataset.lifeItem === picked;
        band.classList.toggle("is-picked", on);
        band.setAttribute("aria-pressed", String(on));
      });
    }
    function pick(id) { picked = id; markPicked(); showReadout(id); }
    function table() {
      const wrap = node("details", "tl-life-table");
      wrap.appendChild(node("summary", null, "以表格列出全部期間"));
      const scroller = node("div", "tl-life-table-wrap");
      scroller.tabIndex = 0;
      scroller.setAttribute("role", "region");
      scroller.setAttribute("aria-label", "人生時間軸的期間表");
      const grid = node("table");
      grid.appendChild(node("caption", null, `人生時間軸的期間（${overview.startAge} 至 ${overview.endAge} 足歲；日期是${Model.DATE_NOTE}）`));
      const head = node("thead");
      const headRow = node("tr");
      ["技法", "主星或星座", "起", "迄", "足歲"].forEach((label) => {
        const cell = node("th", null, label);
        cell.scope = "col";
        headRow.appendChild(cell);
      });
      head.appendChild(headRow);
      grid.appendChild(head);
      overview.lanes.forEach((lane) => {
        const group = node("tbody");
        lane.items.forEach((item, index) => {
          const row = node("tr");
          const name = node(index ? "td" : "th", null, index ? "" : lane.title);
          if (!index) { name.scope = "rowgroup"; name.rowSpan = lane.items.length; row.appendChild(name); }
          row.append(
            node("td", null, item.lord ? `${item.label}（年主星 ${item.lord}）` : item.label),
            node("td", "tl-num", item.start), node("td", "tl-num", item.end),
            node("td", "tl-num", lane.technique === "annual_profection" ? `${item.startAge}` : `${item.startAge}–${item.endAge}`),
          );
          group.appendChild(row);
        });
        grid.appendChild(group);
      });
      scroller.appendChild(grid);
      wrap.appendChild(scroller);
      return wrap;
    }
    function section() {
      stop();
      overview = Model.lifeOverview(state.model);
      if (!overview || !overview.lanes.length) return null;
      if (picked && !findItem(picked)) picked = null;
      const [box, heading] = titledSection("tl-life", "annual-life-title", "人生時間軸");
      const head = node("div", "tl-life-head");
      head.append(heading, node("p", "tl-life-lead", Model.LIFE_LEAD));
      box.appendChild(head);
      figure = node("div", "tl-life-figure");
      box.appendChild(figure);
      readout = node("p", "tl-life-readout");
      readout.id = "annual-life-readout";
      readout.setAttribute("aria-live", "polite");
      box.appendChild(readout);
      showReadout(picked);
      const legend = node("div", "tl-life-legend");
      legend.setAttribute("aria-hidden", "true");
      [["tl-life-lg-today", "今天"], ["tl-life-lg-now", "今天所在的那一段"], ["tl-life-lg-restart", "小限回到上升星座"], ["tl-life-lg-loose", "解鎖（黃道釋放跳到對宮）"]]
        .forEach(([className, label]) => {
          const entry = node("span");
          entry.append(node("i", className), doc.createTextNode(label));
          legend.appendChild(entry);
        });
      box.appendChild(legend);
      box.appendChild(node("p", "note tl-life-note", `底色兩種紙色交替只為分辨相鄰兩段，不代表好壞。各技法的年長不同（法達與小限以太陽回歸為年界，黃道釋放與十年期一年 360 日），所以同一個年數的分界不一定對齊。日期是${Model.DATE_NOTE}。`));
      box.appendChild(table());
      if (typeof win.ResizeObserver === "function") {
        // 重畫放到下一個畫格：在回呼裡直接換掉被觀察的內容，Safari 會報「ResizeObserver loop」錯誤。
        let pending = false;
        observer = new win.ResizeObserver(() => {
          if (pending) return;
          pending = true;
          const redraw = () => { pending = false; const width = measure(); if (Math.abs(width - drawnWidth) >= 1) draw(); };
          if (typeof win.requestAnimationFrame === "function") win.requestAnimationFrame(redraw);
          else redraw();
        });
        observer.observe(figure);
      }
      return box;
    }
    function measure() { return figure && figure.clientWidth > 0 ? figure.clientWidth : LIFE_FALLBACK_WIDTH; }
    function draw() {
      if (!figure || !overview) return;
      const width = measure();
      drawnWidth = width;
      const vertical = width < LIFE_VERTICAL_BELOW;
      const focused = doc.activeElement && figure.contains(doc.activeElement) ? doc.activeElement.dataset.lifeItem : null;
      const drawing = vertical ? drawVertical(width) : drawHorizontal(width);
      figure.dataset.orientation = vertical ? "vertical" : "horizontal";
      figure.replaceChildren(drawing);
      setStops(focused);
      markPicked();
      if (focused) {
        const again = figure.querySelector(`[data-life-item="${CSS_ESCAPE(focused)}"]`);
        if (again) again.focus({ preventScroll: true });
      }
    }
    // 期間 id 只含英數、斜線、點、連字號與 @（回應的閉集）；選擇器裡照樣跳脫引號以外的字元不必要。
    const CSS_ESCAPE = (value) => String(value).replace(/["\\]/g, "\\$&");
    function frame(width, height, vertical) {
      const root = svg("svg", { viewBox: `0 0 ${Math.round(width)} ${Math.round(height)}`, role: "group",
        "aria-label": `人生時間軸，${overview.startAge} 至 ${overview.endAge} 足歲，${overview.lanes.length} 條並列`,
        "aria-describedby": "annual-life-readout" }, `tl-life-svg${vertical ? " is-vertical" : ""}`);
      root.addEventListener("click", onBandEvent);
      root.addEventListener("keydown", onKey);
      root.addEventListener("focusin", (event) => { const band = bandOf(event.target); if (band) showReadout(band.dataset.lifeItem); });
      root.addEventListener("focusout", () => showReadout(picked));
      root.addEventListener("pointerover", (event) => {
        // 觸控的點按不是滑過：讀出列只跟著點選走。
        if (event.pointerType !== "mouse" && event.pointerType !== "pen") return;
        const band = bandOf(event.target);
        if (band) showReadout(band.dataset.lifeItem);
      });
      root.addEventListener("pointerleave", () => {
        const focusedBand = bandOf(doc.activeElement);
        showReadout(focusedBand ? focusedBand.dataset.lifeItem : picked);
      });
      return root;
    }
    function bandOf(target) { return target && typeof target.closest === "function" ? target.closest(".tl-life-band") : null; }
    function onBandEvent(event) {
      const band = bandOf(event.target);
      if (!band) return;
      pick(band.dataset.lifeItem === picked ? null : band.dataset.lifeItem);
      if (picked) showReadout(picked);
    }
    function bandElement(lane, item, rect, vertical) {
      const group = svg("g", { role: "button", tabindex: -1, "aria-pressed": "false",
        "aria-label": Model.lifeItemText(lane, item) }, `tl-life-band${item.index % 2 ? " alt" : ""}${item.current ? " is-now" : ""}`);
      group.dataset.lifeItem = item.id;
      group.dataset.start = String(item.startDay);
      group.dataset.end = String(item.endDay);
      group.appendChild(svg("rect", { x: round(rect.x), y: round(rect.y), width: round(Math.max(1, rect.w)), height: round(Math.max(1, rect.h)), rx: 1.5 }, "tl-life-rect"));
      if (item.current) {
        group.appendChild(vertical
          ? svg("rect", { x: round(rect.x), y: round(rect.y), width: 2.5, height: round(Math.max(1, rect.h)) }, "tl-life-nowmark")
          : svg("rect", { x: round(rect.x), y: round(rect.y + rect.h - 2.5), width: round(Math.max(1, rect.w)), height: 2.5 }, "tl-life-nowmark"));
      }
      const labelLength = [...(item.label || "")].length;
      const size = vertical ? (rect.h >= 17 ? Model.segmentSize(rect.w, labelLength) : "none") : Model.segmentSize(rect.w, labelLength);
      if (size !== "none") {
        const showGlyph = size === "full" || size === "glyph";
        const showName = size === "full" || size === "name";
        const content = (showGlyph ? 13 : 0) + (showGlyph && showName ? 3 : 0) + (showName ? 13 * labelLength : 0);
        let x = rect.x + (rect.w - content) / 2;
        const middle = rect.y + rect.h / 2;
        if (showGlyph) { const mark = glyphAt(item.glyph, x, middle - 6.5, 13); if (mark) group.appendChild(mark); x += 16; }
        if (showName) group.appendChild(text(x, middle + 4.5, item.label, "tl-life-text"));
      }
      if (item.loosing) {
        const cx = vertical ? rect.x + rect.w : rect.x;
        const cy = rect.y;
        group.appendChild(svg("path", { d: `M${round(cx)} ${round(cy - 4)}l4 4l-4 4l-4 -4z` }, "tl-life-loose"));
      }
      return group;
    }
    function drawHorizontal(width) {
      const labelW = width >= 900 ? 168 : 140;
      const right = 16;
      const top = 44;
      const laneH = 38;
      const sampleH = 30;
      const gap = 8;
      const span = overview.endDay - overview.startDay;
      const x = (day) => labelW + ((day - overview.startDay) / span) * (width - labelW - right);
      let y = top;
      const rows = overview.lanes.map((lane, index) => {
        const previous = overview.lanes[index - 1];
        if (previous && previous.technique !== lane.technique) y += gap;
        const h = lane.sample ? sampleH : laneH;
        const row = { lane, y, h };
        y += h;
        return row;
      });
      const height = y + 34;
      const root = frame(width, height, false);
      // 十年一格的淡線與足歲刻度（上）、西元年（下一行小字）。
      const grid = svg("g", { "aria-hidden": "true" }, "tl-life-grid");
      overview.ticks.forEach((tick) => {
        const tx = x(tick.day);
        grid.appendChild(svg("line", { x1: round(tx), x2: round(tx), y1: top - 6, y2: y }, "tl-life-gridline"));
        grid.appendChild(text(tx, 17, tick.age === overview.startAge ? `${tick.age} 歲` : `${tick.age}`, "tl-life-age", "middle"));
        grid.appendChild(text(tx, 33, tick.calendarYear, "tl-life-year", "middle"));
      });
      root.appendChild(grid);
      const labels = svg("g", { "aria-hidden": "true" }, "tl-life-labels");
      rows.forEach(({ lane, y: rowY, h }) => {
        if (lane.sample) {
          labels.appendChild(text(labelW - 12, rowY + h / 2 + 4.5, `${lane.short}・${lane.sample}`, "tl-life-lane-sample", "end"));
        } else {
          labels.appendChild(text(labelW - 12, rowY + h / 2 - 2, lane.title, "tl-life-lane", "end"));
          labels.appendChild(text(labelW - 12, rowY + h / 2 + 12, lane.note, "tl-life-lane-note", "end"));
        }
      });
      root.appendChild(labels);
      rows.forEach(({ lane, y: rowY, h }) => {
        const group = svg("g", { role: "group", "aria-label": lane.title }, "tl-life-lane-row");
        group.dataset.lane = lane.id;
        lane.items.forEach((item) => {
          const left = x(item.startDay);
          const rect = { x: left + 0.5, y: rowY + 4, w: x(item.endDay) - left - 1, h: h - 8 };
          group.appendChild(bandElement(lane, item, rect, false));
          if (item.restart) group.appendChild(svg("line", { x1: round(left), x2: round(left), y1: rowY + 1, y2: rowY + h - 1, "aria-hidden": "true" }, "tl-life-restart"));
        });
        root.appendChild(group);
      });
      if (overview.today) {
        const tx = x(overview.today.day);
        const marker = svg("g", { "aria-hidden": "true" }, "tl-life-today");
        marker.appendChild(svg("line", { x1: round(tx), x2: round(tx), y1: top - 6, y2: y + 4 }));
        const label = `今天・${overview.today.age} 足歲`;
        const labelWidth = 13 * 5 + 7.5 * String(overview.today.age).length + 16;
        const lx = Math.min(Math.max(tx - labelWidth / 2, labelW), width - right - labelWidth);
        marker.appendChild(svg("rect", { x: round(lx), y: y + 6, width: round(labelWidth), height: 20, rx: 2 }));
        marker.appendChild(text(lx + labelWidth / 2, y + 20.5, label, null, "middle"));
        root.appendChild(marker);
      }
      return root;
    }
    function drawVertical(width) {
      const axisW = 50;
      const right = 4;
      const head = 46;
      const gap = 4;
      const yearPx = 9;
      const columns = overview.lanes.length;
      const colW = (width - axisW - right - gap * (columns - 1)) / columns;
      const span = overview.endDay - overview.startDay;
      const plotH = (span / 365.25) * yearPx;
      const y = (day) => head + ((day - overview.startDay) / span) * plotH;
      const height = head + plotH + 26;
      const root = frame(width, height, true);
      const colX = (index) => axisW + index * (colW + gap);
      const grid = svg("g", { "aria-hidden": "true" }, "tl-life-grid");
      overview.ticks.forEach((tick) => {
        const ty = y(tick.day);
        grid.appendChild(svg("line", { x1: axisW - 4, x2: width - right, y1: round(ty), y2: round(ty) }, "tl-life-gridline"));
        grid.appendChild(text(axisW - 8, ty + 5, tick.age === overview.startAge ? `${tick.age}歲` : `${tick.age}`, "tl-life-age", "end"));
        grid.appendChild(text(axisW - 8, ty + 19, tick.calendarYear, "tl-life-year", "end"));
      });
      root.appendChild(grid);
      const labels = svg("g", { "aria-hidden": "true" }, "tl-life-labels");
      overview.lanes.forEach((lane, index) => {
        const cx = colX(index) + colW / 2;
        labels.appendChild(text(cx, lane.sample ? 18 : 26, lane.short, "tl-life-lane", "middle"));
        if (lane.sample) labels.appendChild(text(cx, 36, lane.sample, "tl-life-lane-note", "middle"));
      });
      root.appendChild(labels);
      overview.lanes.forEach((lane, index) => {
        const group = svg("g", { role: "group", "aria-label": lane.title }, "tl-life-lane-row");
        group.dataset.lane = lane.id;
        lane.items.forEach((item) => {
          const topY = y(item.startDay);
          const rect = { x: colX(index), y: topY + 0.5, w: colW, h: y(item.endDay) - topY - 1 };
          group.appendChild(bandElement(lane, item, rect, true));
          if (item.restart) group.appendChild(svg("line", { x1: round(colX(index) - 1), x2: round(colX(index) + colW + 1), y1: round(topY), y2: round(topY), "aria-hidden": "true" }, "tl-life-restart"));
        });
        root.appendChild(group);
      });
      if (overview.today) {
        const ty = y(overview.today.day);
        const marker = svg("g", { "aria-hidden": "true" }, "tl-life-today");
        marker.appendChild(svg("line", { x1: axisW - 2, x2: width - right, y1: round(ty), y2: round(ty) }));
        marker.appendChild(svg("rect", { x: 0, y: round(ty - 10), width: axisW - 4, height: 20, rx: 2 }));
        marker.appendChild(text((axisW - 4) / 2, ty + 4.5, `今天${overview.today.age}`, null, "middle"));
        root.appendChild(marker);
      }
      return root;
    }
    // 每條一個 Tab 停點：讀出列正在看的那段，否則今天所在的那段，否則第一段。
    function setStops(preferred) {
      figure.querySelectorAll(".tl-life-lane-row").forEach((row) => {
        const bands = [...row.querySelectorAll(".tl-life-band")];
        bands.forEach((entry) => entry.setAttribute("tabindex", "-1"));
        const tabStop = bands.find((entry) => entry.dataset.lifeItem === preferred)
          || bands.find((entry) => entry.dataset.lifeItem === picked)
          || bands.find((entry) => entry.classList.contains("is-now")) || bands[0];
        if (tabStop) tabStop.setAttribute("tabindex", "0");
      });
    }
    function onKey(event) {
      const current = bandOf(event.target);
      if (!current) return;
      const vertical = figure.dataset.orientation === "vertical";
      const along = vertical ? ["ArrowUp", "ArrowDown"] : ["ArrowLeft", "ArrowRight"];
      const across = vertical ? ["ArrowLeft", "ArrowRight"] : ["ArrowUp", "ArrowDown"];
      const row = current.closest(".tl-life-lane-row");
      const bands = [...row.querySelectorAll(".tl-life-band")];
      const index = bands.indexOf(current);
      let target = null;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        pick(current.dataset.lifeItem === picked ? null : current.dataset.lifeItem);
        if (picked) showReadout(picked);
        return;
      }
      if (event.key === along[1]) target = bands[index + 1];
      else if (event.key === along[0]) target = bands[index - 1];
      else if (event.key === "Home") target = bands[0];
      else if (event.key === "End") target = bands[bands.length - 1];
      else if (across.includes(event.key)) {
        const rows = [...figure.querySelectorAll(".tl-life-lane-row")];
        const other = rows[rows.indexOf(row) + (event.key === across[1] ? 1 : -1)];
        if (other) {
          const day = Number(current.dataset.start);
          const candidates = [...other.querySelectorAll(".tl-life-band")];
          target = candidates.find((entry) => Number(entry.dataset.start) <= day && day < Number(entry.dataset.end))
            || candidates.find((entry) => Number(entry.dataset.start) >= day) || candidates[candidates.length - 1];
        }
      } else { return; }
      event.preventDefault();
      if (!target) return;
      const targetRow = target.closest(".tl-life-lane-row");
      targetRow.querySelectorAll(".tl-life-band").forEach((entry) => entry.setAttribute("tabindex", "-1"));
      if (targetRow !== row) current.setAttribute("tabindex", "0");
      else current.setAttribute("tabindex", "-1");
      target.setAttribute("tabindex", "0");
      target.focus({ preventScroll: true });
    }
    function stop() {
      if (observer) observer.disconnect();
      observer = null;
      figure = null;
      readout = null;
      drawnWidth = 0;
    }
    function clear() { stop(); overview = null; picked = null; }
    return { section, draw, stop, clear };
  }

  const SOLAR_IDS = Object.freeze({
    box: "annual-sr", title: "annual-sr-title", status: "annual-sr-status", load: "annual-sr-load",
    latitude: "annual-sr-latitude", longitude: "annual-sr-longitude", privacy: "annual-sr-privacy",
    house: "annual-sr-house", houseNote: "annual-sr-house-note",
  });
  // 回歸盤星盤圖區塊（ChartWheel.createSection）的 id 前綴，與下載檔名（不含出生資料）。
  const SOLAR_WHEEL_ID = "annual-sr-wheel";
  const SOLAR_WHEEL_FILES = Object.freeze({
    svg: "classical-astrology-solar-return-chart.svg", png: "classical-astrology-solar-return-chart.png",
  });

  /**
   * 太陽回歸盤那一格。畫面狀態在面板的 state.solar（清除時由面板重設），元素工具與請求也取自面板；
   * 自己用一個請求槽，與重排、第二層互不中止。回傳 box()（畫出這一格）、syncButton()（按鈕跟著
   * 面板的狀態）、stop()（表單改動時停下進行中的請求）與 clear()（丟棄）。
   */
  function createSolarReturn(context) {
    const { doc, win, state, el, node, titledSection, post, failureMessage, codeNote } = context;
    const solarLifecycle = Lifecycle.createSensitiveDataLifecycle({ revokeObjectUrl: (url) => win.URL.revokeObjectURL(url) });
    function selectedYear() { return state.model && state.yearIndex >= 0 ? state.model.years[state.yearIndex] : null; }
    function solarBlocked(year) {
      if (!year) return "";
      if (year.n < 1) return Model.SOLAR_RETURN_REASONS.first_year_has_no_solar_return;
      if (!state.payload || state.payload.birth_time_precision !== "exact") {
        return Model.SOLAR_RETURN_REASONS.solar_return_chart_requires_exact_birth_time;
      }
      return null;
    }
    function solarReturnBox() {
      const year = selectedYear();
      const solar = state.solar;
      const shown = solar.result && year && solar.result.n === year.n ? solar.result : null;
      const [box, heading] = titledSection("tl-box tl-sr", SOLAR_IDS.title,
        shown ? shown.panel.heading : `太陽回歸盤（第 ${year ? year.n + 1 : "—"} 年）`);
      box.id = SOLAR_IDS.box;
      heading.tabIndex = -1;
      // 「不替你解盤，也不預測」在章首說過一次；這裡只說這張盤是什麼（匯出與面板仍帶完整的一句）。
      box.append(heading, node("p", "note tl-sr-lead", Model.SOLAR_RETURN_LEAD));
      const blocked = solarBlocked(year);
      if (blocked) { box.appendChild(node("p", "note tl-sr-blocked", blocked)); } else { box.appendChild(solarControls(year)); }
      const status = node("p", "status-line tl-sr-status");
      status.id = SOLAR_IDS.status;
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      box.appendChild(status);
      if (shown) box.appendChild(solarPanel(shown.panel));
      return box;
    }
    function solarControls(year) {
      const solar = state.solar;
      const wrap = node("div", "tl-sr-controls");
      wrap.appendChild(solarHouseControl());
      const button = node("button", "ghost small", `排出第 ${year.n + 1} 年的太陽回歸盤`);
      button.type = "button";
      button.id = SOLAR_IDS.load;
      button.disabled = state.stale || solar.loading || !state.payload;
      button.addEventListener("click", loadSolarReturn);
      // 另選地點的開關關著時不畫那一格，也不提它的說明。
      if (Model.SOLAR_RETURN_RELOCATION_OFFERED) wrap.appendChild(solarPlaceControl());
      wrap.appendChild(button);
      return wrap;
    }
    function solarPlaceControl() {
      const solar = state.solar;
      const place = node("details", "tl-sr-place");
      // 填過另一個地點時，重畫後照樣展開，看得到送出去的是什麼。
      place.open = Boolean(solar.latitude || solar.longitude);
      place.appendChild(node("summary", null, "太陽回歸時不在出生地？改用另一個地點"));
      place.appendChild(node("p", "note", Model.SOLAR_RETURN_MORIN));
      place.appendChild(node("p", "note", "回歸盤的宮位與四軸依地點而變；兩格都空著就用出生地。座標用十進位度數，南緯與西經填負數。"));
      const fields = node("div", "tl-sr-fields");
      [["latitude", "緯度（度）", "例如 25.0330"], ["longitude", "經度（度）", "例如 121.5654"]].forEach(([key, label, hint]) => {
        const field = node("span", "tl-sr-field");
        const labelNode = node("label", null, label);
        labelNode.htmlFor = SOLAR_IDS[key];
        const input = doc.createElement("input");
        input.type = "text";
        input.inputMode = "decimal";
        input.autocomplete = "off";
        input.spellcheck = false;
        input.id = SOLAR_IDS[key];
        input.placeholder = hint;
        input.value = solar[key];
        input.setAttribute("aria-describedby", SOLAR_IDS.privacy);
        input.addEventListener("input", () => { state.solar[key] = input.value; });
        field.append(labelNode, input);
        fields.appendChild(field);
      });
      const privacy = node("p", "note", Model.SOLAR_RETURN_PRIVACY);
      privacy.id = SOLAR_IDS.privacy;
      place.append(fields, privacy);
      return place;
    }
    function solarHouseControl() {
      const names = Model.HOUSE_SYSTEM_NAMES;
      const natal = Model.solarReturnHouseSystem(state.payload);
      const field = node("span", "tl-sr-field tl-sr-house");
      const label = node("label", null, "回歸盤的宮位制");
      label.htmlFor = SOLAR_IDS.house;
      const houseSelect = doc.createElement("select");
      houseSelect.id = SOLAR_IDS.house;
      houseSelect.setAttribute("aria-describedby", SOLAR_IDS.houseNote);
      const same = doc.createElement("option");
      same.value = "";
      same.textContent = `與本命盤相同（${names[natal] || natal}）`;
      houseSelect.appendChild(same);
      Model.SOLAR_RETURN_HOUSE_SYSTEMS.forEach((code) => {
        const option = doc.createElement("option");
        option.value = code;
        option.textContent = names[code] || code;
        houseSelect.appendChild(option);
      });
      houseSelect.value = state.solar.houseSystem;
      houseSelect.addEventListener("change", () => { state.solar.houseSystem = houseSelect.value; });
      const note = node("p", "note", "回歸盤預設用本命盤所選的宮位制，兩張盤的宮才對得上；也可以另選一種。");
      note.id = SOLAR_IDS.houseNote;
      field.append(label, houseSelect, note);
      return field;
    }
    function setSolarStatus(message, tone) {
      const line = el(SOLAR_IDS.status);
      if (!line) return;
      line.textContent = message;
      line.dataset.tone = tone || "info";
    }
    /** 只換掉回歸盤這一格（不重畫時間軸，捲動與焦點留在原處）。 */
    function refreshSolarBox(message, tone, focusId) {
      const old = el(SOLAR_IDS.box);
      if (!old || !state.model) return;
      const fresh = solarReturnBox();
      old.replaceWith(fresh);
      if (message) setSolarStatus(message, tone);
      const target = focusId ? el(focusId) : null;
      if (target && !target.disabled) target.focus();
    }
    function stopSolarReturn() {
      state.solar.generation += 1;
      solarLifecycle.abortActiveRequest();
      if (!state.solar.loading) return;
      state.solar.loading = false;
      refreshSolarBox("表單已改動，這次的太陽回歸盤計算已停止。", "info");
    }
    function loadSolarReturn() {
      const year = selectedYear();
      if (!year || state.stale || state.solar.loading || solarBlocked(year)) return;
      const parsed = Model.SOLAR_RETURN_RELOCATION_OFFERED
        ? Model.parseSolarReturnLocation(state.solar.latitude, state.solar.longitude) : { location: null };
      if (parsed.error) { setSolarStatus(parsed.error, "error"); const input = el(SOLAR_IDS.latitude); if (input) input.focus(); return; }
      let requestBody;
      try {
        requestBody = Model.solarReturnRequestBody(state.payload, year.n, {
          location: parsed.location, houseSystem: state.solar.houseSystem,
        });
      } catch (error) { setSolarStatus(error.message, "error"); return; }
      state.solar.generation += 1;
      const generation = state.solar.generation;
      state.solar.loading = true;
      refreshSolarBox("正在排太陽回歸盤…", "info", SOLAR_IDS.load);
      post(solarLifecycle, requestBody).then((result) => {
        // 唯一的守衛：清除、表單過期或又按了一次時 generation 已前進。
        if (generation !== state.solar.generation) return;
        state.solar.loading = false;
        let message;
        let tone = "error";
        let focusId = SOLAR_IDS.load;
        if (!result.error && (result.response.status === 404 || result.response.status === 405)) {
          message = "這個伺服器還沒有開放太陽回歸盤；本命盤與時間主星的結果不受影響。";
        } else if (result.error || !result.response.ok || !result.body) { message = failureMessage(result); } else {
          try {
            const panel = Model.solarReturnPanel(result.body, win.ChartViewModel, state.data && state.data.identity);
            // 回來的那一年必須是請求的那一年；對不上就當形狀不符，不把別一年的盤掛在這一年下。
            if (panel.completedYears !== year.n) throw new Error("太陽回歸盤回應形狀不符：年度與請求不同。");
            state.solar.result = { n: year.n, panel };
            message = panel.state === "computed" ? `第 ${year.n + 1} 年的太陽回歸盤已算出。` : `第 ${year.n + 1} 年沒有太陽回歸盤：${panel.text}`;
            tone = "info";
            focusId = SOLAR_IDS.title;
          } catch (_error) {
            // 形狀不符或畫面模型失敗：整格不畫，例外原文不上畫面。
            state.solar.result = null;
            message = "這個版本的頁面無法呈現這次的太陽回歸盤回應。請重新載入頁面。";
          }
        }
        refreshSolarBox(message, tone, focusId);
      });
    }
    function solarPanel(panel) {
      const wrap = node("div", "tl-sr-panel");
      if (panel.state !== "computed") {
        const refusal = node("p", "tl-na");
        refusal.append(node("strong", null, "沒有算。"), doc.createTextNode(panel.text));
        refusal.appendChild(codeNote(panel.code));
        wrap.appendChild(refusal);
        return wrap;
      }
      const facts = node("dl", "tl-sr-facts");
      panel.facts.forEach(([term, value]) => facts.append(node("dt", null, term), node("dd", null, value)));
      wrap.appendChild(facts);
      panel.notes.forEach((text) => wrap.appendChild(node("p", "note", text)));
      if (panel.privacy) wrap.appendChild(node("p", "note tl-sr-privacy", panel.privacy));
      const tableIds = panel.tables.map((_table, index) => `annual-sr-table-${index}`);
      wrap.appendChild(solarWheel(panel, tableIds));
      panel.tables.forEach((table, index) => wrap.appendChild(solarTable(table, tableIds[index])));
      if (panel.comparison) wrap.appendChild(solarComparison(panel.comparison));
      return wrap;
    }
    /** 「與本命盤對照」：三個上升、年之上升落在本命第幾宮、回歸盤行星落在本命哪一宮；只列位置。 */
    function solarComparison(comparison) {
      const section = node("section", "tl-sr-compare");
      section.setAttribute("aria-labelledby", "annual-sr-compare-title");
      const heading = node("h4", "tl-sr-compare-title", comparison.title);
      heading.id = "annual-sr-compare-title";
      const ascendants = node("dl", "tl-sr-ascendants");
      comparison.ascendants.forEach(([term, value]) => ascendants.append(node("dt", null, term), node("dd", null, value)));
      const house = node("p", "tl-sr-asc-house", comparison.ascendantHouse);
      section.append(heading, ascendants, house, solarTable(comparison.table, "annual-sr-compare-table"));
      const note = node("p", "note tl-sr-compare-note", comparison.note.before);
      const link = node("a", null, comparison.note.link);
      link.href = comparison.note.href;
      note.append(link, doc.createTextNode(comparison.note.after));
      section.appendChild(note);
      return section;
    }
    /**
     * 星盤圖：與本命盤同一個區塊元件（ChartWheel.createSection），所以也有「放大檢視」與下載。
     * id 用 annual-sr-wheel-*（不與本命盤重複），標題在「太陽回歸盤」那一格的 h3 底下降成 h4；
     * 圖的名稱帶回歸盤的標題，說明指向圖說與四張表。「在圖內加印輸入摘要」不放：這一格沒有那份摘要。
     */
    function solarWheel(panel, tableIds) {
      const Wheel = win.ChartWheel;
      let section;
      try {
        section = Wheel.createSection(doc, Wheel.buildModel(panel.chart), {
          idPrefix: SOLAR_WHEEL_ID, title: `${panel.heading}的星盤圖`, dialogTitle: `${panel.heading}的星盤圖（放大）`,
          headingLevel: 4, ariaLabel: (model) => `${panel.heading}：${model.ariaLabel}`, includeInput: false, describedBy: tableIds,
          onDownload: (format, _includeInput, _button, showAspects) => downloadSolarWheel(panel, format, showAspects),
        });
      } catch (_error) {
        const figure = node("figure", "tl-sr-wheel");
        figure.appendChild(node("p", "note", "這張回歸盤的星盤圖無法繪製；數值見下方表格。"));
        return figure;
      }
      section.classList.add("tl-sr-wheel");
      return section;
    }
    /** 回歸盤圖的下載：與本命盤同一套畫法；結果已過期或已換掉時不交出。 */
    function downloadSolarWheel(panel, format, showAspects) {
      const shown = state.solar.result;
      if (state.stale || !shown || shown.panel !== panel) return;
      const Wheel = win.ChartWheel;
      let model;
      try { model = Wheel.buildModel(panel.chart, { aspects: showAspects !== false }); } catch (_error) {
        setSolarStatus("下載失敗：這張回歸盤的星盤圖無法繪製。", "error");
        return;
      }
      // 期間若已清除、過期或換了一年，就不交出這張圖。
      Wheel.downloadImage(doc, solarLifecycle, model, format, SOLAR_WHEEL_FILES,
        () => !state.stale && state.solar.result === shown, setSolarStatus);
    }
    function solarTable(table, id) {
      const wrap = node("div", "table-wrap tl-sr-table");
      const label = `${state.solar.result ? state.solar.result.panel.heading : "太陽回歸盤"}：${table.title}`;
      // 窄螢幕上表格在自己的框裡橫捲，框可以用鍵盤捲動（calculate.js 依實際溢出再調整一次）。
      wrap.dataset.regionLabel = label;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", label);
      wrap.tabIndex = 0;
      const element = node("table");
      element.id = id;
      element.appendChild(node("caption", null, table.title));
      const head = node("tr");
      table.columns.forEach((column) => { const th = node("th", null, column); th.scope = "col"; head.appendChild(th); });
      const thead = node("thead");
      thead.appendChild(head);
      const tbody = node("tbody");
      table.rows.forEach((row) => {
        const tr = node("tr");
        row.forEach((cell, index) => {
          const cellNode = node(index === 0 ? "th" : "td", null, String(cell == null ? "" : cell));
          if (index === 0) cellNode.scope = "row";
          tr.appendChild(cellNode);
        });
        tbody.appendChild(tr);
      });
      element.append(thead, tbody);
      wrap.appendChild(element);
      return wrap;
    }
    function syncButton() {
      const button = el(SOLAR_IDS.load);
      if (button) button.disabled = state.stale || state.solar.loading || !state.payload;
      // 圖的下載跟本命盤一樣：表單改動後停用，改回原值再恢復；放大只是換個大小看，照舊可用。
      const wheel = el(SOLAR_WHEEL_ID);
      if (wheel) wheel.querySelectorAll(".chart-wheel-download").forEach((download) => { download.disabled = state.stale; });
    }
    return Object.freeze({ box: solarReturnBox, syncButton, stop: stopSolarReturn, clear: () => solarLifecycle.clear() });
  }

  function deviceToday(win) {
    const date = new win.Date();
    return `${date.getFullYear()}-${Model.pad2(date.getMonth() + 1)}-${Model.pad2(date.getDate())}`;
  }

  function randomToken(win) {
    const bytes = new Uint8Array(12);
    win.crypto.getRandomValues(bytes);
    return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  }

  const panels = new WeakMap();

  function forPage(doc) {
    const host = doc.getElementById("annual");
    if (!host) return null;
    if (!panels.has(host)) {
      const win = doc.defaultView;
      const context = win.ClientContext;
      panels.set(host, createPanel({
        document: doc, window: win, host, postJson: (url, payload, signal) => Lifecycle.postJson(win, url, payload, signal),
        today: () => deviceToday(win), now: () => new win.Date(), token: () => randomToken(win),
        describeError: (detail, status) => context.formatApiError(detail && detail.detail !== undefined ? detail.detail : detail, status),
      }));
    }
    return panels.get(host);
  }

  return Object.freeze({ forPage });
});
