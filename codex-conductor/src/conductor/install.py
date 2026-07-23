from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import shlex
import sys
import tempfile
import tomllib
import uuid
from importlib.resources import files
from pathlib import Path

from conductor.errors import InstallationConflictError
from conductor.path_guard import is_unsafe_path_redirect

CONFIG_START = "# >>> codex-conductor managed >>>"
CONFIG_END = "# <<< codex-conductor managed <<<"
POLICY_START = "<!-- >>> codex-conductor policy >>> -->"
POLICY_END = "<!-- <<< codex-conductor policy <<< -->"


MANIFEST_NAME = "managed-manifest.json"
_TRANSACTION: _FileTransaction | None = None


class ManagedBlockError(InstallationConflictError):
    pass


class _FileTransaction:
    def __init__(self, *, dry_run: bool) -> None:
        self.dry_run = dry_run
        self.changes: dict[Path, str | None] = {}

    def stage(self, path: Path, text: str | None) -> None:
        destination = Path(path)
        _assert_safe_path(destination)
        self.changes[destination] = text

    def commit(self) -> None:
        if self.dry_run:
            for path, text in sorted(
                self.changes.items(), key=lambda item: str(item[0])
            ):
                old = path.read_text(encoding="utf-8") if path.exists() else ""
                new = text or ""
                if old != new:
                    print(
                        "".join(
                            difflib.unified_diff(
                                old.splitlines(True),
                                new.splitlines(True),
                                fromfile=str(path),
                                tofile=str(path),
                            )
                        )
                    )
            return

        staged: dict[Path, Path] = {}
        applied: list[dict[str, object]] = []
        effective: set[Path] = set()
        try:
            for path, text in self.changes.items():
                _assert_safe_path(path)
                if text is None:
                    if path.exists():
                        effective.add(path)
                    continue
                if path.exists() and path.read_text(encoding="utf-8") == text:
                    continue
                effective.add(path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    dir=path.parent,
                    prefix=f".{path.name}.conductor-stage-",
                    delete=False,
                ) as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                    staged[path] = Path(handle.name)

            for path in sorted(effective, key=str):
                text = self.changes[path]
                record: dict[str, object] = {
                    "path": path,
                    "backup": None,
                    "original_moved": False,
                    "new_installed": False,
                }
                applied.append(record)
                if path.exists():
                    backup = path.with_name(
                        f".{path.name}.conductor-backup-{uuid.uuid4().hex}"
                    )
                    record["backup"] = backup
                    os.replace(path, backup)
                    record["original_moved"] = True
                if text is not None:
                    os.replace(staged[path], path)
                    record["new_installed"] = True

            for record in applied:
                backup = record["backup"]
                if isinstance(backup, Path) and backup.exists():
                    # The committed destination is authoritative. A stale
                    # private backup is safer than rolling back a complete
                    # install because cleanup alone failed.
                    with contextlib.suppress(OSError):
                        backup.unlink()
            for parent in {path.parent for path in effective}:
                _fsync_directory(parent)
        except BaseException as commit_error:
            rollback_failures: list[str] = []
            for record in reversed(applied):
                path = record["path"]
                backup = record["backup"]
                if not isinstance(path, Path):
                    continue
                try:
                    if bool(record["new_installed"]) and path.exists():
                        path.unlink()
                    if (
                        bool(record["original_moved"])
                        and isinstance(backup, Path)
                        and backup.exists()
                    ):
                        os.replace(backup, path)
                except OSError as rollback_error:
                    rollback_failures.append(f"{path}: {rollback_error}")
            if rollback_failures:
                raise InstallationConflictError(
                    "install failed and rollback was incomplete; backups were "
                    "preserved: " + "; ".join(rollback_failures)
                ) from commit_error
            raise
        finally:
            for temporary in staged.values():
                if temporary.exists():
                    with contextlib.suppress(OSError):
                        temporary.unlink()


def install(
    codex_home: Path | None = None,
    agents_path: Path | None = None,
    dry_run: bool = False,
    *,
    provider: str = "codex",
    claude_home: Path | None = None,
    claude_md_path: Path | None = None,
    repair: bool = False,
) -> list[Path]:
    global _TRANSACTION

    provider_root = (
        (claude_home or Path.home() / ".claude").expanduser()
        if provider == "claude"
        else (codex_home or Path.home() / ".codex").expanduser()
    )
    policy_path = (
        (claude_md_path or provider_root / "CLAUDE.md").expanduser()
        if provider == "claude"
        else (agents_path or Path.home() / "AGENTS.md").expanduser()
    )
    _assert_safe_path(provider_root)
    _assert_safe_path(policy_path)
    manifest_path = provider_root / "conductor" / MANIFEST_NAME
    _verify_managed_files(
        manifest_path,
        provider_root=provider_root,
        provider=provider,
        repair=repair,
    )

    transaction = _FileTransaction(dry_run=dry_run)
    previous = _TRANSACTION
    _TRANSACTION = transaction
    try:
        if provider == "claude":
            written = _install_claude(provider_root, policy_path, dry_run)
        else:
            written = _install_codex(provider_root, policy_path, dry_run)
        manifest = _render_manifest(provider, provider_root, transaction)
        transaction.stage(manifest_path, manifest)
        transaction.commit()
    finally:
        _TRANSACTION = previous
    return [*written, manifest_path]


def uninstall(
    codex_home: Path | None = None,
    agents_path: Path | None = None,
    dry_run: bool = False,
    *,
    provider: str = "codex",
    claude_home: Path | None = None,
    claude_md_path: Path | None = None,
) -> list[Path]:
    global _TRANSACTION

    provider_root = (
        (claude_home or Path.home() / ".claude").expanduser()
        if provider == "claude"
        else (codex_home or Path.home() / ".codex").expanduser()
    )
    policy_path = (
        (claude_md_path or provider_root / "CLAUDE.md").expanduser()
        if provider == "claude"
        else (agents_path or Path.home() / "AGENTS.md").expanduser()
    )
    _assert_safe_path(provider_root)
    _assert_safe_path(policy_path)
    manifest_path = provider_root / "conductor" / MANIFEST_NAME
    manifest = _load_manifest(manifest_path)
    if manifest is not None:
        _validate_manifest_paths(manifest, provider_root, provider)
    transaction = _FileTransaction(dry_run=dry_run)
    previous = _TRANSACTION
    _TRANSACTION = transaction
    try:
        if provider == "claude":
            changed = _uninstall_claude(provider_root, policy_path, dry_run)
        else:
            changed = _uninstall_codex(provider_root, policy_path, dry_run)
        if manifest is not None:
            for raw_path, record in manifest.get("files", {}).items():
                if not isinstance(raw_path, str) or not isinstance(record, dict):
                    continue
                if record.get("ownership") != "full":
                    continue
                path = Path(raw_path)
                expected = record.get("sha256")
                if path.exists() and expected == _file_sha256(path):
                    transaction.stage(path, None)
                    changed.append(path)
            transaction.stage(manifest_path, None)
            changed.append(manifest_path)
        transaction.commit()
    finally:
        _TRANSACTION = previous
    return changed


# --------------------------------------------------------------------------- #
# Codex
# --------------------------------------------------------------------------- #


def _install_codex(
    codex_home: Path | None, agents_path: Path | None, dry_run: bool
) -> list[Path]:
    codex_home = (codex_home or Path.home() / ".codex").expanduser()
    agents_path = (agents_path or Path.home() / "AGENTS.md").expanduser()
    _refuse_conflicts(codex_home, agents_path)
    written: list[Path] = []
    conductor_home = codex_home / "conductor"
    hooks_dir = conductor_home / "hooks"
    config_dst = conductor_home / "conductor.toml"
    if not config_dst.exists():
        _write_or_diff(config_dst, _asset_text("config", "conductor.toml"), dry_run)
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
    config_block = "\n".join(
        (
            CONFIG_START,
            "[agents]",
            "max_threads = 8",
            "max_depth = 3",
            "job_max_runtime_seconds = 1800",
            CONFIG_END,
            "",
        )
    )
    _upsert_block(
        codex_home / "config.toml", CONFIG_START, CONFIG_END, config_block, dry_run
    )
    written.append(codex_home / "config.toml")
    policy = _render_policy(provider="codex")
    _upsert_block(agents_path, POLICY_START, POLICY_END, policy, dry_run)
    written.append(agents_path)
    return written


def _uninstall_codex(
    codex_home: Path | None, agents_path: Path | None, dry_run: bool
) -> list[Path]:
    codex_home = (codex_home or Path.home() / ".codex").expanduser()
    agents_path = (agents_path or Path.home() / "AGENTS.md").expanduser()
    changed: list[Path] = []
    _remove_block(codex_home / "config.toml", CONFIG_START, CONFIG_END, dry_run)
    changed.append(codex_home / "config.toml")
    _remove_block(agents_path, POLICY_START, POLICY_END, dry_run)
    changed.append(agents_path)
    return changed


def _refuse_conflicts(codex_home: Path, agents_path: Path) -> None:
    config = codex_home / "config.toml"
    hooks = codex_home / "hooks.json"
    for path in (config, hooks, agents_path):
        _assert_safe_path(path)
    if config.exists():
        text = config.read_text(encoding="utf-8")
        try:
            config_value = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise ManagedBlockError(f"invalid Codex config {config}: {exc}") from exc
        disabled_reason = _codex_user_hooks_disabled_reason(config_value)
        if disabled_reason is not None:
            raise ManagedBlockError(f"{config} disables user hooks: {disabled_reason}")
        unmanaged = _strip_block(text, CONFIG_START, CONFIG_END)
        if (
            "[agents]" in unmanaged
            or "[rollout_budget]" in unmanaged
            or "[hooks]" in unmanaged
        ):
            raise ManagedBlockError(
                f"unmanaged agents/hooks/rollout_budget table in {config}"
            )
    if hooks.exists():
        hooks_text = hooks.read_text(encoding="utf-8")
        try:
            hooks_value = json.loads(hooks_text)
        except json.JSONDecodeError as exc:
            raise ManagedBlockError(f"invalid Codex hooks file {hooks}: {exc}") from exc
        owned = isinstance(hooks_value, dict) and (
            hooks_value.get("description") == "Managed by codex-conductor"
            or hooks_value.get("_managed_by") == "codex-conductor"
        )
        if not owned:
            raise ManagedBlockError(f"foreign hooks file {hooks}")
    if agents_path.exists():
        _strip_block(agents_path.read_text(encoding="utf-8"), POLICY_START, POLICY_END)


def _codex_user_hooks_disabled_reason(config: object) -> str | None:
    if not isinstance(config, dict):
        return None
    if config.get("allow_managed_hooks_only") is True:
        return "allow_managed_hooks_only = true skips ~/.codex/hooks.json"
    features = config.get("features")
    if not isinstance(features, dict):
        return None
    if features.get("hooks") is False:
        return "features.hooks = false"
    if "hooks" not in features and features.get("codex_hooks") is False:
        return "features.codex_hooks = false"
    return None


def _hook_command(script: Path, *args: str) -> str:
    parts = [sys.executable, str(script), *args]
    if os.name == "nt":
        return " ".join(
            f'"{part}"' if (" " in part or "\t" in part) else part for part in parts
        )
    return " ".join(shlex.quote(part) for part in parts)


def _render_hooks_json(hooks_dir: Path) -> str:
    def command(module: str) -> str:
        return _hook_command(hooks_dir / f"{module}.py")

    collaboration_tools = (
        "spawn_agent",
        "collaboration.spawn_agent",
        "assign_agent_task",
        "collaboration.assign_agent_task",
        "followup_task",
        "collaboration.followup_task",
        "send_message",
        "collaboration.send_message",
        "send_agent_message",
    )
    collaboration_matcher = "|".join(collaboration_tools)

    data = {
        "description": "Managed by codex-conductor",
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
                    "matcher": collaboration_matcher,
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
            "PostToolUse": [
                {
                    "matcher": collaboration_matcher,
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("lifecycle"),
                            "timeout": 5,
                            "statusMessage": "Linking conductor lifecycle",
                        }
                    ],
                }
            ],
            "SubagentStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("lifecycle"),
                            "timeout": 5,
                        }
                    ]
                }
            ],
            "SubagentStop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": command("lifecycle"),
                            "timeout": 5,
                        }
                    ]
                }
            ],
        },
    }
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


# --------------------------------------------------------------------------- #
# Claude Code
# --------------------------------------------------------------------------- #


def _install_claude(
    claude_home: Path | None, claude_md_path: Path | None, dry_run: bool
) -> list[Path]:
    claude_home = (claude_home or Path.home() / ".claude").expanduser()
    claude_md_path = (claude_md_path or claude_home / "CLAUDE.md").expanduser()
    written: list[Path] = []
    conductor_home = claude_home / "conductor"
    hooks_dir = conductor_home / "hooks"
    config_dst = conductor_home / "conductor.toml"
    if not config_dst.exists():
        _write_or_diff(
            config_dst, _asset_text("config", "conductor.claude.toml"), dry_run
        )
        written.append(config_dst)
    for module in ("pre_tool_use", "lifecycle", "session_start"):
        dst = hooks_dir / f"{module}.py"
        _write_or_diff(
            dst, _wrapper(module, "claude", conductor_home=conductor_home), dry_run
        )
        written.append(dst)
    settings_path = claude_home / "settings.json"
    _merge_claude_settings(settings_path, hooks_dir, dry_run)
    written.append(settings_path)
    policy = _render_policy(provider="claude")
    _upsert_block(claude_md_path, POLICY_START, POLICY_END, policy, dry_run)
    written.append(claude_md_path)
    return written


def _uninstall_claude(
    claude_home: Path | None, claude_md_path: Path | None, dry_run: bool
) -> list[Path]:
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
            "hooks": [
                {
                    "type": "command",
                    "command": command("session_start"),
                    "timeout": 5,
                    "statusMessage": "Starting conductor ledger",
                }
            ],
        },
        "PreToolUse": {
            "matcher": "Task",
            "hooks": [
                {
                    "type": "command",
                    "command": command("pre_tool_use"),
                    "timeout": 5,
                    "statusMessage": "Checking conductor policy",
                }
            ],
        },
        "PostToolUse": {
            "matcher": "Task",
            "hooks": [
                {
                    "type": "command",
                    "command": command("lifecycle"),
                    "timeout": 5,
                    "statusMessage": "Linking conductor lifecycle",
                }
            ],
        },
        "SubagentStart": {
            "hooks": [
                {"type": "command", "command": command("lifecycle"), "timeout": 5}
            ],
        },
        "SubagentStop": {
            "hooks": [
                {"type": "command", "command": command("lifecycle"), "timeout": 5}
            ],
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
            raise ManagedBlockError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ManagedBlockError(f"{path} does not contain a JSON object")
        settings = loaded
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    for event, entry in _claude_hook_entries(hooks_dir).items():
        current = hooks.get(event)
        current = current if isinstance(current, list) else []
        filtered = [
            item for item in current if not _is_conductor_entry(item, hooks_dir)
        ]
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
        filtered = [
            item for item in current if not _is_conductor_entry(item, hooks_dir)
        ]
        if len(filtered) == len(current):
            continue
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
        env_lines += (
            f"os.environ.setdefault('CODEX_CONDUCTOR_HOME', {str(conductor_home)!r})\n"
        )
    if sessions_root is not None:
        env_lines += f"os.environ.setdefault('CODEX_CONDUCTOR_SESSIONS_ROOT', {str(sessions_root)!r})\n"
    if models_cache is not None:
        env_lines += (
            f"os.environ.setdefault('CODEX_MODELS_CACHE', {str(models_cache)!r})\n"
        )
    return (
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import os\n"
        f"{env_lines}"
        f"from conductor.hooks.{module} import main\n"
        f"raise SystemExit({call})\n"
    )


def _asset_text(*parts: str) -> str:
    return files("conductor.assets").joinpath(*parts).read_text(encoding="utf-8")


def _render_policy(project_root: Path | None = None, provider: str = "codex") -> str:
    name = (
        "orchestration-policy.md"
        if provider == "codex"
        else f"orchestration-policy.{provider}.md"
    )
    template = _asset_text("policy", name)
    if project_root is None:
        return template
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
    if _TRANSACTION is not None:
        _TRANSACTION.stage(path, text)
        return
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if old == text:
        return
    if dry_run:
        print(
            "".join(
                difflib.unified_diff(
                    old.splitlines(True),
                    text.splitlines(True),
                    fromfile=str(path),
                    tofile=str(path),
                )
            )
        )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _assert_safe_path(path: Path) -> None:
    current = Path(path)
    while True:
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise InstallationConflictError(
                f"cannot inspect install path {current}: {exc}"
            ) from exc
        else:
            if is_unsafe_path_redirect(current, metadata):
                raise InstallationConflictError(
                    f"install path is a symbolic link or reparse point: {current}"
                )
        parent = current.parent
        if parent == current:
            break
        current = parent


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_manifest(path: Path) -> dict | None:
    if not path.exists():
        return None
    _assert_safe_path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallationConflictError(
            f"invalid managed manifest {path}: {exc}"
        ) from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise InstallationConflictError(f"invalid managed manifest {path}")
    if not isinstance(value.get("files"), dict):
        raise InstallationConflictError(f"invalid managed manifest file map {path}")
    return value


def _verify_managed_files(
    path: Path,
    *,
    provider_root: Path,
    provider: str,
    repair: bool,
) -> None:
    manifest = _load_manifest(path)
    if manifest is None:
        return
    _validate_manifest_paths(manifest, provider_root, provider)
    for raw_path, record in manifest["files"].items():
        if not isinstance(raw_path, str) or not isinstance(record, dict):
            raise InstallationConflictError(
                f"invalid managed manifest entry: {raw_path!r}"
            )
        if record.get("ownership") != "full":
            continue
        target = Path(raw_path)
        _assert_safe_path(target)
        expected = record.get("sha256")
        if target.exists() and expected != _file_sha256(target) and not repair:
            raise InstallationConflictError(f"managed file was modified: {target}")


def _validate_manifest_paths(
    manifest: dict, provider_root: Path, provider: str
) -> None:
    if manifest.get("provider") != provider:
        raise InstallationConflictError(
            "managed manifest provider does not match the requested provider"
        )
    for raw_path, record in manifest["files"].items():
        if not isinstance(raw_path, str) or not isinstance(record, dict):
            raise InstallationConflictError("managed manifest contains an invalid path")
        if record.get("ownership") != "full":
            continue
        path = Path(raw_path)
        allowed = path.parent == provider_root / "conductor" / "hooks"
        if provider == "codex" and path == provider_root / "hooks.json":
            allowed = True
        if not allowed:
            raise InstallationConflictError(
                f"managed manifest contains an out-of-scope owned path: {path}"
            )


def _render_manifest(
    provider: str,
    provider_root: Path,
    transaction: _FileTransaction,
) -> str:
    conductor_home = provider_root / "conductor"
    records: dict[str, dict[str, str]] = {}
    for path, text in sorted(
        transaction.changes.items(), key=lambda item: str(item[0])
    ):
        if text is None:
            continue
        if path.parent == conductor_home / "hooks" or (
            provider == "codex" and path == provider_root / "hooks.json"
        ):
            ownership = "full"
        elif path == conductor_home / "conductor.toml":
            ownership = "seed"
        else:
            ownership = "composite"
        record = {"ownership": ownership, "sha256": _text_sha256(text)}
        if ownership == "composite":
            record["managed_sha256"] = _text_sha256(_managed_fragment(text))
        records[str(path)] = record
    payload = {
        "schema_version": 1,
        "provider": provider,
        "files": records,
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _managed_fragment(text: str) -> str:
    for start, end in (
        (CONFIG_START, CONFIG_END),
        (POLICY_START, POLICY_END),
    ):
        if start in text and end in text:
            before, remainder = text.split(start, 1)
            del before
            body, _ = remainder.split(end, 1)
            return start + body + end
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    hooks = value.get("hooks") if isinstance(value, dict) else None
    if not isinstance(hooks, dict):
        return text
    managed: dict[str, list[dict]] = {}
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            continue
        selected = [
            entry
            for entry in entries
            if isinstance(entry, dict)
            and any(
                "conductor" in str(hook.get("command", ""))
                for hook in entry.get("hooks", [])
                if isinstance(hook, dict)
            )
        ]
        if selected:
            managed[str(event)] = selected
    return json.dumps(managed, sort_keys=True, separators=(",", ":"))


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_RDONLY)
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        if descriptor is not None:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="codex", choices=["codex", "claude"])
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--agents-path", type=Path)
    parser.add_argument("--claude-home", type=Path)
    parser.add_argument("--claude-md-path", type=Path)
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument(
        "--repair",
        action="store_true",
        help="restore modified conductor-owned files from the installed package",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.uninstall and args.repair:
        parser.error("--repair cannot be combined with --uninstall")
    try:
        if args.uninstall:
            paths = uninstall(
                args.codex_home,
                args.agents_path,
                args.dry_run,
                provider=args.provider,
                claude_home=args.claude_home,
                claude_md_path=args.claude_md_path,
            )
        else:
            paths = install(
                args.codex_home,
                args.agents_path,
                args.dry_run,
                provider=args.provider,
                claude_home=args.claude_home,
                claude_md_path=args.claude_md_path,
                repair=args.repair,
            )
    except InstallationConflictError as exc:
        print(f"conductor install: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
