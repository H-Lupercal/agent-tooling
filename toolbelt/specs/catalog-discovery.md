# Catalog Discovery (agent-driven)

## Summary
Add an agent-driven discovery loop so Toolbelt can help expand its own catalog
without ever browsing the web itself. `toolbelt discover` deterministically finds
**gaps** — languages and infrastructure signals in the repo that no catalog tool
covers — and prints a ready-to-fill authoring brief per gap. The AI agent
Toolbelt runs inside (Claude Code / Codex) does the actual web research and writes
draft catalog entries to `catalog/proposed/<id>.toml`. `toolbelt validate` checks
those drafts (schema + safety lint) so the agent has a pass/fail loop. A human
then reviews the file, merges it into `catalog/catalog.toml` as `approved = false`,
and flips `approved = true` once vetted. Toolbelt stays stdlib-only, offline, and
deterministic; all web access lives in the agent.

## Constraints & Assumptions
- No network calls in Toolbelt, no new dependencies, Python 3.11+ stdlib only,
  POSIX-only, no build step — unchanged. `make lint` and `make test` must pass.
- Discovery is **advisory and read-only**: `toolbelt discover` writes nothing and
  never mutates the manifest or catalog.
- Two safety gates, both reusing existing machinery:
  1. Drafts stage in `catalog/proposed/` (isolated — `load_catalog` only reads
     `catalog/catalog.toml`, so a broken draft cannot break the live catalog).
  2. A discovered entry must be `approved = false`; `build_plan` already skips
     unapproved tools (`toolbelt/plan.py`, `if not tool.approved: continue`), so it
     is inert until a human flips the flag.
- Gap types are limited to `lang_ext` and `infra` (bounded, high-signal).
  `manifest_dep` is intentionally NOT a gap type (every library dependency would
  become noise); dependencies are shown in an informational inventory instead so
  the agent can still spot service deps like `redis` and propose tools at its
  discretion. `brief_keyword` is excluded because `parse_brief` only emits evidence
  for keywords the catalog already defines, so such evidence is covered by
  construction.
- The infra key `make` is excluded from gaps (a `Makefile` rarely warrants a
  dedicated tool).
- Out of scope for this spec (noted so they are not silently dropped):
  - `toolbelt promote` (auto-merging a validated draft into `catalog.toml`). The
    human merge is the review gate; a copy/paste or `git mv` is fine for v1.
  - Wiring the discover loop into the `skill-toolbelt-conventions` skill body.
    That entry is also edited by `specs/codex-skill-parity.md`; keep the two specs
    decoupled. Add the instruction there in a later, separate change.
- Open questions: none.

## Affected Files
- Create: `toolbelt/discover.py` — gap detection, brief/template rendering, JSON.
- Create: `catalog/proposed/README.md` — staging-area doc (makes the dir tracked).
- Modify: `toolbelt/catalog.py` — add `PROVENANCE_SCHEMES`, `_looks_like_secret`,
  `safety_lint`.
- Modify: `toolbelt/cli.py` — add `_cmd_discover`, `_cmd_validate`, their
  subparsers, and imports.
- Modify: `catalog/SCHEMA.md` — document the proposals staging area + safety lint.
- Modify: `README.md` — add `discover`/`validate` to Commands and a Discovery
  section.
- Modify: `tests/test_core.py` — add `DiscoveryTests`.
- Delete: none.

## Public Interfaces

### New module `toolbelt/discover.py`
```python
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
    root: Path, mode: str, catalog: list[Tool], evidence: list[Evidence],
    gap_list: list[Gap], brief: Path | None,
) -> str:
    lines = [f"Discovery for {root} — mode: {mode}", f"Catalog covers {len(catalog)} tools.", ""]
    if not gap_list:
        lines.append("No gaps: the catalog covers every detected language and infra signal.")
    else:
        lines.append(f"Gaps ({len(gap_list)}): stack signals no catalog tool covers.")
        for i, g in enumerate(gap_list, start=1):
            e = g.signal
            lines += [
                "", f"── GAP {i}: {e.type}:{e.key} ──",
                f"signal: {e.detail} (e.g. {e.source})",
                f"suggested kind: {g.suggested_kind}",
                "Draft → catalog/proposed/<id>.toml, then run `toolbelt validate`. Rules:",
                RULES, "", entry_template(g),
            ]
    lines += ["", "Stack inventory (context, not gaps):"]
    for etype in ("lang_ext", "manifest_dep", "infra", "test_setup"):
        vals = sorted({e.key for e in evidence if e.type == etype})
        if vals:
            lines.append(f"  {etype}: {', '.join(vals)}")
    if brief is not None:
        lines.append(f"Greenfield brief: {brief} — read it for intent-driven tools.")
    return "\n".join(lines)


def discovery_json(
    mode: str, catalog: list[Tool], evidence: list[Evidence],
    gap_list: list[Gap], brief: Path | None,
) -> dict:
    return {
        "mode": mode,
        "catalog_size": len(catalog),
        "gaps": [
            {"type": g.signal.type, "key": g.signal.key, "detail": g.signal.detail,
             "source": g.signal.source, "suggested_kind": g.suggested_kind}
            for g in gap_list
        ],
        "inventory": {
            etype: sorted({e.key for e in evidence if e.type == etype})
            for etype in ("lang_ext", "manifest_dep", "infra", "test_setup")
        },
        "brief": str(brief) if brief is not None else None,
    }
```

### `toolbelt/catalog.py` additions
```python
import re  # add to imports if not present

PROVENANCE_SCHEMES = (
    "npm:", "pypi:", "pip:", "uv:", "uvx:", "go:", "cargo:", "gem:",
    "composer:", "docker:", "claude-plugin:", "toolbelt:", "https://", "http://",
)


def _looks_like_secret(token: str, secret_names: tuple[str, ...]) -> bool:
    if token in secret_names:
        return True
    if re.match(r"^[A-Z][A-Z0-9_]{2,}=", token):
        return True
    if "://" in token:
        authority = token.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority:
            return True
    return False


def safety_lint(
    tools: list[Tool], *,
    existing_ids: frozenset[str] = frozenset(),
    existing_mcp: frozenset[tuple[str, str]] = frozenset(),
) -> list[str]:
    issues: list[str] = []
    for tool in tools:
        if tool.approved:
            issues.append(f"{tool.id}: proposals must set approved = false")
        if not tool.provenance or not tool.provenance.startswith(PROVENANCE_SCHEMES):
            issues.append(f"{tool.id}: provenance must be present and use a known scheme")
        if not tool.homepage:
            issues.append(f"{tool.id}: homepage required for human review")
        if not tool.permissions:
            issues.append(f"{tool.id}: permissions must be declared (use [\"none\"] if truly none)")
        if not tool.catalog_version:
            issues.append(f"{tool.id}: catalog_version required")
        if tool.id in existing_ids:
            issues.append(f"{tool.id}: id already exists in the live catalog")
        for step in tool.apply:
            for token in (*step.mcp_args, *step.command_argv):
                if _looks_like_secret(token, tool.secrets):
                    issues.append(f"{tool.id}: possible secret value in args: {token!r} — put the env var name in `secrets`")
            if step.apply_via in {"claude_mcp", "codex_mcp"} and (step.apply_via, tool.mcp_name) in existing_mcp:
                issues.append(f"{tool.id}: mcp_name {tool.mcp_name!r} already claimed for {step.apply_via}")
    return issues
```
Notes: `str.startswith(tuple)` and `re.match` are stdlib. `safety_lint` operates on
already-schema-validated `Tool` objects (call `load_catalog(path)` first).

### `toolbelt/cli.py` new commands
Add imports near the top:
```python
from toolbelt import discover
from toolbelt.catalog import CatalogError, load_catalog, safety_lint
```
(the `safety_lint` name is added to the existing catalog import line).

Add handlers:
```python
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
        for t in live for s in t.apply
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
```

Add subparsers inside `main` (alongside the others):
```python
    discover_p = sub.add_parser("discover")
    add_path(discover_p)
    discover_p.add_argument("--json", action="store_true")
    discover_p.set_defaults(func=_cmd_discover)

    validate_p = sub.add_parser("validate")
    add_path(validate_p)
    validate_p.add_argument("target", nargs="?")
    validate_p.set_defaults(func=_cmd_validate)
```

### `catalog/proposed/README.md` (new)
```markdown
# Proposed catalog entries (staging)

Agent-drafted catalog entries land here, one `<id>.toml` per tool, produced from
`toolbelt discover` briefs. Files here are NOT loaded by Toolbelt — `load_catalog`
reads only `catalog/catalog.toml`.

Workflow:
1. `toolbelt discover` prints a gap brief + entry template.
2. The agent writes a draft to `catalog/proposed/<id>.toml` (`approved = false`).
3. `toolbelt validate` must pass (schema + safety lint).
4. A human reviews the file and merges it into `catalog/catalog.toml` with
   `approved = false`, then flips `approved = true` once the tool is vetted.
```

## Implementation Plan
1. Create `toolbelt/discover.py` exactly as in Public Interfaces.
2. Add `PROVENANCE_SCHEMES`, `_looks_like_secret`, `safety_lint`, and the `re`
   import to `toolbelt/catalog.py`.
3. Wire `_cmd_discover`, `_cmd_validate`, imports, and subparsers into
   `toolbelt/cli.py`.
4. Create `catalog/proposed/README.md`.
5. Document the staging area and safety lint in `catalog/SCHEMA.md` (new short
   "Proposals & discovery" section: proposals live in `catalog/proposed/`, must be
   `approved = false`, are validated by `toolbelt validate`, and are never loaded
   until merged into `catalog.toml`).
6. Update `README.md` (see below).
7. Add `DiscoveryTests` to `tests/test_core.py` (see Test Plan).

Steps 1-2 are independent; 3 depends on 1-2; 4-7 are independent of each other.

### README.md changes
In the Commands code block, add:
```sh
# Find languages/infra the catalog doesn't cover yet (agent-driven discovery).
python3 -m toolbelt discover --path .

# Validate agent-drafted entries staged in catalog/proposed/.
python3 -m toolbelt validate [PATH]
```
Add a new section after "Catalog":
```markdown
## Discovery

`toolbelt discover` reports **gaps** — languages and infrastructure signals in the
repo that no catalog tool covers — and prints a ready-to-fill entry template for
each. Toolbelt never browses the web itself; the AI agent it runs inside does the
research and writes drafts to `catalog/proposed/<id>.toml`. `toolbelt validate`
checks those drafts (schema + safety lint: `approved` must be false, no secret
values in args, provenance/homepage/permissions present). A human then merges a
validated draft into `catalog/catalog.toml` as `approved = false` and flips it to
`true` once vetted.
```

## Error Handling
- `toolbelt discover`: always exits 0; writes nothing; if there are no gaps it
  prints "No gaps: ...".
- `toolbelt validate`:
  - No proposal files at the target → prints an informational line, exits 0.
  - A file that fails schema validation → `load_catalog` raises `CatalogError`,
    caught per-file, printed as `FAIL <path>: <reason>`, exit 2.
  - A file that passes schema but fails safety lint → prints `FAIL <path>:` with a
    bulleted reason per issue, exit 2.
  - All files pass → prints `OK <path>` per file, exit 0.
- `_looks_like_secret` is a conservative heuristic (env-style `KEY=…`, a token
  equal to a declared secret name, or a URL with `user:pass@` authority). False
  positives are acceptable — they prompt the agent to move a value into `secrets`.
- The outer `main` handler still maps uncaught `CatalogError`/`ManifestError`/
  `ValueError` to exit 2 (unchanged).

## Test Plan
Add `DiscoveryTests` to `tests/test_core.py`. Hermetic (temp dirs + committed
fixtures only; no network, no external binaries). Uses the existing
`copy_fixture_repo`, `ROOT`, `FIXTURES` helpers and `toolbelt.evidence.scan`.

```python
class DiscoveryTests(unittest.TestCase):
    def test_gaps_are_uncovered_actionable_signals(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.discover import gaps
        from toolbelt.evidence import scan

        catalog = load_catalog()
        with tempfile.TemporaryDirectory() as td:
            node = copy_fixture_repo("node_react", td)
            node_keys = {(g.signal.type, g.signal.key) for g in gaps(catalog, scan(node))}
            self.assertIn(("lang_ext", "typescript"), node_keys)   # no TS tool in catalog

            py = copy_fixture_repo("py_fastapi", td)
            py_keys = {(g.signal.type, g.signal.key) for g in gaps(catalog, scan(py))}
            self.assertNotIn(("lang_ext", "python"), py_keys)      # covered by pyright/ruff
            self.assertIn(("infra", "dockerfile"), py_keys)        # not covered

            tf = copy_fixture_repo("terraform_infra", td)
            tf_keys = {(g.signal.type, g.signal.key) for g in gaps(catalog, scan(tf))}
            self.assertNotIn(("infra", "terraform"), tf_keys)      # covered by mcp-terraform

    def test_entry_template_carries_safety_rules(self) -> None:
        from toolbelt.discover import Gap, entry_template
        from toolbelt.models import Evidence

        tmpl = entry_template(Gap(Evidence("lang_ext", "rust", "42 files", 1, "src/main.rs"), "lsp"))
        self.assertIn("approved = false", tmpl)
        self.assertIn('langs = ["rust"]', tmpl)
        self.assertIn("catalog_version", tmpl)

    def test_discover_command_is_read_only(self) -> None:
        from toolbelt.cli import _cmd_discover
        from contextlib import redirect_stdout
        from io import StringIO

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("py_fastapi", td)
            args = type("Args", (), {"path": str(root), "json": False})()
            with redirect_stdout(StringIO()) as buf:
                self.assertEqual(_cmd_discover(args), 0)
            self.assertFalse((root / ".toolbelt").exists())        # wrote no state
            self.assertIn("Discovery for", buf.getvalue())

    def test_safety_lint_flags_unsafe_proposal(self) -> None:
        from toolbelt.catalog import load_catalog, safety_lint

        with tempfile.TemporaryDirectory() as td:
            bad = Path(td) / "bad.toml"
            bad.write_text(
                '[[tool]]\n'
                'id = "mcp-bad"\nkind = "mcp_server"\nname = "Bad"\nsummary = "x"\n'
                'provenance = ""\nhomepage = ""\napproved = true\nfoundational = false\n'
                'permissions = []\ninstall_scope = "project"\nsecrets = []\nartifacts = []\n'
                'mcp_name = "bad"\nverify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  infra = ["redis"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "claude_mcp"\n  harness = "claude_code"\n'
                '  mcp_command = "npx"\n  mcp_args = ["-y", "server", "postgres://u:p@host/db"]\n',
                encoding="utf-8",
            )
            issues = safety_lint(load_catalog(bad))
            joined = " ".join(issues)
            self.assertIn("approved = false", joined)
            self.assertIn("provenance", joined)
            self.assertIn("homepage", joined)
            self.assertIn("permissions", joined)
            self.assertTrue(any("secret" in i for i in issues))    # URL creds flagged

    def test_safety_lint_passes_clean_proposal(self) -> None:
        from toolbelt.catalog import load_catalog, safety_lint

        with tempfile.TemporaryDirectory() as td:
            good = Path(td) / "good.toml"
            good.write_text(
                '[[tool]]\n'
                'id = "lsp-example-new"\nkind = "lsp"\nname = "Example LSP"\nsummary = "x"\n'
                'provenance = "npm:example-lsp"\nhomepage = "https://example.com"\n'
                'approved = false\nfoundational = false\npermissions = ["process-spawn"]\n'
                'install_scope = "user"\nsecrets = []\nartifacts = []\nmcp_name = ""\n'
                'verify_argv = []\ncatalog_version = "1"\n'
                '  [[tool.match]]\n  langs = ["rust"]\n  weight = 2\n'
                '  [[tool.apply]]\n  apply_via = "command"\n  harness = ""\n'
                '  command_argv = ["npm", "install", "-g", "example-lsp"]\n',
                encoding="utf-8",
            )
            live_ids = frozenset(t.id for t in load_catalog())
            self.assertEqual(safety_lint(load_catalog(good), existing_ids=live_ids), [])
```

Then run:
```sh
make lint
make test    # existing tests + DiscoveryTests all pass
```

## Acceptance Criteria
- [ ] `toolbelt discover --path <repo>` exits 0, writes nothing (no `.toolbelt/`
      created), and prints a gap brief. For `py_fastapi` it lists `infra:dockerfile`
      as a gap and does NOT list `lang_ext:python`; for `node_react` it lists
      `lang_ext:typescript`.
- [ ] `discover --json` emits `{mode, catalog_size, gaps[], inventory{}, brief}`
      with `gaps` limited to `lang_ext`/`infra` and `inventory.manifest_dep`
      populated when deps exist.
- [ ] Each gap brief contains a TOML template with `approved = false`, the closed
      vocabularies inline, and a `match` block for the gap's key.
- [ ] `toolbelt validate` with no staged files exits 0 with an informational line.
- [ ] `toolbelt validate <bad.toml>` exits 2 and reports `approved`, missing
      `provenance`/`homepage`/`permissions`, and a suspected secret in args.
- [ ] `toolbelt validate <clean.toml>` (approved=false, unique id, provenance +
      homepage + permissions present, no secrets in args) prints `OK` and exits 0.
- [ ] `safety_lint` flags an id that collides with a live-catalog id and an
      `mcp_name` already claimed for the same harness.
- [ ] `catalog/proposed/README.md` exists; `load_catalog()` still returns exactly
      the 9 seed tools (proposals are not loaded).
- [ ] `catalog/SCHEMA.md` and `README.md` document `discover`/`validate` and the
      proposals staging area.
- [ ] `make lint` and `make test` pass (existing tests unchanged + `DiscoveryTests`).
```
