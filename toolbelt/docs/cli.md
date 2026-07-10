# CLI reference

Every JSON response is one object with `schema_version: 2`, `command`, `ok`, and
either `data` or `error`. Diagnostics go to stderr. Unexpected tracebacks are
hidden unless global `--debug` is present.

## Commands

- `toolbelt scan` — pure, bounded repository evidence collection.
- `toolbelt discover` — capability-aware recommendations; never writes state.
- `toolbelt plan` — create a digest-bound plan; writes only when `--out` is set.
- `toolbelt apply` — preflight or transactionally execute a plan.
- `toolbelt status` — read the declaration and local transaction state.
- `toolbelt doctor` — distribution checks, plus project checks when `--path` is set.
- `toolbelt verify` — run verification contracts for declared tools.
- `toolbelt adopt` — verify and declare an existing unmanaged tool.
- `toolbelt remove` — execute the catalog rollback contract and update declaration.
- `toolbelt reconcile` — report declaration/catalog/live-inventory drift.
- `toolbelt recover` — finish rollback for an interrupted transaction.
- `toolbelt catalog validate` — validate the bundled or a supplied strict catalog.
- `toolbelt migrate-v1` — write a disabled offline migration candidate.

Run `toolbelt COMMAND --help` for the authoritative flags.

## Capabilities

`discover`, `plan`, `apply`, `verify`, `adopt`, `remove`, and `reconcile` accept
`--capabilities FILE`. The file must match `CapabilitySnapshot` exactly:

```json
{
  "schema_version": 2,
  "provider": "combined",
  "provider_version": null,
  "status": "known",
  "native": ["filesystem", "git"],
  "installed": ["ruff"],
  "managed": [],
  "errors": []
}
```

Without a file, Toolbelt queries supported provider inventory commands. Unknown,
malformed, oversized, timed-out, or nonzero provider output produces an unknown
snapshot and blocks new mutation recommendations.

## Planning and approval

`plan` and `apply` both enforce independent `--allow-network`,
`--allow-user-scope`, and `--allow-elevation` grants. A grant on a saved plan is
not authority to execute it later. Non-dry apply additionally requires `--yes`.

Plans expire after one hour by default. Repository content, catalog bytes,
capabilities, Git HEAD/dirty state, and plan content must still match at apply.

## Doctor modes

`toolbelt doctor --strict --json` without `--path` validates the installed
distribution and bundled catalog. Adding `--path PROJECT` checks repository scan,
permissions, declaration, state database integrity, and capability readiness.
In strict mode every warning makes readiness nonzero.

## Exit codes

| Code | Meaning |
|---:|---|
| 0 | success/readiness |
| 1 | valid result with readiness or drift findings |
| 2 | usage error |
| 3 | validation error |
| 4 | stale or expired plan |
| 5 | mutation not approved |
| 6 | apply failed and rollback completed |
| 7 | rollback incomplete |
| 8 | verification failed |
| 9 | managed-state drift |
| 10 | unexpected internal failure |

## Environment variables

- `TOOLBELT_CATALOG` selects a strict local catalog override.
- `TOOLBELT_CAPABILITIES` selects a strict capability snapshot when the matching
  CLI flag is omitted.

No environment variable grants network, user-scope, elevation, or mutation
approval.
