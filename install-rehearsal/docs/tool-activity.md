# Tool activity

No code authorship attributed to Toolbelt or Conductor.

| Actor | Operation | Evidence |
|---|---|---|
| toolbelt | scan | `toolbelt scan --path . --json` |
| toolbelt | discover | `toolbelt discover --path . --json` |
| conductor | status | `conductor status --last --pretty` |
| verification | test | `PYTHONPATH=src ../codex-conductor/.venv/bin/python -m pytest tests/test_activity.py -q` |
| codex | author | `git diff -- install-rehearsal` |
| verification | test | `PYTHONPATH=src ../codex-conductor/.venv/bin/python -m install_rehearsal --store /tmp/install-rehearsal-agent-tooling-manual run -- ../codex-conductor/.venv/bin/python tests/fixtures/profile_installer.py` |
| codex | debug | `PYTHONPATH=src ../codex-conductor/.venv/bin/python -m pytest tests/test_cli.py -q` |
| verification | test | `PYTHONPATH=src ../codex-conductor/.venv/bin/python -m install_rehearsal --store /tmp/install-rehearsal-agent-tooling-manual-2 run -- ../codex-conductor/.venv/bin/python tests/fixtures/profile_installer.py` |
| toolbelt | scan | `toolbelt scan --path . --json` |
| toolbelt | discover | `toolbelt discover --path . --json` |
| toolbelt | doctor | `toolbelt doctor --strict --path . --json` |
| toolbelt | adopt | `toolbelt adopt ruff --path . --yes --json` |
| toolbelt | adopt | `toolbelt adopt ruff --path . --yes --json` |
| toolbelt | adopt | `toolbelt adopt ruff --path . --allow-user-scope --yes --json` |
| toolbelt | verify | `env PATH=/home/neil/VSproj/agent-tooling/install-rehearsal/.venv/bin:/home/neil/miniconda3/bin:/usr/bin:/bin /home/neil/miniconda3/bin/toolbelt verify --path . --tool ruff --allow-user-scope --json` |
| toolbelt | doctor | `toolbelt doctor --strict --path . --json` |
| conductor | review_gate | `conductor status --last --pretty` |
| codex | remediate-review | `git diff -- install-rehearsal` |
| verification | quality-gate | `make check PYTHON=.venv/bin/python` |
| verification | release-contract | `codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q` |
| verification | build | `.venv/bin/python -m build --no-isolation` |
| verification | clean-install-smoke | `/tmp/install-rehearsal-wheel-verify-20260714-1905/bin/install-rehearsal --store /tmp/install-rehearsal-wheel-store-20260714-1905 run -- /tmp/install-rehearsal-wheel-verify-20260714-1905/bin/python tests/fixtures/profile_installer.py` |
| conductor | review_gate | `conductor status --last --pretty` |
| codex | remediate-review | `git diff -- install-rehearsal` |
| conductor | review_gate | `conductor status --last --pretty` |
| toolbelt | doctor | `toolbelt doctor --strict --path . --json` |
| toolbelt | verify | `env PATH=/home/neil/VSproj/agent-tooling/install-rehearsal/.venv/bin:/home/neil/miniconda3/bin:/usr/bin:/bin /home/neil/miniconda3/bin/toolbelt verify --path . --tool ruff --allow-user-scope --json` |
| verification | release-gate | `uv lock --check && make check PYTHON=.venv/bin/python && make build PYTHON=.venv/bin/python` |
| verification | clean-install-smoke | `/tmp/install-rehearsal-release-py311-20260714/bin/install-rehearsal --store /tmp/install-rehearsal-release-store-20260714 run -- /tmp/install-rehearsal-release-py311-20260714/bin/python tests/fixtures/profile_installer.py` |
