"""Guard UI spec ownership across Vitest and Playwright."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._paths import REPO_ROOT

_UI_ROOT = REPO_ROOT / "apps" / "ui"
_UI_TESTS_DIR = _UI_ROOT / "tests"
_VITEST_CONFIG = _UI_ROOT / "vitest.config.ts"
_PLAYWRIGHT_SMOKE_CONFIG = _UI_ROOT / "playwright.smoke.config.ts"
_PLAYWRIGHT_MOCK_SMOKE_CONFIG = _UI_ROOT / "playwright.smoke.msw.config.ts"
_PLAYWRIGHT_VISUAL_CONFIG = _UI_ROOT / "playwright.config.ts"
_FOLLOW_UP_PLAYWRIGHT_SPECS = {
    "tests/smoke.realtime-logging-summary.spec.ts",
    "tests/smoke.settings-car-feedback-reset.spec.ts",
    "tests/smoke.settings-obd-scan-timeout.spec.ts",
    "tests/smoke.settings-shell.spec.ts",
}


def _config_array_literal(config_path: Path, key: str) -> list[str]:
    config_text = config_path.read_text(encoding="utf-8")
    match = re.search(rf"{key}:\s*(\[[^\]]+\])", config_text)
    assert match is not None
    normalized_literal = re.sub(r"//.*", "", match.group(1))
    return [str(pattern) for pattern in ast.literal_eval(normalized_literal)]


def _config_string_literal(config_path: Path, key: str) -> str:
    config_text = config_path.read_text(encoding="utf-8")
    match = re.search(rf'{key}:\s*"([^"]+)"', config_text)
    assert match is not None
    return str(match.group(1))


def _resolve_ui_globs(*patterns: str) -> set[str]:
    resolved: set[str] = set()
    for pattern in patterns:
        for path in _UI_ROOT.glob(pattern):
            if path.is_file():
                resolved.add(path.relative_to(_UI_ROOT).as_posix())
    return resolved


def _resolve_runner_specs(config_path: Path) -> set[str]:
    test_dir = _config_string_literal(config_path, "testDir")
    test_match_patterns = _config_array_literal(config_path, "testMatch")
    return _resolve_ui_globs(*(f"{test_dir}/{pattern}" for pattern in test_match_patterns))


def _all_ui_specs() -> set[str]:
    return {
        path.relative_to(_UI_ROOT).as_posix()
        for path in _UI_TESTS_DIR.glob("**/*.spec.*")
        if path.is_file()
    }


def _runner_owned_specs() -> dict[str, set[str]]:
    vitest_include = _resolve_ui_globs(
        *_config_array_literal(_VITEST_CONFIG, "include"),
    )
    vitest_exclude = _resolve_ui_globs(
        *_config_array_literal(_VITEST_CONFIG, "exclude"),
    )
    return {
        "vitest": vitest_include - vitest_exclude,
        "playwright-smoke": _resolve_runner_specs(_PLAYWRIGHT_SMOKE_CONFIG),
        "playwright-mock-smoke": _resolve_runner_specs(_PLAYWRIGHT_MOCK_SMOKE_CONFIG),
        "playwright-visual": _resolve_runner_specs(_PLAYWRIGHT_VISUAL_CONFIG),
    }


def test_ui_specs_have_exactly_one_runner_owner() -> None:
    all_specs = _all_ui_specs()
    runner_specs = _runner_owned_specs()

    unowned: dict[str, list[str]] = {}
    multiply_owned: dict[str, list[str]] = {}
    for spec_path in sorted(all_specs):
        owners = sorted(
            runner_name
            for runner_name, owned_specs in runner_specs.items()
            if spec_path in owned_specs
        )
        if not owners:
            unowned[spec_path] = owners
        elif len(owners) > 1:
            multiply_owned[spec_path] = owners

    assert not unowned, f"UI specs missing a runner owner: {unowned}"
    assert not multiply_owned, f"UI specs owned by multiple runners: {multiply_owned}"


def test_follow_up_browser_specs_stay_playwright_owned() -> None:
    runner_specs = _runner_owned_specs()
    smoke_specs = runner_specs["playwright-smoke"]

    missing = _FOLLOW_UP_PLAYWRIGHT_SPECS - smoke_specs
    assert not missing, (
        "Previously migrated browser-flow follow-up specs should stay on the "
        f"Playwright smoke runner: {sorted(missing)}"
    )

    vitest_overlap = _FOLLOW_UP_PLAYWRIGHT_SPECS & runner_specs["vitest"]
    assert not vitest_overlap, (
        "Browser-flow follow-up specs must not slip back into Vitest "
        f"collection: {sorted(vitest_overlap)}"
    )
