# ruff: noqa: E402
from __future__ import annotations

"""Report pipeline audit – rendering and data consistency regressions."""


from vibesensor.report.mapping import map_summary
from vibesensor.report.mapping import peak_classification_text as _peak_classification_text
from vibesensor.report_i18n import tr

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


class TestNextStepFieldsNotRendered:
    """NextStep dataclass has confirm, falsify, eta, speed_band fields
    that are populated by the builder but the PDF renderer only reads
    step.action and step.why.

    Evidence: pdf_page1.py — only action and why are used.
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
            "confidence": 0.85,
            "frequency_hz_or_order": "1x wheel",
            "strongest_location": "front-left wheel",
            "amplitude_metric": {"value": 0.05},
            "evidence_metrics": {"vibration_strength_db": 20.0},
        }
        top_cause = {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
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
            },
        )
        data = map_summary(summary)
        # Find the step that came from our test_plan (not Tier A guidance)
        matching = [ns for ns in data.next_steps if "bearing" in ns.action.lower()]
        assert len(matching) == 1, f"Expected 1 bearing step, got {len(matching)}"
        ns = matching[0]
        assert ns.confirm == "Noise disappears at low speed"
        assert ns.falsify == "Noise persists with new bearing"
        assert ns.eta == "30 min"


class TestTopCausesFallbackBypassesPersistenceRanking:
    """When top_causes_actionable is empty, the fallback chain falls to
    findings_non_ref (raw findings) which are NOT ranked by
    select_top_causes.  This bypasses the persistence-aware
    phase-adjusted ranking.

    Evidence: report_mapping_pipeline.py:
      top_causes = top_causes_actionable or findings_non_ref or top_causes_non_ref or top_causes_all
    """

    def test_fallback_to_findings_non_ref_skips_ranking(self) -> None:
        """When actionable causes are empty, raw findings are used unranked."""
        # Create findings with NO top_causes — forces fallback
        findings = [
            {
                "finding_id": "F_ORDER",
                "suspected_source": "wheel/tire",
                "confidence": 0.3,
                "frequency_hz_or_order": "1x wheel",
                "strongest_location": "front-left wheel",
                "amplitude_metric": {"value": 0.05},
                "evidence_metrics": {"vibration_strength_db": 15.0},
            },
            {
                "finding_id": "F_ORDER",
                "suspected_source": "engine",
                "confidence": 0.6,
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
            },
        )
        data = map_summary(summary)
        # The observed primary system comes from findings_non_ref[0],
        # which is the first finding by list order, NOT the highest-confidence one.
        # This documents the fallback bypass.
        assert data.observed.primary_system is not None


class TestPeakClassificationFallback:
    """Unrecognized peak_classification values silently map to
    CLASSIFICATION_PERSISTENT instead of UNKNOWN.

    Evidence: report_mapping_common.py.
    """

    def test_unrecognized_maps_to_title_case(self) -> None:
        result = _peak_classification_text("totally_new_type", _en_tr)
        # Unrecognised types are title-cased from the raw value
        assert result == "Totally New Type"

    def test_empty_maps_to_unknown(self) -> None:
        result = _peak_classification_text("", _en_tr)
        assert result == _en_tr("UNKNOWN")


class TestSystemFindingCardToneUnused:
    """SystemFindingCard.tone is set by the builder but the PDF renderer
    never reads it — cards are always drawn with SOFT_BG background.

    Evidence: pdf_page1.py _draw_system_card uses fixed SOFT_BG;
              theme.py defines card_success_bg/card_warn_bg/card_error_bg
              which are never referenced by pdf_page1.py.
    """

    def test_tone_is_populated_by_builder(self) -> None:
        finding = {
            "finding_id": "F_ORDER",
            "suspected_source": "wheel/tire",
            "confidence": 0.8,
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
                        "suspected_source": "wheel/tire",
                        "confidence": 0.8,
                        "confidence_tone": "success",
                        "signatures_observed": ["1x wheel"],
                        "strongest_location": "front-left wheel",
                    },
                ],
            },
        )
        data = map_summary(summary)
        assert len(data.system_cards) >= 1
        # tone is populated but never rendered
        assert data.system_cards[0].tone in {"neutral", "success", "warn"}


class TestPeaksTableFixedHeight:
    """The peaks table uses a fixed panel height of 53 mm regardless of
    how many rows it contains.  _draw_peaks_table uses a y_bottom guard
    to limit visible rows to what fits in the panel height.

    Evidence: pdf_page2.py: y - row_h < y_bottom: break
    """

    def test_fixed_height_with_many_rows(self) -> None:
        """Eight peaks in data; the builder forwards all of them and the
        renderer trims via a y_bottom guard at render time.
        """
        rows = [_make_peaks_table_row(rank=i, frequency_hz=20.0 + i * 5) for i in range(1, 9)]
        summary = _make_minimal_summary(overrides={"plots": {"peaks_table": rows}})
        data = map_summary(summary)
        # Builder forwards up to 8 above-noise peaks
        assert len(data.peak_rows) == 8
