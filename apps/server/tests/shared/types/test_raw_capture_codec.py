"""Focused coverage for raw-capture manifest JSON codecs."""

from __future__ import annotations

from vibesensor.shared.types.raw_capture import (
    RawCaptureLossStats,
    RawCaptureManifest,
    RawCaptureSensorClockSync,
    RawCaptureSensorLossStats,
    RawCaptureSensorManifest,
)


def _clock_sync() -> RawCaptureSensorClockSync:
    return RawCaptureSensorClockSync(
        clock_domain="server_monotonic",
        proof_state="verified",
        observed_monotonic_us=1_000,
        last_sync_monotonic_us=900,
        sync_offset_us=12,
        sync_rtt_us=8,
        max_sync_age_us=500,
        max_sync_rtt_us=20,
    )


def _sensor_manifest() -> RawCaptureSensorManifest:
    return RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=800,
        data_file="sensor-a.raw",
        index_file="sensor-a.idx.jsonl",
        sample_count=4_000,
        chunk_count=16,
        bytes_written=32_000,
        first_t0_us=10,
        last_t0_us=4_010,
        clock_sync=_clock_sync(),
        declared_sample_rate_hz=820,
        sample_rate_proof_state="observed_consistent",
    )


def test_raw_capture_manifest_roundtrip_preserves_nested_state() -> None:
    manifest = RawCaptureManifest(
        run_id="run-123",
        relative_dir="raw/run-123",
        sensors=(_sensor_manifest(),),
        total_samples=4_000,
        total_bytes=32_000,
        created_at="2026-04-28T20:00:00Z",
        run_start_monotonic_us=10,
        sensor_losses=(
            RawCaptureSensorLossStats(
                client_id="sensor-a",
                losses=RawCaptureLossStats(
                    udp_ingest_queue_drop_count=1,
                    late_packet_chunk_count=2,
                ),
            ),
        ),
        losses=RawCaptureLossStats(
            udp_ingest_queue_drop_count=1,
            late_packet_chunk_count=2,
        ),
    )

    assert RawCaptureManifest.from_mapping(manifest.to_json_object()) == manifest


def test_raw_capture_manifest_omits_empty_optional_payload_blocks() -> None:
    manifest = RawCaptureManifest(
        run_id="run-123",
        relative_dir="raw/run-123",
        sensors=(
            RawCaptureSensorManifest(
                client_id="sensor-a",
                sample_rate_hz=800,
                data_file="sensor-a.raw",
                index_file="sensor-a.idx.jsonl",
                sample_count=4_000,
                chunk_count=16,
                bytes_written=32_000,
            ),
        ),
        total_samples=4_000,
        total_bytes=32_000,
        created_at="2026-04-28T20:00:00Z",
    )

    payload = manifest.to_json_object()

    assert "run_start_monotonic_us" not in payload
    assert "sensor_losses" not in payload
    assert "losses" not in payload


def test_raw_capture_sensor_manifest_defaults_declared_sample_rate_to_sample_rate() -> None:
    manifest = RawCaptureSensorManifest.from_mapping(
        {
            "client_id": "sensor-a",
            "sample_rate_hz": 800,
            "data_file": "sensor-a.raw",
            "index_file": "sensor-a.idx.jsonl",
            "sample_count": 4_000,
            "chunk_count": 16,
            "bytes_written": 32_000,
        }
    )

    assert manifest.declared_sample_rate_hz == 800
