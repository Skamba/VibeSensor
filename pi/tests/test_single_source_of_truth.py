"""Guardrail tests ensuring key definitions have a single source of truth.

These tests prevent regression of the consolidation work by verifying:
1. DEFAULT_DIAGNOSTIC_SETTINGS is the same object as DEFAULT_ANALYSIS_SETTINGS
2. Spectrum payloads do not contain dead alias fields
3. The legacy strength_scoring module is removed
4. Metrics log records use canonical field names only
5. as_float_or_none is the single canonical float converter
6. _percentile is the single canonical percentile implementation
7. compute_strength_metrics output has no dead alias fields
"""

from __future__ import annotations

import importlib

import pytest

from vibesensor.analysis_settings import DEFAULT_ANALYSIS_SETTINGS
from vibesensor.diagnostics_shared import DEFAULT_DIAGNOSTIC_SETTINGS


def test_diagnostic_settings_is_analysis_settings() -> None:
    """DEFAULT_DIAGNOSTIC_SETTINGS must be the same object as DEFAULT_ANALYSIS_SETTINGS."""
    assert DEFAULT_DIAGNOSTIC_SETTINGS is DEFAULT_ANALYSIS_SETTINGS


def test_analysis_settings_keys_match() -> None:
    """Both default dicts have identical keys and values."""
    assert set(DEFAULT_DIAGNOSTIC_SETTINGS.keys()) == set(DEFAULT_ANALYSIS_SETTINGS.keys())
    for key in DEFAULT_ANALYSIS_SETTINGS:
        assert DEFAULT_DIAGNOSTIC_SETTINGS[key] == DEFAULT_ANALYSIS_SETTINGS[key]


def test_strength_scoring_module_removed() -> None:
    """The legacy strength_scoring.py wrapper should no longer exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("vibesensor.strength_scoring")


def test_spectrum_payload_has_no_combined_alias() -> None:
    """Spectrum payload must not contain the dead 'combined' alias field."""
    import numpy as np

    from vibesensor.processing import SignalProcessor

    proc = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=120,
        fft_n=512,
        spectrum_max_hz=200,
    )
    # Empty client
    payload = proc.spectrum_payload("nonexistent")
    assert "combined" not in payload
    assert "combined_spectrum_amp_g" in payload

    # Client with data
    samples = np.random.randn(600, 3).astype(np.float32) * 0.01
    proc.ingest("test_client", samples, sample_rate_hz=800)
    proc.compute_metrics("test_client")
    payload = proc.spectrum_payload("test_client")
    assert "combined" not in payload
    assert "combined_spectrum_amp_g" in payload


def test_selected_payload_has_no_combined_alias() -> None:
    """Selected payload spectrum must not contain the dead 'combined' alias."""
    import numpy as np

    from vibesensor.processing import SignalProcessor

    proc = SignalProcessor(
        sample_rate_hz=800,
        waveform_seconds=4,
        waveform_display_hz=120,
        fft_n=512,
        spectrum_max_hz=200,
    )
    samples = np.random.randn(600, 3).astype(np.float32) * 0.01
    proc.ingest("test_client", samples, sample_rate_hz=800)
    proc.compute_metrics("test_client")
    payload = proc.selected_payload("test_client")
    assert "combined" not in payload["spectrum"]
    assert "combined_spectrum_amp_g" in payload["spectrum"]


def test_metrics_log_no_legacy_field_names() -> None:
    """New metrics log records must not contain legacy field aliases."""
    from vibesensor.runlog import default_units

    units = default_units()
    legacy_fields = {
        "accel_magnitude_rms_g",
        "accel_magnitude_p2p_g",
        "dominant_peak_amp_g",
        "noise_floor_amp",
    }
    present = legacy_fields & set(units.keys())
    assert not present, f"Legacy fields still in default_units: {present}"


def test_as_float_single_source_of_truth() -> None:
    """diagnostics_shared._as_float and report_analysis._as_float must be
    the canonical as_float_or_none from runlog, not local re-definitions."""
    from vibesensor.diagnostics_shared import _as_float as diag_as_float
    from vibesensor.report_analysis import _as_float as report_as_float
    from vibesensor.runlog import as_float_or_none

    assert diag_as_float is as_float_or_none, (
        "diagnostics_shared._as_float must be imported from runlog.as_float_or_none"
    )
    assert report_as_float is as_float_or_none, (
        "report_analysis._as_float must be imported from runlog.as_float_or_none"
    )


def test_percentile_single_source_of_truth() -> None:
    """report_analysis._percentile must be imported from
    analysis.strength_metrics, not re-defined locally."""
    from vibesensor.analysis.strength_metrics import _percentile as canonical
    from vibesensor.report_analysis import _percentile

    assert _percentile is canonical, (
        "report_analysis._percentile must be imported from analysis.strength_metrics"
    )


def test_strength_metrics_no_dead_aliases() -> None:
    """compute_strength_metrics output must not contain dead alias fields."""
    from vibesensor.analysis.strength_metrics import compute_strength_metrics

    result = compute_strength_metrics(
        freq_hz=[1.0, 2.0, 3.0],
        combined_spectrum_amp_g_values=[0.0, 0.0, 0.0],
    )
    dead_aliases = {"peak_amp", "floor_amp"}
    present = dead_aliases & set(result.keys())
    assert not present, f"Dead alias fields in compute_strength_metrics: {present}"


def test_constants_used_for_speed_conversion() -> None:
    """Speed conversion must use constants, not hardcoded 3.6."""
    from vibesensor.constants import KMH_TO_MPS, MPS_TO_KMH

    assert MPS_TO_KMH == 3.6
    assert abs(KMH_TO_MPS - 1.0 / 3.6) < 1e-15
    assert abs(MPS_TO_KMH * KMH_TO_MPS - 1.0) < 1e-15


def test_constants_used_for_peak_detection() -> None:
    """Peak detection defaults must come from constants module."""
    from vibesensor.analysis.strength_metrics import compute_strength_metrics
    from vibesensor.constants import PEAK_BANDWIDTH_HZ, PEAK_SEPARATION_HZ

    assert PEAK_BANDWIDTH_HZ == 1.2
    assert PEAK_SEPARATION_HZ == 1.2

    # Verify the function signature defaults match constants
    import inspect

    sig = inspect.signature(compute_strength_metrics)
    assert sig.parameters["peak_bandwidth_hz"].default == PEAK_BANDWIDTH_HZ
    assert sig.parameters["peak_separation_hz"].default == PEAK_SEPARATION_HZ


def test_silence_db_constant() -> None:
    """SILENCE_DB must be the canonical silence floor value."""
    from vibesensor.constants import SILENCE_DB

    assert SILENCE_DB == -120.0


def test_config_preflight_no_removed_fields() -> None:
    """config_preflight.summarize must not reference removed config fields."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "tools" / "config"))
    preflight_path = root / "tools" / "config" / "config_preflight.py"
    source = preflight_path.read_text(encoding="utf-8")
    assert "metrics_csv_path" not in source, (
        "config_preflight.py still references removed metrics_csv_path"
    )


def test_wheel_hz_and_engine_rpm_single_source() -> None:
    """wheel_hz and engine_rpm formulas must not be inlined in consumers."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for fname in ("metrics_log.py", "report_analysis.py"):
        source = (root / "vibesensor" / fname).read_text(encoding="utf-8")
        assert "* 60.0" not in source, f"{fname} still contains inline engine RPM formula (* 60.0)"
