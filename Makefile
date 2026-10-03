.DEFAULT_GOAL := help
.PHONY: help doctor setup dev clean pristine format shell-lint lint typecheck-backend typecheck ui-lint ui-typecheck ui-test test test-diagnostic-matrix ci test-e2e test-full-suite benchmark-backend benchmark-post-analysis-30min benchmark-compare-backend sync-contracts coverage smoke

SERVER_DIR := apps/server
UI_DIR := apps/ui
LINT_TARGETS := $(SERVER_DIR)/vibesensor $(SERVER_DIR)/tests tools
PYTHON_VERSION := $(strip $(shell cat .python-version))
PYTHON_MAJOR := $(word 1,$(subst ., ,$(PYTHON_VERSION)))
PYTHON_MINOR := $(word 2,$(subst ., ,$(PYTHON_VERSION)))
PYTHON_MAJOR_MINOR := $(PYTHON_MAJOR).$(PYTHON_MINOR)
PYTHON_BOOTSTRAP := python$(PYTHON_MAJOR_MINOR)
VENV_DIR := $(CURDIR)/.venv
VENV_PYTHON := $(VENV_DIR)/bin/python
BACKEND_BENCHMARK_TARGETS ?= tests/analysis/benchmark_post_analysis_30_minute.py tests/updates/benchmark_update_status_codec.py
CLEAN_PATHS := \
	$(SERVER_DIR)/build \
	$(SERVER_DIR)/dist \
	$(SERVER_DIR)/vibesensor.egg-info \
	$(SERVER_DIR)/.mypy_cache \
	$(SERVER_DIR)/.pytest_cache \
	$(SERVER_DIR)/.ruff_cache \
	$(SERVER_DIR)/.import_linter_cache \
	$(SERVER_DIR)/vibesensor/static \
	$(UI_DIR)/dist \
	$(UI_DIR)/test-results \
	$(UI_DIR)/playwright-report \
	.pytest_cache \
	.ruff_cache \
	.mypy_cache \
	.coverage \
	htmlcov \
	infra/pi-image/pi-gen/.cache \
	tools/dev/.ruff_cache

# Prefer the repo venv after setup, but still allow bootstrap targets to run
# against the pinned host interpreter before `.venv` exists.
define RESOLVE_PYTHON
PYTHON="$(VENV_PYTHON)"; \
if [ ! -x "$$PYTHON" ]; then PYTHON="$(PYTHON_BOOTSTRAP)"; fi;
endef

define CREATE_VENV
if command -v uv >/dev/null 2>&1; then \
	uv venv --seed --python "$(PYTHON_VERSION)" "$(VENV_DIR)"; \
else \
	"$(PYTHON_BOOTSTRAP)" -m venv "$(VENV_DIR)"; \
fi
endef

help: ## Show the available make targets and what each one does
	@awk 'BEGIN {FS = ":.*## "; printf "Available targets:\n"} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

doctor: ## Check pinned tool versions and local workflow availability
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/dev/check_prerequisites.py

setup: ## Install backend dev dependencies and UI node_modules
	@if [ -x "$(VENV_PYTHON)" ] && ! "$(VENV_PYTHON)" -c "import sys; raise SystemExit(0 if sys.version.startswith('$(PYTHON_VERSION)') else 1)"; then \
		echo "Recreating .venv for Python $(PYTHON_VERSION)"; \
		rm -rf "$(VENV_DIR)"; \
	fi
	@if [ ! -x "$(VENV_PYTHON)" ]; then $(CREATE_VENV); fi
	"$(VENV_PYTHON)" -m pip install --upgrade pip
	"$(VENV_PYTHON)" -m pip install -e "./apps/server[dev]"
	cd $(UI_DIR) && node ../../tools/ui/ensure_ui_bootstrap.mjs
	git config --local core.hooksPath .githooks

dev: ## Start the source-mounted Docker dev stack with backend reload + Vite HMR
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

clean: ## Remove fast local build, test cache, static UI, and generated derivative outputs
	rm -rf $(CLEAN_PATHS)

pristine: clean ## Remove all ignored generated/cache/runtime outputs; keep local secrets
	git clean -fdX -e .secrets.act -e apps/server/wifi-secrets.env

format: ## Run Ruff formatter over backend and tooling files
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m ruff format $(LINT_TARGETS)

shell-lint: ## Run ShellCheck over deployment, hook, and Pi-image shell scripts
	@command -v shellcheck >/dev/null 2>&1 || { echo "ERROR: shellcheck is required for make shell-lint." >&2; exit 127; }
	@$(RESOLVE_PYTHON) \
	shellcheck --severity=warning -x -s bash $$("$$PYTHON" tools/dev/shellcheck_targets.py)

lint: ## Run Ruff, ShellCheck, dependency/import-layer checks, and config preflight
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m ruff check $(LINT_TARGETS) && \
	"$$PYTHON" -m ruff format --check $(LINT_TARGETS) && \
	$(MAKE) --no-print-directory shell-lint && \
	cd $(SERVER_DIR) && deptry . tests --config pyproject.toml && lint-imports --config pyproject.toml && \
	cd "$(CURDIR)" && "$$PYTHON" -m vibesensor.cli.preflight $(SERVER_DIR)/config.dev.yaml && \
	"$$PYTHON" -m vibesensor.cli.preflight $(SERVER_DIR)/config.docker.yaml && \
	"$$PYTHON" -m vibesensor.cli.preflight $(SERVER_DIR)/config.pi.yaml

typecheck-backend: ## Run backend mypy checks
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m mypy --config-file pyproject.toml

typecheck: ## Run backend and UI type checks
typecheck: typecheck-backend ui-typecheck

test: ## Run the backend pytest suite (excludes opt-in diagnostic matrices)
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m pytest -q -m "not diagnostic_matrix" apps/server/tests

test-diagnostic-matrix: ## Run opt-in broad synthetic diagnostic matrices excluded from default backend CI
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m pytest -q -m diagnostic_matrix apps/server/tests

ci: ## Run the main local CI gates: lint, type checks, backend tests, and UI unit tests
ci: lint typecheck test ui-test

E2E_WORKERS ?= 6

test-e2e: ## Run the fast process-backed e2e suite (one isolated server per xdist worker)
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m pytest -q -m "e2e and not long_sim" -n $(E2E_WORKERS) apps/server/tests_e2e

test-full-suite: ## Run the full process-backed e2e suite, including long_sim cases
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m pytest -q -m e2e -n $(E2E_WORKERS) apps/server/tests_e2e

benchmark-backend: ## Run explicit backend benchmark suite (set BENCHMARK_OPTS / BACKEND_BENCHMARK_TARGETS as needed)
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m pytest --benchmark-only -o addopts='' $(BACKEND_BENCHMARK_TARGETS) $(BENCHMARK_OPTS)

benchmark-post-analysis-30min: ## Run the opt-in 30-minute simulated-recording post-analysis benchmark
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m pytest --benchmark-only -o addopts='' tests/analysis/benchmark_post_analysis_30_minute.py $(BENCHMARK_OPTS)

benchmark-compare-backend: ## Compare saved backend benchmark runs from apps/server/.benchmarks
	@$(RESOLVE_PYTHON) \
	BENCHMARK_CLI="$$(dirname "$$PYTHON")/py.test-benchmark"; \
	cd $(SERVER_DIR) && "$$BENCHMARK_CLI" compare .benchmarks

sync-contracts: ## Regenerate committed UI contract types/constants and docs/protocol.md from backend sources
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/config/sync_contracts.py

coverage: ## Run backend coverage with optional COV_OPTS overrides
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered $(COV_OPTS) tests

smoke: ## Run simulator and websocket smoke checks against a local server
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m vibesensor.simulator.sim_sender --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server && \
	"$$PYTHON" -m vibesensor.simulator.ws_smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

ui-lint: ## Run UI lint checks
	cd $(UI_DIR) && npm run lint

ui-typecheck: ## Run UI format, lint, and TypeScript checks
	cd $(UI_DIR) && npm run format:check && npm run lint && npm run lint:unused && npm run typecheck && npm run typecheck:tests

ui-test: ## Run UI unit tests
	cd $(UI_DIR) && npm run test:unit
