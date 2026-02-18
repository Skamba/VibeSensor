Agent operating rules
- Default PR mode:
  - After opening/updating a PR, check all status checks and review feedback.
  - Fix blocking issues immediately, push updates, and keep monitoring until required checks are green.

- How to explore the repo efficiently:
  - Start at `pi/` for backend entry points and `ui/` for frontend. Follow imports from `pi/vibesensor/__init__.py` and `pi/vibesensor/app.py`.
  - Use `pi/tests/` to see expected behaviour and fixtures; tests are the fastest way to understand runtime contracts.
  - Search `.github/workflows/ci.yml` and `pi/pyproject.toml` for build, lint and test commands.

- How to make changes:
  - Make small commits with focused intent. Prefer a single logical change per commit.
  - Do not perform large, sweeping refactors in a single PR.
  - Update or add tests in `pi/tests/` covering new behaviour.

- How to validate changes without running code:
  - Use static checks: run `ruff` locally and inspect `pyproject.toml` for dependency changes.
  - Read `pi/tests/` to confirm expected I/O and error cases; add/adjust assertions as necessary.

- How to validate changes with the Docker container (preferred for end-to-end verification):
  - Always rebuild and deploy via Docker after backend or UI changes: `docker compose build --pull && docker compose up -d`.
  - Normal test suite (default): run one simulator end-to-end smoke pass (`tools/simulator/sim_sender.py` and `tools/simulator/ws_smoke.py`).
  - Extended unit-heavy suite is on request only: `python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" pi/tests`.
  - Confirm the container is running: `docker compose ps`.
  - Send test data with the simulator: `python3 tools/simulator/sim_sender.py --count 5 --duration 10 --no-interactive`.
  - Open the web UI (default `http://127.0.0.1:8000`) and verify live data flows correctly.
  - After the simulator stops, confirm the UI stops showing new vibration events and animations (no stale-data artifacts).
  - Check container logs with `docker compose logs --tail 50` if anything looks wrong.

- Vibration Strength — Canonical Metric:
  - The only allowed "how strong is the vibration" metric is `vibration_strength_db` (dB).
  - Formula: `20 * log10((peak_band_rms_amp_g + eps) / (floor_amp_g + eps))`. Implemented in `pi/vibesensor/analysis/vibration_strength.py`. Never re-implement this formula elsewhere.
  - Severity classification: call `bucket_for_strength(vibration_strength_db)` from `strength_bands.py`. Never compare raw dB values against band thresholds inline.
  - Raw g-values (`vib_mag_rms_g`, `strength_peak_band_rms_amp_g`, etc.) must not be used as a proxy for vibration severity.
  - JSONL field: `vibration_strength_db`. Live event field: `vibration_strength_db`. See `docs/metrics.md` for the full reference.

- Misc rules:
  - Never add secrets to the repository. Use `pi/wifi-secrets.example.env` as a template for device configuration.
  - When altering report text, update `pi/vibesensor/report_i18n.py`.
