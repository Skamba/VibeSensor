# VibeSensor AI Context (Canonical)

## Purpose
VibeSensor is an offline vehicle vibration diagnostics system. A Raspberry Pi hosts a Wi-Fi AP, receives UDP accelerometer frames from ESP32 sensor nodes, runs FFT/order analysis, streams live diagnostics to a web UI, and stores run history/report outputs.

## Primary User Journeys
1. Live diagnostics: start server, connect sensors/simulator, inspect live dashboard.
2. Capture run data: monitor events, then stop and review history.
3. Reporting: generate/download PDF report from recorded run metadata.
4. Device deployment: build Pi image and boot into preconfigured hotspot mode.

## Architecture Overview
- ESP firmware (`esp/`): UDP frame sender + control ACKs.
- Backend (`pi/vibesensor/`): FastAPI app, UDP ingestion, signal processing, diagnostics, history storage.
- Frontend (`ui/src/`): WebSocket-driven dashboard and settings UI.
- Tooling (`tools/simulator/`): multi-client simulator and WS smoke checks.
- Image build (`image/pi-gen/`): deterministic Pi image generation with VibeSensor stage.

### Data Flow Boundaries
1. UDP ingress (`udp_data_rx.py`) updates registry + processor buffers.
2. Processing (`processing.py`) computes spectra/metrics.
3. Runtime loop (`app.py`) composes WS payloads and diagnostics.
4. Logging/history (`metrics_log.py`, `history_db.py`) persists run samples.
5. API/router (`api.py`) exposes health, client state, settings, reports.

## Where to Change What
- UI behavior/labels: `ui/src/main.ts`, `ui/src/i18n.ts`, `pi/public/` sync path.
- API routes/contracts: `pi/vibesensor/api.py`.
- Runtime orchestration/timers: `pi/vibesensor/app.py`.
- Signal/math logic: `pi/vibesensor/processing.py`, `pi/vibesensor/analysis/*`.
- Hotspot/deployment logic: `pi/scripts/hotspot_nmcli.sh`, `pi/systemd/*.service`, `image/pi-gen/build.sh`.
- Config schema/defaults: `pi/vibesensor/config.py`, `pi/config.example.yaml`.
- Tests: `pi/tests/` (pytest), `ui/tests/` (Playwright snapshots).

## Must-Not-Break Invariants
- Canonical vibration severity metric is `vibration_strength_db`; do not replace with raw g-value proxies.
- WS payload fields must remain backward compatible for UI (`clients`, `diagnostics`, `spectra`, `selected`).
- Hotspot startup must succeed offline (no runtime apt installs in hotspot script).
- Pi image output must include `/opt/VibeSensor`, `vibesensor-hotspot.service`, and `/etc/vibesensor/config.yaml`.
- CI default test mode is simulator E2E smoke; extended pytest suite is opt-in.

## Coding Conventions
- Python style: Ruff-enforced, explicit signatures, small focused modules.
- Tests: fast-focused pytest files under `pi/tests/`, avoid heavy integration unless requested.
- Frontend: TypeScript strict checks, no ad-hoc runtime contracts; use existing i18n keys.
- Infra: prefer deterministic scripts, fail-fast assertions, low-noise logs.

## Minimal Read Set for Most Changes
1. `docs/ai/context.md`
2. `docs/ai/map.md`
3. `docs/ai/runbooks.md`
4. `docs/ai/decisions.md`
5. Target area files (<=10 total additional files)
