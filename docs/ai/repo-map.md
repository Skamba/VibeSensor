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
- `dsp/`: FFT, order bands, canonical dB strength math, DSP constants.
- `recording/`: `RunRecorder`, sample flush, raw-capture writer, run metadata/sensor-frame codecs, capture readiness, the guided brake step's stop counter.
- `analysis/`: post-run diagnostics (findings, `orders/`, `peaks/`) and the post-analysis worker.
- `summary/`: the persisted analysis-summary contract and its (de)serialization; read by history, report, and web.
- `report/`: PDF report of a stored run: `view_model.py` (stored analysis + run metadata -> localized text), `pdf.py` (ReportLab pages and charts), `service.py` (history delivery + cache), `i18n.py`.
- `history/`: `HistoryDB` (SQLite), history queries/projections, exports.
- `settings/`: persisted car/sensor/speed-source/analysis/UI settings and the car library.
- `speed/`: GPS (gpsd), Bluetooth OBD (`obd/`), selected-speed-source coordination.
- `updates/`: wheel/firmware updater, releases, Wi-Fi uplink.
- `hotspot/`: fixed hotspot settings and the captive-portal probe hosts (`captive_portal.py`, used by `web/middleware.py`). The root-side copies live in `apps/server/root-helpers/`.

- `clock/`: steps the RTC-less Pi's unsynchronised wall clock to the browser clock the UI reports on connect, before a recording starts and after it stops (needs `CAP_SYS_TIME` from `vibesensor.service`); says whether the clock is trusted (kept per boot in `clock_state.json`), so runs started on an unset clock are marked `start_time_unverified`; `run_times.py` re-dates this boot's such runs once it is.
- `power/`: `monitor.py` polls the Pi's undervoltage alarm and SoC temperature from sysfs, logs transitions, reports them in `/api/health` (`power`, per boot in `power_state.json`), and tells the recorder which issues a run saw (`power_issues` in run metadata).
- `simulator/`: sensor simulator and WebSocket smoke client.
- `domain/`: core value objects and aggregates; see `docs/domain-model.md`.
- `common/`: small cross-cutting helpers (JSON, time, logging, errors, units, process env settings, the privileged helper client, `root_side.py` which compares the installed root-side stamp with this release).
- `cli/`: console entry points.
- `apps/server/root-helpers/` (outside the package): the stdlib-only scripts root runs (privileged helper, update allowlist, OBD admin, `hotspot_nmcli.sh`, `vibesensor_hotspot.py` hotspot settings and watchdog). `install_systemd_units.sh` copies them to root-owned `/usr/local/lib/vibesensor`; they never import `vibesensor`, constants they copy are pinned by parity tests in `tests/root_helpers/`, which also runs `hotspot_nmcli.sh` end to end against stub `nmcli`. Any change under `root-helpers/`, `scripts/`, or `systemd/` changes `ROOT_SIDE_DIGEST` (`tests/hygiene/test_root_side.py`); prebuilt-image devices take it with `scripts/push_root_side.sh`.
- Report flow details: `docs/report_pipeline.md`.
- User journeys and expectation-setting principles (car wizard, readiness, source checks, report wording): `docs/user_journeys.md`; open gaps: `docs/user_journey_gaps.md`.
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
- Firmware build identity (HELLO `firmware_version`, `flash.json` stamp; digest of the firmware build inputs, not the server release): `tools/firmware/firmware_build_version.py`; server-side status: `apps/server/vibesensor/domain/sensor_firmware.py`.
- Pi image build/defaults: `infra/pi-image/pi-gen/README.md`.
- Pi local guidance: `infra/pi-image/AGENTS.md`, `.github/instructions/pi-image.instructions.md`.

## Tests and validation

- Backend tests mirror the package layout under `apps/server/tests/<package>/` (for example `tests/recording/`, `tests/report/`).
- Cross-cutting regressions go in `apps/server/tests/integration/`; guards go in `apps/server/tests/hygiene/`.
- Shared backend test helpers live in `apps/server/tests/test_support/`.
- Full test placement and command router: `docs/testing.md`.
