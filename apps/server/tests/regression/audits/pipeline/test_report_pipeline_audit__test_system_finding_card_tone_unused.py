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
    _draw_system_card,
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


class TestSystemFindingCardToneUnused:
    """SystemFindingCard.tone is set by the builder but the PDF renderer
    never reads it — cards are always drawn with SOFT_BG background.

    Evidence: pdf_builder.py _draw_system_card uses fixed SOFT_BG;
              theme.py defines card_success_bg/card_warn_bg/card_error_bg
              which are never referenced by pdf_builder.py.
    """

    def test_tone_referenced_in_renderer(self) -> None:
        """After fix: _draw_system_card uses card.tone for colors."""
        source = inspect.getsource(_draw_system_card)
        assert "card.tone" in source, "_draw_system_card must reference card.tone for theme colors"

    def test_tone_is_populated_by_builder(self) -> None:
        finding = {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.8,
            "frequency_hz_or_order": "1x wheel",
            "strongest_location": "front-left wheel",
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {"vibration_strength_db": 15.0},
        }
        summary = _make_minimal_summary(
            overrides={
                "findings": [finding],
                "top_causes": [
                    {
                        "finding_id": "F_ORDER",
                        "source": "wheel/tire",
                        "confidence": 0.8,
                        "confidence_tone": "success",
                        "signatures_observed": ["1x wheel"],
                        "strongest_location": "front-left wheel",
                    }
                ],
            }
        )
        data = map_summary(summary)
        assert len(data.system_cards) >= 1
        # tone is populated but never rendered
        assert data.system_cards[0].tone in {"neutral", "success", "warn"}
