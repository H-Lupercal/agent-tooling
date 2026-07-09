from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path


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
