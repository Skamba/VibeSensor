.PHONY: setup format lint typecheck-backend typecheck ui-typecheck test test-all test-full-suite sync-contracts regen-contracts coverage smoke loc docs-lint

setup:
	python3 -m pip install --upgrade pip
	python3 -m pip install -e "./apps/server[dev]"
	cd apps/ui && npm ci

format:
	ruff format apps/server/vibesensor apps/server/tests tools/dev tools/tests tools

lint:
	ruff check apps/server/vibesensor apps/server/tests tools/dev tools/tests tools
	ruff format --check apps/server/vibesensor apps/server/tests tools/dev tools/tests tools
	python3 tools/dev/check_hygiene.py
	vibesensor-config-preflight apps/server/config.dev.yaml
	vibesensor-config-preflight apps/server/config.docker.yaml
	vibesensor-config-preflight apps/server/config.pi.yaml
	python3 tools/dev/docs_lint.py
	python3 -m vibesensor.ws_schema_export --check
	python3 -m vibesensor.http_api_schema_export --check

typecheck-backend:
	PYTHON=$(CURDIR)/.venv/bin/python; \
	if [ ! -x "$$PYTHON" ]; then PYTHON=python3; fi; \
	cd apps/server && "$$PYTHON" -m mypy --config-file pyproject.toml

typecheck: typecheck-backend ui-typecheck

test:
	python3 -m pytest -q apps/server/tests

test-all:
	python3 tools/tests/run_ci_parallel.py

test-full-suite:
	python3 tools/tests/run_e2e_parallel.py --shards 1

sync-contracts:
	cd apps/ui && npm run sync:contracts

regen-contracts: sync-contracts
	python3 tools/config/generate_contract_reference_doc.py

coverage:  ## COV_OPTS="--cov-report=html:../../artifacts/coverage/html" or "--cov-fail-under=80"
	cd apps/server && python3 -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered $(COV_OPTS) tests

smoke:
	vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
	vibesensor-ws-smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

loc:
	python3 tools/dev/loc_check.py

docs-lint:
	python3 tools/dev/docs_lint.py

ui-typecheck:
	cd apps/ui && npm run check:contracts && npm run typecheck
