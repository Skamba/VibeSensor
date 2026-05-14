#!/usr/bin/env python3
"""Shared adapter over the authoritative CI workflow job surface."""

from __future__ import annotations

import importlib.util
import re
import shlex
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_repo_tooling_support():
    helper_path = ROOT / "tools" / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_repo_tooling_support = _load_repo_tooling_support()
_CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
_INSTALL_STEP_NAMES = frozenset(
    {
        "Configure backend virtualenv",
        "Install dependencies",
        "Install ShellCheck",
        "Install PlatformIO dependencies",
        "Install UI dependencies",
        "Prepare retry helper",
        "Report backend virtualenv cache hit",
        "Report backend virtualenv cache miss",
    }
)
_CI_LITE_EXCLUDED_JOBS = frozenset({"e2e"})
_CI_FAST_EXCLUDED_JOBS = frozenset(
    {
        "backend-tooling-tests",
        "e2e",
        "firmware-native-tests",
        "release-smoke",
        "ui-smoke",
        "ui-unit",
    }
)
_CI_FAST_EXCLUDED_PREFIXES = ("backend-tests-",)
_WORKFLOW_ONLY_EXCLUDED_JOBS = frozenset({"ci-scope", "ui-build-artifact"})
_PYTHON_PATH_TOKENS = frozenset(
    {
        "${{ steps.setup-backend.outputs.python-path }}",
        "${{ steps.setup-python.outputs.python-path }}",
    }
)
_MATRIX_LOGICAL_JOB_NAME_KEY = "logical_job_name"
_ACTION_INPUT_EQ_RE = re.compile(
    r"^\${{\s*inputs\.([A-Za-z0-9_-]+)\s*==\s*'([^']+)'\s*}}$"
)
_MATRIX_TOKEN_RE = re.compile(r"\${{\s*matrix\.([A-Za-z0-9_-]+)\s*}}")
_JOB_WORKSPACE_WRITE_SETS = {
    "backend-contract-drift": ("ui-generated-contracts",),
    "frontend-typecheck": ("ui-generated-contracts",),
    "ui-unit": ("ui-test-results",),
    "ui-smoke": ("ui-test-results",),
    "release-smoke": (
        "ui-generated-contracts",
        "ui-dist",
        "server-static",
        "server-dist",
        "release-smoke-artifacts",
    ),
}
_JOB_HOST_TOOLS = {
    "shell-lint": ("shellcheck",),
}


@dataclass(frozen=True)
class RunnableCommandSpec:
    label: str
    command: str


@dataclass(frozen=True)
class CiWorkflowStep:
    name: str
    commands: tuple[str, ...]


@dataclass(frozen=True)
class CiWorkflowSkippedAction:
    name: str
    uses: str
    local_substitute: str | None = None


@dataclass(frozen=True)
class CiWorkflowJob:
    job_name: str
    steps: tuple[CiWorkflowStep, ...]
    needs: tuple[str, ...] = ()
    workflow_only_needs: tuple[str, ...] = ()
    skipped_actions: tuple[CiWorkflowSkippedAction, ...] = ()
    workspace_write_sets: tuple[str, ...] = ()
    host_tools: tuple[str, ...] = ()

    def commands_named(self, names: Collection[str]) -> tuple[str, ...]:
        commands: list[str] = []
        for step in self.steps:
            if step.name in names:
                commands.extend(step.commands)
        return tuple(commands)

    @property
    def requires_platformio(self) -> bool:
        return any(
            step.name == "Install PlatformIO dependencies" for step in self.steps
        )

    def local_runnable_steps(self, python_cmd: str) -> tuple[RunnableCommandSpec, ...]:
        specs: list[RunnableCommandSpec] = []
        for step in self.steps:
            if step.name in _INSTALL_STEP_NAMES:
                continue
            for command in step.commands:
                local_command = _local_command_substitute(
                    self.job_name, step.name, command
                )
                if local_command is None:
                    continue
                specs.append(
                    RunnableCommandSpec(
                        label=step.name,
                        command=_replace_python_placeholders(local_command, python_cmd),
                    )
                )
        return tuple(specs)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _substitute_matrix_values(
    value: object, matrix_values: Mapping[str, str]
) -> object:
    if isinstance(value, str):
        return _MATRIX_TOKEN_RE.sub(
            lambda match: matrix_values.get(match.group(1), match.group(0)),
            value,
        )
    if isinstance(value, list):
        return [_substitute_matrix_values(item, matrix_values) for item in value]
    if isinstance(value, Mapping):
        return {
            key: _substitute_matrix_values(item, matrix_values)
            for key, item in value.items()
        }
    return value


def _normalize_tokenized_command(tokens: list[str]) -> str:
    return _repo_tooling_support.normalize_tokenized_command(tokens)


def _normalize_shell_command(command: str) -> str:
    return _repo_tooling_support.normalize_shell_command(command)


def _normalize_env(env: Mapping[str, object] | None) -> str:
    if not env:
        return ""
    parts = [f"{key}={shlex.quote(str(env[key]))}" for key in sorted(env)]
    return f"env {' '.join(parts)} "


def _normalize_ci_step_commands(step: Mapping[str, object]) -> tuple[str, ...]:
    run = step.get("run")
    if not isinstance(run, str):
        return ()
    working_directory = step.get("working-directory")
    cwd_prefix = ""
    if isinstance(working_directory, str) and working_directory:
        cwd_prefix = f"cd {working_directory} && "
    env_prefix = _normalize_env(
        step.get("env") if isinstance(step.get("env"), Mapping) else None
    )
    lines = [raw_line.strip() for raw_line in run.splitlines() if raw_line.strip()]
    line_cwd_prefix = ""
    if lines and lines[0].startswith("cd ") and "&&" not in lines[0] and len(lines) > 1:
        line_cwd_prefix = f"{_normalize_shell_command(lines[0])} && "
        lines = lines[1:]

    commands: list[str] = []
    for line in lines:
        commands.append(
            f"{cwd_prefix}{line_cwd_prefix}{env_prefix}{_normalize_shell_command(line)}"
        )
    return tuple(commands)


def _normalized_needs(raw_needs: object) -> tuple[str, ...]:
    needs = _raw_needs(raw_needs)
    return tuple(
        need
        for need in needs
        if need != "ci-scope" and need not in _WORKFLOW_ONLY_EXCLUDED_JOBS
    )


def _workflow_only_needs(raw_needs: object) -> tuple[str, ...]:
    return tuple(
        need
        for need in _raw_needs(raw_needs)
        if need != "ci-scope" and need in _WORKFLOW_ONLY_EXCLUDED_JOBS
    )


def _raw_needs(raw_needs: object) -> tuple[str, ...]:
    if isinstance(raw_needs, str):
        return (raw_needs,)
    if isinstance(raw_needs, list):
        return tuple(need for need in raw_needs if isinstance(need, str))
    return ()


def _local_action_file(action_ref: str) -> Path | None:
    if not action_ref.startswith("./"):
        return None
    action_file = ROOT / action_ref.removeprefix("./") / "action.yml"
    return action_file if action_file.exists() else None


def _resolved_action_inputs(
    action: Mapping[str, object], raw_with: Mapping[str, object] | None
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    raw_inputs = action.get("inputs")
    if isinstance(raw_inputs, Mapping):
        for input_name, input_spec in raw_inputs.items():
            if not isinstance(input_name, str):
                continue
            default = ""
            if isinstance(input_spec, Mapping):
                raw_default = input_spec.get("default")
                if raw_default is not None:
                    default = str(raw_default)
            resolved[input_name] = default
    if raw_with is not None:
        for input_name, value in raw_with.items():
            if isinstance(input_name, str) and value is not None:
                resolved[input_name] = str(value)
    return resolved


def _action_step_enabled(step: Mapping[str, object], inputs: Mapping[str, str]) -> bool:
    raw_if = step.get("if")
    if not isinstance(raw_if, str):
        return True
    match = _ACTION_INPUT_EQ_RE.fullmatch(raw_if.strip())
    if match is None:
        return True
    input_name, expected_value = match.groups()
    return inputs.get(input_name, "") == expected_value


def _normalized_ci_steps(raw_step: Mapping[str, object]) -> tuple[CiWorkflowStep, ...]:
    run = raw_step.get("run")
    if isinstance(run, str):
        return (
            CiWorkflowStep(
                name=str(raw_step.get("name", "")),
                commands=_normalize_ci_step_commands(raw_step),
            ),
        )

    uses = raw_step.get("uses")
    if not isinstance(uses, str):
        return ()
    action_file = _local_action_file(uses)
    if action_file is None:
        return ()
    action = _load_yaml_mapping(action_file)
    runs = action.get("runs")
    if not isinstance(runs, Mapping):
        return ()
    raw_steps = runs.get("steps")
    if not isinstance(raw_steps, list):
        return ()
    raw_with = raw_step.get("with")
    action_inputs = _resolved_action_inputs(
        action, raw_with if isinstance(raw_with, Mapping) else None
    )
    normalized_steps: list[CiWorkflowStep] = []
    for action_step in raw_steps:
        if not isinstance(action_step, Mapping):
            continue
        if not _action_step_enabled(action_step, action_inputs):
            continue
        normalized_steps.extend(_normalized_ci_steps(action_step))
    return tuple(normalized_steps)


def _local_action_skipped_actions(
    action_ref: str, raw_with: Mapping[str, object] | None
) -> tuple[CiWorkflowSkippedAction, ...]:
    action_file = _local_action_file(action_ref)
    if action_file is None:
        return ()
    action = _load_yaml_mapping(action_file)
    runs = action.get("runs")
    if not isinstance(runs, Mapping):
        return ()
    raw_steps = runs.get("steps")
    if not isinstance(raw_steps, list):
        return ()
    action_inputs = _resolved_action_inputs(action, raw_with)
    skipped: list[CiWorkflowSkippedAction] = []
    for action_step in raw_steps:
        if not isinstance(action_step, Mapping):
            continue
        if not _action_step_enabled(action_step, action_inputs):
            continue
        skipped.extend(_skipped_ci_actions(action_step))
    return tuple(skipped)


def _skipped_ci_actions(
    raw_step: Mapping[str, object],
) -> tuple[CiWorkflowSkippedAction, ...]:
    uses = raw_step.get("uses")
    if not isinstance(uses, str):
        return ()
    raw_with = raw_step.get("with")
    with_mapping = raw_with if isinstance(raw_with, Mapping) else None
    if _local_action_file(uses) is not None:
        return _local_action_skipped_actions(uses, with_mapping)
    return (
        CiWorkflowSkippedAction(
            name=str(raw_step.get("name", "")),
            uses=uses,
        ),
    )


def _local_action_substitute(job_name: str, step_name: str, uses: str) -> str | None:
    if uses.startswith("actions/checkout@"):
        return "local runner uses the current checked-out workspace"
    if job_name == "release-smoke" and uses.startswith("actions/download-artifact@"):
        return "local release-smoke builds UI static directly by running run_release_smoke.py without --skip-ui-build"
    if uses.startswith("actions/upload-artifact@"):
        return "local runner writes job logs under artifacts/ai/logs/ci_local instead of uploading artifacts"
    if uses.startswith("actions/cache@"):
        return "local runner uses the existing workspace/cache state; cache restore/save is CI-only"
    if uses.startswith("actions/setup-node@"):
        return "local runner relies on the configured local Node runtime and UI bootstrap helper"
    if uses.startswith("actions/setup-python@"):
        return "local runner uses the current Python executable and replaces workflow python-path placeholders"
    return None


def _local_command_substitute(
    job_name: str, step_name: str, command: str
) -> str | None:
    if job_name == "release-smoke":
        if step_name == "Restore release-smoke UI static artifact":
            return None
        if step_name == "Release smoke validation":
            return command.replace(" --skip-ui-build", "")
    return command


def _replace_python_placeholders(command: str, python_cmd: str) -> str:
    tokens = shlex.split(command)
    replaced: list[str] = []
    for token in tokens:
        if token in _PYTHON_PATH_TOKENS:
            replaced.append(python_cmd)
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            if value in _PYTHON_PATH_TOKENS:
                replaced.append(f"{key}={python_cmd}")
                continue
        replaced.append(token)
    return _normalize_shell_command(" ".join(shlex.quote(token) for token in replaced))


def _expanded_job_variants(
    job_name: str, job_body: Mapping[str, object]
) -> tuple[tuple[str, Mapping[str, object]], ...]:
    strategy = job_body.get("strategy")
    if not isinstance(strategy, Mapping):
        return ((job_name, job_body),)
    matrix = strategy.get("matrix")
    if not isinstance(matrix, Mapping):
        return ((job_name, job_body),)
    raw_include = matrix.get("include")
    if not isinstance(raw_include, list):
        return ((job_name, job_body),)

    expanded: list[tuple[str, Mapping[str, object]]] = []
    for index, raw_entry in enumerate(raw_include, start=1):
        if not isinstance(raw_entry, Mapping):
            continue
        matrix_values = {
            key: str(value)
            for key, value in raw_entry.items()
            if isinstance(key, str) and value is not None
        }
        logical_job_name = matrix_values.get(
            _MATRIX_LOGICAL_JOB_NAME_KEY, f"{job_name}[{index}]"
        )
        substituted_job = _substitute_matrix_values(job_body, matrix_values)
        if isinstance(substituted_job, Mapping):
            expanded.append((logical_job_name, substituted_job))
    return tuple(expanded) or ((job_name, job_body),)


def ci_workflow_jobs() -> dict[str, CiWorkflowJob]:
    workflow = _load_yaml_mapping(_CI_WORKFLOW)
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        return {}

    result: dict[str, CiWorkflowJob] = {}
    for job_name, job_body in jobs.items():
        if not isinstance(job_name, str) or not isinstance(job_body, Mapping):
            continue
        if job_name in _WORKFLOW_ONLY_EXCLUDED_JOBS:
            continue
        for expanded_job_name, expanded_job_body in _expanded_job_variants(
            job_name, job_body
        ):
            raw_steps = expanded_job_body.get("steps")
            if not isinstance(raw_steps, list):
                continue
            normalized_steps: list[CiWorkflowStep] = []
            skipped_actions: list[CiWorkflowSkippedAction] = []
            for raw_step in raw_steps:
                if not isinstance(raw_step, Mapping):
                    continue
                normalized_steps.extend(_normalized_ci_steps(raw_step))
                skipped_actions.extend(
                    CiWorkflowSkippedAction(
                        name=action.name,
                        uses=action.uses,
                        local_substitute=_local_action_substitute(
                            expanded_job_name, action.name, action.uses
                        ),
                    )
                    for action in _skipped_ci_actions(raw_step)
                )
            result[expanded_job_name] = CiWorkflowJob(
                job_name=expanded_job_name,
                steps=tuple(normalized_steps),
                needs=_normalized_needs(expanded_job_body.get("needs")),
                workflow_only_needs=_workflow_only_needs(
                    expanded_job_body.get("needs")
                ),
                skipped_actions=tuple(skipped_actions),
                workspace_write_sets=_JOB_WORKSPACE_WRITE_SETS.get(
                    expanded_job_name, ()
                ),
                host_tools=_JOB_HOST_TOOLS.get(expanded_job_name, ()),
            )
    return result


def all_job_names() -> tuple[str, ...]:
    return tuple(ci_workflow_jobs())


def ci_lite_job_names() -> tuple[str, ...]:
    return tuple(
        job_name
        for job_name in ci_workflow_jobs()
        if job_name not in _CI_LITE_EXCLUDED_JOBS
    )


def ci_fast_job_names() -> tuple[str, ...]:
    return tuple(
        job_name
        for job_name in ci_workflow_jobs()
        if job_name not in _CI_FAST_EXCLUDED_JOBS
        and not job_name.startswith(_CI_FAST_EXCLUDED_PREFIXES)
    )
