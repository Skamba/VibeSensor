"""Guard the main release workflow's release-validation paths."""

from __future__ import annotations

import yaml

from tests._paths import REPO_ROOT

_STALE_MODULE = "vibesensor.use_cases.updates.release_validation"
_LIVE_MODULE = "vibesensor.use_cases.updates.releases.release_validation"


def test_main_release_workflow_fetches_full_history_and_validates_release_artifacts() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "main-release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    release_job = workflow["jobs"]["release"]
    steps = release_job["steps"]

    checkout_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("uses") == "actions/checkout@v6"
    )
    assert checkout_step["with"]["fetch-depth"] == 0

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


def test_main_release_workflow_labels_and_cleans_only_wheel_esp_releases() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "main-release.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    release_job = workflow["jobs"]["release"]
    steps = release_job["steps"]

    create_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Create combined Wheel / ESP release"
    )
    create_script = create_step["run"]
    assert '--title "Wheel / ESP release ${{ steps.version.outputs.version }}"' in create_script

    cleanup_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Remove superseded Wheel / ESP releases"
    )
    assert cleanup_step["env"]["WHEEL_ESP_RELEASE_TITLE_PREFIX"] == "Wheel / ESP release"
    cleanup_script = cleanup_step["with"]["script"]
    assert 'tag.startsWith("server-v")' in cleanup_script
    assert "title.startsWith(releaseTitlePrefix)" in cleanup_script
    assert "title.startsWith(legacyTitlePrefix)" in cleanup_script
    assert "weekly-pi-image" not in cleanup_script
    assert "/^fw-v/" not in cleanup_script
