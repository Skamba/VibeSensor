.PHONY: setup format lint test smoke loc ai-check ai-test ai-smoke ai-pack ai\:check ai\:test ai\:smoke ai\:pack

setup:
	python3 -m pip install -e "./apps/server[dev]"
	cd apps/ui && npm ci

format:
	ruff format apps/server/vibesensor apps/server/tests apps/simulator

lint:
	ruff check apps/server/vibesensor apps/server/tests apps/simulator
	ruff format --check apps/server/vibesensor apps/server/tests apps/simulator

test:
	python3 tools/sync_ui_to_pi_public.py --skip-npm-ci
	python3 -m pytest -q -m "not selenium" apps/server/tests

smoke:
	set -eu; \
	python3 -m vibesensor.app --config apps/server/config.dev.yaml >server.log 2>&1 & \
	SERVER_PID=$$!; \
	trap 'kill "$$SERVER_PID" >/dev/null 2>&1 || true' EXIT; \
	for i in $$(seq 1 30); do \
	  if curl -sf http://127.0.0.1:8000/ >/dev/null; then break; fi; \
	  sleep 1; \
	done; \
	python3 apps/simulator/sim_sender.py --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server >sim.log 2>&1 & \
	SIM_PID=$$!; \
	python3 apps/simulator/ws_smoke.py --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35; \
	wait $$SIM_PID

loc:
	python3 tools/dev/loc_check.py

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
