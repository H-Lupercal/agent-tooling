# Release Finalization (codex-conductor 1.0.0)

## Summary

Bring codex-conductor to a finished, releasable 1.0.0 state. This is the final
spec for the repository. It adds: a `conductor` console command (via an editable
package install), a manual `conductor gc` command to bound ledger growth, an MIT
`LICENSE`, a `CHANGELOG.md`, a version bump to `1.0.0`, and README documentation
for all of it. It deliberately does **not** rename environment variables or
change any hook, decision, ledger, pricing, installer, or policy behavior — the
tool is feature-complete and this spec is packaging and polish only.

## Constraints & Assumptions

- **Editable install only.** The tool is checkout-coupled by design: the
  installer renders the current checkout path into the generated hook wrappers,
  and `default_config_path()` / `install.py` resolve `config/` and `policy/` as
  siblings of the package via `Path(__file__).resolve().parents[1]`. A regular
  (non-editable) `pip install .` copies the package into site-packages where
  those sibling directories do not exist, breaking `install` and the bundled
  config fallback. Therefore the supported install is `pip install -e .` from the
  checkout, which leaves the package in place so all existing path logic keeps
  working unchanged. **Do not** move `config/` or `policy/` into the package or
  change any path-resolution code.
- **Do not modify hook installation.** Installed hook wrappers keep calling the
  checkout via `sys.path.insert(...)` (see `conductor/install.py:_wrapper`). The
  new console script is for human commands only; hooks must not depend on a pip
  install being present or current.
- **Public docs stay path-clean.** `tests/test_public_docs.py` fails if
  `README.md` or `policy/*.md` contains the literal home directory or checkout
  path. All new README text uses `$PWD`, `~/...`, `pip install -e .`, and
  `conductor <cmd>` only. (`LICENSE` and `CHANGELOG.md` are not in that test's
  file list, but keep them path-clean anyway.)
- **Do not touch `policy/orchestration-policy.md`.**
  `tests/test_install.py::test_policy_template_renders_checkout_path` asserts its
  exact command strings.
- **`gc` is manual and conservative.** It never runs automatically, never deletes
  the `state/` root, only removes immediate run-id subdirectories, and defaults
  to keeping the newest 20 runs, so an active/recent run is preserved.
- **Copyright holder** in `LICENSE`/`pyproject.toml` is `H-Lupercal`, year
  `2026`.
- **`conductor/gc.py`** uses only absolute imports; under Python 3 this does not
  shadow the stdlib `gc` module for any other code.

**Open Questions:** none. Scope and license were confirmed (MIT).

**Non-goals (explicitly out of scope):** environment-variable renaming;
non-editable/wheel packaging; a live provider probe (`probe/probe.py` stays the
documented manual placeholder); any change to enforcement, ledger format,
pricing, or installer file layout.

## Affected Files

Create:
- `pyproject.toml` — PEP 621 metadata, `conductor` console script, dynamic version.
- `LICENSE` — MIT.
- `CHANGELOG.md` — 1.0.0 release notes.
- `conductor/cli.py` — unified `conductor <command>` dispatcher.
- `conductor/gc.py` — `gc` command (prune old run-state dirs).
- `tests/test_cli.py` — dispatcher tests.
- `tests/test_gc.py` — pruning tests.

Modify:
- `conductor/__init__.py` — bump `__version__` to `"1.0.0"`.
- `README.md` — replace the "nothing to pip install" line; add a
  "The `conductor` command" section.

Do NOT modify: any hook, provider, installer, policy, or config `.toml` file.

## Public Interfaces

### `pyproject.toml` (exact content)

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "codex-conductor"
dynamic = ["version"]
description = "Cost-aware orchestration guardrail for Codex and Claude Code subagents"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
authors = [{ name = "H-Lupercal" }]
keywords = ["codex", "claude-code", "llm", "orchestration", "cost", "hooks"]
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Operating System :: POSIX",
]
dependencies = []

[project.scripts]
conductor = "conductor.cli:main"

[tool.setuptools.dynamic]
version = { attr = "conductor.__version__" }

[tool.setuptools.packages.find]
include = ["conductor*"]
```

### `conductor/__init__.py`

```python
__version__ = "1.0.0"
```

### `conductor/cli.py`

```python
def main(argv: list[str] | None = None) -> int
```

Dispatches `argv[0]` to a subcommand and forwards the rest:
- `status`   → `conductor.status.main(rest)`
- `report`   → `conductor.report.main(rest)`
- `doctor`   → `conductor.doctor.main(rest)`
- `install`  → `conductor.install.main(rest)`
- `uninstall`→ `conductor.install.main([*rest, "--uninstall"])`
- `gc`       → `conductor.gc.main(rest)`

`-h`/`--help` prints usage to stdout and returns `0`. No args prints usage to
stderr and returns `2`. An unknown command prints an error + usage to stderr and
returns `2`. Subcommand modules are imported lazily inside each branch.

### `conductor/gc.py`

```python
def prune(state_root: Path, keep: int | None, older_than_days: float | None) -> tuple[list[str], list[str]]
def main(argv: list[str] | None = None) -> int
```

`prune` returns `(removed_run_ids, kept_run_ids)`. Selection rule: if
`older_than_days` is not `None`, remove run dirs whose `mtime` is older than that
many days; otherwise keep the newest `keep` dirs (default 20 when `keep is None`)
and remove the rest. It never removes `state_root` itself and ignores non-dir
entries.

`main` flags: `--provider {codex,claude}` (default `codex`), `--keep INT`
(default `20`), `--older-than-days FLOAT` (default `None`), `--dry-run`. It sets
`CODEX_CONDUCTOR_HOME` via `os.environ.setdefault(str(provider_home(...)))`
(same pattern as `status`/`report`), resolves `state_root = conductor_home() /
"state"`, and prints a one-line summary. Returns `0`.

## Implementation Plan

Steps are independent except where noted; do them in any order.

### 1. Version bump
Set `conductor/__init__.py` to exactly `__version__ = "1.0.0"` (keep the trailing
newline).

### 2. `conductor/cli.py`
Create with this exact content:

```python
from __future__ import annotations

import sys

USAGE = (
    "usage: conductor <command> [options]\n"
    "\n"
    "commands:\n"
    "  status     show current run state\n"
    "  report     render the cost report\n"
    "  doctor     verify an install for a provider\n"
    "  install    install conductor hooks and policy\n"
    "  uninstall  remove conductor hooks and policy\n"
    "  gc         prune old ledger state\n"
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] in (["-h"], ["--help"]):
        sys.stdout.write(USAGE)
        return 0
    if not args:
        sys.stderr.write(USAGE)
        return 2
    command, rest = args[0], args[1:]
    if command == "status":
        from conductor.status import main as run
        return run(rest)
    if command == "report":
        from conductor.report import main as run
        return run(rest)
    if command == "doctor":
        from conductor.doctor import main as run
        return run(rest)
    if command == "install":
        from conductor.install import main as run
        return run(rest)
    if command == "uninstall":
        from conductor.install import main as run
        return run([*rest, "--uninstall"])
    if command == "gc":
        from conductor.gc import main as run
        return run(rest)
    sys.stderr.write(f"conductor: unknown command {command!r}\n\n")
    sys.stderr.write(USAGE)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

### 3. `conductor/gc.py`
Create with this exact content:

```python
from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

from conductor.config import conductor_home, provider_home


def prune(state_root: Path, keep: int | None, older_than_days: float | None) -> tuple[list[str], list[str]]:
    if not state_root.exists():
        return ([], [])
    run_dirs = sorted(
        (path for path in state_root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if older_than_days is not None:
        cutoff = time.time() - older_than_days * 86400
        to_remove = [path for path in run_dirs if path.stat().st_mtime < cutoff]
    else:
        limit = keep if keep is not None else 20
        to_remove = run_dirs[limit:]
    remove_names = {path.name for path in to_remove}
    kept = [path.name for path in run_dirs if path.name not in remove_names]
    return ([path.name for path in to_remove], kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor gc")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--keep", type=int, default=20)
    parser.add_argument("--older-than-days", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    state_root = conductor_home() / "state"
    removed, kept = prune(state_root, args.keep, args.older_than_days)
    for name in removed:
        if args.dry_run:
            print(f"would remove {name}")
        else:
            shutil.rmtree(state_root / name, ignore_errors=True)
            print(f"removed {name}")
    print(f"gc: removed {len(removed)}, kept {len(kept)} (state: {state_root})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 4. `LICENSE` (MIT, exact content)

```
MIT License

Copyright (c) 2026 H-Lupercal

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### 5. `CHANGELOG.md` (exact content)

```markdown
# Changelog

All notable changes to codex-conductor are documented here. The format follows
Keep a Changelog, and the project uses Semantic Versioning.

## [1.0.0] - 2026-07-07

Initial stable release.

### Added
- Cost-aware subagent orchestration for Codex and Claude Code via native hooks
  (PreToolUse, SubagentStart, SubagentStop, SessionStart).
- Tiered model ladder with per-tier concurrency caps, task-class routing, a depth
  limit, strictly-cheaper enforcement, and a delegated-spawn budget (rules
  R1-R10).
- Per-run JSONL ledger with cost recording and a savings report.
- Provider-aware `status`, `report`, and `doctor` commands
  (`--provider {codex,claude}`).
- `gc` command to prune old run-state ledgers.
- `conductor` console entry point (editable install: `pip install -e .`).
- Config-integrity validation: tiers must be strictly decreasing in
  relative_cost_weight.
- MIT license.

### Fixed
- The Claude delegation policy now inspects the Claude ledger via
  `--provider claude` instead of defaulting to the Codex home.

### Removed
- The unused `policy.retry_same_tier_max` config knob.
```

### 6. README updates (path-clean)

a. Replace the exact lines:
   > There is nothing to `pip install`. Run everything from a checkout, or install the
   > hook wrappers into your provider home (below).

   with:
   > You can run everything straight from a checkout
   > (`PYTHONPATH="$PWD" python3 -m conductor.<command>`). Optionally, an editable
   > install adds a `conductor` command — see
   > [The `conductor` command](#the-conductor-command).

b. Insert this new section immediately before the `## Daily Use` heading:

   > ## The `conductor` command
   >
   > An editable install from the checkout adds a single `conductor` entry point:
   >
   > ```bash
   > pip install -e .
   > ```
   >
   > Use `-e` (editable): the project keeps operating from its checkout — the
   > installer renders that checkout path into the hooks — so a non-editable
   > install is not supported. The command groups every subcommand:
   >
   > ```bash
   > conductor status --provider codex --pretty
   > conductor report --provider claude --last
   > conductor doctor --provider claude
   > conductor install --provider claude
   > conductor uninstall
   > conductor gc --keep 20            # keep the newest 20 run ledgers, delete the rest
   > conductor gc --older-than-days 30 # delete run ledgers older than 30 days
   > ```
   >
   > `conductor <cmd>` is exactly equivalent to
   > `PYTHONPATH="$PWD" python3 -m conductor.<cmd>`; use whichever you prefer.
   > Run `conductor gc` between sessions, not during an active run.

### 7. Tests

Create `tests/test_cli.py`:

```python
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tests.helpers import DEFAULT_CONFIG, restore_env, set_env, write_config, write_models_cache


class CliTests(unittest.TestCase):
    def test_status_dispatch_returns_json(self):
        from conductor.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(
                CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"),
                CODEX_CONDUCTOR_CONFIG=str(write_config(Path(tmp) / "c.toml", DEFAULT_CONFIG)),
                CODEX_MODELS_CACHE=str(write_models_cache(Path(tmp) / "m.json", [])),
            )
            try:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = main(["status", "--run", "none"])
                self.assertEqual(rc, 0)
                self.assertIn("run_id", buf.getvalue())
            finally:
                restore_env(old)

    def test_gc_dispatch(self):
        from conductor.cli import main
        with tempfile.TemporaryDirectory() as tmp:
            old = set_env(CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main(["gc", "--dry-run"])
                self.assertEqual(rc, 0)
            finally:
                restore_env(old)

    def test_help_returns_zero(self):
        from conductor.cli import main
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["--help"]), 0)

    def test_no_args_and_unknown_command_return_two(self):
        from conductor.cli import main
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main([]), 2)
            self.assertEqual(main(["frobnicate"]), 2)


if __name__ == "__main__":
    unittest.main()
```

Create `tests/test_gc.py`:

```python
import contextlib
import io
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import restore_env, set_env


def _make_runs(root: Path, runs: list[tuple[str, float]]) -> Path:
    state = root / "state"
    state.mkdir(parents=True)
    for name, age_days in runs:
        run_dir = state / name
        run_dir.mkdir()
        (run_dir / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
        stamp = time.time() - age_days * 86400
        os.utime(run_dir, (stamp, stamp))
    return state


class GcTests(unittest.TestCase):
    def test_keep_newest_removes_the_rest(self):
        from conductor.gc import prune
        with tempfile.TemporaryDirectory() as tmp:
            state = _make_runs(Path(tmp), [("old", 10), ("mid", 5), ("new", 1)])
            removed, kept = prune(state, keep=2, older_than_days=None)
            self.assertEqual(removed, ["old"])
            self.assertEqual(set(kept), {"new", "mid"})

    def test_older_than_days(self):
        from conductor.gc import prune
        with tempfile.TemporaryDirectory() as tmp:
            state = _make_runs(Path(tmp), [("old", 10), ("new", 1)])
            removed, kept = prune(state, keep=None, older_than_days=7)
            self.assertEqual(removed, ["old"])
            self.assertEqual(kept, ["new"])

    def test_dry_run_via_main_keeps_dirs(self):
        from conductor.gc import main
        with tempfile.TemporaryDirectory() as tmp:
            _make_runs(Path(tmp) / "home", [("old", 10), ("new", 1)])
            old = set_env(CODEX_CONDUCTOR_HOME=str(Path(tmp) / "home"))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = main(["--keep", "1", "--dry-run"])
                self.assertEqual(rc, 0)
                self.assertTrue((Path(tmp) / "home" / "state" / "old").exists())
            finally:
                restore_env(old)


if __name__ == "__main__":
    unittest.main()
```

## Error Handling

- `cli.main` never raises for bad input: unknown/missing command → usage on
  stderr, exit `2`; otherwise the subcommand's own `main` governs the exit code.
- `gc.prune` on a missing `state/` returns `([], [])` (no error). `shutil.rmtree`
  uses `ignore_errors=True`, so a partially-locked or vanished run dir does not
  abort the sweep.
- `gc` with `--keep 0` removes every run dir (explicit user intent); the newest
  run is only auto-preserved at the default `--keep 20`.
- Packaging: `pip install -e .` succeeds with no third-party build/runtime deps;
  the dynamic version is read from `conductor.__version__`.

## Test Plan

- `tests/test_cli.py`: dispatch routes `status`/`gc` to their modules and returns
  their exit codes; `--help` → 0; no-args and unknown command → 2. Stdout/stderr
  captured to keep output clean. Offline.
- `tests/test_gc.py`: `prune` keeps the newest `keep` and removes the rest; honors
  `--older-than-days`; `--dry-run` via `main` deletes nothing. Uses temp state
  dirs with `os.utime`-set mtimes and `CODEX_CONDUCTOR_HOME`. Offline.
- Regression: the full existing suite must still pass unchanged (nothing in
  `conductor/` behavior, installer, policy, or configs is modified).
- Packaging smoke (manual, part of release verification, not a unit test):
  `pip install -e . && conductor --help && conductor doctor --provider codex`.

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall conductor
pip install -e . && conductor --help
```

## Acceptance Criteria

- [ ] `conductor/__init__.py` has `__version__ = "1.0.0"`.
- [ ] `pip install -e .` from the checkout succeeds and creates a `conductor`
      command; `conductor --help` exits `0` and lists all six subcommands.
- [ ] `conductor status`, `conductor report`, `conductor doctor`,
      `conductor install`, `conductor uninstall`, and `conductor gc` each dispatch
      to the corresponding module and accept that module's flags
      (`conductor doctor --provider claude` works; `conductor uninstall
      --provider claude` runs the uninstall path).
- [ ] `conductor gc` keeps the newest `--keep` (default 20) run dirs, supports
      `--older-than-days` and `--dry-run`, never deletes the `state/` root, and
      reports removed/kept counts.
- [ ] `LICENSE` (MIT) and `CHANGELOG.md` (1.0.0) exist at the repo root.
- [ ] `README.md` documents `pip install -e .`, the `conductor` command, and
      `gc`; it contains no literal home or checkout path
      (`tests/test_public_docs.py` passes).
- [ ] `policy/orchestration-policy.md`, `policy/orchestration-policy.claude.md`,
      the installer, all providers, hooks, and config `.toml` files are unchanged.
- [ ] `python3 -m unittest discover -s tests -v` passes (all existing tests plus
      `test_cli.py` and `test_gc.py`); `python3 -m compileall conductor` succeeds.

## Release steps (manual — not executed by the spec)

After the files above are in place and the suite is green, the human/release
operator (not a file-editing executor) should: commit the working tree on a
branch off `main`, tag `v1.0.0`, and push. Codex should stop after the file
changes and verification above.
```
