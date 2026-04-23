from __future__ import annotations

from test_support.sample_scenarios import make_analysis_sample

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.orders.whole_run_contracts import OrderTracePoint
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    WholeRunOrderTraceArtifactBundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spatial_coherence import (
    WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY,
    build_whole_run_spatial_coherence_artifact_bundle,
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
        run_id="run-spatial-coherence",
        relative_dir="whole-run-artifacts/run-spatial-coherence",
        window_policy=_window_policy(),
        total_window_count=3,
        artifacts=(
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-front",
                relative_path="spectra/sensor-front/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-front",
            ),
            WholeRunArtifactFile(
                artifact_key="spectral-summary:sensor-rear",
                relative_path="spectra/sensor-rear/windows.jsonl",
                file_format="jsonl",
                record_count=3,
                sensor_id="sensor-rear",
            ),
        ),
        created_at="2025-01-01T00:00:00Z",
    )


def _artifact_contents() -> dict[str, bytes]:
    front_rows: list[WholeRunWindowSpectralSummary] = []
    rear_rows: list[WholeRunWindowSpectralSummary] = []
    for window_index, (wheel_hz, engine_hz) in enumerate(
        ((10.0, 30.0), (12.0, 32.0), (14.0, 34.0))
    ):
        front_rows.append(
            WholeRunWindowSpectralSummary(
                window_index=window_index,
                coverage_state="full",
                returned_sample_start=window_index * 100,
                returned_sample_count=256,
                dominant_freq_hz=wheel_hz,
                vibration_strength_db=28.0,
                top_peaks=(
                    {
                        "hz": wheel_hz,
                        "amp": 0.14,
                        "vibration_strength_db": 32.0,
                        "strength_bucket": "l3",
                    },
                    {
                        "hz": engine_hz,
                        "amp": 0.11,
                        "vibration_strength_db": 29.0,
                        "strength_bucket": "l3",
                    },
                ),
            )
        )
        rear_rows.append(
            WholeRunWindowSpectralSummary(
                window_index=window_index,
                coverage_state="full",
                returned_sample_start=window_index * 100,
                returned_sample_count=256,
                dominant_freq_hz=wheel_hz,
                vibration_strength_db=25.0,
                top_peaks=(
                    {
                        "hz": wheel_hz,
                        "amp": 0.10,
                        "vibration_strength_db": 27.0,
                        "strength_bucket": "l2",
                    },
                ),
            )
        )
    return {
        "spectral-summary:sensor-front": whole_run_window_spectral_summaries_to_jsonl_bytes(
            tuple(front_rows)
        ),
        "spectral-summary:sensor-rear": whole_run_window_spectral_summaries_to_jsonl_bytes(
            tuple(rear_rows)
        ),
    }


def _samples():
    return (
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=50.0,
            client_name="front-left",
            client_id="sensor-front",
            location="front-left",
            top_peaks=[{"hz": 10.0, "amp": 0.14}],
        ),
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=50.0,
            client_name="rear-left",
            client_id="sensor-rear",
            location="rear-left",
            top_peaks=[{"hz": 10.0, "amp": 0.10}],
        ),
    )


def _order_trace_bundle() -> WholeRunOrderTraceArtifactBundle:
    points = [
        OrderTracePoint(
            hypothesis_key="wheel_1x",
            suspected_source="wheel/tire",
            order_family="wheel",
            harmonic=1,
            order_label="1x wheel",
            window_index=index,
            eligible=True,
            matched=True,
            predicted_hz=hz,
        )
        for index, hz in enumerate((10.0, 12.0, 14.0))
    ]
    points.extend(
        OrderTracePoint(
            hypothesis_key="engine_1x",
            suspected_source="engine",
            order_family="engine",
            harmonic=1,
            order_label="1x engine",
            window_index=index,
            eligible=True,
            matched=(index == 0),
            predicted_hz=hz,
        )
        for index, hz in enumerate((30.0, 32.0, 34.0))
    )
    return WholeRunOrderTraceArtifactBundle(
        manifest=WholeRunArtifactManifest(
            run_id="run-spatial-coherence",
            relative_dir="whole-run-artifacts/run-spatial-coherence",
            window_policy=_window_policy(),
            total_window_count=3,
            artifacts=(
                WholeRunArtifactFile(
                    artifact_key=WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
                    relative_path="orders/trace-points.jsonl",
                    file_format="jsonl",
                    record_count=len(points),
                ),
            ),
            created_at="2025-01-01T00:00:00Z",
        ),
        artifact_contents={WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY: b""},
        points=tuple(points),
    )


def test_build_whole_run_spatial_coherence_artifact_bundle_scores_candidates() -> None:
    bundle = build_whole_run_spatial_coherence_artifact_bundle(
        order_trace_bundle=_order_trace_bundle(),
        spectral_manifest=_spectral_manifest(),
        spectral_artifact_contents=_artifact_contents(),
        context_labels=_context_labels(),
        samples=_samples(),
    )

    assert bundle.manifest.artifact(WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY) is not None
    assert bundle.artifact_contents[WHOLE_RUN_SPATIAL_COHERENCE_ARTIFACT_KEY].count(b"\n") == len(
        bundle.windows
    )
    assert [summary.candidate_key for summary in bundle.summaries] == ["wheel_1x", "engine_1x"]

    wheel_summary = bundle.summaries[0]
    assert wheel_summary.supporting_window_count == 3
    assert wheel_summary.coherent_window_count == 3
    assert wheel_summary.supporting_sensor_count == 2
    assert wheel_summary.coherence_ratio == 1.0
    assert wheel_summary.proof_basis == "supporting_windows_raw_backed"

    engine_summary = bundle.summaries[1]
    assert engine_summary.supporting_window_count == 3
    assert engine_summary.coherent_window_count == 0
    assert engine_summary.supporting_sensor_count == 1
    assert engine_summary.coherence_ratio == 0.0

    wheel_rows = [
        row
        for row in bundle.windows
        if row.candidate_key == "wheel_1x" and row.sensor_id == "sensor-rear"
    ]
    assert len(wheel_rows) == 3
    assert all(row.supporting for row in wheel_rows)
    assert all(row.coherent for row in wheel_rows)
    assert all(row.coherence_score == 1.0 for row in wheel_rows)

    engine_rear_rows = [
        row
        for row in bundle.windows
        if row.candidate_key == "engine_1x" and row.sensor_id == "sensor-rear"
    ]
    assert len(engine_rear_rows) == 3
    assert not any(row.supporting for row in engine_rear_rows)
    assert not any(row.coherent for row in engine_rear_rows)


def test_build_whole_run_spatial_coherence_artifact_bundle_is_deterministic() -> None:
    kwargs = {
        "order_trace_bundle": _order_trace_bundle(),
        "spectral_manifest": _spectral_manifest(),
        "spectral_artifact_contents": _artifact_contents(),
        "context_labels": tuple(reversed(_context_labels())),
        "samples": tuple(reversed(_samples())),
    }

    first = build_whole_run_spatial_coherence_artifact_bundle(**kwargs)
    second = build_whole_run_spatial_coherence_artifact_bundle(**kwargs)

    assert first.manifest == second.manifest
    assert first.artifact_contents == second.artifact_contents
    assert first.windows == second.windows
    assert first.summaries == second.summaries
