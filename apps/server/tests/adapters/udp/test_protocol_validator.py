"""Tests for protocol_validator: payload validation independent of byte packing."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from vibesensor.adapters.udp.protocol_validator import (
    ACCEL_AXES,
    CLIENT_ID_BYTES,
    MAX_SAMPLE_COUNT,
    VERSION,
    ProtocolVersionMismatch,
    validate_client_id,
    validate_cmd_seq,
    validate_data_frame,
    validate_fixed_message_size,
    validate_header,
    validate_hello_sample_rate,
    validate_minimum_size,
    validate_samples_array,
)
from vibesensor.shared.exceptions import ProtocolError


def _validate_header_example() -> None:
    validate_header(label="TEST", msg_type=1, expected_msg_type=1, version=VERSION)


def _validate_data_frame_example() -> None:
    validate_data_frame(
        sample_count=10,
        data_length=20 + 10 * 6,
        header_bytes=20,
        bytes_per_sample=6,
    )


def _validate_fixed_message_size_example() -> None:
    validate_fixed_message_size(label="ACK", data_length=10, expected_size=10)


def _validate_cmd_seq_examples() -> None:
    validate_cmd_seq(0)
    validate_cmd_seq(42)


@pytest.mark.parametrize(
    "validate",
    [
        _validate_header_example,
        _validate_data_frame_example,
        lambda: validate_hello_sample_rate(200),
        _validate_fixed_message_size_example,
        lambda: validate_minimum_size(label="HELLO", data_length=20, minimum=15),
        lambda: validate_client_id(b"\x01\x02\x03\x04\x05\x06"),
        _validate_cmd_seq_examples,
    ],
    ids=[
        "header",
        "data-frame",
        "hello-sample-rate",
        "fixed-size",
        "minimum-size",
        "client-id",
        "cmd-seq",
    ],
)
def test_protocol_validator_accepts_valid_inputs(validate: Callable[[], None]) -> None:
    validate()


class TestValidateHeader:
    def test_wrong_msg_type(self) -> None:
        with pytest.raises(ProtocolError, match="Invalid TEST header"):
            validate_header(label="TEST", msg_type=2, expected_msg_type=1, version=VERSION)

    def test_wrong_version(self) -> None:
        with pytest.raises(ProtocolVersionMismatch) as exc_info:
            validate_header(label="DATA", msg_type=2, expected_msg_type=2, version=99)
        assert exc_info.value.expected_version == VERSION
        assert exc_info.value.actual_version == 99


class TestValidateDataFrame:
    def test_sample_count_exceeds_max(self) -> None:
        with pytest.raises(ProtocolError, match="exceeds maximum"):
            validate_data_frame(
                sample_count=MAX_SAMPLE_COUNT + 1,
                data_length=20 + (MAX_SAMPLE_COUNT + 1) * 6,
                header_bytes=20,
                bytes_per_sample=6,
            )

    def test_sample_count_zero(self) -> None:
        with pytest.raises(ProtocolError, match="must not be zero"):
            validate_data_frame(
                sample_count=0,
                data_length=20,
                header_bytes=20,
                bytes_per_sample=6,
            )

    def test_payload_size_mismatch(self) -> None:
        with pytest.raises(ProtocolError, match="payload size mismatch"):
            validate_data_frame(
                sample_count=10,
                data_length=100,
                header_bytes=20,
                bytes_per_sample=6,
            )


class TestValidateHelloSampleRate:
    def test_zero_rate(self) -> None:
        with pytest.raises(ProtocolError, match="must not be zero"):
            validate_hello_sample_rate(0)


class TestValidateFixedMessageSize:
    def test_wrong_size(self) -> None:
        with pytest.raises(ProtocolError, match="ACK has unexpected size"):
            validate_fixed_message_size(label="ACK", data_length=8, expected_size=10)


class TestValidateMinimumSize:
    def test_too_short(self) -> None:
        with pytest.raises(ProtocolError, match="HELLO too short"):
            validate_minimum_size(label="HELLO", data_length=5, minimum=15)


class TestValidateClientId:
    def test_wrong_length(self) -> None:
        with pytest.raises(ValueError, match=f"{CLIENT_ID_BYTES} bytes"):
            validate_client_id(b"\x01\x02\x03")


class TestValidateCmdSeq:
    def test_negative_seq(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            validate_cmd_seq(-1)


class TestValidateSamplesArray:
    def test_valid_array(self) -> None:
        samples = np.zeros((10, ACCEL_AXES), dtype=np.int16)
        assert validate_samples_array(samples) == 10

    def test_wrong_shape(self) -> None:
        samples = np.zeros((10, 2), dtype=np.int16)
        with pytest.raises(ValueError, match=f"shaped \\(N, {ACCEL_AXES}\\)"):
            validate_samples_array(samples)

    def test_empty_array(self) -> None:
        samples = np.zeros((0, ACCEL_AXES), dtype=np.int16)
        with pytest.raises(ValueError, match="must not be empty"):
            validate_samples_array(samples)

    def test_1d_array(self) -> None:
        samples = np.zeros(10, dtype=np.int16)
        with pytest.raises(ValueError, match=f"shaped \\(N, {ACCEL_AXES}\\)"):
            validate_samples_array(samples)
