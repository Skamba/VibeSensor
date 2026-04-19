"""Guard: UI smoke command and Playwright smoke config stay aligned."""

from __future__ import annotations

import ast
import json
import re
import shlex

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


def _package_scripts() -> dict[str, str]:
    package_json = json.loads(_UI_PACKAGE_JSON.read_text())
    return {key: str(value) for key, value in package_json["scripts"].items()}


def _smoke_script_tokens() -> list[str]:
    return shlex.split(_package_scripts()["test:smoke"])


def _smoke_test_match_patterns() -> list[str]:
    config_text = _SMOKE_CONFIG.read_text()
    match = re.search(r"testMatch:\s*(\[[^\]]+\])", config_text)
    assert match is not None
    return [str(pattern) for pattern in ast.literal_eval(match.group(1))]


def _smoke_test_dir() -> str:
    config_text = _SMOKE_CONFIG.read_text()
    match = re.search(r'testDir:\s*"([^"]+)"', config_text)
    assert match is not None
    return str(match.group(1))


def _smoke_workers_env_contract() -> tuple[str, str]:
    config_text = _SMOKE_CONFIG.read_text()
    match = re.search(r'process\.env\.(\w+)\s*\?\?\s*"([^"]+)"', config_text)
    assert match is not None
    return str(match.group(1)), str(match.group(2))


def _resolved_smoke_specs() -> set[str]:
    return {
        path.name
        for pattern in _smoke_test_match_patterns()
        for path in (REPO_ROOT / "apps" / "ui" / _smoke_test_dir()).glob(pattern)
    }


def test_ui_smoke_command_and_config_alignment() -> None:
    scripts = _package_scripts()
    smoke_tokens = _smoke_script_tokens()
    workers_env_var, workers_default = _smoke_workers_env_contract()
    smoke_specs = _resolved_smoke_specs()

    assert scripts["pretest:smoke"] == "npm run sync:generated-contracts"
    assert smoke_tokens[:3] == ["npx", "playwright", "test"]
    assert "--config=playwright.smoke.config.ts" in smoke_tokens
    assert "--project=laptop-light" in smoke_tokens
    assert not any(token.startswith("--workers") for token in smoke_tokens)
    assert not any(
        token.startswith("tests/") or token.endswith(".spec.ts") for token in smoke_tokens[3:]
    ), (
        "Smoke file selection should live in playwright.smoke.config.ts, "
        "not as hard-coded paths in package.json."
    )
    assert workers_env_var == "PLAYWRIGHT_SMOKE_WORKERS"
    assert workers_default == "1"
    assert _smoke_test_dir() == "tests"
    assert smoke_specs
    assert all(name.startswith("smoke") for name in smoke_specs)
    assert "visual.spec.ts" not in smoke_specs


def test_core_ui_smoke_specs_exist() -> None:
    smoke_specs = _resolved_smoke_specs()

    missing = _EXPECTED_CORE_SMOKE_SPECS - smoke_specs
    assert not missing, f"Missing core smoke specs: {sorted(missing)}"
