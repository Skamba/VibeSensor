"""Helpers for loading tools/dev/check_hygiene.py in hygiene tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_CHECK_HYGIENE = REPO_ROOT / "tools" / "dev" / "hygiene" / "checks.py"


def load_tool_package_module(
    *,
    module_name: str,
    module_path: Path,
    package_dir: Path,
) -> ModuleType:
    package_name = f"{module_name}_package"
    package = ModuleType(package_name)
    package.__package__ = package_name
    package.__path__ = [str(package_dir)]  # type: ignore[attr-defined]
    sys.modules[package_name] = package

    qualified_name = f"{package_name}.{module_path.stem}"
    spec = importlib.util.spec_from_file_location(qualified_name, module_path)
    assert spec is not None and spec.loader is not None, f"Unable to load {module_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified_name] = module
    spec.loader.exec_module(module)
    return module


def load_check_hygiene_module(
    module_name: str = "check_hygiene_local_test",
) -> ModuleType:
    return load_tool_package_module(
        module_name=module_name,
        module_path=_CHECK_HYGIENE,
        package_dir=_CHECK_HYGIENE.parent,
    )
