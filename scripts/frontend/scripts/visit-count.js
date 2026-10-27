// 計數：每次載入頁面送一次「瀏覽」，每天最多送一次「今日訪客」。兩個請求都沒有內容、不帶 cookie；伺服器只把計數器加一，
// 不記錄任何一筆請求（backend/app/visit_counts.py）。瀏覽器開了 Global Privacy Control 就一個也不送。今日訪客靠瀏覽器自
// 己的快取去重：伺服器給的快取期限到臺灣的午夜為止，同一天再開頁面時瀏覽器直接讀快取，不會再問。
(function () {
  "use strict";
  if (navigator.globalPrivacyControl === true) return;
  try {
    fetch("/api/visit", { method: "POST", credentials: "omit", keepalive: true }).catch(() => {});
    fetch("/api/visit/daily", { credentials: "omit", cache: "default" }).catch(() => {});
  } catch (_) {
    // 計數失敗不影響頁面。
  }
})();
