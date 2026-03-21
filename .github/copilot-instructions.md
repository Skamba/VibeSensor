Repository overview (scope: high-level orientation and behavioral rules; see `docs/ai/repo-map.md` for detailed layout, entry points, and file ownership)
- VibeSensor: Python backend (`apps/server/`), TypeScript/Vite dashboard (`apps/ui/`), ESP32 firmware (`firmware/esp/`), Pi image build (`infra/pi-image/`).
- Key runtime artifacts: `docker-compose.yml` (local stack), `apps/server/pyproject.toml` (backend packaging and CLI entry points).
- Units policy: raw ingest/sample acceleration values may use g, but post-stop analysis outputs (persisted summaries, findings, report-template artifacts) must expose vibration strength or intensity in dB only.
- Canonical dB definition: `vibesensor/vibration_strength.py::vibration_strength_db_scalar()` (`20*log10((peak+eps)/(floor+eps))`, `eps=max(1e-9, floor*0.05)`).

Source-of-truth note
- This file is the short AI guide.
- AI guidance lives in this file, `.github/instructions/*.instructions.md`, and `docs/ai/repo-map.md`. Do not create additional guidance files in `docs/ai/`.

Instruction sources
- Read `docs/ai/repo-map.md` first.
- Shared workflow, validation, and execution guardrails live in `.github/instructions/general.instructions.md` — do not duplicate them here.
- Area-specific deltas live in `.github/instructions/{backend,frontend,tests}.instructions.md`.

Architectural constraints
- Offline-first hotspot boot: hotspot provisioning must not depend on internet connectivity. Required packages are baked into the image build stage.
- Deterministic image outputs: custom pi-gen stage must export uniquely suffixed artifacts and self-validate rootfs contents.
- Internal shared logic belongs in the server package (`vibesensor/vibration_strength.py`, `vibesensor/strength_bands.py`), not in separate packages. Shared TS constants live directly in `apps/ui/src/constants.ts`.
- Do not create runtime file-loading mechanisms for static configuration data. Use Python constants for values that don't change between deployments.

Domain model (scope: behavioral rules only; see `docs/domain-model.md` for the full domain object catalog and relationship map)
- Domain objects own behavior (classification, ranking, lifecycle, computation). Adapters at persistence/transport/rendering boundaries bridge to/from domain objects but do not duplicate domain logic.
- Consumers import from `vibesensor.domain`, not from individual module files.
- Boundary decoders/serializers live under `apps/server/vibesensor/shared/boundaries/`; do not rebuild payload-driven business logic in report/history/runtime consumers.

Commands
- Other AI guidance and docs should reference this list instead of repeating it.
- `python -m pip install -e "./apps/server[dev]"`
- `make lint`
- `make typecheck-backend`
- `make docs-lint`
- `make test-all` (CI-parity local suite: `python3 tools/tests/run_ci_parallel.py`)
- `act -j backend-quality -W .github/workflows/ci.yml` (run a single CI job locally via `act`; requires Docker)
- `act -l -W .github/workflows/ci.yml` (list CI jobs)
- `python3 tools/tests/run_ci_parallel.py --job backend-quality --job backend-typecheck --job backend-tests` (faster backend-focused CI subset)
- `pytest -q apps/server/tests/<module>/` (run tests for a single feature area)
- `python3 tools/watch_pr_checks.py --pr <PR_NUMBER> --interval 30 --repo Skamba/VibeSensor`
- `cd apps/ui && npm ci && npm run typecheck && npm run build`
- `docker compose build --pull && docker compose up -d`

Pi access defaults (prebuilt image)
- Hotspot address: `10.4.0.1`
- HTTP UI and API: `http://10.4.0.1` (port `80` default); if the primary listener is unavailable, try `http://10.4.0.1:8000`
- SSH user: `pi`
- SSH password: `vibesensor`
- Remote simulator quick run: `vibesensor-sim --count 5 --duration 60 --server-host 10.4.0.1 --server-http-port 80 --speed-kmh 0 --no-interactive --no-auto-server`
- Use `--speed-kmh 0` when you only need UDP traffic or the Pi HTTP API is not answering; non-zero speed override performs an HTTP POST before streaming.
- Source: `infra/pi-image/pi-gen/README.md` (values may be overridden at image build time via `VS_FIRST_USER_NAME` and `VS_FIRST_USER_PASS`).
