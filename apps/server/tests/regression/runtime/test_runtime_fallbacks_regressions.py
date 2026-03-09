# ruff: noqa: E402
from __future__ import annotations

"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""


import json
import math

import pytest
from _paths import SERVER_ROOT
from vibesensor_core.vibration_strength import (
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)

from vibesensor.analysis.order_analysis import _wheel_focus_from_location
from vibesensor.history_db import HistoryDB


class TestStrengthFloorFallback:
    """Regression: strength_floor_amp_g must not return 0.0 when all bins
    are within peak exclusion zones, since 0.0 floor produces ~140 dB.
    """

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
    which use spaces (e.g. 'Front Left Wheel'), not hyphens.
    """

    @pytest.mark.parametrize(
        ("label", "expected_key"),
        [
            # Space-separated (canonical)
            ("Front Left Wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("Front Right Wheel", "WHEEL_FOCUS_FRONT_RIGHT"),
            ("Rear Left Wheel", "WHEEL_FOCUS_REAR_LEFT"),
            ("Rear Right Wheel", "WHEEL_FOCUS_REAR_RIGHT"),
            # Hyphen-separated
            ("front-left wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("rear-right wheel", "WHEEL_FOCUS_REAR_RIGHT"),
            # Underscore-separated
            ("front_left_wheel", "WHEEL_FOCUS_FRONT_LEFT"),
            ("rear_left_wheel", "WHEEL_FOCUS_REAR_LEFT"),
            # Generic locations
            ("Trunk", "WHEEL_FOCUS_REAR"),
            ("Engine Bay", "WHEEL_FOCUS_FRONT"),
            ("unknown location", "WHEEL_FOCUS_ALL"),
        ],
    )
    def test_location_to_wheel_focus(self, label: str, expected_key: str) -> None:
        assert _wheel_focus_from_location(label) == {"_i18n_key": expected_key}


class TestStoreAnalysisErrorGuard:
    """Regression: store_analysis_error must not overwrite a completed run."""

    def test_error_does_not_overwrite_complete(self, tmp_path: pytest.TempPathFactory) -> None:
        db = HistoryDB(tmp_path / "test.db")
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
        i18n_path = SERVER_ROOT / "data" / "report_i18n.json"
        data = json.loads(i18n_path.read_text())

        en_template = data["EVIDENCE_PEAK_PRESENT"]["en"]
        nl_template = data["EVIDENCE_PEAK_PRESENT"]["nl"]

        # Must use .1f, not .4f
        assert ".1f}" in en_template, f"Expected .1f in EN template, got: {en_template}"
        assert ".1f}" in nl_template, f"Expected .1f in NL template, got: {nl_template}"
        assert ".4f" not in en_template, "Stale .4f found in EN template"
        assert ".4f" not in nl_template, "Stale .4f found in NL template"
