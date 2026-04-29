"""Guard the weekly Pi image workflow's native ARM configuration."""

from __future__ import annotations

import yaml

from tests._paths import REPO_ROOT


def test_weekly_pi_image_workflow_uses_native_arm_runner_and_keeps_release_naming() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "weekly-pi-image.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build-and-release"]

    assert job["runs-on"] == "ubuntu-24.04-arm"

    steps = job["steps"]
    assert not any(
        isinstance(step, dict) and step.get("uses") == "docker/setup-qemu-action@v4"
        for step in steps
    )
    source_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Compute weekly source SHA"
    )
    assert source_step["id"] == "source"
    assert "git rev-parse HEAD" in source_step["run"]

    build_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Build weekly Pi image workflow artifact"
    )
    assert build_step["uses"] == "./.github/actions/build-pi-image"
    assert build_step["with"]["release-dir-name"] == "weekly-pi-image"
    assert (
        build_step["with"]["release-artifact-name"]
        == "VibeSensor-${{ steps.metadata.outputs.build_label }}.img.zip"
    )
    assert (
        build_step["with"]["workflow-artifact-name"]
        == "weekly-pi-image-${{ steps.metadata.outputs.build_label }}"
    )
    assert build_step["with"]["include-published-artifact"] == "true"
    publish_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Publish weekly Pi image release"
    )
    publish_script = publish_step["run"]
    assert "${{ steps.assets.outputs.artifact_name }}" not in publish_script
    assert "${GITHUB_SHA}" not in publish_script
    assert "${{ steps.build-image.outputs.release-artifact-name }}" in publish_script
    assert '--target "${{ steps.source.outputs.sha }}"' in publish_script
    step_names = {
        step.get("name")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    }
    assert "Delete previous weekly Pi image releases" in step_names
    assert "Publish weekly Pi image release" in step_names


def test_manual_pi_image_workflow_reuses_shared_build_action_and_stays_artifact_only() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "manual-pi-image-arm.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build-image"]

    assert job["runs-on"] == "ubuntu-24.04-arm"
    steps = job["steps"]

    build_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Build ARM Pi image workflow artifact"
    )
    assert build_step["uses"] == "./.github/actions/build-pi-image"
    assert build_step["with"]["release-dir-name"] == "manual-pi-image-arm"
    assert (
        build_step["with"]["release-artifact-name"]
        == "${{ steps.metadata.outputs.artifact_prefix }}.img.zip"
    )
    assert (
        build_step["with"]["workflow-artifact-name"]
        == "manual-pi-image-arm-${{ steps.metadata.outputs.build_label }}"
    )
    assert "include-published-artifact" not in build_step["with"]

    step_names = {
        step.get("name")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    }
    assert "Publish weekly Pi image release" not in step_names
