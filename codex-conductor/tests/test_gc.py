from __future__ import annotations

from pathlib import Path

import pytest

import conductor.gc as gc_module
from conductor.errors import StateError
from conductor.store import Store


def test_gc_plan_never_selects_an_actively_leased_run(tmp_path: Path) -> None:
    from conductor.gc import plan_gc

    now = [1_000_000.0]
    store = Store(tmp_path / "gc.db", clock=lambda: now[0])
    store.create_run(
        "old-active",
        provider="codex",
        generation=1,
        mode="admission",
        lease_seconds=10_000,
    )
    store.create_run(
        "old-expired",
        provider="codex",
        generation=1,
        mode="admission",
        lease_seconds=1,
    )
    now[0] += 2

    removed, kept = plan_gc(store, keep=0, older_than_days=None, now=now[0])

    assert removed == ["old-expired"]
    assert kept == ["old-active"]


def test_gc_is_plan_only_until_execute_is_explicit(tmp_path: Path) -> None:
    from conductor.gc import main
    from tests.helpers import restore_env, set_env

    home = tmp_path / "home"
    store = Store(home / "state" / "conductor.db", clock=lambda: 1_000.0)
    store.create_run(
        "expired", provider="codex", generation=1, mode="admission", lease_seconds=1
    )
    # A fresh Store uses wall time, so the synthetic lease is expired.
    old = set_env(CODEX_CONDUCTOR_HOME=str(home))
    try:
        assert main(["--keep", "0"]) == 0
        assert Store(home / "state" / "conductor.db").run_ids() == ["expired"]
        assert main(["--keep", "0", "--execute"]) == 0
        assert Store(home / "state" / "conductor.db").run_ids() == []
    finally:
        restore_env(old)


def test_gc_plan_validates_ranges_and_supports_age_cutoff(tmp_path: Path) -> None:
    now = [1000.0]
    store = Store(tmp_path / "gc.db", clock=lambda: now[0])
    with pytest.raises(ValueError, match="keep must be nonnegative"):
        gc_module.plan_gc(store, keep=-1, older_than_days=None)
    with pytest.raises(ValueError, match="older-than-days must be nonnegative"):
        gc_module.plan_gc(store, keep=None, older_than_days=-1)

    store.create_run(
        "aged", provider="codex", generation=1, mode="admission", lease_seconds=1
    )
    now[0] += 2 * 86400
    removed, kept = gc_module.plan_gc(
        store,
        keep=None,
        older_than_days=1,
        now=now[0],
    )
    assert removed == ["aged"]
    assert kept == []


def test_gc_main_handles_absent_store_and_controlled_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(gc_module, "store_path", lambda: missing)
    assert gc_module.main([]) == 0
    assert "no store" in capsys.readouterr().out

    existing = tmp_path / "store.db"
    existing.touch()
    monkeypatch.setattr(gc_module, "store_path", lambda: existing)
    monkeypatch.setattr(
        gc_module,
        "Store",
        lambda _path: (_ for _ in ()).throw(StateError("bad store")),
    )
    assert gc_module.main([]) == int(StateError.exit_code)
    assert "bad store" in capsys.readouterr().err

    monkeypatch.setattr(
        gc_module,
        "Store",
        lambda _path: (_ for _ in ()).throw(ValueError("bad value")),
    )
    assert gc_module.main([]) != 0
    assert "bad value" in capsys.readouterr().err


def test_remove_run_directory_rejects_symlink_and_removes_owned_directory(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    gc_module._remove_run_directory(state, "missing")

    target = state / "run-link"
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        target.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(StateError, match="unsafe run state path"):
        gc_module._remove_run_directory(state, "run-link")

    target.unlink()
    target.mkdir()
    (target / "state.json").write_text("{}", encoding="utf-8")
    gc_module._remove_run_directory(state, "run-link")
    assert not target.exists()
