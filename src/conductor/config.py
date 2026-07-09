from __future__ import annotations

import hashlib
import json
import math
import os
import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from conductor.errors import ConfigError
from conductor.schemas import HIGH_RISK_TRIGGERS as HIGH_RISK_TRIGGERS
from conductor.schemas import TASK_CLASSES as TASK_CLASSES
from conductor.schemas import BudgetConfig, ConductorConfig, PolicyConfig, TierConfig


Budget = BudgetConfig
Policy = PolicyConfig
Tier = TierConfig
Ladder = ConductorConfig


def conductor_home() -> Path:
    return Path(
        os.environ.get("CODEX_CONDUCTOR_HOME", Path.home() / ".codex" / "conductor")
    ).expanduser()


def provider_home(provider: str) -> Path:
    """Canonical conductor home for a provider."""
    root = ".claude" if provider == "claude" else ".codex"
    return Path.home() / root / "conductor"


def default_config_path() -> Path:
    env = os.environ.get("CODEX_CONDUCTOR_CONFIG")
    if env:
        return Path(env).expanduser()
    installed = conductor_home() / "conductor.toml"
    if installed.exists():
        return installed
    return Path(str(files("conductor.assets").joinpath("config", "conductor.toml")))


def models_cache_path() -> Path:
    return Path(
        os.environ.get(
            "CODEX_MODELS_CACHE", Path.home() / ".codex" / "models_cache.json"
        )
    ).expanduser()


def load_config(path: Path | None = None) -> ConductorConfig:
    config_path = Path(path) if path is not None else default_config_path()
    try:
        with config_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot load conductor config {config_path}: {exc}") from exc

    override = os.environ.get("CONDUCTOR_RUN_USD_CAP")
    if override is not None:
        try:
            cap = float(override)
        except ValueError as exc:
            raise ConfigError(
                "CONDUCTOR_RUN_USD_CAP must be a finite positive number"
            ) from exc
        if not math.isfinite(cap) or cap <= 0:
            raise ConfigError("CONDUCTOR_RUN_USD_CAP must be a finite positive number")
        budget = data.get("budget")
        if not isinstance(budget, dict):
            raise ConfigError(
                "budget must be a table before applying CONDUCTOR_RUN_USD_CAP"
            )
        data = {**data, "budget": {**budget, "run_usd_cap": cap}}

    try:
        return ConductorConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"invalid conductor config {config_path}: {exc}") from exc


def load_ladder(path: Path | None = None) -> Ladder:
    return load_config(path)


def enabled_tiers(ladder: Ladder, models_cache_path: Path) -> list[int]:
    available = _available_model_slugs(models_cache_path)
    enabled: list[int] = []
    for index, tier in enumerate(ladder.tiers):
        if tier.enabled == "always":
            enabled.append(index)
        elif tier.enabled == "auto" and tier.model in available:
            enabled.append(index)
    return enabled


def _available_model_slugs(path: Path) -> set[str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    models = data.get("models", []) if isinstance(data, dict) else []
    slugs: set[str] = set()
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("slug"), str):
                slugs.add(item["slug"])
    return slugs


def with_budget(ladder: Ladder, cap: float) -> Ladder:
    payload = ladder.model_dump(mode="python")
    payload["budget"]["run_usd_cap"] = cap
    return ConductorConfig.model_validate(payload)


def config_digest(config: ConductorConfig) -> str:
    payload = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
