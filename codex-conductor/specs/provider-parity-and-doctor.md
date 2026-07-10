# Provider Parity + `conductor doctor`

## Summary

Make every conductor CLI behave identically across the two supported providers
(Codex and Claude Code), and add a `conductor doctor` command that verifies an
install end-to-end for a chosen provider.

Two provider-parity gaps exist today:

1. **`status` and `report` are not provider-aware.** Unlike `install`, they take
   no `--provider` flag; they read whatever `CODEX_CONDUCTOR_HOME` points at,
   defaulting to `~/.codex/conductor` (`conductor/config.py:107`). A Claude user
   must know to export `CODEX_CONDUCTOR_HOME=~/.claude/conductor` or they silently
   inspect the Codex ledger.

2. **The shipped Claude policy inherits that bug.** `policy/orchestration-policy.claude.md`
   instructs the Claude primary agent to run `conductor.status` / `conductor.report`
   with no `--provider` and no env override. Because Claude's installed hooks
   write to `~/.claude/conductor/state` (the Claude hook wrappers set
   `CODEX_CONDUCTOR_HOME` to the `.claude` path), but a manually-run
   `conductor.status` reads `~/.codex/conductor`, the primary reports on the
   wrong (or empty) ledger.

This spec adds a shared `--provider codex|claude` flag to `status` and `report`,
fixes the Claude policy, adds `conductor doctor`, and documents all of it.

## Constraints & Assumptions

- **Do NOT modify `policy/orchestration-policy.md` (the Codex policy).**
  `tests/test_install.py::test_policy_template_renders_checkout_path` asserts the
  rendered Codex policy contains the exact strings
  `python3 -m conductor.status --pretty` and `python3 -m conductor.report --last`,
  and that the checkout path appears exactly twice. Codex is the default provider,
  so its policy does not need `--provider`. Only the Claude policy changes.
- **Public docs must stay path-clean.** `tests/test_public_docs.py` fails if
  `README.md` or any `policy/*.md` contains the literal home directory or the
  literal checkout path. Every command example must use `~/...` and `$PWD` (or
  `/path/to/codex-conductor`), never an absolute real path.
- **`--provider` uses `setdefault` semantics.** An explicitly-exported
  `CODEX_CONDUCTOR_HOME` always wins over `--provider`, matching the installed
  hook wrappers, which use `os.environ.setdefault('CODEX_CONDUCTOR_HOME', ...)`
  (`conductor/install.py:314`). This keeps every existing test (which sets that
  env var explicitly) unaffected.
- **`doctor` must not import `tomllib`-dependent modules until after its Python
  version preflight.** `conductor/__init__.py` only sets `__version__`, so the
  package imports cleanly on Python 3.10; `conductor/doctor.py` must keep its
  module-level imports to the standard library and import `conductor.config` /
  `conductor.install` lazily inside `run_checks`.
- **`doctor` reads paths directly from its `home`/`policy_path` arguments** (no
  env mutation), so it is hermetically testable against temp directories the way
  `tests/test_install.py` already installs into temp homes.
- **Scope:** no change to spawn decisions, budgeting, pricing math, the ledger
  format, the installer's file layout, or the Codex policy. `report`'s existing
  unused `--sessions-root` argument is left as-is (out of scope).

**Open Questions:** none blocking.

## Affected Files

Create:
- `conductor/doctor.py` — the `doctor` command.
- `tests/test_doctor.py` — tests for `run_checks` across both providers.

Modify:
- `conductor/config.py` — add `provider_home(provider: str) -> Path`.
- `conductor/status.py` — add `--provider` flag + `setdefault` of the home.
- `conductor/report.py` — add `--provider` flag + `setdefault` of the home.
- `policy/orchestration-policy.claude.md` — add `--provider claude` to its two
  commands.
- `README.md` — clarify default provider in "Daily Use", add Claude command
  variants, and add a "Health check" section.
- `tests/test_status_report.py` — add tests for `provider_home` and the
  `--provider` precedence.

Do NOT modify: `policy/orchestration-policy.md`, the installer, the ledger.

## Public Interfaces

### `conductor/config.py`

```python
def provider_home(provider: str) -> Path:
    """Canonical conductor home for a provider: ~/.codex/conductor or
    ~/.claude/conductor. Unknown providers fall back to the Codex home."""
    root = ".claude" if provider == "claude" else ".codex"
    return Path.home() / root / "conductor"
```

### `conductor/status.py` and `conductor/report.py`

Both `main` functions gain:

```python
parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
```

and, immediately after `args = parser.parse_args(argv)` and before any
`build_status` / `build_report` call:

```python
os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
```

Add `import os` to each module's top-level imports, and add `provider_home` to
each module's existing `from conductor.config import ...` line.

### `conductor/doctor.py`

Module-level imports are standard library only:

```python
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
```

Public functions:

```python
def run_checks(provider: str, *, home: Path | None = None, policy_path: Path | None = None) -> dict:
    """Run all health checks for `provider`. `home` is the provider root
    (~/.codex or ~/.claude); `policy_path` is ~/AGENTS.md or ~/.claude/CLAUDE.md.
    Both default to the provider's canonical location when None."""

def render_human(report: dict) -> str: ...

def main(argv: list[str] | None = None) -> int: ...
```

`run_checks` returns:

```json
{
  "provider": "codex",
  "checks": [
    {"name": "python", "status": "ok", "detail": "Python 3.13.1"},
    {"name": "config", "status": "ok", "detail": "4 tiers, 3 enabled (installed: /home/u/.codex/conductor/conductor.toml)"}
  ],
  "notes": ["Codex records hook trust by hash - run /hooks in the Codex CLI to trust the installed hooks."],
  "ok": true
}
```

- Each check `status` is one of `"ok"`, `"warn"`, `"fail"`.
- `report["ok"]` is `True` iff **no** check has status `"fail"`. `warn` never
  fails the run.

`main` behavior:
- Preflight before importing `conductor.config`:
  ```python
  if sys.version_info < (3, 11):
      print("[FAIL] python: requires Python 3.11+ (tomllib / datetime.UTC)")
      return 1
  ```
- Flags: `--provider {codex,claude}` (default `codex`), `--json`.
- Prints `render_human(report)` (default) or `json.dumps(report, indent=2,
  sort_keys=True)` (`--json`).
- Returns `0` if `report["ok"]` else `1`.

## Implementation Plan

### 1. `provider_home` (config.py)
Add the function above. No other change to `config.py`.

### 2. `--provider` on status and report
In each of `conductor/status.py` and `conductor/report.py`: add `import os`, add
`provider_home` to the config import, add the `--provider` argument, and add the
`os.environ.setdefault(...)` line right after arg parsing. Do not change
`build_status` / `build_report`.

### 3. `conductor/doctor.py`
Implement `run_checks`, `render_human`, `main` as specified. Inside `run_checks`:

- Lazily import: `from conductor.config import ConfigError, enabled_tiers, load_ladder`
  and `from conductor.install import CONFIG_START, CONFIG_END, POLICY_START, POLICY_END`.
- Resolve defaults:
  - `home = home or (Path.home() / (".claude" if provider == "claude" else ".codex"))`
  - `policy_path = policy_path or (home / "CLAUDE.md" if provider == "claude" else Path.home() / "AGENTS.md")`
  - `conductor_home = home / "conductor"`, `hooks_dir = conductor_home / "hooks"`
  - `installed_config = conductor_home / "conductor.toml"`
  - `bundled = PROJECT_ROOT / "config" / ("conductor.claude.toml" if provider == "claude" else "conductor.toml")`
  - `config_path = installed_config if installed_config.exists() else bundled`
  - `models_cache = home / "models_cache.json"`
- Build the checks list in this order, appending a
  `{"name", "status", "detail"}` dict for each. Use a small local helper to
  append.

Checks shared by both providers:

1. `python` — `status="ok"`, `detail=f"Python {sys.version.split()[0]}"`.
   (Reached only on 3.11+.)
2. `platform` — `fail` with detail `"fcntl.flock unavailable on Windows"` if
   `sys.platform == "win32"`, else `ok` with detail `"posix"`.
3. `config` — try `ladder = load_ladder(config_path)`. On `ConfigError` as `exc`:
   `fail`, detail `str(exc)`. On success: `ok`, detail
   `f"{len(ladder.tiers)} tiers, {len(enabled_tiers(ladder, models_cache))} enabled ({'installed' if config_path == installed_config else 'bundled default'}: {config_path})"`.
   If `config` failed, skip the `pricing` check (no ladder); otherwise:
4. `pricing` — from `conductor.pricing import pricing_verified`; `ok` if
   `pricing_verified(ladder)` else `warn` with detail
   `f"PRICING UNVERIFIED - edit {config_path}"`.

Codex-only checks (when `provider == "codex"`):

5. `hooks_json` — `path = home / "hooks.json"`.
   - missing → `fail`, `"not installed - run: bash install.sh"`.
   - exists and `'"_managed_by": "codex-conductor"'` in its text → `ok`,
     `"managed hooks.json present"`.
   - exists without that marker → `fail`,
     `"foreign hooks.json present - conductor hooks not active"`.
6. `hook_wrappers` — required = `["pre_tool_use.py", "lifecycle.py", "session_start.py"]`.
   All exist under `hooks_dir` → `ok`; else `fail` listing the missing names.
7. `agents_block` — `config_toml = home / "config.toml"`; `ok` if it exists and
   contains both `CONFIG_START` and `CONFIG_END`, else `warn`,
   `"managed [agents] block absent"`.
8. `policy_block` — `ok` if `policy_path` exists and contains both `POLICY_START`
   and `POLICY_END`, else `warn`, `f"delegation policy not installed in {policy_path}"`.
9. `models_cache` — `ok` if `models_cache` exists (`"present"`), else `warn`,
   `"absent - auto tiers (mini, spark) disabled"`.
   - `notes = ["Codex records hook trust by hash - run /hooks in the Codex CLI to trust the installed hooks."]`

Claude-only checks (when `provider == "claude"`):

5. `settings_hooks` — `settings = home / "settings.json"`.
   - missing → `fail`, `"not installed - run: bash install.sh --provider claude"`.
   - not valid JSON (catch `json.JSONDecodeError`) → `fail`,
     `"settings.json is not valid JSON"`.
   - valid: read `hooks = settings.get("hooks") or {}`. For each event in
     `["SessionStart", "PreToolUse", "SubagentStart", "SubagentStop"]`, it is
     "present" if any entry in `hooks.get(event, [])` has a hook whose
     `command` string contains `str(hooks_dir)`. All four present → `ok`,
     `"conductor hooks present"`; some present → `warn`,
     `f"conductor hooks missing for: {', '.join(missing)}"`; none present →
     `fail`, `"conductor hooks not found in settings.json"`.
6. `hook_wrappers` — same as codex check 6.
7. `policy_block` — same as codex check 8, against the Claude `policy_path`.
   - `notes = ["Review ~/.claude/settings.json if your setup requires managed-settings approval."]`

Finally: `ok = not any(c["status"] == "fail" for c in checks)`; return
`{"provider": provider, "checks": checks, "notes": notes, "ok": ok}`.

`render_human(report)`:
- First line: `f"provider: {report['provider']}"`.
- One line per check: `f"[{status.upper():<4}] {name:<14} {detail}"` (e.g.
  `[OK]   config         4 tiers, 3 enabled ...`).
- If `notes`, a `notes:` header followed by `- ` bullets.
- Last line: `f"overall: {'OK' if report['ok'] else 'FAIL'}"`.

### 4. Claude policy fix
In `policy/orchestration-policy.claude.md`, change the status command to
`PYTHONPATH={{PROJECT_ROOT}} python3 -m conductor.status --provider claude --pretty`
and the report command to
`PYTHONPATH={{PROJECT_ROOT}} python3 -m conductor.report --provider claude --last`.
Leave the `{{PROJECT_ROOT}}` placeholder intact (the installer renders it).

### 5. README updates
All examples use `$PWD` / `~/...` only — no literal home or checkout path.

a. In **"## Daily Use"**, replace the intro paragraph
   `Run these from the repository checkout (or use the installed provider config,\nwhich \`conductor\` picks up automatically once present).`
   with:
   > Run these from the repository checkout. By default they read the **Codex**
   > home (`~/.codex/conductor`); pass `--provider claude` (below) or set
   > `CODEX_CONDUCTOR_HOME=~/.claude/conductor` to target a Claude Code install.

b. Immediately before the line
   `The installed policy tells the primary agent to append the report at the end of`,
   insert:
   > To inspect a Claude Code install, add `--provider claude` to either command:
   >
   > ```bash
   > PYTHONPATH="$PWD" python3 -m conductor.status --provider claude --pretty
   > PYTHONPATH="$PWD" python3 -m conductor.report --provider claude --last
   > ```

c. Insert a new section between "## Daily Use" and "## Cost Report":
   > ## Health check
   >
   > Verify an install end-to-end for either provider:
   >
   > ```bash
   > PYTHONPATH="$PWD" python3 -m conductor.doctor --provider codex
   > PYTHONPATH="$PWD" python3 -m conductor.doctor --provider claude
   > ```
   >
   > `doctor` checks Python/platform support, config validity and pricing, hook
   > installation, the delegation-policy block, and (for Codex) the model cache.
   > It prints one line per check and exits non-zero if any check fails. Add
   > `--json` for machine-readable output.

### 6. Tests
Add to `tests/test_status_report.py`:

```python
def test_provider_home_maps_each_provider(self):
    from conductor.config import provider_home
    self.assertTrue(str(provider_home("claude")).endswith("/.claude/conductor"))
    self.assertTrue(str(provider_home("codex")).endswith("/.codex/conductor"))

def test_provider_flag_does_not_override_explicit_home(self):
    import contextlib, io, os
    from conductor.status import main
    with tempfile.TemporaryDirectory() as tmp:
        home = str(Path(tmp) / "home")
        old = set_env(
            CODEX_CONDUCTOR_HOME=home,
            CODEX_CONDUCTOR_CONFIG=str(write_config(Path(tmp) / "c.toml", DEFAULT_CONFIG)),
            CODEX_MODELS_CACHE=str(write_models_cache(Path(tmp) / "m.json", [])),
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["--provider", "claude", "--run", "none"])
            self.assertEqual(rc, 0)
            self.assertEqual(os.environ["CODEX_CONDUCTOR_HOME"], home)
        finally:
            restore_env(old)
```

Create `tests/test_doctor.py`:

```python
import tempfile
import unittest
from pathlib import Path


class DoctorTests(unittest.TestCase):
    def test_codex_all_pass_after_install(self):
        from conductor.doctor import run_checks
        from conductor.install import install
        with tempfile.TemporaryDirectory() as tmp:
            codex_home = Path(tmp) / ".codex"
            agents = Path(tmp) / "AGENTS.md"
            install(codex_home=codex_home, agents_path=agents)
            report = run_checks("codex", home=codex_home, policy_path=agents)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertTrue(report["ok"])
            self.assertEqual(statuses["hooks_json"], "ok")
            self.assertEqual(statuses["hook_wrappers"], "ok")
            self.assertEqual(statuses["models_cache"], "warn")  # no cache in temp

    def test_codex_missing_install_fails(self):
        from conductor.doctor import run_checks
        with tempfile.TemporaryDirectory() as tmp:
            report = run_checks("codex", home=Path(tmp) / ".codex", policy_path=Path(tmp) / "AGENTS.md")
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertFalse(report["ok"])
            self.assertEqual(statuses["hooks_json"], "fail")

    def test_claude_all_pass_after_install(self):
        from conductor.doctor import run_checks
        from conductor.install import install
        with tempfile.TemporaryDirectory() as tmp:
            claude_home = Path(tmp) / ".claude"
            claude_home.mkdir()
            claude_md = claude_home / "CLAUDE.md"
            install(provider="claude", claude_home=claude_home, claude_md_path=claude_md)
            report = run_checks("claude", home=claude_home, policy_path=claude_md)
            statuses = {c["name"]: c["status"] for c in report["checks"]}
            self.assertTrue(report["ok"])
            self.assertEqual(statuses["settings_hooks"], "ok")


if __name__ == "__main__":
    unittest.main()
```

## Error Handling

- `doctor` never raises for a broken/missing install: every filesystem or parse
  problem becomes a `fail`/`warn` check, and `main` returns `1` only when a
  `fail` is present.
- `load_ladder` raising `ConfigError` inside `run_checks` is caught and rendered
  as the `config` check `fail`; a malformed installed config does not crash
  `doctor`.
- Invalid `settings.json` (Claude) is caught (`json.JSONDecodeError`) and
  rendered as a `settings_hooks` `fail`.
- Python `< 3.11` is reported by `main` before any `tomllib`-dependent import and
  returns `1`.
- `status`/`report` `--provider` only sets the home when `CODEX_CONDUCTOR_HOME`
  is unset; an explicit value is preserved (no accidental redirection).

## Test Plan

- **`tests/test_doctor.py`** (new, offline): installs into temp homes via the
  existing `install(...)` entry points and asserts `doctor` reports all-pass
  (`ok is True`) for both providers, and reports `hooks_json == "fail"` /
  `ok is False` for a bare directory. No live services.
- **`tests/test_status_report.py`** (extended): `provider_home` maps each
  provider to the right home; `--provider` does not override an explicitly set
  `CODEX_CONDUCTOR_HOME` (proves existing env-driven tests remain correct and no
  cross-provider leakage occurs). Stdout is captured to keep test output clean.
- **Regression:** `tests/test_install.py` (exact Codex policy strings),
  `tests/test_install_claude.py`, and `tests/test_public_docs.py` must all still
  pass unchanged — the Codex policy is untouched and README/policy edits use only
  `~/...` and `$PWD`.

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall conductor
```

## Acceptance Criteria

- [ ] `conductor/config.py` exports `provider_home(provider)` returning
      `~/.codex/conductor` for `codex`/unknown and `~/.claude/conductor` for
      `claude`.
- [ ] `python3 -m conductor.status --provider claude` and
      `python3 -m conductor.report --provider claude` read the Claude home when
      `CODEX_CONDUCTOR_HOME` is unset, and leave an explicitly-set
      `CODEX_CONDUCTOR_HOME` untouched.
- [ ] `python3 -m conductor.doctor --provider codex` and `--provider claude`
      exist, print one line per check, support `--json`, and exit `0` when all
      checks pass / `1` when any check fails.
- [ ] `doctor` on a freshly-installed temp home reports `ok: true` for both
      providers; on a bare directory it reports `ok: false` with a `fail` check.
- [ ] `doctor` prints a clean message and exits `1` on Python `< 3.11` without a
      traceback.
- [ ] `policy/orchestration-policy.claude.md` runs `conductor.status` and
      `conductor.report` with `--provider claude`; `policy/orchestration-policy.md`
      is unchanged.
- [ ] `README.md` documents the `--provider` flag and the `doctor` command and
      contains no literal home or checkout path.
- [ ] `python3 -m unittest discover -s tests -v` passes (all existing tests plus
      the new `test_doctor.py` and the two new `test_status_report.py` tests);
      `python3 -m compileall conductor` succeeds.
```
