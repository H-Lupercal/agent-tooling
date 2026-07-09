.PHONY: build check e2e format-check lint probe test typecheck

PYTHON ?= python

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .

typecheck:
	$(PYTHON) -m pyright

build:
	$(PYTHON) -m build

check: format-check lint typecheck test

probe:
	scripts/probe_cli_output.sh

e2e:
	@if [ "$$RUN_LIVE" = "1" ]; then \
		tests/e2e_smoke.sh; \
	else \
		echo "set RUN_LIVE=1 to run live e2e"; \
	fi
