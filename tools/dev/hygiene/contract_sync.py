# ruff: noqa: F403,F405
"""Contract synchronization entrypoint checks."""

from __future__ import annotations

import json
from collections.abc import Mapping


from ._shared import *
from .ci_workflow import (
    _extend_missing_text_requirements,
    _extend_step_requirement_errors,
    _load_ci_workflow,
    _workflow_job_steps,
)
from .repo_sync import _git_tracked_files


def check_contract_sync_entrypoint() -> list[str]:
    errors: list[str] = []

    package_json = json.loads(_UI_PACKAGE_JSON_PATH.read_text(encoding="utf-8"))
    scripts = package_json.get("scripts")
    if not isinstance(scripts, dict):
        return ["apps/ui/package.json must define a scripts object."]

    expected_scripts = {
        "sync:contracts": "node ../../tools/config/sync_contract_artifacts.mjs",
        "sync:generated-contracts": "node ../../tools/config/sync_shared_contracts_to_ui.mjs",
        "setup:generated-contracts": "node ../../tools/ui/ensure_ui_bootstrap.mjs --ensure-generated-contracts",
        "check:contracts": "node ../../tools/config/sync_shared_contracts_to_ui.mjs --check",
        "format:check": "biome check . --linter-enabled=false --assist-enabled=false",
        "build": "npm run check:contracts && vite build",
        "build:prevalidated-contracts": "vite build",
        "typecheck": "npm run check:contracts && tsc --noEmit",
        "typecheck:tests": "tsc --noEmit -p tsconfig.test.json",
        "pretest:smoke": "npm run sync:generated-contracts",
    }
    for script_name, expected_command in expected_scripts.items():
        actual_command = scripts.get(script_name)
        if actual_command != expected_command:
            errors.append(
                f"apps/ui/package.json script '{script_name}' must be {expected_command!r}, got {actual_command!r}."
            )
    for removed_script in ("pretypecheck", "prebuild"):
        if removed_script in scripts:
            errors.append(
                f"apps/ui/package.json must not define {removed_script!r}; build and typecheck should fail on stale derivatives instead of regenerating them automatically."
            )

    ui_test_tsconfig = ROOT / "apps/ui/tsconfig.test.json"
    if not ui_test_tsconfig.exists():
        errors.append(
            "apps/ui/tsconfig.test.json must define the frontend test TypeScript project."
        )
    ui_test_typecheck_script = ROOT / "apps/ui/tools/typecheck_tests_with_baseline.mjs"
    if ui_test_typecheck_script.exists():
        errors.append(
            "apps/ui/tools/typecheck_tests_with_baseline.mjs must not exist; UI test typecheck must use plain tsc."
        )
    ui_test_typecheck_baseline = ROOT / "apps/ui/tests/typecheck-baseline.txt"
    if ui_test_typecheck_baseline.exists():
        errors.append(
            "apps/ui/tests/typecheck-baseline.txt must not exist; UI test typecheck must be diagnostic-free."
        )

    makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    gitignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    tracked_paths = {str(path.relative_to(ROOT)) for path in _git_tracked_files()}
    expected_make_command = 'cd $(UI_DIR) && PYTHON="$$PYTHON" npm run sync:contracts $(if $(CHECK),-- --check,)'
    if expected_make_command not in makefile_text:
        errors.append(
            "Makefile sync-contracts target must route through apps/ui npm run sync:contracts and forward CHECK=1 to --check."
        )
    for rel_path in _UI_DERIVATIVE_GENERATED_ARTIFACTS:
        if rel_path in tracked_paths and (ROOT / rel_path).exists():
            errors.append(
                f"{rel_path} must stay out of git; regenerate it locally from the authoritative contract inputs instead."
            )
        if rel_path not in gitignore_text:
            errors.append(f".gitignore must ignore {rel_path}.")

    for rel_path in (
        "tools/config/sync_contract_artifacts.mjs",
        "tools/config/sync_shared_contracts_to_ui.mjs",
    ):
        text = (ROOT / rel_path).read_text(encoding="utf-8")
        if "resolveConfiguredPythonCommand(root)" not in text:
            errors.append(
                f"{rel_path} must resolve Python through tools/config/python_runtime.mjs."
            )
        if "process.env.PYTHON ||" in text or "|| 'python3'" in text:
            errors.append(
                f"{rel_path} must not fall back to ambient python3; use the configured Python runtime."
            )

    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        return errors

    backend_contract_drift_steps = _workflow_job_steps(jobs, "backend-contract-drift")
    if backend_contract_drift_steps is not None:
        _extend_step_requirement_errors(
            errors,
            backend_contract_drift_steps,
            (
                WorkflowStepRequirement(
                    uses="actions/setup-node@v6",
                    error_message=(
                        "backend-contract-drift must install Node because the authoritative contract sync "
                        "runs the UI derivative generator."
                    ),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run=_UI_BOOTSTRAP_HELPER_WORKFLOW_CMD,
                    error_message=(
                        "backend-contract-drift must install UI dependencies from apps/ui before running "
                        "the authoritative contract sync check."
                    ),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run=_UI_DERIVATIVE_SETUP_WORKFLOW_CMD,
                    error_message=(
                        "backend-contract-drift must materialize missing UI contract derivatives on "
                        "fresh checkouts before running the authoritative contract sync check."
                    ),
                ),
                WorkflowStepRequirement(
                    run="make sync-contracts CHECK=1",
                    error_message=(
                        "backend-contract-drift must run `make sync-contracts CHECK=1` as the "
                        "authoritative contract sync check."
                    ),
                ),
            ),
        )

    frontend_quality_steps = _workflow_job_steps(jobs, _FRONTEND_QUALITY_JOB)
    if frontend_quality_steps is not None:
        _extend_step_requirement_errors(
            errors,
            frontend_quality_steps,
            (
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run="npm run lint",
                    error_message=("frontend-quality must run UI lint in apps/ui."),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run="npm run format:check",
                    error_message=(
                        "frontend-quality must run the UI formatter drift check in apps/ui."
                    ),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run="npm run lint:deps",
                    error_message=(
                        "frontend-quality must run UI dependency boundary checks in apps/ui."
                    ),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run="npm run lint:unused",
                    error_message=(
                        "frontend-quality must run UI dead-code checks in apps/ui."
                    ),
                ),
                WorkflowStepRequirement(
                    run="npm run typecheck",
                    forbidden=True,
                    error_message=(
                        "frontend-quality must not run npm run typecheck; that gate belongs in frontend-typecheck."
                    ),
                ),
            ),
        )

    frontend_typecheck_steps = _workflow_job_steps(jobs, _FRONTEND_TYPECHECK_JOB)
    if frontend_typecheck_steps is not None:
        _extend_step_requirement_errors(
            errors,
            frontend_typecheck_steps,
            (
                WorkflowStepRequirement(
                    run="npm run check:contracts",
                    forbidden=True,
                    error_message=(
                        "frontend-typecheck must not run npm run check:contracts; the authoritative "
                        "contract sync check belongs in backend-contract-drift."
                    ),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run="npm run sync:generated-contracts",
                    error_message=(
                        "frontend-typecheck must explicitly sync generated UI contract derivatives before "
                        "running npm run typecheck."
                    ),
                ),
                WorkflowStepRequirement(
                    working_directory="apps/ui",
                    run="npm run typecheck:tests",
                    error_message=(
                        "frontend-typecheck must run the UI test TypeScript project."
                    ),
                ),
                WorkflowStepRequirement(
                    run="npm run lint",
                    forbidden=True,
                    error_message=(
                        "frontend-typecheck must not run npm run lint; that gate belongs in frontend-quality."
                    ),
                ),
                WorkflowStepRequirement(
                    run="npm run format:check",
                    forbidden=True,
                    error_message=(
                        "frontend-typecheck must not run npm run format:check; that gate belongs in frontend-quality."
                    ),
                ),
                WorkflowStepRequirement(
                    run="npm run lint:deps",
                    forbidden=True,
                    error_message=(
                        "frontend-typecheck must not run npm run lint:deps; that gate belongs in frontend-quality."
                    ),
                ),
                WorkflowStepRequirement(
                    run="npm run lint:unused",
                    forbidden=True,
                    error_message=(
                        "frontend-typecheck must not run npm run lint:unused; that gate belongs in frontend-quality."
                    ),
                ),
            ),
        )

    ui_build_artifact_steps = _workflow_job_steps(jobs, _UI_BUILD_ARTIFACT_JOB)
    if ui_build_artifact_steps is not None:
        _extend_step_requirement_errors(
            errors,
            ui_build_artifact_steps,
            (
                WorkflowStepRequirement(
                    run='"${{ steps.setup-python.outputs.python-path }}" tools/build_ui_static.py --skip-typecheck --assume-prevalidated-contracts',
                    error_message=(
                        "ui-build-artifact must build static assets with tools/build_ui_static.py "
                        "--skip-typecheck --assume-prevalidated-contracts."
                    ),
                ),
            ),
        )

    docs_lint_steps = _workflow_job_steps(jobs, "docs-lint")
    if docs_lint_steps is not None:
        _extend_step_requirement_errors(
            errors,
            docs_lint_steps,
            (
                WorkflowStepRequirement(
                    step_id="setup-python",
                    uses=_LOCAL_PYTHON_SETUP_ACTION,
                    error_message="docs-lint must use ./.github/actions/setup-python.",
                ),
                WorkflowStepRequirement(
                    uses=_LOCAL_BACKEND_SETUP_ACTION,
                    forbidden=True,
                    error_message="docs-lint must not use ./.github/actions/setup-backend.",
                ),
                WorkflowStepRequirement(
                    run='"${{ steps.setup-python.outputs.python-path }}" tools/dev/docs_lint.py',
                    error_message=(
                        "docs-lint must invoke tools/dev/docs_lint.py with the configured setup-python "
                        "interpreter path."
                    ),
                ),
            ),
        )

    for path in (_UI_README_PATH, _SERVER_README_PATH, _CONTRIBUTING_PATH):
        _extend_missing_text_requirements(
            errors,
            path.read_text(encoding="utf-8"),
            (
                TextRequirement(
                    needle="make sync-contracts",
                    error_message=(
                        f"{path.relative_to(ROOT)} must point readers at `make sync-contracts`."
                    ),
                ),
            ),
        )

    return errors
