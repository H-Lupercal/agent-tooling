from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CleanVenv:
    root: Path

    @property
    def python(self) -> Path:
        scripts = "Scripts" if os.name == "nt" else "bin"
        name = "python.exe" if os.name == "nt" else "python"
        return self.root / scripts / name

    @property
    def conductor(self) -> Path:
        scripts = "Scripts" if os.name == "nt" else "bin"
        name = "conductor.exe" if os.name == "nt" else "conductor"
        return self.root / scripts / name

    def pip_install(self, wheel: Path) -> None:
        result = subprocess.run(
            [str(self.python), "-m", "pip", "install", "--no-deps", str(wheel)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    def run(self, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.conductor), *args],
            check=False,
            capture_output=True,
            text=True,
            cwd=env["HOME"],
            env=env,
        )


@pytest.fixture(scope="session")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    build_root = tmp_path_factory.mktemp("wheel-build")
    source = build_root / "source"
    shutil.copytree(
        PROJECT_ROOT,
        source,
        ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", "*.pyc"),
    )
    wheelhouse = build_root / "wheelhouse"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-build-isolation",
            "--no-deps",
            "--wheel-dir",
            str(wheelhouse),
            str(source),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    wheels = list(wheelhouse.glob("codex_conductor-*.whl"))
    assert len(wheels) == 1
    return wheels[0]


@pytest.fixture
def clean_venv(tmp_path: Path) -> CleanVenv:
    root = tmp_path / "venv"
    result = subprocess.run(
        [sys.executable, "-m", "venv", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return CleanVenv(root)


def isolated_home(path: Path) -> dict[str, str]:
    home = path / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "USERPROFILE": str(home)})
    env.pop("PYTHONPATH", None)
    return env


def test_installed_wheel_contains_operational_assets(
    built_wheel: Path,
    clean_venv: CleanVenv,
    tmp_path: Path,
) -> None:
    clean_venv.pip_install(built_wheel)
    result = clean_venv.run("install", "--dry-run", env=isolated_home(tmp_path))

    assert result.returncode == 0, result.stderr
    assert "FileNotFoundError" not in result.stderr
    assert "conductor.toml" in result.stdout
