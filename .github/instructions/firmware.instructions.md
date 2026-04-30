---
applyTo: "firmware/esp/**"
---
Firmware (`firmware/esp`)
- `src/main.cpp` stays a thin orchestrator. Keep queue, sampling, transport, Wi-Fi, LED, config, and status logic in the matching `runtime_*.{h,cpp}` owner instead of growing `main.cpp` or creating overlapping runtime state.
- Keep the firmware aligned with the fixed hotspot/protocol contract in `docs/protocol.md` and `infra/pi-image/pi-gen/README.md`; do not add runtime provisioning flows or internet-dependent boot assumptions.
- Prefer targeted edits in the existing runtime module that owns the subsystem (`runtime_sampling.*`, `runtime_transport.*`, `runtime_wifi.*`, and peers) over adding duplicate helpers or parallel recovery paths.
- Validation: for firmware code changes, run `cd firmware/esp && pio run` for compile coverage. For firmware protocol/native CI parity, also run `python tools/firmware/generate_protocol_contract_fixtures.py --check` and `cd firmware/esp && pio test -e native`. Use `pio run -t upload` and `pio device monitor` only when hardware-backed behavior needs confirmation. For docs/instruction-only changes under `firmware/esp/`, use proportionate docs validation instead of flashing hardware.
