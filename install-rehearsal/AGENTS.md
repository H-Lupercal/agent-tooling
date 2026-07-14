# Install Rehearsal executor notes

This directory is an independent Python package. Runtime code must remain standard-library
only and must preserve the explicit `REHEARSAL_NOT_SANDBOXED` trust label.

Run before completion:

```sh
uv sync --extra dev --locked
make check PYTHON=.venv/bin/python
make build PYTHON=.venv/bin/python
```

Tests that change behavior must demonstrate a failing state before the implementation.
Never turn the redirected profile into a claimed security sandbox.

