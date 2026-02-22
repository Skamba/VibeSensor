from __future__ import annotations

from vibesensor_shared.contracts import METRIC_FIELDS, REPORT_FIELDS

from vibesensor.config import DEFAULT_CONFIG
from vibesensor.protocol import (
    ACK_BYTES,
    CMD_HEADER_BYTES,
    CMD_IDENTIFY,
    CMD_IDENTIFY_BYTES,
    DATA_ACK_BYTES,
    DATA_HEADER_BYTES,
    HELLO_FIXED_BYTES,
    MSG_ACK,
    MSG_CMD,
    MSG_DATA,
    MSG_DATA_ACK,
    MSG_HELLO,
    VERSION,
)


def _port(value: str) -> int:
    return int(str(value).rsplit(":", 1)[-1])


def render_contract_reference_markdown() -> str:
    data_port = _port(str(DEFAULT_CONFIG["udp"]["data_listen"]))
    control_port = _port(str(DEFAULT_CONFIG["udp"]["control_listen"]))
    server_http_port = int(DEFAULT_CONFIG["server"]["port"])

    metric_fields = "\n".join(f"- `{key}`" for key in METRIC_FIELDS)
    report_fields = "\n".join(f"- `{key}`" for key in REPORT_FIELDS)

    return f"""# Authoritative Protocol & Ports Contract

This document is generated from code and shared contract files.

- Regenerate with: `python3 tools/config/generate_contract_reference_doc.py`
- Source of truth:
  - `apps/server/vibesensor/protocol.py`
  - `apps/server/vibesensor/config.py`
  - `libs/shared/contracts/metrics_fields.json`
  - `libs/shared/contracts/report_fields.json`

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
- CMD identify id: `{CMD_IDENTIFY}`

## Wire packet byte sizes

- HELLO fixed bytes (without variable name/fw bytes): `{HELLO_FIXED_BYTES}`
- DATA header bytes (without sample payload): `{DATA_HEADER_BYTES}`
- CMD header bytes: `{CMD_HEADER_BYTES}`
- CMD identify bytes: `{CMD_IDENTIFY_BYTES}`
- ACK bytes: `{ACK_BYTES}`
- DATA_ACK bytes: `{DATA_ACK_BYTES}`

## Shared metric payload fields

{metric_fields}

## Shared report summary fields

{report_fields}
"""
