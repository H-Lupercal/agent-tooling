import importlib.metadata
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import unittest
import venv
from pathlib import Path

import toolbelt


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary_directory = tempfile.TemporaryDirectory()
        cls.temporary_path = Path(cls._temporary_directory.name)
        cls.dist_path = cls.temporary_path / "dist"
        cls.wheelhouse = cls.temporary_path / "wheelhouse"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--disable-pip-version-check",
                "--only-binary=:all:",
                "--dest",
                str(cls.wheelhouse),
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
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--outdir",
                str(cls.dist_path),
            ],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.wheel = next(cls.dist_path.glob("*.whl"))
        cls.sdist = next(cls.dist_path.glob("*.tar.gz"))

    @classmethod
    def tearDownClass(cls):
        cls._temporary_directory.cleanup()

    def test_public_metadata_and_console_entrypoint(self):
        self.assertEqual(
            toolbelt.__version__,
            importlib.metadata.version("toolbelt-ai"),
        )
        self.assertTrue(callable(toolbelt.main))

    def test_wheel_installs_and_runs_real_console_outside_checkout(self):
        self._assert_artifact_runs(self.wheel, "wheel")

    def test_sdist_installs_and_runs_real_console_outside_checkout(self):
        self._assert_artifact_runs(self.sdist, "sdist")

    def test_ci_installs_and_checks_the_src_layout_package(self):
        workflow = (PROJECT_ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('python -m pip install -e ".[dev]"', workflow)
        self.assertIn("python -m compileall src/toolbelt", workflow)
        self.assertIn("python -m pytest", workflow)
        self.assertNotIn("compileall toolbelt", workflow)

    def test_e2e_smoke_uses_installed_entrypoint_with_src_fallback(self):
        script = (PROJECT_ROOT / "tests/e2e_smoke.sh").read_text(encoding="utf-8")
        self.assertIn("toolbelt_cli=(toolbelt)", script)
        self.assertIn('PYTHONPATH="$repo/src', script)
        self.assertIn("run_toolbelt scan", script)
        self.assertNotIn('export PYTHONPATH="$repo"', script)

    def test_dev_extra_contains_no_isolation_build_backend(self):
        project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text("utf-8"))
        development_dependencies = project["project"]["optional-dependencies"]["dev"]
        self.assertTrue(
            any(
                dependency.startswith("hatchling>=")
                for dependency in development_dependencies
            )
        )

    def test_readme_describes_distribution_and_src_layout_truthfully(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        for stale_claim in (
            "standard library only",
            "no third-party packages",
            "no build step",
            "catalog/catalog.toml",
            "python -m compileall toolbelt",
            "python3 -m py_compile toolbelt/*.py",
        ):
            self.assertNotIn(stale_claim, readme)
        self.assertIn("Pydantic", readme)
        self.assertIn("PathSpec", readme)
        self.assertIn("src/toolbelt/data/catalog.toml", readme)
        self.assertIn('python -m pip install -e ".[dev]"', readme)

    def _assert_artifact_runs(self, artifact: Path, label: str):
        environment_path = self.temporary_path / f"{label}-venv"
        venv.EnvBuilder(with_pip=True).create(environment_path)
        self.assertIn(
            "include-system-site-packages = false",
            (environment_path / "pyvenv.cfg").read_text(encoding="utf-8").lower(),
        )
        scripts = "Scripts" if os.name == "nt" else "bin"
        python = (
            environment_path / scripts / ("python.exe" if os.name == "nt" else "python")
        )
        toolbelt_command = (
            environment_path
            / scripts
            / ("toolbelt.exe" if os.name == "nt" else "toolbelt")
        )
        install_environment = os.environ.copy()
        install_environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_FIND_LINKS": str(self.wheelhouse),
                "PIP_NO_INDEX": "1",
            }
        )
        subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                str(artifact),
            ],
            env=install_environment,
            check=True,
            capture_output=True,
            text=True,
        )

        outside = self.temporary_path / f"{label}-outside"
        repository = outside / "repository"
        repository.mkdir(parents=True)
        (repository / "pyproject.toml").write_text(
            '[project]\nname = "fixture"\nversion = "1.0.0"\ndependencies = ["pytest==8.4.2"]\n',
            encoding="utf-8",
        )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("TOOLBELT_CATALOG", None)
        environment.update(
            {
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "TOOLBELT_CLAUDE_PLUGINS": str(outside / "missing-plugins.json"),
                "TOOLBELT_CLAUDE_STATE": str(outside / "missing-claude.json"),
                "TOOLBELT_CODEX_CONFIG": str(outside / "missing-codex.toml"),
            }
        )

        imported = subprocess.run(
            [
                str(python),
                "-c",
                (
                    "import pathspec, pydantic, toolbelt; "
                    "print(toolbelt.__file__); print(pathspec.__file__); print(pydantic.__file__)"
                ),
            ],
            cwd=outside,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        imported_paths = imported.stdout.splitlines()
        self.assertEqual(len(imported_paths), 3)
        for imported_path in imported_paths:
            self.assertIn(str(environment_path.resolve()), imported_path)

        for command in ("scan", "plan", "status"):
            result = subprocess.run(
                [str(toolbelt_command), command, "--path", str(repository), "--json"],
                cwd=outside,
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.returncode,
                0,
                f"{label} {command} failed:\nstdout={result.stdout}\nstderr={result.stderr}",
            )
            json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
