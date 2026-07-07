from __future__ import annotations

import argparse
import difflib
import json
import os
import shlex
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_START = "# >>> codex-conductor managed >>>"
CONFIG_END = "# <<< codex-conductor managed <<<"
POLICY_START = "<!-- >>> codex-conductor policy >>> -->"
POLICY_END = "<!-- <<< codex-conductor policy <<< -->"


class ManagedBlockError(Exception):
    pass


def install(
    codex_home: Path | None = None,
    agents_path: Path | None = None,
    dry_run: bool = False,
    *,
    provider: str = "codex",
    claude_home: Path | None = None,
    claude_md_path: Path | None = None,
) -> list[Path]:
    try:
        if provider == "claude":
            return _install_claude(claude_home, claude_md_path, dry_run)
        return _install_codex(codex_home, agents_path, dry_run)
    except ManagedBlockError as exc:
        print(f"refusing to install: {exc}", file=sys.stderr)
        raise SystemExit(2)


def uninstall(
    codex_home: Path | None = None,
    agents_path: Path | None = None,
    dry_run: bool = False,
    *,
    provider: str = "codex",
    claude_home: Path | None = None,
    claude_md_path: Path | None = None,
) -> list[Path]:
    try:
        if provider == "claude":
            return _uninstall_claude(claude_home, claude_md_path, dry_run)
        return _uninstall_codex(codex_home, agents_path, dry_run)
    except ManagedBlockError as exc:
        print(f"refusing to uninstall: {exc}", file=sys.stderr)
        raise SystemExit(2)


# --------------------------------------------------------------------------- #
# Codex
# --------------------------------------------------------------------------- #


def _install_codex(codex_home: Path | None, agents_path: Path | None, dry_run: bool) -> list[Path]:
    codex_home = (codex_home or Path.home() / ".codex").expanduser()
    agents_path = (agents_path or Path.home() / "AGENTS.md").expanduser()
    _refuse_conflicts(codex_home, agents_path)
    written: list[Path] = []
    conductor_home = codex_home / "conductor"
    hooks_dir = conductor_home / "hooks"
    config_dst = conductor_home / "conductor.toml"
    for path in (conductor_home, hooks_dir, conductor_home / "state"):
        if not dry_run:
            path.mkdir(parents=True, exist_ok=True)
    if not config_dst.exists() or dry_run:
        _write_or_diff(config_dst, (PROJECT_ROOT / "config" / "conductor.toml").read_text(encoding="utf-8"), dry_run)
        written.append(config_dst)
    for module in ("pre_tool_use", "lifecycle", "session_start"):
        dst = hooks_dir / f"{module}.py"
        _write_or_diff(
            dst,
            _wrapper(
                module,
                "codex",
                conductor_home=conductor_home,
                sessions_root=codex_home / "sessions",
                models_cache=codex_home / "models_cache.json",
            ),
            dry_run,
        )
        written.append(dst)
    hooks_json = _render_hooks_json(hooks_dir)
    _write_or_diff(codex_home / "hooks.json", hooks_json, dry_run)
    written.append(codex_home / "hooks.json")
    config_block = "\n".join((CONFIG_START, "[agents]", "max_threads = 8", "max_depth = 3", "job_max_runtime_seconds = 1800", CONFIG_END, ""))
    _upsert_block(codex_home / "config.toml", CONFIG_START, CONFIG_END, config_block, dry_run)
    written.append(codex_home / "config.toml")
    policy = _render_policy(PROJECT_ROOT, "codex")
    _upsert_block(agents_path, POLICY_START, POLICY_END, policy, dry_run)
    written.append(agents_path)
    return written


def _uninstall_codex(codex_home: Path | None, agents_path: Path | None, dry_run: bool) -> list[Path]:
    codex_home = (codex_home or Path.home() / ".codex").expanduser()
    agents_path = (agents_path or Path.home() / "AGENTS.md").expanduser()
    changed: list[Path] = []
    _remove_block(codex_home / "config.toml", CONFIG_START, CONFIG_END, dry_run)
    changed.append(codex_home / "config.toml")
    _remove_block(agents_path, POLICY_START, POLICY_END, dry_run)
    changed.append(agents_path)
    hooks = codex_home / "hooks.json"
    if hooks.exists() and '"_managed_by": "codex-conductor"' in hooks.read_text(encoding="utf-8"):
        if not dry_run:
            hooks.unlink()
        changed.append(hooks)
    return changed


def _refuse_conflicts(codex_home: Path, agents_path: Path) -> None:
    config = codex_home / "config.toml"
    if config.exists():
        text = config.read_text(encoding="utf-8")
        unmanaged = _strip_block(text, CONFIG_START, CONFIG_END)
        if "[agents]" in unmanaged or "[rollout_budget]" in unmanaged or "[hooks]" in unmanaged:
            print(f"refusing to install: unmanaged agents/hooks/rollout_budget table in {config}", file=sys.stderr)
            raise SystemExit(2)
    hooks = codex_home / "hooks.json"
    if hooks.exists() and '"_managed_by": "codex-conductor"' not in hooks.read_text(encoding="utf-8"):
        print(f"refusing to install: foreign hooks file {hooks}", file=sys.stderr)
        raise SystemExit(2)
    if agents_path.exists():
        _strip_block(agents_path.read_text(encoding="utf-8"), POLICY_START, POLICY_END)


def _hook_command(script: Path, *args: str) -> str:
    parts = [sys.executable, str(script), *args]
    if os.name == "nt":
        return " ".join(f'"{part}"' if (" " in part or "\t" in part) else part for part in parts)
    return " ".join(shlex.quote(part) for part in parts)


def _render_hooks_json(hooks_dir: Path) -> str:
    def command(module: str) -> str:
        return _hook_command(hooks_dir / f"{module}.py")

    data = {
        "_managed_by": "codex-conductor",
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("session_start"),
                            "timeout": 5,
                            "statusMessage": "Starting conductor ledger",
                        }
                    ],
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "spawn_agent|assign_agent_task|send_message|send_agent_message",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("pre_tool_use"),
                            "timeout": 5,
                            "statusMessage": "Checking conductor policy",
                        }
                    ],
                }
            ],
            "SubagentStart": [{"hooks": [{"type": "command", "command": command("lifecycle"), "timeout": 5}]}],
            "SubagentStop": [{"hooks": [{"type": "command", "command": command("lifecycle"), "timeout": 5}]}],
        },
    }
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------- #
# Claude Code
# --------------------------------------------------------------------------- #


def _install_claude(claude_home: Path | None, claude_md_path: Path | None, dry_run: bool) -> list[Path]:
    claude_home = (claude_home or Path.home() / ".claude").expanduser()
    claude_md_path = (claude_md_path or claude_home / "CLAUDE.md").expanduser()
    written: list[Path] = []
    conductor_home = claude_home / "conductor"
    hooks_dir = conductor_home / "hooks"
    config_dst = conductor_home / "conductor.toml"
    for path in (conductor_home, hooks_dir, conductor_home / "state"):
        if not dry_run:
            path.mkdir(parents=True, exist_ok=True)
    if not config_dst.exists() or dry_run:
        _write_or_diff(config_dst, (PROJECT_ROOT / "config" / "conductor.claude.toml").read_text(encoding="utf-8"), dry_run)
        written.append(config_dst)
    for module in ("pre_tool_use", "lifecycle", "session_start"):
        dst = hooks_dir / f"{module}.py"
        _write_or_diff(dst, _wrapper(module, "claude", conductor_home=conductor_home), dry_run)
        written.append(dst)
    settings_path = claude_home / "settings.json"
    _merge_claude_settings(settings_path, hooks_dir, dry_run)
    written.append(settings_path)
    policy = _render_policy(PROJECT_ROOT, "claude")
    _upsert_block(claude_md_path, POLICY_START, POLICY_END, policy, dry_run)
    written.append(claude_md_path)
    return written


def _uninstall_claude(claude_home: Path | None, claude_md_path: Path | None, dry_run: bool) -> list[Path]:
    claude_home = (claude_home or Path.home() / ".claude").expanduser()
    claude_md_path = (claude_md_path or claude_home / "CLAUDE.md").expanduser()
    hooks_dir = claude_home / "conductor" / "hooks"
    changed: list[Path] = []
    settings_path = claude_home / "settings.json"
    if settings_path.exists():
        _remove_claude_settings(settings_path, hooks_dir, dry_run)
        changed.append(settings_path)
    _remove_block(claude_md_path, POLICY_START, POLICY_END, dry_run)
    changed.append(claude_md_path)
    return changed


def _claude_hook_entries(hooks_dir: Path) -> dict[str, dict]:
    def command(module: str) -> str:
        return _hook_command(hooks_dir / f"{module}.py", "--provider", "claude")

    return {
        "SessionStart": {
            "matcher": "startup|resume|clear|compact",
            "hooks": [{"type": "command", "command": command("session_start"), "timeout": 5, "statusMessage": "Starting conductor ledger"}],
        },
        "PreToolUse": {
            "matcher": "Task",
            "hooks": [{"type": "command", "command": command("pre_tool_use"), "timeout": 5, "statusMessage": "Checking conductor policy"}],
        },
        "SubagentStart": {
            "hooks": [{"type": "command", "command": command("lifecycle"), "timeout": 5}],
        },
        "SubagentStop": {
            "hooks": [{"type": "command", "command": command("lifecycle"), "timeout": 5}],
        },
    }


def _is_conductor_entry(entry: object, hooks_dir: Path) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []) or []:
        if isinstance(hook, dict) and str(hooks_dir) in str(hook.get("command", "")):
            return True
    return False


def _merge_claude_settings(path: Path, hooks_dir: Path, dry_run: bool) -> None:
    settings: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ManagedBlockError(f"{path} is not valid JSON: {exc}")
        if not isinstance(loaded, dict):
            raise ManagedBlockError(f"{path} does not contain a JSON object")
        settings = loaded
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for event, entry in _claude_hook_entries(hooks_dir).items():
        current = hooks.get(event)
        current = current if isinstance(current, list) else []
        filtered = [item for item in current if not _is_conductor_entry(item, hooks_dir)]
        filtered.append(entry)
        hooks[event] = filtered
    settings["hooks"] = hooks
    _write_or_diff(path, json.dumps(settings, indent=2) + "\n", dry_run)


def _remove_claude_settings(path: Path, hooks_dir: Path, dry_run: bool) -> None:
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(settings, dict) or not isinstance(settings.get("hooks"), dict):
        return
    hooks = settings["hooks"]
    for event in list(hooks.keys()):
        current = hooks.get(event)
        if not isinstance(current, list):
            continue
        filtered = [item for item in current if not _is_conductor_entry(item, hooks_dir)]
        if filtered:
            hooks[event] = filtered
        else:
            del hooks[event]
    if hooks:
        settings["hooks"] = hooks
    else:
        settings.pop("hooks", None)
    _write_or_diff(path, json.dumps(settings, indent=2) + "\n", dry_run)


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _wrapper(
    module: str,
    provider: str = "codex",
    *,
    conductor_home: Path | None = None,
    sessions_root: Path | None = None,
    models_cache: Path | None = None,
) -> str:
    call = "main()" if provider == "codex" else f"main(['--provider', {provider!r}])"
    env_lines = ""
    if conductor_home is not None:
        env_lines += f"os.environ.setdefault('CODEX_CONDUCTOR_HOME', {str(conductor_home)!r})\n"
    if sessions_root is not None:
        env_lines += f"os.environ.setdefault('CODEX_CONDUCTOR_SESSIONS_ROOT', {str(sessions_root)!r})\n"
    if models_cache is not None:
        env_lines += f"os.environ.setdefault('CODEX_MODELS_CACHE', {str(models_cache)!r})\n"
    return (
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import os\n"
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        f"{env_lines}"
        f"from conductor.hooks.{module} import main\n"
        f"raise SystemExit({call})\n"
    )


def _render_policy(project_root: Path = PROJECT_ROOT, provider: str = "codex") -> str:
    name = "orchestration-policy.md" if provider == "codex" else f"orchestration-policy.{provider}.md"
    template = (PROJECT_ROOT / "policy" / name).read_text(encoding="utf-8")
    return template.replace("{{PROJECT_ROOT}}", shlex.quote(str(project_root)))


def _upsert_block(path: Path, start: str, end: str, block: str, dry_run: bool) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    new_text = _strip_block(text, start, end).rstrip() + "\n\n" + block.rstrip() + "\n"
    _write_or_diff(path, new_text, dry_run)


def _remove_block(path: Path, start: str, end: str, dry_run: bool) -> None:
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    _write_or_diff(path, _strip_block(text, start, end).strip() + "\n", dry_run)


def _strip_block(text: str, start: str, end: str) -> str:
    if start not in text:
        return text
    before, rest = text.split(start, 1)
    if end not in rest:
        raise ManagedBlockError(f"partial managed block missing end marker {end!r}")
    _, after = rest.split(end, 1)
    return before + after


def _write_or_diff(path: Path, text: str, dry_run: bool) -> None:
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == text:
        return
    if dry_run:
        print("".join(difflib.unified_diff(old.splitlines(True), text.splitlines(True), fromfile=str(path), tofile=str(path))))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="codex", choices=["codex", "claude"])
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--agents-path", type=Path)
    parser.add_argument("--claude-home", type=Path)
    parser.add_argument("--claude-md-path", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    action = uninstall if args.uninstall else install
    paths = action(
        args.codex_home,
        args.agents_path,
        args.dry_run,
        provider=args.provider,
        claude_home=args.claude_home,
        claude_md_path=args.claude_md_path,
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
