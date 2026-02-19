.PHONY: setup format lint test test-all smoke loc docs-lint ai-check ai-test ai-smoke ai-pack ai\:check ai\:test ai\:smoke ai\:pack

setup:
	python3 -m pip install -e "./apps/server[dev]"
	cd apps/ui && npm ci

format:
	ruff format apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python libs/adapters/python

lint:
	ruff check apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python libs/adapters/python
	ruff format --check apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python libs/adapters/python

test:
	python3 -m pytest -q -m "not selenium" apps/server/tests

test-all:
	python3 tools/tests/run_full_suite.py

smoke:
	python3 apps/simulator/sim_sender.py --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
	python3 apps/simulator/ws_smoke.py --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35

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
