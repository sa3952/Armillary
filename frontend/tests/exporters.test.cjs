const test = require("node:test");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const Exporters = require("../../scripts/frontend/scripts/exporters.js");

// 這個值曾經在這裡被手寫成 "1.2.0"，而生產者在 37 天後升到 "1.3.0"；匯出器只是
// 透傳，所以測試永遠不會紅。fixture 不得記得生產者的值——它要去讀。
const ATTESTATION_VERSION = (
  fs.readFileSync(
    path.join(__dirname, "..", "..", "backend", "app", "privacy_receipt.py"),
    "utf8"
  ).match(/"privacy_attestation_version":\s*"([^"]+)"/) || []
)[1];
if (!ATTESTATION_VERSION) {
  throw new Error("privacy_receipt.py no longer declares an attestation version");
}
const compatibilityFixture = JSON.parse(
  fs.readFileSync(
    path.join(__dirname, "fixtures", "response-compatibility.json"),
    "utf8"
  )
);

// ── 公開匯出樹刻意省略的輸入 ─────────────────────────────────────────
// 公開樹由私有的匯出工具依發布清單的 include／forbidden glob 產生；契約文件與後端回應
// fixture（chart-*.json）刻意不公開。
// 判準：同時帶 SOURCE_EXPORT.json（export_mode 為匯出工具寫入的
// "closed_allowlist"）與 PUBLICATION_FILES.json，且前者以 SHA-256 登錄在後者，才算已驗證的
// 公開匯出；某路徑只有在那份清單沒有登錄它時才算被公開邊界省略。私有樹沒有這兩個標記，
// 讀檔照常執行，缺檔照常紅。
const REPOSITORY_ROOT = path.join(__dirname, "..", "..");

function publicationOmits(relativePath, root = REPOSITORY_ROOT) {
  let markerBytes;
  let receipt;
  let inventory;
  try {
    markerBytes = fs.readFileSync(path.join(root, "SOURCE_EXPORT.json"));
    receipt = JSON.parse(markerBytes.toString("utf8"));
    inventory = JSON.parse(
      fs.readFileSync(path.join(root, "PUBLICATION_FILES.json"), "utf8")
    );
  } catch {
    return false;
  }
  if (
    !receipt
    || receipt.schema_version !== 1
    || receipt.export_mode !== "closed_allowlist"
    || !/^[0-9a-f]{40}$/.test(String(receipt.private_source_revision || ""))
  ) {
    return false;
  }
  const entries = inventory && inventory.files;
  if (!Array.isArray(entries)) {
    return false;
  }
  const markerDigest = crypto.createHash("sha256").update(markerBytes).digest("hex");
  const markerBound = entries.some(
    (entry) => entry && entry.path === "SOURCE_EXPORT.json" && entry.sha256 === markerDigest
  );
  return markerBound && !entries.some((entry) => entry && entry.path === relativePath);
}

// 以真實回應 fixture 驗證的測試在 publicationOmits 為真時 skip；判準一旦恆真，它們就無聲跳過。
// relatives 是 fixtures/ 底下的相對路徑；有任何一份被公開邊界省略就 skip 並回傳 true。
function skipIfOmitted(t, relatives, why = "") {
  const omitted = relatives.map((name) => `frontend/tests/fixtures/${name}`).filter((relative) => publicationOmits(relative));
  if (omitted.length) t.skip(`後端回應 fixture 不在公開匯出 allowlist（${omitted.join("、")}）${why}`);
  return omitted.length > 0;
}
const loadResponse = (relative) => JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", relative), "utf8"));
// view-model 只在 fixture 在場時才載入，與原本各測試在 skip 之後才 require 相同。
const canonicalDocument = (response) => Exporters.createDocument(
  response, require("./script-bundles.cjs").load("view-model.js").buildSections(response)
);
test("公開匯出省略只在已驗證的匯出樹成立；私有樹缺檔仍要紅", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "public-export-marker-"));
  const target = "omitted/a-private-document.md";
  const writeJson = (name, value) => {
    const body = JSON.stringify(value);
    fs.writeFileSync(path.join(root, name), body);
    return crypto.createHash("sha256").update(body).digest("hex");
  };
  const marker = { schema_version: 1, export_mode: "closed_allowlist", private_source_revision: "a".repeat(40) };
  try {
    assert.equal(publicationOmits(target, root), false, "沒有標記的私有樹");
    const digest = writeJson("SOURCE_EXPORT.json", marker);
    assert.equal(publicationOmits(target, root), false, "只有標記、沒有清單");
    writeJson("PUBLICATION_FILES.json", { files: [{ path: "SOURCE_EXPORT.json", sha256: "0".repeat(64) }] });
    assert.equal(publicationOmits(target, root), false, "清單沒有以 digest 綁定標記");
    writeJson("PUBLICATION_FILES.json", { files: [{ path: "SOURCE_EXPORT.json", sha256: digest }] });
    assert.equal(publicationOmits(target, root), true, "已驗證的匯出且清單未登錄該路徑");
    writeJson("PUBLICATION_FILES.json", {
      files: [{ path: "SOURCE_EXPORT.json", sha256: digest }, { path: target, sha256: "1".repeat(64) }],
    });
    assert.equal(publicationOmits(target, root), false, "清單登錄了該路徑，缺檔就該紅");
    const forged = writeJson("SOURCE_EXPORT.json", { ...marker, private_source_revision: "HEAD" });
    writeJson("PUBLICATION_FILES.json", { files: [{ path: "SOURCE_EXPORT.json", sha256: forged }] });
    assert.equal(publicationOmits(target, root), false, "標記不是封閉匯出的收據");
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

// 版本一律取自 response-compatibility.json 的 accepted 組合，不在此重複字面值。
// 這兩個字串曾各自釘死在 0.10.0／0.3.2，而契約已走到 0.13.0／0.6.0，
// 使八個與版本無關的 serializer 測試一起變紅。單一出處讓它不會再漂第二次。
function fixture() {
  const response = {
    schema_version: compatibilityFixture.accepted.api_schema_version,
    calculation_dossier: {
      dossier_version: compatibilityFixture.accepted.dossier_version,
      authority: "backend-authored calculation receipt",
      input_receipt: {
        datetime: { year: 1997, month: 8, day: 17, hour: 9, minute: 42, second: 0 },
        location: { latitude: 22.9908, longitude: 120.2133, altitude_m: 80 },
      },
      time_conversion: { utc_iso_8601: "1997-08-17T01:42:00.000Z" },
      warnings: [{ code: "TEST_WARNING", message: "保留, 逗號與 \"引號\"" }],
      // 狀態權威：createDocument 拒絕缺它的回應。一個未請求的選項，它寫的容器是 null。
      calculation_policy: {
        option_states: {
          include_aspects: {
            requested: false, executed: false, applicable: false, available: false,
            reason_code: "option_not_requested", response_paths: ["derived_methods.aspects"],
          },
        },
        modules: { aspects: "not_requested" },
      },
      privacy: {
        privacy_attestation_version: ATTESTATION_VERSION,
        attestation_status: "provisional_pending_external_review",
        uncovered_layers: [{
          layer: "hosting_supervisor",
          status: "outside_current_control_scope",
        }],
      },
    },
    library_info: { swiss_ephemeris_library_version: "2.10.03" },
    computation_mode: { zodiac: "tropical" },
    requested_options: { include_aspects: false },
    output_contract: { status: "provisional" },
    astronomical_data: {
      bodies: [{ name: "木星, Jupiter", longitude: 321.123456789 }],
    },
    derived_geometry: {},
    derived_methods: { aspects: null },
    birth_time_sensitivity: { precision: "exact" },
    calculation_trace: [{ title: "測試步驟", result: { longitude: 321.123456789 } }],
  };
  const sections = [
    {
      id: "time", title: "時間轉換", layer_label: "天文原始資料", notes: ["以下時間均標明時間尺度。"], blocks: [],
      tables: [{
        title: "時間", columns: ["項目", "數值"],
        rows: [["UTC", "1997-08-17T01:42:00.000Z"], ["備註", "say \"hi\", then check"]],
      }],
    },
    {
      id: "bodies", title: "七政", layer_label: "天文原始資料", notes: [], blocks: [],
      tables: [{ title: "黃道／赤道座標", columns: ["星體", "黃經"], rows: [["木星, Jupiter", "水瓶 21°07'24\""]] }],
    },
  ];
  return { response, sections };
}

const fixtureDocument = () => {
  const { response, sections } = fixture();
  return Exporters.createDocument(response, sections);
};

test("one canonical document keeps the dossier, raw precision, and display sections", () => {
  const { response, sections } = fixture();
  const document = Exporters.createDocument(response, sections);
  assert.equal(document.export_contract_version, compatibilityFixture.accepted.export_contract_version);
  assert.equal(document.calculation_dossier, response.calculation_dossier);
  assert.equal(document.source_response, response);
  // 正規化會補上預設收據狀態；沒有 status 的 section 一律視為「已計算」。
  assert.deepEqual(document.sections, sections.map((section) => ({
    ...section, status: { state: "present", label: Exporters.SECTION_STATES.present, reason_code: "", reason_label: "" },
  })));
});

test("compatibility fixture rejects every unsupported API and Dossier pair by its own guard", () => {
  const { response, sections } = fixture();
  for (const entry of compatibilityFixture.rejected) {
    const rejected = structuredClone(response);
    for (const [field, owner] of [["api_schema_version", rejected], ["dossier_version", rejected.calculation_dossier]]) {
      const key = field === "api_schema_version" ? "schema_version" : field;
      if (entry[field] === null) delete owner[key];
      else owner[key] = entry[field];
    }
    // 一個涵蓋所有守衛訊息的 alternation 會讓相鄰的守衛替另一個頂罪；每個案例由 fixture
    // 指名必須拒絕它的那一個守衛。
    const expected = entry.expected_error_contains;
    assert.ok(expected, `rejected case ${entry.name} names no expected guard`);
    assert.throws(() => Exporters.createDocument(rejected, sections),
      (error) => error instanceof Error && error.message.includes(expected),
      `${entry.name} must be rejected by the guard that reports ${expected}`);
  }
});

test("section and full copy are rendered from the canonical section model; non-record sections are rejected", () => {
  const document = fixtureDocument();
  const sectionText = Exporters.renderSectionText(document.sections[0]);
  for (const pattern of [/## 時間轉換/, /項目\t數值/, /UTC\t1997-08-17T01:42:00\.000Z/]) assert.match(sectionText, pattern);
  const fullText = Exporters.renderPlainText(document);
  assert.ok(fullText.includes(`Calculation Dossier ${compatibilityFixture.accepted.dossier_version}`),
    "全文複製必須印出目前 accepted 的 Dossier 版本");
  for (const pattern of [/TEST_WARNING/, /木星, Jupiter/, /"latitude": 22\.9908/, /Calculation Dossier（機器可讀）/, /hosting_supervisor/]) {
    assert.match(fullText, pattern);
  }
  for (const invalidSection of [null, undefined, [], "section"]) {
    assert.throws(() => Exporters.renderSectionText(invalidSection), /canonical section/);
  }
});

test("CSV preserves a single field when a spreadsheet enables additional separators", () => {
  for (const separator of [";", "\t", "|"]) {
    for (const value of [
      `label${separator}=1+1`, `label${separator}+SUM(A1)`,
      `label${separator}@SUM(A1)`, `label${separator}-1+2`,
      `label${separator}text`, `say "hello"${separator}=1+1`,
      `label${separator}\u200b=1+1`, `label${separator}  =1+1`,
    ]) {
      const record = `before,${Exporters.csvCell(value)},after`;
      assert.deepEqual(parseCsvRows(record, ",;\t|"), [["before", value, "after"]], JSON.stringify(value));
    }
  }
});

test("CSV uses a stable long-form schema and RFC 4180 escaping", () => {
  const csv = Exporters.renderCsv(fixtureDocument());
  const lines = csv.split("\r\n");
  assert.equal(lines[0], "區段代碼,區段,表,列,欄位,值,代碼");
  for (const pattern of [
    /input_receipt\.location\.latitude,22\.9908/, /warnings\[0\]\.code,TEST_WARNING/,
    /privacy\.uncovered_layers\[0\]\.layer,hosting_supervisor/, /"say ""hi"", then check"/, /"木星, Jupiter"/,
  ]) {
    assert.match(csv, pattern);
  }
  assert.ok(lines.every((line) => !line.includes("undefined")));
});

test("JSON is lossless and Markdown is labelled as data rather than interpretation", () => {
  const document = fixtureDocument();
  const parsed = JSON.parse(Exporters.renderJson(document));
  assert.equal(parsed.export_contract_version, compatibilityFixture.accepted.export_contract_version);
  assert.equal(parsed.source_response.astronomical_data.bodies[0].longitude, 321.123456789);
  assert.equal(parsed.source_response.calculation_dossier.input_receipt.location.longitude, 120.2133);
  assert.equal("calculation_dossier" in parsed, false);
  const markdown = Exporters.renderMarkdown(document);
  for (const pattern of [
    /^# 古典西洋占星天文計算資料/m, /這是計算資料與重現收據，不是占星解讀/,
    /\| 木星, Jupiter \| 水瓶 21°07'24" \|/, /TEST_WARNING/, /hosting_supervisor/,
  ]) {
    assert.match(markdown, pattern);
  }
});

test("every download format has one renderer, MIME type, generic filename, and CSV BOM policy", () => {
  const document = fixtureDocument();
  for (const [format, mimeType] of Object.entries({
    csv: "text/csv;charset=utf-8", json: "application/json;charset=utf-8",
    txt: "text/plain;charset=utf-8", md: "text/markdown;charset=utf-8",
  })) {
    const artifact = Exporters.buildDownloadArtifact(document, format);
    assert.equal(artifact.mime_type, mimeType);
    // 檔名固定，從不帶出生資料。
    assert.equal(artifact.filename, `classical-astrology-export.${format}`);
    assert.equal(Exporters.buildDownloadName(format), artifact.filename);
    assert.ok(artifact.content.length > 100);
    assert.equal(artifact.content.startsWith("\uFEFF"), format === "csv");
  }
  assert.throws(() => Exporters.buildDownloadArtifact(document, "pdf"), /不支援的匯出格式/);
  // 交付失敗時明說，不宣稱成功。
  assert.deepEqual(Exporters.runDownloadAction(document, "json", () => {
    throw new Error("simulated Blob delivery failure");
  }), { ok: false, error_message: "simulated Blob delivery failure" });
});

// ── 每一種輸出各自中和自己的邊界 ─────────────────────────────────────
// 匯出物會脫離脈絡流傳，所以中和是 serializer 自己的責任，不能倚賴「目前 schema
// 剛好沒有自由文字」。下面三張表各管一種輸出：試算表（CSV 與區段複製的 TSV）、
// Markdown、純文字（全文複製／TXT 與區段複製的欄列結構）。每張表都含相鄰控制：
// 一個把所有東西都吃掉的 escaper 也會讓防護那一半通過。

function cellsDocument(rows, response = fixture().response) {
  return Exporters.createDocument(response, [{
    id: "cells", title: "測試表", layer_label: "test", notes: [], blocks: [],
    tables: [{ title: "cases", columns: ["case", "value"], rows }],
  }]);
}

const csvField = (value) => (/[",;|\t\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value);
const foldControls = (value) => value.replace(/[\t\r\n]+/g, " ");

// [儲存格內容, 是否加公式撇號]。量測值是反向控制：一份普通星盤匯出曾有九格被加上撇號，
// 南緯、南赤緯與負偏移全中。前導的零寬字元與 C0 控制字元不歸在空白，曾整組落在防護之外。
const SPREADSHEET_CASES = [
  ["=1+1", true], ["@SUM(A1:A2)", true], ["-1+2", true], ["=SUM(A1)", true],
  ["\t=1+1", true], ["\r=1+1", true], ["   =1+1", true],
  [" =1+1", true], ["　@SUM(A1:A2)", true],
  ["​=1+1", true], ["‌=1+1", true], ["⁠@SUM(A1:A2)", true], ["​+cmd|calc", true],
  ["\u0001=1+1", true], ["\u0000 @SUM(A1:A2)", true], ["\u007f-1+2", true], ["\u000b=cmd|' /C calc'!A0", true],
  ["+0+m1", true], ["+1+m:m", true], ["-1+1%", true], ["+3%+A1", true],
  ["-2.5", false], ["+123", false], ["1e-6", false], ["-23.4", false],
  ["-23°03′30.38″", false], ["-4.5 ℃", false], ["-12.5%", false],
  ["-1.5h", false], ["-0°00′00.10″", false],
  ["<img src=x>", false], ["太陽", false],
  // 全形的 ＝＋－＠ 同樣可能被試算表讀成公式前導；前面的零寬或
  // 不換行空白也一樣。相鄰控制：不在開頭的全形符號、全形負號開頭的量測值（豁免只認 ASCII 正負號）。
  ["＝1+1", true], ["＋1", true], ["－1", true], ["＠SUM(A1:A2)", true],
  ["​＝1+1", true], ["\u00a0＝1+1", true], ["　＋cmd|calc", true],
  ["－15°25′02.60″", true], ["太陽＝1", false], ["A－B", false],
  // 小型符號（U+FE66、U+FE62、U+FE63、U+FE6B）與全形的｜；，以及顯示為空的填充字元開頭。
  ["﹦HYPERLINK(1)", true], ["﹢1+1", true], ["﹣1+1", true], ["﹫SUM(1)", true],
  ["｜calc", true], ["；=1+1", true],
  ["\u3164=1+1", true], ["\u2800=1+1", true], ["\u115F\u1160=1", true], ["\uFFA0＋1", true],
  ["太陽﹦1", false],
  // `|`（DDE 的 `|calc!A1`）與 `;`（`;=1+1`）在開頭同樣中和，前導空白、零寬與控制字元一樣略過。
  // 相鄰控制：不在開頭的 `|`、`;`、`=` 不加撇號；量測值豁免不變。
  ["|calc!A1", true], [";=1+1", true], [";", true], ["|", true],
  ["\u200b|calc!A1", true], ["  ;=1+1", true], ["\u0001|cmd", true], ["\t;SUM(A1)", true],
  ["a|b", false], ["太陽;月亮", false], ["x;=1+1", false], ["A1=B1", false], ["1|2", false],
  ["+12.5%", false], ["-23°03′30.38″", false],
  // 沒有基底字元的結合記號（\p{M}）顯示為空，與零寬字元一樣是前導；有基底字元時不是。
  ["\u0301=1+1", true], ["\u20dd+cmd|calc", true], ["\u0300\u200b@SUM(1)", true], ["e\u0301=1", false],
  // 原值以撇號開頭也補一個撇號，去掉第一個撇號一律得回原值。
  ["'s-Gravenwezel, Flanders, BE", true], ["'=1+1", true], ["''", true], ["a'b", false],
];

// L-14：負的六十進位值（`-12°34′`）與其他帶號量測值不加撇號。試算表若把它讀成公式，
// 公式裡也只有數字、小數點、`°′″`、`%`、單位 `℃`／`°C`／`h` 與空白：沒有函式名、括號、儲存格或
// 工作表參照、DDE 的 `|`／`!`，也沒有字串或連接。這裡用隨機字串窮舉豁免的形狀，確認被豁免、
// 開頭帶 `+`／`-` 的格一律只由這些字元組成；任何能呼叫、參照或外連的字元都會讓它得到撇號。
test("帶號量測值豁免的格只由數字、°′″、%、℃／°C／h 組成，沒有可呼叫或參照的字元（L-14）", () => {
  const alphabet = [..."0123456789.+-°′″%℃Ch \t=@|!:$\"(),;&[]AaHhcmd'E"];
  let seed = 20261021;
  const random = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const exemptCharacters = /^[\t\r\n +\-0-9.°′″%℃Ch]*$/u;
  let exempt = 0;
  for (let index = 0; index < 200000; index += 1) {
    const length = 2 + Math.floor(random() * 9);
    let value = random() < 0.5 ? "-" : "+";
    for (let position = 1; position < length; position += 1) value += alphabet[Math.floor(random() * alphabet.length)];
    const cell = Exporters.csvCell(value);
    if (cell.startsWith("'") || cell.startsWith("\"'")) continue;
    exempt += 1;
    assert.match(value, exemptCharacters, JSON.stringify(value));
    assert.doesNotMatch(value, /[A-Za-gi-z]|C(?!$)|h\S/u, JSON.stringify(value));
  }
  // The exemption is exercised, not vacuous; the shapes the serializer writes stay unguarded.
  assert.ok(exempt > 100, String(exempt));
  for (const value of ["-12°34′", "-12°34′56.7″", "-0°00′00.10″", "-12.5%", "-4.5 ℃", "-1.5h"]) {
    assert.equal(Exporters.csvCell(value), value);
  }
});

test("試算表輸出（CSV、區段複製）在儲存格開頭中和公式；全文複製與 TXT 原樣，tab／換行折成空白", () => {
  for (const [value, guarded] of SPREADSHEET_CASES) {
    const label = JSON.stringify(value);
    const document = cellsDocument([["v", value]]);
    const neutralized = `${guarded ? "'" : ""}${value}`;
    assert.ok(Exporters.renderCsv(document).includes(`,${csvField(neutralized)}`), `CSV ${label}`);
    assert.ok(Exporters.buildDownloadArtifact(document, "csv").content.includes(`,${csvField(neutralized)}`),
      `CSV 下載 ${label}`);
    const sectionText = Exporters.renderSectionText(document.sections[0]);
    assert.ok(sectionText.includes(`\nv\t${foldControls(neutralized)}`), `區段複製 ${label}`);
    const plain = Exporters.renderPlainText(document);
    assert.ok(plain.includes(`\nv\t${foldControls(value)}`), `全文複製 ${label}`);
    if (guarded && !value.startsWith("'")) assert.ok(!plain.includes(`\nv\t'`), `全文複製不帶撇號 ${label}`);
    assert.equal(neutralized.replace(/^'/, ""), value, `去掉第一個撇號得回原值 ${label}`);
  }
});

// 試算表開啟 CSV 時的型別判定（Excel、LibreOffice、Numbers 的共同部分），測試自己的模型，
// 不沿用匯出器的 regex：整格（去掉首尾空白）是布林、時刻、ISO 日期或日期加時刻，就會被轉成
// 布林或日期時間值，`14:30:00.000` 的毫秒與 `true` 的大小寫在顯示時就不是原字串了。
function spreadsheetTypes(cell) {
  const value = cell.trim();
  if (value.toLowerCase() === "true" || value.toLowerCase() === "false") return "boolean";
  const digits = (part, min, max) => part.length >= min && part.length <= max && [...part].every((c) => c >= "0" && c <= "9");
  const isClock = (part) => {
    const body = part.endsWith("Z") ? part.slice(0, -1) : part;
    const fields = body.split(":");
    if (fields.length < 1 || fields.length > 3 || !digits(fields[0], 1, 2) || Number(fields[0]) > 23) return false;
    if (fields.length >= 2 && !(digits(fields[1], 2, 2) && Number(fields[1]) < 60)) return false;
    if (fields.length === 3) {
      const [whole, fraction, extra] = fields[2].split(".");
      if (extra !== undefined || !digits(whole, 2, 2) || Number(whole) > 60) return false;
      if (fraction !== undefined && !digits(fraction, 1, 9)) return false;
    }
    return true;
  };
  const isDate = (part) => {
    const fields = part.split("-");
    return fields.length === 3 && digits(fields[0], 4, 4) && digits(fields[1], 2, 2) && digits(fields[2], 2, 2)
      && Number(fields[1]) >= 1 && Number(fields[1]) <= 12 && Number(fields[2]) >= 1 && Number(fields[2]) <= 31;
  };
  const separator = value.length > 10 ? value[10] : "";
  if (isDate(value.slice(0, 10)) && separator === "") return "date";
  if (isDate(value.slice(0, 10)) && (separator === " " || separator === "T") && isClock(value.slice(11))) {
    return "date-time";
  }
  if (value.includes(":") && isClock(value)) return "time";
  return null;
}

const TYPED_CASES = [
  ["14:30:00.000", true], ["14:30", true], ["9:05:07", true], ["true", true], ["FALSE", true], [" true ", true],
  ["1990-05-15", true], ["1990-05-15 14:30:00.000", true], ["1990-05-15T16:00:00Z", true],
  ["1990-05-14T21:18:34.341Z", true], ["1990-05-15 14", true],
  // 相鄰控制：帶尾隨文字、時區標記或其他字的格不是試算表的型別，不加撇號。
  ["true story", false], ["untrue", false], ["14:30 UTC", false], ["UTC+08:00", false],
  ["1990-05-15 05:18:34.341 UTC+08:00", false], ["include_houses=true", false], ["2448026.77", false],
  ["14:04:27–14:04:41（解析度 ≤15 秒）：土星的落宮", false], ["1", false], ["-23.4", false], ["0.2.0", false],
];

test("CSV 把試算表會轉成布林或日期時間的整格字串加撇號；區段複製、全文複製與 TXT 原樣", () => {
  for (const [value, guarded] of TYPED_CASES) {
    const label = JSON.stringify(value);
    assert.equal(Boolean(spreadsheetTypes(value)), guarded, `模型本身 ${label}`);
    const document = cellsDocument([["v", value]]);
    const expected = `${guarded ? "'" : ""}${value}`;
    assert.ok(Exporters.renderCsv(document).includes(`,${csvField(expected)},`), `CSV ${label}`);
    assert.ok(Exporters.buildDownloadArtifact(document, "csv").content.includes(`,${csvField(expected)},`),
      `CSV 下載 ${label}`);
    // 區段複製與全文複製會去掉行尾空白。
    assert.ok(Exporters.renderSectionText(document.sections[0]).includes(`\nv\t${value.trimEnd()}`), `區段複製 ${label}`);
    assert.ok(Exporters.renderPlainText(document).includes(`\nv\t${value.trimEnd()}`), `全文複製 ${label}`);
  }
});

// 真實回應的 CSV（兩種模式）：模型判定會被轉型的格一律帶撇號；撇號不多加；`_dossier` 列去掉撇號後
// 等於測試自己攤平 Dossier 得到的字串。
test("真實回應的 CSV 沒有一格會被試算表轉成布林或日期時間，去掉撇號即為原值", (t) => {
  const names = fs.readdirSync(path.join(__dirname, "fixtures"))
    .filter((name) => /^chart-.*\.json$/.test(name) && name !== "chart-requests.json");
  // 公開樹裡這些 fixture 一個都不在，目錄列不出來；那時改問一個具名的 fixture 是否被省略。
  if (skipIfOmitted(t, names.length ? names : ["chart-exact.json"])) return;
  const seen = { boolean: 0, date: 0, "date-time": 0, time: 0 };
  for (const name of names) {
    const response = loadResponse(name);
    const expectedDossier = new Map();
    (function walk(value, at) {
      if (Array.isArray(value)) {
        if (!value.length) expectedDossier.set(at, "[]");
        value.forEach((item, index) => walk(item, `${at}[${index}]`));
      } else if (value && typeof value === "object") {
        if (!Object.keys(value).length) expectedDossier.set(at, "{}");
        for (const key of Object.keys(value)) walk(value[key], at ? `${at}.${key}` : key);
      } else {
        expectedDossier.set(at, value === null ? "null" : String(value));
      }
    })(response.calculation_dossier, "");
    const document = canonicalDocument(response);
    for (const mode of Object.values(Exporters.OUTPUT_MODES)) {
      const rows = parseCsvRows(Exporters.buildDownloadArtifact(document, "csv", mode).content);
      rows.slice(1).forEach((row) => {
        const cell = row[5];
        const guarded = cell.startsWith("'");
        const original = guarded ? cell.slice(1) : cell;
        const type = spreadsheetTypes(original);
        if (type) seen[type] += 1;
        const where = `${name} ${mode} ${row.slice(0, 5).join(",")}`;
        if (type) assert.ok(guarded, `${where}：${JSON.stringify(cell)} 會被試算表轉成 ${type}`);
        if (guarded) assert.ok(type, `${where}：${JSON.stringify(cell)} 不該有撇號`);
        if (row[0] === "_dossier" && expectedDossier.has(row[4])) {
          assert.equal(original, expectedDossier.get(row[4]), `${where}：去掉撇號後的值`);
        }
      });
    }
  }
  // 真實回應裡有布林、日期與日期加時刻（`1990-05-15 14:30:00.000`）；單獨的時刻由上一個測試涵蓋。
  for (const type of ["boolean", "date", "date-time"]) {
    assert.ok(seen[type] > 0, `fixture 必須含會被轉成 ${type} 的格，否則這個測試沒有涵蓋它`);
  }
});

// Markdown 允許 raw HTML，未經處理的自由文字在支援 HTML 的 renderer 裡就是 active content。
// 每一列：[名稱, 文件, 檢查範圍（行首字串；null＝整份）, 必須包含, 不得包含]。
function hostileDocument(payload) {
  const { response } = fixture();
  return {
    export_contract_version: Exporters.EXPORT_CONTRACT_VERSION,
    source_response: response,
    calculation_dossier: response.calculation_dossier,
    sections: [{
      id: "probe",
      title: `標題 ${payload}`,
      layer_label: `層級 ${payload}`,
      status: { state: "present" },
      notes: [`備註 ${payload}`],
      tables: [{
        title: `表格標題 ${payload}`,
        columns: ["欄位", "值"],
        rows: [["地點標籤", payload]],
      }],
      blocks: [],
    }],
  };
}

function sectionDocument(section, mutate = () => {}) {
  const { response } = fixture();
  mutate(response);
  return Exporters.createDocument(response, [{ tables: [], notes: [], blocks: [], ...section }]);
}

const HOSTILE_IMG = "<img src=x onerror=alert(1)>";
const markdownCases = () => [
  ["raw HTML 不進 Markdown", hostileDocument(HOSTILE_IMG), null, [], ["<img", "onerror=alert(1)>"]],
  // 四個面都要涵蓋：先前只有表格儲存格被討論，標題／備註／表格標題同樣沒防。
  ...["## 標題", "**層級：**", "> 備註", "### 表格標題"].map((surface) => [
    `${surface} 經過 escape`, hostileDocument(HOSTILE_IMG), surface, ["&lt;img"], [],
  ]),
  // & 必須先換，否則 `<` 會變成 `&amp;lt;`。
  ["& 不重複編碼", hostileDocument("A & B < C"), null, ["A &amp; B &lt; C"], ["&amp;lt;"]],
  // GFM 的延伸自動連結會把散文裡的 http(s)://、ftp:// 與 www. 變成可點的連結；
  // 跳脫冒號與點之後渲染出的文字不變，但不再是連結。相鄰控制：不接 // 的冒號與一般的點不動。
  ["純文字網址不被自動轉成連結", hostileDocument("見 https://evil.example/x 或 WWW.example.invalid、ftp://h/f"), null,
    ["https\\:/\\/evil.example/x", "WWW\\.example.invalid", "ftp\\:/\\/h/f"], ["https:", "WWW.example", "ftp:", "//"]],
  // 其他會被自動轉成連結的寫法：緊貼在英數字後面的 scheme、mailto:／xmpp:、電子郵件地址，
  // 以及只剩 // 開頭的網址（markdown-it 的 linkify 認得）。
  ["緊貼英數字的 scheme、mailto、xmpp、電子郵件與 // 網址都不成連結",
    hostileDocument("1http://glued.example mailto:a@b.example xmpp:c@d.example user@host.example x;//rel.example"), null,
    ["1http\\:/\\/glued.example", "mailto\\:a\\@b.example", "xmpp\\:c\\@d.example", "user\\@host.example",
      "x;/\\/rel.example"],
    ["http:", "mailto:", "xmpp:", "a@b", "user@host", ";//"]],
  ["不像網址或郵件的 @ 與斜線不跳脫（相鄰控制）", hostileDocument("@ 開頭、結尾@、1/2、a / b"), null,
    ["@ 開頭、結尾@、1/2、a / b"], ["\\@", "\\/"]],
  ["時刻的冒號與小數點不跳脫（相鄰控制）", hostileDocument("12:30 與 22.9908、abcwww.x"), null,
    ["12:30 與 22.9908、abcwww.x"], ["12\\:30", "22\\.9908", "abcwww\\."]],
  ["表格儲存格只 escape 一次、裸 CR 不破表", hostileDocument("alpha|beta\\gamma\rnext"), null,
    ["alpha\\|beta\\\\gamma<br>next"], ["alpha\\\\\\|", "\r"]],
  ["一般文字與表格結構不變（相鄰控制）", hostileDocument("台南 22.9915"), null,
    ["## 標題 台南 22.9915", "| 地點標籤 | 台南 22.9915 |", "| --- | --- |"], []],
  // 文件末端的 dossier JSON code fence 內仍是原值（fence 內不解析 Markdown），這裡只查散文插值點。
  ["authority 插值點經過 escape", sectionDocument({ id: "s", title: "s" }, (response) => {
    response.calculation_dossier.authority = "<script>alert(1)</script> & more";
  }), "- Authority:", ["&lt;script&gt;"], ["<script>"]],
  // inline code span 內的反引號會提早關閉 span。
  ["UTC 的 code span 避開內容裡的反引號", sectionDocument({ id: "s", title: "s" }, (response) => {
    response.calculation_dossier.time_conversion.utc_iso_8601 = "1997`x`Z";
  }), "- UTC:", [": ``"], []],
  ["blocks 的 fence 依內容加長", sectionDocument({ id: "b", title: "測試區段", blocks: ["```\n偽造的區段外文字\n```"] }),
    null, ["\n````text\n"], []],
  ["一般 block 仍用三個反引號（相鄰控制）", sectionDocument({ id: "b", title: "一般區段", blocks: ["沒有反引號的內容"] }),
    null, ["```text\n沒有反引號的內容\n```"], []],
  ["reason_code 的 code span 不被內容裡的反引號提前關閉", sectionDocument({
    id: "s", title: "測試區段", status: { state: "executed_unavailable", reason_code: "alpha`偽造散文`omega" },
  }), "**狀態：**", ["``alpha`偽造散文`omega``"], []],
  ["一般 reason_code 仍用單一反引號（相鄰控制）", sectionDocument({
    id: "s", title: "測試區段", status: { state: "not_requested", reason_code: "house_not_requested" },
  }), "**狀態：**", ["`house_not_requested`"], []],
  ["表格儲存格的裸 CR 轉成 <br>", sectionDocument({
    id: "t", title: "測試表", tables: [{ columns: ["A", "B"], rows: [["left\rright", "ok"]] }],
  }), null, ["left<br>right"], ["\r"]],
  ["CRLF 只產生一個 <br>", sectionDocument({
    id: "t", title: "測試表", tables: [{ columns: ["A"], rows: [["a\r\nb"], ["c\nd"]] }],
  }), null, ["a<br>b", "c<br>d"], ["<br><br>"]],
  ["散文欄位的換行不能偽造標題", sectionDocument({
    id: "h", title: "first\n# forged\tcell\rend", layer_label: "first\n# forged\tcell\rend",
    notes: ["first\n# forged\tcell\rend"],
  }), null, ["\\# forged"], ["\n# forged"]],
  ["~~ 與行首清單／分隔線標記", sectionDocument({
    id: "probe", title: "~~struck~~", layer_label: "- not a list",
    notes: ["- item", "1. numbered", "---", "1) paren"],
  }), null, ["\\~\\~struck\\~\\~", "> \\- item", "> 1\\. numbered", "> 1\\) paren", "\\- not a list"],
  ["~~struck~~", "\n> - item\n", "\n> ---\n"]],
];

test("Markdown 在每一個自由文字插值點中和 HTML、反引號、換行與行首標記", () => {
  for (const [name, document, linePrefix, includes, excludes] of markdownCases()) {
    const markdown = Exporters.renderMarkdown(document);
    const scope = linePrefix === null
      ? markdown
      : markdown.split("\n").find((line) => line.startsWith(linePrefix));
    assert.ok(scope, `${name}：找不到 ${linePrefix} 這一行`);
    includes.forEach((text) => assert.ok(scope.includes(text), `${name}：缺 ${JSON.stringify(text)}\n${scope}`));
    excludes.forEach((text) => assert.ok(!scope.includes(text), `${name}：仍有 ${JSON.stringify(text)}\n${scope}`));
  }
});

// CommonMark 0.31 §6.1 的 code span，獨立實作：開頭一段反引號串（長度 n），到下一段長度恰為 n
// 的反引號串結束；內容的換行改成空白，首尾都是空白且不全是空白時各去掉一個。
function parseCodeSpan(fragment) {
  const runAt = (index) => {
    let end = index;
    while (fragment[end] === "`") end += 1;
    return end - index;
  };
  const open = runAt(0);
  if (!open) return null;
  let index = open;
  while (index < fragment.length) {
    if (fragment[index] !== "`") { index += 1; continue; }
    const run = runAt(index);
    if (run === open) {
      let content = fragment.slice(open, index).replace(/\r\n|\r|\n/g, " ");
      if (content.length > 2 && content[0] === " " && content[content.length - 1] === " " && content.trim() !== "") {
        content = content.slice(1, -1);
      }
      return { fence: open, content, end: index + run };
    }
    index += run;
  }
  return null;
}

function longestRun(value) {
  let longest = 0;
  let current = 0;
  for (const char of value) {
    current = char === "`" ? current + 1 : 0;
    longest = Math.max(longest, current);
  }
  return longest;
}

test("Markdown 行內代碼用比內容最長反引號串多一個的圍欄（最少 1 個），依 CommonMark 讀回原字串", () => {
  const cases = [
    "house_not_requested", "1990-05-15T06:30:00Z", "a`b", "alpha`偽造散文`omega", "``x", "x`", "a```b",
    "` `", " a ", "x``y`z", "````",
  ];
  for (const code of cases) {
    const document = sectionDocument({
      id: "s", title: "測試區段", status: { state: "executed_unavailable", reason_code: code },
    });
    const line = Exporters.renderMarkdown(document).split("\n").find((row) => row.startsWith("**狀態：**"));
    const fragment = line.slice(line.indexOf("（原因代碼 ") + "（原因代碼 ".length, -"）".length);
    const span = parseCodeSpan(fragment);
    const label = JSON.stringify(code);
    assert.ok(span, `${label}：${fragment} 不是 code span`);
    assert.equal(span.end, fragment.length, `${label}：code span 提前結束於 ${fragment}`);
    assert.equal(span.content, code, `${label}：讀回的內容`);
    assert.equal(span.fence, longestRun(code) + 1, `${label}：圍欄長度 ${fragment}`);
  }
  // 只有 fenced code block 需要至少三個反引號；blocks 與 Dossier JSON 仍是三個（相鄰控制）。
  const block = Exporters.renderMarkdown(sectionDocument({ id: "b", title: "一般區段", blocks: ["內容"] }));
  assert.ok(block.includes("\n```text\n內容\n```\n"), "block fence");
  assert.ok(block.includes("\n```json\n{"), "Dossier JSON fence");
});

test("純文字與區段複製守住欄列結構；JSON 與 CSV 不做 HTML escaping", () => {
  const forged = (response) => response.calculation_dossier.warnings.push({
    code: "X\r\n## forged",
    message: "line one\n注意［FAKE］: line two\rend",
  });
  const hostileProse = sectionDocument({
    id: "h", title: "first\n# forged\tcell\rend", layer_label: "first\n# forged\tcell\rend",
    notes: ["first\n# forged\tcell\rend"],
  });
  const sectionText = (rows) => Exporters.renderSectionText(cellsDocument(rows).sections[0]);
  const cases = [
    // 儲存格內的 tab 會多切一欄、換行會拆列，而貼進試算表的人不會察覺錯位；裸 CR 本身就是列界。
    ["tab 與 LF", sectionText([["a\tb", "c\nd"]]), ["\na b\tc d"], ["a\tb", "c\nd"]],
    ["單獨的 CR", sectionText([["left\rright", "ok"]]), ["\nleft right\tok"], ["\r"]],
    ["CRLF 與 LF 各折成一個空白", sectionText([["a\r\nb", "c\nd"]]), ["\na b\tc d"], []],
    ["不含這些字元的儲存格逐字不變", sectionText([["太陽", "23°26′31.79″"]]), ["case\tvalue", "\n太陽\t23°26′31.79″"], []],
    ["散文欄位", Exporters.renderPlainText(hostileProse), [], ["\n# forged", "\r"]],
    ["warning 不能偽造紀錄", Exporters.renderPlainText(sectionDocument({ id: "s", title: "s" }, forged)),
      [], ["\n## forged", "\n注意［FAKE］", "\r"]],
    ["運算結果模式的 warning", Exporters.renderPlainText(Exporters.projectOutputDocument(
      sectionDocument({ id: "s", title: "s" }, forged), "chart_data_only")), [], ["\n注意［FAKE］", "\r"]],
    // escaping 只屬於 Markdown serializer：JSON 保存原始位元組，CSV 的守衛是公式中和。
    ["JSON 不做 HTML escaping", Exporters.renderJson(hostileDocument("<img src=x>")), ["<img src=x>"], []],
    ["CSV 不做 HTML escaping", Exporters.renderCsv(hostileDocument("<img src=x>")), ["<img src=x>"], []],
  ];
  for (const [name, output, includes, excludes] of cases) {
    includes.forEach((text) => assert.ok(output.includes(text), `${name}：缺 ${JSON.stringify(text)}`));
    excludes.forEach((text) => assert.ok(!output.includes(text), `${name}：仍有 ${JSON.stringify(text)}`));
  }
});

// UTC 偏移曾經印成「+08:00:00」（試算表讀成公式，CSV 加撇號）與「−04:00:00」
// （U+2212，不加撇號），同一欄有的帶撇號、有的不帶，負號也與度分秒的 ASCII「-」不一致。偏移改寫成
// 「UTC+08:00」：不以正負號開頭，就不必中和，每一種輸出都是同一個字串。正確答案由回應的
// utc_offset_hours 以獨立的算法換算（整數秒、四捨五入），不讀 view-model 的格式函式。
function expectedOffset(hours) {
  const seconds = Math.round(Math.abs(hours) * 3600);
  const parts = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
  const shown = parts[2] ? parts : parts.slice(0, 2);
  return `UTC${hours < 0 ? "-" : "+"}${shown.map((part) => String(part).padStart(2, "0")).join(":")}`;
}

test("UTC 偏移在每一種輸出都是同一個「UTC±hh:mm」字串，不以正負號開頭、不帶公式撇號", (t) => {
  if (skipIfOmitted(t, ["page/chart-exact.json", "page/chart-repeated-hour-fold.json"])) return;
  const signs = new Set();
  for (const name of ["chart-exact", "chart-repeated-hour-fold"]) {
    const page = loadResponse(`page/${name}.json`);
    const hours = page.astronomical_data.time.utc_offset_hours;
    signs.add(Math.sign(hours));
    const offset = expectedOffset(hours);
    const document = canonicalDocument(page);
    const dataOnly = Exporters.OUTPUT_MODES.chart_data_only;
    const render = (format) => Exporters.buildDownloadArtifact(document, format, dataOnly).content;
    const timeSection = document.sections.find((section) => section.id === "time");
    assert.ok(render("txt").includes(`UTC 偏移\t${offset}`), `${name} TXT 必須印出 ${offset}`);
    assert.ok(Exporters.renderSectionText(timeSection).includes(`UTC 偏移\t${offset}`), `${name} 區段複製`);
    // 長格式：時間表的「UTC 偏移」那一列，其「數值」欄（同一區段、表、列）。
    const csvRows = parseCsvRows(render("csv"));
    const offsetCells = csvRows.filter((row) => row[0] === "time" && row[4] === "項目" && row[5] === "UTC 偏移")
      .map((label) => csvRows.find((row) => row[0] === "time" && row[2] === label[2] && row[3] === label[3] && row[4] === "數值")[5]);
    assert.deepEqual(offsetCells, [offset], `${name} CSV 的 UTC 偏移格`);
    assert.match(render("md"), new RegExp(`\\| UTC 偏移 \\| ${offset.replace("+", "\\+")} \\|`), `${name} Markdown`);
  }
  assert.deepEqual([...signs].sort(), [-1, 1], "fixture 必須涵蓋正負兩種偏移");
});

// 「運算結果」不得刪掉未請求的區段（讀者才知道那一區是沒請求、不是不存在），
// 驗算區段與收據只在「運算結果＋驗算資料」。
test("both detail modes keep chart data across copy and every format; only the detailed one carries trace and receipt", () => {
  const { response } = fixture();
  response.calculation_dossier.warnings.push({ code: "provisional_method_result", message: "internal-method-warning" });
  const document = Exporters.createDocument(response, [
    { id: "bodies", title: "天體", tables: [], notes: ["core-chart-data"], blocks: [] },
    {
      id: "lots", title: "阿拉伯點", status: { state: "not_requested", reason_code: "option_not_requested" },
      tables: [], notes: ["本次未請求阿拉伯點。"], blocks: [],
    },
    { id: "trace", title: "逐步計算軌跡", tables: [], notes: [], blocks: ["reproducibility-trace"] },
    { id: "receipt", title: "收據", tables: [], notes: [], blocks: ["reproducibility-receipt"] },
  ]);
  const ids = Exporters.projectOutputDocument(document, "chart_data_only").sections.map((s) => s.id);
  assert.ok(ids.includes("lots") && !ids.includes("trace"), ids.join(","));
  const renderers = {
    copy: (mode) => Exporters.renderPlainText(Exporters.projectOutputDocument(document, mode)),
    ...Object.fromEntries(["json", "csv", "md", "txt"].map((format) => [
      format, (mode) => Exporters.buildDownloadArtifact(document, format, mode).content,
    ])),
  };
  for (const [format, render] of Object.entries(renderers)) {
    const dataOnly = render("chart_data_only");
    const detailed = render("reproducibility_detail");
    assert.ok(dataOnly.includes("core-chart-data") && detailed.includes("core-chart-data"), `${format} dropped chart data`);
    for (const technical of ["reproducibility-trace", "reproducibility-receipt"]) {
      assert.ok(!dataOnly.includes(technical), `${format} leaked ${technical}`);
      assert.ok(detailed.includes(technical), `${format} lost ${technical}`);
    }
    assert.ok(dataOnly.includes("阿拉伯點"), `${format} 沒有列出未請求的區段`);
    if (format !== "copy") {
      const marker = format === "csv" || format === "json" ? "not_requested" : "未請求";
      assert.ok(dataOnly.includes(marker), `${format} 沒有帶出未請求狀態`);
    }
  }
  const compact = renderers.json("chart_data_only");
  const detailedJson = renderers.json("reproducibility_detail");
  for (const internal of ["calculation_dossier", "internal-method-warning"]) {
    assert.ok(!compact.includes(internal), internal);
    assert.ok(detailedJson.includes(internal), internal);
  }
});

test("JSON 匯出把 -0 寫成 0（值相等、非位元相等）", () => {
  const { response } = fixture();
  response.astronomical_data = { ...(response.astronomical_data || {}), negative_zero_probe: -0 };
  const json = Exporters.renderJson(Exporters.createDocument(response, []));
  assert.ok(json.includes('"negative_zero_probe": 0'), json.slice(0, 400));
  assert.ok(!json.includes('"negative_zero_probe": -0'), json.slice(0, 400));
});

test("printExpansion 展開每個 details 並在 restore 時還原原狀", () => {
  const details = [{ open: false }, { open: true }, { open: false }];
  const restore = Exporters.printExpansion(details);
  assert.deepEqual(details.map((d) => d.open), [true, true, true]);
  restore();
  assert.deepEqual(details.map((d) => d.open), [false, true, false]);
  // 冪等：afterprint 可能被觸發兩次。
  restore();
  assert.deepEqual(details.map((d) => d.open), [false, true, false]);
});


// 版本相容但結構被截斷的回應要大聲拒絕。判準由後端自己的單一狀態產生器給：calculation_policy.option_states 裡 executed=true、
// available=true 的選項，其 response_paths 必須在回應裡真的有內容。畫面不得把「後端說算了、
// 容器卻不見」渲染成「少了幾區」的正常結果。
test("option_states 說已算出的模組容器缺席時 createDocument 拒絕", (t) => {
  const responseFixtures = ["chart-approximate-hour", "chart-exact", "chart-date-only"];
  if (skipIfOmitted(t, responseFixtures.map((name) => `${name}.json`), "；此樹無法以真實回應驗證截斷拒絕")) return;
  const load = (name) => loadResponse(`${name}.json`);
  const real = load("chart-approximate-hour");
  assert.doesNotThrow(() => Exporters.createDocument(real, []));
  for (const [label, mutate] of [
    ["容器整個不見", (response) => { delete response.derived_methods.lots; }],
    ["容器是 null", (response) => { response.astronomical_data.horizon_events = null; }],
    ["容器是空物件", (response) => { response.derived_methods.void_of_course = {}; }],
    ["巢狀路徑不見", (response) => { delete response.astronomical_data.lunar_events.eclipses; }],
    ["整層不見", (response) => { delete response.derived_methods; }],
  ]) {
    const truncated = structuredClone(real);
    mutate(truncated);
    assert.throws(() => Exporters.createDocument(truncated, []), /結構不完整/, label);
  }
  // 相鄰控制：沒有請求的模組容器為空是正常形狀，不得被當成截斷。
  for (const name of responseFixtures.filter((candidate) => candidate !== "chart-approximate-hour")) {
    assert.doesNotThrow(() => Exporters.createDocument(load(name), []), name);
  }
});

// 預設「運算結果」匯出必須說出經度的參考框架。頁面投影曾經丟掉 computation_mode，框架只留在驗算資料的「計算政策」收據裡；
// 恆星黃道的盤匯出後與回歸黃道無從分辨。基線 03701324 的運算結果 JSON 在
// source_response 頂層帶著 computation_mode，這裡要求同一個位置、同一個值。
test("恆星／回歸黃道的預設匯出四種格式都寫出黃道，JSON 帶 computation_mode", (t) => {
  if (skipIfOmitted(t, ["chart-exact.json", "page/chart-exact.json"])) return;
  const tropicalPage = loadResponse("page/chart-exact.json");
  const tropical = loadResponse("chart-exact.json");
  assert.deepEqual(tropicalPage.computation_mode, tropical.computation_mode,
    "頁面投影必須保留與完整回應相同的 computation_mode");
  // 恆星黃道：同一份頁面回應換上恆星黃道的 computation_mode（後端回應裡的形狀）。
  const siderealPage = structuredClone(tropicalPage);
  siderealPage.computation_mode = { ...tropicalPage.computation_mode, zodiac: "sidereal" };
  for (const [name, page, zodiac, ayanamsaShown, zodiacZh] of [
    ["sidereal", siderealPage, "sidereal", true, "恆星黃道"],
    ["tropical", tropicalPage, "tropical", false, "回歸黃道"],
  ]) {
    const document = canonicalDocument(page);
    const render = (format) => Exporters.buildDownloadArtifact(document, format, Exporters.OUTPUT_MODES.chart_data_only).content;

    const txt = render("txt");
    const md = render("md");
    const csv = render("csv");
    const json = JSON.parse(render("json"));
    const ayanamsa = page.computation_mode.ayanamsa;
    assert.ok(txt.includes(`計算模式: 黃道 ${zodiacZh}［${zodiac}］；`), `${name} TXT：${txt.slice(0, 300)}`);
    assert.ok(md.includes(`- 計算模式: 黃道 ${zodiacZh}［${zodiac}］；`), `${name} Markdown：${md.slice(0, 300)}`);
    assert.ok(csv.includes(`_computation_mode,計算模式,計算模式,1,黃道,${zodiac},zodiac`),
      `${name} CSV`);
    // 代碼裡夾在英數字之間的 `_` 不跳脫（escapeMarkdownText），Markdown 原樣含代碼。
    for (const text of [txt, md, csv]) {
      assert.equal(text.includes(ayanamsa), ayanamsaShown,
        `${name}：歲差校正只在恆星黃道下印出`);
    }
    assert.deepEqual(json.source_response.computation_mode, page.computation_mode,
      `${name} JSON：source_response.computation_mode 與回應同位置同值`);
    // 純文字複製與 TXT 下載同一份位元組（契約：Full copy／TXT identical）。
    assert.equal(
      Exporters.renderPlainText(Exporters.projectOutputDocument(document, "chart_data_only")),
      txt
    );
  }
});

// RFC 4180 讀回（CRLF 列界、雙引號跳脫）；BOM 只在下載前綴，renderCsv 本身沒有。
function parseCsvRows(content, delimiters = ",") {
  const rows = [];
  let row = [];
  let cell = "";
  let quoted = false;
  const body = content.replace(/^﻿/, "");
  for (let index = 0; index < body.length; index += 1) {
    const char = body[index];
    if (quoted) {
      if (char === '"' && body[index + 1] === '"') { cell += '"'; index += 1; }
      else if (char === '"') quoted = false;
      else cell += char;
    } else if (char === '"') quoted = true;
    else if (delimiters.includes(char)) { row.push(cell); cell = ""; }
    else if (char === "\r" && body[index + 1] === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; index += 1; }
    else cell += char;
  }
  row.push(cell);
  rows.push(row);
  return rows;
}

// 匯出自己的結構字彙（CSV 表頭、表名與欄位名、注意事項的標題）是讀者看的標籤，一律中文；
// 閉集代碼（區段狀態、原因、注意事項代碼、計算模式的鍵）只放在 CSV 的「代碼」欄。資料表格的
// 標題與欄名是 view-model 的內容，不在此限；Dossier 的 JSON 路徑列是機器可讀的收據本身。
const SNAKE_CASE = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b/;
const ASCII_WORD = /^[A-Za-z][A-Za-z ]*$/;
test("匯出的結構字彙是中文，閉集代碼另放在代碼欄（兩種模式、真實回應）", (t) => {
  if (skipIfOmitted(t, ["chart-heliocentric-all.json", "page/chart-heliocentric-all.json"])) return;
  for (const [mode, response] of [
    ["chart_data_only", loadResponse("page/chart-heliocentric-all.json")],
    ["reproducibility_detail", loadResponse("chart-heliocentric-all.json")],
  ]) {
    const document = canonicalDocument(response);
    const projected = Exporters.projectOutputDocument(document, mode);
    const dataTables = new Set(projected.sections.flatMap((section) => section.tables.map((table) => table.title)));
    const render = (format) => Exporters.buildDownloadArtifact(document, format, mode).content;
    const rows = parseCsvRows(render("csv"));
    assert.deepEqual(rows[0], ["區段代碼", "區段", "表", "列", "欄位", "值", "代碼"], `${mode} CSV 表頭`);
    const structural = rows.slice(1).filter((row) => row[0] !== "_dossier" && !dataTables.has(row[2]));
    assert.ok(structural.length > 0, `${mode}：沒有結構列可檢查`);
    for (const row of structural) {
      for (const [column, value] of [["表", row[2]], ["欄位", row[4]]]) {
        assert.ok(!SNAKE_CASE.test(value) && !ASCII_WORD.test(value), `${mode} CSV ${column}「${value}」：${row.join(",")}`);
      }
    }
    // 狀態列：值是中文標籤、代碼欄是閉集代碼；兩者對應同一個區段狀態。
    const statusRows = structural.filter((row) => row[2] === "狀態" && row[4] === "狀態");
    assert.ok(statusRows.length > 0, `${mode}：沒有狀態列`);
    statusRows.forEach((row) => {
      const section = projected.sections.find((candidate) => candidate.id === row[0]);
      assert.deepEqual([row[5], row[6]], [section.status.label, section.status.state], row.join(","));
    });
    // 注意事項：值是訊息、代碼欄是代碼。
    const warnings = structural.filter((row) => row[0] === "_warnings");
    assert.deepEqual(warnings.map((row) => [row[5], row[6]]),
      JSON.parse(render("json")).warnings.map((warning) => [warning.message, warning.code]));
    for (const format of ["txt", "md"]) {
      assert.doesNotMatch(render(format), /^(?:[-#]+ )?Warnings?\b/m, `${mode} ${format} 仍有英文的注意事項標記`);
    }
    assert.match(render("md"), /^## 注意事項$/m, `${mode} Markdown 的注意事項標題`);
  }
});

test("一頁摘要的收據身分：三個版本、計算模式與出生時刻把握程度，與純文字匯出（驗算資料）的行逐字相同", (t) => {
  const relatives = ["chart-exact.json", "chart-approximate-hour.json"];
  if (skipIfOmitted(t, relatives)) return;
  for (const relative of relatives) {
    const response = loadResponse(relative);
    const document = canonicalDocument(response);
    const lines = Exporters.renderPlainText(
      Exporters.projectOutputDocument(document, Exporters.OUTPUT_MODES.reproducibility_detail)
    ).split("\n");
    // 版本字串另以回應與匯出器常數核對，不只與同一個產生器的輸出比。
    const versions = Exporters.contractVersionLines(document);
    assert.deepEqual(versions, [
      `Export Contract ${Exporters.EXPORT_CONTRACT_VERSION}`,
      `API Schema ${response.schema_version}`,
      `Calculation Dossier ${response.calculation_dossier.dossier_version}`,
    ]);
    const start = lines.indexOf(versions[0]);
    assert.ok(start > 0, relative);
    assert.deepEqual(lines.slice(start, start + 3), versions);
    const mode = Exporters.computationModeLine(document.source_response);
    assert.ok(lines.includes(`${mode.label}: ${mode.value}`), `${relative} 計算模式`);
    const precision = Exporters.inputAssumptionEntries(document).find((entry) => entry.key === "birth_time_precision");
    assert.equal(precision.code, response.birth_time_sensitivity.precision);
    assert.ok(lines.includes(Exporters.inputAssumptionText(precision)), `${relative} 出生時刻把握程度`);
  }
});
