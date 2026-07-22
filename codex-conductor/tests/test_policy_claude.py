from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from conductor.config import load_config
from conductor.policy import evaluate_policy
from conductor.schemas import (
    NormalizedOperation,
    OperatingMode,
    OperationName,
    Provider,
    RunContext,
    TaskEnvelopeV2,
)
from conductor.store import ReservationSnapshot
from tests.helpers import PROJECT_ROOT

CLAUDE_CONFIG = (
    PROJECT_ROOT / "src" / "conductor" / "assets" / "config" / "conductor.claude.toml"
)
EMPTY = ReservationSnapshot(active_by_tier={}, reserved_usd=0.0, spent_usd=0.0)


def _run(mode: OperatingMode = OperatingMode.ROUTING) -> RunContext:
    now = datetime.now(UTC)
    return RunContext(
        provider=Provider.CLAUDE,
        run_id="run-1",
        thread_id="thread-1",
        root_model="claude-opus-4-8",
        model_source="provider",
        provider_contract="claude-current",
        contract_digest="0" * 64,
        mode=mode,
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest="1" * 64,
    )


def _operation(
    task_class: str = "implementation",
    *,
    model: str | None = "claude-sonnet-5",
    risk_triggers: tuple[str, ...] = (),
    effort: str | None = None,
) -> NormalizedOperation:
    payload: dict[str, object] = {"message": "do it", "task_name": f"task-{task_class}"}
    if model is not None:
        payload["model"] = model
    if effort is not None:
        # Claude never sends a per-call effort field; include a stray value only
        # to prove the policy ignores it for a Claude run.
        payload["reasoning_effort"] = effort
    envelope = TaskEnvelopeV2(
        schema_version=1,
        task_name=f"task-{task_class}",
        task_class=task_class,
        risk_triggers=risk_triggers,
        owned_paths=("src/example.py",),
        acceptance_checks=("pytest -q",),
        new_task=True,
    )
    return NormalizedOperation(
        provider=Provider.CLAUDE,
        operation=OperationName.SPAWN,
        raw_tool_name="Task",
        payload=payload,
        envelope=envelope,
        is_new_work=True,
        correlation_id="call-1",
    )


def _evaluate(operation: NormalizedOperation, **overrides):
    values = {
        "operation": operation,
        "run": _run(),
        "config": load_config(CLAUDE_CONFIG),
        "enabled_tiers": (0, 1, 2),
        "snapshot": EMPTY,
        "caller_model": "claude-opus-4-8",
        "caller_effort": "",
        "caller_depth": 0,
    }
    values.update(overrides)
    return evaluate_policy(**values)


def _spawnable_standard_config(tmp_path: Path):
    """Claude ladder with the standard (sonnet) tier allowed to spawn.

    The shipped ladder only lets the frontier tier delegate, so the capability
    ceiling is structurally unreachable there. This variant exercises it.
    """
    text = CLAUDE_CONFIG.read_text(encoding="utf-8").replace(
        'model = "claude-sonnet-5"\n'
        "generation_rank = 48\n"
        "capability_rank = 25\n"
        'reasoning_effort = "medium"\n'
        'enabled = "always"\n'
        "relative_cost_weight = 25\n"
        "est_task_usd = 0.60\n"
        "max_concurrent = 4\n"
        "may_spawn = false",
        'model = "claude-sonnet-5"\n'
        "generation_rank = 48\n"
        "capability_rank = 25\n"
        'reasoning_effort = "medium"\n'
        'enabled = "always"\n'
        "relative_cost_weight = 25\n"
        "est_task_usd = 0.60\n"
        "max_concurrent = 4\n"
        "may_spawn = true",
    )
    path = tmp_path / "claude-spawnable.toml"
    path.write_text(text, encoding="utf-8")
    return load_config(path)


# T1
def test_claude_orchestrator_may_choose_a_cheaper_model_for_any_class() -> None:
    # "implementation" is owned by the sonnet tier; the old behavior denied any
    # other model with MODEL_MISMATCH. Model-led routing allows a cheaper choice.
    result = _evaluate(_operation(model="claude-haiku-4-5"))
    assert result.spec.allowed is True
    assert result.selected_model == "claude-haiku-4-5"
    assert result.reasoning_effort is None


# T2
def test_claude_omitted_model_inherits_the_caller_model() -> None:
    result = _evaluate(_operation(model=None))
    assert result.spec.allowed is True
    assert result.selected_model == "claude-opus-4-8"


# T3
def test_claude_allowed_spawn_records_null_effort() -> None:
    result = _evaluate(_operation(model="claude-sonnet-5"))
    assert result.spec.allowed is True
    # This value flows into ReservationRequest.reasoning_effort -> stored NULL.
    assert result.reasoning_effort is None


# T4
@pytest.mark.parametrize("stray_effort", [None, "ultra", "low"])
def test_claude_never_enforces_effort(stray_effort: str | None) -> None:
    result = _evaluate(_operation(model="claude-haiku-4-5", effort=stray_effort))
    assert result.spec.allowed is True
    assert result.spec.rule not in {
        "MISSING_EFFORT_SELECTION",
        "EFFORT_CEILING",
        "UNKNOWN_CALLER_EFFORT",
        "UNKNOWN_TARGET_EFFORT",
        "UNSUPPORTED_MODEL_EFFORT",
    }
    assert result.reasoning_effort is None


# T5
def test_claude_capability_ceiling_blocks_a_stronger_worker(tmp_path: Path) -> None:
    config = _spawnable_standard_config(tmp_path)
    result = _evaluate(
        _operation(model="claude-opus-4-8"),
        config=config,
        caller_model="claude-sonnet-5",
    )
    assert result.spec.allowed is False
    assert result.spec.rule == "MODEL_CAPABILITY_CEILING"


# T6
def test_claude_high_risk_stays_on_frontier() -> None:
    result = _evaluate(_operation("high_risk", model="claude-haiku-4-5"))
    assert result.spec.allowed is False
    assert result.spec.rule == "HIGH_RISK_REQUIRES_FRONTIER"


@pytest.mark.parametrize(
    "worker", ["claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5"]
)
def test_claude_allowed_worker_never_exceeds_caller_and_effort_is_null(
    worker: str,
) -> None:
    # For any allowed frontier-caller decision, the worker is at or below the
    # caller on both authority axes and effort is never asserted.
    config = load_config(CLAUDE_CONFIG)
    caller_tier = config.tier_for_model("claude-opus-4-8")
    assert caller_tier is not None
    result = _evaluate(_operation(model=worker), config=config)
    if result.spec.allowed:
        target = config.tier_for_model(worker)
        assert target is not None
        assert target.generation_rank is not None
        assert caller_tier.generation_rank is not None
        assert target.generation_rank <= caller_tier.generation_rank
        assert target.effective_capability_rank <= caller_tier.effective_capability_rank
        assert result.reasoning_effort is None
