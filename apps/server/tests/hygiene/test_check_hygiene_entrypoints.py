"""Consolidated pytest entrypoints for repository hygiene checks."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

import pytest
from _paths import REPO_ROOT

_CHECK_HYGIENE = REPO_ROOT / "tools" / "dev" / "check_hygiene.py"

_CHECK_ENTRYPOINTS = (
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
    pytest.param("check_frontend_raw_html_boundaries", id="frontend-raw-html-boundaries"),
    pytest.param("check_runtime_policy_drift", id="runtime-policy-drift"),
)


def _load_check_hygiene_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_hygiene_test_entrypoints",
        _CHECK_HYGIENE,
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_CHECK_HYGIENE}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return _load_check_hygiene_module()


@pytest.mark.parametrize("check_name", _CHECK_ENTRYPOINTS)
def test_check_hygiene_entrypoints_pass(
    hygiene_module: ModuleType,
    check_name: str,
) -> None:
    check = getattr(hygiene_module, check_name)
    assert check() == []
