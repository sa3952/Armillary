const test = require("node:test");
const assert = require("node:assert/strict");

const RequestInput = require("../zh-TW/request-input.js");
const Catalogue = require("../zh-TW/options-catalogue.js");

// 這一檔守兩件事：時間欄位不得靜默改值，UI 數字範圍不得與 API 契約不一致。兩者的失敗
// 形狀相同——介面接受了一個它算不出來的值，而且不說。所以每一組都同時要求「不合法的值
// 必須被指名」與「合法的值必須原樣通過」；只有前者會被一個什麼都拒絕的實作騙過去。

const { EMPTY, INVALID, VALUE } = RequestInput.STATES;

test("欄位讀取：小數或非數字的時分是錯誤而不是截斷或 0；秒保留小數並把 60 留給後端閏秒驗證", () => {
  for (const [read, raw, expected] of [
    ["readInteger", "12", { state: VALUE, value: 12 }],
    ["readInteger", " 0 ", { state: VALUE, value: 0 }],
    ["readInteger", "+7", { state: VALUE, value: 7 }],
    ["readSecond", "0.25", { state: VALUE, value: 0.25 }],
    ["readSecond", "59.999", { state: VALUE, value: 59.999 }],
    ["readSecond", "59.999999", { state: VALUE, value: 59.999999 }],
    ["readSecond", "5e-6", { state: VALUE, value: 0.000005 }],
    ["readSecond", "0", { state: VALUE, value: 0 }],
    ["readSecond", "60", { state: VALUE, value: 60 }],
    ["readDecimal", "22.9908", { state: VALUE, value: 22.9908 }],
    ["readDecimal", "-120.2133", { state: VALUE, value: -120.2133 }],
  ]) {
    assert.deepEqual(RequestInput[read](raw), expected, `${read}(${raw})`);
  }
  for (const [read, raws, state] of [
    ["readInteger", ["", "   "], EMPTY],
    ["readSecond", [""], EMPTY],
    ["readDecimal", [""], EMPTY],
    // 舊版 `readInteger(x) || 0` 會把 NaN 變成 0，也就是把打錯字算成午夜。
    ["readInteger", ["12.5", "1.5", "0.9", "-3.2", "abc", "NaN", "Infinity", "1e2", "١٢"], INVALID],
    // 比微秒更細的值拒絕而不捨入，與後端 second_finer_than_microsecond 相同。
    ["readSecond", ["60.001", "-0.5", "abc", "59.9999999", "1e-7", "30.0000005"], INVALID],
    ["readDecimal", ["abc", "Infinity", "1/2"], INVALID],
  ]) {
    raws.forEach((raw) => assert.equal(RequestInput[read](raw).state, state, `${read}(${raw})`));
  }
});

// 每個數字選項都宣告範圍；範圍與 API 契約相同由 tests/integration/test_frontend_contract.py 以
// backend/app/schemas.py 的欄位約束對照（這裡曾手抄一份 `gt: 0`，schema 改成 `ge=0` 後仍綠）。
test("每個數字選項都宣告有限的範圍", () => {
  Catalogue.OPTIONS.filter((option) => option.type === "number").forEach((option) => {
    assert.ok(Number.isFinite(option.min) && Number.isFinite(option.max) && option.min <= option.max, option.key);
  });
});

test("送出前的範圍檢查指名越界或清空的選項；上下界、未啟用的選項與預設值都通過", () => {
  const problems = (overrides) => RequestInput.numericOptionProblems(Catalogue, { ...Catalogue.defaults(), ...overrides });
  for (const [overrides, pattern] of [
    [{ include_declination_aspects: true, declination_aspect_orb_degrees: 30 }, /不得大於 3/],
    // 清空「預設非 null」的數字欄位會送出 null，後端回 float_type 422；必須被指名為必填。
    [{ include_declination_aspects: true, declination_aspect_orb_degrees: null }, /必須填寫/],
  ]) {
    const found = problems(overrides);
    assert.equal(found.length, 1, JSON.stringify(found));
    assert.match(found[0], /赤緯容許度/);
    assert.match(found[0], pattern);
  }
  const allBooleansOn = Object.fromEntries(Catalogue.OPTIONS.filter((o) => o.type === "boolean").map((o) => [o.key, true]));
  for (const overrides of [
    { include_declination_aspects: true, declination_aspect_orb_degrees: 3 },
    // 使用者不該被一個他沒開啟、也不會送出的欄位擋下來。
    { include_declination_aspects: false, declination_aspect_orb_degrees: 999 },
    {},
    allBooleansOn,
    // 預設本來就是 null 的數字欄位，清空是合法的省略。
    { include_aspects: true, aspect_include_angles: true,
      aspect_fixed_orb_degrees: null, aspect_angle_orb_degrees: null, aspect_orb_scale_percent: null },
  ]) {
    assert.deepEqual(problems(overrides), [], JSON.stringify(overrides));
  }
});

// ── 模糊民用時刻：oracle 是 IANA 時區資料本身，不是本模組的另一條路徑 ──────────

const civil = (year, month, day, hour, minute = 0) => ({ year, month, day, hour, minute, second: 0 });

test("秋季調慢的重複時刻給出兩個解讀，fold=0 是較早的瞬間；台灣歷史上的重複小時同樣被抓到", () => {
  const paris = RequestInput.civilTimeOccurrences(civil(2025, 10, 26, 2, 30), "Europe/Paris");
  assert.equal(paris.state, "ambiguous");
  assert.deepEqual(paris.occurrences.map((o) => [o.fold, o.offsetHours, o.utcIso]), [
    [0, 2, "2025-10-26T00:30:00.000Z"], [1, 1, "2025-10-26T01:30:00.000Z"],
  ]);
  // 台灣曾在 1937、1945-1961、1974、1975、1979 實施日光節約時間。
  const taipei = RequestInput.civilTimeOccurrences(civil(1979, 9, 30, 23, 30), "Asia/Taipei");
  assert.equal(taipei.state, "ambiguous", JSON.stringify(taipei));
  assert.deepEqual(taipei.occurrences.map((o) => o.offsetHours), [9, 8]);
});

test("一般時刻與固定偏移時區是唯一解，春季跳過的時刻不存在，時區不明時回 null", () => {
  for (const [fields, zone, offset] of [[civil(1997, 8, 17, 9, 42), "Asia/Taipei", 8], [civil(2025, 10, 26, 2, 30), "UTC", 0]]) {
    const result = RequestInput.civilTimeOccurrences(fields, zone);
    assert.equal(result.state, "unique", zone);
    assert.equal(result.occurrences[0].offsetHours, offset, zone);
  }
  const taipei = RequestInput.civilTimeOccurrences(civil(1997, 8, 17, 9, 42), "Asia/Taipei");
  assert.equal(taipei.occurrences.length, 1);
  assert.equal(taipei.occurrences[0].utcIso, "1997-08-17T01:42:00.000Z");
  const skipped = RequestInput.civilTimeOccurrences(civil(2025, 3, 30, 2, 30), "Europe/Paris");
  assert.equal(skipped.state, "nonexistent");
  assert.deepEqual(skipped.occurrences, []);
  for (const [fields, zone] of [[civil(2025, 1, 1, 0), ""], [civil(2025, 1, 1, 0), "Not/AZone"], [civil(2025, 1, 1, NaN), "Asia/Taipei"]]) {
    assert.equal(RequestInput.civilTimeOccurrences(fields, zone), null, zone);
  }
});

// 大約時辰以整個小時為單位判定：重複區段可以在小時中間開始或結束，整點本身只出現一次。
// tests/integration/test_partial_hour_fold_parity.py 以伺服器的 zoneinfo 為 oracle 抽樣比對 1900–2030。
test("civilHourOccurrences：小時內任一段重複就是模糊；鄰近的小時、空隙與固定偏移不是", () => {
  for (const [zone, fields, repeated] of [
    ["America/St_Johns", { year: 2005, month: 10, day: 29, hour: 23 }, { from: 60, to: 3600 }],
    ["Australia/Lord_Howe", { year: 2024, month: 4, day: 7, hour: 1 }, { from: 1800, to: 3600 }],
    ["America/St_Johns", { year: 2005, month: 10, day: 30, hour: 0 }, { from: 0, to: 60 }],
    ["America/New_York", { year: 2023, month: 11, day: 5, hour: 1 }, { from: 0, to: 3600 }],
  ]) {
    const result = RequestInput.civilHourOccurrences(fields, zone);
    assert.equal(result.state, "ambiguous", `${zone} ${JSON.stringify(fields)}`);
    assert.deepEqual(result.repeated, repeated);
    assert.deepEqual(result.occurrences.map((o) => o.fold), [0, 1]);
  }
  for (const [zone, fields] of [
    ["America/St_Johns", { year: 2005, month: 10, day: 29, hour: 22 }],
    ["Australia/Lord_Howe", { year: 2024, month: 4, day: 7, hour: 2 }],
    ["Australia/Lord_Howe", { year: 2024, month: 10, day: 6, hour: 2 }],   // 半小時空隙
    ["Europe/Paris", { year: 2025, month: 3, day: 30, hour: 2 }],          // 整小時空隙
    ["UTC", { year: 2025, month: 10, day: 26, hour: 2 }],
  ]) {
    assert.equal(RequestInput.civilHourOccurrences(fields, zone).state, "not_ambiguous", `${zone} ${JSON.stringify(fields)}`);
  }
  assert.equal(RequestInput.civilHourOccurrences({ year: 2025, month: 1, day: 1, hour: 0 }, "Not/AZone"), null);
  assert.equal(RequestInput.civilHourOccurrences({ year: 2025, month: 1, day: 1, hour: NaN }, "UTC"), null);
});
