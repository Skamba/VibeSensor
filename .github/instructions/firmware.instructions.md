---
applyTo: "firmware/esp/**"
---
Firmware rules for `firmware/esp`.

- `src/main.cpp` stays a thin orchestrator. Put queue, sampling, transport, Wi-Fi, LED, config, and status logic in the matching `runtime_*.{h,cpp}` owner.
- Keep firmware aligned with `docs/protocol.md` and `infra/pi-image/pi-gen/README.md`. Do not add runtime provisioning flows or internet-dependent hotspot boot assumptions.
- Prefer targeted edits in the existing subsystem owner (`runtime_sampling.*`, `runtime_transport.*`, `runtime_wifi.*`, etc.) over duplicate helpers or parallel recovery paths.
- Validation: run `cd firmware/esp && pio run` for code changes. For protocol/native CI parity add `python tools/firmware/generate_protocol_contract_fixtures.py --check` and `cd firmware/esp && pio test -e native`. Use `pio run -t upload` and `pio device monitor` only for hardware-backed confirmation.
- The HELLO `firmware_version` is the build identity `fw-<date>+<digest>` from `tools/firmware/firmware_build_version.py`: a digest of `platformio.ini`, `src/`, `lib/` and `include/`, plus the date of the newest commit touching them. The Pi marks a sensor outdated only when this identity differs from its bundle's, so never feed the server release or commit into it, and add any new build input (a file outside those paths that changes the image) to `FIRMWARE_INPUTS`.
