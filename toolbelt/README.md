# Toolbelt

Toolbelt is a conservative, deterministic CLI for discovering and managing
developer tools used by people and AI coding agents. It scans repository data,
loads a locally reviewable catalog, inventories supported harnesses, creates a
digest-bound plan, and applies only explicitly approved actions.

Toolbelt 2 is a clean break from the prototype. Read-only commands do not create
project state. Mutations use direct argument vectors (never a shell), bounded
output and timeouts, an SQLite journal, verification before declaration, and
reverse-order rollback.

## Install

Toolbelt requires Python 3.11 or newer.

```sh
pipx install toolbelt-ai
# or
uv tool install toolbelt-ai

toolbelt --version
toolbelt doctor --strict --json
```

From a source checkout:

```sh
uv sync --extra dev --locked
uv run toolbelt doctor --strict
```

## Quick start

```sh
# Pure repository inspection.
toolbelt scan --path . --json
toolbelt discover --path . --json

# Create a plan. Network and user-scope authority are independent.
toolbelt plan --path . --allow-network --allow-user-scope --out .toolbelt/plan.json --json

# Check every command and permission without executing tool actions.
toolbelt apply \
  --path . \
  --plan .toolbelt/plan.json \
  --allow-network \
  --allow-user-scope \
  --dry-run \
  --json

# Execute only after reviewing the plan.
toolbelt apply \
  --path . \
  --plan .toolbelt/plan.json \
  --allow-network \
  --allow-user-scope \
  --yes
```

If live provider output does not match Toolbelt's versioned inventory contract,
capability state is `unknown` and mutating recommendations remain blocked. For
automation, pass a strict snapshot with `--capabilities capabilities.json`; see
[the CLI reference](docs/cli.md).

## Safety model

- Catalog files are strict TOML, size-bounded, package-version pinned, and reject
  duplicate live names, shell wrappers, shell metacharacters, credential-shaped
  arguments, incomplete rollback, and undeclared permissions.
- Plans bind the catalog bytes, capability snapshot, repository content, Git
  commit, dirty state, exact commands, creation time, and expiry into SHA-256
  digests. Apply rejects any drift.
- Existing unmanaged tools are offered `adopt`, `leave_unmanaged`, or `replace`;
  Toolbelt never silently reinstalls them.
- `--allow-network`, `--allow-user-scope`, and `--allow-elevation` are separate
  grants and must be present again at apply time.
- Commands execute without a shell, in their own process group, with timeouts,
  bounded captured output, and redaction of values from declared environment
  variables.
- The declaration is written only after every action verifies. Failures replay
  rollback in reverse order and remain recoverable with `toolbelt recover`.

Toolbelt reduces accidental mutation; it is not a sandbox. Review catalog
changes and plans before authorizing them.

## State

- `.toolbelt/lock.toml` is the deterministic declaration and may be committed.
- `.toolbelt/plan.json` is a short-lived, repository-bound plan.
- `.toolbelt/state.sqlite3` is the local WAL journal for transactions, command
  results, backups, and recovery.
- `.toolbelt/backups/` contains transaction recovery material.

Keep plans, the SQLite database, backups, and lock files out of source control
unless your team's policy explicitly says otherwise; only `lock.toml` is designed
as a portable declaration. Secret values are never written to the declaration.

## Commands

Toolbelt provides `scan`, `discover`, `plan`, `apply`, `status`, `doctor`,
`verify`, `adopt`, `remove`, `reconcile`, `recover`, `catalog validate`, and
`migrate-v1`. All meaningful outputs support a single versioned JSON object.
See [docs/cli.md](docs/cli.md) for flags, exit codes, and examples.

## Documentation

- [Architecture and trust boundaries](docs/architecture.md)
- [CLI reference](docs/cli.md)
- [Catalog authoring](docs/catalog-authoring.md)
- [Migrating from v1](docs/migrating-from-v1.md)
- [Security policy](SECURITY.md)
- [Contributing](CONTRIBUTING.md)
- [Release process](RELEASING.md)

## Development

```sh
uv sync --extra dev --locked
uv run make check
uv run make e2e
uv run make distribution   # requires package-index access
uv run make security
```

CI covers Python 3.11–3.13 on Linux, macOS, and Windows, plus branch-aware
coverage, clean wheel/sdist installs, dependency audit, CodeQL, and SBOM output.
Tagged releases use PyPI Trusted Publishing and attach checksums, provenance
attestations, and a CycloneDX SBOM.
