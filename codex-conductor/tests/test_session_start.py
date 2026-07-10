from __future__ import annotations

from pathlib import Path

import pytest

from conductor.identity import read_run_context
from conductor.store import Store
from tests.helpers import DEFAULT_CONFIG, restore_env, set_env, write_config


def test_session_start_persists_one_strict_leased_context(tmp_path: Path) -> None:
    from conductor.hooks.session_start import handle

    home = tmp_path / "home"
    config = write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(config),
        CODEX_CONDUCTOR_SESSIONS_ROOT=str(tmp_path / "sessions"),
    )
    try:
        store = Store(tmp_path / "state.db")
        context = handle(
            {
                "provider": "codex",
                "thread_id": "run-session",
                "root_thread_id": "run-session",
                "model": "gpt-5.5",
            },
            provider_name="codex",
            store=store,
        )
    finally:
        restore_env(old)

    assert context.run_id == "run-session"
    assert context.mode.value == "admission"
    assert store.run_context("run-session") == context
    assert (
        read_run_context(home / "state" / "run-session" / "run_context.json") == context
    )


def test_session_start_rejects_unbounded_or_missing_identity(tmp_path: Path) -> None:
    from conductor.errors import StateError
    from conductor.hooks.session_start import handle

    config = write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(tmp_path / "home"),
        CODEX_CONDUCTOR_CONFIG=str(config),
        CODEX_CONDUCTOR_SESSIONS_ROOT=str(tmp_path / "sessions"),
    )
    try:
        with pytest.raises(StateError):
            handle(
                {"provider": "codex", "model": "gpt-5.5"},
                provider_name="codex",
                store=Store(tmp_path / "state.db"),
            )
    finally:
        restore_env(old)
