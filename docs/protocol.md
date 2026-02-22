# Authoritative Protocol & Ports Contract

This document is generated from code and shared contract files.

- Regenerate with: `python3 tools/config/generate_contract_reference_doc.py`
- Source of truth:
  - `apps/server/vibesensor/protocol.py`
  - `apps/server/vibesensor/config.py`
  - `libs/shared/contracts/metrics_fields.json`
  - `libs/shared/contracts/report_fields.json`

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
- CMD identify id: `1`

## Wire packet byte sizes

- HELLO fixed bytes (without variable name/fw bytes): `20`
- DATA header bytes (without sample payload): `22`
- CMD header bytes: `13`
- CMD identify bytes: `15`
- ACK bytes: `13`
- DATA_ACK bytes: `12`

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
