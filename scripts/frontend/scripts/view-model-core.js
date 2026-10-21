// view-model 的共用部分：環、模組覆蓋宣告、格式、收據攤平、模組狀態與閉集標籤。
"use strict";
// 時間尺度與計算模式的標籤只有一份，在 exporters.js；閉集代碼的中文標籤在 labels.js；「全部並列」
// 應有哪幾套表，看計算頁的選項目錄 options-catalogue.js。頁面在 view-model.js 之前載入三者；Node 以 require 取得。
const commonJs = typeof module === "object" && module.exports;
const exportPipeline = commonJs ? require("./exporters.js") : globalThis.ChartExport;
const Labels = commonJs ? require("./labels.js") : globalThis.ArmillaryLabels;
const Catalogue = commonJs ? require("./options-catalogue.js") : globalThis.OptionsCatalogue;

// layer 是區段的 layer_label（畫面與匯出都印）；畫面依它找回環的 key。
const RING = Object.freeze({
  ASTRONOMICAL: { key: "ring-1", layer: "RING I 天文事實" },
  GEOMETRY: { key: "ring-2", layer: "RING II 幾何推導" },
  METHOD: { key: "ring-3", layer: "RING III 方法判斷" },
  VERIFICATION: { key: "ring-v", layer: "VERIFICATION 驗證" },
});
const RING_KEY_BY_LAYER = new Map(Object.values(RING).map((ring) => [ring.layer, ring.key]));

/**
 * 回應側覆蓋宣告：後端能回的每一個模組都要有交代。與 `frontend/tests/fixtures/chart-approximate-hour.json`
 * （全部模組開啟的真實回應）做 exact-set 比對：後端新增模組而這裡沒交代，測試就紅。
 * `section` 是承接的 section；`not_rendered` 必須寫出理由，「忘了做」與「刻意不顯示」在這裡分開。
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
  "derived_methods.motion_states": { zh: "行速、停滯與東出西入", section: "motion_states" },
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
/** 古典七政的鍵與後端名稱，依太陽、月亮、水金火木土；尊貴、外來與行速各表應有的列就是這七顆。 */
const SEVEN_KEYS = Object.freeze(Object.keys(PLANET_BY_KEY));
const SEVEN_NAMES = Object.freeze(Object.values(PLANET_BY_KEY));

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

/* 必要欄位：缺了就拒絕，不補。
   區段讀「後端一定會發」的欄位一律經過 need()：鍵不在、或值不是說好的型別，就以 response_incomplete
   拒絕整份回應，訊息寫出路徑；不補成「—」、空表或少一列（`|| {}`、`|| []` 會把殘缺的回應畫成已計算）。
   可以合法為 null 的欄位寫成 "string?" 等：鍵仍必須在，值是 null 或該型別。
   frontend/tests/fail_closed_sections.test.cjs 對每一區逐一刪鍵、刪列，守住這條規則。 */
const NEED_KINDS = Object.freeze({
  any: () => true,
  record: isRecord,
  array: Array.isArray,
  records: (value) => Array.isArray(value) && value.every(isRecord),
  string: (value) => typeof value === "string" && value !== "",
  number: (value) => typeof value === "number" && Number.isFinite(value),
  boolean: (value) => typeof value === "boolean",
});
function need(record, path, key, kind = "any") {
  const nullable = kind.endsWith("?");
  const check = NEED_KINDS[nullable ? kind.slice(0, -1) : kind];
  if (!check) throw new Error(`need() 沒有這個型別：${kind}`);
  if (!isRecord(record) || !Object.hasOwn(record, key)) {
    throw exportPipeline.incompleteResponse(`缺少 ${path}.${key}`);
  }
  const value = record[key];
  if (!(nullable && value === null) && !check(value)) {
    throw exportPipeline.incompleteResponse(`${path}.${key} 不是預期的型別（${kind}）`);
  }
  return value;
}
/**
 * 同一個紀錄底下的多個必要欄位：`const r = needAt(module, "lots")`，之後 `r("key", "string")`、
 * `r.in("sub")` 走進子紀錄、`r.rows("list")` 取逐列紀錄（每列也是 needAt）、`r.position("key")`
 * 取星座位置；`r.record` 是紀錄本身。路徑自動接上，訊息指得出是哪一格。
 */
function needAt(record, path) {
  if (!isRecord(record)) throw exportPipeline.incompleteResponse(`${path} 不是紀錄`);
  const read = (key, kind) => need(record, path, key, kind);
  read.record = record;
  read.path = path;
  read.in = (key, nullable = false) => {
    const value = need(record, path, key, nullable ? "record?" : "record");
    return value === null ? null : needAt(value, `${path}.${key}`);
  };
  read.rows = (key) => needRows(need(record, path, key), `${path}.${key}`);
  read.position = (key, nullable = false) => needPosition(need(record, path, key), `${path}.${key}`, nullable);
  return read;
}
/** 一張逐列表：值必須是紀錄陣列，每列包成 needAt。 */
function needRows(value, path) {
  if (!Array.isArray(value) || !value.every(isRecord)) {
    throw exportPipeline.incompleteResponse(`${path} 不是逐列紀錄`);
  }
  return value.map((row, index) => needAt(row, `${path}[${index}]`));
}
/** 星座位置 [星座序, 星座內度數字串, 黃經字串]；不是這個形狀就拒絕（可為 null 時另說）。 */
function needPosition(value, path, nullable = false) {
  if (nullable && value === null) return null;
  if (!isSignPosition(value)) throw exportPipeline.incompleteResponse(`${path} 不是星座位置`);
  return value;
}

/** 一串名稱（或鍵）必須恰好是應有的那一組、依應有的順序；應有的集合不得取自同一份回應。 */
function needExactly(actual, expected, path) {
  if (actual.length !== expected.length || actual.some((item, index) => item !== expected[index])) {
    throw exportPipeline.incompleteResponse(
      `${path} 應為 ${expected.join("、")}，回應是 ${actual.join("、") || "空的"}`
    );
  }
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

/* 結構化收據欄位的攤平：物件直接放進儲存格會變成 [object Object]、不報錯只是讀不到（其中隱私
   未涵蓋層是 L1 宣稱），所以具名攤平，不用泛用的 JSON.stringify。 */

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
  const premises = [
    contract("refraction", "string") === "enabled" ? "標準大氣折射" : null,
    contract("disc_position", "string") === "upper_limb" ? "天體上緣" : null,
  ].filter(Boolean);
  const notes = [
    "上升與下降以觀測地的視地平為準"
    + (premises.length ? `，包含${premises.join("與")}` : "")
    + "；表中逐一列出上升、下降、上中天與下中天的前一次與下一次。",
  ];
  if (contract("upper_transit_is_hour_angle_zero_not_max_altitude", "boolean")) {
    notes.push("上中天是時角為 0 的時刻，不是高度最大的時刻。");
  }
  const horizon = contract.in("search_horizon_days");
  notes.push(
    `每一側各自搜尋：升降 ${num(horizon("rise", "number"), 0)} 日、中天 ${num(horizon("upper_transit", "number"), 0)} 日。`
    + "某一側沒有時刻時，印的是那一側的搜尋結果；「搜尋區間內未找到」與「未搜尋」是不同的兩件事。"
  );
  return notes;
}

// 輸出精度是百分之一角秒；一度 = 3600 秒 × 100。
const TICKS_PER_DEGREE = 360000;
const TICKS_PER_MINUTE = 6000;

/** 度轉度分秒。保留正負號，供赤緯與黃緯使用。 */
function dms(value) {
  if (typeof value !== "number" || !Number.isFinite(value)) return DASH;
  // 先量化到輸出精度再切度／分／秒：先切分、最後才對秒 toFixed(2)，59.996″ 會印成 60.00″ 而分不進位
  // （`29°59′60.00″`），而這種黃經是可達的。
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

function positionCells(position) {
  return [longitudeText(position), signPosition(position)];
}

/**
 * 後端收據 → section 狀態：四個布林組合的唯一映射處。requested=true 但 applicable=false 是
 * refused（產品明確拒絕並附理由），不是 not_requested（使用者沒勾）。
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
  // 拒絕或沒算出時理由是收據的一部分：鍵必須在（值可以是 null），缺了不改用別處的理由。
  if (!flag("applicable")) {
    return { state: "refused", reason_code: need(receipt, "模組收據", "reason_code", "string?") || "" };
  }
  // available=false 不論 executed 與否都不是 present：option_states 對「要求了但
  // 沒算出來」回的是 executed=false, available=false（例如年份尾端的朔望）。
  if (!flag("available")) {
    return {
      state: "executed_unavailable",
      reason_code: need(receipt, "模組收據", "reason_code", "string?") || "",
    };
  }
  return { state: "present" };
}

/* 模組狀態的單一產生器：
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

/**
 * 一個模組一區的共同開頭：id、標題與環只寫一次。狀態不是 present 時 `absent` 是要回的缺席區；
 * present 時以 `make(body)` 建區。
 */
function moduleSection(response, { id, title, ring, keys, container, note }) {
  const status = moduleState(response, keys, container, true);
  return {
    status,
    absent: status.state === "present" ? null : absentSectionFor(id, title, ring, note, status),
    make: (body) => makeSection(id, title, ring, status, body),
  };
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
// J2000 框架或關閉章動時，下列模組各回一個 <框架>_<模組>_basis_not_authorized（app.core.frame_compatibility）。
const FRAME_REFUSAL_STEMS = ["antiscia", "aspects", "declination_aspects", "dignity", "lots",
  "void_of_course", "dodecatemoria", "lunar_mansion", "solar_phase", "motion_states", "classical_classification"];
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
  // 行星日與行星時（app.core.planetary_hours）
  no_sunrise_sunset_cycle_around_instant: "出生地這段時間沒有一天一次的日出日落（極晝、極夜或前後幾天），無法定出行星日",
  // 月宿（app.core.lunar_mansions）
  sidereal_lunar_mansion_basis_not_authorized: "月宿從回歸黃道的牡羊 0°（春分點）起算，恆星黃道下不適用",
  // 焦傷與光束下（app.core.solar_phase）
  profile_has_no_cazimi_band: "所選的分法沒有日輪內這一帶（希臘化只有一條 15° 的線）",
  disc_cazimi_not_requested: "沒有選「行星中心落在太陽圓面內」的日輪內",
  sun_apparent_diameter_unavailable: "這一刻算不出太陽的視直徑（天文計算程式沒有回傳），所以「行星中心落在太陽圓面內」的日輪內這次沒有判定；所選分法本身的界線照常使用",
  // 行速、停滯與東出西入（app.core.motion_states）
  sidereal_motion_states_basis_not_authorized: "平均每日行度是照回歸黃道（以春分點起算）的速度給的，恆星黃道下不適用",
  // 行星與宮的古典分類（app.core.classical_classifications）
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
  ...Object.fromEntries(FRAME_REFUSAL_STEMS.flatMap((stem) => [
    [`j2000_${stem}_basis_not_authorized`, "此參考框架下不適用（J2000）"],
    [`nutation_off_${stem}_basis_not_authorized`, "此參考框架下不適用（章動關閉）"],
  ])),
});
/** 空值是「未提供」，不是「未識別」：兩者是不同的事實。 */
function moduleReason(code) {
  return code ? presentClosedVocabulary(code, MODULE_REASON_ZH, "原因") : "未提供";
}
// 封閉詞彙一律走這裡。有對應印中文；沒有對應印「未識別的<角色>（原值）」——
// 缺對應是看得見的缺陷，不是資料。只認自身屬性，原型鏈上的名字不是閉集成員。
const presentClosedVocabulary = Labels.closedLabel;
const pad2 = (value) => String(value).padStart(2, "0");
