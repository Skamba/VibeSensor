"""Guard the shared Pi image composite action contract."""

from __future__ import annotations

import yaml

from tests._paths import REPO_ROOT


def test_build_pi_image_action_reuses_shared_runtime_setup_and_artifact_collection() -> None:
    action_path = REPO_ROOT / ".github" / "actions" / "build-pi-image" / "action.yml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))

    inputs = action["inputs"]
    assert set(inputs) == {
        "release-dir-name",
        "release-artifact-name",
        "workflow-artifact-name",
        "include-published-artifact",
    }
    assert inputs["include-published-artifact"]["default"] == "false"

    outputs = action["outputs"]
    assert outputs["python-path"]["value"] == "${{ steps.setup-python.outputs.python-path }}"
    assert outputs["release-dir"]["value"] == "${{ steps.assets.outputs.release-dir }}"
    assert outputs["release-artifact-name"]["value"] == (
        "${{ steps.assets.outputs.release-artifact-name }}"
    )

    steps = action["runs"]["steps"]
    assert steps[0]["uses"] == "actions/setup-node@v6"

    setup_python_step = next(
        step for step in steps if isinstance(step, dict) and step.get("id") == "setup-python"
    )
    assert setup_python_step["uses"] == "./.github/actions/setup-python"

    build_step = next(
        step for step in steps if isinstance(step, dict) and step.get("name") == "Build Pi image"
    )
    assert build_step["env"]["VS_PYTHON_BIN"] == "${{ steps.setup-python.outputs.python-path }}"

    collect_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Collect Pi image workflow artifacts"
    )
    assert collect_step["id"] == "assets"
    assert collect_step["env"]["VS_RELEASE_DIR_NAME"] == "${{ inputs.release-dir-name }}"
    assert collect_step["env"]["VS_RELEASE_ARTIFACT_NAME"] == "${{ inputs.release-artifact-name }}"
    assert (
        collect_step["env"]["VS_INCLUDE_PUBLISHED_ARTIFACT"]
        == "${{ inputs.include-published-artifact }}"
    )

    upload_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Upload Pi image workflow artifact"
    )
    assert upload_step["uses"] == "actions/upload-artifact@v7"
    assert upload_step["with"]["name"] == "${{ inputs.workflow-artifact-name }}"
    assert upload_step["with"]["retention-days"] == 21
