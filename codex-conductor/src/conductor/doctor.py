from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from conductor.capabilities import contract_digest, contract_mode, load_contract
from conductor.config import config_digest, enabled_tiers, load_config
from conductor.install import (
    CONFIG_END,
    CONFIG_START,
    MANIFEST_NAME,
    POLICY_END,
    POLICY_START,
    _codex_hook_trust_entries,
    _codex_user_hooks_disabled_reason,
    _file_sha256,
    _load_manifest,
    _validate_manifest_paths,
)
from conductor.operations import normalize_operation
from conductor.policy import evaluate_policy
from conductor.pricing import pricing_verified
from conductor.schemas import OperatingMode, Provider, RunContext, TaskEnvelopeV2
from conductor.store import ReservationSnapshot, Store

_MODE_RANK = {
    OperatingMode.UNSUPPORTED: 0,
    OperatingMode.OBSERVE: 1,
    OperatingMode.ADMISSION: 2,
    OperatingMode.ROUTING: 3,
}


def run_checks(
    provider: str,
    *,
    home: Path | None = None,
    policy_path: Path | None = None,
    strict: bool = False,
) -> dict:
    provider = provider if provider in {"codex", "claude"} else "codex"
    home = home or Path.home() / (".claude" if provider == "claude" else ".codex")
    policy_path = policy_path or (
        home / "CLAUDE.md" if provider == "claude" else Path.home() / "AGENTS.md"
    )
    conductor_home = home / "conductor"
    hooks_dir = conductor_home / "hooks"
    installed_config = conductor_home / "conductor.toml"
    bundled = Path(
        str(
            files("conductor.assets").joinpath(
                "config",
                "conductor.claude.toml" if provider == "claude" else "conductor.toml",
            )
        )
    )
    config_path = installed_config if installed_config.exists() else bundled
    models_cache = home / "models_cache.json"
    checks: list[dict[str, str]] = []
    notes: list[str] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    check("python", "ok", f"Python {sys.version.split()[0]}")
    check("platform", "ok", sys.platform)

    config = None
    try:
        config = load_config(config_path)
    except Exception as exc:
        check("config", "fail", str(exc))
    else:
        source = "installed" if config_path == installed_config else "bundled"
        check(
            "config",
            "ok",
            f"schema v{config.schema_version}; {len(config.tiers)} tiers ({source}: {config_path})",
        )
        if pricing_verified(config):
            check("pricing", "ok", "configured rates are nonzero")
        else:
            check(
                "pricing",
                "warn",
                f"rates are unavailable; reports use explicit estimates ({config_path})",
            )

    contract = None
    try:
        contract = load_contract(f"{provider}-current")
        digest = contract_digest(contract)
        mode = contract_mode(contract)
    except Exception as exc:
        check("contract", "fail", str(exc))
    else:
        check(
            "contract",
            "ok",
            f"{contract.contract_name} {digest[:12]} mode={mode.value}",
        )
        if (
            config is not None
            and _MODE_RANK[mode] < _MODE_RANK[config.policy.minimum_mode]
        ):
            check(
                "mode",
                "fail",
                f"contract mode {mode.value} is below minimum {config.policy.minimum_mode.value}",
            )
        else:
            check("mode", "ok", mode.value)
        _check_cli_version(
            check,
            provider,
            contract.cli_version_range.minimum,
            contract.cli_version_range.maximum_exclusive,
        )

    if provider == "claude":
        _check_json_hooks(
            check,
            home / "settings.json",
            hooks_dir,
            expected=(
                "SessionStart",
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
            ),
            settings=True,
        )
    else:
        _check_codex_hook_runtime(check, home / "config.toml", home / "hooks.json")
        _check_json_hooks(
            check,
            home / "hooks.json",
            hooks_dir,
            expected=(
                "SessionStart",
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
            ),
            settings=False,
        )
        if models_cache.exists():
            check("models_cache", "ok", "present")
        else:
            check("models_cache", "warn", "absent; auto tiers are disabled")
        notes.append(
            "Codex hook trust fingerprints are verified against the generated "
            "Conductor hooks; reinstall Conductor after changing hook definitions."
        )

    _check_wrappers(check, hooks_dir)
    _check_block(
        check,
        home / "config.toml" if provider == "codex" else policy_path,
        CONFIG_START if provider == "codex" else POLICY_START,
        CONFIG_END if provider == "codex" else POLICY_END,
        "runtime_block" if provider == "codex" else "policy_block",
    )
    if provider == "codex":
        _check_block(check, policy_path, POLICY_START, POLICY_END, "policy_block")
    _check_manifest(
        check,
        conductor_home / MANIFEST_NAME,
        provider_root=home,
        provider=provider,
    )

    database_path = conductor_home / "state" / "conductor.db"
    if database_path.exists():
        try:
            store = Store(database_path)
            integrity = store.integrity_check()
            if integrity != "ok":
                raise ValueError(integrity)
            check(
                "store",
                "ok",
                f"schema={store.schema_version()} journal={store.journal_mode()} integrity=ok",
            )
            latest = store.latest_run_id()
            if latest is not None and config is not None:
                try:
                    context = store.run_context(latest)
                except Exception as exc:
                    check("run_context", "fail", str(exc))
                else:
                    drift = context.config_digest != config_digest(config)
                    check(
                        "run_context",
                        "fail" if drift else "ok",
                        "config digest drift"
                        if drift
                        else f"validated latest run {latest}",
                    )
        except Exception as exc:
            check("store", "fail", str(exc))
    else:
        check("store", "warn", "not created yet; start a provider session")

    if config is not None and contract is not None:
        _check_policy_canary(
            check, provider, config, contract_mode(contract), models_cache
        )

    failures = any(item["status"] == "fail" for item in checks)
    warnings = any(item["status"] == "warn" for item in checks)
    return {
        "schema_version": 1,
        "provider": provider,
        "checks": checks,
        "notes": notes,
        "strict": strict,
        "ok": not failures and not (strict and warnings),
        "degraded": warnings,
    }


def render_human(report: dict) -> str:
    lines = [f"provider: {report['provider']}"]
    for item in report["checks"]:
        lines.append(
            f"[{item['status'].upper():<4}] {item['name']:<16} {item['detail']}"
        )
    for note in report.get("notes", []):
        lines.append(f"[NOTE] {note}")
    lines.append(f"overall: {'OK' if report['ok'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    report = run_checks(args.provider, strict=args.strict)
    print(
        json.dumps(report, indent=2, sort_keys=True)
        if args.json
        else render_human(report)
    )
    return 0 if report["ok"] else 1


def _check_json_hooks(
    check,
    path: Path,
    hooks_dir: Path,
    *,
    expected: tuple[str, ...],
    settings: bool,
) -> None:
    name = "settings_hooks" if settings else "hooks_json"
    if not path.exists():
        check(name, "fail", f"not installed: {path}")
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        check(name, "fail", str(exc))
        return
    if not isinstance(value, dict):
        check(name, "fail", "root must be a JSON object")
        return
    if not settings:
        if value.get("description") != "Managed by codex-conductor":
            check(name, "fail", "file is not owned by codex-conductor")
            return
        unsupported = sorted(set(value) - {"description", "hooks"})
        if unsupported:
            check(
                name,
                "fail",
                f"unsupported top-level fields: {', '.join(unsupported)}",
            )
            return
    hooks = value.get("hooks")
    if not isinstance(hooks, dict):
        check(name, "fail", "hooks object is missing")
        return
    missing = [
        event for event in expected if not _event_has_hook(hooks.get(event), hooks_dir)
    ]
    check(
        name,
        "fail" if missing else "ok",
        f"missing events: {', '.join(missing)}"
        if missing
        else "all correlated hooks present",
    )


def _check_codex_hook_runtime(check, path: Path, hooks_path: Path) -> None:
    if not path.exists():
        check("hook_runtime", "fail", f"Codex config is missing: {path}")
        return
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        check("hook_runtime", "fail", f"cannot read Codex hook settings: {exc}")
        return
    reason = _codex_user_hooks_disabled_reason(value)
    if reason is not None:
        check("hook_runtime", "fail", f"Codex config disables user hooks: {reason}")
        return
    try:
        expected = _codex_hook_trust_entries(
            hooks_path, hooks_path.read_text(encoding="utf-8")
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        check("hook_runtime", "fail", f"cannot verify Conductor hook trust: {exc}")
        return
    states = value.get("hooks", {}).get("state", {})
    inactive = [
        key
        for key, digest in expected.items()
        if not isinstance(states.get(key), dict)
        or states[key].get("trusted_hash") != digest
    ]
    if inactive:
        events = ", ".join(key.rsplit(":", 3)[-3] for key in inactive)
        check(
            "hook_runtime",
            "fail",
            f"inactive Conductor hooks need trust refresh: {events}; reinstall Conductor",
        )
        return
    check(
        "hook_runtime", "ok", "user hooks are enabled and Conductor hooks are trusted"
    )


def _event_has_hook(value: object, hooks_dir: Path) -> bool:
    if not isinstance(value, list):
        return False
    return any(
        isinstance(hook, dict) and str(hooks_dir) in str(hook.get("command", ""))
        for entry in value
        if isinstance(entry, dict)
        for hook in entry.get("hooks", [])
    )


def _check_wrappers(check, hooks_dir: Path) -> None:
    failures: list[str] = []
    for module in ("pre_tool_use", "lifecycle", "session_start"):
        path = hooks_dir / f"{module}.py"
        if not path.is_file() or path.is_symlink():
            failures.append(path.name)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            failures.append(path.name)
            continue
        if f"from conductor.hooks.{module} import main" not in text:
            failures.append(path.name)
    check(
        "hook_wrappers",
        "fail" if failures else "ok",
        f"invalid: {', '.join(failures)}" if failures else "validated",
    )


def _check_block(check, path: Path, start: str, end: str, name: str) -> None:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        check(name, "fail", str(exc))
        return
    present = text.count(start) == 1 and text.count(end) == 1
    check(
        name,
        "ok" if present else "fail",
        "present" if present else f"missing in {path}",
    )


def _check_manifest(
    check,
    path: Path,
    *,
    provider_root: Path,
    provider: str,
) -> None:
    try:
        manifest = _load_manifest(path)
        if manifest is None:
            raise ValueError("manifest is missing")
        _validate_manifest_paths(manifest, provider_root, provider)
        drift: list[str] = []
        for raw_path, record in manifest["files"].items():
            if record.get("ownership") != "full":
                continue
            target = Path(raw_path)
            if (
                not target.is_file()
                or target.is_symlink()
                or _file_sha256(target) != record.get("sha256")
            ):
                drift.append(str(target))
        if drift:
            raise ValueError("managed file drift: " + ", ".join(drift))
    except Exception as exc:
        check("manifest", "fail", str(exc))
    else:
        check("manifest", "ok", f"{len(manifest['files'])} ownership records validated")


def _check_cli_version(
    check,
    provider: str,
    minimum: str,
    maximum_exclusive: str | None,
) -> None:
    executable = shutil.which(provider)
    if executable is None:
        check("provider_cli", "warn", f"{provider} executable not found")
        return
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        output = (result.stdout + " " + result.stderr).strip()
        match = re.search(r"\d+(?:\.\d+){1,3}", output)
        if result.returncode != 0 or match is None:
            raise ValueError(output or f"exit {result.returncode}")
        version = _version_tuple(match.group(0))
        supported = version >= _version_tuple(minimum) and (
            maximum_exclusive is None or version < _version_tuple(maximum_exclusive)
        )
        check(
            "provider_cli",
            "ok" if supported else "fail",
            f"{match.group(0)} supported range [{minimum}, {maximum_exclusive or '∞'})",
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        check("provider_cli", "warn", str(exc))


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(part) for part in value.split(".")]
    return tuple([*parts, 0, 0, 0, 0][:4])


def _check_policy_canary(
    check,
    provider: str,
    config,
    mode: OperatingMode,
    models_cache: Path,
) -> None:
    now = datetime.now(UTC)
    run = RunContext(
        provider=Provider(provider),
        run_id="doctor-run",
        thread_id="doctor-run",
        root_model=config.tiers[0].model,
        model_source="operator",
        provider_contract=f"{provider}-current",
        contract_digest="0" * 64,
        mode=mode,
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest=config_digest(config),
    )
    target = config.tier_for_class("implementation") or config.tiers[0]
    envelope = TaskEnvelopeV2(
        schema_version=1,
        task_name="doctor-canary",
        task_class="implementation",
        risk_triggers=(),
        owned_paths=("src/doctor_canary.py",),
        acceptance_checks=("conductor doctor --strict",),
        new_task=True,
    )
    operation = normalize_operation(
        provider,
        "Task" if provider == "claude" else "spawn_agent",
        {
            "model": target.model,
            "reasoning_effort": target.reasoning_effort,
            "message": "doctor canary",
        },
        envelope,
    )
    enabled = enabled_tiers(config, models_cache)
    result = evaluate_policy(
        operation=operation,
        run=run,
        config=config,
        enabled_tiers=enabled,
        snapshot=ReservationSnapshot({}, 0.0, 0.0),
        caller_model=config.tiers[0].model,
        caller_depth=0,
        caller_effort=config.tiers[0].reasoning_effort,
    )
    coherent = (
        (mode is OperatingMode.ROUTING and result.spec.allowed)
        or (
            mode is OperatingMode.ADMISSION
            and not result.spec.allowed
            and result.spec.rule == "ROUTING_REQUIRED"
        )
        or mode in {OperatingMode.OBSERVE, OperatingMode.UNSUPPORTED}
    )
    check(
        "policy_canary",
        "ok" if coherent else "fail",
        f"mode={mode.value} rule={result.spec.rule} allowed={result.spec.allowed}",
    )


if __name__ == "__main__":
    raise SystemExit(main())
