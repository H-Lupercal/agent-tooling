# Catalog schema

The strict public v2 schema and review rules are documented in
[`docs/catalog-authoring.md`](../docs/catalog-authoring.md). The live catalog is
`src/toolbelt/data/catalog.toml` and is packaged with the wheel and sdist.

Validate the bundled catalog with:

```sh
toolbelt catalog validate --json
```
