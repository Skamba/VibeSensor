"""Guard the heuristic changed-file runner through CLI-visible behavior."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from dataclasses import fields

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


def _git_outputs(
    *,
    committed: tuple[str, ...] = (),
    staged: tuple[str, ...] = (),
    unstaged: tuple[str, ...] = (),
    untracked: tuple[str, ...] = (),
) -> dict[tuple[str, ...], object]:
    return {
        ("merge-base", "origin/main", "HEAD"): "abc123",
        ("diff", "--name-only", "abc123..HEAD"): "\n".join(committed),
        ("diff", "--name-only", "--cached"): "\n".join(staged),
        ("diff", "--name-only"): "\n".join(unstaged),
        ("ls-files", "--others", "--exclude-standard"): "\n".join(untracked),
    }


def _install_git_state(
    monkeypatch: pytest.MonkeyPatch,
    module,
    *,
    outputs: dict[tuple[str, ...], object],
    valid_refs: tuple[str, ...] = ("origin/main",),
) -> None:
    def _fake_run(command, **_kwargs):
        assert command[:3] == ["git", "rev-parse", "--verify"]
        ref = command[3]
        return subprocess.CompletedProcess(command, 0 if ref in valid_refs else 1)

    def _fake_check_output(command, **_kwargs):
        assert command[0] == "git"
        payload = outputs.get(tuple(command[1:]), "")
        if isinstance(payload, BaseException):
            raise payload
        return payload

    monkeypatch.setattr(module.subprocess, "run", _fake_run)
    monkeypatch.setattr(module.subprocess, "check_output", _fake_check_output)


def _run_dry_run(
    module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    committed: tuple[str, ...] = (),
    staged: tuple[str, ...] = (),
    unstaged: tuple[str, ...] = (),
    untracked: tuple[str, ...] = (),
) -> str:
    _install_git_state(
        monkeypatch,
        module,
        outputs=_git_outputs(
            committed=committed,
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
        ),
    )
    assert module.main(["--dry-run"]) == 0
    return capsys.readouterr().out


def test_main_dry_run_maps_backend_source_to_mirrored_test_dir(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("apps/server/vibesensor/shared/boundaries/summary_fields/finding.py",),
    )

    assert (
        f"[test-changed] pytest: {sys.executable} -m pytest -q apps/server/tests/shared" in output
    )


def test_main_dry_run_uses_changed_test_file_directly(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("apps/server/tests/shared/boundaries/test_finding_roundtrip.py",),
    )

    assert (
        f"{sys.executable} -m pytest -q apps/server/tests/shared/boundaries/"
        "test_finding_roundtrip.py"
    ) in output


def test_main_dry_run_uses_parent_dir_for_deleted_changed_test_file(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("apps/server/tests/adapters/http/test_deleted_settings_endpoints.py",),
    )

    assert f"{sys.executable} -m pytest -q apps/server/tests/adapters/http" in output


def test_main_dry_run_combines_docs_ui_and_hygiene_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("README.md", "apps/ui/package.json", "Makefile"),
    )

    assert "[test-changed] docs-lint: make docs-lint" in output
    assert "[test-changed] ui-typecheck: make ui-typecheck" in output
    assert (
        f"[test-changed] pytest: {sys.executable} -m pytest -q apps/server/tests/hygiene" in output
    )


def test_main_dry_run_runs_ui_unit_tests_for_changed_ui_source_files(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("apps/ui/src/ws_payload_validator.ts",),
    )

    assert "[test-changed] ui-test: make ui-test" in output
    assert "[test-changed] ui-typecheck: make ui-typecheck" in output


def test_main_dry_run_keeps_non_source_ui_changes_on_typecheck_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("apps/ui/package.json",),
    )

    assert "[test-changed] ui-typecheck: make ui-typecheck" in output
    assert "[test-changed] ui-test: make ui-test" not in output


@pytest.mark.parametrize(
    "changed_file,expected_command",
    (
        ("tools/ui/ensure_ui_bootstrap.mjs", "ui-typecheck: make ui-typecheck"),
        (
            "tools/tests/run_ci_with_act.sh",
            "shell-lint: make shell-lint",
        ),
        (".dockerignore", f"pytest: {sys.executable} -m pytest -q apps/server/tests/hygiene"),
        (
            "firmware/esp/src/main.cpp",
            (
                "firmware-native-tests: "
                f"{sys.executable} tools/tests/run_ci_parallel.py --job firmware-native-tests"
            ),
        ),
    ),
)
def test_main_dry_run_reuses_shared_ci_path_rules_for_mapped_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    changed_file: str,
    expected_command: str,
) -> None:
    module = _load_run_changed_module()
    selected_jobs = {
        field.name
        for field in fields(module.workflow_job_selection((changed_file,)))
        if getattr(module.workflow_job_selection((changed_file,)), field.name)
    }
    assert selected_jobs

    output = _run_dry_run(module, monkeypatch, capsys, committed=(changed_file,))

    assert "[test-changed] No mapped checks" not in output
    assert f"[test-changed] {expected_command}" in output


def test_main_dry_run_falls_back_to_make_test_for_unmapped_backend_changes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()

    output = _run_dry_run(
        module,
        monkeypatch,
        capsys,
        committed=("apps/server/vibesensor/_version.py",),
    )

    assert "[test-changed] backend-tests: make test" in output


def test_main_lists_committed_and_worktree_changes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()
    _install_git_state(
        monkeypatch,
        module,
        outputs=_git_outputs(
            committed=("docs/testing.md",),
            staged=("Makefile",),
            unstaged=("CONTRIBUTING.md",),
            untracked=("tools/tests/run_changed.py",),
        ),
    )

    assert module.main(["--dry-run"]) == 0
    output = capsys.readouterr().out

    assert "  - CONTRIBUTING.md" in output
    assert "  - Makefile" in output
    assert "  - docs/testing.md" in output
    assert "  - tools/tests/run_changed.py" in output


def test_main_exits_cleanly_when_merge_base_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_run_changed_module()
    outputs = _git_outputs()
    outputs[("merge-base", "origin/main", "HEAD")] = subprocess.CalledProcessError(
        128,
        ("git", "merge-base", "origin/main", "HEAD"),
    )
    _install_git_state(monkeypatch, module, outputs=outputs)

    with pytest.raises(SystemExit, match="Unable to find a common ancestor"):
        module.main(["--dry-run"])
