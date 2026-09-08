<p align="center">
  <img src="armillary-mark.svg" width="104" alt="Armillary current ring mark">
</p>

<h1 align="center">Armillary</h1>

<p align="center">
  <strong>Private by architecture. Exact about assumptions. Built to be challenged.</strong><br>
  隱私不是附加選項；方法不藏在黑箱裡；每一張盤都應該經得起追問。
</p>

<p align="center">
  <a href="https://projectarmillary.com/">Website</a> ·
  <a href="https://github.com/sa3952/Armillary/releases">Releases</a> ·
  <a href="docs/PRIVACY_ARCHITECTURE.md">Privacy</a> ·
  <a href="SECURITY.md">Security</a>
</p>

<p align="center">
  <a href="https://github.com/sa3952/Armillary/actions/workflows/tests.yml"><img src="https://github.com/sa3952/Armillary/actions/workflows/tests.yml/badge.svg" alt="Tests"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-AGPL--3.0-8b2131.svg" alt="License: AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/privacy-no_chart_database-355c4b.svg" alt="No chart database">
  <img src="https://img.shields.io/badge/Python-3.14-3776ab.svg" alt="Python 3.14">
  <img src="https://img.shields.io/badge/language-繁體中文-c44536.svg" alt="Traditional Chinese">
</p>

---

Armillary is an open-source classical astrology calculator built for people who want more than a polished
answer—and who do not want intimate birth data turned into an account history. Its Private Alpha deployment
has no account database, no chart-history database, no application user-data volume, and no application
Internet egress. The calculation remains inspectable: the effective time and place, coordinate systems,
selected methods, data sources, unavailable modules, warnings, and release identity travel with the result.

**渾儀 Armillary**是一套以繁體中文為主、可檢查且可重現的古典西洋占星計算工具。它不建立帳號或
星盤歷史資料庫，不把出生資料當成日後分析或行銷的素材；它也不把複雜選擇藏在一句「系統預設」後面。
你可以看見實際執行了什麼、哪些沒有執行，以及結果來自哪裡。

> **Private Alpha is live and invite-only.** The source for every live release remains public. Broader access
> will open after real-user feedback confirms that the calculation and export workflows are ready.
>
> **Private Alpha已上線，目前採邀請制。** 每一個live版本的原始碼都保持公開；待真實使用者確認計算與
> 匯出流程已足夠成熟後，再擴大開放。

## Why Armillary?

### Your birth data is not the product

Birth time and precise location can be deeply identifying. Armillary's current deployment is deliberately
small and forgetful: credentials terminate at the reverse proxy, the application receives no credential to
store, request and response bodies are excluded from application logs, NGINX access logging is disabled, and
client IP headers are not forwarded to the application. Availability notifications use a closed event schema
that contains no chart input, response, credential, IP address, header, or exception text.

出生時間與精確地點具有高度識別性。因此Armillary刻意採取「小而健忘」的架構：credential在reverse proxy
終止，計算application不接收可保存的credential；application log排除request／response body，NGINX關閉
access log，也不把client IP headers向後傳遞。Availability通知採封閉schema，不包含星盤輸入、回應、
credential、IP、header或exception文字。

### It respects what you actually know

Birth time is not always exact. Armillary distinguishes an exact minute, an approximate hour, and a date-only
input instead of silently inventing precision. Ambiguous or nonexistent civil times are surfaced as choices
or actionable errors.

出生時間不一定精確。Armillary分開「精確到分鐘」「只知道約略小時」與「只知道日期」，不會無聲捏造一個
精確時刻；遇到重複或不存在的民用時間，則提供選擇或可行動的錯誤說明。

### It shows its work

A result can carry the engine and ephemeris identity, time conversion, observer location, coordinate frame,
requested and executed options, warnings, method identifiers, trace digest, and reproducibility receipt.
Astronomical facts, deterministic geometry, astrological methods, and interpretation remain separate layers.

一份結果可以帶著引擎與星曆身分、時間轉換、觀測地點、座標frame、requested／executed options、warnings、
method identifiers、trace digest與reproducibility receipt。天文事實、確定性幾何、占星方法與解讀始終分層。

### It is made to leave the browser

Copy a focused section or export the chart as JSON, CSV, Markdown, TSV, or plain text. Choose compact chart
data for ordinary use or include the additional receipts and trace material needed for verification. Every
format is generated from the same normalized result rather than reconstructed from the rendered page.

你可以複製單一區段，或匯出JSON、CSV、Markdown、TSV與純文字；平常只帶星盤資料，需要驗算時再加入
receipts與trace。每一種格式都來自同一份normalized result，不從畫面上的DOM反向拼湊。

## What it calculates

- **Three coordinate systems／三套座標** — ecliptic、equatorial、horizontal／黃道、赤道與地平座標
- **Houses and angles／宮位與軸點** — ASC、MC、house cusps與planet-in-house placement
- **Lunar points／月球幾何點** — true／mean nodes、selected apsides與opt-in research points
- **Fixed stars／恆星** — 明確標示source與availability boundary
- **Events／事件** — lunar phases、prenatal syzygy、eclipses、rise／set與meridian transits
- **Methods／方法** — whole-sign relationships、geometric aspects與具名dignity profiles
- **Uncertain time／不確定時刻** — exact、approximate-hour與date-only sensitivity results
- **Calculation Dossier／計算卷宗** — 供檢查、比較與匯出的structured result

Armillary uses [Swiss Ephemeris](https://www.astro.com/swisseph/) through pyswisseph. A supported calculation
does not imply that every historical astrological method is settled or adopted; offered methods are named and
their status is kept visible in the machine-readable result.

Armillary透過pyswisseph使用[Swiss Ephemeris](https://www.astro.com/swisseph/)。產品能計算某項結果，
不代表所有歷史占星方法都已定論或被正式採用；提供的方法會具名，狀態也保留在machine-readable result中。

## A different kind of astrology software

| Typical hidden decision／常被藏起來的決定 | Armillary makes it visible／Armillary如何公開 |
|---|---|
| Which time was actually calculated? | Civil-time conversion, offset, ambiguity, and precision receipt |
| Which coordinate system was used? | Center, frame, zodiac, position type, and effective flags |
| Did every requested module run? | Separate `requested`, `executed`, `applicable`, `available`, and `source` states |
| Why do two programs disagree? | Method, source, frame, house, node, and option identities travel with the result |
| Can I reuse the data elsewhere? | Human-readable and machine-readable exports from one canonical snapshot |
| Which version produced this result? | Public source, backend image, frontend artifact, and combined release identity |

這張表不是宣稱其他工具全部做錯，而是說明Armillary選擇競爭的地方：把會影響結果的假設、版本與執行狀態，
從隱藏實作提升成使用者可以帶走的資料。

## Privacy and security are product features

The Private Alpha does not rely on a privacy-policy promise alone. Its deployed boundaries are designed to make
retention and lateral movement harder:

- **No account or chart database.** The application has no user-data persistence volume.
- **沒有帳號或星盤資料庫。** Application沒有user-data persistence volume。
- **No birth-data application logging.** Request bodies, response bodies, queries, headers, exceptions, IP
  addresses, user agents, and caller-supplied request IDs are excluded from the application event schema.
- **出生資料不進application log。** Request、response、query、headers、exception、IP、User-Agent與
  caller-supplied request ID均排除於application event schema之外。
- **Quiet reverse proxy.** NGINX access logging is disabled and client IP headers are not forwarded downstream.
- **安靜的reverse proxy。** NGINX access logging關閉，也不向application轉送client IP headers。
- **Credentials stop at the edge.** Independent invitation credentials are checked by NGINX rather than passed
  into the calculation application.
- **Credential停在edge。** 每組邀請credential由NGINX驗證，不傳入計算application。
- **Constrained runtime.** The application runs non-root with a read-only root filesystem, a bounded temporary
  filesystem, all Linux capabilities dropped, `no-new-privileges`, resource limits, and no application egress.
- **受限制的runtime。** Non-root、read-only rootfs、bounded tmpfs、drop all capabilities、
  `no-new-privileges`、resource limits與no application egress。
- **Immutable frontend.** Browser assets are installed in a digest-named, root-owned read-only directory and
  checked against a closed per-file SHA-256 manifest before the application serves them.
- **Immutable frontend。** Browser assets安裝在digest-named、root-owned、read-only目錄，供應前依封閉的
  逐檔SHA-256 manifest核對。
- **Minimal monitoring.** Synthetic availability checks use no real birth data; notifications carry only a
  closed availability event, failure class, restart status, and release revision.
- **最小化monitoring。** Synthetic probe不用真實出生資料；通知只帶封閉event、failure class、restart status
  與release revision。
- **Exact rollback identity.** The running backend image and frontend artifact form one combined release ID;
  activation advances only after health, synthetic chart, place search, identity, and privacy checks pass.
- **精確rollback identity。** Backend image與frontend artifact形成combined release ID；health、synthetic
  chart、place search、identity與privacy全部通過後才activation。

Birth inputs are sent for the requested calculation and held only as needed to produce the response. Copying or
downloading is an explicit browser action, and files already saved by the user remain under the user's control.

出生輸入只在產生本次回應所需的期間內處理。複製與下載是使用者明確發起的browser action；已經存到使用者
裝置上的檔案則由使用者自己控制。

The application, reverse proxy, host, browser, uptime monitor, and infrastructure provider are different trust
layers. Read the [privacy architecture](docs/PRIVACY_ARCHITECTURE.md),
[threat model](docs/PRIVACY_THREAT_MODEL.md), and [known limitations](docs/KNOWN_LIMITATIONS.md) for the exact
scope. The project publishes a private vulnerability-reporting route and treats a reproducible privacy or
security failure as a product defect. No software can promise that unknown vulnerabilities do not exist;
Armillary instead exposes the architecture and exact source needed to challenge what it claims.

Application、reverse proxy、host、browser、uptime monitor與infrastructure provider是不同的trust layers。
本專案提供private vulnerability reporting，並把可重現的隱私或資安失敗視為產品缺陷。任何軟體都不能保證
未知漏洞不存在；Armillary選擇公開架構與exact source，讓自己的主張可以被挑戰。

## Verify the source

Each release is a closed Corresponding Source snapshot rather than a mirror of the private engineering history.
`PUBLICATION_FILES.json` lists the published files and hashes; `SOURCE_EXPORT.json` binds the source export;
third-party source and notices remain available with the release.

每次release都是一份封閉的Corresponding Source snapshot，而不是private engineering history的鏡像。
`PUBLICATION_FILES.json`列出公開檔案與hash，`SOURCE_EXPORT.json`綁定source export，third-party source與
notices也隨release提供。

After cloning a tagged release, install the pinned test dependencies:

```bash
python -m pip install --require-hashes \
  --requirement backend/requirements-dev.lock
npm --prefix frontend ci --ignore-scripts
```

Then run the documented public verification entrypoint／接著執行公開、可重現的驗證入口：

```bash
python scripts/verify_delivery.py
```

It checks the closed publication tree, privacy-sensitive dependency boundary, Python source, published tests,
frontend tests, and source postflight. Image, host, TLS, and live-browser claims require their own exact
artifacts and are not inferred from this command.

這個命令驗closed publication tree、privacy-sensitive dependency boundary、Python source、published tests、
frontend tests與source postflight。Image、host、TLS與live browser需要自己的exact artifact，不從source test推定。

## Build an artifact

Requirements: Docker with BuildKit and a Linux/amd64 builder. The release-image owner materializes and checks
one build context; `deploy/compose.yaml` is runtime-only and deliberately has no raw-checkout `build:` path.

需求為Docker BuildKit與Linux/amd64 builder。Release-image owner只materialize並檢查一份build context；
`deploy/compose.yaml`只負責runtime，刻意不提供從raw checkout直接build的捷徑。

```bash
evidence_root="$(mktemp -d /tmp/armillary-build.XXXXXX)"
python -m scripts.verification.build_release_image \
  --image armillary:local \
  --platform linux/amd64 \
  --purpose diagnostic \
  --evidence-dir "$evidence_root/evidence" \
  --require-clean
```

Build the separately mounted, digest-named frontend from the same exact public revision:

```bash
python -m scripts.deployment.frontend_release build \
  --source-root "$PWD" \
  --output-parent /SAFE/OUTSIDE/SOURCE/frontend-releases \
  --public-source-revision "$(git rev-parse HEAD)"
```

`diagnostic` is intentionally provisional. A deployable release additionally needs publication evidence,
artifact acceptance, an immutable frontend digest, and a combined backend/frontend identity.

`diagnostic`刻意保持provisional。要成為可部署release，還必須有publication evidence、artifact acceptance、
immutable frontend digest與combined backend/frontend identity。

## Release anatomy

```text
public source revision ─┐
source archive          ├─> backend image ─┐
third-party sources     ┘                  │
                                           ├─> combined release identity
public frontend revision ─> frontend digest┘
```

Backend and frontend revisions may differ after a frontend-only update. Both remain anonymously reachable and
the live service reports the pair it is actually running. Operational credentials, private history, user data,
logs, and private review evidence are not part of Corresponding Source.

Frontend-only更新後，backend與frontend revision可以不同，但兩者仍須匿名可達，live service也會回報自己
實際執行的pair。Operational credentials、private history、user data、logs與private review evidence不屬於
Corresponding Source。

## Project status

Armillary 1.0.0 is in invited Private Alpha. The current focus is deliberately narrow:

- calculation correctness and explicit boundaries／計算正確性與明確邊界
- privacy and security enforced by architecture／以架構落實隱私與資安，不只寫政策
- understandable results without removing evidence／讓結果易懂，但不刪掉可驗算依據
- useful copy and export workflows／真正可用的複製與匯出流程
- operation without an account or chart database／不建立帳號或星盤資料庫
- real-user feedback before interpretation or prediction／加入解盤、預測或大量方法前先取得真實回饋

The project is built and maintained by Sebastian in Taichung, Taiwan. Issues and contributions are welcome when
they are reproducible and scoped to the current public release.

本專案由Sebastian在台灣台中獨立開發與維護。只要問題可以重現、scope綁定目前public release，都歡迎提出
issue或contribution。

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md). Good reports include an exact release, a minimal input that does
not contain another person's private data, the observed result, and the result you expected. Method proposals
should identify the tradition and source rather than describing a method as universally canonical.

請先閱讀[CONTRIBUTING.md](CONTRIBUTING.md)。好的報告應包含exact release、不涉及他人隱私的最小輸入、
實際結果與預期結果；方法提案則應指明傳統與來源，不把單一方法描述為普遍canonical。

For a potential vulnerability, do not open a public issue. Follow [SECURITY.md](SECURITY.md) and use GitHub's
private vulnerability reporting channel. Do not include birth data, credentials, host locators, or another
person's information.

潛在漏洞請勿開public issue。依[SECURITY.md](SECURITY.md)使用GitHub private vulnerability reporting，
且不得附上出生資料、credential、host locator或他人資訊。

## License and citation

Armillary is licensed under the [GNU Affero General Public License v3.0 only](LICENSE). Users interacting with a
modified network deployment must be offered its corresponding source. Swiss Ephemeris, pyswisseph, data files,
and build dependencies retain their own licenses and notices; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Armillary採[GNU Affero General Public License v3.0 only](LICENSE)。若修改後的版本透過網路與使用者互動，
必須向使用者提供Corresponding Source。Swiss Ephemeris、pyswisseph、資料檔與build dependencies保留各自
license與notice，詳見[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

Academic, historical, or technical writing can cite the exact Git tag or public commit so the referenced
calculation boundary remains identifiable.

學術、歷史或技術文章可以引用exact Git tag或public commit，使被引用的計算邊界仍可辨識。
