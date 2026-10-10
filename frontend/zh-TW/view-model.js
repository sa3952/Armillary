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

  /** 後端在尊貴模組回英文星座鍵；其餘模組回黃經。統一成同一套中文名。 */
  const SIGN_BY_KEY = Object.freeze({
    aries: "牡羊", taurus: "金牛", gemini: "雙子", cancer: "巨蟹",
    leo: "獅子", virgo: "處女", libra: "天秤", scorpio: "天蠍",
    sagittarius: "射手", capricorn: "摩羯", aquarius: "水瓶", pisces: "雙魚",
  });
  /** 依黃經序（0＝牡羊）的同一組名字。 */
  const SIGNS = Object.freeze(Object.values(SIGN_BY_KEY));
  const PLANET_BY_KEY = Object.freeze({
    sun: "太陽", moon: "月亮", mercury: "水星", venus: "金星",
    mars: "火星", jupiter: "木星", saturn: "土星",
  });

  function signName(key) {
    if (!key) return DASH;
    return presentClosedVocabulary(String(key).toLowerCase(), SIGN_BY_KEY, "星座");
  }

  function rulerName(key) {
    if (!key) return DASH;
    const normalized = String(key).toLowerCase();
    if (Object.prototype.hasOwnProperty.call(PLANET_BY_KEY, normalized)) return PLANET_BY_KEY[normalized];
    return presentClosedVocabulary(normalized, SIGN_BY_KEY, "守護");
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

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
  /**
   * @param {object} response 後端回應
   * @param {{option?: string, module?: string}} keys 這個 section 對應的選項鍵與模組鍵
   * @param {*} container 模組容器（物件或陣列）
   * @param {boolean} hasContent 容器是否真的有可渲染內容
   */
  function moduleState(response, keys, container, hasContent) {
    const own = isRecord(container) && "requested" in container
      && typeof container.requested === "boolean"
      ? receiptStatus(container)
      : null;
    const fromOption = optionState(response, keys.option);
    const fromModules = policyModuleState(response, keys.module);
    // 容器自己的收據不是權威（OUTPUT_CONTRACT）：權威裡沒有這一區，就沒有可核對的狀態。
    if (!fromOption && !fromModules) {
      throw exportPipeline.incompleteResponse(
        `${keys.option || keys.module || "未具名模組"} 沒有可核對的狀態`
      );
    }
    let status;
    if (own) {
      status = own;
    } else if (fromOption) {
      status = receiptStatus(fromOption);
    } else if (fromModules === "not_requested") {
      status = { state: "not_requested" };
    } else if (fromModules === "not_applicable") {
      status = { state: "refused", reason_code: "" };
    } else {
      // modules 的值是閉集（assertRenderableResponse 已檢查），剩下的只有 computed。
      status = { state: "present" };
    }
    // 模組自己的收據說 present，但單一產生器說不是：以後者為準（heliocentric 下
    // sect／lots 物件沒有收據欄位，只有 option_states 帶 module_not_applicable）。
    if (status.state === "present" && fromOption) {
      const optionStatus = receiptStatus(fromOption);
      if (optionStatus.state !== "present") {
        status = optionStatus;
      }
    }
    if (status.state === "present" && fromModules === "not_applicable") {
      status = { state: "refused", reason_code: (own && own.reason_code) || "" };
    }
    if (status.state === "present" && fromModules === "not_requested") {
      status = { state: "not_requested" };
    }
    if (status.state === "refused" && !status.reason_code) {
      const fallback = (fromOption && fromOption.reason_code)
        || (isRecord(container) && "reason_code" in container && container.reason_code) || "";
      status = { state: "refused", reason_code: fallback };
    }
    if (status.state === "present" && !hasContent) {
      return {
        state: "executed_unavailable",
        reason_code: (own && own.reason_code) || (fromOption && fromOption.reason_code) || "",
      };
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
    return { ...absentSection(id, title, ring, note), status: status || { state: "not_requested" } };
  }

  /** 未請求的模組仍然要出現在畫面上，帶著「未請求」而不是被靜默省略。 */
  function absentSection(id, title, ring, note) {
    return {
      id,
      title,
      layer_label: ring.layer,
      status: { state: "not_requested" },
      notes: [note],
      tables: [],
      blocks: [],
    };
  }

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
    const time = (response.astronomical_data || {}).time || {};
    const atmosphere = (response.astronomical_data || {}).atmosphere || {};
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
    return {
      id: "time",
      title: "時間轉換",
      layer_label: RING.ASTRONOMICAL.layer,
      status: { state: "present" },
      notes,
      tables: [{
        title: "時間",
        columns: ["項目", "數值"],
        rows: [
          [anchored ? "代表性錨點（非出生時刻）" : "本地時間", time.input_local_time],
          ["時區", time.timezone_label],
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
      blocks: [],
    };
  }

  function bodiesSection(response) {
    const bodies = (response.astronomical_data || {}).bodies || [];
    return {
      id: "bodies",
      title: "天體位置",
      layer_label: RING.ASTRONOMICAL.layer,
      status: { state: bodies.length ? "present" : "executed_unavailable" },
      notes: [
        "黃道、赤道、地平三套座標一次輸出，不必換工具重填生辰。",
        "星座與宮內度數由後端黃經以 30° 分段換寫，非另一次計算；完整精度在『運算結果＋驗算資料』的 JSON 匯出中。",
        bodies.some((body) => body.speed_position_derivative_status
          === "known_internal_disagreement_for_sun_moon")
          ? "站心速度為 Swiss FLG_SPEED 解析值；太陽／月亮部分欄位已知不等於同次位置的有限差分導數，請勿把它當作已驗證的導數精度。"
          : null,
        // 後端對只有日期的請求不輸出地平座標（reason_code date_only_no_birth_time）。
        (response.birth_time_sensitivity || {}).precision === "date_only"
          ? "只有出生日期：沒有出生時刻就沒有對應的地平位置，方位角與高度不列出。"
          : null,
      ].filter(Boolean),
      tables: [{
        title: "本命天體",
        columns: BODY_COLUMNS,
        rows: bodyRows(bodies),
      }],
      blocks: [],
    };
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
    const rows = [
      ["上升 ASC", "asc"],
      ["中天 MC", "mc"],
      ["下降 DSC", "desc"],
      ["天底 IC", "ic"],
    ].map(([label, key]) => [label, ...positionCells(positions[key])]);
    return {
      id: "angles",
      title: "軸點",
      layer_label: RING.ASTRONOMICAL.layer,
      status,
      notes: ["軸點由地方恆星時與觀測地緯度決定，與宮位制的選擇無關。"],
      tables: [{
        title: "四軸",
        columns: ["軸點", LONGITUDE_COLUMN, "星座度數"],
        rows,
      }],
      blocks: [],
    };
  }

  /**
   * 依本次回應實際的黃道印公式。鏡軸固定在回歸黃道的至點軸與分點軸，
   * 恆星黃道下後端用 180°−λ−2×ayanamsa（core/antiscia.py）；只印回歸黃道的公式，
   * 使用者拿畫面上的恆星黃經照算會差兩倍 ayanamsa。
   */
  function antisciaFormulaNotes(response) {
    const ayanamsa = ((response.astronomical_data || {}).time || {}).ayanamsa;
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
    const antiscia = (response.derived_geometry || {}).antiscia;
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
    return {
      id: "antiscia",
      title: "反照點 Antiscia",
      layer_label: RING.GEOMETRY.layer,
      status: antisciaStatus,
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
      blocks: [],
    };
  }

  /**
   * 宮位制的名稱以代碼取 labels.js 的中文名，與表單選單同一個出處；後端給的名稱
   * 不同於中文名時附在括號裡（例：整宮（Whole Sign））。
   */
  function houseSystemText(givenCode, name) {
    // 頁面投影只帶名稱；代碼由後端名稱對照表找回，兩種投影說同一句話。
    const code = givenCode || Labels.houseSystemCodeForName(name);
    if (!code) return name || DASH;
    const zh = Labels.label("house_system", code);
    return name && name !== zh ? `${zh}（${name}）` : zh;
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
    const houses = (response.derived_methods || {}).house_division;
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
    return {
      id: "houses",
      title: "宮位分割",
      layer_label: RING.METHOD.layer,
      status: housesStatus,
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
      blocks: [],
    };
  }

  // 每一格讀後端 aspects.py 的閉集（APPLYING_STATES、PERFECTION_STATUSES）
  // 與 pair record 的真欄位；前端不自己推入離、不自己命名相位。
  function signedNum(value, digits) {
    if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
    return `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
  }

  /** 軸點組合沒有整宮 doctrine——「不適用」不是「無」。 */
  function wholeSignCell(ws) {
    if ("applicable" in ws && ws.applicable === false) return "不適用";
    return ws.in_aspect === true ? (ws.configuration_zh || DASH) : "無";
  }

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
        && Object.prototype.hasOwnProperty.call(PARTILE_FALSE_REASON_ZH, target.partile_reason_code)
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
      && Object.prototype.hasOwnProperty.call(NOT_APPLYING_PHASE_ZH, target.applying)) {
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
      ? `其餘 ${count} 組的星座不成相位，不列出。`
      : `其餘 ${count} 組沒有相位，不列出。`;
    return `${rule}${angleRule}。${rest}`;
  }

  function aspectsSection(response) {
    const aspects = (response.derived_methods || {}).aspects;
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
    return {
      id: "aspects",
      title: "相位",
      layer_label: RING.METHOD.layer,
      // orb 未選定不是「相位模組被拒絕」；相位算出來了，少的是一層判定。
      status: orbReceipt.requested === true ? receiptStatus(orbReceipt) : aspectsStatus,
      notes,
      tables,
      blocks: [],
    };
  }

  function dignitiesSection(response) {
    const dignities = (response.derived_methods || {}).essential_dignities;
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

    return {
      id: "dignities",
      title: "本質尊貴與分配法",
      layer_label: RING.METHOD.layer,
      status,
      notes,
      tables,
      blocks: ["評估基礎：回歸黃道、地心位置、當日黃道框架。"],
    };
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
    // 月交點每張盤都算（OUTPUT_CONTRACT：不屬於任何選項的容器）；缺席不是「未請求」。
    const nodes = response.astronomical_data.nodes;
    if (!Array.isArray(nodes)) throw exportPipeline.incompleteResponse("缺少月交點");
    if (!nodes.length) {
      return absentSectionFor("nodes", "月交點", RING.ASTRONOMICAL, "",
        { state: "executed_unavailable", reason_code: "" });
    }
    return {
      id: "nodes", title: "月交點",
      layer_label: RING.ASTRONOMICAL.layer,
      status: { state: "present" },
      notes: ["密切交點與平均交點分列，不替使用者擇一。"],
      tables: [{ title: "交點", columns: BODY_COLUMNS, rows: bodyRows(nodes) }],
      blocks: [],
    };
  }

  function fixedStarsSection(response) {
    const stars = (response.astronomical_data || {}).fixed_stars;
    const list = Array.isArray(stars) ? stars : [];
    const status = moduleState(
      response, { option: "include_fixed_stars", module: "fixed_stars" }, stars, list.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("fixed_stars", "恆星", RING.ASTRONOMICAL,
        "本次未請求恆星。目錄內的恆星全部列為研究用途，勾選才計算。", status);
    }
    const policy = (response.astronomical_data || {}).fixed_star_policy || {};
    return {
      id: "fixed_stars", title: "恆星",
      layer_label: RING.ASTRONOMICAL.layer,
      status,
      notes: [
        "本項只提供位置與星等，不自動判定固定星合相。",
        `目錄收錄 ${policy.catalog_size || DASH} 顆，本次輸出 ${list.length} 顆。`,
      ],
      tables: [{
        title: "恆星位置",
        // note 與 features 頁都說有星等，表就要有星等欄。
        columns: ["恆星", "目錄名", LONGITUDE_COLUMN, "星座度數", "赤緯 δ（度）", "星等"],
        rows: list.map((star) => [
          // 中文名只取後端 config.py 的 name，前端不另存星名表。
          star.name || star.key, star.catalog_name || DASH,
          ...positionCells(star.sign_position), dms(star.declination),
          num(star.magnitude, 2),
        ]),
      }],
      blocks: [],
    };
  }

  function lunarApsidesSection(response) {
    const module = (response.astronomical_data || {}).lunar_apsides;
    const status = moduleState(
      response, { option: "include_lilith_priapus", module: "lunar_apsides" }, module,
      isRecord(module) && Array.isArray(module.points) && module.points.length > 0
    );
    if (status.state !== "present") {
      return absentSectionFor("lunar_apsides", "Lilith 與 Priapus", RING.ASTRONOMICAL,
        "本次未請求。", status);
    }
    return {
      id: "lunar_apsides", title: "Lilith 與 Priapus",
      layer_label: RING.ASTRONOMICAL.layer,
      status,
      notes: ["三個點都是月球軌道的幾何點，不是物理天體；本項顯示位置，不自動加入相位判定。"],
      tables: [{ title: "月球拱點", columns: BODY_COLUMNS, rows: bodyRows(module.points) }],
      blocks: [],
    };
  }

  function parallaxMoonSection(response) {
    const module = (response.astronomical_data || {}).parallax_moon;
    const status = moduleState(
      response, { module: "parallax_moon" }, module,
      isRecord(module) && isRecord(module.topocentric_effective)
    );
    if (status.state !== "present") {
      return absentSectionFor("parallax_moon", "站心月亮", RING.ASTRONOMICAL,
        "本次未請求。月亮位置口徑維持跟隨整體計算中心。", status);
    }
    return {
      id: "parallax_moon", title: "站心月亮",
      layer_label: RING.ASTRONOMICAL.layer,
      status,
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
      blocks: [],
    };
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
    const module = (response.astronomical_data || {}).extra_angles;
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
    return {
      id: "extra_angles", title: "額外角點",
      layer_label: RING.ASTRONOMICAL.layer,
      status,
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
      blocks: [],
    };
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
    angle_frame_incompatible_with_body_longitudes: "軸點與天體黃經不在同一參考框架，軸點不參與",
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
    // 星曆涵蓋與搜尋
    ephemeris_segment_out_of_coverage: "日期超出這個天體星曆檔的涵蓋範圍",
    ephemeris_segment_file_missing: "伺服器缺少所需的星曆檔",
    full_ephemeris_unavailable_for_search_window: "搜尋會超出完整星曆檔的涵蓋範圍，未產生結果",
    swiss_ephemeris_error_in_search: "星曆程式在搜尋中回報錯誤，未產生結果",
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
  function presentClosedVocabulary(value, vocabulary, role) {
    if (typeof value === "string" && Object.prototype.hasOwnProperty.call(vocabulary, value)) {
      return vocabulary[value];
    }
    return /^[a-z][a-z0-9_.]*$/.test(String(value || ""))
      ? `未識別的${role}（${value}）`
      : `未識別的${role}`;
  }

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
    civil_day: "當地民用日",
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
      rows.push(["產前朔望", "lunar_phases", views.map((view) => instantCell(view.prenatal_syzygy))]);
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
    const module = (response.astronomical_data || {}).lunar_events;
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
    return {
      id: "lunar_events", title: "朔望與日月食",
      layer_label: RING.ASTRONOMICAL.layer,
      status: { state: "present" },
      notes: (module.contract
        ? [presentClosedVocabulary(module.contract, LUNAR_CONTRACT_ZH, "契約")]
        : []).concat(
        rows.length
          ? ["「產前朔望」只列天文事件，不是產前食，也不當作任何技法的輸入。"]
          : [],
        eclipseRows.length
          ? ["日月食以全球搜尋取得，未評估出生地是否看得見；列出不代表與此盤有占星上的關聯。"]
          : [],
        borderlineNotes,
        samplesTable && samplesTable.rows.length
          ? [samplingNote(module, samples, "三個代表性取樣")].concat(samplesDiffer
            ? []
            : ["三個代表性取樣的朔望與日月食結果全部相同，因此不另列表。"])
          : []
      ),
      tables,
      blocks: [],
    };
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

  /** 閉集狀態：有對應印中文；沒有對應印未識別標記，缺對應是可見的缺陷而不是資料。 */
  function presentHorizonState(value, vocabulary, role) {
    if (typeof value === "string" && Object.prototype.hasOwnProperty.call(vocabulary, value)) {
      return vocabulary[value];
    }
    return /^[a-z][a-z0-9_]*$/.test(String(value || ""))
      ? `未識別的${role}（${value}）`
      : `未識別的${role}`;
  }

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
    if (!isRecord(entry)) return presentHorizonState(undefined, HORIZON_EVENT_STATUS_ZH, "事件狀態");
    const instant = entry[side];
    if (isRecord(instant) && instant.utc_time) {
      return table ? table.cell(instant.utc_time, instant.time_scale) : instant.utc_time;
    }
    const search = isRecord(entry.search) ? entry.search[side] : null;
    return presentHorizonState(
      isRecord(search) ? search.status : undefined, HORIZON_SIDE_STATUS_ZH, "搜尋狀態"
    );
  }

  function horizonEventsSection(response) {
    const module = (response.astronomical_data || {}).horizon_events;
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
    return {
      id: "horizon_events", title: "升降與中天",
      layer_label: RING.ASTRONOMICAL.layer,
      status,
      notes: horizonContractNotes(module.contract).concat(samplingNotes),
      tables: [{
        title: timed.title,
        columns: ["天體", "可見性", "事件", "狀態", "前一次", "下一次"],
        rows: bodies.flatMap((body) => {
          const events = isRecord(body.events) ? body.events : {};
          const visibility = presentHorizonState(body.visibility, HORIZON_VISIBILITY_ZH, "可見性");
          return HORIZON_EVENTS.map(([key, label]) => {
            const entry = events[key];
            return [
              body.name || body.key,
              visibility,
              label,
              presentHorizonState(
                isRecord(entry) ? entry.status : undefined, HORIZON_EVENT_STATUS_ZH, "事件狀態"
              ),
              horizonSideCell(entry, "previous", timed),
              horizonSideCell(entry, "next", timed),
            ];
          });
        }),
      }].concat(samplesTable && samplesTable.rows.length ? [samplesTable] : []),
      blocks: [],
    };
  }

  function planetInHouseSection(response) {
    const module = (response.derived_methods || {}).planet_in_house;
    const bodyByKey = new Map(
      ((response.astronomical_data || {}).bodies || [])
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
    return {
      id: "planet_in_house", title: "行星落宮",
      layer_label: RING.METHOD.layer,
      status,
      notes: [
        `宮位制：${houseSystemText(module.house_system_code, module.house_system_name)}。`,
        "距最近宮頭的黃經差一律列出（沿黃道量，不計黃緯），讓你自己判斷這個落宮對出生時刻有多敏感。",
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
      }],
      blocks: [],
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
    const module = (response.derived_methods || {}).sect;
    const status = moduleState(
      response, { module: "sect" }, module, isRecord(module) && typeof module.is_day === "boolean"
    );
    if (status.state !== "present") {
      return absentSectionFor("sect", "日夜盤", RING.METHOD, "本次未計算日夜盤。", status);
    }
    const bandArcmin = typeof module.near_horizon_band_half_width_degrees === "number"
      ? num(module.near_horizon_band_half_width_degrees * 60, 0) : DASH;
    return {
      id: "sect", title: "日夜盤",
      layer_label: RING.METHOD.layer,
      status,
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
      blocks: [],
    };
  }

  function lotsSection(response) {
    const module = (response.derived_methods || {}).lots;
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
      return {
        id: "lots", title: "阿拉伯點",
        layer_label: RING.METHOD.layer,
        status,
        notes,
        tables: [{
          title: "點位",
          columns: ["點", header("day", "若為日盤"), header("night", "若為夜盤")],
          rows: LOTS.map(([lot, label]) => [label, cell("day", lot), cell("night", lot)]),
        }],
        blocks: [],
      };
    }
    const rows = LOTS.map(([lot, label]) => [
      label, ...positionCells(lotPosition(module, lot)), houseCell(placement[lot]),
    ]);
    return {
      id: "lots", title: "阿拉伯點",
      layer_label: RING.METHOD.layer,
      status,
      notes,
      tables: [{ title: "點位", columns: ["點", LONGITUDE_COLUMN, "星座度數", "宮位"], rows }],
      blocks: [],
    };
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
    const module = (response.derived_methods || {}).void_of_course;
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
    return {
      id: "void_of_course", title: "月空亡",
      layer_label: RING.METHOD.layer,
      status,
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
          ["邊界判定", Object.prototype.hasOwnProperty.call(VOC_VERDICT_ZH, module.verdict)
            ? VOC_VERDICT_ZH[module.verdict] : DASH],
          ["離開本星座尚需（小時）", num(module.time_to_sign_exit_hours, 4)],
          ["下一個完成的相位", next.body || DASH],
          ["該相位角度", num(next.aspect_angle, 2)],
          ["尚需（日）", num(next.time_days, 6)],
        ],
      }],
      blocks: [],
    };
  }

  function declinationAspectsSection(response) {
    const module = (response.derived_methods || {}).declination_aspects;
    const status = moduleState(
      response, { option: "include_declination_aspects", module: "declination_aspects" }, module,
      isRecord(module) && Array.isArray(module.aspects)
    );
    if (status.state !== "present") {
      return absentSectionFor("declination_aspects", "赤緯平行與反平行", RING.GEOMETRY,
        "本次未請求。這是 17 世紀 Placidus 的界定，非古典傳統。", status);
    }
    const pairs = module.aspects;
    return {
      id: "declination_aspects", title: "赤緯平行與反平行",
      layer_label: RING.GEOMETRY.layer,
      status,
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
      blocks: [],
    };
  }

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

      return {
        id: sectionId, title: TECHNIQUE_LABELS[technique],
        layer_label: RING.METHOD.layer,
        status,
        notes, tables, blocks: [],
      };
    });
  }

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
    const receipt = (response.calculation_dossier || {}).trace_receipt || {};
    return {
      id: "trace", title: "逐步計算軌跡",
      layer_label: RING.VERIFICATION.layer,
      status: { state: "present" },
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
      blocks: [],
    };
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
    const requested = response.requested_options || {};
    const keys = Object.keys(requested);
    if (!keys.length) {
      return absentSection("requested_options", "本次請求的選項", RING.VERIFICATION,
        "回應沒有回報請求的選項。");
    }
    return {
      id: "requested_options", title: "本次請求的選項",
      layer_label: RING.VERIFICATION.layer,
      status: { state: "present" },
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
      blocks: [],
    };
  }

  /** 輸出契約：三層的定義與其 provisional 狀態。 */
  function contractSection(response) {
    const contract = response.output_contract || {};
    const layers = contract.layers || {};
    return {
      id: "contract", title: "輸出契約",
      layer_label: RING.VERIFICATION.layer,
      status: { state: "present" },
      notes: [
        `契約狀態：${presentClosedVocabulary(contract.status, CONTRACT_STATUS_ZH, "契約狀態")}。`,
        `相容性政策：${presentClosedVocabulary(contract.compatibility, CONTRACT_COMPATIBILITY_ZH, "相容性政策")}。`,
      ],
      tables: [{
        title: "三層的定義（後端原文）",
        columns: ["層", "定義"],
        rows: Object.entries(layers).map(([key, text_]) => [key, text_]),
      }],
      blocks: [],
    };
  }

  function sensitivitySection(response) {
    const sensitivity = response.birth_time_sensitivity;
    // 精確時刻不取樣；其餘一律看模組自己的 status。兩個欄位缺一個都不能猜成「未取樣」或「被拒」。
    if (typeof sensitivity.precision !== "string"
      || (sensitivity.precision !== "exact" && typeof sensitivity.status !== "string")) {
      throw exportPipeline.incompleteResponse("出生時刻敏感度缺少 precision 或 status");
    }
    const section = (status, notes, tables, figures = []) => ({
      id: "sensitivity",
      title: "出生時刻敏感度",
      layer_label: RING.VERIFICATION.layer,
      status,
      figures,
      notes,
      tables,
      blocks: [],
    });
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
    const sensitivityVocabulary = {
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
    };
    const SKIP_REASON_ZH = {
      local_time_nonexistent: "時鐘沒有經過這一刻",
      house_system_unavailable_at_sample: "這一刻所選宮位制算不出宮頭",
    };
    const ANGLE_ZH = { asc: "上升", mc: "中天", desc: "下降", ic: "天底" };
    const LOT_ZH = { fortune: "命運點", spirit: "精神點" };
    const LEDGER_PATH_ZH = { "astronomical_data.bodies": "天體位置" };
    const presentSensitivityText = (value) =>
      presentClosedVocabulary(value, sensitivityVocabulary, "語意");
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
    // 後端標出的評估限制：取樣點在這種情形下界不住結果，受影響的路徑只算部分比較。
    const EVALUATION_LIMIT_ZH = {
      polar_ascendant_can_reverse_between_samples:
        "出生地在極圈內，上升點可能在兩個取樣時刻之間翻轉半個黃道再回來，"
        + "取樣點與細分時刻都可能漏掉其間的星座與宮位",
    };
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
    // 後端以回應路徑命名每一個比較過的分類（例：astronomical_data.bodies[sun].motion_sign）。
    // 認得的歸成一類寫中文；認不得的退回「所屬模組：欄位」，不會消失也不會被猜成別的。
    const classificationLabel = (path) => {
      const text = String(path);
      const owner = Object.keys(ledger || {})
        .filter((prefix) => text.startsWith(`${prefix}.`) || text.startsWith(`${prefix}[`))
        .sort((a, b) => b.length - a.length)[0];
      if (!owner) return text;
      return `${LEDGER_PATH_ZH[owner] || modulePathLabel(owner, bodyNames)}：${text.slice(owner.length + 1)}`;
    };
    const ledger = ((response.calculation_dossier || {}).birth_time || {}).sensitivity_coverage;
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
          LEDGER_PATH_ZH[path] || modulePathLabel(path, bodyNames),
          samplingStatus(state),
        ]),
      });
    }
    const figure = samplingFigure(sensitivity, ledger, {
      bodyNames, classificationLabel, ledgerLabel: (path) => LEDGER_PATH_ZH[path] || modulePathLabel(path, bodyNames),
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
  });
  const PARTIAL_GROUP_ZH = Object.freeze({
    "derived_methods.void_of_course":
      "月空亡：只比較了「是否月空亡」一項；出宮時刻、下一個完成的相位與它的時刻都沒有重算",
  });
  const FIGURE_ANGLE_ORDER = ["asc", "mc", "desc", "ic"];
  const FIGURE_ANGLE_ZH = Object.freeze({ asc: "上升", mc: "中天", desc: "下降", ic: "天底" });
  const FIGURE_LOT_ZH = Object.freeze({ fortune: "命運點", spirit: "精神點" });

  // 後端分類路徑 → 畫面上的一類。成員（天體、角點、宮序）合併成一句，例如「上升、下降的星座」。
  const CLASSIFICATION_KINDS = [
    [/^astronomical_data\.angles\.sign_positions\.(\w+)$/, "angles"],
    [/^derived_methods\.house_division\.cusp_sign_positions\[(\d+)\]$/, "house_cusps"],
    [/^astronomical_data\.(?:bodies|nodes)\[([^\]:]+)(?::[^\]]*)?\]\.sign_position$/, "body_signs"],
    [/^astronomical_data\.(?:bodies|nodes)\[([^\]:]+)(?::[^\]]*)?\]\.motion_sign$/, "motion"],
    [/^derived_methods\.planet_in_house\.placements\[([^\]]+)\]\.house$/, "planet_in_house"],
    [/^derived_methods\.planet_in_house\.placements\[([^\]]+)\]\.on_cusp$/, "on_cusp"],
    [/^derived_methods\.lots\.sign_positions\.(\w+)$/, "lot_signs"],
    [/^derived_methods\.lots\.house_placement\.(\w+)$/, "lot_houses"],
    [/^derived_methods\.lots\.by_sect\./, "lot_comparison"],
    [/^derived_methods\.lots\.(?:formula_basis|sect_applied|sect_status|sect_in_near_horizon_band|sect_named_boundary_disagreement)$/, "lot_formula"],
    [/^derived_methods\.sect\./, "sect"],
    [/^derived_methods\.void_of_course\.is_void_of_course$/, "void_of_course"],
  ];
  const SINGLE_CLASSIFICATION_ZH = Object.freeze({
    lot_comparison: "阿拉伯點另一套公式的比較值",
    lot_formula: "阿拉伯點採用的公式",
    sect: "日夜區分",
    void_of_course: "是否月空亡",
  });
  function classificationKind(path) {
    for (const [pattern, kind] of CLASSIFICATION_KINDS) {
      const match = pattern.exec(String(path));
      if (match) return { kind, member: match[1] };
    }
    return null;
  }

  /** 把一組改變的分類路徑寫成一行：同類合併（「上升、中天的星座；第 1、7 宮宮頭的星座」）。 */
  function changedPathsText(paths, labels) {
    const groups = new Map();
    const other = [];
    paths.forEach((path) => {
      const found = classificationKind(path);
      if (!found) {
        other.push(labels.classificationLabel(path));
        return;
      }
      if (!groups.has(found.kind)) groups.set(found.kind, []);
      if (found.member !== undefined && !groups.get(found.kind).includes(found.member)) {
        groups.get(found.kind).push(found.member);
      }
    });
    const names = (members, vocabulary) => members.map((member) => vocabulary[member] || member);
    const parts = [];
    if (groups.has("angles")) {
      const members = groups.get("angles").slice().sort(
        (a, b) => FIGURE_ANGLE_ORDER.indexOf(a) - FIGURE_ANGLE_ORDER.indexOf(b)
      );
      parts.push(`${names(members, FIGURE_ANGLE_ZH).join("、")}的星座`);
    }
    if (groups.has("house_cusps")) {
      const houses = groups.get("house_cusps").map((index) => Number(index) + 1).sort((a, b) => a - b);
      parts.push(`第 ${houses.join("、")} 宮宮頭的星座`);
    }
    const perMember = [
      ["body_signs", labels.bodyNames, "的星座"],
      ["motion", labels.bodyNames, "的行進方向"],
      ["planet_in_house", labels.bodyNames, "的落宮"],
      ["on_cusp", labels.bodyNames, "是否在宮頭上"],
      ["lot_signs", FIGURE_LOT_ZH, "的星座"],
      ["lot_houses", FIGURE_LOT_ZH, "的落宮"],
    ];
    perMember.forEach(([kind, vocabulary, suffix]) => {
      if (groups.has(kind)) parts.push(`${names(groups.get(kind), vocabulary).join("、")}${suffix}`);
    });
    Object.keys(SINGLE_CLASSIFICATION_ZH).forEach((kind) => {
      if (groups.has(kind)) parts.push(SINGLE_CLASSIFICATION_ZH[kind]);
    });
    return parts.concat([...new Set(other)]).join("；");
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
          return {
            lower: localKey(item.lower_bound_local),
            upper: localKey(item.upper_bound_local),
            paths: Array.isArray(item.changed_paths) ? item.changed_paths : [],
            resolution: Number.isFinite(seconds) && seconds <= TRANSITION_RESOLUTION_LIMIT_SECONDS
              ? `解析度 ≤${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒`
              : `解析度 ${Number.isFinite(seconds) ? seconds : DASH} 秒`,
          };
        })
        .map((band) => ({ ...band, range: `${clockLabel(band.lower, day)}–${clockLabel(band.upper, day)}`,
          text: changedPathsText(band.paths, labels) || DASH }));
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
          resolution: "兩個相鄰取樣點之間，未再細分",
          text: changedPathsText(paths, labels),
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
      // 細分改變時刻時算過的中間時刻也算數：只在那些時刻出現的值同樣計入。
      const coverage = isRecord(sensitivity.probe_coverage) ? sensitivity.probe_coverage : {};
      const refined = Array.isArray(coverage.refinement_offsets_seconds) ? coverage.refinement_offsets_seconds.length : 0;
      lead = `這${word}個取樣點分類不全相同：`
        + (refined ? `連同細分時加算的 ${refined} 個時刻，` : "")
        + `有 ${differing.length} 項判定在取樣點之間改變。`;
    }

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
      groups.push({
        tone: "differs",
        title: "已比較，取樣點之間有改變",
        note: sensitivity.precision === "date_only"
          ? "日期模式只在取樣點比較，沒有細分改變的時刻。"
          : (bands.length
            ? "每一段是改變發生的時間範圍，不是單一時刻；一段之內至少改變一次，不一定只有一次。"
            : ""),
        bands: bands.map(({ range, resolution, text }) => ({ range, resolution, text })),
        items: unbanded.length ? [changedPathsText(unbanded, labels)] : [],
      });
    }
    if (isRecord(ledger)) {
      const pathsIn = (state) => Object.keys(ledger).filter((path) => ledger[path] === state);
      const same = pathsIn("same_at_all_samples");
      if (same.length) {
        groups.push({
          tone: "same",
          title: `已比較，這${word}個取樣點分類相同`,
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
          title: "沒有比較，只算了代表性時刻",
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

  function receiptSection(response) {
    const dossier = response.calculation_dossier || {};
    const engine = dossier.engine || {};
    const privacy = dossier.privacy || {};
    const receipt = dossier.input_receipt || {};
    const place = dossier.location_resolution || {};
    const policy = dossier.calculation_policy || {};
    const traceReceipt = dossier.trace_receipt || {};
    const time = (response.astronomical_data || {}).time || {};
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
    return {
      id: "receipt",
      title: "計算收據",
      layer_label: RING.VERIFICATION.layer,
      status: { state: "present" },
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
            ["時區", time.timezone_label],
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
      blocks: [],
    };
  }

  /**
   * 回應 -> sections。這是唯一一處把後端形狀翻成顯示投影的地方。
   */
  function buildSections(response) {
    if (!isRecord(response)) throw new Error("缺少可用的 backend response。");
    // 先確認版本與狀態權威；之後各區只讀，不再替缺席的權威猜狀態。
    exportPipeline.assertRenderableResponse(response);
    return withReasonLabels([
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
      anglesSection(response),
      extraAnglesSection(response),
      lunarEventsSection(response),
      horizonEventsSection(response),
      antisciaSection(response),
      declinationAspectsSection(response),
      housesSection(response),
      planetInHouseSection(response),
      sectSection(response),
      lotsSection(response),
      voidOfCourseSection(response),
      aspectsSection(response),
      dignitiesSection(response),
      ...dignityProfileSections(response),
      requestedOptionsSection(response),
      traceSection(response),
      contractSection(response),
      receiptSection(response),
    ]);
  }

  /** 非「已計算」區段的原因代碼帶上中文說法，匯出（CSV 的值欄）讀這一份，不另查表。 */
  function withReasonLabels(sections) {
    return sections.map((section) => (
      section.status && section.status.reason_code
        ? { ...section, status: { ...section.status, reason_label: moduleReason(section.status.reason_code) } }
        : section
    ));
  }

  /**
   * canonical document -> 可渲染的節點樹。
   *
   * 刻意回傳純資料而不是 DOM：瀏覽器端只負責把節點變成元素（一律用 textContent），
   * 因此渲染路徑本身沒有字串拼接，也就沒有 HTML 注入面；
   * 而「sections 改了，畫面就會跟著改」這件事可以在 Node 裡直接斷言。
   */
  function buildViewTree(exportDocument) {
    if (!isRecord(exportDocument) || !Array.isArray(exportDocument.sections)) {
      throw new Error("缺少可用的 canonical export document。");
    }
    const dossier = exportDocument.calculation_dossier || {};
    const warnings = Array.isArray(dossier.warnings) ? dossier.warnings : [];
    return {
      header: {
        sampling_callout: samplingCallout(exportDocument.sections),
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
          section.notes.map((note) => ({ type: "note", text: note })),
          section.tables.map((table) => ({
            type: "table",
            title: table.title,
            columns: table.columns,
            rows: table.rows,
          })),
          section.blocks.map((block) => ({ type: "block", text: block }))
        ),
      })),
    };
  }

  /**
   * 結果頁頂端重述取樣摘要的第一行，連到敏感度區。
   * 文字直接取自同一張摘要圖，不另寫一份結論；沒有摘要圖（精確時刻、取樣被拒）時為 null。
   */
  function samplingCallout(sections) {
    const section = sections.find((item) => item.id === "sensitivity");
    const figure = section && Array.isArray(section.figures) ? section.figures[0] : null;
    if (!figure) return null;
    return {
      label: section.title,
      lead: figure.lead,
      link_text: "看取樣摘要",
      target_id: "section-sensitivity",
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
    buildSections,
    buildViewTree,
    markStale,
    TIME_SCALE_ZH,
  });
});
