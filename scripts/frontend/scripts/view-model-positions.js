// view-model：時間、天體、軸點、反照點、宮位、相位與尊貴，以及月交點、恆星、月球拱點、站心月亮與額外角點。
// 時間尺度依時代標示：1930 年、2040 年的盤不是 UTC（方法頁 §07.6）。標籤與匯出共用 exporters.js 的那一份。
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
 * 收據的時刻字串（「1990-05-15 14:30:00.000」）在毫秒為零時去掉「.000」：輸入只到秒，
 * 印出零毫秒是假精度。有毫秒的輸入照印；收據與匯出的欄位值不變。
 */
function clockTimeText(label) { return typeof label === "string" ? label.replace(/\.000$/, "") : label; }

/**
 * 歷史地方平時有秒級偏移（上海 1900 +08:05:43），兩位小數的小時看不出來，所以秒不為零時印出秒。
 * 寫成「UTC+08:00」而不是「+08:00」：以正負號開頭的儲存格會被試算表讀成公式，CSV 與區段複製
 * 就得加撇號，同一欄有的帶、有的不帶；負號用 ASCII「-」，與度分秒一致。收據數值欄位不變。
 */
function utcOffsetText(hours) {
  if (typeof hours !== "number" || !Number.isFinite(hours)) return DASH;
  const total = Math.round(Math.abs(hours) * 3600);
  const seconds = total % 60;
  const hm = `${pad2(Math.floor(total / 3600))}:${pad2(Math.floor((total % 3600) / 60))}`;
  return `UTC${hours < 0 ? "-" : "+"}${hm}${seconds ? `:${pad2(seconds)}` : ""}`;
}

function timeSection(response) {
  const time = needAt(response.astronomical_data.time, "time");
  const atmosphere = needAt(response.astronomical_data.atmosphere, "atmosphere");
  const anchored = time("input_semantics", "string") !== "exact_birth_time";
  const era = time("time_scale_era", "string");
  const scale = timeScaleLabel(era);
  const notes = [`所有時刻均標明時間尺度；${scale}這一欄是換算結果，不是輸入。`];
  if (era !== "modern_leap_second_utc") { notes.push(`這張盤的時刻屬於「${scale}」，不是以閏秒維持的現代 UTC；見方法頁 §07.6。`); }
  if (anchored) { notes.unshift("這一欄是計算用的代表性時刻，不是出生時刻。"); }
  const pressure = atmosphere("pressure_hpa", "number?");
  const pressureMode = presentClosedVocabulary(atmosphere("pressure_mode", "string"), PRESSURE_MODE_ZH, "氣壓模式");
  return makeSection("time", "時間轉換", RING.ASTRONOMICAL, { state: "present" }, {
    notes,
    tables: [{
      title: "時間", columns: ["項目", "數值"],
      rows: [
        [anchored ? "代表性錨點（非出生時刻）" : "本地時間", clockTimeText(time("input_local_time", "string"))],
        ["時區", Labels.timezoneText(time("timezone_label", "string"))], ["UTC 偏移", utcOffsetText(time("utc_offset_hours", "number"))],
        [scale, clockTimeText(time("utc_time", "string"))], ["儒略日 JD(UT)", num(time("jd_ut", "number"), 6)],
        ["ΔT（秒）", num(time("delta_t_seconds", "number"), 3)],
        ["地方真恆星時 LAST（小時）", cyclicFixed(time("last_hours", "number"), 6)],
        ["真黃赤交角 ε", dms(time("true_obliquity", "number"))],
        // 頁面永遠送 pressure_hpa=null，後端以 pressure_mode 說明
        // 它怎麼補；這裡讀的是後端真的會發的欄位（atmosphere.pressure_mode）。
        ["折射計算溫度（°C）", num(atmosphere("temperature_c", "number"), 1)],
        ["折射計算氣壓（hPa）", pressure === null ? `未指定，${pressureMode}` : num(pressure, 1)], ["氣壓來源", pressureMode],
        ["折射模型", presentClosedVocabulary(atmosphere("refraction", "string"), REFRACTION_MODEL_ZH, "折射模型")],
      ],
    }],
  });
}

/**
 * 古典七政之外、由計算政策說了算的天體組（應有集合取自這裡與政策，不取自天體清單本身）。
 * 請求了就列：不適用的中心（例如日心盤的南交點）照樣有那一列，位置是 null。
 */
const OPTIONAL_BODY_GROUPS = Object.freeze({
  outer_planets: Object.freeze(["uranus", "neptune", "pluto"]), chiron: Object.freeze(["chiron"]),
});
function groupRequested(response, group) {
  const state = policyModuleState(response, group);
  if (state === null) throw exportPipeline.incompleteResponse(`calculation_policy.modules 缺少 ${group}`);
  return state !== "not_requested";
}
function expectedBodyKeys(response) {
  const keys = [...SEVEN_KEYS];
  for (const [group, members] of Object.entries(OPTIONAL_BODY_GROUPS)) { if (groupRequested(response, group)) keys.push(...members); }
  return keys;
}
function expectedNodeKeys(response) {
  const keys = ["true_node", "mean_node"];
  if (groupRequested(response, "south_nodes")) keys.push("true_south_node", "mean_south_node");
  return keys;
}
function needBodyList(list, path, expected) {
  if (!Array.isArray(list) || !list.every(isRecord)) throw exportPipeline.incompleteResponse(`${path} 不是逐列紀錄`);
  needExactly(list.map((item, index) => need(item, `${path}[${index}]`, "key", "string")), expected, path);
  return list;
}

function bodiesSection(response) {
  const bodies = needBodyList(response.astronomical_data.bodies, "bodies", expectedBodyKeys(response));
  return makeSection("bodies", "天體位置", RING.ASTRONOMICAL, { state: "present" }, {
    notes: [
      "黃道、赤道、地平三套座標一次輸出，不必換工具重填生辰。",
      "星座與星座內度數由後端黃經以 30° 分段換寫，非另一次計算；完整精度在『運算結果＋驗算資料』的 JSON 匯出中。",
      bodies.some((body, index) => need(body, `bodies[${index}]`, "speed_position_derivative_status", "string?")
        === "known_internal_disagreement_for_sun_moon")
        ? "站心速度為 Swiss FLG_SPEED 解析值；太陽／月亮部分欄位已知不等於同次位置的有限差分導數，請勿把它當作已驗證的導數精度。" : null,
      // 後端對只有日期的請求不輸出地平座標（reason_code date_only_no_birth_time）。
      response.birth_time_sensitivity.precision === "date_only"
        ? "只有出生日期：沒有出生時刻就沒有對應的地平位置，方位角與高度不列出。" : null,
    ].filter(Boolean),
    tables: [{ title: "本命天體", columns: BODY_COLUMNS, rows: bodyRows(bodies, "bodies") }],
  });
}

function anglesSection(response) {
  // 宮位沒有請求時軸點容器是 null；是否請求由 option_states 說，不由 null 推定。
  const angles = response.astronomical_data.angles;
  const section = moduleSection(response, {
    id: "angles", title: "軸點", ring: RING.ASTRONOMICAL,
    keys: { option: requestingOption(response, "astronomical_data.angles", "include_houses") }, container: angles,
    note: "本次未產生軸點計算。",
  });
  if (section.absent) return section.absent;
  const positions = needAt(angles, "angles").in("sign_positions");
  const rows = Object.entries(Labels.VOCABULARIES.angle_label).map(([key, label]) => [label, ...positionCells(positions.position(key))]);
  return section.make({
    notes: ["軸點由地方恆星時與觀測地緯度決定，與宮位制的選擇無關。"],
    tables: [{ title: "四軸", columns: ["軸點", LONGITUDE_COLUMN, "星座度數"], rows }],
  });
}

/**
 * 依本次回應實際的黃道印公式。鏡軸固定在回歸黃道的至點軸與分點軸，恆星黃道下後端用 180°−λ−2×ayanamsa
 * （core/antiscia.py）；只印回歸黃道的公式，使用者拿畫面上的恆星黃經照算會差兩倍 ayanamsa。
 */
function antisciaFormulaNotes(response) {
  // 回歸黃道時 ayanamsa 是 null；鍵一定在，缺了不當成回歸黃道。
  const ayanamsa = need(response.astronomical_data.time, "time", "ayanamsa", "number?");
  if (ayanamsa !== null && ayanamsa !== 0) {
    return [
      `反照點 λ′ = 180° − λ − 2×ayanamsa；反向反照點 λ″ = 360° − λ − 2×ayanamsa（本次 ayanamsa = ${num(ayanamsa, 6)}°）。`,
      "鏡軸固定在回歸黃道的至點軸與分點軸，所以恆星黃經要先扣回兩倍 ayanamsa。",
    ];
  }
  return ["反照點 λ′ = 180° − λ（以 0° 巨蟹—0° 摩羯 為鏡軸）；反向反照點 λ″ = 360° − λ（以 0° 牡羊—0° 天秤 為鏡軸）。"];
}

function antisciaSection(response) {
  const container = response.derived_geometry.antiscia;
  const section = moduleSection(response, {
    id: "antiscia", title: "反照點 Antiscia", ring: RING.GEOMETRY, keys: { option: "include_antiscia", module: "antiscia" }, container,
    note: "本次未請求。座標轉換本身不需要技法選擇；勾選後公式會直接印在數值上方。",
  });
  if (section.absent) return section.absent;
  // 鏡像的是古典七政，勾了「含月交點」再加本盤的月交點（後端 antiscia.py；外行星、軸點與阿拉伯點不列）。
  // 反照點與反向反照點兩張清單都恰好是這一組、依同一順序。
  const antiscia = needAt(container, "antiscia");
  const withNodes = (optionState(response, "antiscia_include_nodes") || {}).requested === true;
  const expected = [...SEVEN_KEYS, ...(withNodes ? expectedNodeKeys(response) : [])];
  const direct = antiscia.rows("antiscia");
  const contra = antiscia.rows("contra_antiscia");
  needExactly(direct.map((item) => item("key", "string")), expected, "antiscia.antiscia");
  needExactly(contra.map((item) => item("key", "string")), expected, "antiscia.contra_antiscia");
  return section.make({
    notes: antisciaFormulaNotes(response).concat(["只提供幾何鏡像位置，不自動作關係或容許度判定。"]),
    tables: [{
      title: "反照點與反向反照點", columns: ["天體", "反照點 λ′", "反照點星座度數", "反向反照點", "反向反照點星座度數"],
      rows: direct.map((item, index) => [
        item("name", "string"), ...positionCells(item.position("sign_position", true)),
        ...positionCells(contra[index].position("sign_position", true)),
      ]),
    }],
  });
}

function houseSystemText(givenCode, name) { return Labels.houseSystemText(givenCode, name) || DASH; }

function houseNotes(houses) {
  const notes = [`宮位制：${houseSystemText(houses("system_code", "string"), houses("system_name", "string"))}。`];
  const state = houses.in("availability")("state", "string");
  if (state !== "available") { notes.push(`宮位可用狀態：${presentClosedVocabulary(state, HOUSE_AVAILABILITY_ZH, "宮位可用狀態")}。`); }
  return notes;
}

const HOUSE_COUNT = 12;

function housesSection(response) {
  const module = response.derived_methods.house_division;
  const section = moduleSection(response, {
    id: "houses", title: "宮位分割", ring: RING.METHOD,
    keys: { option: "include_houses", module: "house_division" }, container: module, note: "本次未請求宮位。",
  });
  if (section.absent) return section.absent;
  const houses = needAt(module, "house_division");
  if (houses("execution_status", "string") !== "computed") {
    throw exportPipeline.incompleteResponse("house_division 狀態是已計算，execution_status 卻不是 computed");
  }
  const cusps = houses("cusps", "array");
  const positions = houses("cusp_sign_positions", "array");
  if (cusps.length !== HOUSE_COUNT || positions.length !== HOUSE_COUNT) {
    throw exportPipeline.incompleteResponse(`house_division 的宮頭應有 ${HOUSE_COUNT} 個`);
  }
  return section.make({
    notes: houseNotes(houses),
    tables: [{
      title: "宮頭", columns: ["宮", LONGITUDE_COLUMN, "星座度數"],
      rows: positions.map((position, index) => [
        `第 ${index + 1} 宮`, ...positionCells(needPosition(position, `house_division.cusp_sign_positions[${index}]`)),
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

// 不參加相位配對的組合（後端 aspects.py）：兩個軸點之間不配；同一條交點軸、或兩種交點模型
// 之間的關係是定義，不是發現（bodies.py DEFINITIONAL_EXCLUDED_PAIRS 列的正是四個交點兩兩之間）。
const ASPECT_ANGLE_KEYS = Object.freeze(Object.keys(Labels.VOCABULARIES.angle_label));
const ASPECT_NODE_KEYS = Object.freeze(Object.keys(Labels.VOCABULARIES.node_backend_name));

/**
 * 相位模組讀進來並核對：參與者、逐度清單（pairs）與整宮不合意清單三者要互相對得起來。應有的組合由參與者兩兩配對（去掉上
 * 面兩種）得出，不取自 pairs 本身：每一組要嘛列在 pairs，要嘛星座不合意而列在不合意清單；沒列進 pairs 的組數等於
 * pair_listing 說的數目。列在 pairs、又不是軸點組合的，星座不成相位時必須也在不合意清單，反之亦然。
 */
function aspectModel(aspects) {
  const participants = aspects.rows("participants");
  const index = new Map(participants.map((item, position) => [item("key", "string"), position]));
  const names = participants.map((item) => item("name", "string"));
  const isAngle = (key) => ASPECT_ANGLE_KEYS.includes(key);
  const cellKey = (row, what) => {
    const a = index.get(row("body_a", "string"));
    const b = index.get(row("body_b", "string"));
    if (a === undefined || b === undefined) {
      throw exportPipeline.incompleteResponse(`${what}的天體不在參與者清單裡（${row.path}）`);
    }
    return `${Math.max(a, b)}:${Math.min(a, b)}`;
  };
  const universe = new Set();
  const keys = [...index.keys()];
  keys.forEach((a, i) => keys.slice(i + 1).forEach((b, offset) => {
    if (isAngle(a) && isAngle(b)) return;
    if (ASPECT_NODE_KEYS.includes(a) && ASPECT_NODE_KEYS.includes(b)) return;
    universe.add(`${i + 1 + offset}:${i}`);
  }));
  const unique = (rows, what) => {
    const seen = new Map();
    rows.forEach((row) => {
      const key = cellKey(row, what);
      if (!universe.has(key) || seen.has(key)) {
        throw exportPipeline.incompleteResponse(`${what}多出或重複一組（${row.path}）`);
      }
      seen.set(key, row);
    });
    return seen;
  };
  const pairs = aspects.rows("pairs").map((pair) => {
    const angle = isAngle(pair("body_a", "string")) || isAngle(pair("body_b", "string"));
    const ws = pair.in("whole_sign");
    if (angle && ws("applicable", "boolean") !== false) {
      throw exportPipeline.incompleteResponse(`${ws.path}：含軸點的組合沒有整宮判定，applicable 應為 false`);
    }
    return { pair, angle, ws, cell: cellKey(pair, "相位組合") };
  });
  const listed = unique(pairs.map((item) => item.pair), "相位組合");
  const aversionRows = aspects.rows("whole_sign_aversions");
  const aversions = unique(aversionRows, "不合意的組合");
  pairs.forEach(({ pair, angle, ws, cell }) => {
    if (angle) return;
    if (!ws("in_aspect", "boolean") !== aversions.has(cell)) {
      throw exportPipeline.incompleteResponse(`${pair.path} 的整宮判定與不合意清單對不上`);
    }
  });
  aversions.forEach((row, cell) => {
    if (listed.has(cell)) return;
    if (cell.split(":").some((position) => isAngle(keys[Number(position)]))) {
      throw exportPipeline.incompleteResponse(`${row.path}：含軸點的組合不參加整宮判定`);
    }
  });
  const unlisted = [...universe].filter((cell) => !listed.has(cell));
  if (unlisted.some((cell) => !aversions.has(cell))) {
    throw exportPipeline.incompleteResponse("aspects：有組合既不在 pairs，也不在不合意清單");
  }
  const count = aspects.in("pair_listing")("unlisted_pairs_without_aspect", "number");
  if (count !== unlisted.length) {
    throw exportPipeline.incompleteResponse(`aspects.pair_listing 說沒列出 ${count} 組，參與者兩兩配對後沒列出的是 ${unlisted.length} 組`);
  }
  const nameOf = new Map(keys.map((key, position) => [key, names[position]]));
  return { names, nameOf, pairs, aversionRows, aversions, unlisted: count };
}

/** 軸點組合沒有整宮 doctrine——「不適用」；兩星的星座不成相位時是後端的名稱「不合意」，不是「無」。 */
function wholeSignCell(item) { return item.angle ? "不適用" : item.ws("configuration_zh", "string"); }

function signGapText(signed) {
  if (!Number.isInteger(signed) || signed < 0 || signed > 11) return DASH;
  const gap = Math.min(signed, 12 - signed);
  return gap === 1 ? "相鄰（差 1 個星座）" : `差 ${gap} 個星座`;
}

// 名稱取後端參與者清單（participants）的名稱；頁面視圖的不合意清單只帶鍵。
function aversionTable(model) {
  if (!model.aversionRows.length) return null;
  return {
    title: "不合意的組合（整宮）", columns: ["組合", "兩星所在星座"],
    rows: model.aversionRows.map((row) => [
      `${model.nameOf.get(row("body_a"))} — ${model.nameOf.get(row("body_b"))}`, signGapText(row("signed_sign_distance", "number")),
    ]),
  };
}


// 〈位置〉章排在〈宮位與相位〉章之前，讀者先讀到這一句，書名原文附在這裡（每份只附一次）。
const PRENATAL_SYZYGY_NOTE = "產前朔望是出生前最近一次朔或望。Ptolemy 用它的度數來定出生的上升度數"
  + "（《占星四書》（Tetrabiblos）III.2），"
  + "選壽命主宰時也用它（III.10）。本站只列出時刻與度數（見「產前朔望與出生前日月食的度數」一節），" + "不拿它去推算上升點或壽命。";

const AVERSION_NOTE = "不合意（aversion）：兩顆星所在的星座相鄰，或差 5 個星座，" + "彼此不成合、六分、四分、三分、對分任何一種相位。"
  + "Ptolemy《占星四書》卷一第 16 章把這樣的星座稱為「不相連」（disjunct），"
  + "說它們彼此沒有關聯、像是互相背對；這是該書的分類，照原文列出。"
  + "「不合意的組合」一表列出本盤每一組這樣的組合；上升點與中天不參加星座這一層的判斷，不列。";

/**
 * 最近相位那一格的判定。後端只在 aspect_targets 存一份（ASPECT_TARGET_LISTING 的
 * nearest_aspect_entry 保證列出）；pair 頂層不再抄寫。找不到那一格就是契約破損，不以空白掩蓋。
 */
function nearestTarget(pair, key) {
  const target = pair.rows("aspect_targets").find((item) => item("key", "string") === key);
  if (!target) { throw exportPipeline.incompleteResponse(`${pair.path} 缺少最近相位的判定（aspect_targets）`); }
  return target;
}

function applyingCell(pair, target) {
  const applying = target("applying", "string?");
  if (applying === null) {
    const reason = pair("applying_reason_code", "string?");
    return reason ? presentClosedVocabulary(reason, APPLYING_REASON_ZH, "入出相位理由") : DASH;
  }
  return presentClosedVocabulary(applying, APPLYING_ZH, "入出相位狀態");
}

/**
 * 同度一格。對某個相位的每一格都成立的理由（現代小相位不適用同度判準）只寫在
 * degree_based.partile_reason_codes_by_aspect 一次，那些格子的 partile 與理由都是 null。
 */
function partileCell(target, reasonsByAspect) {
  const partile = target("partile", "boolean?");
  const ownReason = target("partile_reason_code", "string?");
  const key = target("key", "string");
  const aspectReason = Object.hasOwn(reasonsByAspect, key) ? reasonsByAspect[key] : null;
  if (aspectReason !== null && (partile !== null || ownReason !== null)) {
    throw exportPipeline.incompleteResponse(`${target.path}：${key} 的同度理由已寫在模組，這一格卻另有判定`);
  }
  const reason = ownReason ?? aspectReason;
  if (partile === true) return "是";
  if (partile === false) { return reason && Object.hasOwn(PARTILE_FALSE_REASON_ZH, reason) ? PARTILE_FALSE_REASON_ZH[reason] : "否"; }
  // partile 為 null 一定有理由（格子自己的或模組按相位寫的）；兩者都缺是殘缺。
  if (!reason) throw exportPipeline.incompleteResponse(`${target.path}：同度為 null 卻沒有理由`);
  return presentClosedVocabulary(reason, PARTILE_REASON_ZH, "同度理由");
}

/** 完成時刻一格；搜尋窗只寫在模組的 perfection 收據一次（windowDays 讀它）。 */
function perfectionCell(target, windowDays) {
  const status = target("perfection_status", "string");
  if (status === "found") {
    const hours = target.in("perfection")("hours_from_chart_moment", "array");
    if (!hours.length || !hours.every((value) => typeof value === "number")) {
      throw exportPipeline.incompleteResponse(`${target.path}.perfection.hours_from_chart_moment 應是非空的數字清單`);
    }
    return `${hours[0].toFixed(2)} 小時後` + (hours.length > 1 ? `（搜尋窗內共 ${hours.length} 次）` : "");
  }
  if (status === "searched_no_root") {
    // 搜尋過就一定有那一格的搜尋紀錄；缺了是殘缺，不只看模組的搜尋窗就帶過。
    target.in("perfection");
    return `搜尋過但 ${windowDays()} 日內沒有找到交會`;
  }
  // 完成時刻只對此刻入相位者搜尋；其餘三種相態各自說出為何沒搜尋。
  const applying = target("applying", "string?");
  if (status === "not_applying" && Object.hasOwn(NOT_APPLYING_PHASE_ZH, applying)) { return NOT_APPLYING_PHASE_ZH[applying]; }
  return presentClosedVocabulary(status, PERFECTION_STATUS_ZH, "完成狀態");
}

/** 相位名稱：只取後端 degree_based.aspect_names_zh（唯一產生器）；畫面要用的名字缺了就拒絕。 */
function aspectName(zhByKey, key, path) {
  if (!zhByKey.has(key)) {
    throw exportPipeline.incompleteResponse(`aspects.degree_based.aspect_names_zh 缺少 ${key}（${path}）`);
  }
  return zhByKey.get(key);
}

/**
 * 容許度內的相位：pair 的 aspects_in_orb 與 aspect_targets 裡 in_orb 為真的那幾格必須是同一組
 * （兩邊各自說一次，少一邊就是殘缺）。
 */
function inOrbTargets(pair) {
  const keys = pair("aspects_in_orb", "array");
  const targets = pair.rows("aspect_targets").filter((target) => target("in_orb", "boolean?") === true);
  needExactly(targets.map((target) => target("key", "string")).sort(), [...keys].sort(), `${pair.path}.aspects_in_orb`);
  return targets;
}

function inOrbCell(pair, target, orbUnavailable, zhByKey) {
  const keys = pair("aspects_in_orb", "array");
  if (keys.length) return keys.map((key) => aspectName(zhByKey, key, pair.path)).join("、");
  if (orbUnavailable) return "未套用容許度";
  const reason = target("in_orb_reason_code", "string?");
  if (target("in_orb", "boolean?") === null && reason) { return presentClosedVocabulary(reason, IN_ORB_REASON_ZH, "容許度理由"); }
  return "無";
}

function orbAppliedNote(response, degree, orbReceipt) {
  const option = optionState(response, "aspect_orb_profile");
  const origin = option && option.input_presence === "defaulted" ? "產品預設" : "本次選定";
  const detail = degree.in("orb_profile_detail", true);
  if (detail) { return `相位依〈${detail("display_name", "string")}〉判定` + `（${origin}的容許度表），可在進階選項切換。`; }
  const fixed = orbReceipt("fixed_pair_threshold_degrees", "number?");
  if (fixed !== null) { return `相位依固定容許度 ${num(fixed, 1)}° 判定，可在進階選項切換。`; }
  return "相位已套用容許度判定，可在進階選項切換。";
}

/**
 * 後端只列有相位的組合（逐度在容許度內或 partile，或整宮成相位），含上升點／中天的組合一律列出；其餘只給數量
 * （pair_listing）。規則與數量都說出來，表格少了的列才不會被讀成「沒算」。數量為 0 時不加這句。
 */
function unlistedPairsNote(count, degree, orbUnavailable) {
  if (!(count > 0)) return null;
  const angles = degree.in("angle_participation")("executed", "boolean?") === true;
  const rule = orbUnavailable ? "表中只列兩星的星座成相位或判為同度的組合（目前沒有選定容許度表，逐度層沒有判定）"
    : "表中只列有相位的組合：在容許度內，或兩星的星座成相位，或判為同度";
  const angleRule = angles ? "；含上升點或中天的組合一律列出" : "";
  const rest = orbUnavailable ? `其餘 ${count} 組的星座不合意，不在這張表，列在「不合意的組合」。`
    : `其餘 ${count} 組沒有相位（星座不合意，逐度也不在容許度內），不在這張表，列在「不合意的組合」。`;
  return `${rule}${angleRule}。${rest}`;
}

const APPLYING_SHORT_ZH = Object.freeze({
  applying: "入", exact_now: "精確", separating: "出", indeterminate_relative_station: "方向未定",
});

/**
 * 相位方格：同一份 pairs 排成三角形，不另算。列是第 2 到最後一個參與者，欄是第 1 到倒數
 * 第二個；一格是容許度內的每個相位（名稱、距精確的度數、入／出），容許度內沒有相位但
 * 兩星的星座成相位時寫「整宮」加名稱。後端沒列出的組合（沒有相位）與對角線以上留空。
 */
function aspectGridTable(model, zhByKey) {
  const { names } = model;
  if (names.length < 2) return null;
  const cells = new Map();
  model.pairs.forEach((item) => {
    const inOrb = inOrbTargets(item.pair);
    const text = inOrb.length
      ? inOrb.map((target) => {
        const applying = target("applying", "string?");
        return [
          aspectName(zhByKey, target("key"), target.path), `${num(Math.abs(target("offset_from_exact_degrees", "number")), 2)}°`,
          applying === null ? null : presentClosedVocabulary(applying, APPLYING_SHORT_ZH, "入出相位狀態"),
        ].filter(Boolean).join(" ");
      }).join("；")
      // 軸點組合沒有整宮 doctrine（applicable=false），不讀它的 in_aspect。
      : item.angle ? DASH
        : item.ws("in_aspect", "boolean") ? `整宮${item.ws("configuration_zh", "string")}` : item.ws("configuration_zh", "string");
    cells.set(item.cell, text);
  });
  // 沒有列進逐度相位表的不合意組合，方格裡也寫出名稱，不留白。
  model.aversions.forEach((row, cell) => { if (!cells.has(cell)) cells.set(cell, row("configuration_zh", "string")); });
  return {
    title: "相位方格", variant: "aspect_grid", columns: ["天體", ...names.slice(0, -1)],
    rows: names.slice(1).map((name, row) => [
      name, ...names.slice(0, -1).map((_other, column) => (column <= row ? (cells.get(`${row + 1}:${column}`) ?? "") : "")),
    ]),
  };
}

function aspectsSection(response) {
  const container = response.derived_methods.aspects;
  const aspectsStatus = moduleState(response, { option: "include_aspects", module: "aspects" }, container, true);
  if (aspectsStatus.state !== "present") { return absentSectionFor("aspects", "相位", RING.METHOD, "本次未請求相位。", aspectsStatus); }
  // pairs 在 aspects 的**頂層**，不在 degree_based 底下；缺了就拒絕，不補成空表。
  const aspects = needAt(container, "aspects");
  const model = aspectModel(aspects);
  const degree = aspects.in("degree_based");
  const orbReceipt = degree.in("orb_receipt");
  const orbUnavailable = degree("orb_verdict_available", "boolean") === false;
  const notes = [];
  if (orbUnavailable) {
    notes.push(
      "目前沒有選定容許度（orb）表，因此每一組相位只有幾何角距離，" + "沒有「是否在容許度內」的判定。"
      + "你可以先看幾何關係，或回到選項指定一套容許度來源。"
    );
  } else { notes.push(orbAppliedNote(response, degree, orbReceipt)); }
  const unlisted = unlistedPairsNote(model.unlisted, degree, orbUnavailable);
  if (unlisted) notes.push(unlisted);
  // 三欄讀的是 aspect_targets 中最近相位那一格（nearestTarget）；每個相位各自的判定都在匯出的 aspect_targets。
  notes.push(
    "「入／出」「同度」「完成時刻」三欄只描述最近的那個相位；" + "容許度內若不只一個相位，其他相位各自的狀態在 JSON 匯出裡逐一列出。"
  );
  notes.push(...classicalDisagreementNotes(response, "derived_methods.aspects"));
  const zhByKey = new Map(Object.entries(degree.in("aspect_names_zh").record));
  const partileReasons = degree.in("partile_reason_codes_by_aspect").record;
  const tables = [];
  if (model.pairs.length) {
    tables.push({
      title: "逐度相位",
      columns: [
        "組合", "整宮配置", "最近相位", "角距離", "距精確（度）",
        "最近相位的入／出", "最近相位的同度", "最近相位的完成時刻", "容許度內的相位",
      ],
      collapse: ["最近相位的入／出", "最近相位的同度", "最近相位的完成時刻"],
      rows: model.pairs.map((item) => {
        const { pair } = item;
        const near = pair.in("nearest_aspect");
        const nearKey = near("key", "string");
        const target = nearestTarget(pair, nearKey);
        inOrbTargets(pair);
        return [
          `${pair("body_a_name", "string")} — ${pair("body_b_name", "string")}`, wholeSignCell(item),
          aspectName(zhByKey, nearKey, near.path), num(pair("separation_degrees", "number"), 4),
          signedNum(near("signed_offset_from_exact_degrees", "number"), 4), applyingCell(pair, target), partileCell(target, partileReasons),
          perfectionCell(target, () => aspects.in("perfection")("search_window_days", "number")),
          inOrbCell(pair, target, orbUnavailable, zhByKey),
        ];
      }),
    });
  }
  const grid = aspectGridTable(model, zhByKey);
  if (grid) {
    tables.push(grid);
    notes.push(
      "「相位方格」把同一份結果排成三角形：每一格是容許度內的相位、距精確的度數與入／出相位；"
      + "容許度內沒有相位、但兩星的星座成相位時寫「整宮」加相位名；兩星的星座不成相位時寫「不合意」；"
      + "含上升點或中天、又不在容許度內的組合寫「—」。" + "畫面上，「整宮」的格子畫成同一個相位記號的淡色虛線版，「不合意」的格子畫一個淡色的「×」。"
    );
  }
  const aversionRows = aversionTable(model);
  if (aversionRows) { tables.push(aversionRows); notes.push(AVERSION_NOTE); }
  // orb 未選定不是「相位模組被拒絕」；相位算出來了，少的是一層判定。
  const status = orbReceipt("requested", "boolean") ? receiptStatus(orbReceipt.record) : aspectsStatus;
  return makeSection("aspects", "相位", RING.METHOD, status, { notes, tables });
}

function dignitiesSection(response) {
  const dignities = response.derived_methods.essential_dignities;
  const status = moduleState(response, { module: "essential_dignities" }, dignities, true);
  if (status.state !== "present") { return absentSectionFor("dignities", "本質尊貴", RING.METHOD, "本次未請求本質尊貴。", status); }
  const notes = [];
  notes.push(
    "廟與旺的表同時列出陷與弱（detriment／fall）；外來（peregrine）另有一個選項，選了才列。"
    + "接納（含互容）尚未評估，那是「未評估」，不是「沒有」。"
  );
  const selected = need(dignities, "essential_dignities", "selected_profiles", "record");
  const comparison = triplicityComparison(response, dignities, selected.triplicity);
  const stateText = (technique, profile) => {
    if (technique === "triplicity" && !profile && comparison.length) return `未選定（並列比較 ${comparison.length} 套）`;
    if (!profile) return "未選定";
    if (profile !== ALL_PROFILES) return "已選定";
    // 套數是目錄的套數；回應少算一套時，那一區（allProfilesSection）會拒絕整份回應。
    return `全部並列（${catalogueProfiles(technique).length} 套）`;
  };
  const tables = [{
    title: "本次計算的技法", columns: ["技法", "狀態"],
    rows: [
      ["廟旺陷弱 domicile／exaltation／detriment／fall", "domicile_exaltation"], ["界 bounds", "bounds"],
      ["面／旬 face／decan", "face_decan"], ["三分性 triplicity", "triplicity"], ["外來 peregrine（依 Lilly 1647 判）", "peregrine"],
    ].map(([technique, key]) => [technique, stateText(key, need(
      selected, "essential_dignities.selected_profiles", key, "string?"
    ))]),
  }];
  notes.push(...classicalDisagreementNotes(response, "derived_methods.essential_dignities"));
  if (comparison.length && selected.triplicity) {
    notes.push(`另有 ${comparison.length} 套並列比較用的 profile；並列不會改變你選定的那一套。`);
  }
  return makeSection("dignities", "本質尊貴與分配法", RING.METHOD, status, {
    notes, tables, blocks: ["評估基礎：回歸黃道、地心位置、當日黃道框架。"],
  });
}


function bodyRows(list, path) {
  return list.map((item, index) => {
    const b = needAt(item, `${path}[${index}]`);
    // 三態，不是二態：heliocentric/barycentric 下太陽與月交點的 motion_sign 是 null（該中心無物理意義），
    // 摺成「順行」就是一句沒有依據的天文陳述。"zero" 印「順行」：速度為零算不算停滯是方法問題，
    // 後端 core/bodies.py 不判斷，這裡也不代判。
    const motion = b("motion_sign", "string?");
    return [
      b("name", "string"), ...positionCells(b.position("sign_position", true)), dms(b("latitude", "number?")),
      cyclicFixed(b("right_ascension", "number?"), 6), dms(b("declination", "number?")),
      cyclicFixed(b("azimuth", "number?"), 3), num(b("altitude_true", "number?"), 3),
      num(b("altitude_apparent", "number?"), 3), motion === "negative" ? "逆行"
        : motion === "positive" || motion === "zero" ? "順行" : DASH,
    ];
  });
}
// 角度欄印的是十進位度，表頭帶單位；方位角另標起算慣例（後端 core/bodies.py 已換成
// 北＝0°、向東順時針，Swiss 原始的南＝0° 只留在計算軌跡）。
const LONGITUDE_COLUMN = "黃經 λ（度）";
// 星座裡走了幾度（0°–30°）。「宮」在本站只指宮位，這一欄不叫「宮內度數」。
const DEGREE_IN_SIGN_COLUMN = "星座內度數";
const AZIMUTH_COLUMN = "方位角 Az（度，北＝0°，順時針）";
const BODY_COLUMNS = [
  "天體", LONGITUDE_COLUMN, "星座度數", "黃緯 β（度）", "赤經 α（度）", "赤緯 δ（度）",
  AZIMUTH_COLUMN, "真高度（度）", "視高度（度）", "行進",
];
// 畫面上的短表頭：完整欄名在窄欄裡折成兩行，與其他一行的表頭不齊。起算慣例改寫成表下註；
// 匯出讀 canonical sections，欄名照舊是完整的那一個。
const SCREEN_COLUMNS = Object.freeze({
  [AZIMUTH_COLUMN]: { label: "方位角 Az（度）", note: "方位角從正北 0° 起算，向東順時針量到 360°。" },
});

// 求根與線性外插的差別對讀者是有意義的：後者在月亮速度變化、行星站留、
// 或同一視窗內多重根時會給錯完成時刻。哪一種在用，只有回應知道。求根是先以有限間隔
// 掃描再二分，間距小於掃描間隔的兩個根或只碰一下的切點可能整個漏掉，所以不宣稱對多重根成立。
function solverLimitation(solver) {
  if (!solver) { return "本次回應沒有交代用了哪一種求解器，因此無法說明它的限制。"; }
  if (solver.includes("linear")) {
    return "本模組以線性外插求相位完成時刻，那是已知的正確性缺陷：" + "月亮速度會變、被相位的行星可能站留、站留附近可能出現多重根。";
  }
  return "完成時刻以求根取得，逐點查詢星曆而不假設速度為定值；" + "以有限間隔搜尋；間距極近的根或切點可能遺漏。"
    + "括號端點與迭代次數一併輸出，可據以複算。";
}

/**
 * 白名單：前現代具名文本彼此給出不同規則的方法，在結果旁標「古典文獻說法不一」。標記與說明的唯一產生器是後端
 * core/contested_methods.py（calculation_dossier.methodology.classical_source_disagreements）；前端只依 response_path
 * 取用，不自己決定哪個方法有爭議，也不另寫說明。這不是 method_status：對外不出現 provisional。
 */
function classicalDisagreementNotes(response, responsePath) {
  const dossier = isRecord(response.calculation_dossier) ? response.calculation_dossier : {};
  const methodology = isRecord(dossier.methodology) ? dossier.methodology : {};
  const marks = isRecord(methodology.classical_source_disagreements) ? methodology.classical_source_disagreements : {};
  const items = Array.isArray(marks.items) ? marks.items : [];
  return items.filter((item) => isRecord(item) && item.response_path === responsePath && typeof item.note_zh === "string" && item.note_zh)
    .map((item) => {
      // 有些標記另帶「本次採用」：這次輸出實際用的定義（後端依本次的 method 產生）。
      const applied = Object.hasOwn(item, "applied_note_zh") && typeof item.applied_note_zh === "string" ? item.applied_note_zh : "";
      return `古典文獻說法不一：${item.note_zh}${applied}`;
    });
}

function nodesSection(response) {
  // 月交點每張盤都算（輸出契約：不屬於任何選項的容器）；缺席或少一列都不是「未請求」。
  const nodes = needBodyList(response.astronomical_data.nodes, "nodes", expectedNodeKeys(response));
  return makeSection("nodes", "月交點", RING.ASTRONOMICAL, { state: "present" }, {
    notes: ["密切交點與平均交點分列，不替使用者擇一。"], tables: [{ title: "交點", columns: BODY_COLUMNS, rows: bodyRows(nodes, "nodes") }],
  });
}

function fixedStarsSection(response) {
  const stars = response.astronomical_data.fixed_stars;
  const section = moduleSection(response, {
    id: "fixed_stars", title: "恆星", ring: RING.ASTRONOMICAL,
    keys: { option: "include_fixed_stars", module: "fixed_stars" }, container: stars,
    note: "本次未請求恆星。目錄內的恆星全部列為研究用途，勾選才計算。",
  });
  if (section.absent) return section.absent;
  // 查詢失敗的星也留一列（後端 fixed_stars.py）：列數必須等於目錄收錄數，少一列就是殘缺。
  const catalogSize = need(response.astronomical_data.fixed_star_policy, "fixed_star_policy", "catalog_size", "number");
  const list = needRows(stars, "fixed_stars");
  if (list.length !== catalogSize) {
    throw exportPipeline.incompleteResponse(`fixed_stars 應有 ${catalogSize} 顆，回應是 ${list.length} 顆`);
  }
  // 後端以閉集 magnitude_basis 標明星等是單星還是整團合計；前端不另存星團名單。
  const cluster = (star) => star("magnitude_basis", "string") === "cluster_integrated";
  return section.make({
    notes: [
      "本項只提供位置與星等，不自動判定恆星合相。", `目錄收錄 ${catalogSize} 顆，本次輸出 ${list.length} 顆。`,
      "「星表代碼」是本站星曆程式（Swiss Ephemeris）星表裡這顆星的代碼，多半是拜耳名的縮寫，"
        + "例如 alTau 是金牛座 α 星（畢宿五）；核對或自己重算時用得到。",
      ...(list.some(cluster)
        ? ["星團列的是星表給整個星團的一個位置（各星團的記錄離星團中心多遠，見方法頁）；星等是整團合計的亮度，不是一顆星的亮度，所以在星等後標「整團合計」。"]
        : [])], tables: [{
      title: "恆星位置",
      // note 與 features 頁都說有星等，表就要有星等欄。古典恆星表列黃經與黃緯，所以黃緯緊接在黃道的兩欄之後。
      columns: ["恆星", "星表代碼", LONGITUDE_COLUMN, "星座度數", "黃緯 β（度）", "赤緯 δ（度）", "星等"],
      rows: list.map((star) => {
        const magnitude = star("magnitude", "number?");
        return [
          // 中文名只取後端 config.py 的 name，前端不另存星名表。
          star("name", "string"), star("catalog_name", "string?") || DASH, ...positionCells(star.position("sign_position", true)),
          dms(star("latitude", "number?")), dms(star("declination", "number?")),
          cluster(star) && magnitude !== null ? `${num(magnitude, 2)}（整團合計）` : num(magnitude, 2),
        ];
      }),
    }],
  });
}

function lunarApsidesSection(response) {
  const module = response.astronomical_data.lunar_apsides;
  const section = moduleSection(response, {
    id: "lunar_apsides", title: "Lilith 與 Priapus", ring: RING.ASTRONOMICAL,
    keys: { option: "include_lilith_priapus", module: "lunar_apsides" }, container: module, note: "本次未請求。",
  });
  if (section.absent) return section.absent;
  const points = needBodyList(need(module, "lunar_apsides", "points"), "lunar_apsides.points",
    Object.keys(Labels.VOCABULARIES.lunar_apsis_backend_name));
  return section.make({
    notes: ["三個點都是月球軌道的幾何點，不是物理天體；本項顯示位置，不自動加入相位判定。"],
    tables: [{ title: "月球拱點", columns: BODY_COLUMNS, rows: bodyRows(points, "lunar_apsides.points") }],
  });
}

function parallaxMoonSection(response) {
  const module = response.astronomical_data.parallax_moon;
  const section = moduleSection(response, {
    id: "parallax_moon", title: "站心月亮", ring: RING.ASTRONOMICAL,
    keys: { module: "parallax_moon" }, container: module, note: "本次未請求。月亮位置口徑維持跟隨整體計算中心。",
  });
  if (section.absent) return section.absent;
  const moon = needAt(module, "parallax_moon");
  return section.make({
    notes: [
      "畫面上同時出現兩個月亮不是錯誤，是明示的座標政策：" + "地心參考值保留，站心值另計。",
      "整張盤以地心位置為基準；月亮另列出生地觀測者所見的站心位置。月亮位置、落宮、反照點、阿拉伯點、月空亡、赤緯與黃道相位、本質尊貴與出生時刻敏感度使用站心月亮；"
      + "月相與日月食仍依地心視黃經，升降本來就以站心計算，日夜盤仍用地心太陽高度。",
    ],
    tables: [{
      title: "兩個月亮", columns: ["來源", LONGITUDE_COLUMN],
      rows: [
        ["地心參考 geocentric", longitudeText(moon.in("geocentric_reference").position("sign_position"))],
        ["站心生效 topocentric", longitudeText(moon.in("topocentric_effective").position("sign_position"))],
        ["差值（度）", num(moon("longitude_delta_degrees", "number"), 6)],
      ],
    }],
  });
}

/**
 * 一個模組可能由不只一個選項寫入；哪些選項會寫進它，由後端收據的 response_paths 宣告，這裡不另抄一份。回傳真的請求了它
 * 的那個選項，沒有任何一個請求時回 fallback。
 */
function requestingOption(response, modulePath, fallback) {
  const states = calculationPolicy(response).option_states;
  if (!isRecord(states)) return fallback;
  const carriers = Object.keys(states).filter((key) => {
    const entry = states[key];
    if (!isRecord(entry) || !("response_paths" in entry) || !Array.isArray(entry.response_paths)) { return false; }
    return entry.response_paths.some((path) => path === modulePath || String(path).startsWith(`${modulePath}.`));
  });
  return carriers.find((key) => "requested" in states[key] && states[key].requested === true) || fallback;
}

function extraAnglesSection(response) {
  const module = response.astronomical_data.extra_angles;
  // 額外角點模組由 include_extra_angles 與 include_anti_vertex 共用。只以前者
  // 判斷時，只勾反宿命點的請求在後端算出並回傳了它，畫面卻會寫「本次未請求」。
  const section = moduleSection(response, {
    id: "extra_angles", title: "額外角點", ring: RING.ASTRONOMICAL,
    keys: { option: requestingOption(response, "astronomical_data.extra_angles", "include_extra_angles") }, container: module,
    note: "本次未請求。",
  });
  if (section.absent) return section.absent;
  const angles = needAt(module, "extra_angles").in("angles");
  const requested = (option) => (optionState(response, option) || {}).requested === true;
  const expected = [
    ...(requested("include_extra_angles") ? EXTRA_ANGLE_KEYS : []), ...(requested("include_anti_vertex") ? ["anti_vertex"] : []),
  ].sort();
  needExactly(Object.keys(angles.record).sort(), expected, "extra_angles.angles");
  return section.make({
    notes: ["五個角點由Swiss Ephemeris的宮位計算附帶取得；反宿命點由宿命點的精確對蹠位置導出。這些都不是古典占星的四軸。"],
    tables: [{
      title: "角點", columns: ["角點", LONGITUDE_COLUMN, "星座度數"],
      rows: Object.keys(angles.record).map((key) => {
        const angle = angles.in(key);
        return [angle("zh", "string"), ...positionCells(angle.position("sign_position", true))];
      }),
    }],
  });
}
/** include_extra_angles 帶來的五個角點（後端 core/houses.py）；反宿命點另由 include_anti_vertex 帶。 */
const EXTRA_ANGLE_KEYS = Object.freeze(["co_ascendant_koch", "co_ascendant_munkasey", "equatorial_ascendant", "polar_ascendant", "vertex"]);

// 後端的鍵與列舉值不是顯示字串（sun、內部狀態碼、planet_in_house.jupiter）。識別碼與顯示名稱在這裡成對宣告一次，渲染只
// 准用顯示名稱那一欄。後端只有一套敏感度封閉詞彙（SENSITIVITY_STATES）。最後兩個只說分類在取樣點是否一致，不說結果穩
// 定；數值在區間內本來就會移動。與取樣摘要的「這五個取樣點分類相同」同一套說法。
const SAMPLING_STATUS_ZH = Object.freeze({
  not_requested: "未請求", not_applicable: "此模式下無可比較的值", not_evaluated: "只算了代表性時刻，未在取樣時刻重算",
  partially_evaluated: "只比較了其中一部分", same_at_all_samples: "各取樣點分類相同", differs_between_samples: "取樣點之間分類不同",
});
function samplingStatus(value) { if (!value) return DASH; return presentClosedVocabulary(value, SAMPLING_STATUS_ZH, "取樣狀態"); }
function moduleLabelBySuffix(name) {
  const key = Object.keys(MODULE_COVERAGE).find((path) => path === name || path.endsWith(`.${name}`));
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

const ECLIPSE_SLOTS = [["previous_solar", "前一次日食"], ["previous_lunar", "前一次月食"]];
// 鍵是 backend/app/core/lunar_events.py _eclipse_type 的回傳閉集（含 hybrid 與 unknown）；view_model.test.cjs 直接讀該
// 函式對照。hybrid 依臺北市立天文科學教育館通行譯名「複合日食」（別名「全環食」）。
const ECLIPSE_TYPE_ZH = { total: "全食", partial: "偏食", annular: "環食", hybrid: "複合日食", penumbral: "半影食", unknown: "類型未判定" };
// 日食類型是否落在分類邊界內。鍵是 backend/app/core/lunar_events.py CLASSIFICATION_BORDERLINE_STATES；
// tests/integration/test_frontend_contract.py 以後端的值逐一渲染驗證。這裡只給表格裡的短標籤；完整白話說明由後端
// explanation_zh 產生（唯一產生者），原樣印出。
const ECLIPSE_BORDERLINE_ZH = Object.freeze({
  inside_classification_margin: "近分類邊界", outside_classification_margin: "不在邊界附近",
  no_criterion_for_lunar_eclipses: "月食未做邊界檢查",
});
const LUNAR_PHASE_ZH = Object.freeze({ new_moon: "朔", first_quarter: "上弦", full_moon: "望", last_quarter: "下弦" });
const LUNAR_CONTRACT_ZH = Object.freeze({ geocentric_apparent_tropical_of_date: "地心視黃經、當日回歸黃道" });
// astronomical_data.atmosphere 的兩個閉集。鍵是後端 backend/app/main.py 組 atmosphere 時實際發出的值，不得自創。
const PRESSURE_MODE_ZH = Object.freeze({
  swiss_estimate_from_altitude: "依海拔估算（Swiss Ephemeris 以觀測地海拔推算標準氣壓）", user_supplied: "使用者指定",
});
const REFRACTION_MODEL_ZH = Object.freeze({ swiss_ephemeris_standard_model: "Swiss Ephemeris 標準大氣折射模型" });

// 以下每一張表的鍵都是後端閉集的原值（檔名在各行註明），值是畫面用字。
// 後端新增一個值而這裡沒跟上，畫面印「未識別的…（原值）」，缺對應是看得見的缺陷。

// core/dossier.py calculation_policy.moon_position。profile 標籤與
// options-catalogue.js 的 moon_position_profile 同字（view_model.test.cjs 對照兩處）。
const MOON_PROFILE_ZH = Object.freeze({ global_computation_mode: "跟隨整體計算中心", moon_only_topocentric_v1: "僅月亮採站心" });
// effective_moon_source：topocentric_observer 或 computation_mode.center（schemas.py 的四個中心）。
const MOON_SOURCE_ZH = Object.freeze({
  topocentric_observer: "出生地站心觀測者", geocentric: "地心", topocentric: "站心", heliocentric: "日心", barycentric: "太陽系質心",
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
const CONTRACT_STATUS_ZH = Object.freeze({ provisional: "欄位仍可能變動，尚非已凍結的公開 API" });
const CONTRACT_COMPATIBILITY_ZH = Object.freeze({
  "additive_during_0.x_unless_a_documented_correctness_fix_requires_change": "0.x 期間只新增欄位；除非有記錄在案的正確性修正，既有欄位不改",
});
const BUILD_IDENTITY_STATUS_ZH = Object.freeze({ unavailable: "未提供（此建置沒有注入原始碼修訂）" });
const DOSSIER_STATUS_ZH = Object.freeze({ provisional: "格式尚未凍結，仍可能變動" });
const ATTESTATION_STATUS_ZH = Object.freeze({ provisional_pending_external_review: "自我聲明，尚待外部審查" });

// house_division.availability（core/houses.py HOUSE_AVAILABILITY_STATES）。
const HOUSE_AVAILABILITY_ZH = Object.freeze({
  available: "可用", available_polar_geometry: "可用，但位於極區：部分黃道度數不升起或不落下，宮位幾何與中低緯度不同",
  unstable: "可用，但高緯度下象限宮位對出生時刻與緯度極為敏感", unavailable: "不可用",
});

// core/lots.py SECT_STATUSES 與 LOT_FORMULA_BASES。
const SECT_STATUS_ZH = Object.freeze({
  day: "日盤", night: "夜盤", boundary_both_shown: "近地平邊界：判定仍依 > 0° 規則，阿拉伯點兩套並列",
});
const LOT_FORMULA_BASIS_ZH = Object.freeze({
  day_formula: "日盤公式", night_formula: "夜盤公式", both_formulas_boundary: "日盤公式與夜盤公式兩套並列",
});
const SECT_APPLIED_ZH = Object.freeze({ day: "日盤公式", night: "夜盤公式" });

// core/aspects.py APPLYING_STATES、PERFECTION_STATUSES 與各理由碼。
const APPLYING_ZH = Object.freeze({
  applying: "入相位", exact_now: "此刻精確", separating: "出相位", indeterminate_relative_station: "相對速度為零，方向未定",
});
const APPLYING_REASON_ZH = Object.freeze({
  angle_motion_not_modeled: "不適用（軸點運動未建模）", relative_speed_unavailable: "無法判定（缺少相對速度）",
});
const PARTILE_REASON_ZH = Object.freeze({
  no_aspect_verdict_available_for_partile: "無法判定（沒有容許度判定）",
  partile_profile_not_applicable_to_modern_minor_aspect: "不適用（現代小相位）",
});
// partile 為 false 時的理由（core/aspects.py PARTILE_REASON_CODES）：
// 同度要先在整宮上構成該相位，畫面說出「否」是哪一種否。
const PARTILE_FALSE_REASON_ZH = Object.freeze({
  same_degree_without_whole_sign_aspect: "否（度數相同，但兩星的星座不成這個相位）",
  no_whole_sign_aspect_for_partile: "否（兩星的星座不成這個相位）", angle_pair_not_in_orb_for_partile: "否（不在軸點容許度內）",
});
const IN_ORB_REASON_ZH = Object.freeze({
  orb_profile_not_selected: "未套用容許度", angle_orb_not_selected: "未判定（未指定軸點容許度）",
  historical_orb_profile_not_applicable_to_modern_minor_aspect: "未判定（歷史容許度表不用於小相位）",
  no_sourced_orb_for_participant: "未判定（此參與者沒有出處可據的容許度）",
});
// perfection_status=not_applying 時，依同一格的 applying（core/aspects.py APPLYING_STATES）分開說。
const NOT_APPLYING_PHASE_ZH = Object.freeze({
  exact_now: "此刻已精確，不另搜尋", separating: "出相位中，不搜尋（只搜尋入相位）", indeterminate_relative_station: "相對速度為零，未搜尋",
});
const PERFECTION_STATUS_ZH = Object.freeze({
  not_requested: "未請求推算", not_applying: "非入相位，未搜尋", no_motion_model: "無運動模型，未搜尋",
  no_orb_verdict_nearest_only: "無容許度判定，未搜尋", outside_effective_orb: "不在容許度內，未搜尋",
  source_unavailable: "星曆範圍不足，無法搜尋", searched_no_root: "搜尋過但區間內沒有找到交會", found: "已找到",
});

const DECLINATION_ASPECT_ZH = Object.freeze({ parallel: "平行 parallel", contra_parallel: "反平行 contra-parallel" });
const ELEMENT_ZH = Object.freeze({ fire: "火象", earth: "土象", air: "風象", water: "水象" });
// essential_dignities.py _decan_reading 的閉集。
const DECAN_READING_ZH = Object.freeze({ transmitted_text: "傳本", editorial_correction: "編者校正" });

// 出生時間不精確時，事件模組在區間兩端與代表性時刻各算一次，三個結果並列、不合併。上方各表是代表性時刻的結果；這裡把三
// 個取樣並列。後端在兩端只寫出與代表性時刻不同的子結果，省略的鍵列在 same_as_anchor／events_same_as_anchor（缺鍵＝與代
// 表性時刻相同，不是缺資料）；代表性時刻的取樣指向模組頂層（result_location=module_top_level）。
const SAMPLE_ROLES = Object.freeze([["interval_start", "區間起點"], ["representative_anchor", "代表性時刻"], ["interval_end", "區間終點"]]);
const SAMPLING_INTERVAL_ZH = Object.freeze({
  civil_day: "當地民用日（出生地日曆上的那一天，從午夜到午夜）", stated_civil_hour: "所填的那一小時",
});

/** 「全部並列」應有的那幾套：計算頁目錄（options-catalogue.js）這個選項的具名值，依目錄順序；不取自回應。 */
const ALL_PROFILE_OPTION = Object.freeze({
  bounds: "bounds_profile", face_decan: "decan_profile", triplicity: "triplicity_profile", dodecatemoria: "dodecatemoria_profile",
});
function catalogueProfiles(technique) {
  return Catalogue.BY_KEY[ALL_PROFILE_OPTION[technique]].values
    .map((item) => item.value).filter((value) => value !== null && value !== ALL_PROFILES);
}

// 全部並列：界、面、三分性各家對照。請求選「all」時，後端把本版每一套具名表都算一次（computed_profiles，依目錄順序），
// 每一套的結果與單獨選它時相同，不設主要那一套。這一區先放一張對照表：每顆星一列、每套一欄印出守護者，最後一欄「各家」
// 只比較這些印出來的字是否相同（只比字，不是方法判斷，回應裡沒有這個欄位）；各套的完整表接在後面。欄位一律照目錄順序，
// 不照幾家相同排序，也不印比數：相同的多不表示比較對。
const ALL_PROFILES = "all";

// 三分性的「並列比較」開關：是否執行只由 Dossier 的 option_states 說（不由主要那一套有沒有選推定）。
const TRIPLICITY_COMPARISON_OPTION = "triplicity_include_research_comparison";

/**
 * 並列比較的那幾套三分性表。Dossier 說比較執行了，回應的 research_comparison_profiles 就必須是目錄裡
 * 每一套三分性表（應有集合取自目錄）；沒執行就必須是空的。選了「全部並列」時各套本來就都在，不另列。
 */
function triplicityComparison(response, dignities, selected) {
  const listed = need(dignities, "essential_dignities", "research_comparison_profiles", "array");
  const state = optionState(response, TRIPLICITY_COMPARISON_OPTION);
  const ran = Boolean(state) && receiptStatus(state).state === "present";
  if (selected === ALL_PROFILES) return [];
  needExactly(listed, ran ? catalogueProfiles("triplicity") : [], "essential_dignities.research_comparison_profiles");
  return listed;
}
