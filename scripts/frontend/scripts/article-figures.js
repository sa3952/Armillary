// 文章圖版的互動（只在宣告了互動圖的文章載入）。
//
// 圖本身不靠這支檔案就完整：SVG 畫的是預設版本，圖說說明它，表格列出每個數字。這裡只做三件事：
//   1. 焦點與滑鼠：帶 [data-fx-key] 的元素一起亮起，並把隱藏清單 [data-fx-notes] 裡同 key 的那一句
//      複製到 [data-fx-readout]；Esc 清除。
//   2. 版本：按鈕 [data-fx-set] 切換顯示哪一組 [data-fx-variant]。
//   3. 拖拉條：[data-fx-scrub] 選顯示哪一組 [data-fx-step]。
// 每個數字都由建置時的產生器寫進頁面，這裡不計算、不組字。
//
// served CSP 是 script-src 'self'、style-src 'self'、require-trusted-types-for 'script'、
// trusted-types 'none'：所以只用 textContent、classList、setAttribute 與 hidden，不用 innerHTML、
// 行內事件或 style 屬性。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.init(root.document);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const each = (scope, selector, fn) => Array.prototype.forEach.call(scope.querySelectorAll(selector), fn);
  const inNotes = (el) => el.closest("[data-fx-notes]") !== null;

  function enhance(fig) {
    if (fig.classList.contains("fx-js")) return;
    const doc = fig.ownerDocument;
    const readout = fig.querySelector("[data-fx-readout]");
    const notes = Array.from(fig.querySelectorAll("[data-fx-notes] > li"));
    const state = {
      variant: fig.getAttribute("data-fx-default-variant"),
      step: fig.getAttribute("data-fx-default-step"),
      key: null,
    };
    const idle = readout ? readout.textContent : "";

    // The sentence for what is pointed at: the key's (in this variant), else the step's.
    function sentence() {
      const fits = (li) => {
        const variant = li.getAttribute("data-fx-variant");
        return variant === null || variant === state.variant;
      };
      if (state.key !== null) {
        const found = notes.find((li) => li.getAttribute("data-fx-key") === state.key && fits(li));
        return found ? found.textContent : null;
      }
      if (state.step !== null) {
        const found = notes.find((li) => li.getAttribute("data-fx-step") === state.step
          && !li.hasAttribute("data-fx-key") && fits(li));
        return found ? found.textContent : null;
      }
      return null;
    }

    function render() {
      each(fig, "[data-fx-variant]", (el) => {
        if (!inNotes(el)) el.classList.toggle("fx-off", el.getAttribute("data-fx-variant") !== state.variant);
      });
      each(fig, "[data-fx-step]", (el) => {
        if (!inNotes(el)) el.classList.toggle("fx-off", el.getAttribute("data-fx-step") !== state.step);
      });
      each(fig, "[data-fx-set]", (button) => {
        button.setAttribute("aria-pressed", String(button.getAttribute("data-fx-set") === state.variant));
      });
      each(fig, "[data-fx-key]", (el) => {
        if (!inNotes(el)) el.classList.toggle("is-active", el.getAttribute("data-fx-key") === state.key);
      });
      fig.classList.toggle("has-active", state.key !== null);
      if (readout) readout.textContent = sentence() || idle;
    }

    function point(key) { state.key = key; render(); }
    // When the pointer leaves, the mark that has keyboard focus (if any) is pointed at again.
    function focusedKey() {
      const focused = doc.activeElement;
      return focused && fig.contains(focused) && focused.hasAttribute("data-fx-key")
        ? focused.getAttribute("data-fx-key") : null;
    }
    function release(key) { if (state.key === key) point(focusedKey()); }

    each(fig, "[data-fx-key][tabindex]", (el) => {
      const key = el.getAttribute("data-fx-key");
      el.addEventListener("focus", () => point(key));
      el.addEventListener("blur", () => { if (state.key === key) point(null); });
      el.addEventListener("pointerenter", () => point(key));
      el.addEventListener("pointerleave", () => release(key));
    });
    fig.addEventListener("keydown", (event) => {
      if (event.key !== "Escape" || state.key === null) return;
      const focused = focusedKey() === null ? null : doc.activeElement;
      point(null);
      if (focused) focused.blur();
    });

    each(fig, "[data-fx-set]", (button) => {
      button.addEventListener("click", () => {
        state.variant = button.getAttribute("data-fx-set");
        render();
      });
    });

    each(fig, "[data-fx-scrub]", (input) => {
      const sync = () => {
        state.step = input.value;
        render();
        input.setAttribute("aria-valuetext", sentence() || input.value);
      };
      input.addEventListener("input", sync);
      sync();
    });

    each(fig, "[data-fx-switch], [data-fx-scrub-row]", (el) => { el.hidden = false; });
    if (readout) readout.hidden = false;
    fig.classList.add("fx-js");
    render();
  }

  function init(doc) {
    const start = () => each(doc, "figure[data-fx]", enhance);
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", start);
    else start();
  }

  return Object.freeze({ enhance, init });
});
