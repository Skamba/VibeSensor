"""Guardrail tests ensuring key definitions have a single source of truth.

These tests prevent regression of the consolidation work by verifying:
1. DEFAULT_DIAGNOSTIC_SETTINGS is the same object as DEFAULT_ANALYSIS_SETTINGS
2. Spectrum payloads do not contain dead alias fields
3. The legacy strength_scoring module is removed
4. Metrics log records use canonical field names only
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
