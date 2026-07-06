.PHONY: test lint probe e2e

test:
	python3 -m unittest discover -s tests -v

lint:
	python3 -m py_compile toolbelt/*.py

probe:
	scripts/probe_cli_output.sh

e2e:
	@if [ "$$RUN_LIVE" = "1" ]; then \
		tests/e2e_smoke.sh; \
	else \
		echo "set RUN_LIVE=1 to run live e2e"; \
	fi
