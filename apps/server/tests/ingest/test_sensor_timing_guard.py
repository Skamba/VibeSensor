"""The registry's timing guard: synced sensor stamps against server receive time."""

from __future__ import annotations

import numpy as np
import pytest
from test_support.clock_sync import complete_clock_sync

from vibesensor.ingest.protocol_messages import DataMessage, HelloMessage
from vibesensor.ingest.registry import ClientRegistry

_CLIENT_ID = "aabbccddeeff"
_FRAME_SAMPLES = 80
_START_S = 1_000.0


def _registry() -> ClientRegistry:
    registry = ClientRegistry()
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(_CLIENT_ID),
            control_port=9010,
            sample_rate_hz=800,
            frame_samples=_FRAME_SAMPLES,
            name="node",
            firmware_version="fw",
        ),
        ("10.4.0.2", 50000),
        now=1.0,
    )
    complete_clock_sync(registry, _CLIENT_ID, now_mono_s=_START_S - 1.0)
    return registry


def _stream(
    registry: ClientRegistry,
    *,
    delivered_hz: float,
    stamped_hz: float,
    duration_s: float,
    lost_every: int = 0,
) -> None:
    """Send frames a sensor delivering ``delivered_hz`` makes, stamped at ``stamped_hz``.

    A sensor that stamps right has ``stamped_hz == delivered_hz``; firmware
    cf117a43e stamped from the nominal 800 Hz schedule while delivering ~742.
    Each frame arrives 15-75 ms after its last sample (Wi-Fi and queueing).
    """
    frame = 0
    while True:
        frame_start_s = _START_S + frame * _FRAME_SAMPLES / delivered_hz
        arrival_s = frame_start_s + _FRAME_SAMPLES / delivered_hz + 0.015 + (frame % 7) * 0.01
        if arrival_s - _START_S > duration_s:
            return
        t0_us = int((_START_S + frame * _FRAME_SAMPLES / stamped_hz) * 1_000_000)
        if not (lost_every and frame % lost_every == lost_every - 1):
            registry.update_from_data(
                DataMessage(
                    client_id=bytes.fromhex(_CLIENT_ID),
                    seq=frame + 1,
                    t0_us=t0_us,
                    sample_count=_FRAME_SAMPLES,
                    samples=np.zeros((_FRAME_SAMPLES, 3), dtype=np.int16),
                ),
                ("10.4.0.2", 50000),
                now_mono=arrival_s,
            )
        frame += 1


@pytest.mark.parametrize(
    ("delivered_hz", "stamped_hz", "lost_every", "expected_state"),
    [
        pytest.param(800.0, 800.0, 0, "ok", id="healthy"),
        pytest.param(800.0, 800.0, 10, "ok", id="healthy-with-lost-frames"),
        # The measured ATOM Lite ADXL345 runs +2.9 % off nominal: the firmware
        # resamples it, a raw stream labelled 800 Hz would be this.
        pytest.param(823.0, 823.0, 0, "rate_mismatch", id="off-rate-sensor"),
        # The hardware bug: 742 samples/s stamped as 800, falling ~55 ms/s behind.
        pytest.param(742.0, 800.0, 0, "timestamp_lag", id="stamps-behind-real-time"),
    ],
)
def test_timing_guard_flags_sensors_whose_samples_cannot_be_placed_in_time(
    delivered_hz: float,
    stamped_hz: float,
    lost_every: int,
    expected_state: str,
) -> None:
    registry = _registry()

    _stream(
        registry,
        delivered_hz=delivered_hz,
        stamped_hz=stamped_hz,
        duration_s=45.0,
        lost_every=lost_every,
    )

    record = registry.get(_CLIENT_ID)
    assert record is not None
    guard = record.timing_guard
    assert guard.state == expected_state
    assert guard.degraded is (expected_state != "ok")
    assert guard.effective_rate_hz == pytest.approx(delivered_hz, rel=0.005)
    if expected_state == "ok":
        # The fastest frame of the window: its build and send latency.
        assert guard.min_lag_us is not None
        assert 10_000 <= guard.min_lag_us <= 20_000


def test_timing_guard_reports_nothing_before_a_full_window() -> None:
    registry = _registry()

    _stream(registry, delivered_hz=742.0, stamped_hz=800.0, duration_s=15.0)

    record = registry.get(_CLIENT_ID)
    assert record is not None
    assert record.timing_guard.state == "unknown"


def test_sensor_reboot_resets_its_timing_verdict() -> None:
    registry = _registry()
    _stream(registry, delivered_hz=742.0, stamped_hz=800.0, duration_s=45.0)

    rebooted = registry.update_from_data(
        DataMessage(
            client_id=bytes.fromhex(_CLIENT_ID),
            seq=1,
            t0_us=2_000_000,
            sample_count=_FRAME_SAMPLES,
            samples=np.zeros((_FRAME_SAMPLES, 3), dtype=np.int16),
        ),
        ("10.4.0.2", 50000),
        now_mono=_START_S + 46.0,
    )

    record = registry.get(_CLIENT_ID)
    assert rebooted.reset_detected is True
    assert record is not None
    assert record.timing_guard.state == "unknown"
    assert record.timing_guard.min_lag_us is None
