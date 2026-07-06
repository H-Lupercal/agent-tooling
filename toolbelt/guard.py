from __future__ import annotations

import os
import subprocess
from pathlib import Path

from toolbelt.manifest import unmanaged_and_drift
from toolbelt.models import Tool


GITIGNORE_ENTRIES = [".toolbelt/secrets.env", ".toolbelt/state/", ".toolbelt/cache/", ".toolbelt/plan.json"]
GITIGNORE_BEGIN = "# >>> toolbelt managed >>>"
GITIGNORE_END = "# <<< toolbelt managed <<<"


def ensure_gitignore(root: Path, extra: list[str] = []) -> list[str]:
    path = Path(root) / ".gitignore"
    entries = list(dict.fromkeys(GITIGNORE_ENTRIES + sorted(extra)))
    block = [GITIGNORE_BEGIN, *entries, GITIGNORE_END]
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    idx = 0
    replaced = False
    while idx < len(existing):
        if existing[idx] == GITIGNORE_BEGIN:
            while idx < len(existing) and existing[idx] != GITIGNORE_END:
                idx += 1
            if idx < len(existing):
                idx += 1
            out.extend(block)
            replaced = True
        else:
            out.append(existing[idx])
            idx += 1
    if not replaced:
        if out and out[-1] != "":
            out.append("")
        out.extend(block)
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return entries


def secret_status(env_name: str, root: Path) -> str:
    if env_name in os.environ:
        return "present"
    path = Path(root) / ".toolbelt" / "secrets.env"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                if stripped.split("=", 1)[0].strip() == env_name:
                    return "present"
    return "missing"


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def audit(root: Path, manifest: dict, live: dict, catalog: list[Tool]) -> dict:
    catalog_by_id = {tool.id: tool for tool in catalog}
    drift = unmanaged_and_drift(manifest, live)
    secret_gaps: list[dict] = []
    for tool_id, record in (manifest.get("tools") or {}).items():
        if record.get("state") not in {"installed", "verify_failed"}:
            continue
        tool = catalog_by_id.get(tool_id)
        secrets = tool.secrets if tool else tuple(s.get("env", "") for s in record.get("secrets_required", []))
        for env_name in secrets:
            if env_name and secret_status(env_name, root) == "missing":
                secret_gaps.append({"tool_id": tool_id, "env": env_name})

    git_available = _git(root, ["rev-parse", "--is-inside-work-tree"]).returncode == 0
    tracked_secrets: list[str] = []
    ungitignored_artifacts: list[str] = []
    if git_available:
        tracked = _git(root, ["ls-files", ".toolbelt/secrets.env"])
        tracked_secrets = [line for line in tracked.stdout.splitlines() if line]
        for tool_id, record in (manifest.get("tools") or {}).items():
            if record.get("state") != "installed":
                continue
            tool = catalog_by_id.get(tool_id)
            for artifact in (tool.artifacts if tool else record.get("artifacts", [])):
                if _git(root, ["check-ignore", "-q", artifact]).returncode != 0:
                    ungitignored_artifacts.append(artifact)
    return {
        "secret_gaps": secret_gaps,
        "unmanaged": drift["unmanaged"],
        "drifted_missing": drift["drifted_missing"],
        "duplicates": drift["duplicates"],
        "ungitignored_artifacts": sorted(set(ungitignored_artifacts)),
        "tracked_secrets": tracked_secrets,
        "git_available": git_available,
        "warnings": [] if git_available else ["not a git repo; git checks skipped"],
    }
