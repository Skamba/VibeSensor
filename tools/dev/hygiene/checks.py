"""Repository hygiene check orchestration."""

from __future__ import annotations

import sys

from . import layout_checks as _layout_checks
from ._shared import ROOT, ListCheckSpec
from .ci_workflow import (
    check_ci_command_sync,
    check_ci_job_sync,
    check_ci_lite_job_sync,
)
from .contract_sync import check_contract_sync_entrypoint
from .docker_ci import check_docker_ci_dependency_hygiene
from .frontend_boundaries import (
    check_frontend_component_use_computed_guardrails,
    check_frontend_dom_registry_guardrails,
    check_frontend_generated_contract_boundaries,
    check_frontend_legacy_test_dom_bridge_guardrails,
    check_frontend_manual_chunk_packages,
    check_frontend_raw_html_boundaries,
)
from .repo_sync import _git_tracked_files, check_line_endings, check_path_indirections
from .runtime_policy import (
    check_dependency_reproducibility_hygiene,
    check_python_policy_alignment,
    check_runtime_policy_drift,
)
from .layout_checks import (
    check_oversized_test_files,
    check_test_inventory_ownership,
    check_test_marker_policy,
)


def all_ui_specs() -> set[str]:
    return _layout_checks.all_ui_specs()


def ui_runner_owned_specs() -> dict[str, set[str]]:
    return _layout_checks.ui_runner_owned_specs()


def inventory_errors_for_test_paths(*args: object, **kwargs: object) -> list[str]:
    return _layout_checks.inventory_errors_for_test_paths(*args, **kwargs)


def marker_policy_errors(*args: object, **kwargs: object) -> list[str]:
    return _layout_checks.marker_policy_errors(*args, **kwargs)


def _marker_policy_test_files() -> list[object]:
    original_root = _layout_checks.ROOT
    original_git_tracked_files = _layout_checks._git_tracked_files
    try:
        _layout_checks.ROOT = ROOT
        _layout_checks._git_tracked_files = _git_tracked_files
        return _layout_checks._marker_policy_test_files()
    finally:
        _layout_checks.ROOT = original_root
        _layout_checks._git_tracked_files = original_git_tracked_files


_LIST_CHECK_SPECS = (
    ListCheckSpec(
        runner=check_ci_job_sync,
        failure_heading="CI job sync drift detected:",
        success_message="CI job names in sync between the workflow manifest and run_ci_parallel.py.",
    ),
    ListCheckSpec(
        runner=check_ci_command_sync,
        failure_heading="CI command sync drift detected:",
        success_message="CI commands in sync between the workflow manifest and run_ci_parallel.py.",
    ),
    ListCheckSpec(
        runner=check_ci_lite_job_sync,
        failure_heading="CI lite job drift detected:",
        success_message="CI-lite entrypoints match the workflow-backed non-Docker subset.",
    ),
    ListCheckSpec(
        runner=check_contract_sync_entrypoint,
        failure_heading="Contract sync entrypoint drift detected:",
        success_message="Contract sync entrypoint checks passed.",
    ),
    ListCheckSpec(
        runner=check_docker_ci_dependency_hygiene,
        failure_heading="Docker/CI dependency hygiene drift detected:",
        success_message="Docker/CI dependency hygiene checks passed.",
    ),
    ListCheckSpec(
        runner=check_python_policy_alignment,
        failure_heading="Python policy alignment drift detected:",
        success_message="Python policy alignment checks passed.",
    ),
    ListCheckSpec(
        runner=check_runtime_policy_drift,
        failure_heading="Runtime policy drift detected:",
        success_message="Runtime policy drift checks passed.",
    ),
    ListCheckSpec(
        runner=check_dependency_reproducibility_hygiene,
        failure_heading="Dependency reproducibility hygiene drift detected:",
        success_message="Dependency reproducibility hygiene checks passed.",
    ),
    ListCheckSpec(
        runner=check_frontend_generated_contract_boundaries,
        failure_heading="Frontend generated-contract boundary drift detected:",
        success_message="Frontend generated-contract boundaries passed.",
    ),
    ListCheckSpec(
        runner=check_frontend_manual_chunk_packages,
        failure_heading="Frontend manual chunk package drift detected:",
        success_message="Frontend manual chunk package checks passed.",
    ),
    ListCheckSpec(
        runner=check_frontend_raw_html_boundaries,
        failure_heading="Frontend raw HTML boundary drift detected:",
        success_message="Frontend raw HTML boundaries passed.",
    ),
    ListCheckSpec(
        runner=check_frontend_dom_registry_guardrails,
        failure_heading="Frontend DOM registry guardrail drift detected:",
        success_message="Frontend DOM registry guardrails passed.",
    ),
    ListCheckSpec(
        runner=check_frontend_legacy_test_dom_bridge_guardrails,
        failure_heading="Frontend legacy test-DOM guardrail drift detected:",
        success_message="Frontend legacy test-DOM guardrails passed.",
    ),
    ListCheckSpec(
        runner=check_frontend_component_use_computed_guardrails,
        failure_heading="Frontend component useComputed guardrail drift detected:",
        success_message="Frontend component useComputed guardrails passed.",
    ),
    ListCheckSpec(
        runner=check_test_inventory_ownership,
        failure_heading="Test inventory ownership drift detected:",
        success_message="Committed test-looking files all map to a runner or documented benchmark exception.",
    ),
    ListCheckSpec(
        runner=check_test_marker_policy,
        failure_heading="Test marker policy drift detected:",
        success_message="Pytest marker policy checks passed.",
    ),
)


def _run_list_check(spec: ListCheckSpec) -> int:
    errors = spec.runner()
    if errors:
        print(spec.failure_heading)
        for item in errors:
            print(f"  - {item}")
        return 1
    print(spec.success_message)
    return 0


def main() -> int:
    failures = 0

    crlf = check_line_endings()
    if crlf:
        print("CRLF line endings found:")
        for item in crlf:
            print(f"  - {item}")
        failures += 1
    else:
        print("Line ending check passed (LF-only for tracked text files).")

    pointer_files, path_hacks = check_path_indirections()
    if pointer_files or path_hacks:
        if pointer_files:
            print("Pointer-style files found:")
            for item in pointer_files:
                print(f"  - {item}")
        if path_hacks:
            print("sys.path/PYTHONPATH hacks found in Python files:")
            for item in path_hacks:
                print(f"  - {item}")
        failures += 1
    else:
        print("No path-indirection files or sys.path/PYTHONPATH hacks found.")

    for spec in _LIST_CHECK_SPECS:
        failures += _run_list_check(spec)

    oversized_test_errors, oversized_test_report = check_oversized_test_files()
    if oversized_test_errors:
        print("Oversized test/spec guardrail drift detected:")
        for item in oversized_test_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Oversized test/spec guardrails passed.")
    print("Largest tracked test/spec files:")
    for item in oversized_test_report:
        print(f"  - {item}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
