"""Guard process-backed e2e shard runner behavior."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from tests._paths import REPO_ROOT

_RUN_E2E_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_e2e_parallel.py"


def _load_run_e2e_parallel_module():
    spec = importlib.util.spec_from_file_location(
        "run_e2e_parallel_local_for_tests", _RUN_E2E_PARALLEL
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_RUN_E2E_PARALLEL}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_build_shard_config_creates_isolated_runtime(monkeypatch, tmp_path: Path) -> None:
    module = _load_run_e2e_parallel_module()
    recorded: dict[str, object] = {}
    shard_root = tmp_path / "shard-root"
    runtime = module.IsolatedRuntimePaths(
        root=shard_root,
        data_dir=shard_root / "data",
        rollback_dir=shard_root / "rollback",
        config_path=shard_root / "shard-2.yaml",
    )

    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda prefix: str(shard_root))
    monkeypatch.setattr(
        module,
        "_track_active_runtime_root",
        lambda path: recorded.setdefault("tracked", path),
    )

    def fake_build_isolated_server_config(
        source_config: Path,
        runtime_root: Path,
        *,
        host: str,
        port: int,
        udp_data_port: int,
        udp_control_port: int,
        config_name: str,
        data_seed_dir: Path | None,
    ):
        recorded["config_call"] = {
            "source_config": source_config,
            "runtime_root": runtime_root,
            "host": host,
            "port": port,
            "udp_data_port": udp_data_port,
            "udp_control_port": udp_control_port,
            "config_name": config_name,
            "data_seed_dir": data_seed_dir,
        }
        return runtime

    monkeypatch.setattr(module, "build_isolated_server_config", fake_build_isolated_server_config)

    config = module._build_shard_config(
        source_config=Path("/tmp/base-config.yaml"),
        shard_index=2,
        shard_count=6,
        tests=["apps/server/tests_e2e/test_sample.py::test_alpha"],
        http_port_base=18020,
        sim_data_port_base=19020,
        sim_control_port_base=19120,
    )

    assert recorded["tracked"] == shard_root
    assert recorded["config_call"] == {
        "source_config": Path("/tmp/base-config.yaml"),
        "runtime_root": shard_root,
        "host": "127.0.0.1",
        "port": 18021,
        "udp_data_port": 19021,
        "udp_control_port": 19121,
        "config_name": "shard-2.yaml",
        "data_seed_dir": module._DEFAULT_DATA_SEED_DIR,
    }
    assert config.http_port == 18021
    assert config.sim_data_port == 19021
    assert config.sim_control_port == 19121
    assert config.sim_client_control_base == 9200
    assert config.runtime == runtime


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
    module._track_active_process("shard-a-server", process_a)
    module._track_active_process("shard-b-pytest", process_b)
    monkeypatch.setattr(
        module,
        "terminate_subprocess",
        lambda process: terminated.append(process),
    )

    module._cleanup_active_processes()

    assert terminated == [process_a, process_b]
    assert module._ACTIVE_PROCESSES == {}


def test_parse_args_defaults_to_six_shards(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    monkeypatch.setattr(module.sys, "argv", ["run_e2e_parallel.py"])

    args = module._parse_args()

    assert args.shards == 6
    assert args.config == module._DEFAULT_BASE_CONFIG
