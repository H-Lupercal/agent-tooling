from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from toolbelt.models import Evidence, Tool


ACTIONABLE_TYPES = ("lang_ext", "infra")
NON_ACTIONABLE_INFRA = {"make"}

RULES = (
    "  - approved MUST be false (discovered entries are candidates)\n"
    "  - permissions: least privilege from {network, filesystem-read, filesystem-write, "
    "process-spawn, browser-control, shell-exec, credentials-read, none}\n"
    "  - NEVER put secret values in mcp_args/command_argv; list env var NAMES in `secrets`\n"
    "  - provenance MUST name the exact package (npm:... / pypi:... / uvx:... / cargo:... / claude-plugin:...)"
)


@dataclass(frozen=True)
class Gap:
    signal: Evidence
    suggested_kind: str


def _covered(catalog: list[Tool]) -> set[str]:
    keys: set[str] = set()
    for tool in catalog:
        for group in tool.match:
            for lang in group.langs:
                keys.add(f"lang_ext:{lang.lower()}")
            for inf in group.infra:
                keys.add(f"infra:{inf.lower()}")
    return keys


def gaps(catalog: list[Tool], evidence: list[Evidence]) -> list[Gap]:
    covered = _covered(catalog)
    out: list[Gap] = []
    for e in evidence:
        if e.type not in ACTIONABLE_TYPES:
            continue
        if e.type == "infra" and e.key in NON_ACTIONABLE_INFRA:
            continue
        if f"{e.type}:{e.key.lower()}" in covered:
            continue
        out.append(Gap(e, "lsp" if e.type == "lang_ext" else "mcp_server"))
    return sorted(out, key=lambda g: (g.signal.type, g.signal.key))


def entry_template(gap: Gap) -> str:
    e = gap.signal
    if e.type == "lang_ext":
        kind, mcp_name = "lsp", '""'
        match = f'  [[tool.match]]\n  langs = ["{e.key}"]\n  weight = 2'
        apply = (
            '  [[tool.apply]]\n'
            '  apply_via = "command"        # claude_mcp, codex_mcp, claude_plugin, scaffold, command\n'
            '  harness = ""\n'
            '  command_argv = ["REPLACE"]\n'
            '  rollback_argv = ["REPLACE"]'
        )
    else:
        kind, mcp_name = "mcp_server", '"REPLACE"'
        match = f'  [[tool.match]]\n  infra = ["{e.key}"]\n  weight = 3'
        apply = (
            '  [[tool.apply]]\n'
            '  apply_via = "claude_mcp"     # claude_mcp, codex_mcp, claude_plugin, scaffold, command\n'
            '  harness = "claude_code"\n'
            '  mcp_command = "REPLACE"\n'
            '  mcp_args = ["REPLACE"]'
        )
    return (
        "[[tool]]\n"
        'id = "REPLACE-kebab-id"\n'
        f'kind = "{kind}"                # mcp_server, connector, plugin, skill, lsp, dev_tool\n'
        'name = "REPLACE"\n'
        'summary = "REPLACE one line"\n'
        'provenance = "REPLACE"         # npm:... / pypi:... / uvx:... / cargo:... / claude-plugin:...\n'
        'homepage = "REPLACE"\n'
        "approved = false\n"
        "foundational = false\n"
        'permissions = ["none"]         # least privilege from the closed vocabulary\n'
        'install_scope = "user"         # project, user, repo-committed\n'
        "secrets = []                   # env var NAMES only, never values\n"
        "artifacts = []\n"
        f"mcp_name = {mcp_name}          # required for mcp_server/connector\n"
        "verify_argv = []\n"
        'catalog_version = "1"\n'
        f"{match}\n"
        f"{apply}\n"
    )


def render_discovery(
    root: Path,
    mode: str,
    catalog: list[Tool],
    evidence: list[Evidence],
    gap_list: list[Gap],
    brief: Path | None,
) -> str:
    lines = [f"Discovery for {root} - mode: {mode}", f"Catalog covers {len(catalog)} tools.", ""]
    if not gap_list:
        lines.append("No gaps: the catalog covers every detected language and infra signal.")
    else:
        lines.append(f"Gaps ({len(gap_list)}): stack signals no catalog tool covers.")
        for i, g in enumerate(gap_list, start=1):
            e = g.signal
            lines += [
                "",
                f"-- GAP {i}: {e.type}:{e.key} --",
                f"signal: {e.detail} (e.g. {e.source})",
                f"suggested kind: {g.suggested_kind}",
                "Draft -> catalog/proposed/<id>.toml, then run `toolbelt validate`. Rules:",
                RULES,
                "",
                entry_template(g),
            ]
    lines += ["", "Stack inventory (context, not gaps):"]
    for etype in ("lang_ext", "manifest_dep", "infra", "test_setup"):
        vals = sorted({e.key for e in evidence if e.type == etype})
        if vals:
            lines.append(f"  {etype}: {', '.join(vals)}")
    if brief is not None:
        lines.append(f"Greenfield brief: {brief} - read it for intent-driven tools.")
    return "\n".join(lines)


def discovery_json(
    mode: str,
    catalog: list[Tool],
    evidence: list[Evidence],
    gap_list: list[Gap],
    brief: Path | None,
) -> dict:
    return {
        "mode": mode,
        "catalog_size": len(catalog),
        "gaps": [
            {
                "type": g.signal.type,
                "key": g.signal.key,
                "detail": g.signal.detail,
                "source": g.signal.source,
                "suggested_kind": g.suggested_kind,
            }
            for g in gap_list
        ],
        "inventory": {
            etype: sorted({e.key for e in evidence if e.type == etype})
            for etype in ("lang_ext", "manifest_dep", "infra", "test_setup")
        },
        "brief": str(brief) if brief is not None else None,
    }
