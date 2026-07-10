from __future__ import annotations

from pathlib import Path

import pytest

from conductor.errors import InstallationConflictError
from conductor.legacy import build_v2_candidate, migrate_v1
from tests.helpers import FIXTURES


def _v1_config() -> str:
    return (FIXTURES / "v1-conductor.toml").read_text(encoding="utf-8")


def test_v1_migration_creates_valid_offline_candidate_without_mutating_source(
    tmp_path: Path,
) -> None:
    from conductor.config import load_config

    source = tmp_path / "v1.toml"
    source.write_text(_v1_config(), encoding="utf-8")
    before = source.read_bytes()
    destination = tmp_path / "candidate.toml"

    migrate_v1(source, destination)

    assert source.read_bytes() == before
    assert "REVIEW BEFORE ACTIVATION" in destination.read_text(encoding="utf-8")
    assert load_config(destination).schema_version == 2


def test_migration_refuses_existing_destination_and_unknown_v1_fields(
    tmp_path: Path,
) -> None:
    source = tmp_path / "v1.toml"
    source.write_text(_v1_config(), encoding="utf-8")
    destination = tmp_path / "candidate.toml"
    destination.write_text("keep\n", encoding="utf-8")

    with pytest.raises(InstallationConflictError):
        migrate_v1(source, destination)
    assert destination.read_text(encoding="utf-8") == "keep\n"

    source.write_text(
        _v1_config().replace('name = "frontier"', 'name = "frontier"\nunsafe = true'),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="unknown keys"):
        build_v2_candidate(source)


@pytest.mark.parametrize(
    ("value", "helper"),
    [
        (None, "_string"),
        (["ok", 1], "_string_list"),
        (True, "_number"),
        (1.5, "_integer"),
        (1, "_boolean"),
    ],
)
def test_v1_renderer_rejects_implicit_type_coercion(value: object, helper: str) -> None:
    import conductor.legacy as legacy
    from conductor.errors import ConfigError

    with pytest.raises(ConfigError):
        getattr(legacy, helper)(value)


def test_migration_cli_and_invalid_sources_are_controlled(
    tmp_path: Path,
) -> None:
    import conductor.legacy as legacy
    from conductor.errors import ConfigError

    missing = tmp_path / "missing.toml"
    with pytest.raises(ConfigError):
        build_v2_candidate(missing)
    wrong = tmp_path / "wrong.toml"
    wrong.write_text("schema_version = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="schema_version=1"):
        build_v2_candidate(wrong)

    source = tmp_path / "v1.toml"
    source.write_text(_v1_config(), encoding="utf-8")
    destination = tmp_path / "candidate.toml"
    assert legacy.main([str(source), str(destination)]) == 0
    assert destination.exists()
