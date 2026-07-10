# Releasing

1. Ensure `CHANGELOG.md` and `src/conductor/__init__.py` contain the intended
   semantic version.
2. Run `make release-check PYTHON=.venv/bin/python`; it includes quality,
   coverage, artifact installation, end-to-end, audit, and SBOM gates.
3. Commit the release metadata and create a signed `vX.Y.Z` tag.
4. Push the tag. The release workflow rebuilds artifacts, verifies the tag and
   package versions match, writes SHA-256 checksums, attests the artifacts, and
   publishes through PyPI trusted publishing, and creates a GitHub Release with
   the checksums and SBOM.
5. Verify a clean installation and run `conductor doctor --strict` for each
   supported provider before announcing the release.

Do not upload artifacts built from a dirty tree or publish manually with a PyPI
API token.
