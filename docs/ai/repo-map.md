# Repo map

Scope: detailed file layout, entry points, and stable ownership boundaries for navigation.
This file is the repo map, not a workflow or policy guide. Use `.github/copilot-instructions.md` for canonical AI guidance and `.github/instructions/*.instructions.md` for workflow or area-specific rules.
Paths below are repo-relative unless a line explicitly calls out a Python import namespace.

## Primary entry points

- Backend app: `apps/server/vibesensor/app/bootstrap.py`
- Backend service wiring: `apps/server/vibesensor/app/container.py`
- Backend route assembly: `apps/server/vibesensor/adapters/http/router.py` with domain bundles in `apps/server/vibesensor/adapters/http/route_bundles.py`
- UI app entry: `apps/ui/src/main.ts`
- UI runtime/composition root: `apps/ui/src/app/ui_app_runtime.ts`
- UI runtime owners: `apps/ui/src/app/runtime/`
- Simulator CLI: `apps/server/vibesensor/adapters/simulator/sim_sender.py` (thin CLI/orchestrator over `apps/server/vibesensor/adapters/simulator/sim_client.py`, `apps/server/vibesensor/adapters/simulator/sim_scene.py`, and `apps/server/vibesensor/adapters/simulator/sim_runtime.py`)
- Firmware app: `firmware/esp/src/main.cpp` (thin orchestrator) plus `firmware/esp/src/runtime_*.{h,cpp}`
- Pi image build: `infra/pi-image/pi-gen/build.sh` (thin entrypoint), `infra/pi-image/pi-gen/lib/`, `infra/pi-image/pi-gen/templates/`, and `infra/pi-image/pi-gen/validate-image.sh`
- Local stack entry point: `docker-compose.yml`

## Top-level layout

- `apps/server/`: backend package, configs, tests, scripts, systemd units, public UI assets, simulator, and config tooling.
- `apps/ui/`: TypeScript/Vite dashboard and Playwright tests.
- `firmware/esp/`: ESP32 firmware. `src/main.cpp` owns setup/loop orchestration, while `src/runtime_*.{h,cpp}` owns queue, sampling, transport, Wi-Fi, LED, config, and status logic.
- `apps/server/vibesensor/cli/`: CLI entry points — `apps/server/vibesensor/cli/server.py` (main server), `apps/server/vibesensor/cli/report.py` (report generation), `apps/server/vibesensor/cli/preflight.py` (config preflight), `apps/server/vibesensor/cli/hotspot_config.py` (hotspot config export for shell scripts), `apps/server/vibesensor/cli/http_api_schema_export.py`, and `apps/server/vibesensor/cli/ws_schema_export.py`.
- `apps/server/vibesensor/vibration_strength.py`, `apps/server/vibesensor/strength_bands.py`: shared vibration math and unit logic. Hot-path functions accept numpy arrays; scalar functions remain pure Python.
- `apps/server/vibesensor/report_i18n.py`: canonical report-string/i18n helpers shared by boundary shaping and PDF rendering.
- `infra/pi-image/pi-gen/`: Raspberry Pi image build pipeline. `build.sh` is the thin entrypoint for `BUILD_MODE=app|image|all`; `lib/` owns focused host-side helpers (prereqs, mirror selection, app artifacts, pi-gen repo prep, stage assembly, artifact selection, validation helpers); `templates/` owns tracked stage/config source files copied into `.cache/pi-gen/`; and `validate-image.sh` reruns the post-build mount/chroot/QEMU validator against an existing artifact.
- `docs/`: human-facing docs plus AI repo maps and runbooks.

## Backend package layout

- `apps/server/vibesensor/app/`: startup, dependency wiring, runtime state, and config loading.
- `apps/server/vibesensor/adapters/http/`: API route groups, bundle-level router assembly (`apps/server/vibesensor/adapters/http/router.py`, `apps/server/vibesensor/adapters/http/route_bundles.py`), grouped route dependencies, and HTTP-specific Pydantic request/response models under `apps/server/vibesensor/adapters/http/models/`.
- `apps/server/vibesensor/adapters/websocket/hub.py`: live WebSocket fan-out and payload delivery.
- `apps/server/vibesensor/adapters/persistence/`: SQLite history storage and static car-library loading.
- `apps/server/vibesensor/adapters/pdf/`: report mapping and PDF rendering, with grouped panel renderers under `apps/server/vibesensor/adapters/pdf/panels/`. See `docs/report_pipeline.md` for the report flow.
- `apps/server/vibesensor/adapters/udp/`, `apps/server/vibesensor/adapters/gps/`, `apps/server/vibesensor/adapters/simulator/`, `apps/server/vibesensor/adapters/hotspot/`: transport and device-facing runtime adapters.
- `apps/server/vibesensor/infra/runtime/`: runtime lifecycle, health, registry, and WebSocket coordination.
- `apps/server/vibesensor/infra/processing/`: signal-processing execution and payload building. See `docs/intake_buffering.md` for the live ingest, snapshot/FFT, and buffering flow.
- `apps/server/vibesensor/infra/config/`: runtime settings storage and read-side access.
- `apps/server/vibesensor/infra/workers/`: worker-pool infrastructure.
- `apps/server/vibesensor/use_cases/diagnostics/`: post-stop diagnostics pipeline. Core sample/statistics types stay in `_types.py`, while plot/table/output DTOs live in `_view_types.py`. See `docs/analysis_pipeline.md` for the module map/data flow and `docs/order_tracking.md` for the shared order-reference and matching flow.
- `apps/server/vibesensor/use_cases/history/`: history queries, report loading/preparation/caching, and export orchestration. See `docs/report_pipeline.md` for report-specific flow.
- `apps/server/vibesensor/infra/runtime/health_snapshot.py`: application-level runtime health snapshot assembly for the `/api/health` route.
- `apps/server/vibesensor/use_cases/run/`: recording pipeline orchestration. `apps/server/vibesensor/use_cases/run/logger.py` is the `RunRecorder` entrypoint, `apps/server/vibesensor/use_cases/run/run_context.py` owns run/history context orchestration helpers, `apps/server/vibesensor/use_cases/run/capture_readiness.py` owns the backend idle/pre-record gate, and the `post_analysis*.py` modules split queueing, loading, execution, and summary shaping. See `docs/run_lifecycle.md` for the recording -> persistence -> post-analysis handoff.
- `apps/server/vibesensor/use_cases/updates/`: wheel-based updater workflow and public facade. Focused subpackages group `apps/server/vibesensor/use_cases/updates/firmware/`, `apps/server/vibesensor/use_cases/updates/wifi/`, and `apps/server/vibesensor/use_cases/updates/releases/`, while the root package keeps installer/state/orchestration helpers.
- `apps/server/vibesensor/shared/`: cross-cutting ports, model/payload types, JSON helpers, boundary codecs, split constant modules under `apps/server/vibesensor/shared/constants/`, and small package-level helpers such as `apps/server/vibesensor/shared/_data_files.py`, `apps/server/vibesensor/shared/sensor_units.py`, and `apps/server/vibesensor/shared/run_context_warning.py`. Key stable owners include `apps/server/vibesensor/shared/types/persisted_analysis.py`, `apps/server/vibesensor/shared/types/analysis_views.py`, `apps/server/vibesensor/shared/types/history_analysis_contracts.py`, `apps/server/vibesensor/shared/types/run_schema.py`, `apps/server/vibesensor/shared/types/car_config.py`, `apps/server/vibesensor/shared/types/speed_source_config.py`, and the codec/projection modules under `apps/server/vibesensor/shared/boundaries/` such as `apps/server/vibesensor/shared/boundaries/settings_snapshot_codec.py`.
- `apps/server/vibesensor/domain/`: domain model package for classification, ranking, lifecycle, and query logic. See `docs/domain-model.md` for the domain object graph.
- `apps/ui/src/app/runtime/`: UI composition root and runtime controllers.
- `apps/ui/src/app/features/`: UI feature workflows for settings, realtime, history, updates, cars, and ESP flash, plus the shared polling controller used by long-running status features.
- `apps/ui/src/app/views/`: DOM renderers and event-target decoders, including the car wizard view helpers.
- `apps/ui/src/config.ts`: centralized UI tuning constants (polling intervals, spectrum bounds, history heatmap positions).

## Backend layer dependency DAG

- Package-level import-direction enforcement lives in `apps/server/pyproject.toml`
  under `[tool.importlinter]`. Repo-specific backend static guards remain in
  `tools/dev/verify_backend_static_guards.py`.
- Allowed dependency directions are:
  - `domain` -> none
  - `shared` -> `domain`
  - `use_cases` -> `domain`, `shared`
  - `infra` -> `domain`, `shared`
  - `adapters` -> `domain`, `shared`, `infra`, `use_cases`
  - `app` -> all backend layers
- `shared -> domain` and `infra -> domain` are intentional allowed edges. Focus dependency cleanup on disallowed inward leakage such as `use_cases -> adapters` or `domain -> outer layers`, not these permitted edges.

## Test layout

- `apps/server/tests/` mirrors the backend package layout with `app/`, `shared/`, `domain/`, `use_cases/`, `adapters/`, and `infra/` subtrees.
- Cross-cutting coverage lives in `integration/` and `hygiene/`.
- Regression tests live in the feature directory they primarily test, or in `integration/` for cross-cutting regressions.
- Shared test support lives at the test root (`conftest.py`, `_paths.py`, focused helper modules, and the `test_support/` package including `findings.py` for shared finding-payload factories).
- Full map: `docs/testing.md`.
