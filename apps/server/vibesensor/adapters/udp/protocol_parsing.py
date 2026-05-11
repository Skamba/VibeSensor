"""UDP protocol byte decoders and parse diagnostics."""

from __future__ import annotations

import logging
import struct
from typing import cast

import numpy as np

from vibesensor.adapters.udp.protocol_messages import (
    AckMessage,
    CmdMessage,
    DataAckMessage,
    DataMessage,
    HelloAckMessage,
    HelloMessage,
)
from vibesensor.adapters.udp.protocol_validator import (
    ACCEL_AXES,
    HELLO_MAX_NAME_BYTES,
    validate_data_frame,
    validate_fixed_message_size,
    validate_header,
    validate_hello_sample_rate,
    validate_minimum_size,
)
from vibesensor.adapters.udp.protocol_wire import (
    ACK_BYTES,
    ACK_STRUCT,
    ACK_SYNC_CLOCK_BYTES,
    BYTES_PER_SAMPLE,
    CMD_HEADER,
    CMD_HEADER_BYTES,
    CMD_IDENTIFY,
    CMD_SYNC_CLOCK,
    DATA_ACK_BYTES,
    DATA_ACK_STRUCT,
    DATA_HEADER,
    DATA_HEADER_BYTES,
    HELLO_ACK_BYTES,
    HELLO_ACK_STRUCT,
    HELLO_BASE,
    MSG_ACK,
    MSG_CMD,
    MSG_DATA,
    MSG_DATA_ACK,
    MSG_HELLO,
    MSG_HELLO_ACK,
    SAMPLE_DTYPE,
)
from vibesensor.shared.exceptions import ProtocolError as _ProtocolError

LOGGER = logging.getLogger("vibesensor.adapters.udp.protocol")


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

    samples = np.frombuffer(
        data,
        dtype=SAMPLE_DTYPE,
        count=sample_count * ACCEL_AXES,
        offset=DATA_HEADER_BYTES,
    ).reshape(sample_count, ACCEL_AXES)
    samples.setflags(write=False)
    return DataMessage(
        client_id=client_id,
        seq=seq,
        t0_us=t0_us,
        sample_count=sample_count,
        samples=samples,
    )


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


def parse_ack(data: bytes) -> AckMessage:
    """Decode a raw ACK message into an :class:`AckMessage`."""
    validate_minimum_size(label="ACK", data_length=len(data), minimum=ACK_BYTES)
    if len(data) not in (ACK_BYTES, ACK_SYNC_CLOCK_BYTES):
        raise _ProtocolError(
            "ACK has unexpected size "
            f"{len(data)} bytes (expected {ACK_BYTES} or {ACK_SYNC_CLOCK_BYTES})"
        )
    header = ACK_STRUCT.unpack_from(data, 0)
    _validate_unpacked_header(
        label="ACK",
        header_fields=header,
        expected_msg_type=MSG_ACK,
    )
    _msg_type, _version, client_id, cmd_seq, status = header
    if len(data) == ACK_SYNC_CLOCK_BYTES:
        device_receive_us, device_send_us = struct.unpack_from("<QQ", data, ACK_BYTES)
        return AckMessage(
            client_id=client_id,
            cmd_seq=cmd_seq,
            status=status,
            device_receive_us=device_receive_us,
            device_send_us=device_send_us,
        )
    return AckMessage(client_id=client_id, cmd_seq=cmd_seq, status=status)


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
