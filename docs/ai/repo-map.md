# Repo map

This file is the repo map, not a workflow or policy guide. On-demand navigation help: do not read it by default; use `rg`, file names, imports, and tests first, and open this only when ownership is unclear. Workflow and policy rules live in `.github/copilot-instructions.md` and `.github/instructions/*.instructions.md`.

## Primary entry points

- Backend app/runtime: `apps/server/vibesensor/app/bootstrap.py`, `apps/server/vibesensor/app/composition.py`
- Backend HTTP assembly: `apps/server/vibesensor/web/router.py`
- Backend CLIs: `apps/server/vibesensor/cli/`
- UI app/shell: `apps/ui/src/main.tsx`, `apps/ui/src/app.tsx`, `apps/ui/src/app_store.ts`
- Simulator: `apps/server/vibesensor/simulator/`
- Firmware: `firmware/esp/src/main.cpp`, `firmware/esp/src/runtime_*.{h,cpp}`
- Pi image: `infra/pi-image/pi-gen/build.sh`, `infra/pi-image/pi-gen/lib/`, `infra/pi-image/pi-gen/templates/`, `infra/pi-image/pi-gen/validate-image.sh`
- Local stack: `docker-compose.yml`

## Top-level ownership

- `apps/server/`: Python backend package, configs, tests, simulator, static UI assets, systemd units, and backend tooling.
- `apps/ui/`: TypeScript/Vite dashboard and Playwright/Vitest tests.
- `firmware/esp/`: ESP32 firmware; keep `main.cpp` thin and subsystem logic in `runtime_*`.
- `infra/pi-image/`: Raspberry Pi image build, templates, validation, and image docs.
- `docs/`: human-facing docs plus this navigation index.
- `.github/instructions/`: path-scoped AI instructions.

## Backend package ownership

One package per feature under `apps/server/vibesensor/`; each owns its types, logic, and persistence glue.

- `app/`: FastAPI/Granian bootstrap, config loading, the composition root (`composition.py`), and the runtime lifecycle.
- `web/`: HTTP/WebSocket routes, Pydantic request/response models, middleware, health snapshot, `WebServices` + `create_router()`.
- `ingest/`: UDP wire protocol, data receiver/control plane, client registry, ingest diagnostics.
- `live/`: signal processor, processing loop, live WebSocket payload and broadcaster.
- `dsp/`: FFT, window quality, order bands, canonical dB strength math, DSP constants.
- `recording/`: `RunRecorder`, sample flush, raw-capture writer, run metadata/sensor-frame codecs, capture readiness.
- `analysis/`: post-run diagnostics (findings, `orders/`, `peaks/`) and the post-analysis worker.
- `summary/`: the persisted analysis-summary contract and its (de)serialization; read by history, report, and web.
- `report/`: report facts, document model (`model/`), document assembly (`document/`), PDF rendering (`pdf/`), i18n.
- `history/`: `HistoryDB` (SQLite), history queries/projections, exports.
- `settings/`: persisted car/sensor/speed-source/analysis/UI settings and the car library.
- `speed/`: GPS (gpsd), Bluetooth OBD (`obd/`), selected-speed-source coordination.
- `updates/`: wheel/firmware updater, releases, Wi-Fi uplink.
- `hotspot/`: fixed hotspot settings and the periodic hotspot watchdog (`vibesensor-hotspot-self-heal` timer).
- `simulator/`: sensor simulator and WebSocket smoke client.
- `domain/`: core value objects and aggregates; see `docs/domain-model.md`.
- `common/`: small cross-cutting helpers (JSON, time, logging, errors, units, process env settings).
- `cli/`: console entry points.
- Report flow details: `docs/report_pipeline.md`.
- Analysis/run/live ingest details: `docs/analysis_pipeline.md`, `docs/run_lifecycle.md`, `docs/intake_buffering.md`, `docs/order_tracking.md`.

## Backend package rules

Enforced by the import-linter contracts in `apps/server/pyproject.toml` (annotation-only `TYPE_CHECKING` imports are exempt):

| Rule | Meaning |
|---|---|
| Layers: `cli`/`simulator` > `app` > `web` > feature packages > `domain`/`common` | Feature packages never import `web`, `app`, or `cli`; `domain` and `common` import no feature package. |
| Live path stays light | `ingest`, `live`, and `dsp` never import `analysis`, `history`, `recording`, `report`, or `summary`. |
| Reports never run analysis | `report` never imports `analysis`; it renders stored summaries. |

## UI ownership

- `apps/ui/src/app.tsx`, `apps/ui/src/app_store.ts`: the shell (one render root, navigation, preferences, banner, confirmation).
- `apps/ui/src/pages/<page>/`: page component, page store, pure helpers; pages never import each other.
- `apps/ui/src/live_store.ts` + `live_transport.ts`: live data the pages share and the WebSocket feed that fills it.
- `apps/ui/src/api/http.ts`, `apps/ui/src/ws.ts`, generated contracts, validators: canonical transport/contract seams.
- Contract sync details: `apps/ui/README.md`.

## Firmware and Pi image

- Firmware protocol contract: `docs/protocol.md`.
- Firmware local guidance: `firmware/esp/AGENTS.md`, `.github/instructions/firmware.instructions.md`.
- Pi image build/defaults: `infra/pi-image/pi-gen/README.md`.
- Pi local guidance: `infra/pi-image/AGENTS.md`, `.github/instructions/pi-image.instructions.md`.

## Tests and validation

- Backend tests mirror the package layout under `apps/server/tests/<package>/` (for example `tests/recording/`, `tests/report/`).
- Cross-cutting regressions go in `apps/server/tests/integration/`; guards go in `apps/server/tests/hygiene/`.
- Shared backend test helpers live in `apps/server/tests/test_support/`.
- Full test placement and command router: `docs/testing.md`.
