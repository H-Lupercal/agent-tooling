from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

import conductor.identity as identity
from conductor.errors import StateError
from conductor.rollout import SessionMeta
from conductor.schemas import ConductorConfig
from tests.helpers import DEFAULT_CONFIG, FIXTURES, write_config
from tests.test_schemas import valid_config


def root_transcript_fixture(tmp_path: Path) -> dict:
    from conductor.capabilities import contract_digest, load_contract
    from conductor.config import config_digest, load_config

    transcript = tmp_path / "rollout-root-run.jsonl"
    shutil.copyfile(FIXTURES / "rollout_root.jsonl", transcript)
    config = load_config(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))
    contract = load_contract("codex-current")
    return {
        "provider": "codex",
        "transcript_path": str(transcript),
        "root_model": "gpt-5.5",
        "model_source": "transcript",
        "provider_contract": contract.contract_name,
        "contract_digest": contract_digest(contract),
        "mode": "admission",
        "generation": 1,
        "started_at": datetime(2026, 7, 9, tzinfo=UTC),
        "heartbeat_at": datetime(2026, 7, 9, tzinfo=UTC),
        "config_digest": config_digest(config),
    }


def test_root_transcript_thread_id_becomes_run_id(tmp_path: Path) -> None:
    from conductor.identity import resolve_run_context

    context = resolve_run_context(root_transcript_fixture(tmp_path))

    assert context.run_id == "root-run"
    assert context.thread_id == "root-run"
    assert context.root_model == "gpt-5.5"


def test_run_context_round_trips_through_strict_persistence(tmp_path: Path) -> None:
    from conductor.identity import (
        read_run_context,
        resolve_run_context,
        write_run_context,
    )

    context = resolve_run_context(root_transcript_fixture(tmp_path))
    destination = tmp_path / "state" / "run-context.json"

    write_run_context(destination, context)

    assert read_run_context(destination) == context


def test_resolves_root_run_id_depth_and_tier_from_payload_and_rollouts(
    tmp_path: Path,
) -> None:
    from conductor.config import load_ladder
    from conductor.identity import resolve_caller

    sessions = tmp_path / "sessions"
    day = sessions / "2026" / "07" / "06"
    day.mkdir(parents=True)
    root_rollout = day / "rollout-root-run.jsonl"
    child_rollout = day / "rollout-child-thread.jsonl"
    shutil.copyfile(FIXTURES / "rollout_root.jsonl", root_rollout)
    shutil.copyfile(FIXTURES / "rollout_subagent.jsonl", child_rollout)
    ladder = load_ladder(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))

    caller = resolve_caller(
        {
            "model": "gpt-5.4",
            "thread_id": "child-thread",
            "agent_transcript_path": str(child_rollout),
        },
        ladder,
        sessions,
    )

    assert caller.run_id == "root-run"
    assert caller.depth == 1
    assert caller.tier_index == 1


def test_codex_caller_reads_active_reasoning_effort(tmp_path: Path) -> None:
    from conductor.config import load_ladder
    from conductor.identity import resolve_caller

    ladder = load_ladder(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))

    caller = resolve_caller(
        {
            "run_id": "root-run",
            "thread_id": "root-run",
            "model": "gpt-5.5",
            "model_reasoning_effort": "high",
        },
        ladder,
        tmp_path / "sessions",
    )

    assert caller.effort == "high"


def test_unknown_identity_and_model_use_explicit_posture_without_tier_fabrication(
    tmp_path: Path,
) -> None:
    from conductor.identity import resolve_identity

    deny_config = ConductorConfig.model_validate(valid_config())
    unknown_identity = resolve_identity(
        {"model": "unknown", "thread_id": "child-thread"},
        deny_config,
        tmp_path / "sessions",
    )
    assert unknown_identity.posture == "deny"
    assert unknown_identity.caller.run_id is None
    assert unknown_identity.caller.tier_index is None

    observe_payload = valid_config()
    observe_payload["policy"]["unknown_model"] = "observe"
    observe_config = ConductorConfig.model_validate(observe_payload)
    unknown_model = resolve_identity(
        {"run_id": "root-run", "thread_id": "root-run", "model": "unknown"},
        observe_config,
        tmp_path / "sessions",
    )
    assert unknown_model.posture == "observe"
    assert unknown_model.caller.tier_index is None


def test_invalid_root_identity_is_controlled_state_error(tmp_path: Path) -> None:
    from conductor.errors import StateError
    from conductor.identity import resolve_run_context

    payload = root_transcript_fixture(tmp_path)
    payload["run_id"] = "../escape"

    with pytest.raises(StateError, match="invalid run context"):
        resolve_run_context(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"contract_digest": "f" * 64},
        {"provider": "claude"},
    ],
)
def test_run_context_rejects_contract_digest_or_provider_mismatch(
    tmp_path: Path,
    change: dict[str, str],
) -> None:
    from conductor.errors import StateError
    from conductor.identity import resolve_run_context

    payload = root_transcript_fixture(tmp_path)
    payload.update(change)

    with pytest.raises(StateError, match="provider contract"):
        resolve_run_context(payload)


def test_resolve_caller_handles_relative_root_missing_parent_and_bad_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conductor.config import load_ladder

    ladder = load_ladder(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        identity,
        "read_session_meta",
        lambda _path: SessionMeta("child", "missing-parent", "subagent", None, "."),
    )
    monkeypatch.setattr(identity, "find_rollout", lambda *_args: None)
    missing_parent = identity.resolve_caller(
        {"model": "gpt-5.4", "transcript_path": "relative.jsonl"},
        ladder,
        tmp_path / "sessions",
    )
    assert missing_parent.run_id == "missing-parent"
    assert missing_parent.thread_id == "child"
    assert missing_parent.depth == 1

    monkeypatch.setattr(
        identity,
        "read_session_meta",
        lambda _path: SessionMeta("root", None, None, None, "."),
    )
    root = identity.resolve_caller(
        {"model": "gpt-5.4", "transcript_path": "root.jsonl"},
        ladder,
        tmp_path / "sessions",
    )
    assert root.run_id == "root"

    monkeypatch.setattr(
        identity,
        "read_session_meta",
        lambda _path: (_ for _ in ()).throw(ValueError("invalid")),
    )
    degraded = identity.resolve_caller(
        {
            "model": "gpt-5.4",
            "run_id": "run-1",
            "thread_id": "thread-1",
            "transcript_path": "bad",
        },
        ladder,
        tmp_path / "sessions",
    )
    assert degraded.run_id == "run-1"
    assert degraded.depth == 0


def test_resolve_caller_counts_nested_parent_hops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conductor.config import load_ladder

    ladder = load_ladder(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))
    child = tmp_path / "child.jsonl"
    parent = tmp_path / "parent.jsonl"
    grand = tmp_path / "grand.jsonl"
    metas = {
        child: SessionMeta("child", "parent", "subagent", None, "."),
        parent: SessionMeta("parent", "grand", "subagent", None, "."),
        grand: SessionMeta("grand", None, None, None, "."),
    }
    monkeypatch.setattr(identity, "read_session_meta", lambda path: metas[Path(path)])
    monkeypatch.setattr(
        identity,
        "find_rollout",
        lambda thread, _root: {"parent": parent, "grand": grand}.get(thread),
    )

    caller = identity.resolve_caller(
        {"model": "gpt-5.4", "transcript_path": str(child)},
        ladder,
        tmp_path,
    )
    assert caller.run_id == "grand"
    assert caller.depth == 2


def test_known_identity_returns_known_posture(tmp_path: Path) -> None:
    config = ConductorConfig.model_validate(valid_config())
    resolved = identity.resolve_identity(
        {
            "run_id": "run-1",
            "thread_id": "thread-1",
            "model": "gpt-5.4",
        },
        config,
        tmp_path,
    )
    assert resolved.posture == "known"


def test_run_context_rejects_invalid_payload_provider_transcript_and_contract(
    tmp_path: Path,
) -> None:
    with pytest.raises(StateError, match="payload must be an object"):
        identity.resolve_run_context([])  # type: ignore[arg-type]
    with pytest.raises(StateError, match="provider"):
        identity.resolve_run_context({"provider": "unknown"})

    invalid_transcript = tmp_path / "invalid.jsonl"
    invalid_transcript.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(StateError, match="transcript"):
        identity.resolve_run_context(
            {"provider": "codex", "transcript_path": str(invalid_transcript)}
        )

    payload = root_transcript_fixture(tmp_path)
    payload["provider_contract"] = "missing-contract"
    with pytest.raises(StateError, match="provider contract"):
        identity.resolve_run_context(payload)


def test_run_context_uses_child_parent_and_reports_config_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = tmp_path / "rollout-child.jsonl"
    shutil.copyfile(FIXTURES / "rollout_subagent.jsonl", child)
    payload = root_transcript_fixture(tmp_path)
    payload.pop("transcript_path")
    payload["transcript_path"] = str(child)
    context = identity.resolve_run_context(payload)
    assert context.run_id == "root-run"
    assert context.thread_id == "child-thread"

    payload.pop("config_digest")
    monkeypatch.setattr(
        identity,
        "load_config",
        lambda: (_ for _ in ()).throw(OSError("config unavailable")),
    )
    with pytest.raises(StateError, match="configuration"):
        identity.resolve_run_context(payload)


def test_run_context_persistence_errors_are_controlled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = identity.resolve_run_context(root_transcript_fixture(tmp_path))
    destination = tmp_path / "state" / "run.json"
    monkeypatch.setattr(
        identity.os,
        "replace",
        lambda *_args: (_ for _ in ()).throw(OSError("read-only")),
    )
    with pytest.raises(StateError, match="cannot persist run context"):
        identity.write_run_context(destination, context)
    assert not list(destination.parent.glob("*.tmp"))

    with pytest.raises(StateError, match="cannot read run context"):
        identity.read_run_context(tmp_path / "missing.json")
    invalid = tmp_path / "invalid-context.json"
    invalid.write_text("{}", encoding="utf-8")
    with pytest.raises(StateError, match="cannot read run context"):
        identity.read_run_context(invalid)
