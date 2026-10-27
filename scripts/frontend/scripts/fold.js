// 方法頁與信任頁的段落收合（只在這兩頁載入）。
//
// 收合本身是原生 <details data-fold>：不跑這支檔案也能開合，鍵盤（Tab、Enter、空白鍵）與報讀器照瀏覽器的原生行為；
// Chromium 的頁內搜尋與錨點導覽也會自己打開被收起的段落。這裡只加五件事：  1. 「全部展開／全部收合」兩顆按鈕
// （[data-fold-tools]，沒有這支檔案時保持 hidden）。  2. 讀過的段落自動收起：一個打開的段落整個捲到視窗上緣以上，就把它
// 收起，並把捲動位置補回去，     讓視窗裡正在讀的那一行不動。按過「全部展開」之後不自動收，直到有人收起任何一段。  3.
// 錨點：網址的 #id 或頁內連結指到收起的段落裡時，先打開它的每一層段落，再捲到目標；     指到段落標題本身時，也打開那一
// 段。  4. 段落標題、編號與「重點」一行也可以點來開合（滑鼠的便利；鍵盤用 summary）。  5. 列印時全部展開，印完還原（樣
// 式表另有同一件事的 @media print 後備）。
//
// served CSP 是 script-src 'self'、require-trusted-types-for 'script'、trusted-types 'none'：只用 open、hidden、
// classList 與 scroll API，不用 innerHTML、行內事件或 style 屬性。
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root && root.document) api.install(root.document, root);
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const FOLD = "details[data-fold]";
  const HOST = "[data-fold-host]";
  const HEAD = ".sig, h2, h3, .fold-gist, [data-fold-head]";
  const isHead = (node) => Boolean(node && node.parentElement && node.parentElement.matches(HOST) && node.matches(HEAD));

  function ownFold(host) {
    if (!host) return null;
    for (const child of host.children) { if (child.matches(FOLD)) return child; }
    return null;
  }

  // 要看見 target，必須打開的收合體，由外而內：它所在的每一層，加上 target 是段頭（或段落容器本身）時那一段自己的。
  function foldsToOpen(target) {
    const chain = [];
    for (let node = target.parentElement; node; node = node.parentElement) { if (node.matches(FOLD)) chain.unshift(node); }
    const host = target.matches(HOST) ? target : isHead(target) ? target.parentElement : null;
    const own = ownFold(host);
    if (own && !chain.includes(own)) chain.push(own);
    return chain;
  }

  const inSummary = (fold, node) => {
    const summary = typeof fold.querySelector === "function" ? fold.querySelector(":scope > summary") : null;
    return Boolean(summary && summary.contains(node));
  };

  // 讀過的段落：已打開、整個在視窗上緣以上（bottom ≤ 0），而且它的段落（含段頭）不含 keep，正文裡也沒有焦點（焦點在
  // summary 上不算：收起後 summary 仍看得見，焦點不會掉）。rectOf 由呼叫端提供，單元測試可以餵假的幾何。
  function passedFolds(folds, rectOf, keep, focused) {
    return folds.filter((fold) => fold.open
      && rectOf(fold).bottom <= 0 && !(keep && (fold.parentElement || fold).contains(keep))
      && !(focused && fold.contains(focused) && !inSummary(fold, focused)));
  }

  // 做 change() 前後，讓 anchor 在視窗裡的位置不變。anchor 在 change 之後若被收進看不見的地方，
  // 改把藏住它的最外層那一段的段頭捲回視窗上緣（只往回捲，不往前推）。
  function keepPosition(win, anchor, change) {
    if (!anchor) { change(); return; }
    const before = anchor.getBoundingClientRect().top;
    change();
    let hiddenBy = null;
    for (let node = anchor; node; node = node.parentElement) {
      if (node === anchor || !node.matches(FOLD) || node.open) continue;
      const summary = node.querySelector(":scope > summary");
      if (!(summary && summary.contains(anchor))) hiddenBy = node;
    }
    if (hiddenBy) {
      const top = (hiddenBy.parentElement || hiddenBy).getBoundingClientRect().top;
      if (top < 0) win.scrollBy(0, top);
      return;
    }
    const delta = anchor.getBoundingClientRect().top - before;
    if (delta !== 0) win.scrollBy(0, delta);
  }

  function install(doc, win) {
    const folds = () => Array.from(doc.querySelectorAll(FOLD));
    if (!folds().length) return null;
    doc.documentElement.classList.add("fold-js");
    // 這支檔案自己開合的段落：它們的 toggle 事件不當成讀者的動作。
    const ours = new WeakSet();
    const setOpen = (fold, open) => { if (fold.open === open) return; ours.add(fold); fold.open = open; };
    let expandedAll = false;
    function anchorAtTop() {
      const width = win.innerWidth || doc.documentElement.clientWidth || 0;
      const hit = typeof doc.elementFromPoint === "function" ? doc.elementFromPoint(width / 2, 1) : null;
      return hit && hit !== doc.documentElement && hit !== doc.body ? hit : null;
    }
    function collapsePassed(keep) {
      if (expandedAll) return;
      const passed = passedFolds(folds(), (fold) => fold.getBoundingClientRect(), keep, doc.activeElement);
      // 外層收起就連內層一起看不見；只收最外層的，內層留著原狀，下次打開外層時照舊。
      const outermost = passed.filter((fold) => !passed.some((other) => other !== fold && other.contains(fold)));
      if (!outermost.length) return;
      keepPosition(win, keep || anchorAtTop(), () => outermost.forEach((fold) => setOpen(fold, false)));
    }
    function reveal(target, smooth) {
      const chain = foldsToOpen(target);
      chain.forEach((fold) => setOpen(fold, true));
      collapsePassed(target);
      const reduce = typeof win.matchMedia === "function" && win.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (typeof target.scrollIntoView === "function") {
        target.scrollIntoView({ block: "start", behavior: smooth && !reduce ? "smooth" : "auto" });
      }
    }
    function targetOf(hash) {
      if (!hash || hash.length < 2) return null;
      let id;
      try { id = decodeURIComponent(hash.slice(1)); } catch (_error) { return null; }
      return doc.getElementById(id);
    }
    const tools = doc.querySelector("[data-fold-tools]");
    if (tools) {
      tools.hidden = false;
      tools.addEventListener("click", (event) => {
        const button = event.target.closest("[data-fold-all]");
        if (!button) return;
        const open = button.getAttribute("data-fold-all") === "open";
        expandedAll = open;
        keepPosition(win, anchorAtTop(), () => folds().forEach((fold) => setOpen(fold, open)));
      });
    }
    // 2. 讀者打開一段時，收起已經讀過的；讀者收起任何一段，就離開「全部展開」。
    doc.addEventListener("toggle", (event) => {
      const fold = event.target;
      if (!fold.matches || !fold.matches(FOLD)) return;
      if (ours.has(fold)) { ours.delete(fold); return; }
      if (!fold.open) { expandedAll = false; return; }
      collapsePassed(fold);
    }, true);
    let settle = null;
    const onScrollSettled = () => { settle = null; collapsePassed(null); };
    if ("onscrollend" in win) { win.addEventListener("scrollend", onScrollSettled, { passive: true }); } else {
      win.addEventListener("scroll", () => {
        if (settle !== null) win.clearTimeout(settle);
        settle = win.setTimeout(onScrollSettled, 200);
      }, { passive: true });
    }
    const fromHash = () => { const target = targetOf(win.location.hash); if (target) reveal(target, false); };
    win.addEventListener("hashchange", fromHash);
    doc.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0) return;
      const link = event.target.closest && event.target.closest("a[href*='#']");
      if (link) {
        const url = new URL(link.href, win.location.href);
        if (url.pathname !== win.location.pathname || url.origin !== win.location.origin) return;
        const target = targetOf(url.hash);
        // 打開就好；捲到目標交給瀏覽器的錨點導覽（它在這個 click 之後才發生）。
        if (target) foldsToOpen(target).forEach((fold) => setOpen(fold, true));
        return;
      }
      // 4. 段頭可以點來開合；點到連結、按鈕或選取文字時不算。
      const head = event.target.closest && event.target.closest(HEAD);
      if (!isHead(head) || event.target.closest("a, button")) return;
      const selection = typeof win.getSelection === "function" ? win.getSelection() : null;
      if (selection && !selection.isCollapsed && head.contains(selection.anchorNode)) return;
      const fold = ownFold(head.parentElement);
      if (fold) fold.open = !fold.open;
    });
    if (win.location.hash) fromHash();
    let beforePrint = null;
    win.addEventListener("beforeprint", () => {
      beforePrint = folds().map((fold) => [fold, fold.open]);
      beforePrint.forEach(([fold]) => setOpen(fold, true));
    });
    win.addEventListener("afterprint", () => {
      if (!beforePrint) return;
      beforePrint.forEach(([fold, open]) => setOpen(fold, open));
      beforePrint = null;
    });
    return { reveal, collapsePassed };
  }

  return Object.freeze({ foldsToOpen, passedFolds, keepPosition, install });
});
