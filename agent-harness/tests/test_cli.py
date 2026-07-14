from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def run_cli(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    source = Path(__file__).parents[1] / "src"
    environment["PYTHONPATH"] = str(source)
    return subprocess.run(
        [sys.executable, "-m", "agent_harness", *arguments],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_init_writes_safe_default_config(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "init")

    assert result.returncode == 0
    config = tmp_path / "agent-harness.toml"
    assert config.is_file()
    assert "credential" not in config.read_text(encoding="utf-8").lower()


def test_init_refuses_to_overwrite_config_with_stable_error(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(tmp_path, "init")

    assert result.returncode == 3
    assert result.stderr.startswith("agent-harness: ")
    assert "already exists" in result.stderr


def test_doctor_validates_default_config(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(tmp_path, "doctor")

    assert result.returncode == 0
    assert "configuration valid" in result.stdout


def test_run_with_fake_roster_emits_completed_run(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(
        tmp_path,
        "--store",
        str(tmp_path / "store"),
        "run",
        "prove concurrency",
        "--fake",
    )

    assert result.returncode == 0
    assert "run.completed" in result.stdout
    run_id = result.stdout.splitlines()[0].split("=", 1)[1]

    shown = run_cli(tmp_path, "--store", str(tmp_path / "store"), "show", run_id)
    assert shown.returncode == 0
    assert '"kind":"run.started"' in shown.stdout
    assert shown.stdout.index('"sequence":1') < shown.stdout.index('"sequence":2')


def test_run_without_fake_flag_is_rejected(tmp_path: Path) -> None:
    assert run_cli(tmp_path, "init").returncode == 0

    result = run_cli(tmp_path, "run", "use live providers")

    assert result.returncode == 3
    assert result.stderr.startswith("agent-harness: ")
    assert "--fake" in result.stderr
