from __future__ import annotations

from pathlib import Path

from toolbelt.brief import find_brief, parse_brief
from toolbelt.evidence import scan
from toolbelt.harness import live_state
from toolbelt.manifest import unmanaged_and_drift
from toolbelt.models import Tool
from toolbelt.plan import build_plan
from toolbelt.recommend import recommend


def reconcile(root: Path, catalog: list[Tool], manifest: dict) -> tuple[object, dict]:
    evidence = scan(root)
    brief = find_brief(root)
    if brief:
        evidence.extend(parse_brief(brief, catalog))
    recs = recommend(catalog, evidence, mode=manifest.get("mode") or "existing", root=root)
    live = live_state(root)
    drift = unmanaged_and_drift(manifest, live)
    classification: dict[str, str] = {}
    evidence_tools = {rec.tool_id for rec in recs if not rec.provisional}
    foundational = {tool.id for tool in catalog if tool.foundational}
    for tool_id, rec in (manifest.get("tools") or {}).items():
        if tool_id in drift["drifted_missing"]:
            classification[tool_id] = "drifted_missing"
        elif rec.get("state") == "installed" and (tool_id in evidence_tools or tool_id in foundational):
            classification[tool_id] = "aligned"
        elif rec.get("state") == "installed":
            classification[tool_id] = "stale"
        else:
            classification[tool_id] = rec.get("state", "unknown")
    declared = set((manifest.get("intent") or {}).get("declared_stack") or [])
    observed = {e.key for e in evidence if e.type == "lang_ext"}
    intent_divergence = {
        "declared_not_observed": sorted(declared - observed),
        "observed_not_declared": sorted(observed - declared) if declared else [],
    }
    plan = build_plan(recs, catalog, manifest, mode=manifest.get("mode") or "existing", project_root=root, prune=True)
    report = {
        "classification": classification,
        "unmanaged": drift["unmanaged"],
        "intent_divergence": intent_divergence,
        "warnings": live.get("warnings", []),
    }
    return plan, report
