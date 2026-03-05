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
from vibesensor.report.pdf_builder import (
    _draw_peaks_table,
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


class TestPeaksTableFixedHeight:
    """The peaks table uses a fixed panel height of 53 mm regardless of
    how many rows it contains.  While _draw_peaks_table has a y_bottom
    guard, the panel itself is drawn at fixed size.  With long relevance
    strings, rows may be silently truncated.

    Evidence: pdf_builder.py line ~800: table_h = 53 * mm
    """

    def test_peaks_table_rows_cap_at_six(self) -> None:
        """Verify the renderer caps peak rows at 6 regardless of input."""
        source = inspect.getsource(_draw_peaks_table)
        assert "peak_rows[:6]" in source

    def test_fixed_height_with_many_rows(self) -> None:
        """Eight peaks in data but only 6 rendered, and the panel height
        is fixed regardless."""
        rows = [_make_peaks_table_row(rank=i, frequency_hz=20.0 + i * 5) for i in range(1, 9)]
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": rows}})
        data = map_summary(summary)
        # Builder forwards up to 8 above-noise peaks
        assert len(data.peak_rows) == 8
        # But the renderer only draws 6 — documented via source inspection
        source = inspect.getsource(_draw_peaks_table)
        assert "[:6]" in source
