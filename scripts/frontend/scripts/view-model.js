// 圖表連動的點鍵與 sections → view tree；出貨的 view-model.js 由 view-model-*.js 與本檔合併而成（javascript.py）。
// 本檔與 view-model-*.js 是純函式：不碰 DOM、不發 request、不讀全域狀態。
//
// 契約 §10 的資料流：backend response -> canonical export document -> sections -> {render, exporters}。
// 渲染與匯出是 sections 的兩個平行下游，不回頭刮畫面；兩步都在這裡，Node 測試可直接斷言。

// 圖表連動的點鍵：星盤圖、位置表、速覽、落宮、逐度相位與相位方格以後端的點鍵（sun、true_node、mean_lilith、asc…）互相對
// 應。鍵只放在 view tree（畫面用）；匯出讀 canonical sections，鍵不會進任何匯出檔。每一張表的鍵都從回應讀，並逐列核對列
// 名：列數或任一列名對不上，整張表不連動（null），不猜。
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
  if (participants.length < 2 || table.rows.length !== participants.length - 1 || table.columns.length !== participants.length) return null;
  if (table.columns.slice(1).some((column, index) => column !== names[index])) return null;
  if (table.rows.some((row, index) => row[0] !== names[index + 1])) return null;
  return { rows: keys.slice(1).map((key) => (key ? [key] : null)), columns: [null, ...keys.slice(0, -1)] };
}

/**
 * 相位方格每一格的相位記號（只給畫面；匯出讀 canonical sections 的文字）：容許度內的每個相位的鍵、
 * 名稱與距精確的度數，與格內文字同一個條件（in_orb 為 true）。方格對不上參與者時回 null。
 */
function aspectGridMarks(aspects, table) {
  if (!aspectGridPoints(aspects, table)) return null;
  const participants = aspects.participants.filter((item) => isRecord(item) && item.key);
  const index = new Map(participants.map((item, position) => [item.key, position]));
  const degree = isRecord(aspects.degree_based) ? aspects.degree_based : {};
  const names = isRecord(degree.aspect_names_zh) ? degree.aspect_names_zh : {};
  const marks = new Map();
  for (const pair of Array.isArray(aspects.pairs) ? aspects.pairs : []) {
    if (!isRecord(pair)) continue;
    const a = index.get(pair.body_a);
    const b = index.get(pair.body_b);
    if (a === undefined || b === undefined) continue;
    const inOrb = (Array.isArray(pair.aspect_targets) ? pair.aspect_targets : [])
      .filter((target) => isRecord(target) && target.in_orb === true);
    if (!inOrb.length) continue;
    marks.set(`${Math.max(a, b)}:${Math.min(a, b)}`, inOrb.map((target) => ({
      aspect: target.key, name: typeof names[target.key] === "string" ? names[target.key] : target.key,
      orb: typeof target.offset_from_exact_degrees === "number" ? `${num(Math.abs(target.offset_from_exact_degrees), 1)}°` : null,
    })));
  }
  const count = participants.length;
  return Array.from({ length: count - 1 }, (_row, row) => Array.from({ length: count - 1 }, (_column, column) => (
    column <= row ? (marks.get(`${row + 1}:${column}`) || null) : null)));
}

/** 一張表的點鍵：{ rows: (string[]|null)[], columns?: (string|null)[] }；這張表不連動時回 null。 */
function tablePoints(sectionId, table, sourceResponse) {
  if (!isRecord(sourceResponse) || !isRecord(table) || !Array.isArray(table.rows)
    || table.rows.some((row) => !Array.isArray(row))) return null;
  const astro = isRecord(sourceResponse.astronomical_data) ? sourceResponse.astronomical_data : {};
  const derived = isRecord(sourceResponse.derived_methods) ? sourceResponse.derived_methods : {};
  switch (sectionId) {
    case "bodies": return listPoints(astro.bodies, table.rows);
    case "nodes": return listPoints(astro.nodes, table.rows);
    case "lunar_apsides": return listPoints(isRecord(astro.lunar_apsides) ? astro.lunar_apsides.points : null, table.rows);
    case "angles": return fixedPoints(Object.entries(Labels.VOCABULARIES.angle_label), table.rows);
    case "summary": return fixedPoints(SUMMARY_ROWS, table.rows);
    case "planet_in_house":
      if (table.title === POINT_PLACEMENT_TITLE) {
        const points = isRecord(derived.planet_in_house) && isRecord(derived.planet_in_house.point_placements)
          ? derived.planet_in_house.point_placements.placements : null;
        return listPoints(points, table.rows, null);
      }
      return listPoints(isRecord(derived.planet_in_house) ? derived.planet_in_house.placements : null, table.rows);
    case "aspects": return table.variant === "aspect_grid" ? aspectGridPoints(derived.aspects, table)
        : aspectPairPoints(derived.aspects, table.rows);
    default: return null;
  }
}

// 十二宮表的宮名連到方法頁宮義對照表的那一列（宮義本身不進個人的盤）。連結只給畫面；
// 匯出讀 canonical sections，不帶連結。
const HOUSE_MEANING_HREF = "/zh-TW/methods#house-meaning-";
const HOUSE_NAME_COLUMN = "名稱";

/** 列以回應的 places 逐列核對（宮號與宮名都要對上），對不上的列不連，不由中文名稱反查宮號。 */
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
      && typeof place.name_zh === "string" && place.name_zh !== "" && row[0] === `第 ${number} 宮` && row[column] === place.name_zh;
    return ok ? `${HOUSE_MEANING_HREF}${number}` : null;
  });
  return rows.some(Boolean) ? { column, rows } : null;
}

// 「說明與原典」摺疊：這幾區在表格前有大段說明（原典怎麼說、說法不一、讀法與天文附註），手機上要捲兩屏才看到第一列。畫
// 面把以下列開頭的段落收進一個預設收起的「說明與原典」摺疊，放在第一段白話之後；一個字都不改，列印時展開（beforeprint
// 展開結果裡的每個 details），匯出讀 canonical sections，照常逐段印出。第一段白話、本次分法、這張盤的狀況（時刻不精確、
// 貼近地平線…）與固定句不收，留在表格前。
const EXPLAIN_FOLDED_PREFIXES = Object.freeze({
  solar_phase: Object.freeze([
    "原典怎麼說：", "判定用黃道上的經度差", "al-Bīrūnī 另有一條", "Lilly 說焦傷只發生",
    "月亮落在日輪內", "水星離太陽最遠", "古典文獻說法不一："]), motion_states: Object.freeze([
    "東出西入（oriental", "停滯（stationary）", "Lilly 的強弱表（p.115）", "月亮：Lilly p.80", "古書的「一天走多少」", "原典怎麼說：",
    "「增於行／減於行」", "古典文獻說法不一："]), classical_classifications: Object.freeze([
    "「在地平上／下」看", "水星屬白天或夜晚一組", "喜樂宮（joys）", "Hayz 與 halb", "十二宮的名稱沿用",
    "古典文獻說法不一："]), prenatal_points: Object.freeze(["度數怎麼取：", "同一章接著用", "另一種挑法（不是預設）", "手抄本的另一種讀法",
    "「出生前最近一次日食／月食」", "日食的度數是", "月食有兩種算法", "算進來的理由", "古典文獻說法不一：",
  ]),
  // 外來：定義、日夜盤的狀況與固定句留在外面；依哪一張表判、與陷弱並存、與接納的分別收進去。
  dignity_peregrine: Object.freeze(["依 Lilly 判：", "外來可以和陷、弱同時成立", "外來與接納是兩件事"]),
  aspects: Object.freeze(["「入／出」「同度」「完成時刻」三欄", "古典文獻說法不一：", "「相位方格」", "不合意（aversion）"]),
});
function explainFolded(sectionId, note) {
  const prefixes = EXPLAIN_FOLDED_PREFIXES[sectionId];
  return Boolean(prefixes) && typeof note === "string" && prefixes.some((prefix) => note.startsWith(prefix));
}

// sections → view tree（畫面）：回傳純資料而不是 DOM，瀏覽器端一律以 textContent 變成元素，
// 渲染路徑沒有字串拼接，也就沒有 HTML 注入面。
function buildViewTree(exportDocument) {
  if (!isRecord(exportDocument) || !Array.isArray(exportDocument.sections)) { throw new Error("缺少可用的 canonical export document。"); }
  const dossier = exportDocument.calculation_dossier || {};
  const warnings = Array.isArray(dossier.warnings) ? dossier.warnings : [];
  return {
    header: {
      birth_time_summary: birthTimeSummary(exportDocument.source_response),
      warnings: warnings.filter(
        (warning) => warning.code !== "provisional_method_result"
      ).map((warning) => ({
        code: warning.code || "UNSPECIFIED_WARNING", message: warning.message || "",
        // 句中提到的本站文章路徑：畫面做成連結，匯出照舊只印 message 的純文字。
        ...(isRecord(warning.params) && Object.hasOwn(warning.params, "article_path")
          && typeof warning.params.article_path === "string"
          ? { article_path: warning.params.article_path } : {}),
      })),
      stale: false, stale_notice: "", actions: { copy_enabled: true, download_enabled: true },
    },
    sections: exportDocument.sections.map((section) => ({
      type: "section", id: section.id, title: section.title, layer_label: section.layer_label,
      ring: ringKeyFor(section.layer_label), status: section.status,
      // 摘要圖在最前面：它的第一行是這一區的結論，渲染端永遠放在摺疊之外。
      children: [].concat(
        (section.figures || []).map((figure) => ({ type: "figure", figure })),
        // 表下註在匯出裡是區段備註；畫面上放回它那張表的下面（tableNotes），不在上方重複。
        section.notes.filter((note) => !isTableNote(note, section))
          .map((note) => ({ type: explainFolded(section.id, note) ? "explain" : "note", text: note })),
        section.tables.map((table) => {
          const points = tablePoints(section.id, table, exportDocument.source_response);
          const links = tableLinks(section.id, table, exportDocument.source_response);
          return {
            type: "table", title: table.title,
            columns: table.columns.map((column) => (SCREEN_COLUMNS[column] ? SCREEN_COLUMNS[column].label : column)),
            rows: table.rows, ...(table.variant ? { variant: table.variant } : {}),
            ...(points ? { points } : {}),
            ...(links ? { links } : {}),
            ...(screenTableNotes(table, section).length ? { notes: screenTableNotes(table, section) } : {}),
            ...(section.id === "aspects" && table.variant === "aspect_grid" && isRecord(exportDocument.source_response)
              && isRecord(exportDocument.source_response.derived_methods)
              ? { marks: aspectGridMarks(exportDocument.source_response.derived_methods.aspects, table) } : {}),
          };
        }),
        section.blocks.map((block) => ({ type: SOURCE_FOLDED_SECTIONS.has(section.id) ? "source" : "block", text: block }))
      ),
    })),
  };
}

/**
 * 表單改動後，畫面上的結果不再對應目前的輸入。回傳一棵標為過期的新樹：sections 不重建（同一個參考），複製與下載關閉，說
 * 明文字只在這裡寫一次。原樹不就地改動。
 */
const STALE_NOTICE = "表單已改動，下方結果對應的是先前送出的輸入；複製與下載已停用。" + "請重新計算，或把欄位改回原值。";
function markStale(tree) {
  if (!isRecord(tree) || !isRecord(tree.header) || !Array.isArray(tree.sections)) { throw new Error("缺少可用的 view tree。"); }
  return {
    ...tree, header: { ...tree.header, stale: true, stale_notice: STALE_NOTICE, actions: { copy_enabled: false, download_enabled: false } },
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
      row[0], row[sign], id !== "angles" && houses.has(row[0]) ? houses.get(row[0]) : DASH, motion < 1 ? DASH : row[motion],
    ]));
  }
  return rows.length ? { columns: PRINT_BRIEF_COLUMNS, rows } : null;
}

function ringKeyFor(layerLabel) { return RING_KEY_BY_LAYER.get(String(layerLabel || "")) || RING.VERIFICATION.key; }

const api = Object.freeze({
  MODULE_COVERAGE, TRANSITION_RESOLUTION_LIMIT_SECONDS, MODULE_REASON_ZH, DASH,
  // 計算頁的尊貴一覽以欄名認出廟旺表；欄名只寫這一處。
  DEGREE_IN_SIGN_COLUMN, dms, cyclicFixed, signPosition, longitudeText, receiptStatus, moduleState, buildSections,
  buildViewTree, SCREEN_COLUMNS, birthTimeSummary, changedPathsText, EXPLAIN_FOLDED_PREFIXES, markStale, printBriefRows, TIME_SCALE_ZH,
  SOURCE_LINES: Object.freeze({
    dodecatemoria: DODECATEMORIA_SOURCE_LINES, lunar_mansions: LUNAR_MANSION_SOURCE_LINES,
    solar_phase: SOLAR_PHASE_SOURCE_LINES, motion_states: MOTION_SOURCE_LINES,
    classical_classifications: CLASSICAL_SOURCE_LINES, "dignities/peregrine_lilly_1647_p112_v1": PEREGRINE_SOURCE_LINES,
  }),
});
if (commonJs) module.exports = api;
globalThis.ChartViewModel = api;
