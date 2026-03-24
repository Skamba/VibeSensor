"""Guard docker-backed e2e image preparation behavior."""

from __future__ import annotations

import importlib.util
import sys
import xml.etree.ElementTree as ET

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


def test_prepare_image_builds_by_default(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    built_images: list[str] = []

    monkeypatch.setattr(module, "_build_image", lambda image: built_images.append(image) or 0)

    assert module._prepare_image("vibesensor-full-suite", env={}) == 0
    assert built_images == ["vibesensor-full-suite"]


def test_prepare_image_reuses_prebuilt_image_when_skip_requested(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    emitted: list[str] = []

    def _unexpected_build(_image: str) -> int:
        raise AssertionError("skip-build mode should not rebuild the docker image")

    monkeypatch.setattr(module, "_build_image", _unexpected_build)
    monkeypatch.setattr(
        module,
        "_docker_image_exists",
        lambda image: image == "vibesensor-full-suite",
    )
    monkeypatch.setattr(module, "_emit", emitted.append)

    assert (
        module._prepare_image(
            "vibesensor-full-suite",
            env={module._SKIP_BUILD_ENV: "true"},
        )
        == 0
    )
    assert any("reusing prebuilt docker image" in line for line in emitted)


def test_prepare_image_reuses_prebuilt_image_in_github_actions(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    emitted: list[str] = []

    def _unexpected_build(_image: str) -> int:
        raise AssertionError("GitHub Actions should reuse the prebuilt docker image")

    monkeypatch.setattr(module, "_build_image", _unexpected_build)
    monkeypatch.setattr(module, "_docker_image_exists", lambda _image: True)
    monkeypatch.setattr(module, "_emit", emitted.append)

    assert module._prepare_image("vibesensor-full-suite", env={"GITHUB_ACTIONS": "true"}) == 0
    assert any("reusing prebuilt docker image" in line for line in emitted)


def test_prepare_image_exits_cleanly_when_skip_requested_but_image_is_missing(
    monkeypatch,
) -> None:
    module = _load_run_e2e_parallel_module()
    emitted: list[str] = []

    def _unexpected_build(_image: str) -> int:
        raise AssertionError("skip-build mode should not rebuild missing images")

    monkeypatch.setattr(module, "_build_image", _unexpected_build)
    monkeypatch.setattr(module, "_docker_image_exists", lambda _image: False)
    monkeypatch.setattr(module, "_emit", emitted.append)

    assert module._prepare_image("missing-image", env={module._SKIP_BUILD_ENV: "1"}) == 2
    assert any("missing-image" in line for line in emitted)


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


def test_observed_durations_from_junit_matches_selected_test_ids(tmp_path) -> None:
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


def test_cleanup_active_containers_removes_tracked_names(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    removed: list[str] = []
    module._ACTIVE_CONTAINERS.clear()
    module._track_active_container("vibesensor-e2e-shard-a")
    module._track_active_container("vibesensor-e2e-shard-b")
    monkeypatch.setattr(module, "_force_remove_container", lambda name: removed.append(name) or 0)

    module._cleanup_active_containers()

    assert removed == ["vibesensor-e2e-shard-a", "vibesensor-e2e-shard-b"]
    assert module._ACTIVE_CONTAINERS == set()


def test_parse_args_defaults_to_six_shards(monkeypatch) -> None:
    module = _load_run_e2e_parallel_module()
    monkeypatch.setattr(module.sys, "argv", ["run_e2e_parallel.py"])

    args = module._parse_args()

    assert args.shards == 6
