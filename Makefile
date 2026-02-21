.PHONY: setup format lint test test-fast test-all smoke loc docs-lint ai-check ai-test ai-smoke ai-pack ai\:check ai\:test ai\:smoke ai\:pack

setup:
	python3 -m pip install -e "./apps/server[dev]"
	cd apps/ui && npm ci

format:
	ruff format apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python

lint:
	ruff check apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python
	ruff format --check apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python

test:
	python3 -m pytest -q -m "not selenium" apps/server/tests

test-fast:
	python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests

test-all:
	python3 tools/tests/run_full_suite.py

smoke:
	vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
	vibesensor-ws-smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

loc:
	python3 tools/dev/loc_check.py

docs-lint:
	python3 tools/dev/docs_lint.py

ai-check:
	@scripts/ai/task ai:check

ai-test:
	@scripts/ai/task ai:test

ai-smoke:
	@scripts/ai/task ai:smoke

ai-pack:
	@scripts/ai/task ai:pack

ai\:check: ai-check
ai\:test: ai-test
ai\:smoke: ai-smoke
ai\:pack: ai-pack
