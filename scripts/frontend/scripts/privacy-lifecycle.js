(function attachPrivacyLifecycle(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.PrivacyLifecycle = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function buildPrivacyLifecycle() {
  "use strict";

  function createSensitiveDataLifecycle(options = {}) {
    const revokeObjectUrl =
      typeof options.revokeObjectUrl === "function"
        ? options.revokeObjectUrl
        : (url) => URL.revokeObjectURL(url);

    let canonicalDocument = null;
    let activeRequest = null;
    const objectUrls = new Set();
    const sectionNodes = new Set();

    function setCanonicalDocument(documentModel) {
      if (
        !documentModel ||
        typeof documentModel !== "object" ||
        Array.isArray(documentModel)
      ) {
        throw new Error("缺少可追溯的 canonical document。");
      }
      canonicalDocument = documentModel;
    }

    function requireCanonicalDocument() {
      if (!canonicalDocument) {
        throw new Error("敏感計算資料已清除或尚未完成計算。");
      }
      return canonicalDocument;
    }

    function registerSectionNode(node) {
      if (!node || typeof node !== "object" || Array.isArray(node)) {
        throw new Error("無法登記輸出區段的敏感資料引用。");
      }
      sectionNodes.add(node);
    }

    function registerObjectUrl(url) {
      if (typeof url !== "string" || !url) {
        throw new Error("無法登記空白的 Blob URL。");
      }
      objectUrls.add(url);
      return url;
    }

    function releaseObjectUrl(url) {
      if (!objectUrls.delete(url)) return false;
      try {
        revokeObjectUrl(url);
      } catch (_error) {
        // Revoke failure must not restore the URL to the active registry or
        // expose exception details. Browser/OS retention remains out of scope.
      }
      return true;
    }

    function beginRequest(controller) {
      if (!controller || typeof controller.abort !== "function") {
        throw new Error("敏感 request 必須使用可中止的 AbortController。");
      }
      if (activeRequest) {
        try {
          activeRequest.controller.abort();
        } catch (_error) {
          // Replacing activeRequest below invalidates the old token even if
          // the browser refuses to abort the transport.
        }
      }
      const token = Object.freeze({});
      activeRequest = { controller, token };
      return token;
    }

    function isCurrentRequest(token) {
      return Boolean(activeRequest && activeRequest.token === token);
    }

    function finishRequest(token) {
      if (!isCurrentRequest(token)) return false;
      activeRequest = null;
      return true;
    }

    function scheduleAbort(controller, delayMs, scheduleTimeout = setTimeout) {
      if (!controller || typeof controller.abort !== "function") {
        throw new Error("逾時控制必須使用可中止的 AbortController。");
      }
      if (!Number.isFinite(delayMs) || delayMs <= 0) {
        throw new Error("逾時上限必須是正數。");
      }
      let timedOut = false;
      const handle = scheduleTimeout(() => {
        timedOut = true;
        try { controller.abort(); } catch (_error) { /* token另行判斷是否有效 */ }
      }, delayMs);
      return Object.freeze({ handle, didTimeout: () => timedOut });
    }

    /**
     * 一次請求的起手式：新的 AbortController、它成為目前請求的 token、它的逾時。
     * Controller 可以是頁面視窗自己的類別。
     */
    function beginTimedRequest(delayMs, scheduleTimeout, Controller = AbortController) {
      const controller = new Controller();
      const token = beginRequest(controller);
      return { controller, token, timeout: scheduleAbort(controller, delayMs, scheduleTimeout) };
    }

    /**
     * 中止進行中的請求，但**不動**已算出的結果。
     *
     * `clear()` 也會 abort，可是它同時作廢 canonical document、section 參照
     * 與 Blob URL——那是「清除」的語意。使用者按「中止這次計算」時要的是
     * 停下這一次，不是把上一次的結果一起收掉。
     *
     * 回傳是否真的有一個請求被中止，讓呼叫端不必猜。
     */
    function abortActiveRequest() {
      if (!activeRequest) return false;
      // 先清掉token：即使abort()丟例外，遲到的回應也必須被擋下。
      const request = activeRequest;
      activeRequest = null;
      try {
        request.controller.abort();
      } catch (_error) {
        // token已作廢。
      }
      return true;
    }

    function clear() {
      const receipt = {
        canonical_document_cleared: canonicalDocument !== null,
        object_urls_revoked: objectUrls.size,
        section_references_cleared: sectionNodes.size,
        request_aborted: activeRequest !== null,
      };

      canonicalDocument = null;
      if (activeRequest) {
        const request = activeRequest;
        activeRequest = null;
        try {
          request.controller.abort();
        } catch (_error) {
          // The token is already invalid even if abort() fails.
        }
      }

      // 登記表只持有 section 節點的引用；節點上沒有任何敏感欄位（section 快照
      // 在 calculate.js 的 sectionSnapshots，由呼叫端清除，DOM 由呼叫端移除）。
      // 清除就是放掉這些引用，不在節點上寫一個從未被設定過的屬性，假裝清掉了
      // 什麼。
      sectionNodes.clear();

      for (const url of Array.from(objectUrls)) {
        releaseObjectUrl(url);
      }

      return receipt;
    }

    function inspect() {
      return {
        has_canonical_document: canonicalDocument !== null,
        active_object_url_count: objectUrls.size,
        registered_section_count: sectionNodes.size,
        request_active: activeRequest !== null,
      };
    }

    return Object.freeze({
      setCanonicalDocument,
      requireCanonicalDocument,
      registerSectionNode,
      registerObjectUrl,
      releaseObjectUrl,
      beginRequest,
      isCurrentRequest,
      finishRequest,
      scheduleAbort,
      beginTimedRequest,
      abortActiveRequest,
      clear,
      inspect,
    });
  }

  return Object.freeze({ createSensitiveDataLifecycle });
});
