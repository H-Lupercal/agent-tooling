from __future__ import annotations

from toolbelt.models import Action, Evidence, Recommendation, Tool


def render_evidence(evidence: list[Evidence]) -> str:
    return "\n".join(f"- {e.type}:{e.key} ({e.detail})" for e in evidence)


def render_recommendations(recs: list[Recommendation], catalog: list[Tool], mode: str, min_confidence: int) -> str:
    by_tool = {tool.id: tool for tool in catalog}
    planned: list[str] = []
    provisional: list[str] = []
    candidates: list[str] = []
    unapproved: list[str] = []
    for rec in recs:
        tool = by_tool[rec.tool_id]
        line = f"- {rec.tool_id} confidence={rec.confidence} {tool.summary}"
        if not tool.approved:
            unapproved.append(line)
        elif rec.provisional:
            provisional.append(line)
        elif rec.confidence >= min_confidence:
            planned.append(line)
        else:
            candidates.append(line)
    sections = [f"Mode: {mode}", "Planned", *(planned or ["- none"]), "Provisional (brief-only)", *(provisional or ["- none"]), "Candidates (weak evidence)", *(candidates or ["- none"]), "Unapproved", *(unapproved or ["- none"])]
    return "\n".join(sections)


def action_card(action: Action) -> str:
    lines = [
        f"[{action.id}] {action.op} {action.tool_id}",
        f"purpose: {action.purpose}",
        f"provenance: {action.provenance}",
        f"permissions: {', '.join(action.permissions) if action.permissions else 'none'}",
        f"scope: {action.install_scope}",
        f"secrets: {', '.join(action.secrets_required) if action.secrets_required else 'none'}",
        f"evidence: {', '.join(f'{e.type}:{e.key}' for e in action.evidence) if action.evidence else 'none'}",
        "steps:",
    ]
    for step in action.steps:
        if step.argv:
            lines.append(f"  - {' '.join(step.argv)}")
        else:
            lines.append(f"  - {step.apply_via} {step.scaffold_path}")
    if not action.steps and action.verify_argv:
        lines.append(f"  - verify: {' '.join(action.verify_argv)}")
    lines.append(f"rollback: {action.rollback}")
    return "\n".join(lines)


def render_status(manifest: dict, audit: dict) -> str:
    lines = ["Tools"]
    for tool_id, record in sorted((manifest.get("tools") or {}).items()):
        lines.append(f"- {tool_id}: {record.get('state', 'unknown')}")
    lines.append("Audit")
    for key, value in audit.items():
        if value:
            lines.append(f"- {key}: {value}")
    return "\n".join(lines)


def render_reconcile(report: dict) -> str:
    lines = ["Reconcile"]
    for key, value in report.items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines)
