# Catalog Schema

`catalog.toml` is read-only project data. Toolbelt loads it with `tomllib` and writes all runtime state as JSON.

Top-level fields:

- `schema_version`: integer. Current value is `1`.
- `[[tool]]`: one entry per approved or candidate tool.

Required `tool` fields:

- `id`: stable unique identifier.
- `kind`: one of `mcp_server`, `connector`, `plugin`, `skill`, `lsp`, `dev_tool`.
- `name`, `summary`, `provenance`, `homepage`: display and provenance metadata.
- `approved`: boolean. Unapproved tools are candidates only.
- `foundational`: boolean. Approved foundational tools are planned for greenfield repos.
- `permissions`: list using the closed permission vocabulary.
- `install_scope`: one of `project`, `user`, `repo-committed`.
- `secrets`: environment variable names required at runtime. Values are never stored.
- `artifacts`: generated cache or state paths associated with the tool.
- `mcp_name`: harness-visible MCP name for `mcp_server` and `connector`; empty otherwise.
- `verify_argv`: command used by verify actions, or an empty list.
- `catalog_version`: string version for the catalog entry.

Each tool must have at least one `[[tool.match]]` group. A group may contain:

- `any_files`: glob patterns relative to the project root.
- `manifest_file`: manifest filename such as `package.json` or `pyproject.toml`.
- `manifest_deps`: dependency names expected in `manifest_file`.
- `langs`: normalized language names such as `python` or `typescript`.
- `infra`: infrastructure signals such as `terraform` or `postgres`.
- `brief_keywords`: greenfield brief phrases.
- `weight`: integer confidence contribution when the group matches.

Each tool must have at least one `[[tool.apply]]` step. Common fields:

- `apply_via`: one of `claude_mcp`, `codex_mcp`, `claude_plugin`, `scaffold`, `managed_block`, or `command`.
- `harness`: `claude_code`, `codex`, or empty for direct commands.

Step-specific fields:

- `claude_mcp` and `codex_mcp`: `mcp_command`, optional `mcp_args`.
- `claude_plugin`: `plugin_ref`.
- `scaffold`: `scaffold_path`, `scaffold_body`.
- `managed_block`: `block_path`, `block_body` (inserts an idempotent, tool-id-delimited block into a possibly-existing file; non-destructive).
- `command`: `command_argv`, optional `rollback_argv`.

Validation rejects duplicate ids, duplicate `(apply_via, mcp_name)` claims, unknown keys, missing match/apply groups, missing required step fields (including `block_path` and `block_body` for `managed_block`), and values outside the closed vocabularies.

## Proposals & Discovery

Agent-drafted entries from `toolbelt discover` are staged in
`catalog/proposed/`, one `<id>.toml` per tool. Staged proposals are not loaded by
Toolbelt until a human merges them into `catalog/catalog.toml`.

Run `toolbelt validate [PATH]` before review. Validation runs the normal catalog
schema checks plus safety lint: proposals must use `approved = false`, include
provenance, homepage, permissions, and `catalog_version`, avoid secret values in
`mcp_args` or `command_argv`, and avoid ids or MCP names already claimed by the
live catalog.
