from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from toolbelt.errors import ValidationError
from toolbelt.migration import migrate_v1_candidate


def test_migrate_v1_writes_disabled_candidate_only(tmp_path: Path) -> None:
    control = tmp_path / ".toolbelt"
    control.mkdir()
    (control / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mode": "existing",
                "tools": {
                    "ruff": {
                        "state": "installed",
                        "catalog_version": "1",
                        "provenance": "pypi:ruff==0.8.6",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    environment = os.environ.copy()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "toolbelt",
            "migrate-v1",
            "--path",
            str(tmp_path),
            "--out",
            "candidate.toml",
            "--json",
        ],
        cwd=tmp_path,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    candidate = tomllib.loads((tmp_path / "candidate.toml").read_text(encoding="utf-8"))
    assert candidate["enabled"] is False
    assert candidate["source_schema_version"] == 1
    assert candidate["candidate"][0]["tool_id"] == "ruff"
    assert not (control / "state.sqlite3").exists()


def test_migration_rejects_missing_invalid_and_wrong_schema_sources(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="not found"):
        migrate_v1_candidate(tmp_path, "candidate.toml")

    control = tmp_path / ".toolbelt"
    control.mkdir()
    source = control / "manifest.json"
    source.write_text("not json", encoding="utf-8")
    with pytest.raises(ValidationError, match="invalid v1"):
        migrate_v1_candidate(tmp_path, "candidate.toml")

    source.write_text('{"schema_version": 2}', encoding="utf-8")
    with pytest.raises(ValidationError, match="schema_version 1"):
        migrate_v1_candidate(tmp_path, "candidate.toml")


def test_migration_rejects_bad_tool_shape_and_output_escape(tmp_path: Path) -> None:
    control = tmp_path / ".toolbelt"
    control.mkdir()
    source = control / "manifest.json"
    source.write_text('{"schema_version": 1, "tools": []}', encoding="utf-8")
    with pytest.raises(ValidationError, match="tools must be an object"):
        migrate_v1_candidate(tmp_path, "candidate.toml")

    source.write_text('{"schema_version": 1, "tools": {"ruff": "bad"}}', encoding="utf-8")
    with pytest.raises(ValidationError, match="named objects"):
        migrate_v1_candidate(tmp_path, "candidate.toml")

    source.write_text('{"schema_version": 1, "tools": {}}', encoding="utf-8")
    with pytest.raises(ValidationError, match="inside the repository"):
        migrate_v1_candidate(tmp_path, tmp_path.parent / "outside.toml")
