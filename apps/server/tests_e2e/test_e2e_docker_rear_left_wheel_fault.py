from __future__ import annotations

import pytest

from tests_e2e._docker_wheel_fault_helpers import (
    assert_localized_wheel_fault_alignment,
    assert_localized_wheel_fault_report,
    assert_localized_wheel_fault_summary,
    cleanup_localized_wheel_fault_run,
    fetch_wheel_fault_artifacts,
    normalize_location,
    run_localized_wheel_fault_capture,
)

pytestmark = pytest.mark.e2e


@pytest.mark.parametrize(
    "fault_wheel", ["front-left", "rear-left"], ids=["front-left", "rear-left"]
)
def test_e2e_docker_localized_wheel_fault(
    e2e_env: dict[str, str],
    fault_wheel: str,
) -> None:
    expected_location = normalize_location(fault_wheel)
    run_id: str | None = None
    try:
        run_id = run_localized_wheel_fault_capture(e2e_env, fault_wheel=fault_wheel)
        artifacts = fetch_wheel_fault_artifacts(e2e_env["base_url"], run_id)

        primary_finding = assert_localized_wheel_fault_summary(
            artifacts,
            expected_location=expected_location,
        )
        assert_localized_wheel_fault_report(
            artifacts,
            expected_location=expected_location,
            primary_finding=primary_finding,
        )
        assert_localized_wheel_fault_alignment(artifacts)
    finally:
        cleanup_localized_wheel_fault_run(e2e_env["base_url"], run_id)
