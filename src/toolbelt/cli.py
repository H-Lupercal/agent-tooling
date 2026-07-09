from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path

from toolbelt import discover
from toolbelt.brief import brief_goals, brief_stack, copy_brief, find_brief, is_greenfield, parse_brief, sha256_file
from toolbelt.catalog import CatalogError, load_catalog, safety_lint
from toolbelt.evidence import evidence_sha256, scan
from toolbelt.guard import audit, ensure_gitignore
from toolbelt.harness import live_state
from toolbelt.manifest import ManifestError, load_manifest, save_manifest
from toolbelt.plan import build_plan, plan_to_json, read_plan, write_plan
from toolbelt.recommend import recommend
from toolbelt.render import action_card, render_evidence, render_recommendations, render_reconcile, render_status


def _root(path: str) -> Path:
    root = Path(path).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"path not found: {path}")
    return root


def _mode(root: Path, manifest: dict) -> str:
    return manifest.get("mode") or ("greenfield" if is_greenfield(root) else "existing")


def _scan_bundle(root: Path, catalog) -> tuple[str, list, list, dict]:
    manifest = load_manifest(root)
    mode = _mode(root, manifest)
    evidence = scan(root)
    brief = find_brief(root)
    if brief:
        evidence.extend(parse_brief(brief, catalog))
    recs = recommend(catalog, evidence, mode=mode, root=root)
    manifest["mode"] = mode
    manifest["last_scan"] = {
        "evidence_sha256": evidence_sha256(evidence),
        "evidence": [dataclasses.asdict(e) for e in evidence],
    }
    save_manifest(root, manifest)
    return mode, evidence, recs, manifest


def _plan(root: Path, catalog, prune: bool = False):
    mode, evidence, recs, manifest = _scan_bundle(root, catalog)
    del evidence
    return build_plan(recs, catalog, manifest, mode=mode, project_root=root, prune=prune)


def _cmd_scan(args) -> int:
    root = _root(args.path)
    catalog = load_catalog()
    mode, evidence, recs, _ = _scan_bundle(root, catalog)
    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "evidence": [dataclasses.asdict(e) for e in evidence],
                    "recommendations": [
                        {
                            "tool_id": r.tool_id,
                            "confidence": r.confidence,
                            "provisional": r.provisional,
                            "matched": [dataclasses.asdict(e) for e in r.matched],
                        }
                        for r in recs
                    ],
                },
                sort_keys=True,
            )
        )
    else:
        print(render_evidence(evidence))
        print(render_recommendations(recs, catalog, mode, int(os.environ.get("TOOLBELT_MIN_CONFIDENCE", "2"))))
    return 0


def _cmd_init(args) -> int:
    root = _root(args.path)
    if args.brief and not Path(args.brief).exists():
        print(f"brief not found: {args.brief}", file=sys.stderr)
        return 2
    manifest = load_manifest(root)
    manifest["mode"] = "greenfield"
    if args.brief:
        brief = copy_brief(Path(args.brief), root)
        manifest["intent"] = {
            "brief_path": ".toolbelt/brief.md",
            "brief_sha256": sha256_file(brief),
            "declared_stack": brief_stack(brief),
            "goals": brief_goals(brief),
        }
    save_manifest(root, manifest)
    return _cmd_plan(args)


def _cmd_plan(args) -> int:
    root = _root(args.path)
    catalog = load_catalog()
    plan = _plan(root, catalog, prune=getattr(args, "prune", False))
    out = Path(getattr(args, "out", "") or root / ".toolbelt" / "plan.json")
    write_plan(plan, out)
    if getattr(args, "json", False):
        print(json.dumps(plan_to_json(plan), sort_keys=True))
    else:
        print(f"Plan: {len(plan.actions)} actions")
        for action in plan.actions:
            print(action_card(action))
    return 0


def _cmd_apply(args) -> int:
    from toolbelt.apply import apply_plan, approve_interactively

    root = _root(args.path)
    catalog = load_catalog()
    plan_path = Path(args.plan) if args.plan else root / ".toolbelt" / "plan.json"
    plan = read_plan(plan_path) if plan_path.exists() else _plan(root, catalog)
    only = set(args.only.split(",")) if args.only else None
    try:
        plan = approve_interactively(plan, assume_yes=args.yes, only=only)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    dry_run = args.dry_run or os.environ.get("TOOLBELT_DRY_RUN") == "1"
    summary = apply_plan(plan, root, dry_run=dry_run, catalog=catalog)
    print(json.dumps(summary, sort_keys=True))
    if any(item.get("rc") == 3 for item in summary["failed"]):
        return 3
    return 1 if summary["failed"] else 0


def _cmd_status(args) -> int:
    root = _root(args.path)
    catalog = load_catalog()
    manifest = load_manifest(root)
    aud = audit(root, manifest, live_state(root), catalog)
    if args.json:
        print(json.dumps({"tools": manifest.get("tools", {}), "audit": aud}, sort_keys=True))
    else:
        print(render_status(manifest, aud))
    return 1 if aud.get("tracked_secrets") else 0


def _cmd_guard(args) -> int:
    root = _root(args.path)
    catalog = load_catalog()
    manifest = load_manifest(root)
    if args.fix:
        ensure_gitignore(root)
    aud = audit(root, manifest, live_state(root), catalog)
    print(render_status(manifest, aud))
    if aud.get("tracked_secrets"):
        print("Run: git rm --cached .toolbelt/secrets.env")
        return 1
    return 0


def _cmd_reconcile(args) -> int:
    from toolbelt.reconcile import reconcile

    root = _root(args.path)
    catalog = load_catalog()
    manifest = load_manifest(root)
    plan, report = reconcile(root, catalog, manifest)
    out = Path(args.out) if args.out else root / ".toolbelt" / "plan.json"
    write_plan(plan, out)
    if args.json:
        print(json.dumps({"report": report, "plan": plan_to_json(plan)}, sort_keys=True))
    else:
        print(render_reconcile(report))
        print(f"Plan: {len(plan.actions)} actions")
    return 0


def _cmd_remove(args) -> int:
    from toolbelt.apply import apply_plan
    from toolbelt.models import Action, Plan
    from toolbelt.plan import _reverse_steps

    root = _root(args.path)
    manifest = load_manifest(root)
    record = (manifest.get("tools") or {}).get(args.tool)
    if not record or record.get("state") not in {"installed", "verify_failed"}:
        print(f"tool {args.tool} is not installed", file=sys.stderr)
        return 2
    action = Action(
        id="a1",
        op="remove",
        tool_id=args.tool,
        kind=record.get("kind", ""),
        harnesses=tuple(record.get("harnesses", [])),
        purpose="Remove managed tool",
        provenance=record.get("provenance", ""),
        permissions=(),
        install_scope=record.get("install_scope", ""),
        secrets_required=(),
        evidence=(),
        steps=_reverse_steps(record),
        verify_argv=(),
        rollback="Already removed",
        approved=False,
    )
    print(action_card(action))
    if args.dry_run:
        action = dataclasses.replace(action, approved=True)
    else:
        response = input("[a1] remove {tool} — approve? [y]es/[n]o: ".format(tool=args.tool)).strip().lower()
        action = dataclasses.replace(action, approved=response == "y")
    plan = Plan(1, "", str(root), manifest.get("mode", ""), (action,))
    summary = apply_plan(plan, root, dry_run=args.dry_run)
    print(json.dumps(summary, sort_keys=True))
    return 1 if summary["failed"] else 0


def _cmd_verify(args) -> int:
    root = _root(args.path)
    manifest = load_manifest(root)
    failed = False
    for tool_id, rec in (manifest.get("tools") or {}).items():
        if args.tool and tool_id != args.tool:
            continue
        argv = ((rec.get("verify") or {}).get("argv") or [])
        if not argv:
            rec.setdefault("verify", {})["last_status"] = "never"
            continue
        import subprocess

        try:
            result = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=180)
            ok = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            ok = False
        rec.setdefault("verify", {})["last_status"] = "passed" if ok else "failed"
        rec["state"] = "installed" if ok else "verify_failed"
        failed = failed or not ok
    save_manifest(root, manifest)
    if args.json:
        print(json.dumps(manifest.get("tools", {}), sort_keys=True))
    return 1 if failed else 0


def _cmd_discover(args) -> int:
    root = _root(args.path)
    catalog = load_catalog()
    manifest = load_manifest(root)
    mode = _mode(root, manifest)
    evidence = scan(root)
    brief = find_brief(root)
    if brief:
        evidence.extend(parse_brief(brief, catalog))
    gap_list = discover.gaps(catalog, evidence)
    if args.json:
        print(json.dumps(discover.discovery_json(mode, catalog, evidence, gap_list, brief), sort_keys=True))
    else:
        print(discover.render_discovery(root, mode, catalog, evidence, gap_list, brief))
    return 0


def _cmd_validate(args) -> int:
    root = _root(args.path)
    target = Path(args.target) if args.target else root / "catalog" / "proposed"
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = sorted(target.glob("*.toml"))
    else:
        files = []
    if not files:
        print(f"no proposal files at {target}")
        return 0

    live = load_catalog()
    existing_ids = frozenset(t.id for t in live)
    existing_mcp = frozenset(
        (s.apply_via, t.mcp_name)
        for t in live
        for s in t.apply
        if s.apply_via in {"claude_mcp", "codex_mcp"} and t.mcp_name
    )
    failed = False
    for path in files:
        try:
            tools = load_catalog(path)
        except CatalogError as exc:
            print(f"FAIL {path}: {exc}", file=sys.stderr)
            failed = True
            continue
        issues = safety_lint(tools, existing_ids=existing_ids, existing_mcp=existing_mcp)
        if issues:
            print(f"FAIL {path}:")
            for issue in issues:
                print(f"  - {issue}")
            failed = True
        else:
            print(f"OK {path}")
    return 2 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="toolbelt")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_path(p):
        p.add_argument("--path", default=".")

    scan_p = sub.add_parser("scan")
    add_path(scan_p)
    scan_p.add_argument("--json", action="store_true")
    scan_p.set_defaults(func=_cmd_scan)

    discover_p = sub.add_parser("discover")
    add_path(discover_p)
    discover_p.add_argument("--json", action="store_true")
    discover_p.set_defaults(func=_cmd_discover)

    init_p = sub.add_parser("init")
    add_path(init_p)
    init_p.add_argument("--greenfield", action="store_true", required=True)
    init_p.add_argument("--brief")
    init_p.add_argument("--json", action="store_true")
    init_p.add_argument("--out")
    init_p.set_defaults(func=_cmd_init)

    plan_p = sub.add_parser("plan")
    add_path(plan_p)
    plan_p.add_argument("--json", action="store_true")
    plan_p.add_argument("--prune", action="store_true")
    plan_p.add_argument("--out")
    plan_p.set_defaults(func=_cmd_plan)

    apply_p = sub.add_parser("apply")
    add_path(apply_p)
    apply_p.add_argument("--plan")
    apply_p.add_argument("--yes", action="store_true")
    apply_p.add_argument("--only")
    apply_p.add_argument("--dry-run", action="store_true")
    apply_p.set_defaults(func=_cmd_apply)

    status_p = sub.add_parser("status")
    add_path(status_p)
    status_p.add_argument("--json", action="store_true")
    status_p.set_defaults(func=_cmd_status)

    verify_p = sub.add_parser("verify")
    add_path(verify_p)
    verify_p.add_argument("--tool")
    verify_p.add_argument("--json", action="store_true")
    verify_p.set_defaults(func=_cmd_verify)

    remove_p = sub.add_parser("remove")
    add_path(remove_p)
    remove_p.add_argument("--tool", required=True)
    remove_p.add_argument("--dry-run", action="store_true")
    remove_p.set_defaults(func=_cmd_remove)

    rec_p = sub.add_parser("reconcile")
    add_path(rec_p)
    rec_p.add_argument("--json", action="store_true")
    rec_p.add_argument("--out")
    rec_p.set_defaults(func=_cmd_reconcile)

    guard_p = sub.add_parser("guard")
    add_path(guard_p)
    guard_p.add_argument("--fix", action="store_true")
    guard_p.set_defaults(func=_cmd_guard)

    validate_p = sub.add_parser("validate")
    add_path(validate_p)
    validate_p.add_argument("target", nargs="?")
    validate_p.set_defaults(func=_cmd_validate)

    try:
        args = parser.parse_args(argv)
        return args.func(args)
    except (CatalogError, ManifestError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
