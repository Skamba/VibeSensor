Agent operating guide (short)

Setup
- Python: `python -m pip install -e "./apps/server[dev]"`
- UI: `cd apps/ui && npm ci`

Run server
- Local: `python -m vibesensor.app --config apps/server/config.dev.yaml`
- On Pi (service install): `sudo ./apps/server/scripts/install_pi.sh`
- Hotspot repair: `sudo ./apps/server/scripts/hotspot_nmcli.sh`

Build Pi image
- Canonical: `./infra/pi-image/pi-gen/build.sh`
- Legacy alias remains: `./image/pi-gen/build.sh`

Firmware (ESP)
- Build/flash: `cd firmware/esp && pio run -t upload`
- Serial monitor: `cd firmware/esp && pio device monitor`

UI
- Dev: `cd apps/ui && npm run dev`
- Build: `cd apps/ui && npm run typecheck && npm run build`

Deterministic commands
- Format: `make format`
- Lint: `make lint`
- Test: `make test`
- Smoke: `make smoke`
- LOC check: `make loc`
- Docs lint: `make docs-lint`

Architecture map
- `apps/server`: FastAPI/runtime composition and orchestration
- `apps/ui`: dashboard client
- `apps/simulator`: runnable ingest/websocket simulators
- `firmware/esp`: ESP32 firmware
- `libs/core`: pure vibration/domain logic (no IO/framework)
- `libs/adapters`: path/discovery and integration glue
- `libs/shared`: canonical contracts/schemas/constants used by server and UI
- `infra/pi-image`: pi-gen image build
- Docker entrypoint: `docker-compose.yml` (root canonical); Dockerfile lives at `apps/server/Dockerfile`

Invariants
- Canonical vibration severity metric is `vibration_strength_db`.
- Strength bucket assignment must use `bucket_for_strength` logic.
- Shared contracts under `libs/shared/contracts` are source of truth.
- Avoid reading or indexing build outputs/caches (`artifacts/`, `.cache/`, `node_modules/`, `dist/`) unless debugging packaging.
