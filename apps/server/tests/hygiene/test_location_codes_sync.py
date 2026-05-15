"""Guard: backend location codes stay in sync with generated UI constants."""

from __future__ import annotations

import json
import re
import subprocess
import sys

import pytest

from tests._paths import REPO_ROOT
from vibesensor.app.config_defaults import documented_default_config
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.sensor import _LOCATION_CODES as DOMAIN_LOCATION_CODES
from vibesensor.shared.constants.dsp import FFT_N, SPECTRUM_MAX_HZ, SPECTRUM_MIN_HZ
from vibesensor.shared.locations import LOCATION_CODES
from vibesensor.vibration_strength import (
    CALIBRATION_PROFILE_ID,
    PEAK_BANDWIDTH_HZ,
    PEAK_DETECTOR_VERSION,
    PEAK_SEPARATION_HZ,
    STRENGTH_ALGORITHM_VERSION,
)

_GENERATOR = REPO_ROOT / "tools" / "config" / "generate_ui_shared_constants.py"


def _generated_constants_ts() -> str:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _extract_export_json(module_text: str, export_name: str) -> object:
    match = re.search(
        rf"export const {re.escape(export_name)} = (?P<value>\{{.*?\}}|\[.*?\]) as const;",
        module_text,
        re.DOTALL,
    )
    assert match is not None, f"Missing generated export {export_name}"
    return json.loads(match.group("value"))


@pytest.fixture(scope="module")
def generated_constants() -> str:
    return _generated_constants_ts()


def test_generated_ui_constants_encode_backend_sources(generated_constants: str) -> None:
    """Generated UI constants must be direct projections of backend owners."""
    config = documented_default_config()
    processing = config.get("processing")
    assert isinstance(processing, dict)
    sample_rate_hz = processing.get("sample_rate_hz")
    assert isinstance(sample_rate_hz, (int, float))

    expected_exports = {
        "defaultLocationCodes": list(LOCATION_CODES.keys()),
        "defaultAnalysisSettings": AnalysisSettingsSnapshot.DEFAULTS,
        "defaultLiveAnalysisConfig": {
            "sampleRateHz": sample_rate_hz,
            "fftWindowSizeSamples": FFT_N,
            "spectrumMinHz": SPECTRUM_MIN_HZ,
            "spectrumMaxHz": SPECTRUM_MAX_HZ,
            "peakBandwidthHz": PEAK_BANDWIDTH_HZ,
            "peakSeparationHz": PEAK_SEPARATION_HZ,
            "strengthAlgorithmVersion": STRENGTH_ALGORITHM_VERSION,
            "peakDetectorVersion": PEAK_DETECTOR_VERSION,
            "calibrationProfileId": CALIBRATION_PROFILE_ID,
        },
    }
    for export_name, expected in expected_exports.items():
        assert _extract_export_json(generated_constants, export_name) == expected


def test_domain_location_codes_match_shared() -> None:
    """Domain-internal _LOCATION_CODES must stay in sync with shared/locations."""
    assert DOMAIN_LOCATION_CODES == LOCATION_CODES, (
        "domain/sensor.py _LOCATION_CODES drifted from shared/locations.py LOCATION_CODES"
    )
    assert list(DOMAIN_LOCATION_CODES) == list(LOCATION_CODES)
    assert len(set(LOCATION_CODES)) == len(LOCATION_CODES)
