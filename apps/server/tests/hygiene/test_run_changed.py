"""Guard the heuristic changed-file test runner."""

from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from tests._paths import REPO_ROOT

_RUN_CHANGED = REPO_ROOT / "tools" / "tests" / "run_changed.py"


def _load_run_changed_module():
    spec = importlib.util.spec_from_file_location("run_changed_local_for_tests", _RUN_CHANGED)
    assert spec is not None and spec.loader is not None, f"Unable to load {_RUN_CHANGED}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plan_commands_maps_backend_source_to_mirrored_test_dir() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(
        ("apps/server/vibesensor/shared/boundaries/summary_fields/finding.py",)
    )

    assert commands == (
        module.PlannedCommand(
            "pytest",
            (sys.executable, "-m", "pytest", "-q", "apps/server/tests/shared"),
        ),
    )


def test_plan_commands_uses_changed_test_file_directly() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(
        ("apps/server/tests/shared/boundaries/test_finding_roundtrip.py",)
    )

    assert commands == (
        module.PlannedCommand(
            "pytest",
            (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "apps/server/tests/shared/boundaries/test_finding_roundtrip.py",
            ),
        ),
    )


def test_plan_commands_uses_parent_dir_for_deleted_changed_test_file() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(
        ("apps/server/tests/adapters/http/test_deleted_settings_endpoints.py",)
    )

    assert commands == (
        module.PlannedCommand(
            "pytest",
            (
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "apps/server/tests/adapters/http",
            ),
        ),
    )


def test_plan_commands_combines_docs_ui_and_hygiene_checks() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(("README.md", "apps/ui/package.json", "Makefile"))

    assert commands == (
        module.PlannedCommand("docs-lint", ("make", "docs-lint")),
        module.PlannedCommand("ui-typecheck", ("make", "ui-typecheck")),
        module.PlannedCommand(
            "pytest",
            (sys.executable, "-m", "pytest", "-q", "apps/server/tests/hygiene"),
        ),
    )


def test_plan_commands_runs_ui_unit_tests_for_changed_ui_source_files() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(("apps/ui/src/ws_payload_validator.ts",))

    assert commands == (
        module.PlannedCommand("ui-test", ("make", "ui-test")),
        module.PlannedCommand("ui-typecheck", ("make", "ui-typecheck")),
    )


def test_plan_commands_keeps_non_source_ui_changes_on_typecheck_only() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(("apps/ui/package.json",))

    assert commands == (module.PlannedCommand("ui-typecheck", ("make", "ui-typecheck")),)


def test_plan_commands_falls_back_to_make_test_for_unmapped_backend_changes() -> None:
    module = _load_run_changed_module()

    commands = module._plan_commands(("apps/server/vibesensor/_version.py",))

    assert commands == (module.PlannedCommand("backend-tests", ("make", "test")),)


def test_changed_files_includes_committed_and_worktree_changes(monkeypatch) -> None:
    module = _load_run_changed_module()
    outputs = {
        ("merge-base", "origin/main", "HEAD"): "abc123",
        ("diff", "--name-only", "abc123..HEAD"): "docs/testing.md\n",
        ("diff", "--name-only", "--cached"): "Makefile\n",
        ("diff", "--name-only"): "CONTRIBUTING.md\n",
        ("ls-files", "--others", "--exclude-standard"): "tools/tests/run_changed.py\n",
    }

    monkeypatch.setattr(module, "_git_output", lambda *args: outputs.get(args, ""))

    assert module._changed_files("origin/main") == (
        "CONTRIBUTING.md",
        "Makefile",
        "docs/testing.md",
        "tools/tests/run_changed.py",
    )


def test_changed_files_exits_cleanly_when_merge_base_is_missing(monkeypatch) -> None:
    module = _load_run_changed_module()

    def _raise_on_merge_base(*args: str) -> str:
        if args == ("merge-base", "origin/main", "HEAD"):
            raise subprocess.CalledProcessError(128, ("git", *args))
        return ""

    monkeypatch.setattr(module, "_git_output", _raise_on_merge_base)

    with pytest.raises(SystemExit, match="Unable to find a common ancestor"):
        module._changed_files("origin/main")
