from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_no_tracked_pycache_or_pyc() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "tools" / "dev" / "check_no_pycache.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
