# Install Rehearsal

Install Rehearsal previews what a trusted developer-tool installer writes to its user
profile. It redirects home and application-data environment variables into a disposable
directory, executes the installer directly without a shell, snapshots that directory,
and stores a deterministic JSON receipt of the observed changes.

Every report begins with `REHEARSAL_NOT_SANDBOXED`. This tool is an observability aid,
not a security boundary: it does not isolate the network, processes, system directories,
registries, keychains, package managers, or writes made outside the redirected profile.
Only rehearse installers you already trust to execute on the device.

## Install

Install from this monorepo with Python 3.11 or newer:

```sh
python -m pip install ./install-rehearsal
```

For development:

```sh
cd install-rehearsal
uv sync --extra dev --locked
```

The runtime uses only Python's standard library.

## Run an installer

Separate Install Rehearsal options from the installer argv with `--`:

```sh
install-rehearsal run -- python tests/fixtures/profile_installer.py
```

Typical text output is:

```text
REHEARSAL_NOT_SANDBOXED
Run: 20260714T190218795232Z-692c3ca1
Installer: exited (exit=0)
Duration: 0.011s
Observed profile changes: 2
  created      .config/example
  created      .config/example/config.toml
```

Use `--json` for the canonical receipt and `--keep-profile` to retain the redirected
profile. A retained profile keeps its recovery marker so it can be located and cleaned
later.

```sh
install-rehearsal run --json -- npm install -g trusted-tool
install-rehearsal --store ./receipts run --timeout 30 -- trusted-installer --flag
```

Installers keep the caller's working directory. Only their user-profile environment is
redirected. Common credential-shaped environment variables are not inherited, and
secret-shaped argv and output values are redacted from receipts. Executable and output
digests are retained for comparison.

## Inspect and compare receipts

Receipts default to `~/.install-rehearsal/receipts`. Select another location with the
global `--store PATH` option.

```sh
install-rehearsal show latest
install-rehearsal show RUN_ID --json
install-rehearsal compare FIRST_RUN_ID SECOND_RUN_ID
```

Comparison ignores run IDs, timestamps, durations, and disposable profile paths. It
returns `0` when no semantic difference exists and `1` when installer behavior differs.

## Recover retained profiles

List profiles retained intentionally or left behind after interrupted cleanup:

```sh
install-rehearsal recover
install-rehearsal recover RUN_ID --clean
```

Cleanup accepts only a direct child whose name is bound to the marker's run ID. It
refuses the `profiles` root, nested paths, and paths outside the selected receipt store.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | Command completed; for `run`, the installer exited successfully. |
| `1` | `compare` found semantic differences. |
| `2` | Command-line parsing failed. |
| `3` | Install Rehearsal could not execute or read the requested operation. |
| `10` | The installer failed to launch, timed out, or exited nonzero. |

Output is consumed incrementally: the complete byte streams are hashed while only the
configured prefix is retained. POSIX snapshots use descriptor-relative, no-follow opens
with identity revalidation. On Windows, the installer tree is assigned to a kill-on-close
Job Object and quiesced before the path-based snapshot fallback runs.

Receipts are written atomically before automatic cleanup. An active marker is removed
only after receipt persistence and successful cleanup; a remaining marker identifies a
retained or abandoned disposable profile. If installer execution and cleanup both fail,
the installer failure remains the primary exit status.

## Development checks

```sh
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```

The root CI runs tests on Linux, macOS, and Windows with Python 3.11 and 3.13. The
development activity ledger at [docs/tool-activity.md](docs/tool-activity.md) records
what Toolbelt, Conductor, Codex, and verification actually contributed.
