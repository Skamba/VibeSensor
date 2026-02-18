# Repo map (apps + libs + infra)

## Entry points
- Server app: apps/server/vibesensor/app.py
- UI app: apps/ui/src/main.ts
- Firmware app: firmware/esp/src/main.cpp
- Pi image build: infra/pi-image/pi-gen/build.sh
- Docker entrypoint: docker-compose.yml (root canonical)

## Top-level layout
- apps/server: backend runtime, API orchestration, tests, scripts, systemd files
- apps/ui: dashboard frontend
- apps/simulator: ingest + websocket smoke simulators
- firmware/esp: ESP32 firmware
- libs/core/python/vibesensor_core: pure domain logic (strength bands, unit scaling, vibration strength)
- libs/adapters/python/vibesensor_adapters: repository/path integration adapters
- libs/shared: shared contracts/schemas/constants for server and UI
- infra/pi-image/pi-gen: Raspberry Pi image build pipeline
- infra/docker: Dockerfiles/container tooling

## Data flow
1. ESP sends sensor payloads to server UDP ingress.
2. Server processing computes spectra + strength metrics.
3. Shared metric keys (`libs/shared/contracts/metrics_fields.json`) shape output fields.
4. UI reads server payloads and renders diagnostics using shared keys.
5. Reports/export consume same metric contracts.

## Compatibility links
Legacy paths remain as symlinks for migration safety:
- pi -> apps/server
- ui -> apps/ui
- esp -> firmware/esp
- image/pi-gen -> infra/pi-image/pi-gen
- tools/simulator -> apps/simulator

Prefer canonical paths in new changes.
