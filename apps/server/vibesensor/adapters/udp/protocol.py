"""Stable UDP protocol facade for message DTOs, packing, and parsing."""

from __future__ import annotations

from vibesensor.adapters.udp import protocol_wire as _wire
from vibesensor.adapters.udp.protocol_messages import (
    AckMessage,
    CmdMessage,
    DataAckMessage,
    DataMessage,
    HelloAckMessage,
    HelloMessage,
    client_id_hex,
    client_id_mac,
    extract_client_id_hex,
    parse_client_id,
)
from vibesensor.adapters.udp.protocol_packing import (
    pack_ack,
    pack_ack_sync_clock,
    pack_cmd_identify,
    pack_cmd_sync_clock,
    pack_data,
    pack_data_ack,
    pack_hello,
    pack_hello_ack,
)
from vibesensor.adapters.udp.protocol_parsing import (
    parse_ack,
    parse_cmd,
    parse_data,
    parse_data_ack,
    parse_hello,
    parse_hello_ack,
)
from vibesensor.adapters.udp.protocol_wire import (
    ACK_SYNC_CLOCK_BYTES,
    ACK_SYNC_CLOCK_STRUCT,
    HELLO_ACK_BYTES,
    HELLO_CAP_EXPLICIT_ACK,
)

ACK_BYTES = _wire.ACK_BYTES
ACK_STRUCT = _wire.ACK_STRUCT
BYTES_PER_SAMPLE = _wire.BYTES_PER_SAMPLE
CLIENT_ID_OFFSET = _wire.CLIENT_ID_OFFSET
CMD_HEADER = _wire.CMD_HEADER
CMD_HEADER_BYTES = _wire.CMD_HEADER_BYTES
CMD_IDENTIFY = _wire.CMD_IDENTIFY
CMD_IDENTIFY_BYTES = _wire.CMD_IDENTIFY_BYTES
CMD_IDENTIFY_STRUCT = _wire.CMD_IDENTIFY_STRUCT
CMD_SYNC_CLOCK = _wire.CMD_SYNC_CLOCK
CMD_SYNC_CLOCK_BYTES = _wire.CMD_SYNC_CLOCK_BYTES
CMD_SYNC_CLOCK_STRUCT = _wire.CMD_SYNC_CLOCK_STRUCT
DATA_ACK_BYTES = _wire.DATA_ACK_BYTES
DATA_ACK_STRUCT = _wire.DATA_ACK_STRUCT
DATA_HEADER = _wire.DATA_HEADER
DATA_HEADER_BYTES = _wire.DATA_HEADER_BYTES
HELLO_ACK_STRUCT = _wire.HELLO_ACK_STRUCT
HELLO_BASE = _wire.HELLO_BASE
HELLO_FIXED_BYTES = _wire.HELLO_FIXED_BYTES
MSG_ACK = _wire.MSG_ACK
MSG_CMD = _wire.MSG_CMD
MSG_DATA = _wire.MSG_DATA
MSG_DATA_ACK = _wire.MSG_DATA_ACK
MSG_HELLO = _wire.MSG_HELLO
MSG_HELLO_ACK = _wire.MSG_HELLO_ACK
VERSION = _wire.VERSION

__all__ = [
    "AckMessage",
    "ACK_SYNC_CLOCK_BYTES",
    "ACK_SYNC_CLOCK_STRUCT",
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
    "pack_ack_sync_clock",
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
