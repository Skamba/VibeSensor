"""Guard shared repo-tooling helper behavior."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_REPO_TOOLING_SUPPORT = REPO_ROOT / "tools" / "repo_tooling_support.py"


def _load_repo_tooling_support_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "repo_tooling_support_test_module",
        _REPO_TOOLING_SUPPORT,
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_REPO_TOOLING_SUPPORT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalize_shell_command_preserves_chains_and_normalizes_command_token() -> None:
    module = _load_repo_tooling_support_module()

    def _normalize_python(token: str) -> str:
        if Path(token.strip("\"'")).name.startswith("python"):
            return "python"
        return token

    assert (
        module.normalize_shell_command(
            "env FOO=bar /opt/bin/python3 -m pytest && echo done",
            command_token_normalizer=_normalize_python,
        )
        == "env FOO=bar python -m pytest && echo done"
    )


def test_tracked_files_prefers_git_listing(monkeypatch) -> None:
    module = _load_repo_tooling_support_module()
    repo_root = Path("/tmp/nonexistent")

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert args == (
            [
                "git",
                "-C",
                str(repo_root),
                "ls-files",
                "--cached",
            ],
        )
        assert kwargs["check"] is True
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        return subprocess.CompletedProcess(
            args[0],
            0,
            stdout="tools/dev/check_hygiene.py\ntools/tests/ci_workflow_manifest.py\n",
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    assert module.tracked_files(repo_root, excluded_dirs=()) == [
        "tools/dev/check_hygiene.py",
        "tools/tests/ci_workflow_manifest.py",
    ]
