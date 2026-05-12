"""Guard backend test shard planning and CLI-visible runner behavior."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from tests._paths import REPO_ROOT

_CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_RUN_BACKEND_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_backend_parallel.py"


def _load_run_backend_parallel_module():
    spec = importlib.util.spec_from_file_location(
        "run_backend_parallel_local_for_tests", _RUN_BACKEND_PARALLEL
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_RUN_BACKEND_PARALLEL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_main_fakes(module, monkeypatch, tmp_path: Path) -> tuple[dict[str, object], list[str]]:
    captured: dict[str, object] = {}
    emitted: list[str] = []

    monkeypatch.setattr(module, "LOG_DIR", tmp_path)
    monkeypatch.setattr(
        module,
        "collect_test_ids",
        lambda _pytest_args: ["apps/server/tests/app/test_app_main.py::test_fast"],
    )
    monkeypatch.setattr(module, "_load_duration_cache", lambda _path: {})
    monkeypatch.setattr(module, "_observed_durations_from_junit", lambda _path, _selected: {})
    monkeypatch.setattr(module, "_emit", emitted.append)

    def _fake_run(cmd: list[str], *, log_path: Path, timeout_s: int) -> int:
        captured["cmd"] = list(cmd)
        captured["log_path"] = log_path
        captured["timeout_s"] = timeout_s
        log_path.write_text("$ fake pytest\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(module, "_run", _fake_run)
    return captured, emitted


def test_assign_shards_uses_cached_durations_by_file() -> None:
    module = _load_run_backend_parallel_module()
    slow_a = "apps/server/tests/integration/test_report_pipeline.py::test_alpha"
    slow_b = "apps/server/tests/integration/test_report_pipeline.py::test_beta"
    fast = "apps/server/tests/app/test_app_main.py::test_fast"

    shards = module._assign_shards_by_duration(
        [fast, slow_a, slow_b],
        2,
        {
            slow_a: 4.0,
            slow_b: 3.0,
            fast: 1.0,
        },
    )

    assert shards[0] == ["apps/server/tests/integration/test_report_pipeline.py"]
    assert shards[1] == ["apps/server/tests/app/test_app_main.py"]


def test_observed_durations_from_junit_matches_selected_test_ids(tmp_path: Path) -> None:
    module = _load_run_backend_parallel_module()
    junit_path = tmp_path / "backend-shard.xml"
    root = ET.Element("testsuite")
    ET.SubElement(
        root,
        "testcase",
        classname="tests.integration.test_report_pipeline",
        name="test_alpha[param]",
        time="4.25",
    )
    ET.SubElement(
        root,
        "testcase",
        classname="tests.app.test_app_main",
        name="test_fast",
        time="1.75",
    )
    ET.ElementTree(root).write(junit_path, encoding="utf-8", xml_declaration=True)

    observed = module._observed_durations_from_junit(
        junit_path,
        [
            "apps/server/tests/integration/test_report_pipeline.py::test_alpha[param]",
            "apps/server/tests/app/test_app_main.py::test_fast",
        ],
    )

    assert observed == {
        "apps/server/tests/integration/test_report_pipeline.py::test_alpha[param]": 4.25,
        "apps/server/tests/app/test_app_main.py::test_fast": 1.75,
    }


def test_main_builds_pytest_command_for_selected_backend_shard(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.delenv(module._XDIST_WORKERS_ENV, raising=False)
    captured, emitted = _install_main_fakes(module, monkeypatch, tmp_path)

    assert module.main([]) == 0

    command = captured["cmd"]
    assert command[:4] == [sys.executable, "-m", "pytest", "-q"]
    assert command[command.index("-n") + 1] == "3"
    assert command[command.index("--junitxml") + 1] == str(tmp_path / "backend-tests-1.xml")
    assert "apps/server/tests/app/test_app_main.py" in command
    assert any("running shard 1/1" in line for line in emitted)


def test_main_reads_xdist_workers_from_env(monkeypatch, tmp_path: Path) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.setenv(module._XDIST_WORKERS_ENV, "5")
    captured, _emitted = _install_main_fakes(module, monkeypatch, tmp_path)

    assert module.main([]) == 0

    assert captured["cmd"][4:6] == ["-n", "5"]


def test_main_cli_overrides_env_xdist_workers(monkeypatch, tmp_path: Path) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.setenv(module._XDIST_WORKERS_ENV, "5")
    captured, _emitted = _install_main_fakes(module, monkeypatch, tmp_path)

    assert module.main(["--xdist-workers", "2"]) == 0

    assert captured["cmd"][4:6] == ["-n", "2"]


def test_main_passes_configured_shard_timeout(monkeypatch, tmp_path: Path) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.setenv(module._SHARD_TIMEOUT_ENV, "17")
    captured, emitted = _install_main_fakes(module, monkeypatch, tmp_path)

    assert module.main([]) == 0

    assert captured["timeout_s"] == 17
    assert any("timeout=17s" in line for line in emitted)


def test_run_times_out_pytest_subprocess(monkeypatch, tmp_path: Path) -> None:
    module = _load_run_backend_parallel_module()
    log_path = tmp_path / "backend-tests.log"

    def _fake_run(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise module.subprocess.TimeoutExpired(
            cmd=["pytest"],
            timeout=5,
            output="partial pytest output\n",
        )

    monkeypatch.setattr(module.subprocess, "run", _fake_run)

    assert module._run(["pytest"], log_path=log_path, timeout_s=5) == 124
    log_text = log_path.read_text(encoding="utf-8")
    assert "partial pytest output" in log_text
    assert "timed out after 5s" in log_text


def test_ci_backend_shard_timeout_leaves_artifact_upload_budget() -> None:
    workflow = yaml.safe_load(_CI_WORKFLOW.read_text(encoding="utf-8"))
    backend_tests = workflow["jobs"]["backend-tests"]
    job_timeout_s = int(backend_tests["timeout-minutes"]) * 60
    shard_step = next(
        step
        for step in backend_tests["steps"]
        if isinstance(step, dict) and step.get("name", "").startswith("Backend tests shard")
    )

    shard_timeout_s = int(shard_step["env"]["VIBESENSOR_BACKEND_SHARD_TIMEOUT_S"])

    assert shard_timeout_s <= job_timeout_s - 60
