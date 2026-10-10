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
