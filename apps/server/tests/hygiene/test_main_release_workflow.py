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

    compute_version_step = next(
        step for step in steps if isinstance(step, dict) and step.get("name") == "Compute version"
    )
    compute_script = compute_version_step["run"]
    assert "tools/release/main_release.py compute-version" in compute_script
    assert 'base_ver="$(date -u +%Y.%-m.%-d)"' not in compute_script
    assert 'git tag -l "server-v${base_ver}*"' not in compute_script

    build_wheel_step = next(
        step
        for step in steps
        if isinstance(step, dict) and step.get("name") == "Stamp version and build server wheel"
    )
    build_wheel_script = build_wheel_step["run"]
    assert "tools/release/main_release.py build-wheel" in build_wheel_script
    assert "cat > apps/server/vibesensor/_version.py" not in build_wheel_script
    assert "python -m build --wheel apps/server/" not in build_wheel_script

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
    assert "python - <<'PY'" not in manifest_script

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
    assert cleanup_step["env"]["GH_TOKEN"] == "${{ github.token }}"
    cleanup_script = cleanup_step["run"]
    assert "tools/release/main_release.py cleanup-releases" in cleanup_script
    assert "--current-tag" in cleanup_script
    assert "--release-title-prefix" in cleanup_script
    assert "actions/github-script@v8" not in str(cleanup_step)

    assert release_job["outputs"]["version"] == "${{ steps.version.outputs.version }}"
    assert release_job["outputs"]["tag"] == "${{ steps.version.outputs.tag }}"
