/**
 * 把表單的原始字串變成請求輸入，或明確說出哪裡不對。「沒填」與「填了但不合法」不得壓成同一個回傳值。壓成同一個之後：
 * `Math.trunc` 讓「12.5 時」靜默變成 12 時；  `readInteger(x) || 0` 讓 NaN 靜默變成 0，也讓秒的小數整個消失；  數字選項
 * 的 UI 範圍與 API 契約不一致，送出後才由伺服器回 422。共同的形狀是「介面接受了一個它算不出來的值，而且不說」。因此這裡
 * 的回傳一律是封閉三態 empty / invalid / value：呼叫端無法再把 invalid 當成 0。表單帶 `novalidate`（送出時不得讓瀏覽器
 * 原生驗證接手，否則出生資料會落進 query string），所以 min/max 必須在這裡自己檢查，不能倚賴 HTML 屬性。
 */
(function attachRequestInput(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.RequestInput = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildRequestInput() {
  "use strict";

  const EMPTY = "empty";
  const INVALID = "invalid";
  const VALUE = "value";

  const INTEGER_PATTERN = /^[+-]?\d+$/;

  function empty() { return { state: EMPTY }; }

  function invalid(reason) { return { state: INVALID, reason }; }

  function value(number) { return { state: VALUE, value: number }; }

  /** 時與分：嚴格整數。`12.5`、`1e2`、`abc` 都是錯誤，不是 12、100 或 0。 */
  function readInteger(raw) {
    const text = String(raw === undefined || raw === null ? "" : raw).trim();
    if (text === "") return empty();
    // 先比對字面形狀再轉數字。Number("12.5") 是合法有限數，只看 Number.isFinite 分不出「整數欄位被填了小數」這件事。
    if (!INTEGER_PATTERN.test(text)) return invalid("必須是整數");
    const parsed = Number(text);
    if (!Number.isSafeInteger(parsed)) return invalid("超出可精確表示的整數範圍");
    return value(parsed);
  }

  // 一個數在最短十進位寫法下的小數位數。JSON.stringify 送出的就是這個寫法，
  // 後端 core/time_utils.exact_second_microseconds 也以 Python 的同一種寫法（repr）計數，
  // 兩邊因此對同一個值得到同一個答案：String(1e-7) 是 "1e-7"，算七位。
  const SHORTEST_DECIMAL = /^\d+(?:\.(\d+))?(?:e([+-]\d+))?$/;

  function fractionDigits(number) {
    const match = SHORTEST_DECIMAL.exec(String(number));
    if (!match) return Infinity;
    return Math.max((match[1] || "").length - Number(match[2] || 0), 0);
  }

  /**
   * 秒：唯一允許小數的時間欄位；60只可能是後端另行驗證的UTC閏秒。小數必須保留——截斷會算出使用者沒有輸入的時刻。所以比微
   * 秒更細的值不在這裡捨去，而是與後端一樣拒絕：捨入會把 59.9999999 帶進下一分鐘，甚至越過時鐘跳躍或閏秒。
   */
  function readSecond(raw) {
    const read = readDecimal(raw);
    if (read.state !== VALUE) return read;
    if (read.value < 0 || read.value > 60) return invalid("必須介於 0 與 60 之間");
    if (fractionDigits(read.value) > 6) return invalid("最多到小數第六位（微秒）");
    return read;
  }

  function readDecimal(raw) {
    const text = String(raw === undefined || raw === null ? "" : raw).trim();
    if (text === "") return empty();
    const parsed = Number(text);
    return Number.isFinite(parsed) ? value(parsed) : invalid("必須是數字");
  }

  /** 數字選項：範圍取自 options catalogue 同一份宣告，介面屬性與這裡的檢查因此不可能各說各話。回傳 null 表示通過。 */
  function boundsProblem(option, candidate) {
    if (candidate === null || candidate === undefined) return null;
    if (!Number.isFinite(candidate)) return "必須是數字";
    if (option.min !== undefined && candidate < option.min) { return `不得小於 ${option.min}`; }
    if (option.max !== undefined && candidate > option.max) { return `不得大於 ${option.max}`; }
    return null;
  }

  /**
   * 逐一檢查目前**送得出去**的數字選項。判準是 `isReachable`（相依鏈成立）而不是 `isEnabled`——後者的意思是「與預設不
   * 同」，用它會讓使用者被一個他根本沒開啟的欄位擋下來，也會漏掉「值剛好等於預設但父項已開啟」的情形。
   */
  function numericOptionProblems(catalogue, values) {
    const problems = [];
    catalogue.OPTIONS.forEach((option) => {
      if (option.type !== "number") return;
      if (!catalogue.isReachable(option, values)) return;
      if (catalogue.conflictFor(option, values)) return;
      const candidate = values[option.key];
      // 清空一個「預設值不是 null」的數字欄位，會送出 null 而不是省略該鍵——因為 null 與預設不同，`toRequestOptions` 就
      // 把它帶上，後端則回 `float_type` 422。其餘三個數字選項預設就是 null，清空等於省略，所以只有這一類會踩到。
      // 不自動填回預設：那是把使用者沒有輸入的值算進結果，正是靜默改值。所以明講這欄必填。
      if (candidate === null || candidate === undefined) {
        if (option.default !== null && option.default !== undefined) { problems.push(`${option.label_zh} 必須填寫（或關閉這個選項）`); }
        return;
      }
      const problem = boundsProblem(option, candidate);
      if (problem) problems.push(`${option.label_zh} ${problem}`);
    });
    return problems;
  }

  // 模糊民用時刻 DST 結束當天，同一個時鐘時間在該時區出現兩次，對應兩個相差一小時的 UTC 時刻。後端支援 PEP 495 的
  // `fold` 讓呼叫端指明是哪一次，前端卻只送得出 `{mode:"iana", iana_name}`，因此永遠是 fold=0——使用者可能拿到另一個時刻
  // 算出的盤，上升點差約 15°，而畫面不會說。
  // 這不是只影響歐美：Asia/Taipei 在 1937、1945–1961、1974、1975、1979 之間共有 40 個這樣的小時。

  const DAY_MS = 86400000;

  // 一個整小時的判定要問上百次偏移（見 civilHourOccurrences），每次新建 DateTimeFormat 太貴；同一個時區共用一個。只快取
  // 時區名稱對應的格式器，不含任何時刻。
  const formatters = new Map();

  function zoneFormatter(timeZone) {
    let formatter = formatters.get(timeZone);
    if (!formatter) {
      formatter = new Intl.DateTimeFormat("en-US", {
        timeZone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
      formatters.set(timeZone, formatter);
    }
    return formatter;
  }

  /**
   * 年月日時分秒 → UTC 毫秒，與 Date.UTC 相同的進位規則，但年份照字面。Date.UTC 把 0–99 年當成 1900–1999 年（西元 50 年
   * 會被算成 1950 年，連帶套上 1950 年的夏令時間），所以先設年月日、再設時分秒，各自由 setUTC* 進位。
   */
  function civilUtcMillis(year, monthIndex, day, hour = 0, minute = 0, second = 0) {
    const instant = new Date(0);
    instant.setUTCFullYear(year, monthIndex, day);
    instant.setUTCHours(hour, minute, second, 0);
    return instant.getTime();
  }

  function zoneOffsetMinutes(utcMillis, timeZone) {
    const formatter = zoneFormatter(timeZone);
    const parts = {};
    formatter.formatToParts(new Date(utcMillis)).forEach((part) => { parts[part.type] = part.value; });
    const asIfUtc = civilUtcMillis(
      Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), Number(parts.second)
    );
    return (asIfUtc - utcMillis) / 60000;
  }

  /**
   * `unique`      —— 一般情形，一個瞬間；  `ambiguous`   —— 秋季調慢，出現兩次，使用者必須指明是哪一次；  `nonexistent`
   * —— 春季調快跳過的那一小時，這個時間不存在。
   * 判法：取前後各一天的偏移作為候選（一次轉換至多改變其中之一），再讓每個候選瞬間自己回答「你的偏移真的是這個嗎」。只
   * 挑通過自我驗證的。直接對 `Date` 做時區運算會踩到宿主時區，所以全程用 UTC 毫秒。
   */
  function civilTimeOccurrences(fields, timeZone) {
    if (!timeZone) return null;
    const { year, month, day, hour, minute, second } = fields;
    for (const part of [year, month, day, hour, minute]) { if (!Number.isFinite(part)) return null; }
    // 整秒以下只截斷：時區的偏移只在整秒改變，而後端也以精確值判定、
    // 從不把 59.999999 進位到下一分鐘，所以兩邊對同一個值的判定相同。
    const wholeSeconds = Math.floor(Number.isFinite(second) ? second : 0);
    let wall;
    try {
      wall = civilUtcMillis(year, month - 1, day, hour, minute, wholeSeconds);
      // 探一次，時區名稱不合法時 Intl 會丟。
      zoneOffsetMinutes(wall, timeZone);
    } catch (_error) { return null; }
    const nearby = [zoneOffsetMinutes(wall - DAY_MS, timeZone), zoneOffsetMinutes(wall + DAY_MS, timeZone)];
    const seen = new Set();
    const occurrences = [];
    nearby.forEach((offset) => {
      const utcMillis = wall - offset * 60000;
      if (seen.has(utcMillis)) return;
      if (zoneOffsetMinutes(utcMillis, timeZone) !== offset) return;
      seen.add(utcMillis);
      occurrences.push({ utcMillis, offsetMinutes: offset });
    });
    // PEP 495：fold=0 是較早的那個瞬間。
    occurrences.sort((a, b) => a.utcMillis - b.utcMillis);
    if (!occurrences.length) return { state: "nonexistent", occurrences: [] };
    return {
      state: occurrences.length > 1 ? "ambiguous" : "unique",
      occurrences: occurrences.map((item, index) => ({
        fold: index, offsetHours: item.offsetMinutes / 60, utcIso: new Date(item.utcMillis).toISOString(),
      })),
    };
  }

  // 大約時辰：整個民用小時裡有沒有任何一段重複後端對 approximate_hour 取樣的是整個小時（:30 錨點、每 15 分鐘、59:59，再
  // 加上小時內每一次偏移變更的兩側），只要其中有重複的瞬間就要求 fold。只看 HH:00:00 會漏掉重複區段在小時中間開始或結束
  // 的情形：America/St_Johns 2005-10-29 在 00:01 調回，重複的是 23:01–00:00:59；Australia/Lord_Howe 2024-04-07 重複
  // 01:30–01:59:59。整點本身都只出現一次。判法與後端 _utc_offset_changes／_clock_change_edge_offsets 相同：在涵蓋這個小
  // 時所有可能瞬間（前後再各留一小時）的 UTC 區間裡逐分鐘找偏移變更、精修到整秒；偏移變小（時鐘往回撥）的每一次變更，重
  // 複的鐘面區間是 [變更瞬間＋新偏移, 變更瞬間＋舊偏移)，與這個小時有交集就算模糊。

  const SECOND_MS = 1000;
  const MINUTE_MS = 60 * SECOND_MS;
  const HOUR_MS = 60 * MINUTE_MS;
  // 後端 PROBE_OFFSETS_SECONDS 的代表點順序（approximate_hour_representative_request）：
  // 先 :30，再其餘取樣點。選擇區列出的兩個世界時取自第一個落在重複區段裡的點。
  const HOUR_LABEL_PREFERENCE_SECONDS = [1800, 0, 900, 2700, 3599];

  /** 第一個偏移等於 `after` 的整秒，介於 (lo, hi]。 */
  function refineChange(lo, hi, timeZone, after) {
    let left = lo;
    let right = hi;
    while (right - left > SECOND_MS) {
      const middle = left + Math.floor((right - left) / (2 * SECOND_MS)) * SECOND_MS;
      if (zoneOffsetMinutes(middle, timeZone) === after) right = middle;
      else left = middle;
    }
    return right;
  }

  function offsetChanges(startUtc, endUtc, timeZone) {
    const changes = [];
    let previous = zoneOffsetMinutes(startUtc, timeZone);
    for (let t = startUtc + MINUTE_MS; t <= endUtc; t += MINUTE_MS) {
      const current = zoneOffsetMinutes(t, timeZone);
      if (current !== previous) {
        changes.push({ atUtc: refineChange(t - MINUTE_MS, t, timeZone, current), before: previous, after: current });
        previous = current;
      }
    }
    return changes;
  }

  /**
   * 一個民用小時（`hour` 那一整個小時）在該時區是否有任何一段鐘面時間出現兩次。`ambiguous`     —— 有；`occurrences` 是
   * 重複區段裡一個代表時刻的兩次解讀                      （形狀同 civilTimeOccurrences），`repeated` 是這個小時內
   * 重複的鐘面區間（以小時起點起算的秒數，[from, to)）；  `not_ambiguous` —— 整個小時沒有重複的瞬間（可能部分或全部不存
   * 在，那由後端判定）。時區名稱不合法或欄位不完整時回 null。
   */
  function civilHourOccurrences(fields, timeZone) {
    if (!timeZone) return null;
    const { year, month, day, hour } = fields;
    for (const part of [year, month, day, hour]) { if (!Number.isFinite(part)) return null; }
    let wallStart;
    try {
      wallStart = civilUtcMillis(year, month - 1, day, hour, 0, 0);
      zoneOffsetMinutes(wallStart, timeZone);
    } catch (_error) { return null; }
    const wallEnd = wallStart + HOUR_MS;
    const candidates = [
      zoneOffsetMinutes(wallStart - DAY_MS, timeZone), zoneOffsetMinutes(wallEnd + DAY_MS, timeZone),
      zoneOffsetMinutes(wallStart, timeZone),
    ];
    const earliest = Math.min(...candidates.map((o) => wallStart - o * MINUTE_MS)) - HOUR_MS;
    const latest = Math.max(...candidates.map((o) => wallEnd - o * MINUTE_MS)) + HOUR_MS;
    let from = null;
    let to = null;
    offsetChanges(earliest, latest, timeZone).forEach((change) => {
      if (change.after >= change.before) return;   // 往前撥：產生空隙，不是重複
      const repeatStart = Math.max(wallStart, change.atUtc + change.after * MINUTE_MS);
      const repeatEnd = Math.min(wallEnd, change.atUtc + change.before * MINUTE_MS);
      if (repeatStart >= repeatEnd) return;
      if (from === null || repeatStart < from) from = repeatStart;
      if (to === null || repeatEnd > to) to = repeatEnd;
    });
    if (from === null) return { state: "not_ambiguous", occurrences: [] };
    const firstWholeSecond = Math.ceil(from / SECOND_MS) * SECOND_MS;
    const preferred = HOUR_LABEL_PREFERENCE_SECONDS.map((seconds) => wallStart + seconds * SECOND_MS)
      .find((label) => label >= from && label < to);
    const label = preferred === undefined ? firstWholeSecond : preferred;
    const labelDate = new Date(label);
    const occurrences = civilTimeOccurrences({
      year, month, day, hour, minute: labelDate.getUTCMinutes(), second: labelDate.getUTCSeconds(),
    }, timeZone);
    if (!occurrences || occurrences.state !== "ambiguous") {
      // 理論上不會發生：重複區段裡的時刻依定義有兩個解讀。若前後一天的偏移
      // 推不出那兩個解讀（同一天內多次變更），仍回報模糊，只是不列世界時。
      return {
        state: "ambiguous", occurrences: [{ fold: 0 }, { fold: 1 }],
        repeated: { from: (from - wallStart) / SECOND_MS, to: (to - wallStart) / SECOND_MS },
      };
    }
    return {
      state: "ambiguous", occurrences: occurrences.occurrences,
      repeated: { from: (from - wallStart) / SECOND_MS, to: (to - wallStart) / SECOND_MS },
    };
  }

  // 民國年與日本年號 → 西元國曆只是年份的加法：民國紀年自 1912 年、日本自明治 6 年（1873）起都用格里曆的月日，所以月與
  // 日原樣保留。難處在改元日落在年中：明治 45 年與大正元年、大正 15 年與昭和元年同在一個西元年，因此每個年號都帶第一天
  // 與最後一天，兩端之外的日期拒絕，不挪到相鄰的年號。明治 5 年以前的舊曆日期換出來早於 1900 年，由範圍檢查拒絕。
  const ERAS = Object.freeze({
    roc: Object.freeze({ label: "民國", offset: 1911, first: [1912, 1, 1], last: null, before: null, after: null }),
    meiji: Object.freeze({ label: "明治", offset: 1867, first: null, last: [1912, 7, 29], before: null, after: "大正元年" }),
    taisho: Object.freeze({ label: "大正", offset: 1911, first: [1912, 7, 30], last: [1926, 12, 24], before: "明治 45 年", after: "昭和元年" }),
    showa: Object.freeze({ label: "昭和", offset: 1925, first: [1926, 12, 25], last: [1989, 1, 7], before: "大正 15 年", after: "平成（平成以後請直接填西元日期）" }),
  });

  const pad2 = (number) => String(number).padStart(2, "0");
  const isoDate = (year, month, day) => `${String(year).padStart(4, "0")}-${pad2(month)}-${pad2(day)}`;
  const westernText = ([year, month, day]) => `西元 ${year} 年 ${month} 月 ${day} 日`;
  const compareDates = (a, b) => (a[0] - b[0]) || (a[1] - b[1]) || (a[2] - b[2]);

  function realCalendarDate(year, month, day) {
    const probe = new Date(civilUtcMillis(year, month - 1, day));
    return probe.getUTCFullYear() === year && probe.getUTCMonth() === month - 1 && probe.getUTCDate() === day;
  }

  // 以數值比較：字串比較會讓五位數的年份（"21000-01-01"）落在 "1900" 與 "2399" 之間。
  const boundDate = (iso) => (iso ? String(iso).split("-").map(Number) : null);
  function outsideBounds(date, bounds) {
    const low = boundDate(bounds.min);
    const high = boundDate(bounds.max);
    return Boolean((low && compareDates(date, low) < 0) || (high && compareDates(date, high) > 0));
  }

  // 中文輸入法常送出全形數字（０–９）；先換成半形再比對字面形狀。
  const halfWidthDigits = (text) => text.replace(/[\uFF10-\uFF19]/g, (digit) => String(digit.charCodeAt(0) - 0xFF10));
  const DATE_PART_PATTERNS = Object.freeze({ year: /^\d{4}$/, month: /^\d{1,2}$/, day: /^\d{1,2}$/ });
  const DATE_PART_LIMITS = Object.freeze({ month: [1, 12], day: [1, 31] });
  const DATE_PART_REASONS = Object.freeze({
    year: "的年份必須是四位數的西元年（例：1990）", month: "的月份必須是 1 到 12", day: "的日必須是 1 到 31",
  });
  const DATE_PART_ORDER = Object.freeze(["year", "month", "day"]);

  /**
   * 出生日期的年、月、日三欄（西元年）。bounds 是三欄共用的 min／max（YYYY-MM-DD）。表單帶
   * novalidate，範圍在這裡檢查。回傳封閉三態；EMPTY 與 INVALID 另帶 fields：要標出的那幾欄。
   */
  function readBirthDateParts(parts, bounds) {
    const texts = DATE_PART_ORDER.map((part) => halfWidthDigits(String(parts[part] === undefined || parts[part] === null ? "" : parts[part]).trim()));
    const blank = DATE_PART_ORDER.filter((_, index) => texts[index] === "");
    if (blank.length) return { state: EMPTY, fields: blank };
    const numbers = {};
    const bad = DATE_PART_ORDER.filter((part, index) => {
      if (!DATE_PART_PATTERNS[part].test(texts[index])) return true;
      numbers[part] = Number(texts[index]);
      const limits = DATE_PART_LIMITS[part];
      return Boolean(limits && (numbers[part] < limits[0] || numbers[part] > limits[1]));
    });
    if (bad.length) return { state: INVALID, reason: DATE_PART_REASONS[bad[0]], fields: bad };
    const { year, month, day } = numbers;
    if (!realCalendarDate(year, month, day)) return { state: INVALID, reason: "在日曆上不存在，請核對月與日", fields: ["day"] };
    if (outsideBounds([year, month, day], bounds)) {
      return { state: INVALID, reason: `必須在 ${bounds.min} 到 ${bounds.max} 之間（本計算器的範圍）`, fields: ["year"] };
    }
    return value({ year, month, day, iso: isoDate(year, month, day) });
  }

  // 出生日期的一欄寫法：年月日之間用 - / . 空白或「年」「月」隔開（2000-04-04、2000/4/4、
  // 2000年4月4日），或連寫成八位數字（20000404）。年份一律四位、在前。
  const DATE_TEXT_SEPARATED = /^(\d{4})\s*[-/.年\s]\s*(\d{1,2})\s*[-/.月\s]\s*(\d{1,2})\s*日?$/;
  const DATE_TEXT_COMPACT = /^(\d{4})(\d{2})(\d{2})$/;
  const DATE_TEXT_REASON = "要寫成年、月、日，例如 2000-04-04、2000/4/4 或 20000404";

  /** 出生日期一欄：先拆成年、月、日，其餘檢查（日曆、範圍）與 readBirthDateParts 相同。 */
  function readBirthDateText(text, bounds) {
    const normalized = halfWidthDigits(String(text === undefined || text === null ? "" : text))
      .replace(/[\uFF0D\uFF0F\uFF0E\u3000]/g, (mark) => ({ "\uFF0D": "-", "\uFF0F": "/", "\uFF0E": ".", "\u3000": " " })[mark]).trim();
    if (normalized === "") return { state: EMPTY, fields: ["date"] };
    const match = DATE_TEXT_SEPARATED.exec(normalized) || DATE_TEXT_COMPACT.exec(normalized);
    if (!match) return { state: INVALID, reason: DATE_TEXT_REASON, fields: ["date"] };
    const read = readBirthDateParts({ year: match[1], month: match[2], day: match[3] }, bounds);
    return read.state === INVALID ? { ...read, fields: ["date"] } : read;
  }

  /**
   * 讀年號、年、月、日四欄，換成西元日期。bounds 是出生日期欄的 min／max
   * （YYYY-MM-DD），範圍只有那一個出處。回傳封閉三態；value 帶回顯用的換算式。
   */
  function readEraDate(fields, bounds) {
    const reads = [fields.year, fields.month, fields.day].map(readInteger);
    if (reads.every((read) => read.state === EMPTY)) return empty();
    const definition = Object.hasOwn(ERAS, fields.era) ? ERAS[fields.era] : null;
    if (!definition) return invalid("請選擇紀年");
    const [yearRead, monthRead, dayRead] = reads;
    if (reads.some((read) => read.state === EMPTY)) return invalid("年、月、日都要填");
    if (yearRead.state === INVALID) return invalid(`年份${yearRead.reason}`);
    if (monthRead.state === INVALID) return invalid(`月份${monthRead.reason}`);
    if (dayRead.state === INVALID) return invalid(`日${dayRead.reason}`);
    const eraYear = yearRead.value;
    const month = monthRead.value;
    const day = dayRead.value;
    if (eraYear < 1) return invalid("年份從元年（1）起算");
    if (month < 1 || month > 12) return invalid("月份必須是 1 到 12");
    const year = eraYear + definition.offset;
    if (!realCalendarDate(year, month, day)) return invalid("這一天不存在，請核對月與日");
    const date = [year, month, day];
    if (definition.first && compareDates(date, definition.first) < 0) {
      return invalid(`${definition.label}元年從${westernText(definition.first)}開始；這一天屬於${definition.before}`);
    }
    if (definition.last && compareDates(date, definition.last) > 0) {
      return invalid(`${definition.label}的最後一天是${westernText(definition.last)}；之後是${definition.after}`);
    }
    const iso = isoDate(year, month, day);
    if (outsideBounds(date, bounds)) {
      return invalid(`換算結果是西元 ${year} 年，超出本計算器的 ${bounds.min.slice(0, 4)}–${bounds.max.slice(0, 4)} 年範圍`);
    }
    return value({
      year, month, day, iso, eraText: `${definition.label}${eraYear === 1 ? "元年" : ` ${eraYear} 年`} ${month} 月 ${day} 日`,
      gregorianText: westernText(date), formula: `${eraYear} ＋ ${definition.offset} ＝ ${year}`,
    });
  }

  /**
   * Etc/GMT±N 的 UTC 偏移文字（例：Etc/GMT-8 → "UTC+08:00"）；其他名稱回 null。這組名稱沿用 POSIX 慣例，正負號與 UTC 偏
   * 移相反，而且是固定偏移、不隨日期改變，所以送出前就能確定。名稱是否被服務接受由 TimezoneNames 判斷，不在這裡。
   */
  function etcGmtOffsetText(name) {
    const match = /^Etc\/GMT([+-])(\d{1,2})$/.exec(String(name));
    if (!match) return null;
    const hours = Number(match[2]);
    const sign = match[1] === "-" || hours === 0 ? "+" : "-";
    return `UTC${sign}${String(hours).padStart(2, "0")}:00`;
  }

  return Object.freeze({
    STATES: Object.freeze({ EMPTY, INVALID, VALUE }), etcGmtOffsetText, ERAS, readEraDate, readBirthDateParts,
    readBirthDateText, isoDate, pad2, civilTimeOccurrences, civilHourOccurrences, readInteger, readSecond, readDecimal,
    boundsProblem, numericOptionProblems,
  });
});
