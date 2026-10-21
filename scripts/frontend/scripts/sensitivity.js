/* 首頁 FIG 1.3：出生時刻敏感度的可拖曳示範。
 *
 * 這一段的誠實約束比互動效果重要，所以先寫清楚：
 *
 * 後端對「約略一小時」的語意是 discrete_probes_not_continuous_hour_proof——
 * 它取離散時刻（每 15 分鐘一點），不宣稱掌握整個小時的連續行為；「各取樣時刻
 * 相同」只說取樣點一致，不說取樣點之間也一致。因此本元件：
 *
 *   1. 只在五個取樣點顯示確切的上升點度數。拖到兩點之間時顯示區間
 *      （「介於 A 與 B 之間」），不做內插——內插出來的數字沒有人算過。
 *   2. 夾擊區間之外逐秒回答上升星座，靠的不是取樣，是取樣之外的一個前提：
 *      在臺北這種非極區緯度，上升點黃經隨時間只往前走，所以後端以二分法
 *      夾出的那一次跨界（14:22:58–14:23:12，解析度 14 秒）是這一小時唯一
 *      的一次。極區附近這個前提不成立；後端的敏感度結果也不使用它。
 *   3. 那 14 秒之內顯示「取樣尚未分辨」，不猜一個看起來比較好看的答案。
 *   4. 逐秒回答落宮，另靠各天體在這一小時內不換星座：這張盤上每個天體在
 *      取樣點離星座界線至少 4.7°，移動最快的月亮整個小時只走了約 0.5°
 *      （以同一請求重算查核）。這是本示範資料的查核結果，
 *      不是後端對一般情形的保證。
 *
 * 所有數值取自一次實際計算：1990-05-15 14:00–15:00 臺北
 * （25.053060°N 121.526390°E），整宮制、回歸黃道、視位置、地心。
 */
(function attachSensitivity(root, timeFactory, demo) {
  // 時間軸的半開區間（timeFactory）是純函式，Node 測試直接 require 本檔取得；示範只在頁面上跑。
  const Time = timeFactory();
  if (typeof module === "object" && module.exports) module.exports = Time;
  if (root && root.document) demo(root.document, Time);
})(typeof globalThis !== "undefined" ? globalThis : this, function sensitivityTime() {
  "use strict";

  const HOUR_SECONDS = 3600;
  const LAST_SECOND = HOUR_SECONDS - 1;

  function clampSecond(value) {
    return Math.max(0, Math.min(LAST_SECOND, Math.round(value)));
  }

  function secondFromRatio(value) {
    const ratio = Math.max(0, Math.min(1, Number(value)));
    return clampSecond(ratio * LAST_SECOND);
  }

  function clockOf(value) {
    const second = clampSecond(value);
    const minute = Math.floor(second / 60);
    const remainder = second % 60;
    const pad = (number) => (number < 10 ? `0${number}` : String(number));
    return `14:${pad(minute)}:${pad(remainder)}`;
  }

  function isExactSample(value, sampleSeconds) {
    const second = clampSecond(value);
    return sampleSeconds.some((sample) => second === sample);
  }

  return Object.freeze({
    HOUR_SECONDS,
    LAST_SECOND,
    clampSecond,
    secondFromRatio,
    clockOf,
    isExactSample,
  });
}, function sensitivityDemo(document, Time) {
  "use strict";

  var root = document.getElementById("sens-demo");
  if (!root) return;

  var LAST_SECOND = Time.LAST_SECOND;

  // 後端回傳的五個取樣點（birth_time_sensitivity.angles.asc.sampled_values）
  var PROBES = [
    { at: 0, clock: "14:00:00", sign: "處女", dms: "24°46′40.7″" },
    { at: 900, clock: "14:15:00", sign: "處女", dms: "28°11′04.4″" },
    { at: 1800, clock: "14:30:00", sign: "天秤", dms: "1°35′32.3″" },
    { at: 2700, clock: "14:45:00", sign: "天秤", dms: "4°59′56.5″" },
    { at: 3599, clock: "14:59:59", sign: "天秤", dms: "8°23′55.8″" }
  ];

  // birth_time_sensitivity.transitions[0]：以二分法夾出的跨界區間
  var FLIP_LO = 22 * 60 + 58;
  var FLIP_HI = 23 * 60 + 12;

  // derived_methods.planet_in_house：跨界前後的實際落宮
  var BODIES = [
    ["太陽", 9, 8], ["月亮", 5, 4], ["水星", 9, 8], ["金星", 8, 7],
    ["火星", 7, 6], ["木星", 11, 10], ["土星", 5, 4], ["天王星", 5, 4],
    ["海王星", 5, 4], ["冥王星", 3, 2], ["凱龍星", 11, 10]
  ];

  var track = root.querySelector(".sd-track");
  var handle = root.querySelector(".sd-handle");
  var fill = root.querySelector(".sd-fill");
  var clockEl = root.querySelector(".sd-clock");
  var stateEl = root.querySelector(".sd-state");
  var ascEl = root.querySelector(".sd-asc");
  var noteEl = root.querySelector(".sd-note");
  var listEl = root.querySelector(".sd-bodies");

  var clockOf = Time.clockOf;

  /* 上升點度數：只在取樣點上斷言，其餘給區間。
     回傳兩段文字分別寫入兩個元素，不組 HTML 字串，本 repository 的前端契約
     規定 innerHTML 只能指派空字串（tests/integration/test_frontend_contract.py）。 */
  function ascParts(sec) {
    var exact = Time.isExactSample(sec, PROBES.map(function (probe) { return probe.at; }));
    if (exact) {
      var probe = PROBES.filter(function (item) { return item.at === sec; })[0];
      return {
        value: "上升 " + probe.sign + " " + probe.dms,
        note: "這是取樣點，值為實算"
      };
    }
    var lo = PROBES[0], hi = PROBES[PROBES.length - 1];
    for (var j = 0; j < PROBES.length - 1; j++) {
      if (sec >= PROBES[j].at && sec <= PROBES[j + 1].at) {
        lo = PROBES[j]; hi = PROBES[j + 1]; break;
      }
    }
    return {
      value: "上升介於 " + lo.sign + " " + lo.dms + "（" + lo.clock + "）與 " +
             hi.sign + " " + hi.dms + "（" + hi.clock + "）之間",
      note: "此刻沒有取樣，不內插"
    };
  }

  function render(sec) {
    var pct = (sec / LAST_SECOND) * 100;
    handle.style.left = pct + "%";
    fill.style.width = pct + "%";
    handle.setAttribute("aria-valuenow", String(sec));
    handle.setAttribute("aria-valuetext", clockOf(sec));
    clockEl.textContent = clockOf(sec);

    var phase = sec < FLIP_LO ? "before" : (sec > FLIP_HI ? "after" : "unknown");
    root.setAttribute("data-phase", phase);

    var stateText = phase === "before" ? "上升在處女"
      : (phase === "after" ? "上升在天秤" : "取樣尚未分辨");
    // stateEl 是 polite live region：只在狀態真的改變時重寫，否則每按一次
    // 方向鍵報讀器就重念一次同一句。
    if (stateEl.textContent !== stateText) stateEl.textContent = stateText;

    var parts = ascParts(sec);
    ascEl.textContent = parts.value;
    noteEl.textContent = parts.note;

    var rows = listEl.querySelectorAll("li");
    for (var i = 0; i < rows.length; i++) {
      var b = BODIES[i];
      var span = rows[i].querySelector("b");
      if (phase === "unknown") {
        span.textContent = "第 " + b[1] + " 或 " + b[2] + " 宮";
        rows[i].setAttribute("data-moved", "unknown");
      } else {
        var h = phase === "before" ? b[1] : b[2];
        span.textContent = "第 " + h + " 宮";
        rows[i].setAttribute("data-moved", phase === "after" ? "yes" : "no");
      }
    }
  }

  function secFromEvent(clientX) {
    var box = track.getBoundingClientRect();
    var ratio = (clientX - box.left) / box.width;
    ratio = Math.max(0, Math.min(1, ratio));
    return Time.secondFromRatio(ratio);
  }

  var dragging = false;
  var current = 0;

  /* 把手的「輕推」動畫由兩個 data 屬性一起決定（規則寫在 page.css）：
     data-seen 表示它已經捲進視窗，data-touched 表示使用者已經動過它。
     動畫在看不到的地方播放等於沒播，碰過之後還在動則是干擾，兩者都要避免。 */
  function markTouched() {
    root.setAttribute("data-touched", "yes");
  }

  if (typeof IntersectionObserver === "function") {
    var seen = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) {
          root.setAttribute("data-seen", "yes");
          seen.disconnect();
          return;
        }
      }
    }, { threshold: 0.35 });
    seen.observe(root);
  } else {
    root.setAttribute("data-seen", "yes");
  }

  function setFrom(clientX) {
    current = secFromEvent(clientX);
    render(current);
  }

  track.addEventListener("pointerdown", function (e) {
    markTouched();
    dragging = true;
    track.setPointerCapture(e.pointerId);
    setFrom(e.clientX);
  });
  track.addEventListener("pointermove", function (e) {
    if (dragging) setFrom(e.clientX);
  });
  track.addEventListener("pointerup", function () { dragging = false; });
  track.addEventListener("pointercancel", function () { dragging = false; });

  /* 鍵盤：方向鍵一分鐘，Home/End 到兩端，PageUp/PageDown 跳取樣點。 */
  handle.addEventListener("keydown", function (e) {
    var step = 60;
    var next = current;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = current - step;
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") next = current + step;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = LAST_SECOND;
    else if (e.key === "PageUp" || e.key === "PageDown") {
      // APG slider：PageUp 以較大步距「增加」，PageDown「減少」。
      var dir = e.key === "PageUp" ? 1 : -1;
      for (var i = 0; i < PROBES.length; i++) {
        var k = dir > 0 ? i : PROBES.length - 1 - i;
        if (dir > 0 ? PROBES[k].at > current : PROBES[k].at < current) {
          next = PROBES[k].at; break;
        }
      }
    } else return;
    markTouched();
    e.preventDefault();
    current = Time.clampSecond(next);
    render(current);
  });

  /* 跨界視窗只有 14 秒＝整條軌道的 0.39%，約三個像素——拖曳幾乎命中不了。
     軌道刻度必須誠實（畫寬會誇大那段的長度），所以改為讓標籤可點：
     尺度維持真實，最值得看的狀態仍然到得了。 */
  var flipcap = root.querySelector(".sd-flipcap");
  if (flipcap) {
    flipcap.addEventListener("click", function () {
      markTouched();
      current = Math.round((FLIP_LO + FLIP_HI) / 2);
      render(current);
      handle.focus();
    });
  }

  // 滑桿移動後上升星座是否改變，是這個示範要讓人聽到的結果；aria-valuetext
  // 只念時間（WCAG 4.1.3）。
  stateEl.setAttribute("aria-live", "polite");
  render(0);
});
