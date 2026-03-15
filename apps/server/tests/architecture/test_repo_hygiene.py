from __future__ import annotations

import subprocess
import sys

from _paths import REPO_ROOT


def test_hygiene_checks_pass() -> None:
    script = REPO_ROOT / "tools" / "dev" / "check_hygiene.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
