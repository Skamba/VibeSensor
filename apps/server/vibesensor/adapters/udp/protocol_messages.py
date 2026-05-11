"""UDP protocol message DTOs and client-id helpers."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from vibesensor.adapters.udp.protocol_validator import CLIENT_ID_BYTES, validate_client_id
from vibesensor.adapters.udp.protocol_wire import CLIENT_ID_OFFSET


@dataclass(slots=True)
class HelloMessage:
    """Decoded HELLO message sent by an ESP32 sensor on connect."""

    client_id: bytes
    control_port: int
    sample_rate_hz: int
    name: str
    firmware_version: str
    frame_samples: int = 0
    queue_overflow_drops: int = 0
    capabilities: int = 0


@dataclass(slots=True)
class DataMessage:
    """Decoded DATA message containing one frame of accelerometer samples."""

    client_id: bytes
    seq: int
    t0_us: int
    sample_count: int
    samples: np.ndarray


@dataclass(slots=True)
class CmdMessage:
    """Decoded CMD message: a command sent from server to a sensor node."""

    client_id: bytes
    cmd_id: int
    cmd_seq: int
    params: bytes


@dataclass(slots=True)
class AckMessage:
    """Decoded ACK message: a command acknowledgment sent by a sensor node."""

    client_id: bytes
    cmd_seq: int
    status: int
    device_receive_us: int | None = None
    device_send_us: int | None = None


@dataclass(slots=True)
class DataAckMessage:
    """Decoded DATA_ACK message: data-receipt acknowledgment from server to sensor."""

    client_id: bytes
    last_seq_received: int


@dataclass(slots=True)
class HelloAckMessage:
    """Decoded HELLO_ACK message: server acknowledgment of HELLO receipt."""

    client_id: bytes


def client_id_hex(client_id: bytes) -> str:
    """Return the 6-byte *client_id* as a lowercase hex string."""
    validate_client_id(client_id)
    return client_id.hex()


def extract_client_id_hex(data: bytes) -> str | None:
    """Extract client_id as hex string from a raw protocol message, or None."""
    end = CLIENT_ID_OFFSET + CLIENT_ID_BYTES
    if len(data) < end:
        return None
    return data[CLIENT_ID_OFFSET:end].hex()


def client_id_mac(client_id: bytes | str) -> str:
    """Return *client_id* formatted as a colon-separated MAC address string."""
    raw = parse_client_id(client_id) if isinstance(client_id, str) else client_id
    validate_client_id(raw)
    return ":".join(f"{b:02x}" for b in raw)


def parse_client_id(client_id_text: str) -> bytes:
    """Parse a hex or colon-separated MAC string into 6 bytes."""
    compact = client_id_text.replace(":", "").strip().lower()
    if len(compact) != 12:
        raise ValueError("client_id must be 12 hex chars")
    return bytes.fromhex(compact)
