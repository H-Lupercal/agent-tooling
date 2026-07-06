from __future__ import annotations

import argparse
import difflib
import json
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


def install(codex_home: Path | None = None, agents_path: Path | None = None, dry_run: bool = False) -> list[Path]:
    try:
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
            _write_or_diff(dst, _wrapper(module), dry_run)
            written.append(dst)
        hooks_json = _render_hooks_json(hooks_dir)
        _write_or_diff(codex_home / "hooks.json", hooks_json, dry_run)
        written.append(codex_home / "hooks.json")
        config_block = "\n".join((CONFIG_START, "[agents]", "max_threads = 8", "max_depth = 3", "job_max_runtime_seconds = 1800", CONFIG_END, ""))
        _upsert_block(codex_home / "config.toml", CONFIG_START, CONFIG_END, config_block, dry_run)
        written.append(codex_home / "config.toml")
        policy = (PROJECT_ROOT / "policy" / "orchestration-policy.md").read_text(encoding="utf-8")
        _upsert_block(agents_path, POLICY_START, POLICY_END, policy, dry_run)
        written.append(agents_path)
        return written
    except ManagedBlockError as exc:
        print(f"refusing to install: {exc}", file=sys.stderr)
        raise SystemExit(2)


def uninstall(codex_home: Path | None = None, agents_path: Path | None = None, dry_run: bool = False) -> list[Path]:
    try:
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
    except ManagedBlockError as exc:
        print(f"refusing to uninstall: {exc}", file=sys.stderr)
        raise SystemExit(2)


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


def _wrapper(module: str) -> str:
    return (
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import sys\n"
        f"sys.path.insert(0, {str(PROJECT_ROOT)!r})\n"
        f"from conductor.hooks.{module} import main\n"
        "raise SystemExit(main())\n"
    )


def _render_hooks_json(hooks_dir: Path) -> str:
    def command(module: str) -> str:
        return "python3 " + shlex.quote(str(hooks_dir / f"{module}.py"))

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
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--agents-path", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    paths = uninstall(args.codex_home, args.agents_path, args.dry_run) if args.uninstall else install(args.codex_home, args.agents_path, args.dry_run)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
