---
applyTo: "apps/server/tests/**"
---
Tests
- Normal tests (default CI/LLM): one simulator E2E smoke run using `apps/simulator/sim_sender.py` + `apps/simulator/ws_smoke.py`.
- Extended tests (on request only): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.
- New backend features should include focused unit tests under `apps/server/tests/` and avoid heavy integration tests in quick PRs.
- End-to-end testing: after code changes, always rebuild and test via Docker (`docker compose build --pull && docker compose up -d`), then use the simulator (`vibesensor-sim --count 5 --duration 10 --no-interactive`) to verify the full stack works correctly.
