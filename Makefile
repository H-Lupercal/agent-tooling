.PHONY: build check distribution e2e format format-check lint release-check security test typecheck

PYTHON ?= python3

format:
	$(PYTHON) -m ruff format src tests

format-check:
	$(PYTHON) -m ruff format --check src tests

lint:
	$(PYTHON) -m ruff check src tests

typecheck:
	$(PYTHON) -m pyright

test:
	$(PYTHON) -m pytest -m "not distribution" --cov=src/toolbelt --cov-branch --cov-report=term-missing --cov-fail-under=85

distribution:
	$(PYTHON) -m pytest -m distribution -q

build:
	$(PYTHON) -m build
	$(PYTHON) -m twine check dist/*

security:
	$(PYTHON) -m pip_audit

check: format-check lint typecheck test

release-check: check build distribution security

e2e:
	tests/e2e_smoke.sh
