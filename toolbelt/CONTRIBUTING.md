# Contributing

By participating, follow [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Setup

```sh
git clone https://github.com/H-Lupercal/agent-tooling.git
cd agent-tooling/toolbelt
uv sync --extra dev --locked
uv run make check
uv run make e2e
```

Add or update tests before implementation for behavior changes. Keep scans and
status paths pure, use direct argv rather than shells, preserve stable JSON/error
contracts, and treat catalog edits as executable-code review.

Before opening a pull request, run `uv run make check`. Changes to packaging,
catalog data, or release behavior should also run `uv run make distribution` and
`uv run make security`. Explain breaking behavior and update the changelog/docs.

Do not commit credentials, generated state databases, recovery backups, build
artifacts, or private repository fixtures.
