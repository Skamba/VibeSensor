"""Guard the shared Pi image composite action contract."""

from __future__ import annotations

import yaml

from tests._paths import REPO_ROOT


def _step_by_id(steps: list[dict[str, object]], step_id: str) -> dict[str, object]:
    return next(step for step in steps if isinstance(step, dict) and step.get("id") == step_id)


def _step_by_name(steps: list[dict[str, object]], name: str) -> dict[str, object]:
    return next(step for step in steps if isinstance(step, dict) and step.get("name") == name)


def test_build_pi_image_action_reuses_shared_runtime_and_publishes_image_contract() -> None:
    action_path = REPO_ROOT / ".github" / "actions" / "build-pi-image" / "action.yml"
    action = yaml.safe_load(action_path.read_text(encoding="utf-8"))

    inputs = action["inputs"]
    assert {
        "release-dir-name",
        "release-artifact-name",
        "workflow-artifact-name",
        "include-published-artifact",
    }.issubset(inputs)
    assert inputs["include-published-artifact"]["default"] == "false"

    outputs = action["outputs"]
    assert outputs["python-path"]["value"] == "${{ steps.setup-python.outputs.python-path }}"
    assert outputs["release-dir"]["value"] == "${{ steps.assets.outputs.release-dir }}"
    assert outputs["release-artifact-name"]["value"] == (
        "${{ steps.assets.outputs.release-artifact-name }}"
    )

    steps = action["runs"]["steps"]
    setup_python_step = _step_by_id(steps, "setup-python")
    assert setup_python_step["uses"] == "./.github/actions/setup-python"

    build_step = _step_by_name(steps, "Build Pi image")
    assert build_step["env"]["VS_PYTHON_BIN"] == "${{ steps.setup-python.outputs.python-path }}"
    assert "./infra/pi-image/pi-gen/build.sh" in build_step["run"]

    collect_step = _step_by_id(steps, "assets")
    assert collect_step["id"] == "assets"
    assert collect_step["env"]["VS_RELEASE_DIR_NAME"] == "${{ inputs.release-dir-name }}"
    assert collect_step["env"]["VS_RELEASE_ARTIFACT_NAME"] == "${{ inputs.release-artifact-name }}"
    assert (
        collect_step["env"]["VS_INCLUDE_PUBLISHED_ARTIFACT"]
        == "${{ inputs.include-published-artifact }}"
    )
    collect_run = collect_step["run"]
    assert '-name "image_*-vibesensor-lite*.zip"' in collect_run
    assert "sha256sum" in collect_run
    assert "version_info_source" in collect_run
    assert "published_artifact=${artifact_name}" in collect_run

    upload_step = _step_by_name(steps, "Upload Pi image workflow artifact")
    assert upload_step["uses"] == "actions/upload-artifact@v7"
    assert upload_step["with"]["name"] == "${{ inputs.workflow-artifact-name }}"
    assert upload_step["with"]["path"] == "${{ steps.assets.outputs.release-dir }}/*"
    assert upload_step["with"]["if-no-files-found"] == "error"
