"""Tests for Cycle 1 fixes: strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting."""

from __future__ import annotations

import math

import pytest
from vibesensor_core.vibration_strength import (
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)


class TestStrengthFloorFallback:
    """Regression: strength_floor_amp_g must not return 0.0 when all bins
    are within peak exclusion zones, since 0.0 floor produces ~140 dB."""

    def test_all_bins_excluded_falls_back_to_p20(self) -> None:
        """When every bin is excluded by peaks, fall back to P20 noise floor."""
        # 5 bins, one dominant peak in the center.  With exclusion_hz=10.0
        # every bin falls within the exclusion zone around the peak.
        freq = [5.0, 6.0, 7.0, 8.0, 9.0]
        amps = [0.001, 0.002, 0.1, 0.002, 0.001]
        peak_indexes = [2]  # peak at 7 Hz

        floor = strength_floor_amp_g(
            freq_hz=freq,
            combined_spectrum_amp_g=amps,
            peak_indexes=peak_indexes,
            exclusion_hz=10.0,  # excludes everything
            min_hz=5.0,
            max_hz=9.0,
        )
        # Should NOT be 0.0 — must fall back to P20
        assert floor > 0.0, "Floor must not be 0.0 when all bins are excluded"

        # Verify the dB value is sane (not 140+)
        db = vibration_strength_db_scalar(
            peak_band_rms_amp_g=0.1,
            floor_amp_g=floor,
        )
        assert db < 80, f"Expected sane dB (<80), got {db}"
        assert math.isfinite(db)

    def test_normal_case_unchanged(self) -> None:
        """When bins survive exclusion, the original median behavior is used."""
        freq = [5.0, 6.0, 7.0, 8.0, 9.0]
        amps = [0.001, 0.002, 0.1, 0.002, 0.001]
        peak_indexes = [2]  # peak at 7 Hz

        floor = strength_floor_amp_g(
            freq_hz=freq,
            combined_spectrum_amp_g=amps,
            peak_indexes=peak_indexes,
            exclusion_hz=0.5,  # only excludes 7 Hz ± 0.5
            min_hz=5.0,
            max_hz=9.0,
        )
        assert floor > 0.0
        # Should be the median of [0.001, 0.002, 0.002, 0.001]
        expected_median = (0.001 + 0.002) / 2  # sorted: [0.001, 0.001, 0.002, 0.002]
        assert abs(floor - expected_median) < 1e-6


class TestWheelFocusFromLocation:
    """Regression: _wheel_focus_from_location must match label_for_code() outputs
    which use spaces (e.g. 'Front Left Wheel'), not hyphens."""

    def test_space_separated_labels(self) -> None:
        from vibesensor.analysis.order_analysis import _wheel_focus_from_location

        wf = _wheel_focus_from_location
        assert wf("Front Left Wheel") == {"_i18n_key": "WHEEL_FOCUS_FRONT_LEFT"}
        assert wf("Front Right Wheel") == {"_i18n_key": "WHEEL_FOCUS_FRONT_RIGHT"}
        assert wf("Rear Left Wheel") == {"_i18n_key": "WHEEL_FOCUS_REAR_LEFT"}
        assert wf("Rear Right Wheel") == {"_i18n_key": "WHEEL_FOCUS_REAR_RIGHT"}

    def test_hyphen_separated_labels_still_work(self) -> None:
        from vibesensor.analysis.order_analysis import _wheel_focus_from_location

        wf = _wheel_focus_from_location
        assert wf("front-left wheel") == {"_i18n_key": "WHEEL_FOCUS_FRONT_LEFT"}
        assert wf("rear-right wheel") == {"_i18n_key": "WHEEL_FOCUS_REAR_RIGHT"}

    def test_underscore_separated_labels(self) -> None:
        from vibesensor.analysis.order_analysis import _wheel_focus_from_location

        wf = _wheel_focus_from_location
        assert wf("front_left_wheel") == {"_i18n_key": "WHEEL_FOCUS_FRONT_LEFT"}
        assert wf("rear_left_wheel") == {"_i18n_key": "WHEEL_FOCUS_REAR_LEFT"}

    def test_generic_rear_and_front(self) -> None:
        from vibesensor.analysis.order_analysis import _wheel_focus_from_location

        assert _wheel_focus_from_location("Trunk") == {"_i18n_key": "WHEEL_FOCUS_REAR"}
        assert _wheel_focus_from_location("Engine Bay") == {"_i18n_key": "WHEEL_FOCUS_FRONT"}
        assert _wheel_focus_from_location("unknown location") == {"_i18n_key": "WHEEL_FOCUS_ALL"}


class TestStoreAnalysisErrorGuard:
    """Regression: store_analysis_error must not overwrite a completed run."""

    def test_error_does_not_overwrite_complete(self, tmp_path: pytest.TempPathFactory) -> None:
        from pathlib import Path

        from vibesensor.history_db import HistoryDB

        db = HistoryDB(Path(str(tmp_path)) / "test.db")
        run_id = "test-run-001"
        db.create_run(run_id, "2024-01-01T00:00:00", {"test": True})

        # Complete the analysis
        db.store_analysis(run_id, {"result": "ok"})
        status_before = db.get_run_status(run_id)
        assert status_before == "complete"

        # Try to overwrite with an error
        db.store_analysis_error(run_id, "spurious error")
        status_after = db.get_run_status(run_id)
        assert status_after == "complete", "store_analysis_error must not overwrite a completed run"


class TestEvidencePeakPresentFormat:
    """Regression: EVIDENCE_PEAK_PRESENT i18n template must use .1f for dB values."""

    def test_dB_format_is_one_decimal(self) -> None:
        import json
        from pathlib import Path

        i18n_path = Path(__file__).parent.parent / "data" / "report_i18n.json"
        with open(i18n_path)as f:
            data = json.load(f)

        en_template = data["EVIDENCE_PEAK_PRESENT"]["en"]
        nl_template = data["EVIDENCE_PEAK_PRESENT"]["nl"]

        # Must use .1f, not .4f
        assert ".1f}" in en_template, f"Expected .1f in EN template, got: {en_template}"
        assert ".1f}" in nl_template, f"Expected .1f in NL template, got: {nl_template}"
        assert ".4f" not in en_template, "Stale .4f found in EN template"
        assert ".4f" not in nl_template, "Stale .4f found in NL template"
