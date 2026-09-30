"""Shared helpers for repository tooling scripts."""

from __future__ import annotations

import importlib.util
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType


def _repo_python_major_minor(repo_root: Path) -> tuple[int, int]:
    version_path = repo_root / ".python-version"
    raw_version = version_path.read_text(encoding="utf-8").strip()
    parts = raw_version.split(".")
    if len(parts) < 2:
        raise SystemExit(
            f"{version_path} must contain at least a major.minor Python version."
        )
    try:
        return int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise SystemExit(
            f"{version_path} contains an invalid Python version: {raw_version!r}"
        ) from exc


def ensure_repo_python_version(
    repo_root: Path,
    *,
    script_path: Path | None = None,
    actual_version_info: Sequence[int] | None = None,
    actual_version: str | None = None,
    executable: str | None = None,
) -> None:
    """Stop direct repo tooling runs that use the wrong Python major.minor."""

    expected_major, expected_minor = _repo_python_major_minor(repo_root)
    observed = actual_version_info or sys.version_info
    actual_major_minor = int(observed[0]), int(observed[1])
    if actual_major_minor == (expected_major, expected_minor):
        return

    label = (
        script_path.relative_to(repo_root).as_posix() if script_path else "this command"
    )
    current_version = (actual_version or sys.version).split()[0]
    current_executable = executable or sys.executable
    raise SystemExit(
        f"{label} must run with Python {expected_major}.{expected_minor}.x from .python-version; "
        f"current interpreter is Python {current_version} at {current_executable}. "
        "Run `make setup`, then use a Makefile target or "
        f"`{repo_root / '.venv' / 'bin' / 'python'} {label}`."
    )


def load_module_from_path(module_name: str, module_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load {module_name} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_parallel_runner_support(current_file: str | Path) -> ModuleType:
    helper_path = Path(current_file).with_name("_parallel_runner_support.py")
    return load_module_from_path("_parallel_runner_support", helper_path)


def terminate_processes(
    processes: Sequence[subprocess.Popen[str]],
    *,
    grace_seconds: float = 5.0,
    wait_timeout_seconds: float = 1.0,
) -> None:
    alive = [process for process in processes if process.poll() is None]
    for process in alive:
        process.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + grace_seconds
    while alive and time.monotonic() < deadline:
        alive = [process for process in alive if process.poll() is None]
        if alive:
            time.sleep(0.1)
    for process in alive:
        process.kill()
    for process in processes:
        try:
            process.wait(timeout=wait_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=wait_timeout_seconds)
