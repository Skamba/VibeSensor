"""Import-purity guardrails for the app package and bootstrap module."""

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


def test_importing_app_package_exposes_startup_entrypoints() -> None:
    result = _run_import_probe(
        """
import importlib

module = importlib.import_module("vibesensor.app")
assert module.__name__ == "vibesensor.app"
assert callable(module.create_app)
assert callable(module.create_app_from_env)
assert callable(module.main)
assert not hasattr(module, "app")
        """
    )
    assert result.stdout.strip() == "ok"


def test_importing_bootstrap_does_not_construct_runtime() -> None:
    result = _run_import_probe(
        """
import importlib

bootstrap = importlib.import_module("vibesensor.app.bootstrap")
assert callable(bootstrap.create_app)
assert callable(bootstrap.create_app_from_env)
assert callable(bootstrap.main)
assert not hasattr(bootstrap, "app")
        """
    )
    assert result.stdout.strip() == "ok"


def test_importing_create_app_from_package_is_side_effect_free() -> None:
    result = _run_import_probe(
        """
from vibesensor.app import create_app, create_app_from_env, main

assert callable(create_app)
assert callable(create_app_from_env)
assert callable(main)
        """
    )
    assert result.stdout.strip() == "ok"
