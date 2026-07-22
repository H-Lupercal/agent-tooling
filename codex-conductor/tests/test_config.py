from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

import conductor.config as config_module
from conductor.errors import ConfigError
from tests.helpers import restore_env, set_env, write_config, write_models_cache
from tests.test_schemas import deep_merge, valid_config


def test_valid_config_loads_and_auto_tiers_follow_models_cache(tmp_path: Path) -> None:
    from conductor.config import enabled_tiers, load_config

    config_path = write_config(tmp_path / "conductor.toml")
    models = write_models_cache(
        tmp_path / "models.json",
        ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"],
    )

    config = load_config(config_path)

    assert [tier.name for tier in config.tiers] == [
        "frontier",
        "standard",
        "mini",
        "spark",
    ]
    assert enabled_tiers(config, models) == [0, 1, 2]


def test_environment_budget_override_is_validated_strictly(tmp_path: Path) -> None:
    from conductor.config import ConfigError, load_config

    config_path = write_config(tmp_path / "conductor.toml")
    old = set_env(CONDUCTOR_RUN_USD_CAP="1.25")
    try:
        assert load_config(config_path).budget.run_usd_cap == 1.25
    finally:
        restore_env(old)

    old = set_env(CONDUCTOR_RUN_USD_CAP="nan")
    try:
        with pytest.raises(ConfigError, match="CONDUCTOR_RUN_USD_CAP"):
            load_config(config_path)
    finally:
        restore_env(old)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 99},
        {"budget": {"run_usd_cap": float("nan")}},
        {"budget": {"run_usd_cap": math.inf}},
        {"budget": {"warn_at_fraction": 1.5}},
        {"budget": {"enforce": 1}},
        {"policy": {"max_depth": -1}},
        {"unknown": True},
    ],
)
def test_invalid_config_is_rejected(change: dict[str, object]) -> None:
    from conductor.schemas import ConductorConfig

    with pytest.raises(ValidationError):
        ConductorConfig.model_validate(deep_merge(valid_config(), change))


def test_task_classes_form_exact_partition() -> None:
    from conductor.schemas import ConductorConfig

    duplicate = valid_config()
    duplicate["tiers"][1]["task_classes"].append("architecture")
    with pytest.raises(ValidationError, match="task class ownership"):
        ConductorConfig.model_validate(duplicate)

    missing = valid_config()
    missing["tiers"][0]["task_classes"].remove("architecture")
    with pytest.raises(ValidationError, match="task class ownership"):
        ConductorConfig.model_validate(missing)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda config: config["tiers"][1].update(name="frontier"),
            "unique tier names",
        ),
        (lambda config: config["tiers"][1].update(model="gpt-5.5"), "unique models"),
        (
            lambda config: config["tiers"][1].update(relative_cost_weight=101),
            "non-increasing",
        ),
    ],
)
def test_tier_integrity_constraints(mutate, message: str) -> None:
    from conductor.schemas import ConductorConfig

    payload = valid_config()
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        ConductorConfig.model_validate(payload)


def test_equal_cost_models_are_valid_but_cost_may_not_increase() -> None:
    from conductor.schemas import ConductorConfig

    tied = valid_config()
    tied["tiers"][1]["relative_cost_weight"] = tied["tiers"][0]["relative_cost_weight"]
    assert ConductorConfig.model_validate(tied)

    increasing = valid_config()
    increasing["tiers"][1]["relative_cost_weight"] = (
        increasing["tiers"][0]["relative_cost_weight"] + 1
    )
    with pytest.raises(ValidationError, match="non-increasing"):
        ConductorConfig.model_validate(increasing)


def test_config_paths_honor_environment_install_and_package_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured.toml"
    monkeypatch.setenv("CODEX_CONDUCTOR_CONFIG", str(configured))
    assert config_module.default_config_path() == configured

    monkeypatch.delenv("CODEX_CONDUCTOR_CONFIG")
    home = tmp_path / "home"
    installed = home / "conductor.toml"
    installed.parent.mkdir(parents=True)
    installed.write_text("schema_version = 2\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "conductor_home", lambda: home)
    assert config_module.default_config_path() == installed

    installed.unlink()
    fallback = config_module.default_config_path()
    assert fallback.name == "conductor.toml"
    assert fallback.is_file()

    cache = tmp_path / "models.json"
    monkeypatch.setenv("CODEX_MODELS_CACHE", str(cache))
    assert config_module.models_cache_path() == cache
    assert config_module.provider_home("claude").parts[-2:] == (".claude", "conductor")


def test_load_config_reports_io_toml_override_and_schema_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ConfigError, match="cannot load conductor config"):
        config_module.load_config(tmp_path / "missing.toml")

    invalid_toml = tmp_path / "invalid.toml"
    invalid_toml.write_text("not = [valid", encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot load conductor config"):
        config_module.load_config(invalid_toml)

    config_path = write_config(tmp_path / "conductor.toml")
    monkeypatch.setenv("CONDUCTOR_RUN_USD_CAP", "not-a-number")
    with pytest.raises(ConfigError, match="finite positive"):
        config_module.load_config(config_path)

    no_budget = tmp_path / "no-budget.toml"
    no_budget.write_text("schema_version = 2\n", encoding="utf-8")
    monkeypatch.setenv("CONDUCTOR_RUN_USD_CAP", "1.0")
    with pytest.raises(ConfigError, match="budget must be a table"):
        config_module.load_config(no_budget)

    monkeypatch.delenv("CONDUCTOR_RUN_USD_CAP")
    invalid_schema = tmp_path / "invalid-schema.toml"
    invalid_schema.write_text("schema_version = 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid conductor config"):
        config_module.load_config(invalid_schema)


def test_models_cache_filtering_and_budget_copy_are_deterministic(
    tmp_path: Path,
) -> None:
    config = config_module.load_config(write_config(tmp_path / "conductor.toml"))
    missing = tmp_path / "missing.json"
    assert config_module.enabled_tiers(config, missing) == [0, 1]

    malformed = tmp_path / "malformed.json"
    malformed.write_text("[]", encoding="utf-8")
    assert config_module.enabled_tiers(config, malformed) == [0, 1]

    mixed = tmp_path / "mixed.json"
    mixed.write_text(
        '{"models": [null, {"slug": 1}, {"slug": "gpt-5.4-mini"}]}',
        encoding="utf-8",
    )
    assert config_module.enabled_tiers(config, mixed) == [0, 1, 2]

    changed = config_module.with_budget(config, 3.5)
    assert changed.budget.run_usd_cap == 3.5
    assert config.budget.run_usd_cap != changed.budget.run_usd_cap


def test_packaged_claude_ladder_declares_model_authority_ranks() -> None:
    # Model-led Claude routing requires explicit generation/capability ranks so
    # cross-model spawns are evaluated instead of failing UNKNOWN_MODEL_AUTHORITY.
    from tests.helpers import PROJECT_ROOT

    claude_config = (
        PROJECT_ROOT
        / "src"
        / "conductor"
        / "assets"
        / "config"
        / "conductor.claude.toml"
    )
    config = config_module.load_config(claude_config)
    ranks = {
        tier.model: (tier.generation_rank, tier.capability_rank)
        for tier in config.tiers
    }
    assert ranks == {
        "claude-opus-4-8": (48, 100),
        "claude-sonnet-5": (48, 25),
        "claude-haiku-4-5": (48, 6),
    }
