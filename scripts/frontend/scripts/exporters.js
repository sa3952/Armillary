(function attachExportPipeline(root, factory) {
  const commonJs = typeof module === "object" && module.exports;
  // 代碼的中文標籤在 labels.js；頁面在本檔之前載入它。
  const api = factory(commonJs ? require("./labels.js") : root.ArmillaryLabels);
  if (commonJs) module.exports = api;
  if (root) root.ChartExport = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildExportPipeline(Labels) {
  "use strict";

  const EXPORT_CONTRACT_VERSION = "0.3.0";
  // 畫面（view-model.js）與匯出共用這一份；與後端 time_utils.py 同字由
  // tests/integration/test_frontend_contract.py 對照。1972 年前與約 2033-09 以後的盤
  // 是 UT1 而不是 UTC；這時欄位值結尾的 Z 只是沿用欄位格式，所以一併去掉。
  const TIME_SCALE_ZH = Object.freeze({
    pre_utc_ut1_estimate: "UT1 估計",
    early_utc_era_ut1_by_swiss_rule: "UT1（舊協調世界時期間）",
    modern_leap_second_utc: "UTC",
    future_ut1_by_swiss_stale_leap_table_rule: "UT1（Swiss 遠期規則）",
  });

  // 出生時刻不精確時，這個時刻是後端取樣的代表性錨點（當地正午或該小時的中點），不是出生時刻；
  // 裸標「UTC:」會讓讀者以為那就是出生時刻。標籤沿用時間轉換表那一列的說法，括號內仍寫時間尺度。
  function chartInstantLine(timeConversion, precision) {
    const value = timeConversion && timeConversion.utc_iso_8601;
    if (!value) return null;
    const era = timeConversion.time_scale_era;
    const modern = !era || era === "modern_leap_second_utc";
    const scale = modern ? "UTC" : Labels.closedLabel(era, TIME_SCALE_ZH, "時間尺度");
    const label = precision && precision !== "exact" ? `代表性錨點（非出生時刻，${scale}）` : scale;
    return { label, value: modern ? value : String(value).replace(/Z$/, "") };
  }

  // 輸入假設：出生時刻的把握程度（兩種模式都印，附代碼）；輸入座標的原值只在驗算資料（Dossier 的
  // input_receipt），「運算結果」不帶，改在開頭寫明去哪裡找。恆星時與四軸本身就推得回觀測地，所以
  // 同一句也說出這件事，不讓「不帶座標」被讀成「不含地點」。每一種格式都從這一份產生。
  const OBSERVER_LOCATION_NOTE = "座標全文見驗算資料（星盤數值本身可推回出生地點）";
  function inputAssumptionEntries(document) {
    const detailed = document.include_reproducibility !== false;
    const sensitivity = document.source_response && document.source_response.birth_time_sensitivity;
    const precision = sensitivity && sensitivity.precision;
    const entries = [];
    if (typeof precision === "string" && precision) {
      entries.push({
        key: "birth_time_precision", label: "出生時刻把握程度",
        value: Labels.label("birth_time_precision", precision), code: precision,
      });
    }
    if (!detailed) {
      entries.push({ key: "observer_location", label: "觀測地", value: OBSERVER_LOCATION_NOTE, code: "" });
    }
    return entries;
  }

  function birthTimePrecision(document) {
    const sensitivity = document.source_response && document.source_response.birth_time_sensitivity;
    return sensitivity && sensitivity.precision;
  }

  /** 純文字一行：有代碼的寫成「標籤［代碼］: 值」，觀測地那一句原樣。 */
  function inputAssumptionText(entry) {
    if (entry.key === "observer_location") return entry.value;
    return `${entry.label}［${entry.code}］: ${entry.value}`;
  }
  // 經度的參考框架。恆星黃道的盤若不註明，匯出的位置與回歸黃道無從分辨，
  // 所以兩種輸出模式的每一種格式都在開頭印出。「計算政策」收據表（view-model.js）
  // 也取用這一份標籤，值照後端的代碼，不另譯；歲差校正只在恆星黃道下才有作用，回歸黃道不印。
  const COMPUTATION_MODE_FIELDS = Object.freeze([
    ["zodiac", "黃道"],
    ["ayanamsa", "歲差校正"],
    ["center", "計算中心"],
    ["position_mode", "位置模式"],
    ["ecliptic_frame", "黃道框架"],
    ["nutation", "章動"],
  ]);

  function computationModeEntries(sourceResponse) {
    const mode = sourceResponse && sourceResponse.computation_mode;
    if (!mode || typeof mode !== "object" || Array.isArray(mode)) return [];
    return COMPUTATION_MODE_FIELDS
      .filter(([key]) => Object.hasOwn(mode, key))
      .filter(([key]) => key !== "ayanamsa" || mode.zodiac === "sidereal")
      .map(([key, label]) => ({
        key,
        label,
        value: typeof mode[key] === "boolean" ? (mode[key] ? "是" : "否") : String(mode[key]),
        raw: mode[key],
      }));
  }

  /** 三個契約版本，純文字匯出開頭與一頁摘要的收據身分同一份字。 */
  function contractVersionLines(document) {
    const dossier = document.calculation_dossier || {};
    return [
      `Export Contract ${document.export_contract_version}`,
      `API Schema ${document.source_response.schema_version || "—"}`,
      `Calculation Dossier ${dossier.dossier_version || "—"}`,
    ];
  }

  function computationModeLine(sourceResponse) {
    const entries = computationModeEntries(sourceResponse);
    if (!entries.length) return null;
    return {
      label: "計算模式",
      value: entries.map((entry) => `${entry.label} ${entry.value}`).join("；"),
    };
  }

  const OUTPUT_MODES = Object.freeze({
    chart_data_only: "chart_data_only",
    reproducibility_detail: "reproducibility_detail",
  });
  const REPRODUCIBILITY_SECTION_IDS = new Set([
    "trace", "requested_options", "contract", "receipt",
  ]);
  const SUPPORTED_RESPONSE_CONTRACTS = Object.freeze({
    "0.19.0": Object.freeze(["0.11.0"]),
  });

  function assertCompatibleSourceResponse(sourceResponse) {
    const apiVersion = sourceResponse && sourceResponse.schema_version;
    if (!apiVersion) {
      throw new Error("缺少 API schema 版本，不能建立可追溯輸出。");
    }
    const acceptedDossiers = SUPPORTED_RESPONSE_CONTRACTS[apiVersion];
    if (!acceptedDossiers) {
      throw new Error(`不相容的 API schema 版本：${apiVersion}。`);
    }
    const dossierVersion =
      sourceResponse &&
      sourceResponse.calculation_dossier &&
      sourceResponse.calculation_dossier.dossier_version;
    if (!dossierVersion) {
      throw new Error("缺少 Calculation Dossier 版本，不能建立可追溯輸出。");
    }
    if (!acceptedDossiers.includes(dossierVersion)) {
      throw new Error(
        `不相容的 Calculation Dossier 版本：${dossierVersion}（API ${apiVersion}）。`
      );
    }
  }

  function text(value) {
    if (value === null || value === undefined) return "—";
    return String(value);
  }

  function plainScalar(value) {
    return text(value).replace(/[\t\r\n]+/g, " ");
  }

  function normalizeTable(table) {
    return {
      title: text(table.title || ""),
      columns: (table.columns || []).map(text),
      rows: (table.rows || []).map((row) => row.map(text)),
      // 版面變體（相位方格）只決定畫面樣式；文字匯出照一般表格輸出，不讀它。
      ...(table.variant ? { variant: text(table.variant) } : {}),
    };
  }

  // 收據狀態是 section 模型的第一級欄位，不是備註字串。
  //
  // backend 對每個模組回 requested / executed / applicable / available /
  // source / reason_code，四個布林的組合語義各不相同。若把它們壓平成一句備註，
  // 畫面就只能靠解析字串才能把「產品明確拒絕」與「使用者沒有要求」畫成不同樣子，
  // 而契約 §13.2 第 24 項要求這兩者在畫面上必須不同。狀態進模型，
  // 渲染與各 serializer 才會拿到同一份、且不必再猜。
  const SECTION_STATES = Object.freeze({
    present: "已計算",
    refused: "產品明確拒絕",
    not_requested: "未請求",
    executed_unavailable: "已執行，無可用結果",
  });

  function normalizeStatus(status) {
    if (status === undefined || status === null) {
      return { state: "present", label: SECTION_STATES.present, reason_code: "", reason_label: "" };
    }
    if (typeof status !== "object" || Array.isArray(status)) {
      throw new Error("section status 必須是物件。");
    }
    const state = text(status.state);
    if (!Object.hasOwn(SECTION_STATES, state)) {
      // Fail closed：把未知狀態當成 present 會讓「被拒絕」看起來像「算出來了」。
      throw new Error(`不支援的 section status.state: ${state}`);
    }
    return {
      state,
      label: SECTION_STATES[state],
      reason_code: status.reason_code ? text(status.reason_code) : "",
      // 原因代碼的中文說法由 view-model 的模組原因對照表給；沒有就只有代碼。
      reason_label: status.reason_code && status.reason_label ? text(status.reason_label) : "",
    };
  }

  // 區段摘要圖（出生時刻敏感度的取樣摘要）。圖本身只在畫面與
  // 列印上畫；每一種文字輸出都印它的文字版（figureLines），所以「這五個取樣點
  // 分類相同」這類結論不會只存在於畫面。閉集：未知的 kind 或 tone 直接拒絕，
  // 不默默畫成另一種樣子。
  const FIGURE_TONES = Object.freeze(["same", "differs", "none"]);
  const FIGURE_GROUP_TONES = Object.freeze(["differs", "same", "partial", "unchecked"]);
  function closedValue(value, allowed, role) {
    if (!allowed.includes(value)) throw new Error(`不支援的 ${role}: ${text(value)}`);
    return value;
  }
  function normalizeFigure(figure) {
    if (!figure || typeof figure !== "object" || Array.isArray(figure)) {
      throw new Error("section figure 必須是物件。");
    }
    closedValue(figure.kind, ["sampling_marks"], "section figure kind");
    return {
      kind: figure.kind,
      tone: closedValue(figure.tone, FIGURE_TONES, "figure tone"),
      lead: text(figure.lead),
      marks: (figure.marks || []).map((mark) => ({
        label: text(mark.label),
        representative: mark.representative === true,
        bands_after: Number.isInteger(mark.bands_after) && mark.bands_after > 0 ? mark.bands_after : 0,
        gap_label: mark.gap_label ? text(mark.gap_label) : "",
      })),
      text_alternative: text(figure.text_alternative),
      legend: figure.legend ? text(figure.legend) : "",
      note: figure.note ? text(figure.note) : "",
      groups: (figure.groups || []).map((group) => ({
        tone: closedValue(group.tone, FIGURE_GROUP_TONES, "figure group tone"),
        title: text(group.title),
        note: group.note ? text(group.note) : "",
        bands: (group.bands || []).map((band) => ({
          range: text(band.range),
          resolution: text(band.resolution),
          text: text(band.text),
        })),
        items: (group.items || []).map(text).filter(Boolean),
      })),
    };
  }

  /** 摘要圖的文字版：每一種文字輸出都用這一份，順序與畫面相同。legend 只描述
   *  圖形（「空心點是…」），沒有圖的輸出不印；text_alternative 已寫出哪一點是代表性時刻。 */
  function figureLines(figure) {
    const lines = [figure.lead, figure.text_alternative];
    if (figure.note) lines.push(figure.note);
    figure.groups.forEach((group) => {
      lines.push(group.title + (group.note ? `：${group.note}` : ""));
      group.bands.forEach((band) => lines.push(`${band.range}（${band.resolution}）：${band.text}`));
      if (group.items.length) lines.push(group.items.join("、"));
    });
    return lines;
  }

  function normalizeSection(section, index) {
    const figures = (section.figures || []).map(normalizeFigure);
    return {
      id: text(section.id || `section-${index + 1}`),
      title: text(section.title || `Section ${index + 1}`),
      layer_label: text(section.layer_label || ""),
      status: normalizeStatus(section.status),
      // 只有帶摘要圖的區段才有這個鍵。
      ...(figures.length ? { figures } : {}),
      notes: (section.notes || []).map(text).filter(Boolean),
      tables: (section.tables || []).map(normalizeTable),
      blocks: (section.blocks || []).map(text).filter(Boolean),
    };
  }

  // 版本相容不等於結構完整。模組是否請求、執行、適用、可用，只由後端的單一狀態產生器
  // （calculation_dossier.calculation_policy.option_states 與 modules）說；消費端不得從缺鍵、
  // null 或空容器推定（輸出契約：「option_states is the single authority」）。所以權威本身
  // 缺席、不是正確的紀錄或是空的，這份回應就無從核對，整份拒絕，不退回去猜「未請求」或「已計算」。
  // 權威在時，它說 executed=true、available=true 的選項，其 response_paths 必須真的有內容；
  // 缺席、null 或空物件代表回應在途中被截斷。空陣列不算截斷：已執行的列表模組可以合法地沒有項目。
  // 這裡丟出的錯誤帶 code=response_incomplete，頁面據此說「回應結構不完整」而不是「版本不相容」。
  const INCOMPLETE_RESPONSE = "response_incomplete";
  function incompleteResponse(detail) {
    const error = new Error(`回應結構不完整：${detail}，不能建立可追溯輸出。`);
    error.code = INCOMPLETE_RESPONSE;
    return error;
  }

  function isRecord(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }

  function resolveResponsePath(response, dottedPath) {
    let current = response;
    for (const part of String(dottedPath).split(".")) {
      if (!isRecord(current) || !Object.hasOwn(current, part)) {
        return { found: false, value: undefined };
      }
      current = current[part];
    }
    return { found: true, value: current };
  }

  // 後端 core/module_state.py 的 MODULE_STATUSES。
  const MODULE_STATUSES = Object.freeze(["not_requested", "computed", "not_applicable"]);
  const OPTION_STATE_FLAGS = Object.freeze(["requested", "executed", "applicable", "available"]);
  // 每一張回應（page 投影也保留）都帶的頂層紀錄。
  const REQUIRED_RECORDS = Object.freeze([
    "computation_mode", "astronomical_data", "derived_methods", "derived_geometry", "birth_time_sensitivity",
  ]);
  // 選項的 response_paths 落在這三層時，模組容器的鍵必須在（未請求時值為 null）。
  const RESULT_LAYERS = Object.freeze(["astronomical_data", "derived_methods", "derived_geometry"]);
  const nonEmptyString = (value) => typeof value === "string" && value.length > 0;

  function assertStructurallyComplete(sourceResponse) {
    if (!isRecord(sourceResponse) || !isRecord(sourceResponse.calculation_dossier)) {
      throw incompleteResponse("缺少 Calculation Dossier");
    }
    REQUIRED_RECORDS.forEach((key) => {
      if (!isRecord(sourceResponse[key])) throw incompleteResponse(`缺少 ${key}`);
    });
    // 每一種匯出開頭都印參考框架；少了黃道，恆星黃道的經度讀起來就像回歸黃道。
    if (!nonEmptyString(sourceResponse.computation_mode.zodiac)) {
      throw incompleteResponse("computation_mode 缺少 zodiac");
    }
    if (Object.hasOwn(sourceResponse, "projection")) {
      const projection = sourceResponse.projection;
      if (!isRecord(projection) || projection.name !== "page") {
        throw incompleteResponse("projection 不是已知的投影");
      }
    } else {
      // 完整回應（沒有 projection 鍵）才有驗算資料；少了它們，驗算區段會被畫成「沒有」。
      if (!Array.isArray(sourceResponse.calculation_trace) || !sourceResponse.calculation_trace.length) {
        throw incompleteResponse("完整回應缺少計算軌跡");
      }
      ["requested_options", "output_contract"].forEach((key) => {
        if (!isRecord(sourceResponse[key])) throw incompleteResponse(`完整回應缺少 ${key}`);
      });
    }
    const dossier = sourceResponse.calculation_dossier;
    const warnings = dossier.warnings;
    if (!Array.isArray(warnings) || !warnings.every(
      (warning) => isRecord(warning) && nonEmptyString(warning.code) && nonEmptyString(warning.message)
    )) {
      throw incompleteResponse("注意事項清單缺席或殘缺");
    }
    const policy = dossier.calculation_policy;
    if (!isRecord(policy)) throw incompleteResponse("缺少 calculation_policy");
    const states = policy.option_states;
    if (!isRecord(states) || !Object.keys(states).length) {
      throw incompleteResponse("缺少選項狀態（option_states）");
    }
    const modules = policy.modules;
    if (!isRecord(modules) || !Object.keys(modules).length) {
      throw incompleteResponse("缺少模組狀態（modules）");
    }
    Object.entries(modules).forEach(([module, value]) => {
      if (!MODULE_STATUSES.includes(value)) throw incompleteResponse(`模組 ${module} 的狀態不在閉集`);
    });
    const containers = new Set();
    Object.entries(states).forEach(([option, state]) => {
      const valid = isRecord(state)
        && OPTION_STATE_FLAGS.every((flag) => typeof state[flag] === "boolean")
        && (state.reason_code === null || typeof state.reason_code === "string")
        && Array.isArray(state.response_paths) && state.response_paths.length > 0
        && state.response_paths.every(nonEmptyString);
      if (!valid) throw incompleteResponse(`選項 ${option} 的狀態不是完整紀錄`);
      state.response_paths.forEach((responsePath) => {
        const [layer, key] = responsePath.split(".");
        if (RESULT_LAYERS.includes(layer) && key) containers.add(`${layer}.${key}`);
      });
    });
    containers.forEach((container) => {
      if (!resolveResponsePath(sourceResponse, container).found) {
        throw incompleteResponse(`缺少模組容器 ${container}`);
      }
    });
    const missing = [];
    Object.entries(states).forEach(([option, state]) => {
      if (state.executed !== true || state.available !== true) return;
      state.response_paths.forEach((responsePath) => {
        const { found, value } = resolveResponsePath(sourceResponse, responsePath);
        const empty = !found || value === null || (isRecord(value) && Object.keys(value).length === 0);
        if (empty) missing.push(`${option} → ${responsePath}`);
      });
    });
    if (missing.length) {
      throw incompleteResponse(`後端標為已算出的模組缺少內容（${missing.join("、")}）`);
    }
  }

  /** 版本先於結構：新版本的回應形狀不同，該說的是「版本不相容」，不是「不完整」。 */
  function assertRenderableResponse(sourceResponse) {
    if (!sourceResponse || !sourceResponse.calculation_dossier) {
      throw incompleteResponse("缺少 Calculation Dossier");
    }
    assertCompatibleSourceResponse(sourceResponse);
    assertStructurallyComplete(sourceResponse);
  }

  function createDocument(sourceResponse, sections) {
    assertRenderableResponse(sourceResponse);
    return {
      export_contract_version: EXPORT_CONTRACT_VERSION,
      calculation_dossier: sourceResponse.calculation_dossier,
      source_response: sourceResponse,
      sections: (sections || []).map(normalizeSection),
    };
  }

  // 預設回應是 projection=page，只帶頁面主體畫的欄位；完整回應
  // （detailed）沒有 projection 鍵。「運算結果＋驗算資料」只能由完整回應產生，
  // 頁面版本的文件不得冒充（它沒有軌跡、契約與收據）。
  function holdsVerificationDetail(document) {
    const source = document && document.source_response;
    return Boolean(source) && !Object.hasOwn(source, "projection");
  }

  /**
   * 第二次請求（projection=detailed）回來的文件，是否就是畫面上那一份結果的完整版：
   * 計算軌跡摘要與建置身分相同，而且頁面主體逐區相同。不同就代表服務在兩次請求之間
   * 換了版本或結果，驗算資料不得接到這份結果底下。
   */
  function bindsToPageDocument(pageDocument, detailDocument) {
    const dossier = (document) => (document && document.calculation_dossier) || {};
    const digest = (document) => {
      const receipt = dossier(document).trace_receipt;
      return receipt && typeof receipt === "object"
        ? receipt.python_json_serialization_sha256 : null;
    };
    if (!holdsVerificationDetail(detailDocument)) return false;
    if (!digest(pageDocument) || digest(pageDocument) !== digest(detailDocument)) return false;
    if (JSON.stringify(dossier(pageDocument).build_identity)
      !== JSON.stringify(dossier(detailDocument).build_identity)) return false;
    const body = (document) => JSON.stringify(document.sections.filter(
      (section) => !REPRODUCIBILITY_SECTION_IDS.has(section.id)
    ));
    return body(pageDocument) === body(detailDocument);
  }

  function projectOutputDocument(document, mode = OUTPUT_MODES.reproducibility_detail) {
    if (!Object.hasOwn(OUTPUT_MODES, mode)) {
      throw new Error(`不支援的輸出詳細度: ${mode}`);
    }
    const detailed = mode === OUTPUT_MODES.reproducibility_detail;
    if (detailed && !holdsVerificationDetail(document)) {
      throw new Error("這份結果只有畫面上的資料；請先取得驗算資料。");
    }
    return {
      ...document,
      output_mode: mode,
      include_reproducibility: detailed,
      // 未請求的區段不刪。它們沒有表格、只帶狀態，讀者才分得出「沒請求」與「不存在」。
      sections: detailed
        ? document.sections
        : document.sections
          .filter((section) => !REPRODUCIBILITY_SECTION_IDS.has(section.id)),
    };
  }

  // 契約 §2 說 section copy 是「TSV 型純文字，供貼入筆記或試算表」。TSV 的
  // 欄界是 tab、列界是換行，所以儲存格裡的 tab 會多切出一欄、換行會拆成兩列
  // ——而使用者貼進試算表後**不會察覺資料已錯位**。
  //
  // 折成空白會失去換行這個字形，但保住欄列結構。兩害相權取結構：錯位是靜默的，
  // 少一個換行不是。目前後端進入儲存格的自由文字都不含這些字元，這裡不依賴那件事。
  //
  // 公式中和（前置撇號）只在會被試算表讀進去的輸出：CSV，以及區段複製（契約：TSV 型
  // 純文字，供貼入筆記或試算表；地點標籤之類的外來文字可以是 `=HYPERLINK(…)`）。
  // 全文複製與 TXT 下載是給人讀的文件，撇號在那裡只是一個多出來的字元：UTC 偏移會印成
  // `'+08:00:00`，所以這兩者原樣印出，只折疊 tab／CR／LF。
  function tsvCell(value, spreadsheet) {
    // 三個控制字元都要中和，不只 CRLF 與 LF：單獨的 CR 對試算表本身就是
    // record separator，貼上後照樣拆列。
    return (spreadsheet ? spreadsheetScalar(value) : text(value)).replace(/[\t\r\n]+/g, " ");
  }

  function renderTableText(table, spreadsheet) {
    const cell = (value) => tsvCell(value, spreadsheet);
    const lines = [];
    if (table.title) lines.push(`[${table.title}]`);
    lines.push(table.columns.map(cell).join("\t"));
    table.rows.forEach((row) => lines.push(row.map(cell).join("\t")));
    return lines.join("\n");
  }

  /**
   * 區段複製（預設）中和公式前導，因為它是給試算表貼上的 TSV；renderPlainText 以
   * `{ spreadsheet: false }` 呼叫，給人讀的全文與 TXT 原樣印出。
   */
  function renderSectionText(section, { spreadsheet = true } = {}) {
    if (!section || typeof section !== "object" || Array.isArray(section)) {
      throw new Error("缺少可用的 canonical section。");
    }
    const lines = [`## ${plainScalar(section.title)}`];
    if (section.layer_label) lines.push(`層級: ${plainScalar(section.layer_label)}`);
    if (section.status && section.status.state !== "present") {
      lines.push(`狀態: ${plainScalar(section.status.label)}`);
      if (section.status.reason_code) {
        lines.push(`原因代碼: ${plainScalar(section.status.reason_code)}`);
      }
    }
    (section.figures || []).forEach((figure) => {
      figureLines(figure).forEach((line) => lines.push(`摘要: ${plainScalar(line)}`));
    });
    section.notes.forEach((note) => lines.push(`備註: ${plainScalar(note)}`));
    section.tables.forEach((table) => {
      lines.push("", renderTableText(table, spreadsheet));
    });
    section.blocks.forEach((block) => lines.push("", plainScalar(block)));
    return lines.join("\n").trim();
  }

  // 匯出自己的結構字彙（不是資料）一律中文；閉集代碼不混進這些標籤，而是放在
  // CSV 的「代碼」欄、純文字與 Markdown 的［］裡，讀者看標籤、程式讀代碼。
  const WARNINGS_LABEL = "注意事項";
  const CSV_HEADER = Object.freeze(["區段代碼", "區段", "表", "列", "欄位", "值", "代碼"]);
  const CSV_LABELS = Object.freeze({
    dossier_table: "JSON 路徑",
    layer: "層級",
    status: "狀態",
    reason: "原因",
    summary: "摘要",
    notes: "備註",
    blocks: "區塊",
    text: "文字",
    table: (index) => `表 ${index}`,
  });

  // 每一種格式、兩種模式印的注意事項都是這一份。「運算結果」只省略 provisional_method_result
  // （契約唯一允許省略的一類；畫面也不顯示它），其餘的地理時區、ΔT 外插、重複時刻等
  // 會改變結果讀法的注意事項，四種格式都要帶著，不能只留在畫面與純文字。
  function exportedWarnings(dossier, detailed) {
    return dossier.warnings
      .filter((warning) => detailed || warning.code !== "provisional_method_result")
      .map((warning) => ({ code: warning.code, message: warning.message }));
  }

  function warningLines(dossier, detailed = true) {
    const warnings = exportedWarnings(dossier, detailed);
    if (!warnings.length) return [`${WARNINGS_LABEL}: 無`];
    return warnings.map((warning) => {
      // 純文字的紀錄界是換行；code 與 message 走 plainScalar，
      // 否則資料裡的 CR／LF 可以偽造一整行注意事項。
      const code = plainScalar(warning.code);
      const message = plainScalar(warning.message);
      // 兩種模式同一個寫法：代碼放在［］裡，讀者讀訊息、程式以代碼對照其他格式。
      return `注意［${code}］: ${message}`;
    });
  }

  function renderPlainText(document) {
    const dossier = document.calculation_dossier;
    const detailed = document.include_reproducibility !== false;
    const lines = detailed
      ? [
        "古典西洋占星天文計算資料＋驗算資料",
        "這是計算資料與重現收據，不是占星解讀。",
        ...contractVersionLines(document),
        `Authority: ${dossier.authority || "—"}`,
      ]
      : ["渾儀運算結果", "這是運算資料，不是占星解讀。"];
    const instant = chartInstantLine(dossier.time_conversion, birthTimePrecision(document));
    if (instant) lines.push(`${instant.label}: ${instant.value}`);
    inputAssumptionEntries(document).forEach((entry) => lines.push(plainScalar(inputAssumptionText(entry))));
    const frame = computationModeLine(document.source_response);
    if (frame) lines.push(`${frame.label}: ${plainScalar(frame.value)}`);
    lines.push(...warningLines(dossier, detailed));
    document.sections.forEach((section) => {
      lines.push("", "============================================================", "");
      lines.push(renderSectionText(section, { spreadsheet: false }));
    });
    if (detailed) {
      lines.push(
        "",
        "============================================================",
        "",
        "## Calculation Dossier（機器可讀）",
        JSON.stringify(dossier, null, 2)
      );
    }
    return lines.join("\n").trim() + "\n";
  }

  // 前導不可見字元用 Unicode 類別而不是列舉：零寬字元（U+200B、U+200C、
  // U+200D、U+2060）不歸在空白。
  // C0／C1 控制字元（\p{Cc}）同樣會被試算表略過再讀到公式前導，
  // 而 \s 只涵蓋其中的 tab／CR／LF／VT／FF。
  // 看的是 NFKC 正規化後的開頭：全形（＝＋－＠｜；）與小型（﹦﹢﹣﹫）的符號，東亞語系的試算表或
  // 輸入法可能把它們轉成半形，正規化後就是 =+-@|;，不必逐一列舉。是否真的會被讀成公式沒有在各家
  // 試算表驗過，寧可多一個撇號。前導的「看不見」也包括 Unicode 定為可忽略的字元（韓文填充字
  // U+115F、U+1160、U+3164、U+FFA0 等）與點字空格 U+2800：它們不是空白類別，卻一樣顯示為空。
  // `|` 開頭可被讀成 DDE 呼叫（`|calc!A1`）；以分號為欄界讀入時（部分語系的預設），
  // `;=1+1` 會切出一格 `=1+1`。只看開頭：儲存格中間的 `|`、`;` 不加撇號。
  const CSV_FORMULA_LEAD = /^[\s\p{Cf}\p{Cc}\p{Default_Ignorable_Code_Point}\u2800]*[=+\-@|;]/u;
  // 完整量測值不是公式。只接受目前serializer實際產生的封閉形狀；
  // 時間冒號、運算子或尾隨文字都不在豁免內。
  const CSV_MEASURED_LITERAL = /^[\t\r\n ]*[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:%|\s*(?:℃|°C|h)|°(?:\d{1,2}′(?:\d{1,2}(?:\.\d+)?″)?)?)[\t\r\n ]*$/u;
  function spreadsheetScalar(value) {
    let raw = text(value);
    const formulaLike = CSV_FORMULA_LEAD.test(raw.normalize("NFKC"));
    const numericLiteral = /^[\t\r\n ]*[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?[\t\r\n ]*$/.test(raw);
    if (formulaLike && !numericLiteral && !CSV_MEASURED_LITERAL.test(raw)) raw = "'" + raw;
    return raw;
  }

  // 試算表開啟 CSV 時會把整格的布林、時刻、ISO 日期或日期加時刻轉成值，再用自己的格式顯示
  // （`true` 成為 TRUE）。預設匯入設定下加引號擋不住（引號只界定欄位），前置撇號讓它留在文字。
  // 只在 CSV：區段複製也會貼進筆記，那裡撇號只是多一個字。帶尾隨文字（`… UTC+08:00`）的格不是這些型別。
  const CSV_TYPED_LITERAL = /^[\t\r\n ]*(?:true|false|\d{4}-\d{2}-\d{2}(?:[T ]\d{1,2}(?::\d{2}(?::\d{2}(?:\.\d+)?)?)?Z?)?|\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z?)[\t\r\n ]*$/i;
  function csvCell(value) {
    let raw = spreadsheetScalar(value);
    if (CSV_TYPED_LITERAL.test(raw)) raw = "'" + raw;
    return /[",\r\n]/.test(raw) ? `"${raw.replace(/"/g, '""')}"` : raw;
  }

  function renderCsv(document) {
    const detailed = document.include_reproducibility !== false;
    const rows = [CSV_HEADER.slice()];
    const dossier = document.calculation_dossier;
    const flattenedDossier = [];
    function flatten(value, path) {
      if (Array.isArray(value)) {
        if (!value.length) flattenedDossier.push([path, "[]"]);
        value.forEach((item, index) => flatten(item, `${path}[${index}]`));
      } else if (value !== null && typeof value === "object") {
        const entries = Object.entries(value);
        if (!entries.length) flattenedDossier.push([path, "{}"]);
        entries.forEach(([key, item]) => {
          flatten(item, path ? `${path}.${key}` : key);
        });
      } else {
        const scalar = value === null ? "null" : String(value);
        flattenedDossier.push([path, scalar]);
      }
    }
    if (detailed) {
      flatten(dossier, "");
      flattenedDossier.unshift(
        ["export_contract_version", document.export_contract_version],
        ["api_schema_version", document.source_response.schema_version || "—"]
      );
      flattenedDossier.forEach(([field, value], index) => {
        rows.push([
          "_dossier", "Calculation Dossier", CSV_LABELS.dossier_table,
          index + 1, field, value, "",
        ]);
      });
    }
    // 欄位是中文標籤、值是後端代碼（計算模式行一律印代碼），代碼欄是欄位的鍵。
    computationModeEntries(document.source_response).forEach((entry, index) => {
      rows.push([
        "_computation_mode", "計算模式", "計算模式", index + 1,
        entry.label, entry.raw === null ? "null" : String(entry.raw), entry.key,
      ]);
    });
    inputAssumptionEntries(document).forEach((entry, index) => {
      rows.push(["_input", "輸入假設", "輸入假設", index + 1, entry.label, entry.value, entry.code]);
    });
    // 注意事項各自一列（值是訊息、代碼欄是代碼）；沒有任何一則時明寫一列「無」、代碼欄空白，
    // 讀者才分得出「沒有注意事項」與「這份匯出不帶注意事項」。
    const warnings = exportedWarnings(dossier, detailed);
    (warnings.length ? warnings : [{ code: "", message: "無" }]).forEach((warning, index) => {
      rows.push(["_warnings", WARNINGS_LABEL, WARNINGS_LABEL, index + 1, WARNINGS_LABEL,
        warning.message, warning.code]);
    });
    document.sections.forEach((section) => {
      const row = (table, index, field, value, code = "") => rows.push(
        [section.id, section.title, table, index, field, value, code]
      );
      // 層級（RING I／II／III）是「天文事實／幾何推導／方法判斷」的分層，畫面與其他格式都印；兩種模式都有。
      if (section.layer_label) row(CSV_LABELS.layer, 1, CSV_LABELS.layer, section.layer_label);
      // 狀態與原因同一條規則：兩種模式都印不是「已計算」的區段（TXT 與 Markdown 也是），驗算模式全印。
      const statusShown = detailed || section.status.state !== "present";
      if (statusShown) {
        row(CSV_LABELS.status, 1, CSV_LABELS.status, section.status.label, section.status.state);
      }
      if (statusShown && section.status.reason_code) {
        row(CSV_LABELS.status, 2, CSV_LABELS.reason,
          section.status.reason_label || section.status.reason_code, section.status.reason_code);
      }
      (section.figures || []).flatMap(figureLines).forEach((line, index) => {
        row(CSV_LABELS.summary, index + 1, CSV_LABELS.text, line);
      });
      section.notes.forEach((note, index) => {
        row(CSV_LABELS.notes, index + 1, CSV_LABELS.notes, note);
      });
      section.tables.forEach((table, tableIndex) => {
        const tableName = table.title || CSV_LABELS.table(tableIndex + 1);
        table.rows.forEach((cells, rowIndex) => {
          table.columns.forEach((field, columnIndex) => {
            row(tableName, rowIndex + 1, field,
              cells[columnIndex] === undefined ? "—" : cells[columnIndex]);
          });
        });
      });
      section.blocks.forEach((block, index) => {
        row(CSV_LABELS.blocks, index + 1, CSV_LABELS.text, block);
      });
    });
    return rows.map((row) => row.map(csvCell).join(",")).join("\r\n");
  }

  function renderJson(document) {
    const detailed = document.include_reproducibility !== false;
    const sourceResponse = { ...document.source_response };
    if (!detailed) {
      for (const field of [
        "calculation_dossier", "calculation_trace",
        "requested_options", "output_contract",
      ]) delete sourceResponse[field];
    }
    return JSON.stringify({
      export_contract_version: document.export_contract_version,
      output_mode: document.output_mode || OUTPUT_MODES.reproducibility_detail,
      // Dossier 在「運算結果」整份省略；注意事項與輸入假設不跟著它消失。
      warnings: exportedWarnings(document.calculation_dossier, detailed),
      input_assumptions: inputAssumptionEntries(document),
      source_response: sourceResponse,
      display_sections: document.sections,
    }, null, 2) + "\n";
  }

  /**
   * Markdown 允許 raw HTML，所以任何未經處理就插進 Markdown 的自由文字，
   * 在支援 HTML 的 renderer 裡都是 active content。
   *
   * 這是 serializer 自己的責任，不是上游的：目前 schema 沒有自由文字，不是
   * 未來輸入也永遠安全的理由。每一種輸出各自負責自己的
   * 中和：DOM 走 `textContent`、CSV 有 formula hardening、Markdown 走這裡。
   *
   * `&` 必須先換，否則後面兩個換出來的 `&lt;` 會被自己再換一次。
   */
  function escapeMarkdownText(value) {
    return text(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/([\\`*_{}\[\]()#+|~])/g, "\\$1")
      // 行首的 `-`（清單／分隔線）與 `1.`（編號清單）不在字元
      // 類裡，因為它們只在行首有意義；換行已折成 <br>，所以只看字串開頭。
      .replace(/^(\s{0,3})-(?=[\s-]|$)/, "$1\\-")
      .replace(/^(\s{0,3})(\d{1,9})\.(?=\s|$)/, "$1$2\\.")
      // GFM 的延伸自動連結把散文裡的 http(s)://、ftp:// 與 www. 變成可點的連結；跳脫冒號與點，
      // 渲染出的文字相同，但不再是連結。CommonMark 的 <…> 自動連結已因 < 被換掉而不成立。
      .replace(/(^|[^A-Za-z0-9])(https?|ftp):(?=\/\/)/gi, "$1$2\\:")
      .replace(/(^|[^A-Za-z0-9])(www)\.(?=\S)/gi, "$1$2\\.")
      .replace(/\r\n?|\n/g, "<br>");
  }

  // 儲存格與一般 Markdown 文字共用同一個 escaping owner；再 escape 一次會把
  // 已保護的反斜線與直線變成使用者可見的額外字元。
  function renderMarkdownTable(table) {
    if (!table.columns.length) return "";
    const lines = [
      `| ${table.columns.map(escapeMarkdownText).join(" | ")} |`,
      `| ${table.columns.map(() => "---").join(" | ")} |`,
    ];
    table.rows.forEach((row) => {
      const padded = table.columns.map((_, index) => escapeMarkdownText(row[index]));
      lines.push(`| ${padded.join(" | ")} |`);
    });
    return lines.join("\n");
  }

  // 依內容選一段比內容裡最長的反引號串還長的 fence：判斷「有沒有 ```」不夠，
  // 內容可能含 ```` 之類更長的串。
  function longestBacktickRun(value) {
    const runs = String(value).match(/`+/g);
    return runs ? Math.max(...runs.map((run) => run.length)) : 0;
  }

  // fenced code block 至少要三個反引號；行內 code span 一個就夠，三個在多數 renderer
  // 會被當成區塊開頭或原樣印出。
  function fenceFor(value, minimum = 3) {
    return "`".repeat(Math.max(minimum, longestBacktickRun(value) + 1));
  }

  // inline code span 內的反引號會提早關閉 span，
  // 後面的文字就落在 code 之外、不受 escape。加長分隔並在必要時補空白
  // （CommonMark：首尾都是空白且不全是空白時，解析會各去掉一個；所以首尾為反引號，
  // 或內容本身首尾都是空白時，各補一個空白讓內容原樣讀回）。
  function markdownInlineCode(value) {
    const content = text(value);
    const fence = fenceFor(content, 1);
    const padded = content.startsWith("`") || content.endsWith("`")
      || (/^ .* $/s.test(content) && content.trim() !== "");
    const pad = padded ? " " : "";
    return `${fence}${pad}${content}${pad}${fence}`;
  }

  function markdownCodeFence(value) {
    const serialized = JSON.stringify(value, null, 2);
    const fence = fenceFor(serialized);
    return `${fence}json\n${serialized}\n${fence}`;
  }

  function renderMarkdown(document) {
    const dossier = document.calculation_dossier;
    const detailed = document.include_reproducibility !== false;
    const lines = detailed
      ? [
        "# 古典西洋占星天文計算資料＋驗算資料",
        "",
        "> 這是計算資料與重現收據，不是占星解讀。數值應連同單位、時間尺度、座標系統與Calculation Dossier一起使用。",
        "",
        "## 輸出契約",
        "",
        `- Export contract: \`${document.export_contract_version}\``,
        `- API schema: \`${document.source_response.schema_version || "—"}\``,
        `- Calculation Dossier: \`${dossier.dossier_version || "—"}\``,
        `- Authority: ${escapeMarkdownText(dossier.authority || "—")}`,
      ]
      : ["# 渾儀運算結果", "", "> 這是運算資料，不是占星解讀。"];
    const instant = chartInstantLine(dossier.time_conversion, birthTimePrecision(document));
    if (instant) lines.push(`- ${escapeMarkdownText(instant.label)}: ${markdownInlineCode(instant.value)}`);
    inputAssumptionEntries(document).forEach((entry) => lines.push(entry.key === "observer_location"
      ? `- ${escapeMarkdownText(entry.value)}`
      : `- ${escapeMarkdownText(entry.label)}［${markdownInlineCode(entry.code)}］: ${escapeMarkdownText(entry.value)}`));
    const frame = computationModeLine(document.source_response);
    if (frame) lines.push(`- ${escapeMarkdownText(frame.label)}: ${escapeMarkdownText(frame.value)}`);
    lines.push("", `## ${WARNINGS_LABEL}`, "");
    const warnings = warningLines(dossier, detailed);
    warnings.forEach((warning) => lines.push(`- ${escapeMarkdownText(warning)}`));

    // 每一個把自由文字插進 Markdown 的位置都要經過 escape，不只是表格儲存格：
    // 標題、備註與表格標題同樣會讓 raw HTML 直接通過。
    document.sections.forEach((section) => {
      lines.push("", `## ${escapeMarkdownText(section.title)}`, "");
      if (section.layer_label) {
        lines.push(`**層級：** ${escapeMarkdownText(section.layer_label)}`, "");
      }
      if (section.status && section.status.state !== "present") {
        // 這裡與上面三處一致使用 markdownInlineCode：固定的單一反引號會被
        // `alpha\`x\`omega` 這種內容提前關閉，中間那段變成不受保護的散文。
        const reason = section.status.reason_code
          ? `（原因代碼 ${markdownInlineCode(section.status.reason_code)}）`
          : "";
        lines.push(`**狀態：** ${escapeMarkdownText(section.status.label)}${reason}`, "");
      }
      (section.figures || []).forEach((figure) => {
        figureLines(figure).forEach((line, index) => {
          lines.push(index === 0 ? `**${escapeMarkdownText(line)}**` : escapeMarkdownText(line), "");
        });
      });
      section.notes.forEach((note) => lines.push(`> ${escapeMarkdownText(note)}`, ""));
      section.tables.forEach((table) => {
        if (table.title) lines.push(`### ${escapeMarkdownText(table.title)}`, "");
        lines.push(renderMarkdownTable(table), "");
      });
      // blocks 進的是 ```text fence，fence 內不解析 HTML，因此不 escape——
      // 那會讓使用者在程式碼區塊裡看到 &lt;。
      // 固定長度的 fence 會被含 ``` 的內容撐破，後續文字就落在 fence 之外。
      // 同檔的 markdownCodeFence 早就示範了正確做法，這裡沿用同一個 fenceFor。
      section.blocks.forEach((block) => {
        const fence = fenceFor(block);
        lines.push(`${fence}text`, block, fence, "");
      });
    });

    if (detailed) {
      lines.push(
        "", "## Calculation Dossier（機器可讀）", "",
        "以下區塊是本次回應內同一份後端收據；可用來核對輸入、時間轉換、計算政策、星曆來源與警告。",
        "", markdownCodeFence(dossier), ""
      );
    }
    return lines.join("\n").replace(/\n{3,}/g, "\n\n");
  }

  // 列印走畫面而不是另一個 projection，摺疊的 <details> 在
  // 列印時是空的。beforeprint 全部展開、afterprint 還原；純函式，DOM 只是
  // 剛好有 `open` 屬性的物件。
  function printExpansion(detailsList) {
    const list = Array.from(detailsList || []);
    const previous = list.map((details) => details.open === true);
    list.forEach((details) => { details.open = true; });
    let restored = false;
    return function restore() {
      if (restored) return;
      restored = true;
      list.forEach((details, index) => { details.open = previous[index]; });
    };
  }

  function buildDownloadName(extension) {
    const clean = String(extension).toLowerCase().replace(/^\./, "");
    if (!["csv", "json", "txt", "md"].includes(clean)) {
      throw new Error(`不支援的匯出格式: ${extension}`);
    }
    return `classical-astrology-export.${clean}`;
  }

  function buildDownloadArtifact(
    document,
    format,
    mode = OUTPUT_MODES.reproducibility_detail,
  ) {
    const definitions = {
      csv: {
        renderer: renderCsv,
        mime_type: "text/csv;charset=utf-8",
        prefix: "\uFEFF",
      },
      json: {
        renderer: renderJson,
        mime_type: "application/json;charset=utf-8",
        prefix: "",
      },
      txt: {
        renderer: renderPlainText,
        mime_type: "text/plain;charset=utf-8",
        prefix: "",
      },
      md: {
        renderer: renderMarkdown,
        mime_type: "text/markdown;charset=utf-8",
        prefix: "",
      },
    };
    const definition = definitions[format];
    if (!definition) throw new Error(`不支援的匯出格式: ${format}`);
    const projected = projectOutputDocument(document, mode);
    return {
      filename: buildDownloadName(format),
      mime_type: definition.mime_type,
      content: definition.prefix + definition.renderer(projected),
    };
  }

  function runDownloadAction(document, format, deliverArtifact, mode) {
    try {
      deliverArtifact(buildDownloadArtifact(document, format, mode));
      return { ok: true, error_message: null };
    } catch (error) {
      return {
        ok: false,
        error_message: error instanceof Error ? error.message : String(error),
      };
    }
  }

  return {
    EXPORT_CONTRACT_VERSION,
    INCOMPLETE_RESPONSE,
    isRecord,
    incompleteResponse,
    assertRenderableResponse,
    OUTPUT_MODES,
    REPRODUCIBILITY_SECTION_IDS,
    SECTION_STATES,
    createDocument,
    holdsVerificationDetail,
    bindsToPageDocument,
    projectOutputDocument,
    renderSectionText,
    renderPlainText,
    renderCsv,
    renderJson,
    renderMarkdown,
    buildDownloadName,
    buildDownloadArtifact,
    runDownloadAction,
    printExpansion,
    TIME_SCALE_ZH,
    COMPUTATION_MODE_FIELDS,
    contractVersionLines,
    computationModeLine,
    inputAssumptionEntries,
    inputAssumptionText,
    // 另一份匯出檔（時間主星表）沿用同一套儲存格與 Markdown 中和規則與同一份 CSV 欄名，不另寫一份。
    CSV_HEADER,
    SUPPORTED_API_SCHEMA_VERSIONS: Object.freeze(Object.keys(SUPPORTED_RESPONSE_CONTRACTS)),
    csvCell,
    escapeMarkdownText,
    markdownInlineCode,
  };
});
