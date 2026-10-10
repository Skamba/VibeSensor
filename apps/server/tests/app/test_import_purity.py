"""Import-purity smoke coverage for app startup entrypoints."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]


def _run_import_probe(import_code: str) -> subprocess.CompletedProcess[str]:
    script = "\n".join(
        [
            "import logging.handlers",
            "import sqlite3",
            "from pathlib import Path",
            "",
            "def _boom_connect(*args, **kwargs):",
            '    raise AssertionError("sqlite-connect-called")',
            "",
            "class _BoomHandler:",
            "    def __init__(self, *args, **kwargs):",
            '        raise AssertionError("file-logging-called")',
            "",
            "_orig_exists = Path.exists",
            "",
            "def _guard_exists(self):",
            '    if self.name == "index.html":',
            '        raise AssertionError("static-validation-called")',
            "    return _orig_exists(self)",
            "",
            "sqlite3.connect = _boom_connect",
            "logging.handlers.RotatingFileHandler = _BoomHandler",
            "Path.exists = _guard_exists",
            "",
            textwrap.dedent(import_code).strip(),
            "",
            'print("ok")',
        ]
    )
    env = os.environ.copy()
    env.pop("VIBESENSOR_DISABLE_AUTO_APP", None)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )


def test_importing_startup_entrypoints_is_side_effect_free() -> None:
    result = _run_import_probe(
        """
import importlib

package = importlib.import_module("vibesensor.app")
bootstrap = importlib.import_module("vibesensor.app.bootstrap")
serve = importlib.import_module("vibesensor.app.serve")
from vibesensor.app.bootstrap import create_app, create_app_from_env
from vibesensor.app.serve import main

_ = (package, bootstrap, serve, create_app, create_app_from_env, main)
        """
    )
    assert result.stdout.strip() == "ok"


def test_server_supervisor_leaves_the_app_to_the_worker() -> None:
    """The ``vibesensor-server`` process only supervises the Granian worker.

    Granian forks the worker, so anything the supervisor imports stays resident
    in it as a second copy once the worker touches those pages (~40 MB on the Pi).
    """
    result = _run_import_probe(
        """
import sys
from vibesensor.app.serve import main

app_modules = ("vibesensor.app.bootstrap", "vibesensor.app.composition", "numpy", "fastapi")
print(sorted(m for m in app_modules if m in sys.modules))
        """
    )
    assert result.stdout.strip().splitlines() == ["[]", "ok"]


_SLOW_IMPORTS = (
    "scipy.signal",
    "scipy.fft",
    "pyfftw",
    "httpx",
    "reportlab",
    "vibesensor.settings.car_library",
)
"""Modules that cost seconds to import on the Pi and are only needed later.

FFT (pyfftw pulls in scipy.fft) waits for the first sensor data, httpx for an
update or firmware download, reportlab for a PDF, the car library for the car
picker. The server must not load them before it answers ``/api/health``.
"""


def test_server_start_leaves_slow_imports_for_first_use(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        "logging:\n"
        f"  history_db_path: {tmp_path / 'history.db'}\n"
        f"  app_log_path: {tmp_path / 'app.log'}\n",
        encoding="utf-8",
    )
    script = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from vibesensor.app.bootstrap import create_app

        create_app(Path({str(config)!r}))
        print(sorted(m for m in {_SLOW_IMPORTS!r} if m in sys.modules))
        """
    )
    env = {**os.environ, "VIBESENSOR_SERVE_STATIC": "0"}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=SERVER_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip().splitlines()[-1] == "[]"
