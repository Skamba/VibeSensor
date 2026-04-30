#!/usr/bin/env python3
"""Plan local validation from the current diff using CI path rules."""

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_CI_PATH_RULES_PATH = Path(__file__).with_name("ci_path_rules.py")
_CI_MANIFEST_PATH = Path(__file__).with_name("ci_workflow_manifest.py")
_RUN_CHANGED_PATH = Path(__file__).with_name("run_changed.py")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_CI_PATH_RULES = _load_module("ci_path_rules_for_plan_validation", _CI_PATH_RULES_PATH)
_CI_MANIFEST = _load_module("ci_manifest_for_plan_validation", _CI_MANIFEST_PATH)
_RUN_CHANGED = _load_module("run_changed_for_plan_validation", _RUN_CHANGED_PATH)

BACKEND_TEST_JOBS = tuple(f"backend-tests-{index}" for index in range(1, 6))


@dataclass(frozen=True)
class SelectionMapping:
    field_name: str
    ci_jobs: tuple[str, ...]
    local_jobs: tuple[str, ...]
    act_jobs: tuple[str, ...]


@dataclass(frozen=True)
class ValidationPlan:
    base_ref: str
    changed_files: tuple[str, ...]
    ci_jobs: tuple[str, ...]
    local_jobs: tuple[str, ...]
    act_jobs: tuple[str, ...]
    local_command: tuple[str, ...]
    act_command: tuple[str, ...]
    parity: str
    approximations: tuple[str, ...] = ()
    unsupported: tuple[str, ...] = ()
    github_outputs: dict[str, str] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {
            "base_ref": self.base_ref,
            "changed_files": list(self.changed_files),
            "ci_jobs": list(self.ci_jobs),
            "local_jobs": list(self.local_jobs),
            "act_jobs": list(self.act_jobs),
            "local_command": list(self.local_command),
            "act_command": list(self.act_command),
            "parity": self.parity,
            "approximations": list(self.approximations),
            "unsupported": list(self.unsupported),
            "github_outputs": self.github_outputs,
        }


SELECTION_MAPPINGS = (
    SelectionMapping("docs_lint", ("docs-lint",), ("docs-lint",), ("docs-lint",)),
    SelectionMapping(
        "repo_hygiene", ("repo-hygiene",), ("repo-hygiene",), ("repo-hygiene",)
    ),
    SelectionMapping("shell_lint", ("shell-lint",), ("shell-lint",), ("shell-lint",)),
    SelectionMapping(
        "backend_lint", ("backend-lint",), ("backend-lint",), ("backend-lint",)
    ),
    SelectionMapping(
        "backend_static_guards",
        ("backend-static-guards",),
        ("backend-static-guards",),
        ("backend-static-guards",),
    ),
    SelectionMapping(
        "backend_preflight",
        ("backend-preflight",),
        ("backend-preflight",),
        ("backend-preflight",),
    ),
    SelectionMapping(
        "backend_contract_drift",
        ("backend-contract-drift",),
        ("backend-contract-drift",),
        ("backend-contract-drift",),
    ),
    SelectionMapping(
        "backend_typecheck",
        ("backend-typecheck",),
        ("backend-typecheck",),
        ("backend-typecheck",),
    ),
    SelectionMapping(
        "frontend_typecheck",
        ("frontend-quality", "frontend-typecheck", "ui-unit"),
        ("frontend-quality", "frontend-typecheck", "ui-unit"),
        ("frontend-quality", "frontend-typecheck", "ui-unit"),
    ),
    SelectionMapping("ui_smoke", ("ui-smoke",), ("ui-smoke",), ("ui-smoke",)),
    SelectionMapping(
        "backend_tests",
        ("backend-tests",),
        BACKEND_TEST_JOBS,
        ("backend-tests",),
    ),
    SelectionMapping(
        "release_smoke",
        ("ui-build-artifact", "release-smoke"),
        ("release-smoke",),
        ("ui-build-artifact", "release-smoke"),
    ),
    SelectionMapping(
        "firmware_native_tests",
        ("firmware-native-tests",),
        ("firmware-native-tests",),
        ("firmware-native-tests",),
    ),
    SelectionMapping("e2e", ("e2e",), ("e2e",), ("e2e",)),
)


def _dedupe(items: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _selected_jobs(
    selection,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    ci_jobs: list[str] = []
    local_jobs: list[str] = []
    act_jobs: list[str] = []
    for mapping in SELECTION_MAPPINGS:
        if getattr(selection, mapping.field_name):
            ci_jobs.extend(mapping.ci_jobs)
            local_jobs.extend(mapping.local_jobs)
            act_jobs.extend(mapping.act_jobs)
    return _dedupe(ci_jobs), _dedupe(local_jobs), _dedupe(act_jobs)


def _local_command(local_jobs: tuple[str, ...]) -> tuple[str, ...]:
    if not local_jobs:
        return ()
    command = [sys.executable, "tools/tests/run_ci_parallel.py"]
    for job in local_jobs:
        command.extend(("--job", job))
    return tuple(command)


def _act_command(base_ref: str, act_jobs: tuple[str, ...]) -> tuple[str, ...]:
    if not act_jobs:
        return ()
    command = ["./tools/tests/run_ci_with_act.sh", "--base-ref", base_ref]
    for job in act_jobs:
        command.extend(("-j", job))
    return tuple(command)


def _parity_notes(
    local_jobs: tuple[str, ...],
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    jobs = _CI_MANIFEST.ci_workflow_jobs()
    approximations: list[str] = []
    unsupported: list[str] = []
    if "release-smoke" in local_jobs:
        approximations.append(
            "release-smoke: CI restores ui-build-artifact; local runner builds UI static directly"
        )
    for job_name in local_jobs:
        job = jobs.get(job_name)
        if job is None:
            unsupported.append(f"{job_name}: no local workflow manifest entry")
            continue
        skipped_with_substitutes: list[str] = []
        for action in job.skipped_actions:
            action_label = action.name or action.uses
            if action.local_substitute:
                skipped_with_substitutes.append(action.uses)
            else:
                unsupported.append(
                    f"{job_name}: skips {action.uses} ({action_label}) without local substitute"
                )
        if skipped_with_substitutes:
            approximations.append(
                f"{job_name}: skips external actions with local substitutes: "
                + ", ".join(dict.fromkeys(skipped_with_substitutes))
            )
    if unsupported:
        parity = "unsupported"
    elif approximations:
        parity = "approximate"
    else:
        parity = "exact"
    return parity, tuple(approximations), tuple(unsupported)


def build_validation_plan(requested_base_ref: str | None = None) -> ValidationPlan:
    base_ref = _RUN_CHANGED._resolve_base_ref(requested_base_ref)
    changed_files = _RUN_CHANGED._changed_files(base_ref)
    if not changed_files:
        return ValidationPlan(
            base_ref=base_ref,
            changed_files=(),
            ci_jobs=(),
            local_jobs=(),
            act_jobs=(),
            local_command=(),
            act_command=(),
            parity="exact",
            github_outputs={},
        )

    selection = _CI_PATH_RULES.workflow_job_selection(changed_files)
    ci_jobs, local_jobs, act_jobs = _selected_jobs(selection)
    parity, approximations, unsupported = _parity_notes(local_jobs)
    return ValidationPlan(
        base_ref=base_ref,
        changed_files=changed_files,
        ci_jobs=ci_jobs,
        local_jobs=local_jobs,
        act_jobs=act_jobs,
        local_command=_local_command(local_jobs),
        act_command=_act_command(base_ref, act_jobs),
        parity=parity,
        approximations=approximations,
        unsupported=unsupported,
        github_outputs=selection.github_outputs(),
    )


def _print_plan(plan: ValidationPlan) -> None:
    print(f"[validation-plan] base ref: {plan.base_ref}")
    if not plan.changed_files:
        print("[validation-plan] no changed files detected")
    else:
        print("[validation-plan] changed files:")
        for path in plan.changed_files:
            print(f"  - {path}")
    print(f"[validation-plan] parity: {plan.parity}")
    if plan.ci_jobs:
        print(f"[validation-plan] CI jobs: {', '.join(plan.ci_jobs)}")
    if plan.local_command:
        print(f"[validation-plan] local: {shlex.join(plan.local_command)}")
    if plan.act_command:
        print(f"[validation-plan] act: {shlex.join(plan.act_command)}")
    for note in plan.approximations:
        print(f"[validation-plan] approximate: {note}")
    for note in plan.unsupported:
        print(f"[validation-plan] unsupported: {note}")
    print("[validation-plan] json:")
    print(json.dumps(plan.as_json(), sort_keys=True, separators=(",", ":")))


def _run_command(command: tuple[str, ...]) -> int:
    if not command:
        return 0
    return subprocess.run(command, cwd=ROOT, check=False).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        help="Git ref to diff against (default: origin/main, falling back to main).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Run the planned non-Docker local run_ci_parallel.py command.",
    )
    parser.add_argument(
        "--act",
        action="store_true",
        help="Run the planned act command instead of run_ci_parallel.py.",
    )
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Print only the compact machine-readable JSON summary.",
    )
    args = parser.parse_args(argv)
    if args.run and args.act:
        parser.error("--run and --act are mutually exclusive")

    plan = build_validation_plan(args.base_ref)
    if args.json_only:
        print(json.dumps(plan.as_json(), sort_keys=True, separators=(",", ":")))
    else:
        _print_plan(plan)

    if plan.unsupported and (args.run or args.act):
        print(
            "[validation-plan] refusing to run unsupported local CI parity plan",
            file=sys.stderr,
        )
        return 2
    if args.run:
        return _run_command(plan.local_command)
    if args.act:
        return _run_command(plan.act_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
