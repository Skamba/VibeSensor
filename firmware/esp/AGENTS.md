# Firmware agent guidance

- Firmware rules: `../../.github/instructions/firmware.instructions.md`.
- Keep `src/main.cpp` thin; subsystem behavior belongs in `src/runtime_*.{h,cpp}`.
- Keep protocol/hotspot behavior aligned with `../../docs/protocol.md` and `../../infra/pi-image/pi-gen/README.md`.
- Validation: `cd firmware/esp && pio run`.
