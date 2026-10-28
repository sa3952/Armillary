(function attachTimelordsModel(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  // 星座名只有一份，在 labels.js；時間主星表的儲存格與 Markdown 中和規則在 exporters.js。頁面在本檔之前載入兩者。
  const api = factory(commonJs ? require("./labels.js") : root.ArmillaryLabels, commonJs ? require("./exporters.js") : root.ChartExport);
  if (commonJs) module.exports = api;
  if (root) root.ArmillaryTimelordsModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildTimelordsModel(Labels, ChartExport) {
  "use strict";

  // 年度時間主星的畫面模型：純函式，不碰 DOM、不發請求、不讀時鐘（「今天」由呼叫端給）。
  //
  // 資料流：年度回應 → adaptAnnualSource（唯一認得回應形狀的地方）→ AnnualData         → buildModel → 泳道、年度、細
  // 節、摘要、.ics、時間主星表。每一個日期都是伺服器給的出生地日期（YYYY-MM-DD）；本檔只排序、比較與裁切，不把任何 UTC
  // 換成日期，也不重算任何邊界。泳道位置用「日序」（日期字串的日曆序數），它只決定畫在哪裡，不印在畫面上。

  const FIXED_SENTENCE = "只列計算結果：哪一段時間由哪顆行星或哪個星座輪值。不替你解盤，也不預測。";
  const ICS_LABEL = "含由出生資料推得的日期";
  const DATE_NOTE = "出生地的日期，只到日";
  const ICS_FILENAME = "armillary-time-lords.ics";

  const SIGN_ORDER = Object.freeze(Object.keys(Labels.VOCABULARIES.zodiac_sign));
  const BODY_NAMES = Object.freeze({ ...Labels.VOCABULARIES.body_backend_name, north_node: "北交點", south_node: "南交點" });
  const LOT_NAMES = Labels.VOCABULARIES.lot;
  const RELEASING_LOTS = Object.freeze(["fortune", "spirit"]);
  const ANGULARITY = Object.freeze({
    angular: "角宮位置（第 1、4、7、10 位）", succedent: "續宮位置（第 2、5、8、11 位）", cadent: "果宮位置（第 3、6、9、12 位）",
  });
  const SAMPLE_ROLES = Object.freeze({
    interval_start: "這一小時的開頭", representative_anchor: "中間（代表性時刻）", interval_end: "這一小時的結尾",
  });
  // 只知日期時三項不算的理由（伺服器的閉集碼）。
  const NOT_APPLICABLE = Object.freeze({
    natal_ascendant_unknown_for_date_only: "要從上升星座起算，只知日期算不出上升星座。",
    sect_unknown_for_date_only: "要先知道是日盤還是夜盤（出生時太陽在不在地平線上），只知日期無法判斷。",
    lots_not_derivable_for_date_only: "要從命運點或精神點起算，這兩點都需要上升點，只知日期算不出來。",
  });
  const WARNINGS = Object.freeze({
    natal_ascendant_near_sign_boundary_affects_profection:
      "上升點離星座邊界很近：出生時間稍有出入，上升星座就會換，年度小限與月小限從頭到尾都會不同。",
    sect_near_horizon_band_affects_firdaria: "出生時太陽貼近地平線：日盤或夜盤可能判斷不同，法達的起點與順序會跟著不同。",
    sect_near_horizon_band_affects_decennials:
      "出生時太陽貼近地平線：日盤或夜盤可能判斷不同，十年期從太陽或月亮起算會跟著不同，整條順序也會不同。",
    sect_near_horizon_band_affects_zodiacal_releasing:
      "出生時太陽貼近地平線：日盤或夜盤可能判斷不同，命運點與精神點的位置會跟著不同，黃道釋放的起點星座也會換，大期與小期從頭到尾都會不同。",
    extended_lot_near_sign_boundary: "有延伸的阿拉伯點離星座邊界很近：出生時間稍有出入，它就會落在相鄰的星座。",
    year_boundary_delta_t_extrapolated: "這一年的年界落在地球自轉資料的外推範圍：年界的時刻有幾秒到幾十秒的不確定。",
    zr_start_lot_near_sign_boundary:
      "黃道釋放的起點（命運點或精神點）離星座邊界很近：出生時間稍有出入，它就會落在相鄰的星座，這一條的大期與小期從頭到尾都會不同。",
  });

  const signName = (key) => Labels.label("zodiac_sign", key);
  const bodyName = (key) => Labels.closedLabel(key, BODY_NAMES, "天體");

  function fail(message) { throw new Error(`年度回應形狀不符：${message}`); }

  const DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

  /** 日期字串的日曆序數（1970-01-01 為 0）。只用來排位置與比先後。 */
  function dayNumber(localDate) {
    const match = DATE_PATTERN.exec(localDate || "");
    if (!match) fail(`不是 YYYY-MM-DD 的日期：${localDate}`);
    return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])) / 86400000;
  }

  // adapter：唯一認得回應形狀的地方讀年度路由的頁面投影（POST /api/chart/annual?projection=page；輸出契約「Annual
  // route」）：year_boundaries 給一生的年界，annual_timeline.lanes[] 給泳道與期間（期間的起訖是出生地日期
  // "YYYY-MM-DD"）。投影形狀若再調整，只改這一段；輸出 AnnualData 是本檔其餘部分唯一讀的形狀。

  const SAMPLE_ORDER = Object.freeze(["interval_start", "representative_anchor", "interval_end"]);
  const SAMPLE_SHORT = Object.freeze({ interval_start: "開頭", representative_anchor: "中間", interval_end: "結尾" });
  const RELEASING_LANE = /^zr_(fortune|spirit)_level_\d+$/;
  // 按需取的細分期間：黃道釋放（命運點、精神點）與十年期的第二層，以及月小限。第一層的每一段，第二層只隨「與所請求年度
  // 相交」的那一段一起來，其他段的第二層另外請求；月小限每次只來所請求的那一年，其他年度選到時另外請求。
  const ON_DEMAND_LEVEL_2 = /^((zr_(fortune|spirit)|decennials)_level_2|monthly_profection)$/;
  const MONTHLY_LANE = "monthly_profection";
  const LANE_GROUP = /^(.*)_level_\d+$/;

  function checkedDate(value, where) { if (typeof value !== "string") fail(`${where} 缺少日期`); dayNumber(value); return value; }

  function minuteOf(localTime) {
    const match = /^\d{4}-\d{2}-\d{2}[ T](\d{2}:\d{2})/.exec(localTime || "");
    return match ? match[1] : null;
  }

  const SHA256_HEX = /^[0-9a-f]{64}$/;
  const nonEmpty = (value) => (typeof value === "string" && value.length > 0) || Number.isInteger(value);

  /**
   * 年度回應的相容規則，畫面模型、按需併入、.ics 與時間主星表共用這一條：API 版本在相容清單、
   * 出處清單有代號、版本與 SHA-256 摘要、有計算軌跡收據的摘要。不符時回一句原因，符合時回 null。
   */
  function compatibilityProblem(source) {
    const version = source && source.schema_version;
    if (!version) return "缺少 API schema 版本，不能建立可追溯輸出。";
    if (!ChartExport.SUPPORTED_API_SCHEMA_VERSIONS.includes(version)) return `不相容的 API schema 版本：${version}。`;
    const dossier = source.calculation_dossier || {};
    const register = dossier.method_source_register || {};
    if (!nonEmpty(register.register_id) || !nonEmpty(register.version) || !SHA256_HEX.test(String(register.sha256))) {
      return "年度回應不完整：缺少出處清單的代號、版本或摘要，不能建立可追溯輸出。";
    }
    const trace = dossier.trace_receipt || {};
    if (!SHA256_HEX.test(String(trace.python_json_serialization_sha256))) {
      return "年度回應不完整：缺少計算軌跡收據的摘要，不能建立可追溯輸出。";
    }
    return null;
  }

  /** 相容的回應彼此要同一個 API 版本與同一份出處清單；這個鍵就是那兩者。 */
  function identityKey(source) {
    const register = source.calculation_dossier.method_source_register;
    return JSON.stringify([source.schema_version, register.register_id, register.version, register.sha256]);
  }

  function adaptAnnualSource(source) {
    if (!source || typeof source !== "object" || Array.isArray(source)) fail("不是物件");
    const problem = compatibilityProblem(source);
    if (problem) fail(problem);
    const timeline = source.annual_timeline;
    if (!timeline || !Array.isArray(timeline.lanes)) fail("缺少 annual_timeline.lanes");
    const precision = source.birth_time_precision;
    if (!Labels.VOCABULARIES.birth_time_precision[precision]) fail(`未知的出生時刻精度 ${precision}`);
    const methods = source.annual_methods || {};
    const anchor = source.natal_anchor || {};
    const requested = source.year_boundary || null;
    // 只有所請求的那一年（year_boundary）帶時刻；它的終點是下一年的起點。
    const times = new Map();
    if (requested && requested.start_status === "computed") {
      times.set(requested.completed_years, {
        start: minuteOf(requested.start && requested.start.local_time),
        end: requested.end_status === "computed" ? minuteOf(requested.end && requested.end.local_time) : null,
      });
    }
    const boundaries = source.year_boundaries;
    const years = (boundaries && Array.isArray(boundaries.years) ? boundaries.years : [])
      .filter((year) => year.end_status === "computed" && year.end)
      .map((year, index) => {
        if (!Number.isInteger(year.completed_years)) fail(`year_boundaries.years[${index}].completed_years`);
        const own = times.get(year.completed_years) || {};
        const previous = times.get(year.completed_years - 1) || {};
        return Object.freeze({
          n: year.completed_years,
          start: Object.freeze({
            localDate: checkedDate(year.start && year.start.local_date, `year_boundaries.years[${index}].start`),
            localTime: own.start || previous.end || null }), end: Object.freeze({
            localDate: checkedDate(year.end.local_date, `year_boundaries.years[${index}].end`), localTime: own.end || null,
          }),
        });
      });
    years.forEach((year, index) => { if (index && year.n !== years[index - 1].n + 1) fail("year_boundaries 不是連續的足歲"); });
    const lanes = timeline.lanes.map((lane, laneIndex) => {
      if (!lane.lane_id) fail(`lanes[${laneIndex}] 缺少 lane_id`);
      const releasing = RELEASING_LANE.exec(lane.lane_id);
      const group = LANE_GROUP.exec(lane.lane_id);
      const segments = (lane.status === "computed" && Array.isArray(lane.segments) ? lane.segments : [])
        // 起訖有一端算不出來（例如超出支援年份）的期間沒有日期可畫，不畫。
        .filter((segment) => segment.status === "computed" && segment.start && segment.end)
        .map((segment) => {
          if (!segment.id) fail(`${lane.lane_id} 有期間缺少 id`);
          const flags = Array.isArray(segment.flags) ? segment.flags : [];
          return Object.freeze({
            id: `${lane.lane_id}/${segment.id}`, periodId: segment.id, laneId: lane.lane_id, sampleRole: segment.sample_role || null,
            parentId: segment.parent_id && lane.parent_lane_id ? `${lane.parent_lane_id}/${segment.parent_id}` : null,
            labelKey: segment.label_key || null, lordKey: segment.lord_key || null,
            start: Object.freeze({ localDate: checkedDate(segment.start, `${lane.lane_id}/${segment.id}.start`), localTime: null }),
            end: Object.freeze({ localDate: checkedDate(segment.end, `${lane.lane_id}/${segment.id}.end`), localTime: null }),
            loosing: flags.includes("loosing_of_the_bond"), truncated: flags.includes("truncated"),
            node: flags.includes("node_period"), flags: Object.freeze(flags.slice()), detail: Object.freeze({ ...(segment.detail || {}) }),
          });
        });
      // 月小限在畫面上是年度小限的下一層：同一組（年表同一欄），畫成第二層。
      const under = lane.lane_id === MONTHLY_LANE;
      return Object.freeze({
        laneId: lane.lane_id, technique: lane.technique, level: under ? 2 : lane.level || 1,
        group: under ? lane.parent_lane_id : group ? group[1] : lane.lane_id, lot: releasing ? releasing[1] : null,
        status: lane.status, reason: lane.reason_code || null, basis: lane.segments_basis || null,
        sensitivity: lane.sensitivity_state || null, unit: lane.unit || null, parentLaneId: lane.parent_lane_id || null,
        segments: Object.freeze(segments),
      });
    });
    const techniqueState = (technique) => {
      const head = methods[technique] || null;
      const own = lanes.filter((lane) => lane.technique === technique);
      const computed = own.find((lane) => lane.status === "computed");
      const notApplicable = own.find((lane) => lane.status === "not_applicable");
      return Object.freeze({
        status: computed ? "computed" : notApplicable ? "not_applicable" : "not_requested",
        reason: computed ? null : notApplicable ? notApplicable.reason : null,
        sensitivity: (computed || notApplicable || {}).sensitivity || null, head,
      });
    };
    // 年長與月長只取回應的 year_model：畫面上寫的「每年 N 日」「每月 N 日」都是這幾個數字，
    // 缺了就是形狀不符，不用預設值補。
    const yearModelFields = Object.freeze({
      zodiacal_releasing: ["days_per_year", "days_per_level_2_unit"], decennials: ["days_per_year", "days_per_month", "months_per_level_1"],
    });
    Object.entries(yearModelFields).forEach(([technique, fields]) => {
      if (techniqueState(technique).status !== "computed") return;
      const yearModel = (methods[technique] || {}).year_model;
      fields.forEach((field) => {
        const value = yearModel ? yearModel[field] : undefined;
        if (typeof value !== "number" || !(value > 0)) fail(`annual_methods.${technique}.year_model.${field}`);
      });
    });
    const startSigns = {};
    ((methods.zodiacal_releasing && methods.zodiacal_releasing.releases) || []).forEach((release) => {
      startSigns[release.releasing_from] = release.start_sign;
    });
    const level2LoadedFor = new Set();
    lanes.filter((lane) => ON_DEMAND_LEVEL_2.test(lane.laneId)).forEach((lane) => {
      lane.segments.forEach((segment) => { if (segment.parentId) level2LoadedFor.add(segment.parentId); });
    });
    const dossier = source.calculation_dossier || {};
    const policy = dossier.annual_policy || {};
    return Object.freeze({
      identity: identityKey(source), precision, requestedYears: requested ? requested.completed_years : null,
      natal: Object.freeze({
        ascendantSign: anchor.ascendant && anchor.ascendant.status === "computed" ? anchor.ascendant.sign : null,
        isDay: anchor.sect && typeof anchor.sect.is_day === "boolean" ? anchor.sect.is_day : null,
      }),
      years: Object.freeze(years), yearBoundary: requested ? Object.freeze({ profile: requested.solar_return_profile || null }) : null,
      profection: techniqueState("annual_profection"), firdaria: techniqueState("firdaria"),
      releasing: Object.freeze({ ...techniqueState("zodiacal_releasing"), startSigns: Object.freeze(startSigns) }),
      decennials: techniqueState("decennials"), monthly: techniqueState("monthly_profection"),
      lanes: Object.freeze(lanes), level2LoadedFor: Object.freeze(level2LoadedFor),
      // 年界的警告只說請求的那一年；記下是哪一年，按需併入別年的回應時才不會被當成同一則。
      warnings: Object.freeze((dossier.warnings || []).map((warning) => Object.freeze(
        String(warning.path || "").startsWith("year_boundary") && requested && Number.isInteger(requested.year_of_life)
          && !Object.hasOwn(warning, "year_of_life")
          ? { ...warning, year_of_life: requested.year_of_life } : { ...warning }))),
      samples: Object.freeze(Array.isArray(policy.representative_samples) ? policy.representative_samples.map((sample) => Object.freeze({
        role: sample.sample_role, localTime: minuteOf(sample.reference_local_time) ? sample.reference_local_time.slice(11, 19) : null,
      })) : []),
    });
  }

  /**
   * 按需取得的細分期間併入既有資料：只把黃道釋放與十年期第二層、月小限泳道裡尚未有的期間加進去，其餘不動。回傳新的
   * AnnualData（原物件不變）。monthsFor：要哪幾年的月小限（那一年年度小限期間的 id）。每個按需回應都會順帶那個請求年度
   * 的月小限；不在這裡面的一律不收，也不記為已載入——月小限只列選過的年度，與回應先後無關。
   */
  function mergeLevel2(data, extra, { monthsFor = [] } = {}) {
    // 按需的回應要與已載入的同一個 API 版本、同一份出處清單；否則整份不收，不混成一份。
    if (!data.identity || extra.identity !== data.identity) fail("按需取得的回應與已載入的版本或出處清單不同");
    const wanted = new Set(monthsFor);
    const keep = (segment) => segment.laneId !== MONTHLY_LANE || wanted.has(segment.parentId);
    const incoming = new Map();
    extra.lanes.filter((lane) => ON_DEMAND_LEVEL_2.test(lane.laneId)).forEach((lane) => incoming.set(lane.laneId, lane.segments));
    const lanes = data.lanes.map((lane) => {
      const more = incoming.get(lane.laneId);
      if (!more || lane.basis === "each_sample") return lane;
      const known = new Set(lane.segments.map((segment) => segment.id));
      const added = more.filter((segment) => !known.has(segment.id) && !segment.sampleRole && keep(segment));
      if (!added.length) return lane;
      const segments = lane.segments.concat(added)
        .sort((a, b) => dayNumber(a.start.localDate) - dayNumber(b.start.localDate) || compareIds(a.id, b.id));
      return Object.freeze({ ...lane, segments: Object.freeze(segments) });
    });
    // 月小限的「已載入」只記收下的那幾年；其他年度的月小限沒收，選到那一年時照常去取。
    const monthParents = new Set();
    extra.lanes.filter((lane) => lane.laneId === MONTHLY_LANE)
      .forEach((lane) => lane.segments.forEach((segment) => { if (segment.parentId) monthParents.add(segment.parentId); }));
    const loaded = new Set([...data.level2LoadedFor, ...[...extra.level2LoadedFor].filter((id) => !monthParents.has(id) || wanted.has(id))]);
    // 新回應的警告跟著它的期間一起收下：內容完全相同的只留一則，主體不同（path、年度、對象）的各自保留。
    const warningKey = (warning) => JSON.stringify(Object.keys(warning).sort().map((key) => [key, warning[key]]));
    const knownWarnings = new Set(data.warnings.map(warningKey));
    const warnings = data.warnings.concat((extra.warnings || []).filter((warning) => {
      const key = warningKey(warning);
      return !knownWarnings.has(key) && knownWarnings.add(key);
    }));
    return Object.freeze({
      ...data, lanes: Object.freeze(lanes), level2LoadedFor: Object.freeze(loaded), warnings: Object.freeze(warnings),
    });
  }

  function compareIds(a, b) { return a < b ? -1 : a > b ? 1 : 0; }


  // 年度路由收的出生欄位：與計算頁送出的請求同名的那幾個，其餘（選項）不送。
  const NATAL_KEYS = Object.freeze(["birth_time_precision", "datetime", "timezone", "location", "atmosphere", "computation_mode"]);

  // 十年期的起點（伺服器的閉集）：預設是 Firmicus 的日夜盤光體，另兩種是 Valens「上升點之後的
  // 第一顆」與自己指定一顆行星。預設不送欄位，回應就記為 defaulted。
  const DECENNIALS_START_PROFILES = Object.freeze(["firmicus_sect_light_v1", "valens_first_after_asc_v1", "user_selected_planet_v1"]);
  const DECENNIALS_PLANETS = Object.freeze(["sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"]);
  // 十年期起點選單在手機上的短字（option 的 label）：完整的字仍在頁面的 option 裡。
  const DECENNIALS_START_SHORT = Object.freeze({
    firmicus_sect_light_v1: "日盤太陽、夜盤月亮（預設）", valens_first_after_asc_v1: "上升後第一顆（Valens）",
    user_selected_planet_v1: "自己指定一顆行星",
  });

  function decennialsFields(choice) {
    const fields = { include_decennials: true, decennials_scope: "lifetime_window" };
    const profile = choice && choice.profile ? choice.profile : DECENNIALS_START_PROFILES[0];
    if (!DECENNIALS_START_PROFILES.includes(profile)) throw new Error("十年期的起點不在選項裡。");
    if (profile === DECENNIALS_START_PROFILES[0]) return fields;
    fields.decennials_start_profile = profile;
    if (profile === DECENNIALS_START_PROFILES[2]) {
      if (!DECENNIALS_PLANETS.includes(choice.planet)) throw new Error("自己指定起點時要選一顆行星。");
      fields.decennials_start_planet = choice.planet;
    }
    return fields;
  }

  // 法達夜盤兩個月交點的排法與黃道釋放的一年（伺服器的閉集）：第一個是預設，預設不送欄位，
  // 回應就記為 defaulted；另一個是具名的另一種，送出時回應記為 explicit。
  const FIRDARIA_NODE_PROFILES = Object.freeze(["abu_mashar_nodes_after_mercury_v1", "bonatti_reading_nodes_after_mars_v1"]);
  const ZR_YEAR_MODELS = Object.freeze(["zr_year_360_days_v1", "zr_year_365_25_days_v1"]);
  // 這兩個選單在手機上的短字（option 的 label）：完整的字仍在頁面的 option 裡。
  const METHOD_CHOICE_SHORT = Object.freeze({
    abu_mashar_nodes_after_mercury_v1: "水星之後（預設）", bonatti_reading_nodes_after_mars_v1: "火星之後（Zoller）",
    zr_year_360_days_v1: "360 日（預設）", zr_year_365_25_days_v1: "365.25 日",
  });

  function methodChoice(value, allowed, what) {
    if (value === undefined || value === null || value === allowed[0]) return null;
    if (!allowed.includes(value)) throw new Error(`${what}不在選項裡。`);
    return value;
  }

  /**
   * 由畫面上那份本命盤的請求組出年度請求；不另收任何出生資料。level2Only：只要黃道釋放、十年期與月小限（按需取某個第一
   * 層期間的第二層，或某一年的月小限）。decennials：十年期的起點 { profile, planet }，省略時用預設。firdariaNode：法達
   * 夜盤交點的排法；zrYear：黃道釋放的一年。省略或選預設時不送欄位。法達只在完整請求裡，所以交點排法只送在完整請求；黃
   * 道釋放的一年兩種請求都送，第二層才對得上。
   */
  function annualRequestBody(chartPayload, completedYears, scope = {}) {
    if (!chartPayload || typeof chartPayload !== "object") throw new Error("沒有本命盤的請求可用。");
    if (!Number.isInteger(completedYears) || completedYears < 0) throw new Error("年度必須是非負整數。");
    const body = {};
    NATAL_KEYS.forEach((key) => { if (chartPayload[key] !== undefined) body[key] = JSON.parse(JSON.stringify(chartPayload[key])); });
    const firdariaNode = methodChoice(scope.firdariaNode, FIRDARIA_NODE_PROFILES, "法達夜盤交點的排法");
    const zrYear = methodChoice(scope.zrYear, ZR_YEAR_MODELS, "黃道釋放的一年");
    body.annual = scope.level2Only === true ? {
      target_kind: "completed_years", target_value: completedYears, include_profection: false,
      include_zodiacal_releasing: true, zr_scope: "lifetime_window", ...(zrYear ? { zr_year_model: zrYear } : {}),
      include_monthly_profection: true, ...decennialsFields(scope.decennials) } : { target_kind: "completed_years",
      target_value: completedYears, include_firdaria: true, firdaria_scope: "lifetime_window",
      ...(firdariaNode ? { firdaria_nocturnal_node_profile: firdariaNode } : {}), include_zodiacal_releasing: true,
      zr_scope: "lifetime_window", ...(zrYear ? { zr_year_model: zrYear } : {}), include_natal_lots: true,
      include_year_boundaries: true, include_monthly_profection: true, ...decennialsFields(scope.decennials),
    };
    return body;
  }

  /**
   * 「今天」大約落在第幾個足歲年度：依民用生日與裝置日期估，只用來選第一次請求的年度。
   * 真正的年界由伺服器回答；估錯一年時呼叫端依回應再請求一次。
   */
  function estimateCompletedYears(datetime, todayLocalDate) {
    const match = DATE_PATTERN.exec(todayLocalDate || "");
    if (!match || !datetime) return 0;
    const [ty, tm, td] = [Number(match[1]), Number(match[2]), Number(match[3])];
    let n = ty - datetime.year;
    if (tm < datetime.month || (tm === datetime.month && td < datetime.day)) n -= 1;
    return Math.max(0, Math.min(500, n));
  }

  function locateToday(data, todayLocalDate) {
    const year = data.years.find((candidate) => candidate.n === data.requestedYears);
    if (!year) return "year_missing";
    const today = dayNumber(todayLocalDate);
    if (today < dayNumber(year.start.localDate)) return "today_before_year";
    if (today >= dayNumber(year.end.localDate)) return "today_after_year";
    return "today_in_year";
  }


  const LANE_META = Object.freeze({
    annual_profection: Object.freeze({ title: "年度小限", short: "小限", subtitle: "每年一個星座", prefix: "" }),
    monthly_profection: Object.freeze({ title: "月小限", short: "月小限", subtitle: "每月一個星座", prefix: "月小限" }),
    firdaria_level_1: Object.freeze({ title: "法達・主期", short: "法達 1", subtitle: "主期主星", prefix: "主" }),
    firdaria_level_2: Object.freeze({ title: "法達・子期", short: "法達 2", subtitle: "子期主星", prefix: "子" }),
    zr_fortune_level_1: Object.freeze({ title: "命運點・第一層", short: "命運 1", subtitle: "黃道釋放・大期", prefix: "大期" }),
    zr_fortune_level_2: Object.freeze({ title: "命運點・第二層", short: "命運 2", subtitle: "黃道釋放・小期", prefix: "小期" }),
    zr_spirit_level_1: Object.freeze({ title: "精神點・第一層", short: "精神 1", subtitle: "黃道釋放・大期", prefix: "大期" }),
    zr_spirit_level_2: Object.freeze({ title: "精神點・第二層", short: "精神 2", subtitle: "黃道釋放・小期", prefix: "小期" }),
    decennials_level_1: Object.freeze({ title: "十年期・第一層", short: "十年期 1", subtitle: "每段 10 年 9 個月", prefix: "第一層" }),
    decennials_level_2: Object.freeze({ title: "十年期・第二層", short: "十年期 2", subtitle: "依小年分月", prefix: "第二層" }),
  });

  function laneMeta(laneId) { return LANE_META[laneId] || { title: laneId, short: laneId, subtitle: "", prefix: "" }; }

  /**
   * 時間軸格子在這個寬度（px）下顯示什麼：full（符號＋名稱）、name（只寫名稱）、glyph（只畫符號）、none。字級 .8rem 的
   * 一個中文字約 13px，符號 13px，左右留白合計約 10px（timelords.css）。寫得下名稱就寫名稱：沒學過的人認不出星座符號。
   */
  function segmentSize(width, labelLength) {
    const text = 13 * Math.max(1, labelLength);
    if (width >= 10 + 13 + 3 + text) return "full";
    if (width >= 10 + text) return "name";
    return width >= 17 ? "glyph" : "none";
  }

  function labelOf(key) { if (!key) return ""; return SIGN_ORDER.includes(key) ? signName(key) : bodyName(key); }

  function makeItem(fields) {
    return Object.freeze({
      startDay: dayNumber(fields.start.localDate), endDay: dayNumber(fields.end.localDate), kind: "regular",
      truncated: false, parentId: null, aside: null, lot: null, sampleRole: null, ...fields,
    });
  }

  function segmentItem(lane, segment) {
    // 年度小限與月小限的格子旁附上那個星座的守護行星（年主星、月主星）。
    const profection = lane.technique === "annual_profection" || lane.technique === MONTHLY_LANE;
    return makeItem({
      id: segment.id, technique: lane.technique, level: lane.level, lot: lane.lot, sampleRole: segment.sampleRole,
      glyph: segment.labelKey, label: labelOf(segment.labelKey),
      aside: profection && segment.lordKey ? Object.freeze({ glyph: segment.lordKey, label: bodyName(segment.lordKey) }) : null,
      kind: segment.loosing ? "loosing" : "regular", truncated: segment.truncated, parentId: segment.parentId,
      start: segment.start, end: segment.end, record: segment,
    });
  }

  /**
   * 泳道是通用的：由回應的 lanes[] 依序產生（不寫死清單），每條有 id、group、title、short、subtitle、prefix、
   * technique、level 與依起點排序的期間。分樣本的泳道拆成每個樣本一條並列（不合併、不替你挑）。新的技法（例如十年期）只
   * 要在 LANE_META 加名稱、在 describeItem 加一個分支；沒有名稱的泳道以 lane_id 為名照樣畫出。
   */
  function buildLanes(data) {
    const lanes = [];
    data.lanes.filter((lane) => lane.status === "computed").forEach((lane) => {
      const meta = laneMeta(lane.laneId);
      const base = { technique: lane.technique, level: lane.level, group: lane.group, lot: lane.lot, unit: lane.unit, ...meta };
      if (lane.basis === "each_sample") {
        SAMPLE_ORDER.forEach((role) => {
          const segments = lane.segments.filter((segment) => segment.sampleRole === role);
          if (!segments.length) return;
          lanes.push({
            ...base, id: `${lane.laneId}@${role}`, sampleRole: role, title: `${meta.title}（${SAMPLE_SHORT[role]}）`,
            short: `${meta.short}・${SAMPLE_SHORT[role]}`, subtitle: SAMPLE_ROLES[role],
            prefix: meta.prefix ? `${SAMPLE_SHORT[role]}・${meta.prefix}` : SAMPLE_SHORT[role],
            items: segments.map((segment) => segmentItem(lane, segment)),
          });
        });
        return;
      }
      const items = lane.segments.map((segment) => segmentItem(lane, segment));
      // 法達的交點期不分子期：在子期那一條畫一段說明，與主期等長；它不是期間，不進 .ics。
      if (lane.technique === "firdaria" && lane.parentLaneId) {
        const parent = data.lanes.find((candidate) => candidate.laneId === lane.parentLaneId);
        (parent ? parent.segments : []).filter((segment) => segment.node).forEach((segment) => {
          items.push(makeItem({
            id: `${segment.id}#no-sub-periods`, technique: lane.technique, level: lane.level, kind: "node",
            glyph: null, label: "交點期不分子期", parentId: segment.id, start: segment.start, end: segment.end, record: segment,
          }));
        });
      }
      lanes.push({ ...base, id: lane.laneId, sampleRole: null, items });
    });
    return lanes.map((lane) => Object.freeze({
      ...lane, items: Object.freeze(lane.items.slice().sort((a, b) => a.startDay - b.startDay || compareIds(a.id, b.id))),
    }));
  }

  function releasingDiffersBetweenSamples(data) {
    return data.lanes.some((lane) => lane.lot && lane.status === "computed" && lane.basis === "each_sample");
  }

  function buildModel(data, todayLocalDate) {
    // 只收 adaptAnnualSource 由相容回應做出的資料：畫面、.ics 與表都從這個模型出來。
    if (!data || typeof data.identity !== "string") fail("資料不是由相容的年度回應建成");
    const todayDay = dayNumber(todayLocalDate);
    const years = Object.freeze(data.years.map((year) => Object.freeze({
      ...year, startDay: dayNumber(year.start.localDate), endDay: dayNumber(year.end.localDate),
    })));
    const currentIndex = years.findIndex((year) => year.startDay <= todayDay && todayDay < year.endDay);
    const lanes = Object.freeze(buildLanes(data));
    const byId = new Map();
    lanes.forEach((lane) => lane.items.forEach((item) => byId.set(item.id, Object.freeze({ ...item, laneId: lane.id }))));
    const starts = lanes.flatMap((lane) => lane.items.map((item) => item.startDay));
    const ends = lanes.flatMap((lane) => lane.items.map((item) => item.endDay));
    return Object.freeze({
      data, precision: data.precision, today: todayLocalDate, todayDay, years, currentIndex, lanes, byId,
      domain: Object.freeze({
        startDay: years.length ? years[0].startDay : (starts.length ? Math.min(...starts) : todayDay),
        // 一生的時間軸畫到最後一個年度的終點；更遠的期間（例如法達第二輪的尾段）只露出開頭。
        endDay: years.length ? years[years.length - 1].endDay : (ends.length ? Math.max(...ends) : todayDay + 1),
      }),
    });
  }

  function laneById(model, laneId) { return model.lanes.find((lane) => lane.id === laneId) || null; }

  function itemAt(model, laneId, day) {
    const lane = laneById(model, laneId);
    if (!lane) return null;
    return lane.items.find((item) => item.startDay <= day && day < item.endDay) || null;
  }

  function itemsInYear(model, laneId, index) {
    const lane = laneById(model, laneId);
    const year = model.years[index];
    if (!lane || !year) return [];
    return lane.items.filter((item) => item.startDay < year.endDay && item.endDay > year.startDay);
  }

  /** 摘要卡看的那一天：今年看今天，其他年度看那一年的起點。 */
  function referenceDay(model, index) { return index === model.currentIndex ? model.todayDay : model.years[index].startDay; }

  // 人生時間軸：每種技法只取第一層，排在同一條足歲軸上並列；不合併、不比對重合、不加任何解讀。
  const LIFE_YEARS = 90;
  const LIFE_LEAD = "下面幾種時間主星各自獨立計算，這裡只把它們排在同一條時間軸上並列對照，不合併，也不互相解讀。";
  const LIFE_LANES = Object.freeze({
    annual_profection: Object.freeze({ title: "年度小限", short: "小限", note: "每年換一個星座" }),
    firdaria_level_1: Object.freeze({ title: "法達", short: "法達", note: "主期，75 年一輪" }),
    zr_fortune_level_1: Object.freeze({ title: "黃道釋放・命運點", short: "命運點", note: "第一層大期" }),
    zr_spirit_level_1: Object.freeze({ title: "黃道釋放・精神點", short: "精神點", note: "第一層大期" }),
    decennials_level_1: Object.freeze({ title: "十年期", short: "十年期", note: "每段 10 年 9 個月" }),
  });

  /** 某一天是幾足歲：落在哪個年度（太陽回歸年界）就是那個年度的 n；最後一年之後是 n + 1。 */
  function ageOnDay(model, day) {
    const years = model.years;
    if (!years.length) return null;
    if (day < years[0].startDay) return years[0].n;
    const year = years.find((candidate) => candidate.startDay <= day && day < candidate.endDay);
    return year ? year.n : years[years.length - 1].n + 1;
  }

  /**
   * 人生時間軸的資料：出生（或回應涵蓋的第一個年度）起到 90 足歲（不足則到回應的最後一個年度），
   * 每種技法的第一層一條；分樣本的泳道照樣分成幾條並列。期間只截到這個範圍，日期照回應原值。
   */
  function lifeOverview(model, options = {}) {
    if (!model || !model.years.length) return null;
    const span = Number.isInteger(options.years) && options.years > 0 ? options.years : LIFE_YEARS;
    const first = model.years[0];
    const last = model.years[Math.min(model.years.length - 1, span - 1)];
    const startDay = first.startDay;
    const endDay = last.endDay;
    const lanes = model.lanes.filter((lane) => lane.level === 1 && LIFE_LANES[lane.id.split("@")[0]]).map((lane) => {
      const meta = LIFE_LANES[lane.id.split("@")[0]];
      const suffix = lane.sampleRole ? `（${SAMPLE_SHORT[lane.sampleRole]}）` : "";
      const items = lane.items.filter((item) => item.kind !== "node" && item.startDay < endDay && item.endDay > startDay)
        .map((item, index) => Object.freeze({
          id: item.id, index, label: item.label, glyph: item.glyph, lord: item.aside ? item.aside.label : null,
          lordGlyph: item.aside ? item.aside.glyph : null, startDay: Math.max(item.startDay, startDay),
          endDay: Math.min(item.endDay, endDay), start: item.start.localDate, end: item.end.localDate,
          startAge: ageOnDay(model, item.startDay), endAge: ageOnDay(model, item.endDay),
          continuesAfter: item.endDay > endDay, loosing: item.kind === "loosing",
          // 年度小限回到上升星座（每 12 年）：只是數到第 1 個星座，不是任何判斷。
          restart: lane.technique === "annual_profection" && item.record.detail
            && item.record.detail.profected_place === 1 && item.record.detail.completed_years > 0,
          current: item.startDay <= model.todayDay && model.todayDay < item.endDay,
        }));
      return Object.freeze({
        id: lane.id, technique: lane.technique, sampleRole: lane.sampleRole, title: `${meta.title}${suffix}`,
        short: meta.short, sample: lane.sampleRole ? SAMPLE_SHORT[lane.sampleRole] : null, note: meta.note, items: Object.freeze(items),
      });
    }).filter((lane) => lane.items.length);
    const ticks = model.years.filter((year) => year.startDay >= startDay && year.startDay < endDay && year.n % 10 === 0)
      .map((year) => Object.freeze({ age: year.n, day: year.startDay, calendarYear: year.start.localDate.slice(0, 4) }));
    if (last.n % 10 === 9) { ticks.push(Object.freeze({ age: last.n + 1, day: endDay, calendarYear: last.end.localDate.slice(0, 4) })); }
    const today = model.todayDay >= startDay && model.todayDay < endDay
      ? Object.freeze({ day: model.todayDay, date: model.today, age: ageOnDay(model, model.todayDay) }) : null;
    return Object.freeze({
      startDay, endDay, startAge: first.n, endAge: last.n + 1, lanes: Object.freeze(lanes), ticks: Object.freeze(ticks), today,
      yearNote: lifeYearNote(model.data),
    });
  }

  // 年長照回應這次實際用的寫：黃道釋放的一年可以改選，十年期固定。
  function lifeYearNote(data) {
    const days = (technique, fallback) => {
      const value = (((data[technique] || {}).head || {}).year_model || {}).days_per_year;
      return Number.isFinite(value) ? String(value) : fallback;
    };
    const zr = days("releasing", null), decennials = days("decennials", "360");
    const lengths = zr === decennials ? `黃道釋放與十年期一年 ${zr} 日`
      : `${zr ? `黃道釋放一年 ${zr} 日，` : ""}十年期一年 ${decennials} 日`;
    return `底色兩種紙色交替只為分辨相鄰兩段，不代表好壞。各技法的年長不同（法達與小限以太陽回歸為年界，${lengths}），所以同一個年數的分界不一定對齊。日期是${DATE_NOTE}。`;
  }

  /** 一段的白話描述：技法、主星（小限另附年主星）、起訖日期與足歲。報讀器名稱、讀出列與表格共用。 */
  function lifeItemText(lane, item) {
    const ruler = item.lord ? `${item.label}（年主星 ${item.lord}）` : item.label;
    const ages = item.startAge === item.endAge - 1 && lane.technique === "annual_profection"
      ? `${item.startAge} 足歲這一年` : `${item.startAge} 至 ${item.endAge} 足歲`;
    const marks = [item.loosing ? "解鎖" : "", item.continuesAfter ? "延續到圖的範圍之後" : ""].filter(Boolean);
    return `${lane.title}：${ruler}，${item.start} 到 ${item.end}（${ages}）${marks.length ? `，${marks.join("，")}` : ""}`;
  }

  // 文字文字片段是陣列：字串、{ glyph }（符號鍵）、{ strong }、{ mono }、{ small }。畫面逐段建元素，不經過 HTML 字串。

  const g = (key) => (key ? { glyph: key } : "");
  const named = (key, name) => [g(key), name];
  const formatYears = (value, digits) => Number(value).toFixed(digits);

  function dateRange(moments, withTime) {
    // 時刻只在兩端都有時才印，不讓一端到分鐘、另一端只到日。
    const timed = withTime && moments.start.localTime && moments.end.localTime;
    const part = (moment) => (timed ? `${moment.localDate} ${moment.localTime}` : moment.localDate);
    return { mono: `${part(moments.start)} → ${part(moments.end)}` };
  }

  function pairAt(model, lot, day, role) {
    const suffix = role ? `@${role}` : "";
    return {
      l1: itemAt(model, `zr_${lot}_level_1${suffix}`, day), l2: itemAt(model, `zr_${lot}_level_2${suffix}`, day),
    };
  }

  function pairRuns(entry) {
    return [
      ...(entry.l1 ? named(entry.l1.glyph, entry.l1.label) : ["—"]), "／",
      ...(entry.l2 ? named(entry.l2.glyph, entry.l2.label) : ["（小期未載入）"]),
    ];
  }

  /** 某一天的小限：精確時刻或三樣本一致時一段；三樣本不同時每個樣本一段。 */
  function profectionAt(model, day) {
    const single = itemAt(model, "annual_profection", day);
    if (single) return { single, samples: [] };
    const samples = SAMPLE_ORDER.map((role) => itemAt(model, `annual_profection@${role}`, day)).filter(Boolean);
    return { single: null, samples };
  }

  const PROFECTION_GLOSS = "年度小限：出生那一刻從東方地平線升起的星座叫「上升星座」。年度小限從它開始，每過一歲往後換一個星座，12 年繞一圈。古書替每個星座指定一顆行星來「管」它；今年輪到的星座由哪顆行星管，那顆行星就叫「年主星」。月小限（monthly profection）把這一年再分成 12 個月，每月往後換一個星座。";
  const RELEASING_GLOSS = "黃道釋放（zodiacal releasing；現代名稱，Valens 本人沒有用這個詞）：從命運點（Lot of Fortune，也譯福點、幸運點）或精神點（Lot of Spirit）所在的星座起，依各星座的年數往後分期；第一層是大期，第二層是大期內的小期。";

  function summaryTiles(model, index) {
    const year = model.years[index];
    if (!year) return [];
    const day = referenceDay(model, index);
    const data = model.data;
    const tiles = [];
    const profection = profectionAt(model, day);
    tiles.push({
      key: "age", select: profection.single ? profection.single.id : null, title: "年齡", value: [`${year.n} 足歲`],
      sub: [`第 ${year.n + 1} 年・`, { mono: year.start.localDate }, " 起"],
      gloss: "年齡依太陽回歸計：每次太陽回到出生時的位置，就滿一歲。",
    });
    if (profection.single) {
      const item = profection.single;
      const month = itemAt(model, MONTHLY_LANE, day);
      tiles.push({
        key: "profection", select: item.id, title: "年度小限・年主星", value: named(item.glyph, item.label),
        sub: [`從上升星座數第 ${item.record.detail.profected_place} 個・`,
          ...(item.aside ? ["年主星 ", ...named(item.aside.glyph, item.aside.label)] : ["年主星：這次沒有列出（用恆星黃道時不列）"]),
          ...(month ? [`；月小限第 ${month.record.detail.month_of_year} 個月 `, ...named(month.glyph, month.label),
            ...(month.aside ? ["（月主星 ", ...named(month.aside.glyph, month.aside.label), "）"] : [])] : [])],
        gloss: PROFECTION_GLOSS,
      });
    } else if (profection.samples.length) {
      tiles.push({
        key: "profection", select: profection.samples[0].id, title: "年度小限・年主星", value: ["三個時刻不同"],
        sub: profection.samples.flatMap((item, position) => [
          position ? "；" : "", `${SAMPLE_SHORT[item.sampleRole]} `, ...named(item.glyph, item.label),
        ]),
        gloss: PROFECTION_GLOSS,
      });
    } else { tiles.push(unavailableTile("profection", "年度小限・年主星", data.profection)); }
    const fird1 = itemAt(model, "firdaria_level_1", day);
    const fird2 = itemAt(model, "firdaria_level_2", day);
    if (data.firdaria.status === "computed" && fird1) {
      tiles.push({
        key: "firdaria", select: fird2 && fird2.kind !== "node" ? fird2.id : fird1.id, title: "法達・主期／子期",
        value: named(fird1.glyph, fird1.label), sub: fird2 && fird2.kind !== "node"
          ? ["子期 ", ...named(fird2.glyph, fird2.label), "（", { mono: fird2.start.localDate }, " 起）"]
          : ["這一段由月交點輪值，不再細分"],
        gloss: "法達（firdaria）：把人生依古書定好的年數，輪流分給七顆行星（太陽、月亮、水星、金星、火星、木星、土星）和兩個月交點（月亮軌道和太陽軌道相交的兩點），一輪 75 年。每顆行星分到的一大段叫「主期」，再平分成七小段叫「子期」；輪值的行星分別叫主期主星、子期主星。",
      });
    } else { tiles.push(unavailableTile("firdaria", "法達・主期／子期", data.firdaria)); }
    if (data.releasing.status === "computed" && !releasingDiffersBetweenSamples(data)) {
      const fortune = pairAt(model, "fortune", day, null);
      const spirit = pairAt(model, "spirit", day, null);
      tiles.push({
        key: "releasing", select: (fortune.l2 || fortune.l1 || {}).id || null, title: "黃道釋放・大期／小期",
        value: [{ small: "命運點 " }, ...pairRuns(fortune)], sub: ["精神點 ", ...pairRuns(spirit)], gloss: RELEASING_GLOSS,
      });
    } else if (data.releasing.status === "computed") {
      const sub = [];
      SAMPLE_ORDER.forEach((role) => {
        const fortune = pairAt(model, "fortune", day, role);
        if (!fortune.l1 && !fortune.l2) return;
        if (sub.length) sub.push("；");
        sub.push(`${SAMPLE_SHORT[role]} `, ...pairRuns(fortune));
      });
      tiles.push({
        key: "releasing", select: null, title: "黃道釋放・大期／小期", value: ["三個時刻不同"],
        sub: sub.length ? ["命運點：", ...sub] : ["見時間軸上並列的三組"], gloss: RELEASING_GLOSS,
      });
    } else { tiles.push(unavailableTile("releasing", "黃道釋放・大期／小期", data.releasing)); }
    return tiles;
  }

  /**
   * 第 index 年預先選取的期間：站內連結指定了技法（technique，閉集見 result-chapters.js）而這一年有它的
   * 期間就選它；否則照舊先選法達，再否則選第一張可選的卡。十年期沒有摘要卡，取時間軸上的那一段。
   */
  function preferredSelection(model, index, technique) {
    const tiles = summaryTiles(model, index);
    const pick = (key) => (tiles.find((tile) => tile.key === key && tile.select) || {}).select || null;
    let chosen = null;
    if (technique === "decennials" && model.years[index]) {
      const day = referenceDay(model, index);
      const item = itemAt(model, "decennials_level_2", day) || itemAt(model, "decennials_level_1", day);
      chosen = item ? item.id : null;
    } else if (technique) { chosen = pick(technique); }
    return chosen || pick("firdaria") || (tiles.find((tile) => tile.select) || {}).select || null;
  }

  /**
   * 一頁摘要的一行：第幾年由誰輪值（年度小限與年主星、法達、命運點的黃道釋放、十年期）。只寫輪值，
   * 不寫任何日期；三個時刻不同的照實寫，沒有算的技法略過。第二層還沒取到時只寫第一層。
   */
  function briefLine(model, index) {
    const year = model.years[index];
    if (!year) return null;
    const day = referenceDay(model, index);
    const data = model.data;
    const pair = (first, second) => `${first.label}${second ? `／${second.label}` : ""}`;
    const parts = [];
    const profection = profectionAt(model, day);
    if (profection.single) {
      const item = profection.single;
      parts.push(`年度小限 ${item.label}${item.aside ? `（年主星 ${item.aside.label}）` : ""}`);
    } else if (profection.samples.length) { parts.push("年度小限：三個時刻不同"); }
    const fird1 = itemAt(model, "firdaria_level_1", day);
    const fird2 = itemAt(model, "firdaria_level_2", day);
    if (data.firdaria.status === "computed" && fird1) { parts.push(`法達 ${pair(fird1, fird2 && fird2.kind !== "node" ? fird2 : null)}`); }
    if (data.releasing.status === "computed") {
      const fortune = pairAt(model, "fortune", day, null);
      if (releasingDiffersBetweenSamples(data)) parts.push("黃道釋放：三個時刻不同");
      else if (fortune.l1) parts.push(`黃道釋放（命運點）${pair(fortune.l1, fortune.l2)}`);
    }
    const decennial = itemAt(model, "decennials_level_1", day);
    if (decennial) parts.push(`十年期 ${pair(decennial, itemAt(model, "decennials_level_2", day))}`);
    if (!parts.length) return null;
    return `時間主星，第 ${year.n + 1} 年（${year.n} 足歲）的輪值：${parts.join("・")}`;
  }

  function unavailableTile(key, title, state) {
    return {
      key, select: null, title, value: ["沒有算"],
      sub: [state.status === "not_applicable" ? (NOT_APPLICABLE[state.reason] || `理由碼 ${state.reason}`) : "這次沒有請求。"], gloss: "",
    };
  }

  function referenceNote(model, index) {
    const year = model.years[index];
    if (!year) return "";
    return index === model.currentIndex
      ? `上面四格依「今天（${model.today}，依你的裝置日期）」列出年齡與當時輪值的期間；十年期見下方的時間軸或年表。`
      : `上面四格依「第 ${year.n + 1} 年起點（${year.start.localDate}）」列出年齡與當時輪值的期間；十年期見下方的時間軸或年表。`;
  }

  function yearTitle(model, index) {
    const year = model.years[index];
    return year ? `第 ${year.n + 1} 年（${year.n} 足歲）` : "";
  }

  function yearRange(model, index) {
    const year = model.years[index];
    if (!year) return [];
    const timed = year.start.localTime && year.end.localTime;
    return ["本年度 ", dateRange(year, true), timed ? "（太陽回歸的時刻，出生地時間）" : `（太陽回歸那一天，${DATE_NOTE}）`];
  }

  function firdariaSequence(data) {
    const lane = data.lanes.find((candidate) => candidate.laneId === "firdaria_level_1");
    if (!lane || !lane.segments.length) return "";
    const cycle = lane.segments.filter((segment) => segment.periodId.split(".")[0] === lane.segments[0].periodId.split(".")[0]);
    return cycle.map((segment) => `${bodyName(segment.labelKey)} ${formatYears(segment.detail.end_year - segment.detail.start_year, 0)}`).join("、");
  }

  // 細節欄的出處，一行一條：[方法出處登錄裡那條引文的開頭（一行涵蓋幾條時逐條列出；沒有引文為 null）, 畫面的字, 核到哪
  // 一層（後端閉集）, 句尾補註]。句尾「核到：…」取 labels.js 的 source_reading，與結果頁每一條出處同一個說法；整合測試
  // 逐行核對層級與公開方法出處登錄裡那幾條引文相同。鍵是技法在登錄裡的條目（回應的 source_ref）。
  const SOURCE_LINES = Object.freeze({
    annual_profection: Object.freeze([
      ["Vettius Valens, Anthologies IV.11",
        "依古希臘占星家 Valens 的書《占星選集》（Anthologiae，第四卷第 11 章）：書裡用「第 35 年」舉例；我們對照希臘原文，那是滿 34 歲的那一年，和本站的數法相同。",
        "original_language_read", "（Kroll 1908 希臘文的這一句；另讀 Riley 英譯；Pingree 校勘本未核）"],
      ["Firmicus Maternus, Mathesis II.27.3-4, II.28.3",
        "古羅馬作家 Firmicus 的《Mathesis》（書名原意「學問」，第二卷第 27–28 章）也寫了這個方法。",
        "secondary_only", "（依本站的研究筆記，還沒有重讀原書）"],
      [null, "每一年從太陽回到出生時位置的那一刻算起；這個時刻由本站的星曆程式算出，測試另拿美國太空總署噴射推進實驗室（JPL）公開的星曆核對。"],
    ]), firdaria: Object.freeze([
      ["al-Biruni, Book of Instruction in the Elements of the Art of Astrology §438-439",
        "al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）§438–439：期間表、日夜順序；交點不分子期。",
        "translation_read", "（Wright 1934 英譯，書頁影像）"], ["Guido Bonatti, De astronomia (Basel 1550), the nativities treatise",
        "Bonatti《天文學之書》（De astronomia，1550 年巴塞爾版）本命論第 3 章：各期年數、日盤順序、75 年後重來；夜盤「一切照日盤」。",
        "original_language_read", "（拉丁原文，第 813–814 欄）"], ["Abu Ma'shar, On the Revolutions of the Years of Nativities",
        "Abū Maʿshar《論本命年的回歸》（Kitāb taḥāwīl sinī al-mawālīd；有 Dykes 英譯，收在 Persian Nativities IV）：現存最完整的操作說明。",
        "secondary_only", "（本書與英譯都未核）"],
    ]), zodiacal_releasing: Object.freeze([
      [["Vettius Valens, Anthologies IV.4", "Valens IV.7", "Valens IV.8"],
        "Vettius Valens《占星選集》（Anthologiae）IV.4（起點、星座年數、小期、解鎖到對宮）、IV.7（從命運點數位置）、IV.8（例盤）。",
        "translation_read", "（Riley 英譯，公開的重排本；Pingree 希臘文未核）"], [["Valens IV.9", "Valens IV.10"],
        "同書 IV.9（分配年 360 日）、IV.10（更細的層級）。",
        "original_language_read", "（Kroll 1908 希臘文；另讀 Riley 英譯）"],
      [null, "「黃道釋放」這個名稱與「第一層」「第二層」的分層名稱，是現代（Schmidt、Brennan）的整理，不是 Valens 的用語。"],
    ]), decennials: Object.freeze([
      [["Vettius Valens, Anthologies VI.6", "Valens VI.7"],
        "Vettius Valens《占星選集》（Anthologiae）VI.6–VI.7（Pingree 的章號；Kroll 校勘本為 VI.5–VI.7）：每段 10 年 9 個月、依出生時的黃道順序、分配年 360 日。",
        "translation_read", "（Riley 英譯，公開的重排本；希臘文未核）"], ["Firmicus Maternus, Mathesis II.26-27",
        "Firmicus Maternus《Mathesis》II.26–27：日盤從太陽、夜盤從月亮起，每段再依小年分成月。",
        "original_language_read", "（拉丁文本）"]]), monthly_profection: Object.freeze([["Vettius Valens, Anthologies IV.28",
        "古希臘占星家 Valens 的《占星選集》（Anthologiae，第四卷第 28 章）：看此刻的太陽離出生時的太陽多遠，從年度小限的星座數同樣的距離，就是這個月；夜盤改用月亮，本站沒有採用。",
        "translation_read", "（Riley 英譯；希臘文未核）"], ["Abu Ma'shar, On the Revolutions of the Years of Nativities",
        "中世紀占星家 Abū Maʿshar 的《論本命年的回歸》（Kitāb taḥāwīl sinī al-mawālīd）：年度小限的星座也是第 1 個月，太陽每多走 30 度換下一個月。",
        "secondary_only", "（只讀到英譯者 Dykes 的介紹，原書未核）"], ["al-Biruni, Book of Instruction",
        "al-Bīrūnī 的《占星術入門》（Kitāb al-Tafhīm，第 522 節）：每個月從太陽走到出生時同一度數算起；同一節另有一年 13 個月的分法，本站沒有算。",
        "translation_read", "（Wright 1934 英譯）"],
      // 登錄裡這一節只有一條 Ptolemy；只寫作者，書名英文不進畫面字串表。
      ["Ptolemy",
        "Ptolemy 的《占星四書》（Tetrabiblos）第四卷第 10 章：每 28 天推一個星座，和太陽回歸對不齊，本站沒有算。",
        "translation_read", "（Robbins 英譯，在 LacusCurtius 網頁讀了這一章全文）"],
    ]),
  });
  const SOURCES = Object.freeze(Object.fromEntries(Object.entries(SOURCE_LINES)
    .map(([ref, rows]) => [ref, Object.freeze(rows.map(Labels.sourceLine))])));
  // 夜盤的交點排法：依回應這次實際用的那一種寫，不依選單。
  const FIRDARIA_NIGHT_SOURCE = Object.freeze({
    abu_mashar_nodes_after_mercury_v1: "夜盤兩個月交點排在火星之後，是 Zoller 對 Bonatti 的讀法，不是 Bonatti 的原文；本站預設排在水星之後，這次用的就是預設。",
    bonatti_reading_nodes_after_mars_v1: "這次依你的選擇，夜盤兩個月交點排在火星之後：這是 Zoller 對 Bonatti 的讀法，不是 Bonatti 的原文；本站預設排在水星之後（al-Bīrūnī 的表）。",
  });

  // 十年期這次用的起點（回應的 start_profile.profile），白話一句。
  const DECENNIALS_START_TEXT = Object.freeze({
    firmicus_sect_light_v1: "這次的起點是日盤從太陽、夜盤從月亮（Firmicus 的做法，本站預設）。",
    valens_first_after_asc_v1: "這次的起點是上升點之後的第一顆行星（Valens 在兩個光體都不合用時的做法；本站不判斷光體合不合用）。",
    user_selected_planet_v1: "這次的起點是你自己指定的行星。",
  });

  // 「校勘本」第一次出現時的白話註解。細節欄一次只顯示一段，所以每一段的出處在第一次出現的地方附一次；
  // 時間主星表不帶註解，方法頁在全頁第一次出現的地方另附。
  const EDITION_GLOSS = "校勘本（學者比對多份古抄本後整理出的版本）";

  function glossFirstEdition(lines) {
    const index = lines.findIndex((line) => typeof line === "string" && line.includes("校勘本"));
    if (index >= 0) lines[index] = lines[index].replace("校勘本", EDITION_GLOSS);
    return lines;
  }

  /** 收據：回應裡這一段的原值（頁面投影的期間只帶出生地日期；UTC 與儒略日在 detailed 回應）。 */
  function segmentReceipt(segment) {
    return {
      lane_id: segment.laneId, id: segment.periodId, sample_role: segment.sampleRole, label_key: segment.labelKey,
      lord_key: segment.lordKey, start: segment.start.localDate, end: segment.end.localDate, flags: segment.flags,
      ...Object.fromEntries(Object.entries(segment.detail).map(([key, value]) => [`detail.${key}`, value])),
    };
  }

  function headReceipt(head, keys) {
    const out = {};
    keys.forEach((key) => { if (head && head[key] !== undefined) out[key] = head[key]; });
    return out;
  }

  /** 一段期間的細節：類別、標題、欄位、白話算法、出處與收據（回應原值）。角宮位置只出現在這裡，不畫在時間軸上。 */
  function describeItem(model, id) {
    const item = model.byId.get(id);
    if (!item) return null;
    const data = model.data;
    const detail = { id, technique: item.technique, kind: "", title: [], rows: [], explanation: [], sources: [], receipt: {} };
    const sampleNote = item.sampleRole ? `（出生時刻取${SAMPLE_ROLES[item.sampleRole]}）` : "";
    if (item.technique === "annual_profection") {
      const facts = item.record.detail;
      const n = facts.completed_years;
      const year = model.years.find((candidate) => candidate.n === n);
      const range = year || item;
      detail.kind = `年度小限${sampleNote}`;
      detail.title = [`第 ${n + 1} 年：`, ...named(item.glyph, item.label)];
      if (item.aside) detail.title.push("（年主星 ", ...named(item.aside.glyph, item.aside.label), "）");
      detail.rows.push(["起訖", [dateRange(range, true)]]);
      detail.rows.push(["長度", ["一年：從太陽回到出生時位置的那一刻，到下一次回到同一位置"]]);
      detail.rows.push(["落在", [`從上升星座數第 ${facts.profected_place} 個星座（第 ${facts.profected_place} 宮；這裡一個星座算一宮，叫「整宮」）`]]);
      if (item.aside) detail.rows.push(["年主星", [...named(item.aside.glyph, item.aside.label), `（古書指定管${item.label}的行星）`]]);
      const asc = data.natal.ascendantSign;
      detail.explanation = [
        "你出生那一刻，從東方地平線升起的星座是", { strong: asc ? signName(asc) : "（未知）" },
        `（上升星座）。年度小限從它開始：出生後第一年就是上升星座本身，之後每滿一歲往後換一個星座，12 年繞一圈。這一年你已滿 ${n} 歲，數到第 ${facts.profected_place} 個星座`,
        { strong: item.label }, "；古書指定管這個星座的行星，就是這一年的年主星。", year && year.start.localTime
          ? "這一年從太陽回到出生時位置的那一刻開始，到下一次回到同一位置為止；這裡列到分鐘。"
          : "這一年從太陽回到出生時位置的那一天開始，到下一次回到同一位置的那一天為止。",
      ];
      detail.sources = SOURCES.annual_profection.slice();
      const head = data.profection.head || {};
      detail.receipt = {
        ...segmentReceipt(item.record), solar_return_profile: data.yearBoundary ? data.yearBoundary.profile : null,
        ...headReceipt(head, ["profile", "method_status", "method_provenance"]), interpretation: null,
      };
      glossFirstEdition(detail.sources);
    } else if (item.technique === MONTHLY_LANE) {
      const facts = item.record.detail;
      const n = facts.completed_years;
      const month = facts.month_of_year;
      const head = data.monthly.head || {};
      const parent = item.parentId ? model.byId.get(item.parentId) : null;
      const yearSign = parent ? parent.label : "";
      const solar = head.profile !== "monthly_profection_return_year_twelfths_v1";
      detail.kind = `月小限${sampleNote}`;
      detail.title = [`第 ${n + 1} 年第 ${month} 個月：`, ...named(item.glyph, item.label)];
      if (item.aside) detail.title.push("（月主星 ", ...named(item.aside.glyph, item.aside.label), "）");
      detail.rows.push(["起訖", [dateRange(item, false)]]);
      detail.rows.push(["長度", [solar
        ? "太陽在黃道上走 30 度的時間（約 29 到 32 天，太陽走得快慢不同）"
        : "一年的十二分之一：從這次太陽回到出生時位置，到下一次回到同一位置，平均分成 12 段"]]);
      detail.rows.push(["落在", [`這一年的第 ${month} 個月：從年度小限星座數第 ${month} 個星座（從上升星座數是第 ${facts.profected_place} 個）`]]);
      if (item.aside) detail.rows.push(["月主星", [...named(item.aside.glyph, item.aside.label), `（古書指定管${item.label}的行星，也就是它的守護行星）`]]);
      detail.explanation = [
        "月小限把年度小限再細分到「月」。這一年的年度小限星座是", { strong: yearSign || "（見年度小限）" },
        "，它也是這一年的第 1 個月；之後每個月往後換一個星座，12 個月繞一圈，下一次太陽回歸時再從新一年的年度小限星座數起。", solar
          ? "每個月從太陽比出生時的位置再往前走 30 度的那一刻開始：第 1 個月從太陽回到出生時位置的那一刻開始，太陽多走 30 度就進入第 2 個月，以此類推。所以這裡的「月」是太陽走 30 度的時間，和日曆上的月份無關。"
          : "這次選的是另一種分法：把這一年（從這次太陽回歸到下一次）平均分成 12 段，每段一個月，和日曆上的月份無關。",
        `這是第 ${month} 個月，數到`, { strong: item.label }, "；古書指定管這個星座的行星（守護行星），就是這個月的月主星。",
      ];
      detail.sources = SOURCES.monthly_profection.slice();
      glossFirstEdition(detail.sources);
      detail.receipt = {
        ...segmentReceipt(item.record), solar_return_profile: data.yearBoundary ? data.yearBoundary.profile : null,
        ...headReceipt(head, ["profile", "method_status", "method_provenance"]),
        boundary_rule: (head.month_model || {}).boundary_rule || null, interpretation: null,
      };
    } else if (item.technique === "firdaria") {
      const levelOne = item.level === 1;
      const node = item.kind === "node";
      const parentItem = levelOne || node ? null : model.byId.get(item.parentId);
      const parent = node ? item.record : levelOne ? item.record : (parentItem ? parentItem.record : null);
      const head = data.firdaria.head || {};
      const parentName = parent ? bodyName(parent.labelKey) : "";
      detail.kind = `${levelOne ? "法達・主期" : "法達・子期"}${sampleNote}`;
      if (node) detail.title = [`${parentName}期：不分子期`];
      else if (levelOne) detail.title = [...named(item.glyph, item.label), "主期"];
      else detail.title = [...named(item.glyph, item.label), `子期（屬${parentName}主期）`];
      detail.rows.push(["起訖", [dateRange(item, false)]]);
      if (levelOne || node) {
        detail.rows.push(["足歲", [{ mono: `${formatYears(parent.detail.start_year, 0)} → ${formatYears(parent.detail.end_year, 0)}` }]]);
        detail.rows.push(["主期主星", named(parent.labelKey, parentName)]);
      } else {
        detail.rows.push(["主期主星", parent ? named(parent.labelKey, parentName) : ["—"]]);
        detail.rows.push(["子期主星", named(item.glyph, item.label)]);
      }
      const day = data.natal.isDay;
      const sectText = day === false ? "你出生時太陽在地平線下（古書叫「夜盤」），所以法達從月亮開始"
        : "你出生時太陽在地平線上（古書叫「日盤」），所以法達從太陽開始";
      if (levelOne) {
        detail.explanation = [
          `${sectText}，依序輪下去；每一段的年數是古書定好的：${firdariaSequence(data)} 年，加起來 75 年。75 年後照同一個順序再輪一次（中世紀占星家 Bonatti 的寫法）。`,
          `${item.label}這一段從滿 ${formatYears(parent.detail.start_year, 0)} 歲到滿 ${formatYears(parent.detail.end_year, 0)} 歲。換成日期時，「滿幾歲」那一天，就是那一年太陽回到出生時位置的那一刻。`,
        ];
      } else if (node) { detail.explanation = ["月交點的期間不再細分（交點期不分子期）。"]; } else {
        detail.explanation = [
          `主期${parentName}${parent ? `（${formatYears(parent.detail.start_year, 0)} 到 ${formatYears(parent.detail.end_year, 0)} 足歲）` : ""}平均切成 7 段。第一段給主期行星自己，其餘依迦勒底序（土、木、火、日、金、水、月）往下輪。`,
          "不是整數的年份，在所屬的那一個太陽回歸年內按比例換成日期（本站的計算慣例）。",
        ];
      }
      detail.sources = SOURCES.firdaria.slice();
      if (day === false) detail.sources.push(FIRDARIA_NIGHT_SOURCE[head.nocturnal_node_profile] || FIRDARIA_NIGHT_SOURCE[FIRDARIA_NODE_PROFILES[0]]);
      glossFirstEdition(detail.sources);
      detail.receipt = {
        ...segmentReceipt(node ? parent : item.record),
        ...headReceipt(head, ["profile", "nocturnal_node_profile", "nocturnal_node_profile_input", "nocturnal_node_profile_applies", "method_status", "method_provenance"]),
        interpretation: null,
      };
    } else if (item.technique === "zodiacal_releasing") {
      const segment = item.record;
      const facts = segment.detail;
      const lot = item.lot;
      const head = data.releasing.head || {};
      const levelOne = item.level === 1;
      const yearModel = head.year_model || {};
      const daysPerYear = yearModel.days_per_year;
      const daysPerMonth = yearModel.days_per_level_2_unit;
      detail.kind = `黃道釋放・${LOT_NAMES[lot]}・${levelOne ? "第一層（大期）" : "第二層（小期）"}${sampleNote}`;
      detail.title = [...named(item.glyph, item.label)];
      if (segment.lordKey) detail.title.push("（主星 ", ...named(segment.lordKey, bodyName(segment.lordKey)), "）");
      detail.rows.push(["起訖", [dateRange(item, false)]]);
      const unit = levelOne ? "年" : " 個月";
      const unitNote = levelOne ? `（每年 ${daysPerYear} 日，不是日曆年）` : `（每月 ${daysPerMonth} 日）`;
      detail.rows.push(["長度", [`${facts.nominal_units}${unit}${unitNote}`
        + (item.truncated ? `；${levelOne ? "上一層" : "所屬的大期"}先結束，這一段實際只走了 ${facts.effective_units}${unit}` : "")]]);
      if (segment.lordKey) detail.rows.push(["主星", [...named(segment.lordKey, bodyName(segment.lordKey)), `（古書指定管${item.label}的行星）`]]);
      const position = [`從命運點所在星座數第 ${facts.position_from_fortune} 個・${ANGULARITY[facts.angularity_from_fortune] || facts.angularity_from_fortune}`];
      if (lot === "spirit") position.push(`；從精神點數第 ${facts.position_from_start_lot} 個`);
      position.push({ small: "Valens《占星選集》（Anthologiae）IV.7 說，從命運點數第 1、4、7、10 個星座的位置最有力。本站照列位置，不另標現代的「高峰期」分級。" });
      detail.rows.push(["位置", position]);
      const parent = levelOne ? null : model.byId.get(item.parentId);
      const parentSign = parent ? parent.label : "";
      if (levelOne) {
        const startSign = data.releasing.startSigns[lot];
        detail.explanation = [
          `從${LOT_NAMES[lot]}所在的`, { strong: startSign ? signName(startSign) : "星座" },
          `起，依黃道順序每個星座分到固定年數。這裡的「年」是 ${daysPerYear} 日`,
          yearModel.profile === "zr_year_360_days_v1" ? "（Valens 的分配年）" : "",
          `，不是日曆年：${item.label}分到 ${facts.nominal_units} 年。`,
        ];
      } else if (item.kind === "loosing") {
        detail.explanation = [
          "在大期", { strong: parentSign }, `裡，小期從${parentSign}起依序輪過十二個星座。輪完一圈時大期還沒結束，下一段不回到起點，而是跳到${parentSign}的對宮`,
          { strong: item.label }, "繼續，古典稱為", { strong: "解鎖" }, "（輪完一圈跳到對宮；loosing of the bond，Valens IV.4）。",
        ];
      } else {
        detail.explanation = [
          "大期", { strong: parentSign },
          `裡面再切成小段（小期）：從${parentSign}開始，照十二星座的固定順序（牡羊、金牛、雙子……到雙魚）一個接一個輪。每個星座分到的月數，和它當大期時分到的年數相同，每月 ${daysPerMonth} 日；${item.label}分到 ${facts.nominal_units} 個月。`,
          item.truncated ? "大期在這一段還沒走完時就結束了，所以這一段比原本的月數短。" : "",
        ];
      }
      detail.sources = SOURCES.zodiacal_releasing.slice();
      glossFirstEdition(detail.sources);
      detail.receipt = {
        releasing_from: lot, ...segmentReceipt(segment),
        ...headReceipt(head, ["profile", "period_table_profile", "method_status", "method_provenance"]),
        year_model: yearModel.profile || null, year_model_input: yearModel.input || null, interpretation: null,
      };
    } else if (item.technique === "decennials") {
      const facts = item.record.detail;
      const head = data.decennials.head || {};
      const levelOne = item.level === 1;
      const parent = levelOne ? null : model.byId.get(item.parentId);
      detail.kind = `${levelOne ? "十年期・第一層" : "十年期・第二層"}${sampleNote}`;
      detail.title = levelOne ? [...named(item.glyph, item.label), "輪值"]
        : [...named(item.glyph, item.label), `（屬${parent ? parent.label : ""}的十年期）`];
      detail.rows.push(["起訖", [dateRange(item, false)]]);
      const yearModel = head.year_model;
      detail.rows.push(["長度", [`${facts.months} 個分配月（每月 ${yearModel.days_per_month} 日）`]]);
      detail.rows.push(["輪值行星", named(item.glyph, item.label)]);
      if (levelOne) {
        detail.rows.push(["順序", [`第 ${facts.cycle_index + 1} 輪的第 ${facts.position_in_order} 位`]]);
      } else if (parent) { detail.rows.push(["第一層", named(parent.glyph, parent.label)]); }
      const start = DECENNIALS_START_TEXT[(head.start_profile || {}).profile] || "";
      detail.explanation = levelOne ? [
        `十年期把出生之後的時間切成每段 ${yearModel.months_per_level_1} 個月（一個月 ${yearModel.days_per_month} 日、一年 ${yearModel.days_per_year} 日的「分配年」），每段由一顆行星輪值。${start}`,
        "之後依出生時七顆行星在黃道上的實際順序往下排，七段輪完再從頭開始。"] : [
        `每一段第一層再分成七小段，由這一段的輪值行星${parent ? `（${parent.label}）` : ""}自己先開始，其餘依同一個黃道順序；每顆行星分到的月數等於它的「小年」（古書給每顆行星的固定年數），七個加起來正好 ${yearModel.months_per_level_1} 個月。`,
      ];
      detail.sources = SOURCES.decennials.slice();
      glossFirstEdition(detail.sources);
      detail.methodHref = "/zh-TW/methods/decennials";
      detail.receipt = {
        ...segmentReceipt(item.record), ...headReceipt(head, ["profile", "order_rule", "method_status", "method_provenance"]),
        start_profile: (head.start_profile || {}).profile || null, start_planet: head.start_planet || null, interpretation: null,
      };
    } else {
      // 還沒有專屬說明的泳道：起訖與回應原值照列。
      detail.kind = laneMeta(item.record.laneId).title;
      detail.title = [...named(item.glyph, item.label)];
      detail.rows.push(["起訖", [dateRange(item, false)]]);
      detail.receipt = { ...segmentReceipt(item.record), interpretation: null };
    }
    if (!detail.methodHref) detail.methodHref = "/zh-TW/methods/time-lords";
    detail.dateNote = item.technique === "annual_profection"
      ? `日期是${DATE_NOTE}；所選的那一年另附年界的時刻（到分鐘）。` : item.technique === MONTHLY_LANE
        ? `日期是${DATE_NOTE}；每個月從哪一天開始，看那一刻落在出生地的哪一天。` : `日期是${DATE_NOTE}。`;
    return Object.freeze(detail);
  }

  function conventions(model) {
    const data = model.data;
    // 這兩條依回應這次實際用的排法與年長寫；時間主星表與列印都用這一份。
    const nodeProfile = (data.firdaria.head || {}).nocturnal_node_profile;
    const zrYear = ((data.releasing.head || {}).year_model || {}).profile;
    const firdariaText = nodeProfile === FIRDARIA_NODE_PROFILES[1]
      ? "日盤從太陽起、夜盤從月亮起；夜盤時兩個月交點擺在哪裡有兩種讀法（在水星之後，或在火星之後），本站預設前者，這次依你的選擇用後者，收據每次印出所用的一種。75 年後同一順序重來。"
      : "日盤從太陽起、夜盤從月亮起；夜盤時兩個月交點擺在哪裡有兩種讀法（在水星之後，或在火星之後），本站預設前者，收據每次印出所用的一種。75 年後同一順序重來。";
    const zrText = zrYear === ZR_YEAR_MODELS[1]
      ? "這次依你的選擇用 365.25 日（部分現代軟體的設定），不是本站預設的 360 日（Valens 原文的分配年）；兩種年長不並列。"
      : "360 日（Valens 原文的分配年），不是日曆年；部分現代軟體改用 365.25 日，可以在本章上方改選，兩種不並列。";
    const list = [
      ["一年從哪一刻算起：", "每年太陽回到出生時黃經位置的那一刻（太陽回歸），不是生日日期；兩者最多可差將近一天。年度小限與法達共用這個年界。"],
      ["法達：", firdariaText], ["黃道釋放的「年」：", zrText],
      ["黃道釋放的層級：", "只算第一層（大期）與第二層（小期）。Valens 書中還有以日、以時計的更細層級，本頁沒有算；也不標「高峰期」。"],
      ["命運點與精神點同一星座時：", "Valens 說行動類的要從下一個星座起算；本站不套用，只標示。"],
      ["主星：", "傳統七顆行星（日、月、水、金、火、木、土）的守護（天蠍＝火星、水瓶＝土星、雙魚＝木星）。"],
      ["十年期（decennials）：", "每段 129 個分配月（一年 360 日），依出生時的黃道順序輪值，只算兩層；起點預設日盤從太陽、夜盤從月亮（Firmicus），可改用 Valens 的「上升點之後第一顆」或自己指定，本站不判斷光體好壞。"],
      ["月小限：", "第 1 個月是年度小限星座，之後每月往後一個星座，每年在太陽回歸時重新數起；每個月從太陽比出生時的位置多走 30 度的那一刻開始（中世紀 Abū Maʿshar 的做法），夜盤也用太陽。Ptolemy 的每 28 日一個星座與 al-Bīrūnī 的一年 13 個月，本站沒有算。只列你選過的年度；換到還沒取過的年度時另外取。"],
      ["日期精度：", `年界到分鐘；法達、黃道釋放與十年期的期間只到「日」（原典只給年數，分秒是假精度）。日期是${DATE_NOTE}。`],
    ];
    const head = data.releasing.head;
    if (head && head.fortune_spirit_same_sign === true) {
      list.push(["這張盤：", "命運點與精神點在同一個星座，上面那條 Valens 的規則本站沒有套用。"]);
    }
    return list;
  }

  /** 回應警告的白話說明；未知的代碼照列代碼，不吞掉。 */
  function warningNotices(model) {
    // 同一則警告可以掛在兩個技法上（上升點近邊界：年度小限與月小限），畫面只說一次。
    const seen = new Set();
    return model.data.warnings.filter((warning) => !seen.has(warning.code) && seen.add(warning.code)).map((warning) => ({
      code: warning.code, text: WARNINGS[warning.code] || "回應附了一則這個頁面還不認得的警告。",
    }));
  }

  function unavailableTechniques(model) {
    const data = model.data;
    return [
      ["annual_profection", "年度小限", data.profection], ["monthly_profection", "月小限", data.monthly],
      ["firdaria", "法達", data.firdaria], ["zodiacal_releasing", "黃道釋放", data.releasing], ["decennials", "十年期", data.decennials],
    ].filter(([, , state]) => state.status === "not_applicable").map(([key, title, state]) => ({
      key, title, code: state.reason, text: NOT_APPLICABLE[state.reason] || "伺服器說這一項不適用。",
    }));
  }

  /** 約略到小時：哪些技法三個時刻相同、哪些不同；樣本的在地時刻有就附上。 */
  function sampleSummary(model) {
    const data = model.data;
    if (data.precision !== "approximate_hour") return null;
    const state = (technique) => data[technique].sensitivity;
    return {
      techniques: [
        ["年度小限", state("profection")], ["月小限", state("monthly")], ["法達", state("firdaria")],
        ["黃道釋放", state("releasing")], ["十年期", state("decennials")],
      ].filter(([, value]) => value).map(([title, value]) => ({ title, differs: value === "differs_between_samples" })),
      samples: SAMPLE_ORDER.map((role) => {
        const found = data.samples.find((sample) => sample.role === role);
        return { role, title: SAMPLE_ROLES[role], localTime: found ? found.localTime : null };
      }),
    };
  }

  /**
   * 第二層還沒有的第一層期間（黃道釋放的大期、十年期的第一層）：與 [startDay, endDay) 相交、
   * 而第二層尚未載入的那些。回傳 [{ id, n }]，n 是落在該期間裡的一個足歲年度（按需請求用它）。
   * 三個時刻不同的技法不按需取（並列的三組各自是完整回應）。
   */
  function missingLevel2(model, startDay, endDay) {
    const data = model.data;
    const levelOneLanes = [];
    if (data.releasing.status === "computed" && !releasingDiffersBetweenSamples(data)) {
      RELEASING_LOTS.forEach((lot) => levelOneLanes.push(`zr_${lot}_level_1`));
    }
    if (data.decennials.status === "computed" && data.decennials.sensitivity !== "differs_between_samples") {
      levelOneLanes.push("decennials_level_1");
    }
    const missing = [];
    levelOneLanes.forEach((laneId) => {
      const lane = laneById(model, laneId);
      if (!lane) return;
      lane.items.forEach((item) => {
        if (item.endDay <= startDay || item.startDay >= endDay) return;
        if (data.level2LoadedFor.has(item.id)) return;
        const inside = model.years.find((year) => year.startDay >= item.startDay && year.endDay <= item.endDay)
          || model.years.find((year) => year.startDay < item.endDay && year.endDay > item.startDay);
        if (inside) missing.push({ id: item.id, n: inside.n });
      });
    });
    return missing;
  }

  /** 第 index 個年度的年度小限期間 id（它的月小限掛在這一段下）；沒有月小限或沒有這一段時回 null。 */
  function monthsParentId(model, index) {
    const year = model.years[index];
    if (!year || model.data.monthly.status !== "computed") return null;
    const parent = itemAt(model, "annual_profection", year.startDay);
    return parent ? parent.id : null;
  }

  /**
   * 第 index 個年度的月小限還沒有時，回傳 [{ id, n }]（id 是那一年年度小限的期間，n 是那一年）；已經有、沒有算月小限，
   * 或三個時刻不同（並列的三組各自是完整回應）時回傳空陣列。只看選定的那一年：時間軸捲動或展開十年不會逐年去取。
   */
  function missingMonths(model, index) {
    const lane = model.data.lanes.find((candidate) => candidate.laneId === MONTHLY_LANE);
    if (!lane || lane.basis === "each_sample") return [];
    const id = monthsParentId(model, index);
    if (!id || model.data.level2LoadedFor.has(id)) return [];
    return [{ id, n: model.years[index].n }];
  }

  // .ics 只由畫面上的期間產生：選定年度裡、各泳道與該年相交的期間（「交點期不分子期」只是說明，不是期間，不列）。全日事
  // 件，DTSTART／DTEND 是伺服器給的出生地日期（DTEND 依 RFC 5545 不含當日，正好是下一段的起點）。UID 是每次匯出隨機產生
  // 的識別碼加序號，不含任何出生資料；不加提醒（VALARM），不提供訂閱網址。

  function escapeText(text) {
    return String(text).replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r\n|\r|\n/g, "\\n");
  }

  function utf8Length(character) {
    const code = character.codePointAt(0);
    return code < 0x80 ? 1 : code < 0x800 ? 2 : code < 0x10000 ? 3 : 4;
  }

  /** RFC 5545 3.1：每行最多 75 個位元組（不含 CRLF），續行以一個空白開頭，不切開多位元組字元。 */
  function foldLine(line) {
    const out = [];
    let current = "";
    let bytes = 0;
    for (const character of line) {
      const size = utf8Length(character);
      const limit = out.length ? 74 : 75;
      if (bytes + size > limit) { out.push(current); current = ""; bytes = 0; }
      current += character;
      bytes += size;
    }
    out.push(current);
    return out.map((part, index) => (index ? ` ${part}` : part)).join("\r\n");
  }

  const icsDate = (localDate) => localDate.replace(/-/g, "");
  const pad2 = (value) => String(value).padStart(2, "0");

  function icsStamp(now) {
    return `${now.getUTCFullYear()}${pad2(now.getUTCMonth() + 1)}${pad2(now.getUTCDate())}T${pad2(now.getUTCHours())}${pad2(now.getUTCMinutes())}${pad2(now.getUTCSeconds())}Z`;
  }

  function plain(runs) { return runs.map((run) => (typeof run === "string" ? run : run.mono || run.strong || run.small || "")).join(""); }

  function icsPeriods(model, index) {
    return model.lanes.flatMap((lane) => itemsInYear(model, lane.id, index)
      .filter((item) => item.kind !== "node")
      .map((item) => ({ lane, item })));
  }

  function eventSummary(lane, item) {
    if (item.technique === "annual_profection") {
      return item.aside ? `年度小限：${item.label}（年主星 ${item.aside.label}）` : `年度小限：${item.label}`;
    }
    if (item.technique === MONTHLY_LANE) {
      return item.aside ? `月小限：${item.label}（月主星 ${item.aside.label}）` : `月小限：${item.label}`;
    }
    return `${lane.title}：${item.label}${item.kind === "loosing" ? "（解鎖）" : ""}`;
  }

  /** @param {object} options now：產生時刻（DTSTAMP，Date）；token：隨機識別碼（字串）。 */
  function buildIcs(model, index, options) {
    const year = model.years[index];
    if (!year) throw new Error("沒有選定的年度。");
    const now = options && options.now instanceof Date ? options.now : null;
    const token = options && typeof options.token === "string" ? options.token : "";
    if (!now || !/^[0-9a-f]{16,}$/.test(token)) throw new Error("行事曆檔需要產生時刻與隨機識別碼。");
    const stamp = icsStamp(now);
    // 畫面上的警告也進行事曆檔：行事曆的說明一份，每個事件的說明各一份（匯入後事件常與行事曆分開）。
    const warningLines = warningNotices(model).map((notice) => `注意［${notice.code}］：${notice.text}`);
    const lines = [
      "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Armillary//Time lords//ZH-TW", "CALSCALE:GREGORIAN",
      "METHOD:PUBLISH", `X-WR-CALNAME:${escapeText(`渾儀・時間主星（${ICS_LABEL}）`)}`,
      `X-WR-CALDESC:${escapeText([`${ICS_LABEL}。${FIXED_SENTENCE}`, ...warningLines].join("\n"))}`,
    ];
    const periods = icsPeriods(model, index);
    periods.forEach(({ lane, item }, position) => {
      const description = [
        `起訖（${DATE_NOTE}）：${item.start.localDate} → ${item.end.localDate}`, `${ICS_LABEL}。`, FIXED_SENTENCE, ...warningLines,
      ].join("\n");
      lines.push(
        "BEGIN:VEVENT", `UID:${token}-${position + 1}@armillary`, `DTSTAMP:${stamp}`, `DTSTART;VALUE=DATE:${icsDate(item.start.localDate)}`,
      );
      if (item.endDay > item.startDay) lines.push(`DTEND;VALUE=DATE:${icsDate(item.end.localDate)}`);
      lines.push(
        `SUMMARY:${escapeText(eventSummary(lane, item))}`, `DESCRIPTION:${escapeText(description)}`, "TRANSP:TRANSPARENT", "END:VEVENT",
      );
    });
    lines.push("END:VCALENDAR");
    return Object.freeze({
      filename: ICS_FILENAME, mime_type: "text/calendar;charset=utf-8",
      content: lines.map(foldLine).join("\r\n") + "\r\n", count: periods.length,
    });
  }

  // 時間主星表（Markdown／CSV／JSON）另一份匯出檔，不併進本命盤的匯出：期間取自畫面模型（與時間軸、年表同一份；「交點期
  // 不分子期」只是說明，不是期間），每一列附回應裡的代碼；JSON 另附頁面收到的每一份原始回應。只由頁面已經收到的回應產
  // 生，不發請求。儲存格與 Markdown 的中和、CSV 欄名都用本命盤匯出那一套，版本身分照本命盤匯出的規則：API 版本不在相容
  // 清單、或幾份回應的版本與出處清單不一致，就拒絕。

  const TIME_LORD_TABLE_TITLE = "渾儀・時間主星表";
  const TIME_LORD_TABLE_FILE = "armillary-time-lords";
  const TIME_LORD_TABLE_KIND = "time_lord_table";
  const TABLE_FORMAT_DEFINITIONS = Object.freeze({
    md: Object.freeze({ name: "Markdown", mime_type: "text/markdown;charset=utf-8", prefix: "" }),
    csv: Object.freeze({ name: "CSV", mime_type: "text/csv;charset=utf-8", prefix: "﻿" }),
    json: Object.freeze({ name: "JSON", mime_type: "application/json;charset=utf-8", prefix: "" }),
  });
  const TIME_LORD_TABLE_FORMATS = Object.freeze(Object.keys(TABLE_FORMAT_DEFINITIONS));
  const TIME_LORD_TABLE_FORMAT_NAMES = Object.freeze(Object.fromEntries(
    Object.entries(TABLE_FORMAT_DEFINITIONS).map(([format, definition]) => [format, definition.name])));
  // 表裡的技法順序與回應 lanes[] 的順序相同；右欄是 AnnualData 上的鍵。
  const TABLE_TECHNIQUES = Object.freeze([
    ["annual_profection", "profection", "年度小限"], ["monthly_profection", "monthly", "月小限"],
    ["firdaria", "firdaria", "法達"], ["zodiacal_releasing", "releasing", "黃道釋放"], ["decennials", "decennials", "十年期"],
  ]);
  const TECHNIQUE_STATUS = Object.freeze({ computed: "已計算", not_applicable: "不適用", not_requested: "未請求" });
  const FLAG_LABELS = Object.freeze({ loosing_of_the_bond: "解鎖", truncated: "被上一層截斷", node_period: "交點期不分子期" });
  // 按需取的下一層（黃道釋放與十年期的第二層、月小限）：上一層的每一段，下一層有沒有取到。
  // 沒有取到不等於沒有這一層，所以不寫成空白。
  const SUBDIVISION = Object.freeze({ listed: "已列出", not_fetched: "未取得" });
  const PERIOD_COLUMNS = Object.freeze([
    ["period_id", "期間代碼"], ["start", "起（出生地日期）"], ["end", "迄（出生地日期）"], ["ruler", "輪值"],
    ["domicile_lord", "守護行星"], ["marks", "標記"], ["parent_period_id", "上一層期間代碼"], ["subdivision", "下一層"],
  ]);
  const tableText = (value) => (value === null || value === undefined || value === "" ? "—" : String(value));
  const withoutLane = (id) => (id ? id.slice(id.indexOf("/") + 1) : null);

  /**
   * 收到的每一份回應都過同一條相容規則（compatibilityProblem），而且與畫面模型同一個 API 版本、
   * 同一份出處清單；否則拒絕，不猜哪一份對。
   */
  function tableIdentity(sources, expected) {
    if (!Array.isArray(sources) || !sources.length) throw new Error("沒有年度回應，不能產生時間主星表。");
    sources.forEach((source) => {
      const problem = compatibilityProblem(source);
      if (problem) throw new Error(problem);
      if (identityKey(source) !== expected) throw new Error("幾份年度回應的 API schema 版本或出處清單不一致，不能合成一份表。");
    });
    const register = (sources[0].calculation_dossier || {}).method_source_register || {};
    return {
      export_contract_version: ChartExport.EXPORT_CONTRACT_VERSION, api_schema_version: sources[0].schema_version,
      method_source_register: {
        register_id: register.register_id || null, version: register.version || null, sha256: register.sha256 || null,
      },
      responses: sources.map((source) => ({
        year_of_life: source.year_boundary && Number.isInteger(source.year_boundary.year_of_life)
          ? source.year_boundary.year_of_life : null,
        trace_receipt_sha256: ((source.calculation_dossier || {}).trace_receipt || {}).python_json_serialization_sha256 || null,
      })),
    };
  }

  function tablePeriods(model) {
    const data = model.data;
    const onDemandChildren = new Map();
    data.lanes.filter((lane) => lane.status === "computed" && lane.parentLaneId && ON_DEMAND_LEVEL_2.test(lane.laneId))
      .forEach((lane) => onDemandChildren.set(lane.parentLaneId, (onDemandChildren.get(lane.parentLaneId) || []).concat([lane])));
    return model.lanes.flatMap((lane) => lane.items.filter((item) => item.kind !== "node").map((item) => {
      const record = item.record;
      const children = onDemandChildren.get(record.laneId);
      let subdivision = null;
      if (children && !record.node) {
        const listed = data.level2LoadedFor.has(item.id)
          || children.some((child) => child.segments.some((segment) => segment.parentId === item.id));
        subdivision = listed ? "listed" : "not_fetched";
      }
      return {
        table: lane.title, lane_id: record.laneId, technique: lane.technique, level: lane.level,
        sample_role: record.sampleRole, period_id: record.periodId, parent_period_id: withoutLane(record.parentId),
        start: record.start.localDate, end: record.end.localDate, ruler_key: record.labelKey,
        ruler: record.labelKey ? labelOf(record.labelKey) : null, domicile_lord_key: record.lordKey,
        domicile_lord: record.lordKey ? bodyName(record.lordKey) : null, flags: record.flags.slice(),
        marks: record.flags.map((flag) => FLAG_LABELS[flag] || flag), subdivision,
        subdivision_label: subdivision ? SUBDIVISION[subdivision] : null,
      };
    }));
  }

  function tableTechniques(model) {
    const notApplicable = new Map(unavailableTechniques(model).map((entry) => [entry.key, entry.text]));
    return TABLE_TECHNIQUES.map(([technique, key, title]) => {
      const state = model.data[key];
      const head = state.head || {};
      const ref = head.source_ref || null;
      return {
        technique, title, status: state.status, status_label: TECHNIQUE_STATUS[state.status] || state.status,
        reason_code: state.reason || null, reason: state.reason ? notApplicable.get(technique) || null : null,
        profile: head.profile || null, source_ref: ref, sources: ref && SOURCES[ref] ? SOURCES[ref].slice() : [],
      };
    });
  }

  /**
   * 時間主星表的文件：三種格式都由這一份產生。
   * @param {object[]} sources 頁面收到的年度回應，原樣，依收到的先後。
   */
  function buildTimeLordTable(model, sources) {
    const identity = tableIdentity(sources, model.data.identity);
    return {
      export_contract_version: identity.export_contract_version, export_kind: TIME_LORD_TABLE_KIND,
      title: TIME_LORD_TABLE_TITLE, label: ICS_LABEL, statement: FIXED_SENTENCE, date_basis: DATE_NOTE, identity,
      input_assumptions: [{
        key: "birth_time_precision", label: "出生時刻把握程度",
        value: Labels.label("birth_time_precision", model.data.precision), code: model.data.precision,
      }],
      warnings: warningNotices(model).map((notice) => ({ code: notice.code, message: notice.text })),
      techniques: tableTechniques(model), periods: tablePeriods(model),
      conventions: conventions(model).map(([term, text]) => ({ term: term.replace(/：$/, ""), text })), source_responses: sources,
    };
  }

  function periodCells(period) {
    const values = {
      period_id: [period.period_id, period.lane_id], start: [period.start, ""], end: [period.end, ""],
      ruler: [period.ruler, period.ruler_key], domicile_lord: [period.domicile_lord, period.domicile_lord_key],
      marks: [period.marks.join("、"), period.flags.join(",")], parent_period_id: [period.parent_period_id, ""],
      subdivision: [period.subdivision_label, period.subdivision],
    };
    return PERIOD_COLUMNS.map(([key, header]) => [header, tableText(values[key][0]), values[key][1] || ""]);
  }

  function groupedPeriods(document) {
    const groups = [];
    document.periods.forEach((period) => {
      const last = groups[groups.length - 1];
      if (last && last.title === period.table) last.periods.push(period);
      else groups.push({ title: period.table, periods: [period] });
    });
    return groups;
  }

  function identityEntries(identity) {
    const register = identity.method_source_register;
    return [
      ["Export contract", identity.export_contract_version, "export_contract_version"],
      ["API schema", identity.api_schema_version, "api_schema_version"],
      ["出處清單", register.register_id, "method_source_register.register_id"],
      ["出處清單版本", register.version, "method_source_register.version"],
      ["出處清單 SHA-256", register.sha256, "method_source_register.sha256"],
    ];
  }

  const yearOfLife = (value) => (value === null ? "—" : `第 ${value} 年`);

  function renderTimeLordMarkdown(document) {
    const escape = ChartExport.escapeMarkdownText;
    const code = ChartExport.markdownInlineCode;
    const row = (cells) => `| ${cells.map(escape).join(" | ")} |`;
    const tableLines = (headers, rows) => [row(headers), `| ${headers.map(() => "---").join(" | ")} |`, ...rows.map(row)];
    const lines = [
      `# ${escape(document.title)}`, "", `> ${escape(document.label)}。${escape(document.statement)}`, "", "## 版本與收據", "",
      ...identityEntries(document.identity).map(([label, value]) => `- ${escape(label)}: ${code(tableText(value))}`),
      "", `這份表由 ${document.identity.responses.length} 份伺服器回應組成：`, "",
      ...tableLines(["請求的年度", "計算軌跡摘要（SHA-256）"],
        document.identity.responses.map((response) => [yearOfLife(response.year_of_life), tableText(response.trace_receipt_sha256)])),
      "", "## 輸入假設", "",
      ...document.input_assumptions.map((entry) => `- ${escape(entry.label)}［${code(entry.code)}］: ${escape(entry.value)}`),
      `- 日期: ${escape(document.date_basis)}`, "", "## 注意事項", "",
      ...(document.warnings.length
        ? document.warnings.map((warning) => `- 注意［${code(warning.code)}］: ${escape(warning.message)}`)
        : ["- 注意事項: 無"]),
      "", "## 各技法", "",
      ...tableLines(["技法", "狀態", "沒有算的原因", "算法代碼", "出處"], document.techniques.map((entry) => [
        entry.title, entry.status_label, tableText(entry.reason), tableText(entry.profile),
        tableText(entry.sources.length ? entry.sources.join(" ") : null),
      ])),
      "", "## 期間", "",
      `> 日期是${escape(document.date_basis)}。「下一層」寫「未取得」的，是畫面還沒有取那一段的細分期間，不代表那一段沒有細分。`,
    ];
    groupedPeriods(document).forEach((group) => {
      const cells = group.periods.map(periodCells);
      lines.push("", `### ${escape(group.title)}`, "",
        ...tableLines(PERIOD_COLUMNS.map(([, header]) => header), cells.map((list) => list.map(([, value]) => value))));
    });
    lines.push("", "## 本工具採用的約定", "",
      ...document.conventions.map((entry) => `- **${escape(entry.term)}**：${escape(entry.text)}`), "");
    return lines.join("\n");
  }

  function renderTimeLordCsv(document) {
    const rows = [ChartExport.CSV_HEADER.slice()];
    const push = (section, title, tableName, index, field, value, code = "") =>
      rows.push([section, title, tableName, index, field, tableText(value), code || ""]);
    push("_about", "說明", "說明", 1, "標示", document.label);
    push("_about", "說明", "說明", 2, "說明", document.statement);
    identityEntries(document.identity).forEach(([label, value, key], index) => {
      push("_identity", "版本與收據", "版本與收據", index + 1, label, value, key);
    });
    document.identity.responses.forEach((response, index) => {
      push("_identity", "版本與收據", "伺服器回應", index + 1, "請求的年度", yearOfLife(response.year_of_life), "year_of_life");
      push("_identity", "版本與收據", "伺服器回應", index + 1, "計算軌跡摘要（SHA-256）",
        response.trace_receipt_sha256, "trace_receipt_sha256");
    });
    document.input_assumptions.forEach((entry, index) => {
      push("_input", "輸入假設", "輸入假設", index + 1, entry.label, entry.value, entry.code);
    });
    push("_input", "輸入假設", "輸入假設", document.input_assumptions.length + 1, "日期", document.date_basis);
    (document.warnings.length ? document.warnings : [{ code: "", message: "無" }]).forEach((warning, index) => {
      push("_warnings", "注意事項", "注意事項", index + 1, "注意事項", warning.message, warning.code);
    });
    document.techniques.forEach((entry, index) => {
      const add = (field, value, code) => push("techniques", "各技法", "各技法", index + 1, field, value, code);
      add("技法", entry.title, entry.technique);
      add("狀態", entry.status_label, entry.status);
      if (entry.reason_code) add("沒有算的原因", entry.reason, entry.reason_code);
      add("算法代碼", entry.profile, "");
      entry.sources.forEach((line) => add("出處", line, entry.source_ref));
    });
    groupedPeriods(document).forEach((group) => {
      group.periods.forEach((period, index) => {
        periodCells(period).forEach(([header, value, code]) => push("periods", "期間", group.title, index + 1, header, value, code));
      });
    });
    document.conventions.forEach((entry, index) => {
      push("conventions", "本工具採用的約定", "本工具採用的約定", index + 1, entry.term, entry.text);
    });
    return rows.map((row) => row.map(ChartExport.csvCell).join(",")).join("\r\n");
  }

  function renderTimeLordJson(document) { return JSON.stringify(document, null, 2) + "\n"; }

  const TABLE_RENDERERS = Object.freeze({ md: renderTimeLordMarkdown, csv: renderTimeLordCsv, json: renderTimeLordJson });

  function buildTimeLordTableArtifact(model, sources, format) {
    if (!Object.hasOwn(TABLE_FORMAT_DEFINITIONS, format)) { throw new Error(`不支援的時間主星表格式：${format}`); }
    const definition = TABLE_FORMAT_DEFINITIONS[format];
    const document = buildTimeLordTable(model, sources);
    return Object.freeze({
      filename: `${TIME_LORD_TABLE_FILE}.${format}`, mime_type: definition.mime_type,
      content: definition.prefix + TABLE_RENDERERS[format](document), count: document.periods.length, format_name: definition.name,
    });
  }

  // 太陽回歸盤年度路由的 solar_return_chart：選定年度的年界那一刻（SR_N）起的一張星盤。本檔只認形狀、組畫面要的字；星盤
  // 本體（chart）與 /api/chart 的頁面投影同形，表格由本命盤的同一套 view-model（呼叫端傳入）建出，圖由同一個星盤圖元件
  // 畫。本檔不換算任何時刻。

  const SOLAR_RETURN_LEAD = "太陽回到出生時黃經位置的那一刻，在這個地點起的一張星盤。";
  const SOLAR_RETURN_FIXED = `只列計算結果：${SOLAR_RETURN_LEAD}不替你解盤，也不預測。`;
  const SOLAR_RETURN_HOUSE_SYSTEMS = Object.freeze(["B", "R", "W", "P", "O", "E", "C"]);
  // 回歸盤畫面列的表：天體、軸點、宮位分割、行星落宮（view-model 的區段 id）。
  const SOLAR_RETURN_SECTIONS = Object.freeze(["bodies", "angles", "houses", "planet_in_house"]);
  // 後端 SOLAR_RETURN_CHART_REASON_CODES 的閉集，各一句白話。
  const SOLAR_RETURN_REASONS = Object.freeze({
    solar_return_chart_requires_exact_birth_time: "太陽回歸盤需要確切的出生時間。出生時間差一小時，本命太陽約差 2.5′，回歸時刻也差約一小時，回歸盤的上升點會轉過約 15°；本站不並列幾張取樣的回歸盤。",
    first_year_has_no_solar_return: "第 1 年從出生那一刻開始，那一刻就是本命盤，不是回歸；太陽回歸盤從第 2 年起才有。",
    solar_return_root_count_unexpected: "這一年找不到唯一的太陽回歸時刻，本站不畫這一年的回歸盤。",
  });
  // 後端 year_boundary.SOLAR_RETURN_PROFILES 的閉集（回歸瞬間一律用當日黃道、含章動）。
  const SOLAR_RETURN_PROFILES = Object.freeze({
    solar_return_tropical_geocentric_apparent_of_date_v1: "回歸黃道、地心、視位置、當日黃道（含章動）",
    solar_return_tropical_geocentric_true_of_date_v1: "回歸黃道、地心、真位置、當日黃道（含章動）",
    solar_return_sidereal_geocentric_apparent_of_date_v1: "恆星黃道、地心、視位置、當日黃道（含章動）",
    solar_return_sidereal_geocentric_true_of_date_v1: "恆星黃道、地心、真位置、當日黃道（含章動）",
  });
  // 改用另一個地點起回歸盤的開關。關著時頁面不畫那一格、請求不帶
  // solar_return_location；服務端另有同一道開關（schemas.SOLAR_RETURN_LOCATION_OFFERED）。
  const SOLAR_RETURN_RELOCATION_OFFERED = true;
  const SOLAR_RETURN_MORIN = "本站預設在出生地起回歸盤。改用太陽回歸那一刻你所在的地點起盤，是 Morin（《Astrologia Gallica》，1661）的做法。";
  const SOLAR_RETURN_PRIVACY = "你輸入的地點只隨這一次請求送到計算服務；伺服器不留副本，本頁不寫網址、不存在瀏覽器裡，清除結果或離開頁面時一起丟掉。";
  const SOLAR_RETURN_OTHER_PLACE_TIME = "另一個地點的當地鐘點本站沒有換算；上面兩行是同一個瞬間。";
  const SOLAR_RETURN_UTC_NOTE = "這張盤用世界時（UTC）的時刻起盤；出生地時間只是同一瞬間換成出生地鐘點，方便對照。";
  // 起盤時刻的時間尺度：閉集與中文名與本命盤時間表、匯出同一份（exporters.js 的 TIME_SCALE_ZH）。
  // 1972 年前與約 2033-09 以後的時刻是 UT1，不是 UTC；這時標籤寫出尺度，時刻去掉 Z、不加 UTC。
  const MODERN_UTC = "modern_leap_second_utc";

  /** 本命盤所選的宮位制（不計宮位時用整宮）；回歸盤沿用它，兩張盤的宮才對得上。 */
  function solarReturnHouseSystem(chartPayload) {
    const options = chartPayload && chartPayload.options;
    if (!options || options.include_houses === false) return "W";
    return SOLAR_RETURN_HOUSE_SYSTEMS.includes(options.house_system) ? options.house_system : "W";
  }

  /**
   * 「在別的地點過這個生日」的兩格：都空著是出生地（回 null）；只填一格、不是數字或超出範圍時
   * 回 { error }。座標照填的字送出，不另外取整。
   */
  function parseSolarReturnLocation(latitudeText, longitudeText) {
    const lat = String(latitudeText == null ? "" : latitudeText).trim();
    const lon = String(longitudeText == null ? "" : longitudeText).trim();
    if (!lat && !lon) return { location: null };
    if (!lat || !lon) return { error: "緯度與經度要一起填；都空著就用出生地。" };
    const NUMBER = /^[+-]?(\d+(\.\d*)?|\.\d+)$/;
    if (!NUMBER.test(lat) || !NUMBER.test(lon)) return { error: "緯度與經度請填十進位的度數，例如 25.0330 與 121.5654。" };
    const latitude = Number(lat);
    const longitude = Number(lon);
    if (latitude < -90 || latitude > 90) return { error: "緯度要在 −90 到 90 度之間（南緯是負數）。" };
    if (longitude < -180 || longitude > 180) return { error: "經度要在 −180 到 180 度之間（西經是負數）。" };
    return { location: { latitude, longitude } };
  }

  /** 使用者在回歸盤一格另選的宮位制；沒選（null）就沿用本命盤的。不在可用的那一組時拒絕。 */
  function solarReturnChosenHouseSystem(chartPayload, override) {
    if (override === null || override === undefined || override === "") return solarReturnHouseSystem(chartPayload);
    if (!SOLAR_RETURN_HOUSE_SYSTEMS.includes(override)) throw new Error("回歸盤的宮位制不在選項裡。");
    return override;
  }

  /**
   * 年度路由的請求：只要選定年度的太陽回歸盤，不另算其他技法。另一個地點只在開放時才送；
   * relocationOffered 預設是本檔的開關，測試另一個地點的那條路時才明示傳 true。
   */
  function solarReturnRequestBody(chartPayload, completedYears, scope = {}, relocationOffered = SOLAR_RETURN_RELOCATION_OFFERED) {
    if (!chartPayload || typeof chartPayload !== "object") throw new Error("沒有本命盤的請求可用。");
    if (!Number.isInteger(completedYears) || completedYears < 1) throw new Error("太陽回歸盤從第 2 年起才有。");
    if (scope.location && !relocationOffered) throw new Error("太陽回歸盤目前只在出生地起盤。");
    const body = {};
    NATAL_KEYS.forEach((key) => { if (chartPayload[key] !== undefined) body[key] = JSON.parse(JSON.stringify(chartPayload[key])); });
    body.annual = {
      target_kind: "completed_years", target_value: completedYears, include_profection: false, include_solar_return_chart: true,
      solar_return_house_system: solarReturnChosenHouseSystem(chartPayload, scope.houseSystem),
      // 對照用本命盤自己的宮位制，回歸盤另選宮位制時也一樣。
      solar_return_natal_house_system: solarReturnHouseSystem(chartPayload),
      ...(scope.location ? { solar_return_location: { latitude: scope.location.latitude, longitude: scope.location.longitude } } : {}),
    };
    return body;
  }

  /** 年度回應有沒有這一塊（不論是否請求，支援回歸盤的路由都帶這個鍵，沒請求時是 null）。 */
  function supportsSolarReturn(annualBody) {
    return Boolean(annualBody) && typeof annualBody === "object" && Object.hasOwn(annualBody, "solar_return_chart");
  }

  function coordinateText(value, positive, negative) {
    if (typeof value !== "number" || !Number.isFinite(value)) throw new Error("太陽回歸盤回應形狀不符：座標。");
    return `${Math.abs(value)}°${value < 0 ? negative : positive}`;
  }

  /** 起盤時刻一列與它的說明：照 instant.time_scale；缺鍵或不在閉集時拒絕，不預設成 UTC。 */
  function instantFact(instant) {
    const scale = ownLabel(ChartExport.TIME_SCALE_ZH, instant.time_scale);
    if (!scale) throw new Error("太陽回歸盤回應形狀不符：時間尺度。");
    const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2}(?:\.\d+)?)Z$/.exec(instant.utc_time || "");
    if (!match) throw new Error("太陽回歸盤回應形狀不符：UTC 時刻。");
    if (instant.time_scale === MODERN_UTC) {
      return { fact: ["起盤時刻（UTC，世界時）", `${match[1]} ${match[2]} UTC`], note: SOLAR_RETURN_UTC_NOTE };
    }
    return {
      fact: [`起盤時刻（${scale}）`, `${match[1]} ${match[2]}`],
      note: `這張盤的起盤時刻屬於「${scale}」，不是以閏秒維持的現代 UTC（見方法頁 §07.6）；`
        + "出生地時間只是同一瞬間換成出生地鐘點，方便對照。",
    };
  }

  /** 回應附的方法說明（整宮制、恆星黃道）：鍵一定在，值是 null 或一句話；其他形狀拒絕。 */
  function methodNote(block, key) {
    if (!Object.hasOwn(block, key)) throw new Error("太陽回歸盤回應形狀不符：方法說明。");
    const text = block[key];
    if (text === null) return [];
    if (typeof text !== "string" || !text.trim()) throw new Error("太陽回歸盤回應形狀不符：方法說明。");
    return [text];
  }

  /**
   * 出生地的鐘點：取同一份回應的 year_boundary.start（伺服器換好的出生地時間）。只有它與回歸盤
   * 是同一年時才用；別一年或沒有年界就不列，不在瀏覽器裡換算。同一年而 jd_ut 不同，表示回應自相矛盾，
   * 整區拒絕。比的是完全相等：伺服器把同一個 double 寫進兩處，JSON 來回不改值。
   */
  function birthPlaceClock(yearBoundary, block) {
    if (!yearBoundary || yearBoundary.completed_years !== block.completed_years) return null;
    const start = yearBoundary.start;
    if (!start || typeof start.local_time !== "string" || typeof start.jd_ut !== "number") return null;
    if (start.jd_ut !== block.instant.jd_ut) throw new Error("太陽回歸盤回應形狀不符：年界與回歸時刻不同。");
    return `${start.local_time}（${start.utc_offset || "時區未列"}）`;
  }

  const SOLAR_RETURN_COMPARE_NOTE = Object.freeze({
    before: "依 Abū Maʿshar 的做法並看三個上升；出處見方法頁〈", link: "太陽回歸盤", href: "/zh-TW/methods#solar-return", after: "〉。",
  });
  const isHouseNumber = (value) => Number.isInteger(value) && value >= 1 && value <= 12;
  const ownLabel = Labels.ownLabel;

  /**
   * 「與本命盤對照」：三個上升與回歸盤行星落在本命哪一宮，只列位置。回應沒算（欄位是 null）
   * 或與同一份回歸盤對不上時回 null，整區不畫；本命上升沒算時只少那一列。
   * 黃經照回歸盤天體表的原字（後端同一個格式器），不在瀏覽器裡捨入；兩邊數值對不上就不畫。
   */
  function solarReturnComparison(annualBody, block) {
    const houses = block.return_planets_in_natal_houses;
    const ascendantHouse = block.natal_house_of_return_ascendant;
    const natalSystem = ownLabel(Labels.VOCABULARIES.house_system, block.natal_house_system_code);
    const profected = ownLabel(Labels.VOCABULARIES.zodiac_sign, block.profected_sign);
    if (!Array.isArray(houses) || !houses.length || !isHouseNumber(ascendantHouse) || !natalSystem || !profected) return null;
    const data = block.chart && block.chart.astronomical_data;
    const returnAsc = data && data.angles && data.angles.sign_positions && data.angles.sign_positions.asc;
    if (!Array.isArray(returnAsc) || !SIGN_ORDER[returnAsc[0]]) return null;
    const bodies = new Map((data.bodies || []).map((body) => [body.key, body.sign_position]));
    const rows = [];
    for (const entry of houses) {
      const name = ownLabel(BODY_NAMES, entry && entry.key);
      const position = bodies.get(entry && entry.key);
      if (!name || !isHouseNumber(entry.natal_house) || typeof entry.longitude !== "number"
        || !Array.isArray(position) || typeof position[1] !== "string" || !SIGN_ORDER[position[0]]
        || Math.abs(Number(position[2]) - entry.longitude) > 1e-6) return null;
      rows.push(Object.freeze([name, position[2], `${signName(SIGN_ORDER[position[0]])} ${position[1]}`, `第 ${entry.natal_house} 宮`]));
    }
    const anchor = annualBody && annualBody.natal_anchor && annualBody.natal_anchor.ascendant;
    const natalAsc = anchor && anchor.status === "computed" ? ownLabel(Labels.VOCABULARIES.zodiac_sign, anchor.sign) : null;
    const systemText = `${natalSystem}${natalSystem.endsWith("宮") ? "制" : ""}`;
    return Object.freeze({
      title: "與本命盤對照",
      ascendants: Object.freeze([
        ...(natalAsc ? [["本命上升星座", natalAsc]] : []), ["小限星座", profected],
        ["年之上升（回歸盤上升）星座", signName(SIGN_ORDER[returnAsc[0]])],
      ]), ascendantHouse: `年之上升落在本命第 ${ascendantHouse} 宮（${systemText}）`, table: Object.freeze({
        title: "回歸盤行星落在本命哪一宮",
        columns: Object.freeze(["天體", "回歸盤黃經 λ（度）", "回歸盤星座度數", `本命宮（${systemText}）`]), rows: Object.freeze(rows),
      }),
      note: SOLAR_RETURN_COMPARE_NOTE,
    });
  }

  /**
   * 回歸盤一區的畫面模型。annualBody 是年度路由的回應；viewModel 是計算頁的 ChartViewModel
   * （buildSections 與本命盤同一套）；expectedIdentity 是畫面上時間主星模型的 identity。回 { state: "computed" | "not_applicable", … }；
   * 形狀不符時丟「太陽回歸盤回應形狀不符」，呼叫端整區不畫。
   */
  function solarReturnPanel(annualBody, viewModel, expectedIdentity) {
    // 回歸盤的回應也是年度回應：與時間主星同一條相容規則，而且要與畫面上已排出的模型同一個身分。
    if (!annualBody || typeof annualBody !== "object") fail("不是物件");
    const problem = compatibilityProblem(annualBody);
    if (problem) fail(problem);
    if (typeof expectedIdentity !== "string" || identityKey(annualBody) !== expectedIdentity) {
      fail("太陽回歸盤的回應與已排出的時間主星版本或出處清單不同");
    }
    const block = annualBody.solar_return_chart;
    if (!block || typeof block !== "object") throw new Error("太陽回歸盤回應形狀不符：沒有 solar_return_chart。");
    if (!Number.isInteger(block.completed_years) || block.year_of_life !== block.completed_years + 1) {
      throw new Error("太陽回歸盤回應形狀不符：年度。");
    }
    const heading = `太陽回歸盤（第 ${block.year_of_life} 年）`;
    if (block.status === "not_applicable") {
      const text = SOLAR_RETURN_REASONS[block.reason_code];
      if (!text) throw new Error("太陽回歸盤回應形狀不符：原因碼。");
      return Object.freeze({
        state: "not_applicable", completedYears: block.completed_years, heading, lead: SOLAR_RETURN_FIXED, code: block.reason_code, text,
      });
    }
    if (block.status !== "computed" || block.reason_code !== null || !block.chart || !block.instant
      || typeof block.instant.jd_ut !== "number" || !block.location) { throw new Error("太陽回歸盤回應形狀不符：狀態。"); }
    // 回歸盤這張星盤必須就是起盤那一瞬間的盤（完全相等，理由同 birthPlaceClock）。
    const chartTime = block.chart.astronomical_data && block.chart.astronomical_data.time;
    if (!chartTime || chartTime.jd_ut !== block.instant.jd_ut) { throw new Error("太陽回歸盤回應形狀不符：星盤時刻與回歸時刻不同。"); }
    const location = block.location;
    const other = location.source === "solar_return_location";
    if (!other && location.source !== "birth_location") throw new Error("太陽回歸盤回應形狀不符：地點來源。");
    const coordinates = `緯度 ${coordinateText(location.latitude, "N", "S")}、經度 ${coordinateText(location.longitude, "E", "W")}`;
    const local = birthPlaceClock(annualBody.year_boundary, block);
    const houseName = Labels.VOCABULARIES.house_system[block.house_system_code];
    if (!houseName) throw new Error("太陽回歸盤回應形狀不符：宮位制。");
    const moment = instantFact(block.instant);
    const methodNotes = [...methodNote(block, "house_system_note"), ...methodNote(block, "zodiac_note")];
    const sections = viewModel.buildSections(block.chart);
    const tables = SOLAR_RETURN_SECTIONS.map((id) => sections.find((section) => section.id === id))
      .filter((section) => section && section.status && section.status.state === "present")
      // 第一張表用區段名（本命盤的表名寫「本命天體」，不能搬到回歸盤上）；同區的其他表照原名。
      .flatMap((section) => section.tables.map((table, index) => Object.freeze({
        section: section.id, title: index === 0 ? section.title : (table.title || section.title), columns: table.columns, rows: table.rows,
      })));
    if (!tables.some((table) => table.section === "bodies")) throw new Error("太陽回歸盤回應形狀不符：沒有天體位置。");
    return Object.freeze({
      state: "computed", completedYears: block.completed_years, heading, lead: SOLAR_RETURN_FIXED,
      facts: Object.freeze([
        moment.fact, ...(local ? [["同一瞬間的出生地時間", local]] : []),
        ["地點", `${other ? "你輸入的地點" : "出生地（與本命盤相同）"}：${coordinates}`], ["宮位制", houseName],
        ["算法", SOLAR_RETURN_PROFILES[block.solar_return_profile] || block.solar_return_profile],
      ]), notes: Object.freeze([moment.note, ...methodNotes, ...(other ? [SOLAR_RETURN_OTHER_PLACE_TIME] : []),
      ]),
      privacy: other ? SOLAR_RETURN_PRIVACY : null, otherPlace: other, tables: Object.freeze(tables),
      comparison: solarReturnComparison(annualBody, block), chart: block.chart,
    });
  }

  return Object.freeze({
    pad2, SOLAR_RETURN_LEAD, SOLAR_RETURN_REASONS, SOLAR_RETURN_PRIVACY, SOLAR_RETURN_MORIN,
    SOLAR_RETURN_RELOCATION_OFFERED, SOLAR_RETURN_HOUSE_SYSTEMS, HOUSE_SYSTEM_NAMES: Labels.VOCABULARIES.house_system,
    solarReturnHouseSystem, parseSolarReturnLocation, solarReturnRequestBody, supportsSolarReturn, solarReturnPanel,
    ICS_LABEL, DATE_NOTE, SAMPLE_ORDER, DECENNIALS_START_PROFILES, DECENNIALS_START_SHORT, DECENNIALS_PLANETS,
    FIRDARIA_NODE_PROFILES, ZR_YEAR_MODELS, METHOD_CHOICE_SHORT, SOURCE_LINES, SOURCES, adaptAnnualSource, mergeLevel2,
    annualRequestBody, estimateCompletedYears, locateToday, buildModel, LIFE_LEAD, lifeOverview, lifeItemText,
    itemsInYear, referenceDay, summaryTiles, preferredSelection, briefLine, referenceNote, yearTitle, yearRange,
    describeItem, conventions, warningNotices, unavailableTechniques, sampleSummary, laneMeta, missingLevel2,
    missingMonths, monthsParentId, buildIcs, TIME_LORD_TABLE_FORMATS, TIME_LORD_TABLE_FORMAT_NAMES, buildTimeLordTable,
    buildTimeLordTableArtifact, foldLine, escapeText, plain, bodyName, signName, segmentSize,
  });
});
