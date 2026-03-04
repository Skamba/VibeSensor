from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from _paths import REPO_ROOT


def _run_check_script(cwd: Path) -> subprocess.CompletedProcess[str]:
    repo_root = REPO_ROOT
    script = repo_root / "tools" / "dev" / "check_no_pycache.py"
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_no_tracked_pycache_or_pyc() -> None:
    completed = _run_check_script(REPO_ROOT)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_no_tracked_pycache_or_pyc_without_git_metadata(tmp_path: Path) -> None:
    completed = _run_check_script(tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_detects_pycache_or_pyc_without_git_metadata(tmp_path: Path) -> None:
    pycache_file = tmp_path / "pkg" / "__pycache__" / "module.cpython-312.pyc"
    pycache_file.parent.mkdir(parents=True)
    pycache_file.write_bytes(b"cache")

    completed = _run_check_script(tmp_path)
    assert completed.returncode == 1
    assert "pkg/__pycache__/module.cpython-312.pyc" in completed.stdout
