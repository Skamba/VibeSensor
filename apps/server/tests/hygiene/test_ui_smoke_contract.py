"""Guard: UI smoke command and Playwright smoke config stay aligned."""

from __future__ import annotations

import json

from tests._paths import REPO_ROOT

_UI_PACKAGE_JSON = REPO_ROOT / "apps" / "ui" / "package.json"
_SMOKE_CONFIG = REPO_ROOT / "apps" / "ui" / "playwright.smoke.config.ts"
_UI_TESTS_DIR = REPO_ROOT / "apps" / "ui" / "tests"
_EXPECTED_CORE_SMOKE_SPECS = {
    "smoke.bootstrap.spec.ts",
    "smoke.settings.spec.ts",
    "smoke.history.spec.ts",
    "smoke.cars.spec.ts",
    "smoke.esp-flash.spec.ts",
}


def _smoke_script() -> str:
    package_json = json.loads(_UI_PACKAGE_JSON.read_text())
    return str(package_json["scripts"]["test:smoke"])


def test_ui_smoke_script_defers_test_selection_to_smoke_config() -> None:
    package_json = json.loads(_UI_PACKAGE_JSON.read_text())
    scripts = package_json["scripts"]
    script = str(scripts["test:smoke"])
    config_text = _SMOKE_CONFIG.read_text()

    assert scripts["pretest:smoke"] == "npm run sync:generated-contracts"
    assert "--config=playwright.smoke.config.ts" in script
    assert "--project=laptop-light" in script
    assert "--workers=" not in script
    assert "tests/" not in script, (
        "Smoke file selection should live in playwright.smoke.config.ts, "
        "not as hard-coded paths in package.json."
    )
    assert "PLAYWRIGHT_SMOKE_WORKERS" in config_text
    assert '?? "1"' in config_text


def test_ui_smoke_config_uses_split_smoke_glob() -> None:
    config_text = _SMOKE_CONFIG.read_text()

    assert "testMatch" in config_text
    assert "smoke*.spec.ts" in config_text


def test_core_ui_smoke_specs_exist() -> None:
    smoke_specs = {path.name for path in _UI_TESTS_DIR.glob("smoke*.spec.ts")}

    missing = _EXPECTED_CORE_SMOKE_SPECS - smoke_specs
    assert not missing, f"Missing core smoke specs: {sorted(missing)}"
