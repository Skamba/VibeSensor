"""Guard: changed-path CI gating stays explicit and stable."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, fields
from types import ModuleType

import pytest

from tests._paths import REPO_ROOT

_CI_PATH_RULES = REPO_ROOT / "tools" / "tests" / "ci_path_rules.py"
_FULL_STACK = None


def _load_ci_path_rules_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ci_path_rules_local_test", _CI_PATH_RULES)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CI_PATH_RULES}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ci_path_rules() -> ModuleType:
    return _load_ci_path_rules_module()


@dataclass(frozen=True)
class SelectionCase:
    changed_files: tuple[str, ...]
    expected_jobs: frozenset[str] | None


def _all_jobs(module: ModuleType) -> frozenset[str]:
    return frozenset(field.name for field in fields(module.WorkflowJobSelection))


def _selected_jobs(module: ModuleType, changed_files: tuple[str, ...]) -> frozenset[str]:
    selection = module.workflow_job_selection(changed_files)
    return frozenset(
        field.name
        for field in fields(module.WorkflowJobSelection)
        if getattr(selection, field.name)
    )


_SELECTION_CASES = (
    pytest.param(
        SelectionCase(
            changed_files=("README.md", "docs/design_language.md"),
            expected_jobs=frozenset({"docs_lint"}),
        ),
        id="docs-only",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("apps/server/vibesensor/app/container.py",),
            expected_jobs=frozenset(
                {
                    "repo_hygiene",
                    "backend_lint",
                    "backend_static_guards",
                    "backend_preflight",
                    "backend_contract_drift",
                    "backend_typecheck",
                    "backend_tests",
                    "release_smoke",
                    "e2e",
                }
            ),
        ),
        id="backend-only",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("apps/ui/src/main.ts",),
            expected_jobs=frozenset(
                {
                    "repo_hygiene",
                    "frontend_typecheck",
                    "ui_smoke",
                    "release_smoke",
                    "e2e",
                }
            ),
        ),
        id="frontend-only",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("firmware/esp/src/main.cpp",),
            expected_jobs=frozenset({"firmware_native_tests"}),
        ),
        id="firmware-only",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("apps/ui/src/contracts/http_api_schema.json",),
            expected_jobs=frozenset(
                {
                    "repo_hygiene",
                    "backend_contract_drift",
                    "frontend_typecheck",
                    "ui_smoke",
                    "release_smoke",
                    "e2e",
                }
            ),
        ),
        id="contract-json",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("tools/config/sync_contract_artifacts.mjs",),
            expected_jobs=frozenset({"repo_hygiene", "backend_contract_drift"}),
        ),
        id="contract-sync-tool",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("tools/tests/run_ci_with_act.sh",),
            expected_jobs=frozenset({"shell_lint"}),
        ),
        id="shell-script-only",
    ),
    pytest.param(
        SelectionCase(
            changed_files=(".githooks/pre-push",),
            expected_jobs=frozenset({"shell_lint"}),
        ),
        id="githook-only",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("infra/pi-image/pi-gen/templates/stage-vibesensor/prerun.sh.template",),
            expected_jobs=frozenset({"shell_lint"}),
        ),
        id="pi-image-shell-template",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("apps/server/Dockerfile",),
            expected_jobs=_FULL_STACK,
        ),
        id="dockerfile-full-stack",
    ),
    pytest.param(
        SelectionCase(
            changed_files=(".github/workflows/ci.yml",),
            expected_jobs=_FULL_STACK,
        ),
        id="workflow-full-stack",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("README.md", "apps/ui/src/main.ts"),
            expected_jobs=frozenset(
                {
                    "docs_lint",
                    "repo_hygiene",
                    "frontend_typecheck",
                    "ui_smoke",
                    "release_smoke",
                    "e2e",
                }
            ),
        ),
        id="mixed-docs-and-frontend",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("apps/server/vibesensor/adapters/udp/protocol.py",),
            expected_jobs=frozenset(
                {
                    "repo_hygiene",
                    "backend_lint",
                    "backend_static_guards",
                    "backend_preflight",
                    "backend_contract_drift",
                    "backend_typecheck",
                    "backend_tests",
                    "release_smoke",
                    "firmware_native_tests",
                    "e2e",
                }
            ),
        ),
        id="backend-udp-protocol",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("apps/server/vibesensor/adapters/udp/udp_data_rx.py",),
            expected_jobs=frozenset(
                {
                    "repo_hygiene",
                    "backend_lint",
                    "backend_static_guards",
                    "backend_preflight",
                    "backend_contract_drift",
                    "backend_typecheck",
                    "backend_tests",
                    "release_smoke",
                    "e2e",
                }
            ),
        ),
        id="backend-udp-non-protocol",
    ),
    pytest.param(
        SelectionCase(
            changed_files=("docs/protocol.md",),
            expected_jobs=frozenset({"docs_lint", "repo_hygiene", "backend_contract_drift"}),
        ),
        id="protocol-doc",
    ),
)


@pytest.mark.parametrize("case", _SELECTION_CASES)
def test_workflow_job_selection_matrix(ci_path_rules: ModuleType, case: SelectionCase) -> None:
    expected_jobs = (
        _all_jobs(ci_path_rules) if case.expected_jobs is _FULL_STACK else case.expected_jobs
    )
    assert expected_jobs is not None
    assert _selected_jobs(ci_path_rules, case.changed_files) == expected_jobs
