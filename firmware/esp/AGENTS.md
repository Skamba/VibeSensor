# Firmware agent guidance

Firmware-specific rules live in `../../.github/instructions/firmware.instructions.md`.

Keep `src/main.cpp` as a thin orchestrator. Put queue, sampling, transport, Wi-Fi, LED, config, and status behavior in the matching `src/runtime_*.{h,cpp}` owner.

Keep firmware aligned with `../../docs/protocol.md` and `../../infra/pi-image/pi-gen/README.md`; do not add internet-dependent hotspot boot assumptions.

Default validation:
- `cd firmware/esp && pio run`
