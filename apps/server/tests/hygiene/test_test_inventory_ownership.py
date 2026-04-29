"""Guard: committed test-looking files stay owned by a runner."""

from __future__ import annotations

from types import ModuleType

import pytest
from test_support.check_hygiene_loader import load_check_hygiene_module


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return load_check_hygiene_module("check_hygiene_test_inventory")


def test_test_inventory_guard_passes_for_current_repo(
    hygiene_module: ModuleType,
) -> None:
    assert hygiene_module.check_test_inventory_ownership() == []


def test_unowned_test_inventory_paths_report_runner_guidance(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.inventory_errors_for_test_paths(
        (
            "tools/test_orphan.py",
            "apps/ui/specs/orphan.spec.ts",
            "tools/tests/benchmark_new.py",
        ),
        ui_runner_specs={},
        benchmark_allowlist={},
    )

    assert any(
        "tools/test_orphan.py" in error and "apps/server/tests/" in error for error in errors
    )
    assert any(
        "apps/ui/specs/orphan.spec.ts" in error and "apps/ui/vitest.config.ts" in error
        for error in errors
    )
    assert any(
        "tools/tests/benchmark_new.py" in error
        and "tools/dev/test_inventory_allowlist.yml" in error
        for error in errors
    )


def test_allowlisted_benchmark_scripts_do_not_fail(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.inventory_errors_for_test_paths(
        ("tools/tests/benchmark_custom.py",),
        ui_runner_specs={},
        benchmark_allowlist={"tools/tests/benchmark_custom.py": "Standalone benchmark harness."},
    )

    assert errors == []


def test_production_modules_named_like_tests_are_ignored(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.inventory_errors_for_test_paths(
        (
            "apps/server/vibesensor/domain/test_plan.py",
            "apps/server/vibesensor/domain/test_run.py",
            "apps/server/vibesensor/shared/boundaries/summary_fields/test_plan.py",
        ),
        ui_runner_specs={},
        benchmark_allowlist={},
    )

    assert errors == []


def test_multiply_owned_ui_specs_fail_with_runner_guidance(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.inventory_errors_for_test_paths(
        ("apps/ui/tests/shared.spec.ts",),
        ui_runner_specs={
            "vitest": {"tests/shared.spec.ts"},
            "playwright-smoke": {"tests/shared.spec.ts"},
        },
        benchmark_allowlist={},
    )

    assert errors == [
        "apps/ui/tests/shared.spec.ts is owned by multiple UI runners "
        "['playwright-smoke', 'vitest']; tighten apps/ui/vitest.config.ts "
        "include/exclude or the Playwright testMatch patterns so exactly one "
        "runner owns it."
    ]
