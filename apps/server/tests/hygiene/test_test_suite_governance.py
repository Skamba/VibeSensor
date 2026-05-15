"""High-signal test-suite governance checks."""

from __future__ import annotations

from types import ModuleType

import pytest
from test_support.check_hygiene_loader import load_check_hygiene_module


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return load_check_hygiene_module("check_hygiene_test_suite_governance")


def test_inventory_reports_unowned_and_multiply_owned_tests(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.inventory_errors_for_test_paths(
        (
            "tools/test_orphan.py",
            "apps/ui/tests/shared.spec.ts",
        ),
        ui_runner_specs={
            "vitest": {"tests/shared.spec.ts"},
            "playwright-smoke": {"tests/shared.spec.ts"},
        },
        benchmark_allowlist={},
    )

    assert any(
        "tools/test_orphan.py" in error and "not owned by any configured runner" in error
        for error in errors
    )
    assert any(
        "apps/ui/tests/shared.spec.ts" in error and "owned by multiple UI runners" in error
        for error in errors
    )
    assert len(errors) == 2


def test_marker_policy_reports_fast_lane_blind_spots(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.marker_policy_errors(
        {
            "apps/server/tests/use_cases/demo/test_demo.py": {
                "smoke": {"test_demo_path"},
            },
            "apps/server/tests/integration/test_live_server.py": {
                "e2e": {"TestLiveServer"},
            },
            "apps/server/tests/integration/test_perf.py": {
                "benchmark": {"test_perf_regression"},
            },
            "apps/server/tests_e2e/test_missing_module_marker.py": {},
        },
        tracked_e2e_files=("apps/server/tests_e2e/test_missing_module_marker.py",),
        tracked_benchmark_files=(),
        smoke_allowlist={},
        long_sim_allowlist={},
        e2e_file_exemptions={},
    )

    assert any("marked smoke but is not listed" in error for error in errors)
    assert any("marked e2e outside apps/server/tests_e2e/" in error for error in errors)
    assert any("marked benchmark but does not live" in error for error in errors)
    assert any("missing module-level pytest.mark.e2e" in error for error in errors)
    assert len(errors) == 4
