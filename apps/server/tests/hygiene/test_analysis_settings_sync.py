"""Guard: UI and backend analysis-settings defaults stay in sync."""

from __future__ import annotations

import re
import subprocess
import sys

from tests._paths import REPO_ROOT
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot

_UI_SETTINGS_STATE_TS = REPO_ROOT / "apps" / "ui" / "src" / "app" / "settings_state.ts"
_GENERATOR = REPO_ROOT / "tools" / "config" / "generate_ui_shared_constants.py"


def _generated_constants_ts() -> str:
    result = subprocess.run(
        [sys.executable, str(_GENERATOR)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _parse_generated_numeric_export(name: str) -> dict[str, float]:
    """Extract a numeric object literal export from generated constants output."""
    text = _generated_constants_ts()
    match = re.search(
        rf"export const {name}\s*=\s*\{{([^}}]+)\}} as const;",
        text,
        re.DOTALL,
    )
    assert match, f"Could not find {name} export in generated constants output"
    block = match.group(1)
    pairs: dict[str, float] = {}
    for line_match in re.finditer(r'"?(\w+)"?:\s*([0-9.]+)', block):
        pairs[line_match.group(1)] = float(line_match.group(2))
    return pairs


def _parse_ui_vehicle_defaults() -> dict[str, float]:
    """Extract the generated backend-owned vehicle defaults from constants.ts."""
    return _parse_generated_numeric_export("defaultAnalysisSettings")


def _parse_ts_string_array(name: str) -> list[str]:
    """Extract a string array constant from the UI settings state owner."""
    text = _UI_SETTINGS_STATE_TS.read_text()
    match = re.search(
        rf"{name}\s*=\s*\[([^\]]+)\]",
        text,
        re.DOTALL,
    )
    assert match, f"Could not find {name} in settings_state.ts"
    return re.findall(r'"(\w+)"', match.group(1))


def _parse_ui_setting_keys() -> list[str]:
    """Extract the composed vehicle-setting key set from settings_state.ts."""
    return [
        *_parse_ts_string_array("carAspectSettingKeys"),
        *_parse_ts_string_array("analysisTuningSettingKeys"),
    ]


def test_ui_defaults_match_backend() -> None:
    """Generated UI vehicle defaults must be a value-for-value backend projection."""
    backend = AnalysisSettingsSnapshot.DEFAULTS
    frontend = _parse_ui_vehicle_defaults()

    assert set(frontend) == set(backend), (
        "UI vehicle defaults key set drifted from backend DEFAULTS: "
        f"missing={sorted(set(backend) - set(frontend))}, "
        f"extra={sorted(set(frontend) - set(backend))}"
    )

    mismatched: list[str] = []
    for key, be_val in sorted(backend.items()):
        fe_val = frontend[key]
        if abs(fe_val - be_val) > 1e-9:
            mismatched.append(f"  {key}: UI={fe_val}, backend={be_val}")
    assert not mismatched, "UI/backend analysis-settings default mismatch:\n" + "\n".join(
        mismatched
    )


def test_ui_setting_keys_match_backend() -> None:
    """UI vehicle-setting key unions must list each backend DEFAULTS key exactly once."""
    backend_keys = tuple(AnalysisSettingsSnapshot.DEFAULTS)
    frontend_keys = _parse_ui_setting_keys()

    duplicates = sorted({key for key in frontend_keys if frontend_keys.count(key) > 1})
    assert not duplicates, f"UI vehicle-setting keys are duplicated: {duplicates}"
    assert set(frontend_keys) == set(backend_keys), (
        "UI vehicle-setting keys drifted from backend DEFAULTS: "
        f"missing={sorted(set(backend_keys) - set(frontend_keys))}, "
        f"extra={sorted(set(frontend_keys) - set(backend_keys))}"
    )
