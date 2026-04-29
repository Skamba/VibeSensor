"""Guard: pytest marker usage stays within the documented policy."""

from __future__ import annotations

from types import ModuleType

import pytest
from test_support.check_hygiene_loader import load_check_hygiene_module


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return load_check_hygiene_module("check_hygiene_test_marker_policy")


def test_test_marker_policy_guard_passes_for_current_repo(
    hygiene_module: ModuleType,
) -> None:
    assert hygiene_module.check_test_marker_policy() == []


def test_smoke_marker_outside_allowlist_fails(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.marker_policy_errors(
        {
            "apps/server/tests/use_cases/demo/test_demo.py": {
                "smoke": {"test_demo_path"},
            }
        },
        tracked_e2e_files=(),
        tracked_benchmark_files=(),
        smoke_allowlist={},
        long_sim_allowlist={},
        e2e_file_exemptions={},
    )

    assert errors == [
        "apps/server/tests/use_cases/demo/test_demo.py::test_demo_path is marked smoke "
        "but is not listed in tools/dev/test_marker_policy_allowlist.yml under smoke; "
        "remove pytest.mark.smoke or document why it belongs in the compact critical path."
    ]


def test_e2e_outside_tests_e2e_requires_long_sim(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.marker_policy_errors(
        {
            "apps/server/tests/integration/test_live_server.py": {
                "e2e": {"TestLiveServer"},
            }
        },
        tracked_e2e_files=(),
        tracked_benchmark_files=(),
        smoke_allowlist={},
        long_sim_allowlist={},
        e2e_file_exemptions={},
    )

    assert errors == [
        "apps/server/tests/integration/test_live_server.py::TestLiveServer is marked e2e "
        "outside apps/server/tests_e2e/ but is not marked long_sim; add "
        "pytest.mark.long_sim so fast E2E lanes keep excluding it."
    ]


def test_tests_e2e_file_exemption_skips_module_level_e2e_requirement(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.marker_policy_errors(
        {
            "apps/server/tests_e2e/test_special_case.py": {},
        },
        tracked_e2e_files=("apps/server/tests_e2e/test_special_case.py",),
        tracked_benchmark_files=(),
        smoke_allowlist={},
        long_sim_allowlist={},
        e2e_file_exemptions={
            "apps/server/tests_e2e/test_special_case.py": "Intentional non-pytest fixture shell."
        },
    )

    assert errors == []


def test_benchmark_marker_outside_benchmark_file_fails(
    hygiene_module: ModuleType,
) -> None:
    errors = hygiene_module.marker_policy_errors(
        {
            "apps/server/tests/integration/test_perf.py": {
                "benchmark": {"test_perf_regression"},
            }
        },
        tracked_e2e_files=(),
        tracked_benchmark_files=(),
        smoke_allowlist={},
        long_sim_allowlist={},
        e2e_file_exemptions={},
    )

    assert errors == [
        "apps/server/tests/integration/test_perf.py::test_perf_regression is marked "
        "benchmark but does not live in apps/server/tests/**/benchmark_*.py; move it "
        "into an explicit benchmark file or remove pytest.mark.benchmark."
    ]
