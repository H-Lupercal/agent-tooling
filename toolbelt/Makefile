.PHONY: build check distribution e2e format format-check lint release-check sbom security test typecheck

PYTHON ?= python3
UV ?= uv

format:
	$(PYTHON) -m ruff format src tests scripts

format-check:
	$(PYTHON) -m ruff format --check src tests scripts

lint:
	$(PYTHON) -m ruff check src tests scripts

typecheck:
	$(PYTHON) -m pyright

test:
	$(PYTHON) -m pytest -m "not distribution" --cov=src/toolbelt --cov-branch --cov-report=term-missing --cov-fail-under=90

distribution:
	$(PYTHON) -m pytest -m distribution -q

build:
	$(PYTHON) -m build --no-isolation
	$(PYTHON) -m twine check dist/*.whl dist/*.tar.gz

security:
	$(PYTHON) -m pip_audit

sbom: build
	$(UV) venv --clear --python $(PYTHON) build/sbom-venv
	$(UV) pip install --offline --link-mode=copy --python build/sbom-venv dist/*.whl
	$(PYTHON) -m cyclonedx_py environment build/sbom-venv --pyproject pyproject.toml --mc-type library --output-reproducible --of JSON --output-file dist/toolbelt-ai.cdx.json
	$(UV) run --offline --no-project --python build/sbom-venv python scripts/finalize_sbom.py --input dist/toolbelt-ai.cdx.json --distribution toolbelt-ai

check: format-check lint typecheck test

release-check: check build distribution e2e security sbom

e2e:
	PYTHON=$(PYTHON) bash tests/e2e_smoke.sh
