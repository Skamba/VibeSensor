"""Guard: UI and backend analysis-settings defaults stay in sync."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

_UI_APP_STATE_TS = REPO_ROOT / "apps" / "ui" / "src" / "app" / "ui_app_state.ts"
_SETTINGS_ANALYSIS_MODULE_TS = (
    REPO_ROOT / "apps" / "ui" / "src" / "app" / "features" / "settings_analysis_module.ts"
)


def _parse_ui_vehicle_defaults() -> dict[str, float]:
    """Extract vehicleSettings defaults from ui_app_state.ts."""
    text = _UI_APP_STATE_TS.read_text()
    match = re.search(
        r"vehicleSettings:\s*\{([^}]+)\}",
        text,
        re.DOTALL,
    )
    assert match, "Could not find vehicleSettings block in ui_app_state.ts"
    block = match.group(1)
    pairs: dict[str, float] = {}
    for line_match in re.finditer(r"(\w+):\s*([0-9.]+)", block):
        pairs[line_match.group(1)] = float(line_match.group(2))
    return pairs


def _parse_ui_setting_keys() -> list[str]:
    """Extract ANALYSIS_SETTING_KEYS from settings_analysis_module.ts."""
    text = _SETTINGS_ANALYSIS_MODULE_TS.read_text()
    match = re.search(
        r"ANALYSIS_SETTING_KEYS\s*=\s*\[([^\]]+)\]",
        text,
        re.DOTALL,
    )
    assert match, "Could not find ANALYSIS_SETTING_KEYS in settings_analysis_module.ts"
    return re.findall(r'"(\w+)"', match.group(1))


def test_ui_defaults_match_backend() -> None:
    """Every backend DEFAULTS key must appear in UI vehicleSettings with the
    same value."""
    backend = AnalysisSettingsSnapshot.DEFAULTS
    frontend = _parse_ui_vehicle_defaults()

    missing = set(backend) - set(frontend)
    assert not missing, f"UI vehicleSettings is missing keys: {sorted(missing)}"

    mismatched: list[str] = []
    for key, be_val in backend.items():
        fe_val = frontend[key]
        if abs(fe_val - be_val) > 1e-9:
            mismatched.append(f"  {key}: UI={fe_val}, backend={be_val}")
    assert not mismatched, "UI/backend analysis-settings default mismatch:\n" + "\n".join(
        mismatched
    )


def test_ui_setting_keys_match_backend() -> None:
    """ANALYSIS_SETTING_KEYS must list every backend DEFAULTS key."""
    backend_keys = set(AnalysisSettingsSnapshot.DEFAULTS)
    frontend_keys = set(_parse_ui_setting_keys())

    missing = backend_keys - frontend_keys
    assert not missing, f"ANALYSIS_SETTING_KEYS missing: {sorted(missing)}"

    extra = frontend_keys - backend_keys
    assert not extra, f"ANALYSIS_SETTING_KEYS has extra keys: {sorted(extra)}"
