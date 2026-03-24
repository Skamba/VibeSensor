"""Guard: UI Vite entry points keep fixed-port, fail-fast behavior."""

from __future__ import annotations

import json

from tests._paths import REPO_ROOT

_UI_PACKAGE_JSON = REPO_ROOT / "apps" / "ui" / "package.json"
_VITE_CONFIG = REPO_ROOT / "apps" / "ui" / "vite.config.ts"
_SMOKE_CONFIG = REPO_ROOT / "apps" / "ui" / "playwright.smoke.config.ts"
_SCREENSHOT_SCRIPT = REPO_ROOT / "apps" / "ui" / "take-screenshot.mjs"
_SNAPSHOT_UPDATE_SCRIPT = REPO_ROOT / "apps" / "ui" / "update-snapshots.mjs"


def _package_scripts() -> dict[str, str]:
    package_json = json.loads(_UI_PACKAGE_JSON.read_text())
    return {str(name): str(command) for name, command in package_json["scripts"].items()}


def test_ui_vite_config_pins_dev_and_preview_ports() -> None:
    config_text = _VITE_CONFIG.read_text()

    assert "preview:" in config_text
    assert config_text.count("strictPort: true") >= 2


def test_ui_dev_and_preview_scripts_defer_fixed_port_defaults_to_vite_config() -> None:
    scripts = _package_scripts()

    assert scripts["dev"] == "vite"
    assert scripts["dev:open"] == "vite --open"
    assert scripts["preview"] == "vite preview"


def test_ui_smoke_webserver_fails_fast_on_port_conflicts() -> None:
    smoke_config = _SMOKE_CONFIG.read_text()

    assert "--strictPort" in smoke_config


def test_ui_preview_helpers_fail_fast_on_port_conflicts() -> None:
    assert "--strictPort" in _SCREENSHOT_SCRIPT.read_text()
    assert "--strictPort" in _SNAPSHOT_UPDATE_SCRIPT.read_text()
