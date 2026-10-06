"""Which DATA frames carry server-clock timestamps (and may enter raw capture)."""

from __future__ import annotations

import numpy as np
from test_support.clock_sync import complete_clock_sync

from vibesensor.ingest.protocol_messages import AckMessage, DataMessage, HelloMessage
from vibesensor.ingest.registry import ClientRegistry


def _data(seq: int, t0_us: int) -> DataMessage:
    return DataMessage(
        client_id=bytes.fromhex("aabbccddeeff"),
        seq=seq,
        t0_us=t0_us,
        sample_count=200,
        samples=np.zeros((200, 3), dtype=np.int16),
    )


def _hello(registry: ClientRegistry, *, now_mono: float) -> bool:
    return registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex("aabbccddeeff"),
            control_port=9010,
            sample_rate_hz=800,
            frame_samples=200,
            name="node",
            firmware_version="fw",
        ),
        ("10.4.0.2", 50000),
        now=1.0,
        now_mono=now_mono,
    )


def _registry_with_sensor() -> ClientRegistry:
    registry = ClientRegistry()
    _hello(registry, now_mono=1.0)
    return registry


def test_data_frames_are_clock_synced_only_after_an_applied_offset_is_acknowledged() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000  # the server clock runs 500 s ahead of the device clock
    now_mono_s = 1_000.0
    frame_us = 250_000

    first = registry.update_from_data(
        _data(1, int(now_mono_s * 1e6) - offset_us - frame_us),
        ("10.4.0.2", 50000),
        now_mono=now_mono_s,
    )
    complete_clock_sync(registry, "aabbccddeeff", offset_us=offset_us, now_mono_s=now_mono_s)
    straggler = registry.update_from_data(
        _data(2, int((now_mono_s + 0.25) * 1e6) - offset_us - frame_us),
        ("10.4.0.2", 50000),
        now_mono=now_mono_s + 0.25,
    )
    synced = registry.update_from_data(
        _data(3, int((now_mono_s + 0.5) * 1e6) - frame_us),
        ("10.4.0.2", 50000),
        now_mono=now_mono_s + 0.5,
    )

    assert first.clock_synced is False
    assert straggler.clock_synced is False
    assert synced.clock_synced is True


def test_sensor_reboot_forgets_its_clock_sync() -> None:
    registry = _registry_with_sensor()
    complete_clock_sync(registry, "aabbccddeeff", now_mono_s=1_000.0)
    synced = registry.update_from_data(
        _data(5_000, 999_750_000), ("10.4.0.2", 50000), now_mono=1_000.0
    )
    rebooted = registry.update_from_data(
        _data(1, 2_000_000), ("10.4.0.2", 50000), now_mono=1_000.25
    )

    record = registry.get("aabbccddeeff")
    assert synced.clock_synced is True
    assert synced.sync_due is False
    assert rebooted.reset_detected is True
    assert rebooted.clock_synced is False
    # Its HELLO came before the reboot showed, so its first DATA starts the re-sync.
    assert rebooted.sync_due is True
    assert record is not None
    assert record.clock_offset_applied is False
    assert record.sync_offset_us is None


def test_data_before_the_first_hello_starts_one_sync_exchange_at_a_time() -> None:
    """A sensor keeps streaming across a server restart and says HELLO only every 2 s;
    waiting for that HELLO cost a recording started at once ~1.6 s of raw capture."""
    registry = ClientRegistry()
    addr = ("10.4.0.2", 50000)

    first = registry.update_from_data(_data(1, 2_000_000), addr, now_mono=1_000.0)

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert first.sync_due is True
    # The firmware's control port: 9010 + last MAC byte (0xff) % 100.
    assert record.control_addr == ("10.4.0.2", 9065)

    registry.mark_cmd_sent("aabbccddeeff", 7, sync_send_us=1_000_000_000)
    in_flight = registry.update_from_data(_data(2, 2_250_000), addr, now_mono=1_000.25)
    presumed_lost = registry.update_from_data(_data(3, 2_500_000), addr, now_mono=1_000.5)
    assert in_flight.sync_due is False
    assert presumed_lost.sync_due is True

    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex("aabbccddeeff"),
            control_port=9123,
            sample_rate_hz=800,
            frame_samples=200,
            name="node",
            firmware_version="fw",
        ),
        ("10.4.0.2", 40000),
        now_mono=1_000.6,
    )
    record = registry.get("aabbccddeeff")
    assert record is not None
    assert record.control_addr == ("10.4.0.2", 9123)


def _sync_exchange(
    registry: ClientRegistry,
    cmd_seq: int,
    *,
    send_s: float,
    offset_us: int,
    outbound_us: int,
    inbound_us: int,
) -> bool:
    """One sync exchange with the given one-way delays (server minus device = offset_us).

    Returns whether the registry wants the applying exchange sent right away.
    """
    send_us = int(send_s * 1_000_000)
    device_us = send_us + outbound_us - offset_us
    registry.mark_cmd_sent("aabbccddeeff", cmd_seq, sync_send_us=send_us, sync_applies_offset=True)
    return registry.update_from_ack(
        AckMessage(
            client_id=bytes.fromhex("aabbccddeeff"),
            cmd_seq=cmd_seq,
            status=0,
            device_receive_us=device_us,
            device_send_us=device_us,
        ),
        now_mono=(send_us + outbound_us + inbound_us) / 1_000_000,
    )


def test_a_delayed_sync_exchange_does_not_move_the_clock_offset() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    _sync_exchange(
        registry, 1, send_s=1_000.0, offset_us=offset_us, outbound_us=150, inbound_us=150
    )
    # A 9 ms stall on the way back skews this exchange's estimate by 4.5 ms.
    _sync_exchange(
        registry, 2, send_s=1_002.0, offset_us=offset_us, outbound_us=150, inbound_us=9_150
    )

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert record.sync_offset_us == offset_us
    assert record.sync_rtt_us == 300
    assert record.last_sync_monotonic_us == 1_000_000_300


def test_a_slower_sync_exchange_is_adopted_once_the_current_offset_is_old() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    _sync_exchange(
        registry, 1, send_s=1_000.0, offset_us=offset_us, outbound_us=150, inbound_us=150
    )
    # The link got slower for good: the held estimate expires and the new one is used.
    _sync_exchange(
        registry, 2, send_s=1_010.0, offset_us=offset_us, outbound_us=4_000, inbound_us=6_000
    )
    _sync_exchange(
        registry, 3, send_s=1_012.0, offset_us=offset_us, outbound_us=4_000, inbound_us=6_000
    )

    record = registry.get("aabbccddeeff")
    assert record is not None
    # Each 1 ms-skewed estimate moves the applied offset by the slew limit only.
    assert record.sync_offset_us == offset_us + 400
    assert record.sync_rtt_us == 10_000
    assert record.last_sync_monotonic_us == 1_012_010_000


def test_sync_exchanges_beyond_twice_the_accepted_round_trip_are_skipped() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    # Accepted estimate: 4 ms round trip.
    _sync_exchange(
        registry, 1, send_s=1_000.0, offset_us=offset_us, outbound_us=2_000, inbound_us=2_000
    )
    # 3x the accepted round trip (12 ms, skewed by 4 ms): skipped.
    _sync_exchange(
        registry, 2, send_s=1_002.0, offset_us=offset_us, outbound_us=2_000, inbound_us=10_000
    )
    record = registry.get("aabbccddeeff")
    assert record is not None
    assert (record.sync_offset_us, record.sync_rtt_us) == (offset_us, 4_000)

    # 1.5x the accepted round trip (6 ms, skewed by 1 ms): adopted, slewed.
    _sync_exchange(
        registry, 3, send_s=1_004.0, offset_us=offset_us, outbound_us=2_000, inbound_us=4_000
    )
    record = registry.get("aabbccddeeff")
    assert record is not None
    assert (record.sync_offset_us, record.sync_rtt_us) == (offset_us + 200, 6_000)


# The raw-capture timeline treats a jump of more than 0.75 sample between chunk
# stamps as a gap or overlap; FFT windows across one are not raw-backed.
_RAW_TIMELINE_TOLERANCE_US_800HZ = 0.75 * 1_000_000 / 800


def _applied_offset(registry: ClientRegistry) -> int:
    record = registry.get("aabbccddeeff")
    assert record is not None
    assert record.sync_offset_us is not None
    return record.sync_offset_us


def test_resync_noise_never_steps_sensor_timestamps_past_the_raw_timeline_tolerance() -> None:
    """Asymmetric delays skew every estimate by ms; the stamps the sensor applies must not jump.

    Sensors apply each offset the server sends, so a re-sync that adopted a fresh
    estimate stepped their t0_us by the estimate's error: under load every 2 s
    re-sync broke the raw timeline, and runs replayed no raw windows at all.
    """
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    applied: list[int] = []
    for cmd_seq in range(1, 31):
        # A steady 4 ms round trip whose delay sits on alternating sides.
        outbound_us, inbound_us = (3_800, 200) if cmd_seq % 2 else (200, 3_800)
        _sync_exchange(
            registry,
            cmd_seq,
            send_s=1_000.0 + 2.0 * cmd_seq,
            offset_us=offset_us,
            outbound_us=outbound_us,
            inbound_us=inbound_us,
        )
        applied.append(_applied_offset(registry))

    steps = [abs(b - a) for a, b in zip(applied, applied[1:], strict=False)]
    assert max(steps) < _RAW_TIMELINE_TOLERANCE_US_800HZ
    # Still within the 2 ms an exchange can be off by.
    assert all(abs(value - offset_us) <= 2_000 for value in applied)


# t0_us steps at each 2 s re-sync in real Pi run 27af310d (RTT ~8.8 ms, no lost
# chunks): 19 of these 25 broke the raw timeline and most windows went partial.
_PI_RUN_RESYNC_STEPS_US = (
    -1359, -2180, 4009, -1416, -1412, 299, -984, -610, 1659, 2363, -2211, -1902, 898,
    -73, 1189, -3384, 1932, 4100, 1439, -4207, 2012, 794, -2447, -1563, -68,
)  # fmt: skip


def test_real_pi_resync_jitter_no_longer_steps_sensor_timestamps() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    round_trip_us = 8_838
    # Replay the estimate errors behind those steps, centred within +-RTT/2.
    errors_us = [0]
    for step_us in _PI_RUN_RESYNC_STEPS_US:
        errors_us.append(errors_us[-1] + step_us)
    centre_us = (max(errors_us) + min(errors_us)) // 2
    applied: list[int] = []
    for cmd_seq, error_us in enumerate(errors_us, start=1):
        error_us -= centre_us
        _sync_exchange(
            registry,
            cmd_seq,
            send_s=1_000.0 + 2.0 * cmd_seq,
            offset_us=offset_us,
            outbound_us=round_trip_us // 2 - error_us,
            inbound_us=round_trip_us // 2 + error_us,
        )
        applied.append(_applied_offset(registry))

    steps = [abs(b - a) for a, b in zip(applied, applied[1:], strict=False)]
    assert max(steps) < _RAW_TIMELINE_TOLERANCE_US_800HZ
    assert all(abs(value - offset_us) <= round_trip_us // 2 for value in applied)


def test_resync_tracks_sensor_crystal_drift() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    drift_us_per_exchange = 80  # 40 ppm over the 2 s sync interval
    for cmd_seq in range(1, 21):
        true_offset_us = offset_us - drift_us_per_exchange * cmd_seq
        _sync_exchange(
            registry,
            cmd_seq,
            send_s=1_000.0 + 2.0 * cmd_seq,
            offset_us=true_offset_us,
            outbound_us=300,
            inbound_us=300,
        )
        assert abs(_applied_offset(registry) - true_offset_us) <= drift_us_per_exchange


def test_an_offset_a_precise_exchange_proves_wrong_is_replaced_at_once() -> None:
    registry = _registry_with_sensor()
    offset_us = 500_000_000
    # The first exchange stalls 30 ms on the way out: its estimate is 15 ms off.
    _sync_exchange(
        registry, 1, send_s=1_000.0, offset_us=offset_us, outbound_us=30_000, inbound_us=200
    )
    assert abs(_applied_offset(registry) - offset_us) > 14_000
    _sync_exchange(
        registry, 2, send_s=1_002.0, offset_us=offset_us, outbound_us=150, inbound_us=150
    )
    assert _applied_offset(registry) == offset_us


def test_a_sensor_that_applied_its_previous_boots_offset_is_resynced_at_once() -> None:
    registry = _registry_with_sensor()
    boot1_offset_us = 500_000_000
    complete_clock_sync(registry, "aabbccddeeff", offset_us=boot1_offset_us, now_mono_s=1_000.0)
    for seq in range(7):
        registry.update_from_data(
            _data(seq, 1_000_000_000 + seq * 250_000), ("10.4.0.2", 50000), now_mono=1_000.3
        )
    # The sensor stops after 1.75 s and boots again 4 s after its first boot; the
    # next periodic sync still carries the first boot's offset, which it applies.
    boot2_offset_us = boot1_offset_us + 4_000_000
    resync_now = _sync_exchange(
        registry, 3, send_s=1_006.0, offset_us=boot2_offset_us, outbound_us=150, inbound_us=150
    )
    stale = registry.update_from_data(
        _data(0, 1_006_000_000 - 4_000_000), ("10.4.0.2", 50000), now_mono=1_006.25
    )
    _sync_exchange(
        registry, 4, send_s=1_006.3, offset_us=boot2_offset_us, outbound_us=150, inbound_us=150
    )
    resynced = registry.update_from_data(
        _data(1, 1_006_250_000), ("10.4.0.2", 50000), now_mono=1_006.5
    )

    record = registry.get("aabbccddeeff")
    assert record is not None
    assert resync_now is True
    assert stale.clock_synced is False
    assert (resynced.is_duplicate, resynced.is_late, resynced.clock_synced) == (False, False, True)
    assert _applied_offset(registry) == boot2_offset_us


def test_a_hello_after_the_sensor_went_silent_starts_a_sync_exchange() -> None:
    registry = _registry_with_sensor()
    complete_clock_sync(registry, "aabbccddeeff", now_mono_s=1_000.0)
    for seq in range(6):
        registry.update_from_data(
            _data(seq, 1_000_000_000 + seq * 250_000),
            ("10.4.0.2", 50000),
            now_mono=1_000.0 + 0.25 * (seq + 1),
        )
    streaming_hello = _hello(registry, now_mono=1_001.6)
    # A broadcast to the sensor goes unanswered: it stopped streaming.
    registry.mark_cmd_sent("aabbccddeeff", 9, sync_send_us=1_002_000_000, sync_applies_offset=True)
    hello_after_silence = _hello(registry, now_mono=1_003.5)

    assert streaming_hello is False
    assert hello_after_silence is True
