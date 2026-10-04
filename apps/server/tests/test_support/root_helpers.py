"""Load the root-side helper scripts (``apps/server/root-helpers/``) in tests.

On a device these run as root from the root-owned copy in
``/usr/local/lib/vibesensor``; tests load them straight from the source tree.
"""

from __future__ import annotations

import importlib.util
import sys
from types import ModuleType

from _paths import SERVER_ROOT

__all__ = ["ROOT_HELPERS_DIR", "load_root_helper"]

ROOT_HELPERS_DIR = SERVER_ROOT / "root-helpers"


def load_root_helper(name: str) -> ModuleType:
    """Import ``root-helpers/<name>`` as a module (without writing bytecode next to it)."""

    path = ROOT_HELPERS_DIR / name
    spec = importlib.util.spec_from_file_location(f"root_helper_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Dataclasses resolve their module through sys.modules while the class body runs.
    sys.modules[spec.name] = module
    dont_write_bytecode, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = dont_write_bytecode
    return module
