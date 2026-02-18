Repository overview
- VibeSensor: Python-based data-collection and analysis backend (located in `pi/`), a small web UI (`ui/`) built with Node, and device/firmware helpers under `esp/` and `hardware/`.
- Key runtime artifacts: Docker Compose stack at `docker-compose.yml` and `pi/` Python package (`pi/pyproject.toml`). PDF report generation lives in `pi/vibesensor/report_pdf.py`.

Common commands (exact as found in CI / repo files)
- Install Python deps (dev):
  - python -m pip install -e "./pi[dev]"
- Run normal test suite (default):
  - python tools/simulator/sim_sender.py --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
  - python tools/simulator/ws_smoke.py --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35
- Run extended test suite (on request only):
  - python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" pi/tests
- Lint / format checks (as used in CI):
  - ruff check pi/vibesensor pi/tests tools/simulator
  - ruff format --check pi/vibesensor pi/tests tools/simulator
- Web UI:
  - cd ui && npm ci
  - cd ui && npm run build
  - cd ui && npm run typecheck
- Docker (local dev / CI):
  - docker compose build --pull
  - docker compose up -d

Repo conventions
- Backend code: placed under `pi/vibesensor/`. Keep modules small and prefer explicit function signatures.
- Tests live under `pi/tests/` and use pytest. Selenium-marked tests are slow/optional and excluded in CI with `-m "not selenium"`.
- Strings that appear in generated reports are internationalised via `pi/vibesensor/report_i18n.py` and must be used with `tr(lang, KEY)`.

Configuration and secrets
- Config files: `pi/config.example.yaml`, `pi/config.dev.yaml`, and `pi/config.yaml` live in repo root `pi/`.
- CI installs the dev package using `python -m pip install -e "./pi[dev]"`; follow that pattern for local dev.
- Do NOT add secrets to the repo. Keep WiFi or device secrets out of `pi/config.yaml`; sample secrets live in `pi/wifi-secrets.example.env`.

How to add a feature safely
- Add code under `pi/vibesensor/` for backend changes; add small, focused tests in `pi/tests/` that are fast.
- Update or add i18n keys in `pi/vibesensor/report_i18n.py` when changing report text.
- For UI changes, modify `ui/` and update the `ui` build scripts; ensure `npm run build` succeeds.
- If the change affects Docker, update `docker-compose.yml` or `pi/Dockerfile` and test locally with `docker compose up -d`.

Guardrails for Copilot
- Keep PRs small and self-contained. Add tests for behavior changes. Prefer backwards-compatible changes unless the task explicitly requests breaking changes.
- For normal validation, run one simulator end-to-end smoke pass; run the full unit-heavy suite only when explicitly requested.
- Do not modify unrelated files or reformat the whole repo.

End-to-end validation via Docker
- After making backend or frontend changes, always rebuild and test using the Docker container:
  - `docker compose build --pull`
  - `docker compose up -d`
- Verify the running container by checking `docker compose ps` and confirming the service is healthy.
- Use the simulator (`python3 tools/simulator/sim_sender.py --count 5 --duration 10 --no-interactive`) to send test data and confirm the UI updates correctly.
- After the simulator finishes, verify the UI stops showing new detections and the car map stops animating (no stale-data artifacts).
