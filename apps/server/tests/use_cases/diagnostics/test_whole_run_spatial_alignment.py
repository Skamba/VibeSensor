from __future__ import annotations

from test_support.sample_scenarios import make_analysis_sample

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_alignment import (
    build_whole_run_spatial_alignment_matrix,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunWindowSpectralSummary,
    whole_run_window_spectral_summaries_to_jsonl_bytes,
)


def _window_policy() -> WholeRunWindowPolicy:
    return WholeRunWindowPolicy(
        sample_rate_hz=200,
        window_size_samples=256,
        stride_samples=100,
        overlap_samples=156,
        feature_interval_s=0.5,
    )


def _context_labels() -> tuple[WholeRunContextWindowLabel, ...]:
    return tuple(
        WholeRunContextWindowLabel(
            window_index=index,
            segment_index=0,
            phase=DrivingPhase.CRUISE,
            context_coverage="full",
            speed_validity="measured",
            rpm_validity="measured",
            load_state="steady",
            speed_kmh=50.0 + index * 10.0,
            speed_band="50-60",
            speed_source="gps",
            engine_rpm=1200.0 + index * 200.0,
            engine_rpm_source="obd2",
        )
        for index in range(3)
    )


def _spectral_manifest() -> WholeRunArtifactManifest:
    return WholeRunArtifactManifest(
        run_id="run-spatial-alignment",
        relative_dir="whole-run-artifacts/run-spatial-alignment",
        window_policy=_window_policy(),
        total_window_count=3,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-rear",
                relative_path="spectra/sensor-rear/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-rear",
            ),
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-front",
                relative_path="spectra/sensor-front/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-front",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )


def _summary_rows(
    *,
    scale: float,
    coverage_states: tuple[str, str, str] = ("full", "full", "full"),
) -> tuple[WholeRunWindowSpectralSummary, ...]:
    rows: list[WholeRunWindowSpectralSummary] = []
    for window_index, coverage_state in enumerate(coverage_states):
        peak = {
            "hz": 12.0 + window_index,
            "amp": scale,
            "vibration_strength_db": 20.0 + scale * 50.0,
            "strength_bucket": "l3",
        }
        rows.append(
            WholeRunWindowSpectralSummary(
                window_index=window_index,
                coverage_state=coverage_state,
                returned_sample_start=(window_index * 100 if coverage_state != "missing" else None),
                returned_sample_count=(
                    256 if coverage_state == "full" else (96 if coverage_state == "partial" else 0)
                ),
                dominant_freq_hz=peak["hz"] if coverage_state == "full" else None,
                vibration_strength_db=peak["vibration_strength_db"]
                if coverage_state == "full"
                else None,
                top_peaks=(peak,) if coverage_state == "full" else (),
            )
        )
    return tuple(rows)


def _artifact_contents() -> dict[str, bytes]:
    return {
        "spectral-summary:sensor-front": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(scale=0.14)
        ),
        "spectral-summary:sensor-rear": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(scale=0.08, coverage_states=("full", "empty", "partial"))
        ),
    }


def _samples(include_extra_sensor: bool = False):
    rows = [
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=50.0,
            client_name="rear-left",
            client_id="sensor-rear",
            location="rear-left",
            top_peaks=[{"hz": 8.0, "amp": 0.08}],
        ),
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=50.0,
            client_name="front-left",
            client_id="sensor-front",
            location="front-left",
            top_peaks=[{"hz": 8.0, "amp": 0.14}],
        ),
    ]
    if include_extra_sensor:
        rows.append(
            make_analysis_sample(
                t_s=0.0,
                speed_kmh=50.0,
                client_name="rear-right",
                client_id="sensor-extra",
                location="rear-right",
                top_peaks=[{"hz": 8.0, "amp": 0.05}],
            )
        )
    return tuple(rows)


def test_build_whole_run_spatial_alignment_matrix_is_deterministic() -> None:
    kwargs = {
        "spectral_manifest": _spectral_manifest(),
        "spectral_artifact_contents": _artifact_contents(),
        "context_labels": tuple(reversed(_context_labels())),
        "samples": tuple(reversed(_samples())),
    }

    first = build_whole_run_spatial_alignment_matrix(**kwargs)
    second = build_whole_run_spatial_alignment_matrix(**kwargs)

    assert first == second
    assert first.sensor_ids == ("sensor-front", "sensor-rear")
    assert [window.window_index for window in first.windows] == [0, 1, 2]
    assert [row.sensor_id for row in first.windows[0].sensor_windows] == [
        "sensor-front",
        "sensor-rear",
    ]
    assert [row.location for row in first.windows[0].sensor_windows] == [
        "front-left",
        "rear-left",
    ]


def test_build_whole_run_spatial_alignment_matrix_tracks_missing_and_partial_sensors() -> None:
    matrix = build_whole_run_spatial_alignment_matrix(
        spectral_manifest=_spectral_manifest(),
        spectral_artifact_contents=_artifact_contents(),
        context_labels=_context_labels(),
        samples=_samples(include_extra_sensor=True),
    )

    assert matrix.sensor_ids == ("sensor-extra", "sensor-front", "sensor-rear")

    second_window = matrix.windows[1]
    assert second_window.full_sensor_count == 1
    assert second_window.partial_sensor_count == 0
    assert second_window.empty_sensor_count == 1
    assert second_window.missing_sensor_count == 1
    assert [row.coverage_state for row in second_window.sensor_windows] == [
        "missing",
        "full",
        "empty",
    ]

    third_window = matrix.windows[2]
    assert third_window.full_sensor_count == 1
    assert third_window.partial_sensor_count == 1
    assert third_window.empty_sensor_count == 0
    assert third_window.missing_sensor_count == 1
    missing_row = third_window.sensor_windows[0]
    assert missing_row.sensor_id == "sensor-extra"
    assert missing_row.location == "rear-right"
    assert missing_row.returned_sample_start is None
    assert missing_row.returned_sample_count == 0
    assert missing_row.top_peaks == ()
