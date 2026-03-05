"""Report pipeline audit — tests covering 10 findings from the report-generation
traceability and consistency audit.

These tests document and verify issues found in the analysis → report_data →
PDF pipeline.  Each test class corresponds to one audit finding.
"""

from __future__ import annotations

import inspect

from vibesensor.analysis.report_data_builder import (
    map_summary,
)
from vibesensor.report import pdf_builder
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


class TestPhaseFieldsNeverRendered:
    """ObservedSignature.phase is populated from _dominant_phase() and
    phase_info is passed through to ReportTemplateData, but the PDF
    renderer never accesses either field.

    Evidence: grep -n 'phase' pdf_builder.py → 0 results.
    Impact: driving-phase context (acceleration/deceleration/coast-down)
            is invisible in the PDF report despite being computed.
    """

    def test_observed_phase_populated(self) -> None:
        summary = _make_minimal_summary(
            overrides={
                "phase_info": {
                    "phase_counts": {
                        "idle": 5,
                        "acceleration": 50,
                        "cruise": 100,
                        "deceleration": 20,
                    }
                }
            }
        )
        data = map_summary(summary)
        # phase is populated
        assert data.observed.phase is not None
        assert data.observed.phase == "cruise"
        # phase_info is passed through
        assert data.phase_info is not None
        assert "phase_counts" in data.phase_info

    def test_phase_not_in_pdf_renderer_source(self) -> None:
        source = inspect.getsource(pdf_builder)
        # The word 'phase' appears nowhere in the PDF builder
        # (except possibly in comment strings or variable names like
        # phase_segments for transient findings)
        # But observed.phase and data.phase_info are never accessed
        assert "observed.phase" not in source
        assert "data.phase_info" not in source
