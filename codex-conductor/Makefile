.PHONY: audit build check clean dist-test e2e format format-check install lint probe release-check sbom test typecheck uninstall

PYTHON ?= python3
UV ?= uv

test:
	$(PYTHON) -m pytest -m "not distribution" --cov=conductor --cov-branch --cov-report=term-missing --cov-fail-under=90

dist-test:
	$(PYTHON) -m pytest -m distribution -q

format-check:
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff format .

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m pyright

check: format-check lint typecheck test

build:
	$(PYTHON) -m build --no-isolation

release-check: check build sbom
	$(PYTHON) -m twine check dist/*.whl dist/*.tar.gz
	$(PYTHON) -m pytest -m distribution -q
	PYTHON=$(PYTHON) bash tests/e2e_smoke.sh
	$(PYTHON) -m pip_audit

audit:
	$(PYTHON) -m pip_audit

sbom: build
	$(UV) venv --clear --python $(PYTHON) build/sbom-venv
	$(UV) pip install --offline --link-mode=copy --python build/sbom-venv dist/*.whl
	$(PYTHON) -m cyclonedx_py environment build/sbom-venv --pyproject pyproject.toml --mc-type library --output-reproducible --of JSON --output-file dist/codex-conductor.cdx.json
	$(UV) run --offline --no-project --python build/sbom-venv python scripts/finalize_sbom.py --input dist/codex-conductor.cdx.json --distribution codex-conductor

clean:
	$(PYTHON) -c "import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('build', 'dist')]"

install:
	$(PYTHON) -m conductor.install

uninstall:
	$(PYTHON) -m conductor.install --uninstall

probe:
	$(PYTHON) probe/probe.py

e2e:
	PYTHON=$(PYTHON) bash tests/e2e_smoke.sh
