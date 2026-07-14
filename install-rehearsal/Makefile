.PHONY: build check format format-check lint test typecheck

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
	$(PYTHON) -m pytest --cov=install_rehearsal --cov-branch --cov-report=term-missing --cov-fail-under=90

check: format-check lint typecheck test

build:
	$(PYTHON) -m build --no-isolation
