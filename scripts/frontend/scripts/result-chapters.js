(function attachResultChapters(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.ResultChapters = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildResultChapters() {
  "use strict";

  // 計算頁的三種模式與結果的六章，兩張表都只在這裡。
  //
  // 模式只是一組預先勾好的選項，不是另一種計算：送出的仍是同一份 OptionsInput，
  // 收據照舊列出實際生效的每一個選項。模式不記住（不寫任何瀏覽器儲存）；站內連結
  // 可以帶 ?mode=…（落地頁另帶 &technique=…），頁面讀一次就從網址拿掉。
  //
  // 章是畫面上的分組，不是資料順序：每章內的區段照 view-model 清單的先後，匯出的
  // 區段順序與形狀完全不受影響。新區段要放進某一章，在 SECTION_CHAPTERS 加一列即可；
  // 沒有列的區段跟著 view-model 清單裡排在它前面、最近的那一個有列的區段走，不會從
  // 畫面上消失（前提是新區段照「接在同類之後」插入清單）。

  const MODE_IDS = Object.freeze(["quick", "classical", "custom"]);
  // 站內落地頁（/zh-TW/calculate/<技法>）帶的 technique：時間主星一章先選哪一種。閉集，與
  // timelords-model.js 摘要卡的 key 相同（十年期沒有卡，取時間軸上的那一段）。
  const TECHNIQUE_IDS = Object.freeze(["profection", "firdaria", "releasing", "decennials"]);

  const CHAPTER_IDS = Object.freeze(["overview", "positions", "houses_aspects", "classical", "timelords", "receipt"]);

  // 很窄的螢幕（400px 以下）分頁列上的短章名。短名必須是完整章名裡連續的一段：看得見的字要在
  // 輔助科技念的名稱裡（WCAG 2.5.3）；完整章名照舊是連結的名稱。沒有列的章本來就夠短。
  const SHORT_TITLES = Object.freeze({ classical: "古典", receipt: "收據" });

  const MODES = Object.freeze({
    quick: Object.freeze({
      id: "quick",
      label: "快速看盤",
      // 就是產品預設：不多勾任何一項。
      options: Object.freeze({}),
      chapters: Object.freeze(["overview", "positions", "houses_aspects", "receipt"]),
      // 位置表在畫面上先只顯示常用的四欄；匯出照舊全欄。
      compactPositions: true,
      // 星盤圖與三個答案是首屏的第一個東西；導覽收成一行，要看再點開。
      firstTimeOpen: false,
      exportDetail: "chart_data_only",
      showSettings: false,
      openSettings: false,
      timelordsAfterChart: false,
    }),
    classical: Object.freeze({
      id: "classical",
      label: "古典完整",
      options: Object.freeze({
        body_selection_preset: "classical_seven_v1",
        // 日夜盤與命運點、精神點由同一個選項開啟（後端在算阿拉伯點時判定日夜盤）。
        include_lots: true,
        include_domicile_exaltation: true,
        // 外來依 Lilly 1647 判；後端預設不算，只有這個模式預先選上。
        peregrine_profile: "lilly_1647_p112_v1",
        include_dodecatemoria: true,
        // 界、面、三分性古書各有好幾套，本站不替你選：預設全部並列，第一次算就看得到各家哪裡不同。
        bounds_profile: "all",
        decan_profile: "all",
        triplicity_profile: "all",
      }),
      chapters: CHAPTER_IDS,
      compactPositions: false,
      firstTimeOpen: false,
      exportDetail: "chart_data_only",
      showSettings: true,
      openSettings: false,
      timelordsAfterChart: true,
    }),
    custom: Object.freeze({
      id: "custom",
      label: "自訂",
      options: Object.freeze({}),
      chapters: CHAPTER_IDS,
      compactPositions: false,
      firstTimeOpen: false,
      exportDetail: "reproducibility_detail",
      showSettings: true,
      openSettings: true,
      timelordsAfterChart: false,
    }),
  });

  /**
   * 區段 → 章。folded：這一區預設收起，只露出標題、第一句說明與「展開這一區」（列印照舊全部印出）。
   * 收起的是少數人才查的專門項目；多數人要看的位置、宮位、相位與古典判斷的主幹照舊攤開。
   * 一覽圖已把答案攤在畫面上的區段（行速與停滯）不另外收，免得答案藏進兩層摺疊。
   * enable：這一區「這次沒有算」時，結果頁那一行「加算」要打開的是/否選項；
   * 沒有 enable 的區段沒算時不列（它不是用一個勾選就能加算的，例如出生時刻敏感度、站心月亮）。
   */
  const SECTION_CHAPTERS = Object.freeze([
    { section: "summary", chapter: "overview" },

    { section: "bodies", chapter: "positions" },
    { section: "nodes", chapter: "positions" },
    { section: "lunar_apsides", chapter: "positions", enable: ["include_lilith_priapus"], folded: true },
    { section: "parallax_moon", chapter: "positions", folded: true },
    { section: "fixed_stars", chapter: "positions", enable: ["include_fixed_stars"], folded: true },
    { section: "angles", chapter: "positions" },
    { section: "extra_angles", chapter: "positions", enable: ["include_extra_angles"], folded: true },
    { section: "lunar_events", chapter: "positions", enable: ["include_lunar_phases", "include_eclipses"], folded: true },
    { section: "prenatal_points", chapter: "positions", enable: ["include_lunar_phases", "include_eclipses"], folded: true },
    { section: "horizon_events", chapter: "positions", enable: ["include_rise_set_transits"], folded: true },
    { section: "antiscia", chapter: "positions", enable: ["include_antiscia"], folded: true },
    { section: "declination_aspects", chapter: "positions", enable: ["include_declination_aspects"], folded: true },
    { section: "dodecatemoria", chapter: "positions", enable: ["include_dodecatemoria"] },

    { section: "houses", chapter: "houses_aspects" },
    { section: "planet_in_house", chapter: "houses_aspects" },
    { section: "aspects", chapter: "houses_aspects", enable: ["include_aspects"] },

    { section: "sect", chapter: "classical", enable: ["include_lots"] },
    { section: "planetary_hours", chapter: "classical" },
    { section: "lunar_mansions", chapter: "classical", enable: ["include_lunar_mansions"], folded: true },
    { section: "lots", chapter: "classical", enable: ["include_lots"] },
    { section: "void_of_course", chapter: "classical", enable: ["include_void_of_course"], folded: true },
    { section: "dignities", chapter: "classical", enable: ["include_domicile_exaltation"] },
    { section: "dignity_domicile_exaltation", chapter: "classical" },
    { section: "dignity_bounds", chapter: "classical" },
    { section: "dignity_face_decan", chapter: "classical" },
    { section: "dignity_triplicity", chapter: "classical" },
    { section: "dignity_peregrine", chapter: "classical" },
    { section: "solar_phase", chapter: "classical", enable: ["include_solar_phase"], folded: true },
    { section: "motion_states", chapter: "classical", enable: ["include_motion_states"] },
    { section: "classical_classifications", chapter: "classical", enable: ["include_classical_classifications"], folded: true },

    { section: "time", chapter: "receipt" },
    { section: "sensitivity", chapter: "receipt" },
    { section: "requested_options", chapter: "receipt" },
    { section: "trace", chapter: "receipt" },
    { section: "contract", chapter: "receipt" },
    { section: "receipt", chapter: "receipt" },
  ]);

  const ROW_BY_SECTION = new Map(SECTION_CHAPTERS.map((row) => [row.section, row]));

  /** 網址上的 mode 值：閉集之內才採用，其餘一律當作沒有帶。 */
  function modeFromQuery(search) {
    let value = null;
    try {
      value = new URLSearchParams(String(search || "")).get("mode");
    } catch (_error) {
      return null;
    }
    return MODE_IDS.includes(value) ? value : null;
  }

  /** 網址上的 technique 值：閉集之內才採用，其餘一律當作沒有帶。 */
  function techniqueFromQuery(search) {
    let value = null;
    try {
      value = new URLSearchParams(String(search || "")).get("technique");
    } catch (_error) {
      return null;
    }
    return TECHNIQUE_IDS.includes(value) ? value : null;
  }

  function mode(id) {
    return MODES[id] || MODES.quick;
  }

  /**
   * 「第一次看星盤？」預設打開與否：看模式，但窄螢幕（手機）一律先收起，星盤圖才不被它推到好幾個螢幕之後。
   */
  function firstTimeOpen(id, narrow) {
    return mode(id).firstTimeOpen && !narrow;
  }

  /** 這個模式的起始選項：產品預設，再蓋上模式預先勾好的那幾項。 */
  function modeOptions(id, defaults) {
    return { ...defaults, ...mode(id).options };
  }

  /**
   * 區段 id（照 view-model 清單順序）→ 每一個的章。沒有列的區段跟著前面最近一個有列的區段；
   * 清單開頭就沒有列的，放「位置」。
   */
  function assign(sectionIds) {
    let previous = "positions";
    return sectionIds.map((id) => {
      const row = ROW_BY_SECTION.get(id);
      const chapter = row ? row.chapter : previous;
      previous = chapter;
      return { section: id, chapter, listed: Boolean(row) };
    });
  }

  /** 這一區是否預設收起（表裡的 folded）；不在表裡的區段不收。 */
  function foldedByDefault(sectionId) {
    const row = ROW_BY_SECTION.get(sectionId);
    return Boolean(row && row.folded);
  }

  /** 沒算的區段要打開哪些是/否選項；不能用勾選加算的回空陣列。 */
  function enableOptions(sectionId) {
    const row = ROW_BY_SECTION.get(sectionId);
    return row && Array.isArray(row.enable) ? row.enable.slice() : [];
  }

  return Object.freeze({
    MODE_IDS, TECHNIQUE_IDS, CHAPTER_IDS, MODES, SECTION_CHAPTERS, SHORT_TITLES,
    modeFromQuery, techniqueFromQuery, mode, modeOptions, firstTimeOpen, assign, enableOptions, foldedByDefault,
  });
});
