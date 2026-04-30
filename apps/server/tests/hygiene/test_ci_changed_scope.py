"""Guard: changed-file event scope stays aligned with the shared path rules."""

from __future__ import annotations

import importlib.util
import json
import re
import shlex
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from tests._paths import REPO_ROOT

_CI_PATH_RULES = REPO_ROOT / "tools" / "tests" / "ci_path_rules.py"
_CI_CHANGED_SCOPE = REPO_ROOT / "tools" / "tests" / "ci_changed_scope.py"
_ACT_EVENT = REPO_ROOT / "tools" / "tests" / "act_event.py"
_CI_MANIFEST = REPO_ROOT / "tools" / "tests" / "ci_workflow_manifest.py"
_CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_COMMAND_EXAMPLE_PATHS = (
    REPO_ROOT / "tools" / "tests" / "run_ci_with_act.sh",
    REPO_ROOT / "docs" / "testing.md",
    REPO_ROOT / ".github" / "copilot-instructions.md",
    REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "ai_change_request.md",
)


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"Unable to load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _command_snippets(text: str, command_name: str) -> list[str]:
    snippets: list[str] = []
    command_pattern = re.escape(command_name)
    for line in text.splitlines():
        if command_name not in line:
            continue
        snippets.extend(re.findall(rf"`([^`]*{command_pattern}[^`]*)`", line))
        if snippets and snippets[-1] in line:
            continue
        stripped = re.sub(r"^\s*(?:#\s*)?", "", line).strip()
        snippets.append(stripped)
    return snippets


def _job_args_from_snippets(snippets: list[str], flags: set[str]) -> list[str]:
    job_args: list[str] = []
    for snippet in snippets:
        command_text = snippet.split("#", 1)[0].strip()
        if not command_text:
            continue
        tokens = shlex.split(command_text)
        for index, token in enumerate(tokens):
            if token in flags and index + 1 < len(tokens):
                job_args.append(tokens[index + 1])
            for flag in flags:
                if token.startswith(f"{flag}="):
                    job_args.append(token.split("=", 1)[1])
    return job_args


def _documented_job_args(command_name: str, flags: set[str]) -> set[str]:
    job_args: set[str] = set()
    for path in _COMMAND_EXAMPLE_PATHS:
        job_args.update(
            _job_args_from_snippets(
                _command_snippets(path.read_text(encoding="utf-8"), command_name),
                flags,
            )
        )
    return job_args


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


def test_force_full_stack_env_bypasses_changed_file_scope(
    ci_changed_scope: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload_path = tmp_path / "pull_request_event.json"
    payload_path.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("VIBESENSOR_CI_FORCE_FULL_STACK", "1")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(payload_path))
    monkeypatch.setattr(
        ci_changed_scope,
        "_changed_files_for_merge_base",
        lambda _base_sha, _head_sha: (_ for _ in ()).throw(
            AssertionError("forced full-stack should not inspect changed files")
        ),
    )

    assert (
        ci_changed_scope._selection_for_github_event()
        == ci_changed_scope.workflow_job_selection(()).github_outputs()
    )


def test_act_pull_request_event_helper_writes_non_empty_changed_scope_shas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _load_module("ci_path_rules", _CI_PATH_RULES)
    ci_changed_scope = _load_module("ci_changed_scope_for_act_event_test", _CI_CHANGED_SCOPE)
    module = _load_module("act_event_local_test", _ACT_EVENT)

    def fake_run(command, **_kwargs):
        assert command[:3] == ["git", "rev-parse", "--verify"]
        ref = command[3]
        return module.subprocess.CompletedProcess(
            command,
            0 if ref == "origin/main" else 1,
        )

    def fake_check_output(command, **_kwargs):
        assert command[0] == "git"
        match tuple(command[1:]):
            case ("merge-base", "origin/main", "HEAD"):
                return "base-sha"
            case ("rev-parse", "--abbrev-ref", "HEAD"):
                return "issue-branch"
            case ("rev-parse", "HEAD"):
                return "head-sha"
        raise AssertionError(f"unexpected git command: {command}")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module.subprocess, "check_output", fake_check_output)

    output_path = tmp_path / "act-event.json"
    assert module.main(["--output", str(output_path)]) == 0

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    pull_request = payload["pull_request"]
    assert pull_request["base"] == {"ref": "origin/main", "sha": "base-sha"}
    assert pull_request["head"] == {"ref": "issue-branch", "sha": "head-sha"}

    merge_base_calls: list[tuple[str, str]] = []

    def fake_changed_files_for_merge_base(base_sha: str, head_sha: str) -> tuple[str, ...]:
        merge_base_calls.append((base_sha, head_sha))
        return ("tools/tests/run_ci_with_act.sh",)

    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(output_path))
    monkeypatch.setattr(
        ci_changed_scope,
        "_changed_files_for_merge_base",
        fake_changed_files_for_merge_base,
    )

    ci_changed_scope._selection_for_github_event()
    assert merge_base_calls == [("base-sha", "head-sha")]


def test_act_wrapper_distinguishes_changed_scope_and_full_stack_modes() -> None:
    wrapper_text = (REPO_ROOT / "tools" / "tests" / "run_ci_with_act.sh").read_text(
        encoding="utf-8"
    )
    docs_text = (REPO_ROOT / "docs" / "testing.md").read_text(encoding="utf-8")
    ai_guidance = (REPO_ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")

    assert "run changed-scope CI jobs" in wrapper_text
    assert "--full-stack # force all CI jobs through ci-scope" in wrapper_text
    assert "VIBESENSOR_CI_FORCE_FULL_STACK=1" in wrapper_text
    assert "changed-scope ACT run" in docs_text
    assert "forced full-stack ACT run" in docs_text
    assert "--full-stack" in ai_guidance


def test_documented_act_job_examples_use_raw_workflow_job_ids() -> None:
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    raw_workflow_job_ids = set(workflow["jobs"])

    act_job_examples = _documented_job_args("run_ci_with_act.sh", {"-j"})

    assert "backend-tests" in act_job_examples
    assert "backend-tests-1" not in act_job_examples
    assert not sorted(act_job_examples - raw_workflow_job_ids)


def test_documented_local_runner_job_examples_use_logical_job_ids() -> None:
    manifest = _load_module("ci_workflow_manifest_for_command_docs_test", _CI_MANIFEST)
    local_logical_job_ids = set(manifest.ci_workflow_jobs())

    local_runner_examples = _documented_job_args("run_ci_parallel.py", {"--job"})

    assert "backend-tests-1" in local_runner_examples
    assert not sorted(local_runner_examples - local_logical_job_ids)
