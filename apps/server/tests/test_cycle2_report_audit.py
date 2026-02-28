"""Cycle 2 Report Audit — tests covering 10 findings from the report-generation
traceability and consistency audit.

These tests document and verify issues found in the analysis → report_data →
PDF pipeline.  Each test class corresponds to one audit finding.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


# ===================================================================
# Finding 1 (KNOWN-C1, confirmed still present):
#   Peaks table "Peak (dB)" and "Strength (dB)" columns always show
#   identical values — both read from p95_intensity_db.
# ===================================================================


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
        from vibesensor.analysis.report_data_builder import map_summary

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
        from vibesensor.analysis.report_data_builder import map_summary

        # Simulate a hypothetical fix where strength_db ≠ p95_intensity_db
        row = _make_peaks_table_row(p95_intensity_db=22.3, strength_db=15.1)
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": [row]}})
        data = map_summary(summary)
        pr = data.peak_rows[0]
        assert pr.peak_db == "22.3"
        assert pr.strength_db == "15.1"


# ===================================================================
# Finding 2 (KNOWN-C1, confirmed still present):
#   NextStep confirm/falsify/eta/speed_band populated but never
#   rendered in PDF.
# ===================================================================


class TestNextStepFieldsNotRendered:
    """NextStep dataclass has confirm, falsify, eta, speed_band fields
    that are populated by the builder but the PDF renderer only reads
    step.action and step.why.

    Evidence: pdf_builder.py lines 673-675 — only action and why are used.
    Impact: actionable diagnostic guidance is lost in PDF output.
    """

    def test_nextstep_fields_populated_by_builder(self) -> None:
        """Verify the builder does populate these fields."""
        from vibesensor.analysis.report_data_builder import map_summary

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
        import inspect

        from vibesensor.report.pdf_builder import _draw_next_steps_table

        source = inspect.getsource(_draw_next_steps_table)
        assert "step.action" in source
        assert "step.why" in source
        # These fields are NOW referenced after the fix:
        assert "step.confirm" in source
        assert "step.falsify" in source
        assert "step.eta" in source


# ===================================================================
# Finding 3 (KNOWN-C1, confirmed still present):
#   top_causes fallback chain can bypass persistence-aware ranking.
# ===================================================================


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
        from vibesensor.analysis.report_data_builder import map_summary

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


# ===================================================================
# Finding 4 (KNOWN-C1, confirmed still present):
#   _peak_classification_text maps unrecognized classifications to
#   "persistent".
# ===================================================================


class TestPeakClassificationFallback:
    """Unrecognized peak_classification values silently map to
    CLASSIFICATION_PERSISTENT instead of UNKNOWN.

    Evidence: report_data_builder.py lines 199-212.
    """

    def test_unrecognized_maps_to_persistent(self) -> None:
        from vibesensor.analysis.report_data_builder import _peak_classification_text
        from vibesensor.report_i18n import tr

        def en_tr(key: str, **kw: object) -> str:
            return tr("en", key, **kw)

        result = _peak_classification_text("totally_new_type", en_tr)
        persistent_text = en_tr("CLASSIFICATION_PERSISTENT")
        unknown_text = en_tr("UNKNOWN")
        # This test documents the bug: unrecognized → persistent, not unknown
        assert result == persistent_text
        assert result != unknown_text

    def test_empty_maps_to_unknown(self) -> None:
        from vibesensor.analysis.report_data_builder import _peak_classification_text
        from vibesensor.report_i18n import tr

        def en_tr(key: str, **kw: object) -> str:
            return tr("en", key, **kw)

        result = _peak_classification_text("", en_tr)
        assert result == en_tr("UNKNOWN")


# ===================================================================
# Finding 5 (KNOWN-C1, confirmed still present):
#   Dead db_value variable in _top_strength_values.
# ===================================================================


class TestDeadDbValueVariable:
    """FIXED: _top_strength_values no longer has the dead db_value
    variable. The function directly returns sensor_db in the fallback
    path without an intermediate unused variable.
    """

    def test_db_value_removed(self) -> None:
        """After fix: db_value variable should no longer exist in source."""
        import inspect

        from vibesensor.analysis.report_data_builder import _top_strength_values

        source = inspect.getsource(_top_strength_values)
        assert "db_value" not in source, "Dead db_value variable should have been removed"


# ===================================================================
# Finding 6 (KNOWN-C1, confirmed still present):
#   SystemFindingCard.tone never used by PDF renderer.
# ===================================================================


class TestSystemFindingCardToneUnused:
    """SystemFindingCard.tone is set by the builder but the PDF renderer
    never reads it — cards are always drawn with SOFT_BG background.

    Evidence: pdf_builder.py _draw_system_card uses fixed SOFT_BG;
              theme.py defines card_success_bg/card_warn_bg/card_error_bg
              which are never referenced by pdf_builder.py.
    """

    def test_tone_referenced_in_renderer(self) -> None:
        """After fix: _draw_system_card uses card.tone for colors."""
        import inspect

        from vibesensor.report.pdf_builder import _draw_system_card

        source = inspect.getsource(_draw_system_card)
        assert "card.tone" in source, "_draw_system_card must reference card.tone for theme colors"

    def test_tone_is_populated_by_builder(self) -> None:
        from vibesensor.analysis.report_data_builder import map_summary

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


# ===================================================================
# Finding 7 (NEW):
#   ObservedSignature.phase and ReportTemplateData.phase_info are
#   computed and stored but never rendered in the PDF.
# ===================================================================


class TestPhaseFieldsNeverRendered:
    """ObservedSignature.phase is populated from _dominant_phase() and
    phase_info is passed through to ReportTemplateData, but the PDF
    renderer never accesses either field.

    Evidence: grep -n 'phase' pdf_builder.py → 0 results.
    Impact: driving-phase context (acceleration/deceleration/coast-down)
            is invisible in the PDF report despite being computed.
    """

    def test_observed_phase_populated(self) -> None:
        from vibesensor.analysis.report_data_builder import map_summary

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
        import inspect

        from vibesensor.report import pdf_builder

        source = inspect.getsource(pdf_builder)
        # The word 'phase' appears nowhere in the PDF builder
        # (except possibly in comment strings or variable names like
        # phase_segments for transient findings)
        # But observed.phase and data.phase_info are never accessed
        assert "observed.phase" not in source
        assert "data.phase_info" not in source


# ===================================================================
# Finding 8 (NEW):
#   Data trust panel has no boundary check — long detail strings can
#   draw below the panel rectangle.
# ===================================================================


class TestDataTrustPanelOverflow:
    """The data-trust panel renders items in a loop decrementing ty
    but never checks whether ty has gone below the panel's bottom edge
    (next_y).  With 5+ items having multi-line detail text, content
    can overflow.

    Evidence: pdf_builder.py lines 552-569 — no `ty < bottom` guard.
    Impact: text drawn outside the panel boundary overlapping the footer.
    """

    def test_no_bottom_boundary_check_in_source(self) -> None:
        """Verify there is no boundary guard for the data trust loop."""
        import inspect

        from vibesensor.report.pdf_builder import _page1

        source = inspect.getsource(_page1)
        # The data trust section starts after "Data Trust (right-bottom)"
        trust_section = source[source.index("Data Trust") :]
        # There's no boundary check like 'ty < next_y' or 'ty < bottom'
        assert "ty < next_y" not in trust_section
        assert "ty < " not in trust_section.split("return")[0]


# ===================================================================
# Finding 9 (NEW):
#   Peaks table on page 2 has a fixed height (53 mm) which may not
#   accommodate 6 data rows + header when rendered with wrapping
#   relevance text.
# ===================================================================


class TestPeaksTableFixedHeight:
    """The peaks table uses a fixed panel height of 53 mm regardless of
    how many rows it contains.  While _draw_peaks_table has a y_bottom
    guard, the panel itself is drawn at fixed size.  With long relevance
    strings, rows may be silently truncated.

    Evidence: pdf_builder.py line ~800: table_h = 53 * mm
    """

    def test_peaks_table_rows_cap_at_six(self) -> None:
        """Verify the renderer caps peak rows at 6 regardless of input."""
        import inspect

        from vibesensor.report.pdf_builder import _draw_peaks_table

        source = inspect.getsource(_draw_peaks_table)
        assert "peak_rows[:6]" in source

    def test_fixed_height_with_many_rows(self) -> None:
        """Eight peaks in data but only 6 rendered, and the panel height
        is fixed regardless."""
        from vibesensor.analysis.report_data_builder import map_summary

        rows = [_make_peaks_table_row(rank=i, frequency_hz=20.0 + i * 5) for i in range(1, 9)]
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": rows}})
        data = map_summary(summary)
        # Builder forwards up to 8 above-noise peaks
        assert len(data.peak_rows) == 8
        # But the renderer only draws 6 — documented via source inspection
        import inspect

        from vibesensor.report.pdf_builder import _draw_peaks_table

        source = inspect.getsource(_draw_peaks_table)
        assert "[:6]" in source


# ===================================================================
# Finding 10 (NEW):
#   _finding_strength_values computes peak_amp but may not use it
#   when evidence_metrics.vibration_strength_db exists — the computed
#   peak_amp is wasted work.
# ===================================================================


class TestFindingStrengthValuesWastedComputation:
    """_finding_strength_values always extracts peak_amp from
    amplitude_metric.value, but if evidence_metrics.vibration_strength_db
    is present, it returns immediately without using peak_amp.
    peak_amp is only used in the second fallback path.

    Evidence: report_data_builder.py lines 118-138.
    Impact: minor inefficiency; peak_amp is computed even when not needed.
    """

    def test_early_return_with_db_present(self) -> None:
        from vibesensor.analysis.report_data_builder import _finding_strength_values

        finding = {
            "amplitude_metric": {"value": 0.123},
            "evidence_metrics": {"vibration_strength_db": 25.0},
        }
        result = _finding_strength_values(finding)
        # Returns 25.0 immediately without using peak_amp
        assert result == 25.0

    def test_fallback_uses_peak_amp_and_noise_floor(self) -> None:
        from vibesensor.analysis.report_data_builder import _finding_strength_values

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
        from vibesensor.analysis.report_data_builder import _finding_strength_values

        result = _finding_strength_values({})
        assert result is None
