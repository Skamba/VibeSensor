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
_BACKLOG_S = 0.7
_DRAIN_S = 1.0


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
    outages: tuple[tuple[float, float], ...] = (),
    backlog_s: float = _BACKLOG_S,
    link_delay_s: float = 0.0,
) -> None:
    """Send frames a sensor delivering ``delivered_hz`` makes, stamped at ``stamped_hz``.

    A sensor that stamps right has ``stamped_hz == delivered_hz``; firmware
    cf117a43e stamped from the nominal 800 Hz schedule while delivering ~742.
    Each frame arrives 15-75 ms after its last sample (Wi-Fi and queueing), plus
    ``link_delay_s`` on a link that keeps the sensor's queue that far behind.
    During an outage (start, end), seconds into the stream, nothing arrives:
    the sensor drops frames older than its 3 s hold, and the ``backlog_s`` of
    frames it still queues at the end drain faster than real time over the next
    second.
    """
    frame = 0
    while True:
        frame_start_s = _START_S + frame * _FRAME_SAMPLES / delivered_hz
        arrival_s = (
            frame_start_s
            + _FRAME_SAMPLES / delivered_hz
            + 0.015
            + (frame % 7) * 0.01
            + link_delay_s
        )
        if arrival_s - _START_S > duration_s:
            return
        t0_us = int((_START_S + frame * _FRAME_SAMPLES / stamped_hz) * 1_000_000)
        aged_out = False
        for outage_start_s, outage_end_s in outages:
            since_queued_s = arrival_s - _START_S - (outage_end_s - backlog_s)
            if outage_start_s <= arrival_s - _START_S and since_queued_s < 0:
                aged_out = True
            elif 0 <= since_queued_s < backlog_s + _DRAIN_S:
                arrival_s += backlog_s * (1 - since_queued_s / (backlog_s + _DRAIN_S))
        if not aged_out and not (lost_every and frame % lost_every == lost_every - 1):
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
        # Its first window (25 s) shows rate_mismatch; once its stamps are further
        # behind than the sensor ever holds a frame (3.5 s), timestamp_lag.
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
        duration_s=90.0,
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


@pytest.mark.parametrize(
    ("outages", "backlog_s", "duration_s"),
    [
        # Synced while its queue still holds frames from before the server came
        # up: a window anchored there counts 0.7 s too many samples (+3.5 %).
        pytest.param(((0.0, 0.8),), 0.7, 27.0, id="backlog-at-stream-start"),
        # A Wi-Fi drop that ends just before the second window would close:
        # closed there, it would miss the frames still queued (-2.8 %).
        pytest.param(((0.0, 0.8), (44.0, 45.6)), 0.7, 47.0, id="backlog-after-an-interruption"),
        # A 5 s Wi-Fi drop mid-window: the sensor delivers its last 2.9 s of
        # frames once it is back, 14 % of a window if one were anchored there.
        pytest.param(((0.0, 0.8), (20.0, 25.0)), 2.9, 52.0, id="wifi-drop-backlog"),
    ],
)
def test_timing_guard_waits_for_a_drained_queue_before_judging_the_rate(
    outages: tuple[tuple[float, float], ...],
    backlog_s: float,
    duration_s: float,
) -> None:
    registry = _registry()

    _stream(
        registry,
        delivered_hz=800.0,
        stamped_hz=800.0,
        duration_s=duration_s,
        outages=outages,
        backlog_s=backlog_s,
    )

    record = registry.get(_CLIENT_ID)
    assert record is not None
    assert record.timing_guard.state == "ok"
    assert record.timing_guard.effective_rate_hz == pytest.approx(800.0, rel=0.005)


def test_a_link_that_keeps_a_sensor_seconds_behind_is_not_a_timestamp_error() -> None:
    """The sensor holds frames up to 3 s; correctly stamped late frames are placed right."""
    registry = _registry()

    _stream(registry, delivered_hz=800.0, stamped_hz=800.0, duration_s=50.0, link_delay_s=2.5)

    record = registry.get(_CLIENT_ID)
    assert record is not None
    assert record.timing_guard.state == "ok"
    assert record.timing_guard.min_lag_us is not None
    assert 2_500_000 <= record.timing_guard.min_lag_us <= 2_520_000


def test_timing_guard_still_flags_an_off_rate_sensor_with_a_backlog_at_stream_start() -> None:
    registry = _registry()

    _stream(
        registry,
        delivered_hz=823.0,
        stamped_hz=823.0,
        duration_s=27.0,
        outages=((0.0, 0.8),),
    )

    record = registry.get(_CLIENT_ID)
    assert record is not None
    assert record.timing_guard.state == "rate_mismatch"


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
