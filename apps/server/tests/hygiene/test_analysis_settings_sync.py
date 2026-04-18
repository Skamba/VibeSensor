"""Guard: UI and backend analysis-settings defaults stay in sync."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

_UI_APP_STATE_TS = REPO_ROOT / "apps" / "ui" / "src" / "app" / "ui_app_state.ts"


def _parse_ts_numeric_block(name: str, type_name: str) -> dict[str, float]:
    """Extract a numeric object literal block from ui_app_state.ts."""
    text = _UI_APP_STATE_TS.read_text()
    match = re.search(
        rf"{name}:\s*Readonly<{type_name}>\s*=\s*\{{([^}}]+)\}}",
        text,
        re.DOTALL,
    )
    assert match, f"Could not find {name} block in ui_app_state.ts"
    block = match.group(1)
    pairs: dict[str, float] = {}
    for line_match in re.finditer(r"(\w+):\s*([0-9.]+)", block):
        pairs[line_match.group(1)] = float(line_match.group(2))
    return pairs


def _parse_ui_vehicle_defaults() -> dict[str, float]:
    """Extract the composed vehicle defaults from ui_app_state.ts."""
    return {
        **_parse_ts_numeric_block("defaultCarAspectSettings", "CarAspectSettings"),
        **_parse_ts_numeric_block("defaultAnalysisTuningSettings", "AnalysisTuningSettings"),
    }


def _parse_ts_string_array(name: str) -> list[str]:
    """Extract a string array constant from ui_app_state.ts."""
    text = _UI_APP_STATE_TS.read_text()
    match = re.search(
        rf"{name}\s*=\s*\[([^\]]+)\]",
        text,
        re.DOTALL,
    )
    assert match, f"Could not find {name} in ui_app_state.ts"
    return re.findall(r'"(\w+)"', match.group(1))


def _parse_ui_setting_keys() -> list[str]:
    """Extract the composed vehicle-setting key set from ui_app_state.ts."""
    return [
        *_parse_ts_string_array("carAspectSettingKeys"),
        *_parse_ts_string_array("analysisTuningSettingKeys"),
    ]


def test_ui_defaults_match_backend() -> None:
    """Every backend DEFAULTS key must appear in UI vehicle defaults with the same value."""
    backend = AnalysisSettingsSnapshot.DEFAULTS
    frontend = _parse_ui_vehicle_defaults()

    missing = set(backend) - set(frontend)
    assert not missing, f"UI vehicle defaults are missing keys: {sorted(missing)}"

    mismatched: list[str] = []
    for key, be_val in backend.items():
        fe_val = frontend[key]
        if abs(fe_val - be_val) > 1e-9:
            mismatched.append(f"  {key}: UI={fe_val}, backend={be_val}")
    assert not mismatched, "UI/backend analysis-settings default mismatch:\n" + "\n".join(
        mismatched
    )


def test_ui_setting_keys_match_backend() -> None:
    """UI vehicle-setting key unions must list every backend DEFAULTS key."""
    backend_keys = set(AnalysisSettingsSnapshot.DEFAULTS)
    frontend_keys = set(_parse_ui_setting_keys())

    missing = backend_keys - frontend_keys
    assert not missing, f"UI vehicle-setting keys missing: {sorted(missing)}"

    extra = frontend_keys - backend_keys
    assert not extra, f"UI vehicle-setting keys have extra entries: {sorted(extra)}"
