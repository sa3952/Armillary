(function attachOptionsCatalogue(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  // 宮位制等閉集代碼的中文名在 labels.js（結果與匯出用同一張表）；頁面先載入它。
  const api = factory(commonJs ? require("./labels.js") : root.ArmillaryLabels);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.OptionsCatalogue = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildCatalogue(Labels) {
  "use strict";

  // 三十八個 OptionsInput 欄位的完整目錄。
  //
  // 介面原則：辨識優於回憶。使用者是看到「Lilith」才想起要看它，
  // 不是先想起名字再去搜尋，所以選項一律攤開可掃視，不做搜尋框、不做分類導覽。
  // 分組只是視覺分隔，摺疊只有一層（進階選項開／關）。
  //
  // 兩條約束寫在資料裡而不是寫在畫面程式裡，否則會漂：
  //   1. 具名 profile 一律平等提供，不排序、不推薦、不標示建議值。因此每個
  //      profile 選項的 `values` 沒有 recommended 旗標，只有
  //      `label_zh` / `label_en`。
  //   2. 中文術語不得隱藏英文技術詞，所以每一項都有 label_zh 與 label_en
  //      兩個欄位，畫面必須同時呈現。
  //
  // `depends_on` 讓相依選項可以做第二層摺疊：父項關閉時子項不該佔版面，
  // 但也不得因此消失得無影無蹤——畫面要說「這些跟著誰」。

  // 分組只是視覺分隔線，不是要點開的容器。順序照「使用者掃視時最可能在找什麼」，
  // 不照後端欄位順序：先是看得見的天體與點，再是幾何與相位，最後是需要選流派的判斷。
  const GROUPS = Object.freeze([
    // main_form 的兩項不出現在進階選項裡；它們已升到主表單，與黃道、歲差並排。
    { key: "main_form", label_zh: "（主表單）", label_en: "(main form)", in_advanced: false },
    { key: "bodies",    label_zh: "天體",       label_en: "Bodies", in_advanced: true },
    { key: "points", in_advanced: true,    label_zh: "點與軸",     label_en: "Points and angles" },
    { key: "stars", in_advanced: true,     label_zh: "恆星",       label_en: "Fixed stars" },
    { key: "lunar", in_advanced: true,     label_zh: "月相、食、月空亡與月宿", label_en: "Lunar" },
    { key: "horizon", in_advanced: true,   label_zh: "升降與中天", label_en: "Rise, set and meridian transits" },
    { key: "geometry", in_advanced: true,  label_zh: "幾何推導",   label_en: "Derived geometry" },
    { key: "aspects", in_advanced: true,   label_zh: "相位",       label_en: "Aspects" },
    { key: "dignities", in_advanced: true, label_zh: "本質尊貴",   label_en: "Essential dignities" },
    // 與結果頁〈古典判斷〉同名：焦傷是偶然的減損，行星與宮的分類也不是本質尊貴。
    { key: "classical", in_advanced: true, label_zh: "古典判斷",   label_en: "Classical doctrine" },
  ]);

  /**
   * 每一欄的宣告。
   * type: boolean | choice | number
   * `values` 內不含建議或預設標記；預設值單獨放在 `default`，
   * 讓「產品預設」與「較好的選擇」在資料上就分得開。
   */
  const OPTIONS = Object.freeze([
    // ── 天體集合 ─────────────────────────────────────────
    { key: "body_selection_preset", group: "bodies", type: "choice",
      label_zh: "天體集合預設", label_en: "Body selection preset", default: "custom",
      values: [
        { value: "custom", label_zh: "自訂", label_en: "Custom" },
        { value: "classical_seven_v1", label_zh: "古典七政", label_en: "Classical seven" },
      ],
      // 後端 schemas.py:524 的 check_body_selection_preset：選 classical_seven_v1
      // 時，這四個非古典星體選項一律不得為 true，否則整個請求 422。
      // 宣告在資料裡，畫面才能在送出前就講清楚，而不是讓使用者撞牆。
      conflicts_when: {
        value: "classical_seven_v1",
        disables: [
          "include_outer_planets", "include_fixed_stars",
          "include_chiron", "include_lilith_priapus",
        ],
        reason_zh: "古典七政是封閉集合：太陽、月亮、水星、金星、火星、木星、土星。"
          + "選它就不能同時要求非古典天體；要那些請改回「自訂」。",
      },
      help_zh: "古典七政為太陽、月亮、水星、金星、火星、木星、土星。" },
    { key: "include_outer_planets", group: "bodies", type: "boolean",
      label_zh: "外行星", label_en: "Outer planets", default: false,
      help_zh: "天王星、海王星、冥王星。古典技法不使用，列為可選。" },
    { key: "include_chiron", group: "bodies", type: "boolean",
      label_zh: "凱龍星", label_en: "Chiron", default: false },
    { key: "include_lilith_priapus", group: "bodies", type: "boolean",
      label_zh: "Lilith 與 Priapus（目前一起計算）", label_en: "Lilith and Priapus", default: false,
      help_zh: "勾選後一次算出三個點，目前無法只取其一；它們都是月球軌道上的點，不是天體。平均黑月 Lilith：月球軌道離地球最遠那一點的平均位置，等速前進。自然黑月 Lilith：依月亮實際經過最遠點的位置推算，會在平均位置前後擺動。自然月球近地點 Priapus：月球軌道離地球最近的那一點，同樣依實際位置推算；它另外計算，通常不正好在自然黑月 Lilith 的對面。本產品不提供第三方軟體常稱 True Lilith 的密切遠地點（把此刻的瞬時軌道當成橢圓求出的最遠點；Swiss Ephemeris 文件說它相對平均位置的擺幅約 ±30°），這裡的 Lilith 也不是小行星 1181 Lilith。" },
    { key: "include_south_nodes", group: "bodies", type: "boolean",
      label_zh: "南交點", label_en: "South nodes", default: false },
    { key: "moon_position_profile", group: "bodies", type: "choice",
      label_zh: "月亮位置口徑", label_en: "Moon position profile",
      default: "global_computation_mode",
      values: [
        { value: "global_computation_mode", label_zh: "跟隨整體計算中心", label_en: "Follow global center" },
        { value: "moon_only_topocentric_v1", label_zh: "僅月亮採站心", label_en: "Moon-only topocentric" },
      ],
      help_zh: "選「僅月亮採站心」時，回應會同時保留地心參考值並標示混合來源警告。畫面上出現兩個月亮不是錯誤，是明示的座標政策。月相與日月食仍依地心，日夜盤仍用地心太陽高度；升降本來就以站心計算。" },

    // ── 宮位 ─────────────────────────────────────────────
    // 不單獨呈現：由 house_system 的下拉一併表達（第一個選項是「不計算宮位」）。
    { key: "include_houses", group: "main_form", type: "boolean",
      rendered_by: "house_system",
      label_zh: "計算宮位", label_en: "Include houses", default: true,
      help_zh: "出生時刻只知道日期時，後端會關閉宮位計算，因為宮位需要已知時刻。" },
    { key: "house_system", group: "main_form", type: "choice",
      label_zh: "宮位制", label_en: "House system", default: "W", depends_on: "include_houses",
      // 每個值的 help_zh 是一句白話：這個宮位制怎麼切天空。選單下方跟著所選的值換。
      values: [
        { value: "W", label_zh: Labels.VOCABULARIES.house_system.W, label_en: "Whole Sign",
          help_zh: "上升點所在的整個星座是第一宮，之後一個星座算一宮。" },
        { value: "P", label_zh: Labels.VOCABULARIES.house_system.P, label_en: "Placidus",
          help_zh: "每個宮頭的黃道度數，以它自己從地平升到中天（地平線下則是從天底升到地平）所需的時間三等分來定位；極圈內不提供。" },
        { value: "R", label_zh: Labels.VOCABULARIES.house_system.R, label_en: "Regiomontanus",
          help_zh: "把天赤道（地球赤道投到天上的大圓）從子午圈起每 30 度一分，再用通過地平正南、正北兩點的大圓投到黃道上。" },
        { value: "B", label_zh: Labels.VOCABULARIES.house_system.B, label_en: "Alcabitius",
          help_zh: "把上升點從地平升到中天所需的時間三等分，各分點對應的黃道度數就是宮頭；地平線下同理。" },
        { value: "O", label_zh: Labels.VOCABULARIES.house_system.O, label_en: "Porphyry",
          help_zh: "上升點、中天、下降點、天底把黃道分成四段，每段平分成三宮。" },
        { value: "E", label_zh: Labels.VOCABULARIES.house_system.E, label_en: "Equal",
          help_zh: "從上升點的度數起，每 30 度一宮；宮界不必在星座交界上。" },
        { value: "C", label_zh: Labels.VOCABULARIES.house_system.C, label_en: "Campanus",
          help_zh: "把卯酉圈（通過天頂與正東、正西的大圓）每 30 度一分，再用通過地平正南、正北兩點的大圓投到黃道上。" },
      ],
      // 選單裡的分組只依幾何分類，不表示推薦。四分宮制一組依名稱年代（名字來源人物的年代）排列，組名寫明。
      value_groups: [
        { key: "equal_size", label_zh: "每宮 30 度", values: ["W", "E"] },
        { key: "quadrant", label_zh: "四分宮制（依名稱年代）", values: ["O", "B", "C", "R", "P"] },
      ],
      help_zh: "整宮與等分宮每宮都是 30 度。四分宮制先用上升點與中天（黃道在上子午圈的那一點；子午圈是通過天頂與正南、正北的大圓）把一圈分成四段，每段再分成三宮，所以宮的大小不一。七種平等提供，本產品不排序其歷史適用性；一次計算一種。" },

    // ── 點與軸 ───────────────────────────────────────────
    { key: "include_extra_angles", group: "points", type: "boolean",
      label_zh: "額外角點", label_en: "Extra angles", default: false },
    { key: "include_anti_vertex", group: "points", type: "boolean",
      label_zh: "反宿命點", label_en: "Anti-Vertex", default: false },
    { key: "include_lots", group: "points", type: "boolean",
      label_zh: "阿拉伯點", label_en: "Arabic lots", default: false,
      help_zh: "目前僅命運點與精神點。太陽靠近地平時，日盤與夜盤兩套公式的結果並列；主要值依太陽真高度大於 0 度的規則，落宮與相位只用主要值。" },

    // ── 恆星 ─────────────────────────────────────────────
    { key: "include_fixed_stars", group: "stars", type: "boolean",
      label_zh: "恆星", label_en: "Fixed stars", default: false,
      help_zh: "全部列為研究用途：只列位置與星等，不判定與行星的合相；勾選才計算。收錄幾顆、依據哪些古書，見方法頁。" },

    // ── 月相與食 ─────────────────────────────────────────
    { key: "include_lunar_phases", group: "lunar", type: "boolean",
      label_zh: "朔望", label_en: "New and full moons (syzygies)", default: false,
      help_zh: "朔望會搜尋出生時刻前後的事件。「產前朔望」是出生前最近一次朔或望；Ptolemy 用它的度數來定上升度數（《占星四書》（Tetrabiblos）III.2）。結果列出它的時刻與度數，不拿它去推算上升點或壽命。",
      availability: {
        range_tail_may_be_unavailable: true,
        unavailable_result_preserves_core_chart: true,
      } },
    { key: "include_eclipses", group: "lunar", type: "boolean",
      label_zh: "日月食", label_en: "Eclipses", default: false,
      help_zh: "出生前最近一次日食與月食（月食另列只算本影的那一次），以全球搜尋取得，沒有看出生地是否看得見。古典占星主要用日月食看地區與時局，本命用法是近代的（見方法頁）。" },
    { key: "include_void_of_course", group: "lunar", type: "boolean",
      label_zh: "月空亡", label_en: "Void of course", default: false,
      help_zh: "完成時刻的求解方式與其限制隨每次回應交代在結果的月空亡區塊裡。詳見方法頁。" },
    { key: "include_lunar_mansions", group: "lunar", type: "boolean",
      label_zh: "月宿", label_en: "Lunar mansions", default: false,
      help_zh: "把黃道從牡羊 0° 起分成 28 等分（每宿約 12°51′），看月亮落在哪一宿，列出宿名、這一宿的範圍與月亮在宿內的位置。這是中世紀阿拉伯與歐洲占星書的分法，不是古中國的二十八宿。只計算，不解讀。" },

    // ── 地平事件 ─────────────────────────────────────────
    { key: "include_rise_set_transits", group: "horizon", type: "boolean",
      label_zh: "升降與中天", label_en: "Rise, set and meridian transits", default: false },

    // ── 幾何推導 ─────────────────────────────────────────
    { key: "include_antiscia", group: "geometry", type: "boolean",
      label_zh: "反照點", label_en: "Antiscia", default: false,
      help_zh: "座標轉換本身不需要技法選擇，公式會直接印在數值上方；哪些天體參與依方法裁決（七政，交點須另選）。" },
    { key: "antiscia_include_nodes", group: "geometry", type: "boolean",
      label_zh: "反照點含交點", label_en: "Antiscia include nodes", default: false,
      depends_on: "include_antiscia" },
    { key: "include_declination_aspects", group: "geometry", type: "boolean",
      label_zh: "赤緯平行與反平行", label_en: "Declination aspects", default: false,
      help_zh: "17 世紀 Placidus 的界定，非古典傳統，預設關閉。" },
    { key: "declination_aspect_orb_degrees", group: "geometry", type: "number",
      label_zh: "赤緯容許度（度）", label_en: "Declination orb (degrees)", default: 1.0,
      // 範圍與 backend/app/schemas.py 的 `ge=0.0, le=3.0` 相同：0 是合法值（只收精確平行）。
      // test_frontend_contract.py 以 schema 的欄位約束對照每個數字選項的上下界。
      depends_on: "include_declination_aspects", min: 0, max: 3, step: 0.1 },

    // ── 相位 ─────────────────────────────────────────────
    { key: "include_aspects", group: "aspects", type: "boolean",
      label_zh: "計算相位", label_en: "Include aspects", default: true },
    { key: "aspect_set_profile", group: "aspects", type: "choice",
      label_zh: "相位集合", label_en: "Aspect set", default: "ptolemaic_major_v1",
      depends_on: "include_aspects",
      values: [
        // 標籤與 backend/app/core/aspects.py ASPECT_SET_PROFILES 的 display_name 同字；
        // options_catalogue.test.cjs 直接讀 aspects.py 對照，不手抄第二份。
        { value: "ptolemaic_major_v1", label_zh: "合相＋四種傳統逐度相位", label_en: "Conjunction plus four traditional aspects" },
        { value: "modern_common_minor_v1", label_zh: "合相與四種傳統相位＋常用 Keplerian 小相位", label_en: "Plus common Keplerian minor aspects" },
        { value: "modern_quintile_family_v1", label_zh: "合相與四種傳統相位＋五分相家族（Keplerian）", label_en: "Plus quintile family (Keplerian)" },
        { value: "modern_minor_combined_v1", label_zh: "合相與四種傳統相位＋常用小相位＋五分相家族（Keplerian）", label_en: "Plus common minor and quintile family (Keplerian)" },
      ] },
    { key: "aspect_orb_profile", group: "aspects", type: "choice",
      // 產品預設一組 orb profile，並提示可切換。
      // 值必須等於 backend/app/schemas.py 的 OptionsInput.aspect_orb_profile 預設；
      // options_catalogue.test.cjs 直接讀 schemas.py 對照，不手抄第二份。
      label_zh: "容許度表", label_en: "Orb profile", default: "lilly_1647_experience_v1",
      announce_default: true,
      depends_on: "include_aspects",
      conflicts_when: {
        any_non_null: true,
        disables: ["aspect_fixed_orb_degrees"],
        reason_zh: "已選容許度表，固定容許度不能同時指定。要用固定值，請先把容許度表改成「不套用容許度」。",
      },
      values: [
        { value: null, label_zh: "不套用容許度", label_en: "None applied" },
        { value: "abu_mashar_lineage_v1", label_zh: "Abu Ma'shar 傳承", label_en: "Abū Ma'shar lineage" },
        { value: "lilly_1647_experience_v1", label_zh: "Lilly 1647 經驗值", label_en: "Lilly 1647 experience" },
      ],
      help_zh: "可在這裡切換成另一套容許度表，或選「不套用容許度」。不套用時，相位只有幾何角距離，沒有「是否在容許度內」的判定，這一欄會留空（不判定），而不是寫「否」。" },
    { key: "aspect_orb_scale_percent", group: "aspects", type: "number",
      label_zh: "容許度縮放（%）", label_en: "Orb scale (percent)", default: null,
      // `gt=0.0, le=300.0`。
      depends_on: "aspect_orb_profile", min: 1, max: 300, step: 1 },
    { key: "aspect_fixed_orb_degrees", group: "aspects", type: "number",
      label_zh: "固定容許度（度）", label_en: "Fixed orb (degrees)", default: null,
      // `gt=0.0, le=30.0`；下界 0 會被拒絕。
      depends_on: "include_aspects", min: 0.1, max: 30, step: 0.1,
      help_zh: "指定後會取代容許度表的逐天體數值。" },
    { key: "partile_profile", group: "aspects", type: "choice",
      label_zh: "同度相位判準", label_en: "Partile profile", default: "same_degree_number_v1",
      depends_on: "include_aspects",
      values: [
        { value: "same_degree_number_v1", label_zh: "Lilly 1647：同一整數度", label_en: "Lilly 1647: same degree number" },
        { value: "within_one_degree_v1", label_zh: "距精確 1° 以內（未找到具名前現代來源）", label_en: "Within one degree (no named pre-modern source found)" },
        { value: "lilly_1677_three_degrees_v1", label_zh: "Lilly 1677：距精確 3° 以內", label_en: "Lilly 1677: within three degrees" },
      ] },
    { key: "include_aspect_perfection", group: "aspects", type: "boolean",
      label_zh: "相位完成推算", label_en: "Aspect perfection", default: false,
      depends_on: "include_aspects" },
    { key: "aspect_include_nodes", group: "aspects", type: "boolean",
      label_zh: "相位納入交點", label_en: "Aspects include nodes", default: false,
      depends_on: "include_aspects" },
    { key: "aspect_include_angles", group: "aspects", type: "boolean",
      label_zh: "相位納入軸點", label_en: "Aspects include angles", default: false,
      depends_on: "include_aspects" },
    { key: "aspect_angle_orb_degrees", group: "aspects", type: "number",
      label_zh: "軸點容許度（度）", label_en: "Angle orb (degrees)", default: null,
      // `gt=0.0, le=30.0`；下界 0 會被拒絕。
      depends_on: "aspect_include_angles", min: 0.1, max: 30, step: 0.1 },

    // ── 本質尊貴 ─────────────────────────────────────────
    // 產品與後端預設皆關閉。
    { key: "include_domicile_exaltation", group: "dignities", type: "boolean",
      // 以下拉呈現，與界／面旬／三分性一致：那三個本來就是「不計算 ＋ 具名 profile」。
      render: "select",
      value_labels: [
        { value: false, label_zh: "不計算", label_en: "Not calculated" },
        { value: true,  label_zh: "計算",   label_en: "Calculated" },
      ],
      label_zh: "廟與旺", label_en: "Domicile and exaltation",
      default: false,
      help_zh: "只評估廟與旺；陷、弱、外來與接納（含互容）尚未評估，那是「未評估」，不是「沒有」。恆星黃道下產品會明確拒絕輸出並附原因代碼。" },
    { key: "bounds_profile", group: "dignities", type: "choice",
      label_zh: "界", label_en: "Bounds", default: null,
      values: [
        { value: null, label_zh: "不計算", label_en: "Not calculated" },
        { value: "egyptian_bounds_robbins_1940_v1", label_zh: "埃及界", label_en: "Egyptian" },
        { value: "chaldaean_bounds_ptolemy_i_21_v1", label_zh: "迦勒底界", label_en: "Chaldaean" },
        { value: "ptolemy_bounds_robbins_1940_v1", label_zh: "Ptolemy 界", label_en: "Ptolemy" },
        { value: "lilly_received_bounds_1647_v1", label_zh: "Lilly 1647 承襲界", label_en: "Lilly 1647 received" },
      ],
      help_zh: "四套平等提供。迦勒底界在日夜盤未知時無法選定守護星，回應會同時給出日盤與夜盤候選，由你判讀，本產品不替你選一個。" },
    { key: "decan_profile", group: "dignities", type: "choice",
      label_zh: "面／旬", label_en: "Face / decan", default: null,
      values: [
        { value: null, label_zh: "不計算", label_en: "Not calculated" },
        { value: "chaldean_planetary_faces_firmicus_ii_4_v1", label_zh: "Chaldean 行星面", label_en: "Chaldean planetary faces" },
        { value: "manilius_sign_decans_astronomica_iv_v1", label_zh: "Manilius 星座旬", label_en: "Manilius sign decans" },
      ],
      help_zh: "兩套的守護者型別不同：一套的守護者是行星，另一套是星座。畫面會分開標示，不混用同一種標籤。" },
    { key: "triplicity_profile", group: "dignities", type: "choice",
      label_zh: "三分性", label_en: "Triplicity", default: null,
      values: [
        { value: null, label_zh: "不計算", label_en: "Not calculated" },
        { value: "dorothean_triplicity_three_rulers_v1", label_zh: "Dorotheus 三守護", label_en: "Dorothean three rulers" },
        { value: "ptolemy_triplicity_textual_corulership_v1", label_zh: "Ptolemy 共治", label_en: "Ptolemy co-rulership" },
        { value: "lilly_triplicity_compact_1647_v1", label_zh: "Lilly 1647 簡表", label_en: "Lilly 1647 compact" },
      ] },
    { key: "triplicity_include_research_comparison", group: "dignities", type: "boolean",
      label_zh: "並列其餘三分性 profile 供比較", label_en: "Triplicity research comparison",
      default: false, depends_on: "triplicity_profile",
      help_zh: "並列比較不會改變你選定的那一套；回應中 selected_profiles 與 research_comparison_profiles 分開。" },

    // ── 行星與宮的古典分類（本質尊貴一組）──────────────────
    { key: "include_classical_classifications", group: "classical", type: "boolean",
      label_zh: "行星與宮的古典分類", label_en: "Classical planet and place classifications", default: false,
      help_zh: "列出古書怎麼分類七顆行星（吉星、凶星、屬白天或夜晚一組、喜樂宮、hayz 與 halb）與十二宮（名稱、始宮／續宮／果宮、好壞），每一條寫明出自哪本書、核到哪一層；各書說法不同時並列。想照古書看這張盤的行星屬性時才需要。" },

    // ── 十二分部（點與軸）────────────────────────────────
    { key: "include_dodecatemoria", group: "points", type: "boolean",
      label_zh: "十二分部", label_en: "Twelfth-parts (dodecatemoria)", default: false,
      help_zh: "古典占星的細部技法：把每顆行星在星座裡走了幾度放大，從同一星座的起點往後數，數到的位置叫它的「十二分部」，並列出那個星座的守護行星。有算宮位時也列上升點，勾了阿拉伯點時也列命運點與精神點。想照古書細看一個點的另一層落點時才需要；只列位置，不做解讀。" },
    { key: "dodecatemoria_profile", group: "points", type: "choice",
      label_zh: "十二分部的算法", label_en: "Twelfth-part rule", default: "twelvefold_from_sign_start_v1",
      depends_on: "include_dodecatemoria",
      values: [
        { value: "twelvefold_from_sign_start_v1", label_zh: "乘以 12（Firmicus）", label_en: "Times 12 (Firmicus)" },
        { value: "thirteenfold_from_sign_start_v1", label_zh: "乘以 13（Paulus）", label_en: "Times 13 (Paulus)" },
      ],
      help_zh: "兩種都是把星座內的度數放大，再從同一星座的起點往後數；差在乘以 12 還是乘以 13。古書有這兩種算法，同一個點常落在不同星座。兩種平等提供，結果會寫明用的是哪一種。" },

    // ── 焦傷與光束下（行星離太陽多近）──────────────────────
    { key: "include_solar_phase", group: "classical", type: "boolean",
      label_zh: "焦傷與光束下", label_en: "Combustion and under the beams (cazimi)", default: false,
      help_zh: "古典占星看行星離太陽多近：日輪內（cazimi）、焦傷（combust）、在光束下。勾選後列出月亮與五顆行星在黃道上離太陽幾度、落在哪一個距離帶，出生前後 7 天內是否升出或隱入光束，並照原典附上各家怎麼說。三種分法的結果都會列出。" },
    { key: "solar_phase_profile", group: "classical", type: "choice",
      label_zh: "焦傷的界線", label_en: "Combustion limits", default: "lilly_1647_p113_v1",
      depends_on: "include_solar_phase",
      values: [
        { value: "lilly_1647_p113_v1", label_zh: "Lilly 1647：17′、8°30′、17°", label_en: "Lilly 1647: 17′, 8°30′, 17°" },
        { value: "hellenistic_15_v1", label_zh: "希臘化：一條 15° 的線", label_en: "Hellenistic: one 15° line" },
        { value: "biruni_wright_v1", label_zh: "al-Bīrūnī：16′、6°、依行星 12°–18°", label_en: "al-Bīrūnī: 16′, 6°, 12°–18° by planet" },
      ],
      help_zh: "古書的界線彼此不同，同一顆行星可能在一家算焦傷、在另一家算在光束下。這裡選的那一套放在第一張表；三套的結果都另列在「三種分法對照」。" },
    { key: "solar_phase_disc_cazimi", group: "classical", type: "boolean",
      label_zh: "日輪內改看太陽圓面", label_en: "Cazimi on the solar disc", default: false,
      depends_on: "include_solar_phase",
      help_zh: "改用「行星中心落在太陽圓面內」判定日輪內：看天空中的實際夾角，不看黃經差。古書多半只看黃經，這是另一種讀法，所以不預設；希臘化那一套沒有日輪內，選了也不套用。" },
  ]);

  const BY_KEY = Object.freeze(OPTIONS.reduce((acc, option) => {
    acc[option.key] = option;
    return acc;
  }, {}));

  /**
   * 目前值是否偏離產品預設。與 toRequestOptions 同一個判準：等於預設就不送、
   * 不算；預設開啟的選項被關掉（include_houses: false）、預設有值的選項被清成 null，都是改動。
   */
  function isEnabled(option, value) {
    return value !== undefined && value !== option.default;
  }

  /**
   * 某選項是否因互斥而被封鎖。回傳封鎖它的來源與理由，未被封鎖則回 null。
   *
   * 與 depends_on 不同：depends_on 是「父項關了它就沒意義」，
   * 互斥是「兩者同時成立會被後端拒絕」。前者隱藏，後者要停用並說明——
   * 隱藏會讓使用者以為選項不存在，而它其實只是這一刻不能用。
   */
  function conflictFor(option, values) {
    for (const source of OPTIONS) {
      const rule = source.conflicts_when;
      if (!rule) continue;
      if (!ruleMatches(rule, values[source.key])) continue;
      if (!rule.disables.includes(option.key)) continue;
      return { source, reason_zh: rule.reason_zh };
    }
    return null;
  }

  function ruleMatches(rule, current) {
    const forms = ["value", "values", "any_non_null"]
      .filter((key) => Object.prototype.hasOwnProperty.call(rule, key));
    if (forms.length !== 1) {
      throw new Error("conflicts_when 必須恰好宣告一種比對形式");
    }
    if (rule.any_non_null) {
      return current !== null && current !== undefined && current !== "";
    }
    if (rule.values) return rule.values.includes(current);
    return current === rule.value;
  }

  /** 相依鏈是否全部成立；任一祖先關閉即為 false。 */
  function isReachable(option, values) {
    let current = option;
    const seen = new Set();
    while (current && current.depends_on) {
      if (seen.has(current.key)) return false;
      seen.add(current.key);
      const parent = BY_KEY[current.depends_on];
      if (!parent) return false;
      const parentValue = values[parent.key];
      const parentActive = parent.type === "boolean"
        ? parentValue === true
        : parentValue !== null && parentValue !== undefined;
      if (!parentActive) return false;
      current = parent;
    }
    return true;
  }

  /**
   * 每個群組「已調整」的計數，供摺疊標題顯示（競品實測法則第 1 條）。
   *
   * 摘要必須描述實際送出的選項，所以計數直接由 toRequestOptions 的 payload 導出，
   * 不另寫一套判準——被互斥封鎖、父項關閉而不會送出的值不算；預設開啟卻被關掉、會送出 false 的值要算。
   */
  function enabledCountByGroup(values) {
    const counts = {};
    GROUPS.forEach((group) => { counts[group.key] = 0; });
    Object.keys(toRequestOptions(values)).forEach((key) => { counts[BY_KEY[key].group] += 1; });
    return counts;
  }

  /**
   * 目前值 -> 送給 backend 的 options 物件。
   *
   * **等於產品預設的值一律不送。** 後端就是靠「有沒有明示送出」來區分
   * option_states 的 `input_presence`（`explicit` 與 `defaulted`）：把某個選項明示送出，
   * 收據就會從「產品預設」變成「本次選定」，
   * 而 §13.2 第 31 項要求畫面能分辨這兩者。無條件送出全部欄位會讓其中一態永遠不可達。
   *
   * 這不犧牲可重現性：回應的 `requested_options` 會回報本次實際生效的全部值，
   * 重現靠的是那份回聲，不是靠請求把預設值再說一次。
   */
  function toRequestOptions(values) {
    const payload = {};
    OPTIONS.forEach((option) => {
      if (!isReachable(option, values)) return;
      // 被互斥封鎖的欄位一律不送；送了整個請求會 422。
      if (conflictFor(option, values)) return;
      const value = values[option.key];
      if (value === undefined) return;
      if (value === option.default) return;
      payload[option.key] = value;
    });
    return payload;
  }

  function defaults() {
    return OPTIONS.reduce((acc, option) => {
      acc[option.key] = option.default;
      return acc;
    }, {});
  }

  function helpText(option) {
    const parts = option.help_zh ? [option.help_zh] : [];
    // 產品預設的具名值由 default 與 values 導出，不在說明文字裡手抄一次名稱。
    if (option.announce_default && option.default !== null && option.default !== undefined) {
      const chosen = (option.values || []).find((value) => value.value === option.default);
      if (chosen) parts.unshift(`產品預設：${chosen.label_zh}。`);
    }
    if (option.availability && option.availability.range_tail_may_be_unavailable) {
      parts.push(
        "接近支援年份尾端時，若星曆無法支撐完整搜尋窗，核心星盤仍會完成，"
        + "本模組會標為不可用並說明原因。"
      );
    }
    return parts.join("");
  }

  return Object.freeze({
    GROUPS, OPTIONS, BY_KEY,
    isEnabled, isReachable, conflictFor, enabledCountByGroup, toRequestOptions,
    defaults, helpText,
  });
});
