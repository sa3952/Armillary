// view-model：產前朔望、阿拉伯點、月空亡、赤緯相位與尊貴的各套分配法。
// 產前朔望與出生前日月食的度數。
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

/** 一個發光體在地平線上下（reading 是 needAt）。 */
function altitudeText(reading) {
  const altitude = reading("altitude_true_degrees", "number");
  const sign = altitude < 0 ? "-" : "+";
  const where = reading("in_near_horizon_band", "boolean") ? "貼近地平線"
    : reading("above_horizon", "boolean") ? "在上方" : "在下方";
  return `${where}（高度 ${sign}${num(Math.abs(altitude), 1)}°）`;
}

/** 一次朔望取用的度數（event 是 needAt）：選出的那一個，或狀態說明加兩個度數。 */
function prenatalDegreeText(event) {
  const selection = event.in("degree_selection");
  const state = selection("state", "string");
  if (state === "conjunction_degree" || state === "selected") {
    const who = presentClosedVocabulary(selection("selected_luminary", "string"), PRENATAL_LUMINARY_ZH, "發光體");
    return `${signPosition(selection.position("selected_sign_position"))}（${who}${state === "selected" ? "，在地平線上方" : ""}）`;
  }
  return presentClosedVocabulary(state, PRENATAL_DEGREE_STATE_ZH, "取度數的狀態");
}

function prenatalSyzygyRow(label, event, hours) {
  return [
    label,
    localInstantText(event),
    beforeBirthText(hours),
    signPosition(event.position("sun_sign_position")),
    signPosition(event.position("moon_sign_position")),
    prenatalDegreeText(event),
  ];
}

/** 恆星黃道盤：同一批點換到盤自己的黃道；回歸黃道盤時 chart_zodiac 是 null。 */
function prenatalSiderealCell(event, key) {
  const zodiac = event.in("chart_zodiac", true);
  return zodiac ? signPosition(zodiac.in("sign_positions").position(key)) : null;
}

function prenatalSyzygyParts(module) {
  const syzygy = module.in("prenatal_syzygy");
  const atBirth = module.in("prenatal_syzygy_at_birth");
  const profile = atBirth.in("sect_profile");
  const other = profile.in("other_previous_syzygy");
  const otherState = other("state", "string");
  const otherEvent = otherState === "computed" ? other.in("event") : null;
  const phaseName = (phase) => presentClosedVocabulary(phase, LUNAR_PHASE_ZH, "事件");
  const hoursBefore = atBirth("hours_before_birth", "number");
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
  const rows = [prenatalSyzygyRow(`產前朔望：${phaseName(syzygy("phase", "string"))}（較近的一次）`, syzygy, hoursBefore)];
  const otherPhase = phaseName(other("phase", "string"));
  if (otherEvent) {
    rows.push(prenatalSyzygyRow(`前一次${otherPhase}`, otherEvent, other("hours_before_birth", "number")));
  } else if (otherState === "outside_ephemeris_coverage") {
    rows.push([`前一次${otherPhase}`, "超出本站星曆涵蓋的年代，沒有計算", DASH, DASH, DASH, DASH]);
  }
  const events = [syzygy].concat(otherEvent ? [otherEvent] : []);
  const sidereal = events.some((event) => prenatalSiderealCell(event, "sun"));
  const columns = ["朔望", "出生地時間", "距出生", "太陽", "月亮", "取用的度數（卷三第 2 章）"];
  const tables = [{ title: "出生前的朔與望（回歸黃道）", columns, rows }];
  if (sidereal) {
    tables.push({
      title: "同一批點在這張盤的恆星黃道",
      columns: ["朔望", "太陽", "月亮"],
      rows: events.map((event, index) => [
        rows[index][0], prenatalSiderealCell(event, "sun"), prenatalSiderealCell(event, "moon"),
      ]),
    });
  }
  // 望的那一刻才讀地平高度；朔與沒有地平的盤是 null。
  const fullMoons = events.map((event, index) => [event.in("degree_selection").in("horizon_at_syzygy", true), rows[index][0]])
    .filter(([horizon]) => horizon);
  if (fullMoons.length) {
    const agrees = (horizon) => horizon.in("ecliptic_hemisphere_check")("agrees_with_altitude", "boolean");
    tables.push({
      title: "望的那一刻，從出生地看太陽和月亮的高度",
      columns: ["朔望", "太陽", "月亮", "用黃道半球交叉檢查"],
      rows: fullMoons.map(([horizon, label]) => [
        label,
        altitudeText(horizon.in("sun")),
        altitudeText(horizon.in("moon")),
        agrees(horizon) ? "一致" : "不一致（以高度為準）",
      ]),
    });
    if (fullMoons.some(([horizon]) => !agrees(horizon))) {
      notes.push("交叉檢查：用黃道半球判斷（看度數落在下降點經天頂到上升點的那一半），結果和用高度判斷不同。"
        + "黃道貼近地平線、或月亮偏離黃道較多時會這樣；我們以高度判斷為準。");
    }
  }
  const profileState = profile("state", "string");
  if (profileState === "selected") {
    const sect = profile("selected_phase", "string") === "new_moon" ? "日生盤" : "夜生盤";
    const pickedLabel = profile("selected", "string") === "prenatal_syzygy" ? rows[0][0] : (rows[1] || [DASH])[0];
    notes.push(`另一種挑法（不是預設）：《占星四書》卷三第 10 章與 Lilly 用日生盤看前一次朔、夜生盤看前一次望。`
      + `這張盤是${sect}，這個挑法取「${pickedLabel}」。`);
  } else {
    notes.push("另一種挑法（不是預設）：《占星四書》卷三第 10 章與 Lilly 用日生盤看前一次朔、夜生盤看前一次望。"
      + presentClosedVocabulary(profileState, PRENATAL_SECT_STATE_ZH, "挑法狀態"));
  }
  const atBirthLuminaries = atBirth.in("luminaries_above_horizon_at_birth");
  if (atBirthLuminaries("state", "string") === "computed") {
    const where = (key) => (atBirthLuminaries.in(key)("above_horizon", "boolean") ? "上方" : "下方");
    notes.push("手抄本的另一種讀法（Robbins 英譯本註 9）看出生那一刻誰在地平線上方，只當資訊："
      + `出生時太陽在地平線${where("sun")}，月亮在地平線${where("moon")}。`);
  }
  if (atBirth("near_birth", "boolean")) {
    notes.push(`這次朔望在出生前不到 1 小時（${beforeBirthText(hoursBefore).replace("出生前 ", "")}）。`
      + "出生時刻若其實早了幾分鐘，產前朔望就會是再前一次的朔望。");
  }
  if (atBirth("reference", "string") === "representative_anchor_not_birth_instant") {
    notes.push("出生時間不精確：「距出生」、日生或夜生的挑法和出生時的地平高度，用的是計算用的代表性時刻，不是出生時刻。");
  }
  const samples = representativeSamples(module);
  if (samples) {
    const seen = new Map();
    samples.forEach((entry) => {
      const view = lunarSampleView(entry, module).prenatal_syzygy;
      if (view === undefined) return;
      const sample = needAt(view, `${entry.top ? module.path : entry.sample.path}.prenatal_syzygy`);
      seen.set(sample("utc_time", "string"), sample("phase", "string"));
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
  const eclipses = module.in("eclipses");
  const atBirth = module.in("eclipses_at_birth");
  const days = atBirth.in("days_before_birth");
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
  const eclipseCells = (entry) => [
    presentClosedVocabulary(entry("type", "string"), ECLIPSE_TYPE_ZH, "日月食類型"),
    localInstantText(entry, "maximum_local_time", "maximum_utc_offset"),
  ];
  const pointCells = (entry) => [
    presentClosedVocabulary(entry("eclipsed_luminary", "string"), PRENATAL_LUMINARY_ZH, "發光體"),
    signPosition(entry.position("eclipse_sign_position")),
  ];
  const row = (label, key) => {
    const entry = eclipses.in(key);
    return [label, ...eclipseCells(entry), beforeBirthText(days(key, "number") * 24), ...pointCells(entry)];
  };
  const umbral = eclipses.in("previous_umbral_lunar");
  const rows = [
    row("前一次日食", "previous_solar"),
    row("前一次月食（含半影月食）", "previous_lunar"),
    row(`前一次本影月食（偏食或全食；${presentClosedVocabulary(
      umbral("relation_to_previous_lunar", "string"), PRENATAL_UMBRAL_ZH, "比較")}）`, "previous_umbral_lunar"),
  ];
  // 出生時正在進行的日月食：沒有就是 null，有就說是哪一種關係。
  const inProgress = atBirth.in("in_progress");
  [["solar", "日食"], ["lunar", "月食"]].forEach(([kind, word]) => {
    const entry = inProgress.in(kind, true);
    if (!entry) return;
    const minutes = Math.round(Math.abs(entry("maximum_minus_birth_minutes", "number")));
    const relation = entry("relation", "string");
    if (relation === "maximum_after_birth") {
      notes.push(`你出生的時候，天上正在發生一次${word}；它最深的那一刻（食甚）在你出生之後 ${minutes} 分鐘，`
        + "所以沒有算成「出生前最近一次」，另列在表的最後一列。");
      const record = entry.in("eclipse");
      rows.push([`出生時正在進行的${word}`, ...eclipseCells(record), `出生後 ${minutes} 分鐘`, ...pointCells(record)]);
    } else if (relation === "maximum_at_or_before_birth") {
      notes.push(`你出生的時候，前一次${word}還沒結束：它的食甚在出生前 ${minutes} 分鐘。`);
    }
  });
  if (atBirth("reference", "string") === "representative_anchor_not_birth_instant") {
    notes.push("出生時間不精確：「距出生」和「出生時正在進行」用的是計算用的代表性時刻，不是出生時刻。");
  }
  return {
    notes,
    tables: [{
      title: "出生前最近一次日食與月食",
      columns: ["日月食", "類型", "出生地時間（食甚）", "距出生", "受食的發光體", "日月食的度數"],
      rows,
    }],
  };
}

function prenatalPointsSection(response) {
  const container = response.astronomical_data.lunar_events;
  const syzygyState = moduleState(response, { module: "prenatal_syzygy" }, null, true);
  const eclipsesState = moduleState(response, { option: "include_eclipses", module: "eclipses" }, null, true);
  if (syzygyState.state !== "present" && eclipsesState.state !== "present") {
    return absentSectionFor("prenatal_points", PRENATAL_TITLE, RING.METHOD,
      "本次未請求。勾選「朔望」會列出產前朔望（出生前最近一次朔或望）的度數，勾選「日月食」會列出出生前最近一次日食與月食的度數。",
      syzygyState.state !== "not_requested" ? syzygyState : eclipsesState);
  }
  const module = needAt(container, "lunar_events");
  const notes = [];
  const tables = [];
  if (syzygyState.state === "present") {
    const parts = prenatalSyzygyParts(module);
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

// 阿拉伯點、月空亡與赤緯相位。
function lotsSection(response) {
  const container = response.derived_methods.lots;
  const status = moduleState(response, { option: "include_lots", module: "lots" }, container, true);
  if (status.state !== "present") {
    return absentSectionFor("lots", "阿拉伯點", RING.METHOD, "本次未請求阿拉伯點。", status);
  }
  const module = needAt(container, "lots");
  // 公式基礎讀後端 lots.formula_basis（lots.py LOT_FORMULA_BASES），不是 is_day：
  // is_day 說的是日夜盤，不是公式是否反轉。
  const basis = module("formula_basis", "string");
  const boundary = basis === "both_formulas_boundary";
  const notes = [`公式基礎：${presentClosedVocabulary(basis, LOT_FORMULA_BASIS_ZH, "公式基礎")}。`];
  const applied = module("sect_applied", "string");
  if (boundary) {
    notes.push(
      "太陽在近地平敏感帶內，日盤公式與夜盤公式的結果兩套並列："
      + `主要值依${presentClosedVocabulary(applied, SECT_APPLIED_ZH, "日夜盤公式")}`
      + "（太陽真高度 > 0° 的規則），另一套是比較值；落宮與相位只用主要值。我們核過的古典與中世紀作者沒有「日夜盤不定就並列兩套」的程序；兩套並列是現代的不確定性處理方式。"
    );
    if (module("sect_named_boundary_disagreement", "boolean")) notes.push(NAMED_BOUNDARY_DISAGREEMENT_NOTE);
  }
  notes.push("命運點、精神點之外，另列 Paulus 第 23 章的五個點與 Valens 卷四第 25 章的兩個點；Valens 的兩點加注（Valens），與 Paulus 同名的點分開。只列位置與宮位，不解讀。");
  // 七個延伸點由後端與命運點、精神點同一套日夜盤公式算出，宮位用使用者選的宮位制。
  // 後端每次都算全部七個、順序固定；少一列、多一列或換了順序都是殘缺的回應，不靜靜少印。
  const extendedRows = module.in("extended_lots").rows("lots");
  const extendedIds = extendedRows.map((row) => row("lot_method_id", "string")).join(",");
  if (extendedIds !== Object.keys(Labels.VOCABULARIES.extended_lot).join(",")) {
    throw exportPipeline.incompleteResponse(`${module.path}.extended_lots.lots 不是七個延伸點：${extendedIds}`);
  }
  const extendedName = (row) => Labels.closedLabel(row("lot_method_id", "string"), Labels.VOCABULARIES.extended_lot, "阿拉伯點");
  const houseDivision = response.derived_methods.house_division;
  const houseColumn = houseDivision && typeof houseDivision.system_code === "string"
    ? `宮位（${houseSystemText(houseDivision.system_code, houseDivision.system_name)}）` : "宮位";
  notes.push(...classicalDisagreementNotes(response, "derived_methods.lots"));
  // 宮位由後端以行星同一條半開區間規則算出（lots.py _lot_house）；未算宮位時為 null。
  const houseCell = (value) => (value === null ? DASH : `第 ${value} 宮`);
  const LOTS = [["fortune", "命運點 Fortune"], ["spirit", "精神點 Spirit"]];
  if (boundary) {
    // 兩個點 × 若為日盤／若為夜盤，兩列：日夜兩套只有兩個不同度數
    // （日盤命運點＝夜盤精神點），排成四列看起來像四個答案。
    const bySect = module.in("by_sect");
    const header = (key, label) => `${label}（${key === applied ? "本盤採用" : "比較值"}）`;
    const cell = (key, lot) => {
      const entry = bySect.in(key);
      const position = entry.in("sign_positions").position(lot);
      const house = houseCell(entry(`${lot}_house`, "number?"));
      return `${signPosition(position)}，黃經 ${longitudeText(position)}°`
        + (house === DASH ? "" : `，${house}`);
    };
    return makeSection("lots", "阿拉伯點", RING.METHOD, status, {
      notes,
      tables: [{
        title: "點位",
        columns: ["點", header("day", "若為日盤"), header("night", "若為夜盤")],
        rows: [
          ...LOTS.map(([lot, label]) => [label, cell("day", lot), cell("night", lot)]),
          // 延伸點在頁面上只帶本盤採用的一套；比較值在詳細輸出的 by_sect。
          ...extendedRows.map((row) => {
            const position = row.position("sign_position");
            const house = houseCell(row("house", "number?"));
            const text = `${signPosition(position)}，黃經 ${longitudeText(position)}°`
              + (house === DASH ? "" : `，${house}`);
            return applied === "day" ? [extendedName(row), text, DASH] : [extendedName(row), DASH, text];
          }),
        ],
      }],
    });
  }
  // 算出了阿拉伯點就有命運點的黃經（頁面投影保留它）；表上印的是同一點的星座位置。
  module("fortune", "number");
  const positions = module.in("sign_positions");
  const placement = module.in("house_placement", true);
  const rows = [
    ...LOTS.map(([lot, label]) => [
      label, ...positionCells(positions.position(lot)), houseCell(placement ? placement(lot, "number?") : null),
    ]),
    ...extendedRows.map((row) => [
      extendedName(row), ...positionCells(row.position("sign_position")), houseCell(row("house", "number?")),
    ]),
  ];
  return makeSection("lots", "阿拉伯點", RING.METHOD, status, {
    notes,
    tables: [{ title: "點位", columns: ["點", LONGITUDE_COLUMN, "星座度數", houseColumn], rows }],
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

// 非預設定義的判語（報告 M2）：預設定義的判語寫「離開本星座之前……精確完成」，
// 對 30° 與 Lilly 兩個定義都不對。依 search_horizon.kind 換整套。
const VOC_VERDICT_BY_KIND_ZH = Object.freeze({
  moon_motion_30_degrees: Object.freeze({
    not_void: "月亮從盤上位置再走 30° 之內（或在盤上時刻當下）有相位精確完成，故非空亡。",
    simultaneous_boundary: "simultaneous_boundary：某個相位精確完成的時刻與月亮走滿 30° 的時刻，"
      + "相差不超過求根容差 1e-06 日（約 0.086 秒），數值上分不出先後。此情形既不判為"
      + "空亡、也不判為非空亡：is_void_of_course 為 null，verdict 為 "
      + "simultaneous_boundary；該相位與兩個根的括號區間一併列出，供複算。",
    void: "月亮從盤上位置再走 30° 之內沒有任何相位精確完成，故為空亡。",
    not_evaluated: "月亮走滿 30° 的時刻未能求得，本次未作空亡判定。",
  }),
  sign_exit_moiety_entry: Object.freeze({
    not_void: "月亮離開本星座之前（或在盤上時刻當下）進入某個入相位的容許度，故非空亡。",
    simultaneous_boundary: "simultaneous_boundary：月亮進入某個入相位容許度的時刻與月亮離開本星座的時刻，"
      + "相差不超過求根容差 1e-06 日（約 0.086 秒），數值上分不出先後。此情形既不判為"
      + "空亡、也不判為非空亡：is_void_of_course 為 null，verdict 為 "
      + "simultaneous_boundary；該相位與兩個根的括號區間一併列出，供複算。",
    void: "月亮離開本星座之前沒有進入任何入相位的容許度，故為空亡。",
    not_evaluated: "換座時刻未能求得，本次未作空亡判定。",
  }),
});

// 非預設定義時加一句說明判定依據；預設定義不加，頁面照舊。
// 依 search_horizon.kind 判別（預設定義沒有這個欄位）。
const VOC_METHOD_NOTE_ZH = Object.freeze({
  moon_motion_30_degrees: "本次採「未來 30°」定義（Porphyry 名下《占星四書導論》第 23 章）：看月亮從盤上位置再走 30° 之內有沒有相位精確完成，不管換不換座；下表的「離開本星座」一列只供參考，「邊界判定」的邊界指這 30° 的終點。",
  sign_exit_moiety_entry: "本次採 Lilly 1647 定義：月亮離開本星座前，只要進入某個入相位的容許度（兩星容許度一半相加，p.107）就不算空亡；下表的「下一個完成的相位」指進入容許度的時刻。",
});

function voidOfCourseSection(response) {
  const container = response.derived_methods.void_of_course;
  const section = moduleSection(response, {
    id: "void_of_course", title: "月空亡", ring: RING.METHOD,
    keys: { option: "include_void_of_course", module: "void_of_course" }, container,
    note: "本次未請求月空亡。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "void_of_course");
  // 判定是在哪一刻做的：出生時刻，或出生時間不精確時的代表性時刻。後者不是出生時刻的答案，
  // 「否」旁邊要說清楚，不讓它讀成出生那一刻月亮不空亡。
  // 精度是出生時間敏感度說的；後端寫在模組上的 time_basis（頁面投影目前沒有帶）若在，必須與它一致。
  const anchored = response.birth_time_sensitivity.precision !== "exact";
  const basis = Object.hasOwn(module.record, "time_basis") ? module("time_basis", "string") : null;
  if (basis !== null && (basis !== "birth_instant") !== anchored) {
    throw exportPipeline.incompleteResponse("void_of_course.time_basis 與出生時間的精度對不上");
  }
  const verdict = module("verdict", "string");
  const horizonKind = Object.hasOwn(module.record, "search_horizon")
    ? module.in("search_horizon")("kind", "string") : null;
  const isVoid = module("is_void_of_course", "boolean?");
  // all_candidates 依完成時刻排序，第一個就是下一個完成的相位；換座時刻未能求得時沒有候選。
  const candidates = module.rows("all_candidates");
  const next = candidates.length ? candidates[0] : null;
  const answer = isVoid === true ? "是" : isVoid === false ? "否" : DASH;
  return section.make({
    // 這段限制由回應自帶的求解器欄位導出，不打字。打字的限制在後端改掉之後
    // 仍會留在畫面上，而它旁邊就印著證明它已經過時的那個欄位。
    notes: [
      ...(anchored ? [VOC_ANCHOR_NOTE] : []),
      ...(horizonKind === null ? [] : [presentClosedVocabulary(horizonKind, VOC_METHOD_NOTE_ZH, "月空亡定義")]),
      solverLimitation(module("solver", "string?")),
      ...classicalDisagreementNotes(response, "derived_methods.void_of_course"),
    ],
    tables: [{
      title: anchored ? "代表性時刻的判定" : "判定",
      columns: ["項目", "數值"],
      rows: [
        ["是否空亡", anchored && answer !== DASH ? `${answer}（代表性時刻，不是出生時刻）` : answer],
        // 同時刻（simultaneous_boundary）時「是否空亡」為空白，理由就在這一列。
        ["邊界判定", presentClosedVocabulary(verdict,
          horizonKind === null ? VOC_VERDICT_ZH
            : presentClosedVocabulary(horizonKind, VOC_VERDICT_BY_KIND_ZH, "月空亡定義"), "邊界判定")],
        ["離開本星座尚需（小時）", num(module("time_to_sign_exit_hours", "number?"), 4)],
        ["下一個完成的相位", next ? next("body", "string") : DASH],
        ["該相位角度", next ? num(next("aspect_angle", "number"), 2) : DASH],
        ["尚需（日）", next ? num(next("time_days", "number"), 6) : DASH],
      ],
    }],
  });
}
const VOC_ANCHOR_NOTE = "出生時間不精確：下表是在代表性時刻（計算時拿來代表這段時間的一個時刻）判定的，"
  + "不是出生時刻的答案；月亮在這段時間內可能進入或離開空亡。";

function declinationAspectsSection(response) {
  const container = response.derived_methods.declination_aspects;
  const section = moduleSection(response, {
    id: "declination_aspects", title: "赤緯平行與反平行", ring: RING.GEOMETRY,
    keys: { option: "include_declination_aspects", module: "declination_aspects" }, container,
    note: "本次未請求。這是 17 世紀 Placidus 的界定，非古典傳統。",
  });
  if (section.absent) return section.absent;
  const module = needAt(container, "declination_aspects");
  const orb = module.in("orb_receipt")("effective_orb_degrees", "number");
  return section.make({
    notes: [
      `這是 17 世紀 Placidus 的界定，非古典傳統；本次使用 ${num(orb, 3)}° 容許度。`,
    ],
    tables: [{
      title: "赤緯相位",
      columns: ["類型", "天體 A", "赤緯 A（度）", "天體 B", "赤緯 B（度）", "差值（度）"],
      rows: module.rows("aspects").map((pair) => [
        // 未知類型不得落成「平行」：那是把不認得的值說成一個已知值。
        presentClosedVocabulary(pair("type", "string"), DECLINATION_ASPECT_ZH, "赤緯相位類型"),
        pair("body_a", "string"), dms(pair("declination_a", "number")),
        pair("body_b", "string"), dms(pair("declination_b", "number")),
        num(pair("diff", "number"), 4),
      ]),
    }],
  });
}

// 尊貴的各套分配法。
// 陷與弱照原書的分類列出、附出處，不加淡化的說明。
const DEBILITY_NOTES = Object.freeze([
  "陷（Detriment）：行星落在自己的廟正對面的星座。弱（Fall）：落在自己的旺正對面的星座。"
    + "這是 Lilly《Christian Astrology》（1647）p.104 表上的分類，照原文列出；Detriment、Fall 就是那張表的兩欄欄名。"
    + "Lilly 在 p.105 說，土星在牡羊正對它的旺（天秤），「and so is Infortunate」（因而不吉）；"
    + "al-Bīrūnī《占星術入門》§443 說，行星在弱時受到拘束、處境變壞（依 Wright 英譯）。",
  "陷的出處是 al-Bīrūnī《占星術入門》§442 與 Lilly p.104–105；Ptolemy《占星四書》I.19 有弱"
    + "（他稱 depression，降），但沒有陷這一項。弱和旺一樣只判整個星座，不判度數。",
  "本站只判七顆古典行星；Lilly 的表另列月亮南交點在雙子為弱、北交點在射手為弱，這裡不列出。",
]);
const TECHNIQUE_LABELS = Object.freeze({
  domicile_exaltation: "廟、旺、陷、弱 Domicile / Exaltation / Detriment / Fall",
  bounds: "界 Bounds",
  face_decan: "面／旬 Face / Decan",
  triplicity: "三分性 Triplicity",
});

// 每一套尊貴技法自成一個區塊：技法是使用者心裡的單位，混在同一個 section 分不出段落。
function rulerList(list) {
  return Array.isArray(list) && list.length ? list.map(rulerName).join("、") : DASH;
}
// 星座內度數由後端寫好（捨入不跨到下一度，所以不會跨出界段或旬的終點）。
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

// 每一套表的逐星列一定帶的欄位（essential_dignities.py 的 _*_profile；頁面版的列只帶名稱，沒有 key）。
const DIGNITY_ROW_FIELDS = Object.freeze({
  domicile_exaltation: Object.freeze({
    name: "string", sign: "string", degree_in_sign_text: "string",
    domicile_signs: "array", exaltation_sign: "string", detriment_signs: "array", fall_sign: "string",
    domicile_matched: "boolean", exaltation_matched: "boolean", detriment_matched: "boolean", fall_matched: "boolean",
  }),
  triplicity: Object.freeze({
    name: "string", sign: "string", degree_in_sign_text: "string", element: "string",
    day_rulers: "array", night_rulers: "array", selected_rulers: "array?",
  }),
  bounds: Object.freeze({
    name: "string", sign: "string", degree_in_sign_text: "string",
    ruler: "string?", segment_start_degrees: "number?", segment_end_degrees: "number?",
  }),
  face_decan: Object.freeze({
    name: "string", sign: "string", degree_in_sign_text: "string", ruler: "string",
  }),
});
// 只有某幾套表才發的欄位：一套表裡有一列帶，七列就都要帶（Ptolemy 三分性的主守護與共主、
// Chaldaean 界的日夜候選、面／旬的旬序與讀法）。
const DIGNITY_PROFILE_FIELDS = Object.freeze({
  principal_ruler: "string?", assigned_rulers: "array", secondary_ruler: "string?",
  day_candidate: "record", night_candidate: "record", decan_number: "number", ruler_reading: "string",
});
const DIGNITY_CANDIDATE_FIELDS = Object.freeze({
  ruler: "string", segment_start_degrees: "number", segment_end_degrees: "number",
});

/** 一套表的逐星列：恰好是七政、依序，每一列帶齊這個技法的欄位；缺一項就拒絕整份回應。 */
function dignityObjects(technique, profile, path) {
  const objects = need(profile, path, "objects", "records");
  needExactly(objects.map((object, index) => need(object, `${path}.objects[${index}]`, "name", "string")),
    SEVEN_NAMES, `${path}.objects`);
  objects.forEach((object, index) => {
    const at = `${path}.objects[${index}]`;
    Object.entries(DIGNITY_ROW_FIELDS[technique]).forEach(([key, kind]) => need(object, at, key, kind));
    Object.entries(DIGNITY_PROFILE_FIELDS).forEach(([key, kind]) => {
      if (!objects.some((other) => hasKey(other, key))) return;
      const value = need(object, at, key, kind);
      if (key.endsWith("_candidate")) {
        Object.entries(DIGNITY_CANDIDATE_FIELDS).forEach(([field, type]) => need(value, `${at}.${key}`, field, type));
      }
    });
  });
  return objects;
}

/** 一套表本身：profile_id、technique 與出處都在，逐列帶齊。 */
function dignityProfile(results, profileId, technique) {
  const path = `essential_dignities.profile_results.${profileId}`;
  const profile = need(results, "essential_dignities.profile_results", profileId, "record");
  if (need(profile, path, "profile_id", "string") !== profileId
    || need(profile, path, "technique", "string") !== technique) {
    throw exportPipeline.incompleteResponse(`${path} 的 profile_id 或 technique 與鍵不符`);
  }
  need(profile, path, "source", "string");
  if (technique === "face_decan") need(profile, path, "ruler_type", "string");
  dignityObjects(technique, profile, path);
  return profile;
}

/** 日夜盤收據（classify_sect）：尊貴各表與外來都讀它。 */
function dignitySect(dignities) {
  const path = "essential_dignities.sect";
  const sect = need(dignities, "essential_dignities", "sect", "record");
  need(sect, path, "selected_ruler_available", "boolean");
  need(sect, path, "in_near_horizon_band", "boolean?");
  need(sect, path, "is_day", "boolean?");
  need(sect, path, "near_horizon_band_half_width_degrees", "number");
  need(sect, path, "sect_dependent_components", "array");
  return sect;
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
  // profile 已經過 dignityProfile()：七列都在、每列帶齊這個技法的欄位（缺鍵不讀成「不在陷」）。
  const objects = profile.objects;
  const name = (object) => object.name;
  if (technique === "domicile_exaltation") {
    return {
      title,
      columns: ["天體", "星座", DEGREE_IN_SIGN_COLUMN, "廟", "旺", "陷", "弱", "判定"],
      rows: objects.map((object) => [
        name(object), signName(object.sign), degreeInSignText(object),
        (object.domicile_signs || []).map(signName).join("、") || DASH,
        signName(object.exaltation_sign),
        (object.detriment_signs || []).map(signName).join("、") || DASH,
        signName(object.fall_sign),
        // 四者各自成立：水星在處女座同時入廟、入旺，在雙魚座同時在陷、在弱。
        // 用「在陷」「在弱」，不用「落陷」（中國常見譯法裡指 fall）。
        [
          object.domicile_matched === true ? "入廟" : null,
          object.exaltation_matched === true ? "入旺" : null,
          object.detriment_matched === true ? "在陷" : null,
          object.fall_matched === true ? "在弱" : null,
        ].filter(Boolean).join("、") || "不在廟、旺、陷、弱",
      ]),
    };
  }
  if (technique === "triplicity") {
    const withPrincipal = objects.some((object) => hasKey(object, "principal_ruler"));
    // Ptolemy 共治的指派主星與次要共主（essential_dignities.py）照實綁定；次要共主不計分。
    const withCoRulers = objects.some(
      (object) => hasKey(object, "assigned_rulers") || hasKey(object, "secondary_ruler")
    );
    return {
      title,
      columns: ["天體", "星座", "元素", "日間守護", "夜間守護", "本盤選定"]
        .concat(withPrincipal ? ["主守護"] : [])
        .concat(withCoRulers ? ["指派主星", "次要共主（不計分）"] : []),
      collapse: ["本盤選定", "次要共主（不計分）"],
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
      columns: ["天體", "星座", DEGREE_IN_SIGN_COLUMN, "守護", "界段"]
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
  // 面／旬的守護者型別不同（迦勒底行星面是行星、Manilius 星座旬是星座），
  // 欄名依後端 ruler_type，不混用同一個「守護」。
  const rulerType = profile.ruler_type;
  const rulerLabel = rulerType === "planet" ? "守護行星" : (rulerType === "sign" ? "守護星座" : "守護");
  const withDecan = objects.some((object) => hasKey(object, "decan_number"));
  // Manilius 雙魚前兩旬是編者校正，方法頁說「回應中標明」，畫面也要標。
  const withReading = objects.some((object) => hasKey(object, "ruler_reading"));
  return {
    title,
    columns: ["天體", "星座", DEGREE_IN_SIGN_COLUMN].concat(withDecan ? ["旬"] : []).concat([rulerLabel])
      .concat(withReading ? ["讀法"] : []),
    collapse: ["讀法"],
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
const COMPARISON_TITLE_PREFIX = "各家對照：";
const COMPARISON_VERDICT = Object.freeze({
  same: "相同",
  differ: "有不同",
  unknown: "無法比：日夜盤未知",
  not_compared: "不比：一套是行星、一套是星座",
});
const COMPARISON_SHORT = Object.freeze({ bounds: "界", face_decan: "面", triplicity: "三分性" });
const COMPARISON_FULL_TITLE = Object.freeze({
  bounds: "完整界段", face_decan: "完整表", triplicity: "完整表",
});

/** 一套表的名稱（計算頁選單上的那個名字）；研究用的表名稱後註明。 */
function profileLabel(profileId, researchOnly) {
  const name = Labels.label("dignity_profile", profileId);
  return researchOnly.has(profileId) ? `${name}（研究用）` : name;
}

/**
 * 對照表一格：這一套表給這顆星的守護者，照它自己完整表的印法。日夜盤未知、這一套又依日夜盤選主時，
 * 寫日盤與夜盤的候選。三分性只列日夜盤當令的那一顆（selected_rulers 的第一顆）。
 * day／night 是這一格在日盤、夜盤各會印出的守護者，「各家」拿它們比。
 */
function comparisonCell(technique, object) {
  const known = (ruler) => ({ text: rulerName(ruler), day: rulerName(ruler), night: rulerName(ruler) });
  // 日盤、夜盤的候選相同時，答案不靠日夜盤，只寫一次。
  const candidates = (day, night) => (rulerName(day) === rulerName(night) ? known(day) : {
    text: `日 ${rulerName(day)}／夜 ${rulerName(night)}`, day: rulerName(day), night: rulerName(night),
  });
  if (technique === "bounds") {
    if (object.ruler) return known(object.ruler);
    const day = isRecord(object.day_candidate) ? object.day_candidate.ruler : null;
    const night = isRecord(object.night_candidate) ? object.night_candidate.ruler : null;
    if (day && night) return candidates(day, night);
    throw exportPipeline.incompleteResponse("界缺少守護");
  }
  if (technique === "triplicity") {
    if (Array.isArray(object.selected_rulers) && object.selected_rulers.length) {
      return known(object.selected_rulers[0]);
    }
    const day = Array.isArray(object.day_rulers) ? object.day_rulers[0] : null;
    const night = Array.isArray(object.night_rulers) ? object.night_rulers[0] : null;
    if (day && night) return candidates(day, night);
    throw exportPipeline.incompleteResponse("三分性缺少守護");
  }
  if (!object.ruler) throw exportPipeline.incompleteResponse("面／旬缺少守護");
  return known(object.ruler);
}

/**
 * 「各家」一格：只比印出來的字。日盤、夜盤兩種情況都相同才是「相同」，兩種都不同才是「有不同」；
 * 答案要看日夜盤才知道時是「無法比」。面的兩套守護者型別不同（行星與星座），不比。
 */
function comparisonVerdict(technique, cells) {
  if (technique === "face_decan") return COMPARISON_VERDICT.not_compared;
  const sameBy = (side) => new Set(cells.map((cell) => cell[side])).size === 1;
  const [day, night] = [sameBy("day"), sameBy("night")];
  if (day && night) return COMPARISON_VERDICT.same;
  if (!day && !night) return COMPARISON_VERDICT.differ;
  return COMPARISON_VERDICT.unknown;
}

function comparisonTable(technique, profiles, researchOnly) {
  // 各套的逐星列都已核過是七政、依序（dignityProfile），所以依列號對齊。
  return {
    title: `${COMPARISON_TITLE_PREFIX}${COMPARISON_SHORT[technique]}`,
    columns: ["天體", "星座", DEGREE_IN_SIGN_COLUMN]
      .concat(profiles.map((profile) => profileLabel(profile.profile_id, researchOnly)))
      .concat(["各家"]),
    rows: profiles[0].objects.map((object, index) => {
      const cells = profiles.map((profile) => comparisonCell(technique, profile.objects[index]));
      return [object.name, signName(object.sign), degreeInSignText(object)]
        .concat(cells.map((cell) => cell.text))
        .concat([comparisonVerdict(technique, cells)]);
    }),
    // 面／旬的兩套守護者型別不同，「各家」每一列都是「不比」；收成一句表下註。
    ...(technique === "face_decan" ? { collapse: ["各家"] } : {}),
  };
}

/** 太陽在近地平敏感帶內、subject 又依日夜盤選主星時的一句。 */
function sectBandNote(arcmin, subject, isDay) {
  return `太陽在近地平敏感帶（±${arcmin}′）內：${subject}依日夜盤選主星，`
    + `本盤依太陽真高度 > 0° 的規則判為${isDay === true ? "日盤" : "夜盤"}；`
    + "若改用標準視日出等其他具名邊界，選到的主星可能不同。";
}

function allProfilesSection(technique, sectionId, status, dignities, context) {
  const { results, researchOnly, sectUnknown, sectDependent, sectInBand, sectBandArcmin, sectIsDay } = context;
  const computed = need(need(dignities, "essential_dignities", "computed_profiles", "record"),
    "essential_dignities.computed_profiles", technique, "array");
  // 應有的那幾套取自計算頁的目錄，不取自回應自己的 computed_profiles：少算一套就拒絕，不改口說「都算了」。
  needExactly(computed, catalogueProfiles(technique), `essential_dignities.computed_profiles.${technique}`);
  const profiles = computed.map((profileId) => dignityProfile(results, profileId, technique));
  const names = computed.map((profileId) => profileLabel(profileId, researchOnly));
  const short = COMPARISON_SHORT[technique];
  const notes = [
    `全部並列：本版 ${computed.length} 套${short}表都算了，依目錄順序列出（${names.join("、")}），不設主要那一套。`
      + "先看對照表：每顆星每一套說的守護者；各套的完整表接在後面。",
    `「各家」一欄只比較各套印出來的守護者是否相同。寫「${COMPARISON_VERDICT.differ}」不表示哪一套對，`
      + "欄位也不照幾家相同排序。",
  ];
  if (technique === "triplicity") {
    notes.push("三分性的對照只列日夜盤當令的那一顆（每套表列在第一位的那顆）；Dorotheus 另兩顆參與的守護、"
      + "Ptolemy 的指派主星與次要共主，在各套的完整表。");
  }
  if (technique === "face_decan") {
    notes.push("面／旬的兩套守護者型別不同：迦勒底行星面是行星，Manilius 星座旬是星座，"
      + "所以只並排列出，不比相同或不同。");
  }
  computed.filter((profileId) => researchOnly.has(profileId)).forEach((profileId) => {
    notes.push(`${Labels.label("dignity_profile", profileId)}列為研究用：一樣照原書列出，名稱後註明。`);
  });
  const dependent = computed.filter((profileId) => sectDependent.has(profileId));
  if (dependent.length && sectUnknown) {
    notes.push(`日夜盤未知：${dependent.map((profileId) => profileLabel(profileId, researchOnly)).join("、")}`
      + "的守護依日夜盤而異，對照表寫日盤與夜盤的候選；日盤、夜盤兩種情況答案不一樣時，"
      + `「各家」寫「${COMPARISON_VERDICT.unknown}」。`);
  }
  if (dependent.length && sectInBand) {
    notes.push(sectBandNote(
      sectBandArcmin, dependent.map((profileId) => profileLabel(profileId, researchOnly)).join("、"), sectIsDay
    ));
  }
  profiles.forEach((profile) => {
    notes.push(`來源：${profileLabel(profile.profile_id, researchOnly)}——${profile.source}`);
  });
  // 中文名稱會改寫，不能當程式對應的鍵；每一種匯出（CSV、TXT、Markdown）都帶這一行代碼。
  notes.push(`對照表各欄的代碼（profile_id，與 JSON 的 profile_results 同名，供程式對應）：${
    computed.map((profileId) => `${profileLabel(profileId, researchOnly)}＝${profileId}`).join("、")}。`);
  const tables = [comparisonTable(technique, profiles, researchOnly)].concat(profiles.map((profile) => dignityTable(
    technique, profile,
    `${profileLabel(profile.profile_id, researchOnly)}：${COMPARISON_FULL_TITLE[technique]}`,
    sectUnknown
  )));
  return makeSection(sectionId, TECHNIQUE_LABELS[technique], RING.METHOD, status, {
    notes, tables, blocks: [],
  });
}

function dignityProfileSections(response) {
  const dignities = response.derived_methods.essential_dignities;
  if (!isRecord(dignities)) return [];
  const status = receiptStatus(dignities);
  if (status.state !== "present") {
    return Object.keys(TECHNIQUE_LABELS).map((technique) => absentSectionFor(
      `dignity_${technique}`, TECHNIQUE_LABELS[technique], RING.METHOD, "本次未請求本質尊貴。", status
    ));
  }
  // 四套技法各自選了哪個 profile 是收據的一部分；缺席不是「未選定」（未選定是 null）。
  const selected = need(dignities, "essential_dignities", "selected_profiles", "record");
  Object.keys(TECHNIQUE_LABELS).forEach((technique) => need(
    selected, "essential_dignities.selected_profiles", technique, "string?"
  ));
  const results = need(dignities, "essential_dignities", "profile_results", "record");
  const comparison = triplicityComparison(response, dignities, selected.triplicity);
  // 日夜盤是否可知、哪些 profile 依它選主，收據的 sect 區塊各說一次。
  const sect = dignitySect(dignities);
  const sectUnknown = sect.selected_ruler_available === false;
  const sectDependent = new Set(sect.sect_dependent_components);
  // 帶內旗標與帶寬讀同一份 sect 收據（後端 classify_sect）；選主仍只有一套。
  const sectInBand = !sectUnknown && sect.in_near_horizon_band === true;
  const sectBandArcmin = num(sect.near_horizon_band_half_width_degrees * 60, 0);
  const researchOnly = new Set(need(dignities, "essential_dignities", "research_only_profiles", "array"));

  return Object.keys(TECHNIQUE_LABELS).map((technique) => {
    const profileId = selected[technique];
    const sectionId = `dignity_${technique}`;
    // 並列比較的表附在三分性底下，明示不影響選定的那一套；沒選主要那一套時，比較照 Dossier 照樣列出。
    const comparisonTables = technique !== "triplicity" ? [] : comparison
      .filter((otherId) => otherId !== profileId)
      .map((otherId) => {
        const other = dignityProfile(results, otherId, technique);
        const sourceName = other.source.split(",")[0];
        return dignityTable(technique, other,
          profileId ? `並列比較（不影響選定）：${sourceName}` : `並列比較：${sourceName}`, sectUnknown);
      });
    if (!profileId && !comparisonTables.length) {
      return absentSection(sectionId, TECHNIQUE_LABELS[technique], RING.METHOD,
        "本次未選定這套技法的 profile；未選定不是「沒有這個技法」。");
    }
    if (profileId === ALL_PROFILES) {
      return allProfilesSection(technique, sectionId, status, dignities, {
        results, researchOnly, sectUnknown, sectDependent, sectInBand, sectBandArcmin,
        sectIsDay: sect.is_day,
      });
    }
    const profile = profileId ? dignityProfile(results, profileId, technique) : null;
    const notes = profile ? [`來源：${profile.source}`] : [
      `本次未選定主要的一套${COMPARISON_SHORT[technique]}表；依你勾選的「並列比較」，`
        + `列出 ${comparisonTables.length} 套表，每一套都照原書列出，不設主要那一套。`,
    ];
    if (technique === "domicile_exaltation") notes.push(...DEBILITY_NOTES);
    const sectNamed = profileId ? [profileId] : comparison;
    if (sectUnknown && sectNamed.some((id) => sectDependent.has(id))) {
      notes.push("日夜盤未知時，這套技法的守護依日夜盤而異；本產品不替你選一個，日盤與夜盤候選並列。");
    }
    if (sectInBand && sectNamed.some((id) => sectDependent.has(id))) {
      notes.push(sectBandNote(sectBandArcmin, "這套技法", sect.is_day));
    }
    const tables = (profile ? [dignityTable(
      technique, profile,
      `${TECHNIQUE_LABELS[technique]}　${technique === "domicile_exaltation" ? "判定" : "守護配置"}`,
      sectUnknown
    )] : []).concat(comparisonTables);
    return makeSection(sectionId, TECHNIQUE_LABELS[technique], RING.METHOD, status, {
      notes, tables, blocks: [],
    });
  });
}

// 外來（core/essential_dignities.py _peregrine_profile）。
// 照原典的分類列出、附出處，不打分；判定固定依 Lilly 1647 自己那一套表。
const PEREGRINE_TITLE = "外來 Peregrine";
// 鍵是 dignity_tables.PEREGRINE_STATUSES 的閉集。
const PEREGRINE_STATUS_ZH = Object.freeze({
  peregrine: "外來",
  not_peregrine: "不是外來",
  undetermined_sect_unknown: "無法判定（日夜盤未知）",
  undetermined_sect_near_horizon: "無法判定（太陽貼近地平線）",
});
const PEREGRINE_SECT_ZH = Object.freeze({ peregrine: "外來", not_peregrine: "不是外來" });
const PEREGRINE_DIGNITY_ZH = Object.freeze({
  domicile: "廟", exaltation: "旺", triplicity: "三分性", term: "界", face: "面",
});
const PEREGRINE_DEBILITY_ZH = Object.freeze({ detriment: "陷", fall: "弱" });
const PEREGRINE_SOURCE_LINES = Object.freeze([
  ["William Lilly, Christian Astrology (1647) p.112",
    "出處：Lilly《Christian Astrology》1647 年版 p.112：行星在某個星座的度數上沒有任何本質尊貴，就叫外來；"
    + "例如土星在牡羊 10° 是外來，在 27°、28° 是在自己的界。p.103：在自己的面就不能叫外來；"
    + "p.102：三分性只算日夜盤當令的那一顆；p.104 是這裡用的那一整張表。",
    "original_language_read", "（1647 年版頁影像）"],
  ["Guido Bonatti, De astronomia (Basel 1550) col.165",
    "出處：Bonatti《De astronomia》（1550 年 Basel 版）col.165：十種阻礙的第八種是外來，「在沒有任何尊貴的位置」；"
    + "不被接納另列為第七、第十種。col.178：廟、旺、三分性、界、面都是尊貴，面的力量最小。",
    "original_language_read", "（1550 年版頁影像）"],
  ["John Gadbury, The Doctrine of Nativities",
    "出處：Gadbury《The Doctrine of Nativities》（1658）p.44：外來是在廟、旺、三分性、界、面五項尊貴之外。",
    "original_language_read", "（1658 年版頁影像）"],
  ["al-Bīrūnī, Kitāb al-tafhīm §493",
    "出處：al-Bīrūnī《占星術入門》§493：行星沒有尊貴叫外來（gharīb），若又在陷或弱，災厄再加上去；§494 列出五項尊貴。",
    "translation_read", "（Wright 1934 英譯的掃描辨識文字）"],
  ["Māshāʾallāh, De cogitatione",
    "出處：Māshāʾallāh《De cogitatione》：土星在獅子「peregrinus, non receptus」（外來、未被接納），外來與接納並列。",
    "translation_read", "（1549 年 Heller 版拉丁譯本的掃描）"],
  [null, "出處：完整書目、換表時的差別與每一條核到哪一層，見方法頁〈面、三分性、廟旺陷弱與外來〉一節。"],
]);
const PEREGRINE_SOURCES = sourceBlocks(PEREGRINE_SOURCE_LINES);
const PEREGRINE_NOTES = Object.freeze([
  "外來（peregrine）：行星所在的度數，在它自己的廟、旺、三分性、界、面五項裡一項都沒有。"
    + "這是 Lilly《Christian Astrology》1647 p.112 的定義，照原文列出；他在 p.115 的表把外來列在減損（Debilities）一邊。"
    + "Bonatti《De astronomia》（1550）與 Gadbury（1658）也是五項都沒有才算；面也算，Lilly p.103 說在自己的面就不能叫外來。",
  "依 Lilly 判：界用 Lilly 1647 承襲界（p.104），三分性用 Lilly 1647 簡表、只算日夜盤當令的那一顆（p.102），面用迦勒底行星面。"
    + "所以這一區不跟上面選的界、面、三分性。改用其他界或三分性，約 3%～21% 的位置判定會不同。"
    + "「只算當令的那一顆」只有 Lilly 明說，Bonatti 與 Gadbury 沒有說。",
  "外來可以和陷、弱同時成立：al-Bīrūnī《占星術入門》§493 說，行星沒有尊貴叫外來，若又在陷或弱，災厄再加上去（依 Wright 英譯）。",
  "外來與接納是兩件事：Bonatti 把外來和「不被接納」列為不同的阻礙，Māshāʾallāh 寫「peregrinus, non receptus」（外來、未被接納）。"
    + "本站沒有評估接納；接納不會讓一顆行星不算外來。",
]);

function dignityPeregrineSection(response) {
  const dignities = response.derived_methods.essential_dignities;
  // 狀態只由權威說；說了 present，外來的每一格都必須在。
  const section = moduleSection(response, {
    id: "dignity_peregrine", title: PEREGRINE_TITLE, ring: RING.METHOD,
    keys: { module: "essential_dignities" }, container: dignities,
    note: "本次未請求本質尊貴。",
  });
  if (section.absent) return section.absent;
  const path = "essential_dignities.peregrine";
  const selected = need(dignities, "essential_dignities", "selected_profiles", "record");
  const chosen = need(selected, "essential_dignities.selected_profiles", "peregrine", "string?");
  const peregrine = need(dignities, "essential_dignities", "peregrine", "record?");
  if (!chosen) {
    if (peregrine !== null) throw exportPipeline.incompleteResponse(`${path} 未選外來卻有結果`);
    return absentSection("dignity_peregrine", PEREGRINE_TITLE, RING.METHOD,
      "本次未選「外來」；未選定不是「沒有外來」。選了才依 Lilly 1647 的定義判定。");
  }
  if (!peregrine) throw exportPipeline.incompleteResponse(`缺少 ${path}`);
  const objects = need(peregrine, path, "objects", "records");
  needExactly(objects.map((object, index) => need(object, `${path}.objects[${index}]`, "name", "string")),
    SEVEN_NAMES, `${path}.objects`);
  const sect = dignitySect(dignities);
  const notes = PEREGRINE_NOTES.slice();
  // 兩句說的是規則，日夜盤收據（classify_sect）一說就附上；哪幾顆真的無法判定，由逐列的判定說。
  if (sect.selected_ruler_available === false) {
    notes.push("日夜盤未知：只差三分性一項就決定外來與否的行星，寫「無法判定」，最後一欄列出日盤、夜盤各會怎麼判。");
  } else if (sect.in_near_horizon_band === true) {
    notes.push(
      `太陽在近地平敏感帶（±${num(sect.near_horizon_band_half_width_degrees * 60, 0)}′）內：日夜盤換一種邊界就可能相反，`
      + "所以只差三分性一項就決定外來與否的行星，寫「無法判定」，最後一欄列出日盤、夜盤各會怎麼判。"
    );
  }
  notes.push("不給分數，也不加總。照原典列出。不替你解盤，也不預測。");
  const list = (values, labels, label) => (values.length
    ? values.map((value) => presentClosedVocabulary(value, labels, label)).join("、") : DASH);
  return section.make({
    notes,
    tables: [{
      title: "外來　依 Lilly 1647 判",
      columns: ["天體", "星座", DEGREE_IN_SIGN_COLUMN, "判定", "有的尊貴", "同時在", "日盤／夜盤"],
      rows: objects.map((object, index) => {
        const at = `${path}.objects[${index}]`;
        const bySect = need(object, at, "by_sect", "record");
        const dayCode = need(bySect, `${at}.by_sect`, "day", "string");
        const nightCode = need(bySect, `${at}.by_sect`, "night", "string");
        const day = presentClosedVocabulary(dayCode, PEREGRINE_SECT_ZH, "日盤判定");
        const night = presentClosedVocabulary(nightCode, PEREGRINE_SECT_ZH, "夜盤判定");
        return [
          object.name,
          signName(need(object, at, "sign", "string")),
          need(object, at, "degree_in_sign_text", "string"),
          presentClosedVocabulary(need(object, at, "status", "string"), PEREGRINE_STATUS_ZH, "外來判定"),
          list(need(object, at, "dignities_held", "array"), PEREGRINE_DIGNITY_ZH, "尊貴"),
          list(need(object, at, "debilities_also", "array"), PEREGRINE_DEBILITY_ZH, "減損"),
          dayCode === nightCode ? `日夜相同：${day}` : `日盤：${day}；夜盤：${night}`,
        ];
      }),
    }],
    blocks: PEREGRINE_SOURCES.slice(),
  });
}
