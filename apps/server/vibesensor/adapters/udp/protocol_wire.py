"""UDP protocol wire constants and binary layouts."""

from __future__ import annotations

import struct

import numpy as np

from vibesensor.adapters.udp import protocol_validator as _protocol_validator

VERSION: int = _protocol_validator.VERSION

MSG_HELLO = 1
MSG_DATA = 2
MSG_CMD = 3
MSG_ACK = 4
MSG_DATA_ACK = 5
MSG_HELLO_ACK = 6

HELLO_CAP_EXPLICIT_ACK = 1 << 0

CMD_IDENTIFY = 1
CMD_SYNC_CLOCK = 2

CLIENT_ID_OFFSET = 2

HELLO_BASE = struct.Struct("<BB6sHHHB")
DATA_HEADER = struct.Struct("<BB6sIQH")
ACK_STRUCT = struct.Struct("<BB6sIB")
ACK_SYNC_CLOCK_STRUCT = struct.Struct("<BB6sIBQQ")
DATA_ACK_STRUCT = struct.Struct("<BB6sI")
HELLO_ACK_STRUCT = struct.Struct("<BB6s")
CMD_HEADER = struct.Struct("<BB6sBI")
CMD_IDENTIFY_STRUCT = struct.Struct("<BB6sBIH")
CMD_SYNC_CLOCK_STRUCT = struct.Struct("<BB6sBIQqI")

HELLO_FIXED_BYTES = HELLO_BASE.size + 1 + 4 + 1
DATA_HEADER_BYTES: int = DATA_HEADER.size
ACK_BYTES: int = ACK_STRUCT.size
ACK_SYNC_CLOCK_BYTES: int = ACK_SYNC_CLOCK_STRUCT.size
DATA_ACK_BYTES: int = DATA_ACK_STRUCT.size
HELLO_ACK_BYTES: int = HELLO_ACK_STRUCT.size
CMD_HEADER_BYTES: int = CMD_HEADER.size
CMD_IDENTIFY_BYTES: int = CMD_IDENTIFY_STRUCT.size
CMD_SYNC_CLOCK_BYTES: int = CMD_SYNC_CLOCK_STRUCT.size

SAMPLE_DTYPE = np.dtype("<i2")
BYTES_PER_SAMPLE: int = _protocol_validator.ACCEL_AXES * SAMPLE_DTYPE.itemsize
