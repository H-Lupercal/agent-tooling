# Proposed catalog entries (staging)

Agent-drafted catalog entries land here, one `<id>.toml` per tool, produced from
`toolbelt discover` briefs. Files here are NOT loaded by Toolbelt; `load_catalog`
reads only `catalog/catalog.toml`.

Workflow:
1. `toolbelt discover` prints a gap brief and entry template.
2. The agent writes a draft to `catalog/proposed/<id>.toml` (`approved = false`).
3. `toolbelt validate` must pass (schema plus safety lint).
4. A human reviews the file and merges it into `catalog/catalog.toml` with
   `approved = false`, then flips `approved = true` once the tool is vetted.
