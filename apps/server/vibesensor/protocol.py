"""ESP32 UDP binary protocol — message encoding and decoding.

Defines the binary message format exchanged over UDP between the ESP32
sensor nodes and the VibeSensor server (Hello, Data, Cmd, Ack, DataAck).
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass

import numpy as np

LOGGER = logging.getLogger(__name__)

__all__ = [
    "AckMessage",
    "CmdMessage",
    "DataAckMessage",
    "DataMessage",
    "HelloMessage",
    "ProtocolError",
    "client_id_hex",
    "client_id_mac",
    "extract_client_id_hex",
    "pack_ack",
    "pack_cmd_identify",
    "pack_cmd_sync_clock",
    "pack_data",
    "pack_data_ack",
    "pack_hello",
    "parse_ack",
    "parse_client_id",
    "parse_cmd",
    "parse_data",
    "parse_data_ack",
    "parse_hello",
]

VERSION = 1
CLIENT_ID_BYTES = 6
CLIENT_ID_OFFSET = 2  # Byte offset of the client_id field in all message types.

MSG_HELLO = 1
MSG_DATA = 2
MSG_CMD = 3
MSG_ACK = 4
MSG_DATA_ACK = 5

CMD_IDENTIFY = 1
CMD_SYNC_CLOCK = 2

HELLO_BASE = struct.Struct("<BB6sHHHB")
DATA_HEADER = struct.Struct("<BB6sIQH")
ACK_STRUCT = struct.Struct("<BB6sIB")
DATA_ACK_STRUCT = struct.Struct("<BB6sI")
CMD_HEADER = struct.Struct("<BB6sBI")
CMD_IDENTIFY_STRUCT = struct.Struct("<BB6sBIH")
CMD_SYNC_CLOCK_STRUCT = struct.Struct("<BB6sBIQ")

HELLO_FIXED_BYTES = HELLO_BASE.size + 1 + 4  # +fw_len byte +overflow uint32
DATA_HEADER_BYTES: int = DATA_HEADER.size
ACK_BYTES: int = ACK_STRUCT.size
DATA_ACK_BYTES: int = DATA_ACK_STRUCT.size
CMD_HEADER_BYTES: int = CMD_HEADER.size
CMD_IDENTIFY_BYTES: int = CMD_IDENTIFY_STRUCT.size
CMD_SYNC_CLOCK_BYTES: int = CMD_SYNC_CLOCK_STRUCT.size

HELLO_MAX_NAME_BYTES: int = 32
"""Maximum length (in UTF-8 bytes) for the name and firmware_version fields
in HELLO messages.  ``pack_hello`` enforces this limit on the send path;
``parse_hello`` warns when an inbound message exceeds it (the value is still
accepted to preserve forward compatibility with future firmware)."""

# Pre-resolved dtype for the hot ingest path (parse_data / pack_data).
_SAMPLE_DTYPE = np.dtype("<i2")

ACCEL_AXES: int = 3
"""Number of accelerometer axes per sample (X, Y, Z)."""

BYTES_PER_SAMPLE: int = ACCEL_AXES * _SAMPLE_DTYPE.itemsize
"""Wire size of one accelerometer sample in bytes (3 axes × 2 bytes for int16)."""


class ProtocolError(ValueError):
    """Raised when a binary protocol message is malformed or unexpected."""


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


@dataclass(slots=True)
class DataAckMessage:
    """Decoded DATA_ACK message: data-receipt acknowledgment from server to sensor."""

    client_id: bytes
    last_seq_received: int


def client_id_hex(client_id: bytes) -> str:
    """Return the 6-byte *client_id* as a lowercase hex string."""
    if len(client_id) != 6:
        raise ValueError(f"client_id must be 6 bytes, got {len(client_id)}")
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
    if len(raw) != 6:
        raise ValueError(f"client_id must be 6 bytes, got {len(raw)}")
    return ":".join(f"{b:02x}" for b in raw)


def parse_client_id(client_id_text: str) -> bytes:
    """Parse a hex or colon-separated MAC string into 6 bytes."""
    compact = client_id_text.replace(":", "").strip().lower()
    if len(compact) != 12:
        raise ValueError("client_id must be 12 hex chars")
    return bytes.fromhex(compact)


def parse_hello(data: bytes) -> HelloMessage:
    """Decode a raw HELLO message into a :class:`HelloMessage`."""
    if len(data) < HELLO_BASE.size:
        raise ProtocolError("HELLO too short")
    (
        msg_type,
        version,
        client_id,
        control_port,
        sample_rate_hz,
        frame_samples,
        name_len,
    ) = HELLO_BASE.unpack_from(data, 0)
    if msg_type != MSG_HELLO or version != VERSION:
        raise ProtocolError("Invalid HELLO header")

    offset = HELLO_BASE.size
    if len(data) < offset + name_len:
        raise ProtocolError("HELLO missing name bytes")
    raw_name = data[offset : offset + name_len]
    offset += name_len
    if name_len > HELLO_MAX_NAME_BYTES:
        LOGGER.warning(
            "HELLO name field is %d bytes (max expected %d); accepting but truncating stored value",
            name_len,
            HELLO_MAX_NAME_BYTES,
        )
        raw_name = raw_name[:HELLO_MAX_NAME_BYTES]
    name = raw_name.decode("utf-8", errors="replace")

    firmware_version = ""
    queue_overflow_drops = 0
    if len(data) > offset:
        firmware_len = data[offset]
        offset += 1
        if len(data) < offset + firmware_len:
            raise ProtocolError("HELLO firmware length out of range")
        raw_fw = data[offset : offset + firmware_len]
        offset += firmware_len
        if firmware_len > HELLO_MAX_NAME_BYTES:
            LOGGER.warning(
                "HELLO firmware_version field is %d bytes (max expected %d); "
                "accepting but truncating stored value",
                firmware_len,
                HELLO_MAX_NAME_BYTES,
            )
            raw_fw = raw_fw[:HELLO_MAX_NAME_BYTES]
        firmware_version = raw_fw.decode("utf-8", errors="replace")
        if len(data) >= offset + 4:
            queue_overflow_drops = struct.unpack_from("<I", data, offset)[0]

    return HelloMessage(
        client_id=client_id,
        control_port=control_port,
        sample_rate_hz=sample_rate_hz,
        frame_samples=frame_samples,
        name=name,
        firmware_version=firmware_version,
        queue_overflow_drops=queue_overflow_drops,
    )


def pack_hello(
    client_id: bytes,
    control_port: int,
    sample_rate_hz: int,
    name: str,
    frame_samples: int = 0,
    firmware_version: str = "",
    queue_overflow_drops: int = 0,
) -> bytes:
    """Encode a HELLO message as bytes."""
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
    )


def parse_data(data: bytes) -> DataMessage:
    """Decode a raw DATA message into a :class:`DataMessage`."""
    if len(data) < DATA_HEADER_BYTES:
        raise ProtocolError("DATA too short")
    msg_type, version, client_id, seq, t0_us, sample_count = DATA_HEADER.unpack_from(data, 0)
    if msg_type != MSG_DATA or version != VERSION:
        raise ProtocolError("Invalid DATA header")

    # Reject unreasonably large frames before any allocation.  The ESP32
    # firmware sends at most ~200 samples per frame at 4096 Hz; 1024 gives
    # generous headroom while preventing accidental or malicious OOM.
    _MAX_SAMPLE_COUNT = 1024
    if sample_count > _MAX_SAMPLE_COUNT:
        raise ProtocolError(
            f"DATA sample_count {sample_count} exceeds maximum {_MAX_SAMPLE_COUNT}"
        )

    if sample_count == 0:
        raise ProtocolError("DATA sample_count must not be zero")
    payload_len = sample_count * BYTES_PER_SAMPLE
    expected_len = DATA_HEADER_BYTES + payload_len
    if len(data) != expected_len:
        raise ProtocolError(f"DATA payload size mismatch: expected {expected_len}, got {len(data)}")

    payload = memoryview(data)[DATA_HEADER_BYTES:]
    samples = np.frombuffer(payload, dtype=_SAMPLE_DTYPE).reshape(sample_count, ACCEL_AXES).copy()
    return DataMessage(
        client_id=client_id,
        seq=seq,
        t0_us=t0_us,
        sample_count=sample_count,
        samples=samples,
    )


def pack_data(client_id: bytes, seq: int, t0_us: int, samples: np.ndarray) -> bytes:
    """Encode a DATA message as bytes from an (N, 3) int16 samples array."""
    samples_int16 = np.asarray(samples, dtype=_SAMPLE_DTYPE)
    if samples_int16.ndim != 2 or samples_int16.shape[1] != ACCEL_AXES:
        raise ValueError(f"samples must be shaped (N, {ACCEL_AXES})")
    sample_count = int(samples_int16.shape[0])
    header = DATA_HEADER.pack(MSG_DATA, VERSION, client_id, seq, t0_us, sample_count)
    return header + samples_int16.tobytes(order="C")


def parse_cmd(data: bytes) -> CmdMessage:
    """Decode a raw CMD message into a :class:`CmdMessage`."""
    if len(data) < CMD_HEADER_BYTES:
        raise ProtocolError("CMD too short")
    msg_type, version, client_id, cmd_id, cmd_seq = CMD_HEADER.unpack_from(data, 0)
    if msg_type != MSG_CMD or version != VERSION:
        raise ProtocolError("Invalid CMD header")
    params = data[CMD_HEADER_BYTES:]
    return CmdMessage(client_id=client_id, cmd_id=cmd_id, cmd_seq=cmd_seq, params=params)


def pack_cmd_identify(client_id: bytes, cmd_seq: int, duration_ms: int) -> bytes:
    """Encode a CMD_IDENTIFY command as bytes."""
    return CMD_IDENTIFY_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_IDENTIFY,
        cmd_seq,
        max(1, min(60_000, int(duration_ms))),
    )


def pack_cmd_sync_clock(client_id: bytes, cmd_seq: int, server_time_us: int) -> bytes:
    """Encode a CMD_SYNC_CLOCK command as bytes."""
    return CMD_SYNC_CLOCK_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_SYNC_CLOCK,
        cmd_seq,
        max(0, int(server_time_us)),
    )


def parse_ack(data: bytes) -> AckMessage:
    """Decode a raw ACK message into an :class:`AckMessage`."""
    if len(data) != ACK_BYTES:
        raise ProtocolError("ACK has unexpected size")
    msg_type, version, client_id, cmd_seq, status = ACK_STRUCT.unpack_from(data, 0)
    if msg_type != MSG_ACK or version != VERSION:
        raise ProtocolError("Invalid ACK header")
    return AckMessage(client_id=client_id, cmd_seq=cmd_seq, status=status)


def pack_ack(client_id: bytes, cmd_seq: int, status: int = 0) -> bytes:
    """Encode an ACK message as bytes."""
    return ACK_STRUCT.pack(MSG_ACK, VERSION, client_id, cmd_seq, status & 0xFF)


def parse_data_ack(data: bytes) -> DataAckMessage:
    """Decode a raw DATA_ACK message into a :class:`DataAckMessage`."""
    if len(data) != DATA_ACK_BYTES:
        raise ProtocolError("DATA_ACK has unexpected size")
    msg_type, version, client_id, last_seq_received = DATA_ACK_STRUCT.unpack_from(data, 0)
    if msg_type != MSG_DATA_ACK or version != VERSION:
        raise ProtocolError("Invalid DATA_ACK header")
    return DataAckMessage(client_id=client_id, last_seq_received=last_seq_received)


def pack_data_ack(client_id: bytes, last_seq_received: int) -> bytes:
    """Encode a DATA_ACK message as bytes."""
    return DATA_ACK_STRUCT.pack(MSG_DATA_ACK, VERSION, client_id, last_seq_received & 0xFFFFFFFF)
