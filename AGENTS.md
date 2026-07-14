# AGENTS

Repository-specific execution contract for AI coding agents working in this monorepo.
Home-level safety rules still apply.

## Scope

- `toolbelt/`, `codex-conductor/`, and `install-rehearsal/` are independent Python packages.
- Keep package code, tests, lockfiles, and documentation inside the owning project.
- Root files own monorepo CI, releases, security, support, and contribution policy.
- Do not introduce a runtime dependency between the two packages.
- Do not push, tag, publish, or modify a live user installation without explicit user
  authorization.

## Required verification

Run the root contract after repository metadata or workflow changes:

```sh
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Run project gates from the project directory:

```sh
make check PYTHON=.venv/bin/python
make distribution PYTHON=.venv/bin/python  # Toolbelt
make dist-test PYTHON=.venv/bin/python     # Conductor
make e2e PYTHON=.venv/bin/python

cd ../install-rehearsal
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```

For release work, also run locked builds, Twine, dependency audits, SBOM generation,
and the root workflow validation. Preserve unrelated work and stage files explicitly.

At the end of a run, execute:

```sh
PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last
```

If no store or completed run exists, report that controlled state instead of inventing
a cost table.
