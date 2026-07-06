from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path


TASK_CLASSES = (
    "architecture",
    "high_risk",
    "integration",
    "review_gate",
    "implementation",
    "refactor",
    "debug",
    "cross_module_change",
    "tests",
    "docs",
    "mechanical_edit",
    "rename",
    "config_change",
    "search",
    "summarize",
    "boilerplate",
    "formatting",
    "data_extraction",
)

HIGH_RISK_TRIGGERS = (
    "authentication/authorization",
    "cryptography",
    "payments/billing",
    "database schema migration",
    "deleting or rewriting more than 200 lines",
    "public API contract change",
    "concurrency/locking",
    "build or release pipeline change",
    "security-sensitive input parsing",
    "secrets handling",
    "production configuration",
)


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Tier:
    name: str
    model: str
    reasoning_effort: str
    enabled: str
    input_usd_per_mtok: float
    cached_input_usd_per_mtok: float
    output_usd_per_mtok: float
    relative_cost_weight: int
    est_task_usd: float
    max_concurrent: int
    may_spawn: bool
    task_classes: tuple[str, ...]


@dataclass(frozen=True)
class Budget:
    run_usd_cap: float
    warn_at_fraction: float
    enforce: bool


@dataclass(frozen=True)
class Policy:
    max_depth: int
    require_strictly_cheaper: bool
    same_tier_spawns_from_root_max: int
    retry_same_tier_max: int


@dataclass(frozen=True)
class Ladder:
    budget: Budget
    policy: Policy
    tiers: tuple[Tier, ...]

    def tier_index_for_model(self, model: str) -> int | None:
        for index, tier in enumerate(self.tiers):
            if tier.model == model:
                return index
        return None

    def tier_for_model(self, model: str) -> Tier | None:
        index = self.tier_index_for_model(model)
        if index is None:
            return None
        return self.tiers[index]

    def tier_for_class(self, task_class: str) -> Tier | None:
        for tier in self.tiers:
            if task_class in tier.task_classes:
                return tier
        return None


def conductor_home() -> Path:
    return Path(os.environ.get("CODEX_CONDUCTOR_HOME", Path.home() / ".codex" / "conductor")).expanduser()


def default_config_path() -> Path:
    env = os.environ.get("CODEX_CONDUCTOR_CONFIG")
    if env:
        return Path(env).expanduser()
    installed = conductor_home() / "conductor.toml"
    if installed.exists():
        return installed
    return Path(__file__).resolve().parents[1] / "config" / "conductor.toml"


def models_cache_path() -> Path:
    return Path(os.environ.get("CODEX_MODELS_CACHE", Path.home() / ".codex" / "models_cache.json")).expanduser()


def load_ladder(path: Path | None = None) -> Ladder:
    config_path = Path(path) if path is not None else default_config_path()
    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    budget_data = data.get("budget", {})
    budget = Budget(
        run_usd_cap=float(os.environ.get("CONDUCTOR_RUN_USD_CAP", budget_data.get("run_usd_cap", 10.0))),
        warn_at_fraction=float(budget_data.get("warn_at_fraction", 0.75)),
        enforce=bool(budget_data.get("enforce", True)),
    )
    policy_data = data.get("policy", {})
    policy = Policy(
        max_depth=int(policy_data.get("max_depth", 3)),
        require_strictly_cheaper=bool(policy_data.get("require_strictly_cheaper", True)),
        same_tier_spawns_from_root_max=int(policy_data.get("same_tier_spawns_from_root_max", 2)),
        retry_same_tier_max=int(policy_data.get("retry_same_tier_max", 1)),
    )
    tiers = tuple(_tier_from_dict(raw) for raw in data.get("tier", []))
    ladder = Ladder(budget=budget, policy=policy, tiers=tiers)
    _validate(ladder)
    return ladder


def _tier_from_dict(raw: dict) -> Tier:
    return Tier(
        name=str(raw["name"]),
        model=str(raw["model"]),
        reasoning_effort=str(raw.get("reasoning_effort", "medium")),
        enabled=str(raw.get("enabled", "always")),
        input_usd_per_mtok=float(raw.get("input_usd_per_mtok", 0.0)),
        cached_input_usd_per_mtok=float(raw.get("cached_input_usd_per_mtok", 0.0)),
        output_usd_per_mtok=float(raw.get("output_usd_per_mtok", 0.0)),
        relative_cost_weight=int(raw.get("relative_cost_weight", 1)),
        est_task_usd=float(raw.get("est_task_usd", 0.0)),
        max_concurrent=int(raw.get("max_concurrent", 1)),
        may_spawn=bool(raw.get("may_spawn", True)),
        task_classes=tuple(str(item) for item in raw.get("task_classes", ())),
    )


def _validate(ladder: Ladder) -> None:
    seen_names: set[str] = set()
    seen_models: set[str] = set()
    assigned: dict[str, str] = {}
    if ladder.budget.run_usd_cap <= 0:
        raise ConfigError("budget.run_usd_cap must be > 0")
    if not 1 <= ladder.policy.max_depth <= 5:
        raise ConfigError("policy.max_depth must be in 1..5")
    for tier in ladder.tiers:
        if tier.name in seen_names:
            raise ConfigError(f"duplicate tier name: {tier.name}")
        seen_names.add(tier.name)
        if tier.model in seen_models:
            raise ConfigError(f"duplicate model: {tier.model}")
        seen_models.add(tier.model)
        if tier.enabled not in {"always", "auto", "never"}:
            raise ConfigError(f"tier {tier.name}: enabled must be always|auto|never")
        if tier.max_concurrent < 1:
            raise ConfigError(f"tier {tier.name}: max_concurrent must be >= 1")
        if min(tier.input_usd_per_mtok, tier.cached_input_usd_per_mtok, tier.output_usd_per_mtok, tier.est_task_usd) < 0:
            raise ConfigError(f"tier {tier.name}: negative price")
        for task_class in tier.task_classes:
            if task_class not in TASK_CLASSES:
                raise ConfigError(f"unknown task class: {task_class}")
            if task_class in assigned:
                raise ConfigError(f"task class {task_class} assigned to multiple tiers: {assigned[task_class]}, {tier.name}")
            assigned[task_class] = tier.name
    if not any(tier.enabled != "never" for tier in ladder.tiers):
        raise ConfigError("at least one tier must be enabled")


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
    models = data.get("models", [])
    slugs: set[str] = set()
    if isinstance(models, list):
        for item in models:
            if isinstance(item, dict) and isinstance(item.get("slug"), str):
                slugs.add(item["slug"])
    return slugs


def with_budget(ladder: Ladder, cap: float) -> Ladder:
    return replace(ladder, budget=replace(ladder.budget, run_usd_cap=cap))
