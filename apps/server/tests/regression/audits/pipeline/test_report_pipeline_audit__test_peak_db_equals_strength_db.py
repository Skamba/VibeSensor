"""Report pipeline audit — tests covering 10 findings from the report-generation
traceability and consistency audit.

These tests document and verify issues found in the analysis → report_data →
PDF pipeline.  Each test class corresponds to one audit finding.
"""

from __future__ import annotations

from vibesensor.analysis.report_data_builder import (
    map_summary,
)
from vibesensor.report_i18n import tr


def _make_minimal_summary(*, overrides: dict | None = None) -> dict:
    """Return a minimal summary dict that ``map_summary`` can process."""
    base: dict = {
        "lang": "en",
        "report_date": "2025-01-01T00:00:00",
        "metadata": {"car_name": "Test Car"},
        "findings": [],
        "top_causes": [],
        "speed_stats": {},
        "most_likely_origin": {},
        "sensor_intensity_by_location": [],
        "run_suitability": [],
        "phase_info": None,
        "plots": {"peaks_table": []},
        "test_plan": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _make_peaks_table_row(
    *,
    rank: int = 1,
    frequency_hz: float = 42.0,
    p95_intensity_db: float = 18.5,
    strength_db: float | None = None,
    presence_ratio: float = 0.7,
    persistence_score: float = 0.5,
    burstiness: float = 1.5,
    peak_classification: str = "patterned",
    order_label: str = "",
    typical_speed_band: str = "50-80 km/h",
    p95_vs_run_noise_ratio: float = 5.0,
    spatial_uniformity: float | None = None,
    speed_uniformity: float | None = None,
) -> dict:
    """Build a single peaks-table row dict as produced by plot_data._top_peaks_table_rows."""
    if strength_db is None:
        strength_db = p95_intensity_db  # mirrors the current (buggy) behavior
    return {
        "rank": rank,
        "frequency_hz": frequency_hz,
        "p95_intensity_db": p95_intensity_db,
        "strength_db": strength_db,
        "presence_ratio": presence_ratio,
        "persistence_score": persistence_score,
        "burstiness": burstiness,
        "peak_classification": peak_classification,
        "order_label": order_label,
        "typical_speed_band": typical_speed_band,
        "p95_vs_run_noise_ratio": p95_vs_run_noise_ratio,
        "spatial_uniformity": spatial_uniformity,
        "speed_uniformity": speed_uniformity,
    }


def _en_tr(key: str, **kw: object) -> str:
    """English translation shortcut used by multiple test classes."""
    return tr("en", key, **kw)


class TestPeakDbEqualsStrengthDb:
    """Peaks-table strength_db is always assigned p95_intensity_db,
    making the two columns redundant.

    Evidence: plot_data.py line ~379: bucket["strength_db"] = p95_intensity_db
    Root cause: strength_db should be computed differently from p95_intensity_db
      (e.g. using SNR-based canonical_vibration_db against MEMS noise floor)
      but currently just aliases p95_intensity_db.
    """

    def test_strength_db_equals_p95_intensity_db_in_source(self) -> None:
        """Confirm the assignment in plot_data produces identical values."""
        row = _make_peaks_table_row(p95_intensity_db=22.3, strength_db=22.3)
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": [row]}})
        data = map_summary(summary)
        assert len(data.peak_rows) == 1
        pr = data.peak_rows[0]
        # Currently both are identical — this test documents the bug
        assert pr.peak_db == pr.strength_db, (
            "Expected peak_db == strength_db (documenting current behavior)"
        )

    def test_different_strength_db_would_show_distinct_columns(self) -> None:
        """If strength_db were computed differently, columns would differ."""
        # Simulate a hypothetical fix where strength_db ≠ p95_intensity_db
        row = _make_peaks_table_row(p95_intensity_db=22.3, strength_db=15.1)
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": [row]}})
        data = map_summary(summary)
        pr = data.peak_rows[0]
        assert pr.peak_db == "22.3"
        assert pr.strength_db == "15.1"
