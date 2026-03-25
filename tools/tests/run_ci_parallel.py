#!/usr/bin/env python3
"""Run CI job groups in parallel locally (``make test-all``).

Job definitions here mirror ``.github/workflows/ci.yml`` — keep them in sync.
When a CI job's steps change, update the corresponding ``_*_steps()`` builder
below to match.
"""

from __future__ import annotations

import argparse
import hashlib
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
UI_LOCK_FILE = UI_DIR / "package-lock.json"
UI_LOCK_HASH_FILE = UI_DIR / ".npm-ci-lock.sha256"
PRINT_LOCK = threading.Lock()
RESULT_LOCK = threading.Lock()


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


def _ui_lock_hash() -> str:
    # Keep this hash rule aligned with tools/build_ui_static.py.
    return hashlib.sha256(UI_LOCK_FILE.read_bytes()).hexdigest()


def _ui_lock_hash_is_current() -> bool:
    if not UI_LOCK_HASH_FILE.exists():
        return False
    return UI_LOCK_HASH_FILE.read_text(encoding="utf-8").strip() == _ui_lock_hash()


def _mark_ui_lock_hash_current() -> None:
    UI_LOCK_HASH_FILE.write_text(f"{_ui_lock_hash()}\n", encoding="utf-8")


def _should_run_ui_npm_ci(skip_npm_ci: bool) -> bool:
    return not skip_npm_ci and (
        not UI_NODE_MODULES.exists() or not _ui_lock_hash_is_current()
    )


def _shared_ui_workspace_would_race(
    selected_jobs: list[str], *, skip_bootstrap: bool, skip_npm_ci: bool
) -> bool:
    if not skip_bootstrap or "release-smoke" not in selected_jobs:
        return False
    if "frontend-typecheck" not in selected_jobs and "ui-smoke" not in selected_jobs:
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
        steps.append(Step("ui deps: npm ci", ["npm", "ci"], cwd=ROOT / "apps" / "ui"))
    return steps


def _job_steps(python_cmd: str) -> dict[str, list[Step]]:
    return {
        "backend-quality": [
            Step(
                "Validate dependency consistency",
                [python_cmd, "-m", "pip", "check"],
            ),
            Step("Backend quality checks", ["make", "lint"]),
        ],
        "backend-typecheck": [
            Step(
                "Mypy backend enforced coverage",
                [python_cmd, "-m", "mypy", "--config-file", "pyproject.toml"],
                cwd=ROOT / "apps" / "server",
                env={"MYPYPATH": "."},
            ),
        ],
        "frontend-typecheck": [
            Step(
                "UI contract sync check",
                ["npm", "run", "check:contracts"],
                cwd=ROOT / "apps" / "ui",
            ),
            Step("UI lint", ["npm", "run", "lint"], cwd=ROOT / "apps" / "ui"),
            Step("UI typecheck", ["npm", "run", "typecheck"], cwd=ROOT / "apps" / "ui"),
        ],
        "ui-smoke": [
            Step(
                "Install Playwright Chromium",
                ["npx", "playwright", "install", "chromium"],
                cwd=ROOT / "apps" / "ui",
            ),
            Step(
                "UI smoke tests", ["npm", "run", "test:smoke"], cwd=ROOT / "apps" / "ui"
            ),
        ],
        "release-smoke": [
            Step(
                "Release smoke validation",
                [python_cmd, "tools/tests/run_release_smoke.py"],
            ),
        ],
        "firmware-native-tests": [
            Step(
                "Verify firmware protocol fixtures",
                [
                    python_cmd,
                    "tools/firmware/generate_protocol_contract_fixtures.py",
                    "--check",
                ],
            ),
            Step(
                "Firmware native tests",
                ["pio", "test", "-e", "native"],
                cwd=ROOT / "firmware" / "esp",
            ),
        ],
        "backend-tests-1": [
            Step(
                "Prepare backend test artifacts",
                ["mkdir", "-p", "artifacts/ai/logs/ci"],
            ),
            Step(
                "Backend tests shard 1/5",
                [
                    python_cmd,
                    "tools/tests/run_backend_parallel.py",
                    "--shards",
                    "5",
                    "--shard-index",
                    "1",
                    "--junitxml",
                    "artifacts/ai/logs/ci/backend-tests-1.xml",
                ],
            ),
        ],
        "backend-tests-2": [
            Step(
                "Prepare backend test artifacts",
                ["mkdir", "-p", "artifacts/ai/logs/ci"],
            ),
            Step(
                "Backend tests shard 2/5",
                [
                    python_cmd,
                    "tools/tests/run_backend_parallel.py",
                    "--shards",
                    "5",
                    "--shard-index",
                    "2",
                    "--junitxml",
                    "artifacts/ai/logs/ci/backend-tests-2.xml",
                ],
            ),
        ],
        "backend-tests-3": [
            Step(
                "Prepare backend test artifacts",
                ["mkdir", "-p", "artifacts/ai/logs/ci"],
            ),
            Step(
                "Backend tests shard 3/5",
                [
                    python_cmd,
                    "tools/tests/run_backend_parallel.py",
                    "--shards",
                    "5",
                    "--shard-index",
                    "3",
                    "--junitxml",
                    "artifacts/ai/logs/ci/backend-tests-3.xml",
                ],
            ),
        ],
        "backend-tests-4": [
            Step(
                "Prepare backend test artifacts",
                ["mkdir", "-p", "artifacts/ai/logs/ci"],
            ),
            Step(
                "Backend tests shard 4/5",
                [
                    python_cmd,
                    "tools/tests/run_backend_parallel.py",
                    "--shards",
                    "5",
                    "--shard-index",
                    "4",
                    "--junitxml",
                    "artifacts/ai/logs/ci/backend-tests-4.xml",
                ],
            ),
        ],
        "backend-tests-5": [
            Step(
                "Prepare backend test artifacts",
                ["mkdir", "-p", "artifacts/ai/logs/ci"],
            ),
            Step(
                "Backend tests shard 5/5",
                [
                    python_cmd,
                    "tools/tests/run_backend_parallel.py",
                    "--shards",
                    "5",
                    "--shard-index",
                    "5",
                    "--junitxml",
                    "artifacts/ai/logs/ci/backend-tests-5.xml",
                ],
            ),
        ],
        "e2e": [
            Step(
                "Docker-backed e2e suite (skip already-owned checks)",
                [
                    python_cmd,
                    "tools/tests/run_e2e_parallel.py",
                    "--fast-e2e",
                    "--shards",
                    "6",
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
            if step.label == "ui deps: npm ci":
                _mark_ui_lock_hash_current()
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
        choices=[
            "backend-quality",
            "backend-typecheck",
            "frontend-typecheck",
            "ui-smoke",
            "release-smoke",
            "firmware-native-tests",
            "backend-tests-1",
            "backend-tests-2",
            "backend-tests-3",
            "backend-tests-4",
            "backend-tests-5",
            "e2e",
        ],
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

    all_jobs = _job_steps(python_cmd)
    selected_jobs = (
        args.job
        if args.job
        else [
            "backend-quality",
            "backend-typecheck",
            "frontend-typecheck",
            "ui-smoke",
            "release-smoke",
            "firmware-native-tests",
            "backend-tests-1",
            "backend-tests-2",
            "backend-tests-3",
            "backend-tests-4",
            "backend-tests-5",
            "e2e",
        ]
    )

    if _shared_ui_workspace_would_race(
        selected_jobs,
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

    run_npm_ci = _should_run_ui_npm_ci(args.skip_npm_ci)
    bootstrap_steps = (
        []
        if args.skip_bootstrap
        else _bootstrap_steps(
            python_cmd,
            run_npm_ci,
            include_platformio="firmware-native-tests" in selected_jobs,
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
