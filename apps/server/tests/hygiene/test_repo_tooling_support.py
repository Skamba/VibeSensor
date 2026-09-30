"""Guard shared repo-tooling helper behavior."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

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


def test_ensure_repo_python_version_accepts_configured_major_minor(tmp_path: Path) -> None:
    module = _load_repo_tooling_support_module()
    (tmp_path / ".python-version").write_text("3.13.5\n", encoding="utf-8")

    module.ensure_repo_python_version(
        tmp_path,
        script_path=tmp_path / "tools" / "tests" / "run_e2e_parallel.py",
        actual_version_info=(3, 13, 13),
        actual_version="3.13.13",
        executable="/repo/.venv/bin/python",
    )
    assert (tmp_path / ".python-version").read_text(encoding="utf-8") == "3.13.5\n"


def test_ensure_repo_python_version_rejects_wrong_major_minor(tmp_path: Path) -> None:
    module = _load_repo_tooling_support_module()
    (tmp_path / ".python-version").write_text("3.13.5\n", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        module.ensure_repo_python_version(
            tmp_path,
            script_path=tmp_path / "tools" / "tests" / "run_e2e_parallel.py",
            actual_version_info=(3, 12, 10),
            actual_version="3.12.10",
            executable="/usr/bin/python3",
        )

    message = str(exc_info.value)
    assert "tools/tests/run_e2e_parallel.py must run with Python 3.13.x" in message
    assert "current interpreter is Python 3.12.10 at /usr/bin/python3" in message
    assert "Run `make setup`" in message
    assert ".venv/bin/python tools/tests/run_e2e_parallel.py" in message
