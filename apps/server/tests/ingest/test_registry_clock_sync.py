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


def _registry_with_sensor() -> ClientRegistry:
    registry = ClientRegistry()
    registry.update_from_hello(
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
    )
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
    assert rebooted.reset_detected is True
    assert rebooted.clock_synced is False
    assert record is not None
    assert record.clock_offset_applied is False
    assert record.sync_offset_us is None


def _sync_exchange(
    registry: ClientRegistry,
    cmd_seq: int,
    *,
    send_s: float,
    offset_us: int,
    outbound_us: int,
    inbound_us: int,
) -> None:
    """One sync exchange with the given one-way delays (server minus device = offset_us)."""
    send_us = int(send_s * 1_000_000)
    device_us = send_us + outbound_us - offset_us
    registry.mark_cmd_sent("aabbccddeeff", cmd_seq, sync_send_us=send_us, sync_applies_offset=True)
    registry.update_from_ack(
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
    assert record.sync_offset_us == offset_us + 1_000
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

    # 1.5x the accepted round trip (6 ms, skewed by 1 ms): adopted.
    _sync_exchange(
        registry, 3, send_s=1_004.0, offset_us=offset_us, outbound_us=2_000, inbound_us=4_000
    )
    record = registry.get("aabbccddeeff")
    assert record is not None
    assert (record.sync_offset_us, record.sync_rtt_us) == (offset_us + 1_000, 6_000)
