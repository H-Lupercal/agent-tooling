import json
import os
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


DEFAULT_CONFIG = textwrap.dedent(
    """
    schema_version = 1

    [budget]
    run_usd_cap = 10.00
    warn_at_fraction = 0.75
    enforce = true

    [policy]
    max_depth = 3
    require_strictly_cheaper = true
    same_tier_spawns_from_root_max = 2

    [[tier]]
    name = "frontier"
    model = "gpt-5.5"
    reasoning_effort = "high"
    enabled = "always"
    input_usd_per_mtok = 10.0
    cached_input_usd_per_mtok = 1.0
    output_usd_per_mtok = 30.0
    relative_cost_weight = 100
    est_task_usd = 2.00
    max_concurrent = 2
    may_spawn = true
    task_classes = ["architecture", "high_risk", "integration", "review_gate"]

    [[tier]]
    name = "standard"
    model = "gpt-5.4"
    reasoning_effort = "medium"
    enabled = "always"
    input_usd_per_mtok = 2.0
    cached_input_usd_per_mtok = 0.2
    output_usd_per_mtok = 6.0
    relative_cost_weight = 25
    est_task_usd = 0.60
    max_concurrent = 4
    may_spawn = true
    task_classes = ["implementation", "refactor", "debug", "cross_module_change"]

    [[tier]]
    name = "mini"
    model = "gpt-5.4-mini"
    reasoning_effort = "medium"
    enabled = "auto"
    input_usd_per_mtok = 0.5
    cached_input_usd_per_mtok = 0.05
    output_usd_per_mtok = 1.5
    relative_cost_weight = 6
    est_task_usd = 0.15
    max_concurrent = 6
    may_spawn = true
    task_classes = ["tests", "docs", "mechanical_edit", "rename", "config_change"]

    [[tier]]
    name = "spark"
    model = "gpt-5.3-codex-spark"
    reasoning_effort = "low"
    enabled = "auto"
    input_usd_per_mtok = 0.2
    cached_input_usd_per_mtok = 0.02
    output_usd_per_mtok = 0.6
    relative_cost_weight = 2
    est_task_usd = 0.05
    max_concurrent = 8
    may_spawn = false
    task_classes = ["search", "summarize", "boilerplate", "formatting", "data_extraction"]
    """
).strip()


def write_config(path: Path, text: str = DEFAULT_CONFIG) -> Path:
    path.write_text(text + "\n", encoding="utf-8")
    return path


def write_models_cache(path: Path, slugs: list[str]) -> Path:
    path.write_text(
        json.dumps({"models": [{"slug": slug} for slug in slugs]}),
        encoding="utf-8",
    )
    return path


def set_env(**values: str):
    old = {key: os.environ.get(key) for key in values}
    os.environ.update({key: str(value) for key, value in values.items()})
    return old


def restore_env(old: dict[str, str | None]) -> None:
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
