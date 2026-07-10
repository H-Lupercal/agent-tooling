# Codex skill parity via AGENTS.md

## Summary
Toolbelt manages MCP servers across both Claude Code and Codex, but repo skills
are Claude-only: the one `skill` entry, `skill-toolbelt-conventions`, scaffolds
`.claude/skills/toolbelt-conventions/SKILL.md`, which Codex never reads. Codex
takes standing repo instructions from `AGENTS.md`. This spec closes that gap by
adding a non-destructive `managed_block` apply mechanism (mirroring the existing
`.gitignore` managed block) and giving `skill-toolbelt-conventions` a second
apply step that writes an `AGENTS.md` block for Codex. After this change the
conventions "skill" materializes into both harnesses.

## Constraints & Assumptions
- **Why `managed_block` and not `scaffold`:** `scaffold` writes a whole file and
  returns rc 3 (hard failure) when the target already exists with different
  content (`toolbelt/harness.py`, `run_step`, scaffold branch). `AGENTS.md` is a
  user-owned file that frequently already exists, so it must be edited
  non-destructively. `managed_block` inserts/updates only a delimited region and
  preserves all other content — the same approach `guard.ensure_gitignore`
  already uses. Rejected alternative: append-only (cannot update the block later);
  rejected alternative: relaxing `scaffold`'s hash-mismatch behavior (would change
  `SKILL.md` semantics and is riskier).
- `AGENTS.md` lives at the **project root** and is a **committed** instructions
  file (like `.toolbelt/manifest.json`); it is NOT added to `.gitignore` and is
  not a tool `artifact`.
- The managed block is delimited by HTML comments (invisible in rendered
  markdown) scoped by tool id, so multiple tools could each own an independent
  block and re-apply is idempotent:
  - start marker: `<!-- toolbelt:managed:<tool_id> -->`
  - end marker: `<!-- /toolbelt:managed:<tool_id> -->`
- Applying is idempotent and non-destructive: existing block replaced in place;
  if absent, appended after a blank line; content outside the block untouched.
  Removing strips only the block (and its markers), leaving other content intact.
- No new runtime dependencies; Python 3.11+, stdlib only, POSIX-only unchanged.
- Catalog `schema_version` stays `1` (additive step type, backward compatible).
- The seed catalog keeps exactly 9 tools; only `skill-toolbelt-conventions` gains
  a step. Existing tests must keep passing.
- Open questions: none. The `AGENTS.md` filename is the Codex convention; if a
  future Codex convention path changes, only the catalog `block_path` changes.

## Affected Files
- Modify: `toolbelt/models.py` — extend `APPLY_VIA`; add block fields to
  `CatalogStep` and `ApplyStep`.
- Modify: `toolbelt/catalog.py` — allow/validate the `managed_block` step type.
- Modify: `toolbelt/harness.py` — build concrete `managed_block` steps; execute
  `managed_block` / `managed_block_remove` in `run_step`; add two helpers.
- Modify: `toolbelt/plan.py` — reverse a `managed_block` executed step; serialize
  the new `ApplyStep` fields in `_step_to_json` / `_step_from_json`.
- Modify: `toolbelt/apply.py` — record `block_path` / `block_marker` in
  `executed_steps`; use `scaffold_path or block_path` in the dry-run print.
- Modify: `toolbelt/render.py` — use `scaffold_path or block_path` in
  `action_card`.
- Modify: `catalog/catalog.toml` — add the `managed_block` step to
  `skill-toolbelt-conventions`.
- Modify: `catalog/SCHEMA.md` — document `managed_block`.
- Modify: `tests/test_core.py` — add `ManagedBlockTests`.
- Modify (optional, one line): `README.md` — note the conventions skill lands in
  both `.claude/skills/...` and an `AGENTS.md` block.
- Create/delete: none.

## Public Interfaces

New `apply_via` values in the closed vocabulary (`toolbelt/models.py`):
- `managed_block` — catalog-authorable step; inserts/updates a delimited block.
- `managed_block_remove` — internal reverse step only (never authored in the
  catalog; catalog validation rejects it, like `scaffold_remove`).

`CatalogStep` gains two optional fields (defaults `""`):
- `block_path: str` — path (relative to project root) of the file to edit.
- `block_body: str` — the block contents (without markers).

`ApplyStep` gains three optional fields (defaults `""`):
- `block_path: str`, `block_body: str`, `block_marker: str` (the marker is the
  owning tool id, set by `concrete_steps`).

New helpers in `toolbelt/harness.py`:
- `_managed_markers(marker: str) -> tuple[str, str]`
- `_write_managed_block(target: Path, marker: str, body: str) -> None`
- `_remove_managed_block(target: Path, marker: str) -> None`

Catalog step validation (`toolbelt/catalog.py`): a `managed_block` step requires
non-empty `block_path` and `block_body`, else `CatalogError:
"tool <id>: managed_block step needs block_path and block_body"`.

SCHEMA.md documents `managed_block` with `block_path` and `block_body`.

## Implementation Plan
Changes 1-6 are code; do them in this order (6 depends on the earlier plumbing).
Change 7 (catalog), 8 (schema), 9 (tests), 10 (README) follow.

### 1. `toolbelt/models.py`
- Extend the vocabulary:
  ```python
  APPLY_VIA = {"claude_mcp", "codex_mcp", "claude_plugin", "scaffold", "scaffold_remove", "command", "managed_block", "managed_block_remove"}
  ```
- Add to `CatalogStep` (after `scaffold_body`):
  ```python
      block_path: str = ""
      block_body: str = ""
  ```
- Add to `ApplyStep` (after `tolerate_failure` or alongside scaffold fields):
  ```python
      block_path: str = ""
      block_body: str = ""
      block_marker: str = ""
  ```

### 2. `toolbelt/catalog.py`
- Add to `STEP_KEYS`: `"block_path"`, `"block_body"`.
- Change the apply_via allow-check (currently excludes only `scaffold_remove`) to
  also exclude `managed_block_remove`, in both the condition and the message:
  ```python
  allowed_apply = APPLY_VIA - {"scaffold_remove", "managed_block_remove"}
  if apply_via not in allowed_apply:
      raise CatalogError(f"tool {tool_id}: apply_via must be one of {sorted(allowed_apply)}")
  ```
- After the existing `scaffold` field check, add:
  ```python
  if apply_via == "managed_block" and (not step.get("block_path") or not step.get("block_body")):
      raise CatalogError(f"tool {tool_id}: managed_block step needs block_path and block_body")
  ```
- In the `CatalogStep(...)` construction, add:
  ```python
      block_path=str(step.get("block_path", "")),
      block_body=str(step.get("block_body", "")),
  ```

### 3. `toolbelt/harness.py` — concrete steps
In `concrete_steps`, add a branch (after the `scaffold` branch):
```python
        elif step.apply_via == "managed_block":
            steps.append(
                ApplyStep(
                    step.apply_via,
                    step.harness,
                    block_path=step.block_path,
                    block_body=step.block_body,
                    block_marker=tool.id,
                )
            )
```

### 4. `toolbelt/harness.py` — helpers
Add near the other module functions:
```python
def _managed_markers(marker: str) -> tuple[str, str]:
    return (f"<!-- toolbelt:managed:{marker} -->", f"<!-- /toolbelt:managed:{marker} -->")


def _write_managed_block(target: Path, marker: str, body: str) -> None:
    start, end = _managed_markers(marker)
    block = [start, *body.splitlines(), end]
    existing = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    out: list[str] = []
    idx = 0
    replaced = False
    while idx < len(existing):
        if existing[idx].strip() == start:
            while idx < len(existing) and existing[idx].strip() != end:
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
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def _remove_managed_block(target: Path, marker: str) -> None:
    if not target.exists():
        return
    start, end = _managed_markers(marker)
    existing = target.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    idx = 0
    while idx < len(existing):
        if existing[idx].strip() == start:
            while idx < len(existing) and existing[idx].strip() != end:
                idx += 1
            if idx < len(existing):
                idx += 1
        else:
            out.append(existing[idx])
            idx += 1
    text = "\n".join(out).rstrip()
    target.write_text(text + "\n" if text else "", encoding="utf-8")
```

### 5. `toolbelt/harness.py` — `run_step`
- Dry-run print (currently `print(f"{step.apply_via} {step.scaffold_path}")`):
  change to `print(f"{step.apply_via} {step.scaffold_path or step.block_path}")`.
- Both `_append_log(...)` calls: add `"block_path": step.block_path` to the logged
  dict.
- In the non-dry-run body, add a branch for managed blocks. The current structure
  is `if step.apply_via in {"scaffold", "scaffold_remove"}: ... else: <subprocess>`.
  Insert between them:
  ```python
      elif step.apply_via in {"managed_block", "managed_block_remove"}:
          target = Path(cwd) / step.block_path
          if step.apply_via == "managed_block":
              _write_managed_block(target, step.block_marker, step.block_body)
          else:
              _remove_managed_block(target, step.block_marker)
          rc = 0
  ```
  `managed_block` never returns a non-zero rc (it is always non-destructive);
  there is no hash-mismatch hard-fail.

### 6. `toolbelt/plan.py`
- `_reverse_steps`: add a branch so a recorded `managed_block` reverses to
  `managed_block_remove`:
  ```python
        if executed.get("apply_via") == "scaffold":
            ...  # existing scaffold_remove branch
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
            ...  # existing rollback_argv branch
  ```
- `_step_to_json`: add
  ```python
      "block_path": step.block_path,
      "block_body": step.block_body,
      "block_marker": step.block_marker,
  ```
- `_step_from_json`: add
  ```python
      block_path=str(obj.get("block_path", "")),
      block_body=str(obj.get("block_body", "")),
      block_marker=str(obj.get("block_marker", "")),
  ```
  (These keep `plan_from_json(plan_to_json(plan)) == plan` for managed_block
  actions.)

### 7. `toolbelt/apply.py`
- In `_record`, add to each `executed` dict:
  ```python
          "block_path": s.block_path,
          "block_marker": s.block_marker,
  ```
- In `apply_plan`'s dry-run print, change
  `print(f"{step.apply_via} {step.scaffold_path}")` to
  `print(f"{step.apply_via} {step.scaffold_path or step.block_path}")`.

### 8. `toolbelt/render.py`
In `action_card`, the non-argv step line
`lines.append(f"  - {step.apply_via} {step.scaffold_path}")` becomes
`lines.append(f"  - {step.apply_via} {step.scaffold_path or step.block_path}")`.

### 9. `catalog/catalog.toml`
Append a second apply step to the `skill-toolbelt-conventions` entry (keep the
existing `scaffold` step for Claude Code exactly as-is):
```toml
  [[tool.apply]]
  apply_via = "managed_block"
  harness = "codex"
  block_path = "AGENTS.md"
  block_body = """
## Toolbelt-managed toolchain

This repo's AI toolchain is managed by `toolbelt`. The manifest at
`.toolbelt/manifest.json` records every managed MCP server, plugin, skill, LSP,
and dev tool: why it was installed, what secrets it needs, and how to remove it.

- Prefer `toolbelt plan` + `toolbelt apply` over adding MCP servers by hand;
  check the manifest first.
- Never commit `.toolbelt/secrets.env`, `.toolbelt/state/`, or
  `.toolbelt/plan.json` (the managed `.gitignore` block covers them).
- If a managed tool misbehaves, run `toolbelt verify --tool <id>`.
- If the stack changed, run `toolbelt reconcile` to realign the toolchain.
"""
```
After this, `skill-toolbelt-conventions` has `harnesses = ("claude_code", "codex")`
(derived from its steps in `plan._action`).

### 10. `catalog/SCHEMA.md`
In the "Each tool must have at least one `[[tool.apply]]` step" section:
- Add `managed_block` to the `apply_via` list.
- Add under "Step-specific fields":
  `- `managed_block`: `block_path`, `block_body` (inserts an idempotent,
  tool-id-delimited block into a possibly-existing file; non-destructive).`
- Update the validation summary sentence to mention that `managed_block`
  requires `block_path` and `block_body`.

### 11. `README.md` (optional, one sentence)
In the `Secrets`/`State` area or the intro, note that the conventions skill is
written to both `.claude/skills/toolbelt-conventions/SKILL.md` (Claude Code) and
a managed block in `AGENTS.md` (Codex). Keep it to one sentence; do not restate
the whole mechanism.

## Error Handling
- `managed_block` apply: always non-destructive, always rc 0 (short of an OS-level
  write error, which propagates as it would for `scaffold`). No hash-mismatch
  hard-fail path (contrast `scaffold`, which returns rc 3).
- Idempotent re-apply: an unchanged block yields byte-identical output; a changed
  `block_body` replaces the existing block in place (no duplicate blocks).
- `managed_block_remove` on a file without the block (or a missing file): no-op,
  rc 0.
- Catalog validation: a `managed_block` step missing `block_path` or `block_body`
  raises `CatalogError`; `managed_block_remove` in a catalog is rejected by the
  apply_via allow-check.

## Test Plan
Add `ManagedBlockTests` to `tests/test_core.py`. All hermetic (temp dirs only; no
external binaries). The fake bins are not needed here — managed blocks never spawn
a process.

```python
class ManagedBlockTests(unittest.TestCase):
    def test_conventions_tool_targets_both_harnesses(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.harness import concrete_steps

        tool = {t.id: t for t in load_catalog()}["skill-toolbelt-conventions"]
        steps = concrete_steps(tool, tool.install_scope)
        vias = {s.apply_via for s in steps}
        self.assertEqual(vias, {"scaffold", "managed_block"})
        block = next(s for s in steps if s.apply_via == "managed_block")
        self.assertEqual(block.block_path, "AGENTS.md")
        self.assertEqual(block.block_marker, "skill-toolbelt-conventions")

    def test_managed_block_is_idempotent_and_nondestructive(self) -> None:
        from toolbelt.harness import run_step
        from toolbelt.models import ApplyStep

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            agents = root / "AGENTS.md"
            agents.write_text("# House rules\n\nBe nice.\n", encoding="utf-8")
            log = root / "log.jsonl"
            add = ApplyStep(
                "managed_block", "codex",
                block_path="AGENTS.md", block_body="Managed line.", block_marker="skill-toolbelt-conventions",
            )
            self.assertEqual(run_step(add, cwd=root, dry_run=False, log=log, action_id="a1"), 0)
            text1 = agents.read_text(encoding="utf-8")
            self.assertIn("Be nice.", text1)                      # user content preserved
            self.assertIn("<!-- toolbelt:managed:skill-toolbelt-conventions -->", text1)
            self.assertIn("Managed line.", text1)
            # idempotent re-apply
            run_step(add, cwd=root, dry_run=False, log=log, action_id="a1")
            self.assertEqual(agents.read_text(encoding="utf-8"), text1)
            self.assertEqual(text1.count("<!-- toolbelt:managed:skill-toolbelt-conventions -->"), 1)
            # remove strips only the block
            rm = ApplyStep(
                "managed_block_remove", "codex",
                block_path="AGENTS.md", block_marker="skill-toolbelt-conventions",
            )
            self.assertEqual(run_step(rm, cwd=root, dry_run=False, log=log, action_id="a1"), 0)
            text2 = agents.read_text(encoding="utf-8")
            self.assertIn("Be nice.", text2)
            self.assertNotIn("Managed line.", text2)
            self.assertNotIn("toolbelt:managed", text2)

    def test_managed_block_plan_roundtrips(self) -> None:
        from toolbelt.catalog import load_catalog
        from toolbelt.evidence import scan
        from toolbelt.plan import build_plan, plan_from_json, plan_to_json
        from toolbelt.recommend import recommend

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / ".git").mkdir()
            (root / "app.txt").write_text("hi\n", encoding="utf-8")
            catalog = load_catalog()
            recs = recommend(catalog, scan(root), mode="existing", root=root)
            plan = build_plan(recs, catalog, {"tools": {}}, mode="existing", project_root=root)
            self.assertEqual(plan_from_json(plan_to_json(plan)), plan)
            skill = next(a for a in plan.actions if a.tool_id == "skill-toolbelt-conventions")
            self.assertIn("codex", skill.harnesses)
            self.assertTrue(any(s.apply_via == "managed_block" for s in skill.steps))
```

Then run:
```sh
make lint
make test    # existing 6 tests + ManagedBlockTests all pass
```

## Acceptance Criteria
- [ ] `APPLY_VIA` includes `managed_block` and `managed_block_remove`;
      `CatalogStep` has `block_path`/`block_body`; `ApplyStep` has
      `block_path`/`block_body`/`block_marker`.
- [ ] A catalog `managed_block` step with a missing `block_path` or `block_body`
      is rejected with `CatalogError`; `managed_block_remove` is rejected as an
      authored `apply_via`.
- [ ] `skill-toolbelt-conventions` loads with two apply steps and
      `harnesses == ("claude_code", "codex")`; `concrete_steps` yields a
      `managed_block` step with `block_path == "AGENTS.md"` and
      `block_marker == "skill-toolbelt-conventions"`.
- [ ] Applying `managed_block` to a pre-existing `AGENTS.md` preserves all other
      content, adds one delimited block, and is byte-idempotent on re-apply.
- [ ] `managed_block_remove` strips only the block and its markers.
- [ ] `plan_from_json(plan_to_json(plan)) == plan` for a plan containing the
      `managed_block` action (new `ApplyStep` fields round-trip).
- [ ] `remove --tool skill-toolbelt-conventions` reverses both steps (deletes the
      `SKILL.md` and strips the `AGENTS.md` block).
- [ ] `AGENTS.md` is not added to `.gitignore` (it is committed).
- [ ] `catalog/SCHEMA.md` documents `managed_block`.
- [ ] The seed catalog still loads exactly 9 tools; `make lint` and `make test`
      pass (existing 6 tests unchanged in outcome + new `ManagedBlockTests`).
```
