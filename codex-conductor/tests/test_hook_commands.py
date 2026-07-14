from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

from tests.helpers import (
    DEFAULT_CONFIG,
    restore_env,
    set_env,
    write_config,
    write_models_cache,
)


def _invoke(main, payload: dict, args: list[str] | None = None) -> tuple[int, dict]:
    stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(args or [])
    finally:
        sys.stdin = stdin
    return result, json.loads(output.getvalue())


def _environment(tmp_path: Path):
    home = tmp_path / "home"
    return home, set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(
            write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
        ),
        CODEX_MODELS_CACHE=str(
            write_models_cache(
                tmp_path / "models.json",
                ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex-spark"],
            )
        ),
        CODEX_CONDUCTOR_SESSIONS_ROOT=str(tmp_path / "sessions"),
    )


def test_codex_hook_config_uses_only_supported_top_level_fields(tmp_path: Path) -> None:
    from conductor import doctor
    from conductor.install import _render_hooks_json

    hooks_dir = tmp_path / "hooks"
    path = tmp_path / "hooks.json"
    path.write_text(_render_hooks_json(hooks_dir), encoding="utf-8")
    rendered = json.loads(path.read_text(encoding="utf-8"))
    assert set(rendered) == {"description", "hooks"}
    assert rendered["description"] == "Managed by codex-conductor"

    rendered["_managed_by"] = "codex-conductor"
    path.write_text(json.dumps(rendered), encoding="utf-8")
    results: list[tuple[str, str, str]] = []
    doctor._check_json_hooks(
        lambda *result: results.append(result),
        path,
        hooks_dir,
        expected=("SessionStart",),
        settings=False,
    )
    assert results == [
        ("hooks_json", "fail", "unsupported top-level fields: _managed_by")
    ]


def test_codex_provider_accepts_current_documented_hook_identifiers(
    tmp_path: Path,
) -> None:
    from conductor.config import load_config
    from conductor.providers.codex import PROVIDER

    config = load_config(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))
    payload = {"session_id": "codex-session", "model": "gpt-5.5"}

    assert PROVIDER.session_run_id(payload) == "codex-session"
    caller = PROVIDER.resolve_caller(payload, config)
    assert caller.run_id == "codex-session"
    assert caller.thread_id == "codex-session"
    link = PROVIDER.correlation_link(
        {
            "session_id": "codex-session",
            "tool_use_id": "tool-use-1",
            "tool_response": {"agent_id": "child-1"},
        }
    )
    assert link is not None
    assert (link.run_id, link.source_correlation, link.child_alias) == (
        "codex-session",
        "tool-use-1",
        "child-1",
    )


def test_codex_provider_emits_current_pre_tool_use_decisions() -> None:
    from conductor.providers.codex import PROVIDER

    assert PROVIDER.emit_decision("approve", "allowed") == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
    assert PROVIDER.emit_decision("block", "blocked safely") == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": "blocked safely",
        }
    }


def test_session_start_accepts_current_documented_codex_payload(
    tmp_path: Path,
) -> None:
    from conductor.hooks.session_start import main as session_main
    from conductor.store import Store

    home, old = _environment(tmp_path)
    try:
        rc, response = _invoke(
            session_main,
            {
                "session_id": "documented-session",
                "cwd": str(tmp_path),
                "hook_event_name": "SessionStart",
                "source": "startup",
                "model": "gpt-5.5",
                "permission_mode": "default",
            },
        )
        assert rc == 0 and response == {}
        assert (
            Store(home / "state" / "conductor.db")
            .run_context("documented-session")
            .thread_id
            == "documented-session"
        )
    finally:
        restore_env(old)


def test_hook_entrypoints_initialize_deny_and_record_without_raising(
    tmp_path: Path,
) -> None:
    from conductor.hooks.lifecycle import main as lifecycle_main
    from conductor.hooks.pre_tool_use import main as pre_tool_main
    from conductor.hooks.session_start import main as session_main
    from conductor.store import Store

    home, old = _environment(tmp_path)
    try:
        session = {
            "thread_id": "hook-run",
            "root_thread_id": "hook-run",
            "model": "gpt-5.5",
        }
        rc, response = _invoke(session_main, session)
        assert rc == 0 and response == {}

        other_rc, other = _invoke(
            pre_tool_main,
            {"tool_name": "shell", "tool_input": {"command": "true"}},
        )
        assert other_rc == 0
        assert other == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

        envelope = (
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"risk-task",'
            '"task_class":"high_risk","risk_triggers":[],"owned_paths":["src/risk.py"],'
            '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
        )
        governed_rc, governed = _invoke(
            pre_tool_main,
            {
                **session,
                "tool_call_id": "hook-call",
                "tool_name": "spawn_agent",
                "tool_input": {"task_name": "risk-task", "message": envelope},
            },
        )
        assert governed_rc == 0
        assert governed == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

        start_rc, start = _invoke(
            lifecycle_main,
            {
                "hook_event_name": "SubagentStart",
                "root_thread_id": "hook-run",
                "thread_id": "orphan-child",
                "model": "gpt-5.4",
            },
        )
        assert start_rc == 0 and start == {}
        store = Store(home / "state" / "conductor.db")
        assert store.reservation("orphan-child").recoverable is True
    finally:
        restore_env(old)


def test_hook_entrypoints_return_controlled_error_payloads(tmp_path: Path) -> None:
    from conductor.hooks.lifecycle import main as lifecycle_main
    from conductor.hooks.session_start import main as session_main

    _, old = _environment(tmp_path)
    try:
        rc, session = _invoke(session_main, {"model": "gpt-5.5"})
        assert rc == 0
        assert session["conductor"]["ready"] is False

        rc, lifecycle = _invoke(lifecycle_main, {"hook_event_name": "SubagentStop"})
        assert rc == 0
        assert lifecycle["conductor"]["recorded"] is False
    finally:
        restore_env(old)


def test_active_pre_tool_hook_renews_an_expired_run_lease(tmp_path: Path) -> None:
    from conductor.hooks.pre_tool_use import main as pre_tool_main
    from conductor.hooks.session_start import main as session_main

    home, old = _environment(tmp_path)
    try:
        session = {
            "thread_id": "renew-run",
            "root_thread_id": "renew-run",
            "model": "gpt-5.5",
        }
        assert _invoke(session_main, session)[0] == 0
        database = home / "state" / "conductor.db"
        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE leases SET expires_at = 0 WHERE run_id = ?", ("renew-run",)
            )
            connection.commit()
        finally:
            connection.close()

        envelope = (
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"risk-task",'
            '"task_class":"high_risk","risk_triggers":[],"owned_paths":["src/risk.py"],'
            '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
        )
        _, response = _invoke(
            pre_tool_main,
            {
                **session,
                "tool_call_id": "renew-call",
                "tool_name": "spawn_agent",
                "tool_input": {"task_name": "risk-task", "message": envelope},
            },
        )

        assert response == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
    finally:
        restore_env(old)


def test_common_hook_io_handles_empty_non_object_and_logs_safely(
    tmp_path: Path,
) -> None:
    from conductor.hooks.common import log_error, read_payload, write_json

    home, old = _environment(tmp_path)
    stdin = sys.stdin
    try:
        sys.stdin = io.StringIO("[]")
        assert read_payload() == {}
        sys.stdin = io.StringIO("")
        assert read_payload() == {}
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            write_json({"ok": True})
        assert json.loads(output.getvalue()) == {"ok": True}
        log_error("test", ValueError("bounded"))
        assert "ValueError" in (home / "state" / "errors.log").read_text(
            encoding="utf-8"
        )
        log_error("secret", ValueError("api_key=sk-supersecret123 token=hunter2"))
        logged = (home / "state" / "errors.log").read_text(encoding="utf-8")
        assert "supersecret" not in logged
        assert "hunter2" not in logged
        assert "<redacted>" in logged

        victim = tmp_path / "victim.log"
        victim.write_text("preserve\n", encoding="utf-8")
        errors = home / "state" / "errors.log"
        errors.unlink()
        try:
            os.symlink(victim, errors)
        except (OSError, NotImplementedError):
            pass
        else:
            log_error("symlink", ValueError("must not follow"))
            assert victim.read_text(encoding="utf-8") == "preserve\n"
    finally:
        sys.stdin = stdin
        restore_env(old)


def test_common_hook_io_rejects_oversized_payloads() -> None:
    from conductor.hooks.common import MAX_HOOK_PAYLOAD_BYTES, read_payload

    stdin = sys.stdin
    try:
        sys.stdin = io.StringIO(" " * (MAX_HOOK_PAYLOAD_BYTES + 1))
        with pytest.raises(ValueError, match="hook payload exceeds"):
            read_payload()

        # A character count below the limit can still exceed the byte limit.
        sys.stdin = io.StringIO('"' + ("\N{EURO SIGN}" * 400_000) + '"')
        with pytest.raises(ValueError, match="hook payload exceeds"):
            read_payload()
    finally:
        sys.stdin = stdin
