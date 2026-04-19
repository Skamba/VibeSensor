#!/usr/bin/env python3
"""Run CI job groups in parallel locally from the workflow-backed manifest."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shlex
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
CI_LITE_JOB_NAMES = _CI_MANIFEST.ci_lite_job_names()


@dataclass(frozen=True)
class Step:
    label: str
    cmd: list[str]
    cwd: Path = ROOT
    env: dict[str, str] | None = None


@dataclass(frozen=True)
class JobResult:
    name: str
    ok: bool
    failed_step: str | None
    return_code: int
    duration_s: float
    log_path: Path


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
    log_file.write(f"$ {_format_cmd(step.cmd)}\n")
    env = None if step.env is None else {**os.environ, **step.env}
    proc = subprocess.run(
        step.cmd,
        cwd=str(step.cwd),
        env=env,
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
    tokens = shlex.split(command)
    cwd = ROOT
    if len(tokens) >= 3 and tokens[0] == "cd" and tokens[2] == "&&":
        cwd = ROOT / tokens[1]
        tokens = tokens[3:]

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

    return Step(label, tokens, cwd=cwd, env=env)


def _job_steps(python_cmd: str) -> dict[str, list[Step]]:
    jobs = _CI_MANIFEST.ci_workflow_jobs()
    return {
        job_name: [
            _step_from_manifest_command(spec.label, spec.command)
            for spec in job.local_runnable_steps(python_cmd)
        ]
        for job_name, job in jobs.items()
    }


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


def main() -> int:
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
        "--ci-lite",
        action="store_true",
        help="Run the non-Docker blocking CI subset derived from the workflow manifest.",
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
    args = parser.parse_args()
    if args.job and args.ci_lite:
        parser.error("--ci-lite cannot be combined with --job")

    python_cmd = sys.executable
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    all_jobs = _job_steps(python_cmd)
    selected_jobs = (
        args.job
        if args.job
        else list(CI_LITE_JOB_NAMES if args.ci_lite else ALL_JOB_NAMES)
    )

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

    started = time.monotonic()
    results: dict[str, JobResult] = {}
    threads: list[threading.Thread] = []
    for job_name in selected_jobs:
        thread = threading.Thread(
            target=_run_job,
            args=(job_name, all_jobs[job_name], results),
            daemon=False,
        )
        thread.start()
        threads.append(thread)

    for thread in threads:
        thread.join()

    elapsed = time.monotonic() - started
    _emit("\n=== ci-local summary ===")
    overall_ok = True
    for job_name in selected_jobs:
        result = results[job_name]
        if result.ok:
            _emit(
                f"- {job_name}: PASS ({result.duration_s:.1f}s) log={result.log_path}"
            )
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
