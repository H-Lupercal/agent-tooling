from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path

from toolbelt.models import ApplyStep, Tool


WARNINGS: list[str] = []
ALREADY_EXISTS_PATTERNS = ("already exists", "exists", "already installed")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def claude_bin() -> str:
    return os.environ.get("TOOLBELT_CLAUDE_BIN", "claude")


def codex_bin() -> str:
    return os.environ.get("TOOLBELT_CODEX_BIN", "codex")


def concrete_steps(tool: Tool, scope: str) -> tuple[ApplyStep, ...]:
    steps: list[ApplyStep] = []
    for step in tool.apply:
        if step.apply_via == "claude_mcp":
            argv = (claude_bin(), "mcp", "add", "-s", scope, tool.mcp_name, "--", step.mcp_command, *step.mcp_args)
            rollback = (claude_bin(), "mcp", "remove", "-s", scope, tool.mcp_name)
            steps.append(ApplyStep(step.apply_via, step.harness, argv=argv, rollback_argv=rollback))
        elif step.apply_via == "codex_mcp":
            argv = (codex_bin(), "mcp", "add", tool.mcp_name, "--", step.mcp_command, *step.mcp_args)
            rollback = (codex_bin(), "mcp", "remove", tool.mcp_name)
            steps.append(ApplyStep(step.apply_via, step.harness, argv=argv, rollback_argv=rollback))
        elif step.apply_via == "claude_plugin":
            argv = (claude_bin(), "plugin", "install", step.plugin_ref)
            rollback = (claude_bin(), "plugin", "uninstall", step.plugin_ref)
            steps.append(ApplyStep(step.apply_via, step.harness, argv=argv, rollback_argv=rollback))
        elif step.apply_via == "command":
            steps.append(ApplyStep(step.apply_via, step.harness, argv=step.command_argv, rollback_argv=step.rollback_argv))
        elif step.apply_via == "scaffold":
            sha = hashlib.sha256(step.scaffold_body.encode("utf-8")).hexdigest()
            steps.append(
                ApplyStep(
                    step.apply_via,
                    step.harness,
                    scaffold_path=step.scaffold_path,
                    scaffold_body=step.scaffold_body,
                    scaffold_sha256=sha,
                )
            )
    return tuple(steps)


def _append_log(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, sort_keys=True) + "\n")


def run_step(step: ApplyStep, *, cwd: Path, dry_run: bool, log: Path, action_id: str) -> int:
    if dry_run:
        if step.argv:
            print(" ".join(step.argv))
        else:
            print(f"{step.apply_via} {step.scaffold_path}")
        _append_log(log, {"ts": _now(), "action_id": action_id, "apply_via": step.apply_via, "argv": list(step.argv), "scaffold_path": step.scaffold_path, "rc": 0, "dry_run": True})
        return 0

    stdout = ""
    stderr = ""
    rc = 0
    if step.apply_via in {"scaffold", "scaffold_remove"}:
        target = Path(cwd) / step.scaffold_path
        if step.apply_via == "scaffold":
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                rc = 0 if actual == step.scaffold_sha256 else 3
            else:
                target.write_text(step.scaffold_body, encoding="utf-8")
                rc = 0
        else:
            if target.exists():
                actual = hashlib.sha256(target.read_bytes()).hexdigest()
                if actual == step.scaffold_sha256:
                    target.unlink()
                    rc = 0
                else:
                    rc = 3
            else:
                rc = 0
    else:
        try:
            result = subprocess.run(list(step.argv), cwd=cwd, capture_output=True, text=True, timeout=180)
            stdout = result.stdout[:10000]
            stderr = result.stderr[:10000]
            rc = result.returncode
        except FileNotFoundError:
            rc = 127
            stderr = f"{step.argv[0]} not found on PATH; set TOOLBELT_CLAUDE_BIN/TOOLBELT_CODEX_BIN"
        except subprocess.TimeoutExpired as exc:
            rc = 124
            stdout = (exc.stdout or "")[:10000] if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "")[:10000] if isinstance(exc.stderr, str) else ""
    _append_log(
        log,
        {
            "ts": _now(),
            "action_id": action_id,
            "apply_via": step.apply_via,
            "argv": list(step.argv),
            "scaffold_path": step.scaffold_path,
            "rc": rc,
            "stdout": stdout,
            "stderr": stderr,
        },
    )
    return rc


def _warn(message: str) -> None:
    WARNINGS.append(message)


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        _warn(f"unparseable JSON: {path}")
        return {}


def claude_mcp_servers(root: Path) -> dict[str, list[str]]:
    project = _read_json(Path(root) / ".mcp.json")
    state = _read_json(Path(os.environ.get("TOOLBELT_CLAUDE_STATE", str(Path.home() / ".claude.json"))))
    return {
        "project": sorted((project.get("mcpServers") or {}).keys()),
        "local": sorted((((state.get("projects") or {}).get(str(Path(root).resolve())) or {}).get("mcpServers") or {}).keys()),
        "user": sorted((state.get("mcpServers") or {}).keys()),
    }


def codex_mcp_servers() -> list[str]:
    path = Path(os.environ.get("TOOLBELT_CODEX_CONFIG", str(Path.home() / ".codex" / "config.toml")))
    try:
        if not path.exists():
            return []
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return sorted((data.get("mcp_servers") or {}).keys())
    except tomllib.TOMLDecodeError:
        _warn(f"unparseable TOML: {path}")
        return []


def claude_plugins() -> list[str]:
    path = Path(os.environ.get("TOOLBELT_CLAUDE_PLUGINS", str(Path.home() / ".claude" / "plugins" / "installed_plugins.json")))
    data = _read_json(path)
    return sorted((data.get("plugins") or {}).keys())


def live_state(root: Path) -> dict:
    WARNINGS.clear()
    return {
        "claude_mcp": claude_mcp_servers(root),
        "codex_mcp": codex_mcp_servers(),
        "claude_plugin": claude_plugins(),
        "warnings": list(WARNINGS),
    }
