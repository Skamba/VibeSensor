"""Repository hygiene checks: line endings, path indirection, and CI/local-runner sync."""

from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

TEXT_EXTS = {
    ".py",
    ".js",
    ".css",
    ".html",
    ".md",
    ".yml",
    ".yaml",
    ".sh",
    ".service",
    ".toml",
    ".cpp",
    ".h",
}

_RELATIVE_POINTER_RE = re.compile(r"^(?:\./|\.\./)\S+$")
_PY_PATH_HACK_RE = re.compile(r"sys\.path\.(?:insert|append)\(|PYTHONPATH=")


def _git_tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    ).stdout
    return [ROOT / p.decode("utf-8", errors="replace") for p in out.split(b"\x00") if p]


def check_line_endings() -> list[str]:
    offenders: list[str] = []
    for path in _git_tracked_files():
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\r\n" in data:
            offenders.append(str(path.relative_to(ROOT)))
    return offenders


def _is_pointer_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) == 1 and bool(_RELATIVE_POINTER_RE.fullmatch(lines[0]))


def check_path_indirections() -> tuple[list[str], list[str]]:
    pointer_files: list[str] = []
    python_path_hacks: list[str] = []
    for path in _git_tracked_files():
        if ".git" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        if _is_pointer_file(path):
            pointer_files.append(rel)
        if path.suffix == ".py" and rel != "tools/dev/check_hygiene.py":
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _PY_PATH_HACK_RE.search(text):
                python_path_hacks.append(rel)
    return pointer_files, python_path_hacks


_MIRRORED_UI_INSTALL_JOBS = ("frontend-typecheck", "ui-smoke")
_MIRRORED_BACKEND_INSTALL_JOBS = (
    "backend-quality",
    "backend-typecheck",
    "backend-tests",
    "e2e",
)
_FIRMWARE_INSTALL_JOB = "firmware-native-tests"


def _load_ci_workflow() -> dict[str, object]:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "ci.yml").read_text())
    return workflow if isinstance(workflow, dict) else {}


def _load_ci_parallel_module():
    module_path = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    spec = importlib.util.spec_from_file_location("ci_parallel_local", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _normalize_python_token(token: str) -> str:
    return "python" if Path(token).name.startswith("python") else token


def _normalize_tokenized_command(tokens: list[str]) -> str:
    if not tokens:
        return ""
    normalized = list(tokens)
    normalized[0] = _normalize_python_token(normalized[0])
    return shlex.join(normalized)


def _normalize_shell_command(command: str) -> str:
    tokens = shlex.split(command)
    if "&&" not in tokens:
        return _normalize_tokenized_command(tokens)

    parts: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token == "&&":
            if current:
                parts.append(_normalize_tokenized_command(current))
                current = []
            continue
        current.append(token)
    if current:
        parts.append(_normalize_tokenized_command(current))
    return " && ".join(parts)


def _normalize_env(env: Mapping[str, object] | None) -> str:
    if not env:
        return ""
    parts = [f"{key}={env[key]}" for key in sorted(env)]
    return f"env {' '.join(parts)} "


def _normalize_ci_step_commands(step: Mapping[str, object]) -> list[str]:
    run = step.get("run")
    if not isinstance(run, str):
        return []
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
    return commands


def _ci_run_steps_by_job() -> dict[str, list[dict[str, object]]]:
    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        return {}

    result: dict[str, list[dict[str, object]]] = {}
    for job_name, job_body in jobs.items():
        if not isinstance(job_name, str) or not isinstance(job_body, Mapping):
            continue
        raw_steps = job_body.get("steps")
        if not isinstance(raw_steps, list):
            continue
        normalized_steps: list[dict[str, object]] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                continue
            run = raw_step.get("run")
            if not isinstance(run, str):
                continue
            normalized_steps.append(
                {
                    "name": raw_step.get("name", ""),
                    "commands": _normalize_ci_step_commands(raw_step),
                }
            )
        result[job_name] = normalized_steps
    return result


def _normalize_local_step(step) -> str:
    cwd_prefix = ""
    if step.cwd != ROOT:
        cwd_prefix = f"cd {step.cwd.relative_to(ROOT).as_posix()} && "
    env_prefix = _normalize_env(step.env)
    return f"{cwd_prefix}{env_prefix}{_normalize_tokenized_command(step.cmd)}"


def _local_runner_commands() -> tuple[dict[str, list[str]], list[str], list[str]]:
    ci_parallel = _load_ci_parallel_module()
    common_bootstrap = [
        _normalize_local_step(step)
        for step in ci_parallel._bootstrap_steps(  # type: ignore[attr-defined]
            sys.executable,
            True,
            include_platformio=False,
        )
    ]
    firmware_bootstrap = [
        _normalize_local_step(step)
        for step in ci_parallel._bootstrap_steps(  # type: ignore[attr-defined]
            sys.executable,
            True,
            include_platformio=True,
        )
    ]
    job_steps = {
        name: [_normalize_local_step(step) for step in steps]
        for name, steps in ci_parallel._job_steps(sys.executable).items()  # type: ignore[attr-defined]
    }
    return job_steps, common_bootstrap, firmware_bootstrap


def _pip_install_markers(commands: list[str]) -> set[str]:
    markers: set[str] = set()
    for command in commands:
        tokens = shlex.split(command)
        if len(tokens) < 5:
            continue
        if tokens[1:4] != ["-m", "pip", "install"]:
            continue
        args = tokens[4:]
        i = 0
        while i < len(args):
            token = args[i]
            if token == "--upgrade" and i + 1 < len(args):
                markers.add(f"{token} {args[i + 1]}")
                i += 2
                continue
            if token == "-e" and i + 1 < len(args):
                markers.add(f"{token} {args[i + 1]}")
                i += 2
                continue
            if not token.startswith("-"):
                markers.add(token)
            i += 1
    return markers


def _ci_step_named(steps: list[dict[str, object]], name: str) -> list[str]:
    for step in steps:
        if step.get("name") == name:
            commands = step.get("commands")
            if isinstance(commands, list):
                return [str(command) for command in commands]
    return []


def check_ci_job_sync() -> list[str]:
    """Verify run_ci_parallel.py job names match ci.yml job names."""
    ci_yml = ROOT / ".github" / "workflows" / "ci.yml"
    parallel_py = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    errors: list[str] = []
    if not ci_yml.exists() or not parallel_py.exists():
        return errors

    ci_jobs = set(_ci_run_steps_by_job())
    parallel_jobs = set(_local_runner_commands()[0])

    only_ci = ci_jobs - parallel_jobs
    only_parallel = parallel_jobs - ci_jobs
    if only_ci:
        errors.append(f"CI jobs not mirrored in run_ci_parallel.py: {sorted(only_ci)}")
    if only_parallel:
        errors.append(f"run_ci_parallel.py jobs not in ci.yml: {sorted(only_parallel)}")
    return errors


def check_ci_command_sync() -> list[str]:
    """Verify mirrored CI run commands stay aligned with run_ci_parallel.py."""
    ci_steps = _ci_run_steps_by_job()
    local_jobs, common_bootstrap, firmware_bootstrap = _local_runner_commands()
    errors: list[str] = []

    common_backend_markers = _pip_install_markers(common_bootstrap[:2])
    for job_name in _MIRRORED_BACKEND_INSTALL_JOBS:
        install_commands = _ci_step_named(
            ci_steps.get(job_name, []), "Install dependencies"
        )
        if _pip_install_markers(install_commands) != common_backend_markers:
            errors.append(
                f"{job_name} install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={common_bootstrap[:2]!r}"
            )

    ui_bootstrap_commands = common_bootstrap[2:]
    for job_name in _MIRRORED_UI_INSTALL_JOBS:
        install_commands = _ci_step_named(
            ci_steps.get(job_name, []), "Install UI dependencies"
        )
        if install_commands != ui_bootstrap_commands:
            errors.append(
                f"{job_name} UI install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={ui_bootstrap_commands!r}"
            )

    firmware_install_commands = _ci_step_named(
        ci_steps.get(_FIRMWARE_INSTALL_JOB, []),
        "Install dependencies",
    )
    if _pip_install_markers(firmware_install_commands) != _pip_install_markers(
        firmware_bootstrap[:3]
    ):
        errors.append(
            f"{_FIRMWARE_INSTALL_JOB} install commands drifted from local bootstrap: "
            f"ci={firmware_install_commands!r} local={firmware_bootstrap[:3]!r}"
        )

    install_step_names = {"Install dependencies", "Install UI dependencies"}
    for job_name, steps in ci_steps.items():
        expected_commands: list[str] = []
        for step in steps:
            if step.get("name") in install_step_names:
                continue
            commands = step.get("commands")
            if isinstance(commands, list):
                expected_commands.extend(str(command) for command in commands)
        local_commands = local_jobs.get(job_name, [])
        if expected_commands != local_commands:
            errors.append(
                f"{job_name} run commands drifted from run_ci_parallel.py: "
                f"ci={expected_commands!r} local={local_commands!r}"
            )

    return errors


def main() -> int:
    failures = 0

    crlf = check_line_endings()
    if crlf:
        print("CRLF line endings found:")
        for item in crlf:
            print(f"  - {item}")
        failures += 1
    else:
        print("Line ending check passed (LF-only for tracked text files).")

    pointer_files, path_hacks = check_path_indirections()
    if pointer_files or path_hacks:
        if pointer_files:
            print("Pointer-style files found:")
            for item in pointer_files:
                print(f"  - {item}")
        if path_hacks:
            print("sys.path/PYTHONPATH hacks found in Python files:")
            for item in path_hacks:
                print(f"  - {item}")
        failures += 1
    else:
        print("No path-indirection files or sys.path/PYTHONPATH hacks found.")

    ci_sync_errors = check_ci_job_sync()
    if ci_sync_errors:
        print("CI job sync drift detected:")
        for item in ci_sync_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("CI job names in sync between ci.yml and run_ci_parallel.py.")

    ci_command_sync_errors = check_ci_command_sync()
    if ci_command_sync_errors:
        print("CI command sync drift detected:")
        for item in ci_command_sync_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("CI commands in sync between ci.yml and run_ci_parallel.py.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
