(function attachLabels(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ArmillaryLabels = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildLabels() {
  "use strict";

  // 閉集代碼 → 中文標籤，畫面與匯出共用這一份。
  //
  // 後端與目錄回的是閉集代碼（geonames_cities500、place_representative_point、W…）。
  // 代碼原樣放進看得見、念得出的文字，使用者聽到的是一串底線英文；各處各自翻譯，
  // 同一個代碼就有兩種說法（宮位制選單寫「整宮」、結果寫「Whole Sign」）。所以翻譯只在
  // 這裡，消費端一律經 label() 取用；原始代碼只出現在明示為技術細節或驗算資料的位置。
  // 每一組的鍵集合由整合測試對照後端的閉集（schemas.py 的 Literal、出貨目錄的實際值、
  // 真實目錄查詢回的值），後端多了代碼而這裡沒有，測試就紅。
  const VOCABULARIES = Object.freeze({
    // 後端 schemas.py 的 birth_time_precision；標籤與 calculate.html 三個選項的粗體字同字。
    birth_time_precision: Object.freeze({
      exact: "精確到分鐘",
      approximate_hour: "只知道約略小時",
      date_only: "只知道日期",
    }),
    // 地名目錄的來源（LocationInput.location_source 去掉 manual）。
    place_source: Object.freeze({
      geonames_cities500: "GeoNames 城市資料（人口 500 以上）",
      taiwan_moi_place_names: "內政部地名資料",
    }),
    // 同一組來源的短名，用在地名查詢結果那一行。
    place_source_short: Object.freeze({
      geonames_cities500: "GeoNames",
      taiwan_moi_place_names: "內政部地名",
    }),
    // LocationInput.location_precision。
    location_precision: Object.freeze({
      user_supplied_coordinates: "使用者輸入的座標",
      place_representative_point: "地點的代表點",
      settlement_representative_point: "聚落的代表點",
      administrative_area_representative_point: "行政區的代表點",
      unknown: "不明",
    }),
    // 地名查詢結果的 coordinate_semantics。
    coordinate_semantics: Object.freeze({
      dataset_representative_point_not_birth_address: "目錄資料的代表點，不是出生地址",
    }),
    // 地名查詢結果的 match_tier（排序層級）。
    match_tier: Object.freeze({
      exact_name: "地名完全相符",
      name_prefix: "地名開頭相符",
      other_field: "別名或行政區欄位相符",
    }),
    // TimezoneInput.civil_time_basis：出生紀錄用的是哪一種鐘點（新疆的地點）。
    civil_time_basis: Object.freeze({
      beijing_time: "北京時間",
      xinjiang_time: "新疆時間",
    }),
    // 換算助手回應的 rule.regime（backend/app/core/civil_time_sources.py REGIMES）。
    civil_time_regime: Object.freeze({
      local_mean_time: "地方平時（依經度推算）",
      standard_time: "標準時",
      summer_time: "夏令時間（日光節約時間）",
      japan_standard_time: "日本中央標準時",
      wartime_time: "戰時時間",
    }),
    // OptionsInput.house_system；表單選單與結果都取這一組。
    house_system: Object.freeze({
      W: "整宮",
      P: "Placidus",
      R: "Regiomontanus",
      B: "Alcabitius",
    }),
    // 黃道十二星座，依黃經序（0＝牡羊）。後端在尊貴模組回英文星座鍵、在其餘模組回
    // sign_position 的星座索引；結果表格與星盤圖都取這一組（全站寫「水瓶」）。
    zodiac_sign: Object.freeze({
      aries: "牡羊", taurus: "金牛", gemini: "雙子", cancer: "巨蟹",
      leo: "獅子", virgo: "處女", libra: "天秤", scorpio: "天蠍",
      sagittarius: "射手", capricorn: "摩羯", aquarius: "水瓶", pisces: "雙魚",
    }),
    // 後端對同一組代碼給的英文名（app.config.HOUSE_SYSTEMS，一對一）。回應只帶名稱
    // 不帶代碼時，由這一組找回代碼；兩邊一致由整合測試對照。
    house_system_backend_name: Object.freeze({
      W: "Whole Sign",
      P: "Placidus",
      R: "Regiomontanus",
      B: "Alcabitius",
    }),
    // 後端月交點的名稱（app.config.NODE_BODIES 與 core/bodies.py 的南交點，一對一）。頁面投影的
    // 交點只帶名稱不帶鍵；星盤圖由這一組找回是哪一種交點。兩邊一致由整合測試對照。
    node_backend_name: Object.freeze({
      true_node: "北交點(密切)",
      mean_node: "北交點(平均)",
      true_south_node: "南交點(密切)",
      mean_south_node: "南交點(平均)",
    }),
  });

  /**
   * 代碼的中文標籤。未知的詞彙表是程式錯誤，直接拒絕；詞彙表裡沒有的代碼不猜，照實說
   * 「未識別」並附上代碼，讀者至少知道那不是一個已知值。
   */
  function label(vocabulary, code) {
    if (!Object.prototype.hasOwnProperty.call(VOCABULARIES, vocabulary)) {
      throw new Error(`沒有這個代碼詞彙表：${vocabulary}`);
    }
    const table = VOCABULARIES[vocabulary];
    return typeof code === "string" && Object.prototype.hasOwnProperty.call(table, code)
      ? table[code]
      : `未識別（${code}）`;
  }

  /** 由後端的宮位制名稱找回代碼；不在表裡回 null。 */
  function houseSystemCodeForName(name) {
    const found = Object.entries(VOCABULARIES.house_system_backend_name)
      .find(([, backendName]) => backendName === name);
    return found ? found[0] : null;
  }

  /** 由後端的月交點名稱找回鍵；不在表裡回 null。 */
  function nodeKeyForName(name) {
    const found = Object.entries(VOCABULARIES.node_backend_name).find(([, backendName]) => backendName === name);
    return found ? found[0] : null;
  }

  /**
   * 宮位制的名稱：以代碼取中文名，與表單選單同一個出處；後端給的名稱不同於中文名時附在
   * 括號裡（例：整宮（Whole Sign））。頁面投影只帶名稱，代碼由後端名稱找回。
   * 代碼與名稱都沒有時回 null，由呼叫端決定怎麼寫「沒有」。
   */
  function houseSystemText(givenCode, name) {
    const code = givenCode || houseSystemCodeForName(name);
    if (!code) return name || null;
    const zh = label("house_system", code);
    return name && name !== zh ? `${zh}（${name}）` : zh;
  }

  return Object.freeze({ VOCABULARIES, label, houseSystemCodeForName, houseSystemText, nodeKeyForName });
});
