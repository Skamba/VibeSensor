from __future__ import annotations

from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.whole_run_spectral_projection import (
    WholeRunWindowSpectralSummary,
    whole_run_spectral_summaries_by_sensor,
    whole_run_window_spectral_summaries_from_jsonl_bytes,
    whole_run_window_spectral_summaries_to_jsonl_bytes,
)


def _window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=800,
        window_size_samples=2048,
        stride_samples=200,
        overlap_samples=1848,
        feature_interval_s=0.25,
    )


def test_spectral_projection_summary_jsonl_round_trips() -> None:
    summaries = (
        WholeRunWindowSpectralSummary(
            window_index=0,
            coverage_state="full",
            returned_sample_start=0,
            returned_sample_count=2048,
            dominant_freq_hz=14.5,
            vibration_strength_db=11.2,
            strength_peak_amp_g=0.21,
            strength_floor_amp_g=0.03,
            strength_bucket="moderate",
        ),
        WholeRunWindowSpectralSummary(
            window_index=1,
            coverage_state="partial",
            returned_sample_start=200,
            returned_sample_count=1900,
            coverage_reason="gap",
        ),
    )

    payload = whole_run_window_spectral_summaries_to_jsonl_bytes(summaries)

    assert whole_run_window_spectral_summaries_from_jsonl_bytes(payload) == summaries


def test_spectral_projection_groups_summary_rows_by_sensor() -> None:
    summaries = (
        WholeRunWindowSpectralSummary(
            window_index=0,
            coverage_state="full",
            returned_sample_start=0,
            returned_sample_count=2048,
        ),
        WholeRunWindowSpectralSummary(
            window_index=1,
            coverage_state="missing",
            returned_sample_start=None,
            returned_sample_count=0,
            coverage_reason="sensor_missing",
        ),
    )
    manifest = WholeRunArtifactManifest(
        run_id="run-1",
        relative_dir="whole-run-artifacts/run-1",
        window_policy=_window_policy(),
        total_window_count=2,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-a",
                relative_path="spectra/sensor-a/windows.jsonl",
                file_format="jsonl",
                record_count=2,
                sensor_id="sensor-a",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )

    grouped = whole_run_spectral_summaries_by_sensor(
        manifest=manifest,
        artifact_contents={
            "spectral-summary:sensor-a": whole_run_window_spectral_summaries_to_jsonl_bytes(
                summaries
            )
        },
    )

    assert grouped == {"sensor-a": summaries}
