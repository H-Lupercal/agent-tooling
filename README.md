# Agent Tooling

Agent Tooling is a Python monorepo containing three independently versioned command-line
tools for professional AI-assisted development.

| Project | Package | Purpose |
| --- | --- | --- |
| [Toolbelt](toolbelt/) | `toolbelt-ai` | Deterministically discovers, plans, installs, and reconciles AI-development tools. |
| [Codex Conductor](codex-conductor/) | `codex-conductor` | Enforces cost-aware subagent admission, routing, lifecycle accounting, and installation policy for Codex and Claude Code. |
| [Install Rehearsal](install-rehearsal/) | `install-rehearsal` | Observes trusted installer effects in a disposable redirected user profile. |

All projects require Python 3.11 or newer, ship typed wheels, use locked development
environments, and include detailed documentation.

## Install

```sh
pipx install toolbelt-ai
python -m pip install codex-conductor
python -m pip install ./install-rehearsal
```

Package-specific setup and trust-boundary guidance is in each project README:

- [Toolbelt quick start](toolbelt/README.md)
- [Codex Conductor quick start](codex-conductor/README.md)
- [Install Rehearsal quick start](install-rehearsal/README.md)

## Develop

Use [uv](https://docs.astral.sh/uv/) and run commands inside the project being changed.

```sh
git clone https://github.com/H-Lupercal/agent-tooling.git
cd agent-tooling

cd toolbelt
uv sync --extra dev --locked
make check PYTHON=.venv/bin/python
make distribution PYTHON=.venv/bin/python

cd ../codex-conductor
uv sync --extra dev --locked
make check PYTHON=.venv/bin/python
make dist-test PYTHON=.venv/bin/python
make e2e PYTHON=.venv/bin/python

cd ../install-rehearsal
uv sync --extra dev --locked
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```

The root release-contract test validates monorepo metadata and automation:

```sh
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

## Releases

The currently published packages release independently through protected GitHub environments and PyPI
Trusted Publishing:

- Toolbelt tags: `toolbelt-vX.Y.Z`
- Codex Conductor tags: `codex-conductor-vX.Y.Z`

A tag must match the corresponding package version. Release workflows rebuild and test
the package, audit dependencies, create wheel and sdist artifacts, generate checksums
and a CycloneDX SBOM, attest provenance, publish to PyPI, and create a GitHub release.
See [Toolbelt releasing](toolbelt/RELEASING.md) and
[Conductor releasing](codex-conductor/docs/RELEASING.md).

## Project policy

- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)
- [Support](SUPPORT.md)
- [Code of Conduct](CODE_OF_CONDUCT.md)
- [MIT license](LICENSE); package copies: [Toolbelt](toolbelt/LICENSE) and
  [Codex Conductor](codex-conductor/LICENSE)
