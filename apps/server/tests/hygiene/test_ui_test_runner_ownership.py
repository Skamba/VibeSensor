"""Guard UI spec ownership across Vitest and Playwright."""

from __future__ import annotations

from types import ModuleType

import pytest
from test_support.check_hygiene_loader import load_check_hygiene_module

_FOLLOW_UP_PLAYWRIGHT_SPECS = {
    "tests/regression.realtime-logging-summary.spec.ts",
    "tests/regression.settings-car-feedback-reset.spec.ts",
    "tests/regression.settings-obd-scan-timeout.spec.ts",
    "tests/regression.settings-shell.spec.ts",
}


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return load_check_hygiene_module("check_hygiene_ui_runner_ownership")


def test_ui_specs_have_exactly_one_runner_owner(hygiene_module: ModuleType) -> None:
    all_specs = hygiene_module.all_ui_specs()
    runner_specs = hygiene_module.ui_runner_owned_specs()

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


def test_follow_up_browser_specs_stay_playwright_owned(
    hygiene_module: ModuleType,
) -> None:
    runner_specs = hygiene_module.ui_runner_owned_specs()
    regression_specs = runner_specs["playwright-regression"]

    missing = _FOLLOW_UP_PLAYWRIGHT_SPECS - regression_specs
    assert not missing, (
        "Previously migrated browser-flow follow-up specs should stay on the "
        f"Playwright regression runner: {sorted(missing)}"
    )

    vitest_overlap = _FOLLOW_UP_PLAYWRIGHT_SPECS & runner_specs["vitest"]
    assert not vitest_overlap, (
        "Browser-flow follow-up specs must not slip back into Vitest "
        f"collection: {sorted(vitest_overlap)}"
    )
