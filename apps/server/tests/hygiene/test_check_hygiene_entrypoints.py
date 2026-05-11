"""Consolidated pytest entrypoints for repository hygiene checks."""

from __future__ import annotations

from types import ModuleType

import pytest
from test_support.check_hygiene_loader import load_check_hygiene_module

_CHECK_ENTRYPOINTS = (
    pytest.param("check_changed_scope_command_docs", id="changed-scope-command-docs"),
    pytest.param("check_ci_command_sync", id="ci-command-sync"),
    pytest.param("check_ci_job_sync", id="ci-job-sync"),
    pytest.param("check_ci_lite_job_sync", id="ci-lite-job-sync"),
    pytest.param("check_contract_sync_entrypoint", id="contract-sync-entrypoint"),
    pytest.param(
        "check_dependency_reproducibility_hygiene",
        id="dependency-reproducibility-hygiene",
    ),
    pytest.param(
        "check_docker_ci_dependency_hygiene",
        id="docker-ci-dependency-hygiene",
    ),
    pytest.param("check_docker_dev_workflow_hygiene", id="docker-dev-workflow-hygiene"),
    pytest.param(
        "check_frontend_dom_registry_guardrails",
        id="frontend-dom-registry-guardrails",
    ),
    pytest.param(
        "check_frontend_component_use_computed_guardrails",
        id="frontend-component-usecomputed-guardrails",
    ),
    pytest.param(
        "check_frontend_generated_contract_boundaries",
        id="frontend-generated-contract-boundaries",
    ),
    pytest.param(
        "check_frontend_manual_chunk_packages",
        id="frontend-manual-chunk-packages",
    ),
    pytest.param("check_frontend_raw_html_boundaries", id="frontend-raw-html-boundaries"),
    pytest.param(
        "check_github_actions_python_runtime_usage",
        id="github-actions-python-runtime-usage",
    ),
    pytest.param("check_hotspot_script_guardrails", id="hotspot-script-guardrails"),
    pytest.param("check_pi_image_workflow_contract", id="pi-image-workflow-contract"),
    pytest.param("check_test_inventory_ownership", id="test-inventory-ownership"),
    pytest.param("check_test_marker_policy", id="test-marker-policy"),
    pytest.param("check_runtime_policy_drift", id="runtime-policy-drift"),
    pytest.param("check_ui_vite_server_contract", id="ui-vite-server-contract"),
)


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return load_check_hygiene_module("check_hygiene_test_entrypoints")


@pytest.mark.parametrize("check_name", _CHECK_ENTRYPOINTS)
def test_check_hygiene_entrypoints_pass(
    hygiene_module: ModuleType,
    check_name: str,
) -> None:
    check = getattr(hygiene_module, check_name)
    assert check() == []


def test_check_hygiene_main_passes(hygiene_module: ModuleType) -> None:
    assert hygiene_module.main() == 0
