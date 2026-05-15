"""Guard release workflow safety contracts without pinning step names."""

from __future__ import annotations

import yaml

from tests._paths import REPO_ROOT

_STALE_MODULE = "vibesensor.use_cases.updates.release_validation"
_LIVE_MODULE = "vibesensor.use_cases.updates.releases.release_validation"
_MAIN_RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "main-release.yml"
_WEEKLY_PI_IMAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "weekly-pi-image.yml"


def _load_workflow(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _job_steps(workflow_path, job_name: str) -> list[dict[str, object]]:
    workflow = _load_workflow(workflow_path)
    return [step for step in workflow["jobs"][job_name]["steps"] if isinstance(step, dict)]


def _combined_run_script(steps: list[dict[str, object]]) -> str:
    return "\n".join(str(step.get("run") or "") for step in steps)


def _step_index_containing(steps: list[dict[str, object]], text: str) -> int:
    return next(
        index
        for index, step in enumerate(steps)
        if text in str(step.get("name") or "") or text in str(step.get("run") or "")
    )


def test_main_release_workflow_uses_ci_source_and_release_artifact_contracts() -> None:
    workflow = _load_workflow(_MAIN_RELEASE_WORKFLOW)
    release_job = workflow["jobs"]["release"]
    steps = [step for step in release_job["steps"] if isinstance(step, dict)]
    run_script = _combined_run_script(steps)

    checkout_step = next(step for step in steps if step.get("uses") == "actions/checkout@v6")
    assert checkout_step["with"]["fetch-depth"] == 0
    assert "github.event.workflow_run.head_sha" in checkout_step["with"]["ref"]
    assert 'echo "sha=$(git rev-parse HEAD)"' in run_script

    assert "tools/release/main_release.py compute-version" in run_script
    assert "tools/release/main_release.py build-wheel" in run_script
    assert "tools/tests/run_release_smoke.py" in run_script
    assert "--skip-ui-build" in run_script
    assert "--wheel-path" in run_script

    assert _LIVE_MODULE in run_script
    assert "validate-wheel-metadata" in run_script
    assert "--expected-version" in run_script
    assert "validate-firmware-manifest" in run_script
    assert _STALE_MODULE not in run_script

    assert "tools/release/main_release.py generate-firmware-manifest" in run_script
    assert '--generated-from "${{ steps.release_source.outputs.sha }}"' in run_script
    assert "tools/publish_github_release.py" in run_script
    assert '--target "${{ steps.release_source.outputs.sha }}"' in run_script
    publish_index = run_script.index("tools/publish_github_release.py")
    assert run_script.index("validate-wheel-metadata") < publish_index
    assert run_script.index("validate-firmware-manifest") < publish_index
    assert "tools/release/main_release.py cleanup-releases" in run_script
    assert "WHEEL_ESP_RELEASE_TITLE_PREFIX: Wheel / ESP release" in yaml.safe_dump(release_job)
    assert "GITHUB_SHA" not in run_script
    assert "publish_wiki" not in workflow["jobs"]


def test_manual_release_workflows_require_main_branch_before_publishing() -> None:
    workflow_cases = (
        (_MAIN_RELEASE_WORKFLOW, "release", "Create combined Wheel / ESP release"),
        (_WEEKLY_PI_IMAGE_WORKFLOW, "build-and-release", "Publish weekly Pi image release"),
    )

    for workflow_path, job_name, publish_step_name in workflow_cases:
        steps = _job_steps(workflow_path, job_name)
        guard_index = _step_index_containing(steps, "Manual release workflow runs must use")
        publish_index = _step_index_containing(steps, publish_step_name)
        guard_step = steps[guard_index]

        assert guard_index < publish_index
        assert (
            guard_step["if"]
            == "${{ github.event_name == 'workflow_dispatch' && github.ref != 'refs/heads/main' }}"
        )
        assert "Manual release workflow runs must use the main branch" in guard_step["run"]
        assert "exit 1" in guard_step["run"]
