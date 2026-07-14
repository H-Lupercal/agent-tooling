import sys

import pytest

from install_rehearsal.runner import RunLimits, run_command


def test_runner_captures_success_without_shell(tmp_path) -> None:
    result = run_command(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=5, output_bytes=1024),
    )

    assert result.exit_code == 0
    assert result.stdout_excerpt == "ok\n"
    assert result.termination_reason == "exited"


def test_runner_marks_timeout(tmp_path) -> None:
    result = run_command(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        cwd=tmp_path,
        environment={},
        limits=RunLimits(timeout_seconds=0.05, output_bytes=1024),
    )

    assert result.termination_reason == "timeout"
    assert result.exit_code is None


def test_runner_bounds_and_redacts_output(tmp_path) -> None:
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
def test_runner_refuses_elevation_helpers(tmp_path, executable: str) -> None:
    with pytest.raises(ValueError, match="elevation helper"):
        run_command(
            [executable, "echo", "unsafe"],
            cwd=tmp_path,
            environment={},
            limits=RunLimits(),
        )

