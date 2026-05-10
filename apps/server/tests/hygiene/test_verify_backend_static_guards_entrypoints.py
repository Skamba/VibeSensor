"""Consolidated pytest entrypoints for backend static guards."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from _paths import REPO_ROOT

_BACKEND_STATIC_GUARDS = REPO_ROOT / "tools" / "dev" / "static_guards" / "checks.py"


def _load_verify_backend_static_guards_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_backend_static_guards_test_entrypoints",
        _BACKEND_STATIC_GUARDS,
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_BACKEND_STATIC_GUARDS}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_verify_backend_static_guards_main_passes() -> None:
    guards_module = _load_verify_backend_static_guards_module()
    assert guards_module.main() == 0
