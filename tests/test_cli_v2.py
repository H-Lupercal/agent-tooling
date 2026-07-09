from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "toolbelt", *arguments],
        cwd=root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=['pytest']\n",
        encoding="utf-8",
    )
    return tmp_path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("command", ["scan", "discover", "status", "doctor"])
def test_read_only_commands_leave_tree_byte_identical(
    tmp_path: Path, command: str
) -> None:
    root = _repo(tmp_path)
    before = _snapshot(root)
    arguments = [command, "--json"]
    if command != "doctor" or root is not None:
        arguments.extend(("--path", str(root)))

    result = _run(root, *arguments)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 2
    assert payload["command"] == command
    assert _snapshot(root) == before
    assert not (root / ".toolbelt").exists()


def test_plan_and_apply_dry_run_have_stable_json_contract(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    capabilities = root / "capabilities.json"
    capabilities.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider": "combined",
                "provider_version": None,
                "status": "known",
                "native": [],
                "installed": [],
                "managed": [],
                "errors": [],
            }
        ),
        encoding="utf-8",
    )
    plan_path = root / ".toolbelt" / "plan.json"
    planned = _run(
        root,
        "plan",
        "--path",
        str(root),
        "--capabilities",
        str(capabilities),
        "--allow-network",
        "--out",
        ".toolbelt/plan.json",
        "--json",
    )

    assert planned.returncode == 0, planned.stderr
    plan_payload = json.loads(planned.stdout)
    assert plan_payload["data"]["plan"]["schema_version"] == 2
    assert plan_path.exists()

    applied = _run(
        root,
        "apply",
        "--path",
        str(root),
        "--capabilities",
        str(capabilities),
        "--plan",
        str(plan_path),
        "--allow-network",
        "--dry-run",
        "--json",
    )

    assert applied.returncode == 0, applied.stderr
    applied_payload = json.loads(applied.stdout)
    assert applied_payload["data"]["state"] == "succeeded"
    assert applied_payload["data"]["dry_run"] is True
    assert not (root / ".toolbelt" / "lock.toml").exists()


def test_distribution_only_strict_doctor_is_release_ready(tmp_path: Path) -> None:
    result = _run(tmp_path, "doctor", "--strict", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["data"]["ready"] is True
    assert payload["data"]["distribution"]["catalog_loaded"] is True


def test_declined_mutation_has_stable_nonzero_error(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = _run(root, "recover", "missing", "--path", str(root), "--json")

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"]
    assert "Traceback" not in result.stderr
