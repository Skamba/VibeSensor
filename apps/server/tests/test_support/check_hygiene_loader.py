"""Helpers for loading tools/dev/check_hygiene.py in hygiene tests."""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from tests._paths import REPO_ROOT

_CHECK_HYGIENE = REPO_ROOT / "tools" / "dev" / "check_hygiene.py"


def load_check_hygiene_module(
    module_name: str = "check_hygiene_local_test",
) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, _CHECK_HYGIENE)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CHECK_HYGIENE}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module
