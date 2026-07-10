from __future__ import annotations

from pathlib import Path

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
