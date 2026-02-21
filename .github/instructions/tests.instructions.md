---
applyTo: "apps/server/tests/**"
---
Tests
- Default CI-aligned test suite: `make test-all` (runs `python3 tools/tests/run_full_suite.py`).
- Optional focused backend pytest run (for faster iteration, not a CI substitute): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests`.
- Selenium UI tests are present but skipped in CI; mark them explicitly with the `selenium` marker.
- New backend features should include focused unit tests under `apps/server/tests/`; in fail-fast lab mode, larger/breaking changes can include broader integration coverage when useful.
- Backward compatibility is never a requirement in fail-fast lab mode; validate intended behavior with updated tests.
- End-to-end testing: after code changes, always rebuild and test via Docker (`docker compose build --pull && docker compose up -d`), then use the simulator (`vibesensor-sim --count 5 --duration 10 --no-interactive`) to verify the full stack works correctly.
