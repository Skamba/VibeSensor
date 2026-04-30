# Authoritative Protocol & Ports Contract

This document is generated from code and shared contract files.

- Regenerate with: `make sync-contracts`
- Source of truth:
  - `apps/server/vibesensor/adapters/udp/protocol.py`
  - `apps/server/vibesensor/app/config_defaults.py`
  - `apps/server/vibesensor/cli/contract_reference_doc.py`

## Network contract

- HTTP API/UI server port: `80`
- UDP data ingest port: `9000`
- UDP control/identify port: `9001`

## Wire protocol version and message types

- Version: `1`
- HELLO: `1`
- DATA: `2`
- CMD: `3`
- ACK: `4`
- DATA_ACK: `5`
- HELLO_ACK: `6`
- CMD identify id: `1`
- HELLO explicit-ack capability bit: `0x01`

## Wire packet byte sizes

- HELLO fixed bytes (without variable name/fw bytes): `21`
- DATA header bytes (without sample payload): `22`
- CMD header bytes: `13`
- CMD identify bytes: `15`
- CMD sync clock bytes: `33`
- ACK bytes: `13`
- ACK sync clock bytes: `29`
- DATA_ACK bytes: `12`
- HELLO_ACK bytes: `8`

## Hello handshake

- Firmware sends the canonical HELLO packet shape, including the capabilities byte.
- Server replies to HELLO packets with `HELLO_ACK` on the sensor control port.
- Firmware waits for `HELLO_ACK` before sending DATA frames, so the control path
  is validated before streaming starts.

## Shared metric payload fields

- `vibration_strength_db`
- `strength_bucket`

## Shared report summary fields

- `run_id`
- `timestamp_utc`
- `client_id`
- `client_name`
- `speed_kmh`
- `dominant_freq_hz`
- `vibration_strength_db`
- `strength_bucket`
- `top_peaks`
