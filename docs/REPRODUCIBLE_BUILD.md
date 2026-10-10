# Build correspondence and reproducibility

The release contract is source-corresponding, not bit-for-bit reproducible across independent builders.
It binds exact public revision、digest-pinnedlinux/amd64Python base、hashed dependencies、source-built
pyswisseph、ephemeris hashes、the `/app` file list、the image SBOM、scanner evidence and image digest.
Timestamps、package repositories、toolchains and platforms may change whole-file bytes.

## Reconstruction

Both supported modes create a fresh environment and use the digest-pinned builder recorded in
`deploy/Dockerfile`：

- `online-clean`installs the exact hashed development lock fromHTTPS.
- `offline-source-only`uses only candidate sdists and lock-authorized wheel indexes；pyswisseph is still
  built from retained source. Some upstream Rust sdists are not self-contained, so an all-sdist build is
  not claimed.

**third_party/SOURCE_MANIFEST.json** binds roles、archive／wheel hashes and source-built status；generated
**docs/DEPENDENCY_LICENSES.md** must match it.

```bash
bash scripts/publication/verify_candidate_clean.sh --root . \
  --reconstruction-mode offline-source-only
bash scripts/publication/verify_candidate_clean.sh --root . \
  --reconstruction-mode online-clean
```

The verifier fixes`linux/amd64`; another builder is diagnostic only. RuntimeCompose does not build. The
build context is a `git archive` snapshot of one revision, whose `.dockerignore` whitelist
`scripts.verification.verify_docker_context` checks；a raw-checkout／Compose build is unsupported.

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
