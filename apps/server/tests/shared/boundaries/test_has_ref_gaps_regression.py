"""Regression: _has_ref_gaps was always False due to dual key/state bug."""

from __future__ import annotations

from vibesensor.shared.boundaries.diagnostic_case import test_run_from_summary


def _minimal_summary(
    *,
    run_suitability: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    """Smallest summary that lets test_run_from_summary() succeed."""
    return {
        "run_id": "test-run",
        "meta": {"car": {}, "session_id": "s1"},
        "findings": [],
        "top_causes": [],
        **({"run_suitability": run_suitability} if run_suitability is not None else {}),
    }


class TestHasReferenceGapsReconstruction:
    def test_reference_gap_warn_detected(self) -> None:
        """Reference gap with state='warn' must yield has_reference_gaps=True."""
        summary = _minimal_summary(
            run_suitability=[
                {"check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS", "state": "warn"},
            ],
        )
        test_run = test_run_from_summary(summary)
        assert test_run.suitability is not None
        assert test_run.suitability.has_reference_gaps

    def test_reference_complete_pass_no_gap(self) -> None:
        """Passing reference check must NOT flag gaps."""
        summary = _minimal_summary(
            run_suitability=[
                {"check_key": "SUITABILITY_CHECK_REFERENCE_COMPLETENESS", "state": "pass"},
            ],
        )
        test_run = test_run_from_summary(summary)
        assert test_run.suitability is not None
        assert not test_run.suitability.has_reference_gaps

    def test_no_suitability_payload_no_gap(self) -> None:
        """Missing suitability payload must NOT flag gaps."""
        summary = _minimal_summary()
        test_run = test_run_from_summary(summary)
        # suitability may be None; either way no gap
        if test_run.suitability is not None:
            assert not test_run.suitability.has_reference_gaps
