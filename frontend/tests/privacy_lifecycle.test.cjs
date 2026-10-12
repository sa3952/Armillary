const test = require("node:test");
const assert = require("node:assert/strict");

const PrivacyLifecycle = require("../../scripts/frontend/scripts/privacy-lifecycle.js");

const createLifecycle = (revoked = []) => PrivacyLifecycle.createSensitiveDataLifecycle({
  revokeObjectUrl: (url) => revoked.push(url),
});

test("canonical document and section registry reject arrays and keep a valid object", () => {
  const lifecycle = createLifecycle();
  assert.throws(() => lifecycle.setCanonicalDocument([]), /canonical document/);
  assert.throws(() => lifecycle.registerSectionNode([]), /輸出區段/);
  const documentModel = { calculation_dossier: { dossier_version: "0.3.0" }, sections: [] };
  lifecycle.setCanonicalDocument(documentModel);
  assert.equal(lifecycle.requireCanonicalDocument(), documentModel);
});

test("clear drops the canonical document, section references, and Blob URLs", () => {
  const revoked = [];
  const lifecycle = createLifecycle(revoked);
  const documentModel = {
    calculation_dossier: {
      input_receipt: { datetime: { year: 1997 }, location: { latitude: 22.9908, longitude: 120.2133 } },
    },
  };
  // 登記的 section 節點上沒有任何敏感欄位可清；clear 只放掉登記表對它的引用，
  // 不得在節點上寫一個從來沒被設定過的屬性，假裝清掉了什麼。
  const nodeWrites = [];
  const sectionNode = new Proxy({}, {
    set(target, key, value) {
      nodeWrites.push(String(key));
      target[key] = value;
      return true;
    },
  });
  lifecycle.setCanonicalDocument(documentModel);
  lifecycle.registerSectionNode(sectionNode);
  lifecycle.registerObjectUrl("blob:birth-data-one");
  lifecycle.registerObjectUrl("blob:birth-data-two");
  assert.deepEqual(lifecycle.inspect(), {
    has_canonical_document: true, active_object_url_count: 2, registered_section_count: 1, request_active: false,
  });

  assert.deepEqual(lifecycle.clear(), {
    canonical_document_cleared: true, object_urls_revoked: 2, section_references_cleared: 1, request_aborted: false,
  });
  assert.deepEqual(nodeWrites, [], "clear 不得在 section 節點上寫入任何屬性");
  assert.deepEqual(revoked, ["blob:birth-data-one", "blob:birth-data-two"]);
  assert.throws(() => lifecycle.requireCanonicalDocument(), /已清除或尚未完成計算/);
  assert.deepEqual(lifecycle.inspect(), {
    has_canonical_document: false, active_object_url_count: 0, registered_section_count: 0, request_active: false,
  });
});

test("a newer request and clear each abort and invalidate the previous request", () => {
  const lifecycle = createLifecycle();
  const first = new AbortController();
  const firstToken = lifecycle.beginRequest(first);
  const second = new AbortController();
  const secondToken = lifecycle.beginRequest(second);
  assert.equal(first.signal.aborted, true);
  assert.equal(lifecycle.isCurrentRequest(firstToken), false);
  assert.equal(lifecycle.isCurrentRequest(secondToken), true);
  lifecycle.finishRequest(secondToken);
  assert.equal(lifecycle.inspect().request_active, false);

  const third = new AbortController();
  const thirdToken = lifecycle.beginRequest(third);
  assert.equal(lifecycle.clear().request_aborted, true);
  assert.equal(third.signal.aborted, true);
  assert.equal(lifecycle.isCurrentRequest(thirdToken), false, "遲到的敏感回應必須失效");
});

test("the shared request timeout aborts only after its bounded delay", () => {
  const lifecycle = PrivacyLifecycle.createSensitiveDataLifecycle();
  const controller = new AbortController();
  let callback = null;
  const timeout = lifecycle.scheduleAbort(controller, 10000, (fn, delay) => {
    assert.equal(delay, 10000);
    callback = fn;
    return 47;
  });
  assert.equal(timeout.handle, 47);
  assert.equal(timeout.didTimeout(), false);
  assert.equal(controller.signal.aborted, false);
  callback();
  assert.equal(timeout.didTimeout(), true);
  assert.equal(controller.signal.aborted, true);
});

test("a timed request is the current request, aborts the one before it, and times out on its own controller", () => {
  const lifecycle = PrivacyLifecycle.createSensitiveDataLifecycle();
  const callbacks = [];
  const schedule = (fn, delay) => { callbacks.push({ fn, delay }); return callbacks.length; };
  const first = lifecycle.beginTimedRequest(5000, schedule);
  assert.ok(first.controller instanceof AbortController);
  assert.equal(lifecycle.isCurrentRequest(first.token), true);
  assert.equal(first.timeout.handle, 1);
  assert.equal(callbacks[0].delay, 5000);
  // The controller class can be the page window's own.
  class PageController extends AbortController {}
  const second = lifecycle.beginTimedRequest(7000, schedule, PageController);
  assert.ok(second.controller instanceof PageController);
  assert.equal(first.controller.signal.aborted, true, "a new request aborts the one in flight");
  assert.equal(lifecycle.isCurrentRequest(first.token), false);
  assert.equal(lifecycle.isCurrentRequest(second.token), true);
  callbacks[1].fn();
  assert.equal(second.timeout.didTimeout(), true);
  assert.equal(second.controller.signal.aborted, true);
  assert.equal(first.timeout.didTimeout(), false);
});

test("releasing a Blob URL is idempotent and clear does not revoke it twice", () => {
  const revoked = [];
  const lifecycle = createLifecycle(revoked);
  lifecycle.registerObjectUrl("blob:short-lived");
  assert.equal(lifecycle.releaseObjectUrl("blob:short-lived"), true);
  assert.equal(lifecycle.releaseObjectUrl("blob:short-lived"), false);
  lifecycle.clear();
  assert.deepEqual(revoked, ["blob:short-lived"]);
});

// 中止只停這一次請求，不得順手把已算出的結果一起收掉；中止不是清除。
test("aborting stops only the active request, reports honestly when idle, and a late response cannot revive itself", () => {
  const lifecycle = createLifecycle();
  assert.equal(lifecycle.abortActiveRequest(), false, "沒有請求在飛時不得宣稱中止了什麼");
  lifecycle.setCanonicalDocument({ export_contract_version: "0.1.2" });
  const controller = new AbortController();
  const token = lifecycle.beginRequest(controller);
  assert.equal(lifecycle.abortActiveRequest(), true);
  assert.equal(controller.signal.aborted, true);
  assert.equal(lifecycle.isCurrentRequest(token), false, "遲到的回應仍被視為當前");
  assert.equal(lifecycle.inspect().request_active, false);
  assert.deepEqual(lifecycle.requireCanonicalDocument(), { export_contract_version: "0.1.2" });

  // token 必須在 abort() 之前就失效，否則 abort() 丟例外時遲到的回應會被當成當前結果。
  const hostile = { signal: {}, abort() { throw new Error("abort refused"); } };
  const hostileToken = lifecycle.beginRequest(hostile);
  assert.equal(lifecycle.abortActiveRequest(), true);
  assert.equal(lifecycle.isCurrentRequest(hostileToken), false);
});
