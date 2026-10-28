// view-model：驗算區段、出生時刻敏感度與取樣摘要。驗算區段：軌跡、請求選項與輸出契約（只由完整回應建）。逐步計算軌跡是
// 主要內容，不是附錄：每一步的函式、輸入、旗標、結果與假設都攤開，預設就在頁面上。
function traceSection(response) {
  const trace = response.calculation_trace || [];
  if (!trace.length) { return absentSection("trace", "逐步計算軌跡", RING.VERIFICATION, "本次回應沒有軌跡。"); }
  const receipt = response.calculation_dossier.trace_receipt || {};
  return makeSection("trace", "逐步計算軌跡", RING.VERIFICATION, { state: "present" }, {
    notes: [
      `本次共 ${trace.length} 步。步數隨你勾選的模組而變，不是固定值。`,
      "整份可複製貼出去逐步對照；每一步都列出算式、輸入與結果。", receipt.python_json_serialization_sha256
        ? `序列化雜湊 ${receipt.python_json_serialization_sha256}` + "（對 Python 固定參數序列化的結果計算，不跨語言可攜，"
          + "只能偵測意外損壞，不證明來源，也不證明沒被刻意修改）" : null,
    ].filter(Boolean),
    tables: [{
      title: "軌跡", columns: ["#", "步驟", "算式", "輸入", "結果", "備註"],
      rows: trace.map((step, index) => [
        String(index + 1), step.title || DASH, step.formula || DASH, flattenPairs(step.inputs),
        flattenPairs(step.result), step.note || DASH,
      ]),
    }],
  });
}

function flattenPairs(value) {
  if (value === null || value === undefined) return DASH;
  if (!isRecord(value)) return String(value);
  const parts = Object.entries(value).map(([key, item]) => {
    const shown = isRecord(item) || Array.isArray(item) ? JSON.stringify(item) : String(item);
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
  if (!keys.length) { return absentSection("requested_options", "本次請求的選項", RING.VERIFICATION, "回應沒有回報請求的選項。"); }
  return makeSection("requested_options", "本次請求的選項", RING.VERIFICATION, { state: "present" }, {
    notes: [
      "這是後端回報的本次請求值，含你沒有明示送出、由後端帶入的預設；" + "某個模組是否實際計算，看該模組自己的狀態。",
      "拿這份表就能重現同一次計算，不必記得自己勾了什麼；程式要讀的選項代碼在 JSON 匯出的" + " source_response.requested_options。",
    ],
    tables: [{
      title: "請求的選項", columns: ["選項", "請求值"],
      rows: keys.sort().map((key) => [key, requested[key] === null ? "null（未選定）" : String(requested[key])]),
    }],
  });
}

function contractSection(response) {
  const contract = response.output_contract;
  const layers = contract.layers || {};
  return makeSection("contract", "輸出契約", RING.VERIFICATION, { state: "present" }, {
    notes: [
      `契約狀態：${presentClosedVocabulary(contract.status, CONTRACT_STATUS_ZH, "契約狀態")}。`,
      `相容性政策：${presentClosedVocabulary(contract.compatibility, CONTRACT_COMPATIBILITY_ZH, "相容性政策")}。`,
    ],
    tables: [{
      title: "三層的定義（後端原文）", columns: ["層", "定義"], rows: Object.entries(layers).map(([key, text_]) => [key, text_]),
    }],
  });
}

const SENSITIVITY_SEMANTICS_ZH = Object.freeze({
  representative_midpoint_not_exact_birth_time: "代表性時刻是取樣區間中點，不代表出生發生在第 30 分鐘。",
  representative_first_available_probe_not_exact_birth_time:
    "區間中點在這個時區不存在，因此代表性時刻採用本小時第一個可取樣時刻；它仍不是精確出生時刻。",
  local_noon_computational_anchor_not_birth_time: "代表性時刻是當地正午的計算錨點，不是出生時刻。",
  local_noon_or_first_existing_instant_after:
    "當地正午在這一天因時鐘變更而不存在，代表性時刻採用正午之後第一個真實存在的時刻作為計算錨點；它不是出生時刻。",
  discrete_probes_not_continuous_hour_proof: "取樣點是每 15 分鐘一點；這一小時內若有時鐘變更，另加變更前後各一秒。"
    + "它們能找出取樣到的變動，但不能證明取樣點之間每一刻都相同。",
  hourly_local_clock_samples_plus_day_end_not_continuous_extrema_proof:
    "取樣點是當天每個存在的整點（重複的整點兩次都取）、當天每一段的第一秒與最後一秒，"
    + "以及每次時鐘變更前後落在當天的各一秒。它們能找出取樣到的星座變動，但不能證明取樣點之間每一刻都相同。",
});
const SKIP_REASON_ZH = Object.freeze({
  local_time_nonexistent: "時鐘沒有經過這一刻", house_system_unavailable_at_sample: "這一刻所選宮位制算不出宮頭",
});
// 後端標出的評估限制：取樣點在這種情形下界不住結果，受影響的路徑只算部分比較。
const EVALUATION_LIMIT_ZH = Object.freeze({
  polar_ascendant_can_reverse_between_samples: "出生地在極圈內，上升點可能在兩個取樣時刻之間翻轉半個黃道再回來，"
    + "取樣點與細分時刻都可能漏掉其間的星座與宮位",
  ascendant_moved_past_whole_signs_or_houses_between_samples:
    "出生地接近極圈，上升點可能在兩個取樣時刻之間連跳幾個星座，" + "取樣點與細分時刻都可能漏掉其間的星座與宮位",
  sect_differs_between_samples_dignities_read_at_representative_only:
    "這一小時內有日出或日落，日夜盤會翻轉；尊貴表（三分性主星、迦勒底界、外來）只依代表性時刻的日夜盤判定，"
    + "這一小時裡另一段時間屬於另一個日夜盤",
});

function sensitivityNotes(sensitivity) {
  const presentSensitivityText = (value) => presentClosedVocabulary(value, SENSITIVITY_SEMANTICS_ZH, "語意");
  const notes = [
    `取樣區間：${sensitivity.interval_start_local || DASH} 至 ` + `${sensitivity.interval_end_exclusive_local || DASH}（不含結尾）。`,
  ];
  // 只知時辰有三種讀法，後端只採一種，畫面要說是哪一種。
  if (sensitivity.precision === "approximate_hour") {
    notes.push(
      "「只知道約略小時」在這裡的意思是出生在這個鐘點之內（例如 14:00:00 到 14:59:59），"
      + "不是「整點前後半小時」，也不是「四捨五入到最近的整點」。"
    );
  }
  notes.push(
    `代表性時刻：${sensitivity.representative_local_time || DASH}，` + presentSensitivityText(sensitivity.representative_semantics)
  );
  if (sensitivity.sampling_semantics) { notes.push(presentSensitivityText(sensitivity.sampling_semantics)); }
  // 取樣一致不等於結果穩定，也沒有任何不變式補上取樣點之間。
  notes.push(
    "「各取樣點分類相同」只表示在列出的取樣點分類一致，不代表結果穩定：兩個取樣點之間"
    + "仍可能變了又變回，本系統沒有用任何推論排除這種情形。黃經、四軸與宮頭的數值在區間內" + "本來就會移動，另以範圍列出。"
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
      "未取樣的時刻：" + skipped
        .map((item) => `第 ${item.offset_seconds} 秒（` + `${presentClosedVocabulary(item.reason_code, SKIP_REASON_ZH, "原因")}）`)
        .join("、") + "。"
    );
  }
  const schedule = sensitivity.precision === "date_only" && isRecord(sensitivity.sample_schedule) ? sensitivity.sample_schedule : null;
  if (schedule && Array.isArray(schedule.utc_offset_changes) && schedule.utc_offset_changes.length) {
    notes.push(
      `這一天時鐘變更 ${schedule.utc_offset_changes.length} 次` + `（UTC ${schedule.utc_offset_changes.join("、")}），變更前後各取一秒。`
    );
  }
  if (schedule && Array.isArray(schedule.absent_hourly_labels) && schedule.absent_hourly_labels.length) {
    notes.push(`這些整點在這個時區當天不存在，沒有取樣：${schedule.absent_hourly_labels.join("、")}。`);
  }
  return notes;
}

function sensitivityTables(response, sensitivity) {
  // 每一種精度回的形狀不同，各自承接：落成空表讀起來像「沒有東西變動」，正好把後端的話反過來說。
  const tables = [];
  const bodyNames = {
    ...extendedLotNames(response),
    ...Object.fromEntries(
      (sensitivity.body_signs || []).concat(sensitivity.position_ranges || [])
        .filter((item) => item && item.key && item.name).map((item) => [item.key, item.name])
    ),
  };
  const ranges = sensitivity.position_ranges || [];
  if (ranges.length) {
    tables.push({
      title: "位置範圍", columns: ["天體", "代表性黃經（度）", "取樣點出現的星座數", "取樣狀態"], collapse: ["取樣狀態"],
      rows: ranges.map((range) => [
        range.name || range.key, longitudeText(range.representative_sign_position),
        String((range.sampled_sign_indices || []).length), samplingStatus(range.status),
      ]),
    });
  }
  const bodySigns = sensitivity.body_signs || [];
  if (bodySigns.length) {
    tables.push({
      title: "星座落點", columns: ["天體", "代表性星座", "取樣點出現的星座數", "取樣狀態"], collapse: ["取樣狀態"],
      rows: bodySigns.map((item) => [
        item.name || item.key, item.representative_sign_index === null ? DASH : SIGNS[item.representative_sign_index],
        String((item.sampled_sign_indices || []).length), samplingStatus(item.status),
      ]),
    });
  }
  const placements = sensitivity.planet_in_house || [];
  if (placements.length) {
    tables.push({
      title: "落宮", columns: ["天體", "代表性宮位", "取樣點出現的宮位數", "取樣狀態"], collapse: ["取樣狀態"],
      rows: placements.map((item) => [
        item.name || item.key, item.representative_house === null || item.representative_house === undefined ? DASH
          : String(item.representative_house), String((item.sampled_houses || []).length), samplingStatus(item.status),
      ]),
    });
  }
  const ledger = (response.calculation_dossier.birth_time || {}).sensitivity_coverage;
  const summaryRows = [];
  const angles = isRecord(sensitivity.angles) ? sensitivity.angles : {};
  Object.keys(ANGLE_ZH).forEach((key) => {
    if (isRecord(angles[key])) { summaryRows.push([`${ANGLE_ZH[key]}的星座`, samplingStatus(angles[key].status)]); }
  });
  const cusps = Array.isArray(sensitivity.house_cusps) ? sensitivity.house_cusps : [];
  if (cusps.length && isRecord(ledger)) {
    const differing = cusps.filter((cusp) => isRecord(cusp) && cusp.status === "differs_between_samples").map((cusp) => cusp.house);
    summaryRows.push([
      "宮頭的星座", samplingStatus(ledger["derived_methods.house_division"])
        + (differing.length ? `（第 ${differing.join("、")} 宮）` : ""),
    ]);
  }
  if (isRecord(sensitivity.sect)) { summaryRows.push(["日夜區分", samplingStatus(sensitivity.sect.status)]); }
  if (isRecord(sensitivity.lots)) {
    Object.keys(LOT_ZH).forEach((key) => {
      if (isRecord(sensitivity.lots[key])) {
        summaryRows.push([`${LOT_ZH[key]}的星座`, samplingStatus(sensitivity.lots[key].status)]);
        if (sensitivity.lots[key].house_status) {
          summaryRows.push([`${LOT_ZH[key]}的落宮`, samplingStatus(sensitivity.lots[key].house_status)]);
        }
      }
    });
    if (sensitivity.lots.discontinuity === "sect_flip") { summaryRows.push(["阿拉伯點的公式", "取樣時刻之間換了日夜盤公式"]); }
  }
  if (isRecord(sensitivity.void_of_course)) { summaryRows.push(["是否月空亡", samplingStatus(sensitivity.void_of_course.status)]); }
  if (summaryRows.length) { tables.push({ title: "其他判定的取樣狀態", columns: ["判定", "取樣狀態"], rows: summaryRows }); }
  // 每一條可評估路徑一個狀態，由後端帳本決定；未請求、只算了代表性時刻、只比較一部分，三者分開寫。
  if (isRecord(ledger)) {
    tables.push({
      title: "各模組的取樣涵蓋", columns: ["模組", "狀態"],
      rows: Object.entries(ledger).map(([path, state]) => [
        SENSITIVITY_LEDGER_ZH[path] || modulePathLabel(path, bodyNames), samplingStatus(state),
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
      "出生時刻標記為精確到分鐘，因此沒有進行區間取樣。" + "若你其實只記得大約時辰，改選較寬的把握度，這裡會列出哪些判定會跟著改變。",
    ], []);
  }
  // 模組狀態沿用事件模組的詞彙：不是 computed，就沒有任何取樣結果可列，不能落成一張看起來「什麼都沒變」的空表。
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

/* 出生時間敏感度：讀之前整份核對。
   敏感度區、結果頂端的摘要、落宮與十二分部的取樣記號都讀 birth_time_sensitivity。先在這裡
   一次核對每一種精度的形狀與每張逐列表應有的列，各處讀值時就不必、也不准再補預設。
   應有的列取自目錄、其他模組與 calculation_dossier 的取樣帳本（birth_time.sensitivity_coverage），
   不取自敏感度本身。取樣點之間的改變（transitions）與評估限制的筆數本身就是答案，沒有應有集合。 */
const COMPARED_STATES = Object.freeze(["same_at_all_samples", "differs_between_samples", "partially_evaluated"]);
// 後端 PROBE_OFFSETS_SECONDS：這一小時第 0、15、30、45 分與最後一秒；時鐘變更另加的點不在這裡。
const PROBE_OFFSETS_SECONDS = Object.freeze([0, 900, 1800, 2700, 3599]);
const SENSITIVITY_PRECISIONS = Object.freeze(["exact", "approximate_hour", "date_only"]);

function hourOffsetKey(start, seconds) {
  const base = localKey(`${start}:00`.slice(0, 19)) || localKey(start);
  if (!base) return null;
  const [date, clock] = base.split("T");
  const [hour, minute] = clock.split(":").map(Number);
  const total = minute * 60 + seconds;
  return `${date}T${pad2(hour)}:${pad2(Math.floor(total / 60))}:${pad2(total % 60)}`;
}

/** 這條路徑在取樣時刻比較過嗎（取樣完成、而且帳本這麼說）；checkSensitivity 核過形狀後才可用。 */
function sensitivityCompared(response, path) {
  const sensitivity = response.birth_time_sensitivity;
  if (sensitivity.precision === "exact" || sensitivity.status !== "computed") return false;
  return COMPARED_STATES.includes(response.calculation_dossier.birth_time.sensitivity_coverage[path]);
}

function checkSensitivity(response) {
  const s = needAt(response.birth_time_sensitivity, "birth_time_sensitivity");
  const precision = s("precision", "string");
  if (!SENSITIVITY_PRECISIONS.includes(precision)) {
    throw exportPipeline.incompleteResponse(`birth_time_sensitivity.precision 不是已知的值：${precision}`);
  }
  if (precision === "exact") return;
  if (s("status", "string") !== "computed") { s("reason_code", "string?"); return; }
  ["interval_start_local", "interval_end_exclusive_local", "representative_local_time",
    "representative_semantics", "sampling_semantics", "classification_status"].forEach((key) => s(key, "string"));
  s.rows("evaluation_limits").forEach((limit) => { limit("reason_code", "string"); limit("affected_paths", "array"); });
  const ledger = need(need(response.calculation_dossier, "calculation_dossier", "birth_time", "record"),
    "calculation_dossier.birth_time", "sensitivity_coverage", "record");
  const compared = (path) => COMPARED_STATES.includes(ledger[path]);
  // 帳本說比較過的每一條路徑，都要有它的分類比較結果；沒比較的不得出現。
  const coverage = s.in("classification_coverage");
  needExactly(Object.keys(coverage.record).sort(), Object.keys(ledger).filter(compared).sort(), coverage.path);
  Object.keys(coverage.record).forEach((path) => coverage.in(path)("differing_classifications", "array"));
  const keysOf = (rows, expected, path, field = "key") => needExactly(rows.map((row) => row(field, "string")), expected, path);
  const signRows = (rows) => rows.forEach((row) => { row("sampled_sign_indices", "array"); row("status", "string"); });
  if (compared("derived_methods.dodecatemoria")) {
    const points = need(response.derived_methods.dodecatemoria, "dodecatemoria", "points", "records");
    const rows = s.rows("dodecatemoria_signs");
    keysOf(rows, points.map((point) => point.key), "birth_time_sensitivity.dodecatemoria_signs");
    signRows(rows);
  }
  const bodyKeys = expectedBodyKeys(response);
  if (precision === "approximate_hour") {
    const probes = s.rows("probes");
    const coverageOfProbes = s.in("probe_coverage");
    coverageOfProbes("refinement_offsets_seconds", "array");
    const skipped = coverageOfProbes.rows("skipped").map((item) => {
      item("reason_code", "string");
      return item("offset_seconds", "number");
    });
    const seen = new Set(probes.map((probe) => { probe("fold", "number"); return localKey(probe("input_local_time", "string")); }));
    const start = s("interval_start_local");
    // 這一小時固定的五個取樣點，除了後端說沒取樣的，每一個都要在。
    if (PROBE_OFFSETS_SECONDS.some((offset) => !skipped.includes(offset) && !seen.has(hourOffsetKey(start, offset)))) {
      throw exportPipeline.incompleteResponse("birth_time_sensitivity.probes 少了固定的取樣點");
    }
    s.rows("transitions").forEach((item) => {
      item("lower_bound_local", "string");
      item("upper_bound_local", "string");
      item("changed_paths", "array");
      item("resolution_seconds", "number");
    });
    const bodySigns = s.rows("body_signs");
    keysOf(bodySigns, bodyKeys, "birth_time_sensitivity.body_signs");
    bodySigns.forEach((row) => { row("name", "string"); row("representative_sign_index", "number?"); });
    signRows(bodySigns);
    const placements = s.rows("planet_in_house");
    // 落宮列只帶名稱（頁面投影）：應有的名稱是天體目錄裡這幾顆的名稱。
    keysOf(placements, compared("derived_methods.planet_in_house")
      ? bodyKeys.map((key) => Labels.VOCABULARIES.body_backend_name[key]) : [],
    "birth_time_sensitivity.planet_in_house", "name");
    placements.forEach((row) => { row("representative_house", "number?"); row("sampled_houses", "array"); row("status", "string"); });
    const cusps = s.rows("house_cusps");
    if (compared("derived_methods.house_division")) {
      const angles = s.in("angles");
      needExactly(Object.keys(angles.record).sort(), [...ANGLE_ORDER].sort(), angles.path);
      ANGLE_ORDER.forEach((key) => angles.in(key)("status", "string"));
      angles.in("asc")("sampled_sign_indices", "array");
      needExactly(cusps.map((cusp) => cusp("house", "number")), CLASSICAL_PLACE_NUMBERS, "birth_time_sensitivity.house_cusps");
      cusps.forEach((cusp) => {
        const status = cusp("status", "string");
        // 象限制的第 1／4／7／10 宮宮頭就是四軸本身：後端只寫「同上升」等，不再抄一份範圍；
        // 指向的軸點與狀態必須對得上，否則是殘缺。
        const angle = cusp("same_as_angle", "string?");
        if (angle !== null && (!ANGLE_ORDER.includes(angle) || angles.in(angle)("status", "string") !== status)) {
          throw exportPipeline.incompleteResponse(`${cusp.path}.same_as_angle：${angle} 不是狀態相同的軸點`);
        }
      });
    } else if (cusps.length) { throw exportPipeline.incompleteResponse("birth_time_sensitivity.house_cusps：宮位沒有比較，卻有宮頭"); }
    // 日夜區分、阿拉伯點與月空亡：帳本說比較過才有摘要，沒比較時是 null。
    [["sect", "derived_methods.sect"], ["lots", "derived_methods.lots"],
      ["void_of_course", "derived_methods.void_of_course"]].forEach(([key, path]) => {
      const summary = s.in(key, !compared(path));
      if (!compared(path)) {
        if (summary !== null) throw exportPipeline.incompleteResponse(`birth_time_sensitivity.${key}：沒有比較，應為 null`);
        return;
      }
      if (key !== "lots") { summary("status", "string"); return; }
      summary("discontinuity", "string");
      Object.keys(LOT_ZH).forEach((lot) => { summary.in(lot)("status", "string"); summary.in(lot)("house_status", "string"); });
    });
  } else {
    const samples = s.rows("samples");
    const schedule = s.in("sample_schedule");
    schedule("utc_offset_changes", "array");
    const absent = schedule("absent_hourly_labels", "array").map(localKey);
    const seen = new Set(samples.map((sample) => { sample("fold", "number"); return localKey(sample("local_time", "string")); }));
    // 這一天每一個存在的整點都取樣；沒有時鐘變更的一天，最後一秒也取。
    const day = localKey(s("interval_start_local")).split("T")[0];
    const hourly = Array.from({ length: 24 }, (_value, hour) => `${day}T${String(hour).padStart(2, "0")}:00:00`)
      .filter((key) => !absent.includes(key));
    const expected = hourly.concat(schedule("utc_offset_changes").length ? [] : [`${day}T23:59:59`]);
    if (expected.some((key) => !seen.has(key))) {
      throw exportPipeline.incompleteResponse("birth_time_sensitivity.samples 少了應有的整點或當天最後一秒");
    }
    const ranges = s.rows("position_ranges");
    keysOf(ranges, [...bodyKeys, ...expectedNodeKeys(response)].sort(), "birth_time_sensitivity.position_ranges");
    ranges.forEach((row) => { row("name", "string"); row.position("representative_sign_position", true); });
    signRows(ranges);
    // 月亮一天最多換一兩個星座、不會換回來：取樣看到幾個星座，跨界就是幾減一次。
    const moon = ranges.find((row) => row("key") === "moon");
    const crossings = s.in("moon_boundary_assessment").rows("sampled_sign_boundary_transitions");
    crossings.forEach((item) => {
      item("lower_sample_local", "string");
      item("upper_sample_local", "string");
      item("semantics", "string");
    });
    if (crossings.length !== moon("sampled_sign_indices").length - 1) {
      throw exportPipeline.incompleteResponse("birth_time_sensitivity.moon_boundary_assessment 的跨界次數與月亮取樣到的星座數對不上");
    }
  }
}

// 取樣摘要：敏感度區的第一行永遠是結論，不摺疊；下面是不可操作的取樣點標記：每個實際取樣的時刻一個獨立的點，點數取自回
// 應（通常五個，時鐘變更或日期模式會不同），點與點之間不畫連續填滿的條，因為那裡沒有計算。改變的時刻畫成一段「帶」並標
// 出解析度，不寫成單一時刻；「取樣點之間改變」「分類相同」「只比較一部分」「沒有比較」四組分開列，讓「查過而且會變」與
// 「根本沒查」分得開。
//
// 措辭：「這五個取樣點分類相同」，不用「穩定」——相同只說取樣點一致，不說取樣點之間也一致。
//
// 與後端 TRANSITION_RESOLUTION_SECONDS 同值；tests/integration/ test_frontend_contract.py 直接比對兩處，改一邊另一邊的
// 測試就紅。
const TRANSITION_RESOLUTION_LIMIT_SECONDS = 15;
// 日期模式月亮換星座的兩個取樣點：同一段之內，或分屬兩段、中間隔著時鐘標為別的日期的時間。
const MOON_TRANSITION_RESOLUTION = Object.freeze({
  crossing_exists_between_adjacent_samples_exact_time_not_solved: "兩個相鄰取樣點之間，未再細分",
  crossing_exists_between_adjacent_samples_across_another_date_exact_time_not_solved: "兩個取樣點之間隔著屬於另一個日期的時間，未再細分",
});
// transitions[].semantics 的第二個值（backend TRANSITION_SEMANTICS）：跨過時鐘撥回、沒有細分的改變。
const TRANSITION_ACROSS_UTC_GAP = "sampled_classification_change_across_a_utc_gap_not_bisected";
const COUNT_ZH = ["零", "一", "兩", "三", "四", "五", "六", "七", "八", "九", "十"];
function sampleCountWord(count) { return count >= 0 && count < COUNT_ZH.length ? COUNT_ZH[count] : ` ${count} `; }
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
  "astronomical_data.bodies": "天體的星座與行進方向", "astronomical_data.nodes": "月交點的星座與行進方向",
  "astronomical_data.angles": "四軸的星座", "derived_methods.house_division": "宮頭的星座",
  "derived_methods.planet_in_house": "行星落宮", "derived_methods.sect": "日夜區分（含近地平帶）",
  "derived_methods.lots": "阿拉伯點的星座、落宮與公式", "derived_methods.void_of_course": "是否月空亡",
  "derived_methods.dodecatemoria": "十二分部的星座與守護行星",
});
const PARTIAL_GROUP_ZH = Object.freeze({
  "derived_methods.void_of_course": "月空亡：只比較了「是否月空亡」一項；出宮時刻、下一個將形成的相位與它的時刻都沒有重算",
});
const ANGLE_ZH = Object.freeze({ asc: "上升", mc: "中天", desc: "下降", ic: "天底" });
const ANGLE_ORDER = Object.freeze(Object.keys(ANGLE_ZH));
const LOT_ZH = Labels.VOCABULARIES.lot;

// 後端分類路徑 → 畫面上的一類（路徑寫法見 birth_time_sensitivity.printed_classifications）。
// 成員（天體、角點、宮序、點）合併成一句，例如「上升、下降的星座」。畫面上一律是白話中文：
// 認不得的欄位落到「所屬模組：其他附帶項目」，不印方括號、點號或英文鍵名。
const MEMBER = "\\[([^\\]:]+)(?::[^\\]]*)?\\]";
// 模組附帶的說明欄位（方法名、出處、名稱、語意說明、範圍、時期與名稱來源）：不是計算結果，只會隨模組有無一起變。
const MODULE_NOTE_KEYS = [
  "method", "method_status", "period", "name_status", "method_provenance", "source", "source_ref",
  "source_verification", "lot_method_id", "display_name_key", "points_profile", "computed_profiles",
  "altitude_center", "altitude_sun_position", "system_code", "system_name", "angles_source", "house_system_code", "house_system_name",
  "interval_semantics", "distance_to_nearest_cusp_semantics", "formula", "formula_profile", "formula_bases",
  "boundary_policy", "near_horizon_band", "display_center", "endpoint_rule", "lord_rule", "profile",
  "semantics", "scope", "time_basis", "solver", "solver_status",
].join("|");
const OWNER_PATTERN = "astronomical_data\\.(?:angles|bodies|nodes)|derived_methods\\."
  + "(?:house_division|planet_in_house|sect|lots|void_of_course|dodecatemoria)";
// 十二分部的列：主表（points）與每一種算法自己的列（profile_results.<算法>.points，全部並列時兩種）。
const TWELFTH_ROWS = "(?:points|profile_results\\.[a-z0-9_]+\\.points)";
// 延伸阿拉伯點的列沒有 key，後端以列序命名（lots[3]）；成員寫成 extended_lot:3，名稱由回應的
// lot_method_id 經 labels.js 的 EXTENDED_LOT_NAMES 查（extendedLotNames）。
const EXTENDED_LOTS = "derived_methods\\.lots\\.extended_lots";
const EXTENDED_LOT_MEMBER = "extended_lot:";
const extendedLot = (index) => `${EXTENDED_LOT_MEMBER}${index}`;
const CLASSIFICATION_KINDS = [
  [/^astronomical_data\.angles\.sign_positions\.(\w+)$/, "angles"],
  [/^derived_methods\.house_division\.cusp_sign_positions\[(\d+)\]$/, "house_cusps"],
  [new RegExp(`^astronomical_data\\.(?:bodies|nodes)${MEMBER}\\.sign_position$`), "body_signs"],
  [new RegExp(`^astronomical_data\\.(?:bodies|nodes)${MEMBER}\\.motion_sign$`), "motion"],
  [new RegExp(`^derived_methods\\.planet_in_house\\.(?:point_placements\\.)?placements${MEMBER}\\.(?:house|key|name)$`), "planet_in_house"],
  [new RegExp(`^derived_methods\\.planet_in_house\\.(?:point_placements\\.)?placements${MEMBER}\\.on_cusp$`), "on_cusp"],
  [/^derived_methods\.lots\.sign_positions\.(fortune|spirit)$/, "lot_signs"],
  [/^derived_methods\.lots\.house_placement\.(fortune|spirit)$/, "lot_houses"], [/^derived_methods\.lots\.by_sect\./, "lot_comparison"],
  [/^derived_methods\.lots\.(?:formula_basis|sect_applied|sect_status|sect_in_near_horizon_band|sect_named_boundary_disagreement)$/, "lot_formula"],
  [new RegExp(`^${EXTENDED_LOTS}\\.lots\\[(\\d+)\\]\\.(?:sign|sign_position)$`), "lot_signs", extendedLot],
  [new RegExp(`^${EXTENDED_LOTS}\\.lots\\[(\\d+)\\]\\.house$`), "lot_houses", extendedLot],
  [new RegExp(`^${EXTENDED_LOTS}\\.lots\\[\\d+\\]\\.(?:by_sect\\.|same_value_both_candidates$)`), "lot_comparison"],
  [new RegExp(`^${EXTENDED_LOTS}\\.(?:sect_applied|sect_status|lots\\[\\d+\\]\\.sect_applied)$`), "lot_formula"],
  [new RegExp(`^${EXTENDED_LOTS}\\.lots\\[\\d+\\]\\.(?:${MODULE_NOTE_KEYS})$`), "module_note", () => "derived_methods.lots"],
  [/^derived_methods\.sect\.(?:is_day|sect_status|sect_statuses\[\d+\]|in_near_horizon_band|named_boundary_disagreement)$/, "sect"],
  [/^derived_methods\.void_of_course\.(?:is_void_of_course|verdict)$/, "void_of_course"],
  [/^derived_methods\.void_of_course\.all_candidates\[\d+\]\./, "void_of_course_candidates"],
  // 一列的身分欄位（key、name、category）只隨那一列出現或消失而變，與那一列的星座一起寫。
  [new RegExp(`^derived_methods\\.dodecatemoria\\.${TWELFTH_ROWS}${MEMBER}\\.(?:sign|sign_position|point_sign_position|key|name|category)$`), "dodecatemoria_signs"],
  [new RegExp(`^derived_methods\\.dodecatemoria\\.${TWELFTH_ROWS}${MEMBER}\\.domicile_lord$`), "dodecatemoria_lords"],
  [new RegExp(`^derived_methods\\.dodecatemoria\\.${TWELFTH_ROWS}${MEMBER}\\.(?:comparison_sign|sign_differs_under_other_sect)$`), "dodecatemoria_comparison"],
  [new RegExp(`^astronomical_data\\.(?:bodies|nodes)${MEMBER}\\.(altitude_apparent|apparent_magnitude|azimuth|phenomena)_reason_code$`), "body_reason"],
  // 模組本身在某些取樣點算不出來（例：那一刻所選宮位制沒有宮頭）時，模組的收據欄位跟著不同。
  [new RegExp(`^(${OWNER_PATTERN})\\.(?:applicable|available|executed|requested|reason_code|execution_status|availability\\.\\w+|point_placements\\.(?:execution_status|reason_code|rule))$`), "module_state"],
  // 同一時候，模組附帶的方法說明（方法名、出處、宮位制名稱）也會從有變沒有。
  // 說明欄位可以在模組的子物件裡（lots.house_placement.method、dodecatemoria.profile_results.<算法>.formula）。
  [new RegExp(`^(${OWNER_PATTERN})\\.(?:[a-z0-9_]+\\.)*(?:${MODULE_NOTE_KEYS})(?:[.[]|$)`), "module_note"],
];
const SINGLE_CLASSIFICATION_ZH = Object.freeze({
  lot_comparison: "阿拉伯點另一套公式（日盤／夜盤）的比較值", lot_formula: "阿拉伯點採用日盤還是夜盤公式",
  sect: "日夜區分（日盤或夜盤）", void_of_course: "是否月空亡", void_of_course_candidates: "月空亡判定時看的下一個完成相位",
});
// 認不得的欄位所屬的模組：只寫模組，不寫欄位鍵名。
const PATH_OWNER_ZH = Object.freeze({
  "astronomical_data.bodies": "天體位置", "astronomical_data.nodes": "月交點", "astronomical_data.angles": "四軸",
  "derived_methods.house_division": "宮位", "derived_methods.planet_in_house": "落宮",
  "derived_methods.sect": "日夜區分", "derived_methods.lots": "阿拉伯點", "derived_methods.void_of_course": "月空亡",
  "derived_methods.dodecatemoria": "十二分部",
});
// 天體在某些取樣點算得出、某些算不出的附帶量（例：月亮在地平線下時沒有視星等）。
const BODY_REASON_ZH = Object.freeze({
  altitude_apparent: "視地平高度", apparent_magnitude: "亮度（視星等）", azimuth: "方位角", phenomena: "亮面比例與離太陽的角距",
});
function classificationKind(path) {
  for (const [pattern, kind, toMember] of CLASSIFICATION_KINDS) {
    const match = pattern.exec(String(path));
    if (!match) continue;
    if (kind === "body_reason") return { kind: `body_reason_${match[2]}`, member: match[1] };
    return { kind, member: toMember ? toMember(match[1]) : match[1] };
  }
  return null;
}
/** 阿拉伯點的列法與 Lots 表相同：命運點、精神點，再依延伸點的列序。 */
function lotOrder(member) {
  const text = String(member);
  if (text.startsWith(EXTENDED_LOT_MEMBER)) return 2 + Number(text.slice(EXTENDED_LOT_MEMBER.length));
  return text === "fortune" ? 0 : text === "spirit" ? 1 : Number.MAX_SAFE_INTEGER;
}
const byLotOrder = (a, b) => lotOrder(a) - lotOrder(b);
function extendedLotNames(response) {
  const lots = ((((response || {}).derived_methods || {}).lots || {}).extended_lots || {}).lots;
  return Object.fromEntries((Array.isArray(lots) ? lots : []).map((lot, index) => [
    extendedLot(index), Labels.closedLabel(isRecord(lot) ? lot.lot_method_id : null, Labels.VOCABULARIES.extended_lot, "阿拉伯點"),
  ]));
}
/** 成員鍵 → 中文名：回應自己帶的名稱優先，其次是後端名稱表、角點與阿拉伯點；都沒有就寫「另一個點」。 */
function memberName(member, names) {
  const vocabulary = Labels.VOCABULARIES;
  return (names && names[member]) || vocabulary.body_backend_name[member] || vocabulary.node_backend_name[member]
    || vocabulary.lunar_apsis_backend_name[member] || ANGLE_ZH[member] || LOT_ZH[member]
    || (String(member).startsWith(EXTENDED_LOT_MEMBER) ? "另一個阿拉伯點" : "另一個點");
}
function otherClassificationLabel(path, names) {
  const text = String(path);
  const owner = /^[a-z_]+\.[a-z_]+/.exec(text);
  const ownerKey = owner ? owner[0] : "";
  const declared = PATH_OWNER_ZH[ownerKey] || (MODULE_COVERAGE[ownerKey] && MODULE_COVERAGE[ownerKey].zh);
  // 方括號裡不再有「[」：沒有收尾的「[」不會讓後面每一個「[」都掃到字串尾。
  const member = /\[([^[\]:]+)(?::[^[\]]*)?\]/.exec(text.slice(ownerKey.length));
  const who = member && !/^\d+$/.test(member[1]) ? `${memberName(member[1], names)}的` : "";
  return `${declared || "其他模組"}：${who}其他附帶項目`;
}

/** 十二分部同一點的星座、所在星座與守護行星合成一句，不分開列。 */
function changedPathGroups(paths, names) {
  const groups = new Map();
  const other = [];
  (paths || []).forEach((path) => {
    const found = classificationKind(path);
    if (!found) { other.push(otherClassificationLabel(path, names)); return; }
    if (!groups.has(found.kind)) groups.set(found.kind, []);
    if (found.member !== undefined && !groups.get(found.kind).includes(found.member)) { groups.get(found.kind).push(found.member); }
  });
  const named = (members) => members.map((member) => memberName(member, names)).join("、");
  const parts = [];
  const push = (kind, members, text) => parts.push({ kind, members, text });
  if (groups.has("angles")) {
    const members = groups.get("angles").slice().sort((a, b) => ANGLE_ORDER.indexOf(a) - ANGLE_ORDER.indexOf(b));
    push("angles", members, `${named(members)}的星座`);
  }
  if (groups.has("house_cusps")) {
    const houses = groups.get("house_cusps").map((index) => Number(index) + 1).sort((a, b) => a - b);
    push("house_cusps", houses.map(String), `第 ${houses.join("、")} 宮宮頭的星座`);
  }
  [
    ["body_signs", "的星座"], ["motion", "是順行還是逆行"], ["planet_in_house", "的落宮"],
    ["on_cusp", "是否壓在宮頭上"], ["lot_signs", "的星座"], ["lot_houses", "的落宮"],
  ].forEach(([kind, suffix]) => {
    if (!groups.has(kind)) return;
    const members = kind.startsWith("lot_") ? groups.get(kind).slice().sort(byLotOrder) : groups.get(kind);
    push(kind, members, `${named(members)}${suffix}`);
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
  Object.keys(SINGLE_CLASSIFICATION_ZH).forEach((kind) => { if (groups.has(kind)) push(kind, [], SINGLE_CLASSIFICATION_ZH[kind]); });
  [...new Set(other)].forEach((text) => push("other", [], text));
  return parts;
}

function changedPathsText(paths, names) { return changedPathGroups(paths, names).map((part) => part.text).join("；"); }

function samplingMarks(sensitivity) {
  if (sensitivity.precision === "approximate_hour") {
    return (Array.isArray(sensitivity.probes) ? sensitivity.probes : []).filter(isRecord)
      // fold 由後端逐點給出（PEP 495，1＝重複時刻的第二次）。部分重複的小時裡，
      // 重複區段外的取樣點只出現一次，不得一律依請求的 fold 標成第二次。
      .map((probe) => ({ key: localKey(probe.input_local_time), second_fold: probe.fold === 1 }));
  }
  if (sensitivity.precision === "date_only") {
    return (Array.isArray(sensitivity.samples) ? sensitivity.samples : []).filter(isRecord)
      .map((sample) => ({ key: localKey(sample.local_time), second_fold: sample.fold === 1 }));
  }
  return [];
}

/** 每一段改變：時間範圍、解析度與改了什麼。日期模式只有月亮跨界、且沒有細分。 */
function samplingBands(sensitivity, day, labels) {
  if (sensitivity.precision === "approximate_hour") {
    return (Array.isArray(sensitivity.transitions) ? sensitivity.transitions : []).filter(isRecord)
      .map((item) => {
        const seconds = Number(item.resolution_seconds);
        // 兩個取樣點分屬這一小時的兩段 UTC（時鐘離開這一小時又回來）：中間的時間不屬於這一小時，
        // 後端不細分，只報兩段相對的兩端。沒帶 semantics（page 投影）時照細分的一段寫。
        const gap = item.semantics === TRANSITION_ACROSS_UTC_GAP;
        return {
          lower: localKey(item.lower_bound_local), upper: localKey(item.upper_bound_local),
          paths: Array.isArray(item.changed_paths) ? item.changed_paths : [], gap, resolution: gap ? "時鐘在這兩刻之間撥回，未再細分"
            : Number.isFinite(seconds) && seconds <= TRANSITION_RESOLUTION_LIMIT_SECONDS
            ? `解析度 ≤${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒` : `解析度 ${Number.isFinite(seconds) ? seconds : DASH} 秒`,
        };
      })
      .map((band) => ({ ...band, range: `${clockLabel(band.lower, day)}–${clockLabel(band.upper, day)}`,
        text: changedPathsText(band.paths, labels.bodyNames) || DASH }));
  }
  const moon = isRecord(sensitivity.moon_boundary_assessment) ? sensitivity.moon_boundary_assessment : {};
  return (Array.isArray(moon.sampled_sign_boundary_transitions) ? moon.sampled_sign_boundary_transitions : []).filter(isRecord)
    .map((item) => {
      const lower = localKey(item.lower_sample_local);
      const upper = localKey(item.upper_sample_local);
      const paths = ["astronomical_data.bodies[moon].sign_position"];
      return {
        lower, upper, paths, range: `${clockLabel(lower, day)}–${clockLabel(upper, day)}`,
        resolution: MOON_TRANSITION_RESOLUTION[item.semantics] || DASH, text: changedPathsText(paths, labels.bodyNames),
      };
    });
}

function samplingFigure(sensitivity, ledger, labels) {
  const marks = samplingMarks(sensitivity).filter((mark) => mark.key);
  if (!marks.length) return null;
  const count = marks.length;
  const word = sampleCountWord(count);
  const day = localKey(sensitivity.interval_start_local) ? localKey(sensitivity.interval_start_local).split("T")[0]
    : marks[0].key.split("T")[0];
  const representativeKey = localKey(sensitivity.representative_local_time);
  const representativeIndex = marks.findIndex((mark) => mark.key === representativeKey);
  const markLabel = (mark) => clockLabel(mark.key, day) + (mark.second_fold ? "（第二次）" : "");
  const differing = differingClassificationPaths(sensitivity);
  const status = sensitivity.classification_status;
  let tone = "none";
  let lead = `這${word}個取樣點沒有可比較的分類。`;
  if (count < 2) { lead = "只取到一個取樣點，沒有可以互相比較的時刻。"; } else if (status === "same_at_all_samples") {
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
    + marks.map((mark, index) => markLabel(mark) + (index === representativeIndex ? "（代表性時刻）" : "")).join("、") + "。",
  ];
  bandsAfter.forEach((n, index) => {
    if (n) altParts.push(`${markLabel(marks[index])} 與 ${markLabel(marks[index + 1])} 之間有 ${n} 段改變。`);
  });
  const groups = [];
  const banded = new Set(bands.flatMap((band) => band.paths));
  const unbanded = differing.filter((path) => !banded.has(path));
  if (bands.length || differing.length) {
    const bisected = bands.filter((band) => !band.gap);
    const notes = sensitivity.precision === "date_only" ? ["日期模式只在取樣點比較，沒有細分改變的時刻。"]
      : [].concat(
        bisected.length
          ? ["每一段是改變發生的時間範圍，不是單一時刻；一段之內至少改變一次，不一定只有一次。"
            + `「解析度 ≤${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒」是說這段時間不超過 ${TRANSITION_RESOLUTION_LIMIT_SECONDS} 秒。`]
          : [], refined ? [`為了找出改變的時間，本站在取樣點之間另外加算了 ${refined} 個時刻。`] : [], bands.some((band) => band.gap)
          ? ["標「時鐘在這兩刻之間撥回」的一段：鐘面上這兩個時刻看起來相鄰，中間其實隔著一段不屬於這一小時的時間"
            + "（時鐘撥回，離開這一小時又回來）；改變發生在那段時間裡，沒有再細分。"]
          : []
      );
    groups.push({
      tone: "differs", title: "會變的：取樣點之間結果不同", note: notes.join(""),
      bands: bands.map(({ range, resolution, text }) => ({ range, resolution, text })),
      items: unbanded.length ? [changedPathsText(unbanded, labels.bodyNames)] : [],
    });
  }
  if (isRecord(ledger)) {
    const pathsIn = (state) => Object.keys(ledger).filter((path) => ledger[path] === state);
    const same = pathsIn("same_at_all_samples");
    if (same.length) {
      groups.push({
        tone: "same", title: `不變的：這${word}個取樣點分類相同`, note: "", bands: [],
        items: same.map((path) => SAME_GROUP_ZH[path] || labels.ledgerLabel(path)),
      });
    }
    const partial = pathsIn("partially_evaluated");
    if (partial.length) {
      groups.push({
        tone: "partial", title: "只比較了一部分", note: "", bands: [],
        items: partial.map((path) => PARTIAL_GROUP_ZH[path] || labels.ledgerLabel(path)),
      });
    }
    const unchecked = pathsIn("not_evaluated");
    if (unchecked.length) {
      groups.push({
        tone: "unchecked", title: "沒有比較：只算了代表性時刻（畫面上星盤用的那一刻）",
        note: "這些結果只對代表性時刻成立；在這段時間內會不會改變，沒有檢查。", bands: [], items: unchecked.map(labels.ledgerLabel),
      });
    }
  }
  return {
    kind: "sampling_marks", tone, lead,
    marks: marks.map((mark, index) => ({
      label: markLabel(mark), representative: index === representativeIndex, bands_after: bandsAfter[index],
      gap_label: bandsAfter[index] ? `${bandsAfter[index]} 段` : "",
    })),
    text_alternative: altParts.join(""),
    // legend 只描述圖形本身，文字輸出不印；note 是事實，每一種輸出都印。
    legend: representativeIndex >= 0 ? "空心點是代表性時刻。" : "", note: "點與點之間沒有計算。", groups,
  };
}

// 結果頂端：出生時間不確定時的白話摘要。只在出生時間是約略時辰或只有日期、而且取樣算完時出現；精確時刻與取樣被拒時為
// null。每一句都取自同一份回應（取樣點、改變的時間段、各模組的比較帳本、代表性時刻的星座），不推論、不解讀：「從 A 換到
// B」只在那一項恰好只有一段改變、取樣只見兩個值、而且代表性時刻在那一段之外時才寫——那時取樣點在那一段兩側各自只有一個
// 值。
const BIRTH_TIME_SUMMARY_TITLE = "出生時間不確定：哪些結果會變";
const SENSITIVITY_LEDGER_ZH = Object.freeze({ "astronomical_data.bodies": "天體位置" });

function sensitivityNames(sensitivity) {
  return Object.fromEntries(
    [].concat(sensitivity.body_signs || [], sensitivity.position_ranges || [])
      .filter((item) => isRecord(item) && item.key && item.name).map((item) => [item.key, item.name])
  );
}
function minuteOf(key) { return key ? key.split("T")[1].slice(0, 5) : DASH; }
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
  checkSensitivity(response);
  const sensitivity = response.birth_time_sensitivity;
  if (sensitivity.status !== "computed" || !["approximate_hour", "date_only"].includes(sensitivity.precision)) { return null; }
  const precision = sensitivity.precision;
  const marks = samplingMarks(sensitivity).filter((mark) => mark.key);
  if (!marks.length) return null;
  const count = marks.length;
  const day = localKey(sensitivity.interval_start_local) ? localKey(sensitivity.interval_start_local).split("T")[0]
    : marks[0].key.split("T")[0];
  const names = { ...extendedLotNames(response), ...sensitivityNames(sensitivity) };
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
  const whenByKind = new Map();
  bands.forEach((band) => {
    changedPathGroups(band.paths, names).forEach((part) => {
      const key = keyOf(part);
      if (!whenByKind.has(key)) whenByKind.set(key, []);
      const text = bandWhen(band, precision, day);
      if (!whenByKind.get(key).includes(text)) whenByKind.get(key).push(text);
    });
  });
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
      const pair = fromTo("angles", "asc", Array.isArray(printed) ? printed[0] : null, asc.sampled_sign_indices, sampledSignName);
      if (pair) found.push(`上升從${pair[0]}換到${pair[1]}`);
    }
    if (part.kind === "body_signs") {
      part.members.forEach((member) => {
        const row = [].concat(sensitivity.body_signs || [], sensitivity.position_ranges || [])
          .find((item) => isRecord(item) && item.key === member);
        if (!row) return;
        const representative = row.representative_sign_index !== undefined ? row.representative_sign_index
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
  const span = precision === "approximate_hour" ? `在 ${minuteOf(marks[0].key)}–${minuteOf(marks[count - 1].key)} 之間`
    : `在 ${day} 這一天裡`;
  let lead = `${span}，沒有可以互相比較的結果。`;
  if (count < 2) { lead = "只取到一個時刻，沒有可以互相比較的結果。"; } else if (status === "same_at_all_samples") {
    lead = `${span}，比較過的結果都一樣。`;
  } else if (status === "differs_between_samples") {
    lead = `${span}，有 ${changes.length} 類結果會變。`;
  }
  return {
    title: BIRTH_TIME_SUMMARY_TITLE, lead, intro, changes, same, partial, unchecked,
    caveat: "「不變」只表示取樣到的時刻結果相同，兩個取樣點之間仍可能變了又變回。"
      + (precision === "approximate_hour"
        ? "「約幾點改變」指的是一小段時間，這段之內至少變了一次。"
        : "日期模式只比較取樣點，沒有細算改變的時刻。"),
    link_text: "看細節", target_id: "section-sensitivity",
    // 結果最上方、每一章都看得到的一行，連到這個摘要。
    notice_text: "出生時間不確定，看哪些結果會變", notice_target_id: "sampling-callout",
  };
}

const CLASSICAL_PLACE_NUMBERS = Object.freeze(Array.from({ length: 12 }, (_value, index) => index + 1));
