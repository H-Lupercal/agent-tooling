from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolbelt.scanner import scan_repository


def test_supported_manifests_collect_dependencies_and_test_configuration(
    tmp_path: Path,
) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "dependencies": {"react": "19.0.0"},
                "devDependencies": {"vitest": "2.0.0"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["pytest>=8", "pydantic>=2"]
[tool.pytest.ini_options]
testpaths = ["tests"]
[tool.poetry.dependencies]
python = ">=3.11"
httpx = "^0.28"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "requirements.txt").write_text(
        "# comment\nruff==0.8.6\n-r base.txt\n",
        encoding="utf-8",
    )
    (tmp_path / "Cargo.toml").write_text('[dependencies]\nserde = "1"\n', encoding="utf-8")
    (tmp_path / "go.mod").write_text(
        """
module example.test/demo
require example.test/one v1.0.0
require (
  example.test/two v2.0.0
  // ignored
)
""".lstrip(),
        encoding="utf-8",
    )

    result = scan_repository(tmp_path)
    dependencies = {item.key for item in result if item.type == "dependency"}

    assert dependencies >= {
        "react",
        "vitest",
        "pytest",
        "pydantic",
        "httpx",
        "ruff",
        "serde",
        "example.test-one",
        "example.test-two",
    }
    assert any(item.type == "test" and item.key == "pytest" for item in result)
    assert not result.warnings


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("package.json", "[]"),
        ("pyproject.toml", "project = [1]"),
        ("Cargo.toml", "dependencies = [1]"),
    ],
)
def test_wrong_manifest_shapes_are_warnings_not_crashes(
    tmp_path: Path, name: str, content: str
) -> None:
    (tmp_path / name).write_text(content, encoding="utf-8")

    result = scan_repository(tmp_path)

    assert any(
        warning.code == "parse_error" and warning.source == name for warning in result.warnings
    )


def test_infrastructure_and_test_config_detection(tmp_path: Path) -> None:
    (tmp_path / ".github/workflows").mkdir(parents=True)
    (tmp_path / ".github/workflows/ci.yaml").write_text("name: ci\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  db:\n    image: postgres:17\n", encoding="utf-8"
    )
    (tmp_path / "playwright.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "vitest.config.ts").write_text("export default {}\n", encoding="utf-8")
    (tmp_path / "main.tf").write_text('resource "x" "y" {}\n', encoding="utf-8")

    keys = {(item.type, item.key) for item in scan_repository(tmp_path)}

    assert keys >= {
        ("infra", "github_actions"),
        ("infra", "compose"),
        ("infra", "postgres"),
        ("infra", "terraform"),
        ("test", "playwright"),
        ("test", "vitest"),
    }
