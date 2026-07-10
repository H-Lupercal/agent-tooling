# Professional Public Release Design

## Goal

Make `agent-tooling` a professional monorepo that releases `toolbelt-ai` and
`codex-conductor` independently without changing either package's public runtime
contract.

## Repository architecture

The repository keeps two independently installable Python projects:

- `toolbelt/` builds and publishes `toolbelt-ai`.
- `codex-conductor/` builds and publishes `codex-conductor`.

Root-level repository metadata owns concerns GitHub only recognizes at the repository
root: CI, CodeQL, Dependabot, release workflows, CODEOWNERS, security policy,
contribution guidance, and the monorepo landing page. Project-specific source,
lockfiles, package documentation, and build configuration stay inside each project.

## CI and release model

CI runs both projects on Linux, macOS, and Windows with Python 3.11, 3.12, and 3.13.
Quality, branch-enabled coverage, distribution installation, end-to-end, dependency
audit, and artifact validation jobs use explicit project working directories. Action
dependencies are pinned to immutable commit SHAs.

Releases are independent and use namespaced tags:

- `toolbelt-vX.Y.Z`
- `codex-conductor-vX.Y.Z`

Each release workflow verifies its tag against the package version, builds only its
package, creates checksums and a reproducible SBOM, attests the distributions, and
publishes through a package-specific protected PyPI environment. No workflow publishes
both packages from one tag.

## Public metadata and documentation

Both package metadata files point to the new monorepo and the correct project
subdirectory. Root documentation explains project selection, development commands,
release tags, security reporting, support, and contribution routing. Deleted repository
URLs are forbidden by an automated release-contract test.

## Quality target

The release gate is 90% branch-enabled combined coverage for each package. Tests focus
on meaningful failure, rollback, accounting, identity, installer, policy, and
transaction paths. Coverage exclusions remain limited to genuine abstract interfaces
and interpreter entry points; tests must not inflate coverage through blanket pragmas.

## Security and trust boundaries

The audit covers secrets in the current tree and history, dependency vulnerabilities,
shell invocation boundaries, symlink and path handling, lifecycle correlation,
workflow permissions, untrusted GitHub event interpolation, and artifact provenance.
Release workflows use minimal permissions and never expose PyPI credentials to build
jobs.

## Acceptance

A release candidate is acceptable when:

1. Root release-contract tests pass.
2. Both projects pass formatting, linting, Pyright, 90% branch-enabled coverage,
   distribution tests, E2E tests, lock checks, clean builds, and Twine checks.
3. Dependency audits report no known vulnerabilities.
4. Conductor installs into disposable Codex and Claude homes, passes strict doctor
   checks, processes a complete lifecycle, reports it, repairs managed files, and
   uninstalls conservatively.
5. Git history contains no confirmed credentials and the final working tree is clean.

No package is pushed or published as part of this work.

