from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

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

HELLO_FIXED_BYTES = 1 + 1 + CLIENT_ID_BYTES + 2 + 2 + 2 + 1 + 1 + 4
DATA_HEADER_BYTES = 1 + 1 + CLIENT_ID_BYTES + 4 + 8 + 2
ACK_BYTES = 1 + 1 + CLIENT_ID_BYTES + 4 + 1
DATA_ACK_BYTES = 1 + 1 + CLIENT_ID_BYTES + 4
CMD_HEADER_BYTES = 1 + 1 + CLIENT_ID_BYTES + 1 + 4
CMD_IDENTIFY_BYTES = CMD_HEADER_BYTES + 2
CMD_SYNC_CLOCK_BYTES = CMD_HEADER_BYTES + 8


class ProtocolError(ValueError):
    pass


@dataclass(slots=True)
class HelloMessage:
    client_id: bytes
    control_port: int
    sample_rate_hz: int
    name: str
    firmware_version: str
    frame_samples: int = 0
    queue_overflow_drops: int = 0


@dataclass(slots=True)
class DataMessage:
    client_id: bytes
    seq: int
    t0_us: int
    sample_count: int
    samples: np.ndarray


@dataclass(slots=True)
class CmdMessage:
    client_id: bytes
    cmd_id: int
    cmd_seq: int
    params: bytes


@dataclass(slots=True)
class AckMessage:
    client_id: bytes
    cmd_seq: int
    status: int


@dataclass(slots=True)
class DataAckMessage:
    client_id: bytes
    last_seq_received: int


def client_id_hex(client_id: bytes) -> str:
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
    raw = parse_client_id(client_id) if isinstance(client_id, str) else client_id
    if len(raw) != 6:
        raise ValueError(f"client_id must be 6 bytes, got {len(raw)}")
    return ":".join(f"{b:02x}" for b in raw)


def parse_client_id(client_id_text: str) -> bytes:
    compact = client_id_text.replace(":", "").strip().lower()
    if len(compact) != 12:
        raise ValueError("client_id must be 12 hex chars")
    return bytes.fromhex(compact)


def parse_hello(data: bytes) -> HelloMessage:
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
    name = data[offset : offset + name_len].decode("utf-8", errors="replace")
    offset += name_len

    firmware_version = ""
    queue_overflow_drops = 0
    if len(data) > offset:
        firmware_len = data[offset]
        offset += 1
        if len(data) < offset + firmware_len:
            raise ProtocolError("HELLO firmware length out of range")
        firmware_version = data[offset : offset + firmware_len].decode("utf-8", errors="replace")
        offset += firmware_len
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
    name_bytes = name.encode("utf-8")[:32]
    fw_bytes = firmware_version.encode("utf-8")[:32]
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
    if len(data) < DATA_HEADER.size:
        raise ProtocolError("DATA too short")
    msg_type, version, client_id, seq, t0_us, sample_count = DATA_HEADER.unpack_from(data, 0)
    if msg_type != MSG_DATA or version != VERSION:
        raise ProtocolError("Invalid DATA header")

    payload_len = sample_count * 6
    expected_len = DATA_HEADER.size + payload_len
    if len(data) != expected_len:
        raise ProtocolError(f"DATA payload size mismatch: expected {expected_len}, got {len(data)}")

    payload = memoryview(data)[DATA_HEADER.size :]
    samples = np.frombuffer(payload, dtype="<i2").reshape(sample_count, 3).copy()
    return DataMessage(
        client_id=client_id,
        seq=seq,
        t0_us=t0_us,
        sample_count=sample_count,
        samples=samples,
    )


def pack_data(client_id: bytes, seq: int, t0_us: int, samples: np.ndarray) -> bytes:
    samples_int16 = np.asarray(samples, dtype="<i2")
    if samples_int16.ndim != 2 or samples_int16.shape[1] != 3:
        raise ValueError("samples must be shaped (N, 3)")
    sample_count = int(samples_int16.shape[0])
    header = DATA_HEADER.pack(MSG_DATA, VERSION, client_id, seq, t0_us, sample_count)
    return header + samples_int16.tobytes(order="C")


def parse_cmd(data: bytes) -> CmdMessage:
    if len(data) < CMD_HEADER.size:
        raise ProtocolError("CMD too short")
    msg_type, version, client_id, cmd_id, cmd_seq = CMD_HEADER.unpack_from(data, 0)
    if msg_type != MSG_CMD or version != VERSION:
        raise ProtocolError("Invalid CMD header")
    params = data[CMD_HEADER.size :]
    return CmdMessage(client_id=client_id, cmd_id=cmd_id, cmd_seq=cmd_seq, params=params)


def pack_cmd_identify(client_id: bytes, cmd_seq: int, duration_ms: int) -> bytes:
    return CMD_IDENTIFY_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_IDENTIFY,
        cmd_seq,
        max(1, min(60_000, int(duration_ms))),
    )


def pack_cmd_sync_clock(client_id: bytes, cmd_seq: int, server_time_us: int) -> bytes:
    return CMD_SYNC_CLOCK_STRUCT.pack(
        MSG_CMD,
        VERSION,
        client_id,
        CMD_SYNC_CLOCK,
        cmd_seq,
        max(0, int(server_time_us)),
    )


def parse_ack(data: bytes) -> AckMessage:
    if len(data) != ACK_STRUCT.size:
        raise ProtocolError("ACK has unexpected size")
    msg_type, version, client_id, cmd_seq, status = ACK_STRUCT.unpack_from(data, 0)
    if msg_type != MSG_ACK or version != VERSION:
        raise ProtocolError("Invalid ACK header")
    return AckMessage(client_id=client_id, cmd_seq=cmd_seq, status=status)


def pack_ack(client_id: bytes, cmd_seq: int, status: int = 0) -> bytes:
    return ACK_STRUCT.pack(MSG_ACK, VERSION, client_id, cmd_seq, status & 0xFF)


def parse_data_ack(data: bytes) -> DataAckMessage:
    if len(data) != DATA_ACK_STRUCT.size:
        raise ProtocolError("DATA_ACK has unexpected size")
    msg_type, version, client_id, last_seq_received = DATA_ACK_STRUCT.unpack_from(data, 0)
    if msg_type != MSG_DATA_ACK or version != VERSION:
        raise ProtocolError("Invalid DATA_ACK header")
    return DataAckMessage(client_id=client_id, last_seq_received=last_seq_received)


def pack_data_ack(client_id: bytes, last_seq_received: int) -> bytes:
    return DATA_ACK_STRUCT.pack(MSG_DATA_ACK, VERSION, client_id, last_seq_received & 0xFFFFFFFF)
