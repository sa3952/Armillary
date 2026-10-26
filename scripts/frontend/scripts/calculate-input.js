// 計算頁：地點查詢、民用時間與重複時刻、時間核對、收表單與錯誤顯示。

const PLACE_SEARCH_TIMEOUT_MS = 10000;
// 地點查詢的狀態是閉集，寫在 #place-status 的 data-state（訊息文字只是它的呈現）：
// 「未搜尋」與「服務答了但零筆」等各是不同值。
const PLACE_SEARCH = Object.freeze({
  NOT_SEARCHED: "not_searched",
  SEARCHING: "searching",
  FOUND: "found",
  SPELLING_FALLBACK: "spelling_fallback",
  NONE: "none",
  NOTHING_SEARCHABLE: "no_searchable_tokens",
  UNREADABLE: "unreadable",
  REJECTED: "rejected",
  TIMEOUT: "timeout",
  FAILED: "failed",
  TOO_SHORT: "too_short",
});

function setPlaceStatus(state, message, tone) {
  placeStatus.dataset.state = state;
  placeStatus.textContent = message;
  placeStatus.dataset.tone = tone;
}

el("place-search-button").addEventListener("click", searchPlaces);
placeQuery.addEventListener("keydown", (event) => {
  // 注音、倉頡選字時的 Enter 是確認組字。組字中 isComposing 為真；Safari 等在
  // 組字結束那一下只給 keyCode 229。兩者都不是要查詢。
  if (event.key !== "Enter" || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  searchPlaces();
});

function revealPlaceResults() {
  placeResults.scrollIntoView({ block: "nearest", behavior: scrollBehavior() });
}

function searchPlaces() {
  placeSearchLifecycle.abortActiveRequest();
  const query = placeQuery.value.trim();
  placeResults.replaceChildren();
  placeResults.hidden = true;
  if (query.length < 2) {
    setPlaceStatus(PLACE_SEARCH.TOO_SHORT, "請輸入至少兩個字再查詢。", "error");
    return;
  }
  setPlaceStatus(PLACE_SEARCH.SEARCHING, "查詢中…", "info");
  const { controller, token, timeout } = placeSearchLifecycle.beginTimedRequest(
    PLACE_SEARCH_TIMEOUT_MS, window.setTimeout.bind(window)
  );

  // 與 /api/chart 同一條政策：2xx 也要驗 media type 與形狀。
  postJson("/api/places/search", { query, limit: 10 }, controller.signal)
    .then(({ response, body, invalidJsonMedia }) => {
      if (!placeSearchLifecycle.isCurrentRequest(token)) return;
      if (!response.ok) {
        setPlaceStatus(
          PLACE_SEARCH.REJECTED,
          window.ClientContext.formatApiError(body && body.detail, response.status),
          "error"
        );
        return;
      }
      // 「服務答了但零筆」與「服務答了但答案讀不懂」是兩個值。把畸形回應
      // 當成零筆，會讓使用者以為目錄裡真的沒有這個地方。
      const shaped = !invalidJsonMedia
        && window.ChartExport.isRecord(body)
        && Array.isArray(body.results);
      if (!shaped) {
        setPlaceStatus(
          PLACE_SEARCH.UNREADABLE,
          "地名查詢的回應無法解讀，這不代表目錄裡沒有這個地方。請再試一次；若持續發生，請在下方手動輸入座標與時區。",
          "error"
        );
        return;
      }
      // 只有標點或符號時後端沒有搜尋；說「目錄裡沒有」會是假話。
      if (body.query && body.query.status === "no_searchable_tokens") {
        setPlaceStatus(
          PLACE_SEARCH.NOTHING_SEARCHABLE,
          "查詢裡沒有可比對的文字（標點與符號會被略過）。請輸入地名，或在下方手動輸入座標與時區。",
          "error"
        );
        return;
      }
      const found = body.results;
      // 後端會回一份 query 收據，說明有沒有詞被丟掉。不讀它，等於把一個
      // 被改寫過的查詢報成使用者自己的查詢。
      const truncation = window.ClientContext.placeQueryNotice(body.query);
      if (!found.length) {
        setPlaceStatus(
          PLACE_SEARCH.NONE,
          truncation
            ? `內建目錄沒有符合的地名。${truncation}`
            : "內建目錄沒有符合的地名。可以改用鄰近的較大地點，或在下方手動輸入座標與時區。",
          "error"
        );
        return;
      }
      // 原字查無結果時後端改列拼法相近的地名；不說明，使用者會以為列出的就是他打的字。
      // 被截斷時是警告而不是單純資訊：結果不涵蓋使用者打的全部內容。
      const fallback = Boolean(body.query && body.query.spelling_fallback
        && body.query.spelling_fallback.status === "applied");
      if (fallback) {
        setPlaceStatus(
          PLACE_SEARCH.SPELLING_FALLBACK,
          `找不到與「${query}」相符的地名；以下 ${found.length} 筆是拼法相近（最多差兩個字母）的地名，`
            + `請確認是不是你要找的地方。座標為目錄的代表點，不是出生地址。${truncation || ""}`,
          "warning"
        );
      } else {
        setPlaceStatus(
          PLACE_SEARCH.FOUND,
          truncation
            ? `找到 ${found.length} 筆。座標為目錄的代表點，不是出生地址。${truncation}`
            : `找到 ${found.length} 筆。座標為目錄的代表點，不是出生地址。`,
          truncation ? "warning" : "info"
        );
      }
      found.forEach((place) => placeResults.appendChild(buildPlaceRow(place)));
      placeResults.hidden = false;
      // 手機上清單常落在視窗下緣之外，看起來像沒反應：捲到剛好看得見（已看得見就不動）。焦點留在查詢欄。
      revealPlaceResults();
    })
    .catch((error) => {
      if (!placeSearchLifecycle.isCurrentRequest(token)) return;
      const timedOut = timeout.didTimeout() && error && error.name === "AbortError";
      setPlaceStatus(
        timedOut ? PLACE_SEARCH.TIMEOUT : PLACE_SEARCH.FAILED,
        timedOut
          ? "地名查詢逾時。請再試一次，或在下方手動輸入座標與時區。"
          : "地名查詢沒有完成。這個查詢只讀取內建目錄，不會對外連線；請再試一次，或在下方手動輸入座標與時區。",
        "error"
      );
    })
    .finally(() => {
      window.clearTimeout(timeout.handle);
      placeSearchLifecycle.finishRequest(token);
    });
}

function buildPlaceRow(place) {
  const item = document.createElement("li");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "place-option";

  // 目錄只在標籤與他筆相同時給 disambiguator（二級行政區或座標），附在標籤後。
  const name = document.createElement("b");
  const label = place.display_name || place.name;
  name.textContent = place.disambiguator ? `${label}（${place.disambiguator}）` : label;
  button.appendChild(name);

  // 同名地點必須靠這一行分辨，因此經緯度、時區、來源與人口都要出現。
  const meta = make("span", "place-meta");
  // 來源念中文短名，不念目錄代碼；原始代碼在選定後的收據技術細節裡。
  meta.textContent = [
    `${Number(place.latitude).toFixed(4)}, ${Number(place.longitude).toFixed(4)}`,
    place.timezone,
    place.country_code,
    place.population ? `人口 ${place.population.toLocaleString("en-US")}` : "人口不詳",
    Labels.label("place_source_short", place.source),
  ].filter(Boolean).join("　·　");
  button.appendChild(meta);

  button.addEventListener("click", () => selectPlace(place));
  item.appendChild(button);
  return item;
}

// 出生紀錄用北京時間還是新疆時間：
// 新疆同時使用北京時間與新疆時間；目錄對這類地點回兩種鐘點
// （civil_time_basis_choices，北京時間在前）。沒有預設：選定前時區欄留空、
// 送出 fail closed；選定後時區欄填入那一種的 IANA 時區，請求一併送出所選的鐘點。
// 手動輸入座標沒有目錄列可問，服務也不以座標判定（沒有省界多邊形）：使用者親手把時區
// 填成新疆時間（Asia/Urumqi 或其 tz 連結 Asia/Kashgar）時，問同一個問題、給同樣兩個選項；
// 服務對這種請求同樣要求指明鐘點。選項之後由程式改寫時區欄，不會再觸發這個判定。
const XINJIANG_TIME_ZONES = Object.freeze(["Asia/Urumqi", "Asia/Kashgar"]);
const MANUAL_CIVIL_TIME_CHOICES = Object.freeze([
  Object.freeze({ civil_time_basis: "beijing_time", iana_name: "Asia/Shanghai" }),
  Object.freeze({ civil_time_basis: "xinjiang_time", iana_name: "Asia/Urumqi" }),
]);
function civilTimeChoices(place) {
  if (!place) return pageState.manualCivilTime ? MANUAL_CIVIL_TIME_CHOICES : null;
  return Array.isArray(place.civil_time_basis_choices)
    && place.civil_time_basis_choices.length
    ? place.civil_time_basis_choices
    : null;
}

function chosenCivilTime() {
  const choices = civilTimeChoices(pageState.selectedPlace);
  if (!choices || pageState.civilTimeBasis === null) return null;
  return choices.find((choice) => choice.civil_time_basis === pageState.civilTimeBasis) || null;
}

// 目錄收據仍成立時，時區欄應有的值；不同就是使用者手動改過。
function expectedPlaceTimezone(place) {
  if (!civilTimeChoices(place)) return String(place.timezone || "");
  const chosen = chosenCivilTime();
  return chosen ? chosen.iana_name : "";
}

function renderCivilTimeChoice(place) {
  const choices = civilTimeChoices(place);
  const options = el("civil-time-choice-options");
  options.replaceChildren();
  // 上一組選項的錯誤訊息不再對應任何選項。
  const stale = document.getElementById("civil_time_basis-error");
  if (stale) stale.remove();
  pageState.civilTimeBasis = null;
  el("civil-time-choice").hidden = !choices;
  (choices || []).forEach((choice) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "civil_time_basis";
    input.value = choice.civil_time_basis;
    // 先於表單層的 change 執行：noteFormChanged 重算模糊時刻時，時區欄已是所選的那一種。
    input.addEventListener("change", () => {
      pageState.civilTimeBasis = choice.civil_time_basis;
      el("timezone").value = choice.iana_name;
    });
    const caption = document.createElement("span");
    const bold = document.createElement("b");
    bold.textContent = Labels.label("civil_time_basis", choice.civil_time_basis);
    const zone = make("span", "mono");
    zone.lang = "en";
    zone.textContent = choice.iana_name;
    caption.append(bold, zone);
    label.append(input, caption);
    options.appendChild(label);
  });
}

function selectPlace(place) {
  pageState.selectedPlace = place;
  pageState.manualCivilTime = false;
  el("latitude").value = String(place.latitude);
  el("longitude").value = String(place.longitude);
  if (!el("altitude").value.trim()) el("altitude").value = "0";
  renderCivilTimeChoice(place);
  const dualClock = Boolean(civilTimeChoices(place));
  el("timezone").value = expectedPlaceTimezone(place);

  // 收據念的是中文標籤；目錄的原始代碼與記錄 id 收在「技術細節」摺疊裡，
  // 回報問題或對照目錄時仍拿得到，平常讀收據時不會聽到一串底線英文。
  const describe = (list, rows, lang) => {
    list.replaceChildren();
    rows.forEach(([term, en, value]) => {
      const dt = document.createElement("dt");
      dt.append(term);
      if (en) {
        const tag = make("span", "en");
        tag.lang = "en";
        tag.textContent = en;
        dt.appendChild(tag);
      }
      const dd = document.createElement("dd");
      dd.textContent = value === undefined || value === null ? "—" : String(value);
      if (lang) dd.lang = lang;
      list.append(dt, dd);
    });
  };
  // 臺灣以外的地點寫出國家或地區：同名或近名的外國地點（例：東京的台東區）一眼可辨。
  const abroad = place.country_code && place.country_code !== "TW"
    ? [["國家或地區", null, Labels.regionName(place.country_code)]]
    : [];
  describe(el("place-receipt-body"), [
    ["地點", null, place.display_name || place.name],
    ...abroad,
    ["緯度", null, Number(place.latitude).toFixed(6)],
    ["經度", null, Number(place.longitude).toFixed(6)],
    ["時區", null, dualClock
      ? `${place.timezone}（目錄的時區；出生紀錄可能用北京時間或新疆時間，請在下方選擇）`
      : place.timezone || "—"],
    ["目錄來源", null, Labels.label("place_source", place.source)],
    ["座標語義", null, Labels.label("coordinate_semantics", place.coordinate_semantics)],
    ["位置精度", null, Labels.label("location_precision", place.location_precision)],
    ["比對層級", null, Labels.label("match_tier", place.match_tier)],
  ]);
  describe(el("place-receipt-codes"), [
    ["目錄來源", "source", place.source],
    ["目錄記錄 id", "source_record_id", place.source_record_id],
    ["座標語義", "coordinate_semantics", place.coordinate_semantics],
    ["位置精度", "location_precision", place.location_precision],
    ["比對層級", "match_tier", place.match_tier],
  ], "en");

  el("place-caveat").textContent =
    "這組座標是目錄對該地點的代表點，不是你的出生地址。上升點對經緯度敏感，"
    + "若你知道更精確的座標，請在下方手動輸入取代它。"
    + (dualClock
      ? "這個地點同時使用北京時間與新疆時間，請在下方指明出生紀錄用的是哪一種；選定前不會計算。"
      : "時區已依目錄帶入，仍請確認出生當時實際適用的時區。");
  el("place-receipt").hidden = false;
  placeResults.hidden = true;
  setPlaceStatus(
    PLACE_SEARCH.FOUND,
    dualClock
      ? "已選定地點，座標已填入；請選擇出生紀錄用的是北京時間還是新疆時間。"
      : "已選定地點，座標與時區已填入。",
    "info"
  );
  // 程式寫入座標與時區，和使用者親手輸入走同一條狀態轉移：模糊時刻的
  // 選擇區、欄位錯誤旗標、結果與表單的綁定都由 noteFormChanged 重算。
  // 少了這一步，「先填時間再選地點」的順序永遠看不到
  // 選擇區，送出卻被 fail-closed 擋住。
  noteFormChanged();
  // 剛按下的那顆結果按鈕已隨清單隱藏，焦點會掉到 body；把它移到收據上。
  // 收據在 HTML 帶 tabindex="-1"，只能被程式聚焦。
  el("place-receipt").focus();
}

// 手動改動座標或時區時，目錄收據不再成立，必須撤下。
["latitude", "longitude", "timezone"].forEach((id) => {
  el(id).addEventListener("input", () => {
    if (!pageState.selectedPlace) return;
    const drifted =
      !LocationReceipt.sameCoordinate(el("latitude").value, pageState.selectedPlace.latitude)
      || !LocationReceipt.sameCoordinate(el("longitude").value, pageState.selectedPlace.longitude)
      || String(el("timezone").value) !== expectedPlaceTimezone(pageState.selectedPlace);
    if (drifted) {
      pageState.selectedPlace = null;
      clearPlaceReceipt();
      setPlaceStatus(PLACE_SEARCH.NOT_SEARCHED, "座標或時區已手動修改，目錄收據不再適用。", "info");
    }
  });
});

// 手動座標親手填的時區是新疆時間：顯示鐘點選擇（重新填一次就重新問）；改成別的時區就撤下。
el("timezone").addEventListener("input", () => {
  if (pageState.selectedPlace) return;
  const xinjiang = XINJIANG_TIME_ZONES.includes(String(el("timezone").value).trim());
  if (!xinjiang && !pageState.manualCivilTime) return;
  pageState.manualCivilTime = xinjiang;
  renderCivilTimeChoice(null);
});

// 時區欄的建議清單與結果的時區列取同一組中文地名（labels.js），不在頁面另寫一份。
Object.entries(Labels.VOCABULARIES.timezone_place).forEach(([zone, place]) => {
  const option = document.createElement("option");
  option.value = zone;
  option.label = place;
  el("timezone-suggestions").appendChild(option);
});

// Etc/GMT±N 的正負號與 UTC 偏移相反；手動填這種名稱時，在欄位下寫出解析後的偏移。
// 由表單的 input 事件與程式改值後的 noteFormChanged 一起更新。
function refreshTimezoneOffset() {
  const line = el("timezone-offset");
  const zone = String(el("timezone").value).trim();
  const offset = TimezoneNames.accepts(zone) ? RI.etcGmtOffsetText(zone) : null;
  line.textContent = offset ? `${zone} 即 ${offset}（Etc/GMT 名稱的正負號與 UTC 偏移相反）。` : "";
  line.hidden = !offset;
}

// 表單連動。
const precisionConsequence = el("precision-consequence");
const zodiacConsequence = el("zodiac-consequence");
const hourInput = el("hour");
const minuteInput = el("minute");
const secondInput = el("second");
const zodiacSelect = el("zodiac");
const ayanamsaSelect = el("ayanamsa");

function currentPrecision() {
  const checked = form.querySelector('input[name="precision"]:checked');
  return checked ? checked.value : "exact";
}

function applyPrecisionConsequences() {
  const precision = currentPrecision();
  minuteInput.disabled = precision !== "exact";
  secondInput.disabled = precision !== "exact";
  hourInput.disabled = precision === "date_only";
  // 不只停用也收起：灰掉的欄位不帶資訊，還得先看懂才知道不必填；讓出的位置給 .consequence 說明。
  // disabled 保留不動：hidden 只管版面，送出路徑仍照 precision 讀值。
  el("field-minute").hidden = precision !== "exact";
  el("field-second").hidden = precision !== "exact";
  el("field-hour").hidden = precision === "date_only";
  if (precision !== "exact") { minuteInput.value = ""; secondInput.value = ""; }
  if (precision === "date_only") hourInput.value = "";
  const messages = {
    exact: "",
    approximate_hour:
      "分與秒會以 0 送出，因為後端只接受已知的民用小時，並會自行對整個小時取樣。這些 0 不代表你出生在整點。",
    date_only:
      "時、分、秒都會以 0 送出，那只是 API 的日期容器，不代表你出生在午夜。"
      + "後端在這個模式下會關閉宮位計算，因為宮位需要已知時刻；結果中的宮位區塊會標示為未請求。",
  };
  // 不切 hidden：這一段是 aria-live 宣告區，必須常駐在無障礙樹裡，內容改變才念得到。
  precisionConsequence.textContent = messages[precision];
}

function applyZodiacConsequences() {
  refreshModeSummary();
  const sidereal = zodiacSelect.value === "sidereal";
  ayanamsaSelect.disabled = !sidereal;
  // 歲差校正只對恆星黃道有意義（目錄的 depends_on）；回歸黃道下收起。
  el("field-ayanamsa").hidden = !sidereal;
  zodiacConsequence.textContent = sidereal
    ? "恆星黃道下，本質尊貴會被產品明確拒絕而不是算錯，尊貴的判準建立在回歸黃道上，"
      + "尚未有授權的恆星黃道版本。結果中會顯示拒絕的原因代碼。"
    : "";
}

// 大約時辰的分與秒恆為 0（送出的 payload 也是），所以同一個鍵涵蓋兩種精確度。
function timeKey(precision, dateValue, hour, minute, second, timezone) {
  return `${precision}|${dateValue}|${hour}|${minute}|${second}|${timezone}`;
}

function timeKeyOfPayload(payload) {
  const { datetime, timezone } = payload;
  return timeKey(
    payload.birth_time_precision,
    RI.isoDate(datetime.year, datetime.month, datetime.day),
    datetime.hour,
    datetime.minute,
    datetime.second,
    timezone.iana_name
  );
}

const SERVICE_AMBIGUITY = Object.freeze(
  { state: "ambiguous", source: "service", occurrences: [{ fold: 0 }, { fold: 1 }] }
);

// 出生日期是一欄（2000-04-04、2000/4/4、20000404…）；讀取只有這一個出處：格式、日曆與範圍（欄位的
// data-min／data-max）。表單帶 novalidate，鍵盤打進來的 1895 年或 2400 年不會被瀏覽器擋下。
const DATE_INPUT_ID = "birth-date";
const datePartInputs = () => [el(DATE_INPUT_ID)];
const isDatePart = (input) => Boolean(input && input.id === DATE_INPUT_ID);
function dateBounds() {
  const input = el(DATE_INPUT_ID);
  return { min: input.dataset.min, max: input.dataset.max };
}
function readDateField() {
  return RI.readBirthDateText(String(el(DATE_INPUT_ID).value), dateBounds());
}
function setDateFields({ year, month, day }) {
  el(DATE_INPUT_ID).value = `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function currentAmbiguity() {
  const timezone = String(el("timezone").value).trim();
  const dateRead = readDateField();
  // 範圍外或不成日期的值不問 fold：送出守衛會先指名日期本身的問題。
  if (dateRead.state !== RI.STATES.VALUE || !timezone) return null;
  const { year, month, day, iso: dateValue } = dateRead.value;
  const precision = currentPrecision();
  // date_only 由後端對整個民用日取樣，不需要這個選擇；exact 與 approximate_hour 後端都要求指明
  // 是哪一次，這裡就得給得出選擇，否則使用者被擋在無法回答的問題前。
  if (precision === "date_only") return null;
  const hour = RI.readInteger(String(hourInput.value));
  if (hour.state !== RI.STATES.VALUE) return null;
  if (precision === "approximate_hour") {
    // 後端對整個小時取樣，所以判定單位是整個小時，不是 HH:00:00：重複區段可在小時中間起訖
    // （St_Johns 23:01 起、Lord Howe 01:30 起），整點只出現一次。
    const hourResult = RI.civilHourOccurrences(
      { year, month, day, hour: hour.value }, timezone
    );
    if (hourResult && hourResult.state === "ambiguous") return hourResult;
    // 服務是時區事實的單一來源：它對這個小時回過「需要指明是哪一次」，
    // 而本頁自己的判定沒看出來時，照服務的判定提供選擇，不讓使用者卡住。
    if (pageState.serviceRepeatedTime === timeKey(precision, dateValue, hour.value, 0, 0, timezone)) {
      return SERVICE_AMBIGUITY;
    }
    return null;
  }
  const minute = RI.readInteger(String(minuteInput.value));
  if (minute.state !== RI.STATES.VALUE) return null;
  const secondRead = RI.readSecond(String(secondInput.value));
  const second = secondRead.state === RI.STATES.VALUE ? secondRead.value : 0;
  const result = RI.civilTimeOccurrences(
    { year, month, day, hour: hour.value, minute: minute.value, second },
    timezone
  );
  if (result && result.state === "ambiguous") return result;
  // 同上：服務對這個 exact 時刻回過「需要指明是哪一次」（本頁判定為單次），照服務的判定提供選擇。
  if (pageState.serviceRepeatedTime === timeKey(precision, dateValue, hour.value, minute.value, second, timezone)) {
    return SERVICE_AMBIGUITY;
  }
  return null;
}

function repeatSpanText(occurrences) {
  const times = occurrences.map((o) => Date.parse(o.utcIso)).filter(Number.isFinite);
  if (times.length < 2) return null;
  const minutes = Math.round(Math.abs(times[1] - times[0]) / 60000);
  if (!minutes) return null;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours && rest) return `${hours} 小時 ${rest} 分鐘`;
  return hours ? `${hours} 小時` : `${rest} 分鐘`;
}

// 選擇區出現在使用者剛填完的欄位下方，視線與報讀游標都可能已經離開；狀態列
// （role=status）是本頁的宣告管道，出現時在那裡說一次，收起時撤下這句。
const FOLD_ANNOUNCEMENT = "這個時間在所選時區出現了兩次：請在出生時間下方的選擇區指明是哪一次。";

// 選項重建或收起時，上一組選項的錯誤訊息不再對應任何選項。
function removeFoldError() {
  const stale = document.getElementById("fold-error");
  if (stale) stale.remove();
}

function refreshFoldChoice() {
  const ambiguity = currentAmbiguity();
  const host = el("fold-choice");
  if (!ambiguity) {
    if (statusLine.textContent === FOLD_ANNOUNCEMENT) setStatus("", "info");
    removeFoldError();
    host.hidden = true;
    el("fold-choice-options").replaceChildren();
    // signature 一起清掉：否則清空後再輸入同一個模糊時刻，下面的早退判定「選項沒變」而不重建，
    // 選擇區不再出現，送出卻被 fail-closed 擋下。
    delete host.dataset.signature;
    pageState.foldChoice = null;
    return;
  }
  const signature = ambiguity.source === "service"
    ? "service"
    : ambiguity.occurrences.map((o) => o.utcIso).join("|");
  if (host.dataset.signature === signature) return;   // 同一組選項不重建
  host.dataset.signature = signature;
  pageState.foldChoice = null;
  removeFoldError();

  el("fold-choice-title").textContent =
    "這個時間在所選時區出現了兩次，請指明是哪一次。";
  const options = el("fold-choice-options");
  options.replaceChildren();
  ambiguity.occurrences.forEach((occurrence, index) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "fold";
    input.value = String(occurrence.fold);
    input.addEventListener("change", () => { pageState.foldChoice = occurrence.fold; });
    const caption = document.createElement("span");
    const which = index === 0 ? "第一次（較早）" : "第二次（較晚）";
    if (!Number.isFinite(occurrence.offsetHours) || !occurrence.utcIso) {
      // 只有服務的判定、本頁算不出兩次各自的偏移：只列先後，不編造世界時。
      const bold = document.createElement("b");
      bold.textContent = which;
      caption.append(bold);
      label.append(input, caption);
      options.appendChild(label);
      return;
    }
    // 秒級的歷史偏移不印成長小數，一律 ±時:分:秒。寫法與結果頁的「UTC 偏移」相同（view-model.js 的
    // utcOffsetText；那支在送出後才載入，這裡用不到）：負號是 ASCII「-」。
    const sign = occurrence.offsetHours >= 0 ? "+" : "-";
    const seconds = Math.round(Math.abs(occurrence.offsetHours) * 3600);
    const magnitude = `${RI.pad2(Math.floor(seconds / 3600))}:${RI.pad2(Math.floor((seconds % 3600) / 60))}`
      + (seconds % 60 ? `:${RI.pad2(seconds % 60)}` : "");
    const bold = document.createElement("b");
    bold.textContent = `${which}　UTC${sign}${magnitude}`;
    const detail = document.createElement("span");
    // 寫成「世界時 日期 時:分」，不寫 ISO 的 Z：Z 是 UTC，而 1972 年前（與 Swiss 判定閏秒表過期之後）
    // 結果頁標的是 UT1。「世界時」兩者都涵蓋，與結果頁不矛盾。
    const instant = occurrence.utcIso.replace(/\.000Z$|Z$/, "").replace("T", " ").replace(/:00$/, "");
    detail.textContent = `對應世界時 ${instant}`;
    caption.append(bold, detail);
    label.append(input, caption);
    options.appendChild(label);
  });
  // 重複的長度不一定是一小時、原因也不一定是日光節約
  // （Lord Howe 2024-04-07 重複 30 分鐘；臺北 1945-09-21 是日本標準時改回中原標準時；
  // Kwajalein 1969-09-30 重複約 23 小時），所以相差多久由兩個 UTC 時刻相減得出。
  const span = ambiguity.source === "service" ? null : repeatSpanText(ambiguity.occurrences);
  el("fold-choice-note").textContent =
    "這個時區在此時刻改變了 UTC 偏移（例如日光節約時間結束，或標準時變更），時鐘往回撥，"
    + "於是同一個鐘面時間出現兩次。"
    + (span ? `兩次相差 ${span}，` : "")
    + "算出來的上升點可能落在不同星座，所以這裡不替你猜。"
    + "若真的無法確定，任選一個，並把這件事記在結果之外，收據會記下採用了哪一次。";
  host.hidden = false;
  setStatus(FOLD_ANNOUNCEMENT, "warning");
}

// 表單任何一處改動——使用者輸入、程式寫入（選地點、範例）、選項重設——
// 都走這一個轉移。相依狀態（模糊時刻選擇區、欄位錯誤旗標、結果與表單的
// 綁定）只在這裡重算，程式寫入不得繞過它。
function noteFormChanged(target) {
  if (!target || target.name !== "fold") refreshFoldChoice();
  refreshTimezoneOffset();
  if (target && typeof target.hasAttribute === "function" && target.hasAttribute("aria-invalid")) {
    clearFieldInvalid(target);
    if (pageState.formErrorShown && !form.querySelector("[aria-invalid]")) {
      hideError();
      setStatus("", "info");
    }
  }
  refreshResultBinding();
  refreshTimeCheckBinding();
}

form.addEventListener("change", (event) => {
  if (event.target.name === "precision") applyPrecisionConsequences();
  if (event.target.id === "zodiac") applyZodiacConsequences();
  if (event.target.id === "ayanamsa") refreshModeSummary();
  noteFormChanged(event.target);
});
form.addEventListener("input", (event) => { noteFormChanged(event.target); });

// 換算助手：民國年與日本年號。
// 換算在 RequestInput（純函式，範圍讀出生日期三欄共用的 min／max）；這裡只把結果寫進
// 年、月、日三欄，並走與使用者輸入相同的轉移。助手的欄位沒有 name，不進請求。
function setEraEcho(message, tone) {
  const echo = el("era-echo");
  echo.textContent = message;
  echo.dataset.tone = tone;
}

el("era-apply").addEventListener("click", () => {
  const read = RI.readEraDate({
    era: el("era-name").value,
    year: String(el("era-year").value),
    month: String(el("era-month").value),
    day: String(el("era-day").value),
  }, dateBounds());
  if (read.state === RI.STATES.EMPTY) {
    setEraEcho("請填年、月、日。", "error");
    return;
  }
  if (read.state === RI.STATES.INVALID) {
    setEraEcho(`${read.reason}。出生日期沒有改動。`, "error");
    return;
  }
  const { eraText, gregorianText, formula, year, month, day } = read.value;
  setDateFields({ year, month, day });
  datePartInputs().forEach(noteFormChanged);
  setEraEcho(`${eraText} ＝ ${gregorianText}（${formula}），已填入出生日期。`, "info");
});

// 換算助手：核對鐘面時間。
// 由計算服務回答（POST /api/time/convert）：它跑的是排盤時同一個換算函式、同一份時區資料庫。
// 瀏覽器自己的時區資料版本不明，不拿來回答這個問題。請求只帶日期、時刻與時區，不帶座標；
// 回答只留在畫面上，對應的輸入一改就撤下，清除敏感資料時與進行中的請求一起作廢。
const TIME_CHECK_TIMEOUT_MS = 10000;
const timeCheckLifecycle = window.PrivacyLifecycle.createSensitiveDataLifecycle();

function setTimeCheckStatus(message, tone) {
  const status = el("time-check-status");
  status.textContent = message;
  status.dataset.tone = tone;
}

function clearTimeCheck(message, tone) {
  timeCheckLifecycle.abortActiveRequest();
  const host = el("time-check-result");
  host.replaceChildren();
  host.hidden = true;
  pageState.timeCheckShownKey = null;
  setTimeCheckStatus(message || "", tone || "info");
}

/** 從目前的表單組出核對請求，或說出還缺什麼。不動 DOM。 */
function timeCheckRequest() {
  const dateRead = readDateField();
  if (dateRead.state === RI.STATES.EMPTY) return { problem: "請先填出生日期（或用上面的年號換算）。" };
  if (dateRead.state === RI.STATES.INVALID) return { problem: `出生日期${dateRead.reason}。` };
  const precision = currentPrecision();
  if (precision === "date_only") {
    return { problem: "「只知道日期」沒有單一的鐘面時刻可以核對；請填上時刻並改選較精確的出生時間，或直接計算。" };
  }
  const inRange = (read, low, high) => read.state === RI.STATES.VALUE && read.value >= low && read.value <= high;
  const hour = RI.readInteger(String(hourInput.value));
  if (!inRange(hour, 0, 23)) return { problem: "請先填小時（0–23）。" };
  let minute = 0;
  let second = 0;
  if (precision === "exact") {
    const minuteRead = RI.readInteger(String(minuteInput.value));
    if (!inRange(minuteRead, 0, 59)) return { problem: "請先填分（0–59）。" };
    minute = minuteRead.value;
    const secondRead = RI.readSecond(String(secondInput.value));
    if (secondRead.state === RI.STATES.INVALID) return { problem: `秒${secondRead.reason}。` };
    second = secondRead.state === RI.STATES.VALUE ? secondRead.value : 0;
  }
  const civilTime = chosenCivilTime();
  if (civilTimeChoices(pageState.selectedPlace) && !civilTime) {
    return { problem: "請先在出生地點下方選擇出生紀錄用的是北京時間還是新疆時間。" };
  }
  const timezone = String(el("timezone").value).trim();
  if (!timezone) return { problem: "請先選定出生地點，或在手動輸入裡填 IANA 時區名稱。" };
  if (!TimezoneNames.accepts(timezone)) {
    return { problem: "時區名稱不在服務接受的 IANA 名單內（例如 Asia/Taipei，大小寫須相符）。" };
  }
  const { year, month, day } = dateRead.value;
  return {
    approximate: precision === "approximate_hour",
    body: {
      datetime: { year, month, day, hour: hour.value, minute, second },
      timezone: {
        mode: "iana",
        iana_name: timezone,
        ...(civilTime ? { civil_time_basis: civilTime.civil_time_basis } : {}),
      },
    },
  };
}

const timeCheckKey = (request) => (request.body ? JSON.stringify(request.body) : null);

// 表單改動後，畫面上的核對結果若不再對應目前的輸入就撤下（由 noteFormChanged 呼叫）。
function refreshTimeCheckBinding() {
  if (pageState.timeCheckShownKey === null) return;
  if (timeCheckKey(timeCheckRequest()) === pageState.timeCheckShownKey) return;
  clearTimeCheck("出生日期、時刻或時區改了；先前的核對結果已撤下，請重新核對。", "info");
}

function appendText(host, tag, text, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  host.appendChild(node);
  return node;
}

function externalLink(label, url) {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.rel = "noopener noreferrer";
  anchor.target = "_blank";
  anchor.textContent = label;
  return anchor;
}

const wallTime = (label) => String(label).replace(/\.000$/, "");

function readingKind(reading) {
  const regime = reading.rule && reading.rule.regime;
  const kind = regime ? Labels.label("civil_time_regime", regime) : (reading.summer_time ? "夏令時間" : "非夏令時間");
  return `${kind}，時區縮寫 ${reading.abbreviation}`;
}

function renderRule(host, rule, checkedVersion) {
  if (!rule || rule.status === "not_cited") {
    appendText(host, "p", "這一段沒有可引用的文件（未引用）：時區資料庫的值是它自己的推定。", "caveat");
    return;
  }
  if (rule.status !== "cited" || !rule.source) {
    appendText(host, "p",
      `服務正在使用的時區資料庫對這一段的說法，與本站出處表（依 ${checkedVersion} 核對）不同，因此不列出處。`,
      "caveat");
    return;
  }
  const source = rule.source;
  const list = document.createElement("dl");
  const row = (term, ...content) => {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.append(...content);
    list.append(dt, dd);
  };
  row("規則", source.title);
  row("依據文件", source.document);
  row("我們核到哪一層", source.verification_label);
  const read = [];
  source.read.forEach((item, index) => {
    if (index) read.push("；");
    read.push(externalLink(item.label, item.url));
  });
  row("我們讀過的", ...read);
  const holder = [];
  if (source.holder.name) {
    holder.push(source.holder.url ? externalLink(source.holder.name, source.holder.url) : source.holder.name);
    holder.push("。");
  }
  holder.push(source.holder.note);
  row("原件在哪裡", ...holder);
  host.appendChild(list);
}

function renderTimeCheck(body, approximate) {
  const host = el("time-check-result");
  host.replaceChildren();
  const zone = body.timezone;
  const where = `${zone.region_label}（${zone.iana_name}）`;
  const local = wallTime(body.input_local_time);
  if (approximate) {
    appendText(host, "p", `只知道約略小時：這裡核對的是 ${local} 這一刻；計算時會對整個小時取樣。`, "note");
  }
  const readings = Array.isArray(body.readings) ? body.readings : [];
  let rules;
  if (body.status === "nonexistent" && body.gap) {
    const gap = body.gap;
    appendText(host, "p",
      `${local} 在${where}不存在：時鐘在 ${gap.skipped_local_start} 從 ${gap.offset_before_label} `
      + `撥到 ${gap.offset_after_label}，${gap.skipped_local_start} 到 ${gap.skipped_local_end} 之間的鐘面時間被跳過了。`
      + "請核對出生紀錄的日期與時刻；服務不會替你挪動。");
    rules = [gap.rule];
  } else if (body.status === "repeated" && readings.length === 2) {
    appendText(host, "p", `${local} 在${where}出現了兩次：`);
    const list = document.createElement("ul");
    readings.forEach((reading, index) => {
      appendText(list, "li",
        `${index === 0 ? "第一次（較早）" : "第二次（較晚）"}　${reading.utc_offset_label}（${readingKind(reading)}），`
        + `世界時 ${reading.utc_iso_8601}`);
    });
    host.appendChild(list);
    appendText(host, "p", "計算時，請在出生時間下方指明是哪一次。");
    rules = readings.map((reading) => reading.rule);
  } else if (body.status === "single" && readings.length === 1) {
    const reading = readings[0];
    appendText(host, "p",
      `${local} 在${where}是 ${reading.utc_offset_label}（${readingKind(reading)}），即世界時 ${reading.utc_iso_8601}。`);
    rules = [reading.rule];
  } else {
    throw new Error("換算助手的回應無法解讀；這不影響計算，請再試一次或直接計算。");
  }
  (body.warnings || []).forEach((warning) => appendText(host, "p", warning.message, "caveat"));
  const checkedVersion = body.source_table && body.source_table.tzdb_version_checked;
  const seen = new Set();
  rules.forEach((rule) => {
    const key = rule && rule.source ? rule.source.id : JSON.stringify(rule && rule.status);
    if (seen.has(key)) return;
    seen.add(key);
    renderRule(host, rule, checkedVersion);
  });
  const tz = body.tz_database || {};
  appendText(host, "p",
    `時區資料庫：${tz.version || "無法辨識版本"}（服務實際使用的版本）；出處表依 ${checkedVersion} 核對。`, "note");
  if (readings.some((reading) => reading.offset_status
    && reading.offset_status.historical_verification_status === "pre_1970_database_inferred_not_verified")) {
    appendText(host, "p", "1970 年以前的偏移多為時區資料庫的推定，未經歷史文獻核實。", "note");
  }
  host.hidden = false;
}

el("time-check-button").addEventListener("click", () => {
  clearTimeCheck();
  const request = timeCheckRequest();
  if (!request.body) {
    setTimeCheckStatus(request.problem, "error");
    return;
  }
  setTimeCheckStatus("核對中…", "info");
  const { controller, token, timeout } = timeCheckLifecycle.beginTimedRequest(
    TIME_CHECK_TIMEOUT_MS, window.setTimeout.bind(window)
  );
  const key = timeCheckKey(request);
  postJson("/api/time/convert", request.body, controller.signal)
    .then(({ response, body, invalidJsonMedia }) => {
      if (!timeCheckLifecycle.isCurrentRequest(token)) return;
      if (!response.ok) {
        setTimeCheckStatus(window.ClientContext.formatApiError(body && body.detail, response.status), "error");
        return;
      }
      if (invalidJsonMedia || !body || typeof body !== "object" || !body.timezone) {
        setTimeCheckStatus("換算助手的回應無法解讀；這不影響計算，請再試一次或直接計算。", "error");
        return;
      }
      if (timeCheckKey(timeCheckRequest()) !== key) {
        setTimeCheckStatus("出生日期、時刻或時區在核對途中改了；請重新核對。", "info");
        return;
      }
      try {
        renderTimeCheck(body, request.approximate);
      } catch (_) {
        el("time-check-result").replaceChildren();
        el("time-check-result").hidden = true;
        setTimeCheckStatus("換算助手的回應無法解讀；這不影響計算，請再試一次或直接計算。", "error");
        return;
      }
      pageState.timeCheckShownKey = key;
      setTimeCheckStatus("", "info");
    })
    .catch((error) => {
      if (!timeCheckLifecycle.isCurrentRequest(token)) return;
      const timedOut = timeout.didTimeout() && error && error.name === "AbortError";
      setTimeCheckStatus(
        timedOut ? "核對逾時；請再試一次，或直接計算。" : "核對沒有完成；請再試一次，或直接計算。",
        "error"
      );
    })
    .finally(() => {
      window.clearTimeout(timeout.handle);
      timeCheckLifecycle.finishRequest(token);
    });
});

// 範例載入是完整的狀態取代：先走與「清除敏感資料」相同的
// 重設，把舊結果、地點收據、查詢結果、錯誤、選項與欄位旗標全部換掉，再
// 寫入範例值，最後經同一條轉移重算相依狀態。從髒頁面載入與從新頁面載入
// 必須得到同一個狀態。
el("example-button").addEventListener("click", () => {
  resetFormState();
  form.querySelector('input[name="precision"][value="exact"]').checked = true;
  applyPrecisionConsequences();
  setDateFields({ year: 1990, month: 5, day: 15 });
  hourInput.value = "14";
  minuteInput.value = "30";
  el("latitude").value = "22.9908";
  el("longitude").value = "120.2133";
  el("altitude").value = "80";
  el("timezone").value = "Asia/Taipei";
  el("manual-place").open = true;
  noteFormChanged();
  setStatus("已載入合成範例。這不是任何真實人物的出生資料。", "info");
});

// 送出。collect 把問題分流到 missing 或 invalid：一個是「去填」，一個是「你填的那個值不對」。
// 欄位自己的錯誤訊息：聚焦時念的是這一欄錯在哪，不是整張表的總表。
function missingMessage(label) { return `${label}：尚未填寫。`; }

function collect(reader, input, label, required, problems) {
  const { missing, invalid, fields, messages } = problems;
  const read = reader(String(input.value));
  if (read.state === RI.STATES.EMPTY) {
    if (required) {
      missing.push(label);
      fields.push(input);
      messages.set(input, missingMessage(label));
    }
    return null;
  }
  // 主欄位的上下界只有一個出處：HTML 的 min/max。表單帶 novalidate，
  // 那些屬性不會自己守門，所以在這裡讀同一份值來守。
  const reason = read.state === RI.STATES.INVALID
    ? read.reason
    : RI.boundsProblem(htmlBounds(input), read.value);
  if (reason) {
    invalid.push(`${label}${reason}`);
    fields.push(input);
    messages.set(input, `${label}${reason}。`);
    return null;
  }
  return read.value;
}

function htmlBounds(input) {
  const min = input.min === "" ? undefined : Number(input.min);
  const max = input.max === "" ? undefined : Number(input.max);
  return {
    min: Number.isFinite(min) ? min : undefined,
    max: Number.isFinite(max) ? max : undefined,
  };
}

function documentOrder(a, b) {
  if (a === b) return 0;
  return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
}

/**
 * 回傳 { ok, missing, invalid, fields } 或 { ok, payload }。fields 是依畫面
 * 順序排好的問題欄位，供送出處標 aria-invalid 與移焦點；這個函式本身不動
 * DOM，所以結果綁定可以拿它來比對而沒有副作用。
 */
function buildPayload() {
  const missing = [];
  const invalid = [];
  const fields = [];
  const messages = new Map();
  const problems = { missing, invalid, fields, messages };
  const requireField = (input, label) => {
    missing.push(label);
    fields.push(input);
    messages.set(input, missingMessage(label));
  };
  const dateRead = readDateField();
  // 日期欄的訊息是 #date-error，排在欄位之後。
  if (dateRead.state !== RI.STATES.VALUE) {
    const inputs = datePartInputs();
    if (dateRead.state === RI.STATES.EMPTY) missing.push("出生日期");
    else invalid.push(`出生日期${dateRead.reason}`);
    const message = dateRead.state === RI.STATES.EMPTY ? missingMessage("出生日期") : `出生日期${dateRead.reason}。`;
    inputs.forEach((input) => { fields.push(input); messages.set(input, message); });
  }
  const timezone = String(el("timezone").value).trim();
  // 新疆的地點在選定鐘點前時區欄是空的：指向那一組選項，不叫人去填時區欄。
  const civilTime = chosenCivilTime();
  if (civilTimeChoices(pageState.selectedPlace) && !civilTime) {
    invalid.push("請先選擇出生紀錄用的是北京時間還是新疆時間");
    const firstChoice = form.querySelector('#civil-time-choice input[name="civil_time_basis"]');
    if (firstChoice) {
      fields.push(firstChoice);
      messages.set(firstChoice, "請選擇北京時間或新疆時間。");
    }
  } else if (!timezone) requireField(el("timezone"), "時區（查詢地點或手動輸入）");
  // 服務只接受隨程式碼釘選的 IANA 名單（不含 localtime、Factory 與舊別名）；
  // 頁面讀同一份產生出來的名單，不讓使用者送出後才被拒。
  else if (!TimezoneNames.accepts(timezone)) {
    const reason = "時區名稱不在服務接受的 IANA 名單內（例如 Asia/Taipei，大小寫須相符）";
    invalid.push(reason);
    fields.push(el("timezone"));
    messages.set(el("timezone"), `${reason}。`);
  }

  const precision = currentPrecision();
  const hour = precision === "date_only"
    ? 0
    : collect(RI.readInteger, hourInput, "小時", true, problems);
  const minute = precision === "exact"
    ? collect(RI.readInteger, minuteInput, "分", true, problems)
    : 0;
  // 秒不填視為 0；非 exact 模式下後端要求必須為 0。
  const secondRead = precision === "exact"
    ? collect(RI.readSecond, secondInput, "秒", false, problems)
    : 0;

  const latitude = collect(RI.readDecimal, el("latitude"), "緯度", true, problems);
  const longitude = collect(RI.readDecimal, el("longitude"), "經度", true, problems);
  const altitude = collect(RI.readDecimal, el("altitude"), "海拔", true, problems);

  // 數字選項的上下界在這裡檢查：表單帶 novalidate，HTML min/max 不守門。
  invalid.push(...RI.numericOptionProblems(Catalogue, pageState.optionValues));

  // 模糊時刻沒選就 fail closed。與其猜一個再附帶告知，不如
  // 停下來問——猜錯的代價是整張盤的上升點，而使用者當場就能回答。
  const ambiguity = currentAmbiguity();
  if (ambiguity && pageState.foldChoice === null) {
    invalid.push("這個時間在所選時區出現了兩次，請先指明是哪一次");
    // 第一個選項代表整組：送出處把整組標無效，焦點也落在這裡。
    const firstFold = form.querySelector('#fold-choice input[name="fold"]');
    if (firstFold) {
      fields.push(firstFold);
      messages.set(firstFold, "請指明是第一次還是第二次。");
    }
  }

  if (missing.length || invalid.length) {
    return { ok: false, missing, invalid, fields: fields.slice().sort(documentOrder), messages };
  }

  const { year, month, day } = dateRead.value;
  return {
    ok: true,
    payload: {
      birth_time_precision: precision,
      datetime: {
        year, month, day, hour, minute,
        second: secondRead === null ? 0 : secondRead,
      },
      // fold 只在真的模糊時送出。平時省略，讓收據忠實反映「使用者沒有
      // 需要做這個選擇」，而不是「他選了第一次」。
      // 鐘點只在新疆的地點送出，收據因此只在使用者真的做了這個選擇時記下它。
      timezone: {
        mode: "iana",
        iana_name: timezone,
        ...(ambiguity ? { fold: pageState.foldChoice } : {}),
        ...(civilTime ? { civil_time_basis: civilTime.civil_time_basis } : {}),
      },
      location: LocationReceipt.buildLocationInput({
        latitude,
        longitude,
        altitudeM: altitude,
        selectedPlace: pageState.selectedPlace,
      }),
      // 不送 atmosphere。折射用的溫度與氣壓預設值只在伺服器
      // （app.domain_catalog.DEFAULT_ATMOSPHERE_TEMPERATURE_C 與 AtmosphereInput），
      // 頁面不另寫一份；實際採用的值由回應的 astronomical_data.atmosphere 顯示。
      computation_mode: zodiacSelect.value === "sidereal"
        ? { zodiac: "sidereal", ayanamsa: ayanamsaSelect.value }
        : { zodiac: "tropical" },
      options: Catalogue.toRequestOptions(pageState.optionValues),
    },
  };
}

function setStatus(message, tone) {
  statusLine.textContent = message || "";
  statusLine.dataset.tone = tone || "info";
}

// 匯出訊息寫進 #status-line（表單的 action 區）；捲到結果深處按下按鈕時它在視窗外，`aria-live`
// 只對報讀有效。所以在按下的按鈕旁補一則同文短訊，全域那條保留（它承載 aria-live）。
// 訊息內容只有固定字串與 error.message，不含使用者輸入。
const INLINE_STATUS_TIMEOUT_MS = 6000;
const inlineStatusTimers = new WeakMap();

function reportAt(anchor, message, tone) {
  setStatus(message, tone);
  if (!anchor || !anchor.parentNode) return;
  let note = anchor.nextElementSibling;
  if (!note || !note.classList.contains("inline-status")) {
    note = document.createElement("span");
    note.className = "inline-status";
    anchor.insertAdjacentElement("afterend", note);
  }
  note.textContent = message;
  note.dataset.tone = tone || "info";
  window.clearTimeout(inlineStatusTimers.get(note));
  inlineStatusTimers.set(
    note,
    window.setTimeout(() => {
      note.textContent = "";
    }, INLINE_STATUS_TIMEOUT_MS)
  );
}

// 指向頁面上某個控制項的動作做成連結，按下就到那裡；其餘是一般文字。
const FOLD_ACTION = Object.freeze({
  text: "到「這個時間出現了兩次」的選擇區指定是第一次還是第二次。",
  href: "#fold-choice",
});
const CIVIL_TIME_ACTION = Object.freeze({
  text: "到「出生紀錄用的是北京時間還是新疆時間？」選擇其中一種。",
  href: "#civil-time-choice",
});

function showError(message, actions) {
  pageState.formErrorShown = false;
  errorMessage.textContent = message;
  errorActions.replaceChildren();
  (actions || []).forEach((action) => {
    const item = document.createElement("li");
    if (action && typeof action === "object") {
      const link = document.createElement("a");
      link.href = action.href;
      link.textContent = action.text;
      item.appendChild(link);
    } else {
      item.textContent = action;
    }
    errorActions.appendChild(item);
  });
  errorPanel.hidden = false;
  // 送出鈕在飛行中是 disabled，焦點會掉到 body；錯誤出現時把焦點交給
  // 錯誤標題（HTML 帶 tabindex="-1"），讓鍵盤與螢幕報讀使用者停在錯誤上。
  // 表單驗證失敗時，送出處隨後會再把焦點移到第一個問題欄位。
  el("error-title").focus();
}

// aria-describedby 同時承載欄位說明（靜態 HTML 或選項 UI 寫入）與錯誤訊息；
// 錯誤只加減自己那個 token，不得覆蓋說明的關聯。錯誤排在前面，
// 報讀時先聽到出了什麼錯。
function describedByTokens(input) {
  return (input.getAttribute("aria-describedby") || "").split(/\s+/).filter(Boolean);
}

function setDescribedBy(input, tokens) {
  if (tokens.length) input.setAttribute("aria-describedby", tokens.join(" "));
  else input.removeAttribute("aria-describedby");
}

// 單選鈕的對錯屬於整組：標記與撤下都作用在同名的每一顆上。
function fieldGroup(input) {
  return input.type === "radio" && input.name
    ? [...form.querySelectorAll(`input[type="radio"][name="${input.name}"]`)]
    : [input];
}

// 描述裡屬於錯誤的 token：整張表的 #error-message，或欄位自己的 <id>-error。
const isErrorToken = (token) => token === "error-message" || token.endsWith("-error");
const fieldErrorId = (input) => (isDatePart(input) ? "date-error" : `${input.id || input.name}-error`);

/** 欄位自己的錯誤訊息，緊跟在欄位（單選鈕則是整組選項）後面，畫面上看得到。 */
function showFieldError(input, message) {
  const id = fieldErrorId(input);
  let node = document.getElementById(id);
  if (!node) {
    node = document.createElement("span");
    node.id = id;
    node.className = "field-error";
    const anchor = input.type === "radio" ? input.closest(".choice") || input
      : input;
    anchor.insertAdjacentElement("afterend", node);
  }
  node.textContent = message;
  return id;
}

/**
 * messages 是本頁自己擋下時每一欄的訊息；伺服器點名的欄位沒有逐欄訊息，
 * 連到錯誤面板裡伺服器那一句。
 */
function markInvalidFields(fields, messages) {
  fields.forEach((leader) => {
    const message = messages && messages.get(leader);
    const token = message ? showFieldError(leader, message) : "error-message";
    fieldGroup(leader).forEach((input) => {
      input.setAttribute("aria-invalid", "true");
      setDescribedBy(input, [token, ...describedByTokens(input).filter((t) => !isErrorToken(t))]);
    });
  });
  const first = fields[0];
  if (!first) return;
  // 手動座標區收在 <details> 裡；一個看不見的無效欄位無法被修正。每一個含
  // 無效欄位的 <details> 都要展開，不只第一個欄位所在的那個——否則焦點落在
  // 小時，緯度的錯誤仍藏在收合的區塊裡。
  fields.forEach((input) => {
    const details = input.closest("details");
    if (details) details.open = true;
  });
  first.focus();
}

function clearFieldInvalid(input) {
  fieldGroup(input).forEach((node) => {
    node.removeAttribute("aria-invalid");
    setDescribedBy(node, describedByTokens(node).filter((t) => !isErrorToken(t)));
    const message = document.getElementById(fieldErrorId(node));
    if (message) message.remove();
  });
}

function clearAllFieldInvalid() {
  form.querySelectorAll("[aria-invalid]").forEach(clearFieldInvalid);
  form.querySelectorAll(".field-error").forEach((node) => node.remove());
}

function hideError() {
  pageState.formErrorShown = false;
  errorPanel.hidden = true;
  errorMessage.textContent = "";
  errorActions.replaceChildren();
}
