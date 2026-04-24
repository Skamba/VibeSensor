Canonical AI guidance entrypoint (scope: short repo orientation, enduring architectural invariants, and command pointers)

Guidance stack
- This file is the canonical AI guidance entrypoint and short index.
- `.github/instructions/general.instructions.md` owns shared workflow, validation, and documentation-maintenance guardrails.
- `.github/instructions/backend.instructions.md`, `.github/instructions/frontend.instructions.md`, `.github/instructions/firmware.instructions.md`, `.github/instructions/pi-image.instructions.md`, and `.github/instructions/tests.instructions.md` own area-specific deltas only.
- `docs/ai/repo-map.md` is the repo map for layout, entry points, and stable ownership boundaries; it is not a second workflow or policy guide.
- Do not create additional guidance files in `docs/ai/`.
- Paths below are repo-relative unless a bullet is explicitly talking about a Python import namespace such as `vibesensor.domain` or `vibesensor.shared.*`.

Execution philosophy
- Be decisive, direct, and completion-oriented. Default to completing the user's requested change end to end.
- Expand scope only to fix the root cause, update direct callers, or handle clearly adjacent regressions found during validation. Do not broaden into unrelated cleanup.
- Decompose large tasks into execution waves and keep going until the in-scope work is done, validated, or blocked by credentials, hardware, external services, or an explicit user pause.
- Breaking internal-only interfaces is acceptable and preferred when the result is cleaner. The repo controls both producers and consumers; coordinated breaking refactors are the right default, not the exception.
- Do not preserve deprecated aliases, old DTO shapes, fallback branches, or legacy config forms unless a real external consumer is confirmed. The cleaner architecture wins.
- Full workflow and validation rules live in `.github/instructions/general.instructions.md`.

Repository overview
- VibeSensor: Python backend (`apps/server/`), TypeScript/Vite dashboard (`apps/ui/`), ESP32 firmware (`firmware/esp/`), Pi image build (`infra/pi-image/`).
- Key runtime artifacts: `docker-compose.yml` (local stack), `apps/server/pyproject.toml` (backend packaging and CLI entry points).
- Units policy: raw ingest/sample acceleration values may use g, but post-stop analysis outputs (persisted summaries, findings, report-template artifacts) must expose vibration strength or intensity in dB only.
- Canonical dB definition: `apps/server/vibesensor/vibration_strength.py::vibration_strength_db_scalar()` (`20*log10((peak+eps)/(floor+eps))`, `eps=max(1e-9, floor*0.05)`).

Architectural constraints
- Offline-first hotspot boot: hotspot provisioning must not depend on internet connectivity. Required packages are baked into the image build stage.
- Deterministic image outputs: custom pi-gen stage must export uniquely suffixed artifacts and self-validate rootfs contents.
- Internal shared logic belongs in the server package (`apps/server/vibesensor/vibration_strength.py`, `apps/server/vibesensor/strength_bands.py`), not in separate packages. Generated shared TS constants are emitted to `apps/ui/src/constants.ts` from backend sources under the `vibesensor.shared.*` Python import namespace.
- Do not create runtime file-loading mechanisms for static configuration data. Use Python constants for values that don't change between deployments.

Domain model (scope: behavioral rules only; see `docs/domain-model.md` for the full domain object catalog and relationship map)
- Domain objects own behavior (classification, ranking, lifecycle, computation). Adapters at persistence/transport/rendering boundaries bridge to/from domain objects but do not duplicate domain logic.
- Consumers import from `vibesensor.domain`, not from individual module files.
- Boundary decoders/serializers live under `apps/server/vibesensor/shared/boundaries/`; do not rebuild payload-driven business logic in report/history/runtime consumers.
- Factories that build domain objects from already-typed internal metadata, snapshots, or computed state belong on domain objects (or the owning use-case), not in `apps/server/vibesensor/shared/boundaries/`.
- Backend layer dependency DAG is enforced by `tools/dev/verify_backend_static_guards.py::_check_layer_boundaries()`:
  - `domain` imports no inner project layers
  - `shared` may import `domain`
  - `use_cases` may import `domain` and `shared`
  - `infra` may import `domain` and `shared`
  - `adapters` may import `domain`, `shared`, `infra`, and `use_cases`
  - `app` may import all backend layers
- Treat `shared -> domain` and `infra -> domain` as intentional allowed edges, not violations. The disallowed direction is outer-layer leakage back inward, such as `use_cases -> adapters` or `domain -> shared/infra/adapters`.

Commands
- Other AI guidance and docs should reference this list instead of repeating it.
- `make setup`
- `make format`
- `python -m pip install -e "./apps/server[dev]"`
- `make lint`
- `make typecheck-backend`
- `make sync-contracts`
- `make ui-typecheck` (default frontend validation path: materialize generated UI contract artifacts, then run UI lint and TypeScript checks)
- `make docs-lint`
- `make test-changed` (heuristic changed-file runner vs `origin/main`, falling back to `main`)
- `make test-all` (CI-parity local suite: `python3 tools/tests/run_ci_parallel.py`)
- `act -j backend-lint -W .github/workflows/ci.yml` (run a single CI job locally via `act`; requires Docker)
- `act -l -W .github/workflows/ci.yml` (list CI jobs)
- `python3 tools/tests/run_ci_parallel.py --job backend-lint --job repo-hygiene --job backend-static-guards --job backend-preflight --job docs-lint --job backend-contract-drift --job backend-typecheck --job backend-tests-1 --job backend-tests-2 --job backend-tests-3 --job backend-tests-4 --job backend-tests-5` (faster backend-focused CI subset)
- `pytest -q apps/server/tests/<module>/` (run tests for a single feature area)
- `python3 tools/watch_pr_checks.py --pr <PR_NUMBER> --repo Skamba/VibeSensor --merge-on-green` (compact state-change watcher; default `--interval 10`, `--heartbeat 120`; omit `--merge-on-green` for watch-only mode)
- `cd apps/ui && npm ci && npm run build` (bundle build after `make ui-typecheck`; raw `npm run typecheck` / `npm run build` only check contract freshness and fail if generated UI files are stale)
- `cd apps/ui && npm run test:visual`
- `cd firmware/esp && pio run`
- `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh`
- `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh`
- `./infra/pi-image/pi-gen/validate-image.sh`
- `docker compose build --pull && docker compose up -d`

Validation chooser
- Backend source: `make lint`, `make typecheck-backend`, and targeted `pytest -q apps/server/tests/<module>/`.
- Backend contracts/API payloads: add `make sync-contracts` and `make ui-typecheck`.
- Frontend logic, contracts, or composition: `make ui-typecheck`; for bundle behavior also run `cd apps/ui && npm ci && npm run build`.
- Rendered UI or snapshots: add `cd apps/ui && npm run test:visual`.
- Firmware code: `cd firmware/esp && pio run`.
- Pi app artifact changes: `BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh`.
- Pi image-stage logic: `BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh`, then `./infra/pi-image/pi-gen/validate-image.sh [artifact]` when an artifact is available.
- Docs or AI-instruction-only changes: `make docs-lint`.

Command gotchas
- `make ui-typecheck` is the default frontend gate because it materializes generated UI contract artifacts before linting and TypeScript checks.
- Raw `cd apps/ui && npm run typecheck` or `npm run build` can fail when generated UI contract files are stale; run `make sync-contracts` or `make ui-typecheck` first when backend contracts changed.
- `act` requires Docker and is best for targeted GitHub workflow parity, not docs-only changes.
- PlatformIO must be installed before `cd firmware/esp && pio run`.
- Pi image builds are expensive; use the narrow `BUILD_MODE=app` or `BUILD_MODE=image` path unless both layers changed.
- The local Docker stack is for runtime integration behavior, not docs-only, instruction-only, or pure unit-test changes.

Pi access defaults (prebuilt image)
- Narrow owner: `infra/pi-image/pi-gen/README.md` and `docs/operational-runbooks.md`
- Use those docs for hotspot/UI defaults, SSH defaults, and remote-simulator examples; image-build overrides still live under `VS_FIRST_USER_NAME` and `VS_FIRST_USER_PASS` in `infra/pi-image/pi-gen/README.md`.
