"""UDP protocol payload validation helpers.

Extracted from ``protocol.py`` so wire-shape rules, version checks,
and field constraints are independently testable and separate from
binary packing and unpacking.
"""

from __future__ import annotations

import numpy as np

from vibesensor.shared.exceptions import ProtocolError

VERSION = 1
CLIENT_ID_BYTES = 6
HELLO_MAX_NAME_BYTES: int = 32
MAX_SAMPLE_COUNT: int = 1024
ACCEL_AXES: int = 3


class ProtocolVersionMismatch(ProtocolError):
    """Protocol error raised when a packet uses an unsupported wire version."""

    def __init__(self, *, label: str, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"{label} version mismatch: expected {expected_version}, got {actual_version}",
        )
        self.label = label
        self.expected_version = expected_version
        self.actual_version = actual_version


def validate_header(
    *,
    label: str,
    msg_type: int,
    expected_msg_type: int,
    version: int,
) -> None:
    """Validate message type and wire version after unpacking a header."""
    if msg_type != expected_msg_type:
        raise ProtocolError(f"Invalid {label} header")
    if version != VERSION:
        raise ProtocolVersionMismatch(
            label=label,
            expected_version=VERSION,
            actual_version=version,
        )


def validate_data_frame(
    *,
    sample_count: int,
    data_length: int,
    header_bytes: int,
    bytes_per_sample: int,
) -> None:
    """Validate DATA message sample count and payload size."""
    if sample_count > MAX_SAMPLE_COUNT:
        raise ProtocolError(f"DATA sample_count {sample_count} exceeds maximum {MAX_SAMPLE_COUNT}")
    if sample_count == 0:
        raise ProtocolError("DATA sample_count must not be zero")
    expected_len = header_bytes + sample_count * bytes_per_sample
    if data_length != expected_len:
        raise ProtocolError(
            f"DATA payload size mismatch: expected {expected_len}, got {data_length}"
        )


def validate_hello_sample_rate(sample_rate_hz: int) -> None:
    """Raise if HELLO sample_rate_hz is zero."""
    if sample_rate_hz == 0:
        raise ProtocolError("HELLO sample_rate_hz must not be zero")


def validate_fixed_message_size(*, label: str, data_length: int, expected_size: int) -> None:
    """Raise if a fixed-size message has an unexpected length."""
    if data_length != expected_size:
        raise ProtocolError(f"{label} has unexpected size")


def validate_minimum_size(*, label: str, data_length: int, minimum: int) -> None:
    """Raise if a message is shorter than its minimum header size."""
    if data_length < minimum:
        raise ProtocolError(f"{label} too short")


def validate_client_id(client_id: bytes) -> None:
    """Raise if *client_id* is not exactly 6 bytes."""
    if len(client_id) != CLIENT_ID_BYTES:
        raise ValueError(f"client_id must be {CLIENT_ID_BYTES} bytes, got {len(client_id)}")


def validate_cmd_seq(cmd_seq: int) -> None:
    """Raise if *cmd_seq* is negative."""
    if cmd_seq < 0:
        raise ValueError(f"cmd_seq must be non-negative, got {cmd_seq}")


def validate_samples_array(samples: np.ndarray) -> int:
    """Validate the samples array for pack_data and return sample_count."""
    if samples.ndim != 2 or samples.shape[1] != ACCEL_AXES:
        raise ValueError(f"samples must be shaped (N, {ACCEL_AXES})")
    count = int(samples.shape[0])
    if count == 0:
        raise ValueError("pack_data: samples array must not be empty (sample_count must be > 0)")
    return count
