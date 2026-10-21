const test = require("node:test");
const assert = require("node:assert/strict");

const RequestInput = require("../../scripts/frontend/scripts/request-input.js");
const Catalogue = require("../../scripts/frontend/scripts/options-catalogue.js");

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

// Date.UTC 把 0–99 年當成 1900–1999 年：year 50 曾被算成 1950 年，Asia/Taipei 1950-09-30 23 時
// 的夏令時間重複因此冒出來。期待值是 IANA 的事實：tzdata 在 1896 年以前只有地方平時（LMT），
// 西元 50 年的任何時刻都只出現一次；世界時也必須落在西元 0050 年，不是 1950 年。
test("兩位數年份不被當成 19xx：西元 50 年的台北沒有夏令時間的重複，世界時落在 0050 年", () => {
  const ancient = RequestInput.civilTimeOccurrences(civil(50, 9, 30, 23, 30), "Asia/Taipei");
  assert.equal(ancient.state, "unique", JSON.stringify(ancient));
  assert.match(ancient.occurrences[0].utcIso, /^0050-09-30T/);
  assert.notEqual(ancient.occurrences[0].offsetHours, 9, "1950 年的夏令時間偏移不得套到西元 50 年");
  assert.equal(
    RequestInput.civilHourOccurrences({ year: 50, month: 9, day: 30, hour: 23 }, "Asia/Taipei").state,
    "not_ambiguous",
  );
  const utc = RequestInput.civilTimeOccurrences(civil(99, 1, 1, 12, 0), "UTC");
  assert.equal(utc.occurrences[0].utcIso, "0099-01-01T12:00:00.000Z");
  // 對照組：同一個鐘面時刻在 1950 年確實重複，所以上面的 unique 不是什麼都回 unique 的實作。
  assert.equal(RequestInput.civilTimeOccurrences(civil(1950, 9, 30, 23, 30), "Asia/Taipei").state, "ambiguous");
});

// ── 出生日期三欄（年／月／日）：表單 novalidate，範圍要在這裡檢查 ──────────
// 期待值逐筆手打；fields 是要標紅的那幾欄，供頁面逐欄標 aria-invalid。
const parts = (year, month, day) => ({ year, month, day });
test("出生日期三欄：格式、日曆與範圍不合就指名拒絕並指出是哪一欄，範圍兩端與一般日期原樣通過", () => {
  const bounds = { min: "1900-01-01", max: "2399-12-31" };
  for (const [raw, expected] of [
    [parts("1990", "5", "15"), { year: 1990, month: 5, day: 15, iso: "1990-05-15" }],
    [parts("1990", "05", "05"), { year: 1990, month: 5, day: 5, iso: "1990-05-05" }],
    [parts("1900", "1", "1"), { year: 1900, month: 1, day: 1, iso: "1900-01-01" }],
    [parts("2399", "12", "31"), { year: 2399, month: 12, day: 31, iso: "2399-12-31" }],
    [parts(" 2000 ", " 2 ", " 29 "), { year: 2000, month: 2, day: 29, iso: "2000-02-29" }],
    // 中文輸入法常送出全形數字。
    [parts("１９９０", "１", "１５"), { year: 1990, month: 1, day: 15, iso: "1990-01-15" }],
  ]) {
    assert.deepEqual(RequestInput.readBirthDateParts(raw, bounds), { state: VALUE, value: expected }, JSON.stringify(raw));
  }
  assert.deepEqual(RequestInput.readBirthDateParts(parts("", "", ""), bounds), { state: EMPTY, fields: ["year", "month", "day"] });
  assert.deepEqual(RequestInput.readBirthDateParts(parts("1990", " ", ""), bounds), { state: EMPTY, fields: ["month", "day"] });
  for (const [raw, pattern, fields] of [
    [parts("1895", "5", "15"), /1900-01-01 到 2399-12-31/, ["year"]],
    [parts("1899", "12", "31"), /1900-01-01 到 2399-12-31/, ["year"]],
    [parts("2400", "1", "1"), /1900-01-01 到 2399-12-31/, ["year"]],
    [parts("0050", "5", "15"), /1900-01-01 到 2399-12-31/, ["year"]],
    [parts("21000", "5", "15"), /四位數/, ["year"]],
    [parts("90", "5", "15"), /四位數/, ["year"]],
    [parts("1990", "13", "1"), /月份必須是 1 到 12/, ["month"]],
    [parts("1990", "0", "1"), /月份必須是 1 到 12/, ["month"]],
    [parts("1990", "1", "32"), /日必須是 1 到 31/, ["day"]],
    [parts("1990", "1.5", "3"), /月份必須是 1 到 12/, ["month"]],
    [parts("abc", "x", "1"), /四位數/, ["year", "month"]],
    [parts("1990", "2", "30"), /不存在/, ["day"]],
    [parts("1900", "2", "29"), /不存在/, ["day"]],
  ]) {
    const read = RequestInput.readBirthDateParts(raw, bounds);
    assert.equal(read.state, INVALID, JSON.stringify(raw));
    assert.match(read.reason, pattern, JSON.stringify(raw));
    assert.deepEqual(read.fields, fields, JSON.stringify(raw));
  }
  assert.equal(RequestInput.readBirthDateParts(parts("2150", "5", "15"), bounds).state, VALUE, "上限是 2399，不是 2099");
});

// ── 民國年與日本年號 ──────────────────────────────────────────────
// 期待值是逐條手打的史實，不由被測的年號表推出：民國元年＝1912；明治改元大正在
// 1912 年 7 月 30 日（明治 45 年 7 月 29 日為明治最後一天），大正改元昭和在 1926 年
// 12 月 25 日（大正 15 年 12 月 24 日為大正最後一天），昭和最後一天是 1989 年 1 月 7 日。
const DATE_BOUNDS = { min: "1900-01-01", max: "2399-12-31" };
const era = (name, year, month, day) => RequestInput.readEraDate(
  { era: name, year: String(year), month: String(month), day: String(day) }, DATE_BOUNDS
);

test("年號換算：手打的史實逐條對上，回顯含換算式", () => {
  for (const [args, iso] of [
    [["roc", 64, 7, 15], "1975-07-15"],
    [["roc", 1, 1, 1], "1912-01-01"],
    [["roc", 79, 5, 15], "1990-05-15"],
    [["roc", 34, 10, 25], "1945-10-25"],
    [["roc", 89, 2, 29], "2000-02-29"],
    [["roc", 9, 2, 29], "1920-02-29"],
    [["roc", 488, 12, 31], "2399-12-31"],
    [["meiji", 33, 1, 1], "1900-01-01"],
    [["meiji", 45, 7, 29], "1912-07-29"],
    [["taisho", 1, 7, 30], "1912-07-30"],
    [["taisho", 12, 9, 1], "1923-09-01"],
    [["taisho", 15, 12, 24], "1926-12-24"],
    [["showa", 1, 12, 25], "1926-12-25"],
    [["showa", 1, 12, 31], "1926-12-31"],
    [["showa", 2, 1, 1], "1927-01-01"],
    [["showa", 3, 2, 29], "1928-02-29"],
    [["showa", 12, 10, 1], "1937-10-01"],
    [["showa", 20, 8, 15], "1945-08-15"],
    [["showa", 64, 1, 7], "1989-01-07"],
  ]) {
    const read = era(...args);
    assert.equal(read.state, VALUE, `${args.join(" ")}：${read.reason || ""}`);
    assert.equal(read.value.iso, iso, args.join(" "));
  }
  const roc = era("roc", 64, 7, 15).value;
  assert.equal(roc.eraText, "民國 64 年 7 月 15 日");
  assert.equal(roc.gregorianText, "西元 1975 年 7 月 15 日");
  assert.equal(roc.formula, "64 ＋ 1911 ＝ 1975");
  const showa = era("showa", 1, 12, 25).value;
  assert.equal(showa.eraText, "昭和元年 12 月 25 日");
  assert.equal(showa.formula, "1 ＋ 1925 ＝ 1926");
  assert.equal(era("meiji", 45, 7, 29).value.formula, "45 ＋ 1867 ＝ 1912");
  assert.equal(era("taisho", 15, 12, 24).value.formula, "15 ＋ 1911 ＝ 1926");
});

test("年號換算：改元日前後與不存在的日期一律拒絕，並說出原因", () => {
  for (const [args, pattern] of [
    [["taisho", 1, 7, 29], /大正元年從西元 1912 年 7 月 30 日開始/],
    [["taisho", 1, 1, 1], /大正元年從西元 1912 年 7 月 30 日開始/],
    [["showa", 1, 12, 24], /昭和元年從西元 1926 年 12 月 25 日開始/],
    [["showa", 1, 3, 1], /昭和元年從西元 1926 年 12 月 25 日開始/],
    [["meiji", 45, 7, 30], /明治的最後一天是西元 1912 年 7 月 29 日/],
    [["meiji", 46, 1, 1], /明治的最後一天是西元 1912 年 7 月 29 日/],
    [["taisho", 15, 12, 25], /大正的最後一天是西元 1926 年 12 月 24 日/],
    [["taisho", 16, 1, 1], /大正的最後一天是西元 1926 年 12 月 24 日/],
    [["showa", 64, 1, 8], /昭和的最後一天是西元 1989 年 1 月 7 日/],
    [["roc", 88, 2, 29], /這一天不存在/],
    [["roc", 64, 2, 30], /這一天不存在/],
    [["roc", 64, 13, 1], /月份必須是 1 到 12/],
    [["roc", 64, 0, 1], /月份必須是 1 到 12/],
    [["roc", 0, 1, 1], /年份從元年（1）起算/],
    [["roc", -1, 1, 1], /年份從元年（1）起算/],
    [["roc", "64.5", 1, 1], /必須是整數/],
    [["roc", 489, 1, 1], /西元 2400 年，超出本計算器的 1900–2399 年範圍/],
    [["meiji", 32, 12, 31], /西元 1899 年，超出本計算器的 1900–2399 年範圍/],
    // 字串比較會讓五位數的年份（"21000-01-01"）落在 "1900" 與 "2399" 之間。
    [["roc", 19089, 1, 1], /西元 21000 年，超出本計算器的 1900–2399 年範圍/],
    [["heisei", 1, 1, 8], /請選擇紀年/],
  ]) {
    const read = era(...args);
    assert.equal(read.state, INVALID, args.join(" "));
    assert.match(read.reason, pattern, args.join(" "));
  }
  assert.equal(era("roc", "", "", "").state, EMPTY, "全部空白是「沒填」，不是錯誤");
  assert.equal(era("roc", 64, "", 15).state, INVALID, "部分空白是錯誤");
});

test("年號換算：每個年號的每一天都換回同一天（逐日走過 1900–1989，另以民國走到 2399）", () => {
  // 期待值只用上面手打的改元日判斷每一天屬於哪個年號，不讀被測模組的表。
  const boundaries = [
    ["meiji", 1867, "1900-01-01", "1912-07-29"],
    ["taisho", 1911, "1912-07-30", "1926-12-24"],
    ["showa", 1925, "1926-12-25", "1989-01-07"],
    ["roc", 1911, "1912-01-01", "2399-12-31"],
  ];
  for (const [name, offset, first, last] of boundaries) {
    const day = new Date(`${first}T00:00:00Z`);
    const end = new Date(`${last}T00:00:00Z`);
    for (; day <= end; day.setUTCDate(day.getUTCDate() + (name === "roc" ? 7 : 1))) {
      const iso = day.toISOString().slice(0, 10);
      const read = era(name, day.getUTCFullYear() - offset, day.getUTCMonth() + 1, day.getUTCDate());
      assert.equal(read.state, VALUE, `${name} ${iso}`);
      assert.equal(read.value.iso, iso);
    }
  }
});
