(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ClientContext = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const FIELD_LABELS = Object.freeze({
    datetime: "出生日期時間",
    year: "年份",
    month: "月份",
    day: "日期",
    hour: "小時",
    minute: "分鐘",
    second: "秒數",
    timezone: "時區",
    iana_name: "IANA 時區名稱",
    utc_offset_hours: "UTC 偏移",
    location: "出生地點",
    latitude: "緯度",
    longitude: "經度",
    altitude_m: "海拔",
    atmosphere: "大氣設定",
    pressure_hpa: "氣壓",
    temperature_c: "溫度",
  });

  // 以下文案由多個閉集代碼共用；每個代碼仍逐一列在兩張表裡，缺一個
  // 由 tests/integration/test_frontend_contract.py 對照後端的閉集抓到。
  // 頁面自己組 JSON：這類拒絕表示頁面版本過舊或傳輸出錯，不是使用者填錯。
  const STALE_PAGE_REQUEST = (
    "頁面送出的資料無法被服務解讀；這通常表示頁面版本過舊，請重新載入頁面後再試。"
  );
  const PAGE_SERVICE_MISMATCH = (
    "頁面與服務的版本不一致，服務不認得這個請求；請重新載入頁面後再試。"
  );
  // 本頁沒有固定 UTC 偏移的控制項；出路是地名查詢或手動的 IANA 欄位。
  const TIMEZONE_NAME_GUIDANCE = (
    "時區名稱無效；請用「地名查詢」選定地點，由目錄帶入時區，"
    + "或在「改為手動輸入座標與時區」裡的「IANA 時區名稱」欄輸入例如 Asia/Taipei 的名稱。"
  );
  const LOCATION_RECEIPT_MISMATCH = (
    "頁面送出的地點資料前後不一致；請重新用「地名查詢」選定地點，"
    + "或展開「改為手動輸入座標與時區」直接輸入。"
  );
  const LEAP_SECOND_GUIDANCE = "請把「秒」改為 0 到 59。";

  // 429 與 5xx 的狀態後備文案；邊緣（NGINX）對 /api 路徑回的閉集代碼
  // （edge_rate_limited、upstream_unavailable）在代碼表裡引用同一句。
  const RATE_LIMITED_MESSAGE = "服務目前忙碌，這不是你的輸入有問題；請依提示稍後重試。";
  const SERVER_UNAVAILABLE_MESSAGE = "服務暫時無法完成計算。請稍後重試；若持續發生，請聯絡服務管理者。";

  const ERROR_CODE_MESSAGES = Object.freeze({
    nonexistent_local_time: (
      // 後端的訊息會提到 fixed_offset，那對 API 消費者是對的；本頁沒有那個
      // 控制項，所以這裡只指向本頁真的能做的事。
      "這個本地時間在所選時區不存在（該時鐘從未指向這個時刻）；請核對出生紀錄的日期、"
      + "時刻與時區。"
    ),
    // 這裡只描述情況，不描述頁面能做什麼：頁面的能力改變時，這句話不會被通知。
    // 出路由 calculate.js 依「選擇區實際有沒有出現」導出。
    ambiguous_local_time_choice_required: (
      "這個時間在所選時區出現了兩次（時區在此改變了 UTC 偏移，例如日光節約時間結束或標準時變更），"
      + "服務需要知道是哪一次。"
    ),
    // 同上，只描述情況；指向選擇區的連結由 calculate.js 依選擇區有沒有出現導出。
    civil_time_basis_required: (
      "這個出生地的紀錄可能用北京時間，也可能用新疆時間，兩者相差 2 小時；"
      + "服務需要知道出生紀錄用的是哪一種，不替你猜。"
    ),
    // 本頁只在目錄標示為新疆的地點送出這一項；走到這裡表示頁面版本與服務不一致。
    civil_time_basis_not_applicable: PAGE_SERVICE_MISMATCH,
    // 本頁的選項叫「整宮」，而一定走得通的出路是宮位制選單的「不計算宮位」。
    // 引號裡的名稱必須是頁面上真的存在的控制項（client-context.test.cjs 逐一對照頁面）。
    house_system_unavailable: (
      "所選宮位制無法在這個緯度計算；請在「宮位制」選單改選「整宮」，或選「不計算宮位」。"
    ),
    // 重送不會改變結果，所以不說「稍後重試」；回應不說出生資料的哪一項
    // 超出範圍，所以也不點名控制項。
    full_ephemeris_required: (
      "這次計算需要的星曆資料超出服務內建的完整 Swiss Ephemeris 範圍；"
      + "服務不改用較低精度的替代結果，重送也不會改變。請核對出生日期、時刻與時區。"
    ),
    // 內建地名目錄開不起來時由 /api/places/search 回 503。通用的 5xx 措辭在
    // 這裡是錯的：這是地名查詢，不是計算。出路指向手動輸入，依產品原則：
    // 「找不到地點時保留手動座標／時區入口並提供可行動錯誤」。不建議重新
    // 載入——那是伺服器端的資料檔問題，重載不會改變它。
    place_catalog_unavailable: (
      "內建地名目錄暫時無法讀取，這次查不了地點。這不是你的輸入有問題；"
      + "請展開「改為手動輸入座標與時區」輸入座標與時區，或稍後重試。"
    ),
    unsupported_media_type: "送出的資料格式不受支援，請重新載入頁面後再試。",
    invalid_content_length: "送出的資料長度資訊無效，請重新載入頁面後再試。",
    request_body_too_large: "送出的資料超過服務允許大小，請重新載入頁面後再試。",
    // 選配模組的星曆失敗已在模組內標為不可用，走到這裡的是核心命盤
    // 本身；同一組輸入重送會得到同一個錯誤，所以不再建議「稍後重試」。
    swiss_ephemeris_error: (
      "天文計算函式庫無法完成這次計算；同一組輸入重送通常會得到相同結果。"
      + "請核對出生日期、時刻與地點；若確認無誤，請聯絡服務管理者。"
    ),
    internal_server_error: SERVER_UNAVAILABLE_MESSAGE,
    edge_rate_limited: RATE_LIMITED_MESSAGE,
    upstream_unavailable: SERVER_UNAVAILABLE_MESSAGE,
    request_capacity_exhausted: (
      "服務目前忙碌，這不是你的輸入有問題；請稍後重試。"
    ),
    compute_capacity_exhausted: (
      "計算佇列仍在忙碌，暫時無法開始這次計算；請依下方提示稍後重試。"
    ),
    // 語句預算中斷不是目錄壞了；可以重試，出路同樣是手動輸入。
    place_search_timeout: (
      "地名查詢這次花太久而被中止，這不是你的輸入有問題；請輸入更完整的地名後再試，"
      + "或展開「改為手動輸入座標與時區」直接輸入。"
    ),
    // 換算助手只在本頁時區屬於這四地時送出；走到這裡多半是時區欄在送出後改了。
    time_conversion_zone_not_covered: (
      "換算助手目前只涵蓋臺灣、香港、澳門與中國大陸的時區；其他時區請直接按「開始排盤」，"
      + "計算結果會記下換算出的世界時與時區資料庫版本。"
    ),
    request_validation_failed: "部分輸入無法驗證；請檢查必填欄位與格式。",
    json_invalid: STALE_PAGE_REQUEST,
    request_body_not_utf8: STALE_PAGE_REQUEST,
    duplicate_json_key: STALE_PAGE_REQUEST,
    bad_request: STALE_PAGE_REQUEST,
    conflicting_request_framing: STALE_PAGE_REQUEST,
    empty_request_body: STALE_PAGE_REQUEST,
    request_headers_too_large: STALE_PAGE_REQUEST,
    request_body_read_timeout: "送出資料的傳輸逾時；請確認網路連線後再送出一次。",
    undeclared_host: PAGE_SERVICE_MISMATCH,
    unknown_api_path: PAGE_SERVICE_MISMATCH,
    unsupported_method: PAGE_SERVICE_MISMATCH,
    not_found: PAGE_SERVICE_MISMATCH,
    method_not_allowed: PAGE_SERVICE_MISMATCH,
    unauthorized: PAGE_SERVICE_MISMATCH,
  });

  const VALIDATION_REASON_MESSAGES = Object.freeze({
    approximate_hour_requires_zero_subhour: (
      "「只知道約略小時」只能輸入整點；請將分鐘與秒數改為 0，或改選「精確到分鐘」。"
    ),
    date_only_requires_zero_time: (
      "「只知道日期」不能同時指定時分秒；請清除時間，或改選較精確的出生時間類型。"
    ),
    // 以下五則在本頁多半到不了（頁面送出前就依選項目錄的互斥規則擋下），但它們與可到達的
    // 訊息是同一張表，路徑一打開就會出現，所以同樣只引用頁面上真的存在的控制項。
    // 本頁沒有「計算中心」控制項，月亮衝突只能從「月亮位置口徑」解。
    moon_profile_center_conflict: (
      "「月亮位置口徑」的「僅月亮採站心」只能搭配地心計算；"
      + "請把「月亮位置口徑」改回「跟隨整體計算中心」。"
    ),
    body_selection_conflict: (
      "「天體集合預設」選「古典七政」時，不能同時勾選「外行星」、「凱龍星」、「恆星」或"
      + "「Lilith 與 Priapus（目前一起計算）」；請改回「自訂」，或取消這些勾選。"
    ),
    aspect_orb_scale_requires_profile: (
      "設定「容許度縮放（%）」前，請先在「容許度表」選一套具名容許度。"
    ),
    aspect_orb_sources_conflict: (
      "「固定容許度（度）」與「容許度表」不能同時使用；請保留其中一種。"
    ),
    aspect_angle_orb_requires_angles: (
      "設定「軸點容許度（度）」前，請先勾選「相位納入軸點」。"
    ),
    // 以下每一則對應 schemas.REQUEST_VALIDATION_RULES 的一個代碼。
    calendar_date_invalid: "出生日期不存在（例如 2 月 30 日）；請核對「出生日期」。",
    second_finer_than_microsecond: "「秒」最多到小數第六位（微秒）；請刪去多餘的小數位。",
    iana_timezone_unknown: TIMEZONE_NAME_GUIDANCE,
    iana_name_required: TIMEZONE_NAME_GUIDANCE,
    // 本頁只送 IANA 時區；固定偏移相關的拒絕只會來自過期的頁面。
    utc_offset_hours_required: STALE_PAGE_REQUEST,
    timezone_field_not_applicable_to_mode: STALE_PAGE_REQUEST,
    fold_requires_iana_mode: STALE_PAGE_REQUEST,
    // 本頁依所選的那一種填入時區；兩者不一致只會來自過期的頁面。
    civil_time_basis_zone_mismatch: STALE_PAGE_REQUEST,
    place_label_forbidden_codepoint: (
      "地點名稱含有不可顯示的控制字元；請重新用「地名查詢」選定地點。"
    ),
    location_precision_not_accepted_for_source: LOCATION_RECEIPT_MISMATCH,
    source_record_id_not_allowed_for_manual: LOCATION_RECEIPT_MISMATCH,
    catalog_location_requires_label_and_record_id: LOCATION_RECEIPT_MISMATCH,
    ayanamsa_unsupported: "所選的「歲差校正」不在服務支援的清單內；請重新載入頁面後再選一次。",
    // 本頁不送 ecliptic_frame，這個組合在介面上到不了；文案只描述情況，
    // 不點名任何控制項。
    sidereal_with_j2000_frame_not_supported: (
      "恆星黃道不能與 J2000 黃道座標框架一起使用；服務拒絕這個組合，"
      + "而不輸出一個 ayanamsa 收據與實際扣除量不一致的結果。"
    ),
    leap_second_not_applicable_to_pre_1972_scale: (
      "秒數 60 只存在於 1972 年起以閏秒維持的 UTC；" + LEAP_SECOND_GUIDANCE
    ),
    leap_second_requires_exact_utc_2359: (
      "秒數 60 只接受精確出生時間、且換算成 UTC 後為 23:59:60 的已知閏秒；"
      + LEAP_SECOND_GUIDANCE
    ),
    leap_second_not_in_bundled_table: (
      "這個時刻換算成 UTC 後不是服務內建表中的閏秒；" + LEAP_SECOND_GUIDANCE
    ),
    // 換算助手送出的時區沒有 fold；收到這一項表示頁面版本與服務不一致。
    fold_not_accepted_by_time_conversion: STALE_PAGE_REQUEST,
    leap_second_not_accepted_by_time_conversion: (
      "換算助手不核對秒數 60（閏秒）；核對時請把「秒」改為 0 到 59，計算時仍可依紀錄填 60。"
    ),
  });

  function fieldLabel(location) {
    if (!Array.isArray(location)) return "輸入資料";
    for (let index = location.length - 1; index >= 0; index -= 1) {
      const key = String(location[index]);
      if (FIELD_LABELS[key]) return FIELD_LABELS[key];
    }
    return "輸入資料";
  }

  function validationGuidance(issue) {
    const location = Array.isArray(issue && issue.loc) ? issue.loc : [];
    const locationKeys = new Set(location.map(String));
    const label = fieldLabel(location);
    const type = issue && typeof issue.type === "string" ? issue.type : "";

    if (Object.prototype.hasOwnProperty.call(VALIDATION_REASON_MESSAGES, type)) {
      return VALIDATION_REASON_MESSAGES[type];
    }

    if (type === "missing") return `${label}尚未填寫。`;
    if (type === "extra_forbidden") {
      return "頁面送出了目前版本不支援的欄位，請重新載入後再試。";
    }
    if (locationKeys.has("timezone") || locationKeys.has("iana_name")) {
      return TIMEZONE_NAME_GUIDANCE;
    }
    if (locationKeys.has("datetime")) {
      // 範圍違反必須先分流出去：1800-01-01 這個日期存在，後端回的是
      // datetime.year 的 greater_than_equal，問題是產品只算 1900–2399。說成
      // 「請確認日期確實存在」會把使用者送去檢查一個沒有問題的地方。
      if (type.includes("greater_than") || type.includes("less_than")) {
        if (locationKeys.has("year")) {
          return "出生年份超出本產品目前計算的範圍；日期欄位下方註明了支援的西元年區間。";
        }
        return `${label}超出允許範圍；請參考該欄位下方的數字範圍說明。`;
      }
      return "出生日期時間無效；請確認日期確實存在，且時間數字在允許範圍內。";
    }
    if (locationKeys.has("latitude")) {
      return "緯度無效；請輸入 -90 到 90 的十進位度數。";
    }
    if (locationKeys.has("longitude")) {
      return "經度無效；請輸入 -180 到 180 的十進位度數。";
    }
    if (
      type.includes("greater_than")
      || type.includes("less_than")
      || type.includes("finite_number")
    ) {
      return `${label}超出允許範圍；請檢查欄位旁的格式說明。`;
    }
    return `${label}格式無效；請檢查後再試。`;
  }

  // 每個拒絕都是 { code, message, ... }；只有 request_validation_failed 的 issues
  // 是欄位發現。裸陣列是舊形狀，服務不再送出，這裡也不再把它當成欄位發現。
  function validationIssues(detail) {
    return detail
      && typeof detail === "object"
      && !Array.isArray(detail)
      && detail.code === "request_validation_failed"
      && Array.isArray(detail.issues)
      ? detail.issues
      : [];
  }

  function formatApiError(detail, statusCode) {
    const issues = validationIssues(detail);
    if (issues.length > 0) {
      return validationGuidance(issues[0]);
    }
    // 地理極點沒有唯一上升點（houses.py unique_ascendant_undefined）：整宮也算不出來，
    // 唯一出路是「不計算宮位」，不能照一般宮位拒絕建議改選整宮。
    if (
      detail
      && typeof detail === "object"
      && detail.code === "house_system_unavailable"
      && detail.reason_code === "unique_ascendant_undefined"
    ) {
      return (
        "這個緯度沒有唯一的上升點（地理極點），任何宮位制都無法計算；"
        + "請在「宮位制」選單選「不計算宮位」。"
      );
    }
    if (
      detail
      && typeof detail === "object"
      && typeof detail.code === "string"
      && Object.prototype.hasOwnProperty.call(ERROR_CODE_MESSAGES, detail.code)
    ) {
      return ERROR_CODE_MESSAGES[detail.code];
    }
    if (statusCode === 413) return "送出的資料超過服務允許大小，請重新載入頁面後再試。";
    if (statusCode === 415) return "送出的資料格式不受支援，請重新載入頁面後再試。";
    if (statusCode === 422) return "部分輸入無法驗證；請檢查必填欄位與格式。";
    if (statusCode === 429) return RATE_LIMITED_MESSAGE;
    if (statusCode >= 500) {
      return SERVER_UNAVAILABLE_MESSAGE;
    }
    return `服務拒絕本次請求（HTTP ${statusCode}）。請檢查輸入後再試。`;
  }

  // 伺服器 422 點名的欄位 → 頁面控制項 id。只列確定的對應；
  // 對不到的欄位回空陣列（錯誤訊息照常顯示，只是不標任何欄位）。選項一律是 opt-<key>，
  // 由 calculate.js 依選項目錄的 rendered_by 換成看得見的那個控制項。
  const DATETIME_CONTROL_IDS = Object.freeze({
    year: "date", month: "date", day: "date", hour: "hour", minute: "minute", second: "second",
  });
  const LOCATION_CONTROL_IDS = Object.freeze({
    latitude: "latitude", longitude: "longitude", altitude_m: "altitude",
  });
  const REASON_CONTROL_IDS = Object.freeze({
    approximate_hour_requires_zero_subhour: ["minute", "second"],
    date_only_requires_zero_time: ["hour", "minute", "second"],
    moon_profile_center_conflict: ["opt-moon_position_profile"],
    body_selection_conflict: ["opt-body_selection_preset"],
    aspect_orb_scale_requires_profile: ["opt-aspect_orb_profile"],
    aspect_orb_sources_conflict: ["opt-aspect_fixed_orb_degrees", "opt-aspect_orb_profile"],
    aspect_angle_orb_requires_angles: ["opt-aspect_include_angles"],
    ayanamsa_unsupported: ["ayanamsa"],
  });
  const CODE_CONTROL_IDS = Object.freeze({
    house_system_unavailable: ["opt-house_system"],
  });
  const TIMEZONE_CONTROL_ID = "timezone";
  const DATE_CONTROL_ID = "date";
  // 這個模組可能點名的每一個固定控制項 id，由上面幾張表導出（opt-<key> 另由
  // 選項目錄決定）。頁面層測試拿它對開機後的 DOM 驗證，不另抄一份清單。
  const KNOWN_CONTROL_IDS = Object.freeze([...new Set([
    TIMEZONE_CONTROL_ID,
    DATE_CONTROL_ID,
    ...Object.values(DATETIME_CONTROL_IDS),
    ...Object.values(LOCATION_CONTROL_IDS),
    ...Object.values(REASON_CONTROL_IDS).flat(),
    ...Object.values(CODE_CONTROL_IDS).flat(),
  ])].filter((id) => !id.startsWith("opt-")));

  function issueControlIds(issue) {
    if (!issue || typeof issue !== "object") return [];
    const type = typeof issue.type === "string" ? issue.type : "";
    if (Object.prototype.hasOwnProperty.call(REASON_CONTROL_IDS, type)) {
      return REASON_CONTROL_IDS[type];
    }
    const location = Array.isArray(issue.loc) ? issue.loc.map(String) : [];
    const [, section, field] = location;
    if (section === "timezone") return [TIMEZONE_CONTROL_ID];
    if (section === "datetime") {
      if (!field) return [DATE_CONTROL_ID];
      return Object.prototype.hasOwnProperty.call(DATETIME_CONTROL_IDS, field)
        ? [DATETIME_CONTROL_IDS[field]] : [];
    }
    if (section === "location") {
      return Object.prototype.hasOwnProperty.call(LOCATION_CONTROL_IDS, field)
        ? [LOCATION_CONTROL_IDS[field]] : [];
    }
    if (section === "options" && field && /^[a-z][a-z0-9_]*$/.test(field)) {
      return [`opt-${field}`];
    }
    return [];
  }

  function fieldControlIds(detail) {
    const ids = [];
    const add = (list) => list.forEach((id) => { if (!ids.includes(id)) ids.push(id); });
    validationIssues(detail).forEach((issue) => add(issueControlIds(issue)));
    if (
      detail && typeof detail === "object" && typeof detail.code === "string"
      && Object.prototype.hasOwnProperty.call(CODE_CONTROL_IDS, detail.code)
    ) {
      add(CODE_CONTROL_IDS[detail.code]);
    }
    return ids;
  }

  function networkErrorMessage() {
    return "無法連線到命盤計算服務。請確認網路連線後再試；若持續發生，請透過聯絡頁回報。";
  }

  // 這兩種拒絕重送不會改變結果；建議「稍後重試」只會讓使用者反覆送出同一個請求。
  const NON_RETRYABLE_SERVER_REFUSALS = Object.freeze([
    "full_ephemeris_required",
    "swiss_ephemeris_error",
  ]);

  function apiErrorActions(statusCode, retryAfterHeader, code) {
    const actions = [];
    if (NON_RETRYABLE_SERVER_REFUSALS.includes(code)) {
      actions.push("核對出生日期、時刻與地點後再送出。");
    } else if (statusCode === 429 || statusCode >= 500) {
      const raw = typeof retryAfterHeader === "string" ? retryAfterHeader.trim() : "";
      const seconds = /^\d+$/.test(raw) ? Number(raw) : 0;
      actions.push(
        seconds >= 1 && seconds <= 3600
          ? `約 ${seconds} 秒後重試。`
          : "稍後重試。"
      );
    } else {
      actions.push("修正輸入後再送出一次。");
    }
    if (statusCode === 413 || statusCode === 415) actions.push("重新載入頁面。");
    actions.push("若持續發生，請透過聯絡頁回報。");
    return actions;
  }

  /**
   * 地名查詢的 token 截斷告知。
   *
   * 後端會把超過上限的詞丟掉，並在 `query` 收據裡逐字交代
   * （`truncated`、`tokens_used`、`tokens_ignored`）。只讀 `results` 是不夠
   * 的：一個被砍過詞的查詢無論回「找到 N 筆」還是「沒有符合的地名」，都是
   * **在使用者不知情的狀況下，把一個被改寫過的查詢報成他自己的查詢**。
   *
   * 回傳 null 表示沒有截斷，呼叫端不必顯示任何東西。
   *
   * 這串文字只進畫面，不得進 log：它是使用者輸入的自由文字，屬
   * `PRIVACY_LOGGING_POLICY` 的最高敏感類別。
   */
  function placeQueryNotice(queryReceipt) {
    if (!queryReceipt || typeof queryReceipt !== "object") return null;
    if (queryReceipt.truncated !== true) return null;
    const ignored = Array.isArray(queryReceipt.tokens_ignored)
      ? queryReceipt.tokens_ignored
      : [];
    if (!ignored.length) return null;
    const used = Array.isArray(queryReceipt.tokens_used)
      ? queryReceipt.tokens_used
      : [];
    const limit = queryReceipt.max_search_tokens;
    const limitText = Number.isFinite(limit) ? `前 ${limit} 個詞` : "前幾個詞";
    return (
      `這次只用了${limitText}查詢：「${used.join(" ")}」。`
      + `略過了「${ignored.join(" ")}」，所以結果不涵蓋這些字。`
      + "想更精確，請改用較短的地名，或直接在下方手動輸入座標與時區。"
    );
  }

  return Object.freeze({
    formatApiError,
    fieldControlIds,
    KNOWN_CONTROL_IDS,
    apiErrorActions,
    networkErrorMessage,
    placeQueryNotice,
  });
});
