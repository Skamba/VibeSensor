# VibeSensor AI Entry-Point Map

## Key Entry Points (canonical)
- `apps/server/vibesensor/app.py` - app factory, runtime loop, WS payload assembly.
- `apps/server/vibesensor/api.py` - HTTP endpoints and request/response surface.
- `apps/server/vibesensor/processing.py` - signal buffers, FFT, metrics, freshness filtering.
- `apps/server/vibesensor/metrics_log/` - run/session logging and history integration.
- `apps/server/vibesensor/live_diagnostics.py` - event detection engine logic.
- `apps/server/vibesensor/config.py` - config defaults, schema mapping, typed dataclasses.
- `apps/server/vibesensor/history_db.py` - persisted run DB interfaces.
- `apps/server/vibesensor/report/pdf_builder.py` - report generation pipeline.
- `apps/server/vibesensor/report_i18n.py` - translatable report string keys.
- `apps/server/vibesensor/registry.py` - client liveness and metadata registry.
- `apps/server/vibesensor/ws_hub.py` - websocket client fanout and broadcast.
- `apps/server/scripts/hotspot_nmcli.sh` - AP provisioning (must be offline-safe).
- `apps/server/systemd/vibesensor-hotspot.service` - hotspot boot orchestration unit.
- `infra/pi-image/pi-gen/build.sh` - Pi image wrapper + stage generation + assertions.
- `infra/pi-image/pi-gen/assets/vibesensor-hotspot.service` - baked image hotspot unit.
- `apps/simulator/sim_sender.py` - synthetic sensor traffic source.
- `apps/simulator/ws_smoke.py` - websocket smoke verifier.
- `apps/ui/src/main.ts` - UI state reducer/render orchestration.
- `apps/ui/src/ws.ts` - websocket client and payload contract handling.
- `.github/workflows/ci.yml` - CI critical checks; local mirror is `make test-all` via `tools/tests/run_ci_parallel.py`.

## Module Boundaries
- **Acquisition**: `udp_data_rx.py`, `registry.py`.
- **Computation**: `processing.py`, `libs/core/python/vibesensor_core/*`, `live_diagnostics.py`.
- **Delivery**: `app.py`, `api.py`, `ws_hub.py`, `apps/ui/src/*`.
- **Persistence**: `metrics_log/`, `history_db.py`, `runlog.py`.
- **Device Ops**: `apps/server/scripts/*`, `apps/server/systemd/*`, `infra/pi-image/pi-gen/*`.

## Hot Spots (read before touching)
- `apps/server/vibesensor/app.py` (high fan-in, scheduling-sensitive).
- `apps/ui/src/main.ts` (large orchestrator; keep changes scoped).
- `infra/pi-image/pi-gen/build.sh` (artifact correctness + mount assertions).
- `apps/server/scripts/hotspot_nmcli.sh` (boot-critical behavior).

## Safe Change Areas
- New focused backend helpers: `apps/server/vibesensor/` modules or `libs/core/python/vibesensor_core/*` for shared vibration math.
- Test additions: `apps/server/tests/test_*` with narrow scope.
- AI docs/runbooks: `docs/ai/*`.
- Simulator-only enhancements: `apps/simulator/*`.

## File Selection Heuristic (start focused, expand when needed)
1. Pick one hot spot + directly imported helpers.
2. Add 1–2 nearest tests.
3. Add any impacted config/unit file.
4. Avoid scanning unrelated modules.
