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
    // OptionsInput.house_system；表單選單與結果都取這一組。
    house_system: Object.freeze({
      W: "整宮",
      P: "Placidus",
      R: "Regiomontanus",
      B: "Alcabitius",
    }),
    // 後端對同一組代碼給的英文名（app.config.HOUSE_SYSTEMS，一對一）。回應只帶名稱
    // 不帶代碼時，由這一組找回代碼；兩邊一致由整合測試對照。
    house_system_backend_name: Object.freeze({
      W: "Whole Sign",
      P: "Placidus",
      R: "Regiomontanus",
      B: "Alcabitius",
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

  return Object.freeze({ VOCABULARIES, label, houseSystemCodeForName });
});
