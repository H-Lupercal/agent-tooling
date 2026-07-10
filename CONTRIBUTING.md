# Contributing

Contributions are welcome through issues and pull requests in this repository. Follow
the [Code of Conduct](CODE_OF_CONDUCT.md) in all project spaces.

## Choose the project

Keep changes within `toolbelt/` or `codex-conductor/` unless they alter shared
repository automation or governance. Update the matching changelog and documentation
when behavior changes. Avoid coupling the packages: they are built, installed, and
released independently.

## Setup

```sh
git clone https://github.com/H-Lupercal/agent-tooling.git
cd agent-tooling

cd toolbelt
uv sync --extra dev --locked

# Or, in a separate environment:
cd ../codex-conductor
uv sync --extra dev --locked
```

Use test-driven development for behavior changes. Before opening a pull request, run
the root release-contract test and the changed project's `make check` target. Changes
to packaging, installation, dependency locks, or release automation must also run the
distribution and E2E gates documented in the project README.

Pull requests should explain the user-visible outcome, breaking behavior, security or
trust-boundary impact, tests run, and any platform limitations. Never commit secrets,
provider transcripts, private repository fixtures, state databases, recovery data,
virtual environments, or build artifacts.
