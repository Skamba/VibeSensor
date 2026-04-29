"""Public report-analysis contract regressions."""

from __future__ import annotations

from test_support.core import standard_metadata
from test_support.sample_scenarios import make_sample

from vibesensor.adapters.analysis_summary import summarize_run_data
from vibesensor.shared.boundaries.reporting import prepare_report_input
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase
from vibesensor.use_cases.history.report_document import build_report_document

_VALID_PHASES = frozenset(phase.value for phase in DrivingPhase)


def _phased_summary() -> dict[str, object]:
    samples = [
        make_sample(
            t_s=float(idx),
            speed_kmh=0.0,
            client_name="Front Left",
            vibration_strength_db=5.0,
        )
        for idx in range(5)
    ]
    samples.extend(
        make_sample(
            t_s=float(idx),
            speed_kmh=60.0,
            client_name="Front Left",
            vibration_strength_db=22.0,
        )
        for idx in range(5, 15)
    )
    return summarize_run_data(standard_metadata(), samples)


def _multi_sensor_summary() -> dict[str, object]:
    samples: list[dict[str, object]] = []
    for idx in range(15):
        t_s = float(idx)
        speed_kmh = 50.0 + idx
        samples.append(
            make_sample(
                t_s=t_s,
                speed_kmh=speed_kmh,
                client_name="Front Left",
                vibration_strength_db=24.0,
            )
        )
        samples.append(
            make_sample(
                t_s=t_s,
                speed_kmh=speed_kmh,
                client_name="Rear Right",
                vibration_strength_db=12.0,
            )
        )
    return summarize_run_data(standard_metadata(), samples, include_samples=False)


def test_summary_plots_emit_phase_labeled_vibration_points() -> None:
    summary = _phased_summary()

    vib_magnitude = summary["plots"]["vib_magnitude"]
    assert vib_magnitude

    phases_seen = {phase for _t_s, _strength_db, phase in vib_magnitude}
    for t_s, strength_db, phase in vib_magnitude:
        assert isinstance(t_s, float)
        assert isinstance(strength_db, float)
        assert phase in _VALID_PHASES

    assert DrivingPhase.IDLE.value in phases_seen
    assert (
        DrivingPhase.CRUISE.value in phases_seen or DrivingPhase.ACCELERATION.value in phases_seen
    )


def test_summary_phase_segments_cover_the_public_run_range() -> None:
    summary = _phased_summary()

    phase_segments = summary["phase_segments"]
    plot_phase_segments = summary["plots"]["phase_segments"]

    assert phase_segments
    assert plot_phase_segments
    assert len(plot_phase_segments) == len(phase_segments)
    assert min(float(segment["start_t_s"]) for segment in phase_segments) <= 0.0
    assert max(float(segment["end_t_s"]) for segment in phase_segments) >= 14.0
    assert sum(int(segment["sample_count"]) for segment in phase_segments) == 15
    assert {segment["phase"] for segment in phase_segments}.issubset(_VALID_PHASES)


def test_build_report_document_uses_public_summary_sensor_outputs() -> None:
    summary = _multi_sensor_summary()

    document = build_report_document(prepare_report_input(summary))

    assert document.sensor_count == 2
    assert document.sensor_locations == ["Front Left", "Rear Right"]
    assert [row.location for row in document.sensor_intensity_by_location] == [
        "Front Left",
        "Rear Right",
    ]
