"""Repository hygiene checks: line endings, path indirection, and CI/local-runner sync."""

from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
import tomllib
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
_CI_LITE_EXCLUDED_JOBS = ("e2e",)
_LOCAL_BACKEND_SETUP_ACTION = "./.github/actions/setup-backend"
_DOCKER_NODE_RE = re.compile(r"^FROM node:(\S+) AS ui-build$", re.MULTILINE)
_DOCKER_PYTHON_RE = re.compile(r"^FROM python:(\S+)$", re.MULTILINE)
_ACTION_INPUT_EQ_RE = re.compile(
    r"^\${{\s*inputs\.([A-Za-z0-9_-]+)\s*==\s*'([^']+)'\s*}}$"
)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _load_ci_workflow() -> dict[str, object]:
    return _load_yaml_mapping(ROOT / ".github" / "workflows" / "ci.yml")


def _load_ci_parallel_module():
    module_path = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    spec = importlib.util.spec_from_file_location("ci_parallel_local", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_required_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _makefile_job_list(var_name: str) -> list[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(var_name)}\s*[:+?]?=\s*(.+)$", text, re.MULTILINE)
    if match is None:
        return []
    tokens = shlex.split(match.group(1))
    jobs: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index] != "--job" or index + 1 >= len(tokens):
            return []
        jobs.append(tokens[index + 1])
        index += 2
    return jobs


def _load_server_pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "apps" / "server" / "pyproject.toml").read_text())


def _docker_base_tag(pattern: re.Pattern[str], dockerfile_text: str) -> str | None:
    match = pattern.search(dockerfile_text)
    return match.group(1) if match else None


def _version_core(image_tag: str) -> str:
    return image_tag.split("-", 1)[0]


def _validate_server_dockerfile(
    *,
    path: Path,
    label: str,
    expected_python: str,
    expected_node: str | None,
    require_ui_stage: bool,
) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        errors.append(f"Missing {label} at {path.relative_to(ROOT)}.")
        return errors

    dockerfile_text = path.read_text(encoding="utf-8")

    docker_python = _docker_base_tag(_DOCKER_PYTHON_RE, dockerfile_text)
    if docker_python is None:
        errors.append(f"{label} is missing the runtime python base image line.")
    elif _version_core(docker_python) != expected_python:
        errors.append(
            f"{label} runtime python tag {docker_python!r} does not match .python-version "
            f"{expected_python!r}."
        )

    docker_node = _docker_base_tag(_DOCKER_NODE_RE, dockerfile_text)
    if require_ui_stage:
        if docker_node is None:
            errors.append(f"{label} is missing the UI node base image line.")
        elif expected_node is not None and _version_core(docker_node) != expected_node:
            errors.append(
                f"{label} UI node tag {docker_node!r} does not match .nvmrc {expected_node!r}."
            )
    elif docker_node is not None:
        errors.append(
            f"{label} must stay backend-only and must not include a ui-build stage."
        )

    if '.get("optional-dependencies", {}).get("esp"' in dockerfile_text:
        errors.append(f"{label} must not install the optional esp dependency group.")
    if "tomllib" in dockerfile_text or "subprocess.check_call" in dockerfile_text:
        errors.append(
            f"{label} must not parse pyproject.toml inline; let pip resolve /app/apps/server directly."
        )
    if "--no-deps /app/apps/server" in dockerfile_text:
        errors.append(f"{label} must not install /app/apps/server with --no-deps.")
    if "python -m pip install --no-cache-dir /app/apps/server" not in dockerfile_text:
        errors.append(f"{label} must install /app/apps/server directly with pip.")

    if not require_ui_stage and (
        "npm ci" in dockerfile_text
        or "npm run build" in dockerfile_text
        or "COPY --from=ui-build" in dockerfile_text
    ):
        errors.append(
            f"{label} must stay backend-only and must not build or copy UI assets."
        )
    if not require_ui_stage and "VIBESENSOR_SERVE_STATIC=0" not in dockerfile_text:
        errors.append(f"{label} must disable static UI serving.")

    return errors


def _project_dependency_spec(requirement_name: str) -> str | None:
    pyproject = _load_server_pyproject()
    project = pyproject.get("project")
    if not isinstance(project, Mapping):
        return None
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return None
    prefix = f"{requirement_name}>="
    for dependency in dependencies:
        if isinstance(dependency, str) and dependency.startswith(prefix):
            return dependency
    return None


def _build_system_requirement_spec(requirement_name: str) -> str | None:
    pyproject = _load_server_pyproject()
    build_system = pyproject.get("build-system")
    if not isinstance(build_system, Mapping):
        return None
    requires = build_system.get("requires")
    if not isinstance(requires, list):
        return None
    prefix = f"{requirement_name}>="
    for requirement in requires:
        if isinstance(requirement, str) and requirement.startswith(prefix):
            return requirement
    return None


def _platformio_package_pin(package_name: str) -> str | None:
    platformio_path = ROOT / "firmware" / "esp" / "platformio.ini"
    if not platformio_path.exists():
        return None
    in_platform_packages = False
    for raw_line in platformio_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_platform_packages = False
            continue
        if line.startswith("platform_packages"):
            in_platform_packages = True
            _, _, value = line.partition("=")
            candidate = value.strip()
            if candidate.startswith(f"{package_name}@"):
                return candidate.split("@", 1)[1].strip()
            continue
        if in_platform_packages:
            if "=" in raw_line and not raw_line.startswith((" ", "\t")):
                in_platform_packages = False
                continue
            if line.startswith(f"{package_name}@"):
                return line.split("@", 1)[1].strip()
    return None


def _lower_bound_major(requirement_spec: str) -> int | None:
    match = re.search(r">=?\s*([0-9]+)", requirement_spec)
    return int(match.group(1)) if match else None


def _upper_bound_major(requirement_spec: str) -> int | None:
    match = re.search(r"<\s*([0-9]+)", requirement_spec)
    return int(match.group(1)) if match else None


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


def _normalized_ci_steps(raw_step: Mapping[str, object]) -> list[dict[str, object]]:
    run = raw_step.get("run")
    if isinstance(run, str):
        return [
            {
                "name": raw_step.get("name", ""),
                "commands": _normalize_ci_step_commands(raw_step),
            }
        ]

    uses = raw_step.get("uses")
    if not isinstance(uses, str):
        return []
    action_file = _local_action_file(uses)
    if action_file is None:
        return []
    action = _load_yaml_mapping(action_file)
    runs = action.get("runs")
    if not isinstance(runs, Mapping):
        return []
    raw_steps = runs.get("steps")
    if not isinstance(raw_steps, list):
        return []
    raw_with = raw_step.get("with")
    action_inputs = _resolved_action_inputs(
        action, raw_with if isinstance(raw_with, Mapping) else None
    )
    normalized_steps: list[dict[str, object]] = []
    for action_step in raw_steps:
        if not isinstance(action_step, Mapping):
            continue
        if not _action_step_enabled(action_step, action_inputs):
            continue
        normalized_steps.extend(_normalized_ci_steps(action_step))
    return normalized_steps


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
            normalized_steps.extend(_normalized_ci_steps(raw_step))
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


def _ci_commands_named(steps: list[dict[str, object]], names: set[str]) -> list[str]:
    collected: list[str] = []
    for step in steps:
        if step.get("name") not in names:
            continue
        commands = step.get("commands")
        if isinstance(commands, list):
            collected.extend(str(command) for command in commands)
    return collected


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
        install_commands = _ci_commands_named(
            ci_steps.get(job_name, []), {"Install dependencies"}
        )
        if _pip_install_markers(install_commands) != common_backend_markers:
            errors.append(
                f"{job_name} install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={common_bootstrap[:2]!r}"
            )

    ui_bootstrap_commands = common_bootstrap[2:]
    for job_name in _MIRRORED_UI_INSTALL_JOBS:
        install_commands = _ci_commands_named(
            ci_steps.get(job_name, []), {"Install UI dependencies"}
        )
        if install_commands != ui_bootstrap_commands:
            errors.append(
                f"{job_name} UI install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={ui_bootstrap_commands!r}"
            )

    firmware_install_commands = _ci_commands_named(
        ci_steps.get(_FIRMWARE_INSTALL_JOB, []),
        {"Install dependencies", "Install PlatformIO dependencies"},
    )
    if _pip_install_markers(firmware_install_commands) != _pip_install_markers(
        firmware_bootstrap[:3]
    ):
        errors.append(
            f"{_FIRMWARE_INSTALL_JOB} install commands drifted from local bootstrap: "
            f"ci={firmware_install_commands!r} local={firmware_bootstrap[:3]!r}"
        )

    install_step_names = {
        "Install dependencies",
        "Install PlatformIO dependencies",
        "Install UI dependencies",
    }
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


def check_ci_lite_job_sync() -> list[str]:
    """Verify Makefile CI_LITE_JOBS tracks the non-Docker CI job subset."""
    ci_jobs = list(_ci_run_steps_by_job())
    expected = [
        job_name for job_name in ci_jobs if job_name not in _CI_LITE_EXCLUDED_JOBS
    ]
    actual = _makefile_job_list("CI_LITE_JOBS")
    if not actual:
        return ["Makefile CI_LITE_JOBS is missing or unparsable."]
    if actual == expected:
        return []
    return [
        "Makefile CI_LITE_JOBS drifted from the non-Docker CI subset: "
        f"expected={expected!r} actual={actual!r}"
    ]


def check_docker_ci_dependency_hygiene() -> list[str]:
    errors: list[str] = []

    expected_python = _read_required_text(ROOT / ".python-version")
    expected_node = _read_required_text(ROOT / ".nvmrc")
    errors.extend(
        _validate_server_dockerfile(
            path=ROOT / "apps" / "server" / "Dockerfile",
            label="Production Dockerfile",
            expected_python=expected_python,
            expected_node=expected_node,
            require_ui_stage=True,
        )
    )
    errors.extend(
        _validate_server_dockerfile(
            path=ROOT / "apps" / "server" / "Dockerfile.e2e",
            label="E2E Dockerfile",
            expected_python=expected_python,
            expected_node=None,
            require_ui_stage=False,
        )
    )

    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        errors.append("CI workflow is missing its jobs mapping.")
        return errors

    action_file = ROOT / ".github" / "actions" / "setup-backend" / "action.yml"
    if not action_file.exists():
        errors.append(
            "Missing shared backend setup composite action at .github/actions/setup-backend/action.yml."
        )

    for job_name in (*_MIRRORED_BACKEND_INSTALL_JOBS, _FIRMWARE_INSTALL_JOB):
        raw_job = jobs.get(job_name)
        if not isinstance(raw_job, Mapping):
            continue
        raw_steps = raw_job.get("steps")
        if not isinstance(raw_steps, list):
            continue
        setup_step = next(
            (
                step
                for step in raw_steps
                if isinstance(step, Mapping)
                and step.get("uses") == _LOCAL_BACKEND_SETUP_ACTION
            ),
            None,
        )
        if setup_step is None:
            errors.append(
                f"{job_name} must use {_LOCAL_BACKEND_SETUP_ACTION} for shared backend setup."
            )
            continue
        if any(
            isinstance(step, Mapping) and step.get("uses") == "actions/setup-python@v5"
            for step in raw_steps
        ):
            errors.append(
                f"{job_name} should rely on {_LOCAL_BACKEND_SETUP_ACTION} instead of duplicating actions/setup-python."
            )
        if job_name == _FIRMWARE_INSTALL_JOB:
            raw_with = setup_step.get("with")
            include_platformio = ""
            if isinstance(raw_with, Mapping):
                raw_value = raw_with.get("include-platformio")
                if raw_value is not None:
                    include_platformio = str(raw_value)
            if include_platformio != "true":
                errors.append(
                    "firmware-native-tests must enable include-platformio on the shared backend setup action."
                )

    ui_smoke = jobs.get("ui-smoke") if isinstance(jobs, Mapping) else None
    steps = ui_smoke.get("steps") if isinstance(ui_smoke, Mapping) else None
    playwright_cache_ok = False
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not uses.startswith("actions/cache@"):
                continue
            with_data = step.get("with")
            if not isinstance(with_data, Mapping):
                continue
            path = with_data.get("path")
            key = with_data.get("key")
            if (
                isinstance(path, str)
                and path.strip() == "~/.cache/ms-playwright"
                and isinstance(key, str)
                and "ms-playwright" in key
                and "package-lock.json" in key
            ):
                playwright_cache_ok = True
                break
    if not playwright_cache_ok:
        errors.append(
            "ui-smoke must cache ~/.cache/ms-playwright with a package-lock-based actions/cache key."
        )

    e2e_job = jobs.get("e2e") if isinstance(jobs, Mapping) else None
    steps: object = None
    prebuild_e2e_dockerfile_ok = False
    if not isinstance(e2e_job, Mapping):
        errors.append("CI workflow is missing the e2e job.")
    else:
        if e2e_job.get("needs") not in (None, []):
            errors.append("e2e must not declare job needs so it can start immediately.")

        steps = e2e_job.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                if step.get("name") != "Prebuild cached E2E image":
                    continue
                uses = step.get("uses")
                with_data = step.get("with")
                dockerfile = (
                    with_data.get("file") if isinstance(with_data, Mapping) else None
                )
                if (
                    isinstance(uses, str)
                    and uses.startswith("docker/build-push-action@")
                    and dockerfile == "apps/server/Dockerfile.e2e"
                ):
                    prebuild_e2e_dockerfile_ok = True
                    break
    if not prebuild_e2e_dockerfile_ok:
        errors.append(
            "e2e must prebuild its shared image from apps/server/Dockerfile.e2e."
        )

    e2e_duration_cache_ok = False
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not uses.startswith("actions/cache@"):
                continue
            with_data = step.get("with")
            if not isinstance(with_data, Mapping):
                continue
            path = with_data.get("path")
            key = with_data.get("key")
            restore_keys = with_data.get("restore-keys")
            if (
                isinstance(path, str)
                and path.strip() == "~/.cache/vibesensor/e2e-duration-cache.json"
                and isinstance(key, str)
                and "e2e-durations" in key
                and "run_e2e_parallel.py" in key
                and "tests_e2e" in key
                and "github.run_id" in key
                and isinstance(restore_keys, str)
                and "tests_e2e" in restore_keys
                and "${{ runner.os }}-e2e-durations-" in restore_keys
            ):
                e2e_duration_cache_ok = True
                break
    if not e2e_duration_cache_ok:
        errors.append(
            "e2e must cache ~/.cache/vibesensor/e2e-duration-cache.json with a "
            "restoreable actions/cache key tied to run_e2e_parallel.py, tests_e2e, and github.run_id."
        )

    numpy_spec = _project_dependency_spec("numpy")
    if numpy_spec is None:
        errors.append(
            "apps/server/pyproject.toml is missing the numpy runtime dependency."
        )
    else:
        lower_major = _lower_bound_major(numpy_spec)
        upper_major = _upper_bound_major(numpy_spec)
        if lower_major is None or upper_major is None:
            errors.append(
                f"NumPy dependency must declare explicit lower and upper bounds; found {numpy_spec!r}."
            )
        elif upper_major <= lower_major or upper_major > lower_major + 2:
            errors.append(
                "NumPy dependency must stay within at most two adjacent major versions; "
                f"found {numpy_spec!r}."
            )

    return errors


def check_dependency_reproducibility_hygiene() -> list[str]:
    errors: list[str] = []

    release_fetcher = (
        ROOT
        / "apps"
        / "server"
        / "vibesensor"
        / "use_cases"
        / "updates"
        / "releases"
        / "release_fetcher.py"
    ).read_text(encoding="utf-8")
    packaging_spec = _project_dependency_spec("packaging")
    if (
        "from packaging.version import Version" in release_fetcher
        and packaging_spec is None
    ):
        errors.append(
            "apps/server/pyproject.toml must declare packaging when release_fetcher imports packaging.version.Version."
        )

    setuptools_spec = _build_system_requirement_spec("setuptools")
    if setuptools_spec is None:
        errors.append(
            "apps/server/pyproject.toml build-system requires must declare setuptools."
        )
    elif "<" not in setuptools_spec:
        errors.append(
            f"apps/server/pyproject.toml build-system setuptools requirement must include an upper bound; found {setuptools_spec!r}."
        )

    wheel_spec = _build_system_requirement_spec("wheel")
    if wheel_spec is None:
        errors.append(
            "apps/server/pyproject.toml build-system requires must declare wheel."
        )
    elif ">=" not in wheel_spec or "<" not in wheel_spec:
        errors.append(
            "apps/server/pyproject.toml build-system wheel requirement must include "
            f"explicit lower and upper bounds; found {wheel_spec!r}."
        )

    websockets_spec = _project_dependency_spec("websockets")
    if websockets_spec is None:
        errors.append(
            "apps/server/pyproject.toml is missing the websockets runtime dependency."
        )
    else:
        lower_major = _lower_bound_major(websockets_spec)
        upper_major = _upper_bound_major(websockets_spec)
        if lower_major is None or upper_major is None:
            errors.append(
                "websockets dependency must declare explicit lower and upper bounds; "
                f"found {websockets_spec!r}."
            )
        elif upper_major != lower_major + 1:
            errors.append(
                "websockets dependency must stay within a single major version window; "
                f"found {websockets_spec!r}."
            )

    framework_pin = _platformio_package_pin("framework-arduinoespressif32")
    if framework_pin is None:
        errors.append(
            "firmware/esp/platformio.ini must pin framework-arduinoespressif32 via "
            "platform_packages."
        )
    elif framework_pin.startswith(("~", "^", "<", ">", "=")):
        errors.append(
            "firmware/esp/platformio.ini must pin framework-arduinoespressif32 to an "
            f"exact version; found {framework_pin!r}."
        )

    dependabot_path = ROOT / ".github" / "dependabot.yml"
    if not dependabot_path.exists():
        errors.append(
            "Missing .github/dependabot.yml for automated dependency updates."
        )
        return errors

    dependabot = _load_yaml_mapping(dependabot_path)
    raw_updates = dependabot.get("updates")
    if not isinstance(raw_updates, list):
        errors.append(".github/dependabot.yml must define an updates list.")
        return errors

    configured_updates: set[tuple[str, str]] = set()
    for item in raw_updates:
        if not isinstance(item, Mapping):
            continue
        ecosystem = item.get("package-ecosystem")
        directory = item.get("directory")
        if isinstance(ecosystem, str) and isinstance(directory, str):
            configured_updates.add((ecosystem, directory))

    required_updates = {
        ("pip", "/apps/server"),
        ("npm", "/apps/ui"),
        ("github-actions", "/"),
    }
    missing_updates = sorted(required_updates - configured_updates)
    if missing_updates:
        errors.append(
            ".github/dependabot.yml is missing required update entries: "
            f"{missing_updates}"
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

    ci_lite_sync_errors = check_ci_lite_job_sync()
    if ci_lite_sync_errors:
        print("CI lite job drift detected:")
        for item in ci_lite_sync_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Makefile CI_LITE_JOBS matches the non-Docker CI subset.")

    docker_ci_hygiene_errors = check_docker_ci_dependency_hygiene()
    if docker_ci_hygiene_errors:
        print("Docker/CI dependency hygiene drift detected:")
        for item in docker_ci_hygiene_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Docker/CI dependency hygiene checks passed.")

    dependency_repro_errors = check_dependency_reproducibility_hygiene()
    if dependency_repro_errors:
        print("Dependency reproducibility hygiene drift detected:")
        for item in dependency_repro_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Dependency reproducibility hygiene checks passed.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
