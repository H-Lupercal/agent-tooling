import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from install_rehearsal.runner import RunLimits, run_command


def test_runner_captures_success_without_shell(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=5, output_bytes=1024),
    )

    assert result.exit_code == 0
    assert result.stdout_excerpt == f"ok{os.linesep}"
    assert result.termination_reason == "exited"


def test_runner_marks_timeout(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=0.05, output_bytes=1024),
    )

    assert result.termination_reason == "timeout"
    assert result.exit_code is None


def test_runner_bounds_and_redacts_output(tmp_path: Path) -> None:
    result = run_command(
        [sys.executable, "-c", "print('TOKEN=abc123-' + 'x' * 100)"],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=5, output_bytes=30),
    )

    assert result.stdout_truncated is True
    assert "abc123" not in result.stdout_excerpt
    assert len(result.stdout_excerpt.encode()) <= 30


@pytest.mark.parametrize("executable", ["sudo", "/usr/bin/doas", "RUNAS.exe"])
def test_runner_refuses_elevation_helpers(tmp_path: Path, executable: str) -> None:
    with pytest.raises(ValueError, match="elevation helper"):
        run_command(
            [executable, "echo", "unsafe"],
            cwd=tmp_path,
            environment={},
            limits=RunLimits(),
        )


def test_runner_rejects_invalid_limits_and_argv(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="timeout"):
        RunLimits(timeout_seconds=0)
    with pytest.raises(ValueError, match="byte limit"):
        RunLimits(output_bytes=-1)
    with pytest.raises(ValueError, match="empty"):
        run_command([], cwd=tmp_path, environment={}, limits=RunLimits())
    with pytest.raises(ValueError, match="NUL"):
        run_command(["bad\0command"], cwd=tmp_path, environment={}, limits=RunLimits())


def test_runner_records_launch_error(tmp_path: Path) -> None:
    result = run_command(
        [str(tmp_path / "missing-executable")],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(),
    )

    assert result.termination_reason == "launch_error"
    assert result.exit_code is None
    assert result.stderr_excerpt


def test_runner_streams_output_without_communicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_communicate(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("communicate buffers unbounded output")

    monkeypatch.setattr(subprocess.Popen, "communicate", forbidden_communicate)
    result = run_command(
        [sys.executable, "-c", "import sys; sys.stdout.write('x' * 2_000_000)"],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=5, output_bytes=32),
    )

    assert result.exit_code == 0
    assert result.stdout_excerpt == "x" * 32
    assert result.stdout_truncated is True


def test_timeout_terminates_descendant_process(tmp_path: Path) -> None:
    marker = tmp_path / "descendant-survived"
    child = f"import pathlib,time; time.sleep(0.3); pathlib.Path({str(marker)!r}).write_text('bad')"
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(5)"
    )

    result = run_command(
        [sys.executable, "-c", parent],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=0.05, output_bytes=1024),
    )
    time.sleep(0.4)

    assert result.termination_reason == "timeout"
    assert not marker.exists()
