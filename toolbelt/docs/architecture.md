# Architecture

Toolbelt separates observation, intent, mutation, and declaration so a failed or
stale operation cannot silently become managed state.

## Data flow

1. `scanner.py` traverses a bounded repository tree without following symlinks or
   importing project code. It returns immutable evidence and bounded warnings.
2. Provider adapters run bounded, read-only inventory commands. Parse failure is
   represented as unknown capability state, not absence.
3. `catalog.py` validates the bundled or operator-selected TOML catalog through
   strict Pydantic models and additional provenance/command safety rules.
4. `policy.py` combines evidence, capabilities, and explicit scope grants into
   advisory or actionable recommendations.
5. `planner.py` canonicalizes actions and binds them to repository, catalog,
   capability, Git, time, and exact command digests.
6. `executor.py` revalidates every binding, preflights permissions and binaries,
   records a transaction, applies actions, verifies the complete set, and writes
   the declaration. Failure triggers reverse-order rollback.
7. `state.py` stores the local journal in SQLite WAL mode and renders the portable
   declaration as deterministic TOML.

## Trust boundaries

Repository files, provider output, catalog overrides, plan files, environment
variables, subprocess output, and existing `.toolbelt` state are untrusted input.
They are size-bounded and schema-validated before use. Catalog entries are still
operator-controlled code authority: approving a catalog command authorizes that
binary and argument vector to execute.

Toolbelt does not invoke a shell. A trusted executable may itself interpret input
or run other programs, so provenance and version review remain necessary.

## Atomicity and recovery

The transaction state machine is `planned → preflight → applying → verifying →
succeeded`. Failure moves through `rolling_back` to `rolled_back` or
`rollback_failed`; interruption is recorded explicitly. State writes use bounded
SQLite transactions. Declaration files use same-directory temporary files,
flush/fsync where supported, and atomic replacement.

Only the declaration commit occurs after full verification. Backups retain the
previous declaration so `recover` can safely finish an interrupted rollback.

## Platform behavior

Repository paths use a portable relative-path contract and reject absolute paths,
parent traversal, NUL/control characters, Windows device names, ambiguous trailing
characters, symlink components, and reparse points. Process-group handling uses
POSIX sessions or Windows process groups as available.
