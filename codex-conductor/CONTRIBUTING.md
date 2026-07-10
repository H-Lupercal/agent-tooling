# Contributing

Contributions are welcome through GitHub issues and pull requests.

Clone the monorepo and enter this project with:

```sh
git clone https://github.com/H-Lupercal/agent-tooling.git
cd agent-tooling/codex-conductor
```

1. Use Python 3.11 or newer and create an isolated environment.
2. Install development dependencies with `python -m pip install -e ".[dev]"`.
3. Add tests before changing policy, state transitions, provider contracts, or
   installation behavior.
4. Run `make check PYTHON=python` and `make release-check PYTHON=python`.
5. Document breaking behavior in `CHANGELOG.md`.

Never weaken identifier validation, atomic budget/concurrency reservations,
exact lifecycle correlation, or installer ownership checks merely to make an
unsupported provider payload pass. New provider claims require a checked-in
capability contract and golden payload fixtures.
