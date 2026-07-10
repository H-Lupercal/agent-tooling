# Releasing

1. Confirm `main` is green on all CI jobs.
2. Update `CHANGELOG.md` and the version in `src/toolbelt/__init__.py`.
3. Run `uv sync --extra dev --locked` and `uv run make release-check`.
4. Inspect wheel and sdist contents and run the clean-environment doctor/apply
   dry-run from outside the checkout.
5. From the monorepo root, create and push an annotated `toolbelt-vX.Y.Z` tag
   from the reviewed commit. The tag version must match Toolbelt's package version.
6. The release workflow rebuilds and retests artifacts, checks metadata, creates
   checksums and a CycloneDX SBOM, attests provenance, publishes through PyPI
   Trusted Publishing, and creates the GitHub release.
7. Verify the PyPI files and GitHub assets match `SHA256SUMS`; install from PyPI
   into a new environment and run `toolbelt doctor --strict --json`.

The trusted publisher must target the `H-Lupercal/agent-tooling` repository,
`release-toolbelt.yml` workflow, and `pypi-toolbelt` environment. Never publish from
an uncommitted tree or add a long-lived PyPI token fallback.
