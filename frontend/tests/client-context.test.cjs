const assert = require("node:assert/strict");
const test = require("node:test");
const ClientContext = require("../../scripts/frontend/scripts/client-context.js");
const {
  formatApiError, apiErrorActions, networkErrorMessage, placeQueryNotice, fieldControlIds, KNOWN_CONTROL_IDS,
} = ClientContext;

// 422 驗證拒絕與其他拒絕同一個信封——`detail` 是物件，欄位發現在 `issues`。
const validationRefusal = (...issues) => ({ code: "request_validation_failed", issues });
const issue = (type, ...loc) => validationRefusal({ type, loc: ["body", ...loc] });
const GENERIC_INVALID = "部分輸入無法驗證；請檢查必填欄位與格式。";
const holds = (text, pattern) => (typeof pattern === "string" ? text.includes(pattern) : pattern.test(text));

// 拒絕文案只能指向頁面上真的存在的控制項（點名的控制項存在由 calculate_lifecycle.test.cjs 對
// 開機後的頁面 DOM 驗證），而且不得回顯後端原文。
test("拒絕文案逐字對照", () => {
  for (const [detail, status, expected] of [
    [validationRefusal({
      type: "value_error", loc: ["body", "timezone"],
      msg: "Value error, raw framework detail with Not/AZone", input: { iana_name: "Not/AZone" },
    }), 422, "時區名稱無效；請用「地名查詢」選定地點，由目錄帶入時區，"
      + "或在「改為手動輸入座標與時區」裡的「IANA 時區名稱」欄輸入例如 Asia/Taipei 的名稱。"],
    [issue("missing", "datetime", "year"), 422, "年份尚未填寫。"],
    [issue("less_than_equal", "location", "latitude"), 422, "緯度無效；請輸入 -90 到 90 的十進位度數。"],
    [issue("less_than_equal", "datetime", "hour"), 422, "小時超出允許範圍；請參考該欄位下方的數字範圍說明。"],
    // 真正不存在的日期仍是這一句；年份超範圍另有分流（見下一個測試）。
    [issue("date_from_datetime_parsing", "datetime"), 422, "出生日期時間無效；請確認日期確實存在，且時間數字在允許範圍內。"],
    // 頁面上的選項叫「整宮」，極區一定走得通的出路是宮位制選單的第一項「不計算宮位」。
    [{ code: "house_system_unavailable", message: "Placidus 在緯度 89.123456° 無法計算", latitude: 89.123456 }, 422,
      "所選宮位制無法在這個緯度計算；請在「宮位制」選單改選「整宮」，或選「不計算宮位」。"],
    [{ code: "internal_server_error", message: "raw traceback detail" }, 500,
      "網站暫時無法完成這次請求。請稍後再試一次；若持續發生，請透過聯絡頁回報。"],
    // 舊的裸陣列不再當成欄位發現。
    [[{ type: "calendar_date_invalid", loc: ["body", "datetime", "day"] }], 422, GENERIC_INVALID],
  ]) {
    assert.equal(formatApiError(detail, status), expected, JSON.stringify(detail));
  }
});

test("拒絕文案必須說出的與不得說出的", () => {
  for (const [detail, status, includes, excludes] of [
    [{ code: "request_capacity_exhausted" }, 503, [/不是.*輸入|忙碌/], []],
    [{ code: "compute_capacity_exhausted" }, 503, [/稍後|再試一次/], []],
    ["caller supplied secret", 400, [], ["secret"]],
    [null, 500, [/網站暫時無法完成這次請求/], []],
    // 訊息只描述情況：出路由 calculate.js 依選擇區是否真的出現導出，訊息不得自行宣稱頁面能或不能
    // 做什麼，也不得指向本頁不存在的固定偏移輸入，或回顯後端原文。
    [{
      code: "ambiguous_local_time_choice_required",
      message: "此本地時間在 America/New_York 為模糊時刻；已採用 fold=0，對應 UTC-04.00；另一種解讀為 UTC-05.00。",
    }, 422, ["出現了兩次", "需要知道是哪一次"], ["固定偏移", "無法", "fold", "America/New_York", "UTC-04"]],
    // 地名目錄不可用不是「無法完成計算」；指向手動輸入，不回顯內部路徑。
    [{
      code: "place_catalog_unavailable",
      message: "bundled place catalog is unavailable at /app/backend/place_data/places.sqlite3",
    }, 503, ["手動輸入"], ["計算", "sqlite", "/app/"]],
    // 1800-01-01（支援 1900–2399）確實存在；不得叫人去確認日期是否存在。
    [issue("greater_than_equal", "datetime", "year"), 422, ["年份", "範圍"], ["確實存在"]],
    [issue("approximate_hour_requires_zero_subhour"), 422, [/整點|精確到分鐘/], ["輸入資料格式無效"]],
    [issue("date_only_requires_zero_time"), 422, [/清除時間|出生時間類型/], ["輸入資料格式無效"]],
    [issue("moon_profile_center_conflict"), 422, [/站心模式|計算中心/], ["輸入資料格式無效"]],
    [issue("aspect_orb_scale_requires_profile"), 422, ["「容許度表」"], ["輸入資料格式無效"]],
    [issue("calendar_date_invalid", "datetime", "day"), 422, ["「出生日期」"], []],
    // 地理極點上整宮也無法計算。
    [{ code: "house_system_unavailable", reason_code: "unique_ascendant_undefined", latitude: 90 }, 422,
      ["「不計算宮位」"], ["「整宮」"]],
    // 中天沉到地平線下：說清楚為什麼（四段不再是地平線上下各兩段），以及改選什麼。
    [{ code: "house_system_unavailable", reason_code: "mc_below_horizon_rejected" }, 422,
      ["中天（MC", "地平線下", "極圈", "四段", "Porphyry", "Alcabitius", "「整宮」", "「等分宮」", "「不計算宮位」"],
      ["天頂點", "無法在這個緯度計算"]],
    // 本頁到不了這個組合，不得點名控制項。
    [issue("sidereal_with_j2000_frame_not_supported", "computation_mode"), 422, ["J2000"], [/「[^」]+」/]],
    [{ code: "place_search_timeout" }, 503, ["「改為手動輸入座標與時區」"], ["目錄暫時無法讀取"]],
    // 星曆拒絕重送不會改變結果。
    [{ code: "swiss_ephemeris_error", message: "server text" }, 500, [], ["重試", "再試"]],
    [{ code: "full_ephemeris_required", message: "server text" }, 422, [], ["重試", "再試"]],
    // 時間主星區塊會送年度請求：出生在可計算範圍尾端時，要算的那一年可能在 2399 年之後。
    // 輸入沒有錯，頁面也沒有過期，不得叫人重新載入。
    [issue("solar_return_outside_supported_year_range", "annual", "target_value"), 422,
      ["2399", "超出本站能計算的範圍", "沒有問題"], ["重新載入", "版本", "請檢查", "請核對"]],
  ]) {
    const message = formatApiError(detail, status);
    includes.forEach((pattern) => assert.ok(holds(message, pattern), `${JSON.stringify(detail)} 缺 ${pattern}：${message}`));
    excludes.forEach((pattern) => assert.ok(!holds(message, pattern), `${JSON.stringify(detail)} 不得有 ${pattern}：${message}`));
  }
});

test("每個閉集代碼都有專屬文案", () => {
  const codes = [
    "place_search_timeout", "json_invalid", "request_body_not_utf8", "duplicate_json_key",
    "not_found", "method_not_allowed", "unsupported_method", "unknown_api_path",
    "request_body_read_timeout", "request_headers_too_large", "conflicting_request_framing",
    "empty_request_body", "bad_request", "unauthorized", "undeclared_host", "request_validation_failed",
    "civil_time_basis_required", "civil_time_basis_not_applicable",
    "catalog_record_unknown", "catalog_location_mismatch",
  ];
  const rules = [
    "calendar_date_invalid", "second_finer_than_microsecond", "iana_name_required", "iana_timezone_unknown",
    "utc_offset_hours_required", "timezone_field_not_applicable_to_mode", "fold_requires_iana_mode",
    "civil_time_basis_zone_mismatch",
    "place_label_forbidden_codepoint", "place_label_has_no_base_character",
    "location_precision_not_accepted_for_source",
    "source_record_id_not_allowed_for_manual", "catalog_location_requires_label_and_record_id",
    "ayanamsa_unsupported", "sidereal_with_j2000_frame_not_supported",
    "leap_second_not_applicable_to_pre_1972_scale", "leap_second_requires_exact_utc_2359",
    "leap_second_not_in_bundled_table",
  ];
  for (const detail of [...codes.map((code) => ({ code })), ...rules.map((type) => issue(type))]) {
    const message = formatApiError(detail, 400);
    assert.notEqual(message, "網站沒有接受這次請求。請檢查輸入後再試一次。", JSON.stringify(detail));
    assert.notEqual(message, "輸入資料格式無效；請檢查後再試一次。", JSON.stringify(detail));
  }
});

test("錯誤動作：可重試的 503 依 Retry-After 建議重試；星曆拒絕不建議重試；不叫人修正輸入", () => {
  assert.deepStrictEqual(apiErrorActions(503, "5", null), ["約 5 秒後再試一次。", "若持續發生，請透過聯絡頁回報。"]);
  assert.equal(apiErrorActions(503, "5", "place_search_timeout")[0], "約 5 秒後再試一次。");
  assert.ok(!apiErrorActions(503, null, null).some((value) => value.includes("修正輸入")));
  for (const [code, status] of [["swiss_ephemeris_error", 500], ["full_ephemeris_required", 422]]) {
    const actions = apiErrorActions(status, null, code);
    assert.ok(!actions.some((action) => action.includes("重試") || action.includes("再試")), actions.join(" / "));
  }
});

// 宮位制在這個緯度或時刻一定算不出時（422 方法拒收），同一組輸入每次都會被拒；
// 「若持續發生」的回報指引對它是多餘的。其他錯誤照舊附上。
test("必然的方法拒收（422 宮位制不可用）不叫人透過聯絡頁回報；其他錯誤照舊", () => {
  const actions = apiErrorActions(422, null, "house_system_unavailable");
  assert.ok(!actions.some((action) => action.includes("聯絡頁")), actions.join(" / "));
  assert.deepStrictEqual(actions, ["修正輸入後再送出一次。"]);
  assert.ok(apiErrorActions(422, null, "nonexistent_local_time").some((a) => a.includes("聯絡頁")));
  assert.ok(apiErrorActions(503, null, null).some((a) => a.includes("聯絡頁")));
});

test("網路錯誤只有一種措辭，沒有私測 profile 或邀請者", () => {
  assert.equal(networkErrorMessage(), "連不上本站的計算功能。請確認網路連線後再試一次；若持續發生，請透過聯絡頁回報。");
  for (const retired of ["PROFILES", "validateClientConfiguration", "resolveProfileBounded"]) {
    assert.equal(ClientContext[retired], undefined, retired);
  }
});

// 後端逐字交代哪些詞被丟掉：被改寫過的查詢不得報成使用者自己的查詢。有截斷必說、沒截斷不吵。
test("地名查詢截斷時說出被略過與實際使用的詞，沒有截斷或收據自相矛盾時不說", () => {
  const truncated = placeQueryNotice({
    token_count: 8, max_search_tokens: 6, truncated: true,
    tokens_used: ["新竹縣", "竹北市", "光明", "六路", "東二段", "一號"],
    tokens_ignored: ["附近", "巷口"],
    reason: "token_limit_protects_against_broad_prefix_term_cost",
  });
  for (const pattern of [/附近 巷口/, /新竹縣/, /前 6 個詞/]) assert.match(truncated, pattern);
  for (const notice of [
    { token_count: 2, max_search_tokens: 6, truncated: false, tokens_used: ["台南"], tokens_ignored: [], reason: null },
    undefined, null, {},
    // truncated 為真卻沒列出被略過的詞：寧可不說，也不要生出一句「略過了「」」。
    { truncated: true, tokens_used: ["台南"], tokens_ignored: [] },
  ]) {
    assert.equal(placeQueryNotice(notice), null, JSON.stringify(notice));
  }
});

test("422 欄位錯誤對應到控制項 id", () => {
  for (const [detail, expected] of [
    [issue("value_error", "timezone"), ["timezone"]],
    [issue("missing", "timezone", "iana_name"), ["timezone"]],
    [issue("greater_than_equal", "datetime", "year"), ["birth-date"]],
    [issue("calendar_date_invalid", "datetime", "day"), ["birth-date"]],
    [issue("less_than_equal", "datetime", "hour"), ["hour"]],
    [issue("less_than_equal", "location", "latitude"), ["latitude"]],
    [issue("finite_number", "location", "altitude_m"), ["altitude"]],
    [issue("literal_error", "options", "partile_profile"), ["opt-partile_profile"]],
    [issue("aspect_orb_scale_requires_profile", "options"), ["opt-aspect_orb_profile"]],
    [issue("date_only_requires_zero_time"), ["hour", "minute", "second"]],
    [validationRefusal(
      { type: "less_than_equal", loc: ["body", "location", "latitude"] },
      { type: "less_than_equal", loc: ["body", "location", "longitude"] },
      { type: "less_than_equal", loc: ["body", "location", "latitude"] },
    ), ["latitude", "longitude"]],
    [{ code: "house_system_unavailable" }, ["opt-house_system"]],
    [{ code: "internal_server_error" }, []],
    [issue("value_error", "unknown_field"), []],
    // 重複鍵是頁面組 JSON 出錯，不是使用者填錯欄位。
    [{ code: "duplicate_json_key", issues: [{ type: "duplicate_json_key", loc: ["body", "datetime"] }] }, []],
    [null, []],
  ]) {
    const ids = fieldControlIds(detail);
    assert.deepEqual(ids, expected, JSON.stringify(detail));
    // 頁面上是否真有這個 id 由頁面層測試驗；這裡只要求它屬於模組宣告的集合。
    ids.filter((id) => !id.startsWith("opt-"))
      .forEach((id) => assert.ok(KNOWN_CONTROL_IDS.includes(id), `${id} 不在 KNOWN_CONTROL_IDS`));
  }
});

// 錯誤文案在排盤以外的情境（地名查詢、時間換算、年度時間主星）也要說得對：
// 5xx 不說「計算」、429 不叫人「依提示」（沒有提示時就沒有提示可依）；
// 2xx 卻讀不出答案（截斷的 JSON、HTML、204）是網站的問題，不叫人檢查輸入。
test("共用錯誤文案不怪使用者、不假設情境", () => {
  for (const status of [200, 204]) {
    const message = formatApiError(null, status);
    assert.ok(message.includes("不是你的輸入有問題"), `${status}: ${message}`);
    assert.doesNotMatch(message, /檢查輸入|修正輸入|請核對/, `${status}: ${message}`);
    assert.ok(!apiErrorActions(status, null, undefined).some((action) => /修正輸入/.test(action)), String(status));
  }
  assert.doesNotMatch(formatApiError(null, 429), /依提示/);
  for (const status of [500, 502, 503]) {
    assert.doesNotMatch(formatApiError(null, status), /計算/, String(status));
  }
  assert.equal(ClientContext.refusalStatus(422), "服務拒絕了這次計算。");
  for (const status of [429, 500, 502, 503]) {
    assert.doesNotMatch(ClientContext.refusalStatus(status), /拒絕/, String(status));
  }
});
