from __future__ import annotations

import contextlib
import io
from datetime import UTC, datetime
from pathlib import Path

import pytest

import conductor.status as status_module
from conductor.errors import StateError
from conductor.schemas import LifecycleEvent, RawUsage
from conductor.store import Store
from tests.helpers import (
    DEFAULT_CONFIG,
    restore_env,
    set_env,
    write_config,
    write_models_cache,
)
from tests.test_store import request


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
    )


def _populated_store(home: Path, *, mode: str = "routing") -> Store:
    store = Store(home / "state" / "conductor.db")
    store.create_run("run-1", provider="codex", generation=1, mode=mode)
    decision = store.reserve(
        request(
            "run-1",
            "task-1",
            correlation_id="call-1",
            model="gpt-5.4",
            estimate=0.6,
        ),
        concurrency_cap=4,
        budget_cap=10.0,
    )
    assert decision.allowed
    now = datetime.now(UTC)
    store.record_lifecycle(
        LifecycleEvent(
            event_id="start-call-1",
            provider="codex",
            run_id="run-1",
            correlation_id="call-1",
            kind="start",
            occurred_at=now,
        )
    )
    store.record_lifecycle(
        LifecycleEvent(
            event_id="terminal-call-1",
            provider="codex",
            run_id="run-1",
            correlation_id="call-1",
            kind="stop",
            occurred_at=now,
            status="completed",
        )
    )
    store.record_lifecycle(
        LifecycleEvent(
            event_id="cost-call-1",
            provider="codex",
            run_id="run-1",
            correlation_id="call-1",
            kind="cost",
            occurred_at=now,
            usage=RawUsage(
                source_event_id="usage-call-1",
                provider="codex",
                parser_version="test-v1",
                model="gpt-5.4",
                input_tokens=1_000,
                cache_read_tokens=100,
                cache_write_tokens=0,
                output_tokens=100,
                reasoning_tokens=10,
                measured=True,
                occurred_at=now,
            ),
            cost_usd=0.01,
            estimated=False,
        )
    )
    return store


def test_status_and_report_are_derived_only_from_v2_store(tmp_path: Path) -> None:
    from conductor.report import build_report, render_human
    from conductor.status import build_status

    home, old = _environment(tmp_path)
    try:
        store = _populated_store(home)
        status = build_status("run-1", store=store)
        report = build_report("run-1", store=store)
    finally:
        restore_env(old)

    assert status["schema_version"] == 1
    assert report["schema_version"] == 1
    assert status["run_id"] == "run-1"
    assert status["costs"]["measured_usd"] == 0.01
    assert status["decisions"]["total"] == 1
    assert (
        report["tiers"]["mini"]["input_tokens"] == 0
    )  # request helper labels the reservation mini
    assert report["tiers"]["standard"]["input_tokens"] == 1_000
    assert report["measured_usd"] == 0.01
    assert "TOTAL measured=" in render_human(report)


def test_savings_are_never_claimed_outside_routing_mode(tmp_path: Path) -> None:
    from conductor.report import build_report

    home, old = _environment(tmp_path)
    try:
        report = build_report("run-1", store=_populated_store(home, mode="admission"))
    finally:
        restore_env(old)

    assert report["projected_savings_usd"] is None
    assert report["savings_basis"] == "unavailable outside routing mode"


def test_invalid_or_missing_run_returns_nonzero(tmp_path: Path) -> None:
    from conductor.report import main as report_main
    from conductor.status import main as status_main

    home, old = _environment(tmp_path)
    try:
        _populated_store(home)
        with contextlib.redirect_stderr(io.StringIO()):
            assert status_main(["--run", "missing"]) != 0
            assert report_main(["--run", "missing"]) != 0
    finally:
        restore_env(old)


def test_provider_home_maps_each_provider() -> None:
    from conductor.config import provider_home

    assert provider_home("claude") == Path.home() / ".claude" / "conductor"
    assert provider_home("codex") == Path.home() / ".codex" / "conductor"


def test_status_reports_budget_pricing_lease_recovery_and_active_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, old = _environment(tmp_path)

    class SnapshotStore:
        def latest_run_id(self):
            return "run-1"

        def run_snapshot(self, run_id):
            return {
                "run_id": run_id,
                "costs": {"total_usd": 9.0},
                "reserved_usd": 1.0,
                "lease": None,
                "recoverable": 2,
                "reservations": [
                    {"state": "approved", "tier": "mini", "count": 2},
                    {"state": "started", "tier": "mini", "count": 1},
                    {"state": "denied", "tier": "frontier", "count": 5},
                ],
            }

    monkeypatch.setattr(status_module, "pricing_verified", lambda _config: False)
    monkeypatch.setattr(status_module, "enabled_tiers", lambda *_args: [])
    try:
        status = status_module.build_status(store=SnapshotStore())  # type: ignore[arg-type]
    finally:
        restore_env(old)

    assert status["remaining_usd"] == 0
    assert status["active"] == {"mini": 3}
    assert status["enabled_tiers"] == []
    assert status["warnings"] == [
        "budget warning threshold reached",
        "pricing is unverified; dollar costs may use task estimates",
        "run lease is inactive",
        "2 lifecycle record(s) require recovery",
    ]


def test_status_rejects_empty_or_missing_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, old = _environment(tmp_path)

    class EmptyStore:
        def latest_run_id(self):
            return None

    try:
        with pytest.raises(StateError, match="no conductor runs"):
            status_module.build_status(store=EmptyStore())  # type: ignore[arg-type]
    finally:
        restore_env(old)

    monkeypatch.setattr(status_module, "store_path", lambda: tmp_path / "missing.db")
    with pytest.raises(StateError, match="store does not exist"):
        status_module._existing_store()


def test_status_main_maps_unexpected_value_error_to_internal_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        status_module,
        "build_status",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid snapshot")),
    )
    assert status_module.main([]) != 0
    assert "invalid snapshot" in capsys.readouterr().err
