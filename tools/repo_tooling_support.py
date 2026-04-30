"""Shared helpers for repository tooling scripts."""

from __future__ import annotations

import importlib.util
import shlex
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from types import ModuleType

CommandTokenNormalizer = Callable[[str], str]


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


def walk_files(repo_root: Path, excluded_dirs: Iterable[str]) -> list[str]:
    excluded = set(excluded_dirs)
    files: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in excluded for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return files


def tracked_files(repo_root: Path, excluded_dirs: Iterable[str]) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = [line for line in result.stdout.splitlines() if line]
        if tracked:
            return tracked
    except (OSError, subprocess.CalledProcessError):
        pass
    return walk_files(repo_root, excluded_dirs)


def normalize_tokenized_command(
    tokens: list[str],
    *,
    command_token_normalizer: CommandTokenNormalizer | None = None,
) -> str:
    if not tokens:
        return ""
    normalized = list(tokens)
    command_index = 0
    if normalized[0] == "env":
        command_index = 1
        while command_index < len(normalized) and "=" in normalized[command_index]:
            command_index += 1
        if command_index >= len(normalized):
            return shlex.join(normalized)
    if command_token_normalizer is not None:
        normalized[command_index] = command_token_normalizer(normalized[command_index])
    return shlex.join(normalized)


def normalize_shell_command(
    command: str,
    *,
    command_token_normalizer: CommandTokenNormalizer | None = None,
) -> str:
    tokens = shlex.split(command)
    if "&&" not in tokens:
        return normalize_tokenized_command(
            tokens,
            command_token_normalizer=command_token_normalizer,
        )

    parts: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token == "&&":
            if current:
                parts.append(
                    normalize_tokenized_command(
                        current,
                        command_token_normalizer=command_token_normalizer,
                    )
                )
                current = []
            continue
        current.append(token)
    if current:
        parts.append(
            normalize_tokenized_command(
                current,
                command_token_normalizer=command_token_normalizer,
            )
        )
    return " && ".join(parts)


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
