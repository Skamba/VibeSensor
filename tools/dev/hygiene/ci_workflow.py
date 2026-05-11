"""CI workflow and local runner synchronization checks."""

from __future__ import annotations

import importlib.util
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path


from ._shared import *


def _load_ci_workflow() -> dict[str, object]:
    return _load_yaml_mapping(ROOT / ".github" / "workflows" / "ci.yml")


def _workflow_job_needs(raw_job: Mapping[str, object]) -> tuple[str, ...]:
    raw_needs = raw_job.get("needs")
    if isinstance(raw_needs, str):
        return (raw_needs,)
    if isinstance(raw_needs, list):
        return tuple(need for need in raw_needs if isinstance(need, str))
    return ()


def _load_action_steps(path: Path) -> list[object]:
    action = _load_yaml_mapping(path)
    runs = action.get("runs")
    if not isinstance(runs, Mapping):
        return []
    steps = runs.get("steps")
    return steps if isinstance(steps, list) else []


def _load_ci_parallel_module():
    module_path = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    spec = importlib.util.spec_from_file_location("ci_parallel_local", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_ci_manifest_module():
    module_path = ROOT / "tools" / "tests" / "ci_workflow_manifest.py"
    spec = importlib.util.spec_from_file_location(
        "ci_workflow_manifest_local", module_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _workflow_job_mapping(
    jobs: Mapping[str, object], job_name: str
) -> Mapping[str, object] | None:
    raw_job = jobs.get(job_name)
    return raw_job if isinstance(raw_job, Mapping) else None


def _workflow_job_steps(
    jobs: Mapping[str, object], job_name: str
) -> list[object] | None:
    raw_job = _workflow_job_mapping(jobs, job_name)
    if raw_job is None:
        return None
    steps = raw_job.get("steps")
    return steps if isinstance(steps, list) else None


def _extend_missing_text_requirements(
    errors: list[str],
    text: str,
    requirements: Sequence[TextRequirement],
) -> None:
    for requirement in requirements:
        if requirement.needle not in text:
            errors.append(requirement.error_message)


def _workflow_step_matches(step: object, requirement: WorkflowStepRequirement) -> bool:
    if not isinstance(step, Mapping):
        return False
    if requirement.step_id is not None and step.get("id") != requirement.step_id:
        return False
    if requirement.uses is not None and step.get("uses") != requirement.uses:
        return False
    if requirement.uses_prefix is not None:
        raw_uses = step.get("uses")
        if not isinstance(raw_uses, str) or not raw_uses.startswith(
            requirement.uses_prefix
        ):
            return False
    if requirement.run is not None and step.get("run") != requirement.run:
        return False
    if (
        requirement.working_directory is not None
        and step.get("working-directory") != requirement.working_directory
    ):
        return False
    return True


def _extend_step_requirement_errors(
    errors: list[str],
    steps: Sequence[object],
    requirements: Sequence[WorkflowStepRequirement],
) -> None:
    for requirement in requirements:
        matched = any(_workflow_step_matches(step, requirement) for step in steps)
        if requirement.forbidden:
            if matched:
                errors.append(requirement.error_message)
            continue
        if not matched:
            errors.append(requirement.error_message)


def _normalize_python_token(token: str) -> str:
    stripped = token.strip("\"'")
    if Path(stripped).name.startswith("python") or "python-path" in stripped:
        return "python"
    return token


def _normalize_tokenized_command(tokens: list[str]) -> str:
    return _repo_tooling_support.normalize_tokenized_command(
        tokens,
        command_token_normalizer=_normalize_python_token,
    )


def _normalize_shell_command(command: str) -> str:
    return _repo_tooling_support.normalize_shell_command(
        command,
        command_token_normalizer=_normalize_python_token,
    )


def _normalize_env(env: Mapping[str, object] | None) -> str:
    if not env:
        return ""
    parts = [f"{key}={shlex.quote(str(env[key]))}" for key in sorted(env)]
    return f"env {' '.join(parts)} "


def _normalize_local_step(step) -> str:
    cwd_prefix = ""
    if step.cwd != ROOT:
        cwd_prefix = f"cd {step.cwd.relative_to(ROOT).as_posix()} && "
    env_prefix = _normalize_env(step.env)
    command = (
        step.cmd[0]
        if getattr(step, "shell", False)
        else _normalize_tokenized_command(step.cmd)
    )
    return f"{cwd_prefix}{env_prefix}{command}"


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
        pip_install_index = next(
            (
                index
                for index in range(len(tokens) - 3)
                if tokens[index + 1 : index + 4] == ["-m", "pip", "install"]
            ),
            None,
        )
        if pip_install_index is None:
            continue
        args = tokens[pip_install_index + 4 :]
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


def check_ci_job_sync() -> list[str]:
    """Verify run_ci_parallel.py exposes every workflow-backed manifest job."""
    # ruff: noqa: F403,F405
    manifest_py = ROOT / "tools" / "tests" / "ci_workflow_manifest.py"
    parallel_py = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    errors: list[str] = []
    if not manifest_py.exists() or not parallel_py.exists():
        return errors

    ci_jobs = list(_load_ci_manifest_module().all_job_names())
    parallel_jobs = list(_local_runner_commands()[0])

    only_ci = set(ci_jobs) - set(parallel_jobs)
    only_parallel = set(parallel_jobs) - set(ci_jobs)
    if only_ci:
        errors.append(
            f"Workflow manifest jobs missing from run_ci_parallel.py: {sorted(only_ci)}"
        )
    if only_parallel:
        errors.append(
            f"run_ci_parallel.py exposes jobs not present in the workflow manifest: {sorted(only_parallel)}"
        )
    return errors


def check_ci_command_sync() -> list[str]:
    """Verify local runner commands translate the shared workflow manifest correctly."""
    manifest_jobs = _load_ci_manifest_module().ci_workflow_jobs()
    local_jobs, common_bootstrap, firmware_bootstrap = _local_runner_commands()
    errors: list[str] = []

    common_backend_markers = _pip_install_markers(common_bootstrap[:2])
    backend_install_jobs = [
        job_name
        for job_name, job in manifest_jobs.items()
        if job.commands_named({"Install dependencies"})
        and not job.commands_named({"Install UI dependencies"})
        and not job.requires_platformio
    ]
    for job_name in backend_install_jobs:
        install_commands = list(
            manifest_jobs[job_name].commands_named({"Install dependencies"})
        )
        if _pip_install_markers(install_commands) != common_backend_markers:
            errors.append(
                f"{job_name} backend install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={common_bootstrap[:2]!r}"
            )

    ui_bootstrap_commands = common_bootstrap[2:]
    ui_install_jobs = [
        job_name
        for job_name, job in manifest_jobs.items()
        if job.commands_named({"Install UI dependencies"})
    ]
    for job_name in ui_install_jobs:
        install_commands = list(
            manifest_jobs[job_name].commands_named({"Install UI dependencies"})
        )
        if install_commands != ui_bootstrap_commands:
            errors.append(
                f"{job_name} UI install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={ui_bootstrap_commands!r}"
            )

    firmware_jobs = [
        job_name for job_name, job in manifest_jobs.items() if job.requires_platformio
    ]
    for job_name in firmware_jobs:
        firmware_install_commands = list(
            manifest_jobs[job_name].commands_named(
                {"Install dependencies", "Install PlatformIO dependencies"}
            )
        )
        if _pip_install_markers(firmware_install_commands) != _pip_install_markers(
            firmware_bootstrap[:3]
        ):
            errors.append(
                f"{job_name} install commands drifted from local bootstrap: "
                f"ci={firmware_install_commands!r} local={firmware_bootstrap[:3]!r}"
            )

    for job_name, job in manifest_jobs.items():
        expected_commands = [
            _normalize_shell_command(spec.command)
            for spec in job.local_runnable_steps(sys.executable)
        ]
        local_commands = local_jobs.get(job_name, [])
        if expected_commands != local_commands:
            errors.append(
                f"{job_name} run commands drifted from the workflow manifest: "
                f"ci={expected_commands!r} local={local_commands!r}"
            )

    return errors


def check_ci_lite_job_sync() -> list[str]:
    """Verify CI-lite entrypoints derive from the shared workflow manifest."""
    manifest = _load_ci_manifest_module()
    ci_parallel = _load_ci_parallel_module()
    errors: list[str] = []
    for name, manifest_names, runner_names in (
        ("CI-fast", manifest.ci_fast_job_names(), ci_parallel.CI_FAST_JOB_NAMES),
        ("CI-lite", manifest.ci_lite_job_names(), ci_parallel.CI_LITE_JOB_NAMES),
    ):
        expected = list(manifest_names)
        actual = list(runner_names)
        if actual != expected:
            errors.append(
                f"run_ci_parallel.py {name} jobs drifted from the workflow manifest: "
                f"expected={expected!r} actual={actual!r}"
            )
    makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    if "CI_LITE_JOBS :=" in makefile_text or "CI_LITE_JOBS:=" in makefile_text:
        errors.append("Makefile must not define a mirrored CI_LITE_JOBS variable.")
    for target, flag in (("test-ci-fast", "--ci-fast"), ("test-ci-lite", "--ci-lite")):
        if f"tools/tests/run_ci_parallel.py {flag}" not in makefile_text:
            errors.append(f"Makefile {target} must invoke run_ci_parallel.py {flag}.")
    return errors


def check_changed_scope_command_docs() -> list[str]:
    errors: list[str] = []
    wrapper_text = (ROOT / "tools/tests/run_ci_with_act.sh").read_text(encoding="utf-8")
    if (
        "--full-stack" not in wrapper_text
        or "VIBESENSOR_CI_FORCE_FULL_STACK=1" not in wrapper_text
    ):
        errors.append(
            "tools/tests/run_ci_with_act.sh must expose --full-stack and set VIBESENSOR_CI_FORCE_FULL_STACK=1."
        )
    for path in (
        ROOT / "docs/testing.md",
        ROOT / ".github/copilot-instructions.md",
    ):
        text = path.read_text(encoding="utf-8")
        if "run_ci_with_act.sh" not in text or "--full-stack" not in text:
            errors.append(
                f"{path.relative_to(ROOT)} must document changed-scope and full-stack ACT usage."
            )
    return errors


def _named_step(steps: Sequence[object], name: str) -> Mapping[str, object] | None:
    return next(
        (
            step
            for step in steps
            if isinstance(step, Mapping) and step.get("name") == name
        ),
        None,
    )


def check_pi_image_workflow_contract() -> list[str]:
    errors: list[str] = []
    weekly = _load_yaml_mapping(ROOT / ".github/workflows/weekly-pi-image.yml")
    weekly_jobs = weekly.get("jobs")
    weekly_job = (
        weekly_jobs.get("build-and-release")
        if isinstance(weekly_jobs, Mapping)
        else None
    )
    if not isinstance(weekly_job, Mapping):
        errors.append("weekly-pi-image workflow must define jobs.build-and-release.")
    else:
        if weekly_job.get("runs-on") != "ubuntu-24.04-arm":
            errors.append(
                "weekly-pi-image build-and-release must use ubuntu-24.04-arm."
            )
        steps = weekly_job.get("steps")
        if not isinstance(steps, list):
            errors.append("weekly-pi-image build-and-release must define steps.")
        else:
            if any(
                isinstance(step, Mapping)
                and step.get("uses") == "docker/setup-qemu-action@v4"
                for step in steps
            ):
                errors.append(
                    "weekly-pi-image must not install QEMU on the native ARM runner."
                )
            source_step = _named_step(steps, "Compute weekly source SHA")
            if (
                source_step is None
                or source_step.get("id") != "source"
                or "git rev-parse HEAD" not in str(source_step.get("run", ""))
            ):
                errors.append(
                    "weekly-pi-image must compute a source SHA from git rev-parse HEAD."
                )
            build_step = _named_step(steps, "Build weekly Pi image workflow artifact")
            build_with = (
                build_step.get("with") if isinstance(build_step, Mapping) else None
            )
            if (
                not isinstance(build_with, Mapping)
                or build_step.get("uses") != "./.github/actions/build-pi-image"
            ):
                errors.append(
                    "weekly-pi-image must build through ./.github/actions/build-pi-image."
                )
            elif (
                build_with.get("release-dir-name") != "weekly-pi-image"
                or build_with.get("release-artifact-name")
                != "VibeSensor-${{ steps.metadata.outputs.build_label }}.img.zip"
                or build_with.get("workflow-artifact-name")
                != "weekly-pi-image-${{ steps.metadata.outputs.build_label }}"
                or build_with.get("include-published-artifact") != "true"
            ):
                errors.append(
                    "weekly-pi-image build action inputs must keep weekly release and workflow artifact naming."
                )
            publish_step = _named_step(steps, "Publish weekly Pi image release")
            publish_script = str(publish_step.get("run", "")) if publish_step else ""
            if (
                "${{ steps.assets.outputs.artifact_name }}" in publish_script
                or "${GITHUB_SHA}" in publish_script
                or "${{ steps.build-image.outputs.release-artifact-name }}"
                not in publish_script
                or '--target "${{ steps.source.outputs.sha }}"' not in publish_script
            ):
                errors.append(
                    "weekly-pi-image publish step must target the computed source SHA and build-image artifact output."
                )

    manual = _load_yaml_mapping(ROOT / ".github/workflows/manual-pi-image-arm.yml")
    manual_jobs = manual.get("jobs")
    manual_job = (
        manual_jobs.get("build-image") if isinstance(manual_jobs, Mapping) else None
    )
    if not isinstance(manual_job, Mapping):
        errors.append("manual-pi-image-arm workflow must define jobs.build-image.")
    else:
        if manual_job.get("runs-on") != "ubuntu-24.04-arm":
            errors.append("manual-pi-image-arm build-image must use ubuntu-24.04-arm.")
        steps = manual_job.get("steps")
        build_step = (
            _named_step(steps, "Build ARM Pi image workflow artifact")
            if isinstance(steps, list)
            else None
        )
        build_with = build_step.get("with") if isinstance(build_step, Mapping) else None
        if (
            not isinstance(build_with, Mapping)
            or build_step.get("uses") != "./.github/actions/build-pi-image"
        ):
            errors.append(
                "manual-pi-image-arm must build through ./.github/actions/build-pi-image."
            )
        elif (
            build_with.get("release-dir-name") != "manual-pi-image-arm"
            or build_with.get("release-artifact-name")
            != "${{ steps.metadata.outputs.artifact_prefix }}.img.zip"
            or build_with.get("workflow-artifact-name")
            != "manual-pi-image-arm-${{ steps.metadata.outputs.build_label }}"
            or "include-published-artifact" in build_with
        ):
            errors.append(
                "manual-pi-image-arm build action inputs must stay artifact-only with manual naming."
            )
        if isinstance(steps, list) and _named_step(
            steps, "Publish weekly Pi image release"
        ):
            errors.append("manual-pi-image-arm must not publish weekly releases.")

    actrc = (ROOT / ".actrc").read_text(encoding="utf-8")
    if "ubuntu-24.04-arm" in actrc:
        errors.append(
            ".actrc must not map ubuntu-24.04-arm; local ACT cannot emulate those workflows."
        )
    for path in (
        ROOT / "docs/testing.md",
        ROOT / ".github/copilot-instructions.md",
        ROOT / "infra/pi-image/pi-gen/README.md",
    ):
        text = path.read_text(encoding="utf-8")
        missing = [
            needle
            for needle in (
                "ubuntu-24.04-arm",
                "not mapped",
                "BUILD_MODE=app ./infra/pi-image/pi-gen/build.sh",
                "BUILD_MODE=image ./infra/pi-image/pi-gen/build.sh",
                "./infra/pi-image/pi-gen/validate-image.sh",
            )
            if needle not in text
        ]
        if missing:
            errors.append(
                f"{path.relative_to(ROOT)} must document native ARM Pi image ACT limits and local build commands; missing {missing}."
            )
    return errors
