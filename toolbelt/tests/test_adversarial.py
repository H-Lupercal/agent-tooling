from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from tests.test_executor_v2 import NOW, _fixture
from toolbelt.executor import Executor
from toolbelt.planner import build_plan_v2
from toolbelt.schemas import CapabilitySnapshot, EvidenceV2
from toolbelt.state import atomic_write_text


def test_ten_mib_output_is_bounded_and_declared_secret_is_redacted(tmp_path: Path) -> None:
    plan, catalog, capabilities, _, _ = _fixture(tmp_path, huge_output=True)
    environment = os.environ.copy()
    environment["TOOLBELT_TEST_SECRET"] = "super-secret-fixture-value"

    result = Executor(environment=environment).apply(
        plan,
        tmp_path,
        catalog,
        capabilities,
        now=NOW,
    )

    assert result.state == "succeeded"
    verification = next(command for command in result.commands if command.argv[2] == "verify")
    assert len(verification.stdout.encode("utf-8")) <= 64 * 1024
    assert "super-secret-fixture-value" not in verification.stdout
    assert "[REDACTED]" in verification.stdout
    assert verification.redacted is True


def test_atomic_write_disk_failure_preserves_original_and_removes_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "lock.toml"
    target.write_text("original\n", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("toolbelt.state.os.replace", fail_replace)
    with pytest.raises(OSError, match="simulated"):
        atomic_write_text(target, "replacement\n")

    assert target.read_text(encoding="utf-8") == "original\n"
    assert not list(tmp_path.glob("*.tmp"))


def test_unicode_repository_without_git_binds_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "δοκιμή-文件.toml"
    source.write_text("fixture = true\n", encoding="utf-8")
    monkeypatch.setattr("toolbelt.planner._run_git_bytes", lambda *args: None)
    catalog = _fixture(tmp_path)[1]
    capabilities = CapabilitySnapshot(provider="combined", status="known")
    evidence = [
        EvidenceV2(
            type="config",
            key="fixture",
            detail="Unicode fixture",
            source=source.name,
            strength="strong",
        )
    ]

    first = build_plan_v2(tmp_path, evidence, catalog, capabilities, now=NOW)
    second = build_plan_v2(tmp_path, evidence, catalog, capabilities, now=NOW)

    assert first.plan_id == second.plan_id
    assert first.repository.git_head is None


def test_state_lock_timeout_is_bounded(tmp_path: Path) -> None:
    from toolbelt.state import StateStore

    database = tmp_path / "state.sqlite3"
    store = StateStore(database, busy_timeout_ms=25)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(Exception, match="locked|database operation"):
            store.begin_transaction(
                plan_id="a" * 64,
                repository_identity="b" * 64,
            )
    finally:
        connection.rollback()
        connection.close()
