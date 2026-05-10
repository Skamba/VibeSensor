"""Consolidated pytest entrypoints for backend static guards."""

from __future__ import annotations

from types import ModuleType

from _paths import REPO_ROOT
from test_support.check_hygiene_loader import load_tool_package_module

_BACKEND_STATIC_GUARDS = REPO_ROOT / "tools" / "dev" / "static_guards" / "checks.py"


def _load_verify_backend_static_guards_module() -> ModuleType:
    return load_tool_package_module(
        module_name="verify_backend_static_guards_test_entrypoints",
        module_path=_BACKEND_STATIC_GUARDS,
        package_dir=_BACKEND_STATIC_GUARDS.parent,
    )


def test_verify_backend_static_guards_main_passes() -> None:
    guards_module = _load_verify_backend_static_guards_module()
    assert guards_module.main() == 0
