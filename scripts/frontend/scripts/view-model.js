(function attachViewModel(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  // 時間尺度與計算模式的標籤只有一份，在 exporters.js；閉集代碼的中文標籤在 labels.js。
  // 頁面在本檔之前載入兩者。
  const api = factory(
    commonJs ? require("./exporters.js") : root.ChartExport,
    commonJs ? require("./labels.js") : root.ArmillaryLabels,
  );
  if (commonJs) module.exports = api;
  if (root) root.ChartViewModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildViewModel(exportPipeline, Labels) {
  "use strict";

  // 本檔是純函式：不碰 DOM、不發 request、不讀全域狀態。
  //
  // 契約 §10 要求的資料流是
  //   backend response -> canonical export document -> sections -> {render, exporters}
  // 渲染與匯出必須是 sections 的兩個平行下游，而不是渲染完再回頭刮畫面。
  // 把「回應 -> sections」與「sections -> 可渲染樹」都放在這裡，
  // 是為了讓這兩步能在 Node 測試裡直接斷言，不必先有瀏覽器。
  //
  // 檔內分區（依出現順序）：共用的格式與收據攤平；模組狀態；時間、天體、軸點、反照點、宮位、
  // 相位與尊貴；其餘各模組（月交點到產前朔望）；阿拉伯點、月空亡與赤緯相位；尊貴的各套分配法；
  // 驗算區段；出生時刻敏感度與取樣摘要；結果頂端的白話摘要；計算收據；速覽；回應 → sections；
  // 十二分部；古典分類；圖表連動的點鍵；sections → view tree。

  // layer 是區段的 layer_label（畫面與匯出都印）；畫面依它找回環的 key。
  const RING = Object.freeze({
    ASTRONOMICAL: { key: "ring-1", layer: "RING I 天文事實" },
    GEOMETRY: { key: "ring-2", layer: "RING II 幾何推導" },
    METHOD: { key: "ring-3", layer: "RING III 方法判斷" },
    VERIFICATION: { key: "ring-v", layer: "VERIFICATION 驗證" },
  });
  const RING_KEY_BY_LAYER = new Map(Object.values(RING).map((ring) => [ring.layer, ring.key]));

  /**
   * 回應側覆蓋宣告：後端能回的每一個模組，這裡都要有交代。
   *
   * 一份多數模組為空的樣本回應不足以定義覆蓋範圍：照它寫成的 view-model 會
   * 讓後端算得出來、畫面卻不承接的模組完全不可見，而測試依然全綠。
   *
   * 因此這份宣告與 `frontend/tests/fixtures/chart-approximate-hour.json`（全部模組開啟的
   * 真實回應）做 exact-set 比對。後端新增模組而這裡沒交代，測試就紅。
   * `section` 表示由哪個 section 承接；`not_rendered` 必須寫出理由，
   * 不接受空白——「忘了做」與「刻意不顯示」必須在這裡就分得開。
   */
  const MODULE_COVERAGE = Object.freeze({
    "astronomical_data.time": { section: "time" },
    "astronomical_data.atmosphere": { section: "time" },
    "astronomical_data.bodies": { section: "bodies" },
    "astronomical_data.nodes": { zh: "月交點", section: "nodes" },
    "astronomical_data.fixed_stars": { zh: "恆星", section: "fixed_stars" },
    "astronomical_data.fixed_star_policy": { section: "fixed_stars" },
    "astronomical_data.lunar_apsides": { zh: "月亮遠近地點", section: "lunar_apsides" },
    "astronomical_data.parallax_moon": { zh: "月亮視差", section: "parallax_moon" },
    "astronomical_data.angles": { zh: "四軸", section: "angles" },
    "astronomical_data.extra_angles": { zh: "額外角點", section: "extra_angles" },
    "astronomical_data.lunar_events": { zh: "朔望與日月食", section: "lunar_events" },
    "astronomical_data.horizon_events": { zh: "升降與中天", section: "horizon_events" },
    "derived_geometry.antiscia": { zh: "反照點", section: "antiscia" },
    "derived_methods.house_division": { zh: "宮位", section: "houses" },
    "derived_methods.planet_in_house": { zh: "行星落宮", section: "planet_in_house" },
    "derived_methods.sect": { zh: "日夜區分", section: "sect" },
    "derived_methods.lots": { zh: "阿拉伯點", section: "lots" },
    "derived_methods.void_of_course": { zh: "月空亡", section: "void_of_course" },
    "derived_methods.declination_aspects": { zh: "赤緯相位", section: "declination_aspects" },
    "derived_methods.aspects": { zh: "相位", section: "aspects" },
    "derived_methods.essential_dignities": { zh: "本質尊貴", section: "dignities" },
    "derived_methods.planetary_hours": { zh: "行星日與行星時", section: "planetary_hours" },
    "derived_methods.dodecatemoria": { zh: "十二分部", section: "dodecatemoria" },
    "derived_methods.lunar_mansions": { zh: "月宿", section: "lunar_mansions" },
    "derived_methods.solar_phase": { zh: "焦傷與光束下", section: "solar_phase" },
    "derived_methods.classical_classifications": { zh: "行星與宮的古典分類", section: "classical_classifications" },

    // 頂層鍵。這份宣告的範圍必須是回應的實際範圍：任何只涵蓋部分資料層的
    // 宣告，都會讓它沒列到的頂層鍵完全不受這道閘門檢查。
    "schema_version": { section: "receipt" },
    "output_contract": { section: "contract" },
    "requested_options": { section: "requested_options" },
    "library_info": { section: "receipt" },
    "computation_mode": { section: "receipt" },
    "calculation_dossier": { section: "receipt" },
    "astronomical_data": { not_rendered: "層容器本身；其下每個模組各自宣告。" },
    "derived_geometry": { not_rendered: "層容器本身；其下每個模組各自宣告。" },
    "derived_methods": { not_rendered: "層容器本身；其下每個模組各自宣告。" },
    "birth_time_sensitivity": { section: "sensitivity" },
    "calculation_trace": { section: "trace" },
  });

  const DASH = "—";

  /** 後端在尊貴模組回英文星座鍵；其餘模組回黃經。統一成 labels.js 的同一套中文名。 */
  const SIGN_BY_KEY = Labels.VOCABULARIES.zodiac_sign;
  /** 依黃經序（0＝牡羊）的同一組名字。 */
  const SIGNS = Object.freeze(Object.values(SIGN_BY_KEY));
  const PLANET_BY_KEY = Object.freeze(Object.fromEntries(
    ["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]
      .map((key) => [key, Labels.VOCABULARIES.body_backend_name[key]]),
  ));

  function signName(key) {
    if (!key) return DASH;
    return presentClosedVocabulary(String(key).toLowerCase(), SIGN_BY_KEY, "星座");
  }

  function rulerName(key) {
    if (!key) return DASH;
    const normalized = String(key).toLowerCase();
    if (Object.hasOwn(PLANET_BY_KEY, normalized)) return PLANET_BY_KEY[normalized];
    return presentClosedVocabulary(normalized, SIGN_BY_KEY, "守護");
  }

  const isRecord = exportPipeline.isRecord;

  function num(value, digits) {
    if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
    return value.toFixed(digits);
  }

  /**
   * 週期量（赤經、方位角、恆星時）的十進位字串：捨入不跨到下一個整數，
   * 與後端 core/formatting.py `degree_text` 同一條 KEEP_DEG 規則。單純
   * toFixed 會把 359.9999996° 印成 360.000000、23.9999999 時印成 24.000000——
   * 一個不在 [0, 360)、[0, 24) 內的值，並經 canonical sections 進入四種匯出。
   */
  function cyclicFixed(value, digits) {
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return num(value, digits);
    const whole = Math.floor(value);
    const text = value.toFixed(digits);
    if (Number(text) >= whole + 1) return digits > 0 ? `${whole}.${"9".repeat(digits)}` : String(whole);
    return text;
  }

  /* ── 結構化收據欄位的攤平 ─────────────────────────────────
     後端有幾個欄位是物件或物件陣列，不是純量。把它們直接放進表格
     儲存格會被字串化成 [object Object]，不會報錯，只是讀不到；其中隱私未涵蓋層
     是 L1 宣稱。所以攤平必須具名，而不是丟一個泛用的 JSON.stringify。 */

  /** 時區資料庫：版本 ＋ 來源；不可用時說出原因（MODULE_REASON_ZH）。 */
  function tzDatabase(value) {
    if (!isRecord(value)) return value === undefined || value === null ? DASH : String(value);
    if (value.available === false) {
      return `不可用（原因：${moduleReason(value.reason_code)}）`;
    }
    const version = value.version || DASH;
    return value.source ? `${version}（${value.source}）` : String(version);
  }

  /** 星曆譜系：狀態、JPL 基礎與適用檔案。 */
  function ephemerisLineage(value) {
    if (!isRecord(value)) return value === undefined || value === null ? DASH : String(value);
    const parts = [];
    if (value.jpl_ephemeris_basis) parts.push(`JPL ${value.jpl_ephemeris_basis}`);
    if (value.representation) parts.push(value.representation);
    if (Array.isArray(value.applies_to) && value.applies_to.length) {
      parts.push(value.applies_to.join("、"));
    }
    if (value.status) parts.push(`狀態：${value.status}`);
    return parts.length ? parts.join("；") : DASH;
  }

  /** 旗標政策：每組旗標的名稱與數值，名稱在前因為數值不可讀。 */
  function flagPolicy(value) {
    if (!isRecord(value)) return value === undefined || value === null ? DASH : String(value);
    const parts = [];
    for (const [group, entry] of Object.entries(value)) {
      if (!isRecord(entry)) {
        parts.push(`${group}：${entry}`);
        continue;
      }
      const names = Array.isArray(entry.names) ? entry.names.join("＋") : DASH;
      parts.push(`${group}：${names}（${entry.value}）`);
    }
    return parts.length ? parts.join("；") : DASH;
  }

  /** 未涵蓋層：層名 ＋ 狀態；備註另行成列，不擠進同一格。 */
  function uncoveredLayers(value) {
    if (!Array.isArray(value) || !value.length) return DASH;
    return value
      .map((entry) => {
        if (!isRecord(entry)) return String(entry);
        return entry.status ? `${entry.layer}（${entry.status}）` : String(entry.layer);
      })
      .join("、");
  }

  // 說明由 horizon_events.contract 導出，說的是表裡真的畫了什麼；
  // 契約沒有的前提不寫，契約改了這裡跟著改。
  function horizonContractNotes(contract) {
    if (!isRecord(contract)) return [];
    const premises = [
      contract.refraction === "enabled" ? "標準大氣折射" : null,
      contract.disc_position === "upper_limb" ? "天體上緣" : null,
    ].filter(Boolean);
    const notes = [
      "上升與下降以觀測地的視地平為準"
      + (premises.length ? `，包含${premises.join("與")}` : "")
      + "；表中逐一列出上升、下降、上中天與下中天的前一次與下一次。",
    ];
    if (contract.upper_transit_is_hour_angle_zero_not_max_altitude === true) {
      notes.push("上中天是時角為 0 的時刻，不是高度最大的時刻。");
    }
    const horizon = isRecord(contract.search_horizon_days) ? contract.search_horizon_days : null;
    if (horizon && typeof horizon.rise === "number" && typeof horizon.upper_transit === "number") {
      notes.push(
        `每一側各自搜尋：升降 ${num(horizon.rise, 0)} 日、中天 ${num(horizon.upper_transit, 0)} 日。`
        + "某一側沒有時刻時，印的是那一側的搜尋結果；「搜尋區間內未找到」與「未搜尋」是不同的兩件事。"
      );
    }
    return notes;
  }

  // 輸出精度是百分之一角秒；一度 = 3600 秒 × 100。
  const TICKS_PER_DEGREE = 360000;
  const TICKS_PER_MINUTE = 6000;

  /** 度轉度分秒。保留正負號，供赤緯與黃緯使用。 */
  function dms(value) {
    if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
    // 先把整個值量化到輸出精度，再切分度／分／秒。反過來做——先用 floor 切分、
    // 最後才對秒 toFixed(2)——會讓 59.996″ 印成 60.00″ 而分位不跟著進位，產出
    // `29°59′60.00″` 這種不存在的六十進位值。黃經是連續量，落在每度最後五毫弧秒
    // 的輸入是可達的，且同一個錯值會經 canonical sections 進入畫面與四種匯出。
    const ticks = Math.round(Math.abs(value) * TICKS_PER_DEGREE);
    const sign = value < 0 && ticks !== 0 ? "-" : "";
    const d = Math.floor(ticks / TICKS_PER_DEGREE);
    const m = Math.floor((ticks % TICKS_PER_DEGREE) / TICKS_PER_MINUTE);
    const s = (ticks % TICKS_PER_MINUTE) / 100;
    return `${sign}${d}°${String(m).padStart(2, "0")}′${s.toFixed(2).padStart(5, "0")}″`;
  }

  /**
   * 後端 `sign_position` 三元陣列 [星座索引, 星座內度分秒, 十進位黃經] 的合法性。
   *
   * 星座與度分秒只有一個產生器：後端 core/formatting.py `sign_position`。
   * 星座歸屬由原始值決定，捨入不跨到下一度（Swiss Ephemeris
   * KEEP_DEG，涵蓋 KEEP_SIGN），所以 359.9999999° 是「雙魚 29°59′59.99″」與
   * 「359.999999」。前端自己量化會先進位再分段，同一個值在這裡寫牡羊、在尊貴表寫
   * 雙魚，十進位欄印出 360.000000；所以這裡只照印，不自己捨入。
   */
  function isSignPosition(position) {
    return Array.isArray(position)
      && Number.isInteger(position[0]) && position[0] >= 0 && position[0] < 12
      && typeof position[1] === "string" && typeof position[2] === "string";
  }

  /** 星座度數欄：「雙魚 29°59′59.99″」。 */
  function signPosition(position) {
    return isSignPosition(position) ? `${SIGNS[position[0]]} ${position[1]}` : DASH;
  }

  /** 黃經欄：後端依同一條規則寫好的十進位字串，不會出現 360.000000。 */
  function longitudeText(position) {
    return isSignPosition(position) ? position[2] : DASH;
  }

  /** 一列的「黃經、星座度數」兩格。 */
  function positionCells(position) {
    return [longitudeText(position), signPosition(position)];
  }

  /**
   * 把後端收據翻成 section 狀態。
   *
   * 四個布林的組合語義各不相同，這個函式是唯一決定它們如何映射到畫面狀態的地方。
   * 特別是「requested=true 但 applicable=false」必須成為 refused 而不是 not_requested——
   * 前者是產品明確拒絕並附理由，後者只是使用者沒勾。
   */
  function receiptStatus(receipt) {
    // 只讀分支用得到的欄位，而且每一個都必須是布林：缺一個就會把「已請求」讀成
    // 「未請求」、把「不適用」讀成「已計算」。
    const flag = (key) => {
      if (typeof receipt[key] !== "boolean") {
        throw exportPipeline.incompleteResponse(`模組收據缺少布林欄位 ${key}`);
      }
      return receipt[key];
    };
    if (!isRecord(receipt)) throw exportPipeline.incompleteResponse("模組收據不是紀錄");
    if (!flag("requested")) return { state: "not_requested" };
    if (!flag("applicable")) {
      return { state: "refused", reason_code: receipt.reason_code || "" };
    }
    // available=false 不論 executed 與否都不是 present：option_states 對「要求了但
    // 沒算出來」回的是 executed=false, available=false（例如年份尾端的朔望）。
    if (!flag("available")) {
      return {
        state: "executed_unavailable",
        reason_code: receipt.reason_code || "",
      };
    }
    return { state: "present" };
  }

  /* ── 模組狀態的單一產生器──────────────────
     後端在 calculation_dossier.calculation_policy 裡對每一個選項
     （option_states[<option>]：requested／applicable／executed／available／reason_code）
     與每一個模組（modules[<module>]：computed／not_requested／not_applicable）
     各給一份狀態。畫面不得再從「容器是不是空的」猜狀態：
       requested=false                  -> not_requested（仍列在索引，不刪）
       requested=true, applicable=false -> refused（附 reason_code）
       requested=true, 容器卻是空的      -> executed_unavailable，絕不摺成 not_requested
     權威是否在、是否完整由 exporters 的 assertRenderableResponse 在 buildSections 開頭檢查；
     某一區在權威裡找不到自己的狀態時拒絕整份回應，不從容器是否為空去猜。 */
  function calculationPolicy(response) {
    const dossier = response.calculation_dossier;
    const policy = isRecord(dossier) ? dossier.calculation_policy : null;
    return isRecord(policy) ? policy : {};
  }
  function optionState(response, optionKey) {
    if (!optionKey) return null;
    const states = calculationPolicy(response).option_states;
    if (!isRecord(states)) return null;
    const entry = states[optionKey];
    return isRecord(entry) ? entry : null;
  }
  function policyModuleState(response, moduleKey) {
    if (!moduleKey) return null;
    const modules = calculationPolicy(response).modules;
    if (!isRecord(modules)) return null;
    const value = modules[moduleKey];
    return typeof value === "string" ? value : null;
  }
  // calculation_policy.modules 的值對應的狀態；computed 不在表裡：它不推翻任何來源。
  const POLICY_MODULE_STATUS = Object.freeze({
    not_requested: Object.freeze({ state: "not_requested" }),
    not_applicable: Object.freeze({ state: "refused", reason_code: "" }),
  });
  /**
   * 一區的狀態。優先序：模組容器自己的收據、option_states、modules，依序取第一個「不是
   * present」的來源；三者都是 present 或沒說，才是 present。容器的收據不是權威（輸出契約）：
   * option_states 與 modules 都沒有這一區時拒絕整份回應（heliocentric 下 sect／lots 物件沒有
   * 收據欄位，只有 option_states 帶 module_not_applicable）。之後兩步只補細節：被拒絕卻沒有
   * 理由時依序取 option_states、容器的 reason_code；present 而容器沒有可畫的內容時降為
   * executed_unavailable。
   * @param {object} response 後端回應
   * @param {{option?: string, module?: string}} keys 這個 section 對應的選項鍵與模組鍵
   * @param {*} container 模組容器（物件或陣列）
   * @param {boolean} hasContent 容器是否真的有可渲染內容
   */
  function moduleState(response, keys, container, hasContent) {
    // 先問鍵在不在再讀值：沒有收據欄位的容器不讀那個鍵（module_coverage 的負控制記下每一次讀取）。
    const own = isRecord(container) && "requested" in container && typeof container.requested === "boolean"
      ? receiptStatus(container) : null;
    const option = optionState(response, keys.option);
    const fromModules = policyModuleState(response, keys.module);
    if (!option && !fromModules) {
      throw exportPipeline.incompleteResponse(
        `${keys.option || keys.module || "未具名模組"} 沒有可核對的狀態`
      );
    }
    const sources = [
      () => own,
      () => (option ? receiptStatus(option) : null),
      () => { const found = Labels.ownLabel(POLICY_MODULE_STATUS, fromModules); return found && { ...found }; },
    ];
    let status = { state: "present" };
    for (const source of sources) {
      const found = source();
      if (found && found.state !== "present") { status = found; break; }
    }
    if (status.state === "refused" && !status.reason_code) {
      const fallback = (option && option.reason_code)
        || (isRecord(container) && "reason_code" in container && container.reason_code) || "";
      return { state: "refused", reason_code: fallback };
    }
    if (status.state === "present" && !hasContent) {
      return { state: "executed_unavailable", reason_code: (option && option.reason_code) || "" };
    }
    return status;
  }

  /** 非 present 狀態的 section：不畫表，狀態與理由寫在 notes。 */
  function absentSectionFor(id, title, ring, notRequestedNote, status) {
    const state = status && status.state;
    const reason = (status && status.reason_code) || "";
    let note = notRequestedNote;
    if (state === "refused") {
      note = "這次沒有輸出這個模組。"
        + `原因：${moduleReason(reason)}。`;
    } else if (state === "executed_unavailable") {
      note = "已請求這個模組，但後端沒有回可用結果。"
        + `原因：${moduleReason(reason)}。`;
    }
    return makeSection(id, title, ring, status || { state: "not_requested" }, { notes: [note] });
  }

  /** 未請求的模組仍然要出現在畫面上，帶著「未請求」而不是被靜默省略。 */
  function absentSection(id, title, ring, note) {
    return makeSection(id, title, ring, { state: "not_requested" }, { notes: [note] });
  }

  /**
   * 一區的共同欄位：層級標籤取自環，notes／tables／blocks 沒給就是空的。匯出的鍵序由
   * exporters 的 normalizeSection 決定，不由這裡。
   */
  function makeSection(id, title, ring, status, body = {}) {
    return { id, title, layer_label: ring.layer, status, notes: [], tables: [], blocks: [], ...body };
  }

  // ── 時間、天體、軸點、反照點、宮位、相位與尊貴 ─────────────────────
  // 時間尺度依時代標示：1930 年、2040 年的盤不是 UTC（方法頁 §07.6）。
  // 標籤與匯出共用 exporters.js 的那一份。
  const TIME_SCALE_ZH = exportPipeline.TIME_SCALE_ZH;

  function timeScaleLabel(era) {
    if (era === undefined || era === null) return "時間尺度未標明";
    return presentClosedVocabulary(era, TIME_SCALE_ZH, "時間尺度");
  }

  /** 一張表的時刻若同屬一個時間尺度，標在標題；跨尺度時逐格標。 */
  function timedTable(baseTitle, eras, qualifier) {
    const labels = [...new Set(eras.map(timeScaleLabel))];
    const mixed = labels.length > 1;
    const parts = [qualifier, labels.length === 1 ? labels[0] : null].filter(Boolean);
    return {
      title: parts.length ? `${baseTitle}（${parts.join("，")}）` : baseTitle,
      cell: (value, era) => (mixed && value !== DASH ? `${value}（${timeScaleLabel(era)}）` : value),
      heading: (base) => (labels.length === 1 ? `${base}（${labels[0]}）` : base),
    };
  }

  /**
   * 歷史地方平時有秒級偏移（上海 1900 +08:05:43），兩位小數的小時看不出來，所以秒不為零時印出秒。
   * 寫成「UTC+08:00」而不是「+08:00」：以正負號開頭的儲存格會被試算表讀成公式，CSV 與區段複製
   * 就得加撇號，同一欄有的帶、有的不帶；負號用 ASCII「-」，與度分秒一致。收據數值欄位不變。
   */
  function utcOffsetText(hours) {
    if (typeof hours !== "number" || !Number.isFinite(hours)) return DASH;
    const total = Math.round(Math.abs(hours) * 3600);
    const pad = (value) => String(value).padStart(2, "0");
    const seconds = total % 60;
    const hm = `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}`;
    return `UTC${hours < 0 ? "-" : "+"}${hm}${seconds ? `:${pad(seconds)}` : ""}`;
  }

  function timeSection(response) {
    const time = response.astronomical_data.time || {};
    const atmosphere = response.astronomical_data.atmosphere || {};
    const anchored = time.input_semantics
      && time.input_semantics !== "exact_birth_time";
    const scale = timeScaleLabel(time.time_scale_era);
    const notes = [
      `所有時刻均標明時間尺度；${scale}這一欄是換算結果，不是輸入。`,
    ];
    if (time.time_scale_era && time.time_scale_era !== "modern_leap_second_utc") {
      notes.push(`這張盤的時刻屬於「${scale}」，不是以閏秒維持的現代 UTC；見方法頁 §07.6。`);
    }
    if (anchored) {
      notes.unshift(
        "這一欄是計算用的代表性時刻，不是出生時刻。"
      );
    }
    return makeSection("time", "時間轉換", RING.ASTRONOMICAL, { state: "present" }, {
      notes,
      tables: [{
        title: "時間",
        columns: ["項目", "數值"],
        rows: [
          [anchored ? "代表性錨點（非出生時刻）" : "本地時間", time.input_local_time],
          ["時區", Labels.timezoneText(time.timezone_label)],
          ["UTC 偏移", utcOffsetText(time.utc_offset_hours)],
          [scale, time.utc_time],
          ["儒略日 JD(UT)", num(time.jd_ut, 6)],
          ["ΔT（秒）", num(time.delta_t_seconds, 3)],
          ["地方真恆星時 LAST（小時）", cyclicFixed(time.last_hours, 6)],
          ["真黃赤交角 ε", dms(time.true_obliquity)],
          // 頁面永遠送 pressure_hpa=null，後端以 pressure_mode 說明
          // 它怎麼補；這裡讀的是後端真的會發的欄位（atmosphere.pressure_mode）。
          ["折射計算溫度（°C）", num(atmosphere.temperature_c, 1)],
          ["折射計算氣壓（hPa）", atmosphere.pressure_hpa === null || atmosphere.pressure_hpa === undefined
            ? `未指定，${presentClosedVocabulary(atmosphere.pressure_mode, PRESSURE_MODE_ZH, "氣壓模式")}`
            : num(atmosphere.pressure_hpa, 1)],
          ["氣壓來源", presentClosedVocabulary(atmosphere.pressure_mode, PRESSURE_MODE_ZH, "氣壓模式")],
          ["折射模型", presentClosedVocabulary(atmosphere.refraction, REFRACTION_MODEL_ZH, "折射模型")],
        ],
      }],
    });
  }

  function bodiesSection(response) {
    const bodies = response.astronomical_data.bodies || [];
    return makeSection("bodies", "天體位置", RING.ASTRONOMICAL, { state: bodies.length ? "present" : "executed_unavailable" }, {
      notes: [
        "黃道、赤道、地平三套座標一次輸出，不必換工具重填生辰。",
        "星座與宮內度數由後端黃經以 30° 分段換寫，非另一次計算；完整精度在『運算結果＋驗算資料』的 JSON 匯出中。",
        bodies.some((body) => body.speed_position_derivative_status
          === "known_internal_disagreement_for_sun_moon")
          ? "站心速度為 Swiss FLG_SPEED 解析值；太陽／月亮部分欄位已知不等於同次位置的有限差分導數，請勿把它當作已驗證的導數精度。"
          : null,
        // 後端對只有日期的請求不輸出地平座標（reason_code date_only_no_birth_time）。
        response.birth_time_sensitivity.precision === "date_only"
          ? "只有出生日期：沒有出生時刻就沒有對應的地平位置，方位角與高度不列出。"
          : null,
      ].filter(Boolean),
      tables: [{
        title: "本命天體",
        columns: BODY_COLUMNS,
        rows: bodyRows(bodies),
      }],
    });
  }

  function anglesSection(response) {
    // 宮位沒有請求時軸點容器是 null；是否請求由 option_states 說，不由 null 推定。
    const angles = response.astronomical_data.angles;
    const positions = isRecord(angles) && isRecord(angles.sign_positions) ? angles.sign_positions : {};
    const status = moduleState(
      response,
      { option: requestingOption(response, "astronomical_data.angles", "include_houses") },
      angles,
      Object.keys(positions).length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("angles", "軸點", RING.ASTRONOMICAL, "本次未產生軸點計算。", status);
    }
    const rows = Object.entries(Labels.VOCABULARIES.angle_label)
      .map(([key, label]) => [label, ...positionCells(positions[key])]);
    return makeSection("angles", "軸點", RING.ASTRONOMICAL, status, {
      notes: ["軸點由地方恆星時與觀測地緯度決定，與宮位制的選擇無關。"],
      tables: [{
        title: "四軸",
        columns: ["軸點", LONGITUDE_COLUMN, "星座度數"],
        rows,
      }],
    });
  }

  /**
   * 依本次回應實際的黃道印公式。鏡軸固定在回歸黃道的至點軸與分點軸，
   * 恆星黃道下後端用 180°−λ−2×ayanamsa（core/antiscia.py）；只印回歸黃道的公式，
   * 使用者拿畫面上的恆星黃經照算會差兩倍 ayanamsa。
   */
  function antisciaFormulaNotes(response) {
    const ayanamsa = (response.astronomical_data.time || {}).ayanamsa;
    if (typeof ayanamsa === "number" && Number.isFinite(ayanamsa) && ayanamsa !== 0) {
      return [
        `反照點 λ′ = 180° − λ − 2×ayanamsa；反向反照點 λ″ = 360° − λ − 2×ayanamsa（本次 ayanamsa = ${num(ayanamsa, 6)}°）。`,
        "鏡軸固定在回歸黃道的至點軸與分點軸，所以恆星黃經要先扣回兩倍 ayanamsa。",
      ];
    }
    return [
      "反照點 λ′ = 180° − λ（以 0° 巨蟹—0° 摩羯 為鏡軸）；反向反照點 λ″ = 360° − λ（以 0° 牡羊—0° 天秤 為鏡軸）。",
    ];
  }

  function antisciaSection(response) {
    const antiscia = response.derived_geometry.antiscia;
    const direct = isRecord(antiscia) && Array.isArray(antiscia.antiscia) ? antiscia.antiscia : [];
    const contra = isRecord(antiscia) && Array.isArray(antiscia.contra_antiscia)
      ? antiscia.contra_antiscia : [];
    const antisciaStatus = moduleState(
      response, { option: "include_antiscia", module: "antiscia" }, antiscia, direct.length > 0
    );
    if (antisciaStatus.state !== "present") {
      return absentSectionFor(
        "antiscia",
        "反照點 Antiscia",
        RING.GEOMETRY,
        "本次未請求。座標轉換本身不需要技法選擇；勾選後公式會直接印在數值上方。",
        antisciaStatus
      );
    }
    const byKey = new Map();
    direct.forEach((p) => byKey.set(p.key, { name: p.name || p.key, antiscion: p.sign_position }));
    contra.forEach((p) => {
      const entry = byKey.get(p.key) || { name: p.name || p.key };
      entry.contra = p.sign_position;
      byKey.set(p.key, entry);
    });
    return makeSection("antiscia", "反照點 Antiscia", RING.GEOMETRY, antisciaStatus, {
      notes: antisciaFormulaNotes(response).concat([
        "只提供幾何鏡像位置，不自動作關係或容許度判定。",
      ]),
      tables: [{
        title: "反照點與反向反照點",
        columns: ["天體", "反照點 λ′", "反照點星座度數", "反向反照點", "反向反照點星座度數"],
        rows: [...byKey.values()].map((e) => [
          e.name,
          ...positionCells(e.antiscion),
          ...positionCells(e.contra),
        ]),
      }],
    });
  }

  /** 宮位制的名稱（labels.js；星盤圖頁尾同一句）。 */
  function houseSystemText(givenCode, name) {
    return Labels.houseSystemText(givenCode, name) || DASH;
  }

  /** 宮位 notes：宮位制，以及 house_division.availability 不是 available 時的說明。 */
  function houseNotes(houses) {
    const notes = [`宮位制：${houseSystemText(houses.system_code, houses.system_name)}。`];
    const availability = isRecord(houses.availability) ? houses.availability : null;
    if (availability && availability.state !== "available") {
      notes.push(
        `宮位可用狀態：${presentClosedVocabulary(availability.state, HOUSE_AVAILABILITY_ZH, "宮位可用狀態")}。`
      );
    }
    return notes;
  }

  function housesSection(response) {
    const houses = response.derived_methods.house_division;
    const cusps = isRecord(houses) && Array.isArray(houses.cusps) ? houses.cusps : [];
    const housesStatus = moduleState(
      response, { option: "include_houses", module: "house_division" }, houses,
      cusps.length > 0 && houses.execution_status === "computed"
    );
    if (housesStatus.state !== "present") {
      return absentSectionFor(
        "houses", "宮位分割", RING.METHOD, "本次未請求宮位。", housesStatus
      );
    }
    return makeSection("houses", "宮位分割", RING.METHOD, housesStatus, {
      notes: houseNotes(houses),
      tables: [{
        title: "宮頭",
        columns: ["宮", LONGITUDE_COLUMN, "星座度數"],
        rows: cusps.map((cusp, index) => [
          `第 ${index + 1} 宮`,
          ...positionCells(
            Array.isArray(houses.cusp_sign_positions) ? houses.cusp_sign_positions[index] : null
          ),
        ]),
      }],
    });
  }

  // 每一格讀後端 aspects.py 的閉集（APPLYING_STATES、PERFECTION_STATUSES）
  // 與 pair record 的真欄位；前端不自己推入離、不自己命名相位。
  function signedNum(value, digits) {
    if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
    return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
  }

  /** 軸點組合沒有整宮 doctrine——「不適用」；兩星的星座不成相位時是後端的名稱「不合意」，不是「無」。 */
  function wholeSignCell(ws) {
    if ("applicable" in ws && ws.applicable === false) return "不適用";
    return ws.configuration_zh || DASH;
  }

  /** 整宮層不合意的組合：後端另列的清單（含沒有列進逐度相位表的組合）。 */
  function wholeSignAversions(aspects) {
    if (!("whole_sign_aversions" in aspects)) return [];
    if (!Array.isArray(aspects.whole_sign_aversions)) {
      throw exportPipeline.incompleteResponse("aspects.whole_sign_aversions 不是陣列");
    }
    return aspects.whole_sign_aversions.filter(isRecord);
  }

  // 名稱取後端參與者清單（participants）的名稱；頁面視圖的不合意清單只帶鍵。
  const pairName = (pair, names) => {
    const name = (key, own) => (names && names.get(key)) || own || key || DASH;
    return `${name(pair.body_a, pair.body_a_name)} — ${name(pair.body_b, pair.body_b_name)}`;
  };

  /** 兩星座差幾個星座：後端給順行方向的差（0–11），兩個方向取小的那一個。 */
  function signGapText(signed) {
    if (!Number.isInteger(signed) || signed < 0 || signed > 11) return DASH;
    const gap = Math.min(signed, 12 - signed);
    return gap === 1 ? "相鄰（差 1 個星座）" : `差 ${gap} 個星座`;
  }

  function aversionTable(aversions, aspects) {
    if (!aversions.length) return null;
    const names = new Map((Array.isArray(aspects.participants) ? aspects.participants : [])
      .filter(isRecord).map((item) => [item.key, item.name]));
    return {
      title: "不合意的組合（整宮）",
      columns: ["組合", "兩星所在星座"],
      rows: aversions.map((row) => [pairName(row, names), signGapText(row.signed_sign_distance)]),
    };
  }

  // 〈位置〉章排在〈宮位與相位〉章之前，讀者先讀到這一句，書名原文附在這裡（每份只附一次）。
  const PRENATAL_SYZYGY_NOTE = "產前朔望是出生前最近一次朔或望。Ptolemy 用它的度數來定出生的上升度數"
    + "（《占星四書》（Tetrabiblos）III.2），"
    + "選壽命主宰時也用它（III.10）。本站只列出時刻與度數（見「產前朔望與出生前日月食的度數」一節），"
    + "不拿它去推算上升點或壽命。";

  const AVERSION_NOTE = "不合意（aversion）：兩顆星所在的星座相鄰，或差 5 個星座，"
    + "彼此不成合、六分、四分、三分、對分任何一種相位。"
    + "Ptolemy《占星四書》卷一第 16 章把這樣的星座稱為「不相連」（disjunct），"
    + "說它們彼此沒有關聯、像是互相背對；這是該書的分類，照原文列出。"
    + "「不合意的組合」一表列出本盤每一組這樣的組合；上升點與中天不參加星座這一層的判斷，不列。";

  /**
   * 最近相位那一格的判定。後端只在 aspect_targets 存一份（ASPECT_TARGET_LISTING 的
   * nearest_aspect_entry 保證列出）；pair 頂層不再抄寫。沒有最近相位時三欄是 —；
   * 有最近相位卻找不到那一格就是契約破損，不以空白掩蓋。
   */
  function nearestTarget(pair) {
    if (!isRecord(pair.nearest_aspect)) return null;
    const key = pair.nearest_aspect.key;
    const target = Array.isArray(pair.aspect_targets)
      ? pair.aspect_targets.find((item) => isRecord(item) && item.key === key)
      : undefined;
    if (!target) {
      throw exportPipeline.incompleteResponse("相位資料缺少最近相位的判定（aspect_targets）");
    }
    return target;
  }

  function applyingCell(pair, target) {
    if (!target) return DASH;
    if (target.applying === null || target.applying === undefined) {
      return pair.applying_reason_code
        ? presentClosedVocabulary(pair.applying_reason_code, APPLYING_REASON_ZH, "入出相位理由")
        : DASH;
    }
    return presentClosedVocabulary(target.applying, APPLYING_ZH, "入出相位狀態");
  }

  function partileCell(target) {
    if (!target) return DASH;
    if (target.partile === true) return "是";
    if (target.partile === false) {
      return target.partile_reason_code
        && Object.hasOwn(PARTILE_FALSE_REASON_ZH, target.partile_reason_code)
        ? PARTILE_FALSE_REASON_ZH[target.partile_reason_code]
        : "否";
    }
    return target.partile_reason_code
      ? presentClosedVocabulary(target.partile_reason_code, PARTILE_REASON_ZH, "同度理由")
      : DASH;
  }

  function perfectionCell(target) {
    if (!target) return DASH;
    const status = target.perfection_status;
    const perfection = isRecord(target.perfection) ? target.perfection : null;
    if (status === "found" && perfection && Array.isArray(perfection.hours_from_chart_moment)
      && typeof perfection.hours_from_chart_moment[0] === "number") {
      const count = perfection.hours_from_chart_moment.length;
      return `${perfection.hours_from_chart_moment[0].toFixed(2)} 小時後`
        + (count > 1 ? `（搜尋窗內共 ${count} 次）` : "");
    }
    if (status === "searched_no_root" && perfection
      && typeof perfection.search_window_days === "number") {
      return `搜尋過但 ${perfection.search_window_days} 日內沒有找到交會`;
    }
    // 完成時刻只對此刻入相位者搜尋；其餘三種相態各自說出為何沒搜尋。
    if (status === "not_applying"
      && Object.hasOwn(NOT_APPLYING_PHASE_ZH, target.applying)) {
      return NOT_APPLYING_PHASE_ZH[target.applying];
    }
    return presentClosedVocabulary(status, PERFECTION_STATUS_ZH, "完成狀態");
  }

  /** 容許度內的相位：名稱取自後端 degree_based.aspect_names_zh（唯一產生器），前端不另存相位名表。 */
  function inOrbCell(pair, target, orbUnavailable, zhByKey) {
    const keys = Array.isArray(pair.aspects_in_orb) ? pair.aspects_in_orb : [];
    if (keys.length) {
      return keys.map((key) => zhByKey.get(key) || `未識別的相位（${key}）`).join("、");
    }
    if (orbUnavailable) return "未套用容許度";
    if (target && target.in_orb === null && target.in_orb_reason_code) {
      return presentClosedVocabulary(target.in_orb_reason_code, IN_ORB_REASON_ZH, "容許度理由");
    }
    return "無";
  }

  /** 已套用容許度時說出依據與可切換。 */
  function orbAppliedNote(response, degree, orbReceipt) {
    const option = optionState(response, "aspect_orb_profile");
    const origin = option && option.input_presence === "defaulted" ? "產品預設" : "本次選定";
    if (isRecord(degree.orb_profile_detail)) {
      return `相位依〈${degree.orb_profile_detail.display_name || DASH}〉判定`
        + `（${origin}的容許度表），可在進階選項切換。`;
    }
    if (typeof orbReceipt.fixed_pair_threshold_degrees === "number") {
      return `相位依固定容許度 ${num(orbReceipt.fixed_pair_threshold_degrees, 1)}° 判定，可在進階選項切換。`;
    }
    return "相位已套用容許度判定，可在進階選項切換。";
  }

  /**
   * 後端只列有相位的組合（逐度在容許度內或 partile，或整宮成相位），
   * 含上升點／中天的組合一律列出；其餘只給數量（pair_listing）。規則與數量都說出來，
   * 表格少了的列才不會被讀成「沒算」。數量為 0 時不加這句。
   */
  function unlistedPairsNote(aspects, degree, orbUnavailable) {
    const listing = isRecord(aspects.pair_listing) ? aspects.pair_listing : null;
    const count = listing ? listing.unlisted_pairs_without_aspect : null;
    if (typeof count !== "number" || !(count > 0)) return null;
    const angles = isRecord(degree.angle_participation)
      && degree.angle_participation.executed === true;
    const rule = orbUnavailable
      ? "表中只列兩星的星座成相位或判為同度的組合（目前沒有選定容許度表，逐度層沒有判定）"
      : "表中只列有相位的組合：在容許度內，或兩星的星座成相位，或判為同度";
    const angleRule = angles ? "；含上升點或中天的組合一律列出" : "";
    const rest = orbUnavailable
      ? `其餘 ${count} 組的星座不合意，不在這張表，列在「不合意的組合」。`
      : `其餘 ${count} 組沒有相位（星座不合意，逐度也不在容許度內），不在這張表，列在「不合意的組合」。`;
    return `${rule}${angleRule}。${rest}`;
  }

  // 相位方格裡的入／出相位縮寫；鍵同 APPLYING_ZH（core/aspects.py APPLYING_STATES）。
  const APPLYING_SHORT_ZH = Object.freeze({
    applying: "入",
    exact_now: "精確",
    separating: "出",
    indeterminate_relative_station: "方向未定",
  });

  /**
   * 相位方格：同一份 pairs 排成三角形，不另算。列是第 2 到最後一個參與者，欄是第 1 到倒數
   * 第二個；一格是容許度內的每個相位（名稱、距精確的度數、入／出），容許度內沒有相位但
   * 兩星的星座成相位時寫「整宮」加名稱。後端沒列出的組合（沒有相位）與對角線以上留空。
   */
  function aspectGridTable(aspects, zhByKey) {
    const participants = Array.isArray(aspects.participants)
      ? aspects.participants.filter((item) => isRecord(item) && item.key)
      : [];
    if (participants.length < 2) return null;
    const index = new Map(participants.map((item, position) => [item.key, position]));
    const cells = new Map();
    (aspects.pairs || []).forEach((pair) => {
      const a = index.get(pair.body_a);
      const b = index.get(pair.body_b);
      if (a === undefined || b === undefined) {
        throw exportPipeline.incompleteResponse("相位組合的天體不在參與者清單裡");
      }
      const targets = Array.isArray(pair.aspect_targets) ? pair.aspect_targets : [];
      const inOrb = targets.filter((target) => isRecord(target) && target.in_orb === true);
      const ws = isRecord(pair.whole_sign) ? pair.whole_sign : {};
      const text = inOrb.length
        ? inOrb.map((target) => [
          zhByKey.get(target.key) || `未識別的相位（${target.key}）`,
          typeof target.offset_from_exact_degrees === "number"
            ? `${num(Math.abs(target.offset_from_exact_degrees), 2)}°` : DASH,
          target.applying === null || target.applying === undefined
            ? null : presentClosedVocabulary(target.applying, APPLYING_SHORT_ZH, "入出相位狀態"),
        ].filter(Boolean).join(" ")).join("；")
        // 軸點組合沒有整宮 doctrine（applicable=false），不讀它的 in_aspect。
        : ("applicable" in ws && ws.applicable === false)
          ? DASH
          : ws.in_aspect === true ? `整宮${ws.configuration_zh || DASH}` : (ws.configuration_zh || DASH);
      cells.set(`${Math.max(a, b)}:${Math.min(a, b)}`, text);
    });
    // 沒有列進逐度相位表的不合意組合，方格裡也寫出名稱，不留白。
    wholeSignAversions(aspects).forEach((row) => {
      const a = index.get(row.body_a);
      const b = index.get(row.body_b);
      if (a === undefined || b === undefined) {
        throw exportPipeline.incompleteResponse("不合意的組合裡的天體不在參與者清單裡");
      }
      const key = `${Math.max(a, b)}:${Math.min(a, b)}`;
      if (!cells.has(key)) cells.set(key, row.configuration_zh || DASH);
    });
    const names = participants.map((item) => item.name || item.key);
    return {
      title: "相位方格",
      variant: "aspect_grid",
      columns: ["天體", ...names.slice(0, -1)],
      rows: names.slice(1).map((name, row) => [
        name,
        ...names.slice(0, -1).map((_other, column) => (
          column <= row ? (cells.get(`${row + 1}:${column}`) ?? "") : ""
        )),
      ]),
    };
  }

  function aspectsSection(response) {
    const aspects = response.derived_methods.aspects;
    // pairs 在 aspects 的**頂層**，不在 degree_based 底下。取錯層級的
    // `a || b || []` 會永遠回空陣列且永遠不報錯，表格就靜靜地空著。
    if (isRecord(aspects) && "pairs" in aspects && !Array.isArray(aspects.pairs)) {
      throw exportPipeline.incompleteResponse("aspects.pairs 不是陣列");
    }
    const pairs = isRecord(aspects) && Array.isArray(aspects.pairs) ? aspects.pairs : [];
    const aspectsStatus = moduleState(
      response, { option: "include_aspects", module: "aspects" }, aspects,
      isRecord(aspects) && Array.isArray(aspects.pairs)
    );
    if (aspectsStatus.state !== "present") {
      return absentSectionFor("aspects", "相位", RING.METHOD, "本次未請求相位。", aspectsStatus);
    }
    const degree = isRecord(aspects.degree_based) ? aspects.degree_based : {};
    const orbReceipt = isRecord(degree.orb_receipt) ? degree.orb_receipt : {};
    const orbUnavailable = degree.orb_verdict_available === false;
    const notes = [];
    if (orbUnavailable) {
      notes.push(
        "目前沒有選定容許度（orb）表，因此每一組相位只有幾何角距離，"
        + "沒有「是否在容許度內」的判定。"
        + "你可以先看幾何關係，或回到選項指定一套容許度來源。"
      );
    } else {
      notes.push(orbAppliedNote(response, degree, orbReceipt));
    }
    const unlisted = unlistedPairsNote(aspects, degree, orbUnavailable);
    if (unlisted) notes.push(unlisted);
    // 三欄讀的是 aspect_targets 中最近相位那一格（nearestTarget）；
    // 每個相位各自的判定都在匯出的 aspect_targets。
    notes.push(
      "「入／出」「同度」「完成時刻」三欄只描述最近的那個相位；"
      + "容許度內若不只一個相位，其他相位各自的狀態在 JSON 匯出裡逐一列出。"
    );
    notes.push(...classicalDisagreementNotes(response, "derived_methods.aspects"));
    // 相位名稱的唯一產生器是後端 degree_based.aspect_names_zh，涵蓋所選集合的每個相位。
    const zhByKey = new Map(
      Object.entries(isRecord(degree.aspect_names_zh) ? degree.aspect_names_zh : {})
    );
    const tables = [];
    if (pairs.length) {
      tables.push({
        title: "逐度相位",
        columns: [
          "組合", "整宮配置", "最近相位", "角距離", "距精確（度）",
          "最近相位的入／出", "最近相位的同度", "最近相位的完成時刻", "容許度內的相位",
        ],
        rows: pairs.map((pair) => {
          const ws = isRecord(pair.whole_sign) ? pair.whole_sign : {};
          const near = isRecord(pair.nearest_aspect) ? pair.nearest_aspect : null;
          const target = nearestTarget(pair);
          return [
            `${pair.body_a_name || pair.body_a || DASH} — ${pair.body_b_name || pair.body_b || DASH}`,
            wholeSignCell(ws),
            // 名稱只取後端名稱表；後端沒給就是 —，前端不代為命名。
            near && zhByKey.has(near.key) ? zhByKey.get(near.key) : DASH,
            num(pair.separation_degrees, 4),
            near ? signedNum(near.signed_offset_from_exact_degrees, 4) : DASH,
            applyingCell(pair, target),
            partileCell(target),
            perfectionCell(target),
            inOrbCell(pair, target, orbUnavailable, zhByKey),
          ];
        }),
      });
    }
    const aversions = wholeSignAversions(aspects);
    const grid = aspectGridTable(aspects, zhByKey);
    if (grid) {
      tables.push(grid);
      notes.push(
        "「相位方格」把同一份結果排成三角形：每一格是容許度內的相位、距精確的度數與入／出相位；"
        + "容許度內沒有相位、但兩星的星座成相位時寫「整宮」加相位名；兩星的星座不成相位時寫「不合意」；"
        + "含上升點或中天、又不在容許度內的組合寫「—」。"
      );
    }
    const aversionRows = aversionTable(aversions, aspects);
    if (aversionRows) {
      tables.push(aversionRows);
      notes.push(AVERSION_NOTE);
    }
    // orb 未選定不是「相位模組被拒絕」；相位算出來了，少的是一層判定。
    const status = orbReceipt.requested === true ? receiptStatus(orbReceipt) : aspectsStatus;
    return makeSection("aspects", "相位", RING.METHOD, status, { notes, tables });
  }

  function dignitiesSection(response) {
    const dignities = response.derived_methods.essential_dignities;
    const status = moduleState(
      response, { module: "essential_dignities" }, dignities,
      isRecord(dignities) && isRecord(dignities.selected_profiles)
    );
    if (status.state !== "present") {
      return absentSectionFor(
        "dignities", "本質尊貴", RING.METHOD, "本次未請求本質尊貴。", status
      );
    }
    const notes = [];
    notes.push(
      "本模組只評估廟與旺（domicile／exaltation）。"
      + "陷、弱、外來與接納（含互容）尚未評估，那是「未評估」，不是「沒有」。"
    );
    const selected = dignities.selected_profiles || {};
    const tables = [{
      title: "本次計算的技法",
      columns: ["技法", "狀態"],
      rows: [
        ["廟旺 domicile／exaltation", selected.domicile_exaltation, null],
        ["界 bounds", selected.bounds, null],
        ["面／旬 face／decan", selected.face_decan, null],
        ["三分性 triplicity", selected.triplicity, null],
      ].map(([technique, profile]) => [technique, profile ? "已選定" : "未選定"]),
    }];
    notes.push(...classicalDisagreementNotes(response, "derived_methods.essential_dignities"));
    const comparison = dignities.research_comparison_profiles || [];
    if (comparison.length) {
      notes.push(
        `另有 ${comparison.length} 套並列比較用的 profile；並列不會改變你選定的那一套。`
      );
    }

    return makeSection("dignities", "本質尊貴與分配法", RING.METHOD, status, {
      notes,
      tables,
      blocks: ["評估基礎：回歸黃道、地心位置、當日黃道框架。"],
    });
  }

  // ── 各模組的承接區塊 ────────────────────────────────────────────

  /** 共用：把一組天體列成三套座標的表。 */
  function bodyRows(list) {
    return (list || []).map((b) => [
      b.name || b.key,
      ...positionCells(b.sign_position),
      dms(b.latitude),
      cyclicFixed(b.right_ascension, 6),
      dms(b.declination),
      cyclicFixed(b.azimuth, 3),
      num(b.altitude_true, 3),
      num(b.altitude_apparent, 3),
      // 三態，不是二態。heliocentric/barycentric 下後端對太陽與月交點回傳
      // motion_sign: null，因為那些點在該中心沒有物理意義。把 null 摺進「順行」
      // 會在同一列印出「黃經 —、行進 順行」——一句沒有依據的天文陳述，而且會經
      // canonical sections 進入四種匯出。
      // "zero" 顯示「順行」：速度為零是否構成「停滯」是方法問題，
      // 後端 core/bodies.py 明示不做該判斷，這裡也不代它做。
      b.motion_sign === "negative"
        ? "逆行"
        : b.motion_sign === "positive" || b.motion_sign === "zero"
          ? "順行"
          : DASH,
    ]);
  }
  // 角度欄印的是十進位度，表頭帶單位；方位角另標起算慣例（後端 core/bodies.py 已換成
  // 北＝0°、向東順時針，Swiss 原始的南＝0° 只留在計算軌跡）。
  const LONGITUDE_COLUMN = "黃經 λ（度）";
  const BODY_COLUMNS = [
    "天體", LONGITUDE_COLUMN, "星座度數", "黃緯 β（度）", "赤經 α（度）", "赤緯 δ（度）",
    "方位角 Az（度，北＝0°，順時針）", "真高度（度）", "視高度（度）", "行進",
  ];

  // 求根與線性外插的差別對讀者是有意義的：後者在月亮速度變化、行星站留、
  // 或同一視窗內多重根時會給錯完成時刻。哪一種在用，只有回應知道。求根是先以有限間隔
  // 掃描再二分，間距小於掃描間隔的兩個根或只碰一下的切點可能整個漏掉，所以不宣稱對多重根成立。
  function solverLimitation(module) {
    const solver = String(module.solver || "");
    if (!solver) {
      return "本次回應沒有交代用了哪一種求解器，因此無法說明它的限制。";
    }
    if (solver.includes("linear")) {
      return "本模組以線性外插求相位完成時刻，那是已知的正確性缺陷："
        + "月亮速度會變、被相位的行星可能站留、站留附近可能出現多重根。";
    }
    return "完成時刻以求根取得，逐點查詢星曆而不假設速度為定值；"
      + "以有限間隔搜尋；間距極近的根或切點可能遺漏。"
      + "括號端點與迭代次數一併輸出，可據以複算。";
  }

  /**
   * 白名單：前現代具名文本彼此給出不同規則的方法，
   * 在結果旁標「古典文獻說法不一」。標記與說明的唯一產生器是後端
   * core/contested_methods.py（calculation_dossier.methodology.classical_source_disagreements）；
   * 前端只依 response_path 取用，不自己決定哪個方法有爭議，也不另寫說明。
   * 這不是 method_status：對外不出現 provisional。
   */
  function classicalDisagreementNotes(response, responsePath) {
    const dossier = isRecord(response.calculation_dossier) ? response.calculation_dossier : {};
    const methodology = isRecord(dossier.methodology) ? dossier.methodology : {};
    const marks = isRecord(methodology.classical_source_disagreements)
      ? methodology.classical_source_disagreements : {};
    const items = Array.isArray(marks.items) ? marks.items : [];
    return items
      .filter((item) => isRecord(item) && item.response_path === responsePath
        && typeof item.note_zh === "string" && item.note_zh)
      .map((item) => `古典文獻說法不一：${item.note_zh}`);
  }

  function nodesSection(response) {
    // 月交點每張盤都算（輸出契約：不屬於任何選項的容器）；缺席不是「未請求」。
    const nodes = response.astronomical_data.nodes;
    if (!Array.isArray(nodes)) throw exportPipeline.incompleteResponse("缺少月交點");
    if (!nodes.length) {
      return absentSectionFor("nodes", "月交點", RING.ASTRONOMICAL, "",
        { state: "executed_unavailable", reason_code: "" });
    }
    return makeSection("nodes", "月交點", RING.ASTRONOMICAL, { state: "present" }, {
      notes: ["密切交點與平均交點分列，不替使用者擇一。"],
      tables: [{ title: "交點", columns: BODY_COLUMNS, rows: bodyRows(nodes) }],
    });
  }

  // 後端以閉集 magnitude_basis 標明星等是單星還是整團合計；前端不另存星團名單。
  function isClusterMagnitude(star) {
    return star.magnitude_basis === "cluster_integrated";
  }

  function fixedStarsSection(response) {
    const stars = response.astronomical_data.fixed_stars;
    const list = Array.isArray(stars) ? stars : [];
    const status = moduleState(
      response, { option: "include_fixed_stars", module: "fixed_stars" }, stars, list.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("fixed_stars", "恆星", RING.ASTRONOMICAL,
        "本次未請求恆星。目錄內的恆星全部列為研究用途，勾選才計算。", status);
    }
    const policy = response.astronomical_data.fixed_star_policy || {};
    return makeSection("fixed_stars", "恆星", RING.ASTRONOMICAL, status, {
      notes: [
        "本項只提供位置與星等，不自動判定恆星合相。",
        `目錄收錄 ${policy.catalog_size || DASH} 顆，本次輸出 ${list.length} 顆。`,
        "「星表代碼」是本站星曆程式（Swiss Ephemeris）星表裡這顆星的代碼，多半是拜耳名的縮寫，"
          + "例如 alTau 是金牛座 α 星（畢宿五）；核對或自己重算時用得到。",
        ...(list.some(isClusterMagnitude)
          ? ["星團列的是星表給整個星團的一個位置（各星團的記錄離星團中心多遠，見方法頁）；星等是整團合計的亮度，不是一顆星的亮度，所以在星等後標「整團合計」。"]
          : []),
      ],
      tables: [{
        title: "恆星位置",
        // note 與 features 頁都說有星等，表就要有星等欄。
        // 古典恆星表列黃經與黃緯，所以黃緯緊接在黃道的兩欄之後。
        columns: ["恆星", "星表代碼", LONGITUDE_COLUMN, "星座度數", "黃緯 β（度）", "赤緯 δ（度）", "星等"],
        rows: list.map((star) => [
          // 中文名只取後端 config.py 的 name，前端不另存星名表。
          star.name || star.key, star.catalog_name || DASH,
          ...positionCells(star.sign_position), dms(star.latitude), dms(star.declination),
          isClusterMagnitude(star) && star.magnitude != null
            ? `${num(star.magnitude, 2)}（整團合計）` : num(star.magnitude, 2),
        ]),
      }],
    });
  }

  function lunarApsidesSection(response) {
    const module = response.astronomical_data.lunar_apsides;
    const status = moduleState(
      response, { option: "include_lilith_priapus", module: "lunar_apsides" }, module,
      isRecord(module) && Array.isArray(module.points) && module.points.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("lunar_apsides", "Lilith 與 Priapus", RING.ASTRONOMICAL,
        "本次未請求。", status);
    }
    return makeSection("lunar_apsides", "Lilith 與 Priapus", RING.ASTRONOMICAL, status, {
      notes: ["三個點都是月球軌道的幾何點，不是物理天體；本項顯示位置，不自動加入相位判定。"],
      tables: [{ title: "月球拱點", columns: BODY_COLUMNS, rows: bodyRows(module.points) }],
    });
  }

  function parallaxMoonSection(response) {
    const module = response.astronomical_data.parallax_moon;
    const status = moduleState(
      response, { module: "parallax_moon" }, module,
      isRecord(module) && isRecord(module.topocentric_effective)
    );
    if (status.state !== "present") {
      return absentSectionFor("parallax_moon", "站心月亮", RING.ASTRONOMICAL,
        "本次未請求。月亮位置口徑維持跟隨整體計算中心。", status);
    }
    return makeSection("parallax_moon", "站心月亮", RING.ASTRONOMICAL, status, {
      notes: [
        "畫面上同時出現兩個月亮不是錯誤，是明示的座標政策："
        + "地心參考值保留，站心值另計。",
        "整張盤以地心位置為基準；月亮另列出生地觀測者所見的站心位置。月亮位置、落宮、反照點、阿拉伯點、月空亡、赤緯與黃道相位、本質尊貴與出生時刻敏感度使用站心月亮；"
        + "月相與日月食仍依地心視黃經，升降本來就以站心計算，日夜盤仍用地心太陽高度。",
      ],
      tables: [{
        title: "兩個月亮",
        columns: ["來源", LONGITUDE_COLUMN],
        rows: [
          ["地心參考 geocentric", longitudeText((module.geocentric_reference || {}).sign_position)],
          ["站心生效 topocentric", longitudeText((module.topocentric_effective || {}).sign_position)],
          ["差值（度）", num(module.longitude_delta_degrees, 6)],
        ],
      }],
    });
  }

  /**
   * 一個模組可能由不只一個選項寫入；哪些選項會寫進它，由後端收據的
   * response_paths 宣告，這裡不另抄一份。回傳真的請求了它的那個選項，
   * 沒有任何一個請求時回 fallback。
   */
  function requestingOption(response, modulePath, fallback) {
    const states = calculationPolicy(response).option_states;
    if (!isRecord(states)) return fallback;
    const carriers = Object.keys(states).filter((key) => {
      const entry = states[key];
      if (!isRecord(entry) || !("response_paths" in entry) || !Array.isArray(entry.response_paths)) {
        return false;
      }
      return entry.response_paths.some(
        (path) => path === modulePath || String(path).startsWith(`${modulePath}.`)
      );
    });
    return carriers.find((key) => "requested" in states[key] && states[key].requested === true)
      || fallback;
  }

  function extraAnglesSection(response) {
    const module = response.astronomical_data.extra_angles;
    // 額外角點模組由 include_extra_angles 與 include_anti_vertex 共用。只以前者
    // 判斷時，只勾反宿命點的請求在後端算出並回傳了它，畫面卻會寫「本次未請求」。
    const status = moduleState(
      response,
      { option: requestingOption(response, "astronomical_data.extra_angles", "include_extra_angles") },
      module,
      isRecord(module) && isRecord(module.angles) && Object.keys(module.angles).length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("extra_angles", "額外角點", RING.ASTRONOMICAL, "本次未請求。", status);
    }
    const angles = module.angles || {};
    return makeSection("extra_angles", "額外角點", RING.ASTRONOMICAL, status, {
      notes: [
        "五個角點由Swiss Ephemeris的宮位計算附帶取得；反宿命點由宿命點的精確對蹠位置導出。這些都不是古典占星的四軸。",
      ],
      tables: [{
        title: "角點",
        columns: ["角點", LONGITUDE_COLUMN, "星座度數"],
        rows: Object.entries(angles).map(([key, value]) => [
          isRecord(value) && value.zh ? value.zh : presentClosedVocabulary(key, {}, "角點"),
          ...positionCells(isRecord(value) ? value.sign_position : null),
        ]),
      }],
    });
  }

  // 後端的鍵與列舉值不是顯示字串（sun、內部狀態碼、planet_in_house.jupiter）。
  // 識別碼與顯示名稱在這裡成對宣告一次，渲染只准用顯示名稱那一欄。
  // 後端只有一套敏感度封閉詞彙（SENSITIVITY_STATES）。最後兩個只說分類
  // 在取樣點是否一致，不說結果穩定；數值在區間內本來就會移動。
  // 與取樣摘要的「這五個取樣點分類相同」同一套說法。
  const SAMPLING_STATUS_ZH = Object.freeze({
    not_requested: "未請求",
    not_applicable: "此模式下無可比較的值",
    not_evaluated: "只算了代表性時刻，未在取樣時刻重算",
    partially_evaluated: "只比較了其中一部分",
    same_at_all_samples: "各取樣點分類相同",
    differs_between_samples: "取樣點之間分類不同",
  });
  function samplingStatus(value) {
    if (!value) return DASH;
    return presentClosedVocabulary(value, SAMPLING_STATUS_ZH, "取樣狀態");
  }
  function moduleLabelBySuffix(name) {
    const key = Object.keys(MODULE_COVERAGE).find(
      (path) => path === name || path.endsWith(`.${name}`)
    );
    const declared = key ? MODULE_COVERAGE[key] : null;
    return declared && declared.zh ? declared.zh : null;
  }
  function modulePathLabel(path, names) {
    const declared = MODULE_COVERAGE[path];
    if (declared && declared.zh) return declared.zh;
    const parts = String(path).split(".");
    const own = moduleLabelBySuffix(parts.slice(0, -1).join("."));
    if (own) {
      const member = parts[parts.length - 1];
      return `${own}（${(names && names[member]) || member}）`;
    }
    return moduleLabelBySuffix(path) || path;
  }

  const ECLIPSE_SLOTS = [
    ["previous_solar", "前一次日食"],
    ["previous_lunar", "前一次月食"],
  ];
  // 鍵是 backend/app/core/lunar_events.py _eclipse_type 的回傳閉集（含 hybrid 與 unknown）；
  // view_model.test.cjs 直接讀該函式對照。hybrid 依臺北市立天文科學教育館通行譯名「複合日食」
  // （別名「全環食」）。
  const ECLIPSE_TYPE_ZH = {
    total: "全食", partial: "偏食", annular: "環食",
    hybrid: "複合日食", penumbral: "半影食", unknown: "類型未判定",
  };
  // 日食類型是否落在分類邊界內。鍵是
  // backend/app/core/lunar_events.py CLASSIFICATION_BORDERLINE_STATES；
  // tests/integration/test_frontend_contract.py 以後端的值逐一渲染驗證。
  // 這裡只給表格裡的短標籤；完整白話說明由後端 explanation_zh 產生（唯一產生者），原樣印出。
  const ECLIPSE_BORDERLINE_ZH = Object.freeze({
    inside_classification_margin: "近分類邊界",
    outside_classification_margin: "不在邊界附近",
    no_criterion_for_lunar_eclipses: "月食未做邊界檢查",
  });
  const LUNAR_PHASE_ZH = Object.freeze({
    new_moon: "朔",
    first_quarter: "上弦",
    full_moon: "望",
    last_quarter: "下弦",
  });
  const LUNAR_CONTRACT_ZH = Object.freeze({
    geocentric_apparent_tropical_of_date: "地心視黃經、當日回歸黃道",
  });
  // astronomical_data.atmosphere 的兩個閉集。鍵是後端
  // backend/app/main.py 組 atmosphere 時實際發出的值，不得自創。
  const PRESSURE_MODE_ZH = Object.freeze({
    swiss_estimate_from_altitude: "依海拔估算（Swiss Ephemeris 以觀測地海拔推算標準氣壓）",
    user_supplied: "使用者指定",
  });
  const REFRACTION_MODEL_ZH = Object.freeze({
    swiss_ephemeris_standard_model: "Swiss Ephemeris 標準大氣折射模型",
  });

  // 以下每一張表的鍵都是後端閉集的原值（檔名在各行註明），值是畫面用字。
  // 後端新增一個值而這裡沒跟上，畫面印「未識別的…（原值）」，缺對應是看得見的缺陷。

  // core/dossier.py calculation_policy.moon_position。profile 標籤與
  // options-catalogue.js 的 moon_position_profile 同字（view_model.test.cjs 對照兩處）。
  const MOON_PROFILE_ZH = Object.freeze({
    global_computation_mode: "跟隨整體計算中心",
    moon_only_topocentric_v1: "僅月亮採站心",
  });
  // effective_moon_source：topocentric_observer 或 computation_mode.center（schemas.py 的四個中心）。
  const MOON_SOURCE_ZH = Object.freeze({
    topocentric_observer: "出生地站心觀測者",
    geocentric: "地心",
    topocentric: "站心",
    heliocentric: "日心",
    barycentric: "太陽系質心",
  });
  function moonPositionReceipt(value) {
    if (!isRecord(value)) return DASH;
    const parts = [
      presentClosedVocabulary(value.requested_profile, MOON_PROFILE_ZH, "月亮位置口徑"),
      `實際來源：${presentClosedVocabulary(value.effective_moon_source, MOON_SOURCE_ZH, "月亮來源")}`,
    ];
    if (value.geocentric_reference_retained === true) parts.push("另保留地心參考值");
    return parts.join("；");
  }

  // 不對外標 provisional。契約、Dossier 與隱私聲明的 status
  // 原值都含這個字；畫面說它的意思，原值留在 canonical 原始回應與 JSON 匯出。
  const CONTRACT_STATUS_ZH = Object.freeze({
    provisional: "欄位仍可能變動，尚非已凍結的公開 API",
  });
  const CONTRACT_COMPATIBILITY_ZH = Object.freeze({
    "additive_during_0.x_unless_a_documented_correctness_fix_requires_change":
      "0.x 期間只新增欄位；除非有記錄在案的正確性修正，既有欄位不改",
  });
  const BUILD_IDENTITY_STATUS_ZH = Object.freeze({
    unavailable: "未提供（此建置沒有注入原始碼修訂）",
  });
  const DOSSIER_STATUS_ZH = Object.freeze({
    provisional: "格式尚未凍結，仍可能變動",
  });
  const ATTESTATION_STATUS_ZH = Object.freeze({
    provisional_pending_external_review: "自我聲明，尚待外部審查",
  });

  // house_division.availability（core/houses.py HOUSE_AVAILABILITY_STATES）。
  const HOUSE_AVAILABILITY_ZH = Object.freeze({
    available: "可用",
    available_polar_geometry: "可用，但位於極區：部分黃道度數不升起或不落下，宮位幾何與中低緯度不同",
    unstable: "可用，但高緯度下象限宮位對出生時刻與緯度極為敏感",
    unavailable: "不可用",
  });

  // core/lots.py SECT_STATUSES 與 LOT_FORMULA_BASES。
  const SECT_STATUS_ZH = Object.freeze({
    day: "日盤",
    night: "夜盤",
    boundary_both_shown: "近地平邊界：判定仍依 > 0° 規則，阿拉伯點兩套並列",
  });
  const LOT_FORMULA_BASIS_ZH = Object.freeze({
    day_formula: "日盤公式",
    night_formula: "夜盤公式",
    both_formulas_boundary: "日盤公式與夜盤公式兩套並列",
  });
  const SECT_APPLIED_ZH = Object.freeze({ day: "日盤公式", night: "夜盤公式" });

  // core/aspects.py APPLYING_STATES、PERFECTION_STATUSES 與各理由碼。
  const APPLYING_ZH = Object.freeze({
    applying: "入相位",
    exact_now: "此刻精確",
    separating: "出相位",
    indeterminate_relative_station: "相對速度為零，方向未定",
  });
  const APPLYING_REASON_ZH = Object.freeze({
    angle_motion_not_modeled: "不適用（軸點運動未建模）",
    relative_speed_unavailable: "無法判定（缺少相對速度）",
  });
  const PARTILE_REASON_ZH = Object.freeze({
    no_aspect_verdict_available_for_partile: "無法判定（沒有容許度判定）",
    partile_profile_not_applicable_to_modern_minor_aspect: "不適用（現代小相位）",
  });
  // partile 為 false 時的理由（core/aspects.py PARTILE_REASON_CODES）：
  // 同度要先在整宮上構成該相位，畫面說出「否」是哪一種否。
  const PARTILE_FALSE_REASON_ZH = Object.freeze({
    same_degree_without_whole_sign_aspect: "否（度數相同，但兩星的星座不成這個相位）",
    no_whole_sign_aspect_for_partile: "否（兩星的星座不成這個相位）",
    angle_pair_not_in_orb_for_partile: "否（不在軸點容許度內）",
  });
  const IN_ORB_REASON_ZH = Object.freeze({
    orb_profile_not_selected: "未套用容許度",
    angle_orb_not_selected: "未判定（未指定軸點容許度）",
    historical_orb_profile_not_applicable_to_modern_minor_aspect: "未判定（歷史容許度表不用於小相位）",
    no_sourced_orb_for_participant: "未判定（此參與者沒有出處可據的容許度）",
  });
  // 模組收據與時區收據的 reason_code。畫面印中文，原始代碼只留在
  // status.reason_code 與匯出。鍵集合由 tests/integration/test_module_reason_labels.py 對
  // 後端實際回應（請求矩陣走訪每一份收據）與後端閉集常數比對；缺一個就紅。
  const MODULE_REASON_ZH = Object.freeze({
    // 請求本身
    option_not_requested: "本次未請求此選項",
    configuration_not_selected: "本次未選定此設定",
    parent_module_not_requested_or_not_applicable: "所屬的上層模組未請求或不適用",
    request_validation_constraint_only: "此設定只用來檢查請求，本身不產生結果",
    // 出生時刻與宮位
    date_only_no_birth_time: "只有出生日期、沒有時刻，宮位與角點無法定義",
    house_calculation_not_executed: "本次沒有計算宮位與角點，依賴它們的項目無法產生",
    // 計算中心（app.core.frame_compatibility）
    non_earth_observer_center: "日心或質心計算沒有地表觀測者，此項不適用",
    non_earth_center_dignity_basis_not_authorized: "日心或質心計算下不適用",
    earth_observer_phenomena_not_applicable_for_center: "日心或質心計算不輸出地表觀測者看到的現象",
    // 參考框架（app.core.frame_compatibility）
    planet_house_frame_mismatch: "天體黃經是 J2000 框架、宮頭是當日框架，不判定落宮",
    planet_house_nutation_mismatch: "天體黃經關閉章動、宮頭含章動，不判定落宮",
    sidereal_dignity_basis_not_authorized: "尊貴表依回歸黃道定義，恆星黃道下不適用",
    j2000_antiscia_basis_not_authorized: "此參考框架下不適用（J2000）",
    j2000_aspects_basis_not_authorized: "此參考框架下不適用（J2000）",
    j2000_declination_aspects_basis_not_authorized: "此參考框架下不適用（J2000）",
    j2000_dignity_basis_not_authorized: "此參考框架下不適用（J2000）",
    j2000_lots_basis_not_authorized: "此參考框架下不適用（J2000）",
    j2000_void_of_course_basis_not_authorized: "此參考框架下不適用（J2000）",
    nutation_off_antiscia_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    nutation_off_aspects_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    nutation_off_declination_aspects_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    nutation_off_dignity_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    nutation_off_lots_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    nutation_off_void_of_course_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    j2000_dodecatemoria_basis_not_authorized: "此參考框架下不適用（J2000）",
    nutation_off_dodecatemoria_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    // 行星日與行星時（app.core.planetary_hours）
    no_sunrise_sunset_cycle_around_instant: "出生地這段時間沒有一天一次的日出日落（極晝、極夜或前後幾天），無法定出行星日",
    // 月宿（app.core.lunar_mansions）
    sidereal_lunar_mansion_basis_not_authorized: "月宿從回歸黃道的牡羊 0°（春分點）起算，恆星黃道下不適用",
    j2000_lunar_mansion_basis_not_authorized: "此參考框架下不適用（J2000）",
    nutation_off_lunar_mansion_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    // 焦傷與光束下（app.core.solar_phase）
    j2000_solar_phase_basis_not_authorized: "此參考框架下不適用（J2000）",
    nutation_off_solar_phase_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    profile_has_no_cazimi_band: "所選的分法沒有日輪內這一帶（希臘化只有一條 15° 的線）",
    disc_cazimi_not_requested: "沒有選「行星中心落在太陽圓面內」的日輪內",
    sun_apparent_diameter_unavailable: "這一刻算不出太陽的視直徑（天文計算程式沒有回傳），所以「行星中心落在太陽圓面內」的日輪內這次沒有判定；所選分法本身的界線照常使用",
    // 行星與宮的古典分類（app.core.classical_classifications）
    j2000_classical_classification_basis_not_authorized: "此參考框架下不適用（J2000）",
    nutation_off_classical_classification_basis_not_authorized: "此參考框架下不適用（章動關閉）",
    // 星曆涵蓋與搜尋
    ephemeris_segment_out_of_coverage: "這個天體所用的星曆資料（記錄天體位置的天文資料）不涵蓋這個日期，所以這一項沒有結果；只有出生日期接近本站可計算年代的盡頭時才會發生，你輸入的日期本身沒有問題，其他天體照常計算",
    ephemeris_segment_file_missing: "伺服器上少了計算這一項所需的星曆資料檔（記錄天體位置的天文資料），所以這一項沒有結果；這是本站的問題，不是你的輸入有誤",
    full_ephemeris_unavailable_for_search_window: "這一項要在出生時刻前後的一段日子裡找事件，但那段日子超出本站星曆資料（記錄天體位置的天文資料）涵蓋的年代，所以這一項沒有結果；只有出生日期接近本站可計算年代的盡頭時才會發生，你輸入的日期本身沒有問題，星盤其他部分照常計算",
    swiss_ephemeris_error_in_search: "天文計算程式在找這些事件時出錯，所以這一項沒有結果；這是本站的問題，不是你的輸入有誤",
    sign_exit_not_found_in_search_window: "搜尋時段內找不到月亮離開星座的時刻",
    node_coordinates_unavailable: "交點座標不可用",
    fixed_star_query_failed: "恆星查詢全部失敗",
    fixed_star_query_partially_failed: "部分恆星查詢失敗",
    // 時區資料庫（app.core.tz_database.REASON_CODES）
    tz_database_version_not_identifiable: "無法辨識時區資料庫的版本",
    tz_database_version_unrecognized_format: "時區資料庫的版本字串格式無法辨識",
  });
  /** 空值是「未提供」，不是「未識別」：兩者是不同的事實。 */
  function moduleReason(code) {
    return code ? presentClosedVocabulary(code, MODULE_REASON_ZH, "原因") : "未提供";
  }
  // perfection_status=not_applying 時，依同一格的 applying（core/aspects.py APPLYING_STATES）分開說。
  const NOT_APPLYING_PHASE_ZH = Object.freeze({
    exact_now: "此刻已精確，不另搜尋",
    separating: "出相位中，不搜尋（只搜尋入相位）",
    indeterminate_relative_station: "相對速度為零，未搜尋",
  });
  const PERFECTION_STATUS_ZH = Object.freeze({
    not_requested: "未請求推算",
    not_applying: "非入相位，未搜尋",
    no_motion_model: "無運動模型，未搜尋",
    no_orb_verdict_nearest_only: "無容許度判定，未搜尋",
    outside_effective_orb: "不在容許度內，未搜尋",
    source_unavailable: "星曆範圍不足，無法搜尋",
    searched_no_root: "搜尋過但區間內沒有找到交會",
    found: "已找到",
  });

  const DECLINATION_ASPECT_ZH = Object.freeze({
    parallel: "平行 parallel",
    contra_parallel: "反平行 contra-parallel",
  });
  const ELEMENT_ZH = Object.freeze({ fire: "火象", earth: "土象", air: "風象", water: "水象" });
  // essential_dignities.py _decan_reading 的閉集。
  const DECAN_READING_ZH = Object.freeze({
    transmitted_text: "傳本",
    editorial_correction: "編者校正",
  });
  // 封閉詞彙一律走這裡。有對應印中文；沒有對應印「未識別的<角色>（原值）」——
  // 缺對應是看得見的缺陷，不是資料。只認自身屬性，原型鏈上的名字不是閉集成員。
  const presentClosedVocabulary = Labels.closedLabel;

  // 出生時間不精確時，事件模組在
  // 區間兩端與代表性時刻各算一次，三個結果並列、不合併。上方各表是代表性時刻的結果；
  // 這裡把三個取樣並列。後端在兩端只寫出與代表性時刻不同的子結果，省略的鍵列在
  // same_as_anchor／events_same_as_anchor（缺鍵＝與代表性時刻相同，不是缺資料）；
  // 代表性時刻的取樣指向模組頂層（result_location=module_top_level）。
  const SAMPLE_ROLES = Object.freeze([
    ["interval_start", "區間起點"],
    ["representative_anchor", "代表性時刻"],
    ["interval_end", "區間終點"],
  ]);
  const SAMPLING_INTERVAL_ZH = Object.freeze({
    civil_day: "當地民用日（出生地日曆上的那一天，從午夜到午夜）",
    stated_civil_hour: "所填的那一小時",
  });

  function representativeSamples(module) {
    if (!isRecord(module) || !isRecord(module.representative_sampling)
      || module.representative_sampling.status !== "sampled_interval_ends_and_anchor"
      || !Array.isArray(module.representative_samples)) return null;
    const byRole = Object.fromEntries(module.representative_samples
      .filter(isRecord).map((sample) => [sample.sample_role, sample]));
    if (!SAMPLE_ROLES.every(([role]) => isRecord(byRole[role]))) return null;
    const localTimes = SAMPLE_ROLES.map(([role]) => String(byRole[role].reference_local_time || ""));
    const sameDate = localTimes.every((value) => value.slice(0, 10) === localTimes[0].slice(0, 10));
    return SAMPLE_ROLES.map(([role, label], index) => {
      const sample = byRole[role];
      const local = localTimes[index]
        ? (sameDate ? localTimes[index].slice(11) : localTimes[index].replace("T", " "))
        : DASH;
      return {
        role,
        heading: `${label}（當地 ${local}）`,
        sample,
        top: sample.result_location === "module_top_level",
        refusals: isRecord(sample.module_refusals) ? sample.module_refusals : {},
      };
    });
  }

  /** 這個取樣的某個模組被拒絕時的儲存格文字；沒被拒絕回 null。 */
  function sampleRefusal(entry, moduleKey) {
    const refusal = entry.top ? null : entry.refusals[moduleKey];
    return isRecord(refusal) ? `未計算：${moduleReason(refusal.reason_code)}` : null;
  }

  function samplingNote(module, samples, tableName) {
    const interval = presentClosedVocabulary(
      module.representative_sampling.interval, SAMPLING_INTERVAL_ZH, "取樣區間"
    );
    return `出生時間不精確：上方各表是「${samples[1].heading}」的結果，不是出生時刻的事件。`
      + `依本站方法，另在${interval}的兩端各算一次；三個取樣並列於「${tableName}」表，不合併成一個答案。`
      + "同一次事件從不同的取樣時刻起算，數值求解停下的位置可能相差幾毫秒；這種差距是計算容差，不代表事件不同。";
  }

  /** 一個取樣看到的月相／日月食結果：省略的鍵取代表性時刻（模組頂層）的值。 */
  function lunarSampleView(entry, module) {
    if (entry.top) return module;
    const omitted = Array.isArray(entry.sample.same_as_anchor) ? entry.sample.same_as_anchor : [];
    const view = {};
    ["primary_phases", "prenatal_syzygy", "eclipses"].forEach((key) => {
      if (key in entry.sample) view[key] = entry.sample[key];
      else if (omitted.includes(key)) view[key] = module[key];
    });
    return view;
  }

  function lunarSamplesTable(module, samples) {
    const views = samples.map((entry) => lunarSampleView(entry, module));
    const rows = [];
    const eras = [];
    const instantCell = (instant) => {
      if (!isRecord(instant) || !instant.utc_time) return null;
      eras.push(instant.time_scale);
      return [instant.utc_time, instant.time_scale];
    };
    Object.entries(isRecord(module.primary_phases) ? module.primary_phases : {}).forEach(([key]) => {
      [["previous", "前一次"], ["next", "下一次"]].forEach(([side, sideLabel]) => {
        rows.push([
          `${presentClosedVocabulary(key, LUNAR_PHASE_ZH, "事件")}（${sideLabel}）`,
          "lunar_phases",
          views.map((view) => instantCell(((view.primary_phases || {})[key] || {})[side])),
        ]);
      });
    });
    if (isRecord(module.prenatal_syzygy)) {
      rows.push(["產前朔望", "prenatal_syzygy", views.map((view) => instantCell(view.prenatal_syzygy))]);
    }
    ECLIPSE_SLOTS.forEach(([slot, label]) => {
      if (!isRecord((module.eclipses || {})[slot])) return;
      rows.push([label, "eclipses", views.map((view) => {
        const eclipse = isRecord(view.eclipses) ? view.eclipses[slot] : null;
        if (!isRecord(eclipse) || !eclipse.utc_time_maximum) return null;
        eras.push(eclipse.time_scale);
        return [eclipse.utc_time_maximum, eclipse.time_scale,
          presentClosedVocabulary(eclipse.type, ECLIPSE_TYPE_ZH, "日月食類型")];
      })]);
    });
    const timed = timedTable("三個代表性取樣", eras);
    return {
      title: timed.title,
      columns: ["事件"].concat(samples.map((entry) => entry.heading)),
      rows: rows.map(([label, moduleKey, cells]) => [label].concat(cells.map((cell, index) => {
        const refusal = sampleRefusal(samples[index], moduleKey);
        if (refusal) return refusal;
        if (!cell) return DASH;
        const time = timed.cell(cell[0], cell[1]);
        return cell[2] ? `${cell[2]}，食甚 ${time}` : time;
      }))),
    };
  }

  /** 一個取樣看到的各天體地平事件：省略的事件取代表性時刻（模組頂層）的值。 */
  function horizonSampleBodies(entry, module) {
    const anchorBodies = Array.isArray(module.bodies) ? module.bodies : [];
    if (entry.top) return anchorBodies;
    const anchorByKey = Object.fromEntries(anchorBodies.map((body) => [body.key, body]));
    return (Array.isArray(entry.sample.bodies) ? entry.sample.bodies : []).map((body) => {
      const anchorEvents = (anchorByKey[body.key] || {}).events || {};
      const omitted = Array.isArray(body.events_same_as_anchor) ? body.events_same_as_anchor : [];
      const events = {};
      omitted.forEach((name) => { events[name] = anchorEvents[name]; });
      Object.assign(events, isRecord(body.events) ? body.events : {});
      return { ...body, events };
    });
  }

  function horizonSamplesTable(module, samples) {
    const perSample = samples.map((entry) => Object.fromEntries(
      horizonSampleBodies(entry, module).map((body) => [body.key, body])
    ));
    const eras = [];
    const anchorBodies = Array.isArray(module.bodies) ? module.bodies : [];
    anchorBodies.forEach((body) => HORIZON_EVENTS.forEach(([key]) => ["previous", "next"].forEach((side) => {
      perSample.forEach((bodies) => {
        const instant = ((((bodies[body.key] || {}).events || {})[key]) || {})[side];
        if (isRecord(instant) && instant.utc_time) eras.push(instant.time_scale);
      });
    })));
    const timed = timedTable("三個代表性取樣：取樣之間不同的地平事件", eras);
    const rows = [];
    anchorBodies.forEach((body) => HORIZON_EVENTS.forEach(([key, label]) => {
      [["previous", "前一次"], ["next", "下一次"]].forEach(([side, sideLabel]) => {
        const cells = samples.map((entry, index) => {
          const refusal = sampleRefusal(entry, "rise_set_transits");
          if (refusal) return refusal;
          const sampleBody = perSample[index][body.key];
          return sampleBody ? horizonSideCell((sampleBody.events || {})[key], side, timed) : DASH;
        });
        if (new Set(cells).size > 1) {
          rows.push([body.name || body.key, `${label}（${sideLabel}）`].concat(cells));
        }
      });
    }));
    return {
      title: timed.title,
      columns: ["天體", "事件"].concat(samples.map((entry) => entry.heading)),
      rows,
    };
  }

  function lunarEventsSection(response) {
    const module = response.astronomical_data.lunar_events;
    const phasesState = moduleState(
      response, { option: "include_lunar_phases", module: "lunar_phases" }, module,
      isRecord(module) && isRecord(module.primary_phases)
        && Object.keys(module.primary_phases).length > 0
    );
    const eclipsesState = moduleState(
      response, { option: "include_eclipses", module: "eclipses" }, module,
      isRecord(module) && isRecord(module.eclipses) && Object.keys(module.eclipses).length > 0
    );
    if (phasesState.state !== "present" && eclipsesState.state !== "present") {
      return absentSectionFor("lunar_events", "朔望與日月食", RING.ASTRONOMICAL,
        "本次未請求朔望或日月食。",
        phasesState.state !== "not_requested" ? phasesState : eclipsesState);
    }
    const phases = isRecord(module.primary_phases) ? module.primary_phases : {};
    const stamped = Object.entries(phases).flatMap(([key, entry]) => [
      [`${presentClosedVocabulary(key, LUNAR_PHASE_ZH, "事件")}（前一次）`, (entry || {}).previous || {}],
      [`${presentClosedVocabulary(key, LUNAR_PHASE_ZH, "事件")}（下一次）`, (entry || {}).next || {}],
    ]);
    const syzygy = module.prenatal_syzygy || {};
    if (syzygy.utc_time || syzygy.phase) {
      stamped.push([
        `產前朔望：出生前最近一次地心朔或望（本次為${presentClosedVocabulary(syzygy.phase, LUNAR_PHASE_ZH, "事件")}）`,
        syzygy,
      ]);
    }
    const phaseTable = timedTable(
      "朔望時刻", stamped.filter(([, instant]) => instant.utc_time).map(([, instant]) => instant.time_scale)
    );
    const rows = stamped.map(([label, instant]) => [
      label, phaseTable.cell(instant.utc_time || DASH, instant.time_scale),
    ]);
    // 勾了「日月食」就要畫出後端算出的日月食：標題含日月食、表格零列的區段
    // 讀起來是「沒有東西發生」，正好把後端說的話反過來說。
    const eclipses = module.eclipses || {};
    const eclipseEntries = ECLIPSE_SLOTS.filter(([key]) => isRecord(eclipses[key]));
    const eclipseTable = timedTable(
      "出生前最近一次日食與月食",
      eclipseEntries.filter(([key]) => eclipses[key].utc_time_maximum)
        .map(([key]) => eclipses[key].time_scale),
      "全球搜尋"
    );
    const eclipseRows = eclipseEntries.map(([key, label]) => {
      const entry = eclipses[key];
      const borderline = isRecord(entry.classification_borderline)
        ? entry.classification_borderline : null;
      return [
        label,
        presentClosedVocabulary(entry.type, ECLIPSE_TYPE_ZH, "日月食類型"),
        borderline
          ? presentClosedVocabulary(borderline.state, ECLIPSE_BORDERLINE_ZH, "類型判定")
          : DASH,
        eclipseTable.cell(entry.utc_time_maximum || DASH, entry.time_scale),
      ];
    });
    // 每一列的類型判定都附上後端的白話說明：近邊界是什麼、為什麼、讀者該怎麼用。
    const borderlineNotes = eclipseEntries.flatMap(([key, label]) => {
      const borderline = eclipses[key].classification_borderline;
      return isRecord(borderline) && typeof borderline.explanation_zh === "string"
        && borderline.explanation_zh
        ? [`${label}的類型判定：${borderline.explanation_zh}`]
        : [];
    });
    const tables = [];
    if (rows.length) {
      tables.push({ title: phaseTable.title, columns: ["事件", "時刻"], rows });
    }
    if (eclipseRows.length) {
      tables.push({
        title: eclipseTable.title,
        columns: ["事件", "類型", "類型判定", "食甚時刻"],
        rows: eclipseRows,
      });
    }
    const samples = representativeSamples(module);
    const samplesTable = samples ? lunarSamplesTable(module, samples) : null;
    // 與地平事件同一個規則：三個取樣的結果全部相同時不另列表，只說明。
    const samplesDiffer = Boolean(samplesTable)
      && samplesTable.rows.some((row) => new Set(row.slice(1)).size > 1);
    if (samplesDiffer) tables.push(samplesTable);
    return makeSection("lunar_events", "朔望與日月食", RING.ASTRONOMICAL, { state: "present" }, {
      notes: (module.contract
        ? [presentClosedVocabulary(module.contract, LUNAR_CONTRACT_ZH, "契約")]
        : []).concat(
        rows.length
          ? [PRENATAL_SYZYGY_NOTE]
          : [],
        eclipseRows.length
          ? ["日月食是全球搜尋的結果，沒有看出生地是否看得見。古典占星用日月食，主要是看它對地區與時局的作用"
            + "（《占星四書》II.4 說這是「第一個、也最有力的原因」）；把出生前最近一次日月食當作本命盤的要點，"
            + "是二十世紀才有的做法，我們讀過的古書裡沒有。"]
          : [],
        borderlineNotes,
        samplesTable && samplesTable.rows.length
          ? [samplingNote(module, samples, "三個代表性取樣")].concat(samplesDiffer
            ? []
            : ["三個代表性取樣的朔望與日月食結果全部相同，因此不另列表。"])
          : []
      ),
      tables,
    });
  }

  // 升降狀態的顯示名稱。鍵是後端 core/horizon_events.py 的 VISIBILITY_STATES 與
  // EVENT_STATUSES 閉集；tests/integration/test_frontend_contract.py 對照
  // 後端常數檢查兩邊恰好相同，這裡不得自創鍵。
  const HORIZON_VISIBILITY_ZH = Object.freeze({
    rises_and_sets: "有升有降",
    above_horizon_between_bracketing_events: "在地平線上，介於前後兩次穿越之間",
    below_horizon_between_bracketing_events: "在地平線下，介於前後兩次穿越之間",
    continuously_above_during_search_interval: "搜尋區間內始終在地平線上",
    continuously_below_during_search_interval: "搜尋區間內始終在地平線下",
    grazing_contact: "擦過地平線，未穿越",
    indeterminate_evidence_conflict: "證據互相矛盾，無法判定",
    numerically_unavailable: "星曆或求解失敗",
    method_not_applicable: "此天體不適用",
  });
  const HORIZON_EVENT_STATUS_ZH = Object.freeze({
    event_found: "前後皆找到",
    grazing_contact: "擦過地平線，未穿越",
    always_above_threshold: "搜尋區間內始終在地平線上，無此事件",
    always_below_threshold: "搜尋區間內始終在地平線下，無此事件",
    no_event_within_search_interval: "搜尋區間內未找到此事件",
    numerically_unavailable: "星曆或求解失敗",
    method_not_applicable: "此天體不適用",
  });


  // 後端事件鍵是 rise／set／upper_transit／lower_transit（horizon_events.py）。
  const HORIZON_EVENTS = Object.freeze([
    ["rise", "上升"], ["set", "下降"], ["upper_transit", "上中天"], ["lower_transit", "下中天"],
  ]);
  // 每一側的搜尋狀態（horizon_events.py SIDE_STATUSES）。「未搜尋」與「搜尋區間內沒有」是不同值。
  const HORIZON_SIDE_STATUS_ZH = Object.freeze({
    event_found: "已找到",
    no_event_within_search_interval: "搜尋區間內未找到",
    numerically_unavailable: "星曆或求解失敗",
    not_searched: "未搜尋",
  });

  /** 升降的一側：有時刻印時刻；沒有時刻印那一側的搜尋狀態，不折成 —。 */
  function horizonSideCell(entry, side, table) {
    if (!isRecord(entry)) return presentClosedVocabulary(undefined, HORIZON_EVENT_STATUS_ZH, "事件狀態");
    const instant = entry[side];
    if (isRecord(instant) && instant.utc_time) {
      return table ? table.cell(instant.utc_time, instant.time_scale) : instant.utc_time;
    }
    const search = isRecord(entry.search) ? entry.search[side] : null;
    return presentClosedVocabulary(
      isRecord(search) ? search.status : undefined, HORIZON_SIDE_STATUS_ZH, "搜尋狀態"
    );
  }

  function horizonEventsSection(response) {
    const module = response.astronomical_data.horizon_events;
    const bodies = isRecord(module) && Array.isArray(module.bodies) ? module.bodies : [];
    const status = moduleState(
      response, { option: "include_rise_set_transits", module: "rise_set_transits" }, module,
      bodies.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("horizon_events", "升降與中天", RING.ASTRONOMICAL,
        "本次未請求升降與中天。", status);
    }
    const eras = [];
    bodies.forEach((body) => {
      const events = isRecord(body.events) ? body.events : {};
      HORIZON_EVENTS.forEach(([key]) => {
        ["previous", "next"].forEach((side) => {
          const instant = isRecord(events[key]) ? events[key][side] : null;
          if (isRecord(instant) && instant.utc_time) eras.push(instant.time_scale);
        });
      });
    });
    const timed = timedTable("地平事件", eras);
    const samples = representativeSamples(module);
    const samplesTable = samples ? horizonSamplesTable(module, samples) : null;
    const samplingNotes = samples
      ? [samplingNote(module, samples, "三個代表性取樣"),
        samplesTable.rows.length
          ? "「三個代表性取樣」表只列三個取樣之間不同的事件；沒列出的事件，三個取樣的結果相同。"
          : "三個代表性取樣的地平事件結果全部相同，因此不另列表。"]
      : [];
    return makeSection("horizon_events", "升降與中天", RING.ASTRONOMICAL, status, {
      notes: horizonContractNotes(module.contract).concat(samplingNotes),
      tables: [{
        title: timed.title,
        columns: ["天體", "可見性", "事件", "狀態", "前一次", "下一次"],
        rows: bodies.flatMap((body) => {
          const events = isRecord(body.events) ? body.events : {};
          const visibility = presentClosedVocabulary(body.visibility, HORIZON_VISIBILITY_ZH, "可見性");
          return HORIZON_EVENTS.map(([key, label]) => {
            const entry = events[key];
            return [
              body.name || body.key,
              visibility,
              label,
              presentClosedVocabulary(
                isRecord(entry) ? entry.status : undefined, HORIZON_EVENT_STATUS_ZH, "事件狀態"
              ),
              horizonSideCell(entry, "previous", timed),
              horizonSideCell(entry, "next", timed),
            ];
          });
        }),
      }].concat(samplesTable && samplesTable.rows.length ? [samplesTable] : []),
    });
  }

  function planetInHouseSection(response) {
    const module = response.derived_methods.planet_in_house;
    const bodyByKey = new Map(
      (response.astronomical_data.bodies || [])
        .filter((body) => isRecord(body) && body.key)
        .map((body) => [body.key, body])
    );
    const placements = isRecord(module) && Array.isArray(module.placements) ? module.placements : [];
    const status = moduleState(
      response, { option: "include_houses", module: "planet_in_house" }, module,
      placements.length > 0 && module.execution_status === "computed"
    );
    if (status.state !== "present") {
      return absentSectionFor("planet_in_house", "行星落宮", RING.METHOD,
        "本次未請求宮位，因此沒有落宮。", status);
    }
    const points = pointPlacementTable(response, module);
    return makeSection("planet_in_house", "行星落宮", RING.METHOD, status, {
      notes: [
        `宮位制：${houseSystemText(module.house_system_code, module.house_system_name)}。`,
        "距最近宮頭的黃經差一律列出（沿黃道量，不計黃緯），讓你自己判斷這個落宮對出生時刻有多敏感。",
        ...points.notes,
      ],
      tables: [{
        title: "落宮",
        columns: ["天體", LONGITUDE_COLUMN, "宮", "距最近宮頭（黃經差，度）", "在宮頭上"],
        rows: placements.map((place) => [
          place.name || place.key,
          // 落宮的每一列都是 astronomical_data.bodies 的同一個天體（後端以同一份清單計算），
          // 黃經文字依鍵讀那一列的 sign_position，不在這裡另寫一份。
          longitudeText((bodyByKey.get(place.key) || {}).sign_position),
          place.house === null || place.house === undefined ? DASH : String(place.house),
          num(place.distance_to_nearest_cusp_degrees, 4),
          place.on_cusp === true ? "是" : "否",
        ]),
      }, ...points.tables],
    });
  }

  /**
   * 月交點與月球拱點（Lilith 等）的落宮：後端只在整宮制給（planet_in_house.point_placements），
   * 整宮制的宮就是星座。其他宮位制後端回具名原因，這裡說一句，不自己用星座補。
   */
  const POINT_PLACEMENT_TITLE = "月交點、Lilith 與 Priapus 的落宮（整宮制）";
  function pointPlacementTable(response, module) {
    const points = isRecord(module.point_placements) ? module.point_placements : null;
    if (!points) return { notes: [], tables: [] };
    if (points.execution_status !== "computed") {
      return {
        notes: points.reason_code === "not_whole_sign_house_system"
          ? ["月交點、Lilith 與 Priapus 不是行星，只在整宮制列出落宮（整宮制的宮就是星座）；本次的宮位制不列。"]
          : [],
        tables: [],
      };
    }
    const placements = Array.isArray(points.placements) ? points.placements.filter(isRecord) : [];
    if (!placements.length) return { notes: [], tables: [] };
    const astro = isRecord(response.astronomical_data) ? response.astronomical_data : {};
    const apsides = isRecord(astro.lunar_apsides) && Array.isArray(astro.lunar_apsides.points)
      ? astro.lunar_apsides.points : [];
    // 頁面投影的交點與拱點紀錄沒有鍵，以名稱對上（兩邊是後端同一個名稱）。
    const positionByName = new Map([...(astro.nodes || []), ...apsides]
      .filter((record) => isRecord(record) && record.name)
      .map((record) => [record.name, record.sign_position]));
    // 約略時辰：出生時間敏感度只逐列列出行星的落宮；各點的落宮在這一小時內換不換，
    // 讀分類覆蓋裡改變的路徑（後端以鍵命名每一點），在這張表說出來。
    const sensitivity = isRecord(response.birth_time_sensitivity) ? response.birth_time_sensitivity : {};
    const moving = new Set(differingClassificationPaths(sensitivity)
      .map((item) => /^derived_methods\.planet_in_house\.point_placements\.placements\[([^\]]+)\]\.house$/
        .exec(String(item)))
      .filter(Boolean)
      .map((match) => match[1]));
    const movingNames = placements.filter((place) => moving.has(place.key)).map((place) => place.name || place.key);
    return {
      notes: [
        "月交點、Lilith 與 Priapus 不是行星，另列一張；整宮制的宮就是星座，所以只在整宮制列出它們的落宮。",
        ...(movingNames.length
          ? [`只知道約略時辰：這一小時內${movingNames.join("、")}的落宮會變；表中的宮位依代表性時刻判定。`]
          : []),
      ],
      tables: [{
        title: POINT_PLACEMENT_TITLE,
        columns: ["點", LONGITUDE_COLUMN, "宮"],
        rows: placements.map((place) => [
          place.name || place.key,
          longitudeText(positionByName.get(place.name)),
          Number.isInteger(place.house) ? String(place.house) : DASH,
        ]),
      }],
    };
  }

  // −50′ < 太陽真高度 ≤ 0° 時，後端 named_boundary_disagreement
  // 為 true。日夜盤與阿拉伯點兩區共用這一句，不各寫一份。
  const NAMED_BOUNDARY_DISAGREEMENT_NOTE =
    "這張盤的太陽中心在地平線下 50 角分以內：本產品的規則判為夜盤，"
    + "但依天文年鑑的標準日出日落定義，這時太陽還算在地平線上，兩種定義判法不同。";

  function yesNo(value) {
    return value === true ? "是" : value === false ? "否" : DASH;
  }

  function sectSection(response) {
    const module = response.derived_methods.sect;
    const status = moduleState(
      response, { module: "sect" }, module, isRecord(module) && typeof module.is_day === "boolean"
    );
    if (status.state !== "present") {
      return absentSectionFor("sect", "日夜盤", RING.METHOD, "本次未計算日夜盤。", status);
    }
    const bandArcmin = typeof module.near_horizon_band_half_width_degrees === "number"
      ? num(module.near_horizon_band_half_width_degrees * 60, 0) : DASH;
    return makeSection("sect", "日夜盤", RING.METHOD, status, {
      notes: (
        module.in_near_horizon_band === true
          ? [`此盤太陽真高度在近地平敏感帶（±${bandArcmin}′）內。`
             + "判定本身仍依太陽真高度 > 0° 的規則確定；若改用標準視日出（太陽上緣初現）等其他具名邊界，"
             + `太陽高度在 −${bandArcmin}′ 到 0° 之間時日夜盤會相反，因此阿拉伯點兩套公式並列。`]
          : []
      ).concat(
        module.named_boundary_disagreement === true ? [NAMED_BOUNDARY_DISAGREEMENT_NOTE] : []
      ),
      tables: [{
        title: "判定",
        columns: ["項目", "數值"],
        rows: [
          ["判定", module.is_day === true ? "日生盤" : "夜生盤"],
          ["狀態", presentClosedVocabulary(module.sect_status, SECT_STATUS_ZH, "日夜盤狀態")],
          ["判定規則", "太陽中心在真地平線上方時為日盤；恰好 0° 或在下方時為夜盤"],
          ["所用太陽高度", num(module.sun_altitude_used, 6)],
          ["近地平敏感帶內", module.in_near_horizon_band === true ? "是" : "否"],
          ["兩種日出日落定義判法不同", yesNo(module.named_boundary_disagreement)],
        ],
      }],
    });
  }

  // core/planetary_hours.py WEEKDAYS 與 PERIODS 的閉集。
  const WEEKDAY_ZH = Object.freeze({
    monday: "星期一", tuesday: "星期二", wednesday: "星期三", thursday: "星期四",
    friday: "星期五", saturday: "星期六", sunday: "星期日",
  });
  const PLANETARY_PERIOD_ZH = Object.freeze({ day: "晝", night: "夜" });
  const PLANETARY_INTERVAL_ZH = Object.freeze({
    stated_civil_hour: "你填的那一個鐘點",
    civil_day: "出生那一天（民用日）",
  });

  /** 第 n 時（晝或夜第 k 時）。 */
  function planetaryHourText(hour) {
    if (!isRecord(hour) || typeof hour.index !== "number") return DASH;
    const period = presentClosedVocabulary(hour.period, PLANETARY_PERIOD_ZH, "晝夜");
    return `第 ${hour.index} 時（${period}第 ${hour.index_in_period} 時）`;
  }

  /** 當地時間與它的 UTC 偏移，同一格。 */
  function planetaryLocalTime(instant) {
    if (!isRecord(instant) || !instant.local_time) return DASH;
    return `${instant.local_time} ${instant.utc_offset || ""}`.trim();
  }

  function planetaryHoursSection(response) {
    const module = response.derived_methods.planetary_hours;
    const status = moduleState(
      response, { module: "planetary_hours" }, module,
      isRecord(module) && isRecord(module.chart_instant)
    );
    if (status.state !== "present") {
      return absentSectionFor("planetary_hours", "行星日與行星時", RING.METHOD,
        "本次未計算行星日與行星時。", status);
    }
    const day = isRecord(module.chart_instant.planetary_day) ? module.chart_instant.planetary_day : {};
    const hour = isRecord(module.chart_instant.planetary_hour) ? module.chart_instant.planetary_hour : {};
    const interval = isRecord(module.birth_time_interval) ? module.birth_time_interval : {};
    const candidates = Array.isArray(interval.candidates) ? interval.candidates : [];
    const anchored = module.time_basis !== "birth_instant";
    const notes = [
      "行星日從日出算起，不從午夜算起：日出到日落十二等分為晝時，日落到下一次日出十二等分為夜時，"
      + "所以晝時與夜時通常不等長。第一時之主是日出那天（民用日：出生地日曆上的那一天，從午夜到午夜）的七曜之主，"
      + "之後依迦勒底序（土星、木星、火星、太陽、金星、水星、月亮）逐時輪替。",
      "日出與日落用太陽上緣、含標準大氣折射、從地表觀測者看、不計地平俯角，與「升降與中天」同一個定義。",
    ];
    if (anchored) {
      notes.push(
        "出生時刻不精確：「代表性時刻所在的行星日與行星時」表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；"
        + `「可能的行星時」表列出${presentClosedVocabulary(interval.interval, PLANETARY_INTERVAL_ZH, "區間")}`
        + "內每一個可能的行星時。"
        + (interval.crosses_hour_boundary === true ? "這段時間跨過行星時的交界，行星時無法只定一個。" : "")
        + (interval.crosses_planetary_day_boundary === true ? "這段時間也跨過日出，行星日之主有兩個可能。" : "")
      );
    }
    const eras = [day.sunrise, day.sunset, day.next_sunrise, hour.start, hour.end]
      .filter((instant) => isRecord(instant) && instant.utc_time)
      .map((instant) => instant.time_scale);
    const timed = timedTable("時刻", eras);
    const utcCell = (instant) => (
      isRecord(instant) && instant.utc_time ? timed.cell(instant.utc_time, instant.time_scale) : DASH
    );
    const weekday = presentClosedVocabulary(day.weekday, WEEKDAY_ZH, "星期");
    const tables = [
      {
        title: anchored ? "代表性時刻所在的行星日與行星時" : "出生時刻所在的行星日與行星時",
        columns: ["項目", "數值"],
        rows: [
          ["行星日之主", `${day.ruler_name || DASH}（日出在 ${day.sunrise_local_date || DASH}，${weekday}）`],
          ["行星時", planetaryHourText(hour)],
          ["行星時之主", hour.ruler_name || DASH],
          ["一個晝時的長度（分鐘）", num(day.day_hour_minutes, 1)],
          ["一個夜時的長度（分鐘）", num(day.night_hour_minutes, 1)],
        ],
      },
      {
        // 時間尺度標在世界時欄（timed.heading），不標在表題：當地時間欄不是 UTC。
        title: "行星日與行星時的起訖時刻",
        columns: ["事件", "當地時間", timed.heading("世界時")],
        rows: [
          ["日出（行星日開始）", day.sunrise],
          ["日落（晝時結束、夜時開始）", day.sunset],
          ["下一次日出（行星日結束）", day.next_sunrise],
          ["本行星時開始", hour.start],
          ["本行星時結束", hour.end],
        ].map(([label, instant]) => [label, planetaryLocalTime(instant), utcCell(instant)]),
      },
    ];
    if (anchored) {
      tables.push({
        title: "可能的行星時",
        columns: ["行星日之主", "行星時", "行星時之主", "開始（當地時間）", "結束（當地時間）"],
        rows: candidates.map((item) => [
          item.planetary_day_ruler_name || DASH,
          planetaryHourText(item),
          item.ruler_name || DASH,
          planetaryLocalTime(item.start),
          planetaryLocalTime(item.end),
        ]),
      });
    }
    return makeSection("planetary_hours", "行星日與行星時", RING.METHOD, status, {
      notes,
      tables,
    });
  }

  // core/lunar_mansions.py INTERVALS 的閉集。
  const MANSION_INTERVAL_ZH = Object.freeze({
    stated_civil_hour: "你填的那一個鐘點",
    civil_day: "出生那一天（民用日：出生地日曆上的那一天，從午夜到午夜）",
  });

  /** 「第 23 宿 Saʿd Bulaʿ」：宿名只寫原名的轉寫，不譯成中文。 */
  function mansionText(mansion) {
    if (!isRecord(mansion) || typeof mansion.number !== "number") return DASH;
    return `第 ${mansion.number} 宿 ${mansion.transliteration || DASH}`;
  }

  // 區塊標題附英文，與「十二分部 Dodecatemoria」同一寫法。
  const LUNAR_MANSIONS_TITLE = "月宿 Lunar Mansions";

  function lunarMansionsSection(response) {
    const module = response.derived_methods.lunar_mansions;
    const placements = isRecord(module) && Array.isArray(module.placements) ? module.placements : [];
    const status = moduleState(
      response, { option: "include_lunar_mansions", module: "lunar_mansions" }, module,
      placements.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("lunar_mansions", LUNAR_MANSIONS_TITLE, RING.METHOD, "本次未請求月宿。", status);
    }
    const width = isRecord(module.division) ? module.division.width_text : DASH;
    const interval = isRecord(module.birth_time_interval) ? module.birth_time_interval : null;
    const bodies = (response.astronomical_data.bodies || []).filter(isRecord);
    const notes = [
      `月宿是把黃道從牡羊 0°（春分點）起分成 28 等分，每宿 ${width}，看月亮落在哪一宿。`
      + "這是中世紀阿拉伯與歐洲占星書的分法；宿名是阿拉伯星名，照原名的拉丁字母轉寫，不譯成中文。",
      "這不是古中國的二十八宿：二十八宿沿天球赤道、以各宿的距星（每宿起點的那顆星）劃分，寬窄不一，"
      + "名稱與範圍都不同，這裡不換算成二十八宿。",
      "只列月亮落在哪一宿。不替你解盤，也不預測。",
    ];
    const near = placements.filter((item) => item.near_boundary === true);
    if (!interval && near.length) {
      notes.push("月亮離月宿的交界不到 1′：出生時刻差幾分鐘就可能落在相鄰的另一宿。");
    }
    if (interval) {
      notes.push(
        "出生時刻不精確：上面那張表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；"
        + `下面那張表列出${presentClosedVocabulary(interval.interval, MANSION_INTERVAL_ZH, "區間")}`
        + "裡月亮待過的每一宿。"
        + (interval.crosses_mansion_boundary === true ? "這段時間跨過月宿交界，月宿無法只定一個。" : "")
      );
    }
    const tables = placements.map((item) => {
      const mansion = isRecord(item.mansion) ? item.mansion : {};
      const bounds = isRecord(mansion.boundary_sign_positions) ? mansion.boundary_sign_positions : {};
      const body = bodies.find((record) => record.key === item.key) || {};
      return {
        title: interval ? `代表性時刻${item.name || DASH}所在的月宿` : `${item.name || DASH}所在的月宿`,
        columns: ["項目", "數值"],
        rows: [
          [`${item.name || DASH}的位置`, signPosition(body.sign_position)],
          ["月宿", mansionText(mansion)],
          ["本宿範圍", `${signPosition(bounds.start)} 至 ${signPosition(bounds.end)}（不含終點）`],
          ["在宿內走了多遠", item.degrees_into_mansion_text || DASH],
          // 與上一列同寫度分秒；不到 1′ 時區塊說明與注意事項各說一次，不另列是／否。
          ["離最近的交界", typeof item.distance_to_nearest_boundary_degrees === "number"
            ? dms(item.distance_to_nearest_boundary_degrees) : DASH],
        ],
      };
    });
    if (interval) {
      tables.push({
        title: "這段時間內月亮待過的月宿",
        columns: ["月宿", "阿拉伯名稱"],
        rows: (Array.isArray(interval.mansions) ? interval.mansions : []).filter(isRecord).map((item) => [
          `第 ${item.number} 宿`, item.transliteration || DASH,
        ]),
      });
    }
    return makeSection("lunar_mansions", LUNAR_MANSIONS_TITLE, RING.METHOD, status, {
      notes,
      tables,
      blocks: LUNAR_MANSION_SOURCES.slice(),
    });
  }

  // 出處的一行由 labels.js 的 sourceLine 組成（登錄以鍵列出處時第一欄用鍵）；整合測試
  // 逐行核對層級與登錄裡那條引文相同。
  function sourceBlocks(lines) {
    return Object.freeze(lines.map(Labels.sourceLine));
  }

  // 月宿的出處：章節加一句白話，與方法出處登錄 lunar_mansions 同一組來源；
  // 和十二分部一樣是區塊，畫面收進「出處」摺疊（SOURCE_FOLDED_SECTIONS），匯出逐條印出。
  const LUNAR_MANSION_SOURCE_LINES = Object.freeze([
    ["Agrippa, De occulta philosophia II.33",
      "出處：Agrippa《De occulta philosophia》卷二第 33 章（1651 年英譯本）："
      + "28 個月宿等分黃道，每宿 12°51′ 又將近 26″；第 1、8、15、22 宿從牡羊、巨蟹、天秤、摩羯的起點開始。",
      "translation_read", "（英譯，掃描本）"],
    ["al-Biruni, Chronology of Ancient Nations ch. XXI",
      "出處：al-Bīrūnī《古代民族年代學》（al-Āthār al-bāqiya）第 21 章（Sachau 1879 英譯，pp. 335–366）："
      + "阿拉伯人把天球分成 28 份、每個星座兩又三分之一份，從 al-Sharaṭān 起算，因為當時它的星在牡羊之初；"
      + "之後星已移動。宿名也依這一章。",
      "translation_read", "（英譯，掃描本）"],
    [null, "出處：本站方法頁〈月宿〉一節：從回歸黃道的春分點（當日）起算，是本站對這套等分的做法；"
      + "上面兩本書說的是當時恆星天的牡羊之初。"],
  ]);
  const LUNAR_MANSION_SOURCES = sourceBlocks(LUNAR_MANSION_SOURCE_LINES);

  // ── 焦傷與光束下（core/solar_phase.py）────────────────────
  // 自成一塊：建區段的函式、它用的閉集標籤與出處都在這裡；buildSections 只呼叫一次。
  // 距離帶的名稱只有這一張表。兩套寫法並列：traditional 用原典名稱當主標籤，distance 是
  // 以距離描述當主標籤的另一案；換用時只改 SOLAR_PHASE_BAND_ZH 那一行。
  const SOLAR_PHASE_TITLE = "焦傷與光束下（離太陽多近）";
  const SOLAR_PHASE_BAND_LABELS = Object.freeze({
    traditional: Object.freeze({
      cazimi: "日輪內（cazimi）",
      combust: "焦傷（combust）",
      under_beams: "在光束下（under the beams）",
      clear: "離開光束",
      accompanying_high_latitude: "伴隨太陽（muqārina）",
    }),
    distance: Object.freeze({
      cazimi: "日輪內（cazimi）",
      combust: "緊貼太陽（焦傷，combust）",
      under_beams: "在太陽光芒下（在光束下，under the beams）",
      clear: "離開光芒",
      accompanying_high_latitude: "伴隨太陽（muqārina）",
    }),
  });
  const SOLAR_PHASE_BAND_ZH = SOLAR_PHASE_BAND_LABELS.traditional;
  // core/solar_phase.py PROFILE_IDS，順序即對照表的欄序。
  const SOLAR_PHASE_PROFILE_ZH = Object.freeze({
    lilly_1647_p113_v1: "Lilly 1647（17′、8°30′、17°）",
    hellenistic_15_v1: "希臘化（一條 15° 的線）",
    biruni_wright_v1: "al-Bīrūnī（16′、6°、依行星 12°–18°）",
  });
  const SOLAR_PHASE_PROFILE_NOTE_ZH = Object.freeze({
    lilly_1647_p113_v1: "本次分法：Lilly《Christian Astrology》1647 年版 p.113——離太陽 17 角分以內為日輪內，"
      + "8°30′ 以內為焦傷，17° 以內為在光束下（1 角分是 1 度的 60 分之 1）。",
    hellenistic_15_v1: "本次分法：希臘化時期的作者只用一條線——太陽前後 15° 以內在光束下；這套分法沒有日輪內與焦傷兩帶。",
    biruni_wright_v1: "本次分法：al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）§481–484——不到 16 角分為日輪內，"
      + "6° 以內為焦傷（水星、金星順行時到 7°；月亮不到 7°），在光束下的界線依行星與在太陽哪一側而不同，從 12° 到 18°。",
  });
  const SOLAR_PHASE_SIDE_ZH = Object.freeze({
    morning: "西側，比太陽早升起（晨星）",
    evening: "東側，比太陽晚落下（昏星）",
    on_the_sun: "與太陽同一黃經",
  });
  const SOLAR_PHASE_MOTION_ZH = Object.freeze({
    approaching_sun: "正在靠近太陽",
    separating_from_sun: "正在離開太陽",
    no_relative_motion: "與太陽沒有相對移動",
  });
  const SOLAR_PHASE_CROSSING_ZH = Object.freeze({
    emerging: "升出光束",
    sinking: "隱入光束",
  });
  const SOLAR_PHASE_LIMIT_SIDE_ZH = Object.freeze({ morning: "西側（晨星）", evening: "東側（昏星）" });
  const SOLAR_PHASE_INTERVAL_ZH = Object.freeze({
    stated_civil_hour: "你填的那一個鐘點",
    civil_day: "出生那一天（民用日：出生地日曆上的那一天，從午夜到午夜）",
  });
  const SOLAR_PHASE_FIXED_SENTENCE = "照原典列出各分法怎麼說；不替這張盤做個人解讀，也不預測。";
  // 和月宿、十二分部一樣經 sourceBlocks：有引文的一行附方法出處登錄 solar_phase 那條引文的開頭與核到層級。
  const SOLAR_PHASE_SOURCE_LINES = Object.freeze([
    ["William Lilly, Christian Astrology (London 1647)",
      "出處：Lilly《Christian Astrology》1647 年版 pp.113–114：離太陽 17 角分以內為 Cazimi，8°30′ 以內為焦傷，"
      + "到 17° 為止在光束下；太陽正在趕上行星時，行星受害比太陽離開時更重；焦傷只發生在與太陽同一星座的本體會合，"
      + "不由相位造成；「各家都認為行星在 Cazimi 因而得力」。",
      "original_language_read", "（1647 年版與 1659 年轉錄本的線上全文，頁影像未核）"],
    [null, "出處：同書 p.111：Lilly 說「任何行星的焦傷，是所能有的最大不幸」（the greatest misfortune that can be）。"],
    ["William Lilly, Christian Astrology, aphorism 26",
      "出處：同書格言第 26 條（Houlding 標為 p.300）：在太陽 12° 以內就在光束下，「不論在哪一個星座」都沒有力量；"
      + "16 角分以內為 Cazimi，「非常強」。數字與 p.113 不一致，本站預設採 p.113。",
      "original_language_read", "（1659 年轉錄本，頁碼依 Houlding）"],
    ["al-Biruni, The Book of Instruction",
      "出處：al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm，Wright 1934 英譯）§481–484：不到 16′ 稱 samīm（即 Cazimi）；"
      + "到 6° 稱 muḥtariq（焦傷，字面是「被燒」），水星、金星順行時到 7°；之後在光束下，行星「像被關住的囚犯」，"
      + "在東方升出的界線是金星、水星 12°，土星、木星 15°，火星 16°，在西方隱入的界線是土星、木星 16°，火星 18°；"
      + "月亮不到 7° 為焦傷，到 12° 為止在光束下。",
      "translation_read", "（英譯，線上打字稿，1934 年版的頁碼未核）"],
    [null, "出處：al-Bīrūnī 同書 §483：金星在會合時北黃緯超過 7°，不稱 samīm 也不稱焦傷，只稱「伴隨太陽」（muqārina）；"
      + "§486：行星的作用在焦傷時最小。"],
    ["Abu Ma'shar, Great Introduction VII.2",
      "出處：Abū Maʿshar《大導論》（Kitāb al-mudkhal al-kabīr）VII.2，Hermann of Carinthia 的拉丁譯本：除了 zamim（Cazimi），"
      + "太陽會灼燒與它會合的每一顆星，使它衰弱、敗壞；金星因為黃緯，與太陽在同一度時仍看得見，"
      + "這時不能稱為焦傷，而稱「顯現」。",
      "translation_read", "（Hermann 的拉丁文譯本，線上讀；阿拉伯原本未讀，Dykes 英譯 p.418 只見轉引）"],
    [null, "出處（本站的推論，不是原典的話）：為什麼判定用黃經差。上面兩位作者都替「北黃緯很高的金星」另立例外。"
      + "這樣的金星在天空中離太陽已有 7°–8°，若他們量的是天空中的實際距離，它本來就在 16′ 與 6° 之外，"
      + "根本不需要例外；正因為他們量的是黃道上的度數，金星與太陽「在同一度」，才需要另外說明它看得見、不算焦傷。"],
    ["Ptolemy, ",
      "出處：Ptolemy《占星四書》III.10（Robbins 1940 英譯 p.285）：在太陽光線下的行星，不採為破壞者，也不採為援助者。",
      "translation_read", "（英譯，LacusCurtius 轉錄）"],
    ["Porphyry, Introduction ch.2 and ch.30",
      "出處：希臘化時期一條 15° 的線，以及出生前後 7 天內升出或隱入光束：Porphyry 名下的《占星四書導論》（Eisagōgē）第 2、30 章、Antiochus、"
      + "Rhetorius（Brennan 2017；Holden 2009 pp.24、134 經網頁轉引），原文未核。",
      "secondary_only"],
    [null, "出處：完整書目與每一條核到哪一層，見方法頁〈焦傷與光束下〉一節。"],
  ]);
  const SOLAR_PHASE_SOURCES = sourceBlocks(SOLAR_PHASE_SOURCE_LINES);

  /** 「+16°33′58.20″」：後端給絕對值的度分秒，正負號照黃經差。 */
  function solarPhaseDifferenceText(row) {
    const value = row.longitude_difference_degrees;
    if (typeof value !== "number" || typeof row.longitude_difference_text !== "string") return DASH;
    return `${value < 0 ? "−" : "+"}${row.longitude_difference_text}`;
  }

  /** 一條界線：「≤ 17′」「< 16′」「≤ 8°30′」；依順行／逆行而不同時兩者並列。 */
  function solarPhaseLimitText(limit) {
    if (limit === null || limit === undefined) return "（這套分法沒有這一帶）";
    if (!isRecord(limit)) return DASH;
    // `in` 而不是讀鍵：一般的界線沒有 direct／retrograde，讀了就是讀不存在的欄位。
    if ("direct" in limit || "retrograde" in limit) {
      return `順行 ${solarPhaseLimitText(limit.direct)}；逆行 ${solarPhaseLimitText(limit.retrograde)}`;
    }
    if (typeof limit.degrees !== "number") return DASH;
    const minutes = Math.round(limit.degrees * 60);
    const whole = Math.floor(minutes / 60);
    const rest = minutes % 60;
    const text = whole ? `${whole}°${rest ? `${String(rest).padStart(2, "0")}′` : ""}` : `${rest}′`;
    return `${limit.inclusive === false ? "<" : "≤"} ${text}`;
  }

  /** 出生前後幾小時或幾天。 */
  function solarPhaseOffsetText(days, anchored) {
    if (typeof days !== "number") return DASH;
    const before = days < 0;
    const span = Math.abs(days) < 1 ? `${(Math.abs(days) * 24).toFixed(1)} 小時` : `${Math.abs(days).toFixed(1)} 天`;
    const base = anchored ? "代表性時刻" : "出生";
    return `${base}${before ? "前" : "後"} ${span}`;
  }

  /** 焦傷區的說明：原典怎麼說、所選分法、量法、例外與這次的時間基準。 */
  function solarPhaseNotes(response, module, { selected, sun, disc, interval }) {
    const notes = [
      "古典占星看行星離太陽多近：太近時，行星被太陽的光芒蓋住，肉眼看不到。這一區列出月亮與五顆行星在黃道上離太陽幾度，"
      + "以及照所選分法落在哪一個距離帶。（黃道：太陽一年在天上走的路線，星座度數就是沿著它量的。）",
      "原典怎麼說：Lilly 說任何行星的焦傷是「所能有的最大不幸」，太陽正在趕上行星時受害更重；"
      + "al-Bīrūnī 說行星在光束下「像被關住的囚犯」；Ptolemy 說在太陽光線下的行星，不採為破壞者也不採為援助者。"
      + "行星在日輪內（cazimi，阿拉伯文「在太陽之心」），Lilly 說各家都認為它因此得力。出處見下方摺疊。",
      presentClosedVocabulary(module.profile, SOLAR_PHASE_PROFILE_NOTE_ZH, "分法"),
    ];
    if (module.decision_basis === "ecliptic_longitude_difference") {
      notes.push(
        "判定用黃道上的經度差，不計行星在黃道上方或下方偏離多少，這是古典文獻的量法（理由見出處）。"
        + "表上另列天空中的實際夾角、黃緯，以及行星中心是否落在太陽圓面內（太陽此刻的視半徑是 "
        + `${dms(sun.semidiameter_degrees)}），只供對照，不拿來判定；黃經差與實際夾角對金星與月亮可能差到 8° 以上。`
      );
    }
    if (typeof selected.venus_latitude_exception_degrees === "number") {
      notes.push(
        `al-Bīrūnī 另有一條：金星北黃緯超過 ${selected.venus_latitude_exception_degrees}° 時，落在日輪內或焦傷的距離也不這樣稱呼，`
        + "改稱「伴隨太陽」（muqārina）。"
      );
    }
    notes.push(
      "Lilly 說焦傷只發生在與太陽同一星座時；別的作者沒有這一條，他自己的格言第 26 條也說在光束下不論哪個星座，"
      + "所以本站不套用，只在表中註明是否與太陽同星座。",
      "月亮落在日輪內，就是朔（新月）前後，朔的時刻見〈朔望與日月食〉。月亮離地球近，從出生地看（站心）與從地心看可差到約 1°；"
      + `本區用的是${module.moon_center === "topocentric" ? "站心" : "地心"}月亮，與本次其他各區相同。`,
      "水星離太陽最遠約 28°，金星約 47°，所以水星常落在光束下；這是天象，不是錯誤。",
    );
    if (disc.requested === true) {
      notes.push(disc.applicable === true
        ? "你選了「行星中心落在太陽圓面內」的日輪內：天空中的實際夾角不超過太陽此刻的視半徑"
          + `（${dms(sun.semidiameter_degrees)}）才算日輪內；其他距離帶仍看黃經差。Abū Maʿshar 說 16′ 是因為太陽的直徑約 32′–34′；`
          + "但「看實際夾角、不看黃經」不是他的規則，是本站提供的另一種讀法。"
        : `你選了「行星中心落在太陽圓面內」的日輪內，但這次沒有套用。原因：${moduleReason(disc.reason_code)}。`);
    }
    if (interval) {
      notes.push(
        "出生時刻不精確：上方各表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；"
        + "「出生時間範圍內的距離帶」列出"
        + `${presentClosedVocabulary(interval.interval, SOLAR_PHASE_INTERVAL_ZH, "區間")}內每一種分法出現過的每一個距離帶。`
        + "只知時辰時月亮約移動半度，只知日期時約 12°，距離帶可能因此改變。"
      );
    }
    notes.push(...classicalDisagreementNotes(response, "derived_methods.solar_phase"));
    notes.push(SOLAR_PHASE_FIXED_SENTENCE);
    return notes;
  }

  /** 三種分法的界線並列；一顆星兩側的界線在三種分法裡都相同時只寫一列。 */
  function solarPhaseLimitTable(rows, results, profiles) {
    const limitText = (profile, key, side) => {
      const table = isRecord(results[profile]) && isRecord(results[profile].limits) ? results[profile].limits : {};
      const perSide = isRecord(table[key]) && isRecord(table[key][side]) ? table[key][side] : {};
      return [["cazimi", "日輪內"], ["combust", "焦傷"], ["under_beams", "在光束下"]]
        .filter(([name]) => perSide[name] !== null)
        .map(([name, label]) => `${label} ${solarPhaseLimitText(perSide[name])}`)
        .join("；");
    };
    const limitRows = [];
    rows.forEach((row) => {
      const morning = profiles.map((profile) => limitText(profile, row.key, "morning"));
      const evening = profiles.map((profile) => limitText(profile, row.key, "evening"));
      if (morning.join("|") === evening.join("|")) {
        limitRows.push([row.name || DASH, "兩側相同"].concat(morning));
      } else {
        limitRows.push([row.name || DASH, SOLAR_PHASE_LIMIT_SIDE_ZH.morning].concat(morning));
        limitRows.push([row.name || DASH, SOLAR_PHASE_LIMIT_SIDE_ZH.evening].concat(evening));
      }
    });
    return {
      title: "三種分法的界線（黃經差）",
      columns: ["天體", "太陽哪一側"].concat(profiles.map((profile) => SOLAR_PHASE_PROFILE_ZH[profile])),
      rows: limitRows,
    };
  }

  /** 前後幾天內跨過光束界線的時刻（月亮不搜尋）。 */
  function solarPhaseCrossingTable(rows, module, selected, anchored) {
    const search = isRecord(module.seven_day_search) ? module.seven_day_search : {};
    const crossings = isRecord(selected.beam_crossings_within_7_days) ? selected.beam_crossings_within_7_days : {};
    const crossingRows = [];
    rows.forEach((row) => {
      const found = crossings[row.key];
      if (!Array.isArray(found)) return;  // 月亮不搜尋（null）
      if (!found.length) {
        crossingRows.push([row.name || DASH, "這段時間內沒有跨過", DASH, DASH, DASH]);
        return;
      }
      found.filter(isRecord).forEach((item) => {
        const instant = isRecord(item.instant) ? item.instant : {};
        crossingRows.push([
          row.name || DASH,
          presentClosedVocabulary(item.direction, SOLAR_PHASE_CROSSING_ZH, "方向"),
          typeof item.threshold_degrees === "number" ? `${item.threshold_degrees}°` : DASH,
          solarPhaseOffsetText(item.day_offset, anchored),
          instant.local_time ? `${instant.local_time} ${instant.utc_offset || ""}`.trim() : DASH,
        ]);
      });
    });
    return {
      title: `${anchored ? "代表性時刻" : "出生"}前後 ${num(search.window_days, 0)} 天內跨過光束界線的時刻（五顆行星）`,
      columns: ["行星", "方向", "界線", "什麼時候", "當地時間"],
      rows: crossingRows,
    };
  }

  function solarPhaseSection(response) {
    const module = response.derived_methods.solar_phase;
    const rows = isRecord(module) && Array.isArray(module.rows) ? module.rows.filter(isRecord) : [];
    const status = moduleState(
      response, { option: "include_solar_phase", module: "solar_phase" }, module, rows.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor(
        "solar_phase", SOLAR_PHASE_TITLE, RING.METHOD,
        "本次未請求。古典占星看行星離太陽多近：日輪內（cazimi）、焦傷（combust）、在光束下；勾選後列出月亮與五顆行星的距離與所屬距離帶。",
        status
      );
    }
    const results = isRecord(module.profile_results) ? module.profile_results : {};
    const selected = isRecord(results[module.profile]) ? results[module.profile] : {};
    const bandsOf = (profile) => (isRecord(results[profile]) && isRecord(results[profile].bands) ? results[profile].bands : {});
    const band = (value) => presentClosedVocabulary(value, SOLAR_PHASE_BAND_ZH, "距離帶");
    const disc = isRecord(module.disc_cazimi) ? module.disc_cazimi : {};
    const sun = isRecord(module.sun) ? module.sun : {};
    const interval = isRecord(module.birth_time_interval) ? module.birth_time_interval : null;
    const anchored = module.time_basis !== "birth_instant";
    const notes = solarPhaseNotes(response, module, { selected, sun, disc, interval });

    const tables = [{
      title: anchored ? "代表性時刻各行星離太陽多遠" : "各行星離太陽多遠",
      columns: ["天體", "距離帶", "黃經差（行星減太陽）", "在太陽哪一側", "靠近或離開", "天空中的實際夾角", "黃緯",
        "落在太陽圓面內", "與太陽同星座"],
      rows: rows.map((row) => [
        row.name || DASH,
        band(row.band),
        solarPhaseDifferenceText(row),
        presentClosedVocabulary(row.side, SOLAR_PHASE_SIDE_ZH, "側"),
        presentClosedVocabulary(row.relative_motion, SOLAR_PHASE_MOTION_ZH, "移動"),
        dms(row.angular_separation_degrees),
        dms(row.ecliptic_latitude_degrees),
        yesNo(row.within_solar_disc),
        yesNo(row.same_sign_as_sun),
      ]),
    }];
    const profiles = Object.keys(SOLAR_PHASE_PROFILE_ZH);
    tables.push({
      title: "三種分法對照",
      columns: ["天體"].concat(profiles.map((profile) => SOLAR_PHASE_PROFILE_ZH[profile]
        + (isRecord(results[profile]) && results[profile].disc_cazimi_applied === true ? "，日輪內看太陽圓面" : ""))),
      rows: rows.map((row) => [row.name || DASH].concat(profiles.map((profile) => band(bandsOf(profile)[row.key])))),
    });
    tables.push(solarPhaseLimitTable(rows, results, profiles));
    tables.push(solarPhaseCrossingTable(rows, module, selected, anchored));
    const daily = rows.map((row) => (Array.isArray(row.daily_longitude_differences)
      ? row.daily_longitude_differences.filter(isRecord) : []));
    tables.push({
      title: `${anchored ? "代表性時刻" : "出生"}前後 7 天，每天的黃經差（正：東側；負：西側）`,
      columns: ["第幾天"].concat(rows.map((row) => row.name || DASH)),
      rows: (daily[0] || []).map((item, index) => [
        item.day_offset === 0 ? "當天" : `${item.day_offset > 0 ? "後" : "前"} ${Math.abs(item.day_offset)} 天`,
      ].concat(daily.map((series) => {
        const value = series[index] ? series[index].longitude_difference_degrees : undefined;
        return typeof value === "number" ? `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(2)}°` : DASH;
      }))),
    });
    if (interval) {
      const intervalRows = Array.isArray(interval.rows) ? interval.rows.filter(isRecord) : [];
      const seenOf = (profile) => (isRecord(results[profile])
        && isRecord(results[profile].bands_seen_in_birth_time_interval)
        ? results[profile].bands_seen_in_birth_time_interval : {});
      tables.push({
        title: "出生時間範圍內的距離帶",
        columns: ["天體", "黃經差最小", "黃經差最大", "所選分法只有一種距離帶"]
          .concat(profiles.map((profile) => SOLAR_PHASE_PROFILE_ZH[profile])),
        rows: intervalRows.map((row) => [
          row.name || DASH,
          `${num(row.longitude_difference_min_degrees, 2)}°`,
          `${num(row.longitude_difference_max_degrees, 2)}°`,
          yesNo(row.stable),
        ].concat(profiles.map((profile) => {
          const seen = seenOf(profile)[row.key];
          return Array.isArray(seen) && seen.length ? seen.map(band).join("、") : DASH;
        }))),
      });
    }
    return makeSection("solar_phase", SOLAR_PHASE_TITLE, RING.METHOD, status, {
      notes,
      tables,
      blocks: SOLAR_PHASE_SOURCES.slice(),
    });
  }

  // ── 產前朔望與出生前日月食的度數 ─────────────────────────────
  // 一個自足的區段：後端 core/prenatal_points.py 寫的度數、挑法與狀態，這裡只照印。
  // 第一層白話；古書出處放在 blocks，畫面收進「出處」摺疊（SOURCE_FOLDED_SECTIONS）。
  const PRENATAL_TITLE = "產前朔望與出生前日月食的度數";
  // 鍵是 core/prenatal_points.py DEGREE_SELECTION_STATES 的閉集。
  const PRENATAL_DEGREE_STATE_ZH = Object.freeze({
    conjunction_degree: "朔：太陽和月亮同一個度數",
    selected: "取在地平線上方的",
    near_horizon_not_selected: "有一個貼近地平線，不選，兩個度數都列",
    both_above_horizon_not_selected: "兩個都在地平線上方，不選，兩個度數都列",
    both_below_horizon_not_selected: "兩個都在地平線下方，不選，兩個度數都列",
    not_applicable_no_horizon: "這個計算中心沒有地平線，不選，兩個度數都列",
  });
  // core/prenatal_points.py SECT_PROFILE_STATES。
  const PRENATAL_SECT_STATE_ZH = Object.freeze({
    selected: "selected",
    sect_near_horizon_not_selected: "出生時太陽貼近地平線，日生盤或夜生盤不定，這個挑法不選，兩次都列出。",
    sect_unavailable_not_selected: "沒有出生時刻（或這個計算中心沒有地平線），分不出日生盤或夜生盤，這個挑法不選，兩次都列出。",
  });
  const PRENATAL_LUMINARY_ZH = Object.freeze({ sun: "太陽", moon: "月亮", both: "太陽與月亮" });
  const PRENATAL_UMBRAL_ZH = Object.freeze({
    same_eclipse_as_previous_lunar: "與上一列是同一次",
    earlier_than_previous_lunar: "比上一列更早",
  });
  const PRENATAL_SOURCES = sourceBlocks([
    [null, "出處：Ptolemy《占星四書》卷三第 2 章（Robbins 英譯，Loeb 1940，頁 229–235，朔望這一句在頁 231–233；Hübner 校勘本（學者比對多份古抄本後整理出的版本）III.3）："
      + "取出生前最近一次朔望的度數；朔取兩個發光體共同的度數，望取在地平線上方的那一個；"
      + "再找在出生時主宰這個度數的行星，以它所在的度數定為上升度數。",
      "translation_read", "（Robbins 英譯）"],
    [null, "出處：Robbins 英譯本卷三第 2 章註 9：正文依兩個最重要的手抄本與佚名註釋者，看朔望那一刻誰在地平線上方；"
      + "另一個讀法看出生那一刻。本站採用前者，後者只當資訊列出。",
      "translation_read", "（Robbins 英譯與註）"],
    [null, "出處：Ptolemy《占星四書》卷三第 10 章（Robbins 英譯頁 277–279；Hübner III.11）：定壽命主宰（hyleg）時，"
      + "日生盤的候選包括前一次朔，夜生盤包括前一次望；書中沒有明說較近的另一種要不要越過。",
      "translation_read", "（Robbins 英譯）"],
    [null, "出處：Lilly《Christian Astrology》（1647）卷三第 104 章，頁 527–529：日生盤取前一次朔、夜生盤取前一次望，"
      + "較近的是另一種也要越過。",
      "original_language_read", "（為方法頁讀過，這一條沒有重讀）"],
    [null, "出處：Valens《占星選集》（Anthologiae）卷三第 10、12 章（Riley 英譯的重排本）：用前一次朔或望的度數推算壽命的起點。"
      + "書中其他幾章也用朔或望：用朔或望的主星判斷死因，用望落在陽性或陰性星座判斷父母誰先過世，"
      + "也用它定月份與關鍵年（卷二第 22、27、33、41 章，卷四第 2、28 章，卷五第 2、6 章）。"
      + "這些章號照 Kroll 校勘本與 Riley；Pingree 校勘本的卷三第 10、12 章是第 7、9 章，"
      + "卷二第 22、27、33 章是第 23、28、34 章，卷五第 6 章是第 4 章。",
      "translation_read", "（Riley 英譯）"],
    [null, "出處：Ptolemy《占星四書》卷二第 4、5、6、8 章（Robbins 英譯）：日月食主要用在世運（地區、城市與時局）；"
      + "第 4 章說，這類普遍事件「第一個、也最有力的原因」是日月在食時的會合；"
      + "第 8 章說，（出生以後發生的）日月食的度數或其對沖度數上正好有某人本命的太陽或月亮時，是「最危險、最難避開」的位置；"
      + "影響多久看遮蔽持續幾小時，日食一小時算一年，月食一小時算一個月。",
      "translation_read", "（Robbins 英譯）"],
    [null, "出處：把出生前最後一次日月食當作命盤要點的二十世紀做法：Jansky《Interpreting the Eclipses》（Para Research 1977）、"
      + "Lineman《Eclipses》（AFA 1984）與《Your Prenatal Eclipse》（AFA 1992）、Brady《The Eagle and the Lark》（Weiser 1992）、"
      + "Graves〈Introduction to Prenatal Eclipses〉（2004 年網文）。"
      + "Graves 只讀到網頁摘要，其餘只讀到書目或書商說明。",
      "secondary_only"],
    [null, "出處：半影月食看不看得出來：Espenak〈Visual Appearance of Lunar Eclipses〉（eclipsewise.com）。"
      + "日月食時刻與類型以 NASA 的日月食表驗證：Eclipse Predictions by Fred Espenak and Jean Meeus (NASA's GSFC)。",
      "original_language_read"],
  ]);

  /** 「出生前 9.4 天」「出生前 35 分鐘」：後端給的數字，只換單位。 */
  function beforeBirthText(hours) {
    if (typeof hours !== "number" || !Number.isFinite(hours)) return DASH;
    if (hours < 1) return `出生前 ${Math.round(hours * 60)} 分鐘`;
    if (hours < 48) return `出生前 ${num(hours, 1)} 小時`;
    return `出生前 ${num(hours / 24, 1)} 天`;
  }

  function altitudeText(reading) {
    if (!isRecord(reading) || typeof reading.altitude_true_degrees !== "number") return DASH;
    const altitude = reading.altitude_true_degrees;
    const sign = altitude < 0 ? "-" : "+";
    const where = reading.in_near_horizon_band ? "貼近地平線"
      : reading.above_horizon ? "在上方" : "在下方";
    return `${where}（高度 ${sign}${num(Math.abs(altitude), 1)}°）`;
  }

  /** 一次朔望取用的度數：選出的那一個，或狀態說明加兩個度數。 */
  function prenatalDegreeText(event) {
    const selection = isRecord(event.degree_selection) ? event.degree_selection : {};
    if (selection.state === "conjunction_degree" || selection.state === "selected") {
      const who = presentClosedVocabulary(selection.selected_luminary, PRENATAL_LUMINARY_ZH, "發光體");
      return `${signPosition(selection.selected_sign_position)}（${who}${selection.state === "selected" ? "，在地平線上方" : ""}）`;
    }
    return presentClosedVocabulary(selection.state, PRENATAL_DEGREE_STATE_ZH, "取度數的狀態");
  }

  function prenatalSyzygyRow(label, event, hours) {
    return [
      label,
      planetaryLocalTime(event),
      beforeBirthText(hours),
      signPosition(event.sun_sign_position),
      signPosition(event.moon_sign_position),
      prenatalDegreeText(event),
    ];
  }

  /** 恆星黃道盤：同一批點換到盤自己的黃道。 */
  function prenatalSiderealCell(event, key) {
    const zodiac = isRecord(event.chart_zodiac) ? event.chart_zodiac : null;
    return zodiac && isRecord(zodiac.sign_positions) ? signPosition(zodiac.sign_positions[key]) : null;
  }

  function prenatalSyzygyParts(module, response) {
    const syzygy = module.prenatal_syzygy;
    const atBirth = isRecord(module.prenatal_syzygy_at_birth) ? module.prenatal_syzygy_at_birth : {};
    const profile = isRecord(atBirth.sect_profile) ? atBirth.sect_profile : {};
    const other = isRecord(profile.other_previous_syzygy) ? profile.other_previous_syzygy : {};
    const phaseName = (phase) => presentClosedVocabulary(phase, LUNAR_PHASE_ZH, "事件");
    const notes = [
      "「產前朔望」是出生前最近的一次朔或望。朔是新月：太陽和月亮在黃道上同一個度數；"
        + "望是滿月：兩者在黃道上正好相對，相差 180°。這裡算的是真朔望，也就是從地心看太陽和月亮實際位置的那一刻。",
      "度數怎麼取：Ptolemy 的《占星四書》卷三第 2 章說，朔的時候取太陽和月亮共同的度數；"
        + "望的時候取「在地平線上方」那一個發光體的度數。我們看的是朔望發生的那一刻、從你的出生地看出去，"
        + "哪一個在地平線上方，判斷方法和日夜盤相同（太陽或月亮的中心在地平線上方就算）。"
        + "有一個貼近地平線（上下 50′ 以內），或兩個都在上方、都在下方時，我們不替你選，兩個度數都列出。",
      "同一章接著用這個度數推定上升點：找出在出生時刻主宰這個度數的行星，以它所在的度數為上升度數。"
        + "本站只列度數，不替你改上升點，也不把這個度數接到其他技法。",
    ];
    const rows = [prenatalSyzygyRow(`產前朔望：${phaseName(syzygy.phase)}（較近的一次）`, syzygy, atBirth.hours_before_birth)];
    if (other.state === "computed" && isRecord(other.event)) {
      rows.push(prenatalSyzygyRow(`前一次${phaseName(other.phase)}`, other.event, other.hours_before_birth));
    } else if (other.state === "outside_ephemeris_coverage") {
      rows.push([`前一次${phaseName(other.phase)}`, "超出本站星曆涵蓋的年代，沒有計算", DASH, DASH, DASH, DASH]);
    }
    const events = [syzygy].concat(other.state === "computed" && isRecord(other.event) ? [other.event] : []);
    const sidereal = events.some((event) => prenatalSiderealCell(event, "sun"));
    const columns = ["朔望", "出生地時間", "距出生", "太陽", "月亮", "取用的度數（卷三第 2 章）"];
    const tables = [{ title: "出生前的朔與望（回歸黃道）", columns, rows }];
    if (sidereal) {
      tables.push({
        title: "同一批點在這張盤的恆星黃道",
        columns: ["朔望", "太陽", "月亮"],
        rows: events.map((event, index) => [
          rows[index][0], prenatalSiderealCell(event, "sun") || DASH, prenatalSiderealCell(event, "moon") || DASH,
        ]),
      });
    }
    const fullMoons = events.map((event, index) => [event, rows[index][0]])
      .filter(([event]) => isRecord((event.degree_selection || {}).horizon_at_syzygy));
    if (fullMoons.length) {
      tables.push({
        title: "望的那一刻，從出生地看太陽和月亮的高度",
        columns: ["朔望", "太陽", "月亮", "用黃道半球交叉檢查"],
        rows: fullMoons.map(([event, label]) => {
          const selection = event.degree_selection;
          const hemisphere = selection.horizon_at_syzygy.ecliptic_hemisphere_check;
          const check = isRecord(hemisphere) ? hemisphere.agrees_with_altitude : null;
          return [
            label,
            altitudeText(selection.horizon_at_syzygy.sun),
            altitudeText(selection.horizon_at_syzygy.moon),
            check === true ? "一致" : check === false ? "不一致（以高度為準）" : DASH,
          ];
        }),
      });
      if (fullMoons.some(([event]) => (event.degree_selection.horizon_at_syzygy.ecliptic_hemisphere_check || {})
        .agrees_with_altitude === false)) {
        notes.push("交叉檢查：用黃道半球判斷（看度數落在下降點經天頂到上升點的那一半），結果和用高度判斷不同。"
          + "黃道貼近地平線、或月亮偏離黃道較多時會這樣；我們以高度判斷為準。");
      }
    }
    if (profile.state === "selected") {
      const sect = profile.selected_phase === "new_moon" ? "日生盤" : "夜生盤";
      const pickedLabel = profile.selected === "prenatal_syzygy" ? rows[0][0] : (rows[1] || [DASH])[0];
      notes.push(`另一種挑法（不是預設）：《占星四書》卷三第 10 章與 Lilly 用日生盤看前一次朔、夜生盤看前一次望。`
        + `這張盤是${sect}，這個挑法取「${pickedLabel}」。`);
    } else {
      notes.push("另一種挑法（不是預設）：《占星四書》卷三第 10 章與 Lilly 用日生盤看前一次朔、夜生盤看前一次望。"
        + presentClosedVocabulary(profile.state, PRENATAL_SECT_STATE_ZH, "挑法狀態"));
    }
    const atBirthLuminaries = isRecord(atBirth.luminaries_above_horizon_at_birth)
      ? atBirth.luminaries_above_horizon_at_birth : {};
    if (atBirthLuminaries.state === "computed") {
      const where = (reading) => (isRecord(reading) && reading.above_horizon ? "上方" : "下方");
      notes.push("手抄本的另一種讀法（Robbins 英譯本註 9）看出生那一刻誰在地平線上方，只當資訊："
        + `出生時太陽在地平線${where(atBirthLuminaries.sun)}，月亮在地平線${where(atBirthLuminaries.moon)}。`);
    }
    if (atBirth.near_birth === true) {
      notes.push(`這次朔望在出生前不到 1 小時（${beforeBirthText(atBirth.hours_before_birth).replace("出生前 ", "")}）。`
        + "出生時刻若其實早了幾分鐘，產前朔望就會是再前一次的朔望。");
    }
    if (atBirth.reference === "representative_anchor_not_birth_instant") {
      notes.push("出生時間不精確：「距出生」、日生或夜生的挑法和出生時的地平高度，用的是計算用的代表性時刻，不是出生時刻。");
    }
    const samples = representativeSamples(module);
    if (samples) {
      const seen = new Map();
      samples.forEach((entry) => {
        const view = lunarSampleView(entry, module).prenatal_syzygy;
        if (isRecord(view) && view.utc_time) seen.set(view.utc_time, view.phase);
      });
      if (seen.size > 1) {
        const later = [...seen.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).slice(1).map(([, phase]) => phaseName(phase));
        notes.push(`你填的出生時間不精確，而這段時間之內剛好有一次${later.join("、")}：出生在它之前或之後，產前朔望是不同的兩次。`
          + "「朔望與日月食」一節的「三個代表性取樣」表把它們並列，不合併；上表是代表性時刻的結果。");
      }
    }
    return { notes, tables };
  }

  function prenatalEclipseParts(module) {
    const eclipses = module.eclipses;
    const atBirth = isRecord(module.eclipses_at_birth) ? module.eclipses_at_birth : {};
    const days = isRecord(atBirth.days_before_birth) ? atBirth.days_before_birth : {};
    const notes = [
      "「出生前最近一次日食／月食」：古典占星用日月食，主要是看它對地區與時局的作用"
        + "（《占星四書》卷二第 4 章說，這類普遍的事件「第一個、也最有力的原因」是日月在食時的會合）；"
        + "卷二第 8 章說，日月食的度數或其對沖度數上正好有某人本命的太陽或月亮時，是「最危險、最難避開」的位置"
        + "（這裡說的是出生以後發生的日月食）。"
        + "把出生前最近一次日月食當作本命盤的要點，是二十世紀才有的做法，我們讀過的古書裡沒有。",
      "日食的度數是食甚（最深的那一刻）太陽的黃道度數，月亮在同一處；月食的度數是月亮的度數，太陽在正對面。",
      "月食有兩種算法，所以列兩列。月亮只經過地球影子外圍較淡的一圈（半影）、沒有進到中間最暗的本影，叫「半影月食」："
        + "月亮只是稍微變暗，常常肉眼看不出來。NASA 日月食專家 Espenak 說，月亮直徑要有大約六成以上沒入半影，"
        + "有經驗的觀測者才看得出淡淡的陰影，到快要變成偏食時才明顯。",
      "算進來的理由：天文上它是一次月食，NASA 的月食表和本站用的 Swiss Ephemeris 都把它列為月食。"
        + "不算的理由：Ptolemy 講的日月食是看得見的遮蔽，卷二第 5 章說的是「發生在地平線上方、看得見的」那些，"
        + "第 6 章用遮蔽持續幾小時來算，而半影月食通常看不見。我們讀到的占星書都沒有明說半影月食算不算，"
        + "所以「前一次月食（含半影月食）」和「前一次本影月食（偏食或全食）」兩個都列，不替你選。",
      "日月食以全球搜尋取得，沒有評估在出生地看不看得到。",
    ];
    const row = (label, entry, dayCount) => [
      label,
      presentClosedVocabulary(entry.type, ECLIPSE_TYPE_ZH, "日月食類型"),
      isRecord(entry) && entry.maximum_local_time ? `${entry.maximum_local_time} ${entry.maximum_utc_offset || ""}`.trim() : DASH,
      typeof dayCount === "number" ? beforeBirthText(dayCount * 24) : DASH,
      presentClosedVocabulary(entry.eclipsed_luminary, PRENATAL_LUMINARY_ZH, "發光體"),
      signPosition(entry.eclipse_sign_position),
    ];
    const rows = [];
    if (isRecord(eclipses.previous_solar)) rows.push(row("前一次日食", eclipses.previous_solar, days.previous_solar));
    if (isRecord(eclipses.previous_lunar)) rows.push(row("前一次月食（含半影月食）", eclipses.previous_lunar, days.previous_lunar));
    if (isRecord(eclipses.previous_umbral_lunar)) {
      const umbral = eclipses.previous_umbral_lunar;
      rows.push(row(
        `前一次本影月食（偏食或全食；${presentClosedVocabulary(umbral.relation_to_previous_lunar, PRENATAL_UMBRAL_ZH, "比較")}）`,
        umbral, days.previous_umbral_lunar
      ));
    }
    const inProgress = isRecord(atBirth.in_progress) ? atBirth.in_progress : {};
    [["solar", "日食"], ["lunar", "月食"]].forEach(([kind, word]) => {
      const entry = inProgress[kind];
      if (!isRecord(entry)) return;
      const minutes = Math.round(Math.abs(entry.maximum_minus_birth_minutes));
      if (entry.relation === "maximum_after_birth" && isRecord(entry.eclipse)) {
        notes.push(`你出生的時候，天上正在發生一次${word}；它最深的那一刻（食甚）在你出生之後 ${minutes} 分鐘，`
          + "所以沒有算成「出生前最近一次」，另列在表的最後一列。");
        const record = entry.eclipse;
        rows.push([
          `出生時正在進行的${word}`,
          presentClosedVocabulary(record.type, ECLIPSE_TYPE_ZH, "日月食類型"),
          record.maximum_local_time ? `${record.maximum_local_time} ${record.maximum_utc_offset || ""}`.trim() : DASH,
          `出生後 ${minutes} 分鐘`,
          presentClosedVocabulary(record.eclipsed_luminary, PRENATAL_LUMINARY_ZH, "發光體"),
          signPosition(record.eclipse_sign_position),
        ]);
      } else if (entry.relation === "maximum_at_or_before_birth") {
        notes.push(`你出生的時候，前一次${word}還沒結束：它的食甚在出生前 ${minutes} 分鐘。`);
      }
    });
    if (atBirth.reference === "representative_anchor_not_birth_instant") {
      notes.push("出生時間不精確：「距出生」和「出生時正在進行」用的是計算用的代表性時刻，不是出生時刻。");
    }
    return {
      notes,
      tables: rows.length ? [{
        title: "出生前最近一次日食與月食",
        columns: ["日月食", "類型", "出生地時間（食甚）", "距出生", "受食的發光體", "日月食的度數"],
        rows,
      }] : [],
    };
  }

  function prenatalPointsSection(response) {
    const module = response.astronomical_data.lunar_events;
    const syzygyState = moduleState(
      response, { module: "prenatal_syzygy" }, null,
      isRecord(module) && isRecord(module.prenatal_syzygy) && isRecord(module.prenatal_syzygy.degree_selection)
    );
    const eclipsesState = moduleState(
      response, { option: "include_eclipses", module: "eclipses" }, null,
      isRecord(module) && isRecord(module.eclipses) && isRecord(module.eclipses.previous_umbral_lunar)
    );
    if (syzygyState.state !== "present" && eclipsesState.state !== "present") {
      return absentSectionFor("prenatal_points", PRENATAL_TITLE, RING.METHOD,
        "本次未請求。勾選「朔望」會列出產前朔望（出生前最近一次朔或望）的度數，勾選「日月食」會列出出生前最近一次日食與月食的度數。",
        syzygyState.state !== "not_requested" ? syzygyState : eclipsesState);
    }
    const notes = [];
    const tables = [];
    if (syzygyState.state === "present") {
      const parts = prenatalSyzygyParts(module, response);
      notes.push(...parts.notes);
      tables.push(...parts.tables);
    } else if (syzygyState.state !== "not_requested") {
      notes.push(`產前朔望這次沒有結果。原因：${moduleReason(syzygyState.reason_code || "")}。`);
    }
    if (eclipsesState.state === "present") {
      const parts = prenatalEclipseParts(module);
      notes.push(...parts.notes);
      tables.push(...parts.tables);
    }
    notes.push("照原典列出。不替你解盤，也不預測。");
    return makeSection("prenatal_points", PRENATAL_TITLE, RING.METHOD, { state: "present" }, {
      notes,
      tables,
      blocks: PRENATAL_SOURCES.slice(),
    });
  }

  // ── 阿拉伯點、月空亡與赤緯相位 ─────────────────────────────────
  function lotsSection(response) {
    const module = response.derived_methods.lots;
    const status = moduleState(
      response, { option: "include_lots", module: "lots" }, module,
      isRecord(module) && typeof module.fortune === "number"
    );
    if (status.state !== "present") {
      return absentSectionFor("lots", "阿拉伯點", RING.METHOD, "本次未請求阿拉伯點。", status);
    }
    // 公式基礎讀後端 lots.formula_basis（lots.py LOT_FORMULA_BASES），不是 is_day：
    // is_day 說的是日夜盤，不是公式是否反轉。
    const basis = module.formula_basis;
    const boundary = basis === "both_formulas_boundary";
    const notes = [];
    notes.push(basis === null || basis === undefined
      ? "後端未標明本盤採用哪一套公式。"
      : `公式基礎：${presentClosedVocabulary(basis, LOT_FORMULA_BASIS_ZH, "公式基礎")}。`);
    if (boundary) {
      notes.push(
        "太陽在近地平敏感帶內，日盤公式與夜盤公式的結果兩套並列："
        + `主要值依${presentClosedVocabulary(module.sect_applied, SECT_APPLIED_ZH, "日夜盤公式")}`
        + "（太陽真高度 > 0° 的規則），另一套是比較值；落宮與相位只用主要值。我們核過的古典與中世紀作者沒有「日夜盤不定就並列兩套」的程序；兩套並列是現代的不確定性處理方式。"
      );
    }
    if (boundary && module.sect_named_boundary_disagreement === true) {
      notes.push(NAMED_BOUNDARY_DISAGREEMENT_NOTE);
    }
    notes.push("目前僅命運點與精神點。");
    notes.push(...classicalDisagreementNotes(response, "derived_methods.lots"));
    const bySect = isRecord(module.by_sect) ? module.by_sect : {};
    // 宮位由後端以行星同一條半開區間規則算出（lots.py _lot_house）；未算宮位時為 null。
    const houseCell = (value) => (Number.isInteger(value) ? `第 ${value} 宮` : DASH);
    const placement = isRecord(module.house_placement) ? module.house_placement : {};
    const lotPosition = (record, lot) =>
      (isRecord(record) && isRecord(record.sign_positions) ? record.sign_positions[lot] : null);
    const LOTS = [["fortune", "命運點 Fortune"], ["spirit", "精神點 Spirit"]];
    if (boundary) {
      // 兩個點 × 若為日盤／若為夜盤，兩列：日夜兩套只有兩個不同度數
      // （日盤命運點＝夜盤精神點），排成四列看起來像四個答案。
      const applied = module.sect_applied;
      const header = (key, label) => `${label}（${key === applied ? "本盤採用" : "比較值"}）`;
      const cell = (key, lot) => {
        const entry = isRecord(bySect[key]) ? bySect[key] : {};
        const position = lotPosition(entry, lot);
        if (!isSignPosition(position)) return DASH;
        const house = houseCell(entry[`${lot}_house`]);
        return `${signPosition(position)}，黃經 ${longitudeText(position)}°`
          + (house === DASH ? "" : `，${house}`);
      };
      return makeSection("lots", "阿拉伯點", RING.METHOD, status, {
        notes,
        tables: [{
          title: "點位",
          columns: ["點", header("day", "若為日盤"), header("night", "若為夜盤")],
          rows: LOTS.map(([lot, label]) => [label, cell("day", lot), cell("night", lot)]),
        }],
      });
    }
    const rows = LOTS.map(([lot, label]) => [
      label, ...positionCells(lotPosition(module, lot)), houseCell(placement[lot]),
    ]);
    return makeSection("lots", "阿拉伯點", RING.METHOD, status, {
      notes,
      tables: [{ title: "點位", columns: ["點", LONGITUDE_COLUMN, "星座度數", "宮位"], rows }],
    });
  }

  // 「邊界判定」一列依閉集 verdict（core/moon.py VOC_VERDICTS）。同時刻的容差與
  // 寫法同方法出處登錄 void_of_course.boundary_simultaneity_policy。
  const VOC_VERDICT_ZH = Object.freeze({
    not_void: "月亮離開本星座之前（或在盤上時刻當下）有相位精確完成，故非空亡。",
    simultaneous_boundary: "simultaneous_boundary：某個相位精確完成的時刻與月亮離開本星座的時刻，"
      + "相差不超過求根容差 1e-06 日（約 0.086 秒），數值上分不出先後。此情形既不判為"
      + "空亡、也不判為非空亡：is_void_of_course 為 null，verdict 為 "
      + "simultaneous_boundary；該相位與兩個根的括號區間一併列出，供複算。",
    void: "月亮離開本星座之前沒有任何相位精確完成，故為空亡。",
    not_evaluated: "換座時刻未能求得，本次未作空亡判定。",
  });

  function voidOfCourseSection(response) {
    const module = response.derived_methods.void_of_course;
    const status = moduleState(
      response, { option: "include_void_of_course", module: "void_of_course" }, module,
      isRecord(module) && "is_void_of_course" in module
    );
    if (status.state !== "present") {
      return absentSectionFor("void_of_course", "月空亡", RING.METHOD, "本次未請求月空亡。", status);
    }
    // all_candidates 依完成時刻排序，第一個就是下一個完成的相位。
    const candidates = Array.isArray(module.all_candidates) ? module.all_candidates : [];
    const next = isRecord(candidates[0]) ? candidates[0] : {};
    return makeSection("void_of_course", "月空亡", RING.METHOD, status, {
      // 這段限制由回應自帶的求解器欄位導出，不打字。打字的限制在後端改掉之後
      // 仍會留在畫面上，而它旁邊就印著證明它已經過時的那個欄位。
      notes: [
        solverLimitation(module),
        ...classicalDisagreementNotes(response, "derived_methods.void_of_course"),
      ],
      tables: [{
        title: "判定",
        columns: ["項目", "數值"],
        rows: [
          ["是否空亡", module.is_void_of_course === true ? "是"
            : (module.is_void_of_course === false ? "否" : DASH)],
          // 同時刻（simultaneous_boundary）時「是否空亡」為空白，理由就在這一列。
          ["邊界判定", Object.hasOwn(VOC_VERDICT_ZH, module.verdict)
            ? VOC_VERDICT_ZH[module.verdict] : DASH],
          ["離開本星座尚需（小時）", num(module.time_to_sign_exit_hours, 4)],
          ["下一個完成的相位", next.body || DASH],
          ["該相位角度", num(next.aspect_angle, 2)],
          ["尚需（日）", num(next.time_days, 6)],
        ],
      }],
    });
  }

  function declinationAspectsSection(response) {
    const module = response.derived_methods.declination_aspects;
    const status = moduleState(
      response, { option: "include_declination_aspects", module: "declination_aspects" }, module,
      isRecord(module) && Array.isArray(module.aspects)
    );
    if (status.state !== "present") {
      return absentSectionFor("declination_aspects", "赤緯平行與反平行", RING.GEOMETRY,
        "本次未請求。這是 17 世紀 Placidus 的界定，非古典傳統。", status);
    }
    const pairs = module.aspects;
    return makeSection("declination_aspects", "赤緯平行與反平行", RING.GEOMETRY, status, {
      notes: [
        `這是 17 世紀 Placidus 的界定，非古典傳統；本次使用 ${num((module.orb_receipt || {}).effective_orb_degrees, 3)}° 容許度。`,
      ],
      tables: [{
        title: "赤緯相位",
        columns: ["類型", "天體 A", "赤緯 A（度）", "天體 B", "赤緯 B（度）", "差值（度）"],
        rows: pairs.map((pair) => [
          // 未知類型不得落成「平行」：那是把不認得的值說成一個已知值。
          presentClosedVocabulary(pair.type, DECLINATION_ASPECT_ZH, "赤緯相位類型"),
          pair.body_a, dms(pair.declination_a),
          pair.body_b, dms(pair.declination_b),
          num(pair.diff, 4),
        ]),
      }],
    });
  }

  // ── 尊貴的各套分配法 ─────────────────────────────────────
  const TECHNIQUE_LABELS = Object.freeze({
    domicile_exaltation: "廟與旺 Domicile / Exaltation",
    bounds: "界 Bounds",
    face_decan: "面／旬 Face / Decan",
    triplicity: "三分性 Triplicity",
  });

  /**
   * 每一套尊貴技法自成一個區塊。
   *
   * 六套 profile 塞進同一個 section 會讓廟旺、界、面、三分性混在一起分不出
   * 段落。技法是使用者心裡的單位，區塊就該照技法切。
   */
  function rulerList(list) {
    return Array.isArray(list) && list.length ? list.map(rulerName).join("、") : DASH;
  }
  // 宮內度數由後端寫好（捨入不跨到下一度，所以不會跨出界段或旬的終點）。
  function degreeInSignText(object) {
    return typeof object.degree_in_sign_text === "string" ? object.degree_in_sign_text : DASH;
  }
  function degreeSpan(start, end) {
    if (typeof start !== "number" || typeof end !== "number") return DASH;
    const show = (value) => (Number.isInteger(value) ? String(value) : value.toFixed(2));
    return `${show(start)}°–${show(end)}°`;
  }
  function hasKey(record, key) {
    return isRecord(record) && key in record;
  }

  /**
   * 一套 profile 的逐星表。欄位只綁這個技法在 essential_dignities.py 真的會發的鍵：
   * 三分性是 day_rulers／night_rulers／selected_rulers（Ptolemy 另有
   * principal_ruler），界是 ruler＋界段（Chaldaean 另有日夜候選），面／旬是 ruler＋ruler_type。
   * 後端沒有「相合／不合」謂詞，所以只有廟旺有判定欄。
   * sectUnknown：日夜盤未知（essential_dignities.sect.selected_ruler_available === false），
   * 依日夜盤選主的欄位此時沒有選定值。
   */
  function dignityTable(technique, profile, title, sectUnknown) {
    const objects = Array.isArray(profile.objects) ? profile.objects : [];
    const name = (object) => object.name || object.key;
    if (technique === "domicile_exaltation") {
      return {
        title,
        columns: ["天體", "星座", "宮內度數", "廟", "旺", "判定"],
        rows: objects.map((object) => [
          name(object), signName(object.sign), degreeInSignText(object),
          (object.domicile_signs || []).map(signName).join("、") || DASH,
          signName(object.exaltation_sign),
          // 廟與旺各自成立：水星在處女座兩者同時為真，舊寫法只印「入廟」。
          [
            object.domicile_matched === true ? "入廟" : null,
            object.exaltation_matched === true ? "入旺" : null,
          ].filter(Boolean).join("、") || "無廟旺",
        ]),
      };
    }
    if (technique === "triplicity") {
      const withPrincipal = objects.some((object) => hasKey(object, "principal_ruler"));
      // Ptolemy 共治的指派主星與
      // 次要共主後端早已輸出（essential_dignities.py），畫面卻沒有綁定，方法頁說的
      // 「次要共主」欄位因此只在 JSON 裡存在。次要共主不計分。
      const withCoRulers = objects.some(
        (object) => hasKey(object, "assigned_rulers") || hasKey(object, "secondary_ruler")
      );
      return {
        title,
        columns: ["天體", "星座", "元素", "日間守護", "夜間守護", "本盤選定"]
          .concat(withPrincipal ? ["主守護"] : [])
          .concat(withCoRulers ? ["指派主星", "次要共主（不計分）"] : []),
        rows: objects.map((object) => [
          name(object), signName(object.sign),
          presentClosedVocabulary(object.element, ELEMENT_ZH, "元素"),
          rulerList(object.day_rulers), rulerList(object.night_rulers),
          sectUnknown ? "日夜盤未知，無法選定" : rulerList(object.selected_rulers),
        ].concat(withPrincipal
          ? [object.principal_ruler ? rulerName(object.principal_ruler) : "此元素未另列主守護"]
          : [])
          .concat(withCoRulers
            ? [
              rulerList(object.assigned_rulers),
              object.secondary_ruler
                ? rulerName(object.secondary_ruler)
                : (sectUnknown ? "日夜盤未知，無法選定" : DASH),
            ]
            : [])),
      };
    }
    if (technique === "bounds") {
      const withCandidates = objects.some(
        (object) => hasKey(object, "day_candidate") || hasKey(object, "night_candidate")
      );
      return {
        title,
        columns: ["天體", "星座", "宮內度數", "守護", "界段"]
          .concat(withCandidates ? ["日盤候選", "夜盤候選"] : []),
        rows: objects.map((object) => {
          const unresolved = object.ruler === null || object.ruler === undefined;
          const ruler = !unresolved
            ? rulerName(object.ruler)
            : (sectUnknown ? "日夜盤未知，無法選定（見日盤／夜盤候選）" : DASH);
          const row = [
            name(object), signName(object.sign), degreeInSignText(object), ruler,
            degreeSpan(object.segment_start_degrees, object.segment_end_degrees),
          ];
          if (!withCandidates) return row;
          const day = isRecord(object.day_candidate) ? object.day_candidate : {};
          const night = isRecord(object.night_candidate) ? object.night_candidate : {};
          if (row[4] === DASH) {
            row[4] = `日 ${degreeSpan(day.segment_start_degrees, day.segment_end_degrees)}`
              + `／夜 ${degreeSpan(night.segment_start_degrees, night.segment_end_degrees)}`;
          }
          return row.concat([rulerName(day.ruler), rulerName(night.ruler)]);
        }),
      };
    }
    // 面／旬的守護者型別不同（Chaldean 行星面是行星、Manilius 星座旬是星座），
    // 欄名依後端 ruler_type，不混用同一個「守護」。
    const rulerType = profile.ruler_type || (objects[0] && objects[0].ruler_type);
    const rulerLabel = rulerType === "planet" ? "守護行星" : (rulerType === "sign" ? "守護星座" : "守護");
    const withDecan = objects.some((object) => hasKey(object, "decan_number"));
    // Manilius 雙魚前兩旬是編者校正，方法頁說「回應中標明」，畫面也要標。
    const withReading = objects.some((object) => hasKey(object, "ruler_reading"));
    return {
      title,
      columns: ["天體", "星座", "宮內度數"].concat(withDecan ? ["旬"] : []).concat([rulerLabel])
        .concat(withReading ? ["讀法"] : []),
      rows: objects.map((object) => [name(object), signName(object.sign), degreeInSignText(object)]
        .concat(withDecan
          ? [typeof object.decan_number === "number" ? `第 ${object.decan_number} 旬` : DASH]
          : [])
        .concat([rulerName(object.ruler)])
        .concat(withReading
          ? [presentClosedVocabulary(object.ruler_reading, DECAN_READING_ZH, "讀法")]
          : [])),
    };
  }

  function dignityProfileSections(response) {
    const dignities = response.derived_methods.essential_dignities;
    if (!isRecord(dignities)) return [];
    const status = receiptStatus(dignities);
    // 四套技法各自選了哪個 profile 是收據的一部分；缺席不是「未選定」（未選定是 null）。
    if (!isRecord(dignities.selected_profiles)
      || !Object.keys(TECHNIQUE_LABELS).every((technique) => technique in dignities.selected_profiles)) {
      throw exportPipeline.incompleteResponse("本質尊貴缺少 selected_profiles");
    }
    const selected = dignities.selected_profiles;
    const results = isRecord(dignities.profile_results) ? dignities.profile_results : {};
    const comparison = new Set(Array.isArray(dignities.research_comparison_profiles)
      ? dignities.research_comparison_profiles : []);
    // 日夜盤是否可知、哪些 profile 依它選主，收據的 sect 區塊各說一次。
    const sect = isRecord(dignities.sect) ? dignities.sect : {};
    const sectUnknown = sect.selected_ruler_available === false;
    const sectDependent = new Set(Array.isArray(sect.sect_dependent_components)
      ? sect.sect_dependent_components : []);
    // 帶內旗標與帶寬讀同一份 sect 收據（後端 classify_sect）；選主仍只有一套。
    const sectInBand = !sectUnknown && sect.in_near_horizon_band === true;
    const sectBandArcmin = typeof sect.near_horizon_band_half_width_degrees === "number"
      ? num(sect.near_horizon_band_half_width_degrees * 60, 0) : DASH;

    return Object.keys(TECHNIQUE_LABELS).map((technique) => {
      const profileId = selected[technique];
      const sectionId = `dignity_${technique}`;
      if (status.state !== "present") {
        return absentSectionFor(sectionId, TECHNIQUE_LABELS[technique], RING.METHOD,
          "本次未請求本質尊貴。", status);
      }
      if (!profileId) {
        return absentSection(sectionId, TECHNIQUE_LABELS[technique], RING.METHOD,
          "本次未選定這套技法的 profile；未選定不是「沒有這個技法」。");
      }
      if (!isRecord(results[profileId])) {
        throw exportPipeline.incompleteResponse(`本質尊貴缺少 ${profileId} 的結果`);
      }
      const profile = results[profileId];
      const objects = Array.isArray(profile.objects) ? profile.objects : [];
      const notes = [
        profile.source ? `來源：${profile.source}` : null,
      ].filter(Boolean);
      if (sectUnknown && objects.length && sectDependent.has(profileId)) {
        notes.push("日夜盤未知時，這套技法的守護依日夜盤而異；本產品不替你選一個，日盤與夜盤候選並列。");
      }
      if (sectInBand && objects.length && sectDependent.has(profileId)) {
        notes.push(
          `太陽在近地平敏感帶（±${sectBandArcmin}′）內：這套技法依日夜盤選主星，`
          + `本盤依太陽真高度 > 0° 的規則判為${sect.is_day === true ? "日盤" : "夜盤"}；`
          + "若改用標準視日出等其他具名邊界，選到的主星可能不同。"
        );
      }
      const tables = [dignityTable(
        technique, profile,
        `${TECHNIQUE_LABELS[technique]}　${technique === "domicile_exaltation" ? "判定" : "守護配置"}`,
        sectUnknown
      )];

      // 並列比較的 profile 附在同一個技法底下，但明示不影響選定的那一套。
      Object.values(results).forEach((other) => {
        if (!isRecord(other) || other.technique !== technique) return;
        if (other.profile_id === profileId) return;
        if (!comparison.has(other.profile_id)) return;
        const sourceName = String(other.source || "其他來源").split(",")[0];
        tables.push(dignityTable(
          technique, other, `並列比較（不影響選定）：${sourceName}`, sectUnknown
        ));
      });

      return makeSection(sectionId, TECHNIQUE_LABELS[technique], RING.METHOD, status, {
        notes, tables, blocks: [],
      });
    });
  }

  // ── 驗算區段：軌跡、請求選項與輸出契約（只由完整回應建）──────────────
  /**
   * 逐步計算軌跡。
   *
   * 這是產品的頭號賣點——「每一步的函式、輸入、旗標、結果與當時的假設都攤開」。
   * 它是主要內容，不是附錄，因此預設就在頁面上，不藏在摺疊後面。
   */
  function traceSection(response) {
    const trace = response.calculation_trace || [];
    if (!trace.length) {
      return absentSection("trace", "逐步計算軌跡", RING.VERIFICATION,
        "本次回應沒有軌跡。");
    }
    const receipt = response.calculation_dossier.trace_receipt || {};
    return makeSection("trace", "逐步計算軌跡", RING.VERIFICATION, { state: "present" }, {
      notes: [
        `本次共 ${trace.length} 步。步數隨你勾選的模組而變，不是固定值。`,
        "整份可複製貼出去逐步對照；每一步都列出算式、輸入與結果。",
        receipt.python_json_serialization_sha256
          ? `序列化雜湊 ${receipt.python_json_serialization_sha256}`
            + "（對 Python 固定參數序列化的結果計算，不跨語言可攜，"
            + "只能偵測意外損壞，不證明來源，也不證明沒被刻意修改）"
          : null,
      ].filter(Boolean),
      tables: [{
        title: "軌跡",
        columns: ["#", "步驟", "算式", "輸入", "結果", "備註"],
        rows: trace.map((step, index) => [
          String(index + 1),
          step.title || DASH,
          step.formula || DASH,
          flattenPairs(step.inputs),
          flattenPairs(step.result),
          step.note || DASH,
        ]),
      }],
    });
  }

  /** 把 inputs／result 的物件壓成一行可讀文字，數值不改精度。 */
  function flattenPairs(value) {
    if (value === null || value === undefined) return DASH;
    if (!isRecord(value)) return String(value);
    const parts = Object.entries(value).map(([key, item]) => {
      const shown = isRecord(item) || Array.isArray(item)
        ? JSON.stringify(item) : String(item);
      return `${key}=${shown}`;
    });
    return parts.length ? parts.join("；") : DASH;
  }

  /**
   * 本次請求的選項。後端原樣回聲請求、不改寫（例如 date_only 仍回 include_houses=true），
   * 所以這是「請求了什麼」，不是「實際算了什麼」；後者看各模組自己的狀態。
   */
  function requestedOptionsSection(response) {
    const requested = response.requested_options;
    const keys = Object.keys(requested);
    if (!keys.length) {
      return absentSection("requested_options", "本次請求的選項", RING.VERIFICATION,
        "回應沒有回報請求的選項。");
    }
    return makeSection("requested_options", "本次請求的選項", RING.VERIFICATION, { state: "present" }, {
      notes: [
        "這是後端回報的本次請求值，含你沒有明示送出、由後端帶入的預設；"
        + "某個模組是否實際計算，看該模組自己的狀態。",
        "拿這份表就能重現同一次計算，不必記得自己勾了什麼。",
      ],
      tables: [{
        title: "請求的選項",
        columns: ["選項", "請求值"],
        rows: keys.sort().map((key) => [
          key,
          requested[key] === null ? "null（未選定）" : String(requested[key]),
        ]),
      }],
    });
  }

  /** 輸出契約：三層的定義與其 provisional 狀態。 */
  function contractSection(response) {
    const contract = response.output_contract;
    const layers = contract.layers || {};
    return makeSection("contract", "輸出契約", RING.VERIFICATION, { state: "present" }, {
      notes: [
        `契約狀態：${presentClosedVocabulary(contract.status, CONTRACT_STATUS_ZH, "契約狀態")}。`,
        `相容性政策：${presentClosedVocabulary(contract.compatibility, CONTRACT_COMPATIBILITY_ZH, "相容性政策")}。`,
      ],
      tables: [{
        title: "三層的定義（後端原文）",
        columns: ["層", "定義"],
        rows: Object.entries(layers).map(([key, text_]) => [key, text_]),
      }],
    });
  }

  // ── 出生時刻敏感度 ─────────────────────────────────────────
  const SENSITIVITY_SEMANTICS_ZH = Object.freeze({
    representative_midpoint_not_exact_birth_time:
      "代表性時刻是取樣區間中點，不代表出生發生在第 30 分鐘。",
    representative_first_available_probe_not_exact_birth_time:
      "區間中點在這個時區不存在，因此代表性時刻採用本小時第一個可取樣時刻；它仍不是精確出生時刻。",
    local_noon_computational_anchor_not_birth_time:
      "代表性時刻是當地正午的計算錨點，不是出生時刻。",
    local_noon_or_first_existing_instant_after:
      "當地正午在這一天因時鐘變更而不存在，代表性時刻採用正午之後第一個真實存在的時刻作為計算錨點；它不是出生時刻。",
    discrete_probes_not_continuous_hour_proof:
      "取樣點是每 15 分鐘一點；這一小時內若有時鐘變更，另加變更前後各一秒。"
      + "它們能找出取樣到的變動，但不能證明取樣點之間每一刻都相同。",
    hourly_local_clock_samples_plus_day_end_not_continuous_extrema_proof:
      "取樣點是當天每個存在的整點（重複的整點兩次都取）、當天每一段的第一秒與最後一秒，"
      + "以及每次時鐘變更前後落在當天的各一秒。它們能找出取樣到的星座變動，但不能證明取樣點之間每一刻都相同。",
  });
  const SKIP_REASON_ZH = Object.freeze({
    local_time_nonexistent: "時鐘沒有經過這一刻",
    house_system_unavailable_at_sample: "這一刻所選宮位制算不出宮頭",
  });
  // 後端標出的評估限制：取樣點在這種情形下界不住結果，受影響的路徑只算部分比較。
  const EVALUATION_LIMIT_ZH = Object.freeze({
    polar_ascendant_can_reverse_between_samples:
      "出生地在極圈內，上升點可能在兩個取樣時刻之間翻轉半個黃道再回來，"
      + "取樣點與細分時刻都可能漏掉其間的星座與宮位",
  });

  /** 敏感度區的說明：取樣區間、代表性時刻、取樣語意與限制、沒取樣的時刻、當天的時鐘變更。 */
  function sensitivityNotes(sensitivity) {
    const presentSensitivityText = (value) =>
      presentClosedVocabulary(value, SENSITIVITY_SEMANTICS_ZH, "語意");
    const notes = [
      `取樣區間：${sensitivity.interval_start_local || DASH} 至 `
      + `${sensitivity.interval_end_exclusive_local || DASH}（不含結尾）。`,
    ];
    // 只知時辰有三種讀法，後端只採一種，畫面要說是哪一種。
    if (sensitivity.precision === "approximate_hour") {
      notes.push(
        "「只知道約略小時」在這裡的意思是出生在這個鐘點之內（例如 14:00:00 到 14:59:59），"
        + "不是「整點前後半小時」，也不是「四捨五入到最近的整點」。"
      );
    }
    notes.push(
      `代表性時刻：${sensitivity.representative_local_time || DASH}，`
      + presentSensitivityText(sensitivity.representative_semantics)
    );
    if (sensitivity.sampling_semantics) {
      notes.push(presentSensitivityText(sensitivity.sampling_semantics));
    }
    // 取樣一致不等於結果穩定，也沒有任何不變式補上取樣點之間。
    notes.push(
      "「各取樣點分類相同」只表示在列出的取樣點分類一致，不代表結果穩定：兩個取樣點之間"
      + "仍可能變了又變回，本系統沒有用任何推論排除這種情形。黃經、四軸與宮頭的數值在區間內"
      + "本來就會移動，另以範圍列出。"
    );

    const probeCoverage = isRecord(sensitivity.probe_coverage) ? sensitivity.probe_coverage : null;
    const skipped = probeCoverage && Array.isArray(probeCoverage.skipped) ? probeCoverage.skipped : [];
    if (skipped.some((item) => isRecord(item) && item.reason_code === "local_time_nonexistent")) {
      notes.push("這個民用小時只有一部分實際存在；以下範圍只涵蓋可取樣的時刻。");
    }
    const limits = Array.isArray(sensitivity.evaluation_limits) ? sensitivity.evaluation_limits : [];
    limits.filter(isRecord).forEach((limit) => {
      const affected = (Array.isArray(limit.affected_paths) ? limit.affected_paths : [])
        .map((path) => SAME_GROUP_ZH[path] || modulePathLabel(path, {}));
      notes.push(
        `${presentClosedVocabulary(limit.reason_code, EVALUATION_LIMIT_ZH, "評估限制")}；`
        + `因此${affected.join("、")}只算部分比較，列出的集合不代表這一小時的全部可能。`
      );
    });
    if (skipped.length) {
      notes.push(
        "未取樣的時刻："
        + skipped
          .map((item) => `第 ${item.offset_seconds} 秒（`
            + `${presentClosedVocabulary(item.reason_code, SKIP_REASON_ZH, "原因")}）`)
          .join("、")
        + "。"
      );
    }
    const schedule = sensitivity.precision === "date_only" && isRecord(sensitivity.sample_schedule)
      ? sensitivity.sample_schedule
      : null;
    if (schedule && Array.isArray(schedule.utc_offset_changes) && schedule.utc_offset_changes.length) {
      notes.push(
        `這一天時鐘變更 ${schedule.utc_offset_changes.length} 次`
        + `（UTC ${schedule.utc_offset_changes.join("、")}），變更前後各取一秒。`
      );
    }
    if (schedule && Array.isArray(schedule.absent_hourly_labels) && schedule.absent_hourly_labels.length) {
      notes.push(`這些整點在這個時區當天不存在，沒有取樣：${schedule.absent_hourly_labels.join("、")}。`);
    }
    return notes;
  }

  /** 敏感度區的表格：每一種精度回的形狀各一張，加上其他判定與各模組的取樣涵蓋。 */
  function sensitivityTables(response, sensitivity) {
    // 每一種精度回的是不同的形狀，畫面必須各自承接。只讀其中一種而讓另一種
    // 落成空表，讀起來會像「沒有東西變動」——在後端剛好回報有變動時，那是把
    // 訊息反過來說。
    const tables = [];
    const bodyNames = Object.fromEntries(
      (sensitivity.body_signs || [])
        .concat(sensitivity.position_ranges || [])
        .filter((item) => item && item.key && item.name)
        .map((item) => [item.key, item.name])
    );
    const ranges = sensitivity.position_ranges || [];
    if (ranges.length) {
      tables.push({
        title: "位置範圍",
        columns: ["天體", "代表性黃經（度）", "取樣點出現的星座數", "取樣狀態"],
        rows: ranges.map((range) => [
          range.name || range.key,
          longitudeText(range.representative_sign_position),
          String((range.sampled_sign_indices || []).length),
          samplingStatus(range.status),
        ]),
      });
    }
    const bodySigns = sensitivity.body_signs || [];
    if (bodySigns.length) {
      tables.push({
        title: "星座落點",
        columns: ["天體", "代表性星座", "取樣點出現的星座數", "取樣狀態"],
        rows: bodySigns.map((item) => [
          item.name || item.key,
          item.representative_sign_index === null
            ? DASH
            : SIGNS[item.representative_sign_index],
          String((item.sampled_sign_indices || []).length),
          samplingStatus(item.status),
        ]),
      });
    }
    const placements = sensitivity.planet_in_house || [];
    if (placements.length) {
      tables.push({
        title: "落宮",
        columns: ["天體", "代表性宮位", "取樣點出現的宮位數", "取樣狀態"],
        rows: placements.map((item) => [
          item.name || item.key,
          item.representative_house === null || item.representative_house === undefined
            ? DASH
            : String(item.representative_house),
          String((item.sampled_houses || []).length),
          samplingStatus(item.status),
        ]),
      });
    }
    const ledger = (response.calculation_dossier.birth_time || {}).sensitivity_coverage;
    const summaryRows = [];
    const angles = isRecord(sensitivity.angles) ? sensitivity.angles : {};
    Object.keys(ANGLE_ZH).forEach((key) => {
      if (isRecord(angles[key])) {
        summaryRows.push([`${ANGLE_ZH[key]}的星座`, samplingStatus(angles[key].status)]);
      }
    });
    const cusps = Array.isArray(sensitivity.house_cusps) ? sensitivity.house_cusps : [];
    if (cusps.length && isRecord(ledger)) {
      const differing = cusps
        .filter((cusp) => isRecord(cusp) && cusp.status === "differs_between_samples")
        .map((cusp) => cusp.house);
      summaryRows.push([
        "宮頭的星座",
        samplingStatus(ledger["derived_methods.house_division"])
          + (differing.length ? `（第 ${differing.join("、")} 宮）` : ""),
      ]);
    }
    if (isRecord(sensitivity.sect)) {
      summaryRows.push(["日夜區分", samplingStatus(sensitivity.sect.status)]);
    }
    if (isRecord(sensitivity.lots)) {
      Object.keys(LOT_ZH).forEach((key) => {
        if (isRecord(sensitivity.lots[key])) {
          summaryRows.push([`${LOT_ZH[key]}的星座`, samplingStatus(sensitivity.lots[key].status)]);
          if (sensitivity.lots[key].house_status) {
            summaryRows.push([`${LOT_ZH[key]}的落宮`, samplingStatus(sensitivity.lots[key].house_status)]);
          }
        }
      });
      if (sensitivity.lots.discontinuity === "sect_flip") {
        summaryRows.push(["阿拉伯點的公式", "取樣時刻之間換了日夜盤公式"]);
      }
    }
    if (isRecord(sensitivity.void_of_course)) {
      summaryRows.push(["是否月空亡", samplingStatus(sensitivity.void_of_course.status)]);
    }
    if (summaryRows.length) {
      tables.push({
        title: "其他判定的取樣狀態",
        columns: ["判定", "取樣狀態"],
        rows: summaryRows,
      });
    }
    // 每一條可評估路徑一個狀態，由後端帳本決定；未請求、只算了代表
    // 性時刻、只比較一部分，三者分開寫。
    if (isRecord(ledger)) {
      tables.push({
        title: "各模組的取樣涵蓋",
        columns: ["模組", "狀態"],
        rows: Object.entries(ledger).map(([path, state]) => [
          SENSITIVITY_LEDGER_ZH[path] || modulePathLabel(path, bodyNames),
          samplingStatus(state),
        ]),
      });
    }
    return { tables, ledger, bodyNames };
  }

  function sensitivitySection(response) {
    const sensitivity = response.birth_time_sensitivity;
    // 精確時刻不取樣；其餘一律看模組自己的 status。兩個欄位缺一個都不能猜成「未取樣」或「被拒」。
    if (typeof sensitivity.precision !== "string"
      || (sensitivity.precision !== "exact" && typeof sensitivity.status !== "string")) {
      throw exportPipeline.incompleteResponse("出生時刻敏感度缺少 precision 或 status");
    }
    const section = (status, notes, tables, figures = []) => makeSection(
      "sensitivity", "出生時刻敏感度", RING.VERIFICATION, status, { figures, notes, tables },
    );
    if (sensitivity.precision === "exact") {
      return section({ state: "not_requested" }, [
        "出生時刻標記為精確到分鐘，因此沒有進行區間取樣。"
        + "若你其實只記得大約時辰，改選較寬的把握度，這裡會列出哪些判定會跟著改變。",
      ], []);
    }
    // 模組狀態沿用事件模組的詞彙：不是 computed，就沒有任何取樣結果可列，
    // 不能落成一張看起來「什麼都沒變」的空表。
    if (sensitivity.status !== "computed") {
      return section(
        { state: "refused", reason_code: sensitivity.reason_code || "" },
        ["這次沒有完成出生時刻的區間取樣，因此不列任何取樣結果；代表性時刻的命盤本身不受影響。"
          + `原因：${moduleReason(sensitivity.reason_code || "")}。`],
        []
      );
    }
    const notes = sensitivityNotes(sensitivity);
    const { tables, ledger, bodyNames } = sensitivityTables(response, sensitivity);
    const figure = samplingFigure(sensitivity, ledger, {
      bodyNames, ledgerLabel: (path) => SENSITIVITY_LEDGER_ZH[path] || modulePathLabel(path, bodyNames),
    });
    return section({ state: "present" }, notes, tables, figure ? [figure] : []);
  }

  // ═══ 取樣摘要 ═══════════════════════════════════════════════
  //
  // 敏感度區的第一行永遠是結論，不摺疊；下面是不可操作的取樣點標記：每個實際取樣
  // 的時刻一個獨立的點，點數取自回應（通常五個，時鐘變更或日期模式會不同），點與點
  // 之間不畫連續填滿的條，因為那裡沒有計算。改變的時刻畫成一段「帶」並標出解析度，
  // 不寫成單一時刻；「取樣點之間改變」「分類相同」「只比較一部分」「沒有比較」四組
  // 分開列，讓「查過而且會變」與「根本沒查」分得開。
  //
  // 措辭：「這五個取樣點分類相同」，不用「穩定」——相同只說取樣點一致，
  // 不說取樣點之間也一致。
  //
  // 與後端 TRANSITION_RESOLUTION_SECONDS 同值；tests/integration/
  // test_frontend_contract.py 直接比對兩處，改一邊另一邊的測試就紅。
  const TRANSITION_RESOLUTION_LIMIT_SECONDS = 15;
  // 日期模式月亮換星座的兩個取樣點：同一段之內，或分屬兩段、中間隔著時鐘標為別的日期的時間。
  const MOON_TRANSITION_RESOLUTION = Object.freeze({
    crossing_exists_between_adjacent_samples_exact_time_not_solved: "兩個相鄰取樣點之間，未再細分",
    crossing_exists_between_adjacent_samples_across_another_date_exact_time_not_solved:
      "兩個取樣點之間隔著屬於另一個日期的時間，未再細分",
  });
  // transitions[].semantics 的第二個值（backend TRANSITION_SEMANTICS）：跨過時鐘撥回、沒有細分的改變。
  const TRANSITION_ACROSS_UTC_GAP = "sampled_classification_change_across_a_utc_gap_not_bisected";
  const COUNT_ZH = ["零", "一", "兩", "三", "四", "五", "六", "七", "八", "九", "十"];
  function sampleCountWord(count) {
    return count >= 0 && count < COUNT_ZH.length ? COUNT_ZH[count] : ` ${count} `;
  }
  // 「YYYY-MM-DD HH:MM:SS.00」與「YYYY-MM-DDTHH:MM:SS」兩種寫法換成同一個可比較的鍵。
  function localKey(value) {
    const match = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/.exec(String(value || ""));
    return match ? `${match[1]}T${match[2]}` : null;
  }
  function clockLabel(key, day) {
    if (!key) return DASH;
    const [date, clock] = key.split("T");
    return date === day ? clock : `${date} ${clock}`;
  }
  // 每一條路徑比較的是它印出的全部分類（後端 classification_coverage），標籤照實寫出主要內容。
  const SAME_GROUP_ZH = Object.freeze({
    "astronomical_data.bodies": "天體的星座與行進方向",
    "astronomical_data.nodes": "月交點的星座與行進方向",
    "astronomical_data.angles": "四軸的星座",
    "derived_methods.house_division": "宮頭的星座",
    "derived_methods.planet_in_house": "行星落宮",
    "derived_methods.sect": "日夜區分（含近地平帶）",
    "derived_methods.lots": "阿拉伯點的星座、落宮與公式",
    "derived_methods.void_of_course": "是否月空亡",
    "derived_methods.dodecatemoria": "十二分部的星座與守護行星",
  });
  const PARTIAL_GROUP_ZH = Object.freeze({
    "derived_methods.void_of_course":
      "月空亡：只比較了「是否月空亡」一項；出宮時刻、下一個完成的相位與它的時刻都沒有重算",
  });
  // 角點與點的短名：圖文的分類句與取樣摘要共用（依這個順序列出）。
  const ANGLE_ZH = Object.freeze({ asc: "上升", mc: "中天", desc: "下降", ic: "天底" });
  const ANGLE_ORDER = Object.freeze(Object.keys(ANGLE_ZH));
  const LOT_ZH = Object.freeze({ fortune: "命運點", spirit: "精神點" });

  // 後端分類路徑 → 畫面上的一類（路徑寫法見 birth_time_sensitivity.printed_classifications）。
  // 成員（天體、角點、宮序、點）合併成一句，例如「上升、下降的星座」。畫面上一律是白話中文：
  // 認不得的欄位落到「所屬模組：其他附帶項目」，不印方括號、點號或英文鍵名。
  const MEMBER = "\\[([^\\]:]+)(?::[^\\]]*)?\\]";
  // 模組附帶的說明欄位（方法名、出處、名稱、語意說明、範圍）：不是計算結果，只會隨模組有無一起變。
  const MODULE_NOTE_KEYS = [
    "method", "method_status", "method_provenance", "source", "source_ref", "source_verification",
    "system_code", "system_name", "angles_source", "house_system_code", "house_system_name",
    "interval_semantics", "distance_to_nearest_cusp_semantics", "formula", "formula_profile", "formula_bases",
    "boundary_policy", "near_horizon_band", "display_center", "endpoint_rule", "lord_rule", "profile",
    "semantics", "scope", "time_basis", "solver", "solver_status",
  ].join("|");
  const OWNER_PATTERN = "astronomical_data\\.(?:angles|bodies|nodes)|derived_methods\\."
    + "(?:house_division|planet_in_house|sect|lots|void_of_course|dodecatemoria)";
  const CLASSIFICATION_KINDS = [
    [/^astronomical_data\.angles\.sign_positions\.(\w+)$/, "angles"],
    [/^derived_methods\.house_division\.cusp_sign_positions\[(\d+)\]$/, "house_cusps"],
    [new RegExp(`^astronomical_data\\.(?:bodies|nodes)${MEMBER}\\.sign_position$`), "body_signs"],
    [new RegExp(`^astronomical_data\\.(?:bodies|nodes)${MEMBER}\\.motion_sign$`), "motion"],
    [new RegExp(`^derived_methods\\.planet_in_house\\.(?:point_placements\\.)?placements${MEMBER}\\.house$`), "planet_in_house"],
    [new RegExp(`^derived_methods\\.planet_in_house\\.(?:point_placements\\.)?placements${MEMBER}\\.on_cusp$`), "on_cusp"],
    [/^derived_methods\.lots\.sign_positions\.(fortune|spirit)$/, "lot_signs"],
    [/^derived_methods\.lots\.house_placement\.(fortune|spirit)$/, "lot_houses"],
    [/^derived_methods\.lots\.by_sect\./, "lot_comparison"],
    [/^derived_methods\.lots\.(?:formula_basis|sect_applied|sect_status|sect_in_near_horizon_band|sect_named_boundary_disagreement)$/, "lot_formula"],
    [/^derived_methods\.sect\.(?:is_day|sect_status|sect_statuses\[\d+\]|in_near_horizon_band|named_boundary_disagreement)$/, "sect"],
    [/^derived_methods\.void_of_course\.(?:is_void_of_course|verdict)$/, "void_of_course"],
    [new RegExp(`^derived_methods\\.dodecatemoria\\.points${MEMBER}\\.(?:sign|sign_position|point_sign_position)$`), "dodecatemoria_signs"],
    [new RegExp(`^derived_methods\\.dodecatemoria\\.points${MEMBER}\\.domicile_lord$`), "dodecatemoria_lords"],
    [new RegExp(`^derived_methods\\.dodecatemoria\\.points${MEMBER}\\.(?:comparison_sign|sign_differs_under_other_sect)$`), "dodecatemoria_comparison"],
    [new RegExp(`^astronomical_data\\.(?:bodies|nodes)${MEMBER}\\.(altitude_apparent|apparent_magnitude|azimuth|phenomena)_reason_code$`), "body_reason"],
    // 模組本身在某些取樣點算不出來（例：那一刻所選宮位制沒有宮頭）時，模組的收據欄位跟著不同。
    [new RegExp(`^(${OWNER_PATTERN})\\.(?:applicable|available|executed|requested|reason_code|execution_status|availability\\.\\w+|point_placements\\.(?:execution_status|reason_code|rule))$`), "module_state"],
    // 同一時候，模組附帶的方法說明（方法名、出處、宮位制名稱）也會從有變沒有。
    [new RegExp(`^(${OWNER_PATTERN})\\.(?:${MODULE_NOTE_KEYS})(?:[.[]|$)`), "module_note"],
  ];
  const SINGLE_CLASSIFICATION_ZH = Object.freeze({
    lot_comparison: "阿拉伯點另一套公式（日盤／夜盤）的比較值",
    lot_formula: "阿拉伯點採用日盤還是夜盤公式",
    sect: "日夜區分（日盤或夜盤）",
    void_of_course: "是否月空亡",
  });
  // 認不得的欄位所屬的模組：只寫模組，不寫欄位鍵名。
  const PATH_OWNER_ZH = Object.freeze({
    "astronomical_data.bodies": "天體位置",
    "astronomical_data.nodes": "月交點",
    "astronomical_data.angles": "四軸",
    "derived_methods.house_division": "宮位",
    "derived_methods.planet_in_house": "落宮",
    "derived_methods.sect": "日夜區分",
    "derived_methods.lots": "阿拉伯點",
    "derived_methods.void_of_course": "月空亡",
    "derived_methods.dodecatemoria": "十二分部",
  });
  // 天體在某些取樣點算得出、某些算不出的附帶量（例：月亮在地平線下時沒有視星等）。
  const BODY_REASON_ZH = Object.freeze({
    altitude_apparent: "視地平高度",
    apparent_magnitude: "亮度（視星等）",
    azimuth: "方位角",
    phenomena: "亮面比例與離太陽的角距",
  });
  function classificationKind(path) {
    for (const [pattern, kind] of CLASSIFICATION_KINDS) {
      const match = pattern.exec(String(path));
      if (match) return kind === "body_reason" ? { kind: `body_reason_${match[2]}`, member: match[1] } : { kind, member: match[1] };
    }
    return null;
  }
  /** 成員鍵 → 中文名：回應自己帶的名稱優先，其次是後端名稱表、角點與阿拉伯點；都沒有就寫「另一個點」。 */
  function memberName(member, names) {
    const vocabulary = Labels.VOCABULARIES;
    return (names && names[member])
      || vocabulary.body_backend_name[member]
      || vocabulary.node_backend_name[member]
      || vocabulary.lunar_apsis_backend_name[member]
      || ANGLE_ZH[member]
      || LOT_ZH[member]
      || "另一個點";
  }
  /** 認不得的路徑：所屬模組加上成員名（有的話），例如「天體位置：太陽的其他附帶項目」。 */
  function otherClassificationLabel(path, names) {
    const text = String(path);
    const owner = /^[a-z_]+\.[a-z_]+/.exec(text);
    const ownerKey = owner ? owner[0] : "";
    const declared = PATH_OWNER_ZH[ownerKey] || (MODULE_COVERAGE[ownerKey] && MODULE_COVERAGE[ownerKey].zh);
    const member = /\[([^\]:]+)(?::[^\]]*)?\]/.exec(text.slice(ownerKey.length));
    const who = member && !/^\d+$/.test(member[1]) ? `${memberName(member[1], names)}的` : "";
    return `${declared || "其他模組"}：${who}其他附帶項目`;
  }

  /**
   * 一組改變的分類路徑，同類合併成白話的幾項：每項 { kind, members, text }。
   * 十二分部同一點的星座、所在星座與守護行星合成一句，不分開列。
   */
  function changedPathGroups(paths, names) {
    const groups = new Map();
    const other = [];
    (paths || []).forEach((path) => {
      const found = classificationKind(path);
      if (!found) {
        other.push(otherClassificationLabel(path, names));
        return;
      }
      if (!groups.has(found.kind)) groups.set(found.kind, []);
      if (found.member !== undefined && !groups.get(found.kind).includes(found.member)) {
        groups.get(found.kind).push(found.member);
      }
    });
    const named = (members) => members.map((member) => memberName(member, names)).join("、");
    const parts = [];
    const push = (kind, members, text) => parts.push({ kind, members, text });
    if (groups.has("angles")) {
      const members = groups.get("angles").slice().sort(
        (a, b) => ANGLE_ORDER.indexOf(a) - ANGLE_ORDER.indexOf(b)
      );
      push("angles", members, `${named(members)}的星座`);
    }
    if (groups.has("house_cusps")) {
      const houses = groups.get("house_cusps").map((index) => Number(index) + 1).sort((a, b) => a - b);
      push("house_cusps", houses.map(String), `第 ${houses.join("、")} 宮宮頭的星座`);
    }
    [
      ["body_signs", "的星座"],
      ["motion", "是順行還是逆行"],
      ["planet_in_house", "的落宮"],
      ["on_cusp", "是否壓在宮頭上"],
      ["lot_signs", "的星座"],
      ["lot_houses", "的落宮"],
    ].forEach(([kind, suffix]) => {
      if (groups.has(kind)) push(kind, groups.get(kind), `${named(groups.get(kind))}${suffix}`);
    });
    const twelfth = [...new Set([].concat(groups.get("dodecatemoria_signs") || [], groups.get("dodecatemoria_lords") || []))];
    if (twelfth.length) {
      const what = groups.has("dodecatemoria_signs") && groups.has("dodecatemoria_lords") ? "星座與守護行星"
        : groups.has("dodecatemoria_lords") ? "守護行星" : "星座";
      push("dodecatemoria", twelfth, `十二分部：${named(twelfth)}的${what}`);
    }
    if (groups.has("dodecatemoria_comparison")) {
      push("dodecatemoria_comparison", groups.get("dodecatemoria_comparison"),
        `十二分部：${named(groups.get("dodecatemoria_comparison"))}改用另一套日夜公式時的比較值`);
    }
    Object.keys(BODY_REASON_ZH).forEach((field) => {
      const kind = `body_reason_${field}`;
      if (groups.has(kind)) push(kind, groups.get(kind), `${named(groups.get(kind))}的${BODY_REASON_ZH[field]}算不算得出來`);
    });
    const owners = (kind) => (groups.get(kind) || []).map((owner) => PATH_OWNER_ZH[owner]).join("、");
    if (groups.has("module_state")) push("module_state", groups.get("module_state"), `${owners("module_state")}算不算得出來`);
    if (groups.has("module_note")) push("module_note", groups.get("module_note"), `${owners("module_note")}附帶的方法說明`);
    Object.keys(SINGLE_CLASSIFICATION_ZH).forEach((kind) => {
      if (groups.has(kind)) push(kind, [], SINGLE_CLASSIFICATION_ZH[kind]);
    });
    [...new Set(other)].forEach((text) => push("other", [], text));
    return parts;
  }

  /** 把一組改變的分類路徑寫成一行：同類合併（「上升、中天的星座；第 1、7 宮宮頭的星座」）。 */
  function changedPathsText(paths, names) {
    return changedPathGroups(paths, names).map((part) => part.text).join("；");
  }

  /** 每一個在取樣點之間不同的分類，用與 transitions.changed_paths 相同的路徑寫法。 */
  function differingClassificationPaths(sensitivity) {
    const coverage = isRecord(sensitivity.classification_coverage) ? sensitivity.classification_coverage : {};
    return Object.values(coverage)
      .filter(isRecord)
      .flatMap((item) => (Array.isArray(item.differing_classifications) ? item.differing_classifications : []));
  }

  function samplingMarks(sensitivity) {
    if (sensitivity.precision === "approximate_hour") {
      return (Array.isArray(sensitivity.probes) ? sensitivity.probes : [])
        .filter(isRecord)
        // fold 由後端逐點給出（PEP 495，1＝重複時刻的第二次）。部分重複的小時裡，
        // 重複區段外的取樣點只出現一次，不得一律依請求的 fold 標成第二次。
        .map((probe) => ({ key: localKey(probe.input_local_time), second_fold: probe.fold === 1 }));
    }
    if (sensitivity.precision === "date_only") {
      return (Array.isArray(sensitivity.samples) ? sensitivity.samples : [])
        .filter(isRecord)
        .map((sample) => ({ key: localKey(sample.local_time), second_fold: sample.fold === 1 }));
    }
    return [];
  }

  /** 每一段改變：時間範圍、解析度與改了什麼。日期模式只有月亮跨界、且沒有細分。 */
  function samplingBands(sensitivity, day, labels) {
    if (sensitivity.precision === "approximate_hour") {
      return (Array.isArray(sensitivity.transitions) ? sensitivity.transitions : [])
        .filter(isRecord)
        .map((item) => {
          const seconds = Number(item.resolution_seconds);
          // 兩個取樣點分屬這一小時的兩段 UTC（時鐘離開這一小時又回來）：中間的時間不屬於這一小時，
          // 後端不細分，只報兩段相對的兩端。沒帶 semantics（page 投影）時照細分的一段寫。
          const gap = item.semantics === TRANSITION_ACROSS_UTC_GAP;
          return {
            lower: localKey(item.lower_bound_local),
            upper: localKey(item.upper_bound_local),
            paths: Array.isArray(item.changed_paths) ? item.changed_paths : [],
            gap,
            resolution: gap ? "時鐘在這兩刻之間撥回，未再細分"
              : Number.isFinite(seconds) && seconds <= TRANSITION_RESOLUTION_LIMIT_SECONDS
              ? `解析度 ≤${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒`
              : `解析度 ${Number.isFinite(seconds) ? seconds : DASH} 秒`,
          };
        })
        .map((band) => ({ ...band, range: `${clockLabel(band.lower, day)}–${clockLabel(band.upper, day)}`,
          text: changedPathsText(band.paths, labels.bodyNames) || DASH }));
    }
    const moon = isRecord(sensitivity.moon_boundary_assessment) ? sensitivity.moon_boundary_assessment : {};
    return (Array.isArray(moon.sampled_sign_boundary_transitions) ? moon.sampled_sign_boundary_transitions : [])
      .filter(isRecord)
      .map((item) => {
        const lower = localKey(item.lower_sample_local);
        const upper = localKey(item.upper_sample_local);
        const paths = ["astronomical_data.bodies[moon].sign_position"];
        return {
          lower, upper, paths,
          range: `${clockLabel(lower, day)}–${clockLabel(upper, day)}`,
          resolution: MOON_TRANSITION_RESOLUTION[item.semantics] || DASH,
          text: changedPathsText(paths, labels.bodyNames),
        };
      });
  }

  function samplingFigure(sensitivity, ledger, labels) {
    const marks = samplingMarks(sensitivity).filter((mark) => mark.key);
    if (!marks.length) return null;
    const count = marks.length;
    const word = sampleCountWord(count);
    const day = localKey(sensitivity.interval_start_local)
      ? localKey(sensitivity.interval_start_local).split("T")[0]
      : marks[0].key.split("T")[0];
    const representativeKey = localKey(sensitivity.representative_local_time);
    const representativeIndex = marks.findIndex((mark) => mark.key === representativeKey);
    const markLabel = (mark) => clockLabel(mark.key, day) + (mark.second_fold ? "（第二次）" : "");

    const differing = differingClassificationPaths(sensitivity);
    const status = sensitivity.classification_status;
    let tone = "none";
    let lead = `這${word}個取樣點沒有可比較的分類。`;
    if (count < 2) {
      lead = "只取到一個取樣點，沒有可以互相比較的時刻。";
    } else if (status === "same_at_all_samples") {
      tone = "same";
      lead = `這${word}個取樣點分類相同。`;
    } else if (status === "differs_between_samples") {
      tone = "differs";
      lead = `這${word}個取樣點分類不全相同：本站在這段時間裡實際重算的${word}個時刻（取樣點），`
        + "算出的結果不完全一樣；下面列出哪些會變、大約在什麼時候變。";
    }
    // 細分改變時刻時算過的中間時刻也算數：只在那些時刻出現的值同樣計入。
    const coverage = isRecord(sensitivity.probe_coverage) ? sensitivity.probe_coverage : {};
    const refined = Array.isArray(coverage.refinement_offsets_seconds) ? coverage.refinement_offsets_seconds.length : 0;

    const bands = samplingBands(sensitivity, day, labels);
    const bandsAfter = marks.map(() => 0);
    bands.forEach((band) => {
      for (let index = 0; index < marks.length - 1; index += 1) {
        if (band.lower && band.upper && marks[index].key <= band.lower && band.upper <= marks[index + 1].key) {
          bandsAfter[index] += 1;
          return;
        }
      }
    });

    const altParts = [
      `取樣點 ${count} 個：`
      + marks.map((mark, index) => markLabel(mark) + (index === representativeIndex ? "（代表性時刻）" : "")).join("、")
      + "。",
    ];
    bandsAfter.forEach((n, index) => {
      if (n) altParts.push(`${markLabel(marks[index])} 與 ${markLabel(marks[index + 1])} 之間有 ${n} 段改變。`);
    });

    const groups = [];
    const banded = new Set(bands.flatMap((band) => band.paths));
    const unbanded = differing.filter((path) => !banded.has(path));
    if (bands.length || differing.length) {
      const bisected = bands.filter((band) => !band.gap);
      const notes = sensitivity.precision === "date_only"
        ? ["日期模式只在取樣點比較，沒有細分改變的時刻。"]
        : [].concat(
          bisected.length
            ? ["每一段是改變發生的時間範圍，不是單一時刻；一段之內至少改變一次，不一定只有一次。"
              + `「解析度 ≤${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒」是說這段時間不超過 ${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒。`]
            : [],
          refined ? [`為了找出改變的時間，本站在取樣點之間另外加算了 ${refined} 個時刻。`] : [],
          bands.some((band) => band.gap)
            ? ["標「時鐘在這兩刻之間撥回」的一段：鐘面上這兩個時刻看起來相鄰，中間其實隔著一段不屬於這一小時的時間"
              + "（時鐘撥回，離開這一小時又回來）；改變發生在那段時間裡，沒有再細分。"]
            : []
        );
      groups.push({
        tone: "differs",
        title: "會變的：取樣點之間結果不同",
        note: notes.join(""),
        bands: bands.map(({ range, resolution, text }) => ({ range, resolution, text })),
        items: unbanded.length ? [changedPathsText(unbanded, labels.bodyNames)] : [],
      });
    }
    if (isRecord(ledger)) {
      const pathsIn = (state) => Object.keys(ledger).filter((path) => ledger[path] === state);
      const same = pathsIn("same_at_all_samples");
      if (same.length) {
        groups.push({
          tone: "same",
          title: `不變的：這${word}個取樣點分類相同`,
          note: "",
          bands: [],
          items: same.map((path) => SAME_GROUP_ZH[path] || labels.ledgerLabel(path)),
        });
      }
      const partial = pathsIn("partially_evaluated");
      if (partial.length) {
        groups.push({
          tone: "partial",
          title: "只比較了一部分",
          note: "",
          bands: [],
          items: partial.map((path) => PARTIAL_GROUP_ZH[path] || labels.ledgerLabel(path)),
        });
      }
      const unchecked = pathsIn("not_evaluated");
      if (unchecked.length) {
        groups.push({
          tone: "unchecked",
          title: "沒有比較：只算了代表性時刻（畫面上星盤用的那一刻）",
          note: "這些結果只對代表性時刻成立；在這段時間內會不會改變，沒有檢查。",
          bands: [],
          items: unchecked.map(labels.ledgerLabel),
        });
      }
    }

    return {
      kind: "sampling_marks",
      tone,
      lead,
      marks: marks.map((mark, index) => ({
        label: markLabel(mark),
        representative: index === representativeIndex,
        bands_after: bandsAfter[index],
        gap_label: bandsAfter[index] ? `${bandsAfter[index]} 段` : "",
      })),
      text_alternative: altParts.join(""),
      // legend 只描述圖形本身，文字輸出不印；note 是事實，每一種輸出都印。
      legend: representativeIndex >= 0 ? "空心點是代表性時刻。" : "",
      note: "點與點之間沒有計算。",
      groups,
    };
  }

  // ═══ 結果頂端：出生時間不確定時的白話摘要 ═══════════════════════
  //
  // 只在出生時間是約略時辰或只有日期、而且取樣算完時出現；精確時刻與取樣被拒時為 null。
  // 每一句都取自同一份回應（取樣點、改變的時間段、各模組的比較帳本、代表性時刻的星座），
  // 不推論、不解讀：「從 A 換到 B」只在那一項恰好只有一段改變、取樣只見兩個值、而且代表性
  // 時刻在那一段之外時才寫——那時取樣點在那一段兩側各自只有一個值。
  const BIRTH_TIME_SUMMARY_TITLE = "出生時間不確定：哪些結果會變";
  const SENSITIVITY_LEDGER_ZH = Object.freeze({ "astronomical_data.bodies": "天體位置" });

  function sensitivityNames(sensitivity) {
    return Object.fromEntries(
      [].concat(sensitivity.body_signs || [], sensitivity.position_ranges || [])
        .filter((item) => isRecord(item) && item.key && item.name)
        .map((item) => [item.key, item.name])
    );
  }
  function minuteOf(key) {
    return key ? key.split("T")[1].slice(0, 5) : DASH;
  }
  /** 一段改變的時間，寫成一般人讀的樣子：「約 14:28」「14:00–15:00 之間」。 */
  function bandWhen(band, precision, day) {
    if (band.gap) {
      return `時鐘撥回處（${clockLabel(band.lower, day)} 與 ${clockLabel(band.upper, day)} 之間）`;
    }
    if (precision === "date_only") return `${minuteOf(band.lower)}–${minuteOf(band.upper)} 之間`;
    const lower = minuteOf(band.lower);
    const upper = minuteOf(band.upper);
    return lower === upper ? `約 ${lower}` : `約 ${lower}–${upper}`;
  }

  function birthTimeSummary(response) {
    const sensitivity = isRecord(response) && isRecord(response.birth_time_sensitivity)
      ? response.birth_time_sensitivity : null;
    if (!sensitivity || sensitivity.status !== "computed"
      || !["approximate_hour", "date_only"].includes(sensitivity.precision)) {
      return null;
    }
    const precision = sensitivity.precision;
    const marks = samplingMarks(sensitivity).filter((mark) => mark.key);
    if (!marks.length) return null;
    const count = marks.length;
    const day = localKey(sensitivity.interval_start_local)
      ? localKey(sensitivity.interval_start_local).split("T")[0]
      : marks[0].key.split("T")[0];
    const names = sensitivityNames(sensitivity);
    const representativeKey = localKey(sensitivity.representative_local_time);
    const representativeClock = clockLabel(representativeKey, day);
    const ledger = ((response.calculation_dossier || {}).birth_time || {}).sensitivity_coverage;
    const ledgerLabel = (path) => SENSITIVITY_LEDGER_ZH[path] || modulePathLabel(path, names);

    const intro = precision === "approximate_hour"
      ? `你填的是「大約幾點」，所以本站在 ${minuteOf(marks[0].key)}–${minuteOf(marks[count - 1].key)} 之間取 ${count} 個時刻`
        + `（取樣點）各算一次，比較結果。上面的星盤是用 ${representativeClock} 算的。`
      : `你只填了日期，所以本站在 ${day} 這一天取 ${count} 個時刻（取樣點）各算一次，比較結果。`
        + `上面的星盤用的是 ${representativeClock}，那只是計算的基準，不是出生時間。`;

    const bands = samplingBands(sensitivity, day, { bodyNames: names });
    const differing = differingClassificationPaths(sensitivity);
    const keyOf = (part) => (part.kind === "other" ? `other:${part.text}` : part.kind);
    // 每一類改變出現在哪幾段。
    const whenByKind = new Map();
    bands.forEach((band) => {
      changedPathGroups(band.paths, names).forEach((part) => {
        const key = keyOf(part);
        if (!whenByKind.has(key)) whenByKind.set(key, []);
        const text = bandWhen(band, precision, day);
        if (!whenByKind.get(key).includes(text)) whenByKind.get(key).push(text);
      });
    });
    // 一個成員的改變落在哪幾段（路徑的類別與成員都相同）。
    const bandsOf = (kind, member) => bands.filter((band) => band.paths.some((path) => {
      const found = classificationKind(path);
      return found && found.kind === kind && found.member === member;
    }));
    const fromTo = (kind, member, representative, values, render) => {
      const only = bandsOf(kind, member);
      if (only.length !== 1 || !Array.isArray(values) || values.length !== 2 || !representativeKey) return null;
      if (representative === null || representative === undefined || !values.includes(representative)) return null;
      const other = values.find((value) => value !== representative);
      // 一段的下界是左側的值、上界是右側的值（取樣點或二分時的中間時刻），代表性時刻落在端點上也算在那一側。
      if (representativeKey <= only[0].lower) return [render(representative), render(other)];
      if (representativeKey >= only[0].upper) return [render(other), render(representative)];
      return null;
    };
    const sampledSignName = (index) => SIGNS[index] || DASH;
    const houseName = (house) => `第 ${house} 宮`;
    const details = (part) => {
      const found = [];
      if (part.kind === "angles" && part.members.includes("asc")) {
        const asc = isRecord(sensitivity.angles) && isRecord(sensitivity.angles.asc) ? sensitivity.angles.asc : {};
        const printed = (((response.astronomical_data || {}).angles || {}).sign_positions || {}).asc;
        const pair = fromTo("angles", "asc", Array.isArray(printed) ? printed[0] : null,
          asc.sampled_sign_indices, sampledSignName);
        if (pair) found.push(`上升從${pair[0]}換到${pair[1]}`);
      }
      if (part.kind === "body_signs") {
        part.members.forEach((member) => {
          const row = [].concat(sensitivity.body_signs || [], sensitivity.position_ranges || [])
            .find((item) => isRecord(item) && item.key === member);
          if (!row) return;
          const representative = row.representative_sign_index !== undefined
            ? row.representative_sign_index
            : (Array.isArray(row.representative_sign_position) ? row.representative_sign_position[0] : null);
          const pair = fromTo("body_signs", member, representative, row.sampled_sign_indices, sampledSignName);
          if (pair) found.push(`${memberName(member, names)}從${pair[0]}換到${pair[1]}`);
        });
      }
      if (part.kind === "planet_in_house") {
        part.members.forEach((member) => {
          const name = memberName(member, names);
          const row = (sensitivity.planet_in_house || []).find((item) => isRecord(item) && item.name === name);
          if (!row) return;
          const pair = fromTo("planet_in_house", member, row.representative_house, row.sampled_houses, houseName);
          if (pair) found.push(`${name}從${pair[0]}換到${pair[1]}`);
        });
      }
      return found;
    };

    const changes = changedPathGroups(differing.concat(bands.flatMap((band) => band.paths)), names)
      .map((part) => {
        const times = whenByKind.get(keyOf(part)) || [];
        const extra = details(part);
        return {
          what: part.text,
          when: (times.length
            ? `${times.join("、")}${times[times.length - 1].endsWith("）") ? "" : " "}改變`
            : "取樣點之間不同，沒有細算是在哪一刻變的")
            + (extra.length ? `（${extra.join("；")}）` : ""),
        };
      });

    const pathsIn = (state) => (isRecord(ledger) ? Object.keys(ledger).filter((path) => ledger[path] === state) : []);
    const same = pathsIn("same_at_all_samples").map((path) => {
      const label = SAME_GROUP_ZH[path] || ledgerLabel(path);
      const asc = isRecord(sensitivity.angles) && isRecord(sensitivity.angles.asc) ? sensitivity.angles.asc : null;
      if (path === "astronomical_data.angles" && asc && Array.isArray(asc.sampled_sign_indices)
        && asc.sampled_sign_indices.length === 1) {
        return `${label}（上升都是${sampledSignName(asc.sampled_sign_indices[0])}）`;
      }
      return label;
    });
    const partial = pathsIn("partially_evaluated").map((path) => PARTIAL_GROUP_ZH[path] || ledgerLabel(path));
    const unchecked = pathsIn("not_evaluated").map(ledgerLabel);

    // 第一句是白話：在哪一段時間、會變幾類或都一樣（細節區照 Option D 的「取樣點分類」說法）。
    const status = sensitivity.classification_status;
    const span = precision === "approximate_hour"
      ? `在 ${minuteOf(marks[0].key)}–${minuteOf(marks[count - 1].key)} 之間`
      : `在 ${day} 這一天裡`;
    let lead = `${span}，沒有可以互相比較的結果。`;
    if (count < 2) {
      lead = "只取到一個時刻，沒有可以互相比較的結果。";
    } else if (status === "same_at_all_samples") {
      lead = `${span}，比較過的結果都一樣。`;
    } else if (status === "differs_between_samples") {
      lead = `${span}，有 ${changes.length} 類結果會變。`;
    }
    return {
      title: BIRTH_TIME_SUMMARY_TITLE,
      lead,
      intro,
      changes,
      same,
      partial,
      unchecked,
      caveat: "「不變」只表示取樣到的時刻結果相同，兩個取樣點之間仍可能變了又變回。"
        + (precision === "approximate_hour"
          ? "「約幾點改變」指的是一小段時間，這段之內至少變了一次。"
          : "日期模式只比較取樣點，沒有細算改變的時刻。"),
      link_text: "看細節",
      target_id: "section-sensitivity",
      // 結果最上方、每一章都看得到的一行，連到這個摘要。
      notice_text: "出生時間不確定，看哪些結果會變",
      notice_target_id: "sampling-callout",
    };
  }

  // ── 計算收據 ─────────────────────────────────────────────
  function receiptSection(response) {
    const dossier = response.calculation_dossier;
    const engine = dossier.engine || {};
    const privacy = dossier.privacy || {};
    const receipt = dossier.input_receipt || {};
    const place = dossier.location_resolution || {};
    const policy = dossier.calculation_policy || {};
    const traceReceipt = dossier.trace_receipt || {};
    const time = response.astronomical_data.time || {};
    const trace = response.calculation_trace || [];
    const buildIdentity = dossier.build_identity || {};
    const releaseIdentity = buildIdentity.release_identity || {};
    const releaseRows = releaseIdentity.status === "available" ? [
      ["組合發布識別", releaseIdentity.combined_release_id],
      ["後端 image", (releaseIdentity.backend || {}).image_id],
      ["前端 artifact", (releaseIdentity.frontend || {}).artifact_digest],
      // 兩個 public_source_revision 與 source_url 都來自後端
      // 的 release identity（由發布流程注入），前端不手打。
      ["後端公開原始碼修訂", (releaseIdentity.backend || {}).public_source_revision],
      ["後端原始碼網址", (releaseIdentity.backend || {}).source_url],
      ["前端公開原始碼修訂", (releaseIdentity.frontend || {}).public_source_revision],
      ["前端原始碼網址", (releaseIdentity.frontend || {}).source_url],
    ] : [];
    return makeSection("receipt", "計算收據", RING.VERIFICATION, { state: "present" }, {
      notes: [
        "這是本次計算的可重現證據，不是占星解讀，也不是任何外部天文、方法、"
        + "資安或法規認證。",
        `隱私聲明狀態：${presentClosedVocabulary(privacy.attestation_status, ATTESTATION_STATUS_ZH, "隱私聲明狀態")}；`
        + "它不等於已通過外部審查。",
      ],
      tables: [
        {
          title: "版本與來源",
          columns: ["項目", "數值"],
          rows: [
            ["API schema", response.schema_version],
            ["Calculation Dossier", dossier.dossier_version],
            ["Dossier 狀態", presentClosedVocabulary(dossier.status, DOSSIER_STATUS_ZH, "Dossier 狀態")],
            ["Dossier 權威", dossier.authority],
            // 後端 build_identity 只發 source_revision／revision_source／status。
            ["建置識別", buildIdentity.source_revision
              || presentClosedVocabulary(buildIdentity.status, BUILD_IDENTITY_STATUS_ZH, "建置識別狀態")],
            ...releaseRows,
            ["pyswisseph", engine.pyswisseph_distribution_version],
            ["Swiss Ephemeris", engine.swiss_ephemeris_library_version],
            ["時區資料庫", tzDatabase(engine.tz_database)],
            ["星曆來源", engine.requested_ephemeris_source],
            ["星曆譜系", ephemerisLineage(engine.ephemeris_dataset_lineage)],
          ],
        },
        {
          title: "已驗證的輸入（input receipt）",
          columns: ["項目", "數值"],
          rows: [
            ["出生時刻把握程度", Labels.label("birth_time_precision", receipt.birth_time_precision)],
            ["本地時間", (time.input_local_time)],
            ["時區", Labels.timezoneText(time.timezone_label)],
            // 新疆的地點由使用者指明出生紀錄用的鐘點；只在真的做了這個選擇時出現。
            ...((receipt.timezone || {}).civil_time_basis
              ? [["出生紀錄的鐘點", Labels.label("civil_time_basis", receipt.timezone.civil_time_basis)]]
              : []),
            ["UTC 偏移", utcOffsetText(time.utc_offset_hours)],
            // 後端在模糊時刻已經逐字說明採用了
            // 哪一次、另一次是什麼，前端卻整份丟掉。使用者因此看不出自己
            // 的盤是從兩個可能時刻裡挑出來的。只在真的模糊時出現。
            ...(time.dst_warning
              ? [["重複民用時刻的處置", time.dst_warning]]
              : []),
            [timeScaleLabel(time.time_scale_era), time.utc_time],
            ["儒略日 JD(UT)", num(time.jd_ut, 6)],
            ["ΔT（秒）", num(time.delta_t_seconds, 3)],
            ["Swiss 時間輸入語義", time.swiss_time_input_semantics],
            ["ΔT 模型狀態", (time.delta_t_model || {}).status],
            ["緯度", num((receipt.location || {}).latitude, 6)],
            ["經度", num((receipt.location || {}).longitude, 6)],
            ["海拔（公尺）", num((receipt.location || {}).altitude_m, 1)],
          ],
        },
        {
          title: "地點解析",
          columns: ["項目", "數值"],
          rows: [
            ["地點標籤", place.place_label],
            ["來源", place.location_source],
            ["目錄記錄 id", place.source_record_id],
            ["位置精度", place.location_precision],
            ["驗證狀態", place.verification_status],
          ],
        },
        {
          title: "計算政策",
          columns: ["項目", "數值"],
          rows: [
            // 標籤與匯出開頭的計算模式行同一份；章動不在這張收據表。
            ...exportPipeline.COMPUTATION_MODE_FIELDS
              .filter(([key]) => key !== "nutation")
              .map(([key, label]) => [label, (policy.computation_mode || {})[key]]),
            ["旗標政策", flagPolicy(policy.flag_policy)],
            ["月亮位置", moonPositionReceipt(policy.moon_position)],
          ],
        },
        {
          title: "軌跡收據",
          columns: ["項目", "數值"],
          rows: [
            ["逐步軌跡步數", String(trace.length)],
            ["後端回報步數", String(traceReceipt.step_count === undefined
              ? DASH : traceReceipt.step_count)],
            ["序列化雜湊 SHA-256", traceReceipt.python_json_serialization_sha256],
            ["跨語言可攜", (traceReceipt.serialization_recipe || {})
              .portable_across_languages === true ? "是" : "否（僅供偵測意外損壞）"],
          ],
        },
        {
          title: "隱私聲明",
          columns: ["項目", "數值"],
          rows: [
            ["聲明版本", privacy.privacy_attestation_version],
            ["聲明狀態", presentClosedVocabulary(privacy.attestation_status, ATTESTATION_STATUS_ZH, "隱私聲明狀態")],
            ["含敏感出生資料", privacy.contains_sensitive_birth_data === true ? "是" : "否"],
            ["可匿名分享", privacy.anonymous_share_ready === true ? "是" : "否"],
            ["已列出的未涵蓋層", uncoveredLayers(privacy.uncovered_layers)],
            ["App 持久化邊界", "計算期間不寫檔、不建立帳號或命盤資料庫；"
              + "下載是你主動觸發的本機寫入，本頁無法收回"],
          ],
        },
      ],
    });
  }

  // ═══ 本命盤速覽 ═════════════════════════════════════════
  //
  // 太陽、月亮與上升的星座，排在結果最前面。不另算：單一星座照印天體表與軸點表
  // 那一格（同一個 signPosition）；出生時刻不精確時，候選星座讀後端取樣的星座集合
  // （只知小時：body_signs、angles.asc；只知日期：position_ranges），集合有兩個以上
  // 就全部列出。集合只含取樣時刻看到的星座，所以註明「取樣到的」。不寫任何解讀。
  const SUMMARY_TITLE = "本命盤速覽";
  const SUMMARY_CHANGES = "（這段時間內會換星座）";
  // 速覽的三列：點鍵與列名。表格列名與圖表連動的鍵都取這一份。
  const SUMMARY_ROWS = Object.freeze([["sun", "太陽星座"], ["moon", "月亮星座"], ["asc", "上升星座"]]);

  /** 星座索引依黃道順序排：從前一個星座不在集合裡的那一個開始，跨 0° 時雙魚接牡羊。 */
  function zodiacOrder(indices) {
    const present = new Set(indices);
    const start = indices.find((index) => !present.has((index + 11) % 12));
    if (start === undefined) return indices.slice().sort((a, b) => a - b);
    return Array.from({ length: 12 }, (_, step) => (start + step) % 12)
      .filter((index) => present.has(index));
  }

  /** 一個天體或上升點的那一格：取樣集合有兩個以上星座就列候選，否則照印代表值。 */
  function summaryCell(sampled, position) {
    const indices = isRecord(sampled) && Array.isArray(sampled.sampled_sign_indices)
      ? sampled.sampled_sign_indices.filter((index) => Number.isInteger(index) && index >= 0 && index < 12)
      : null;
    if (indices && indices.length > 1) {
      const names = zodiacOrder(indices).map((index) => SIGNS[index]);
      return `${names.slice(0, -1).join("、")}或${names[names.length - 1]}${SUMMARY_CHANGES}`;
    }
    if (indices && indices.length === 0) return samplingStatus(sampled.status);
    return signPosition(position);
  }

  function summarySection(response, angles) {
    // 日心或質心沒有地表觀測者：與軸點表同一個拒絕與原因。
    if (angles.status.state === "refused" && angles.status.reason_code === "non_earth_observer_center") {
      return absentSectionFor("summary", SUMMARY_TITLE, RING.ASTRONOMICAL, "", angles.status);
    }
    const sensitivity = isRecord(response.birth_time_sensitivity) ? response.birth_time_sensitivity : {};
    const precision = sensitivity.precision;
    const sampledList = precision === "approximate_hour" ? sensitivity.body_signs
      : precision === "date_only" ? sensitivity.position_ranges : null;
    const samplesByKey = Object.fromEntries(
      (Array.isArray(sampledList) ? sampledList : [])
        .filter((item) => isRecord(item) && item.key)
        .map((item) => [item.key, item])
    );
    const bodies = response.astronomical_data.bodies || [];
    const bodyRow = (key, label) => {
      const body = bodies.find((item) => isRecord(item) && item.key === key);
      return [label, summaryCell(samplesByKey[key], body ? body.sign_position : null)];
    };

    const angleRecord = response.astronomical_data.angles;
    const ascPosition = isRecord(angleRecord) && isRecord(angleRecord.sign_positions)
      ? angleRecord.sign_positions.asc : null;
    let ascText;
    if (angles.status.state === "present") {
      const sampledAngles = precision === "approximate_hour" && isRecord(sensitivity.angles)
        ? sensitivity.angles.asc : null;
      ascText = summaryCell(sampledAngles, ascPosition);
    } else if (angles.status.reason_code === "date_only_no_birth_time") {
      ascText = "需要出生時間";
    } else if (angles.status.state === "not_requested") {
      ascText = "本次未計算軸點";
    } else {
      ascText = moduleReason(angles.status.reason_code);
    }

    const notes = [];
    if (precision === "approximate_hour" || precision === "date_only") {
      notes.push("出生時刻不精確：只有一個星座的，度數取自代表性時刻，不是出生時刻；"
        + "會換星座的，列出取樣到的每一個星座。");
    }
    if (angles.status.reason_code === "date_only_no_birth_time") {
      notes.push("上升星座需要出生時刻；知道大約幾點時，可改選「只知道約略小時」。");
    }

    const sidereal = response.computation_mode.zodiac === "sidereal";
    return makeSection("summary", SUMMARY_TITLE, RING.ASTRONOMICAL, { state: "present" }, {
      notes,
      tables: [{
        title: "太陽、月亮與上升",
        columns: ["項目", sidereal ? "星座度數（恆星黃道）" : "星座度數"],
        rows: SUMMARY_ROWS.map(([key, label]) => (key === "asc" ? [label, ascText] : bodyRow(key, label))),
      }],
      // 表後一行指向完整的表；畫面把〈〉裡的區段名換成連結。
      blocks: [angles.status.state === "present"
        ? "完整數值見〈天體位置〉與〈軸點〉。"
        : "完整數值見〈天體位置〉。"],
    });
  }

  // ═══ 回應 → sections ═══════════════════════════════════════
  /** 這是唯一一處把後端形狀翻成顯示投影的地方。 */
  function buildSections(response) {
    if (!isRecord(response)) throw new Error("缺少可用的 backend response。");
    // 先確認版本與狀態權威；之後各區只讀，不再替缺席的權威猜狀態。
    exportPipeline.assertRenderableResponse(response);
    const angles = anglesSection(response);
    // 頁面投影（帶 projection 鍵）沒有軌跡、請求選項、輸出契約與完整收據。這四區只由完整回應
    // 建出；頁面文件不建，而不是以缺鍵推定「未請求」。
    const verification = Object.hasOwn(response, "projection") ? [] : [
      requestedOptionsSection(response),
      traceSection(response),
      contractSection(response),
      receiptSection(response),
    ];
    return withReasonLabels([
      // 速覽在最前面：剛算完的人先看到最常被問到的三個星座，細節在後面各區。
      summarySection(response, angles),
      timeSection(response),
      // 敏感度緊接在時間轉換之後。它限定後面每一區
      // 結果的成立範圍，排在第二十幾區等於讀完全部結果才知道哪些會變。
      // 匯出與畫面讀同一份清單，所以匯出的區段順序同步改變。
      sensitivitySection(response),
      bodiesSection(response),
      nodesSection(response),
      lunarApsidesSection(response),
      parallaxMoonSection(response),
      fixedStarsSection(response),
      angles,
      extraAnglesSection(response),
      lunarEventsSection(response),
      horizonEventsSection(response),
      antisciaSection(response),
      declinationAspectsSection(response),
      housesSection(response),
      planetInHouseSection(response),
      sectSection(response),
      planetaryHoursSection(response),
      lunarMansionsSection(response),
      prenatalPointsSection(response),
      lotsSection(response),
      voidOfCourseSection(response),
      aspectsSection(response),
      dignitiesSection(response),
      ...dignityProfileSections(response),
      solarPhaseSection(response),
      dodecatemoriaSection(response),
      classicalClassificationsSection(response),
      ...verification,
    ]);
  }

  // ── 十二分部 ─────────────────────────────────────────────
  // 第一層是白話：它是什麼、這次用哪一種算法、哪些點沒列與為什麼；古書出處放在 blocks，
  // 畫面收進「出處」摺疊（SOURCE_FOLDED_SECTIONS），匯出照常逐條印出。
  const DODECATEMORIA_TITLE = "十二分部 Dodecatemoria";
  /** 區塊全是古書出處的區段：畫面把它們收進一個「出處」摺疊。 */
  const SOURCE_FOLDED_SECTIONS = new Set([
    "dodecatemoria", "lunar_mansions", "solar_phase", "prenatal_points", "classical_classifications",
  ]);
  const DODECATEMORIA_PROFILE_ZH = Object.freeze({
    twelvefold_from_sign_start_v1:
      "本次算法：星座內的度數乘以 12，從同一星座的起點往後數（Firmicus 的算法）。",
    thirteenfold_from_sign_start_v1:
      "本次算法：星座內的度數乘以 13，從同一星座的起點往後數，等於從這個點自己的位置再往後數 12 倍（Paulus 的算法）。",
  });
  const DODECATEMORIA_NOT_LISTED_ZH = Object.freeze({
    angles_not_computed: "這次沒有計算宮位，所以不列上升點。",
    lots_not_requested_or_not_computed: "命運點與精神點只在勾選「阿拉伯點」並算出時才列。",
  });
  // 只知道日期時沒有上升點，命運點與精神點根本算不出來；不是使用者沒勾「阿拉伯點」。
  const DODECATEMORIA_LOTS_NEED_TIME_NOTE = "命運點與精神點要有出生時間才算得出來（要先有上升點）；"
    + "這次只知道出生日期，所以不列。";
  const DODECATEMORIA_CATEGORY_ZH = Object.freeze({
    classical_planet: "行星", angle: "軸點", lot: "阿拉伯點",
  });
  const DODECATEMORIA_SOURCE_LINES = Object.freeze([
    ["Firmicus Maternus, Mathesis II.13",
      "出處：Firmicus《Mathesis》卷二第 13 章（Kroll–Skutsch 編號）：度數乘以 12，從星座起點往後數；書中的例子是太陽在牡羊 5°05′，得雙子第 1 度。",
      "original_language_read", "（拉丁文）"],
    ["Manilius, Astronomica II.693-748",
      "出處：Manilius《Astronomica》卷二 693–748 行：每個星座分成 12 段、每段 2°30′，第一段歸本座，其餘依序歸後面各座；只算到星座，結果與上一條相同。",
      "original_language_read", "（拉丁文）"],
    ["Paulus Alexandrinus, Introduction ch.22",
      "出處：Paulus《導論》（Eisagōgika）第 22 章：度數乘以 13，從星座起點往後數；書中的例子是牡羊 11°，得獅子 23°。據 Greenbaum 與 Jones 2017 年的論文，希臘原文未讀。",
      "secondary_only"],
    ["Olympiodorus, Commentary on Paulus ch.20",
      "出處：Olympiodorus 註解 Paulus 的第 20 章用同一算法算上升點（天蠍 20° 得巨蟹 20°）。據同一篇論文。",
      "secondary_only"],
    ["Olympiodorus, Commentary on Paulus ch.21",
      "出處：Olympiodorus 註解 Paulus 的第 21 章談阿拉伯點的十二分部；這一章只見到章名。",
      "bibliographic_only"],
    [null, "出處：完整書目與每條核到哪一層，見方法頁〈十二分部〉一節。"],
  ]);
  const DODECATEMORIA_SOURCES = sourceBlocks(DODECATEMORIA_SOURCE_LINES);

  const DODECATEMORIA_SAMPLED_NOTE = "標「這段時間內會換星座」的列，在取樣的時刻裡出現過不只一個十二分部星座，"
    + "括號裡列出取樣到的星座；沒有標的列，只表示取樣的時刻都落在同一個星座，不保證取樣點之間沒有換過。"
    + "度數與守護行星是代表性時刻的值。「點」一欄名稱後加「※」的，就是這些列。";

  /** 取樣到兩個以上十二分部星座的點：表格很寬時（手機），第一欄就看得到記號，不必橫捲到十二分部那一格。 */
  const DODECATEMORIA_SAMPLED_MARK = " ※";
  function dodecatemoriaSampledMany(sampled) {
    return isRecord(sampled) && Array.isArray(sampled.sampled_sign_indices)
      && sampled.sampled_sign_indices.filter((index) => Number.isInteger(index) && index >= 0 && index < 12).length >= 2;
  }

  /** 十二分部那一格：代表性時刻的位置；取樣到兩個以上星座時，接著列出取樣到的星座。 */
  // 後端逐點說取樣比較做到哪裡；有取樣時刻算不出這一點（partially_evaluated）時，照實說只比較了一部分。
  const DODECATEMORIA_PARTIAL_NOTE = "（部分取樣時刻算不出這一點，只比較了算得出的時刻）";
  function dodecatemoriaCell(sampled, position) {
    const indices = isRecord(sampled) && Array.isArray(sampled.sampled_sign_indices)
      ? sampled.sampled_sign_indices.filter((index) => Number.isInteger(index) && index >= 0 && index < 12)
      : [];
    const partial = isRecord(sampled) && sampled.status === "partially_evaluated" ? DODECATEMORIA_PARTIAL_NOTE : "";
    const text = signPosition(position);
    if (indices.length < 2) return `${text}${partial}`;
    return `${text}（這段時間內會換星座，取樣到：${zodiacOrder(indices).map((index) => SIGNS[index]).join("、")}）${partial}`;
  }

  function dodecatemoriaTimeNote(response) {
    const precision = response.birth_time_sensitivity.precision;
    if (precision === "date_only") {
      return "只知道出生日期時，這一區用當天的代表性時刻計算。十二分部把度數放大十二倍以上，"
        + "所以同一天裡早一點或晚一點出生，任何一列都可能換到另一個星座：月亮最快，一天就繞過大半圈；"
        + "太陽、水星、金星、火星一天走半度到兩度，十二分部就走 6° 到 26°，也常常換。這一區每一列都只能當參考。";
    }
    if (precision === "approximate_hour") {
      return "只知道約略時辰時，這一區用代表性時刻計算。十二分部把度數放大十二倍以上，"
        + "所以這一小時裡任何一列都可能換到另一個星座。最容易換的是上升點、命運點與精神點："
        + "它們的十二分部一小時內大約移動半圈；其次是月亮，約 7°。其他行星一小時移動很少，只在靠近星座交界時才會換。";
    }
    return null;
  }

  /**
   * 日夜盤邊界帶：阿拉伯點有日盤、夜盤兩套公式時，後端逐列說另一套公式的十二分部是否換了星座
   * （sign_differs_under_other_sect；不在邊界帶是 null）。
   */
  function dodecatemoriaSectBandNote(point) {
    const differs = point.sign_differs_under_other_sect;
    if (differs !== true && differs !== false) return null;
    const name = point.name || point.key;
    const head = `太陽貼近地平線（日夜盤的邊界帶），${name}有日盤、夜盤兩套公式；表中是本盤採用的那一套。`;
    return differs
      ? `${head}改用另一套公式，${name}的十二分部會落在${signName(point.comparison_sign)}。`
      : `${head}改用另一套公式，${name}的十二分部仍在同一個星座。`;
  }

  function dodecatemoriaSection(response) {
    const module = response.derived_methods.dodecatemoria;
    const points = isRecord(module) && Array.isArray(module.points) ? module.points : [];
    const status = moduleState(
      response, { option: "include_dodecatemoria", module: "dodecatemoria" }, module, points.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor(
        "dodecatemoria", DODECATEMORIA_TITLE, RING.METHOD,
        "本次未請求。十二分部是古典占星的細部技法：把一個點在星座裡的度數放大，對應到另一個星座；勾選後列出位置與該星座的守護行星。",
        status
      );
    }
    const scope = isRecord(module.scope) ? module.scope : {};
    const notListed = Array.isArray(scope.not_listed) ? scope.not_listed : [];
    const notes = [
      "十二分部（dodecatemoria）：把一個點在星座裡走了幾度放大，"
        + "再從同一個星座的起點往後數，每 30° 換下一個星座，數到的位置就是它的十二分部。"
        + "表的最後一欄是那個星座的守護行星。Firmicus 說，有人認為從十二分部可以找出整張命盤的實質，命盤裡隱藏的事也能由它揭露（《Mathesis》II.13）。",
      presentClosedVocabulary(module.profile, DODECATEMORIA_PROFILE_ZH, "算法"),
      ...classicalDisagreementNotes(response, "derived_methods.dodecatemoria"),
      ...notListed.map((code) => (code === "lots_not_requested_or_not_computed"
        && response.birth_time_sensitivity.precision === "date_only"
        ? DODECATEMORIA_LOTS_NEED_TIME_NOTE
        : presentClosedVocabulary(code, DODECATEMORIA_NOT_LISTED_ZH, "未列原因"))),
      "中天不列：讀過的古書沒有算中天的十二分部。只列位置與守護行星。不替你解盤，也不預測。",
    ];
    if (points.some((point) => point.category === "angle")) {
      notes.push("十二分部對出生時間很敏感：時間差 4 分鐘，上升點的十二分部常常就差 10° 以上。");
    }
    notes.push(...points.filter((point) => point.category === "lot")
      .map(dodecatemoriaSectBandNote).filter(Boolean));
    const timeNote = dodecatemoriaTimeNote(response);
    if (timeNote) notes.push(timeNote);
    // 出生時間不精確時，後端在取樣的每個時刻重算各點的十二分部（birth_time_sensitivity.
    // dodecatemoria_signs，以點鍵對應）；取樣到兩個以上星座的列就在十二分部那一格標出來。
    const sensitivity = isRecord(response.birth_time_sensitivity) ? response.birth_time_sensitivity : {};
    const sampledByKey = Object.fromEntries(
      (Array.isArray(sensitivity.dodecatemoria_signs) ? sensitivity.dodecatemoria_signs : [])
        .filter((item) => isRecord(item) && typeof item.key === "string")
        .map((item) => [item.key, item])
    );
    if (Object.keys(sampledByKey).length) notes.push(DODECATEMORIA_SAMPLED_NOTE);
    return makeSection("dodecatemoria", DODECATEMORIA_TITLE, RING.METHOD, status, {
      notes,
      tables: [{
        title: "各點的十二分部",
        columns: ["點", "類別", "原位置", "十二分部", "十二分部星座的守護行星"],
        rows: points.map((point) => [
          `${point.name || point.key}${dodecatemoriaSampledMany(sampledByKey[point.key]) ? DODECATEMORIA_SAMPLED_MARK : ""}`,
          presentClosedVocabulary(point.category, DODECATEMORIA_CATEGORY_ZH, "類別"),
          signPosition(point.point_sign_position),
          dodecatemoriaCell(sampledByKey[point.key], point.sign_position),
          rulerName(point.domicile_lord),
        ]),
      }],
      blocks: DODECATEMORIA_SOURCES.slice(),
    });
  }

  // ── 行星與宮的古典分類 ─────────────────────────────────────
  // 每一欄是一本書的分類或條件，照原文的用語；各書不同時並列。白話在第一層，出處收進「出處」摺疊。
  const CLASSICAL_TITLE = "行星與宮的古典分類";
  const CLASSICAL_PLACES_TITLE = "十二宮的名稱與分類";
  const NATURE_ZH = Object.freeze({
    beneficent: "吉星",
    maleficent: "凶星",
    both_powers: "吉凶兩種力量都有，隨同處的行星",
    beneficent_when_distant_maleficent_when_conjunct: "相隔而有相位時為吉，相合而靠近時為凶",
    follows_the_planet_nearest_it: "隨最近的行星而吉或凶",
  });
  const PLANET_GENDER_ZH = Object.freeze({ masculine: "陽性", feminine: "陰性", common: "陰陽兼有" });
  const SIGN_GENDER_ZH = Object.freeze({ masculine: "陽性", feminine: "陰性" });
  const SECT_MEMBERSHIP_ZH = Object.freeze({
    diurnal: "白天一組",
    nocturnal: "夜晚一組",
    diurnal_as_morning_star: "白天一組（此刻是晨星）",
    nocturnal_as_evening_star: "夜晚一組（此刻是昏星）",
    undetermined_same_longitude_as_the_sun: "未定（與太陽同一黃經）",
  });
  const JOY_SOURCE_ZH = Object.freeze({
    paulus_introduction_24: "Paulus 第 24 章（轉引）",
    firmicus_mathesis_ii_19: "Firmicus 卷二第 19 章",
  });
  const HAYZ_REASON_ZH = Object.freeze({
    mercury_has_no_rule_in_this_source: "書中沒有水星的規則",
    planet_not_covered_by_this_definition: "不在這個定義內",
    chart_sect_unavailable: DASH,
    planet_altitude_unavailable: DASH,
  });
  const TRIAD_ZH = Object.freeze({ angular: "始宮", succedent: "續宮", cadent: "果宮" });
  const FIRMICUS_GROUP_ZH = Object.freeze({
    joined_to_the_ascendant: "與上升相連",
    sluggish_and_cast_down: "遲滯、低落（與上升沒有關聯）",
  });
  const DOROTHEUS_RANK_ZH = Object.freeze({ good: "好", middling: "中等", bad: "壞" });
  // 出處經 sourceBlocks：有引文的一行附方法出處登錄 classical_classifications 那條引文的鍵（登錄以鍵列出處）與核到層級。
  const CLASSICAL_SOURCE_LINES = Object.freeze([
    ["ptolemy_tetrabiblos_i_5",
      "出處：Ptolemy《占星四書》卷一第 5、6、7、12 章：木星、金星、月亮為吉星，土星、火星為凶星，"
      + "太陽與水星兩種力量都有；行星與星座的陰陽；白天與夜晚兩組行星，水星是晨星時屬白天、是昏星時屬夜晚。",
      "translation_read", "（Robbins 英譯，Loeb 1940）"],
    ["valens_anthologies_i_1",
      "出處：Valens《占星選集》（Anthologiae）卷一第 1 章：土星、木星、太陽屬白天一組，火星、金星、月亮屬夜晚一組，"
      + "水星沒有寫；又說凶星在自己那一組、所在合宜時，反而帶來好處。",
      "translation_read", "（Riley 英譯，線上重排本）"],
    ["al_biruni_tafhim_382",
      "出處：al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）第 382、385、386 節：吉星與凶星（土星尤凶）、太陽與水星的條件、"
      + "行星的陰陽與日夜；第 496 節：halb 與 hayyiz 的定義。al-Qabīṣī 與 Bonatti 的定義相同。",
      "translation_read", "（Wright 1934 英譯，掃描文字）"],
    ["lilly_christian_astrology_p113",
      "出處：Lilly《Christian Astrology》（1647）第 113 頁：hayz 的定義。",
      "original_language_read", "（現代重排本的掃描文字）"],
    ["paulus_introduction_24",
      "出處：Paulus《導論》（Eisagōgika）第 24 章：七顆行星各自喜樂的宮。"
      + "Paulus 原文與譯本都未核；Olympiodorus、Rhetorius 的同一說法也只見轉引。",
      "secondary_only", "（Brennan 2013 年的文章）"],
    ["firmicus_mathesis_ii_15_20",
      "出處：Firmicus《Mathesis》卷二第 15–20 章：四個樞軸、與上升相連的四處、遲滯低落的四處，以及十二宮的名稱；"
      + "第 19 章說第 8 宮只有月亮喜樂、而且只在夜盤，並把第 5、6、9、11、12 宮稱為金星、火星、太陽、木星、土星的位置。",
      "original_language_read", "（拉丁文，Kroll–Skutsch 編號）"],
    ["valens_anthologies_ii",
      "出處：Valens《占星選集》（Anthologiae）卷二、卷四：十二宮逐一的名稱，例如第 2 宮「冥府之門」、"
      + "第 3 宮「女神月亮的位置」、第 8 宮「怠惰之處」、第 9 宮「神太陽的位置」。",
      "translation_read", "（Riley 英譯，線上重排本）"],
    ["ptolemy_tetrabiblos_iii_3_10",
      "出處：Ptolemy《占星四書》卷三第 3、10 章與 Robbins 的注 56：始宮、續宮與「自始宮下落」的宮，"
      + "以及十二宮的希臘名稱。",
      "translation_read", "（Robbins 英譯）"],
    ["dorotheus_carmen_i_5",
      "出處：Dorotheus《Carmen Astrologicum》卷一第 5 章：最好的七宮、中等三宮、壞的兩宮。Pingree 的英譯未核。",
      "secondary_only", "（網路上的二手整理）"],
    ["manilius_astronomica_ii",
      "出處：Manilius《Astronomica》卷二另有一套十二宮的名稱與守護神（例如金星在中天、土星在天底），"
      + "本站沒有採用。",
      "secondary_only", "（拉丁原文部分核過，各宮的對應依二手整理）"],
    [null, "出處：完整書目與每條核到哪一層，見方法頁〈行星與宮的古典分類〉一節。"],
  ]);
  const CLASSICAL_SOURCES = sourceBlocks(CLASSICAL_SOURCE_LINES);

  const yesNoDash = (value) => (value === true ? "是" : value === false ? "否" : DASH);

  // 只知日期時，後端在代表性計算時刻算古典分類，並在模組的 time_basis 寫明；這一句照它寫，不由精度推斷。
  const CLASSICAL_DATE_ONLY_BASIS = "representative_computational_anchor_not_birth_time";
  function classicalTimeNote(response, module) {
    const precision = response.birth_time_sensitivity.precision;
    if (module.time_basis === CLASSICAL_DATE_ONLY_BASIS) {
      return "只知道出生日期時沒有出生時刻：日盤或夜盤、在地平上或下，以及落在哪一宮都無法判定，這幾欄寫「—」；"
        + "吉凶、陰陽與日夜區照列，水星是晨星或昏星依當天的代表性時刻。";
    }
    if (precision === "approximate_hour") {
      return "只知道約略時辰時，日盤或夜盤、在地平上或下與落在哪一宮都依代表性時刻判定；這一小時內它們可能改變。";
    }
    return null;
  }

  function classicalClassificationsSection(response) {
    const module = response.derived_methods.classical_classifications;
    const planets = isRecord(module) && Array.isArray(module.planets) ? module.planets.filter(isRecord) : [];
    const places = isRecord(module) && Array.isArray(module.places) ? module.places.filter(isRecord) : [];
    const status = moduleState(
      response, { option: "include_classical_classifications", module: "classical_classifications" },
      module, planets.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor(
        "classical_classifications", CLASSICAL_TITLE, RING.METHOD,
        "本次未請求。勾選後列出古書怎麼分類七顆行星（吉星、凶星、白天或夜晚一組、喜樂宮、hayz）"
          + "與十二宮（名稱、始宮／續宮／果宮、好壞），每一條都寫明出自哪本書。",
        status
      );
    }
    const sect = isRecord(module.chart_sect) ? module.chart_sect : null;
    const notEvaluated = Array.isArray(module.not_evaluated) ? module.not_evaluated : [];
    const housesModule = response.derived_methods.planet_in_house;
    const notes = [
      "這一區照古書原文列出分類：哪本書把哪顆行星歸為吉星或凶星、屬於白天還是夜晚一組、在哪一宮「喜樂」，"
        + "以及這張盤合不合乎書中的條件。各書說法不同時並列，不替你挑。本站只列分類與條件，不加總、不打分。",
    ];
    if (sect && typeof sect.is_day === "boolean") {
      notes.push(`本盤是${sect.is_day ? "日盤（出生時太陽在地平線上）" : "夜盤（出生時太陽在地平線下）"}。`);
      if (sect.in_near_horizon_band === true) {
        notes.push("太陽貼近地平線（日夜盤的邊界帶）：日夜相關的各欄依本站的規則（太陽中心高於地平線為日盤）判定；"
          + "判法一換，這些欄可能一起改變。");
      }
    }
    notes.push(
      "「在地平上／下」看行星中心是否高於地平線（從地心算，不計大氣折射），與本站判日夜盤的規則相同；"
        + "古書只說「在地上」「在地下」，沒有說要看地平線還是看宮位。",
      "水星屬白天或夜晚一組，依 Ptolemy《占星四書》卷一第 7 章：在太陽之前升起（晨星）時屬白天，"
        + "在太陽之後落下（昏星）時屬夜晚；本站以黃經在太陽之西或之東判斷。al-Bīrūnī 說水星隨同處的行星或星座而定，那一種本站沒有算。",
      "喜樂宮（joys）：古書說每顆行星在某一宮特別「喜樂」。水星第 1 宮、月亮第 3 宮、金星第 5 宮、火星第 6 宮、"
        + "太陽第 9 宮、木星第 11 宮、土星第 12 宮這一組，本站只讀到轉引（Paulus《導論》第 24 章）；"
        + "Firmicus《Mathesis》卷二第 19 章另說第 8 宮只有月亮喜樂，而且只在夜盤。兩條都列。"
        + (isRecord(housesModule) && housesModule.execution_status === "computed"
          ? `本盤的宮依你選的宮位制（${houseSystemText(housesModule.house_system_code, housesModule.house_system_name)}）。`
          : ""),
      "Hayz 與 halb 是中世紀阿拉伯語占星書的用詞，說一顆行星的所在合不合乎它屬於白天或夜晚。"
        + "al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）第 496 節：白天一組的行星白天在地平上、夜裡在地平下，夜晚一組相反，叫 halb；"
        + "再加上陽性行星在陽性星座、陰性行星在陰性星座，叫 hayyiz（火星是陽性，但屬夜晚一組）。"
        + "Lilly《Christian Astrology》（1647）第 113 頁只有 hayz：陽性的白天行星白天在地平上、在陽性星座；"
        + "陰性的夜晚行星夜裡在地平下、在陰性星座。兩書對夜晚行星該在地平上或下說法相反，本站兩種都列。",
      "十二宮的名稱沿用希臘化時期的叫法；中文是本站的譯名，並列希臘文、拉丁文與英文。"
        + "第 1、4、7、10 宮是始宮（又稱角宮），各自的下一宮是續宮，再下一宮是果宮。"
        + "好壞有兩種分法：Firmicus《Mathesis》卷二第 15–17 章說第 2、6、8、12 宮與上升沒有關聯，"
        + "是「遲滯、低落」的位置，其餘八宮與上升相連；Dorotheus《Carmen Astrologicum》卷一第 5 章（轉引）分成好、中等、壞三等。"
        + "各宮的含義不在這裡列，見方法頁。",
      ...classicalDisagreementNotes(response, "derived_methods.classical_classifications"),
    );
    const near = planets.filter((row) => row.altitude_in_near_horizon_band === true).map((row) => row.name || row.key);
    if (near.length) {
      notes.push(`${near.join("、")}貼近地平線（離地平線不到 50′）：出生時刻差幾分鐘，或改用計入大氣折射的判法，`
        + "在地平上或下就可能不同。");
    }
    if (notEvaluated.includes("houses_not_computed") && response.birth_time_sensitivity.precision !== "date_only") {
      notes.push("這次沒有計算宮位，所以喜樂宮的「本盤所在的宮」與十二宮表的行星一欄寫「—」。");
    }
    const timeNote = classicalTimeNote(response, module);
    if (timeNote) notes.push(timeNote);

    const houseCell = (house) => (Number.isInteger(house) ? `第 ${house} 宮` : DASH);
    const hayzCell = (verdict, field) => {
      if (!isRecord(verdict)) return DASH;
      if (verdict.reason_code) return presentClosedVocabulary(verdict.reason_code, HAYZ_REASON_ZH, "原因");
      return yesNoDash(verdict[field]);
    };
    const residents = new Map();
    if (isRecord(housesModule) && housesModule.execution_status === "computed" && Array.isArray(housesModule.placements)) {
      housesModule.placements.filter(isRecord).forEach((place) => {
        if (!residents.has(place.house)) residents.set(place.house, []);
        residents.get(place.house).push(place.name || place.key);
      });
    }
    const placesDrawn = residents.size > 0;
    return makeSection("classical_classifications", CLASSICAL_TITLE, RING.METHOD, status, {
      notes,
      tables: [
        {
          title: "七顆行星：吉凶與日夜區",
          columns: ["行星", "吉凶（Ptolemy）", "吉凶（al-Bīrūnī）", "陰陽", "日夜區", "與本盤日夜"],
          rows: planets.map((row) => {
            const nature = isRecord(row.nature) ? row.nature : {};
            return [
              row.name || row.key,
              presentClosedVocabulary(nature.ptolemy_tetrabiblos_i_5, NATURE_ZH, "分類"),
              presentClosedVocabulary(nature.al_biruni_tafhim_382, NATURE_ZH, "分類"),
              presentClosedVocabulary(row.gender, PLANET_GENDER_ZH, "陰陽"),
              presentClosedVocabulary(row.sect_membership, SECT_MEMBERSHIP_ZH, "日夜區"),
              row.of_chart_sect === true ? "同一組" : row.of_chart_sect === false ? "不同組" : DASH,
            ];
          }),
        },
        {
          title: "喜樂宮",
          columns: ["行星", "喜樂的宮", "出處", "本盤所在的宮", "是否在喜樂宮"],
          rows: planets.flatMap((row) => (Array.isArray(row.joys) ? row.joys.filter(isRecord) : []).map((joy) => [
            row.name || row.key,
            `第 ${joy.place} 宮${joy.condition === "night_chart_only" ? "（只在夜盤）" : ""}`,
            presentClosedVocabulary(joy.source, JOY_SOURCE_ZH, "出處"),
            houseCell(row.house),
            yesNoDash(joy.in_joy),
          ])),
        },
        {
          title: "Hayz 與 halb",
          columns: ["行星", "在地平上／下", "所在星座", "星座陰陽",
            "halb（al-Bīrūnī）", "hayyiz（al-Bīrūnī）", "hayz（Lilly）"],
          rows: planets.map((row) => {
            const hayz = isRecord(row.hayz) ? row.hayz : {};
            return [
              row.name || row.key,
              row.above_horizon === true ? "地平上" : row.above_horizon === false ? "地平下" : DASH,
              signName(row.sign),
              presentClosedVocabulary(row.sign_gender, SIGN_GENDER_ZH, "陰陽"),
              hayzCell(hayz.al_biruni_tafhim_496, "halb"),
              hayzCell(hayz.al_biruni_tafhim_496, "hayyiz"),
              hayzCell(hayz.lilly_christian_astrology_p113, "hayz"),
            ];
          }),
        },
        {
          title: CLASSICAL_PLACES_TITLE,
          columns: ["宮", "名稱", "原文名稱", "始宮／續宮／果宮", "Firmicus 的分法", "Dorotheus 的分法（轉引）",
            "本盤在這一宮的行星"],
          rows: places.map((place) => [
            `第 ${place.place} 宮`,
            place.name_zh || DASH,
            `${place.name_greek}（希臘文）、${place.name_latin}（拉丁文）、${place.name_english}`,
            presentClosedVocabulary(place.triad, TRIAD_ZH, "分類"),
            presentClosedVocabulary(place.firmicus_ii_15_17, FIRMICUS_GROUP_ZH, "分類"),
            presentClosedVocabulary(place.dorotheus_i_5, DOROTHEUS_RANK_ZH, "分類"),
            placesDrawn ? (residents.get(place.place) || []).join("、") || "（無）" : DASH,
          ]),
        },
      ],
      blocks: CLASSICAL_SOURCES.slice(),
    });
  }

  /** 非「已計算」區段的原因代碼帶上中文說法，匯出（CSV 的值欄）讀這一份，不另查表。 */
  function withReasonLabels(sections) {
    return sections.map((section) => (
      section.status && section.status.reason_code
        ? { ...section, status: { ...section.status, reason_label: moduleReason(section.status.reason_code) } }
        : section
    ));
  }

  // ── 圖表連動的點鍵 ─────────────────────────────────────
  //
  // 星盤圖、位置表、速覽、落宮、逐度相位與相位方格以後端的點鍵（sun、true_node、mean_lilith、asc…）
  // 互相對應。鍵只放在 view tree（畫面用）；匯出讀 canonical sections，鍵不會進任何匯出檔。
  // 每一張表的鍵都從回應讀，並逐列核對列名：列數或任一列名對不上，整張表不連動（null），不猜。
  const POINT_KEY = /^[a-z][a-z_]*$/;
  const pointKey = (value) => (typeof value === "string" && POINT_KEY.test(value) ? value : null);

  /**
   * 一份回應清單 → 每列一個鍵；列名必須是 name（沒有 name 時是 key），與 bodyRows 等表同一條規則。
   * 鍵只讀回應的 key：沒有 key 的列不連動，不由中文名稱反查。
   */
  function listPoints(list, rows) {
    if (!Array.isArray(list) || list.length !== rows.length) return null;
    const keys = [];
    for (let index = 0; index < list.length; index += 1) {
      const item = list[index];
      if (!isRecord(item) || rows[index][0] !== (item.name || item.key)) return null;
      const key = pointKey(item.key);
      keys.push(key ? [key] : null);
    }
    return { rows: keys };
  }

  /** 固定列名的表（軸點、速覽）：[鍵, 列名] 的同一份常數同時產生列名與鍵。 */
  function fixedPoints(entries, rows) {
    if (entries.length !== rows.length || entries.some(([, label], index) => rows[index][0] !== label)) return null;
    return { rows: entries.map(([key]) => (pointKey(key) ? [key] : null)) };
  }

  function aspectPairPoints(aspects, rows) {
    const pairs = isRecord(aspects) && Array.isArray(aspects.pairs) ? aspects.pairs : null;
    if (!pairs || pairs.length !== rows.length) return null;
    const keys = [];
    for (let index = 0; index < pairs.length; index += 1) {
      const pair = pairs[index];
      if (!isRecord(pair)) return null;
      const name = `${pair.body_a_name || pair.body_a || DASH} — ${pair.body_b_name || pair.body_b || DASH}`;
      if (rows[index][0] !== name) return null;
      const a = pointKey(pair.body_a);
      const b = pointKey(pair.body_b);
      keys.push(a && b ? [a, b] : null);
    }
    return { rows: keys };
  }

  /** 相位方格：列＝參與者 2..n，欄＝參與者 1..n−1（第一欄是列名，沒有鍵）。 */
  function aspectGridPoints(aspects, table) {
    const participants = isRecord(aspects) && Array.isArray(aspects.participants)
      ? aspects.participants.filter((item) => isRecord(item) && item.key) : [];
    const names = participants.map((item) => item.name || item.key);
    const keys = participants.map((item) => pointKey(item.key));
    if (participants.length < 2 || table.rows.length !== participants.length - 1
      || table.columns.length !== participants.length) return null;
    if (table.columns.slice(1).some((column, index) => column !== names[index])) return null;
    if (table.rows.some((row, index) => row[0] !== names[index + 1])) return null;
    return {
      rows: keys.slice(1).map((key) => (key ? [key] : null)),
      columns: [null, ...keys.slice(0, -1)],
    };
  }

  /**
   * 一張表的點鍵：{ rows: (string[]|null)[], columns?: (string|null)[] }；這張表不連動時回 null。
   * 連動的八張表：天體、月交點、月球拱點、軸點、速覽、行星落宮、逐度相位、相位方格。
   */
  function tablePoints(sectionId, table, sourceResponse) {
    if (!isRecord(sourceResponse) || !isRecord(table) || !Array.isArray(table.rows)
      || table.rows.some((row) => !Array.isArray(row))) return null;
    const astro = isRecord(sourceResponse.astronomical_data) ? sourceResponse.astronomical_data : {};
    const derived = isRecord(sourceResponse.derived_methods) ? sourceResponse.derived_methods : {};
    switch (sectionId) {
      case "bodies":
        return listPoints(astro.bodies, table.rows);
      case "nodes":
        return listPoints(astro.nodes, table.rows);
      case "lunar_apsides":
        return listPoints(isRecord(astro.lunar_apsides) ? astro.lunar_apsides.points : null, table.rows);
      case "angles":
        return fixedPoints(Object.entries(Labels.VOCABULARIES.angle_label), table.rows);
      case "summary":
        return fixedPoints(SUMMARY_ROWS, table.rows);
      case "planet_in_house":
        if (table.title === POINT_PLACEMENT_TITLE) {
          const points = isRecord(derived.planet_in_house) && isRecord(derived.planet_in_house.point_placements)
            ? derived.planet_in_house.point_placements.placements : null;
          return listPoints(points, table.rows, null);
        }
        return listPoints(isRecord(derived.planet_in_house) ? derived.planet_in_house.placements : null,
          table.rows);
      case "aspects":
        return table.variant === "aspect_grid"
          ? aspectGridPoints(derived.aspects, table)
          : aspectPairPoints(derived.aspects, table.rows);
      default:
        return null;
    }
  }

  // 十二宮表的宮名連到方法頁宮義對照表的那一列（宮義本身不進個人的盤）。連結只給畫面；
  // 匯出讀 canonical sections，不帶連結。
  const HOUSE_MEANING_HREF = "/zh-TW/methods#house-meaning-";
  const HOUSE_NAME_COLUMN = "名稱";

  /**
   * 一張表要連結的格：{ column, rows: (string|null)[] }；這張表沒有連結時回 null。
   * 列以回應的 places 逐列核對（宮號與宮名都要對上），對不上的列不連，不由中文名稱反查宮號。
   */
  function tableLinks(sectionId, table, sourceResponse) {
    if (sectionId !== "classical_classifications" || !isRecord(table) || table.title !== CLASSICAL_PLACES_TITLE
      || !Array.isArray(table.rows) || !Array.isArray(table.columns) || !isRecord(sourceResponse)) return null;
    const derived = isRecord(sourceResponse.derived_methods) ? sourceResponse.derived_methods : {};
    const module = derived.classical_classifications;
    const places = isRecord(module) && Array.isArray(module.places) ? module.places.filter(isRecord) : [];
    const column = table.columns.indexOf(HOUSE_NAME_COLUMN);
    if (column < 1 || places.length !== table.rows.length) return null;
    const rows = places.map((place, index) => {
      const row = table.rows[index];
      const number = place.place;
      const ok = Array.isArray(row) && Number.isInteger(number) && number >= 1 && number <= 12
        && typeof place.name_zh === "string" && place.name_zh !== ""
        && row[0] === `第 ${number} 宮` && row[column] === place.name_zh;
      return ok ? `${HOUSE_MEANING_HREF}${number}` : null;
    });
    return rows.some(Boolean) ? { column, rows } : null;
  }

  /**
   * canonical document -> 可渲染的節點樹。
   *
   * 刻意回傳純資料而不是 DOM：瀏覽器端只負責把節點變成元素（一律用 textContent），
   * 因此渲染路徑本身沒有字串拼接，也就沒有 HTML 注入面；
   * 而「sections 改了，畫面就會跟著改」這件事可以在 Node 裡直接斷言。
   */
  // ── 「說明與原典」摺疊 ────────────────────────────────────
  // 這幾區在表格前有大段說明（原典怎麼說、說法不一、讀法與天文附註），手機上要捲兩屏才看到第一列。
  // 畫面把以下列開頭的段落收進一個預設收起的「說明與原典」摺疊，放在第一段白話之後；一個字都不改，
  // 列印時展開（beforeprint 展開結果裡的每個 details），匯出讀 canonical sections，照常逐段印出。
  // 第一段白話、本次分法、這張盤的狀況（時刻不精確、貼近地平線…）與固定句不收，留在表格前。
  const EXPLAIN_FOLDED_PREFIXES = Object.freeze({
    solar_phase: Object.freeze([
      "原典怎麼說：", "判定用黃道上的經度差", "al-Bīrūnī 另有一條", "Lilly 說焦傷只發生",
      "月亮落在日輪內", "水星離太陽最遠", "古典文獻說法不一：",
    ]),
    classical_classifications: Object.freeze([
      "「在地平上／下」看", "水星屬白天或夜晚一組", "喜樂宮（joys）", "Hayz 與 halb", "十二宮的名稱沿用",
      "古典文獻說法不一：",
    ]),
    prenatal_points: Object.freeze([
      "度數怎麼取：", "同一章接著用", "另一種挑法（不是預設）", "手抄本的另一種讀法",
      "「出生前最近一次日食／月食」", "日食的度數是", "月食有兩種算法", "算進來的理由",
      "古典文獻說法不一：",
    ]),
    aspects: Object.freeze([
      "「入／出」「同度」「完成時刻」三欄", "古典文獻說法不一：", "「相位方格」", "不合意（aversion）",
    ]),
  });
  /** 這一段在畫面上收進「說明與原典」摺疊嗎（只看區段與段落開頭；第一段永遠不收）。 */
  function explainFolded(sectionId, note) {
    const prefixes = EXPLAIN_FOLDED_PREFIXES[sectionId];
    return Boolean(prefixes) && typeof note === "string" && prefixes.some((prefix) => note.startsWith(prefix));
  }

  // ═══ sections → view tree（畫面）════════════════════════════
  function buildViewTree(exportDocument) {
    if (!isRecord(exportDocument) || !Array.isArray(exportDocument.sections)) {
      throw new Error("缺少可用的 canonical export document。");
    }
    const dossier = exportDocument.calculation_dossier || {};
    const warnings = Array.isArray(dossier.warnings) ? dossier.warnings : [];
    return {
      header: {
        birth_time_summary: birthTimeSummary(exportDocument.source_response),
        warnings: warnings.filter(
          (warning) => warning.code !== "provisional_method_result"
        ).map((warning) => ({
          code: warning.code || "UNSPECIFIED_WARNING",
          message: warning.message || "",
        })),
        stale: false,
        stale_notice: "",
        actions: { copy_enabled: true, download_enabled: true },
      },
      sections: exportDocument.sections.map((section) => ({
        type: "section",
        id: section.id,
        title: section.title,
        layer_label: section.layer_label,
        ring: ringKeyFor(section.layer_label),
        status: section.status,
        // 摘要圖在最前面：它的第一行是這一區的結論，渲染端永遠放在摺疊之外。
        children: [].concat(
          (section.figures || []).map((figure) => ({ type: "figure", figure })),
          section.notes.map((note) => ({ type: explainFolded(section.id, note) ? "explain" : "note", text: note })),
          section.tables.map((table) => {
            const points = tablePoints(section.id, table, exportDocument.source_response);
            const links = tableLinks(section.id, table, exportDocument.source_response);
            return {
              type: "table",
              title: table.title,
              columns: table.columns,
              rows: table.rows,
              ...(table.variant ? { variant: table.variant } : {}),
              // 圖表連動的點鍵（只給畫面）；這張表不連動時沒有這個鍵。
              ...(points ? { points } : {}),
              // 格內連結（只給畫面）：十二宮表的宮名連到方法頁宮義對照表。
              ...(links ? { links } : {}),
            };
          }),
          // 出處收進畫面上的「出處」摺疊；匯出讀 canonical sections，照常逐條印出。
          section.blocks.map((block) => ({
            type: SOURCE_FOLDED_SECTIONS.has(section.id) ? "source" : "block",
            text: block,
          }))
        ),
      })),
    };
  }

  /**
   * 表單改動後，畫面上的結果不再對應目前的輸入。
   * 回傳一棵標為過期的新樹：sections 不重建（同一個參考），複製與下載關閉，
   * 說明文字只在這裡寫一次。原樹不就地改動。
   */
  const STALE_NOTICE = "表單已改動，下方結果對應的是先前送出的輸入；複製與下載已停用。"
    + "請重新計算，或把欄位改回原值。";
  function markStale(tree) {
    if (!isRecord(tree) || !isRecord(tree.header) || !Array.isArray(tree.sections)) {
      throw new Error("缺少可用的 view tree。");
    }
    return {
      ...tree,
      header: {
        ...tree.header,
        stale: true,
        stale_notice: STALE_NOTICE,
        actions: { copy_enabled: false, download_enabled: false },
      },
    };
  }

  /**
   * 一頁摘要的位置表：天體、交點、拱點、軸點四區（已計算者）逐列，每一格照畫面上那張表同名欄的
   * 原字，不重新格式化；「宮」以列名對到行星落宮表，對不到與軸點一律「—」，軸點表沒有「行進」欄。
   * 任一區找不到要的欄名就整張回 null：紙上改印一句說明，不猜。
   */
  const PRINT_BRIEF_COLUMNS = Object.freeze(["點", "星座度數", "宮", "行進"]);
  const PRINT_BRIEF_SECTION_IDS = Object.freeze(["bodies", "nodes", "lunar_apsides", "angles"]);
  function printBriefRows(tree) {
    if (!isRecord(tree) || !Array.isArray(tree.sections)) return null;
    const presentTable = (id) => {
      const section = tree.sections.find((item) => item.id === id);
      if (!section || !section.status || section.status.state !== "present") return undefined;
      return section.children.find((child) => child.type === "table") || null;
    };
    const houses = new Map();
    const houseTable = presentTable("planet_in_house");
    if (houseTable === null) return null;
    if (houseTable) {
      // 行星落宮表之外，整宮制還有月交點與 Lilith 的落宮表；兩張都以列名對上。
      const section = tree.sections.find((item) => item.id === "planet_in_house");
      for (const table of section.children.filter((child) => child.type === "table")) {
        const at = table.columns.indexOf("宮");
        if (at < 1) return null;
        table.rows.forEach((row) => houses.set(row[0], row[at]));
      }
    }
    const rows = [];
    for (const id of PRINT_BRIEF_SECTION_IDS) {
      const table = presentTable(id);
      if (table === undefined) continue;
      if (table === null) return null;
      const sign = table.columns.indexOf("星座度數");
      const motion = table.columns.indexOf("行進");
      if (sign < 1 || (id !== "angles" && motion < 1)) return null;
      table.rows.forEach((row) => rows.push([
        row[0],
        row[sign],
        id !== "angles" && houses.has(row[0]) ? houses.get(row[0]) : DASH,
        motion < 1 ? DASH : row[motion],
      ]));
    }
    return rows.length ? { columns: PRINT_BRIEF_COLUMNS, rows } : null;
  }

  function ringKeyFor(layerLabel) {
    return RING_KEY_BY_LAYER.get(String(layerLabel || "")) || RING.VERIFICATION.key;
  }

  return Object.freeze({
    MODULE_COVERAGE,
    TRANSITION_RESOLUTION_LIMIT_SECONDS,
    MODULE_REASON_ZH,
    DASH,
    dms,
    cyclicFixed,
    signPosition,
    longitudeText,
    receiptStatus,
    moduleState,
    buildSections,
    buildViewTree,
    birthTimeSummary,
    changedPathsText,
    EXPLAIN_FOLDED_PREFIXES,
    markStale,
    printBriefRows,
    TIME_SCALE_ZH,
    SOURCE_LINES: Object.freeze({
      dodecatemoria: DODECATEMORIA_SOURCE_LINES,
      lunar_mansions: LUNAR_MANSION_SOURCE_LINES,
      solar_phase: SOLAR_PHASE_SOURCE_LINES,
      classical_classifications: CLASSICAL_SOURCE_LINES,
    }),
  });
});
