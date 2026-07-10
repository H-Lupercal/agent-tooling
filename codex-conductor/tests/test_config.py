from __future__ import annotations

import math
from pathlib import Path

import pytest
from pydantic import ValidationError

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
            "strictly decreasing",
        ),
    ],
)
def test_tier_integrity_constraints(mutate, message: str) -> None:
    from conductor.schemas import ConductorConfig

    payload = valid_config()
    mutate(payload)
    with pytest.raises(ValidationError, match=message):
        ConductorConfig.model_validate(payload)
