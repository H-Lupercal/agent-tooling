# Toolbelt

Toolbelt is a per-project AI toolchain manager. It scans a repository, matches
the evidence it finds against a curated local catalog, proposes an
approval-gated plan, and applies approved MCP servers, connectors, Claude Code
plugins, repo-committed skills, language servers, and dev tools across the
Claude Code and Codex harnesses.

Toolbelt requires Python 3.11 or newer plus Pydantic and PathSpec. It is built as
a wheel and source distribution and exposes the `toolbelt` console entry point.
The package and test suite run on Linux, macOS, and Windows. The `make` targets
and `*.sh` helpers (`tests/e2e_smoke.sh`, `scripts/probe_cli_output.sh`) need a
POSIX shell; on Windows run them under Git Bash or WSL, or use the native
commands directly: `python -m compileall src/toolbelt` and `python -m pytest`.

## Installation

Install from a source checkout:

```sh
python -m pip install .
toolbelt --help
```

Contributors should install the development dependencies in editable mode:

```sh
python -m pip install -e ".[dev]"
```

## Commands

Every command accepts `--path` (default `.`).

```sh
# Detect evidence and show recommendations.
python3 -m toolbelt scan --path .

# Find languages/infra the catalog doesn't cover yet (agent-driven discovery).
python3 -m toolbelt discover --path .

# Force greenfield mode for a new repo; optionally attach an intent brief.
python3 -m toolbelt init --greenfield [--brief brief.md]

# Write .toolbelt/plan.json.
python3 -m toolbelt plan --path . [--prune] [--out FILE]

# Show each action as an approval card and apply the approved ones.
python3 -m toolbelt apply --path . [--yes | --only a1,a2] [--dry-run]

# Managed tools plus a secrets/drift/gitignore audit.
python3 -m toolbelt status --path . [--json]

# Re-run recorded verify commands for managed tools.
python3 -m toolbelt verify --path . [--tool ID]

# Roll back a single managed tool.
python3 -m toolbelt remove --path . --tool ID [--dry-run]

# Realign the manifest with reality and write a prune plan.
python3 -m toolbelt reconcile --path .

# Audit secrets and .gitignore; --fix rewrites the managed .gitignore block.
python3 -m toolbelt guard --path . [--fix]

# Validate agent-drafted entries staged in catalog/proposed/.
python3 -m toolbelt validate [PATH]
```

`scan`, `plan`, and `apply` auto-detect the mode (greenfield vs existing) from
the tree; `init --greenfield` forces greenfield and, with `--brief`, copies the
brief to `.toolbelt/brief.md` and records declared stack and goals. Applying is
approval-gated: each action prints a card and runs only after you approve it.
`--yes` approves everything, `--only a1,a2` approves specific action ids
(`--yes` and `--only` are mutually exclusive).

## Dry runs

Use `--dry-run` or `TOOLBELT_DRY_RUN=1` to print the exact commands `apply`
would run without executing them.

## Secrets

Toolbelt never writes secret values to config files and never passes them to
`claude mcp add` or `codex mcp add`. Catalog entries list required environment
variable *names* in `secrets`; `status` and `guard` report whether each name is
present in the shell environment or defined in `.toolbelt/secrets.env`.

## State and .gitignore

Toolbelt keeps its state under `.toolbelt/` as JSON:

- `.toolbelt/manifest.json` — record of every managed tool: why it was
  installed, what secrets it needs, and how to remove it. **Committed.**
- `.toolbelt/plan.json` — the pending plan. Ignored.
- `.toolbelt/state/` — per-apply JSONL logs. Ignored.
- `.toolbelt/cache/` — reserved cache directory. Ignored.
- `.toolbelt/secrets.env` — local secret definitions. Ignored — never commit it.

`toolbelt guard --fix`, and every `apply`, maintains a managed block in
`.gitignore` covering the ignored paths above plus any tool artifacts
(for example `.ruff_cache/`).

The conventions skill writes Claude Code instructions to
`.claude/skills/toolbelt-conventions/SKILL.md` and Codex instructions to a
managed block in `AGENTS.md`.

## Catalog

The seed catalog lives at `src/toolbelt/data/catalog.toml` in the source tree
and is bundled as an installed package resource. Its authoring schema is
documented in `catalog/SCHEMA.md`. The catalog is read-only TOML; all
Toolbelt-owned runtime state is JSON. Point Toolbelt at a different local
catalog with `TOOLBELT_CATALOG=/path/to/catalog.toml`.

## Discovery

`toolbelt discover` reports **gaps**: languages and infrastructure signals in the
repo that no catalog tool covers. It prints a ready-to-fill entry template for
each gap. Toolbelt never browses the web itself; the AI agent it runs inside does
the research and writes drafts to `catalog/proposed/<id>.toml`. `toolbelt
validate` checks those drafts with schema validation plus safety lint:
`approved` must be false, args must not contain secret values, and
provenance/homepage/permissions must be present. A human then merges a validated
draft into `src/toolbelt/data/catalog.toml` as `approved = false` and flips it
to `true` once vetted.

## Environment variables

- `TOOLBELT_DRY_RUN=1` — force dry-run for `apply`.
- `TOOLBELT_MIN_CONFIDENCE` — minimum confidence for a recommendation to be
  planned (default `2`).
- `TOOLBELT_CATALOG` — override the catalog path.
- `TOOLBELT_CLAUDE_BIN` / `TOOLBELT_CODEX_BIN` — override the `claude` / `codex`
  executables. The unit tests point these at `tests/fake_bin`.
- `TOOLBELT_CLAUDE_STATE` / `TOOLBELT_CODEX_CONFIG` / `TOOLBELT_CLAUDE_PLUGINS` —
  override the files Toolbelt reads to detect live harness state.

## Development

```sh
python -m pip install -e ".[dev]"
make test    # python -m pytest
make lint    # python -m ruff check .
make format-check
make typecheck
make build
make probe   # scripts/probe_cli_output.sh — records live CLI facts
make e2e     # runs tests/e2e_smoke.sh when RUN_LIVE=1; otherwise prints a reminder
```

`make e2e` runs a live smoke test only when `RUN_LIVE=1`; otherwise it prints how
to enable it.
