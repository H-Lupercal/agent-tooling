from __future__ import annotations

import argparse
import json
import sys
from importlib.resources import files
from pathlib import Path


def run_checks(provider: str, *, home: Path | None = None, policy_path: Path | None = None) -> dict:
    from conductor.config import ConfigError, enabled_tiers, load_ladder
    from conductor.install import CONFIG_END, CONFIG_START, POLICY_END, POLICY_START

    provider = provider if provider in {"codex", "claude"} else "codex"
    home = home or (Path.home() / (".claude" if provider == "claude" else ".codex"))
    policy_path = policy_path or (home / "CLAUDE.md" if provider == "claude" else Path.home() / "AGENTS.md")
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

    checks: list[dict] = []
    notes: list[str] = []

    def check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    check("python", "ok", f"Python {sys.version.split()[0]}")
    check("platform", "ok", sys.platform)

    ladder = None
    try:
        ladder = load_ladder(config_path)
    except (ConfigError, OSError, KeyError, TypeError, ValueError) as exc:
        check("config", "fail", str(exc))
    else:
        source = "installed" if config_path == installed_config else "bundled default"
        check(
            "config",
            "ok",
            f"{len(ladder.tiers)} tiers, {len(enabled_tiers(ladder, models_cache))} enabled ({source}: {config_path})",
        )

    if ladder is not None:
        from conductor.pricing import pricing_verified

        if pricing_verified(ladder):
            check("pricing", "ok", "verified")
        else:
            check("pricing", "warn", f"PRICING UNVERIFIED - edit {config_path}")

    required_wrappers = ["pre_tool_use.py", "lifecycle.py", "session_start.py"]
    if provider == "claude":
        _check_claude_settings(check, home / "settings.json", hooks_dir)
        _check_hook_wrappers(check, hooks_dir, required_wrappers)
        _check_policy_block(check, policy_path, POLICY_START, POLICY_END)
        notes.append("Review ~/.claude/settings.json if your setup requires managed-settings approval.")
    else:
        _check_codex_hooks_json(check, home / "hooks.json")
        _check_hook_wrappers(check, hooks_dir, required_wrappers)
        _check_agents_block(check, home / "config.toml", CONFIG_START, CONFIG_END)
        _check_policy_block(check, policy_path, POLICY_START, POLICY_END)
        _check_models_cache(check, models_cache)
        notes.append("Codex records hook trust by hash - run /hooks in the Codex CLI to trust the installed hooks.")

    ok = not any(item["status"] == "fail" for item in checks)
    return {"provider": provider, "checks": checks, "notes": notes, "ok": ok}


def render_human(report: dict) -> str:
    lines = [f"provider: {report['provider']}"]
    for item in report["checks"]:
        lines.append(f"[{item['status'].upper():<4}] {item['name']:<14} {item['detail']}")
    if report.get("notes"):
        lines.append("notes:")
        for note in report["notes"]:
            lines.append(f"- {note}")
    lines.append(f"overall: {'OK' if report['ok'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < (3, 11):
        print("[FAIL] python: requires Python 3.11+ (tomllib / datetime.UTC)")
        return 1

    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_checks(args.provider)
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report))
    return 0 if report["ok"] else 1


def _check_codex_hooks_json(check, path: Path) -> None:
    if not path.exists():
        check("hooks_json", "fail", "not installed - run: bash install.sh")
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        check("hooks_json", "fail", str(exc))
        return
    if '"_managed_by": "codex-conductor"' in text:
        check("hooks_json", "ok", "managed hooks.json present")
    else:
        check("hooks_json", "fail", "foreign hooks.json present - conductor hooks not active")


def _check_claude_settings(check, path: Path, hooks_dir: Path) -> None:
    if not path.exists():
        check("settings_hooks", "fail", "not installed - run: bash install.sh --provider claude")
        return
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        check("settings_hooks", "fail", str(exc))
        return
    except json.JSONDecodeError:
        check("settings_hooks", "fail", "settings.json is not valid JSON")
        return

    hooks = settings.get("hooks") if isinstance(settings, dict) else {}
    hooks = hooks or {}
    if not isinstance(hooks, dict):
        hooks = {}
    expected = ["SessionStart", "PreToolUse", "SubagentStart", "SubagentStop"]
    missing = [event for event in expected if not _event_has_hook(hooks.get(event, []), hooks_dir)]
    if not missing:
        check("settings_hooks", "ok", "conductor hooks present")
    elif len(missing) == len(expected):
        check("settings_hooks", "fail", "conductor hooks not found in settings.json")
    else:
        check("settings_hooks", "warn", f"conductor hooks missing for: {', '.join(missing)}")


def _event_has_hook(entries: object, hooks_dir: Path) -> bool:
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for hook in entry.get("hooks", []) or []:
            if isinstance(hook, dict) and str(hooks_dir) in str(hook.get("command", "")):
                return True
    return False


def _check_hook_wrappers(check, hooks_dir: Path, required: list[str]) -> None:
    missing = [name for name in required if not (hooks_dir / name).exists()]
    if missing:
        check("hook_wrappers", "fail", f"missing: {', '.join(missing)}")
    else:
        check("hook_wrappers", "ok", "present")


def _check_agents_block(check, path: Path, start: str, end: str) -> None:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        check("agents_block", "warn", str(exc))
        return
    if start in text and end in text:
        check("agents_block", "ok", "managed [agents] block present")
    else:
        check("agents_block", "warn", "managed [agents] block absent")


def _check_policy_block(check, path: Path, start: str, end: str) -> None:
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:
        check("policy_block", "warn", str(exc))
        return
    if start in text and end in text:
        check("policy_block", "ok", "delegation policy installed")
    else:
        check("policy_block", "warn", f"delegation policy not installed in {path}")


def _check_models_cache(check, path: Path) -> None:
    if path.exists():
        check("models_cache", "ok", "present")
    else:
        check("models_cache", "warn", "absent - auto tiers (mini, spark) disabled")


if __name__ == "__main__":
    raise SystemExit(main())
