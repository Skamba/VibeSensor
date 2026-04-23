from __future__ import annotations

from test_support.report_helpers import diagnostics_context, wheel_metadata
from test_support.sample_scenarios import make_analysis_sample

from vibesensor.domain import DrivingPhase
from vibesensor.shared.types.whole_run_analysis import (
    WholeRunArtifactFile,
    WholeRunArtifactManifest,
    WholeRunContextWindowLabel,
    WholeRunWindowPolicy,
)
from vibesensor.use_cases.diagnostics.orders.physics import _order_hypotheses
from vibesensor.use_cases.diagnostics.orders.whole_run_traces import (
    WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY,
    build_whole_run_order_trace_artifact_bundle,
)
from vibesensor.use_cases.diagnostics.whole_run_spectra import (
    WholeRunWindowSpectralSummary,
    whole_run_window_spectral_summaries_to_jsonl_bytes,
)


def _metadata():
    return diagnostics_context(
        wheel_metadata(
            raw_sample_rate_hz=200.0,
            final_drive_ratio=2.0,
            current_gear_ratio=1.5,
        ),
        run_id="run-order-traces",
        feature_interval_s=0.5,
        fft_window_size_samples=256,
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
    speeds = (40.0, 60.0, 80.0)
    rpm_values = (1000.0, 1500.0, 2000.0)
    return tuple(
        WholeRunContextWindowLabel(
            window_index=index,
            segment_index=0,
            phase=DrivingPhase.CRUISE,
            context_coverage="full",
            speed_validity="measured",
            rpm_validity="measured",
            load_state="steady",
            speed_kmh=speed_kmh,
            speed_band="40-50",
            speed_source="gps",
            engine_rpm=engine_rpm,
            engine_rpm_source="obd2",
        )
        for index, (speed_kmh, engine_rpm) in enumerate(zip(speeds, rpm_values, strict=True))
    )


def _spectral_manifest() -> WholeRunArtifactManifest:
    return WholeRunArtifactManifest(
        run_id="run-order-traces",
        relative_dir="whole-run-artifacts/run-order-traces",
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


def _context_sample(window_index: int, *, speed_kmh: float, engine_rpm: float):
    return make_analysis_sample(
        t_s=float(window_index) * 0.5,
        speed_kmh=speed_kmh,
        engine_rpm=engine_rpm,
        client_name="context",
        client_id="context",
        location="",
        top_peaks=[],
    )


def _summary_rows(*, sensor_scale: float) -> tuple[WholeRunWindowSpectralSummary, ...]:
    metadata = _metadata()
    rows: list[WholeRunWindowSpectralSummary] = []
    for label in _context_labels():
        context_sample = _context_sample(
            label.window_index,
            speed_kmh=float(label.speed_kmh or 0.0),
            engine_rpm=float(label.engine_rpm or 0.0),
        )
        peaks = []
        for hypothesis in _order_hypotheses():
            predicted_hz, _ = hypothesis.predicted_hz(
                context_sample,
                metadata,
                metadata.tire_circumference_m,
            )
            if predicted_hz is None or predicted_hz <= 0:
                continue
            amplitude = sensor_scale / max(1, hypothesis.order)
            peaks.append(
                {
                    "hz": float(predicted_hz),
                    "amp": amplitude,
                    "vibration_strength_db": 30.0 + amplitude * 50.0,
                    "strength_bucket": "l3",
                }
            )
        rows.append(
            WholeRunWindowSpectralSummary(
                window_index=label.window_index,
                coverage_state="full",
                returned_sample_start=label.window_index * 100,
                returned_sample_count=256,
                dominant_freq_hz=peaks[0]["hz"],
                vibration_strength_db=24.0 + sensor_scale * 10.0,
                strength_peak_amp_g=max(float(peak["amp"]) for peak in peaks),
                strength_floor_amp_g=0.01,
                strength_bucket="l3",
                top_peaks=tuple(peaks),
            )
        )
    return tuple(rows)


def _artifact_contents() -> dict[str, bytes]:
    return {
        "spectral-summary:sensor-front": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(sensor_scale=0.14)
        ),
        "spectral-summary:sensor-rear": whole_run_window_spectral_summaries_to_jsonl_bytes(
            _summary_rows(sensor_scale=0.08)
        ),
    }


def _samples():
    return (
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=36.0,
            client_name="front-left",
            client_id="sensor-front",
            location="front-left",
            top_peaks=[{"hz": 5.0, "amp": 0.14}],
        ),
        make_analysis_sample(
            t_s=0.0,
            speed_kmh=36.0,
            client_name="rear-left",
            client_id="sensor-rear",
            location="rear-left",
            top_peaks=[{"hz": 5.0, "amp": 0.08}],
        ),
    )


def test_build_whole_run_order_trace_artifact_bundle_emits_supported_candidate_traces() -> None:
    bundle = build_whole_run_order_trace_artifact_bundle(
        run_id="run-order-traces",
        metadata=_metadata(),
        spectral_manifest=_spectral_manifest(),
        spectral_artifact_contents=_artifact_contents(),
        context_labels=_context_labels(),
        samples=_samples(),
    )

    assert bundle.manifest.artifact(WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY) is not None
    assert bundle.artifact_contents[WHOLE_RUN_ORDER_TRACE_ARTIFACT_KEY].count(b"\n") == len(
        bundle.points
    )
    assert {point.order_family for point in bundle.points} == {"wheel", "driveshaft", "engine"}
    wheel_1x = [
        point
        for point in bundle.points
        if point.hypothesis_key == "wheel_1x" and point.harmonic == 1
    ]
    assert len(wheel_1x) == 3
    assert [point.window_index for point in wheel_1x] == [0, 1, 2]
    assert all(point.eligible for point in wheel_1x)
    assert all(point.matched for point in wheel_1x)
    assert all(point.strongest_location == "front-left" for point in wheel_1x)


def test_build_whole_run_order_trace_artifact_bundle_is_deterministic() -> None:
    kwargs = {
        "run_id": "run-order-traces",
        "metadata": _metadata(),
        "spectral_manifest": _spectral_manifest(),
        "spectral_artifact_contents": _artifact_contents(),
        "context_labels": tuple(reversed(_context_labels())),
        "samples": tuple(reversed(_samples())),
    }

    first = build_whole_run_order_trace_artifact_bundle(**kwargs)
    second = build_whole_run_order_trace_artifact_bundle(**kwargs)

    assert first.manifest == second.manifest
    assert first.artifact_contents == second.artifact_contents
    assert first.points == second.points
