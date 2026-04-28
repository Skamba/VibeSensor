"""Guard: changed-path CI gating stays explicit and stable."""

from __future__ import annotations

import importlib.util
import sys

from tests._paths import REPO_ROOT

_CI_PATH_RULES = REPO_ROOT / "tools" / "tests" / "ci_path_rules.py"


def _load_ci_path_rules_module():
    spec = importlib.util.spec_from_file_location("ci_path_rules_local_test", _CI_PATH_RULES)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CI_PATH_RULES}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docs_only_changes_only_run_docs_lint() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("README.md", "docs/design_language.md"))
    assert selection.docs_lint is True
    assert selection.repo_hygiene is False
    assert selection.backend_lint is False
    assert selection.frontend_typecheck is False
    assert selection.release_smoke is False
    assert selection.firmware_native_tests is False
    assert selection.e2e is False


def test_frontend_only_changes_run_frontend_and_release_checks() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("apps/ui/src/main.ts",))
    assert selection.repo_hygiene is True
    assert selection.frontend_typecheck is True
    assert selection.ui_smoke is True
    assert selection.release_smoke is True
    assert selection.backend_tests is False
    assert selection.firmware_native_tests is False


def test_authoritative_contract_input_changes_run_frontend_and_contract_drift() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("apps/ui/src/contracts/http_api_schema.json",))
    assert selection.repo_hygiene is True
    assert selection.backend_contract_drift is True
    assert selection.frontend_typecheck is True
    assert selection.ui_smoke is True
    assert selection.release_smoke is True


def test_backend_only_changes_run_backend_stack_without_frontend_smoke() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("apps/server/vibesensor/app/container.py",))
    assert selection.repo_hygiene is True
    assert selection.backend_lint is True
    assert selection.backend_static_guards is True
    assert selection.backend_preflight is True
    assert selection.backend_contract_drift is True
    assert selection.backend_typecheck is True
    assert selection.backend_tests is True
    assert selection.release_smoke is True
    assert selection.e2e is True
    assert selection.frontend_typecheck is False
    assert selection.ui_smoke is False
    assert selection.firmware_native_tests is False


def test_firmware_only_changes_run_only_firmware_native_checks() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("firmware/esp/src/main.cpp",))
    assert selection.firmware_native_tests is True
    assert selection.backend_lint is False
    assert selection.frontend_typecheck is False
    assert selection.release_smoke is False
    assert selection.e2e is False


def test_backend_udp_protocol_changes_also_run_firmware_native_checks() -> None:
    module = _load_ci_path_rules_module()

    for changed_path in (
        "apps/server/vibesensor/adapters/udp/protocol.py",
        "apps/server/vibesensor/adapters/udp/protocol_validator.py",
    ):
        selection = module.workflow_job_selection((changed_path,))
        assert selection.backend_lint is True
        assert selection.backend_static_guards is True
        assert selection.backend_preflight is True
        assert selection.backend_contract_drift is True
        assert selection.backend_typecheck is True
        assert selection.backend_tests is True
        assert selection.release_smoke is True
        assert selection.e2e is True
        assert selection.firmware_native_tests is True
        assert selection.frontend_typecheck is False
        assert selection.ui_smoke is False


def test_non_protocol_backend_udp_changes_do_not_run_firmware_native_checks() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(
        ("apps/server/vibesensor/adapters/udp/udp_data_rx.py",)
    )
    assert selection.backend_lint is True
    assert selection.backend_static_guards is True
    assert selection.backend_preflight is True
    assert selection.backend_contract_drift is True
    assert selection.backend_typecheck is True
    assert selection.backend_tests is True
    assert selection.release_smoke is True
    assert selection.e2e is True
    assert selection.firmware_native_tests is False
    assert selection.frontend_typecheck is False
    assert selection.ui_smoke is False


def test_workflow_changes_fall_back_to_full_stack() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection((".github/workflows/ci.yml",))
    assert selection == module.WorkflowJobSelection.full_stack()


def test_protocol_doc_changes_run_docs_lint_and_contract_drift() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("docs/protocol.md",))
    assert selection.docs_lint is True
    assert selection.repo_hygiene is True
    assert selection.backend_contract_drift is True
    assert selection.frontend_typecheck is False


def test_contract_sync_tool_changes_run_repo_hygiene_and_contract_drift() -> None:
    module = _load_ci_path_rules_module()

    selection = module.workflow_job_selection(("tools/config/sync_contract_artifacts.mjs",))
    assert selection.repo_hygiene is True
    assert selection.backend_contract_drift is True
    assert selection.backend_lint is False
    assert selection.frontend_typecheck is False
