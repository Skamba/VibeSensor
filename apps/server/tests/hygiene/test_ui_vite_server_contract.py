"""Guard: UI Vite entry points keep fixed-port, fail-fast behavior."""

from __future__ import annotations

import json

from tests._paths import REPO_ROOT

_UI_PACKAGE_JSON = REPO_ROOT / "apps" / "ui" / "package.json"
_VITE_CONFIG = REPO_ROOT / "apps" / "ui" / "vite.config.ts"
_SMOKE_CONFIG = REPO_ROOT / "apps" / "ui" / "playwright.smoke.config.ts"
_PREVIEW_HELPER = REPO_ROOT / "apps" / "ui" / "playwright-preview-helpers.mjs"
_SCREENSHOT_SCRIPT = REPO_ROOT / "apps" / "ui" / "take-screenshot.mjs"
_SNAPSHOT_UPDATE_SCRIPT = REPO_ROOT / "apps" / "ui" / "update-snapshots.mjs"
_WIKI_SCREENSHOT_SCRIPT = REPO_ROOT / "apps" / "ui" / "update-wiki-screenshots.mjs"


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
    helper_text = _PREVIEW_HELPER.read_text()

    assert "--strictPort" in helper_text
    assert "./playwright-preview-helpers.mjs" in _SCREENSHOT_SCRIPT.read_text()
    assert "./playwright-preview-helpers.mjs" in _SNAPSHOT_UPDATE_SCRIPT.read_text()
    assert "./playwright-preview-helpers.mjs" in _WIKI_SCREENSHOT_SCRIPT.read_text()


def test_ui_package_exposes_opt_in_wiki_screenshot_updater() -> None:
    scripts = _package_scripts()

    assert scripts["wiki:screenshots"] == "node update-wiki-screenshots.mjs"
