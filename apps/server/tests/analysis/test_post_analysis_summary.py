"""What post-analysis adds to a run's summary: metadata, warnings and data checks.

The analysis itself runs for real on minimal inputs; the simulator benchmark
covers it end to end. These cases cover run conditions the benchmark cannot
produce: thinned long runs, a degraded raw-capture finalize, unaligned vehicle
context, too-short recordings, incomplete raw replay and rows without stored
strength.
"""

from __future__ import annotations

import pytest
from test_support.raw_capture_fixtures import (
    post_analysis_metadata,
    sine_xyz_i16,
    verified_clock_sync,
)
from test_support.report_rendering import report_view_for

from vibesensor.analysis.post_analysis_input import PostAnalysisRunInput, build_post_analysis_input
from vibesensor.analysis.post_analysis_loader import LoadedPostAnalysisRun
from vibesensor.analysis.post_analysis_summary import build_post_analysis_summary
from vibesensor.recording.raw_capture import (
    RawCaptureChunkIndex,
    RawCaptureChunkTable,
    RawCaptureManifest,
    RawCaptureSensorData,
    RawCaptureSensorManifest,
    RawRunCapture,
)
from vibesensor.recording.run_suitability_codec import (
    run_suitability_from_payload,
    run_suitability_payload,
)
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings
from vibesensor.report.i18n import tr
from vibesensor.summary.run_context_warning import (
    WARNING_CODE_RAW_CAPTURE_FINALIZE_DEGRADED,
    WARNING_CODE_VEHICLE_CONTEXT_ALIGNMENT_INCOMPLETE,
)

_ROW = {"t_s": 1.0, "vibration_strength_db": 10.0}


def _run(
    run_id: str,
    rows: list[dict[str, object]] | None = None,
    *,
    raw_capture: RawRunCapture | None = None,
    metadata: dict[str, object] | None = None,
    **loaded: object,
) -> PostAnalysisRunInput:
    loaded.setdefault("total_summary_row_count", 1)
    loaded.setdefault("stride", 1)
    return build_post_analysis_input(
        LoadedPostAnalysisRun(
            run_id=run_id,
            metadata=post_analysis_metadata(run_id, **(metadata or {})),
            language="en",
            samples=sensor_frames_from_mappings(rows or [_ROW]),
            raw_capture=raw_capture,
            **loaded,  # type: ignore[arg-type]
        )
    )


def _check(summary: dict, check_key: str) -> dict:
    return next(check for check in summary["run_suitability"] if check["check_key"] == check_key)


def _raw_capture(run_id: str, *, sample_count: int = 160) -> RawRunCapture:
    """One sensor, one chunk of a 32 Hz sine, starting 0.1 s into the run."""
    run_start_us = 1_000_000
    samples = sine_xyz_i16(32.0, sample_count)
    chunk = RawCaptureChunkIndex(
        sample_start=0, sample_count=sample_count, t0_us=run_start_us + 100_000, byte_offset=0
    )
    sensor = RawCaptureSensorManifest(
        client_id="sensor-a",
        sample_rate_hz=800,
        data_file="sensor-a.raw.i16le",
        index_file="sensor-a.index.jsonl",
        sample_count=sample_count,
        chunk_count=1,
        bytes_written=int(samples.nbytes),
        first_t0_us=chunk.t0_us,
        last_t0_us=chunk.t0_us,
        clock_sync=verified_clock_sync(),
    )
    return RawRunCapture(
        manifest=RawCaptureManifest(
            run_id=run_id,
            relative_dir=f"raw-runs/{run_id}",
            sensors=(sensor,),
            total_samples=sample_count,
            total_bytes=int(samples.nbytes),
            created_at="2025-01-01T00:00:01Z",
            run_start_monotonic_us=run_start_us,
        ),
        sensors=(
            RawCaptureSensorData(
                manifest=sensor,
                samples_i16=samples,
                chunks=RawCaptureChunkTable.from_rows([chunk]),
            ),
        ),
    )


def test_thinned_long_run_records_the_sampling_and_warns() -> None:
    summary = build_post_analysis_summary(
        _run(
            "run-stride",
            total_summary_row_count=5,
            stride=3,
            sampling_method="event_preserving",
            evenly_spaced_sample_count=2,
            event_sample_count=1,
        )
    )

    metadata = summary["analysis_metadata"]
    assert metadata["sampling_method"] == "event_preserving"
    assert metadata["sampling_base_stride"] == 3
    assert metadata["sampling_evenly_spaced_sample_count"] == 2
    assert metadata["sampling_event_sample_count"] == 1
    check = _check(summary, "SUITABILITY_CHECK_ANALYSIS_SAMPLING")
    assert check["state"] == "warn"
    assert check["explanation"] == tr(
        "en", "SUITABILITY_ANALYSIS_SAMPLING_STRIDE_WARNING", stride="3"
    )


def test_degraded_raw_capture_finalize_is_kept_and_warned() -> None:
    finalize = {
        "status": "timeout",
        "queue_depth": 3,
        "error_summary": "raw capture finalize timed out",
    }
    summary = build_post_analysis_summary(
        _run("run-degraded-finalize", metadata={"raw_capture_finalize": finalize})
    )

    metadata = summary["analysis_metadata"]
    assert metadata["raw_capture_finalize_status"] == "timeout"
    assert metadata["raw_capture_finalize_queue_depth"] == 3
    assert metadata["raw_capture_finalize_error_summary"] == "raw capture finalize timed out"
    codes = [warning["code"] for warning in summary["warnings"]]
    assert WARNING_CODE_RAW_CAPTURE_FINALIZE_DEGRADED in codes


def test_unaligned_vehicle_context_is_counted_and_warned() -> None:
    row = {**_ROW, "speed_source": "gps_unaligned", "engine_rpm_source": "context_unaligned"}
    summary = build_post_analysis_summary(_run("run-vehicle-context", [row]))

    metadata = summary["analysis_metadata"]
    assert metadata["vehicle_context_unaligned_speed_sample_count"] == 1
    assert metadata["vehicle_context_unaligned_rpm_sample_count"] == 1
    codes = [warning["code"] for warning in summary["warnings"]]
    assert WARNING_CODE_VEHICLE_CONTEXT_ALIGNMENT_INCOMPLETE in codes


def test_a_raw_capture_shorter_than_a_second_fails_the_duration_check() -> None:
    row = {
        "client_id": "sensor-a",
        "t_s": 2.0,
        "sample_rate_hz": 800,
        "vibration_strength_db": 0.0,
        "dominant_freq_hz": 0.0,
    }
    summary = build_post_analysis_summary(
        _run(
            "run-raw-short",
            [row],
            raw_capture=_raw_capture("run-raw-short"),
            summary_duration_s=2.0,
        )
    )

    check = _check(summary, "SUITABILITY_CHECK_RUN_DURATION")
    assert check["state"] == "warn"
    # 160 raw samples at 800 Hz is 0.2 s; a second of raw data (800 samples) is needed.
    assert "only preserved 160 raw sample(s)" in check["explanation"]
    assert "at least 800 are needed" in check["explanation"]


def _frame_integrity_line(summary: dict, lang: str = "en") -> tuple[bool, str]:
    quality = report_view_for(summary, lang=lang).quality
    label = tr(lang, "SUITABILITY_CHECK_FRAME_INTEGRITY")
    (check,) = (check for check in quality.checks if check.label == label)
    return check.passed, check.detail


def test_incomplete_raw_replay_fails_frame_integrity_instead_of_claiming_nothing_was_lost() -> None:
    """The report must not say "no sensor data was lost" when the raw capture had gaps."""
    row = {
        "client_id": "sensor-a",
        "t_s": 2.0,
        "sample_rate_hz": 800,
        "vibration_strength_db": 0.0,
        "dominant_freq_hz": 0.0,
    }
    # The raw chunk covers 0.1-0.3 s; the summary row at 2 s has no raw window.
    run = _run("run-replay-gap", [row], raw_capture=_raw_capture("run-replay-gap"))
    without_raw = build_post_analysis_summary(_run("run-no-raw", [row]))
    summary = build_post_analysis_summary(run)

    assert _frame_integrity_line(without_raw) == (True, "No sensor data was lost.")
    assert run.raw_replay.missing_window_count == 1
    # The failing check states it; the replay-coverage warning is not repeated below it.
    assert not any(
        "raw sensor data was missing" in warning
        for warning in report_view_for(summary).quality.warnings
    )
    assert _frame_integrity_line(summary) == (
        False,
        "Some sensor data was lost or incomplete. The raw capture did not cover the whole run"
        " (0 partial and 1 missing windows, 0 timing gaps, 0 overlaps); those moments were"
        " analysed from the stored summaries.",
    )
    assert "1 ontbrekende vensters" in _frame_integrity_line(summary, "nl")[1]
    persisted = [_check(summary, "SUITABILITY_CHECK_FRAME_INTEGRITY")]
    assert run_suitability_payload(run_suitability_from_payload(persisted)) == persisted


def test_without_a_known_duration_too_few_summary_rows_fail_the_duration_check() -> None:
    summary = build_post_analysis_summary(
        _run(
            "run-summary-rows",
            [{"vibration_strength_db": 10.0}],
            metadata={"feature_interval_s": None},
            summary_duration_s=None,
        )
    )

    check = _check(summary, "SUITABILITY_CHECK_RUN_DURATION")
    assert check["state"] == "warn"
    assert "Only 1 summary row(s)" in check["explanation"]
    assert "at least 2 are needed" in check["explanation"]


def test_rows_without_stored_strength_get_it_from_peak_and_floor() -> None:
    run = _run(
        "run-derived-strength",
        [
            {
                "t_s": 1.0,
                "top_peaks": [{"hz": 14.0, "amp": 0.12}],
                "strength_peak_amp_g": 0.12,
                "strength_floor_amp_g": 0.003,
            }
        ],
    )

    assert run.samples[0].vibration_strength_db is not None
    assert run.samples[0].strength_bucket


def test_raw_backed_rows_drive_the_per_location_intensity() -> None:
    row = {
        "client_id": "sensor-a",
        "location": "front_left",
        "t_s": 0.18,
        "sample_rate_hz": 800,
        "vibration_strength_db": 0.0,
        "strength_bucket": "l0",
        "dominant_freq_hz": 0.0,
    }
    run = _run(
        "run-raw-intensity",
        [row],
        raw_capture=_raw_capture("run-raw-intensity"),
        metadata={"feature_interval_s": None},
    )
    raw_backed_strength = run.samples[0].vibration_strength_db
    assert raw_backed_strength is not None and raw_backed_strength > 0.0

    intensity = build_post_analysis_summary(run)["sensor_intensity_by_location"]

    assert len(intensity) == 1
    assert intensity[0]["p95_intensity_db"] == pytest.approx(raw_backed_strength)
    assert intensity[0]["strength_bucket_distribution"]["total"] == 1
    assert intensity[0]["strength_bucket_distribution"]["counts"]["l0"] == 0
