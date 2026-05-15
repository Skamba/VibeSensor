"""Guard meaningful local-CI manifest contracts without pinning CI topology."""

from __future__ import annotations

import importlib.util
import re
import shlex
import sys

from tests._paths import REPO_ROOT

_CI_MANIFEST = REPO_ROOT / "tools" / "tests" / "ci_workflow_manifest.py"


def _load_ci_manifest_module():
    spec = importlib.util.spec_from_file_location("ci_workflow_manifest_local_test", _CI_MANIFEST)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CI_MANIFEST}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _backend_shard_index(job_name: str) -> int:
    match = re.fullmatch(r"backend-tests-(\d+)", job_name)
    assert match is not None, f"unexpected backend shard job name: {job_name}"
    return int(match.group(1))


def test_backend_shard_matrix_expands_to_runnable_logical_local_jobs() -> None:
    module = _load_ci_manifest_module()

    jobs = module.ci_workflow_jobs()
    backend_shard_jobs = sorted(
        (job_name for job_name in jobs if job_name.startswith("backend-tests-")),
        key=_backend_shard_index,
    )

    assert backend_shard_jobs, "backend shard matrix did not expand for local runner"
    assert [_backend_shard_index(job_name) for job_name in backend_shard_jobs] == list(
        range(1, len(backend_shard_jobs) + 1)
    )
    for job_name in backend_shard_jobs:
        shard_index = _backend_shard_index(job_name)
        commands = [
            shlex.split(spec.command)
            for spec in jobs[job_name].local_runnable_steps("python")
            if "tools/tests/run_backend_parallel.py" in spec.command
        ]
        assert len(commands) == 1
        command = commands[0]
        assert "--shards" in command
        assert command[command.index("--shards") + 1] == str(len(backend_shard_jobs))
        assert "--shard-index" in command
        assert command[command.index("--shard-index") + 1] == str(shard_index)
        assert any(token.endswith(f"backend-tests-{shard_index}.xml") for token in command)


def test_manifest_public_job_sets_exclude_workflow_only_and_expensive_fast_jobs() -> None:
    module = _load_ci_manifest_module()

    all_jobs = set(module.all_job_names())
    fast_jobs = set(module.ci_fast_job_names())
    lite_jobs = set(module.ci_lite_job_names())

    assert {"ci-scope", "ui-build-artifact"}.isdisjoint(all_jobs)
    assert fast_jobs < all_jobs
    assert lite_jobs < all_jobs
    assert not any(job_name.startswith("backend-tests-") for job_name in fast_jobs)
    assert {"ui-unit", "ui-smoke", "release-smoke", "firmware-native-tests", "e2e"}.isdisjoint(
        fast_jobs
    )
    assert "e2e" not in lite_jobs
    assert any(job_name.startswith("backend-tests-") for job_name in lite_jobs)


def test_release_smoke_local_manifest_builds_ui_static_instead_of_downloading_artifact() -> None:
    module = _load_ci_manifest_module()

    job = module.ci_workflow_jobs()["release-smoke"]
    runnable_commands = tuple(spec.command for spec in job.local_runnable_steps("python"))

    assert any("tools/tests/run_release_smoke.py" in command for command in runnable_commands)
    assert all("--skip-ui-build" not in command for command in runnable_commands)
    assert all("ui-static.tar.gz" not in command for command in runnable_commands)
    assert job.workflow_only_needs == ("ui-build-artifact",)


def test_skipped_external_actions_are_explicit_and_substituted() -> None:
    module = _load_ci_manifest_module()

    jobs = module.ci_workflow_jobs()
    release_smoke_downloads = [
        action
        for action in jobs["release-smoke"].skipped_actions
        if action.uses.startswith("actions/download-artifact@")
    ]
    assert len(release_smoke_downloads) == 1
    assert release_smoke_downloads[0].local_substitute
    assert "without --skip-ui-build" in release_smoke_downloads[0].local_substitute

    unsupported_required_artifact_actions = [
        (job_name, action.uses)
        for job_name, job in jobs.items()
        for action in job.skipped_actions
        if (
            action.uses.startswith("actions/download-artifact@")
            or action.uses.startswith("actions/upload-artifact@")
            or action.uses.startswith("actions/cache@")
        )
        and not action.local_substitute
    ]
    assert unsupported_required_artifact_actions == []


def test_common_local_jobs_declare_shared_workspace_write_sets() -> None:
    module = _load_ci_manifest_module()

    jobs = module.ci_workflow_jobs()
    write_sets_by_job = {job_name: set(job.workspace_write_sets) for job_name, job in jobs.items()}
    jobs_by_write_set: dict[str, set[str]] = {}
    for job_name, write_sets in write_sets_by_job.items():
        for write_set in write_sets:
            jobs_by_write_set.setdefault(write_set, set()).add(job_name)

    assert jobs_by_write_set["ui-generated-contracts"] >= {
        "frontend-typecheck",
        "backend-contract-drift",
        "release-smoke",
    }
    assert jobs_by_write_set["ui-test-results"] >= {"ui-unit", "ui-smoke"}
    assert {
        "server-static",
        "server-dist",
        "release-smoke-artifacts",
    }.issubset(write_sets_by_job["release-smoke"])


def test_shell_lint_declares_host_shellcheck_prerequisite() -> None:
    module = _load_ci_manifest_module()

    assert module.ci_workflow_jobs()["shell-lint"].host_tools == ("shellcheck",)


def test_local_needs_reference_manifest_jobs_only() -> None:
    module = _load_ci_manifest_module()

    jobs = module.ci_workflow_jobs()
    unknown_needs = {
        job_name: tuple(need for need in job.needs if need not in jobs)
        for job_name, job in jobs.items()
        if any(need not in jobs for need in job.needs)
    }

    assert unknown_needs == {}
