"""Guard: workflow-backed CI manifest expands backend shard matrix variants."""

from __future__ import annotations

import importlib.util
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


def test_backend_shard_matrix_expands_to_logical_local_jobs() -> None:
    module = _load_ci_manifest_module()

    backend_shard_jobs = tuple(
        job_name for job_name in module.all_job_names() if job_name.startswith("backend-tests")
    )
    assert backend_shard_jobs == (
        "backend-tests-1",
        "backend-tests-2",
        "backend-tests-3",
        "backend-tests-4",
        "backend-tests-5",
    )


def test_backend_shard_matrix_preserves_shard_specific_commands() -> None:
    module = _load_ci_manifest_module()

    job = module.ci_workflow_jobs()["backend-tests-3"]
    commands = [
        spec.command
        for spec in job.local_runnable_steps("python")
        if spec.label == "Backend tests shard 3/5"
    ]
    assert len(commands) == 1
    assert "env VIBESENSOR_BACKEND_XDIST_WORKERS=3" in commands[0]
    assert "--shards 5" in commands[0]
    assert "--shard-index 3" in commands[0]
    assert "backend-tests-3.xml" in commands[0]


def test_backend_quality_jobs_are_split_into_focused_gates() -> None:
    module = _load_ci_manifest_module()

    job_names = set(module.all_job_names())
    assert "ci-scope" not in job_names
    assert "ui-build-artifact" not in job_names
    assert "backend-quality" not in job_names
    assert {
        "backend-lint",
        "repo-hygiene",
        "backend-static-guards",
        "backend-preflight",
        "docs-lint",
        "backend-contract-drift",
    }.issubset(job_names)


def test_contributing_docs_reference_focused_backend_ci_gates() -> None:
    module = _load_ci_manifest_module()
    job_names = set(module.all_job_names())
    contributing_text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "backend-quality" not in contributing_text
    focused_gate_names = {
        "backend-lint",
        "repo-hygiene",
        "backend-static-guards",
        "backend-preflight",
        "docs-lint",
        "backend-contract-drift",
    }
    assert focused_gate_names.issubset(job_names)
    for gate_name in focused_gate_names:
        assert gate_name in contributing_text
