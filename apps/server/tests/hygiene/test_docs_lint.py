"""Smoke coverage for docs lint policy checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_DOCS_LINT = REPO_ROOT / "tools" / "dev" / "docs_lint.py"


def _load_docs_lint_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docs_lint_local_for_tests", _DOCS_LINT)
    assert spec is not None and spec.loader is not None, f"Unable to load {_DOCS_LINT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_docs_lint_main_passes_current_repo() -> None:
    module = _load_docs_lint_module()

    assert module.main() == 0


def test_docs_lint_rejects_stale_documented_make_target(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    (tmp_path / "Makefile").write_text(
        ".PHONY: lint\nlint:\n\truff check .\n",
        encoding="utf-8",
    )
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "testing.md").write_text(
        "Good: `make lint`.\nBad: `make removed-target`.\n",
        encoding="utf-8",
    )

    assert module._check_make_command_targets(["docs/testing.md"], tmp_path) == [
        "docs/testing.md: documented make target does not exist: removed-target"
    ]
