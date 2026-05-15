"""Smoke coverage for the changed-file local runner."""

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


def test_main_dry_run_smoke_maps_representative_changed_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_run_changed_module()
    _install_git_state(
        monkeypatch,
        module,
        outputs=_git_outputs(
            committed=(
                "README.md",
                "apps/ui/src/ws_payload_validator.ts",
                "tools/tests/run_changed.py",
                "apps/server/vibesensor/shared/boundaries/summary_fields/finding.py",
            ),
        ),
    )

    assert module.main(["--dry-run"]) == 0
    output = capsys.readouterr().out

    assert "[test-changed] docs-lint:" in output
    assert "[test-changed] ui-test:" in output
    assert "[test-changed] ui-typecheck:" in output
    assert "[test-changed] pytest:" in output
    assert "Changed files vs origin/main:" in output
    assert "apps/ui/src/ws_payload_validator.ts" in output
    assert "apps/server/tests/hygiene" in output
    assert "apps/server/tests/shared" in output


def test_changed_files_combines_committed_staged_unstaged_and_untracked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_run_changed_module()
    _install_git_state(
        monkeypatch,
        module,
        outputs=_git_outputs(
            committed=("README.md",),
            staged=("apps/ui/src/main.ts",),
            unstaged=("apps/server/tests/hygiene/test_run_changed.py",),
            untracked=("tools/dev/new_helper.py",),
        ),
    )

    assert module._changed_files("origin/main") == (
        "README.md",
        "apps/server/tests/hygiene/test_run_changed.py",
        "apps/ui/src/main.ts",
        "tools/dev/new_helper.py",
    )


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
