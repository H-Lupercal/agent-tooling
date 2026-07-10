from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from conductor.config import config_digest, load_config
from conductor.identity import Caller
from conductor.schemas import OperatingMode, RunContext
from conductor.store import Store
from tests.helpers import DEFAULT_CONFIG, FIXTURES, write_config


def _payload(task_name: str = "implementation-task") -> dict:
    payload = json.loads(
        (FIXTURES / "hook_payloads" / "pre_tool_use_spawn.json").read_text(
            encoding="utf-8"
        )
    )
    message = payload["tool_input"]["message"]
    message = message.replace(
        '"task_name":"tests_ledger"', f'"task_name":"{task_name}"'
    )
    message = message.replace('"task_class":"tests"', '"task_class":"implementation"')
    payload["tool_input"]["task_name"] = task_name
    payload["tool_input"]["message"] = message
    payload["tool_call_id"] = f"call-{task_name}"
    return payload


def _setup(tmp_path: Path, *, mode: OperatingMode = OperatingMode.ROUTING):
    config = load_config(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))
    now = datetime.now(UTC)
    run = RunContext(
        provider="codex",
        run_id="root-run",
        thread_id="root-run",
        root_model="gpt-5.5",
        model_source="provider",
        provider_contract="codex-current",
        contract_digest="0" * 64,
        mode=mode,
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest=config_digest(config),
    )
    store = Store(tmp_path / "conductor.db")
    store.create_run(
        run.run_id,
        provider=run.provider.value,
        generation=run.generation,
        mode=run.mode.value,
        context=run.model_dump(mode="json"),
    )
    caller = Caller("root-run", "root-run", 0, 0, "gpt-5.5")
    return config, run, store, caller


def _decide(tmp_path: Path, payload: dict, **overrides):
    from conductor.hooks.pre_tool_use import decide

    config, run, store, caller = _setup(
        tmp_path, mode=overrides.pop("mode", OperatingMode.ROUTING)
    )
    return (
        decide(
            payload,
            overrides.pop("config", config),
            store,
            overrides.pop("run", run),
            overrides.pop("caller", caller),
            overrides.pop("enabled", (0, 1, 2, 3)),
            provider_name="codex",
        ),
        store,
    )


def test_hook_policy_and_reservation_are_one_idempotent_transaction(
    tmp_path: Path,
) -> None:
    payload = _payload()
    decision, store = _decide(tmp_path, payload)

    from conductor.hooks.pre_tool_use import decide

    config = load_config(tmp_path / "conductor.toml")
    run = store.run_context("root-run")
    caller = Caller("root-run", "root-run", 0, 0, "gpt-5.5")
    duplicate = decide(
        payload,
        config,
        store,
        run,
        caller,
        (0, 1, 2, 3),
        provider_name="codex",
    )

    assert decision.allowed is True
    assert decision.rule == "ALLOW"
    assert decision.reservation_id is not None
    assert duplicate == decision
    assert store.decision_count(run_id="root-run") == 1
    assert store.reserved_count(run_id="root-run") == 1


def test_malformed_governed_payload_is_persisted_as_a_denial(
    tmp_path: Path,
) -> None:
    payload = _payload("malformed")
    payload["tool_input"]["message"] = "no envelope"

    decision, store = _decide(tmp_path, payload)

    assert decision.allowed is False
    assert decision.rule == "MISSING_ENVELOPE"
    assert decision.reservation_id is None
    assert store.decision_count(run_id="root-run") == 1
    assert store.reserved_count(run_id="root-run") == 0


def test_atomic_snapshot_enforces_concurrency_across_hook_calls(
    tmp_path: Path,
) -> None:
    from conductor.hooks.pre_tool_use import decide

    config, run, store, caller = _setup(tmp_path)
    decisions = [
        decide(
            _payload(f"task-{index}"),
            config,
            store,
            run,
            caller,
            (0, 1, 2, 3),
            provider_name="codex",
        )
        for index in range(6)
    ]

    assert sum(decision.allowed for decision in decisions) == 4
    assert [decision.rule for decision in decisions[-2:]] == [
        "CONCURRENCY_CAP",
        "CONCURRENCY_CAP",
    ]
    assert store.reserved_count(run_id="root-run", tier="standard") == 4


def test_config_drift_and_unknown_identity_fail_closed(tmp_path: Path) -> None:
    payload = _payload()
    config, run, store, caller = _setup(tmp_path)
    drifted = run.model_copy(update={"config_digest": "f" * 64})

    from conductor.hooks.pre_tool_use import decide

    drift = decide(
        payload,
        config,
        store,
        drifted,
        caller,
        (0, 1, 2, 3),
        provider_name="codex",
    )
    unknown = decide(
        _payload("unknown"),
        config,
        store,
        run,
        Caller(None, None, 0, None, ""),
        (0, 1, 2, 3),
        provider_name="codex",
    )

    assert drift.rule == "CONFIG_DRIFT"
    assert drift.allowed is False
    assert unknown.rule == "IDENTITY_UNKNOWN"
    assert unknown.allowed is False


def test_observe_mode_never_creates_a_reservation(tmp_path: Path) -> None:
    decision, store = _decide(
        tmp_path,
        _payload(),
        mode=OperatingMode.OBSERVE,
    )

    assert decision.allowed is True
    assert decision.rule == "OBSERVE_ONLY"
    assert decision.reservation_id is None
    assert store.reserved_count(run_id="root-run") == 0


def test_feedback_bypasses_state_and_policy(tmp_path: Path) -> None:
    config, run, store, caller = _setup(tmp_path)
    from conductor.hooks.pre_tool_use import decide

    decision = decide(
        {
            "tool_name": "collaboration.send_message",
            "tool_input": {"target": "agent", "message": "status?"},
        },
        config,
        store,
        run,
        caller,
        (0, 1, 2, 3),
        provider_name="codex",
    )

    assert decision.allowed is True
    assert decision.rule == "NOT_GOVERNED"
    assert store.decision_count(run_id="root-run") == 0


def test_enforced_mode_denies_work_without_exact_provider_correlation(
    tmp_path: Path,
) -> None:
    payload = _payload("missing-correlation")
    payload.pop("tool_call_id")

    decision, store = _decide(tmp_path, payload)

    assert decision.allowed is False
    assert decision.rule == "MISSING_CORRELATION"
    assert decision.reservation_id is None
    assert store.decision_count(run_id="root-run") == 1
