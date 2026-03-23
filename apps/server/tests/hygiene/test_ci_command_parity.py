"""Guard: local CI-parallel runner commands stay aligned with ci.yml."""

from __future__ import annotations

import importlib.util
import sys

from tests._paths import REPO_ROOT

_CHECK_HYGIENE = REPO_ROOT / "tools" / "dev" / "check_hygiene.py"


def _load_check_hygiene_module():
    spec = importlib.util.spec_from_file_location("check_hygiene_local", _CHECK_HYGIENE)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CHECK_HYGIENE}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_local_runner_commands_match_ci_yml() -> None:
    module = _load_check_hygiene_module()
    assert module.check_ci_command_sync() == []
