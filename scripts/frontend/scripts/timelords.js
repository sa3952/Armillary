(function attachTimelords(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  // 畫面模型在 timelords-model.js，符號在 chart-glyphs.js，清除與中止在 privacy-lifecycle.js；
  // 頁面在本檔之前載入三者。
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
  // 出生資料只有一個來源：畫面上那張本命盤送出的請求（calculate.js 交給 show()）。本區不另收
  // 任何資料、不寫網址（沒有 #hash、沒有 query）、不用任何瀏覽器儲存；結果清除、過期或離開
  // 頁面時，calculate.js 呼叫 drop()／setStale()，本區跟著丟棄或停用。所有日期都是伺服器給的
  // 出生地日期，本檔不換算日期。元素一律逐個建立，不經過 HTML 字串（Trusted Types）。

  const SVG_NS = "http://www.w3.org/2000/svg";
  const REQUEST_TIMEOUT_MS = 30000;
  const SCROLL_SETTLE_MS = 250;
  // 與 timelords.css 的抽屜斷點相同。
  const NARROW_QUERY = "(max-width: 1100px)";
  const MOBILE_QUERY = "(max-width: 640px)";
  const ZOOMS = Object.freeze([
    ["life", "一生"],
    ["decade", "前後十年"],
    ["year", "本年度"],
  ]);
  const VIEWS = Object.freeze([
    ["timeline", "時間軸"],
    ["yearbook", "逐年年表"],
  ]);
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
    const lifecycle = Lifecycle.createSensitiveDataLifecycle({
      revokeObjectUrl: (url) => win.URL.revokeObjectURL(url),
    });
    // 按需的第二層另用一個請求槽：同一個槽裡新請求會中止舊請求，共用時第二層會中止使用者按下的重排。
    const level2Lifecycle = Lifecycle.createSensitiveDataLifecycle({
      revokeObjectUrl: (url) => win.URL.revokeObjectURL(url),
    });

    const el = (id) => doc.getElementById(id);
    const startButton = el("annual-load");
    const startNote = el("annual-start");
    // 十年期的起點：排出之前選；排出之後改了，「排出時間主星」再出現，按下才重新請求。
    const decennialsProfile = el("annual-dec-profile");
    const decennialsPlanet = el("annual-dec-planet");
    const statusLine = el("annual-status");
    const body = el("annual-body");

    const state = {
      payload: null,
      stale: false,
      loading: false,
      data: null,
      model: null,
      sources: [],
      view: null,
      zoom: "decade",
      yearIndex: -1,
      selected: null,
      generation: 0,
      level2Generation: 0,
      level2Busy: false,
      ...freshLevel2(),
      returnFocus: null,
      decennials: null,
      // 年表各段十年使用者自己打開或收起的狀態（以該段第一個年度的索引為鍵）；重畫時照舊。
      openDecades: new Map(),
    };
    // 伺服器沒有開年度路由（回 404／405）：這是部署狀態，不是這次輸入的問題。記住它，之後同一頁
    // 的每一張盤都直接顯示「尚未開放」，不再送出。
    let routeUnavailable = false;
    let scrollTimer = null;
    // 換年度後的延遲取用，與暫時失敗後的再試（期間 id → 計時器）。
    let yearTimer = null;
    const retryTimers = new Map();

    // ── 小工具 ─────────────────────────────────────────
    function node(tag, className, text) {
      const element = doc.createElement(tag);
      if (className) element.className = className;
      if (text !== undefined && text !== null) element.textContent = text;
      return element;
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

    /** 帶標題的區塊：<section> 以 aria-labelledby 指向它自己的 <h3>。 */
    function titledSection(className, id, title) {
      const section = node("section", className);
      section.setAttribute("aria-labelledby", id);
      const heading = node("h3", null, title);
      heading.id = id;
      return [section, heading];
    }

    /** 把文字片段（字串、{glyph}、{strong}、{mono}、{small}）接到 parent 底下。 */
    function runs(parent, list) {
      (list || []).forEach((run) => {
        if (run === null || run === undefined || run === "") return;
        if (typeof run === "string") { parent.appendChild(doc.createTextNode(run)); return; }
        if (run.glyph) { const svg = glyph(run.glyph); if (svg) parent.appendChild(svg); return; }
        if (run.strong) { parent.appendChild(node("strong", null, run.strong)); return; }
        if (run.mono) { parent.appendChild(node("span", "mono", run.mono)); return; }
        if (run.small) { parent.appendChild(node("span", "tl-small", run.small)); }
      });
      return parent;
    }

    function matches(query) {
      return typeof win.matchMedia === "function" && win.matchMedia(query).matches;
    }

    function reducedMotion() {
      return matches("(prefers-reduced-motion: reduce)");
    }

    function setStatus(message, tone) {
      statusLine.textContent = message;
      statusLine.dataset.tone = tone || "info";
    }

    // ── 請求 ───────────────────────────────────────────
    // 每個槽一次只有一個請求（重排在 state.loading 時不再送，第二層一次一個），所以槽裡的請求只會被
    // drop()、setStale() 或重排開始時中止；那三處都會遞增對應的 generation，回呼只看 generation。
    function post(channel, requestBody) {
      const { controller, token: ticket, timeout: timer } = channel.beginTimedRequest(
        REQUEST_TIMEOUT_MS, win.setTimeout.bind(win), win.AbortController
      );
      // 網址照字寫在這裡：自我檢查頁依這一行列出本頁會送的請求。
      return postJson("/api/chart/annual?projection=page", requestBody, controller.signal)
        .catch((error) => ({ error, timedOut: timer.didTimeout() }))
        .finally(() => {
          win.clearTimeout(timer.handle);
          channel.finishRequest(ticket);
        });
    }

    /** 使用者看得懂的失敗訊息；其他例外（程式錯誤）只顯示通用的一句，不把例外原文放上畫面。 */
    function plainFailure(message) {
      const error = new Error(message);
      error.plain = true;
      return error;
    }

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
        return result.timedOut
          ? `等待超過 ${REQUEST_TIMEOUT_MS / 1000} 秒，已停止等待。`
          : "沒有送達計算服務。請確認連線後再試一次。";
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

    function onDecennialsChange() {
      refreshDecennialsControls();
      if (!state.model || state.loading) return;
      const choice = decennialsChoice();
      const same = state.decennials && choice.profile === state.decennials.profile && choice.planet === state.decennials.planet;
      startNote.hidden = same;
      setStatus(same ? "" : "十年期的起點改了；按「排出時間主星」重新排出。", "info");
    }

    function load() {
      if (!state.payload || state.stale || state.loading) return;
      // 舊起點的第二層與這次重排無關，先停掉；重排進行中也不送新的第二層（pumpLevel2）。
      stopLevel2();
      const generation = state.generation;
      const decennials = decennialsChoice();
      const todayDate = today();
      const birth = state.payload.datetime;
      const estimate = Model.estimateCompletedYears(birth, todayDate);
      state.loading = true;
      startButton.disabled = true;
      setStatus("計算中…", "info");
      const request = (years) => post(lifecycle, Model.annualRequestBody(state.payload, years, { decennials }));
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
          if (outcome.unavailable) {
            routeUnavailable = true;
            showUnavailable();
            return;
          }
          showLoaded(outcome.data, decennials, todayDate, outcome.body);
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
        }
      });
    }

    function showLoaded(data, decennials, todayDate, sourceBody) {
      const model = Model.buildModel(data, todayDate);
      // 一生視窗裡沒有任何算得出的年界（例如出生在可計算範圍的最後一年）：沒有年度可以畫。
      if (!model.years.length) {
        throw plainFailure("這張盤的年界超出本站可以計算的範圍（到西元 2399 年），排不出年度時間主星；本命盤的結果不受影響。");
      }
      state.decennials = decennials;
      // 排在舊結果上的按需請求（例如重排進行中換了年度）屬於舊的那一份，不帶到新結果；
      // 選過的年度（只有這幾年的月小限會從按需回應收下）也從頭記。
      Object.assign(state, freshLevel2());
      clearLevel2Timers();
      state.openDecades = new Map();
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
      post(level2Lifecycle, Model.annualRequestBody(state.payload, next.n, { level2Only: true, decennials: state.decennials })).then((result) => {
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
        } catch (_error) {
          state.level2Failed.add(next.id);
          setStatus("這個版本的頁面無法呈現這次的第二層回應。", "error");
        }
        pumpLevel2();
      });
    }

    // ── 選取 ──────────────────────────────────────────
    function defaultSelection() {
      const tiles = Model.summaryTiles(state.model, state.yearIndex);
      const firdaria = tiles.find((tile) => tile.key === "firdaria" && tile.select);
      const first = tiles.find((tile) => tile.select);
      return (firdaria || first || {}).select || null;
    }

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

    // ── 畫面 ──────────────────────────────────────────
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

    // 第二層回來：只換掉摘要卡與主欄（時間軸或年表），細節欄（手機的抽屜）不動；焦點、捲動位置與
    // 使用者打開的十年照舊。
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
      if (!model.lanes.length) {
        renderUnavailableOnly();
        return;
      }
      body.append(
        viewSwitch(),
        yearNav(),
        summary(),
        node("p", "tl-reference note", Model.referenceNote(model, state.yearIndex)),
      );
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
      body.append(layout, exportBox(), tableExportBox(), conventionsBox(), lotsBox());
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
        item.appendChild(node("span", "tl-code mono", entry.code));
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
      const prev = node("button", null, "‹ 上一年");
      prev.type = "button";
      prev.id = "annual-prev-year";
      prev.disabled = state.yearIndex <= 0;
      prev.addEventListener("click", () => moveYear(-1, prev.id));
      const title = node("span", "tl-year-title", Model.yearTitle(model, state.yearIndex));
      title.id = "annual-year-title";
      title.setAttribute("aria-live", "polite");
      const next = node("button", null, "下一年 ›");
      next.type = "button";
      next.id = "annual-next-year";
      next.disabled = state.yearIndex >= model.years.length - 1;
      next.addEventListener("click", () => moveYear(1, next.id));
      const back = node("button", null, "回到今年");
      back.type = "button";
      back.id = "annual-this-year";
      back.disabled = model.currentIndex < 0 || state.yearIndex === model.currentIndex;
      back.addEventListener("click", () => moveYear(model.currentIndex - state.yearIndex, back.id));
      const range = runs(node("span", "tl-year-range"), Model.yearRange(model, state.yearIndex));
      nav.append(prev, title, next, back, range);
      return nav;
    }

    function moveYear(delta, focusId) {
      const target = state.yearIndex + delta;
      if (target < 0 || target >= state.model.years.length || delta === 0) return;
      state.yearIndex = target;
      state.openDecades.delete(target - (target % 10));
      const tiles = Model.summaryTiles(state.model, target);
      const pick = tiles.find((tile) => tile.key === "firdaria" && tile.select) || tiles.find((tile) => tile.select);
      if (pick) state.selected = pick.select;
      renderAll({ keepScroll: state.zoom === "life" });
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
        card.append(
          node("span", "tl-tile-key", tile.title),
          runs(node("span", "tl-tile-value"), tile.value),
          runs(node("span", "tl-tile-sub"), tile.sub),
        );
        if (tile.gloss) card.appendChild(node("span", "tl-tile-gloss", tile.gloss));
        grid.appendChild(card);
      });
      return grid;
    }

    function warnings() {
      return Model.warningNotices(state.model).map((warning) => {
        const notice = node("p", "tl-notice");
        notice.append(node("strong", null, "注意："), doc.createTextNode(warning.text));
        notice.appendChild(node("span", "tl-code mono", warning.code));
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

    // ── 方案 A：橫向時間軸 ─────────────────────────────
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
      canvas.appendChild(node("div", "tl-axis"));
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
        ["tl-lg-today", "今天"],
        ["tl-lg-year", "年界（每年太陽回到出生位置的時刻）"],
        ["tl-lg-loose", "解鎖（輪完一圈跳到對宮）"],
        ["tl-lg-trunc", "被上一層截斷"],
        ["tl-lg-node", "交點期不分子期"],
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
      const narrow = matches(MOBILE_QUERY);
      const step = state.zoom === "life" ? (narrow ? 20 : 10) : state.zoom === "decade" ? (narrow ? 2 : 1) : 1;
      const axis = canvas.querySelector(".tl-axis");
      axis.replaceChildren();
      model.years.forEach((year) => {
        if (year.n % step) return;
        const tick = node("div", "tl-tick");
        tick.style.left = `${x(year.startDay)}px`;
        tick.appendChild(node("b", null, `${year.n}`));
        tick.appendChild(doc.createElement("br"));
        tick.appendChild(doc.createTextNode(state.zoom === "year"
          ? `${year.start.localDate} ${year.start.localTime || ""}`.trim() : year.start.localDate.slice(0, 4)));
        axis.appendChild(tick);
      });
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
      if (keepLeft !== null && keepLeft !== undefined) {
        scroll.scrollLeft = keepLeft;
      } else if (state.zoom === "life") {
        scroll.scrollLeft = 0;
      } else {
        const centre = state.yearIndex === model.currentIndex && state.zoom !== "year"
          ? model.todayDay : (year.startDay + year.endDay) / 2;
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
          || buttons.find((button) => Number(button.dataset.start) <= reference && reference < Number(button.dataset.end))
          || buttons[0];
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
      } else {
        return;
      }
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

    // ── 方案 B：直向年表 ───────────────────────────────
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
          th.appendChild(node("b", null, `第 ${year.n + 1} 年`));
          if (index === model.currentIndex) th.appendChild(node("span", "tl-now-tag", "今年"));
          th.appendChild(runs(node("span", "tl-book-sub"), [`${year.n} 足歲・`, { mono: year.start.localDate }, " 起"]));
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
        wrap.appendChild(table);
        details.appendChild(wrap);
        section.appendChild(details);
      }
      section.appendChild(node("p", "note", `日期是${Model.DATE_NOTE}。`));
      // 只在紙上出現：列印不展開收著的十年，也不為了列印向伺服器取第二層。
      section.appendChild(node("p", "note tl-print-note", "列印只印畫面上已展開的十年；收著的十年與還沒取到的第二層，列印時不會另外向伺服器取。"));
      return section;
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
          holder.append(doc.createTextNode("↳ "), node("span", "mono", item.start.localDate.slice(5)), doc.createTextNode(" 起 "));
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

    // ── 細節 ──────────────────────────────────────────
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
      detail.rows.forEach(([term, value]) => {
        list.append(node("dt", null, term), runs(node("dd"), value));
      });
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
      content.appendChild(node("p", "tl-detail-foot", Model.FIXED_SENTENCE));
      panel.append(head, content);
    }

    function openDrawer(fromUser) {
      const panel = el("annual-detail");
      if (!panel || !matches(NARROW_QUERY)) return;
      panel.classList.add("is-open");
      if (fromUser) {
        const title = el("annual-detail-title");
        if (title) title.focus({ preventScroll: true });
      }
    }

    function closeDrawer() {
      const panel = el("annual-detail");
      if (!panel) return;
      panel.classList.remove("is-open");
      const back = state.returnFocus;
      state.returnFocus = null;
      if (back && back.isConnected) back.focus({ preventScroll: true });
    }

    // ── 匯出 .ics ──────────────────────────────────────
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
      try {
        artifact = Model.buildIcs(state.model, state.yearIndex, { now: now(), token: token() });
      } catch (error) {
        setStatus(`沒有產生行事曆檔：${error.message}`, "error");
        return;
      }
      deliver(artifact);
      setStatus(`已產生行事曆檔（${artifact.count} 段期間，${Model.ICS_LABEL}）。${monthsState() === "failed" ? ICS_MONTHS_FAILED : ""}`, "info");
    }

    /** 檔案交給瀏覽器下載：Blob 網址登記在本區的生命週期，清除或離開頁面時一併收回。 */
    function deliver(artifact) {
      const blob = new win.Blob([artifact.content], { type: artifact.mime_type });
      const url = lifecycle.registerObjectUrl(win.URL.createObjectURL(blob));
      const anchor = doc.createElement("a");
      anchor.href = url;
      anchor.download = artifact.filename;
      anchor.hidden = true;
      doc.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      win.setTimeout(() => lifecycle.releaseObjectUrl(url), 0);
    }

    // ── 匯出時間主星表 ───────────────────────────────────
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
      try {
        artifact = Model.buildTimeLordTableArtifact(state.model, state.sources, format);
      } catch (error) {
        setStatus(`沒有產生時間主星表：${error.message}`, "error");
        return;
      }
      deliver(artifact);
      setStatus(`已產生時間主星表（${artifact.format_name}，${artifact.count} 段期間，${Model.ICS_LABEL}）。`, "info");
    }

    // ── 約定、擴充點 ───────────────────────────────────
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

    function lotsBox() {
      const lots = Model.extendedLots(state.model);
      const fragment = doc.createDocumentFragment();
      if (!lots.length) return fragment;
      const box = node("details", "tl-box tl-lots");
      box.appendChild(node("summary", null, "七個延伸的阿拉伯點（本命，整宮）"));
      box.appendChild(node("p", "note", "Paulus 的五個點與 Valens 的兩個點；Valens 的兩點加注（Valens），與 Paulus 同名的點分開。只列星座與宮位，不解讀。宮位用整宮：一個星座算一宮。"));
      const table = node("table", "tl-lots-table");
      const head = node("tr");
      ["點", "星座", "宮位"].forEach((text) => { const th = node("th", null, text); th.scope = "col"; head.appendChild(th); });
      const thead = node("thead");
      thead.appendChild(head);
      const tbody = node("tbody");
      lots.forEach((lot) => {
        const row = node("tr");
        const name = node("th", null, lot.name);
        name.scope = "row";
        const sign = node("td");
        const svg = glyph(lot.sign);
        if (svg) sign.appendChild(svg);
        sign.appendChild(doc.createTextNode(Model.signName(lot.sign)));
        row.append(name, sign, node("td", null, `第 ${lot.house} 宮`));
        tbody.appendChild(row);
      });
      table.append(thead, tbody);
      box.appendChild(table);
      return box;
    }

    // ── 狀態與控制項 ───────────────────────────────────
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
      const note = el("annual-ics-months");
      if (note) {
        note.hidden = months === "ready";
        note.textContent = months === "failed" ? ICS_MONTHS_FAILED : months === "pending" ? ICS_MONTHS_PENDING : "";
      }
    }

    function show(payload) {
      drop();
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
      if (scrollTimer !== null) { win.clearTimeout(scrollTimer); scrollTimer = null; }
      clearLevel2Timers();
      Object.assign(state, {
        payload: null, stale: false, loading: false, data: null, model: null, sources: [], view: null,
        zoom: "decade", yearIndex: -1, selected: null, level2Busy: false, ...freshLevel2(),
        returnFocus: null, decennials: null, openDecades: new Map(),
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
        if (busy) setStatus("表單已改動，這次的年度計算已停止。", "info");
      }
      refreshControls();
    }

    startButton.addEventListener("click", load);
    if (decennialsProfile) decennialsProfile.addEventListener("change", onDecennialsChange);
    if (decennialsPlanet) decennialsPlanet.addEventListener("change", onDecennialsChange);
    refreshDecennialsControls();
    // Esc 只關最上層的東西：抽屜開著時只關抽屜（捕獲階段先處理並標記 defaultPrevented，星盤的
    // 點選標示就不跟著清除）。
    doc.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const panel = el("annual-detail");
      if (!panel || !panel.classList.contains("is-open")) return;
      event.preventDefault();
      closeDrawer();
    }, true);

    return Object.freeze({
      show,
      drop,
      setStale,
      // 與按「排出時間主星」同一個動作（計算頁在古典完整算完星盤後呼叫）。
      load,
      // 一頁摘要的一行（選定的那一年由誰輪值）；還沒排出或表單已改動時是 null。
      briefLine: () => (state.model && !state.stale ? Model.briefLine(state.model, state.yearIndex) : null),
      // 測試用：目前狀態的唯讀快照。
      snapshot: () => ({
        view: state.view, zoom: state.zoom, yearIndex: state.yearIndex, selected: state.selected,
        stale: state.stale, hasModel: Boolean(state.model), loaded: state.data ? [...state.data.level2LoadedFor] : [],
      }),
    });
  }

  function deviceToday(win) {
    const date = new win.Date();
    const pad = (value) => String(value).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  }

  function randomToken(win) {
    const bytes = new Uint8Array(12);
    win.crypto.getRandomValues(bytes);
    return [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  }

  function jsonPoster(win) {
    return (url, payload, signal) => win.fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload),
      signal,
    }).then((response) => response.json().catch(() => null).then((parsed) => ({ response, body: parsed })));
  }

  const panels = new WeakMap();

  /** 頁面上的那一個面板（第一次呼叫時接線）；頁面沒有這一區時回 null。 */
  function forPage(doc) {
    const host = doc.getElementById("annual");
    if (!host) return null;
    if (!panels.has(host)) {
      const win = doc.defaultView;
      const context = win.ClientContext;
      panels.set(host, createPanel({
        document: doc,
        window: win,
        host,
        postJson: jsonPoster(win),
        today: () => deviceToday(win),
        now: () => new win.Date(),
        token: () => randomToken(win),
        describeError: (detail, status) => (context && typeof context.formatApiError === "function"
          ? context.formatApiError(detail && detail.detail !== undefined ? detail.detail : detail, status)
          : "年度時間主星沒有算出來。"),
      }));
    }
    return panels.get(host);
  }

  return Object.freeze({ forPage });
});
