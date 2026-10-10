# Security policy／安全政策

[English](#english) · [繁體中文](#繁體中文)

This project is a free, single-operator calculator. This policy says how to report a vulnerability, what
happens next, and where the boundaries are. Nothing here claims that vulnerabilities are absent.

本專案是一個免費、由一人營運的計算工具。這份政策說明怎麼回報漏洞、回報之後會發生什麼，以及界線在哪裡。
這裡沒有任何一句宣稱本專案沒有漏洞。

---

## English

### Supported versions

| Version | Receives fixes |
|---|---|
| The release live on https://projectarmillary.com (its revision is printed in every calculation receipt and listed on the [Releases](https://github.com/sa3952/Armillary/releases) page) | Yes |
| The release named by the immediate rollback receipt | Yes, until it is no longer the rollback target |
| Any older revision, fork or self-hosted copy | No |

No long-term support period is promised.

### Report privately

1. Use [GitHub private vulnerability reporting](https://github.com/sa3952/Armillary/security/advisories/new).
   This is the preferred and only channel for vulnerability details.
2. If that channel is unavailable to you, send only a minimal contact request — without vulnerability
   details — to `privacy@projectarmillary.com`, and we will arrange a private channel. This one mailbox is
   shared by privacy requests, security contact and general mail; how a message is handled and stored is
   described on the [contact page](https://projectarmillary.com/zh-TW/contact).

Please **never** put birth data, credentials, tokens, host locators or another person's data in a report,
an issue, a pull request or a discussion. Use synthetic inputs only — the calculator has a built-in
synthetic example.

### What a useful report contains

- the affected revision (from the calculation receipt or a release tag) or the file and line in this
  repository;
- the affected URL, endpoint or component, and the request you sent (synthetic data only);
- step-by-step reproduction, what you observed and what you expected;
- the impact you believe it has (confidentiality, integrity, availability, privacy) and any preconditions;
- whether and how you would like to be credited.

Reports in Traditional Chinese or English are both welcome.

### What happens next

- **Acknowledgement:** the operator aims to acknowledge a complete report within seven days. This is
  best-effort, not an SLA.
- **Triage:** we reproduce the issue against the supported versions and tell you whether we consider it a
  vulnerability, a hardening item or out of scope, with the reason.
- **Fix:** a fix ships as a normal release through the documented release gates; the release notes and the
  calculation receipt name the fixed revision.
- **Disclosure:** we prefer coordinated disclosure — we agree a date with you and publish a GitHub security
  advisory after the fix is live. Please do not disclose before then. If we cannot reach agreement, we will
  tell you why.
- **Credit:** with your permission, we credit you in the advisory. There is no monetary reward.

### Scope and authorized boundary

In scope: the source code in this repository, and behaviour of https://projectarmillary.com that you
observe through **normal use** of its public pages (for example a header, cache or privacy behaviour that
contradicts what the [security page](https://projectarmillary.com/zh-TW/security) states).

Source review and testing on systems you own are welcome: the repository can be run locally
(see [README](README.md)). This policy does **not** authorize testing of the hosted service, credential
enumeration, DoS or load testing, automated scanning that exceeds normal use, social engineering,
persistence, destruction, third-party infrastructure testing, or access to another person's data. Stop
before affecting availability or confidentiality. No bug bounty or additional safe-harbor promise is
offered.

### Usually not treated as vulnerabilities

Reports are still read, but these are normally closed as informational unless you show a concrete impact:

- missing "best-practice" headers or scanner grades without an exploit (the current header set and its
  reasons are listed on the security page);
- rate limiting, `429` or `503` responses — these are designed limits;
- the `Server: nginx` header without a version, or other non-sensitive version disclosure;
- clickjacking on pages without state-changing actions (`frame-ancestors 'none'` is already sent);
- self-XSS, attacks that require a compromised device, browser extension or physical access;
- TLS configuration preferences that do not lead to a practical downgrade (known hardening items are
  tracked openly);
- reports generated only by automated tools without reproduction or impact.

### Background reading

- Security page (attack surface, logging fields, limits, failure behaviour):
  https://projectarmillary.com/zh-TW/security
- Threat model: [docs/PRIVACY_THREAT_MODEL.md](docs/PRIVACY_THREAT_MODEL.md)
- Privacy architecture and logging policy: [docs/PRIVACY_ARCHITECTURE.md](docs/PRIVACY_ARCHITECTURE.md),
  [docs/PRIVACY_LOGGING_POLICY.md](docs/PRIVACY_LOGGING_POLICY.md)
- Known limitations: [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)
- Reproducible build: [docs/REPRODUCIBLE_BUILD.md](docs/REPRODUCIBLE_BUILD.md)

### What this policy does not prove

The exporter produces `/.well-known/security.txt` with a release-derived expiry; its presence in the source
does not prove the live path, content type, redirect, canonical URL or expiry. Public source and templates
also do not prove provider, DNS, CA, operator device, browser, RAM, swap, backup or support-access
behavior. Nothing here claims vulnerability absence, whole-repository approval or professional
suitability.

---

## 繁體中文

### 支援的版本

| 版本 | 是否修補 |
|---|---|
| 目前在 https://projectarmillary.com 上線的版本（每一份計算收據都會印出它的 revision，也列在 [Releases](https://github.com/sa3952/Armillary/releases) 頁） | 是 |
| 立即回退收據所指的版本 | 是，直到它不再是回退目標 |
| 其他舊版本、fork 或自行架設的副本 | 否 |

不承諾長期支援期間。

### 私下回報

1. 請使用 [GitHub private vulnerability reporting](https://github.com/sa3952/Armillary/security/advisories/new)。
   這是漏洞細節唯一、也是優先的管道。
2. 如果你無法使用這個管道，請只寄一封**不含漏洞細節**的聯絡請求到 `privacy@projectarmillary.com`，我們會另外安排私下管道。
   這個信箱同時用於個資權利請求、安全聯絡與一般來信；一封信會怎麼處理、存在哪裡，寫在
   [聯絡頁](https://projectarmillary.com/zh-TW/contact)。

**請不要**在回報、issue、pull request 或 discussion 裡放入出生資料、帳密、token、主機位置資訊或任何他人的資料。
請只用合成資料——計算頁內建「載入合成範例」。

### 一份有用的回報包含

- 受影響的版本（計算收據或 release tag 上的 revision），或本 repo 的檔案與行號；
- 受影響的網址、端點或元件，以及你送出的請求（只用合成資料）；
- 逐步重現方式、你觀察到的結果與預期的結果；
- 你認為的影響（機密性、完整性、可用性、隱私）與前提條件；
- 你是否希望、以及希望怎麼被致謝。

繁體中文或英文的回報都歡迎。

### 回報之後

- **確認收到：**營運者會盡量在七天內回覆一份完整的回報。這是盡力而為，不是服務等級承諾（SLA）。
- **分類：**我們在支援的版本上重現問題，並告訴你我們認為它是漏洞、加固項目，或不在範圍內，以及理由。
- **修補：**修補以一般發布的方式、經過既有的發布閘門上線；release 說明與計算收據會寫出修正後的 revision。
- **揭露：**我們偏好協調揭露——和你約定日期，修補上線後發布 GitHub security advisory。在那之前請不要公開。若無法取得共識，我們會說明原因。
- **致謝：**經你同意，我們會在 advisory 中致謝。沒有金錢獎勵。

### 範圍與授權界線

在範圍內：本 repo 的原始碼，以及你**正常使用**公開頁面時觀察到的 https://projectarmillary.com 行為（例如某個標頭、快取或隱私行為和〈[安全](https://projectarmillary.com/zh-TW/security)〉頁的說法不一致）。

歡迎審閱原始碼，以及在你自己擁有的系統上測試：本 repo 可以在本機執行（見 [README](README.md)）。本政策**不**授權：測試正式服務、帳密列舉、DoS 或壓力測試、超出正常使用的自動化掃描、社交工程、植入持續存取、破壞、測試第三方基礎設施，或存取他人資料。在影響可用性或機密性之前請停止。沒有漏洞獎金，也不提供額外的安全港（safe harbor）承諾。

### 通常不視為漏洞

我們仍會閱讀這些回報，但除非你能證明具體影響，通常以「資訊性」結案：

- 缺少某個「最佳做法」標頭或掃描工具的評分，但沒有可利用的方式（目前送出的標頭與理由列在〈安全〉頁）；
- 限流、`429` 或 `503` 回應——這些是設計好的上限；
- 不含版本的 `Server: nginx` 標頭，或其他不敏感的版本資訊；
- 沒有狀態變更動作的頁面被嵌入框架（已送出 `frame-ancestors 'none'`）；
- self-XSS，或需要裝置已被入侵、瀏覽器擴充功能或實體接觸的攻擊；
- 不會造成實際降級的 TLS 設定偏好（已知的加固項目會公開追蹤）；
- 只有自動化工具產出、沒有重現步驟或影響說明的報告。

### 延伸閱讀

- 〈安全〉頁（攻擊面、日誌欄位、上限、故障時的行為）：https://projectarmillary.com/zh-TW/security
- 威脅模型：[docs/PRIVACY_THREAT_MODEL.md](docs/PRIVACY_THREAT_MODEL.md)
- 隱私架構與日誌政策：[docs/PRIVACY_ARCHITECTURE.md](docs/PRIVACY_ARCHITECTURE.md)、[docs/PRIVACY_LOGGING_POLICY.md](docs/PRIVACY_LOGGING_POLICY.md)
- 已知限制：[docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)
- 可重現建置：[docs/REPRODUCIBLE_BUILD.md](docs/REPRODUCIBLE_BUILD.md)

### 這份政策證明不了的事

匯出程式會產生帶有依發布推得之到期日的 `/.well-known/security.txt`；它存在於原始碼中，不代表線上的路徑、內容類型、轉址、canonical URL 或到期日一定正確。公開原始碼與範本也證明不了供應商、DNS、憑證機構、營運者裝置、瀏覽器、記憶體、swap、備份或支援存取的實際行為。這裡沒有任何一句宣稱沒有漏洞、整個 repo 已獲核可，或適用於專業用途。
