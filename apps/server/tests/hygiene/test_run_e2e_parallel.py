"""Guard process-backed e2e shard runner behavior without pinning helper names."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tests._paths import REPO_ROOT

_RUN_E2E_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_e2e_parallel.py"
pytestmark = pytest.mark.dev_tooling


def _load_run_e2e_parallel_module():
    spec = importlib.util.spec_from_file_location(
        "run_e2e_parallel_local_for_tests", _RUN_E2E_PARALLEL
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_RUN_E2E_PARALLEL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _install_main_fakes(
    module,
    monkeypatch,
    tmp_path: Path,
    *,
    collected: list[str] | None = None,
    assigned: list[list[str]] | None = None,
) -> tuple[dict[str, object], list[str]]:
    recorded: dict[str, object] = {}
    emitted: list[str] = []
    runtime_root = tmp_path / "runtime-root"

    monkeypatch.setattr(module, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(module, "_register_cleanup_hooks", lambda: None)
    monkeypatch.setattr(
        module,
        "collect_test_ids",
        lambda _pytest_args: collected or ["apps/server/tests_e2e/test_sample.py::test_alpha"],
    )
    monkeypatch.setattr(module, "_load_duration_cache", lambda _path: {})
    monkeypatch.setattr(module, "_observed_durations_from_junit", lambda _path, _selected: {})
    monkeypatch.setattr(module, "_emit", emitted.append)
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda prefix: str(runtime_root))
    if assigned is not None:
        monkeypatch.setattr(
            module,
            "_assign_shards_by_duration",
            lambda _collected, _min_shards, _durations: assigned,
        )

    def _fake_build_isolated_server_config(
        source_config: Path,
        runtime_root_arg: Path,
        *,
        host: str,
        port: int,
        udp_data_port: int,
        udp_control_port: int,
        config_name: str,
        data_seed_dir: Path | None,
    ):
        runtime_root_arg.mkdir(parents=True, exist_ok=True)
        recorded["config_call"] = {
            "source_config": source_config,
            "runtime_root": runtime_root_arg,
            "host": host,
            "port": port,
            "udp_data_port": udp_data_port,
            "udp_control_port": udp_control_port,
            "config_name": config_name,
            "data_seed_dir": data_seed_dir,
        }
        return module.IsolatedRuntimePaths(
            root=runtime_root_arg,
            data_dir=runtime_root_arg / "data",
            rollback_dir=runtime_root_arg / "rollback",
            config_path=runtime_root_arg / config_name,
        )

    monkeypatch.setattr(module, "build_isolated_server_config", _fake_build_isolated_server_config)
    monkeypatch.setattr(module, "_run_shard_e2e", lambda *, config, marker: 0)
    return recorded, emitted


def test_main_builds_isolated_runtime_for_selected_shard(
    monkeypatch,
    tmp_path: Path,
) -> None:
    module = _load_run_e2e_parallel_module()
    base_config = tmp_path / "base-config.yaml"
    base_config.write_text("server:\n  port: 8000\n", encoding="utf-8")
    recorded, emitted = _install_main_fakes(
        module,
        monkeypatch,
        tmp_path,
        assigned=[["apps/server/tests_e2e/test_sample.py::test_alpha"]],
    )

    assert (
        module.main(
            [
                "--config",
                str(base_config),
                "--shards",
                "1",
                "--http-port-base",
                "18020",
                "--sim-data-port-base",
                "19020",
                "--sim-control-port-base",
                "19120",
            ]
        )
        == 0
    )

    assert recorded["config_call"] == {
        "source_config": base_config.resolve(),
        "runtime_root": tmp_path / "runtime-root",
        "host": "127.0.0.1",
        "port": 18020,
        "udp_data_port": 19020,
        "udp_control_port": 19120,
        "config_name": "shard-1.yaml",
        "data_seed_dir": module._DEFAULT_DATA_SEED_DIR,
    }
    assert any("min requested: 1" in line for line in emitted)


def test_assign_shards_uses_cached_durations() -> None:
    module = _load_run_e2e_parallel_module()
    slow_test = "apps/server/tests_e2e/test_slow.py::test_slow"
    fast_a = "apps/server/tests_e2e/test_fast.py::test_fast_a"
    fast_b = "apps/server/tests_e2e/test_fast.py::test_fast_b"

    shards = module._assign_shards_by_duration(
        [fast_a, slow_test, fast_b],
        2,
        {
            slow_test: module.SLOW_TEST_THRESHOLD + 1.0,
            fast_a: 1.0,
            fast_b: 1.5,
        },
    )

    assert shards[0] == [slow_test]
    assert shards[1] == [fast_b, fast_a]


def test_assign_shards_only_dedicates_tests_above_threshold() -> None:
    module = _load_run_e2e_parallel_module()
    threshold_test = "apps/server/tests_e2e/test_threshold.py::test_threshold"
    above_threshold_test = "apps/server/tests_e2e/test_slow.py::test_slow"
    fast_test = "apps/server/tests_e2e/test_fast.py::test_fast"

    shards = module._assign_shards_by_duration(
        [threshold_test, above_threshold_test, fast_test],
        2,
        {
            threshold_test: module.SLOW_TEST_THRESHOLD,
            above_threshold_test: module.SLOW_TEST_THRESHOLD + 0.1,
            fast_test: 1.0,
        },
    )

    assert shards[0] == [above_threshold_test]
    assert shards[1] == [threshold_test, fast_test]


def test_observed_durations_from_junit_matches_selected_test_ids(tmp_path: Path) -> None:
    module = _load_run_e2e_parallel_module()
    junit_path = tmp_path / "shard.xml"
    root = ET.Element("testsuite")
    ET.SubElement(
        root,
        "testcase",
        classname="tests_e2e.test_sample",
        name="test_alpha[param]",
        time="4.25",
    )
    ET.SubElement(
        root,
        "testcase",
        classname="tests_e2e.test_other",
        name="test_beta",
        time="1.75",
    )
    ET.ElementTree(root).write(junit_path, encoding="utf-8", xml_declaration=True)

    observed = module._observed_durations_from_junit(
        junit_path,
        [
            "apps/server/tests_e2e/test_sample.py::test_alpha[param]",
            "apps/server/tests_e2e/test_other.py::test_beta",
        ],
    )

    assert observed == {
        "apps/server/tests_e2e/test_sample.py::test_alpha[param]": 4.25,
        "apps/server/tests_e2e/test_other.py::test_beta": 1.75,
    }


def test_cleanup_active_processes_terminates_tracked_processes(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    terminated: list[object] = []
    process_a = object()
    process_b = object()
    module._ACTIVE_PROCESSES.clear()
    try:
        module._track_active_process("shard-a-server", process_a)
        module._track_active_process("shard-b-pytest", process_b)
        monkeypatch.setattr(
            module,
            "terminate_subprocess",
            lambda process: terminated.append(process),
        )

        module._cleanup_active_processes()
    finally:
        module._ACTIVE_PROCESSES.clear()

    assert terminated == [process_a, process_b]


def test_main_reports_default_min_shards_and_base_config(monkeypatch, tmp_path: Path) -> None:
    module = _load_run_e2e_parallel_module()
    recorded, emitted = _install_main_fakes(module, monkeypatch, tmp_path)

    assert module.main([]) == 0

    assert recorded["config_call"]["source_config"] == module._DEFAULT_BASE_CONFIG.resolve()
    assert any("min requested: 6" in line for line in emitted)
