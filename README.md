<p align="center">
  <img src="frontend/zh-TW/favicon.svg" width="92" alt="Armillary logo">
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

## Why Armillary?

### Your birth data is not the product

Birth time and precise location can be deeply identifying. Armillary's current deployment is deliberately
small and forgetful: credentials terminate at the reverse proxy, the application receives no credential to
store, request and response bodies are excluded from application logs, NGINX access logging is disabled, and
client IP headers are not forwarded to the application. Availability notifications use a closed event schema
that contains no chart input, response, credential, IP address, header, or exception text.

### It respects what you actually know

Birth time is not always exact. Armillary distinguishes an exact minute, an approximate hour, and a date-only
input instead of silently inventing precision. Ambiguous or nonexistent civil times are surfaced as choices
or actionable errors.

### It shows its work

A result can carry the engine and ephemeris identity, time conversion, observer location, coordinate frame,
requested and executed options, warnings, method identifiers, trace digest, and reproducibility receipt.
Astronomical facts, deterministic geometry, astrological methods, and interpretation remain separate layers.

### It is made to leave the browser

Copy a focused section or export the chart as JSON, CSV, Markdown, TSV, or plain text. Choose compact chart
data for ordinary use or include the additional receipts and trace material needed for verification. Every
format is generated from the same normalized result rather than reconstructed from the rendered page.

## What it calculates

- Planetary positions across ecliptic, equatorial, and horizontal coordinates
- Ascendant, Midheaven, house cusps, and planet-in-house placement
- True and mean lunar nodes, selected lunar apsides, and opt-in research points
- Fixed stars with explicit source and availability boundaries
- Lunar phases, prenatal syzygy, eclipses, rise/set, and meridian transits
- Whole-sign relationships, geometric aspects, and named dignity profiles
- Exact, approximate-hour, and date-only sensitivity results
- A structured Calculation Dossier for inspection, comparison, and export

Armillary uses [Swiss Ephemeris](https://www.astro.com/swisseph/) through pyswisseph. A supported calculation
does not imply that every historical astrological method is settled or adopted; offered methods are named and
their status is kept visible in the machine-readable result.

## A different kind of astrology software

| Typical hidden decision | Armillary makes it visible |
|---|---|
| Which time was actually calculated? | Civil-time conversion, offset, ambiguity, and precision receipt |
| Which coordinate system was used? | Center, frame, zodiac, position type, and effective flags |
| Did every requested module run? | Separate `requested`, `executed`, `applicable`, `available`, and `source` states |
| Why do two programs disagree? | Method, source, frame, house, node, and option identities travel with the result |
| Can I reuse the data elsewhere? | Human-readable and machine-readable exports from one canonical snapshot |
| Which version produced this result? | Public source, backend image, frontend artifact, and combined release identity |

## Privacy and security are product features

The Private Alpha does not rely on a privacy-policy promise alone. Its deployed boundaries are designed to make
retention and lateral movement harder:

- **No account or chart database.** The application has no user-data persistence volume.
- **No birth-data application logging.** Request bodies, response bodies, queries, headers, exceptions, IP
  addresses, user agents, and caller-supplied request IDs are excluded from the application event schema.
- **Quiet reverse proxy.** NGINX access logging is disabled and client IP headers are not forwarded downstream.
- **Credentials stop at the edge.** Independent invitation credentials are checked by NGINX rather than passed
  into the calculation application.
- **Constrained runtime.** The application runs non-root with a read-only root filesystem, a bounded temporary
  filesystem, all Linux capabilities dropped, `no-new-privileges`, resource limits, and no application egress.
- **Immutable frontend.** Browser assets are installed in a digest-named, root-owned read-only directory and
  checked against a closed per-file SHA-256 manifest before the application serves them.
- **Minimal monitoring.** Synthetic availability checks use no real birth data; notifications carry only a
  closed availability event, failure class, restart status, and release revision.
- **Exact rollback identity.** The running backend image and frontend artifact form one combined release ID;
  activation advances only after health, synthetic chart, place search, identity, and privacy checks pass.

Birth inputs are sent for the requested calculation and held only as needed to produce the response. Copying or
downloading is an explicit browser action, and files already saved by the user remain under the user's control.

The application, reverse proxy, host, browser, uptime monitor, and infrastructure provider are different trust
layers. Read the [privacy architecture](docs/PRIVACY_ARCHITECTURE.md),
[threat model](docs/PRIVACY_THREAT_MODEL.md), and [known limitations](docs/KNOWN_LIMITATIONS.md) for the exact
scope. The project publishes a private vulnerability-reporting route and treats a reproducible privacy or
security failure as a product defect. No software can promise that unknown vulnerabilities do not exist;
Armillary instead exposes the architecture and exact source needed to challenge what it claims.

## Verify the source

Each release is a closed Corresponding Source snapshot rather than a mirror of the private engineering history.
`PUBLICATION_FILES.json` lists the published files and hashes; `SOURCE_EXPORT.json` binds the source export;
third-party source and notices remain available with the release.

After cloning a tagged release, install the pinned test dependencies:

```bash
python -m pip install --require-hashes \
  --requirement backend/requirements-dev.lock
npm --prefix frontend ci --ignore-scripts
```

Then run the documented public verification entrypoint:

```bash
python scripts/verify_delivery.py
```

It checks the closed publication tree, privacy-sensitive dependency boundary, Python source, published tests,
frontend tests, and source postflight. Image, host, TLS, and live-browser claims require their own exact
artifacts and are not inferred from this command.

## Build an artifact

Requirements: Docker with BuildKit and a Linux/amd64 builder. The release-image owner materializes and checks
one build context; `deploy/compose.yaml` is runtime-only and deliberately has no raw-checkout `build:` path.

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

## Project status

Armillary 1.0.0 is in invited Private Alpha. The current focus is deliberately narrow:

- calculation correctness and explicit boundaries
- privacy and security enforced by architecture, not only by policy text
- understandable results without removing the underlying evidence
- useful copy and export workflows
- privacy-preserving operation without an account or chart database
- real-user feedback before adding interpretation, prediction, or a large method catalogue

The project is built and maintained by Sebastian in Taichung, Taiwan. Issues and contributions are welcome when
they are reproducible and scoped to the current public release.

## Contributing

Start with [CONTRIBUTING.md](CONTRIBUTING.md). Good reports include an exact release, a minimal input that does
not contain another person's private data, the observed result, and the result you expected. Method proposals
should identify the tradition and source rather than describing a method as universally canonical.

For a potential vulnerability, do not open a public issue. Follow [SECURITY.md](SECURITY.md) and use GitHub's
private vulnerability reporting channel. Do not include birth data, credentials, host locators, or another
person's information.

## License and citation

Armillary is licensed under the [GNU Affero General Public License v3.0 only](LICENSE). Users interacting with a
modified network deployment must be offered its corresponding source. Swiss Ephemeris, pyswisseph, data files,
and build dependencies retain their own licenses and notices; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Academic, historical, or technical writing can cite the exact Git tag or public commit so the referenced
calculation boundary remains identifiable.
