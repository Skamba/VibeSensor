from __future__ import annotations

import pytest

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.shared.types.whole_run_analysis import (
    WHOLE_RUN_ARTIFACT_SCHEMA_VERSION,
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextInterval,
    WholeRunContextWindowLabel,
    WholeRunWindowDescriptor,
    WholeRunWindowPolicy,
)


def _metadata(
    *,
    raw_sample_rate_hz: int | None = 800,
    feature_interval_s: float | None = 0.25,
    fft_window_size_samples: int | None = 2048,
) -> RunMetadata:
    return RunMetadata.create(
        run_id="run-1",
        start_time_utc="2025-01-01T00:00:00Z",
        sensor_model="fixture-sensor",
        raw_sample_rate_hz=raw_sample_rate_hz,
        feature_interval_s=feature_interval_s,
        fft_window_size_samples=fft_window_size_samples,
        accel_scale_g_per_lsb=0.001,
    )


def test_window_policy_derives_stride_and_overlap_from_run_metadata() -> None:
    policy = WholeRunWindowPolicy.from_metadata(_metadata())

    assert policy.sample_rate_hz == 800
    assert policy.window_size_samples == 2048
    assert policy.stride_samples == 200
    assert policy.overlap_samples == 1848
    assert policy.feature_interval_s == pytest.approx(0.25)
    assert policy.window_duration_s == pytest.approx(2.56)
    assert policy.stride_duration_s == pytest.approx(0.25)


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"raw_sample_rate_hz": None}, "raw_sample_rate_hz"),
        ({"fft_window_size_samples": None}, "fft_window_size_samples"),
        ({"feature_interval_s": None}, "feature_interval_s"),
        ({"raw_sample_rate_hz": 800, "feature_interval_s": 1.0 / 3.0}, "integral sample stride"),
        (
            {"fft_window_size_samples": 128, "feature_interval_s": 0.25},
            "stride_samples <= window_size_samples",
        ),
    ],
)
def test_window_policy_rejects_invalid_metadata(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        WholeRunWindowPolicy.from_metadata(_metadata(**kwargs))


def test_window_descriptor_from_policy_sets_sample_and_time_bounds() -> None:
    policy = WholeRunWindowPolicy.from_metadata(_metadata())

    descriptor = WholeRunWindowDescriptor.from_policy(
        window_index=3,
        sample_start=600,
        policy=policy,
    )

    assert descriptor.window_index == 3
    assert descriptor.sample_start == 600
    assert descriptor.sample_end == 2648
    assert descriptor.center_sample == 1624
    assert descriptor.sample_count == 2048
    assert descriptor.start_t_s == pytest.approx(0.75)
    assert descriptor.end_t_s == pytest.approx(3.31)
    assert descriptor.center_t_s == pytest.approx(2.03)
    assert WholeRunWindowDescriptor.from_mapping(descriptor.to_json_object()) == descriptor


def test_whole_run_artifact_manifest_round_trips_with_window_policy() -> None:
    policy = WholeRunWindowPolicy.from_metadata(_metadata())
    manifest = WholeRunArtifactManifest(
        run_id="run-1",
        relative_dir="whole-run-artifacts/run-1",
        window_policy=policy,
        total_window_count=123,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="window_spectra",
                relative_path="window-spectra.jsonl",
                file_format="jsonl",
                record_count=123,
            ),
            WholeRunArtifactFile(
                artifact_key="window_spectra_sensor-a",
                relative_path="sensor-a/window-spectra.npz",
                file_format="npz",
                record_count=123,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2025-01-01T00:00:10Z",
    )

    restored = WholeRunArtifactManifest.from_mapping(manifest.to_json_object())

    assert restored == manifest
    assert restored.schema_version == WHOLE_RUN_ARTIFACT_SCHEMA_VERSION
    assert restored.artifact("window_spectra_sensor-a") == manifest.artifacts[1]


def test_context_window_label_round_trips_with_explicit_quality_states() -> None:
    label = WholeRunContextWindowLabel(
        window_index=12,
        segment_index=3,
        phase=DrivingPhase.CRUISE,
        context_coverage="partial",
        speed_validity="assumed",
        rpm_validity="estimated",
        load_state="steady",
        speed_kmh=63.5,
        speed_band="60-70 km/h",
        speed_source="manual",
        speed_is_stale=True,
        engine_rpm=1825.0,
        engine_rpm_source="estimated_from_speed_and_ratios",
        rpm_is_stale=False,
    )

    restored = WholeRunContextWindowLabel.from_mapping(label.to_json_object())

    assert restored == label


def test_context_window_label_rejects_negative_indices() -> None:
    with pytest.raises(ValueError, match="window_index >= 0"):
        WholeRunContextWindowLabel(
            window_index=-1,
            segment_index=None,
            phase=DrivingPhase.SPEED_UNKNOWN,
            context_coverage="missing",
            speed_validity="missing",
            rpm_validity="missing",
            load_state="unknown",
        )


def test_context_interval_round_trips_with_window_range_summary() -> None:
    interval = WholeRunContextInterval(
        segment_index=2,
        phase=DrivingPhase.ACCELERATION,
        load_state="transient",
        start_window_index=8,
        end_window_index=14,
        start_t_s=2.0,
        end_t_s=5.5,
        speed_min_kmh=18.0,
        speed_max_kmh=46.0,
        speed_band="10-50 km/h",
        full_context_window_count=4,
        partial_context_window_count=2,
        missing_context_window_count=1,
    )

    restored = WholeRunContextInterval.from_mapping(interval.to_json_object())

    assert restored == interval
    assert restored.window_count == 7


def test_context_interval_rejects_inverted_window_ranges() -> None:
    with pytest.raises(ValueError, match="end_window_index >= start_window_index"):
        WholeRunContextInterval(
            segment_index=0,
            phase=DrivingPhase.CRUISE,
            load_state="steady",
            start_window_index=4,
            end_window_index=3,
            start_t_s=1.0,
            end_t_s=1.5,
        )
