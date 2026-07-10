from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from conductor.errors import InstallationConflictError


def test_path_guard_allows_only_trusted_posix_system_symlinks() -> None:
    from conductor.path_guard import is_unsafe_path_redirect

    class FakeParent:
        def __init__(self, *, uid: int, mode: int) -> None:
            self._metadata = SimpleNamespace(st_uid=uid, st_mode=mode)

        def stat(self):
            return self._metadata

    class FakePath:
        def __init__(self, *, symlink: bool, parent: FakeParent) -> None:
            self._symlink = symlink
            self.parent = parent

        def is_symlink(self) -> bool:
            return self._symlink

    safe_parent = FakeParent(uid=0, mode=0o755)
    root_owned = SimpleNamespace(st_uid=0, st_file_attributes=0)
    user_owned = SimpleNamespace(st_uid=1000, st_file_attributes=0)

    assert not is_unsafe_path_redirect(
        FakePath(symlink=True, parent=safe_parent), root_owned
    )
    assert is_unsafe_path_redirect(
        FakePath(symlink=True, parent=safe_parent), user_owned
    )
    assert is_unsafe_path_redirect(
        FakePath(symlink=True, parent=FakeParent(uid=0, mode=0o777)), root_owned
    )
    assert is_unsafe_path_redirect(
        FakePath(symlink=False, parent=safe_parent),
        SimpleNamespace(st_uid=0, st_file_attributes=0x400),
    )


def test_transaction_stages_text_without_platform_newline_translation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import conductor.install as installer

    real_named_temporary_file = installer.tempfile.NamedTemporaryFile

    def stable_newline_file(*args, **kwargs):
        assert kwargs.get("newline") == ""
        return real_named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(installer.tempfile, "NamedTemporaryFile", stable_newline_file)
    installer.install(
        codex_home=tmp_path / ".codex",
        agents_path=tmp_path / "AGENTS.md",
    )


def test_install_writes_hash_manifest_and_post_tool_correlation_hook(
    tmp_path: Path,
) -> None:
    from conductor.install import install

    codex_home = tmp_path / ".codex"
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# local policy\n", encoding="utf-8")

    install(codex_home=codex_home, agents_path=agents)

    manifest = json.loads(
        (codex_home / "conductor" / "managed-manifest.json").read_text(encoding="utf-8")
    )
    hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
    wrapper = codex_home / "conductor" / "hooks" / "pre_tool_use.py"
    record = manifest["files"][str(wrapper)]
    assert manifest["schema_version"] == 1
    assert record["ownership"] == "full"
    assert record["sha256"] == hashlib.sha256(wrapper.read_bytes()).hexdigest()
    assert "PostToolUse" in hooks["hooks"]
    pre_matcher = hooks["hooks"]["PreToolUse"][0]["matcher"]
    post_matcher = hooks["hooks"]["PostToolUse"][0]["matcher"]
    assert "followup_task" in pre_matcher
    assert "followup_task" in post_matcher
    assert "send_message" in post_matcher


def test_install_rejects_symlink_targets_without_touching_the_victim(
    tmp_path: Path,
) -> None:
    from conductor.install import install

    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    victim = tmp_path / "victim.json"
    victim.write_text('{"foreign": true}\n', encoding="utf-8")
    try:
        os.symlink(victim, codex_home / "hooks.json")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    with pytest.raises(InstallationConflictError, match="symbolic link"):
        install(codex_home=codex_home, agents_path=tmp_path / "AGENTS.md")

    assert victim.read_text(encoding="utf-8") == '{"foreign": true}\n'


def test_transaction_rolls_back_every_file_after_mid_commit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import conductor.install as installer

    codex_home = tmp_path / ".codex"
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# original\n", encoding="utf-8")
    real_replace = installer.os.replace
    calls = 0

    def fail_once(source, destination):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("injected replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(installer.os, "replace", fail_once)

    with pytest.raises(OSError, match="injected"):
        installer.install(codex_home=codex_home, agents_path=agents)

    assert agents.read_text(encoding="utf-8") == "# original\n"
    assert not (codex_home / "hooks.json").exists()
    assert not (codex_home / "conductor" / "managed-manifest.json").exists()


def test_staging_cleanup_failure_never_masks_the_commit_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import conductor.install as installer

    codex_home = tmp_path / ".codex"
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# original\n", encoding="utf-8")
    real_replace = installer.os.replace
    real_unlink = installer.Path.unlink
    replace_calls = 0

    def fail_commit(source, destination):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 3:
            raise OSError("primary commit failure")
        return real_replace(source, destination)

    def fail_stage_cleanup(path, *args, **kwargs):
        if ".conductor-stage-" in path.name:
            raise OSError("secondary cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(installer.os, "replace", fail_commit)
    monkeypatch.setattr(installer.Path, "unlink", fail_stage_cleanup)

    with pytest.raises(OSError, match="primary commit failure"):
        installer.install(codex_home=codex_home, agents_path=agents)

    assert agents.read_text(encoding="utf-8") == "# original\n"


def test_modified_managed_file_requires_explicit_repair(tmp_path: Path) -> None:
    from conductor.install import install

    codex_home = tmp_path / ".codex"
    agents = tmp_path / "AGENTS.md"
    install(codex_home=codex_home, agents_path=agents)
    wrapper = codex_home / "conductor" / "hooks" / "pre_tool_use.py"
    wrapper.write_text("# local edit\n", encoding="utf-8")

    with pytest.raises(InstallationConflictError, match="managed file was modified"):
        install(codex_home=codex_home, agents_path=agents)

    install(codex_home=codex_home, agents_path=agents, repair=True)
    assert "from conductor.hooks.pre_tool_use import main" in wrapper.read_text(
        encoding="utf-8"
    )


def test_uninstall_preserves_modified_files_and_foreign_content(
    tmp_path: Path,
) -> None:
    from conductor.install import install, uninstall

    codex_home = tmp_path / ".codex"
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# foreign policy\n", encoding="utf-8")
    install(codex_home=codex_home, agents_path=agents)
    wrapper = codex_home / "conductor" / "hooks" / "pre_tool_use.py"
    wrapper.write_text("# preserve me\n", encoding="utf-8")

    uninstall(codex_home=codex_home, agents_path=agents)

    assert wrapper.read_text(encoding="utf-8") == "# preserve me\n"
    assert not (codex_home / "hooks.json").exists()
    assert not (codex_home / "conductor" / "hooks" / "lifecycle.py").exists()
    assert not (codex_home / "conductor" / "managed-manifest.json").exists()
    assert agents.read_text(encoding="utf-8") == "# foreign policy\n"


def test_dry_run_has_zero_filesystem_side_effects(tmp_path: Path) -> None:
    from conductor.install import install

    codex_home = tmp_path / ".codex"
    install(
        codex_home=codex_home,
        agents_path=tmp_path / "AGENTS.md",
        dry_run=True,
    )

    assert not codex_home.exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_uninstall_rejects_out_of_scope_manifest_paths(tmp_path: Path) -> None:
    from conductor.install import install, uninstall

    codex_home = tmp_path / ".codex"
    agents = tmp_path / "AGENTS.md"
    install(codex_home=codex_home, agents_path=agents)
    victim = tmp_path / "victim.txt"
    victim.write_text("keep\n", encoding="utf-8")
    manifest_path = codex_home / "conductor" / "managed-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][str(victim)] = {
        "ownership": "full",
        "sha256": hashlib.sha256(victim.read_bytes()).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(InstallationConflictError, match="out-of-scope"):
        uninstall(codex_home=codex_home, agents_path=agents)
    assert victim.read_text(encoding="utf-8") == "keep\n"
