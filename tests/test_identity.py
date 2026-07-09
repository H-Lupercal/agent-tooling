from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
