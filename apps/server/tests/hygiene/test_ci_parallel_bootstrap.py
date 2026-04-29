"""Guards for local CI runner bootstrap behavior through the public entrypoint."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from tests._paths import REPO_ROOT

_CI_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_ci_parallel.py"


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
