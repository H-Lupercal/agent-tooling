# Toolbelt hardening

## Summary
Six correctness/quality upgrades to Toolbelt found during review, plus the test
coverage to lock them in. None change the public CLI surface or the catalog
schema. Grouped:

1. Make `make e2e` real — add a hermetic end-to-end smoke script and its catalog
   fixture (the target currently references a script that does not exist).
2. Rewrite the unreadable `_cmd_remove` plan construction.
3. Store repo-relative evidence `source` paths so the committed manifest is
   portable across machines.
4. Give `verify` a subprocess timeout + missing-binary handling, and delete three
   dead-code spots.
5. Add always-on (CI) tests for the real, non-dry-run apply/reconcile/remove path
   and for drift detection.
6. Make manifest detection recursive so monorepo sub-package manifests are found.

## Constraints & Assumptions
- Runtime stays Python 3.11+, standard library only, POSIX-only. No new
  third-party dependencies. `make lint` (`py_compile`) and `make test` must pass
  after every change.
- The seed catalog `catalog/catalog.toml` and the `catalog.toml` schema are NOT
  changed. New behavior is tested with a dedicated, minimal **test** catalog
  fixture so tests never invoke real `npx`/`uvx`/`npm`/`uv`/`pyright`/`ruff`.
- `tests/fake_bin/claude` and `tests/fake_bin/codex` already exist: each appends
  its argv to `$FAKE_BIN_LOG` (which must be set) and exits `$FAKE_EXIT_CODE`
  (default 0). Reuse them; do not modify them.
- The e2e smoke and the new unittests are **hermetic**: they run only against
  temp directories, the fake bins, and the test catalog. They must not mutate the
  developer's real `~/.claude*`, `~/.codex`, global npm, or the toolbelt repo.
- Decisions made for the two items that had open questions (recorded here so a
  blind executor does not re-litigate them):
  - **`make e2e`**: ADD a hermetic smoke script (do not delete the target, do not
    attempt real `claude`/`codex` mutation — the probe report at
    `docs/probe-report.md` explicitly deferred real mutating probes). Keep the
    existing `RUN_LIVE=1` gate and Makefile as-is.
  - **Manifest detection depth**: DEEPEN to a full-tree walk honoring `SKIP_DIRS`
    (consistent with `detect_lang_ext`), rather than documenting the current
    depth-2 limit.
- Out of scope (deliberately not done here; noted so they are not silently
  dropped): guarding the `fcntl` import for Windows, and switching `make lint`
  from `py_compile` to Ruff. Both are lower value and the second adds a dev
  dependency that conflicts with the repo's stdlib-only stance; raise separately
  if wanted.

## Affected Files
- Create: `tests/fixtures/e2e_catalog.toml` — minimal hermetic test catalog.
- Create: `tests/e2e_smoke.sh` — black-box CLI smoke driven via `python3 -m toolbelt`.
- Modify: `toolbelt/cli.py` — rewrite `_cmd_remove` plan construction (Change 2);
  add timeout/missing-binary handling to `_cmd_verify` (Change 4a).
- Modify: `toolbelt/evidence.py` — repo-relative `source` paths (Change 3);
  recursive `_manifest_paths` (Change 6).
- Modify: `toolbelt/recommend.py` — repo-relative `source` in `_first_glob`
  (Change 3).
- Modify: `toolbelt/plan.py` — remove dead ternary (Change 4b).
- Modify: `toolbelt/apply.py` — remove dead `root = Path(...); del root` (Change 4c).
- `README.md` — no change required. The `make e2e` note has already been trimmed
  to drop the "not yet part of the repository" caveat, so once
  `tests/e2e_smoke.sh` exists the README is already accurate (Change 1).
- Modify: `tests/test_core.py` — add the new test classes (Changes 5 and 6).
- Delete: none.

## Public Interfaces
No CLI command, flag, exit code, catalog field, or manifest field changes. The
only signature touched is internal:

- `toolbelt/evidence.py`: rename helper `_rel_source(root: Path, path: Path) -> str`
  to `_rel(root: Path, path: Path) -> str` returning `str(path.relative_to(root))`.

New test fixture catalog `tests/fixtures/e2e_catalog.toml` defines exactly three
tools, all matching `any_files = ["*"]` at `weight = 2`, all with empty
`verify_argv`, all `approved = true`, `foundational = false`:

- `e2e-mcp` — `kind = "mcp_server"`, `mcp_name = "e2e"`, two apply steps
  (`claude_mcp` and `codex_mcp`) with `mcp_command = "echo"`, `mcp_args = ["hi"]`,
  `install_scope = "project"`, `permissions = ["none"]`.
- `e2e-plugin` — `kind = "plugin"`, one `claude_plugin` step with
  `plugin_ref = "e2e-plugin@marketplace"`, `install_scope = "user"`,
  `permissions = ["none"]`.
- `e2e-skill` — `kind = "skill"`, one `scaffold` step with
  `scaffold_path = ".claude/skills/e2e/SKILL.md"`,
  `scaffold_body = "e2e skill fixture\n"`, `install_scope = "repo-committed"`,
  `permissions = ["none"]`.

## Implementation Plan

Steps 2, 3, 4, 6 are independent and may be done in parallel. Step 1 depends on
the fixture from Step 5's fixture (shared `e2e_catalog.toml`); create the fixture
first. Step 5 depends on Changes 3 and 6 only for the assertions it adds.

### Change 0 — create `tests/fixtures/e2e_catalog.toml`
Write this file verbatim:

```toml
# Hermetic test catalog for e2e smoke and real-apply unit tests.
schema_version = 1

[[tool]]
id = "e2e-mcp"
kind = "mcp_server"
name = "E2E MCP"
summary = "Hermetic MCP fixture for the e2e smoke."
provenance = "test:e2e-mcp"
homepage = ""
approved = true
foundational = false
permissions = ["none"]
install_scope = "project"
secrets = []
artifacts = []
mcp_name = "e2e"
verify_argv = []
catalog_version = "1"
  [[tool.match]]
  any_files = ["*"]
  weight = 2
  [[tool.apply]]
  apply_via = "claude_mcp"
  harness = "claude_code"
  mcp_command = "echo"
  mcp_args = ["hi"]
  [[tool.apply]]
  apply_via = "codex_mcp"
  harness = "codex"
  mcp_command = "echo"
  mcp_args = ["hi"]

[[tool]]
id = "e2e-plugin"
kind = "plugin"
name = "E2E plugin"
summary = "Hermetic plugin fixture."
provenance = "test:e2e-plugin"
homepage = ""
approved = true
foundational = false
permissions = ["none"]
install_scope = "user"
secrets = []
artifacts = []
mcp_name = ""
verify_argv = []
catalog_version = "1"
  [[tool.match]]
  any_files = ["*"]
  weight = 2
  [[tool.apply]]
  apply_via = "claude_plugin"
  harness = "claude_code"
  plugin_ref = "e2e-plugin@marketplace"

[[tool]]
id = "e2e-skill"
kind = "skill"
name = "E2E skill"
summary = "Hermetic scaffold fixture."
provenance = "toolbelt:scaffold"
homepage = ""
approved = true
foundational = false
permissions = ["none"]
install_scope = "repo-committed"
secrets = []
artifacts = []
mcp_name = ""
verify_argv = []
catalog_version = "1"
  [[tool.match]]
  any_files = ["*"]
  weight = 2
  [[tool.apply]]
  apply_via = "scaffold"
  harness = "claude_code"
  scaffold_path = ".claude/skills/e2e/SKILL.md"
  scaffold_body = "e2e skill fixture\n"
```

This must pass `toolbelt.catalog.load_catalog(Path("tests/fixtures/e2e_catalog.toml"))`
without raising `CatalogError`.

### Change 1 — add `tests/e2e_smoke.sh`
Create the script below and mark it executable (`chmod +x tests/e2e_smoke.sh`).
It is invoked by `make e2e` when `RUN_LIVE=1`; the Makefile is NOT changed.

```bash
#!/usr/bin/env bash
# Hermetic black-box smoke: drives the real `python3 -m toolbelt` CLI against a
# throwaway repo using the fake claude/codex bins and the e2e test catalog.
# Mutates only $tmp; never touches real harness state.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/.git"
printf 'hello\n' > "$tmp/app.txt"

export PYTHONPATH="$repo"
export TOOLBELT_CATALOG="$repo/tests/fixtures/e2e_catalog.toml"
export TOOLBELT_CLAUDE_BIN="$repo/tests/fake_bin/claude"
export TOOLBELT_CODEX_BIN="$repo/tests/fake_bin/codex"
export FAKE_BIN_LOG="$tmp/fake.log"
export TOOLBELT_CLAUDE_STATE="$tmp/claude_state.json"
export TOOLBELT_CODEX_CONFIG="$tmp/codex_config.toml"
export TOOLBELT_CLAUDE_PLUGINS="$tmp/installed_plugins.json"
: > "$FAKE_BIN_LOG"

fail() { printf 'e2e FAIL: %s\n' "$1" >&2; exit 1; }

python3 -m toolbelt scan --path "$tmp"      >/dev/null || fail "scan exited nonzero"
python3 -m toolbelt plan --path "$tmp"      >/dev/null || fail "plan exited nonzero"
[ -f "$tmp/.toolbelt/plan.json" ]           || fail "plan.json not written"

python3 -m toolbelt apply --path "$tmp" --yes >/dev/null || fail "apply exited nonzero"
grep -q "mcp add" "$FAKE_BIN_LOG"           || fail "no 'mcp add' in fake log"
grep -q "plugin install" "$FAKE_BIN_LOG"    || fail "no 'plugin install' in fake log"
[ -f "$tmp/.claude/skills/e2e/SKILL.md" ]   || fail "scaffold file not created"
grep -q "toolbelt managed" "$tmp/.gitignore" || fail "managed .gitignore block missing"
python3 - "$tmp" <<'PY' || fail "e2e-mcp not recorded installed"
import json, sys
m = json.load(open(f"{sys.argv[1]}/.toolbelt/manifest.json"))
assert m["tools"]["e2e-mcp"]["state"] == "installed", m["tools"]["e2e-mcp"]["state"]
PY

python3 -m toolbelt status --path "$tmp" --json >/dev/null || fail "status exited nonzero"
python3 -m toolbelt verify --path "$tmp" --json >/dev/null || fail "verify exited nonzero"
python3 -m toolbelt reconcile --path "$tmp"     >/dev/null || fail "reconcile exited nonzero"
python3 -m toolbelt guard --path "$tmp"         >/dev/null || fail "guard exited nonzero"

out="$(python3 -m toolbelt remove --path "$tmp" --tool e2e-skill --dry-run)" || fail "remove exited nonzero"
printf '%s\n' "$out" | grep -q "remove e2e-skill" || fail "remove card missing tool id"

printf 'e2e PASS\n'
```

The README's `make e2e` note has already been trimmed of any "script not yet
present" caveat, so no README edit is needed once the script exists — the
Development section is accurate as soon as `tests/e2e_smoke.sh` lands.

### Change 2 — rewrite `_cmd_remove` plan construction (`toolbelt/cli.py`)
In `_cmd_remove` (currently lines ~182-218):

- Change the import line `from toolbelt.models import Action` to
  `from toolbelt.models import Action, Plan`.
- Replace the final `summary = apply_plan(...)` line, which currently reads:

  ```python
  summary = apply_plan(dataclasses.replace(__import__("toolbelt.models").models.Plan(1, "", str(root), manifest.get("mode", ""), (action,))), root, dry_run=args.dry_run)
  ```

  with:

  ```python
  plan = Plan(1, "", str(root), manifest.get("mode", ""), (action,))
  summary = apply_plan(plan, root, dry_run=args.dry_run)
  ```

No behavior change: the removed `dataclasses.replace(...)` had no field
overrides (a no-op copy), and `apply_plan`'s `catalog` argument is unused on the
`remove` op path (it calls `remove_tool_record`, not `_record`).

### Change 3 — repo-relative evidence `source` (`toolbelt/evidence.py`, `toolbelt/recommend.py`)
The `source` field is persisted into `.toolbelt/manifest.json` (`last_scan`)
which is committed; absolute paths there are non-portable. `source` is not used
for display and not part of `evidence_sha256` (which hashes `type|key|detail`),
so this change affects only the stored path string.

In `toolbelt/evidence.py`:

- Replace the helper:
  ```python
  def _rel_source(root: Path, path: Path) -> str:
      return str(path.resolve())
  ```
  with:
  ```python
  def _rel(root: Path, path: Path) -> str:
      return str(path.relative_to(root))
  ```
- Update every `source` argument that is a filesystem path under `root` to use
  `_rel(root, <path>)`:
  - `detect_manifest_files`: `_rel_source(root, path)` → `_rel(root, path)`.
  - `detect_manifest_deps`: every `str(path.resolve())` → `_rel(root, path)`
    (all five/six occurrences).
  - `detect_lang_ext`: `str(first[lang].resolve())` → `_rel(root, first[lang])`.
  - `detect_infra`: `str(path.resolve())` → `_rel(root, path)`.
  - `detect_test_setup`: `str(path.resolve())` → `_rel(root, path)`;
    `str((root / "pytest.ini").resolve())` → `_rel(root, root / "pytest.ini")`;
    `str(pyproject.resolve())` → `_rel(root, pyproject)`.
  - `detect_existing_tools`: `str(project.resolve())` → `_rel(root, project)`.
    Leave the non-path sources `"codex config"` and `"claude plugins"` unchanged.

In `toolbelt/recommend.py`, `_first_glob`:
- Change `Evidence("file_glob", pattern, str(path.relative_to(root)), weight, str(path.resolve()))`
  so the final `source` argument is `str(path.relative_to(root))` instead of
  `str(path.resolve())`.

Leave `brief.parse_brief` (`source="brief"`) unchanged.

### Change 4 — verify timeout + dead code
4a. `toolbelt/cli.py` `_cmd_verify`: the current body runs
`subprocess.run(argv, cwd=root, capture_output=True, text=True)` with no timeout
and no `FileNotFoundError` handling (a missing verify binary crashes the
command). Replace the block that computes status:

```python
        import subprocess

        result = subprocess.run(argv, cwd=root, capture_output=True, text=True)
        rec.setdefault("verify", {})["last_status"] = "passed" if result.returncode == 0 else "failed"
        rec["state"] = "installed" if result.returncode == 0 else "verify_failed"
        failed = failed or result.returncode != 0
```

with:

```python
        import subprocess

        try:
            result = subprocess.run(argv, cwd=root, capture_output=True, text=True, timeout=180)
            ok = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            ok = False
        rec.setdefault("verify", {})["last_status"] = "passed" if ok else "failed"
        rec["state"] = "installed" if ok else "verify_failed"
        failed = failed or not ok
```

4b. `toolbelt/plan.py` (~line 120): replace
```python
            steps = concrete_steps(tool, tool.install_scope if tool.kind in {"mcp_server", "connector"} else tool.install_scope)
```
with
```python
            steps = concrete_steps(tool, tool.install_scope)
```
(both ternary branches were identical).

4c. `toolbelt/apply.py` in `_record` (~lines 107-108): delete the two dead lines
```python
    root = Path(action.install_scope)
    del root
```
Leave the surrounding code and the `Path` import (used elsewhere in the module)
intact.

### Change 6 — recursive manifest detection (`toolbelt/evidence.py`)
Replace `_manifest_paths`:
```python
def _manifest_paths(root: Path) -> list[Path]:
    paths: list[Path] = []
    for child in root.iterdir() if root.exists() else []:
        if child.name in SKIP_DIRS:
            continue
        candidates = [child] if child.is_file() else list(child.iterdir()) if child.is_dir() else []
        for path in candidates:
            if path.name in MANIFEST_FILES or fnmatch.fnmatch(path.name, "*.csproj"):
                paths.append(path)
    return sorted(set(paths))
```
with a full-tree walk that reuses `_walk` (which already skips `SKIP_DIRS`,
including `node_modules`):
```python
def _manifest_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    paths: list[Path] = []
    for path in _walk(root):
        if path.is_file() and (path.name in MANIFEST_FILES or fnmatch.fnmatch(path.name, "*.csproj")):
            paths.append(path)
    return sorted(set(paths))
```
`_walk` yields every descendant except those under `SKIP_DIRS`, so deeper
monorepo manifests (e.g. `packages/api/package.json`) are now detected while
`node_modules` manifests remain excluded.

### Change 5 — new tests (`tests/test_core.py`)
Add two test classes. They must run under the existing `make test`
(`unittest discover`) with no external binaries invoked.

Add near the top of the file if not present:
```python
from toolbelt.catalog import load_catalog
from toolbelt.evidence import scan
```
(or import locally inside each test, matching the file's existing style of
local imports).

Class A — real, non-dry-run apply/reconcile/remove using the e2e catalog:
```python
class RealApplyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.old_env = os.environ.copy()
        fake = ROOT / "tests" / "fake_bin"
        self.tmp = tempfile.mkdtemp()
        os.environ.update(
            {
                "TOOLBELT_CATALOG": str(FIXTURES / "e2e_catalog.toml"),
                "TOOLBELT_CLAUDE_BIN": str(fake / "claude"),
                "TOOLBELT_CODEX_BIN": str(fake / "codex"),
                "FAKE_BIN_LOG": str(Path(self.tmp) / "fake.log"),
                "TOOLBELT_CLAUDE_STATE": str(Path(self.tmp) / "claude_state.json"),
                "TOOLBELT_CODEX_CONFIG": str(Path(self.tmp) / "codex_config.toml"),
                "TOOLBELT_CLAUDE_PLUGINS": str(Path(self.tmp) / "installed_plugins.json"),
            }
        )

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.old_env)
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_real_apply_then_reconcile_and_remove(self) -> None:
        from toolbelt.apply import apply_plan, approve_interactively
        from toolbelt.plan import build_plan, _reverse_steps
        from toolbelt.recommend import recommend
        from toolbelt.manifest import load_manifest
        from toolbelt.reconcile import reconcile
        from toolbelt.models import Action, Plan

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            (root / "app.txt").write_text("hello\n", encoding="utf-8")
            catalog = load_catalog()

            recs = recommend(catalog, scan(root), mode="existing", root=root)
            plan = build_plan(recs, catalog, {"tools": {}}, mode="existing", project_root=root)
            plan = approve_interactively(plan, assume_yes=True, only=None)
            summary = apply_plan(plan, root, dry_run=False, catalog=catalog)

            self.assertEqual(summary["failed"], [])
            manifest = load_manifest(root)
            self.assertEqual(manifest["tools"]["e2e-mcp"]["state"], "installed")
            self.assertTrue((root / ".claude" / "skills" / "e2e" / "SKILL.md").exists())
            gitignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("toolbelt managed", gitignore)
            log = Path(os.environ["FAKE_BIN_LOG"]).read_text(encoding="utf-8")
            self.assertIn("mcp add", log)
            self.assertIn("plugin install", log)

            # reconcile: manifest says installed, live state is empty -> drifted.
            _plan, report = reconcile(root, catalog, manifest)
            self.assertEqual(report["classification"]["e2e-mcp"], "drifted_missing")

            # remove: reverse steps of a recorded tool succeed.
            record = manifest["tools"]["e2e-skill"]
            action = Action(
                id="a1", op="remove", tool_id="e2e-skill", kind=record["kind"],
                harnesses=tuple(record.get("harnesses", [])), purpose="Remove",
                provenance=record.get("provenance", ""), permissions=(),
                install_scope=record.get("install_scope", ""), secrets_required=(),
                evidence=(), steps=_reverse_steps(record), verify_argv=(),
                rollback="", approved=True,
            )
            rm = apply_plan(Plan(1, "", str(root), "existing", (action,)), root, dry_run=False)
            self.assertEqual(rm["failed"], [])
            self.assertEqual(load_manifest(root)["tools"]["e2e-skill"]["state"], "removed")
            self.assertFalse((root / ".claude" / "skills" / "e2e" / "SKILL.md").exists())
```

Class B — recursive manifest detection (Change 6):
```python
class ManifestDepthTests(unittest.TestCase):
    def test_nested_manifest_found_and_node_modules_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "packages" / "api").mkdir(parents=True)
            (root / "packages" / "api" / "package.json").write_text(
                '{"dependencies": {"pg": "^8"}}', encoding="utf-8"
            )
            (root / "node_modules" / "foo").mkdir(parents=True)
            (root / "node_modules" / "foo" / "package.json").write_text(
                '{"dependencies": {"leftpad": "1"}}', encoding="utf-8"
            )
            keys = {(e.type, e.key) for e in scan(root)}
            self.assertIn(("manifest_file", "package.json"), keys)
            self.assertIn(("manifest_dep", "package.json:pg"), keys)
            self.assertNotIn(("manifest_dep", "package.json:leftpad"), keys)
```

## Error Handling
- `_cmd_verify`: a missing verify binary or a verify command exceeding 180s is
  treated as `failed` / `verify_failed` (no exception propagates); `_cmd_verify`
  still returns exit code 1 when any tool failed, matching prior semantics for
  the non-crash cases.
- e2e smoke: any failed assertion calls `fail()` which prints `e2e FAIL: <reason>`
  to stderr and exits 1; success prints `e2e PASS` and exits 0.
- No other failure modes change. Catalog validation still rejects the same
  malformed inputs; the new `e2e_catalog.toml` is valid by construction.

## Test Plan
All tests are hermetic — no live services, no real `claude`/`codex`/`npx`/`uvx`.
Boundaries are mocked via `tests/fake_bin` and `tests/fixtures/e2e_catalog.toml`.

Run:
```sh
make lint    # must pass (py_compile of toolbelt/*.py)
make test    # must pass; now includes RealApplyTests and ManifestDepthTests
RUN_LIVE=1 make e2e   # must print "e2e PASS"
```

## Acceptance Criteria
- [ ] `tests/fixtures/e2e_catalog.toml` exists and `load_catalog` accepts it.
- [ ] `tests/e2e_smoke.sh` exists, is executable, and `RUN_LIVE=1 make e2e`
      prints `e2e PASS` and exits 0.
- [ ] `README.md`'s `make e2e` note is accurate with the script present (no
      "not yet part of the repository" caveat — already trimmed).
- [ ] `_cmd_remove` no longer contains `__import__("toolbelt.models")` or a
      no-op `dataclasses.replace` around the `Plan`; `remove --tool <id> --dry-run`
      still prints the action card and exits 0, and a real `remove` sets the
      tool's manifest state to `removed`.
- [ ] After `scan`, every `source` in `.toolbelt/manifest.json` `last_scan.evidence`
      that refers to a file is a repo-relative path (no leading `/`); the six
      existing tests still pass.
- [ ] `verify` with a nonexistent verify binary reports `verify_failed` and does
      not raise; `subprocess.run` in `_cmd_verify` passes `timeout=180`.
- [ ] `toolbelt/plan.py` no longer contains the identical-branch ternary; and
      `toolbelt/apply.py` no longer contains `root = Path(action.install_scope)` /
      `del root`.
- [ ] `RealApplyTests.test_real_apply_then_reconcile_and_remove` passes.
- [ ] `ManifestDepthTests.test_nested_manifest_found_and_node_modules_skipped`
      passes (nested `packages/api/package.json` detected; `node_modules`
      manifest excluded).
- [ ] `make lint` and `make test` pass.
