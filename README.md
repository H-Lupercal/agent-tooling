# Toolbelt

Toolbelt is a per-project AI toolchain manager. It scans a repository, matches evidence against a curated local catalog, proposes an approval-based plan, and applies approved MCP servers, Claude Code plugins, repo skills, language servers, and dev tools.

Runtime constraints are intentionally small: Python 3.11 or newer, standard library only, no build step.

## Commands

Expected CLI flow:

```sh
python3 -m toolbelt scan --path .
python3 -m toolbelt plan --path .
python3 -m toolbelt apply --path .
python3 -m toolbelt reconcile --path .
python3 -m toolbelt guard --path .
```

Use `--dry-run` or `TOOLBELT_DRY_RUN=1` before live apply work. Unit tests use `TOOLBELT_CLAUDE_BIN` and `TOOLBELT_CODEX_BIN` to point at `tests/fake_bin`.

## Secrets

Toolbelt never writes secret values to config files and never passes secret values to `claude mcp add` or `codex mcp add`. Catalog entries list required environment variable names in `secrets`; guard/status reports whether each name is present in the shell or named in `.toolbelt/secrets.env`.

Do not commit:

- `.toolbelt/secrets.env`
- `.toolbelt/state/`
- `.toolbelt/cache/`
- `.toolbelt/plan.json`

## Catalog

The seed catalog lives at `catalog/catalog.toml`; schema notes are in `catalog/SCHEMA.md`. The catalog is read-only TOML. Toolbelt-owned runtime data is JSON.

## Development

```sh
make test
make lint
make probe
make e2e
```

`make e2e` is gated by `RUN_LIVE=1`; otherwise it prints the command that would run.
