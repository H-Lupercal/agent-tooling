from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.distribution


@dataclass(frozen=True)
class BuiltArtifacts:
    wheel: Path
    sdist: Path
    wheelhouse: Path | None


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

    def pip_install(self, artifact: Path, wheelhouse: Path | None) -> None:
        uv = shutil.which("uv")
        if uv is not None:
            result = subprocess.run(
                [
                    uv,
                    "pip",
                    "install",
                    "--offline",
                    "--link-mode=copy",
                    "--python",
                    str(self.python),
                    str(artifact),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, result.stderr
            return
        assert wheelhouse is not None
        environment = os.environ.copy()
        environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_FIND_LINKS": str(wheelhouse),
                "PIP_NO_INDEX": "1",
            }
        )
        result = subprocess.run(
            [str(self.python), "-m", "pip", "install", str(artifact)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
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
def built_artifacts(tmp_path_factory: pytest.TempPathFactory) -> BuiltArtifacts:
    build_root = tmp_path_factory.mktemp("distribution-build")
    source = build_root / "source"
    shutil.copytree(
        PROJECT_ROOT,
        source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".coverage*",
            ".hypothesis",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "*.egg-info",
            "*.pyc",
            "__pycache__",
            "build",
            "dist",
        ),
    )
    wheelhouse: Path | None = None
    if shutil.which("uv") is None:
        wheelhouse = build_root / "wheelhouse"
        wheelhouse.mkdir()
        downloaded = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--dest",
                str(wheelhouse),
                "hatchling>=1.25,<2",
                "pydantic>=2.8,<3",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert downloaded.returncode == 0, downloaded.stderr
    distributions = build_root / "dist"
    built = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--no-isolation",
            "--outdir",
            str(distributions),
        ],
        cwd=source,
        check=False,
        capture_output=True,
        text=True,
    )
    assert built.returncode == 0, built.stderr
    wheels = list(distributions.glob("codex_conductor-*.whl"))
    sdists = list(distributions.glob("codex_conductor-*.tar.gz"))
    assert len(wheels) == 1
    assert len(sdists) == 1
    return BuiltArtifacts(wheels[0], sdists[0], wheelhouse)


@pytest.fixture(scope="session")
def built_wheel(built_artifacts: BuiltArtifacts) -> Path:
    return built_artifacts.wheel


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


@pytest.mark.parametrize(
    ("provider_args", "asset_marker"),
    [
        ((), "gpt-5.5"),
        (("--provider", "claude"), "claude-opus-4-8"),
    ],
)
def test_installed_wheel_contains_operational_assets(
    built_artifacts: BuiltArtifacts,
    built_wheel: Path,
    clean_venv: CleanVenv,
    tmp_path: Path,
    provider_args: tuple[str, ...],
    asset_marker: str,
) -> None:
    clean_venv.pip_install(built_wheel, built_artifacts.wheelhouse)
    result = clean_venv.run(
        "install",
        "--dry-run",
        *provider_args,
        env=isolated_home(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert "FileNotFoundError" not in result.stderr
    assert "conductor.toml" in result.stdout
    assert asset_marker in result.stdout
    assert "conductor status" in result.stdout
    assert "conductor report" in result.stdout
    assert "python3 -m conductor." not in result.stdout


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_release_artifact_installs_and_runs_outside_the_checkout(
    built_artifacts: BuiltArtifacts,
    clean_venv: CleanVenv,
    tmp_path: Path,
    kind: str,
) -> None:
    artifact = getattr(built_artifacts, kind)
    clean_venv.pip_install(artifact, built_artifacts.wheelhouse)
    environment = isolated_home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    imported = subprocess.run(
        [
            str(clean_venv.python),
            "-c",
            (
                "import importlib.resources, pydantic, conductor; "
                "print(conductor.__version__); "
                "print(importlib.resources.files('conductor.assets').joinpath('contracts/codex-current.json').is_file())"
            ),
        ],
        cwd=outside,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert imported.returncode == 0, imported.stderr
    assert imported.stdout.splitlines() == ["2.0.0", "True"]

    installed = clean_venv.run("install", env=environment)
    assert installed.returncode == 0, installed.stderr
    doctor = clean_venv.run("doctor", env=environment)
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert "policy_canary" in doctor.stdout
    uninstalled = clean_venv.run("uninstall", env=environment)
    assert uninstalled.returncode == 0, uninstalled.stderr
    assert not (Path(environment["HOME"]) / ".codex" / "hooks.json").exists()


def test_checkout_launch_paths_use_the_installed_console_entrypoint() -> None:
    launchers = {
        "install.sh": "conductor install",
        "uninstall.sh": "conductor uninstall",
        "install.ps1": "conductor install",
        "uninstall.ps1": "conductor uninstall",
    }
    for relative_path, command in launchers.items():
        text = (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        assert command in text
        assert "-m conductor.install" not in text

    readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    assert "PYTHONPATH=" not in readme
    assert "pip install -e '.[dev]'" in readme
    assert "config/conductor.toml" not in readme
    assert "compileall conductor" not in readme
    assert "compileall src/conductor" in readme
