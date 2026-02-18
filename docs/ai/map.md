# VibeSensor AI Entry-Point Map

## Key Entry Points (canonical)
- `pi/vibesensor/app.py` - app factory, runtime loop, WS payload assembly.
- `pi/vibesensor/api.py` - HTTP endpoints and request/response surface.
- `pi/vibesensor/processing.py` - signal buffers, FFT, metrics, freshness filtering.
- `pi/vibesensor/metrics_log.py` - run/session logging and history integration.
- `pi/vibesensor/live_diagnostics.py` - event detection engine logic.
- `pi/vibesensor/config.py` - config defaults, schema mapping, typed dataclasses.
- `pi/vibesensor/history_db.py` - persisted run DB interfaces.
- `pi/vibesensor/report_pdf.py` - report generation pipeline.
- `pi/vibesensor/report_i18n.py` - translatable report string keys.
- `pi/vibesensor/registry.py` - client liveness and metadata registry.
- `pi/vibesensor/ws_hub.py` - websocket client fanout and broadcast.
- `pi/scripts/hotspot_nmcli.sh` - AP provisioning (must be offline-safe).
- `pi/systemd/vibesensor-hotspot.service` - hotspot boot orchestration unit.
- `image/pi-gen/build.sh` - Pi image wrapper + stage generation + assertions.
- `image/pi-gen/assets/vibesensor-hotspot.service` - baked image hotspot unit.
- `tools/simulator/sim_sender.py` - synthetic sensor traffic source.
- `tools/simulator/ws_smoke.py` - websocket smoke verifier.
- `ui/src/main.ts` - UI state reducer/render orchestration.
- `ui/src/ws.ts` - websocket client and payload contract handling.
- `.github/workflows/ci.yml` - CI critical checks and smoke flow.

## Module Boundaries
- **Acquisition**: `udp_data_rx.py`, `registry.py`.
- **Computation**: `processing.py`, `analysis/*`, `live_diagnostics.py`.
- **Delivery**: `app.py`, `api.py`, `ws_hub.py`, `ui/src/*`.
- **Persistence**: `metrics_log.py`, `history_db.py`, `runlog.py`.
- **Device Ops**: `pi/scripts/*`, `pi/systemd/*`, `image/pi-gen/*`.

## Hot Spots (read before touching)
- `pi/vibesensor/app.py` (high fan-in, scheduling-sensitive).
- `ui/src/main.ts` (large orchestrator; keep changes scoped).
- `image/pi-gen/build.sh` (artifact correctness + mount assertions).
- `pi/scripts/hotspot_nmcli.sh` (boot-critical behavior).

## Safe Change Areas
- New focused backend helpers: `pi/vibesensor/analysis/*`.
- Test additions: `pi/tests/test_*` with narrow scope.
- AI docs/runbooks: `docs/ai/*`.
- Simulator-only enhancements: `tools/simulator/*`.

## File Selection Heuristic (<=10 files)
1. Pick one hot spot + directly imported helpers.
2. Add 1–2 nearest tests.
3. Add any impacted config/unit file.
4. Avoid scanning unrelated modules.
