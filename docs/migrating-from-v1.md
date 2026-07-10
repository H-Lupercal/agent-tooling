# Migrating from Toolbelt v1

Version 2 intentionally does not load v1 plans, JSON manifests, JSONL apply logs,
catalog entries, approval flags, or checkout-pinned launchers. Reusing those
objects would bypass v2's digest, capability, rollback, and path contracts.

1. Preserve the old `.toolbelt/manifest.json` outside active automation.
2. Run `toolbelt migrate-v1 --path PROJECT --out candidate.toml --json`.
3. Review the disabled candidate. It is an inventory aid, not an executable v2
   catalog and it does not import historical decisions.
4. Validate or author corresponding strict entries using
   [catalog-authoring.md](catalog-authoring.md).
5. Generate a fresh capability snapshot, run `scan` and `discover`, then create a
   new v2 plan.
6. Adopt tools that already exist rather than reinstalling them.
7. Commit `.toolbelt/lock.toml` only after verification and team review.

`migrate-v1` is offline and does not create `state.sqlite3`, run commands, or mark
anything managed. There is no compatibility alias or automatic in-place upgrade.
