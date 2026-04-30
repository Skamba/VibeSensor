"""Guard the main release workflow's release-validation paths."""

from __future__ import annotations

import yaml

from tests._paths import REPO_ROOT

_STALE_MODULE = "vibesensor.use_cases.updates.release_validation"
_LIVE_MODULE = "vibesensor.use_cases.updates.releases.release_validation"
_MAIN_RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-release.yml"
_WEEKLY_PI_IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "weekly-pi-image.yml"


def test_main_release_workflow_fetches_full_history_and_validates_release_artifacts() -> None:
    workflow_path = _MAIN_RELEASE_WORKFLOW
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    release_job = workflow["jobs"]["release"]
    steps = release_job["steps"]

    checkout_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("uses") == "actions/checkout@v6"
    )
    assert checkout_step["with"]["fetch-depth"] == 0
    assert "github.event.workflow_run.head_sha" in checkout_step["with"]["ref"]

    source_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Compute release source SHA"
    )
    assert source_step["id"] == "release_source"
    assert "git rev-parse HEAD" in source_step["run"]

    compute_version_step = next(
        step for step in steps if isinstance(step, dict) and step.get("name") == "Compute version"
    )
    compute_script = compute_version_step["run"]
    assert "tools/release/main_release.py compute-version" in compute_script

    build_wheel_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Stamp version and build server wheel"
    )
    build_wheel_script = build_wheel_step["run"]
    assert "tools/release/main_release.py build-wheel" in build_wheel_script

    metadata_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Validate built server wheel metadata"
    )
    run_script = metadata_step["run"]
    assert _LIVE_MODULE in run_script
    assert "validate-wheel-metadata" in run_script
    assert "--expected-version" in run_script
    assert _STALE_MODULE not in run_script

    firmware_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Validate firmware manifest"
    )
    run_script = firmware_step["run"]
    assert _LIVE_MODULE in run_script
    assert "validate-firmware-manifest" in run_script
    assert _STALE_MODULE not in run_script

    manifest_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Generate flash manifest"
    )
    manifest_script = manifest_step["run"]
    assert "tools/release/main_release.py generate-firmware-manifest" in manifest_script
    assert '--generated-from "${{ steps.release_source.outputs.sha }}"' in manifest_script
    assert "GITHUB_SHA" not in manifest_script

    release_step_names = {
        step.get("name")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    }
    assert "publish_wiki" not in workflow["jobs"]
    assert "Generate wiki screenshots" not in release_step_names
    assert "Upload wiki screenshot artifact" not in release_step_names
    assert "Publish GitHub wiki screenshots" not in release_step_names


def test_main_release_workflow_labels_and_cleans_only_wheel_esp_releases() -> None:
    workflow_path = _MAIN_RELEASE_WORKFLOW
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    release_job = workflow["jobs"]["release"]
    steps = release_job["steps"]

    create_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Create combined Wheel / ESP release"
    )
    assert isinstance(create_step["run"], str)
    assert '--target "${{ steps.release_source.outputs.sha }}"' in create_step["run"]
    assert "GITHUB_SHA" not in create_step["run"]

    cleanup_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Remove superseded Wheel / ESP releases"
    )
    assert cleanup_step["env"]["WHEEL_ESP_RELEASE_TITLE_PREFIX"] == "Wheel / ESP release"
    assert cleanup_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    cleanup_script = cleanup_step["run"]
    assert "tools/release/main_release.py cleanup-releases" in cleanup_script
    assert "--current-tag" in cleanup_script
    assert "--release-title-prefix" in cleanup_script

    assert release_job["outputs"]["version"] == "${{ steps.version.outputs.version }}"
    assert release_job["outputs"]["tag"] == "${{ steps.version.outputs.tag }}"


def test_manual_release_workflows_require_main_branch_before_publishing() -> None:
    workflow_cases = (
        (_MAIN_RELEASE_WORKFLOW, "release", "Create combined Wheel / ESP release"),
        (_WEEKLY_PI_IMAGE_WORKFLOW, "build-and-release", "Publish weekly Pi image release"),
    )

    for workflow_path, job_name, publish_step_name in workflow_cases:
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        steps = workflow["jobs"][job_name]["steps"]
        guard_index = next(
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("name") == "Validate manual release source"
        )
        publish_index = next(
            index
            for index, step in enumerate(steps)
            if isinstance(step, dict) and step.get("name") == publish_step_name
        )
        guard_step = steps[guard_index]

        assert guard_index < publish_index
        assert (
            guard_step["if"]
            == "${{ github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main' }}"
        )
        assert "Manual release workflow runs must use the main branch" in guard_step["run"]
        assert "exit 1" in guard_step["run"]
