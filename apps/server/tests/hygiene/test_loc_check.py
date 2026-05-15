"""Smoke coverage for maintainability size checks."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_LOC_CHECK = REPO_ROOT / "tools" / "dev" / "loc_check.py"


def _load_loc_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("loc_check_test_module", _LOC_CHECK)
    assert spec is not None and spec.loader is not None, f"Unable to load {_LOC_CHECK}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _prepare_fixture_repo(module: ModuleType, tmp_path: Path, monkeypatch) -> Path:
    repo_root = tmp_path / "repo"
    (repo_root / "tools" / "dev").mkdir(parents=True)
    (repo_root / "src").mkdir()
    monkeypatch.setattr(module, "__file__", str(repo_root / "tools" / "dev" / "loc_check.py"))

    def _raise_git_failure(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(128, args[0])

    monkeypatch.setattr(module._repo_tooling_support.subprocess, "run", _raise_git_failure)
    return repo_root


def test_loc_check_reports_file_and_function_size_policy_violations(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = _load_loc_check_module()
    repo_root = _prepare_fixture_repo(module, tmp_path, monkeypatch)
    (repo_root / "src" / "main.py").write_text(
        "def too_large():\n    one = 1\n    two = 2\n    return one + two\n",
        encoding="utf-8",
    )

    assert module.main(["--file-fail-over", "2", "--function-fail-over", "2"]) == 1

    stdout = capsys.readouterr().out
    assert "file exceeds threshold" in stdout
    assert "function exceeds threshold" in stdout
    assert "2 lines" in stdout
    assert "src/main.py::too_large" in stdout
