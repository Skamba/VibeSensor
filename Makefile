.PHONY: setup format lint typecheck-backend typecheck ui-typecheck test test-fast test-all test-ci test-full-suite sync-contracts coverage coverage-html coverage-strict smoke loc docs-lint

setup:
	python3 -m pip install --upgrade pip
	python3 -m pip install -e "./apps/server[dev]"
	cd apps/ui && npm ci

format:
	ruff format apps/server/vibesensor apps/server/tests tools/dev tools/tests tools/ci

lint:
	ruff check apps/server/vibesensor apps/server/tests tools/dev tools/tests tools/ci
	ruff format --check apps/server/vibesensor apps/server/tests tools/dev tools/tests tools/ci

typecheck-backend:
	PYTHON=$(CURDIR)/.venv/bin/python; \
	if [ ! -x "$$PYTHON" ]; then PYTHON=python3; fi; \
	cd apps/server && "$$PYTHON" -m mypy --config-file pyproject.toml

typecheck: typecheck-backend ui-typecheck

test:
	python3 -m pytest -q -m "not selenium" apps/server/tests

test-fast: test  # alias — use 'make test'

test-all:
	python3 tools/tests/run_ci_parallel.py

test-ci: test-all  # alias — use 'make test-all'

test-full-suite:
	python3 tools/tests/run_full_suite.py

sync-contracts:
	cd apps/ui && npm run sync:contracts

coverage:
	python3 tools/tests/run_coverage.py

coverage-html:
	python3 tools/tests/run_coverage.py --html

coverage-strict:
	python3 tools/tests/run_coverage.py --fail-under --min-coverage 80

smoke:
	vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
	vibesensor-ws-smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

loc:
	python3 tools/dev/loc_check.py

docs-lint:
	python3 tools/dev/docs_lint.py

ui-typecheck:
	cd apps/ui && npm run typecheck
