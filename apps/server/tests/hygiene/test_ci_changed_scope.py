"""Guard: changed-file event scope stays aligned with the shared path rules."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests._paths import REPO_ROOT

_CI_PATH_RULES = REPO_ROOT / "tools" / "tests" / "ci_path_rules.py"
_CI_CHANGED_SCOPE = REPO_ROOT / "tools" / "tests" / "ci_changed_scope.py"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"Unable to load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def ci_changed_scope() -> ModuleType:
    _load_module("ci_path_rules", _CI_PATH_RULES)
    return _load_module("ci_changed_scope_local_test", _CI_CHANGED_SCOPE)


def test_pull_request_event_outputs_match_path_rules(
    ci_changed_scope: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "pull_request_event.json"
    payload_path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "base": {"sha": "base-sha"},
                    "head": {"sha": "head-sha"},
                }
            }
        ),
        encoding="utf-8",
    )
    changed_files = ("README.md", "apps/ui/src/main.ts")
    merge_base_calls: list[tuple[str, str]] = []

    def fake_changed_files_for_merge_base(base_sha: str, head_sha: str) -> tuple[str, ...]:
        merge_base_calls.append((base_sha, head_sha))
        return changed_files

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(payload_path))
    monkeypatch.setattr(
        ci_changed_scope,
        "_changed_files_for_merge_base",
        fake_changed_files_for_merge_base,
    )

    assert (
        ci_changed_scope._selection_for_github_event()
        == ci_changed_scope.workflow_job_selection(changed_files).github_outputs()
    )
    assert merge_base_calls == [("base-sha", "head-sha")]
