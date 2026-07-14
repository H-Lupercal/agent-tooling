# Agent Harness executor notes

This directory is an independent Python package. Foundation runtime code must remain
standard-library only. Provider credentials and hidden model reasoning must never enter
fixtures, events, logs, receipts, or commits.

Every behavior change follows test-driven development: write the test, run it and observe
the expected failure, implement the minimum behavior, and rerun the focused and package
tests.

Run before completion:

```sh
uv lock --check
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```
