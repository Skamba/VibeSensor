---
applyTo: "**"
---
Validation (always required)
- After any backend or frontend change, rebuild and test via the Docker container before considering the work done:
  1. `docker compose build --pull`
  2. `docker compose up -d`
  3. Verify the container is running: `docker compose ps`
  4. Send test data with the simulator: `python3 tools/simulator/sim_sender.py --count 5 --duration 10 --no-interactive`
  5. Confirm the web UI (`http://127.0.0.1:8000`) displays live data correctly while the simulator runs.
  6. After the simulator stops, verify the UI stops showing new vibration events and the car map stops animating (no stale-data artifacts).
  7. Check container logs (`docker compose logs --tail 50`) if anything looks wrong.
- Normal test suite (default): run one simulator end-to-end smoke pass (use `tools/simulator/sim_sender.py` and `tools/simulator/ws_smoke.py`).
- Extended test suite (on request only): `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" pi/tests`.
- Run lint (`ruff check`) before pushing changes.
- Never skip Docker validation even if unit tests pass — integration issues often only surface at runtime.
