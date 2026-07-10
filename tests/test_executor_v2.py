from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from toolbelt.catalog import load_catalog_v2
from toolbelt.executor import Executor
from toolbelt.planner import build_plan_v2
from toolbelt.schemas import CapabilitySnapshot, EvidenceV2

NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _fixture(
    tmp_path: Path,
    *,
    verify_fails: bool = False,
    sleeps: bool = False,
    huge_output: bool = False,
):
    script = tmp_path / "fixture.py"
    state = tmp_path / "machine.txt"
    script.write_text(
        """
import pathlib
import os
import subprocess
import sys
import time

command = sys.argv[1]
state = pathlib.Path(sys.argv[2])
if command == "install":
    state.write_text("installed", encoding="utf-8")
elif command == "verify":
    if sys.argv[3] == "fail":
        raise SystemExit(9)
    if sys.argv[3] == "sleep":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        pathlib.Path(sys.argv[4]).write_text(str(child.pid), encoding="ascii")
        time.sleep(60)
    if sys.argv[3] == "output":
        sys.stdout.write(os.environ["TOOLBELT_TEST_SECRET"] + "\\n")
        sys.stdout.write("x" * (10 * 1024 * 1024))
        raise SystemExit(0)
    raise SystemExit(0 if state.exists() else 8)
elif command == "rollback":
    state.unlink(missing_ok=True)
""".lstrip(),
        encoding="utf-8",
    )
    pid_file = tmp_path / ".toolbelt" / "child.pid"
    verify_extra = (
        "sleep" if sleeps else ("output" if huge_output else ("fail" if verify_fails else "pass"))
    )
    verify_argv = [sys.executable, str(script), "verify", str(state), verify_extra]
    if sleeps:
        verify_argv.append(str(pid_file))
    catalog_path = tmp_path / "catalog.toml"
    catalog_path.write_text(
        "\n".join(
            (
                "schema_version = 2",
                "[[tool]]",
                "schema_version = 2",
                'id = "fixture"',
                'name = "Fixture"',
                'summary = "Transactional fixture"',
                'kind = "dev_tool"',
                'provenance = "toolbelt:fixture"',
                'version = "1.0.0"',
                'homepage = "https://example.com/fixture"',
                'license = "MIT"',
                f"platforms = [{json.dumps('windows' if os.name == 'nt' else 'linux')}]",
                'harnesses = ["codex", "claude"]',
                'permissions = ["process-spawn", "filesystem-write"'
                + (', "credentials-read"]' if huge_output else "]"),
                'install_scope = "project"',
                'artifacts = ["machine.txt"]',
                'required_env = ["TOOLBELT_TEST_SECRET"]' if huge_output else "required_env = []",
                'strong_evidence = ["config:fixture"]',
                f"install = {{ argv = {json.dumps([sys.executable, str(script), 'install', str(state)])} }}",
                f"verify = {{ argv = {json.dumps(verify_argv)}, timeout_seconds = {0.2 if sleeps else 5.0} }}",
                f"rollback = {{ argv = {json.dumps([sys.executable, str(script), 'rollback', str(state)])} }}",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    catalog = load_catalog_v2(catalog_path)
    capabilities = CapabilitySnapshot(provider="combined", status="known")
    evidence = [
        EvidenceV2(
            type="config",
            key="fixture",
            detail="test fixture",
            source="fixture.py",
            strength="strong",
        )
    ]
    plan = build_plan_v2(
        tmp_path,
        evidence,
        catalog,
        capabilities,
        now=NOW,
    )
    return plan, catalog, capabilities, state, pid_file


def test_successful_apply_verifies_before_committing_declaration(tmp_path: Path) -> None:
    plan, catalog, capabilities, state, _ = _fixture(tmp_path)

    result = Executor().apply(plan, tmp_path, catalog, capabilities, now=NOW)

    assert result.state == "succeeded"
    assert state.read_text(encoding="utf-8") == "installed"
    lock = tmp_path / ".toolbelt" / "lock.toml"
    assert lock.exists()
    assert 'tool_id = "fixture"' in lock.read_text(encoding="utf-8")


def test_failed_verification_rolls_back_entire_action_set(tmp_path: Path) -> None:
    plan, catalog, capabilities, state, _ = _fixture(tmp_path, verify_fails=True)

    result = Executor().apply(plan, tmp_path, catalog, capabilities, now=NOW)

    assert result.state == "rolled_back"
    assert not state.exists()
    assert not (tmp_path / ".toolbelt" / "lock.toml").exists()


def test_dry_run_performs_preflight_without_commands_or_declaration(tmp_path: Path) -> None:
    plan, catalog, capabilities, state, _ = _fixture(tmp_path)

    result = Executor().apply(
        plan,
        tmp_path,
        catalog,
        capabilities,
        now=NOW,
        dry_run=True,
    )

    assert result.state == "succeeded"
    assert not state.exists()
    assert not (tmp_path / ".toolbelt" / "lock.toml").exists()


def test_catalog_change_requires_full_declared_tool_verification(tmp_path: Path) -> None:
    plan, catalog, capabilities, state, _ = _fixture(tmp_path)
    first = Executor().apply(plan, tmp_path, catalog, capabilities, now=NOW)
    assert first.state == "succeeded"
    catalog_path = Path(catalog.source)
    catalog_path.write_text(
        catalog_path.read_text(encoding="utf-8") + "# reviewed catalog change\n",
        encoding="utf-8",
    )
    changed_catalog = load_catalog_v2(catalog_path)
    changed_plan = build_plan_v2(
        tmp_path,
        list(plan.actions[0].evidence),
        changed_catalog,
        capabilities,
        now=NOW,
    )

    result = Executor().apply(
        changed_plan,
        tmp_path,
        changed_catalog,
        capabilities,
        now=NOW,
    )

    assert result.state == "rolled_back"
    assert "verify every declared tool" in (result.error or "")
    assert state.exists()


def test_declared_tool_cannot_be_reinstalled_even_with_manual_inventory(tmp_path: Path) -> None:
    plan, catalog, capabilities, state, _ = _fixture(tmp_path)
    first = Executor().apply(plan, tmp_path, catalog, capabilities, now=NOW)
    assert first.state == "succeeded"
    duplicate = build_plan_v2(
        tmp_path,
        list(plan.actions[0].evidence),
        catalog,
        capabilities,
        now=NOW,
    )

    result = Executor().apply(duplicate, tmp_path, catalog, capabilities, now=NOW)

    assert result.state == "rolled_back"
    assert "already declared" in (result.error or "")
    assert state.exists()
