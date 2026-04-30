"""Guard docs lint command-reference checks."""

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


def test_make_command_target_lint_rejects_stale_documented_targets(
    tmp_path: Path,
) -> None:
    module = _load_docs_lint_module()
    (tmp_path / "Makefile").write_text(
        ".PHONY: coverage lint\ncoverage:\n\tpytest\nlint:\n\truff check .\n",
        encoding="utf-8",
    )
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    docs_path = docs_dir / "testing.md"
    docs_path.write_text(
        "```bash\nmake coverage\nmake coverage-html\n```\nInline command: `make lint`.\n",
        encoding="utf-8",
    )

    assert module._check_make_command_targets(["docs/testing.md"], tmp_path) == [
        "docs/testing.md: documented make target does not exist: coverage-html"
    ]


def test_docs_lint_rejects_removed_processing_path_references(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    docs_path = docs_dir / "intake_buffering.md"
    docs_path.write_text(
        "Old path: `infra/processing/fft.py`.\n",
        encoding="utf-8",
    )

    original_repo_root = module.REPO_ROOT
    module.REPO_ROOT = tmp_path
    try:
        assert module._check_stale_repo_path_references(["docs/intake_buffering.md"]) == [
            "docs/intake_buffering.md: stale repo path reference: "
            "infra/processing/fft.py "
            "(use apps/server/vibesensor/shared/fft_analysis.py)"
        ]
    finally:
        module.REPO_ROOT = original_repo_root
