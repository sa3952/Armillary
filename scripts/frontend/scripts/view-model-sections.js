// view-model：計算收據、速覽、回應 → sections、十二分部與古典分類。
// 計算收據。
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
          ["本地時間", clockTimeText(time.input_local_time)],
          ["時區", Labels.timezoneText(time.timezone_label)],
          // 新疆的地點由使用者指明出生紀錄用的鐘點；只在真的做了這個選擇時出現。
          ...((receipt.timezone || {}).civil_time_basis
            ? [["出生紀錄的鐘點", Labels.label("civil_time_basis", receipt.timezone.civil_time_basis)]]
            : []),
          ["UTC 偏移", utcOffsetText(time.utc_offset_hours)],
          // 後端逐字說明模糊時刻採用了哪一次、另一次是什麼：使用者才看得出盤是從兩個可能時刻裡挑的。只在真的模糊時出現。
          ...(time.dst_warning
            ? [["重複民用時刻的處置", time.dst_warning]]
            : []),
          [timeScaleLabel(time.time_scale_era), clockTimeText(time.utc_time)],
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

// 本命盤速覽：
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
    return `取樣到 ${names.join("、")}${SUMMARY_CHANGES}`;
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

// 回應 → sections：唯一一處把後端形狀翻成顯示投影的地方。
function buildSections(response) {
  if (!isRecord(response)) throw new Error("缺少可用的 backend response。");
  // 先確認版本與狀態權威；之後各區只讀，不再替缺席的權威猜狀態。
  exportPipeline.assertRenderableResponse(response);
  checkSensitivity(response);
  const angles = anglesSection(response);
  // 頁面投影（帶 projection 鍵）沒有軌跡、請求選項、輸出契約與完整收據。這四區只由完整回應
  // 建出；頁面文件不建，而不是以缺鍵推定「未請求」。
  const verification = Object.hasOwn(response, "projection") ? [] : [
    requestedOptionsSection(response),
    traceSection(response),
    contractSection(response),
    receiptSection(response),
  ];
  return displayFormat(collapseUniformColumns(withReasonLabels([
    // 速覽在最前面：剛算完的人先看到最常被問到的三個星座，細節在後面各區。
    summarySection(response, angles),
    timeSection(response),
    // 敏感度緊接在時間轉換之後：它限定後面每一區的成立範圍。匯出讀同一份清單，順序同步。
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
    dignityPeregrineSection(response),
    solarPhaseSection(response),
    motionStatesSection(response),
    dodecatemoriaSection(response),
    classicalClassificationsSection(response),
    ...verification,
  ])));
}

/* 表格的排字：畫面、「複製本區」與每一種匯出都讀這一份，不另在畫面改字。
   時刻：ISO 8601 的「T…Z」寫成「1987-11-22 06:39:26」，零毫秒不印；同一欄上一格已寫過同一天時
   只印時刻（「15:43:45」），日期換了才再寫。時間尺度寫在欄頭。驗算軌跡例外：它的欄頭與表題不寫
   時間尺度，格裡的時刻照原字（保留 Z），才看得出是世界時。相位方格的格不是時刻，不動。
   欄頭與表題的尺度標籤「世界時（UT1（舊協調世界時期間））」：括號裡再套括號難讀，寫成
   「世界時 UT1（舊協調世界時期間）」。「本次請求的選項」：選項鍵與閉集值寫表單上的中文名；
   沒有中文名的（數字、null）照原字。程式要讀的代碼在 JSON 匯出的 source_response.requested_options。 */
const ISO_INSTANT = /(\d{4}-\d\d-\d\d)T(\d\d:\d\d(?::\d\d)?)(?:\.0+(?=Z))?(\.\d+)?Z/g;
const DATED_CELL = /^(\d{4}-\d\d-\d\d) (?=\d\d:\d\d)/;
// 只試括號裡第一個 UT1：其餘的 UT1 不改變後面能不能接上內層括號，逐一回溯是二次方。
const NESTED_SCALE = /（((?:(?!UT1)[^（）])*UT1[^（）]*（[^（）]*）)）/g;
function displayHeading(text) {
  return typeof text === "string" ? text.replace(NESTED_SCALE, " $1") : text;
}
function displayInstants(text) {
  return text.replace(ISO_INSTANT, "$1 $2$3").replace(NESTED_SCALE, " $1");
}
function requestedOptionText(columnIndex, row) {
  const option = Catalogue.BY_KEY[row[0]];
  const raw = String(row[columnIndex] == null ? "" : row[columnIndex]);
  if (!option) return raw;
  if (columnIndex === 1 && raw === "null（未選定）") return "未選定";
  if (columnIndex === 0) return option.label_zh || raw;
  if (option.type === "boolean" && (raw === "true" || raw === "false")) return raw === "true" ? "是" : "否";
  if (option.type === "choice") {
    const value = (option.values || []).find((entry) => entry.value === raw);
    if (value && value.label_zh) return value.label_zh;
    if (row[0] === "house_system") {
      const zh = Labels.ownLabel(Labels.VOCABULARIES.house_system, raw);
      if (zh) return zh;
    }
  }
  return raw;
}
function displayRows(table, sectionId) {
  const rows = table.rows.map((row) => row.map((cell, index) => {
    if (sectionId === "requested_options" && index < 2) return requestedOptionText(index, row);
    if (sectionId === "trace" || typeof cell !== "string") return cell;
    return displayInstants(cell);
  }));
  table.columns.forEach((_column, index) => {
    if (index === 0) return;
    let previous = null;
    rows.forEach((row) => {
      const match = typeof row[index] === "string" ? DATED_CELL.exec(row[index]) : null;
      if (!match) { previous = null; return; }
      if (match[1] === previous) row[index] = row[index].slice(match[0].length);
      previous = match[1];
    });
  });
  return rows;
}
function displayFormat(sections) {
  return sections.map((section) => ({
    ...section,
    tables: section.tables.map((table) => ({
      ...table,
      ...(table.title ? { title: displayHeading(table.title) } : {}),
      columns: table.columns.map(displayHeading),
      rows: table.variant === "aspect_grid" ? table.rows : displayRows(table, section.id),
    })),
  }));
}

/* 整欄都一樣的狀態欄收成一句：
   有些表的狀態欄（「各家」「最近相位的完成時刻」「取樣狀態」…）在一張盤上常常每一列都是同一句，
   例如沒有請求推算時整欄是「未請求推算」。表格在 collapse 列出這類欄；某一欄每一列都相同時，
   把那一欄拿掉，改寫成一句表下註（TABLE_NOTE_PREFIX 開頭，進區段備註，四種匯出都帶）。只在每一格都
   相同時收；字一個不少。數值欄與名稱欄不列在 collapse，即使碰巧相同也不收。 */
const TABLE_NOTE_PREFIX = "表下註";
function tableNoteText(title, column, value) {
  return `${TABLE_NOTE_PREFIX}（${title}）：「${column}」一欄每一列都是「${value}」，所以不另列成一欄。`;
}
function tableNotesOf(table, section) {
  return section.notes.filter((note) => note.startsWith(`${TABLE_NOTE_PREFIX}（${table.title}）：`));
}
// 畫面上的表下註：匯出裡的表下註，加上被縮短的表頭原本說的話。
function screenTableNotes(table, section) {
  return tableNotesOf(table, section).concat(
    table.columns.filter((column) => SCREEN_COLUMNS[column]).map((column) => SCREEN_COLUMNS[column].note)
  );
}
function isTableNote(note, section) {
  return section.tables.some((table) => note.startsWith(`${TABLE_NOTE_PREFIX}（${table.title}）：`));
}
function collapseUniformColumns(sections) {
  return sections.map((section) => {
    const moved = [];
    const tables = section.tables.map((table) => {
      const { collapse, ...rest } = table;
      if (!collapse || table.rows.length < 2) return rest;
      const drop = collapse
        .map((column) => table.columns.indexOf(column))
        .filter((index) => index > 0 && new Set(table.rows.map((row) => row[index])).size === 1);
      if (!drop.length) return rest;
      drop.forEach((index) => moved.push(tableNoteText(table.title, table.columns[index], table.rows[0][index])));
      const keep = (_value, index) => !drop.includes(index);
      return { ...rest, columns: table.columns.filter(keep), rows: table.rows.map((row) => row.filter(keep)) };
    });
    return moved.length ? { ...section, notes: section.notes.concat(moved), tables } : { ...section, tables };
  });
}

// 十二分部。
// 第一層是白話：它是什麼、這次用哪一種算法、哪些點沒列與為什麼；古書出處放在 blocks，
// 畫面收進「出處」摺疊（SOURCE_FOLDED_SECTIONS），匯出照常逐條印出。
const DODECATEMORIA_TITLE = "十二分部 Dodecatemoria";
/** 區塊全是古書出處的區段：畫面把它們收進一個「出處」摺疊。 */
const SOURCE_FOLDED_SECTIONS = new Set([
  "dodecatemoria", "lunar_mansions", "solar_phase", "motion_states", "prenatal_points",
  "classical_classifications", "dignity_peregrine",
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
/** 取樣到的十二分部星座（sampled 是 checkSensitivity 核過的一列；沒有比較時是 undefined）。 */
function dodecatemoriaSampledSigns(sampled) {
  return sampled
    ? sampled.sampled_sign_indices.filter((index) => Number.isInteger(index) && index >= 0 && index < 12)
    : [];
}
function dodecatemoriaSampledMany(sampled) {
  return dodecatemoriaSampledSigns(sampled).length >= 2;
}

// 後端逐點說取樣比較做到哪裡；有取樣時刻算不出這一點（partially_evaluated）時，照實說只比較了一部分。
const DODECATEMORIA_PARTIAL_NOTE = "（部分取樣時刻算不出這一點，只比較了算得出的時刻）";
function dodecatemoriaCell(sampled, position) {
  const indices = dodecatemoriaSampledSigns(sampled);
  const partial = sampled && sampled.status === "partially_evaluated" ? DODECATEMORIA_PARTIAL_NOTE : "";
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

// 十二分部列的點：七政，加上升（有算宮位時）與命運點、精神點（有算阿拉伯點時）；少列的那一組由
// scope.not_listed 寫明原因（core/dodecatemoria.py _points）。
const DODECATEMORIA_GROUPS = Object.freeze([
  [null, SEVEN_KEYS],
  ["angles_not_computed", Object.freeze(["asc"])],
  ["lots_not_requested_or_not_computed", Object.freeze(["fortune", "spirit"])],
]);
const DODECATEMORIA_POINT_FIELDS = Object.freeze({
  key: "string", name: "string", category: "string",
  point_sign_position: "array", sign_position: "array", domicile_lord: "string",
  // 只有阿拉伯點在日夜盤邊界帶內才有值；其他點是 null。
  comparison_sign: "string?", sign_differs_under_other_sect: "boolean?",
});

/** 主表的點：恰好是應列的那幾個、依序，每一點帶齊欄位。 */
function dodecatemoriaPoints(module) {
  const path = "dodecatemoria";
  const notListed = need(need(module, path, "scope", "record"), `${path}.scope`, "not_listed", "array");
  notListed.forEach((code) => {
    if (!Object.hasOwn(DODECATEMORIA_NOT_LISTED_ZH, code)) {
      throw exportPipeline.incompleteResponse(`${path}.scope.not_listed 有未知的原因 ${code}`);
    }
  });
  const expected = DODECATEMORIA_GROUPS.filter(([reason]) => !reason || !notListed.includes(reason))
    .flatMap(([, keys]) => keys);
  const points = need(module, path, "points", "records");
  points.forEach((point, index) => Object.entries(DODECATEMORIA_POINT_FIELDS)
    .forEach(([key, kind]) => need(point, `${path}.points[${index}]`, key, kind)));
  needExactly(points.map((point) => point.key), expected, `${path}.points`);
  return { points, notListed };
}

function dodecatemoriaSection(response) {
  const module = response.derived_methods.dodecatemoria;
  const section = moduleSection(response, {
    id: "dodecatemoria", title: DODECATEMORIA_TITLE, ring: RING.METHOD,
    keys: { option: "include_dodecatemoria", module: "dodecatemoria" }, container: module,
    note: "本次未請求。十二分部是古典占星的細部技法：把一個點在星座裡的度數放大，對應到另一個星座；勾選後列出位置與該星座的守護行星。",
  });
  if (section.absent) return section.absent;
  const { points, notListed } = dodecatemoriaPoints(module);
  const profile = need(module, "dodecatemoria", "profile", "string");
  const notes = [
    "十二分部（dodecatemoria）：把一個點在星座裡走了幾度放大，"
      + "再從同一個星座的起點往後數，每 30° 換下一個星座，數到的位置就是它的十二分部。"
      + "表的最後一欄是那個星座的守護行星。Firmicus 說，有人認為從十二分部可以找出整張命盤的實質，命盤裡隱藏的事也能由它揭露（《Mathesis》II.13）。",
    profile === ALL_PROFILES
      ? dodecatemoriaAllNote(module)
      : presentClosedVocabulary(profile, DODECATEMORIA_PROFILE_ZH, "算法"),
    ...classicalDisagreementNotes(response, "derived_methods.dodecatemoria"),
    ...notListed.map((code) => (code === "lots_not_requested_or_not_computed"
      && response.birth_time_sensitivity.precision === "date_only"
      ? DODECATEMORIA_LOTS_NEED_TIME_NOTE
      : presentClosedVocabulary(code, DODECATEMORIA_NOT_LISTED_ZH, "未列原因"))),
    "中天不列：讀過的古書沒有算中天的十二分部。只列位置與守護行星。",
    "九分部（novenaria；吠陀占星稱 navamsa）把每個星座分成九份，本站不算；規則與出處見方法頁〈十二分部〉一節。",
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
  // 帳本說比較過時，checkSensitivity 已核對每一點都有一列；沒比較時不讀。
  const sampledByKey = sensitivityCompared(response, "derived_methods.dodecatemoria")
    ? Object.fromEntries(response.birth_time_sensitivity.dodecatemoria_signs.map((item) => [item.key, item]))
    : {};
  if (Object.keys(sampledByKey).length) notes.push(DODECATEMORIA_SAMPLED_NOTE);
  const all = profile === ALL_PROFILES;
  const comparison = all ? dodecatemoriaComparisonTable(module, points) : null;
  return section.make({
    notes,
    tables: (comparison ? [comparison] : []).concat([{
      title: all
        ? `各點的十二分部（${Labels.label("dodecatemoria_profile", module.points_profile)}，產品預設的算法）`
        : "各點的十二分部",
      columns: ["點", "類別", "原位置", "十二分部", "十二分部星座的守護行星"],
      rows: points.map((point) => [
        `${point.name}${dodecatemoriaSampledMany(sampledByKey[point.key]) ? DODECATEMORIA_SAMPLED_MARK : ""}`,
        presentClosedVocabulary(point.category, DODECATEMORIA_CATEGORY_ZH, "類別"),
        signPosition(point.point_sign_position),
        dodecatemoriaCell(sampledByKey[point.key], point.sign_position),
        rulerName(point.domicile_lord),
      ]),
    }]),
    blocks: DODECATEMORIA_SOURCES.slice(),
  });
}

/** 十二分部選「全部並列」：哪一種是主表、取樣用哪一種、另一種在哪裡。 */
function dodecatemoriaAllNote(module) {
  // 應有的兩種算法取自計算頁的目錄，不取自回應自己的 computed_profiles。
  const computed = need(module, "dodecatemoria", "computed_profiles", "array");
  needExactly(computed, catalogueProfiles("dodecatemoria"), "dodecatemoria.computed_profiles");
  if (!computed.includes(need(module, "dodecatemoria", "points_profile", "string"))) {
    throw exportPipeline.incompleteResponse("十二分部的 points_profile 不在 computed_profiles 裡");
  }
  const listed = Labels.label("dodecatemoria_profile", module.points_profile);
  const others = computed.filter((profileId) => profileId !== module.points_profile)
    .map((profileId) => Labels.label("dodecatemoria_profile", profileId));
  return `本次算法：全部並列，${computed.length} 種都算。主表（含出生時間不精確時的取樣）用${listed}，`
    + `這是產品預設的算法；${others.join("、")}的結果在對照表。對照表每格是十二分部的星座，括號裡是那個星座的守護行星；`
    + "「各家」只比較星座是否相同，不表示哪一種對。"
    // 中文名稱會改寫，不能當程式對應的鍵；每一種匯出都帶代碼。
    + `對照表各欄的代碼（profile_id，與 JSON 的 profile_results 同名，供程式對應）：${
      computed.map((profileId) => `${Labels.label("dodecatemoria_profile", profileId)}＝${profileId}`).join("、")}。`;
}

/** 十二分部「全部並列」的對照表：每點一列、每種算法一欄（目錄順序），最後一欄只比較星座字。 */
function dodecatemoriaComparisonTable(module, listed) {
  const results = need(module, "dodecatemoria", "profile_results", "record");
  const computed = module.computed_profiles;  // dodecatemoriaAllNote 已對目錄核過
  const byProfile = computed.map((profileId) => {
    const at = `dodecatemoria.profile_results.${profileId}`;
    const own = need(need(results, "dodecatemoria.profile_results", profileId, "record"), at, "points", "records");
    own.forEach((point, index) => ["key", "sign", "domicile_lord"]
      .forEach((key) => need(point, `${at}.points[${index}]`, key, "string")));
    // 每一種算法列的點與主表同一組、同一順序。
    needExactly(own.map((point) => point.key), listed.map((point) => point.key), `${at}.points`);
    return new Map(own.map((point) => [point.key, point]));
  });
  // 列照主表（頂層 points，帶原位置）；每一種算法的那一格依點鍵對齊。
  return {
    title: `${COMPARISON_TITLE_PREFIX}十二分部`,
    columns: ["點", "原位置"]
      .concat(computed.map((profileId) => Labels.label("dodecatemoria_profile", profileId)))
      .concat(["各家"]),
    rows: listed.map((point) => {
      const cells = byProfile.map((points) => points.get(point.key));
      const same = new Set(cells.map((own) => own.sign)).size === 1;
      return [point.name, signPosition(point.point_sign_position)]
        .concat(cells.map((own) => `${signName(own.sign)}（${rulerName(own.domicile_lord)}）`))
        .concat([same ? COMPARISON_VERDICT.same : COMPARISON_VERDICT.differ]);
    }),
  };
}

// 行星與宮的古典分類。
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
    "出處：Ptolemy《占星四書》卷三第 3、10 章與 Robbins 英譯（LacusCurtius 線上本註 56）：始宮、續宮與「自始宮下落」的宮，"
    + "以及十二宮的希臘名稱。",
    "translation_read", "（Robbins 英譯）"],
  ["dorotheus_carmen_i_5",
    "出處：Dorotheus《Carmen Astrologicum》卷一第 5 章（Pingree 1976 英譯 p.164）：最好的七宮、中等三宮、壞的兩宮。阿拉伯文未核。",
    "translation_read", "（Pingree 英譯）"],
  ["manilius_astronomica_ii",
    "出處：Manilius《Astronomica》卷二另有一套十二宮的名稱與守護神（例如金星在中天、土星在天底），"
    + "本站沒有採用。",
    "secondary_only", "（拉丁原文部分核過，各宮的對應依二手整理）"],
  [null, "出處：完整書目與每條核到哪一層，見方法頁〈行星與宮的古典分類〉一節。"],
]);
const CLASSICAL_SOURCES = sourceBlocks(CLASSICAL_SOURCE_LINES);

const yesNoDash = (value) => (value === true ? "是" : value === false ? "否" : DASH);
// 每顆行星的喜樂宮（說明文字列的同一組）：Paulus《導論》第 24 章七條，Firmicus 卷二第 19 章另給月亮第 8 宮。
const CLASSICAL_JOYS = Object.freeze({
  sun: [9], moon: [3, 8], mercury: [1], venus: [5], mars: [6], jupiter: [11], saturn: [12],
});

/**
 * 只知日期時，後端在這些模組寫上 time_basis（代表性計算時刻）；其他精度目前不寫這個鍵。
 * 只知日期卻沒有這個鍵就是殘缺；有這個鍵就照它說。
 */
function eventTimeBasis(response, module, path) {
  if (response.birth_time_sensitivity.precision === "date_only") return module("time_basis", "string");
  return Object.hasOwn(module.record, "time_basis") ? need(module.record, path, "time_basis", "string") : null;
}

// 只知日期時，後端在代表性計算時刻算古典分類，並在模組的 time_basis 寫明；這一句照它寫，不由精度推斷。
const CLASSICAL_DATE_ONLY_BASIS = "representative_computational_anchor_not_birth_time";
function classicalTimeNote(response, module) {
  const precision = response.birth_time_sensitivity.precision;
  if (eventTimeBasis(response, module, "classical_classifications") === CLASSICAL_DATE_ONLY_BASIS) {
    return "只知道出生日期時沒有出生時刻：日盤或夜盤、在地平上或下，以及落在哪一宮都無法判定，這幾欄寫「—」；"
      + "吉凶、陰陽與日夜區照列，水星是晨星或昏星依當天的代表性時刻。";
  }
  if (precision === "approximate_hour") {
    return "只知道約略時辰時，日盤或夜盤、在地平上或下與落在哪一宮都依代表性時刻判定；這一小時內它們可能改變。";
  }
  return null;
}

function classicalClassificationsSection(response) {
  const container = response.derived_methods.classical_classifications;
  const section = moduleSection(response, {
    id: "classical_classifications", title: CLASSICAL_TITLE, ring: RING.METHOD,
    keys: { option: "include_classical_classifications", module: "classical_classifications" }, container,
    note: "本次未請求。勾選後列出古書怎麼分類七顆行星（吉星、凶星、白天或夜晚一組、喜樂宮、hayz）"
        + "與十二宮（名稱、始宮／續宮／果宮、好壞），每一條都寫明出自哪本書。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "classical_classifications");
  // 七顆行星（頁面投影只帶名稱）依古典順序、十二宮依宮序；應有的集合取自目錄，不取自回應。
  const planets = module.rows("planets");
  needExactly(planets.map((row) => row("name", "string")), SEVEN_NAMES, "classical_classifications.planets");
  const places = module.rows("places");
  needExactly(places.map((place) => place("place", "number")), CLASSICAL_PLACE_NUMBERS,
    "classical_classifications.places");
  // 喜樂宮：每顆行星應有的那幾條（Paulus 一組七條，Firmicus 另給月亮第 8 宮），依同一份目錄核對。
  planets.forEach((row, index) => needExactly(row.rows("joys").map((joy) => joy("place", "number")),
    CLASSICAL_JOYS[SEVEN_KEYS[index]], `${row.path}.joys`));
  const sect = module.in("chart_sect", true);
  const notEvaluated = module("not_evaluated", "array");
  const housesModule = response.derived_methods.planet_in_house;
  const notes = [
    "這一區照古書原文列出分類：哪本書把哪顆行星歸為吉星或凶星、屬於白天還是夜晚一組、在哪一宮「喜樂」，"
      + "以及這張盤合不合乎書中的條件。各書說法不同時並列，不替你挑。本站只列分類與條件，不加總、不打分。",
  ];
  const isDay = sect ? sect("is_day", "boolean?") : null;
  if (isDay !== null) {
    notes.push(`本盤是${isDay ? "日盤（出生時太陽在地平線上）" : "夜盤（出生時太陽在地平線下）"}。`);
    if (sect("in_near_horizon_band", "boolean")) {
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
      + "是「遲滯、低落」的位置，其餘八宮與上升相連；Dorotheus《Carmen Astrologicum》卷一第 5 章分成好、中等、壞三等。"
      + "各宮的含義不在這裡列，見方法頁。",
    ...classicalDisagreementNotes(response, "derived_methods.classical_classifications"),
  );
  const near = planets.filter((row) => row("altitude_in_near_horizon_band", "boolean?") === true).map((row) => row("name"));
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
    const reason = verdict("reason_code", "string?");
    if (reason) return presentClosedVocabulary(reason, HAYZ_REASON_ZH, "原因");
    return yesNoDash(verdict(field, "boolean?"));
  };
  const residents = new Map();
  if (isRecord(housesModule) && housesModule.execution_status === "computed" && Array.isArray(housesModule.placements)) {
    housesModule.placements.filter(isRecord).forEach((place) => {
      if (!residents.has(place.house)) residents.set(place.house, []);
      residents.get(place.house).push(place.name || place.key);
    });
  }
  const placesDrawn = residents.size > 0;
  return section.make({
    notes,
    tables: [
      {
        title: "七顆行星：吉凶與日夜區",
        columns: ["行星", "吉凶（Ptolemy）", "吉凶（al-Bīrūnī）", "陰陽", "日夜區", "與本盤日夜"],
        rows: planets.map((row) => {
          const nature = row.in("nature");
          const ofSect = row("of_chart_sect", "boolean?");
          return [
            row("name"),
            presentClosedVocabulary(nature("ptolemy_tetrabiblos_i_5", "string"), NATURE_ZH, "分類"),
            presentClosedVocabulary(nature("al_biruni_tafhim_382", "string"), NATURE_ZH, "分類"),
            presentClosedVocabulary(row("gender", "string"), PLANET_GENDER_ZH, "陰陽"),
            presentClosedVocabulary(row("sect_membership", "string"), SECT_MEMBERSHIP_ZH, "日夜區"),
            ofSect === true ? "同一組" : ofSect === false ? "不同組" : DASH,
          ];
        }),
      },
      {
        title: "喜樂宮",
        columns: ["行星", "喜樂的宮", "出處", "本盤所在的宮", "是否在喜樂宮"],
        rows: planets.flatMap((row) => row.rows("joys").map((joy) => [
          row("name"),
          `第 ${joy("place")} 宮${joy("condition", "string") === "night_chart_only" ? "（只在夜盤）" : ""}`,
          presentClosedVocabulary(joy("source", "string"), JOY_SOURCE_ZH, "出處"),
          houseCell(row("house", "number?")),
          yesNoDash(joy("in_joy", "boolean?")),
        ])),
      },
      {
        title: "Hayz 與 halb",
        columns: ["行星", "在地平上／下", "所在星座", "星座陰陽",
          "halb（al-Bīrūnī）", "hayyiz（al-Bīrūnī）", "hayz（Lilly）"],
        rows: planets.map((row) => {
          const hayz = row.in("hayz");
          const above = row("above_horizon", "boolean?");
          return [
            row("name"),
            above === true ? "地平上" : above === false ? "地平下" : DASH,
            signName(row("sign", "string")),
            presentClosedVocabulary(row("sign_gender", "string"), SIGN_GENDER_ZH, "陰陽"),
            hayzCell(hayz.in("al_biruni_tafhim_496"), "halb"),
            hayzCell(hayz.in("al_biruni_tafhim_496"), "hayyiz"),
            hayzCell(hayz.in("lilly_christian_astrology_p113"), "hayz"),
          ];
        }),
      },
      {
        title: CLASSICAL_PLACES_TITLE,
        columns: ["宮", "名稱", "原文名稱", "始宮／續宮／果宮", "Firmicus 的分法", "Dorotheus 的分法",
          "本盤在這一宮的行星"],
        rows: places.map((place) => [
          `第 ${place("place")} 宮`,
          place("name_zh", "string"),
          `${place("name_greek", "string")}（希臘文）、${place("name_latin", "string")}（拉丁文）、${place("name_english", "string")}`,
          presentClosedVocabulary(place("triad", "string"), TRIAD_ZH, "分類"),
          presentClosedVocabulary(place("firmicus_ii_15_17", "string"), FIRMICUS_GROUP_ZH, "分類"),
          presentClosedVocabulary(place("dorotheus_i_5", "string"), DOROTHEUS_RANK_ZH, "分類"),
          placesDrawn ? (residents.get(place("place")) || []).join("、") || "（無）" : DASH,
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
