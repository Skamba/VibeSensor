"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""

from __future__ import annotations

import json
import math

import pytest
from _paths import SERVER_ROOT
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.vibration_strength import (
    strength_floor_amp_g,
    vibration_strength_db_scalar,
)


def _metadata(run_id: str, **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2024-01-01T00:00:00",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


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


class TestStoreAnalysisErrorGuard:
    """Regression: store_analysis_error must not overwrite a completed run."""

    def test_error_does_not_overwrite_complete(self, tmp_path: pytest.TempPathFactory) -> None:
        db = create_history_persistence_adapters(tmp_path / "test.db")
        run_id = "test-run-001"
        db.run_repository.create_run(run_id, "2024-01-01T00:00:00", _metadata(run_id, test=True))

        # Complete the analysis
        db.run_repository.store_analysis(run_id, make_persisted_analysis({"result": "ok"}))
        run_before = db.run_repository.get_run(run_id)
        assert run_before is not None
        assert run_before.status.value == "complete"

        # Try to overwrite with an error
        db.run_repository.store_analysis_error(run_id, "spurious error")
        run_after = db.run_repository.get_run(run_id)
        assert run_after is not None
        assert run_after.status.value == "complete", (
            "store_analysis_error must not overwrite a completed run"
        )


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
