"""Generate frontend constants from shared backend-owned definitions."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import TypeGuard

ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = ROOT / "apps" / "server" / "vibesensor" / "shared"
DOMAIN_ROOT = ROOT / "apps" / "server" / "vibesensor" / "domain"
APP_ROOT = ROOT / "apps" / "server" / "vibesensor" / "app"
SERVER_ROOT = ROOT / "apps" / "server" / "vibesensor"
LOCATIONS_PATH = SHARED_ROOT / "locations.py"
ANALYSIS_SETTINGS_PATH = DOMAIN_ROOT / "analysis_settings.py"
DSP_CONSTANTS_PATH = SHARED_ROOT / "constants" / "dsp.py"
CONFIG_DEFAULTS_PATH = APP_ROOT / "config_defaults.py"
VIBRATION_STRENGTH_PATH = SERVER_ROOT / "vibration_strength.py"


def _is_string_dict(value: object) -> TypeGuard[dict[str, str]]:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    )


def _is_numeric_dict(value: object) -> TypeGuard[dict[str, int | float]]:
    return isinstance(value, dict) and all(
        isinstance(key, str)
        and isinstance(item, (int, float))
        and not isinstance(item, bool)
        for key, item in value.items()
    )


def _load_literal_constant(module_path: Path, constant_name: str) -> object:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id == constant_name
                and node.value is not None
            ):
                value_node = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == constant_name:
                    value_node = node.value
                    break
        if value_node is None:
            continue
        return ast.literal_eval(value_node)
    msg = f"Could not find {constant_name} in {module_path}"
    raise ValueError(msg)


def _load_string_dict_constant(module_path: Path, constant_name: str) -> dict[str, str]:
    value = _load_literal_constant(module_path, constant_name)
    if not _is_string_dict(value):
        msg = f"{module_path}::{constant_name} must be a dict[str, str] literal"
        raise ValueError(msg)
    return dict(value)


def _load_numeric_dict_constant(
    module_path: Path, constant_name: str
) -> dict[str, int | float]:
    value = _load_literal_constant(module_path, constant_name)
    if not _is_numeric_dict(value):
        msg = f"{module_path}::{constant_name} must be a dict[str, number] literal"
        raise ValueError(msg)
    return dict(value)


def _load_number_constant(module_path: Path, constant_name: str) -> int | float:
    value = _load_literal_constant(module_path, constant_name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        msg = f"{module_path}::{constant_name} must be a numeric literal"
        raise ValueError(msg)
    return value


def _load_string_constant(module_path: Path, constant_name: str) -> str:
    value = _load_literal_constant(module_path, constant_name)
    if not isinstance(value, str):
        msg = f"{module_path}::{constant_name} must be a string literal"
        raise ValueError(msg)
    return value


def _load_processing_sample_rate_hz() -> int | float:
    value = _load_literal_constant(CONFIG_DEFAULTS_PATH, "DEFAULT_CONFIG")
    if not isinstance(value, dict):
        msg = f"{CONFIG_DEFAULTS_PATH}::DEFAULT_CONFIG must be a dict literal"
        raise ValueError(msg)
    processing = value.get("processing")
    if not isinstance(processing, dict):
        msg = f"{CONFIG_DEFAULTS_PATH}::DEFAULT_CONFIG['processing'] must be a dict literal"
        raise ValueError(msg)
    sample_rate_hz = processing.get("sample_rate_hz")
    if not isinstance(sample_rate_hz, (int, float)) or isinstance(sample_rate_hz, bool):
        msg = (
            f"{CONFIG_DEFAULTS_PATH}::DEFAULT_CONFIG['processing']['sample_rate_hz'] "
            "must be numeric"
        )
        raise ValueError(msg)
    return sample_rate_hz


def _render_export(name: str, value: object) -> str:
    return f"export const {name} = {json.dumps(value, indent=2)} as const;\n"


def render_ui_shared_constants_module() -> str:
    location_codes = _load_string_dict_constant(LOCATIONS_PATH, "LOCATION_CODES")
    analysis_settings = _load_numeric_dict_constant(
        ANALYSIS_SETTINGS_PATH, "ANALYSIS_SETTINGS_DEFAULTS"
    )
    live_analysis_config = {
        "sampleRateHz": _load_processing_sample_rate_hz(),
        "fftWindowSizeSamples": _load_number_constant(DSP_CONSTANTS_PATH, "FFT_N"),
        "spectrumMinHz": _load_number_constant(DSP_CONSTANTS_PATH, "SPECTRUM_MIN_HZ"),
        "spectrumMaxHz": _load_number_constant(DSP_CONSTANTS_PATH, "SPECTRUM_MAX_HZ"),
        "peakBandwidthHz": _load_number_constant(
            VIBRATION_STRENGTH_PATH, "PEAK_BANDWIDTH_HZ"
        ),
        "peakSeparationHz": _load_number_constant(
            VIBRATION_STRENGTH_PATH, "PEAK_SEPARATION_HZ"
        ),
        "strengthAlgorithmVersion": _load_string_constant(
            VIBRATION_STRENGTH_PATH, "STRENGTH_ALGORITHM_VERSION"
        ),
        "peakDetectorVersion": _load_string_constant(
            VIBRATION_STRENGTH_PATH, "PEAK_DETECTOR_VERSION"
        ),
        "calibrationProfileId": _load_string_constant(
            VIBRATION_STRENGTH_PATH, "CALIBRATION_PROFILE_ID"
        ),
    }
    return (
        "// Generated from backend-owned shared constants\n"
        "// Do not edit manually; run make sync-contracts\n\n"
        + _render_export("defaultLocationCodes", list(location_codes.keys()))
        + "\n"
        + _render_export("defaultAnalysisSettings", analysis_settings)
        + "\n"
        + _render_export("defaultLiveAnalysisConfig", live_analysis_config)
    )


def main() -> None:
    sys.stdout.write(render_ui_shared_constants_module())


if __name__ == "__main__":
    main()
