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

    assets_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Collect weekly release assets"
    )
    assets_script = assets_step["run"]
    assert 'release_artifact="${release_dir}/VibeSensor-${short_date}.img.zip"' in assets_script
    assert (
        'version_info_target="${release_dir}/VibeSensor-${short_date}.img.zip.version.txt"'
        in assets_script
    )
    assert 'echo "published_artifact=VibeSensor-${short_date}.img.zip"' in assets_script
    assert 'echo "runner_label=ubuntu-24.04-arm"' in assets_script

    upload_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Upload weekly image workflow artifact"
    )
    assert (
        upload_step["with"]["name"] == "weekly-pi-image-${{ steps.metadata.outputs.build_label }}"
    )
