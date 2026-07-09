.PHONY: build check e2e format-check install lint probe test typecheck uninstall

test:
	python3 -m pytest

format-check:
	python3 -m ruff format --check .

lint:
	python3 -m ruff check .

typecheck:
	pyright

check: format-check lint typecheck test

build:
	python3 -m build

install:
	python3 -m conductor.install

uninstall:
	python3 -m conductor.install --uninstall

probe:
	RUN_LIVE=1 python3 probe/probe.py

e2e:
	RUN_LIVE=1 bash tests/e2e_smoke.sh
