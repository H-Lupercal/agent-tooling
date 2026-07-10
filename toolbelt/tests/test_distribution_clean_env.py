from __future__ import annotations

import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

import pytest

import toolbelt
from toolbelt.cli import main

pytestmark = pytest.mark.distribution
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def artifacts() -> tuple[Path, Path, Path]:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        dist = root / "dist"
        wheelhouse = root / "wheelhouse"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--dest",
                str(wheelhouse),
                "hatchling>=1.25",
                "pathspec>=0.12,<1",
                "pydantic>=2.8,<3",
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(dist)],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [sys.executable, "-m", "twine", "check", *map(str, dist.iterdir())],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        yield next(dist.glob("*.whl")), next(dist.glob("*.tar.gz")), wheelhouse


def test_public_metadata_and_console_entrypoint() -> None:
    assert toolbelt.__version__ == importlib.metadata.version("toolbelt-ai")
    assert callable(main)


def test_wheel_contains_v2_catalog_and_no_legacy_catalog(
    artifacts: tuple[Path, Path, Path],
) -> None:
    wheel, _, _ = artifacts
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        assert "toolbelt/data/catalog.toml" in names
        assert "toolbelt/data/catalog-v1.toml" not in names
        for name in names:
            if name.endswith((".py", ".toml", ".md")):
                assert b"/home/neil" not in archive.read(name)


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
def test_artifact_installs_and_runs_outside_checkout(
    artifacts: tuple[Path, Path, Path], kind: str
) -> None:
    wheel, sdist, wheelhouse = artifacts
    artifact = wheel if kind == "wheel" else sdist
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        environment_path = root / "venv"
        venv.EnvBuilder(with_pip=True).create(environment_path)
        assert (
            "include-system-site-packages = false"
            in (environment_path / "pyvenv.cfg").read_text(encoding="utf-8").lower()
        )
        scripts = "Scripts" if os.name == "nt" else "bin"
        python = environment_path / scripts / ("python.exe" if os.name == "nt" else "python")
        command = environment_path / scripts / ("toolbelt.exe" if os.name == "nt" else "toolbelt")
        install_environment = os.environ.copy()
        install_environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_FIND_LINKS": str(wheelhouse),
                "PIP_NO_INDEX": "1",
            }
        )
        subprocess.run(
            [str(python), "-m", "pip", "install", str(artifact)],
            env=install_environment,
            check=True,
            capture_output=True,
            text=True,
        )
        outside = root / "outside"
        repository = outside / "repository"
        repository.mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "1.0.0"\ndependencies = ["pytest"]\n',
            encoding="utf-8",
        )
        capabilities = outside / "capabilities.json"
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
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        imported = subprocess.run(
            [str(python), "-c", "import toolbelt; print(toolbelt.__file__)"],
            cwd=outside,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        assert str(environment_path.resolve()) in imported.stdout

        checks = (
            ("doctor", "--strict", "--json"),
            ("scan", "--path", str(repository), "--json"),
            (
                "plan",
                "--path",
                str(repository),
                "--capabilities",
                str(capabilities),
                "--allow-network",
                "--out",
                ".toolbelt/plan.json",
                "--json",
            ),
            (
                "apply",
                "--path",
                str(repository),
                "--capabilities",
                str(capabilities),
                "--allow-network",
                "--plan",
                str(repository / ".toolbelt" / "plan.json"),
                "--dry-run",
                "--json",
            ),
            ("status", "--path", str(repository), "--json"),
        )
        for arguments in checks:
            result = subprocess.run(
                [str(command), *arguments],
                cwd=outside,
                env=environment,
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, (
                f"{kind} {' '.join(arguments)} failed:\n"
                f"stdout={result.stdout}\nstderr={result.stderr}"
            )
            payload = json.loads(result.stdout)
            assert payload["schema_version"] == 2
