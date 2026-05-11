"""Shared runtime helpers for fuzz tooling scripts."""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType


def load_repo_tooling_support(repo_root: Path) -> ModuleType:
    helper_path = repo_root / "tools" / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def terminate_processes(
    processes: Sequence[subprocess.Popen[str]],
    *,
    repo_root: Path,
) -> None:
    load_repo_tooling_support(repo_root).terminate_processes(processes)


def worker_seed(base_seed: int | None, worker_index: int) -> int | None:
    if base_seed is None:
        return None
    return base_seed + worker_index


def worker_prefix(worker_index: int | None) -> str:
    if worker_index is None:
        return ""
    return f"[worker {worker_index}] "
