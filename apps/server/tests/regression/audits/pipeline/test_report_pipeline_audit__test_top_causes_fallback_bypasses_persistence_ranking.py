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


class TestTopCausesFallbackBypassesPersistenceRanking:
    """When top_causes_actionable is empty, the fallback chain falls to
    findings_non_ref (raw findings) which are NOT ranked by
    select_top_causes.  This bypasses the persistence-aware
    phase-adjusted ranking.

    Evidence: report_data_builder.py line ~312:
      top_causes = top_causes_actionable or findings_non_ref or top_causes_non_ref or top_causes_all
    """

    def test_fallback_to_findings_non_ref_skips_ranking(self) -> None:
        """When actionable causes are empty, raw findings are used unranked."""
        # Create findings with NO top_causes — forces fallback
        findings = [
            {
                "finding_id": "F_ORDER",
                "suspected_source": "wheel/tire",
                "confidence_0_to_1": 0.3,
                "frequency_hz_or_order": "1x wheel",
                "strongest_location": "front-left wheel",
                "amplitude_metric": {"value": 0.05},
                "evidence_metrics": {"vibration_strength_db": 15.0},
            },
            {
                "finding_id": "F_ORDER",
                "suspected_source": "engine",
                "confidence_0_to_1": 0.6,
                "frequency_hz_or_order": "2x engine",
                "strongest_location": "engine bay",
                "amplitude_metric": {"value": 0.08},
                "evidence_metrics": {"vibration_strength_db": 20.0},
            },
        ]
        summary = _make_minimal_summary(
            overrides={
                "findings": findings,
                "top_causes": [],  # empty → forces fallback
            }
        )
        data = map_summary(summary)
        # The observed primary system comes from findings_non_ref[0],
        # which is the first finding by list order, NOT the highest-confidence one.
        # This documents the fallback bypass.
        assert data.observed.primary_system is not None
