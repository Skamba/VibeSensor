"""Per-sensor clock proof stored in raw-capture manifests."""

from __future__ import annotations

import time

import pytest
from test_support.clock_sync import complete_clock_sync

from vibesensor.ingest.protocol_messages import HelloMessage
from vibesensor.ingest.registry import ClientRegistry
from vibesensor.recording.recorder import _snapshot_raw_capture_sensor_sync

_CLIENT_ID = "aabbccddeeff"


@pytest.mark.parametrize(
    ("timing_state", "expected_proof", "expected_domain"),
    [
        ("ok", "verified", "server_monotonic"),
        ("unknown", "verified", "server_monotonic"),
        ("timestamp_lag", "timing_unreliable", "unverified"),
        ("rate_mismatch", "timing_unreliable", "unverified"),
    ],
)
def test_a_fresh_sync_does_not_prove_timestamps_the_timing_guard_flagged(
    timing_state, expected_proof: str, expected_domain: str
) -> None:
    registry = ClientRegistry()
    registry.update_from_hello(
        HelloMessage(
            client_id=bytes.fromhex(_CLIENT_ID),
            control_port=9010,
            sample_rate_hz=800,
            frame_samples=80,
            name="node",
            firmware_version="fw",
        ),
        ("10.4.0.2", 50000),
        now=1.0,
    )
    complete_clock_sync(registry, _CLIENT_ID, now_mono_s=time.monotonic())
    record = registry.get(_CLIENT_ID)
    assert record is not None
    record.timing_guard.state = timing_state

    proof = _snapshot_raw_capture_sensor_sync(registry, (_CLIENT_ID,))[_CLIENT_ID]

    assert proof.proof_state == expected_proof
    assert proof.clock_domain == expected_domain
