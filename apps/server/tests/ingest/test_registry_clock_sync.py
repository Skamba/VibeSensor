"""Which DATA frames carry server-clock timestamps (and may enter raw capture)."""

from __future__ import annotations

import numpy as np
from test_support.clock_sync import complete_clock_sync

from vibesensor.ingest.protocol_messages import DataMessage, HelloMessage
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
