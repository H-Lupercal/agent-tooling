# Changelog

All notable changes are recorded here. The project follows semantic versioning.

## 2.0.0 - 2026-07-09

### Changed

- Rebuilt the package around strict v2 Pydantic contracts and a `src` layout.
- Made repository scans and operational status commands read-only.
- Added capability-aware conservative policy and explicit adoption semantics.
- Bound plans to repository, Git, catalog, capability, time, and exact commands.
- Replaced JSON/JSONL prototype state with transactional SQLite WAL state and a
  deterministic TOML declaration.
- Added bounded direct-process execution, verification-before-commit, rollback,
  recovery, stable JSON output, and stable exit codes.
- Added cross-platform CI, clean artifact tests, dependency audit, CodeQL, SBOM,
  attestations, and PyPI Trusted Publishing.
- Restricted source distributions to public documentation and portable project
  content; internal planning material and checkout-specific paths are excluded.

### Breaking

- Removed all v1 plans, manifests, catalogs, compatibility modules, command
  aliases, implicit approval behavior, and checkout-pinned execution paths.
- `migrate-v1` writes a disabled review candidate; it does not import decisions.
