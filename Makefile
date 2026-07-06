.PHONY: test install uninstall probe e2e

test:
	python3 -m unittest discover -s tests -v

install:
	python3 -m conductor.install

uninstall:
	python3 -m conductor.install --uninstall

probe:
	RUN_LIVE=1 python3 probe/probe.py

e2e:
	RUN_LIVE=1 bash tests/e2e_smoke.sh
