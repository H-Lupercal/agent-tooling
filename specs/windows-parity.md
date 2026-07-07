# Cross-platform parity (Windows == Linux == macOS)

## Summary
Today Toolbelt is POSIX-only: it will not even import on Windows because
`toolbelt/manifest.py` does an unconditional `import fcntl`, and `cli.py` imports
`manifest` at startup. This spec makes the Toolbelt CLI and its unit-test suite
run and behave identically on Linux, macOS, and Windows. It fixes six real
portability issues: (1) the `fcntl` hard-import, (2) executable resolution so the
real `claude`/`codex` CLIs (installed as `.cmd`/`.exe` on Windows) are found,
(3) a latent `fnmatch` bug that makes GitHub-Actions detection silently fail on
Windows, (4) OS-specific path separators leaking into committed state, (5) CRLF
newline translation making committed files differ by OS, and (6) the test harness
hardcoding the POSIX `:` PATH separator and bash-only fake CLIs. It also adds a
3-OS CI matrix so parity is proven continuously.

## Constraints & Assumptions
- In scope and made fully cross-platform: the `python -m toolbelt` CLI (all
  commands) and the unit-test suite (`python -m unittest discover -s tests`).
- Out of scope (documented, not ported): the `Makefile` and the POSIX shell
  helpers `tests/e2e_smoke.sh` and `scripts/probe_cli_output.sh`. `make` and bash
  are not native to Windows. On Windows those run under Git Bash or WSL; the
  equivalent native commands (`python -m unittest discover -s tests`,
  `python -m compileall toolbelt`) are documented in the README. The unit suite
  (via `RealApplyTests`) already covers the same real-apply pipeline the e2e
  script exercises, so no coverage is lost on Windows.
- No new third-party dependencies; Python 3.11+ stdlib only; no build step.
- The manifest write stays crash-safe on every OS via the existing temp-file +
  `os.replace` (atomic on Windows too). The lock only provides mutual exclusion
  between concurrent writers.
- True proof of Windows behavior requires a Windows runner. The added
  `PortabilityTests` exercise the Windows code paths *on any OS* by simulating the
  absence of `fcntl`; the CI matrix runs the full suite on real Windows/macOS.
- `Path.write_text(..., newline=...)` requires Python 3.10+ (Toolbelt requires
  3.11+), so it is available.
- Open questions: none.

## Affected Files
- Modify: `toolbelt/manifest.py` — guarded `fcntl` import + portable
  `_manifest_lock` context manager; LF newline on write.
- Modify: `toolbelt/harness.py` — resolve `argv[0]` via `shutil.which`; LF
  newline on scaffold/managed-block/log writes.
- Modify: `toolbelt/evidence.py` — POSIX separators (`as_posix`) in stored
  relative paths and in the `detect_infra` `fnmatch` target.
- Modify: `toolbelt/recommend.py` — POSIX separators in `_first_glob`.
- Modify: `toolbelt/plan.py` — LF newline in `write_plan`.
- Modify: `toolbelt/guard.py` — LF newline in `ensure_gitignore`.
- Modify: `tests/helpers.py` — `os.pathsep` PATH join; platform-selected fake CLI.
- Create: `tests/fake_bin/claude.cmd`, `tests/fake_bin/codex.cmd` — Windows fakes.
- Modify: `tests/test_core.py` — add `PortabilityTests`.
- Modify: `README.md` — replace the "POSIX-only … will not import on Windows"
  paragraph with cross-platform text + Windows dev commands.
- Create: `.github/workflows/ci.yml` — lint + test on ubuntu/macos/windows.

## Public Interfaces
No CLI command, flag, exit code, catalog field, or manifest field changes.
Internal additions only:

- `toolbelt/manifest.py`:
  - Module attribute `fcntl` is now `None` when the module is unavailable
    (guarded import), so tests can monkeypatch it.
  - New `@contextmanager def _manifest_lock(tb: Path)` — acquires an advisory lock
    for the `.toolbelt/` dir: `fcntl.flock` when available, else an
    `O_CREAT|O_EXCL` lockfile with stale-lock stealing. Raises `ManifestError`
    on a 5-second timeout, same as today.
- `toolbelt/harness.py`: `run_step` resolves `argv[0]` with `shutil.which` before
  spawning, falling back to the raw name.

Stored-data contract (now identical on every OS):
- Every relative path in `.toolbelt/manifest.json` (`last_scan.evidence[].source`,
  `.detail`) and in plan evidence uses forward slashes.
- Every Toolbelt-written text file (`manifest.json`, `plan.json`, `.gitignore`
  managed block, scaffold `SKILL.md`, `AGENTS.md` block, apply logs) uses `\n`
  line endings regardless of OS.

## Implementation Plan
Changes 1-6 are independent and may be done in any order; 7 (tests) and 8-9
(docs/CI) come last.

### 1. `toolbelt/manifest.py` — portable locking + LF
Replace the top-of-file `import fcntl` with a guarded import and add
`contextmanager`:
```python
import json
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows / non-POSIX
    fcntl = None
```

Add the lock context manager (place above `save_manifest`):
```python
@contextmanager
def _manifest_lock(tb: Path):
    lock = tb / ".manifest.lock"
    start = time.time()
    if fcntl is not None:
        with lock.open("w", encoding="utf-8") as lock_f:
            while True:
                try:
                    fcntl.flock(lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.time() - start > 5:
                        raise ManifestError("manifest lock timeout") from exc
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock_f, fcntl.LOCK_UN)
    else:
        fd = None
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError as exc:
                try:
                    stale = (time.time() - lock.stat().st_mtime) > 30
                except OSError:
                    stale = False
                if stale:
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() - start > 5:
                    raise ManifestError("manifest lock timeout") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                lock.unlink()
            except OSError:
                pass
```

Rewrite `save_manifest` to use it and to force LF:
```python
def save_manifest(root: Path, data: dict) -> None:
    root = Path(root)
    tb = root / ".toolbelt"
    tb.mkdir(parents=True, exist_ok=True)
    with _manifest_lock(tb):
        data = dict(data)
        data.setdefault("schema_version", 1)
        data.setdefault("project_root", str(root.resolve()))
        if not data.get("created_at"):
            data["created_at"] = _now()
        data["updated_at"] = _now()
        fd, tmp_name = tempfile.mkstemp(prefix="manifest.", suffix=".tmp", dir=str(tb))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as tmp:
                json.dump(data, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            os.replace(tmp_name, manifest_path(root))
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
```

### 2. `toolbelt/harness.py` — executable resolution + LF
- Add `import shutil` to the imports.
- In `run_step`, the non-scaffold/non-managed-block branch currently runs
  `result = subprocess.run(list(step.argv), cwd=cwd, capture_output=True, text=True, timeout=180)`.
  Resolve the executable first so a Windows `.cmd`/`.exe` shim (npm-installed
  `claude`/`codex`) is found:
  ```python
          argv = list(step.argv)
          exe = shutil.which(argv[0]) or argv[0]
          try:
              result = subprocess.run([exe, *argv[1:]], cwd=cwd, capture_output=True, text=True, timeout=180)
  ```
  (Leave the `FileNotFoundError`/`TimeoutExpired` handling below unchanged; keep
  the `stderr` message referencing `TOOLBELT_CLAUDE_BIN`/`TOOLBELT_CODEX_BIN`.)
- Add `newline="\n"` to these text writes:
  - the scaffold branch: `target.write_text(step.scaffold_body, encoding="utf-8", newline="\n")`.
  - `_write_managed_block`: `target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")`.
  - `_remove_managed_block`: `target.write_text(text + "\n" if text else "", encoding="utf-8", newline="\n")`.
  - `_append_log`: `with path.open("a", encoding="utf-8", newline="\n") as f:`.

### 3. `toolbelt/evidence.py` — POSIX separators
- `_rel`: `return path.relative_to(root).as_posix()`.
- `detect_manifest_files`: change the `detail` argument
  `str(path.relative_to(root))` to `path.relative_to(root).as_posix()`.
- `detect_infra`: change `rel = str(path.relative_to(root))` to
  `rel = path.relative_to(root).as_posix()`. **This also fixes a real bug:** `rel`
  feeds `fnmatch.fnmatch(rel, ".github/workflows/*.yml")`, which on Windows sees
  backslashes and never matches, so `infra:github_actions` is missed. `as_posix`
  makes detection identical on all OSes.
- `detect_test_setup`: change the `detail` `str(path.relative_to(root))` to
  `path.relative_to(root).as_posix()`.

### 4. `toolbelt/recommend.py` — POSIX separators
- `_first_glob`: build the evidence with
  `path.relative_to(root).as_posix()` for BOTH the `detail` (3rd) and `source`
  (5th) arguments instead of `str(path.relative_to(root))` / `str(path.resolve())`.

### 5. `toolbelt/plan.py` — LF in `write_plan`
- `path.write_text(json.dumps(plan_to_json(plan), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")`.

### 6. `toolbelt/guard.py` — LF in `ensure_gitignore`
- `path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8", newline="\n")`.

### 7. `tests/helpers.py` — PATH separator + platform fake CLI
Rewrite `fixture_state_env`:
```python
def fixture_state_env(root: Path) -> dict[str, str]:
    state = FIXTURES / "state"
    fake = ROOT / "tests" / "fake_bin"
    suffix = ".cmd" if os.name == "nt" else ""
    env = os.environ.copy()
    env.update(
        {
            "TOOLBELT_CLAUDE_STATE": str(state / "claude_state.json"),
            "TOOLBELT_CLAUDE_PLUGINS": str(state / "installed_plugins.json"),
            "TOOLBELT_CODEX_CONFIG": str(state / "codex_config.toml"),
            "TOOLBELT_CLAUDE_BIN": str(fake / f"claude{suffix}"),
            "TOOLBELT_CODEX_BIN": str(fake / f"codex{suffix}"),
            "PATH": f"{fake}{os.pathsep}{env.get('PATH', '')}",
        }
    )
    return env
```
Also audit `RealApplyTests.setUp` in `tests/test_core.py`: it sets
`TOOLBELT_CLAUDE_BIN`/`TOOLBELT_CODEX_BIN` to `str(fake / "claude")` /
`str(fake / "codex")`. Update those two lines to append the same
`".cmd" if os.name == "nt" else ""` suffix so `RealApplyTests` runs the Windows
fakes on Windows.

### 8. `tests/fake_bin/claude.cmd` and `tests/fake_bin/codex.cmd` (new)
Both files identical, mirroring the bash fakes' behavior:
```bat
@echo off
>>"%FAKE_BIN_LOG%" echo %*
if defined FAKE_STDOUT_FILE type "%FAKE_STDOUT_FILE%"
if defined FAKE_STDERR echo %FAKE_STDERR% 1>&2
if defined FAKE_EXIT_CODE exit /b %FAKE_EXIT_CODE%
exit /b 0
```
(The POSIX `tests/fake_bin/claude` / `codex` bash scripts stay unchanged.)

### 9. `README.md`
Replace the second paragraph (currently: "Runtime constraints … Toolbelt is
POSIX-only — it uses `fcntl` for manifest locking and will not import on
Windows.") with:
```markdown
Runtime constraints are intentionally small: Python 3.11 or newer, standard
library only, no third-party packages, no build step. The `python -m toolbelt`
CLI and the unit-test suite (`python -m unittest discover -s tests`) run on
Linux, macOS, and Windows. The `make` targets and the `*.sh` helpers
(`tests/e2e_smoke.sh`, `scripts/probe_cli_output.sh`) need a POSIX shell; on
Windows run them under Git Bash or WSL, or use the native commands directly:
`python -m compileall toolbelt` (lint) and `python -m unittest discover -s tests`
(test).
```

### 10. `.github/workflows/ci.yml` (new)
```yaml
name: ci
on:
  push:
  pull_request:
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Lint
        run: python -m compileall toolbelt
      - name: Test
        run: python -m unittest discover -s tests -v
```

## Error Handling
- No `fcntl`: `_manifest_lock` uses an `O_CREAT|O_EXCL` lockfile. Contention
  behaves like today (busy-wait, `ManifestError` after 5s). A lockfile older than
  30s is treated as stale (from a crashed process) and stolen, since the
  `O_EXCL` file — unlike `flock` — is not auto-released on process death.
- Executable not found on any OS: `shutil.which` returns `None`, the raw name is
  used, and `subprocess` still raises `FileNotFoundError`, which `run_step`
  already catches and reports (rc 127 with the `TOOLBELT_*_BIN` hint) — unchanged.
- Newline forcing (`newline="\n"`) only affects writes; reads are unchanged (JSON
  and text parsing tolerate either ending).
- `as_posix()` is used only for stored/`fnmatch` string values; real filesystem
  access still goes through `Path`, so nothing about actual path resolution
  changes.

## Test Plan
Add `PortabilityTests` to `tests/test_core.py`. These pass on any OS and
exercise the Windows-specific code paths on Linux/macOS by simulating `fcntl`'s
absence. Real Windows/macOS execution is covered by the CI matrix.

```python
class PortabilityTests(unittest.TestCase):
    def test_save_manifest_works_without_fcntl(self) -> None:
        from toolbelt import manifest as m

        original = m.fcntl
        m.fcntl = None  # emulate Windows: force the lockfile path
        try:
            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                data = m.load_manifest(root)
                data["tools"] = {"x": {"state": "installed"}}
                m.save_manifest(root, data)
                self.assertEqual(m.load_manifest(root)["tools"]["x"]["state"], "installed")
                self.assertFalse((root / ".toolbelt" / ".manifest.lock").exists())
        finally:
            m.fcntl = original

    def test_manifest_uses_lf_newlines(self) -> None:
        from toolbelt.manifest import load_manifest, save_manifest

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save_manifest(root, load_manifest(root))
            raw = (root / ".toolbelt" / "manifest.json").read_bytes()
            self.assertNotIn(b"\r\n", raw)

    def test_evidence_sources_use_forward_slashes(self) -> None:
        from toolbelt.evidence import scan

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "packages" / "api").mkdir(parents=True)
            (root / "packages" / "api" / "package.json").write_text(
                '{"dependencies": {"pg": "^8"}}', encoding="utf-8"
            )
            for e in scan(root):
                self.assertNotIn("\\", e.source)
                self.assertNotIn("\\", e.detail)

    def test_github_actions_detected(self) -> None:
        from toolbelt.evidence import scan

        with tempfile.TemporaryDirectory() as td:
            root = copy_fixture_repo("terraform_infra", td)
            keys = {(e.type, e.key) for e in scan(root)}
            self.assertIn(("infra", "github_actions"), keys)
```

Run:
```sh
make lint      # or: python -m compileall toolbelt
make test      # or: python -m unittest discover -s tests
```
All existing tests plus `PortabilityTests` must pass. `make test` must still
report the full suite green on Linux, and the CI matrix must be green on
ubuntu-latest, macos-latest, and windows-latest.

## Acceptance Criteria
- [ ] With `fcntl` forced to `None`, `import toolbelt.cli` succeeds and
      `save_manifest`/`load_manifest` round-trip correctly, and the `.manifest.lock`
      file is removed afterward (`test_save_manifest_works_without_fcntl`).
- [ ] `toolbelt/manifest.py`'s `import fcntl` is wrapped in `try/except ImportError`
      and locking goes through `_manifest_lock`.
- [ ] `run_step` resolves `argv[0]` via `shutil.which(...) or argv[0]` before
      spawning.
- [ ] `.toolbelt/manifest.json` contains no `\r\n` bytes on any OS
      (`test_manifest_uses_lf_newlines`); the same LF guarantee holds for the
      `.gitignore` managed block, scaffold files, the `AGENTS.md` block, and
      `plan.json`.
- [ ] All evidence `source`/`detail` values use `/` separators
      (`test_evidence_sources_use_forward_slashes`).
- [ ] `infra:github_actions` is detected for the `terraform_infra` fixture
      (`test_github_actions_detected`) — the `fnmatch` target is `as_posix`.
- [ ] `tests/helpers.py` joins PATH with `os.pathsep` and selects
      `claude.cmd`/`codex.cmd` when `os.name == "nt"`; `RealApplyTests.setUp` does
      the same; `tests/fake_bin/claude.cmd` and `codex.cmd` exist.
- [ ] `README.md` no longer claims POSIX-only / "will not import on Windows" and
      documents the native Windows dev commands.
- [ ] `.github/workflows/ci.yml` runs lint + test on ubuntu/macos/windows.
- [ ] `make lint` and `make test` pass on Linux (existing suite unchanged +
      `PortabilityTests`); catalog still loads 9 tools.
```
