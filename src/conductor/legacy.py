from __future__ import annotations

import argparse
import os
import tempfile
import tomllib
from pathlib import Path

from conductor.errors import ConfigError, InstallationConflictError
from conductor.schemas import ConductorConfig

_TIER_KEYS = {
    "name",
    "model",
    "reasoning_effort",
    "enabled",
    "input_usd_per_mtok",
    "cached_input_usd_per_mtok",
    "output_usd_per_mtok",
    "relative_cost_weight",
    "est_task_usd",
    "max_concurrent",
    "may_spawn",
    "task_classes",
}


def build_v2_candidate(source: Path) -> str:
    try:
        raw = tomllib.loads(Path(source).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read v1 config {source}: {exc}") from exc
    if raw.get("schema_version") != 1:
        raise ConfigError("source must be a schema_version=1 conductor config")
    budget = raw.get("budget")
    policy = raw.get("policy")
    tiers = raw.get("tier")
    if not isinstance(budget, dict) or not isinstance(policy, dict):
        raise ConfigError("v1 budget and policy tables are required")
    if not isinstance(tiers, list) or not tiers:
        raise ConfigError("v1 config must contain at least one [[tier]]")
    lines = [
        "# Generated offline from a v1 config. REVIEW BEFORE ACTIVATION.",
        "# This candidate is not installed or selected automatically.",
        "schema_version = 2",
        "",
        "[budget]",
        f"run_usd_cap = {_number(budget.get('run_usd_cap'))}",
        f"warn_at_fraction = {_number(budget.get('warn_at_fraction'))}",
        f"enforce = {_boolean(budget.get('enforce'))}",
        "",
        "[policy]",
        f"max_depth = {_integer(policy.get('max_depth'))}",
        f"require_strictly_cheaper = {_boolean(policy.get('require_strictly_cheaper'))}",
        f"same_tier_spawns_from_root_max = {_integer(policy.get('same_tier_spawns_from_root_max'))}",
        'minimum_mode = "admission"',
        'unknown_identity = "deny"',
        'unknown_model = "deny"',
        "reservation_ttl_seconds = 300",
        "busy_timeout_ms = 1000",
    ]
    for index, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            raise ConfigError(f"v1 tier {index} must be a table")
        unknown = sorted(set(tier) - _TIER_KEYS)
        if unknown:
            raise ConfigError(f"v1 tier {index} has unknown keys: {unknown}")
        lines.extend(
            [
                "",
                "[[tiers]]",
                f"name = {_string(tier.get('name'))}",
                f"model = {_string(tier.get('model'))}",
                f"reasoning_effort = {_string(tier.get('reasoning_effort'))}",
                f"enabled = {_string(tier.get('enabled'))}",
                f"relative_cost_weight = {_integer(tier.get('relative_cost_weight'))}",
                f"est_task_usd = {_number(tier.get('est_task_usd'))}",
                f"max_concurrent = {_integer(tier.get('max_concurrent'))}",
                f"may_spawn = {_boolean(tier.get('may_spawn'))}",
                f"task_classes = {_string_list(tier.get('task_classes'))}",
                "",
                "[tiers.pricing]",
                f"input_usd_per_mtok = {_number(tier.get('input_usd_per_mtok'))}",
                f"cache_read_usd_per_mtok = {_number(tier.get('cached_input_usd_per_mtok'))}",
                "cache_write_usd_per_mtok = 0.0",
                f"output_usd_per_mtok = {_number(tier.get('output_usd_per_mtok'))}",
            ]
        )
    candidate = "\n".join(lines) + "\n"
    try:
        ConductorConfig.model_validate(tomllib.loads(candidate))
    except ValueError as exc:
        raise ConfigError(f"v1 config cannot form a valid v2 candidate: {exc}") from exc
    return candidate


def migrate_v1(source: Path, destination: Path, *, overwrite: bool = False) -> Path:
    source = Path(source)
    destination = Path(destination)
    if destination.is_symlink():
        raise InstallationConflictError(
            f"migration destination is a symbolic link: {destination}"
        )
    if destination.exists() and not overwrite:
        raise InstallationConflictError(
            f"migration destination already exists: {destination}"
        )
    candidate = build_v2_candidate(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(candidate)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor migrate-v1")
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = migrate_v1(args.source, args.destination, overwrite=args.overwrite)
    except (ConfigError, InstallationConflictError) as exc:
        parser.exit(int(exc.exit_code), f"conductor migrate-v1: {exc}\n")
    print(path)
    return 0


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise ConfigError("v1 string field is missing or invalid")
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _string_list(value: object) -> str:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError("v1 task_classes must be an array of strings")
    return "[" + ", ".join(_string(item) for item in value) + "]"


def _number(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("v1 numeric field is missing or invalid")
    return repr(float(value))


def _integer(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("v1 integer field is missing or invalid")
    return str(value)


def _boolean(value: object) -> str:
    if not isinstance(value, bool):
        raise ConfigError("v1 boolean field is missing or invalid")
    return "true" if value else "false"


if __name__ == "__main__":
    raise SystemExit(main())
