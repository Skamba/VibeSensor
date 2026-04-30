.DEFAULT_GOAL := help
.PHONY: help doctor setup dev clean format shell-lint lint typecheck-backend typecheck ui-lint ui-typecheck ui-test test test-changed test-ci-lite test-all test-full-suite benchmark-backend benchmark-compare-backend sync-contracts coverage smoke loc docs-lint

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
BACKEND_BENCHMARK_TARGETS ?= tests/infra/workers/benchmark_compute_all.py tests/use_cases/diagnostics/benchmark_whole_run_spectra.py tests/use_cases/updates/benchmark_update_status_codec.py

# Prefer the repo venv after setup, but still allow bootstrap targets to run
# against the pinned host interpreter before `.venv` exists.
define RESOLVE_PYTHON
PYTHON="$(VENV_PYTHON)"; \
if [ ! -x "$$PYTHON" ]; then PYTHON="$(PYTHON_BOOTSTRAP)"; fi;
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
	@if [ ! -x "$(VENV_PYTHON)" ]; then "$(PYTHON_BOOTSTRAP)" -m venv "$(VENV_DIR)"; fi
	"$(VENV_PYTHON)" -m pip install --upgrade pip
	"$(VENV_PYTHON)" -m pip install -e "./apps/server[dev]"
	cd $(UI_DIR) && npm ci
	git config --local core.hooksPath .githooks

dev: ## Start the source-mounted Docker dev stack with backend reload + Vite HMR
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

clean: ## Remove local build, package, and Pi image cache artifacts
	rm -rf $(SERVER_DIR)/build $(SERVER_DIR)/dist $(SERVER_DIR)/vibesensor.egg-info infra/pi-image/pi-gen/.cache

format: ## Run Ruff formatter over backend and tooling files
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m ruff format $(LINT_TARGETS)

shell-lint: ## Run ShellCheck over deployment, hook, and Pi-image shell scripts
	@command -v shellcheck >/dev/null 2>&1 || { echo "ERROR: shellcheck is required for make shell-lint." >&2; exit 127; }
	@$(RESOLVE_PYTHON) \
	shellcheck --severity=warning -x -s bash $$("$$PYTHON" tools/dev/shellcheck_targets.py)

lint: ## Run repo hygiene, dependency/static guards, docs lint, and contract drift checks
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m ruff check $(LINT_TARGETS) && \
	"$$PYTHON" -m ruff format --check $(LINT_TARGETS) && \
	"$$PYTHON" tools/dev/check_hygiene.py && \
	$(MAKE) --no-print-directory shell-lint && \
	cd $(SERVER_DIR) && deptry . tests --config pyproject.toml && lint-imports --config pyproject.toml && "$$PYTHON" ../../tools/dev/verify_backend_static_guards.py && \
	cd "$(CURDIR)" && "$$PYTHON" -m vibesensor.cli.preflight $(SERVER_DIR)/config.dev.yaml && \
	"$$PYTHON" -m vibesensor.cli.preflight $(SERVER_DIR)/config.docker.yaml && \
	"$$PYTHON" -m vibesensor.cli.preflight $(SERVER_DIR)/config.pi.yaml && \
	"$$PYTHON" tools/dev/docs_lint.py && \
	cd $(UI_DIR) && PYTHON="$$PYTHON" npm run sync:contracts -- --check

typecheck-backend: ## Run backend mypy checks
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m mypy --config-file pyproject.toml

typecheck: ## Run backend and UI type checks
typecheck: typecheck-backend ui-typecheck

test: ## Run the fast backend pytest suite
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m pytest -q apps/server/tests

test-changed: ## Run heuristic checks for files changed vs origin/main
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/tests/run_changed.py $(if $(BASE_REF),--base-ref $(BASE_REF),)

test-ci-lite: ## Run the non-Docker blocking CI subset locally
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/tests/run_ci_parallel.py --ci-lite

test-all: ## Run the broader local CI runner
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/tests/run_ci_parallel.py

test-full-suite: ## Run the full end-to-end suite locally
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/tests/run_e2e_parallel.py --shards 1

benchmark-backend: ## Run explicit backend benchmark suite (set BENCHMARK_OPTS / BACKEND_BENCHMARK_TARGETS as needed)
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m pytest --benchmark-only $(BACKEND_BENCHMARK_TARGETS) $(BENCHMARK_OPTS)

benchmark-compare-backend: ## Compare saved backend benchmark runs from apps/server/.benchmarks
	@$(RESOLVE_PYTHON) \
	BENCHMARK_CLI="$$(dirname "$$PYTHON")/py.test-benchmark"; \
	cd $(SERVER_DIR) && "$$BENCHMARK_CLI" compare .benchmarks

sync-contracts: ## Regenerate or check the authoritative contract sync pipeline
	@$(RESOLVE_PYTHON) \
	cd $(UI_DIR) && PYTHON="$$PYTHON" npm run sync:contracts $(if $(CHECK),-- --check,)

coverage: ## Run backend coverage with optional COV_OPTS overrides
	@$(RESOLVE_PYTHON) \
	cd $(SERVER_DIR) && "$$PYTHON" -m pytest -q --cov=vibesensor --cov-report=term-missing:skip-covered $(COV_OPTS) tests

smoke: ## Run simulator and websocket smoke checks against a local server
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" -m vibesensor.adapters.simulator.sim_sender --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server && \
	"$$PYTHON" -m vibesensor.adapters.simulator.ws_smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

loc: ## Run the repo lines-of-code budget check
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/dev/loc_check.py

docs-lint: ## Run docs lint without the broader lint suite
	@$(RESOLVE_PYTHON) \
	"$$PYTHON" tools/dev/docs_lint.py

ui-lint: ## Run UI lint checks
	cd $(UI_DIR) && npm run lint

ui-typecheck: ## Materialize UI-derived contracts, then run lint and TypeScript type checking
	@$(RESOLVE_PYTHON) \
	cd $(UI_DIR) && PYTHON="$$PYTHON" npm run sync:generated-contracts && npm run lint && npm run lint:deps && npm run lint:unused && PYTHON="$$PYTHON" npm run typecheck && npm run typecheck:tests

ui-test: ## Run UI unit tests
	@$(RESOLVE_PYTHON) \
	cd $(UI_DIR) && PYTHON="$$PYTHON" npm run test:unit
