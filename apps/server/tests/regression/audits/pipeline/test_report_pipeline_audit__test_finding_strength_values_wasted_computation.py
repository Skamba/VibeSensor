"""Report pipeline audit — tests covering 10 findings from the report-generation
traceability and consistency audit.

These tests document and verify issues found in the analysis → report_data →
PDF pipeline.  Each test class corresponds to one audit finding.
"""

from __future__ import annotations

from vibesensor.analysis.report_data_builder import (
    _finding_strength_values,
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


class TestFindingStrengthValuesWastedComputation:
    """_finding_strength_values always extracts peak_amp from
    amplitude_metric.value, but if evidence_metrics.vibration_strength_db
    is present, it returns immediately without using peak_amp.
    peak_amp is only used in the second fallback path.

    Evidence: report_data_builder.py lines 118-138.
    Impact: minor inefficiency; peak_amp is computed even when not needed.
    """

    def test_early_return_with_db_present(self) -> None:
        finding = {
            "amplitude_metric": {"value": 0.123},
            "evidence_metrics": {"vibration_strength_db": 25.0},
        }
        result = _finding_strength_values(finding)
        # Returns 25.0 immediately without using peak_amp
        assert result == 25.0

    def test_fallback_uses_peak_amp_and_noise_floor(self) -> None:
        finding = {
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {
                # No vibration_strength_db → falls through to canonical calc
                "mean_noise_floor": 0.01,
            },
        }
        result = _finding_strength_values(finding)
        # Should compute canonical_vibration_db(0.05, 0.01)
        assert result is not None
        assert result > 0

    def test_returns_none_when_no_metrics(self) -> None:
        result = _finding_strength_values({})
        assert result is None
