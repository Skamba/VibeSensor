#!/usr/bin/env python3
"""Run CI job groups in parallel locally from the workflow-backed manifest."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "ci_local"
UI_DIR = ROOT / "apps" / "ui"
UI_NODE_MODULES = UI_DIR / "node_modules"
UI_BOOTSTRAP_HELPER = ROOT / "tools" / "ui" / "ensure_ui_bootstrap.mjs"
PRINT_LOCK = threading.Lock()
RESULT_LOCK = threading.Lock()
_CI_MANIFEST_PATH = Path(__file__).with_name("ci_workflow_manifest.py")


def _load_ci_workflow_manifest_module():
    spec = importlib.util.spec_from_file_location(
        "ci_workflow_manifest_local", _CI_MANIFEST_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {_CI_MANIFEST_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CI_MANIFEST = _load_ci_workflow_manifest_module()
ALL_JOB_NAMES = _CI_MANIFEST.all_job_names()
CI_FAST_JOB_NAMES = _CI_MANIFEST.ci_fast_job_names()
CI_LITE_JOB_NAMES = _CI_MANIFEST.ci_lite_job_names()


@dataclass(frozen=True)
class Step:
    label: str
    cmd: list[str]
    cwd: Path = ROOT
    env: dict[str, str] | None = None
    shell: bool = False


@dataclass(frozen=True)
class JobResult:
    name: str
    ok: bool
    failed_step: str | None
    return_code: int
    duration_s: float
    log_path: Path
    skipped_reason: str | None = None


def _emit(line: str) -> None:
    with PRINT_LOCK:
        print(line, flush=True)


def _format_cmd(cmd: list[str]) -> str:
    return shlex.join(cmd)


@dataclass(frozen=True)
class UiBootstrapStatus:
    needs_npm_ci: bool
    lock_hash: str
    current_lock_hash: str
    node_modules_exists: bool


def _ui_bootstrap_status(skip_npm_ci: bool) -> UiBootstrapStatus:
    command = ["node", os.path.relpath(UI_BOOTSTRAP_HELPER, UI_DIR), "--check"]
    if skip_npm_ci:
        command.append("--skip-npm-ci")
    raw = subprocess.check_output(command, cwd=UI_DIR, text=True)
    payload = json.loads(raw)
    return UiBootstrapStatus(
        needs_npm_ci=bool(payload["needs_npm_ci"]),
        lock_hash=str(payload["lock_hash"]),
        current_lock_hash=str(payload["current_lock_hash"]),
        node_modules_exists=bool(payload["node_modules_exists"]),
    )


def _should_run_ui_npm_ci(skip_npm_ci: bool) -> bool:
    return _ui_bootstrap_status(skip_npm_ci).needs_npm_ci


def _job_uses_ui_workspace(steps: list[Step]) -> bool:
    return any(step.cwd == UI_DIR for step in steps)


def _job_runs_release_smoke_ui_build(steps: list[Step]) -> bool:
    return any(
        "tools/tests/run_release_smoke.py" in step.cmd
        and "--skip-ui-build" not in step.cmd
        for step in steps
    )


def _selected_jobs_touch_ui(
    selected_jobs: list[str], all_jobs: dict[str, list[Step]]
) -> bool:
    return any(
        _job_runs_release_smoke_ui_build(all_jobs[job_name])
        or _job_uses_ui_workspace(all_jobs[job_name])
        for job_name in selected_jobs
    )


def _shared_ui_workspace_would_race(
    selected_jobs: list[str],
    all_jobs: dict[str, list[Step]],
    *,
    skip_bootstrap: bool,
    skip_npm_ci: bool,
) -> bool:
    if not skip_bootstrap:
        return False
    if not any(
        _job_runs_release_smoke_ui_build(all_jobs[job_name])
        for job_name in selected_jobs
    ):
        return False
    if not any(
        _job_uses_ui_workspace(all_jobs[job_name]) for job_name in selected_jobs
    ):
        return False
    return _should_run_ui_npm_ci(skip_npm_ci)


def _run_step(step: Step, log_file) -> int:
    formatted_cmd = step.cmd[0] if step.shell else _format_cmd(step.cmd)
    log_file.write(f"$ {formatted_cmd}\n")
    env = None if step.env is None else {**os.environ, **step.env}
    command: str | list[str] = step.cmd[0] if step.shell else step.cmd
    proc = subprocess.run(
        command,
        cwd=str(step.cwd),
        env=env,
        shell=step.shell,
        executable="/bin/bash" if step.shell else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = proc.stdout or ""
    if output:
        log_file.write(output)
        if not output.endswith("\n"):
            log_file.write("\n")
    log_file.flush()
    return proc.returncode


def _run_job(name: str, steps: list[Step], results: dict[str, JobResult]) -> None:
    started = time.monotonic()
    log_path = LOG_DIR / f"{name}.log"
    _emit(f"[{name}] start ({len(steps)} steps)")
    failed_step: str | None = None
    failed_code = 0
    with log_path.open("w", encoding="utf-8") as log_file:
        for step in steps:
            _emit(f"[{name}] step: {step.label}")
            step_started = time.monotonic()
            rc = _run_step(step, log_file)
            step_elapsed = time.monotonic() - step_started
            if rc != 0:
                failed_step = step.label
                failed_code = rc
                _emit(
                    f"[{name}] fail at '{step.label}' (exit {rc}) after {step_elapsed:.1f}s; log: {log_path}"
                )
                break
            _emit(f"[{name}] ok '{step.label}' in {step_elapsed:.1f}s")

    elapsed = time.monotonic() - started
    ok = failed_step is None
    if ok:
        _emit(f"[{name}] success in {elapsed:.1f}s")
    with RESULT_LOCK:
        results[name] = JobResult(
            name=name,
            ok=ok,
            failed_step=failed_step,
            return_code=failed_code,
            duration_s=elapsed,
            log_path=log_path,
        )


def _run_job_with_workspace_locks(
    name: str,
    steps: list[Step],
    results: dict[str, JobResult],
    workspace_write_sets: tuple[str, ...],
    workspace_locks: dict[str, threading.Lock],
) -> None:
    ordered_write_sets = tuple(sorted(workspace_write_sets))
    acquired: list[threading.Lock] = []
    try:
        for write_set in ordered_write_sets:
            lock = workspace_locks[write_set]
            lock.acquire()
            acquired.append(lock)
        _run_job(name, steps, results)
    finally:
        for lock in reversed(acquired):
            lock.release()


def _bootstrap_steps(
    python_cmd: str,
    run_npm_ci: bool,
    *,
    include_platformio: bool,
) -> list[Step]:
    steps = [
        Step(
            "python deps: pip upgrade",
            [python_cmd, "-m", "pip", "install", "--upgrade", "pip"],
        ),
        Step(
            "python deps: editable install",
            [python_cmd, "-m", "pip", "install", "-e", "./apps/server[dev]"],
        ),
    ]
    if include_platformio:
        steps.append(
            Step(
                "python deps: platformio",
                [python_cmd, "-m", "pip", "install", "platformio>=6,<7"],
            )
        )
    if run_npm_ci:
        steps.append(
            Step(
                "ui deps: ensure bootstrap",
                ["node", os.path.relpath(UI_BOOTSTRAP_HELPER, UI_DIR)],
                cwd=ROOT / "apps" / "ui",
            )
        )
    return steps


def _step_from_manifest_command(label: str, command: str) -> Step:
    command_text = command
    tokens = shlex.split(command_text)
    cwd = ROOT
    if len(tokens) >= 3 and tokens[0] == "cd" and tokens[2] == "&&":
        cwd = ROOT / tokens[1]
        _cd_prefix, _separator, command_text = command_text.partition(" && ")
        tokens = shlex.split(command_text)

    env: dict[str, str] | None = None
    if tokens and tokens[0] == "env":
        parsed_env: dict[str, str] = {}
        index = 1
        while index < len(tokens) and "=" in tokens[index]:
            key, value = tokens[index].split("=", 1)
            parsed_env[key] = value
            index += 1
        env = parsed_env or None
        tokens = tokens[index:]
        command_text = shlex.join(tokens)

    shell = _requires_shell(command_text, tokens)
    return Step(
        label, [command_text] if shell else tokens, cwd=cwd, env=env, shell=shell
    )


def _requires_shell(command: str, tokens: list[str]) -> bool:
    if not tokens:
        return False
    if tokens[0] in {"set"}:
        return True
    return any(operator in command for operator in (" && ", " || ", " | ", ";"))


def _job_steps(python_cmd: str) -> dict[str, list[Step]]:
    jobs = _CI_MANIFEST.ci_workflow_jobs()
    return {
        job_name: [
            _step_from_manifest_command(spec.label, spec.command)
            for spec in job.local_runnable_steps(python_cmd)
        ]
        for job_name, job in jobs.items()
    }


def _job_workspace_write_sets() -> dict[str, tuple[str, ...]]:
    return {
        job_name: job.workspace_write_sets
        for job_name, job in _CI_MANIFEST.ci_workflow_jobs().items()
    }


def _job_host_tools() -> dict[str, tuple[str, ...]]:
    return {
        job_name: job.host_tools
        for job_name, job in _CI_MANIFEST.ci_workflow_jobs().items()
    }


def _job_needs() -> dict[str, tuple[str, ...]]:
    return {
        job_name: job.needs for job_name, job in _CI_MANIFEST.ci_workflow_jobs().items()
    }


def _job_workflow_only_needs() -> dict[str, tuple[str, ...]]:
    return {
        job_name: job.workflow_only_needs
        for job_name, job in _CI_MANIFEST.ci_workflow_jobs().items()
    }


def _emit_skipped_action_warnings(selected_jobs: list[str]) -> None:
    jobs = _CI_MANIFEST.ci_workflow_jobs()
    warned = False
    for job_name in selected_jobs:
        skipped_actions = jobs[job_name].skipped_actions
        if not skipped_actions:
            continue
        if not warned:
            _emit("[ci-local] skipped external workflow actions:")
            warned = True
        for action in skipped_actions:
            action_name = f" ({action.name})" if action.name else ""
            substitute = (
                f"; local substitute: {action.local_substitute}"
                if action.local_substitute
                else "; no local substitute"
            )
            _emit(f"[ci-local] - {job_name}{action_name}: {action.uses}{substitute}")


def _missing_host_tools(
    selected_jobs: list[str],
    job_host_tools: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    missing_by_job: dict[str, tuple[str, ...]] = {}
    for job_name in selected_jobs:
        missing = tuple(
            tool for tool in job_host_tools[job_name] if shutil.which(tool) is None
        )
        if missing:
            missing_by_job[job_name] = missing
    return missing_by_job


def _check_host_tool_prerequisites(
    selected_jobs: list[str],
    job_host_tools: dict[str, tuple[str, ...]],
) -> bool:
    missing = _missing_host_tools(selected_jobs, job_host_tools)
    if not missing:
        return True
    _emit("[ci-local] missing host prerequisites for selected jobs:")
    for job_name, tools in missing.items():
        _emit(
            f"[ci-local] - {job_name} requires {', '.join(tools)}. "
            "GitHub CI installs these inside the job; install them locally or run "
            "the job through ACT for workflow-managed prerequisites."
        )
    return False


def _overlapping_workspace_write_sets(
    selected_jobs: list[str],
    job_write_sets: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    jobs_by_write_set: dict[str, list[str]] = {}
    for job_name in selected_jobs:
        for write_set in job_write_sets[job_name]:
            jobs_by_write_set.setdefault(write_set, []).append(job_name)
    return {
        write_set: tuple(job_names)
        for write_set, job_names in sorted(jobs_by_write_set.items())
        if len(job_names) > 1
    }


def _emit_workspace_write_set_warnings(
    selected_jobs: list[str],
    job_write_sets: dict[str, tuple[str, ...]],
) -> None:
    overlaps = _overlapping_workspace_write_sets(selected_jobs, job_write_sets)
    if not overlaps:
        return
    _emit("[ci-local] shared workspace write-set serialization:")
    for write_set, job_names in overlaps.items():
        _emit(
            f"[ci-local] - {write_set}: {', '.join(job_names)}; serialized locally "
            "because GitHub jobs use isolated checkouts"
        )


def _emit_dependency_warnings(
    selected_jobs: list[str],
    job_needs: dict[str, tuple[str, ...]],
    job_workflow_only_needs: dict[str, tuple[str, ...]],
) -> None:
    selected = set(selected_jobs)
    missing_by_job = {
        job_name: tuple(need for need in job_needs[job_name] if need not in selected)
        for job_name in selected_jobs
    }
    missing_by_job = {
        job_name: missing for job_name, missing in missing_by_job.items() if missing
    }
    if missing_by_job:
        _emit("[ci-local] GitHub needs not selected locally:")
        for job_name, missing in missing_by_job.items():
            _emit(
                f"[ci-local] - {job_name} normally needs {', '.join(missing)}; "
                "selected jobs still run, but omitted prerequisites are not modeled."
            )
    workflow_only_by_job = {
        job_name: job_workflow_only_needs[job_name] for job_name in selected_jobs
    }
    workflow_only_by_job = {
        job_name: needs for job_name, needs in workflow_only_by_job.items() if needs
    }
    if not workflow_only_by_job:
        return
    _emit("[ci-local] GitHub workflow-only needs not runnable locally:")
    for job_name, needs in workflow_only_by_job.items():
        _emit(
            f"[ci-local] - {job_name} normally needs {', '.join(needs)}; "
            "the local runner reports the dependency-order difference instead."
        )


def _selected_jobs_require_platformio(selected_jobs: list[str]) -> bool:
    jobs = _CI_MANIFEST.ci_workflow_jobs()
    return any(jobs[job_name].requires_platformio for job_name in selected_jobs)


def _run_bootstrap(steps: list[Step]) -> int:
    if not steps:
        return 0
    bootstrap_log = LOG_DIR / "bootstrap.log"
    _emit(f"[bootstrap] start ({len(steps)} steps)")
    with bootstrap_log.open("w", encoding="utf-8") as log_file:
        for step in steps:
            _emit(f"[bootstrap] step: {step.label}")
            started = time.monotonic()
            rc = _run_step(step, log_file)
            elapsed = time.monotonic() - started
            if rc != 0:
                _emit(
                    f"[bootstrap] fail at '{step.label}' (exit {rc}) after {elapsed:.1f}s; log: {bootstrap_log}"
                )
                return rc
            _emit(f"[bootstrap] ok '{step.label}' in {elapsed:.1f}s")
    _emit("[bootstrap] success")
    return 0


def _skipped_job_result(name: str, reason: str, started: float) -> JobResult:
    return JobResult(
        name=name,
        ok=False,
        failed_step=None,
        return_code=0,
        duration_s=time.monotonic() - started,
        log_path=LOG_DIR / f"{name}.log",
        skipped_reason=reason,
    )


def _run_selected_jobs(
    selected_jobs: list[str],
    all_jobs: dict[str, list[Step]],
    job_write_sets: dict[str, tuple[str, ...]],
    job_needs: dict[str, tuple[str, ...]],
) -> tuple[dict[str, JobResult], float, bool]:
    started = time.monotonic()
    results: dict[str, JobResult] = {}
    selected = set(selected_jobs)
    pending = set(selected_jobs)
    workspace_locks = {
        write_set: threading.Lock()
        for job_name in selected_jobs
        for write_set in job_write_sets[job_name]
    }
    while pending:
        ready = [
            job_name
            for job_name in selected_jobs
            if job_name in pending
            and all(
                need not in selected or need in results for need in job_needs[job_name]
            )
        ]
        if not ready:
            _emit(
                "[ci-local] unable to resolve selected job dependency order; "
                f"remaining jobs: {', '.join(sorted(pending))}"
            )
            return results, time.monotonic() - started, False

        runnable: list[str] = []
        for job_name in ready:
            failed_needs = [
                need
                for need in job_needs[job_name]
                if need in selected and not results[need].ok
            ]
            if failed_needs:
                reason = f"needed job failed: {', '.join(failed_needs)}"
                _emit(f"[{job_name}] skip ({reason})")
                with RESULT_LOCK:
                    results[job_name] = _skipped_job_result(job_name, reason, started)
                pending.remove(job_name)
                continue
            runnable.append(job_name)

        threads: list[threading.Thread] = []
        for job_name in runnable:
            thread = threading.Thread(
                target=_run_job_with_workspace_locks,
                args=(
                    job_name,
                    all_jobs[job_name],
                    results,
                    job_write_sets[job_name],
                    workspace_locks,
                ),
                daemon=False,
            )
            thread.start()
            threads.append(thread)

        for thread in threads:
            thread.join()
        for job_name in runnable:
            pending.remove(job_name)

    return results, time.monotonic() - started, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run local CI-equivalent checks with the same command groups as .github/workflows/ci.yml, "
            "executed in parallel."
        )
    )
    parser.add_argument(
        "--job",
        action="append",
        choices=ALL_JOB_NAMES,
        help="Run only selected job(s). Repeat to run multiple jobs.",
    )
    parser.add_argument(
        "--ci-fast",
        action="store_true",
        help="Run fast local CI gates: lint, docs, static guards, and type checks.",
    )
    parser.add_argument(
        "--ci-lite",
        action="store_true",
        help="Run non-Docker workflow jobs except E2E, including heavier browser/release/backend suites.",
    )
    parser.add_argument(
        "--skip-bootstrap",
        action="store_true",
        help="Skip shared local dependency bootstrap (pip install + optional npm ci).",
    )
    parser.add_argument(
        "--skip-npm-ci",
        action="store_true",
        help="Skip npm ci bootstrap even when node_modules is missing.",
    )
    args = parser.parse_args(argv)
    selected_modes = sum(bool(mode) for mode in (args.job, args.ci_fast, args.ci_lite))
    if selected_modes > 1:
        parser.error("--job, --ci-fast, and --ci-lite are mutually exclusive")

    python_cmd = sys.executable
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    all_jobs = _job_steps(python_cmd)
    job_write_sets = _job_workspace_write_sets()
    job_host_tools = _job_host_tools()
    job_needs = _job_needs()
    job_workflow_only_needs = _job_workflow_only_needs()
    if args.job:
        selected_jobs = args.job
    elif args.ci_fast:
        selected_jobs = list(CI_FAST_JOB_NAMES)
    elif args.ci_lite:
        selected_jobs = list(CI_LITE_JOB_NAMES)
    else:
        selected_jobs = list(ALL_JOB_NAMES)
    _emit_skipped_action_warnings(selected_jobs)
    _emit_workspace_write_set_warnings(selected_jobs, job_write_sets)
    _emit_dependency_warnings(selected_jobs, job_needs, job_workflow_only_needs)
    if not _check_host_tool_prerequisites(selected_jobs, job_host_tools):
        return 2

    if _shared_ui_workspace_would_race(
        selected_jobs,
        all_jobs,
        skip_bootstrap=args.skip_bootstrap,
        skip_npm_ci=args.skip_npm_ci,
    ):
        _emit(
            "[ci-local] refusing to run shared UI jobs with --skip-bootstrap: "
            "release-smoke would trigger npm ci inside apps/ui while other UI jobs "
            "use the same workspace. Re-run without --skip-bootstrap, or refresh "
            "apps/ui/.npm-ci-lock.sha256 before using --skip-bootstrap."
        )
        return 2

    run_npm_ci = (
        _should_run_ui_npm_ci(args.skip_npm_ci)
        if _selected_jobs_touch_ui(selected_jobs, all_jobs)
        else False
    )
    bootstrap_steps = (
        []
        if args.skip_bootstrap
        else _bootstrap_steps(
            python_cmd,
            run_npm_ci,
            include_platformio=_selected_jobs_require_platformio(selected_jobs),
        )
    )
    bootstrap_rc = _run_bootstrap(bootstrap_steps)
    if bootstrap_rc != 0:
        return bootstrap_rc

    results, elapsed, ordered = _run_selected_jobs(
        selected_jobs, all_jobs, job_write_sets, job_needs
    )
    _emit("\n=== ci-local summary ===")
    overall_ok = ordered
    for job_name in selected_jobs:
        result = results.get(job_name)
        if result is None:
            overall_ok = False
            _emit(f"- {job_name}: NOT RUN (dependency order could not be resolved)")
            continue
        if result.ok:
            _emit(
                f"- {job_name}: PASS ({result.duration_s:.1f}s) log={result.log_path}"
            )
            continue
        if result.skipped_reason is not None:
            _emit(f"- {job_name}: SKIP ({result.skipped_reason})")
            continue
        overall_ok = False
        _emit(
            f"- {job_name}: FAIL at '{result.failed_step}' (exit {result.return_code}) "
            f"after {result.duration_s:.1f}s log={result.log_path}"
        )

    _emit(f"total wall time: {elapsed:.1f}s")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
