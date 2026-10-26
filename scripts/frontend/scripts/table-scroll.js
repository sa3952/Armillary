// 橫向捲動表格的提示：建置時在每個捲動框前放了一行 hidden 的「表格可左右捲動」，
// 這裡只在框裡的表格真的比框寬（還有看不到的欄）時把它打開，框變寬或表格疊成卡片時再收起。
// 框的 tab 停留點跟著提示走：放得下的框多一個停留點只是噪音（計算頁的表格同一規則）。
// 建置時寫在框上的 tabindex 是沒有腳本時的預設，看不到的欄仍可用鍵盤捲到。
//
// served CSP 是 script-src 'self'、require-trusted-types-for 'script'、trusted-types 'none'：
// 只切換 hidden，不用 innerHTML、行內事件或 style 屬性。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.install(root.document, root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const HINT = "p.scroll-hint";
  // 建置時（scripts/frontend/table_layout.py）標在每個表格捲動框上，疊排的表格也有。
  const FRAME = "[data-scroll-frame]";

  // 捲動框比可見寬度多出 1px 以上才算溢出（避開次像素的捨入）。
  function overflows(box) {
    return Boolean(box) && box.scrollWidth - box.clientWidth > 1;
  }

  function update(doc) {
    // 先量完全部再寫：邊量邊寫時，每寫一次屬性，下一次量就得重排一次版面。
    const frames = [...doc.querySelectorAll(FRAME)];
    const scrolling = frames.map(overflows);
    frames.forEach((box, index) => {
      const hint = box.previousElementSibling;
      if (hint && hint.matches(HINT)) hint.hidden = !scrolling[index];
      if (scrolling[index]) box.setAttribute("tabindex", "0");
      else box.removeAttribute("tabindex");
    });
  }

  function install(doc, win) {
    const run = () => update(doc);
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", run, { once: true });
    else run();
    if (win && typeof win.ResizeObserver === "function") {
      const observer = new win.ResizeObserver(run);
      const observe = () => doc.querySelectorAll(FRAME).forEach((box) => {
        observer.observe(box);
        if (box.firstElementChild) observer.observe(box.firstElementChild);
      });
      if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", observe, { once: true });
      else observe();
    } else if (win) {
      win.addEventListener("resize", run);
    }
    // 收合段落打開後，裡面的表格才有寬度。
    doc.addEventListener("toggle", run, true);
  }

  return { install, update, overflows };
});
