# Catalog authoring

The runtime catalog is `src/toolbelt/data/catalog.toml`. Installed distributions
load it through `importlib.resources`; a checkout path is not required. Validate
changes with `toolbelt catalog validate path/to/catalog.toml`.

The root contains only `schema_version = 2` and one or more `[[tool]]` tables.
Every tool declares:

- identity: `schema_version`, `id`, `name`, `summary`, `kind`;
- provenance: `provenance`, exact `version`, `homepage`, `license`;
- support: `platforms`, `harnesses`, `enabled`;
- authority: `permissions`, `install_scope`, `required_env`, `artifacts`;
- policy: `strong_evidence`, `weak_evidence`, `required_capabilities`,
  `suppressed_by_capabilities`, and optional `live_name`;
- contracts: exactly one `install`, `verify`, and `rollback` inline table.

Each command contract contains an `argv` array and optional repository-relative
`cwd`, `timeout_seconds`, `requires_network`, and `requires_elevation`. Commands
are direct argument vectors; shell executables and shell metacharacters are
rejected. Environment variable names belong in `required_env`; values never
belong in arguments or catalog files.

Network package provenance is exact, for example `pypi:ruff==0.15.21` or
`npm:pyright@1.1.411`, and must match `version`. A network command requires the
`network` permission. `required_env` requires `credentials-read`. Every enabled
entry must have an executable rollback contract.

Evidence keys use `type:key`, such as `test:pytest`, `config:pyright`, or
`infra:repository`. Weak evidence may explain a recommendation but cannot
authorize installation by itself.

Catalog changes are code-review changes. Confirm project ownership, upstream
release provenance, license, version pin, platform claims, command help output,
verification behavior, and rollback behavior before enabling an entry.
