# Windows Portability

## Summary

Make codex-conductor run identically on Windows and on Linux/macOS. The only true
blocker is the POSIX-only `fcntl` import in the ledger's write lock; everything
else is interpreter/installer ergonomics. This spec adds a portable advisory
file-lock abstraction, selects the Python interpreter and shell quoting per
platform when generating hook commands, ships PowerShell installer wrappers,
flips the `doctor` platform check and the packaging/OS metadata, and updates the
docs. No enforcement, ledger-format, pricing, or decision behavior changes.

## Constraints & Assumptions

- **This spec runs after `release-finalization.md` (already executed).**
  `pyproject.toml`, `conductor/cli.py`, `conductor/gc.py`, `conductor/doctor.py`,
  `LICENSE`, and `CHANGELOG.md` already exist. This spec edits real files.
- **Stdlib only.** The Windows lock uses `msvcrt` (standard library); the POSIX
  lock keeps using `fcntl`. No third-party lock library.
- **Lock semantics must match across platforms:** an exclusive, advisory, whole-
  file mutex that blocks until acquired and releases on close/process exit. The
  Windows path emulates `fcntl.flock`'s blocking behavior with a non-blocking
  `msvcrt.locking` call in a short sleep-retry loop (avoids `LK_LOCK`'s ~10s
  timeout-then-raise).
- **Do not change** the ledger's lock-file open mode (`"a"`), the per-run state
  layout, or the wrapper generator `_wrapper` (its `repr()`-escaped path literals
  are already Windows-safe).
- **Public docs stay path-clean** (`tests/test_public_docs.py`): all new README
  text uses `.\install.ps1`, `~/...`, `$PWD`, and inline code only — never a
  literal home or checkout path.
- **Do not modify** `policy/orchestration-policy.md` (exact-string assertions in
  `tests/test_install.py`).
- **Out of scope (dev-only POSIX conveniences, not functional blockers):** the
  `Makefile`, `tests/e2e_smoke.sh`, and `probe/probe.py` stay POSIX/opt-in. On
  Windows, developers use the already-documented cross-platform commands
  (`python -m unittest discover -s tests`, `python -m compileall conductor`,
  `conductor ...`). `config/hooks.json.tmpl` is an unused artifact and is left
  as-is.

**Open Questions:** none.

## Affected Files

Create:
- `conductor/filelock.py` — portable exclusive file lock.
- `install.ps1` — PowerShell equivalent of `install.sh`.
- `uninstall.ps1` — PowerShell equivalent of `uninstall.sh`.
- `tests/test_filelock.py` — lock/unlock smoke test.

Modify:
- `conductor/ledger.py` — use the portable lock instead of `fcntl` directly.
- `conductor/install.py` — generate hook commands with `sys.executable` and
  platform-correct quoting.
- `conductor/doctor.py` — the `platform` check passes on every OS.
- `pyproject.toml` — `Operating System :: OS Independent`.
- `README.md` — Requirements, Install, and Uninstall sections.

Do NOT modify: any config `.toml`, any policy `.md`, `conductor/config.py`,
providers, or the hook modules themselves.

## Public Interfaces

### `conductor/filelock.py`

```python
def lock_exclusive(handle) -> None   # block until an exclusive lock on `handle` is held
def unlock(handle) -> None           # release the lock held on `handle`
```

`handle` is an open file object (the ledger opens the lock file in text-append
mode). The implementation is selected once at import time by `os.name`.

### `conductor/install.py`

New private helper:

```python
def _hook_command(script: Path, *args: str) -> str
```

Returns the command string a provider hook runs: the current interpreter
(`sys.executable`), the wrapper script path, and any extra args, quoted for the
host shell (`shlex.quote` on POSIX; double-quote-if-spaces on Windows).

No public signature changes elsewhere.

## Implementation Plan

### 1. `conductor/filelock.py` (create, exact content)

```python
from __future__ import annotations

import os

if os.name == "nt":
    import msvcrt
    import time

    def lock_exclusive(handle) -> None:
        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)

    def unlock(handle) -> None:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def lock_exclusive(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
```

### 2. `conductor/ledger.py`
- Delete the top-level `import fcntl`.
- Add `from conductor.filelock import lock_exclusive, unlock` to the imports.
- In `append_event`, replace the two `fcntl.flock(...)` calls:

  Replace:
  ```python
      with lock_path.open("a", encoding="utf-8") as lock:
          fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
          try:
              with (state / "ledger.jsonl").open("a", encoding="utf-8") as handle:
                  handle.write(json.dumps(record, sort_keys=True) + "\n")
          finally:
              fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
  ```
  with:
  ```python
      with lock_path.open("a", encoding="utf-8") as lock:
          lock_exclusive(lock)
          try:
              with (state / "ledger.jsonl").open("a", encoding="utf-8") as handle:
                  handle.write(json.dumps(record, sort_keys=True) + "\n")
          finally:
              unlock(lock)
  ```

### 3. `conductor/install.py`
- Add `import os` to the top-level imports.
- Add the helper (place it beside the other module-level helpers, e.g. just
  before `_render_hooks_json`):
  ```python
  def _hook_command(script: Path, *args: str) -> str:
      parts = [sys.executable, str(script), *args]
      if os.name == "nt":
          return " ".join(f'"{part}"' if (" " in part or "\t" in part) else part for part in parts)
      return " ".join(shlex.quote(part) for part in parts)
  ```
- In `_render_hooks_json`, replace the nested command builder:
  ```python
      def command(module: str) -> str:
          return "python3 " + shlex.quote(str(hooks_dir / f"{module}.py"))
  ```
  with:
  ```python
      def command(module: str) -> str:
          return _hook_command(hooks_dir / f"{module}.py")
  ```
- In `_claude_hook_entries`, replace the nested command builder:
  ```python
      def command(module: str) -> str:
          return "python3 " + shlex.quote(str(hooks_dir / f"{module}.py")) + " --provider claude"
  ```
  with:
  ```python
      def command(module: str) -> str:
          return _hook_command(hooks_dir / f"{module}.py", "--provider", "claude")
  ```

### 4. `conductor/doctor.py`
Replace the `platform` check line:
```python
    check("platform", "fail" if sys.platform == "win32" else "ok", "fcntl.flock unavailable on Windows" if sys.platform == "win32" else "posix")
```
with:
```python
    check("platform", "ok", sys.platform)
```

### 5. `install.ps1` (create, exact content)

```powershell
#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python -m conductor.install @args
exit $LASTEXITCODE
```

### 6. `uninstall.ps1` (create, exact content)

```powershell
#!/usr/bin/env pwsh
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
python -m conductor.install --uninstall @args
exit $LASTEXITCODE
```

### 7. `pyproject.toml`
Replace the classifier line `    "Operating System :: POSIX",` with
`    "Operating System :: OS Independent",`.

### 8. `README.md`
a. Replace the Requirements bullet:
   > - **A POSIX host (Linux or macOS).** The ledger serializes concurrent writes
   >   with `fcntl.flock`, which is not available on Windows.

   with:
   > - **Linux, macOS, or Windows.** The ledger serializes concurrent writes with
   >   a portable advisory file lock — `fcntl.flock` on POSIX, `msvcrt.locking`
   >   on Windows.

b. Immediately after the Codex-install code block (the fenced block containing
   `bash install.sh`), add the line:
   > On Windows (PowerShell): `.\install.ps1`.

c. Immediately after the Claude-install code block (the fenced block containing
   `bash install.sh --provider claude`), add the line:
   > On Windows (PowerShell): `.\install.ps1 --provider claude`.

d. Immediately after the Uninstall code block (the fenced block containing
   `bash uninstall.sh`), add the line:
   > On Windows (PowerShell): `.\uninstall.ps1` (add `--provider claude` for
   > Claude Code).

### 9. `tests/test_filelock.py` (create, exact content)

```python
import tempfile
import unittest
from pathlib import Path


class FileLockTests(unittest.TestCase):
    def test_lock_unlock_reacquire(self):
        from conductor.filelock import lock_exclusive, unlock

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".lock"
            with path.open("a", encoding="utf-8") as handle:
                lock_exclusive(handle)
                unlock(handle)
            with path.open("a", encoding="utf-8") as handle:
                lock_exclusive(handle)
                unlock(handle)


if __name__ == "__main__":
    unittest.main()
```

## Error Handling

- Windows `lock_exclusive` retries on `OSError` (region already locked) every
  50 ms until it succeeds, matching `flock`'s block-until-acquired behavior;
  crash safety is preserved because closing the handle / exiting the process
  releases the OS lock on both platforms.
- Windows `unlock` swallows `OSError` (e.g. already released) so ledger writes in
  the `finally` block never raise on teardown.
- `_hook_command` uses `sys.executable`, an absolute interpreter path, so the
  installed hooks invoke the same Python that ran the installer on any OS; paths
  containing spaces are quoted per platform.

## Test Plan

- **`tests/test_ledger.py::test_flock_keeps_concurrent_writes_valid`** (existing,
  unchanged) now exercises the portable lock. It spawns two processes writing 200
  events each and asserts 400 intact records — this is the cross-platform lock
  regression (validates `fcntl` on POSIX CI, `msvcrt` on Windows CI). It must
  still pass.
- **`tests/test_filelock.py`** (new): acquires, releases, and re-acquires the
  lock on the host platform.
- **`tests/test_install.py`** and **`tests/test_install_claude.py`** (existing,
  unchanged): still pass. `_hook_command` keeps the wrapper-script path and
  `--provider claude` as substrings and adds no `PYTHONPATH=`, which is all those
  tests assert. Install remains idempotent because `sys.executable` is stable
  within a process.
- **`tests/test_doctor.py`** (existing, unchanged): the codex/claude all-pass
  tests still pass on POSIX and now also pass on Windows because the `platform`
  check no longer fails there.

Run (cross-platform):

```bash
python -m unittest discover -s tests -v
python -m compileall conductor
```

## Acceptance Criteria

- [ ] `import conductor.ledger` (and therefore `conductor.status`,
      `conductor.report`, `conductor.cli`, and the hooks) succeeds on Windows —
      no unconditional `import fcntl` remains in `conductor/ledger.py`.
- [ ] `conductor/filelock.py` provides `lock_exclusive`/`unlock`, backed by
      `fcntl` on POSIX and `msvcrt` on Windows, selected by `os.name`.
- [ ] The ledger's concurrent-write test passes unchanged, proving mutual
      exclusion via the new abstraction.
- [ ] Generated hook commands use `sys.executable` (not the literal `python3`)
      and are quoted for the host shell; `tests/test_install.py` and
      `tests/test_install_claude.py` still pass.
- [ ] `conductor doctor` reports `platform` as `ok` on Windows, and its all-pass
      tests hold on every OS.
- [ ] `install.ps1` / `uninstall.ps1` exist and, from the checkout, run
      `python -m conductor.install [--uninstall] @args` with the same flags as the
      bash scripts.
- [ ] `pyproject.toml` declares `Operating System :: OS Independent`; `README.md`
      documents Windows install/uninstall and no longer claims POSIX-only;
      `tests/test_public_docs.py` passes.
- [ ] `python -m unittest discover -s tests -v` passes (existing tests plus
      `test_filelock.py`); `python -m compileall conductor` succeeds.
- [ ] No changes to enforcement, ledger format, pricing, config, or policy.
```
