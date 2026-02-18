# Repo map (apps + libs + infra)

## Entry points
- Server app: apps/server/vibesensor/app.py
- UI app: apps/ui/src/main.ts
- Firmware app: firmware/esp/src/main.cpp
- Pi image build: infra/pi-image/pi-gen/build.sh
- Docker entrypoint: docker-compose.yml (root canonical)

## Read-first files (keep context cost low)
- Server (start here):
  - `apps/server/vibesensor/app.py`
  - `apps/server/vibesensor/api.py`
  - `apps/server/vibesensor/shared_contracts.py`
  - `apps/server/vibesensor/processing.py`
- UI (start here):
  - `apps/ui/src/main.ts`
  - `apps/ui/src/server_payload.ts`
  - `apps/ui/src/generated/shared_contracts.ts`
- Firmware (start here):
  - `firmware/esp/src/main.cpp`
  - `firmware/esp/include/vibesensor_contracts.h`
  - `firmware/esp/lib/vibesensor_proto/vibesensor_proto.h`
- Pi image (start here):
  - `infra/pi-image/pi-gen/build.sh`
  - `infra/pi-image/pi-gen/stage-vibesensor/00-packages`
  - `infra/pi-image/pi-gen/stage-vibesensor/04-run.sh`

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

## Path policy
Use canonical paths only: `apps/server`, `apps/ui`, `apps/simulator`,
`firmware/esp`, `infra/pi-image/pi-gen`, `docs`, and `libs`.
