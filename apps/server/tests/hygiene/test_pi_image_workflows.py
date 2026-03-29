"""Guard Yocto-based Raspberry Pi image workflow wiring."""

from __future__ import annotations

import yaml

from _paths import REPO_ROOT


def _load_workflow(name: str) -> dict[str, object]:
    path = REPO_ROOT / ".github" / "workflows" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _step_by_name(workflow: dict[str, object], job_name: str, step_name: str) -> dict[str, object]:
    steps = workflow["jobs"][job_name]["steps"]
    return next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == step_name
    )


def test_weekly_pi_image_workflow_uses_arm_runner_and_yocto_build() -> None:
    workflow = _load_workflow("weekly-pi-image.yml")
    job = workflow["jobs"]["build-and-release"]

    assert job["runs-on"] == "ubuntu-24.04-arm"

    downloads_step = _step_by_name(workflow, "build-and-release", "Restore Yocto downloads cache")
    assert downloads_step["with"]["path"] == "infra/pi-image/yocto/.build/downloads"

    sstate_step = _step_by_name(workflow, "build-and-release", "Restore Yocto sstate cache")
    assert sstate_step["with"]["path"] == "infra/pi-image/yocto/.build/sstate-cache"

    build_step = _step_by_name(workflow, "build-and-release", "Build Pi image")
    run_script = build_step["run"]
    assert "./infra/pi-image/yocto/build.sh" in run_script
    assert "BUILD_LABEL=" in run_script

    prereq_step = _step_by_name(workflow, "build-and-release", "Install Yocto build prerequisites")
    prereq_script = prereq_step["run"]
    assert "locale-gen en_US.UTF-8" in prereq_script
    assert 'echo "LANG=en_US.UTF-8"' in prereq_script
    assert 'echo "LC_ALL=en_US.UTF-8"' in prereq_script

    collect_step = _step_by_name(workflow, "build-and-release", "Collect weekly release assets")
    collect_script = collect_step["run"]
    assert 'out_dir="infra/pi-image/yocto/out"' in collect_script
    assert "vibesensor-rpi-universal.wic.bz2" in collect_script
    assert ".img.bz2" in collect_script


def test_manual_pi_image_workflow_uses_arm_runner_and_yocto_build() -> None:
    workflow = _load_workflow("manual-pi-image-arm.yml")
    job = workflow["jobs"]["build-image"]

    assert job["runs-on"] == "ubuntu-24.04-arm"

    downloads_step = _step_by_name(workflow, "build-image", "Restore Yocto downloads cache")
    assert downloads_step["with"]["path"] == "infra/pi-image/yocto/.build/downloads"

    sstate_step = _step_by_name(workflow, "build-image", "Restore Yocto sstate cache")
    assert sstate_step["with"]["path"] == "infra/pi-image/yocto/.build/sstate-cache"

    build_step = _step_by_name(workflow, "build-image", "Build Pi image")
    run_script = build_step["run"]
    assert "./infra/pi-image/yocto/build.sh" in run_script
    assert "BUILD_LABEL=" in run_script

    prereq_step = _step_by_name(workflow, "build-image", "Install Yocto build prerequisites")
    prereq_script = prereq_step["run"]
    assert "locale-gen en_US.UTF-8" in prereq_script
    assert 'echo "LANG=en_US.UTF-8"' in prereq_script
    assert 'echo "LC_ALL=en_US.UTF-8"' in prereq_script

    collect_step = _step_by_name(workflow, "build-image", "Collect ARM workflow artifacts")
    collect_script = collect_step["run"]
    assert 'out_dir="infra/pi-image/yocto/out"' in collect_script
    assert "vibesensor-rpi-universal.wic.bz2" in collect_script
    assert ".img.bz2" in collect_script
