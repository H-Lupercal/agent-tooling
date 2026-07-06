from __future__ import annotations

import dataclasses
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from toolbelt import guard
from toolbelt.harness import ALREADY_EXISTS_PATTERNS, run_step
from toolbelt.manifest import load_manifest, remove_tool_record, save_manifest, upsert_tool
from toolbelt.models import Action, Plan, Tool
from toolbelt.render import action_card


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def approve_interactively(plan: Plan, *, assume_yes: bool, only: set[str] | None, input_fn=input, out=None) -> Plan:
    import sys

    out = out or sys.stdout
    if assume_yes and only is not None:
        raise ValueError("--yes and --only are mutually exclusive")
    if assume_yes:
        return dataclasses.replace(plan, actions=tuple(dataclasses.replace(a, approved=True) for a in plan.actions))
    if only is not None:
        return dataclasses.replace(plan, actions=tuple(dataclasses.replace(a, approved=a.id in only) for a in plan.actions))
    approved: list[Action] = []
    approve_all = False
    quit_all = False
    for action in plan.actions:
        if approve_all:
            approved.append(dataclasses.replace(action, approved=True))
            continue
        if quit_all:
            approved.append(dataclasses.replace(action, approved=False))
            continue
        print(action_card(action), file=out)
        response = input_fn(f"[{action.id}] {action.op} {action.tool_id} — approve? [y]es/[n]o/[A]ll/[q]uit: ")
        response = response.strip().lower() or "n"
        if response == "y":
            approved.append(dataclasses.replace(action, approved=True))
        elif response == "a":
            approve_all = True
            approved.append(dataclasses.replace(action, approved=True))
        elif response == "q":
            quit_all = True
            approved.append(dataclasses.replace(action, approved=False))
        else:
            approved.append(dataclasses.replace(action, approved=False))
    return dataclasses.replace(plan, actions=tuple(approved))


def _stderr_matches(log: Path, action_id: str) -> bool:
    if not log.exists():
        return False
    last = None
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("action_id") == action_id:
            last = obj
    stderr = str((last or {}).get("stderr", "")).lower()
    return any(pattern in stderr for pattern in ALREADY_EXISTS_PATTERNS)


def _verify(action: Action, root: Path) -> str:
    if not action.verify_argv:
        return "never"
    try:
        result = subprocess.run(list(action.verify_argv), cwd=root, capture_output=True, text=True, timeout=180)
        return "passed" if result.returncode == 0 else "failed"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return "failed"


def _live_names(action: Action) -> dict:
    names: dict[str, str] = {}
    for step in action.steps:
        if step.apply_via == "claude_mcp":
            names["claude_mcp"] = action.tool_id.removeprefix("mcp-")
        elif step.apply_via == "codex_mcp":
            names["codex_mcp"] = action.tool_id.removeprefix("mcp-")
        elif step.apply_via == "claude_plugin" and step.argv:
            names["claude_plugin"] = step.argv[-1]
    return names


def _record(action: Action, catalog_by_id: dict[str, Tool], verify_status: str) -> dict:
    tool = catalog_by_id.get(action.tool_id)
    executed = [
        {
            "apply_via": s.apply_via,
            "harness": s.harness,
            "argv": list(s.argv),
            "exit_code": 0,
            "rollback_argv": list(s.rollback_argv),
            "scaffold_path": s.scaffold_path,
            "scaffold_sha256": s.scaffold_sha256,
        }
        for s in action.steps
    ]
    root = Path(action.install_scope)
    del root
    return {
        "state": "installed" if verify_status in {"passed", "never"} else "verify_failed",
        "kind": action.kind,
        "catalog_version": tool.catalog_version if tool else "",
        "installed_at": _now(),
        "harnesses": list(action.harnesses),
        "provenance": action.provenance,
        "install_scope": action.install_scope,
        "live_names": _live_names(action),
        "executed_steps": executed,
        "secrets_required": [],
        "artifacts": list(tool.artifacts if tool else ()),
        "verify": {"argv": list(action.verify_argv), "last_status": verify_status, "at": _now()},
        "evidence_refs": [f"{e.type}:{e.key}" for e in action.evidence],
    }


def apply_plan(plan: Plan, root: Path, *, dry_run: bool, catalog: list[Tool] | None = None) -> dict:
    root = Path(root)
    if dry_run:
        for action in plan.actions:
            if action.approved:
                for step in action.steps:
                    if step.argv:
                        print(" ".join(step.argv))
                    else:
                        print(f"{step.apply_via} {step.scaffold_path}")
        return {"applied": [], "skipped": [a.id for a in plan.actions if not a.approved], "failed": []}

    catalog_by_id = {tool.id: tool for tool in (catalog or [])}
    log = root / ".toolbelt" / "state" / f"apply-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.jsonl"
    applied: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    manifest = load_manifest(root)
    for action in plan.actions:
        if not action.approved:
            skipped.append(action.id)
            continue
        action_failed = False
        for index, step in enumerate(action.steps):
            rc = run_step(step, cwd=root, dry_run=False, log=log, action_id=action.id)
            if rc != 0 and not step.tolerate_failure and not _stderr_matches(log, action.id):
                failed.append({"id": action.id, "rc": rc, "step_index": index})
                action_failed = True
                break
        if action_failed:
            continue
        if action.op == "remove":
            manifest = remove_tool_record(manifest, action.tool_id)
        else:
            status = _verify(action, root)
            record = _record(action, catalog_by_id, status)
            record["secrets_required"] = [
                {"env": env_name, "status": guard.secret_status(env_name, root)}
                for env_name in action.secrets_required
            ]
            manifest = upsert_tool(manifest, action.tool_id, record)
        save_manifest(root, manifest)
        applied.append(action.id)

    artifacts: list[str] = []
    for rec in (manifest.get("tools") or {}).values():
        if rec.get("state") == "installed":
            artifacts.extend(rec.get("artifacts") or [])
    guard.ensure_gitignore(root, extra=artifacts)
    return {"applied": applied, "skipped": skipped, "failed": failed}
