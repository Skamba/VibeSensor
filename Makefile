.DEFAULT_GOAL := help
.PHONY: help doctor setup dev format lint typecheck-backend typecheck ui-lint ui-typecheck test test-changed test-ci-lite test-all test-full-suite sync-contracts regen-contracts coverage smoke loc docs-lint

LINT_TARGETS := apps/server/vibesensor apps/server/tests tools
CI_LITE_JOBS := --job backend-quality --job backend-typecheck --job frontend-typecheck --job ui-smoke --job release-smoke --job firmware-native-tests --job backend-tests-1 --job backend-tests-2 --job backend-tests-3 --job backend-tests-4 --job backend-tests-5

help: ## Show the available make targets and what each one does
	@awk 'BEGIN {FS = ":.*## "; printf "Available targets:\n"} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

doctor: ## Check pinned tool versions and local workflow availability
	python3 tools/dev/check_prerequisites.py

setup: ## Install backend dev dependencies and UI node_modules
	python3 -m pip install --upgrade pip
	python3 -m pip install -e "./apps/server[dev]"
	cd apps/ui && npm ci
	git config --local core.hooksPath .githooks

dev: ## Start the source-mounted Docker dev stack with backend reload + Vite HMR
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

format: ## Run Ruff formatter over backend and tooling files
	ruff format $(LINT_TARGETS)

lint: ## Run repo hygiene, static guards, docs lint, and contract drift checks
	ruff check $(LINT_TARGETS)
	ruff format --check $(LINT_TARGETS)
	python3 tools/dev/check_hygiene.py
	cd apps/server && python3 ../../tools/dev/verify_backend_static_guards.py
	vibesensor-config-preflight apps/server/config.dev.yaml
	vibesensor-config-preflight apps/server/config.docker.yaml
	vibesensor-config-preflight apps/server/config.pi.yaml
	python3 tools/dev/docs_lint.py
	python3 -m vibesensor.cli.ws_schema_export --check
	python3 -m vibesensor.cli.http_api_schema_export --check

typecheck-backend: ## Run backend mypy checks
	PYTHON=$(CURDIR)/.venv/bin/python; \
	if [ ! -x "$$PYTHON" ]; then PYTHON=python3; fi; \
	cd apps/server && "$$PYTHON" -m mypy --config-file pyproject.toml

typecheck: ## Run backend and UI type checks
typecheck: typecheck-backend ui-typecheck

test: ## Run the fast backend pytest suite
	python3 -m pytest -q apps/server/tests

test-changed: ## Run heuristic checks for files changed vs origin/main
	python3 tools/tests/run_changed.py $(if $(BASE_REF),--base-ref $(BASE_REF),)

test-ci-lite: ## Run the non-Docker blocking CI subset locally
	python3 tools/tests/run_ci_parallel.py $(CI_LITE_JOBS)

test-all: ## Run the broader local CI runner, including Docker jobs when available
	python3 tools/tests/run_ci_parallel.py

test-full-suite: ## Run the full Docker-backed end-to-end suite locally
	python3 tools/tests/run_e2e_parallel.py --shards 1

sync-contracts: ## Regenerate shared frontend HTTP/WS/contracts artifacts
	cd apps/ui && npm run sync:contracts

regen-contracts: ## Sync contracts and rebuild the contract reference doc
regen-contracts: sync-contracts
	python3 tools/config/generate_contract_reference_doc.py

coverage: ## Run backend coverage with optional COV_OPTS overrides
	cd apps/server && python3 -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered $(COV_OPTS) tests

smoke: ## Run simulator and websocket smoke checks against a local server
	vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
	vibesensor-ws-smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

loc: ## Run the repo lines-of-code budget check
	python3 tools/dev/loc_check.py

docs-lint: ## Run docs lint without the broader lint suite
	python3 tools/dev/docs_lint.py

ui-lint: ## Run UI lint checks
	cd apps/ui && npm run lint

ui-typecheck: ## Run UI contract freshness, lint, and TypeScript type checking
	cd apps/ui && npm run check:contracts && npm run lint && npm run typecheck
