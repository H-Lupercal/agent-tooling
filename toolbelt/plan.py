from __future__ import annotations

import dataclasses
import os
from datetime import datetime, timezone
from pathlib import Path

from toolbelt.models import Action, ApplyStep, Evidence, Plan, Recommendation, Tool


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _min_confidence() -> int:
    try:
        return int(os.environ.get("TOOLBELT_MIN_CONFIDENCE", "2"))
    except ValueError:
        return 2


def _tool_map(catalog: list[Tool]) -> dict[str, Tool]:
    return {tool.id: tool for tool in catalog}


def _rec_map(recs: list[Recommendation]) -> dict[str, Recommendation]:
    return {rec.tool_id: rec for rec in recs}


def _reverse_steps(record: dict) -> tuple[ApplyStep, ...]:
    steps: list[ApplyStep] = []
    for executed in reversed(record.get("executed_steps", [])):
        if executed.get("apply_via") == "scaffold":
            steps.append(
                ApplyStep(
                    "scaffold_remove",
                    str(executed.get("harness", "")),
                    scaffold_path=str(executed.get("scaffold_path", "")),
                    scaffold_sha256=str(executed.get("scaffold_sha256", "")),
                )
            )
        elif executed.get("apply_via") == "managed_block":
            steps.append(
                ApplyStep(
                    "managed_block_remove",
                    str(executed.get("harness", "")),
                    block_path=str(executed.get("block_path", "")),
                    block_marker=str(executed.get("block_marker", "")),
                )
            )
        else:
            steps.append(
                ApplyStep(
                    str(executed.get("apply_via", "")),
                    str(executed.get("harness", "")),
                    argv=tuple(str(v) for v in executed.get("rollback_argv", [])),
                    rollback_argv=(),
                    tolerate_failure=True,
                )
            )
    return tuple(steps)


def _action(
    op: str,
    tool: Tool,
    rec: Recommendation | None,
    root: Path,
    steps: tuple[ApplyStep, ...],
) -> Action:
    evidence = rec.matched if rec else ()
    harnesses = tuple(sorted({s.harness for s in tool.apply if s.harness}))
    purpose = tool.summary if op != "install" else (tool.summary if rec else "Foundational baseline")
    rollback = "Run recorded rollback steps in reverse order" if op in {"install", "update", "remove"} else "No mutation"
    return Action(
        id="",
        op=op,
        tool_id=tool.id,
        kind=tool.kind,
        harnesses=harnesses,
        purpose=purpose,
        provenance=tool.provenance,
        permissions=tool.permissions,
        install_scope=tool.install_scope,
        secrets_required=tool.secrets,
        evidence=evidence,
        steps=steps,
        verify_argv=tool.verify_argv,
        rollback=rollback,
        approved=None,
    )


def build_plan(
    recs: list[Recommendation],
    catalog: list[Tool],
    manifest: dict,
    *,
    mode: str,
    project_root: Path,
    prune: bool = False,
) -> Plan:
    from toolbelt.harness import concrete_steps

    by_tool = _tool_map(catalog)
    by_rec = _rec_map(recs)
    selected: set[str] = set()
    min_conf = _min_confidence()
    if mode == "greenfield":
        for tool in catalog:
            if tool.approved and tool.foundational:
                selected.add(tool.id)
    for rec in recs:
        tool = by_tool[rec.tool_id]
        if not tool.approved:
            continue
        if rec.provisional:
            continue
        if rec.confidence >= min_conf:
            selected.add(tool.id)

    buckets: dict[str, list[Action]] = {"install": [], "update": [], "verify": [], "remove": []}
    tools_manifest = manifest.get("tools") or {}
    for tool_id in sorted(selected):
        tool = by_tool[tool_id]
        rec = by_rec.get(tool_id)
        record = tools_manifest.get(tool_id)
        if record is None or record.get("state") == "removed":
            steps = concrete_steps(tool, tool.install_scope)
            buckets["install"].append(_action("install", tool, rec, project_root, steps))
        elif record.get("state") == "installed" and record.get("catalog_version") != tool.catalog_version:
            steps = tuple(dataclasses.replace(s, tolerate_failure=True) for s in _reverse_steps(record)) + concrete_steps(
                tool, tool.install_scope
            )
            buckets["update"].append(_action("update", tool, rec, project_root, steps))
        elif record.get("state") in {"verify_failed", "unknown"}:
            buckets["verify"].append(_action("verify", tool, rec, project_root, ()))

    if prune:
        for tool_id, record in sorted(tools_manifest.items()):
            if record.get("state") != "installed" or tool_id in selected:
                continue
            tool = by_tool.get(tool_id)
            if tool and tool.foundational:
                continue
            if tool is None:
                tool = Tool(tool_id, "dev_tool", tool_id, "", "", "", True, False, (), "user", (), (), "", (), (), (), "")
            buckets["remove"].append(_action("remove", tool, by_rec.get(tool_id), project_root, _reverse_steps(record)))

    actions: list[Action] = []
    for op in ("install", "update", "verify", "remove"):
        actions.extend(sorted(buckets[op], key=lambda a: a.tool_id))
    numbered = tuple(dataclasses.replace(action, id=f"a{i}") for i, action in enumerate(actions, start=1))
    return Plan(1, _now(), str(Path(project_root).resolve()), mode, numbered)


def _ev_to_json(e: Evidence) -> dict:
    return dataclasses.asdict(e)


def _step_to_json(step: ApplyStep) -> dict:
    return {
        "apply_via": step.apply_via,
        "harness": step.harness,
        "argv": list(step.argv),
        "scaffold_path": step.scaffold_path,
        "scaffold_body": step.scaffold_body,
        "scaffold_sha256": step.scaffold_sha256,
        "rollback_argv": list(step.rollback_argv),
        "tolerate_failure": step.tolerate_failure,
        "block_path": step.block_path,
        "block_body": step.block_body,
        "block_marker": step.block_marker,
    }


def plan_to_json(plan: Plan) -> dict:
    return {
        "schema_version": plan.schema_version,
        "generated_at": plan.generated_at,
        "project_root": plan.project_root,
        "mode": plan.mode,
        "actions": [
            {
                "id": a.id,
                "op": a.op,
                "tool_id": a.tool_id,
                "kind": a.kind,
                "harnesses": list(a.harnesses),
                "purpose": a.purpose,
                "provenance": a.provenance,
                "permissions": list(a.permissions),
                "install_scope": a.install_scope,
                "secrets_required": list(a.secrets_required),
                "evidence": [_ev_to_json(e) for e in a.evidence],
                "steps": [_step_to_json(s) for s in a.steps],
                "verify_argv": list(a.verify_argv),
                "rollback": a.rollback,
                "approved": a.approved,
            }
            for a in plan.actions
        ],
    }


def _ev_from_json(obj: dict) -> Evidence:
    return Evidence(str(obj["type"]), str(obj["key"]), str(obj["detail"]), int(obj["weight"]), str(obj["source"]))


def _step_from_json(obj: dict) -> ApplyStep:
    return ApplyStep(
        str(obj["apply_via"]),
        str(obj.get("harness", "")),
        argv=tuple(str(v) for v in obj.get("argv", [])),
        scaffold_path=str(obj.get("scaffold_path", "")),
        scaffold_body=str(obj.get("scaffold_body", "")),
        scaffold_sha256=str(obj.get("scaffold_sha256", "")),
        rollback_argv=tuple(str(v) for v in obj.get("rollback_argv", [])),
        tolerate_failure=bool(obj.get("tolerate_failure", False)),
        block_path=str(obj.get("block_path", "")),
        block_body=str(obj.get("block_body", "")),
        block_marker=str(obj.get("block_marker", "")),
    )


def plan_from_json(obj: dict) -> Plan:
    if obj.get("schema_version") != 1:
        raise ValueError(f"unsupported plan schema_version: {obj.get('schema_version')}")
    actions = []
    for raw in obj.get("actions", []):
        actions.append(
            Action(
                id=str(raw["id"]),
                op=str(raw["op"]),
                tool_id=str(raw["tool_id"]),
                kind=str(raw["kind"]),
                harnesses=tuple(str(v) for v in raw.get("harnesses", [])),
                purpose=str(raw.get("purpose", "")),
                provenance=str(raw.get("provenance", "")),
                permissions=tuple(str(v) for v in raw.get("permissions", [])),
                install_scope=str(raw.get("install_scope", "")),
                secrets_required=tuple(str(v) for v in raw.get("secrets_required", [])),
                evidence=tuple(_ev_from_json(e) for e in raw.get("evidence", [])),
                steps=tuple(_step_from_json(s) for s in raw.get("steps", [])),
                verify_argv=tuple(str(v) for v in raw.get("verify_argv", [])),
                rollback=str(raw.get("rollback", "")),
                approved=raw.get("approved"),
            )
        )
    return Plan(1, str(obj["generated_at"]), str(obj["project_root"]), str(obj["mode"]), tuple(actions))


def write_plan(plan: Plan, path: Path) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan_to_json(plan), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_plan(path: Path) -> Plan:
    import json

    return plan_from_json(json.loads(path.read_text(encoding="utf-8")))
