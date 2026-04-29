"""Guard backend test shard planning and cache observations."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET

from tests._paths import REPO_ROOT

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


def test_observed_durations_from_junit_matches_selected_test_ids(tmp_path) -> None:
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


def test_parse_args_defaults_to_single_shard(monkeypatch) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.delenv(module._XDIST_WORKERS_ENV, raising=False)
    monkeypatch.setattr(module.sys, "argv", ["run_backend_parallel.py"])

    args = module._parse_args()

    assert args.shards == 1
    assert args.shard_index == 1
    assert args.junitxml is None
    assert args.xdist_workers == 3


def test_parse_args_reads_xdist_workers_from_env(monkeypatch) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.setenv(module._XDIST_WORKERS_ENV, "3")
    monkeypatch.setattr(module.sys, "argv", ["run_backend_parallel.py"])

    args = module._parse_args()

    assert args.xdist_workers == 3


def test_parse_args_cli_overrides_env_xdist_workers(monkeypatch) -> None:
    module = _load_run_backend_parallel_module()
    monkeypatch.setenv(module._XDIST_WORKERS_ENV, "3")
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["run_backend_parallel.py", "--xdist-workers", "2"],
    )

    args = module._parse_args()

    assert args.xdist_workers == 2
