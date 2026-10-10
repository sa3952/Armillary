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
