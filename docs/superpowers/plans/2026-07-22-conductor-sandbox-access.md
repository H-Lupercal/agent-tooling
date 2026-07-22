# Conductor Sandbox Access and Claude Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make provider-aware Conductor diagnostics reliable for Codex and repair the existing Claude Code integration without changing SQLite storage or schema.

**Architecture:** Keep each provider's installed Conductor home and live WAL database unchanged. Encode the Codex-only escalation rule in both applicable executor contracts, add normal Claude-provider guidance to the planner contract, and use Conductor's transactional installer for Claude-managed files.

**Tech Stack:** Markdown operating contracts, Conductor Python CLI, SQLite WAL diagnostics.

---

### Task 1: Add durable provider-aware operating guidance

**Files:**
- Modify: `/home/neil/AGENTS.md`
- Modify: `/home/neil/VSproj/agent-tooling/AGENTS.md`
- Modify: `/home/neil/CLAUDE.md`

- [ ] **Step 1: Add the Codex executor rule to both AGENTS contracts**

Insert this text inside `/home/neil/AGENTS.md`'s `codex-conductor policy` managed
section, immediately before the final-report requirement. In the repository-local
`AGENTS.md`, add it under a `## Conductor state access` heading immediately before that
file's final-report requirement:

```markdown
Conductor's SQLite store uses WAL and needs write access to its provider state directory,
including for `status`, `doctor`, and `report`. Use `--provider codex` or
`--provider claude` explicitly when provider selection matters. In a Codex sandbox, first
run the requested command normally. If it fails with
`cannot initialize conductor store: unable to open database file` for a store below
`~/.codex/conductor/state`, rerun only that same Conductor command with narrowly scoped
sandbox escalation. Do not use SQLite immutable/no-lock modes, copy a live store, relocate
provider state, or broaden access to the rest of `~/.codex` as a workaround. If escalation
is denied, report the access denial and exact command rather than calling the database
corrupt.
```

- [ ] **Step 2: Add Claude provider guidance to the planner contract**

Append this section to `/home/neil/CLAUDE.md`:

```markdown
## Conductor provider access

For Conductor diagnostics in Claude Code, pass `--provider claude` explicitly and use the
normal Claude state at `~/.claude/conductor/state`. Do not use Codex-specific sandbox
escalation syntax, SQLite immutable/no-lock modes, copied live stores, or relocated state.
A missing store before the first Claude provider session is a controlled warning, not
database corruption.
```

- [ ] **Step 3: Validate the contract edits**

Run:

```bash
rg -n "Conductor's SQLite store|Conductor provider access|immutable/no-lock" /home/neil/AGENTS.md /home/neil/VSproj/agent-tooling/AGENTS.md /home/neil/CLAUDE.md
git -C /home/neil/VSproj/agent-tooling diff --check
```

Expected: both AGENTS files contain the executor rule, CLAUDE.md contains the provider section, and `git diff --check` exits 0.

### Task 2: Repair the Claude Code installation transactionally

**Managed state:**
- Modify through installer: `/home/neil/.claude/settings.json`
- Modify through installer: `/home/neil/.claude/CLAUDE.md`
- Create or repair through installer: `/home/neil/.claude/conductor/`

- [ ] **Step 1: Preview the repair**

Run:

```bash
conductor install --provider claude --repair --dry-run
```

Expected: a bounded plan for Claude hooks, policy block, and managed manifest with no changes applied.

- [ ] **Step 2: Apply the repair through the supported installer**

Run:

```bash
conductor install --provider claude --repair
```

Expected: exit 0 and a repaired Claude installation. Do not hand-edit installer-managed files.

- [ ] **Step 3: Verify the Claude installation**

Run:

```bash
conductor doctor --provider claude
```

Expected: hook, policy, wrapper, and manifest checks are `OK`; `overall: OK`. Pricing and a missing pre-session store may remain warnings.

### Task 3: Verify Codex behavior and repository contracts

**Files:**
- Verify: `/home/neil/.codex/conductor/state/conductor.db`
- Verify: `/home/neil/VSproj/agent-tooling/tests/test_release_contract.py`

- [ ] **Step 1: Verify Codex diagnostics with narrow state access**

Run with narrowly scoped sandbox escalation if the normal invocation hits the documented access error:

```bash
conductor doctor --provider codex
conductor status --last --pretty --provider codex
```

Expected: doctor reports `schema=3 journal=wal integrity=ok` and `overall: OK`; status exits 0.

- [ ] **Step 2: Run the repository contract test**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: all release-contract tests pass.

- [ ] **Step 3: Commit repository-owned documentation**

Run:

```bash
git add AGENTS.md docs/superpowers/specs/2026-07-22-conductor-sandbox-access-design.md docs/superpowers/plans/2026-07-22-conductor-sandbox-access.md
git commit -m "docs: document conductor state access"
```

Expected: one commit containing only repository-owned contract and workflow documentation. Home and live-installation files remain uncommitted external state.

- [ ] **Step 4: Produce the required final report**

Run with narrow escalation if required:

```bash
PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last
```

Expected: exit 0 and a report table for the latest Codex run.
