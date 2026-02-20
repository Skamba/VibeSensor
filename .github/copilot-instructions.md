Repository overview
- VibeSensor: Python-based data-collection and analysis backend (located in `apps/server/`), a small web UI (`apps/ui/`) built with Node, and device/firmware helpers under `firmware/esp/` and `hardware/`.
- Key runtime artifacts: Docker Compose stack at `docker-compose.yml` and `apps/server/` Python package (`apps/server/pyproject.toml`). PDF report generation lives in `apps/server/vibesensor/report_pdf.py`.

Common commands (exact as found in CI / repo files)
- Install Python deps (dev):
  - python -m pip install -e "./apps/server[dev]"
- Run normal test suite (default):
  - vibesensor-sim --count 3 --duration 20 --server-host 127.0.0.1 --no-auto-server
  - vibesensor-ws-smoke --uri ws://127.0.0.1:8000/ws --min-clients 3 --timeout 35
- Run extended test suite (on request only):
  - python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests
- Lint / format checks (as used in CI):
  - ruff check apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python libs/adapters/python
  - ruff format --check apps/server/vibesensor apps/server/tests apps/simulator libs/core/python libs/shared/python libs/adapters/python
- Web UI:
  - cd apps/ui && npm ci
  - cd apps/ui && npm run build
  - cd apps/ui && npm run typecheck
- Docker (local dev / CI):
  - docker compose build --pull
  - docker compose up -d

Repo conventions
- Backend code: placed under `apps/server/vibesensor/`. Keep modules small and prefer explicit function signatures.
- Tests live under `apps/server/tests/` and use pytest. Selenium-marked tests are slow/optional and excluded in CI with `-m "not selenium"`.
- Strings that appear in generated reports are internationalised via `apps/server/data/report_i18n.json` and loaded by `apps/server/vibesensor/report_i18n.py`.

Configuration and secrets
- Config files: `apps/server/config.example.yaml`, `apps/server/config.dev.yaml`, and `apps/server/config.yaml` live under `apps/server/`.
- CI installs the dev package using `python -m pip install -e "./apps/server[dev]"`; follow that pattern for local dev.
- Do NOT add secrets to the repo. Keep WiFi or device secrets out of `apps/server/config.yaml`; sample secrets live in `apps/server/wifi-secrets.example.env`.

How to add a feature safely
- Add code under `apps/server/vibesensor/` for backend changes; add small, focused tests in `apps/server/tests/` that are fast.
- Update or add i18n keys in `apps/server/data/report_i18n.json` when changing report text.
- For UI changes, modify `apps/ui/` and update the `apps/ui` build scripts; ensure `npm run build` succeeds.
- If the change affects Docker, update `docker-compose.yml` or `apps/server/Dockerfile` and test locally with `docker compose up -d`.

Guardrails for Copilot
- Keep PRs small and self-contained. Add tests for behavior changes. Prefer backwards-compatible changes unless the task explicitly requests breaking changes.
- For normal validation, run one simulator end-to-end smoke pass; run the full unit-heavy suite only when explicitly requested.
- Do not modify unrelated files or reformat the whole repo.
- Default PR mode: check PR status checks and review feedback, fix all blocking issues, push updates, and continue monitoring until required checks are fully green.

End-to-end validation via Docker
- After making backend or frontend changes, always rebuild and test using the Docker container:
  - `docker compose build --pull`
  - `docker compose up -d`
- Verify the running container by checking `docker compose ps` and confirming the service is healthy.
- Use the simulator (`vibesensor-sim --count 5 --duration 10 --no-interactive`) to send test data and confirm the UI updates correctly.
- After the simulator finishes, verify the UI stops showing new detections and the car map stops animating (no stale-data artifacts).
