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
    _draw_next_steps_table,
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


class TestNextStepFieldsNotRendered:
    """NextStep dataclass has confirm, falsify, eta, speed_band fields
    that are populated by the builder but the PDF renderer only reads
    step.action and step.why.

    Evidence: pdf_builder.py lines 673-675 — only action and why are used.
    Impact: actionable diagnostic guidance is lost in PDF output.
    """

    def test_nextstep_fields_populated_by_builder(self) -> None:
        """Verify the builder does populate these fields."""
        step = {
            "what": "Inspect front-left wheel bearing",
            "why": "Dominant order in front-left sensor",
            "confirm": "Noise disappears at low speed",
            "falsify": "Noise persists with new bearing",
            "eta": "30 min",
            "speed_band": "60-90 km/h",
        }
        # Need a high-confidence finding + top_cause so the builder does NOT
        # fall into Tier A (which replaces test_plan steps with generic guidance).
        finding = {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "confidence_0_to_1": 0.85,
            "frequency_hz_or_order": "1x wheel",
            "strongest_location": "front-left wheel",
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {"vibration_strength_db": 20.0},
        }
        top_cause = {
            "finding_id": "F_ORDER",
            "source": "wheel/tire",
            "confidence": 0.85,
            "confidence_tone": "success",
            "signatures_observed": ["1x wheel"],
            "strongest_location": "front-left wheel",
        }
        summary = _make_minimal_summary(
            overrides={
                "test_plan": [step],
                "findings": [finding],
                "top_causes": [top_cause],
            }
        )
        data = map_summary(summary)
        # Find the step that came from our test_plan (not Tier A guidance)
        matching = [ns for ns in data.next_steps if "bearing" in ns.action.lower()]
        assert len(matching) == 1, f"Expected 1 bearing step, got {len(matching)}"
        ns = matching[0]
        assert ns.confirm == "Noise disappears at low speed"
        assert ns.falsify == "Noise persists with new bearing"
        assert ns.eta == "30 min"
        assert ns.speed_band == "60-90 km/h"

    def test_pdf_renderer_renders_confirm_falsify_eta(self) -> None:
        """After fix: renderer now accesses .action, .why, and optional fields."""
        source = inspect.getsource(_draw_next_steps_table)
        assert "step.action" in source
        assert "step.why" in source
        # These fields are NOW referenced after the fix:
        assert "step.confirm" in source
        assert "step.falsify" in source
        assert "step.eta" in source
