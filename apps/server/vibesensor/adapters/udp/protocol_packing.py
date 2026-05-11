"""UDP protocol byte encoders."""

from __future__ import annotations

import struct

import numpy as np

from vibesensor.adapters.udp.protocol_validator import (
    HELLO_MAX_NAME_BYTES,
    VERSION,
    validate_client_id,
    validate_cmd_seq,
    validate_samples_array,
)
from vibesensor.adapters.udp.protocol_wire import (
    ACK_STRUCT,
    ACK_SYNC_CLOCK_STRUCT,
    CMD_IDENTIFY,
    CMD_IDENTIFY_STRUCT,
    CMD_SYNC_CLOCK,
    CMD_SYNC_CLOCK_STRUCT,
    DATA_ACK_STRUCT,
    DATA_HEADER,
    HELLO_ACK_STRUCT,
    HELLO_BASE,
    HELLO_CAP_EXPLICIT_ACK,
    MSG_ACK,
    MSG_CMD,
    MSG_DATA,
    MSG_DATA_ACK,
    MSG_HELLO,
    MSG_HELLO_ACK,
    SAMPLE_DTYPE,
)


def pack_hello(
    client_id: bytes,
    control_port: int,
    sample_rate_hz: int,
    name: str,
    frame_samples: int = 0,
    firmware_version: str = "",
    queue_overflow_drops: int = 0,
    capabilities: int = HELLO_CAP_EXPLICIT_ACK,
) -> bytes:
    """Encode a HELLO message as bytes."""
    validate_client_id(client_id)
    name_bytes = name.encode("utf-8")[:HELLO_MAX_NAME_BYTES]
    fw_bytes = firmware_version.encode("utf-8")[:HELLO_MAX_NAME_BYTES]
    header = HELLO_BASE.pack(
        MSG_HELLO,
        VERSION,
        client_id,
        control_port,
        sample_rate_hz,
        frame_samples,
        len(name_bytes),
    )
    return (
        header
        + name_bytes
        + bytes([len(fw_bytes)])
        + fw_bytes
        + struct.pack("<I", int(max(0, queue_overflow_drops)))
        + bytes([capabilities & 0xFF])
    )


def pack_data(client_id: bytes, seq: int, t0_us: int, samples: np.ndarray) -> bytes:
    """Encode a DATA message as bytes from an (N, 3) int16 samples array."""
    samples_int16 = np.asarray(samples, dtype=SAMPLE_DTYPE)
    sample_count = validate_samples_array(samples_int16)
    header = DATA_HEADER.pack(MSG_DATA, VERSION, client_id, seq, t0_us, sample_count)
    return bytes(header + samples_int16.tobytes(order="C"))


def pack_cmd_identify(client_id: bytes, cmd_seq: int, duration_ms: int) -> bytes:
    """Encode a CMD_IDENTIFY command as bytes."""
    validate_cmd_seq(cmd_seq)
    return CMD_IDENTIFY_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_IDENTIFY,
        cmd_seq,
        max(1, min(60_000, int(duration_ms))),
    )


def pack_cmd_sync_clock(
    client_id: bytes,
    cmd_seq: int,
    server_time_us: int,
    *,
    applied_offset_us: int = 0,
    round_trip_us: int = 0,
) -> bytes:
    """Encode a CMD_SYNC_CLOCK command as bytes."""
    validate_cmd_seq(cmd_seq)
    clamped_offset_us = max(-(1 << 63), min((1 << 63) - 1, int(applied_offset_us)))
    return CMD_SYNC_CLOCK_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_SYNC_CLOCK,
        cmd_seq,
        max(0, int(server_time_us)),
        clamped_offset_us,
        max(0, min((1 << 32) - 1, int(round_trip_us))),
    )


def pack_hello_ack(client_id: bytes) -> bytes:
    """Encode a HELLO_ACK message as bytes."""
    validate_client_id(client_id)
    return HELLO_ACK_STRUCT.pack(MSG_HELLO_ACK, VERSION, client_id)


def pack_ack(client_id: bytes, cmd_seq: int, status: int = 0) -> bytes:
    """Encode an ACK message as bytes."""
    validate_cmd_seq(cmd_seq)
    return ACK_STRUCT.pack(MSG_ACK, VERSION, client_id, cmd_seq, status & 0xFF)


def pack_ack_sync_clock(
    client_id: bytes,
    cmd_seq: int,
    *,
    device_receive_us: int,
    device_send_us: int,
    status: int = 0,
) -> bytes:
    """Encode an ACK payload carrying sync-clock receive/send timestamps."""
    validate_cmd_seq(cmd_seq)
    return ACK_SYNC_CLOCK_STRUCT.pack(
        MSG_ACK,
        VERSION,
        client_id,
        cmd_seq,
        status & 0xFF,
        max(0, int(device_receive_us)),
        max(0, int(device_send_us)),
    )


def pack_data_ack(client_id: bytes, last_seq_received: int) -> bytes:
    """Encode a DATA_ACK message as bytes."""
    return DATA_ACK_STRUCT.pack(MSG_DATA_ACK, VERSION, client_id, last_seq_received & 0xFFFFFFFF)
