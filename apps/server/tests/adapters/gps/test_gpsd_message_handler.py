"""Tests for GPSD message classification and field extraction."""

from __future__ import annotations

import math

from vibesensor.adapters.gps.gpsd_message_handler import (
    GpsdVersionInfo,
    NormalizedTpvData,
    classify_gpsd_message,
    read_non_negative_metric,
    read_tpv_mode,
)


class TestClassifyGpsdMessage:
    """Message classification dispatches correctly by payload class."""

    def test_version_message(self) -> None:
        msg = classify_gpsd_message({"class": "VERSION", "rev": "3.25"})
        assert msg == GpsdVersionInfo(revision="3.25")

    def test_version_without_rev(self) -> None:
        assert classify_gpsd_message({"class": "VERSION"}) is None

    def test_version_with_non_string_rev(self) -> None:
        assert classify_gpsd_message({"class": "VERSION", "rev": 42}) is None

    def test_tpv_message(self) -> None:
        msg = classify_gpsd_message(
            {
                "class": "TPV",
                "mode": 3,
                "speed": 12.5,
                "epx": 1.0,
                "epy": 2.0,
                "epv": 3.0,
                "device": "/dev/ttyS0",
            }
        )
        assert isinstance(msg, NormalizedTpvData)
        assert msg.mode == 3
        assert msg.speed == 12.5
        assert msg.epx == 1.0
        assert msg.epy == 2.0
        assert msg.epv == 3.0
        assert msg.device == "/dev/ttyS0"

    def test_tpv_minimal(self) -> None:
        msg = classify_gpsd_message({"class": "TPV"})
        assert isinstance(msg, NormalizedTpvData)
        assert msg.mode is None
        assert msg.speed is None
        assert msg.device is None

    def test_unsupported_class(self) -> None:
        assert classify_gpsd_message({"class": "SKY"}) is None

    def test_missing_class(self) -> None:
        assert classify_gpsd_message({"speed": 10.0}) is None


class TestReadTpvMode:
    """TPV mode extraction validates type."""

    def test_valid_mode(self) -> None:
        assert read_tpv_mode({"mode": 3}) == 3

    def test_bool_rejected(self) -> None:
        assert read_tpv_mode({"mode": True}) is None

    def test_float_rejected(self) -> None:
        assert read_tpv_mode({"mode": 3.0}) is None

    def test_missing_mode(self) -> None:
        assert read_tpv_mode({}) is None


class TestReadNonNegativeMetric:
    """Metric extraction validates numeric range."""

    def test_valid_metric(self) -> None:
        assert read_non_negative_metric({"epx": 1.5}, "epx") == 1.5

    def test_zero_accepted(self) -> None:
        assert read_non_negative_metric({"epx": 0.0}, "epx") == 0.0

    def test_negative_rejected(self) -> None:
        assert read_non_negative_metric({"epx": -1.0}, "epx") is None

    def test_nan_rejected(self) -> None:
        assert read_non_negative_metric({"epx": math.nan}, "epx") is None

    def test_inf_rejected(self) -> None:
        assert read_non_negative_metric({"epx": math.inf}, "epx") is None

    def test_bool_rejected(self) -> None:
        assert read_non_negative_metric({"epx": True}, "epx") is None

    def test_missing_field(self) -> None:
        assert read_non_negative_metric({}, "epx") is None


class TestNormalizedTpvDataFieldExtraction:
    """Verify end-to-end field extraction through classify_gpsd_message."""

    def test_speed_nan_normalized_to_none(self) -> None:
        msg = classify_gpsd_message({"class": "TPV", "speed": math.nan})
        assert isinstance(msg, NormalizedTpvData)
        assert msg.speed is None

    def test_speed_inf_normalized_to_none(self) -> None:
        msg = classify_gpsd_message({"class": "TPV", "speed": math.inf})
        assert isinstance(msg, NormalizedTpvData)
        assert msg.speed is None

    def test_speed_bool_normalized_to_none(self) -> None:
        msg = classify_gpsd_message({"class": "TPV", "speed": True})
        assert isinstance(msg, NormalizedTpvData)
        assert msg.speed is None

    def test_device_empty_string_normalized_to_none(self) -> None:
        msg = classify_gpsd_message({"class": "TPV", "device": ""})
        assert isinstance(msg, NormalizedTpvData)
        assert msg.device is None

    def test_device_non_string_normalized_to_none(self) -> None:
        msg = classify_gpsd_message({"class": "TPV", "device": 42})
        assert isinstance(msg, NormalizedTpvData)
        assert msg.device is None
