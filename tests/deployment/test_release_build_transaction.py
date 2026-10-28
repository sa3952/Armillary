"""The image build binds one exact revision to the image it produces.
Published with the source, so it uses no shared test fixture."""

from __future__ import annotations

import json

import pytest

from scripts.verification import build_release_image as module


def test_a_release_build_requires_a_publication_receipt_and_a_clean_checkout(tmp_path):
    assert module.publication_status_for_build(
        purpose="diagnostic", publication_receipt=None, revision="a" * 40) == "provisional_unpublished"
    with pytest.raises(module.BuildTransactionFailure, match="publication receipt"):
        module.publication_status_for_build(purpose="release-candidate", publication_receipt=None,
                                            revision="a" * 40)
    provisional = tmp_path / "SOURCE_EXPORT.json"
    provisional.write_text(json.dumps({"schema_version": 1, "private_source_revision": "a" * 40,
                                       "status": "public_revision_intentionally_out_of_band"}))
    with pytest.raises(module.BuildTransactionFailure, match="key set"):
        module.publication_status_for_build(purpose="release-candidate", publication_receipt=provisional,
                                            revision="a" * 40)
    for purpose, requested, required in (("diagnostic", False, False), ("diagnostic", True, True),
                                         ("release-candidate", False, True)):
        assert module.clean_checkout_required(purpose=purpose, requested=requested) is required


def test_platform_contract_accepts_only_the_production_vocabulary():
    assert module.platform_contract("linux/amd64") == ("linux", "amd64")
    assert module.platform_contract("linux/arm64/v8") == ("linux", "arm64")
    assert module.platform_args(None) == []
    for platform in ("linux/riscv64", "darwin/arm64", "amd64"):
        with pytest.raises(ValueError):
            module.platform_contract(platform)


def _fake_build(monkeypatch, module, *, revision: str, labels: dict, architecture="amd64"):
    commands = []

    def run(command, **kwargs):
        commands.append((command, kwargs.get("cwd")))
        stdout = ""
        if command[:2] == ["git", "rev-parse"]:
            stdout = revision if command[2] == "HEAD" else "d" * 40
        elif command[:3] == ["docker", "image", "inspect"]:
            stdout = json.dumps([{
                "Id": "sha256:" + "b" * 64, "Os": "linux", "Architecture": architecture,
                "Config": {"Labels": labels},
            }])
        return type("Completed", (), {"stdout": stdout, "stderr": "", "returncode": 0})()

    monkeypatch.setattr(module, "_run", run)
    monkeypatch.setattr(
        module, "materialize_git_snapshot",
        lambda _root, _revision, destination: destination.mkdir(parents=True) or destination,
    )
    monkeypatch.setattr(module, "verify_context", lambda _root: {})
    monkeypatch.setattr(module, "prepare_wheelhouse", lambda _context, _platform: {"a.whl": "e" * 64})
    return commands


def test_a_build_is_bound_to_its_revision_snapshot_and_image(tmp_path, monkeypatch):
    revision = "a" * 40
    commands = _fake_build(monkeypatch, module, revision=revision, labels={
        "org.opencontainers.image.revision": revision,
        "org.projectarmillary.publication.status": "provisional_unpublished",
    })
    receipt = module.build_image(
        source_root=tmp_path / "source", image="fixture:latest", platform="linux/amd64",
        purpose="diagnostic", publication_receipt=None, evidence_dir=tmp_path / "evidence",
        require_clean=False,
    )
    assert receipt["source_revision"] == revision
    assert receipt["context_git_tree"] == "d" * 40
    assert receipt["image_id"] == "sha256:" + "b" * 64
    assert receipt["builder_isolation"] == "diagnostic_default_builder"
    [(build, context)] = [(c, cwd) for c, cwd in commands if c[:3] == ["docker", "buildx", "build"]]
    # The build runs in the Git snapshot, never in the working tree.
    assert context.name == "context" and context != tmp_path / "source"
    assert f"VCS_REF={revision}" in build
    saved = json.loads((tmp_path / "evidence" / "build-transaction.json").read_text(encoding="utf-8"))
    assert saved == receipt
    # Beside it, the unsigned build provenance of exactly this image and revision.
    provenance = json.loads((tmp_path / "evidence" / "provenance.intoto.json").read_text(encoding="utf-8"))
    assert provenance["subject"] == [{"name": "fixture:latest", "digest": {"sha256": "b" * 64}}]
    source = provenance["predicate"]["buildDefinition"]["externalParameters"]["source"]
    assert source["digest"] == {"gitCommit": revision}


@pytest.mark.parametrize(
    ("labels", "architecture"),
    [
        ({"org.opencontainers.image.revision": "c" * 40,
          "org.projectarmillary.publication.status": "provisional_unpublished"}, "amd64"),
        ({"org.opencontainers.image.revision": "a" * 40,
          "org.projectarmillary.publication.status": "published_anonymously_reachable"}, "amd64"),
        ({"org.opencontainers.image.revision": "a" * 40,
          "org.projectarmillary.publication.status": "provisional_unpublished"}, "arm64"),
    ],
)
def test_an_image_that_is_not_this_builds_is_refused(tmp_path, monkeypatch, labels, architecture):
    _fake_build(monkeypatch, module, revision="a" * 40, labels=labels, architecture=architecture)
    with pytest.raises(module.BuildTransactionFailure, match="not this build's"):
        module.build_image(
            source_root=tmp_path / "source", image="fixture:latest", platform="linux/amd64",
            purpose="diagnostic", publication_receipt=None, evidence_dir=tmp_path / "evidence",
            require_clean=False,
        )
    assert not (tmp_path / "evidence").exists()


def test_a_release_candidate_uses_an_ephemeral_pinned_builder_without_cache(tmp_path, monkeypatch):
    revision = "a" * 40
    commands = _fake_build(monkeypatch, module, revision=revision, labels={
        "org.opencontainers.image.revision": revision,
        "org.projectarmillary.publication.status": "published_anonymously_reachable",
    })
    monkeypatch.setattr(
        module, "publication_status_for_build",
        lambda **_kwargs: "published_anonymously_reachable",
    )
    receipt = module.build_image(
        source_root=tmp_path / "source", image="fixture:latest", platform="linux/amd64",
        purpose="release-candidate", publication_receipt=tmp_path / "receipt.json",
        evidence_dir=tmp_path / "evidence",
    )
    names = [command for command, _ in commands]
    create = next(c for c in names if c[:3] == ["docker", "buildx", "create"])
    build = next(c for c in names if c[:3] == ["docker", "buildx", "build"])
    assert f"image={module.BUILDKIT_IMAGE}" in create
    # An isolated builder container, not the daemon's shared default builder.
    assert create[create.index("--driver") + 1] == "docker-container"
    assert "--no-cache" in build and build[build.index("--builder") + 1] == create[4]
    assert any(c[:3] == ["docker", "buildx", "rm"] for c in names)
    assert receipt["builder_isolation"] == "ephemeral_docker_container_builder_no_cache"


# --- the offline wheelhouse -----------------------------------------------------------

def _sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


WHEELS = {
    "alpha-1.0-py3-none-any.whl": b"alpha wheel",
    "setuptools-84.0.0-py3-none-any.whl": b"setuptools wheel",
    "wheel-0.48.0-py3-none-any.whl": b"wheel wheel",
}


def _wheelhouse_context(tmp_path):
    """A build context with the real Dockerfile and two small locks."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    context = tmp_path / "context"
    (context / "deploy").mkdir(parents=True)
    (context / "deploy/Dockerfile").write_text((root / "deploy/Dockerfile").read_text(encoding="utf-8"),
                                               encoding="utf-8")
    (context / "deploy/requirements.lock").write_text(
        f"alpha==1.0 \\\n    --hash=sha256:{_sha256(WHEELS['alpha-1.0-py3-none-any.whl'])}\n"
        f"pyswisseph==2.10.3.2 \\\n    --hash=sha256:{'5' * 64}\n", encoding="utf-8")
    (context / "deploy/build-requirements.lock").write_text(
        f"other==1.0 \\\n    --hash=sha256:{'6' * 64}\n"
        f"wheel==0.48.0 \\\n    --hash=sha256:{_sha256(WHEELS['wheel-0.48.0-py3-none-any.whl'])}\n"
        f"setuptools==84.0.0 \\\n    --hash=sha256:{_sha256(WHEELS['setuptools-84.0.0-py3-none-any.whl'])}\n",
        encoding="utf-8")
    return context


def _fake_download(monkeypatch, wheels: dict):
    downloads = []

    def run(command, **_kwargs):
        downloads.append(command)
        destination = command[command.index("--dest") + 1]
        from pathlib import Path

        for name, data in wheels.items():
            (Path(destination) / name).write_bytes(data)
        return type("Completed", (), {"stdout": "", "stderr": "", "returncode": 0})()

    monkeypatch.setattr(module, "_run", run)
    return downloads


def test_the_wheelhouse_holds_one_hash_checked_wheel_per_locked_binary_and_the_build_backend(
        tmp_path, monkeypatch):
    """pip in the image installs only from this directory (`--no-index`); it is
    downloaded on the host for the image's platform, Python and glibc, never
    pyswisseph (built from its vendored sdist) and nothing else of the build lock."""
    context = _wheelhouse_context(tmp_path)
    downloads = _fake_download(monkeypatch, WHEELS)
    wheelhouse = module.prepare_wheelhouse(context, "linux/amd64")
    assert wheelhouse == {name: _sha256(data) for name, data in WHEELS.items()}
    [download] = downloads
    assert download[download.index("--dest") + 1] == str(context / module.WHEELHOUSE)
    for flag in ("--require-hashes", "--no-deps", "--only-binary=:all:"):
        assert flag in download
    platforms = [download[index + 1] for index, word in enumerate(download) if word == "--platform"]
    assert platforms == [f"manylinux_2_{minor}_x86_64" for minor in range(41, 4, -1)]
    assert download[download.index("--python-version") + 1] == "3.14"
    assert download[download.index("--abi") + 1] == "cp314"
    requested = (context / module.WHEELHOUSE).parent
    assert not any(path.suffix == ".lock" for path in requested.iterdir())


def test_a_wheelhouse_wheel_outside_the_lock_or_a_missing_one_fails_the_build(tmp_path, monkeypatch):
    context = _wheelhouse_context(tmp_path)
    _fake_download(monkeypatch, {**WHEELS, "alpha-1.0-py3-none-any.whl": b"substituted"})
    import pytest as _pytest

    with _pytest.raises(module.BuildTransactionFailure, match="not authorized"):
        module.prepare_wheelhouse(context, "linux/amd64")
    context = _wheelhouse_context(tmp_path / "second")
    _fake_download(monkeypatch, {name: data for name, data in WHEELS.items() if not name.startswith("wheel-")})
    with _pytest.raises(module.BuildTransactionFailure, match="one wheel per"):
        module.prepare_wheelhouse(context, "linux/amd64")


def test_the_build_prepares_the_wheelhouse_in_the_snapshot_before_the_context_check(tmp_path, monkeypatch):
    revision = "a" * 40
    commands = _fake_build(monkeypatch, module, revision=revision, labels={
        "org.opencontainers.image.revision": revision,
        "org.projectarmillary.publication.status": "provisional_unpublished",
    })
    order = []
    monkeypatch.setattr(module, "prepare_wheelhouse",
                        lambda context, platform: order.append(("wheelhouse", context.name, platform))
                        or {"a.whl": "e" * 64})
    monkeypatch.setattr(module, "verify_context", lambda root: order.append(("context", root.name)) or {})
    receipt = module.build_image(
        source_root=tmp_path / "source", image="fixture:latest", platform="linux/amd64",
        purpose="diagnostic", publication_receipt=None, evidence_dir=tmp_path / "evidence",
        require_clean=False,
    )
    assert order == [("wheelhouse", "context", "linux/amd64"), ("context", "context")]
    assert receipt["wheelhouse_sha256"] == {"a.whl": "e" * 64}
    assert any(command[:3] == ["docker", "buildx", "build"] for command, _ in commands)


def test_every_pip_in_the_image_build_is_offline():
    """The builder's pip reads the wheelhouse only (`--no-index`), and the RUN
    that calls it has no network at all, so a missing wheel fails the build
    rather than reaching PyPI."""
    from pathlib import Path
    import shlex

    from scripts.verification.verify_docker_context import dockerfile_logical_lines

    root = Path(__file__).resolve().parents[2]
    lines = dockerfile_logical_lines((root / "deploy/Dockerfile").read_text(encoding="utf-8"))
    fetching = 0
    for line in (line for line in lines if line.startswith("RUN ")):
        words = shlex.split(line)
        flags = []
        for word in words[1:]:
            if not word.startswith("--"):
                break
            flags.append(word)
        for index, word in enumerate(words[:-1]):
            if word == "pip" and words[index + 1] in ("install", "wheel", "download"):
                fetching += 1
                command = words[index:words.index("&&", index) if "&&" in words[index:] else None]
                assert "--no-index" in command, command
                assert "--network=none" in flags, line[:120]
    assert fetching >= 3
    assert ("COPY", module.WHEELHOUSE) in {(line.split()[0], line.split()[1].rstrip("/")) for line in lines
                                           if line.startswith("COPY ")}
