"""Live and health warnings follow recent frame loss; the totals never reset."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from test_support.runtime_lifecycle import (
    build_history_db,
    build_registry,
    build_registry_with_hello,
    make_data_message,
    make_hello_message,
)

from vibesensor.ingest.client_payloads import snapshot_for_api
from vibesensor.ingest.protocol_messages import HelloMessage
from vibesensor.ingest.registry import EXPECTED_LOSS_DRAIN_S, STREAM_START_GRACE_S

_FRAME_S = 0.25  # 200 samples at 800 Hz


def _feed(registry, client_id: bytes, seqs: range | list[int], start_mono: float) -> float:
    mono = start_mono
    for seq in seqs:
        mono += _FRAME_S
        registry.update_from_data(
            make_data_message(client_id, seq, 10 + seq * 250_000, sample_count=200),
            ("10.4.0.2", 50000),
            now=mono,
            now_mono=mono,
        )
    return mono


def test_frame_loss_warning_clears_a_minute_after_the_loss(tmp_path: Path) -> None:
    registry, client_id = build_registry_with_hello(tmp_path)
    # Ten frames lost out of about forty, well after the stream started.
    mono = _feed(registry, client_id, [*range(30), *range(40, 50)], start_mono=10.0)

    row = snapshot_for_api(registry, now=mono, now_mono=mono)[0]
    assert (row["dropped_frames"], row["frame_loss_recent"]) == (10, True)
    recent = registry.recent_data_loss_snapshot(now_mono=mono)
    assert (recent["frame_loss_clients"], recent["frames_dropped"]) == (1, 10)

    # A clean minute later the warning is gone but the total remains.
    mono = _feed(registry, client_id, range(50, 50 + 250), start_mono=mono)
    row = snapshot_for_api(registry, now=mono, now_mono=mono)[0]
    assert (row["dropped_frames"], row["frame_loss_recent"]) == (10, False)
    assert registry.recent_data_loss_snapshot(now_mono=mono)["frames_dropped"] == 0
    assert registry.data_loss_snapshot()["frames_dropped"] == 10


def test_an_occasional_lost_frame_is_not_a_warning(tmp_path: Path) -> None:
    registry, client_id = build_registry_with_hello(tmp_path)
    # One frame lost among a minute of frames: well under 1 %.
    mono = _feed(registry, client_id, [*range(120), *range(121, 240)], start_mono=10.0)

    row = snapshot_for_api(registry, now=mono, now_mono=mono)[0]
    assert (row["dropped_frames"], row["frame_loss_recent"]) == (1, False)
    assert registry.recent_data_loss_snapshot(now_mono=mono)["frames_dropped"] == 1


def test_queue_overflow_while_streaming_warns_and_its_total_survives_reboots(
    tmp_path: Path,
) -> None:
    registry, client_id = build_registry_with_hello(tmp_path)

    def hello(drops: int, mono: float) -> None:
        registry.update_from_hello(
            HelloMessage(
                client_id=client_id,
                control_port=9010,
                sample_rate_hz=800,
                name="node",
                firmware_version="fw",
                queue_overflow_drops=drops,
            ),
            ("10.4.0.2", 9010),
            now=mono,
            now_mono=mono,
        )

    _feed(registry, client_id, range(4), start_mono=90.0)
    hello(5, 100.0)
    hello(7, 101.0)
    hello(2, 102.0)  # rebooted: the device counter restarted
    assert registry.recent_data_loss_snapshot(now_mono=102.0)["queue_overflow_drops"] == 9
    assert registry.recent_data_loss_snapshot(now_mono=200.0)["queue_overflow_drops"] == 0
    assert registry.data_loss_snapshot()["queue_overflow_drops"] == 9


def test_queue_overflow_reported_after_a_server_restart_is_stream_start_loss(
    tmp_path: Path,
) -> None:
    """The sensor kept streaming through a server update and its queue overflowed."""
    registry = build_registry(db=build_history_db(tmp_path))
    hello_msg = make_hello_message("aabbccddeeff", queue_overflow_drops=31)
    client_id = hello_msg.client_id
    # Its DATA can arrive first; its first HELLO here reports the overflow.
    mono = _feed(registry, client_id, range(500, 504), start_mono=10.0)
    registry.update_from_hello(hello_msg, ("10.4.0.2", 9010), now=mono, now_mono=mono)
    mono = _feed(registry, client_id, range(504, 512), start_mono=mono)
    # The next HELLO, while the backlog drains, reports one more.
    registry.update_from_hello(
        replace(hello_msg, queue_overflow_drops=32), ("10.4.0.2", 9010), now=mono, now_mono=mono
    )

    assert registry.recent_data_loss_snapshot(now_mono=mono)["queue_overflow_drops"] == 0
    assert registry.data_loss_snapshot()["queue_overflow_drops"] == 32
    record = registry.get(client_id.hex())
    assert record is not None
    assert (record.expected_queue_overflow_drops, record.last_expected_loss_reason) == (
        32,
        "stream_start",
    )


def test_frames_lost_as_a_stream_starts_are_kept_but_not_a_recent_warning(
    tmp_path: Path,
) -> None:
    """Frames the sensor queued while the server was down age out at the first ACKs."""
    registry, client_id = build_registry_with_hello(tmp_path)
    assert 3 * _FRAME_S < STREAM_START_GRACE_S
    mono = _feed(registry, client_id, [0, 1, 2, *range(6, 40)], start_mono=10.0)

    row = snapshot_for_api(registry, now=mono, now_mono=mono)[0]
    assert (row["dropped_frames"], row["frame_loss_recent"]) == (3, False)
    recent = registry.recent_data_loss_snapshot(now_mono=mono)
    assert (recent["frames_dropped"], recent["expected_frames_dropped"]) == (0, 3)
    record = registry.get(client_id.hex())
    assert record is not None
    assert (record.expected_frames_dropped, record.last_expected_loss_reason) == (
        3,
        "stream_start",
    )


def test_frames_lost_to_a_bluetooth_scan_are_annotated_until_the_drain_ends(
    tmp_path: Path,
) -> None:
    registry, client_id = build_registry_with_hello(tmp_path)
    # Fake sensor time stays behind the real clock that times the drain window.
    mono = _feed(registry, client_id, range(40), start_mono=time.monotonic() - 30.0)

    with registry.expecting_frame_loss("bluetooth_scan"):
        mono = _feed(registry, client_id, range(45, 60), start_mono=mono)
    # Frames already in flight when the scan ends still count as scan loss.
    mono = _feed(registry, client_id, range(62, 64), start_mono=time.monotonic())

    recent = registry.recent_data_loss_snapshot(now_mono=mono)
    assert (recent["frames_dropped"], recent["expected_frames_dropped"]) == (0, 7)
    record = registry.get(client_id.hex())
    assert record is not None
    assert record.last_expected_loss_reason == "bluetooth_scan"

    # After the drain window a gap is ordinary loss again.
    mono = _feed(
        registry,
        client_id,
        range(70, 80),
        start_mono=time.monotonic() + EXPECTED_LOSS_DRAIN_S + 1.0,
    )
    recent = registry.recent_data_loss_snapshot(now_mono=mono)
    assert (recent["frames_dropped"], recent["expected_frames_dropped"]) == (6, 7)
    assert registry.data_loss_snapshot()["frames_dropped"] == 13
