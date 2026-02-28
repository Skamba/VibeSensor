#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = ROOT / "artifacts" / "ai" / "logs" / "ci_local"
PRINT_LOCK = threading.Lock()
RESULT_LOCK = threading.Lock()


@dataclass(frozen=True)
class Step:
    label: str
    cmd: list[str]
    cwd: Path = ROOT


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


def _run_step(step: Step, log_file) -> int:
    log_file.write(f"$ {_format_cmd(step.cmd)}\n")
    proc = subprocess.run(
        step.cmd,
        cwd=str(step.cwd),
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


def _bootstrap_steps(python_cmd: str, run_npm_ci: bool) -> list[Step]:
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
    if run_npm_ci:
        steps.append(Step("ui deps: npm ci", ["npm", "ci"], cwd=ROOT / "apps" / "ui"))
    return steps


def _job_steps(python_cmd: str) -> dict[str, list[Step]]:
    return {
        "preflight": [
            Step(
                "ruff check",
                [
                    "ruff",
                    "check",
                    "apps/server/vibesensor",
                    "apps/server/tests",
                    "apps/simulator",
                    "libs/core/python",
                    "libs/shared/python",
                ],
            ),
            Step(
                "ruff format --check",
                [
                    "ruff",
                    "format",
                    "--check",
                    "apps/server/vibesensor",
                    "apps/server/tests",
                    "apps/simulator",
                    "libs/core/python",
                    "libs/shared/python",
                ],
            ),
            Step("line endings", [python_cmd, "tools/config/check_line_endings.py"]),
            Step(
                "config preflight (example)",
                [
                    python_cmd,
                    "tools/config/config_preflight.py",
                    "apps/server/config.example.yaml",
                ],
            ),
            Step(
                "config preflight (dev)",
                [
                    python_cmd,
                    "tools/config/config_preflight.py",
                    "apps/server/config.dev.yaml",
                ],
            ),
            Step(
                "verify no path indirections",
                [python_cmd, "tools/dev/verify_no_path_indirections.py"],
            ),
        ],
        "tests": [
            Step("ui sync", [python_cmd, "tools/sync_ui_to_pi_public.py"]),
            Step("ui typecheck", ["npm", "run", "typecheck"], cwd=ROOT / "apps" / "ui"),
            Step(
                "playwright install chromium",
                ["npx", "playwright", "install", "chromium"],
                cwd=ROOT / "apps" / "ui",
            ),
            Step("ui smoke", ["npm", "run", "test:smoke"], cwd=ROOT / "apps" / "ui"),
            Step(
                "backend tests shard 1/4 (non-selenium)",
                [
                    python_cmd,
                    "tools/tests/pytest_shard.py",
                    "--shard-index",
                    "1",
                    "--shard-count",
                    "4",
                    "--",
                    "-m",
                    "not selenium",
                    "apps/server/tests",
                ],
            ),
            Step(
                "backend tests shard 2/4 (non-selenium)",
                [
                    python_cmd,
                    "tools/tests/pytest_shard.py",
                    "--shard-index",
                    "2",
                    "--shard-count",
                    "4",
                    "--",
                    "-m",
                    "not selenium",
                    "apps/server/tests",
                ],
            ),
            Step(
                "backend tests shard 3/4 (non-selenium)",
                [
                    python_cmd,
                    "tools/tests/pytest_shard.py",
                    "--shard-index",
                    "3",
                    "--shard-count",
                    "4",
                    "--",
                    "-m",
                    "not selenium",
                    "apps/server/tests",
                ],
            ),
            Step(
                "backend tests shard 4/4 (non-selenium)",
                [
                    python_cmd,
                    "tools/tests/pytest_shard.py",
                    "--shard-index",
                    "4",
                    "--shard-count",
                    "4",
                    "--",
                    "-m",
                    "not selenium",
                    "apps/server/tests",
                ],
            ),
        ],
        "e2e": [
            Step(
                "docker-backed e2e suite",
                [
                    python_cmd,
                    "tools/tests/run_e2e_parallel.py",
                    "--shards",
                    "2",
                    "--fast-e2e",
                ],
            ),
        ],
    }


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
        choices=["preflight", "tests", "e2e"],
        help="Run only selected job(s). Repeat to run multiple jobs.",
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

    python_cmd = sys.executable
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    run_npm_ci = (
        not args.skip_npm_ci and not (ROOT / "apps" / "ui" / "node_modules").exists()
    )
    bootstrap_steps = (
        [] if args.skip_bootstrap else _bootstrap_steps(python_cmd, run_npm_ci)
    )
    bootstrap_rc = _run_bootstrap(bootstrap_steps)
    if bootstrap_rc != 0:
        return bootstrap_rc

    all_jobs = _job_steps(python_cmd)
    selected_jobs = args.job if args.job else ["preflight", "tests", "e2e"]

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
