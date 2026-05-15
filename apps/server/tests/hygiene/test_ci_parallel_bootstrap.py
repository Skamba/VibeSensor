"""Guards for local CI runner bootstrap behavior through the public entrypoint."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from tests._paths import REPO_ROOT

_CI_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_ci_parallel.py"
pytestmark = pytest.mark.dev_tooling


def _load_ci_parallel_module():
    spec = importlib.util.spec_from_file_location("ci_parallel_local_for_tests", _CI_PARALLEL)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CI_PARALLEL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _configure_ui_paths(module, monkeypatch, tmp_path: Path) -> Path:
    ui_dir = tmp_path / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    helper_path = tmp_path / "tools" / "ui" / "ensure_ui_bootstrap.mjs"
    helper_path.parent.mkdir(parents=True, exist_ok=True)
    helper_path.write_text("// helper\n", encoding="utf-8")

    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(module, "UI_DIR", ui_dir)
    monkeypatch.setattr(module, "UI_BOOTSTRAP_HELPER", helper_path)
    return ui_dir


def _stub_ui_bootstrap_check(
    monkeypatch,
    module,
    *,
    needs_npm_ci: bool,
    current_lock_hash: str = "",
    node_modules_exists: bool = True,
) -> None:
    monkeypatch.setattr(
        module.subprocess,
        "check_output",
        lambda command, cwd, text: json.dumps(
            {
                "needs_npm_ci": needs_npm_ci,
                "lock_hash": "lock",
                "current_lock_hash": current_lock_hash,
                "node_modules_exists": node_modules_exists,
            }
        ),
    )


def _install_main_harness(module, monkeypatch, tmp_path: Path, jobs):
    captured: dict[str, object] = {}
    outputs: list[str] = []

    monkeypatch.setattr(module, "_job_steps", lambda _python_cmd: jobs)

    def _fake_run_bootstrap(steps):
        captured["bootstrap_steps"] = steps
        return 0

    def _fake_run_job(name, steps, results):
        results[name] = module.JobResult(
            name=name,
            ok=True,
            failed_step=None,
            return_code=0,
            duration_s=0.0,
            log_path=tmp_path / f"{name}.log",
        )

    monkeypatch.setattr(module, "_run_bootstrap", _fake_run_bootstrap)
    monkeypatch.setattr(module, "_run_job", _fake_run_job)
    monkeypatch.setattr(module, "_emit", outputs.append)
    return captured, outputs


def test_main_uses_shared_ui_bootstrap_helper_when_npm_ci_is_needed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    ui_dir = _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(
        monkeypatch,
        module,
        needs_npm_ci=True,
        node_modules_exists=False,
    )
    ui_step = module.Step("UI lint", ["npm", "run", "lint"], cwd=ui_dir)
    captured, _outputs = _install_main_harness(
        module,
        monkeypatch,
        tmp_path,
        {"frontend-typecheck": [ui_step]},
    )

    assert module.main(["--job", "frontend-typecheck"]) == 0

    assert captured["bootstrap_steps"][-1] == module.Step(
        "ui deps: ensure bootstrap",
        ["node", "../../tools/ui/ensure_ui_bootstrap.mjs"],
        cwd=ui_dir,
    )
    assert captured["bootstrap_steps"][-1].cmd[0] == "node"


def test_main_refuses_skip_bootstrap_when_release_smoke_would_race_ui_jobs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    ui_dir = _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=True)
    release_smoke_step = module.Step(
        "Release smoke validation",
        ["python3", "tools/tests/run_release_smoke.py"],
    )
    ui_step = module.Step("UI lint", ["npm", "run", "lint"], cwd=ui_dir)
    captured, outputs = _install_main_harness(
        module,
        monkeypatch,
        tmp_path,
        {
            "frontend-typecheck": [ui_step],
            "ui-smoke": [ui_step],
            "release-smoke": [release_smoke_step],
        },
    )

    result = module.main(
        [
            "--skip-bootstrap",
            "--job",
            "frontend-typecheck",
            "--job",
            "ui-smoke",
            "--job",
            "release-smoke",
        ]
    )

    assert result == 2
    assert "release-smoke would trigger npm ci inside apps/ui" in "\n".join(outputs)
    assert "bootstrap_steps" not in captured


def test_main_allows_release_smoke_with_skip_ui_build_under_skip_bootstrap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    ui_dir = _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=True)
    release_smoke_step = module.Step(
        "Release smoke validation",
        ["python3", "tools/tests/run_release_smoke.py", "--skip-ui-build"],
    )
    ui_step = module.Step("UI lint", ["npm", "run", "lint"], cwd=ui_dir)
    captured, outputs = _install_main_harness(
        module,
        monkeypatch,
        tmp_path,
        {
            "frontend-typecheck": [ui_step],
            "release-smoke": [release_smoke_step],
        },
    )

    assert (
        module.main(
            [
                "--skip-bootstrap",
                "--job",
                "frontend-typecheck",
                "--job",
                "release-smoke",
            ]
        )
        == 0
    )
    assert "refusing to run shared UI jobs" not in "\n".join(outputs)
    assert captured["bootstrap_steps"] == []


def test_main_skips_ui_bootstrap_step_when_helper_reports_clean_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    ui_dir = _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(
        monkeypatch,
        module,
        needs_npm_ci=False,
        current_lock_hash="lock",
        node_modules_exists=True,
    )
    ui_step = module.Step("UI lint", ["npm", "run", "lint"], cwd=ui_dir)
    captured, _outputs = _install_main_harness(
        module,
        monkeypatch,
        tmp_path,
        {"frontend-typecheck": [ui_step]},
    )

    assert module.main(["--job", "frontend-typecheck"]) == 0

    assert all(step.label != "ui deps: ensure bootstrap" for step in captured["bootstrap_steps"])


def test_main_warns_about_skipped_external_workflow_actions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=False)
    release_smoke_step = module.Step(
        "Release smoke validation",
        ["python3", "tools/tests/run_release_smoke.py"],
    )
    _captured, outputs = _install_main_harness(
        module,
        monkeypatch,
        tmp_path,
        {"release-smoke": [release_smoke_step]},
    )

    assert module.main(["--job", "release-smoke"]) == 0

    output = "\n".join(outputs)
    assert "[ci-local] skipped external workflow actions:" in output
    assert "release-smoke (Download release-smoke UI static artifact)" in output
    assert "actions/download-artifact@" in output
    assert "without --skip-ui-build" in output
    assert "GitHub workflow-only needs not runnable locally" in output
    assert "release-smoke normally needs ui-build-artifact" in output


def test_main_reports_unselected_github_needs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=False)
    _captured, outputs = _install_main_harness(
        module,
        monkeypatch,
        tmp_path,
        {"ui-unit": [module.Step("UI unit tests", ["true"])]},
    )

    assert module.main(["--job", "ui-unit"]) == 0

    output = "\n".join(outputs)
    assert "GitHub needs not selected locally" in output
    assert "ui-unit normally needs frontend-typecheck" in output


def test_main_runs_selected_jobs_after_their_github_needs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=False)
    jobs = {
        "frontend-typecheck": [module.Step("UI typecheck", ["true"])],
        "ui-unit": [module.Step("UI unit tests", ["true"])],
    }
    outputs: list[str] = []
    run_order: list[str] = []

    monkeypatch.setattr(module, "_job_steps", lambda _python_cmd: jobs)
    monkeypatch.setattr(module, "_job_workspace_write_sets", lambda: {name: () for name in jobs})
    monkeypatch.setattr(module, "_run_bootstrap", lambda _steps: 0)
    monkeypatch.setattr(module, "_emit", outputs.append)

    def _fake_run_job(name, _steps, results):
        run_order.append(name)
        results[name] = module.JobResult(
            name=name,
            ok=True,
            failed_step=None,
            return_code=0,
            duration_s=0.0,
            log_path=tmp_path / f"{name}.log",
        )

    monkeypatch.setattr(module, "_run_job", _fake_run_job)

    assert module.main(["--job", "ui-unit", "--job", "frontend-typecheck"]) == 0

    assert run_order == ["frontend-typecheck", "ui-unit"]


def test_main_skips_selected_downstream_job_when_github_need_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=False)
    jobs = {
        "frontend-typecheck": [module.Step("UI typecheck", ["false"])],
        "ui-unit": [module.Step("UI unit tests", ["true"])],
    }
    outputs: list[str] = []
    run_order: list[str] = []

    monkeypatch.setattr(module, "_job_steps", lambda _python_cmd: jobs)
    monkeypatch.setattr(module, "_job_workspace_write_sets", lambda: {name: () for name in jobs})
    monkeypatch.setattr(module, "_run_bootstrap", lambda _steps: 0)
    monkeypatch.setattr(module, "_emit", outputs.append)

    def _fake_run_job(name, _steps, results):
        run_order.append(name)
        results[name] = module.JobResult(
            name=name,
            ok=False,
            failed_step="UI typecheck",
            return_code=1,
            duration_s=0.0,
            log_path=tmp_path / f"{name}.log",
        )

    monkeypatch.setattr(module, "_run_job", _fake_run_job)

    assert module.main(["--job", "frontend-typecheck", "--job", "ui-unit"]) == 1

    output = "\n".join(outputs)
    assert run_order == ["frontend-typecheck"]
    assert "[ui-unit] skip (needed job failed: frontend-typecheck)" in output
    assert "- ui-unit: SKIP (needed job failed: frontend-typecheck)" in output
    assert "frontend-typecheck.log" in output


def test_main_reports_missing_shellcheck_before_running_shell_lint(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    _configure_ui_paths(module, monkeypatch, tmp_path)
    outputs: list[str] = []

    monkeypatch.setattr(
        module,
        "_job_steps",
        lambda _python_cmd: {"shell-lint": [module.Step("ShellCheck", ["make"])]},
    )
    monkeypatch.setattr(module, "_job_workspace_write_sets", lambda: {"shell-lint": ()})
    monkeypatch.setattr(module, "_job_host_tools", lambda: {"shell-lint": ("shellcheck",)})
    monkeypatch.setattr(module.shutil, "which", lambda _tool: None)
    monkeypatch.setattr(
        module,
        "_run_bootstrap",
        lambda _steps: (_ for _ in ()).throw(AssertionError("bootstrap should not run")),
    )
    monkeypatch.setattr(
        module,
        "_run_job",
        lambda _name, _steps, _results: (_ for _ in ()).throw(AssertionError("job should not run")),
    )
    monkeypatch.setattr(module, "_emit", outputs.append)

    assert module.main(["--job", "shell-lint"]) == 2

    output = "\n".join(outputs)
    assert "missing host prerequisites" in output
    assert "shell-lint requires shellcheck" in output
    assert "run the job through ACT" in output


def test_manifest_shell_operator_steps_run_through_bash(tmp_path: Path) -> None:
    module = _load_ci_parallel_module()
    step = module._step_from_manifest_command(
        "shell operators",
        "set -euo pipefail && printf ok",
    )

    assert step.shell is True
    assert step.cmd == ["set -euo pipefail && printf ok"]
    with (tmp_path / "step.log").open("w", encoding="utf-8") as log_file:
        assert module._run_step(step, log_file) == 0

    assert "ok" in (tmp_path / "step.log").read_text(encoding="utf-8")


def test_main_serializes_jobs_with_overlapping_workspace_write_sets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_ci_parallel_module()
    _configure_ui_paths(module, monkeypatch, tmp_path)
    _stub_ui_bootstrap_check(monkeypatch, module, needs_npm_ci=False)
    jobs = {
        "frontend-typecheck": [module.Step("UI typecheck", ["true"])],
        "backend-contract-drift": [module.Step("Contract sync", ["true"])],
    }
    outputs: list[str] = []
    active_jobs = 0
    max_active_jobs = 0
    lock = threading.Lock()

    monkeypatch.setattr(module, "_job_steps", lambda _python_cmd: jobs)
    monkeypatch.setattr(module, "_run_bootstrap", lambda _steps: 0)
    monkeypatch.setattr(module, "_emit", outputs.append)
    monkeypatch.setattr(
        module,
        "_job_workspace_write_sets",
        lambda: {
            "frontend-typecheck": ("ui-generated-contracts",),
            "backend-contract-drift": ("ui-generated-contracts",),
        },
    )

    def _fake_run_job(name, _steps, results):
        nonlocal active_jobs, max_active_jobs
        with lock:
            active_jobs += 1
            max_active_jobs = max(max_active_jobs, active_jobs)
        time.sleep(0.02)
        with lock:
            active_jobs -= 1
        results[name] = module.JobResult(
            name=name,
            ok=True,
            failed_step=None,
            return_code=0,
            duration_s=0.0,
            log_path=tmp_path / f"{name}.log",
        )

    monkeypatch.setattr(module, "_run_job", _fake_run_job)

    assert (
        module.main(
            [
                "--job",
                "frontend-typecheck",
                "--job",
                "backend-contract-drift",
            ]
        )
        == 0
    )

    output = "\n".join(outputs)
    assert "shared workspace write-set serialization" in output
    assert "ui-generated-contracts: frontend-typecheck, backend-contract-drift" in output
    assert "- frontend-typecheck: PASS" in output
    assert "- backend-contract-drift: PASS" in output
    assert max_active_jobs == 1
