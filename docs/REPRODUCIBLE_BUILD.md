# Build correspondence and reproducibility

The release contract is source-corresponding, not bit-for-bit reproducible across independent builders.
It binds exact public revision、digest-pinnedlinux/amd64Python base、hashed dependencies、source-built
pyswisseph、ephemeris hashes、the `/app` file list、the image SBOM、scanner evidence and image digest.
Timestamps、package repositories、toolchains and platforms may change whole-file bytes.

## Reconstruction

The tree carries the AGPL pyswisseph source（`third_party/pyswisseph/`, recorded in
**third_party/SOURCE_MANIFEST.json**）and no other dependency archive. Every other input is named by hash: the
requirement locks（`deploy/requirements.lock`、`deploy/build-requirements.lock`、`backend/requirements-dev.lock`）pin
each artifact pip may install, and `publication/third_party_source_lock.json` names each dependency's single source
distribution on PyPI.

This tree alone does not rebuild offline: the dependencies are fetched from PyPI and checked against
those hashes, so a rebuild needs PyPI (or a mirror serving the same bytes) to still carry them.

The supported reconstruction creates a fresh environment in the digest-pinned builder recorded in `deploy/Dockerfile`
and installs the development lock from PyPI over HTTPS with `--require-hashes`; pyswisseph is built from its source.
Some upstream Rust sdists are not self-contained, so an all-sdist build is not claimed.

```bash
bash scripts/publication/verify_candidate_clean.sh --root . \
  --reconstruction-mode online-clean
```

To obtain every dependency's source distribution and check it against the locked hashes（PyPI's declared hash and
the downloaded bytes must both equal the source lock's）:

```bash
python -m scripts.publication.prepare_third_party_sources \
  --runtime-lock deploy/requirements.lock --build-lock deploy/build-requirements.lock \
  --development-lock backend/requirements-dev.lock \
  --source-lock publication/third_party_source_lock.json \
  --destination /SAFE/OUTSIDE/SOURCE/dependency-sources
```

The verifier fixes`linux/amd64`; another builder is diagnostic only. RuntimeCompose does not build. The
build context is a `git archive` snapshot of one revision, whose `.dockerignore` whitelist
`scripts.verification.verify_docker_context` checks；a raw-checkout／Compose build is unsupported.
`build_release_image` adds a directory named `wheelhouse` to that snapshot（it is not in the tree）: one wheel per locked runtime dependency and the
build lock's `setuptools`／`wheel`, downloaded on the host for the image's platform and checked against the
lock hashes. The builder installs only from it（`pip --no-index`）in a `RUN --network=none` step, so the image
build itself reaches no package index; the build receipt lists every wheel's SHA-256（`wheelhouse_sha256`）.

## Build an artifact

Requirements: Docker with BuildKit and a Linux/amd64 builder. The release-image owner builds from a `git archive`
snapshot of one revision after checking its `.dockerignore` whitelist; `deploy/compose.yaml` is runtime-only and deliberately has no raw-checkout `build:` path.

需求為Docker BuildKit與Linux/amd64 builder。Release-image owner只從單一revision的`git archive`快照建置，並先檢查`.dockerignore`白名單；
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
locked dependencies     ┘                  │
                                           ├─> combined release identity
public frontend revision ─> frontend digest┘
```

Backend and frontend revisions may differ after a frontend-only update. Both remain anonymously reachable and
the live service reports the pair it is actually running. Operational credentials, private history, user data,
logs, and private review evidence are not part of Corresponding Source.

Frontend-only更新後，backend與frontend revision可以不同，但兩者仍須匿名可達，live service也會回報自己
實際執行的pair。Operational credentials、private history、user data、logs與private review evidence不屬於
Corresponding Source。

## Verify a release tag

Each release is an annotated tag signed with the release signer's SSH key. The public keys allowed to sign
releases are in `deploy/release-allowed-signers`, the same list the release gate checks every tag against.
With Git 2.34 or later, in a clone of this repository:

```sh
git fetch --tags
git -c gpg.ssh.allowedSignersFile=deploy/release-allowed-signers tag -v VER
```

`VER` is the release name, for example `public-alpha-2026-10-28`. A good tag prints `Good "git" signature`
for a key in that file. A lightweight tag, an unsigned tag, or one signed by any other key is not a release.
The tag message names the public source revision, the frontend release digest and the backend image; compare
the digest with the release record releases/VER/frontend-release.json in the public repository, and the image
with what `/api/version` reports.

`tag -v` also accepts an OpenPGP signature if one is present. To check only the SSH signature, verify the
signature block directly:

```sh
git cat-file tag VER | sed '/^-----BEGIN SSH SIGNATURE-----$/,$d' > tag.payload
git cat-file tag VER | sed -n '/^-----BEGIN SSH SIGNATURE-----$/,$p' > tag.sig
ssh-keygen -Y verify -f deploy/release-allowed-signers -I git -n git -s tag.sig < tag.payload
```

The allowed-signers file comes from the same clone you are verifying, so it only proves that the tag matches
the key this repository names; compare the key's fingerprint with one obtained elsewhere before trusting it.

Some older tags are not signed releases in this sense: the tags made before the signing key
existed are lightweight, and `public-alpha-2026-10-21` was published as an unsigned tag by a one-time
decision because no signing key was set up yet. Those tags identify a revision only; check them against the
release record and `/api/version`, not against a signature.

If a signing key is ever retired, it leaves `deploy/release-allowed-signers` and moves to a separate
retired-signers file published beside it, with a historical-tags list naming, by tag object id
(`git rev-parse refs/tags/VER`), the past tags it still vouches for. Verify such a tag against the retired list
only when its object id is in that file; a retired key's signature on any other tag, whatever date it carries,
is not a release.

金鑰若退役，會從 `deploy/release-allowed-signers` 移到同目錄另行公開的退役名單；
並以一份舊 tag 清單，用 tag 物件 ID 列出它仍擔保的舊 tag。只有物件 ID 在清單裡的 tag 才用退役名單驗；
退役金鑰簽的其他 tag，不論寫的日期是哪天，都不是 release。

每個 release 都是用發布者 SSH 金鑰簽過的 annotated tag。允許簽發布的公鑰在
`deploy/release-allowed-signers`，與發布閘門驗每個 tag 的名單相同。用上面兩行指令驗；看到 `Good "git" signature`
才算數，lightweight、未簽或其他金鑰簽的 tag 都不是 release。
`tag -v` 也接受 OpenPGP 簽章；只驗 SSH 簽章請用上面的 `ssh-keygen -Y verify`。簽者名單來自同一份 clone，
請另找來源核對金鑰指紋。較舊的 tag 有些不是簽章 release：設定金鑰前的 tag 是 lightweight，
`public-alpha-2026-10-21` 依一次性決定以未簽 tag 發布；這些 tag 只標出 revision，請對照發布紀錄與 `/api/version`。

## What this tree does not carry, and why

Two kinds of thing are deliberately absent, so that their absence reads as a decision rather than an
omission.

**Operator state.** The edge (NGINX) configuration and its site template are published here. The tool
that fills a domain into that template is not, and neither is the hardening of the host machine (TLS
preparation, credential tooling, and settings for generally available programs such as sshd, ufw,
sysctl, journald and certbot, used unmodified). What those hold is one operator's machine and
identity, not knowledge needed to build, run or modify this work. Bring your own.

**Our own quality apparatus.** The tests published here are the ones that verify a claim this
project makes in public: privacy logging, the runtime contract, resource bounds, the release
transaction, the hosted profile, and the browser-side privacy lifecycle and export serializers.
Ordinary functional and coverage tests, their fixtures, and lint configuration are not published.
They are not needed to generate, install, run or modify the work, and publishing them would say
nothing a reader could check.
The same holds for the private release tooling that only reads our own state: the dependency-age check
compares a change against our private lock history, and the gate-receipt importer copies test receipts
between our own machines. Neither can be rerun from this tree, and neither is needed to build or run it;
the locks and the build steps above are what a reader can check.
