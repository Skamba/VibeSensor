"""Guard the AI/dev validation planner."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from tests._paths import REPO_ROOT

_PLAN_VALIDATION = REPO_ROOT / "tools" / "tests" / "plan_validation.py"


def _load_plan_validation_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "plan_validation_local_for_tests", _PLAN_VALIDATION
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_PLAN_VALIDATION}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_changed_files(
    module: ModuleType,
    monkeypatch,
    changed_files: tuple[str, ...],
) -> None:
    monkeypatch.setattr(module._RUN_CHANGED, "_resolve_base_ref", lambda _ref: "origin/main")
    monkeypatch.setattr(module._RUN_CHANGED, "_changed_files", lambda _base: changed_files)


def test_plan_validation_uses_ci_path_rules_for_docs_only_changes(monkeypatch) -> None:
    module = _load_plan_validation_module()
    _install_changed_files(module, monkeypatch, ("docs/testing.md",))

    plan = module.build_validation_plan("origin/main")

    assert plan.ci_jobs == ("docs-lint",)
    assert plan.local_jobs == ("docs-lint",)
    assert plan.act_jobs == ("docs-lint",)
    assert plan.local_command[-2:] == ("--job", "docs-lint")
    assert plan.act_command[-2:] == ("-j", "docs-lint")
    assert plan.parity == "approximate"
    assert plan.unsupported == ()
    assert plan.github_outputs["run_docs_lint"] == "true"
    assert plan.github_outputs["run_backend_tests"] == "false"


def test_plan_validation_expands_backend_tests_for_local_runner(monkeypatch) -> None:
    module = _load_plan_validation_module()
    _install_changed_files(
        module,
        monkeypatch,
        ("apps/server/vibesensor/use_cases/run/post_analysis_executor.py",),
    )

    plan = module.build_validation_plan("origin/main")

    assert "backend-tests" in plan.ci_jobs
    assert "backend-tests" in plan.act_jobs
    assert all(f"backend-tests-{index}" in plan.local_jobs for index in range(1, 6))
    assert plan.github_outputs["run_backend_tests"] == "true"


def test_plan_validation_marks_release_smoke_as_approximate_not_unsupported(
    monkeypatch,
) -> None:
    module = _load_plan_validation_module()
    _install_changed_files(module, monkeypatch, ("tools/tests/run_release_smoke.py",))

    plan = module.build_validation_plan("origin/main")

    assert "ui-build-artifact" in plan.ci_jobs
    assert "release-smoke" in plan.ci_jobs
    assert "release-smoke" in plan.local_jobs
    assert "repo-hygiene" in plan.local_jobs
    assert "backend-lint" in plan.local_jobs
    assert plan.parity == "approximate"
    assert plan.unsupported == ()
    assert any("ui-build-artifact" in note for note in plan.approximations)
