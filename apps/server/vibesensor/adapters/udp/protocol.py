"""ESP32 UDP binary protocol — message encoding and decoding.

Defines the binary message format exchanged over UDP between the ESP32
sensor nodes and the VibeSensor server (Hello, Data, Cmd, Ack, DataAck).
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import cast

import numpy as np

from vibesensor.adapters.udp.protocol_validator import (
    ACCEL_AXES,
    CLIENT_ID_BYTES,
    HELLO_MAX_NAME_BYTES,
    VERSION,
    validate_client_id,
    validate_cmd_seq,
    validate_data_frame,
    validate_fixed_message_size,
    validate_header,
    validate_hello_sample_rate,
    validate_minimum_size,
    validate_samples_array,
)
from vibesensor.shared.exceptions import ProtocolError as _ProtocolError

LOGGER = logging.getLogger(__name__)

__all__ = [
    "AckMessage",
    "CmdMessage",
    "DataAckMessage",
    "DataMessage",
    "HELLO_ACK_BYTES",
    "HELLO_CAP_EXPLICIT_ACK",
    "HelloMessage",
    "HelloAckMessage",
    "client_id_hex",
    "client_id_mac",
    "extract_client_id_hex",
    "pack_ack",
    "pack_cmd_identify",
    "pack_cmd_sync_clock",
    "pack_data",
    "pack_data_ack",
    "pack_hello",
    "pack_hello_ack",
    "parse_ack",
    "parse_client_id",
    "parse_cmd",
    "parse_data",
    "parse_data_ack",
    "parse_hello",
    "parse_hello_ack",
]

CLIENT_ID_OFFSET = 2  # Byte offset of the client_id field in all message types.

MSG_HELLO = 1
MSG_DATA = 2
MSG_CMD = 3
MSG_ACK = 4
MSG_DATA_ACK = 5
MSG_HELLO_ACK = 6

HELLO_CAP_EXPLICIT_ACK = 1 << 0

CMD_IDENTIFY = 1
CMD_SYNC_CLOCK = 2

HELLO_BASE = struct.Struct("<BB6sHHHB")
DATA_HEADER = struct.Struct("<BB6sIQH")
ACK_STRUCT = struct.Struct("<BB6sIB")
DATA_ACK_STRUCT = struct.Struct("<BB6sI")
HELLO_ACK_STRUCT = struct.Struct("<BB6s")
CMD_HEADER = struct.Struct("<BB6sBI")
CMD_IDENTIFY_STRUCT = struct.Struct("<BB6sBIH")
CMD_SYNC_CLOCK_STRUCT = struct.Struct("<BB6sBIQ")

HELLO_FIXED_BYTES = HELLO_BASE.size + 1 + 4 + 1  # +fw_len byte +overflow uint32 +capabilities
DATA_HEADER_BYTES: int = DATA_HEADER.size
ACK_BYTES: int = ACK_STRUCT.size
DATA_ACK_BYTES: int = DATA_ACK_STRUCT.size
HELLO_ACK_BYTES: int = HELLO_ACK_STRUCT.size
CMD_HEADER_BYTES: int = CMD_HEADER.size
CMD_IDENTIFY_BYTES: int = CMD_IDENTIFY_STRUCT.size
CMD_SYNC_CLOCK_BYTES: int = CMD_SYNC_CLOCK_STRUCT.size

# Pre-resolved dtype for the hot ingest path (parse_data / pack_data).
_SAMPLE_DTYPE = np.dtype("<i2")

BYTES_PER_SAMPLE: int = ACCEL_AXES * _SAMPLE_DTYPE.itemsize
"""Wire size of one accelerometer sample in bytes (3 axes × 2 bytes for int16)."""


def _validate_unpacked_header(
    *,
    label: str,
    header_fields: tuple[object, ...],
    expected_msg_type: int,
) -> None:
    validate_header(
        label=label,
        msg_type=cast(int, header_fields[0]),
        expected_msg_type=expected_msg_type,
        version=cast(int, header_fields[1]),
    )


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


def parse_hello(data: bytes) -> HelloMessage:
    """Decode a raw HELLO message into a :class:`HelloMessage`."""
    validate_minimum_size(label="HELLO", data_length=len(data), minimum=HELLO_BASE.size)
    header = HELLO_BASE.unpack_from(data, 0)
    _validate_unpacked_header(
        label="HELLO",
        header_fields=header,
        expected_msg_type=MSG_HELLO,
    )
    (
        _msg_type,
        _version,
        client_id,
        control_port,
        sample_rate_hz,
        frame_samples,
        name_len,
    ) = header
    validate_hello_sample_rate(sample_rate_hz)

    if control_port == 0:
        LOGGER.warning("HELLO control_port is 0; sensor may not be reachable for commands")

    offset = HELLO_BASE.size
    if len(data) < offset + name_len:
        raise _ProtocolError("HELLO missing name bytes")
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

    if len(data) < offset + 1:
        raise _ProtocolError("HELLO missing firmware length")
    firmware_len = data[offset]
    offset += 1
    if len(data) < offset + firmware_len:
        raise _ProtocolError("HELLO firmware length out of range")
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
    if len(data) < offset + 4:
        raise _ProtocolError("HELLO missing queue_overflow_drops")
    queue_overflow_drops = struct.unpack_from("<I", data, offset)[0]
    offset += 4
    if len(data) < offset + 1:
        raise _ProtocolError("HELLO missing capabilities")
    capabilities = data[offset]

    return HelloMessage(
        client_id=client_id,
        control_port=control_port,
        sample_rate_hz=sample_rate_hz,
        frame_samples=frame_samples,
        name=name,
        firmware_version=firmware_version,
        queue_overflow_drops=queue_overflow_drops,
        capabilities=capabilities,
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


def parse_data(data: bytes) -> DataMessage:
    """Decode a raw DATA message into a :class:`DataMessage`."""
    validate_minimum_size(label="DATA", data_length=len(data), minimum=DATA_HEADER_BYTES)
    header = DATA_HEADER.unpack_from(data, 0)
    _validate_unpacked_header(
        label="DATA",
        header_fields=header,
        expected_msg_type=MSG_DATA,
    )
    _msg_type, _version, client_id, seq, t0_us, sample_count = header
    validate_data_frame(
        sample_count=sample_count,
        data_length=len(data),
        header_bytes=DATA_HEADER_BYTES,
        bytes_per_sample=BYTES_PER_SAMPLE,
    )

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
    sample_count = validate_samples_array(samples_int16)
    header = DATA_HEADER.pack(MSG_DATA, VERSION, client_id, seq, t0_us, sample_count)
    return bytes(header + samples_int16.tobytes(order="C"))


def parse_cmd(data: bytes) -> CmdMessage:
    """Decode a raw CMD message into a :class:`CmdMessage`."""
    validate_minimum_size(label="CMD", data_length=len(data), minimum=CMD_HEADER_BYTES)
    header = CMD_HEADER.unpack_from(data, 0)
    _validate_unpacked_header(
        label="CMD",
        header_fields=header,
        expected_msg_type=MSG_CMD,
    )
    _msg_type, _version, client_id, cmd_id, cmd_seq = header
    if cmd_id not in (CMD_IDENTIFY, CMD_SYNC_CLOCK):
        raise _ProtocolError(f"CMD has unsupported cmd_id={cmd_id}")
    params = data[CMD_HEADER_BYTES:]
    return CmdMessage(client_id=client_id, cmd_id=cmd_id, cmd_seq=cmd_seq, params=params)


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


def pack_cmd_sync_clock(client_id: bytes, cmd_seq: int, server_time_us: int) -> bytes:
    """Encode a CMD_SYNC_CLOCK command as bytes."""
    validate_cmd_seq(cmd_seq)
    return CMD_SYNC_CLOCK_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_SYNC_CLOCK,
        cmd_seq,
        max(0, int(server_time_us)),
    )


def parse_hello_ack(data: bytes) -> HelloAckMessage:
    """Decode a raw HELLO_ACK message into a :class:`HelloAckMessage`."""
    validate_fixed_message_size(
        label="HELLO_ACK", data_length=len(data), expected_size=HELLO_ACK_BYTES
    )
    header = HELLO_ACK_STRUCT.unpack_from(data, 0)
    _validate_unpacked_header(
        label="HELLO_ACK",
        header_fields=header,
        expected_msg_type=MSG_HELLO_ACK,
    )
    _msg_type, _version, client_id = header
    return HelloAckMessage(client_id=client_id)


def pack_hello_ack(client_id: bytes) -> bytes:
    """Encode a HELLO_ACK message as bytes."""
    validate_client_id(client_id)
    return HELLO_ACK_STRUCT.pack(MSG_HELLO_ACK, VERSION, client_id)


def parse_ack(data: bytes) -> AckMessage:
    """Decode a raw ACK message into an :class:`AckMessage`."""
    validate_fixed_message_size(label="ACK", data_length=len(data), expected_size=ACK_BYTES)
    header = ACK_STRUCT.unpack_from(data, 0)
    _validate_unpacked_header(
        label="ACK",
        header_fields=header,
        expected_msg_type=MSG_ACK,
    )
    _msg_type, _version, client_id, cmd_seq, status = header
    return AckMessage(client_id=client_id, cmd_seq=cmd_seq, status=status)


def pack_ack(client_id: bytes, cmd_seq: int, status: int = 0) -> bytes:
    """Encode an ACK message as bytes."""
    validate_cmd_seq(cmd_seq)
    return ACK_STRUCT.pack(MSG_ACK, VERSION, client_id, cmd_seq, status & 0xFF)


def parse_data_ack(data: bytes) -> DataAckMessage:
    """Decode a raw DATA_ACK message into a :class:`DataAckMessage`."""
    validate_fixed_message_size(
        label="DATA_ACK", data_length=len(data), expected_size=DATA_ACK_BYTES
    )
    header = DATA_ACK_STRUCT.unpack_from(data, 0)
    _validate_unpacked_header(
        label="DATA_ACK",
        header_fields=header,
        expected_msg_type=MSG_DATA_ACK,
    )
    _msg_type, _version, client_id, last_seq_received = header
    return DataAckMessage(client_id=client_id, last_seq_received=last_seq_received)


def pack_data_ack(client_id: bytes, last_seq_received: int) -> bytes:
    """Encode a DATA_ACK message as bytes."""
    return DATA_ACK_STRUCT.pack(MSG_DATA_ACK, VERSION, client_id, last_seq_received & 0xFFFFFFFF)
