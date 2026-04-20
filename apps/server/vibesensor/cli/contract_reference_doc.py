"""Contract reference document renderer.

Generates a human-readable Markdown description of the public UDP / HTTP /
WebSocket API contracts for use in documentation and diagnostics.
"""

from __future__ import annotations

__all__ = ["render_contract_reference_markdown"]

from vibesensor.adapters.udp.protocol import (
    ACK_BYTES,
    CMD_HEADER_BYTES,
    CMD_IDENTIFY,
    CMD_IDENTIFY_BYTES,
    DATA_ACK_BYTES,
    DATA_HEADER_BYTES,
    HELLO_ACK_BYTES,
    HELLO_CAP_EXPLICIT_ACK,
    HELLO_FIXED_BYTES,
    MSG_ACK,
    MSG_CMD,
    MSG_DATA,
    MSG_DATA_ACK,
    MSG_HELLO,
    MSG_HELLO_ACK,
    VERSION,
)
from vibesensor.app.config_defaults import DEFAULT_CONFIG
from vibesensor.shared.types.json_types import JsonObject


def render_contract_reference_markdown() -> str:
    """Render the public API contract reference as a Markdown string."""
    udp_raw = DEFAULT_CONFIG["udp"]
    srv_raw = DEFAULT_CONFIG["server"]
    assert isinstance(udp_raw, dict), "DEFAULT_CONFIG['udp'] must be a dict"
    assert isinstance(srv_raw, dict), "DEFAULT_CONFIG['server'] must be a dict"
    udp: JsonObject = udp_raw
    srv: JsonObject = srv_raw
    data_port = int(str(udp["data_port"]))
    control_port = int(str(udp["control_port"]))
    server_http_port = int(str(srv["port"]))

    # Canonical metric/report field names
    _metric_field_names = ["vibration_strength_db", "strength_bucket"]
    _report_field_names = [
        "run_id",
        "timestamp_utc",
        "client_id",
        "client_name",
        "speed_kmh",
        "dominant_freq_hz",
        "vibration_strength_db",
        "strength_bucket",
        "top_peaks",
    ]
    metric_fields = "\n".join(f"- `{key}`" for key in _metric_field_names)
    report_fields = "\n".join(f"- `{key}`" for key in _report_field_names)

    return f"""# Authoritative Protocol & Ports Contract

This document is generated from code and shared contract files.

- Regenerate with: `make sync-contracts`
- Source of truth:
  - `apps/server/vibesensor/adapters/udp/protocol.py`
  - `apps/server/vibesensor/app/settings.py`
  - `apps/server/vibesensor/contracts.py`

## Network contract

- HTTP API/UI server port: `{server_http_port}`
- UDP data ingest port: `{data_port}`
- UDP control/identify port: `{control_port}`

## Wire protocol version and message types

- Version: `{VERSION}`
- HELLO: `{MSG_HELLO}`
- DATA: `{MSG_DATA}`
- CMD: `{MSG_CMD}`
- ACK: `{MSG_ACK}`
- DATA_ACK: `{MSG_DATA_ACK}`
- HELLO_ACK: `{MSG_HELLO_ACK}`
- CMD identify id: `{CMD_IDENTIFY}`
- HELLO explicit-ack capability bit: `0x{HELLO_CAP_EXPLICIT_ACK:02x}`

## Wire packet byte sizes

- HELLO fixed bytes (without variable name/fw bytes): `{HELLO_FIXED_BYTES}`
- DATA header bytes (without sample payload): `{DATA_HEADER_BYTES}`
- CMD header bytes: `{CMD_HEADER_BYTES}`
- CMD identify bytes: `{CMD_IDENTIFY_BYTES}`
- ACK bytes: `{ACK_BYTES}`
- DATA_ACK bytes: `{DATA_ACK_BYTES}`
- HELLO_ACK bytes: `{HELLO_ACK_BYTES}`

## Hello handshake

- Capable firmware advertises support for explicit control-plane acknowledgment in
  the HELLO capability byte.
- Server replies to capable HELLO packets with `HELLO_ACK` on the sensor control port.
- Firmware waits for `HELLO_ACK` before sending DATA frames, so the control path
  is validated before streaming starts.

## Shared metric payload fields

{metric_fields}

## Shared report summary fields

{report_fields}
"""
