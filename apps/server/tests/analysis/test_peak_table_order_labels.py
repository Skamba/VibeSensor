"""Peak-table rows tracked by an order finding carry its order code and are patterned."""

from __future__ import annotations

from test_support.findings import make_finding

from vibesensor.analysis._view_types import PeakTableRowData
from vibesensor.analysis.peaks.table import annotate_peak_rows_with_order_labels
from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import OrderMatchObservation


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


def test_every_row_an_order_sweeps_through_is_labelled_and_patterned() -> None:
    # A speed sweep moves wheel 1x across 10-12 Hz: all three rows belong to it.
    finding = _order_finding(
        "wheel_1x", VibrationSource.WHEEL_TIRE, *([10.4] * 5 + [11.5] * 5 + [12.2] * 5)
    )
    rows = annotate_peak_rows_with_order_labels(
        [_peak_row(10.0), _peak_row(11.0), _peak_row(12.0), _peak_row(30.0, "persistent")],
        [finding],
    )
    assert [row.order_label for row in rows] == ["T1", "T1", "T1", ""]
    assert [row.peak_classification for row in rows] == [
        "patterned",
        "patterned",
        "patterned",
        "persistent",
    ]
    assert rows[0].suspected_source == "wheel/tire"


def test_rows_with_only_stray_matches_stay_unlabelled() -> None:
    finding = _order_finding("wheel_1x", VibrationSource.WHEEL_TIRE, *([11.2] * 40), 25.3)
    rows = annotate_peak_rows_with_order_labels([_peak_row(11.0), _peak_row(25.0)], [finding])
    assert [row.order_label for row in rows] == ["T1", ""]


def test_the_order_with_most_points_in_a_row_claims_it() -> None:
    wheel = _order_finding("wheel_2x", VibrationSource.WHEEL_TIRE, *([24.5] * 4))
    engine = _order_finding("engine_2x", VibrationSource.ENGINE, *([24.2] * 9 + [70.1] * 9))
    rows = annotate_peak_rows_with_order_labels([_peak_row(24.0), _peak_row(70.0)], [wheel, engine])
    assert [row.order_label for row in rows] == ["E2", "E2"]


def test_peak_findings_never_label_rows() -> None:
    peak = make_finding(
        finding_id="F002",
        finding_key="peak_41hz",
        matched_points=(
            OrderMatchObservation(
                predicted_hz=41.0, matched_hz=41.0, rel_error=0.0, amp=0.1, location="Trunk"
            ),
        )
        * 5,
    )
    rows = annotate_peak_rows_with_order_labels([_peak_row(41.0)], [peak])
    assert rows[0].order_label == ""
    assert rows[0].peak_classification == "transient"
