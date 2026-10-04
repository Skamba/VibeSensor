"""Non-order peaks: how they are classified, ranked, banded and given a noise floor."""

from __future__ import annotations

import pytest
from test_support.findings import make_finding
from test_support.report_helpers import analysis_sample_with_peaks as sample

from vibesensor.analysis._sample_metrics import _estimate_strength_floor_amp_g
from vibesensor.analysis._view_types import PeakTableRowData
from vibesensor.analysis.findings import _build_persistent_peak_findings
from vibesensor.analysis.peaks.classification import classify_peak_type
from vibesensor.analysis.peaks.table import (
    annotate_peak_rows_with_order_labels,
    top_peaks_table_rows,
)
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.dsp.vibration_strength import percentile
from vibesensor.recording.sensor_frame_mapping import sensor_frames_from_mappings


def _findings_at(samples: list[dict], frequency: str) -> list:
    findings = _build_persistent_peak_findings(
        samples=sensor_frames_from_mappings(samples),
        order_finding_freqs=set(),
        lang="en",
        per_sample_phases=None,
    )
    return [
        finding
        for finding in findings
        if frequency in (finding.order or "") or frequency in str(finding.frequency_hz)
    ]


@pytest.mark.parametrize(
    ("presence_ratio", "burstiness", "expected"),
    [
        pytest.param(0.80, 1.5, "patterned", id="high_presence_low_burstiness"),
        pytest.param(0.45, 2.5, "patterned", id="moderate_presence_low_burstiness"),
        pytest.param(0.30, 3.5, "persistent", id="moderate_presence_moderate_burstiness"),
        pytest.param(0.05, 1.0, "transient", id="low_presence"),
        pytest.param(0.30, 8.0, "transient", id="high_burstiness"),
        pytest.param(0.40, 2.9, "patterned", id="boundary_patterned"),
        pytest.param(0.20, 4.0, "persistent", id="boundary_persistent_not_patterned"),
    ],
)
def test_peak_classification(presence_ratio: float, burstiness: float, expected: str) -> None:
    assert classify_peak_type(presence_ratio=presence_ratio, burstiness=burstiness) == expected


def test_a_persistent_peak_ranks_above_a_single_loud_spike() -> None:
    samples = []
    for i in range(20):
        peaks = [{"hz": 30.0, "amp": 0.04}]
        if i == 0:
            peaks.append({"hz": 80.0, "amp": 1.0})
        samples.append(sample(float(i) * 0.5, 85.0, peaks))

    rows = top_peaks_table_rows(sensor_frames_from_mappings(samples))

    assert len(rows) >= 2
    assert rows[0].frequency_hz == 30.0
    assert rows[0].presence_ratio > 0.5


def test_a_peak_seen_evenly_everywhere_is_baseline_noise() -> None:
    samples = []
    for speed in (35.0, 55.0, 75.0, 95.0):
        for location in ("Front Left", "Front Right", "Rear Left", "Rear Right"):
            for rep in range(3):
                peaks = [{"hz": 10.0, "amp": 0.01}]
                if rep == 0:
                    amp = 0.20 if (speed, location) == (35.0, "Front Left") else 0.05
                    peaks.append({"hz": 25.0, "amp": amp})
                samples.append(
                    sample(float(len(samples)) * 0.5, speed, peaks, client_name=location)
                )

    assert _findings_at(samples, "25")[0].peaks.classification == "baseline_noise"
    rows = top_peaks_table_rows(sensor_frames_from_mappings(samples), top_n=12, freq_bin_hz=1.0)
    row_25 = next(row for row in rows if abs(row.frequency_hz - 25.0) <= 0.5)
    assert row_25.peaks.classification == "baseline_noise"


def test_strongest_speed_band_follows_the_amplitude() -> None:
    samples = [
        sample(
            float(idx) * 0.5,
            float(speed),
            [{"hz": 43.0, "amp": 0.08 if 70 <= speed <= 90 else 0.01}],
        )
        for idx, speed in enumerate(range(40, 121))
    ]

    target = _findings_at(samples, "43")[0]

    assert target.strongest_speed_band in {"70-80 km/h", "80-90 km/h"}


def _floor_sample(peaks: list[tuple[float, float]], *, floor_amp: float | None = None) -> object:
    row: dict[str, object] = {
        "top_peaks": [{"hz": hz, "amp": amp} for hz, amp in peaks],
        "speed_kmh": 80.0,
    }
    if floor_amp is not None:
        row["strength_floor_amp_g"] = floor_amp
    return sensor_frames_from_mappings([row])[0]


def test_noise_floor_falls_back_to_the_quiet_end_of_the_peaks() -> None:
    assert (
        _estimate_strength_floor_amp_g(_floor_sample([(20.0, 0.2), (30.0, 0.3)], floor_amp=0.0))
        is None
    )
    amps = [0.1, 0.2, 0.3]
    assert _estimate_strength_floor_amp_g(
        _floor_sample([(10.0, a) for a in amps])
    ) == pytest.approx(percentile(sorted(amps), 0.20))


def _peak_row(frequency_hz: float, classification: str = "transient") -> PeakTableRowData:
    return PeakTableRowData(
        rank=1,
        frequency_hz=frequency_hz,
        order_label="",
        suspected_source="",
        max_intensity_db=None,
        median_intensity_db=None,
        p95_intensity_db=None,
        run_noise_baseline_db=None,
        median_vs_run_noise_ratio=0.0,
        p95_vs_run_noise_ratio=0.0,
        strength_floor_db=None,
        strength_db=None,
        presence_ratio=0.3,
        burstiness=2.0,
        persistence_score=0.0,
        peak_classification=classification,
        typical_speed_band="-",
    )


def _order_finding(key: str, source: VibrationSource, *matched_hz: float) -> Finding:
    return make_finding(
        finding_id="F001",
        finding_key=key,
        suspected_source=source,
        matched_points=tuple(
            OrderMatchObservation(
                predicted_hz=hz, matched_hz=hz, rel_error=0.0, amp=0.1, location="Front Left Wheel"
            )
            for hz in matched_hz
        ),
    )


def test_the_order_with_most_points_in_a_row_claims_it() -> None:
    wheel = _order_finding("wheel_2x", VibrationSource.WHEEL_TIRE, *([24.5] * 4))
    engine = _order_finding("engine_2x", VibrationSource.ENGINE, *([24.2] * 9 + [70.1] * 9))
    rows = annotate_peak_rows_with_order_labels([_peak_row(24.0), _peak_row(70.0)], [wheel, engine])
    assert [row.order_label for row in rows] == ["E2", "E2"]
