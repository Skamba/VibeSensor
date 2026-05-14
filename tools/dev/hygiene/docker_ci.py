# ruff: noqa: F403,F405
"""Docker and CI dependency hygiene checks."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path


from ._shared import *
from .ci_workflow import (
    _extend_missing_text_requirements,
    _extend_step_requirement_errors,
    _load_action_steps,
    _load_ci_workflow,
    _normalize_env,
    _normalize_shell_command,
    _workflow_job_needs,
    _workflow_step_matches,
)
from .runtime_policy import (
    _lower_bound_major,
    _project_dependency_spec,
    _upper_bound_major,
)


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
        if "ENV PYTHON=/usr/bin/python3" not in dockerfile_text:
            errors.append(
                f"{label} UI build stage must pass an explicit Python path into npm contract sync."
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


def _validate_ui_dev_compose_node_image(expected_node: str) -> list[str]:
    compose_path = ROOT / "docker-compose.dev.yml"
    if not compose_path.exists():
        return ["Missing Docker dev override at docker-compose.dev.yml."]

    compose = _load_yaml_mapping(compose_path)
    services = compose.get("services")
    if not isinstance(services, Mapping):
        return ["docker-compose.dev.yml is missing its services mapping."]
    ui_service = services.get("vibesensor-ui-dev")
    if not isinstance(ui_service, Mapping):
        return ["docker-compose.dev.yml is missing the vibesensor-ui-dev service."]
    image = ui_service.get("image")
    if not isinstance(image, str):
        return ["docker-compose.dev.yml:vibesensor-ui-dev must declare a node image."]

    match = re.fullmatch(r"node:(\S+)", image.strip())
    if match is None:
        return ["docker-compose.dev.yml:vibesensor-ui-dev must use a node:<tag> image."]
    actual_node = match.group(1)
    if _version_core(actual_node) != expected_node:
        return [
            "docker-compose.dev.yml:vibesensor-ui-dev image "
            f"{actual_node!r} does not match .nvmrc {expected_node!r}."
        ]
    return []


def _check_setup_backend_cache_contract(
    backend_action_steps: list[object],
) -> list[str]:
    errors: list[str] = []
    cache_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping)
            and step.get("id") == "backend-venv-cache"
            and step.get("uses") == "actions/cache@v5"
        ),
        None,
    )
    if cache_step is None:
        errors.append(
            ".github/actions/setup-backend/action.yml must restore a repo-local backend virtualenv via actions/cache@v5."
        )
    else:
        raw_with = cache_step.get("with")
        if not isinstance(raw_with, Mapping):
            errors.append(
                ".github/actions/setup-backend/action.yml backend virtualenv cache step must define a path and key."
            )
        else:
            path = raw_with.get("path")
            key = raw_with.get("key")
            restore_keys = raw_with.get("restore-keys")
            if path != ".venv":
                errors.append(
                    ".github/actions/setup-backend/action.yml must cache the repo-local .venv path."
                )
            if not isinstance(key, str) or any(
                token not in key
                for token in (
                    "backend-venv",
                    "runner.os",
                    "runner.arch",
                    ".python-version",
                    "apps/server/pyproject.toml",
                    ".github/actions/setup-python/action.yml",
                    ".github/actions/setup-backend/action.yml",
                )
            ):
                errors.append(
                    ".github/actions/setup-backend/action.yml backend virtualenv cache key must include OS/arch plus .python-version, apps/server/pyproject.toml, and both setup action files."
                )
            if restore_keys is not None:
                errors.append(
                    ".github/actions/setup-backend/action.yml backend virtualenv cache must not use restore-keys that could hide dependency changes."
                )

    hit_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping)
            and step.get("name") == "Report backend virtualenv cache hit"
        ),
        None,
    )
    if (
        hit_step is None
        or hit_step.get("if")
        != "${{ steps.backend-venv-cache.outputs.cache-hit == 'true' }}"
    ):
        errors.append(
            ".github/actions/setup-backend/action.yml must report backend virtualenv cache hits."
        )
    miss_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping)
            and step.get("name") == "Report backend virtualenv cache miss"
        ),
        None,
    )
    if (
        miss_step is None
        or miss_step.get("if")
        != "${{ steps.backend-venv-cache.outputs.cache-hit != 'true' }}"
    ):
        errors.append(
            ".github/actions/setup-backend/action.yml must report backend virtualenv cache misses."
        )
    return errors


def _check_setup_backend_action_contract() -> list[str]:
    errors: list[str] = []
    action_file = ROOT / ".github" / "actions" / "setup-backend" / "action.yml"
    if not action_file.exists():
        return [
            "Missing shared backend setup composite action at .github/actions/setup-backend/action.yml."
        ]

    backend_action = _load_yaml_mapping(action_file)
    outputs = backend_action.get("outputs")
    if (
        not isinstance(outputs, Mapping)
        or not isinstance(outputs.get("python-path"), Mapping)
        or outputs["python-path"].get("value")
        != "${{ steps.backend-python.outputs.python-path }}"
    ):
        errors.append(
            ".github/actions/setup-backend/action.yml must expose outputs.python-path from the backend-python step."
        )

    backend_action_steps = _load_action_steps(action_file)
    _extend_step_requirement_errors(
        errors,
        backend_action_steps,
        (
            WorkflowStepRequirement(
                uses=_LOCAL_PYTHON_SETUP_ACTION,
                error_message=(
                    ".github/actions/setup-backend/action.yml must delegate Python setup to "
                    f"{_LOCAL_PYTHON_SETUP_ACTION}."
                ),
            ),
            WorkflowStepRequirement(
                uses_prefix="actions/setup-python@",
                forbidden=True,
                error_message=(
                    ".github/actions/setup-backend/action.yml must not call actions/setup-python directly."
                ),
            ),
        ),
    )
    errors.extend(_check_setup_backend_cache_contract(backend_action_steps))

    retry_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping) and step.get("name") == "Prepare retry helper"
        ),
        None,
    )
    retry_run = retry_step.get("run") if isinstance(retry_step, Mapping) else None
    if not isinstance(retry_run, str) or retry_run.count("retry_command()") != 1:
        errors.append(
            ".github/actions/setup-backend/action.yml must define a single retry_command helper for network installs."
        )

    install_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping) and step.get("name") == "Install dependencies"
        ),
        None,
    )
    if install_step is None:
        errors.append(
            ".github/actions/setup-backend/action.yml is missing its Install dependencies step."
        )
    else:
        raw_if = install_step.get("if")
        run = install_step.get("run")
        if raw_if != "${{ steps.backend-venv-cache.outputs.cache-hit != 'true' }}":
            errors.append(
                ".github/actions/setup-backend/action.yml must only install backend dependencies when the backend virtualenv cache misses."
            )
        if not isinstance(run, str) or any(
            needle not in run
            for needle in (
                'source "${RUNNER_TEMP}/setup-backend-retry.sh"',
                "rm -rf .venv",
                'retry_command 3 "${{ steps.setup-python.outputs.python-path }}" -m venv .venv',
                "retry_command 3 .venv/bin/python -m pip install --upgrade pip",
                'retry_command 3 .venv/bin/python -m pip install -e "./apps/server[dev]"',
            )
        ):
            errors.append(
                ".github/actions/setup-backend/action.yml Install dependencies step must source the retry helper, recreate .venv from the configured Python runtime, and install the editable backend dev environment into it."
            )

    backend_python_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping) and step.get("id") == "backend-python"
        ),
        None,
    )
    if backend_python_step is None:
        errors.append(
            ".github/actions/setup-backend/action.yml must expose the cached backend virtualenv interpreter via a backend-python step."
        )
    else:
        run = backend_python_step.get("run")
        if not isinstance(run, str) or any(
            needle not in run
            for needle in (
                "${GITHUB_WORKSPACE}/.venv/bin/python",
                'echo "${GITHUB_WORKSPACE}/.venv/bin" >> "${GITHUB_PATH}"',
                'echo "VIRTUAL_ENV=${GITHUB_WORKSPACE}/.venv" >> "${GITHUB_ENV}"',
                'echo "python-path=${backend_python}" >> "${GITHUB_OUTPUT}"',
            )
        ):
            errors.append(
                ".github/actions/setup-backend/action.yml backend-python step must publish the cached .venv interpreter and prepend it to GITHUB_PATH."
            )

    platformio_step = next(
        (
            step
            for step in backend_action_steps
            if isinstance(step, Mapping)
            and step.get("name") == "Install PlatformIO dependencies"
        ),
        None,
    )
    platformio_run = (
        platformio_step.get("run") if isinstance(platformio_step, Mapping) else None
    )
    if (
        platformio_step is None
        or platformio_step.get("if") != "${{ inputs.include-platformio == 'true' }}"
        or not isinstance(platformio_run, str)
        or 'source "${RUNNER_TEMP}/setup-backend-retry.sh"' not in platformio_run
        or 'retry_command 3 "${{ steps.backend-python.outputs.python-path }}" -m pip install "platformio>=6,<7"'
        not in platformio_run
    ):
        errors.append(
            ".github/actions/setup-backend/action.yml must install PlatformIO only when requested and through the configured backend Python with retry_command."
        )

    return errors


def check_docker_dev_workflow_hygiene() -> list[str]:
    errors: list[str] = []

    package_json = json.loads(
        (ROOT / "apps/ui/package.json").read_text(encoding="utf-8")
    )
    scripts = package_json.get("scripts")
    if not isinstance(scripts, Mapping):
        return ["apps/ui/package.json must define a scripts mapping."]
    expected_scripts = {
        "dev:docker": "sh ./dev-docker.sh",
        "lint:unused": "knip --config knip.jsonc",
        "format:check": "biome check . --linter-enabled=false --assist-enabled=false",
    }
    for script_name, expected in expected_scripts.items():
        if scripts.get(script_name) != expected:
            errors.append(
                f"apps/ui/package.json script {script_name!r} must stay {expected!r}."
            )

    makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    if (
        "dev:" not in makefile_text
        or "docker-compose.dev.yml up --build" not in makefile_text
    ):
        errors.append(
            "Makefile dev target must start the source-mounted Docker dev stack with docker-compose.dev.yml."
        )
    if _UI_BOOTSTRAP_HELPER_WORKFLOW_CMD not in makefile_text:
        errors.append(
            "Makefile setup must reuse tools/ui/ensure_ui_bootstrap.mjs for UI dependencies."
        )
    if "cd $(UI_DIR) && npm ci" in makefile_text:
        errors.append("Makefile setup must not bypass the shared UI bootstrap helper.")
    if 'cd $(UI_DIR) && PYTHON="$$PYTHON" npm run test:unit' not in makefile_text:
        errors.append(
            "Makefile ui-test target must run the UI unit suite from apps/ui."
        )

    compose = _load_yaml_mapping(ROOT / "docker-compose.dev.yml")
    services = compose.get("services")
    ui_service = (
        services.get("vibesensor-ui-dev") if isinstance(services, Mapping) else None
    )
    if not isinstance(ui_service, Mapping):
        errors.append("docker-compose.dev.yml must define services.vibesensor-ui-dev.")
        return errors
    if ui_service.get("command") != [
        "npm",
        "run",
        "dev:docker",
        "--",
        "--host",
        "0.0.0.0",
        "--port",
        "5173",
    ]:
        errors.append(
            "docker-compose.dev.yml vibesensor-ui-dev must run npm run dev:docker on 0.0.0.0:5173."
        )

    healthcheck = ui_service.get("healthcheck")
    test_command = healthcheck.get("test") if isinstance(healthcheck, Mapping) else None
    if (
        not isinstance(test_command, list)
        or test_command[:3] != ["CMD", "node", "-e"]
        or not any(
            isinstance(token, str) and "127.0.0.1:5173/" in token
            for token in test_command
        )
    ):
        errors.append(
            "docker-compose.dev.yml vibesensor-ui-dev healthcheck must probe the Vite dev server on 127.0.0.1:5173."
        )
    if not isinstance(healthcheck, Mapping) or healthcheck.get("start_period") != "75s":
        errors.append(
            "docker-compose.dev.yml vibesensor-ui-dev healthcheck must keep a 75s start period."
        )
    return errors


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
    errors.extend(_validate_ui_dev_compose_node_image(expected_node))

    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        errors.append("CI workflow is missing its jobs mapping.")
        return errors

    python_action_file = ROOT / ".github" / "actions" / "setup-python" / "action.yml"
    if not python_action_file.exists():
        errors.append(
            "Missing shared GitHub Actions Python setup action at .github/actions/setup-python/action.yml."
        )
    else:
        python_action_steps = _load_action_steps(python_action_file)
        setup_step = next(
            (
                step
                for step in python_action_steps
                if _workflow_step_matches(
                    step,
                    WorkflowStepRequirement(
                        uses_prefix="actions/setup-python@",
                        error_message="",
                    ),
                )
            ),
            None,
        )
        if setup_step is None:
            errors.append(
                ".github/actions/setup-python/action.yml must wrap actions/setup-python."
            )
        else:
            uses = setup_step.get("uses")
            if uses != "actions/setup-python@v6":
                errors.append(
                    ".github/actions/setup-python/action.yml must pin actions/setup-python@v6."
                )
            raw_with = setup_step.get("with")
            if not isinstance(raw_with, Mapping):
                errors.append(
                    ".github/actions/setup-python/action.yml must configure python-version-file and pip caching."
                )
            else:
                if raw_with.get("python-version-file") != ".python-version":
                    errors.append(
                        ".github/actions/setup-python/action.yml must resolve Python from .python-version."
                    )
                if raw_with.get("cache") != "pip":
                    errors.append(
                        ".github/actions/setup-python/action.yml must enable pip caching."
                    )
                if (
                    raw_with.get("cache-dependency-path")
                    != "apps/server/pyproject.toml"
                ):
                    errors.append(
                        ".github/actions/setup-python/action.yml must cache against apps/server/pyproject.toml."
                    )

    errors.extend(_check_setup_backend_action_contract())

    if "backend-quality" in jobs:
        errors.append(
            "CI workflow must not define a monolithic backend-quality job; keep the focused quality jobs split by concern."
        )
    missing_quality_jobs = [
        job_name for job_name in _BACKEND_QUALITY_JOBS if job_name not in jobs
    ]
    if missing_quality_jobs:
        errors.append(
            f"CI workflow is missing split quality jobs: {missing_quality_jobs}"
        )
    if _CI_SCOPE_JOB not in jobs:
        errors.append("CI workflow is missing the ci-scope job for path-aware gating.")
    release_smoke = jobs.get("release-smoke")
    if (
        isinstance(release_smoke, Mapping)
        and _workflow_job_needs(release_smoke) != _RELEASE_SMOKE_QUALITY_NEEDS
    ):
        errors.append(
            "release-smoke must depend on ci-scope, the split quality jobs, backend-typecheck, frontend-quality, frontend-typecheck, and ui-build-artifact."
        )
    ui_build_artifact = jobs.get(_UI_BUILD_ARTIFACT_JOB)
    if (
        isinstance(ui_build_artifact, Mapping)
        and _workflow_job_needs(ui_build_artifact) != _UI_BUILD_ARTIFACT_NEEDS
    ):
        errors.append(
            "ui-build-artifact must depend on ci-scope and frontend-typecheck."
        )
    firmware_job = jobs.get(_FIRMWARE_INSTALL_JOB)
    if (
        isinstance(firmware_job, Mapping)
        and _workflow_job_needs(firmware_job) != _FIRMWARE_NEEDS
    ):
        errors.append(
            "firmware-native-tests must depend on ci-scope plus the split quality jobs."
        )
    ui_smoke = jobs.get("ui-smoke")
    if (
        isinstance(ui_smoke, Mapping)
        and _workflow_job_needs(ui_smoke) != _UI_SMOKE_NEEDS
    ):
        errors.append("ui-smoke must depend on ci-scope and frontend-typecheck.")

    for job_name in (
        *_BACKEND_QUALITY_JOBS,
        "backend-typecheck",
        _FRONTEND_QUALITY_JOB,
        _FRONTEND_TYPECHECK_JOB,
    ):
        raw_job = jobs.get(job_name)
        if (
            isinstance(raw_job, Mapping)
            and _workflow_job_needs(raw_job) != _CI_SCOPE_ONLY_NEEDS
        ):
            errors.append(
                f"{job_name} must depend only on ci-scope for path-aware gating."
            )

    for job_name in (*_BACKEND_SETUP_JOBS, _FIRMWARE_INSTALL_JOB):
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

    workflow_dir = ROOT / ".github" / "workflows"
    for workflow_path in sorted(workflow_dir.glob("*.yml")):
        workflow = _load_yaml_mapping(workflow_path)
        workflow_jobs = workflow.get("jobs")
        if not isinstance(workflow_jobs, Mapping):
            continue
        rel_workflow_path = workflow_path.relative_to(ROOT)
        for job_name, raw_job in workflow_jobs.items():
            if not isinstance(raw_job, Mapping):
                continue
            raw_steps = raw_job.get("steps")
            if not isinstance(raw_steps, list):
                continue
            for step in raw_steps:
                if not isinstance(step, Mapping):
                    continue
                uses = step.get("uses")
                if isinstance(uses, str) and uses.startswith("actions/setup-python@"):
                    errors.append(
                        f"{rel_workflow_path}:{job_name} must use {_LOCAL_PYTHON_SETUP_ACTION} "
                        f"or {_LOCAL_BACKEND_SETUP_ACTION} instead of direct {uses}."
                    )

    runtime_support_matrix = (ROOT / "docs" / "runtime_support_matrix.md").read_text(
        encoding="utf-8"
    )
    _extend_missing_text_requirements(
        errors,
        runtime_support_matrix,
        (
            TextRequirement(
                needle=".github/actions/setup-python/action.yml",
                error_message=(
                    "docs/runtime_support_matrix.md must point GitHub Actions maintainers to "
                    ".github/actions/setup-python/action.yml."
                ),
            ),
            TextRequirement(
                needle=".github/actions/setup-backend/action.yml",
                error_message=(
                    "docs/runtime_support_matrix.md must point GitHub Actions maintainers to "
                    ".github/actions/setup-backend/action.yml."
                ),
            ),
            TextRequirement(
                needle="docker-compose.dev.yml",
                error_message=(
                    "docs/runtime_support_matrix.md must mention docker-compose.dev.yml as a "
                    "Node policy surface."
                ),
            ),
        ),
    )

    ui_readme = (ROOT / "apps" / "ui" / "README.md").read_text(encoding="utf-8")
    _extend_missing_text_requirements(
        errors,
        ui_readme,
        (
            TextRequirement(
                needle="docs/runtime_support_matrix.md",
                error_message=(
                    "apps/ui/README.md must point UI setup readers to docs/runtime_support_matrix.md and .nvmrc."
                ),
            ),
            TextRequirement(
                needle=".nvmrc",
                error_message=(
                    "apps/ui/README.md must point UI setup readers to docs/runtime_support_matrix.md and .nvmrc."
                ),
            ),
        ),
    )

    ui_smoke = jobs.get("ui-smoke") if isinstance(jobs, Mapping) else None
    steps = ui_smoke.get("steps") if isinstance(ui_smoke, Mapping) else None
    playwright_cache_ok = False
    playwright_install_step_ok = False
    ui_smoke_command_ok = False
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            step_name = step.get("name")
            step_run = step.get("run")
            step_working_directory = step.get("working-directory")
            step_env = step.get("env") if isinstance(step.get("env"), Mapping) else None
            normalized_command = ""
            if isinstance(step_run, str):
                cwd_prefix = ""
                if isinstance(step_working_directory, str) and step_working_directory:
                    cwd_prefix = f"cd {step_working_directory} && "
                normalized_command = (
                    f"{cwd_prefix}{_normalize_env(step_env)}"
                    f"{_normalize_shell_command(step_run.strip())}"
                )
            if (
                isinstance(step_name, str)
                and step_name == "Install Playwright Chromium (cache miss)"
                and step.get("if")
                == "${{ steps.playwright-browser-cache.outputs.cache-hit != 'true' }}"
                and normalized_command
                == "cd apps/ui && npx playwright install chromium"
            ):
                playwright_install_step_ok = True
            if (
                isinstance(step_name, str)
                and step_name == "UI smoke tests"
                and normalized_command
                == "cd apps/ui && env PLAYWRIGHT_SMOKE_WORKERS=4 PYTHON='${{ steps.setup-python.outputs.python-path }}' npm run test:smoke"
            ):
                ui_smoke_command_ok = True
            uses = step.get("uses")
            if not isinstance(uses, str) or not uses.startswith("actions/cache@"):
                continue
            with_data = step.get("with")
            if not isinstance(with_data, Mapping):
                continue
            path = with_data.get("path")
            key = with_data.get("key")
            if (
                step.get("id") == "playwright-browser-cache"
                and isinstance(path, str)
                and path.strip() == "~/.cache/ms-playwright"
                and isinstance(key, str)
                and "ms-playwright" in key
                and "package-lock.json" in key
            ):
                playwright_cache_ok = True
    if not playwright_cache_ok:
        errors.append(
            "ui-smoke must cache ~/.cache/ms-playwright with id playwright-browser-cache and a package-lock-based actions/cache key."
        )
    if not playwright_install_step_ok:
        errors.append(
            "ui-smoke must install Playwright Chromium in a separate cache-miss-only step."
        )
    if not ui_smoke_command_ok:
        errors.append(
            "ui-smoke must keep the smoke step focused on npm run test:smoke."
        )

    backend_job = (
        jobs.get(_BACKEND_TEST_MATRIX_JOB) if isinstance(jobs, Mapping) else None
    )
    if not isinstance(backend_job, Mapping):
        errors.append("CI workflow is missing the backend-tests matrix job.")
    else:
        if _workflow_job_needs(backend_job) != _CI_SCOPE_ONLY_NEEDS:
            errors.append(
                "backend-tests must depend only on ci-scope so path-aware gating stays centralized."
            )

        backend_job_name = backend_job.get("name")
        if (
            not isinstance(backend_job_name, str)
            or "${{ matrix.shard_label }}" not in backend_job_name
        ):
            errors.append(
                "backend-tests must include matrix.shard_label in its displayed job name so PR checks stay distinguishable."
            )

        strategy = backend_job.get("strategy")
        matrix = strategy.get("matrix") if isinstance(strategy, Mapping) else None
        raw_include = matrix.get("include") if isinstance(matrix, Mapping) else None
        actual_shard_jobs: list[str] = []
        if isinstance(raw_include, list):
            for raw_entry in raw_include:
                if not isinstance(raw_entry, Mapping):
                    continue
                logical_job_name = raw_entry.get("logical_job_name")
                if isinstance(logical_job_name, str):
                    actual_shard_jobs.append(logical_job_name)
        if tuple(actual_shard_jobs) != _BACKEND_TEST_SHARD_JOBS:
            errors.append(
                "backend-tests must define strategy.matrix.include entries whose logical_job_name values match backend-tests-1 through backend-tests-5 in order."
            )

        backend_steps = backend_job.get("steps")
        backend_duration_cache_ok = False
        backend_parallel_config_ok = False
        if isinstance(backend_steps, list):
            for step in backend_steps:
                if not isinstance(step, Mapping):
                    continue
                step_name = step.get("name")
                step_run = step.get("run")
                step_env = step.get("env")
                normalized_run = (
                    " ".join(
                        line.strip() for line in step_run.splitlines() if line.strip()
                    )
                    if isinstance(step_run, str)
                    else ""
                )
                if (
                    isinstance(step_name, str)
                    and step_name == "Backend tests shard ${{ matrix.shard_label }}"
                    and isinstance(step_env, Mapping)
                    and str(
                        step_env.get("VIBESENSOR_BACKEND_XDIST_WORKERS", "")
                    ).strip()
                    == _BACKEND_TEST_XDIST_WORKERS
                    and f"tools/tests/run_backend_parallel.py --shards {_BACKEND_TEST_SHARD_COUNT}"
                    in normalized_run
                    and "--shard-index ${{ matrix.shard_index }}" in normalized_run
                ):
                    backend_parallel_config_ok = True
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
                    and path.strip()
                    == "~/.cache/vibesensor/backend-duration-cache.json"
                    and isinstance(key, str)
                    and "backend-test-durations" in key
                    and "run_backend_parallel.py" in key
                    and "apps/server/tests/**/*.py" in key
                    and "matrix.cache_suffix" in key
                    and "github.run_id" in key
                    and isinstance(restore_keys, str)
                    and "run_backend_parallel.py" in restore_keys
                    and "${{ runner.os }}-backend-test-durations-" in restore_keys
                ):
                    backend_duration_cache_ok = True
        if not backend_duration_cache_ok:
            errors.append(
                "backend-tests must cache ~/.cache/vibesensor/backend-duration-cache.json "
                "with a restoreable actions/cache key tied to run_backend_parallel.py, "
                "apps/server/tests, matrix.cache_suffix, and github.run_id."
            )
        if not backend_parallel_config_ok:
            errors.append(
                "backend-tests must run run_backend_parallel.py with --shards 5 and "
                "VIBESENSOR_BACKEND_XDIST_WORKERS=3 so the measured backend test tuning "
                "stays explicit in CI."
            )

    e2e_job = jobs.get("e2e") if isinstance(jobs, Mapping) else None
    steps: object = None
    e2e_uses_docker_steps = False
    if not isinstance(e2e_job, Mapping):
        errors.append("CI workflow is missing the e2e job.")
    else:
        if _workflow_job_needs(e2e_job) != _CI_SCOPE_ONLY_NEEDS:
            errors.append(
                "e2e must depend only on ci-scope so path-aware gating stays centralized."
            )

        steps = e2e_job.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                uses = step.get("uses")
                if isinstance(uses, str) and (
                    uses.startswith("docker/setup-buildx-action@")
                    or uses.startswith("docker/build-push-action@")
                ):
                    e2e_uses_docker_steps = True
                    break
    if e2e_uses_docker_steps:
        errors.append(
            "e2e must not depend on Docker buildx or docker image build steps."
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
