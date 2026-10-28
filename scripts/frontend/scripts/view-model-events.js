// view-model：取樣、朔望與日月食、升降、落宮、日夜盤、行星時、月宿、焦傷與行速。
/**
 * 事件模組的三個代表性取樣。精確時刻時沒有取樣（回 null）；不精確時三個取樣恰好是 SAMPLE_ROLES、依序排列，缺一個、多一
 * 個或取樣說不出結果放在哪裡都拒絕。module 是 needAt 包好的模組容器。
 */
function representativeSamples(module) {
  const status = module.in("representative_sampling")("status", "string");
  if (status === "not_applicable_exact_birth_time") return null;
  if (status !== "sampled_interval_ends_and_anchor") {
    throw exportPipeline.incompleteResponse(`${module.path}.representative_sampling.status 不是已知的值：${status}`);
  }
  const rows = module.rows("representative_samples");
  needExactly(rows.map((row) => row("sample_role", "string")), SAMPLE_ROLES.map(([role]) => role), `${module.path}.representative_samples`);
  const localTimes = rows.map((row) => row("reference_local_time", "string"));
  const sameDate = localTimes.every((value) => value.slice(0, 10) === localTimes[0].slice(0, 10));
  return SAMPLE_ROLES.map(([role, label], index) => {
    const sample = rows[index];
    const location = sample("result_location", "string");
    if (location !== "module_top_level" && location !== "inline") {
      throw exportPipeline.incompleteResponse(`${sample.path}.result_location 不是已知的值：${location}`);
    }
    const top = location === "module_top_level";
    const local = sameDate ? localTimes[index].slice(11) : localTimes[index].replace("T", " ");
    return {
      role, heading: `${label}（當地 ${local}）`, sample, top,
      // 取樣自己算的那兩個才有拒絕清單；代表性時刻的拒絕就是模組自己的狀態。
      refusals: top ? {} : sample.in("module_refusals").record,
    };
  });
}

function sampleRefusal(entry, moduleKey) {
  if (entry.top || !Object.hasOwn(entry.refusals, moduleKey)) return null;
  const reason = need(entry.refusals[moduleKey], `${entry.sample.path}.module_refusals.${moduleKey}`, "reason_code", "string");
  return `未計算：${moduleReason(reason)}`;
}

function samplingNote(module, samples, tableName) {
  const interval = presentClosedVocabulary(module.in("representative_sampling")("interval", "string"), SAMPLING_INTERVAL_ZH, "取樣區間");
  return `出生時間不精確：上方各表是「${samples[1].heading}」的結果，不是出生時刻的事件。`
    + `依本站方法，另在${interval}的兩端各算一次；三個取樣並列於「${tableName}」表，不合併成一個答案。`
    + "同一次事件從不同的取樣時刻起算，數值求解停下的位置可能相差幾毫秒；這種差距是計算容差，不代表事件不同。";
}

const LUNAR_SAMPLE_KEYS = Object.freeze([
  ["primary_phases", "lunar_phases"], ["prenatal_syzygy", "prenatal_syzygy"], ["eclipses", "eclipses"],
]);

/**
 * 一個取樣看到的月相／日月食結果：省略的鍵取代表性時刻（模組頂層）的值。代表性時刻有結果、
 * 取樣卻沒有這個鍵，又沒列在 same_as_anchor、也沒有被拒絕，就是殘缺。
 */
function lunarSampleView(entry, module) {
  if (entry.top) return module.record;
  const omitted = entry.sample("same_as_anchor", "array");
  const view = {};
  LUNAR_SAMPLE_KEYS.forEach(([key, moduleKey]) => {
    if (Object.hasOwn(entry.sample.record, key)) view[key] = entry.sample.record[key];
    else if (omitted.includes(key)) view[key] = module(key);
    else if (Object.hasOwn(module.record, key) && !Object.hasOwn(entry.refusals, moduleKey)) {
      throw exportPipeline.incompleteResponse(`${entry.sample.path}.${key} 缺少，也沒有列為與代表性時刻相同或被拒絕`);
    }
  });
  return view;
}

function needInstant(instant) { return [instant("utc_time", "string"), instant("time_scale", "string")]; }

function lunarSamplesTable(module, samples) {
  const views = samples.map((entry) => lunarSampleView(entry, module));
  const rows = [];
  const eras = [];
  const at = (index, key) => `${samples[index].top ? module.path : samples[index].sample.path}.${key}`;
  const timedCell = (cell) => { eras.push(cell[1]); return cell; };
  if (Object.hasOwn(module.record, "primary_phases")) {
    Object.keys(module.in("primary_phases").record).forEach((key) => {
      [["previous", "前一次"], ["next", "下一次"]].forEach(([side, sideLabel]) => {
        rows.push([
          `${presentClosedVocabulary(key, LUNAR_PHASE_ZH, "事件")}（${sideLabel}）`, "lunar_phases",
          views.map((view, index) => (view.primary_phases === undefined ? null : timedCell(needInstant(
            needAt(view.primary_phases, at(index, "primary_phases")).in(key).in(side)
          )))),
        ]);
      });
    });
  }
  if (Object.hasOwn(module.record, "prenatal_syzygy")) {
    rows.push(["產前朔望", "prenatal_syzygy", views.map((view, index) => (
      view.prenatal_syzygy === undefined ? null : timedCell(needInstant(needAt(view.prenatal_syzygy, at(index, "prenatal_syzygy"))))
    ))]);
  }
  if (Object.hasOwn(module.record, "eclipses")) {
    ECLIPSE_SLOTS.forEach(([slot, label]) => {
      rows.push([label, "eclipses", views.map((view, index) => {
        if (view.eclipses === undefined) return null;
        const eclipse = needAt(view.eclipses, at(index, "eclipses")).in(slot);
        const scale = eclipse("time_scale", "string");
        eras.push(scale);
        return [eclipse("utc_time_maximum", "string"), scale,
          presentClosedVocabulary(eclipse("type", "string"), ECLIPSE_TYPE_ZH, "日月食類型")];
      })]);
    });
  }
  const timed = timedTable("三個代表性取樣", eras);
  return {
    title: timed.title, columns: ["事件"].concat(samples.map((entry) => entry.heading)),
    rows: rows.map(([label, moduleKey, cells]) => [label].concat(cells.map((cell, index) => {
      const refusal = sampleRefusal(samples[index], moduleKey);
      if (refusal) return refusal;
      if (!cell) { throw exportPipeline.incompleteResponse(`${at(index, moduleKey)} 沒有結果，也沒有被拒絕`); }
      const time = timed.cell(cell[0], cell[1]);
      return cell[2] ? `${cell[2]}，食甚 ${time}` : time;
    }))),
  };
}

const HORIZON_EVENT_KEYS = () => HORIZON_EVENTS.map(([key]) => key);

/**
 * 一個取樣看到的各天體地平事件：省略的事件取代表性時刻（模組頂層）的值。取樣的天體恰好是
 * 代表性時刻那一組；每個天體的事件，自己帶的加上 events_same_as_anchor，恰好是四種事件。
 */
function horizonSampleBodies(entry, module, anchorBodies) {
  if (entry.top) return anchorBodies;
  const bodies = entry.sample.rows("bodies");
  needExactly(bodies.map((body) => body("key", "string")), anchorBodies.map((body) => body("key")), `${entry.sample.path}.bodies`);
  return bodies.map((body, index) => {
    const own = body.in("events");
    const omitted = body("events_same_as_anchor", "array");
    needExactly([...Object.keys(own.record), ...omitted].sort(), HORIZON_EVENT_KEYS().sort(), `${body.path}.events`);
    const anchorEvents = anchorBodies[index].in("events");
    const events = {};
    omitted.forEach((name) => { events[name] = anchorEvents(name, "record"); });
    Object.assign(events, own.record);
    return needAt({ key: body("key"), events }, body.path);
  });
}

function horizonSamplesTable(module, samples, anchorBodies) {
  const refusals = samples.map((entry) => sampleRefusal(entry, "rise_set_transits"));
  const perSample = samples.map((entry, index) => (refusals[index] ? null : Object.fromEntries(
    horizonSampleBodies(entry, module, anchorBodies).map((body) => [body("key"), body])
  )));
  const eras = [];
  anchorBodies.forEach((body) => HORIZON_EVENTS.forEach(([key]) => ["previous", "next"].forEach((side) => {
    perSample.forEach((bodies) => {
      if (!bodies) return;
      const instant = bodies[body("key")].in("events").in(key)(side, "record?");
      if (instant) eras.push(needInstant(needAt(instant, `${body.path}.events.${key}.${side}`))[1]);
    });
  })));
  const timed = timedTable("三個代表性取樣：取樣之間不同的地平事件", eras);
  const rows = [];
  anchorBodies.forEach((body) => HORIZON_EVENTS.forEach(([key, label]) => {
    [["previous", "前一次"], ["next", "下一次"]].forEach(([side, sideLabel]) => {
      const cells = samples.map((_entry, index) => refusals[index]
        || horizonSideCell(perSample[index][body("key")].in("events").in(key), side, timed));
      if (new Set(cells).size > 1) { rows.push([body("name", "string"), `${label}（${sideLabel}）`].concat(cells)); } });
  }));
  return { title: timed.title, columns: ["天體", "事件"].concat(samples.map((entry) => entry.heading)), rows };
}

function lunarEventsSection(response) {
  const container = response.astronomical_data.lunar_events;
  const phasesState = moduleState(response, { option: "include_lunar_phases", module: "lunar_phases" }, container, true);
  const eclipsesState = moduleState(response, { option: "include_eclipses", module: "eclipses" }, container, true);
  if (phasesState.state !== "present" && eclipsesState.state !== "present") {
    return absentSectionFor("lunar_events", "朔望與日月食", RING.ASTRONOMICAL,
      "本次未請求朔望或日月食。",
      phasesState.state !== "not_requested" ? phasesState : eclipsesState);
  }
  const module = needAt(container, "lunar_events");
  const phaseName = (key) => presentClosedVocabulary(key, LUNAR_PHASE_ZH, "事件");
  const stamped = [];
  if (phasesState.state === "present") {
    // 四種月相各有前一次與下一次；應有的四種取自月相名稱表，不取自回應。
    const phases = module.in("primary_phases");
    needExactly(Object.keys(phases.record).sort(), Object.keys(LUNAR_PHASE_ZH).sort(), "lunar_events.primary_phases");
    Object.keys(phases.record).forEach((key) => {
      const entry = phases.in(key);
      stamped.push([`${phaseName(key)}（前一次）`, needInstant(entry.in("previous"))]);
      stamped.push([`${phaseName(key)}（下一次）`, needInstant(entry.in("next"))]);
    });
  }
  // 產前朔望只要它自己那一次事件，月相搜尋被拒絕時仍可能有結果；有沒有由它自己的狀態說。
  if (moduleState(response, { module: "prenatal_syzygy" }, null, true).state === "present") {
    const syzygy = module.in("prenatal_syzygy");
    stamped.push([`產前朔望：出生前最近一次地心朔或望（本次為${phaseName(syzygy("phase", "string"))}）`, needInstant(syzygy)]);
  }
  const phaseTable = timedTable("朔望時刻", stamped.map(([, instant]) => instant[1]));
  const rows = stamped.map(([label, instant]) => [label, phaseTable.cell(instant[0], instant[1])]);
  // 勾了「日月食」就要畫出後端算出的日月食：標題含日月食、表格零列的區段
  // 讀起來是「沒有東西發生」，正好把後端說的話反過來說。
  const eclipseEntries = eclipsesState.state === "present"
    ? ECLIPSE_SLOTS.map(([key, label]) => [label, module.in("eclipses").in(key)]) : [];
  const eclipseTable = timedTable("出生前最近一次日食與月食", eclipseEntries.map(([, entry]) => entry("time_scale", "string")), "全球搜尋");
  const eclipseRows = eclipseEntries.map(([label, entry]) => [
    label, presentClosedVocabulary(entry("type", "string"), ECLIPSE_TYPE_ZH, "日月食類型"),
    presentClosedVocabulary(entry.in("classification_borderline")("state", "string"), ECLIPSE_BORDERLINE_ZH, "類型判定"),
    eclipseTable.cell(entry("utc_time_maximum", "string"), entry("time_scale", "string")),
  ]);
  const borderlineNotes = eclipseEntries.map(([label, entry]) => (
    `${label}的類型判定：${entry.in("classification_borderline")("explanation_zh", "string")}`
  ));
  const tables = [];
  if (rows.length) { tables.push({ title: phaseTable.title, columns: ["事件", "時刻"], rows }); }
  if (eclipseRows.length) {
    tables.push({ title: eclipseTable.title, columns: ["事件", "類型", "類型判定", "食甚時刻"], rows: eclipseRows });
  }
  const samples = representativeSamples(module);
  const samplesTable = samples ? lunarSamplesTable(module, samples) : null;
  // 與地平事件同一個規則：三個取樣的結果全部相同時不另列表，只說明。
  const samplesDiffer = Boolean(samplesTable) && samplesTable.rows.some((row) => new Set(row.slice(1)).size > 1);
  if (samplesDiffer) tables.push(samplesTable);
  return makeSection("lunar_events", "朔望與日月食", RING.ASTRONOMICAL, { state: "present" }, {
    // 契約由月相與朔望的搜尋寫入；只勾日月食時沒有這個鍵。
    notes: (stamped.length
      ? [presentClosedVocabulary(module("contract", "string"), LUNAR_CONTRACT_ZH, "契約")] : []).concat(rows.length
        ? [PRENATAL_SYZYGY_NOTE] : [], eclipseRows.length
        ? ["日月食是全球搜尋的結果，沒有看出生地是否看得見。古典占星用日月食，主要是看它對地區與時局的作用"
          + "（《占星四書》II.4 說這是「第一個、也最有力的原因」）；把出生前最近一次日月食當作本命盤的要點，"
          + "是二十世紀才有的做法，我們讀過的古書裡沒有。"]
        : [], borderlineNotes, samplesTable && samplesTable.rows.length
        ? [samplingNote(module, samples, "三個代表性取樣")].concat(samplesDiffer
          ? []
          : ["三個代表性取樣的朔望與日月食結果全部相同，因此不另列表。"])
        : []
    ),
    tables,
  });
}

// 升降狀態的顯示名稱。鍵是後端 core/horizon_events.py 的 VISIBILITY_STATES 與 EVENT_STATUSES 閉集；
// tests/integration/test_frontend_contract.py 對照後端常數檢查兩邊恰好相同，這裡不得自創鍵。
const HORIZON_VISIBILITY_ZH = Object.freeze({
  rises_and_sets: "有升有降", above_horizon_between_bracketing_events: "在地平線上，介於前後兩次穿越之間",
  below_horizon_between_bracketing_events: "在地平線下，介於前後兩次穿越之間",
  continuously_above_during_search_interval: "搜尋區間內始終在地平線上",
  continuously_below_during_search_interval: "搜尋區間內始終在地平線下", grazing_contact: "擦過地平線，未穿越",
  indeterminate_evidence_conflict: "證據互相矛盾，無法判定", numerically_unavailable: "星曆或求解失敗",
  method_not_applicable: "此天體不適用",
});
const HORIZON_EVENT_STATUS_ZH = Object.freeze({
  event_found: "前後皆找到", grazing_contact: "擦過地平線，未穿越", always_above_threshold: "搜尋區間內始終在地平線上，無此事件",
  always_below_threshold: "搜尋區間內始終在地平線下，無此事件",
  no_event_within_search_interval: "搜尋區間內未找到此事件", numerically_unavailable: "星曆或求解失敗",
  method_not_applicable: "此天體不適用",
});


const HORIZON_EVENTS = Object.freeze([["rise", "上升"], ["set", "下降"], ["upper_transit", "上中天"], ["lower_transit", "下中天"]]);
// 每一側的搜尋狀態（horizon_events.py SIDE_STATUSES）。「未搜尋」與「搜尋區間內沒有」是不同值。
const HORIZON_SIDE_STATUS_ZH = Object.freeze({
  event_found: "已找到", no_event_within_search_interval: "搜尋區間內未找到", numerically_unavailable: "星曆或求解失敗",
  not_searched: "未搜尋",
});

/** 升降的一側（entry 是 needAt 包好的事件）：有時刻印時刻；沒有時刻印那一側的搜尋狀態，不折成 —。 */
function horizonSideCell(entry, side, table) {
  const instant = entry(side, "record?");
  if (instant) {
    const [utc, scale] = needInstant(needAt(instant, `${entry.path}.${side}`));
    return table.cell(utc, scale);
  }
  return presentClosedVocabulary(entry.in("search").in(side)("status", "string"), HORIZON_SIDE_STATUS_ZH, "搜尋狀態");
}

function horizonEventsSection(response) {
  const container = response.astronomical_data.horizon_events;
  const section = moduleSection(response, {
    id: "horizon_events", title: "升降與中天", ring: RING.ASTRONOMICAL,
    keys: { option: "include_rise_set_transits", module: "rise_set_transits" }, container, note: "本次未請求升降與中天。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "horizon_events");
  // 每個天體都搜尋升降：應有的天體與天體位置表同一組，事件恰好是四種。
  const bodies = module.rows("bodies");
  needExactly(bodies.map((body) => body("key", "string")), expectedBodyKeys(response), "horizon_events.bodies");
  bodies.forEach((body) => needExactly(Object.keys(body.in("events").record).sort(), HORIZON_EVENT_KEYS().sort(), `${body.path}.events`));
  const eras = [];
  bodies.forEach((body) => {
    const events = body.in("events");
    HORIZON_EVENTS.forEach(([key]) => {
      ["previous", "next"].forEach((side) => {
        const instant = events.in(key)(side, "record?");
        if (instant) eras.push(needInstant(needAt(instant, `${body.path}.events.${key}.${side}`))[1]);
      });
    });
  });
  const timed = timedTable("地平事件", eras);
  const samples = representativeSamples(module);
  const samplesTable = samples ? horizonSamplesTable(module, samples, bodies) : null;
  const samplingNotes = samples
    ? [samplingNote(module, samples, "三個代表性取樣"),
      samplesTable.rows.length ? "「三個代表性取樣」表只列三個取樣之間不同的事件；沒列出的事件，三個取樣的結果相同。"
        : "三個代表性取樣的地平事件結果全部相同，因此不另列表。"]
    : [];
  return section.make({
    notes: horizonContractNotes(module.in("contract")).concat(samplingNotes),
    tables: [{
      title: timed.title, columns: ["天體", "可見性", "事件", "狀態", "前一次", "下一次"],
      rows: bodies.flatMap((body) => {
        const events = body.in("events");
        const visibility = presentClosedVocabulary(body("visibility", "string"), HORIZON_VISIBILITY_ZH, "可見性");
        return HORIZON_EVENTS.map(([key, label]) => {
          const entry = events.in(key);
          return [
            body("name", "string"), visibility, label,
            presentClosedVocabulary(entry("status", "string"), HORIZON_EVENT_STATUS_ZH, "事件狀態"),
            horizonSideCell(entry, "previous", timed), horizonSideCell(entry, "next", timed),
          ];
        });
      }),
    }].concat(samplesTable && samplesTable.rows.length ? [samplesTable] : []),
  });
}

function planetInHouseSection(response) {
  const container = response.derived_methods.planet_in_house;
  const section = moduleSection(response, {
    id: "planet_in_house", title: "行星落宮", ring: RING.METHOD,
    keys: { option: "include_houses", module: "planet_in_house" }, container, note: "本次未請求宮位，因此沒有落宮。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "planet_in_house");
  if (module("execution_status", "string") !== "computed") {
    throw exportPipeline.incompleteResponse("planet_in_house 狀態是已計算，execution_status 卻不是 computed");
  }
  // 落宮的每一列都是 astronomical_data.bodies 的同一個天體（後端以同一份清單計算）：應有的列是天體位置表
  // 裡有黃經的那幾顆（星曆範圍外算不出位置的天體沒有落宮，house_placements.py），依同一順序；
  // 黃經文字依鍵讀那一列的 sign_position，不在這裡另寫一份。
  const positioned = response.astronomical_data.bodies.filter((body) => body.sign_position !== null);
  const placements = module.rows("placements");
  needExactly(placements.map((place) => place("key", "string")), positioned.map((body) => body.key), "planet_in_house.placements");
  const bodies = positioned;
  const points = pointPlacementTable(response, module);
  return section.make({
    notes: [
      `宮位制：${houseSystemText(module("house_system_code", "string"), module("house_system_name", "string"))}。`,
      "距最近宮頭的黃經差一律列出（沿黃道量，不計黃緯），讓你自己判斷這個落宮對出生時刻有多敏感。", ...points.notes,
    ],
    tables: [{
      title: "落宮", columns: ["天體", LONGITUDE_COLUMN, "宮", "距最近宮頭（黃經差，度）", "在宮頭上"], collapse: ["在宮頭上"],
      rows: placements.map((place, index) => {
        const house = place("house", "number?");
        return [
          place("name", "string"), longitudeText(bodies[index].sign_position), house === null ? DASH : String(house),
          num(place("distance_to_nearest_cusp_degrees", "number?"), 4), place("on_cusp", "boolean?") === true ? "是" : "否",
        ];
      }),
    }, ...points.tables],
  });
}

/**
 * 月交點與月球拱點（Lilith 等）的落宮：後端只在整宮制給（planet_in_house.point_placements），
 * 整宮制的宮就是星座。其他宮位制後端回具名原因，這裡說一句，不自己用星座補。
 */
const POINT_PLACEMENT_TITLE = "月交點、Lilith 與 Priapus 的落宮（整宮制）";
function pointPlacementTable(response, module) {
  const points = module.in("point_placements");
  if (points("execution_status", "string") !== "computed") {
    return {
      notes: points("reason_code", "string?") === "not_whole_sign_house_system"
        ? ["月交點、Lilith 與 Priapus 不是行星，只在整宮制列出落宮（整宮制的宮就是星座）；本次的宮位制不列。"] : [], tables: [],
    };
  }
  // 應有的點：本盤有黃經的每一個月交點與月球拱點（後端以同一份清單計算），依同一順序。
  const astro = response.astronomical_data;
  const apsides = isRecord(astro.lunar_apsides) && Array.isArray(astro.lunar_apsides.points) ? astro.lunar_apsides.points : [];
  const sources = [...astro.nodes, ...apsides].filter((record) => record.sign_position !== null);
  const placements = points.rows("placements");
  needExactly(placements.map((place) => place("key", "string")), sources.map((record) => record.key),
    "planet_in_house.point_placements.placements");
  // 約略時辰：出生時間敏感度只逐列列出行星的落宮；各點的落宮在這一小時內換不換，
  // 讀分類覆蓋裡改變的路徑（後端以鍵命名每一點），在這張表說出來。
  const sensitivity = isRecord(response.birth_time_sensitivity) ? response.birth_time_sensitivity : {};
  const moving = new Set(differingClassificationPaths(sensitivity)
    .map((item) => /^derived_methods\.planet_in_house\.point_placements\.placements\[([^\]]+)\]\.house$/.exec(String(item))).filter(Boolean)
    .map((match) => match[1]));
  const movingNames = placements.filter((place) => moving.has(place("key"))).map((place) => place("name", "string"));
  return {
    notes: [
      "月交點、Lilith 與 Priapus 不是行星，另列一張；整宮制的宮就是星座，所以只在整宮制列出它們的落宮。",
      ...(movingNames.length
        ? [`只知道約略時辰：這一小時內${movingNames.join("、")}的落宮會變；表中的宮位依代表性時刻判定。`]
        : [])], tables: [{ title: POINT_PLACEMENT_TITLE, columns: ["點", LONGITUDE_COLUMN, "宮"],
      rows: placements.map((place, index) => [
        place("name", "string"), longitudeText(sources[index].sign_position), String(place("house", "number")),
      ]),
    }],
  };
}

// −50′ < 太陽真高度 ≤ 0° 時，後端 named_boundary_disagreement 為 true。日夜盤與阿拉伯點兩區共用這一句，不各寫一份。
const NAMED_BOUNDARY_DISAGREEMENT_NOTE = "這張盤的太陽中心在地平線下 50 角分以內：本產品的規則判為夜盤，"
  + "但依天文年鑑的標準日出日落定義，這時太陽還算在地平線上，兩種定義判法不同。";

function yesNo(value) { return value === true ? "是" : value === false ? "否" : DASH; }

function sectSection(response) {
  const module = response.derived_methods.sect;
  const section = moduleSection(response, {
    id: "sect", title: "日夜盤", ring: RING.METHOD, keys: { module: "sect" }, container: module, note: "本次未計算日夜盤。",
  });
  if (section.absent) return section.absent;
  // 算出了日夜盤，判定、狀態、所用高度與兩個旗標就都在；缺一項不補成「夜生盤」或「否」。
  need(module, "sect", "is_day", "boolean");
  need(module, "sect", "sect_status", "string");
  need(module, "sect", "sun_altitude_used", "number");
  need(module, "sect", "in_near_horizon_band", "boolean");
  need(module, "sect", "named_boundary_disagreement", "boolean?");
  const bandArcmin = num(need(module, "sect", "near_horizon_band_half_width_degrees", "number") * 60, 0);
  return section.make({
    notes: (
      module.in_near_horizon_band === true
        ? [`此盤太陽真高度在近地平敏感帶（±${bandArcmin}′）內。`
           + "判定本身仍依太陽真高度 > 0° 的規則確定；若改用標準視日出（太陽上緣初現）等其他具名邊界，"
           + `太陽高度在 −${bandArcmin}′ 到 0° 之間時日夜盤會相反，因此阿拉伯點兩套公式並列。`]
        : []).concat(module.named_boundary_disagreement === true ? [NAMED_BOUNDARY_DISAGREEMENT_NOTE] : []
    ),
    tables: [{
      title: "判定", columns: ["項目", "數值"],
      rows: [
        ["判定", module.is_day === true ? "日生盤" : "夜生盤"],
        ["狀態", presentClosedVocabulary(module.sect_status, SECT_STATUS_ZH, "日夜盤狀態")],
        ["判定規則", "太陽中心在真地平線上方時為日盤；恰好 0° 或在下方時為夜盤"], ["所用太陽高度", num(module.sun_altitude_used, 6)],
        ["近地平敏感帶內", module.in_near_horizon_band === true ? "是" : "否"],
        ["兩種日出日落定義判法不同", yesNo(module.named_boundary_disagreement)],
      ],
    }],
  });
}

// core/planetary_hours.py WEEKDAYS 與 PERIODS 的閉集。
const WEEKDAY_ZH = Object.freeze({
  monday: "星期一", tuesday: "星期二", wednesday: "星期三", thursday: "星期四", friday: "星期五", saturday: "星期六", sunday: "星期日",
});
const PLANETARY_PERIOD_ZH = Object.freeze({ day: "晝", night: "夜" });
const PLANETARY_INTERVAL_ZH = Object.freeze({ stated_civil_hour: "你填的那一個鐘點", civil_day: "出生那一天（民用日）" });

function planetaryHourText(hour) {
  const period = presentClosedVocabulary(hour("period", "string"), PLANETARY_PERIOD_ZH, "晝夜");
  return `第 ${hour("index", "number")} 時（${period}第 ${hour("index_in_period", "number")} 時）`;
}

/** 當地時刻字串補成同一長度（「1990-05-15T14:00」與「1990-05-15 13:01:43.815」才比得了先後）。 */
function localSortKey(text) {
  const template = "0000-00-00T00:00:00.000";
  const value = String(text).replace(" ", "T");
  return value + template.slice(value.length);
}

/**
 * 只填日期時，候選依真正的時間先後排、互不重疊，而且恰好蓋住回應寫明的民用日 UTC 段落
 * （calculation_dossier.time_conversion.civil_day.utc_spans）：每一段由與它相交的候選首尾相連地蓋滿，
 * 沒有一個候選落在所有段落之外。時鐘撥回會把民用日切成兩段 UTC，兩段之間那一時屬於另一天，
 * 不在清單裡是對的；應有的範圍取自段落，不取自候選清單本身。
 */
function civilDayCandidatesBroken(candidates, civilDay) {
  const instant = (item, key) => Date.parse(item.in(key)("utc_time", "string"));
  const spans = needAt(civilDay, "calculation_dossier.time_conversion.civil_day").rows("utc_spans").map((span) => [
    Date.parse(span("start_utc", "string")), Date.parse(span("end_exclusive_utc", "string"))]);
  const times = candidates.map((item) => [instant(item, "start"), instant(item, "end")]);
  const valid = ([from, to]) => Number.isFinite(from) && Number.isFinite(to) && from < to;
  if (!spans.length || !spans.every(valid) || !times.every(valid)) return true;
  if (spans.some(([from], index) => index > 0 && from < spans[index - 1][1])) return true;
  if (times.some(([from], index) => index > 0 && from < times[index - 1][1])) return true;
  const overlapping = (span) => times.filter(([from, to]) => from < span[1] && to > span[0]);
  if (times.some((time) => !spans.some((span) => overlapping(span).includes(time)))) return true;
  return spans.some((span) => {
    const covering = overlapping(span);
    return !covering.length || covering[0][0] > span[0] || covering.at(-1)[1] < span[1]
      || covering.some(([from], index) => index > 0 && from !== covering[index - 1][1]);
  });
}

/**
 * 可能的行星時：一個接一個、首尾相連地蓋住整段出生時間。應有的範圍取自出生時間敏感度的區間，
 * 不取自候選清單本身：第一個不晚於區間起點、最後一個不早於區間終點、中間不斷；代表性時刻
 * 所在的那一時必須在裡面；「跨過行星時／行星日交界」兩個旗標要與候選相符。只填日期時改依
 * 民用日的 UTC 段落核對（civilDayCandidatesBroken）。
 */
function planetaryCandidates(interval, hour, sensitivity, civilDay) {
  const candidates = interval.rows("candidates");
  const path = `${interval.path}.candidates`;
  const start = (item) => item.in("start")("local_time", "string");
  const end = (item) => item.in("end")("local_time", "string");
  if (interval("interval", "string") === "civil_day") {
    if (!candidates.length || civilDayCandidatesBroken(candidates, civilDay)) {
      throw exportPipeline.incompleteResponse(`${path} 沒有恰好蓋住出生那一天的每一段 UTC 時間`);
    }
  } else {
    // 區間的兩端只有取樣完成時才在（checkSensitivity 已核過）；取樣被拒絕時只核首尾相連。兩端是鐘面時刻：這段時間裡時鐘撥
    // 動過（候選的 UTC 偏移不只一種）時，鐘面先後不等於真正的先後（撥回的那一小時走兩次），也只核首尾相連。
    const offsets = new Set(candidates.flatMap((item) => [item.in("start")("utc_offset", "string"), item.in("end")("utc_offset", "string")]));
    const bounds = sensitivity.status === "computed" && offsets.size === 1
      ? [localSortKey(sensitivity.interval_start_local), localSortKey(sensitivity.interval_end_exclusive_local)] : null;
    const broken = !candidates.length
      || (bounds && (localSortKey(start(candidates[0])) > bounds[0] || localSortKey(end(candidates.at(-1))) < bounds[1]))
      || candidates.some((item, index) => index > 0 && start(item) !== end(candidates[index - 1]));
    if (broken) throw exportPipeline.incompleteResponse(`${path} 沒有首尾相連地蓋住出生時間的區間`);
  }
  const same = (item) => item("index", "number") === hour("index", "number")
    && item("period", "string") === hour("period", "string") && start(item) === hour.in("start")("local_time", "string");
  if (!candidates.some(same)) { throw exportPipeline.incompleteResponse(`${path} 不含代表性時刻所在的那一時`); }
  const days = new Set(candidates.map((item) => item("planetary_day_ruler_name", "string")));
  if (interval("crosses_hour_boundary", "boolean") !== (candidates.length > 1)
    || interval("crosses_planetary_day_boundary", "boolean") !== (days.size > 1)) {
    throw exportPipeline.incompleteResponse(`${interval.path} 的跨交界旗標與候選對不上`);
  }
  return candidates;
}

function planetaryHoursSection(response) {
  const container = response.derived_methods.planetary_hours;
  const section = moduleSection(response, {
    id: "planetary_hours", title: "行星日與行星時", ring: RING.METHOD, keys: { module: "planetary_hours" }, container,
    note: "本次未計算行星日與行星時。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "planetary_hours");
  const instant = module.in("chart_instant");
  const day = instant.in("planetary_day");
  const hour = instant.in("planetary_hour");
  const anchored = module("time_basis", "string") !== "birth_instant";
  // 出生時間不精確（代表性時刻）時才讀區間；精確時刻的區間只有出生那一時，畫面不列。
  const interval = anchored ? module.in("birth_time_interval") : null;
  const notes = [
    "行星日從日出算起，不從午夜算起：日出到日落十二等分為晝時，日落到下一次日出十二等分為夜時，"
    + "所以晝時與夜時通常不等長。第一時之主是日出那天（民用日：出生地日曆上的那一天，從午夜到午夜）的七曜之主，"
    + "之後依迦勒底序（土星、木星、火星、太陽、金星、水星、月亮）逐時輪替。",
    "日出與日落用太陽上緣、含標準大氣折射、從地表觀測者看、不計地平俯角，與「升降與中天」同一個定義。"
    + "日盤夜盤的判定另用太陽中心是否在地平線上、不計折射，所以日出後約幾分鐘內，可能行星時已是晝時、日夜盤仍判為夜盤。",
  ];
  const candidates = anchored ? planetaryCandidates(
    interval, hour, response.birth_time_sensitivity, response.calculation_dossier?.time_conversion?.civil_day) : [];
  if (anchored) {
    notes.push(
      "出生時刻不精確：「代表性時刻所在的行星日與行星時」表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；"
      + `「可能的行星時」表列出${presentClosedVocabulary(interval("interval", "string"), PLANETARY_INTERVAL_ZH, "區間")}`
      + "內每一個可能的行星時。" + (interval("crosses_hour_boundary", "boolean") ? "這段時間跨過行星時的交界，行星時無法只定一個。" : "")
      + (interval("crosses_planetary_day_boundary", "boolean") ? "這段時間也跨過日出，行星日之主有兩個可能。" : "")
    );
  }
  const instants = [
    ["日出（行星日開始）", day.in("sunrise")], ["日落（晝時結束、夜時開始）", day.in("sunset")],
    ["下一次日出（行星日結束）", day.in("next_sunrise")], ["本行星時開始", hour.in("start")], ["本行星時結束", hour.in("end")],
  ];
  const timed = timedTable("時刻", instants.map(([, item]) => needInstant(item)[1]));
  const weekday = presentClosedVocabulary(day("weekday", "string"), WEEKDAY_ZH, "星期");
  const localZone = sharedOffsetColumn(instants.map(([, item]) => item));
  const candidateZone = sharedOffsetColumn(anchored ? candidates.flatMap((item) => [item.in("start"), item.in("end")]) : []);
  const tables = [
    {
      title: anchored ? "代表性時刻所在的行星日與行星時" : "出生時刻所在的行星日與行星時", columns: ["項目", "數值"],
      rows: [
        ["行星日之主", `${day("ruler_name", "string")}（日出在 ${day("sunrise_local_date", "string")}，${weekday}）`],
        ["行星時", planetaryHourText(hour)], ["行星時之主", hour("ruler_name", "string")],
        ["一個晝時的長度（分鐘）", num(day("day_hour_minutes", "number"), 1)],
        ["一個夜時的長度（分鐘）", num(day("night_hour_minutes", "number"), 1)],
      ],
    }, {
      // 時間尺度標在世界時欄（timed.heading），不標在表題：當地時間欄不是 UTC。
      title: "行星日與行星時的起訖時刻", columns: ["事件", localZone.heading("當地時間"), timed.heading("世界時")],
      rows: instants.map(([label, item]) => [label, localZone.cell(item), timed.cell(...needInstant(item))]),
    },
  ];
  if (anchored) {
    tables.push({
      title: "可能的行星時",
      columns: ["行星日之主", "行星時", "行星時之主", candidateZone.heading("開始（當地時間"), candidateZone.heading("結束（當地時間")],
      rows: candidates.map((item) => [
        item("planetary_day_ruler_name", "string"), planetaryHourText(item), item("ruler_name", "string"),
        candidateZone.cell(item.in("start")), candidateZone.cell(item.in("end")),
      ]),
    });
  }
  return section.make({ notes, tables });
}

// core/lunar_mansions.py INTERVALS 的閉集。
const MANSION_INTERVAL_ZH = Object.freeze({
  stated_civil_hour: "你填的那一個鐘點", civil_day: "出生那一天（民用日：出生地日曆上的那一天，從午夜到午夜）",
});

/** 「第 23 宿 Saʿd Bulaʿ」：宿名只寫原名的轉寫，不譯成中文；mansion 是 needAt。 */
function mansionText(mansion) {
  return `第 ${mansion("number", "number")} 宿 ${mansion("transliteration", "string")}`;
}

// 區塊標題附英文，與「十二分部 Dodecatemoria」同一寫法。
const LUNAR_MANSIONS_TITLE = "月宿 Lunar Mansions";
// 月宿只看月亮（後端 lunar_mansions.py PLACED_BODIES）。
const LUNAR_MANSION_BODIES = Object.freeze(["moon"]);
const MANSION_COUNT = 28;

function lunarMansionsSection(response) {
  const container = response.derived_methods.lunar_mansions;
  const section = moduleSection(response, {
    id: "lunar_mansions", title: LUNAR_MANSIONS_TITLE, ring: RING.METHOD,
    keys: { option: "include_lunar_mansions", module: "lunar_mansions" }, container, note: "本次未請求月宿。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "lunar_mansions");
  const placements = module.rows("placements");
  needExactly(placements.map((item) => item("key", "string")), LUNAR_MANSION_BODIES, "lunar_mansions.placements");
  const width = module.in("division")("width_text", "string");
  // 出生時間不精確時才有區間；精確時刻這個鍵在、值是 null（精度由出生時間敏感度說）。
  const exact = response.birth_time_sensitivity.precision === "exact";
  const interval = module.in("birth_time_interval", exact);
  if (exact && interval !== null) { throw exportPipeline.incompleteResponse("lunar_mansions.birth_time_interval 在精確時刻應為 null"); }
  const bodies = response.astronomical_data.bodies;
  const notes = [
    `月宿是把黃道從牡羊 0°（春分點）起分成 28 等分，每宿 ${width}，看月亮落在哪一宿。`
    + "這是中世紀阿拉伯與歐洲占星書的分法；宿名是阿拉伯星名，照原名的拉丁字母轉寫，不譯成中文。",
    "這不是古中國的二十八宿：二十八宿沿天球赤道、以各宿的距星（每宿起點的那顆星）劃分，寬窄不一，"
    + "名稱與範圍都不同，這裡不換算成二十八宿。", "只列月亮落在哪一宿。",
  ];
  const near = placements.filter((item) => item("near_boundary", "boolean"));
  if (!interval && near.length) { notes.push("月亮離月宿的交界不到 1′：出生時刻差幾分鐘就可能落在相鄰的另一宿。"); }
  // 區間內月亮待過的宿：一宿接一宿（第 28 宿之後是第 1 宿），代表性時刻那一宿在裡面，「跨過交界」與宿數相符。
  const mansions = interval ? interval.rows("mansions") : [];
  if (interval) {
    const numbers = mansions.map((item) => item("number", "number"));
    const consecutive = numbers.every((value, index) => index === 0 || value === (numbers[index - 1] % MANSION_COUNT) + 1);
    const anchors = placements.map((item) => item.in("mansion")("number", "number"));
    if (!numbers.length || !consecutive || !anchors.every((value) => numbers.includes(value))
      || interval("crosses_mansion_boundary", "boolean") !== (numbers.length > 1)) {
      throw exportPipeline.incompleteResponse("lunar_mansions.birth_time_interval.mansions 與代表性時刻或跨界旗標對不上");
    }
    notes.push(
      "出生時刻不精確：上面那張表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；"
      + `下面那張表列出${presentClosedVocabulary(interval("interval", "string"), MANSION_INTERVAL_ZH, "區間")}` + "裡月亮待過的每一宿。"
      + (interval("crosses_mansion_boundary", "boolean") ? "這段時間跨過月宿交界，月宿無法只定一個。" : "")
    );
  }
  const tables = placements.map((item) => {
    const mansion = item.in("mansion");
    const bounds = mansion.in("boundary_sign_positions");
    const name = item("name", "string");
    const body = bodies.find((record) => record.key === item("key"));
    return {
      title: interval ? `代表性時刻${name}所在的月宿` : `${name}所在的月宿`, columns: ["項目", "數值"],
      rows: [
        [`${name}的位置`, signPosition(body.sign_position)], ["月宿", mansionText(mansion)],
        ["本宿範圍", `${signPosition(bounds.position("start"))} 至 ${signPosition(bounds.position("end"))}（不含終點）`],
        ["在宿內走了多遠", item("degrees_into_mansion_text", "string")],
        // 與上一列同寫度分秒；不到 1′ 時區塊說明與注意事項各說一次，不另列是／否。
        ["離最近的交界", dms(item("distance_to_nearest_boundary_degrees", "number"))],
      ],
    };
  });
  if (interval) {
    tables.push({
      title: "這段時間內月亮待過的月宿", columns: ["月宿", "阿拉伯名稱"],
      rows: mansions.map((item) => [`第 ${item("number")} 宿`, item("transliteration", "string")]),
    });
  }
  return section.make({ notes, tables, blocks: LUNAR_MANSION_SOURCES.slice() });
}

// 出處的一行由 labels.js 的 sourceLine 組成（登錄以鍵列出處時第一欄用鍵）；整合測試逐行核對層級與登錄裡那條引文相同。
function sourceBlocks(lines) { return Object.freeze(lines.map(Labels.sourceLine)); }

// 月宿的出處：章節加一句白話，與方法出處登錄 lunar_mansions 同一組來源；
// 和十二分部一樣是區塊，畫面收進「出處」摺疊（SOURCE_FOLDED_SECTIONS），匯出逐條印出。
const LUNAR_MANSION_SOURCE_LINES = Object.freeze([
  ["Agrippa, De occulta philosophia II.33",
    "出處：Agrippa《De occulta philosophia》卷二第 33 章（1651 年英譯本）："
    + "28 個月宿等分黃道，每宿 12°51′ 又將近 26″；第 1、8、15、22 宿從牡羊、巨蟹、天秤、摩羯的起點開始。",
    "translation_read", "（英譯，掃描本）"], ["al-Biruni, Chronology of Ancient Nations ch. XXI",
    "出處：al-Bīrūnī《古代民族年代學》（al-Āthār al-bāqiya）第 21 章（Sachau 1879 英譯，pp. 335–366）："
    + "阿拉伯人把天球分成 28 份、每個星座兩又三分之一份，從 al-Sharaṭān 起算，因為當時它的星在牡羊之初；"
    + "之後星已移動。宿名也依這一章。",
    "translation_read", "（英譯，掃描本）"], [null, "出處：本站方法頁〈月宿〉一節：從回歸黃道的春分點（當日）起算，是本站對這套等分的做法；"
    + "上面兩本書說的是當時恆星天的牡羊之初。"],
]);
const LUNAR_MANSION_SOURCES = sourceBlocks(LUNAR_MANSION_SOURCE_LINES);

// 距離帶的名稱只有這一張表。兩套寫法並列：traditional 用原典名稱當主標籤，distance 是以距離描述當主標籤的另一案；換用時
// 只改 SOLAR_PHASE_BAND_ZH 那一行。
const SOLAR_PHASE_TITLE = "焦傷與光束下（離太陽多近）";
const SOLAR_PHASE_BAND_LABELS = Object.freeze({
  traditional: Object.freeze({
    cazimi: "日輪內（cazimi）", combust: "焦傷（combust）", under_beams: "在光束下（under the beams）",
    clear: "離開光束", accompanying_high_latitude: "伴隨太陽（muqārina）" }), distance: Object.freeze({
    cazimi: "日輪內（cazimi）", combust: "緊貼太陽（焦傷，combust）",
    under_beams: "在太陽光芒下（在光束下，under the beams）", clear: "離開光芒", accompanying_high_latitude: "伴隨太陽（muqārina）",
  }),
});
const SOLAR_PHASE_BAND_ZH = SOLAR_PHASE_BAND_LABELS.traditional;
// core/solar_phase.py PROFILE_IDS，順序即對照表的欄序。
const SOLAR_PHASE_PROFILE_ZH = Object.freeze({
  lilly_1647_p113_v1: "Lilly 1647（17′、8°30′、17°）", hellenistic_15_v1: "希臘化（一條 15° 的線）",
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
  morning: "西側，比太陽早升起（晨星）", evening: "東側，比太陽晚落下（昏星）", on_the_sun: "與太陽同一黃經",
});
const SOLAR_PHASE_MOTION_ZH = Object.freeze({
  approaching_sun: "正在靠近太陽", separating_from_sun: "正在離開太陽", no_relative_motion: "與太陽沒有相對移動",
});
const SOLAR_PHASE_CROSSING_ZH = Object.freeze({ emerging: "升出光束", sinking: "隱入光束" });
const SOLAR_PHASE_LIMIT_SIDE_ZH = Object.freeze({ morning: "西側（晨星）", evening: "東側（昏星）" });
const SOLAR_PHASE_INTERVAL_ZH = Object.freeze({
  stated_civil_hour: "你填的那一個鐘點", civil_day: "出生那一天（民用日：出生地日曆上的那一天，從午夜到午夜）",
});
const SOLAR_PHASE_FIXED_SENTENCE = "照原典列出各分法怎麼說；不替這張盤做個人解讀，也不預測。";
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
    "original_language_read", "（1659 年轉錄本，頁碼依 Houlding）"], ["al-Biruni, The Book of Instruction",
    "出處：al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm，Wright 1934 英譯）§481–484：不到 16′ 稱 samīm（即 Cazimi）；"
    + "到 6° 稱 muḥtariq（焦傷，字面是「被燒」），水星、金星順行時到 7°；之後在光束下，行星「像被關住的囚犯」，"
    + "在東方升出的界線是金星、水星 12°，土星、木星 15°，火星 16°，在西方隱入的界線是土星、木星 16°，火星 18°；"
    + "月亮不到 7° 為焦傷，到 12° 為止在光束下。",
    "translation_read", "（英譯，線上打字稿，1934 年版的頁碼未核）"],
  [null, "出處：al-Bīrūnī 同書 §483：金星在會合時北黃緯超過 7°，不稱 samīm 也不稱焦傷，只稱「伴隨太陽」（muqārina）；"
    + "§486：行星的作用在焦傷時最小。"], ["Abu Ma'shar, Great Introduction VII.2",
    "出處：Abū Maʿshar《大導論》（Kitāb al-mudkhal al-kabīr）VII.2，Hermann of Carinthia 的拉丁譯本：除了 zamim（Cazimi），"
    + "太陽會灼燒與它會合的每一顆星，使它衰弱、敗壞；金星因為黃緯，與太陽在同一度時仍看得見，" + "這時不能稱為焦傷，而稱「顯現」。",
    "translation_read", "（Hermann 的拉丁文譯本，線上讀；阿拉伯原本未讀，Dykes 英譯 p.418 只見轉引）"],
  [null, "出處（本站的推論，不是原典的話）：為什麼判定用黃經差。上面兩位作者都替「北黃緯很高的金星」另立例外。"
    + "這樣的金星在天空中離太陽已有 7°–8°，若他們量的是天空中的實際距離，它本來就在 16′ 與 6° 之外，"
    + "根本不需要例外；正因為他們量的是黃道上的度數，金星與太陽「在同一度」，才需要另外說明它看得見、不算焦傷。"], ["Ptolemy, ",
    "出處：Ptolemy《占星四書》III.10（Robbins 1940 英譯 p.285）：在太陽光線下的行星，不採為破壞者，也不採為援助者。",
    "translation_read", "（英譯，LacusCurtius 轉錄）"], ["Porphyry, Introduction ch.2 and ch.30",
    "出處：希臘化時期一條 15° 的線，以及出生前後 7 天內升出或隱入光束：Porphyry 名下的《占星四書導論》（Eisagōgē）第 2、30 章、Antiochus、"
    + "Rhetorius（Brennan 2017；Holden 2009 pp.24、134 經網頁轉引），原文未核。",
    "secondary_only"],
  [null, "出處：完整書目與每一條核到哪一層，見方法頁〈焦傷與光束下〉一節。"],
]);
const SOLAR_PHASE_SOURCES = sourceBlocks(SOLAR_PHASE_SOURCE_LINES);

/** 「+16°33′58.20″」：後端給絕對值的度分秒，正負號照黃經差；row 是 needAt。 */
function solarPhaseDifferenceText(row) {
  const value = row("longitude_difference_degrees", "number");
  return `${value < 0 ? "−" : "+"}${row("longitude_difference_text", "string")}`;
}

function solarPhaseLimitText(limit, path) {
  if (limit === null) return "（這套分法沒有這一帶）";
  const at = needAt(limit, path);
  // 依順行／逆行而不同的界線只有這兩個鍵；一般的界線是度數加是否含端點。
  if (Object.hasOwn(limit, "direct") || Object.hasOwn(limit, "retrograde")) {
    return `順行 ${solarPhaseLimitText(at("direct", "record?"), `${path}.direct`)}；`
      + `逆行 ${solarPhaseLimitText(at("retrograde", "record?"), `${path}.retrograde`)}`;
  }
  const minutes = Math.round(at("degrees", "number") * 60);
  const whole = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const text = whole ? `${whole}°${rest ? `${String(rest).padStart(2, "0")}′` : ""}` : `${rest}′`;
  return `${at("inclusive", "boolean") ? "≤" : "<"} ${text}`;
}

function solarPhaseOffsetText(days, anchored) {
  if (typeof days !== "number") return DASH;
  const before = days < 0;
  const span = Math.abs(days) < 1 ? `${(Math.abs(days) * 24).toFixed(1)} 小時` : `${Math.abs(days).toFixed(1)} 天`;
  const base = anchored ? "代表性時刻" : "出生";
  return `${base}${before ? "前" : "後"} ${span}`;
}

function solarPhaseNotes(response, module, { selected, sun, disc, interval }) {
  const notes = [
    "古典占星看行星離太陽多近：太近時，行星被太陽的光芒蓋住，肉眼看不到。這一區列出月亮與五顆行星在黃道上離太陽幾度，"
    + "以及照所選分法落在哪一個距離帶。（黃道：太陽一年在天上走的路線，星座度數就是沿著它量的。）",
    "原典怎麼說：Lilly 說任何行星的焦傷是「所能有的最大不幸」，太陽正在趕上行星時受害更重；"
    + "al-Bīrūnī 說行星在光束下「像被關住的囚犯」；Ptolemy 說在太陽光線下的行星，不採為破壞者也不採為援助者。"
    + "行星在日輪內（cazimi，阿拉伯文「在太陽之心」），Lilly 說各家都認為它因此得力。出處見下方摺疊。",
    presentClosedVocabulary(module("profile", "string"), SOLAR_PHASE_PROFILE_NOTE_ZH, "分法"),
  ];
  if (module("decision_basis", "string") === "ecliptic_longitude_difference") {
    notes.push(
      "判定用黃道上的經度差，不計行星在黃道上方或下方偏離多少，這是古典文獻的量法（理由見出處）。"
      + "表上另列天空中的實際夾角、黃緯，以及行星中心是否落在太陽圓面內（太陽此刻的視半徑是 "
      + `${dms(sun("semidiameter_degrees", "number"))}），只供對照，不拿來判定；黃經差與實際夾角對金星與月亮可能差到 8° 以上。`
    );
  }
  const venusException = selected("venus_latitude_exception_degrees", "number?");
  if (venusException !== null) {
    notes.push(
      `al-Bīrūnī 另有一條：金星北黃緯超過 ${venusException}° 時，落在日輪內或焦傷的距離也不這樣稱呼，` + "改稱「伴隨太陽」（muqārina）。"
    );
  }
  notes.push(
    "Lilly 說焦傷只發生在與太陽同一星座時；別的作者沒有這一條，他自己的格言第 26 條也說在光束下不論哪個星座，"
    + "所以本站不套用，只在表中註明是否與太陽同星座。",
    "月亮落在日輪內，就是朔（新月）前後，朔的時刻見〈朔望與日月食〉。月亮離地球近，從出生地看（站心）與從地心看可差到約 1°；"
    + `本區用的是${module("moon_center", "string") === "topocentric" ? "站心" : "地心"}月亮，與本次其他各區相同。`,
    "水星離太陽最遠約 28°，金星約 47°，所以水星常落在光束下；這是天象，不是錯誤。",
  );
  if (disc("requested", "boolean")) {
    notes.push(disc("applicable", "boolean")
      ? "你選了「行星中心落在太陽圓面內」的日輪內：天空中的實際夾角不超過太陽此刻的視半徑"
        + `（${dms(sun("semidiameter_degrees", "number"))}）才算日輪內；其他距離帶仍看黃經差。Abū Maʿshar 說 16′ 是因為太陽的直徑約 32′–34′；`
        + "但「看實際夾角、不看黃經」不是他的規則，是本站提供的另一種讀法。"
      : `你選了「行星中心落在太陽圓面內」的日輪內，但這次沒有套用。原因：${moduleReason(disc("reason_code", "string?"))}。`);
  }
  if (interval) {
    notes.push(
      "出生時刻不精確：上方各表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；" + "「出生時間範圍內的距離帶」列出"
      + `${presentClosedVocabulary(interval("interval", "string"), SOLAR_PHASE_INTERVAL_ZH, "區間")}內每一種分法出現過的每一個距離帶。`
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
    const perSide = results.in(profile).in("limits").in(key).in(side);
    return [["cazimi", "日輪內"], ["combust", "焦傷"], ["under_beams", "在光束下"]]
      .map(([name, label]) => [label, perSide(name, "record?"), `${perSide.path}.${name}`]).filter(([, limit]) => limit !== null)
      .map(([label, limit, path]) => `${label} ${solarPhaseLimitText(limit, path)}`).join("；");
  };
  const limitRows = [];
  rows.forEach((row) => {
    const key = row("key");
    const name = row("name", "string");
    const morning = profiles.map((profile) => limitText(profile, key, "morning"));
    const evening = profiles.map((profile) => limitText(profile, key, "evening"));
    if (morning.join("|") === evening.join("|")) { limitRows.push([name, "兩側相同"].concat(morning)); } else {
      limitRows.push([name, SOLAR_PHASE_LIMIT_SIDE_ZH.morning].concat(morning));
      limitRows.push([name, SOLAR_PHASE_LIMIT_SIDE_ZH.evening].concat(evening));
    }
  });
  return {
    title: "三種分法的界線（黃經差）",
    columns: ["天體", "太陽哪一側"].concat(profiles.map((profile) => SOLAR_PHASE_PROFILE_ZH[profile])), rows: limitRows,
  };
}

/** 前後幾天內跨過光束界線的時刻（月亮不搜尋：鍵在、值是 null）。 */
function solarPhaseCrossingTable(rows, module, selected, anchored) {
  const windowDays = module.in("seven_day_search")("window_days", "number");
  const crossings = selected.in("beam_crossings_within_7_days");
  const crossingRows = [];
  rows.forEach((row) => {
    const key = row("key");
    const name = row("name", "string");
    if (key === "moon") {
      if (crossings(key) !== null) { throw exportPipeline.incompleteResponse(`${crossings.path}.moon 月亮不搜尋，應為 null`); }
      return;
    }
    const found = crossings.rows(key);
    if (!found.length) { crossingRows.push([name, "這段時間內沒有跨過", DASH, DASH, DASH]); return; }
    found.forEach((item) => {
      crossingRows.push([
        name, presentClosedVocabulary(item("direction", "string"), SOLAR_PHASE_CROSSING_ZH, "方向"),
        `${item("threshold_degrees", "number")}°`, solarPhaseOffsetText(item("day_offset", "number"), anchored),
        localInstantText(item.in("instant")),
      ]);
    });
  });
  return {
    title: `${anchored ? "代表性時刻" : "出生"}前後 ${num(windowDays, 0)} 天內跨過光束界線的時刻（五顆行星）`,
    columns: ["行星", "方向", "界線", "什麼時候", "當地時間"], rows: crossingRows,
  };
}

// 焦傷與光束下看的天體（後端 solar_phase.py）：月亮與五顆行星，依這個順序。
const SOLAR_PHASE_BODIES = Object.freeze(["moon", "mercury", "venus", "mars", "jupiter", "saturn"]);

function solarPhaseSection(response) {
  const container = response.derived_methods.solar_phase;
  const section = moduleSection(response, {
    id: "solar_phase", title: SOLAR_PHASE_TITLE, ring: RING.METHOD,
    keys: { option: "include_solar_phase", module: "solar_phase" }, container,
    note: "本次未請求。古典占星看行星離太陽多近：日輪內（cazimi）、焦傷（combust）、在光束下；勾選後列出月亮與五顆行星的距離與所屬距離帶。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "solar_phase");
  const rows = module.rows("rows");
  const keys = rows.map((row) => row("key", "string"));
  needExactly(keys, SOLAR_PHASE_BODIES, "solar_phase.rows");
  const profiles = Object.keys(SOLAR_PHASE_PROFILE_ZH);
  const results = module.in("profile_results");
  needExactly(Object.keys(results.record).sort(), [...profiles].sort(), "solar_phase.profile_results");
  // 每一套分法、每一張逐星表都恰好是這六顆。
  const byBody = (record, path) => needExactly(Object.keys(record).sort(), [...SOLAR_PHASE_BODIES].sort(), path);
  profiles.forEach((profile) => ["limits", "bands", "beam_crossings_within_7_days"]
    .forEach((key) => byBody(results.in(profile).in(key).record, `solar_phase.profile_results.${profile}.${key}`)));
  const selected = results.in(module("profile", "string"));
  const bandsOf = (profile) => results.in(profile).in("bands");
  const band = (value) => presentClosedVocabulary(value, SOLAR_PHASE_BAND_ZH, "距離帶");
  const disc = module.in("disc_cazimi");
  const sun = module.in("sun");
  const anchored = module("time_basis", "string") !== "birth_instant";
  // 出生時間不精確（代表性時刻）才有區間；精確時刻時這個鍵在、值是 null。
  const interval = module.in("birth_time_interval", !anchored);
  if (!anchored && interval !== null) { throw exportPipeline.incompleteResponse("solar_phase.birth_time_interval 在精確時刻應為 null"); }
  const notes = solarPhaseNotes(response, module, { selected, sun, disc, interval });
  const tables = [{
    title: anchored ? "代表性時刻各行星離太陽多遠" : "各行星離太陽多遠",
    columns: ["天體", "距離帶", "黃經差（行星減太陽）", "在太陽哪一側", "靠近或離開", "天空中的實際夾角", "黃緯",
      "落在太陽圓面內", "與太陽同星座"],
    rows: rows.map((row) => [
      row("name", "string"), band(row("band", "string")), solarPhaseDifferenceText(row),
      presentClosedVocabulary(row("side", "string"), SOLAR_PHASE_SIDE_ZH, "側"),
      presentClosedVocabulary(row("relative_motion", "string"), SOLAR_PHASE_MOTION_ZH, "移動"),
      dms(row("angular_separation_degrees", "number")), dms(row("ecliptic_latitude_degrees", "number")),
      yesNo(row("within_solar_disc", "boolean")), yesNo(row("same_sign_as_sun", "boolean")),
    ]),
  }];
  tables.push({
    title: "三種分法對照",
    columns: ["天體"].concat(profiles.map((profile) => SOLAR_PHASE_PROFILE_ZH[profile]
      + (results.in(profile)("disc_cazimi_applied", "boolean") ? "，日輪內看太陽圓面" : ""))),
    rows: rows.map((row) => [row("name")].concat(profiles.map((profile) => band(bandsOf(profile)(row("key"), "string"))))),
  });
  tables.push(solarPhaseLimitTable(rows, results, profiles));
  tables.push(solarPhaseCrossingTable(rows, module, selected, anchored));
  // 前後幾天的逐日黃經差：每一顆都恰好是 −窗口 到 +窗口 的每一天（應有的天數取自搜尋窗口）。
  const windowDays = module.in("seven_day_search")("window_days", "number");
  const offsets = Array.from({ length: 2 * windowDays + 1 }, (_value, index) => index - windowDays);
  const daily = rows.map((row) => {
    const series = row.rows("daily_longitude_differences");
    needExactly(series.map((item) => item("day_offset", "number")), offsets, `${row.path}.daily_longitude_differences`);
    return series.map((item) => item("longitude_difference_degrees", "number"));
  });
  tables.push({
    title: `${anchored ? "代表性時刻" : "出生"}前後 7 天，每天的黃經差（正：東側；負：西側）`,
    columns: ["第幾天"].concat(rows.map((row) => row("name"))),
    rows: offsets.map((offset, index) => [
      offset === 0 ? "當天" : `${offset > 0 ? "後" : "前"} ${Math.abs(offset)} 天`,
    ].concat(daily.map((series) => `${series[index] < 0 ? "−" : "+"}${Math.abs(series[index]).toFixed(2)}°`))),
  });
  if (interval) {
    const intervalRows = interval.rows("rows");
    needExactly(intervalRows.map((row) => row("key", "string")), SOLAR_PHASE_BODIES, "solar_phase.birth_time_interval.rows");
    const seenOf = (profile) => {
      const seen = results.in(profile).in("bands_seen_in_birth_time_interval");
      byBody(seen.record, seen.path);
      return seen;
    };
    tables.push({
      title: "出生時間範圍內的距離帶", columns: ["天體", "黃經差最小", "黃經差最大", "所選分法只有一種距離帶"]
        .concat(profiles.map((profile) => SOLAR_PHASE_PROFILE_ZH[profile])),
      rows: intervalRows.map((row) => [
        row("name", "string"), `${num(row("longitude_difference_min_degrees", "number"), 2)}°`,
        `${num(row("longitude_difference_max_degrees", "number"), 2)}°`, yesNo(row("stable", "boolean")),
      ].concat(profiles.map((profile) => {
        const seen = seenOf(profile)(row("key"), "array");
        if (!seen.length) {
          throw exportPipeline.incompleteResponse(`solar_phase.profile_results.${profile}.bands_seen_in_birth_time_interval.${row("key")} 是空的`);
        }
        return seen.map(band).join("、");
      }))),
    });
  }
  return section.make({ notes, tables, blocks: SOLAR_PHASE_SOURCES.slice() });
}

// 後端算好每一格的狀態，這裡只照閉集翻成白話，不重算。
const MOTION_TITLE = "行速、停滯與東出西入";
const MOTION_COURSE_ZH = Object.freeze({
  swift: "行速快（swift）", slow: "行速慢（slow）", equal_to_mean_at_source_precision: "等於平均（到原典印出的那一位）",
});
const MOTION_DIRECTION_ZH = Object.freeze({ direct: "順行", retrograde: "逆行" });
const MOTION_STATION_ZH = Object.freeze({
  stationary_before_retrograde: "停滯（第一次：快要轉為逆行）", stationary_before_direct: "停滯（第二次：快要轉回順行）",
  stationary_after_turning_retrograde: "停滯（第一次：剛轉為逆行）",
  stationary_after_turning_direct: "停滯（第二次：剛轉回順行）", not_stationary: "沒有停滯", not_applicable_luminary: "日月不停滯",
});
const MOTION_TURN_ZH = Object.freeze({
  first_station_to_retrograde: "第一次停滯，轉為逆行", second_station_to_direct: "第二次停滯，轉回順行",
});
const MOTION_SIDE_ZH = Object.freeze({
  oriental: "晨星（東出）", occidental: "昏星（西入）", on_the_sun: "與太陽同一黃經", not_applicable_sun: "太陽本身不分東出西入",
});
const MOTION_P115_ZH = Object.freeze({
  listed_as_accidental_fortitude: "Lilly 列為偶然強", listed_as_accidental_debility: "Lilly 列為偶然弱", not_listed: DASH,
});
// core/motion_states.py MEAN_MOTION_PROFILES，順序即對照表的欄序。
const MOTION_PROFILE_ZH = Object.freeze({ lilly_1647_v1: "Lilly 1647", bonatti_1550_v1: "Bonatti 1550" });
const MOTION_FIXED_SENTENCE = "照原典列出。";
const MOTION_SOURCE_LINES = Object.freeze([
  ["William Lilly, Christian Astrology (London 1647)",
    "出處：Lilly《Christian Astrology》1647 年版：各行星章的平均每日行度與停滯天數（pp.57–58、61–62、65、69、72–73、76、80）；"
    + "p.114 東出西入與停滯的定義；p.115 偶然強弱表；p.168 行速快的定義（一天走的多於平均）；p.178 七顆星的算例。",
    "original_language_read", "（1647 年版頁影像）"], ["Guido Bonatti, De astronomia tractatus X",
    "出處：Bonatti《De astronomia》（1550 年 Basel 版）第三論 cols.129–130：同一組平均每日行度，土星寫到比秒再小一位"
    + "（‴，1″ 的 60 分之 1：2′00″35‴）；剛好等於平均叫 aequalis。",
    "original_language_read", "（1550 年版頁影像）"], ["Ptolemy, Tetrabiblos I.6",
    "出處：Ptolemy《占星四書》I.24（Robbins 1940 英譯 pp.115–117）：東出而且增於行最有力，西入而且減速較弱；"
    + "I.6、I.8 講晨星、昏星與兩次停滯。", "translation_read", "（英譯，LacusCurtius 轉錄）"], ["al-Biruni, Book of Instruction",
    "出處：al-Bīrūnī《占星術入門》（Kitāb al-Tafhīm）§481–486、§498、§512：東出、西入與停滯的名稱；東出時作用最強，西入時弱。",
    "translation_read", "（英譯，線上打字稿，1934 年版的頁碼未核）"], ["Vettius Valens, Anthologies",
    "出處：Valens《選集》（Anthologies）IV.14：過了第一次停滯而逆行，使期待延遲；到第二次停滯，延遲取消。",
    "translation_read", "（Riley 英譯）"],
  [null, "出處：完整書目、兩套平均行度與每一條核到哪一層，見方法頁〈行速、停滯與東出西入〉一節。"],
]);
const MOTION_SOURCES = sourceBlocks(MOTION_SOURCE_LINES);

/** 行速一格：逆行時補一句比的是什麼。 */
function motionCourseText(course, direction) {
  const text = presentClosedVocabulary(course, MOTION_COURSE_ZH, "行速");
  return direction === "retrograde" ? `${text}；比的是每天退的度數` : text;
}

function motionStationText(station, anchored, path) {
  const text = presentClosedVocabulary(need(station, path, "state", "string"), MOTION_STATION_ZH, "停滯");
  const days = need(station, path, "lilly_days", "number?");
  const turn = need(station, path, "turn", "record?");
  if (!turn || days === null) return text;
  const offset = need(turn, `${path}.turn`, "day_offset", "number");
  const after = String(station.state).startsWith("stationary_after_");
  return `${text}；${solarPhaseOffsetText(offset, anchored)}轉向，Lilly 給` + `${after ? "轉向後" : ""} ${days} 天`;
}

function motionNotes(response, module, { interval }) {
  const notes = [
    "古書會看行星這一天走得比平常快還是慢、是不是快要停住轉向、在太陽的哪一邊。這一區照原典列出太陽、月亮與五顆行星的這三件事。",
    "行速快慢：這一天在黃道上走的度數，和 Lilly《Christian Astrology》（1647）給每顆星的「平均每日行度」（mean motion）比，"
    + "多於平均是行速快，少於平均是行速慢（p.168）。例如土星平均每天走 2′01″（1′ 是 1 度的 60 分之 1）。"
    + "逆行中的行星，比的是每天退的度數（Lilly p.178 的例子就是這樣比）。和平均相同到原典印出的那一位（Lilly 到秒）才算等於平均。",
    "停滯（stationary）：行星看起來幾乎停住，快要由順行轉成逆行（第一次停滯），或由逆行轉回順行（第二次停滯）。"
    + "Lilly 寫各行星在轉向前停幾天：土星 5 天與 5 天、木星 5 天與 4 天、火星「兩三天」（本站取 3 天）與 2 天、"
    + "金星 2 天與 2 天、水星「停一天」。從這一刻到轉向的時間不超過這個天數，就列為停滯。"
    + "轉向之後，Lilly 只替火星寫了天數：轉回順行之後「再一天」（p.65），所以火星轉回順行後 1 天內也列為停滯，"
    + "其他行星轉向後不再列；把轉向後的天數也算進去，是本站對各行星章的讀法。精確的轉向時刻另列一表。太陽與月亮不會停滯。",
    "東出西入（oriental／occidental）這裡只用「相對太陽」這一種意思（Lilly p.114）：晨星（東出）比太陽早升起，"
    + "清晨在東方天空看得到，在黃道上它其實位於太陽的西側；昏星（西入）在太陽下山後還留在西方天空，在黃道上位於太陽東側。"
    + "月亮從滿月到新月（漸虧）是東出，從新月到滿月（漸盈）是西入。這和〈焦傷與光束下〉一區的「西側（晨星）／東側（昏星）」是同一件事。",
    "Lilly 的強弱表（p.115）把行速快、土星木星火星東出、金星水星西入、月亮漸盈或西入列為偶然強（accidental fortitude），"
    + "相反的列為偶然弱。表上只寫 Lilly 把它列在哪一邊，不給分數、不加總。",
    "月亮：Lilly p.80 說月亮一天走不到 13°10′ 就算慢，「等同逆行的行星」；但他給的平均是 13°10′36″，兩者差 36″。"
    + "本站照 p.168 的規則用平均 13°10′36″，所以月亮一天走 13°10′00″ 到 13°10′36″ 之間時，本站判慢，照 p.80 的字面則不算慢。",
    "古書的「一天走多少」是相鄰兩個正午的位置相減；本站用這一刻從地心看的速度（天文計算程式直接給的瞬時值）。"
    + "兩者只在接近平均時判得不同：以這一刻為中心、前後各 12 小時的位置相減，月亮約萬分之 2.5 的時刻判法不同；"
    + "改用「之後 24 小時」相減，月亮約 3.6%、水星約 1.4%（1950–2050 年實測）。"
    + "從出生地看（站心）的月亮速度一天內會擺動約 ±5.5°，所以行速一律用地心速度，不隨本次選的中心改變。",
    "原典怎麼說：Ptolemy《占星四書》I.24：東出而且行速增加時力量最大，西入而且減速時較弱。"
    + "al-Bīrūnī《占星術入門》§486：東出時作用最強，西入時弱。Lilly p.80：月亮行速慢時「等同逆行的行星」。"
    + "Valens《選集》IV.14：過了第一次停滯而逆行，使期待延遲；到第二次停滯，延遲取消。這些是各書的說法，照原文列出。",
    "「增於行／減於行」（increasing／decreasing in course）各書的定義互相衝突，本站不輸出；"
    + "東出西入的其他幾種意思（al-Bīrūnī 的分段、天空四象限）也不輸出。理由見方法頁。",
  ];
  if (interval) {
    notes.push(
      "出生時刻不精確：上方各表用的是代表性時刻，也就是計算時拿來代表這段時間的一個時刻，不是出生時刻；"
      + "「出生時間範圍內出現過的狀態」列出"
      + `${presentClosedVocabulary(interval.interval, SOLAR_PHASE_INTERVAL_ZH, "區間")}內每一種出現過的行速、停滯與東出西入。`
      + "月亮一個月有兩次左右走到平均附近，只知日期時行速可能在當天改變。"
    );
  }
  notes.push(...classicalDisagreementNotes(response, "derived_methods.motion_states"));
  notes.push(MOTION_FIXED_SENTENCE);
  return notes;
}

// 會停滯、會搜尋轉向的五顆行星；日月不停滯，轉向清單是 null（後端 STATION_DAYS 只列這五顆）。
const MOTION_STATION_KEYS = Object.freeze(SEVEN_KEYS.filter((key) => key !== "sun" && key !== "moon"));

function motionStatesSection(response) {
  const module = response.derived_methods.motion_states;
  // 可不可以畫只由狀態權威說；說了 present，下面每一格都必須在（不從空容器推定「沒結果」）。
  const section = moduleSection(response, {
    id: "motion_states", title: MOTION_TITLE, ring: RING.METHOD,
    keys: { option: "include_motion_states", module: "motion_states" }, container: module,
    note: "本次未請求。古書看行星這一天走得快或慢、是不是快要停住轉向、在太陽哪一邊；勾選後列出太陽、月亮與五顆行星的行速、停滯與東出西入。",
  });
  if (section.absent) return section.absent;
  const path = "motion_states";
  const m = needAt(module, path);
  const rows = m("rows", "records").map((row, index) => needAt(row, `${path}.rows[${index}]`));
  needExactly(rows.map((r) => r("key", "string")), SEVEN_KEYS, `${path}.rows`);
  const results = m.in("profile_results");
  needExactly(Object.keys(results.record).sort(), Object.keys(MOTION_PROFILE_ZH).sort(), `${path}.profile_results`);
  const anchored = m("time_basis", "string") !== "birth_instant";
  // 出生時間不精確（代表性時刻）才有區間；精確時刻時這個鍵在、值是 null。
  const interval = m("birth_time_interval", anchored ? "record" : "any");
  if (!anchored && interval !== null) { throw exportPipeline.incompleteResponse(`${path}.birth_time_interval 在精確時刻應為 null`); }
  const course = (value) => presentClosedVocabulary(value, MOTION_COURSE_ZH, "行速");
  const side = (value) => presentClosedVocabulary(value, MOTION_SIDE_ZH, "東出西入");
  const station = (value) => presentClosedVocabulary(value, MOTION_STATION_ZH, "停滯");
  const p115 = (value) => presentClosedVocabulary(value, MOTION_P115_ZH, "Lilly 強弱表");
  const tables = [{
    title: anchored ? "代表性時刻的行速、停滯與東出西入" : "行速、停滯與東出西入",
    columns: ["天體", "這一刻每天走", "順行或逆行", "Lilly 的平均每日行度", "行速", "停滯", "東出或西入"],
    rows: rows.map((r) => {
      const direction = r("direction", "string");
      return [
        r("name", "string"), r("daily_motion_text", "string"),
        presentClosedVocabulary(direction, MOTION_DIRECTION_ZH, "方向"), r("mean_motion_text", "string"),
        motionCourseText(r("course", "string"), direction),
        motionStationText(r("station", "record"), anchored, `${r.path}.station`), side(r("relative_to_sun", "string")),
      ];
    }),
  }];
  tables.push({
    title: "Lilly 的強弱表（p.115）把它列在哪一邊", columns: ["天體", "行速", "東出或西入"],
    rows: rows.map((r) => {
      const listed = r.in("lilly_p115");
      const sideText = p115(listed("relative_to_sun", "string"));
      return [
        r.record.name, p115(listed("course", "string")),
        r.record.key === "moon" && r.record.relative_to_sun === "oriental" && sideText !== DASH
          ? `${sideText}（他寫的是「漸虧」）` : sideText,
      ];
    }),
  });
  const profiles = Object.keys(MOTION_PROFILE_ZH);
  tables.push({
    title: "兩本書的平均每日行度對照",
    columns: ["天體"].concat(...profiles.map((profile) => [`${MOTION_PROFILE_ZH[profile]} 的平均`, `照 ${MOTION_PROFILE_ZH[profile]}`])),
    rows: rows.map((r) => [r.record.name].concat(...profiles.map((profile) => {
      const result = results.in(profile);
      const mean = result.in("means").in(r.record.key);
      const courses = result.in("courses");
      return [mean("text", "string"), course(courses(r.record.key, "string"))];
    }))),
  });
  const listed = m.in("stations_within_window");
  const search = m.in("station_search");
  const stationRows = [];
  rows.forEach(({ record: row }) => {
    if (!MOTION_STATION_KEYS.includes(row.key)) {
      // 日月不搜尋：鍵在、值是 null。
      if (listed(row.key) !== null) {
        throw exportPipeline.incompleteResponse(`${listed.path}.${row.key} 日月不搜尋轉向，應為 null`);
      }
      return;
    }
    const found = listed(row.key, "records");
    if (!found.length) { stationRows.push([row.name, "這段時間內沒有轉向", DASH, DASH]); return; }
    found.forEach((value, index) => {
      const item = needAt(value, `${listed.path}.${row.key}[${index}]`);
      const instant = item.in("instant");
      stationRows.push([
        row.name, presentClosedVocabulary(item("kind", "string"), MOTION_TURN_ZH, "轉向"),
        solarPhaseOffsetText(item("day_offset", "number"), anchored),
        `${instant("local_time", "string")} ${instant("utc_offset", "string")}`,
      ]);
    });
  });
  tables.push({
    title: `${anchored ? "代表性時刻" : "出生"}前後 ${num(search("window_days", "number"), 0)} 天內的轉向時刻（五顆行星）`,
    columns: ["行星", "哪一次", "什麼時候", "當地時間"], rows: stationRows,
  });
  if (interval) {
    const at = needAt(interval, `${path}.birth_time_interval`);
    at("interval", "string");
    const intervalRows = at("rows", "records").map((row, index) => needAt(row, `${at.path}.rows[${index}]`));
    // 區間表的列與上方主表同一組、同一順序（頁面版的列只帶名稱）。
    needExactly(intervalRows.map((r) => r("name", "string")), rows.map((r) => r.record.name), `${at.path}.rows`);
    // 每一欄至少出現過一種狀態：空清單不是「沒有」，是殘缺。
    const list = (r, key, label) => {
      const values = r(key, "array");
      if (!values.length) throw exportPipeline.incompleteResponse(`${r.path}.${key} 是空的`);
      return values.map(label).join("、");
    };
    tables.push({
      title: "出生時間範圍內出現過的狀態", columns: ["天體", "行速", "停滯", "東出或西入", "三項都只有一種"],
      rows: intervalRows.map((r) => [
        r.record.name, list(r, "courses_seen", course), list(r, "station_states_seen", station),
        list(r, "relative_to_sun_seen", side), yesNo(r("stable", "boolean")),
      ]),
    });
  }
  return section.make({ notes: motionNotes(response, module, { interval }), tables, blocks: MOTION_SOURCES.slice() });
}

/**
 * 一欄當地時間：各格的時差都相同時，時差只寫在欄標頭，格裡只留時刻；不同時（例如跨過夏令時間）每格照舊帶時差。
 * heading 收到的標題若以未閉合的「（」結尾（「開始（當地時間」），時差補在括號裡再閉合。
 */
function sharedOffsetColumn(records) {
  const offsets = new Set(records.map((record) => record("utc_offset", "string")));
  const shared = offsets.size === 1 ? [...offsets][0] : null;
  return {
    heading: (title) => {
      const open = title.endsWith("當地時間") && title.includes("（");
      if (!shared) return open ? `${title}）` : title;
      return open ? `${title}，${shared}）` : `${title}（${shared}）`;
    },
    cell: (record) => (shared ? record("local_time", "string") : localInstantText(record)),
  };
}

function localInstantText(record, timeKey = "local_time", offsetKey = "utc_offset") {
  return `${record(timeKey, "string")} ${record(offsetKey, "string")}`;
}

function differingClassificationPaths(sensitivity) {
  const coverage = isRecord(sensitivity.classification_coverage) ? sensitivity.classification_coverage : {};
  return Object.values(coverage).filter(isRecord)
    .flatMap((item) => (Array.isArray(item.differing_classifications) ? item.differing_classifications : []));
}
