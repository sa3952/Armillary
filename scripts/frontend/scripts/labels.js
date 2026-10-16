(function attachLabels(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ArmillaryLabels = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildLabels() {
  "use strict";

  // 閉集代碼 → 中文標籤：下面這些詞彙表，畫面與匯出共用這一份。
  //
  // 後端與目錄回的是閉集代碼（geonames_cities500、place_representative_point、W…）。
  // 代碼原樣放進看得見、念得出的文字，使用者聽到的是一串底線英文；同一個代碼各處各自
  // 翻譯，就有兩種說法（宮位制選單寫「整宮」、結果寫「Whole Sign」）。所以這裡列出的
  // 詞彙表只在這裡翻譯，消費端經 label() 取用。這不是全站唯一的翻譯處：view-model、
  // exporters、calculate、client-context 與 timelords-model 各自還有自己代碼的中文表。
  // 這裡每一組的鍵集合由整合測試對照後端的閉集（schemas.py 的 Literal、出貨目錄的實際值、
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
      spelling_fallback: "原字查無結果，拼法相近（最多差兩個字母）",
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
    // 以人名命名的宮位制寫原文，不另取中文音譯；Equal 是方法名，譯成「等分宮」（不是「等分宮制」：
    // 計算口徑摘要會在中文名後接「制」）。
    house_system: Object.freeze({
      W: "整宮",
      P: "Placidus",
      R: "Regiomontanus",
      B: "Alcabitius",
      O: "Porphyry",
      E: "等分宮",
      C: "Campanus",
    }),
    // 時區的中文地名。計算頁時區欄的建議清單由這一組產生（依此順序），結果與匯出的時區列
    // 也取這一組；不在表裡的時區照印 IANA 名。
    timezone_place: Object.freeze({
      "Asia/Taipei": "臺北",
      "Asia/Shanghai": "上海",
      "Asia/Tokyo": "東京",
      "Asia/Hong_Kong": "香港",
      "America/New_York": "紐約",
      "Europe/London": "倫敦",
      "Europe/Zurich": "蘇黎世",
      "Australia/Sydney": "雪梨",
    }),
    // 黃道十二星座，依黃經序（0＝牡羊）。後端在尊貴模組回英文星座鍵、在其餘模組回
    // sign_position 的星座索引；結果表格與星盤圖都取這一組（全站寫「水瓶」）。
    zodiac_sign: Object.freeze({
      aries: "牡羊", taurus: "金牛", gemini: "雙子", cancer: "巨蟹",
      leo: "獅子", virgo: "處女", libra: "天秤", scorpio: "天蠍",
      sagittarius: "射手", capricorn: "摩羯", aquarius: "水瓶", pisces: "雙魚",
    }),
    // 後端對同一組代碼給的英文名（app.domain_catalog.HOUSE_SYSTEMS，一對一）。回應只帶名稱
    // 不帶代碼時，由這一組找回代碼；兩邊一致由整合測試對照。
    house_system_backend_name: Object.freeze({
      W: "Whole Sign",
      P: "Placidus",
      R: "Regiomontanus",
      B: "Alcabitius",
      O: "Porphyry",
      E: "Equal",
      C: "Campanus",
    }),
    // 後端天體的名稱（app.config 的 CLASSICAL_BODIES、OUTER_BODIES、MODERN_MINOR_BODIES，一對一）。
    // 結果表格只帶名稱；名稱前的符號由這一組找回是哪一顆星。兩邊一致由整合測試對照。
    body_backend_name: Object.freeze({
      sun: "太陽", moon: "月亮", mercury: "水星", venus: "金星", mars: "火星",
      jupiter: "木星", saturn: "土星", uranus: "天王星", neptune: "海王星", pluto: "冥王星",
      chiron: "凱龍星",
    }),
    // 後端月交點的名稱（app.domain_catalog.NODE_BODIES 與 core/bodies.py 的南交點，一對一）。認點一律讀回應
    // 的 key；這一組只給表格的名稱格補符號（calculate.js）。兩邊一致由整合測試對照。
    node_backend_name: Object.freeze({
      true_node: "北交點(密切)",
      mean_node: "北交點(平均)",
      true_south_node: "南交點(密切)",
      mean_south_node: "南交點(平均)",
    }),
    // 後端月球拱點的名稱（app.domain_catalog.LUNAR_APSIDES，一對一）。同上，只給表格的名稱格補符號。
    // 兩邊一致由整合測試對照。
    lunar_apsis_backend_name: Object.freeze({
      mean_lilith: "平均黑月 Lilith",
      natural_lilith: "自然黑月 Lilith",
      natural_priapus: "自然月球近地點 Priapus",
    }),
    // 出處核到哪一層（後端 core/source_reading.py 的閉集，依此順序）：結果頁每一條出處的句尾
    // 「核到：…」都取這一組。任何譯本（包括阿拉伯著作的中世紀拉丁文譯本）都是「已讀譯本」，
    // 譯成哪一種語言寫在每一條句尾的括號裡（英譯、拉丁文譯本）。
    source_reading: Object.freeze({
      original_language_read: "已讀原文",
      translation_read: "已讀譯本",
      secondary_only: "轉引（只讀到二手）",
      bibliographic_only: "只見書目",
    }),
    // 四軸的列名（後端 angles.sign_positions 的鍵，依此順序）。軸點表的列名與圖表連動的鍵都取這一組。
    angle_label: Object.freeze({
      asc: "上升 ASC",
      mc: "中天 MC",
      desc: "下降 DSC",
      ic: "天底 IC",
    }),
  });

  // 每一組詞彙表在「未識別的<角色>（代碼）」裡的角色名。
  const ROLES = Object.freeze({
    birth_time_precision: "出生時刻把握程度",
    place_source: "目錄來源",
    place_source_short: "目錄來源",
    location_precision: "位置精度",
    coordinate_semantics: "座標語義",
    match_tier: "比對層級",
    civil_time_basis: "鐘點依據",
    civil_time_regime: "時制",
    house_system: "宮位制",
    timezone_place: "時區",
    zodiac_sign: "星座",
    house_system_backend_name: "宮位制",
    body_backend_name: "天體",
    node_backend_name: "月交點",
    lunar_apsis_backend_name: "月球拱點",
    source_reading: "核對層級",
    angle_label: "軸點",
  });

  /** 表裡自身屬性的值；原型鏈上的名字不是閉集成員。不在表裡回 null。 */
  function ownLabel(table, code) {
    return typeof code === "string" && Object.hasOwn(table, code) ? table[code] : null;
  }

  /**
   * 閉集代碼的中文。有對應印中文；沒有對應印「未識別的<角色>（代碼）」——缺對應是看得見的
   * 缺陷，不是資料。值不像代碼（例如一段後端原文）時只寫「未識別的<角色>」，原文不上畫面。
   */
  function closedLabel(code, table, role) {
    const found = ownLabel(table, code);
    if (found !== null) return found;
    return /^[A-Za-z][A-Za-z0-9_.]*$/.test(String(code || "")) ? `未識別的${role}（${code}）` : `未識別的${role}`;
  }

  /** 代碼的中文標籤。未知的詞彙表是程式錯誤，直接拒絕；詞彙表裡沒有的代碼不猜（closedLabel）。 */
  function label(vocabulary, code) {
    if (!Object.hasOwn(VOCABULARIES, vocabulary)) {
      throw new Error(`沒有這個代碼詞彙表：${vocabulary}`);
    }
    return closedLabel(code, VOCABULARIES[vocabulary], ROLES[vocabulary]);
  }

  /**
   * 出處的一行：[方法出處登錄裡那條引文的開頭, 畫面的字, 核到哪一層（後端閉集）, 句尾補註]。
   * 句尾「核到：…」取 source_reading，每一種層級全站同一個說法。沒有層級的一行（指向方法頁）照印。
   */
  function sourceLine([, text, reading, note]) {
    return reading ? `${text}核到：${label("source_reading", reading)}${note || ""}。` : text;
  }

  /** 由後端名稱找回它在這一組裡的代碼或鍵；不在表裡回 null。 */
  function keyForName(table, name) {
    const found = Object.entries(table).find(([, backendName]) => backendName === name);
    return found ? found[0] : null;
  }

  /** 由後端的宮位制名稱找回代碼。 */
  const houseSystemCodeForName = (name) => keyForName(VOCABULARIES.house_system_backend_name, name);

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

  /** 時區列的寫法：表裡有中文地名時寫「臺北（Asia/Taipei）」，否則照印原值。 */
  function timezoneText(name) {
    const place = ownLabel(VOCABULARIES.timezone_place, name);
    return place ? `${place}（${name}）` : name;
  }

  /**
   * 國家或地區代碼（ISO 3166-1 alpha-2）的中文短名。名稱取瀏覽器內建的 CLDR 資料
   * （Intl.DisplayNames，zh-TW），不在這裡另抄一份兩百多個國家的對照表；瀏覽器沒有
   * 這項功能或不認得代碼時照印代碼。沒有代碼回 null。
   */
  function regionName(code) {
    if (typeof code !== "string" || !code) return null;
    try {
      const names = new Intl.DisplayNames(["zh-TW"], { type: "region", style: "short", fallback: "none" });
      return names.of(code) || code;
    } catch (_error) {
      return code;
    }
  }

  return Object.freeze({
    VOCABULARIES, ROLES, label, ownLabel, closedLabel, sourceLine, houseSystemCodeForName, houseSystemText,
    timezoneText, regionName,
  });
});
