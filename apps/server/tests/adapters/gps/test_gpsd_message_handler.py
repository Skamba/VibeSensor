"""Tests for GPSD message classification and field extraction."""

from __future__ import annotations

import math

import pytest

from vibesensor.adapters.gps.gpsd_message_handler import (
    GpsdVersionInfo,
    NormalizedTpvData,
    classify_gpsd_message,
    read_non_negative_metric,
    read_tpv_mode,
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param(
            {"class": "VERSION", "rev": "3.25"},
            GpsdVersionInfo(revision="3.25"),
            id="version",
        ),
        pytest.param({"class": "VERSION"}, None, id="version_missing_rev"),
        pytest.param({"class": "VERSION", "rev": 42}, None, id="version_invalid_rev"),
        pytest.param(
            {
                "class": "TPV",
                "mode": 3,
                "speed": 12.5,
                "epx": 1.0,
                "epy": 2.0,
                "epv": 3.0,
                "device": "/dev/ttyS0",
            },
            NormalizedTpvData(
                mode=3,
                speed=12.5,
                epx=1.0,
                epy=2.0,
                epv=3.0,
                device="/dev/ttyS0",
            ),
            id="tpv_full",
        ),
        pytest.param(
            {"class": "TPV"},
            NormalizedTpvData(
                mode=None,
                speed=None,
                epx=None,
                epy=None,
                epv=None,
                device=None,
            ),
            id="tpv_minimal",
        ),
        pytest.param({"class": "SKY"}, None, id="unsupported_class"),
        pytest.param({"speed": 10.0}, None, id="missing_class"),
    ],
)
def test_classifies_gpsd_messages(payload: dict[str, object], expected: object) -> None:
    assert classify_gpsd_message(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param({"mode": 3}, 3, id="valid"),
        pytest.param({"mode": True}, None, id="bool_rejected"),
        pytest.param({"mode": 3.0}, None, id="float_rejected"),
        pytest.param({}, None, id="missing"),
    ],
)
def test_read_tpv_mode_validates_type(
    payload: dict[str, object],
    expected: int | None,
) -> None:
    assert read_tpv_mode(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        pytest.param({"epx": 1.5}, 1.5, id="valid"),
        pytest.param({"epx": 0.0}, 0.0, id="zero"),
        pytest.param({"epx": -1.0}, None, id="negative_rejected"),
        pytest.param({"epx": math.nan}, None, id="nan_rejected"),
        pytest.param({"epx": math.inf}, None, id="inf_rejected"),
        pytest.param({"epx": True}, None, id="bool_rejected"),
        pytest.param({}, None, id="missing"),
    ],
)
def test_read_non_negative_metric_validates_range(
    payload: dict[str, object],
    expected: float | None,
) -> None:
    assert read_non_negative_metric(payload, "epx") == expected


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"class": "TPV", "speed": math.nan}, id="speed_nan"),
        pytest.param({"class": "TPV", "speed": math.inf}, id="speed_inf"),
        pytest.param({"class": "TPV", "speed": True}, id="speed_bool"),
        pytest.param({"class": "TPV", "device": ""}, id="empty_device"),
        pytest.param({"class": "TPV", "device": 42}, id="non_string_device"),
    ],
)
def test_tpv_field_extraction_normalizes_invalid_fields(
    payload: dict[str, object],
) -> None:
    assert classify_gpsd_message(payload) == NormalizedTpvData(
        mode=None,
        speed=None,
        epx=None,
        epy=None,
        epv=None,
        device=None,
    )
